-- StreamWatch: Monitoring result tables (chemical, bacteria, habitat, biological)

-- Chemical (field/lab chemistry per visit)
CREATE TABLE IF NOT EXISTS chemical (
  chemical_id       SERIAL PRIMARY KEY,
  visit_id          INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  data_condition_id INT REFERENCES data_condition(data_condition_id) ON DELETE SET NULL,
  -- Physical
  air_temp_c        NUMERIC(6, 2),
  water_temp_c      NUMERIC(6, 2),
  -- Nutrients
  nitrate_ug_l      NUMERIC(12, 4),
  nitrate_dilution_adj NUMERIC(12, 4),
  phosphate_mg_l    NUMERIC(12, 4),
  -- Physical/chemical
  ph                NUMERIC(5, 2),
  turbidity_ntu     NUMERIC(12, 4),
  dissolved_oxygen_ppm NUMERIC(8, 3),
  dissolved_oxygen_pct NUMERIC(8, 2),
  conductivity_us_cm NUMERIC(12, 4),
  chloride_mg_l     NUMERIC(12, 4),
  -- Source/metadata
  method_id         INT REFERENCES lst_method(method_id) ON DELETE SET NULL,
  detection_limit_note TEXT,
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chemical_visit ON chemical(visit_id);
CREATE INDEX IF NOT EXISTS idx_chemical_condition ON chemical(data_condition_id);

-- Bacteria (E. coli etc. per visit)
CREATE TABLE IF NOT EXISTS bacteria (
  bacteria_id       SERIAL PRIMARY KEY,
  visit_id          INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  data_condition_id  INT REFERENCES data_condition(data_condition_id) ON DELETE SET NULL,
  e_coli_mpn_100ml  INT,
  total_coliform_mpn INT,
  detection_limit_note TEXT,
  holding_time_flag  BOOLEAN,
  holding_temp_flag BOOLEAN,
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bacteria_visit ON bacteria(visit_id);

-- Habitat assessment (RBP-style metrics per visit)
CREATE TABLE IF NOT EXISTS habitat_assessment (
  habitat_id        SERIAL PRIMARY KEY,
  visit_id          INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  data_condition_id INT REFERENCES data_condition(data_condition_id) ON DELETE SET NULL,
  -- High gradient
  embeddedness      INT,
  velocity_depth    INT,
  freq_riffles      INT,
  -- Low gradient
  pool_variability  INT,
  pool_substrate    INT,
  channel_sinuosity INT,
  -- Shared
  sediment_deposition INT,
  channel_flow_status INT,
  epifaunal_substrate INT,
  bank_stability_left  INT,
  bank_stability_right INT,
  bank_veg_protection_left  INT,
  bank_veg_protection_right INT,
  riparian_zone_left  INT,
  riparian_zone_right INT,
  channel_alteration INT,
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_habitat_visit ON habitat_assessment(visit_id);

-- Macro analysis (summary indices per visit: NJIS, HGMI, CPMI, FBI)
CREATE TABLE IF NOT EXISTS macro_analysis (
  macro_analysis_id SERIAL PRIMARY KEY,
  visit_id          INT NOT NULL UNIQUE REFERENCES visit(visit_id) ON DELETE CASCADE,
  data_condition_id INT REFERENCES data_condition(data_condition_id) ON DELETE SET NULL,
  total_organisms   INT,
  total_taxa        INT,
  ept_taxa          INT,
  pct_ept           NUMERIC(8, 2),
  pct_dominance     NUMERIC(8, 2),
  dominant_taxon    TEXT,
  fbi              NUMERIC(8, 2),
  hbi              NUMERIC(8, 2),
  njis_score       NUMERIC(8, 2),
  njis_rating       TEXT,
  hgmi_genus       NUMERIC(8, 2),
  hgmi_family       NUMERIC(8, 2),
  hgmi_rating       TEXT,
  cpmi_score       NUMERIC(8, 2),
  cpmi_rating       TEXT,
  index_type        TEXT,  -- HGMI, CPMI
  created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_macro_analysis_visit ON macro_analysis(visit_id);

-- Bug list (taxonomic reference for biological indices)
CREATE TABLE IF NOT EXISTS bug_list (
  bug_id              SERIAL PRIMARY KEY,
  bug_code            TEXT UNIQUE,
  order_class         TEXT,
  family              TEXT NOT NULL,
  genus_species       TEXT,
  ept                 BOOLEAN,
  tolerance_ftv        NUMERIC(8, 2),
  tolerance_nytol     NUMERIC(8, 2),
  functional_feeding_group TEXT,
  habit               TEXT,
  scraper             BOOLEAN,
  clinger             BOOLEAN,
  talu_attribute      TEXT,
  tsn                 TEXT,
  created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bug_list_family ON bug_list(family);
CREATE INDEX IF NOT EXISTS idx_bug_list_genus ON bug_list(genus_species);

-- Raw bug counts per visit (links to bug_list)
CREATE TABLE IF NOT EXISTS bug_count (
  bug_count_id   SERIAL PRIMARY KEY,
  visit_id       INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  bug_id         INT NOT NULL REFERENCES bug_list(bug_id) ON DELETE RESTRICT,
  amount         INT NOT NULL,
  exclude        BOOLEAN NOT NULL DEFAULT false,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bug_count_visit ON bug_count(visit_id);
CREATE INDEX IF NOT EXISTS idx_bug_count_bug ON bug_count(bug_id);

-- RBP 100-organism subsample (for index calculation)
CREATE TABLE IF NOT EXISTS rbp100_bug (
  rbp100_id   SERIAL PRIMARY KEY,
  visit_id    INT NOT NULL REFERENCES visit(visit_id) ON DELETE CASCADE,
  bug_id      INT NOT NULL REFERENCES bug_list(bug_id) ON DELETE RESTRICT,
  amount      INT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rbp100_visit ON rbp100_bug(visit_id);

-- Result-level flags (link flag_type to any result row for reporting/filtering)
CREATE TABLE IF NOT EXISTS result_flag (
  result_flag_id SERIAL PRIMARY KEY,
  result_table   TEXT NOT NULL,
  result_pk      INT NOT NULL,
  flag_type_id   INT NOT NULL REFERENCES flag_type(flag_type_id) ON DELETE CASCADE,
  notes          TEXT,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_result_flag_table_pk ON result_flag(result_table, result_pk);
CREATE INDEX IF NOT EXISTS idx_result_flag_type ON result_flag(flag_type_id);
