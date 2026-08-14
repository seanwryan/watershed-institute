# StreamWatch Data Migration Log

Source → target mapping per Database Project Plan. ETL scripts in `etl/`.

## 1. Sites and lookups

| Source | Sheet/Table | Target | Script |
|--------|-------------|--------|--------|
| 2025 StreamWatch Locations.xlsx | SWSites_2024 | `site`, `waterbody`, `subwatershed`, `lst_priority`, `lst_groundtruthing_status` | `etl/migrate_sites.py` |
| (same) | — | Lookups populated on first use from site columns | (in migrate_sites) |

**Column mapping (SWSites_2024 → site):**
- SiteCode → site_code
- WaterBody → waterbody (lookup/insert)
- Subwatershed → subwatershed (lookup/insert)
- Description → description
- Drainage area → drainage_area_sq_km
- Latitude / Longitude → latitude, longitude
- Type of property → property_type
- Permission → permission
- Walk time/distance/gradient, Water access, Parking, Walking directions, Environmental hazards, Additional comments → same
- Groundtruthing priority/status → groundtruthing_priority, groundtruthing_status_id
- CAT/BAT/BACT Priority → cat_priority_id, bat_priority_id, bact_priority_id
- (Status and Last sample date → calculated via views, not migrated)

## 2. Volunteers and equipment

| Source | Sheet/Table | Target | Script |
|--------|-------------|--------|--------|
| Volunteer_Tracking.xlsm | Volunteers | `volunteer` | `etl/migrate_volunteers.py` |
| Volunteer_Tracking.xlsm | Trainings, TrainingLog | `training`, `training_log` | (same) |
| Volunteer_Tracking.xlsm | Assignments | `junc_assignments` | (same) |
| Volunteer_Tracking.xlsm | Sites_Live | (reference only; sites from migrate_sites) | — |
| CAT Meter Tracking v.1.xlsx | Assignments, Sensors, Tracking, 2024/2025/2026 Testing | `equipment`, `sensor`, `session`, `meter_maintenance`, `meter_testing`, `calibration_log` | `etl/migrate_equipment.py` |

**Volunteers / trainings / assignments (`Volunteer_Tracking.xlsm`):** Table headers often sit a few rows below the top of the sheet. `migrate_volunteers.py` detects the header row from labels (`VolunteerID`, `TrainingID`, `SiteID`, etc.). `Street` maps to `volunteer.address`. Assignments `SiteID` values that are non-numeric are treated as `site_code` and resolved against `site`. Parent links, phone, ZIP padding, and role alias normalization are not handled in this import.

**Equipment inventory (Assignments → `equipment`):** Only rows whose Meter ID matches `TWI` + exactly 3 digits (case-insensitive) are inserted. The lower “LaMotte Users” block reuses the Meter ID column for assignee names and is skipped. Serial numbers from numeric Excel cells are normalized to digit strings (no trailing `.0`); text serials are stripped only so leading zeros are preserved.

**Meter testing (`2024 Testing` / `2025 Testing` / `2026 Testing` → `session` + `meter_testing`):** Sheets are wide quarterly matrices (Round / Test Date / Standards / Meter columns), not flat tables. Each dated Round block becomes a `session` (`date_start` = workbook test date, type Quarterly maintenance). One `meter_testing` row is inserted per meter × parameter (`pH`, `DO` from DO ppm, `EC` from Cond. or Cond. 1) when a numeric measured value is present. Trailing `*` on meter IDs are stripped. Blocks without a test date are skipped. `pass_fail`, Tracking-sheet codes, staff, and sensors are not joined in this import.

## 3. Visits and results

| Source | Sheet/Table | Target | Script |
|--------|-------------|--------|--------|
| All StreamWatch Data.xlsx | **ALL DATA only** | `visit`, `chemical`, `bacteria` | `etl/migrate_streamwatch_data.py` |
| BACT and HAB 2025 Data.xlsx | Survey123 (enrichment), IDEXX (bacteria) | `chemical` fill-nulls; `bacteria` | `etl/migrate_bact_2025.py` |
| BAT Data Consolidation, BATSITES COLLECTED, tblSampleDates.xlsx | Various | `visit`, `macro_analysis`, `bug_count`, `rbp100_bug` | `etl/migrate_bat.py` |
| (BugList, SiteSize) | BugList, SiteSize | `bug_list`, site drainage / ref | (in migrate_bat or shared) |

