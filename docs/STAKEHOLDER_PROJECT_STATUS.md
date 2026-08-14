# StreamWatch Database Project — Project Status

## Overview

The StreamWatch database project began with the goal of moving Watershed's existing monitoring data and workflows from Microsoft Access and separate spreadsheets into a more centralized PostgreSQL database.

Based on the database structure plan, existing Access database, historical spreadsheets, and workflow documentation provided by Watershed, the project has expanded beyond the initial database migration into a working staff-facing prototype.

The current system brings together monitoring sites, visits, water-quality results, biological monitoring, volunteers, equipment, quality review, reporting, and data-entry workflows in one application.

The goal of the current prototype is to demonstrate how these pieces can work together while preserving Watershed's existing data and leaving program-specific decisions to staff where the supplied documentation does not provide enough information to automate them safely.

---

## What Is Working Today

### Sites and Monitoring Visits

Staff can browse and search StreamWatch sites, view them on a map, and open individual site profiles containing site information and recent monitoring activity.

Sites can be added and edited.

Monitoring visits can also be created and edited. Each Visit acts as a workspace connecting the different types of monitoring data collected during that sampling event.

From a Visit, staff can review or enter chemistry, bacteria, habitat, and macroinvertebrate information.

### Chemistry and Bacteria

Chemistry results can be added and edited directly from a monitoring Visit.

The system supports multiple chemistry result packages for the same Visit when multiple sets of measurements exist.

Bacteria results can also be entered and edited, including E. coli, total coliform, data-condition information, holding flags, and notes.

Basic validation and duplicate protection are included.

### Habitat Assessments

High Gradient and Low Gradient habitat assessment **entry** is implemented. Staff can record assessments from a Visit for sites with those habitat types.

The form automatically presents the appropriate gradient-specific metrics along with the shared habitat measurements.

Component scores are totaled for review, but habitat ratings are not automatically assigned because the supplied materials do not fully document the rating thresholds.

Lake, Canal, and unclassified sites remain intentionally blocked until the appropriate assessment procedure is confirmed.

Historical habitat assessments have **not** been bulk migrated. The current demo baseline therefore has **0** habitat assessment records before any staff-entered data. Loading historical habitat depends on confirming the appropriate Watershed source or field form and how it should be interpreted.

### Macroinvertebrate Monitoring

Macroinvertebrate observations can be managed from the Visit workspace.

Staff can add taxa from the existing StreamWatch taxonomy, record and edit counts, remove individual observations, and review calculated biological indices.

Existing BAT and RBP100 historical information is preserved.

### Volunteers and Training

The volunteer area now supports:

- Volunteer profiles
- Adding and editing volunteers
- Site and role assignments
- Active and ended assignments
- Training sessions
- Volunteer training attendance
- Training status and expiration information

This provides the foundation for the Volunteer-related workflows described in the original database plan.

### Equipment and Meter Testing

Equipment records and historical meter-testing information are available through equipment profiles.

Staff can review meter history and enter new meter-test records.

The system does not yet automatically determine how field data should be affected by a failed meter test because that policy still requires program guidance.

---

## Data Review and Analysis

### Explore

Monitoring results can be explored by site, parameter, and date range using charts and filters.

This provides a quicker way to inspect historical trends without working directly from spreadsheets or database queries.

### Quality Review

A QA workspace surfaces existing stored result flags and provides context for reviewing questionable results.

Limited warnings are also available during chemistry entry.

The current QA tools are intended to assist staff review rather than replace Watershed's scientific quality-control procedures.

### Biological Scores

Calculated biological indices can be reviewed through the Scores area and are connected back to the underlying monitoring data.

---

## Reports and Exports

A Reports area provides staff-readable views of information currently stored in PostgreSQL.

Available reports include:

- Site Summary
- Visit History
- Data Completeness
- Training Compliance
- Assignment Coverage
- Monitoring Results
- BACT seasonal reporting

Applicable reports can also be exported to CSV.

