#include "../../ptkit_offload_controller.h"

#include <assert.h>
#include <stdio.h>

static ptkit::SensorSample validSample(float ir, float tc, unsigned long lux) {
  ptkit::SensorSample sample;
  sample.irDeciC = static_cast<int32_t>(ir * 10.0f);
  sample.tcDeciC = static_cast<int32_t>(tc * 10.0f);
  sample.lux = lux;
  sample.maxHardwareLux = 10000;
  sample.flags = ptkit::SENSOR_IR_VALID | ptkit::SENSOR_TC_VALID | ptkit::SENSOR_LUX_VALID;
  return sample;
}

int main() {
  ptkit::BackendCommand command;
  assert(ptkit::parseBackendCommand("ISO1:45:120:0.5:10:80:2:TC:6", command));
  assert(command.kind == ptkit::COMMAND_FIXED && command.targetTempDeciC == 450 &&
         command.sensor == ptkit::CONTROL_SENSOR_TC && command.rampRateMilliCPerMin == 6000);
  assert(ptkit::parseBackendCommand("PLAT1:5000:60:30:0.2:0.8:20:900:90:2:IR:REGULATED", command));
  assert(command.kind == ptkit::COMMAND_PLATEAU && command.targetLux == 5000 &&
         command.postMode == ptkit::POST_REGULATED);
  assert(ptkit::parseBackendCommand("PLAT2:MAX_OUTPUT:60:30:0.2:0.8:20:900:90:2:IR:PASSIVE", command));
  assert(command.illuminationMode == ptkit::ILLUMINATION_MAX_OUTPUT);
  assert(ptkit::parseBackendCommand("SET2:60:5:80:2:MAX_OUTPUT", command));
  assert(command.kind == ptkit::COMMAND_NORMAL && command.illuminationMode == ptkit::ILLUMINATION_MAX_OUTPUT);
  assert(!ptkit::parseBackendCommand("ISO1:45junk:120:0.5:10:80:2:TC:6", command));
  assert(!ptkit::parseBackendCommand("PLAT1:5000:60:2:0.2:0.8:20:900:90:2:IR:PASSIVE", command));

  ptkit::ExperimentController controller;
  assert(ptkit::parseBackendCommand("ISO1:45:4:0.5:2:80:1:TC:600", command));
  assert(controller.start(command, 0, validSample(20.0f, 20.0f, 0)));
  ptkit::ControlSnapshot snapshot = controller.step(0, validSample(20.0f, 20.0f, 0));
  assert(snapshot.stateCode == ptkit::STATE_ISO_RAMP && snapshot.lampPwm > 0);
  snapshot = controller.step(1000, validSample(45.0f, 45.0f, 0));
  assert(snapshot.stateCode == ptkit::STATE_ISO_RAMP || snapshot.stateCode == ptkit::STATE_ISO_QUALIFY);
  snapshot = controller.step(2000, validSample(45.0f, 45.0f, 0));
  assert(snapshot.stateCode == ptkit::STATE_ISO_QUALIFY);
  snapshot = controller.step(4000, validSample(45.0f, 45.0f, 0));
  assert(snapshot.stateCode == ptkit::STATE_ISO_HOLD);
  snapshot = controller.step(8000, validSample(45.0f, 45.0f, 0));
  assert(snapshot.stateCode == ptkit::STATE_DONE);

  assert(ptkit::parseBackendCommand("PLAT2:MAX_OUTPUT:3:3:0.2:0.8:2:10:90:1:IR:PASSIVE", command));
  assert(controller.start(command, 10000, validSample(30.0f, 30.0f, 100)));
  for (unsigned long ms = 10000; ms <= 14000; ms += 1000) {
    snapshot = controller.step(ms, validSample(30.0f, 30.0f, 100));
  }
  assert(snapshot.stateCode == ptkit::STATE_PLATEAU_CONFIRM || snapshot.stateCode == ptkit::STATE_PLATEAU_HOLD);
  snapshot = controller.step(16000, validSample(30.0f, 30.0f, 100));
  assert(snapshot.stateCode == ptkit::STATE_PLATEAU_HOLD);
  snapshot = controller.step(19000, validSample(30.0f, 30.0f, 100));
  assert(snapshot.stateCode == ptkit::STATE_DONE);

  ptkit::ExperimentController pausedController;
  assert(ptkit::parseBackendCommand("PLAT2:MAX_OUTPUT:60:3:0.2:0.8:30:900:90:1:IR:PASSIVE", command));
  assert(pausedController.start(command, 30000, validSample(30.0f, 30.0f, 100)));
  snapshot = pausedController.step(30000, validSample(30.0f, 30.0f, 100));
  const uint8_t stateBeforePause = snapshot.stateCode;
  pausedController.pauseLink(31000, 77, 33);
  assert(pausedController.linkPaused());
  snapshot = pausedController.step(81000, validSample(30.0f, 30.0f, 100));
  assert(snapshot.stateCode == stateBeforePause && snapshot.totalSeconds == 1 &&
         snapshot.lampPwm == 77 && snapshot.fanPwm == 33);
  pausedController.resumeLink(81000);
  assert(!pausedController.linkPaused());
  snapshot = pausedController.step(82000, validSample(30.0f, 30.0f, 100));
  assert(snapshot.totalSeconds == 2 && snapshot.stateCode == stateBeforePause);
  pausedController.pauseLink(83000, 77, 33);
  snapshot = pausedController.step(84000, validSample(30.0f, 95.0f, 100));
  assert(snapshot.stateCode == ptkit::STATE_ABORTED && snapshot.fault == ptkit::FAULT_OVER_TEMPERATURE);

  assert(ptkit::parseBackendCommand("ISO1:45:120:0.5:10:80:1:TC:6", command));
  assert(controller.start(command, 20000, validSample(25.0f, 25.0f, 0)));
  ptkit::SensorSample bad = validSample(25.0f, 25.0f, 0);
  bad.flags &= static_cast<uint8_t>(~ptkit::SENSOR_TC_VALID);
  snapshot = controller.step(20000, bad);
  assert(snapshot.lampPwm == 0 && snapshot.fanPwm == 255);
  snapshot = controller.step(30000, bad);
  assert(snapshot.stateCode == ptkit::STATE_ABORTED);

  puts("offload controller tests: PASS");
  return 0;
}
