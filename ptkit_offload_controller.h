#ifndef PTKIT_OFFLOAD_CONTROLLER_H
#define PTKIT_OFFLOAD_CONTROLLER_H

#include "ptkit_offload_protocol.h"

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

namespace ptkit {

const uint8_t STATE_IDLE = 0;
const uint8_t STATE_PRE_HEAT = 1;
const uint8_t STATE_HEATING = 2;
const uint8_t STATE_COOLING = 3;
const uint8_t STATE_STABILIZING = 4;
const uint8_t STATE_DONE = 5;
const uint8_t STATE_CAL_BARE = 6;
const uint8_t STATE_CAL_TAPE = 7;
const uint8_t STATE_CAL_FULL = 8;
const uint8_t STATE_ISO_RAMP = 9;
const uint8_t STATE_ISO_QUALIFY = 10;
const uint8_t STATE_ISO_HOLD = 11;
const uint8_t STATE_PLATEAU_HEATING = 12;
const uint8_t STATE_PLATEAU_CONFIRM = 13;
const uint8_t STATE_PLATEAU_HOLD = 14;
const uint8_t STATE_ABORTED = 15;

enum CommandKind : uint8_t { COMMAND_NONE, COMMAND_STOP, COMMAND_NORMAL, COMMAND_FIXED, COMMAND_PLATEAU };
enum ControlSensor : uint8_t { CONTROL_SENSOR_IR, CONTROL_SENSOR_TC };
enum PostMode : uint8_t { POST_PASSIVE, POST_REGULATED };
enum Illumination : uint8_t { ILLUMINATION_TARGET_LUX, ILLUMINATION_MAX_OUTPUT, ILLUMINATION_TEMPERATURE_CONTROLLED };

struct BackendCommand {
  CommandKind kind;
  Illumination illuminationMode;
  ControlSensor sensor;
  PostMode postMode;
  uint32_t durationSeconds;
  uint32_t cycles;
  uint32_t holdSeconds;
  uint32_t qualificationSeconds;
  uint32_t plateauWindowSeconds;
  uint32_t plateauConfirmationSeconds;
  uint32_t plateauDiscoverySeconds;
  uint32_t logIntervalSeconds;
  uint32_t targetLux;
  int32_t targetTempDeciC;
  int32_t toleranceDeciC;
  int32_t maxTempDeciC;
  int32_t maxSlopeMilliCPerMin;
  int32_t maxRangeDeciC;
  int32_t rampRateMilliCPerMin;
};

struct SensorSample {
  int32_t irDeciC;
  int32_t tcDeciC;
  uint32_t lux;
  uint32_t maxHardwareLux;
  uint8_t flags;
};

struct ControlSnapshot {
  uint32_t totalSeconds;
  uint32_t phaseSeconds;
  uint32_t cycleNum;
  uint8_t stateCode;
  CommandKind kind;
  Illumination illuminationMode;
  int32_t controlTempDeciC;
  int32_t tempSetpointDeciC;
  int32_t tempErrorDeciC;
  uint8_t lampPwm;
  uint8_t fanPwm;
  uint32_t holdWallSeconds;
  uint32_t holdQualifiedSeconds;
  bool qualified;
  int32_t detectedPlateauDeciC;
  uint8_t fault;
};

inline bool strictUnsigned(const char *text, uint32_t &value, uint32_t maximum = 4294967UL) {
  return parseUnsigned(text, value, maximum);
}

inline bool strictFloat(const char *text, float &value) {
  if (!text || !*text) return false;
  bool dot = false, digit = false;
  for (const char *p = text; *p; ++p) {
    if (*p == '.' && !dot) { dot = true; continue; }
    if (*p < '0' || *p > '9') return false;
    digit = true;
  }
  if (!digit) return false;
  char *end = 0;
  const double parsed = strtod(text, &end);
  if (!end || *end || !isfinite(parsed) || parsed > 214748364.0) return false;
  value = static_cast<float>(parsed);
  return isfinite(value);
}

inline bool deciC(const char *text, int32_t &value, bool positiveOnly = true) {
  float degrees = 0.0f;
  if (!strictFloat(text, degrees) || (positiveOnly && degrees <= 0.0f)) return false;
  const float scaled = degrees * 10.0f;
  if (!isfinite(scaled) || scaled > 65535.0f) return false;
  value = static_cast<int32_t>(scaled + (scaled >= 0 ? 0.5f : -0.5f));
  return true;
}

inline bool milliCPerMin(const char *text, int32_t &value) {
  float degrees = 0.0f;
  if (!strictFloat(text, degrees) || degrees <= 0.0f) return false;
  const float scaled = degrees * 1000.0f;
  if (!isfinite(scaled) || scaled > 214748364.0f) return false;
  value = static_cast<int32_t>(scaled + 0.5f);
  return true;
}

inline bool parseSensorField(const char *text, ControlSensor &sensor) {
  if (!strcmp(text, "IR")) { sensor = CONTROL_SENSOR_IR; return true; }
  if (!strcmp(text, "TC")) { sensor = CONTROL_SENSOR_TC; return true; }
  return false;
}

inline bool parseBackendCommand(const char *text, BackendCommand &command) {
  if (!text || !*text || strlen(text) >= BACKEND_COMMAND_MAX_CHARS) return false;
  char mutableText[BACKEND_COMMAND_MAX_CHARS];
  strcpy(mutableText, text);
  char *fields[12]; uint8_t count = 0;
  if (!splitPayload(mutableText, fields, 12, count)) return false;
  memset(&command, 0, sizeof(command));
  command.kind = COMMAND_NONE;

  if (count == 1 && !strcmp(fields[0], "STOP")) { command.kind = COMMAND_STOP; return true; }
  if (!strcmp(fields[0], "SET") && (count == 5 || count == 6)) {
    uint32_t duration = 0, cycles = 0, interval = 0;
    int32_t maxTemp = 0;
    float targetLux = 0.0f;
    if (!strictUnsigned(fields[1], duration) || !strictUnsigned(fields[2], cycles, 32767UL) ||
        !deciC(fields[3], maxTemp) || !strictUnsigned(fields[4], interval, 32767UL) ||
        !duration || !cycles || !interval) return false;
    if (count == 6 && (!strictFloat(fields[5], targetLux) || targetLux < 0.0f)) return false;
    command.kind = COMMAND_NORMAL; command.illuminationMode = ILLUMINATION_TARGET_LUX;
    command.durationSeconds = duration; command.cycles = cycles; command.maxTempDeciC = maxTemp;
    command.logIntervalSeconds = interval; command.targetLux = count == 6 ? static_cast<uint32_t>(targetLux + 0.5f) : 0;
    return true;
  }
  if (!strcmp(fields[0], "SET2") && count == 6) {
    uint32_t duration = 0, cycles = 0, interval = 0; int32_t maxTemp = 0;
    if (strcmp(fields[5], "MAX_OUTPUT") || !strictUnsigned(fields[1], duration) ||
        !strictUnsigned(fields[2], cycles, 32767UL) || !deciC(fields[3], maxTemp) ||
        !strictUnsigned(fields[4], interval, 32767UL) || !duration || !cycles || !interval) return false;
    command.kind = COMMAND_NORMAL; command.illuminationMode = ILLUMINATION_MAX_OUTPUT;
    command.durationSeconds = duration; command.cycles = cycles; command.maxTempDeciC = maxTemp;
    command.logIntervalSeconds = interval;
    return true;
  }
  if (!strcmp(fields[0], "ISO1") && count == 9) {
    uint32_t hold = 0, qualify = 0, interval = 0;
    int32_t target = 0, tolerance = 0, maximum = 0, ramp = 0;
    if (!deciC(fields[1], target) || !strictUnsigned(fields[2], hold) || !deciC(fields[3], tolerance) ||
        !strictUnsigned(fields[4], qualify) || !deciC(fields[5], maximum) ||
        !strictUnsigned(fields[6], interval, 32767UL) || !parseSensorField(fields[7], command.sensor) ||
        !milliCPerMin(fields[8], ramp) || !hold || !qualify || !interval || maximum <= target) return false;
    command.kind = COMMAND_FIXED; command.illuminationMode = ILLUMINATION_TEMPERATURE_CONTROLLED;
    command.targetTempDeciC = target; command.toleranceDeciC = tolerance; command.maxTempDeciC = maximum;
    command.holdSeconds = hold; command.qualificationSeconds = qualify; command.logIntervalSeconds = interval;
    command.rampRateMilliCPerMin = ramp;
    return true;
  }
  if ((!strcmp(fields[0], "PLAT1") || !strcmp(fields[0], "PLAT2")) && count == 12) {
    const bool maximumOutput = !strcmp(fields[0], "PLAT2");
    float targetLux = 0.0f;
    uint32_t hold = 0, window = 0, confirm = 0, discovery = 0, interval = 0;
    int32_t slope = 0, range = 0, maximum = 0;
    if ((maximumOutput && strcmp(fields[1], "MAX_OUTPUT")) ||
        (!maximumOutput && (!strictFloat(fields[1], targetLux) || targetLux <= 0.0f)) ||
        !strictUnsigned(fields[2], hold) || !strictUnsigned(fields[3], window, 30UL) ||
        !milliCPerMin(fields[4], slope) || !deciC(fields[5], range) ||
        !strictUnsigned(fields[6], confirm) || !strictUnsigned(fields[7], discovery, 6500UL) ||
        !deciC(fields[8], maximum) || !strictUnsigned(fields[9], interval, 32767UL) ||
        !parseSensorField(fields[10], command.sensor) || !hold || window < 3 || !confirm || discovery < window || !interval) return false;
    if (!strcmp(fields[11], "PASSIVE")) command.postMode = POST_PASSIVE;
    else if (!strcmp(fields[11], "REGULATED")) command.postMode = POST_REGULATED;
    else return false;
    command.kind = COMMAND_PLATEAU;
    command.illuminationMode = maximumOutput ? ILLUMINATION_MAX_OUTPUT : ILLUMINATION_TARGET_LUX;
    command.targetLux = maximumOutput ? 0 : static_cast<uint32_t>(targetLux + 0.5f);
    command.holdSeconds = hold; command.plateauWindowSeconds = window;
    command.maxSlopeMilliCPerMin = slope; command.maxRangeDeciC = range;
    command.plateauConfirmationSeconds = confirm; command.plateauDiscoverySeconds = discovery;
    command.maxTempDeciC = maximum; command.logIntervalSeconds = interval;
    return true;
  }
  return false;
}

class ExperimentController {
 public:
  ExperimentController() { reset(); }

