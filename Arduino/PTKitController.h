#ifndef PTKIT_CONTROLLER_H
#define PTKIT_CONTROLLER_H

#include "IsothermalControl.h"
#include "PTKitPlatform.h"

#include <stddef.h>
#include <stdint.h>

// Values are part of the firmware telemetry wire contract.
enum PTKitState {
  PTKIT_IDLE = 0,
  PTKIT_PRE_HEAT,
  PTKIT_HEATING,
  PTKIT_COOLING,
  PTKIT_STABILIZING,
  PTKIT_DONE,
  PTKIT_CAL_BARE,
  PTKIT_CAL_TAPE,
  PTKIT_CAL_FULL,
  PTKIT_ISO_RAMP,
  PTKIT_ISO_QUALIFY,
  PTKIT_ISO_HOLD,
  PTKIT_PLATEAU_HEATING,
  PTKIT_PLATEAU_CONFIRM,
  PTKIT_PLATEAU_HOLD,
  PTKIT_ABORTED
};

enum PTKitOperatingMode {
  PTKIT_NORMAL_CYCLIC = 0,
  PTKIT_FIXED_TEMPERATURE,
  PTKIT_NATURAL_PLATEAU
};

struct PTKitRawSensors {
  float tempIrC;
  float tempTcC;
  float lux;
};

struct PTKitSnapshot {
  uint32_t nowMs;
  uint32_t totalSeconds;
  uint32_t stateSeconds;
  uint32_t holdElapsedSeconds;
  uint32_t holdQualifiedSeconds;
  int32_t cycle;
  int32_t state;
  int32_t mode;
  int32_t illuminationMode;
  float tempIrC;
  float tempTcC;
  float smoothedLux;
  float controlTempC;
  float tempSetpointC;
  float tempErrorC;
  float detectedPlateauTempC;
  uint8_t lampPwm;
  uint8_t fanPwm;
  uint8_t tempIrValid;
  uint8_t tempTcValid;
  uint8_t controlTempValid;
  uint8_t qualified;
};

class PTKitController {
 public:
  explicit PTKitController(PTKitPlatform &platform);
  void begin();
  bool command(const char *bytes, size_t length);
  bool step(const PTKitRawSensors &raw);
  PTKitSnapshot snapshot() const;

 private:
  PTKitController(const PTKitController &);
  PTKitController &operator=(const PTKitController &);

  void resetRun(uint32_t now);
  void stop();
  void abort(const char *reason);
  void setLamp(int pwm);
  void setFan(int pwm);
  void conditionSensors(const PTKitRawSensors &raw);
  void runNormal();
  void runCalibration();
  void runControlled(uint32_t now);
  void driveIllumination();
  void driveTemperature(float target, uint32_t now);
  void qualifiedHold(float target, float tolerance, uint32_t seconds, uint32_t now);
  void emitTelemetry();
  void emit(const char *bytes);
  void display(const char *stateText);
  bool parseSet(const char *text);
  void handleDone();

  PTKitPlatform &platform_;
  PTKitState state_;
  PTKitOperatingMode mode_;
  IlluminationMode illuminationMode_;
  IsoCommand iso_;
  PlateauCommand plateau_;
  PIController pi_;
  PlateauWindow plateauWindow_;

  float maxHardwareLux_;
  float attenuation_;
  float calBareLux_;
  float calTapedLux_;
  float luxWindow_[10];
  float rawIr_;
  float rawTc_;
  float tempIr_;
  float tempTc_;
  float rawLux_;
  float smoothedLux_;
  float userMaxTemp_;
  float targetLux_;
  float controlTemp_;
  float tempSetpoint_;
  float tempError_;
  float detectedPlateauTemp_;
  bool irValid_;
  bool tcValid_;
  bool controlValid_;
  bool qualified_;

  uint32_t targetSeconds_;
  uint32_t targetCycles_;
  uint32_t userInterval_;
  uint32_t currentSeconds_;
  uint32_t totalSeconds_;
  int currentCycle_;
  int stableCounter_;
  int lampPwm_;
  int fanPwm_;
  uint32_t lastLoopMs_;
  uint32_t lastLogMs_;
  uint32_t modeStartedMs_;
  uint32_t stateStartedMs_;
  uint32_t holdStartedMs_;
  uint32_t holdQualifiedMs_;
  uint32_t lastQualifiedMs_;
  uint32_t confirmStartedMs_;
  uint32_t lastControlMs_;
  uint32_t invalidSinceMs_;
};

#endif
