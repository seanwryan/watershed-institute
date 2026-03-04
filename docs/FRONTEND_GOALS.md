# Frontend goals (from raw_breakdown)

Summary of visualization and UI goals extracted from **raw_breakdown.txt** (Goals for Data Organization, Reporting, and Visualization; Database Structure Plan; 2025 BACT; ModelingInstructions).

## Strategic goals

- **Public visualization layer**: Time series graphs, site maps with parameter context, public dashboards and reports, shareable outputs.
- **Filter / search / download**: By date, location, parameter; WQX-compatible export for regulatory submission.
- **Site pages**: Identity, trends, and downloads (per-site export).
- **QA dashboard**: Internal view of flagged data, exceedances, meter-fail counts for defensible reporting.

## Page-level goals vs current implementation

| Goal | Source | Current implementation |
|------|--------|------------------------|
| **Site map** with monitoring locations | Goals doc | **Map** page: Leaflet map, `/api/sites`, markers with link to site detail. |
| **Site map** with parameter values / context | Goals doc, BACT dashboard | Map popups show site code + waterbody; can add last sample date and visit count. |
| **Time series** (multi-period) by site & parameter | Goals doc, ModelingInstructions | **Explore** page: site + parameter + date range, Chart.js line chart via `/api/time_series`. |
| **Site pages** with trends and downloads | Goals doc | **Site detail**: waterbody, description, last sample, visit count, recent results table, link to Explore; add per-site export link. |
| **Public dashboards** / summary reporting | BACT, Goals doc | Home + Map + Sites + Explore + Export; QA is internal summary. |
| **Filter by date, location, parameter** | Goals doc | Explore: site select, parameter select, date range. Export: date range + optional site. |
| **WQX export** for regulatory submission | Goals doc, WQX summary | **Export** page: date range + optional site → download WQX CSV. |
| **QA summary** (flagged, exceedance, meter-fail) | Goals doc, Data Questions | **QA** page: `/api/qa_summary` shows flagged chemistry count, exceedance flags, meter-fail flags. |

## Data source

All frontend API routes use `DATABASE_URL` (Neon when running with `source .env`). No frontend code changes are required to “point at Neon”—the backend is already configured via environment.

## Possible future enhancements (from raw_breakdown)

- **Charts**: Scatter (e.g. temperature vs DO), bar for category comparison (ModelingInstructions).
- **Site photos / media**: Referenced in SITES schema; would require media storage and UI.
- **BACT-style dashboard**: Site-by-parameter scores, HAB status, lat/long (partially covered by site detail + map).
- **Drill-down QA**: Table of recent flagged records or links to flagged visits (beyond summary counts).