  void reset() {
    memset(&command_, 0, sizeof(command_));
    state_ = STATE_IDLE; startedMs_ = phaseStartedMs_ = holdStartedMs_ = 0;
    lastControlMs_ = invalidSinceMs_ = lastQualificationMs_ = confirmationStartedMs_ = 0;
    totalSeconds_ = phaseSeconds_ = cycleNum_ = qualifiedMs_ = 0;
    lampPwm_ = fanPwm_ = 0; targetSetpointDeciC_ = INVALID_DECI_C;
    controlTempDeciC_ = tempErrorDeciC_ = detectedPlateauDeciC_ = INVALID_DECI_C;
    integral_ = 0.0f; smoothedLux_ = 0.0f; plateauCount_ = plateauNext_ = 0;
    fault_ = FAULT_NONE; qualified_ = false;
    linkPaused_ = false; linkPauseStartedMs_ = 0;
  }

  bool start(const BackendCommand &command, uint32_t nowMs, const SensorSample &sensor) {
    reset();
    if (command.kind == COMMAND_STOP) return true;
    if (command.kind != COMMAND_NORMAL && command.kind != COMMAND_FIXED && command.kind != COMMAND_PLATEAU) return false;
    command_ = command; startedMs_ = phaseStartedMs_ = nowMs; cycleNum_ = 1;
    if (command.kind == COMMAND_NORMAL) {
      state_ = STATE_PRE_HEAT;
      lampPwm_ = initialLuxPwm(sensor);
    } else if (command.kind == COMMAND_FIXED) {
      state_ = STATE_ISO_RAMP;
    } else {
      state_ = STATE_PLATEAU_HEATING;
      lampPwm_ = initialLuxPwm(sensor);
    }
    return true;
  }

