-- Seed data_condition and flag_type from DataDictionary / 2025 Data Questions

INSERT INTO data_condition (code, description, domain) VALUES
  ('Accepted', 'Reviewed, meets QA standards', 'quality_status'),
  ('Corrected', 'Issues identified and fixed', 'quality_status'),
  ('Flagged', 'Flagged for review', 'issues_anomalies'),
  ('Minor_Deviation', 'Minor deviation from protocol', 'issues_anomalies'),
  ('Moderate_Deviation', 'Moderate deviation', 'issues_anomalies'),
  ('Site_Conflict', 'Site conflict', 'issues_anomalies'),
  ('Duplicate', 'Duplicate record', 'issues_anomalies'),
  ('Incomplete', 'Incomplete data', 'issues_anomalies'),
  ('Erroneous', 'Known error', 'issues_anomalies'),
  ('Provisional', 'Not yet verified', 'quality_status'),
  ('Unchecked', 'Not yet reviewed', 'quality_status'),
  ('Validated', 'Validated', 'quality_status'),
  ('Approved', 'Approved for use', 'quality_status'),
  ('Certified', 'Certified', 'quality_status'),
  ('Derived', 'Derived value', 'processing_modifiers'),
  ('Estimated', 'Estimated value', 'processing_modifiers'),
  ('Adjusted', 'Adjusted value', 'processing_modifiers'),
  ('Suppressed', 'Suppressed', 'processing_modifiers')
ON CONFLICT (code) DO NOTHING;

-- flag_type for result-level flags (subset; expand as needed)
INSERT INTO flag_type (code, description, domain) VALUES
  ('Suspect', 'Suspected issue', 'issues_anomalies'),
  ('Outlier', 'Statistical outlier', 'issues_anomalies'),
  ('Known_Issue', 'Known issue', 'issues_anomalies'),
  ('Meter_Failed_Test', 'Meter failed calibration/test', 'issues_anomalies'),
  ('Exceedance', 'Exceeds regulatory threshold', 'issues_anomalies')
ON CONFLICT (code) DO NOTHING;

-- Seed lst_priority for CAT/BAT/BACT
INSERT INTO lst_priority (label, sort_order) VALUES
  ('1 – Primary', 1),
  ('2 – Secondary', 2),
  ('3 – Tertiary', 3)
ON CONFLICT (label) DO NOTHING;

-- Seed lst_groundtruthing_status
INSERT INTO lst_groundtruthing_status (label) VALUES
  ('Done'),
  ('Pending'),
  ('Not Started')
ON CONFLICT (label) DO NOTHING;

-- Seed lst_method
INSERT INTO lst_method (name) VALUES
  ('BACT'),
  ('BAT'),
  ('LaMotte'),
  ('Hanna'),
  ('Survey123'),
  ('Gallery')
ON CONFLICT (name) DO NOTHING;

-- Seed lst_session_type
INSERT INTO lst_session_type (name) VALUES
  ('Quarterly maintenance'),
  ('Thermometer calibration'),
  ('Troubleshooting')
ON CONFLICT (name) DO NOTHING;

-- Seed lst_training_type
INSERT INTO lst_training_type (name) VALUES
  ('BACT Online Module'),
  ('BAT Accreditation'),
  ('CAT Training')
ON CONFLICT (name) DO NOTHING;

-- Seed lst_role
INSERT INTO lst_role (name) VALUES
  ('CAT'),
  ('BAT'),
  ('BACT')
ON CONFLICT (name) DO NOTHING;
