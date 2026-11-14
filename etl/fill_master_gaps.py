#!/usr/bin/env python3
"""
Fill what the original ALL DATA load (migrate_streamwatch_data.py) left out.

Found 2026-11-14 by comparing All StreamWatch Data (2026-10-26) with live Neon:
  1. 8 master sites were never created, so their 69 rows were skipped.
  2. ensure_visit() matched visits on site + date only, so rows from different
     teams on the same day were merged into one visit: 340 chemistry rows and
     92 bacteria rows sit on a visit labelled with another method.
  3. Bug-index columns (N.bat, NJIS, HGMI, CPMI, FBI) were never loaded:
     721 master rows, 108 already in macro_analysis from tblSampleDates.
  4. The master's RBP habitat columns were never loaded (8 rows).
  5. The Notes column was never loaded (1,940 rows).

Steps (one transaction, dry run unless --apply):
  sites   add missing master sites (case-insensitive reuse of an existing code
          with no visits, e.g. ELY -> Ely, instead of a duplicate)
  split   move each chemistry row whose method differs from its visit, and each
          bacteria row on a non-BACT visit, to the (site, date, method) visit,
          creating it if needed; never deletes a result row
  newsite load chemistry / E. coli for rows at the newly added sites
  bio     add macro_analysis to the (site, date, BAT) visit; existing rows are
          only overwritten with --replace-computed-bio (differences reported)
  habitat add habitat_assessment where the BAT visit has none
  notes   attach distinct master Notes to the (site, date, method) visit,
          keeping any existing text

Rows with no values at all (e.g. Incomplete with nothing recorded) are reported,
not loaded. Compound Data Conditions ("Flagged; Incomplete") stay unresolved,
as in the original loader.

Usage:
  python -m etl.fill_master_gaps [--file PATH] [--apply]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "Watershed Data" / "Data" / "All StreamWatch Data - 2026.10.26.xlsx"

# master header -> (macro_analysis column, cast)
BIO_COLUMNS = {
    "N.bat": ("total_organisms", int),
    "NJIS": ("njis_score", float),
    "HGMI.Family": ("hgmi_family", float),
    "HGMI.Genus": ("hgmi_genus", float),
    "CPMI": ("cpmi_score", float),
    "FBI": ("fbi", float),
}

# Master site code -> existing DB code (same site, different case). Applied 2026-11-14.
SITE_ALIASES = {"ELY": "Ely"}

# Computed by the earlier unvalidated biological_indices.py; cleared when master scores replace a row.
DERIVED_MACRO_COLUMNS = [
    "total_taxa", "ept_taxa", "pct_ept", "pct_dominance", "dominant_taxon", "hbi",
    "njis_rating", "hgmi_rating", "cpmi_rating",
]

# master header -> habitat_assessment column
HABITAT_COLUMNS = {
    "Epifaunal Substrate/Available Cover": "epifaunal_substrate",
    "Embeddedness - High Gradient": "embeddedness",
    "Pool Substrate Characterization - Low Gradient": "pool_substrate",
    "Velocity/Depth Combinations - High Gradient": "velocity_depth",
    "Pool Variability - Low Gradient": "pool_variability",
    "Sediment Deposition": "sediment_deposition",
    "Channel Flow Status": "channel_flow_status",
    "Channel Alteration": "channel_alteration",
    "Frequency of Riffles - High Gradient": "freq_riffles",
    "Channel Sinuosity - Low Gradient": "channel_sinuosity",
    "Bank Stability - Left": "bank_stability_left",
    "Bank Stability - Right": "bank_stability_right",
    "Bank Vegetative Protection - Left": "bank_veg_protection_left",
    "Bank Vegetative Protection - Right": "bank_veg_protection_right",
    "Riparian Vegetative Zone - Left": "riparian_zone_left",
    "Riparian Vegetative Zone - Right": "riparian_zone_right",
}


def _blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    return isinstance(v, str) and not v.strip()


def bio_values(row) -> Dict[str, Optional[float]]:
    """Macro index values from a master row; {} when the row has none."""
    out = {}
    for header, (column, cast) in BIO_COLUMNS.items():
        v = row.get(header)
        if _blank(v):
            continue
        try:
            out[column] = cast(round(float(v))) if cast is int else float(v)
        except (TypeError, ValueError):
            continue
    return out


def index_type(values: Dict[str, float]) -> Optional[str]:
    if "hgmi_genus" in values or "hgmi_family" in values:
        return "HGMI"
    if "cpmi_score" in values:
        return "CPMI"
    if "njis_score" in values:
        return "NJIS"
    return None


def habitat_values(row) -> Dict[str, int]:
    out = {}
    for header, column in HABITAT_COLUMNS.items():
        v = row.get(header)
        if _blank(v):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == int(f):
            out[column] = int(f)
    return out


def merge_notes(existing: Optional[str], new: List[str]) -> Optional[str]:
    """Append distinct new note texts to existing text, preserving order."""
    parts = [p for p in ((existing or "").split(" | ")) if p.strip()]
    for n in new:
        n = n.strip()
        if n and n not in parts:
            parts.append(n)
    return " | ".join(parts) or None


def resolve_site_code(code: str, existing: Dict[str, int], visit_counts: Dict[int, int]) -> Optional[str]:
    """Exact match, else a unique case-insensitive match that has no visits."""
    if code in existing:
        return code
    matches = [c for c in existing if c.lower() == code.lower()]
    if len(matches) == 1 and visit_counts.get(existing[matches[0]], 0) == 0:
        return matches[0]
    return None


class VisitIndex:
    """(site_id, date, method_id) -> visit_id, creating visits on demand."""

    def __init__(self, cur):
        self.cur = cur
        self.created = 0
        self.by_key: Dict[Tuple, int] = {}
        cur.execute("SELECT visit_id, site_id, sample_date, method_id FROM visit ORDER BY visit_id")
        for vid, sid, d, mid in cur.fetchall():
            self.by_key.setdefault((sid, d, mid), vid)

    def get(self, site_id, d, method_id) -> Optional[int]:
        return self.by_key.get((site_id, d, method_id))

    def get_or_create(self, site_id, d, method_id) -> int:
        vid = self.get(site_id, d, method_id)
        if vid is None:
            self.cur.execute(
                "INSERT INTO visit (site_id, sample_date, method_id) VALUES (%s, %s, %s) RETURNING visit_id",
                (site_id, d, method_id),
            )
            vid = self.cur.fetchone()[0]
            self.by_key[(site_id, d, method_id)] = vid
            self.created += 1
        return vid


def _counts(cur) -> dict:
    cur.execute(
        """SELECT (SELECT count(*) FROM site), (SELECT count(*) FROM visit),
                  (SELECT count(*) FROM chemical), (SELECT count(*) FROM bacteria),
                  (SELECT count(*) FROM macro_analysis), (SELECT count(*) FROM habitat_assessment),
                  (SELECT count(*) FROM visit WHERE notes IS NOT NULL AND notes <> ''),
                  (SELECT count(*) FROM chemical c JOIN visit v USING (visit_id)
                     WHERE c.method_id IS DISTINCT FROM v.method_id),
                  (SELECT count(*) FROM bacteria b JOIN visit v USING (visit_id)
                     JOIN lst_method m ON m.method_id = v.method_id WHERE m.name <> 'BACT'),
                  (SELECT count(*) FROM visit v WHERE NOT EXISTS (SELECT 1 FROM chemical x WHERE x.visit_id = v.visit_id)
                     AND NOT EXISTS (SELECT 1 FROM bacteria x WHERE x.visit_id = v.visit_id)
                     AND NOT EXISTS (SELECT 1 FROM macro_analysis x WHERE x.visit_id = v.visit_id)
                     AND NOT EXISTS (SELECT 1 FROM habitat_assessment x WHERE x.visit_id = v.visit_id)
                     AND NOT EXISTS (SELECT 1 FROM bug_count x WHERE x.visit_id = v.visit_id))"""
    )
    keys = ["sites", "visits", "chemical", "bacteria", "macro", "habitat", "visits_with_notes",
            "chem_on_wrong_method_visit", "bacteria_on_non_bact_visit", "empty_visits"]
    return dict(zip(keys, cur.fetchone()))


def run(path: Path, apply: bool, replace_computed_bio: bool = False) -> dict:
    import pandas as pd
    from openpyxl import load_workbook

    from etl.all_data_workbook import (
        CHLORIDE_APPLY_DIVIDE_BY_TEN, classify_data_condition, col,
        mapped_chem_values, parse_e_coli_result, read_all_data_sheet,
    )
    from etl.chem_recon import chem_fingerprint
    from etl.config import DATABASE_URL, database_name_from_url, refuse_if_protected_database
    from etl.db import get_conn
    from etl.visit_helpers import _date, _str, get_data_condition_id_map, insert_bacteria, insert_chemical

    refuse_if_protected_database(DATABASE_URL)
    if CHLORIDE_APPLY_DIVIDE_BY_TEN:
        raise RuntimeError("Refusing to run with chloride ÷10 correction enabled")
    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'APPLY' if apply else 'DRY RUN'}")
    print(f"Source: {path.name}")

    df, _ = read_all_data_sheet(path)
    wb = load_workbook(path, read_only=True, data_only=True)
    site_sheet = list(wb["SITES"].iter_rows(values_only=True))
    wb.close()
    site_header = [str(h).strip() if h else "" for h in site_sheet[0]]
    master_sites = {}
    for r in site_sheet[1:]:
        if r and r[0] and str(r[0]).strip():
            master_sites[str(r[0]).strip()] = dict(zip(site_header, r))

    report: Dict[str, object] = defaultdict(int)
    notes_unattached = Counter()
    bio_conflicts: List[str] = []

    with get_conn() as conn:
        cur = conn.cursor()
        before = _counts(cur)

        cur.execute("SELECT name, method_id FROM lst_method")
        method_map = dict(cur.fetchall())
        bat_id, bact_id = method_map["BAT"], method_map["BACT"]
        cond_map = get_data_condition_id_map(conn)

        # ---- 1. sites ----------------------------------------------------
        cur.execute("SELECT site_code, site_id FROM site")
        site_map = dict(cur.fetchall())
        cur.execute("SELECT site_id, count(*) FROM visit GROUP BY 1")
        visit_counts = dict(cur.fetchall())
        cur.execute("SELECT name, waterbody_id FROM waterbody")
        waterbodies = dict(cur.fetchall())

        master_codes = {(_str(c) or "") for c in df["Site"].dropna()}
        new_site_codes = set()
        alias: Dict[str, str] = {k: v for k, v in SITE_ALIASES.items() if v in site_map}
        for code in sorted(master_codes):
            if not code or code in site_map or code in alias:
                continue
            reuse = resolve_site_code(code, site_map, visit_counts)
            if reuse:
                alias[code] = reuse
                print(f"  site: {code} -> existing {reuse} (case-insensitive, no visits)")
                continue
            info = master_sites.get(code, {})
            lat, lon = info.get("Latitude"), info.get("Longitude")
            cur.execute(
                """INSERT INTO site (site_code, is_active, waterbody_id, description, latitude, longitude, notes)
                   VALUES (%s, true, %s, %s, %s, %s, %s) RETURNING site_id""",
                (code, waterbodies.get(info.get("Waterbody")), info.get("Description"),
                 lat if isinstance(lat, (int, float)) else None,
                 lon if isinstance(lon, (int, float)) else None,
                 "Added 2026-11-14 from All StreamWatch Data SITES sheet" + ("" if info else " (not in SITES sheet)")),
            )
            site_map[code] = cur.fetchone()[0]
            new_site_codes.add(code)
            print(f"  site: added {code}")
        report["sites_added"] = len(new_site_codes)

        def site_id_for(code):
            return site_map.get(alias.get(code, code))

        # Only sites with no visits at the start of this run get their master
        # chemistry/E. coli loaded here (keeps re-runs from loading twice).
        unloaded_site_ids = {
            site_id_for(c) for c in master_codes
            if c and site_id_for(c) is not None and visit_counts.get(site_id_for(c), 0) == 0
        }

        vi = VisitIndex(cur)

        # ---- 2. split results onto visits with the right method -----------
        cur.execute(
            """SELECT c.chemical_id, v.site_id, v.sample_date, c.method_id
               FROM chemical c JOIN visit v USING (visit_id)
               WHERE c.method_id IS NOT NULL AND c.method_id IS DISTINCT FROM v.method_id"""
        )
        for chem_id, sid, d, mid in cur.fetchall():
            target = vi.get_or_create(sid, d, mid)
            cur.execute("UPDATE chemical SET visit_id = %s WHERE chemical_id = %s", (target, chem_id))
            report["chemical_moved"] += 1
        cur.execute(
            """SELECT b.bacteria_id, v.site_id, v.sample_date
               FROM bacteria b JOIN visit v USING (visit_id)
               WHERE v.method_id IS DISTINCT FROM %s""",
            (bact_id,),
        )
        for bact_row, sid, d in cur.fetchall():
            target = vi.get_or_create(sid, d, bact_id)
            cur.execute("UPDATE bacteria SET visit_id = %s WHERE bacteria_id = %s", (target, bact_row))
            report["bacteria_moved"] += 1

        # ---- 3-6. walk master rows -----------------------------------------
        seen_fp = set()
        notes_by_visit: Dict[int, List[str]] = defaultdict(list)
        bio_targets = Counter()
        bio_rows = []
        hab_rows = []
        unresolved_conditions: List[str] = []

        for _, row in df.iterrows():
            code = _str(col(row, "Site"))
            d = _date(col(row, "Date"))
            if not code or not d:
                report["rows_without_site_or_date"] += 1
                continue
            sid = site_id_for(code)
            if sid is None:
                report["rows_site_unresolved"] += 1
                continue
            meth = _str(col(row, "Method"))
            mid = method_map.get(meth) if meth else None
            chem = mapped_chem_values(row)
            has_chem = any(v is not None for v in chem.values())
            e_coli, mod, _skip = parse_e_coli_result(row)
            bio = bio_values(row)
            hab = habitat_values(row)
            note = _str(col(row, "Notes"))
            cond = classify_data_condition(_str(col(row, "Data Condition")), cond_map, unresolved_conditions)
            dc_id = cond["data_condition_id"]

            if not (has_chem or e_coli is not None or bio or hab):
                report["rows_with_no_values"] += 1
                if note:
                    notes_unattached["row has no values"] += 1
                continue

            # 3. rows at newly added sites: chemistry + E. coli, as the original loader would
            if sid in unloaded_site_ids:
                if has_chem:
                    fp = chem_fingerprint(code, d, meth, chem)
                    if fp not in seen_fp:
                        seen_fp.add(fp)
                        insert_chemical(cur, vi.get_or_create(sid, d, mid), dc_id, mid, **chem)
                        report["newsite_chemical_added"] += 1
                if e_coli is not None:
                    insert_bacteria(cur, vi.get_or_create(sid, d, bact_id), dc_id,
                                    e_coli_mpn_100ml=e_coli,
                                    detection_limit_note=f"E. coli Mod.: {mod}" if mod else None)
                    report["newsite_bacteria_added"] += 1

            if bio:
                bio_rows.append((sid, d, code, bio, dc_id))
                bio_targets[(sid, d)] += 1
            if hab:
                hab_rows.append((sid, d, code, hab, dc_id))

            if note:
                # After the split every result sits on its own method's visit.
                vid = vi.get(sid, d, mid)
                if vid is None and (bio or hab) and mid == bat_id:
                    vid = vi.get_or_create(sid, d, bat_id)
                if vid is None:
                    notes_unattached["no visit for site/date/method"] += 1
                else:
                    notes_by_visit[vid].append(note)

        # 4. bio -> macro_analysis
        cur.execute(
            "SELECT visit_id, total_organisms, njis_score, hgmi_family, hgmi_genus, cpmi_score, fbi FROM macro_analysis"
        )
        existing_macro = {r[0]: dict(zip(["total_organisms", "njis_score", "hgmi_family", "hgmi_genus", "cpmi_score", "fbi"], r[1:]))
                          for r in cur.fetchall()}
        for sid, d, code, bio, dc_id in bio_rows:
            if bio_targets[(sid, d)] > 1:
                report["bio_skipped_multiple_rows_same_day"] += 1
                continue
            vid = vi.get_or_create(sid, d, bat_id)
            if vid in existing_macro:
                old = existing_macro[vid]
                diffs = [k for k, v in bio.items() if old.get(k) is not None and abs(float(old[k]) - float(v)) > 0.01]
                report["bio_already_present"] += 1
                if diffs:
                    bio_conflicts.append(f"{code} {d}: " + ", ".join(f"{k} db={old[k]} master={bio[k]}" for k in diffs))
                if replace_computed_bio:
                    # Master scores win; clear metrics derived by the old unvalidated calculation.
                    score_cols = [c for c, _ in BIO_COLUMNS.values()]
                    sets = ", ".join(f"{c} = %s" for c in score_cols + DERIVED_MACRO_COLUMNS)
                    cur.execute(
                        f"UPDATE macro_analysis SET {sets}, data_condition_id = %s, index_type = %s WHERE visit_id = %s",
                        [bio.get(c) for c in score_cols] + [None] * len(DERIVED_MACRO_COLUMNS)
                        + [dc_id, index_type(bio), vid],
                    )
                    report["bio_replaced_with_master"] += 1
                continue
            cols = ["visit_id", "data_condition_id", "index_type"] + list(bio)
            cur.execute(
                f"INSERT INTO macro_analysis ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                [vid, dc_id, index_type(bio)] + list(bio.values()),
            )
            existing_macro[vid] = bio
            report["bio_added"] += 1

        # 5. habitat
        cur.execute("SELECT visit_id FROM habitat_assessment")
        has_habitat = {r[0] for r in cur.fetchall()}
        for sid, d, code, hab, dc_id in hab_rows:
            vid = vi.get_or_create(sid, d, bat_id)
            if vid in has_habitat:
                report["habitat_already_present"] += 1
                continue
            cols = ["visit_id", "data_condition_id"] + list(hab)
            cur.execute(
                f"INSERT INTO habitat_assessment ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                [vid, dc_id] + list(hab.values()),
            )
            has_habitat.add(vid)
            report["habitat_added"] += 1

        # 6. notes
        if notes_by_visit:
            cur.execute("SELECT visit_id, notes FROM visit WHERE visit_id = ANY(%s)", (list(notes_by_visit),))
            current = dict(cur.fetchall())
            for vid, new in notes_by_visit.items():
                merged = merge_notes(current.get(vid), new)
                if merged != current.get(vid):
                    cur.execute("UPDATE visit SET notes = %s, updated_at = CURRENT_TIMESTAMP WHERE visit_id = %s", (merged, vid))
                    report["visits_notes_set"] += 1

        report["visits_created"] = vi.created
        after = _counts(cur)

        # ---- invariants ----------------------------------------------------
        if after["chemical"] != before["chemical"] + report["newsite_chemical_added"]:
            raise RuntimeError("chemical row count changed unexpectedly")
        if after["bacteria"] != before["bacteria"] + report["newsite_bacteria_added"]:
            raise RuntimeError("bacteria row count changed unexpectedly")
        if after["chem_on_wrong_method_visit"] != 0 or after["bacteria_on_non_bact_visit"] != 0:
            raise RuntimeError(f"results still on wrong-method visits: {after}")

        print("\n  " + "\n  ".join(f"{k}: {v}" for k, v in sorted(report.items())))
        print("  notes not attached:", dict(notes_unattached))
        print(f"  bio values that differ from existing macro rows: {len(bio_conflicts)}")
        for line in bio_conflicts[:15]:
            print("    " + line)
        print("\n  before:", before)
        print("  after: ", after)

        if not apply:
            conn.rollback()
            print("\nDRY RUN: rolled back, nothing changed. Re-run with --apply to commit.")
        else:
            print("\nAPPLIED.")
        return {"report": dict(report), "before": before, "after": after, "bio_conflicts": bio_conflicts}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", type=Path, default=DEFAULT_FILE)
    p.add_argument("--apply", action="store_true", help="commit changes (default is dry run)")
    p.add_argument("--replace-computed-bio", action="store_true",
                   help="overwrite existing macro_analysis scores with the master's values")
    args = p.parse_args(argv)
    run(args.file, apply=args.apply, replace_computed_bio=args.replace_computed_bio)


if __name__ == "__main__":
    main()
