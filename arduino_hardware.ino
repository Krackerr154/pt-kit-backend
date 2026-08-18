/*
 * === PT-KIT — ARDUINO UNO SAFE OFFLOAD GATEWAY ===
 *
 * This is the migration firmware paired with the root ESP32.ino offload bridge.
 * The Uno owns the physical sensors, PWM outputs, LCD, EEPROM calibration and
 * all local safety interlocks. ESP32 owns experiment state machines, ISO/plateau
 * calculations, command parsing and backend transport.
 *
 * NEVER run this alongside the legacy ESP32 firmware. Upload ESP32.ino first,
 * verify its boot banner, then upload this sketch.
 */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Adafruit_MLX90614.h>
#include <SoftwareSerial.h>
#include <max6675.h>
#include <BH1750.h>
#include <EEPROM.h>

#include "ptkit_offload_protocol.h"

#define PIN_LAMP 5
#define PIN_FAN 3
#define PIN_TC_CLK 6
#define PIN_TC_CS 7
#define PIN_TC_DO 8
#define PIN_ESP_RX 10
#define PIN_ESP_TX 11

const unsigned long SENSOR_PERIOD_MS = 1000UL;
const unsigned long STATUS_PERIOD_MS = 1000UL;
const unsigned long LINK_TIMEOUT_MS = 3500UL;
const unsigned long LINK_HARD_TIMEOUT_MS = 10000UL;
const unsigned long LINK_PAUSE_NOTIFY_MS = 1000UL;
const float ABSOLUTE_MAX_TEMP_C = 150.0f;
const int CAL_REF_PWM = 128;
const int CAL_MIN_WARMUP_S = 15;

enum LocalState : uint8_t { LOCAL_IDLE = 0, LOCAL_CAL_BARE = 6, LOCAL_CAL_TAPE = 7, LOCAL_CAL_FULL = 8 };

enum AckCode : uint8_t { ACK_OK = 0, ACK_REPLAY = 1, NACK_BAD_FRAME = 2, NACK_NOT_ARMED = 3, NACK_STALE = 4, NACK_UNSAFE = 5 };

SoftwareSerial comm(PIN_ESP_RX, PIN_ESP_TX);
LiquidCrystal_I2C lcd(0x27, 16, 2);
Adafruit_MLX90614 mlx = Adafruit_MLX90614();
MAX6675 thermocouple(PIN_TC_CLK, PIN_TC_CS, PIN_TC_DO);
BH1750 lightMeter;

float temperatureIr = NAN;
float temperatureTc = NAN;
float smoothedLux = 0.0f;
float attenuation = 1.0f;
float maxHardwareLux = 10000.0f;
float calBareLux = 0.0f;
float calTapedLux = 0.0f;
float calibrationWindow[10];

LocalState localState = LOCAL_IDLE;
uint8_t reportedState = 0;
uint8_t localFault = ptkit::FAULT_NONE;
bool armed = false;
uint16_t armedMaxTempDeciC = 0;
uint16_t lastSequence = 0;
uint16_t activeOutputTtlMs = LINK_TIMEOUT_MS;
unsigned long lastValidControlMs = 0;
unsigned long linkPauseStartedMs = 0;
unsigned long lastLinkPauseNotifyMs = 0;
bool linkPaused = false;
unsigned long lastSensorMs = 0;
unsigned long lastStatusMs = 0;
unsigned long calibrationSeconds = 0;
unsigned long lastCalibrationTickMs = 0;
int lampPwm = 0;
int fanPwm = 0;

char lineBuffer[ptkit::FRAME_MAX_CHARS];
uint8_t lineLength = 0;

static uint16_t deciC(float value) {
  if (!isfinite(value) || value < 0.0f || value > 6553.5f) return 0;
  return static_cast<uint16_t>(value * 10.0f + 0.5f);
}

static int32_t signedDeciC(float value) {
  if (!isfinite(value) || value < -214748300.0f || value > 214748300.0f) return ptkit::INVALID_DECI_C;
  return static_cast<int32_t>(value * 10.0f + (value >= 0.0f ? 0.5f : -0.5f));
}

static uint32_t luxValue(float value) {
  if (!isfinite(value) || value < 0.0f) return 0;
  if (value > 4294967000.0f) return 4294967000UL;
  return static_cast<uint32_t>(value + 0.5f);
}

static void setLamp(uint8_t pwm) {
  lampPwm = pwm;
  analogWrite(PIN_LAMP, lampPwm);
}

static void setFan(uint8_t pwm) {
  fanPwm = pwm;
  analogWrite(PIN_FAN, fanPwm);
}

static void sendFrame(const char *frame) {
  if (frame && *frame) comm.println(frame);
}

