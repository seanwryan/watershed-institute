#!/usr/bin/env python3
"""
Restore Data Conditions that the old apply_qa_rules.py overwrote with "Flagged".

That script set data_condition_id = Flagged on every result it flagged as an
exceedance (18 results over 31 C). For each chemistry row that has an
Exceedance flag and the Flagged condition, find the All StreamWatch Data row
(same site, date, method, matching values) and put its Data Condition back:
a single code into data_condition_id, or a combined one ("Outlier;
Incomplete") into source_data_condition. The Exceedance flag itself is kept.
Rows whose workbook condition really is "Flagged" are left alone.

Dry run by default; --apply commits.  Usage:
  python -m etl.restore_qa_overwritten_conditions [--file PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.backfill_source_conditions import CHEM_FIELDS, is_compound, normalize_condition, same_values
from etl.fill_master_gaps import DEFAULT_FILE, SITE_ALIASES


def run(path: Path, apply: bool) -> dict:
    from etl.all_data_workbook import classify_data_condition, col, mapped_chem_values, read_all_data_sheet
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn
    from etl.visit_helpers import _date, _str, get_data_condition_id_map

    refuse_if_protected_database(DATABASE_URL)
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    df, _ = read_all_data_sheet(path)
    by_key = {}
    for _, row in df.iterrows():
        code = _str(col(row, "Site"))
        key = (SITE_ALIASES.get(code, code), _date(col(row, "Date")), _str(col(row, "Method")))
        by_key.setdefault(key, []).append(row)

    restored, unchanged, unmatched = [], [], []
    with get_conn() as conn:
        cur = conn.cursor()
        cond_map = get_data_condition_id_map(conn)
        cur.execute(
            f"""SELECT c.chemical_id, s.site_code, v.sample_date, m.name, {', '.join('c.' + f for f in CHEM_FIELDS)}
                FROM chemical c
                JOIN visit v USING (visit_id) JOIN site s USING (site_id)
                LEFT JOIN lst_method m ON m.method_id = c.method_id
                JOIN data_condition dc ON dc.data_condition_id = c.data_condition_id AND dc.code = 'Flagged'
                WHERE EXISTS (SELECT 1 FROM result_flag rf JOIN flag_type ft USING (flag_type_id)
                              WHERE rf.result_table = 'chemical' AND rf.result_pk = c.chemical_id
                                AND ft.code = 'Exceedance')"""
        )
        for chem_id, site, d, method, *vals in cur.fetchall():
            stored = dict(zip(CHEM_FIELDS, vals))
            cands = [r for r in by_key.get((site, d, method), []) if same_values(stored, mapped_chem_values(r))]
            if len(cands) != 1:
                unmatched.append(f"{site} {d} {method}: {len(cands)} workbook matches")
                continue
            raw = _str(col(cands[0], "Data Condition"))
            if raw and raw.strip() == "Flagged":
                unchanged.append(f"{site} {d}")
                continue
            if raw and is_compound(raw):
                text = normalize_condition(raw)
                cur.execute("UPDATE chemical SET data_condition_id = NULL, source_data_condition = %s WHERE chemical_id = %s",
                            (text, chem_id))
            else:
                dc_id = classify_data_condition(raw, cond_map, [])["data_condition_id"] if raw else None
                text = raw or "(blank)"
                cur.execute("UPDATE chemical SET data_condition_id = %s, source_data_condition = NULL WHERE chemical_id = %s",
                            (dc_id, chem_id))
            restored.append(f"{site} {d} {method}: Flagged -> {text}")

        print(f"  restored {len(restored)}:")
        for line in restored:
            print("    " + line)
        if unchanged:
            print("  workbook also says Flagged (left alone):", "; ".join(unchanged))
        if unmatched:
            print("  not matched (left alone):", "; ".join(unmatched))
        if not apply:
            conn.rollback()
            print("\nDRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("\nAPPLIED.")
    return {"restored": restored, "unchanged": unchanged, "unmatched": unmatched}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)
    run(args.file, apply=args.apply)


if __name__ == "__main__":
    main()
