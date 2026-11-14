"""
Data audit page (/qa/audit): evidence that the database faithfully reflects
Watershed's source files.

  1. Reconciliation  every source sheet vs the database (saved by etl/audit_sources.py,
                     which runs where the source files are)
  2. Live checks     integrity rules re-run against the database on every page load
  3. Change log      every transformation, its rule, date, rows and script
  4. Trace a record  any site + date: what each workbook row became

Read-only.
"""
from __future__ import annotations

from datetime import date

from flask import render_template, request

# Each live check counts problems; 0 means it passes. "known" problems are
# expected for a documented reason and show as "attention", not "fail".
LIVE_CHECKS = [
    dict(
        title="Every result is on the visit for its own program",
        why="CAT, BACT, BAT and Salt Watch sampling on the same day are separate visits.",
        sql="""SELECT (SELECT count(*) FROM chemical c JOIN visit v USING (visit_id) WHERE c.method_id IS DISTINCT FROM v.method_id)
                    + (SELECT count(*) FROM bacteria b JOIN visit v USING (visit_id) JOIN lst_method m ON m.method_id = v.method_id WHERE m.name <> 'BACT')""",
    ),
    dict(
        title="One visit per site, date and program",
        why="No duplicate visits.",
        sql="""SELECT count(*) FROM (SELECT 1 FROM visit GROUP BY site_id, sample_date, method_id HAVING count(*) > 1) d""",
    ),
    dict(
        title="Every visit holds data",
        why="No empty visits left behind by loads or fixes.",
        sql="""SELECT count(*) FROM visit v WHERE NOT EXISTS (SELECT 1 FROM chemical x WHERE x.visit_id = v.visit_id)
                 AND NOT EXISTS (SELECT 1 FROM bacteria x WHERE x.visit_id = v.visit_id)
                 AND NOT EXISTS (SELECT 1 FROM macro_analysis x WHERE x.visit_id = v.visit_id)
                 AND NOT EXISTS (SELECT 1 FROM habitat_assessment x WHERE x.visit_id = v.visit_id)
                 AND NOT EXISTS (SELECT 1 FROM bug_count x WHERE x.visit_id = v.visit_id)""",
    ),
    dict(
        title="Every result carries its Data Condition",
        why="Single codes or the workbook's combined wording.",
        sql="""SELECT (SELECT count(*) FROM chemical WHERE data_condition_id IS NULL AND source_data_condition IS NULL)
                    + (SELECT count(*) FROM bacteria WHERE data_condition_id IS NULL AND source_data_condition IS NULL)""",
    ),
    dict(
        title="Every BAT visit has bug-index scores",
        why="Scores 1996–2025 come from All StreamWatch Data.",
        sql="""SELECT count(*) FROM visit v JOIN lst_method m USING (method_id)
               WHERE m.name = 'BAT' AND NOT EXISTS (SELECT 1 FROM macro_analysis x WHERE x.visit_id = v.visit_id)""",
    ),
    dict(
        title="Bug-score ratings follow the 2026 Assessment Framework bands",
        why="Ratings are recomputed here from the scores and compared.",
        sql="""SELECT count(*) FROM macro_analysis WHERE
                 njis_rating IS DISTINCT FROM CASE WHEN njis_score IS NULL OR njis_score < 0 OR njis_score > 30 THEN NULL
                   WHEN njis_score >= 22.5 THEN 'Excellent' WHEN njis_score >= 15 THEN 'Good' WHEN njis_score >= 7.5 THEN 'Fair' ELSE 'Poor' END
              OR hgmi_rating IS DISTINCT FROM CASE WHEN COALESCE(hgmi_genus, hgmi_family) IS NULL OR COALESCE(hgmi_genus, hgmi_family) NOT BETWEEN 0 AND 100 THEN NULL
                   WHEN COALESCE(hgmi_genus, hgmi_family) >= 63 THEN 'Excellent' WHEN COALESCE(hgmi_genus, hgmi_family) >= 42 THEN 'Good'
                   WHEN COALESCE(hgmi_genus, hgmi_family) >= 21 THEN 'Fair' ELSE 'Poor' END
              OR cpmi_rating IS DISTINCT FROM CASE WHEN cpmi_score IS NULL OR cpmi_score < 0 OR cpmi_score > 30 THEN NULL
                   WHEN cpmi_score >= 22 THEN 'Excellent' WHEN cpmi_score BETWEEN 12 AND 20 THEN 'Good'
                   WHEN cpmi_score BETWEEN 6 AND 10 THEN 'Fair' WHEN cpmi_score < 6 THEN 'Poor' ELSE NULL END""",
    ),
    dict(
        title="Bug scores are within each index's scale",
        why="NJIS and CPMI 0–30, HGMI 0–100.",
        sql="""SELECT count(*) FROM macro_analysis WHERE njis_score NOT BETWEEN 0 AND 30 OR cpmi_score NOT BETWEEN 0 AND 30
                 OR hgmi_genus NOT BETWEEN 0 AND 100 OR hgmi_family NOT BETWEEN 0 AND 100""",
        known=3,
        known_note="BB1 2014-03-15, CB2 2015-07-19 and SM1 2015-07-23 hold older computed scores with no workbook value; awaiting Watershed.",
    ),
    dict(
        title="Every reading over a threshold is flagged",
        why="Water temperature over 31 °C or nitrate over 10 mg/L gets an Exceedance flag.",
        sql="""SELECT count(*) FROM chemical c WHERE (c.water_temp_c > 31 OR c.nitrate_ug_l > 10)
                 AND NOT EXISTS (SELECT 1 FROM result_flag rf JOIN flag_type ft USING (flag_type_id)
                                 WHERE rf.result_table = 'chemical' AND rf.result_pk = c.chemical_id AND ft.code = 'Exceedance')""",
    ),
    dict(
        title="Values are physically possible",
        why="pH 0–14, water temperature −5 to 45 °C, dissolved oxygen and conductivity not negative.",
        sql="""SELECT count(*) FROM chemical WHERE ph NOT BETWEEN 0 AND 14 OR water_temp_c NOT BETWEEN -5 AND 45
                 OR dissolved_oxygen_ppm < 0 OR dissolved_oxygen_pct < 0 OR conductivity_us_cm < 0""",
    ),
    dict(
        title="Nitrate values are not negative",
        why="Negative analyzer readings are usually below the detection limit.",
        sql="SELECT count(*) FROM chemical WHERE nitrate_ug_l < 0",
        known=61,
        known_note="61 negative nitrate readings (e.g. −0.0231 mg/L) are kept as recorded; how Watershed wants below-detection values stored is an open question.",
    ),
    dict(
        title="Every record comes from a source file",
        why="Rows typed into the app's forms instead of loaded from Watershed's files are listed in the reconciliation.",
        sql="""SELECT (SELECT count(*) FROM volunteer WHERE created_at::date NOT IN ('2026-09-10', '2026-11-14'))
                    + (SELECT count(*) FROM session WHERE created_at::date NOT IN ('2026-09-10', '2026-11-14'))
                    + (SELECT count(*) FROM meter_testing WHERE created_at::date NOT IN ('2026-09-10', '2026-11-14'))
                    + (SELECT count(*) FROM visit WHERE created_at::date NOT IN ('2026-09-10', '2026-11-14'))
                    + (SELECT count(*) FROM site WHERE created_at::date NOT IN ('2026-09-10', '2026-11-14'))""",
    ),
]


