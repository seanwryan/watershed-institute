# StreamWatch Web App — How to Use

This guide covers using the StreamWatch web app **locally** or on the **live site** (e.g. https://watershed-institute.onrender.com).

---

## 1. Opening the app

### Live site (Render)

- Open **https://watershed-institute.onrender.com** in your browser.
- **First load or after idle:** The server may take **up to a minute** to wake up (free-tier spin-down). If the page hangs, wait and refresh once. Later loads are fast.
- The **Home** page is the starting point.

### Local

From the project root:

```bash
source .env   # or: export DATABASE_URL=postgresql://...
python dashboard/app.py
```

Then open **http://localhost:5000** (or the port shown; use `PORT=5001` if 5000 is in use).

---

## 2. Navigation

At the top of every page:

| Link | What it does |
|------|----------------|
| **StreamWatch** | Back to Home |
| **Home** | Intro and links to all sections |
| **Map** | Map of monitoring sites |
| **Sites** | List and search all sites |
| **Explore data** | Time series charts by site and parameter |
| **QA** | Data quality summary (flagged, exceedances, meter-fail) |
| **Export** | Download WQX CSV for reporting |

The current section is highlighted.

---

## 3. Home

Short description of the app and links to Map, Sites, Explore data, QA, and Export. Use it as the jumping-off point.

---

## 4. Map

**Purpose:** See where monitoring sites are located.

**How to use:**

1. Click **Map** in the nav.
2. The map loads with **markers only for sites that have valid coordinates**. Sites without coordinates in the database do not appear.
3. Click a marker to open a popup with site code, waterbody, last sample date, and visit count.
4. Click the link in the popup to open that site’s **Site detail** page.
5. Pan and zoom as on any web map.

**If you see “Could not load sites”:** The app can’t reach the database. On the live site, check [DEPLOYMENT.md](DEPLOYMENT.md) (e.g. `DATABASE_URL` on Render) or open `/health` to verify connectivity.

---

## 5. Sites

**Purpose:** Browse and search all monitoring sites.

**How to use:**

1. Click **Sites** in the nav.
2. The table shows **Site** (code), **Waterbody**, **Last sample**, **Visits**, and a **View** link.
3. Use the **Search** box to filter by site code or waterbody name (e.g. `AC1` or part of a stream name).
4. Click **View** on a row to open that site’s **Site detail** page.

---

## 6. Site detail

**Purpose:** View one site’s metadata and latest results.

**How to get there:** From the Map (marker popup link) or from the Sites list (View).

**What you see:**

- Site code and waterbody  
- Description (if present)  
- Last sample date and total visit count  
- **View on map** link (if the site has coordinates)  
- **Recent results** table: last 5 sampling dates with water temp, nitrate, phosphate, pH, turbidity, dissolved oxygen, chloride, E. coli  

**Links at the bottom:**

- **Explore time series for this site** — Opens Explore data with this site pre-selected.  
- **Download data for this site (WQX)** — Opens the Export page with this site pre-selected so you can download a WQX CSV for this site only.

---

## 7. Explore data

**Purpose:** View a time series chart for a parameter (e.g. water temperature, nitrate) at one site or all sites.

**How to use:**

1. Click **Explore data** in the nav.
2. **Site** — Choose one site or “All sites”.
3. **Parameter** — Choose what to plot (e.g. Water temperature (°C), Nitrate, pH, E. coli).
4. **From** / **To** — Set a date range. Defaults to the last 12 months if blank; you can change it.
5. Click **Load**. The chart updates with dates on the horizontal axis and values on the vertical axis.

**Tips:**

- If you came from a Site detail page via “Explore time series for this site”, the site is already selected; pick a parameter and click **Load**.
- If you see “Could not load data” or “Could not load sites”, the database may be disconnected; check `/health` or your deployment config.

---

## 8. QA

**Purpose:** Quick view of data quality and flags.

**How to use:**

1. Click **QA** in the nav.
2. You’ll see three counts:
   - **Flagged chemistry** — Chemistry rows marked for review  
   - **Exceedance flags** — Results that exceed set thresholds (e.g. temperature, nitrate)  
   - **Meter-fail flags** — Results tied to a meter that failed a test  

Use these to decide what to review before reporting or export. If the page shows “Failed to load”, the app can’t reach the database; see [DEPLOYMENT.md](DEPLOYMENT.md) and `/health`.

---

## 9. Export

**Purpose:** Download monitoring data as a WQX-style CSV for reporting or EPA Water Quality Exchange.

**How to use:**

1. Click **Export** in the nav.
2. **From date** / **To date** — Optionally set a range. Leave blank to include all data.
3. **Site** — Leave as “All sites” or pick one site (e.g. after using “Download data for this site” from a Site detail page).
4. Click **Download WQX CSV**. The browser downloads a file such as `streamwatch_wqx_export.csv` with columns suitable for WQX (Monitoring Location ID, Activity ID, Date, Characteristic, Result, Unit, etc.).

**Tips:**

- Leaving both dates blank exports all data in the database.  
- To export a single site, choose it in the **Site** dropdown or use the link from that site’s detail page.

---

## 10. Quick reference

| Goal | Where | Action |
|------|--------|--------|
| See where sites are | Map | Open Map; click markers for site links. |
| Find a site | Sites | Use Search, then View. |
| One site’s latest data | Site detail | From Map or Sites (View). |
| Plot a trend | Explore data | Pick site, parameter, dates; click Load. |
| Check data quality | QA | Open QA; review the three counts. |
| Get CSV for reporting | Export | Set dates/site if needed; click Download. |
| Check if DB is connected | `/health` | Open in browser; expect `"database":"connected"`. |

---

## Troubleshooting

| Issue | What to try |
|--------|--------------|
| **Page hangs or “takes forever” on first load (live site)** | Free tier spins down after ~15 min idle. Wait up to a minute and refresh. |
| **“Could not load sites” / “Failed to load sites”** | Database not reachable. On Render, set `DATABASE_URL` in Environment (no quotes), redeploy, and check `/health`. |
| **Map has no markers** | Only sites with valid latitude/longitude in the database are shown. |
| **Chart is empty** | That site or date range may have no data; try “All sites” or different dates. |
| **Export file is empty or small** | Little or no data for the chosen dates/site; try a wider range or “All sites”. |

For running the app and database setup, see the main [README](../README.md) and [dashboard README](../dashboard/README.md). For hosting the app publicly, see [DEPLOYMENT.md](DEPLOYMENT.md).
