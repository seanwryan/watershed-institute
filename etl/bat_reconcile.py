"""Read-only review of seasonal BAT lab CSV and volunteer habitat workbook.

Source: 2026 BAT Bug Data to be entered.csv and BAT Habitat Data to be entered.xlsx.
Only exact source identifiers/names are compared. No visit, taxon, replicate,
volunteer, habitat-score, or biological-index mapping is selected or saved.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

MAX_SOURCE_ROWS = 20000
BUG_HEADERS = {"Activity ID", "Station ID", "Sample Date", "Sample Type (Orig or Rep)", "Count", "Taxon Name"}
HABITAT_HEADERS = {"Site ID", "Sample Date", "Sampler Name(s)"}


def _text(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _header(value):
    return " ".join(_text(value).replace("\\n", " ").split())


def _date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raw = _text(value).strip()
    # The supplied CSV uses US month/day/year; also accept ISO dates.
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _read_rows(headers, rows, required):
    names = [_header(value) for value in headers]
    missing = required - set(names)
    if missing:
        raise ValueError("Missing source columns: " + ", ".join(sorted(missing)))
    nonblank_names = [name for name in names if name]
    if len(nonblank_names) != len(set(nonblank_names)):
        raise ValueError("The source has repeated column headings. Check the file before reviewing it.")
    records, blanks = [], 0
    seen = set()
    for source_row, cells in enumerate(rows, 2):
        if source_row - 1 > MAX_SOURCE_ROWS:
            raise ValueError(f"Review files with no more than {MAX_SOURCE_ROWS:,} data rows each.")
        if not any(_text(value).strip() for value in cells):
            blanks += 1
            continue
        if any(_text(value).strip() for value in cells[len(names):]):
            raise ValueError(f"Row {source_row} has values beyond the column headings.")
        if any(not name and i < len(cells) and _text(cells[i]).strip() for i, name in enumerate(names)):
            raise ValueError(f"Row {source_row} has a value under a blank column heading.")
        raw = {name: _text(cells[i]) if i < len(cells) else "" for i, name in enumerate(names) if name}
        fingerprint = tuple(raw.items())
        repeated = fingerprint in seen
        seen.add(fingerprint)
        records.append({"source_row": source_row, "raw": raw, "exact_repeat": repeated})
    return records, blanks


def read_bug_csv(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            return _read_rows(next(reader, []), reader, BUG_HEADERS)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Use a UTF-8 CSV exported from the BAT lab results.") from exc


def read_habitat_workbook(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if "Form Responses 1" not in workbook.sheetnames:
            raise ValueError("The habitat workbook needs a Form Responses 1 sheet.")
        rows = workbook["Form Responses 1"].iter_rows(values_only=True)
        headers = next(rows, ())
        # Retain typed Excel dates for matching; preserve every other source cell.
        records, blanks = _read_rows(headers, rows, HABITAT_HEADERS)
        for record in records:
            raw_date = record["raw"]["Sample Date"]
            if "T" in raw_date:
                try:
                    record["sample_date"] = _date(datetime.fromisoformat(raw_date))
                except ValueError:
                    record["sample_date"] = None
            else:
                record["sample_date"] = _date(raw_date)
        return records, blanks
    finally:
        workbook.close()


def _count(raw):
    try:
        value = Decimal(raw.strip())
        if value.is_finite() and value >= 0 and value == value.to_integral_value():
            return int(value)
    except (InvalidOperation, ValueError):
        pass
    return None


def preview_bat_files(bug_path, habitat_path, conn):
    """Read source files and SELECT comparison facts. Never write to PostgreSQL."""
    if not bug_path and not habitat_path:
        raise ValueError("Choose a BAT bug CSV, a habitat workbook, or both.")
    bugs, blank_bugs = read_bug_csv(bug_path) if bug_path else ([], 0)
    habitats, blank_habitats = read_habitat_workbook(habitat_path) if habitat_path else ([], 0)
    samples = {}
    activities = defaultdict(set)
    for row in bugs:
        raw = row["raw"]
        row.update(site_code=raw["Station ID"].strip(), sample_date=_date(raw["Sample Date"]),
                   activity_id=raw["Activity ID"].strip(), sample_type=raw["Sample Type (Orig or Rep)"].strip(),
                   taxon_name=raw["Taxon Name"].strip(), amount=_count(raw["Count"]), issues=[])
        for missing, message in ((not row["site_code"], "Site ID is missing."),
                                 (not row["sample_date"], "Sample date is missing or unreadable."),
                                 (not row["activity_id"], "Activity ID is missing."),
                                 (not row["taxon_name"], "Taxon name is missing."),
                                 (row["amount"] is None, "Count is missing or is not a non-negative whole number.")):
            if missing:
                row["issues"].append(message)
        if row["sample_type"] not in ("Orig", "Rep"):
            row["issues"].append("Sample type is not Orig or Rep; no type was inferred.")
        identity = (row["activity_id"], row["site_code"], row["sample_date"], row["sample_type"])
        # Missing identifiers cannot establish that two source rows belong to
        # the same activity. Retain each such row as a separate review group.
        key = identity + (None if all(identity) else row["source_row"],)
        if row["activity_id"]:
            activities[row["activity_id"]].add(identity[1:])
        sample = samples.setdefault(key, {"activity_id": key[0], "site_code": key[1], "sample_date": key[2], "sample_type": key[3], "rows": []})
        sample["rows"].append(row)

    for row in habitats:
        row["site_code"] = row["raw"]["Site ID"].strip()
        row["issues"] = []
        if not row["site_code"]:
            row["issues"].append("Site ID is missing.")
        if not row["sample_date"]:
            row["issues"].append("Sample date is missing or unreadable.")

    records = bugs + habitats
    site_codes = sorted({row["site_code"] for row in records if row["site_code"]})
    dates = sorted({row["sample_date"] for row in records if row["sample_date"]})
    visits = defaultdict(list)
    taxa = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT site_code FROM site")
        sites = {row[0] for row in cur.fetchall()}
        if site_codes and dates:
            cur.execute("""
                SELECT s.site_code, v.sample_date, v.visit_id, v.sample_code
                FROM visit v JOIN site s ON s.site_id = v.site_id
                WHERE s.site_code = ANY(%s) AND v.sample_date = ANY(%s::date[])
                ORDER BY v.sample_date, v.visit_id
            """, (site_codes, dates))
            for code, sample_date, visit_id, sample_code in cur.fetchall():
                visits[(code, str(sample_date))].append({"visit_id": visit_id, "sample_code": sample_code})
        if bugs:
            cur.execute("SELECT bug_id, genus_species FROM bug_list WHERE genus_species IS NOT NULL")
            for bug_id, name in cur.fetchall():
                if name.strip():
                    taxa[name.strip()].append(bug_id)

    habitat_by_key = defaultdict(list)
    for row in habitats:
        if row["site_code"] and row["sample_date"]:
            habitat_by_key[(row["site_code"], row["sample_date"])].append(row["source_row"])
    activities_by_date = defaultdict(list)
    for sample in samples.values():
        key = (sample["site_code"], sample["sample_date"])
        sample["habitat_rows"] = habitat_by_key.get(key, [])
        sample["activity_conflict"] = len(activities[sample["activity_id"]]) > 1 if sample["activity_id"] else False
        if all(key):
            activities_by_date[key].append({"activity_id": sample["activity_id"], "sample_type": sample["sample_type"]})
    for row in records + list(samples.values()):
        row["site_exists"] = row["site_code"] in sites
        row["visits"] = visits.get((row["site_code"], row["sample_date"]), [])
    for row in bugs:
        row["taxon_ids"] = taxa.get(row["taxon_name"], [])
    for sample in samples.values():
        sample["taxon_review_rows"] = sum(len(row["taxon_ids"]) != 1 for row in sample["rows"])
    for row in habitats:
        row["lab_activities"] = activities_by_date.get((row["site_code"], row["sample_date"]), [])

    return {
        "samples": list(samples.values()), "habitats": habitats,
        "summary": {
            "bug_rows": len(bugs), "blank_bug_rows": blank_bugs,
            "samples": len(samples), "habitat_rows": len(habitats), "blank_habitat_rows": blank_habitats,
            "invalid_bug_rows": sum(bool(row["issues"]) for row in bugs),
            "invalid_habitat_rows": sum(bool(row["issues"]) for row in habitats),
            "exact_duplicate_bug_rows": sum(row["exact_repeat"] for row in bugs),
            "exact_duplicate_habitat_rows": sum(row["exact_repeat"] for row in habitats),
            "missing_sites": sorted(set(site_codes) - sites),
            "samples_with_habitat": sum(bool(sample["habitat_rows"]) for sample in samples.values()),
            "samples_with_multiple_habitat_rows": sum(len(sample["habitat_rows"]) > 1 for sample in samples.values()),
            "samples_without_visit": sum(not sample["visits"] for sample in samples.values()),
            "samples_with_multiple_visits": sum(len(sample["visits"]) > 1 for sample in samples.values()),
            "unmatched_taxon_names": sorted({row["taxon_name"] for row in bugs if row["taxon_name"] and not row["taxon_ids"]}),
            "ambiguous_taxon_names": sorted({row["taxon_name"] for row in bugs if len(row["taxon_ids"]) > 1}),
            "activity_id_conflicts": sum(len(keys) > 1 for keys in activities.values()),
            "date_start": dates[0] if dates else None, "date_end": dates[-1] if dates else None,
        },
    }
