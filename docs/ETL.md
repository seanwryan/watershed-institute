# StreamWatch Data Processing Guide

This guide explains what happens to Watershed's source data before it appears in the StreamWatch database and website.

## 1. The Basic Process

StreamWatch uses ETL: **Extract → Transform → Load**.

**Source files → Read the data → Clean and match records → Organize into related records → Load into StreamWatch**

The database is therefore **not an exact copy of the spreadsheets**. The original values are generally preserved, but the data is reorganized so sites, sampling visits, measurements, volunteers, equipment, and other information can be connected.

For example, one row in `All StreamWatch Data.xlsx` may contain:

`Site + Date + Method + Chemistry + E. coli + Data Condition`

StreamWatch can separate that into:

- a **Site**
- a **Visit** at that site and date
- a **Chemistry** record attached to the visit
- a **Bacteria** record if an E. coli result is present
- a **Data Condition** attached to the chemistry record

This allows one sampling visit to contain multiple related types of information without repeating all of the site and visit information.

---

## 2. How Different Data Is Processed

| Source data | What happens | Where it ends up |
|---|---|---|
| **Sites** | Site codes and information are standardized and matched. | Sites |
| **All StreamWatch Data** | Site and date are matched to a visit. Chemistry measurements are grouped together. Exact duplicate chemistry records are skipped. | Visits + Chemistry |
| **E. coli** | E. coli results are separated from chemistry and connected to the same sampling visit. | Bacteria |
| **BACT Survey123 / IDEXX** | Survey123 can fill missing chemistry values without replacing existing ones. IDEXX results are matched using sample codes. | Chemistry + Bacteria |
| **BAT / macroinvertebrates** | Bug types and counts are organized by visit. Biological indices are then calculated from those observations. | Bug records + Biological analysis |
| **Volunteers** | People are separated from their training history and site assignments, then linked together. | Volunteers + Training + Assignments |
| **Equipment** | Meters are identified and connected to testing and usage records. | Equipment + Meter testing |
| **Habitat** | Site habitat type is loaded, but historical habitat assessments are not currently bulk-loaded. | Sites; limited habitat data |

Some tools only **preview or export** data. They do not automatically change the database.

---

## 3. What Can Change During Processing?

### Values and formatting

StreamWatch recognizes different versions of column names and converts dates and numbers into formats the database can use.

Most measurement values are stored as supplied, with a few important notes:

- **Chloride:** Watershed already corrected the affected historical values in the final source workbook by dividing them by 10. StreamWatch stores those corrected values as supplied and does **not** divide them again.
- **Nitrate:** The source workbook labels nitrate as mg/L. StreamWatch currently stores the value as supplied, although the internal database field has an older `ug/L` name. No unit conversion is currently performed.
- **Methods:** Current method names such as `CAT: Hanna`, `CAT: LaMotte`, `CAT: Early LaMotte`, `BACT`, `BAT`, and `Salt Watch` are retained.

### Matching

Many records must be matched before they can be loaded.

For example:

**Site ABM4 + July 12, 2025 → ABM4 visit on July 12 → chemistry/bacteria results**

If StreamWatch cannot confidently identify something such as a site, it does not invent a match. The affected record may be skipped or left for review.

### Duplicates

For chemistry, StreamWatch compares the site, date, method, and measurement values.

- An **exact duplicate chemistry package** is skipped.
- Different legitimate measurements from the same site and date are retained.

This means multiple chemistry records can correctly belong to the same sampling visit.

### Data Conditions

Recognized individual Data Conditions such as `Outlier`, `Flagged`, `Provisional`, `Duplicate`, and `Duplicate?` can be connected to chemistry records.

If the source contains a compound condition containing multiple tags, StreamWatch currently leaves it unresolved rather than choosing one automatically.

---

## 4. Calculated Information and QA Flags

Not everything in StreamWatch comes directly from a spreadsheet cell.

### Biological analysis

BAT bug observations are loaded first. StreamWatch then calculates biological indices and stores the resulting analysis separately.

### Automatic QA flags

After data has been loaded, StreamWatch can apply additional QA rules.

The current automated rules include:

| Check | Current automatic action |
|---|---|
| Water temperature above 31 °C | Flag result |
| Nitrate above the currently coded threshold | Flag result |
| Certain meter-failure situations | Flag associated results when the required equipment/testing information is available |

These are **software-generated flags**, separate from Data Conditions already present in Watershed's source data.

The current automatic QA system does **not** represent every Watershed analysis rule. For example, Watershed's guidance to exclude values ending in `?` and `CAT: Early LaMotte` turbidity is documented for analysis but is not automatically converted into QA flags by the ETL.

Because these rules affect which records receive attention, the QA rules should be reviewed with Watershed before being treated as a complete automated quality-control system.

---

## 5. Important Things to Know

- StreamWatch reorganizes the source data; it does not simply copy spreadsheets into PostgreSQL.
- One source row may create or connect to several related database records.
- Exact chemistry duplicates are skipped, but legitimate repeated measurements are retained.
- Unknown or ambiguous matches are generally left unresolved rather than guessed.
- Compound Data Conditions are currently unresolved.
- Chloride values in the current source are already corrected and are not corrected again during loading.
- Nitrate values are currently stored as supplied; the internal field name does not accurately describe the source unit.
- Historical habitat assessments are not currently bulk-loaded.
- Some information, especially biological analyses and QA flags, is calculated after the original data is loaded.