# StreamWatch Operations Runbook

Repeatable procedures for workflows that are **validated and safe** with the current
codebase and supplied Watershed source files.

Baselines below describe the current `streamwatch_demo` dataset after a full
validated rebuild. They are **validation baselines for this dataset**, not permanent
business invariants.

Related docs: [migration_log.md](migration_log.md), [DEPLOYMENT.md](DEPLOYMENT.md),
[APP_TUTORIAL.md](APP_TUTORIAL.md), root [README.md](../README.md).

---

## 1. Database safety

### Rules

1. **Always set `DATABASE_URL` explicitly** before ETL or app work.
2. **Confirm the target** before any write migration:
   ```bash
   psql "$DATABASE_URL" -c "SELECT current_database(), current_user;"
   ```
3. Prefer **fresh verification/staging DBs** (e.g. `streamwatch_bat_verify`,
   `streamwatch_chem_verify`) for migration experiments.
4. **Do not casually re-run historical bulk ETL** against a shared demo or future
   production database.
5. Before destructive replacement (drop/create/restore), take a **dump/snapshot**.
6. Distinguish environments:
   | Role | Typical name / notes |
   |---|---|
   | Local demo | `postgresql://localhost/streamwatch_demo` |
   | Neon demo branch | Hosted branch used by Render for public demo |
   | Protected / archive | Default refuse list includes `streamwatch_final` |
   | Future production | Do not target until Watershed confirms |

### Protected databases

`etl/config.py` defines `refuse_if_protected_database()`. Historical chemistry and
BACT write migrations refuse protected names (default: `streamwatch_final`).

Override only deliberately:

```bash
export STREAMWATCH_PROTECTED_DBS=streamwatch_final,some_other_name
```

Sites / volunteers / equipment / BAT migrations do **not** currently call this
guard—still verify `current_database()` yourself.

### Baseline count check (read-only)

```bash
export DATABASE_URL=postgresql://localhost/streamwatch_demo
psql "$DATABASE_URL" -c "SELECT current_database(), current_user;"
psql "$DATABASE_URL" <<'SQL'
SELECT 'site' AS t, COUNT(*) FROM site
UNION ALL SELECT 'visit', COUNT(*) FROM visit
UNION ALL SELECT 'chemical', COUNT(*) FROM chemical
UNION ALL SELECT 'bacteria', COUNT(*) FROM bacteria
UNION ALL SELECT 'volunteer', COUNT(*) FROM volunteer
UNION ALL SELECT 'training', COUNT(*) FROM training
UNION ALL SELECT 'training_log', COUNT(*) FROM training_log
UNION ALL SELECT 'junc_assignments', COUNT(*) FROM junc_assignments
UNION ALL SELECT 'equipment', COUNT(*) FROM equipment
UNION ALL SELECT 'session', COUNT(*) FROM session
UNION ALL SELECT 'meter_testing', COUNT(*) FROM meter_testing
UNION ALL SELECT 'bug_list', COUNT(*) FROM bug_list
UNION ALL SELECT 'bug_count', COUNT(*) FROM bug_count
UNION ALL SELECT 'rbp100_bug', COUNT(*) FROM rbp100_bug
UNION ALL SELECT 'macro_analysis', COUNT(*) FROM macro_analysis
UNION ALL SELECT 'result_flag', COUNT(*) FROM result_flag
UNION ALL SELECT 'habitat_assessment', COUNT(*) FROM habitat_assessment
ORDER BY 1;
SQL
```

### Do not

- Paste Neon or Render secrets into docs, tickets, or commits
- Assume a Neon URL is the demo branch without checking the Neon console
- Point write ETL at Neon until the branch is verified and a snapshot exists

---

## 2. Clean database rebuild

Use only when intentionally rebuilding a **writable** local/staging database.
Place source workbooks under `data/` (or set `STREAMWATCH_DATA_DIR`).

