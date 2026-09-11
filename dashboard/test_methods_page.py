#!/usr/bin/env python3
"""Focused checks for the StreamWatch Methods reference page."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.methods_reference import (
    ANALYSIS_EXCLUSION_BULLETS,
    ANALYSIS_EXCLUSION_NOTE,
    CHLORIDE_BULLETS,
    CHLORIDE_NOTE,
    METHOD_GROUPS,
    METHOD_ROWS,
    PROGRAM_SUMMARIES,
    SOURCE_LINE,
    TIMELINE_EVENTS,
)


def test_reference_data_shape():
    assert METHOD_ROWS
    assert METHOD_GROUPS
    assert TIMELINE_EVENTS
    assert len(PROGRAM_SUMMARIES) == 3
    assert {p["name"] for p in PROGRAM_SUMMARIES} == {"CAT", "BACT", "BAT"}
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
    assert len(ANALYSIS_EXCLUSION_BULLETS) == 3
    assert any("Flagged" in b for b in ANALYSIS_EXCLUSION_BULLETS)
    assert any("?" in b for b in ANALYSIS_EXCLUSION_BULLETS)
    assert any("Early LaMotte" in b for b in ANALYSIS_EXCLUSION_BULLETS)
    assert len(CHLORIDE_BULLETS) == 2
    assert any("2026" in b for b in CHLORIDE_BULLETS)
    assert any("10" in b for b in CHLORIDE_BULLETS)
    assert "Flagged" in ANALYSIS_EXCLUSION_NOTE
    assert "10" in CHLORIDE_NOTE
    assert "September 9, 2026" in SOURCE_LINE
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
    assert "Analysis notes" in body
    assert "Chloride correction" in body
    assert "Exclude Flagged records" in body
    assert "CAT: Early LaMotte" in body
    assert "Salt Watch" in body
    assert "Historical method" in body or "Historical Method" in body
    assert "September 9, 2026" in body
    assert "Hanna: 0.00 – 14.00" in body or "Hanna: 0.00" in body
    assert "0.2 OR 1" not in body
    assert "4.5 OR 10" not in body
    assert "Colisure" in body
    assert "IDEXX/Colilert" in body
    # Compact page: no long interpretation dump / deployment jargon
    assert "Source &amp; Interpretation Notes" not in body
    assert "database alignment" not in body
    assert "streamwatch_demo" not in body
    assert "Neon" not in body
    assert "Render" not in body
    # Filters / table still present
    assert 'id="methods-search"' in body
    assert 'id="methods-table"' in body


def main():
    test_reference_data_shape()
    test_methods_page_route()
    print("METHODS_PAGE_OK")


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    main()
