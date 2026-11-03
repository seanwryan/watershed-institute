"""Editable reference records, isolated from result lookups and scientific logic."""
import hashlib
import json

from dashboard.methods_reference import METHOD_ROWS, SOURCE_LINE

FIELDS = {
    "parameter": "Parameter / data type", "program": "Program / method",
    "field_lab": "Field / lab", "activity_type": "WQX activity type",
    "units": "Units", "limit": "Detection / range", "equipment": "Equipment / method",
    "effective_period": "Effective period", "notes": "Notes",
}


def baseline_rows():
    rows = []
    for original in METHOD_ROWS:
        # Content-derived identities survive reordering of the source reference.
        key = "source-" + hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()[:24]
        rows.append(dict(original, reference_id=key, revision=0, source_reference=SOURCE_LINE))
    return rows


def read_rows(conn):
    """Read current revisions; callers may fall back to the source on missing setup."""
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (reference_id) reference_id, revision, fields, source_reference
                       FROM method_reference_revision ORDER BY reference_id, revision DESC""")
        saved = cur.fetchall()
    rows = {row["reference_id"]: row for row in baseline_rows()}
    for key, revision, fields, source in saved:
        rows[key] = dict(fields, reference_id=key, revision=revision, source_reference=source)
    return list(rows.values())


def validate_form(form):
    fields = {name: (form.get(name) or "").strip() for name in FIELDS}
    source = (form.get("source_reference") or "").strip()
    note = (form.get("change_note") or "").strip()
    if not fields["parameter"] or not fields["program"] or not source or not note:
        return fields, source, note, "Enter a parameter, program / method, source reference, and change note."
    if any(len(value) > 4000 for value in [*fields.values(), source, note]):
        return fields, source, note, "Keep each field under 4,000 characters."
    return fields, source, note, None


def save_revision(conn, key, expected_revision, fields, source, note):
    """Append history with optimistic concurrency; never edit a stored result."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("method-reference:" + key,))
        cur.execute("SELECT COALESCE(MAX(revision), 0) FROM method_reference_revision WHERE reference_id = %s", (key,))
        if cur.fetchone()[0] != expected_revision:
            return False
        cur.execute("""INSERT INTO method_reference_revision
                       (reference_id, revision, fields, source_reference, change_note)
                       VALUES (%s, %s, %s::jsonb, %s, %s)""",
                    (key, expected_revision + 1, json.dumps(fields), source, note))
    return True
