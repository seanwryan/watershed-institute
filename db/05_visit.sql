-- StreamWatch: Visit (sampling event) - links site to all result tables

CREATE TABLE IF NOT EXISTS visit (
  visit_id       SERIAL PRIMARY KEY,
  site_id        INT NOT NULL REFERENCES site(site_id) ON DELETE RESTRICT,
  sample_date    DATE NOT NULL,
  sample_time    TIME,
  sample_code    TEXT,
  method_id      INT REFERENCES lst_method(method_id) ON DELETE SET NULL,
  equipment_id   INT REFERENCES equipment(equipment_id) ON DELETE SET NULL,
  notes          TEXT,
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_visit_site ON visit(site_id);
CREATE INDEX IF NOT EXISTS idx_visit_sample_date ON visit(sample_date);
CREATE INDEX IF NOT EXISTS idx_visit_sample_code ON visit(sample_code);

-- Junction: volunteer attendance at visit
CREATE TABLE IF NOT EXISTS junc_attendance (
  attendance_id SERIAL PRIMARY KEY,
  visit_id      INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  volunteer_id  INT NOT NULL REFERENCES volunteer(volunteer_id) ON DELETE CASCADE,
  role_id       INT REFERENCES lst_role(role_id) ON DELETE SET NULL,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(visit_id, volunteer_id)
);

CREATE INDEX IF NOT EXISTS idx_junc_attendance_visit ON junc_attendance(visit_id);
CREATE INDEX IF NOT EXISTS idx_junc_attendance_volunteer ON junc_attendance(volunteer_id);
