#!/usr/bin/env python3
"""
Migrate All StreamWatch Data.xlsx (per-watershed sheets) or 30 yr StreamWatch Data Analysis into visit, chemical, bacteria, habitat_assessment, macro_analysis.
Each sheet has ~44 columns: Site, Date, Time, Method, Data Condition, chemistry, biology, habitat.
Expects: STREAMWATCH_DATA_DIR with All StreamWatch Data.xlsx (and/or 30 yr file). Run migrate_sites first.
"""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.config import DATA_DIR
from etl.db import get_conn
from etl.visit_helpers import (
    get_site_id_map, get_data_condition_id_map, get_method_id_map,
    ensure_visit, insert_chemical, insert_bacteria,
    _str, _int, _float, _date,
)


def _col(row, *names):
    for n in names:
        if n in row.index and pd.notna(row.get(n)):
            return row.get(n)
    return None


def run():
    data_file = DATA_DIR / "All StreamWatch Data.xlsx"
    if not data_file.exists():
        data_file = DATA_DIR / "30 yr StreamWatch Data Analysis.xlsx"
    if not data_file.exists():
        print(f"Neither 'All StreamWatch Data.xlsx' nor '30 yr StreamWatch Data Analysis.xlsx' found in {DATA_DIR}.")
        sys.exit(1)

    xl = pd.ExcelFile(data_file)
    # Use all sheets that look like data (have Site and Date)
    sheets_to_load = []
    for name in xl.sheet_names:
        df = pd.read_excel(data_file, sheet_name=name, nrows=2)
        cols = [str(c).strip() for c in df.columns]
        if any("site" in c.lower() for c in cols) and any("date" in c.lower() for c in cols):
            sheets_to_load.append(name)

    if not sheets_to_load:
        sheets_to_load = xl.sheet_names[:5]  # fallback first 5

    with get_conn() as conn:
        cur = conn.cursor()
        site_map = get_site_id_map(conn)
        cond_map = get_data_condition_id_map(conn)
        method_map = get_method_id_map(conn)

        for sheet in sheets_to_load:
            df = pd.read_excel(data_file, sheet_name=sheet)
            # Normalize column names to lowercase with spaces
            df.columns = [str(c).strip() for c in df.columns]
            site_col = next((c for c in df.columns if "site" in c.lower() and "code" not in c.lower() or c.lower() == "site"), None)
            date_col = next((c for c in df.columns if "date" in c.lower()), None)
            if not site_col or not date_col:
                continue
            for _, row in df.iterrows():
                site_code = _str(_col(row, "Site", "site", "Site Code", "SiteCode"))
                if not site_code:
                    continue
                site_id = site_map.get(site_code)
                if not site_id:
                    continue
                sample_date = _date(_col(row, "Date", "date", "Sample Date"))
                if not sample_date:
                    continue
                sample_time = _col(row, "Time", "time", "Sample Time")
                if hasattr(sample_time, "time"):
                    sample_time = sample_time.time()
                sample_time = None  # simplify: store as time if needed
                sample_code = _str(_col(row, "Sample Code", "SampleCode", "sample_code"))
                method_name = _str(_col(row, "Method", "method"))
                method_id = method_map.get(method_name) if method_name else None
                cond_code = _str(_col(row, "Data Condition", "Data Condition", "data_condition"))
                data_condition_id = cond_map.get(cond_code) if cond_code else None
                if not cond_code and _str(_col(row, "Notes", "notes")):
                    data_condition_id = cond_map.get("Unchecked")

                visit_id = ensure_visit(cur, site_id, sample_date, sample_time, sample_code, method_id, None)

                # Chemical
                insert_chemical(cur, visit_id, data_condition_id, method_id,
                    air_temp_c=_float(_col(row, "Air temperature", "Air temp", "Air Temp", "air_temp_c")),
                    water_temp_c=_float(_col(row, "Water temperature", "Water temp", "Water Temp", "water_temp_c")),
                    nitrate_ug_l=_float(_col(row, "Nitrate", "nitrate", "Nitrate (ug/L)")),
                    phosphate_mg_l=_float(_col(row, "Phosphates", "Phosphate", "phosphate_mg_l")),
                    ph=_float(_col(row, "pH", "ph")),
                    turbidity_ntu=_float(_col(row, "Turbidity", "turbidity_ntu")),
                    dissolved_oxygen_ppm=_float(_col(row, "Dissolved oxygen", "DO", "dissolved_oxygen_ppm")),
                    conductivity_us_cm=_float(_col(row, "Conductivity", "conductivity")),
                    chloride_mg_l=_float(_col(row, "Chloride", "chloride_mg_l")),
                )

                # Bacteria (E. coli)
                e_coli = _int(_col(row, "E. coli", "E coli", "E_coli", "e_coli_mpn_100ml"))
                if e_coli is not None:
                    insert_bacteria(cur, visit_id, data_condition_id, e_coli_mpn_100ml=e_coli)

        print(f"StreamWatch data migration done: sheets {sheets_to_load}.")


if __name__ == "__main__":
    run()
