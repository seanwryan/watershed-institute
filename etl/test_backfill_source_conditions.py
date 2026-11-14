"""Matching rules for the compound Data Condition backfill. No database needed."""
from decimal import Decimal
import unittest

from etl.backfill_source_conditions import is_compound, normalize_condition, same_values


class ConditionTextTest(unittest.TestCase):
    def test_is_compound(self):
        self.assertTrue(is_compound("Outlier; Incomplete"))
        self.assertTrue(is_compound("Outlier,Incomplete"))
        self.assertFalse(is_compound("Provisional"))
        self.assertFalse(is_compound(None))

    def test_normalize_keeps_order_and_words(self):
        self.assertEqual(normalize_condition("Minor Deviation;Outlier ; Incomplete"), "Minor Deviation; Outlier; Incomplete")
        self.assertEqual(normalize_condition("Corrected, Outlier"), "Corrected; Outlier")


class SameValuesTest(unittest.TestCase):
    def test_matches_at_stored_precision(self):
        stored = {"nitrate_ug_l": Decimal("0.2871"), "ph": Decimal("7.10")}
        self.assertTrue(same_values(stored, {"nitrate_ug_l": 0.287126, "ph": 7.1}))

    def test_rejects_real_difference(self):
        self.assertFalse(same_values({"ph": Decimal("7.10")}, {"ph": 7.2}))

    def test_rejects_value_present_on_one_side_only(self):
        self.assertFalse(same_values({"ph": Decimal("7.10"), "chloride_mg_l": None}, {"ph": 7.1, "chloride_mg_l": 30.0}))

    def test_zero_is_a_value(self):
        self.assertTrue(same_values({"nitrate_ug_l": Decimal("0.0000")}, {"nitrate_ug_l": 0.0}))
        self.assertFalse(same_values({"nitrate_ug_l": None}, {"nitrate_ug_l": 0.0}))


if __name__ == "__main__":
    unittest.main()
