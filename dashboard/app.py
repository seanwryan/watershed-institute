"""
StreamWatch dashboard API and multi-page web app.
JSON endpoints for sites, time series, QA; HTML routes for Map, Sites, Site detail, Explore, QA, Export.
"""
import os
import sys
from pathlib import Path
from datetime import date

import psycopg2
from flask import Flask, jsonify, request, send_from_directory, render_template, Response

# Allow importing etl when running from dashboard/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/streamwatch")

app = Flask(__name__, static_folder="static", template_folder="templates")


def get_db():
    return psycopg2.connect(DATABASE_URL)


@app.route("/api/sites")
def api_sites():
    """List active sites with last sample date and visit count (for maps and site pages)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.site_id, s.site_code, w.name AS waterbody_name, s.latitude, s.longitude, s.description,
                   (SELECT MAX(v.sample_date)::text FROM visit v WHERE v.site_id = s.site_id),
                   (SELECT COUNT(*) FROM visit v WHERE v.site_id = s.site_id)
            FROM site s
            LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
            WHERE s.is_active = true
            ORDER BY s.site_code
            """)
        rows = cur.fetchall()
        return jsonify([
            {
                "site_id": r[0], "site_code": r[1], "waterbody_name": r[2],
                "latitude": float(r[3]) if r[3] else None, "longitude": float(r[4]) if r[4] else None,
                "description": r[5], "last_sample_date": r[6], "visit_count": r[7],
            }
            for r in rows
        ])
    finally:
        conn.close()


@app.route("/api/time_series")
def api_time_series():
    """Time series: parameter values by site and date range. Query params: site_code, parameter, date_start, date_end."""
    site_code = request.args.get("site_code")
    parameter = request.args.get("parameter", "water_temp_c")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    conn = get_db()
    try:
        cur = conn.cursor()
        allowed = {"water_temp_c", "nitrate_ug_l", "phosphate_mg_l", "ph", "turbidity_ntu", "dissolved_oxygen_ppm", "chloride_mg_l", "e_coli_mpn_100ml"}
        if parameter not in allowed:
            parameter = "water_temp_c"
        if "e_coli" in parameter:
            cur.execute("""
                SELECT v.sample_date::text, b.e_coli_mpn_100ml
                FROM visit v
                JOIN site s ON s.site_id = v.site_id
                JOIN bacteria b ON b.visit_id = v.visit_id
                WHERE (%s IS NULL OR s.site_code = %s) AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                ORDER BY v.sample_date
                """, (site_code, site_code, date_start, date_start, date_end, date_end))
        else:
            cur.execute(f"""
                SELECT v.sample_date::text, c.{parameter}
                FROM chemical c
                JOIN visit v ON v.visit_id = c.visit_id
                JOIN site s ON s.site_id = v.site_id
                WHERE (%s IS NULL OR s.site_code = %s) AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                ORDER BY v.sample_date
                """, (site_code, site_code, date_start, date_start, date_end, date_end))
        rows = cur.fetchall()
        return jsonify([{"date": r[0], "value": float(r[1]) if r[1] is not None else None} for r in rows])
    finally:
        conn.close()


