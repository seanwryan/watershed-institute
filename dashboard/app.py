"""
StreamWatch dashboard API and multi-page web app.
JSON endpoints for sites, time series, QA; HTML routes for Map, Sites, Site detail, Explore, QA, Export.
"""
import os
import sys
import math
import re
from pathlib import Path
from datetime import date, datetime

import psycopg2
from flask import Flask, jsonify, request, send_from_directory, render_template, Response, redirect, url_for

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


@app.route("/api/home_summary")
def api_home_summary():
    """
    Read-only aggregate counts and recent sampling activity for the Home dashboard.
    No business rules beyond simple COUNT / ORDER BY last sample date.
    """
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM site")
        sites_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM site WHERE is_active = true")
        sites_active = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM visit")
        visits = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM chemical")
        chemistry = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM result_flag")
        qa_flags = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM chemical c "
            "JOIN data_condition dc ON dc.data_condition_id = c.data_condition_id "
            "WHERE dc.code = 'Flagged'"
        )
        flagged_chemistry = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM result_flag WHERE flag_type_id IN "
            "(SELECT flag_type_id FROM flag_type WHERE code = 'Exceedance')"
        )
        exceedance_flags = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM result_flag WHERE flag_type_id IN "
            "(SELECT flag_type_id FROM flag_type WHERE code = 'Meter_Failed_Test')"
        )
        meter_fail_flags = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM volunteer")
        volunteers = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM equipment WHERE equipment_code ~* '^TWI[0-9]{3}$'")
        equipment = cur.fetchone()[0]
        cur.execute(
            """
            SELECT s.site_code,
                   w.name AS waterbody_name,
                   MAX(v.sample_date)::text AS last_sample_date,
                   COUNT(v.visit_id) AS visit_count
            FROM site s
            JOIN visit v ON v.site_id = s.site_id
            LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
            GROUP BY s.site_id, s.site_code, w.name
            HAVING MAX(v.sample_date) IS NOT NULL
            ORDER BY MAX(v.sample_date) DESC, s.site_code
            LIMIT 8
            """
        )
        recent = [
            {
                "site_code": r[0],
                "waterbody_name": r[1],
                "last_sample_date": r[2],
                "visit_count": r[3],
            }
            for r in cur.fetchall()
        ]
        return jsonify(
            {
                "sites_total": sites_total,
                "sites_active": sites_active,
                "sampling_visits": visits,
                "chemistry_results": chemistry,
                "qa_flags": qa_flags,
                "flagged_chemistry_results": flagged_chemistry,
                "exceedance_flags": exceedance_flags,
                "meter_related_flags": meter_fail_flags,
                "volunteers": volunteers,
                "equipment": equipment,
                "recent_sites": recent,
            }
        )
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
    """List available parameters for time series dropdown (human labels + units)."""
    return jsonify([
        {"id": "water_temp_c", "label": "Water temperature", "unit": "°C"},
        {"id": "nitrate_ug_l", "label": "Nitrate", "unit": "µg/L"},
        {"id": "phosphate_mg_l", "label": "Phosphate", "unit": "mg/L"},
        {"id": "ph", "label": "pH", "unit": ""},
        {"id": "turbidity_ntu", "label": "Turbidity", "unit": "NTU"},
        {"id": "dissolved_oxygen_ppm", "label": "Dissolved oxygen", "unit": "mg/L"},
        {"id": "chloride_mg_l", "label": "Chloride", "unit": "mg/L"},
        {"id": "e_coli_mpn_100ml", "label": "E. coli", "unit": "MPN/100mL"},
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
                   s.is_active, s.site_type::text,
                   (SELECT MAX(v.sample_date)::text FROM visit v WHERE v.site_id = s.site_id),
                   (SELECT COUNT(*) FROM visit v WHERE v.site_id = s.site_id)
            FROM site s
            LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
            WHERE s.site_code = %s
            """, (site_code,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Site not found"}), 404

        def _safe_float(val):
            if val is None:
                return None
            try:
                f = float(val)
            except (TypeError, ValueError):
                return None
            return f if math.isfinite(f) else None

        site = {
            "site_id": row[0],
            "site_code": row[1],
            "waterbody_name": row[2],
            "description": row[3],
            "latitude": _safe_float(row[4]),
            "longitude": _safe_float(row[5]),
            "is_active": bool(row[6]),
            "site_type": row[7],
            "last_sample_date": row[8],
            "visit_count": row[9],
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
            method = row[14] or ""
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


# --- Equipment (staff meter inventory / testing) ---

_TWI_EQUIPMENT_RE = re.compile(r"^TWI\d{3}$", re.IGNORECASE)
_METER_PARAMETERS = ("pH", "DO", "EC")
_PASS_FAIL_OPTIONS = ("Pass", "Fail")


def _parse_optional_float(raw):
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s:
        return None, None
    try:
        return float(s), None
    except (TypeError, ValueError):
        return None, "invalid"


def _parse_optional_int(raw):
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s:
        return None, None
    try:
        return int(s), None
    except (TypeError, ValueError):
        return None, "invalid"


def _normalize_equipment_code(code):
    if not code:
        return None
    s = str(code).strip()
    if not _TWI_EQUIPMENT_RE.fullmatch(s):
        return None
    return s.upper()


@app.route("/api/equipment")
def api_equipment():
    """List TWI multiparameter meters with last test date (from v_equipment_inventory)."""
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT equipment_id, equipment_code, equipment_type, serial_number, status,
                   last_test_date::text
            FROM v_equipment_inventory
            WHERE equipment_code ~* '^TWI[0-9]{3}$'
            ORDER BY equipment_code
            """)
        rows = cur.fetchall()
        return jsonify([
            {
                "equipment_id": r[0],
                "equipment_code": r[1],
                "equipment_type": r[2],
                "serial_number": r[3],
                "status": r[4],
                "last_test_date": r[5],
            }
            for r in rows
        ])
    finally:
        conn.close()


@app.route("/api/equipment/<equipment_code>")
def api_equipment_detail(equipment_code):
    """Equipment metadata plus meter-test history (newest first)."""
    code = _normalize_equipment_code(equipment_code)
    if not code:
        return jsonify({"error": "Equipment not found"}), 404
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT e.equipment_id, e.equipment_code, e.equipment_type, e.serial_number, e.status,
                   v.last_test_date::text
            FROM equipment e
            LEFT JOIN v_equipment_inventory v ON v.equipment_id = e.equipment_id
            WHERE e.equipment_code = %s
            """, (code,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Equipment not found"}), 404
        eq = {
            "equipment_id": row[0],
            "equipment_code": row[1],
            "equipment_type": row[2],
            "serial_number": row[3],
            "status": row[4],
            "last_test_date": row[5],
        }
        cur.execute("""
            SELECT s.date_start::text, mt.round_number, mt.parameter_type,
                   mt.reference_value, mt.measured_value, mt.difference, mt.pass_fail
            FROM meter_testing mt
            JOIN session s ON s.session_id = mt.session_id
            WHERE mt.equipment_id = %s
            ORDER BY s.date_start DESC NULLS LAST, mt.round_number DESC NULLS LAST,
                     mt.meter_testing_id DESC
            """, (eq["equipment_id"],))
        tests = []
        for r in cur.fetchall():
            tests.append({
                "test_date": r[0],
                "round_number": r[1],
                "parameter_type": r[2],
                "reference_value": float(r[3]) if r[3] is not None else None,
                "measured_value": float(r[4]) if r[4] is not None else None,
                "difference": float(r[5]) if r[5] is not None else None,
                "pass_fail": r[6],
            })
        eq["meter_tests"] = tests
        return jsonify(eq)
    finally:
        conn.close()


@app.route("/equipment")
def equipment_page():
    return render_template("equipment.html")


@app.route("/equipment/<equipment_code>")
def equipment_detail_page(equipment_code):
    code = _normalize_equipment_code(equipment_code) or equipment_code
    return render_template("equipment_detail.html", equipment_code=code)


@app.route("/equipment/<equipment_code>/meter-tests/new", methods=["GET", "POST"])
def meter_test_new(equipment_code):
    """
    Staff form to add a meter test (creates session + meter_testing).
    NOTE: Write access is intentionally open in this milestone. Protect this route
    (auth / network restriction) before any production deployment.
    """
    code = _normalize_equipment_code(equipment_code)
    if not code:
        return render_template(
            "meter_test_form.html",
            equipment_code=equipment_code,
            error="Equipment not found.",
            form={},
            parameters=_METER_PARAMETERS,
            pass_fail_options=_PASS_FAIL_OPTIONS,
        ), 404

    conn, err = get_db_or_503()
    if err:
        return render_template(
            "meter_test_form.html",
            equipment_code=code,
            error="Service temporarily unavailable. Please try again in a moment.",
            form=request.form if request.method == "POST" else {},
            parameters=_METER_PARAMETERS,
            pass_fail_options=_PASS_FAIL_OPTIONS,
        ), 503

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT equipment_id, equipment_code FROM equipment WHERE equipment_code = %s",
            (code,),
        )
        eq = cur.fetchone()
        if not eq:
            return render_template(
                "meter_test_form.html",
                equipment_code=code,
                error="Equipment not found.",
                form={},
                parameters=_METER_PARAMETERS,
                pass_fail_options=_PASS_FAIL_OPTIONS,
            ), 404
        equipment_id = eq[0]

        if request.method == "GET":
            return render_template(
                "meter_test_form.html",
                equipment_code=code,
                error=None,
                form={},
                parameters=_METER_PARAMETERS,
                pass_fail_options=_PASS_FAIL_OPTIONS,
            )

        form = {
            "test_date": (request.form.get("test_date") or "").strip(),
            "staff": (request.form.get("staff") or "").strip(),
            "parameter_type": (request.form.get("parameter_type") or "").strip(),
            "round_number": (request.form.get("round_number") or "").strip(),
            "reference_value": (request.form.get("reference_value") or "").strip(),
            "measured_value": (request.form.get("measured_value") or "").strip(),
            "pass_fail": (request.form.get("pass_fail") or "").strip(),
            "action_taken": (request.form.get("action_taken") or "").strip(),
        }

        def _form_error(msg):
            return render_template(
                "meter_test_form.html",
                equipment_code=code,
                error=msg,
                form=form,
                parameters=_METER_PARAMETERS,
                pass_fail_options=_PASS_FAIL_OPTIONS,
            ), 400

        if not form["test_date"]:
            return _form_error("Test date is required.")
        try:
            test_date = datetime.strptime(form["test_date"], "%Y-%m-%d").date()
        except ValueError:
            return _form_error("Test date must be a valid date.")

        if form["parameter_type"] not in _METER_PARAMETERS:
            return _form_error("Parameter must be pH, DO, or EC.")

        measured_value, meas_err = _parse_optional_float(form["measured_value"])
        if meas_err or measured_value is None:
            return _form_error("Measured value is required and must be a number.")

        reference_value, ref_err = _parse_optional_float(form["reference_value"])
        if ref_err:
            return _form_error("Reference value must be a number.")

        round_number, round_err = _parse_optional_int(form["round_number"])
        if round_err:
            return _form_error("Round number must be a whole number.")

        pass_fail = form["pass_fail"] or None
        if pass_fail and pass_fail not in _PASS_FAIL_OPTIONS:
            return _form_error("Pass/Fail must be Pass or Fail.")

        staff = form["staff"] or None
        action_taken = form["action_taken"] or None
        difference = None
        if measured_value is not None and reference_value is not None:
            difference = measured_value - reference_value

        try:
            cur.execute(
                "SELECT session_type_id FROM lst_session_type WHERE name = %s",
                ("Quarterly maintenance",),
            )
            st = cur.fetchone()
            if not st:
                conn.rollback()
                return _form_error("Could not save meter test right now. Please try again in a moment.")
            session_type_id = st[0]

            summary = f"Staff meter test {code} ({form['parameter_type']})"
            cur.execute(
                """
                INSERT INTO session (session_type_id, date_start, date_end, staff, summary)
                VALUES (%s, %s, %s, %s, %s) RETURNING session_id
                """,
                (session_type_id, test_date, test_date, staff, summary),
            )
            session_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO meter_testing (
                    session_id, equipment_id, parameter_type, round_number,
                    reference_value, measured_value, difference, pass_fail, action_taken
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    equipment_id,
                    form["parameter_type"],
                    round_number,
                    reference_value,
                    measured_value,
                    difference,
                    pass_fail,
                    action_taken,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            return render_template(
                "meter_test_form.html",
                equipment_code=code,
                error="Could not save meter test right now. Please try again in a moment.",
                form=form,
                parameters=_METER_PARAMETERS,
                pass_fail_options=_PASS_FAIL_OPTIONS,
            ), 500

        return redirect(url_for("equipment_detail_page", equipment_code=code))
    finally:
        conn.close()


# --- Volunteers (staff volunteer management v1) ---

_VOLUNTEER_STATUSES = ("Active", "Inactive", "Parent", "Unknown")
_TRAINING_LOG_STATUSES = ("Passed", "Not Started")


def _form_bool(form, name):
    """Checkbox / truthy form values → bool."""
    return str(form.get(name, "")).strip().lower() in ("1", "true", "yes", "on", "x")


def _parse_optional_date(raw):
    """Parse YYYY-MM-DD to date, or (None, None) if blank, or (None, 'invalid')."""
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s:
        return None, None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date(), None
    except (TypeError, ValueError):
        return None, "invalid"


def _volunteer_row_to_dict(row):
    return {
        "volunteer_id": row[0],
        "first_name": row[1],
        "last_name": row[2],
        "perfect_id": row[3],
        "is_under_17": bool(row[4]),
        "email": row[5],
        "alt_email": row[6],
        "phone": row[7],
        "alt_phone": row[8],
        "address": row[9],
        "city_id": row[10],
        "city_name": row[11],
        "state": (row[12].strip() if row[12] is not None else None),
        "zip_code": row[13],
        "active_cat": bool(row[14]),
        "active_bat": bool(row[15]),
        "active_bact": bool(row[16]),
        "status": row[17],
        "notes": row[18],
    }


def _empty_volunteer_form(defaults=None):
    form = {
        "first_name": "",
        "last_name": "",
        "perfect_id": "",
        "email": "",
        "alt_email": "",
        "phone": "",
        "alt_phone": "",
        "address": "",
        "city_id": "",
        "state": "NJ",
        "zip_code": "",
        "status": "Active",
        "active_cat": False,
        "active_bat": False,
        "active_bact": False,
        "is_under_17": False,
        "notes": "",
    }
    if defaults:
        form.update(defaults)
    return form


def _volunteer_form_from_request():
    return {
        "first_name": (request.form.get("first_name") or "").strip(),
        "last_name": (request.form.get("last_name") or "").strip(),
        "perfect_id": (request.form.get("perfect_id") or "").strip(),
        "email": (request.form.get("email") or "").strip(),
        "alt_email": (request.form.get("alt_email") or "").strip(),
        "phone": (request.form.get("phone") or "").strip(),
        "alt_phone": (request.form.get("alt_phone") or "").strip(),
        "address": (request.form.get("address") or "").strip(),
        "city_id": (request.form.get("city_id") or "").strip(),
        "state": (request.form.get("state") or "").strip(),
        "zip_code": (request.form.get("zip_code") or "").strip(),
        "status": (request.form.get("status") or "").strip(),
        "active_cat": _form_bool(request.form, "active_cat"),
        "active_bat": _form_bool(request.form, "active_bat"),
        "active_bact": _form_bool(request.form, "active_bact"),
        "is_under_17": _form_bool(request.form, "is_under_17"),
        "notes": (request.form.get("notes") or "").strip(),
    }


def _volunteer_to_form(v):
    return {
        "first_name": v.get("first_name") or "",
        "last_name": v.get("last_name") or "",
        "perfect_id": v.get("perfect_id") or "",
        "email": v.get("email") or "",
        "alt_email": v.get("alt_email") or "",
        "phone": v.get("phone") or "",
        "alt_phone": v.get("alt_phone") or "",
        "address": v.get("address") or "",
        "city_id": "" if v.get("city_id") is None else str(v.get("city_id")),
        "state": v.get("state") or "",
        "zip_code": v.get("zip_code") or "",
        "status": v.get("status") or "Unknown",
        "active_cat": bool(v.get("active_cat")),
        "active_bat": bool(v.get("active_bat")),
        "active_bact": bool(v.get("active_bact")),
        "is_under_17": bool(v.get("is_under_17")),
        "notes": v.get("notes") or "",
    }


def _validate_volunteer_form(cur, form):
    """
    Validate volunteer create/edit form fields.
    Returns (error_message_or_None, city_id_or_None, state_val_or_None).
    Mutates form['state'] to normalized 2-letter (or '').
    """
    if not form["first_name"] or not form["last_name"]:
        return "First name and last name are required.", None, None
    if form["status"] not in _VOLUNTEER_STATUSES:
        return "Status must be Active, Inactive, Parent, or Unknown.", None, None

    state_val = form["state"].upper() if form["state"] else None
    if state_val is not None and len(state_val) != 2:
        return "State must be a 2-letter code (for example NJ).", None, None
    form["state"] = state_val or ""

    city_id = None
    if form["city_id"]:
        city_id, city_err = _parse_optional_int(form["city_id"])
        if city_err or city_id is None:
            return "Municipality selection is invalid.", None, None
        cur.execute("SELECT 1 FROM municipality WHERE municipality_id = %s", (city_id,))
        if not cur.fetchone():
            return "Municipality selection is invalid.", None, None
    return None, city_id, state_val


def _load_municipalities(cur):
    cur.execute("SELECT municipality_id, name FROM municipality ORDER BY name")
    return [{"municipality_id": r[0], "name": r[1]} for r in cur.fetchall()]


def _load_volunteer_name(cur, volunteer_id):
    cur.execute(
        "SELECT first_name, last_name FROM volunteer WHERE volunteer_id = %s",
        (volunteer_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    name = ((row[0] or "") + " " + (row[1] or "")).strip()
    return name or ("Volunteer " + str(volunteer_id))


def _load_roles(cur):
    cur.execute("SELECT role_id, name FROM lst_role ORDER BY name")
    return [{"role_id": r[0], "name": r[1]} for r in cur.fetchall()]


def _load_sites_for_assign(cur):
    cur.execute("""
        SELECT s.site_id, s.site_code, w.name AS waterbody_name
        FROM site s
        LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
        WHERE s.is_active = true
        ORDER BY s.site_code
        """)
    return [
        {
            "site_id": r[0],
            "site_code": r[1],
            "label": r[1] + ((" – " + r[2]) if r[2] else ""),
        }
        for r in cur.fetchall()
    ]


def _load_training_types(cur):
    cur.execute("SELECT training_type_id, name FROM lst_training_type ORDER BY name")
    return [{"training_type_id": r[0], "name": r[1]} for r in cur.fetchall()]


def _format_training_session_label(training_date, type_name, trainer, location):
    parts = [type_name or "Unspecified training"]
    if training_date:
        parts.append(str(training_date))
    if trainer:
        parts.append(trainer)
    elif location:
        parts.append(location)
    return " · ".join(parts)


def _load_training_sessions(cur, limit=250):
    cur.execute(
        """
        SELECT t.training_id, t.training_date::text,
               COALESCE(tt.name, 'Unspecified') AS training_type,
               t.trainer, t.location
        FROM training t
        LEFT JOIN lst_training_type tt ON tt.training_type_id = t.training_type_id
        ORDER BY t.training_date DESC NULLS LAST, t.training_id DESC
        LIMIT %s
        """,
        (limit,),
    )
    sessions = []
    for r in cur.fetchall():
        sessions.append(
            {
                "training_id": r[0],
                "training_date": r[1],
                "training_type": r[2],
                "trainer": r[3],
                "location": r[4],
                "label": _format_training_session_label(r[1], r[2], r[3], r[4]),
            }
        )
    return sessions


def _refresh_training_attendee_count(cur, training_id):
    cur.execute(
        """
        UPDATE training
        SET total_attendees = (
            SELECT COUNT(*) FROM training_log WHERE training_id = %s
        )
        WHERE training_id = %s
        """,
        (training_id, training_id),
    )


_VOLUNTEER_SELECT = """
    SELECT v.volunteer_id, v.first_name, v.last_name, v.perfect_id, v.is_under_17,
           v.email, v.alt_email, v.phone, v.alt_phone, v.address,
           v.city_id, m.name AS city_name, v.state, v.zip_code,
           v.active_cat, v.active_bat, v.active_bact, v.status, v.notes
    FROM volunteer v
    LEFT JOIN municipality m ON m.municipality_id = v.city_id
"""


@app.route("/api/volunteers")
def api_volunteers():
    """List volunteers for staff management (searchable client-side)."""
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute(_VOLUNTEER_SELECT + " ORDER BY v.last_name, v.first_name, v.volunteer_id")
        rows = cur.fetchall()
        return jsonify([_volunteer_row_to_dict(r) for r in rows])
    finally:
        conn.close()


@app.route("/api/volunteers/<int:volunteer_id>")
def api_volunteer_detail(volunteer_id):
    """Volunteer profile plus read-only training history and site assignments."""
    conn, err = get_db_or_503()
    if err:
        return err
    try:
        cur = conn.cursor()
        cur.execute(_VOLUNTEER_SELECT + " WHERE v.volunteer_id = %s", (volunteer_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Volunteer not found"}), 404
        vol = _volunteer_row_to_dict(row)

        cur.execute("""
            SELECT COALESCE(tt.name, 'Unspecified') AS training_type,
                   t.training_date::text, tl.status, tl.expiration_date::text, t.trainer
            FROM training_log tl
            JOIN training t ON t.training_id = tl.training_id
            LEFT JOIN lst_training_type tt ON tt.training_type_id = t.training_type_id
            WHERE tl.volunteer_id = %s
            ORDER BY t.training_date DESC NULLS LAST, tl.training_log_id DESC
            """, (volunteer_id,))
        vol["trainings"] = [
            {
                "training_type": r[0],
                "training_date": r[1],
                "status": r[2],
                "expiration_date": r[3],
                "trainer": r[4],
            }
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT a.assignment_id, s.site_code, w.name AS waterbody_name, r.name AS role_name,
                   a.start_date::text, a.end_date::text
            FROM junc_assignments a
            JOIN site s ON s.site_id = a.site_id
            LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
            LEFT JOIN lst_role r ON r.role_id = a.role_id
            WHERE a.volunteer_id = %s
            ORDER BY (a.end_date IS NULL) DESC, a.start_date DESC NULLS LAST, s.site_code
            """, (volunteer_id,))
        vol["assignments"] = [
            {
                "assignment_id": r[0],
                "site_code": r[1],
                "waterbody_name": r[2],
                "role": r[3] or "Unspecified",
                "start_date": r[4],
                "end_date": r[5],
                "is_active": r[5] is None,
            }
            for r in cur.fetchall()
        ]
        return jsonify(vol)
    finally:
        conn.close()


