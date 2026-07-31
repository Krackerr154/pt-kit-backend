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
  class Chart { constructor(){this.data={labels:[],datasets:[{data:[]},{data:[]}]}} update(){} destroy(){} }
  const fetchQueue=[];
  const context={document,Chart,console,Date,Math,JSON,Number,parseInt,parseFloat,Promise,
    fetch: (...args)=>args[0]==='/api/get_config'?Promise.resolve({ok:true,status:200,json:async()=>({})}):(assert.ok(fetchQueue.length,'unexpected fetch '+args[0]),Promise.resolve(fetchQueue.shift())),
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
  assert.equal(h.elements.get('connStatus').innerText,'🔴 Backend disconnected');
  assert.equal(h.elements.get('valIR').innerText,'41.0 °C'); assert.equal(h.elements.get('valTC').innerText,'40.0 °C');
  assert.notEqual(h.elements.get('connStatus').innerText,'🟢 Connected');
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
