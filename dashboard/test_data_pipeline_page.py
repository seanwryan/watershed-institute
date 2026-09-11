#!/usr/bin/env python3
"""Focused checks for the StreamWatch Data Pipeline documentation page."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.data_pipeline_reference import (
    ETL_DEFINITION,
    FLOW_STEPS,
    INTERPRETATION_NOTES,
    LINEAGE_ROWS,
    PIPELINE_SECTIONS,
    PIPELINE_SUBTITLE,
)


def test_reference_data_shape():
    assert PIPELINE_SUBTITLE
    assert len(FLOW_STEPS) == 4
    assert FLOW_STEPS[0].lower().startswith("source")
    assert FLOW_STEPS[-1].lower() == "website"
    assert "ETL" in ETL_DEFINITION
    assert "Extract, Transform, Load" in ETL_DEFINITION
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
    for section in PIPELINE_SECTIONS:
        assert 2 <= len(section["summary"]) <= 4
    statuses = {r["status"] for r in LINEAGE_ROWS}
    assert "Loaded" in statuses
    assert "Preview only" in statuses
    assert "Export only" in statuses
    assert any("10" in n["body"] for n in INTERPRETATION_NOTES)
    assert "Needs review" in statuses or "Partially loaded" in statuses or "Partially migrated" in statuses


def test_data_pipeline_page_route():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/data-pipeline")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Data Pipeline" in body
    assert "ETL" in body
    assert "Pipeline reference" in body
    assert "Status overview" in body or "Data lineage" in body
    assert "Source files" in body
    assert "Clean &amp; match" in body or "Clean & match" in body
    assert "etl/migrate_streamwatch_data.py" in body
    assert "Preview only" in body
    assert "Authoritative source caveat" not in body
    assert "Current source data" not in body
    assert "streamwatch_demo" not in body
    assert "Neon" not in body
    assert "Render" not in body
    assert "controlled refresh" not in body.lower()
    # Collapsed details still present
    assert "Technical details" in body
    assert "More detail" in body


def test_methods_still_ok():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/methods").status_code == 200


def main():
    test_reference_data_shape()
    test_data_pipeline_page_route()
    test_methods_still_ok()
    print("DATA_PIPELINE_PAGE_OK")


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    main()