static void sendAck(uint16_t sequence, uint8_t code) {
  char frame[ptkit::FRAME_MAX_CHARS];
  if (ptkit::frameAck(frame, sizeof(frame), sequence, code)) sendFrame(frame);
}

static void sendFault(uint8_t fault) {
  char frame[ptkit::FRAME_MAX_CHARS];
  if (ptkit::frameFault(frame, sizeof(frame), fault)) sendFrame(frame);
}

static void showSafety(const char *top, const char *bottom) {
  lcd.clear();
  lcd.setCursor(0, 0); lcd.print(top);
  lcd.setCursor(0, 1); lcd.print(bottom);
}

static void sendLinkPause() {
  char frame[ptkit::FRAME_MAX_CHARS];
  if (ptkit::frameLinkPause(frame, sizeof(frame), lastSequence,
                            static_cast<uint8_t>(lampPwm), static_cast<uint8_t>(fanPwm))) sendFrame(frame);
}

static void beginLinkPause(unsigned long now) {
  if (!armed || linkPaused) return;
  linkPaused = true;
  linkPauseStartedMs = now;
  lastLinkPauseNotifyMs = now;
  localFault = ptkit::FAULT_NONE;
  showSafety("LINK PAUSED", "HOLD OUTPUT");
  sendLinkPause();
}

static void safeStop(uint8_t fault) {
  armed = false;
  linkPaused = false;
  linkPauseStartedMs = 0;
  lastLinkPauseNotifyMs = 0;
  localFault = fault;
  reportedState = (fault == ptkit::FAULT_NONE) ? 0 : 15;
  setLamp(0);
  setFan(fault == ptkit::FAULT_NONE ? 0 : 255);
  if (fault == ptkit::FAULT_LINK_TIMEOUT) showSafety("ESP32 LINK LOST", "Lamp OFF Fan ON");
  else if (fault == ptkit::FAULT_OVER_TEMPERATURE) showSafety("OVER TEMP", "Lamp OFF Fan ON");
  else if (fault == ptkit::FAULT_SENSOR_INVALID) showSafety("SENSOR FAULT", "Lamp OFF Fan ON");
  else if (fault != ptkit::FAULT_NONE) showSafety("CONTROL FAULT", "Lamp OFF Fan ON");
  if (fault != ptkit::FAULT_NONE) sendFault(fault);
}

static void readSensors() {
  temperatureIr = mlx.readObjectTempC();
  temperatureTc = thermocouple.readCelsius();
  const float rawLux = lightMeter.readLightLevel();
  const float corrected = isfinite(rawLux) && rawLux >= 0.0f ? rawLux * attenuation : NAN;
  if (isfinite(corrected)) {
    if (smoothedLux < 1.0f && corrected > 1.0f) smoothedLux = corrected;
    else smoothedLux = 0.2f * corrected + 0.8f * smoothedLux;
  }
}

static uint8_t sensorFlags() {
  uint8_t flags = 0;
  if (isfinite(temperatureIr)) flags |= ptkit::SENSOR_IR_VALID;
  if (isfinite(temperatureTc)) flags |= ptkit::SENSOR_TC_VALID;
  if (isfinite(smoothedLux)) flags |= ptkit::SENSOR_LUX_VALID;
  if ((isfinite(temperatureTc) && temperatureTc > ABSOLUTE_MAX_TEMP_C) ||
      (armed && isfinite(temperatureTc) && temperatureTc * 10.0f > static_cast<float>(armedMaxTempDeciC))) {
    flags |= ptkit::SENSOR_OVER_TEMP;
  }
  if (armed && millis() - lastValidControlMs > activeOutputTtlMs) flags |= ptkit::SENSOR_LINK_EXPIRED;
  return flags;
}

static void sendStatus() {
  char frame[ptkit::FRAME_MAX_CHARS];
  const uint8_t flags = sensorFlags();
  if (ptkit::frameSensor(frame, sizeof(frame), signedDeciC(temperatureIr), signedDeciC(temperatureTc),
                         luxValue(smoothedLux), luxValue(maxHardwareLux), flags)) sendFrame(frame);
}

