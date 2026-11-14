"""
Data browser: a friendly, read-only view of every StreamWatch table and how the
tables connect.

  /data                 overview: relationship map + tables grouped by topic
  /data/<table>         the table's actual rows: search, sort, filter by site,
                        page through, follow links to related records
  /data/<table>.csv     the same rows (current filters) as CSV

Safety
  - Every connection is set read-only; nothing here can change data.
  - Only tables in CATALOG are reachable, and only real column names (read from
    information_schema) ever appear in SQL; values are always bound parameters.
  - Volunteer contact details (email, phone, address) are never shown here.
  - Binary and JSON columns are left out.
"""
from __future__ import annotations

import csv
import io
import math
import re
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal

from flask import Response, abort, render_template, request, url_for

PAGE_SIZE = 50
ROW = "_row"  # alias for the browsed table; distinct from aliases inside LINK_LABEL lookups
CSV_LIMIT = 50000
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

# --------------------------------------------------------------------------
# Catalog: what Jian sees. Order within a group is display order.
# --------------------------------------------------------------------------
GROUPS = [
    ("places", "Places", "Where StreamWatch samples, and the areas those places belong to."),
    ("sampling", "Sampling visits", "Each time a team sampled a site."),
    ("results", "Results", "What was measured on each visit."),
    ("biology", "Bugs (macroinvertebrates)", "Lab and volunteer bug counts, the taxa list, and the scores they produce."),
    ("people", "Volunteers & training", "Who samples where, and their training."),
    ("equipment", "Equipment", "Meters, sensors and their test sessions."),
    ("quality", "Data quality", "Review status codes and automated flags."),
    ("lookups", "Reference lists", "Short lists the other tables point to."),
]