  void stop() { reset(); }
  void abortExternal(uint8_t fault) { abort(fault); }
  void pauseLink(uint32_t nowMs, uint8_t heldLampPwm, uint8_t heldFanPwm) {
    if (!active() || linkPaused_) return;
    linkPaused_ = true;
    linkPauseStartedMs_ = nowMs;
    lampPwm_ = heldLampPwm;
    fanPwm_ = heldFanPwm;
  }
  void resumeLink(uint32_t nowMs) {
    if (!linkPaused_) return;
    const uint32_t pausedMs = nowMs - linkPauseStartedMs_;
    shiftTimestamp(startedMs_, pausedMs);
    shiftTimestamp(phaseStartedMs_, pausedMs);
    shiftTimestamp(holdStartedMs_, pausedMs);
    shiftTimestamp(lastControlMs_, pausedMs);
    shiftTimestamp(invalidSinceMs_, pausedMs);
    shiftTimestamp(lastQualificationMs_, pausedMs);
    shiftTimestamp(confirmationStartedMs_, pausedMs);
    for (uint8_t i = 0; i < plateauCount_; ++i) shiftTimestamp(plateauTimes_[i], pausedMs);
    linkPaused_ = false;
    linkPauseStartedMs_ = 0;
  }
  bool linkPaused() const { return linkPaused_; }
  bool active() const { return state_ != STATE_IDLE && state_ != STATE_DONE && state_ != STATE_ABORTED; }
  uint8_t stateCode() const { return state_; }
  uint32_t logIntervalSeconds() const { return command_.logIntervalSeconds ? command_.logIntervalSeconds : 1UL; }
  const BackendCommand &command() const { return command_; }

