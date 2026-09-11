"""Static reference content for the internal StreamWatch Data Pipeline page."""

from __future__ import annotations

PIPELINE_SUBTITLE = (
    "How StreamWatch source files are cleaned, matched, and organized for use "
    "in the application."
)

ETL_DEFINITION = (
    "ETL means Extract, Transform, Load: read the source files, clean and "
    "organize the records, then load supported data into StreamWatch."
)

# Kept for tests / older callers; not shown on the compact page by default.
PIPELINE_OVERVIEW = ETL_DEFINITION
PIPELINE_RAW_DATA_NOTE = (
    "StreamWatch holds cleaned records derived from source files—not a "
    "cell-by-cell spreadsheet copy."
)
PIPELINE_SOURCE_CAVEAT = (
    "Primary chemistry source: All StreamWatch Data.xlsx (ALL DATA), plus "
    "supporting files for sites, volunteers, equipment, bacteria, and macros."
)

FLOW_STEPS = [
    "Source files",
    "Clean & match",
    "StreamWatch database",
    "Website",
]

LINEAGE_ROWS = [
    {
        "area": "Sites",
        "source": "2025 StreamWatch Locations.xlsx (SWSites_2024)",
        "processing": "Normalize columns; update by site code",
        "destination": "Sites",
        "status": "Loaded",
    },
    {
        "area": "Visits",
        "source": "Created when results load",
        "processing": "Match or create by site, date, sample code",
        "destination": "Visits",
        "status": "Loaded",
    },
    {
        "area": "Chemistry (historical)",
        "source": "All StreamWatch Data.xlsx → ALL DATA",
        "processing": "Map headers; skip exact duplicates",
        "destination": "Chemistry",
        "status": "Loaded",
    },
    {
        "area": "Chemistry (Survey123 fill)",
        "source": "BACT and HAB 2025 Data.xlsx → Survey123",
        "processing": "Fill empty fields on matched visits",
        "destination": "Chemistry",
        "status": "Loaded",
    },
    {
        "area": "Bacteria (IDEXX)",
        "source": "BACT and HAB 2025 Data.xlsx → IDEXX",
        "processing": "Match by sample code; skip censored values",
        "destination": "Bacteria",
        "status": "Loaded",
    },
    {
        "area": "Volunteers / training / assignments",
        "source": "Volunteer_Tracking.xlsm",
        "processing": "Detect headers; link sites by code",
        "destination": "Volunteers & training",
        "status": "Loaded",
    },
    {
        "area": "Equipment / meter testing",
        "source": "CAT Meter Tracking v.1.xlsx",
        "processing": "TWI### meters; quarterly test matrices",
        "destination": "Equipment",
        "status": "Loaded",
    },
    {
        "area": "Macroinvertebrates",
        "source": "tblSampleDates.xlsx (preferred)",
        "processing": "Taxonomy, counts, RBP100",
        "destination": "Bug data",
        "status": "Loaded",
    },
    {
        "area": "Biology scores",
        "source": "Derived from bug tables",
        "processing": "HGMI / NJIS / CPMI",
        "destination": "Scores",
        "status": "Derived",
    },
    {
        "area": "QA flags",
        "source": "Derived after load",
        "processing": "Thresholds; meter-fail windows",
        "destination": "Flags",
        "status": "Derived",
    },
    {
        "area": "Habitat assessments (historical)",
        "source": "RBP columns on ALL DATA",
        "processing": "Not bulk-loaded",
        "destination": "Habitat",
        "status": "Partially loaded",
    },
    {
        "area": "BACT / HAB import tools",
        "source": "Uploaded workbooks",
        "processing": "Preview / reconcile only",
        "destination": "—",
        "status": "Preview only",
    },
    {
        "area": "WQX",
        "source": "StreamWatch monitoring data",
        "processing": "Preparation CSV",
        "destination": "Download",
        "status": "Export only",
    },
]

# Short bullets for an optional collapsed notes block (not shown as a long top section).
INTERPRETATION_NOTES = [
    {
        "title": "Same-day chemistry packages",
        "body": "Differing packages on the same site/date are kept; only exact duplicates are skipped.",
    },
    {
        "title": "Unresolved rows",
        "body": "Unknown sites, missing dates, unmatched IDEXX sample codes, and censored bacteria values are skipped for review.",
    },
    {
        "title": "Import previews",
        "body": "BACT and HAB import pages compare workbooks to StreamWatch and do not write data automatically.",
    },
    {
        "title": "Habitat",
        "body": "Historical RBP habitat score sheets are not fully bulk-loaded; staff can enter assessments in the app.",
    },
    {
        "title": "Chloride",
        "body": "2026 discrete-analyzer chloride values were corrected by dividing by 10 in the source; do not divide again.",
    },
]

