#!/usr/bin/env python3
"""
Migrate BAT biological data: tblSampleDates.xlsx (tblSampleDates, tblBugResults, tblRBP100Bugs, BugList).

Populates visit (from sample events), bug_list, bug_count, and rbp100_bug.
Run migrate_sites first. BugList sheet/table must exist or be provided.

Idempotency (application-level; no new UNIQUE constraints):
  - visit: resolve_bat_visit on (site_id, sample_date, sample_code); visits are
    tagged method BAT and reuse an existing un-coded BAT visit at the same
    site/date instead of creating a duplicate
  - bug_list: ON CONFLICT (bug_code) DO NOTHING
  - bug_count: skip when (visit_id, bug_id) already exists
    (source tblBugResults has one row per SampleID+BugID)
  - rbp100_bug: skip when (visit_id, bug_id) already exists
    (source tblRBP100Bugs has one row per SampleID+BugID)

Re-running against the same DB and source files must not duplicate biological
observations. macro_analysis is produced separately by biological_indices.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.config import DATA_DIR
from etl.db import ensure_lookup, get_conn
from etl.visit_helpers import get_site_id_map, _str, _int, _float, _date


def resolve_bat_visit(cur, bat_method_id, site_id, sample_date, sample_code):
    """Return (visit_id, created) for a BAT sample.

    Match order:
      1. A visit with the same site, date and sample_code (re-runs). If it has
         no method yet, tag it BAT.
      2. A BAT visit at the same site/date with no sample_code (created from the
         All-Data workbook): reuse it and record the sample_code.
      3. Otherwise create a new visit tagged BAT.
    """
    cur.execute(
        """
        SELECT visit_id, method_id FROM visit
        WHERE site_id = %s AND sample_date = %s
          AND (sample_code IS NOT DISTINCT FROM %s)
        LIMIT 1
        """,
        (site_id, sample_date, sample_code),
    )
    found = cur.fetchone()
    if found:
        if found[1] is None:
            cur.execute(
                "UPDATE visit SET method_id = %s WHERE visit_id = %s", (bat_method_id, found[0])
            )
        return found[0], False

    cur.execute(
        """
        SELECT visit_id FROM visit
        WHERE site_id = %s AND sample_date = %s
          AND method_id = %s AND sample_code IS NULL
        """,
        (site_id, sample_date, bat_method_id),
    )
    unnamed = cur.fetchall()
    if len(unnamed) == 1:
        visit_id = unnamed[0][0]
        if sample_code:
            cur.execute(
                "UPDATE visit SET sample_code = %s WHERE visit_id = %s", (sample_code, visit_id)
            )
        return visit_id, False

    cur.execute(
        "INSERT INTO visit (site_id, sample_date, sample_code, method_id) "
        "VALUES (%s, %s, %s, %s) RETURNING visit_id",
        (site_id, sample_date, sample_code, bat_method_id),
    )
    return cur.fetchone()[0], True


def run():
    # Prefer tblSampleDates (normalized)
    tbl_file = DATA_DIR / "tblSampleDates.xlsx"
    if not tbl_file.exists():
        tbl_file = DATA_DIR / "BAT Data Consolidation and Recount – Lily Raphael.xlsx"

    stats = {
        "bug_list_inserted": 0,
        "bug_list_existing": 0,
        "visits_created": 0,
        "visits_existing": 0,
        "bug_count_inserted": 0,
        "bug_count_skipped_existing": 0,
        "rbp100_inserted": 0,
        "rbp100_skipped_existing": 0,
        "skipped_unresolved_site": 0,
        "skipped_unresolved_bug": 0,
    }

    with get_conn() as conn:
        cur = conn.cursor()
        site_map = get_site_id_map(conn)
        if not site_map:
            cur.execute("SELECT site_id, site_code FROM site")
            site_map = {r[1]: r[0] for r in cur.fetchall()}

        if not tbl_file.exists():
            print(f"BAT source not found: {tbl_file}")
            sys.exit(1)

        xl = pd.ExcelFile(tbl_file)

        # BugList: taxonomy lookup (already idempotent on bug_code)
        if "BugList" in xl.sheet_names:
            bug_df = pd.read_excel(tbl_file, sheet_name="BugList")
            bug_df.columns = [str(c).strip() for c in bug_df.columns]
            bug_id_map = {}
            for _, row in bug_df.iterrows():
                bug_code = _str(row.get("BugID") or row.get("Bug Id"))
                if not bug_code:
                    continue
                cur.execute("SELECT bug_id FROM bug_list WHERE bug_code = %s", (bug_code,))
                existing = cur.fetchone()
                if existing:
                    bug_id_map[bug_code] = existing[0]
                    stats["bug_list_existing"] += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO bug_list (
                        bug_code, order_class, family, genus_species, ept, tolerance_ftv,
                        functional_feeding_group, habit, scraper, clinger
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (bug_code) DO NOTHING
                    """,
                    (
                        bug_code,
                        _str(row.get("Order/Class") or row.get("Order")),
                        _str(row.get("Family")),
                        _str(row.get("GenusSpecies") or row.get("Genus")),
                        bool(row.get("EPT")) if pd.notna(row.get("EPT")) else None,
                        _float(row.get("FTV") or row.get("tolerance_ftv")),
                        _str(row.get("Functional feeding group")),
                        _str(row.get("Habit")),
                        bool(row.get("Scraper")) if pd.notna(row.get("Scraper")) else None,
                        bool(row.get("Clinger")) if pd.notna(row.get("Clinger")) else None,
                    ),
                )
                cur.execute("SELECT bug_id FROM bug_list WHERE bug_code = %s", (bug_code,))
                r = cur.fetchone()
                if r:
                    bug_id_map[bug_code] = r[0]
                    stats["bug_list_inserted"] += 1

        # Existing observation fingerprints for idempotent re-runs
        # Source identity: one observation per sample (visit) + taxon (bug_id).
        cur.execute("SELECT visit_id, bug_id FROM bug_count")
        existing_bug_count = {(r[0], r[1]) for r in cur.fetchall()}
        cur.execute("SELECT visit_id, bug_id FROM rbp100_bug")
        existing_rbp100 = {(r[0], r[1]) for r in cur.fetchall()}

        bat_method_id = ensure_lookup(conn, "lst_method", "method_id", "name", "BAT")

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
                    stats["skipped_unresolved_site"] += 1
                    continue

                visit_id, created = resolve_bat_visit(
                    cur, bat_method_id, site_id, sample_date, sample_code
                )
                stats["visits_created" if created else "visits_existing"] += 1
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
                    cur.execute(
                        "SELECT bug_id FROM bug_list WHERE bug_code = %s OR bug_id = %s LIMIT 1",
                        (str(bug_id_key), bug_id_key),
                    )
                    b = cur.fetchone()
                    if not b:
                        stats["skipped_unresolved_bug"] += 1
                        continue
                    amount = _int(row.get("Amount") or row.get("Number"))
                    if amount is None:
                        continue
                    exclude = (
                        bool(row.get("Exclude")) if pd.notna(row.get("Exclude")) else False
                    )
                    fp = (visit_id, b[0])
                    if fp in existing_bug_count:
                        stats["bug_count_skipped_existing"] += 1
                        continue
                    cur.execute(
                        "INSERT INTO bug_count (visit_id, bug_id, amount, exclude) VALUES (%s, %s, %s, %s)",
                        (visit_id, b[0], amount, exclude),
                    )
                    existing_bug_count.add(fp)
                    stats["bug_count_inserted"] += 1

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
                    cur.execute(
                        "SELECT bug_id FROM bug_list WHERE bug_code = %s OR bug_id = %s LIMIT 1",
                        (str(bug_id_key), bug_id_key),
                    )
                    b = cur.fetchone()
                    if not b:
                        stats["skipped_unresolved_bug"] += 1
                        continue
                    amount = _int(row.get("Amount"))
                    if amount is None:
                        continue
                    fp = (visit_id, b[0])
                    if fp in existing_rbp100:
                        stats["rbp100_skipped_existing"] += 1
                        continue
                    cur.execute(
                        "INSERT INTO rbp100_bug (visit_id, bug_id, amount) VALUES (%s, %s, %s)",
                        (visit_id, b[0], amount),
                    )
                    existing_rbp100.add(fp)
                    stats["rbp100_inserted"] += 1

    print("BAT migration done.")
    print(
        "  visits_created={visits_created} visits_existing={visits_existing} "
        "bug_list_inserted={bug_list_inserted} bug_list_existing={bug_list_existing} "
        "bug_count_inserted={bug_count_inserted} "
        "bug_count_skipped_existing={bug_count_skipped_existing} "
        "rbp100_inserted={rbp100_inserted} "
        "rbp100_skipped_existing={rbp100_skipped_existing}".format(**stats)
    )
    return stats


if __name__ == "__main__":
    run()
