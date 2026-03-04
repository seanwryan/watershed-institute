#!/usr/bin/env python3
"""
Migrate CAT Meter Tracking v.1.xlsx into equipment, sensor, session, meter_maintenance, meter_testing.
Sheets: Assignments (inventory), Sensors (replacement log), Tracking (failure/quarterly), 2024/2025/2026 Testing.
Expects: STREAMWATCH_DATA_DIR or EQUIPMENT_FILE.
"""
import pandas as pd
from pathlib import Path
import sys
import re

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.config import EQUIPMENT_FILE
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


def run():
    if not EQUIPMENT_FILE.exists():
        print(f"Equipment file not found: {EQUIPMENT_FILE}. Set STREAMWATCH_DATA_DIR or EQUIPMENT_FILE.")
        sys.exit(1)

    xl = pd.ExcelFile(EQUIPMENT_FILE)
    assignments_df = pd.read_excel(EQUIPMENT_FILE, sheet_name="Assignments") if "Assignments" in xl.sheet_names else pd.DataFrame()
    sensors_df = pd.read_excel(EQUIPMENT_FILE, sheet_name="Sensors") if "Sensors" in xl.sheet_names else pd.DataFrame()
    tracking_df = pd.read_excel(EQUIPMENT_FILE, sheet_name="Tracking") if "Tracking" in xl.sheet_names else pd.DataFrame()

    with get_conn() as conn:
        cur = conn.cursor()
        session_type_id = ensure_lookup(conn, "lst_session_type", "session_type_id", "name", "Quarterly maintenance")

        equipment_code_to_id = {}

        for _, row in assignments_df.iterrows():
            meter_id = _str(row.get("Meter ID") or row.get("MeterID") or row.get("MeterId"))
            if not meter_id:
                continue
            sn = _str(row.get("Serial number") or row.get("SN") or row.get("Serial Number"))
            status = "Active"
            if _str(row.get("Retired")) or str(row.get("Inactive", "")).strip().lower() in ("1", "true", "yes", "x"):
                status = "Retired"
            cur.execute("""
                INSERT INTO equipment (equipment_code, equipment_type, serial_number, status)
                VALUES (%s, 'Multiparameter meter', %s, %s::equipment_status_enum)
                ON CONFLICT (equipment_code) DO UPDATE SET serial_number = EXCLUDED.serial_number, status = EXCLUDED.status, updated_at = NOW()
                RETURNING equipment_id
                """, (meter_id, sn, status))
            eq_id = cur.fetchone()[0]
            equipment_code_to_id[meter_id] = eq_id

        for _, row in sensors_df.iterrows():
            meter_id = _str(row.get("Meter ID") or row.get("MeterID"))
            if not meter_id or meter_id not in equipment_code_to_id:
                continue
            eq_id = equipment_code_to_id[meter_id]
            for param, sensor_type in (("DO", "DO"), ("pH", "pH"), ("EC", "EC")):
                col = _str(row.get(f"Date last changed {param}") or row.get(f"{param}") or row.get("DO sensor") or row.get("pH sensor") or row.get("EC sensor"))
                date_installed = _date(col) if col else None
                if date_installed or param in str(row.keys()):
                    cur.execute("""
                        INSERT INTO sensor (equipment_id, sensor_type, date_installed) VALUES (%s, %s::sensor_type_enum, %s)
                        """, (eq_id, param, date_installed))

        for year in ("2024", "2025", "2026"):
            if year not in xl.sheet_names:
                continue
            test_df = pd.read_excel(EQUIPMENT_FILE, sheet_name=year)
            # Create a session for this year's testing
            cur.execute("""
                INSERT INTO session (session_type_id, date_start, date_end, summary) VALUES (%s, %s, %s, %s) RETURNING session_id
                """, (session_type_id, f"{year}-01-01", f"{year}-12-31", f"CAT meter testing {year}"))
            session_id = cur.fetchone()[0]
            # Try to parse test rows: columns may be Meter ID, Parameter, Round, Reference, Measured, Pass/Fail, etc.
            for _, row in test_df.iterrows():
                meter_id = _str(row.get("Meter ID") or row.get("MeterID") or row.get("Meter Id"))
                if not meter_id or meter_id not in equipment_code_to_id:
                    continue
                eq_id = equipment_code_to_id[meter_id]
                param = _str(row.get("Parameter") or row.get("Parameter Type") or row.get("ParameterType"))
                if not param:
                    continue
                ref = _float(row.get("Reference value") or row.get("Reference Value") or row.get("ReferenceValue"))
                meas = _float(row.get("Measured value") or row.get("Measured Value") or row.get("MeasuredValue"))
                pf = _str(row.get("Pass/Fail") or row.get("Pass Fail") or row.get("PassFail"))
                cur.execute("""
                    INSERT INTO meter_testing (session_id, equipment_id, parameter_type, reference_value, measured_value, pass_fail)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """, (session_id, eq_id, param, ref, meas, pf))

    print("Equipment migration done.")


if __name__ == "__main__":
    run()
