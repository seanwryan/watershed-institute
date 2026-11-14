#!/usr/bin/env python3
"""
One-off fixes for differences found by the 2026-11 data audit (etl/audit_sources.py).

  CB3 2025-06-29 BACT: the workbook's third row ("Duplicate; Incomplete") has
  no water temperature, but the stored copy had 27.0 (filled in by the 2025
  Survey123 enrichment) and no condition. Restore the workbook's blank value
  and condition. This was the only stored value that differed from the workbook.

Each change only applies if the row still looks exactly as the audit found it.
Dry run by default; --apply commits.  Usage: python -m etl.fix_audit_findings [--apply]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXES = [
    dict(
        name="CB3 2025-06-29 BACT: restore blank water temperature and 'Duplicate; Incomplete'",
        find="""SELECT c.chemical_id FROM chemical c JOIN visit v USING (visit_id) JOIN site s USING (site_id)
                JOIN lst_method m ON m.method_id = v.method_id
                WHERE s.site_code = 'CB3' AND v.sample_date = '2025-06-29' AND m.name = 'BACT'
                  AND c.data_condition_id IS NULL AND c.source_data_condition IS NULL
                  AND c.water_temp_c = 27.0 AND c.chloride_mg_l BETWEEN 68.124 AND 68.125""",
        update="UPDATE chemical SET water_temp_c = NULL, source_data_condition = 'Duplicate; Incomplete' WHERE chemical_id = %s",
    ),
]


def run(apply: bool):
    from etl.config import DATABASE_URL, database_name_from_url
    from etl.db import get_conn

    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    with get_conn() as conn:
        cur = conn.cursor()
        for fix in FIXES:
            cur.execute(fix["find"])
            ids = [r[0] for r in cur.fetchall()]
            if len(ids) != 1:
                print(f"  skip ({len(ids)} matching rows, expected 1): {fix['name']}")
                continue
            cur.execute(fix["update"], (ids[0],))
            print(f"  fixed chemical {ids[0]}: {fix['name']}")
        if not apply:
            conn.rollback()
            print("DRY RUN: rolled back. Re-run with --apply to commit.")
        else:
            print("APPLIED.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true")
    run(p.parse_args().apply)
