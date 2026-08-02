# PT-Kit Simulator Calibration Protocol

> **Status:** DRAFT — No acceptance thresholds are defined until run-to-run repeatability data exists.

## Purpose

This document defines the procedure for collecting real PT-Kit step-response data
and using it to calibrate the simulator's two-node thermal plant model. The goal is
to move the plant profile from `UNCALIBRATED_SYNTHETIC` to `CALIBRATED` status.

## Scope

The calibration protocol covers:

- Lamp gain and response time identification
- Surface and bulk thermal capacity estimation
- Surface–bulk thermal coupling (conductance)
- Passive heat loss to ambient
- Fan-dependent forced-convection heat loss
- IR sensor lag, bias, and noise characterization
- TC sensor lag, bias, and noise characterization
- Lux sensor transfer function and noise characterization

## Prerequisites

- Physical PT-Kit instrument in working condition
- Arduino firmware matching the version documented in `docs/simulator-contract.md`
- ESP32 bridge connected and communicating with the backend
- Backend server running with data ingestion operational
- Stable ambient environment (no drafts, no direct sunlight on the apparatus)
- At least 30 minutes of thermal equilibrium before starting measurements

---

## Phase A: Run-to-Run Repeatability Assessment

**This phase MUST be completed before any fitting or threshold definition.**

### A.1 Purpose

Quantify the natural variability of the physical system under identical conditions.
Acceptance thresholds for the calibrated model will be derived from this data
(e.g., thresholds set at 2× the observed run-to-run standard deviation).

### A.2 Procedure

1. **Equilibrate** the PT-Kit for at least 30 minutes with lamp OFF, fan OFF.
   Record ambient temperature (IR and TC should agree within 1°C).

2. **Select a reference protocol:** Use a fixed-temperature (ISO1) command with
   moderate parameters:
   ```
   ISO1:50:120:2:5:80:10:IR:2
   ```
   (Target 50°C, hold 120s, tolerance ±2°C, qualification 5s, max temp 80°C,
   interval 10s, IR sensor control, ramp rate 2°C/min)

3. **Run the reference protocol N ≥ 5 times** with at least 15 minutes of cooling
   between runs (until both sensors read within 2°C of ambient).

4. **Record for each run:**
   - Full telemetry stream (timestamp, IR, TC, lux, state, lamp PWM, fan PWM)
   - Ambient temperature at start and end
   - Time of day (to detect drift)
   - Any anomalies or interruptions

5. **Compute repeatability metrics:**
   - For each run, extract:
     - Heating slope (°C/min) from 30°C to 45°C (linear fit)
     - Cooling slope (°C/min) from 45°C to 35°C after lamp off
     - Time-to-threshold: time from lamp ON to first IR reading ≥ 40°C
     - Steady-state temperature: mean of last 60s of hold phase
     - IR–TC lag: cross-correlation delay between IR and TC during heating
     - Plateau temperature: mean temperature during PLATEAU_CONFIRM (if applicable)
   - Compute mean and standard deviation across N runs for each metric
   - Report as `repeatability_report.json`

6. **Acceptance gate:** If any metric has coefficient of variation (CV) > 15%,
   investigate environmental stability before proceeding. High variability may
   indicate drafts, unstable power supply, or sensor issues.

### A.3 Output

```
tests/fixtures/simulator/calibration/repeatability/
├── run_001.csv
├── run_002.csv
├── ...
├── run_00N.csv
└── repeatability_report.json
```

`repeatability_report.json` schema:
```json
{
  "date": "ISO-8601",
  "n_runs": 5,
  "ambient_temp_c": {"mean": 25.1, "std": 0.3},
  "metrics": {
    "heating_slope_c_per_min": {"mean": 4.2, "std": 0.15, "cv_pct": 3.6},
    "cooling_slope_c_per_min": {"mean": -2.1, "std": 0.08, "cv_pct": 3.8},
    "time_to_40c_s": {"mean": 185.0, "std": 4.2, "cv_pct": 2.3},
    "steady_state_temp_c": {"mean": 50.1, "std": 0.3, "cv_pct": 0.6},
    "ir_tc_lag_s": {"mean": 2.1, "std": 0.4, "cv_pct": 19.0},
    "plateau_temp_c": {"mean": null, "std": null, "cv_pct": null}
  },
  "pass": true
}
```

