#!/usr/bin/env python3
"""
Migrate Volunteer_Tracking.xlsm (Volunteers, Trainings, TrainingLog, Assignments) into volunteer, training, training_log, junc_assignments.
Expects: STREAMWATCH_DATA_DIR or VOLUNTEER_FILE pointing to Volunteer_Tracking.xlsm.
Sites must exist (run migrate_sites.py first) for assignments that reference site_code.
"""
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.config import VOLUNTEER_FILE
from etl.db import get_conn, ensure_lookup


def _str(v):
    if v is None or (hasattr(v, "__iter__") and not isinstance(v, str) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s if s else None


def _int(v):
    if v is None or pd.isna(v):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _date(v):
    if v is None or pd.isna(v):
        return None
    if hasattr(v, "date"):
        return v
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def run():
    if not VOLUNTEER_FILE.exists():
        print(f"Volunteer file not found: {VOLUNTEER_FILE}. Set STREAMWATCH_DATA_DIR or VOLUNTEER_FILE.")
        sys.exit(1)

    volunteers_df = pd.read_excel(VOLUNTEER_FILE, sheet_name="Volunteers")
    trainings_df = pd.read_excel(VOLUNTEER_FILE, sheet_name="Trainings") if "Trainings" in pd.ExcelFile(VOLUNTEER_FILE).sheet_names else pd.DataFrame()
    training_log_df = pd.read_excel(VOLUNTEER_FILE, sheet_name="TrainingLog") if "TrainingLog" in pd.ExcelFile(VOLUNTEER_FILE).sheet_names else pd.DataFrame()
    assignments_df = pd.read_excel(VOLUNTEER_FILE, sheet_name="Assignments") if "Assignments" in pd.ExcelFile(VOLUNTEER_FILE).sheet_names else pd.DataFrame()

    with get_conn() as conn:
        cur = conn.cursor()

        # Map VolunteerID -> volunteer_id (our PK)
        volunteer_id_map = {}

        for _, row in volunteers_df.iterrows():
            vid = _int(row.get("VolunteerID") or row.get("Volunteer Id"))
            first = _str(row.get("FirstName") or row.get("First Name"))
            last = _str(row.get("LastName") or row.get("Last Name"))
            if not first and not last:
                continue
            first = first or ""
            last = last or ""

            city_id = None
            city = _str(row.get("City"))
            if city:
                city_id = ensure_lookup(conn, "municipality", "municipality_id", "name", city)

            status = _str(row.get("Status")) or "Unknown"
            if status not in ("Active", "Inactive", "Parent", "Unknown"):
                status = "Unknown"

            active_cat = str(row.get("Active CAT", "")).strip().lower() in ("1", "true", "yes", "x")
            active_bat = str(row.get("Active BAT", "")).strip().lower() in ("1", "true", "yes", "x")
            active_bact = str(row.get("Active BACT", "")).strip().lower() in ("1", "true", "yes", "x")
            is_under_17 = str(row.get("Under 16?", row.get("Under 16", ""))).strip().lower() in ("1", "true", "yes", "x")
            parent_id = _int(row.get("Parent ID") or row.get("ParentId"))

            cur.execute("""
                INSERT INTO volunteer (
                    first_name, last_name, perfect_id, is_under_17, email, address, city_id, state, zip_code,
                    active_cat, active_bat, active_bact, status, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(NULLIF(%s, ''), 'NJ'), %s, %s, %s, %s, %s, %s)
                RETURNING volunteer_id
                """, (
                    first, last, _str(row.get("DPID") or row.get("Perfect_ID")), is_under_17,
                    _str(row.get("Email")), _str(row.get("Address")), city_id, _str(row.get("State")), _str(row.get("Zip_code") or row.get("Zip")),
                    active_cat, active_bat, active_bact, status, _str(row.get("Notes")),
                ))
            new_id = cur.fetchone()[0]
            if vid is not None:
                volunteer_id_map[vid] = new_id
            else:
                volunteer_id_map[len(volunteer_id_map)] = new_id  # fallback by order

        # If no VolunteerID column, map by row index to our inserted order (assume insert order = row order)
        if "VolunteerID" not in volunteers_df.columns and "Volunteer Id" not in volunteers_df.columns:
            volunteer_id_map = {i: list(volunteer_id_map.values())[i] for i in range(len(volunteer_id_map))}

        # Trainings
        training_id_map = {}
        for _, row in trainings_df.iterrows():
            tid = _int(row.get("TrainingID") or row.get("Training Id"))
            tt = _str(row.get("TrainingType") or row.get("Training Type"))
            if tt:
                training_type_id = ensure_lookup(conn, "lst_training_type", "training_type_id", "name", tt)
            else:
                training_type_id = None
            training_date = _date(row.get("TrainingDate") or row.get("Training Date"))
            if not training_date:
                continue
            cur.execute("""
                INSERT INTO training (training_type_id, training_date, trainer, location, notes, total_attendees)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING training_id
                """, (training_type_id, training_date, _str(row.get("Trainer")), _str(row.get("Location")),
                     _str(row.get("Notes")), _int(row.get("Total Attendees"))))
            new_tid = cur.fetchone()[0]
            if tid is not None:
                training_id_map[tid] = new_tid

        # TrainingLog
        for _, row in training_log_df.iterrows():
            tl_tid = _int(row.get("TrainingID") or row.get("Training Id"))
            tl_vid = _int(row.get("VolunteerID") or row.get("Volunteer Id"))
            if tl_tid is None or tl_vid is None:
                continue
            our_tid = training_id_map.get(tl_tid)
            our_vid = volunteer_id_map.get(tl_vid)
            if our_tid is None or our_vid is None:
                continue
            cur.execute("""
                INSERT INTO training_log (training_id, volunteer_id, status, expiration_date)
                VALUES (%s, %s, %s, %s) ON CONFLICT (training_id, volunteer_id) DO UPDATE SET status = EXCLUDED.status, expiration_date = EXCLUDED.expiration_date
                """, (our_tid, our_vid, _str(row.get("Status")), _date(row.get("ExpirationDate") or row.get("Expiration Date"))))

        # Assignments: need site_id by site_code. Get site codes from Sites_Live or from Assignments if it has SiteID/SiteCode
        cur.execute("SELECT site_id, site_code FROM site")
        site_code_to_id = {r[1]: r[0] for r in cur.fetchall()}
        role_name_to_id = {}
        cur.execute("SELECT role_id, name FROM lst_role")
        for r in cur.fetchall():
            role_name_to_id[r[1]] = r[0]

        for _, row in assignments_df.iterrows():
            v_id = _int(row.get("VolunteerID") or row.get("Volunteer Id"))
            site_id = _int(row.get("SiteID") or row.get("Site Id"))
            site_code = _str(row.get("SiteCode") or row.get("Site Code"))
            # Resolve site: Assignments may have SiteCode (e.g. AC1) or numeric ID
            if site_id is not None and site_id not in set(site_code_to_id.values()):
                site_id = None
            if site_id is None and site_code:
                site_id = site_code_to_id.get(site_code)
            if site_id is None:
                continue
            our_vid = volunteer_id_map.get(v_id) if v_id is not None else None
            if our_vid is None:
                continue
            role = _str(row.get("Role"))
            role_id = role_name_to_id.get(role) if role else None
            cur.execute("""
                INSERT INTO junc_assignments (volunteer_id, site_id, role_id, start_date, end_date)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT (volunteer_id, site_id) DO NOTHING
                """, (our_vid, site_id, role_id, _date(row.get("StartDate") or row.get("Start Date")), _date(row.get("EndDate") or row.get("End Date"))))

    print("Volunteers migration done.")


if __name__ == "__main__":
    run()
