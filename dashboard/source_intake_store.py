"""Transactional source ledger. Never writes monitoring, person, or equipment tables."""
from uuid import uuid4
from psycopg2.extras import Json, execute_values


def ready(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('source_import'), to_regclass('source_observation'), to_regclass('source_review')")
        return all(cur.fetchone())


def save(conn, parsed, workbook):
    """Same original bytes produce one batch, including concurrent submissions."""
    with conn:
        with conn.cursor() as cur:
            batch = str(uuid4())
            summary = {k: v for k, v in parsed.items() if k != 'rows'}
            cur.execute("""INSERT INTO source_import(import_id, filename, sha256, parser_version, original_workbook, summary)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (sha256) DO NOTHING RETURNING import_id""",
                (batch, parsed['filename'], parsed['sha256'], parsed['parser_version'], workbook, Json(summary)))
            result = cur.fetchone()
            if result is None:
                cur.execute("SELECT import_id FROM source_import WHERE sha256 = %s", (parsed['sha256'],))
                return str(cur.fetchone()[0]), False
            execute_values(cur, "INSERT INTO source_observation(import_id,sheet,source_row,source) VALUES %s",
                           [(batch, row['sheet'], row['source_row'], Json(row)) for row in parsed['rows']])
            return batch, True


def batches(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT import_id::text, filename, created_at, summary FROM source_import ORDER BY created_at DESC LIMIT 50")
        return [{'id': r[0], 'filename': r[1], 'created_at': r[2], 'summary': r[3]} for r in cur.fetchall()]


def batch(conn, batch_id, sheet='', decision='', page=1):
    with conn.cursor() as cur:
        cur.execute("SELECT filename, sha256, created_at, summary FROM source_import WHERE import_id=%s", (batch_id,))
        found = cur.fetchone()
        if not found:
            return None
        result = dict(zip(('filename','sha256','created_at','summary'),found))
        join = """FROM source_observation o LEFT JOIN LATERAL
             (SELECT revision,decision,reviewer,reason,created_at FROM source_review
              WHERE observation_id=o.observation_id ORDER BY revision DESC LIMIT 1) r ON true
             WHERE o.import_id=%s AND (%s='' OR o.sheet=%s)
               AND (%s='' OR COALESCE(r.decision,'pending')=%s)"""
        params=(batch_id,sheet,sheet,decision,decision)
        cur.execute('SELECT COUNT(*) '+join, params)
        result['total']=cur.fetchone()[0]
        cur.execute('SELECT o.observation_id,o.source,r.revision,r.decision,r.reviewer,r.reason '+join+
                    ' ORDER BY o.observation_id LIMIT 50 OFFSET %s', params+((page-1)*50,))
        result['rows']=[{'id':r[0],**r[1],'revision':r[2] or 0,'decision':r[3] or 'pending','reviewer':r[4],'reason':r[5]} for r in cur.fetchall()]
        cur.execute("""SELECT COALESCE(r.decision,'pending'),COUNT(*) FROM source_observation o LEFT JOIN LATERAL
            (SELECT decision FROM source_review WHERE observation_id=o.observation_id ORDER BY revision DESC LIMIT 1) r ON true
            WHERE o.import_id=%s GROUP BY 1""", (batch_id,))
        result['decisions']=dict(cur.fetchall())
        if result['rows']:
            cur.execute("SELECT observation_id,revision,decision,reviewer,reason,created_at FROM source_review WHERE observation_id=ANY(%s) ORDER BY revision DESC", ([row['id'] for row in result['rows']],))
            events={row['id']:[] for row in result['rows']}
            for event in cur.fetchall():
                events[event[0]].append(dict(zip(('revision','decision','reviewer','reason','created_at'),event[1:])))
            for row in result['rows']:
                row['history']=events[row['id']]
        return result


def review(conn, batch_id, observation_id, expected, decision, reviewer, reason):
    if decision not in ('reviewed','hold') or not 1 <= len(reviewer.strip()) <= 120 or not 1 <= len(reason.strip()) <= 2000:
        raise ValueError('Choose a decision and enter your name and a reason (up to 2,000 characters).')
    with conn:
        with conn.cursor() as cur:
            cur.execute('SELECT observation_id FROM source_observation WHERE import_id=%s AND observation_id=%s FOR UPDATE', (batch_id,observation_id))
            if not cur.fetchone():
                raise ValueError('That source record was not found in this batch.')
            cur.execute('SELECT COALESCE(MAX(revision),0) FROM source_review WHERE observation_id=%s',(observation_id,))
            revision=cur.fetchone()[0]
            if revision != expected:
                raise ValueError('Someone reviewed this record after you opened it. Reload before deciding.')
            cur.execute('INSERT INTO source_review(observation_id,revision,decision,reviewer,reason) VALUES (%s,%s,%s,%s,%s)',
                        (observation_id,revision+1,decision,reviewer.strip(),reason.strip()))
