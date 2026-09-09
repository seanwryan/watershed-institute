#!/usr/bin/env python3
"""Focused checks for shared table enhancement behavior."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_table_enhance_asset():
    js = Path("dashboard/static/js/table_enhance.js").read_text(encoding="utf-8")
    assert "StreamWatchTables" in js
    assert "compareValues" in js or "function compareValues" in js or "compare:" in js
    assert "data-enhance" in js


def test_key_pages_include_enhance():
    from dashboard.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    pages = [
        "/methods",
        "/sites",
        "/qa",
        "/scores",
        "/reports/sites",
        "/reports/visits",
        "/reports/completeness",
        "/reports/results",
        "/reports/training",
        "/reports/assignments",
    ]
    for path in pages:
        resp = client.get(path)
        assert resp.status_code == 200, path
        body = resp.get_data(as_text=True)
        assert "/static/js/table_enhance.js" in body, path
        if path.startswith("/reports/") or path in ("/qa", "/scores"):
            assert 'data-enhance="table"' in body, path
        if path == "/methods":
            assert "table-sort" in body


def main():
    test_table_enhance_asset()
    test_key_pages_include_enhance()
    print("TABLE_ENHANCE_OK")


if __name__ == "__main__":
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    main()