A WQX-style export workflow has been implemented for monitoring results. It preserves multiple legitimate chemistry packages associated with the same Visit.

The export is intended to help prepare WQX-compatible data; it is not presented as a direct EPA submission system.

---

## BACT Workflows

The project includes tools for reviewing the annual BACT data workflow without automatically modifying the database.

### BACT Import Review

A BACT workbook can be uploaded for reconciliation against the existing database.

The preview identifies records that are already present, records needing review, unmatched samples, censored results, and invalid records.

For unmatched IDEXX samples, the application can also show existing visits on the same or nearby dates to help staff investigate the discrepancy.

No database changes occur during this review.

### Seasonal BACT Reporting

The scoring logic from the supplied 2025 BACT Analysis workbook has been reproduced in a read-only reporting workflow.

The application uses the weekly values already selected in the Watershed workbook rather than assuming that an arbitrary PostgreSQL chemistry record represents the official BACT result.

This allows the existing seasonal rating process to be reproduced while preserving Watershed's current source-selection decisions.

### HAB Review

The supplied HAB status logic has also been reproduced as a preview workflow.

Calculated conditions can be compared with the statuses stored in the workbook while preserving manually assigned Watch or Advisory decisions.

---

## Historical Data and Repeatability

Historical StreamWatch information has been migrated into the PostgreSQL structure, including sites, visits, chemistry, volunteers, training, assignments, equipment testing, and biological monitoring data.

For bacteria, the database includes the migrated historical and season IDEXX records used in the current demo. Other bacteria cases remain intentionally outside the loaded dataset pending Watershed decisions—for example censored IDEXX values and historical E. coli source-authority questions documented elsewhere. Those records are deferred, not discarded as invalid.

The migration process has also been made repeatable so that rebuilding a database from the supplied source files produces consistent results.

An operations runbook documents the migration sequence, database safety procedures, QA processing, biological calculations, exports, reporting, and troubleshooting.

---

## Areas That Still Need Watershed Input

Development has reached several areas where additional program knowledge would be more useful than making assumptions in the software.

### Chemistry and Gallery Data

We would like to confirm how Watershed wants results from different chemistry sources handled, particularly where multiple measurements exist for the same sample.

The Gallery workflow also contains cases where staff currently select between multiple test ranges, so the appropriate selection rules should be confirmed before automating that process.

### Bacteria

The existing BACT workbook documents how censored IDEXX results are treated for seasonal calculations, but the preferred way to store those results in the database still needs to be confirmed.

There are also historical samples that do not currently match an existing monitoring Visit and would benefit from staff review before any records are created or linked automatically.

### Equipment and QA

Additional guidance would be helpful for defining meter-testing pass/fail rules and determining what should happen to monitoring results when a meter fails testing or calibration.

### Habitat

High- and Low-Gradient habitat entry is available; historical habitat assessments have not been bulk loaded.

Additional guidance would help confirm official scoring/rating rules, determine how Canal and Lake sites should be handled, and identify the source or form to use for any future historical habitat migration.

Reviewing the habitat form currently used by staff would also help ensure the new workflow matches field practice.

### Other Integrations and Workflows

Future discussions can also determine the priority and expected behavior of:

- Visit volunteer attendance
- DonorPerfect volunteer synchronization
- ArcGIS Online data workflows
- WQX submission workflow
- User accounts and staff permissions
- Production hosting, ownership, and backup procedures

---

## Current Project State

The project has progressed from a database migration into a functional StreamWatch operations prototype.

The major data areas are connected through Sites and monitoring Visits, historical data can be searched and reviewed through the application, several important staff data-entry workflows are functional, and reporting/import-review tools have been added around recurring StreamWatch processes.

At this stage, many of the remaining questions are program and workflow decisions rather than fundamental database or application-development blockers.

The next step is to review the current system with Watershed staff, confirm that the implemented workflows match how the program operates in practice, and use that feedback to prioritize the remaining work.