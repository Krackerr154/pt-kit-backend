/*
 * Unit tests for app/static/pt-stats.js — run with: node tests/js/pt-stats.test.js
 *
 * No test framework dependency (kept intentionally framework-free so it runs with
 * plain `node` in this environment). Each test is a function that throws on failure;
 * the runner at the bottom collects pass/fail counts and exits non-zero on any failure.
 */
const assert = require('assert');
const path = require('path');
const PTStats = require(path.join(__dirname, '..', '..', 'app', 'static', 'pt-stats.js'));

const results = [];
function test(name, fn) {
    try {
        fn();
        results.push({ name, ok: true });
    } catch (e) {
        results.push({ name, ok: false, error: e });
    }
}

function approxEqual(a, b, tol, msg) {
    tol = tol === undefined ? 1e-6 : tol;
    assert.ok(Math.abs(a - b) <= tol, (msg || '') + ` expected ${a} ≈ ${b} (tol ${tol})`);
}

// --- Fixtures: synthetic cycles with KNOWN slope/intercept so we can assert exact math ---

// One cycle: PRE_HEAT (2 rows, excluded from heating fit) + HEATING (n rows, exact linear ramp)
// + COOLING (2 rows, included in "plottable" but not "heating").
function makeCycle(cycleNum, opts) {
    opts = opts || {};
    var slope = opts.slope !== undefined ? opts.slope : 0.5; // deg C per second
    var intercept = opts.intercept !== undefined ? opts.intercept : 25;
    var nHeat = opts.nHeat || 6;
    var t0 = opts.t0 || 0;
    var dt = opts.dt || 1; // seconds between samples
    var noise = opts.noise || (() => 0);
    var rows = [];
    var t = t0;
    // PRE_HEAT rows (should be excluded from heating fit AND from "plottable" filter)
    for (var i = 0; i < 2; i++) {
        rows.push({ cycle_num: cycleNum, total_time: t, state_label: 'PRE_HEAT', ir_temp: intercept, tc_temp: intercept });
        t += dt;
    }
    // HEATING rows: exact line y = slope*x + intercept, x measured from filtered-data start
    var heatStartT = t;
    for (var h = 0; h < nHeat; h++) {
        var relX = (t - heatStartT);
        var y = slope * relX + intercept + noise(h);
        rows.push({ cycle_num: cycleNum, total_time: t, state_label: 'HEATING', ir_temp: y, tc_temp: y });
        t += dt;
    }
    // COOLING rows (plottable, not heating)
    for (var c = 0; c < 2; c++) {
        rows.push({ cycle_num: cycleNum, total_time: t, state_label: 'COOLING', ir_temp: intercept, tc_temp: intercept });
        t += dt;
    }
    return rows;
}

const kCyc = 'cycle_num', kState = 'state_label', kTime = 'total_time', kIR = 'ir_temp', kTC = 'tc_temp';

// === State filter tests ===

test('isPlottableRow excludes PRE_HEAT/IDLE/DONE, keeps HEATING/COOLING/STABILIZING', () => {
    assert.strictEqual(PTStats.isPlottableRow({ state_label: 'PRE_HEAT' }, kState), false);
    assert.strictEqual(PTStats.isPlottableRow({ state_label: 'IDLE' }, kState), false);
    assert.strictEqual(PTStats.isPlottableRow({ state_label: 'DONE' }, kState), false);
    assert.strictEqual(PTStats.isPlottableRow({ state_label: 'HEATING' }, kState), true);
    assert.strictEqual(PTStats.isPlottableRow({ state_label: 'COOLING' }, kState), true);
    assert.strictEqual(PTStats.isPlottableRow({ state_label: 'STABILIZING' }, kState), true);
    // no state column at all -> keep (can't filter what we can't see)
    assert.strictEqual(PTStats.isPlottableRow({}, null), true);
});

