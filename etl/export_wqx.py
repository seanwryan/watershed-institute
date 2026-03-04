#!/usr/bin/env python3
"""
Export monitoring data to WQX-compatible format (CSV).
WQX schema: Monitoring Location ID, Activity ID, Activity Type, Characteristic Name, Result Value, Unit, etc.
Output can be used for EPA Water Quality Exchange upload. Filter by date range, site, parameter.
Core logic in build_wqx_csv() for use from CLI or Flask.
"""
import csv
import io
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.db import get_conn

FIELDNAMES = ["MonitoringLocationIdentifier", "ActivityIdentifier", "ActivityStartDate", "CharacteristicName", "ResultMeasureValue", "ResultMeasure/MeasureUnitCode"]
PARAM_MAP = {
    "water_temp_c": ("Temperature, water", "deg C"),
    "nitrate_ug_l": ("Nitrate", "ug/L"),
    "phosphate_mg_l": ("Phosphate", "mg/L"),
    "ph": ("pH", "None"),
    "turbidity_ntu": ("Turbidity", "NTU"),
    "dissolved_oxygen_ppm": ("Dissolved oxygen", "mg/L"),
    "conductivity_us_cm": ("Specific conductance", "uS/cm"),
    "chloride_mg_l": ("Chloride", "mg/L"),
    "e_coli_mpn_100ml": ("Escherichia coli", "MPN/100mL"),
}


def build_wqx_csv(
    date_start: date = None,
    date_end: date = None,
    site_codes: list = None,
    parameters: list = None,
):
    """
    Build WQX-style CSV rows and return a file-like object (StringIO) with CSV content.
    Callable from Flask to stream download without writing to disk.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.visit_id, v.sample_date, v.sample_code, s.site_code
            FROM visit v
            JOIN site s ON s.site_id = v.site_id
            WHERE (%s::date IS NULL OR v.sample_date >= %s)
              AND (%s::date IS NULL OR v.sample_date <= %s)
              AND (%s::text[] IS NULL OR s.site_code = ANY(%s))
            ORDER BY v.sample_date, s.site_code
            """, (date_start, date_start, date_end, date_end, site_codes, site_codes))
        visits = cur.fetchall()

    param_map = {k: v for k, v in PARAM_MAP.items() if not parameters or k in parameters}
    rows = []

    with get_conn() as conn:
        cur = conn.cursor()
        for (visit_id, sample_date, sample_code, site_code) in visits:
            activity_id = sample_code or f"{site_code}-{sample_date}"
            cur.execute(
                "SELECT water_temp_c, nitrate_ug_l, phosphate_mg_l, ph, turbidity_ntu, dissolved_oxygen_ppm, conductivity_us_cm, chloride_mg_l FROM chemical WHERE visit_id = %s",
                (visit_id,),
            )
            chem = cur.fetchone()
            if chem:
                for i, col in enumerate(["water_temp_c", "nitrate_ug_l", "phosphate_mg_l", "ph", "turbidity_ntu", "dissolved_oxygen_ppm", "conductivity_us_cm", "chloride_mg_l"]):
                    if col not in param_map:
                        continue
                    val = chem[i]
                    if val is None:
                        continue
                    name, unit = param_map[col]
                    rows.append({
                        "MonitoringLocationIdentifier": site_code,
                        "ActivityIdentifier": activity_id,
                        "ActivityStartDate": str(sample_date),
                        "CharacteristicName": name,
                        "ResultMeasureValue": str(val),
                        "ResultMeasure/MeasureUnitCode": unit,
                    })
            cur.execute("SELECT e_coli_mpn_100ml FROM bacteria WHERE visit_id = %s", (visit_id,))
            bac = cur.fetchone()
            if bac and bac[0] is not None and "e_coli_mpn_100ml" in param_map:
                name, unit = param_map["e_coli_mpn_100ml"]
                rows.append({
                    "MonitoringLocationIdentifier": site_code,
                    "ActivityIdentifier": activity_id,
                    "ActivityStartDate": str(sample_date),
                    "CharacteristicName": name,
                    "ResultMeasureValue": str(bac[0]),
                    "ResultMeasure/MeasureUnitCode": unit,
                })

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDNAMES)
    w.writeheader()
    w.writerows(rows)
    buf.seek(0)
    return buf


def export_wqx_csv(
    out_path: Path,
    date_start: date = None,
    date_end: date = None,
    site_codes: list = None,
    parameters: list = None,
):
    """Write WQX-style CSV to a file (CLI use)."""
    buf = build_wqx_csv(date_start=date_start, date_end=date_end, site_codes=site_codes, parameters=parameters)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print(f"WQX export written to {out_path}.")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("wqx_export.csv")
    date_start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    date_end = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None
    site_codes = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else None
    export_wqx_csv(out, date_start=date_start, date_end=date_end, site_codes=site_codes)
