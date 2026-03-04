"""Shared helpers for visit and result ETL: resolve site, ensure visit, insert chemical/bacteria."""
import pandas as pd
from etl.db import get_conn, ensure_lookup


def _str(v):
    if v is None or pd.isna(v):
        return None
    return str(v).strip() or None


def _int(v):
    if v is None or pd.isna(v):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v):
    if v is None or pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date(v):
    if v is None or pd.isna(v):
        return None
    if hasattr(v, "date"):
        return v
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def get_site_id_map(conn):
    """Return dict site_code -> site_id."""
    with conn.cursor() as cur:
        cur.execute("SELECT site_id, site_code FROM site")
        return {r[1]: r[0] for r in cur.fetchall()}


def get_data_condition_id_map(conn):
    """Return dict code -> data_condition_id."""
    with conn.cursor() as cur:
        cur.execute("SELECT data_condition_id, code FROM data_condition")
        return {r[1]: r[0] for r in cur.fetchall()}


def get_method_id_map(conn):
    """Return dict method name -> method_id."""
    with conn.cursor() as cur:
        cur.execute("SELECT method_id, name FROM lst_method")
        return {r[1]: r[0] for r in cur.fetchall()}


def ensure_visit(cur, site_id, sample_date, sample_time=None, sample_code=None, method_id=None, equipment_id=None):
    """Insert or get visit; return visit_id."""
    cur.execute(
        "SELECT visit_id FROM visit WHERE site_id = %s AND sample_date = %s AND (sample_code IS NOT DISTINCT FROM %s) LIMIT 1",
        (site_id, sample_date, sample_code),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO visit (site_id, sample_date, sample_time, sample_code, method_id, equipment_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING visit_id",
        (site_id, sample_date, sample_time, sample_code, method_id, equipment_id),
    )
    return cur.fetchone()[0]


def insert_chemical(cur, visit_id, data_condition_id=None, method_id=None, **kwargs):
    """Insert one chemical row. kwargs: air_temp_c, water_temp_c, nitrate_ug_l, phosphate_mg_l, ph, turbidity_ntu, dissolved_oxygen_ppm, conductivity_us_cm, chloride_mg_l."""
    cols = ["visit_id", "data_condition_id", "method_id"]
    vals = [visit_id, data_condition_id, method_id]
    for k in ["air_temp_c", "water_temp_c", "nitrate_ug_l", "nitrate_dilution_adj", "phosphate_mg_l", "ph", "turbidity_ntu", "dissolved_oxygen_ppm", "dissolved_oxygen_pct", "conductivity_us_cm", "chloride_mg_l"]:
        if k in kwargs and kwargs[k] is not None:
            cols.append(k)
            vals.append(kwargs[k])
    if len(cols) <= 3:
        return
    cur.execute("INSERT INTO chemical (" + ", ".join(cols) + ") VALUES (" + ", ".join(["%s"] * len(cols)) + ")", vals)


def insert_bacteria(cur, visit_id, data_condition_id=None, e_coli_mpn_100ml=None, total_coliform_mpn=None, holding_time_flag=None, holding_temp_flag=None):
    """Insert one bacteria row."""
    if e_coli_mpn_100ml is None and total_coliform_mpn is None:
        return
    cur.execute(
        "INSERT INTO bacteria (visit_id, data_condition_id, e_coli_mpn_100ml, total_coliform_mpn, holding_time_flag, holding_temp_flag) VALUES (%s, %s, %s, %s, %s, %s)",
        (visit_id, data_condition_id, _int(e_coli_mpn_100ml), _int(total_coliform_mpn), holding_time_flag, holding_temp_flag),
    )
