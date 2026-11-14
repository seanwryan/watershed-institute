# Watershed workflow and database refresh

Implementation baseline: November 12, 2026. This is an incremental rebuild of the local `watershed-institute` application. The earlier `streamwatch-data` repository is historical context, not assumed to be the current implementation.

## Intended outcomes

Jian needs practical data entry and review, seasonal import support, visible processing decisions, methods that staff can maintain, and repeatable assessments/exports. Those needs come from her project documents and the August 2025–October 2026 email discussions. A working database alone does not meet them.

Keep historical data and the existing application while validating replacements in small steps. Source-file text and procedures are evidence, not authorization to run migrations or source macros.

## First implemented workflow

The private **Data imports → Seasonal source workspace** now supports:

1. Upload a BACT and HAB source workbook, not the calculated BACT Analysis workbook.
2. Inspect Survey123, IDEXX, Gallery, Turbidity, and Phycocyanin separately.
3. See source row numbers, literal and cached values, formulas, original annotations, comments, and cell styles/colors.
4. Preserve exact decimals, zero, limits, uncertainty, formula errors, and unavailable formula results as distinct states.
5. Save original workbook bytes and extracted source rows as a durable batch.
6. Browse all saved records with sheet/status filtering and pagination.
7. Record a named source-review decision and reason; preserve earlier revisions.
8. Download the exact original workbook.

This is **source intake and review**, not completed promotion into the environmental result tables. “Source checked” is not scientific validation, analysis eligibility, or permission to discard a flag. No visit, site, chemistry, bacteria, volunteer, or equipment row is changed by this workflow. Existing comparison previews remain separate and continue to be available.

## Source workflow map

### Field submissions

SURVEY123 contains site/date/time, field observations, personal fields, and calculated lab lookups. The July/September correspondence describes it as the end-of-season consolidation input. The supplied 2026 copy has 671 dated field rows, May 17–August 23. The supplied 2025 copy has 623 dated field rows ending August 3, so it is not assumed to be a final full-season copy.

### Bacteria laboratory testing

IDEXX stores sample identifiers, dates, positive well counts, MPN results, and source conditions. Decimal and censored results must survive. The older `bacteria.e_coli_mpn_100ml INT` model cannot fully express these source values.

### Analyzer results

GALLERY has test/control identifiers, result values and units, analysis timestamps, dilution fields, errors, and instrument metadata. Do not infer collection date or monitoring site from an analyzer identifier. Controls and repeat tests need explicit classification before promotion.

### Turbidity

TURBIDITY holds replicate readings and a calculated Final Reading. The inspected source uses MIN, not an average. Preserve both original readings and the supplied calculation; approval of the aggregation rule is separate.

### Bloom follow-up

PHYCOCYANIN contains dates, replicate/median readings, observations, DEP status, and formulas. The 2026 layout adds Aquafluor fields and shifts some columns. Source error indicators and missing cached formulas require review. No new bloom safety thresholds are inferred.

### Reference and change history

METADATA, Site_GPS-Coordinates, and IDEXX MPN Table remain inside the preserved original file. They are listed as supporting sheets. The first parser does not turn them into independently editable database entities.

## Additive database changes

`db/12_source_intake.sql` adds three tables:

- `source_import`: exact workbook bytes, hash, sanitized filename, parser version, summary, timestamp. Unique file hash makes repeated identical uploads idempotent.
- `source_observation`: one extracted row per batch/sheet/source-row, retaining raw cell evidence and interpreted parameter states as JSON.
- `source_review`: append-only decision revisions, reviewer label, reason, timestamp. Row locking and expected revisions prevent stale screens overwriting newer decisions.

Save operations are transactional: a failed observation insert rolls back the whole batch. Original data is not overwritten. No source ledger table cascades deletion into monitoring records. The schema does not alter nitrate units, bacteria types, existing QA, scoring, or older imports.

A reviewer name is entered by the operator and is **not verified identity**. The existing application does not supply staff authentication. Public-demo mode blocks all new source routes; read-only mode permits private inspection/browsing but blocks saving and review decisions. These modes do not substitute for authenticated access on a staff deployment.

## Deployment and operation

