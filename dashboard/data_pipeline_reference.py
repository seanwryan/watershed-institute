"""Static reference content for the internal StreamWatch Data Pipeline page."""

from __future__ import annotations

PIPELINE_SUBTITLE = (
    "How StreamWatch source files are cleaned, matched, and organized into "
    "the application database."
)

PIPELINE_OVERVIEW = (
    "Historical StreamWatch data came from multiple spreadsheets, databases, "
    "forms, and program-specific files. Python loading scripts (often called "
    "ETL) read those sources, standardize the records, connect related "
    "information, and load supported data into PostgreSQL so staff can work "
    "with it in this application."
)

ETL_DEFINITION = (
    "ETL stands for Extract, Transform, Load: "
    "Extract — read the source data; "
    "Transform — clean and organize it; "
    "Load — save it into the centralized database. "
    "Some tools only preview or export and do not load."
)

PIPELINE_RAW_DATA_NOTE = (
    "The database is not a byte-for-byte copy of every spreadsheet cell. "
    "It holds cleaned and structured records derived from the provided source "
    "files. Exact duplicates may be skipped, related rows are linked to sites "
    "and visits, some values are derived after load, and unresolved or "
    "unsupported cases are skipped or left for review rather than forced into "
    "a match."
)

FLOW_STEPS = [
    "Source Files",
    "Python ETL",
    "Cleaning & Matching",
    "PostgreSQL",
    "StreamWatch Application",
]

LINEAGE_ROWS = [
    {
        "area": "Sites",
        "source": "2025 StreamWatch Locations.xlsx (SWSites_2024)",
        "processing": "Normalize columns; upsert by site code",
        "destination": "site (+ lookups)",
        "status": "Loaded",
    },
    {
        "area": "Visits (from chemistry / BAT / BACT)",
        "source": "Created when results load",
        "processing": "Match or create by site, date, sample code",
        "destination": "visit",
        "status": "Loaded",
    },
    {
        "area": "Chemistry (historical)",
        "source": "All StreamWatch Data.xlsx → ALL DATA",
        "processing": "Map headers; skip exact package clones; keep differing same-day packages",
        "destination": "chemical",
        "status": "Loaded",
    },
    {
        "area": "Chemistry (Survey123 fill)",
        "source": "BACT and HAB 2025 Data.xlsx → Survey123",
        "processing": "Fill NULL fields only on matched visits",
        "destination": "chemical (update)",
        "status": "Loaded",
    },
    {
        "area": "Bacteria (IDEXX)",
        "source": "BACT and HAB 2025 Data.xlsx → IDEXX",
        "processing": "Attach by sample code; skip duplicates and censored values",
        "destination": "bacteria",
        "status": "Loaded",
    },
    {
        "area": "Volunteers / training / assignments",
        "source": "Volunteer_Tracking.xlsm",
        "processing": "Detect headers; link sites by code",
        "destination": "volunteer, training, training_log, junc_assignments",
        "status": "Loaded",
    },
    {
        "area": "Equipment / meter testing",
        "source": "CAT Meter Tracking v.1.xlsx",
        "processing": "Accept TWI### meters; parse quarterly test matrices",
        "destination": "equipment, sensor, session, meter_testing",
        "status": "Loaded",
    },
    {
        "area": "Macroinvertebrates",
        "source": "tblSampleDates.xlsx (preferred)",
        "processing": "Taxonomy + counts + RBP100; skip existing observations",
        "destination": "bug_list, bug_count, rbp100_bug",
        "status": "Loaded",
    },
    {
        "area": "Biology scores",
        "source": "Derived from bug tables",
        "processing": "HGMI / NJIS / CPMI formulas",
        "destination": "macro_analysis",
        "status": "Derived",
    },
    {
        "area": "QA flags",
        "source": "Derived after load",
        "processing": "Temperature / nitrate thresholds; meter-fail windows",
        "destination": "result_flag / data_condition",
        "status": "Derived",
    },
    {
        "area": "Habitat assessments (historical)",
        "source": "RBP columns on ALL DATA (and related forms)",
        "processing": "Not bulk-migrated",
        "destination": "habitat_assessment",
        "status": "Partially migrated",
    },
    {
        "area": "BACT import reconciliation",
        "source": "Uploaded BACT workbook",
        "processing": "Same matching rules as load; no automatic write from the page",
        "destination": "—",
        "status": "Preview only",
    },
    {
        "area": "HAB status",
        "source": "BACT and HAB workbook (Phycocyanin / Survey123)",
        "processing": "Workbook formulas mirrored for review",
        "destination": "— (phycocyanin not in PostgreSQL)",
        "status": "Preview only",
    },
    {
        "area": "BACT Analysis scores",
        "source": "2025 BACT Analysis.xlsx upload",
        "processing": "Seasonal rating preview",
        "destination": "—",
        "status": "Preview only",
    },
    {
        "area": "WQX",
        "source": "PostgreSQL",
        "processing": "Build preparation CSV (all chemistry packages)",
        "destination": "Download file",
        "status": "Export only",
    },
]