  ControlSnapshot step(uint32_t nowMs, const SensorSample &sensor) {
    updateLux(sensor);

    if (state_ == STATE_IDLE || state_ == STATE_DONE || state_ == STATE_ABORTED) {
      if (state_ != STATE_ABORTED) { lampPwm_ = 0; fanPwm_ = 0; }
      return snapshot(nowMs, sensor);
    }

    if (sensor.tcDeciC != INVALID_DECI_C && sensor.tcDeciC > command_.maxTempDeciC) {
      abort(FAULT_OVER_TEMPERATURE);
      return snapshot(nowMs, sensor);
    }

    totalSeconds_ = startedMs_ ? elapsedWithoutLinkPause(nowMs, startedMs_) / 1000UL : 0;
    phaseSeconds_ = phaseStartedMs_ ? elapsedWithoutLinkPause(nowMs, phaseStartedMs_) / 1000UL : 0;
    if (linkPaused_) return snapshot(nowMs, sensor);

    if (command_.kind == COMMAND_NORMAL) stepNormal(nowMs, sensor);
    else stepControlled(nowMs, sensor);
    return snapshot(nowMs, sensor);
  }

 private:
  static const uint8_t PLATEAU_CAPACITY = 64;
  uint32_t plateauTimes_[PLATEAU_CAPACITY];
  int32_t plateauTemps_[PLATEAU_CAPACITY];
  BackendCommand command_;
  uint8_t state_;
  uint32_t startedMs_, phaseStartedMs_, holdStartedMs_, lastControlMs_, invalidSinceMs_, lastQualificationMs_, confirmationStartedMs_;
  uint32_t totalSeconds_, phaseSeconds_, cycleNum_, qualifiedMs_;
  uint8_t lampPwm_, fanPwm_, fault_;
  int32_t targetSetpointDeciC_, controlTempDeciC_, tempErrorDeciC_, detectedPlateauDeciC_;
  float integral_, smoothedLux_;
  uint8_t plateauCount_, plateauNext_;
  bool qualified_;
  bool linkPaused_;
  uint32_t linkPauseStartedMs_;

  static int32_t selectedTemperature(const SensorSample &sensor, ControlSensor selected) {
    return selected == CONTROL_SENSOR_TC ? sensor.tcDeciC : sensor.irDeciC;
  }

  static bool selectedValid(const SensorSample &sensor, ControlSensor selected) {
    return selected == CONTROL_SENSOR_TC ? (sensor.flags & SENSOR_TC_VALID) : (sensor.flags & SENSOR_IR_VALID);
  }

  static void shiftTimestamp(uint32_t &timestamp, uint32_t delta) {
    if (timestamp) timestamp += delta;
  }

  uint32_t elapsedWithoutLinkPause(uint32_t nowMs, uint32_t startedMs) const {
    if (!startedMs) return 0;
    uint32_t elapsed = nowMs - startedMs;
    if (linkPaused_) {
      const uint32_t currentPause = nowMs - linkPauseStartedMs_;
      if (elapsed >= currentPause) elapsed -= currentPause;
      else elapsed = 0;
    }
    return elapsed;
  }

  void changeState(uint8_t state, uint32_t nowMs) {
    state_ = state; phaseStartedMs_ = nowMs; phaseSeconds_ = 0;
  }

  void abort(uint8_t fault) {
    fault_ = fault; state_ = STATE_ABORTED; lampPwm_ = 0; fanPwm_ = 255; qualified_ = false;
  }

