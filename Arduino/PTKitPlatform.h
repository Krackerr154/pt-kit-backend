#ifndef PTKIT_PLATFORM_H
#define PTKIT_PLATFORM_H

#include <stddef.h>
#include <stdint.h>

class PTKitPlatform {
 public:
  virtual ~PTKitPlatform() {}
  virtual uint32_t nowMs() const = 0;
  virtual void setLampPwm(uint8_t pwm) = 0;
  virtual void setFanPwm(uint8_t pwm) = 0;
  virtual void writeUart(const char *bytes, size_t length) = 0;
  virtual void clearDisplay() = 0;
  virtual void showDisplay(const char *line1, const char *line2) = 0;
  virtual void blockingDelay(uint32_t milliseconds) = 0;
  virtual float confirmThermocoupleC() = 0;
  virtual void loadCalibration(float &maxLux, float &attenuation) = 0;
  virtual void saveCalibration(float maxLux, float attenuation) = 0;
};

#endif
