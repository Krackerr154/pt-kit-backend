#include "PTKitController.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>
#ifndef ARDUINO
#include <stdio.h>
static char *ultoa(unsigned long value, char *buffer, int base) {
  if (!buffer || base != 10) return buffer;
  snprintf(buffer, 16, "%lu", value);
  return buffer;
}
static char *itoa(int value, char *buffer, int base) {
  if (!buffer || base != 10) return buffer;
  snprintf(buffer, 12, "%d", value);
  return buffer;
}
#endif

namespace {
const float MAIN_TARGET = 30.0f;
const float UNDERSHOOT = 1.0f;
const float HYSTERESIS = 0.5f;
const int STABLE_TIME = 5;
const float LUX_KP = 0.05f;
const float LUX_TOLERANCE = 50.0f;
const float EMA_ALPHA = 0.2f;
const int CAL_REF_PWM = 128;
const int CAL_MIN_WARMUP = 15;
const float TEMP_KP = 18.0f;
const float TEMP_KI = 0.35f;
const float TEMP_APPROACH_ZONE = 2.0f;

int clampPwm(int value) {
  if (value < 0) return 0;
  if (value > 255) return 255;
  return value;
}

const char *modeName(PTKitOperatingMode mode) {
  if (mode == PTKIT_NORMAL_CYCLIC) return "NORMAL_CYCLIC";
  if (mode == PTKIT_FIXED_TEMPERATURE) return "FIXED_TEMPERATURE";
  return "NATURAL_PLATEAU";
}

bool exact(const char *text, const char *expected) {
  return strcmp(text, expected) == 0;
}

bool starts(const char *text, const char *prefix) {
  return strncmp(text, prefix, strlen(prefix)) == 0;
}

void appendText(char *buffer, size_t capacity, size_t &length, const char *text) {
  if (!buffer || !text || length >= capacity) return;
  size_t available = capacity - length - 1;
  size_t count = strlen(text);
  if (count > available) count = available;
  memcpy(buffer + length, text, count);
  length += count;
  buffer[length] = '\0';
}

void appendUnsigned(char *buffer, size_t capacity, size_t &length, unsigned long value) {
  char text[16];
  ultoa(value, text, 10);
  appendText(buffer, capacity, length, text);
}

void appendSigned(char *buffer, size_t capacity, size_t &length, int value) {
  char text[12];
  itoa(value, text, 10);
  appendText(buffer, capacity, length, text);
}

void appendFloat(char *buffer, size_t capacity, size_t &length, float value, uint8_t decimals) {
  char text[24];
#ifdef ARDUINO
  dtostrf(value, 0, decimals, text);
  char *first = text;
  while (*first == ' ') ++first;
  appendText(buffer, capacity, length, first);
#else
  char format[8];
  snprintf(format, sizeof format, "%%.%uf", static_cast<unsigned int>(decimals));
  snprintf(text, sizeof text, format, (double)value);
  appendText(buffer, capacity, length, text);
#endif
}

void appendSeparator(char *buffer, size_t capacity, size_t &length) {
  appendText(buffer, capacity, length, ",");
}
}  // namespace

PTKitController::PTKitController(PTKitPlatform &platform)
    : platform_(platform), state_(PTKIT_IDLE), mode_(PTKIT_NORMAL_CYCLIC),
      illuminationMode_(TARGET_LUX), maxHardwareLux_(10000.0f), attenuation_(1.0f),
      calBareLux_(0), calTapedLux_(0), rawIr_(0), rawTc_(0), tempIr_(0), tempTc_(0),
      rawLux_(0), smoothedLux_(0), userMaxTemp_(100), targetLux_(38000),
      controlTemp_(NAN), tempSetpoint_(NAN), tempError_(NAN), detectedPlateauTemp_(NAN),
      irValid_(true), tcValid_(true), controlValid_(false), qualified_(false),
      targetSeconds_(0), targetCycles_(0), userInterval_(1), currentSeconds_(0),
      totalSeconds_(0), currentCycle_(0), stableCounter_(0), lampPwm_(0), fanPwm_(0),
      lastLoopMs_(0), lastLogMs_(0), modeStartedMs_(0), stateStartedMs_(0),
      holdStartedMs_(0), holdQualifiedMs_(0), lastQualifiedMs_(0), confirmStartedMs_(0),
      lastControlMs_(0), invalidSinceMs_(0) {
  memset(&iso_, 0, sizeof iso_);
  memset(&plateau_, 0, sizeof plateau_);
  memset(luxWindow_, 0, sizeof luxWindow_);
  piReset(pi_);
  plateauReset(plateauWindow_);
}

