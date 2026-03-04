-- StreamWatch: Volunteer table (from VOLUNTEERS schema doc)
-- Training status derived from training_log; not stored.

CREATE TABLE IF NOT EXISTS volunteer (
  volunteer_id   SERIAL PRIMARY KEY,
  first_name     TEXT NOT NULL,
  last_name      TEXT NOT NULL,
  perfect_id     TEXT,
  is_under_17    BOOLEAN NOT NULL DEFAULT false,
  parent_id      INT REFERENCES volunteer(volunteer_id) ON DELETE SET NULL,
  -- Contact (required for new entries)
  email          TEXT,
  address        TEXT,
  city_id        INT REFERENCES municipality(municipality_id) ON DELETE SET NULL,
  state          CHAR(2) NOT NULL DEFAULT 'NJ',
  zip_code       TEXT,
  alt_email      TEXT,
  phone          TEXT,
  alt_phone      TEXT,
  -- Participation
  active_cat     BOOLEAN NOT NULL DEFAULT false,
  active_bat     BOOLEAN NOT NULL DEFAULT false,
  active_bact    BOOLEAN NOT NULL DEFAULT false,
  partner_id     INT REFERENCES volunteer(volunteer_id) ON DELETE SET NULL,
  status         volunteer_status_enum NOT NULL DEFAULT 'Unknown',
  notes          TEXT,
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_volunteer_status ON volunteer(status);
CREATE INDEX IF NOT EXISTS idx_volunteer_active ON volunteer(active_cat, active_bat, active_bact);

-- Training event catalog
CREATE TABLE IF NOT EXISTS training (
  training_id    SERIAL PRIMARY KEY,
  training_type_id INT REFERENCES lst_training_type(training_type_id) ON DELETE SET NULL,
  training_date  DATE NOT NULL,
  trainer        TEXT,
  location       TEXT,
  notes          TEXT,
  total_attendees INT,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- Training log (attendance and credential validity)
CREATE TABLE IF NOT EXISTS training_log (
  training_log_id SERIAL PRIMARY KEY,
  training_id     INT NOT NULL REFERENCES training(training_id) ON DELETE CASCADE,
  volunteer_id    INT NOT NULL REFERENCES volunteer(volunteer_id) ON DELETE CASCADE,
  status          TEXT,  -- Passed, Not Started, etc.
  expiration_date DATE,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(training_id, volunteer_id)
);

CREATE INDEX IF NOT EXISTS idx_training_log_volunteer ON training_log(volunteer_id);
CREATE INDEX IF NOT EXISTS idx_training_log_expiration ON training_log(expiration_date);
