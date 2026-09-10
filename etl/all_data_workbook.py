"""
Read / validate All StreamWatch Data.xlsx ALL DATA sheet.

Compatible with the Sep 9 final workbook layout (title banner above the real header)
and older flat-header copies. Shared by migrate_streamwatch_data and dry-run validation.

Does not write to PostgreSQL.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

from etl.chem_recon import (
    CHEM_HEADER_ALIASES,
    CHEM_VALUE_FIELDS,
    PRIMARY_SHEET,
    chem_fingerprint,
    resolve_data_condition_id,
    round_chem,
)
from etl.visit_helpers import _date, _float, _int, _str

# Columns that mark the real ALL DATA header (final workbook has banner rows above).
HEADER_MARKERS = ("Data Condition", "Method", "Site", "Date")

# Final workbook Method values (additive to legacy LaMotte/Hanna seeds).
FINAL_METHOD_NAMES = (
    "CAT: Early LaMotte",
    "CAT: LaMotte",
    "CAT: Hanna",
    "Salt Watch",
    "BACT",
    "BAT",
)

# Chloride must be stored as read — final workbook is already ÷10-corrected.
# Never introduce a divide-by-10 (or multiply-by-0.1) correction here.
CHLORIDE_APPLY_DIVIDE_BY_TEN = False

E_COLI_RESULT_ALIASES = (
    "E. coli Result",
    "E. coli",
    "E coli",
    "E_coli",
    "e_coli_mpn_100ml",
)
E_COLI_MOD_ALIASES = (
    "E. coli Mod.",
    "E. coli mod.",
    "E. coli Mod",
    "E coli Mod.",
)

# Documented nitrate finding: final header is mg/L; DB column remains nitrate_ug_l.
# Values in recent workbooks are mg/L-scale and historically were loaded without
# mg→µg conversion. Do not auto-convert until Watershed confirms policy.
NITRATE_UNIT_POLICY = (
    "Store Nitrate (mg/L) numeric values as-is into nitrate_ug_l without unit "
    "conversion (historical ETL behavior). Column name is historically misleading; "
    "scientific conversion is deferred pending confirmation."
)


def col(row, *names):
    for n in names:
        if n in row.index and pd.notna(row.get(n)):
            return row.get(n)
    return None


def find_all_data_header_row(
    path: Path,
    sheet_name: str = PRIMARY_SHEET,
    max_scan: int = 40,
) -> int:
    """
    Return 0-based header row index for ALL DATA.

    Prefers a row containing Data Condition + Method + Site + Date.
    Falls back to row 0 when the sheet is already a flat table (older copies).
    """
    path = Path(path)
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=max_scan)
    markers = {m.lower() for m in HEADER_MARKERS}
    for i in range(len(raw)):
        cells = {
            str(v).strip().lower()
            for v in raw.iloc[i].tolist()
            if pd.notna(v) and str(v).strip()
        }
        if markers.issubset(cells):
            return i
    # Older workbooks: first row already has Method/Site/Date (may omit Data Condition label edge cases)
    soft = {"method", "site", "date"}
    for i in range(len(raw)):
        cells = {
            str(v).strip().lower()
            for v in raw.iloc[i].tolist()
            if pd.notna(v) and str(v).strip()
        }
        if soft.issubset(cells):
            return i
    return 0


def read_all_data_sheet(path: Path, sheet_name: str = PRIMARY_SHEET) -> Tuple[pd.DataFrame, int]:
    """Load ALL DATA with detected header. Returns (dataframe, header_row_0based)."""
    path = Path(path)
    header_row = find_all_data_header_row(path, sheet_name=sheet_name)
    df = pd.read_excel(path, sheet_name=sheet_name, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    return df, header_row


def mapped_chem_values(row) -> Dict[str, Optional[float]]:
    """Map one ALL DATA row to chemical field values using CHEM_HEADER_ALIASES."""
    values = {}
    for field, aliases in CHEM_HEADER_ALIASES.items():
        raw = col(row, *aliases)
        if field == "chloride_mg_l":
            values[field] = map_chloride_mg_l(raw)
        else:
            values[field] = round_chem(_float(raw))
    return values


def map_chloride_mg_l(raw) -> Optional[float]:
    """
    Map chloride from the workbook.

    Final authoritative workbook already contains corrected discrete-analyzer
    values. This function must never divide by 10.
    """
    if CHLORIDE_APPLY_DIVIDE_BY_TEN:
        raise RuntimeError(
            "CHLORIDE_APPLY_DIVIDE_BY_TEN must remain False; final workbook "
            "chloride is already corrected."
        )
    return round_chem(_float(raw))


def parse_e_coli_result(row) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    Return (e_coli_mpn, modifier, skip_reason).

    Loads integer-parseable E. coli Result (and legacy E. coli aliases).
    Modifier from E. coli Mod. is returned for storage in detection_limit_note
    when the bacteria schema supports it — not invented as a new scientific rule.
    """
    raw_result = col(row, *E_COLI_RESULT_ALIASES)
    raw_mod = col(row, *E_COLI_MOD_ALIASES)
    mod = _str(raw_mod)
    if raw_result is None or (isinstance(raw_result, float) and pd.isna(raw_result)):
        return None, mod, None
    # Trailing ? / non-numeric: do not invent censored policy — skip unparsable
    e_coli = _int(raw_result)
    if e_coli is None:
        return None, mod, "unparsable_e_coli_result"
    return e_coli, mod, None


