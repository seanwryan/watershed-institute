"""Small synthetic fixtures for profiling semantics; no operational data."""
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from etl.summarize_xlsx import summarize_workbook


class ProfileTests(unittest.TestCase):
    def test_missing_duplicates_formulas_and_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.append([])
            sheet.append(["value", "value", None, "calculation"])
            sheet.append([0, False, "  ", "=A3+1"])
            sheet.append([0, False])
            sheet.append([0, False])
            sheet.append(["#DIV/0!"])
            book.create_sheet("empty")
            book.save(path)
            before = path.read_bytes()
            report = summarize_workbook(path, Path(folder), None)
            self.assertNotIn("error", report)
            result = report["sheets"][0]
            self.assertEqual(result["header_row"], 2)
            self.assertEqual(result["nonempty_data_rows"], 4)
            self.assertEqual(result["duplicate_headers"], ["value"])
            self.assertEqual(result["duplicate_data_rows"], 1)
            self.assertEqual(result["excel_error_count"], 1)
            self.assertEqual(result["columns"][0]["numeric"]["min"], 0)
            self.assertEqual(result["columns"][1]["types"], {"boolean": 3})
            self.assertEqual(result["columns"][2]["missing"], 4)
            self.assertEqual(result["columns"][3]["formula_cells_without_cached_result"], 1)
            self.assertEqual(report["sheets"][1]["nonempty_rows"], 0)
            self.assertEqual(before, path.read_bytes())

    def test_corrupt_workbook_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.xlsx"
            path.write_text("not a workbook")
            self.assertIn("error", summarize_workbook(path, Path(folder), None))


if __name__ == "__main__":
    unittest.main()
