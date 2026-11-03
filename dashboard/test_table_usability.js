/* Run with: node --test dashboard/test_table_usability.js (no npm dependencies). */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

// Minimal DOM fixture for the shared utility's actual click/input handlers.
class Element {
  constructor(text = '', attrs = {}) {
    this.textContent = text;
    this.attrs = { ...attrs };
    this.children = [];
    this.listeners = {};
    this.hidden = false;
    this.classes = new Set();
    this.classList = {
      contains: name => this.classes.has(name),
      toggle: (name, enabled) => enabled ? this.classes.add(name) : this.classes.delete(name)
    };
  }
  getAttribute(name) { return this.attrs[name] ?? null; }
  setAttribute(name, value) { this.attrs[name] = value; }
  appendChild(child) {
    this.children = this.children.filter(item => item !== child);
    this.children.push(child);
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  querySelector(selector) {
    return selector === '.table-sort'
      ? this.children.find(item => item.className === 'table-sort') || null : null;
  }
  querySelectorAll(selector) {
    if (selector === 'tr') return this.children;
    return [];
  }
}

function fixture() {
  const document = {
    readyState: 'loading',
    addEventListener() {},
    createElement: () => new Element()
  };
  const window = {};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'static/js/table_enhance.js'), 'utf8'), { window, document });
  const headers = [
    new Element('Site'),
    new Element('Open', { 'data-sortable': 'false' }),
    new Element('Value', { 'data-type': 'number' }),
    new Element('Date', { 'data-type': 'date' })
  ];
  const tbody = new Element();
  function row(site, value, date) {
    const tr = new Element([site, 'Open', value, date].join(' '));
    tr.cells = [site, 'Open', value, date].map(text => new Element(text));
    // Preserve actual row/link identity when sorting, rather than rewriting HTML.
    tr.link = { href: '/site/' + site };
    return tr;
  }
  tbody.children = [row('B2', '10', '2026-10-01'), row('A1', '2', '2025-01-01'), row('C3', '—', '')];
  const originalRows = [...tbody.children];
  const table = new Element();
  table.tBodies = [tbody];
  table.querySelectorAll = selector => selector === 'thead th' ? headers : [];
  const search = new Element();
  search.value = '';
  const count = new Element();
  window.StreamWatchTables.enhance(table, { searchInput: search, countEl: count });
  return { headers, tbody, table, search, count, originalRows, tables: window.StreamWatchTables };
}

test('sort indicators track real columns past a non-sortable column', () => {
  const f = fixture();
  const valueButton = f.headers[2].querySelector('.table-sort');
  valueButton.listeners.click();
  assert.deepEqual(f.tbody.children.map(row => row.cells[2].textContent), ['2', '10', '—']);
  assert.equal(f.headers[2].getAttribute('aria-sort'), 'ascending');
  assert.equal(valueButton.textContent, 'Value ↑');
  assert.equal(f.headers[1].querySelector('.table-sort'), null);
  assert.equal(valueButton.getAttribute('aria-sort'), null); // ARIA belongs on th.
  valueButton.listeners.click();
  assert.deepEqual(f.tbody.children.map(row => row.cells[2].textContent), ['10', '2', '—']);
  assert.equal(f.headers[2].getAttribute('aria-sort'), 'descending');
  f.headers[3].querySelector('.table-sort').listeners.click();
  assert.equal(f.headers[2].getAttribute('aria-sort'), 'none');
  assert.equal(f.headers[3].getAttribute('aria-sort'), 'ascending');
  assert.equal(f.headers[3].querySelector('.table-sort').textContent, 'Date ↑');
  assert.deepEqual(f.tbody.children.map(row => row.cells[0].textContent), ['A1', 'B2', 'C3']);
  f.originalRows.forEach(row => assert.ok(f.tbody.children.includes(row) && row.link.href));
});

test('text search updates counts, clearing restores rows, and sort survives refresh', () => {
  const f = fixture();
  f.headers[0].querySelector('.table-sort').listeners.click();
  assert.deepEqual(f.tbody.children.map(row => row.cells[0].textContent), ['A1', 'B2', 'C3']);
  f.search.value = 'b2';
  f.search.listeners.input();
  assert.equal(f.count.textContent, '1 of 3 rows');
  assert.equal(f.tbody.children.filter(row => !row.hidden)[0].cells[0].textContent, 'B2');
  f.search.value = 'not present';
  f.search.listeners.input();
  assert.equal(f.count.textContent, '0 of 3 rows');
  f.search.value = '';
  f.search.listeners.input();
  assert.equal(f.count.textContent, '3 rows');
  assert.ok(f.tbody.children.every(row => !row.hidden));
  f.tbody.children.reverse();
  f.tables.refresh(f.table);
  assert.deepEqual(f.tbody.children.map(row => row.cells[0].textContent), ['A1', 'B2', 'C3']);
});

for (const template of ['equipment.html', 'equipment_detail.html']) {
  test(template + ': inactive and retired meters never get the active badge', () => {
    const source = fs.readFileSync(path.join(__dirname, 'templates', template), 'utf8');
    const start = source.indexOf('  function statusBadge(');
    const end = source.indexOf('\n  }', start) + 4;
    assert.ok(start >= 0 && end > start);
    const statusBadge = vm.runInNewContext('(' + source.slice(start, end) + ')', {
      esc: value => String(value).replace(/</g, '&lt;')
    });
    assert.match(statusBadge('Active'), /badge-success/);
    for (const status of ['Inactive', 'INACTIVE', 'Retired', 'Inactive / retired']) {
      assert.match(statusBadge(status), /badge-warning/);
      assert.doesNotMatch(statusBadge(status), /badge-success/);
    }
    assert.doesNotMatch(statusBadge('Unknown'), /badge-success|badge-warning/);
    assert.doesNotMatch(statusBadge(null), /badge-success|badge-warning/);
    assert.doesNotMatch(statusBadge('<script>'), /<script>/);
  });
}