CATALOG = {
    # Places
    "site": dict(group="places", label="Sites", row="One monitoring location.",
                 about="Site code, waterbody, location, habitat type, drainage area and access notes.",
                 sort="site_code", app="/site/{site_code}",
                 related=[("visit", "site_id", "Visits"), ("junc_assignments", "site_id", "Volunteer assignments"),
                          ("junc_site_municipality", "site_id", "Towns"), ("junc_site_subwatershed", "site_id", "Subwatersheds")]),
    "waterbody": dict(group="places", label="Waterbodies", row="One stream, river or lake.", sort="name",
                      related=[("site", "waterbody_id", "Sites")]),
    "municipality": dict(group="places", label="Towns", row="One municipality (also used for volunteer addresses).",
                         sort="name", related=[("junc_site_municipality", "municipality_id", "Sites")]),
    "subwatershed": dict(group="places", label="Subwatersheds", row="One subwatershed.", sort="name",
                         related=[("junc_site_subwatershed", "subwatershed_id", "Sites")]),
    "junc_site_municipality": dict(group="places", label="Site ↔ town links", row="One site in one town.",
                                   about="A site can sit in more than one town."),
    "junc_site_subwatershed": dict(group="places", label="Site ↔ subwatershed links", row="One site in one subwatershed."),
    "tbl_huc14": dict(group="places", label="HUC-14 areas", row="One USGS hydrologic unit (not filled in yet)."),
    "tbl_huc13": dict(group="places", label="HUC-13 areas", row="One USGS hydrologic unit (not filled in yet)."),
    # Sampling
    "visit": dict(group="sampling", label="Visits", row="One team's sampling at one site on one day (CAT, BACT, BAT or Salt Watch).",
                  about="Results hang off visits. Notes are Watershed's notes from All StreamWatch Data.",
                  sort="-sample_date", app="/visits/{visit_id}",
                  related=[("chemical", "visit_id", "Chemistry"), ("bacteria", "visit_id", "E. coli"),
                           ("macro_analysis", "visit_id", "Bug scores"), ("habitat_assessment", "visit_id", "Habitat"),
                           ("bug_count", "visit_id", "Taxon counts")]),
    # Results
    "chemical": dict(group="results", label="Chemistry", row="One set of chemistry readings from a visit.",
                     about="Temperatures, nitrate (mg/L as N), phosphate, pH, turbidity, dissolved oxygen, conductivity, chloride.",
                     sort="-chemical_id"),
    "bacteria": dict(group="results", label="E. coli", row="One bacteria result from a BACT visit.",
                     about="E. coli in MPN/100 mL; a note records '<' or '>' when the result was beyond the test range.",
                     sort="-bacteria_id"),
    "habitat_assessment": dict(group="results", label="Habitat assessments", row="One EPA rapid habitat assessment from a BAT visit.",
                               about="Each item is scored 0–20 (bank items 0–10). High- and low-gradient items differ.",
                               sort="-habitat_id"),
    # Biology
    "macro_analysis": dict(group="biology", label="Bug scores", row="The index scores for one BAT sample.",
                           about="NJIS, HGMI and CPMI from All StreamWatch Data, rated with the 2026 Assessment Framework bands.",
                           sort="-macro_analysis_id"),
    "bug_count": dict(group="biology", label="Taxon counts", row="How many of one taxon were found in one sample.",
                      about="Detailed counts exist for 2014–2021 samples.", sort="-bug_count_id"),
    "rbp100_bug": dict(group="biology", label="100-organism subsample counts", row="One taxon's count in the standardized 100-organism subsample."),
    "bug_list": dict(group="biology", label="Taxa list", row="One kind of macroinvertebrate, with its traits and tolerance values.",
                     sort="family", related=[("bug_count", "bug_id", "Counts")]),
    # People
    "volunteer": dict(group="people", label="Volunteers", row="One volunteer. Contact details are hidden here.",
                      sort="last_name", app="/volunteers/{volunteer_id}",
                      hidden={"email", "alt_email", "phone", "alt_phone", "address", "zip_code", "perfect_id"},
                      related=[("junc_assignments", "volunteer_id", "Assignments"), ("training_log", "volunteer_id", "Training")]),
    "junc_assignments": dict(group="people", label="Site assignments", row="One volunteer assigned to one site in a role."),
    "training": dict(group="people", label="Training sessions", row="One training event.", sort="-training_date",
                     related=[("training_log", "training_id", "Attendees")]),
    "training_log": dict(group="people", label="Training records", row="One volunteer's completion of one training."),
    "junc_attendance": dict(group="people", label="Visit attendance", row="One volunteer at one visit (not filled in yet)."),
    # Equipment
    "equipment": dict(group="equipment", label="Meters", row="One meter.", sort="equipment_code", app="/equipment/{equipment_code}",
                      related=[("meter_testing", "equipment_id", "Tests")]),
    "meter_testing": dict(group="equipment", label="Meter tests", row="One parameter check on one meter in a test session.",
                          sort="-meter_testing_id"),
    "session": dict(group="equipment", label="Test sessions", row="One meter testing or maintenance session.", sort="-date_start",
                    related=[("meter_testing", "session_id", "Tests")]),
    "sensor": dict(group="equipment", label="Sensors", row="One sensor in a meter (not filled in yet)."),
    "meter_maintenance": dict(group="equipment", label="Meter maintenance", row="One maintenance check (not filled in yet)."),
    "calibration_log": dict(group="equipment", label="Calibrations", row="One calibration (not filled in yet)."),
    "equipment_loans": dict(group="equipment", label="Equipment loans", row="One meter lent to a volunteer (not filled in yet)."),
    "temp_corrections": dict(group="equipment", label="Temperature corrections", row="One sensor's temperature correction (not filled in yet)."),
    # Quality
    "data_condition": dict(group="quality", label="Data Condition codes", row="One review status used on results (Provisional, Outlier, …).",
                           sort="code"),
    "result_flag": dict(group="quality", label="Automated flags", row="One automated check that flagged a result (e.g. nitrate over 10 mg/L).",
                        sort="-result_flag_id"),
    "flag_type": dict(group="quality", label="Flag types", row="One kind of automated flag.", sort="code"),
    # Lookups
    "lst_method": dict(group="lookups", label="Methods / programs", row="One method or program (CAT: Hanna, BACT, BAT, …).", sort="name"),
    "lst_role": dict(group="lookups", label="Volunteer roles", row="One role."),
    "lst_priority": dict(group="lookups", label="Priorities", row="One priority level."),
    "lst_groundtruthing_status": dict(group="lookups", label="Groundtruthing statuses", row="One status."),
    "lst_training_type": dict(group="lookups", label="Training types", row="One kind of training."),
    "lst_session_type": dict(group="lookups", label="Session types", row="One kind of equipment session."),
    "lst_troubleshooting": dict(group="lookups", label="Troubleshooting codes", row="One meter troubleshooting step (not filled in yet)."),
}

