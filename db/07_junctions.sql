-- StreamWatch: Volunteer–site assignments (many-to-many)

CREATE TABLE IF NOT EXISTS junc_assignments (
  assignment_id SERIAL PRIMARY KEY,
  volunteer_id  INT NOT NULL REFERENCES volunteer(volunteer_id) ON DELETE CASCADE,
  site_id       INT NOT NULL REFERENCES site(site_id) ON DELETE CASCADE,
  role_id       INT REFERENCES lst_role(role_id) ON DELETE SET NULL,
  start_date    DATE,
  end_date     DATE,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(volunteer_id, site_id)
);

CREATE INDEX IF NOT EXISTS idx_junc_assignments_volunteer ON junc_assignments(volunteer_id);
CREATE INDEX IF NOT EXISTS idx_junc_assignments_site ON junc_assignments(site_id);
