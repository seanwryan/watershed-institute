"""Shared helpers for Explore time-series date bounds and chart threshold display."""

from __future__ import annotations

EXPLORE_PARAMETERS = frozenset(
    {
        "water_temp_c",
        "nitrate_ug_l",
        "phosphate_mg_l",
        "ph",
        "turbidity_ntu",
        "dissolved_oxygen_ppm",
        "chloride_mg_l",
        "e_coli_mpn_100ml",
    }
)

# Threshold is drawn only when it is at most this many times the observed maximum.
THRESHOLD_AXIS_MULTIPLIER = 3.0


def normalize_explore_parameter(parameter: str | None, default: str = "water_temp_c") -> str:
    if parameter in EXPLORE_PARAMETERS:
        return parameter
    return default


def fetch_time_series_date_bounds(cur, site_codes: list[str], parameter: str) -> dict[str, str | None]:
    """
    Return earliest/latest sample_date where parameter is non-null for the given site(s).
    For multiple sites, spans the union of each site's available range.
    """
    parameter = normalize_explore_parameter(parameter)
    mins: list[str] = []
    maxs: list[str] = []
    for site_code in site_codes:
        if "e_coli" in parameter:
            cur.execute(
                """
                SELECT MIN(v.sample_date)::text, MAX(v.sample_date)::text
                FROM visit v
                JOIN site s ON s.site_id = v.site_id
                JOIN bacteria b ON b.visit_id = v.visit_id
                WHERE s.site_code = %s AND b.e_coli_mpn_100ml IS NOT NULL
                """,
                (site_code,),
            )
        else:
            cur.execute(
                f"""
                SELECT MIN(v.sample_date)::text, MAX(v.sample_date)::text
                FROM visit v
                JOIN site s ON s.site_id = v.site_id
                JOIN chemical c ON c.visit_id = v.visit_id
                WHERE s.site_code = %s AND c.{parameter} IS NOT NULL
                """,
                (site_code,),
            )
        row = cur.fetchone()
        if row and row[0] is not None and row[1] is not None:
            mins.append(row[0])
            maxs.append(row[1])
    if not mins:
        return {"date_start": None, "date_end": None}
    return {"date_start": min(mins), "date_end": max(maxs)}


def threshold_line_visible(data_max: float | None, threshold: float | None, multiplier: float = THRESHOLD_AXIS_MULTIPLIER) -> bool:
    """True when the reference threshold is close enough to observed data to draw on-chart."""
    if threshold is None or data_max is None:
        return False
    if data_max <= 0:
        return threshold <= 0
    return threshold <= data_max * multiplier