# How a linked record is named, given its key: SQL with {k} = the key expression.
LINK_LABEL = {
    "site": "(SELECT site_code FROM site WHERE site_id = {k})",
    "visit": ("(SELECT s.site_code || ' · ' || to_char(v.sample_date, 'YYYY-MM-DD') || COALESCE(' · ' || m.name, '') "
              "FROM visit v JOIN site s ON s.site_id = v.site_id LEFT JOIN lst_method m ON m.method_id = v.method_id "
              "WHERE v.visit_id = {k})"),
    "waterbody": "(SELECT name FROM waterbody WHERE waterbody_id = {k})",
    "municipality": "(SELECT name FROM municipality WHERE municipality_id = {k})",
    "subwatershed": "(SELECT name FROM subwatershed WHERE subwatershed_id = {k})",
    "lst_method": "(SELECT name FROM lst_method WHERE method_id = {k})",
    "data_condition": "(SELECT code FROM data_condition WHERE data_condition_id = {k})",
    "flag_type": "(SELECT code FROM flag_type WHERE flag_type_id = {k})",
    "volunteer": "(SELECT first_name || ' ' || last_name FROM volunteer WHERE volunteer_id = {k})",
    "equipment": "(SELECT equipment_code FROM equipment WHERE equipment_id = {k})",
    "bug_list": "(SELECT COALESCE(NULLIF(genus_species, ''), family, bug_code) FROM bug_list WHERE bug_id = {k})",
    "lst_role": "(SELECT name FROM lst_role WHERE role_id = {k})",
    "lst_priority": "(SELECT label FROM lst_priority WHERE priority_id = {k})",
    "lst_groundtruthing_status": "(SELECT label FROM lst_groundtruthing_status WHERE groundtruthing_status_id = {k})",
    "lst_training_type": "(SELECT name FROM lst_training_type WHERE training_type_id = {k})",
    "lst_session_type": "(SELECT name FROM lst_session_type WHERE session_type_id = {k})",
    "lst_troubleshooting": "(SELECT code FROM lst_troubleshooting WHERE troubleshooting_id = {k})",
    "training": ("(SELECT COALESCE(tt.name, 'Training') || ' · ' || COALESCE(to_char(t.training_date, 'YYYY-MM-DD'), '') "
                 "FROM training t LEFT JOIN lst_training_type tt ON tt.training_type_id = t.training_type_id WHERE t.training_id = {k})"),
    "session": ("(SELECT COALESCE(st.name, 'Session') || ' · ' || COALESCE(to_char(s.date_start, 'YYYY-MM-DD'), '') "
                "FROM session s LEFT JOIN lst_session_type st ON st.session_type_id = s.session_type_id WHERE s.session_id = {k})"),
    "sensor": "(SELECT sensor_type::text || COALESCE(' ' || serial_number, '') FROM sensor WHERE sensor_id = {k})",
    "tbl_huc14": "(SELECT code FROM tbl_huc14 WHERE huc14_id = {k})",
    "tbl_huc13": "(SELECT code FROM tbl_huc13 WHERE huc13_id = {k})",
}

