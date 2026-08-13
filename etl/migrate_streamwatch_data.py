#!/usr/bin/env python3
"""
Migrate historical StreamWatch chemistry/bacteria from All StreamWatch Data.xlsx.

Phase 1 Data Trust reconstruction:
  - Load ONLY the ALL DATA sheet (technical primary pending staff confirmation).
  - Do NOT bulk-import watershed sheets (prior ALL DATA + watershed load caused duplication).
  - Application-level exact-package dedupe; retain differing same-day packages.
  - Corrected source header mappings for temperatures, DO, chloride, etc.

Does not invent UNIQUE(visit_id). Run migrate_sites first.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.chem_recon import (
    CHEM_HEADER_ALIASES,
    CHEM_VALUE_FIELDS,
    PRIMARY_SHEET,
    chem_fingerprint,
    empty_report,
    finalize_db_stats,
    resolve_data_condition_id,
    round_chem,
    save_report,
)
from etl.config import DATA_DIR, DATABASE_URL, refuse_if_protected_database
from etl.db import get_conn
from etl.visit_helpers import (
    _date,
    _float,
    _int,
    _str,
    ensure_visit,
    get_data_condition_id_map,
    get_method_id_map,
    get_site_id_map,
    insert_bacteria,
    insert_chemical,
)


def _col(row, *names):
    for n in names:
        if n in row.index and pd.notna(row.get(n)):
            return row.get(n)
    return None


def _mapped_chem_values(row) -> dict:
    values = {}
    for field, aliases in CHEM_HEADER_ALIASES.items():
        values[field] = round_chem(_float(_col(row, *aliases)))
    return values


def run():
    refuse_if_protected_database()

    data_file = DATA_DIR / "All StreamWatch Data.xlsx"
    if not data_file.exists():
        print(f"Required file not found: {data_file}")
        print("Historical chemistry reconstruction uses ALL DATA only (no 30-yr fallback in this path).")
        sys.exit(1)

    xl = pd.ExcelFile(data_file)
    if PRIMARY_SHEET not in xl.sheet_names:
        print(f"Sheet {PRIMARY_SHEET!r} not found in {data_file}. Sheets: {xl.sheet_names}")
        sys.exit(1)

    # Guard: never auto-detect watershed sheets.
    sheets_to_load = [PRIMARY_SHEET]

    report = empty_report()
    report["database_target"] = DATABASE_URL
    all_data = report["all_data"]
    unresolved_conditions: list = []
    unresolved_sites = set()
    seen_fingerprints = set()
    site_date_packages = defaultdict(set)

    source_non_null = {f: 0 for f in CHEM_VALUE_FIELDS}
    inserted_non_null = {f: 0 for f in CHEM_VALUE_FIELDS}

    with get_conn() as conn:
        cur = conn.cursor()
        site_map = get_site_id_map(conn)
        cond_map = get_data_condition_id_map(conn)
        method_map = get_method_id_map(conn)

        for sheet in sheets_to_load:
            df = pd.read_excel(data_file, sheet_name=sheet)
            df.columns = [str(c).strip() for c in df.columns]
            all_data["source_rows"] = len(df)

            for _, row in df.iterrows():
                site_code = _str(_col(row, "Site", "site", "Site Code", "SiteCode"))
                if not site_code:
                    continue
                site_id = site_map.get(site_code)
                if not site_id:
                    unresolved_sites.add(site_code)
                    continue

                sample_date = _date(_col(row, "Date", "date", "Sample Date"))
                if not sample_date:
                    continue

                method_name = _str(_col(row, "Method", "method"))
                method_id = method_map.get(method_name) if method_name else None

                cond_raw = _str(_col(row, "Data Condition", "data_condition"))
                data_condition_id = resolve_data_condition_id(
                    cond_raw, cond_map, unresolved_conditions
                )
                if not cond_raw and _str(_col(row, "Notes", "notes")):
                    data_condition_id = cond_map.get("Unchecked")

                values = _mapped_chem_values(row)
                if all(v is None for v in values.values()):
                    # Still allow bacteria-only rows below
                    pass
                else:
                    all_data["chemistry_capable_packages"] += 1
                    for f, v in values.items():
                        if v is not None:
                            source_non_null[f] += 1

                    fp = chem_fingerprint(site_code, sample_date, method_name, values)
                    site_date_packages[(site_code, sample_date)].add(fp)

                    if fp in seen_fingerprints:
                        all_data["exact_duplicates_skipped"] += 1
                    else:
                        seen_fingerprints.add(fp)
                        visit_id = ensure_visit(
                            cur, site_id, sample_date, None, None, method_id, None
                        )
                        insert_chemical(
                            cur,
                            visit_id,
                            data_condition_id,
                            method_id,
                            **values,
                        )
                        # Count only if at least one value present (insert_chemical no-ops otherwise)
                        if any(v is not None for v in values.values()):
                            all_data["packages_inserted"] += 1
                            for f, v in values.items():
                                if v is not None:
                                    inserted_non_null[f] += 1

                # Bacteria (E. coli) — keep existing behavior on ALL DATA rows
                e_coli = _int(_col(row, "E. coli", "E coli", "E_coli", "e_coli_mpn_100ml"))
                if e_coli is not None:
                    visit_id = ensure_visit(
                        cur, site_id, sample_date, None, None, method_id, None
                    )
                    insert_bacteria(cur, visit_id, data_condition_id, e_coli_mpn_100ml=e_coli)

        all_data["source_non_null"] = source_non_null
        all_data["inserted_non_null"] = inserted_non_null
        all_data["unresolved_sites"] = sorted(unresolved_sites)
        all_data["unresolved_site_count"] = len(unresolved_sites)
        all_data["unresolved_data_conditions"] = sorted(unresolved_conditions)
        all_data["differing_multi_package_site_dates"] = sum(
            1 for pkgs in site_date_packages.values() if len(pkgs) > 1
        )

        # Partial finalize (BACT enrichment may update final_db later)
        finalize_db_stats(conn, report, DATABASE_URL)
        path = save_report(report)

    print(
        f"StreamWatch ALL DATA chemistry migration done. "
        f"inserted={all_data['packages_inserted']} "
        f"exact_dups_skipped={all_data['exact_duplicates_skipped']} "
        f"report={path}"
    )


if __name__ == "__main__":
    run()
