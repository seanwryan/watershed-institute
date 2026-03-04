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

## 3. Visits and results

| Source | Sheet/Table | Target | Script |
|--------|-------------|--------|--------|
| All StreamWatch Data.xlsx | Per-watershed sheets | `visit`, `chemical`, `bacteria`, `habitat_assessment`, `macro_analysis` as applicable | `etl/migrate_streamwatch_data.py` |
| 30 yr StreamWatch Data Analysis.xlsx | 00-04, 05-09, 10-14, Sheet1 | `visit`, `chemical` (and linked) | (same or separate) |
| BACT and HAB 2025 Data.xlsx | Survey123, IDEXX, Gallery, Turbidity, Phycocyanin | `visit`, `chemical`, `bacteria` | `etl/migrate_bact_2025.py` |
| BAT Data Consolidation, BATSITES COLLECTED, tblSampleDates.xlsx | Various | `visit`, `macro_analysis`, `bug_count`, `rbp100_bug` | `etl/migrate_bat.py` |
| (BugList, SiteSize) | BugList, SiteSize | `bug_list`, site drainage / ref | (in migrate_bat or shared) |

## 4. Execution order

1. Run schema: `psql $DATABASE_URL -f db/run_schema.sql`
2. Migrate sites and lookups (creates sites and lookup rows used by other ETL)
3. Migrate volunteers and equipment
4. Migrate visits and results (depends on site_id, volunteer_id, equipment_id where used)

## 5. Data condition

- Where source has "Data Condition", "Notes" or equivalent (Provisional, Unchecked, Flagged), map to `data_condition_id` on the result row.
- Simple rule-based flags (e.g. exceedance 31°C, 10 ppm nitrate) applied in ETL or post-load QA step.
