## StreamWatch Data Modernization — Summary

This file summarizes what we have built so far and where we are headed for the StreamWatch data and web app.

---

## What we have now

- **Central PostgreSQL database (`streamwatch`)**
  - Schema for:
    - `site`, `visit`, `chemical`, `bacteria`, `habitat_assessment`, `macro_analysis`, `bug_list`, `bug_count`, `rbp100_bug`
    - `volunteer`, `training`, `training_log`, `junc_assignments`, `junc_attendance`
    - `equipment`, `sensor`, `session`, `meter_maintenance`, `meter_testing`, `calibration_log`, `equipment_loans`, `temp_corrections`
    - Lookups: `waterbody`, `subwatershed`, `municipality`, `tbl_huc13`, `tbl_huc14`, `data_condition`, `flag_type`, `lst_*` tables
  - QA views and reporting views:
    - QA: `v_chemical_meter_qa`, `v_chemical_exceedances`
    - Reporting: `v_site_summary`, `v_volunteer_activity`, `v_visit_summary`, `v_chemical_results`, `v_bacteria_results`, `v_equipment_inventory`, `v_training_compliance`

- **ETL and computation scripts (`etl/`)**
  - **Migration:**
    - `migrate_sites.py` – 2025 StreamWatch Locations → `site` + lookups
    - `migrate_volunteers.py` – Volunteer_Tracking → `volunteer`, `training`, `training_log`, `junc_assignments`
    - `migrate_equipment.py` – CAT Meter Tracking → `equipment`, `sensor`, `meter_testing` (and related tables)
    - `migrate_streamwatch_data.py` – All StreamWatch Data / 30 yr analysis → `visit`, `chemical`, `bacteria`
    - `migrate_bact_2025.py` – BACT and HAB 2025 Data → `visit`, `chemical`, `bacteria`
    - `migrate_bat.py` – BAT/tblSampleDates/BugList → `bug_list`, `visit`, `bug_count`, `rbp100_bug`
  - **QA and flags:**
    - `apply_qa_rules.py` – flags exceedances (temp > 31 °C, nitrate > 10 ppm), meter-fail windows, updates `data_condition` and `result_flag`
  - **Biological indices:**
    - `biological_indices.py` – HGMI (genus/family), NJIS, dominance metrics, writes to `macro_analysis` using `bug_*` tables + drainage area
  - **Exports:**
    - `export_wqx.py` – `build_wqx_csv()` and `export_wqx_csv()` for WQX-style CSV output (used by CLI and web app)

- **Web app (`dashboard/`)**
  - Flask app: [dashboard/app.py](../dashboard/app.py)
  - JSON API:
    - `GET /api/sites` – active sites (code, waterbody, coords, last sample, visit count)
    - `GET /api/site/<site_code>` – full site info + recent 5 results
    - `GET /api/time_series` – time series by site, parameter, date range
    - `GET /api/qa_summary` – counts of flagged chemistry, exceedances, meter-fail flags
    - `GET /api/parameters` – list of available parameters
    - `GET /export/wqx` – download WQX CSV (date range + optional site)
  - HTML pages (templates):
    - `home.html` – overview + links to sections
    - `map.html` – Leaflet map of sites with links to site detail
    - `sites.html` – table of sites with search and “View” links
    - `site_detail.html` – one site’s metadata + latest results + link to Explore
    - `explore.html` – time-series chart (Chart.js) with site, parameter, date range
    - `qa.html` – QA summary display
    - `export.html` – WQX export form (date range + site)
    - Shared layout and styling via `base.html` and `static/css/style.css`
  - Local + free-tier friendly deployment documented in [dashboard/README.md](../dashboard/README.md)

- **Docs**
  - [README.md](../README.md) – overall project overview and ETL run order
  - [db/README.md](../db/README.md) – schema application instructions
  - [dashboard/README.md](../dashboard/README.md) – running and deploying the web app
  - [docs/migration_log.md](migration_log.md) – mapping of source files → target tables
  - [docs/APP_TUTORIAL.md](APP_TUTORIAL.md) – step‑by‑step web app usage guide
  - [docs/DEPLOYMENT.md](DEPLOYMENT.md) – public hosting (Render + Neon, free tier)
  - [docs/FRONTEND_GOALS.md](FRONTEND_GOALS.md) – frontend goals from raw_breakdown

