const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');
function extract(name){const m=html.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(m,'missing '+name);return m[0];}
const ctx={Math,Number,String};vm.createContext(ctx);
vm.runInContext(extract('getReadinessModel'),ctx);
vm.runInContext(extract('computePlannedDurationSeconds'),ctx);
vm.runInContext(extract('formatPlannedDuration'),ctx);

// 1.1 ESP32-aware readiness
const ready=ctx.getReadinessModel('connected');
assert.equal(ready.bannerText,'Ready for experiment');
assert.equal(ready.startEnabled,true);
assert.equal(ready.hint,'');
for(const state of ['disconnected','stale']){
    const off=ctx.getReadinessModel(state);
    assert.equal(off.deviceReady,false,state);
    assert.equal(off.bannerText,'Waiting for device',state);
    assert.equal(off.startEnabled,false,state);
    assert.equal(off.hint,'Connect ESP32 to begin',state);
}

// 1.2 TOTAL TIME computation
assert.equal(ctx.computePlannedDurationSeconds({mode:'NORMAL_CYCLIC',duration:60,cycles:5}),300);
assert.equal(ctx.computePlannedDurationSeconds({mode:'FIXED_TEMPERATURE',hold_minutes:10}),600);
assert.equal(ctx.computePlannedDurationSeconds({mode:'NATURAL_PLATEAU',max_discovery_minutes:60,confirmation_s:60,hold_minutes:10}),4260);
assert.equal(ctx.computePlannedDurationSeconds({mode:'NORMAL_CYCLIC',duration:NaN,cycles:NaN}),0);
assert.equal(ctx.computePlannedDurationSeconds(null),0);
assert.equal(ctx.formatPlannedDuration(300),'05:00');
assert.equal(ctx.formatPlannedDuration(600),'10:00');
assert.equal(ctx.formatPlannedDuration(4260),'1:11:00');
assert.equal(ctx.formatPlannedDuration(0),'00:00');

// HTML wiring for the readiness gate
assert(/id="phaseReady"/.test(html),'readiness banner exists');
assert(/id="startHint"[^>]*hidden/.test(html),'start hint begins hidden');
assert(/id="reviewStartBtn"/.test(html),'desktop start button is addressable');
assert(/id="mobileReviewBtn"/.test(html),'mobile start button is addressable');
console.log('State integrity (readiness gate + planned total time): PASS');
