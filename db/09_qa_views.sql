-- QA views and helper logic (meter failure windows, exceedance flags)
-- DataDictionary: water temp must not exceed 31 C; nitrate drinking standard 10 ppm.

-- View: chemical rows with meter that failed test within 30 days after sample (flag candidate)
CREATE OR REPLACE VIEW v_chemical_meter_qa AS
SELECT c.chemical_id, c.visit_id, v.sample_date, v.equipment_id,
       mt.meter_testing_id, mt.pass_fail, mt.parameter_type
FROM chemical c
JOIN visit v ON v.visit_id = c.visit_id
LEFT JOIN meter_testing mt ON mt.equipment_id = v.equipment_id
  AND mt.pass_fail IN ('F', 'F1', 'F2', 'F3', 'Fail', 'C-F')
  AND mt.session_id IN (SELECT session_id FROM session s WHERE s.date_start IS NOT NULL)
  AND EXISTS (
    SELECT 1 FROM session s2
    WHERE s2.session_id = mt.session_id
      AND s2.date_start <= v.sample_date + INTERVAL '30 days'
      AND (s2.date_end IS NULL OR s2.date_end >= v.sample_date - INTERVAL '7 days')
  )
WHERE v.equipment_id IS NOT NULL;

-- View: chemical exceedances (regulatory thresholds)
CREATE OR REPLACE VIEW v_chemical_exceedances AS
SELECT c.chemical_id, c.visit_id, 'water_temp_31c' AS exceedance_type, c.water_temp_c AS value
FROM chemical c
WHERE c.water_temp_c > 31
UNION ALL
SELECT c.chemical_id, c.visit_id, 'nitrate_10ppm', c.nitrate_ug_l / 1000.0
FROM chemical c
WHERE c.nitrate_ug_l IS NOT NULL AND c.nitrate_ug_l > 10000;
