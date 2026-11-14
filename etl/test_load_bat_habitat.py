"""Unit tests for BAT habitat score parsing and load planning. No database needed."""
import unittest

from etl.load_bat_habitat import SCORE_COLUMNS, parse_scores, plan_rows

FULL = {h: "10.0" for h in SCORE_COLUMNS}


def rec(raw=None, visits=(), site_exists=True, row=2):
    return {
        "raw": dict(FULL if raw is None else raw),
        "visits": [{"visit_id": v} for v in visits],
        "site_exists": site_exists,
        "site_code": "SB1",
        "sample_date": "2023-05-01",
        "source_row": row,
    }


class ParseScoresTest(unittest.TestCase):
    def test_whole_number_floats_and_blanks(self):
        scores, problems = parse_scores({"1. Epifaunal Substrate": "15.0", "8. Bank Stability - LEFT": ""})
        self.assertEqual(problems, [])
        self.assertEqual(scores["epifaunal_substrate"], 15)
        self.assertIsNone(scores["bank_stability_left"])

    def test_zero_is_kept(self):
        scores, _ = parse_scores({"HIGH GRADIENT ONLY 7. Frequency of Riffles": "0.0"})
        self.assertEqual(scores["freq_riffles"], 0)

    def test_rejects_fraction_text_and_range(self):
        _, problems = parse_scores({
            "1. Epifaunal Substrate": "15.5",
            "4. Sediment Deposition": "abc",
            "8. Bank Stability - LEFT": "11",
            "5. Channel Flow Status": "21",
        })
        self.assertEqual(len(problems), 4)


class PlanRowsTest(unittest.TestCase):
    def test_loads_single_bat_visit(self):
        loads, skips = plan_rows([rec(visits=[5])], {5: (True, False)})
        self.assertEqual([(l[1]) for l in loads], [5])
        self.assertEqual(skips, [])

    def test_skip_reasons(self):
        records = [
            rec(raw={h: "" for h in SCORE_COLUMNS}, visits=[1]),  # no scores
            rec(site_exists=False),
            rec(visits=[]),
            rec(visits=[2, 3]),
            rec(visits=[4]),  # not BAT
            rec(visits=[6]),  # already has habitat
            rec(raw={**FULL, "1. Epifaunal Substrate": "99"}, visits=[7]),
        ]
        info = {1: (True, False), 4: (False, False), 6: (True, True), 7: (True, False)}
        loads, skips = plan_rows(records, info)
        self.assertEqual(loads, [])
        reasons = [r for _, r in skips]
        self.assertTrue(any(r == "no RBP scores" for r in reasons))
        self.assertTrue(any(r == "site not in database" for r in reasons))
        self.assertTrue(any(r == "no visit on that site/date" for r in reasons))
        self.assertTrue(any(r.startswith("2 visits") for r in reasons))
        self.assertTrue(any("not a BAT visit" in r for r in reasons))
        self.assertTrue(any("already has habitat" in r for r in reasons))
        self.assertTrue(any(r.startswith("invalid score") for r in reasons))

    def test_two_rows_for_same_visit_both_skipped(self):
        loads, skips = plan_rows([rec(visits=[5], row=2), rec(visits=[5], row=3)], {5: (True, False)})
        self.assertEqual(loads, [])
        self.assertEqual(len(skips), 2)


if __name__ == "__main__":
    unittest.main()
