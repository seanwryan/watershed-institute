"""apply_qa_rules must only add flags, with nitrate compared in mg/L. No database needed."""
import inspect
import unittest

import etl.apply_qa_rules as qa


class ApplyQaRulesTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(qa.WATER_TEMP_MAX_C, 31)
        self.assertEqual(qa.NITRATE_MAX_MG_L, 10)  # 10 ppm; nitrate_ug_l holds mg/L

    def test_never_updates_results(self):
        source = inspect.getsource(qa)
        self.assertNotIn("UPDATE chemical", source)
        self.assertNotIn("SET data_condition_id", source)
        self.assertNotIn("10000", qa.EXCEEDANCE_SQL)

    def test_threshold_conditions_are_grouped(self):
        # (temp > 31 OR nitrate > 10) AND NOT EXISTS ...: both checks inside one group
        sql = " ".join(qa.EXCEEDANCE_SQL.split())
        self.assertIn("WHERE ((c.water_temp_c IS NOT NULL AND c.water_temp_c > %(temp)s) OR (c.nitrate_ug_l IS NOT NULL AND c.nitrate_ug_l > %(nitrate)s)) AND NOT EXISTS", sql)


if __name__ == "__main__":
    unittest.main()
