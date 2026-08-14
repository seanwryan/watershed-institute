"""
Read-only StreamWatch report query helpers (Reporting & Export Integrity v1).

Used by dashboard/app.py HTML report routes. No writes.
"""
from __future__ import annotations

from datetime import date


REPORT_CHEM_FIELDS = [
    ("water_temp_c", "Water temperature", "°C"),
    ("nitrate_ug_l", "Nitrate", "µg/L"),
    ("phosphate_mg_l", "Phosphate", "mg/L"),
    ("ph", "pH", ""),
    ("turbidity_ntu", "Turbidity", "NTU"),
    ("dissolved_oxygen_ppm", "Dissolved oxygen", "mg/L"),
    ("dissolved_oxygen_pct", "Dissolved oxygen saturation", "%"),
    ("conductivity_us_cm", "Conductivity", "µS/cm"),
    ("chloride_mg_l", "Chloride", "mg/L"),
    ("air_temp_c", "Air temperature", "°C"),
]


def parse_optional_date(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def load_site_options(cur):
    cur.execute(
        """
        SELECT s.site_code, w.name AS waterbody_name
        FROM site s
        LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
        ORDER BY s.site_code
        """
    )
    return [{"site_code": r[0], "waterbody_name": r[1]} for r in cur.fetchall()]


def load_volunteer_options(cur):
    cur.execute(
        """
        SELECT volunteer_id,
               TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS name
        FROM volunteer
        ORDER BY last_name NULLS LAST, first_name NULLS LAST, volunteer_id
        """
    )
    return [{"volunteer_id": r[0], "name": (r[1] or f"Volunteer {r[0]}").strip()} for r in cur.fetchall()]


def site_summary_rows(cur, q="", status=""):
    q = (q or "").strip()
    status = (status or "").strip().lower()
    clauses = ["TRUE"]
    params = []
    if q:
        clauses.append(
            "(s.site_code ILIKE %s OR COALESCE(w.name, '') ILIKE %s)"
        )
        like = f"%{q}%"
        params.extend([like, like])
    if status == "active":
        clauses.append("s.is_active = TRUE")
    elif status == "inactive":
        clauses.append("s.is_active = FALSE")
    where = " AND ".join(clauses)
    cur.execute(
        f"""
        SELECT s.site_code,
               w.name AS waterbody_name,
               s.is_active,
               s.habitat_type::text,
               (SELECT MAX(v.sample_date)::text FROM visit v WHERE v.site_id = s.site_id) AS last_sample_date,
               (SELECT COUNT(*) FROM visit v WHERE v.site_id = s.site_id) AS visit_count
        FROM site s
        LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
        WHERE {where}
        ORDER BY s.site_code
        """,
        params,
    )
    rows = []
    for r in cur.fetchall():
        rows.append(
            {
                "site_code": r[0],
                "waterbody_name": r[1],
                "is_active": bool(r[2]),
                "habitat_type": r[3],
                "last_sample_date": r[4],
                "visit_count": int(r[5] or 0),
            }
        )
    return rows


def visit_history_rows(cur, site_code="", date_start=None, date_end=None, limit=500):
    clauses = ["TRUE"]
    params = []
    if site_code:
        clauses.append("s.site_code = %s")
        params.append(site_code)
    if date_start:
        clauses.append("v.sample_date >= %s")
        params.append(date_start)
    if date_end:
        clauses.append("v.sample_date <= %s")
        params.append(date_end)
    where = " AND ".join(clauses)
    params.append(limit)
    cur.execute(
        f"""
        SELECT v.visit_id,
               s.site_code,
               v.sample_date::text,
               m.name AS method_name,
               EXISTS (SELECT 1 FROM chemical c WHERE c.visit_id = v.visit_id) AS has_chemistry,
               EXISTS (SELECT 1 FROM bacteria b WHERE b.visit_id = v.visit_id) AS has_bacteria,
               EXISTS (SELECT 1 FROM habitat_assessment h WHERE h.visit_id = v.visit_id) AS has_habitat,
               EXISTS (SELECT 1 FROM bug_count bc WHERE bc.visit_id = v.visit_id) AS has_macro
        FROM visit v
        JOIN site s ON s.site_id = v.site_id
        LEFT JOIN lst_method m ON m.method_id = v.method_id
        WHERE {where}
        ORDER BY v.sample_date DESC, s.site_code, v.visit_id DESC
        LIMIT %s
        """,
        params,
    )
    rows = []
    for r in cur.fetchall():
        rows.append(
            {
                "visit_id": r[0],
                "site_code": r[1],
                "sample_date": r[2],
                "method_name": r[3],
                "has_chemistry": bool(r[4]),
                "has_bacteria": bool(r[5]),
                "has_habitat": bool(r[6]),
                "has_macro": bool(r[7]),
            }
        )
    return rows


def completeness_summary(cur, site_code="", date_start=None, date_end=None):
    clauses = ["TRUE"]
    params = []
    if site_code:
        clauses.append("s.site_code = %s")
        params.append(site_code)
    if date_start:
        clauses.append("v.sample_date >= %s")
        params.append(date_start)
    if date_end:
        clauses.append("v.sample_date <= %s")
        params.append(date_end)
    where = " AND ".join(clauses)
    cur.execute(
        f"""
        SELECT
          COUNT(*) AS total_visits,
          COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM chemical c WHERE c.visit_id = v.visit_id)) AS with_chemistry,
          COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM chemical c WHERE c.visit_id = v.visit_id)) AS without_chemistry,
          COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM bacteria b WHERE b.visit_id = v.visit_id)) AS with_bacteria,
          COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM bacteria b WHERE b.visit_id = v.visit_id)) AS without_bacteria,
          COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM bug_count bc WHERE bc.visit_id = v.visit_id)) AS with_macro,
          COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM habitat_assessment h WHERE h.visit_id = v.visit_id)) AS with_habitat
        FROM visit v
        JOIN site s ON s.site_id = v.site_id
        WHERE {where}
        """,
        params,
    )
    r = cur.fetchone()
    return {
        "total_visits": int(r[0] or 0),
        "with_chemistry": int(r[1] or 0),
        "without_chemistry": int(r[2] or 0),
        "with_bacteria": int(r[3] or 0),
        "without_bacteria": int(r[4] or 0),
        "with_macro": int(r[5] or 0),
        "with_habitat": int(r[6] or 0),
    }


def completeness_rows(cur, site_code="", date_start=None, date_end=None, gap="", limit=500):
    clauses = ["TRUE"]
    params = []
    if site_code:
        clauses.append("s.site_code = %s")
        params.append(site_code)
    if date_start:
        clauses.append("v.sample_date >= %s")
        params.append(date_start)
    if date_end:
        clauses.append("v.sample_date <= %s")
        params.append(date_end)
    gap = (gap or "").strip()
    if gap == "no_chemistry":
        clauses.append("NOT EXISTS (SELECT 1 FROM chemical c WHERE c.visit_id = v.visit_id)")
    elif gap == "no_bacteria":
        clauses.append("NOT EXISTS (SELECT 1 FROM bacteria b WHERE b.visit_id = v.visit_id)")
    elif gap == "no_habitat":
        clauses.append("NOT EXISTS (SELECT 1 FROM habitat_assessment h WHERE h.visit_id = v.visit_id)")
    elif gap == "no_macro":
        clauses.append("NOT EXISTS (SELECT 1 FROM bug_count bc WHERE bc.visit_id = v.visit_id)")
    where = " AND ".join(clauses)
    params.append(limit)
    cur.execute(
        f"""
        SELECT v.visit_id, s.site_code, v.sample_date::text,
               EXISTS (SELECT 1 FROM chemical c WHERE c.visit_id = v.visit_id),
               EXISTS (SELECT 1 FROM bacteria b WHERE b.visit_id = v.visit_id),
               EXISTS (SELECT 1 FROM habitat_assessment h WHERE h.visit_id = v.visit_id),
               EXISTS (SELECT 1 FROM bug_count bc WHERE bc.visit_id = v.visit_id)
        FROM visit v
        JOIN site s ON s.site_id = v.site_id
        WHERE {where}
        ORDER BY v.sample_date DESC, s.site_code
        LIMIT %s
        """,
        params,
    )
    return [
        {
            "visit_id": r[0],
            "site_code": r[1],
            "sample_date": r[2],
            "has_chemistry": bool(r[3]),
            "has_bacteria": bool(r[4]),
            "has_habitat": bool(r[5]),
            "has_macro": bool(r[6]),
        }
        for r in cur.fetchall()
    ]


def training_rows(
    cur,
    volunteer_id=None,
    training_type_id=None,
    status="",
    expires_before=None,
    today=None,
):
    today = today or date.today()
    clauses = ["TRUE"]
    params = []
    if volunteer_id:
        clauses.append("vol.volunteer_id = %s")
        params.append(volunteer_id)
    if training_type_id:
        clauses.append("t.training_type_id = %s")
        params.append(training_type_id)
    if expires_before:
        clauses.append("tl.expiration_date IS NOT NULL AND tl.expiration_date < %s")
        params.append(expires_before)
    status = (status or "").strip().lower()
    if status == "expired":
        clauses.append("tl.expiration_date IS NOT NULL AND tl.expiration_date < %s")
        params.append(today)
    elif status == "current":
        clauses.append("tl.expiration_date IS NOT NULL AND tl.expiration_date >= %s")
        params.append(today)
    elif status == "no_expiration":
        clauses.append("tl.expiration_date IS NULL")
    where = " AND ".join(clauses)
    cur.execute(
        f"""
        SELECT vol.volunteer_id,
               TRIM(COALESCE(vol.first_name, '') || ' ' || COALESCE(vol.last_name, '')),
               tt.name,
               t.training_date::text,
               tl.status,
               tl.expiration_date,
               tl.training_log_id
        FROM training_log tl
        JOIN volunteer vol ON vol.volunteer_id = tl.volunteer_id
        JOIN training t ON t.training_id = tl.training_id
        LEFT JOIN lst_training_type tt ON tt.training_type_id = t.training_type_id
        WHERE {where}
        ORDER BY tl.expiration_date NULLS LAST, vol.last_name NULLS LAST, vol.first_name, t.training_date DESC
        """,
        params,
    )
    rows = []
    for r in cur.fetchall():
        exp = r[5]
        if exp is None:
            exp_status = "No expiration date"
            days = None
        else:
            days = (exp - today).days
            exp_status = "Expired" if exp < today else "Current"
        rows.append(
            {
                "volunteer_id": r[0],
                "volunteer_name": (r[1] or f"Volunteer {r[0]}").strip(),
                "training_type": r[2],
                "training_date": r[3],
                "attendance_status": r[4],
                "expiration_date": exp.isoformat() if exp else None,
                "days_until_expiration": days,
                "expiration_status": exp_status,
            }
        )
    return rows


def assignment_rows(cur, site_code="", volunteer_id=None, role_id=None, active="", today=None):
    today = today or date.today()
    clauses = ["TRUE"]
    params = []
    if site_code:
        clauses.append("s.site_code = %s")
        params.append(site_code)
    if volunteer_id:
        clauses.append("vol.volunteer_id = %s")
        params.append(volunteer_id)
    if role_id:
        clauses.append("a.role_id = %s")
        params.append(role_id)
    active = (active or "").strip().lower()
    if active == "active":
        clauses.append("(a.end_date IS NULL OR a.end_date >= %s)")
        params.append(today)
    elif active == "ended":
        clauses.append("a.end_date IS NOT NULL AND a.end_date < %s")
        params.append(today)
    where = " AND ".join(clauses)
    cur.execute(
        f"""
        SELECT vol.volunteer_id,
               TRIM(COALESCE(vol.first_name, '') || ' ' || COALESCE(vol.last_name, '')),
               s.site_code,
               w.name,
               lr.name,
               a.start_date,
               a.end_date
        FROM junc_assignments a
        JOIN volunteer vol ON vol.volunteer_id = a.volunteer_id
        JOIN site s ON s.site_id = a.site_id
        LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
        LEFT JOIN lst_role lr ON lr.role_id = a.role_id
        WHERE {where}
        ORDER BY vol.last_name NULLS LAST, vol.first_name, s.site_code
        """,
        params,
    )
    rows = []
    for r in cur.fetchall():
        end = r[6]
        if end is None or end >= today:
            status = "Active"
        else:
            status = "Ended"
        rows.append(
            {
                "volunteer_id": r[0],
                "volunteer_name": (r[1] or f"Volunteer {r[0]}").strip(),
                "site_code": r[2],
                "waterbody_name": r[3],
                "role_name": r[4],
                "start_date": r[5].isoformat() if r[5] else None,
                "end_date": end.isoformat() if end else None,
                "assignment_status": status,
            }
        )
    return rows


def _fmt_result_value(val):
    if val is None:
        return ""
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.4f}".rstrip("0").rstrip(".")


