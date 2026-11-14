"""ensure_method_visit keeps one visit per site, date and method. No database needed."""
from datetime import date
import unittest

from etl.visit_helpers import ensure_method_visit


class FakeCursor:
    def __init__(self):
        self.visits = []  # (visit_id, site_id, date, method_id)
        self._row = None

    def execute(self, sql, params):
        if sql.startswith("SELECT"):
            site_id, d, method_id = params
            hits = [v for v in self.visits if v[1:] == (site_id, d, method_id)]
            self._row = (hits[0][0],) if hits else None
        else:
            vid = len(self.visits) + 1
            self.visits.append((vid, *params))
            self._row = (vid,)

    def fetchone(self):
        return self._row


class EnsureMethodVisitTest(unittest.TestCase):
    def test_same_day_different_methods_are_separate(self):
        cur = FakeCursor()
        d = date(2022, 10, 16)
        cat = ensure_method_visit(cur, 1, d, 8)
        bat = ensure_method_visit(cur, 1, d, 2)
        self.assertNotEqual(cat, bat)
        self.assertEqual(len(cur.visits), 2)

    def test_reuses_existing_visit_for_same_method(self):
        cur = FakeCursor()
        d = date(2022, 10, 16)
        self.assertEqual(ensure_method_visit(cur, 1, d, 8), ensure_method_visit(cur, 1, d, 8))
        self.assertEqual(len(cur.visits), 1)

    def test_null_method_matches_null(self):
        cur = FakeCursor()
        d = date(2024, 11, 17)
        self.assertEqual(ensure_method_visit(cur, 1, d, None), ensure_method_visit(cur, 1, d, None))


if __name__ == "__main__":
    unittest.main()
