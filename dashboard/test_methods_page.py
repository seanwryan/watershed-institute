#!/usr/bin/env python3
"""Focused checks for the StreamWatch Methods reference page."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.methods_reference import CHLORIDE_NOTE, METHOD_ROWS, TIMELINE_EVENTS


def test_reference_data_shape():
    assert METHOD_ROWS
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
        "Chloride - High",
        "Nitrite",
        "Phosphorous / Phosphorus",
        "Total Nitrogen",
        "E. coli",
        "Macroinvertebrate",
        "Macroinvertebrate QC",
        "Bug Count",
        "Habitat assessment",
    }
    assert required.issubset(parameters)
    assert "divided by 10" in CHLORIDE_NOTE


def test_methods_page_route():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/methods")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Methods" in body
    assert "2026 Chloride Correction Note" in body
    assert "Historical Method &amp; Program Changes" in body
    assert "Sample-Routine" in body
    assert "Coliscan Easygel" in body


def main():
    test_reference_data_shape()
    test_methods_page_route()
    print("METHODS_PAGE_OK")


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    main()
