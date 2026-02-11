# PT-Kit Backend — Copilot Instructions

## Architecture Overview

PT-Kit is a **photothermal experiment** data acquisition platform with a hardware→server→browser pipeline:

```
Arduino (sensors) → Serial 9600 → ESP32 (WiFi/HTTPS) → FastAPI (main.py) → PostgreSQL
                                                              ↕ polling 1s
                                                        Browser Dashboard
```

- **Arduino.ino**: Reads IR + thermocouple sensors, runs a 6-state machine (`IDLE=0, PRE_HEAT=1, HEATING=2, COOLING=3, STABILIZING=4, DONE=5`), sends 7-field CSV lines over Serial every 1 second. Timer (`totalMasterSec`) only increments during active experiment states (not IDLE/DONE).
- **ESP32.ino**: FreeRTOS dual-core — Core 1 reads Serial2 into a queue, Core 0 POSTs `{"csv_line":"..."}` to `/api/insert_data` and polls `/api/check_command` every 3 seconds. JSON command parsing uses robust `indexOf('"')` chain to extract values.
- **app/main.py**: Single-file FastAPI app. All state is in globals (`pending_command`, `current_experiment_id`, `recent_sensors_cache`). No async — uses sync `psycopg2`. DB connection uses bounded retries (max 5 for requests, infinite for startup).
- **app/static/index.html**: Live dashboard — polls `/api/current_status` every 1 second, plots Chart.js, computes live heating rate via linear regression.
- **app/static/history.html**: Archive page — expanded/overlay/advanced views, per-cycle regression, T-Test comparison via jStat.

## Data Flow — CSV Line Format

Arduino sends: `totalMasterSec,currentSec,cycleNum,stateCode,irTemp,tcTemp,saveFlag`
Server parses indices 0–5 in `insert_data()`. The 7th field (`saveFlag`) is currently ignored by the server — data saving is controlled server-side based on state and active experiment.

The server buffers the last 20 readings in `recent_sensors_cache` (`collections.deque(maxlen=20)`, thread-safe) and conditionally saves to DB. The dashboard reads this cache via `/api/current_status`.

## State Code Contract

The numeric state codes `0–5` are the **canonical interface** between all systems. String labels are standardized to **underscore** format:

| Code | Label | Arduino Enum | Server/DB | Dashboard |
|------|-------|-------------|-----------|-----------|
| 0 | IDLE | `IDLE` | `"IDLE"` | `"IDLE"` |
| 1 | PRE_HEAT | `PRE_HEAT` | `"PRE_HEAT"` | `"PRE_HEAT"` |
| 2 | HEATING | `HEATING` | `"HEATING"` | `"HEATING"` |
| 3 | COOLING | `COOLING` | `"COOLING"` | `"COOLING"` |
| 4 | STABILIZING | `STABILIZING` | `"STABILIZING"` | `"STABILIZING"` |
| 5 | DONE | `DONE` | `"DONE"` | `"DONE"` |

**When editing state logic, always work with numeric `state_code`, not string labels.**
History.html filters heating data using `.includes('HEAT') && !.includes('PRE')` for resilience.

## Experiment Lifecycle

1. Dashboard `POST /api/start_experiment` → status `WAITING`, sets `pending_command`
2. ESP32 polls `GET /api/check_command` → forwards `SET:dur:cycles:maxTemp:interval` to Arduino
3. Arduino runs state machine: `PRE_HEAT → HEATING → COOLING → STABILIZING → (repeat cycles) → DONE`
4. On DONE: server receives state_code=5 → updates status to `COMPLETED`, sets `ended_at`, clears `current_experiment_id`
5. On STOP: dashboard `POST /api/stop_experiment` → status `STOPPED`, Arduino `forceStop()` resets all timers

Commands are one-shot: `check_command` returns the pending command once, then clears it to `"IDLE"`.

## Key Conventions

- **Single-file backend**: All endpoints, models, DB setup, and globals live in `app/main.py`. No routers or modules.
- **No ORM**: Raw `psycopg2` with `RealDictCursor` for dict results. `get_db_connection(max_retries=5)` opens a new connection per call (no pool). Use `max_retries=0` for startup only.
- **Frontend is vanilla JS**: No framework. Chart.js 4.4.1, chartjs-plugin-zoom, jStat. All logic in `<script>` blocks within the HTML files.
- **Comments in Indonesian**: Much of the codebase uses Bahasa Indonesia comments. Preserve this convention when adding comments.
- **Inline CSS**: Styles are embedded in `<style>` tags, not external files.

## CSV Header Convention

All CSV headers use **no-space, underscore** format for consistency across export, import, and generation:
`TotalTime,PhaseTime,Cycle,State,IR_Temp,TC_Temp`

- `gen_data.py` outputs this format (+ `SaveFlag` column)
- `import_csv.py` reads this format with `STATE_MAP` supporting both `PRE_HEAT` and `PRE-HEAT`
- `/api/export/{exp_id}` writes this format (+ `Recorded At` column)

## Dashboard State Machine (index.html)

The dashboard uses several boolean flags to manage transitions:
- `isProcessingStart` — blocks `updateStatus()` while the server processes a start request
- `startWaitData` — waits for fresh data (time < 5s, or time dropped, or state changed to non-IDLE) after starting
- `isWaitingReset` — after DONE, waits for Arduino to cycle back to IDLE before clearing the chart
- `isRunning` — general running state; controls UI form/button visibility

**Heating rate** is calculated via linear regression on accumulated `{x: relativeTime, y: temp}` buffers, only during HEATING phase (state 2). Uses `calculateSlopeAndError()` returning `{slope, error, r2}`.

## Docker & Deployment

```bash
docker compose up --build -d   # starts web (8000), db (5433→5432), adminer (8081)
```

Server is behind NAT, exposed via WireGuard VPN tunnel → Nginx Proxy Manager → `https://pt-kit.g-labs.my.id/api`. The ESP32 connects to this HTTPS URL with `client.setInsecure()` (no cert verification).

## Utility Scripts (run inside Docker network or with DB_HOST adjusted)

- `gen_data.py` — Physics-based simulation generator. Outputs CSV with headers: `TotalTime,PhaseTime,Cycle,State,IR_Temp,TC_Temp,SaveFlag`
- `import_csv.py` — Imports CSV into DB. Reads `TotalTime,PhaseTime,Cycle,State,IR_Temp,TC_Temp`. `STATE_MAP` supports both `PRE_HEAT` and `PRE-HEAT` plus `DONE`.
