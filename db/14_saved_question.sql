-- Saved questions for the "Ask the data" query builder (dashboard/ask_data.py).
-- A question is stored as the builder's URL query string, e.g.
--   ds=chemistry&mode=rows&f=chloride&o=gt&v=100
-- Starter questions are seeded below and can't be deleted from the app.
-- Additive and safe to re-run.

CREATE TABLE IF NOT EXISTS saved_question (
  question_id  SERIAL PRIMARY KEY,
  name         TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
  description  TEXT,
  query        TEXT NOT NULL CHECK (length(query) <= 4000),
  is_starter   BOOLEAN NOT NULL DEFAULT false,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_saved_question_starter_name
  ON saved_question (name) WHERE is_starter;

INSERT INTO saved_question (name, description, query, is_starter)
SELECT v.name, v.description, v.query, true
FROM (VALUES
  ('Chloride readings above 100 mg/L',
   'Readings over the 2026 Assessment Framework''s Excellent limit for chloride.',
   'ds=chemistry&mode=rows&f=chloride&o=gt&v=100&v2=&sort=chloride&dir=desc'),
  ('Average chloride per year',
   'Average, median and number of chloride readings each year, all sites.',
   'ds=chemistry&mode=summary&f=chloride&o=notempty&v=&v2=&group=year&m=avg:chloride&m=median:chloride&m=count:chloride'),
  ('Nitrate above 10 mg/L',
   'Readings over the 10 mg/L (as N) drinking-water standard.',
   'ds=chemistry&mode=rows&f=nitrate&o=gt&v=10&v2=&sort=nitrate&dir=desc'),
  ('E. coli above 320 MPN/100 mL',
   'BACT results over the single-sample level used in the 2026 Assessment Framework.',
   'ds=ecoli&mode=rows&f=e_coli&o=gt&v=320&v2=&sort=e_coli&dir=desc'),
  ('NJIS ratings by year',
   'How many BAT samples were rated Excellent, Good, Fair or Poor each year.',
   'ds=bug_scores&mode=summary&f=njis_rating&o=notempty&v=&v2=&group=year&group=njis_rating&m=count:*'),
  ('Visits per year by program',
   'Number of sampling visits each year for CAT, BACT, BAT and Salt Watch.',
   'ds=visits&mode=summary&group=year&group=visit_method&m=count:*'),
  ('Active sites not sampled since 2023',
   'Active sites whose latest sample is before 2023.',
   'ds=sites&mode=rows&f=site_active&o=true&v=&v2=&f=last_sample&o=before&v=2023-01-01&v2=&sort=last_sample'),
  ('Failed meter tests',
   'Meter checks recorded as a fail.',
   'ds=meter_tests&mode=rows&f=result&o=is&v=Fail&v2=&sort=date&dir=desc')
) AS v(name, description, query)
WHERE NOT EXISTS (SELECT 1 FROM saved_question s WHERE s.is_starter AND s.name = v.name);
