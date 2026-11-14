#!/usr/bin/env python3
"""
Data audit: reconcile every source file with the database.

For each source sheet, compare what the file contains with what the database
holds, and explain every difference. For All StreamWatch Data (ALL DATA) this
is row by row: every one of its rows is matched to the result(s) it produced,
and every chemistry/E. coli row in the database is checked to come from a
workbook row. Results are saved so the app can show them at /qa/audit (the
live server doesn't have the source files).

Statuses:  match      counts agree
           explained  counts differ for a documented reason
           gap        something is missing or wrong and needs action
           info       context, nothing to reconcile

Read-only unless --apply, which saves a new audit run (and replaces the
row-level trace with this run's).

Usage: python -m etl.audit_sources [--data-dir DIR] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "Watershed Data" / "Data"
MASTER = "All StreamWatch Data - 2026.10.26.xlsx"


class Report:
    def __init__(self):
        self.checks = []
        self.rows = []
        self.summary = {}

    def add(self, source, sheet, item, source_count, db_count, status, explanation):
        self.checks.append(dict(source=source, sheet=sheet, item=item, source_count=source_count,
                                db_count=db_count, status=status, explanation=explanation))


def _num(v):
    try:
        f = float(v)
        return round(f, 6)
    except (TypeError, ValueError):
        return None


def _same_at_stored_precision(stored, source, fields):
    """Equal to 4 decimals: what NUMERIC(_,4) can hold. Temperatures (2 decimals) that
    only differ by rounding are reported separately as 'rounded'."""
    for f in fields:
        a, b = stored.get(f), source.get(f)
        if (a is None) != (b is None):
            return False
        if a is not None and abs(float(a) - float(b)) > 0.0005:
            return False
    return True


# --------------------------------------------------------------------------
# All StreamWatch Data
# --------------------------------------------------------------------------
def audit_master(rep: Report, cur, data_dir: Path):
    import pandas as pd
    from etl.all_data_workbook import (classify_data_condition, col, mapped_chem_values,
                                       parse_e_coli_result, read_all_data_sheet)
    from etl.backfill_source_conditions import CHEM_FIELDS, is_compound, normalize_condition
    from etl.fill_master_gaps import SITE_ALIASES, bio_values, habitat_values
    from etl.visit_helpers import _date, _str

    path = data_dir / MASTER
    df, header_row = read_all_data_sheet(path)

    cur.execute("SELECT site_code, site_id FROM site")
    sites = dict(cur.fetchall())
    cur.execute("SELECT name, method_id FROM lst_method")
    meth = dict(cur.fetchall())
    cur.execute("SELECT code, data_condition_id FROM data_condition")
    cond_map = dict(cur.fetchall())
    code_by_id = {v: k for k, v in cond_map.items()}
    cur.execute("SELECT site_id, sample_date, method_id, visit_id, COALESCE(notes, '') FROM visit")
    visits, notes = {}, {}
    for s, d, m, v, n in cur.fetchall():
        visits.setdefault((s, d, m), v)
        notes[v] = n
    cur.execute(f"SELECT chemical_id, visit_id, data_condition_id, source_data_condition, {', '.join(CHEM_FIELDS)} FROM chemical")
    chem = defaultdict(list)
    for r in cur.fetchall():
        chem[r[1]].append((r[0], r[2], r[3], dict(zip(CHEM_FIELDS, r[4:]))))
    cur.execute("SELECT bacteria_id, visit_id, e_coli_mpn_100ml FROM bacteria")
    bact = defaultdict(list)
    for r in cur.fetchall():
        bact[r[1]].append(r)
    cur.execute("SELECT visit_id FROM macro_analysis")
    macro = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT visit_id FROM habitat_assessment")
    hab = {r[0] for r in cur.fetchall()}

    used_chem, used_bact, seen = set(), set(), set()
    c = Counter()
    rounding_rows, cond_mismatch = 0, []
    for idx, row in df.iterrows():
        excel_row = header_row + 2 + int(idx)
        code = _str(col(row, "Site"))
        d = _date(col(row, "Date"))
        mname = _str(col(row, "Method"))
        raw_cond = _str(col(row, "Data Condition"))
        rec = dict(source="ALL DATA", row_number=excel_row, site_code=code, sample_date=d, method=mname,
                   outcome="", detail={}, visit_id=None, chemical_id=None, bacteria_id=None)
        rep.rows.append(rec)
        c["rows"] += 1
        if raw_cond:
            rec["detail"]["condition"] = raw_cond
        if not code or not d:
            rec["outcome"] = "Not loaded: no site or date"; c["no_site_date"] += 1
            continue
        sid = sites.get(SITE_ALIASES.get(code, code))
        mid = meth.get(mname) if mname else None
        chemv = {k: v for k, v in mapped_chem_values(row).items() if v is not None}
        ec, mod, _ = parse_e_coli_result(row)
        bio, hb = bio_values(row), habitat_values(row)
        note = _str(col(row, "Notes"))
        if chemv:
            rec["detail"]["values"] = {k: _num(v) for k, v in chemv.items()}
        if ec is not None:
            rec["detail"]["e_coli"] = ec
            if mod:
                rec["detail"]["e_coli_modifier"] = mod
        if bio:
            rec["detail"]["bug_scores"] = {k: _num(v) for k, v in bio.items()}
        if note:
            rec["detail"]["note"] = note
        if not (chemv or ec is not None or bio or hb):
            rec["outcome"] = "Not loaded: no values recorded"; c["no_values"] += 1
            continue
        if sid is None:
            rec["outcome"] = "GAP: site not in database"; c["site_missing"] += 1
            continue
        parts = []
        if chemv:
            c["chem_rows"] += 1
            vid = visits.get((sid, d, mid))
            rec["visit_id"] = vid
            full = mapped_chem_values(row)
            exact = [x for x in chem.get(vid, []) if x[0] not in used_chem and _same_at_stored_precision(x[3], full, CHEM_FIELDS)]
            near = exact or [x for x in chem.get(vid, []) if x[0] not in used_chem and all(
                (x[3].get(f) is None) == (full.get(f) is None) and (full.get(f) is None or abs(float(x[3][f]) - float(full[f])) < 0.006)
                for f in CHEM_FIELDS)]
            fp = (sid, d, mid, tuple(sorted(chemv.items())))
            if near:
                hit = near[0]
                used_chem.add(hit[0]); rec["chemical_id"] = hit[0]
                if exact:
                    c["chem_loaded"] += 1; parts.append("chemistry loaded")
                else:
                    c["chem_rounded"] += 1; rounding_rows += 1; parts.append("chemistry loaded (temperature rounded to 0.01 °C)")
                stored_cond = code_by_id.get(hit[1]) if hit[1] else hit[2]
                if raw_cond:
                    want = normalize_condition(raw_cond) if is_compound(raw_cond) else raw_cond
                    if not stored_cond or stored_cond.replace("_", " ").lower() != want.replace("_", " ").lower():
                        cond_mismatch.append((code, str(d), mname, raw_cond, stored_cond))
            elif fp in seen:
                c["chem_duplicate"] += 1; parts.append("chemistry identical to an earlier row (stored once)")
            else:
                c["chem_missing"] += 1; parts.append("GAP: chemistry not in database")
            seen.add(fp)
        if ec is not None:
            c["ecoli_rows"] += 1
            vid = visits.get((sid, d, meth["BACT"]))
            hits = [b for b in bact.get(vid, []) if b[0] not in used_bact and b[2] == ec]
            if hits:
                used_bact.add(hits[0][0]); rec["bacteria_id"] = hits[0][0]; rec["visit_id"] = rec["visit_id"] or vid
                c["ecoli_loaded"] += 1; parts.append("E. coli loaded")
            else:
                c["ecoli_missing"] += 1; parts.append("GAP: E. coli not in database")
        if bio:
            c["bio_rows"] += 1
            vid = visits.get((sid, d, meth["BAT"]))
            if vid in macro:
                c["bio_loaded"] += 1; parts.append("bug scores loaded"); rec["visit_id"] = rec["visit_id"] or vid
            elif raw_cond and "Duplicate" in raw_cond:
                c["bio_duplicate"] += 1; parts.append("bug scores not loaded: marked Duplicate (two rows for one sample)")
            else:
                c["bio_missing"] += 1; parts.append("GAP: bug scores not in database")
        if hb:
            c["hab_rows"] += 1
            vid = visits.get((sid, d, meth["BAT"]))
            if vid in hab:
                c["hab_loaded"] += 1; parts.append("habitat loaded")
            else:
                c["hab_missing"] += 1; parts.append("GAP: habitat not in database")
        if note:
            c["note_rows"] += 1
            nvid = visits.get((sid, d, mid))
            if nvid and note in notes.get(nvid, ""):
                c["note_loaded"] += 1
            else:
                c["note_missing"] += 1; parts.append("GAP: note not on visit")
        rec["outcome"] = "; ".join(parts)[:1].upper() + "; ".join(parts)[1:]

    total_chem = sum(len(v) for v in chem.values())
    total_bact = sum(len(v) for v in bact.values())
    cur.execute("SELECT count(*) FROM macro_analysis")
    total_macro = cur.fetchone()[0]

    src = "All StreamWatch Data"
    rep.add(src, "ALL DATA", "Workbook rows", c["rows"], c["rows"] - c["no_site_date"] - c["no_values"], "explained",
            f"{c['no_values']:,} rows have no measurements recorded (mostly “Incomplete”) and {c['no_site_date']} have no site or date; every other row is loaded.")
    chem_status = "match" if c["chem_missing"] == 0 and total_chem == len(used_chem) else "gap"
    rep.add(src, "ALL DATA", "Chemistry readings", c["chem_rows"], total_chem, chem_status,
            f"{c['chem_loaded'] + c['chem_rounded']:,} rows match a stored result ({c['chem_rounded']} with temperatures rounded to 0.01 °C, "
            f"max difference 0.005 °C); {c['chem_duplicate']} rows repeat an earlier row exactly and are stored once. "
            f"{total_chem - len(used_chem)} stored results have no workbook row; {c['chem_missing']} workbook rows are missing.")
    rep.add(src, "ALL DATA", "E. coli results", c["ecoli_rows"], total_bact,
            "match" if c["ecoli_missing"] == 0 and total_bact == len(used_bact) else "gap",
            f"Every E. coli result matches one workbook row; {total_bact - len(used_bact)} stored results have no workbook row.")
    rep.add(src, "ALL DATA", "Bug-index scores", c["bio_rows"], total_macro, "explained",
            f"{c['bio_loaded']} rows loaded. {c['bio_duplicate']} rows are two pairs Watershed marked “Duplicate” (SB1 2018-10-30, SB3 2018-10-20) "
            f"and are not loaded until the right one is chosen. {total_macro - c['bio_loaded']} stored scores have no workbook row "
            f"(older computed values for BB1 2014-03-15, CB2 2015-07-19, SM1 2015-07-23).")
    rep.add(src, "ALL DATA", "Habitat scores", c["hab_rows"], c["hab_loaded"], "match" if c["hab_missing"] == 0 else "gap",
            "Every habitat row is on its BAT visit.")
    rep.add(src, "ALL DATA", "Notes", c["note_rows"], c["note_loaded"], "match" if c["note_missing"] == 0 else "gap",
            "Every note is on its visit (several rows can share one visit).")
    rep.add(src, "ALL DATA", "Data Conditions", c["chem_loaded"] + c["chem_rounded"], c["chem_loaded"] + c["chem_rounded"] - len(cond_mismatch),
            "match" if not cond_mismatch else "gap",
            "Every stored chemistry result carries the workbook's Data Condition (single codes as codes, combined ones as written)."
            if not cond_mismatch else f"{len(cond_mismatch)} results differ, e.g. {cond_mismatch[:3]}")
    rep.summary["master_rows"] = c["rows"]
    rep.summary["master_rows_loaded"] = c["rows"] - c["no_site_date"] - c["no_values"]
    return path.name


# --------------------------------------------------------------------------
# Other sources
# --------------------------------------------------------------------------
def audit_sites(rep: Report, cur, data_dir: Path):
    from openpyxl import load_workbook
    from etl.fill_master_gaps import SITE_ALIASES
    cur.execute("SELECT site_code FROM site")
    db_sites = {r[0] for r in cur.fetchall()}
    wb = load_workbook(data_dir / MASTER, read_only=True, data_only=True)
    codes = [str(r[0]).strip() for r in list(wb["SITES"].iter_rows(values_only=True))[1:164] if r and r[0]]
    wb.close()
    missing = [c for c in codes if SITE_ALIASES.get(c, c) not in db_sites]
    rep.add("All StreamWatch Data", "SITES", "Sites", len(codes), len(codes) - len(missing), "match" if not missing else "gap",
            "Every site in the master list is in the database (ELY is stored as the existing Ely)." if not missing else f"Missing: {missing}")
    import pandas as pd
    loc = pd.read_excel(data_dir / "2025 StreamWatch Locations.xlsx", sheet_name="SWSites_2024")
    col = next(c for c in loc.columns if "site" in str(c).lower() and "code" in str(c).lower()) if any("code" in str(c).lower() for c in loc.columns) else loc.columns[3]
    loc_codes = {str(v).strip() for v in loc[col].dropna()}
    missing_loc = sorted(c for c in loc_codes if c not in db_sites)
    rep.add("2025 StreamWatch Locations", "SWSites_2024", "Sites", len(loc_codes), len(loc_codes) - len(missing_loc),
            "match" if not missing_loc else "gap", "Every site in the locations workbook is in the database." if not missing_loc else f"Missing: {missing_loc}")
    rep.summary["sites_db"] = len(db_sites)


def audit_bat(rep: Report, cur, data_dir: Path):
    import pandas as pd
    f = data_dir / "tblSampleDates.xlsx"
    sd = pd.read_excel(f, sheet_name="tblSampleDates")
    br = pd.read_excel(f, sheet_name="tblBugResults")
    rb = pd.read_excel(f, sheet_name="tblRBP100Bugs")
    bl = pd.read_excel(f, sheet_name="BugList")
    dated = set(sd.dropna(subset=["Station", "SampleDate"])["SampleID"].astype(int))
    undated = sd[sd["Station"].isna() | sd["SampleDate"].isna()]
    orph_br = br[~br["SampleID"].isin(dated)]
    orph_rb = rb[~rb["SampleID"].isin(dated)]
    cur.execute("SELECT count(DISTINCT visit_id) FROM bug_count"); n_samples = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM bug_count"); n_bc = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM rbp100_bug"); n_rb = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM bug_list"); n_bl = cur.fetchone()[0]
    src = "BAT lab history (tblSampleDates.xlsx)"
    rep.add(src, "tblSampleDates", "Bug samples", len(sd), n_samples, "explained",
            f"{len(undated)} sample has no date ({', '.join(str(x) for x in undated['SampleCode'])}) and no counts, so nothing is lost.")
    ids = sorted({int(x) for x in pd.concat([orph_br["SampleID"], orph_rb["SampleID"]]).dropna()})
    rep.add(src, "tblBugResults", "Taxon counts", len(br), n_bc, "gap" if len(orph_br) else "match",
            f"{len(orph_br)} counts belong to samples {ids} that are not in tblSampleDates and have no sample code, so they can't be placed on a site or date. Every other count is loaded.")
    rep.add(src, "tblRBP100Bugs", "100-organism subsample counts", len(rb), n_rb, "gap" if len(orph_rb) else "match",
            f"{len(orph_rb)} counts belong to samples {ids} (same issue). Every other count is loaded.")
    rep.add(src, "BugList", "Taxa", len(bl), n_bl, "match" if len(bl) == n_bl else "explained", "Every taxon is in the taxa list.")


def audit_habitat_form(rep: Report, cur, data_dir: Path):
    from etl.bat_reconcile import read_habitat_workbook
    from etl.load_bat_habitat import _attach_visits, plan_rows
    records, _ = read_habitat_workbook(data_dir / "BAT Habitat Data to be entered.xlsx")
    _attach_visits(cur, records)
    vids = sorted({v["visit_id"] for r in records for v in r["visits"]})
    info = {}
    if vids:
        cur.execute("""SELECT v.visit_id, COALESCE(m.name = 'BAT', false),
                              EXISTS (SELECT 1 FROM habitat_assessment h WHERE h.visit_id = v.visit_id)
                       FROM visit v LEFT JOIN lst_method m USING (method_id) WHERE v.visit_id = ANY(%s)""", (vids,))
        info = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    loads, skips = plan_rows(records, info)
    reasons = Counter()
    for rec, reason in skips:
        key = ("already loaded" if "already has habitat" in reason else
               "2026 (no visits yet)" if str(rec.get("sample_date", "")).startswith("2026") else
               "no BAT visit that day" if "no visit" in reason or "not a BAT visit" in reason else reason.split(":")[0])
        reasons[key] += 1
    loaded = reasons.pop("already loaded", 0)
    rep.add("BAT habitat forms", "Form Responses 1", "Habitat assessments", len(records), loaded,
            "explained" if not loads else "gap",
            f"{loaded} loaded. Not loaded: " + ", ".join(f"{n} {k}" for k, n in reasons.most_common()) +
            ". Two sites (COL2, Colonial Lake Outfall) aren't in any site list.")


def audit_volunteers(rep: Report, cur, data_dir: Path):
    import etl.migrate_volunteers as mv
    f = data_dir / "Volunteer_Tracking.xlsm"
    vol, _ = mv._read_sheet(f, "Volunteers", ("VolunteerID",))
    tr, _ = mv._read_sheet(f, "Trainings", ("TrainingID",))
    tl, _ = mv._read_sheet(f, "TrainingLog", ("TrainingID", "VolunteerID"))
    asg, _ = mv._read_sheet(f, "Assignments", ("VolunteerID",))
    asg = asg.dropna(subset=["VolunteerID"])
    norm = lambda s: s.dropna().astype(str).str.replace(r"\.0$", "", regex=True)
    vids, tids = set(norm(vol["VolunteerID"])), set(norm(tr["TrainingID"]))
    bad_tl = [(t, v) for t, v in zip(norm(tl["TrainingID"]), norm(tl["VolunteerID"])) if v not in vids or t not in tids]
    cur.execute("SELECT count(*), count(*) FILTER (WHERE created_at::date = '2026-09-10') FROM volunteer"); n_vol, n_vol_loaded = cur.fetchone()
    cur.execute("SELECT count(*) FROM training"); n_tr = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM training_log"); n_tl = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM junc_assignments"); n_as = cur.fetchone()[0]
    src = "Volunteer tracking (Volunteer_Tracking.xlsm)"
    rep.add(src, "Volunteers", "Volunteers", len(vol), n_vol, "match" if n_vol_loaded == len(vol) and n_vol == len(vol) else "gap",
            f"All {n_vol_loaded} volunteers in the workbook are loaded." + (f" {n_vol - n_vol_loaded} more was entered through the app (see “Entered through the app”)." if n_vol > n_vol_loaded else ""))
    rep.add(src, "Trainings", "Training sessions", len(tr), n_tr, "match" if len(tr) == n_tr else "gap", "Every training session is loaded.")
    rep.add(src, "TrainingLog", "Training records", len(tl), n_tl, "gap" if bad_tl else "match",
            ("Every record is loaded except " + ", ".join(f"training {t} for volunteer {v}" for t, v in bad_tl) +
             ": that volunteer ID isn't in the Volunteers sheet.") if bad_tl else "Every training record is loaded.")
    rep.add(src, "Assignments", "Site assignments", len(asg), n_as, "match" if len(asg) == n_as else "gap", "Every assignment is loaded.")


def audit_meters(rep: Report, cur, data_dir: Path):
    from openpyxl import load_workbook
    import etl.migrate_equipment as me
    from etl.load_meter_sensors import read_sensor_sheet
    f = data_dir / "CAT Meter Tracking v.1.xlsx"
    sensors = read_sensor_sheet(f)
    wb = load_workbook(f, data_only=True)
    parsed = {}
    for year in ("2024", "2025", "2026"):
        blocks, stats = me._parse_testing_sheet(wb[f"{year} Testing"], year)
        parsed[year] = (sum(len(b["measurements"]) for b in blocks), stats)
    wb.close()
    cur.execute("SELECT count(*) FROM equipment"); n_eq = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM sensor"); n_sensor = cur.fetchone()[0]
    cur.execute("""SELECT extract(year FROM s.date_start)::int, count(*) FROM meter_testing mt JOIN session s USING (session_id)
                   WHERE mt.created_at::date = '2026-09-10' GROUP BY 1""")
    by_year = dict(cur.fetchall())
    src = "Meter tracking (CAT Meter Tracking v.1.xlsx)"
    rep.add(src, "Sensors", "Meters", len(sensors), n_eq, "match" if len(sensors) == n_eq else "gap", "Every meter is loaded.")
    rep.add(src, "Sensors", "Sensors (DO, pH, EC)", len(sensors) * 3, n_sensor, "match" if n_sensor == len(sensors) * 3 else "gap",
            "One DO, pH and EC sensor per meter, with the date each was last changed (loaded 2026-11-14; the original loader misread the sheet).")
    for year in ("2024", "2025"):
        n_src, stats = parsed[year]
        rep.add(src, f"{year} Testing", f"Meter test readings {year}", n_src, by_year.get(int(year), 0),
                "match" if n_src == by_year.get(int(year), 0) else "explained",
                "Every dated reading is loaded." + (f" {stats['blocks_skipped_no_date']} test rounds have no test date in the sheet and were skipped." if stats["blocks_skipped_no_date"] else ""))
    rep.add(src, "2026 Testing", "Meter test readings 2026", parsed["2026"][0], by_year.get(2026, 0), "info",
            "The 2026 sheet is an empty template (no dates or readings yet).")
    rep.add(src, "Tracking", "Pass/fail outcomes", None, 0, "gap",
            "The quarterly pass/fail summary (P1, F1, C-F3…) isn't loaded, and the testing sheets record differences rather than outcomes, so stored tests have no pass/fail. Waiting on Watershed's redesigned meter process.")
    rep.add(src, "Assignments", "Meter ↔ volunteer assignments", None, 0, "gap",
            "Not loaded: volunteers are written as free text (e.g. two names with relatives in brackets) that doesn't link reliably to volunteer records.")


def audit_app_entries(rep: Report, cur):
    rows = []
    for table, label in (("site", "site_code"), ("visit", "visit_id::text"), ("chemical", "chemical_id::text"),
                         ("bacteria", "bacteria_id::text"), ("volunteer", "first_name || ' ' || last_name"),
                         ("training", "training_id::text"), ("training_log", "training_log_id::text"),
                         ("junc_assignments", "assignment_id::text"), ("equipment", "equipment_code"),
                         ("session", "session_id::text"), ("meter_testing", "meter_testing_id::text"),
                         ("habitat_assessment", "habitat_id::text"), ("bug_count", "bug_count_id::text")):
        cur.execute(f"SELECT {label}, created_at::date FROM {table} WHERE created_at::date NOT IN ('2026-09-10', '2026-11-14')")
        rows += [(table, r[0], r[1]) for r in cur.fetchall()]
    rep.add("Entered through the app", None, "Records not from a source file", None, len(rows), "gap" if rows else "match",
            ("Records created through the app's forms rather than a source file: " + "; ".join(f"{t} {n} ({d})" for t, n, d in rows) +
             ". These look like test entries (a volunteer named “Michael Angelo Kim” with a joke note and a meter test dated 1492) and should be removed.")
            if rows else "Every record comes from a source file load.")
    rep.summary["app_entries"] = len(rows)


def audit_pending(rep: Report):
    rep.add("2026 season files", None, "BACT and HAB 2026, 2026 BAT lab results", None, None, "info",
            "Not loaded yet: waiting on Watershed's 2026 update to All StreamWatch Data (with Data Conditions) and two new site codes (COL2, Colonial Lake Outfall).")


def run(data_dir: Path, apply: bool):
    from psycopg2.extras import execute_values
    from etl.config import DATABASE_URL, database_name_from_url
    from etl.db import get_conn

    print(f"Target database: {database_name_from_url(DATABASE_URL)!r}  mode: {'SAVE' if apply else 'PREVIEW'}")
    rep = Report()
    with get_conn() as conn:
        cur = conn.cursor()
        audit_master(rep, cur, data_dir)
        audit_sites(rep, cur, data_dir)
        audit_habitat_form(rep, cur, data_dir)
        audit_bat(rep, cur, data_dir)
        audit_volunteers(rep, cur, data_dir)
        audit_meters(rep, cur, data_dir)
        audit_app_entries(rep, cur)
        audit_pending(rep)
        status = Counter(c["status"] for c in rep.checks)
        rep.summary.update({"checks": len(rep.checks), **{f"status_{k}": v for k, v in status.items()},
                            "trace_rows": len(rep.rows), "source_files": sorted({c["source"] for c in rep.checks})})
        for c in rep.checks:
            mark = {"match": "✓", "explained": "~", "gap": "✗", "info": "i"}[c["status"]]
            print(f"  {mark} {c['source'][:34]:34s} {str(c['sheet'] or '')[:16]:16s} {c['item'][:34]:34s} "
                  f"{'' if c['source_count'] is None else c['source_count']:>7} {'' if c['db_count'] is None else c['db_count']:>7}")
        print("  outcomes:", Counter(r["outcome"] for r in rep.rows).most_common(8))
        if not apply:
            conn.rollback()
            print("PREVIEW only. Re-run with --apply to save this audit run.")
            return rep
        cur.execute("INSERT INTO audit_run (summary) VALUES (%s) RETURNING run_id", (json.dumps(rep.summary),))
        run_id = cur.fetchone()[0]
        execute_values(cur, """INSERT INTO audit_check (run_id, sort_order, source, sheet, item, source_count, db_count, status, explanation)
                               VALUES %s""",
                       [(run_id, i, c["source"], c["sheet"], c["item"], c["source_count"], c["db_count"], c["status"], c["explanation"])
                        for i, c in enumerate(rep.checks)])
        cur.execute("DELETE FROM audit_source_row")
        execute_values(cur, """INSERT INTO audit_source_row (run_id, source, row_number, site_code, sample_date, method, outcome, detail,
                                                             visit_id, chemical_id, bacteria_id) VALUES %s""",
                       [(run_id, r["source"], r["row_number"], r["site_code"], r["sample_date"], r["method"], r["outcome"],
                         json.dumps(r["detail"], default=str), r["visit_id"], r["chemical_id"], r["bacteria_id"]) for r in rep.rows],
                       page_size=2000)
        print(f"SAVED audit run {run_id}: {len(rep.checks)} checks, {len(rep.rows):,} traced rows.")
    return rep


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)
    run(args.data_dir, apply=args.apply)


if __name__ == "__main__":
    main()
