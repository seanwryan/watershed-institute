"""Source-preserving seasonal intake. No scoring, substitutions, or DB access."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
import math
import re
from zipfile import ZipFile, BadZipFile

from openpyxl import load_workbook

VERSION = "seasonal-bact-1"
MAX_BYTES = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
SHEETS = {
    "SURVEY123": (1, "Field submissions", ("Monitoring Site ID",), ("Date",)),
    "IDEXX": (1, "Bacteria tests", ("Sample ID",), ("Date Collected",)),
    "GALLERY": (1, "Analyzer results", ("Sample/ctrl ID",), ("Result time",)),
    "TURBIDITY": (1, "Turbidity readings", ("Sample ID",), ("Date Collected",)),
    "PHYCOCYANIN": (1, "Bloom follow-up", ("Site ID",), ("Date Flagged",)),
}
PARAMETERS = {
    "SURVEY123": {"Water Temperature": "°C", "E. coli": "MPN/100 mL", "Phosphate": "mg/L", "Chloride": "mg/L", "Nitrate": "mg/L (basis unconfirmed)", "Turbidity (NTU)": "NTU"},
    "IDEXX": {"E. coli": "MPN/100 mL", "Ttl Coli": "MPN/100 mL"},
    "TURBIDITY": {"Final Reading": "unit unconfirmed"},
    "PHYCOCYANIN": {"Median Reading": "unit unconfirmed"},
}


def literal(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def result_value(value, formula=None, error=False):
    """Keep decimals/limits as strings. Never turn uncertain/invalid into zero."""
    raw = literal(value)
    text = str(raw).strip() if raw is not None else ""
    out = {"raw": raw, "number": None, "qualifier": None, "state": "missing", "formula": formula}
    if error:
        out["state"] = "formula_error"
    elif not text:
        out["state"] = "missing_cached_result" if formula else "missing"
    elif "?" in text:
        out["state"] = "uncertain"
    else:
        match = re.fullmatch(r"([<>]=?|=)?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", text)
        if match:
            try:
                number = Decimal(match[2])
                if number.is_finite():
                    out.update(number=str(number), qualifier=match[1] or "=", state="censored" if match[1] in ("<", ">", "<=", ">=") else "numeric")
            except InvalidOperation:
                pass
        if out["state"] == "missing":
            out["state"] = "unparsed"
    return out


def color_value(color):
    if color is None:
        return None
    return {"type": color.type, "value": str(color.value), "tint": color.tint}


def collection_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(value.strip(), fmt).date().isoformat()
            except ValueError:
                pass
    return None


def inspect_workbook(data: bytes, filename: str) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("Choose a workbook smaller than 16 MB.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED:
                raise ValueError("This workbook expands beyond the supported size. Use a seasonal BACT workbook.")
            if "xl/vbaProject.bin" in archive.namelist():
                raise ValueError("Choose an .xlsx seasonal workbook without macros.")
        formulas = load_workbook(BytesIO(data), data_only=False, keep_links=False)
        cached = load_workbook(BytesIO(data), data_only=True, keep_links=False)
    except (BadZipFile, KeyError, OSError) as exc:
        raise ValueError("The file could not be read as an Excel workbook.") from exc
    try:
        names = {s.upper(): s for s in formulas.sheetnames}
        if "SURVEY123" not in names:
            raise ValueError("Choose the BACT and HAB source workbook with a SURVEY123 sheet, rather than the BACT Analysis workbook.")
        rows, summaries = [], []
        for key, (header, label, site_headers, date_headers) in SHEETS.items():
            if key not in names:
                summaries.append({"sheet": key, "label": label, "present": False, "rows": 0})
                continue
            sheet, values = formulas[names[key]], cached[names[key]]
            if sheet.max_row > 20000 or sheet.max_column > 200:
                raise ValueError(f"{key} has an unexpectedly large layout. Review its used range first.")
            headers = {c.column: str(c.value).strip() for c in sheet[header] if c.value is not None}
            site_col = next((c for c, h in headers.items() if h in site_headers), None)
            date_col = next((c for c, h in headers.items() if h in date_headers), None)
            if site_col is None or date_col is None:
                raise ValueError(f"{key} needs its site/sample identifier and date columns. Check the source layout.")
            if key == "PHYCOCYANIN" and values.cell(2, 8).value == "Median Reading":
                headers[8] = "Median Reading"
            first = 3 if key in ("IDEXX", "PHYCOCYANIN") else 2
            count, empty, years = 0, 0, Counter()
            for cells in sheet.iter_rows(min_row=first):
                # Cached/formula-only tails are not source observations. A literal in
                # any column keeps an incomplete row visible for investigation.
                if not any(c.value is not None and str(c.value).strip() and c.data_type != "f" for c in cells):
                    empty += 1
                    continue
                count += 1
                source_row = cells[0].row
                raw_cells, display, parameters, issues = {}, {}, {}, []
                for cell in cells:
                    if cell.value is None and not cell.has_style and cell.comment is None:
                        continue
                    value_cell = values.cell(source_row, cell.column)
                    is_formula = cell.data_type == "f"
                    formula = (getattr(cell.value, "text", None) or str(cell.value)) if is_formula else None
                    value = value_cell.value if is_formula else cell.value
                    raw_cells[cell.coordinate] = {
                        "header": headers.get(cell.column, f"Column {cell.column}"),
                        "original": formula if is_formula else literal(cell.value), "cached": literal(value_cell.value),
                        "formula": formula, "type": cell.data_type,
                        "format": cell.number_format, "style_id": cell.style_id,
                        "font_color": color_value(cell.font.color),
                        "fill_color": color_value(cell.fill.fgColor),
                        "comment": cell.comment.text if cell.comment else None,
                    }
                    if value_cell.data_type == "e":
                        issues.append(f"{cell.coordinate}: saved Excel error")
                    name = headers.get(cell.column, f"Column {cell.column}")
                    if value is not None:
                        display[name] = literal(value)
                    if name in PARAMETERS.get(key, {}) or (key == "GALLERY" and name == "Result"):
                        result = result_value(value, formula, value_cell.data_type == "e")
                        result["unit"] = PARAMETERS.get(key, {}).get(name) or str(values.cell(source_row, 6).value or "unit unconfirmed")
                        result["cell"] = cell.coordinate
                        parameters[name] = result
                        if result["state"] not in ("numeric", "missing"):
                            issues.append(f"{name}: {result['state'].replace('_', ' ')}")
                site_raw = values.cell(source_row, site_col).value
                site = str(site_raw).strip() if site_raw is not None else None
                # Gallery identifiers may contain date/parameter/control codes: never
                # guess a monitoring-site key from their spelling.
                sample_date = collection_date(values.cell(source_row, date_col).value)
                if not site:
                    issues.append("Site/sample identifier missing")
                analysis_date = sample_date if key == "GALLERY" else None
                if key == "GALLERY":
                    sample_date = None
                    issues.append("Analyzer sample/control identity needs review; collection date not inferred")
                elif not sample_date:
                    issues.append("Date needs review")
                else:
                    years[sample_date[:4]] += 1
                annotations = {h: display[h] for h in ("Data Condition", "Data Conditions", "Notes", "Additional Comments (optional)") if h in display}
                if annotations:
                    issues.append("Source notes or conditions to review")
                # No analysis eligibility, pass/fail, or method equivalence is inferred.
                rows.append({"sheet": key, "source_row": source_row, "site_code": site if key != "GALLERY" else None,
                             "sample_identifier": display.get("Sample Code") or display.get("Sample code") or (site if key == "GALLERY" else None),
                             "sample_date": sample_date, "analysis_date": analysis_date, "values": display, "cells": raw_cells,
                             "parameters": parameters, "annotations": annotations, "issues": issues})
            summaries.append({"sheet": key, "label": label, "present": True, "rows": count, "empty_or_formula_only": empty, "years": dict(years)})
        for key in SHEETS:
            groups = Counter((r["site_code"], r["sample_date"]) for r in rows if r["sheet"] == key and r["site_code"] and r["sample_date"])
            for row in rows:
                if row["sheet"] == key and groups.get((row["site_code"], row["sample_date"]), 0) > 1:
                    row["issues"].append("Repeated site/date in this sheet; no match selected")
        return {"filename": filename, "sha256": sha256(data).hexdigest(), "parser_version": VERSION,
                "sheets": summaries, "reference_sheets": [s for s in formulas.sheetnames if s.upper() not in SHEETS],
                "rows": rows, "row_count": len(rows), "needs_attention": sum(bool(r["issues"]) for r in rows)}
    finally:
        formulas.close()
        cached.close()