def run_live_checks(cur):
    out = []
    for chk in LIVE_CHECKS:
        cur.execute(chk["sql"])
        n = cur.fetchone()[0] or 0
        known = chk.get("known")
        if n == 0:
            status = "pass"
        elif known is not None and n <= known:
            status = "attention"
        else:
            status = "fail"
        out.append(dict(title=chk["title"], why=chk["why"], count=n, status=status,
                        note=chk.get("known_note") if status == "attention" else None))
    return out


def register(app, get_db):
    @app.route("/qa/audit")
    def data_audit_page():
        site = (request.args.get("site") or "").strip()[:20]
        day = (request.args.get("date") or "").strip()
        trace_error = None
        try:
            day_value = date.fromisoformat(day) if day else None
        except ValueError:
            day_value, trace_error = None, "Use a date like 2024-06-23."
        conn = get_db()
        try:
            conn.set_session(readonly=True, autocommit=True)
            cur = conn.cursor()
            cur.execute("SET statement_timeout = 15000")
            try:
                cur.execute("SELECT run_id, run_at, summary FROM audit_run ORDER BY run_id DESC LIMIT 1")
                run = cur.fetchone()
            except Exception:
                return render_template("data_audit.html", ready=False, live=run_live_checks(cur)), 200
            checks, changes = [], []
            if run:
                cur.execute("""SELECT source, sheet, item, source_count, db_count, status, explanation
                               FROM audit_check WHERE run_id = %s ORDER BY sort_order""", (run[0],))
                checks = [dict(zip(["source", "sheet", "item", "source_count", "db_count", "status", "explanation"], r)) for r in cur.fetchall()]
            cur.execute("SELECT applied_on, area, title, rule, rows_affected, script FROM audit_change_log ORDER BY applied_on, change_id")
            changes = [dict(zip(["applied_on", "area", "title", "rule", "rows", "script"], r)) for r in cur.fetchall()]
            live = run_live_checks(cur)
            trace_rows, trace_visits = [], []
            if site and day_value:
                cur.execute("""SELECT row_number, method, outcome, detail, visit_id, chemical_id, bacteria_id
                               FROM audit_source_row WHERE site_code = %s AND sample_date = %s ORDER BY row_number""", (site, day_value))
                trace_rows = [dict(zip(["row", "method", "outcome", "detail", "visit_id", "chemical_id", "bacteria_id"], r)) for r in cur.fetchall()]
                cur.execute("""SELECT v.visit_id, m.name,
                                      (SELECT count(*) FROM chemical x WHERE x.visit_id = v.visit_id),
                                      (SELECT count(*) FROM bacteria x WHERE x.visit_id = v.visit_id),
                                      EXISTS (SELECT 1 FROM macro_analysis x WHERE x.visit_id = v.visit_id),
                                      EXISTS (SELECT 1 FROM habitat_assessment x WHERE x.visit_id = v.visit_id)
                               FROM visit v JOIN site s USING (site_id) LEFT JOIN lst_method m ON m.method_id = v.method_id
                               WHERE s.site_code = %s AND v.sample_date = %s ORDER BY v.visit_id""", (site, day_value))
                trace_visits = [dict(zip(["visit_id", "method", "chem", "bact", "scores", "habitat"], r)) for r in cur.fetchall()]
            groups = []
            for c in checks:
                if not groups or groups[-1]["source"] != c["source"]:
                    groups.append(dict(source=c["source"], checks=[]))
                groups[-1]["checks"].append(c)
            counts = {s: sum(1 for c in checks if c["status"] == s) for s in ("match", "explained", "gap", "info")}
            return render_template(
                "data_audit.html", ready=bool(run), run=run, groups=groups, counts=counts, changes=changes, live=live,
                live_counts={s: sum(1 for l in live if l["status"] == s) for s in ("pass", "attention", "fail")},
                site=site, day=day, trace_rows=trace_rows, trace_visits=trace_visits, trace_error=trace_error,
                traced=bool(site and day_value),
            )
        finally:
            conn.close()
