"""Rating bands (2026 framework, section 11) and site-detail helpers. No database needed."""
import unittest

from etl.fill_site_details import habitat_enum, sq_mi_to_km
from etl.rate_bio_scores import rate_cpmi, rate_hgmi, rate_njis


class HgmiTest(unittest.TestCase):
    def test_band_edges(self):
        self.assertEqual(rate_hgmi(63), "Excellent")
        self.assertEqual(rate_hgmi(62.99), "Good")
        self.assertEqual(rate_hgmi(42), "Good")
        self.assertEqual(rate_hgmi(41.9), "Fair")
        self.assertEqual(rate_hgmi(21), "Fair")
        self.assertEqual(rate_hgmi(20.9), "Poor")
        self.assertEqual(rate_hgmi(0), "Poor")

    def test_out_of_range(self):
        self.assertIsNone(rate_hgmi(101))
        self.assertIsNone(rate_hgmi(None))


class CpmiTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(rate_cpmi(22), "Excellent")
        self.assertEqual(rate_cpmi(20), "Good")
        self.assertEqual(rate_cpmi(12), "Good")
        self.assertEqual(rate_cpmi(10), "Fair")
        self.assertEqual(rate_cpmi(6), "Fair")
        self.assertEqual(rate_cpmi(4), "Poor")

    def test_framework_gaps_left_unrated(self):
        self.assertIsNone(rate_cpmi(11))
        self.assertIsNone(rate_cpmi(21))
        self.assertIsNone(rate_cpmi(31))


class NjisTest(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(rate_njis(22.5), "Excellent")
        self.assertEqual(rate_njis(22.4), "Good")
        self.assertEqual(rate_njis(15), "Good")
        self.assertEqual(rate_njis(7.5), "Fair")
        self.assertEqual(rate_njis(7.4), "Poor")

    def test_impossible_old_computed_values(self):
        self.assertIsNone(rate_njis(54.2))


class SiteHelpersTest(unittest.TestCase):
    def test_square_miles_to_km(self):
        self.assertAlmostEqual(sq_mi_to_km(1), 2.59, places=2)
        self.assertAlmostEqual(sq_mi_to_km(35), 90.65, places=2)
        self.assertIsNone(sq_mi_to_km(None))
        self.assertIsNone(sq_mi_to_km(0))

    def test_habitat_enum(self):
        self.assertEqual(habitat_enum("High gradient"), "High Gradient")
        self.assertEqual(habitat_enum("lake"), "Lake")
        self.assertIsNone(habitat_enum("Fresh tidal"))


if __name__ == "__main__":
    unittest.main()
