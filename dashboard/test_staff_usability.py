"""Staff UI regressions using synthetic read-only fixtures, without PostgreSQL.

Run: python -m unittest dashboard.test_staff_usability
"""
from contextlib import ExitStack
from datetime import date
from html.parser import HTMLParser
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))


class StaffUsabilityTests(unittest.TestCase):
    def setUp(self):
        from dashboard import app as module

        self.module = module
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "READ_ONLY_MODE": "false", "PUBLIC_DEMO_MODE": "false",
        }))
        self.stack.enter_context(patch.dict(module.app.config, TESTING=True))
        self.conn = MagicMock()
        self.cursor = self.conn.cursor.return_value
        self.cursor.fetchall.return_value = []
        self.cursor.fetchone.return_value = (0,) * 8

        def select_only(sql, *args):
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)

        self.cursor.execute.side_effect = select_only
        self.stack.enter_context(patch.object(module, "get_db", return_value=self.conn))
        self.client = module.app.test_client()

    def test_report_search_scope_and_empty_state(self):
        for report in ("sites", "visits", "results", "training", "assignments", "completeness"):
            with self.subTest(report=report):
                response = self.client.get("/reports/" + report)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("Search displayed rows", html)
                self.assertIn("aria-describedby=", html)
                self.assertIn("displayed rows only", html)
                if report == "completeness":
                    self.assertIn("Summary counts do not change", html)
                else:
                    self.assertIn("not the table search or sort order", html)
                    self.assertTrue(any(link.startswith("/reports/" + report + ".csv?") for link in Links(html).links))
                if report == "results":
                    self.assertIn("Try a wider date range or choose all sites", html)
                    self.assertNotIn("Try narrowing", html)

    def test_results_csv_retains_report_filters(self):
        with patch.object(self.module.rq, "results_rows", return_value=[]) as rows:
            response = self.client.get("/reports/results?site_code=AC1&date_start=2025-01-01&date_end=2025-12-31&family=bacteria")
            self.assertEqual(response.status_code, 200)
            page_args = rows.call_args.kwargs
            link = next(link for link in Links(response.get_data(as_text=True)).links if link.startswith("/reports/results.csv?"))
            self.assertEqual(parse_qs(urlsplit(link).query)["family"], ["bacteria"])
            download = self.client.get(link)
            self.assertEqual(download.status_code, 200)
            self.assertIn("attachment", download.headers["Content-Disposition"])
            csv_args = rows.call_args.kwargs
            for key, value in {"site_code": "AC1", "date_start": date(2025, 1, 1), "date_end": date(2025, 12, 31), "family": "bacteria"}.items():
                self.assertEqual(page_args[key], value)
                self.assertEqual(csv_args[key], value)
            self.assertEqual(page_args["limit"], 400)
            self.assertIsNone(csv_args["limit"])

    def test_three_modes_preserve_staff_visibility_and_write_blocking(self):
        from dashboard.test_access_modes import test_all_write_routes_block_before_database

        # Normal mode: staff sections and write links remain visible.
        html = self.client.get("/volunteers").get_data(as_text=True)
        self.assertIn('href="/volunteers/new"', html)
        self.assertEqual(self.client.get("/equipment").status_code, 200)

        # Private read-only: all write routes refuse before connecting.
        os.environ["READ_ONLY_MODE"] = "true"
        test_all_write_routes_block_before_database()
        self.assertEqual(self.client.get("/volunteers").status_code, 200)
        self.assertNotIn('href="/volunteers/new"', self.client.get("/volunteers").get_data(as_text=True))

        # Public read-only: staff pages, APIs and CSV cannot bypass the boundary.
        os.environ["PUBLIC_DEMO_MODE"] = "true"
        for route in ("/volunteers", "/api/volunteers", "/equipment", "/api/equipment", "/reports/training", "/reports/training.csv", "/reports/assignments", "/reports/assignments.csv"):
            self.assertEqual(self.client.get(route).status_code, 404, route)
        self.assertEqual(self.client.get("/reports/sites").status_code, 200)

    def test_access_count_checks_accept_refreshed_dataset(self):
        from dashboard import test_access_modes as access

        # Updated source counts are a fixture here, not a requirement on staff data.
        counts = (168, 17736, 17604, 2920, 428, 25, 1301, 18)
        cursor = MagicMock()
        cursor.fetchone.side_effect = [(count,) for count in counts * 2]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        with patch.object(access, "get_conn") as connect:
            connect.return_value.__enter__.return_value = connection
            access.test_read_only_blocks_writes()
        self.assertEqual(cursor.execute.call_count, len(counts) * 2)

    def test_reference_and_browse_routes_still_render(self):
        for route in ("/", "/sites", "/site/AC1", "/explore", "/qa", "/reports", "/methods", "/data-pipeline", "/scores", "/imports", "/imports/bact", "/imports/hab", "/export", "/volunteers", "/equipment", "/equipment/TEST"):
            self.assertEqual(self.client.get(route).status_code, 200, route)
        html = self.client.get("/methods").get_data(as_text=True)
        self.assertIn('href="/data-pipeline"', html)
        self.assertIn('href="/methods"', html)


if __name__ == "__main__":
    unittest.main()