def classify_data_condition(
    raw: Optional[str],
    cond_map: Dict[str, int],
    unresolved_log: List[str],
) -> Dict[str, Any]:
    """
    Resolve Data Condition without inventing compound-token policy.

    Atomic official values (including Outlier, Duplicate?) map when present in cond_map.
    Semicolon/comma compounds are left unresolved and logged in full.
    """
    info = {
        "raw": raw,
        "data_condition_id": None,
        "status": "empty",
        "is_compound": False,
    }
    if not raw:
        return info
    s = raw.strip()
    if not s:
        return info
    info["is_compound"] = (";" in s) or ("," in s)
    dc_id = resolve_data_condition_id(s, cond_map, unresolved_log)
    info["data_condition_id"] = dc_id
    if dc_id is not None:
        info["status"] = "resolved"
    elif info["is_compound"]:
        info["status"] = "unresolved_compound"
    else:
        info["status"] = "unresolved_atomic"
    return info


def dry_run_all_data(
    path: Path,
    *,
    site_codes: Optional[Iterable[str]] = None,
    method_names: Optional[Iterable[str]] = None,
    condition_codes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """
    Read the final (or any) ALL DATA workbook and report what WOULD load.

    Does not connect to or write PostgreSQL. Optional lookup sets simulate
    resolution against known site/method/condition codes.
    """
    path = Path(path)
    df, header_row = read_all_data_sheet(path)
    site_set = set(site_codes) if site_codes is not None else None
    method_set = set(method_names) if method_names is not None else set(FINAL_METHOD_NAMES) | {
        "LaMotte",
        "Hanna",
        "Survey123",
        "Gallery",
    }
    cond_map = {c: i for i, c in enumerate(condition_codes or (), start=1)}
    if not cond_map:
        # Typical seed + final atomic tags for dry-run visibility
        for i, c in enumerate(
            [
                "Accepted",
                "Corrected",
                "Flagged",
                "Minor_Deviation",
                "Moderate_Deviation",
                "Site_Conflict",
                "Duplicate",
                "Duplicate?",
                "Incomplete",
                "Erroneous",
                "Outlier",
                "Provisional",
                "Unchecked",
                "Validated",
                "Approved",
                "Certified",
                "Derived",
                "Estimated",
                "Adjusted",
                "Suppressed",
            ],
            start=1,
        ):
            cond_map[c] = i

    unresolved_conditions: List[str] = []
    unresolved_sites: Set[str] = set()
    unresolved_methods: Set[str] = set()
    seen_fps: Set[Tuple] = set()
    site_date_packages = defaultdict(set)

    stats: Dict[str, Any] = {
        "source_file": str(path),
        "sheet": PRIMARY_SHEET,
        "header_row_0based": header_row,
        "workbook_rows_read": len(df),
        "valid_rows": 0,
        "skipped_no_site": 0,
        "skipped_no_date": 0,
        "skipped_unresolved_site": 0,
        "chemistry_capable_rows": 0,
        "exact_duplicates": 0,
        "would_insert_chemistry": 0,
        "multi_package_site_dates": 0,
        "e_coli_result_nonnull": 0,
        "e_coli_result_parseable": 0,
        "e_coli_result_unparsable": 0,
        "e_coli_with_modifier": 0,
        "e_coli_modifier_not_stored_in_schema_note": (
            "Modifier is preserved via bacteria.detection_limit_note when loading; "
            "no separate modifier column exists"
        ),
        "chloride_nonnull": 0,
        "parameter_non_null": {f: 0 for f in CHEM_VALUE_FIELDS},
        "method_counts": defaultdict(int),
        "unresolved_method_counts": defaultdict(int),
        "data_condition_status_counts": defaultdict(int),
        "unresolved_data_conditions": [],
        "unresolved_sites": [],
        "unresolved_methods": [],
        "chloride_divide_by_ten_enabled": CHLORIDE_APPLY_DIVIDE_BY_TEN,
        "nitrate_unit_policy": NITRATE_UNIT_POLICY,
        "writes_database": False,
    }

    for _, row in df.iterrows():
        site_code = _str(col(row, "Site", "site", "Site Code", "SiteCode"))
        if not site_code:
            stats["skipped_no_site"] += 1
            continue
        sample_date = _date(col(row, "Date", "date", "Sample Date"))
        if not sample_date:
            stats["skipped_no_date"] += 1
            continue

        stats["valid_rows"] += 1
        if site_set is not None and site_code not in site_set:
            unresolved_sites.add(site_code)
            stats["skipped_unresolved_site"] += 1
            continue

        method_name = _str(col(row, "Method", "method"))
        if method_name:
            stats["method_counts"][method_name] += 1
            if method_name not in method_set:
                unresolved_methods.add(method_name)
                stats["unresolved_method_counts"][method_name] += 1

        cond_raw = _str(col(row, "Data Condition", "data_condition"))
        dc_info = classify_data_condition(cond_raw, cond_map, unresolved_conditions)
        stats["data_condition_status_counts"][dc_info["status"]] += 1

        values = mapped_chem_values(row)
        if values.get("chloride_mg_l") is not None:
            stats["chloride_nonnull"] += 1
        if any(v is not None for v in values.values()):
            stats["chemistry_capable_rows"] += 1
            for f, v in values.items():
                if v is not None:
                    stats["parameter_non_null"][f] += 1
            fp = chem_fingerprint(site_code, sample_date, method_name, values)
            site_date_packages[(site_code, sample_date)].add(fp)
            if fp in seen_fps:
                stats["exact_duplicates"] += 1
            else:
                seen_fps.add(fp)
                stats["would_insert_chemistry"] += 1

        raw_ecoli = col(row, *E_COLI_RESULT_ALIASES)
        if raw_ecoli is not None and not (isinstance(raw_ecoli, float) and pd.isna(raw_ecoli)):
            stats["e_coli_result_nonnull"] += 1
        e_coli, mod, skip = parse_e_coli_result(row)
        if mod:
            stats["e_coli_with_modifier"] += 1
        if skip == "unparsable_e_coli_result":
            stats["e_coli_result_unparsable"] += 1
        elif e_coli is not None:
            stats["e_coli_result_parseable"] += 1

    stats["multi_package_site_dates"] = sum(
        1 for pkgs in site_date_packages.values() if len(pkgs) > 1
    )
    stats["unresolved_sites"] = sorted(unresolved_sites)
    stats["unresolved_site_count"] = len(unresolved_sites)
    stats["unresolved_methods"] = sorted(unresolved_methods)
    stats["unresolved_method_count"] = len(unresolved_methods)
    stats["unresolved_data_conditions"] = sorted(unresolved_conditions)
    stats["unresolved_data_condition_count"] = len(unresolved_conditions)
    stats["method_counts"] = dict(stats["method_counts"])
    stats["unresolved_method_counts"] = dict(stats["unresolved_method_counts"])
    stats["data_condition_status_counts"] = dict(stats["data_condition_status_counts"])
    return stats