The schema script is included at the end of `db/run_schema.sql` for fresh installations. For an existing database, apply only `db/12_source_intake.sql` using the established migration/backup procedure. No existing operational or remote database has been migrated as part of this change.

Set a stable `SECRET_KEY` for any multiworker deployment. Preview ownership and form tokens use signed browser sessions. Source previews are private temporary files with a 30-minute lifetime and at most three active previews per browser; cleanup runs on subsequent uploads. A preview directory needs to be shared by workers on the same host. Multiple independent hosting instances need shared preview storage or another upload architecture.

Inspect accepts `.xlsx` files up to 16 MB, caps expanded archive size, rejects macro projects, validates expected source headings, and limits worksheet dimensions. It does not refresh formulas or external links. The parser includes rows with literal values even if incomplete; formula-only tails do not become observations. Preserved original files may contain personal information and require staff-only backup/access handling.

If the source tables are unavailable, inspection is still usable, but saving needs setup. Saved batch history reads up to 50 batches, and each record page displays up to 50 rows. There is no delete/publish/monitoring-import action in this first slice.

## Decisions required before monitoring promotion

1. Confirm primary source ownership: Survey123 consolidations versus original IDEXX/Gallery values, handling disagreements and formula substitutions.
2. Approve visit/sample identity, repeat samples, unknown sites, and sample-code inconsistencies. Preserve lowercase site suffixes.
3. Define analyzer environmental samples versus controls, repeat tests, and collection/analysis timestamps.
4. Confirm chemical reporting basis and units, especially nitrate as N versus nitrate ion. No implicit conversion.
5. Confirm which chloride values already carry the tenfold correction. Never apply it twice.
6. Approve limited-value storage and analysis policies. Do not translate source `>2419.6` into 2500 without a versioned analytical rule.
7. Separate row-level flags, individual-value uncertainty, method exclusions, and review decisions.
8. Establish authenticated reviewer identity and access roles before multiuser operational use.

The source ledger allows those questions to be reviewed without losing evidence. It does not resolve them by choosing the first match or overwriting historical measurements.

## Subsequent implementation stages

### Monitoring records and reconciliation

Add a parameter-level result model with decimal value, original representation, qualifier, unit and chemical basis, collection/analysis method, source observation link, and review/eligibility reasons. Model visits and samples separately where repeat sampling requires it. Build a proposed-action view showing exact matches, conflicts, unknowns, and intended new records. Only explicit reviewed selections should be promoted transactionally, with repeat-upload protection and a source-to-destination ledger.

### Site workspace

Reconcile current site metadata with the older site inventory. Add staff-friendly access/ownership, aliases/relocations, geographic associations, and calculated team activity. Confirm source authority and units before changing existing site values.

### Biological and habitat intake

Preserve Orig/Rep, taxon-level counts, original versus standardized samples, laboratory metrics, multi-year habitat records, and matching evidence. Resolve formula defects and index applicability with Watershed before recalculating scores.

### Equipment and volunteer operations

Use Jian's current procedures rather than freezing older drafts. Separate sensor histories, loans, sessions, tests, calibrations, training events, attendance, assignments, and person records. Resolve age/status conventions and historical missing-field exceptions. Keep contact and operational notes private.

### Assessment and WQX

Version assessment rules separately from raw data. Resolve exact-boundary gaps, minimum sampling windows, index priorities, and regional aggregation. Compare traced examples with the supplied R script and report cards. Use the 2024 submission as an example, then verify current export requirements before claiming WQX compliance.

### Staff pilot

Walk Jian through actual seasonal tasks. Confirm what is easier, what remains confusing, and which step can safely replace the spreadsheet process. Validate backups/restoration and maintenance instructions before operational rollout.

## Validation

Synthetic tests cover decimal/censored/uncertain values, zero retention, source formulas and formatting, repeated site/date rows, formula-only tails, malformed files, preview ownership, escaped output, form tokens, public/read-only boundaries, transactional rollback, repeated identical uploads, stale reviews, history, and cross-batch review protection.

The parser was also exercised read-only against the supplied 2025 and 2026 seasonal source files. This establishes layout compatibility, not scientific validation or complete reconciliation with the historical database. PostgreSQL tests use a separate temporary instance and the dedicated `streamwatch_source_test` database only.
