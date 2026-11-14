#!/usr/bin/env python3
"""
One-time repair: link historical BAT biological results to BAT visits.

Problem (found 2026-11-14 on the live Neon branch):
  migrate_bat.py created a visit for every BAT sample with method_id = NULL and
  only reused an existing visit when sample_code matched exactly. So:
    - 108 visits holding macro_analysis / bug_count / rbp100_bug rows have no
      method and are not recognised as BAT.
    - When the All-Data workbook had already created a BAT visit for the same
      site + date (with chemistry, but no sample_code), a second visit was made
      instead of reusing it (e.g. SB1 2021-10-02).

What this does, per "bio visit" (method_id IS NULL and has biological rows):
  - MERGE when exactly one BAT visit exists at the same site + date that has no
    sample_code and no biological rows: move every child row to that visit,
    copy the sample_code over, then delete the now-empty bio visit.
  - Otherwise TAG: set the bio visit's method_id to BAT.
Visits with no method and no biological rows (e.g. lone chemistry rows) are
reported but left alone.

Safety:
  - Dry run by default: everything runs inside one transaction that is rolled
    back. Pass --apply to commit.
  - A visit is only deleted after confirming it has zero rows left in every
    table with a foreign key to visit (all are ON DELETE CASCADE).
  - Refuses protected database names (etl.config.refuse_if_protected_database).
  - Re-running after --apply finds nothing to do.

Usage:
  python -m etl.fix_bat_visit_links            # dry run
  python -m etl.fix_bat_visit_links --apply    # commit
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BIO_TABLES = ("macro_analysis", "bug_count", "rbp100_bug", "habitat_assessment")


@dataclass(frozen=True)
class BioVisit:
    visit_id: int
    site_id: int
    sample_date: date
    sample_code: Optional[str]


@dataclass(frozen=True)
class Action:
    kind: str  # "merge" or "tag"
    bio_visit_id: int
    target_visit_id: Optional[int] = None
    sample_code: Optional[str] = None


def plan_actions(
    bio_visits: List[BioVisit],
    bat_candidates: Dict[Tuple[int, date], List[int]],
) -> List[Action]:
    """Decide merge vs tag for each bio visit.

    bat_candidates maps (site_id, sample_date) -> BAT visit ids at that site/date
    that have no sample_code and no biological rows.
    A candidate is merged into at most once, and only when it is the sole
    candidate and only one bio visit points at that site/date.
    """
    bio_per_key: Dict[Tuple[int, date], int] = {}
    for bv in bio_visits:
        key = (bv.site_id, bv.sample_date)
        bio_per_key[key] = bio_per_key.get(key, 0) + 1

    actions: List[Action] = []
    for bv in sorted(bio_visits, key=lambda b: b.visit_id):
        key = (bv.site_id, bv.sample_date)
        cands = bat_candidates.get(key, [])
        if len(cands) == 1 and bio_per_key[key] == 1:
            actions.append(Action("merge", bv.visit_id, cands[0], bv.sample_code))
        else:
            actions.append(Action("tag", bv.visit_id))
    return actions


def _bio_exists_sql(alias: str) -> str:
    return " OR ".join(
        f"EXISTS (SELECT 1 FROM {t} x WHERE x.visit_id = {alias}.visit_id)" for t in BIO_TABLES
    )


def visit_child_tables(cur) -> List[str]:
    cur.execute(
        """
        SELECT c.conrelid::regclass::text
        FROM pg_constraint c
        WHERE c.contype = 'f' AND c.confrelid = 'visit'::regclass
        ORDER BY 1
        """
    )
    return [r[0] for r in cur.fetchall()]


def counts(cur, bat_id: int) -> dict:
    cur.execute(
        f"""
        SELECT
          (SELECT count(*) FROM visit) AS visits,
          (SELECT count(*) FROM visit v WHERE v.method_id IS NULL AND ({_bio_exists_sql('v')})) AS untagged_bio_visits,
          (SELECT count(*) FROM visit v WHERE v.method_id = %s) AS bat_visits,
          (SELECT count(*) FROM visit v WHERE v.method_id = %s AND EXISTS
              (SELECT 1 FROM macro_analysis m WHERE m.visit_id = v.visit_id)) AS bat_visits_with_macro,
          (SELECT count(*) FROM macro_analysis) AS macro_rows,
          (SELECT count(*) FROM bug_count) AS bug_count_rows,
          (SELECT count(*) FROM rbp100_bug) AS rbp100_rows,
          (SELECT count(*) FROM chemical) AS chemical_rows
        """,
        (bat_id, bat_id),
    )
    names = [d[0] for d in cur.description]
    return dict(zip(names, cur.fetchone()))


def run(apply: bool) -> dict:
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn

    refuse_if_protected_database(DATABASE_URL)
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT method_id FROM lst_method WHERE name = 'BAT'")
        row = cur.fetchone()
        if not row:
            sys.exit("lst_method has no 'BAT' row; aborting.")
        bat_id = row[0]

        before = counts(cur, bat_id)
        child_tables = visit_child_tables(cur)

        cur.execute(
            f"""
            SELECT v.visit_id, v.site_id, v.sample_date, v.sample_code
            FROM visit v
            WHERE v.method_id IS NULL AND ({_bio_exists_sql('v')})
            """
        )
        bio_visits = [BioVisit(*r) for r in cur.fetchall()]

        cur.execute(
            f"""
            SELECT v.site_id, v.sample_date, v.visit_id
            FROM visit v
            WHERE v.method_id = %s
              AND v.sample_code IS NULL
              AND NOT ({_bio_exists_sql('v')})
            """,
            (bat_id,),
        )
        bat_candidates: Dict[Tuple[int, date], List[int]] = {}
        for site_id, sample_date, visit_id in cur.fetchall():
            bat_candidates.setdefault((site_id, sample_date), []).append(visit_id)

        actions = plan_actions(bio_visits, bat_candidates)

        merged = tagged = 0
        for a in actions:
            if a.kind == "tag":
                cur.execute(
                    "UPDATE visit SET method_id = %s, updated_at = CURRENT_TIMESTAMP "
                    "WHERE visit_id = %s AND method_id IS NULL",
                    (bat_id, a.bio_visit_id),
                )
                tagged += cur.rowcount
                continue

            for t in child_tables:
                cur.execute(
                    f"UPDATE {t} SET visit_id = %s WHERE visit_id = %s",
                    (a.target_visit_id, a.bio_visit_id),
                )
            leftovers = 0
            for t in child_tables:
                cur.execute(f"SELECT count(*) FROM {t} WHERE visit_id = %s", (a.bio_visit_id,))
                leftovers += cur.fetchone()[0]
            if leftovers:
                raise RuntimeError(
                    f"visit {a.bio_visit_id} still has {leftovers} child rows after merge; aborting"
                )
            cur.execute("DELETE FROM visit WHERE visit_id = %s", (a.bio_visit_id,))
            cur.execute(
                "UPDATE visit SET sample_code = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE visit_id = %s AND sample_code IS NULL",
                (a.sample_code, a.target_visit_id),
            )
            merged += 1
            print(f"  merge: visit {a.bio_visit_id} ({a.sample_code}) -> BAT visit {a.target_visit_id}")

        cur.execute(
            f"""
            SELECT v.visit_id, s.site_code, v.sample_date
            FROM visit v JOIN site s USING (site_id)
            WHERE v.method_id IS NULL AND NOT ({_bio_exists_sql('v')})
            ORDER BY v.visit_id
            """
        )
        untouched = cur.fetchall()

        after = counts(cur, bat_id)

        # Invariants: no result rows lost.
        for k in ("macro_rows", "bug_count_rows", "rbp100_rows", "chemical_rows"):
            if before[k] != after[k]:
                raise RuntimeError(f"{k} changed {before[k]} -> {after[k]}; aborting")
        if after["untagged_bio_visits"] != 0:
            raise RuntimeError(f"{after['untagged_bio_visits']} bio visits still untagged; aborting")

        print(f"\n  tagged as BAT: {tagged}   merged into existing BAT visits: {merged}")
        print("  before:", before)
        print("  after: ", after)
        if untouched:
            print("  left alone (no method, no biological rows):",
                  ", ".join(f"{vid} {code} {d}" for vid, code, d in untouched))

        if not apply:
            conn.rollback()
            print("\nDRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("\nAPPLIED.")
        return {"tagged": tagged, "merged": merged, "before": before, "after": after}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="commit changes (default is dry run)")
    args = p.parse_args(argv)
    run(apply=args.apply)


if __name__ == "__main__":
    main()