# Column headings that need more than tidying the name.
COLUMN_LABELS = {
    "nitrate_ug_l": "Nitrate (mg/L as N)",  # stored in mg/L despite the column name
    "nitrate_dilution_adj": "Nitrate dilution adj.",
    "air_temp_c": "Air temp (°C)", "water_temp_c": "Water temp (°C)",
    "phosphate_mg_l": "Phosphate (mg/L)", "chloride_mg_l": "Chloride (mg/L)",
    "ph": "pH", "turbidity_ntu": "Turbidity (NTU)",
    "dissolved_oxygen_ppm": "Dissolved oxygen (mg/L)", "dissolved_oxygen_pct": "Dissolved oxygen (%)",
    "conductivity_us_cm": "Conductivity (µS/cm)", "e_coli_mpn_100ml": "E. coli (MPN/100 mL)",
    "total_coliform_mpn": "Total coliform (MPN)", "drainage_area_sq_km": "Drainage area (km²)",
    "source_data_condition": "Data Condition (combined)", "detection_limit_note": "Limit note",
    "njis_score": "NJIS", "njis_rating": "NJIS rating", "hgmi_genus": "HGMI (genus)", "hgmi_family": "HGMI (family)",
    "hgmi_rating": "HGMI rating", "cpmi_score": "CPMI", "cpmi_rating": "CPMI rating", "fbi": "FBI", "hbi": "HBI",
    "pct_ept": "% EPT", "ept_taxa": "EPT taxa", "pct_dominance": "% dominance", "tolerance_ftv": "Tolerance (FTV)",
    "tolerance_nytol": "Tolerance (NY)", "tsn": "TSN", "ept": "EPT", "is_under_17": "Under 17",
    "active_cat": "Active CAT", "active_bat": "Active BAT", "active_bact": "Active BACT",
    "result_table": "Result type", "result_pk": "Result record",
}
ALWAYS_HIDDEN = {"created_at", "updated_at"}
HIDDEN_TYPES = {"bytea", "jsonb", "json"}
RATING_COLUMNS = {"njis_rating", "hgmi_rating", "cpmi_rating"}


# Name for a column that links to another table (when the column is that table's key).
LINK_NAMES = {
    "site": "Site", "visit": "Visit", "waterbody": "Waterbody", "municipality": "Town",
    "subwatershed": "Subwatershed", "lst_method": "Method", "data_condition": "Data Condition",
    "flag_type": "Flag type", "volunteer": "Volunteer", "equipment": "Meter", "bug_list": "Taxon",
    "lst_role": "Role", "lst_groundtruthing_status": "Groundtruthing status", "lst_training_type": "Training type",
    "lst_session_type": "Session type", "lst_troubleshooting": "Troubleshooting step", "training": "Training",
    "session": "Session", "sensor": "Sensor", "tbl_huc14": "HUC-14", "tbl_huc13": "HUC-13",
}
_ACRONYMS = {"cat": "CAT", "bat": "BAT", "bact": "BACT", "huc14": "HUC-14", "huc13": "HUC-13", "id": "ID"}


def _tidy(words: str) -> str:
    parts = [_ACRONYMS.get(w, w) for w in words.split("_") if w]
    text = " ".join(parts)
    return text[:1].upper() + text[1:]


def column_label(col: str, fk_parent: str | None = None) -> str:
    if col in COLUMN_LABELS:
        return COLUMN_LABELS[col]
    if fk_parent:
        base = col[:-3] if col.endswith("_id") else col
        generic = {"city", "parent", "partner"} | {f"{p}_priority" for p in ("cat", "bat", "bact")}
        if base in generic or fk_parent not in LINK_NAMES:
            return _tidy(base)
        return LINK_NAMES[fk_parent]
    return _tidy(col)


def sort_spec(raw: str | None, columns: list[str], default: str | None, pk: str | None):
    """Return (column, descending) using only real column names."""
    for candidate in (raw, default, pk):
        if not candidate:
            continue
        desc = candidate.startswith("-")
        name = candidate.lstrip("-")
        if name in columns:
            return name, desc
    return (columns[0], False) if columns else (None, False)


def format_value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, Decimal):
        s = format(v.normalize(), "f")
        return s.rstrip("0").rstrip(".") if "." in s else s
    if isinstance(v, float):
        return ("%.6g" % v) if math.isfinite(v) else str(v)
    if isinstance(v, (datetime,)):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, (date, dtime)):
        return v.isoformat()
    return str(v)


