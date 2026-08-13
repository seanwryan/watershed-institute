/* Shared StreamWatch parameter labels/units for monitoring UI (frontend only). */
window.StreamWatchParams = (function () {
  var META = {
    air_temp_c: { label: "Air temperature", unit: "°C" },
    water_temp_c: { label: "Water temperature", unit: "°C" },
    dissolved_oxygen_ppm: { label: "Dissolved oxygen", unit: "mg/L" },
    dissolved_oxygen_pct: { label: "Dissolved oxygen saturation", unit: "%" },
    nitrate_ug_l: { label: "Nitrate", unit: "µg/L" },
    phosphate_mg_l: { label: "Phosphate", unit: "mg/L" },
    ph: { label: "pH", unit: "" },
    turbidity_ntu: { label: "Turbidity", unit: "NTU" },
    conductivity_us_cm: { label: "Conductivity", unit: "µS/cm" },
    chloride_mg_l: { label: "Chloride", unit: "mg/L" },
    e_coli_mpn_100ml: { label: "E. coli", unit: "MPN/100mL" }
  };

  function meta(id) {
    return META[id] || { label: id, unit: "" };
  }

  function displayLabel(id) {
    var m = meta(id);
    return m.unit ? m.label + " (" + m.unit + ")" : m.label;
  }

  function titleLabel(id) {
    return meta(id).label;
  }

  function unit(id) {
    return meta(id).unit || "";
  }

  return { META: META, meta: meta, displayLabel: displayLabel, titleLabel: titleLabel, unit: unit };
})();
