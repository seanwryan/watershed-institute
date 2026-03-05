"""
StreamWatch dashboard API and multi-page web app.
JSON endpoints for sites, time series, QA; HTML routes for Map, Sites, Site detail, Explore, QA, Export.
"""
import os
import sys
import math
from pathlib import Path
from datetime import date

import psycopg2
from flask import Flask, jsonify, request, send_from_directory, render_template, Response

# Allow importing etl when running from dashboard/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Strip quotes so pasting 'postgresql://...' in Render Environment still works
_raw = os.getenv("DATABASE_URL", "postgresql://localhost/streamwatch") or ""
DATABASE_URL = _raw.strip().strip("'\"").strip()

app = Flask(__name__, static_folder="static", template_folder="templates")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def get_db_or_503():
    """Return (conn, None) or (None, response_tuple) so API routes can return JSON 503 on DB failure."""
    try:
        return get_db(), None
    except psycopg2.Error:
        return None, (jsonify({"error": "Service temporarily unavailable. Please try again in a moment."}), 503)


@app.route("/health")
def health():
    """Check app and database connectivity. Returns 200 if DB is reachable, 503 otherwise."""
    try:
        conn = get_db()
        conn.close()
        return jsonify({"status": "ok", "database": "connected"})
    except psycopg2.Error:
        return jsonify({"status": "degraded", "database": "disconnected"}), 503


