const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');
const source=html.match(/function formatSensorValue\(value, digits, unit\) \{[\s\S]*?\n\}/)[0];
const ctx={}; vm.createContext(ctx); vm.runInContext(source,ctx);
assert.equal(ctx.formatSensorValue(23.45,1,'°C'),'23.4 °C');
for (const value of [null,undefined,NaN,Infinity,-Infinity,'not-a-number']) {
  assert.equal(ctx.formatSensorValue(value,1,'°C'),'-- °C');
  assert.equal(ctx.formatSensorValue(value,0,'lx'),'-- lx');
}
console.log('frontend invalid sensor formatting: PASS');