void PTKitController::begin() {
  platform_.loadCalibration(maxHardwareLux_, attenuation_);
  if (!isfinite(maxHardwareLux_) || maxHardwareLux_ <= 0) maxHardwareLux_ = 10000.0f;
  if (!isfinite(attenuation_) || attenuation_ <= 0) attenuation_ = 1.0f;
  setLamp(0);
  setFan(0);
}

void PTKitController::emit(const char *bytes) {
  platform_.writeUart(bytes, strlen(bytes));
}

void PTKitController::setLamp(int pwm) {
  lampPwm_ = clampPwm(pwm);
  platform_.setLampPwm((uint8_t)lampPwm_);
}

void PTKitController::setFan(int pwm) {
  fanPwm_ = clampPwm(pwm);
  platform_.setFanPwm((uint8_t)fanPwm_);
}

void PTKitController::resetRun(uint32_t now) {
  totalSeconds_ = currentSeconds_ = 0;
  currentCycle_ = 1;
  stableCounter_ = 0;
  modeStartedMs_ = stateStartedMs_ = now;
  holdStartedMs_ = holdQualifiedMs_ = lastQualifiedMs_ = confirmStartedMs_ = 0;
  qualified_ = false;
  controlValid_ = false;
  controlTemp_ = tempSetpoint_ = tempError_ = detectedPlateauTemp_ = NAN;
  lastLogMs_ = now;
}

bool PTKitController::parseSet(const char *text) {
  char fields[6][20];
  int count = splitFields(text, fields, 6);
  if (count != 5 && count != 6) return false;
  if (strcmp(fields[0], "SET")) return false;
  unsigned long duration = 0, cycles = 0, interval = 0;
  float maximum = 0, lux = maxHardwareLux_;
  if (!parseUnsignedField(fields[1], duration) || !parseUnsignedField(fields[2], cycles, 32767UL) ||
      !parseFloatField(fields[3], maximum) || !parseUnsignedField(fields[4], interval, 32767UL)) return false;
  if (count == 6 && !parseFloatField(fields[5], lux)) return false;
  // Preserve the sketch's permissive/defaulting quirks rather than SET2 strictness.
  targetSeconds_ = duration ? duration : 60;
  targetCycles_ = cycles;
  userMaxTemp_ = maximum < 50.0f ? 100.0f : maximum;
  userInterval_ = interval < 1 ? 1 : interval;
  targetLux_ = lux;
  return true;
}

