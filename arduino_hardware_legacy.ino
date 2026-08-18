/*
 * === PT-KIT — ARDUINO UNO SINGLE-FILE FIRMWARE ===
 *
 * NORMAL_CYCLIC + FIXED_TEMPERATURE (ISO) + NATURAL_PLATEAU
 * Commands: SET, SET2, ISO1, PLAT1, PLAT2, STOP, CAL_BARE/TAPE/FULL, IP:
 */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Adafruit_MLX90614.h>
#include <SoftwareSerial.h>
#include <max6675.h>
#include <BH1750.h>
#include <EEPROM.h>


// --- PIN MAPPING ---
#define PIN_LAMP    5
#define PIN_FAN     3
#define PIN_TC_CLK  6
#define PIN_TC_CS   7
#define PIN_TC_DO   8
#define PIN_ESP_RX  10
#define PIN_ESP_TX  11


// --- LOGIC CONSTANTS ---
const float MAIN_TARGET    = 30.0;
const float UNDERSHOOT     = 1.0;
const float HYSTERESIS     = 0.5;
const int   STABLE_TIME    = 5;
const float LUX_KP         = 0.05;
const float LUX_TOLERANCE  = 50.0;
const float EMA_ALPHA      = 0.2;
const int   CAL_REF_PWM    = 128;
const int   CAL_MIN_WARMUP = 15;
const float TEMP_KP        = 18.0;
const float TEMP_KI        = 0.35;
const float TEMP_APPROACH  = 2.0;


// --- OBJECTS ---
SoftwareSerial comm(PIN_ESP_RX, PIN_ESP_TX);
LiquidCrystal_I2C lcd(0x27, 16, 2);
Adafruit_MLX90614 mlx = Adafruit_MLX90614();
MAX6675 thermocouple(PIN_TC_CLK, PIN_TC_CS, PIN_TC_DO);
BH1750 lightMeter;


// --- ENUMS ---
enum State {
  IDLE, PRE_HEAT, HEATING, COOLING, STABILIZING, DONE,
  CAL_BARE, CAL_TAPE, CAL_FULL,
  ISO_RAMP, ISO_QUALIFY, ISO_HOLD,
  PLATEAU_HEATING, PLATEAU_CONFIRM, PLATEAU_HOLD,
  ABORTED
};
enum OpMode  { NORMAL_CYCLIC, FIXED_TEMPERATURE, NATURAL_PLATEAU };
enum CtrlSns { SENSOR_TC, SENSOR_IR };
enum PostPlt { POST_PASSIVE, POST_REGULATED };
enum IllMode { TARGET_LUX, MAX_OUTPUT, TEMPERATURE_CONTROLLED };


// --- COMMAND STRUCTS ---
struct IsoCmd {
  float targetTemp, tolerance, maxTemp, rampRate;
  unsigned long holdSeconds, qualificationSeconds, logInterval;
  CtrlSns sensor;
};
struct PlateauCmd {
  float targetLux, maxSlope, maxPeakToPeak, maxTemp;
  unsigned long holdSeconds, windowSeconds, confirmationSeconds, maxDiscoverySeconds, logInterval;
  CtrlSns sensor;
  PostPlt postMode;
  IllMode illuminationMode;
};
struct MaxOutCmd {
  unsigned long durationSeconds, cycles, logInterval;
  float maxTemp;
};


// --- PLATEAU WINDOW ---
#define PLAT_CAP 30
struct PlatWin {
  uint32_t t[PLAT_CAP];
  float y[PLAT_CAP];
  int count, next;
};
struct PlatStats { bool valid; float slopePerMin, peakToPeak, mean; };


// --- PI CONTROLLER ---
// Arduino.h defines PI as the mathematical constant, so this type must not be
// named PI or the preprocessor will replace it before compilation.
struct PIControllerState {
  float integral, lastOutput;
};