  uint8_t initialLuxPwm(const SensorSample &sensor) const {
    if (command_.illuminationMode == ILLUMINATION_MAX_OUTPUT) return 255;
    if (!sensor.maxHardwareLux) return 0;
    const uint32_t raw = (command_.targetLux * 255UL) / sensor.maxHardwareLux;
    return raw > 255 ? 255 : static_cast<uint8_t>(raw);
  }

  void updateLux(const SensorSample &sensor) {
    if (!(sensor.flags & SENSOR_LUX_VALID)) return;
    if (smoothedLux_ < 1.0f && sensor.lux > 1UL) smoothedLux_ = static_cast<float>(sensor.lux);
    else smoothedLux_ = 0.2f * static_cast<float>(sensor.lux) + 0.8f * smoothedLux_;
  }

  void driveLux(const SensorSample &sensor) {
    if (command_.illuminationMode == ILLUMINATION_MAX_OUTPUT) { lampPwm_ = 255; fanPwm_ = 0; return; }
    if (!(sensor.flags & SENSOR_LUX_VALID)) { lampPwm_ = 0; fanPwm_ = 255; return; }
    const float error = static_cast<float>(command_.targetLux) - smoothedLux_;
    if (fabsf(error) > 50.0f) {
      int next = static_cast<int>(lampPwm_) + static_cast<int>(error * 0.05f);
      if (next < 0) next = 0;
      if (next > 255) next = 255;
      lampPwm_ = static_cast<uint8_t>(next);
    }
    fanPwm_ = 0;
  }

  void driveTemperature(uint32_t nowMs, int32_t targetDeciC) {
    float dt = lastControlMs_ ? static_cast<float>(nowMs - lastControlMs_) / 1000.0f : 1.0f;
    if (dt < 0.001f) dt = 0.001f;
    if (dt > 2.0f) dt = 2.0f;
    lastControlMs_ = nowMs;
    const float error = static_cast<float>(targetDeciC - controlTempDeciC_) / 10.0f;
    const float candidate = integral_ + 0.35f * error * dt;
    const float cap = (error < 2.0f) ? 140.25f : 255.0f;
    float raw = 18.0f * error + candidate;
    if (raw < 0.0f) raw = 0.0f;
    if (raw > cap) raw = cap;
    const float uncapped = 18.0f * error + candidate;
    if ((uncapped >= 0.0f && uncapped <= cap) || (uncapped > cap && error < 0.0f) || (uncapped < 0.0f && error > 0.0f)) integral_ = candidate;
    lampPwm_ = static_cast<uint8_t>(raw + 0.5f); fanPwm_ = 0;
    targetSetpointDeciC_ = targetDeciC; tempErrorDeciC_ = targetDeciC - controlTempDeciC_;
  }

  void stepNormal(uint32_t nowMs, const SensorSample &sensor) {
    const bool temperaturesValid = (sensor.flags & SENSOR_IR_VALID) && (sensor.flags & SENSOR_TC_VALID);
    if (!temperaturesValid) { lampPwm_ = 0; fanPwm_ = 255; return; }
    switch (state_) {
      case STATE_PRE_HEAT:
        driveLux(sensor);
        if (sensor.tcDeciC >= 300 && sensor.irDeciC >= 300) changeState(STATE_HEATING, nowMs);
        break;
      case STATE_HEATING:
        driveLux(sensor);
        if (phaseSeconds_ >= command_.durationSeconds) { lampPwm_ = 0; fanPwm_ = 255; changeState(STATE_COOLING, nowMs); }
        break;
      case STATE_COOLING:
        lampPwm_ = 0; fanPwm_ = 255;
        if (sensor.tcDeciC <= 290 && sensor.irDeciC <= 290) changeState(STATE_STABILIZING, nowMs);
        break;
      case STATE_STABILIZING:
        lampPwm_ = 0; fanPwm_ = 150;
        if (sensor.tcDeciC > 305) changeState(STATE_COOLING, nowMs);
        else if (phaseSeconds_ >= 5) {
          if (cycleNum_ >= command_.cycles) { state_ = STATE_DONE; lampPwm_ = fanPwm_ = 0; }
          else { ++cycleNum_; changeState(STATE_PRE_HEAT, nowMs); }
        }
        break;
      default: break;
    }
  }

