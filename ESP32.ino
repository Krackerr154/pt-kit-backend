#include <WiFi.h>
#include "esp_wpa2.h"
#include "esp_arduino_version.h"
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "esp_task_wdt.h"
#include "esp_system.h"
#include <stdarg.h>

// Set to 1 while diagnosing intermittent stale/communication states.
// The USB debug serial port is 115200 baud. Credentials are never printed.
#define PTKIT_DEBUG_LOGGING 1
// TEMPORARY DIAGNOSTIC MODE is disabled for the connectivity build. The watchdog
// remains enabled so a network hang cannot silently leave outputs uncontrolled.
#define PTKIT_DISABLE_WATCHDOG 0
#define PTKIT_FIRMWARE_TAG "PTKIT_CONNECTIVITY_V9"

#if __has_include("ESP32.local.h")
#include "ESP32.local.h"
#endif

// ==========================================
// 1. CONNECTION CONFIGURATION
// ==========================================
// Provision these with build flags or edit this local, uncommitted block.
// Never commit Wi-Fi credentials or session secrets to the firmware source.
#ifndef PTKIT_WIFI_SSID
#define PTKIT_WIFI_SSID ""
#endif
#ifndef PTKIT_EAP_IDENTITY
#define PTKIT_EAP_IDENTITY ""
#endif
#ifndef PTKIT_EAP_USERNAME
#define PTKIT_EAP_USERNAME ""
#endif
#ifndef PTKIT_EAP_PASSWORD
#define PTKIT_EAP_PASSWORD ""
#endif
#ifndef PTKIT_API_BASE_URL
#define PTKIT_API_BASE_URL "https://pt-kit.g-labs.my.id/api"
#endif
#ifndef PTKIT_ROOT_CA
#define PTKIT_ROOT_CA ""
#endif
const char* ssid = PTKIT_WIFI_SSID;
const char* eap_identity = PTKIT_EAP_IDENTITY;
const char* eap_username = PTKIT_EAP_USERNAME;
const char* eap_password = PTKIT_EAP_PASSWORD;
String baseUrl = PTKIT_API_BASE_URL;

// Optional BSSID pinning. Leave false unless the deployment AP is intentionally fixed.
const bool PIN_TARGET_BSSID = false;
const uint8_t target_bssid[] = {0, 0, 0, 0, 0, 0};

// TLS CA is supplied as a local build flag/header; blank means network calls fail closed.
#ifndef PTKIT_ROOT_CA
#define PTKIT_ROOT_CA ""
#endif


// ==========================================
// 2. PT-KIT OFFLOAD ARCHITECTURE
// ==========================================
// Core 0: Wi-Fi supervision, backend command polling, bounded HTTP uploads.
// Core 1: the sole owner of Serial2, compact Uno transport, controller and telemetry formatting.
// No Wi-Fi/HTTP call is permitted in either Core-1 task.

#include "ptkit_offload_protocol.h"
#include "ptkit_offload_controller.h"

#define RXD2 16
#define TXD2 17

const uint8_t NETWORK_CORE = 0;
const uint8_t CONTROL_CORE = 1;
const uint16_t UART_BAUD = 9600;
const uint16_t CONTROL_HEARTBEAT_MS = 500;
const uint16_t CONTROL_TTL_MS = 3000;
const uint16_t ARM_RETRY_MS = 500;
const uint16_t CAL_RETRY_MS = 500;
// Keep command polling deliberately sparse: the backend HTTPS GET can take several
// seconds on this deployment. A tight poll loop can starve CPU0 idle time and trip
// the ESP32 task watchdog while telemetry is also waiting for the network core.
const uint16_t COMMAND_POLL_MS = 5000;
const uint16_t WIFI_RETRY_MS = 15000;
const uint8_t WIFI_FRESH_SCAN_EVERY = 3;
const uint8_t UPLOAD_ATTEMPTS = 2;
const uint16_t HTTP_CONNECT_TIMEOUT_MS = 2500;
const uint16_t HTTP_RESPONSE_TIMEOUT_MS = 3500;
const uint16_t HTTP_GUARD_MS = 1200;
const uint16_t NETWORK_REQUEST_GAP_MS = 150;
const uint16_t DEBUG_HEARTBEAT_MS = 5000;

struct UploadPacket { char line[192]; };
struct CommandPacket { char command[ptkit::BACKEND_COMMAND_MAX_CHARS]; };
struct UartTxPacket { char frame[ptkit::FRAME_MAX_CHARS]; };
enum UnoEventType : uint8_t { UNO_EVENT_ACK, UNO_EVENT_FAULT, UNO_EVENT_CALIBRATION, UNO_EVENT_LINK_PAUSED };
struct UnoEvent {
  UnoEventType type;
  ptkit::AckPacket ack;
  uint8_t fault;
  ptkit::CalibrationResultPacket calibration;
  ptkit::LinkPausePacket linkPause;
};

static portMUX_TYPE debugMux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint32_t debugUartRxFrames = 0;
static volatile uint32_t debugUartRxBadFrames = 0;
static volatile uint32_t debugUartTxFrames = 0;
static volatile uint32_t debugUartTxDrops = 0;
static volatile uint32_t debugSensorPackets = 0;
static volatile uint32_t debugUploadQueued = 0;
static volatile uint32_t debugUploadSent = 0;
static volatile uint32_t debugUploadFailed = 0;
static volatile uint32_t debugBackendPolls = 0;
static volatile uint32_t debugBackendPollErrors = 0;
static volatile uint32_t debugBackendCommands = 0;
static volatile uint32_t debugCommandDrops = 0;
static volatile uint32_t debugLastUartRxMs = 0;
static volatile uint32_t debugLastUartTxMs = 0;
static volatile uint32_t debugLastSensorMs = 0;
static volatile uint32_t debugLastUploadMs = 0;
static volatile uint32_t debugLastBackendPollMs = 0;
static volatile uint32_t debugLastBackendCommandMs = 0;
static uint32_t debugLastHeartbeatMs = 0;