class Schema:
    """Columns, primary keys and relationships, read from the database (cached)."""

    TTL = 300

    def __init__(self):
        self.loaded_at = 0.0
        self.columns: dict[str, list[tuple[str, str]]] = {}
        self.pk: dict[str, str] = {}
        self.fks: dict[str, dict[str, str]] = {}  # table -> {column: parent table}

    def load(self, cur):
        if time.time() - self.loaded_at < self.TTL and self.columns:
            return self
        cur.execute(
            """SELECT table_name, column_name, data_type FROM information_schema.columns
               WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"""
        )
        cols: dict[str, list[tuple[str, str]]] = {}
        for t, c, dt in cur.fetchall():
            cols.setdefault(t, []).append((c, dt))
        cur.execute(
            """SELECT c.conrelid::regclass::text, a.attname FROM pg_constraint c
               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
               WHERE c.contype = 'p' AND array_length(c.conkey, 1) = 1 AND c.connamespace = 'public'::regnamespace"""
        )
        pk = dict(cur.fetchall())
        cur.execute(
            """SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text FROM pg_constraint c
               JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
               WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace"""
        )
        fks: dict[str, dict[str, str]] = {}
        for t, c, parent in cur.fetchall():
            fks.setdefault(t, {})[c] = parent
        self.columns, self.pk, self.fks, self.loaded_at = cols, pk, fks, time.time()
        return self

    def visible_columns(self, table: str) -> list[str]:
        hidden = ALWAYS_HIDDEN | CATALOG[table].get("hidden", set())
        return [c for c, dt in self.columns.get(table, []) if c not in hidden and dt not in HIDDEN_TYPES and _IDENT.match(c)]


SCHEMA = Schema()


def build_query(table: str, schema: Schema, args) -> tuple[str, list, list[dict], str, list[str]]:
    """SQL for one page of a table. Returns (inner_sql, params, column_meta, sort_col, where_desc)."""
    if table not in CATALOG or not _IDENT.match(table):
        raise KeyError(table)
    cols = schema.visible_columns(table)
    fks = schema.fks.get(table, {})
    select, meta, params, where, desc = [], [], [], ["TRUE"], []
    for c in cols:
        select.append(f'{ROW}."{c}"')
        parent = fks.get(c)
        m = {"name": c, "label": column_label(c, parent), "parent": parent if parent in CATALOG else None,
             "rating": c in RATING_COLUMNS}
        if parent in LINK_LABEL:
            select.append(LINK_LABEL[parent].format(k=f'{ROW}."{c}"') + f' AS "{c}__label"')
            m["has_label"] = True
        meta.append(m)

    # Filter by a linked record, e.g. ?visit_id=123 (only real link/key columns, integer values)
    for c in [*fks.keys(), schema.pk.get(table)]:
        if c and c in cols and args.get(c, "").strip().lstrip("-").isdigit():
            where.append(f'{ROW}."{c}" = %s')
            params.append(int(args[c]))
            desc.append(f"{column_label(c, fks.get(c))} = {args[c]}")

    # Filter by site code for anything that hangs off a site or a visit
    site = (args.get("site") or "").strip()
    if site:
        if "site_code" in cols:
            where.append(f"{ROW}.site_code = %s")
        elif "site_id" in cols:
            where.append(f"{ROW}.site_id IN (SELECT site_id FROM site WHERE site_code = %s)")
        elif "visit_id" in cols:
            where.append(f"{ROW}.visit_id IN (SELECT v.visit_id FROM visit v JOIN site s ON s.site_id = v.site_id WHERE s.site_code = %s)")
        else:
            site = ""
        if site:
            params.append(site)
            desc.append(f"Site {site}")

    inner = f'SELECT {", ".join(select)} FROM "{table}" {ROW} WHERE {" AND ".join(where)}'
    sort_col, _ = sort_spec(args.get("sort"), cols, CATALOG[table].get("sort"), schema.pk.get(table))
    return inner, params, meta, sort_col, desc