@app.route("/volunteers")
def volunteers_page():
    return render_template("volunteers.html")


@app.route("/volunteers/new", methods=["GET", "POST"])
def volunteer_new():
    """
    Staff form to create a new volunteer record.
    NOTE: Write access is intentionally open in this milestone. Protect this route
    (auth / network restriction) before any production deployment.
    """
    conn, err = get_db_or_503()
    if err:
        return render_template(
            "volunteer_new.html",
            error="Service temporarily unavailable. Please try again in a moment.",
            form=_empty_volunteer_form(),
            municipalities=[],
            statuses=_VOLUNTEER_STATUSES,
        ), 503

    try:
        cur = conn.cursor()
        municipalities = _load_municipalities(cur)

        if request.method == "GET":
            return render_template(
                "volunteer_new.html",
                error=None,
                form=_empty_volunteer_form(),
                municipalities=municipalities,
                statuses=_VOLUNTEER_STATUSES,
            )

        form = _volunteer_form_from_request()

        def _form_error(msg):
            return render_template(
                "volunteer_new.html",
                error=msg,
                form=form,
                municipalities=municipalities,
                statuses=_VOLUNTEER_STATUSES,
            ), 400

        val_err, city_id, state_val = _validate_volunteer_form(cur, form)
        if val_err:
            return _form_error(val_err)

        try:
            cur.execute(
                """
                INSERT INTO volunteer (
                    first_name, last_name, perfect_id, email, alt_email, phone, alt_phone,
                    address, city_id, state, zip_code, status,
                    active_cat, active_bat, active_bact, is_under_17, notes
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, COALESCE(%s, 'NJ'), %s, %s::volunteer_status_enum,
                    %s, %s, %s, %s, %s
                )
                RETURNING volunteer_id
                """,
                (
                    form["first_name"],
                    form["last_name"],
                    form["perfect_id"] or None,
                    form["email"] or None,
                    form["alt_email"] or None,
                    form["phone"] or None,
                    form["alt_phone"] or None,
                    form["address"] or None,
                    city_id,
                    state_val,
                    form["zip_code"] or None,
                    form["status"],
                    form["active_cat"],
                    form["active_bat"],
                    form["active_bact"],
                    form["is_under_17"],
                    form["notes"] or None,
                ),
            )
            new_id = cur.fetchone()[0]
            conn.commit()
        except Exception:
            conn.rollback()
            return render_template(
                "volunteer_new.html",
                error="Could not save volunteer right now. Please try again in a moment.",
                form=form,
                municipalities=municipalities,
                statuses=_VOLUNTEER_STATUSES,
            ), 500

        return redirect(url_for("volunteer_detail_page", volunteer_id=new_id))
    finally:
        conn.close()