static void updateCalibration() {
  if (localState == LOCAL_IDLE) return;
  const unsigned long now = millis();
  if (now - lastCalibrationTickMs < SENSOR_PERIOD_MS) return;
  lastCalibrationTickMs = now;
  ++calibrationSeconds;
  calibrationWindow[(calibrationSeconds - 1UL) % 10UL] = smoothedLux;

  lcd.setCursor(0, 0);
  if (localState == LOCAL_CAL_BARE) lcd.print("CAL: BARE      ");
  else if (localState == LOCAL_CAL_TAPE) lcd.print("CAL: TAPE      ");
  else lcd.print("CAL: FULL      ");
  lcd.setCursor(0, 1); lcd.print("Lux:"); lcd.print(static_cast<int>(smoothedLux)); lcd.print("    ");

  if (calibrationSeconds < CAL_MIN_WARMUP_S) return;
  const float oldest = calibrationWindow[calibrationSeconds % 10UL];
  if (!isfinite(oldest) || oldest <= 0.0f || fabs(oldest - smoothedLux) / oldest >= 0.01f) return;

  uint8_t phase = 0;
  if (localState == LOCAL_CAL_BARE) {
    calBareLux = smoothedLux;
    phase = 1;
  } else if (localState == LOCAL_CAL_TAPE) {
    calTapedLux = smoothedLux;
    attenuation = calTapedLux > 0.0f ? calBareLux / calTapedLux : 1.0f;
    phase = 2;
  } else {
    maxHardwareLux = smoothedLux;
    EEPROM.put(0, maxHardwareLux);
    EEPROM.put(4, attenuation);
    phase = 3;
  }

  char frame[ptkit::FRAME_MAX_CHARS];
  const uint32_t bare = luxValue(calBareLux * 10.0f);
  const uint32_t taped = luxValue(calTapedLux * 10.0f);
  const uint16_t factor = static_cast<uint16_t>(attenuation * 1000.0f + 0.5f);
  const uint32_t maximum = luxValue(maxHardwareLux * 10.0f);
  if (ptkit::frameCalibrationResult(frame, sizeof(frame), phase, bare, taped, factor, maximum)) sendFrame(frame);
  localState = LOCAL_IDLE;
  setLamp(0);
  setFan(0);
  showSafety("CAL COMPLETE", "Await command");
}

static void beginCalibration(const ptkit::CalibrationPacket &packet) {
  safeStop(ptkit::FAULT_NONE);
  localFault = ptkit::FAULT_NONE;
  calibrationSeconds = 0;
  lastCalibrationTickMs = millis();
  if (packet.phase == 1) { attenuation = 1.0f; calBareLux = 0.0f; localState = LOCAL_CAL_BARE; setLamp(CAL_REF_PWM); }
  else if (packet.phase == 2) { attenuation = 1.0f; calTapedLux = 0.0f; localState = LOCAL_CAL_TAPE; setLamp(CAL_REF_PWM); }
  else { localState = LOCAL_CAL_FULL; setLamp(255); }
  setFan(0);
  sendAck(packet.sequence, ACK_OK);
}

static bool duplicateOrStale(uint16_t sequence) {
  // Accept only strictly newer sequence numbers, with uint16 wraparound handling.
  // This prevents delayed/replayed frames from changing actuator state.
  return sequence == lastSequence || static_cast<int16_t>(sequence - lastSequence) <= 0;
}

static void handleFrame(const char *frame) {
  ptkit::ArmPacket arm;
  ptkit::OutputPacket output;
  ptkit::CalibrationPacket calibration;
  uint16_t sequence = 0;

  if (ptkit::parseStop(frame, sequence)) {
    if (duplicateOrStale(sequence)) { sendAck(sequence, ACK_REPLAY); return; }
    safeStop(ptkit::FAULT_NONE);
    lastSequence = sequence;
    sendAck(sequence, ACK_OK);
    return;
  }
  if (ptkit::parseArm(frame, arm)) {
    if (duplicateOrStale(arm.sequence)) { sendAck(arm.sequence, ACK_REPLAY); return; }
    safeStop(ptkit::FAULT_NONE);
    armed = true;
    armedMaxTempDeciC = arm.maxTempDeciC;
    activeOutputTtlMs = LINK_TIMEOUT_MS;
    linkPaused = false;
    linkPauseStartedMs = 0;
    lastLinkPauseNotifyMs = 0;
    lastSequence = arm.sequence;
    lastValidControlMs = millis();
    localFault = ptkit::FAULT_NONE;
    reportedState = 0;
    showSafety("ARMED: ESP32", "Safety local");
    sendAck(arm.sequence, ACK_OK);
    return;
  }
  if (ptkit::parseOutput(frame, output)) {
    if (duplicateOrStale(output.sequence)) { sendAck(output.sequence, ACK_REPLAY); return; }
    if (!armed) { sendAck(output.sequence, NACK_NOT_ARMED); return; }
    if (output.ttlMs > LINK_TIMEOUT_MS) { sendAck(output.sequence, NACK_UNSAFE); return; }
    const uint8_t flags = sensorFlags();
    if ((flags & ptkit::SENSOR_OVER_TEMP) || !(flags & ptkit::SENSOR_TC_VALID)) {
      safeStop((flags & ptkit::SENSOR_OVER_TEMP) ? ptkit::FAULT_OVER_TEMPERATURE : ptkit::FAULT_SENSOR_INVALID);
      sendAck(output.sequence, NACK_UNSAFE);
      return;
    }
    lastSequence = output.sequence;
    lastValidControlMs = millis();
    activeOutputTtlMs = output.ttlMs;
    reportedState = output.stateCode;
    localFault = ptkit::FAULT_NONE;
    const bool wasPaused = linkPaused;
    linkPaused = false;
    linkPauseStartedMs = 0;
    lastLinkPauseNotifyMs = 0;
    if (wasPaused) showSafety("LINK RECOVERED", "OUTPUT RESTORED");
    setLamp(output.lampPwm);
    setFan(output.fanPwm);
    sendAck(output.sequence, ACK_OK);
    return;
  }
  if (ptkit::parsePing(frame, sequence)) {
    if (duplicateOrStale(sequence)) { sendAck(sequence, ACK_REPLAY); return; }
    lastSequence = sequence;
    lastValidControlMs = millis();
    sendAck(sequence, ACK_OK);
    return;
  }
  if (ptkit::parseCalibration(frame, calibration)) {
    if (duplicateOrStale(calibration.sequence)) { sendAck(calibration.sequence, ACK_REPLAY); return; }
    lastSequence = calibration.sequence;
    beginCalibration(calibration);
    return;
  }
  sendAck(0, NACK_BAD_FRAME);
}