@app.route("/api/sites")
def api_sites():
    """List active sites with last sample date and visit count (for maps and site pages)."""
    conn, err = get_db_or_503()
    if err:
        return err
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

        def _safe_coord(val):
            if val is None:
                return None
            try:
                f = float(val)
            except (TypeError, ValueError):
                return None
            return f if math.isfinite(f) else None

        return jsonify([
            {
                "site_id": r[0],
                "site_code": r[1],
                "waterbody_name": r[2],
                "latitude": _safe_coord(r[3]),
                "longitude": _safe_coord(r[4]),
                "description": r[5],
                "last_sample_date": r[6],
                "visit_count": r[7],
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
    conn, err = get_db_or_503()
    if err:
        return err
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
    conn, err = get_db_or_503()
    if err:
        return err
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


@app.route("/api/data_conditions")
def api_data_conditions():
    """List data_condition codes and descriptions for QA legend."""
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute("SELECT code, description FROM data_condition ORDER BY code")
        rows = cur.fetchall()
        return jsonify([{"code": r[0], "description": r[1] or ""} for r in rows])
    finally:
        conn.close()


@app.route("/api/qa_flags")
def api_qa_flags():
    """List recent flagged records. Params: site_code, flag_type (code), date_start, date_end, limit (default 200)."""
    site_code = request.args.get("site_code")
    flag_type_code = request.args.get("flag_type")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    limit = min(int(request.args.get("limit", 200)), 500)
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        # Chemical flags: rf -> chemical -> visit -> site
        cur.execute("""
            SELECT s.site_code, v.sample_date::text, ft.code AS flag_type_code, ft.description AS flag_type_desc, 'chemical' AS result_table, c.chemical_id AS result_pk
            FROM result_flag rf
            JOIN flag_type ft ON ft.flag_type_id = rf.flag_type_id
            JOIN chemical c ON rf.result_table = 'chemical' AND rf.result_pk = c.chemical_id
            JOIN visit v ON v.visit_id = c.visit_id
            JOIN site s ON s.site_id = v.site_id
            WHERE (%s IS NULL OR s.site_code = %s) AND (%s IS NULL OR ft.code = %s)
            AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
            ORDER BY v.sample_date DESC, s.site_code
            LIMIT %s
        """, (site_code, site_code, flag_type_code, flag_type_code, date_start, date_start, date_end, date_end, limit))
        rows = cur.fetchall()
        # Bacteria flags: rf -> bacteria -> visit -> site
        cur.execute("""
            SELECT s.site_code, v.sample_date::text, ft.code AS flag_type_code, ft.description AS flag_type_desc, 'bacteria' AS result_table, b.bacteria_id AS result_pk
            FROM result_flag rf
            JOIN flag_type ft ON ft.flag_type_id = rf.flag_type_id
            JOIN bacteria b ON rf.result_table = 'bacteria' AND rf.result_pk = b.bacteria_id
            JOIN visit v ON v.visit_id = b.visit_id
            JOIN site s ON s.site_id = v.site_id
            WHERE (%s IS NULL OR s.site_code = %s) AND (%s IS NULL OR ft.code = %s)
            AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
            ORDER BY v.sample_date DESC, s.site_code
            LIMIT %s
        """, (site_code, site_code, flag_type_code, flag_type_code, date_start, date_start, date_end, date_end, limit))
        rows = list(rows) + list(cur.fetchall())
        rows.sort(key=lambda r: (r[1] or "", r[0] or ""), reverse=True)
        flags = [{"site_code": r[0], "sample_date": r[1], "flag_type_code": r[2], "flag_type_description": r[3], "result_table": r[4]} for r in rows[:limit]]
        return jsonify({"flags": flags})
    finally:
        conn.close()


@app.route("/api/flag_types")
def api_flag_types():
    """List flag_type codes for QA filter dropdown."""
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute("SELECT code, description FROM flag_type ORDER BY code")
        rows = cur.fetchall()
        return jsonify([{"code": r[0], "description": r[1] or ""} for r in rows])
    finally:
        conn.close()


# Regulatory thresholds (DataDictionary / 30-yr analysis) for optional chart lines
THRESHOLDS = {
    "water_temp_c": 31,
    "nitrate_ug_l": 10000,  # 10 ppm
    "phosphate_mg_l": None,
    "ph": None,
    "turbidity_ntu": None,
    "dissolved_oxygen_ppm": None,
    "chloride_mg_l": None,
    "e_coli_mpn_100ml": 235,
}


@app.route("/api/thresholds")
def api_thresholds():
    """Return parameter thresholds for chart reference lines (e.g. temp 31°C, nitrate 10 ppm)."""
    return jsonify({k: v for k, v in THRESHOLDS.items() if v is not None})


@app.route("/api/time_series_multi")
def api_time_series_multi():
    """Time series for multiple sites (compare mode). Params: site_codes (comma-separated), parameter, date_start, date_end.
    Returns { "series": [ { "site_code": "AC1", "label": "AC1 – Stream", "data": [ {"date": "...", "value": 12.3} ] }, ... ] }.
    """
    site_codes_raw = request.args.get("site_codes")
    parameter = request.args.get("parameter", "water_temp_c")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    site_codes = [s.strip() for s in site_codes_raw.split(",")] if site_codes_raw else []
    if not site_codes or len(site_codes) > 5:
        return jsonify({"error": "Provide 1–5 comma-separated site codes"}), 400
    conn, err = get_db_or_503()
    if err:
        return err
    allowed = {"water_temp_c", "nitrate_ug_l", "phosphate_mg_l", "ph", "turbidity_ntu", "dissolved_oxygen_ppm", "chloride_mg_l", "e_coli_mpn_100ml"}
    if parameter not in allowed:
        parameter = "water_temp_c"
    try:
        cur = conn.cursor()
        series_list = []
        for site_code in site_codes:
            if "e_coli" in parameter:
                cur.execute("""
                    SELECT v.sample_date::text, b.e_coli_mpn_100ml
                    FROM visit v JOIN site s ON s.site_id = v.site_id
                    JOIN bacteria b ON b.visit_id = v.visit_id
                    WHERE s.site_code = %s AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                    ORDER BY v.sample_date
                """, (site_code, date_start, date_start, date_end, date_end))
            else:
                cur.execute(f"""
                    SELECT v.sample_date::text, c.{parameter}
                    FROM chemical c JOIN visit v ON v.visit_id = c.visit_id
                    JOIN site s ON s.site_id = v.site_id
                    WHERE s.site_code = %s AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                    ORDER BY v.sample_date
                """, (site_code, date_start, date_start, date_end, date_end))
            rows = cur.fetchall()
            cur.execute("SELECT w.name FROM site s LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id WHERE s.site_code = %s", (site_code,))
            wb = (cur.fetchone() or (None,))[0]
            label = site_code + (" – " + wb if wb else "")
            series_list.append({
                "site_code": site_code,
                "label": label,
                "data": [{"date": r[0], "value": float(r[1]) if r[1] is not None else None} for r in rows],
            })
        return jsonify({"series": series_list, "parameter": parameter})
    finally:
        conn.close()


@app.route("/api/scatter")
def api_scatter():
    """Scatter data: two parameters (x and y) for same visits. Params: param_x, param_y, site_code (optional), date_start, date_end.
    Returns { "points": [ {"x": 12.3, "y": 8.1, "date": "...", "site_code": "AC1"} ], "param_x": "...", "param_y": "..." }.
    """
    param_x = request.args.get("param_x", "water_temp_c")
    param_y = request.args.get("param_y", "dissolved_oxygen_ppm")
    site_code = request.args.get("site_code")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    allowed = {"water_temp_c", "nitrate_ug_l", "phosphate_mg_l", "ph", "turbidity_ntu", "dissolved_oxygen_ppm", "chloride_mg_l", "e_coli_mpn_100ml"}
    if param_x not in allowed:
        param_x = "water_temp_c"
    if param_y not in allowed:
        param_y = "dissolved_oxygen_ppm"
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        # Both from chemical except e_coli from bacteria; need join visit+chemical and optionally bacteria
        if "e_coli" in param_x and "e_coli" in param_y:
            cur.execute("""
                SELECT b.e_coli_mpn_100ml, b.e_coli_mpn_100ml, v.sample_date::text, s.site_code
                FROM visit v JOIN site s ON s.site_id = v.site_id
                JOIN bacteria b ON b.visit_id = v.visit_id
                WHERE (%s IS NULL OR s.site_code = %s) AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                AND b.e_coli_mpn_100ml IS NOT NULL
            """, (site_code, site_code, date_start, date_start, date_end, date_end))
            rows = [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]
        elif "e_coli" in param_x:
            cur.execute(f"""
                SELECT b.e_coli_mpn_100ml, c.{param_y}, v.sample_date::text, s.site_code
                FROM visit v JOIN site s ON s.site_id = v.site_id
                JOIN chemical c ON c.visit_id = v.visit_id
                JOIN bacteria b ON b.visit_id = v.visit_id
                WHERE (%s IS NULL OR s.site_code = %s) AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                AND b.e_coli_mpn_100ml IS NOT NULL AND c.{param_y} IS NOT NULL
            """, (site_code, site_code, date_start, date_start, date_end, date_end))
            rows = [(r[0], float(r[1]) if r[1] is not None else None, r[2], r[3]) for r in cur.fetchall()]
        elif "e_coli" in param_y:
            cur.execute(f"""
                SELECT c.{param_x}, b.e_coli_mpn_100ml, v.sample_date::text, s.site_code
                FROM visit v JOIN site s ON s.site_id = v.site_id
                JOIN chemical c ON c.visit_id = v.visit_id
                JOIN bacteria b ON b.visit_id = v.visit_id
                WHERE (%s IS NULL OR s.site_code = %s) AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                AND c.{param_x} IS NOT NULL AND b.e_coli_mpn_100ml IS NOT NULL
            """, (site_code, site_code, date_start, date_start, date_end, date_end))
            rows = [(float(r[0]) if r[0] is not None else None, r[1], r[2], r[3]) for r in cur.fetchall()]
        else:
            cur.execute(f"""
                SELECT c1.{param_x}, c2.{param_y}, v.sample_date::text, s.site_code
                FROM visit v JOIN site s ON s.site_id = v.site_id
                JOIN chemical c1 ON c1.visit_id = v.visit_id
                JOIN chemical c2 ON c2.visit_id = v.visit_id AND c1.chemical_id = c2.chemical_id
                WHERE (%s IS NULL OR s.site_code = %s) AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                AND c1.{param_x} IS NOT NULL AND c2.{param_y} IS NOT NULL
            """, (site_code, site_code, date_start, date_start, date_end, date_end))
            rows = [(float(r[0]) if r[0] is not None else None, float(r[1]) if r[1] is not None else None, r[2], r[3]) for r in cur.fetchall()]
        points = [{"x": r[0], "y": r[1], "date": r[2], "site_code": r[3]} for r in rows]
        return jsonify({"points": points, "param_x": param_x, "param_y": param_y})
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
    conn, err = get_db_or_503()
    if err:
        return err
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
            "site_id": row[0],
            "site_code": row[1],
            "waterbody_name": row[2],
            "description": row[3],
            "latitude": float(row[4]) if (row[4] is not None and math.isfinite(float(row[4]))) else None,
            "longitude": float(row[5]) if (row[5] is not None and math.isfinite(float(row[5]))) else None,
            "last_sample_date": row[6],
            "visit_count": row[7],
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


@app.route("/export/explore_csv")
def export_explore_csv():
    """Download current Explore view as CSV. Params: parameter, date_start, date_end, site_codes (optional, comma-separated).
    If site_codes given: columns date, site_code, value. Else: date, value (all sites aggregated in one series).
    """
    import io
    import csv
    parameter = request.args.get("parameter", "water_temp_c")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    site_codes_raw = request.args.get("site_codes")
    site_codes = [s.strip() for s in site_codes_raw.split(",")] if site_codes_raw else []
    conn, err = get_db_or_503()
    if err:
        return err
    allowed = {"water_temp_c", "nitrate_ug_l", "phosphate_mg_l", "ph", "turbidity_ntu", "dissolved_oxygen_ppm", "chloride_mg_l", "e_coli_mpn_100ml"}
    if parameter not in allowed:
        parameter = "water_temp_c"
    buf = io.StringIO()
    try:
        cur = conn.cursor()
        if site_codes:
            writer = csv.writer(buf)
            writer.writerow(["date", "site_code", "value"])
            for site_code in site_codes:
                if "e_coli" in parameter:
                    cur.execute("""
                        SELECT v.sample_date::text, b.e_coli_mpn_100ml FROM visit v JOIN site s ON s.site_id = v.site_id
                        JOIN bacteria b ON b.visit_id = v.visit_id
                        WHERE s.site_code = %s AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                        ORDER BY v.sample_date
                    """, (site_code, date_start, date_start, date_end, date_end))
                else:
                    cur.execute(f"""
                        SELECT v.sample_date::text, c.{parameter} FROM chemical c JOIN visit v ON v.visit_id = c.visit_id
                        JOIN site s ON s.site_id = v.site_id
                        WHERE s.site_code = %s AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                        ORDER BY v.sample_date
                    """, (site_code, date_start, date_start, date_end, date_end))
                for row in cur.fetchall():
                    writer.writerow([row[0], site_code, row[1] if row[1] is not None else ""])
        else:
            writer = csv.writer(buf)
            writer.writerow(["date", "value"])
            if "e_coli" in parameter:
                cur.execute("""
                    SELECT v.sample_date::text, b.e_coli_mpn_100ml FROM visit v JOIN bacteria b ON b.visit_id = v.visit_id
                    WHERE (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                    ORDER BY v.sample_date
                """, (date_start, date_start, date_end, date_end))
            else:
                cur.execute(f"""
                    SELECT v.sample_date::text, c.{parameter} FROM chemical c JOIN visit v ON v.visit_id = c.visit_id
                    WHERE (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
                    ORDER BY v.sample_date
                """, (date_start, date_start, date_end, date_end))
            for row in cur.fetchall():
                writer.writerow([row[0], row[1] if row[1] is not None else ""])
        buf.seek(0)
        return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=streamwatch_explore.csv"})
    finally:
        conn.close()


CHEM_PARAMS = [
    "air_temp_c", "water_temp_c", "nitrate_ug_l", "nitrate_dilution_adj", "phosphate_mg_l",
    "ph", "turbidity_ntu", "dissolved_oxygen_ppm", "dissolved_oxygen_pct", "conductivity_us_cm", "chloride_mg_l",
]


@app.route("/export/csv")
def export_csv():
    """Generic analytical CSV: site_code, sample_date, parameter, value, data_condition, method.
    Params: date_start, date_end, site_code (optional). One row per result value."""
    import io
    import csv
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    site_code = request.args.get("site_code")
    conn, err = get_db_or_503()
    if err:
        return err
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["site_code", "sample_date", "parameter", "value", "data_condition", "method"])
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.site_code, v.sample_date::text, dc.code,
                   c.air_temp_c, c.water_temp_c, c.nitrate_ug_l, c.nitrate_dilution_adj, c.phosphate_mg_l,
                   c.ph, c.turbidity_ntu, c.dissolved_oxygen_ppm, c.dissolved_oxygen_pct, c.conductivity_us_cm, c.chloride_mg_l,
                   COALESCE(m.name, '')
            FROM chemical c
            JOIN visit v ON v.visit_id = c.visit_id
            JOIN site s ON s.site_id = v.site_id
            LEFT JOIN data_condition dc ON dc.data_condition_id = c.data_condition_id
            LEFT JOIN lst_method m ON m.method_id = c.method_id
            WHERE (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
              AND (%s IS NULL OR s.site_code = %s)
            ORDER BY s.site_code, v.sample_date
        """, (date_start, date_start, date_end, date_end, site_code, site_code))
        for row in cur.fetchall():
            site_code_val, sample_date, dc_code = row[0], row[1], row[2] or ""
            method = row[15] or ""
            for i, param in enumerate(CHEM_PARAMS):
                val = row[3 + i]
                if val is not None:
                    writer.writerow([site_code_val, sample_date, param, val, dc_code, method])
        cur.execute("""
            SELECT s.site_code, v.sample_date::text, dc.code, b.e_coli_mpn_100ml
            FROM bacteria b
            JOIN visit v ON v.visit_id = b.visit_id
            JOIN site s ON s.site_id = v.site_id
            LEFT JOIN data_condition dc ON dc.data_condition_id = b.data_condition_id
            WHERE (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
              AND (%s IS NULL OR s.site_code = %s)
            ORDER BY s.site_code, v.sample_date
        """, (date_start, date_start, date_end, date_end, site_code, site_code))
        for row in cur.fetchall():
            site_code_val, sample_date, dc_code, ecol = row[0], row[1], row[2] or "", row[3]
            if ecol is not None:
                writer.writerow([site_code_val, sample_date, "e_coli_mpn_100ml", ecol, dc_code, ""])
        buf.seek(0)
        return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=streamwatch_data.csv"})
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


@app.route("/api/bio_scores")
def api_bio_scores():
    """Biological index scores per visit (HGMI, NJIS, CPMI from macro_analysis). Params: site_code, date_start, date_end, limit (default 500)."""
    site_code = request.args.get("site_code")
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    limit = min(int(request.args.get("limit", 500)), 1000)
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.site_code, v.sample_date::text, m.njis_score, m.njis_rating, m.hgmi_genus, m.hgmi_family, m.hgmi_rating, m.cpmi_score, m.cpmi_rating, m.index_type
            FROM macro_analysis m
            JOIN visit v ON v.visit_id = m.visit_id
            JOIN site s ON s.site_id = v.site_id
            WHERE (%s IS NULL OR s.site_code = %s) AND (%s::date IS NULL OR v.sample_date >= %s) AND (%s::date IS NULL OR v.sample_date <= %s)
            ORDER BY v.sample_date DESC, s.site_code
            LIMIT %s
        """, (site_code, site_code, date_start, date_start, date_end, date_end, limit))
        rows = cur.fetchall()
        scores = [{"site_code": r[0], "sample_date": r[1], "njis_score": float(r[2]) if r[2] is not None else None, "njis_rating": r[3],
                   "hgmi_genus": float(r[4]) if r[4] is not None else None, "hgmi_family": float(r[5]) if r[5] is not None else None, "hgmi_rating": r[6],
                   "cpmi_score": float(r[7]) if r[7] is not None else None, "cpmi_rating": r[8], "index_type": r[9]} for r in rows]
        return jsonify({"scores": scores})
    finally:
        conn.close()


@app.route("/qa")
def qa_page():
    return render_template("qa.html")


@app.route("/scores")
def scores_page():
    return render_template("scores.html")


@app.route("/export")
def export_page():
    return render_template("export.html")


@app.route("/about")
def about_page():
    return render_template("about.html")


@app.route("/static/<path:path>")
def static_file(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
