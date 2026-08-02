#include "../../Arduino/PTKitController.h"
#include "../../Arduino/sim/PTKitHostPlatform.h"
#include "../../Arduino/sim/PTKitSimulationCAPI.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static int fieldCount(const char *line) {
  int fields = 1;
  for (const char *p = line; *p && *p != '\n'; ++p) if (*p == ',') ++fields;
  return fields;
}

static void tick(PTKitController &controller, PTKitHostPlatform &platform,
                 float ir, float tc, float lux, uint32_t advance = 1000) {
  platform.advanceMs(advance);
  PTKitRawSensors raw = {ir, tc, lux};
  controller.step(raw);
}

int main() {
  static_assert(PTKIT_IDLE == 0 && PTKIT_PRE_HEAT == 1 && PTKIT_HEATING == 2 &&
                PTKIT_COOLING == 3 && PTKIT_STABILIZING == 4 && PTKIT_DONE == 5 &&
                PTKIT_CAL_BARE == 6 && PTKIT_CAL_TAPE == 7 && PTKIT_CAL_FULL == 8 &&
                PTKIT_ISO_RAMP == 9 && PTKIT_ISO_QUALIFY == 10 && PTKIT_ISO_HOLD == 11 &&
                PTKIT_PLATEAU_HEATING == 12 && PTKIT_PLATEAU_CONFIRM == 13 &&
                PTKIT_PLATEAU_HOLD == 14 && PTKIT_ABORTED == 15,
                "wire state values changed");

  PTKitHostPlatform platform;
  platform.persistedMaxLux = 10000.0f;
  platform.persistedAttenuation = 1.0f;
  PTKitController controller(platform);
  controller.begin();

  assert(controller.command("SET:2:1:80:1:5000", 19));
  assert(platform.blockingDelayMs == 2000U);
  PTKitSnapshot s = controller.snapshot();
  assert(s.state == PTKIT_PRE_HEAT && s.mode == PTKIT_NORMAL_CYCLIC);
  assert(s.illuminationMode == TARGET_LUX && s.cycle == 1 && s.lampPwm == 127);

  tick(controller, platform, 31, 31, 5000);
  assert(controller.snapshot().state == PTKIT_HEATING);
  tick(controller, platform, 31, 31, 5000);
  assert(controller.snapshot().state == PTKIT_HEATING);
  tick(controller, platform, 31, 31, 5000);
  assert(controller.snapshot().state == PTKIT_COOLING && platform.lampPwm == 0);
  tick(controller, platform, 28, 28, 0);
  assert(controller.snapshot().state == PTKIT_STABILIZING);
  for (int i = 0; i < 5; ++i) tick(controller, platform, 28, 28, 0);
  assert(controller.snapshot().state == PTKIT_DONE);
  assert(fieldCount(platform.lastLine().c_str()) == 17);

  // DONE is terminal until its next due tick, where the current firmware emits
  // repeated DONE frames through blocking delays and then auto-resets to IDLE.
  const uint32_t beforeDoneDelay = platform.nowMs();
  tick(controller, platform, 28, 28, 0);
  assert(controller.snapshot().state == PTKIT_IDLE);
  assert((uint32_t)(platform.nowMs() - beforeDoneDelay) == 4500U);
  assert(platform.blockingDelayMs >= 3500U);

  assert(controller.command("SET2:3:2:90:2:MAX_OUTPUT", 28));
  assert(controller.snapshot().illuminationMode == MAX_OUTPUT);
  assert(controller.snapshot().lampPwm == 255);
  const size_t outputBeforeBad = platform.output.size();
  assert(!controller.command("SET2:bad", 8));
  assert(platform.output.size() > outputBeforeBad);
  assert(platform.output.find("ERR:SET2\n", outputBeforeBad) != std::string::npos);

  assert(controller.command("ISO1:45:5:0.5:2:80:1:TC:6", 29));
  tick(controller, platform, 30, 30, 0);
  s = controller.snapshot();
  assert(s.state == PTKIT_ISO_RAMP && fabs(s.tempSetpointC - 30.1f) < 0.001f);
  const int firstRampPwm = s.lampPwm;
  tick(controller, platform, 30, 30, 0, 5000); // skipped catch-up; one ramp increment
  s = controller.snapshot();
  assert(fabs(s.tempSetpointC - 30.2f) < 0.001f);
  assert(s.lampPwm >= firstRampPwm); // PI dt is capped at two seconds

  // Controlled modes preserve invalid raw values, shut lamp down, and abort
  // only after the existing ten-second invalid-selected-sensor interval.
  tick(controller, platform, 30, NAN, 0);
  assert(controller.snapshot().state == PTKIT_ISO_RAMP && platform.lampPwm == 0 && platform.fanPwm == 255);
  tick(controller, platform, 30, NAN, 0, 9999);
  assert(controller.snapshot().state == PTKIT_ISO_RAMP);
  // The firmware's one-second gate means a one-millisecond advance alone does
  // not execute a controller tick; the next eligible tick aborts at 10 s.
  tick(controller, platform, 30, NAN, 0, 1000);
  assert(controller.snapshot().state == PTKIT_ABORTED);
  tick(controller, platform, 30, 30, 0);
  assert(controller.snapshot().state == PTKIT_ABORTED && platform.fanPwm == 255);
  assert(controller.command("STOP", 4));
  s = controller.snapshot();
  assert(s.state == PTKIT_IDLE && s.totalSeconds == 0 && s.cycle == 0);
  assert(platform.lampPwm == 0 && platform.fanPwm == 0);

  assert(controller.command("CAL_BARE", 8));
  assert(controller.snapshot().state == PTKIT_CAL_BARE && controller.snapshot().lampPwm == 128);
  assert(controller.command("CAL_TAPE", 8));
  assert(controller.snapshot().state == PTKIT_CAL_TAPE);
  assert(controller.command("CAL_FULL", 8));
  assert(controller.snapshot().state == PTKIT_CAL_FULL && controller.snapshot().lampPwm == 255);

  assert(controller.command("PLAT1:5000:5:3:0.2:0.8:2:30:90:1:IR:REGULATED", 53));
  assert(controller.snapshot().state == PTKIT_PLATEAU_HEATING);
  assert(controller.snapshot().mode == PTKIT_NATURAL_PLATEAU);
  assert(controller.command("PLAT2:MAX_OUTPUT:5:3:0.2:0.8:2:30:90:1:IR:PASSIVE", 57));
  assert(controller.snapshot().illuminationMode == MAX_OUTPUT && controller.snapshot().lampPwm == 255);

  // Calibration must execute its warm-up/stability path, emit side-channel
  // results, and persist the completed profile through the platform boundary.
  PTKitHostPlatform calibrationPlatform;
  PTKitController calibrationController(calibrationPlatform);
  calibrationController.begin();
  uint32_t calibrationNow = 0;
  assert(calibrationController.command("CAL_BARE", 8));
  for (int i = 0; i < 35; ++i) {
    calibrationNow += 1000;
    calibrationPlatform.setNowMs(calibrationNow);
    calibrationController.step(PTKitRawSensors{30, 30, 1000});
  }
  assert(calibrationPlatform.output.find("CALBARE:") != std::string::npos);
  assert(calibrationController.snapshot().state == PTKIT_IDLE);
  assert(calibrationController.command("CAL_TAPE", 8));
  for (int i = 0; i < 35; ++i) {
    calibrationNow += 1000;
    calibrationPlatform.setNowMs(calibrationNow);
    calibrationController.step(PTKitRawSensors{30, 30, 500});
  }
  assert(calibrationPlatform.output.find("CALTAPE:") != std::string::npos);
  assert(calibrationController.command("CAL_FULL", 8));
  for (int i = 0; i < 35; ++i) {
    calibrationNow += 1000;
    calibrationPlatform.setNowMs(calibrationNow);
    calibrationController.step(PTKitRawSensors{30, 30, 700});
  }
  assert(calibrationPlatform.output.find("CALRESULT:") != std::string::npos);
  assert(calibrationPlatform.output.find("MAXLUX:") != std::string::npos);
  assert(calibrationPlatform.saveCount == 1U);
  assert(calibrationController.snapshot().state == PTKIT_IDLE);

  // Unsigned subtraction keeps the one-second scheduler valid across rollover.
  PTKitHostPlatform wrapPlatform;
  wrapPlatform.setNowMs(0xfffffff0U);
  PTKitController wrapController(wrapPlatform);
  wrapController.begin();
  assert(wrapController.command("SET:60:1:80:1:5000", 20));
  wrapPlatform.setNowMs(0x000003e8U);
  wrapController.step(PTKitRawSensors{20, 20, 0});
  assert(wrapController.snapshot().totalSeconds == 1);

  // Plain-C facade: POD snapshots, explicit command/output lengths, no C++ API needed.
  PTKitSimHandle *handle = ptkit_sim_create();
  assert(handle);
  ptkit_sim_set_time(handle, 1000);
  ptkit_sim_set_raw_sensors(handle, 31, 31, 5000);
  assert(ptkit_sim_send_command(handle, "SET:1:1:80:1:5000", 19) == 1);
  assert(ptkit_sim_step(handle) == 1);
  PTKitSimSnapshot abi = {};
  assert(ptkit_sim_get_snapshot(handle, &abi) == 1 && abi.state == PTKIT_HEATING);
  char bytes[512];
  const size_t available = ptkit_sim_output_size(handle);
  assert(available > 0);
  const size_t copied = ptkit_sim_read_output(handle, bytes, sizeof bytes);
  assert(copied <= sizeof bytes && copied <= available);
  ptkit_sim_destroy(handle);

  puts("ptkit controller host tests: PASS");
  return 0;
}
