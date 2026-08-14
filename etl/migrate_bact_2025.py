#!/usr/bin/env python3
"""
Migrate BACT and HAB 2025 Data.xlsx.

Chemistry (Survey123): conservative enrichment only.
  - Use sample Date (not CreationDate).
  - Match existing site/date visits from historical load.
  - Fill NULL chemical fields only (esp. chloride, water temperature).
  - Do not overwrite non-null historical values.
  - Log conflicts / unmatched; do not blindly append duplicate packages.

Bacteria (IDEXX): attach by visit.sample_code with application-level
  idempotency on (visit_id, e_coli_mpn_100ml). Re-runs skip existing rows.

Gallery / Turbidity / Phycocyanin sheets are not loaded in this milestone.

Parsing helpers are shared with etl/bact_reconcile.py (preview uses the same
rules; write path behavior below is unchanged).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.bact_reconcile import (
    analyze_fill,
    chemical_rows_for_visit,
    col,
    find_visits_for_site_date,
    pick_enrichment_target,
    survey123_values,
)
from etl.chem_recon import (
    CHEM_VALUE_FIELDS,
    finalize_db_stats,
    load_report,
    save_report,
)
from etl.config import DATA_DIR, DATABASE_URL, refuse_if_protected_database
from etl.db import get_conn
from etl.visit_helpers import (
    _date,
    _int,
    _str,
    get_site_id_map,
    insert_bacteria,
)


# Backwards-compatible aliases for any external imports of private helpers.
_col = col
_survey123_values = survey123_values
_find_visits_for_site_date = find_visits_for_site_date
_chemical_rows_for_visit = chemical_rows_for_visit
_pick_enrichment_target = pick_enrichment_target


def _apply_fill(cur, chemical_id, row, incoming, fields_filled_counter, conflict_fields: list) -> int:
    """Fill NULL fields only. Record per-field conflicts when non-null values differ."""
    would_fill, conflicts = analyze_fill(row, incoming)
    conflict_fields.extend(
        {"field": c["field"], "existing": c["existing"], "survey123": c["survey123"]}
        for c in conflicts
    )
    if not would_fill:
        return 0
    sets = []
    vals = []
    for item in would_fill:
        f = item["field"]
        sets.append(f"{f} = %s")
        vals.append(item["value"])
        fields_filled_counter[f] = fields_filled_counter.get(f, 0) + 1
    vals.append(chemical_id)
    cur.execute(
        f"UPDATE chemical SET {', '.join(sets)} WHERE chemical_id = %s",
        vals,
    )
    return len(would_fill)


def run():
    refuse_if_protected_database()

    data_file = DATA_DIR / "BACT and HAB 2025 Data.xlsx"
    if not data_file.exists():
        print(f"File not found: {data_file}. Set STREAMWATCH_DATA_DIR.")
        sys.exit(1)

    report = load_report()
    report["database_target"] = DATABASE_URL
    s123 = report["survey123"]
    # reset survey123 section for this run
    s123.update(
        {
            "rows_read": 0,
            "rows_considered": 0,
            "site_date_matches": 0,
            "enrichment_updates": 0,
            "fields_filled": {f: 0 for f in CHEM_VALUE_FIELDS},
            "visit_sample_code_filled": 0,
            "conflicts": [],
            "conflict_count": 0,
            "unmatched": [],
            "unmatched_count": 0,
            "packages_inserted": 0,
            "skipped_no_chem": 0,
            "skipped_unresolved_site": 0,
            "skipped_no_date": 0,
        }
    )

    xl = pd.ExcelFile(data_file)
    with get_conn() as conn:
        cur = conn.cursor()
        site_map = get_site_id_map(conn)
        method_id_bact = None
        cur.execute("SELECT method_id FROM lst_method WHERE name = 'BACT' LIMIT 1")
        r = cur.fetchone()
        if r:
            method_id_bact = r[0]

        if "SURVEY123" in xl.sheet_names or "Survey123" in xl.sheet_names:
            sheet = "SURVEY123" if "SURVEY123" in xl.sheet_names else "Survey123"
            df = pd.read_excel(data_file, sheet_name=sheet)
            df.columns = [str(c).strip() for c in df.columns]
            s123["rows_read"] = len(df)

            # Prefer explicit sample Date — never CreationDate.
            date_col = "Date" if "Date" in df.columns else None
            if date_col is None:
                # fallback: column named exactly Sample Date
                date_col = next(
                    (c for c in df.columns if c.lower() in ("sample date", "date collected")),
                    None,
                )
            site_col = next(
                (
                    c
                    for c in df.columns
                    if c.lower() in ("monitoring site id", "monitoring site id ")
                    or ("site" in c.lower() and "id" in c.lower())
                ),
                None,
            )

            for _, row in df.iterrows():
                site_code = _str(row.get(site_col) if site_col else None)
                if not site_code:
                    continue
                site_id = site_map.get(site_code)
                if not site_id:
                    s123["skipped_unresolved_site"] += 1
                    continue

                sample_date = _date(row.get(date_col) if date_col else None)
                if not sample_date:
                    s123["skipped_no_date"] += 1
                    continue

                incoming = survey123_values(row)
                if all(v is None for v in incoming.values()):
                    s123["skipped_no_chem"] += 1
                    continue

                s123["rows_considered"] += 1
                sample_code = _str(row.get("Sample Code") or row.get("Sample code"))

                visits = find_visits_for_site_date(cur, site_id, sample_date)
                if not visits:
                    s123["unmatched"].append(
                        {
                            "site": site_code,
                            "sample_date": str(sample_date),
                            "sample_code": sample_code,
                            "reason": "no_visit",
                        }
                    )
                    continue

                s123["site_date_matches"] += 1
                # Prefer visit with matching sample_code if present; else first visit
                visit_id = visits[0][0]
                visit_sample_code = visits[0][1]
                if sample_code:
                    for vid, sc in visits:
                        if sc == sample_code:
                            visit_id = vid
                            visit_sample_code = sc
                            break

                if sample_code and not visit_sample_code:
                    cur.execute(
                        "UPDATE visit SET sample_code = %s WHERE visit_id = %s AND sample_code IS NULL",
                        (sample_code, visit_id),
                    )
                    if cur.rowcount:
                        s123["visit_sample_code_filled"] += 1

                chem_rows = chemical_rows_for_visit(cur, visit_id)
                target, reason = pick_enrichment_target(chem_rows, method_id_bact, incoming)
                if target is None:
                    s123["unmatched"].append(
                        {
                            "site": site_code,
                            "sample_date": str(sample_date),
                            "sample_code": sample_code,
                            "visit_id": visit_id,
                            "reason": reason,
                            "incoming": {k: v for k, v in incoming.items() if v is not None},
                        }
                    )
                    continue

                field_conflicts = []
                filled = _apply_fill(
                    cur,
                    target["chemical_id"],
                    target,
                    incoming,
                    s123["fields_filled"],
                    field_conflicts,
                )
                if field_conflicts:
                    s123["conflicts"].append(
                        {
                            "site": site_code,
                            "sample_date": str(sample_date),
                            "sample_code": sample_code,
                            "visit_id": visit_id,
                            "chemical_id": target["chemical_id"],
                            "fields": field_conflicts[:20],
                        }
                    )
                if filled:
                    s123["enrichment_updates"] += 1
                elif not field_conflicts:
                    s123["unmatched"].append(
                        {
                            "site": site_code,
                            "sample_date": str(sample_date),
                            "reason": "nothing_to_fill",
                            "visit_id": visit_id,
                        }
                    )

            s123["conflict_count"] = len(s123["conflicts"])
            s123["unmatched_count"] = len(s123["unmatched"])
            # Cap long lists in report for readability
            s123["conflicts"] = s123["conflicts"][:200]
            s123["unmatched"] = s123["unmatched"][:200]

        # IDEXX bacteria attach (non-chemistry), idempotent on visit + E. coli MPN
        idexx = {
            "rows_read": 0,
            "rows_considered": 0,
            "inserted": 0,
            "already_existing": 0,
            "unresolved_visit": 0,
            "invalid_skipped": 0,
            "skipped_no_sample_code": 0,
        }
        report["idexx"] = idexx

        if "IDEXX" in xl.sheet_names:
            df = pd.read_excel(data_file, sheet_name="IDEXX")
            df.columns = [str(c).strip() for c in df.columns]
            idexx["rows_read"] = int(len(df))
            code_col = next(
                (
                    c
                    for c in df.columns
                    if ("sample" in c.lower() and "code" in c.lower()) or c == "SampleCode"
                ),
                None,
            )
            ecoli_col = next(
                (
                    c
                    for c in df.columns
                    if "e. coli" in c.lower() or "ecoli" in c.lower() or c == "E. coli (MPN)"
                ),
                None,
            )

            # Fingerprint: visit_id + integer E. coli MPN (source Sample Code → visit).
            # Same sample code with distinct MPN values (e.g. HO2_2025-07-13) remain distinct.
            cur.execute(
                """
                SELECT visit_id, e_coli_mpn_100ml
                FROM bacteria
                WHERE e_coli_mpn_100ml IS NOT NULL
                """
            )
            existing = {(r[0], r[1]) for r in cur.fetchall()}

            for _, row in df.iterrows():
                sample_code = _str(row.get(code_col) if code_col else None) or _str(
                    row.get("Sample code")
                )
                raw_ecoli = row.get(ecoli_col) if ecoli_col else row.get("E. coli (MPN)")
                e_coli = _int(raw_ecoli)

                if not sample_code:
                    # Header / blank rows in the IDEXX sheet
                    if pd.notna(raw_ecoli) or pd.notna(row.get("Sample ID")):
                        idexx["skipped_no_sample_code"] += 1
                    continue

                if e_coli is None:
                    idexx["invalid_skipped"] += 1
                    continue

                idexx["rows_considered"] += 1
                cur.execute(
                    "SELECT visit_id FROM visit WHERE sample_code = %s LIMIT 1",
                    (sample_code,),
                )
                v = cur.fetchone()
                if not v:
                    idexx["unresolved_visit"] += 1
                    continue

                visit_id = v[0]
                fp = (visit_id, e_coli)
                if fp in existing:
                    idexx["already_existing"] += 1
                    continue

                insert_bacteria(cur, visit_id, None, e_coli_mpn_100ml=e_coli)
                existing.add(fp)
                idexx["inserted"] += 1

        finalize_db_stats(conn, report, DATABASE_URL)
        path = save_report(report)

    print(f"BACT 2025 Survey123 enrichment done. report={path}")
    print(
        f"  considered={s123['rows_considered']} matches={s123['site_date_matches']} "
        f"updates={s123['enrichment_updates']} conflicts={s123['conflict_count']} "
        f"unmatched={s123['unmatched_count']}"
    )
    ix = report.get("idexx") or {}
    print(
        f"IDEXX bacteria: considered={ix.get('rows_considered', 0)} "
        f"inserted={ix.get('inserted', 0)} skipped_existing={ix.get('already_existing', 0)} "
        f"unresolved_visit={ix.get('unresolved_visit', 0)} "
        f"invalid_skipped={ix.get('invalid_skipped', 0)}"
    )


if __name__ == "__main__":
    run()
