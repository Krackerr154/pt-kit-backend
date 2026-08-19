const fs=require('fs'),assert=require('assert'),vm=require('vm');
const html=fs.readFileSync('app/static/index.html','utf8');
function extract(name){const m=html.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(m,'missing '+name);return m[0];}
const ctx={String};vm.createContext(ctx);
vm.runInContext(extract('isUserRelevantLog'),ctx);
vm.runInContext(extract('getLogStatusSummary'),ctx);

// 2.2 collapsed System Log summary
assert.equal(ctx.getLogStatusSummary(null,'connected'),'System ready');
assert.equal(ctx.getLogStatusSummary(null,'disconnected'),'Device link unavailable');
assert.equal(ctx.getLogStatusSummary(null,'stale'),'Device link unavailable');
assert.equal(ctx.getLogStatusSummary('Experiment started! ID: 42','connected'),'Experiment started! ID: 42');
assert.equal(ctx.getLogStatusSummary('ESP32 disconnected — waiting for device','disconnected'),'Device link unavailable');

// relevance filter: internal chatter hidden, connection/experiment/error events surfaced
assert.equal(ctx.isUserRelevantLog('Syncing: Stopped remotely.'),false);
assert.equal(ctx.isUserRelevantLog('New data stream detected. Recording Started.'),false);
assert.equal(ctx.isUserRelevantLog('ESP32 connected'),true);
assert.equal(ctx.isUserRelevantLog('ESP32 disconnected — waiting for device'),true);
assert.equal(ctx.isUserRelevantLog('Experiment started! ID: 9'),true);
assert.equal(ctx.isUserRelevantLog('Stop failed: boom'),true);
assert.equal(ctx.isUserRelevantLog('Experiment Completed! Waiting for Arduino/ESP32 reset...'),true);

// 2.1 troubleshooting panel lives inside the monitoring empty state
const empty=html.match(/id="monitoringEmpty"[^]*?<\/details>/);
assert(empty,'troubleshooting panel must live inside the empty state');
assert(/<details id="troubleshootingPanel"/.test(empty[0]),'panel is a collapsible details element');
for(const hint of ['Check ESP32 power and USB connection','Verify the device is provisioned and on the same network','Restart the backend if the device was recently reconnected'])assert(empty[0].includes(hint),hint);
console.log('Empty-state guidance (troubleshooting + log summary): PASS');