---

## High-level goals

### 1. Stabilize and complete data migration

- Finish and verify ETL from all key historical sources into the new schema:
  - 30+ years of chemistry, biology, habitat, bacteria, and HAB data (30 yr workbook, All StreamWatch Data, BACT/HAB 2025, BAT/BATSITES/tblSampleDates, WQX submissions).
  - Ensure every active StreamWatch site is represented in `site` with correct coordinates, status, and priorities.
- Validate row counts and key statistics against the original Excel workbooks (spot checks by watershed, year, and parameter).
- Document any gaps (years/sites/parameters that cannot be loaded cleanly) so they’re explicit, not silent.

### 2. Formalize QA and governance

- Turn the draft logic in 2025 Data Questions and the DataDictionary into concrete rules:
  - Clear numeric thresholds per parameter for flagging vs invalidation.
  - Time windows and conditions for meter failure impacts.
  - Policies for handling LaMotte/volunteer “questionable” data and lab QC (Gallery, IDEXX).
- Use `data_condition` and `flag_type` consistently so:
  - Analysts can filter by QA status.
  - Exports can easily include or exclude flagged data.
  - Public dashboards only show data that meet agreed standards.
- Add guidance for staff/volunteers on interpreting flags (simple narrative, not just codes).

### 3. Strengthen reporting and analysis

- Build out repeatable internal reports using the reporting views:
  - Site‑level summaries (long‑term trends, exceedance counts).
  - Program metrics (number of active sites, visits per year, volunteer activity).
  - QA monitoring (how many values flagged, which sites/parameters most often exceed thresholds).
- Support external analysis:
  - Make it easy to connect tools like R, Python, Power BI, and DBeaver to the `streamwatch` DB.
  - Provide example queries/snippets in documentation.

### 4. Public‑facing access and transparency

- Host the web app publicly on a free or low‑cost platform (e.g. Render or Fly.io). **Step‑by‑step:** [docs/DEPLOYMENT.md](DEPLOYMENT.md) (Render + Neon, free tier; optional Fly.io). A `render.yaml` in the repo enables one‑click deploy; set `DATABASE_URL` (Neon) in the Render dashboard after deploy.
- Use a managed Postgres service (Neon, Supabase, ElephantSQL, etc.) or a tunnel from the existing DB so the app can be reached without exposing your laptop.
- Provide a clear, plain‑language “What this shows / What it doesn’t” section on the public app:
  - Clarify which data are provisional vs validated.
  - Explain basic QA concepts and limits.

### 5. Support external database access (for partners)

- For trusted partners (e.g. researchers, agencies), give read‑only access to the core database:
  - Use a dedicated read‑only user and connection string.
  - Document how to connect with DBeaver/pgAdmin and recommended views/tables to start with.
- Keep this separate from the public web app so you can control who has raw access.

### 6. Make the system maintainable

- Keep the schema and ETL scripts in sync with documentation:
  - When schemas change, update `db/` SQL and the docs together.
  - When adding a new data source, record it in `docs/migration_log.md`.
- Add a simple “runbook” for:
  - Loading a new monitoring season.
  - Re‑running QA rules.
  - Regenerating indices/exports.
- Aim for tasks that staff can run with a small, well‑documented set of commands.

---

## How this supports the original vision

From the `raw_breakdown.txt` summaries and planning docs, the vision is to move from many scattered Excel/Access files to a **single, defensible, queryable system** that can:

- Store **all** StreamWatch data (chemistry, biology, habitat, bacteria, HAB, equipment, volunteers, sites) in one place.
- Apply consistent **QA rules and flags** that are traceable and transparent.
- Produce repeatable **reports, exports, and dashboards** for staff, partners, and the public.
- Be **hosted and shared** without everyone needing to wrangle raw spreadsheets.

The current database, ETL scripts, and web app are the core of that system. The remaining work is primarily about loading all historical data, tightening QA and documentation, and choosing a stable hosting/deployment setup so others can reliably use what’s been built.

