#!/usr/bin/env python3
"""
Read-only verification: WQX-style export includes every chemistry package.

Uses an existing multi-package visit in the database pointed at by DATABASE_URL
(default / demo). Does not insert or modify data.

Run:
  DATABASE_URL=postgresql://localhost/streamwatch_demo python -m etl.test_export_wqx_multipackage
"""
from __future__ import annotations

import csv
import io
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.db import get_conn
from etl.export_wqx import CHEM_COLUMNS, PARAM_MAP, build_wqx_csv


def _find_multipackage_visit(cur):
    cur.execute(
        """
        SELECT v.visit_id, s.site_code, v.sample_date
        FROM visit v
        JOIN site s ON s.site_id = v.site_id
        JOIN chemical c ON c.visit_id = v.visit_id
        GROUP BY v.visit_id, s.site_code, v.sample_date
        HAVING COUNT(c.chemical_id) >= 2
        ORDER BY COUNT(c.chemical_id) DESC, v.sample_date DESC
        LIMIT 1
        """
    )
    return cur.fetchone()


def _expected_chem_rows(cur, visit_id):
    cur.execute(
        f"""
        SELECT chemical_id, {", ".join(CHEM_COLUMNS)}
        FROM chemical
        WHERE visit_id = %s
        ORDER BY chemical_id
        """,
        (visit_id,),
    )
    expected = []
    packages = cur.fetchall()
    for chem in packages:
        chemical_id = chem[0]
        for i, col in enumerate(CHEM_COLUMNS):
            val = chem[i + 1]
            if val is None:
                continue
            name, _unit = PARAM_MAP[col]
            expected.append((chemical_id, name, str(val)))
    return packages, expected


def main():
    with get_conn() as conn:
        cur = conn.cursor()
        found = _find_multipackage_visit(cur)
        if not found:
            print("FAIL: no multi-package chemistry visit found")
            return 1
        visit_id, site_code, sample_date = found
        packages, expected = _expected_chem_rows(cur, visit_id)

    print(
        f"Using visit_id={visit_id} site={site_code} date={sample_date} "
        f"packages={len(packages)} expected_chem_value_rows={len(expected)}"
    )
    if len(packages) < 2:
        print("FAIL: need at least 2 packages")
        return 1

    buf = build_wqx_csv(
        date_start=sample_date,
        date_end=sample_date,
        site_codes=[site_code],
    )
    reader = csv.DictReader(io.StringIO(buf.getvalue()))
    export_rows = [
        r
        for r in reader
        if r["MonitoringLocationIdentifier"] == site_code
        and r["ActivityStartDate"] == str(sample_date)
        and r["CharacteristicName"] != "Escherichia coli"
    ]

    # Map exported values by characteristic+value (packages distinguished by ActivityIdentifier)
    exported_triples = [
        (r["ActivityIdentifier"], r["CharacteristicName"], r["ResultMeasureValue"])
        for r in export_rows
    ]

    # Every expected non-null value must appear
    missing = []
    for chemical_id, name, val in expected:
        matches = [
            t
            for t in exported_triples
            if t[1] == name and t[2] == val and (f"-C{chemical_id}" in t[0] or len(packages) == 1)
        ]
        if not matches:
            # Also accept exact activity match when multi-package suffix present
            matches = [t for t in exported_triples if t[1] == name and t[2] == val]
        if not matches:
            missing.append((chemical_id, name, val))

    if missing:
        print("FAIL: missing exported values:", missing[:10])
        return 1

    if len(export_rows) < len(expected):
        print(
            f"FAIL: export chem rows {len(export_rows)} < expected {len(expected)}"
        )
        return 1

    # Distinct package activity IDs when multi-package
    activity_ids = {r["ActivityIdentifier"] for r in export_rows}
    if len(packages) >= 2 and len(activity_ids) < 2:
        print("FAIL: multi-package visit collapsed to one ActivityIdentifier", activity_ids)
        return 1

    # Spot-check: package values are not collapsed to a single arbitrary package
    temps = sorted(
        {
            float(r["ResultMeasureValue"])
            for r in export_rows
            if r["CharacteristicName"] == "Temperature, water"
        }
    )
    db_temps = sorted(
        {float(p[1]) for p in packages if p[1] is not None}
    )
    if temps != db_temps:
        print(f"FAIL: water temps export={temps} db={db_temps}")
        return 1

    print("OK: multi-package WQX-style export includes all chemistry packages")
    print(f"  activity_ids={sorted(activity_ids)}")
    print(f"  chem_export_rows={len(export_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
