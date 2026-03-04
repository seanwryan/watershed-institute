#!/usr/bin/env python3
"""
Compute biological indices (HGMI, NJIS, CPMI) from bug_count/rbp100_bug + bug_list per BugCountsInfo.
Uses 100-organism subsample (rbp100_bug) when available; otherwise bug_count. Area correction uses site.drainage_area_sq_km.
Writes to macro_analysis. Run after BAT data migration.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.db import get_conn


# Simplified scaling bounds (align with BugCountsInfo formulas in production)
HGMI_GENUS_MAX = 31
HGMI_HBI_RANGE = (2.6, 7.2)
NJIS_LOWER_BETTER = True


def run():
    with get_conn() as conn:
        cur = conn.cursor()
        # Visits with RBP100 or bug counts
        cur.execute("""
            SELECT DISTINCT v.visit_id, v.site_id, s.drainage_area_sq_km
            FROM visit v
            JOIN site s ON s.site_id = v.site_id
            WHERE EXISTS (SELECT 1 FROM rbp100_bug r WHERE r.visit_id = v.visit_id)
               OR EXISTS (SELECT 1 FROM bug_count bc WHERE bc.visit_id = v.visit_id AND bc.exclude = false)
            """)
        visits = cur.fetchall()

        for (visit_id, site_id, drainage_area_sq_km) in visits:
            # Prefer rbp100_bug; else bug_count (exclude flagged)
            cur.execute("""
                SELECT COALESCE(
                    (SELECT SUM(amount) FROM rbp100_bug WHERE visit_id = %s), 0
                ) + (SELECT 0)
                """, (visit_id,))
            rbp_total = cur.fetchone()[0]
            use_rbp = rbp_total and rbp_total >= 50

            if use_rbp:
                cur.execute("""
                    SELECT b.bug_id, b.family, b.genus_species, b.ept, b.tolerance_ftv, b.scraper, b.order_class, r.amount
                    FROM rbp100_bug r
                    JOIN bug_list b ON b.bug_id = r.bug_id
                    WHERE r.visit_id = %s
                    """, (visit_id,))
            else:
                cur.execute("""
                    SELECT b.bug_id, b.family, b.genus_species, b.ept, b.tolerance_ftv, b.scraper, b.order_class, bc.amount
                    FROM bug_count bc
                    JOIN bug_list b ON b.bug_id = bc.bug_id
                    WHERE bc.visit_id = %s AND bc.exclude = false
                    """, (visit_id,))
            rows = cur.fetchall()
            if not rows:
                continue

            total_organisms = sum(r[7] for r in rows)
            if total_organisms == 0:
                continue

            # Genus-level: use genus_species or family as proxy
            genera = set()
            families = set()
            ept_count = 0
            insect_count = 0
            scraper_count = 0
            tolerance_sum = 0
            tolerance_n = 0
            for (bug_id, family, genus_species, ept, tol_ftv, scraper, order_class, amount) in rows:
                key = (family, genus_species) if genus_species else (family,)
                genera.add(key)
                families.add(family)
                if ept:
                    ept_count += amount
                if order_class and "Insect" in str(order_class):
                    insect_count += amount
                if scraper:
                    scraper_count += amount
                if tol_ftv is not None and amount:
                    tolerance_sum += float(tol_ftv) * amount
                    tolerance_n += amount

            total_taxa = len(genera)
            num_families = len(families)
            pct_ept = (100.0 * ept_count / total_organisms) if total_organisms else 0
            pct_insect = (100.0 * insect_count / total_organisms) if total_organisms else 0
            pct_not_insect = 100 - pct_insect
            hbi = (tolerance_sum / tolerance_n) if tolerance_n else None
            fbi = hbi  # approximate

            # Area adjustment: log(area_sq_km); cap for safety
            area_adj = 1.0
            if drainage_area_sq_km and drainage_area_sq_km > 0:
                area_adj = max(0.1, min(2.0, math.log1p(float(drainage_area_sq_km))))

            total_genera_adj = total_taxa * area_adj if area_adj else total_taxa
            pct_sensitive_ept_adj = pct_ept * area_adj if area_adj else pct_ept
            hbi_adj = (hbi / area_adj) if hbi and area_adj else hbi
            scraper_adj = scraper_count * area_adj if area_adj else scraper_count

            # Standardize to 0-100 (simplified; match BugCountsInfo formulas in production)
            def scale_0_100(val, max_val):
                if val is None or max_val is None or max_val == 0:
                    return 50
                return min(100, 100 * float(val) / max_val)

            def scale_inverse_0_100(val, low, high):
                if val is None or high is None or high == low:
                    return 50
                return min(100, max(0, 100 * (high - float(val)) / (high - low)))

            s1 = scale_0_100(total_genera_adj, HGMI_GENUS_MAX)
            s2 = scale_0_100(100 - pct_not_insect, 100)
            s3 = scale_0_100(pct_sensitive_ept_adj, 100)
            s4 = scale_inverse_0_100(hbi_adj, HGMI_HBI_RANGE[0], HGMI_HBI_RANGE[1]) if hbi_adj else 50
            s5 = scale_0_100(scraper_adj, 20)
            hgmi_genus = (s1 + s2 + s3 + s4 + s5) / 5.0

            s_fam1 = scale_0_100(num_families, 25)
            s_fam2 = scale_0_100(100 - pct_not_insect, 100)
            s_fam3 = scale_0_100(pct_sensitive_ept_adj, 100)
            s_fam4 = scale_inverse_0_100(hbi_adj, 2, 8) if hbi_adj else 50
            s_fam5 = scale_0_100(scraper_adj, 20)
            hgmi_family = (s_fam1 + s_fam2 + s_fam3 + s_fam4 + s_fam5) / 5.0

            # NJIS: lower tolerance = better; scale so lower HBI = higher score
            njis_score = (10 - hbi) * 10 if hbi is not None else None
            if njis_score is not None:
                njis_score = max(0, min(100, njis_score))
            njis_rating = None
            if njis_score is not None:
                if njis_score >= 70:
                    njis_rating = "Good"
                elif njis_score >= 40:
                    njis_rating = "Fair"
                else:
                    njis_rating = "Poor"

            hgmi_rating = None
            if hgmi_genus is not None:
                if hgmi_genus >= 70:
                    hgmi_rating = "Excellent"
                elif hgmi_genus >= 50:
                    hgmi_rating = "Good"
                elif hgmi_genus >= 30:
                    hgmi_rating = "Fair"
                else:
                    hgmi_rating = "Poor"

            # Dominant taxon (highest count)
            cur.execute("""
                SELECT b.family, b.genus_species, SUM(r.amount)
                FROM rbp100_bug r JOIN bug_list b ON b.bug_id = r.bug_id WHERE r.visit_id = %s
                GROUP BY b.family, b.genus_species ORDER BY SUM(r.amount) DESC LIMIT 1
                """, (visit_id,))
            dom = cur.fetchone()
            if not dom and not use_rbp:
                cur.execute("""
                    SELECT b.family, b.genus_species, SUM(bc.amount)
                    FROM bug_count bc JOIN bug_list b ON b.bug_id = bc.bug_id WHERE bc.visit_id = %s AND bc.exclude = false
                    GROUP BY b.family, b.genus_species ORDER BY SUM(bc.amount) DESC LIMIT 1
                    """, (visit_id,))
                dom = cur.fetchone()
            dominant_taxon = f"{dom[1] or dom[0]}" if dom else None
            pct_dominance = (100.0 * dom[2] / total_organisms) if dom and total_organisms else None

            cur.execute("""
                INSERT INTO macro_analysis (visit_id, total_organisms, total_taxa, ept_taxa, pct_ept, pct_dominance, dominant_taxon,
                    fbi, hbi, njis_score, njis_rating, hgmi_genus, hgmi_family, hgmi_rating, index_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'HGMI')
                ON CONFLICT (visit_id) DO UPDATE SET
                    total_organisms = EXCLUDED.total_organisms, total_taxa = EXCLUDED.total_taxa, ept_taxa = EXCLUDED.ept_taxa,
                    pct_ept = EXCLUDED.pct_ept, pct_dominance = EXCLUDED.pct_dominance, dominant_taxon = EXCLUDED.dominant_taxon,
                    fbi = EXCLUDED.fbi, hbi = EXCLUDED.hbi, njis_score = EXCLUDED.njis_score, njis_rating = EXCLUDED.njis_rating,
                    hgmi_genus = EXCLUDED.hgmi_genus, hgmi_family = EXCLUDED.hgmi_family, hgmi_rating = EXCLUDED.hgmi_rating
                """, (visit_id, total_organisms, total_taxa, len([r for r in rows if r[3]]), pct_ept, pct_dominance, dominant_taxon,
                      fbi, hbi, njis_score, njis_rating, round(hgmi_genus, 2), round(hgmi_family, 2), hgmi_rating))
        conn.commit()
    print("Biological indices computed.")


if __name__ == "__main__":
    run()
