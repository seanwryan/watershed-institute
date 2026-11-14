"""
"Ask the data": a point-and-click query builder over StreamWatch.

A question is a dataset (e.g. chemistry results already joined to site, date,
method and condition), filters, and either a list of rows or a summary
(group by site / year / method..., with count, average, min, max, median).
Questions are carried in the URL, so they can be bookmarked, shared and saved.

Safety: every field is a fixed SQL expression from DATASETS below; requests can
only pick fields by key, and every value is a bound parameter. Connections are
read-only with a statement timeout. Saved questions are the only writes.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
from datetime import date
from urllib.parse import urlencode

from flask import Response, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.datastructures import MultiDict

ROW_PAGE = 100
SUMMARY_LIMIT = 2000
CSV_LIMIT = 50000
MAX_FILTERS = 12
MAX_MEASURES = 6
TIMEOUT_MS = 10000

# --------------------------------------------------------------------------
# Datasets
# --------------------------------------------------------------------------
_SITE_JOINS = (
    " JOIN visit v ON v.visit_id = {t}.visit_id"
    " JOIN site s ON s.site_id = v.site_id"
    " LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id"
    " LEFT JOIN lst_method vm ON vm.method_id = v.method_id"
)
_SUBWATERSHED = "(SELECT min(sw.name) FROM junc_site_subwatershed j JOIN subwatershed sw ON sw.subwatershed_id = j.subwatershed_id WHERE j.site_id = s.site_id)"
_TOWN = "(SELECT min(mu.name) FROM junc_site_municipality j JOIN municipality mu ON mu.municipality_id = j.municipality_id WHERE j.site_id = s.site_id)"


def F(label, sql, type_, group=False, unit=None, choices=False):
    return dict(label=label, sql=sql, type=type_, group=group, unit=unit, choices=choices)


def _place_and_time_fields():
    return {
        "site": F("Site", "s.site_code", "category", group=True, choices=True),
        "waterbody": F("Waterbody", "w.name", "category", group=True, choices=True),
        "subwatershed": F("Subwatershed", _SUBWATERSHED, "category", group=True, choices=True),
        "town": F("Town", _TOWN, "category", group=True, choices=True),
        "habitat_type": F("Site habitat type", "s.habitat_type::text", "category", group=True, choices=True),
        "site_active": F("Site is active", "s.is_active", "bool"),
        "date": F("Sample date", "v.sample_date", "date"),
        "year": F("Year", "extract(year from v.sample_date)::int", "number", group=True),
        "month": F("Month (YYYY-MM)", "to_char(v.sample_date, 'YYYY-MM')", "category", group=True),
        "month_of_year": F("Month of year (1–12)", "extract(month from v.sample_date)::int", "number", group=True),
        "visit_method": F("Program / method", "vm.name", "category", group=True, choices=True),
    }


def _condition(alias):
    return F("Data Condition", f"COALESCE((SELECT code FROM data_condition WHERE data_condition_id = {alias}.data_condition_id), {alias}.source_data_condition)",
             "category", group=True, choices=True)


DATASETS = {
    "chemistry": dict(
        label="Chemistry results", row="one set of chemistry readings from a visit",
        from_sql="chemical c" + _SITE_JOINS.format(t="c"),
        fields={
            **_place_and_time_fields(),
            "condition": _condition("c"),
            "water_temp_c": F("Water temperature", "c.water_temp_c", "number", unit="°C"),
            "air_temp_c": F("Air temperature", "c.air_temp_c", "number", unit="°C"),
            "nitrate": F("Nitrate (as N)", "c.nitrate_ug_l", "number", unit="mg/L"),
            "phosphate": F("Phosphate", "c.phosphate_mg_l", "number", unit="mg/L"),
            "ph": F("pH", "c.ph", "number"),
            "turbidity": F("Turbidity", "c.turbidity_ntu", "number", unit="NTU"),
            "do_mg_l": F("Dissolved oxygen", "c.dissolved_oxygen_ppm", "number", unit="mg/L"),
            "do_pct": F("Dissolved oxygen saturation", "c.dissolved_oxygen_pct", "number", unit="%"),
            "conductivity": F("Conductivity", "c.conductivity_us_cm", "number", unit="µS/cm"),
            "chloride": F("Chloride", "c.chloride_mg_l", "number", unit="mg/L"),
            "limit_note": F("Limit note", "c.detection_limit_note", "text"),
        },
        default_columns=["site", "date", "visit_method", "condition", "water_temp_c", "nitrate", "phosphate", "ph", "chloride"],
    ),
    "ecoli": dict(
        label="E. coli results", row="one bacteria result from a BACT visit",
        from_sql="bacteria b" + _SITE_JOINS.format(t="b"),
        fields={
            **_place_and_time_fields(),
            "condition": _condition("b"),
            "e_coli": F("E. coli", "b.e_coli_mpn_100ml", "number", unit="MPN/100 mL"),
            "total_coliform": F("Total coliform", "b.total_coliform_mpn", "number", unit="MPN"),
            "limit_note": F("Limit note (< or >)", "b.detection_limit_note", "text"),
        },
        default_columns=["site", "date", "condition", "e_coli", "limit_note"],
    ),
    "bug_scores": dict(
        label="Bug scores", row="the index scores for one BAT sample",
        from_sql="macro_analysis ma" + _SITE_JOINS.format(t="ma"),
        fields={
            **_place_and_time_fields(),
            "condition": _condition("ma"),
            "njis": F("NJIS", "ma.njis_score", "number"),
            "njis_rating": F("NJIS rating", "ma.njis_rating", "category", group=True, choices=True),
            "hgmi_genus": F("HGMI (genus)", "ma.hgmi_genus", "number"),
            "hgmi_family": F("HGMI (family)", "ma.hgmi_family", "number"),
            "hgmi_rating": F("HGMI rating", "ma.hgmi_rating", "category", group=True, choices=True),
            "cpmi": F("CPMI", "ma.cpmi_score", "number"),
            "cpmi_rating": F("CPMI rating", "ma.cpmi_rating", "category", group=True, choices=True),
            "fbi": F("FBI", "ma.fbi", "number"),
            "organisms": F("Organisms counted", "ma.total_organisms", "number"),
        },
        default_columns=["site", "date", "njis", "njis_rating", "hgmi_genus", "hgmi_family", "hgmi_rating", "cpmi", "cpmi_rating"],
    ),
    "habitat": dict(
        label="Habitat assessments", row="one EPA rapid habitat assessment",
        from_sql="habitat_assessment h" + _SITE_JOINS.format(t="h"),
        fields={
            **_place_and_time_fields(),
            **{k: F(lbl, f"h.{k}", "number") for k, lbl in [
                ("epifaunal_substrate", "Epifaunal substrate"), ("embeddedness", "Embeddedness"),
                ("velocity_depth", "Velocity/depth"), ("sediment_deposition", "Sediment deposition"),
                ("channel_flow_status", "Channel flow status"), ("channel_alteration", "Channel alteration"),
                ("freq_riffles", "Frequency of riffles"), ("pool_substrate", "Pool substrate"),
                ("pool_variability", "Pool variability"), ("channel_sinuosity", "Channel sinuosity"),
                ("bank_stability_left", "Bank stability (left)"), ("bank_stability_right", "Bank stability (right)"),
                ("bank_veg_protection_left", "Vegetative protection (left)"), ("bank_veg_protection_right", "Vegetative protection (right)"),
                ("riparian_zone_left", "Riparian zone (left)"), ("riparian_zone_right", "Riparian zone (right)")]},
        },
        default_columns=["site", "date", "epifaunal_substrate", "embeddedness", "sediment_deposition", "channel_flow_status", "channel_alteration"],
    ),
    "visits": dict(
        label="Visits", row="one team's sampling at one site on one day",
        from_sql=("visit v JOIN site s ON s.site_id = v.site_id"
                  " LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id"
                  " LEFT JOIN lst_method vm ON vm.method_id = v.method_id"),
        fields={
            **_place_and_time_fields(),
            "notes": F("Notes", "v.notes", "text"),
            "has_chemistry": F("Has chemistry", "EXISTS (SELECT 1 FROM chemical x WHERE x.visit_id = v.visit_id)", "bool"),
            "has_ecoli": F("Has E. coli", "EXISTS (SELECT 1 FROM bacteria x WHERE x.visit_id = v.visit_id)", "bool"),
            "has_bug_scores": F("Has bug scores", "EXISTS (SELECT 1 FROM macro_analysis x WHERE x.visit_id = v.visit_id)", "bool"),
            "has_habitat": F("Has habitat", "EXISTS (SELECT 1 FROM habitat_assessment x WHERE x.visit_id = v.visit_id)", "bool"),
        },
        default_columns=["site", "date", "visit_method", "notes"],
    ),
    "sites": dict(
        label="Sites", row="one monitoring location",
        from_sql="site s LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id",
        fields={
            "site": F("Site", "s.site_code", "category", group=True, choices=True),
            "waterbody": F("Waterbody", "w.name", "category", group=True, choices=True),
            "subwatershed": F("Subwatershed", _SUBWATERSHED, "category", group=True, choices=True),
            "town": F("Town", _TOWN, "category", group=True, choices=True),
            "habitat_type": F("Habitat type", "s.habitat_type::text", "category", group=True, choices=True),
            "site_active": F("Active", "s.is_active", "bool"),
            "drainage_km2": F("Drainage area", "s.drainage_area_sq_km", "number", unit="km²"),
            "description": F("Description", "s.description", "text"),
            "last_sample": F("Latest sample", "(SELECT max(sample_date) FROM visit x WHERE x.site_id = s.site_id)", "date"),
            "visits": F("Number of visits", "(SELECT count(*) FROM visit x WHERE x.site_id = s.site_id)", "number"),
        },
        default_columns=["site", "waterbody", "town", "habitat_type", "site_active", "last_sample", "visits"],
    ),
    "meter_tests": dict(
        label="Meter tests", row="one parameter check on one meter",
        from_sql=("meter_testing mt JOIN equipment e ON e.equipment_id = mt.equipment_id"
                  " LEFT JOIN session ss ON ss.session_id = mt.session_id"),
        fields={
            "meter": F("Meter", "e.equipment_code", "category", group=True, choices=True),
            "date": F("Session date", "ss.date_start", "date"),
            "year": F("Year", "extract(year from ss.date_start)::int", "number", group=True),
            "parameter": F("Parameter", "mt.parameter_type", "category", group=True, choices=True),
            "result": F("Pass / fail", "mt.pass_fail", "category", group=True, choices=True),
            "reference": F("Reference value", "mt.reference_value", "number"),
            "measured": F("Measured value", "mt.measured_value", "number"),
            "difference": F("Difference", "mt.difference", "number"),
            "action": F("Action taken", "mt.action_taken", "text"),
        },
        default_columns=["meter", "date", "parameter", "reference", "measured", "difference", "result"],
    ),
}

OPS = {
    "number": [("eq", "="), ("ne", "≠"), ("gt", ">"), ("gte", "≥"), ("lt", "<"), ("lte", "≤"), ("between", "between"), ("empty", "is empty"), ("notempty", "has a value")],
    "category": [("is", "is"), ("isnot", "is not"), ("in", "is any of"), ("contains", "contains"), ("empty", "is empty"), ("notempty", "has a value")],
    "text": [("contains", "contains"), ("is", "is"), ("isnot", "is not"), ("empty", "is empty"), ("notempty", "has a value")],
    "date": [("on", "on"), ("after", "on or after"), ("before", "on or before"), ("between", "between"), ("empty", "is empty"), ("notempty", "has a value")],
    "bool": [("true", "is yes"), ("false", "is no")],
}
AGGS = [("count", "Count"), ("avg", "Average"), ("median", "Median"), ("min", "Minimum"), ("max", "Maximum"), ("sum", "Total")]
_AGG_SQL = {"avg": "round(avg({e})::numeric, 3)", "median": "round((percentile_cont(0.5) WITHIN GROUP (ORDER BY {e}))::numeric, 3)",
            "min": "min({e})", "max": "max({e})", "sum": "sum({e})", "count": "count({e})"}


class QuestionError(ValueError):
    """A problem with the question the person asked (shown to them, not a crash)."""


# --------------------------------------------------------------------------
# Parsing a question from request args
# --------------------------------------------------------------------------
def parse_question(args) -> dict:
    ds_key = args.get("ds") or "chemistry"
    if ds_key not in DATASETS:
        raise QuestionError("Unknown dataset.")
    ds = DATASETS[ds_key]
    fields = ds["fields"]
    filters = []
    fs, os_, vs, v2s = args.getlist("f"), args.getlist("o"), args.getlist("v"), args.getlist("v2")
    for i, fkey in enumerate(fs[:MAX_FILTERS]):
        if not fkey:
            continue
        if fkey not in fields:
            raise QuestionError(f"Unknown field “{fkey}”.")
        op = os_[i] if i < len(os_) else ""
        if op not in dict(OPS[fields[fkey]["type"]]):
            raise QuestionError(f"“{op}” doesn't apply to {fields[fkey]['label']}.")
        filters.append(dict(field=fkey, op=op, value=(vs[i] if i < len(vs) else "").strip(), value2=(v2s[i] if i < len(v2s) else "").strip()))
    mode = "summary" if args.get("mode") == "summary" else "rows"
    picked = list(dict.fromkeys(c for c in args.getlist("col") if c in fields))
    cols = picked or [c for c in ds["default_columns"] if c in fields]
    # Stable, sensible order: the dataset's default columns first, then the rest in field order.
    order = {k: i for i, k in enumerate(ds["default_columns"])}
    field_pos = {k: i for i, k in enumerate(fields)}
    cols.sort(key=lambda c: (order.get(c, 1000), field_pos[c]))
    groups = [g for g in args.getlist("group") if g in fields and fields[g]["group"]][:2]
    measures = []
    for m in args.getlist("m")[:MAX_MEASURES]:
        agg, _, fkey = m.partition(":")
        if agg == "count" and fkey in ("", "*"):
            measures.append(("count", "*"))
        elif agg in _AGG_SQL and fkey in fields and fields[fkey]["type"] == "number":
            measures.append((agg, fkey))
    if mode == "summary" and not measures:
        measures = [("count", "*")]
    sort = args.get("sort") or ""
    desc = args.get("dir") == "desc"
    try:
        page = max(1, min(int(args.get("page", "1")), 100000))
    except ValueError:
        page = 1
    return dict(ds=ds_key, filters=filters, mode=mode, cols=cols, groups=groups, measures=measures,
                sort=sort, desc=desc, page=page)


def _num(v, label):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise QuestionError(f"{label}: “{v}” isn't a number.")


def _date(v, label):
    try:
        return date.fromisoformat(v)
    except (TypeError, ValueError):
        raise QuestionError(f"{label}: “{v}” isn't a date (use YYYY-MM-DD).")


def _like(v):
    return "%" + v.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def where_clause(q) -> tuple[str, list]:
    fields = DATASETS[q["ds"]]["fields"]
    parts, params = [], []
    for f in q["filters"]:
        fd = fields[f["field"]]
        e, op, v, v2, lbl = fd["sql"], f["op"], f["value"], f["value2"], fd["label"]
        t = fd["type"]
        if op == "empty":
            parts.append(f"({e}) IS NULL" if t != "text" else f"COALESCE(({e}), '') = ''")
            continue
        if op == "notempty":
            parts.append(f"({e}) IS NOT NULL" if t != "text" else f"COALESCE(({e}), '') <> ''")
            continue
        if t == "bool":
            parts.append(f"({e}) IS {'TRUE' if op == 'true' else 'FALSE'}")
            continue
        if not v:
            raise QuestionError(f"{lbl}: enter a value.")
        if t == "number":
            sym = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}.get(op)
            if op == "between":
                parts.append(f"({e}) BETWEEN %s AND %s"); params += [_num(v, lbl), _num(v2, lbl)]
            else:
                parts.append(f"({e}) {sym} %s"); params.append(_num(v, lbl))
        elif t == "date":
            if op == "between":
                parts.append(f"({e}) BETWEEN %s AND %s"); params += [_date(v, lbl), _date(v2, lbl)]
            else:
                parts.append(f"({e}) {dict(on='=', after='>=', before='<=')[op]} %s"); params.append(_date(v, lbl))
        else:
            if op == "is":
                parts.append(f"({e})::text = %s"); params.append(v)
            elif op == "isnot":
                parts.append(f"(({e}) IS NULL OR ({e})::text <> %s)"); params.append(v)
            elif op == "in":
                items = [x.strip() for x in v.split(",") if x.strip()][:200]
                parts.append(f"({e})::text = ANY(%s)"); params.append(items)
            elif op == "contains":
                parts.append(f"({e})::text ILIKE %s"); params.append(_like(v))
    return (" WHERE " + " AND ".join(parts)) if parts else "", params


def build_sql(q, *, for_csv=False):
    """Return (sql, params, columns) where columns = [(key, label, unit, kind)]."""
    ds = DATASETS[q["ds"]]
    fields = ds["fields"]
    where, params = where_clause(q)
    if q["mode"] == "summary":
        sel, cols = [], []
        for g in q["groups"]:
            sel.append(f'({fields[g]["sql"]}) AS "{g}"')
            cols.append((g, fields[g]["label"], fields[g]["unit"], "group"))
        for agg, fkey in q["measures"]:
            key = f"{agg}__{fkey if fkey != '*' else 'rows'}"
            expr = "count(*)" if fkey == "*" else _AGG_SQL[agg].format(e=f"({fields[fkey]['sql']})")
            label = "Number of rows" if fkey == "*" else f"{dict(AGGS)[agg]} {fields[fkey]['label'].lower()}" if agg != "count" else f"Readings of {fields[fkey]['label'].lower()}"
            sel.append(f'{expr} AS "{key}"')
            cols.append((key, label, None if agg == "count" else fields[fkey]["unit"], "measure"))
        group_by = (" GROUP BY " + ", ".join(str(i + 1) for i in range(len(q["groups"])))) if q["groups"] else ""
        keys = [c[0] for c in cols]
        order_key = q["sort"] if q["sort"] in keys else (keys[0] if q["groups"] else None)
        order = f' ORDER BY "{order_key}" {"DESC" if q["desc"] else "ASC"} NULLS LAST' if order_key else ""
        limit = CSV_LIMIT if for_csv else SUMMARY_LIMIT
        sql = f"SELECT {', '.join(sel)} FROM {ds['from_sql']}{where}{group_by}{order} LIMIT {limit}"
        return sql, params, cols
    cols = [(c, fields[c]["label"], fields[c]["unit"], fields[c]["type"]) for c in q["cols"]]
    sel = [f'({fields[c]["sql"]}) AS "{c}"' for c in q["cols"]]
    keys = [c[0] for c in cols]
    default_sort = "date" if "date" in keys else keys[0]
    order_key = q["sort"] if q["sort"] in keys else default_sort
    desc = q["desc"] if q["sort"] in keys else (order_key == "date")
    order = f' ORDER BY "{order_key}" {"DESC" if desc else "ASC"} NULLS LAST'
    limit_sql = f" LIMIT {CSV_LIMIT}" if for_csv else f" LIMIT {ROW_PAGE} OFFSET {(q['page'] - 1) * ROW_PAGE}"
    sql = f"SELECT {', '.join(sel)} FROM {ds['from_sql']}{where}{order}{limit_sql}"
    return sql, params, cols


def count_sql(q):
    ds = DATASETS[q["ds"]]
    where, params = where_clause(q)
    if q["mode"] == "summary" and q["groups"]:
        fields = ds["fields"]
        g = ", ".join(f'({fields[k]["sql"]})' for k in q["groups"])
        return f"SELECT count(*) FROM (SELECT 1 FROM {ds['from_sql']}{where} GROUP BY {g}) z", params
    return f"SELECT count(*) FROM {ds['from_sql']}{where}", params


def question_args(q, **overrides) -> dict:
    """The question back as URL args (for links: sort, page, CSV, save)."""
    out = {"ds": q["ds"], "mode": q["mode"]}
    multi = {"f": [], "o": [], "v": [], "v2": []}
    for f in q["filters"]:
        multi["f"].append(f["field"]); multi["o"].append(f["op"]); multi["v"].append(f["value"]); multi["v2"].append(f["value2"])
    if q["mode"] == "summary":
        multi["group"] = q["groups"]
        multi["m"] = [f"{a}:{k}" for a, k in q["measures"]]
    else:
        multi["col"] = q["cols"]
    if q["sort"]:
        out["sort"] = q["sort"]
        if q["desc"]:
            out["dir"] = "desc"
    out.update(multi)
    out.update(overrides)
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def to_query_string(args: dict) -> str:
    return urlencode(args, doseq=True)


def chart_spec(q, cols, rows):
    """A simple chart for summaries: line over time, bars otherwise."""
    if q["mode"] != "summary" or not q["groups"] or not rows:
        return None
    measures = [c for c in cols if c[3] == "measure"]
    if not measures:
        return None
    m = measures[0]
    g1 = q["groups"][0]
    time_axis = g1 in ("year", "month", "month_of_year")
    if len(q["groups"]) == 2:
        g2 = q["groups"][1]
        series_names = []
        for r in rows:
            if r[g2] not in series_names:
                series_names.append(r[g2])
        series_names = series_names[:8]
        labels = sorted({r[g1] for r in rows if r[g1] is not None}, key=lambda x: (str(type(x)), x))
        data = {s: {r[g1]: r[m[0]] for r in rows if r[g2] == s} for s in series_names}
        return dict(type="line" if time_axis else "bar", labels=[str(x) for x in labels], measure=m[1],
                    series=[dict(name=str(s), values=[_float(data[s].get(x)) for x in labels]) for s in series_names],
                    truncated=len({r[g2] for r in rows}) > 8)
    pts = [(r[g1], r[m[0]]) for r in rows if r[g1] is not None][:200]
    if time_axis:
        pts.sort(key=lambda p: p[0])
    return dict(type="line" if time_axis else "bar", labels=[str(p[0]) for p in pts], measure=m[1],
                series=[dict(name=m[1], values=[_float(p[1]) for p in pts])], truncated=False)


def _float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
def register(app, get_db, fmt):
    def ro_conn():
        conn = get_db()
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        return conn

    def csrf_token():
        if "ask_csrf" not in session:
            session["ask_csrf"] = secrets.token_hex(24)
        return session["ask_csrf"]

    def check_csrf():
        if not session.get("ask_csrf") or not secrets.compare_digest(session["ask_csrf"], request.form.get("csrf", "")):
            abort(400, "This form expired. Reload the page and try again.")

    def saved_questions(cur):
        try:
            cur.execute("SELECT question_id, name, description, query, is_starter FROM saved_question ORDER BY is_starter DESC, lower(name)")
            return [dict(zip(["id", "name", "description", "query", "starter"], r)) for r in cur.fetchall()], True
        except Exception:
            return [], False

    @app.route("/data/ask")
    def data_ask_page():
        error, rows, cols, total, sql_text, chart = None, [], [], 0, None, None
        q = None
        asked = "ds" in request.args
        try:
            q = parse_question(request.args)
        except QuestionError as exc:
            # Show the problem and fall back to a blank question on the same dataset.
            safe_ds = request.args.get("ds") if request.args.get("ds") in DATASETS else "chemistry"
            error, q = str(exc), parse_question(MultiDict({"ds": safe_ds}))
        saved, saved_ok = [], False
        try:
            conn = ro_conn()
        except Exception:
            return render_template("ask.html", error="The database is not reachable right now.", q=q, **_page_context(q)), 503
        try:
            with conn.cursor() as cur:
                saved, saved_ok = saved_questions(cur)
                if asked and not error:
                    try:
                        sql, params, cols = build_sql(q)
                        csql, cparams = count_sql(q)
                        cur.execute(csql, cparams)
                        total = cur.fetchone()[0]
                        cur.execute(sql, params)
                        names = [d[0] for d in cur.description]
                        rows = [dict(zip(names, r)) for r in cur.fetchall()]
                        sql_text = cur.mogrify(sql, params).decode("utf-8", "replace")
                        chart = chart_spec(q, cols, rows)
                    except QuestionError as exc:
                        error = str(exc)
                    except Exception as exc:  # e.g. statement timeout
                        error = "That question took too long or couldn't run. Try adding filters (a site or date range)."
                        app.logger.warning("ask_data query failed: %s", exc)
        finally:
            conn.close()
        args = question_args(q)
        pages = max(1, -(-total // ROW_PAGE)) if q["mode"] == "rows" else 1
        return render_template(
            "ask.html", error=error, q=q, asked=asked, rows=rows, cols=cols, total=total, sql_text=sql_text,
            chart=chart, saved=saved, saved_ok=saved_ok, csrf=csrf_token(), fmt=fmt, pages=pages,
            query_string=to_query_string(args),
            csv_url=url_for("data_ask_csv") + "?" + to_query_string(args),
            sort_url=lambda key: url_for("data_ask_page") + "?" + to_query_string(question_args(
                q, sort=key, dir=("asc" if (q["sort"] == key and q["desc"]) else "desc") if q["sort"] == key else ("desc" if key in ("date", "year", "month") or key.startswith(("count__", "avg__", "max__", "median__", "sum__")) else "asc"), page=None)),
            page_url=lambda p: url_for("data_ask_page") + "?" + to_query_string(question_args(q, page=p)),
            **_page_context(q),
        )

    def _page_context(q):
        return dict(datasets=DATASETS, ops=OPS, aggs=AGGS,
                    fields_json={k: {f: dict(label=v["label"], type=v["type"], group=v["group"], unit=v["unit"], choices=v["choices"])
                                     for f, v in ds["fields"].items()} for k, ds in DATASETS.items()},
                    defaults_json={k: ds["default_columns"] for k, ds in DATASETS.items()})

    @app.route("/data/ask.csv")
    def data_ask_csv():
        try:
            q = parse_question(request.args)
        except QuestionError as exc:
            abort(400, str(exc))
        conn = ro_conn()
        try:
            with conn.cursor() as cur:
                sql, params, cols = build_sql(q, for_csv=True)
                cur.execute(sql, params)
                rows = cur.fetchall()
        finally:
            conn.close()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([f"{c[1]} ({c[2]})" if c[2] else c[1] for c in cols])
        for r in rows:
            w.writerow([fmt(v) for v in r])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="streamwatch_{q["ds"]}_question.csv"'})

    @app.route("/data/ask/choices")
    def data_ask_choices():
        ds_key, fkey = request.args.get("ds"), request.args.get("field")
        if ds_key not in DATASETS or fkey not in DATASETS[ds_key]["fields"] or not DATASETS[ds_key]["fields"][fkey]["choices"]:
            return jsonify([])
        fd = DATASETS[ds_key]["fields"][fkey]
        conn = ro_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT DISTINCT ({fd['sql']})::text AS x FROM {DATASETS[ds_key]['from_sql']} WHERE ({fd['sql']}) IS NOT NULL ORDER BY 1 LIMIT 500")
                return jsonify([r[0] for r in cur.fetchall()])
        finally:
            conn.close()

    @app.route("/data/ask/save", methods=["POST"])
    def data_ask_save():
        check_csrf()
        name = (request.form.get("name") or "").strip()[:120]
        description = (request.form.get("description") or "").strip()[:500] or None
        query = (request.form.get("query") or "").strip()[:4000]
        if not name or not query:
            return redirect(url_for("data_ask_page") + "?" + query)
        from urllib.parse import parse_qsl
        try:
            parse_question(MultiDict(parse_qsl(query, keep_blank_values=True)))  # only save valid questions
        except QuestionError:
            abort(400, "That question isn't valid, so it wasn't saved.")
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO saved_question (name, description, query) VALUES (%s, %s, %s)", (name, description, query))
            conn.commit()
        finally:
            conn.close()
        return redirect(url_for("data_ask_page") + "?" + query + "&saved=1")

    @app.route("/data/ask/saved/<int:question_id>/delete", methods=["POST"])
    def data_ask_delete(question_id):
        check_csrf()
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM saved_question WHERE question_id = %s AND NOT is_starter", (question_id,))
            conn.commit()
        finally:
            conn.close()
        return redirect(url_for("data_ask_page"))
