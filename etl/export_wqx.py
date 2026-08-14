#!/usr/bin/env python3
"""
Export monitoring data to WQX-style CSV (preparation format, not EPA portal upload).

Emits one result row per non-null characteristic value. Visits may have multiple
legitimate chemistry packages; every package is included (no fetchone / first-only).
"""
import csv
import io
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.db import get_conn

FIELDNAMES = [
    "MonitoringLocationIdentifier",
    "ActivityIdentifier",
    "ActivityStartDate",
    "CharacteristicName",
    "ResultMeasureValue",
    "ResultMeasure/MeasureUnitCode",
]
CHEM_COLUMNS = [
    "water_temp_c",
    "nitrate_ug_l",
    "phosphate_mg_l",
    "ph",
    "turbidity_ntu",
    "dissolved_oxygen_ppm",
    "conductivity_us_cm",
    "chloride_mg_l",
]
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


def _chem_activity_id(base_activity, chemical_id, package_count):
    """Keep historical single-package activity IDs; disambiguate multi-package visits."""
    if package_count <= 1:
        return base_activity
    return f"{base_activity}-C{chemical_id}"


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
        cur.execute(
            """
            SELECT v.visit_id, v.sample_date, v.sample_code, s.site_code
            FROM visit v
            JOIN site s ON s.site_id = v.site_id
            WHERE (%s::date IS NULL OR v.sample_date >= %s)
              AND (%s::date IS NULL OR v.sample_date <= %s)
              AND (%s::text[] IS NULL OR s.site_code = ANY(%s))
            ORDER BY v.sample_date, s.site_code
            """,
            (date_start, date_start, date_end, date_end, site_codes, site_codes),
        )
        visits = cur.fetchall()

    param_map = {k: v for k, v in PARAM_MAP.items() if not parameters or k in parameters}
    rows = []

    with get_conn() as conn:
        cur = conn.cursor()
        for (visit_id, sample_date, sample_code, site_code) in visits:
            base_activity = sample_code or f"{site_code}-{sample_date}"
            cur.execute(
                f"""
                SELECT chemical_id, {", ".join(CHEM_COLUMNS)}
                FROM chemical
                WHERE visit_id = %s
                ORDER BY chemical_id
                """,
                (visit_id,),
            )
            chem_packages = cur.fetchall()
            package_count = len(chem_packages)
            for chem in chem_packages:
                chemical_id = chem[0]
                activity_id = _chem_activity_id(base_activity, chemical_id, package_count)
                for i, col in enumerate(CHEM_COLUMNS):
                    if col not in param_map:
                        continue
                    val = chem[i + 1]
                    if val is None:
                        continue
                    name, unit = param_map[col]
                    rows.append(
                        {
                            "MonitoringLocationIdentifier": site_code,
                            "ActivityIdentifier": activity_id,
                            "ActivityStartDate": str(sample_date),
                            "CharacteristicName": name,
                            "ResultMeasureValue": str(val),
                            "ResultMeasure/MeasureUnitCode": unit,
                        }
                    )

            # Preserve prior bacteria behavior: one E. coli row per bacteria record
            # (demo is typically one per visit; fetchall avoids dropping extras).
            if "e_coli_mpn_100ml" in param_map:
                cur.execute(
                    """
                    SELECT bacteria_id, e_coli_mpn_100ml
                    FROM bacteria
                    WHERE visit_id = %s
                    ORDER BY bacteria_id
                    """,
                    (visit_id,),
                )
                bac_rows = cur.fetchall()
                for bacteria_id, ecol in bac_rows:
                    if ecol is None:
                        continue
                    name, unit = param_map["e_coli_mpn_100ml"]
                    bac_activity = base_activity
                    if len(bac_rows) > 1:
                        bac_activity = f"{base_activity}-B{bacteria_id}"
                    rows.append(
                        {
                            "MonitoringLocationIdentifier": site_code,
                            "ActivityIdentifier": bac_activity,
                            "ActivityStartDate": str(sample_date),
                            "CharacteristicName": name,
                            "ResultMeasureValue": str(ecol),
                            "ResultMeasure/MeasureUnitCode": unit,
                        }
                    )

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
    buf = build_wqx_csv(
        date_start=date_start,
        date_end=date_end,
        site_codes=site_codes,
        parameters=parameters,
    )
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print(f"WQX export written to {out_path}.")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("wqx_export.csv")
    date_start = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None
    date_end = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None
    site_codes = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else None
    export_wqx_csv(out, date_start=date_start, date_end=date_end, site_codes=site_codes)
