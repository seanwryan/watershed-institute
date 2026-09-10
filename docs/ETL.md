# StreamWatch ETL (developer reference)

This document describes **what the Python ETL scripts currently do**. It is not a redesign proposal.

Staff-facing overview: in-app page **`/data-pipeline`**. Methods reference: **`/methods`**.

Related: `docs/migration_log.md` (historical migration notes), `docs/OPERATIONS_RUNBOOK.md` (rebuild counts and ops).

## Authoritative Watershed sources (Sep 9, 2026)

Documentation and UI wording for methods / Data Condition vocabulary should follow:

- StreamWatch Data Summary & Description (last updated September 9, 2026)
- StreamWatch Data Dictionary (last updated September 9, 2026)

Supporting Original Resources workbooks remain useful for ETL file names and sheets.

**ETL status (code):** Chemistry ETL is compatible with the final Sep 9 **All StreamWatch Data.xlsx** (banner/header detection, unit-suffixed columns, CAT:* / Salt Watch methods, E. coli Result, Outlier / Duplicate?).

**Local demo database:** `streamwatch_demo` was clean-rebuilt from the final workbook (post-ETL compatibility work). Chloride in that local demo matches the corrected workbook scale (stored as-is; ETL does not ÷10).

**Hosted / Render-connected database:** A separate controlled refresh is still required before assuming live Neon/production matches the final source. Do not treat a local rebuild as an automatic live-data deploy.

Use `python -m etl.migrate_streamwatch_data --dry-run` to validate a workbook without writing.

Do not put local absolute filesystem paths in public-facing pages or committed docs beyond generic filenames.

## Terminology

PostgreSQL holds **cleaned and structured records derived from Watershed source files**, not a byte-for-byte copy of every spreadsheet cell.

Pipelines may:

- normalize headers and types
- map aliases to columns
- skip exact duplicate chemistry packages
- link rows to sites/visits
- fill only NULL chemistry fields (Survey123)
- compute derived scores (`macro_analysis`, QA flags)
- skip unresolved, censored, or unsupported rows

Unresolved cases are logged or left for review rather than forced into matches.

**ETL** = Extract (read sources) → Transform (clean/match) → Load (write PostgreSQL), or preview/export without loading.

### Method strings (raw / documentation)

Sep 9 Summary Method groups include:

- `CAT: Hanna`
- `CAT: LaMotte`
- `CAT: Early LaMotte` (predecessor; turbidity not comparable — exclude from analysis)
- `BAT`
- `BACT`
- `Salt Watch` (Dictionary-only: in-house Hach chloride strip check vs Gallery — **not** community Salt Watch program data)

Legacy short names (`Hanna`, `LaMotte`) remain in seed for older DB rows. Final workbook Method values are stored as exact labels (`CAT: Hanna`, etc.) and are **not** silently collapsed.

### Data Condition vocabulary (Sep 9 Dictionary)

Tags described as currently in use in the raw dataset:

Provisional, Incomplete, Outlier, Minor Deviation, Flagged, Corrected, Erroneous, Duplicate, Duplicate?

August 2026: full review of Data Condition tags completed (per Summary timeline).

App/database seed includes Dictionary atomic tags (**Outlier**, **Duplicate?**) plus additional historical codes (Accepted, Unchecked, …). Semicolon **compound** Data Condition strings are **left unresolved** (full string logged); ETL does not invent a “first token” rule.

Watershed analysis practice excludes: Flagged records; trailing `?` values; CAT: Early LaMotte turbidity.

## Environment

| Variable | Role |
|----------|------|
| `DATABASE_URL` | PostgreSQL target |
| `STREAMWATCH_DATA_DIR` | Directory of Excel sources (default `data/`) |
| `SITES_FILE` / `VOLUNTEER_FILE` / `EQUIPMENT_FILE` | Optional per-file overrides |
| `STREAMWATCH_PROTECTED_DBS` | Comma-separated DB names that rebuild writers refuse (default includes `streamwatch_final`) |

Do not put absolute local paths, credentials, or private source extracts in git.

## Rebuild order (demo / writable DB)

From repo README / operations runbook:

```bash
psql "$DATABASE_URL" -f db/run_schema.sql
python -m etl.migrate_sites
python -m etl.migrate_volunteers
python -m etl.migrate_equipment
python -m etl.migrate_streamwatch_data
python -m etl.migrate_bact_2025
python -m etl.migrate_bat
python -m etl.biological_indices
python -m etl.apply_qa_rules
# optional export (does not load PG):
# python -m etl.export_wqx wqx_export.csv 2020-01-01 2025-12-31
```

