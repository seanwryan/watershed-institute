-- Keep the workbook's Data Condition text exactly as written.
--
-- data_condition_id holds one code. The All StreamWatch Data workbook also uses
-- combined conditions such as "Outlier; Incomplete" (1,228 rows, 47 combinations),
-- which have no single code, so they were stored as blank. This column keeps the
-- source text; the app shows it whenever data_condition_id is empty.
-- Additive and safe to re-run.

ALTER TABLE chemical           ADD COLUMN IF NOT EXISTS source_data_condition TEXT;
ALTER TABLE bacteria           ADD COLUMN IF NOT EXISTS source_data_condition TEXT;
ALTER TABLE macro_analysis     ADD COLUMN IF NOT EXISTS source_data_condition TEXT;
ALTER TABLE habitat_assessment ADD COLUMN IF NOT EXISTS source_data_condition TEXT;

COMMENT ON COLUMN chemical.source_data_condition IS
  'Data Condition text from the source workbook when it is not a single code (e.g. "Outlier; Incomplete").';
COMMENT ON COLUMN bacteria.source_data_condition IS
  'Data Condition text from the source workbook when it is not a single code.';
COMMENT ON COLUMN macro_analysis.source_data_condition IS
  'Data Condition text from the source workbook when it is not a single code.';
COMMENT ON COLUMN habitat_assessment.source_data_condition IS
  'Data Condition text from the source workbook when it is not a single code.';