# Expandable pipeline cards for staff. `technical` is optional detail.
PIPELINE_SECTIONS = [
    {
        "id": "sites",
        "title": "Sites",
        "summary": [
            'Source: 2025 StreamWatch Locations.xlsx (SWSites_2024)',
            'Loads monitoring sites and related lookups by site code',
            'Rows without a usable site code are skipped',
        ],
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
        "where_it_goes": "Sites and related lookups in StreamWatch.",
        "skipped": (
            "Rows without a usable site code are skipped. Reloading updates "
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
        "summary": [
            'Created when chemistry, bacteria, or macro results load',
            'Matched by site, sample date, and sample code when present',
            'One visit can hold multiple chemistry packages',
        ],
        "source": (
            "Visits are created while loading chemistry, bacteria, and "
            "macroinvertebrate sample events—not from a single standalone "
            "“visits only” workbook."
        ),
        "what_happens": (
            "StreamWatch looks for an existing visit for the same site, sample "
            "date, and sample code (when present). If none exists, it creates one."
        ),
        "where_it_goes": "Visits in StreamWatch.",
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
        "summary": [
            'Source: All StreamWatch Data.xlsx → ALL DATA',
            'Keeps differing same-day packages; skips exact duplicates',
            'Chloride already includes the 2026 ÷10 correction',
        ],
        "source": (
            "Primary historical source: All StreamWatch Data.xlsx, sheet "
            "ALL DATA (the workbook also has START HERE / SITES / SITE FINDER "
            "sheets that are not used for chemistry loading). Survey123 empty-"
            "field fill is a separate step."
        ),
        "what_happens": (
            "Headers such as Water Temperature (°C), Nitrate (mg/L), Phosphate "
            "(mg/L), pH, Turbidity (JTU/NTU), DO (ppm), Conductivity (µS/cm), and "
            "Chloride (mg/L) become chemistry results. Exact duplicate "
            "packages are skipped; differing same-day packages are kept. Method "
            "values include CAT: Hanna, CAT: LaMotte, CAT: Early LaMotte, BACT, "
            "BAT, and Salt Watch. Survey123 enrichment fills empty fields only."
        ),
        "where_it_goes": "Chemistry results linked to visits.",
        "skipped": (
            "Unknown site codes; missing dates; exact duplicate packages; "
            "Survey123 rows with no matching visit or nothing left to fill. "
            "Per-watershed sheets are intentionally not loaded alongside "
            "ALL DATA (that combination previously duplicated packages)."
        ),
        "caveats": (
            "Habitat and index columns on ALL DATA are not loaded with "
            "chemistry. Chloride values already include Watershed’s 2026 "
            "correction—do not divide by 10 again."
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
        "summary": [
            'Recent: BACT and HAB workbook → IDEXX (by sample code)',
            'Historical E. coli from ALL DATA when present',
            'Censored / non-integer MPN values are skipped',
        ],
        "source": (
            "BACT and HAB 2025 Data.xlsx → IDEXX for recent bacteria. "
            "Historical ALL DATA E. coli Result values are loaded with "
            "chemistry when present (modifier text is kept when available)."
        ),
        "what_happens": (
            "IDEXX rows are matched to visits by sample code. Integer E. coli "
            "MPN values are stored. Values that cannot be read as integers "
            "(including censored results such as >2419.6) are skipped. "
            "Reloading skips an identical visit + MPN pair."
        ),
        "where_it_goes": "Bacteria results in StreamWatch.",
        "skipped": (
            "Missing sample code; no visit with that sample code; censored or "
            "non-integer MPN; already-recorded identical pairs."
        ),
        "caveats": (
            "The in-app BACT import page is a read-only review preview using "
            "the same matching ideas."
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
        "summary": [
            'Source: Volunteer_Tracking.xlsm → Volunteers',
            'Loads names, contact fields, status, and program flags',
            'Rows without a first or last name are skipped',
        ],
        "source": "Volunteer_Tracking.xlsm → Volunteers sheet.",
        "what_happens": (
            "Header rows are detected automatically when title rows sit above "
            "the table. Names, contact fields, status, and active CAT/BAT/BACT "
            "flags are loaded."
        ),
        "where_it_goes": "Volunteer records (and municipality lookup).",
        "skipped": "Rows with no first or last name.",
        "caveats": (
            "Reloading volunteers can create duplicate people if the same "
            "workbook is loaded again. Prefer a clean rebuild when reloading "
            "volunteers from scratch."
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
        "summary": [
            'Source: Trainings, TrainingLog, Assignments sheets',
            'Links volunteers to trainings and sites',
            'Unresolved volunteer or site rows are skipped',
        ],
        "source": (
            "Volunteer_Tracking.xlsm → Trainings, TrainingLog, Assignments."
        ),
        "what_happens": (
            "Training sessions and attendance links are created. Assignments "
            "connect volunteers to sites (site codes resolved against the "
            "sites table)."
        ),
        "where_it_goes": "Training sessions, attendance, and site assignments.",
        "skipped": (
            "Trainings without a date; log/assignment rows that cannot resolve "
            "volunteer or site."
        ),
        "caveats": "Sites_Live in the workbook is reference only; monitoring sites come from the Locations workbook.",
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
        "summary": [
            'Source: CAT Meter Tracking → Assignments / Sensors',
            'Only TWI### meter IDs become equipment',
            'Non-TWI Meter ID rows are skipped',
        ],
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
            "The Tracking sheet is present in the workbook but is not used when "
            "loading equipment."
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
        "summary": [
            'Source: 2024 / 2025 / 2026 Testing sheets',
            'Parses quarterly rounds into meter test records',
            'Non-numeric or undated blocks are skipped',
        ],
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
        "summary": [
            'Source: tblSampleDates.xlsx (preferred)',
            'Loads taxonomy, counts, and RBP100 subsample counts',
            'Existing visit + taxon observations are skipped on reload',
        ],
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
        "summary": [
            'Site habitat type may load from Locations',
            'Historical RBP habitat score sheets are not bulk-loaded',
            'HAB status tools are preview only',
        ],
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
            "Habitat type on the site when available; habitat assessments when "
            "staff enter them; HAB preview does not store phycocyanin in "
            "StreamWatch."
        ),
        "skipped": "Bulk historical habitat score rows (not loaded).",
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
        "summary": [
            'Upload preview for Survey123 and IDEXX rows',
            'Same matching ideas as the bulk bacteria load',
            'Does not change stored StreamWatch data',
        ],
        "source": "Workbook uploaded on Imports → BACT (same structure as BACT and HAB 2025 Data.xlsx).",
        "what_happens": (
            "The app classifies Survey123 and IDEXX rows (ready to enrich, "
            "needs review, censored, needs visit match, and similar) using the "
            "same matching rules as the bulk bacteria load."
        ),
        "where_it_goes": "Nowhere automatically—preview tables and downloads only.",
        "skipped": "Same unresolved classes as the bulk bacteria load.",
        "caveats": "Read-only review. Does not change how bulk loads are handled.",
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
        "summary": [
            'Preview HAB status from Phycocyanin / Survey123',
            'Compares calculated status to workbook values',
            'Does not store phycocyanin in StreamWatch',
        ],
        "source": "BACT and HAB workbook Phycocyanin and Survey123 sheets.",
        "what_happens": (
            "Derives HAB status strings from METADATA formulas (for example "
            "Elevated Phycocyanin, Reported to DEP, Flagged) and compares to "
            "workbook-stored values where available."
        ),
        "where_it_goes": "Preview only.",
        "skipped": "Does not store Gallery / Turbidity / Phycocyanin numeric series in StreamWatch.",
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
        "summary": [
            'Builds a WQX-style preparation CSV for download',
            'Includes every chemistry package on a visit',
            'Export only — not an import',
        ],
        "source": "Monitoring data already stored in StreamWatch.",
        "what_happens": (
            "Builds a WQX-style preparation CSV: one result row per non-null "
            "characteristic. Every chemistry package on a visit is included. "
            "When a visit has multiple packages, activity IDs append -C plus "
            "the chemical id; multiple bacteria rows append -B plus the "
            "bacteria id."
        ),
        "where_it_goes": "Downloadable CSV (Export page)—not an import into StreamWatch.",
        "skipped": "Empty measurements; this is not a full EPA portal package.",
        "caveats": "Export / preparation only.",
        "technical": {
            "script": "etl/export_wqx.py",
            "sheet": "— (database)",
            "destination": "CSV download",
            "matching": "N/A (export)",
        },
    },
]
