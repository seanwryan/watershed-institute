# StreamWatch Database & Data Modernization

Centralized PostgreSQL database, ETL, QA, reporting, and dashboard for the StreamWatch water quality monitoring program (CAT, BAT, BACT), per the [StreamWatch Database Modernization Plan](.cursor/plans/streamwatch_database_modernization_7ab7197e.plan.md).

## Quick start

1. **Create database and apply schema**
   ```bash
   createdb streamwatch
   cd db && psql $DATABASE_URL -f run_schema.sql
   ```

2. **Install Python deps and run ETL** (place Excel sources in `data/` or set `STREAMWATCH_DATA_DIR`)
   ```bash
   pip install -r requirements.txt
   export DATABASE_URL=postgresql://localhost/streamwatch
   python -m etl.migrate_sites
   python -m etl.migrate_volunteers
   python -m etl.migrate_equipment
   python -m etl.migrate_streamwatch_data
   python -m etl.migrate_bact_2025
   python -m etl.migrate_bat
   python -m etl.biological_indices
   python -m etl.apply_qa_rules
   ```

3. **WQX export**
   ```bash
   python -m etl.export_wqx wqx_export.csv 2020-01-01 2025-12-31
   ```

4. **Web app**
   ```bash
   python dashboard/app.py
   ```
   Open http://localhost:5000 for the multi-page app (Home, Map, Sites, Site detail, Explore, Equipment, Volunteers, Scores, QA, Export). See `dashboard/README.md` for deployment on a free tier (e.g. Render, Fly.io).

Historical chemistry (`migrate_streamwatch_data`) loads the **ALL DATA** sheet only as the evidence-supported technical primary pending Watershed confirmation; see `docs/migration_log.md`. Generated reconciliation JSON under `reports/` is gitignored. Rebuild migrations refuse protected DB names (default `streamwatch_final`; set `STREAMWATCH_PROTECTED_DBS` to customize).

## Layout

- **db/** – PostgreSQL schema (lookups, site, volunteer, equipment, visit, results, flags, QA views, reporting views) and seed data
- **etl/** – Migration scripts (sites, volunteers, equipment, StreamWatch data, BACT 2025, BAT), QA rules, biological indices, WQX export
- **dashboard/** – Flask web app (Map, Sites, Explore, Equipment, Volunteers, Scores, QA, Export) and JSON API
- **docs/** – Operations runbook (`docs/OPERATIONS_RUNBOOK.md`), app tutorial, deployment guide, migration log; **docs/reference/** – source workbook summaries (raw_breakdown.txt)
- **data/** – Excel/XLSX source files (see “Data sources” below)
- **reports/** – local ETL reconciliation outputs (gitignored)

## Data sources (expected in `data/` or paths in `etl/config.py`)

- 2025 StreamWatch Locations.xlsx
- Volunteer_Tracking.xlsm
- CAT Meter Tracking v.1.xlsx
- All StreamWatch Data.xlsx (ALL DATA chemistry path; 30 yr workbook not dual-loaded by current ETL)
- BACT and HAB 2025 Data.xlsx
- tblSampleDates.xlsx / BAT Data Consolidation / BATSITES COLLECTED (for BAT/BugList)
