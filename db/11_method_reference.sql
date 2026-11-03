-- Additive reference-only storage. Does not change methods attached to results,
-- QA, exports, scoring, units, or parameter availability in data-entry forms.
BEGIN;
CREATE TABLE IF NOT EXISTS method_reference_revision (
    reference_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    fields JSONB NOT NULL CHECK (jsonb_typeof(fields) = 'object'),
    source_reference TEXT NOT NULL CHECK (length(trim(source_reference)) > 0),
    change_note TEXT NOT NULL CHECK (length(trim(change_note)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (reference_id, revision)
);
COMMIT;
