# PT-Kit Backend API Reference

> Authoritative REST reference for the production FastAPI backend (`app/main.py`, `app/protocol.py`).
> Base URL (LAN): `http://<host>:8000` — publicly proxied via Nginx Proxy Manager over WireGuard.
> All responses are JSON unless noted. Error responses follow FastAPI conventions (`{"detail": ...}`, HTTP 400/404/422/503).

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Flow & Command Queue Model](#2-data-flow--command-queue-model)
3. [Global Server State](#3-global-server-state)
4. [Page Routes](#4-page-routes)
5. [Experiment Lifecycle API](#5-experiment-lifecycle-api)
6. [Live Data API (ESP32-facing)](#6-live-data-api-esp32-facing)
7. [History & Export API](#7-history--export-api)
8. [Calibration & Configuration API](#8-calibration--configuration-api)
9. [Hardware Command Strings](#9-hardware-command-strings)
10. [Telemetry Wire Format](#10-telemetry-wire-format)
11. [State Code Map](#11-state-code-map)
12. [Database Schema](#12-database-schema)
13. [Database Status Lifecycle](#13-database-status-lifecycle)
14. [Server Memory Semantics (recent_sensors_cache)](#14-server-memory-semantics-recent_sensors_cache)
15. [Error Handling Summary](#15-error-handling-summary)

---

## 1. System Overview

| Layer | Component |
|---|---|
| Sensors | Arduino: IR temperature, thermocouple (TC) temperature, ambient light (Lux) |
| Transport | ESP32 (WiFi) — polls commands, POSTs CSV telemetry lines |
| Backend | Python + FastAPI + Uvicorn (port 8000) |
| Database | PostgreSQL 13 (port 5432), three tables |
| Frontend | Vanilla HTML/CSS/JS + Chart.js + jStat (`app/static/`) |
| Deployment | Docker Compose; exposed via WireGuard + Nginx Proxy Manager |

Environment variables: `DB_HOST` (default `db`), `POSTGRES_DB` (`ptkit_db`), `POSTGRES_USER` (`ptkit_user`), `POSTGRES_PASSWORD`.

## 2. Data Flow & Command Queue Model

The backend never opens a connection to the ESP32. Instead, a **single-slot command queue** (`pending_command`) is drained by the ESP32's polling loop:

```
Dashboard ──POST /api/start_experiment──▶ Backend
                                            │ sets pending_command = "SET:…" / "ISO1:…" / "PLAT1:…"
ESP32 ──GET /api/check_command───────────▶ drains pending_command (one-shot, then "IDLE")
ESP32 ──POST /api/insert_data (CSV)──────▶ Backend → deque cache (+ PostgreSQL if experiment active)
Dashboard ──GET /api/current_status──────▶ { active_experiment, recent_data (≤20 samples) }
```

Consequences:

- Commands are **fire-and-forget**: there is no acknowledgement path. `/api/check_command` returns the pending command exactly once, then `{"command":"IDLE"}`.
- Starting or calibrating **overwrites** any undelivered pending command.
- Live charts are fed from the **server deque cache**, not the database, during monitoring.

## 3. Global Server State

In-memory (not persisted, resets on process restart):

| Variable | Type | Semantics |
|---|---|---|
| `pending_command` | str \| None | One-slot command queue; drained by `/api/check_command` |
| `current_experiment_id` | int \| None | Active experiment; restored from DB (`status='WAITING'`) on startup |
| `recent_sensors_cache` | `deque(maxlen=20)` | Last 20 parsed telemetry rows for live monitoring; **cleared on start AND on stop** |
| `calibration_state` | dict | `{phase, bare_lux, taped_lux, factor}` + transient `last_cal_lux`/`last_cal_state` fallback keys |

Startup behavior (`@app.on_event("startup")`): creates/migrates all tables, then restores the most recent `WAITING` experiment into `current_experiment_id`. `COMPLETED`/`STOPPED`/`ABORTED` experiments are never restored.

## 4. Page Routes

| Method | Path | Response |
|---|---|---|
| GET | `/` | `app/static/index.html` (live monitoring dashboard) |
| GET | `/history` | `app/static/history.html` (archive/analysis view) |
| GET | `/static/*` | Static assets (`index.html`, `history.html`, `calibration.html`, `pt-stats.js`, …) |

## 5. Experiment Lifecycle API

### POST `/api/start_experiment`

Creates an experiment row (`status='WAITING'`), builds the mode-appropriate hardware command, clears the live cache, and queues the command.

**Request body — `ExperimentConfig`:**

| Field | Type | Default | Validation |
|---|---|---|---|
| `operator_name` | string | — | required |
| `sample_name` | string | — | required |
| `description` | string | `""` | — |
| `duration` | int (s) | 60 | 0 < v ≤ 4,294,967 |
| `cycles` | int | 5 | 0 < v ≤ 32,767 |
| `max_temp` | float (°C) | 80.0 | must exceed `target_temperature` in FIXED mode |
| `interval` | int (s) | 1 | 0 < v ≤ 32,767 |
| `target_lux` | float \| null | 38000.0 | finite ≥ 0 in TARGET_LUX mode; > 0 for NATURAL_PLATEAU |
| `illumination_mode` | enum | `TARGET_LUX` | `TARGET_LUX` \| `MAX_OUTPUT` \| `TEMPERATURE_CONTROLLED` |
| `mode` | enum | `NORMAL_CYCLIC` | `NORMAL_CYCLIC` \| `FIXED_TEMPERATURE` \| `NATURAL_PLATEAU` |
| `target_temperature` | float \| null | — | required, finite > 0 for FIXED_TEMPERATURE |
| `hold_duration_s` | int \| null | — | required for FIXED & PLATEAU |
| `temperature_tolerance` | float \| null | — | required for FIXED |
| `qualification_dwell_s` | int \| null | — | required for FIXED |
| `control_sensor` | string | `"IR"` | `"IR"` or `"TC"` |
| `ramp_rate` | float \| null | — | required for FIXED (°C/min) |
| `plateau_window_s` | int \| null | — | PLATEAU; ≤ 60 (firmware capacity) |
| `plateau_max_slope` | float \| null | — | PLATEAU (°C/min) |
| `plateau_max_range` | float \| null | — | PLATEAU (°C peak-to-peak) |
| `plateau_confirmation_s` | int \| null | — | PLATEAU |
| `plateau_max_discovery_s` | int \| null | — | PLATEAU; ≥ window; ≤ 6500 |
| `post_plateau_mode` | enum | `PASSIVE` | `PASSIVE` \| `REGULATED` |

Cross-field rules:

- `FIXED_TEMPERATURE` forces `illumination_mode=TEMPERATURE_CONTROLLED` and nulls `target_lux`.
- `TEMPERATURE_CONTROLLED` is rejected for any non-FIXED mode.
- `MAX_OUTPUT` nulls `target_lux` and is **incompatible with FIXED_TEMPERATURE** (HTTP 422).
- All mode-required numeric fields must be finite and > 0; hold/dwell/window/confirmation/discovery each ≤ 4,294,967.

**Response 200:**

```json
{"status": "success", "id": 42, "mode": "NORMAL_CYCLIC", "illumination_mode": "TARGET_LUX"}
```

**Errors:** 422 (validation), 503 (database unavailable).

Side effects: `recent_sensors_cache.clear()`, DB insert, `current_experiment_id = new id`, `pending_command = serialized command`.

### POST `/api/stop_experiment`

Queues `STOP`, clears the live cache, marks the active experiment `STOPPED` with `ended_at=NOW()`, clears `current_experiment_id`.

**Response 200 (always, even with no active experiment):**

```json
{"status": "stopped"}
```

> Frontend dependency: this endpoint never errors; the dashboard's stop flow relies on the unconditional success shape.

### GET `/api/current_status`

Live polling endpoint for the dashboard (~1 s cadence).

**Response 200:**

```json
{
  "active_experiment": { "id": 42, "sample_name": "…", "status": "WAITING", /* full experiments row or null */ },
  "recent_data": [ { "total_time": 12, "phase_time": 12, "cycle_num": 1, "state_code": 2,
                     "state_label": "HEATING", "ir_temp": 45.2, "tc_temp": 44.8, "current_lux": 37100.0,
                     "mode": "…", "control_temp": 45.0, "temp_setpoint": 80.0, "temp_error": 0.4,
                     "lamp_pwm": 128.0, "hold_wall_elapsed_s": 0, "hold_qualified_elapsed_s": 0,
                     "qualified": false, "detected_plateau_temp": null } ]
}
```

- `recent_data` is the **≤20-sample server deque**, newest last. IDLE-phase rows are included (pre-experiment monitoring).
- **Cleared on start and on stop** — after a stop, a fresh page load cannot restore the previous run's KPIs/charts from the server; retention is session-local in the browser (see `MOBILE_PHASE3_CONTRACT.md` requirement 5 scope note).

## 6. Live Data API (ESP32-facing)

### GET `/api/check_command`

Drains the one-slot command queue.

**Response 200:** `{"command": "SET:60:5:80:1:38000"}` or `{"command": "IDLE"}` when empty.

### POST `/api/insert_data`

Single ingestion point for **all** ESP32 traffic. Body: `{"csv_line": "<line>"}`.

**Side-band messages (handled before telemetry parsing):**

| Prefix | Payload | Effect | Response |
|---|---|---|---|
| `MAXLUX:` | `<lux>` | upserts `device_config.max_hardware_lux` | `max_lux_saved` |
| `CALBARE:` | `<lux>` | calibration_state.phase = `bare_done` | `cal_bare_saved` |
| `CALTAPE:` | `<lux>:<factor>` | phase = `tape_done` | `cal_tape_saved` |
| `CALRESULT:` | `<bare>,<taped>,<factor>,<corrected_max>` | upserts 5 config keys, phase = `done` | `cal_complete` |

`CALRESULT` upserts: `max_hardware_lux`, `lux_attenuation_factor`, `cal_bare_lux`, `cal_taped_lux`, `cal_timestamp`.

**Telemetry rows (7–17 CSV fields):** parsed by `parse_telemetry` (§10). Disposition:

1. Every row (including IDLE and calibration rows) is appended to `recent_sensors_cache`.
2. Calibration-state rows (state 6/7/8): tracked as fallback (`last_cal_lux`/`last_cal_state`), returns `cal_live_only`. If a CALBARE/CALTAPE message is lost, completion is inferred from the CAL→IDLE state transition (bare factor = `bare_lux / taped_lux`).
3. Rows with no active experiment: returns `live_only` (cache only, no DB write).
4. With active experiment:
   - `IDLE` → `ignored_idle_data` (never written to DB)
   - `DONE` → experiment finalized `COMPLETED`, `ended_at` set, returns `experiment_completed`
   - `ABORTED` → finalized `ABORTED` with `completion_reason='FIRMWARE_ABORT'`, returns `experiment_aborted`
   - all other states → inserted into `sensor_logs` (returns `saved`); also updates the experiment's `hold_qualified_progress` and `detected_plateau_temperature` when mode fields are present.

**Response 200:** `{"status": "saved" | "live_only" | "ignored_idle_data" | "experiment_completed" | "experiment_aborted" | "cal_live_only" | … }`. Malformed rows (<7 fields): `error_format`. Unhandled exception: `error` (HTTP 200 — firmware must not retry on HTTP status alone).

## 7. History & Export API

### GET `/api/experiments`

List, newest first. Columns: `id, operator_name, sample_name, started_at, status, mode, illumination_mode, target_lux, target_temperature, hold_duration_s, detected_plateau_temperature, hold_qualified_progress, completion_reason`.

### GET `/api/experiment/{exp_id}`

All telemetry rows for one experiment, chronological (`ORDER BY id ASC`). Columns: `total_time, phase_time, cycle_num, state_label, ir_temp, tc_temp, current_lux, mode, control_temp, temp_setpoint, temp_error, lamp_pwm, hold_wall_elapsed_s, hold_qualified_elapsed_s, qualified, detected_plateau_temp`.

### GET `/api/export/{exp_id}`

CSV download (`StreamingResponse`, filename `<sample>_<operator>.csv`, spaces → underscores). Columns:

```
TotalTime, PhaseTime, Cycle, State, IR_Temp, TC_Temp, Lux, Recorded At, Mode,
ControlTemp, TempSetpoint, TempError, LampPWM, HoldWallElapsedS,
HoldQualifiedElapsedS, Qualified, DetectedPlateauTemp, IlluminationMode, TargetLux
```

(`IlluminationMode`/`TargetLux` are joined from the experiments row.) 404 if the experiment does not exist.

## 8. Calibration & Configuration API

### POST `/api/calibrate_tape?phase=bare|tape|full`

Queues `CAL_BARE` / `CAL_TAPE` / `CAL_FULL` and sets `calibration_state.phase = "<phase>_running"`. 400 for any other phase value.

### GET `/api/calibration_status`

```json
{ "state": {"phase": "tape_done", "bare_lux": 39000.0, "taped_lux": 9500.0, "factor": 4.1},
  "config": {"max_hardware_lux": "38000", "lux_attenuation_factor": "4.1", …} }
```

### GET `/api/get_config`

All `device_config` rows as a flat key→value object (all values are strings; cast as needed). Known keys: `max_hardware_lux`, `lux_attenuation_factor`, `cal_bare_lux`, `cal_taped_lux`, `cal_timestamp`.

## 9. Hardware Command Strings

Emitted by `app/protocol.py`, consumed verbatim by firmware. All fields are `:`-delimited; numbers are decimal-formatted as-is.

| Command | Format | Purpose |
|---|---|---|
| `SET` | `SET:{duration}:{cycles}:{max_temp}:{interval}:{target_lux}` | Normal cyclic, TARGET_LUX |
| `SET2` | `SET2:{duration}:{cycles}:{max_temp}:{interval}:MAX_OUTPUT` | Normal cyclic, MAX_OUTPUT |
| `ISO1` | `ISO1:{target_temp}:{hold_s}:{tolerance}:{qualify_s}:{max_temp}:{interval}:{IR\|TC}:{ramp_rate}` | Fixed-temperature isothermal hold |
| `PLAT1` | `PLAT1:{target_lux}:{hold_s}:{window_s}:{max_slope}:{max_range}:{confirm_s}:{max_discovery_s}:{max_temp}:{interval}:{IR\|TC}:{PASSIVE\|REGULATED}` | Natural plateau, TARGET_LUX |
| `PLAT2` | `PLAT2:MAX_OUTPUT:{hold_s}:{window_s}:{max_slope}:{max_range}:{confirm_s}:{max_discovery_s}:{max_temp}:{interval}:{IR\|TC}:{PASSIVE\|REGULATED}` | Natural plateau, MAX_OUTPUT |
| `STOP` | `STOP` | Abort active experiment |
| `CAL_BARE` / `CAL_TAPE` / `CAL_FULL` | literal | Calibration phases |

## 10. Telemetry Wire Format

CSV line, 7 legacy fields minimum; 17 fields enables the extended control block. Field 8 is a reserved legacy slot — the extension begins at field 9 (index 8).

| # | Name | Type | Notes |
|---|---|---|---|
| 1 | total_time | int (s) | since experiment start |
| 2 | phase_time | int (s) | within current phase |
| 3 | cycle_num | int | current cycle |
| 4 | state_code | int | see §11 |
| 5 | ir_temp | float (°C) | non-finite → null |
| 6 | tc_temp | float (°C) | non-finite → null |
| 7 | current_lux | float | non-finite → null |
| 8 | *(reserved)* | — | ignored by parser |
| 9 | mode | string | e.g. FIXED_TEMPERATURE |
| 10 | control_temp | float (°C) | sensor selected by `control_sensor` |
| 11 | temp_setpoint | float (°C) | |
| 12 | temp_error | float (°C) | |
| 13 | lamp_pwm | float | duty (0–255 scale at UI) |
| 14 | hold_wall_elapsed_s | int | wall-clock hold time |
| 15 | hold_qualified_elapsed_s | int | in-tolerance qualified time |
| 16 | qualified | bool | accepts `1/true/yes` |
| 17 | detected_plateau_temp | float (°C) | plateau result |

## 11. State Code Map

| Code | Label | DB-written? | Notes |
|---|---|---|---|
| 0 | IDLE | no | live monitoring only |
| 1 | PRE_HEAT | yes | excluded from heating fits |
| 2 | HEATING | yes | regression/slope phase |
| 3 | COOLING | yes | |
| 4 | STABILIZING | yes | |
| 5 | DONE | terminal | finalizes experiment as COMPLETED |
| 6 | CAL_BARE | cal | cache only |
| 7 | CAL_TAPE | cal | cache only |
| 8 | CAL_FULL | cal | cache only |
| 9 | ISO_RAMP | yes | fixed-temperature mode |
| 10 | ISO_QUALIFY | yes | |
| 11 | ISO_HOLD | yes | |
| 12 | PLATEAU_HEATING | yes | natural-plateau mode |
| 13 | PLATEAU_CONFIRM | yes | |
| 14 | PLATEAU_HOLD | yes | |
| 15 | ABORTED | terminal | finalizes as ABORTED (FIRMWARE_ABORT) |

Codes outside 0–15 map to label `UNKNOWN`.

## 12. Database Schema

**`experiments`** — one row per experiment: `id` (serial PK), `operator_name`, `sample_name`, `description`, `target_duration`, `target_cycles`, `max_temp`, `log_interval`, `target_lux`, `illumination_mode`, `status` (default WAITING), `started_at`, `ended_at`, plus mode columns: `mode`, `target_temperature`, `hold_duration_s`, `temperature_tolerance`, `qualification_dwell_s`, `control_sensor`, `ramp_rate`, `plateau_window_s`, `plateau_max_slope`, `plateau_max_range`, `plateau_confirmation_s`, `plateau_max_discovery_s`, `post_plateau_mode`, `detected_plateau_temperature`, `hold_qualified_progress`, `completion_reason`.

**`sensor_logs`** — one row per stored telemetry sample: `id` (bigserial PK), `experiment_id` (FK), `total_time`, `phase_time`, `cycle_num`, `state_code`, `state_label`, `ir_temp`, `tc_temp`, `current_lux`, `recorded_at`, plus `mode`, `control_temp`, `temp_setpoint`, `temp_error`, `lamp_pwm`, `hold_wall_elapsed_s`, `hold_qualified_elapsed_s`, `qualified`, `detected_plateau_temp`.

**`device_config`** — key/value store (`key` PK): calibration and hardware limits.

## 13. Database Status Lifecycle

```
            start_experiment            STOP cmd / stop_experiment
                 │                              │
                 ▼                              ▼
              WAITING ────────────────────▶ STOPPED (ended_at)
                 │
     telemetry state 5 (DONE) ──────────▶ COMPLETED (ended_at)
     telemetry state 15 (ABORTED) ──────▶ ABORTED (completion_reason=FIRMWARE_ABORT, ended_at)
```

Only `WAITING` rows are restored into memory at backend startup. Terminal states are never reactivated.

## 14. Server Memory Semantics (recent_sensors_cache)

- Capacity: last 20 telemetry rows (any state, including IDLE and calibration).
- Cleared on `start_experiment` **and** `stop_experiment`.
- This is the **only** source of `/api/current_status.recent_data` — no DB read-back for live charts.
- Implication: after stop, a browser reload shows an empty monitor even though the run's data persists in `sensor_logs` (viewable via `/history`). Mobile Phase 3 KPI retention is therefore session-local; this is a documented limitation, not a bug.

## 15. Error Handling Summary

| Endpoint | Failure mode | Behavior |
|---|---|---|
| any DB-dependent route | DB unreachable (5 retries, 2 s apart) | HTTP 503 `Database unavailable` |
| `start_experiment` | validation failure | HTTP 422 with detail |
| `export/{id}` | unknown id | HTTP 404 |
| `calibrate_tape` | invalid phase | HTTP 400 |
| `insert_data` | malformed CSV | `{"status":"error_format"}` (HTTP 200) |
| `insert_data` | any other exception | `{"status":"error"}` (HTTP 200, logged) |
| `stop_experiment` | any | always `{"status":"stopped"}` |

> Related docs: `docs/DATA_ANALYSIS.md` (analysis conventions), `docs/MOBILE_PHASE3_CONTRACT.md` (dashboard behavior), `README.md` (deployment & network topology).