static void debugLog(const char *format, ...) {
#if PTKIT_DEBUG_LOGGING
  char buffer[256];
  va_list args;
  va_start(args, format);
  vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);
  Serial.printf("[%10lu ms] %s\n", static_cast<unsigned long>(millis()), buffer);
#endif
}

static const char *wifiStatusName(wl_status_t status) {
  switch (status) {
    case WL_CONNECTED: return "CONNECTED";
    case WL_NO_SSID_AVAIL: return "NO_SSID";
    case WL_CONNECT_FAILED: return "CONNECT_FAILED";
    case WL_CONNECTION_LOST: return "CONNECTION_LOST";
    case WL_DISCONNECTED: return "DISCONNECTED";
    case WL_IDLE_STATUS: return "IDLE";
    default: return "OTHER";
  }
}

static void debugStatus(const char *label) {
#if PTKIT_DEBUG_LOGGING
  const wl_status_t status = WiFi.status();
  Serial.printf("[wifi] %s status=%d(%s) connected=%d ssid=%s rssi=%d ip=%s heap=%u\n",
                label ? label : "status", static_cast<int>(status), wifiStatusName(status), status == WL_CONNECTED ? 1 : 0,
                ssid[0] ? "configured" : "MISSING", status == WL_CONNECTED ? WiFi.RSSI() : 0,
                WiFi.localIP().toString().c_str(), static_cast<unsigned>(ESP.getFreeHeap()));
#endif
}

static void debugSnapshot(const char *reason) {
#if PTKIT_DEBUG_LOGGING
  uint32_t uartRx, uartBad, uartTx, uartDrop, sensors, uploadQ, uploadOk, uploadFail;
  uint32_t polls, pollErrors, commands, commandDrops, lastRx, lastTx, lastSensor, lastUpload, lastPoll, lastCommand;
  portENTER_CRITICAL(&debugMux);
  uartRx = debugUartRxFrames; uartBad = debugUartRxBadFrames; uartTx = debugUartTxFrames; uartDrop = debugUartTxDrops;
  sensors = debugSensorPackets; uploadQ = debugUploadQueued; uploadOk = debugUploadSent; uploadFail = debugUploadFailed;
  polls = debugBackendPolls; pollErrors = debugBackendPollErrors; commands = debugBackendCommands; commandDrops = debugCommandDrops;
  lastRx = debugLastUartRxMs; lastTx = debugLastUartTxMs; lastSensor = debugLastSensorMs; lastUpload = debugLastUploadMs;
  lastPoll = debugLastBackendPollMs; lastCommand = debugLastBackendCommandMs;
  portEXIT_CRITICAL(&debugMux);
  debugLog("snapshot=%s UART rx=%lu bad=%lu tx=%lu tx_drop=%lu sensor=%lu upload_queued=%lu sent=%lu failed=%lu polls=%lu poll_err=%lu commands=%lu cmd_drop=%lu last_rx=%lums last_tx=%lums last_sensor=%lums last_upload=%lums last_poll=%lums last_cmd=%lums free_heap=%u",
            reason ? reason : "periodic", static_cast<unsigned long>(uartRx), static_cast<unsigned long>(uartBad),
            static_cast<unsigned long>(uartTx), static_cast<unsigned long>(uartDrop), static_cast<unsigned long>(sensors),
            static_cast<unsigned long>(uploadQ), static_cast<unsigned long>(uploadOk), static_cast<unsigned long>(uploadFail),
            static_cast<unsigned long>(polls), static_cast<unsigned long>(pollErrors), static_cast<unsigned long>(commands),
            static_cast<unsigned long>(commandDrops), static_cast<unsigned long>(lastRx), static_cast<unsigned long>(lastTx),
            static_cast<unsigned long>(lastSensor), static_cast<unsigned long>(lastUpload), static_cast<unsigned long>(lastPoll),
            static_cast<unsigned long>(lastCommand), static_cast<unsigned>(ESP.getFreeHeap()));
#endif
}

static void onWiFiEvent(arduino_event_t *event) {
#if PTKIT_DEBUG_LOGGING
  if (!event) return;
  switch (event->event_id) {
    case ARDUINO_EVENT_WIFI_STA_START:
      debugLog("[wifi] STA_START");
      break;
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      debugLog("[wifi] CONNECTED channel=%u authmode=%u", static_cast<unsigned>(event->event_info.wifi_sta_connected.channel),
               static_cast<unsigned>(event->event_info.wifi_sta_connected.authmode));
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED: {
      const uint8_t reason = event->event_info.wifi_sta_disconnected.reason;
      debugLog("[wifi] DISCONNECTED reason=%u name=%s rssi=%d", static_cast<unsigned>(reason),
               WiFi.disconnectReasonName(static_cast<wifi_err_reason_t>(reason)),
               static_cast<int>(event->event_info.wifi_sta_disconnected.rssi));
      break;
    }
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      debugStatus("GOT_IP");
      break;
    case ARDUINO_EVENT_WIFI_STA_LOST_IP:
      debugLog("[wifi] LOST_IP");
      break;
    default:
      break;
  }
#endif
}

QueueHandle_t uploadQueue;
QueueHandle_t commandQueue;
QueueHandle_t uartTxQueue;
QueueHandle_t sensorQueue;
QueueHandle_t eventQueue;
SemaphoreHandle_t httpMutex;

static bool enqueueUpload(const char *line) {
  if (!line || !*line) return false;
  UploadPacket packet;
  strncpy(packet.line, line, sizeof(packet.line) - 1U);
  packet.line[sizeof(packet.line) - 1U] = '\0';
  const bool accepted = xQueueSend(uploadQueue, &packet, 0) == pdPASS;
  if (accepted) {
    ++debugUploadQueued;
    debugLog("[upload] queued len=%u data=%s", static_cast<unsigned>(strlen(packet.line)), packet.line);
  } else {
    ++debugUploadFailed;
    debugLog("[upload] QUEUE_DROP len=%u queue_full=1", static_cast<unsigned>(strlen(packet.line)));
  }
  return accepted;
}

