"""
Chemistry migration reconciliation helpers and report writer.

Used by migrate_streamwatch_data and migrate_bact_2025. Writes JSON under reports/
(gitignored). Does not connect to a database by itself except when finalizing
stats from a provided connection.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from etl.config import DATA_DIR, DATABASE_URL, safe_db_slug

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def recon_report_path(database_url: Optional[str] = None) -> Path:
    """JSON recon path under reports/, named for the target database."""
    return REPORTS_DIR / f"chem_recon_{safe_db_slug(database_url or DATABASE_URL)}.json"

# Evidence-supported technical primary for reconstruction; not a staff policy claim.
PRIMARY_SHEET = "ALL DATA"

# Known watershed-only site/date observations deliberately not imported this milestone.
UNRESOLVED_WATERSHED_ONLY = [
    {"sheet": "StonyBrook", "site": "SB6", "sample_date": "2024-03-17", "method": "Hanna"},
    {"sheet": "Crosswick Creek", "site": "CC1", "sample_date": "2024-09-20", "method": "Hanna"},
    {"sheet": "Doctors Creek", "site": "ATL1", "sample_date": "2024-09-20", "method": "Hanna"},
    {"sheet": "Six Mile Run", "site": "SM1", "sample_date": "2024-06-17", "method": "Hanna"},
    {"sheet": "Royce Brook", "site": "RO1a", "sample_date": "2024-06-17", "method": "Hanna"},
    {"sheet": "Millstone River", "site": "TM1", "sample_date": "2024-06-17", "method": "Hanna"},
]

CHEM_VALUE_FIELDS = [
    "air_temp_c",
    "water_temp_c",
    "nitrate_ug_l",
    "phosphate_mg_l",
    "ph",
    "turbidity_ntu",
    "dissolved_oxygen_ppm",
    "dissolved_oxygen_pct",
    "conductivity_us_cm",
    "chloride_mg_l",
]

# Source workbook header → chemical column (plus compatible aliases).
CHEM_HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "air_temp_c": (
        "Air Temperature",
        "Air temperature",
        "Air temp",
        "Air Temp",
        "air_temp_c",
    ),
    "water_temp_c": (
        "Water Temperature",
        "Water temperature",
        "Water temp",
        "Water Temp",
        "Field water temperature",
        "water_temp_c",
    ),
    "nitrate_ug_l": ("Nitrate", "nitrate", "Nitrate (ug/L)", "nitrate_ug_l"),
    "phosphate_mg_l": ("Phosphates", "Phosphate", "phosphate", "phosphate_mg_l"),
    "ph": ("pH", "ph"),
    "turbidity_ntu": ("Turbidity", "Turbidity (NTU)", "turbidity_ntu"),
    "dissolved_oxygen_ppm": (
        "DO ppm",
        "Dissolved oxygen",
        "Dissolved Oxygen",
        "DO",
        "dissolved_oxygen_ppm",
    ),
    "dissolved_oxygen_pct": ("%DO", "DO %", "Percent DO", "dissolved_oxygen_pct"),
    "conductivity_us_cm": ("Conductivity", "conductivity", "conductivity_us_cm"),
    "chloride_mg_l": ("Chloride (mg/L)", "Chloride", "chloride", "chloride_mg_l"),
}


def _json_default(obj: Any):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    # psycopg2 returns Decimal for NUMERIC aggregates
    try:
        from decimal import Decimal

        if isinstance(obj, Decimal):
            return int(obj) if obj == obj.to_integral_value() else float(obj)
    except Exception:
        pass
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def round_chem(v: Optional[float], nd: int = 6) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def chem_fingerprint(
    site_code: str,
    sample_date,
    method_name: Optional[str],
    values: Dict[str, Optional[float]],
) -> Tuple:
    """Deterministic exact-package fingerprint (application-level; not a DB constraint)."""
    d = sample_date.isoformat() if hasattr(sample_date, "isoformat") else str(sample_date)
    method = (method_name or "").strip() or None
    rounded = tuple(round_chem(values.get(f)) for f in CHEM_VALUE_FIELDS)
    return (site_code.strip(), d, method) + rounded


def empty_report() -> Dict[str, Any]:
    return {
        "database_target": None,
        "generated_at": None,
        "notes": {
            "primary_source": (
                "ALL DATA sheet in All StreamWatch Data.xlsx is the evidence-supported "
                "technical primary source for this reconstruction pending staff confirmation "
                "of official authority."
            ),
            "watershed_sheets": "Not bulk-imported (prior ALL DATA + watershed load caused duplication).",
        },
        "all_data": {
            "source_file": str(DATA_DIR / "All StreamWatch Data.xlsx"),
            "sheet": PRIMARY_SHEET,
            "source_rows": 0,
            "chemistry_capable_packages": 0,
            "packages_inserted": 0,
            "exact_duplicates_skipped": 0,
            "unresolved_sites": [],
            "unresolved_site_count": 0,
            "unresolved_data_conditions": [],
            "differing_multi_package_site_dates": 0,
            "source_non_null": {f: 0 for f in CHEM_VALUE_FIELDS},
            "inserted_non_null": {f: 0 for f in CHEM_VALUE_FIELDS},
        },
        "survey123": {
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
        },
        "unresolved_not_imported": {
            "watershed_only_site_dates": UNRESOLVED_WATERSHED_ONLY,
            "count": len(UNRESOLVED_WATERSHED_ONLY),
        },
        "final_db": {},
    }


def load_report(database_url: Optional[str] = None) -> Dict[str, Any]:
    path = recon_report_path(database_url)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return empty_report()


def save_report(report: Dict[str, Any], database_url: Optional[str] = None) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = recon_report_path(database_url or report.get("database_target") or DATABASE_URL)
    report["generated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(
        json.dumps(report, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return path


def resolve_data_condition_id(
    raw: Optional[str],
    cond_map: Dict[str, int],
    unresolved_log: List[str],
) -> Optional[int]:
    """
    Map a source Data Condition string to data_condition_id when safe.
    Does not invent mappings for multi-token / ambiguous strings.
    """
    if not raw:
        return None
    s = raw.strip()
    if not s:
        return None
    if s in cond_map:
        return cond_map[s]
    # Single-token space → underscore (e.g. "Minor Deviation" → Minor_Deviation)
    if ";" not in s and "," not in s:
        underscored = s.replace(" ", "_")
        if underscored in cond_map:
            return cond_map[underscored]
        # case-insensitive single-token
        lower_map = {k.lower(): v for k, v in cond_map.items()}
        if s.lower() in lower_map:
            return lower_map[s.lower()]
        if underscored.lower() in lower_map:
            return lower_map[underscored.lower()]
    if s not in unresolved_log:
        unresolved_log.append(s)
    return None


def finalize_db_stats(conn, report: Dict[str, Any], database_url: str) -> Dict[str, Any]:
    """Fill final_db section from the verification database."""
    report["database_target"] = database_url
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chemical")
    chem_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT visit_id) FROM chemical")
    visits_with_chem = cur.fetchone()[0]

    field_sql = ", ".join(
        f"COUNT(*) FILTER (WHERE {f} IS NOT NULL) AS {f}" for f in CHEM_VALUE_FIELDS
    )
    cur.execute(f"SELECT {field_sql} FROM chemical")
    row = cur.fetchone()
    non_null = dict(zip(CHEM_VALUE_FIELDS, row))

    # Exact duplicate packages under migration fingerprint (site+date+method+values)
    cur.execute(
        """
        SELECT COUNT(*) AS excess_exact_dup_rows
        FROM (
          SELECT 1
          FROM chemical c
          JOIN visit v ON v.visit_id = c.visit_id
          JOIN site s ON s.site_id = v.site_id
          LEFT JOIN lst_method m ON m.method_id = c.method_id
          GROUP BY s.site_code, v.sample_date, m.name,
                   c.air_temp_c, c.water_temp_c, c.nitrate_ug_l, c.phosphate_mg_l,
                   c.ph, c.turbidity_ntu, c.dissolved_oxygen_ppm, c.dissolved_oxygen_pct,
                   c.conductivity_us_cm, c.chloride_mg_l
          HAVING COUNT(*) > 1
        ) d
        """
    )
    exact_dup_groups = cur.fetchone()[0]
    cur.execute(
        """
        SELECT COALESCE(SUM(cnt - 1), 0)
        FROM (
          SELECT COUNT(*) AS cnt
          FROM chemical c
          JOIN visit v ON v.visit_id = c.visit_id
          JOIN site s ON s.site_id = v.site_id
          LEFT JOIN lst_method m ON m.method_id = c.method_id
          GROUP BY s.site_code, v.sample_date, m.name,
                   c.air_temp_c, c.water_temp_c, c.nitrate_ug_l, c.phosphate_mg_l,
                   c.ph, c.turbidity_ntu, c.dissolved_oxygen_ppm, c.dissolved_oxygen_pct,
                   c.conductivity_us_cm, c.chloride_mg_l
          HAVING COUNT(*) > 1
        ) d
        """
    )
    exact_dup_excess = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT visit_id
          FROM chemical
          GROUP BY visit_id
          HAVING COUNT(DISTINCT (
            air_temp_c, water_temp_c, nitrate_ug_l, phosphate_mg_l, ph,
            turbidity_ntu, dissolved_oxygen_ppm, dissolved_oxygen_pct,
            conductivity_us_cm, chloride_mg_l
          )) > 1
        ) x
        """
    )
    differing_multi = cur.fetchone()[0]

    cur.execute(
        """
        SELECT COALESCE(m.name, '(NULL)'), COUNT(*)
        FROM chemical c
        LEFT JOIN lst_method m ON m.method_id = c.method_id
        GROUP BY 1 ORDER BY 2 DESC
        """
    )
    methods = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute(
        """
        SELECT COALESCE(dc.code, '(NULL)'), COUNT(*)
        FROM chemical c
        LEFT JOIN data_condition dc ON dc.data_condition_id = c.data_condition_id
        GROUP BY 1 ORDER BY 2 DESC
        """
    )
    conditions = {r[0]: r[1] for r in cur.fetchall()}

    report["final_db"] = {
        "chemical_row_count": chem_count,
        "visits_with_chemistry": visits_with_chem,
        "exact_duplicate_groups": exact_dup_groups,
        "exact_duplicate_excess_rows": exact_dup_excess,
        "visits_with_differing_packages": differing_multi,
        "per_field_non_null": non_null,
        "method_distribution": methods,
        "data_condition_distribution": conditions,
    }
    return report
