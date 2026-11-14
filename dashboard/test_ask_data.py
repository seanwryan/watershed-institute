"""Ask the data: question parsing, SQL safety, saving. No database needed."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from werkzeug.datastructures import MultiDict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ask_data as ad


def Q(**kw):
    md = MultiDict()
    for k, v in kw.items():
        for item in (v if isinstance(v, list) else [v]):
            md.add(k, item)
    return ad.parse_question(md)


class ParseTest(unittest.TestCase):
    def test_defaults(self):
        q = Q(ds="chemistry")
        self.assertEqual(q["mode"], "rows")
        self.assertEqual(q["cols"], ad.DATASETS["chemistry"]["default_columns"])

    def test_unknown_dataset_and_field(self):
        with self.assertRaises(ad.QuestionError):
            Q(ds="pg_authid")
        with self.assertRaises(ad.QuestionError):
            Q(ds="chemistry", f="password", o="is", v="x")

    def test_operator_must_fit_field_type(self):
        with self.assertRaises(ad.QuestionError):
            Q(ds="chemistry", f="chloride", o="contains", v="1")

    def test_columns_ordered_and_deduped(self):
        q = Q(ds="ecoli", col=["limit_note", "site", "site", "e_coli"])
        self.assertEqual(q["cols"], ["site", "e_coli", "limit_note"])

    def test_measures_only_numeric(self):
        q = Q(ds="chemistry", mode="summary", group="site", m=["avg:chloride", "avg:site", "drop:chloride", "count:*"])
        self.assertEqual(q["measures"], [("avg", "chloride"), ("count", "*")])

    def test_summary_defaults_to_count(self):
        self.assertEqual(Q(ds="visits", mode="summary", group="year")["measures"], [("count", "*")])

    def test_group_only_groupable_fields(self):
        q = Q(ds="chemistry", mode="summary", group=["chloride", "year", "site", "method"])
        self.assertEqual(q["groups"], ["year", "site"])


class SqlTest(unittest.TestCase):
    def test_values_are_bound_not_inlined(self):
        q = Q(ds="chemistry", f=["site", "chloride"], o=["is", "gt"], v=["CL2'; DROP TABLE site;--", "100"])
        sql, params, cols = ad.build_sql(q)
        self.assertNotIn("DROP", sql)
        self.assertIn("CL2'; DROP TABLE site;--", params)
        self.assertIn(100.0, params)

    def test_number_and_date_validation(self):
        with self.assertRaises(ad.QuestionError):
            ad.build_sql(Q(ds="chemistry", f="chloride", o="gt", v="lots"))
        with self.assertRaises(ad.QuestionError):
            ad.build_sql(Q(ds="chemistry", f="date", o="after", v="last week"))

    def test_between_and_in(self):
        q = Q(ds="chemistry", f=["date", "site"], o=["between", "in"], v=["2024-01-01", "CL2, SB10"], v2=["2024-12-31", ""])
        sql, params, _ = ad.build_sql(q)
        self.assertIn("BETWEEN %s AND %s", sql)
        self.assertIn(["CL2", "SB10"], params)

    def test_sort_injection_ignored(self):
        q = Q(ds="chemistry", sort='chloride" DESC; DROP TABLE site;--')
        sql, _, _ = ad.build_sql(q)
        self.assertNotIn("DROP", sql)

    def test_like_escaping(self):
        sql, params, _ = ad.build_sql(Q(ds="visits", f="notes", o="contains", v="100%_x"))
        self.assertIn(r"%100\%\_x%", params)

    def test_summary_sql(self):
        q = Q(ds="chemistry", mode="summary", group=["year", "site"], m=["avg:chloride", "count:*"])
        sql, params, cols = ad.build_sql(q)
        self.assertIn("GROUP BY 1, 2", sql)
        self.assertEqual([c[0] for c in cols], ["year", "site", "avg__chloride", "count__rows"])

    def test_every_dataset_builds(self):
        for key, ds in ad.DATASETS.items():
            sql, _, cols = ad.build_sql(Q(ds=key))
            self.assertTrue(sql.startswith("SELECT"), key)
            for col in ds["default_columns"]:
                self.assertIn(col, ds["fields"], key)

    def test_question_round_trips_through_url(self):
        q = Q(ds="chemistry", mode="summary", f="chloride", o="gt", v="100", group="year", m="avg:chloride", sort="year", dir="desc")
        again = ad.parse_question(MultiDict(ad.question_args(q)))
        for k in ("ds", "mode", "filters", "groups", "measures", "sort", "desc"):
            self.assertEqual(q[k], again[k], k)


class ChartTest(unittest.TestCase):
    def test_time_series_is_line(self):
        q = Q(ds="chemistry", mode="summary", group="year", m="avg:chloride")
        _, _, cols = ad.build_sql(q)
        spec = ad.chart_spec(q, cols, [{"year": 2023, "avg__chloride": 40}, {"year": 2022, "avg__chloride": 50}])
        self.assertEqual(spec["type"], "line")
        self.assertEqual(spec["labels"], ["2022", "2023"])

    def test_rows_have_no_chart(self):
        q = Q(ds="chemistry")
        self.assertIsNone(ad.chart_spec(q, [], [{"site": "CL2"}]))


class SaveTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("STAFF_PASSWORD", None)
        os.environ.pop("READ_ONLY_MODE", None)
        os.environ.pop("PUBLIC_DEMO_MODE", None)
        from flask import Flask
        self.app = Flask(__name__, template_folder=str(HERE / "templates"))
        self.app.secret_key = "test"
        self.conn = MagicMock()
        self.cur = self.conn.cursor.return_value.__enter__.return_value
        ad.register(self.app, lambda: self.conn, str)
        self.client = self.app.test_client()

    def _csrf(self):
        with self.client.session_transaction() as s:
            s["ask_csrf"] = "tok"
        return "tok"

    def test_save_requires_csrf(self):
        r = self.client.post("/data/ask/save", data={"name": "x", "query": "ds=chemistry"})
        self.assertEqual(r.status_code, 400)
        self.cur.execute.assert_not_called()

    def test_save_valid_question(self):
        tok = self._csrf()
        r = self.client.post("/data/ask/save", data={"csrf": tok, "name": "High chloride", "query": "ds=chemistry&f=chloride&o=gt&v=100"})
        self.assertEqual(r.status_code, 302)
        sql, params = self.cur.execute.call_args[0]
        self.assertTrue(sql.startswith("INSERT INTO saved_question"))
        self.assertEqual(params[0], "High chloride")

    def test_invalid_question_not_saved(self):
        tok = self._csrf()
        r = self.client.post("/data/ask/save", data={"csrf": tok, "name": "Bad", "query": "ds=chemistry&f=password&o=is&v=x"})
        self.assertEqual(r.status_code, 400)
        self.cur.execute.assert_not_called()

    def test_delete_never_removes_starters(self):
        tok = self._csrf()
        self.client.post("/data/ask/saved/3/delete", data={"csrf": tok})
        sql, params = self.cur.execute.call_args[0]
        self.assertIn("AND NOT is_starter", sql)


if __name__ == "__main__":
    unittest.main()