**BAT idempotency (`etl/migrate_bat.py`):** Re-runs against the same DB/source are safe.
Source `tblSampleDates.xlsx` has one row per `SampleID`+`BugID` in both `tblBugResults` and
`tblRBP100Bugs`. Application-level fingerprints skip inserts when `(visit_id, bug_id)` already
exists for `bug_count` / `rbp100_bug`. Visits use `ensure_visit(site_id, sample_date, sample_code)`.
`bug_list` remains `ON CONFLICT (bug_code) DO NOTHING`. No new UNIQUE constraints. Macro scores
are computed separately by `etl/biological_indices.py` (upsert on `visit_id`). BATSITES COLLECTED
path is not used when `tblSampleDates.xlsx` is present.

### Historical chemistry reconstruction (Phase 1 Data Trust)

**Technical primary source (pending staff confirmation of official authority):**
`All StreamWatch Data.xlsx` → sheet **`ALL DATA`**.

**Why ALL DATA (not watershed sheets):** Empirically, loading ALL DATA together with per-watershed sheets produced large exact-package duplication (~32k chemical rows vs ~17.4k distinct packages). Watershed sheets largely overlap ALL DATA; Assunpink and Beden Brook are a duplicated sheet pair. ALL DATA is used here as the **evidence-supported technical primary** for reconstruction, not as a claim that Watershed has formally designated it authoritative.

**What is not bulk-imported:** Per-watershed sheets in the same workbook. Six watershed-only site/date observations remain **unresolved / not imported** and are listed in the reconciliation report (`reports/chem_recon_*.json`).

**Exact dedupe:** Application-level fingerprint on site + date + method + rounded measurement values. Exact clones are skipped; **differing** same-day packages are retained (no `UNIQUE(visit_id)`).

**Corrected parameter headers (ALL DATA → `chemical`):**
- `Air Temperature` → `air_temp_c`
- `Water Temperature` → `water_temp_c`
- `Nitrate` → `nitrate_ug_l`
- `Phosphates` → `phosphate_mg_l`
- `pH` → `ph`
- `Turbidity` → `turbidity_ntu`
- `DO ppm` → `dissolved_oxygen_ppm`
- `%DO` → `dissolved_oxygen_pct`
- `Conductivity` → `conductivity_us_cm`
- `Chloride (mg/L)` → `chloride_mg_l`

**Survey123 / BACT:** Uses sample `Date` (not `CreationDate`). Matches existing site/date visits and **fills NULL fields only** (does not overwrite non-null historical values). Conflicts and unmatched rows are logged. Gallery / Turbidity / Phycocyanin sheets are not loaded in this milestone.

**IDEXX bacteria idempotency:** `etl/migrate_bact_2025.py` attaches IDEXX rows by `visit.sample_code` and skips when `(visit_id, e_coli_mpn_100ml)` already exists. Re-runs must not multiply bacteria rows. Distinct MPN values on the same sample code remain representable (no broad UNIQUE). Historical ALL DATA `E. coli Result` (~2,936) is **not** imported here — deferred pending Watershed staff confirmation of source authority/scope. Censored IDEXX values (`> 2419.6`, `< 1.0`) remain unparsed/skipped. Gallery lab sheets remain unloaded.

**Date parsing:** `etl.visit_helpers._date` returns a Python `date` (not a datetime/Timestamp). Returning datetimes previously broke Survey123 site/date matching when sample times were non-midnight.

**Verification before canonical cutover:** Run this chemistry path against a writable verification/demo database (e.g. `streamwatch_demo` or `streamwatch_chem_verify`) first. Rebuild migrations refuse protected database names (default: `streamwatch_final`; override via `STREAMWATCH_PROTECTED_DBS`). Do **not** replace or rewrite archive/production targets until reconciliation is reviewed.

## 4. Execution order

1. Run schema: `psql $DATABASE_URL -f db/run_schema.sql`
2. Migrate sites and lookups (creates sites and lookup rows used by other ETL)
3. Migrate volunteers and equipment
4. Migrate visits and results (depends on site_id, volunteer_id, equipment_id where used)

## 5. Data condition

- Where source has "Data Condition", "Notes" or equivalent (Provisional, Unchecked, Flagged), map to `data_condition_id` on the result row.
- Simple rule-based flags (e.g. exceedance 31°C, 10 ppm nitrate) applied in ETL or post-load QA step.
