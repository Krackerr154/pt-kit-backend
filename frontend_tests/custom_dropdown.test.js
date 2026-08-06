const fs = require('fs');
const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync('app/static/index.html', 'utf8');
const inline = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].at(-1)[1];

// ---------------------------------------------------------------------------
// Minimal harness (mirrors priority1_integration.test.js): bare createElement
// stubs that omit classList/dataset/insertAdjacentElement. The L479-481 guard
// in customizeSelect must feature-detect this and no-op without crashing.
// ---------------------------------------------------------------------------
function minimalHarness() {
  function el(id = '') {
    return {
      id, value: '', innerText: '', textContent: '', innerHTML: '',
      hidden: false, disabled: false, style: { display: 'none' },
      className: '', children: [],
      classList: { add() {}, remove() {}, toggle() {} },
      appendChild(c) { this.children.push(c); return c; },
      append(...c) { this.children.push(...c); },
      replaceChildren(...c) { this.children = c; },
      querySelector() { return elLeaf(); },
      focus() {}, addEventListener() {}, setAttribute() {}, removeAttribute() {},
      getContext() { return {}; }
    };
  }
  function elLeaf() {
    return { innerText: '', textContent: '', innerHTML: '', style: {}, className: '', focus() {}, setAttribute() {}, removeAttribute() {} };
  }
  const elements = new Map();
  const document = {
    getElementById(id) { if (!elements.has(id)) elements.set(id, el(id)); return elements.get(id); },
    querySelector() { return elLeaf(); },
    createElement(tag) { return el(tag); },
    createTextNode(text) { return { textContent: text }; },
    addEventListener() {}
  };
  class Chart {
    static register() {}
    constructor(_c, config) { this.data = config.data; this.options = config.options; this.ctx = { save() {}, restore() {}, fillRect() {} }; this.scales = { x: { getPixelForValue: v => v } }; this.chartArea = { top: 0, bottom: 100 }; }
    update() {} destroy() {} resetZoom() {}
  }
  const context = {
    document, Chart, console, Date, Math, JSON, Number, parseInt, parseFloat, Promise,
    fetch: () => Promise.resolve({ ok: true, status: 200, json: async () => ({}) }),
    setInterval() { return 1; }, clearInterval() {}, setTimeout(fn) { fn(); return 1; }, clearTimeout() {}, alert() {}
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(inline, context, { filename: 'index.inline.js' });
  return { context, elements };
}

// ---------------------------------------------------------------------------
// Rich harness: a fuller mock DOM that genuinely provides the APIs
// customizeSelect touches (classList, dataset, parentNode, insertBefore,
// appendChild, setAttribute, addEventListener, contains, querySelector,
// insertAdjacentElement, style, textContent). This lets the FULL code path run.
// ---------------------------------------------------------------------------
function richHarness() {
  // A single shared registry so document.querySelectorAll('.csel...') works.
  const allCreatedEls = [];

  // Shared root container: every mock element defaults its parentNode to this,
  // so sel.parentNode.insertBefore(wrap, sel) during initCustomSelects() at
  // script-load time doesn't crash on detached elements.
  const root = {
    tagName: 'DIV', id: '', className: '', children: [], childNodes: [],
    insertBefore(newNode, ref) { this.children.unshift(newNode); if (newNode) newNode._parent = this; return newNode; },
    appendChild(c) { this.children.push(c); if (c) c._parent = this; return c; },
    append(...c) { c.forEach(x => this.appendChild(x)); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    addEventListener() {}, removeEventListener() {}, contains() { return false; }
  };

  function makeEl(tag) {
    const node = {
      tagName: String(tag || 'div').toUpperCase(),
      id: '',
      value: '',
      innerText: '',
      textContent: '',
      innerHTML: '',
      hidden: false,
      disabled: false,
      type: '',
      className: '',
      children: [],
      childNodes: [],
      options: [],
      selectedIndex: 0,
      dataset: {},
      style: {},
      _attrs: {},
      _listeners: {},
      _parent: root,
      get parentNode() { return this._parent; },
      get parentElement() { return this._parent; },
      classList: {
        add(c) { const s = (node.className || '').split(/\s+/).filter(Boolean); if (!s.includes(c)) s.push(c); node.className = s.join(' '); },
        remove(c) { const s = (node.className || '').split(/\s+/).filter(x => x !== c); node.className = s.join(' '); },
        toggle(c, force) { const s = (node.className || '').split(/\s+/).filter(Boolean); const has = s.includes(c); if (force === true) { if (!has) s.push(c); } else if (force === false) { /* remove */ } else { has ? s.splice(s.indexOf(c), 1) : s.push(c); } node.className = s.join(' '); },
        contains(c) { return (node.className || '').split(/\s+/).includes(c); }
      },
      setAttribute(k, v) { node._attrs[k] = String(v); if (k === 'class') node.className = String(v); },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(node._attrs, k) ? node._attrs[k] : null; },
      removeAttribute(k) { delete node._attrs[k]; },
      hasAttribute(k) { return Object.prototype.hasOwnProperty.call(node._attrs, k); },
      appendChild(c) { node.children.push(c); node.childNodes.push(c); if (c) c._parent = node; return c; },
      append(...c) { c.forEach(x => node.appendChild(x)); },
      replaceChildren(...c) { node.children = [...c]; node.childNodes = [...c]; c.forEach(x => { if (x) x._parent = node; }); },
      insertBefore(newNode, ref) { node.children.unshift(newNode); node.childNodes.unshift(newNode); if (newNode) newNode._parent = node; return newNode; },
      insertAdjacentElement(pos, el) { if (el) el._parent = node._parent; return el; },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      contains(target) { if (!target) return false; let n = target; while (n) { if (n === node) return true; n = n._parent; } return false; },
      addEventListener(type, fn) { (node._listeners[type] = node._listeners[type] || []).push(fn); },
      removeEventListener() {},
      dispatchEvent(e) { const fns = node._listeners[e && e.type] || []; fns.forEach(fn => { try { fn(e); } catch (_) {} }); return true; },
      focus() {},
      scrollIntoView() {},
      remove() { if (node._parent) { const p = node._parent; p.children = p.children.filter(c => c !== node); p.childNodes = p.childNodes.filter(c => c !== node); node._parent = null; } },
      closest() { return null; },
      getContext() { return {}; }
    };
    allCreatedEls.push(node);
    return node;
  }

  // document.querySelectorAll needs to scan all live elements for .csel matches.
  // getElementById lazily creates a rich element (like the minimal harness) so
  // top-level init code in the inline script doesn't crash on null.
  const byId = new Map();
  const document = {
    _els: allCreatedEls,
    getElementById(id) { if (!byId.has(id)) byId.set(id, makeEl(id)); return byId.get(id); },
    createElement(tag) { return makeEl(tag); },
    createTextNode(text) { return { textContent: text } },
    querySelector() { return null; },
    querySelectorAll(sel) {
      // Minimal selector support for '.csel[data-open="true"]' used by closeAll.
      if (/^\.csel(\[data-open=["']true["']\])?$/.test(sel)) {
        return allCreatedEls.filter(e => (e.className || '').split(/\s+/).includes('csel') && e.dataset && e.dataset.open === 'true');
      }
      return [];
    },
    addEventListener() {}
  };

  // Event constructor (customizeSelect's choose() uses `new Event('change')`).
  function Event(type) { this.type = type; this.bubbles = false; }

  // Minimal Chart stub (the inline script calls initChart at load time).
  class Chart {
    static register() {}
    constructor(_ctx, config) { this.data = config && config.data; this.options = config && config.options; }
    update() {} destroy() {} resetZoom() {}
  }

  const context = {
    document, Event, Chart, console, Date, Math, JSON, Number, parseInt, parseFloat, Promise,
    fetch: () => Promise.resolve({ ok: true, status: 200, json: async () => ({}) }),
    setInterval() { return 1; }, clearInterval() {}, setTimeout(fn) { fn(); return 1; }, clearTimeout() {}, alert() {}
  };
  context.window = context;
  context.Event = Event;
  vm.createContext(context);
  vm.runInContext(inline, context, { filename: 'index.inline.js' });
  return { context, document, makeEl };
}

// ===========================================================================
// GUARD PATH — minimal mock: customizeSelect returns null, does not crash.
// ===========================================================================
test('guard path: customizeSelect no-ops in minimal mock DOM without classList/dataset/insertAdjacentElement', () => {
  const h = minimalHarness();
  const c = h.context;
  // The minimal el() has classList but no dataset object and no insertAdjacentElement,
  // so the probe feature-detect at L479-480 must bail out.
  const probe = c.document.createElement('a');
  assert.ok(!('dataset' in probe) || typeof probe.insertAdjacentElement !== 'function',
    'minimal mock should lack the APIs the guard checks');
  const select = c.document.createElement('select');
  assert.equal(c.customizeSelect(select, {}), null, 'guard must return null in minimal mock');
  // Calling again must still be safe (no throw, returns null).
  assert.equal(c.customizeSelect(select, {}), null);
});

// ===========================================================================
// FULL PATH — richer mock: the real enhancement logic runs end to end.
// ===========================================================================
test('full path: customizeSelect wraps select in .csel div and marks idempotency', () => {
  const { context, document, makeEl } = richHarness();

  // Build a mocked <select> with three options, as the real selects have.
  const select = document.createElement('select');
  select.id = 'experimentMode';
  const opts = ['NORMAL_CYCLIC', 'FIXED_TEMPERATURE', 'NATURAL_PLATEAU'].map(v => {
    const o = makeEl('option');
    o.value = v; o.textContent = v.replace(/_/g, ' '); o.selected = false;
    return o;
  });
  opts[0].selected = true;
  select.options = opts;
  select.selectedIndex = 0;
  // Give the select a parent (insertBefore needs parentNode).
  const parent = document.createElement('div');
  parent.appendChild(select);

  const descriptions = { NORMAL_CYCLIC: 'Heating / cooling cycles', FIXED_TEMPERATURE: 'Hold a constant temperature' };
  assert.doesNotThrow(() => context.customizeSelect(select, descriptions), 'enhancement must not crash');

  // It wraps the select in a .csel div.
  const wrap = select._parent;
  assert.ok(wrap, 'select must be reparented into a wrapper');
  assert.equal(wrap.className, 'csel', 'wrapper must have class csel');
  assert.equal(wrap.dataset.open, 'false', 'wrapper starts closed');
  assert.ok(wrap.children.includes(select), 'wrapper must contain the original select');
  assert.ok(select.classList.contains('visually-hidden'), 'select must be hidden');
  assert.equal(select._attrs['aria-hidden'], 'true', 'select must be aria-hidden');

  // Idempotency: dataset.cselEnhanced === 'true'.
  assert.equal(select.dataset.cselEnhanced, 'true', 'select must be marked enhanced');
  const second = context.customizeSelect(select, descriptions);
  assert.equal(second, null, 'calling customizeSelect twice must return null');
});

test('full path: customizeSelect creates .csel-btn button and .csel-list listbox', () => {
  const { context, document, makeEl } = richHarness();
  const select = document.createElement('select');
  select.options = [makeEl('option')].map(o => { o.value = 'X'; o.textContent = 'X'; o.selected = true; return o; });
  select.selectedIndex = 0;
  const parent = document.createElement('div');
  parent.appendChild(select);

  const wrap = context.customizeSelect(select, {});
  assert.ok(wrap, 'must return the wrapper');
  const btn = wrap.children.find(c => c.className === 'csel-btn');
  const list = wrap.children.find(c => c.className === 'csel-list');
  assert.ok(btn, 'must create .csel-btn button');
  assert.equal(btn.tagName, 'BUTTON');
  assert.equal(btn._attrs['aria-haspopup'], 'listbox');
  assert.equal(btn._attrs['aria-expanded'], 'false', 'button starts collapsed');
  assert.ok(list, 'must create .csel-list listbox');
  assert.equal(list.tagName, 'UL');
  assert.equal(list._attrs['role'], 'listbox');
});

test('full path: customizeSelect creates .csel-opt elements matching select options', () => {
  const { context, document, makeEl } = richHarness();
  const select = document.createElement('select');
  const optVals = ['TC', 'IR'];
  select.options = optVals.map(v => { const o = makeEl('option'); o.value = v; o.textContent = v; o.selected = (v === 'TC'); return o; });
  select.selectedIndex = 0;
  const parent = document.createElement('div');
  parent.appendChild(select);

  const wrap = context.customizeSelect(select, { TC: 'Thermocouple (contact)', IR: 'Infrared (non-contact)' });
  const list = wrap.children.find(c => c.className === 'csel-list');
  assert.ok(list, 'listbox must exist');
  const opts = list.children.filter(c => c.className === 'csel-opt');
  assert.equal(opts.length, 2, 'must create one .csel-opt per option');
  assert.equal(opts[0].dataset.value, 'TC', 'first opt carries TC value');
  assert.equal(opts[1].dataset.value, 'IR', 'second opt carries IR value');
  assert.equal(opts[0]._attrs['role'], 'option', 'opts have role=option');
  assert.equal(opts[0].dataset.selected, 'true', 'selected opt marked');
  assert.equal(opts[1].dataset.selected, 'false', 'non-selected opt unmarked');
});

test('full path: clicking the button toggles dataset.open', () => {
  const { context, document, makeEl } = richHarness();
  const select = document.createElement('select');
  select.options = [makeEl('option')].map(o => { o.value = 'A'; o.textContent = 'A'; o.selected = true; return o; });
  select.selectedIndex = 0;
  const parent = document.createElement('div');
  parent.appendChild(select);

  const wrap = context.customizeSelect(select, {});
  const btn = wrap.children.find(c => c.className === 'csel-btn');
  const clickHandlers = btn._listeners['click'] || [];
  assert.ok(clickHandlers.length > 0, 'button must have a click listener');

  // Closed -> open.
  assert.equal(wrap.dataset.open, 'false', 'starts closed');
  clickHandlers.forEach(fn => fn({}));
  assert.equal(wrap.dataset.open, 'true', 'first click opens the list');
  assert.equal(btn._attrs['aria-expanded'], 'true', 'aria-expanded reflects open');

  // Open -> closed.
  clickHandlers.forEach(fn => fn({}));
  assert.equal(wrap.dataset.open, 'false', 'second click closes the list');
  assert.equal(btn._attrs['aria-expanded'], 'false', 'aria-expanded reflects closed');
});

test('full path: initCustomSelects does not crash when selects are present', () => {
  const { context, document, makeEl } = richHarness();
  // Provide the three real selects with one option each (experimentMode uses tabs, not a custom dropdown).
  ['fixedControlSensor', 'plateauControlSensor', 'postPlateauBehavior'].forEach(id => {
    const sel = makeEl('select'); sel.id = id;
    const o = makeEl('option'); o.value = 'X'; o.textContent = 'X'; o.selected = true;
    sel.options = [o]; sel.selectedIndex = 0;
    const parent = makeEl('div'); parent.appendChild(sel);
    document.getElementById = (targetId) => targetId === id ? sel : null;
    context.customizeSelect(sel, {});
  });
  assert.doesNotThrow(() => context.initCustomSelects());
});
