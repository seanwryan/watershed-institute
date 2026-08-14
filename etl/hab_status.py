"""
HAB status helpers from BACT and HAB 2025 Data.xlsx METADATA (J. Smith 2025-06-09).

PHYCOCYANIN HAB Status:
  IFS(ReportedToDEP="Yes", "Reported to DEP",
      median_phycocyanin >= 20, "Elevated Phycocyanin",
      TRUE, "")

SURVEY123 HAB Status:
  LET(lookupVal, XLOOKUP(sample_code, PHYCOCYANIN HAB Status),
      IFS(lookupVal <> "", lookupVal,
          OR(AlgalBloomPresence="Abundant algae",
             SEARCH("Suspected_HAB", AlgaeType)),
          "Flagged",
          TRUE, ""))

Read-only. Does not write to the database. Phycocyanin is not modeled in PostgreSQL.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from etl.visit_helpers import _date, _float, _str


def phycocyanin_hab_status(
    reported_to_dep: Any,
    median_phycocyanin: Any,
) -> str:
    """Workbook PHYCOCYANIN column R / METADATA IFS."""
    dep = _str(reported_to_dep)
    if dep and dep.strip().lower() == "yes":
        return "Reported to DEP"
    val = _float(median_phycocyanin)
    if val is not None and val >= 20:
        return "Elevated Phycocyanin"
    return ""


def survey123_hab_status(
    phyco_hab_status: Any,
    algal_bloom_presence: Any,
    algae_type: Any,
) -> str:
    """
    Workbook SURVEY123 column AK formula (METADATA 2025-06-09).

    Uses Algal Bloom Presence (Z) and Algae Type (AA) exactly as in the formula.
    Manual DEP dashboard strings (Watch/Advisory) are outside this calculated rule.
    """
    lookup = _str(phyco_hab_status) or ""
    if lookup.strip():
        return lookup.strip()
    algae = _str(algal_bloom_presence) or ""
    algae_type_s = _str(algae_type) or ""
    if algae == "Abundant algae":
        return "Flagged"
    if "Suspected_HAB" in algae_type_s:
        return "Flagged"
    return ""


def _sheet(xl: pd.ExcelFile, *names: str) -> Optional[str]:
    lower = {n.lower(): n for n in xl.sheet_names}
    for n in names:
        if n in xl.sheet_names:
            return n
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def preview_hab_workbook(path) -> Dict[str, Any]:
    """
    Read-only HAB status preview from BACT and HAB workbook sheets.
    Returns phyco rows and survey123 rows with derived vs workbook-stored status.
    """
    path = Path(path)
    xl = pd.ExcelFile(path)
    phyco_name = _sheet(xl, "PHYCOCYANIN", "Phycocyanin")
    s123_name = _sheet(xl, "SURVEY123", "Survey123")

    phyco_rows: List[dict] = []
    phyco_by_sample: Dict[str, str] = {}

    if phyco_name:
        df = pd.read_excel(path, sheet_name=phyco_name, header=0)
        # Row 0 may be sub-headers (Reading 1..); detect
        if df.shape[0] and str(df.iloc[0].get("Fluorometer Readings") or "").startswith(
            "Reading"
        ):
            # columns already named; median often under Unnamed for col H
            pass
        # Rebuild with header row 0 as names; median is typically column index 7 (H)
        raw = pd.read_excel(path, sheet_name=phyco_name, header=None)
        # Find header row with Sample code
        header_idx = 0
        for i in range(min(5, len(raw))):
            vals = [str(v).strip().lower() if pd.notna(v) else "" for v in raw.iloc[i]]
            if any(v == "sample code" for v in vals):
                header_idx = i
                break
        headers = [str(v).strip() if pd.notna(v) else f"col{j}" for j, v in enumerate(raw.iloc[header_idx])]
        # Subheader row for fluorometer
        data_start = header_idx + 1
        if data_start < len(raw):
            sub = raw.iloc[data_start]
            if any(str(v).startswith("Reading") for v in sub if pd.notna(v)) or any(
                str(v) == "Median Reading" for v in sub if pd.notna(v)
            ):
                data_start += 1
                for j, v in enumerate(sub):
                    if pd.notna(v) and str(v).strip():
                        headers[j] = str(v).strip()

        # Map columns by known names / positions
        # A=sample code, B=site, H=median (index 7), Q=Reported to DEP (16), R=HAB Status (17)
        for i in range(data_start, len(raw)):
            row = raw.iloc[i]
            sample_code = _str(row.iloc[0]) if len(row) > 0 else None
            if not sample_code:
                continue
            site_id = _str(row.iloc[1]) if len(row) > 1 else None
            date_flagged = _date(row.iloc[2]) if len(row) > 2 else None
            median = _float(row.iloc[7]) if len(row) > 7 else None
            reported = _str(row.iloc[16]) if len(row) > 16 else None
            stored_status = _str(row.iloc[17]) if len(row) > 17 else None
            derived = phycocyanin_hab_status(reported, median)
            rec = {
                "source": "PHYCOCYANIN",
                "sample_code": sample_code,
                "site_code": site_id,
                "sample_date": date_flagged.isoformat() if date_flagged else None,
                "phycocyanin_median": median,
                "reported_to_dep": reported,
                "workbook_hab_status": stored_status or "",
                "derived_hab_status": derived,
                "matches_workbook": (stored_status or "") == derived
                or (
                    # cached formula may equal derived; allow blank==blank
                    (not stored_status and not derived)
                ),
            }
            phyco_rows.append(rec)
            if derived:
                phyco_by_sample[sample_code] = derived
            elif stored_status:
                # Prefer derived; if blank derived but stored manual, still index for S123 lookup
                # Lookup uses column R which may be formula result or manual — use derived for rule fidelity
                pass
            # XLOOKUP uses PHYCOCYANIN!R — stored/formula value. For preview of Survey123 rule,
            # use derived when we can compute it; else stored.
            phyco_by_sample[sample_code] = derived if derived else (stored_status or "")

    survey_rows: List[dict] = []
    if s123_name:
        df = pd.read_excel(path, sheet_name=s123_name)
        df.columns = [str(c).strip() for c in df.columns]
        for idx, row in df.iterrows():
            sample_code = _str(row.get("Sample Code") or row.get("Sample code"))
            if not sample_code and pd.isna(row.get("Date")):
                continue
            site = _str(row.get("Monitoring Site ID"))
            sample_date = _date(row.get("Date"))
            algae = _str(row.get("Algal Bloom Presence"))
            algae_type = _str(row.get("Algae Type"))
            notes = _str(row.get("Additional Comments (optional)"))
            stored = _str(row.get("HAB Status")) or ""
            phyco_status = phyco_by_sample.get(sample_code or "", "")
            derived = survey123_hab_status(phyco_status, algae, algae_type)
            survey_rows.append(
                {
                    "source": "SURVEY123",
                    "sample_code": sample_code,
                    "site_code": site,
                    "sample_date": sample_date.isoformat() if sample_date else None,
                    "phycocyanin_status": phyco_status,
                    "algal_bloom_presence": algae,
                    "algae_type": algae_type,
                    "notes": notes,
                    "workbook_hab_status": stored,
                    "derived_hab_status": derived,
                    "matches_calculated_rule": stored == derived,
                    "manual_or_dep_override": bool(
                        stored
                        and stored != derived
                        and stored
                        not in ("Reported to DEP", "Elevated Phycocyanin", "Flagged", "")
                    ),
                }
            )

    def _count_status(rows, key):
        from collections import Counter

        return dict(Counter((r.get(key) or "(blank)") for r in rows))

    return {
        "phyco": {
            "rows": phyco_rows,
            "summary": {
                "rows_reviewed": len(phyco_rows),
                "derived_status_counts": _count_status(phyco_rows, "derived_hab_status"),
            },
        },
        "survey123": {
            "rows": survey_rows,
            "summary": {
                "rows_reviewed": len(survey_rows),
                "derived_status_counts": _count_status(survey_rows, "derived_hab_status"),
                "workbook_status_counts": _count_status(survey_rows, "workbook_hab_status"),
                "manual_or_dep_overrides": sum(
                    1 for r in survey_rows if r.get("manual_or_dep_override")
                ),
            },
        },
        "sheets_present": {
            "phycocyanin": bool(phyco_name),
            "survey123": bool(s123_name),
        },
        "source_note": (
            "HAB Status reproduces METADATA formulas (2025-06-09). "
            "Manual DEP Watch/Advisory entries on SURVEY123 are outside the calculated rule."
        ),
    }
