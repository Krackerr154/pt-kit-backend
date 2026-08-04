const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');
const py=fs.readFileSync('app/main.py','utf8');
function extract(name){const m=html.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(m,'missing '+name);return m[0];}
const ctx={Number};vm.createContext(ctx);
vm.runInContext(extract('getArchiveBadgeModel'),ctx);

// 3.1 three header zones with named grid areas
const header=html.match(/<header class="instrument-header"[^]*?<\/header>/)[0];
assert(/class="header-grid"/.test(header),'header uses the grid shell');
assert(/class="header-brand"/.test(header),'brand zone exists');
const brand=header.match(/class="header-brand"[^]*?instrument-status/)[0];
assert(brand.includes('instrument-title'),'brand carries the title');
assert(brand.includes('id="healthCluster"'),'brand carries the health pills');
assert(header.indexOf('header-brand')<header.indexOf('instrument-status'),'brand precedes live status');
assert(header.indexOf('instrument-status')<header.indexOf('instrument-utilities'),'status precedes utilities');
assert(/grid-template-areas:"brand status utilities"/.test(html),'wide grid names all three zones');
assert(/grid-template-areas:"brand overflow" "status status"/.test(html),'narrow grid stacks status and swaps in overflow');

// overflow menu keeps both utilities reachable at narrow widths
assert(/id="utilitiesMenuBtn"[^>]*aria-haspopup="menu"/.test(header),'overflow button announces a menu');
assert(/id="utilitiesMenu"[^>]*role="menu"[^>]*hidden/.test(header),'menu starts hidden');
const menu=header.match(/id="utilitiesMenu"[^]*?<\/div>/)[0];
assert(menu.includes('href="/history"')&&menu.includes('href="/static/calibration.html"'),'menu links both utilities');

// 3.2 archive count badge
const badge=c=>{const m=ctx.getArchiveBadgeModel(c);return {visible:m.visible,text:m.text}};
assert.deepStrictEqual(badge(3),{visible:true,text:'3'});
assert.deepStrictEqual(badge(0),{visible:false,text:''});
assert.deepStrictEqual(badge('abc'),{visible:false,text:''});
assert.deepStrictEqual(badge(null),{visible:false,text:''});
assert(/id="archiveCount"[^>]*hidden/.test(header),'header badge starts hidden');
assert(/id="archiveCountMenu"[^>]*hidden/.test(header),'menu badge starts hidden');
assert(html.includes("fetch('/api/archive/count')"),'count fetched on page load');
assert(py.includes('@app.get("/api/archive/count")'),'backend exposes the count endpoint');
console.log('Header navigation (zones + overflow menu + archive badge): PASS');
