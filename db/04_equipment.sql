-- StreamWatch: Equipment and QA tables (from EQUIPMENT schema doc)

CREATE TABLE IF NOT EXISTS equipment (
  equipment_id    SERIAL PRIMARY KEY,
  equipment_code  TEXT NOT NULL UNIQUE,  -- e.g. TWI001
  equipment_type  TEXT NOT NULL,          -- Multiparameter meter, Alcohol thermometer, etc.
  manufacturer    TEXT,
  model           TEXT,
  serial_number   TEXT,
  status         equipment_status_enum NOT NULL DEFAULT 'Active',
  date_acquired   DATE,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sensor (
  sensor_id       SERIAL PRIMARY KEY,
  equipment_id    INT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  sensor_type     sensor_type_enum NOT NULL,
  serial_number   TEXT,
  date_installed  DATE,
  date_retired    DATE,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sensor_equipment ON sensor(equipment_id);

CREATE TABLE IF NOT EXISTS session (
  session_id    SERIAL PRIMARY KEY,
  session_type_id INT REFERENCES lst_session_type(session_type_id) ON DELETE SET NULL,
  date_start    DATE,
  date_end      DATE,
  staff         TEXT,
  summary       TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS equipment_loans (
  loan_id        SERIAL PRIMARY KEY,
  equipment_id   INT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  volunteer_id   INT NOT NULL REFERENCES volunteer(volunteer_id) ON DELETE CASCADE,
  date_assigned  DATE NOT NULL,
  date_returned  DATE,
  condition_out TEXT,
  condition_in   TEXT,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_equipment_loans_equipment ON equipment_loans(equipment_id);
CREATE INDEX IF NOT EXISTS idx_equipment_loans_volunteer ON equipment_loans(volunteer_id);

CREATE TABLE IF NOT EXISTS meter_maintenance (
  meter_maintenance_id SERIAL PRIMARY KEY,
  session_id           INT NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
  equipment_id         INT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  inspection_date      DATE NOT NULL,
  inspected_by         TEXT,
  last_sample_date     DATE,
  case_contents        TEXT,
  battery_level        TEXT,
  comments             TEXT,
  created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS meter_testing (
  meter_testing_id   SERIAL PRIMARY KEY,
  session_id         INT NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
  equipment_id       INT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  sensor_id          INT REFERENCES sensor(sensor_id) ON DELETE SET NULL,
  parameter_type     TEXT NOT NULL,  -- pH, DO, EC
  round_number       INT,
  reference_value    NUMERIC(12, 4),
  measured_value     NUMERIC(12, 4),
  difference         NUMERIC(12, 4),
  pass_fail          TEXT,
  troubleshooting_id INT REFERENCES lst_troubleshooting(troubleshooting_id) ON DELETE SET NULL,
  action_taken       TEXT,
  created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meter_testing_equipment ON meter_testing(equipment_id);
CREATE INDEX IF NOT EXISTS idx_meter_testing_session ON meter_testing(session_id);

CREATE TABLE IF NOT EXISTS calibration_log (
  calibration_log_id SERIAL PRIMARY KEY,
  equipment_id       INT NOT NULL REFERENCES equipment(equipment_id) ON DELETE CASCADE,
  sensor_id          INT REFERENCES sensor(sensor_id) ON DELETE SET NULL,
  calibration_date   DATE NOT NULL,
  calibration_type   TEXT NOT NULL,  -- pH, DO, EC, Temperature
  reference_value    NUMERIC(12, 4),
  measured_value     NUMERIC(12, 4),
  offset_value       NUMERIC(12, 4),
  slope_a            NUMERIC(12, 4),
  slope_b            NUMERIC(12, 4),
  cell_constant      NUMERIC(12, 4),
  created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS temp_corrections (
  temp_correction_id   SERIAL PRIMARY KEY,
  sensor_id            INT NOT NULL REFERENCES sensor(sensor_id) ON DELETE CASCADE,
  ambient_correction   NUMERIC(12, 4),
  zero_deg_correction  NUMERIC(12, 4),
  calculated_by        TEXT,
  created_at           TIMESTAMPTZ DEFAULT NOW()
);
