#!/usr/bin/env python3
"""Focused checks for the StreamWatch Data Pipeline documentation page."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.data_pipeline_reference import (
    INTERPRETATION_NOTES,
    LINEAGE_ROWS,
    PIPELINE_SECTIONS,
    PIPELINE_SOURCE_CAVEAT,
    PIPELINE_SUBTITLE,
)


def test_reference_data_shape():
    assert PIPELINE_SUBTITLE
    assert len(PIPELINE_SECTIONS) >= 10
    ids = {s["id"] for s in PIPELINE_SECTIONS}
    required = {
        "sites",
        "visits",
        "chemistry",
        "bacteria",
        "volunteers",
        "training",
        "equipment",
        "meter-testing",
        "macro",
        "habitat",
        "bact-recon",
        "hab-recon",
        "wqx",
    }
    assert required.issubset(ids)
    statuses = {r["status"] for r in LINEAGE_ROWS}
    assert "Loaded" in statuses
    assert "Preview only" in statuses
    assert "Export only" in statuses
    assert any(
        "divided by 10" in n["body"] or "dividing by 10" in n["body"] or "÷10" in n["body"]
        for n in INTERPRETATION_NOTES
    )
    assert "Needs review" in statuses or "Partially loaded" in statuses or "Partially migrated" in statuses
    # Outdated hosted-refresh messaging must not remain in interpretation notes
    for note in INTERPRETATION_NOTES:
        blob = (note["title"] + " " + note["body"]).lower()
        assert "render" not in blob
        assert "neon" not in blob
        assert "streamwatch_demo" not in blob


def test_data_pipeline_page_route():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/data-pipeline")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Data Pipeline" in body
    assert "Extract, Transform, Load" in body
    assert "Pipeline reference" in body
    assert "Data lineage summary" in body
    assert "Current source data" in body
    assert "Authoritative source caveat" not in body
    assert "All StreamWatch Data" in body
    assert "etl/migrate_streamwatch_data.py" in body
    assert "Preview only" in body
    assert "Needs review" in body or "Partially loaded" in body or "Partially migrated" in body
    assert "divided by 10" in body or "dividing by 10" in body or "÷10" in body
    assert "streamwatch_demo" not in body
    assert "Neon" not in body
    assert "Render" not in body
    assert "controlled refresh" not in body.lower()


def test_reference_includes_source_note():
    assert "All StreamWatch Data" in PIPELINE_SOURCE_CAVEAT
    assert "streamwatch_demo" not in PIPELINE_SOURCE_CAVEAT.lower()
    assert "Render" not in PIPELINE_SOURCE_CAVEAT
    assert "Neon" not in PIPELINE_SOURCE_CAVEAT
    assert "refresh" not in PIPELINE_SOURCE_CAVEAT.lower()
    assert any("chloride" in n["title"].lower() for n in INTERPRETATION_NOTES)


def test_methods_still_ok():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/methods").status_code == 200


def main():
    test_reference_data_shape()
    test_reference_includes_source_note()
    test_data_pipeline_page_route()
    test_methods_still_ok()
    print("DATA_PIPELINE_PAGE_OK")


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    main()