bool PTKitController::command(const char *bytes, size_t length) {
  if (!bytes) return false;
  if (length > 159) return false;
  char text[160];
  memcpy(text, bytes, length);
  text[length] = 0;
  while (length && (static_cast<unsigned char>(text[length - 1]) <= ' ')) text[--length] = 0;
  size_t beginAt = 0;
  while (static_cast<unsigned char>(text[beginAt]) <= ' ' && text[beginAt] != 0) ++beginAt;
  if (beginAt) memmove(text, text + beginAt, strlen(text + beginAt) + 1);
  const uint32_t now = platform_.nowMs();

  if (exact(text, "STOP")) {
    stop();
    return true;
  }
  if (starts(text, "SET:")) {
    if (!parseSet(text)) return false;
    // Preserve the physical sketch's operator-facing two-second confirmation
    // pause.  The run timers start after the pause, not before it.
    platform_.blockingDelay(2000);
    resetRun(platform_.nowMs());
    mode_ = PTKIT_NORMAL_CYCLIC;
    illuminationMode_ = TARGET_LUX;
    setLamp((int)((targetLux_ / maxHardwareLux_) * 255.0f));
    state_ = PTKIT_PRE_HEAT;
    platform_.clearDisplay();
    return true;
  }
  if (starts(text, "SET2:")) {
    MaxOutputNormalCommand parsed;
    if (!parseMaxOutputNormalCommand(text, parsed)) {
      emit("ERR:SET2\n");
      return false;
    }
    targetSeconds_ = parsed.durationSeconds;
    targetCycles_ = parsed.cycles;
    userMaxTemp_ = parsed.maxTemp;
    userInterval_ = parsed.logInterval;
    resetRun(now);
    mode_ = PTKIT_NORMAL_CYCLIC;
    illuminationMode_ = MAX_OUTPUT;
    setLamp(255);
    state_ = PTKIT_PRE_HEAT;
    platform_.clearDisplay();
    return true;
  }
  if (starts(text, "ISO1:")) {
    IsoCommand parsed;
    if (!parseIsoCommand(text, parsed)) {
      emit("ERR:ISO1\n");
      return false;
    }
    iso_ = parsed;
    userMaxTemp_ = parsed.maxTemp;
    userInterval_ = parsed.logInterval;
    resetRun(now);
    mode_ = PTKIT_FIXED_TEMPERATURE;
    illuminationMode_ = TEMPERATURE_CONTROLLED;
    piReset(pi_);
    state_ = PTKIT_ISO_RAMP;
    platform_.clearDisplay();
    return true;
  }
  if (starts(text, "PLAT1:") || starts(text, "PLAT2:")) {
    PlateauCommand parsed;
    if (!parsePlateauCommand(text, parsed)) {
      emit("ERR:PLAT\n");
      return false;
    }
    plateau_ = parsed;
    targetLux_ = parsed.targetLux;
    userMaxTemp_ = parsed.maxTemp;
    userInterval_ = parsed.logInterval;
    resetRun(now);
    mode_ = PTKIT_NATURAL_PLATEAU;
    illuminationMode_ = parsed.illuminationMode;
    plateauReset(plateauWindow_);
    piReset(pi_);
    setLamp(illuminationMode_ == MAX_OUTPUT ? 255 : (int)((targetLux_ / maxHardwareLux_) * 255.0f));
    state_ = PTKIT_PLATEAU_HEATING;
    platform_.clearDisplay();
    return true;
  }
  if (exact(text, "CAL_BARE") || exact(text, "CAL_TAPE") || exact(text, "CAL_FULL")) {
    currentSeconds_ = 0;
    if (exact(text, "CAL_BARE")) {
      attenuation_ = 1.0f;
      calBareLux_ = 0;
      state_ = PTKIT_CAL_BARE;
      setLamp(CAL_REF_PWM);
    } else if (exact(text, "CAL_TAPE")) {
      attenuation_ = 1.0f;
      calTapedLux_ = 0;
      state_ = PTKIT_CAL_TAPE;
      setLamp(CAL_REF_PWM);
    } else {
      state_ = PTKIT_CAL_FULL;
      setLamp(255);
    }
    platform_.clearDisplay();
    return true;
  }
  return false;
}

void PTKitController::stop() {
  state_ = PTKIT_IDLE;
  currentCycle_ = 0;
  currentSeconds_ = totalSeconds_ = 0;
  stableCounter_ = 0;
  setLamp(0);
  setFan(0);
  platform_.clearDisplay();
}

void PTKitController::abort(const char *reason) {
  state_ = PTKIT_ABORTED;
  setLamp(0);
  setFan(255);
  emit("ABORT:");
  emit(reason);
  emit("\n");
}

void PTKitController::conditionSensors(const PTKitRawSensors &raw) {
  rawIr_ = raw.tempIrC;
  rawTc_ = raw.tempTcC;
  bool legacy = mode_ == PTKIT_NORMAL_CYCLIC || state_ == PTKIT_CAL_BARE ||
                state_ == PTKIT_CAL_TAPE || state_ == PTKIT_CAL_FULL;
  SensorTemperatures temperatures = sensorTemperatures(rawIr_, rawTc_, legacy);
  irValid_ = temperatures.irValid;
  tcValid_ = temperatures.tcValid;
  tempIr_ = temperatures.irExposed;
  tempTc_ = temperatures.tcExposed;
  rawLux_ = isfinite(raw.lux) ? raw.lux : 0.0f;
  float corrected = rawLux_ * attenuation_;
  smoothedLux_ = EMA_ALPHA * corrected + (1.0f - EMA_ALPHA) * smoothedLux_;
  if (smoothedLux_ < 1.0f && corrected > 1.0f) smoothedLux_ = corrected;
}