  void stepControlled(uint32_t nowMs, const SensorSample &sensor) {
    if (!selectedValid(sensor, command_.sensor)) {
      lampPwm_ = 0; fanPwm_ = 255; qualified_ = false;
      if (!invalidSinceMs_) invalidSinceMs_ = nowMs;
      if (nowMs - invalidSinceMs_ >= 10000UL) abort(FAULT_SENSOR_INVALID);
      return;
    }
    invalidSinceMs_ = 0;
    controlTempDeciC_ = selectedTemperature(sensor, command_.sensor);
    if (controlTempDeciC_ > command_.maxTempDeciC) { abort(FAULT_OVER_TEMPERATURE); return; }

    if (state_ == STATE_ISO_RAMP) {
      if (targetSetpointDeciC_ == INVALID_DECI_C) targetSetpointDeciC_ = controlTempDeciC_;
      uint32_t elapsed = lastControlMs_ ? nowMs - lastControlMs_ : 1000UL;
      if (elapsed > 2000UL) elapsed = 2000UL;
      const int32_t increment = static_cast<int32_t>((static_cast<int64_t>(command_.rampRateMilliCPerMin) * elapsed) / 6000LL);
      targetSetpointDeciC_ += increment > 0 ? increment : 1;
      if (targetSetpointDeciC_ > command_.targetTempDeciC) targetSetpointDeciC_ = command_.targetTempDeciC;
      driveTemperature(nowMs, targetSetpointDeciC_);
      if (targetSetpointDeciC_ >= command_.targetTempDeciC && abs(tempErrorDeciC_) <= command_.toleranceDeciC)
        changeState(STATE_ISO_QUALIFY, nowMs);
      return;
    }

    if (state_ == STATE_ISO_QUALIFY) {
      driveTemperature(nowMs, command_.targetTempDeciC);
      qualified_ = abs(tempErrorDeciC_) <= command_.toleranceDeciC;
      if (!qualified_) changeState(STATE_ISO_QUALIFY, nowMs);
      else if (nowMs - phaseStartedMs_ >= command_.qualificationSeconds * 1000UL) {
        holdStartedMs_ = lastQualificationMs_ = nowMs; qualifiedMs_ = 0; changeState(STATE_ISO_HOLD, nowMs);
      }
      return;
    }

    if (state_ == STATE_ISO_HOLD) {
      driveTemperature(nowMs, command_.targetTempDeciC);
      qualified_ = abs(tempErrorDeciC_) <= command_.toleranceDeciC;
      if (qualified_) {
        if (lastQualificationMs_) qualifiedMs_ += nowMs - lastQualificationMs_;
        lastQualificationMs_ = nowMs;
      } else lastQualificationMs_ = 0;
      if (qualifiedMs_ >= command_.holdSeconds * 1000UL) { state_ = STATE_DONE; lampPwm_ = fanPwm_ = 0; }
      return;
    }

    if (state_ == STATE_PLATEAU_HEATING || state_ == STATE_PLATEAU_CONFIRM) {
      driveLux(sensor); plateauAdd(nowMs, controlTempDeciC_);
      float slope = 0.0f, range = 0.0f, mean = 0.0f;
      const bool stable = plateauStats(nowMs, command_.plateauWindowSeconds, slope, range, mean) &&
                          fabsf(slope) <= static_cast<float>(command_.maxSlopeMilliCPerMin) &&
                          range <= static_cast<float>(command_.maxRangeDeciC);
      if (state_ == STATE_PLATEAU_HEATING && stable) { confirmationStartedMs_ = nowMs; changeState(STATE_PLATEAU_CONFIRM, nowMs); }
      else if (state_ == STATE_PLATEAU_CONFIRM && !stable) { confirmationStartedMs_ = 0; changeState(STATE_PLATEAU_HEATING, nowMs); }
      else if (state_ == STATE_PLATEAU_CONFIRM && nowMs - confirmationStartedMs_ >= command_.plateauConfirmationSeconds * 1000UL) {
        detectedPlateauDeciC_ = static_cast<int32_t>(mean + (mean >= 0 ? 0.5f : -0.5f));
        holdStartedMs_ = lastQualificationMs_ = nowMs; qualifiedMs_ = 0; integral_ = 0.0f; changeState(STATE_PLATEAU_HOLD, nowMs);
      }
      if (nowMs - startedMs_ >= command_.plateauDiscoverySeconds * 1000UL && state_ != STATE_PLATEAU_HOLD) abort(FAULT_DISCOVERY_TIMEOUT);
      return;
    }

    if (state_ == STATE_PLATEAU_HOLD) {
      if (command_.postMode == POST_PASSIVE) {
        driveLux(sensor);
        qualified_ = abs(controlTempDeciC_ - detectedPlateauDeciC_) <= command_.maxRangeDeciC;
        if (nowMs - holdStartedMs_ >= command_.holdSeconds * 1000UL) { state_ = STATE_DONE; lampPwm_ = fanPwm_ = 0; }
      } else {
        driveTemperature(nowMs, detectedPlateauDeciC_);
        qualified_ = abs(tempErrorDeciC_) <= command_.maxRangeDeciC;
        if (qualified_) {
          if (lastQualificationMs_) qualifiedMs_ += nowMs - lastQualificationMs_;
          lastQualificationMs_ = nowMs;
        } else lastQualificationMs_ = 0;
        if (qualifiedMs_ >= command_.holdSeconds * 1000UL) { state_ = STATE_DONE; lampPwm_ = fanPwm_ = 0; }
      }
    }
  }

