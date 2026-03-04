-- Run all schema and seed scripts in order.
-- Usage: psql -f run_schema.sql <connection_string>
-- Or: psql $DATABASE_URL -f run_schema.sql

\ir 01_lookups.sql
\ir 02_site.sql
\ir 03_volunteer.sql
\ir 04_equipment.sql
\ir 05_visit.sql
\ir 06_results.sql
\ir 07_junctions.sql
\ir 08_data_governance_seed.sql
\ir 09_qa_views.sql
\ir 10_reporting_views.sql