bool PTKitController::step(const PTKitRawSensors &raw) {
  uint32_t now = platform_.nowMs();
  if ((uint32_t)(now - lastLoopMs_) < 1000U) return false;
  lastLoopMs_ = now;  // deliberately skip catch-up
  conditionSensors(raw);
  if (state_ != PTKIT_IDLE && state_ != PTKIT_DONE) ++totalSeconds_;

  if (tempTc_ > 150.0f || tempTc_ > userMaxTemp_) {
    platform_.blockingDelay(50);
    float confirmed = platform_.confirmThermocoupleC();
    if ((confirmed > 150.0f || confirmed > userMaxTemp_) && state_ != PTKIT_IDLE && state_ != PTKIT_DONE) {
      platform_.blockingDelay(3000);
      stop();  // current forceStop overheat behavior is IDLE, not ABORTED
    }
  }

  if (state_ != PTKIT_IDLE && state_ != PTKIT_DONE) {
    if (state_ == PTKIT_CAL_BARE || state_ == PTKIT_CAL_TAPE || state_ == PTKIT_CAL_FULL) runCalibration();
    else if (mode_ == PTKIT_NORMAL_CYCLIC) runNormal();
    else runControlled(now);
  } else if (state_ == PTKIT_DONE) {
    handleDone();
  } else {
    setLamp(0);
    setFan(0);
  }
  emitTelemetry();
  return true;
}

void PTKitController::driveIllumination() {
  if (illuminationMode_ == MAX_OUTPUT) setLamp(255);
  else {
    float error = targetLux_ - smoothedLux_;
    if (fabs(error) > LUX_TOLERANCE) setLamp((int)(lampPwm_ + error * LUX_KP));
  }
}

void PTKitController::runNormal() {
  switch (state_) {
    case PTKIT_PRE_HEAT:
      ++currentSeconds_;
      setLamp(lampPwm_);
      setFan(0);
      display("PRE-HEAT");
      if (tempTc_ >= 30.0f && tempIr_ >= 30.0f) {
        state_ = PTKIT_HEATING;
        currentSeconds_ = 0;
        platform_.clearDisplay();
      }
      break;
    case PTKIT_HEATING:
      ++currentSeconds_;
      driveIllumination();
      setFan(0);
      display("HEAT");
      if (currentSeconds_ >= targetSeconds_) {
        setLamp(0);
        state_ = PTKIT_COOLING;
        currentSeconds_ = 0;
        platform_.clearDisplay();
      }
      break;
    case PTKIT_COOLING:
      ++currentSeconds_;
      setLamp(0);
      setFan(255);
      display("COOL");
      if (tempTc_ <= MAIN_TARGET - UNDERSHOOT && tempIr_ <= MAIN_TARGET - UNDERSHOOT) {
        state_ = PTKIT_STABILIZING;
        stableCounter_ = 0;
        currentSeconds_ = 0;
        platform_.clearDisplay();
      }
      break;
    case PTKIT_STABILIZING:
      ++currentSeconds_;
      setLamp(0);
      setFan(150);
      ++stableCounter_;
      display("STABIL");
      if (tempTc_ > MAIN_TARGET + HYSTERESIS) {
        state_ = PTKIT_COOLING;
        currentSeconds_ = 0;
        platform_.clearDisplay();
      } else if (stableCounter_ >= STABLE_TIME) {
        if ((uint32_t)currentCycle_ >= targetCycles_) state_ = PTKIT_DONE;
        else {
          ++currentCycle_;
          state_ = PTKIT_PRE_HEAT;
          currentSeconds_ = 0;
        }
        platform_.clearDisplay();
      }
      break;
    default: break;
  }
}

