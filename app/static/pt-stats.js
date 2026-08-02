/*
 * PTStats — pure statistics module for PT-Kit's history/analysis view.
 *
 * Design goals (Phase 3):
 *  - Zero DOM dependency: every function takes plain arrays/objects and returns
 *    plain objects. This file can be loaded in a browser <script> tag OR
 *    required() from Node for unit testing without any mocking.
 *  - Single source of truth for state filtering, regression, slope stats,
 *    time-grid interpolation, and the Welch t-test used by history.html.
 *  - No use of `jStat` here except through an injectable interface, so tests
 *    can run without the CDN dependency. jStat is only used (via the caller)
 *    for the t-distribution CDF/inverse; a normal-approximation fallback is
 *    provided so the module still degrades gracefully without it.
 *
 * Exposed as:
 *   - `window.PTStats` in browsers (via <script src="pt-stats.js">)
 *   - `module.exports` in Node (CommonJS) for the test suite
 */
(function (root, factory) {
    var mod = factory();
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = mod; // Node / CommonJS (tests)
    }
    if (root) {
        root.PTStats = mod; // Browser global
    }
})(typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : null), function () {
    'use strict';

    // --- Shared state-filtering helpers (single source of truth) ---

    // "Plottable" rows: everything except PRE_HEAT/IDLE/DONE. Used for overlay + stats bands.
    function isPlottableRow(row, kState) {
        if (!kState) return true;
        var state = row[kState];
        if (!state) return true; // Keep if no state info
        var s = String(state).toUpperCase();
        return !s.includes('PRE') && !s.includes('IDLE') && !s.includes('DONE');
    }

    // "Heating" rows: strictly the HEATING phase, excluding PRE_HEAT. Used for slope/regression fits.
    function isHeatingRow(row, kState) {
        if (!kState) return false; // without state info we cannot isolate heating-only rows
        var state = row[kState];
        if (!state) return false;
        var s = String(state).toUpperCase();
        return s === 'HEATING' || (s.includes('HEAT') && !s.includes('PRE'));
    }

    function filterPlottable(rows, kState) { return kState ? rows.filter(function (d) { return isPlottableRow(d, kState); }) : rows; }
    function filterHeating(rows, kState) { return kState ? rows.filter(function (d) { return isHeatingRow(d, kState); }) : rows; }

    function groupDataByCycle(data, keyCycle) {
        var c = {};
        data.forEach(function (d) {
            var k = d[keyCycle];
            if (k !== undefined) { if (!c[k]) c[k] = []; c[k].push(d); }
        });
        return c;
    }

    // --- Time-grid interpolation ---

    // Linear interpolation of a (relative-time, value) series onto a common time grid.
    // Points need not be pre-sorted. Returns null for grid times outside [minT, maxT].
    function interpolateToGrid(points, gridTimes) {
        if (!points.length) return gridTimes.map(function () { return null; });
        var sorted = points.slice().sort(function (a, b) { return a.t - b.t; });
        var out = []; var j = 0;
        gridTimes.forEach(function (gt) {
            if (gt < sorted[0].t || gt > sorted[sorted.length - 1].t) { out.push(null); return; }
            while (j < sorted.length - 2 && sorted[j + 1].t < gt) j++;
            var p0 = sorted[j], p1 = sorted[Math.min(j + 1, sorted.length - 1)];
            if (p1.t === p0.t) { out.push(p0.v); return; }
            var frac = (gt - p0.t) / (p1.t - p0.t);
            out.push(p0.v + frac * (p1.v - p0.v));
        });
        return out;
    }

    // Builds a shared relative-time grid spanning the union of all cycles' relative-time ranges,
    // stepped at `stepS` seconds (default 1s), so per-cycle series with slightly different
    // sampling times can be aligned before computing mean/SD bands.
    function buildCommonTimeGrid(cycleSeriesList, stepS) {
        stepS = stepS || 1;
        var maxEnd = 0;
        cycleSeriesList.forEach(function (series) {
            if (series.length) maxEnd = Math.max(maxEnd, series[series.length - 1].t);
        });
        var grid = [];
        for (var t = 0; t <= maxEnd; t += stepS) grid.push(t);
        return grid;
    }

    // --- Regression / slope statistics ---

    // Per-cycle slope mean/SD for the heating phase of `kTemp` (e.g. IR or TC temperature).
    // Returns { mean, sd, n, slopes } where n = number of cycles that yielded a usable slope
    // (heatingData.length > 2), and slopes is the raw per-cycle slope array (for t-tests / CI).
    function calculateSlopeStats(data, kCyc, kState, kTime, kTemp) {
        var cycles = groupDataByCycle(data, kCyc);
        var slopes = [];
        Object.values(cycles).forEach(function (cData) {
            var heatingData = filterHeating(cData, kState);
            if (heatingData.length > 2) {
                var n = heatingData.length, sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
                var startT = cData[0][kTime];
                heatingData.forEach(function (d) {
                    var x = d[kTime] - startT, y = parseFloat(d[kTemp]);
                    sumX += x; sumY += y; sumXY += (x * y); sumXX += (x * x);
                });
                var slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
                slopes.push(slope);
            }
        });
        var n = slopes.length;
        var mean = n > 0 ? slopes.reduce(function (a, b) { return a + b; }, 0) / n : 0;
        var variance = n > 1 ? slopes.reduce(function (a, b) { return a + Math.pow(b - mean, 2); }, 0) / (n - 1) : 0;
        return { mean: mean, sd: Math.sqrt(variance), n: n, slopes: slopes };
    }

    // Pooled linear regression across all cycles' heating-phase points (relative time vs kTemp).
    // Intended as a VISUAL GUIDE only — not the primary inferential statistic (see slope stats).
    function calculateLinearRegression(data, kCyc, kState, kTime, kTemp) {
        var cycles = groupDataByCycle(data, kCyc);
        var allPoints = [];
        Object.values(cycles).forEach(function (cData) {
            var startT = cData[0][kTime];
            var heatingData = filterHeating(cData, kState);
            heatingData.forEach(function (d) { allPoints.push({ x: d[kTime] - startT, y: parseFloat(d[kTemp]) }); });
        });
        if (allPoints.length < 2) return { slope: 0, intercept: 0, r2: 0, points: [], count: 0 };
        var n = allPoints.length, sumX = 0, sumY = 0, sumXY = 0, sumXX = 0, sumYY = 0;
        allPoints.forEach(function (p) { sumX += p.x; sumY += p.y; sumXY += (p.x * p.y); sumXX += (p.x * p.x); sumYY += (p.y * p.y); });
        var slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
        var intercept = (sumY - slope * sumX) / n;
        var r2 = Math.pow((n * sumXY - sumX * sumY), 2) / ((n * sumXX - sumX * sumX) * (n * sumYY - sumY * sumY));
        var minX = Math.min.apply(null, allPoints.map(function (p) { return p.x; }));
        var maxX = Math.max.apply(null, allPoints.map(function (p) { return p.x; }));
        return {
            slope: slope, intercept: intercept, r2: r2,
            points: [{ x: minX, y: slope * minX + intercept }, { x: maxX, y: slope * maxX + intercept }],
            count: Object.keys(cycles).length
        };
    }

    // --- Mean/SD bands over a common time grid (for overlay / advanced view) ---

    // Builds per-cycle (relative-time, value) series for kIR/kTC, filtered to plottable rows,
    // then interpolates each cycle onto a shared time grid before computing mean/upper/lower.
    function calculateStatistics(data, kCyc, kTime, kIR, kTC, kState) {
        var c = groupDataByCycle(data, kCyc);
        var irSeries = [], tcSeries = [];
        Object.values(c).forEach(function (cD) {
            var filteredData = filterPlottable(cD, kState);
            if (filteredData.length === 0) return;
            var sT = filteredData[0][kTime];
            var irPts = [], tcPts = [];
            filteredData.forEach(function (d) {
                var rT = d[kTime] - sT;
                irPts.push({ t: rT, v: parseFloat(d[kIR]) });
                tcPts.push({ t: rT, v: parseFloat(d[kTC]) });
            });
            irSeries.push(irPts); tcSeries.push(tcPts);
        });
        var grid = buildCommonTimeGrid(irSeries.concat(tcSeries), 1);

        function gS(seriesList) {
            var m = [], u = [], l = [];
            if (!grid.length) return { mean: m, upper: u, lower: l };
            var interpolated = seriesList.map(function (series) { return interpolateToGrid(series, grid); });
            grid.forEach(function (t, gi) {
                var vals = interpolated.map(function (series) { return series[gi]; }).filter(function (v) { return v !== null && Number.isFinite(v); });
                if (vals.length < 1) return;
                var av = vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
                var sd = Math.sqrt(vals.reduce(function (a, b) { return a + Math.pow(b - av, 2); }, 0) / vals.length);
                m.push({ x: t, y: av }); u.push({ x: t, y: av + sd }); l.push({ x: t, y: av - sd });
            });
            return { mean: m, upper: u, lower: l };
        }
        return { ir: gS(irSeries), tc: gS(tcSeries) };
    }

    // --- Inferential statistics ---

    // 95% CI half-width for the mean of per-cycle slopes: SD/sqrt(n) * t(0.975, n-1).
    // `studentTInv(p, df)` is injectable (e.g. jStat.studentt.inv) — falls back to the
    // z=1.96 normal approximation when not supplied, which is reasonable for n >= ~30
    // but should be treated as approximate for the small-n case typical of this instrument.
    function slopeCI95(stats, studentTInv) {
        if (!stats || stats.n < 2) return null;
        var se = stats.sd / Math.sqrt(stats.n);
        var tCrit = (typeof studentTInv === 'function') ? studentTInv(0.975, stats.n - 1) : 1.96;
        return se * tCrit;
    }

    // Welch's two-sample t-test (unequal variances assumed). Returns {t, df, p} or null if
    // not computable (n<2 in either sample, or zero pooled variance).
    // `studentTCdf(x, df)` is injectable (e.g. jStat.studentt.cdf) — p is null without it,
    // since there is no reliable closed-form fallback for the t-CDF.
    //
    // IMPORTANT: jStat 1.9.6's own `ttest()` has NO two-independent-samples code path (verified
    // by reading its source). Calling jStat.ttest(A, B, sides) silently falls through to a
    // one-sample-vs-array branch and produces meaningless output. Do not use it for this purpose.
    function welchTTest(A, B, studentTCdf) {
        var nA = A.length, nB = B.length;
        if (nA < 2 || nB < 2) return null;
        var meanA = A.reduce(function (a, b) { return a + b; }, 0) / nA;
        var meanB = B.reduce(function (a, b) { return a + b; }, 0) / nB;
        var varA = A.reduce(function (a, b) { return a + Math.pow(b - meanA, 2); }, 0) / (nA - 1);
        var varB = B.reduce(function (a, b) { return a + Math.pow(b - meanB, 2); }, 0) / (nB - 1);
        var seA = varA / nA, seB = varB / nB;
        var se = Math.sqrt(seA + seB);
        if (se === 0) return null;
        var t = (meanA - meanB) / se;
        var df = Math.pow(seA + seB, 2) / ((Math.pow(seA, 2) / (nA - 1)) + (Math.pow(seB, 2) / (nB - 1)));
        var p = (typeof studentTCdf === 'function') ? 2 * studentTCdf(-Math.abs(t), df) : null;
        return { t: t, df: df, p: p };
    }

    return {
        isPlottableRow: isPlottableRow,
        isHeatingRow: isHeatingRow,
        filterPlottable: filterPlottable,
        filterHeating: filterHeating,
        groupDataByCycle: groupDataByCycle,
        interpolateToGrid: interpolateToGrid,
        buildCommonTimeGrid: buildCommonTimeGrid,
        calculateSlopeStats: calculateSlopeStats,
        calculateLinearRegression: calculateLinearRegression,
        calculateStatistics: calculateStatistics,
        slopeCI95: slopeCI95,
        welchTTest: welchTTest
    };
});
