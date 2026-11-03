"""Preview HTTP tests using synthetic source files and a SELECT-only DB stub."""
from contextlib import ExitStack
import csv
import io
import os
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from etl import test_bat_reconcile as fixtures
from etl.bact_reconcile import source_annotations


class SeasonalPreviewTests(unittest.TestCase):
    def setUp(self):
        from dashboard import app as module

        self.source = fixtures.BatPreviewTests()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.module = module
        self.stack.enter_context(patch.dict(os.environ, {"READ_ONLY_MODE": "false", "PUBLIC_DEMO_MODE": "false"}))
        self.stack.enter_context(patch.dict(module.app.config, TESTING=True))
        self.stack.enter_context(patch.object(module, "_BACT_PREVIEW_DIR", self.source.root / "previews"))
        self.conn = fixtures.ReadOnlyConnection()
        self.conn.set_session = Mock()
        self.conn.close = Mock()
        self.connect = self.stack.enter_context(patch.object(module, "get_db", return_value=self.conn))
        self.client = module.app.test_client()

    def upload(self):
        return self.client.post("/imports/bat/preview", data={
            "bugs": (io.BytesIO(self.source.bugs.read_bytes()), "bugs.csv"),
            "habitat": (io.BytesIO(self.source.habitat.read_bytes()), "habitat.xlsx"),
        }, content_type="multipart/form-data")

    def test_preview_is_allowed_in_all_three_modes(self):
        for readonly, public in (("false", "false"), ("true", "false"), ("true", "true")):
            with self.subTest(readonly=readonly, public=public):
                os.environ.update(READ_ONLY_MODE=readonly, PUBLIC_DEMO_MODE=public)
                self.assertEqual(self.client.get("/imports/bat").status_code, 200)
                response = self.upload()
                self.assertEqual(response.status_code, 302)
                page = self.client.get(response.headers["Location"])
                self.assertEqual(page.status_code, 200)
                html = page.get_data(as_text=True)
                self.assertIn("No StreamWatch data has been changed", html)
                self.assertIn("/visits/10", html)
                self.assertIn("/visits/11", html)
                self.assertIn("habitat-2", html)
                self.assertIn("habitat-3", html)
                self.assertIn("2020-09-27", html)
                self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
                self.assertNotIn("<script>alert(1)</script>", html)
                self.assertNotIn("Confirm import", html)
        self.conn.set_session.assert_called_with(readonly=True, autocommit=True)
        self.assertEqual(self.conn.close.call_count, 3)

    def test_other_preview_routes_reject_bat_token(self):
        response = self.upload()
        token = response.headers["Location"].rsplit("/", 1)[1]
        for path in (f"/imports/bact/preview/{token}", f"/imports/bact/preview/{token}.csv", f"/imports/hab/preview/{token}"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.get("/imports/bat/preview/invalid-token").status_code, 404)

    def test_input_errors_do_not_connect(self):
        self.assertEqual(self.client.post("/imports/bat/preview", data={}).status_code, 400)
        response = self.client.post("/imports/bat/preview", data={"bugs": (io.BytesIO(b"x"), "wrong.xlsx")})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/imports/bat/preview", environ_overrides={"CONTENT_LENGTH": str(17 * 1024 * 1024)})
        self.assertEqual(response.status_code, 400)
        self.connect.assert_not_called()

    def test_database_readonly_failure_does_not_parse_or_continue(self):
        import psycopg2

        self.conn.set_session.side_effect = psycopg2.OperationalError("Synthetic failure")
        with patch.object(self.module, "preview_bat_files") as preview:
            self.assertEqual(self.upload().status_code, 503)
            preview.assert_not_called()
        self.conn.close.assert_called_once()

    def test_source_conditions_and_notes_are_preserved_in_preview_and_csv(self):
        annotations = source_annotations(pd.Series({"Data Conditions": "Outlier; Duplicate?", "Notes": "Source <note>"}))
        self.assertEqual(annotations["source_data_conditions"], "Outlier; Duplicate?")
        row = {"source": "Survey123", "source_row": 2, "status": "needs_review", "status_label": "Needs review", "detail": "Review", **annotations}
        payload = {"result": {"survey123": {"rows": [row], "summary": {}}, "idexx": {"rows": [], "summary": {}}}}
        with patch.object(self.module, "_load_bact_preview", return_value=payload):
            response = self.client.get("/imports/bact/preview/abc")
            self.assertEqual(response.status_code, 200)
            self.assertIn("Source &lt;note&gt;", response.get_data(as_text=True))
            response = self.client.get("/imports/bact/preview/abc.csv")
            self.assertEqual(response.status_code, 200)
            rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
            self.assertEqual(rows[0]["source_data_conditions"], "Outlier; Duplicate?")
            self.assertEqual(rows[0]["source_notes"], "Source <note>")
            self.assertNotIn(None, rows[0])  # CSV field alignment is unchanged.
            row["source_notes"] = "=1+1"
            response = self.client.get("/imports/bact/preview/abc.csv")
            exported = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
            self.assertEqual(exported[0]["source_notes"], "'=1+1")
            self.assertEqual(row["source_notes"], "=1+1")  # source stays unchanged


if __name__ == "__main__":
    unittest.main()