def results_rows(
    cur,
    site_code="",
    date_start=None,
    date_end=None,
    family="both",
    limit=None,
):
    """Flatten chemistry packages + bacteria into value rows. limit=None → all matching."""
    family = (family or "both").strip().lower()
    if family not in ("both", "chemistry", "bacteria"):
        family = "both"
    out = []

    if family in ("both", "chemistry"):
        clauses = ["TRUE"]
        params = []
        if site_code:
            clauses.append("s.site_code = %s")
            params.append(site_code)
        if date_start:
            clauses.append("v.sample_date >= %s")
            params.append(date_start)
        if date_end:
            clauses.append("v.sample_date <= %s")
            params.append(date_end)
        where = " AND ".join(clauses)
        cols = ", ".join(f[0] for f in REPORT_CHEM_FIELDS)
        cur.execute(
            f"""
            SELECT c.chemical_id, v.visit_id, s.site_code, v.sample_date::text, {cols}
            FROM chemical c
            JOIN visit v ON v.visit_id = c.visit_id
            JOIN site s ON s.site_id = v.site_id
            WHERE {where}
            ORDER BY v.sample_date DESC, s.site_code, c.chemical_id
            """,
            params,
        )
        for r in cur.fetchall():
            chemical_id, visit_id, sc, sd = r[0], r[1], r[2], r[3]
            values = r[4:]
            for i, (key, label, unit) in enumerate(REPORT_CHEM_FIELDS):
                val = values[i]
                if val is None:
                    continue
                out.append(
                    {
                        "site_code": sc,
                        "sample_date": sd,
                        "family": "Chemistry",
                        "package_label": f"Chemistry package {chemical_id}",
                        "parameter_key": key,
                        "parameter_label": label,
                        "value_display": _fmt_result_value(val),
                        "value_raw": val,
                        "unit": unit,
                        "visit_id": visit_id,
                        "record_id": chemical_id,
                    }
                )
                if limit is not None and len(out) >= limit:
                    return out

    if family in ("both", "bacteria"):
        clauses = ["TRUE"]
        params = []
        if site_code:
            clauses.append("s.site_code = %s")
            params.append(site_code)
        if date_start:
            clauses.append("v.sample_date >= %s")
            params.append(date_start)
        if date_end:
            clauses.append("v.sample_date <= %s")
            params.append(date_end)
        where = " AND ".join(clauses)
        cur.execute(
            f"""
            SELECT b.bacteria_id, v.visit_id, s.site_code, v.sample_date::text,
                   b.e_coli_mpn_100ml, b.total_coliform_mpn
            FROM bacteria b
            JOIN visit v ON v.visit_id = b.visit_id
            JOIN site s ON s.site_id = v.site_id
            WHERE {where}
            ORDER BY v.sample_date DESC, s.site_code, b.bacteria_id
            """,
            params,
        )
        for r in cur.fetchall():
            bacteria_id, visit_id, sc, sd, ecol, tc = r
            for key, label, unit, val in (
                ("e_coli_mpn_100ml", "E. coli", "MPN/100mL", ecol),
                ("total_coliform_mpn", "Total coliform", "MPN/100mL", tc),
            ):
                if val is None:
                    continue
                out.append(
                    {
                        "site_code": sc,
                        "sample_date": sd,
                        "family": "Bacteria",
                        "package_label": f"Bacteria record {bacteria_id}",
                        "parameter_key": key,
                        "parameter_label": label,
                        "value_display": _fmt_result_value(val),
                        "value_raw": val,
                        "unit": unit,
                        "visit_id": visit_id,
                        "record_id": bacteria_id,
                    }
                )
                if limit is not None and len(out) >= limit:
                    return out
    return out