@app.route("/volunteers/<int:volunteer_id>")
def volunteer_detail_page(volunteer_id):
    return render_template("volunteer_detail.html", volunteer_id=volunteer_id)


@app.route("/volunteers/<int:volunteer_id>/edit", methods=["GET", "POST"])
def volunteer_edit(volunteer_id):
    """
    Staff form to edit an existing volunteer record.
    NOTE: Write access is intentionally open in this milestone. Protect this route
    (auth / network restriction) before any production deployment.
    """
    conn, err = get_db_or_503()
    if err:
        return render_template(
            "volunteer_edit.html",
            volunteer_id=volunteer_id,
            error="Service temporarily unavailable. Please try again in a moment.",
            form=_empty_volunteer_form(),
            municipalities=[],
            statuses=_VOLUNTEER_STATUSES,
        ), 503

    try:
        cur = conn.cursor()
        cur.execute(_VOLUNTEER_SELECT + " WHERE v.volunteer_id = %s", (volunteer_id,))
        row = cur.fetchone()
        if not row:
            return render_template(
                "volunteer_edit.html",
                volunteer_id=volunteer_id,
                error="Volunteer not found.",
                form=_empty_volunteer_form(),
                municipalities=[],
                statuses=_VOLUNTEER_STATUSES,
            ), 404
        vol = _volunteer_row_to_dict(row)
        municipalities = _load_municipalities(cur)

        if request.method == "GET":
            return render_template(
                "volunteer_edit.html",
                volunteer_id=volunteer_id,
                error=None,
                form=_volunteer_to_form(vol),
                municipalities=municipalities,
                statuses=_VOLUNTEER_STATUSES,
            )

        form = _volunteer_form_from_request()

        def _form_error(msg):
            return render_template(
                "volunteer_edit.html",
                volunteer_id=volunteer_id,
                error=msg,
                form=form,
                municipalities=municipalities,
                statuses=_VOLUNTEER_STATUSES,
            ), 400

        val_err, city_id, state_val = _validate_volunteer_form(cur, form)
        if val_err:
            return _form_error(val_err)

        try:
            cur.execute(
                """
                UPDATE volunteer SET
                    first_name = %s,
                    last_name = %s,
                    perfect_id = %s,
                    email = %s,
                    alt_email = %s,
                    phone = %s,
                    alt_phone = %s,
                    address = %s,
                    city_id = %s,
                    state = COALESCE(%s, state),
                    zip_code = %s,
                    status = %s::volunteer_status_enum,
                    active_cat = %s,
                    active_bat = %s,
                    active_bact = %s,
                    is_under_17 = %s,
                    notes = %s,
                    updated_at = NOW()
                WHERE volunteer_id = %s
                """,
                (
                    form["first_name"],
                    form["last_name"],
                    form["perfect_id"] or None,
                    form["email"] or None,
                    form["alt_email"] or None,
                    form["phone"] or None,
                    form["alt_phone"] or None,
                    form["address"] or None,
                    city_id,
                    state_val,
                    form["zip_code"] or None,
                    form["status"],
                    form["active_cat"],
                    form["active_bat"],
                    form["active_bact"],
                    form["is_under_17"],
                    form["notes"] or None,
                    volunteer_id,
                ),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return _form_error("Volunteer not found.")
            conn.commit()
        except Exception:
            conn.rollback()
            return render_template(
                "volunteer_edit.html",
                volunteer_id=volunteer_id,
                error="Could not save volunteer right now. Please try again in a moment.",
                form=form,
                municipalities=municipalities,
                statuses=_VOLUNTEER_STATUSES,
            ), 500

        return redirect(url_for("volunteer_detail_page", volunteer_id=volunteer_id))
    finally:
        conn.close()


@app.route("/volunteers/<int:volunteer_id>/assignments/new", methods=["GET", "POST"])
def volunteer_assignment_new(volunteer_id):
    """Assign a volunteer to a site (junc_assignments)."""
    conn, err = get_db_or_503()
    if err:
        return render_template(
            "volunteer_assignment_form.html",
            volunteer_id=volunteer_id,
            volunteer_name="Volunteer",
            mode="new",
            assignment_id=None,
            error="Service temporarily unavailable. Please try again in a moment.",
            form={},
            sites=[],
            roles=[],
            current_assignments=[],
        ), 503

    try:
        cur = conn.cursor()
        volunteer_name = _load_volunteer_name(cur, volunteer_id)
        if not volunteer_name:
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name="Volunteer",
                mode="new",
                assignment_id=None,
                error="Volunteer not found.",
                form={},
                sites=[],
                roles=[],
                current_assignments=[],
            ), 404

        sites = _load_sites_for_assign(cur)
        roles = _load_roles(cur)
        cur.execute("""
            SELECT s.site_code, r.name AS role_name, a.start_date::text, a.end_date::text
            FROM junc_assignments a
            JOIN site s ON s.site_id = a.site_id
            LEFT JOIN lst_role r ON r.role_id = a.role_id
            WHERE a.volunteer_id = %s
            ORDER BY (a.end_date IS NULL) DESC, a.start_date DESC NULLS LAST, s.site_code
            """, (volunteer_id,))
        current_assignments = [
            {
                "site_code": r[0],
                "role": r[1] or "Unspecified",
                "start_date": r[2],
                "end_date": r[3],
                "is_active": r[3] is None,
            }
            for r in cur.fetchall()
        ]

        empty_form = {"site_id": "", "role_id": "", "start_date": "", "end_date": ""}

        if request.method == "GET":
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                mode="new",
                assignment_id=None,
                error=None,
                form=empty_form,
                sites=sites,
                roles=roles,
                current_assignments=current_assignments,
            )

        form = {
            "site_id": (request.form.get("site_id") or "").strip(),
            "role_id": (request.form.get("role_id") or "").strip(),
            "start_date": (request.form.get("start_date") or "").strip(),
            "end_date": (request.form.get("end_date") or "").strip(),
        }

        def _form_error(msg):
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                mode="new",
                assignment_id=None,
                error=msg,
                form=form,
                sites=sites,
                roles=roles,
                current_assignments=current_assignments,
            ), 400

        site_id, site_err = _parse_optional_int(form["site_id"])
        if site_err or site_id is None:
            return _form_error("Site is required.")
        cur.execute("SELECT 1 FROM site WHERE site_id = %s", (site_id,))
        if not cur.fetchone():
            return _form_error("Site selection is invalid.")

        role_id = None
        if form["role_id"]:
            role_id, role_err = _parse_optional_int(form["role_id"])
            if role_err or role_id is None:
                return _form_error("Role selection is invalid.")
            cur.execute("SELECT 1 FROM lst_role WHERE role_id = %s", (role_id,))
            if not cur.fetchone():
                return _form_error("Role selection is invalid.")

        start_date, start_err = _parse_optional_date(form["start_date"])
        if start_err:
            return _form_error("Start date must be a valid date.")
        end_date, end_err = _parse_optional_date(form["end_date"])
        if end_err:
            return _form_error("End date must be a valid date.")
        if start_date and end_date and end_date < start_date:
            return _form_error("End date cannot be before start date.")

        cur.execute(
            "SELECT 1 FROM junc_assignments WHERE volunteer_id = %s AND site_id = %s",
            (volunteer_id, site_id),
        )
        if cur.fetchone():
            return _form_error(
                "This volunteer already has an assignment for that site. "
                "Edit the existing assignment instead of creating a new one."
            )

        try:
            cur.execute(
                """
                INSERT INTO junc_assignments (volunteer_id, site_id, role_id, start_date, end_date)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (volunteer_id, site_id, role_id, start_date, end_date),
            )
            conn.commit()
        except psycopg2.IntegrityError:
            conn.rollback()
            return _form_error(
                "This volunteer already has an assignment for that site. "
                "Edit the existing assignment instead of creating a new one."
            )
        except Exception:
            conn.rollback()
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                mode="new",
                assignment_id=None,
                error="Could not save assignment right now. Please try again in a moment.",
                form=form,
                sites=sites,
                roles=roles,
                current_assignments=current_assignments,
            ), 500

        return redirect(url_for("volunteer_detail_page", volunteer_id=volunteer_id))
    finally:
        conn.close()


@app.route(
    "/volunteers/<int:volunteer_id>/assignments/<int:assignment_id>/edit",
    methods=["GET", "POST"],
)
def volunteer_assignment_edit(volunteer_id, assignment_id):
    """Edit role/dates for an existing assignment (including ending it)."""
    conn, err = get_db_or_503()
    if err:
        return render_template(
            "volunteer_assignment_form.html",
            volunteer_id=volunteer_id,
            volunteer_name="Volunteer",
            mode="edit",
            assignment_id=assignment_id,
            error="Service temporarily unavailable. Please try again in a moment.",
            form={},
            sites=[],
            roles=[],
            current_assignments=[],
            site_label="",
        ), 503

    try:
        cur = conn.cursor()
        volunteer_name = _load_volunteer_name(cur, volunteer_id)
        if not volunteer_name:
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name="Volunteer",
                mode="edit",
                assignment_id=assignment_id,
                error="Volunteer not found.",
                form={},
                sites=[],
                roles=[],
                current_assignments=[],
                site_label="",
            ), 404

        cur.execute("""
            SELECT a.assignment_id, a.site_id, a.role_id, a.start_date::text, a.end_date::text,
                   s.site_code, w.name AS waterbody_name
            FROM junc_assignments a
            JOIN site s ON s.site_id = a.site_id
            LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
            WHERE a.assignment_id = %s AND a.volunteer_id = %s
            """, (assignment_id, volunteer_id))
        row = cur.fetchone()
        if not row:
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                mode="edit",
                assignment_id=assignment_id,
                error="Assignment not found for this volunteer.",
                form={},
                sites=[],
                roles=_load_roles(cur),
                current_assignments=[],
                site_label="",
            ), 404

        site_label = row[5] + ((" – " + row[6]) if row[6] else "")
        roles = _load_roles(cur)
        form_from_db = {
            "site_id": str(row[1]),
            "role_id": "" if row[2] is None else str(row[2]),
            "start_date": row[3] or "",
            "end_date": row[4] or "",
        }

        if request.method == "GET":
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                mode="edit",
                assignment_id=assignment_id,
                error=None,
                form=form_from_db,
                sites=[],
                roles=roles,
                current_assignments=[],
                site_label=site_label,
            )

        form = {
            "site_id": form_from_db["site_id"],
            "role_id": (request.form.get("role_id") or "").strip(),
            "start_date": (request.form.get("start_date") or "").strip(),
            "end_date": (request.form.get("end_date") or "").strip(),
        }

        def _form_error(msg):
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                mode="edit",
                assignment_id=assignment_id,
                error=msg,
                form=form,
                sites=[],
                roles=roles,
                current_assignments=[],
                site_label=site_label,
            ), 400

        role_id = None
        if form["role_id"]:
            role_id, role_err = _parse_optional_int(form["role_id"])
            if role_err or role_id is None:
                return _form_error("Role selection is invalid.")
            cur.execute("SELECT 1 FROM lst_role WHERE role_id = %s", (role_id,))
            if not cur.fetchone():
                return _form_error("Role selection is invalid.")

        start_date, start_err = _parse_optional_date(form["start_date"])
        if start_err:
            return _form_error("Start date must be a valid date.")
        end_date, end_err = _parse_optional_date(form["end_date"])
        if end_err:
            return _form_error("End date must be a valid date.")
        if start_date and end_date and end_date < start_date:
            return _form_error("End date cannot be before start date.")

        try:
            cur.execute(
                """
                UPDATE junc_assignments
                SET role_id = %s, start_date = %s, end_date = %s
                WHERE assignment_id = %s AND volunteer_id = %s
                """,
                (role_id, start_date, end_date, assignment_id, volunteer_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return _form_error("Assignment not found for this volunteer.")
            conn.commit()
        except Exception:
            conn.rollback()
            return render_template(
                "volunteer_assignment_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                mode="edit",
                assignment_id=assignment_id,
                error="Could not save assignment right now. Please try again in a moment.",
                form=form,
                sites=[],
                roles=roles,
                current_assignments=[],
                site_label=site_label,
            ), 500

        return redirect(url_for("volunteer_detail_page", volunteer_id=volunteer_id))
    finally:
        conn.close()


@app.route("/trainings/new", methods=["GET", "POST"])
def training_session_new():
    """
    Create a training session/event (training table only).
    Optional ?volunteer_id=N returns to that volunteer's attendance form after create.
    """
    volunteer_id_raw = (request.values.get("volunteer_id") or "").strip()
    return_volunteer_id = None
    if volunteer_id_raw:
        return_volunteer_id, _ = _parse_optional_int(volunteer_id_raw)
        if return_volunteer_id is None:
            return_volunteer_id = None

    today = date.today().isoformat()
    empty_form = {
        "training_type_id": "",
        "training_date": today,
        "trainer": "",
        "location": "",
        "notes": "",
    }

    conn, err = get_db_or_503()
    if err:
        return render_template(
            "training_new.html",
            error="Service temporarily unavailable. Please try again in a moment.",
            form=empty_form,
            training_types=[],
            volunteer_id=return_volunteer_id,
            volunteer_name=None,
        ), 503

    try:
        cur = conn.cursor()
        training_types = _load_training_types(cur)
        volunteer_name = None
        if return_volunteer_id is not None:
            volunteer_name = _load_volunteer_name(cur, return_volunteer_id)
            if not volunteer_name:
                return_volunteer_id = None

        if request.method == "GET":
            return render_template(
                "training_new.html",
                error=None,
                form=empty_form,
                training_types=training_types,
                volunteer_id=return_volunteer_id,
                volunteer_name=volunteer_name,
            )

        form = {
            "training_type_id": (request.form.get("training_type_id") or "").strip(),
            "training_date": (request.form.get("training_date") or "").strip(),
            "trainer": (request.form.get("trainer") or "").strip(),
            "location": (request.form.get("location") or "").strip(),
            "notes": (request.form.get("notes") or "").strip(),
        }

        def _form_error(msg):
            return render_template(
                "training_new.html",
                error=msg,
                form=form,
                training_types=training_types,
                volunteer_id=return_volunteer_id,
                volunteer_name=volunteer_name,
            ), 400

        if not form["training_date"]:
            return _form_error("Training date is required.")
        training_date, date_err = _parse_optional_date(form["training_date"])
        if date_err or training_date is None:
            return _form_error("Training date must be a valid date.")

        training_type_id = None
        if form["training_type_id"]:
            training_type_id, tt_err = _parse_optional_int(form["training_type_id"])
            if tt_err or training_type_id is None:
                return _form_error("Training type selection is invalid.")
            cur.execute(
                "SELECT 1 FROM lst_training_type WHERE training_type_id = %s",
                (training_type_id,),
            )
            if not cur.fetchone():
                return _form_error("Training type selection is invalid.")

        try:
            cur.execute(
                """
                INSERT INTO training (
                    training_type_id, training_date, trainer, location, notes, total_attendees
                ) VALUES (%s, %s, %s, %s, %s, 0)
                RETURNING training_id
                """,
                (
                    training_type_id,
                    training_date,
                    form["trainer"] or None,
                    form["location"] or None,
                    form["notes"] or None,
                ),
            )
            training_id = cur.fetchone()[0]
            conn.commit()
        except Exception:
            conn.rollback()
            return render_template(
                "training_new.html",
                error="Could not save training session right now. Please try again in a moment.",
                form=form,
                training_types=training_types,
                volunteer_id=return_volunteer_id,
                volunteer_name=volunteer_name,
            ), 500

        if return_volunteer_id is not None:
            return redirect(
                url_for(
                    "volunteer_training_new",
                    volunteer_id=return_volunteer_id,
                    training_id=training_id,
                )
            )
        return redirect(url_for("training_detail_page", training_id=training_id))
    finally:
        conn.close()


@app.route("/trainings/<int:training_id>")
def training_detail_page(training_id):
    """Compact training session view with attendees."""
    conn, err = get_db_or_503()
    if err:
        return render_template(
            "training_detail.html",
            error="Service temporarily unavailable. Please try again in a moment.",
            session=None,
            attendees=[],
        ), 503
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.training_id, t.training_date::text,
                   COALESCE(tt.name, 'Unspecified') AS training_type,
                   t.trainer, t.location, t.notes, t.total_attendees
            FROM training t
            LEFT JOIN lst_training_type tt ON tt.training_type_id = t.training_type_id
            WHERE t.training_id = %s
            """,
            (training_id,),
        )
        row = cur.fetchone()
        if not row:
            return render_template(
                "training_detail.html",
                error="Training session not found.",
                session=None,
                attendees=[],
            ), 404
        session = {
            "training_id": row[0],
            "training_date": row[1],
            "training_type": row[2],
            "trainer": row[3],
            "location": row[4],
            "notes": row[5],
            "total_attendees": row[6],
        }
        cur.execute(
            """
            SELECT v.volunteer_id, v.first_name, v.last_name, tl.status, tl.expiration_date::text
            FROM training_log tl
            JOIN volunteer v ON v.volunteer_id = tl.volunteer_id
            WHERE tl.training_id = %s
            ORDER BY v.last_name, v.first_name, v.volunteer_id
            """,
            (training_id,),
        )
        attendees = [
            {
                "volunteer_id": r[0],
                "name": ((r[1] or "") + " " + (r[2] or "")).strip() or ("Volunteer " + str(r[0])),
                "status": r[3],
                "expiration_date": r[4],
            }
            for r in cur.fetchall()
        ]
        return render_template(
            "training_detail.html",
            error=None,
            session=session,
            attendees=attendees,
        )
    finally:
        conn.close()


