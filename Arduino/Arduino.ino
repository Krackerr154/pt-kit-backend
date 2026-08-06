/*
 * === PT-KIT — CONTROLLER ISOLATION TEST ===
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


#define PIN_LAMP        5
#define PIN_FAN         3 
#define PIN_TC_CLK      6
#define PIN_TC_CS       7
#define PIN_TC_DO       8
#define PIN_ESP_RX      10 
#define PIN_ESP_TX      11 


SoftwareSerial comm(PIN_ESP_RX, PIN_ESP_TX); 
LiquidCrystal_I2C lcd(0x27, 16, 2);
Adafruit_MLX90614 mlx = Adafruit_MLX90614();
MAX6675 thermocouple(PIN_TC_CLK, PIN_TC_CS, PIN_TC_DO);
BH1750 lightMeter;


float rawTempIR = 0.0, rawTempTC = 0.0, rawLux = 0.0;
unsigned long lastLoop = 0; 


void setup() {
  Serial.begin(9600);
  Serial.println(F("=== ISO TEST ==="));

  comm.begin(9600); 
  Serial.println(F("1. comm"));

  pinMode(PIN_LAMP, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  analogWrite(PIN_LAMP, 0);
  analogWrite(PIN_FAN, 0);
  Serial.println(F("2. pins"));

  mlx.begin();
  Serial.println(F("3. MLX"));

  lightMeter.begin();
  Serial.println(F("4. BH1750"));

  lcd.init(); lcd.backlight();
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("All OK - no ctrl");
  Serial.println(F("5. LCD + DONE"));
}


void loop() {
  if (millis() - lastLoop >= 1000UL) {
    lastLoop = millis();
    rawTempIR = mlx.readObjectTempC();
    rawTempTC = thermocouple.readCelsius();
    rawLux = lightMeter.readLightLevel();
    Serial.print("IR="); Serial.print(rawTempIR);
    Serial.print(" TC="); Serial.print(rawTempTC);
    Serial.print(" Lux="); Serial.println(rawLux);
  }
}