---

## Phase B: Step-Response Data Collection

### B.1 Lamp Step Responses (Heating)

Collect step responses at multiple lamp PWM levels with fan OFF:

| Test ID | Lamp PWM | Fan PWM | Duration | Notes |
|---------|----------|---------|----------|-------|
| LAMP_064 | 64 | 0 | 600s | Low power |
| LAMP_128 | 128 | 0 | 600s | Medium power |
| LAMP_192 | 192 | 0 | 600s | High power |
| LAMP_255 | 255 | 0 | 600s | Maximum power |

**Procedure for each test:**

1. Ensure thermal equilibrium (both sensors within 1°C of ambient for 5 minutes).
2. Record 30s of baseline (lamp OFF, fan OFF).
3. Apply lamp step (set PWM via direct actuator command or ISO mode).
4. Record for the specified duration.
5. Turn lamp OFF.
6. Record 300s of cooling (natural convection).
7. Save raw telemetry as CSV.

**Repeat each test N ≥ 3 times** for noise estimation.

### B.2 Fan Step Responses (Cooling)

Collect cooling responses at multiple fan PWM levels after heating to a standard
temperature:

| Test ID | Lamp PWM (heat) | Fan PWM | Duration | Notes |
|---------|-----------------|---------|----------|-------|
| FAN_064 | 255 (pre-heat) | 64 | 300s | Low airflow |
| FAN_128 | 255 (pre-heat) | 128 | 300s | Medium airflow |
| FAN_192 | 255 (pre-heat) | 192 | 300s | High airflow |
| FAN_255 | 255 (pre-heat) | 255 | 300s | Maximum airflow |

**Procedure for each test:**

1. Heat with lamp PWM=255 until surface reaches 60°C (±2°C).
2. Turn lamp OFF, simultaneously apply fan step.
3. Record for the specified duration.
4. Turn fan OFF.
5. Allow to cool to ambient.
6. Save raw telemetry as CSV.

**Repeat each test N ≥ 3 times.**

### B.3 Lux Sensor Characterization

| Test ID | Lamp PWM | Fan PWM | Duration | Notes |
|---------|----------|---------|----------|-------|
| LUX_SWEEP | 0→255 (ramp) | 0 | 120s | Linear ramp up |
| LUX_STEP | 255 | 0 | 60s | Step to max |
| LUX_DECAY | 255→0 | 0 | 60s | Step to zero |

### B.4 Sensor Lag and Bias

- **Lag:** Estimated from step-response rise time (10%–90%) for IR and TC.
- **Bias:** Estimated from equilibrium readings vs. a reference thermometer
  (if available) or from IR–TC agreement at steady state.
- **Noise:** Estimated from baseline (lamp OFF) standard deviation over 60s.

---

## Phase C: Parameter Identification (Fitting)

### C.1 Fitting Procedure

Run the fitting script:
```bash
python scripts/fit_simulator_plant.py \
    --data-dir tests/fixtures/simulator/calibration/step_responses/ \
    --repeatability tests/fixtures/simulator/calibration/repeatability/repeatability_report.json \
    --output app/simulator/profiles/calibrated.json \
    --seed 42
```

The script performs:

1. **Load and validate** step-response data files.
2. **Verify repeatability** report exists and passes the CV gate.
3. **Fit lamp model:** lamp_max_power_w, lamp_response_time_s, lamp_max_lux
   from LUX_STEP and LAMP_* heating curves.
4. **Fit thermal model:** surface_capacity, bulk_capacity, conductances
   from heating and cooling curves (least-squares or optimization).
5. **Fit fan model:** fan_max_conductance_w_per_k, fan_response_time_s
   from FAN_* cooling curves.
6. **Fit sensor models:** response time, bias, noise from step edges and baseline.
7. **Compute fit metrics** against held-out data (if available) or
   leave-one-out cross-validation across repeated runs.
8. **Compare against acceptance thresholds** derived from repeatability data.
9. **Write calibrated profile** with `validation_status: CALIBRATED` only if
   all gates pass; otherwise write with `validation_status: CALIBRATION_FAILED`.

