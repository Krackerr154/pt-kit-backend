#include "../IsothermalControl.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

int main() {
  IsoCommand iso;
  assert(parseIsoCommand("ISO1:45:120:0.5:10:80:2:TC:6", iso));
  assert(iso.targetTemp == 45 && iso.holdSeconds == 120 && iso.sensor == SENSOR_TC);
  assert(!parseIsoCommand("ISO1:45:0:0.5:10:80:2:TC:6", iso));
  PlateauCommand p;
  assert(parsePlateauCommand("PLAT1:5000:60:30:0.2:0.8:20:900:90:2:IR:REGULATED", p));
  assert(p.sensor == SENSOR_IR && p.postMode == POST_REGULATED);
  assert(!parsePlateauCommand("PLAT1:5000:60:2:0.2:0.8:20:900:90:2:IR:PASSIVE", p));
  assert(!parseIsoCommand("ISO1:45junk:120:0.5:10:80:2:TC:6", iso));
  assert(!parseIsoCommand("ISO1:+45:120:0.5:10:80:2:TC:6", iso));
  assert(!parseIsoCommand("ISO1:45:-1:0.5:10:80:2:TC:6", iso));
  assert(!parseIsoCommand("ISO1:45:4294968:0.5:10:80:2:TC:6", iso));
  assert(!parseIsoCommand("ISO1:9999999999999999999:120:0.5:10:80:2:TC:6", iso));
  assert(!parsePlateauCommand("PLAT1:5000:60:30:0.2:0.8:20:6501:90:2:IR:PASSIVE", p));

  PlateauWindow w; plateauReset(w);
  for (int i=0;i<30;i++) plateauAdd(w, i, 40.0f + 0.001f*i);
  PlateauStats s = plateauStats(w, 30);
  assert(s.valid && fabs(s.slopePerMin - 0.06f) < 0.002f && s.peakToPeak < 0.04f);

  PIController pi; piReset(pi);
  float out = piStep(pi, 20, 10, 1, 3, 0.2, 255, 2);
  assert(out > 0 && out <= 255);
  for(int i=0;i<100;i++) out=piStep(pi, 100, 0, 1, 3, 0.2, 80, 5);
  assert(out == 80); // clamp + anti-windup
  piReset(pi); pi.integral=200;
  out=piStep(pi, 20, 21, 1, 3, .2, 100, 2);
  assert(out == 55 && pi.integral < 200); // saturated high output must unwind
  piReset(pi); pi.integral=-200;
  out=piStep(pi, 20, 21, 1, 3, .2, 100, 2);
  assert(out == 0 && pi.integral == -200); // matching error cannot wind farther down
  out=piStep(pi, 20, 10, 1, 3, .2, 100, 2);
  assert(out == 0 && pi.integral > -200); // saturated low output must unwind

  PlateauWindow irregular; plateauReset(irregular);
  for(int i=0;i<35;i++) plateauAdd(irregular, i*1.2f, 40.0f+.001f*i);
  assert(plateauStats(irregular,30).valid);
  for(int i=35;i<80;i++) plateauAdd(irregular, i*1.2f, i<54 ? 1000.0f : 40.0f+.001f*i);
  PlateauStats latest=plateauStats(irregular,30);
  assert(irregular.count==PLATEAU_CAPACITY && latest.valid && latest.peakToPeak < .1f); // old points excluded

  PlateauWindow wrapped; plateauReset(wrapped);
  const uint32_t base=0xfffffff0UL;
  for(int i=0;i<35;i++){wrapped.t[wrapped.next]=base+(uint32_t)(i*10);wrapped.y[wrapped.next]=20+.01f*i;wrapped.next=(wrapped.next+1)%PLATEAU_CAPACITY;wrapped.count++;}
  PlateauStats ws=plateauStats(wrapped,30);
  assert(ws.valid && fabs(ws.slopePerMin-.6f)<.01f);
  puts("isothermal host tests: PASS");
}
