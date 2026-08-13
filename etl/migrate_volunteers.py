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
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    # Scalar missing values (float NaN, pd.NA, etc.). Skip pd.isna on collection-like
    # values so it does not return an array and break truth-value testing.
    if not hasattr(v, "__iter__"):
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
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


def _detect_header_row(path, sheet_name, labels, max_scan=15):
    """
    Find the header row by requiring all labels to appear as cell values (case-insensitive).
    Specific to Volunteer_Tracking.xlsm sheets that often have blank title rows above the table.
    """
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=max_scan, engine="openpyxl")
    wanted = {lab.strip().lower() for lab in labels}
    for i in range(len(raw)):
        cells = {str(v).strip().lower() for v in raw.iloc[i].tolist() if pd.notna(v)}
        if wanted.issubset(cells):
            return i
    return 0


def _read_sheet(path, sheet_name, labels):
    """Read a sheet using a detected header row. Returns (dataframe, header_row_index)."""
    header = _detect_header_row(path, sheet_name, labels)
    df = pd.read_excel(path, sheet_name=sheet_name, header=header, engine="openpyxl")
    return df, header


def run():
    if not VOLUNTEER_FILE.exists():
        print(f"Volunteer file not found: {VOLUNTEER_FILE}. Set STREAMWATCH_DATA_DIR or VOLUNTEER_FILE.")
        sys.exit(1)

    xl = pd.ExcelFile(VOLUNTEER_FILE, engine="openpyxl")
    sheet_names = set(xl.sheet_names)

    volunteers_df, volunteers_header = _read_sheet(
        VOLUNTEER_FILE, "Volunteers", ("VolunteerID", "FirstName")
    )
    trainings_df, trainings_header = (
        _read_sheet(VOLUNTEER_FILE, "Trainings", ("TrainingID", "TrainingDate"))
        if "Trainings" in sheet_names else (pd.DataFrame(), None)
    )
    training_log_df, training_log_header = (
        _read_sheet(VOLUNTEER_FILE, "TrainingLog", ("TrainingID", "VolunteerID"))
        if "TrainingLog" in sheet_names else (pd.DataFrame(), None)
    )
    assignments_df, assignments_header = (
        _read_sheet(VOLUNTEER_FILE, "Assignments", ("VolunteerID", "SiteID"))
        if "Assignments" in sheet_names else (pd.DataFrame(), None)
    )

    volunteers_inserted = 0
    volunteers_skipped_no_name = 0
    trainings_inserted = 0
    trainings_skipped_no_date = 0
    training_log_inserted = 0
    training_log_skipped_unresolved = 0
    assignments_inserted = 0
    assignments_skipped_unresolved_site = 0
    assignments_skipped_unresolved_volunteer = 0

    with get_conn() as conn:
        cur = conn.cursor()

        # Map VolunteerID -> volunteer_id (our PK)
        volunteer_id_map = {}

        for _, row in volunteers_df.iterrows():
            vid = _int(row.get("VolunteerID") or row.get("Volunteer Id"))
            first = _str(row.get("FirstName") or row.get("First Name"))
            last = _str(row.get("LastName") or row.get("Last Name"))
            if not first and not last:
                volunteers_skipped_no_name += 1
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

            cur.execute("""
                INSERT INTO volunteer (
                    first_name, last_name, perfect_id, is_under_17, email, address, city_id, state, zip_code,
                    active_cat, active_bat, active_bact, status, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(NULLIF(%s, ''), 'NJ'), %s, %s, %s, %s, %s, %s)
                RETURNING volunteer_id
                """, (
                    first, last, _str(row.get("DPID") or row.get("Perfect_ID")), is_under_17,
                    _str(row.get("Email")),
                    _str(row.get("Address") or row.get("Street")),
                    city_id, _str(row.get("State")), _str(row.get("Zip_code") or row.get("Zip")),
                    active_cat, active_bat, active_bact, status, _str(row.get("Notes")),
                ))
            new_id = cur.fetchone()[0]
            volunteers_inserted += 1
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
                trainings_skipped_no_date += 1
                continue
            cur.execute("""
                INSERT INTO training (training_type_id, training_date, trainer, location, notes, total_attendees)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING training_id
                """, (training_type_id, training_date, _str(row.get("Trainer")), _str(row.get("Location")),
                     _str(row.get("Notes")), _int(row.get("Total Attendees"))))
            new_tid = cur.fetchone()[0]
            trainings_inserted += 1
            if tid is not None:
                training_id_map[tid] = new_tid

        # TrainingLog
        for _, row in training_log_df.iterrows():
            tl_tid = _int(row.get("TrainingID") or row.get("Training Id"))
            tl_vid = _int(row.get("VolunteerID") or row.get("Volunteer Id"))
            if tl_tid is None or tl_vid is None:
                training_log_skipped_unresolved += 1
                continue
            our_tid = training_id_map.get(tl_tid)
            our_vid = volunteer_id_map.get(tl_vid)
            if our_tid is None or our_vid is None:
                training_log_skipped_unresolved += 1
                continue
            cur.execute("""
                INSERT INTO training_log (training_id, volunteer_id, status, expiration_date)
                VALUES (%s, %s, %s, %s) ON CONFLICT (training_id, volunteer_id) DO UPDATE SET status = EXCLUDED.status, expiration_date = EXCLUDED.expiration_date
                """, (our_tid, our_vid, _str(row.get("Status")), _date(row.get("ExpirationDate") or row.get("Expiration Date"))))
            training_log_inserted += 1

        # Assignments: need site_id by site_code. Get site codes from site table.
        cur.execute("SELECT site_id, site_code FROM site")
        site_code_to_id = {r[1]: r[0] for r in cur.fetchall()}
        known_site_ids = set(site_code_to_id.values())
        role_name_to_id = {}
        cur.execute("SELECT role_id, name FROM lst_role")
        for r in cur.fetchall():
            role_name_to_id[r[1]] = r[0]

        for _, row in assignments_df.iterrows():
            v_id = _int(row.get("VolunteerID") or row.get("Volunteer Id"))
            raw_site = row.get("SiteID") or row.get("Site Id")
            site_code = _str(row.get("SiteCode") or row.get("Site Code"))
            # Skip blank padded rows from Excel used-range inflation (do not count as unresolved).
            if (
                v_id is None
                and not _str(raw_site)
                and not site_code
                and not _str(row.get("FullName") or row.get("Full Name"))
                and not _str(row.get("Role"))
                and _int(row.get("AssignmentID") or row.get("Assignment Id")) is None
            ):
                continue
            site_id = _int(raw_site)
            # Non-numeric SiteID values are site codes (e.g. AWL1)
            if site_id is None:
                maybe_code = _str(raw_site)
                if maybe_code:
                    site_code = site_code or maybe_code
            # Resolve site: numeric PK if known, else site_code lookup
            if site_id is not None and site_id not in known_site_ids:
                site_id = None
            if site_id is None and site_code:
                site_id = site_code_to_id.get(site_code)
            if site_id is None:
                assignments_skipped_unresolved_site += 1
                continue
            our_vid = volunteer_id_map.get(v_id) if v_id is not None else None
            if our_vid is None:
                assignments_skipped_unresolved_volunteer += 1
                continue
            role = _str(row.get("Role"))
            role_id = role_name_to_id.get(role) if role else None
            cur.execute("""
                INSERT INTO junc_assignments (volunteer_id, site_id, role_id, start_date, end_date)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT (volunteer_id, site_id) DO NOTHING
                """, (our_vid, site_id, role_id, _date(row.get("StartDate") or row.get("Start Date")), _date(row.get("EndDate") or row.get("End Date"))))
            if cur.rowcount:
                assignments_inserted += 1

    print(
        "Volunteers migration done. "
        f"Headers: Volunteers={volunteers_header}, Trainings={trainings_header}, "
        f"TrainingLog={training_log_header}, Assignments={assignments_header}. "
        f"Inserted volunteer={volunteers_inserted}, training={trainings_inserted}, "
        f"training_log={training_log_inserted}, junc_assignments={assignments_inserted}. "
        f"Skipped: volunteers_no_name={volunteers_skipped_no_name}, "
        f"trainings_no_date={trainings_skipped_no_date}, "
        f"training_log_unresolved={training_log_skipped_unresolved}, "
        f"assignments_unresolved_site={assignments_skipped_unresolved_site}, "
        f"assignments_unresolved_volunteer={assignments_skipped_unresolved_volunteer}."
    )


if __name__ == "__main__":
    run()
