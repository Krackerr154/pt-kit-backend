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
  out=piStep(pi, 20, 19, 1, 3, .2, 100, 2);
  assert(out == 55 && pi.integral == 200); // approach cap also prevents windup
  PlateauWindow irregular; plateauReset(irregular);
  for(int i=0;i<35;i++) plateauAdd(irregular, i*1.2f, 40.0f+.001f*i);
  assert(plateauStats(irregular,30).valid);
  for(int i=35;i<80;i++) plateauAdd(irregular, i*1.2f, 40.0f+.001f*i);
  assert(irregular.count==PLATEAU_CAPACITY && plateauStats(irregular,30).valid);
  puts("isothermal host tests: PASS");
}
