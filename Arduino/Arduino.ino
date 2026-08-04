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
#include "PTKitController.h"


// --- PIN MAPPING ---
#define PIN_LAMP        5
#define PIN_FAN         3 
#define PIN_TC_CLK      6
#define PIN_TC_CS       7
#define PIN_TC_DO       8
// Komunikasi ke ESP32
#define PIN_ESP_RX      10 
#define PIN_ESP_TX      11 


// --- OBJEK ---
SoftwareSerial comm(PIN_ESP_RX, PIN_ESP_TX); 
LiquidCrystal_I2C lcd(0x27, 16, 2);
Adafruit_MLX90614 mlx = Adafruit_MLX90614();
MAX6675 thermocouple(PIN_TC_CLK, PIN_TC_CS, PIN_TC_DO);
BH1750 lightMeter;


// Data Variabel
float rawTempIR = 0.0, rawTempTC = 0.0, rawLux = 0.0;
// Timer Variables
unsigned long lastLoop = 0; 
unsigned long lastHeartbeat = 0;

// Hardware adapter for the host-testable controller core.  The physical sketch
// supplies sensors and concrete Arduino peripherals; command parsing, state
// transitions, actuator writes, calibration persistence, and telemetry remain
// in PTKitController so the simulator does not maintain a second controller.
class ArduinoPTKitPlatform : public PTKitPlatform {
 public:
  uint32_t nowMs() const override { return millis(); }
  void setLampPwm(uint8_t pwm) override { analogWrite(PIN_LAMP, pwm); }
  void setFanPwm(uint8_t pwm) override { analogWrite(PIN_FAN, pwm); }
  void writeUart(const char *bytes, size_t length) override {
    comm.write(reinterpret_cast<const uint8_t *>(bytes), length);
  }
  void clearDisplay() override { lcd.clear(); }
  void showDisplay(const char *line1, const char *line2) override {
    lcd.clear();
    lcd.setCursor(0, 0); lcd.print(line1 ? line1 : "");
    lcd.setCursor(0, 1); lcd.print(line2 ? line2 : "");
  }
  void blockingDelay(uint32_t milliseconds) override { delay(milliseconds); }
  float confirmThermocoupleC() override { return thermocouple.readCelsius(); }
  void loadCalibration(float &maxLux, float &attenuation) override {
    EEPROM.get(0, maxLux);
    EEPROM.get(4, attenuation);
  }
  void saveCalibration(float maxLux, float attenuation) override {
    EEPROM.put(0, maxLux);
    EEPROM.put(4, attenuation);
  }
};

ArduinoPTKitPlatform controllerPlatform;
PTKitController controller(controllerPlatform);


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


  // [DEBUG STARTUP] - Fitur dari kode pertama
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("System Booting..");
  delay(1000); 
  
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Wait WiFi...");

  controller.begin();
}


void loop() {
  if (comm.available()) {
    String data = comm.readStringUntil('\n');
    data.trim();
    if (data.length() > 0) lastHeartbeat = millis();

    // IP is an ESP32-to-Arduino status message, not an experiment command.
    if (data.startsWith("IP:")) {
      lcd.clear();
      lcd.setCursor(0, 0); lcd.print("WiFi Connected!");
      lcd.setCursor(0, 1); lcd.print(data.substring(3));
      delay(2000);
      lcd.clear();
    } else if (data.length() > 0) {
      controller.command(data.c_str(), data.length());
    }
  }

  // The controller owns the one-second gate.  Sensor reads remain concrete
  // Arduino operations; the controller receives only a host-testable sample.
  if (millis() - lastLoop >= 1000UL) {
    lastLoop = millis();
    readSensors();
    PTKitRawSensors raw = {rawTempIR, rawTempTC, rawLux};
    controller.step(raw);
  }

  if (controller.snapshot().state == PTKIT_IDLE) {
    lcd.setCursor(0, 0); lcd.print("Waiting WiFi...");
    lcd.setCursor(0, 1); lcd.print("Check ESP32... ");
  }
}


void readSensors() {
  rawTempIR = mlx.readObjectTempC();
  rawTempTC = thermocouple.readCelsius();
  rawLux = lightMeter.readLightLevel();
  if (isnan(rawLux)) rawLux = 0.0;
}
