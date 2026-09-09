# StreamWatch ETL (developer reference)

This document describes **what the Python ETL scripts currently do**. It is not a redesign proposal.

Staff-facing overview: in-app page **`/data-pipeline`**. Methods reference: **`/methods`**.

Related: `docs/migration_log.md` (historical migration notes), `docs/OPERATIONS_RUNBOOK.md` (rebuild counts and ops).

## Authoritative Watershed sources (Sep 9, 2026)

Documentation and UI wording for methods / Data Condition vocabulary should follow:

- StreamWatch Data Summary & Description (last updated September 9, 2026)
- StreamWatch Data Dictionary (last updated September 9, 2026)

Supporting Original Resources workbooks remain useful for ETL file names and sheets.

**Important caveat:** The final Sep 9 documentation package references an updated **All StreamWatch Data.xlsx**, but that workbook is **not present** in the current authoritative source folder. Do **not** assume the live/demo PostgreSQL database is fully aligned with final Watershed chemistry data until that workbook is confirmed and a deliberate refresh is planned.

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

Legacy ETL lookup seeds may still use shorter names (`Hanna`, `LaMotte`, `BACT`, …). Do not silently rename stored method values in this documentation-only update.

### Data Condition vocabulary (Sep 9 Dictionary)

Tags described as currently in use in the raw dataset:

Provisional, Incomplete, Outlier, Minor Deviation, Flagged, Corrected, Erroneous, Duplicate, Duplicate?

August 2026: full review of Data Condition tags completed (per Summary timeline).

App/database seed still includes additional historical codes (Accepted, Unchecked, Validated, Approved, Certified, …). Those are **app organization / legacy lookups**, not the Sep 9 Dictionary’s current raw-workbook tag list. Do not change schema or seed in a docs-only pass.

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

**Do not run a chemistry rebuild expecting the missing final Sep 9 All StreamWatch Data workbook until that file is confirmed available.**

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
| `etl/migrate_streamwatch_data.py` | Historical chem (+ attempted E. coli) | **Write** | Yes |
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

### Chemistry (historical) — `migrate_streamwatch_data.py`

- **Source:** `All StreamWatch Data.xlsx` → sheet **`ALL DATA` only** (hard-coded; never auto-loads watershed sheets)
- **Availability:** Final Sep 9 authoritative folder currently **missing** this workbook; ETL still expects the filename when a rebuild is run against whatever `STREAMWATCH_DATA_DIR` provides.
- **Dest:** `visit`, `chemical`, and bacteria only when an integer E. coli column matches aliases below
- **Chem fields:** Mapped via `CHEM_HEADER_ALIASES` in `chem_recon.py` (air/water temp, nitrate, phosphates, pH, turbidity, DO ppm/%DO, conductivity, **Chloride (mg/L)**)
- **Chloride:** Watershed documented a 2026 standard-preparation error; discrete-analyzer chloride results “to date” were divided by 10; newer candidate workbooks appear already corrected. ETL copies chloride as numbers after float parse + round — **there is no ÷10 (or ×10) correction in ETL.** A future refresh from a confirmed corrected workbook must **avoid double-correction**. Live DB alignment cannot be guaranteed until the final workbook is confirmed.
- **Duplicates:** Application fingerprint on site + date + method + rounded chem values; exact clones skipped; **differing same-day packages retained** (no `UNIQUE(visit_id)` on chemical)
- **Visits:** `ensure_visit(site_id, sample_date, sample_code=None, …)`
- **Skipped:** Missing site code; site code not in `site`; missing date; unresolved sites listed in `reports/chem_recon_*.json`
- **Not loaded from ALL DATA:** Per-watershed sheets (when present historically); RBP habitat columns; index columns (NJIS/HGMI/…); Gallery-style fields. Known watershed-only site/dates listed in `chem_recon.UNRESOLVED_WATERSHED_ONLY`
- **E. coli header mismatch (known issue — do not “fix” in a docs-only pass):**
  Current source / Dictionary variants use columns such as **`E. coli Result`** and **`E. coli mod.`**
  Current ETL looks for **`E. coli`**, `E coli`, `E_coli`, `e_coli_mpn_100ml`.
  Those names do not match, so historical Result values are typically **not inserted** by `migrate_streamwatch_data`. This needs a **future ETL review once the final workbook is confirmed**. Recent BACT bacteria primarily come from IDEXX (`migrate_bact_2025`).
- **Scientific values:** Inserted as mapped; no unit conversion beyond float/round.
- **Protected DB:** Refuses protected names before write.

### BACT Survey123 + IDEXX — `migrate_bact_2025.py` (+ `bact_reconcile.py`)

- **Source:** `BACT and HAB 2025 Data.xlsx` → `SURVEY123` / `Survey123`, `IDEXX` (**not** Gallery / Turbidity / Phycocyanin)
- **Survey123:** Match visits by site + **sample `Date`** (never `CreationDate`). Prefer matching `sample_code`. Fill **NULL chemical fields only**; do not overwrite non-null historical values. May fill `visit.sample_code` when NULL. Conflicts / unmatched logged in recon JSON.
- **Fields enriched:** water temp, nitrate, phosphate, turbidity, chloride (shared aliases)
- **IDEXX:** Match `visit.sample_code`; insert bacteria when integer MPN parses; skip existing `(visit_id, e_coli_mpn_100ml)`; skip censored / non-integer (`> 2419.6`, `< 1.0`, etc.)
- **Idempotency:** IDEXX skip-existing is re-run safe for identical MPN; Survey123 fill-NULL is generally safe; chemistry package inserts are not the primary path here
- **Preview:** `/imports/bact` uses the same parsing rules **read-only**

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

1. **Missing final All StreamWatch Data.xlsx** in the Sep 9 authoritative folder — blocks confident chemistry refresh / alignment claims.
2. **Chloride:** ETL does not apply the 2026 ÷10 correction; avoid double-correction on a future refresh from an already-corrected workbook.
3. **E. coli header mismatch** (`E. coli Result` / `E. coli mod.` vs ETL `E. coli`) — future ETL review after final workbook confirmation; **do not change ETL in a docs-only task**.
4. **Volunteer / equipment** re-runs can duplicate some child rows.
5. **Habitat assessments** and HAB phycocyanin not bulk-loaded.
6. **Gallery / Turbidity / Phycocyanin** sheets in BACT workbook not loaded by migrate.
7. **Watershed sheets** deliberately not co-loaded with ALL DATA (historical duplication).
8. **WQX** export is preparation CSV, not a full EPA submission package.
9. **Colilert vs Colisure** naming remains unresolved source ambiguity (timeline vs Methods table).
10. Ambiguous Watershed rules stay as review points — scripts skip or log rather than invent matches.

---

## App surfaces that call ETL modules

| Route | Module | Writes DB? |
|-------|--------|------------|
| `/imports/bact` | `bact_reconcile` | No (preview) |
| `/imports/hab` | `hab_status` | No |
| `/reports/bact` | `bact_scoring` | No |
| `/export/wqx` | `export_wqx` | No (download) |

Do not run destructive migrations solely to test documentation.
