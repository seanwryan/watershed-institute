"""Read-only, recursive Excel inventory. Run with --help for options."""

import argparse
from collections import Counter
from datetime import date, datetime, time, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import warnings

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter


def blank(value):
    return value is None or isinstance(value, str) and not value.strip()


def kind(value):
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (datetime, date, time)):
        return "date/time"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def summarize_sheet(sheet, cached, header_row):
    # reset_dimensions avoids trusting incorrect or formatting-inflated dimensions.
    declared = sheet.calculate_dimension()
    sheet.reset_dimensions()
    cached.reset_dimensions()
    rows = []
    formulas = Counter()
    errors = []
    missing_caches = Counter()
    for row, values in zip(sheet.iter_rows(), cached.iter_rows()):
        populated = [cell.column for cell in row if not blank(cell.value)]
        if populated:
            rows.append((row[0].row, {c.column: c.value for c in row if not blank(c.value)}))
        for cell, result in zip(row, values):
            if cell.data_type == "f":
                formulas[cell.column] += 1
                if result.value is None:
                    missing_caches[cell.column] += 1
            if cell.data_type == "e" or result.data_type == "e":
                errors.append({"cell": cell.coordinate, "error": str(result.value if result.data_type == "e" else cell.value)})
    if not rows:
        return {"sheet": sheet.title, "visibility": sheet.sheet_state, "nonempty_rows": 0, "columns": []}
    selected = header_row or rows[0][0]
    headers = next((values for index, values in rows if index == selected), {})
    data = [(index, values) for index, values in rows if index > selected]
    width = max(max(values) for _, values in rows)
    labels = [str(headers.get(i, "")).strip() for i in range(1, width + 1)]
    duplicates = [label for label, count in Counter(labels).items() if label and count > 1]
    columns = []
    row_signatures = Counter(tuple((i, type(v).__name__, str(v)) for i, v in sorted(values.items())) for _, values in data)
    for index, label in enumerate(labels, 1):
        values = [values[index] for _, values in data if index in values]
        # Formula expressions are counted separately; never treat them as measured data.
        raw = [v for v in values if not (isinstance(v, str) and v.startswith("="))]
        types = Counter(kind(v) for v in raw)
        numbers = [v for v in raw if kind(v) == "number" and math.isfinite(v)]
        dates = [v.isoformat() for v in raw if kind(v) == "date/time"]
        column = {"letter": get_column_letter(index), "header": label or None,
                  "nonempty": len(values), "missing": len(data) - len(values),
                  "missing_percent": round(100 * (len(data) - len(values)) / len(data), 2) if data else None,
                  "types": dict(types), "distinct_raw_values": len({(type(v).__name__, str(v)) for v in raw}),
                  "formula_cells_all_rows": formulas[index], "formula_cells_without_cached_result": missing_caches[index]}
        if numbers:
            column["numeric"] = {"count": len(numbers), "min": min(numbers), "max": max(numbers), "mean": statistics.fmean(numbers)}
        if dates:
            column["date_time_range_iso"] = {"min": min(dates), "max": max(dates)}
        columns.append(column)
    return {"sheet": sheet.title, "visibility": sheet.sheet_state,
            "declared_dimension": declared, "last_nonempty_row": rows[-1][0],
            "nonempty_rows": len(rows), "header_row": selected,
            "header_selection": "explicit override" if header_row else "first nonempty row; requires review",
            "nonempty_data_rows": len(data), "blank_rows_after_header": max(0, rows[-1][0] - selected - len(data)),
            "duplicate_headers": duplicates, "duplicate_data_rows": sum(n - 1 for n in row_signatures.values()),
            "excel_error_count": len(errors), "excel_errors_first_100": errors[:100], "columns": columns}


def summarize_workbook(path, root, header_row):
    with path.open("rb") as source:
        fingerprint = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            fingerprint.update(chunk)
        digest = fingerprint.hexdigest()
    result = {"file": str(path.relative_to(root)), "size_bytes": path.stat().st_size,
              "sha256": digest, "sheets": []}
    workbooks = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
            workbooks.append(workbook)
            cached = load_workbook(path, read_only=True, data_only=True, keep_links=False)
            workbooks.append(cached)
            for sheet in workbook:
                try:
                    result["sheets"].append(summarize_sheet(sheet, cached[sheet.title], header_row))
                except Exception as exc:
                    result["sheets"].append({"sheet": sheet.title, "error": f"{type(exc).__name__}: {exc}"})
            result["warnings"] = sorted({str(w.message) for w in caught})
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for workbook in workbooks:
            workbook.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/xlsx_summary.json"))
    parser.add_argument("--header-row", type=int, help="Use this 1-based header row for every sheet; otherwise first nonempty row")
    args = parser.parse_args()
    if not args.folder.is_dir():
        parser.error("folder must be an existing directory")
    if args.header_row is not None and args.header_row < 1:
        parser.error("--header-row must be positive")
    root = args.folder.resolve()
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".xlsx" and not p.name.startswith("~$"))
    if not files:
        parser.error("no .xlsx files found")
    report = {"source_folder": str(root), "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "method": "Read-only structural profiling, not domain validation. Blank means None or whitespace. Data rows are nonempty rows after the assumed header. Formula expressions are excluded from raw statistics; Excel formulas are not recalculated. Duplicate rows are candidates, not confirmed errors. No cell contents are executed.",
              "workbooks": []}
    for path in files:
        print(f"Reading {path.relative_to(root)}", flush=True)
        try:
            report["workbooks"].append(summarize_workbook(path, root, args.header_row))
        except Exception as exc:
            report["workbooks"].append({"file": str(path.relative_to(root)), "error": f"{type(exc).__name__}: {exc}"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    failures = sum("error" in w for w in report["workbooks"]) + sum("error" in s for w in report["workbooks"] for s in w.get("sheets", []))
    print(f"Saved {len(files)} workbook summaries to {args.output}; {failures} read failures.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
