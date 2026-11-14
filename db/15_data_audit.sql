-- Data audit: evidence that the database is a faithful, fully accounted-for
-- version of Watershed's source files. Filled by etl/audit_sources.py (run
-- locally, where the source workbooks are) and shown at /qa/audit.
-- Additive and safe to re-run.

-- One reconciliation run.
CREATE TABLE IF NOT EXISTS audit_run (
  run_id      SERIAL PRIMARY KEY,
  run_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  summary     JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Source count vs database count, per source sheet and item.
CREATE TABLE IF NOT EXISTS audit_check (
  run_id        INT NOT NULL REFERENCES audit_run(run_id) ON DELETE CASCADE,
  sort_order    INT NOT NULL,
  source        TEXT NOT NULL,
  sheet         TEXT,
  item          TEXT NOT NULL,
  source_count  INT,
  db_count      INT,
  status        TEXT NOT NULL CHECK (status IN ('match', 'explained', 'gap', 'info')),
  explanation   TEXT,
  PRIMARY KEY (run_id, sort_order)
);

-- What happened to every row of All StreamWatch Data (ALL DATA), for tracing.
-- Holds measurement values only (no personal information). Only the latest
-- run's rows are kept.
CREATE TABLE IF NOT EXISTS audit_source_row (
  run_id       INT NOT NULL REFERENCES audit_run(run_id) ON DELETE CASCADE,
  source       TEXT NOT NULL,
  row_number   INT NOT NULL,
  site_code    TEXT,
  sample_date  DATE,
  method       TEXT,
  outcome      TEXT NOT NULL,
  detail       JSONB NOT NULL DEFAULT '{}'::jsonb,
  visit_id     INT,
  chemical_id  INT,
  bacteria_id  INT,
  PRIMARY KEY (run_id, source, row_number)
);
CREATE INDEX IF NOT EXISTS idx_audit_source_row_lookup ON audit_source_row (site_code, sample_date);

-- Every transformation applied to the data, in plain words.
CREATE TABLE IF NOT EXISTS audit_change_log (
  change_id    SERIAL PRIMARY KEY,
  applied_on   DATE NOT NULL,
  area         TEXT NOT NULL,
  title        TEXT NOT NULL,
  rule         TEXT NOT NULL,
  rows_affected INT,
  script       TEXT,
  UNIQUE (applied_on, title)
);

INSERT INTO audit_change_log (applied_on, area, title, rule, rows_affected, script) VALUES
 ('2026-09-10', 'Load', 'Historical results loaded from All StreamWatch Data',
  'Each ALL DATA row with values became chemistry and/or E. coli results on a visit; exact duplicate rows were loaded once.', 20524, 'etl/migrate_streamwatch_data.py'),
 ('2026-09-10', 'Load', 'Chloride kept as recorded',
  'The workbook''s chloride values were already corrected for the 2026 standards error, so nothing was divided by 10 again.', NULL, 'etl/all_data_workbook.py'),
 ('2026-09-10', 'Load', 'Nitrate kept in mg/L as N',
  'Workbook nitrate (mg/L as N) is stored unchanged; the column name nitrate_ug_l is historical.', NULL, 'etl/all_data_workbook.py'),
 ('2026-09-10', 'Storage', 'Temperatures stored to 0.01 °C',
  'Temperature columns hold two decimals; 188 workbook readings with more digits (e.g. 12.002) were rounded. Largest difference 0.005 °C.', 188, 'db/06_results.sql'),
 ('2026-11-14', 'Fix', 'BAT bug visits tagged as BAT',
  'Visits holding bug results had no method; they were tagged BAT, and one duplicate same-day visit (SB1 2021-10-02) was merged.', 108, 'etl/fix_bat_visit_links.py'),
 ('2026-11-14', 'Fix', 'Results moved to the visit for their own program',
  'Same-day rows from different teams had been merged into one visit. Each result now sits on the visit for its own method; no values changed.', 432, 'etl/fill_master_gaps.py'),
 ('2026-11-14', 'Load', 'Sites added from the master SITES sheet',
  'CANAL, CH2, DP1, DR1, LSC2, PLD, SB10 were added (ELY matched existing Ely) and their 63 results loaded.', 7, 'etl/fill_master_gaps.py'),
 ('2026-11-14', 'Load', 'Bug-index scores from All StreamWatch Data',
  '611 NJIS/HGMI/CPMI scores added for 1996–2025; 105 scores from an unvalidated calculation were replaced with the workbook''s reviewed values.', 716, 'etl/fill_master_gaps.py'),
 ('2026-11-14', 'Load', 'Notes attached to visits',
  'The ALL DATA Notes column (previously not loaded) was attached to each row''s visit.', 1926, 'etl/fill_master_gaps.py'),
 ('2026-11-14', 'Load', 'Habitat assessments loaded',
  'RBP habitat scores from the BAT habitat form export (57) and ALL DATA (1) attached to matching BAT visits.', 58, 'etl/load_bat_habitat.py'),
 ('2026-11-14', 'Load', 'Site details filled from the SITES sheet',
  'Towns (173 links), drainage area (111, converted from square miles to km²), habitat type and subwatersheds; only blanks were filled.', 114, 'etl/fill_site_details.py'),
 ('2026-11-14', 'Derive', 'Bug-score ratings',
  'Excellent/Good/Fair/Poor from the 2026 Assessment Framework bands; scores outside the scale or in a band gap are left unrated.', 655, 'etl/rate_bio_scores.py'),
 ('2026-11-14', 'Load', 'Combined Data Conditions kept as written',
  'Conditions like "Outlier; Incomplete" have no single code; the workbook text is kept so no result loses its condition.', 1322, 'etl/backfill_source_conditions.py'),
 ('2026-11-14', 'Fix', 'Data Conditions restored after QA overwrite',
  'The old QA script replaced the condition with "Flagged" on results over 31 °C; the workbook conditions were put back. QA now only adds flags.', 18, 'etl/restore_qa_overwritten_conditions.py'),
 ('2026-11-14', 'Derive', 'Nitrate drinking-water flags',
  'Results over 10 mg/L nitrate get an Exceedance flag (the check had compared against 10,000 and never fired).', 18, 'etl/apply_qa_rules.py'),
 ('2026-11-14', 'Fix', 'Old sites marked inactive',
  'Sites added from the workbook that were last sampled before 2021 are inactive, matching existing sites.', 5, 'etl/fill_master_gaps.py'),
 ('2026-11-14', 'Load', 'Meter sensors loaded',
  'DO, pH and EC sensor-change dates from the meter tracking Sensors sheet (the loader had misread its headings).', 75, 'etl/load_meter_sensors.py'),
 ('2026-11-14', 'Fix', 'Survey123 fill-in removed',
  'The 2025 Survey123 enrichment had filled a water temperature (27.0) into CB3 2025-06-29''s "Duplicate; Incomplete" row, where the workbook is blank; restored. The only stored value that differed from the workbook.', 1, 'etl/fix_audit_findings.py'),
 ('2026-11-14', 'Load', 'More habitat forms matched',
  'Six habitat forms whose BAT visit didn''t exist before today''s bug-score load now attach to it.', 6, 'etl/load_bat_habitat.py')
ON CONFLICT (applied_on, title) DO NOTHING;
