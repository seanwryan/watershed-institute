"""
Shared BACT Survey123 / IDEXX parsing and READ-ONLY reconciliation.

Used by:
  - etl/migrate_bact_2025.py (write path; behavior unchanged)
  - dashboard BACT import preview (no database writes)

Gallery / Turbidity / Phycocyanin are out of scope.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from etl.chem_recon import CHEM_HEADER_ALIASES, CHEM_VALUE_FIELDS, round_chem
from etl.visit_helpers import _date, _float, _int, _str, get_site_id_map

FIELD_LABELS = {
    "air_temp_c": "Air temperature",
    "water_temp_c": "Water temperature",
    "nitrate_ug_l": "Nitrate",
    "phosphate_mg_l": "Phosphate",
    "ph": "pH",
    "turbidity_ntu": "Turbidity",
    "dissolved_oxygen_ppm": "Dissolved oxygen",
    "dissolved_oxygen_pct": "Dissolved oxygen saturation",
    "conductivity_us_cm": "Conductivity",
    "chloride_mg_l": "Chloride",
}

SURVEY123_STATUS = {
    "ready_to_enrich": "Ready to enrich",
    "nothing_to_update": "Nothing to update",
    "needs_review": "Needs review",
    "invalid": "Invalid",
}

IDEXX_STATUS = {
    "ready_to_add": "Ready to add",
    "already_recorded": "Already recorded",
    "needs_visit_match": "Needs visit match",
    "censored": "Censored result",
    "invalid": "Invalid",
}

_CENSORED_RE = re.compile(r"^\s*[<>]=?\s*")


def col(row, *names):
    for n in names:
        if n in row.index and pd.notna(row.get(n)):
            return row.get(n)
    return None


def survey123_values(row) -> dict:
    """Map Survey123 chem fields using shared aliases (same as migrate_bact_2025)."""
    values = {}
    for field in (
        "water_temp_c",
        "nitrate_ug_l",
        "phosphate_mg_l",
        "turbidity_ntu",
        "chloride_mg_l",
    ):
        values[field] = round_chem(_float(col(row, *CHEM_HEADER_ALIASES[field])))
    return values


def find_visits_for_site_date(cur, site_id, sample_date):
    cur.execute(
        """
        SELECT visit_id, sample_code
        FROM visit
        WHERE site_id = %s AND sample_date = %s
        ORDER BY visit_id
        """,
        (site_id, sample_date),
    )
    return cur.fetchall()


def chemical_rows_for_visit(cur, visit_id):
    cur.execute(
        f"""
        SELECT chemical_id, method_id,
               {", ".join(CHEM_VALUE_FIELDS)}
        FROM chemical
        WHERE visit_id = %s
        ORDER BY chemical_id
        """,
        (visit_id,),
    )
    rows = []
    for r in cur.fetchall():
        chem = {"chemical_id": r[0], "method_id": r[1]}
        for i, f in enumerate(CHEM_VALUE_FIELDS):
            chem[f] = r[2 + i]
        rows.append(chem)
    return rows


def pick_enrichment_target(chem_rows, method_id_bact, incoming: dict):
    """
    Choose a chemical row to fill NULLs on.
    Same rules as migrate_bact_2025._pick_enrichment_target.
    """
    if not chem_rows:
        return None, "no_chemical_row"

    def fillable_count(row):
        return sum(1 for f, v in incoming.items() if v is not None and row.get(f) is None)

    bact_rows = [r for r in chem_rows if method_id_bact and r["method_id"] == method_id_bact]
    candidates = bact_rows or chem_rows
    candidates = sorted(candidates, key=fillable_count, reverse=True)
    if fillable_count(candidates[0]) == 0:
        return candidates[0], None
    return candidates[0], None


def analyze_fill(row: dict, incoming: dict) -> Tuple[List[dict], List[dict]]:
    """
    Dry-run of migrate_bact_2025 fill-NULL logic.
    Returns (would_fill, conflicts) without writing.
    would_fill: [{field, label, value}, ...]
    conflicts: [{field, label, existing, survey123}, ...]
    """
    would_fill = []
    conflicts = []
    for f, v in incoming.items():
        if v is None:
            continue
        existing = row.get(f)
        label = FIELD_LABELS.get(f, f)
        if existing is None:
            would_fill.append({"field": f, "label": label, "value": v})
        else:
            try:
                existing_r = round_chem(float(existing), 4)
                incoming_r = round_chem(float(v), 4)
            except (TypeError, ValueError):
                existing_r, incoming_r = existing, v
            if existing_r != incoming_r and (
                existing_r is None
                or incoming_r is None
                or abs(float(existing_r) - float(incoming_r)) > 1e-4
            ):
                conflicts.append(
                    {
                        "field": f,
                        "label": label,
                        "existing": existing_r,
                        "survey123": incoming_r,
                    }
                )
    return would_fill, conflicts


def is_censored_result(raw) -> bool:
    """True when a source value looks like an inequality / censored MPN (e.g. >2419.6)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    s = str(raw).strip()
    if not s:
        return False
    if _CENSORED_RE.match(s):
        return True
    # Excel may store as string with spaces: "> 2419.6"
    return bool(re.search(r"[<>]", s)) and _int(raw) is None


