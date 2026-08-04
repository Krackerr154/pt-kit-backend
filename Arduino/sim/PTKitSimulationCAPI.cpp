#include "PTKitSimulationCAPI.h"

#include "PTKitHostPlatform.h"
#include "../PTKitController.h"

#include <algorithm>
#include <new>
#include <string.h>

struct PTKitSimHandle {
  PTKitHostPlatform platform;
  PTKitController controller;
  PTKitRawSensors raw;
  size_t outputCursor;

  PTKitSimHandle() : controller(platform), outputCursor(0) {
    raw.tempIrC = raw.tempTcC = raw.lux = 0;
    controller.begin();
  }
};

extern "C" {

PTKitSimHandle *ptkit_sim_create(void) {
  try { return new (std::nothrow) PTKitSimHandle(); }
  catch (...) { return 0; }
}

void ptkit_sim_destroy(PTKitSimHandle *handle) {
  try { delete handle; } catch (...) {}
}

void ptkit_sim_set_time(PTKitSimHandle *handle, uint32_t now_ms) {
  if (!handle) return;
  try { handle->platform.setNowMs(now_ms); } catch (...) {}
}

void ptkit_sim_set_raw_sensors(PTKitSimHandle *handle, float ir_c, float tc_c, float lux) {
  if (!handle) return;
  try {
    handle->raw.tempIrC = ir_c;
    handle->raw.tempTcC = tc_c;
    handle->raw.lux = lux;
    handle->platform.confirmationTemp = tc_c;
  } catch (...) {}
}

int ptkit_sim_send_command(PTKitSimHandle *handle, const char *bytes, size_t length) {
  if (!handle || (!bytes && length)) return 0;
  try { return handle->controller.command(bytes, length) ? 1 : 0; }
  catch (...) { return 0; }
}

int ptkit_sim_step(PTKitSimHandle *handle) {
  if (!handle) return 0;
  try { return handle->controller.step(handle->raw) ? 1 : 0; }
  catch (...) { return 0; }
}

int ptkit_sim_get_snapshot(const PTKitSimHandle *handle, PTKitSimSnapshot *out) {
  if (!handle || !out) return 0;
  try {
    PTKitSnapshot value = handle->controller.snapshot();
    out->now_ms = value.nowMs;
    out->total_seconds = value.totalSeconds;
    out->state_seconds = value.stateSeconds;
    out->hold_elapsed_seconds = value.holdElapsedSeconds;
    out->hold_qualified_seconds = value.holdQualifiedSeconds;
    out->cycle = value.cycle;
    out->state = value.state;
    out->mode = value.mode;
    out->illumination_mode = value.illuminationMode;
    out->temp_ir_c = value.tempIrC;
    out->temp_tc_c = value.tempTcC;
    out->smoothed_lux = value.smoothedLux;
    out->control_temp_c = value.controlTempC;
    out->temp_setpoint_c = value.tempSetpointC;
    out->temp_error_c = value.tempErrorC;
    out->detected_plateau_temp_c = value.detectedPlateauTempC;
    out->lamp_pwm = value.lampPwm;
    out->fan_pwm = value.fanPwm;
    out->temp_ir_valid = value.tempIrValid;
    out->temp_tc_valid = value.tempTcValid;
    out->control_temp_valid = value.controlTempValid;
    out->qualified = value.qualified;
    return 1;
  } catch (...) { return 0; }
}

size_t ptkit_sim_output_size(const PTKitSimHandle *handle) {
  if (!handle) return 0;
  try {
    if (handle->outputCursor >= handle->platform.output.size()) return 0;
    return handle->platform.output.size() - handle->outputCursor;
  } catch (...) { return 0; }
}

size_t ptkit_sim_read_output(PTKitSimHandle *handle, char *buffer, size_t length) {
  if (!handle || (!buffer && length)) return 0;
  try {
    size_t available = ptkit_sim_output_size(handle);
    size_t count = std::min(available, length);
    if (count) memcpy(buffer, handle->platform.output.data() + handle->outputCursor, count);
    handle->outputCursor += count;
    if (handle->outputCursor == handle->platform.output.size()) {
      handle->platform.output.clear();
      handle->outputCursor = 0;
    }
    return count;
  } catch (...) { return 0; }
}

void ptkit_sim_clear_output(PTKitSimHandle *handle) {
  if (!handle) return;
  try {
    handle->platform.clearOutput();
    handle->outputCursor = 0;
  } catch (...) {}
}

}  // extern "C"
