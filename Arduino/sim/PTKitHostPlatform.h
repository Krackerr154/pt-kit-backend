#ifndef PTKIT_HOST_PLATFORM_H
#define PTKIT_HOST_PLATFORM_H

#include "../PTKitPlatform.h"

#include <math.h>
#include <stdint.h>
#include <string>

class PTKitHostPlatform : public PTKitPlatform {
 public:
  PTKitHostPlatform()
      : lampPwm(0), fanPwm(0), blockingDelayMs(0),
        confirmationTemp(NAN), persistedMaxLux(10000.0f), persistedAttenuation(1.0f),
        saveCount(0), nowMs_(0) {}

  uint32_t nowMs() const { return nowMs_; }
  void setNowMs(uint32_t value) { nowMs_ = value; }
  void advanceMs(uint32_t amount) { nowMs_ += amount; }
  void setLampPwm(uint8_t pwm) { lampPwm = pwm; }
  void setFanPwm(uint8_t pwm) { fanPwm = pwm; }
  void writeUart(const char *bytes, size_t length) { output.append(bytes, length); }
  void clearDisplay() { displayLine1.clear(); displayLine2.clear(); }
  void showDisplay(const char *line1, const char *line2) {
    displayLine1 = line1 ? line1 : "";
    displayLine2 = line2 ? line2 : "";
  }
  void blockingDelay(uint32_t milliseconds) {
    blockingDelayMs += milliseconds;
    nowMs_ += milliseconds;
  }
  float confirmThermocoupleC() { return confirmationTemp; }
  void loadCalibration(float &maxLux, float &attenuation) {
    maxLux = persistedMaxLux;
    attenuation = persistedAttenuation;
  }
  void saveCalibration(float maxLux, float attenuation) {
    persistedMaxLux = maxLux;
    persistedAttenuation = attenuation;
    ++saveCount;
  }
  std::string lastLine() const {
    if (output.empty()) return std::string();
    size_t end = output.size();
    if (end && output[end - 1] == '\n') --end;
    size_t begin = output.rfind('\n', end ? end - 1 : 0);
    if (begin == std::string::npos) begin = 0;
    else ++begin;
    return output.substr(begin, output.size() - begin);
  }
  void clearOutput() { output.clear(); }

  uint8_t lampPwm;
  uint8_t fanPwm;
  uint64_t blockingDelayMs;
  float confirmationTemp;
  float persistedMaxLux;
  float persistedAttenuation;
  unsigned saveCount;
  std::string output;
  std::string displayLine1;
  std::string displayLine2;

 private:
  uint32_t nowMs_;
};

#endif