def register(app, get_db):
    def connection():
        conn = get_db()
        conn.set_session(readonly=True, autocommit=True)
        return conn

    @app.route("/data")
    def data_browser_page():
        try:
            conn = connection()
        except Exception:
            return render_template("data_browser.html", error="The database is not reachable right now.", groups=[]), 503
        try:
            cur = conn.cursor()
            SCHEMA.load(cur)
            counts = {}
            for table in CATALOG:
                if table in SCHEMA.columns:
                    cur.execute(f'SELECT count(*) FROM "{table}"')
                    counts[table] = cur.fetchone()[0]
            groups = []
            for key, title, blurb in GROUPS:
                tables = [dict(name=t, count=counts.get(t, 0), **CATALOG[t]) for t in CATALOG
                          if CATALOG[t]["group"] == key and t in SCHEMA.columns]
                groups.append(dict(key=key, title=title, blurb=blurb, tables=tables))
            n_links = sum(1 for t, f in SCHEMA.fks.items() if t in CATALOG for p in f.values() if p in CATALOG)
            return render_template("data_browser.html", error=None, groups=groups, counts=counts,
                                   n_tables=len(counts), n_links=n_links, rel_map=map_layout(counts))
        finally:
            conn.close()

    def _rows(table, limit, offset):
        conn = connection()
        try:
            cur = conn.cursor()
            SCHEMA.load(cur)
            if table not in SCHEMA.columns:
                abort(404)
            inner, params, meta, sort_col, desc = build_query(table, SCHEMA, request.args)
            q = (request.args.get("q") or "").strip()[:100]
            outer_where, outer_params = "", []
            if q:
                outer_where = " WHERE CAST(q AS text) ILIKE %s"
                outer_params = ["%" + q.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"]
            _, descending = sort_spec(request.args.get("sort"), SCHEMA.visible_columns(table),
                                      CATALOG[table].get("sort"), SCHEMA.pk.get(table))
            cur.execute(f"SELECT count(*) FROM ({inner}) q{outer_where}", params + outer_params)
            total = cur.fetchone()[0]
            order = f'q."{sort_col}" {"DESC" if descending else "ASC"} NULLS LAST' if sort_col else "1"
            cur.execute(f"SELECT * FROM ({inner}) q{outer_where} ORDER BY {order} LIMIT %s OFFSET %s",
                        params + outer_params + [limit, offset])
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, r)) for r in cur.fetchall()]
            return rows, total, meta, sort_col, descending, desc, q
        finally:
            conn.close()

    @app.route("/data/<table>")
    def data_table_page(table):
        if table not in CATALOG:
            abort(404)
        try:
            page = max(1, min(int(request.args.get("page", "1")), 100000))
        except ValueError:
            page = 1
        try:
            rows, total, meta, sort_col, descending, filters, q = _rows(table, PAGE_SIZE, (page - 1) * PAGE_SIZE)
        except KeyError:
            abort(404)
        info = CATALOG[table]
        pk = SCHEMA.pk.get(table)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        base_args = {k: v for k, v in request.args.items() if k != "page"}
        parents = sorted({m["parent"] for m in meta if m["parent"]})
        children = [(child, col, label) for child, col, label in info.get("related", []) if child in CATALOG]
        referenced_by = sorted({t for t, f in SCHEMA.fks.items() if t in CATALOG and table in f.values()} - {c for c, _, _ in children})
        return render_template(
            "data_table.html", table=table, info=info, group=dict((g[0], g[1]) for g in GROUPS)[info["group"]],
            rows=rows, total=total, meta=meta, pk=pk, page=page, pages=pages, sort_col=sort_col,
            descending=descending, filters=filters, q=q, base_args=base_args, fmt=format_value,
            parents=parents, children=children, referenced_by=referenced_by, catalog=CATALOG,
            parent_pk={p: SCHEMA.pk.get(p, "id") for p in parents},
            site=(request.args.get("site") or "").strip(), can_filter_site=any(
                c in SCHEMA.visible_columns(table) for c in ("site_code", "site_id", "visit_id")),
            csv_url=url_for("data_table_csv", table=table, **{k: v for k, v in base_args.items()}),
        )

    @app.route("/data/<table>.csv")
    def data_table_csv(table):
        if table not in CATALOG:
            abort(404)
        rows, total, meta, *_ = _rows(table, CSV_LIMIT, 0)
        buf = io.StringIO()
        w = csv.writer(buf)
        header = []
        for m in meta:
            header.append(m["label"])
            if m.get("has_label"):
                header.append(m["label"] + " (name)")
        w.writerow(header)
        for r in rows:
            line = []
            for m in meta:
                line.append(format_value(r.get(m["name"])))
                if m.get("has_label"):
                    line.append(format_value(r.get(m["name"] + "__label")))
            w.writerow(line)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="streamwatch_{table}.csv"'})


