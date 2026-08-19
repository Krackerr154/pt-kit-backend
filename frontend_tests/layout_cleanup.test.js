const fs = require('fs');
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
    const char = inline[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
      else if (char === quote) quote = null;
      continue;
    }
    if (char === '"' || char === "'" || char === '`') { quote = char; continue; }
    if (char === '{') depth += 1;
    if (char === '}' && --depth === 0) return inline.slice(start, i + 1);
  }
  assert.fail(`unterminated ${name}`);
}

function visibilityHarness() {
  const elements = new Map();
  const element = id => ({ id, hidden: false, disabled: false, textContent: '', innerHTML: '', dataset: {} });
  const document = { getElementById(id) { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); } };
  const context = { document };
  vm.createContext(context);
  vm.runInContext(extractFunction('renderMonitoringVisibility'), context);
  vm.runInContext(extractFunction('renderPhaseVisibility'), context);
  return { context, get: id => document.getElementById(id) };
}

test('compact instrument header carries primary run, device, and freshness status', () => {
  assert.match(html, /<header[^>]*class="instrument-header"/);
  assert.match(html, /id="stateBadge"[^>]*aria-live="polite"/);
  assert.match(html, /id="connStatus"[^>]*aria-live="polite"/);
  assert.match(html, /id="backendStatus"[^>]*aria-live="polite"/);
  assert.match(html, /id="sampleFreshness"[^>]*aria-live="polite"/);
  assert.match(html, /id="healthCluster"[^>]*class="health-cluster"/);
  assert.match(html, /\.header-brand\s*>\s*\.health-cluster\s*\{\s*display:none/);
  assert.match(html, /Utilities ▾/);
});

test('monitoring starts as one purposeful empty state and hides all scientific chrome', () => {
  assert.match(html, /id="monitoringEmpty"[^>]*class="monitoring-empty"/);
  assert.match(html, /id="monitoringEmptyTitle"[^>]*>Waiting for telemetry</);
  assert.match(html, /id="monitoringEmptyContext"[^>]*>Connect ESP32 to begin monitoring\.<\/p>/);
  assert.match(html, /id="monitoringData"[^>]*hidden/);
  const monitoring = html.match(/id="monitoringData"[^]*?<\/div>\s*<div id="resultSummaryCards"/);
  assert.ok(monitoring, 'monitoringData must contain toolbar and both chart canvases');
  for (const required of ['chartToolbar', 'liveChart', 'luxChart', 'zoomHint']) assert.match(monitoring[0], new RegExp(`id="${required}"`));
});

test('real monitoring visibility helper keeps cached samples visible on backend loss', () => {
  const h = visibilityHarness();
  h.context.renderMonitoringVisibility(false, 'IDLE', true);
  assert.equal(h.get('monitoringEmpty').hidden, false);
  assert.equal(h.get('monitoringData').hidden, true);
  assert.equal(h.get('monitoringEmptyTitle').textContent, 'Waiting for telemetry');
  assert.equal(h.get('monitoringEmptyContext').textContent, 'Connect ESP32 to begin monitoring.');

  h.context.renderMonitoringVisibility(false, 'RUNNING', false);
  assert.equal(h.get('monitoringEmptyTitle').textContent, 'Monitoring unavailable');
  assert.match(h.get('monitoringEmptyContext').textContent, /backend connection/);

  h.context.renderMonitoringVisibility(true, 'RUNNING', false);
  assert.equal(h.get('monitoringEmpty').hidden, true);
  assert.equal(h.get('monitoringData').hidden, false, 'cached valid readings remain visible');
  assert.equal(h.get('resetZoomButton').hidden, false);
  assert.equal(h.get('resetZoomButton').disabled, true, 'reset remains unavailable until a zoom occurs');
});

test('idle has a concise ready state while run and terminal states expose the phase stepper', () => {
  assert.match(html,/id="phaseReady"[^>]*>NOT READY.*ESP32 disconnected/);
  const h = visibilityHarness();
  h.context.renderPhaseVisibility('IDLE');
  assert.equal(h.get('phaseReady').hidden, false);
  assert.equal(h.get('phaseStepper').hidden, true);
  for (const state of ['RUNNING', 'STOPPING', 'DONE', 'ABORTED']) {
    h.context.renderPhaseVisibility(state);
    assert.equal(h.get('phaseReady').hidden, true, state);
    assert.equal(h.get('phaseStepper').hidden, false, state);
  }
});

test('scientific controls are grouped by Range and Series with a compact reset', () => {
  const toolbar = html.match(/id="chartToolbar"[^]*?<\/div>\s*<div class="chart-container"/);
  assert.ok(toolbar, 'chart toolbar missing');
  assert.match(toolbar[0], /class="chart-control-group(?: monitoring-view-group)?"[^>]*>\s*<legend>View<\/legend>/);
  for (const view of ['temperature','illuminance','both']) assert.match(toolbar[0], new RegExp(`data-view="${view}"`));
  assert.match(html, /id="telemetryNotice"[^>]*role="status"[^>]*hidden/);
  assert.match(html, /function renderTelemetryOverlay\([^]*?notice\.hidden=kind==='live'\|\|kind==='none'/);
  assert.match(html, /function setMonitoringView\([^]*?data-view/);
  assert.match(toolbar[0], /class="chart-control-group"[^>]*>\s*<legend>Series<\/legend>/);
  assert.match(toolbar[0], /id="resetZoomButton"[^>]*hidden[^>]*disabled/);
  for (const id of ['toggleIR', 'toggleTC', 'toggleLux', 'toggleSetpoint']) assert.match(toolbar[0], new RegExp(`id="${id}"`));
});

test('control panel uses paired fields, a sticky action, and progressive mode controls', () => {
  assert.match(html, /class="form-pair"[^]*?id="duration"[^]*?id="cycles"/);
  assert.match(html, /class="form-pair"[^]*?id="targetLux"[^]*?id="interval"/);
  assert.match(html, /class="control-action-bar"[^]*?Review &amp; start experiment/);
  for (const id of ['panelNormal', 'panelFixed', 'panelPlateau']) assert.match(html, new RegExp(`id="${id}" class="mode-tab-panel( active)?`));
  assert.match(html, /class="mode-tabs"[^]*role="tablist"/);
  for (const legend of ['Experiment','Experiment mode','Illumination &amp; acquisition','Safety']) assert.match(html, new RegExp(`<legend>${legend}<\\/legend>`));
  for (const id of ['illuminationFieldset','safetyFieldset']) {
    assert.match(html, new RegExp(`id="${id}"[^>]*data-expanded="false"`));
    assert.match(html, new RegExp(`id="${id}"[^]*?aria-controls="[^"]+"`));
  }
  assert.match(html, /content\.hidden=!expanded/);
  assert.match(html, /var expanded=fieldset\.dataset&&fieldset\.dataset\.expanded==='true'/);
});

test('responsive laboratory layout uses a wide sticky panel without horizontal overflow', () => {
  assert.match(html, /grid-template-columns:\s*minmax\(0,\s*1fr\)\s+clamp\(340px,\s*min\(30vw,\s*540px\),\s*540px\)/);
  assert.match(html, /\.right-col\s*\{[^}]*position:\s*sticky[^}]*top:/);
  // Control panel scrolls naturally; no artificial max-height to prevent form/button overlap
  assert.doesNotMatch(html, /\.right-col\s*\{[^}]*max-height:\s*calc\(100vh/s, 'desktop control should not have constrained height');
  assert.match(html, /@media\s*\(max-width:\s*900px\)[^]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(html, /dashboard-grid\[data-ui-state="IDLE"\][^}]*grid-template-areas:\s*"control"\s*"monitor"/);
  assert.match(html, /@media\s*\(max-width:\s*600px\)[^]*\.form-pair\s*\{[^}]*grid-template-columns:\s*1fr/);
  assert.match(html, /overflow-x:\s*hidden/);
});

test('PC shell is uncapped and uses the full available desktop width', () => {
  assert.match(html, /\.page-shell\s*\{[^}]*width:\s*100%[^}]*max-width:\s*none[^}]*margin:\s*0/);
  assert.doesNotMatch(html, /\.page-shell\s*\{[^}]*max-width:\s*1440px/);
  // Fluid 4-tier system: wide desktop uses clamp in TIER 1
  assert.match(html, /@media\s*\(min-width:\s*1360px\)\s*and\s*\(min-height:\s*800px\)[^]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+clamp\(420px,\s*min\(28vw,\s*580px\),\s*580px\)/);
});

test('large desktop control panel uses named section areas and natural capped height', () => {
  const large = html.match(/@media\s*\(min-width:\s*1360px\)\s*and\s*\(min-height:\s*800px\)\s*\{[^]*?\n\s*\}/)?.[0] || html;
  assert.match(large, /grid-template-columns:\s*minmax\(0,\s*1fr\)\s+clamp\(420px,\s*min\(28vw,\s*580px\),\s*580px\)/);
  assert.match(large, /grid-template-areas:\s*"primary"\s*"secondary"\s*"summary"\s*"action"/);
  assert.match(large, /\.control-card\s*\{[^}]*flex:\s*0\s+1\s+auto[^}]*max-height:\s*calc\(100%\s*-\s*70px\)[^}]*overflow-y:\s*auto/);
  assert.match(large, /\.setup-column-primary\s*\{[^}]*grid-area:\s*primary/);
  assert.match(large, /\.setup-column-secondary\s*\{[^}]*grid-area:\s*secondary/);
  assert.match(large, /#systemLogCard\s*\{[^}]*flex:\s*0\s+0\s+auto[^}]*margin:\s*0/);
  const short = html.match(/@media\s*\(min-width:\s*901px\)\s*and\s*\(max-height:\s*799px\)\s*\{[\s\S]*?\n\s*\}/)?.[0] || html;
  assert.match(short, /\.page-shell\s*\{[^}]*height:\s*calc\(100dvh\s*-\s*16px\)[^}]*display:\s*flex[^}]*flex-direction:\s*column/);
  assert.match(short, /\.dashboard-grid\s*\{[^}]*flex:\s*1\s+1\s+auto[^}]*grid-template-rows:\s*minmax\(0,1fr\)[^}]*height:\s*auto/);
  assert.match(short, /\.left-col\s*\{[^}]*min-height:\s*0[^}]*overflow-y:\s*auto/);
  assert.match(html, /\.system-log-card\[data-collapsed="true"\]\s+\.system-log-content\s*\{\s*display:none/);
});