test('isHeatingRow matches HEATING exactly, excludes PRE_HEAT, excludes everything else', () => {
    assert.strictEqual(PTStats.isHeatingRow({ state_label: 'HEATING' }, kState), true);
    assert.strictEqual(PTStats.isHeatingRow({ state_label: 'PRE_HEAT' }, kState), false);
    assert.strictEqual(PTStats.isHeatingRow({ state_label: 'COOLING' }, kState), false);
    assert.strictEqual(PTStats.isHeatingRow({ state_label: 'HEATING_RAMP' }, kState), true); // contains HEAT, not PRE
    // without a state column we CANNOT claim a row is heating -> false (fail-safe)
    assert.strictEqual(PTStats.isHeatingRow({}, null), false);
});

test('filterHeating drops PRE_HEAT rows from a real cycle fixture', () => {
    var cycle = makeCycle(1, { nHeat: 6 });
    var heating = PTStats.filterHeating(cycle, kState);
    assert.strictEqual(heating.length, 6);
    heating.forEach(r => assert.strictEqual(r.state_label, 'HEATING'));
});

// === Regression / slope tests (exact linear fixture -> exact recovered slope) ===

test('calculateSlopeStats recovers the exact known slope on a noise-free single cycle', () => {
    var knownSlope = 0.5;
    var data = makeCycle(1, { slope: knownSlope, nHeat: 6 });
    var stats = PTStats.calculateSlopeStats(data, kCyc, kState, kTime, kIR);
    assert.strictEqual(stats.n, 1);
    approxEqual(stats.mean, knownSlope, 1e-9, 'recovered slope mismatch');
    approxEqual(stats.sd, 0, 1e-9, 'SD of single-cycle slope should be 0');
});

test('calculateSlopeStats: mean/SD across multiple cycles with different known slopes', () => {
    var slopes = [0.3, 0.5, 0.7];
    var data = [];
    slopes.forEach((s, i) => { data = data.concat(makeCycle(i + 1, { slope: s, nHeat: 8 })); });
    var stats = PTStats.calculateSlopeStats(data, kCyc, kState, kTime, kIR);
    assert.strictEqual(stats.n, 3);
    var expectedMean = (0.3 + 0.5 + 0.7) / 3;
    approxEqual(stats.mean, expectedMean, 1e-9);
    // sample SD (n-1 denominator) of [0.3, 0.5, 0.7] around mean 0.5 = sqrt(((0.2^2)*2)/2) = 0.2
    approxEqual(stats.sd, 0.2, 1e-6);
    assert.deepStrictEqual(stats.slopes.map(s => Math.round(s * 1000) / 1000), slopes);
});

test('calculateSlopeStats ignores cycles with <=2 heating points (insufficient for a fit)', () => {
    var goodCycle = makeCycle(1, { slope: 0.4, nHeat: 6 });
    var sparseCycle = makeCycle(2, { slope: 0.9, nHeat: 2 }); // only 2 heating rows -> excluded (needs >2)
    var stats = PTStats.calculateSlopeStats(goodCycle.concat(sparseCycle), kCyc, kState, kTime, kIR);
    assert.strictEqual(stats.n, 1, 'sparse cycle should not contribute a slope');
    approxEqual(stats.mean, 0.4, 1e-9);
});

test('calculateLinearRegression recovers exact slope and r2=1 on noise-free pooled data', () => {
    // NOTE: calculateLinearRegression measures x relative to each cycle's *entire* first row
    // (cData[0], typically PRE_HEAT), not relative to the heating phase's own start. With a
    // fixed-length PRE_HEAT block (2 rows here) preceding HEATING in every cycle, the recovered
    // intercept is the value the line would take at the cycle's absolute start (x=0), i.e.
    // knownIntercept - knownSlope * preHeatDurationS — NOT knownIntercept itself. This is
    // documented behavior of the pooled-regression "visual guide" fit, distinct from
    // calculateSlopeStats which fits within each cycle's own heating-relative time origin.
    var knownSlope = 0.5, knownIntercept = 25, preHeatRows = 2;
    var data = makeCycle(1, { slope: knownSlope, intercept: knownIntercept, nHeat: 6 })
        .concat(makeCycle(2, { slope: knownSlope, intercept: knownIntercept, nHeat: 6, t0: 100 }));
    var reg = PTStats.calculateLinearRegression(data, kCyc, kState, kTime, kIR);
    approxEqual(reg.slope, knownSlope, 1e-9);
    approxEqual(reg.intercept, knownIntercept - knownSlope * preHeatRows, 1e-6);
    approxEqual(reg.r2, 1, 1e-9, 'perfectly linear noise-free data should give r2=1');
    assert.strictEqual(reg.count, 2);
});

