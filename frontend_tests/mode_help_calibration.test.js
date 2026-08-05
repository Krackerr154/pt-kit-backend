const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');
const cal=fs.readFileSync('app/static/calibration.html','utf8');
function extractFrom(src,name){const m=src.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(m,'missing '+name);return m[0];}

// 4.1 mode help tooltip
const ctx={document:{getElementById:()=>null},Number};vm.createContext(ctx);
const helpDict=html.match(/var MODE_HELP = \{[^]*?\};/)[0];
vm.runInContext(helpDict+'\n'+extractFrom(html,'getModeHelpText'),ctx);
for(const mode of ['NORMAL_CYCLIC','FIXED_TEMPERATURE','NATURAL_PLATEAU']){
    const t=ctx.getModeHelpText(mode);
    assert(t.length>40,mode+' help text is substantive');
}
assert.notEqual(ctx.getModeHelpText('NORMAL_CYCLIC'),ctx.getModeHelpText('FIXED_TEMPERATURE'),'texts differ per mode');
assert.equal(ctx.getModeHelpText('BOGUS'),ctx.getModeHelpText('NORMAL_CYCLIC'),'unknown mode falls back');
assert(/id="modeHelpBtn"[^>]*aria-expanded="false"[^>]*aria-controls="modeHelpTip"/.test(html),'help button wired to tooltip');
assert(/id="modeHelpTip"[^>]*role="tooltip"[^>]*hidden/.test(html),'tooltip starts hidden');
assert(html.indexOf('modeHelpBtn')<html.indexOf('id="experimentMode"'),'help button sits beside the mode selector');
const umf=extractFrom(html,'updateModeFields');
assert(umf.includes('renderModeHelp()'),'mode changes refresh the tooltip text');
assert(/\.mode-summary \{ background:#eaf2fb;/.test(html),'mode summary has a tinted background');
assert(/addEventListener\('mouseenter'/.test(html)&&/addEventListener\('mouseleave'/.test(html),'hover opens and closes the tooltip');

// 4.2 last calibration date on the calibration page
assert(cal.includes('id="lastCalibrated"'),'calibration page has the date element');
const cctx={Date,parseFloat,isFinite};vm.createContext(cctx);
vm.runInContext(extractFrom(cal,'getLastCalibratedModel'),cctx);
const m1=cctx.getLastCalibratedModel({cal_timestamp:'1712000000'});
assert(m1.uncalibrated===false&&m1.text.startsWith('Last calibrated: '),'timestamp renders a date');
assert(!/NaN|Invalid/.test(m1.text),'date is valid');
for(const bad of [{},null,{cal_timestamp:'abc'},{cal_timestamp:'0'}]){
    const m=cctx.getLastCalibratedModel(bad);
    assert.strictEqual(m.text,'Not yet calibrated.');
    assert.strictEqual(m.uncalibrated,true);
}
assert(extractFrom(cal,'loadExistingConfig').includes('renderLastCalibrated(conf)'),'page load renders the date');
assert(extractFrom(cal,'onCalComplete').includes('renderLastCalibrated(config)'),'finishing calibration refreshes the date');
console.log('Mode help & calibration info: PASS');
