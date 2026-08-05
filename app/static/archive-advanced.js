// PT-Kit Data Archive — Phase 2-6 advanced analysis features
// Loaded by history.html after the main script.
// Depends on: PTStats (pt-stats.js), Chart.js, jStat, and history.html globals.
(function(){
'use strict';

// ---- CSS injection ----
var style = document.createElement('style');
style.textContent = '.extra-views-row{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:14px}.extra-views-row .toggle-btn{margin:0}.data-quality{display:flex;flex-wrap:wrap;gap:5px 10px;margin-bottom:12px;padding:8px 10px;border-radius:7px;background:#f4f7f9;font-size:.82rem}.dq-ok{color:#1e7e34}.dq-warn{color:#9a6700}.dq-bad{color:#ac1b1b}#batchStatsBox{display:none;background:#eef5fb;color:#173f67;border:1px solid #b6cbe0;padding:10px 12px;border-radius:7px;margin-bottom:10px;font-size:.9rem}';
document.head.appendChild(style);

// ---- HTML injection — gallery row + data quality + batch stats ----
function injectHTML() {
    var compareBox = document.getElementById('compareStatsBox');
    if (!compareBox) return;
    // batch stats box
    var batchBox = document.createElement('div');
    batchBox.id = 'batchStatsBox';
    // gallery row
    var gallery = document.createElement('div');
    gallery.className = 'extra-views-row';
    gallery.id = 'extraViews';
    gallery.style.display = 'none';
    gallery.innerHTML = '<span class="tool-label">Gallery</span> '+
        '<button class="toggle-btn" id="btnRate">Heating Rate</button> '+
        '<button class="toggle-btn" id="btnLux">Lux Profile</button> '+
        '<button class="toggle-btn" id="btnSensor">Sensor Cross</button> '+
        '<button class="toggle-btn" id="btnBatch">Batch Stats</button>';
    // data quality box
    var dq = document.createElement('div');
    dq.id = 'dataQualityBox';
    dq.className = 'data-quality';
    dq.style.display = 'none';
    // insert after compareStatsBox
    compareBox.parentNode.insertBefore(batchBox, compareBox.nextSibling);
    batchBox.parentNode.insertBefore(gallery, batchBox.nextSibling);
    gallery.parentNode.insertBefore(dq, gallery.nextSibling);
    // wire up gallery buttons
    ['Rate','Lux','Sensor','Batch'].forEach(function(v){
        var b = document.getElementById('btn'+v);
        if (b) b.addEventListener('click', function(){ switchView(v.toLowerCase()); });
    });
}
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectHTML);
} else {
    injectHTML();
}

// ---- Monkey-patch loadExpAnalysis to show gallery and render quality ----
var _origLoadExpAnalysis = window.loadExpAnalysis;
window.loadExpAnalysis = function() {
    var result = _origLoadExpAnalysis.apply(this, arguments);
    var ev = document.getElementById('extraViews');
    if (ev) ev.style.display = 'flex';
    return result;
};

// ---- renderDataQuality — called from loadExpAnalysis monkey-patch ----
window.renderDataQuality = function(rows) {
    var box = document.getElementById('dataQualityBox');
    if (!box || !rows || !rows.length) return;
    var kIR = window.getColumnName(rows[0], ['ir_temp','IR_Temp','ir']);
    var kTC = window.getColumnName(rows[0], ['tc_temp','TC_Temp','tc']);
    var kCyc = window.getColumnName(rows[0], ['cycle_num','Cycle','cycle']);
    var cycles = new Set(), irMissing=0, tcMissing=0;
    for (var i=0;i<rows.length;i++){
        var r=rows[i];
        if (r[kIR]===undefined||r[kIR]===null) irMissing++;
        if (r[kTC]===undefined||r[kTC]===null) tcMissing++;
        var c=parseInt(r[kCyc]); if (Number.isFinite(c)&&c>=0) cycles.add(c);
    }
    var irArr=[],tcArr=[];
    rows.forEach(function(r){var ir=parseFloat(r[kIR]);if(Number.isFinite(ir))irArr.push(ir);var tc=parseFloat(r[kTC]);if(Number.isFinite(tc))tcArr.push(tc);});
    var irMean=irArr.length?(irArr.reduce(function(a,b){return a+b;},0)/irArr.length):null;
    var tcMean=tcArr.length?(tcArr.reduce(function(a,b){return a+b;},0)/tcArr.length):null;
    var offset=(irMean!==null&&tcMean!==null)?Math.abs(irMean-tcMean):null;
    var parts=[];
    parts.push({l:'Points',v:rows.length,c:'dq-ok'});
    parts.push({l:'Cycles',v:cycles.size,c:cycles.size>0?'dq-ok':'dq-warn'});
    if(irMissing||tcMissing)parts.push({l:'Missing',v:'IR '+irMissing+' TC '+tcMissing,c:'dq-warn'});
    else parts.push({l:'Completeness',v:'Full',c:'dq-ok'});
    if(offset!==null){
        parts.push({l:'IR-TC offset',v:offset.toFixed(2)+' °C',c:offset<2?'dq-ok':offset<5?'dq-warn':'dq-bad'});
        parts.push({l:'Sensor',v:offset<1?'Good agreement':offset<3?'Moderate offset':'Large offset',c:offset<1?'dq-ok':offset<3?'dq-warn':'dq-bad'});
    }
    box.style.display='flex';
    box.innerHTML=parts.map(function(p){return '<span class="'+p.c+'"><b>'+p.l+':</b> '+p.v+'</span>';}).join(' · ');
};