static bool enqueueUartFrame(const char *frame) {
  if (!frame || !*frame) return false;
  UartTxPacket packet;
  strncpy(packet.frame, frame, sizeof(packet.frame) - 1U);
  packet.frame[sizeof(packet.frame) - 1U] = '\0';
  const bool accepted = xQueueSend(uartTxQueue, &packet, 0) == pdPASS;
  if (accepted) {
    debugLog("[uart] TX_QUEUED len=%u frame=%s", static_cast<unsigned>(strlen(packet.frame)), packet.frame);
  } else {
    ++debugUartTxDrops;
    debugLog("[uart] TX_QUEUE_DROP frame=%s", packet.frame);
  }
  return accepted;
}

static void sendFrameArm(uint16_t sequence, uint16_t maxTempDeciC) {
  char frame[ptkit::FRAME_MAX_CHARS];
  if (ptkit::frameArm(frame, sizeof(frame), sequence, maxTempDeciC)) enqueueUartFrame(frame);
}

static void sendFrameStop(uint16_t sequence) {
  char frame[ptkit::FRAME_MAX_CHARS];
  if (ptkit::frameStop(frame, sizeof(frame), sequence)) enqueueUartFrame(frame);
}

static void sendFrameCalibration(uint16_t sequence, uint8_t phase) {
  char frame[ptkit::FRAME_MAX_CHARS];
  if (ptkit::frameCalibration(frame, sizeof(frame), sequence, phase)) enqueueUartFrame(frame);
}

static bool wifiReady() {
  return WiFi.status() == WL_CONNECTED;
}

static void beginEnterpriseWifi() {
  if (!ssid[0] || !eap_identity[0] || !eap_username[0] || !eap_password[0]) {
    debugLog("[wifi] CONFIG_MISSING ssid=%d identity=%d username=%d password=%d",
             ssid[0] ? 1 : 0, eap_identity[0] ? 1 : 0, eap_username[0] ? 1 : 0, eap_password[0] ? 1 : 0);
    return;
  }
  debugLog("[wifi] BEGIN enterprise PEAP ssid_configured=1 bssid_pin=%d", PIN_TARGET_BSSID ? 1 : 0);
  // Campus deployments can expose the same SSID through many APs. Scan every
  // channel and let the ESP32 choose the matching AP with the strongest RSSI.
  // BSSID pinning remains disabled so the choice can change as the device moves.
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  debugLog("[wifi] AP_SELECTION scan=all_channels sort=signal bssid_pin=%d", PIN_TARGET_BSSID ? 1 : 0);
  if (PIN_TARGET_BSSID) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
    WiFi.begin(ssid, WPA2_AUTH_PEAP, eap_identity, eap_username, eap_password,
               NULL, NULL, NULL, -1, 6, target_bssid, true);
#else
    WiFi.begin(ssid, WPA2_AUTH_PEAP, eap_identity, eap_username, eap_password,
               NULL, NULL, NULL, -1, target_bssid, true);
#endif
  } else {
    WiFi.begin(ssid, WPA2_AUTH_PEAP, eap_identity, eap_username, eap_password);
  }
  debugStatus("after_begin");
}

// ── HTTP connections (old proven transport pattern) ────────────────────────
// Keep exactly one telemetry client alive, matching the working standalone
// uploader. The command client is short-lived and destroyed after each poll.
// TLS certificate verification is intentionally disabled per deployment choice.

static WiFiClientSecure *telemetryClient = nullptr;
static HTTPClient *telemetryHttp = nullptr;
static bool telemetryReady = false;

static bool initTelemetryHttp() {
  if (telemetryReady) return true;
  if (!baseUrl.length()) {
    debugLog("[http] telemetry CONFIG_FAIL api_url=0");
    return false;
  }
  telemetryClient = new WiFiClientSecure();
  telemetryClient->setInsecure();
  telemetryClient->setHandshakeTimeout(3);
  telemetryHttp = new HTTPClient();
  telemetryHttp->setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  telemetryHttp->setTimeout(HTTP_RESPONSE_TIMEOUT_MS);
  telemetryHttp->setReuse(true);
  const String endpoint = baseUrl + "/insert_data";
  if (!telemetryHttp->begin(*telemetryClient, endpoint)) {
    debugLog("[http] telemetry PERSISTENT_BEGIN_FAIL");
    delete telemetryHttp; telemetryHttp = nullptr;
    delete telemetryClient; telemetryClient = nullptr;
    return false;
  }
  telemetryHttp->addHeader("Content-Type", "application/json");
  telemetryReady = true;
  debugLog("[http] telemetry persistent connection initialized");
  return true;
}

static void destroyTelemetryHttp() {
  if (telemetryHttp) { telemetryHttp->end(); delete telemetryHttp; telemetryHttp = nullptr; }
  if (telemetryClient) { delete telemetryClient; telemetryClient = nullptr; }
  telemetryReady = false;
}

// ── End HTTP transport ─────────────────────────────────────────────────────

static bool postTelemetry(const char *line) {
  if (!wifiReady() || !line) {
    debugLog("[http] telemetry SKIP wifi=%d line=%d", wifiReady() ? 1 : 0, line ? 1 : 0);
    return false;
  }
  if (xSemaphoreTake(httpMutex, pdMS_TO_TICKS(HTTP_GUARD_MS)) != pdTRUE) {
    debugLog("[http] telemetry SKIP reason=http_busy");
    return false;
  }
  bool result = false;
  if (!telemetryReady && !initTelemetryHttp()) {
    debugLog("[http] telemetry INIT_FAIL");
    xSemaphoreGive(httpMutex);
    return false;
  }
  const String payload = String("{\"csv_line\":\"") + String(line) + "\"}";
  const unsigned long started = millis();
  debugLog("[http] telemetry POST START payload_bytes=%u", static_cast<unsigned>(payload.length()));
  const int status = telemetryHttp->POST(payload);
  const unsigned long elapsed = millis() - started;
  const String response = status > 0 ? telemetryHttp->getString() : String();
  if (status <= 0) {
    debugLog("[http] telemetry CONNECTION_LOST status=%d error=%s", status,
             telemetryHttp->errorToString(status).c_str());
    destroyTelemetryHttp();
  }
  const bool success = status >= 200 && status < 300;
  debugLog("[http] telemetry POST END status=%d success=%d elapsed_ms=%lu response_bytes=%u response=%s",
           status, success ? 1 : 0, static_cast<unsigned long>(elapsed), static_cast<unsigned>(response.length()), response.c_str());
  result = success;
  xSemaphoreGive(httpMutex);
  vTaskDelay(pdMS_TO_TICKS(NETWORK_REQUEST_GAP_MS));
  return result;
}

