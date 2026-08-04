const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = fs.readFileSync('app/static/history.html', 'utf8');

assert.match(html, /<meta charset="UTF-8">/);
assert.match(html, /--ink:#17212b;\s*--muted:#52606d;\s*--line:#d9e0e7;/);
assert.match(html, /body\s*\{[^}]*background:#eef2f5/);
assert.match(html, /class="page-shell"/);
assert.match(html, /class="instrument-header"/);
assert.match(html, /class="instrument-title"><h1>PT-Kit<\/h1><span>Thermal photostability instrument<\/span>/);
assert.match(html, /class="instrument-utility-link" href="\/">← Dashboard<\/a>/);
assert.match(html, /class="instrument-current" aria-current="page">📁 Data archive<\/span>/);
assert.match(html, /class="archive-layout"/);
assert.match(html, /grid-template-columns:clamp\(260px,24vw,320px\) minmax\(0,1fr\)/);
assert.match(html, /id="analysisEmpty" class="analysis-empty"/);
assert.match(html, /id="analysisWorkspace" hidden/);
assert.match(html, /id="compareBtn"[^>]*disabled/);
assert.match(html, /id="analysisBtn"[^>]*disabled/);
assert.match(html, /id="csvBtn"[^>]*disabled/);
assert.match(html, /function updateSelectionActions\(\)/);
assert.match(html, /analysisBtn'\)\.disabled=n!==1/);
assert.match(html, /function showAnalysisWorkspace\(\)/);
assert.match(html, /@media \(max-width:900px\)/);
assert.doesNotMatch(html, /max-width:\s*1100px/);
assert.doesNotMatch(html, /\.btn-exp\s*\{\s*background:\s*#6f42c1/);

console.log('archive dashboard theme contract: PASS');
