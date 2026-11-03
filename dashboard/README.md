# StreamWatch Web App

Multi-page web app and JSON API for viewing sites, exploring time series, QA summary, and exporting WQX data.

## Run locally

From the project root:

```bash
export DATABASE_URL=postgresql://localhost/streamwatch
python dashboard/app.py
```

If port 5000 is in use (e.g. by AirPlay Receiver), use another port:

```bash
export PORT=5001
python dashboard/app.py
```

Then open http://localhost:5000 (or http://localhost:5001 when using `PORT=5001`).

**Pages:** Home, **Map** (Leaflet), **Sites** (list + search), **Site detail** (`/site/<code>`), **Explore data** (time series with date range), **QA**, **Export** (download WQX CSV).

## Deploy (free tier)

See **[docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md)** for step-by-step Render + Neon (and optional Fly.io) deployment, including start command, `DATABASE_URL` (no quotes), and troubleshooting. For full app usage (local and live), see **[docs/APP_TUTORIAL.md](../docs/APP_TUTORIAL.md)**.

Summary: Render — connect repo, set Build/Start commands, add `DATABASE_URL` (Neon connection string, no quotes), redeploy. Use `sh -c 'gunicorn -w 1 -b 0.0.0.0:${PORT:-10000} dashboard.app:app'` as Start Command.

## API (for Power BI, Excel, R)

- `GET /api/sites` – active sites with last sample date and visit count
- `GET /api/site/<site_code>` – site detail + recent results (last 5 visits)
- `GET /api/time_series?site_code=AC1&parameter=water_temp_c&date_start=2020-01-01&date_end=2025-12-31` – time series
- `GET /api/qa_summary` – flagged count, exceedance count, meter-fail count
- `GET /api/parameters` – list of parameter ids for time_series
- `GET /export/wqx?date_start=...&date_end=...&site_code=...` – download WQX CSV

Connect Power BI / Excel to these JSON endpoints or to the database using the reporting views in `db/10_reporting_views.sql`.

## Focused UI checks

Use a Python 3.12 virtual environment with the project requirements installed.
If an older environment stalls at startup, create a separate ignored environment
instead of reusing it:

```bash
python3.12 -m venv env/verification
env/verification/bin/python -m pip install -r requirements.txt
env/verification/bin/python -m unittest dashboard.test_staff_usability
node --test dashboard/test_table_usability.js
```

These checks use synthetic fixtures and require no running database. They cover
report-search wording, CSV filter links, equipment badges, table sorting/search,
and normal/private/public access modes. The access-mode integration checks below
also compare real table counts before and after; they do not require a fixed
historical dataset:

```bash
DATABASE_URL=postgresql://localhost/streamwatch_demo \
PGOPTIONS='-c default_transaction_read_only=on' \
env/verification/bin/python -m dashboard.test_access_modes
```

Run database integration checks only against a local or verification database.

## Seasonal file previews

- `/imports/bact` reviews the 2025/2026 Survey123 and IDEXX layouts. Source
  Data Conditions and Notes remain visible as supplied, including compound tags;
  they do not change reconciliation classifications. The preview CSV includes them.
- `/imports/bat` reviews the seasonal lab CSV and/or the `Form Responses 1` habitat
  workbook. Blank rows are counted separately; populated rows, exact repeats,
  original/replicate distinctions, lab indices, and habitat fields are retained.
  The preview shows exact site/date overlaps and exact `bug_list.genus_species`
  name occurrences. It never selects a visit or taxon, guesses aliases, merges
  volunteer records, chooses a replicate destination, or calculates scores.

These tools do not import data. BAT uploads use a read-only database session;
temporary source files are removed after processing and preview results expire
after two hours. Both preview workflows remain available in read-only/demo modes.
No changes to the historical rebuild scripts or schema are needed.

Synthetic preview tests require no private source files or running PostgreSQL:

```bash
env/verification/bin/python -m unittest etl.test_bat_reconcile dashboard.test_seasonal_previews
```

### QA investigation

`/qa` links to `/qa/review`, a read-only chemistry/bacteria workspace. Filter by
site, dates, parameter, result flag, or Data Condition. Each package remains
separate; flags and conditions describe the whole record, not an inferred
parameter-specific issue. Results without measurements remain visible when no
parameter filter is set. All stored result/visit notes are shown, not reconstructed
source text. Missing conditions do not mean acceptance.

The table paginates 100 value rows. Its search/sort affects only the displayed
page; `/qa/review.csv` exports all matching rows using the same server filters.
CSV free text is protected against spreadsheet-formula interpretation. Nitrate is
shown as stored with unresolved units; no conversion or threshold is applied.

Both workspace and CSV are blocked in public-demo mode because notes may contain
internal information. Private read-only mode permits both. All queries run in a
read-only transaction; there are no review/save/resolve actions or new QA rules.