void PTKitController::runCalibration() {
  ++currentSeconds_;
  setLamp(state_ == PTKIT_CAL_FULL ? 255 : CAL_REF_PWM);
  luxWindow_[(currentSeconds_ - 1) % 10] = smoothedLux_;
  if (currentSeconds_ < (uint32_t)CAL_MIN_WARMUP) return;
  float oldest = luxWindow_[currentSeconds_ % 10];
  if (oldest <= 0) return;
  if (fabs(oldest - smoothedLux_) / oldest >= 0.01f) return;

  char line[128];
  size_t length = 0;
  if (state_ == PTKIT_CAL_BARE) {
    calBareLux_ = smoothedLux_;
    line[0] = '\0';
    appendText(line, sizeof line, length, "CALBARE:");
    appendFloat(line, sizeof line, length, calBareLux_, 1);
    appendText(line, sizeof line, length, "\n");
    emit(line);
    platform_.blockingDelay(300);
    emit(line);
    state_ = PTKIT_IDLE;
    setLamp(0);
  } else if (state_ == PTKIT_CAL_TAPE) {
    calTapedLux_ = smoothedLux_;
    attenuation_ = calTapedLux_ > 0 ? calBareLux_ / calTapedLux_ : 1.0f;
    line[0] = '\0';
    length = 0;
    appendText(line, sizeof line, length, "CALTAPE:");
    appendFloat(line, sizeof line, length, calTapedLux_, 1);
    appendText(line, sizeof line, length, ":");
    appendFloat(line, sizeof line, length, attenuation_, 3);
    appendText(line, sizeof line, length, "\n");
    emit(line);
    platform_.blockingDelay(300);
    emit(line);
    state_ = PTKIT_IDLE;
    setLamp(0);
  } else {
    maxHardwareLux_ = smoothedLux_;
    platform_.saveCalibration(maxHardwareLux_, attenuation_);
    line[0] = '\0';
    length = 0;
    appendText(line, sizeof line, length, "CALRESULT:");
    appendFloat(line, sizeof line, length, calBareLux_, 1);
    appendSeparator(line, sizeof line, length);
    appendFloat(line, sizeof line, length, calTapedLux_, 1);
    appendSeparator(line, sizeof line, length);
    appendFloat(line, sizeof line, length, attenuation_, 3);
    appendSeparator(line, sizeof line, length);
    appendFloat(line, sizeof line, length, maxHardwareLux_, 1);
    appendText(line, sizeof line, length, "\n");
    emit(line);
    platform_.blockingDelay(500);
    emit(line);
    line[0] = '\0';
    length = 0;
    appendText(line, sizeof line, length, "MAXLUX:");
    appendFloat(line, sizeof line, length, maxHardwareLux_, 2);
    appendText(line, sizeof line, length, "\n");
    emit(line);
    platform_.blockingDelay(3000);
    stop();
  }
}

void PTKitController::driveTemperature(float target, uint32_t now) {
  float dt = lastControlMs_ ? (uint32_t)(now - lastControlMs_) / 1000.0f : 1.0f;
  if (dt > 2.0f) dt = 2.0f;
  lastControlMs_ = now;
  tempError_ = target - controlTemp_;
  setLamp((int)piStep(pi_, target, controlTemp_, dt, TEMP_KP, TEMP_KI, 255, TEMP_APPROACH_ZONE));
  setFan(0);
}

void PTKitController::qualifiedHold(float target, float tolerance, uint32_t seconds, uint32_t now) {
  qualified_ = controlValid_ && fabs(controlTemp_ - target) <= tolerance;
  if (qualified_) {
    if (lastQualifiedMs_) holdQualifiedMs_ += (uint32_t)(now - lastQualifiedMs_);
    lastQualifiedMs_ = now;
  } else lastQualifiedMs_ = 0;
  driveTemperature(target, now);
  if (holdQualifiedMs_ >= seconds * 1000UL) state_ = PTKIT_DONE;
}

