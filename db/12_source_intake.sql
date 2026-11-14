-- Additive source ledger: does not alter historical results or calculate scores.
BEGIN;
CREATE TABLE IF NOT EXISTS source_import (
    import_id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL UNIQUE,
    parser_version TEXT NOT NULL,
    original_workbook BYTEA NOT NULL,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS source_observation (
    observation_id BIGSERIAL PRIMARY KEY,
    import_id UUID NOT NULL REFERENCES source_import(import_id) ON DELETE RESTRICT,
    sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL CHECK (source_row > 0),
    source JSONB NOT NULL,
    UNIQUE(import_id, sheet, source_row)
);
-- Append-only decisions, with optimistic concurrency per observation.
-- A reviewer label is self-reported; this app does not provide staff authentication.
CREATE TABLE IF NOT EXISTS source_review (
    observation_id BIGINT NOT NULL REFERENCES source_observation(observation_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision > 0),
    decision TEXT NOT NULL CHECK (decision IN ('reviewed', 'hold')),
    reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) BETWEEN 1 AND 120),
    reason TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 2000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(observation_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_source_observation_import ON source_observation(import_id, observation_id);
COMMIT;
