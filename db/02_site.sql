-- StreamWatch: Site table (from SITES schema doc)
-- site_code unique, required. Status/last_sample_date calculated via views.

CREATE TABLE IF NOT EXISTS site (
  site_id                SERIAL PRIMARY KEY,
  site_code               TEXT NOT NULL UNIQUE,
  is_active                BOOLEAN NOT NULL DEFAULT true,
  waterbody_id             INT REFERENCES waterbody(waterbody_id) ON DELETE SET NULL,
  description              TEXT,
  latitude                 NUMERIC(10, 7),
  longitude                NUMERIC(10, 7),
  site_type                site_type_enum,
  map_link                 TEXT,
  -- Groundtruthing
  groundtruthing_priority  TEXT,
  groundtruthing_status_id INT REFERENCES lst_groundtruthing_status(groundtruthing_status_id) ON DELETE SET NULL,
  -- Ownership / access
  property_type            property_type_enum,
  permission               TEXT,
  walk_time                TEXT,
  walk_distance            TEXT,
  walk_gradient            TEXT,
  water_access             TEXT,
  environmental_hazards   TEXT,
  parking_details          TEXT,
  walking_directions       TEXT,
  additional_comments      TEXT,
  -- Attributes
  habitat_type             habitat_type_enum,
  drainage_area_sq_km       NUMERIC(10, 4),
  notes                    TEXT,
  -- Program priority (stored). Status/last_sample_date derived from visit.
  cat_priority_id          INT REFERENCES lst_priority(priority_id) ON DELETE SET NULL,
  bat_priority_id          INT REFERENCES lst_priority(priority_id) ON DELETE SET NULL,
  bact_priority_id         INT REFERENCES lst_priority(priority_id) ON DELETE SET NULL,
  created_at               TIMESTAMPTZ DEFAULT NOW(),
  updated_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_site_site_code ON site(site_code);
CREATE INDEX IF NOT EXISTS idx_site_waterbody ON site(waterbody_id);
CREATE INDEX IF NOT EXISTS idx_site_active ON site(is_active);

-- Junction: site <-> subwatershed (many-to-many)
CREATE TABLE IF NOT EXISTS junc_site_subwatershed (
  site_id         INT NOT NULL REFERENCES site(site_id) ON DELETE CASCADE,
  subwatershed_id INT NOT NULL REFERENCES subwatershed(subwatershed_id) ON DELETE CASCADE,
  PRIMARY KEY (site_id, subwatershed_id)
);

-- Junction: site <-> municipality (many-to-many)
CREATE TABLE IF NOT EXISTS junc_site_municipality (
  site_id          INT NOT NULL REFERENCES site(site_id) ON DELETE CASCADE,
  municipality_id  INT NOT NULL REFERENCES municipality(municipality_id) ON DELETE CASCADE,
  PRIMARY KEY (site_id, municipality_id)
);

-- Optional: link site to HUC14
ALTER TABLE site ADD COLUMN IF NOT EXISTS huc14_id INT REFERENCES tbl_huc14(huc14_id) ON DELETE SET NULL;
