"""Synthetic seasonal BAT preview fixtures; no database or private files required."""
import csv
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from etl.bat_reconcile import preview_bat_files, read_bug_csv, read_habitat_workbook


class ReadOnlyCursor:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=None):
        assert sql.lstrip().upper().startswith("SELECT"), "Unexpected database mutation"
        self.queries.append((sql, params))
        if "SELECT site_code FROM site" in sql:
            self.rows = [("T1",)]
        elif "FROM visit v" in sql:
            self.rows = [("T1", date(2026, 4, 26), 10, "one"), ("T1", date(2026, 4, 26), 11, "two")]
        elif "FROM bug_list" in sql:
            self.rows = [(1, "Baetis"), (2, "Baetis"), (3, "Hydropsyche")]
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return self.rows


class ReadOnlyConnection:
    def __init__(self):
        self.reader = ReadOnlyCursor()

    def cursor(self):
        return self.reader


class BatPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bugs = self.root / "bugs.csv"
        self.habitat = self.root / "habitat.xlsx"
        self.headers = ["Activity ID", "Station ID", "Sample Date", "Sample Type \\n(Orig or Rep)", "Count", "Taxon Name", "HBI"]
        self.write_bugs([
            ["T1:20260426:Orig", "T1", "4/26/2026", "Orig", "10", "Baetis", "2.8"],
            ["T1:20260426:Orig", "T1", "4/26/2026", "Orig", "10", "Baetis", "2.8"],
            ["T1:20260426:Rep", "T1", "2026-04-26", "Rep", "2.5", "Hydropsyche", "3.2"],
            ["Other", "UNKNOWN", "not a date", "Orig", "3", "Unknown taxon", ""],
            ["", "", "", "", "", "", ""],
        ])
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Form Responses 1"
        sheet.append(["Sample Date", "Site ID", "Sampler Name(s)", "HIGH GRADIENT ONLY 2. Embeddedness", "Comments/Observations"])
        sheet.append([datetime(2026, 4, 26), "T1", "Synthetic A", "Good - source label", "<script>alert(1)</script>"])
        sheet.append([datetime(2026, 4, 26), "T1", "Synthetic B", 7, "Second form"])
        sheet.append([datetime(2020, 9, 27), "T1", "Synthetic C", 0, "Historical form"])
        workbook.save(self.habitat)
        workbook.close()

    def write_bugs(self, rows):
        with self.bugs.open("w", encoding="utf-8-sig", newline="") as source:
            writer = csv.writer(source)
            writer.writerow(self.headers)
            writer.writerows(rows)

    def test_source_rows_replication_and_original_indices_are_preserved(self):
        result = preview_bat_files(self.bugs, self.habitat, ReadOnlyConnection())
        s = result["summary"]
        self.assertEqual(s["bug_rows"], 4)
        self.assertEqual(s["blank_bug_rows"], 1)
        self.assertEqual(s["samples"], 3)
        self.assertEqual(s["exact_duplicate_bug_rows"], 1)
        original, replicate, invalid = result["samples"]
        self.assertEqual(len(original["rows"]), 2)  # no deduplication or summing
        self.assertEqual(replicate["sample_type"], "Rep")
        self.assertIsNone(replicate["rows"][0]["amount"])  # do not truncate 2.5
        self.assertEqual(replicate["rows"][0]["raw"]["HBI"], "3.2")
        self.assertFalse(invalid["site_exists"])
        self.assertIsNone(invalid["sample_date"])

    def test_exact_facts_do_not_select_a_parent_or_habitat(self):
        result = preview_bat_files(self.bugs, self.habitat, ReadOnlyConnection())
        sample = result["samples"][0]
        self.assertEqual(sample["habitat_rows"], [2, 3])
        self.assertEqual(len(sample["visits"]), 2)
        self.assertEqual(sample["rows"][0]["taxon_ids"], [1, 2])
        self.assertNotIn("visit_id", sample)
        self.assertEqual(result["summary"]["unmatched_taxon_names"], ["Unknown taxon"])
        self.assertEqual(result["summary"]["ambiguous_taxon_names"], ["Baetis"])
        self.assertEqual(result["summary"]["date_start"], "2020-09-27")
        self.assertEqual(result["habitats"][0]["raw"]["HIGH GRADIENT ONLY 2. Embeddedness"], "Good - source label")
        self.assertNotIn("score", result["habitats"][0])
        self.assertEqual(result["habitats"][2]["raw"]["HIGH GRADIENT ONLY 2. Embeddedness"], "0")

    def test_conflicting_activity_ids_stay_separate(self):
        self.write_bugs([
            ["Same", "T1", "4/26/2026", "Orig", "1", "Baetis", ""],
            ["Same", "T1", "4/27/2026", "Orig", "1", "Baetis", ""],
        ])
        result = preview_bat_files(self.bugs, None, ReadOnlyConnection())
        self.assertEqual(result["summary"]["activity_id_conflicts"], 1)
        self.assertEqual(len(result["samples"]), 2)
        self.assertTrue(all(sample["activity_conflict"] for sample in result["samples"]))

    def test_one_source_is_allowed_and_headers_are_required(self):
        self.assertEqual(preview_bat_files(None, self.habitat, ReadOnlyConnection())["summary"]["bug_rows"], 0)
        with self.assertRaisesRegex(ValueError, "Choose"):
            preview_bat_files(None, None, ReadOnlyConnection())
        self.bugs.write_text("Site,Count\nT1,4\n")
        with self.assertRaisesRegex(ValueError, "Missing source columns"):
            read_bug_csv(self.bugs)

    def test_row_limit_rejects_instead_of_truncating(self):
        with patch("etl.bat_reconcile.MAX_SOURCE_ROWS", 1):
            with self.assertRaisesRegex(ValueError, "no more than"):
                read_bug_csv(self.bugs)

    def test_missing_activity_does_not_merge_unidentified_rows(self):
        self.write_bugs([
            ["", "T1", "4/26/2026", "Orig", "1", "Baetis", ""],
            ["", "T1", "4/26/2026", "Orig", "2", "Hydropsyche", ""],
        ])
        result = preview_bat_files(self.bugs, None, ReadOnlyConnection())
        self.assertEqual(len(result["samples"]), 2)
        self.assertEqual(result["summary"]["invalid_bug_rows"], 2)

    def test_habitat_sheet_and_columns_must_match_source_format(self):
        workbook = Workbook()
        workbook.active.append(["Site ID", "Sample Date"])
        workbook.save(self.habitat)
        with self.assertRaisesRegex(ValueError, "Form Responses 1"):
            read_habitat_workbook(self.habitat)
        workbook.active.title = "Form Responses 1"
        workbook.save(self.habitat)
        workbook.close()
        with self.assertRaisesRegex(ValueError, "Sampler Name"):
            read_habitat_workbook(self.habitat)


if __name__ == "__main__":
    unittest.main()
