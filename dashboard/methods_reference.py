"""Static reference data for the internal StreamWatch Methods page.

Grounded in Watershed Sep 9, 2026 sources:
  - StreamWatch Data Summary & Description
  - StreamWatch Data Dictionary

Does not invent missing method details. Ambiguous source wording is preserved.
"""

METHODS_SUBTITLE = (
    "Reference information for StreamWatch monitoring methods, instruments, "
    "detection ranges, and historical program changes from the Sep 9, 2026 "
    "Watershed Data Summary and Data Dictionary."
)

CHLORIDE_NOTE = (
    "In 2026, Watershed documented a chloride standard-preparation error. "
    "The Data Summary states that discrete-analyzer chloride measurements "
    "\"to date\" were divided by 10, and that 2026 report cards were also "
    "adjusted. Newer candidate chemistry workbooks appear already corrected. "
    "This application's loading scripts do not apply another divide-by-10. "
    "A future refresh from a confirmed corrected workbook must avoid "
    "double-correction. Live database alignment cannot be guaranteed until "
    "the final All StreamWatch Data workbook is confirmed and present in the "
    "authoritative source set. This page is documentation only and does not "
    "change stored chloride values."
)

ANALYSIS_EXCLUSION_NOTE = (
    "Before analyzing StreamWatch raw data, Watershed's own practice is to "
    "exclude: (1) any record tagged Flagged in the Data Condition column "
    "(alone or combined with other tags); (2) any individual value carrying "
    "a trailing \"?\"; and (3) any Turbidity value collected under the "
    "discontinued CAT: Early LaMotte method. See the StreamWatch Data "
    "Dictionary for the full set of cell-level conventions."
)

METHOD_GROUPS = [
    {
        "name": "CAT: Hanna",
        "summary": (
            "Current CAT protocol using Hanna Instruments multimeter plus lab "
            "grab samples (typically Saturdays/Sundays 10AM–12PM). Parameters: "
            "air temperature, water temperature, pH, dissolved oxygen, "
            "conductivity, nitrate, phosphate, turbidity, chloride."
        ),
    },
    {
        "name": "CAT: LaMotte",
        "summary": (
            "Current CAT field-kit protocol (typically Fridays–Sundays "
            "10AM–12PM). Parameters: air temperature, water temperature, pH, "
            "dissolved oxygen, nitrate, phosphate, turbidity (no chloride in "
            "the Sep 9 Methods table)."
        ),
    },
    {
        "name": "CAT: Early LaMotte",
        "summary": (
            "Predecessor protocol to CAT: LaMotte, used from 1992 into the "
            "early 2010s (the two overlapped for several years). Same "
            "parameter set as CAT: LaMotte; Turbidity used a separate, "
            "discontinued proprietary method that is not comparable to later "
            "JTU/NTU methods and should be excluded from analysis."
        ),
    },
    {
        "name": "BAT",
        "summary": (
            "Macroinvertebrate counts/identification (family and/or genus) "
            "and USEPA Rapid Bio-Assessment Protocol habitat assessment scores."
        ),
    },
    {
        "name": "BACT",
        "summary": (
            "Sunday-season monitoring (May–September, typically 8AM–12PM): "
            "water temperature, nitrate, phosphate, turbidity, chloride, "
            "E. coli. No pH, DO, or conductivity in the Sep 9 Methods table."
        ),
    },
    {
        "name": "Salt Watch",
        "summary": (
            "Despite the label, this is not community Salt Watch program data. "
            "Per the Data Dictionary, these are in-house Hach Low-Range "
            "Chloride test-strip checks on CAT samples (within 48 hours) used "
            "as a check against Gallery Discrete Analyzer chloride. Only "
            "chloride, date, time, and location are recorded. Not listed in "
            "the Data Summary Methods table."
        ),
    },
]