test('History and calibration are header utilities, not experiment-form actions', () => {
  const header = html.match(/<header class="instrument-header"[^]*?<\/header>/)?.[0] || '';
  assert.ok(header.includes('class="instrument-utilities"'));
  assert.ok(header.includes('aria-label="Instrument utilities"'));
  assert.ok(header.includes('href="/history"'));
  assert.ok(header.includes('href="/static/calibration.html"'));
  assert.equal((html.match(/class="btn-history"/g) || []).length, 0);
});

test('chart zoom callbacks are nested where chartjs-plugin-zoom executes them', () => {
  const configs = [];
  const reset = { dataset: {}, disabled: true };
  function Chart(_context, config) {
    configs.push(config);
    return { data: config.data, options: config.options };
  }
  const document = {
    getElementById(id) { return id === 'resetZoomButton' ? reset : { getContext() { return {}; } }; },
    querySelectorAll() { return []; }
  };
  const context = { Chart, document, chartZoomActive: false };
  vm.createContext(context);
  vm.runInContext('var chart, luxChart; var currentTheme="light"; function applyChartTheme(){}', context);
  vm.runInContext(extractFunction('setZoomResetAvailable'), context);
  vm.runInContext(extractFunction('setChartZoomActive'), context);
  vm.runInContext(extractFunction('applyChannelVisibility'), context);
  vm.runInContext(extractFunction('initChart'), context);
  context.initChart();
  const zoomPlugin = configs[0].options.plugins.zoom;
  assert.equal(typeof zoomPlugin.pan.onPanComplete, 'function');
  assert.equal(typeof zoomPlugin.zoom.onZoomComplete, 'function');
  assert.equal(zoomPlugin.onPanComplete, undefined);
  assert.equal(zoomPlugin.onZoomComplete, undefined);
  zoomPlugin.pan.onPanComplete();
  assert.equal(context.chartZoomActive, true);
  assert.equal(reset.disabled, false);
  assert.equal(reset.dataset.zoomed, 'true');
  context.setChartZoomActive(false);
  zoomPlugin.zoom.onZoomComplete();
  assert.equal(context.chartZoomActive, true);
  assert.equal(reset.disabled, false);
});

