const fs = require('fs');
const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const html = fs.readFileSync('app/static/index.html', 'utf8');
const inline = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].at(-1)[1];

function harness() {
  const elements = new Map();
  function el(id='') {
    const queryChild=elLeaf();
    return {id, value: id === 'experimentMode' ? 'NORMAL_CYCLIC' : '', innerText:'', textContent:'', innerHTML:'', hidden:false, disabled:false,
      style:{display:'none'}, className:'', children:[], cells:[elLeaf(),elLeaf(),elLeaf(),elLeaf(),elLeaf()],
      classList:{add(){},remove(){},toggle(){}}, appendChild(c){this.children.push(c);return c}, append(...c){this.children.push(...c)}, replaceChildren(...c){this.children=c},
      querySelector(){return queryChild}, focus(){}, addEventListener(){}, getContext(){return {}}, setAttribute(){}, removeAttribute(){}};
  }
  function elLeaf(){return {innerText:'',textContent:'',innerHTML:'',style:{},className:'',focus(){},removeAttribute(){},setAttribute(){}}}
  const document = {getElementById(id){if(!elements.has(id)) elements.set(id,el(id)); return elements.get(id)}, querySelector(){return elLeaf()},
    createElement(tag){return el(tag)}, createTextNode(text){return {textContent:text}}, addEventListener(){}};
  class Chart {
    static register() {}
    constructor(_context,config){
      this.data=config.data; this.options=config.options; this.ctx={save(){},restore(){},fillRect(){}};
      this.scales={x:{getPixelForValue:value=>value}}; this.chartArea={top:0,bottom:100};
    }
    update(){} destroy(){} resetZoom(){}
  }
  const fetchQueue=[];
  const context={document,Chart,console,Date,Math,JSON,Number,parseInt,parseFloat,Promise,
    fetch: (...args)=>(args[0]==='/api/get_config'||args[0]==='/api/archive/count')?Promise.resolve({ok:true,status:200,json:async()=>({})}):(assert.ok(fetchQueue.length,'unexpected fetch '+args[0]),Promise.resolve(fetchQueue.shift())),
    setInterval(){return 1},clearInterval(){},setTimeout(fn){fn();return 1},clearTimeout(){},alert(){}};
  context.window=context;
  vm.createContext(context); vm.runInContext(inline,context,{filename:'index.inline.js'});
  return {context,elements,queue(response){fetchQueue.push(response)}, response(ok,status,body){return {ok,status,json:async()=>body}}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('current_status HTTP 500 uses disconnected handling and preserves readings', async()=>{
  const h=harness(), c=h.context;
  c.document.getElementById('valIR').innerText='41.0 °C'; c.document.getElementById('valTC').innerText='40.0 °C';
  h.queue(h.response(false,500,{active_experiment:{status:'WAITING',id:9},recent_data:[{ir_temp:99,tc_temp:99,current_lux:9,total_time:9,state_code:2,cycle_num:1}]}));
  c.updateStatus(); await tick(); await tick();
  assert.equal(h.elements.get('connStatus').textContent,'🔴 ESP32 disconnected');
  assert.equal(h.elements.get('valIR').innerText,'41.0 °C'); assert.equal(h.elements.get('valTC').innerText,'40.0 °C');
  assert.notEqual(h.elements.get('connStatus').textContent,'🟢 ESP32 connected');
});

test('real updateStatus completes an active run when the backend has already cleared active_experiment', async()=>{
  const h=harness(), c=h.context;
  c.currentExpId=91; c.activeMode='FIXED_TEMPERATURE'; c.setUIState('RUNNING');
  h.queue(h.response(true,200,{active_experiment:null,recent_data:[{
    ir_temp:42,tc_temp:41,current_lux:900,total_time:120,state_code:5,cycle_num:3,temp_setpoint:40
  }]}));
  c.updateStatus(); await tick(); await tick();

  assert.equal(c.terminalUiState,'DONE');
  assert.equal(c.isRunning,false);
  assert.equal(h.elements.get('statusBadge').innerText,'COMPLETED');
  assert.equal(h.elements.get('setupForm').style.display,'none','setup must not reopen after completion');
  assert.equal(h.elements.get('finishedPanel').style.display,'block','terminal result actions must be exposed');
  assert.equal(h.elements.get('downloadLink').href,'/api/export/91','completed run retains its export authority');
  assert.match(h.elements.get('cycleInfo').innerText,/Cycle: 3 \| Phase: DONE/);
  assert.match(h.elements.get('modeProgress').textContent,/Mode: FIXED TEMPERATURE.*Phase: DONE/,'terminal summary retains the completed run mode');
  assert.match(h.elements.get('phaseStepper').innerHTML,/Current: Complete/);
  assert.match(html,/id="finishedPanel"[^]*?id="downloadLink"[^]*?NEW EXPERIMENT/,'finished result exposes export and new-run actions');
});

test('real updateStatus keeps abort cycle and mode summary authoritative over cached idle telemetry', async()=>{
  const h=harness(), c=h.context;
  c.currentExpId=92; c.activeMode='FIXED_TEMPERATURE'; c.setUIState('RUNNING');
  h.queue(h.response(true,200,{active_experiment:{id:92,status:'WAITING',mode:'FIXED_TEMPERATURE',target_temperature:40},recent_data:[{
    ir_temp:47,tc_temp:46,current_lux:850,total_time:32,state_code:15,cycle_num:2,temp_setpoint:40
  }]}));
  c.updateStatus(); await tick(); await tick();

  assert.equal(c.terminalUiState,'ABORTED');
  const terminalCycle=h.elements.get('cycleInfo').innerText;
  const terminalMode=h.elements.get('modeProgress').textContent;
  assert.match(terminalCycle,/Cycle: 2 \| Phase: ABORTED/);
  assert.match(terminalMode,/Mode: FIXED TEMPERATURE.*Phase: ABORTED/);

  h.queue(h.response(true,200,{active_experiment:null,recent_data:[{
    ir_temp:30,tc_temp:29,current_lux:0,total_time:0,state_code:0,cycle_num:0,temp_setpoint:0
  }]}));
  c.updateStatus(); await tick(); await tick();

  assert.equal(c.terminalUiState,'ABORTED');
  assert.equal(h.elements.get('cycleInfo').innerText,terminalCycle);
  assert.equal(h.elements.get('modeProgress').textContent,terminalMode);
  assert.doesNotMatch(h.elements.get('cycleInfo').innerText,/Phase: IDLE/);
  assert.doesNotMatch(h.elements.get('modeProgress').textContent,/Phase: IDLE/);
});

test('terminal result survives cached telemetry and state 15 abort is idempotent', async()=>{
  const h=harness(), c=h.context; c.setUIState('ABORTED');
  const title=h.elements.get('finishedPanel').querySelector('div'); // fake returns stable only through state assertions below
  h.queue(h.response(true,200,{active_experiment:null,recent_data:[{ir_temp:41,tc_temp:40,current_lux:900,total_time:12,state_code:2,cycle_num:1}]}));
  c.updateStatus(); await tick(); await tick();
  assert.equal(h.elements.get('statusBadge').innerText,'ABORTED');
  assert.equal(h.elements.get('finishedPanel').style.display,'block');
  c.resetUI(); c.setUIState('DONE');
  h.queue(h.response(true,200,{active_experiment:null,recent_data:[{ir_temp:42,tc_temp:41,current_lux:901,total_time:13,state_code:15,cycle_num:1}]}));
  c.updateStatus(); await tick(); await tick();
  assert.equal(h.elements.get('statusBadge').innerText,'COMPLETED','later abort telemetry must not replace FINISHED');
  h.queue(h.response(true,200,{active_experiment:null,recent_data:[{ir_temp:42,tc_temp:41,current_lux:901,total_time:13,state_code:15,cycle_num:1}]}));
  c.updateStatus(); await tick(); await tick();
  assert.equal(h.elements.get('statusBadge').innerText,'COMPLETED','state 15 must not oscillate terminal result');
});

test('stop failure remains RUNNING; success aborts and exposes export', async()=>{
  const h=harness(), c=h.context; c.currentExpId=77; c.setUIState('RUNNING');
  h.queue(h.response(false,500,{detail:'relay failure'})); c.stopExperiment(); await tick(); await tick();
  assert.equal(c.isRunning,true); assert.equal(h.elements.get('statusBadge').innerText,'RUNNING');
  assert.equal(h.elements.get('finishedPanel').style.display,'none','failure must not imply lamp off/result');
  h.queue(h.response(true,200,{status:'stopped'})); c.stopExperiment(); await tick(); await tick();
  assert.equal(c.isRunning,false); assert.equal(h.elements.get('statusBadge').innerText,'ABORTED');
  assert.equal(h.elements.get('downloadLink').href,'/api/export/77');
});

test('terminal clears only on reset or accepted new start', async()=>{
  const h=harness(), c=h.context; c.setUIState('ABORTED'); c.setUIState('RUNNING');
  assert.equal(h.elements.get('statusBadge').innerText,'ABORTED','generic RUNNING cannot clear terminal');
  c.resetUI(); assert.equal(h.elements.get('statusBadge').innerText,'IDLE');
});

// Security/contract checks retained alongside the real-script harness.
test('stop response validation and safe log rendering',()=>{
  const h=harness(), c=h.context;
  assert.doesNotThrow(()=>c.validateStopResponse({ok:true,status:200},{status:'stopped'}));
  assert.throws(()=>c.validateStopResponse({ok:false,status:500},{status:'stopped'}));
  const logFn=html.match(/function log\([^]*?\n\}/)[0]; assert.ok(!/innerHTML/.test(logFn)&&/textContent/.test(logFn));
});
