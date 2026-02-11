#include <WiFi.h>
#include "esp_wpa2.h"
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "esp_task_wdt.h"

// ==========================================
// 1. SETUP KONEKSI (ITB Hotspot Locked)
// ==========================================
const char* ssid = "ITB Hotspot"; 
const char* eap_identity = "20525011@mahasiswa.itb.ac.id";
const char* eap_username = "20525011@mahasiswa.itb.ac.id";
const char* eap_password = "mhsITB#204012"; 

// Target BSSID Router Terkuat (Channel 6)
const uint8_t target_bssid[] = {0xC8, 0x84, 0x8C, 0x6E, 0x46, 0xE0};

String baseUrl = "https://pt-kit.g-labs.my.id/api";

// ==========================================
// 2. PIN CONFIG
// ==========================================
#define RXD2 16  
#define TXD2 17  
#define QUEUE_SIZE 50 
#define MSG_SIZE 64

typedef struct { char csvLine[MSG_SIZE]; } DataPaket;
QueueHandle_t dataQueue;

// ==========================================
// TASK UPLOAD (CORE 0) - PENGIRIM KE SERVER
// ==========================================
void uploadTask(void * parameter) {
  // [FIX] Keep this commented out to prevent watchdog errors
  // esp_task_wdt_delete(NULL); 
  
  DataPaket receivedPaket;
  unsigned long lastCmdCheck = 0;
  
  WiFiClientSecure client;
  client.setInsecure(); 
  
  HTTPClient http; 
  bool isConnected = false;

  while(true) {
    
    // --- 1. GLOBAL WIFI CHECK ---
    if(WiFi.status() != WL_CONNECTED){
        Serial.println("[WiFi] Putus! Reconnecting to Fixed AP...");
        isConnected = false;
        WiFi.disconnect(); 
        
        esp_wifi_sta_wpa2_ent_enable();
        WiFi.begin(ssid, NULL, 6, target_bssid, true);
        
        vTaskDelay(2000 / portTICK_PERIOD_MS); 
        continue; 
    }

    // --- 2. AMBIL DATA DARI ANTRIAN ---
    if (xQueueReceive(dataQueue, &receivedPaket, 5) == pdPASS) {
        
        bool packetSent = false;
        int retryCount = 0;

        // [FITUR BARU: RETRY LOOP]
        // Loop ini akan menahan proses sampai data BERHASIL terkirim
        while(!packetSent) {
            
            // Cek WiFi di dalam loop retry (Penting jika putus saat sedang retry)
            if(WiFi.status() != WL_CONNECTED) {
                Serial.println("[Retry] WiFi Lost! Waiting...");
                isConnected = false;
                // Kita tunggu saja, biarkan logic reconnect di atas atau auto-reconnect bekerja
                vTaskDelay(1000 / portTICK_PERIOD_MS);
                
                // Jika ingin memaksa reconnect di sini bisa, tapi delay saja cukup aman
                // untuk menghindari konflik stack WiFi.
                continue; 
            }

            // Setup HTTP Connection jika belum connect
            if (!isConnected) {
                isConnected = http.begin(client, baseUrl + "/insert_data");
                if(isConnected) http.addHeader("Content-Type", "application/json");
            }

            if (isConnected) {
                String jsonPayload = "{\"csv_line\": \"" + String(receivedPaket.csvLine) + "\"}";
                
                unsigned long tStart = millis();
                int httpCode = http.POST(jsonPayload);
                unsigned long duration = millis() - tStart;
                
                if(httpCode > 0) {
                   // --- SUKSES ---
                   Serial.printf("[TX] OK (%dms) >> %s\n", duration, receivedPaket.csvLine);
                   packetSent = true; // KELUAR DARI LOOP RETRY
                } else {
                   // --- GAGAL (RETRY) ---
                   retryCount++;
                   Serial.printf("[TX] FAIL (%s) Try #%d >> %s\n", http.errorToString(httpCode).c_str(), retryCount, receivedPaket.csvLine);
                   http.end(); 
                   isConnected = false; 
                   
                   // Tunggu sebentar sebelum coba lagi (Backoff)
                   vTaskDelay(500 / portTICK_PERIOD_MS); 
                }
            } else {
                // Gagal connect ke server
                isConnected = false;
                vTaskDelay(500 / portTICK_PERIOD_MS);
            }
            
            // Safety: Beri napas untuk Watchdog saat stuck di retry loop
            vTaskDelay(10 / portTICK_PERIOD_MS);
        }
    }

    // --- 3. CEK PERINTAH (Interval 3 Detik) ---
    // Tetap dijalankan agar tombol STOP di web tetap responsif (jika internet lancar)
    if (millis() - lastCmdCheck > 3000) {
      lastCmdCheck = millis();
      
      HTTPClient httpCmd;
      WiFiClientSecure clientCmd;
      clientCmd.setInsecure();
      
      if (httpCmd.begin(clientCmd, baseUrl + "/check_command")) {
          int httpCode = httpCmd.GET();
          if (httpCode == 200) {
              String p = httpCmd.getString();
              if (p.indexOf("IDLE") == -1) { 
                    // [FIX] Robust JSON parsing — cari value string setelah key "command"
                    int keyPos = p.indexOf("\"command\"");
                    if (keyPos >= 0) {
                        int colonPos = p.indexOf(':', keyPos);
                        if (colonPos >= 0) {
                            int openQuote = p.indexOf('"', colonPos);
                            if (openQuote >= 0) {
                                int closeQuote = p.indexOf('"', openQuote + 1);
                                if (closeQuote > openQuote) {
                                    String c = p.substring(openQuote + 1, closeQuote);
                                    Serial.println("[CMD] Diterima Server: " + c);
                                    Serial2.println(c); 
                                }
                            }
                        }
                    }
              }
          }
          httpCmd.end();
      }
    }
    
    // Wajib ada delay kecil untuk Watchdog Core 0
    vTaskDelay(1 / portTICK_PERIOD_MS); 
  }
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); 
  
  Serial.begin(115200); 
  
  // [WAJIB] Perbesar Buffer Penerima agar data Arduino tertampung saat WiFi Retry
  Serial2.setRxBufferSize(2048); 
  
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2); 
  
  dataQueue = xQueueCreate(QUEUE_SIZE, sizeof(DataPaket));

  Serial.println("\n--- ESP32 ITB HOTSPOT LOCKED MODE (RETRY ENABLED) ---");
  Serial.printf("Target AP: %02X:%02X:%02X:%02X:%02X:%02X (Ch 6)\n", 
                target_bssid[0], target_bssid[1], target_bssid[2], 
                target_bssid[3], target_bssid[4], target_bssid[5]);

  WiFi.disconnect(true);
  WiFi.mode(WIFI_STA);
  
  // Setup Enterprise Credentials
  esp_wifi_sta_wpa2_ent_set_identity((uint8_t *)eap_identity, strlen(eap_identity));
  esp_wifi_sta_wpa2_ent_set_username((uint8_t *)eap_username, strlen(eap_username));
  esp_wifi_sta_wpa2_ent_set_password((uint8_t *)eap_password, strlen(eap_password));
  esp_wifi_sta_wpa2_ent_enable();
  
  // Connect dengan BSSID Locking
  WiFi.begin(ssid, NULL, 6, target_bssid, true);

  int tryCount = 0;
  while (WiFi.status() != WL_CONNECTED) { 
    delay(500); 
    Serial.print("."); 
    tryCount++;
    // Logic restart WiFi jika stuck 20 detik
    if(tryCount > 40) {
        Serial.println("\n[Setup] Retry Connection...");
        WiFi.disconnect(true);
        esp_wifi_sta_wpa2_ent_enable();
        WiFi.begin(ssid, NULL, 6, target_bssid, true);
        tryCount = 0;
    }
  }
  
  Serial.println("\nConnected to ITB Hotspot!");
  Serial.println("IP: " + WiFi.localIP().toString());
  
  delay(2000); 
  Serial2.println("IP:" + WiFi.localIP().toString()); // Info ke Arduino

  // Jalankan Task Upload
  xTaskCreatePinnedToCore(uploadTask, "UploadTask", 10000, NULL, 1, NULL, 0);
}

void loop() {
  // --- CORE 1: PENERIMA DATA DARI ARDUINO ---
  if (Serial2.available()) {
    String input = Serial2.readStringUntil('\n');
    input.trim();
    
    if (input.length() > 2) { // Filter noise pendek
      DataPaket item;
      strncpy(item.csvLine, input.c_str(), MSG_SIZE);
      item.csvLine[MSG_SIZE - 1] = '\0';
      
      if (xQueueSend(dataQueue, &item, 0) == pdPASS) {
         Serial.printf("[BUF] In  << %s\n", input.c_str());
      } else {
         Serial.printf("[FULL] DROP !! %s\n", input.c_str());
      }
    }
  }
}