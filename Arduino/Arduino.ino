/*

 * === KODE FINAL: ARDUINO UNO (FULL FEATURES PRESERVED) ===

 * Fitur: Sensor, Relay, Safety, LCD, Auto Reset.

 * PERBAIKAN: Semua fitur kode pertama tetap ada, plus auto reset setelah DONE.

 */


#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Adafruit_MLX90614.h>
#include <SoftwareSerial.h>
#include <max6675.h>
#include <BH1750.h>
#include <EEPROM.h>
#include "IsothermalControl.h"


// --- PIN MAPPING ---
#define PIN_LAMP        5
#define PIN_FAN         3 
#define PIN_TC_CLK      6
#define PIN_TC_CS       7
#define PIN_TC_DO       8
// Komunikasi ke ESP32
#define PIN_ESP_RX      10 
#define PIN_ESP_TX      11 


// --- SETTING LOGIKA ---
const float MAIN_TARGET    = 30.0; 
const float UNDERSHOOT     = 1.0;  
const float HYSTERESIS     = 0.5;   
const int   STABLE_TIME    = 5;    


// URL Scrolling
const String SERVER_URL    = "   pt-kit.g-labs.my.id   "; 


// --- OBJEK ---
SoftwareSerial comm(PIN_ESP_RX, PIN_ESP_TX); 
LiquidCrystal_I2C lcd(0x27, 16, 2);
Adafruit_MLX90614 mlx = Adafruit_MLX90614();
MAX6675 thermocouple(PIN_TC_CLK, PIN_TC_CS, PIN_TC_DO);
BH1750 lightMeter;


// Status Mesin
enum State { IDLE, PRE_HEAT, HEATING, COOLING, STABILIZING, DONE, CAL_BARE, CAL_TAPE, CAL_FULL, ISO_RAMP, ISO_QUALIFY, ISO_HOLD, PLATEAU_HEATING, PLATEAU_CONFIRM, PLATEAU_HOLD, ABORTED };
State currentState = IDLE;
enum OperatingMode { NORMAL_CYCLIC, FIXED_TEMPERATURE, NATURAL_PLATEAU };
OperatingMode operatingMode = NORMAL_CYCLIC;


// Data Variabel
String espIP = "";
bool wifiConnected = false;
float tempIR = 0.0, tempTC = 0.0;
float rawLux = 0.0, smoothedLux = 0.0;
float userMaxTemp = 100.0;       
int   userInterval = 1;          
float targetLux = 38000.0;
IsoCommand isoConfig; PlateauCommand plateauConfig; PIController tempPI; PlateauWindow plateauWindow;
float controlTemp=NAN, tempSetpoint=NAN, tempError=NAN, detectedPlateauTemp=NAN;
bool controlTempValid=false, qualified=false;
unsigned long modeStarted=0,stateStarted=0,holdStarted=0,holdQualifiedMs=0,lastQualifiedMs=0,confirmStarted=0,lastControlMs=0,invalidSince=0;
const float TEMP_KP=18.0, TEMP_KI=0.35, TEMP_APPROACH_ZONE=2.0;
const unsigned long EXCURSION_GRACE_MS=3000;

// Lux Control Vars
int lampPWM = 0;
float maxHardwareLux = 10000.0; // default, will be overridden by EEPROM
const float KP = 0.05;
const float LUX_TOLERANCE = 50.0;
const float EMA_ALPHA = 0.2;

// Tape Calibration Vars
float luxAttenuationFactor = 1.0;  // multiplier (default = no tape)
float calBareLux = 0.0;            // bare sensor reading at ref PWM
float calTapedLux = 0.0;           // taped sensor reading at ref PWM
const int CAL_REF_PWM = 128;       // hardcoded 50% reference
const int CAL_MIN_WARMUP = 15;     // minimum seconds before checking stability


unsigned long currentSec = 0;       
unsigned long totalMasterSec = 0;   
unsigned long targetSec = 0;        
int targetCycles = 0;               
int currentCycleNum = 0;
int stableCounter = 0;


// Timer Variables
unsigned long lastLoop = 0; 
unsigned long lastLogTime = 0;      
unsigned long lastHeartbeat = 0;


