#include "PTKitSimulationCAPI.h"

#include <stdio.h>

int main() {
  PTKitSimHandle *sim = ptkit_sim_create();
  if (!sim) {
    fprintf(stderr, "ptkit_sim_create failed\n");
    return 1;
  }

  ptkit_sim_set_time(sim, 1000U);
  ptkit_sim_set_raw_sensors(sim, 31.0f, 31.0f, 5000.0f);
  const char command[] = "SET:2:1:80:1:5000";
  if (!ptkit_sim_send_command(sim, command, sizeof(command) - 1U)) {
    fprintf(stderr, "command rejected\n");
    ptkit_sim_destroy(sim);
    return 1;
  }
  if (!ptkit_sim_step(sim)) {
    fprintf(stderr, "controller did not step\n");
    ptkit_sim_destroy(sim);
    return 1;
  }

  PTKitSimSnapshot snapshot = {};
  if (!ptkit_sim_get_snapshot(sim, &snapshot)) {
    fprintf(stderr, "snapshot unavailable\n");
    ptkit_sim_destroy(sim);
    return 1;
  }

  printf("state=%d mode=%d cycle=%ld lamp_pwm=%u fan_pwm=%u\n",
         snapshot.state, snapshot.mode, (long)snapshot.cycle,
         (unsigned)snapshot.lamp_pwm, (unsigned)snapshot.fan_pwm);

  ptkit_sim_destroy(sim);
  return 0;
}
