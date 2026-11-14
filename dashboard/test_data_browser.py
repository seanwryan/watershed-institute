"""Data browser: catalog integrity and query safety. No database needed."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import data_browser as db


def fake_schema():
    s = db.Schema()
    s.columns = {
        "visit": [("visit_id", "integer"), ("site_id", "integer"), ("sample_date", "date"),
                  ("method_id", "integer"), ("notes", "text"), ("created_at", "timestamp")],
        "volunteer": [("volunteer_id", "integer"), ("first_name", "text"), ("last_name", "text"),
                      ("email", "text"), ("phone", "text"), ("address", "text"), ("zip_code", "text"),
                      ("alt_email", "text"), ("alt_phone", "text"), ("perfect_id", "text"), ("status", "USER-DEFINED")],
        "chemical": [("chemical_id", "integer"), ("visit_id", "integer"), ("nitrate_ug_l", "numeric")],
        "source_import": [("import_id", "uuid"), ("original_workbook", "bytea")],
        "site": [("site_id", "integer"), ("site_code", "text")],
    }
    s.pk = {"visit": "visit_id", "volunteer": "volunteer_id", "chemical": "chemical_id", "site": "site_id"}
    s.fks = {"visit": {"site_id": "site", "method_id": "lst_method"}, "chemical": {"visit_id": "visit"}}
    s.loaded_at = 1e18
    return s


class CatalogTest(unittest.TestCase):
    def test_every_table_has_a_known_group(self):
        keys = {g[0] for g in db.GROUPS}
        for name, info in db.CATALOG.items():
            self.assertIn(info["group"], keys, name)
            self.assertTrue(info["label"] and info["row"], name)

    def test_identifiers_are_safe(self):
        for name in list(db.CATALOG) + list(db.LINK_LABEL):
            self.assertRegex(name, r"^[a-z_][a-z0-9_]*$")

    def test_related_and_map_point_at_catalog_tables(self):
        for name, info in db.CATALOG.items():
            for child, col, _ in info.get("related", []):
                self.assertIn(child, db.CATALOG, f"{name} -> {child}")
        for t in db.MAP_NODES:
            self.assertIn(t, db.CATALOG)
        for a, b, _ in db.MAP_EDGES:
            self.assertIn(a, db.MAP_NODES)
            self.assertIn(b, db.MAP_NODES)

    def test_source_ledger_tables_not_browsable(self):
        for t in ("source_import", "source_observation", "source_review"):
            self.assertNotIn(t, db.CATALOG)


class LabelsTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(db.column_label("nitrate_ug_l"), "Nitrate (mg/L as N)")
        self.assertEqual(db.column_label("site_id", "site"), "Site")
        self.assertEqual(db.column_label("bact_priority_id", "lst_priority"), "BACT priority")
        self.assertEqual(db.column_label("partner_id", "volunteer"), "Partner")
        self.assertEqual(db.column_label("sample_code"), "Sample code")


class QueryTest(unittest.TestCase):
    def setUp(self):
        self.s = fake_schema()

    def test_volunteer_contact_details_hidden(self):
        cols = self.s.visible_columns("volunteer")
        for c in ("email", "phone", "address", "zip_code", "alt_email", "alt_phone", "perfect_id"):
            self.assertNotIn(c, cols)
        self.assertIn("last_name", cols)

    def test_timestamps_hidden(self):
        self.assertNotIn("created_at", self.s.visible_columns("visit"))

    def test_sort_only_real_columns(self):
        cols = self.s.visible_columns("visit")
        self.assertEqual(db.sort_spec("-sample_date", cols, None, "visit_id"), ("sample_date", True))
        self.assertEqual(db.sort_spec("x; DROP TABLE visit", cols, "-sample_date", "visit_id"), ("sample_date", True))

    def test_filters_bind_values_and_ignore_junk(self):
        sql, params, meta, sort_col, desc = db.build_query("visit", self.s, {"site_id": "5", "method_id": "1 OR 1=1", "site": "CL2"})
        self.assertIn('"site_id" = %s', sql)
        self.assertNotIn("1 OR 1=1", sql)
        self.assertEqual(params, [5, "CL2"])
        self.assertNotIn("CL2", sql)
        self.assertIn(f"FROM \"visit\" {db.ROW}", sql)

    def test_links_get_readable_names(self):
        sql, *_ = db.build_query("chemical", self.s, {})
        self.assertIn('AS "visit_id__label"', sql)
        self.assertIn(f'v.visit_id = {db.ROW}."visit_id"', sql)

    def test_unknown_table_rejected(self):
        with self.assertRaises(KeyError):
            db.build_query("pg_authid", self.s, {})

    def test_format_value(self):
        from decimal import Decimal
        self.assertEqual(db.format_value(Decimal("0.2000")), "0.2")
        self.assertEqual(db.format_value(Decimal("12.00")), "12")
        self.assertEqual(db.format_value(True), "Yes")
        self.assertEqual(db.format_value(None), "")


if __name__ == "__main__":
    unittest.main()