// --- STATE VARIABLES ---
State curState = IDLE;
OpMode mode = NORMAL_CYCLIC;
IllMode illum = TARGET_LUX;
IsoCmd iso; PlateauCmd plat; MaxOutCmd maxo;
PIControllerState tempPI; PlatWin platWin;
char espIP[20] = "";
bool wifiOk = false;
float tempIR, tempTC, rawLux, smoothedLux;
float userMaxTemp = 100.0, targetLux = 38000.0;
float maxHwLux = 10000.0, atten = 1.0, calBare = 0, calTaped = 0;
float ctrlTemp = NAN, setpoint = NAN, errTemp = NAN, detPlatTemp = NAN;
bool ctrlValid = false, qualified = false;
unsigned long curSec = 0, totalSec = 0, targSec = 0;
int targCycles = 0, cycleNum = 0, stableCnt = 0;
int lampPWM = 0, fanPWM = 0;
unsigned long modeStart = 0, stateStart = 0, holdStart = 0;
unsigned long holdQual = 0, lastQual = 0, confirmStart = 0;
unsigned long lastCtrl = 0, invalidSince = 0;
unsigned long lastLoop = 0, lastLog = 0, lastHb = 0;
unsigned long lastScroll = 0; int scrollPos = 0;
int userInterval = 1;
float luxWin[10];


// --- HELPERS ---
void platReset(PlatWin &w) { w.count = w.next = 0; }
void piReset(PIControllerState &p) { p.integral = p.lastOutput = 0; }

void platAdd(PlatWin &w, float t, float y) {
  if (!isfinite(t) || !isfinite(y)) return;
  w.t[w.next] = (uint32_t)(t * 10.0f);
  w.y[w.next] = y;
  w.next = (w.next + 1) % PLAT_CAP;
  if (w.count < PLAT_CAP) w.count++;
}

PlatStats platCalc(const PlatWin &w, unsigned long req) {
  PlatStats r = {false, 0, 0, 0};
  if (w.count < 3 || req < 1) return r;
  int newest = (w.next - 1 + PLAT_CAP) % PLAT_CAP;
  uint32_t newestT = w.t[newest];
  uint32_t span = req * 10UL;
  int n = 0; double st = 0, sy = 0, stt = 0, sty = 0;
  float mn = INFINITY, mx = -INFINITY;
  uint32_t oldestAge = 0;
  for (int k = 0; k < w.count; k++) {
    int i = (w.next - 1 - k + PLAT_CAP) % PLAT_CAP;
    uint32_t age = newestT - w.t[i];
    if (age > span) break;
    double t = -(double)age / 10.0, y = w.y[i];
    st += t; sy += y; stt += t * t; sty += t * y;
    if (y < mn) mn = y; if (y > mx) mx = y;
    oldestAge = age; n++;
  }
  if (n < 3 || oldestAge + 10 < span) return r;
  double d = n * stt - st * st;
  if (fabs(d) < 1e-9) return r;
  r.valid = true;
  r.slopePerMin = (float)(60 * (n * sty - st * sy) / d);
  r.peakToPeak = mx - mn;
  r.mean = (float)(sy / n);
  return r;
}

float piStep(PIControllerState &p, float set, float meas, float dt, float kp, float ki, float maxOut) {
  float e = set - meas;
  float cand = p.integral + ki * e * dt;
  float cap = maxOut;
  float raw = kp * e + cand;
  float out = raw;
  if (out < 0) out = 0; if (out > cap) out = cap;
  if ((raw >= 0 && raw <= cap) || (raw > cap && e < 0) || (raw < 0 && e > 0))
    p.integral = cand;
  p.lastOutput = out;
  return out;
}

// --- PARSING ---
bool parseUlong(const char *s, unsigned long &v) {
  if (!s || !*s) return false;
  v = 0;
  for (const char *p = s; *p; p++) {
    if (*p < '0' || *p > '9') return false;
    v = v * 10 + (*p - '0');
  }
  return true;
}

bool parseFloat(const char *s, float &v) {
  if (!s || !*s) return false;
  char *end;
  v = strtod(s, &end);
  return end != s && *end == 0 && isfinite(v);
}

int splitFields(const char *in, char out[][20], int max) {
  int n = 0, j = 0;
  if (!in) return 0;
  for (; *in && n < max; in++) {
    if (*in == ':') { out[n][j] = 0; n++; j = 0; }
    else if (j < 19) out[n][j++] = *in;
    else return 0;
  }
  if (n < max) { out[n][j] = 0; n++; }
  return n;
}

