#!/usr/bin/env python3
"""
Load BAT habitat (EPA RBP) scores onto existing BAT visits.

Source: "BAT Habitat Data to be entered.xlsx" (Google Form export, sheet
"Form Responses 1"), read with etl.bat_reconcile.read_habitat_workbook.

Only the RBP habitat scores are loaded into habitat_assessment. A row is
loaded when ALL of these hold:
  - the RBP data sheet was completed (row has at least one score),
  - exactly one existing visit matches site + date, and it is a BAT visit,
  - that visit has no habitat_assessment row yet,
  - no other source row targets the same visit,
  - every score is a whole number within its RBP range.
Everything else is reported with a reason and skipped. No visits, sites or
other tables are created or changed. Sampler names, field observations and
comments are not stored here (no columns for them yet).

Dry run by default (transaction rolled back); --apply commits. Re-running after
--apply skips rows already loaded.

Usage:
  python -m etl.load_bat_habitat [--file PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "Watershed Data" / "Data" / "BAT Habitat Data to be entered.xlsx"

# source header -> (habitat_assessment column, max score)
SCORE_COLUMNS: Dict[str, Tuple[str, int]] = {
    "1. Epifaunal Substrate": ("epifaunal_substrate", 20),
    "HIGH GRADIENT ONLY 2. Embeddedness": ("embeddedness", 20),
    "LOW GRADIENT ONLY 2. Pool Substrate Characterization": ("pool_substrate", 20),
    "HIGH GRADIENT ONLY 3. Velocity/Depth Combination": ("velocity_depth", 20),
    "LOW GRADIENT ONLY 3. Pool Variability": ("pool_variability", 20),
    "4. Sediment Deposition": ("sediment_deposition", 20),
    "5. Channel Flow Status": ("channel_flow_status", 20),
    "6. Channel Alteration": ("channel_alteration", 20),
    "HIGH GRADIENT ONLY 7. Frequency of Riffles": ("freq_riffles", 20),
    "LOW GRADIENT ONLY 7. Channel Sinuosity": ("channel_sinuosity", 20),
    "8. Bank Stability - LEFT": ("bank_stability_left", 10),
    "8. Bank Stability - RIGHT": ("bank_stability_right", 10),
    "9. Vegetative Protection - LEFT": ("bank_veg_protection_left", 10),
    "9. Vegetative Protection - RIGHT": ("bank_veg_protection_right", 10),
    "10. Vegetative Zone Width - LEFT": ("riparian_zone_left", 10),
    "10. Vegetative Zone Width - RIGHT": ("riparian_zone_right", 10),
}
DB_COLUMNS = [col for col, _ in SCORE_COLUMNS.values()]


def parse_scores(raw: Dict[str, str]) -> Tuple[Dict[str, Optional[int]], List[str]]:
    """Return ({column: int|None}, [problems]). Blank cells become None."""
    scores: Dict[str, Optional[int]] = {}
    problems: List[str] = []
    for header, (column, max_score) in SCORE_COLUMNS.items():
        text = str(raw.get(header, "") or "").strip()
        if not text:
            scores[column] = None
            continue
        try:
            value = Decimal(text)
        except InvalidOperation:
            problems.append(f"{header}: not a number ({text!r})")
            continue
        if not value.is_finite() or value != value.to_integral_value():
            problems.append(f"{header}: not a whole number ({text!r})")
            continue
        number = int(value)
        if not 0 <= number <= max_score:
            problems.append(f"{header}: {number} outside 0-{max_score}")
            continue
        scores[column] = number
    return scores, problems


def plan_rows(records: List[dict], visit_info: Dict[int, Tuple[bool, bool]]):
    """Decide which source rows load.

    records: habitat rows from read_habitat_workbook, with "visits" filled in
      ([{"visit_id": ...}]) and "site_exists".
    visit_info: visit_id -> (is_bat_visit, already_has_habitat)

    Returns (loads, skips): loads = [(record, visit_id, scores)],
    skips = [(record, reason)].
    """
    loads, skips = [], []
    candidates = []
    for rec in records:
        scores, problems = parse_scores(rec["raw"])
        if problems:
            skips.append((rec, "invalid score: " + "; ".join(problems)))
            continue
        if all(v is None for v in scores.values()):
            skips.append((rec, "no RBP scores"))
            continue
        if not rec.get("site_exists"):
            skips.append((rec, "site not in database"))
            continue
        visits = rec.get("visits") or []
        if not visits:
            skips.append((rec, "no visit on that site/date"))
            continue
        if len(visits) > 1:
            skips.append((rec, f"{len(visits)} visits on that site/date"))
            continue
        visit_id = visits[0]["visit_id"]
        is_bat, has_habitat = visit_info.get(visit_id, (False, False))
        if not is_bat:
            skips.append((rec, f"visit {visit_id} is not a BAT visit"))
            continue
        if has_habitat:
            skips.append((rec, f"visit {visit_id} already has habitat"))
            continue
        candidates.append((rec, visit_id, scores))

    per_visit = Counter(vid for _, vid, _ in candidates)
    for rec, visit_id, scores in candidates:
        if per_visit[visit_id] > 1:
            skips.append((rec, f"{per_visit[visit_id]} source rows for visit {visit_id}"))
        else:
            loads.append((rec, visit_id, scores))
    return loads, skips


def _attach_visits(cur, records: List[dict]) -> None:
    for r in records:  # same derivation as bat_reconcile.preview_bat_files
        r["site_code"] = (r["raw"].get("Site ID") or "").strip() or None
    cur.execute("SELECT site_code FROM site")
    sites = {r[0] for r in cur.fetchall()}
    codes = sorted({r["site_code"] for r in records if r.get("site_code")})
    dates = sorted({str(r["sample_date"]) for r in records if r.get("sample_date")})
    visits = defaultdict(list)
    if codes and dates:
        cur.execute(
            """
            SELECT s.site_code, v.sample_date, v.visit_id
            FROM visit v JOIN site s ON s.site_id = v.site_id
            WHERE s.site_code = ANY(%s) AND v.sample_date = ANY(%s::date[])
            """,
            (codes, dates),
        )
        for code, d, vid in cur.fetchall():
            visits[(code, str(d))].append({"visit_id": vid})
    for r in records:
        r["site_exists"] = r.get("site_code") in sites
        r["visits"] = visits.get((r.get("site_code"), str(r.get("sample_date"))), [])


def run(path: Path, apply: bool) -> dict:
    from etl.bat_reconcile import read_habitat_workbook
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn

    refuse_if_protected_database(DATABASE_URL)
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    print(f"Source: {path.name}")
    records, _blank = read_habitat_workbook(path)

    with get_conn() as conn:
        cur = conn.cursor()
        _attach_visits(cur, records)
        visit_ids = sorted({v["visit_id"] for r in records for v in r["visits"]})
        visit_info: Dict[int, Tuple[bool, bool]] = {}
        if visit_ids:
            cur.execute(
                """
                SELECT v.visit_id,
                       COALESCE(m.name = 'BAT', false),
                       EXISTS (SELECT 1 FROM habitat_assessment h WHERE h.visit_id = v.visit_id)
                FROM visit v LEFT JOIN lst_method m USING (method_id)
                WHERE v.visit_id = ANY(%s)
                """,
                (visit_ids,),
            )
            visit_info = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

        loads, skips = plan_rows(records, visit_info)

        cur.execute("SELECT count(*) FROM habitat_assessment")
        before = cur.fetchone()[0]
        cols = ", ".join(["visit_id"] + DB_COLUMNS)
        marks = ", ".join(["%s"] * (1 + len(DB_COLUMNS)))
        for rec, visit_id, scores in loads:
            cur.execute(
                f"INSERT INTO habitat_assessment ({cols}) VALUES ({marks})",
                [visit_id] + [scores[c] for c in DB_COLUMNS],
            )
        cur.execute("SELECT count(*) FROM habitat_assessment")
        after = cur.fetchone()[0]
        if after - before != len(loads):
            raise RuntimeError(f"expected {len(loads)} inserts, table grew by {after - before}")

        by_year = Counter(str(rec["sample_date"])[:4] for rec, _, _ in loads)
        print(f"\n  source rows: {len(records)}   load: {len(loads)}   skip: {len(skips)}")
        print("  loading by year:", dict(sorted(by_year.items())))
        print("  skipped:")
        for rec, reason in sorted(skips, key=lambda s: str(s[0].get("sample_date"))):
            print(f"    {rec.get('site_code')} {rec.get('sample_date')}  (row {rec.get('source_row')}): {reason}")
        print(f"  habitat_assessment rows: {before} -> {after}")

        if not apply:
            conn.rollback()
            print("\nDRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("\nAPPLIED.")
        return {"loaded": len(loads), "skipped": len(skips), "before": before, "after": after}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--apply", action="store_true", help="commit changes (default is dry run)")
    args = p.parse_args(argv)
    run(args.file, apply=args.apply)


if __name__ == "__main__":
    main()