def _parse_site_date_from_sample_code(sample_code: Optional[str]):
    if not sample_code:
        return None, None
    m = re.match(r"^([A-Za-z0-9]+)_(\d{4}-\d{2}-\d{2})$", sample_code.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _select_visit_for_preview(visits, sample_code):
    """
    Visit selection for preview.

    Matches migrate_bact_2025 when a sample_code matches or only one visit exists.
    When multiple visits exist and sample_code does not match any, return None
    (needs review) instead of silently picking the first visit.
    """
    if not visits:
        return None, None, "no_visit"
    if sample_code:
        matches = [(vid, sc) for vid, sc in visits if sc == sample_code]
        if len(matches) == 1:
            return matches[0][0], matches[0][1], None
        if len(matches) > 1:
            return None, None, "ambiguous_sample_code"
    if len(visits) == 1:
        return visits[0][0], visits[0][1], None
    if sample_code:
        # ETL would fall through to first visit; preview flags for review.
        return None, None, "multiple_visits_no_code_match"
    return None, None, "multiple_visits_no_sample_code"


def _sheet_name(xl, *candidates):
    names = list(xl.sheet_names)
    lower = {n.lower(): n for n in names}
    for c in candidates:
        if c in names:
            return c
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def validate_bact_workbook(path) -> Tuple[Optional[pd.ExcelFile], Optional[str]]:
    """Open workbook; return (ExcelFile, None) or (None, friendly_error)."""
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return None, "That file could not be opened as an Excel workbook (.xlsx)."
    s123 = _sheet_name(xl, "SURVEY123", "Survey123")
    idexx = _sheet_name(xl, "IDEXX", "Idexx")
    if not s123 and not idexx:
        return (
            None,
            "This workbook needs a SURVEY123 and/or IDEXX sheet. "
            "Gallery, Turbidity, and Phycocyanin sheets are not reviewed here.",
        )
    return xl, None


def preview_bact_workbook(path, conn) -> Dict[str, Any]:
    """
    READ-ONLY reconciliation of SURVEY123 and IDEXX against the connected DB.

    Does not INSERT/UPDATE/DELETE. Does not fill visit.sample_code.
    """
    xl, err = validate_bact_workbook(path)
    if err:
        raise ValueError(err)

    cur = conn.cursor()
    site_map = get_site_id_map(conn)
    method_id_bact = None
    cur.execute("SELECT method_id FROM lst_method WHERE name = 'BACT' LIMIT 1")
    r = cur.fetchone()
    if r:
        method_id_bact = r[0]

    survey_rows: List[dict] = []
    idexx_rows: List[dict] = []

    s123_name = _sheet_name(xl, "SURVEY123", "Survey123")
    if s123_name:
        df = pd.read_excel(path, sheet_name=s123_name)
        df.columns = [str(c).strip() for c in df.columns]
        date_col = "Date" if "Date" in df.columns else None
        if date_col is None:
            date_col = next(
                (c for c in df.columns if c.lower() in ("sample date", "date collected")),
                None,
            )
        site_col = next(
            (
                c
                for c in df.columns
                if c.lower() in ("monitoring site id", "monitoring site id ")
                or ("site" in c.lower() and "id" in c.lower())
            ),
            None,
        )

        for idx, row in df.iterrows():
            source_row = int(idx) + 2  # header is row 1 in Excel
            site_code = _str(row.get(site_col) if site_col else None)
            sample_code = _str(row.get("Sample Code") or row.get("Sample code"))
            sample_date = _date(row.get(date_col) if date_col else None)
            incoming = survey123_values(row)

            base = {
                "source": "Survey123",
                "source_row": source_row,
                "site_code": site_code,
                "sample_date": str(sample_date) if sample_date else None,
                "sample_code": sample_code,
                "visit_id": None,
                "chemical_id": None,
                "proposed_fields": [],
                "proposed_action": "",
                "status": "invalid",
                "status_label": SURVEY123_STATUS["invalid"],
                "detail": "",
                "link_visit": False,
                "link_site": False,
            }

            if not site_code:
                base["detail"] = "Monitoring site ID is missing or blank."
                survey_rows.append(base)
                continue

            site_id = site_map.get(site_code)
            if not site_id:
                base["status"] = "needs_review"
                base["status_label"] = SURVEY123_STATUS["needs_review"]
                base["detail"] = (
                    f"Site “{site_code}” is not in StreamWatch. "
                    "No visit match can be made until the site exists."
                )
                survey_rows.append(base)
                continue

            base["link_site"] = True

            if not sample_date:
                base["detail"] = (
                    "Sample date is missing or could not be read "
                    "(CreationDate is not used)."
                )
                survey_rows.append(base)
                continue

            if all(v is None for v in incoming.values()):
                base["detail"] = (
                    "No supported chemistry values were found in this Survey123 row "
                    "(water temperature, nitrate, phosphate, turbidity, chloride)."
                )
                survey_rows.append(base)
                continue

            visits = find_visits_for_site_date(cur, site_id, sample_date)
            visit_id, visit_sc, vreason = _select_visit_for_preview(visits, sample_code)
            if vreason == "no_visit":
                base["status"] = "needs_review"
                base["status_label"] = SURVEY123_STATUS["needs_review"]
                base["detail"] = (
                    f"No visit was found for site {site_code} on {sample_date}."
                )
                survey_rows.append(base)
                continue
            if vreason:
                base["status"] = "needs_review"
                base["status_label"] = SURVEY123_STATUS["needs_review"]
                if vreason == "multiple_visits_no_code_match":
                    base["detail"] = (
                        f"Multiple visits exist for {site_code} on {sample_date}, "
                        f"and none have sample code “{sample_code}”. "
                        "No match was selected."
                    )
                elif vreason == "multiple_visits_no_sample_code":
                    base["detail"] = (
                        f"Multiple visits exist for {site_code} on {sample_date}, "
                        "and this Survey123 row has no sample code. "
                        "No match was selected."
                    )
                else:
                    base["detail"] = (
                        f"Multiple visits share sample code “{sample_code}”. "
                        "No match was selected."
                    )
                survey_rows.append(base)
                continue

            base["visit_id"] = visit_id
            base["link_visit"] = True

            chem_rows = chemical_rows_for_visit(cur, visit_id)
            target, reason = pick_enrichment_target(chem_rows, method_id_bact, incoming)
            if target is None:
                base["status"] = "needs_review"
                base["status_label"] = SURVEY123_STATUS["needs_review"]
                base["detail"] = (
                    f"Visit {visit_id} has no chemistry package to enrich."
                    if reason == "no_chemical_row"
                    else "No chemistry target could be selected for enrichment."
                )
                survey_rows.append(base)
                continue

            base["chemical_id"] = target["chemical_id"]
            would_fill, conflicts = analyze_fill(target, incoming)
            base["proposed_fields"] = would_fill

            would_fill_sample_code = bool(sample_code and not visit_sc)
            # Preview never writes sample_code; surface as informational when ETL would fill it.
            notes = []
            if would_fill_sample_code:
                notes.append(
                    f"Migration would also set blank visit sample code to “{sample_code}” "
                    "(preview does not change it)."
                )

            if would_fill:
                fields_txt = ", ".join(
                    f"{f['label']}={f['value']}" for f in would_fill
                )
                base["status"] = "ready_to_enrich"
                base["status_label"] = SURVEY123_STATUS["ready_to_enrich"]
                base["proposed_action"] = f"Fill NULL field(s): {fields_txt}"
                detail = (
                    f"Matching chemistry package {target['chemical_id']} has blank "
                    f"field(s) that Survey123 could fill: {fields_txt}."
                )
                if conflicts:
                    detail += (
                        " Some other fields already differ and would not be overwritten."
                    )
                if notes:
                    detail += " " + " ".join(notes)
                base["detail"] = detail
            elif conflicts:
                clash = "; ".join(
                    f"{c['label']} (StreamWatch {c['existing']} vs Survey123 {c['survey123']})"
                    for c in conflicts[:5]
                )
                base["status"] = "needs_review"
                base["status_label"] = SURVEY123_STATUS["needs_review"]
                base["proposed_action"] = "No NULL fields to fill; values conflict"
                base["detail"] = (
                    "Matching chemistry data is already populated for fillable fields, "
                    f"but Survey123 differs on: {clash}. "
                    "Current migration never overwrites non-null values."
                )
            else:
                base["status"] = "nothing_to_update"
                base["status_label"] = SURVEY123_STATUS["nothing_to_update"]
                base["proposed_action"] = "No change"
                base["detail"] = (
                    "Matching chemistry data is already populated; "
                    "no update would be made."
                )
                if notes:
                    base["detail"] += " " + " ".join(notes)

            survey_rows.append(base)

    idexx_name = _sheet_name(xl, "IDEXX", "Idexx")
    if idexx_name:
        df = pd.read_excel(path, sheet_name=idexx_name)
        df.columns = [str(c).strip() for c in df.columns]
        code_col = next(
            (
                c
                for c in df.columns
                if ("sample" in c.lower() and "code" in c.lower()) or c == "SampleCode"
            ),
            None,
        )
        ecoli_col = next(
            (
                c
                for c in df.columns
                if "e. coli" in c.lower() or "ecoli" in c.lower() or c == "E. coli (MPN)"
            ),
            None,
        )
        tc_col = next(
            (
                c
                for c in df.columns
                if "ttl coli" in c.lower()
                or "total coli" in c.lower()
                or c.lower().startswith("ttl")
            ),
            None,
        )

        cur.execute(
            """
            SELECT visit_id, e_coli_mpn_100ml
            FROM bacteria
            WHERE e_coli_mpn_100ml IS NOT NULL
            """
        )
        existing = {(r[0], r[1]) for r in cur.fetchall()}

        # Count visits per sample_code for ambiguity
        cur.execute(
            """
            SELECT sample_code, COUNT(*)
            FROM visit
            WHERE sample_code IS NOT NULL
            GROUP BY sample_code
            """
        )
        code_counts = {r[0]: r[1] for r in cur.fetchall()}

        for idx, row in df.iterrows():
            source_row = int(idx) + 2
            sample_code = _str(row.get(code_col) if code_col else None) or _str(
                row.get("Sample code")
            )
            raw_ecoli = row.get(ecoli_col) if ecoli_col else row.get("E. coli (MPN)")
            raw_tc = row.get(tc_col) if tc_col else None
            e_coli = _int(raw_ecoli)
            site_guess, date_guess = _parse_site_date_from_sample_code(sample_code)

            base = {
                "source": "IDEXX",
                "source_row": source_row,
                "site_code": site_guess,
                "sample_date": date_guess,
                "sample_code": sample_code,
                "visit_id": None,
                "e_coli_raw": None
                if raw_ecoli is None or (isinstance(raw_ecoli, float) and pd.isna(raw_ecoli))
                else str(raw_ecoli).strip(),
                "e_coli_mpn": e_coli,
                "total_coliform_raw": None
                if raw_tc is None or (isinstance(raw_tc, float) and pd.isna(raw_tc))
                else str(raw_tc).strip(),
                "proposed_action": "",
                "status": "invalid",
                "status_label": IDEXX_STATUS["invalid"],
                "detail": "",
                "link_visit": False,
                "link_site": bool(site_guess and site_guess in site_map),
            }

            # Blank header / empty rows: skip silently like ETL for pure blanks
            if not sample_code:
                if pd.notna(raw_ecoli) or pd.notna(row.get("Sample ID")):
                    base["detail"] = "Sample code is missing."
                    idexx_rows.append(base)
                continue

            if is_censored_result(raw_ecoli):
                base["status"] = "censored"
                base["status_label"] = IDEXX_STATUS["censored"]
                base["proposed_action"] = "Do not import (policy pending)"
                base["detail"] = (
                    f"E. coli value “{base['e_coli_raw']}” is censored and StreamWatch "
                    "does not yet have a confirmed storage policy for censored results."
                )
                idexx_rows.append(base)
                continue

            if e_coli is None:
                base["detail"] = (
                    "E. coli value is missing or could not be parsed as a number."
                    if base["e_coli_raw"]
                    else "E. coli value is blank."
                )
                idexx_rows.append(base)
                continue

            cur.execute(
                "SELECT visit_id FROM visit WHERE sample_code = %s ORDER BY visit_id",
                (sample_code,),
            )
            visits = cur.fetchall()
            if not visits:
                base["status"] = "needs_visit_match"
                base["status_label"] = IDEXX_STATUS["needs_visit_match"]
                base["proposed_action"] = "Needs visit match"
                base["detail"] = (
                    f"No visit was found with sample code “{sample_code}”."
                )
                idexx_rows.append(base)
                continue

            if len(visits) > 1 or code_counts.get(sample_code, 0) > 1:
                base["status"] = "needs_visit_match"
                base["status_label"] = IDEXX_STATUS["needs_visit_match"]
                base["proposed_action"] = "Needs visit match"
                base["detail"] = (
                    f"Multiple visits were found with sample code “{sample_code}”; "
                    "no match was selected."
                )
                idexx_rows.append(base)
                continue

            visit_id = visits[0][0]
            base["visit_id"] = visit_id
            base["link_visit"] = True
            fp = (visit_id, e_coli)
            if fp in existing:
                base["status"] = "already_recorded"
                base["status_label"] = IDEXX_STATUS["already_recorded"]
                base["proposed_action"] = "No change"
                base["detail"] = (
                    f"Visit {visit_id} already has an E. coli result of {e_coli} MPN/100mL."
                )
            else:
                base["status"] = "ready_to_add"
                base["status_label"] = IDEXX_STATUS["ready_to_add"]
                base["proposed_action"] = f"Add E. coli {e_coli} MPN/100mL"
                base["detail"] = (
                    f"Visit {visit_id} matched on sample code “{sample_code}”. "
                    f"E. coli {e_coli} MPN/100mL is not yet recorded for that visit."
                )
            idexx_rows.append(base)

    def _count(rows, key):
        return sum(1 for r in rows if r["status"] == key)

    return {
        "survey123": {
            "rows": survey_rows,
            "summary": {
                "rows_reviewed": len(survey_rows),
                "ready_to_enrich": _count(survey_rows, "ready_to_enrich"),
                "nothing_to_update": _count(survey_rows, "nothing_to_update"),
                "needs_review": _count(survey_rows, "needs_review"),
                "invalid": _count(survey_rows, "invalid"),
            },
        },
        "idexx": {
            "rows": idexx_rows,
            "summary": {
                "rows_reviewed": len(idexx_rows),
                "ready_to_add": _count(idexx_rows, "ready_to_add"),
                "already_recorded": _count(idexx_rows, "already_recorded"),
                "needs_visit_match": _count(idexx_rows, "needs_visit_match"),
                "censored": _count(idexx_rows, "censored"),
                "invalid": _count(idexx_rows, "invalid"),
            },
        },
        "sheets_present": {
            "survey123": bool(s123_name),
            "idexx": bool(idexx_name),
        },
    }
