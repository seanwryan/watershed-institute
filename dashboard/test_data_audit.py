"""Data audit: live-check classification, query safety, audit comparison helpers. No database needed."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import data_audit as da
from etl.audit_sources import _same_at_stored_precision
from etl.backfill_source_conditions import same_values


def cursor_returning(counts):
    cur = MagicMock()
    cur.fetchone.side_effect = [(n,) for n in counts]
    return cur


class LiveChecksTest(unittest.TestCase):
    def test_checks_are_read_only_counts(self):
        for chk in da.LIVE_CHECKS:
            sql = " ".join(chk["sql"].split()).upper()
            self.assertTrue(sql.startswith("SELECT"), chk["title"])
            for word in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER "):
                self.assertNotIn(word, sql, chk["title"])

    def test_all_zero_passes(self):
        out = da.run_live_checks(cursor_returning([0] * len(da.LIVE_CHECKS)))
        self.assertTrue(all(c["status"] == "pass" for c in out))

    def test_known_problems_are_attention_and_new_ones_fail(self):
        idx = next(i for i, c in enumerate(da.LIVE_CHECKS) if c.get("known") == 61)
        counts = [0] * len(da.LIVE_CHECKS)
        counts[idx] = 61
        self.assertEqual(da.run_live_checks(cursor_returning(counts))[idx]["status"], "attention")
        counts[idx] = 62
        self.assertEqual(da.run_live_checks(cursor_returning(counts))[idx]["status"], "fail")

    def test_unknown_problem_fails(self):
        counts = [0] * len(da.LIVE_CHECKS)
        counts[0] = 1
        self.assertEqual(da.run_live_checks(cursor_returning(counts))[0]["status"], "fail")


class ComparisonTest(unittest.TestCase):
    FIELDS = ("water_temp_c", "nitrate_ug_l")

    def test_audit_separates_rounding_from_exact(self):
        stored = {"water_temp_c": Decimal("12.00"), "nitrate_ug_l": Decimal("0.2871")}
        self.assertFalse(_same_at_stored_precision(stored, {"water_temp_c": 12.002, "nitrate_ug_l": 0.287126}, self.FIELDS))
        self.assertTrue(_same_at_stored_precision(stored, {"water_temp_c": 12.0, "nitrate_ug_l": 0.287126}, self.FIELDS))

    def test_backfill_tolerates_temperature_rounding_only(self):
        stored = {"water_temp_c": Decimal("12.00"), "nitrate_ug_l": Decimal("0.2871")}
        self.assertTrue(same_values(stored, {"water_temp_c": 12.002, "nitrate_ug_l": 0.287126}))
        self.assertFalse(same_values(stored, {"water_temp_c": 12.002, "nitrate_ug_l": 0.29}))

    def test_blank_vs_value_differs(self):
        self.assertFalse(_same_at_stored_precision({"water_temp_c": Decimal("27.0")}, {"water_temp_c": None}, ("water_temp_c",)))


if __name__ == "__main__":
    unittest.main()
