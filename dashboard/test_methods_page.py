#!/usr/bin/env python3
"""Focused checks for the StreamWatch Methods reference page."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.methods_reference import (
    ANALYSIS_EXCLUSION_NOTE,
    CHLORIDE_NOTE,
    METHOD_GROUPS,
    METHOD_ROWS,
    TIMELINE_EVENTS,
)


def test_reference_data_shape():
    assert METHOD_ROWS
    assert METHOD_GROUPS
    assert TIMELINE_EVENTS
    parameters = {row["parameter"] for row in METHOD_ROWS}
    required = {
        "Water Temperature",
        "Air Temperature",
        "pH",
        "Dissolved Oxygen",
        "Conductivity",
        "Turbidity",
        "Nitrate",
        "Phosphate",
        "Chloride",
        "E. coli",
        "Macroinvertebrate",
        "Habitat assessment",
    }
    assert required.issubset(parameters)
    group_names = {g["name"] for g in METHOD_GROUPS}
    assert {
        "CAT: Hanna",
        "CAT: LaMotte",
        "CAT: Early LaMotte",
        "BAT",
        "BACT",
        "Salt Watch",
    }.issubset(group_names)
    assert "divided by 10" in CHLORIDE_NOTE
    assert "do not apply another divide-by-10" in CHLORIDE_NOTE
    assert "Flagged" in ANALYSIS_EXCLUSION_NOTE
    assert "CAT: Early LaMotte" in ANALYSIS_EXCLUSION_NOTE
    assert any("0.2 OR 1" not in (r.get("limit") or "") for r in METHOD_ROWS)
    assert not any("0.2 OR 1" in (r.get("limit") or "") for r in METHOD_ROWS)
    assert not any("4.5 OR 10" in (r.get("limit") or "") for r in METHOD_ROWS)
    assert any("Colisure" in (r.get("equipment") or "") for r in METHOD_ROWS)
    assert any("IDEXX/Colilert" in e["event"] for e in TIMELINE_EVENTS)
    assert any("August" in e["event"] for e in TIMELINE_EVENTS)


def test_methods_page_route():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/methods")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Methods" in body
    assert "2026 Chloride Correction Note" in body
    assert "What to exclude from analysis" in body
    assert "CAT: Early LaMotte" in body
    assert "Salt Watch" in body
    assert "Historical Method &amp; Program Changes" in body
    assert "September 9, 2026" in body
    assert "Hanna: 0.00 – 14.00" in body or "Hanna: 0.00" in body
    assert "0.2 OR 1" not in body
    assert "4.5 OR 10" not in body
    assert "Colisure" in body
    assert "IDEXX/Colilert" in body


def main():
    test_reference_data_shape()
    test_methods_page_route()
    print("METHODS_PAGE_OK")


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    main()