// ---- Patch switchView to support gallery modes ----
var _origSwitchView = window.switchView;
window.switchView = function(mode) {
    // gallery modes
    if (mode==='rate'||mode==='lux'||mode==='sensor'||mode==='batch') {
        // hide stats box for gallery modes
        var sb = document.getElementById('statsBox');
        if (sb) sb.style.display = 'none';
        // update button state
        ['btnExpanded','btnOverlay','btnAdvanced','btnRate','btnLux','btnSensor','btnBatch'].forEach(function(id){
            var b=document.getElementById(id); if(b) b.className='toggle-btn';
        });
        var bm={'expanded':'btnExpanded','overlay':'btnOverlay','advanced':'btnAdvanced','rate':'btnRate','lux':'btnLux','sensor':'btnSensor','batch':'btnBatch'};
        var act=document.getElementById(bm[mode]); if(act) act.className='toggle-btn active';

        if (!window.currentData || !window.currentData.length) return;
        var kIR=window.getColumnName(window.currentData[0],['ir_temp','IR_Temp','ir']);
        var kTC=window.getColumnName(window.currentData[0],['tc_temp','TC_Temp','tc']);
        var kCyc=window.getColumnName(window.currentData[0],['cycle_num','Cycle','cycle']);
        var kTime=window.getColumnName(window.currentData[0],['total_time','TotalTime','time']);
        var kState=window.getColumnName(window.currentData[0],['state_label','State','state']);
        var ds=[], xLabel='', title='';

        if (mode==='rate') {
            var cycles=PTStats.groupDataByCycle(window.currentData,kCyc);
            xLabel='Temperature (°C)';title='Heating Rate vs Temperature';
            Object.keys(cycles).forEach(function(cNum){
                var cData=PTStats.filterPlottable(cycles[cNum],kState);
                if(cData.length<3)return;
                var rates=[];
                for(var i=1;i<cData.length;i++){
                    var dt=cData[i][kTime]-cData[i-1][kTime];
                    if(dt>0)rates.push({x:parseFloat(cData[i][kIR]),y:(parseFloat(cData[i][kIR])-parseFloat(cData[i-1][kIR]))/dt});
                }
                ds.push({label:'C'+cNum+' IR Rate',data:rates,borderColor:'rgba(0,123,255,0.5)',pointRadius:1,tension:0.2,showLine:false});
            });
        } else if (mode==='lux') {
            xLabel='Time (s)';title='Lux Profile - '+window.currentExpName;
            var luxData=window.currentData.map(function(d){var v=parseFloat(d.current_lux||d.lux||0);return Number.isFinite(v)?{x:d[kTime],y:v}:null;}).filter(Boolean);
            ds.push({label:'Lux',data:luxData,borderColor:'#e0a63c',backgroundColor:'rgba(224,166,60,0.15)',pointRadius:0,tension:0.3});
        } else if (mode==='sensor') {
            xLabel='IR Temp (°C)';title='Sensor Cross-Plot - '+window.currentExpName;
            var cross=[];
            window.currentData.forEach(function(d){var ir=parseFloat(d[kIR]),tc=parseFloat(d[kTC]);if(Number.isFinite(ir)&&Number.isFinite(tc))cross.push({x:ir,y:tc});});
            ds.push({label:'IR vs TC',data:cross,borderColor:'#6610f2',pointRadius:1,showLine:false});
        } else if (mode==='batch') {
            xLabel='Experiment Date';title='Batch Trend - IR Slope Over Time';
            var bb=document.getElementById('batchStatsBox');if(bb){bb.style.display='block';bb.innerHTML='Computing slopes across '+window.allExperiments.length+' experiments...';}
            var loaded=0,batchSlopes=[];
            window.allExperiments.forEach(function(exp){
                fetch('/api/experiment/'+exp.id).then(function(r){return r.json();}).then(function(d){
                    loaded++;
                    var rows=Array.isArray(d)?d:(d.data||d.readings||[]);if(!rows||!rows.length)return;
                    var kIr=window.getColumnName(rows[0],['ir_temp','IR_Temp','ir']);
                    var kCy=window.getColumnName(rows[0],['cycle_num','Cycle','cycle']);
                    var kTi=window.getColumnName(rows[0],['total_time','TotalTime','time']);
                    var kSt=window.getColumnName(rows[0],['state_label','State','state']);
                    var ss=PTStats.calculateSlopeStats(rows,kCy,kSt,kTi,kIr);
                    if(ss.n>0)batchSlopes.push({x:new Date(exp.started_at||0).getTime(),y:ss.mean,name:exp.sample_name||'#'+exp.id});
                    if(loaded===window.allExperiments.length){
                        var bp=batchSlopes.filter(function(b){return Number.isFinite(b.x)&&Number.isFinite(b.y);});
                        bp.sort(function(a,b){return a.x-b.x;});
                        var bds=[];bp.forEach(function(b){bds.push({label:b.name,data:[{x:b.x,y:b.y}],borderColor:window.COLORS[bds.length%window.COLORS.length],pointRadius:4,showLine:false});});
                        window.drawChart(bds,title,xLabel);
                        var st='<b>'+bp.length+' experiments with slope data</b>';
                        if(bp.length>1){var sl=bp.map(function(b){return b.y;});var mn=sl.reduce(function(a,b){return a+b;},0)/sl.length;var sd=Math.sqrt(sl.reduce(function(a,b){return a+Math.pow(b-mn,2);},0)/sl.length);st+='<br>Mean slope: '+mn.toFixed(4)+' °C/s · SD: ±'+sd.toFixed(4);}
                        if(bb)bb.innerHTML=st;
                    }
                });
            });
            return;
        }
        window.drawChart(ds, title, xLabel);
        return;
    }
    // Pass through to original for expanded/overlay/advanced
    var result = _origSwitchView.apply(this, arguments);
    // After advanced view loads, add full-report button
    if (mode==='advanced') {
        setTimeout(function(){
            var sb=document.getElementById('statsBox');
            if(sb&&sb.innerHTML.indexOf('Full report')===-1){
                sb.innerHTML=sb.innerHTML.replace('</button></div>','</button><button onclick="exportExperimentReport()" style="min-height:32px;margin-left:4px;padding:4px 10px;border-radius:6px;border:1px solid #8090a0;background:#fff;cursor:pointer;font-size:.8rem;">📄 Full report (CSV)</button></div>');
            }
        }, 200);
    }
    // Render data quality
    if (window.currentData && window.currentData.length) {
        window.renderDataQuality(window.currentData);
    }
    return result;
};