INTERPRETATION_NOTES = [
    {
        "title": "Multiple chemistry packages on one day can be legitimate",
        "body": (
            "The chemistry load keeps packages that differ in method or measured "
            "values on the same site and date. Only exact clones are skipped."
        ),
    },
    {
        "title": "Unresolved rows are not forced into matches",
        "body": (
            "Unknown site codes, missing dates, IDEXX rows without a matching "
            "sample code visit, and censored bacteria values are skipped or "
            "logged for review."
        ),
    },
    {
        "title": "Some BACT and HAB tools are reconciliation previews",
        "body": (
            "The Imports BACT and HAB pages help staff compare a workbook to "
            "the database. They do not automatically rewrite PostgreSQL. "
            "Bulk Survey123 / IDEXX loading is a separate migration script."
        ),
    },
    {
        "title": "Historical habitat is not fully bulk migrated",
        "body": (
            "Sites may carry a habitat type (for example High Gradient or "
            "Low Gradient). Full historical Rapid Bioassessment Protocol "
            "habitat score sheets are not loaded into habitat_assessment; "
            "staff can enter assessments in the application."
        ),
    },
    {
        "title": "Chloride is not divided by 10 again in the loading scripts",
        "body": (
            "The chemistry ETL maps Chloride (mg/L) as a number. It does not "
            "apply a second ÷10 correction. The Methods page documents the "
            "2026 source correction separately; confirm how any given value "
            "should be interpreted before drawing conclusions."
        ),
    },
    {
        "title": "Ambiguous Watershed rules stay as review points",
        "body": (
            "Where source authority or matching is unclear, the pipeline "
            "documents skips and conflicts instead of inventing cleanup rules."
        ),
    },
]