test('calculateLinearRegression r2 drops below 1 when noise is added', () => {
    var data = makeCycle(1, { slope: 0.5, nHeat: 8, noise: (h) => (h % 2 === 0 ? 0.3 : -0.3) });
    var reg = PTStats.calculateLinearRegression(data, kCyc, kState, kTime, kIR);
    assert.ok(reg.r2 < 1 && reg.r2 > 0, `expected 0 < r2 < 1, got ${reg.r2}`);
});

// === Time-grid interpolation tests ===

test('interpolateToGrid: exact hits return exact values, midpoints are linearly interpolated', () => {
    var points = [{ t: 0, v: 10 }, { t: 10, v: 20 }];
    var grid = [0, 5, 10];
    var out = PTStats.interpolateToGrid(points, grid);
    approxEqual(out[0], 10);
    approxEqual(out[1], 15); // midpoint of a straight line from 10 to 20
    approxEqual(out[2], 20);
});

test('interpolateToGrid: returns null outside the series time range', () => {
    var points = [{ t: 2, v: 100 }, { t: 4, v: 200 }];
    var grid = [0, 2, 3, 4, 6];
    var out = PTStats.interpolateToGrid(points, grid);
    assert.strictEqual(out[0], null); // before range
    approxEqual(out[1], 100);
    approxEqual(out[2], 150);
    approxEqual(out[3], 200);
    assert.strictEqual(out[4], null); // after range
});

test('interpolateToGrid: unsorted input points are handled correctly', () => {
    var points = [{ t: 10, v: 20 }, { t: 0, v: 10 }]; // deliberately out of order
    var out = PTStats.interpolateToGrid(points, [5]);
    approxEqual(out[0], 15);
});

test('buildCommonTimeGrid spans the union of series and steps at the given interval', () => {
    var seriesA = [{ t: 0, v: 1 }, { t: 5, v: 2 }];
    var seriesB = [{ t: 0, v: 1 }, { t: 8, v: 2 }];
    var grid = PTStats.buildCommonTimeGrid([seriesA, seriesB], 2);
    assert.deepStrictEqual(grid, [0, 2, 4, 6, 8]);
});

test('calculateStatistics produces mean bands that match manual interpolation on 2 misaligned cycles', () => {
    // Cycle 1 samples at t=0,1,2 (relative); Cycle 2 samples at t=0,2 (relative) — misaligned grids.
    // Both go through PRE_HEAT(excluded)+HEATING+COOLING so filterPlottable keeps HEATING+COOLING.
    var c1 = [
        { cycle_num: 1, total_time: 0, state_label: 'HEATING', ir_temp: 25, tc_temp: 25 },
        { cycle_num: 1, total_time: 1, state_label: 'HEATING', ir_temp: 26, tc_temp: 26 },
        { cycle_num: 1, total_time: 2, state_label: 'HEATING', ir_temp: 27, tc_temp: 27 },
    ];
    var c2 = [
        { cycle_num: 2, total_time: 0, state_label: 'HEATING', ir_temp: 30, tc_temp: 30 },
        { cycle_num: 2, total_time: 2, state_label: 'HEATING', ir_temp: 32, tc_temp: 32 },
    ];
    var stats = PTStats.calculateStatistics(c1.concat(c2), kCyc, kTime, kIR, kTC, kState);
    // grid = [0,1,2]; cycle2 interpolated at t=1 -> midpoint of 30,32 = 31
    // mean at t=0: (25+30)/2=27.5 ; t=1: (26+31)/2=28.5 ; t=2: (27+32)/2=29.5
    var meanAtT = {};
    stats.ir.mean.forEach(p => meanAtT[p.x] = p.y);
    approxEqual(meanAtT[0], 27.5, 1e-9);
    approxEqual(meanAtT[1], 28.5, 1e-9);
    approxEqual(meanAtT[2], 29.5, 1e-9);
});

// === Inferential statistics tests ===