// ---- exportExperimentReport — one-click full CSV report ----
window.exportExperimentReport = function() {
    if(!window.currentData||!window.currentData.length)return window.notify&&window.notify('Open an experiment analysis first.');
    var kIR=window.getColumnName(window.currentData[0],['ir_temp','IR_Temp','ir']);
    var kTC=window.getColumnName(window.currentData[0],['tc_temp','TC_Temp','tc']);
    var kCyc=window.getColumnName(window.currentData[0],['cycle_num','Cycle','cycle']);
    var kTime=window.getColumnName(window.currentData[0],['total_time','TotalTime','time']);
    var kState=window.getColumnName(window.currentData[0],['state_label','State','state']);
    var sIR=PTStats.calculateSlopeStats(window.currentData,kCyc,kState,kTime,kIR);
    var sTC=PTStats.calculateSlopeStats(window.currentData,kCyc,kState,kTime,kTC);
    var rt=Math.round(window.currentData[window.currentData.length-1][kTime]-window.currentData[0][kTime]);
    var rows=[['experiment','sensor','n_cycles','slope_mean_C_per_s','slope_sd','n_data_points','runtime_s']];
    rows.push([window.currentExpName,'IR',sIR.n,sIR.mean.toFixed(6),sIR.sd.toFixed(6),window.currentData.length,rt]);
    rows.push([window.currentExpName,'TC',sTC.n,sTC.mean.toFixed(6),sTC.sd.toFixed(6),window.currentData.length,rt]);
    var csv=rows.map(function(r){return r.map(window.csvEscape).join(',');}).join('\n');
    window.downloadTextFile('pt-kit_report_'+(window.currentExpName||'exp').replace(/[^a-z0-9_-]+/gi,'_')+'.csv',csv);
};
})();