# Parameter / instrument / detection-limit rows from Sep 9 Data Summary Methods table.
# activity_type is not provided in that table; left unresolved on purpose.
METHOD_ROWS = [
    {
        "parameter": "Water Temperature",
        "program": "CAT: LaMotte / CAT: Early LaMotte / BACT",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "°C",
        "limit": "LaMotte: -5.0 – 45.0 °C",
        "equipment": "LaMotte Armored Alcohol Thermometer",
        "effective_period": "1992–present (method groups as named)",
        "notes": "Sep 9 Summary lists this thermometer for CAT: LaMotte, CAT: Early LaMotte, and BACT.",
    },
    {
        "parameter": "Water Temperature",
        "program": "CAT: Hanna",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "°C",
        "limit": "Hanna: -5.0 – 55.0 °C",
        "equipment": "Hanna Instruments Multiparameter Meter",
        "effective_period": "2023 onward (Hanna introduced 2023)",
        "notes": "Instrument-specific range from the Sep 9 Methods table.",
    },
    {
        "parameter": "Air Temperature",
        "program": "CAT: Hanna / CAT: LaMotte / CAT: Early LaMotte",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "°C",
        "limit": "Not listed separately in Sep 9 detection-limit table",
        "equipment": "Collected under CAT method groups; instrument not separately listed in Sep 9 Methods table",
        "effective_period": "1992–present (CAT method groups)",
        "notes": "Named in the Method Group parameters table and Data Dictionary column list; no separate instrument/limit row in the Sep 9 Summary.",
    },
    {
        "parameter": "pH",
        "program": "CAT: LaMotte / CAT: Early LaMotte",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "pH units (0–14 scale)",
        "limit": "LaMotte: 3.0 – 10.5",
        "equipment": "LaMotte Precision pH Test Kit",
        "effective_period": "1992–present (LaMotte / Early LaMotte)",
        "notes": "Dictionary notes LaMotte color-swatch readings land on half-unit steps (3.0, 3.5, …).",
    },
    {
        "parameter": "pH",
        "program": "CAT: Hanna",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "pH units (0–14 scale)",
        "limit": "Hanna: 0.00 – 14.00",
        "equipment": "Hanna Multiparameter Meter",
        "effective_period": "2023 onward",
        "notes": "Digital continuous reading; judged on its own terms per Data Dictionary.",
    },
    {
        "parameter": "Dissolved Oxygen",
        "program": "CAT: LaMotte / CAT: Early LaMotte",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "mg/L",
        "limit": "LaMotte: 0.0 – 10.0 mg/L",
        "equipment": "LaMotte DO Test Kit",
        "effective_period": "1992–present (LaMotte / Early LaMotte)",
        "notes": "Dictionary also records DO (%) saturation separately when collected.",
    },
    {
        "parameter": "Dissolved Oxygen",
        "program": "CAT: Hanna",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "mg/L or ppm; % saturation",
        "limit": "Hanna: 0.0 – 500.0% / 0.00 – 50.00 mg/L or ppm",
        "equipment": "Hanna Multiparameter Meter",
        "effective_period": "2023 onward",
        "notes": "Both percent saturation and concentration ranges appear in the Sep 9 Methods table.",
    },
    {
        "parameter": "Conductivity",
        "program": "CAT: Hanna",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "µS/cm",
        "limit": "Hanna: 0 – 200,000 µS/cm",
        "equipment": "Hanna Multiparameter Meter",
        "effective_period": "2023 onward",
        "notes": "Not collected under CAT: LaMotte, CAT: Early LaMotte, or BACT per Sep 9 Methods table. Dictionary notes no formal Assessment Framework detection limit beyond the instrument range shown here.",
    },
    {
        "parameter": "Turbidity",
        "program": "CAT: LaMotte",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "JTU",
        "limit": "LaMotte: 5 – 200 JTU",
        "equipment": "LaMotte Turbidity Test Kit",
        "effective_period": "After mid–late 2010 turbidity method change (current LaMotte path)",
        "notes": "Timeline notes a CAT turbidity method change in mid–late 2010.",
    },
    {
        "parameter": "Turbidity",
        "program": "CAT: Hanna / BACT",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "NTU",
        "limit": "Hach: 0 – 1000 NTU",
        "equipment": "Hach 2100-P Turbidimeter",
        "effective_period": "Current CAT: Hanna and BACT methodology in Sep 9 Summary",
        "notes": "Exact start date for Hach use is not separately dated beyond method-group context.",
    },
    {
        "parameter": "Turbidity",
        "program": "CAT: Early LaMotte",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "Not comparable (proprietary / discontinued)",
        "limit": "Not comparable — exclude from analysis",
        "equipment": "Discontinued proprietary LaMotte turbidity method",
        "effective_period": "1992 into early 2010s (overlap with CAT: LaMotte)",
        "notes": "Purple-font convention in the Data Dictionary. Readings cannot be converted to or compared with later JTU/NTU methods; Watershed practice excludes them from analysis.",
    },
    {
        "parameter": "Nitrate",
        "program": "CAT: LaMotte / CAT: Early LaMotte",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "mg/L (as stated in Sep 9 Summary)",
        "limit": "LaMotte: <0.2 – 4.0 mg/L",
        "equipment": "LaMotte Nitrate-N/Phosphate Kit",
        "effective_period": "1992–present (LaMotte / Early LaMotte)",
        "notes": "Units and range shown as published in the Sep 9 Methods table.",
    },
    {
        "parameter": "Nitrate",
        "program": "CAT: Hanna / BACT",
        "field_lab": "Lab",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "mg/L (as stated in Sep 9 Summary)",
        "limit": "Gallery: 0.0115 – 25 mg/L",
        "equipment": "Thermo Scientific Gallery Discrete Analyzer",
        "effective_period": "BACT nutrient grabs from 2021; CAT Hanna from 2023",
        "notes": "Timeline: BACT begins nutrient grab samples with discrete analyzer in 2021; CAT introduces discrete analyzer with Hanna in 2023.",
    },
    {
        "parameter": "Phosphate",
        "program": "CAT: LaMotte / CAT: Early LaMotte",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "mg/L",
        "limit": "LaMotte: <0.2 – 1.0 mg/L",
        "equipment": "LaMotte Nitrate-N/Phosphate Kit",
        "effective_period": "1992–present (LaMotte / Early LaMotte)",
        "notes": "Sep 9 Methods table supersedes older ambiguous dual-limit placeholders.",
    },
    {
        "parameter": "Phosphate",
        "program": "CAT: Hanna / BACT",
        "field_lab": "Lab",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "mg/L",
        "limit": "Gallery: <0.01 – 10.0 mg/L",
        "equipment": "Gallery Discrete Analyzer",
        "effective_period": "BACT from 2021; CAT Hanna from 2023",
        "notes": "Instrument-specific Gallery range from the Sep 9 Methods table.",
    },
    {
        "parameter": "Chloride",
        "program": "CAT: Hanna / BACT",
        "field_lab": "Lab",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "mg/L",
        "limit": "Gallery: 20 – 500 mg/L",
        "equipment": "Gallery Discrete Analyzer",
        "effective_period": "BACT nutrient era from 2021; CAT Hanna from 2023",
        "notes": "See the 2026 chloride correction note. Salt Watch strip checks are documented separately under Method Groups.",
    },
    {
        "parameter": "E. coli",
        "program": "BACT",
        "field_lab": "Lab",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "colonies/100 mL (Methods table); MPN/100 mL in Data Dictionary E. coli Result",
        "limit": "0 – >2,419 colonies/100 mL",
        "equipment": "Idexx Colisure with Quanti-Tray (Methods table)",
        "effective_period": "BACT from 2007; method change noted 2015",
        "notes": (
            "Timeline says the 2015 switch was from Coliscan Easygel to IDEXX/Colilert; "
            "the Sep 9 Methods table lists Idexx Colisure with Quanti-Tray. "
            "Both source wordings are preserved; do not silently reconcile Colilert vs Colisure."
        ),
    },
    {
        "parameter": "Macroinvertebrate",
        "program": "BAT",
        "field_lab": "Field / Lab",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "Organism count / indices as reported",
        "limit": "Sample size: 90 – 110 organisms",
        "equipment": "Multihabitat D-net sampling",
        "effective_period": "1995–present; ID workflow changes after 2018 / 2024",
        "notes": "Family-level ID through 2018; from 2018 at least one event per year to species by certified lab; 2024 spring sampling uses certified lab IDs exclusively.",
    },
    {
        "parameter": "Habitat assessment",
        "program": "BAT",
        "field_lab": "Field",
        "activity_type": "Not listed in Sep 9 Methods table",
        "units": "Protocol sub-metric scores",
        "limit": "No numeric detection limit",
        "equipment": "USEPA Rapid Bio-Assessment Protocol",
        "effective_period": "BAT program; denser coverage ~2018 onward per Dictionary",
        "notes": "Used to help distinguish poor habitat from poor water quality as a driver of low macroinvertebrate scores.",
    },
]

