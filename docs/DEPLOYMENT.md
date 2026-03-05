# Hosting the StreamWatch Web App (Free, Public)

This guide gets the StreamWatch app **publicly hosted for free** so you can meet the strategic goals: **public visualization**, **WQX export**, **site maps and time series**, **QA summary**, and **shareable dashboards**.

## What you get

- **Public URL** – Anyone can open the app (e.g. `https://streamwatch.onrender.com`).
- **Neon database** – Your existing Neon DB; no extra database host. Set `DATABASE_URL` in the host’s dashboard.
- **Strategic goals covered** – Map, Sites, Site detail, Explore (time series), QA summary, WQX export all work against Neon.

## Option 1: Render (recommended, free tier)

Render gives you a free Web Service (750 hours/month). The app uses your **Neon** database; Render’s free Postgres is not used.

### 1. Push your code

Ensure the project is in a **Git** repo (e.g. GitHub or GitLab). Render deploys from the repo.

```bash
git init
git add .
git commit -m "StreamWatch app and ETL"
git remote add origin https://github.com/YOUR_ORG/watershed-institute.git
git push -u origin main
```

### 2. Create a Web Service on Render

1. Go to [dashboard.render.com](https://dashboard.render.com) and sign up / log in.
2. **New** → **Web Service**.
3. Connect your repo (`watershed-institute` or the repo you use).
4. Use these settings:

| Field | Value |
|-------|--------|
| **Name** | `streamwatch` (or any name) |
| **Region** | Choose closest to your users |
| **Branch** | `main` (or your default branch) |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `sh -c 'gunicorn -w 1 -b 0.0.0.0:${PORT:-10000} dashboard.app:app'` |
| **Instance Type** | Free |

5. **Environment** – Add one variable:
   - **Key:** `DATABASE_URL`
   - **Value:** Your Neon connection string (from [Neon Console](https://console.neon.tech) → Connection string). It should include `?sslmode=require` (Neon usually adds this).

6. Click **Create Web Service**. Render will build and deploy.

**If you see "No open HTTP ports detected"** in the logs: (1) Use the start command above (with `sh -c` and `${PORT:-10000}`) so the port is always set. (2) Scroll up in the same log and look for a **Python traceback** (e.g. `ModuleNotFoundError`, `ImportError`, or database connection errors)—the app may be crashing before it binds; fix that error and redeploy.

**If Map / Sites / Explore show "Could not load sites" or "Failed to load sites"** (and QA shows "Failed to load" or zeros with an error): the app is running but **cannot reach the database**. Do this:

1. In Render → your service → **Environment**, confirm **`DATABASE_URL`** is set to your **Neon** connection string (from [Neon Console](https://console.neon.tech) → Connection details). It must include **`?sslmode=require`** (Neon usually adds this).
2. Open **`https://your-app.onrender.com/health`** in a browser. You should see `{"status":"ok","database":"connected"}`. If you see `{"status":"degraded","database":"disconnected"}`, the app cannot connect to Neon—double-check the URL, re-paste it in Environment, and **Redeploy** (Environment changes require a redeploy).

### 3. Get your public URL

After the first deploy, Render shows a URL like:

`https://streamwatch-xxxx.onrender.com`

Use this as your **public app URL**. Share it for Map, Sites, Explore, Export, and QA.

### 4. Verify (strategic goals)

- **Map** – Open `/map`; markers load from Neon.
- **Sites** – `/sites`; list and search work.
- **Site detail** – Click a site; recent results and “Explore” / “Download data” work.
- **Explore** – `/explore`; pick site/parameter/dates; chart loads.
- **QA** – `/qa`; summary counts show.
- **Export** – `/export`; choose dates (and optional site); WQX CSV downloads.

### Free tier behavior (why the first load is slow)

- **Cold start** – On the **free tier**, Render puts your service to sleep after about **15 minutes of no traffic**. The next time someone opens your URL, Render has to start the server again. That **first request can take 30–90 seconds** (sometimes longer) before the page appears. Once it’s awake, the site responds quickly until it’s idle again for 15+ minutes.
- **Right after “Successfully deployed”** – The first time you open the live URL (or after a deploy), you’re often hitting a cold start too, so a long wait there is normal.
- **What you can do:**
  - **Expect it** – For a free app, this is normal. Tell users: “First load may take up to a minute; please wait.”
  - **Keep it awake (optional)** – A free uptime checker (e.g. [UptimeRobot](https://uptimerobot.com)) can ping your URL every 10–14 minutes so the service stays awake when you care about fast response. Stay within Render’s [fair use](https://render.com/docs/free#limitations); a single ping every 10–14 minutes is typically fine.
  - **Faster always-on** – Render’s paid plans keep the service running (no spin-down), so the first load is always fast.
- **Hours** – 750 free instance hours per month; usually enough for a single service.
- **HTTPS** – Render provides HTTPS and a default `*.onrender.com` hostname.

### Custom domain (optional)

In the Render service → **Settings** → **Custom Domains**, add your domain and follow the DNS instructions. TLS is managed by Render.

---

## Option 2: Fly.io (free tier)

You can also run the app on Fly.io with a small free allowance.

1. Install [flyctl](https://fly.io/docs/hands-on/install-flyctl/).
2. From the **project root**:

   ```bash
   fly launch --no-deploy
   ```

   When prompted, don’t add a Postgres app; we use Neon.

3. Set the Neon connection string:

   ```bash
   fly secrets set DATABASE_URL="postgresql://...?sslmode=require"
   ```

4. In `fly.toml`, set the HTTP service to internal port **8080** and ensure the start command uses that port, e.g.:

   ```bash
   gunicorn -w 1 -b 0.0.0.0:8080 dashboard.app:app
   ```

   (Fly often sets `PORT=8080`; if your platform uses `$PORT`, use that.)

5. Deploy:

   ```bash
   fly deploy
   ```

Your app will be at `https://YOUR_APP_NAME.fly.dev`.

---

## Environment variables (all hosts)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Neon (or any Postgres) connection string; must include `?sslmode=require` for Neon. |

Optional:

- `PORT` – Set by Render/Fly; only needed when running locally with a different port.
- `FLASK_DEBUG` – Leave unset or `false` in production.

---

## Neon connection notes

- Use the **connection string** from Neon (not the pooler) unless you scale to multiple workers.
- If you see connection timeouts, try Neon’s **connection pooler** (session or transaction mode) and use the pooler URL as `DATABASE_URL`.
- Do **not** commit `.env` or put `DATABASE_URL` in the repo; set it only in the host’s dashboard or secrets.

---

## Summary

| Goal | How it’s met |
|------|----------------|
| Public hosting | Deploy to Render (or Fly.io) free tier; single public URL. |
| Public visualization | Map, Sites, Site detail, Explore (time series) served from the same app. |
| WQX export | Export page and `/export/wqx`; date range and optional site. |
| QA dashboard | QA page shows flagged chemistry, exceedance, and meter-fail counts. |
| Centralized data | App reads from Neon; one DB for all features. |

After deployment, you can point partners and the public to the app URL for viewing data and downloading WQX exports.