# Expandable pipeline cards for staff. `technical` is optional detail.
PIPELINE_SECTIONS = [
    {
        "id": "sites",
        "title": "Sites",
        "source": (
            "Workbook: 2025 StreamWatch Locations.xlsx. "
            "Sheet: SWSites_2024."
        ),
        "what_happens": (
            "Each row becomes a monitoring site. Waterbody, subwatershed, and "
            "priority labels are stored as linked lookups. Coordinates, access "
            "notes, and program priorities (CAT / BAT / BACT) are carried over "
            "when present."
        ),
        "where_it_goes": "PostgreSQL tables: site and related lookups.",
        "skipped": (
            "Rows without a usable site code are skipped. Re-running updates "
            "existing sites by site code instead of creating duplicates."
        ),
        "caveats": (
            "Habitat type on the site record is a classification, not a full "
            "historical habitat assessment."
        ),
        "technical": {
            "script": "etl/migrate_sites.py",
            "sheet": "SWSites_2024",
            "destination": "site, waterbody, subwatershed, priority lookups",
            "matching": "ON CONFLICT (site_code) DO UPDATE",
        },
    },
    {
        "id": "visits",
        "title": "Visits",
        "source": (
            "Visits are created while loading chemistry, bacteria, and "
            "macroinvertebrate sample events—not from a single standalone "
            "“visits only” workbook."
        ),
        "what_happens": (
            "The loader looks for an existing visit for the same site, sample "
            "date, and sample code (when present). If none exists, it creates one."
        ),
        "where_it_goes": "PostgreSQL table: visit.",
        "skipped": (
            "Results that cannot resolve to a known site or date never create "
            "a visit."
        ),
        "caveats": (
            "One visit can hold multiple chemistry packages and related "
            "bacteria or bug observations."
        ),
        "technical": {
            "script": "etl/visit_helpers.py (ensure_visit)",
            "sheet": "— (shared helper)",
            "destination": "visit",
            "matching": "(site_id, sample_date, sample_code IS NOT DISTINCT FROM …)",
        },
    },
    {
        "id": "chemistry",
        "title": "Chemistry",
        "source": (
            "Primary historical source: All StreamWatch Data.xlsx, sheet "
            "ALL DATA only. Additional NULL-fill enrichment can come from "
            "Survey123 in the BACT and HAB 2025 workbook."
        ),
        "what_happens": (
            "Headers such as Water Temperature, Nitrate, Phosphates, pH, "
            "Turbidity, DO ppm, %DO, Conductivity, and Chloride (mg/L) are "
            "mapped into chemistry columns. Exact duplicate packages (same "
            "site, date, method, and rounded values) are skipped. Packages "
            "that differ are kept even on the same day. Survey123 enrichment "
            "fills empty fields only and does not overwrite existing numbers."
        ),
        "where_it_goes": "PostgreSQL table: chemical (linked to visit).",
        "skipped": (
            "Unknown site codes; missing dates; exact duplicate packages; "
            "Survey123 rows with no matching visit or nothing left to fill. "
            "Per-watershed sheets are intentionally not bulk-imported alongside "
            "ALL DATA (that combination previously duplicated packages)."
        ),
        "caveats": (
            "ALL DATA also contains habitat and index-style columns that are "
            "not loaded by the chemistry script. Chloride is stored as read "
            "from the workbook—there is no second ÷10 adjustment in ETL."
        ),
        "technical": {
            "script": "etl/migrate_streamwatch_data.py; etl/migrate_bact_2025.py (Survey123)",
            "sheet": "ALL DATA; SURVEY123",
            "destination": "visit, chemical",
            "matching": "Chem fingerprint for exact dups; Survey123 by site+Date (+ sample code preferred)",
        },
    },
    {
        "id": "bacteria",
        "title": "Bacteria / IDEXX",
        "source": (
            "BACT and HAB 2025 Data.xlsx → IDEXX sheet for recent bacteria "
            "results. Historical ALL DATA E. coli columns use different header "
            "names than the chemistry script currently looks for, so those "
            "Result values are typically not loaded by that path."
        ),
        "what_happens": (
            "IDEXX rows are matched to visits by sample code. Integer E. coli "
            "MPN values are inserted. Values that cannot be parsed as integers "
            "(including censored results such as >2419.6) are skipped. "
            "Re-runs skip an identical visit + MPN pair."
        ),
        "where_it_goes": "PostgreSQL table: bacteria.",
        "skipped": (
            "Missing sample code; no visit with that sample code; censored or "
            "non-integer MPN; already-recorded identical pairs."
        ),
        "caveats": (
            "The in-app BACT import page is a read-only reconciliation preview "
            "using the same matching ideas."
        ),
        "technical": {
            "script": "etl/migrate_bact_2025.py; preview etl/bact_reconcile.py",
            "sheet": "IDEXX",
            "destination": "bacteria",
            "matching": "visit.sample_code; idempotent on (visit_id, e_coli_mpn_100ml)",
        },
    },
    {
        "id": "volunteers",
        "title": "Volunteers",
        "source": "Volunteer_Tracking.xlsm → Volunteers sheet.",
        "what_happens": (
            "Header rows are detected automatically when title rows sit above "
            "the table. Names, contact fields, status, and active CAT/BAT/BACT "
            "flags are loaded."
        ),
        "where_it_goes": "PostgreSQL table: volunteer (+ municipality lookup).",
        "skipped": "Rows with no first or last name.",
        "caveats": (
            "Re-running the volunteer migration inserts volunteers again; it is "
            "not fully idempotent. Prefer a clean database rebuild when reloading."
        ),
        "technical": {
            "script": "etl/migrate_volunteers.py",
            "sheet": "Volunteers",
            "destination": "volunteer",
            "matching": "Source VolunteerID mapped during a single run; no unique upsert on re-run",
        },
    },
    {
        "id": "training",
        "title": "Training & Assignments",
        "source": (
            "Volunteer_Tracking.xlsm → Trainings, TrainingLog, Assignments."
        ),
        "what_happens": (
            "Training sessions and attendance links are created. Assignments "
            "connect volunteers to sites (site codes resolved against the "
            "sites table)."
        ),
        "where_it_goes": "training, training_log, junc_assignments.",
        "skipped": (
            "Trainings without a date; log/assignment rows that cannot resolve "
            "volunteer or site."
        ),
        "caveats": "Sites_Live in the workbook is reference only; sites come from the sites migration.",
        "technical": {
            "script": "etl/migrate_volunteers.py",
            "sheet": "Trainings, TrainingLog, Assignments",
            "destination": "training, training_log, junc_assignments",
            "matching": "Assignments ON CONFLICT (volunteer_id, site_id) DO NOTHING",
        },
    },
    {
        "id": "equipment",
        "title": "Equipment",
        "source": "CAT Meter Tracking v.1.xlsx → Assignments (and Sensors).",
        "what_happens": (
            "Only meter IDs matching TWI plus three digits are treated as "
            "equipment inventory. Serial numbers are normalized carefully so "
            "text serials keep leading zeros."
        ),
        "where_it_goes": "equipment, sensor.",
        "skipped": (
            "LaMotte-user name rows and other non-TWI### Meter ID values."
        ),
        "caveats": (
            "The Tracking sheet is present in the workbook but not used by the "
            "current loader."
        ),
        "technical": {
            "script": "etl/migrate_equipment.py",
            "sheet": "Assignments, Sensors",
            "destination": "equipment, sensor",
            "matching": "ON CONFLICT (equipment_code) DO UPDATE",
        },
    },
    {
        "id": "meter-testing",
        "title": "Meter Testing",
        "source": "CAT Meter Tracking sheets 2024 Testing, 2025 Testing, 2026 Testing.",
        "what_happens": (
            "Wide quarterly matrices are parsed into dated Round blocks. "
            "Measured pH, DO (ppm), and conductivity values become meter_testing "
            "rows under a quarterly maintenance session."
        ),
        "where_it_goes": "session, meter_testing.",
        "skipped": (
            "Blocks without a confident test date; non-numeric measured cells; "
            "unknown meter codes."
        ),
        "caveats": (
            "Pass/fail is not invented from the matrix in this import. "
            "Re-running can duplicate session/test rows."
        ),
        "technical": {
            "script": "etl/migrate_equipment.py",
            "sheet": "2024/2025/2026 Testing",
            "destination": "session, meter_testing",
            "matching": "Inserts per parsed measurement (not re-run-safe)",
        },
    },
    {
        "id": "macro",
        "title": "Macroinvertebrates",
        "source": (
            "Preferred: tblSampleDates.xlsx (BugList, tblSampleDates, "
            "tblBugResults, tblRBP100Bugs)."
        ),
        "what_happens": (
            "Taxonomy is loaded into the bug list. Sample events become visits. "
            "Counts and 100-organism subsample counts are stored. Re-runs skip "
            "observations that already exist for the same visit and taxon."
        ),
        "where_it_goes": "bug_list, visit, bug_count, rbp100_bug.",
        "skipped": "Unresolved sites or unresolved bug identifiers; missing amounts.",
        "caveats": (
            "Index scores are calculated afterward by a separate step, not "
            "inside the BAT count loader."
        ),
        "technical": {
            "script": "etl/migrate_bat.py",
            "sheet": "BugList, tblSampleDates, tblBugResults, tblRBP100Bugs",
            "destination": "bug_list, visit, bug_count, rbp100_bug",
            "matching": "Skip existing (visit_id, bug_id); bug_list ON CONFLICT (bug_code)",
        },
    },
    {
        "id": "habitat",
        "title": "Habitat",
        "source": (
            "Site habitat type from the locations workbook. Historical RBP "
            "habitat score columns appear on ALL DATA but are not bulk-loaded. "
            "HAB bloom/phycocyanin status lives in the BACT and HAB workbook."
        ),
        "what_happens": (
            "High Gradient / Low Gradient (and related) types may be stored on "
            "the site. Staff can enter habitat assessments in the app. HAB "
            "status tools on Imports mirror workbook formulas for review only."
        ),
        "where_it_goes": (
            "site.habitat_type when migrated; habitat_assessment when staff "
            "enter data; HAB preview does not write phycocyanin to PostgreSQL."
        ),
        "skipped": "Bulk historical habitat score rows (not migrated in this milestone).",
        "caveats": "Canal and Lake scoring rules remain review topics for future work.",
        "technical": {
            "script": "etl/migrate_sites.py (type only); etl/hab_status.py (preview)",
            "sheet": "SWSites_2024; PHYCOCYANIN / SURVEY123 for HAB preview",
            "destination": "site.habitat_type; habitat_assessment (entry); preview only for HAB",
            "matching": "N/A for bulk historical habitat",
        },
    },
    {
        "id": "bact-recon",
        "title": "BACT reconciliation",
        "source": "Workbook uploaded on Imports → BACT (same structure as BACT and HAB 2025 Data.xlsx).",
        "what_happens": (
            "The app classifies Survey123 and IDEXX rows (ready to enrich, "
            "needs review, censored, needs visit match, and similar) using the "
            "same parsing helpers as the migration script."
        ),
        "where_it_goes": "Nowhere automatically—preview tables and downloads only.",
        "skipped": "Same unresolved classes as the write-path migration.",
        "caveats": "Read-only. Does not change review or write policy of the bulk migrate.",
        "technical": {
            "script": "etl/bact_reconcile.py",
            "sheet": "SURVEY123, IDEXX",
            "destination": "— (preview)",
            "matching": "Same rules as migrate_bact_2025",
        },
    },
    {
        "id": "hab-recon",
        "title": "HAB reconciliation",
        "source": "BACT and HAB workbook Phycocyanin and Survey123 sheets.",
        "what_happens": (
            "Derives HAB status strings from METADATA formulas (for example "
            "Elevated Phycocyanin, Reported to DEP, Flagged) and compares to "
            "workbook-stored values where available."
        ),
        "where_it_goes": "Preview only.",
        "skipped": "Does not load Gallery / Turbidity / Phycocyanin numeric series into PostgreSQL.",
        "caveats": "Manual DEP Watch/Advisory overrides are outside the calculated rule.",
        "technical": {
            "script": "etl/hab_status.py",
            "sheet": "PHYCOCYANIN, SURVEY123",
            "destination": "— (preview)",
            "matching": "Sample-code lookup for Survey123 HAB status",
        },
    },
    {
        "id": "wqx",
        "title": "WQX export",
        "source": "PostgreSQL monitoring data already in the application.",
        "what_happens": (
            "Builds a WQX-style preparation CSV: one result row per non-null "
            "characteristic. Every chemistry package on a visit is included. "
            "When a visit has multiple packages, activity IDs append -C plus "
            "the chemical id; multiple bacteria rows append -B plus the "
            "bacteria id."
        ),
        "where_it_goes": "Downloadable CSV (CLI or Export page)—not an import into PostgreSQL.",
        "skipped": "Null measurements; this is not a full EPA portal package.",
        "caveats": "Export / preparation logic only.",
        "technical": {
            "script": "etl/export_wqx.py",
            "sheet": "— (database)",
            "destination": "CSV download",
            "matching": "N/A (export)",
        },
    },
]