void PTKitController::runControlled(uint32_t now) {
  currentSeconds_ = (uint32_t)(now - stateStartedMs_) / 1000U;
  ControlSensor sensor = mode_ == PTKIT_FIXED_TEMPERATURE ? iso_.sensor : plateau_.sensor;
  controlTemp_ = sensor == SENSOR_TC ? rawTc_ : rawIr_;
  controlValid_ = sensor == SENSOR_TC ? tcValid_ : irValid_;
  if (!controlValid_) {
    qualified_ = false;
    setLamp(0);
    setFan(255);
    if (!invalidSinceMs_) invalidSinceMs_ = now;
    if (invalidSensorAbortDue(now, invalidSinceMs_)) abort("SENSOR_INVALID");
    display("SENSOR INVALID");
    return;
  }
  invalidSinceMs_ = 0;
  if (controlTemp_ > userMaxTemp_) {
    abort("MAX_TEMP");
    return;
  }

  if (state_ == PTKIT_ISO_RAMP) {
    if (!isfinite(tempSetpoint_)) tempSetpoint_ = controlTemp_;
    tempSetpoint_ += iso_.rampRate / 60.0f;  // per controller tick, not elapsed time
    if (tempSetpoint_ > iso_.targetTemp) tempSetpoint_ = iso_.targetTemp;
    driveTemperature(tempSetpoint_, now);
    display("ISO RAMP");
    if (tempSetpoint_ >= iso_.targetTemp && fabs(tempError_) <= iso_.tolerance) {
      state_ = PTKIT_ISO_QUALIFY;
      stateStartedMs_ = now;
    }
  } else if (state_ == PTKIT_ISO_QUALIFY) {
    tempSetpoint_ = iso_.targetTemp;
    driveTemperature(tempSetpoint_, now);
    qualified_ = fabs(tempError_) <= iso_.tolerance;
    display("ISO QUALIFY");
    if (!qualified_) stateStartedMs_ = now;
    else if ((uint32_t)(now - stateStartedMs_) >= iso_.qualificationSeconds * 1000UL) {
      state_ = PTKIT_ISO_HOLD;
      holdStartedMs_ = lastQualifiedMs_ = now;
      holdQualifiedMs_ = 0;
      stateStartedMs_ = now;
    }
  } else if (state_ == PTKIT_ISO_HOLD) {
    tempSetpoint_ = iso_.targetTemp;
    qualifiedHold(tempSetpoint_, iso_.tolerance, iso_.holdSeconds, now);
    display("ISO HOLD");
  } else if (state_ == PTKIT_PLATEAU_HEATING || state_ == PTKIT_PLATEAU_CONFIRM) {
    driveIllumination();
    plateauAdd(plateauWindow_, (uint32_t)(now - modeStartedMs_) / 1000.0f, controlTemp_);
    PlateauStats stats = plateauStats(plateauWindow_, plateau_.windowSeconds);
    bool okay = stats.valid && fabs(stats.slopePerMin) <= plateau_.maxSlope && stats.peakToPeak <= plateau_.maxPeakToPeak;
    if (state_ == PTKIT_PLATEAU_HEATING && okay) {
      state_ = PTKIT_PLATEAU_CONFIRM;
      confirmStartedMs_ = now;
    } else if (state_ == PTKIT_PLATEAU_CONFIRM && !okay) {
      state_ = PTKIT_PLATEAU_HEATING;
      confirmStartedMs_ = 0;
    } else if (state_ == PTKIT_PLATEAU_CONFIRM && (uint32_t)(now - confirmStartedMs_) >= plateau_.confirmationSeconds * 1000UL) {
      detectedPlateauTemp_ = stats.mean;
      state_ = PTKIT_PLATEAU_HOLD;
      holdStartedMs_ = lastQualifiedMs_ = now;
      holdQualifiedMs_ = 0;
      piReset(pi_);
    }
    if ((uint32_t)(now - modeStartedMs_) >= plateau_.maxDiscoverySeconds * 1000UL && state_ != PTKIT_PLATEAU_HOLD) abort("DISCOVERY_TIMEOUT");
    display(state_ == PTKIT_PLATEAU_CONFIRM ? "PLAT CONFIRM" : "PLAT HEAT");
  } else if (state_ == PTKIT_PLATEAU_HOLD) {
    tempSetpoint_ = detectedPlateauTemp_;
    if (plateau_.postMode == POST_PASSIVE) {
      driveIllumination();
      qualified_ = controlValid_ && fabs(controlTemp_ - detectedPlateauTemp_) <= plateau_.maxPeakToPeak;
      if ((uint32_t)(now - holdStartedMs_) >= plateau_.holdSeconds * 1000UL) state_ = PTKIT_DONE;
    } else qualifiedHold(tempSetpoint_, plateau_.maxPeakToPeak, plateau_.holdSeconds, now);
    display("PLAT HOLD");
  } else if (state_ == PTKIT_ABORTED) {
    setLamp(0);
    setFan(255);
    display("ABORTED");
  }
}

void PTKitController::display(const char *stateText) {
  char line1[32], line2[32];
  strcpy(line1, stateText);
  char *p = line1 + strlen(line1);
  ultoa(currentSeconds_, p, 10);
  line2[0] = 'C'; line2[1] = ':';
  itoa(currentCycle_, line2 + 2, 10);
  p = line2 + strlen(line2);
  *p++ = ' '; *p++ = 'T';
  itoa((int)tempTc_, p, 10);
  p += strlen(p);
  *p++ = ' '; *p++ = 'I';
  itoa((int)tempIr_, p, 10);
  platform_.showDisplay(line1, line2);
}

