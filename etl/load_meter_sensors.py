#!/usr/bin/env python3
"""
Load meter sensors from CAT Meter Tracking v.1.xlsx > Sensors.

Each meter (TWI###) has a DO, pH and EC sensor. The sheet records the date each
was last changed ("Date Last Changed"), stored here as the sensor's
date_installed (blank when the sheet has no date). The headings are on the
sheet's second row; migrate_equipment.py originally read the first row, found
no "Meter ID" column and loaded no sensors (found by the 2026-11 data audit).

One sensor per meter and type; re-running updates the date instead of adding
rows. Dry run by default; --apply commits.

Usage: python -m etl.load_meter_sensors [--file PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "Watershed Data" / "Data" / "CAT Meter Tracking v.1.xlsx"
SENSOR_COLUMNS = {"DO": "DO Sensor", "pH": "pH Sensor", "EC": "EC Sensor"}


def read_sensor_sheet(path: Path) -> List[dict]:
    """Rows of {meter, serial, DO, pH, EC} with dates or None, finding the heading row."""
    import pandas as pd

    raw = pd.read_excel(path, sheet_name="Sensors", header=None)
    header_row = next(i for i, r in raw.iterrows() if any(str(v).strip() == "Meter ID" for v in r.values))
    df = pd.read_excel(path, sheet_name="Sensors", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    out = []
    for _, r in df.iterrows():
        meter = str(r.get("Meter ID") or "").strip().upper()
        if not meter.startswith("TWI"):
            continue
        rec = {"meter": meter}
        for sensor_type, colname in SENSOR_COLUMNS.items():
            v = pd.to_datetime(r.get(colname), errors="coerce")
            rec[sensor_type] = None if pd.isna(v) else v.date()
        out.append(rec)
    return out


def run(path: Path, apply: bool) -> dict:
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn

    refuse_if_protected_database(DATABASE_URL)
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    rows = read_sensor_sheet(path)
    added = updated = unchanged = 0
    unknown: List[str] = []
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT equipment_code, equipment_id FROM equipment")
        equipment = dict(cur.fetchall())
        cur.execute("SELECT sensor_id, equipment_id, sensor_type::text, date_installed FROM sensor")
        existing = {(e, t): (sid, d) for sid, e, t, d in cur.fetchall()}
        for rec in rows:
            eq = equipment.get(rec["meter"])
            if eq is None:
                unknown.append(rec["meter"])
                continue
            for sensor_type in SENSOR_COLUMNS:
                when: Optional[object] = rec[sensor_type]
                if (eq, sensor_type) in existing:
                    sid, current = existing[(eq, sensor_type)]
                    if current != when:
                        cur.execute("UPDATE sensor SET date_installed = %s WHERE sensor_id = %s", (when, sid))
                        updated += 1
                    else:
                        unchanged += 1
                else:
                    cur.execute("INSERT INTO sensor (equipment_id, sensor_type, date_installed) VALUES (%s, %s::sensor_type_enum, %s)",
                                (eq, sensor_type, when))
                    added += 1
        print(f"  meters in sheet: {len(rows)}   sensors added: {added}   updated: {updated}   unchanged: {unchanged}")
        if unknown:
            print("  meters not in equipment table:", ", ".join(unknown))
        if not apply:
            conn.rollback()
            print("DRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("APPLIED.")
    return {"meters": len(rows), "added": added, "updated": updated, "unknown": unknown}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)
    run(args.file, apply=args.apply)


if __name__ == "__main__":
    main()