static void receiveFrames() {
  while (comm.available()) {
    const char c = static_cast<char>(comm.read());
    if (c == '\r') continue;
    if (c == '\n') {
      lineBuffer[lineLength] = '\0';
      if (lineLength) handleFrame(lineBuffer);
      lineLength = 0;
    } else if (lineLength + 1U < sizeof(lineBuffer)) {
      lineBuffer[lineLength++] = c;
    } else {
      lineLength = 0;
      sendAck(0, NACK_BAD_FRAME);
    }
  }
}

static void updateDisplay() {
  if (localFault != ptkit::FAULT_NONE) return;
  if (linkPaused) return;
  if (localState != LOCAL_IDLE) return;
  lcd.setCursor(0, 0);
  if (armed) { lcd.print("ESP32 ST:"); lcd.print(reportedState); lcd.print("   "); }
  else lcd.print("SYSTEM SAFE IDLE");
  lcd.setCursor(0, 1);
  lcd.print("T"); lcd.print(static_cast<int>(temperatureTc));
  lcd.print(" I"); lcd.print(static_cast<int>(temperatureIr));
  lcd.print("   ");
}

void setup() {
  comm.begin(9600);
  pinMode(PIN_LAMP, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  setLamp(0); setFan(0);

  lcd.init();
  lcd.backlight();
  Wire.setWireTimeout(3000UL, true);
  mlx.begin();
  lightMeter.begin();

  EEPROM.get(0, maxHardwareLux);
  if (!isfinite(maxHardwareLux) || maxHardwareLux <= 0.0f) maxHardwareLux = 10000.0f;
  EEPROM.get(4, attenuation);
  if (!isfinite(attenuation) || attenuation <= 0.0f) attenuation = 1.0f;

  showSafety("PT-KIT OFFLOAD", "Await ESP32 link");
}

void loop() {
  receiveFrames();
  const unsigned long now = millis();
  if (now - lastSensorMs >= SENSOR_PERIOD_MS) {
    lastSensorMs = now;
    readSensors();
    if (armed) {
      if (!isfinite(temperatureTc)) safeStop(ptkit::FAULT_SENSOR_INVALID);
      else if (temperatureTc > ABSOLUTE_MAX_TEMP_C || temperatureTc * 10.0f > static_cast<float>(armedMaxTempDeciC)) safeStop(ptkit::FAULT_OVER_TEMPERATURE);
      else if (!linkPaused && now - lastValidControlMs > LINK_TIMEOUT_MS) beginLinkPause(now);
      else if (linkPaused && now - lastValidControlMs > LINK_HARD_TIMEOUT_MS) safeStop(ptkit::FAULT_LINK_TIMEOUT);
      else if (linkPaused && now - lastLinkPauseNotifyMs >= LINK_PAUSE_NOTIFY_MS) {
        sendLinkPause();
        lastLinkPauseNotifyMs = now;
      }
    }
    updateCalibration();
    updateDisplay();
  }
  if (now - lastStatusMs >= STATUS_PERIOD_MS) {
    lastStatusMs = now;
    sendStatus();
  }
}