# --------------------------------------------------------------------------
# Relationship map (overview page). Hand-placed so it reads left to right:
# places -> sites -> visits -> results, with people and equipment below.
# --------------------------------------------------------------------------
MAP_W, MAP_H, NODE_W, NODE_H = 1060, 560, 190, 50
MAP_NODES = {
    # table: (x, y)
    "waterbody": (20, 40), "municipality": (20, 120), "subwatershed": (20, 200),
    "site": (290, 120), "junc_assignments": (290, 280), "volunteer": (290, 380), "training_log": (290, 480),
    "training": (20, 480),
    "lst_method": (560, 30), "visit": (560, 120), "data_condition": (560, 250), "equipment": (560, 380), "session": (560, 480),
    "chemical": (850, 20), "bacteria": (850, 85), "habitat_assessment": (850, 150), "macro_analysis": (850, 215),
    "bug_count": (850, 280), "bug_list": (850, 345), "meter_testing": (850, 440),
}
MAP_EDGES = [
    # (from, to, dashed)
    ("site", "waterbody", False), ("site", "municipality", False), ("site", "subwatershed", False),
    ("visit", "site", False), ("visit", "lst_method", False),
    ("chemical", "visit", False), ("bacteria", "visit", False), ("habitat_assessment", "visit", False),
    ("macro_analysis", "visit", False), ("bug_count", "visit", False), ("bug_count", "bug_list", False),
    ("chemical", "data_condition", True), ("bacteria", "data_condition", True),
    ("junc_assignments", "site", False), ("junc_assignments", "volunteer", False),
    ("training_log", "volunteer", False), ("training_log", "training", False),
    ("meter_testing", "equipment", False), ("meter_testing", "session", False),
]


def map_layout(counts: dict) -> dict:
    nodes = []
    for table, (x, y) in MAP_NODES.items():
        info = CATALOG[table]
        nodes.append(dict(table=table, x=x, y=y, label=info["label"], count=counts.get(table),
                          group=info["group"], cx=x + NODE_W / 2, cy=y + NODE_H / 2))
    pos = {n["table"]: n for n in nodes}
    edges = []
    for a, b, dashed in MAP_EDGES:
        na, nb = pos[a], pos[b]
        # attach to the facing sides so lines don't run under the boxes
        if abs(na["cx"] - nb["cx"]) >= NODE_W:
            x1 = na["x"] if na["cx"] > nb["cx"] else na["x"] + NODE_W
            x2 = nb["x"] + NODE_W if na["cx"] > nb["cx"] else nb["x"]
            y1, y2 = na["cy"], nb["cy"]
        else:
            x1, x2 = na["cx"], nb["cx"]
            y1 = na["y"] if na["cy"] > nb["cy"] else na["y"] + NODE_H
            y2 = nb["y"] + NODE_H if na["cy"] > nb["cy"] else nb["y"]
        mx = (x1 + x2) / 2
        path = f"M{x1:.0f},{y1:.0f} C{mx:.0f},{y1:.0f} {mx:.0f},{y2:.0f} {x2:.0f},{y2:.0f}" if x1 != x2 else f"M{x1:.0f},{y1:.0f} L{x2:.0f},{y2:.0f}"
        edges.append(dict(path=path, dashed=dashed))
    return dict(nodes=nodes, edges=edges, w=MAP_W, h=MAP_H, node_w=NODE_W, node_h=NODE_H)
