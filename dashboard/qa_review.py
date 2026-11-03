"""Read-only, record-linked QA investigation queries. No review decisions or writes."""
from datetime import date
from dashboard.report_queries import REPORT_CHEM_FIELDS, _fmt_result_value

PARAMETERS = [(key, label, 'Unresolved' if key == 'nitrate_ug_l' else unit)
              for key, label, unit in REPORT_CHEM_FIELDS] + [
    ('e_coli_mpn_100ml', 'E. coli', 'MPN/100mL'),
    ('total_coliform_mpn', 'Total coliform', 'MPN/100mL'),
]
PARAMETER_META = {key: (label, unit) for key, label, unit in PARAMETERS}
PAGE_SIZE = 100


def parse_filters(args):
    filters = {k: (args.get(k) or '').strip() for k in
               ('site_code', 'date_start', 'date_end', 'parameter', 'flag_type', 'condition')}
    for name in ('date_start', 'date_end'):
        if filters[name]:
            try:
                filters[name] = date.fromisoformat(filters[name]).isoformat()
            except ValueError:
                raise ValueError('Enter valid From and To dates.') from None
    if filters['date_start'] and filters['date_end'] and filters['date_start'] > filters['date_end']:
        raise ValueError('From must be on or before To.')
    if filters['parameter'] and filters['parameter'] not in PARAMETER_META:
        raise ValueError('Choose a listed parameter.')
    try:
        page = int(args.get('page', 1))
        if not 1 <= page <= 100000:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Choose a valid results page.') from None
    return filters, page


def _query(filters):
    # SQL identifiers come exclusively from the existing report parameter allowlist.
    chem_values = ', '.join("'%s', c.%s" % (k, k) for k, _, _ in REPORT_CHEM_FIELDS)
    clauses, params = ['TRUE'], []
    for name, clause in (
        ('site_code', 's.site_code = %s'), ('date_start', 'v.sample_date >= %s::date'),
        ('date_end', 'v.sample_date <= %s::date'), ('parameter', 'm.key = %s'),
    ):
        if filters.get(name):
            clauses.append(clause); params.append(filters[name])
    if filters.get('condition') == '__none__':
        clauses.append('r.data_condition_id IS NULL')
    elif filters.get('condition'):
        clauses.append('dc.code = %s'); params.append(filters['condition'])
    if filters.get('flag_type') == '__none__':
        clauses.append("NOT EXISTS (SELECT 1 FROM result_flag rf WHERE rf.result_table=r.family AND rf.result_pk=r.record_id)")
    elif filters.get('flag_type') == '__any__':
        clauses.append("EXISTS (SELECT 1 FROM result_flag rf WHERE rf.result_table=r.family AND rf.result_pk=r.record_id)")
    elif filters.get('flag_type'):
        clauses.append("""EXISTS (SELECT 1 FROM result_flag rf JOIN flag_type ft USING (flag_type_id)
                       WHERE rf.result_table=r.family AND rf.result_pk=r.record_id AND ft.code=%s)""")
        params.append(filters['flag_type'])
    sql = f"""WITH records AS (
        SELECT 'chemical'::text family, c.chemical_id record_id, c.visit_id,
               c.data_condition_id, c.detection_limit_note, lm.name method,
               jsonb_strip_nulls(jsonb_build_object({chem_values})) measurements,
               false holding_time_flag, false holding_temp_flag
        FROM chemical c LEFT JOIN lst_method lm ON lm.method_id=c.method_id
        UNION ALL
        SELECT 'bacteria', b.bacteria_id, b.visit_id, b.data_condition_id,
               b.detection_limit_note, NULL::text,
               jsonb_strip_nulls(jsonb_build_object('e_coli_mpn_100ml', b.e_coli_mpn_100ml,
                                                  'total_coliform_mpn', b.total_coliform_mpn)),
               b.holding_time_flag, b.holding_temp_flag FROM bacteria b
    ), matched AS (
        SELECT r.family, r.record_id, v.visit_id, s.site_code, v.sample_date::text,
               v.sample_code, r.method, dc.code condition, m.key parameter,
               m.value #>> '{{}}' value, r.detection_limit_note, v.notes visit_notes,
               r.holding_time_flag, r.holding_temp_flag
        FROM records r JOIN visit v ON v.visit_id=r.visit_id
        JOIN site s ON s.site_id=v.site_id LEFT JOIN data_condition dc USING (data_condition_id)
        LEFT JOIN LATERAL jsonb_each(r.measurements) m ON true
        WHERE {' AND '.join(clauses)}
    ) """
    return sql, params


def review_rows(cur, filters, page=1, export=False):
    sql, params = _query(filters)
    total = None
    if not export:
        cur.execute(sql + 'SELECT count(*) FROM matched', params)
        total = cur.fetchone()[0]
    cur.execute(sql + """SELECT m.*, COALESCE(f.flags, '[]'::jsonb) flags
        FROM matched m LEFT JOIN (
            SELECT rf.result_table, rf.result_pk,
                   jsonb_agg(jsonb_build_object('code', ft.code, 'description', ft.description, 'notes', rf.notes)
                             ORDER BY ft.code, rf.result_flag_id) flags
            FROM result_flag rf JOIN flag_type ft USING (flag_type_id)
            GROUP BY rf.result_table, rf.result_pk
        ) f ON f.result_table=m.family AND f.result_pk=m.record_id
        ORDER BY sample_date DESC, site_code, family, record_id, parameter NULLS LAST
        """ + ('' if export else 'LIMIT %s OFFSET %s'),
        params if export else params + [PAGE_SIZE, (page - 1) * PAGE_SIZE])
    columns = [d[0] for d in cur.description]
    rows = []
    for values in cur.fetchall():
        row = dict(zip(columns, values))
        label, unit = PARAMETER_META.get(row['parameter'], ('No stored measurements', ''))
        row.update(parameter_label=label, unit=unit)
        if not export:
            row.update(value_display=_fmt_result_value(row['value']),
                       record_label=('Chemistry package ' if row['family'] == 'chemical' else 'Bacteria record ') + str(row['record_id']),
                       detail_url='/visits/%s#%s-%s' % (row['visit_id'], row['family'], row['record_id']))
        rows.append(row)
    return rows, len(rows) if export else total


def csv_cells(rows):
    """Protect free-text spreadsheet cells without changing stored/source text."""
    def safe(value):
        if value is None:
            return ''
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        return value
    for r in rows:
        flags = '; '.join(f['code'] for f in r['flags'])
        notes = '; '.join((f['code'] + ': ' + (f['notes'] or '')) for f in r['flags'])
        values = [r['site_code'], r['sample_date'], r['sample_code'], r['visit_id'], r['family'], r['record_id'],
                  r['method'], r['parameter_label'], r['value'], r['unit'], r['condition'], flags, notes,
                  r['detection_limit_note'], r['visit_notes'], r['holding_time_flag'], r['holding_temp_flag']]
        # Only free-text columns need formula protection. Numeric result text comes
        # directly from PostgreSQL numeric fields: retain precision and negatives.
        # The other columns are typed IDs/dates/booleans or code-owned labels/units.
        for index in (0, 2, 6, 10, 11, 12, 13, 14):
            values[index] = safe(values[index])
        yield values
