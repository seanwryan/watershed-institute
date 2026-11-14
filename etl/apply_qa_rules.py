#!/usr/bin/env python3
"""
Apply automated QA checks by ADDING result_flag rows. Never changes a result's
Data Condition: that is Watershed's own review status from the source workbook.

Checks:
  - Exceedance: water temperature > 31 C, or nitrate > 10 mg/L (the 10 ppm
    drinking-water standard; nitrate is stored in mg/L as N in the
    historically named nitrate_ug_l column)
  - Meter_Failed_Test: the visit's meter failed a test within 30 days after
    (or 7 days before) the sample

Safe to re-run: a flag is only added if the same flag type isn't already on
that result. Dry run by default; --apply commits.

History: until 2026-11-14 this script also overwrote data_condition_id with
"Flagged" (and, through an operator-precedence bug, did so for every result
over 31 C), and compared nitrate to 10000 as if it were stored in µg/L, so the
nitrate check never fired. etl/restore_qa_overwritten_conditions.py put the 18
affected conditions back.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WATER_TEMP_MAX_C = 31
NITRATE_MAX_MG_L = 10

EXCEEDANCE_SQL = """
    INSERT INTO result_flag (result_table, result_pk, flag_type_id, notes)
    SELECT 'chemical', c.chemical_id, %(ft)s,
           CASE WHEN c.water_temp_c > %(temp)s AND c.nitrate_ug_l > %(nitrate)s
                     THEN 'Water temperature > 31 C and nitrate > 10 mg/L'
                WHEN c.water_temp_c > %(temp)s THEN 'Water temperature > 31 C'
                ELSE 'Nitrate > 10 mg/L (10 ppm)' END
    FROM chemical c
    WHERE ((c.water_temp_c IS NOT NULL AND c.water_temp_c > %(temp)s)
           OR (c.nitrate_ug_l IS NOT NULL AND c.nitrate_ug_l > %(nitrate)s))
      AND NOT EXISTS (SELECT 1 FROM result_flag rf
                      WHERE rf.result_table = 'chemical' AND rf.result_pk = c.chemical_id
                        AND rf.flag_type_id = %(ft)s)
"""

METER_FAIL_SQL = """
    INSERT INTO result_flag (result_table, result_pk, flag_type_id, notes)
    SELECT DISTINCT 'chemical', c.chemical_id, %(ft)s, 'Meter failed test within 30 days of sample'
    FROM chemical c
    JOIN visit v ON v.visit_id = c.visit_id
    JOIN meter_testing mt ON mt.equipment_id = v.equipment_id
                          AND mt.pass_fail IN ('F', 'F1', 'F2', 'F3', 'Fail', 'C-F')
    JOIN session s ON s.session_id = mt.session_id
    WHERE v.equipment_id IS NOT NULL
      AND s.date_start <= v.sample_date + INTERVAL '30 days'
      AND (s.date_end IS NULL OR s.date_end >= v.sample_date - INTERVAL '7 days')
      AND NOT EXISTS (SELECT 1 FROM result_flag rf
                      WHERE rf.result_table = 'chemical' AND rf.result_pk = c.chemical_id
                        AND rf.flag_type_id = %(ft)s)
"""


def run(apply: bool = False) -> dict:
    from etl.config import DATABASE_URL, database_name_from_url
    from etl.db import get_conn

    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    added = {}
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT code, flag_type_id FROM flag_type WHERE code IN ('Exceedance', 'Meter_Failed_Test')")
        flag_types = dict(cur.fetchall())
        cur.execute("SELECT count(*), count(DISTINCT data_condition_id) FROM chemical")
        before_conditions = cur.fetchone()
        cur.execute("SELECT md5(string_agg(chemical_id || ':' || coalesce(data_condition_id, 0), ',' ORDER BY chemical_id)) FROM chemical")
        before_hash = cur.fetchone()[0]

        if "Exceedance" in flag_types:
            cur.execute(EXCEEDANCE_SQL, {"ft": flag_types["Exceedance"], "temp": WATER_TEMP_MAX_C, "nitrate": NITRATE_MAX_MG_L})
            added["Exceedance"] = cur.rowcount
        if "Meter_Failed_Test" in flag_types:
            cur.execute(METER_FAIL_SQL, {"ft": flag_types["Meter_Failed_Test"]})
            added["Meter_Failed_Test"] = cur.rowcount

        cur.execute("SELECT md5(string_agg(chemical_id || ':' || coalesce(data_condition_id, 0), ',' ORDER BY chemical_id)) FROM chemical")
        if cur.fetchone()[0] != before_hash:
            raise RuntimeError("Data Conditions changed; this script must only add flags")

        print("  flags added:", added)
        if not apply:
            conn.rollback()
            print("DRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("APPLIED.")
    return added


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true")
    run(apply=p.parse_args(argv).apply)


if __name__ == "__main__":
    main()
