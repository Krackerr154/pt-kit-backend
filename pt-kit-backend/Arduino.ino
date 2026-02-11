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


// --- PIN MAPPING ---
#define PIN_RELAY       2
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


// Status Mesin
enum State { IDLE, PRE_HEAT, HEATING, COOLING, STABILIZING, DONE };
State currentState = IDLE;


// Data Variabel
String espIP = "";
bool wifiConnected = false;
float tempIR = 0.0, tempTC = 0.0;
float userMaxTemp = 100.0;       
int   userInterval = 1;          


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
   
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);
  analogWrite(PIN_FAN, 0);

  lcd.init(); lcd.backlight();
  mlx.begin();
  
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
      // === PARSING BARU (METODE POTONG KUE) ===
      // Format: SET:Durasi:Siklus:MaxTemp:Interval
      // Contoh: SET:60:5:80.0:1
      
      String raw = data; 
      raw.remove(0, 4); // Buang "SET:" -> sisa "60:5:80.0:1"
      
      // Ambil Durasi
      int firstDiv = raw.indexOf(':');
      targetSec = raw.substring(0, firstDiv).toInt();
      
      // Potong lagi -> sisa "5:80.0:1"
      raw = raw.substring(firstDiv + 1);
      int secondDiv = raw.indexOf(':');
      targetCycles = raw.substring(0, secondDiv).toInt();
      
      // Potong lagi -> sisa "80.0:1"
      raw = raw.substring(secondDiv + 1);
      int thirdDiv = raw.indexOf(':');
      userMaxTemp = raw.substring(0, thirdDiv).toFloat();
      
      // Sisanya adalah Interval -> "1"
      userInterval = raw.substring(thirdDiv + 1).toInt();
      
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
      currentState = PRE_HEAT; 
      lcd.clear();
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
      runExperimentLogic(); 
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
      digitalWrite(PIN_RELAY, LOW); analogWrite(PIN_FAN, 0); 
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
void runExperimentLogic() {
  switch (currentState) {
    case PRE_HEAT:
      currentSec++;
      digitalWrite(PIN_RELAY, HIGH); analogWrite(PIN_FAN, 0);
      updateLCD("PRE-HEAT");
      if (tempTC >= 30.0 && tempIR >= 30.0) { // Tetap pakai kedua sensor
         currentState = HEATING; currentSec=0; lcd.clear();
      }
      break;
    case HEATING:
      currentSec++;
      digitalWrite(PIN_RELAY, HIGH); analogWrite(PIN_FAN, 0);
      updateLCD("HEAT"); // Format: HEAT 5/60
      // Matikan lampu TEPAT WAKTU sesuai targetSec
      if (currentSec >= targetSec) {
        digitalWrite(PIN_RELAY, LOW); currentState = COOLING; currentSec=0; lcd.clear();
      }
      break;
    case COOLING:
      currentSec++; 
      digitalWrite(PIN_RELAY, LOW); analogWrite(PIN_FAN, 255); 
      updateLCD("COOL");
      // Tetap pakai kedua sensor seperti kode pertama
      if (tempTC <= (MAIN_TARGET - UNDERSHOOT) && tempIR <= (MAIN_TARGET - UNDERSHOOT)) {
        currentState = STABILIZING; stableCounter=0; currentSec=0; lcd.clear();
      }
      break;
    case STABILIZING:
      currentSec++;
      digitalWrite(PIN_RELAY, LOW); analogWrite(PIN_FAN, 150); 
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
    comm.println(saveFlag);
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
  tempIR = mlx.readObjectTempC(); if(isnan(tempIR)) tempIR = 0.0;
  tempTC = thermocouple.readCelsius(); if(isnan(tempTC)) tempTC = 0.0;
}

void forceStop(String reason) { 
  currentState = IDLE; 
  // Reset semua timer agar bersih saat Start baru (sama seperti DONE handler)
  currentCycleNum = 0;
  currentSec = 0;
  totalMasterSec = 0;
  stableCounter = 0;
  digitalWrite(PIN_RELAY, LOW); 
  analogWrite(PIN_FAN, 0);
  lcd.clear(); 
}

void showDone() { 
  digitalWrite(PIN_RELAY, LOW); 
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