static bool extractCommand(const String &json, char *out, size_t capacity) {
  if (!out || capacity < 2) return false;
  const int key = json.indexOf("\"command\"");
  if (key < 0) return false;
  const int colon = json.indexOf(':', key);
  if (colon < 0) return false;
  const int openQuote = json.indexOf('"', colon);
  if (openQuote < 0) return false;
  const int closeQuote = json.indexOf('"', openQuote + 1);
  if (closeQuote <= openQuote) return false;
  const int length = closeQuote - openQuote - 1;
  if (length <= 0 || static_cast<size_t>(length) >= capacity) return false;
  json.substring(openQuote + 1, closeQuote).toCharArray(out, capacity);
  return true;
}

static bool pollBackendCommand(CommandPacket &packet) {
  ++debugBackendPolls;
  debugLastBackendPollMs = millis();
  if (!wifiReady()) {
    ++debugBackendPollErrors;
    debugLog("[http] command GET SKIP wifi=0");
    return false;
  }
  if (xSemaphoreTake(httpMutex, pdMS_TO_TICKS(HTTP_GUARD_MS)) != pdTRUE) {
    ++debugBackendPollErrors;
    debugLog("[http] command GET SKIP reason=http_busy");
    return false;
  }
  // Match the working standalone uploader: one temporary command client per
  // poll, with certificate verification disabled and no second persistent TLS
  // allocation competing with the telemetry connection.
  WiFiClientSecure commandClient;
  commandClient.setInsecure();
  commandClient.setHandshakeTimeout(3);
  HTTPClient commandHttp;
  commandHttp.setConnectTimeout(HTTP_CONNECT_TIMEOUT_MS);
  commandHttp.setTimeout(HTTP_RESPONSE_TIMEOUT_MS);
  if (!commandHttp.begin(commandClient, baseUrl + "/check_command")) {
    ++debugBackendPollErrors;
    debugLog("[http] command BEGIN_FAIL");
    xSemaphoreGive(httpMutex);
    return false;
  }
  const unsigned long started = millis();
  debugLog("[http] command GET START");
  const int status = commandHttp.GET();
  const unsigned long elapsed = millis() - started;
  const String body = status > 0 ? commandHttp.getString() : String();
  if (status <= 0) {
    debugLog("[http] command CONNECTION_LOST status=%d error=%s", status,
             commandHttp.errorToString(status).c_str());
    commandHttp.end();
    ++debugBackendPollErrors;
    xSemaphoreGive(httpMutex);
    vTaskDelay(pdMS_TO_TICKS(NETWORK_REQUEST_GAP_MS));
    return false;
  }
  if (status != 200) {
    ++debugBackendPollErrors;
    debugLog("[http] command GET END status=%d elapsed_ms=%lu response_bytes=%u body=%s",
             status, static_cast<unsigned long>(elapsed), static_cast<unsigned>(body.length()), body.c_str());
    commandHttp.end();
    xSemaphoreGive(httpMutex);
    vTaskDelay(pdMS_TO_TICKS(NETWORK_REQUEST_GAP_MS));
    return false;
  }
  if (!extractCommand(body, packet.command, sizeof(packet.command))) {
    debugLog("[http] command GET status=200 parse=FAIL body=%s", body.c_str());
    commandHttp.end();
    xSemaphoreGive(httpMutex);
    vTaskDelay(pdMS_TO_TICKS(NETWORK_REQUEST_GAP_MS));
    return false;
  }
  const bool actionable = strcmp(packet.command, "IDLE") != 0;
  debugLog("[http] command GET END status=200 elapsed_ms=%lu response_bytes=%u command=%s actionable=%d",
           static_cast<unsigned long>(elapsed), static_cast<unsigned>(body.length()), packet.command, actionable ? 1 : 0);
  commandHttp.end();
  xSemaphoreGive(httpMutex);
  vTaskDelay(pdMS_TO_TICKS(NETWORK_REQUEST_GAP_MS));
  return actionable;
}

void wifiSupervisorTask(void *) {
  unsigned long lastAttempt = 0;
  unsigned long lastStatus = 0;
  uint8_t failedReconnects = 0;
  for (;;) {
    const unsigned long now = millis();
    if (wifiReady()) {
      failedReconnects = 0;
    } else if (now - lastAttempt >= WIFI_RETRY_MS) {
      lastAttempt = now;
      ++failedReconnects;
      const bool freshScan = (failedReconnects % WIFI_FRESH_SCAN_EVERY) == 0;
      debugLog("[wifi] RETRY begin attempt=%u fresh_scan=%d", static_cast<unsigned>(failedReconnects), freshScan ? 1 : 0);
      debugStatus("before_retry");
      // Normal retries preserve the current STA profile and avoid an association
      // flap. Periodically force a fresh all-channel scan so a campus AP change
      // can be selected by RSSI after repeated failed reconnects.
      if (freshScan) {
        debugLog("[wifi] FRESH_SCAN restart reason=reconnect_failures");
        WiFi.disconnect(false);
        beginEnterpriseWifi();
      } else if (!WiFi.reconnect()) {
        beginEnterpriseWifi();
      }
    }
    if (now - lastStatus >= DEBUG_HEARTBEAT_MS) {
      lastStatus = now;
      debugStatus("heartbeat");
      debugSnapshot("periodic");
    }
    vTaskDelay(pdMS_TO_TICKS(250));
  }
}

