"""Staff sign-in (page + session, and HTTP Basic for scripts) and the macro
recalculation guard. No database needed.

Run from the repo root:  python -m pytest dashboard/test_staff_auth.py
"""
from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from flask import Flask

from staff_auth import _safe_next, register_staff_auth

ENV = {"STAFF_PASSWORD": "s3cret", "STAFF_USERNAME": "staff", "SECRET_KEY": "test-key"}


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _app():
    app = Flask(__name__, template_folder=str(HERE / "templates"))
    register_staff_auth(app)

    @app.route("/health")
    def health():
        return "ok"

    @app.route("/")
    def index():
        return "home"

    @app.route("/sites")
    def sites():
        return "sites page"

    @app.route("/api/volunteers")
    def volunteers():
        return "private"

    @app.route("/export/csv")
    def export_csv():
        return "a,b"

    return app


class SignedOutTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.client = _app().test_client()

    def tearDown(self):
        self.env.stop()

    def test_pages_redirect_to_sign_in_with_next(self):
        r = self.client.get("/sites?site=CL2")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login?next=", r.headers["Location"])
        self.assertIn("sites", r.headers["Location"])

    def test_api_and_exports_get_401_not_redirect(self):
        r = self.client.get("/api/volunteers")
        self.assertEqual(r.status_code, 401)
        self.assertNotIn(b"private", r.data)
        self.assertEqual(self.client.get("/export/csv").status_code, 401)

    def test_posts_are_blocked(self):
        self.assertEqual(self.client.post("/sites").status_code, 401)

    def test_open_paths(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Sign in", r.data)

    def test_basic_auth_still_works_for_scripts(self):
        self.assertEqual(self.client.get("/api/volunteers", headers=_basic("staff", "s3cret")).status_code, 200)
        self.assertEqual(self.client.get("/api/volunteers", headers=_basic("staff", "nope")).status_code, 401)


class SignInFlowTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.client = _app().test_client()

    def tearDown(self):
        self.env.stop()

    def test_wrong_password_rejected(self):
        with patch("staff_auth.time.sleep"):
            r = self.client.post("/login", data={"username": "staff", "password": "wrong"})
        self.assertEqual(r.status_code, 401)
        self.assertIn(b"password didn&#39;t match", r.data)
        self.assertEqual(self.client.get("/sites").status_code, 302)

    def test_wrong_username_rejected(self):
        with patch("staff_auth.time.sleep"):
            r = self.client.post("/login", data={"username": "admin", "password": "s3cret"})
        self.assertEqual(r.status_code, 401)

    def test_sign_in_then_browse_then_sign_out(self):
        r = self.client.post("/login", data={"username": "staff", "password": "s3cret", "next": "/sites"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/sites"))
        self.assertEqual(self.client.get("/sites").data, b"sites page")
        self.assertEqual(self.client.get("/api/volunteers").status_code, 200)
        self.client.get("/logout")
        self.assertEqual(self.client.get("/sites").status_code, 302)
        self.assertEqual(self.client.get("/api/volunteers").status_code, 401)

    def test_changing_password_ends_sessions(self):
        self.client.post("/login", data={"username": "staff", "password": "s3cret"})
        self.assertEqual(self.client.get("/sites").status_code, 200)
        with patch.dict(os.environ, {"STAFF_PASSWORD": "new-password"}):
            self.assertEqual(self.client.get("/sites").status_code, 302)

    def test_session_cookie_is_httponly(self):
        r = self.client.post("/login", data={"username": "staff", "password": "s3cret"})
        cookie = r.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)


class SafeNextTest(unittest.TestCase):
    def test_only_same_site_paths(self):
        self.assertEqual(_safe_next("/sites?x=1"), "/sites?x=1")
        self.assertEqual(_safe_next("https://evil.example/"), "/")
        self.assertEqual(_safe_next("//evil.example/"), "/")
        self.assertEqual(_safe_next("sites"), "/")
        self.assertEqual(_safe_next(None), "/")


class NoPasswordConfiguredTest(unittest.TestCase):
    def test_open_when_unset_or_blank(self):
        for value in (None, "   "):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("STAFF_PASSWORD", None)
                if value is not None:
                    os.environ["STAFF_PASSWORD"] = value
                client = _app().test_client()
                self.assertEqual(client.get("/api/volunteers").status_code, 200)
                self.assertEqual(client.get("/sites").status_code, 200)


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
