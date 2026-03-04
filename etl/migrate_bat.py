#!/usr/bin/env python3
"""
Migrate BAT biological data: tblSampleDates.xlsx (tblSampleDates, tblBugResults, tblRBP100Bugs, BugList) or BATSITES COLLECTED + BUGSPICKED.
Populates visit (from sample events), bug_list, bug_count, rbp100_bug, and optionally macro_analysis.
Run migrate_sites first. BugList sheet/table must exist or be provided.
"""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.config import DATA_DIR
from etl.db import get_conn
from etl.visit_helpers import get_site_id_map, ensure_visit, _str, _int, _float, _date


def run():
    # Prefer tblSampleDates (normalized)
    tbl_file = DATA_DIR / "tblSampleDates.xlsx"
    if not tbl_file.exists():
        tbl_file = DATA_DIR / "BAT Data Consolidation and Recount – Lily Raphael.xlsx"
    batsites_file = DATA_DIR / "BATSITES COLLECTED.xlsx"

    with get_conn() as conn:
        cur = conn.cursor()
        site_map = get_site_id_map(conn)
        # Map station/site code to site_id
        if not site_map:
            cur.execute("SELECT site_id, site_code FROM site")
            site_map = {r[1]: r[0] for r in cur.fetchall()}

        # BugList: ensure we have taxonomy
        if tbl_file.exists():
            xl = pd.ExcelFile(tbl_file)
            if "BugList" in xl.sheet_names:
                bug_df = pd.read_excel(tbl_file, sheet_name="BugList")
                bug_df.columns = [str(c).strip() for c in bug_df.columns]
                bug_id_map = {}
                for _, row in bug_df.iterrows():
                    bug_code = _str(row.get("BugID") or row.get("Bug Id"))
                    if not bug_code:
                        continue
                    cur.execute("""
                        INSERT INTO bug_list (bug_code, order_class, family, genus_species, ept, tolerance_ftv, functional_feeding_group, habit, scraper, clinger)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (bug_code) DO NOTHING
                        """, (
                        bug_code, _str(row.get("Order/Class") or row.get("Order")), _str(row.get("Family")), _str(row.get("GenusSpecies") or row.get("Genus")),
                        bool(row.get("EPT")) if pd.notna(row.get("EPT")) else None, _float(row.get("FTV") or row.get("tolerance_ftv")), _str(row.get("Functional feeding group")), _str(row.get("Habit")),
                        bool(row.get("Scraper")) if pd.notna(row.get("Scraper")) else None, bool(row.get("Clinger")) if pd.notna(row.get("Clinger")) else None,
                    ))
                    cur.execute("SELECT bug_id FROM bug_list WHERE bug_code = %s", (bug_code,))
                    r = cur.fetchone()
                    if r:
                        bug_id_map[bug_code] = r[0]

            # tblSampleDates
            if "tblSampleDates" in xl.sheet_names:
                sample_df = pd.read_excel(tbl_file, sheet_name="tblSampleDates")
                sample_df.columns = [str(c).strip() for c in sample_df.columns]
                visit_id_by_sample_id = {}
                for _, row in sample_df.iterrows():
                    station = _str(row.get("Station") or row.get("Site") or row.get("SiteCode"))
                    sample_date = _date(row.get("SampleDate") or row.get("Sample Date"))
                    sample_code = _str(row.get("SampleCode") or row.get("Sample Code"))
                    if not station or not sample_date:
                        continue
                    site_id = site_map.get(station)
                    if not site_id:
                        continue
                    visit_id = ensure_visit(cur, site_id, sample_date, None, sample_code, None, None)
                    visit_id_by_sample_id[_int(row.get("SampleID"))] = visit_id

                # tblBugResults -> bug_count
                if "tblBugResults" in xl.sheet_names:
                    bug_results = pd.read_excel(tbl_file, sheet_name="tblBugResults")
                    bug_results.columns = [str(c).strip() for c in bug_results.columns]
                    for _, row in bug_results.iterrows():
                        sample_id = _int(row.get("SampleID"))
                        visit_id = visit_id_by_sample_id.get(sample_id)
                        if not visit_id:
                            continue
                        bug_id_key = _int(row.get("BugID")) or _str(row.get("BugID"))
                        cur.execute("SELECT bug_id FROM bug_list WHERE bug_code = %s OR bug_id = %s LIMIT 1", (str(bug_id_key), bug_id_key))
                        b = cur.fetchone()
                        if not b:
                            continue
                        amount = _int(row.get("Amount") or row.get("Number"))
                        if amount is None:
                            continue
                        exclude = bool(row.get("Exclude")) if pd.notna(row.get("Exclude")) else False
                        cur.execute("INSERT INTO bug_count (visit_id, bug_id, amount, exclude) VALUES (%s, %s, %s, %s)", (visit_id, b[0], amount, exclude))

                # tblRBP100Bugs -> rbp100_bug
                if "tblRBP100Bugs" in xl.sheet_names:
                    rbp = pd.read_excel(tbl_file, sheet_name="tblRBP100Bugs")
                    rbp.columns = [str(c).strip() for c in rbp.columns]
                    for _, row in rbp.iterrows():
                        sample_id = _int(row.get("SampleID"))
                        visit_id = visit_id_by_sample_id.get(sample_id)
                        if not visit_id:
                            continue
                        bug_id_key = _int(row.get("BugID")) or _str(row.get("BugID"))
                        cur.execute("SELECT bug_id FROM bug_list WHERE bug_code = %s OR bug_id = %s LIMIT 1", (str(bug_id_key), bug_id_key))
                        b = cur.fetchone()
                        if not b:
                            continue
                        amount = _int(row.get("Amount"))
                        if amount is None:
                            continue
                        cur.execute("INSERT INTO rbp100_bug (visit_id, bug_id, amount) VALUES (%s, %s, %s)", (visit_id, b[0], amount))

    print("BAT migration done.")


if __name__ == "__main__":
    run()
