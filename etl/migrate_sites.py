#!/usr/bin/env python3
"""
Migrate 2025 StreamWatch Locations (sheet SWSites_2024) into site and lookups.
Expects: STREAMWATCH_DATA_DIR or SITES_FILE pointing to '2025 StreamWatch Locations.xlsx'.
"""
import pandas as pd
from pathlib import Path
import sys

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.config import SITES_FILE
from etl.db import get_conn, ensure_lookup


SHEET = "SWSites_2024"

# Map Excel column names (flexible) to our schema
COLUMN_ALIASES = {
    "SiteCode": "site_code",
    "Site Code": "site_code",
    "WaterBody": "waterbody",
    "Water Body": "waterbody",
    "Subwatershed": "subwatershed",
    "Description": "description",
    "Drainage area": "drainage_area",
    "Drainage Area": "drainage_area",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Type of property": "property_type",
    "Property Type": "property_type",
    "Permission": "permission",
    "Walk time": "walk_time",
    "Walk distance": "walk_distance",
    "Walk gradient": "walk_gradient",
    "Water access": "water_access",
    "Environmental hazards": "environmental_hazards",
    "Parking details": "parking_details",
    "Walking directions": "walking_directions",
    "Additional comments": "additional_comments",
    "Groundtruthing priority": "groundtruthing_priority",
    "Groundtruthing status": "groundtruthing_status",
    "CAT Priority": "cat_priority",
    "BAT Priority": "bat_priority",
    "BACT Priority": "bact_priority",
    "CAT Status": "cat_status",
    "BAT Status": "bat_status",
    "BACT Status": "bact_status",
    "Last sample date": "last_sample_date",
    "Habitat type": "habitat_type",
    "Notes": "notes",
    "isActive": "is_active",
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to snake_case and align to known aliases."""
    out = df.copy()
    for raw, canonical in COLUMN_ALIASES.items():
        if raw in out.columns and canonical not in out.columns:
            out[canonical] = out[raw]
    # Ensure we have at least site_code
    if "site_code" not in out.columns:
        for c in ["SiteCode", "Site Code", "SiteCode "] + list(out.columns):
            if c in out.columns and "site" in str(c).lower() and "code" in str(c).lower():
                out["site_code"] = out[c]
                break
    return out


def coerce_priority(conn, label) -> int:
    if pd.isna(label) or label is None or str(label).strip() == "":
        return None
    return ensure_lookup(conn, "lst_priority", "priority_id", "label", str(label).strip())


def coerce_groundtruthing_status(conn, label) -> int:
    if pd.isna(label) or label is None or str(label).strip() == "":
        return None
    return ensure_lookup(conn, "lst_groundtruthing_status", "groundtruthing_status_id", "label", str(label).strip())


def coerce_property_type(s) -> str:
    if pd.isna(s) or s is None:
        return None
    v = str(s).strip()
    if not v:
        return None
    # Normalize to enum-like
    for choice in ("Public", "Private", "TWI", "Other"):
        if choice.lower() in v.lower():
            return choice
    return "Other"


def coerce_habitat_type(s) -> str:
    if pd.isna(s) or s is None:
        return None
    v = str(s).strip()
    for choice in ("High Gradient", "Low Gradient", "Canal", "Lake"):
        if choice.lower() in v.lower():
            return choice
    return None


def run():
    if not SITES_FILE.exists():
        print(f"Sites file not found: {SITES_FILE}. Set STREAMWATCH_DATA_DIR or SITES_FILE.")
        sys.exit(1)
    df = pd.read_excel(SITES_FILE, sheet_name=SHEET)
    df = normalize_columns(df)
    if "site_code" not in df.columns:
        print("Could not find site code column. Columns:", list(df.columns))
        sys.exit(1)

    with get_conn() as conn:
        cur = conn.cursor()
        for _, row in df.iterrows():
            site_code = row.get("site_code")
            if pd.isna(site_code) or str(site_code).strip() == "":
                continue
            site_code = str(site_code).strip()

            waterbody_id = ensure_lookup(
                conn, "waterbody", "waterbody_id", "name", row.get("waterbody")
            ) if pd.notna(row.get("waterbody")) else None

            subwatershed_id = ensure_lookup(
                conn, "subwatershed", "subwatershed_id", "name", row.get("subwatershed")
            ) if pd.notna(row.get("subwatershed")) else None

            cat_priority_id = coerce_priority(conn, row.get("cat_priority"))
            bat_priority_id = coerce_priority(conn, row.get("bat_priority"))
            bact_priority_id = coerce_priority(conn, row.get("bact_priority"))
            groundtruthing_status_id = coerce_groundtruthing_status(conn, row.get("groundtruthing_status"))

            lat = row.get("latitude")
            lon = row.get("longitude")
            if pd.notna(lat):
                try:
                    lat = float(lat)
                except (TypeError, ValueError):
                    lat = None
            if pd.notna(lon):
                try:
                    lon = float(lon)
                except (TypeError, ValueError):
                    lon = None

            drainage = row.get("drainage_area")
            if pd.notna(drainage):
                try:
                    drainage = float(drainage)
                except (TypeError, ValueError):
                    drainage = None
            else:
                drainage = None

            is_active = True
            if "is_active" in row.index and pd.notna(row.get("is_active")):
                v = str(row.get("is_active")).lower()
                is_active = v in ("1", "true", "yes", "active")

            prop_type = coerce_property_type(row.get("property_type"))
            habitat_type = coerce_habitat_type(row.get("habitat_type"))

            cur.execute("""
                INSERT INTO site (
                    site_code, is_active, waterbody_id, description,
                    latitude, longitude, site_type, groundtruthing_priority, groundtruthing_status_id,
                    property_type, permission, walk_time, walk_distance, walk_gradient,
                    water_access, environmental_hazards, parking_details, walking_directions, additional_comments,
                    habitat_type, drainage_area_sq_km, notes, cat_priority_id, bat_priority_id, bact_priority_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, NULL, %s, %s,                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (site_code) DO UPDATE SET
                    is_active = EXCLUDED.is_active,
                    waterbody_id = COALESCE(EXCLUDED.waterbody_id, site.waterbody_id),
                    description = EXCLUDED.description,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    groundtruthing_priority = EXCLUDED.groundtruthing_priority,
                    groundtruthing_status_id = EXCLUDED.groundtruthing_status_id,
                    property_type = EXCLUDED.property_type,
                    permission = EXCLUDED.permission,
                    walk_time = EXCLUDED.walk_time,
                    walk_distance = EXCLUDED.walk_distance,
                    walk_gradient = EXCLUDED.walk_gradient,
                    water_access = EXCLUDED.water_access,
                    environmental_hazards = EXCLUDED.environmental_hazards,
                    parking_details = EXCLUDED.parking_details,
                    walking_directions = EXCLUDED.walking_directions,
                    additional_comments = EXCLUDED.additional_comments,
                    habitat_type = COALESCE(EXCLUDED.habitat_type, site.habitat_type),
                    drainage_area_sq_km = EXCLUDED.drainage_area_sq_km,
                    notes = EXCLUDED.notes,
                    cat_priority_id = EXCLUDED.cat_priority_id,
                    bat_priority_id = EXCLUDED.bat_priority_id,
                    bact_priority_id = EXCLUDED.bact_priority_id,
                    updated_at = NOW()
                """, (
                    site_code, is_active, waterbody_id, _str(row.get("description")),
                    lat, lon, _str(row.get("groundtruthing_priority")), groundtruthing_status_id,
                    prop_type, _str(row.get("permission")), _str(row.get("walk_time")), _str(row.get("walk_distance")),
                    _str(row.get("walk_gradient")), _str(row.get("water_access")), _str(row.get("environmental_hazards")),
                    _str(row.get("parking_details")), _str(row.get("walking_directions")), _str(row.get("additional_comments")),
                    habitat_type, drainage, _str(row.get("notes")), cat_priority_id, bat_priority_id, bact_priority_id,
                ))
            cur.execute("SELECT site_id FROM site WHERE site_code = %s", (site_code,))
            site_id = cur.fetchone()[0]
            if subwatershed_id and site_id:
                cur.execute(
                    "INSERT INTO junc_site_subwatershed (site_id, subwatershed_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (site_id, subwatershed_id),
                )
        print(f"Sites migration done: {len(df)} rows processed.")


def _str(v):
    if v is None or pd.isna(v):
        return None
    s = str(v).strip()
    return s if s else None


if __name__ == "__main__":
    run()