```bash
# Example: rebuild a writable local DB (NOT streamwatch_final; prefer a named verify DB)
export DATABASE_URL=postgresql://localhost/YOUR_WRITABLE_DB
psql "$DATABASE_URL" -c "SELECT current_database(), current_user;"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/run_schema.sql

python -m etl.migrate_sites
python -m etl.migrate_volunteers
python -m etl.migrate_equipment
python -m etl.migrate_streamwatch_data
python -m etl.migrate_bact_2025
python -m etl.migrate_bat
python -m etl.biological_indices
python -m etl.apply_qa_rules
```

Order notes:

- Sites must precede visits/results (foreign keys).
- Chemistry before BACT (Survey123 enrich / IDEXX attach to existing visits).
- BAT before biological indices.
- Indices then QA (QA flags chemistry; indices use bug tables).
- Root `README.md` uses this same rebuild sequence.

### Expected `streamwatch_demo` baselines (current dataset)

| Table | Count |
|---|---:|
| site | 168 |
| visit | 17221 |
| chemical | 17313 |
| bacteria | 544 |
| volunteer | 428 |
| training | 55 |
| training_log | 181 |
| junc_assignments | 66 |
| equipment | 25 |
| session | 21 |
| meter_testing | 629 |
| bug_list | 1625 |
| bug_count | 1301 |
| rbp100_bug | 1227 |
| macro_analysis | 108 |
| result_flag | 40 |
| habitat_assessment | 0 |

Habitat type distribution (`site.habitat_type`):

| Type | Count |
|---|---:|
| High Gradient | 86 |
| Low Gradient | 43 |
| Lake | 36 |
| Canal | 1 |
| NULL | 2 |

### Do not

- Rebuild `streamwatch_demo` casually once it is the shared local baseline
- Dual-load ALL DATA + watershed chemistry sheets
- Treat these counts as forever-fixed product requirements

---

## 3. Sites refresh

**Source:** `data/2025 StreamWatch Locations.xlsx` (sheet `SWSites_2024`)  
**Command:** `python -m etl.migrate_sites`  
**Script:** `etl/migrate_sites.py`

### Expect

- ~168 sites after a clean load from the current Locations workbook
- Habitat type mapped from source aliases including `HabitatType` / `Habitat type`
- Lookups created/reused for waterbody, subwatershed, priorities, groundtruthing

### Verify

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM site;"
psql "$DATABASE_URL" -c "SELECT habitat_type::text, COUNT(*) FROM site GROUP BY 1 ORDER BY 1 NULLS LAST;"
```

### Caveats

- Do not invent missing habitat classifications.
- Municipality / multi-junction completeness may be incomplete relative to every
  Access-era association—spot-check critical sites rather than assuming full
  junction parity.

### Do not

- Use Sites refresh as a place to invent Canal/Lake habitat scoring rules

---

## 4. Volunteer / training / assignment refresh

**Source:** `data/Volunteer_Tracking.xlsm`  
**Command:** `python -m etl.migrate_volunteers`  
**Script:** `etl/migrate_volunteers.py`

### Expect (current dataset)

- volunteer 428  
- training 55  
- training_log 181  
- junc_assignments 66  

### Behavior

- Header row detection below title rows (`VolunteerID`, `TrainingID`, etc.)
- `Street` → `volunteer.address`
- `DPID` → `perfect_id` when present
- Assignment `SiteID` values that are non-numeric are treated as `site_code`

### Caveats / limitations

- Parent volunteer links, phone formatting, and ZIP padding are not fully normalized
- Role alias normalization may be incomplete
- DonorPerfect sync is **not** implemented (Perfect ID is stored when present)
- After go-live, the **web Volunteers UI** can maintain profiles, trainings, and
  assignments—spreadsheet refresh is not automatically the ongoing source of truth

### Do not

- Declare spreadsheet vs app as official SoT without Watershed confirmation
- Automate DonorPerfect bidirectional sync from this runbook

---

## 5. Equipment / meter test refresh

**Source:** `data/CAT Meter Tracking v.1.xlsx`  
**Command:** `python -m etl.migrate_equipment`  
**Script:** `etl/migrate_equipment.py`

### Expect (current dataset)

- equipment 25 (TWI + three digits only; LaMotte-user name rows skipped)
- session 21  
- meter_testing 629  

### Behavior

- Assignments sheet → inventory (`TWI###`)
- `2024` / `2025` / `2026 Testing` wide matrices → `session` + `meter_testing`
  (pH, DO ppm, Cond/EC when numeric)