CtrlSns parseSensor(const char *s) {
  if (strcmp(s, "TC") == 0) return SENSOR_TC;
  return SENSOR_IR;
}

void resetRun(unsigned long now) {
  totalSec = curSec = 0; cycleNum = 1; stableCnt = 0;
  modeStart = stateStart = now;
  holdStart = holdQual = lastQual = confirmStart = 0;
  qualified = false; ctrlValid = false;
  ctrlTemp = setpoint = errTemp = detPlatTemp = NAN;
  lastLog = now;
}

void forceStop() {
  curState = IDLE; cycleNum = 0; curSec = totalSec = 0;
  stableCnt = 0; lampPWM = 0;
  analogWrite(PIN_LAMP, 0); analogWrite(PIN_FAN, 0);
  lcd.clear();
}

void abortRun(const char *reason) {
  curState = ABORTED; lampPWM = 0;
  analogWrite(PIN_LAMP, 0); analogWrite(PIN_FAN, 255);
  comm.print("ABORT:"); comm.println(reason);
}


// --- SETUP ---
void setup() {
  comm.begin(9600);

  pinMode(PIN_LAMP, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  analogWrite(PIN_LAMP, 0);
  analogWrite(PIN_FAN, 0);

  lcd.init(); lcd.backlight();
  mlx.begin();
  lightMeter.begin();

  // Load EEPROM calibration
  EEPROM.get(0, maxHwLux);
  if (isnan(maxHwLux) || maxHwLux <= 0) maxHwLux = 10000.0;
  EEPROM.get(4, atten);
  if (isnan(atten) || atten <= 0) atten = 1.0;

  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("System Booting..");
  delay(1000);

  lcd.clear();
  lcd.setCursor(0, 0); lcd.print("Wait WiFi...");

  memset(&iso, 0, sizeof(iso));
  memset(&plat, 0, sizeof(plat));
  piReset(tempPI);
  platReset(platWin);
}


// --- SENSOR READ ---
void readSensors() {
  tempIR = mlx.readObjectTempC();
  tempTC = thermocouple.readCelsius();
  rawLux = lightMeter.readLightLevel();
  if (isnan(rawLux)) rawLux = 0.0;
  float corrected = rawLux * atten;
  smoothedLux = EMA_ALPHA * corrected + (1.0 - EMA_ALPHA) * smoothedLux;
  if (smoothedLux < 1.0 && corrected > 1.0) smoothedLux = corrected;
}


// --- LCD ---
void showLCD(const char *s) {
  lcd.setCursor(0, 0); lcd.print(s);
  if (curState == HEATING) {
    char buf[20]; ultoa(curSec, buf, 10);
    lcd.print(" "); lcd.print(curSec); lcd.print("/"); lcd.print(targSec);
  } else {
    lcd.print(" "); lcd.print(curSec);
  }
  lcd.setCursor(0, 1);
  lcd.print("C:"); lcd.print(cycleNum);
  lcd.print(" T"); lcd.print((int)tempTC);
  lcd.print(" I"); lcd.print((int)tempIR);
}


// --- ACTUATORS ---
void doLamp(int pwm) {
  lampPWM = constrain(pwm, 0, 255);
  analogWrite(PIN_LAMP, lampPWM);
}
void doFan(int pwm) {
  fanPWM = constrain(pwm, 0, 255);
  analogWrite(PIN_FAN, fanPWM);
}

void luxCtrl() {
  float e = targetLux - smoothedLux;
  if (abs(e) > LUX_TOLERANCE) doLamp(lampPWM + (int)(e * LUX_KP));
}

void tempDrive(float target) {
  unsigned long now = millis();
  float dt = lastCtrl ? min((now - lastCtrl) / 1000.0f, 2.0f) : 1.0f;
  lastCtrl = now;
  errTemp = target - ctrlTemp;
  doLamp((int)piStep(tempPI, target, ctrlTemp, dt, TEMP_KP, TEMP_KI, 255));
  doFan(0);
}

void qualHold(float target, float tol, unsigned long sec) {
  unsigned long now = millis();
  qualified = ctrlValid && fabs(ctrlTemp - target) <= tol;
  if (qualified) {
    if (lastQual) holdQual += now - lastQual;
    lastQual = now;
  } else lastQual = 0;
  tempDrive(target);
  if (holdQual >= sec * 1000UL) curState = DONE;
}


// --- TELEMETRY ---
void sendTelemetry() {
  int save = 0;
  unsigned long now = millis();
  if (curState != IDLE && ((now - lastLog) >= (unsigned long)userInterval * 1000UL || curState == DONE)) {
    save = 1; lastLog = now;
  }

  comm.print(totalSec); comm.print(",");
  comm.print(curSec); comm.print(",");
  comm.print(cycleNum); comm.print(",");
  comm.print((int)curState); comm.print(",");
  comm.print(tempIR, 1); comm.print(",");
  comm.print(tempTC, 1); comm.print(",");
  comm.print(smoothedLux, 1); comm.print(",");
  comm.print(save); comm.print(",");

  if (mode == NORMAL_CYCLIC) comm.print("NORMAL_CYCLIC");
  else if (mode == FIXED_TEMPERATURE) comm.print("FIXED_TEMPERATURE");
  else comm.print("NATURAL_PLATEAU");
  comm.print(",");

  comm.print(ctrlTemp, 2); comm.print(",");
  comm.print(setpoint, 2); comm.print(",");
  comm.print(errTemp, 2); comm.print(",");
  comm.print(lampPWM); comm.print(",");
  comm.print(holdStart ? (now - holdStart) / 1000UL : 0); comm.print(",");
  comm.print(holdQual / 1000UL); comm.print(",");
  comm.print(qualified ? 1 : 0); comm.print(",");
  comm.println(detPlatTemp, 2);
}


// --- STATE MACHINES ---
void runNormal() {
  switch (curState) {
    case PRE_HEAT:
      curSec++;
      doLamp(lampPWM); doFan(0);
      showLCD("PRE-HEAT");
      if (tempTC >= 30.0 && tempIR >= 30.0) {
        curState = HEATING; curSec = 0; lcd.clear();
      }
      break;
    case HEATING:
      curSec++;
      luxCtrl(); doFan(0);
      showLCD("HEAT");
      if (curSec >= targSec) {
        doLamp(0); curState = COOLING; curSec = 0; lcd.clear();
      }
      break;
    case COOLING:
      curSec++;
      doLamp(0); doFan(255);
      showLCD("COOL");
      if (tempTC <= MAIN_TARGET - UNDERSHOOT && tempIR <= MAIN_TARGET - UNDERSHOOT) {
        curState = STABILIZING; stableCnt = 0; curSec = 0; lcd.clear();
      }
      break;
    case STABILIZING:
      curSec++; stableCnt++;
      doLamp(0); doFan(150);
      showLCD("STABIL");
      if (tempTC > MAIN_TARGET + HYSTERESIS) {
        curState = COOLING; curSec = 0; lcd.clear();
      } else if (stableCnt >= STABLE_TIME) {
        if ((unsigned long)cycleNum >= (unsigned long)targCycles) curState = DONE;
        else { cycleNum++; curState = PRE_HEAT; curSec = 0; }
        lcd.clear();
      }
      break;
    default: break;
  }
}

void runCalib() {
  curSec++;
  if (curState == CAL_FULL) doLamp(255);
  else doLamp(CAL_REF_PWM);

  luxWin[(curSec - 1) % 10] = smoothedLux;

  lcd.setCursor(0, 1);
  lcd.print("Lux:"); lcd.print((int)smoothedLux);
  lcd.print(" "); lcd.print(curSec); lcd.print("s   ");

  if (curSec < (unsigned long)CAL_MIN_WARMUP) return;
  float oldest = luxWin[curSec % 10];
  if (oldest <= 0) return;
  if (fabs(oldest - smoothedLux) / oldest >= 0.01f) return;

  if (curState == CAL_BARE) {
    calBare = smoothedLux;
    comm.print("CALBARE:"); comm.println(calBare, 1);
    delay(300);
    comm.print("CALBARE:"); comm.println(calBare, 1);
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("BARE OK:");
    lcd.setCursor(0, 1); lcd.print((int)calBare); lcd.print(" lx");
    curState = IDLE; doLamp(0);
  } else if (curState == CAL_TAPE) {
    calTaped = smoothedLux;
    atten = calTaped > 0 ? calBare / calTaped : 1.0;
    comm.print("CALTAPE:"); comm.print(calTaped, 1);
    comm.print(":"); comm.println(atten, 3);
    delay(300);
    comm.print("CALTAPE:"); comm.print(calTaped, 1);
    comm.print(":"); comm.println(atten, 3);
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("TAPE OK: x");
    lcd.setCursor(0, 1); lcd.print(atten, 2);
    curState = IDLE; doLamp(0);
  } else {
    maxHwLux = smoothedLux;
    EEPROM.put(0, maxHwLux);
    EEPROM.put(4, atten);
    comm.print("CALRESULT:"); comm.print(calBare, 1); comm.print(",");
    comm.print(calTaped, 1); comm.print(",");
    comm.print(atten, 3); comm.print(",");
    comm.println(maxHwLux, 1);
    delay(500);
    comm.print("CALRESULT:"); comm.print(calBare, 1); comm.print(",");
    comm.print(calTaped, 1); comm.print(",");
    comm.print(atten, 3); comm.print(",");
    comm.println(maxHwLux, 1);
    comm.print("MAXLUX:"); comm.println(maxHwLux, 2);
    lcd.clear(); lcd.setCursor(0, 0); lcd.print("DONE! Max:");
    lcd.setCursor(0, 1); lcd.print((int)maxHwLux); lcd.print(" lx");
    delay(3000);
    forceStop();
  }
}

void runControlled() {
  unsigned long now = millis();
  curSec = (now - stateStart) / 1000UL;
  CtrlSns sensor = mode == FIXED_TEMPERATURE ? iso.sensor : plat.sensor;
  ctrlTemp = sensor == SENSOR_TC ? tempTC : tempIR;
  ctrlValid = isfinite(ctrlTemp);
  if (!ctrlValid) {
    qualified = false;
    doLamp(0); doFan(255);
    if (!invalidSince) invalidSince = now;
    if (now - invalidSince >= 10000UL) abortRun("SENSOR_INVALID");
    showLCD("SENSOR INVALID");
    return;
  }
  invalidSince = 0;
  if (ctrlTemp > userMaxTemp) { abortRun("MAX_TEMP"); return; }

  if (curState == ISO_RAMP) {
    if (!isfinite(setpoint)) setpoint = ctrlTemp;
    setpoint = min(iso.targetTemp, setpoint + iso.rampRate / 60.0f);
    tempDrive(setpoint);
    showLCD("ISO RAMP");
    if (setpoint >= iso.targetTemp && fabs(errTemp) <= iso.tolerance) {
      curState = ISO_QUALIFY; stateStart = now;
    }
  } else if (curState == ISO_QUALIFY) {
    setpoint = iso.targetTemp;
    tempDrive(setpoint);
    qualified = fabs(errTemp) <= iso.tolerance;
    showLCD("ISO QUALIFY");
    if (!qualified) stateStart = now;
    else if (now - stateStart >= iso.qualificationSeconds * 1000UL) {
      curState = ISO_HOLD; holdStart = lastQual = now;
      holdQual = 0; stateStart = now;
    }
  } else if (curState == ISO_HOLD) {
    setpoint = iso.targetTemp;
    qualHold(setpoint, iso.tolerance, iso.holdSeconds);
    showLCD("ISO HOLD");
  } else if (curState == PLATEAU_HEATING || curState == PLATEAU_CONFIRM) {
    luxCtrl();
    platAdd(platWin, (now - modeStart) / 1000.0f, ctrlTemp);
    PlatStats s = platCalc(platWin, plat.windowSeconds);
    bool ok = s.valid && fabs(s.slopePerMin) <= plat.maxSlope && s.peakToPeak <= plat.maxPeakToPeak;
    if (curState == PLATEAU_HEATING && ok) {
      curState = PLATEAU_CONFIRM; confirmStart = now;
    } else if (curState == PLATEAU_CONFIRM && !ok) {
      curState = PLATEAU_HEATING; confirmStart = 0;
    } else if (curState == PLATEAU_CONFIRM && now - confirmStart >= plat.confirmationSeconds * 1000UL) {
      detPlatTemp = s.mean;
      curState = PLATEAU_HOLD; holdStart = lastQual = now;
      holdQual = 0; piReset(tempPI);
    }
    if (now - modeStart >= plat.maxDiscoverySeconds * 1000UL && curState != PLATEAU_HOLD)
      abortRun("DISCOVERY_TIMEOUT");
    showLCD(curState == PLATEAU_CONFIRM ? "PLAT CONFIRM" : "PLAT HEAT");
  } else if (curState == PLATEAU_HOLD) {
    setpoint = detPlatTemp;
    if (plat.postMode == POST_PASSIVE) {
      luxCtrl();
      qualified = ctrlValid && fabs(ctrlTemp - detPlatTemp) <= plat.maxPeakToPeak;
      if (now - holdStart >= plat.holdSeconds * 1000UL) curState = DONE;
    } else qualHold(setpoint, plat.maxPeakToPeak, plat.holdSeconds);
    showLCD("PLAT HOLD");
  } else if (curState == ABORTED) {
    doLamp(0); doFan(255);
    showLCD("ABORTED");
  }
}


// --- SCROLLING IDLE DISPLAY ---
void showScrolling() {
  lcd.setCursor(0, 0); lcd.print("SYSTEM READY   ");
  char buf[17]; const char *url = "   pt-kit.g-labs.my.id   ";
  int ulen = strlen(url);
  for (int i = 0; i < 16; i++) {
    int pos = (scrollPos + i) % ulen;
    buf[i] = url[pos];
  }
  buf[16] = 0;
  lcd.setCursor(0, 1); lcd.print(buf);
  scrollPos++;
  if (scrollPos >= ulen) scrollPos = 0;
}


// --- LOOP ---
void loop() {
  // --- COMMAND INPUT ---
  static char cmdBuf[80];
  static uint8_t cmdIdx = 0;
  while (comm.available()) {
    char c = comm.read();
    // ESP32 Serial2.println() sends CRLF.  Ignore CR so exact commands and
    // final numeric/mode fields are not received as "STOP\r", "5.0\r", etc.
    if (c == '\r') continue;
    if (c == '\n' || cmdIdx >= 79) {
      cmdBuf[cmdIdx] = 0; cmdIdx = 0;
      if (cmdBuf[0]) {
        lastHb = millis();

        if (strcmp(cmdBuf, "STOP") == 0) {
          forceStop();
        } else if (strncmp(cmdBuf, "IP:", 3) == 0) {
          strncpy(espIP, cmdBuf + 3, 19); espIP[19] = 0;
          wifiOk = true;
          lcd.clear(); lcd.setCursor(0, 0); lcd.print("WiFi Connected!");
          lcd.setCursor(0, 1); lcd.print(espIP);
          delay(2000); lcd.clear();
        } else if (strncmp(cmdBuf, "SET2:", 5) == 0) {
          char f[6][20];
          if (splitFields(cmdBuf, f, 6) == 6 && strcmp(f[0], "SET2") == 0 && strcmp(f[5], "MAX_OUTPUT") == 0) {
            MaxOutCmd p;
            if (parseUlong(f[1], p.durationSeconds) && parseUlong(f[2], p.cycles) &&
                parseFloat(f[3], p.maxTemp) && parseUlong(f[4], p.logInterval) &&
                p.durationSeconds && p.cycles && p.maxTemp > 0 && p.logInterval) {
              maxo = p;
              targSec = p.durationSeconds;
              targCycles = p.cycles;
              userMaxTemp = p.maxTemp;
              userInterval = p.logInterval;
              unsigned long now = millis();
              resetRun(now);
              mode = NORMAL_CYCLIC; illum = MAX_OUTPUT;
              doLamp(255);
              curState = PRE_HEAT; lcd.clear();
            } else comm.println("ERR:SET2");
          }
        } else if (strncmp(cmdBuf, "SET:", 4) == 0) {
          char f[6][20];
          int cnt = splitFields(cmdBuf, f, 6);
          if ((cnt == 5 || cnt == 6) && strcmp(f[0], "SET") == 0) {
            unsigned long dur, cyc, intv;
            float mx, lx = maxHwLux;
            if (parseUlong(f[1], dur) && parseUlong(f[2], cyc) &&
                parseFloat(f[3], mx) && parseUlong(f[4], intv)) {
              if (cnt == 6) parseFloat(f[5], lx);
              targSec = dur ? dur : 60;
              targCycles = cyc;
              userMaxTemp = mx < 50 ? 100 : mx;
              userInterval = intv < 1 ? 1 : intv;
              targetLux = lx;
              lcd.clear();
              lcd.setCursor(0, 0);
              lcd.print("GOT: "); lcd.print((int)targSec); lcd.print("s");
              lcd.setCursor(0, 1);
              lcd.print("T:"); lcd.print((int)userMaxTemp);
              lcd.print(" I:"); lcd.print(userInterval);
              delay(2000);
              unsigned long now = millis();
              resetRun(now);
              mode = NORMAL_CYCLIC; illum = TARGET_LUX;
              doLamp((int)((targetLux / maxHwLux) * 255.0f));
              curState = PRE_HEAT; lcd.clear();
            }
          }
        } else if (strncmp(cmdBuf, "ISO1:", 5) == 0) {
          char f[9][20];
          if (splitFields(cmdBuf, f, 9) == 9 && strcmp(f[0], "ISO1") == 0) {
            IsoCmd p;
            if (parseFloat(f[1], p.targetTemp) && parseUlong(f[2], p.holdSeconds) &&
                parseFloat(f[3], p.tolerance) && parseUlong(f[4], p.qualificationSeconds) &&
                parseFloat(f[5], p.maxTemp) && parseUlong(f[6], p.logInterval) &&
                parseFloat(f[8], p.rampRate) &&
                p.targetTemp > 0 && p.holdSeconds && p.tolerance > 0 &&
                p.qualificationSeconds && p.maxTemp > p.targetTemp &&
                p.logInterval && p.rampRate > 0) {
              p.sensor = parseSensor(f[7]);
              iso = p;
              userMaxTemp = p.maxTemp; userInterval = p.logInterval;
              unsigned long now = millis();
              resetRun(now);
              mode = FIXED_TEMPERATURE; illum = TEMPERATURE_CONTROLLED;
              piReset(tempPI);
              curState = ISO_RAMP; lcd.clear();
            } else comm.println("ERR:ISO1");
          }
        } else if (strncmp(cmdBuf, "PLAT1:", 6) == 0 || strncmp(cmdBuf, "PLAT2:", 6) == 0) {
          char f[12][20];
          if (splitFields(cmdBuf, f, 12) == 12) {
            PlateauCmd p;
            bool plat1 = (strcmp(f[0], "PLAT1") == 0);
            bool plat2 = (strcmp(f[0], "PLAT2") == 0 && strcmp(f[1], "MAX_OUTPUT") == 0);
            if (plat1 || plat2) {
              // Both serializers place the first shared plateau field
              // (holdSeconds) at index 2.  PLAT1 uses f[1] for targetLux;
              // PLAT2 uses f[1] for MAX_OUTPUT.
              int off = 2;
              if (plat2) { p.targetLux = 0; p.illuminationMode = MAX_OUTPUT; }
              else if (!parseFloat(f[1], p.targetLux) || !(p.targetLux > 0)) goto platfail;
              if (parseUlong(f[off], p.holdSeconds) &&
                  parseUlong(f[off+1], p.windowSeconds) &&
                  parseFloat(f[off+2], p.maxSlope) &&
                  parseFloat(f[off+3], p.maxPeakToPeak) &&
                  parseUlong(f[off+4], p.confirmationSeconds) &&
                  parseUlong(f[off+5], p.maxDiscoverySeconds) &&
                  parseFloat(f[off+6], p.maxTemp) &&
                  parseUlong(f[off+7], p.logInterval)) {
                p.sensor = parseSensor(f[off+8]);
                if (strcmp(f[off+9], "PASSIVE") == 0) p.postMode = POST_PASSIVE;
                else if (strcmp(f[off+9], "REGULATED") == 0) p.postMode = POST_REGULATED;
                else goto platfail;
                p.illuminationMode = plat1 ? TARGET_LUX : MAX_OUTPUT;
                if (p.holdSeconds && p.windowSeconds >= 3 && p.windowSeconds <= PLAT_CAP &&
                    p.maxSlope > 0 && p.maxPeakToPeak > 0 && p.confirmationSeconds &&
                    p.maxDiscoverySeconds >= p.windowSeconds && p.maxTemp > 0 && p.logInterval) {
                  plat = p;
                  if (plat1) targetLux = p.targetLux;
                  userMaxTemp = p.maxTemp; userInterval = p.logInterval;
                  unsigned long now = millis();
                  resetRun(now);
                  mode = NATURAL_PLATEAU; illum = plat1 ? TARGET_LUX : MAX_OUTPUT;
                  platReset(platWin); piReset(tempPI);
                  doLamp(illum == MAX_OUTPUT ? 255 : constrain((targetLux / maxHwLux) * 255.0f, 0, 255));
                  curState = PLATEAU_HEATING; lcd.clear();
                  continue;
                }
              }
            }
            platfail:
            comm.println("ERR:PLAT");
          }
        } else if (strcmp(cmdBuf, "CAL_BARE") == 0) {
          atten = 1.0; calBare = 0; curSec = 0;
          doLamp(CAL_REF_PWM);
          curState = CAL_BARE; lcd.clear();
          lcd.setCursor(0, 0); lcd.print("CAL: BARE SENSOR");
        } else if (strcmp(cmdBuf, "CAL_TAPE") == 0) {
          atten = 1.0; calTaped = 0; curSec = 0;
          doLamp(CAL_REF_PWM);
          curState = CAL_TAPE; lcd.clear();
          lcd.setCursor(0, 0); lcd.print("CAL: TAPED SENS");
        } else if (strcmp(cmdBuf, "CAL_FULL") == 0) {
          curSec = 0; doLamp(255);
          curState = CAL_FULL; lcd.clear();
          lcd.setCursor(0, 0); lcd.print("CAL: FULL POWER");
        }
      }
    } else {
      cmdBuf[cmdIdx++] = c;
    }
  }

  // --- MAIN TICK (1 Hz) ---
  if (millis() - lastLoop >= 1000UL) {
    lastLoop = millis();
    readSensors();

    if (curState != IDLE && curState != DONE) totalSec++;

    // Safety
    if (tempTC > 150.0 || tempTC > userMaxTemp) {
      delay(50);
      float cek = thermocouple.readCelsius();
      if (cek > 150.0 || cek > userMaxTemp) {
        if (curState != IDLE && curState != DONE) {
          lcd.clear();
          lcd.setCursor(0, 0); lcd.print("ERR: OVERHEAT!");
          lcd.setCursor(0, 1);
          lcd.print((int)tempTC); lcd.print("C > ");
          lcd.print((int)userMaxTemp); lcd.print("C");
          delay(3000);
          forceStop();
        }
      }
    }

    if (curState != IDLE && curState != DONE) {
      if (curState == CAL_BARE || curState == CAL_TAPE || curState == CAL_FULL)
        runCalib();
      else if (mode == NORMAL_CYCLIC)
        runNormal();
      else
        runControlled();
    } else if (curState == DONE) {
      doLamp(0); doFan(0);
      lcd.setCursor(0, 0); lcd.print("DONE! Saving...");
      delay(2000);
      for (int i = 0; i < 3; i++) { sendTelemetry(); delay(500); }
      curState = IDLE; cycleNum = 0; curSec = totalSec = 0;
      lcd.clear();
    } else {
      doLamp(0); doFan(0);
    }

    sendTelemetry();
  }

  // --- IDLE SCROLLING ---
  if (curState == IDLE && wifiOk) {
    if (millis() - lastScroll >= 400UL) {
      lastScroll = millis();
      showScrolling();
    }
  } else if (curState == IDLE && !wifiOk) {
    lcd.setCursor(0, 0); lcd.print("Waiting WiFi...");
    lcd.setCursor(0, 1); lcd.print("Check ESP32... ");
  }
}
