#!/usr/bin/env python3
"""
Set macro_analysis ratings (Excellent / Good / Fair / Poor) from the bands in the
StreamWatch Water Quality Assessment Framework 2026, section 11.

  HGMI (genus or family): Excellent 63-100, Good 42-<63, Fair 21-<42, Poor <21
  CPMI (genus):           Excellent 22-30, Good 12-20, Fair 6-10, Poor <6
  NJIS (family):          Excellent 22.5-30, Good 15-<22.5, Fair 7.5-<15, Poor <7.5

hgmi_rating uses the genus score when present, else family (framework priority).
A rating is left blank when the score is outside the index's range, or falls in
a gap the framework does not cover (CPMI 10-12 and 20-22); those are reported.
Ratings are recalculated from the scores every run, so re-running is safe.

These are per-sample ratings. Site/period ratings (minimum samples, lowest
rating across years, regional applicability) are a separate assessment step.

Dry run by default; --apply commits.  Usage: python -m etl.rate_bio_scores [--apply]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FRAMEWORK = "StreamWatch Water Quality Assessment Framework 2026, section 11"


def rate_hgmi(v: Optional[float]) -> Optional[str]:
    if v is None or v < 0 or v > 100:
        return None
    if v >= 63:
        return "Excellent"
    if v >= 42:
        return "Good"
    if v >= 21:
        return "Fair"
    return "Poor"


def rate_cpmi(v: Optional[float]) -> Optional[str]:
    if v is None or v < 0 or v > 30:
        return None
    if v >= 22:
        return "Excellent"
    if 12 <= v <= 20:
        return "Good"
    if 6 <= v <= 10:
        return "Fair"
    if v < 6:
        return "Poor"
    return None  # 10-12 or 20-22: not covered by the framework


def rate_njis(v: Optional[float]) -> Optional[str]:
    if v is None or v < 0 or v > 30:
        return None
    if v >= 22.5:
        return "Excellent"
    if v >= 15:
        return "Good"
    if v >= 7.5:
        return "Fair"
    return "Poor"


def run(apply: bool) -> dict:
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn

    refuse_if_protected_database(DATABASE_URL)
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    stats: Counter = Counter()
    unrated = []
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT m.macro_analysis_id, s.site_code, v.sample_date, m.hgmi_genus, m.hgmi_family,
                      m.cpmi_score, m.njis_score, m.hgmi_rating, m.cpmi_rating, m.njis_rating
               FROM macro_analysis m JOIN visit v USING (visit_id) JOIN site s USING (site_id)"""
        )
        for mid, code, d, hg, hf, cp, nj, old_h, old_c, old_n in cur.fetchall():
            f = lambda x: float(x) if x is not None else None
            hgmi_source = hg if hg is not None else hf
            new = (rate_hgmi(f(hgmi_source)), rate_cpmi(f(cp)), rate_njis(f(nj)))
            for name, score, rating in (("HGMI", hgmi_source, new[0]), ("CPMI", cp, new[1]), ("NJIS", nj, new[2])):
                if score is not None:
                    stats[f"{name} {rating or 'unrated'}"] += 1
                    if rating is None:
                        unrated.append(f"{code} {d} {name}={score}")
            if new != (old_h, old_c, old_n):
                cur.execute(
                    "UPDATE macro_analysis SET hgmi_rating = %s, cpmi_rating = %s, njis_rating = %s WHERE macro_analysis_id = %s",
                    (*new, mid),
                )
                stats["rows updated"] += 1
        print(f"  bands: {FRAMEWORK}")
        print("  " + "\n  ".join(f"{k}: {v}" for k, v in sorted(stats.items())))
        print("  unrated (out of range or in a framework gap):", "; ".join(unrated) or "none")
        if not apply:
            conn.rollback()
            print("\nDRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("\nAPPLIED.")
    return {"stats": dict(stats), "unrated": unrated}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true")
    run(apply=p.parse_args(argv).apply)


if __name__ == "__main__":
    main()
