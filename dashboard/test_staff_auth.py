"""Staff sign-in and macro recalculation guard. No database needed.

Run from the repo root:  python -m unittest dashboard.test_staff_auth
"""
from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask

from staff_auth import register_staff_auth


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _app():
    app = Flask(__name__)
    register_staff_auth(app)

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/api/volunteers")
    def volunteers():
        return "private"

    return app


class StaffAuthTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"STAFF_PASSWORD": "s3cret", "STAFF_USERNAME": "staff"})
        self.env.start()
        self.client = _app().test_client()

    def tearDown(self):
        self.env.stop()

    def test_blocks_without_credentials(self):
        r = self.client.get("/api/volunteers")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Basic", r.headers["WWW-Authenticate"])
        self.assertNotIn(b"private", r.data)

    def test_blocks_wrong_password_and_user(self):
        self.assertEqual(self.client.get("/api/volunteers", headers=_basic("staff", "nope")).status_code, 401)
        self.assertEqual(self.client.get("/api/volunteers", headers=_basic("other", "s3cret")).status_code, 401)

    def test_allows_correct_credentials(self):
        r = self.client.get("/api/volunteers", headers=_basic("staff", "s3cret"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, b"private")

    def test_health_stays_open(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_blocks_writes_too(self):
        self.assertEqual(self.client.post("/api/volunteers").status_code, 401)


class NoPasswordConfiguredTest(unittest.TestCase):
    def test_open_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STAFF_PASSWORD", None)
            client = _app().test_client()
            self.assertEqual(client.get("/api/volunteers").status_code, 200)

    def test_blank_password_counts_as_unset(self):
        with patch.dict(os.environ, {"STAFF_PASSWORD": "   "}):
            self.assertEqual(_app().test_client().get("/api/volunteers").status_code, 200)


class MacroRecalcGuardTest(unittest.TestCase):
    def test_recalc_off_by_default_and_on_when_enabled(self):
        try:
            import app as dashboard_app
        except Exception as exc:  # pragma: no cover - environment without app deps
            self.skipTest(f"dashboard app not importable: {exc}")
        with patch.object(dashboard_app, "calculate_visit_indices", return_value=True) as calc:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MACRO_AUTO_RECALC", None)
                self.assertFalse(dashboard_app._recalc_visit_macro(object(), 1))
                calc.assert_not_called()
            with patch.dict(os.environ, {"MACRO_AUTO_RECALC": "true"}):
                self.assertTrue(dashboard_app._recalc_visit_macro(object(), 1))
                calc.assert_called_once()


if __name__ == "__main__":
    unittest.main()