Chemistry / BACT writers call `refuse_if_protected_database()` before mutating results.

The final Sep 9 **All StreamWatch Data.xlsx** is the chemistry source for clean rebuilds (set `STREAMWATCH_DATA_DIR` / pass the workbook path; do not commit source files into the repo).

## Inventory

| Module | Role | Mode | Rebuild? |
|--------|------|------|----------|
| `etl/config.py` | Paths, protected DB guard | Config | — |
| `etl/db.py` | Connection, lookup upsert | Helper | — |
| `etl/visit_helpers.py` | Visit ensure, chem/bact insert | Helper | — |
| `etl/chem_recon.py` | Chem fingerprints, recon JSON | Support + reports/ | Indirect |
| `etl/migrate_sites.py` | Sites + lookups | **Write** | Yes |
| `etl/migrate_volunteers.py` | Volunteers, trainings, assignments | **Write** | Yes |
| `etl/migrate_equipment.py` | Equipment, sensors, meter tests | **Write** | Yes |
| `etl/all_data_workbook.py` | ALL DATA reader, aliases, dry-run | Support / dry-run | Indirect |
| `etl/migrate_streamwatch_data.py` | Historical chem + ALL DATA E. coli | **Write** (+ `--dry-run`) | Yes |
| `etl/migrate_bact_2025.py` | Survey123 fill-NULL + IDEXX bacteria | **Write** | Yes |
| `etl/migrate_bat.py` | Bug taxonomy, counts, RBP100 | **Write** | Yes |
| `etl/biological_indices.py` | HGMI/NJIS/CPMI → `macro_analysis` | **Write** (derived) | Yes |
| `etl/apply_qa_rules.py` | Exceedance / meter-fail flags | **Write** (derived) | Yes |
| `etl/bact_reconcile.py` | Shared parse + import preview | Preview / shared | App `/imports/bact` |
| `etl/hab_status.py` | HAB status preview | Preview only | App `/imports/hab` |
| `etl/bact_scoring.py` | BACT Analysis workbook scoring | Preview only | App `/reports/bact` |
| `etl/export_wqx.py` | WQX-style CSV from DB | **Export** | Optional CLI + `/export/wqx` |

Schema/seed: `db/run_schema.sql` and numbered `db/*.sql` (not Excel ETL).

---

## Pipelines

### Sites — `migrate_sites.py`

- **Source:** `2025 StreamWatch Locations.xlsx` → sheet `SWSites_2024`
- **Dest:** `site`, `waterbody`, `subwatershed`, `lst_priority`, `lst_groundtruthing_status`, `junc_site_subwatershed`
- **Match / idempotency:** `ON CONFLICT (site_code) DO UPDATE`; junction `ON CONFLICT DO NOTHING`
- **Notes:** Habitat type coerced to High/Low Gradient, Canal, Lake when recognizable. Status / last sample date are not loaded as authoritative history (app views compute activity).

### Volunteers / training / assignments — `migrate_volunteers.py`

- **Source:** `Volunteer_Tracking.xlsm` → `Volunteers`, `Trainings`, `TrainingLog`, `Assignments` (`Sites_Live` not loaded)
- **Dest:** `volunteer`, `municipality`, `training`, `lst_training_type`, `training_log`, `junc_assignments`
- **Headers:** Scans first rows for labels (`VolunteerID`, `FirstName`, etc.)
- **Idempotency:** Assignments `ON CONFLICT (volunteer_id, site_id) DO NOTHING`; training_log upsert-style. **Volunteer and training rows are inserted again on re-run** (not fully idempotent).
- **Skips:** Rows with no name; assignments with unresolved site/volunteer; trainings with no date.

### Equipment / meter testing — `migrate_equipment.py`

- **Source:** `CAT Meter Tracking v.1.xlsx` → `Assignments`, `Sensors`, `2024/2025/2026 Testing` (`Tracking` is read but **not used**)
- **Dest:** `equipment`, `sensor`, `session`, `meter_testing`
- **Equipment codes:** Only `TWI` + exactly 3 digits; LaMotte-user name rows skipped
- **Meter tests:** Wide Round / Test Date matrices → sessions + measured pH / DO ppm / Cond (or Cond. 1). **Does not invent pass/fail or staff.** Blocks without a confident test date skipped.
- **Idempotency:** Equipment upsert by code; sensor/session/meter_testing inserts are **not** re-run-safe.
- **Docstring vs code:** Module docstring mentions `meter_maintenance` / `calibration_log`; **current code does not populate those tables.**