### Limitations (not populated by this ETL)

- `pass_fail` from Tracking codes  
- `sensor`, `meter_maintenance`, `calibration_log`, `equipment_loans`, `temp_corrections`  
- Thermometer calibration spreadsheet (not in current packet / not migrated)

### Ongoing ops

Staff can enter meter tests in the web UI (`/equipment/.../meter-tests/new`) after
migration. Spreadsheet refresh and UI entry are separate paths.

---

## 6. Historical chemistry rebuild

**Source:** `data/All StreamWatch Data.xlsx`  
**Sheet:** **`ALL DATA` only**  
**Command:** `python -m etl.migrate_streamwatch_data`  
**Script:** `etl/migrate_streamwatch_data.py`  
**Recon:** `reports/chem_recon_<dbslug>.json` (gitignored)

### Expect

- On a clean full rebuild with the current workbook: **chemical ≈ 17,313**
- Exact-package dedupe skips clones; **differing** same-day packages are retained
  (no `UNIQUE(visit_id)` on chemical)

### Why 17,313 ≠ spreadsheet row count

ALL DATA has ~18.5k rows including non-chemistry / incomplete rows; exact duplicate
packages are skipped; unresolved site codes are not imported. Watershed per-sheet
rows are **not** bulk-loaded (they largely overlap ALL DATA and previously caused
~2× duplication).

### Technical source caveat

ALL DATA is the **evidence-supported technical primary** pending Watershed
confirmation of official authority (`docs/migration_log.md`).

### Do not

- Bulk-load watershed sheets on top of ALL DATA
- Run against protected DB names without deliberate override
- Expect historical ALL DATA `E. coli` and IDEXX season bacteria to be the same
  authority without staff policy

---

## 7. BACT season process

**Source:** `data/BACT and HAB 2025 Data.xlsx`  
**Write command:** `python -m etl.migrate_bact_2025`  
**Script:** `etl/migrate_bact_2025.py`  
**Staff preview (read-only):** `/imports` → `/imports/bact`

### Supported sheets

| Sheet | Write behavior |
|---|---|
| SURVEY123 | Fill **NULL** chemistry fields only; never overwrite non-null |
| IDEXX | Attach E. coli by `visit.sample_code`; skip if `(visit_id, e_coli_mpn)` exists |
| GALLERY / TURBIDITY / PHYCOCYANIN | **Not loaded** |

### Staff preview workflow (preferred before any future write UI)

1. Open `/imports/bact`
2. Upload the season workbook (`.xlsx`)
3. Review Survey123 / IDEXX categories
4. Download reconciliation CSV if needed

Preview **does not write** visits, chemistry, bacteria, or sample codes.  
**No Confirm Import** button exists yet.

### Current-dataset observations (`streamwatch_demo` + historical 2025 workbook)

These describe the **current** supplied season file against the current demo DB—not
hard expectations for future seasons.

Survey123: reviewed 623 · ready to enrich 0 · nothing to update 597 · needs review 19 · invalid 7  

IDEXX: reviewed 695 · ready to add 0 · already recorded 544 · needs visit match 93 · censored 57 · invalid 1  

### Write-path notes

- Censored IDEXX values (`> 2419.6`, `< 1.0`) remain unparsed / skipped
- Unresolved sample codes are skipped (do not invent visits)
- Protected DB refuse applies to this write migration

### Do not

- Import Gallery via this pipeline
- Convert censored MPN to arbitrary integers
- Treat preview counts as season SLAs

---

## 8. BAT process

**Primary source:** `data/tblSampleDates.xlsx`  
(Sheets: `BugList`, `tblSampleDates`, `tblBugResults`, `tblRBP100Bugs`)  
**Commands:**

```bash
python -m etl.migrate_bat
python -m etl.biological_indices
```

**Scripts:** `etl/migrate_bat.py`, `etl/biological_indices.py`

### Expect (current dataset)

- bug_list 1625  
- bug_count 1301  
- rbp100_bug 1227  
- macro_analysis 108 (after indices)

### Idempotency (as of `d0b6765`)

