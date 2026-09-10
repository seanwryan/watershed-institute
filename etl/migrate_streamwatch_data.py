#!/usr/bin/env python3
"""
Migrate historical StreamWatch chemistry/bacteria from All StreamWatch Data.xlsx.

Phase 1 Data Trust reconstruction:
  - Load ONLY the ALL DATA sheet (technical primary pending staff confirmation).
  - Do NOT bulk-import watershed sheets (prior ALL DATA + watershed load caused duplication).
  - Application-level exact-package dedupe; retain differing same-day packages.
  - Compatible with final Sep 9 workbook banner/header layout and unit-suffixed columns.
  - Chloride is stored as-is (workbook already corrected; never ÷10 again).

Does not invent UNIQUE(visit_id). Run migrate_sites first.

Dry-run (no DB writes):
  python -m etl.migrate_streamwatch_data --dry-run [/path/to/All StreamWatch Data.xlsx]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.all_data_workbook import (
    CHLORIDE_APPLY_DIVIDE_BY_TEN,
    E_COLI_RESULT_ALIASES,
    FINAL_METHOD_NAMES,
    NITRATE_UNIT_POLICY,
    classify_data_condition,
    col,
    dry_run_all_data,
    mapped_chem_values,
    parse_e_coli_result,
    read_all_data_sheet,
)
from etl.chem_recon import (
    CHEM_VALUE_FIELDS,
    PRIMARY_SHEET,
    chem_fingerprint,
    empty_report,
    finalize_db_stats,
    save_report,
)
from etl.config import DATA_DIR, DATABASE_URL, refuse_if_protected_database
from etl.db import ensure_lookup, get_conn
from etl.visit_helpers import (
    _date,
    _str,
    ensure_visit,
    get_data_condition_id_map,
    get_method_id_map,
    get_site_id_map,
    insert_bacteria,
    insert_chemical,
)


def _ensure_final_methods(conn) -> dict:
    """Additive method seed for final workbook labels; keep legacy names intact."""
    for name in FINAL_METHOD_NAMES:
        ensure_lookup(conn, "lst_method", "method_id", "name", name)
    for name in ("LaMotte", "Hanna", "Survey123", "Gallery"):
        ensure_lookup(conn, "lst_method", "method_id", "name", name)
    return get_method_id_map(conn)


def _ensure_final_data_conditions(conn) -> dict:
    """Additive data_condition codes used by the Sep 9 workbook."""
    extras = {
        "Outlier": ("Value outside typical range; review warranted", "issues_anomalies"),
        "Duplicate?": (
            "Apparent duplicate awaiting paper-sheet reconciliation",
            "issues_anomalies",
        ),
    }
    with conn.cursor() as cur:
        for code, (desc, domain) in extras.items():
            cur.execute(
                """
                INSERT INTO data_condition (code, description, domain)
                VALUES (%s, %s, %s)
                ON CONFLICT (code) DO NOTHING
                """,
                (code, desc, domain),
            )
    return get_data_condition_id_map(conn)


def run(data_file: Path | None = None):
    refuse_if_protected_database()
    if CHLORIDE_APPLY_DIVIDE_BY_TEN:
        raise RuntimeError("Refusing to run with chloride ÷10 correction enabled")

    data_file = Path(data_file) if data_file else (DATA_DIR / "All StreamWatch Data.xlsx")
    if not data_file.exists():
        print(f"Required file not found: {data_file}")
        print(
            "Historical chemistry reconstruction uses ALL DATA only "
            "(no 30-yr fallback in this path)."
        )
        sys.exit(1)

    xl = pd.ExcelFile(data_file)
    if PRIMARY_SHEET not in xl.sheet_names:
        print(f"Sheet {PRIMARY_SHEET!r} not found in {data_file}. Sheets: {xl.sheet_names}")
        sys.exit(1)

    report = empty_report()
    report["database_target"] = DATABASE_URL
    report["notes"]["nitrate_unit_policy"] = NITRATE_UNIT_POLICY
    report["notes"]["chloride_correction"] = (
        "Final workbook chloride is stored as-is; ETL does not divide by 10."
    )
    report["notes"]["data_condition_compounds"] = (
        "Semicolon/comma compound Data Condition strings are left unresolved "
        "(full string logged); atomic official values including Outlier and "
        "Duplicate? are mapped when present in data_condition."
    )
    all_data = report["all_data"]
    all_data["source_file"] = str(data_file)
    unresolved_conditions: list = []
    unresolved_sites = set()
    unresolved_methods = set()
    seen_fingerprints = set()
    site_date_packages = defaultdict(set)

    source_non_null = {f: 0 for f in CHEM_VALUE_FIELDS}
    inserted_non_null = {f: 0 for f in CHEM_VALUE_FIELDS}
    e_coli_stats = {
        "result_nonnull": 0,
        "inserted": 0,
        "unparsable": 0,
        "with_modifier_note": 0,
    }

    df, header_row = read_all_data_sheet(data_file)
    all_data["header_row_0based"] = header_row
    all_data["source_rows"] = len(df)

    with get_conn() as conn:
        cur = conn.cursor()
        site_map = get_site_id_map(conn)
        cond_map = _ensure_final_data_conditions(conn)
        method_map = _ensure_final_methods(conn)

        for _, row in df.iterrows():
            site_code = _str(col(row, "Site", "site", "Site Code", "SiteCode"))
            if not site_code:
                continue
            site_id = site_map.get(site_code)
            if not site_id:
                unresolved_sites.add(site_code)
                continue

            sample_date = _date(col(row, "Date", "date", "Sample Date"))
            if not sample_date:
                continue

            method_name = _str(col(row, "Method", "method"))
            method_id = method_map.get(method_name) if method_name else None
            if method_name and method_id is None:
                unresolved_methods.add(method_name)

            cond_raw = _str(col(row, "Data Condition", "data_condition"))
            dc_info = classify_data_condition(cond_raw, cond_map, unresolved_conditions)
            data_condition_id = dc_info["data_condition_id"]
            if not cond_raw and _str(col(row, "Notes", "notes")):
                data_condition_id = cond_map.get("Unchecked")

            values = mapped_chem_values(row)
            if all(v is None for v in values.values()):
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
                    if any(v is not None for v in values.values()):
                        all_data["packages_inserted"] += 1
                        for f, v in values.items():
                            if v is not None:
                                inserted_non_null[f] += 1

            # ALL DATA E. coli — distinct from IDEXX (migrate_bact_2025)
            raw_ecoli = col(row, *E_COLI_RESULT_ALIASES)
            if raw_ecoli is not None and not (
                isinstance(raw_ecoli, float) and pd.isna(raw_ecoli)
            ):
                e_coli_stats["result_nonnull"] += 1
            e_coli, mod, skip = parse_e_coli_result(row)
            if skip == "unparsable_e_coli_result":
                e_coli_stats["unparsable"] += 1
            elif e_coli is not None:
                visit_id = ensure_visit(
                    cur, site_id, sample_date, None, None, method_id, None
                )
                note = f"E. coli Mod.: {mod}" if mod else None
                if mod:
                    e_coli_stats["with_modifier_note"] += 1
                insert_bacteria(
                    cur,
                    visit_id,
                    data_condition_id,
                    e_coli_mpn_100ml=e_coli,
                    detection_limit_note=note,
                )
                e_coli_stats["inserted"] += 1

        all_data["source_non_null"] = source_non_null
        all_data["inserted_non_null"] = inserted_non_null
        all_data["unresolved_sites"] = sorted(unresolved_sites)
        all_data["unresolved_site_count"] = len(unresolved_sites)
        all_data["unresolved_methods"] = sorted(unresolved_methods)
        all_data["unresolved_method_count"] = len(unresolved_methods)
        all_data["unresolved_data_conditions"] = sorted(unresolved_conditions)
        all_data["differing_multi_package_site_dates"] = sum(
            1 for pkgs in site_date_packages.values() if len(pkgs) > 1
        )
        all_data["e_coli"] = e_coli_stats
        all_data["compound_data_conditions_unresolved"] = sum(
            1 for s in unresolved_conditions if ";" in s or "," in s
        )

        finalize_db_stats(conn, report, DATABASE_URL)
        path = save_report(report)

    print(
        f"StreamWatch ALL DATA chemistry migration done. "
        f"header_row={header_row} "
        f"inserted={all_data['packages_inserted']} "
        f"exact_dups_skipped={all_data['exact_duplicates_skipped']} "
        f"e_coli_inserted={e_coli_stats['inserted']} "
        f"report={path}"
    )


def run_dry_run(data_file: Path | None = None, site_codes=None):
    data_file = Path(data_file) if data_file else (DATA_DIR / "All StreamWatch Data.xlsx")
    if not data_file.exists():
        print(f"Required file not found: {data_file}")
        sys.exit(1)
    stats = dry_run_all_data(data_file, site_codes=site_codes)
    assert stats["writes_database"] is False
    assert stats["chloride_divide_by_ten_enabled"] is False
    print(json.dumps(stats, indent=2, default=str))
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migrate or dry-run ALL DATA chemistry")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate workbook load plan without writing to PostgreSQL",
    )
    parser.add_argument(
        "workbook",
        nargs="?",
        default=None,
        help="Optional path to All StreamWatch Data.xlsx",
    )
    args = parser.parse_args(argv)
    path = Path(args.workbook) if args.workbook else None
    if args.dry_run:
        run_dry_run(path)
    else:
        run(path)


if __name__ == "__main__":
    main()