### Chemistry (historical) — `migrate_streamwatch_data.py` (+ `all_data_workbook.py`)

- **Source:** `All StreamWatch Data.xlsx` → sheet **`ALL DATA` only** (never auto-loads watershed sheets)
- **Header detection:** Locates the real header row by required labels (`Data Condition`, `Method`, `Site`, `Date`). Final workbook has a title banner; header is typically row 15 (0-based index 14).
- **Dry-run:** `python -m etl.migrate_streamwatch_data --dry-run [workbook.xlsx]` reports load stats **without writing** to PostgreSQL.
- **Dest:** `visit`, `chemical`; bacteria from ALL DATA **`E. coli Result`** (modifier text → `bacteria.detection_limit_note` when present). IDEXX remains a separate path in `migrate_bact_2025`.
- **Chem field mappings (source → internal):**
  - `Air Temperature (°C)` / `Air Temperature` → `air_temp_c`
  - `Water Temperature (°C)` / `Water Temperature` → `water_temp_c`
  - `Nitrate (mg/L)` / `Nitrate` → `nitrate_ug_l` (**stored as-is; no mg↔µg conversion** — see nitrate note below)
  - `Phosphate (mg/L)` / `Phosphates` / `Phosphate` → `phosphate_mg_l`
  - `pH` → `ph`
  - `Turbidity (JTU/NTU)` / `Turbidity` → `turbidity_ntu`
  - `DO (ppm)` / `DO ppm` → `dissolved_oxygen_ppm`
  - `DO (%)` / `%DO` → `dissolved_oxygen_pct`
  - `Conductivity (µS/cm)` / `Conductivity` → `conductivity_us_cm`
  - `Chloride (mg/L)` / `Chloride` → `chloride_mg_l`
- **Chloride:** Final workbook already contains corrected discrete-analyzer values. ETL **must not** divide by 10 (`CHLORIDE_APPLY_DIVIDE_BY_TEN = False`).
- **Methods:** Exact final labels `CAT: Early LaMotte`, `CAT: LaMotte`, `CAT: Hanna`, `Salt Watch`, `BACT`, `BAT` (additive seed; legacy `LaMotte`/`Hanna` retained). Not collapsed.
- **Data Conditions:** Atomic tags including **Outlier** and **Duplicate?** map when seeded. **Compound** semicolon/comma strings are **unresolved** (full string logged; no first-token invention).
- **Duplicates:** Application fingerprint on site + date + method + rounded chem values; exact clones skipped; differing same-day packages retained.
- **Nitrate unit:** Final header says mg/L; DB column remains `nitrate_ug_l`. Evidence supports **B — historically misnamed column / mg/L-scale values loaded without conversion**. No automatic conversion until Watershed confirms policy.
- **Sites sheet:** Workbook `SITES` is **not** a blind replacement for Locations migration (Fresh tidal / site-set diffs deferred).
- **Protected DB:** Refuses protected names before write.

### BACT Survey123 + IDEXX — `migrate_bact_2025.py` (+ `bact_reconcile.py`)

- **Source:** `BACT and HAB 2025 Data.xlsx` → `SURVEY123` / `Survey123`, `IDEXX` (**not** Gallery / Turbidity / Phycocyanin)
- **Survey123:** Match visits by site + **sample `Date`** (never `CreationDate`). Prefer matching `sample_code`. Fill **NULL chemical fields only**; do not overwrite non-null historical values. May fill `visit.sample_code` when NULL. Conflicts / unmatched logged in recon JSON.
- **Fields enriched:** water temp, nitrate, phosphate, turbidity, chloride (shared aliases)
- **IDEXX:** Match `visit.sample_code`; insert bacteria when integer MPN parses; skip existing `(visit_id, e_coli_mpn_100ml)`; skip censored / non-integer (`> 2419.6`, `< 1.0`, etc.)
- **Idempotency:** IDEXX skip-existing is re-run safe for identical MPN; Survey123 fill-NULL is generally safe; chemistry package inserts are not the primary path here
- **Preview:** `/imports/bact` uses the same parsing rules **read-only**
- **Note:** ALL DATA historical E. coli Result load is separate from this IDEXX attach path.

