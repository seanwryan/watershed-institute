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
