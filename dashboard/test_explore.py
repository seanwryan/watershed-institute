#!/usr/bin/env python3
"""
Explore page helpers and date-bounds API checks.

Run:
  DATABASE_URL=postgresql://localhost/streamwatch_demo python -m dashboard.test_explore
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.explore_helpers import (
    THRESHOLD_AXIS_MULTIPLIER,
    fetch_time_series_date_bounds,
    normalize_explore_parameter,
    threshold_line_visible,
)
from etl.db import get_conn


def test_normalize_explore_parameter():
    assert normalize_explore_parameter("nitrate_ug_l") == "nitrate_ug_l"
    assert normalize_explore_parameter("bad_param") == "water_temp_c"
    assert normalize_explore_parameter(None) == "water_temp_c"


def test_threshold_line_visible():
    assert threshold_line_visible(500, 10000) is False
    assert threshold_line_visible(4000, 10000) is True
    assert threshold_line_visible(25, 31) is True
    assert threshold_line_visible(80, 235) is True
    assert threshold_line_visible(70, 235) is False
    assert threshold_line_visible(None, 235) is False
    assert threshold_line_visible(10, None) is False
    assert THRESHOLD_AXIS_MULTIPLIER == 3.0


def test_time_series_bounds_api():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/api/time_series_bounds")
    assert resp.status_code == 400

    resp = client.get("/api/time_series_bounds?site_code=ZZZZ&parameter=nitrate_ug_l")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["date_start"] is None
    assert payload["date_end"] is None


def test_time_series_bounds_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT s.site_code
            FROM site s
            JOIN visit v ON v.site_id = s.site_id
            JOIN chemical c ON c.visit_id = v.visit_id
            WHERE c.nitrate_ug_l IS NOT NULL
            ORDER BY v.sample_date
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            print("SKIP bounds DB detail: no nitrate rows")
            return
        site_code = row[0]
        bounds = fetch_time_series_date_bounds(cur, [site_code], "nitrate_ug_l")
        assert bounds["date_start"]
        assert bounds["date_end"]
        assert bounds["date_start"] <= bounds["date_end"]

        cur.execute(
            """
            SELECT s.site_code
            FROM site s
            JOIN visit v ON v.site_id = s.site_id
            JOIN bacteria b ON b.visit_id = v.visit_id
            WHERE b.e_coli_mpn_100ml IS NOT NULL
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row:
            e_bounds = fetch_time_series_date_bounds(cur, [row[0]], "e_coli_mpn_100ml")
            assert e_bounds["date_start"]
            assert e_bounds["date_end"]


def main():
    test_normalize_explore_parameter()
    test_threshold_line_visible()
    test_time_series_bounds_api()
    test_time_series_bounds_db()
    print("EXPLORE_TESTS_OK")


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    main()
