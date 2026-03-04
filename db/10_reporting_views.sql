-- Operational reporting views (Database Structure Plan)

-- Site summary: site + waterbody + last visit + sample counts
CREATE OR REPLACE VIEW v_site_summary AS
SELECT s.site_id, s.site_code, w.name AS waterbody_name, s.description, s.latitude, s.longitude,
       s.drainage_area_sq_km, s.cat_priority_id, s.bat_priority_id, s.bact_priority_id,
       (SELECT MAX(v.sample_date) FROM visit v WHERE v.site_id = s.site_id) AS last_sample_date,
       (SELECT COUNT(*) FROM visit v WHERE v.site_id = s.site_id) AS visit_count
FROM site s
LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
WHERE s.is_active = true;

-- Volunteer activity: volunteer + assignment count + last training
CREATE OR REPLACE VIEW v_volunteer_activity AS
SELECT vol.volunteer_id, vol.first_name, vol.last_name, vol.email, vol.active_cat, vol.active_bat, vol.active_bact, vol.status,
       (SELECT COUNT(*) FROM junc_assignments a WHERE a.volunteer_id = vol.volunteer_id) AS assignment_count,
       (SELECT MAX(tl.expiration_date) FROM training_log tl WHERE tl.volunteer_id = vol.volunteer_id) AS latest_training_expiration
FROM volunteer vol;

-- Visit summary: visit + site + sample code + has chemical/bacteria
CREATE OR REPLACE VIEW v_visit_summary AS
SELECT v.visit_id, v.sample_date, v.sample_time, v.sample_code, s.site_code, s.site_id, w.name AS waterbody_name,
       (SELECT COUNT(*) FROM chemical c WHERE c.visit_id = v.visit_id) AS chemical_count,
       (SELECT COUNT(*) FROM bacteria b WHERE b.visit_id = v.visit_id) AS bacteria_count
FROM visit v
JOIN site s ON s.site_id = v.site_id
LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id;

-- Chemical results (flat for export/reports)
CREATE OR REPLACE VIEW v_chemical_results AS
SELECT c.chemical_id, v.visit_id, v.sample_date, v.sample_code, s.site_code, w.name AS waterbody_name,
       dc.code AS data_condition_code, c.water_temp_c, c.air_temp_c, c.nitrate_ug_l, c.phosphate_mg_l,
       c.ph, c.turbidity_ntu, c.dissolved_oxygen_ppm, c.conductivity_us_cm, c.chloride_mg_l
FROM chemical c
JOIN visit v ON v.visit_id = c.visit_id
JOIN site s ON s.site_id = v.site_id
LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id
LEFT JOIN data_condition dc ON dc.data_condition_id = c.data_condition_id;

-- Bacteria results
CREATE OR REPLACE VIEW v_bacteria_results AS
SELECT b.bacteria_id, v.visit_id, v.sample_date, v.sample_code, s.site_code, w.name AS waterbody_name,
       b.e_coli_mpn_100ml, b.total_coliform_mpn, b.holding_time_flag, b.holding_temp_flag
FROM bacteria b
JOIN visit v ON v.visit_id = b.visit_id
JOIN site s ON s.site_id = v.site_id
LEFT JOIN waterbody w ON w.waterbody_id = s.waterbody_id;

-- Equipment inventory with last test
CREATE OR REPLACE VIEW v_equipment_inventory AS
SELECT e.equipment_id, e.equipment_code, e.equipment_type, e.serial_number, e.status,
       (SELECT MAX(s.date_start) FROM meter_testing mt JOIN session s ON s.session_id = mt.session_id WHERE mt.equipment_id = e.equipment_id) AS last_test_date
FROM equipment e;

-- Training compliance: volunteers with expiring or expired training
CREATE OR REPLACE VIEW v_training_compliance AS
SELECT vol.volunteer_id, vol.first_name, vol.last_name, tl.expiration_date,
       CASE WHEN tl.expiration_date < CURRENT_DATE THEN 'Expired' WHEN tl.expiration_date < CURRENT_DATE + INTERVAL '90 days' THEN 'Expiring soon' ELSE 'Current' END AS status
FROM volunteer vol
JOIN training_log tl ON tl.volunteer_id = vol.volunteer_id
WHERE vol.status = 'Active'
ORDER BY tl.expiration_date;