Application-level fingerprints—**no new UNIQUE constraints**:

- visit: `(site_id, sample_date, sample_code)` via `ensure_visit`
- bug_list: `ON CONFLICT (bug_code) DO NOTHING`
- bug_count / rbp100_bug: skip when `(visit_id, bug_id)` already exists

A **second identical run** against the same DB/source should insert **0**
`bug_count` and **0** `rbp100_bug` rows and leave macro scores unchanged after
recalculation.

### Limitations

- Changed source amounts for an existing `(visit_id, bug_id)` are not refreshed on re-run
- Unresolved site/bug codes are skipped
- Lily consolidation site-tab formats are not a staff-ready import path
- BATSITES COLLECTED is unused when `tblSampleDates.xlsx` is present

---

## 9. QA rules

**Command:** `python -m etl.apply_qa_rules`  
**Script:** `etl/apply_qa_rules.py`  
**Review UI:** `/qa`

### What it does today

1. **Exceedances:** flag chemistry when `water_temp_c > 31` or nitrate > 10 ppm
   (`nitrate_ug_l > 10000`); set `data_condition` Flagged + `result_flag` Exceedance
2. **Meter-fail window:** if visit has `equipment_id` and linked `meter_testing.pass_fail`
   indicates failure in a temporal window around the sample, add Meter_Failed_Test flags

### What it is not

- Not full scientific QA / WQX validation
- Meter-fail effectiveness depends on `pass_fail` and visit–equipment linkage; historical
  equipment ETL often leaves `pass_fail` empty, so meter-fail flags may be sparse
- Gallery blanks, LaMotte “questionable volunteer,” and calibration-window policies remain
  unresolved (see Data Questions)

---

## 10. Biological indices

**Command:** `python -m etl.biological_indices`  
**Script:** `etl/biological_indices.py`  
**UI:** `/scores` and per-visit macro workspace (recalculate one visit)

### Behavior

- Writes/upserts `macro_analysis` on `visit_id`
- Prefers `rbp100_bug` when subsample total qualifies (≥ 50); else non-excluded `bug_count`
- Uses site drainage area when present for area-adjusted metrics
- Formulas are code-owned—do not “edit scores” by hand in the UI

---

## 11. WQX-style export

**UI:** `/export`  
**API:** `GET /export/wqx`  
**CLI:**

```bash
python -m etl.export_wqx wqx_export.csv [date_start] [date_end] [site1,site2]
```

**Script:** `etl/export_wqx.py`

### Output

Preparation CSV columns:

`MonitoringLocationIdentifier`, `ActivityIdentifier`, `ActivityStartDate`,
`CharacteristicName`, `ResultMeasureValue`, `ResultMeasure/MeasureUnitCode`

Includes selected chemistry parameters and E. coli when present.  
**Multi-package chemistry is preserved** (distinct activity IDs when a visit has
multiple chemical packages)—fixed in `9d627fb`.

### Gaps vs real EPA / 2024 TWI WQX Submission

Not a portal-ready package: missing full habitat/phys/bio/index sheets, projects,
QAPP metadata, and many WQX domains present in `2024 TWI WQX Submission.xlsx`.

UI wording: **WQX-style** — not direct EPA submission.

---

## 12. Reporting

| Route | Purpose |
|---|---|
| `/reports` | Staff report directory |
| `/reports/sites` | Site operational summary (+ CSV) |
| `/reports/visits` | Visit history / coverage flags (+ CSV) |
| `/reports/completeness` | Coverage review (not automatic “errors”) |
| `/reports/training` | Training / expiration review (+ CSV) |
| `/reports/assignments` | Volunteer–site assignment coverage (+ CSV) |
| `/reports/results` | Chemistry/bacteria extract; multi-package preserved (+ CSV) |

Reports are **read-only**. Completeness gaps are coverage, not invented compliance failures.

---

## 13. Local app / demo

```bash
export DATABASE_URL=postgresql://localhost/streamwatch_demo
psql "$DATABASE_URL" -c "SELECT current_database(), current_user;"
python dashboard/app.py
```

Default URL: `http://localhost:5000` (override with `PORT`).

