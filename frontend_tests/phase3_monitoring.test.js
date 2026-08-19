const fs = require('node:fs');
const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync('app/static/index.html', 'utf8');
const inline = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].at(-1)[1];

function extractFunction(name) {
  const start = inline.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing ${name}`);
  const bodyStart = inline.indexOf('{', start);
  let depth = 0;
  let quote = null;
  let escaped = false;
  for (let i = bodyStart; i < inline.length; i += 1) {
    const ch = inline[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue; }
    if (ch === '{') depth += 1;
    if (ch === '}' && --depth === 0) return inline.slice(start, i + 1);
  }
  assert.fail(`unterminated ${name}`);
}

function harness() {
  const elements = new Map();
  const make = id => ({
    id, hidden: true, className: '', textContent: '', dataset: {},
    setAttribute(name, value) { this[name] = String(value); },
    getAttribute(name) { return this[name] ?? null; },
  });
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, make(id));
      return elements.get(id);
    },
    querySelector(selector) {
      if (selector === '.chart-container') return this.getElementById('temperatureChart');
      if (selector === '.lux-chart-container') return this.getElementById('luxChart');
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '[data-view]') return ['temperature', 'illuminance', 'both'].map(view => {
        const button = make(`view-${view}`);
        button.dataset.view = view;
        button.setAttribute('aria-pressed', 'false');
        elements.set(button.id, button);
        return button;
      });
      return [];
    },
  };
  const context = { document, Number, Math, String };
  vm.createContext(context);
  vm.runInContext(extractFunction('formatAge'), context);
  vm.runInContext(extractFunction('renderTelemetryOverlay'), context);
  vm.runInContext(extractFunction('setMonitoringView'), context);
  return { context, document, get: id => document.getElementById(id) };
}

test('telemetry notice transitions live -> stale -> offline without destroying cached charts', () => {
  const h = harness();
  const notice = h.get('telemetryNotice');
  const overlay = h.get('chartOverlay');

  h.context.renderTelemetryOverlay('live', 1);
  assert.equal(notice.hidden, true);
  assert.equal(overlay.hidden, true);

  h.context.renderTelemetryOverlay('stale', 8);
  assert.equal(notice.hidden, false);
  assert.match(notice.textContent, /TELEMETRY STALE/);
  assert.match(notice.textContent, /8s ago/);
  assert.equal(notice.className, 'telemetry-notice');
  assert.equal(overlay.hidden, true, 'shared notice replaces chart-blocking overlay');

  h.context.renderTelemetryOverlay('offline', 12);
  assert.equal(notice.hidden, false);
  assert.match(notice.textContent, /TELEMETRY OFFLINE/);
  assert.equal(notice.className, 'telemetry-notice telemetry-offline');

  h.context.renderTelemetryOverlay('live', 1);
  assert.equal(notice.hidden, true, 'recovery clears the stale notice');
});

test('monitoring view selector exposes exactly one selected view and toggles chart visibility', () => {
  const h = harness();
  const temp = h.get('temperatureChart');
  const lux = h.get('luxChart');

  h.context.setMonitoringView('temperature');
  assert.equal(temp.hidden, false);
  assert.equal(lux.hidden, true);

  h.context.setMonitoringView('illuminance');
  assert.equal(temp.hidden, true);
  assert.equal(lux.hidden, false);

  h.context.setMonitoringView('both');
  assert.equal(temp.hidden, false);
  assert.equal(lux.hidden, false);

  assert.match(html, /id="telemetryNotice"[^>]*role="status"[^>]*aria-live="assertive"/);
});

console.log('Phase 3 monitoring runtime: PASS');