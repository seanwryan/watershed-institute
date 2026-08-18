#!/usr/bin/env python3
"""
Access-mode safety checks: route classification, read-only writes, public demo privacy.

Does not insert or modify PostgreSQL data.

Run:
  DATABASE_URL=postgresql://localhost/streamwatch_demo python -m dashboard.test_access_modes
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.public_demo import STAFF_ONLY_ENDPOINTS, is_public_demo_mode
from dashboard.read_only import PREVIEW_POST_ENDPOINTS, WRITE_ENDPOINTS, is_read_only_mode
from dashboard.route_classification import mutating_routes, verify_route_classification
from etl.db import get_conn

BASELINE_COUNTS = {
    "site": 168,
    "visit": 17221,
    "chemical": 17313,
    "bacteria": 544,
    "volunteer": 428,
    "equipment": 25,
    "bug_count": 1301,
    "result_flag": 40,
}


def _table_counts(cur):
    out = {}
    for table in BASELINE_COUNTS:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


def _load_app():
    from dashboard.app import app

    return app


def _clear_modes():
    os.environ.pop("READ_ONLY_MODE", None)
    os.environ.pop("PUBLIC_DEMO_MODE", None)


def _set_modes(*, read_only=False, public_demo=False):
    _clear_modes()
    if read_only:
        os.environ["READ_ONLY_MODE"] = "true"
    if public_demo:
        os.environ["PUBLIC_DEMO_MODE"] = "true"


def test_config_parsers():
    for raw in ("true", "1", "yes", "on", "TRUE"):
        os.environ["READ_ONLY_MODE"] = raw
        assert is_read_only_mode()
        os.environ["PUBLIC_DEMO_MODE"] = raw
        assert is_public_demo_mode()
    os.environ["READ_ONLY_MODE"] = "false"
    os.environ["PUBLIC_DEMO_MODE"] = "false"
    assert not is_read_only_mode()
    assert not is_public_demo_mode()
    _clear_modes()


def test_route_classification_complete():
    app = _load_app()
    routes = verify_route_classification(app)
    assert len(routes) == len(PREVIEW_POST_ENDPOINTS) + len(WRITE_ENDPOINTS)
    assert len(WRITE_ENDPOINTS) == 20
    assert len(PREVIEW_POST_ENDPOINTS) == 3
    assert not (WRITE_ENDPOINTS & PREVIEW_POST_ENDPOINTS)
    return routes


def test_read_only_blocks_writes():
    _set_modes(read_only=True)
    app = _load_app()
    client = app.test_client()

    with get_conn() as conn:
        before = _table_counts(conn.cursor())

    posts = [
        ("/sites/new", {"site_code": "ZZZ_RO"}),
        ("/volunteers/new", {"first_name": "X", "last_name": "Y"}),
        ("/visits/1/edit", {"sample_date": "2020-01-01"}),
    ]
    for path, data in posts:
        assert client.post(path, data=data).status_code == 403

    for path in ("/sites/new", "/volunteers/new"):
        assert client.get(path).status_code == 403

    for path in ("/imports/bact/preview", "/imports/hab/preview", "/reports/bact/preview"):
        assert client.post(path, data={}).status_code != 403

    with get_conn() as conn:
        after = _table_counts(conn.cursor())
    assert before == after == BASELINE_COUNTS


def test_public_demo_blocks_staff_routes():
    _set_modes(public_demo=True)
    app = _load_app()
    client = app.test_client()

    blocked = [
        "/volunteers",
        "/volunteers/1",
        "/api/volunteers",
        "/api/volunteers/1",
        "/equipment",
        "/api/equipment",
        "/reports/training",
        "/reports/training.csv",
        "/reports/assignments",
        "/reports/assignments.csv",
    ]
    for path in blocked:
        resp = client.get(path)
        assert resp.status_code == 404, f"{path} -> {resp.status_code}"

    allowed = ["/", "/sites", "/reports", "/reports/sites", "/export", "/explore"]
    for path in allowed:
        resp = client.get(path)
        assert resp.status_code in (200, 503), f"{path} -> {resp.status_code}"


def test_public_demo_plus_read_only():
    _set_modes(read_only=True, public_demo=True)
    app = _load_app()
    client = app.test_client()

    with get_conn() as conn:
        before = _table_counts(conn.cursor())

    assert client.post("/sites/new", data={"site_code": "ZZZ"}).status_code == 403
    assert client.get("/volunteers").status_code == 404
    assert client.get("/sites").status_code in (200, 503)

    with get_conn() as conn:
        after = _table_counts(conn.cursor())
    assert before == after == BASELINE_COUNTS


def test_private_read_only_allows_staff_browse():
    _set_modes(read_only=True, public_demo=False)
    app = _load_app()
    client = app.test_client()

    assert client.get("/volunteers").status_code in (200, 503)
    assert client.get("/equipment").status_code in (200, 503)
    assert client.post("/volunteers/new", data={"first_name": "A", "last_name": "B"}).status_code == 403


def test_normal_mode():
    _set_modes(read_only=False, public_demo=False)
    app = _load_app()
    client = app.test_client()

    assert client.get("/sites/new").status_code == 200
    assert client.get("/volunteers").status_code in (200, 503)
    assert client.get("/api/volunteers").status_code in (200, 503)


def test_staff_only_registry_subset_of_app():
    app = _load_app()
    registered = {rule.endpoint for rule in app.url_map.iter_rules()}
    missing = STAFF_ONLY_ENDPOINTS - registered
    assert not missing, f"STAFF_ONLY_ENDPOINTS not registered: {sorted(missing)}"


def main():
    os.environ.setdefault("DATABASE_URL", "postgresql://localhost/streamwatch_demo")
    routes = test_route_classification_complete()
    print("MUTATING_ROUTES", len(routes))
    for ep, methods, rule in routes:
        kind = "WRITE" if ep in WRITE_ENDPOINTS else "PREVIEW"
        print(f"  {kind}\t{ep}\t{sorted(methods)}\t{rule}")
    test_config_parsers()
    test_read_only_blocks_writes()
    test_public_demo_blocks_staff_routes()
    test_public_demo_plus_read_only()
    test_private_read_only_allows_staff_browse()
    test_normal_mode()
    test_staff_only_registry_subset_of_app()
    print("ACCESS_MODES_OK", BASELINE_COUNTS)


if __name__ == "__main__":
    main()