function chartViewHarness() {
  const rangeButtons = ['live', '1m', '5m', 'all'].map(window => ({
    dataset: { window }, attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    getAttribute(name) { return this.attributes[name]; }
  }));
  const reset = { dataset: {}, disabled: true };
  const document = {
    getElementById(id) { if (id === 'resetZoomButton') return reset; return { value: 'NORMAL_CYCLIC' }; },
    querySelectorAll(selector) { return selector === '[data-window]' ? rangeButtons : []; }
  };
  const chart = {
    data: { datasets: Array.from({ length: 7 }, () => ({ data: [] })) },
    options: { plugins: {}, scales: { x: { min: 41, max: 43 } } },
    updates: 0, resets: 0,
    update() { this.updates += 1; }, resetZoom() { this.resets += 1; }
  };
  const luxChart = {
    data: { datasets: [{ data: [] }, { data: [] }] },
    options: { scales: { x: { min: 41, max: 43 } } },
    updates: 0, resets: 0,
    update() { this.updates += 1; }, resetZoom() { this.resets += 1; }
  };
  const context = {
    document, chart, luxChart, chartWindow: 'live', chartZoomActive: true, activeMode: null,
    scientificSeries: { samples: [{ x: 0, ir: 20, tc: 21, lux: 100 }, { x: 100, ir: 30, tc: 31, lux: 200 }] },
    selectScientificView(buffer) { return buffer.samples; },
    pointData(view, key) { return view.filter(point => point[key] != null).map(point => ({ x: point.x, y: point[key] })); },
    derivePhaseRegions() { return []; },
    chartDomain(view) { return { min: view[0].x, max: view.at(-1).x }; },
    valueOf() { return 'NORMAL_CYCLIC'; }
  };
  vm.createContext(context);
  return { context, chart, luxChart, reset, rangeButtons };
}