### Macroinvertebrates — `migrate_bat.py` + `biological_indices.py`

- **Source preference:** `tblSampleDates.xlsx` (sheets `BugList`, `tblSampleDates`, `tblBugResults`, `tblRBP100Bugs`); else BAT consolidation workbook
- **Dest:** `bug_list`, `visit`, `bug_count`, `rbp100_bug`; then **`macro_analysis`** via `biological_indices.py`
- **Idempotency:** bug_list `ON CONFLICT (bug_code)`; skip existing `(visit_id, bug_id)` for counts/RBP100; visits via ensure_visit
- **Indices:** Prefer `rbp100_bug` when sum(amount) ≥ 50 else non-excluded `bug_count`; upsert `macro_analysis` by `visit_id`
- **Not written by migrate_bat:** `macro_analysis` (separate job); BATSITES COLLECTED unused when tblSampleDates present

### Habitat

- **Site habitat type** (HG/LG/Canal/Lake) comes from sites migration.
- **Historical RBP habitat columns** exist on ALL DATA but are **not bulk-migrated** into `habitat_assessment`.
- App supports staff entry of HG/LG habitat assessments; demo baseline habitat_assessment count is typically **0** until entered.
- HAB **phycocyanin / bloom status** tools are **preview-only** (`hab_status.py`, `/imports/hab`); phycocyanin is not a PostgreSQL result table.

### QA post-load — `apply_qa_rules.py`

- Flags water temp > 31 °C or nitrate_ug_l > 10000; meter-fail windows when visit has equipment linked to failing `meter_testing.pass_fail` codes
- Updates `chemical.data_condition_id` / inserts `result_flag` with `NOT EXISTS` guards
- Does **not** implement the full Sep 9 Dictionary analysis-exclusion rules for trailing `?` or Early LaMotte turbidity (those are source-workbook conventions documented on Methods / Data Dictionary)

### WQX — `export_wqx.py`

- **Export only** from PostgreSQL → WQX-style CSV (prep format, not EPA portal package)
- Emits all chemistry packages for a visit; multi-package activity IDs become `{base}-C{chemical_id}`; multi-bact `{base}-B{bacteria_id}`
- CLI and `/export/wqx`

### BACT Analysis scoring — `bact_scoring.py`

- Reads uploaded `2025 BACT Analysis.xlsx` weekly parameter sheets; mirrors workbook rating logic for preview on `/reports/bact`
- Does not load into PostgreSQL

---

## Supporting helpers

### `visit_helpers.ensure_visit`

Match key: `(site_id, sample_date, sample_code IS NOT DISTINCT FROM …)`.

### `chem_recon`

- `PRIMARY_SHEET = "ALL DATA"`
- Fingerprint + reconciliation JSON under `reports/chem_recon_<dbslug>.json` (gitignored)

### Protected databases

Writers for chemistry/BACT refuse configured protected DB names so archive/production targets are not casually rebuilt.

---

## Known limitations / review points

1. **Hosted / Render-connected DB** may still need its own controlled refresh; local `streamwatch_demo` alignment does not update Neon automatically.
2. **Chloride:** Final workbook values are stored as-is; ETL does not apply ÷10 (avoid double-correction on any future refresh).
3. **Compound Data Conditions** remain unresolved by design until Watershed specifies compound policy.
4. **Nitrate:** `nitrate_ug_l` name vs mg/L-scale values — conversion deferred.
5. **Workbook SITES vs Locations** site-set / Fresh tidal sync deferred (Locations remains site source).
6. **Volunteer / equipment** re-runs can duplicate some child rows.
7. **Habitat assessments** and HAB phycocyanin not bulk-loaded.
8. **Gallery / Turbidity / Phycocyanin** sheets in BACT workbook not loaded by migrate.
9. **WQX** export is preparation CSV, not a full EPA submission package.
10. **Colilert vs Colisure** naming remains unresolved source ambiguity.

---

## App surfaces that call ETL modules

| Route | Module | Writes DB? |
|-------|--------|------------|
| `/imports/bact` | `bact_reconcile` | No (preview) |
| `/imports/hab` | `hab_status` | No |
| `/reports/bact` | `bact_scoring` | No |
| `/export/wqx` | `export_wqx` | No (download) |

Do not run destructive migrations solely to test documentation.
