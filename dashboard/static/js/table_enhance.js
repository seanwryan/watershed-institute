/* Lightweight sortable / searchable tables for StreamWatch staff views. */
(function (global) {
  var EMPTY_RE = /^(?:—|-|–|n\/?a|none|not recorded|loading|no .+)$/i;

  function textOf(el) {
    return (el && (el.textContent || '') || '').replace(/\s+/g, ' ').trim();
  }

  function isBlank(text) {
    return !text || EMPTY_RE.test(text);
  }

  function detectType(text) {
    if (isBlank(text)) return 'blank';
    if (/^\d{4}-\d{2}-\d{2}/.test(text)) return 'date';
    if (/^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}$/i.test(text)) return 'date';
    var cleaned = text.replace(/,/g, '').replace(/%$/, '');
    if (/^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/.test(cleaned)) return 'number';
    return 'text';
  }

  function parseDate(text) {
    if (!text) return null;
    var iso = String(text).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (iso) return Date.UTC(+iso[1], +iso[2] - 1, +iso[3]);
    var named = String(text).match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s+(\d{4})$/i);
    if (named) {
      var months = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
      return Date.UTC(+named[3], months[named[1].toLowerCase()], +named[2]);
    }
    var t = Date.parse(text);
    return isNaN(t) ? null : t;
  }

  function parseNumber(text) {
    if (isBlank(text)) return null;
    var n = Number(String(text).replace(/,/g, '').replace(/%$/, ''));
    return isFinite(n) ? n : null;
  }

  function compareValues(aText, bText, type, desc) {
    var aBlank = isBlank(aText);
    var bBlank = isBlank(bText);
    if (aBlank && bBlank) return 0;
    if (aBlank) return 1;
    if (bBlank) return -1;

    var dir = desc ? -1 : 1;
    var kind = type || 'auto';
    if (kind === 'auto') {
      var da = detectType(aText);
      var db = detectType(bText);
      kind = da === db ? da : 'text';
    }

    if (kind === 'number') {
      var an = parseNumber(aText);
      var bn = parseNumber(bText);
      if (an == null && bn == null) return 0;
      if (an == null) return 1;
      if (bn == null) return -1;
      if (an < bn) return -1 * dir;
      if (an > bn) return 1 * dir;
      return 0;
    }

    if (kind === 'date') {
      var ad = parseDate(aText);
      var bd = parseDate(bText);
      if (ad == null && bd == null) return String(aText).localeCompare(String(bText)) * dir;
      if (ad == null) return 1;
      if (bd == null) return -1;
      if (ad < bd) return -1 * dir;
      if (ad > bd) return 1 * dir;
      return 0;
    }

    return String(aText).localeCompare(String(bText), undefined, { sensitivity: 'base', numeric: true }) * dir;
  }

  function dataRows(tbody) {
    return Array.prototype.slice.call(tbody.querySelectorAll('tr')).filter(function (tr) {
      if (tr.getAttribute('data-empty-row') === 'true') return false;
      if (tr.classList.contains('table-empty-row')) return false;
      var cells = tr.cells;
      if (!cells || !cells.length) return false;
      if (cells.length === 1 && cells[0].colSpan > 1) return false;
      return true;
    });
  }

  function ensureSortButton(th) {
    if (th.querySelector('.table-sort')) return th.querySelector('.table-sort');
    if (th.getAttribute('data-sortable') === 'false') return null;
    var label = textOf(th) || 'Column';
    th.textContent = '';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'table-sort';
    btn.textContent = label;
    btn.setAttribute('aria-sort', 'none');
    th.appendChild(btn);
    return btn;
  }

  function updateSortIndicators(table, activeIndex, desc) {
    Array.prototype.forEach.call(table.querySelectorAll('thead .table-sort'), function (btn, idx) {
      var active = idx === activeIndex;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-sort', active ? (desc ? 'descending' : 'ascending') : 'none');
      var marker = active ? (desc ? ' ↓' : ' ↑') : '';
      var base = btn.getAttribute('data-label') || btn.textContent.replace(/\s*[↑↓]$/, '');
      btn.setAttribute('data-label', base);
      btn.textContent = base + marker;
    });
  }

  function applyVisibility(state) {
    var rows = dataRows(state.tbody);
    var q = (state.searchInput && state.searchInput.value || '').trim().toLowerCase();
    var visible = 0;
    rows.forEach(function (tr) {
      var show = !q || textOf(tr).toLowerCase().indexOf(q) !== -1;
      tr.hidden = !show;
      if (show) visible += 1;
    });
    if (state.countEl) {
      var total = rows.length;
      if (!total) {
        state.countEl.textContent = state.countEl.getAttribute('data-count-empty') || '';
      } else if (!q || visible === total) {
        state.countEl.textContent = total + ' row' + (total === 1 ? '' : 's');
      } else {
        state.countEl.textContent = visible + ' of ' + total + ' rows';
      }
    }
    return visible;
  }

  function sortDom(state, colIndex, type, desc) {
    var rows = dataRows(state.tbody);
    rows.sort(function (a, b) {
      var aCell = a.cells[colIndex];
      var bCell = b.cells[colIndex];
      var aVal = aCell ? (aCell.getAttribute('data-sort-value') || textOf(aCell)) : '';
      var bVal = bCell ? (bCell.getAttribute('data-sort-value') || textOf(bCell)) : '';
      return compareValues(aVal, bVal, type, desc);
    });
    rows.forEach(function (tr) { state.tbody.appendChild(tr); });
    state.sortIndex = colIndex;
    state.sortDesc = !!desc;
    state.sortType = type || 'auto';
    updateSortIndicators(state.table, colIndex, !!desc);
    applyVisibility(state);
  }

  function enhance(table, options) {
    if (!table || table.getAttribute('data-enhanced') === 'true') {
      if (table && table._swt) {
        applyVisibility(table._swt);
        if (table._swt.sortIndex != null) {
          sortDom(table._swt, table._swt.sortIndex, table._swt.sortType, table._swt.sortDesc);
        }
      }
      return table && table._swt;
    }

    options = options || {};
    var tbody = table.tBodies[0];
    if (!tbody) return null;

    var state = {
      table: table,
      tbody: tbody,
      searchInput: options.searchInput || (table.getAttribute('data-search') ? document.querySelector(table.getAttribute('data-search')) : null),
      countEl: options.countEl || (table.getAttribute('data-count') ? document.querySelector(table.getAttribute('data-count')) : null),
      sortIndex: null,
      sortDesc: false,
      sortType: 'auto'
    };

    Array.prototype.forEach.call(table.querySelectorAll('thead th'), function (th, idx) {
      var btn = ensureSortButton(th);
      if (!btn) return;
      btn.addEventListener('click', function () {
        var type = th.getAttribute('data-type') || 'auto';
        var desc = state.sortIndex === idx ? !state.sortDesc : false;
        sortDom(state, idx, type, desc);
      });
    });

    if (state.searchInput) {
      state.searchInput.addEventListener('input', function () {
        applyVisibility(state);
      });
    }

    table.setAttribute('data-enhanced', 'true');
    table._swt = state;
    applyVisibility(state);
    return state;
  }

  function refresh(table) {
    if (!table) return;
    if (table.getAttribute('data-enhanced') !== 'true') {
      enhance(table);
      return;
    }
    var state = table._swt;
    if (!state) return;
    state.tbody = table.tBodies[0];
    if (state.sortIndex != null) {
      sortDom(state, state.sortIndex, state.sortType, state.sortDesc);
    } else {
      applyVisibility(state);
    }
  }

  function enhanceAll(root) {
    root = root || document;
    Array.prototype.forEach.call(root.querySelectorAll('table[data-enhance="table"]'), function (table) {
      enhance(table);
    });
  }

  function compare(a, b, type, desc) {
    return compareValues(a, b, type, desc);
  }

  global.StreamWatchTables = {
    enhance: enhance,
    enhanceAll: enhanceAll,
    refresh: refresh,
    compare: compare,
    detectType: detectType
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { enhanceAll(document); });
  } else {
    enhanceAll(document);
  }
})(window);