test('slopeCI95 returns null for n<2, and a positive half-width for n>=2', () => {
    assert.strictEqual(PTStats.slopeCI95({ n: 1, sd: 0.1 }), null);
    assert.strictEqual(PTStats.slopeCI95(null), null);
    var ci = PTStats.slopeCI95({ n: 5, sd: 0.1 }, (p, df) => 2.776); // t(0.975, 4) ~ 2.776
    approxEqual(ci, (0.1 / Math.sqrt(5)) * 2.776, 1e-9);
});

test('slopeCI95 falls back to z=1.96 when no studentTInv is supplied', () => {
    var ci = PTStats.slopeCI95({ n: 10, sd: 0.2 });
    approxEqual(ci, (0.2 / Math.sqrt(10)) * 1.96, 1e-9);
});

test('welchTTest returns null when either sample has <2 points', () => {
    assert.strictEqual(PTStats.welchTTest([1], [1, 2, 3]), null);
    assert.strictEqual(PTStats.welchTTest([1, 2, 3], []), null);
});

test('welchTTest: identical samples give t=0 (or null se=0 short-circuit avoided) and near-zero effect', () => {
    var A = [0.5, 0.5, 0.5, 0.5];
    var B = [0.5, 0.5, 0.5, 0.5];
    // se = 0 because variance is 0 in both -> function returns null (degenerate variance),
    // which is the correct, honest behavior rather than fabricating a t-stat.
    var result = PTStats.welchTTest(A, B);
    assert.strictEqual(result, null);
});

test('welchTTest: clearly separated samples give a large |t| and (with a real CDF) a small p', () => {
    var A = [0.1, 0.12, 0.11, 0.13, 0.09];
    var B = [0.9, 0.88, 0.91, 0.89, 0.92];
    // Fake student-t CDF stand-in: for a well-separated case we just check |t| is large and
    // that a supplied CDF function is actually invoked with sensible arguments.
    var cdfCalls = [];
    var fakeCdf = (x, df) => { cdfCalls.push({ x, df }); return x < -3 ? 0.001 : 0.5; };
    var result = PTStats.welchTTest(A, B, fakeCdf);
    assert.ok(Math.abs(result.t) > 10, `expected large |t| for well-separated samples, got ${result.t}`);
    assert.ok(result.df > 0);
    assert.strictEqual(cdfCalls.length, 1);
    assert.ok(result.p !== null && result.p < 0.05);
});

test('welchTTest returns p=null when no CDF function is supplied (no fabricated p-value)', () => {
    var result = PTStats.welchTTest([0.1, 0.2, 0.3], [0.9, 0.8, 0.7]);
    assert.ok(result !== null);
    assert.strictEqual(result.p, null);
});

test('welchTTest matches a hand-computed reference value (regression fixture)', () => {
    // Hand-computed reference (Welch's t-test), values chosen to be simple to verify by hand:
    // A = [1,2,3], meanA=2, varA=1 (sample var, n-1=2) -> seA = 1/3
    // B = [4,6,8], meanB=6, varB=4 (sample var) -> seB = 4/3
    // se = sqrt(1/3+4/3) = sqrt(5/3); t = (2-6)/sqrt(5/3) = -4 / 1.29099... = -3.0983866...
    var A = [1, 2, 3], B = [4, 6, 8];
    var result = PTStats.welchTTest(A, B);
    approxEqual(result.t, -3.0983866769, 1e-6);
    // Welch-Satterthwaite df = (seA+seB)^2 / (seA^2/(nA-1) + seB^2/(nB-1))
    // seA=1/3, seB=4/3 -> (5/3)^2 / ((1/9)/2 + (16/9)/2) = (25/9) / (17/18) = 50/17 ≈ 2.9412
    approxEqual(result.df, 50 / 17, 1e-6);
});

// === Runner ===
let passed = 0, failed = 0;
results.forEach(r => {
    if (r.ok) { passed++; console.log(`  ok - ${r.name}`); }
    else { failed++; console.log(`  FAIL - ${r.name}`); console.log(`         ${r.error.message}`); }
});
console.log(`\n${passed} passed, ${failed} failed, ${results.length} total`);
if (failed > 0) process.exit(1);
