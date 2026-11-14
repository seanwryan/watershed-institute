"""Unit tests for BAT visit-link repair planning and the BAT loader's visit matching.

No database needed.
"""
from datetime import date
import unittest

from etl.fix_bat_visit_links import Action, BioVisit, plan_actions
from etl.migrate_bat import resolve_bat_visit

D = date(2021, 10, 2)
BAT = 2


class PlanActionsTest(unittest.TestCase):
    def test_merges_into_single_uncoded_bat_visit(self):
        bio = [BioVisit(17733, 5, D, "SB1_2021-10-02")]
        self.assertEqual(
            plan_actions(bio, {(5, D): [13960]}),
            [Action("merge", 17733, 13960, "SB1_2021-10-02")],
        )

    def test_tags_when_no_bat_visit_that_day(self):
        bio = [BioVisit(1, 5, D, "X")]
        self.assertEqual(plan_actions(bio, {}), [Action("tag", 1)])

    def test_tags_when_bat_visit_ambiguous(self):
        bio = [BioVisit(1, 5, D, "X")]
        self.assertEqual(plan_actions(bio, {(5, D): [10, 11]}), [Action("tag", 1)])

    def test_tags_when_two_bio_visits_share_site_date(self):
        bio = [BioVisit(1, 5, D, "A"), BioVisit(2, 5, D, "B")]
        self.assertEqual(
            plan_actions(bio, {(5, D): [10]}),
            [Action("tag", 1), Action("tag", 2)],
        )

    def test_other_site_same_date_not_merged(self):
        bio = [BioVisit(1, 6, D, "A")]
        self.assertEqual(plan_actions(bio, {(5, D): [10]}), [Action("tag", 1)])


class FakeCursor:
    """Answers the three lookups resolve_bat_visit makes, records writes."""

    def __init__(self, exact=None, uncoded=()):
        self.exact = exact
        self.uncoded = list(uncoded)
        self.writes = []
        self._result = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT visit_id, method_id"):
            self._result = [self.exact] if self.exact else []
        elif s.startswith("SELECT visit_id FROM visit"):
            self._result = [(v,) for v in self.uncoded]
        elif s.startswith("INSERT INTO visit"):
            self.writes.append(("insert", params))
            self._result = [(999,)]
        elif s.startswith("UPDATE visit"):
            self.writes.append(("update", params))
        else:
            raise AssertionError(s)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result


class ResolveBatVisitTest(unittest.TestCase):
    def test_rerun_reuses_exact_match(self):
        cur = FakeCursor(exact=(42, BAT))
        self.assertEqual(resolve_bat_visit(cur, BAT, 5, D, "C"), (42, False))
        self.assertEqual(cur.writes, [])

    def test_exact_match_without_method_gets_tagged(self):
        cur = FakeCursor(exact=(42, None))
        self.assertEqual(resolve_bat_visit(cur, BAT, 5, D, "C"), (42, False))
        self.assertEqual(cur.writes, [("update", (BAT, 42))])

    def test_reuses_uncoded_bat_visit_and_sets_code(self):
        cur = FakeCursor(uncoded=[13960])
        self.assertEqual(resolve_bat_visit(cur, BAT, 5, D, "SB1_2021-10-02"), (13960, False))
        self.assertEqual(cur.writes, [("update", ("SB1_2021-10-02", 13960))])

    def test_creates_tagged_visit_when_nothing_matches(self):
        cur = FakeCursor()
        self.assertEqual(resolve_bat_visit(cur, BAT, 5, D, "C"), (999, True))
        self.assertEqual(cur.writes, [("insert", (5, D, "C", BAT))])

    def test_creates_when_uncoded_match_is_ambiguous(self):
        cur = FakeCursor(uncoded=[1, 2])
        self.assertEqual(resolve_bat_visit(cur, BAT, 5, D, "C"), (999, True))


if __name__ == "__main__":
    unittest.main()