test('active user zoom survives chart data refresh and Reset zoom restores the selected range', () => {
  const h = chartViewHarness();
  for (const name of ['setZoomResetAvailable', 'setChartZoomActive', 'applyChartView', 'resetZoom']) {
    vm.runInContext(extractFunction(name), h.context);
  }
  h.context.applyChartView();
  assert.deepEqual([h.chart.options.scales.x.min, h.chart.options.scales.x.max], [41, 43]);
  assert.deepEqual([h.luxChart.options.scales.x.min, h.luxChart.options.scales.x.max], [41, 43]);
  assert.equal(h.chart.data.datasets[0].data.length, 2, 'telemetry data still refreshes while zoomed');

  h.context.resetZoom();
  assert.equal(h.context.chartZoomActive, false);
  assert.equal(h.chart.resets, 1);
  assert.equal(h.luxChart.resets, 1);
  assert.deepEqual([h.chart.options.scales.x.min, h.chart.options.scales.x.max], [0, 100]);
  assert.equal(h.reset.disabled, true);
  assert.equal(h.reset.dataset.zoomed, 'false');
});

test('range selection is a single-choice aria state and clears an active zoom', () => {
  const toolbar = html.match(/id="chartToolbar"[^]*?<\/div>\s*<div class="chart-container"/)[0];
  const rangeButtons = [...toolbar.matchAll(/<button\b([^>]*data-window="([^"]+)"[^>]*)>/g)];
  assert.deepEqual(rangeButtons.map(match => [match[2], /aria-pressed="true"/.test(match[1])]), [
    ['live', true], ['1m', false], ['5m', false], ['all', false]
  ]);

  const h = chartViewHarness();
  for (const name of ['setZoomResetAvailable', 'setChartZoomActive', 'applyChartView', 'selectChartWindow']) {
    vm.runInContext(extractFunction(name), h.context);
  }
  h.context.selectChartWindow('5m');
  assert.equal(h.context.chartWindow, '5m');
  assert.equal(h.context.chartZoomActive, false);
  assert.equal(h.chart.resets, 1);
  assert.equal(h.luxChart.resets, 1);
  assert.deepEqual(h.rangeButtons.map(button => button.getAttribute('aria-pressed')), ['false', 'false', 'true', 'false']);
  assert.equal(h.reset.disabled, true);
});

test('terminal UI state remains authoritative when cached IDLE telemetry arrives', () => {
  const phaseStepper = { innerHTML: '' };
  const document = { getElementById(id) { return id === 'phaseStepper' ? phaseStepper : { value: 'NORMAL_CYCLIC' }; } };
  const context = { document, isRunning: false, activeMode: 'NORMAL_CYCLIC', terminalUiState: 'ABORTED', stateMap: { 15: 'ABORTED' } };
  vm.createContext(context);
  for (const name of ['valueOf', 'resolveActiveMode', 'getPhaseModel', 'getPhaseStep', 'phaseInfo', 'renderPhaseStepper', 'updateStateIndicator']) {
    vm.runInContext(extractFunction(name), context);
  }
  assert.equal(context.phaseInfo(15, 'NORMAL_CYCLIC').label, 'Aborted');
  context.updateStateIndicator(0);
  assert.match(phaseStepper.innerHTML, /Current: Aborted/);
  assert.doesNotMatch(phaseStepper.innerHTML, /Current: Ready/);

  context.terminalUiState = 'DONE';
  context.updateStateIndicator(0);
  assert.match(phaseStepper.innerHTML, /Current: Complete/);
  assert.doesNotMatch(phaseStepper.innerHTML, /Current: Ready/);
  assert.match(inline, /15:\s*"ABORTED"/);
});

test('every setup label is explicitly associated with its existing control', () => {
  const setup = html.match(/<div id="setupForm">([^]*?)<div id="runOverview"/)[1];
  const controlIds = new Set([...setup.matchAll(/<(?:input|select)\b[^>]*id="([^"]+)"/g)].map(match => match[1]));
  const labels = [...setup.matchAll(/<label\b([^>]*)>/g)];
  assert.ok(labels.length > 0);
  let matched = 0;
  for (const [, attributes] of labels) {
    const association = attributes.match(/\bfor="([^"]+)"/);
    assert.ok(association, `label lacks for attribute: <label${attributes}>`);
    assert.ok(controlIds.has(association[1]), `label targets missing control: ${association[1]}`);
    if (controlIds.has(association[1])) matched += 1;
  }
  assert.ok(matched >= controlIds.size - 1, 'all visible controls have explicit labels (hidden experimentMode select may lack one)');
});

test('opening a modal isolates the entire page shell and the hidden badge is not live', () => {
  const attributes = new Map();
  const shell = {
    inert: false,
    setAttribute(name, value) { attributes.set(name, value); },
    removeAttribute(name) { attributes.delete(name); }
  };
  const stopModal = { hidden: true };
  const confirmStop = { focusCalled: false, focus() { this.focusCalled = true; } };
  const opener = { focusCalled: false, focus() { this.focusCalled = true; } };
  const document = {
    activeElement: opener,
    getElementById(id) { return id === 'stopModal' ? stopModal : confirmStop; },
    querySelector(selector) { assert.equal(selector, '.page-shell'); return shell; }
  };
  const context = { document, stopModalOpener: null };
  vm.createContext(context);
  for (const name of ['setPageModalIsolation', 'openStopModal', 'closeStopModal']) {
    vm.runInContext(extractFunction(name), context);
  }
  context.openStopModal();
  assert.equal(stopModal.hidden, false);
  assert.equal(attributes.get('aria-hidden'), 'true');
  assert.equal(shell.inert, true);
  assert.equal(confirmStop.focusCalled, true);
  context.closeStopModal();
  assert.equal(stopModal.hidden, true);
  assert.equal(attributes.has('aria-hidden'), false);
  assert.equal(shell.inert, false);
  assert.equal(opener.focusCalled, true);

  const hiddenBadge = html.match(/<span id="statusBadge"[^>]*>/)[0];
  assert.doesNotMatch(hiddenBadge, /aria-live/);
  for (const name of ['openReviewModal', 'closeReviewModal', 'confirmReviewedStart']) {
    assert.match(extractFunction(name), /setPageModalIsolation\(/, `${name} must isolate or restore the page shell`);
  }
});
