#!/usr/bin/env python3
"""
Apply QA rules: set data_condition_id or result_flag based on:
- Meter failure within temporal window (link meter_testing to visit/chemical)
- Exceedance thresholds (water temp > 31 C, nitrate > 10 ppm)
Uses data_condition and flag_type lookups. Run after data load.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.db import get_conn


def run():
    with get_conn() as conn:
        cur = conn.cursor()
        # Resolve condition/flag IDs
        cur.execute("SELECT data_condition_id FROM data_condition WHERE code = 'Flagged' LIMIT 1")
        flagged_dc = cur.fetchone()
        flagged_dc = flagged_dc[0] if flagged_dc else None
        cur.execute("SELECT flag_type_id FROM flag_type WHERE code = 'Exceedance' LIMIT 1")
        exceedance_ft = cur.fetchone()
        exceedance_ft = exceedance_ft[0] if exceedance_ft else None
        cur.execute("SELECT flag_type_id FROM flag_type WHERE code = 'Meter_Failed_Test' LIMIT 1")
        meter_fail_ft = cur.fetchone()
        meter_fail_ft = meter_fail_ft[0] if meter_fail_ft else None

        # 1) Flag chemical rows where water_temp_c > 31 or nitrate > 10 ppm (nitrate_ug_l > 10000)
        if exceedance_ft:
            cur.execute("""
                UPDATE chemical SET data_condition_id = %s
                WHERE (water_temp_c IS NOT NULL AND water_temp_c > 31) OR (nitrate_ug_l IS NOT NULL AND nitrate_ug_l > 10000)
                AND (data_condition_id IS NULL OR data_condition_id NOT IN (SELECT data_condition_id FROM data_condition WHERE code = 'Flagged'))
                """, (flagged_dc,))
            cur.execute("""
                INSERT INTO result_flag (result_table, result_pk, flag_type_id, notes)
                SELECT 'chemical', chemical_id, %s, 'Water temp > 31 C or nitrate > 10 ppm'
                FROM chemical
                WHERE (water_temp_c IS NOT NULL AND water_temp_c > 31) OR (nitrate_ug_l IS NOT NULL AND nitrate_ug_l > 10000)
                AND NOT EXISTS (SELECT 1 FROM result_flag rf WHERE rf.result_table = 'chemical' AND rf.result_pk = chemical.chemical_id AND rf.flag_type_id = %s)
                """, (exceedance_ft, exceedance_ft))

        # 2) Flag chemical rows where visit used equipment that failed test within 30 days after sample
        if meter_fail_ft and flagged_dc:
            cur.execute("""
                INSERT INTO result_flag (result_table, result_pk, flag_type_id, notes)
                SELECT DISTINCT 'chemical', c.chemical_id, %s, 'Meter failed test within 30 days of sample'
                FROM chemical c
                JOIN visit v ON v.visit_id = c.visit_id
                JOIN meter_testing mt ON mt.equipment_id = v.equipment_id AND mt.pass_fail IN ('F', 'F1', 'F2', 'F3', 'Fail', 'C-F')
                JOIN session s ON s.session_id = mt.session_id
                WHERE v.equipment_id IS NOT NULL
                  AND s.date_start <= v.sample_date + INTERVAL '30 days'
                  AND (s.date_end IS NULL OR s.date_end >= v.sample_date - INTERVAL '7 days')
                  AND NOT EXISTS (SELECT 1 FROM result_flag rf WHERE rf.result_table = 'chemical' AND rf.result_pk = c.chemical_id AND rf.flag_type_id = %s)
                """, (meter_fail_ft, meter_fail_ft))
            cur.execute("""
                UPDATE chemical c SET data_condition_id = %s
                FROM visit v, meter_testing mt, session s
                WHERE c.visit_id = v.visit_id AND v.equipment_id = mt.equipment_id AND mt.session_id = s.session_id
                  AND mt.pass_fail IN ('F', 'F1', 'F2', 'F3', 'Fail', 'C-F')
                  AND s.date_start <= v.sample_date + INTERVAL '30 days'
                  AND (s.date_end IS NULL OR s.date_end >= v.sample_date - INTERVAL '7 days')
                  AND (c.data_condition_id IS NULL OR c.data_condition_id NOT IN (SELECT data_condition_id FROM data_condition WHERE code = 'Flagged'))
                """, (flagged_dc,))

    print("QA rules applied.")


if __name__ == "__main__":
    run()
