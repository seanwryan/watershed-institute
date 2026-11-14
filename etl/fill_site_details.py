#!/usr/bin/env python3
"""
Fill blank site reference details from the All StreamWatch Data SITES sheet.

Fills only what is missing; never overwrites an existing value:
  - municipality links (Primary / Secondary Municipality), adding missing
    municipality names verbatim (state NJ)
  - subwatershed links for sites that have none (Primary / Secondary)
  - drainage_area_sq_km, converted from square miles (Data Dictionary unit)
  - habitat_type (High gradient / Low gradient / Lake / Canal)
  - description, waterbody, latitude/longitude when blank

Where the master and the database disagree, the difference is listed for
review instead of changed.

Dry run by default; --apply commits.  Usage:
  python -m etl.fill_site_details [--file PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "Watershed Data" / "Data" / "All StreamWatch Data - 2026.10.26.xlsx"
SQ_MI_TO_SQ_KM = 2.589988110336
HABITAT_ENUM = {"high gradient": "High Gradient", "low gradient": "Low Gradient", "lake": "Lake", "canal": "Canal"}
SITES_ROWS = 163  # SITES!A1:K164 (rows below are legend labels)


def _text(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def sq_mi_to_km(v) -> Optional[float]:
    n = _num(v)
    return round(n * SQ_MI_TO_SQ_KM, 3) if n is not None and n > 0 else None


def habitat_enum(v) -> Optional[str]:
    t = _text(v)
    return HABITAT_ENUM.get(t.lower()) if t else None


def read_sites(path: Path) -> List[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = list(wb["SITES"].iter_rows(values_only=True))
    finally:
        wb.close()
    header = [str(h).strip() if h else "" for h in rows[0]]
    out = []
    for r in rows[1:SITES_ROWS + 1]:
        rec = dict(zip(header, r))
        if _text(rec.get("Site Code")):
            out.append(rec)
    return out


def run(path: Path, apply: bool) -> dict:
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn

    refuse_if_protected_database(DATABASE_URL)
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    sites = read_sites(path)
    stats: Counter = Counter()
    differences: List[str] = []
    skipped: List[str] = []

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT s.site_id, s.site_code, s.description, s.latitude, s.longitude,
                      s.drainage_area_sq_km, s.habitat_type::text, w.name
               FROM site s LEFT JOIN waterbody w USING (waterbody_id)"""
        )
        db = {r[1]: dict(zip(["site_id", "code", "description", "lat", "lon", "area", "habitat", "waterbody"], r)) for r in cur.fetchall()}
        db_lower = {k.lower(): k for k in db}
        cur.execute("SELECT lower(name), municipality_id FROM municipality")
        municipalities = dict(cur.fetchall())
        cur.execute("SELECT site_id, municipality_id FROM junc_site_municipality")
        mun_links = set(cur.fetchall())
        cur.execute("SELECT lower(name), subwatershed_id FROM subwatershed")
        subwatersheds = dict(cur.fetchall())
        cur.execute("SELECT DISTINCT site_id FROM junc_site_subwatershed")
        has_subwatershed = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT lower(name), waterbody_id FROM waterbody")
        waterbodies = dict(cur.fetchall())

        for rec in sites:
            code = _text(rec["Site Code"])
            key = code if code in db else db_lower.get(code.lower())
            if key is None:
                skipped.append(f"{code}: not in database")
                continue
            s = db[key]
            sid = s["site_id"]
            updates: Dict[str, object] = {}

            desc = _text(rec.get("Description"))
            if desc and not _text(s["description"]):
                updates["description"] = desc
            elif desc and desc != _text(s["description"]):
                differences.append(f"{key} description: db={s['description']!r} master={desc!r}")

            lat, lon = _num(rec.get("Latitude")), _num(rec.get("Longitude"))
            if lat is not None and lon is not None and s["lat"] is None:
                updates["latitude"], updates["longitude"] = lat, lon

            area = sq_mi_to_km(rec.get("Drainage Area"))
            if area is not None and s["area"] is None:
                updates["drainage_area_sq_km"] = area

            hab_raw = _text(rec.get("Habitat Type"))
            hab = habitat_enum(hab_raw)
            if hab and not s["habitat"]:
                updates["habitat_type"] = hab
            elif hab and s["habitat"] and hab != s["habitat"]:
                differences.append(f"{key} habitat: db={s['habitat']} master={hab_raw}")
            elif hab_raw and not hab:
                differences.append(f"{key} habitat: master value {hab_raw!r} has no matching category")

            wb_name = _text(rec.get("Waterbody"))
            if wb_name and not s["waterbody"]:
                wid = waterbodies.get(wb_name.lower())
                if wid is not None:
                    updates["waterbody_id"] = wid
                else:
                    differences.append(f"{key} waterbody: master {wb_name!r} not in waterbody list")
            elif wb_name and s["waterbody"] and wb_name.lower() != s["waterbody"].lower():
                differences.append(f"{key} waterbody: db={s['waterbody']!r} master={wb_name!r}")

            if updates:
                cols = ", ".join(f"{c} = %s" + ("::habitat_type_enum" if c == "habitat_type" else "") for c in updates)
                cur.execute(f"UPDATE site SET {cols}, updated_at = CURRENT_TIMESTAMP WHERE site_id = %s",
                            list(updates.values()) + [sid])
                for c in updates:
                    stats[f"site.{c} filled"] += 1
                stats["sites updated"] += 1

            for col in ("Primary Municipality", "Secondary Municipality"):
                name = _text(rec.get(col))
                if not name:
                    continue
                mid = municipalities.get(name.lower())
                if mid is None:
                    cur.execute("INSERT INTO municipality (name, state) VALUES (%s, 'NJ') RETURNING municipality_id", (name,))
                    mid = cur.fetchone()[0]
                    municipalities[name.lower()] = mid
                    stats["municipalities added"] += 1
                if (sid, mid) not in mun_links:
                    cur.execute("INSERT INTO junc_site_municipality (site_id, municipality_id) VALUES (%s, %s)", (sid, mid))
                    mun_links.add((sid, mid))
                    stats["site-municipality links added"] += 1

            if sid not in has_subwatershed:
                for col in ("Primary Subwatershed", "Secondary Subwatershed"):
                    name = _text(rec.get(col))
                    if not name:
                        continue
                    swid = subwatersheds.get(name.lower())
                    if swid is None:
                        cur.execute("INSERT INTO subwatershed (name) VALUES (%s) RETURNING subwatershed_id", (name,))
                        swid = cur.fetchone()[0]
                        subwatersheds[name.lower()] = swid
                        stats["subwatersheds added"] += 1
                    cur.execute("INSERT INTO junc_site_subwatershed (site_id, subwatershed_id) VALUES (%s, %s)", (sid, swid))
                    stats["site-subwatershed links added"] += 1
                has_subwatershed.add(sid)

        cur.execute(
            """SELECT count(*), count(*) FILTER (WHERE drainage_area_sq_km IS NULL),
                      count(*) FILTER (WHERE habitat_type IS NULL),
                      count(*) FILTER (WHERE latitude IS NULL),
                      count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM junc_site_municipality j WHERE j.site_id = site.site_id)),
                      count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM junc_site_subwatershed j WHERE j.site_id = site.site_id))
               FROM site"""
        )
        remaining = dict(zip(["sites", "no_drainage", "no_habitat", "no_coords", "no_municipality", "no_subwatershed"], cur.fetchone()))

        print("\n  " + "\n  ".join(f"{k}: {v}" for k, v in sorted(stats.items())))
        print("  remaining gaps:", remaining)
        print(f"  differences for review ({len(differences)}):")
        for d in differences:
            print("    " + d)
        if skipped:
            print("  skipped:", "; ".join(skipped))

        if not apply:
            conn.rollback()
            print("\nDRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("\nAPPLIED.")
        return {"stats": dict(stats), "remaining": remaining, "differences": differences}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)
    run(args.file, apply=args.apply)


if __name__ == "__main__":
    main()