@app.route("/volunteers/<int:volunteer_id>/training/new", methods=["GET", "POST"])
def volunteer_training_new(volunteer_id):
    """
    Record attendance for an existing training session (training_log only).
    Optional ?training_id=N preselects a session (e.g. after creating one).
    """
    preset_training_id = (request.values.get("training_id") or "").strip()
    empty_form = {
        "training_id": preset_training_id,
        "status": "Passed",
        "expiration_date": "",
    }

    conn, err = get_db_or_503()
    if err:
        return render_template(
            "volunteer_training_form.html",
            volunteer_id=volunteer_id,
            volunteer_name="Volunteer",
            error="Service temporarily unavailable. Please try again in a moment.",
            form=empty_form,
            sessions=[],
            statuses=_TRAINING_LOG_STATUSES,
        ), 503

    try:
        cur = conn.cursor()
        volunteer_name = _load_volunteer_name(cur, volunteer_id)
        if not volunteer_name:
            return render_template(
                "volunteer_training_form.html",
                volunteer_id=volunteer_id,
                volunteer_name="Volunteer",
                error="Volunteer not found.",
                form=empty_form,
                sessions=[],
                statuses=_TRAINING_LOG_STATUSES,
            ), 404

        sessions = _load_training_sessions(cur)

        if request.method == "GET":
            return render_template(
                "volunteer_training_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                error=None,
                form=empty_form,
                sessions=sessions,
                statuses=_TRAINING_LOG_STATUSES,
            )

        form = {
            "training_id": (request.form.get("training_id") or "").strip(),
            "status": (request.form.get("status") or "").strip(),
            "expiration_date": (request.form.get("expiration_date") or "").strip(),
        }

        def _form_error(msg):
            return render_template(
                "volunteer_training_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                error=msg,
                form=form,
                sessions=sessions,
                statuses=_TRAINING_LOG_STATUSES,
            ), 400

        training_id, tid_err = _parse_optional_int(form["training_id"])
        if tid_err or training_id is None:
            return _form_error("Training session is required.")
        cur.execute("SELECT 1 FROM training WHERE training_id = %s", (training_id,))
        if not cur.fetchone():
            return _form_error("Training session selection is invalid.")

        status_val = form["status"] or None
        if status_val and status_val not in _TRAINING_LOG_STATUSES:
            return _form_error("Attendance status is invalid.")

        expiration_date, exp_err = _parse_optional_date(form["expiration_date"])
        if exp_err:
            return _form_error("Expiration date must be a valid date.")

        cur.execute(
            """
            SELECT 1 FROM training_log
            WHERE training_id = %s AND volunteer_id = %s
            """,
            (training_id, volunteer_id),
        )
        if cur.fetchone():
            return _form_error(
                "This volunteer is already recorded for that training session."
            )

        try:
            cur.execute(
                """
                INSERT INTO training_log (
                    training_id, volunteer_id, status, expiration_date
                ) VALUES (%s, %s, %s, %s)
                """,
                (training_id, volunteer_id, status_val, expiration_date),
            )
            _refresh_training_attendee_count(cur, training_id)
            conn.commit()
        except psycopg2.IntegrityError:
            conn.rollback()
            return _form_error(
                "This volunteer is already recorded for that training session."
            )
        except Exception:
            conn.rollback()
            return render_template(
                "volunteer_training_form.html",
                volunteer_id=volunteer_id,
                volunteer_name=volunteer_name,
                error="Could not save attendance right now. Please try again in a moment.",
                form=form,
                sessions=sessions,
                statuses=_TRAINING_LOG_STATUSES,
            ), 500

        return redirect(url_for("volunteer_detail_page", volunteer_id=volunteer_id))
    finally:
        conn.close()


@app.route("/static/<path:path>")
def static_file(path):
    return send_from_directory(app.static_folder, path)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