Useful staff paths: `/`, `/sites`, `/map`, `/explore`, `/qa`, `/reports`, `/imports`,
`/export`, `/volunteers`, `/equipment`, `/scores`.

### Public architecture (high level)

```
GitHub main  →  Render web service  →  Neon Postgres (demo branch)
```

Render `DATABASE_URL` must point at the **intended Neon branch**. See
[DEPLOYMENT.md](DEPLOYMENT.md) for host settings (no credentials in this runbook).

---

## 14. Neon demo refresh

Validated pattern (no secrets):

1. Confirm local demo is healthy (counts + habitat distribution).
2. Dump local demo (custom format):
   ```bash
   pg_dump -Fc -f streamwatch_demo.dump "$LOCAL_DEMO_URL"
   ```
3. Verify archive (file size / `pg_restore -l`).
4. Confirm **destination** Neon branch identity in the Neon console (name/branch), then:
   ```bash
   pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error \
     -d "$NEON_DEMO_URL" streamwatch_demo.dump
   ```
5. Re-check counts and habitat distribution on Neon.
6. Confirm Render `DATABASE_URL` still targets that demo branch; redeploy if needed.

### Warn

- Always verify the Neon branch **before** restore
- Never assume a Neon URL is demo
- Do not restore onto an unverified production branch
- `--clean` can drop objects; a failed mid-restore may leave a partial schema—use
  `--exit-on-error` and be prepared to restore again from a known-good dump

---

## 15. Troubleshooting / known pitfalls

| Issue | Note |
|---|---|
| Wrong `DATABASE_URL` | Always `SELECT current_database()` first |
| Failed restore after `--clean` | Objects may already be dropped; restore again from dump |
| openpyxl “Unknown extension” | Common Excel warning; usually ignorable |
| Flask port in use | Set `PORT=5001` or free the port |
| Old verify DBs | `streamwatch_*_verify` are experiments, not canonical |
| Excel used-range inflation | Wide sheets (e.g. Assignments) look larger than real data |
| Header offset | Volunteer/equipment sheets need detected header rows |
| `"nan"` strings | Guard against Excel NaN → text |
| HabitatType alias | Sites ETL accepts `HabitatType` / `Habitat type` |
| BAT re-run duplication | Fixed (`d0b6765`): `(visit_id, bug_id)` skip |
| BACT censored IDEXX | Preview labels censored; write path still skips |
| WQX multi-package | Fixed (`9d627fb`): exporter emits all chemistry packages |

---

## 16. Do not automate without confirmation

| Workflow | Why blocked |
|---|---|
| Gallery chemistry import | Analyte map (Nitrite/TON/PO4 High-Low), negatives/blanks, merge policy unresolved |
| Historical ALL DATA E. coli merge with IDEXX | Dual bacteria authority not confirmed |
| Censored IDEXX conversion (`>2419.6`) | No storage policy; schema is integer MPN |
| Meter-failure QA window policy | Data Questions open; historical `pass_fail` sparse |
| Habitat Canal / Lake scoring | App supports High/Low Gradient entry; other types blocked pending rules |
| Habitat bulk from Erin Google Form | Form export sample / encoding not confirmed |
| DonorPerfect sync | No DP file/SoT/direction confirmed |
| AGO / ArcGIS live API | Goals only; Survey123 file export is the current path |
| Thermometer / calibration historical import | Source incomplete; tables largely empty |
| BACT scoring / report-card automation | Policy and scoring workbook not productized in DB |

---

## Quick command index

```bash
export DATABASE_URL=postgresql://localhost/streamwatch_demo   # or verified writable target
psql "$DATABASE_URL" -c "SELECT current_database(), current_user;"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/run_schema.sql
python -m etl.migrate_sites
python -m etl.migrate_volunteers
python -m etl.migrate_equipment
python -m etl.migrate_streamwatch_data
python -m etl.migrate_bact_2025
python -m etl.migrate_bat
python -m etl.biological_indices
python -m etl.apply_qa_rules

python -m etl.export_wqx wqx_export.csv 2020-01-01 2025-12-31
python dashboard/app.py
```

Staff preview (no writes): open `/imports/bact`.
