# StreamWatch PostgreSQL Schema

Schema and seed data for the centralized StreamWatch database (lowercase, underscores, explicit PKs/FKs).

## Apply schema

```bash
cd db
psql "$DATABASE_URL" -f run_schema.sql
```

Or run files individually in numeric order if you need to skip or re-run parts.

## Table overview

- **Lookups**: `waterbody`, `subwatershed`, `municipality`, `tbl_huc13`, `tbl_huc14`, `data_condition`, `flag_type`, `lst_*`
- **Core**: `site`, `volunteer`, `visit`, `equipment`, `sensor`, `session`, etc.
- **Results**: `chemical`, `bacteria`, `habitat_assessment`, `macro_analysis`, `bug_count`, `rbp100_bug`, `bug_list`
- **Junctions**: `junc_assignments`, `junc_attendance`, `junc_site_subwatershed`, `junc_site_municipality`

Site/volunteer status and last sample dates are intended to be computed via views (not stored).
