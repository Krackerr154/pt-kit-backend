const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');

// Extract the full 7.1/7.2 block (model functions, checklist renderer, wizard controller, state vars).
const start=html.indexOf('function getChecklistModel');
const end=html.indexOf('function handleCalWizardKeydown');
assert(start>0&&end>start,'wizard block found');
const block=html.slice(start,end);

function mkEl(){const el={className:'',textContent:'',hidden:false,disabled:false,children:[],attrs:{},style:{},
    setAttribute(k,v){this.attrs[k]=String(v);},getAttribute(k){return k in this.attrs?this.attrs[k]:null;},
    appendChild(c){this.children.push(c);},focus(){this.focused=true;}};
    let html='';Object.defineProperty(el,'innerHTML',{get:()=>html,set:v=>{html=v;if(v==='')el.children.length=0;}});
    return el;}
const els={};
const ctx={
    document:{
        getElementById:(id)=>els[id]||(els[id]=mkEl()),
        createElement:()=>mkEl(),
    },
    Number,String,Date,JSON,Promise,Array,Object,
    lastEsp32State:'connected',
    fetchQueue:[],
    fetch:null, // installed below
    setInterval:()=>1, clearInterval:()=>{},
    setTimeout:(fn)=>{fn();return 0;},
    setPageModalIsolation:()=>{}, toggleUtilitiesMenu:()=>{},
};
ctx.fetch=(url,opts)=>{const r=ctx.fetchQueue.shift();assert(r,'unexpected fetch '+url);r.url=url;r.opts=opts;return Promise.resolve({ok:true,json:()=>Promise.resolve(r.body)});};
vm.createContext(ctx);
vm.runInContext(block,ctx);
const flush=()=>new Promise(r=>setImmediate(r));

// ---------- 7.2 checklist model ----------
const good=ctx.getChecklistModel({sample_name:'MOF-1',max_temp:120,illumination_mode:'TARGET_LUX'},'connected','Target lux (1000 lx)');
assert.strictEqual(good.length,4,'four checklist items');
assert.strictEqual(good.map(i=>i.key).join(','),'device,sample,safety,illumination');
assert(good.every(i=>i.ok),'all items pass for a valid setup');
assert.strictEqual(good[2].detail,'Cutoff at 120 °C');
const bad=ctx.getChecklistModel({sample_name:'  ',max_temp:30,illumination_mode:''},'disconnected','');
assert(bad.every(i=>!i.ok),'every item flags when setup is missing');
assert.strictEqual(bad[1].detail,'No sample name entered');
assert.strictEqual(bad[0].detail,'Waiting for device');

// ---------- 7.2 checklist renderer ----------
ctx.renderChecklist(bad);
const list=els['reviewChecklist'];
assert.strictEqual(list.children.length,4,'renderer emits one row per item');
assert.strictEqual(list.children[0].className,'missing');
assert.strictEqual(list.children[0].children[0].textContent,'⚠','missing items are flagged');
ctx.renderChecklist(good);
assert.strictEqual(els['reviewChecklist'].children[0].className,'ok');
assert.strictEqual(els['reviewChecklist'].children[0].children[0].textContent,'✓','passing items are auto-checked');

// ---------- 7.1 step readiness (skipping prevention) ----------
assert.strictEqual(ctx.getCalStepReadiness('prepare',{connected:false}),false,'prepare blocked while disconnected');
assert.strictEqual(ctx.getCalStepReadiness('prepare',{connected:true}),true);
assert.strictEqual(ctx.getCalStepReadiness('zero',{bareLux:null}),false,'zero blocked until measured');
assert.strictEqual(ctx.getCalStepReadiness('zero',{bareLux:25000}),true);
assert.strictEqual(ctx.getCalStepReadiness('reference',{correctedMax:null}),false,'reference blocked until verified');
assert.strictEqual(ctx.getCalStepReadiness('reference',{correctedMax:55000}),true);
assert.strictEqual(ctx.getCalStepReadiness('confirm',{}),true,'confirm always reachable once prior gates passed');
const v0=ctx.getCalWizardView('prepare',{connected:true});
assert(v0.isFirst&&!v0.isLast&&v0.nextLabel==='Next'&&v0.index===0);
const v3=ctx.getCalWizardView('confirm',{});
assert(v3.isLast&&v3.nextLabel==='Finish'&&v3.index===3);
assert.strictEqual(ctx.getCalWizardView('bogus',{}).index,0,'unknown step falls back to prepare');
assert.strictEqual(ctx.formatCalLux(1234.5),'1235');
assert.strictEqual(ctx.formatCalLux(null),'--');
assert.strictEqual(ctx.formatCalLux('abc'),'--');