// Scrolling Variables
unsigned long lastScrollTime = 0;
int scrollPos = 0;
const int SCROLL_DELAY = 400; 


void setup() {
  Serial.begin(9600);
  comm.begin(9600); 
   
  pinMode(PIN_LAMP, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  analogWrite(PIN_LAMP, 0);
  analogWrite(PIN_FAN, 0);

  lcd.init(); lcd.backlight();
  mlx.begin();
  lightMeter.begin();

  // Load calibration values from EEPROM
  // Memory Map: addr 0-3 = maxHardwareLux, addr 4-7 = luxAttenuationFactor
  EEPROM.get(0, maxHardwareLux);
  if(isnan(maxHardwareLux) || maxHardwareLux <= 0) maxHardwareLux = 10000.0;
  EEPROM.get(4, luxAttenuationFactor);
  if(isnan(luxAttenuationFactor) || luxAttenuationFactor <= 0) luxAttenuationFactor = 1.0;
  
  // [DEBUG STARTUP] - Fitur dari kode pertama
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("System Booting..");
  delay(1000); 
  
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Wait WiFi...");
}


void loop() {
  // 1. CEK KOMUNIKASI (TERIMA PERINTAH) - Sama seperti kode pertama
  if (comm.available()) {
    String data = comm.readStringUntil('\n');
    data.trim();
    if(data.length() > 0) {
      lastHeartbeat = millis(); // Fitur heartbeat dari kode pertama
    }

    if (data == "STOP") forceStop("STOP CMD");
    else if (data.startsWith("IP:")) {
      espIP = data.substring(3);
      wifiConnected = true;
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("WiFi Connected!");
      lcd.setCursor(0,1); lcd.print(espIP); 
      delay(2000); lcd.clear();
    }
    else if (data.startsWith("SET:")) {
      operatingMode = NORMAL_CYCLIC;
      // === PARSING BARU (METODE POTONG KUE) ===
      // Format: SET:Durasi:Siklus:MaxTemp:Interval:TargetLux
      // Contoh: SET:60:5:80.0:1:5000
      
      String raw = data; 
      raw.remove(0, 4); // Buang "SET:" -> sisa "60:5:80.0:1:5000"
      
      // Ambil Durasi
      int firstDiv = raw.indexOf(':');
      targetSec = raw.substring(0, firstDiv).toInt();
      
      // Potong lagi -> sisa "5:80.0:1:5000"
      raw = raw.substring(firstDiv + 1);
      int secondDiv = raw.indexOf(':');
      targetCycles = raw.substring(0, secondDiv).toInt();
      
      // Potong lagi -> sisa "80.0:1:5000"
      raw = raw.substring(secondDiv + 1);
      int thirdDiv = raw.indexOf(':');
      userMaxTemp = raw.substring(0, thirdDiv).toFloat();
      
      // Potong lagi -> sisa "1:5000"
      raw = raw.substring(thirdDiv + 1);
      int fourthDiv = raw.indexOf(':');
      
      if(fourthDiv == -1) {
          userInterval = raw.toInt();
          targetLux = maxHardwareLux; // fallback
      } else {
          userInterval = raw.substring(0, fourthDiv).toInt();
          targetLux = raw.substring(fourthDiv + 1).toFloat();
      }
      
      // Validasi Safety - dari kode pertama
      if(userMaxTemp < 50) userMaxTemp = 100.0; 
      if(userInterval < 1) userInterval = 1;
      // Default jika targetSec nol (gagal parse) kasih 60
      if(targetSec <= 0) targetSec = 60; 

      // [DEBUG HASIL PARSING DI LCD] - Fitur penting dari kode pertama
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("GOT: " + String(targetSec) + "s"); 
      lcd.setCursor(0,1); lcd.print("T:" + String((int)userMaxTemp) + " I:" + String(userInterval));
      delay(2000); // Tahan 2 detik buat dibaca

      // RESET & START
      totalMasterSec = 0; 
      currentSec = 0; 
      currentCycleNum = 1;
      lastLogTime = millis(); 
      lampPWM = constrain((targetLux / maxHardwareLux) * 255.0, 0, 255); // open loop start
      currentState = PRE_HEAT; 
      lcd.clear();
    }
    else if (data.startsWith("ISO1:")) {
      IsoCommand p; if(parseIsoCommand(data.c_str(),p)){ isoConfig=p; operatingMode=FIXED_TEMPERATURE; userMaxTemp=p.maxTemp; userInterval=p.logInterval; totalMasterSec=currentSec=0; currentCycleNum=1; modeStarted=stateStarted=millis(); holdStarted=holdQualifiedMs=lastQualifiedMs=0; tempSetpoint=NAN; piReset(tempPI); currentState=ISO_RAMP; lastLogTime=millis(); lcd.clear(); } else comm.println("ERR:ISO1");
    }
    else if (data.startsWith("PLAT1:")) {
      PlateauCommand p; if(parsePlateauCommand(data.c_str(),p)){ plateauConfig=p; operatingMode=NATURAL_PLATEAU; targetLux=p.targetLux; userMaxTemp=p.maxTemp; userInterval=p.logInterval; totalMasterSec=currentSec=0; currentCycleNum=1; modeStarted=stateStarted=millis(); holdStarted=holdQualifiedMs=confirmStarted=0; detectedPlateauTemp=NAN; plateauReset(plateauWindow); piReset(tempPI); lampPWM=constrain((targetLux/maxHardwareLux)*255.0,0,255); currentState=PLATEAU_HEATING; lastLogTime=millis(); lcd.clear(); } else comm.println("ERR:PLAT1");
    }
    else if (data == "CAL_BARE") {
      // Phase 1: Bare sensor measurement at 50% PWM
      luxAttenuationFactor = 1.0;  // CRITICAL: reset factor for raw measurement
      currentState = CAL_BARE;
      currentSec = 0;
      calBareLux = 0.0;
      lampPWM = CAL_REF_PWM;
      analogWrite(PIN_LAMP, lampPWM);
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("CAL: BARE SENSOR");
    }
    else if (data == "CAL_TAPE") {
      // Phase 2: Taped sensor measurement (factor must be 1.0 for raw reading)
      luxAttenuationFactor = 1.0;  // Ensure raw measurement
      currentState = CAL_TAPE;
      currentSec = 0;
      calTapedLux = 0.0;
      lampPWM = CAL_REF_PWM;  // same PWM as bare
      analogWrite(PIN_LAMP, lampPWM);
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("CAL: TAPED SENS");
    }
    else if (data == "CAL_FULL") {
      // Phase 3: Full power measurement with newly computed factor
      currentState = CAL_FULL;
      currentSec = 0;
      lampPWM = 255;
      analogWrite(PIN_LAMP, lampPWM);
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("CAL: FULL POWER");
    }
  }

  // 2. LOGIKA UTAMA (TIAP 1 DETIK) - Sama seperti kode pertama
  if (millis() - lastLoop >= 1000) {
    lastLoop = millis();
    readSensors();
    // Timer hanya jalan saat eksperimen aktif (bukan IDLE/DONE)
    if (currentState != IDLE && currentState != DONE) {
      totalMasterSec++;
    }

    // SAFETY CUTOFF - Lengkap seperti kode pertama
    if (tempTC > 150.0 || tempTC > userMaxTemp) { 
       delay(50);
       float cekLagi = thermocouple.readCelsius();
       if (cekLagi > 150.0 || cekLagi > userMaxTemp) {
          if(currentState!=IDLE && currentState!=DONE) {
             lcd.clear(); lcd.setCursor(0,0); lcd.print("ERR: OVERHEAT!");
             lcd.setCursor(0,1); lcd.print(String((int)tempTC) + "C > " + String((int)userMaxTemp) + "C");
             delay(3000);
             forceStop("OVERHEAT"); 
          }
       }
    }

    if(currentState != IDLE && currentState != DONE) {
      // Route calibration states to calibration logic
      if (currentState == CAL_BARE || currentState == CAL_TAPE || currentState == CAL_FULL) {
        runCalibrationLogic();
      } else if (operatingMode == NORMAL_CYCLIC) {
        runExperimentLogic();
      } else {
        runIsothermalLogic();
      }
    } 
    else if (currentState == DONE) {
      // MODIFIKASI: Tetap tampilkan DONE, lalu auto reset setelah delay
      showDone();
      delay(2000); // Tampilkan DONE selama 2 detik
      
      // Kirim data DONE ke web sebelum reset
      for(int i=0; i<3; i++) {
        sendDataToESP();
        delay(500);
      }
      
      // Auto reset ke IDLE
      currentState = IDLE;
      currentCycleNum = 0;
      currentSec = 0;
      totalMasterSec = 0;
      lcd.clear();
    }
    else {
      // MODE IDLE
      analogWrite(PIN_LAMP, 0); analogWrite(PIN_FAN, 0); 
    }
    
    sendDataToESP();
  }

  // 3. SCROLLING TEXT - Sama persis seperti kode pertama
  if (currentState == IDLE && wifiConnected) {
    if (millis() - lastScrollTime >= SCROLL_DELAY) {
      lastScrollTime = millis();
      showScrollingStandby();
    }
  } else if (currentState == IDLE && !wifiConnected) {
     lcd.setCursor(0,0); lcd.print("Waiting WiFi...");
     lcd.setCursor(0,1); lcd.print("Check ESP32... ");
  }
}


// --- LOGIC FUNCTIONS ---
void luxControl(){float e=targetLux-smoothedLux;if(abs(e)>LUX_TOLERANCE)lampPWM=constrain(lampPWM+e*KP,0,255);}
void abortMode(const char*r){currentState=ABORTED;lampPWM=0;analogWrite(PIN_LAMP,0);analogWrite(PIN_FAN,255);comm.print("ABORT:");comm.println(r);}
void temperatureDrive(float target){unsigned long now=millis();float dt=lastControlMs?min((now-lastControlMs)/1000.0f,2.0f):1.0f;lastControlMs=now;tempError=target-controlTemp;lampPWM=(int)piStep(tempPI,target,controlTemp,dt,TEMP_KP,TEMP_KI,255,TEMP_APPROACH_ZONE);analogWrite(PIN_LAMP,lampPWM);analogWrite(PIN_FAN,0);}
void qualifiedHold(float target,float tolerance,unsigned long seconds){unsigned long now=millis();qualified=controlTempValid&&abs(controlTemp-target)<=tolerance;if(qualified){if(lastQualifiedMs)holdQualifiedMs+=now-lastQualifiedMs;lastQualifiedMs=now;}else lastQualifiedMs=0;temperatureDrive(target);if(holdQualifiedMs>=seconds*1000UL)currentState=DONE;}
void runIsothermalLogic(){
 unsigned long now=millis();currentSec=(now-stateStarted)/1000;ControlSensor sensor=operatingMode==FIXED_TEMPERATURE?isoConfig.sensor:plateauConfig.sensor;controlTemp=sensor==SENSOR_TC?tempTC:tempIR;controlTempValid=isfinite(controlTemp);if(!controlTempValid){qualified=false;analogWrite(PIN_LAMP,0);analogWrite(PIN_FAN,255);if(!invalidSince)invalidSince=now;if(now-invalidSince>=10000UL)abortMode("SENSOR_INVALID");updateLCD("SENSOR INVALID");return;}invalidSince=0;if(controlTemp>userMaxTemp){abortMode("MAX_TEMP");return;}
 if(currentState==ISO_RAMP){if(!isfinite(tempSetpoint))tempSetpoint=controlTemp;tempSetpoint=min(isoConfig.targetTemp,tempSetpoint+isoConfig.rampRate/60.0);temperatureDrive(tempSetpoint);updateLCD("ISO RAMP");if(tempSetpoint>=isoConfig.targetTemp&&abs(tempError)<=isoConfig.tolerance){currentState=ISO_QUALIFY;stateStarted=now;}}
 else if(currentState==ISO_QUALIFY){tempSetpoint=isoConfig.targetTemp;temperatureDrive(tempSetpoint);qualified=abs(tempError)<=isoConfig.tolerance;updateLCD("ISO QUALIFY");if(!qualified)stateStarted=now;else if(now-stateStarted>=isoConfig.qualificationSeconds*1000UL){currentState=ISO_HOLD;holdStarted=lastQualifiedMs=now;holdQualifiedMs=0;stateStarted=now;}}
 else if(currentState==ISO_HOLD){tempSetpoint=isoConfig.targetTemp;qualifiedHold(tempSetpoint,isoConfig.tolerance,isoConfig.holdSeconds);updateLCD("ISO HOLD");}
 else if(currentState==PLATEAU_HEATING||currentState==PLATEAU_CONFIRM){luxControl();analogWrite(PIN_LAMP,lampPWM);plateauAdd(plateauWindow,(now-modeStarted)/1000.0,controlTemp);PlateauStats s=plateauStats(plateauWindow,plateauConfig.windowSeconds);bool ok=s.valid&&abs(s.slopePerMin)<=plateauConfig.maxSlope&&s.peakToPeak<=plateauConfig.maxPeakToPeak;if(currentState==PLATEAU_HEATING&&ok){currentState=PLATEAU_CONFIRM;confirmStarted=now;}else if(currentState==PLATEAU_CONFIRM&&!ok){currentState=PLATEAU_HEATING;confirmStarted=0;}else if(currentState==PLATEAU_CONFIRM&&now-confirmStarted>=plateauConfig.confirmationSeconds*1000UL){detectedPlateauTemp=s.mean;currentState=PLATEAU_HOLD;holdStarted=lastQualifiedMs=now;holdQualifiedMs=0;piReset(tempPI);}if(now-modeStarted>=plateauConfig.maxDiscoverySeconds*1000UL&&currentState!=PLATEAU_HOLD)abortMode("DISCOVERY_TIMEOUT");updateLCD(currentState==PLATEAU_CONFIRM?"PLAT CONFIRM":"PLAT HEAT");}
 else if(currentState==PLATEAU_HOLD){tempSetpoint=detectedPlateauTemp;if(plateauConfig.postMode==POST_PASSIVE){luxControl();analogWrite(PIN_LAMP,lampPWM);qualified=controlTempValid&&abs(controlTemp-detectedPlateauTemp)<=plateauConfig.maxPeakToPeak;if(now-holdStarted>=plateauConfig.holdSeconds*1000UL)currentState=DONE;}else qualifiedHold(tempSetpoint,plateauConfig.maxPeakToPeak,plateauConfig.holdSeconds);updateLCD("PLAT HOLD");}
 else if(currentState==ABORTED){analogWrite(PIN_LAMP,0);analogWrite(PIN_FAN,255);updateLCD("ABORTED");}
}
void runExperimentLogic() {
  switch (currentState) {
    case PRE_HEAT:
      currentSec++;
      analogWrite(PIN_LAMP, lampPWM); analogWrite(PIN_FAN, 0);
      updateLCD("PRE-HEAT");
      if (tempTC >= 30.0 && tempIR >= 30.0) { // Tetap pakai kedua sensor
         currentState = HEATING; currentSec=0; lcd.clear();
      }
      break;
    case HEATING:
      currentSec++;
      
      // Closed Loop Lux Control with Deadband
      float luxError = targetLux - smoothedLux;
      if (abs(luxError) > LUX_TOLERANCE) {
          lampPWM += (luxError * KP);
          lampPWM = constrain(lampPWM, 0, 255);
      }
      analogWrite(PIN_LAMP, lampPWM); analogWrite(PIN_FAN, 0);
      
      updateLCD("HEAT"); // Format: HEAT 5/60
      // Matikan lampu TEPAT WAKTU sesuai targetSec
      if (currentSec >= targetSec) {
        analogWrite(PIN_LAMP, 0); currentState = COOLING; currentSec=0; lcd.clear();
      }
      break;
    case COOLING:
      currentSec++; 
      analogWrite(PIN_LAMP, 0); analogWrite(PIN_FAN, 255); 
      updateLCD("COOL");
      // Tetap pakai kedua sensor seperti kode pertama
      if (tempTC <= (MAIN_TARGET - UNDERSHOOT) && tempIR <= (MAIN_TARGET - UNDERSHOOT)) {
        currentState = STABILIZING; stableCounter=0; currentSec=0; lcd.clear();
      }
      break;
    case STABILIZING:
      currentSec++;
      analogWrite(PIN_LAMP, 0); analogWrite(PIN_FAN, 150); 
      stableCounter++;
      updateLCD("STABIL");
      if (tempTC > (MAIN_TARGET + HYSTERESIS)) { 
         currentState = COOLING; currentSec=0; lcd.clear(); 
      }
      else if (stableCounter >= STABLE_TIME) { 
         if (currentCycleNum >= targetCycles) currentState = DONE;
         else { currentCycleNum++; currentState = PRE_HEAT; currentSec=0; }
         lcd.clear();
      }
      break;
  }
}

// Sliding Window vars for Calibration
float luxWindow[10];

void runCalibrationLogic() {
  currentSec++;
  
  // Keep lamp at the correct PWM for current phase
  if (currentState == CAL_FULL) {
    analogWrite(PIN_LAMP, 255);  // 100% PWM
  } else {
    analogWrite(PIN_LAMP, CAL_REF_PWM);  // 50% reference
  }
  
  // Fill sliding window
  luxWindow[(currentSec - 1) % 10] = smoothedLux;
  
  // Update LCD with live reading
  lcd.setCursor(0,1);
  lcd.print("Lux:"); lcd.print(smoothedLux, 0); lcd.print("  ");
  lcd.print(currentSec); lcd.print("s   ");
  
  // Don't check stability until minimum warm-up
  if (currentSec < CAL_MIN_WARMUP) return;
  
  // Check stability: sliding window 1% deviation
  float oldest = luxWindow[currentSec % 10];
  if (oldest <= 0) return;
  float diffPercent = abs(oldest - smoothedLux) / oldest;
  
  if (diffPercent < 0.01) {  // Stable!
    if (currentState == CAL_BARE) {
      calBareLux = smoothedLux;
      // Send bare result to server
      comm.println("CALBARE:" + String(calBareLux, 1));
      delay(300);
      comm.println("CALBARE:" + String(calBareLux, 1)); // redundancy
      
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("BARE OK:");
      lcd.setCursor(0,1); lcd.print(String(calBareLux, 0) + " lx");
      
      // Turn off lamp and wait for next command
      currentState = IDLE;
      analogWrite(PIN_LAMP, 0);
    }
    else if (currentState == CAL_TAPE) {
      calTapedLux = smoothedLux;
      
      // Compute attenuation factor
      if (calTapedLux > 0) {
        luxAttenuationFactor = calBareLux / calTapedLux;
      } else {
        luxAttenuationFactor = 1.0;  // safety fallback
      }
      
      comm.println("CALTAPE:" + String(calTapedLux, 1) + ":" + String(luxAttenuationFactor, 3));
      delay(300);
      comm.println("CALTAPE:" + String(calTapedLux, 1) + ":" + String(luxAttenuationFactor, 3));
      
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("TAPE OK: x");
      lcd.setCursor(0,1); lcd.print(String(luxAttenuationFactor, 2));
      
      // Turn off lamp and wait for CAL_FULL command
      currentState = IDLE;
      analogWrite(PIN_LAMP, 0);
    }
    else if (currentState == CAL_FULL) {
      // smoothedLux already has factor applied (from readSensors)
      maxHardwareLux = smoothedLux;  // this IS the corrected max
      
      // Save both to EEPROM
      EEPROM.put(0, maxHardwareLux);
      EEPROM.put(4, luxAttenuationFactor);
      
      // Send final result to server
      String result = "CALRESULT:" + String(calBareLux, 1) 
                    + "," + String(calTapedLux, 1) 
                    + "," + String(luxAttenuationFactor, 3) 
                    + "," + String(maxHardwareLux, 1);
      comm.println(result);
      delay(500);
      comm.println(result);  // redundancy
      
      // Also send MAXLUX for backward compatibility
      comm.println("MAXLUX:" + String(maxHardwareLux));
      
      lcd.clear();
      lcd.setCursor(0,0); lcd.print("DONE! Max:");
      lcd.setCursor(0,1); lcd.print(String(maxHardwareLux, 0) + " lx");
      delay(3000);
      
      forceStop("CALIB_DONE");
    }
  }
}



void sendDataToESP() {
    int saveFlag = 0;
    // Simpan ke DB hanya jika Running atau DONE - Sama seperti kode pertama
    if (currentState != IDLE && (millis() - lastLogTime >= (userInterval * 1000) || currentState == DONE)) {
       saveFlag = 1; lastLogTime = millis();
    }
    comm.print(totalMasterSec); comm.print(",");
    comm.print(currentSec); comm.print(",");
    comm.print(currentCycleNum); comm.print(",");
    comm.print(currentState); comm.print(",");
    comm.print(tempIR, 1); comm.print(",");
    comm.print(tempTC, 1); comm.print(",");
    comm.print(smoothedLux, 1); comm.print(",");
    comm.print(saveFlag); comm.print(",");
    comm.print(operatingMode==NORMAL_CYCLIC?"NORMAL_CYCLIC":operatingMode==FIXED_TEMPERATURE?"FIXED_TEMPERATURE":"NATURAL_PLATEAU");comm.print(",");
    comm.print(controlTemp,2);comm.print(",");comm.print(tempSetpoint,2);comm.print(",");comm.print(tempError,2);comm.print(",");comm.print(lampPWM);comm.print(",");
    comm.print(holdStarted?(millis()-holdStarted)/1000:0);comm.print(",");comm.print(holdQualifiedMs/1000);comm.print(",");comm.print(qualified?1:0);comm.print(",");comm.println(detectedPlateauTemp,2);
}


void showScrollingStandby() {
  lcd.setCursor(0,0); lcd.print("SYSTEM READY   "); 
  String textToShow;
  if (scrollPos + 16 < SERVER_URL.length()) {
    textToShow = SERVER_URL.substring(scrollPos, scrollPos + 16);
  } else {
    String part1 = SERVER_URL.substring(scrollPos);
    String part2 = SERVER_URL.substring(0, 16 - part1.length());
    textToShow = part1 + part2;
  }
  lcd.setCursor(0,1); lcd.print(textToShow);
  scrollPos++;
  if (scrollPos >= SERVER_URL.length()) scrollPos = 0;
}


void readSensors() {
  tempIR = mlx.readObjectTempC();
  tempTC = thermocouple.readCelsius();
  
  rawLux = lightMeter.readLightLevel();
  if(isnan(rawLux)) rawLux = 0.0;

  // Apply teflon tape attenuation correction to raw reading BEFORE smoothing
  // During CAL_BARE/CAL_TAPE, factor is set to 1.0 so we measure raw sensor
  float correctedLux = rawLux * luxAttenuationFactor;

  // EMA Filter (operates on corrected values to avoid compounding)
  smoothedLux = (EMA_ALPHA * correctedLux) + ((1.0 - EMA_ALPHA) * smoothedLux);
  // Optional: if smoothed is 0 initially, set to corrected
  if (smoothedLux < 1.0 && correctedLux > 1.0) smoothedLux = correctedLux;
}

void forceStop(String reason) { 
  currentState = IDLE; 
  // Reset semua timer agar bersih saat Start baru (sama seperti DONE handler)
  currentCycleNum = 0;
  currentSec = 0;
  totalMasterSec = 0;
  stableCounter = 0;
  lampPWM = 0;
  analogWrite(PIN_LAMP, 0); 
  analogWrite(PIN_FAN, 0);
  lcd.clear(); 
}

void showDone() { 
  analogWrite(PIN_LAMP, 0); 
  analogWrite(PIN_FAN, 0);
  lcd.setCursor(0,0); lcd.print("DONE! Saving..."); 
}

void updateLCD(String s) {
  lcd.setCursor(0,0); lcd.print(s); 
  if (currentState == HEATING) {
      lcd.print(" "); lcd.print(currentSec); lcd.print("/"); lcd.print(targetSec);
  } else {
      lcd.print(" "); lcd.print(currentSec);
  }
  lcd.setCursor(0,1); lcd.print("C:"); lcd.print(currentCycleNum); 
  lcd.print(" T"); lcd.print((int)tempTC); lcd.print(" I"); lcd.print((int)tempIR);
}