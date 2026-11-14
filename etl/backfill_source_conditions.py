#!/usr/bin/env python3
"""
Backfill source_data_condition for results whose workbook Data Condition is a
combination such as "Outlier; Incomplete" (no single data_condition code).

Each such ALL DATA row is matched to the stored result it produced:
  chemistry  same site / date / method visit, same measured values
  E. coli    same site / date BACT visit, same E. coli result
  bug scores same site / date BAT visit
  habitat    same site / date BAT visit
Only results with no condition yet (data_condition_id and source text empty)
are filled, each at most once. Unmatched rows are reported.
Requires db/13_source_data_condition.sql.

Dry run by default; --apply commits.  Usage:
  python -m etl.backfill_source_conditions [--file PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.fill_master_gaps import DEFAULT_FILE, SITE_ALIASES, bio_values, habitat_values

CHEM_FIELDS = ("air_temp_c", "water_temp_c", "nitrate_ug_l", "nitrate_dilution_adj", "phosphate_mg_l", "ph",
               "turbidity_ntu", "dissolved_oxygen_ppm", "dissolved_oxygen_pct", "conductivity_us_cm", "chloride_mg_l")


def is_compound(text: Optional[str]) -> bool:
    return bool(text) and (";" in text or "," in text)


def normalize_condition(text: str) -> str:
    """'Outlier;Incomplete ' -> 'Outlier; Incomplete' (keeps the workbook's order and words)."""
    parts = [p.strip() for p in text.replace(",", ";").split(";")]
    return "; ".join(p for p in parts if p)


def same_values(stored: Dict[str, Optional[float]], source: Dict[str, Optional[float]]) -> bool:
    for f in CHEM_FIELDS:
        a, b = stored.get(f), source.get(f)
        if a is None and b is None:
            continue
        # Columns are NUMERIC with up to 4 decimals (temperatures 2), so compare at
        # stored precision; temperatures like 12.002 are stored as 12.00.
        tol = 0.006 if f in ("air_temp_c", "water_temp_c") else 0.0005
        if a is None or b is None or abs(float(a) - float(b)) > tol:
            return False
    return True


def run(path: Path, apply: bool) -> dict:
    from etl.all_data_workbook import col, mapped_chem_values, parse_e_coli_result, read_all_data_sheet
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn
    from etl.visit_helpers import _date, _str

    refuse_if_protected_database(DATABASE_URL)
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    df, _ = read_all_data_sheet(path)
    stats: Counter = Counter()
    unmatched = Counter()
    examples = []

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT site_code, site_id FROM site")
        sites = dict(cur.fetchall())
        cur.execute("SELECT name, method_id FROM lst_method")
        methods = dict(cur.fetchall())
        cur.execute("SELECT site_id, sample_date, method_id, visit_id FROM visit")
        visits = {(s, d, m): v for s, d, m, v in cur.fetchall()}

        open_chem = defaultdict(list)
        cur.execute(f"""SELECT visit_id, chemical_id, {', '.join(CHEM_FIELDS)} FROM chemical
                        WHERE data_condition_id IS NULL AND source_data_condition IS NULL""")
        for r in cur.fetchall():
            open_chem[r[0]].append((r[1], dict(zip(CHEM_FIELDS, r[2:]))))
        open_bact = defaultdict(list)
        cur.execute("""SELECT visit_id, bacteria_id, e_coli_mpn_100ml FROM bacteria
                       WHERE data_condition_id IS NULL AND source_data_condition IS NULL""")
        for v, bid, ec in cur.fetchall():
            open_bact[v].append((bid, ec))
        cur.execute("SELECT visit_id, macro_analysis_id FROM macro_analysis WHERE data_condition_id IS NULL AND source_data_condition IS NULL")
        open_macro = dict(cur.fetchall())
        cur.execute("SELECT visit_id, habitat_id FROM habitat_assessment WHERE data_condition_id IS NULL AND source_data_condition IS NULL")
        open_hab = dict(cur.fetchall())

        def setcond(table, pk_col, pk, text):
            cur.execute(f"UPDATE {table} SET source_data_condition = %s WHERE {pk_col} = %s", (text, pk))
            stats[f"{table} filled"] += 1

        for _, row in df.iterrows():
            raw = _str(col(row, "Data Condition"))
            if not is_compound(raw):
                continue
            text = normalize_condition(raw)
            stats["compound rows in workbook"] += 1
            code = _str(col(row, "Site"))
            sid = sites.get(SITE_ALIASES.get(code, code))
            d = _date(col(row, "Date"))
            mid = methods.get(_str(col(row, "Method")) or "")
            if sid is None or d is None:
                unmatched["no site/date"] += 1
                continue
            matched_any = False

            chem = mapped_chem_values(row)
            if any(v is not None for v in chem.values()):
                vid = visits.get((sid, d, mid))
                cands = [c for c in open_chem.get(vid, []) if same_values(c[1], chem)]
                if cands:
                    chem_id = cands[0][0]
                    open_chem[vid] = [c for c in open_chem[vid] if c[0] != chem_id]
                    setcond("chemical", "chemical_id", chem_id, text)
                    matched_any = True
                else:
                    unmatched["chemistry not found"] += 1
                    if len(examples) < 12:
                        examples.append(f"{code} {d} {_str(col(row, 'Method'))} [{text}] visit={vid} open={len(open_chem.get(vid, []))}")

            e_coli, _mod, _skip = parse_e_coli_result(row)
            if e_coli is not None:
                vid = visits.get((sid, d, methods["BACT"]))
                cands = [b for b in open_bact.get(vid, []) if b[1] == e_coli]
                if cands:
                    open_bact[vid].remove(cands[0])
                    setcond("bacteria", "bacteria_id", cands[0][0], text)
                    matched_any = True
                else:
                    unmatched["E. coli not found"] += 1

            if bio_values(row) or habitat_values(row):
                vid = visits.get((sid, d, methods["BAT"]))
                if bio_values(row) and vid in open_macro:
                    setcond("macro_analysis", "macro_analysis_id", open_macro.pop(vid), text)
                    matched_any = True
                if habitat_values(row) and vid in open_hab:
                    setcond("habitat_assessment", "habitat_id", open_hab.pop(vid), text)
                    matched_any = True

            if not matched_any:
                unmatched["row with nothing matched (often no values)"] += 1

        cur.execute("""SELECT (SELECT count(*) FROM chemical WHERE data_condition_id IS NULL AND source_data_condition IS NULL),
                              (SELECT count(*) FROM bacteria WHERE data_condition_id IS NULL AND source_data_condition IS NULL)""")
        still = cur.fetchone()
        print("  " + "\n  ".join(f"{k}: {v}" for k, v in sorted(stats.items())))
        print("  unmatched:", dict(unmatched))
        for e in examples:
            print("    e.g. " + e)
        print(f"  results still without any condition: chemical {still[0]}, bacteria {still[1]}")
        if not apply:
            conn.rollback()
            print("\nDRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("\nAPPLIED.")
    return {"stats": dict(stats), "unmatched": dict(unmatched)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)
    run(args.file, apply=args.apply)


if __name__ == "__main__":
    main()