// ---------- 7.1 wizard rendering + navigation ----------
ctx.renderCalWizard();
assert.strictEqual(els['calDot0'].className,'cal-dot active');
assert.strictEqual(els['calDot1'].className,'cal-dot');
assert.strictEqual(els['calStep-prepare'].hidden,false);
assert.strictEqual(els['calStep-zero'].hidden,true,'only the current panel is visible');
assert.strictEqual(els['calWizardProgress'].attrs['aria-valuenow'],'1','progressbar tracks the step');
assert.strictEqual(els['calWizBack'].disabled,true,'Back disabled on the first step');
assert.strictEqual(els['calWizNext'].disabled,false,'Next enabled when the device is connected');
ctx.calWizardNext();
assert.strictEqual(ctx.calWizardState.step,'zero');
assert.strictEqual(els['calStep-zero'].hidden,false);
assert.strictEqual(els['calDot0'].className,'cal-dot done');
assert.strictEqual(els['calDot0'].textContent,'✓');
assert.strictEqual(els['calWizNext'].disabled,true,'Next blocked until the zero point is measured');
ctx.calWizardNext();
assert.strictEqual(ctx.calWizardState.step,'zero','cannot skip past an incomplete step');
ctx.calWizardBack();
assert.strictEqual(ctx.calWizardState.step,'prepare','Back returns to the previous step');
ctx.calWizardNext();

