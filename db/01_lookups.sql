-- StreamWatch Database: Lookup and reference tables
-- Naming: lowercase, underscores. Explicit PKs/FKs.

-- Waterbody (stream/lake name)
CREATE TABLE IF NOT EXISTS waterbody (
  waterbody_id   SERIAL PRIMARY KEY,
  name           TEXT NOT NULL UNIQUE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Subwatershed
CREATE TABLE IF NOT EXISTS subwatershed (
  subwatershed_id SERIAL PRIMARY KEY,
  name           TEXT NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Municipality (for site and volunteer address)
CREATE TABLE IF NOT EXISTS municipality (
  municipality_id SERIAL PRIMARY KEY,
  name            TEXT NOT NULL,
  state           CHAR(2) NOT NULL DEFAULT 'NJ',
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- HUC (watershed hierarchy)
CREATE TABLE IF NOT EXISTS tbl_huc13 (
  huc13_id   SERIAL PRIMARY KEY,
  code       TEXT NOT NULL UNIQUE,
  name       TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tbl_huc14 (
  huc14_id   SERIAL PRIMARY KEY,
  huc13_id   INT NOT NULL REFERENCES tbl_huc13(huc13_id) ON DELETE RESTRICT,
  code       TEXT NOT NULL,
  name       TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(huc13_id, code)
);

-- Site type
CREATE TYPE site_type_enum AS ENUM (
  'HUC', 'Target', 'Project', 'Legacy', 'MUNI', 'V.Req'
);

-- Property type for site access
CREATE TYPE property_type_enum AS ENUM (
  'Public', 'Private', 'TWI', 'Other'
);

-- Habitat type (for biological index applicability)
CREATE TYPE habitat_type_enum AS ENUM (
  'High Gradient', 'Low Gradient', 'Canal', 'Lake'
);

-- Program tier priority (e.g. "1 – Primary", "2 – Secondary")
CREATE TABLE IF NOT EXISTS lst_priority (
  priority_id SERIAL PRIMARY KEY,
  label       TEXT NOT NULL UNIQUE,
  sort_order  INT
);

-- Groundtruthing status
CREATE TABLE IF NOT EXISTS lst_groundtruthing_status (
  groundtruthing_status_id SERIAL PRIMARY KEY,
  label                   TEXT NOT NULL UNIQUE
);

-- Method (LaMotte, BACT, Hanna, BAT, etc.)
CREATE TABLE IF NOT EXISTS lst_method (
  method_id SERIAL PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Data condition (QA lifecycle: Raw, Provisional, Unchecked, Validated, Approved, Certified, etc.)
CREATE TABLE IF NOT EXISTS data_condition (
  data_condition_id SERIAL PRIMARY KEY,
  code              TEXT NOT NULL UNIQUE,
  description       TEXT,
  domain            TEXT,  -- 'quality_status' | 'issues_anomalies' | 'processing_modifiers'
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

-- Flag taxonomy: Issues & Anomalies (Suspect, Flagged, Outlier, Erroneous, etc.)
CREATE TABLE IF NOT EXISTS flag_type (
  flag_type_id SERIAL PRIMARY KEY,
  code         TEXT NOT NULL UNIQUE,
  description  TEXT,
  domain       TEXT,
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Volunteer status
CREATE TYPE volunteer_status_enum AS ENUM (
  'Active', 'Inactive', 'Parent', 'Unknown'
);

-- Equipment status
CREATE TYPE equipment_status_enum AS ENUM (
  'Active', 'Retired', 'Lost', 'Under Repair'
);

-- Sensor type
CREATE TYPE sensor_type_enum AS ENUM (
  'pH', 'DO', 'EC', 'ORP'
);

-- Session type (maintenance/testing)
CREATE TABLE IF NOT EXISTS lst_session_type (
  session_type_id SERIAL PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE
);

-- Troubleshooting level (for meter testing)
CREATE TABLE IF NOT EXISTS lst_troubleshooting (
  troubleshooting_id SERIAL PRIMARY KEY,
  code               TEXT NOT NULL,
  parameter_type     TEXT,  -- DO, pH, EC
  description        TEXT,
  created_at         TIMESTAMPTZ DEFAULT NOW()
);

-- Training type (for volunteer training log)
CREATE TABLE IF NOT EXISTS lst_training_type (
  training_type_id SERIAL PRIMARY KEY,
  name             TEXT NOT NULL UNIQUE
);

-- Role (CAT, BAT, BACT for assignments)
CREATE TABLE IF NOT EXISTS lst_role (
  role_id SERIAL PRIMARY KEY,
  name    TEXT NOT NULL UNIQUE
);