@app.route("/api/qa_summary")
def api_qa_summary():
    """QA summary: flagged chemical count, exceedance count, meter-fail count (for internal QA dashboard)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM chemical c JOIN data_condition dc ON dc.data_condition_id = c.data_condition_id WHERE dc.code = 'Flagged'")
        flagged = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM result_flag WHERE flag_type_id IN (SELECT flag_type_id FROM flag_type WHERE code = 'Exceedance')")
        exceedance = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM result_flag WHERE flag_type_id IN (SELECT flag_type_id FROM flag_type WHERE code = 'Meter_Failed_Test')")
        meter_fail = cur.fetchone()[0]
        return jsonify({"flagged_chemical_count": flagged, "exceedance_flag_count": exceedance, "meter_failed_flag_count": meter_fail})
    finally:
        conn.close()


@app.route("/api/parameters")
def api_parameters():
    """List available parameters for time series dropdown."""
    return jsonify([
        {"id": "water_temp_c", "label": "Water temperature (°C)"},
        {"id": "nitrate_ug_l", "label": "Nitrate (µg/L)"},
        {"id": "phosphate_mg_l", "label": "Phosphate (mg/L)"},
        {"id": "ph", "label": "pH"},
        {"id": "turbidity_ntu", "label": "Turbidity (NTU)"},
        {"id": "dissolved_oxygen_ppm", "label": "Dissolved oxygen (mg/L)"},
        {"id": "chloride_mg_l", "label": "Chloride (mg/L)"},
        {"id": "e_coli_mpn_100ml", "label": "E. coli (MPN/100mL)"},
    ])


@app.route("/api/site/<site_code>")
def api_site(site_code):
    """Full site info + last sample date + visit count + recent chemical/bacteria summary (last 5 visits)."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.site_id, s.site_code, w.name AS waterbody_name, s.description, s.latitude, s.longitude,
                   (SELECT MAX(v.sample_date)::text FROM visit v WHERE v.site_id = s.site_id),
                   (SELECT COUNT(*) FROM visit v WHERE v.site_id = s.site_id)
            FROM site s
            LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
            WHERE s.site_code = %s AND s.is_active = true
            """, (site_code,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Site not found"}), 404
        site = {
            "site_id": row[0], "site_code": row[1], "waterbody_name": row[2], "description": row[3],
            "latitude": float(row[4]) if row[4] else None, "longitude": float(row[5]) if row[5] else None,
            "last_sample_date": row[6], "visit_count": row[7],
        }
        cur.execute("""
            SELECT v.sample_date::text, c.water_temp_c, c.nitrate_ug_l, c.phosphate_mg_l, c.ph, c.turbidity_ntu, c.dissolved_oxygen_ppm, c.chloride_mg_l, b.e_coli_mpn_100ml
            FROM visit v
            LEFT JOIN chemical c ON c.visit_id = v.visit_id
            LEFT JOIN bacteria b ON b.visit_id = v.visit_id
            WHERE v.site_id = %s
            ORDER BY v.sample_date DESC
            LIMIT 5
            """, (site["site_id"],))
        recent = []
        for r in cur.fetchall():
            recent.append({
                "sample_date": r[0],
                "water_temp_c": float(r[1]) if r[1] is not None else None,
                "nitrate_ug_l": float(r[2]) if r[2] is not None else None,
                "phosphate_mg_l": float(r[3]) if r[3] is not None else None,
                "ph": float(r[4]) if r[4] is not None else None,
                "turbidity_ntu": float(r[5]) if r[5] is not None else None,
                "dissolved_oxygen_ppm": float(r[6]) if r[6] is not None else None,
                "chloride_mg_l": float(r[7]) if r[7] is not None else None,
                "e_coli_mpn_100ml": r[8],
            })
        site["recent_results"] = recent
        return jsonify(site)
    finally:
        conn.close()


@app.route("/export/wqx")
def export_wqx():
    """Download WQX CSV. Query params: date_start, date_end, site_code (optional, single or comma-separated)."""
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    site_codes = request.args.get("site_code")
    date_start = date.fromisoformat(date_start) if date_start else None
    date_end = date.fromisoformat(date_end) if date_end else None
    site_codes = [s.strip() for s in site_codes.split(",")] if site_codes else None
    try:
        from etl.export_wqx import build_wqx_csv
        buf = build_wqx_csv(date_start=date_start, date_end=date_end, site_codes=site_codes)
        csv_content = buf.getvalue()
    except Exception as e:
        return Response(str(e), status=500, mimetype="text/plain")
    return Response(csv_content, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=streamwatch_wqx_export.csv"})


# --- HTML page routes (multi-page web app) ---

@app.route("/")
def index():
    return render_template("home.html")


@app.route("/map")
def map_page():
    return render_template("map.html")


@app.route("/sites")
def sites_page():
    return render_template("sites.html")


@app.route("/site/<site_code>")
def site_detail_page(site_code):
    return render_template("site_detail.html", site_code=site_code)


@app.route("/explore")
def explore_page():
    return render_template("explore.html")


@app.route("/qa")
def qa_page():
    return render_template("qa.html")


@app.route("/export")
def export_page():
    return render_template("export.html")


@app.route("/static/<path:path>")
def static_file(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
