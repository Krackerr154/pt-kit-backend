const fs=require('fs'),assert=require('assert');
const index=fs.readFileSync('app/static/index.html','utf8');
const history=fs.readFileSync('app/static/history.html','utf8');
for(const s of ['NORMAL_CYCLIC','FIXED_TEMPERATURE','NATURAL_PLATEAU','experimentMode','qualified_hold_minutes','qualification_dwell','control_sensor','ramp_rate','detection_window','max_abs_slope','max_peak_to_peak','confirmation_duration','max_discovery_time','post_plateau_behavior']) assert(index.includes(s),`index missing ${s}`);
for(let n=9;n<=15;n++) assert(index.includes(`${n}:`),`state ${n} missing`);
for(const s of ['modeProgress','qualified_time','wall_hold_time','lamp_pwm','detected_plateau_temp']) assert(index.includes(s),`progress missing ${s}`);
for(const s of ['modeSummary','holdOnlyData','FIXED_TEMPERATURE','NATURAL_PLATEAU']) assert(history.includes(s),`history missing ${s}`);
console.log('mode contract OK');
