const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');
const names=['getPhaseModel','getPhaseStep','getHealthState','getRuntimeViewModel','formatRemainingHold'];
const ctx={}; vm.createContext(ctx);
for(const name of names){const m=html.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(m,`missing ${name}`);vm.runInContext(m[0],ctx);}
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.getPhaseModel('NORMAL_CYCLIC'))),['Ready','Pre-heat','Heating','Cooling','Stabilizing','Complete']);
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.getPhaseModel('FIXED_TEMPERATURE'))),['Ready','Ramp','Qualify','Hold','Complete']);
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.getPhaseModel('NATURAL_PLATEAU'))),['Ready','Heating','Confirm','Hold','Complete']);
assert.equal(ctx.getPhaseStep('FIXED_TEMPERATURE',10).current,2); assert.equal(ctx.getPhaseStep('NORMAL_CYCLIC',5).current,5);
assert.equal(ctx.getHealthState(true,2,true).state,'live'); assert.equal(ctx.getHealthState(true,5,true).state,'stale'); assert.equal(ctx.getHealthState(true,11,true).state,'offline'); assert.equal(ctx.getHealthState(false,1,true).state,'stale'); assert.equal(ctx.getHealthState(false,11,true).state,'offline'); assert.equal(ctx.getHealthState(true,null,true).state,'no-data'); assert.equal(ctx.getHealthState(true,1,false).state,'invalid');
assert.equal(ctx.getRuntimeViewModel('IDLE').showSetup,true); assert.equal(ctx.getRuntimeViewModel('RUNNING').showStop,true); assert.equal(ctx.getRuntimeViewModel('DONE').showResult,true); assert.equal(ctx.getRuntimeViewModel('ABORTED').aborted,true);
assert.equal(ctx.formatRemainingHold(125),'02:05'); assert.equal(ctx.formatRemainingHold(-4),'00:00'); assert.equal(ctx.formatRemainingHold(NaN),'--:--');
assert(html.includes('<meta charset="UTF-8">'),'UTF-8 declaration missing');
assert(/role="dialog"/.test(html)&&/aria-modal="true"/.test(html)&&/aria-labelledby="stopModalTitle"/.test(html));
assert(/id="stickyStop"/.test(html)&&/Stop now/.test(html)&&!/confirm\(/.test(html));
console.log('operational UX behavior: PASS');
