#ifndef PTKIT_SIMULATION_CAPI_H
#define PTKIT_SIMULATION_CAPI_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct PTKitSimHandle PTKitSimHandle;

typedef struct PTKitSimSnapshot {
  uint32_t now_ms;
  uint32_t total_seconds;
  uint32_t state_seconds;
  uint32_t hold_elapsed_seconds;
  uint32_t hold_qualified_seconds;
  int32_t cycle;
  int32_t state;
  int32_t mode;
  int32_t illumination_mode;
  float temp_ir_c;
  float temp_tc_c;
  float smoothed_lux;
  float control_temp_c;
  float temp_setpoint_c;
  float temp_error_c;
  float detected_plateau_temp_c;
  uint8_t lamp_pwm;
  uint8_t fan_pwm;
  uint8_t temp_ir_valid;
  uint8_t temp_tc_valid;
  uint8_t control_temp_valid;
  uint8_t qualified;
} PTKitSimSnapshot;

PTKitSimHandle *ptkit_sim_create(void);
void ptkit_sim_destroy(PTKitSimHandle *handle);
void ptkit_sim_set_time(PTKitSimHandle *handle, uint32_t now_ms);
void ptkit_sim_set_raw_sensors(PTKitSimHandle *handle, float ir_c, float tc_c, float lux);
int ptkit_sim_send_command(PTKitSimHandle *handle, const char *bytes, size_t length);
int ptkit_sim_step(PTKitSimHandle *handle);
int ptkit_sim_get_snapshot(const PTKitSimHandle *handle, PTKitSimSnapshot *out_snapshot);
size_t ptkit_sim_output_size(const PTKitSimHandle *handle);
size_t ptkit_sim_read_output(PTKitSimHandle *handle, char *buffer, size_t buffer_length);
void ptkit_sim_clear_output(PTKitSimHandle *handle);

#ifdef __cplusplus
}
#endif
#endif