### C.2 Acceptance Thresholds

**Thresholds are NOT predefined.** They are derived from Phase A repeatability:

```
threshold_X = k * std_X
```

where `std_X` is the run-to-run standard deviation of metric X, and `k` is a
multiplier (default k=2, configurable). The model must achieve errors within
the natural variability of the physical system.

Metrics subject to thresholds:

| Metric | Definition | Threshold basis |
|--------|-----------|-----------------|
| IR RMSE | Root-mean-square error of simulated vs. measured IR (°C) | k × IR noise std |
| TC RMSE | Root-mean-square error of simulated vs. measured TC (°C) | k × TC noise std |
| Heating slope error | |simulated - measured| heating rate (°C/min) | k × heating_slope std |
| Cooling slope error | |simulated - measured| cooling rate (°C/min) | k × cooling_slope std |
| Time-to-threshold error | |simulated - measured| time to reach 40°C (s) | k × time_to_40c std |
| IR–TC lag error | |simulated - measured| cross-correlation delay (s) | k × ir_tc_lag std |
| Steady-state error | |simulated - measured| mean hold temperature (°C) | k × steady_state std |
| Plateau temp error | |simulated - measured| plateau temperature (°C) | k × plateau std |

### C.3 Profile Output

The calibrated profile follows the same schema as `synthetic-default.json`:

```json
{
  "profile_id": "calibrated-v1",
  "model_version": "2.0.0",
  "validation_status": "CALIBRATED",
  "validity_domain": {
    "ambient_temp_c": [20, 30],
    "lamp_pwm_range": [0, 255],
    "fan_pwm_range": [0, 255],
    "max_duration_s": 3600
  },
  "parameters": { "...": "with units" },
  "source_dataset": "tests/fixtures/simulator/calibration/",
  "fit_metrics": {
    "ir_rmse_c": 0.42,
    "tc_rmse_c": 0.51,
    "heating_slope_error_c_per_min": 0.12,
    "cooling_slope_error_c_per_min": 0.08,
    "time_to_threshold_error_s": 3.1,
    "ir_tc_lag_error_s": 0.3,
    "steady_state_error_c": 0.2,
    "plateau_temp_error_c": null
  },
  "acceptance_thresholds": {
    "derived_from": "repeatability_report.json",
    "multiplier_k": 2,
    "...": "computed values"
  },
  "calibration_date": "ISO-8601",
  "calibration_operator": "name",
  "notes": ""
}
```

---

## Phase D: Validation and Sign-Off

### D.1 Independent Validation

After fitting, run at least 2 validation protocols NOT used in fitting:

1. A normal cyclic experiment (SET command) — compare full telemetry.
2. A natural plateau experiment (PLAT1 command) — compare plateau detection.

### D.2 Documentation

Record in the profile:
- Date of calibration
- Operator name
- Firmware version
- Ambient conditions
- Any anomalies

### D.3 Recalibration Triggers

Recalibrate when:
- Physical hardware changes (new lamp, new sensor, new sample holder)
- Ambient environment changes significantly (new room, seasonal shift > 5°C)
- Firmware changes affect actuator timing or sensor reading
- More than 6 months since last calibration

---

## Data Format

### Raw Telemetry CSV

Each step-response file uses the standard PT-Kit telemetry format:

```csv
timestamp_ms,ir_temp_c,tc_temp_c,lux,state_code,lamp_pwm,fan_pwm
0,25.1,25.0,3,0,0,0
1000,25.1,25.0,3,0,0,0
...
```

Extended 17-field format is also accepted; the fitting script extracts the
relevant columns by index.

### File Naming Convention

```
{TEST_ID}_{run_number}_{YYYYMMDD_HHMMSS}.csv
```

Example: `LAMP_128_run001_20250801_143022.csv`

---

## Safety Notes

- Maximum surface temperature during calibration: 80°C (do not exceed).
- Allow the lamp to cool before handling the apparatus.
- Ensure adequate ventilation during extended heating.
- Do not leave the apparatus unattended during lamp-on phases.

---

## Revision History

| Date | Author | Change |
|------|--------|--------|
| 2025-08-01 | Simulator Team | Initial draft — protocol structure defined, no thresholds |
