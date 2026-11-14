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
-- 13 adds columns that the 09/10 views read, so it runs before them
\ir 13_source_data_condition.sql
\ir 08_data_governance_seed.sql
\ir 09_qa_views.sql
\ir 10_reporting_views.sql
\ir 11_method_reference.sql

\ir 12_source_intake.sql