// ---------- 7.1 measurement flow against mocked API ----------
(async()=>{
    // zero point
    ctx.fetchQueue.push({body:{status:'calibrating',phase:'bare'}},{body:{state:{phase:'bare_running',bare_lux:null,taped_lux:null,factor:null},config:{}}});
    ctx.startCalWizardMeasure('bare');
    await flush();await flush();
    assert.strictEqual(ctx.calWizardState.measuring,'bare');
    ctx.fetchQueue.push({body:{state:{phase:'bare_done',bare_lux:25000,taped_lux:null,factor:null},config:{}}});
    ctx.pollCalWizardStatus();
    await flush();
    assert.strictEqual(ctx.calWizardState.bareLux,25000,'zero point recorded');
    assert.strictEqual(ctx.calWizardState.measuring,null);
    assert.strictEqual(els['calWizNext'].disabled,false,'zero step complete unlocks Next');
    assert.strictEqual(els['calWizStatusZero'].textContent,'Zero point recorded: 25000 lx.');
    ctx.calWizardNext();
    assert.strictEqual(ctx.calWizardState.step,'reference');
    assert.strictEqual(els['calMeasureFull'].disabled,true,'full-power verification locked until the tape reading');

    // taped reading
    ctx.fetchQueue.push({body:{status:'calibrating',phase:'tape'}},{body:{state:{phase:'tape_running',bare_lux:null,taped_lux:null,factor:null},config:{}}});
    ctx.startCalWizardMeasure('tape');
    await flush();await flush();
    ctx.fetchQueue.push({body:{state:{phase:'tape_done',bare_lux:25000,taped_lux:5000,factor:5},config:{}}});
    ctx.pollCalWizardStatus();
    await flush();
    assert.strictEqual(ctx.calWizardState.factor,5);
    assert.strictEqual(els['calMeasureFull'].disabled,false,'tape reading unlocks full-power verification');

    // full-power verification
    ctx.fetchQueue.push({body:{status:'calibrating',phase:'full'}},{body:{state:{phase:'full_running',bare_lux:null,taped_lux:null,factor:null},config:{}}});
    ctx.startCalWizardMeasure('full');
    await flush();await flush();
    ctx.fetchQueue.push({body:{state:{phase:'done',bare_lux:25000,taped_lux:5000,factor:5},config:{max_hardware_lux:55000,cal_timestamp:1754300000}}});
    ctx.pollCalWizardStatus();
    await flush();
    assert.strictEqual(ctx.calWizardState.correctedMax,55000);
    assert.strictEqual(ctx.calWizardState.savedAt,1754300000);
    assert.strictEqual(els['calWizNext'].disabled,false,'reference complete unlocks Next');
    ctx.calWizardNext();
    assert.strictEqual(ctx.calWizardState.step,'confirm');
    assert.strictEqual(els['calWizNext'].textContent,'Finish');
    const rows=els['calWizSummary'].children;
    assert.strictEqual(rows.length,4,'summary lists every calibration value');
    assert.strictEqual(rows[0].children[1].textContent,'25000 lx');
    assert.strictEqual(rows[2].children[1].textContent,'5.00 ×');
    assert.strictEqual(rows[3].children[1].textContent,'55000 lx');
    assert(els['calWizSaved'].textContent.startsWith('Saved by the instrument on'),'save confirmation shown');

    // Finish closes the wizard and restores state
    ctx.calWizardNext();
    assert.strictEqual(els['calWizardModal'].hidden,true,'Finish closes the wizard');

    // failed measurement re-enables the buttons
    ctx.fetchQueue.push({body:{active_experiment:null,recent_data:[{current_lux:1200}]}});
    ctx.openCalWizard();
    ctx.calWizardNext();
    ctx.fetch=()=>Promise.reject(new Error('offline'));
    ctx.startCalWizardMeasure('bare');
    await flush();await flush();
    assert.strictEqual(ctx.calWizardState.measuring,null,'failed request clears the busy state');
    assert.strictEqual(els['calMeasureZero'].disabled,false);
    assert.strictEqual(els['calWizStatusZero'].textContent,'Could not reach the instrument. Try again.');
    ctx.closeCalWizard(false);

    // ---------- HTML / ARIA assertions ----------
    assert(/id="calWizardModal"[^>]*hidden><div class="modal" role="dialog" aria-modal="true" aria-labelledby="calWizardTitle"/.test(html),'wizard is a labelled modal dialog');
    assert(/id="calWizardProgress"[^>]*role="progressbar"[^>]*aria-valuemax="4"/.test(html),'progress indicator exposes 4 steps');
    assert((html.match(/class="cal-dot/g)||[]).length===4,'four progress dots');
    assert(html.indexOf('calStep-prepare')<html.indexOf('calStep-zero')&&html.indexOf('calStep-zero')<html.indexOf('calStep-reference')&&html.indexOf('calStep-reference')<html.indexOf('calStep-confirm'),'steps render in order');
    assert(/id="calMeasureFull"[^>]*disabled/.test(html),'full-power verification starts disabled');
    assert(html.indexOf('id="reviewChecklist"')>html.indexOf('id="reviewModal"')&&html.indexOf('id="reviewChecklist"')<html.indexOf('id="reviewDetails"'),'checklist sits at the top of the review modal');
    assert(html.includes('renderChecklist(getChecklistModel(values,lastEsp32State'),'review modal renders the checklist on open');
    assert((html.match(/onclick="openCalWizard\(\);return false;"/g)||[]).length===2,'both utility links open the wizard');
    assert(block.includes('closeCalWizard(true)'),'Escape layer can close the wizard');

    console.log('Calibration wizard & pre-experiment checklist: PASS');
})().catch(e=>{console.error(e);process.exit(1);});