  void plateauAdd(uint32_t nowMs, int32_t temperatureDeciC) {
    plateauTimes_[plateauNext_] = nowMs;
    plateauTemps_[plateauNext_] = temperatureDeciC;
    plateauNext_ = static_cast<uint8_t>((plateauNext_ + 1U) % PLATEAU_CAPACITY);
    if (plateauCount_ < PLATEAU_CAPACITY) ++plateauCount_;
  }

  bool plateauStats(uint32_t nowMs, uint32_t requiredSeconds, float &slopeMilliCPerMin, float &rangeDeciC, float &meanDeciC) const {
    if (plateauCount_ < 3 || requiredSeconds < 1) return false;
    const uint32_t windowMs = requiredSeconds * 1000UL;
    float sumT = 0.0f, sumY = 0.0f, sumTT = 0.0f, sumTY = 0.0f;
    int32_t minimum = 2147483647L, maximum = -2147483647L - 1L;
    uint8_t count = 0; uint32_t oldestAge = 0;
    for (uint8_t offset = 0; offset < plateauCount_; ++offset) {
      const uint8_t index = static_cast<uint8_t>((plateauNext_ + PLATEAU_CAPACITY - 1U - offset) % PLATEAU_CAPACITY);
      const uint32_t age = nowMs - plateauTimes_[index];
      if (age > windowMs) break;
      const float time = -static_cast<float>(age) / 1000.0f;
      const float temperature = static_cast<float>(plateauTemps_[index]);
      sumT += time; sumY += temperature; sumTT += time * time; sumTY += time * temperature;
      if (plateauTemps_[index] < minimum) minimum = plateauTemps_[index];
      if (plateauTemps_[index] > maximum) maximum = plateauTemps_[index];
      oldestAge = age; ++count;
    }
    if (count < 3 || oldestAge + 1000UL < windowMs) return false;
    const float divisor = count * sumTT - sumT * sumT;
    if (fabsf(divisor) < 0.00001f) return false;
    slopeMilliCPerMin = 60.0f * (count * sumTY - sumT * sumY) / divisor;
    rangeDeciC = static_cast<float>(maximum - minimum);
    meanDeciC = sumY / count;
    return true;
  }

  ControlSnapshot snapshot(uint32_t nowMs, const SensorSample &) const {
    ControlSnapshot out;
    out.totalSeconds = totalSeconds_; out.phaseSeconds = phaseSeconds_; out.cycleNum = cycleNum_;
    out.stateCode = state_; out.kind = command_.kind; out.illuminationMode = command_.illuminationMode;
    out.controlTempDeciC = controlTempDeciC_; out.tempSetpointDeciC = targetSetpointDeciC_; out.tempErrorDeciC = tempErrorDeciC_;
    out.lampPwm = lampPwm_; out.fanPwm = fanPwm_;
    out.holdWallSeconds = holdStartedMs_ ? elapsedWithoutLinkPause(nowMs, holdStartedMs_) / 1000UL : 0;
    out.holdQualifiedSeconds = qualifiedMs_ / 1000UL; out.qualified = qualified_;
    out.detectedPlateauDeciC = detectedPlateauDeciC_; out.fault = fault_;
    return out;
  }
};

}  // namespace ptkit
#endif
