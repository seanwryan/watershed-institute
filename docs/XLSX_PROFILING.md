# Workbook profiling

Run from the project root with Python 3.9 or newer and the `openpyxl` dependency in `requirements.txt`:

```bash
python etl/summarize_xlsx.py "/Users/seanryan/Downloads/Watershed Data"
```

The script recursively reads `.xlsx` files, skipping Excel lock files. It writes
`reports/xlsx_summary.json` (excluded from version control). Use `--output PATH`
to choose another location. Sources are opened read-only and never saved.
CSV, XLSM, PDF, R, and other files are outside this initial inventory.

The JSON lists each source's relative path, size, SHA-256 fingerprint, sheets
(including hidden sheets), observed rows and columns, assumed headers, missing
values, raw value types, distinct counts, numeric statistics, date/time ranges,
duplicate row candidates, duplicate headers, Excel errors, formulas without cached
results, and reader warnings. Read failures are recorded while other files continue;
the command exits with status 1 if any workbook or sheet failed.

The first nonempty row is provisionally treated as the header. Inspect this choice
before using the column statistics, especially for forms, title rows, multiple
tables, and notes. `--header-row N` overrides this for **all** sheets in the run;
use a separate run on a folder containing only matching layouts if necessary.
Blank rows do not count as observations; whitespace-only cells count as missing.
Zeros and false values remain populated. Duplicate counts exclude blank rows.
Error locations are capped at the first 100 per sheet, but counts cover all errors.

Formula cells count as populated, but formula expressions are excluded from raw
statistics and distinct counts. Formula counts include headers and other rows.
The script checks saved formula results for errors and absent caches, but does
not recalculate formulas or validate their logic. Numbers are not coerced from
text, and units, detection limits, identifiers, dates stored as numbers/text,
relationships, and domain rules require later validation against the data dictionary.
ISO date/time bounds are lexical and should only be interpreted as chronological
when the column contains a consistent temporal type.

This is a structural baseline, not certification of scientific validity. The
report does not include sample values or full rows, but headers, paths, statistics,
and error locations may still contain sensitive information; keep it local.
