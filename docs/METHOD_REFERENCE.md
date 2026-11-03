# Editable method references

The Methods table supports staff additions and edits to reference information:
parameter labels, program/method names, instruments, units, detection/ranges,
activity types, effective periods, and notes. A source reference and change note
are required. Blank details remain blank; the application does not infer them.

These records are **documentation only**. They do not change `lst_method`, result
values, data-entry parameters, QA thresholds, BACT scoring, or WQX mappings. Adding
a measured parameter to operational workflows still requires engineering review.

## Setup

For an existing, explicitly selected database, apply the additive migration:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/11_method_reference.sql
```

The standard `db/run_schema.sql` includes the same migration for new installations.
No automatic startup migration occurs. Before setup, `/methods` continues to show
the bundled source reference; editing is unavailable. If a database read fails,
the page falls back to that original reference and hides editing controls.

Use the normal database-backup procedure before deploying schema changes. This
migration only creates an empty reference-history table; it does not seed or
rewrite monitoring data. No live setup or deployment is implied by adding it.

## Staff workflow

On Methods, use **Add reference** or **Edit reference**. Keep effective periods
explicit and cite the supporting protocol/document. Save creates a new revision.
Earlier saved versions and change notes are available under **Previous updates**.
The bundled September 9 source remains in version-controlled reference data.
There is no delete action or automatic rollback. Correct an entry by saving a
new revision with an explanation.

Stable content-derived baseline IDs survive reordering. If the bundled source
content is revised in code later, reconcile the corresponding staff override
explicitly: an unmatched saved reference is retained, not silently discarded.

## Protection and limitations

- `READ_ONLY_MODE=true`: editing URLs and submissions return 403.
- `PUBLIC_DEMO_MODE=true`: editing URLs return 404; the public Methods page shows
  only the bundled source, excluding internal staff changes.
- Private read-only mode shows saved references but hides editing controls.
- Existing access restrictions remain in place. This feature does not provide
  authentication or verified editor attribution; history records time and change
  note, not an authenticated identity. Writable use requires appropriate private
  access controls.
- Signed, two-hour editing forms reject invalid tokens. A stable `SECRET_KEY`
  environment value supports multiple workers; without it, a process-local random
  key safely invalidates forms on restart and is suitable only for one worker.
- Revision checks and a transaction-scoped advisory lock reject stale saves with
  409. Staff must open a new form and review current values; there is no force-save.
- Only explicitly submitted forms write reference history. GET requests are SELECT
  only; table creation is never attempted in request handlers.

## Checks

```sh
python -m pytest -q dashboard/test_method_editing.py dashboard/test_methods_page.py
```

The isolated integration verification also exercises PostgreSQL JSON storage,
Unicode units, idempotent setup, and concurrent saves without using monitoring data.