TIMELINE_EVENTS = [
    {"year": "1992", "event": "StreamWatch Chemical Action Team (CAT) founded; volunteers begin collecting data twice a month."},
    {"year": "1995", "event": "Biological Action Team (BAT) founded; volunteers begin collecting data three times per year in spring, summer, and fall."},
    {"year": "2007", "event": "Bacterial Action Team (BACT) founded; volunteers begin collecting quarterly samples analyzed using Coliscan Easygel."},
    {"year": "2007", "event": "BAT QAPP? (source leaves this timeline entry unresolved)."},
    {"year": "2010", "event": "CAT switches from bi-weekly to monthly sampling."},
    {"year": "Mid–late 2010", "event": "CAT changes method for measuring turbidity."},
    {"year": "2011", "event": "BAT QAPP? (source leaves this timeline entry unresolved)."},
    {"year": "2014", "event": "BACT partnership with NJDEP."},
    {"year": "2015", "event": "BACT method switches from Coliscan Easygel to IDEXX/Colilert."},
    {"year": "2017", "event": "Expansion into Lower Delaware watershed."},
    {"year": "2018", "event": "BATs decrease from sampling 3× per year to 2× — alternating samples identified by volunteers or certified lab in spring and fall."},
    {"year": "2020", "event": "Significant decline in monitoring activities due to COVID-19 pandemic."},
    {"year": "2021", "event": "BACT begins collecting grab samples for nutrient analysis with discrete analyzer."},
    {"year": "2023", "event": "CAT introduces Hanna meters and use of discrete analyzer."},
    {"year": "2023", "event": "NJDEP approves BAT QAPP for Tier 3.3 data; field accreditations required for all BAT volunteers."},
    {"year": "2024", "event": "BATs decrease from sampling 2× per year to once in the spring, using certified lab identifications exclusively."},
    {"year": "2026", "event": "Error discovered in chloride standard preparation; measurements divided by 10 for all results measured by discrete analyzer to date (2026 report cards also adjusted)."},
    {"year": "2026", "event": "Full review of Data Condition tags completed (August)."},
    {"year": "Discontinued", "event": "River Action Team / StreamWalking conducted quarterly visual stream-corridor and habitat assessments; program discontinued and its data is not included in the current dataset."},
]

SOURCE_NOTES = [
    "Primary sources: StreamWatch Data Summary & Description and StreamWatch Data Dictionary, last updated September 9, 2026.",
    "The Method field identifies a named protocol group, not an individual instrument.",
    "Instrument-specific detection ranges replace older ambiguous dual placeholders where the Sep 9 Methods table provides clearer values.",
    "CAT: Early LaMotte was added to the Sep 9 Methods group table so documentation matches Method values used in the raw dataset.",
    "Colilert (timeline) vs Colisure (Methods table) naming is preserved as source ambiguity.",
    "WQX activity-type labels are not part of the Sep 9 Methods table and are not invented here.",
    "This page documents Watershed source materials; it does not independently define scientific policy or change stored data.",
]