void PTKitController::handleDone() {
  setLamp(0);
  setFan(0);
  platform_.showDisplay("DONE! Saving...", "");
  platform_.blockingDelay(2000);
  for (int i = 0; i < 3; ++i) {
    emitTelemetry();
    platform_.blockingDelay(500);
  }
  state_ = PTKIT_IDLE;
  currentCycle_ = 0;
  currentSeconds_ = totalSeconds_ = 0;
  platform_.clearDisplay();
}

void PTKitController::emitTelemetry() {
  uint32_t now = platform_.nowMs();
  int save = 0;
  if (state_ != PTKIT_IDLE && ((uint32_t)(now - lastLogMs_) >= userInterval_ * 1000UL || state_ == PTKIT_DONE)) {
    save = 1;
    lastLogMs_ = now;
  }

  char line[160];
  size_t length = 0;
  line[0] = '\0';
  appendUnsigned(line, sizeof line, length, totalSeconds_);
  appendSeparator(line, sizeof line, length);
  appendUnsigned(line, sizeof line, length, currentSeconds_);
  appendSeparator(line, sizeof line, length);
  appendSigned(line, sizeof line, length, currentCycle_);
  appendSeparator(line, sizeof line, length);
  appendSigned(line, sizeof line, length, (int)state_);
  appendSeparator(line, sizeof line, length);
  appendFloat(line, sizeof line, length, tempIr_, 1);
  appendSeparator(line, sizeof line, length);
  appendFloat(line, sizeof line, length, tempTc_, 1);
  appendSeparator(line, sizeof line, length);
  appendFloat(line, sizeof line, length, smoothedLux_, 1);
  appendSeparator(line, sizeof line, length);
  appendSigned(line, sizeof line, length, save);
  appendSeparator(line, sizeof line, length);
  appendText(line, sizeof line, length, modeName(mode_));
  appendSeparator(line, sizeof line, length);
  appendFloat(line, sizeof line, length, controlTemp_, 2);
  appendSeparator(line, sizeof line, length);
  appendFloat(line, sizeof line, length, tempSetpoint_, 2);
  appendSeparator(line, sizeof line, length);
  appendFloat(line, sizeof line, length, tempError_, 2);
  appendSeparator(line, sizeof line, length);
  appendSigned(line, sizeof line, length, lampPwm_);
  appendSeparator(line, sizeof line, length);
  appendUnsigned(line, sizeof line, length, holdStartedMs_ ? (uint32_t)(now - holdStartedMs_) / 1000U : 0U);
  appendSeparator(line, sizeof line, length);
  appendUnsigned(line, sizeof line, length, holdQualifiedMs_ / 1000U);
  appendSeparator(line, sizeof line, length);
  appendSigned(line, sizeof line, length, qualified_ ? 1 : 0);
  appendSeparator(line, sizeof line, length);
  appendFloat(line, sizeof line, length, detectedPlateauTemp_, 2);
  appendText(line, sizeof line, length, "\n");
  emit(line);
}

PTKitSnapshot PTKitController::snapshot() const {
  PTKitSnapshot result;
  result.nowMs = platform_.nowMs();
  result.totalSeconds = totalSeconds_;
  result.stateSeconds = currentSeconds_;
  result.holdElapsedSeconds = holdStartedMs_ ? (uint32_t)(result.nowMs - holdStartedMs_) / 1000U : 0;
  result.holdQualifiedSeconds = holdQualifiedMs_ / 1000U;
  result.cycle = currentCycle_;
  result.state = state_;
  result.mode = mode_;
  result.illuminationMode = illuminationMode_;
  result.tempIrC = tempIr_;
  result.tempTcC = tempTc_;
  result.smoothedLux = smoothedLux_;
  result.controlTempC = controlTemp_;
  result.tempSetpointC = tempSetpoint_;
  result.tempErrorC = tempError_;
  result.detectedPlateauTempC = detectedPlateauTemp_;
  result.lampPwm = (uint8_t)lampPwm_;
  result.fanPwm = (uint8_t)fanPwm_;
  result.tempIrValid = irValid_;
  result.tempTcValid = tcValid_;
  result.controlTempValid = controlValid_;
  result.qualified = qualified_;
  return result;
}
