"""Unit tests for fill_master_gaps value mapping. No database or workbook needed."""
import math
import unittest

from etl.fill_master_gaps import (
    bio_values, habitat_values, index_type, merge_notes, resolve_site_code,
)


class BioValuesTest(unittest.TestCase):
    def test_maps_and_casts(self):
        v = bio_values({"N.bat": 104.0, "NJIS": 21.0, "HGMI.Genus": 63.5, "CPMI": float("nan"), "FBI": ""})
        self.assertEqual(v, {"total_organisms": 104, "njis_score": 21.0, "hgmi_genus": 63.5})

    def test_empty_row(self):
        self.assertEqual(bio_values({"NJIS": None, "FBI": math.nan}), {})

    def test_index_type(self):
        self.assertEqual(index_type({"hgmi_family": 40}), "HGMI")
        self.assertEqual(index_type({"cpmi_score": 12}), "CPMI")
        self.assertEqual(index_type({"njis_score": 21}), "NJIS")
        self.assertIsNone(index_type({"fbi": 4.2}))


class HabitatValuesTest(unittest.TestCase):
    def test_whole_numbers_only(self):
        v = habitat_values({"Sediment Deposition": 16.0, "Channel Alteration": 15.5, "Bank Stability - Left": None})
        self.assertEqual(v, {"sediment_deposition": 16})


class MergeNotesTest(unittest.TestCase):
    def test_keeps_existing_and_dedupes(self):
        self.assertEqual(merge_notes("a", ["b", "a", " b "]), "a | b")

    def test_none_when_empty(self):
        self.assertIsNone(merge_notes(None, ["  "]))


class ResolveSiteCodeTest(unittest.TestCase):
    def test_exact(self):
        self.assertEqual(resolve_site_code("SB1", {"SB1": 1}, {1: 5}), "SB1")

    def test_case_insensitive_reuse_when_no_visits(self):
        self.assertEqual(resolve_site_code("ELY", {"Ely": 7}, {}), "Ely")

    def test_no_reuse_when_existing_has_visits(self):
        self.assertIsNone(resolve_site_code("BD1A", {"BD1a": 3}, {3: 12}))

    def test_no_reuse_when_ambiguous(self):
        self.assertIsNone(resolve_site_code("ab1", {"AB1": 1, "Ab1": 2}, {}))


if __name__ == "__main__":
    unittest.main()
