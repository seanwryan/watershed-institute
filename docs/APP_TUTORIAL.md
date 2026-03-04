# StreamWatch Web App – How to Use

This tutorial walks you through the StreamWatch web app: opening it, moving around, and using each section.

---

## 1. Open the app

1. From the project folder, start the app in a terminal:
   ```bash
   export DATABASE_URL=postgresql://localhost/streamwatch
   python dashboard/app.py
   ```
   If you see "Address already in use" on port 5000, use another port:
   ```bash
   export PORT=5001
   python dashboard/app.py
   ```

2. In your browser, go to:
   - **http://localhost:5000** (or **http://localhost:5001** if you set `PORT=5001`).

3. You should see the **Home** page with the StreamWatch title and short description.

---

## 2. Navigation

At the top of every page you’ll see:

- **StreamWatch** (logo) – takes you back to Home  
- **Home** – intro and links to the main sections  
- **Map** – map of monitoring sites  
- **Sites** – list of all sites  
- **Explore data** – time series charts  
- **QA** – data quality summary  
- **Export** – download data as CSV  

Use these links to move between sections. The current section is highlighted.

---

## 3. Home

**What it’s for:** Entry point and short description of the app.

**What to do:** Use the list of links to go to Map, Sites, Explore data, QA, or Export.

---

## 4. Map

**What it’s for:** See where monitoring sites are.

**How to use:**

1. Click **Map** in the top navigation.
2. Wait for the map to load. Sites that have latitude/longitude appear as markers.
3. Click a marker to open a popup with the site code and waterbody name.
4. Click the link in the popup to open that site’s **Site detail** page.

**Tip:** You can pan and zoom the map like any normal web map.

---

## 5. Sites

**What it’s for:** Browse and search all monitoring sites.

**How to use:**

1. Click **Sites** in the top navigation.
2. The table lists: **Site** (code), **Waterbody**, **Last sample** (date), **Visits** (count).
3. Use the **Search** box to filter by site code or waterbody name (e.g. type `AC1` or part of a stream name).
4. Click **View** in a row to open that site’s **Site detail** page.

---

## 6. Site detail

**What it’s for:** See one site’s info and latest results.

**How to get there:** From the Map (marker popup link) or from the Sites list (View).

**What you see:**

- Site code and waterbody  
- Description (if present)  
- Last sample date and total visit count  
- Link to view the site on an external map (if coordinates exist)  
- **Recent results** table: last 5 sampling dates with water temperature, nitrate, phosphate, pH, turbidity, dissolved oxygen, chloride, E. coli  

At the bottom there’s a link: **Explore time series for this site**. It opens **Explore data** with this site already selected.

---

## 7. Explore data

**What it’s for:** View a time series chart for a parameter (e.g. water temperature, nitrate) at one site or all sites.

**How to use:**

1. Click **Explore data** in the top navigation.
2. **Site** – Choose one site or “All sites”.
3. **Parameter** – Choose what to plot (e.g. Water temperature (°C), Nitrate, pH, E. coli).
4. **From** / **To** – Optionally set a date range. Leave blank to use all available dates.
5. Click **Load**.
6. The chart updates with dates on the horizontal axis and values on the vertical axis.

**Tip:** If you came from a Site detail page via “Explore time series for this site”, the site dropdown is already set to that site; pick a parameter and click **Load**.

---

## 8. QA

**What it’s for:** Quick view of data quality and flags.

**How to use:**

1. Click **QA** in the top navigation.
2. You’ll see three counts:
   - **Flagged chemistry** – chemistry rows marked for review  
   - **Exceedance flags** – results that exceed set thresholds (e.g. temperature or nitrate)  
   - **Meter-fail flags** – results tied to a meter that failed a test  

Use these to decide what to review or fix before reporting or export.

---

## 9. Export

**What it’s for:** Download monitoring data as a WQX-style CSV for use in reporting or EPA Water Quality Exchange.

**How to use:**

1. Click **Export** in the top navigation.
2. **From date** – Start of the date range (optional).
3. **To date** – End of the date range (optional).
4. **Site** – Leave as “All sites” or pick one site (optional).
5. Click **Download WQX CSV**.
6. The browser will download a file named like `streamwatch_wqx_export.csv` with columns such as Monitoring Location ID, Activity ID, Date, Characteristic, Result, and Unit.

**Tips:**

- Leaving both dates blank exports all data in the database.  
- To export a single site, choose it in the **Site** dropdown.  
- The CSV is generated when you click the button; no files are stored on the server.

---

## 10. Quick reference

| Goal                     | Where to go      | What to do                                      |
|--------------------------|------------------|-------------------------------------------------|
| See where sites are      | Map              | Open Map, click markers for site links.         |
| Find a specific site     | Sites            | Use Search, then View.                         |
| See one site’s latest    | Site detail      | From Map or Sites (View).                       |
| Plot a trend over time   | Explore data     | Pick site, parameter, dates; click Load.        |
| Check data quality       | QA               | Open QA and review the three counts.            |
| Get a CSV for reporting  | Export           | Set dates/site if needed; click Download.       |

---

## Troubleshooting

- **Blank or “Loading…” that never finishes** – The database may be empty or the connection may have failed. Check that PostgreSQL is running and `DATABASE_URL` is set correctly.
- **Map has no markers** – Sites only show if they have latitude and longitude in the database.
- **Chart is empty** – That site or date range may have no data; try “All sites” or different dates.
- **Export downloads an empty or small file** – There may be little or no data for the chosen dates/site; try a wider range or “All sites”.

For running the app and setting up the database, see the main [README](../README.md) and [dashboard README](../dashboard/README.md).