void backendUploadTask(void *) {
  UploadPacket packet;
  for (;;) {
    if (xQueueReceive(uploadQueue, &packet, pdMS_TO_TICKS(250)) == pdPASS) {
      bool sent = false;
      debugLog("[upload] dequeued len=%u", static_cast<unsigned>(strlen(packet.line)));
      for (uint8_t attempt = 0; attempt < UPLOAD_ATTEMPTS && !sent; ++attempt) {
        debugLog("[upload] attempt=%u/%u wifi=%d", static_cast<unsigned>(attempt + 1U),
                 static_cast<unsigned>(UPLOAD_ATTEMPTS), wifiReady() ? 1 : 0);
        if (wifiReady()) sent = postTelemetry(packet.line);
        if (!sent) vTaskDelay(pdMS_TO_TICKS(250U * (attempt + 1U)));
      }
      if (sent) {
        ++debugUploadSent;
        debugLastUploadMs = millis();
        debugLog("[upload] SENT total=%lu", static_cast<unsigned long>(debugUploadSent));
      } else {
        ++debugUploadFailed;
        debugLog("[upload] RETRY_EXHAUSTED packet_dropped=1 total_failed=%lu",
                 static_cast<unsigned long>(debugUploadFailed));
      }
    }
  }
}

void backendCommandTask(void *) {
  for (;;) {
    CommandPacket packet;
    if (pollBackendCommand(packet)) {
      ++debugBackendCommands;
      debugLastBackendCommandMs = millis();
      if (xQueueSend(commandQueue, &packet, pdMS_TO_TICKS(100)) != pdPASS) {
        ++debugCommandDrops;
        debugLog("[command] QUEUE_DROP command=%s", packet.command);
      } else {
        debugLog("[command] QUEUED command=%s", packet.command);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(COMMAND_POLL_MS));
  }
}

static void publishUnoEvent(const UnoEvent &event) {
  if (xQueueSend(eventQueue, &event, 0) != pdPASS) {
    debugLog("[uart] EVENT_QUEUE_DROP type=%u", static_cast<unsigned>(event.type));
  } else {
    debugLog("[uart] EVENT_QUEUED type=%u", static_cast<unsigned>(event.type));
  }
}

static void decodeUnoFrame(const char *frame) {
  ptkit::SensorPacket sensor;
  ptkit::AckPacket ack;
  ptkit::CalibrationResultPacket calibration;
  ptkit::LinkPausePacket linkPause;
  uint8_t fault = ptkit::FAULT_NONE;
  UnoEvent event;
  if (ptkit::parseSensor(frame, sensor)) {
    ++debugUartRxFrames;
    ++debugSensorPackets;
    debugLastUartRxMs = millis();
    debugLastSensorMs = debugLastUartRxMs;
    xQueueOverwrite(sensorQueue, &sensor);
    debugLog("[uart] RX_SENSOR frame=%s ir=%ld tc=%ld lux=%lu flags=%u",
             frame, static_cast<long>(sensor.irDeciC), static_cast<long>(sensor.tcDeciC),
             static_cast<unsigned long>(sensor.lux), static_cast<unsigned>(sensor.flags));
    return;
  }
  if (ptkit::parseAck(frame, ack)) {
    ++debugUartRxFrames;
    debugLastUartRxMs = millis();
    event.type = UNO_EVENT_ACK;
    event.ack = ack;
    event.fault = ptkit::FAULT_NONE;
    debugLog("[uart] RX_ACK frame=%s seq=%u code=%u", frame, static_cast<unsigned>(ack.sequence), static_cast<unsigned>(ack.code));
    publishUnoEvent(event);
    return;
  }
  if (ptkit::parseLinkPause(frame, linkPause)) {
    ++debugUartRxFrames;
    debugLastUartRxMs = millis();
    event.type = UNO_EVENT_LINK_PAUSED;
    event.linkPause = linkPause;
    event.fault = ptkit::FAULT_NONE;
    debugLog("[uart] RX_LINK_PAUSED frame=%s last_output_seq=%u lamp=%u fan=%u", frame,
             static_cast<unsigned>(linkPause.lastOutputSequence), static_cast<unsigned>(linkPause.lampPwm),
             static_cast<unsigned>(linkPause.fanPwm));
    publishUnoEvent(event);
    return;
  }
  if (ptkit::parseFault(frame, fault)) {
    ++debugUartRxFrames;
    debugLastUartRxMs = millis();
    event.type = UNO_EVENT_FAULT;
    event.fault = fault;
    debugLog("[uart] RX_FAULT frame=%s fault=%u", frame, static_cast<unsigned>(fault));
    publishUnoEvent(event);
    return;
  }
  if (ptkit::parseCalibrationResult(frame, calibration)) {
    ++debugUartRxFrames;
    debugLastUartRxMs = millis();
    event.type = UNO_EVENT_CALIBRATION;
    event.calibration = calibration;
    event.fault = ptkit::FAULT_NONE;
    debugLog("[uart] RX_CAL_RESULT frame=%s phase=%u bare=%lu taped=%lu factor_permille=%u max=%lu",
             frame, static_cast<unsigned>(calibration.phase), static_cast<unsigned long>(calibration.bareDeciLux),
             static_cast<unsigned long>(calibration.tapedDeciLux), static_cast<unsigned>(calibration.attenuationPermille),
             static_cast<unsigned long>(calibration.maxDeciLux));
    publishUnoEvent(event);
    return;
  }
  ++debugUartRxBadFrames;
  debugLog("[uart] RX_BAD frame=%s reason=CRC_OR_FORMAT", frame);
}

void uartTransportTask(void *) {
  char frame[ptkit::FRAME_MAX_CHARS];
  uint8_t length = 0;
  for (;;) {
    while (Serial2.available()) {
      const char c = static_cast<char>(Serial2.read());
      if (c == '\r') continue;
      if (c == '\n') {
        frame[length] = '\0';
        if (length) decodeUnoFrame(frame);
        length = 0;
      } else if (length + 1U < sizeof(frame)) {
        frame[length++] = c;
      } else {
        length = 0;
        ++debugUartRxBadFrames;
        debugLog("[uart] RX_OVERSIZE frame_discarded=1");
      }
    }
    UartTxPacket outbound;
    if (xQueueReceive(uartTxQueue, &outbound, 0) == pdPASS) {
      Serial2.println(outbound.frame);
      ++debugUartTxFrames;
      debugLastUartTxMs = millis();
      debugLog("[uart] TX_SENT frame=%s", outbound.frame);
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

static ptkit::SensorSample toSample(const ptkit::SensorPacket &packet) {
  ptkit::SensorSample sample;
  sample.irDeciC = packet.irDeciC;
  sample.tcDeciC = packet.tcDeciC;
  sample.lux = packet.lux;
  sample.maxHardwareLux = packet.maxHardwareLux;
  sample.flags = packet.flags;
  return sample;
}

static float celsiusValue(int32_t deci) {
  return deci == ptkit::INVALID_DECI_C ? NAN : static_cast<float>(deci) / 10.0f;
}

static const char *modeName(const ptkit::ControlSnapshot &snapshot) {
  if (snapshot.kind == ptkit::COMMAND_NORMAL) return "NORMAL_CYCLIC";
  if (snapshot.kind == ptkit::COMMAND_FIXED) return "FIXED_TEMPERATURE";
  if (snapshot.kind == ptkit::COMMAND_PLATEAU) return "NATURAL_PLATEAU";
  return "";
}

static void buildTelemetry(char *line, size_t capacity, const ptkit::SensorPacket &sensor,
                           const ptkit::ControlSnapshot &snapshot, uint8_t stateOverride,
                           uint32_t logIntervalSeconds) {
  const uint8_t state = stateOverride == 255 ? snapshot.stateCode : stateOverride;
  const bool terminal = state == ptkit::STATE_DONE || state == ptkit::STATE_ABORTED;
  const uint32_t interval = logIntervalSeconds ? logIntervalSeconds : 1UL;
  const uint8_t save = terminal || (state != ptkit::STATE_IDLE && snapshot.totalSeconds % interval == 0) ? 1U : 0U;
  snprintf(line, capacity,
           "%lu,%lu,%lu,%u,%.1f,%.1f,%lu,%u,%s,%.1f,%.1f,%.1f,%u,%lu,%lu,%u,%.1f",
           static_cast<unsigned long>(snapshot.totalSeconds), static_cast<unsigned long>(snapshot.phaseSeconds),
           static_cast<unsigned long>(snapshot.cycleNum), static_cast<unsigned>(state),
           celsiusValue(sensor.irDeciC), celsiusValue(sensor.tcDeciC), static_cast<unsigned long>(sensor.lux),
           static_cast<unsigned>(save), modeName(snapshot), celsiusValue(snapshot.controlTempDeciC),
           celsiusValue(snapshot.tempSetpointDeciC), celsiusValue(snapshot.tempErrorDeciC),
           static_cast<unsigned>(snapshot.lampPwm), static_cast<unsigned long>(snapshot.holdWallSeconds),
           static_cast<unsigned long>(snapshot.holdQualifiedSeconds), snapshot.qualified ? 1U : 0U,
           celsiusValue(snapshot.detectedPlateauDeciC));
}

static uint16_t nextSequence(uint16_t &counter) {
  ++counter;
  if (!counter) ++counter;
  return counter;
}

static void uploadCalibration(const ptkit::CalibrationResultPacket &result) {
  char line[128];
  const float bare = static_cast<float>(result.bareDeciLux) / 10.0f;
  const float taped = static_cast<float>(result.tapedDeciLux) / 10.0f;
  const float factor = static_cast<float>(result.attenuationPermille) / 1000.0f;
  const float maximum = static_cast<float>(result.maxDeciLux) / 10.0f;
  if (result.phase == 1) snprintf(line, sizeof(line), "CALBARE:%.1f", bare);
  else if (result.phase == 2) snprintf(line, sizeof(line), "CALTAPE:%.1f:%.3f", taped, factor);
  else snprintf(line, sizeof(line), "CALRESULT:%.1f,%.1f,%.3f,%.1f", bare, taped, factor, maximum);
  enqueueUpload(line);
  if (result.phase == 3) {
    snprintf(line, sizeof(line), "MAXLUX:%.1f", maximum);
    enqueueUpload(line);
  }
}

void experimentControlTask(void *) {
  ptkit::ExperimentController controller;
  ptkit::SensorPacket latestSensor;
  memset(&latestSensor, 0, sizeof(latestSensor));
  latestSensor.irDeciC = latestSensor.tcDeciC = ptkit::INVALID_DECI_C;
  bool haveSensor = false;
  bool armAwaitingAck = false;
  bool armConfirmed = false;
  uint16_t sequenceCounter = 1;
  uint16_t armSequence = 0;
  uint16_t calibrationSequence = 0;
  uint8_t calibrationPhase = 0;
  bool calibrationAwaitingAck = false;
  unsigned long lastArmSendMs = 0;
  unsigned long lastCalibrationSendMs = 0;
  unsigned long lastOutputSendMs = 0;
  uint16_t lastOutputSequence = 0;
  ptkit::ControlSnapshot snapshot;
  memset(&snapshot, 0, sizeof(snapshot));
  snapshot.kind = ptkit::COMMAND_NONE;
  snapshot.stateCode = ptkit::STATE_IDLE;
  snapshot.controlTempDeciC = snapshot.tempSetpointDeciC = snapshot.tempErrorDeciC = snapshot.detectedPlateauDeciC = ptkit::INVALID_DECI_C;

  for (;;) {
    const unsigned long now = millis();
    UnoEvent event;
    while (xQueueReceive(eventQueue, &event, 0) == pdPASS) {
      if (event.type == UNO_EVENT_ACK) {
        debugLog("[control] ACK seq=%u code=%u expected_arm=%u expected_cal=%u",
                 static_cast<unsigned>(event.ack.sequence), static_cast<unsigned>(event.ack.code),
                 static_cast<unsigned>(armSequence), static_cast<unsigned>(calibrationSequence));
        if (event.ack.sequence == armSequence && (event.ack.code == 0 || event.ack.code == 1)) {
          armAwaitingAck = false;
          armConfirmed = true;
          debugLog("[control] ARM_CONFIRMED seq=%u", static_cast<unsigned>(armSequence));
        }
        if (event.ack.sequence == calibrationSequence && (event.ack.code == 0 || event.ack.code == 1)) {
          calibrationAwaitingAck = false;
          debugLog("[control] CAL_CONFIRMED seq=%u", static_cast<unsigned>(calibrationSequence));
        }
        if (controller.linkPaused() && event.ack.sequence == lastOutputSequence && event.ack.code == 0) {
          controller.resumeLink(now);
          debugLog("[control] LINK_RESUMED output_seq=%u", static_cast<unsigned>(lastOutputSequence));
        }
      } else if (event.type == UNO_EVENT_LINK_PAUSED) {
        if (controller.active()) {
          controller.pauseLink(now, event.linkPause.lampPwm, event.linkPause.fanPwm);
          snapshot.lampPwm = event.linkPause.lampPwm;
          snapshot.fanPwm = event.linkPause.fanPwm;
          lastOutputSendMs = 0;
          debugLog("[control] LINK_PAUSED held_lamp=%u held_fan=%u last_output_seq=%u",
                   static_cast<unsigned>(event.linkPause.lampPwm), static_cast<unsigned>(event.linkPause.fanPwm),
                   static_cast<unsigned>(event.linkPause.lastOutputSequence));
        }
      } else if (event.type == UNO_EVENT_FAULT) {
        debugLog("[control] UNO_FAULT fault=%u", static_cast<unsigned>(event.fault));
        if (controller.stateCode() != ptkit::STATE_IDLE) controller.abortExternal(event.fault);
        armAwaitingAck = false;
        armConfirmed = false;
      } else if (event.type == UNO_EVENT_CALIBRATION) {
        debugLog("[control] CAL_RESULT received phase=%u", static_cast<unsigned>(event.calibration.phase));
        uploadCalibration(event.calibration);
        calibrationPhase = 0;
        calibrationAwaitingAck = false;
      }
    }

    CommandPacket incoming;
    while (xQueueReceive(commandQueue, &incoming, 0) == pdPASS) {
      if (!strcmp(incoming.command, "CAL_BARE") || !strcmp(incoming.command, "CAL_TAPE") || !strcmp(incoming.command, "CAL_FULL")) {
        debugLog("[control] CAL_COMMAND=%s", incoming.command);
        controller.stop();
        sendFrameStop(nextSequence(sequenceCounter));
        armAwaitingAck = false;
        armConfirmed = false;
        calibrationPhase = !strcmp(incoming.command, "CAL_BARE") ? 1 : (!strcmp(incoming.command, "CAL_TAPE") ? 2 : 3);
        calibrationSequence = nextSequence(sequenceCounter);
        calibrationAwaitingAck = true;
        lastCalibrationSendMs = 0;
        continue;
      }
      debugLog("[control] COMMAND_RECEIVED=%s", incoming.command);
      ptkit::BackendCommand command;
      if (!ptkit::parseBackendCommand(incoming.command, command)) {
        debugLog("[control] REJECT malformed_command=%s", incoming.command);
        continue;
      }
      if (command.kind == ptkit::COMMAND_STOP) {
        debugLog("[control] STOP dispatch");
        controller.stop();
        sendFrameStop(nextSequence(sequenceCounter));
        armAwaitingAck = false;
        armConfirmed = false;
        calibrationAwaitingAck = false;
        calibrationPhase = 0;
        continue;
      }
      if (!haveSensor || !controller.start(command, now, toSample(latestSensor))) {
        debugLog("[control] DEFER command sensor_available=%d", haveSensor ? 1 : 0);
        continue;
      }
      debugLog("[control] START kind=%u", static_cast<unsigned>(command.kind));
      calibrationAwaitingAck = false;
      calibrationPhase = 0;
      armSequence = nextSequence(sequenceCounter);
      armAwaitingAck = true;
      armConfirmed = false;
      lastArmSendMs = 0;
      lastOutputSendMs = 0;
      lastOutputSequence = 0;
      snapshot = controller.step(now, toSample(latestSensor));
    }

    ptkit::SensorPacket receivedSensor;
    if (xQueueReceive(sensorQueue, &receivedSensor, 0) == pdPASS) {
      latestSensor = receivedSensor;
      haveSensor = true;
      debugLog("[control] SENSOR_UPDATE ir=%ld tc=%ld lux=%lu flags=%u",
               static_cast<long>(latestSensor.irDeciC), static_cast<long>(latestSensor.tcDeciC),
               static_cast<unsigned long>(latestSensor.lux), static_cast<unsigned>(latestSensor.flags));
      if (controller.stateCode() != ptkit::STATE_IDLE) snapshot = controller.step(now, toSample(latestSensor));
      else {
        memset(&snapshot, 0, sizeof(snapshot));
        snapshot.kind = ptkit::COMMAND_NONE;
        snapshot.stateCode = calibrationPhase ? (calibrationPhase == 1 ? ptkit::STATE_CAL_BARE : calibrationPhase == 2 ? ptkit::STATE_CAL_TAPE : ptkit::STATE_CAL_FULL) : ptkit::STATE_IDLE;
        snapshot.controlTempDeciC = snapshot.tempSetpointDeciC = snapshot.tempErrorDeciC = snapshot.detectedPlateauDeciC = ptkit::INVALID_DECI_C;
      }
      char telemetry[192];
      buildTelemetry(telemetry, sizeof(telemetry), latestSensor, snapshot, 255, controller.logIntervalSeconds());
      debugLog("[control] TELEMETRY_BUILT state=%u len=%u", static_cast<unsigned>(snapshot.stateCode), static_cast<unsigned>(strlen(telemetry)));
      enqueueUpload(telemetry);
      if (snapshot.stateCode == ptkit::STATE_DONE || snapshot.stateCode == ptkit::STATE_ABORTED) {
        sendFrameStop(nextSequence(sequenceCounter));
        controller.reset();
        armAwaitingAck = false;
        armConfirmed = false;
      }
    }

    if (armAwaitingAck && now - lastArmSendMs >= ARM_RETRY_MS) {
      if (controller.stateCode() != ptkit::STATE_IDLE) {
        debugLog("[control] ARM_SEND seq=%u max_temp_deci_c=%d", static_cast<unsigned>(armSequence), controller.command().maxTempDeciC);
        sendFrameArm(armSequence, static_cast<uint16_t>(controller.command().maxTempDeciC));
      }
      lastArmSendMs = now;
    }
    if (calibrationAwaitingAck && now - lastCalibrationSendMs >= CAL_RETRY_MS) {
      debugLog("[control] CAL_SEND seq=%u phase=%u", static_cast<unsigned>(calibrationSequence), static_cast<unsigned>(calibrationPhase));
      sendFrameCalibration(calibrationSequence, calibrationPhase);
      lastCalibrationSendMs = now;
    }
    if (armConfirmed && controller.active() && now - lastOutputSendMs >= CONTROL_HEARTBEAT_MS) {
      char frame[ptkit::FRAME_MAX_CHARS];
      const uint16_t sequence = nextSequence(sequenceCounter);
      if (ptkit::frameOutput(frame, sizeof(frame), sequence, snapshot.lampPwm, snapshot.fanPwm,
                             CONTROL_TTL_MS, snapshot.stateCode)) {
        debugLog("[control] OUTPUT_SEND seq=%u lamp=%u fan=%u ttl=%u state=%u",
                 static_cast<unsigned>(sequence), static_cast<unsigned>(snapshot.lampPwm),
                 static_cast<unsigned>(snapshot.fanPwm), static_cast<unsigned>(CONTROL_TTL_MS),
                 static_cast<unsigned>(snapshot.stateCode));
        if (enqueueUartFrame(frame)) lastOutputSequence = sequence;
      }
      lastOutputSendMs = now;
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void setup() {
  Serial.begin(115200);
  delay(250);
  debugLog("[boot] FIRMWARE=%s watchdog_disabled=%d", PTKIT_FIRMWARE_TAG, PTKIT_DISABLE_WATCHDOG ? 1 : 0);
#if PTKIT_DISABLE_WATCHDOG
  // Print the identity before any WDT API call so the monitor proves which
  // firmware actually booted, even if deinitialization reports an error.
  Serial.printf("[%10lu ms] [boot] FIRMWARE=%s TEMP watchdog_disable_requested=1",
                static_cast<unsigned long>(millis()), PTKIT_FIRMWARE_TAG);
  Serial.println();
  // The ESP-IDF deinitializer owns idle-task cleanup. Do not delete idle tasks
  // manually first: deinit() unsubscribes them once and a second delete triggers
  // ESP_ERROR_CHECK/abort with ESP_ERR_NOT_FOUND.
  disableLoopWDT();
  const esp_err_t twdtDeinit = esp_task_wdt_deinit();
  debugLog("[boot] TEMP watchdog_disabled twdt_deinit=%d", static_cast<int>(twdtDeinit));
#endif
  debugLog("[boot] PT-KIT ESP32 debug firmware start reset_reason=%d cpu_mhz=%u free_heap=%u",
           static_cast<int>(esp_reset_reason()), static_cast<unsigned>(getCpuFrequencyMhz()),
           static_cast<unsigned>(ESP.getFreeHeap()));
  debugLog("[boot] UART2 rx_gpio=%d tx_gpio=%d baud=%u", RXD2, TXD2, static_cast<unsigned>(UART_BAUD));
  // Keep the ESP32 brownout detector enabled. A power disturbance must reset the
  // network MCU rather than leave partially initialized control state running.
  Serial2.setRxBufferSize(2048);
  Serial2.begin(UART_BAUD, SERIAL_8N1, RXD2, TXD2);

  uploadQueue = xQueueCreate(80, sizeof(UploadPacket));
  commandQueue = xQueueCreate(8, sizeof(CommandPacket));
  uartTxQueue = xQueueCreate(24, sizeof(UartTxPacket));
  sensorQueue = xQueueCreate(1, sizeof(ptkit::SensorPacket));
  eventQueue = xQueueCreate(16, sizeof(UnoEvent));
  httpMutex = xSemaphoreCreateMutex();
  debugLog("[boot] queues upload=%d command=%d uart_tx=%d sensor=%d event=%d http_mutex=%d heap=%u",
           uploadQueue ? 1 : 0, commandQueue ? 1 : 0, uartTxQueue ? 1 : 0,
           sensorQueue ? 1 : 0, eventQueue ? 1 : 0, httpMutex ? 1 : 0, static_cast<unsigned>(ESP.getFreeHeap()));
  if (!uploadQueue || !commandQueue || !uartTxQueue || !sensorQueue || !eventQueue || !httpMutex) {
    debugLog("[boot] FATAL queue allocation failed");
    return;
  }

  WiFi.onEvent(onWiFiEvent);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  debugStatus("before_initial_begin");
  beginEnterpriseWifi();

  // The upload task lazily creates one insecure persistent telemetry client,
  // matching the proven standalone uploader. Command polling creates a
  // temporary client for each poll.
  xTaskCreatePinnedToCore(wifiSupervisorTask, "WifiSupervisor", 4096, NULL, 3, NULL, NETWORK_CORE);
  xTaskCreatePinnedToCore(backendCommandTask, "BackendCommands", 8192, NULL, 2, NULL, NETWORK_CORE);
  xTaskCreatePinnedToCore(backendUploadTask, "BackendUpload", 12288, NULL, 1, NULL, NETWORK_CORE);
  xTaskCreatePinnedToCore(uartTransportTask, "UartTransport", 4096, NULL, 4, NULL, CONTROL_CORE);
  xTaskCreatePinnedToCore(experimentControlTask, "ExperimentControl", 8192, NULL, 3, NULL, CONTROL_CORE);
  debugLog("[boot] tasks_started network_core=%u control_core=%u", static_cast<unsigned>(NETWORK_CORE), static_cast<unsigned>(CONTROL_CORE));
}

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}
