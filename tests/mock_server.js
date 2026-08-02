#!/usr/bin/env node
/*
 * Minimal static HTTP server for browser-testing history.html without touching the real
 * Postgres-backed backend. Serves app/static/* as-is, and fakes /api/experiments and
 * /api/experiment/{id} with synthetic multi-cycle data so we can exercise the real browser
 * code path (Chart.js, jStat, PTStats, DOM rendering, CSV export) end-to-end.
 *
 * This does NOT touch the project's Postgres database or app/main.py — read-only, local-only,
 * throwaway test harness. Kill with Ctrl+C or `kill <pid>`.
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const STATIC_DIR = path.join(__dirname, '..', 'app', 'static');
const PORT = process.env.PORT || 8934;

function makeCycle(cycleNum, opts) {
    opts = opts || {};
    var slope = opts.slope !== undefined ? opts.slope : 0.5;
    var intercept = opts.intercept !== undefined ? opts.intercept : 25;
    var nHeat = opts.nHeat || 20;
    var t0 = opts.t0 !== undefined ? opts.t0 : 0;
    var dt = opts.dt || 1;
    var jitter = opts.jitter || 0;
    var rows = [];
    var t = t0;
    for (var i = 0; i < 3; i++) { rows.push({ cycle_num: cycleNum, total_time: t, state_label: 'PRE_HEAT', ir_temp: intercept, tc_temp: intercept - 0.3 }); t += dt; }
    var heatStartT = t;
    for (var h = 0; h < nHeat; h++) {
        var relX = t - heatStartT;
        var noise = jitter ? (Math.random() - 0.5) * jitter : 0;
        var yIR = slope * relX + intercept + noise;
        var yTC = slope * relX + intercept - 0.3 + noise * 0.8;
        rows.push({ cycle_num: cycleNum, total_time: t, state_label: 'HEATING', ir_temp: yIR, tc_temp: yTC });
        t += dt;
    }
    var peak = slope * (nHeat - 1) + intercept;
    for (var c = 0; c < 5; c++) { rows.push({ cycle_num: cycleNum, total_time: t, state_label: 'COOLING', ir_temp: peak - c * 0.5, tc_temp: peak - 0.3 - c * 0.5 }); t += dt; }
    return rows;
}

function makeExperiment(id, opts) {
    opts = opts || {};
    var nCycles = opts.nCycles || 5;
    var data = [];
    var t = 0;
    for (var c = 1; c <= nCycles; c++) {
        var cRows = makeCycle(c, Object.assign({ t0: t, slope: opts.slope, intercept: opts.intercept, jitter: opts.jitter }, opts.perCycle ? opts.perCycle(c) : {}));
        data = data.concat(cRows);
        t = cRows[cRows.length - 1].total_time + 2; // gap between cycles
    }
    return data;
}

const EXPERIMENTS_META = [
    { id: 1, sample_name: 'CF_Ni-BDC_85-10-5_A', operator_name: 'Gerald', started_at: '2026-07-01T10:00:00Z', mode: 'NORMAL_CYCLIC' },
    { id: 2, sample_name: 'CF_Ni-BDC_85-10-5_B', operator_name: 'Gerald', started_at: '2026-07-02T10:00:00Z', mode: 'NORMAL_CYCLIC' },
];
const EXPERIMENT_DATA = {
    1: makeExperiment(1, { nCycles: 5, slope: 0.5, intercept: 25, jitter: 0.15 }),
    2: makeExperiment(2, { nCycles: 4, slope: 0.35, intercept: 24, jitter: 0.15 }),
};

const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json' };

const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/api/experiments') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify(EXPERIMENTS_META));
    }
    var m = url.pathname.match(/^\/api\/experiment\/(\d+)$/);
    if (m) {
        var id = Number(m[1]);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify(EXPERIMENT_DATA[id] || []));
    }
    // static files
    var reqPath = url.pathname === '/' ? '/history.html' : url.pathname.replace(/^\/static/, '');
    var filePath = path.join(STATIC_DIR, reqPath);
    if (!filePath.startsWith(STATIC_DIR)) { res.writeHead(403); return res.end('forbidden'); }
    fs.readFile(filePath, (err, data) => {
        if (err) { res.writeHead(404); return res.end('not found: ' + reqPath); }
        var ext = path.extname(filePath);
        res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
        res.end(data);
    });
});

server.listen(PORT, () => console.log(`Mock PT-Kit server on http://localhost:${PORT} (history.html at /)`));
