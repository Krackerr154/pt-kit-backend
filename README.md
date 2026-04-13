# PT-Kit Backend — Photothermal Experiment Data Acquisition Platform

> A real-time web-based data acquisition and monitoring platform for photothermal experiments. Sensor data is collected by an **Arduino**, transmitted wirelessly via **ESP32** to a **FastAPI** backend, stored in **PostgreSQL**, and visualized live on a browser-based dashboard.

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Network Topology](#network-topology)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation & Deployment](#installation--deployment)
  - [Environment Variables](#environment-variables)
- [Network & Infrastructure Setup](#network--infrastructure-setup)
  - [WireGuard VPN Tunnel](#wireguard-vpn-tunnel)
  - [Nginx Proxy Manager (NPM)](#nginx-proxy-manager-npm)
- [ESP32 Integration](#esp32-integration)
- [Utility Scripts](#utility-scripts)
- [Usage Guide](#usage-guide)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

**PT-Kit** (Photothermal Kit) is a lab-grade platform designed for conducting, monitoring, and archiving photothermal experiments. The system automates the full experiment lifecycle:

1. **Operator** configures experiment parameters (duration, cycles, max temperature, etc.) via the web dashboard.
2. **Server** issues a command to the ESP32 microcontroller.
3. **Arduino** reads IR, thermocouple (TC), and ambient light (Lux) sensor data in real-time while actively maintaining PWM duty cycles.
4. **ESP32** transmits CSV-formatted sensor lines to the server via HTTP.
5. **Server** stores valid data in PostgreSQL and broadcasts live readings to the dashboard.
6. **Dashboard** renders real-time charts, heating rate calculations, lux readings, and state indicators.
7. **History/Archive** page allows post-experiment analysis with overlay, regression, and statistical comparison (T-Test) between samples.
8. **Calibration Page** maps hardware constraints like Absolute Max Lux by analyzing temperature-induced LED drooping in real-time.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           EXPERIMENT SETUP                              │
│                                                                         │
│   ┌────────────┐    Serial    ┌────────────┐     HTTP POST              │
│   │  Arduino   │ ──────────► │   ESP32    │ ──────────────────┐        │
│   │ (Sensors)  │             │ (WiFi TX)  │                   │        │
│   │            │             │            │                   │        │
│   │ • IR Temp  │             │ Polls:     │                   ▼        │
│   │ • TC Temp  │             │ /api/check │          ┌───────────────┐ │
│   │ • Lux      │             │  _command  │          │  FastAPI      │ │
│   │ • State    │             │            │          │  Server       │ │
│   │ • Cycle    │             │ Sends:     │          │  (Uvicorn)    │ │
│                              │ /api/insert│          │  Port 8000    │ │
│                              │  _data     │          └───────┬───────┘ │
│                              └────────────┘                  │         │
│                                                              │         │
│                                                    ┌─────────▼───────┐ │
│                                                    │  PostgreSQL 13  │ │
│                                                    │  Port 5432      │ │
│                                                    └─────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Network Topology

The server runs behind a **NAT** and is exposed to the public internet through a **WireGuard VPN tunnel** to a main server with a public IP. Traffic is then forwarded via **Nginx Proxy Manager (NPM)**.

```
┌──────────────────┐         WireGuard Tunnel         ┌───────────────────────────┐
│  LOCAL SERVER    │ ◄──────────────────────────────► │  MAIN SERVER (Public IP)  │
│  (Behind NAT)   │      Encrypted VPN (UDP)          │                           │
│                  │                                   │  ┌─────────────────────┐  │
│  ┌────────────┐  │    Traffic Forwarding             │  │ Nginx Proxy Manager │  │
│  │ PT-Kit     │  │  ◄──────────────────────────────  │  │ (Reverse Proxy)     │  │
│  │ Backend    │  │    VPN IP → localhost:8000         │  │                     │  │
│  │ :8000      │  │                                   │  │ yourdomain.com ──►  │  │
│  ├────────────┤  │                                   │  │   wg-peer:8000      │  │
│  │ PostgreSQL │  │                                   │  └─────────────────────┘  │
│  │ :5432      │  │                                   │                           │
│  ├────────────┤  │                                   │  Public IP: x.x.x.x      │
│  │ Adminer    │  │                                   └───────────────────────────┘
│  │ :8081      │  │
│  └────────────┘  │         ┌─────────────┐
│                  │  WiFi   │   ESP32      │
│  LAN / WiFi  ◄──┼─────────┤ + Arduino    │
│                  │         │ (Lab Bench)  │
└──────────────────┘         └─────────────┘
```

### Traffic Flow (External User → Experiment Data)

1. **User** opens `https://yourdomain.com` in a browser.
2. **Nginx Proxy Manager** on the public server terminates SSL and proxies the request through the WireGuard tunnel to the local server's internal VPN IP (e.g., `10.0.0.2:8000`).
3. **FastAPI** serves the dashboard and handles API calls.
4. **ESP32** on the same local network communicates directly with the FastAPI server at its LAN IP (e.g., `192.168.x.x:8000`).

---

## Tech Stack

| Layer          | Technology                                       |
| -------------- | ------------------------------------------------ |
| **Hardware**   | Arduino, ESP32, AOD4184 MOSFET, GY-302 (BH1750)  |
| **Backend**    | Python 3.9, FastAPI, Uvicorn                     |
| **Database**   | PostgreSQL 13                                    |
| **Frontend**   | Vanilla HTML/CSS/JS, Chart.js, jStat             |
| **Deployment** | Docker, Docker Compose                           |
| **VPN**        | WireGuard                                        |
| **Proxy**      | Nginx Proxy Manager                              |
| **DB Admin**   | Adminer (port 8081)                              |

---

## Features

### Live Dashboard (`/`)
- **Real-time temperature monitoring** — IR and TC sensor values updated every second.
- **Live charting** with Chart.js — zoomable (Ctrl+Scroll), pannable, and auto-scrolling.
- **Heating rate calculation** — instantaneous °C/s for both IR and TC during heating phase.
- **State indicator bar** — visual dots showing current experiment phase (IDLE → PRE-HEAT → HEATING → COOLING → STABILIZING → DONE).
- **Cycle performance table** — per-cycle heating rate with linear regression slope ± standard error, duration, and peak temperature.
- **Experiment control panel** — configure operator name, sample name, duration, cycles, max temp, target lux, and logging interval.
- **Closed-Loop LED Dimming** — seamless mapping and PID-style tuning that adjusts the AOD4184 PWM frequency in real-time to combat LED thermal droop. 
- **Emergency stop** — immediately halts the experiment and updates database.
- **Auto-sync** — multiple browser clients stay synchronized with server state.
- **State restore on restart** — server resumes tracking an active experiment after a reboot.

### Device Calibration (`/static/calibration.html`)
- **Automated hardware profiling** — blazes an LED connected to the AOD4184 module at 100% PWM.
- **Droop-Awareness** — intelligently charts and halts only when the sliding-window derivative proves the LED's thermal drop has plateaued.
- **Hardware Limitations** — binds hardware constraints to PostgreSQL to prevent impossible parameter requests.

### Data Archive / History (`/history`)
- **Experiment list** — filterable by operator and searchable by sample name.
- **Three analysis modes:**
  - **Expanded** — full timeline view of IR and TC data.
  - **Overlay** — all cycles overlaid on relative time axis for comparison.
  - **Advanced (Regression)** — mean ± SD bands, linear regression line, R² value, and per-sensor statistics.
- **Multi-sample comparison** — select 2+ experiments for side-by-side plotting with automatic **T-Test** significance analysis.
- **CSV export** — download raw data per experiment.

---

## Project Structure

```
pt-kit-backend/
├── docker-compose.yml          # Multi-container orchestration (web, db, adminer)
├── Dockerfile                  # Python 3.9-slim image for the FastAPI app
├── requirements.txt            # Python dependencies
├── gen_data.py                 # Simulated photothermal data generator (for testing)
├── import_csv.py               # CSV-to-database import utility
├── SiAuNPs(3.5_1)_MethodA_80_10_2.csv   # Sample experimental dataset
├── simulasi_fototermal_fisika.csv        # Simulated physics-based dataset
├── app/
│   ├── main.py                 # FastAPI application (all API endpoints)
│   └── static/
│       ├── index.html          # Live monitoring dashboard (SPA)
│       └── history.html        # Data archive & analysis page (SPA)
└── postgres_data/              # Persistent PostgreSQL data volume (auto-generated)
```

---

## API Reference

### Pages

| Method | Endpoint    | Description                      |
| ------ | ----------- | -------------------------------- |
| GET    | `/`         | Serves the live dashboard        |
| GET    | `/history`  | Serves the data archive page     |

### Experiment Control

| Method | Endpoint                  | Description                                        |
| ------ | ------------------------- | -------------------------------------------------- |
| POST   | `/api/start_experiment`   | Create a new experiment and issue START command     |
| POST   | `/api/stop_experiment`    | Emergency stop — marks experiment as STOPPED        |
| GET    | `/api/current_status`     | Returns active experiment info + recent sensor data |

#### `POST /api/start_experiment`

**Request Body:**
```json
{
  "operator_name": "Gerald",
  "sample_name": "MOF-Batch-1",
  "description": "Testing nanoparticle heating efficiency",
  "duration": 60,
  "cycles": 5,
  "max_temp": 80.0,
  "interval": 1,
  "target_lux": 5000.0
}
```

**Response:**
```json
{
  "status": "success",
  "id": 42
}
```

**Behavior:** Creates a new experiment record with status `WAITING`, clears the sensor cache, and queues a command string for the ESP32: `SET:<duration>:<cycles>:<max_temp>:<interval>:<target_lux>`.

#### `POST /api/stop_experiment`

**Response:**
```json
{
  "status": "stopped"
}
```

**Behavior:** Queues a `STOP` command for the ESP32, marks the experiment as `STOPPED` with an `ended_at` timestamp, and clears the sensor cache.

#### `GET /api/current_status`

**Response:**
```json
{
  "active_experiment": {
    "id": 42,
    "operator_name": "Gerald",
    "sample_name": "MOF-Batch-1",
    "status": "WAITING",
    "target_duration": 60,
    "target_cycles": 5,
    "max_temp": 80.0,
    "log_interval": 1,
    "target_lux": 5000.0,
    "started_at": "2026-02-11T10:30:00"
  },
  "recent_data": [
    {
      "total_time": 45,
      "phase_time": 15,
      "cycle_num": 2,
      "state_code": 2,
      "state_label": "HEATING",
      "ir_temp": 65.32,
      "tc_temp": 63.18,
      "current_lux": 4980.5
    }
  ]
}
```

### ESP32 Communication

| Method | Endpoint             | Description                                          |
| ------ | -------------------- | ---------------------------------------------------- |
| GET    | `/api/check_command`  | ESP32 polls this to receive commands                 |
| POST   | `/api/insert_data`    | ESP32 sends sensor readings as a CSV-formatted line  |

#### `GET /api/check_command`

**Response (when command is pending):**
```json
{
  "command": "SET:60:5:80.0:1"
}
```

**Response (no command):**
```json
{
  "command": "IDLE"
}
```

**Behavior:** Returns the pending command once and clears it (one-shot consumption).

#### `POST /api/insert_data`

**Request Body:**
```json
{
  "csv_line": "45,15,2,2,65.32,63.18,4980.5"
}
```

CSV format: `total_time,phase_time,cycle_num,state_code,ir_temp,tc_temp,current_lux`

**State Codes:**
| Code | Label        |
| ---- | ------------ |
| 0    | IDLE         |
| 1    | PRE-HEAT     |
| 2    | HEATING      |
| 3    | COOLING      |
| 4    | STABILIZING  |
| 5    | DONE         |

**Response:**
```json
{"status": "saved"}          // Data saved to DB (valid state + active experiment)
{"status": "live_only"}      // No active experiment — data shown on chart only
{"status": "ignored_idle_data"} // IDLE/DONE state filtered out from DB storage
```

**Behavior:**
- Always appends to the in-memory `recent_sensors_cache` (max 20 entries) for live dashboard display.
- Only writes to the database when an experiment is active **AND** the state is not IDLE or DONE (prevents junk data in exports).

### History & Export

| Method | Endpoint                   | Description                                      |
| ------ | -------------------------- | ------------------------------------------------ |
| GET    | `/api/experiments`         | List all experiments (descending by ID)           |
| GET    | `/api/experiment/{exp_id}` | Get all sensor log data for a specific experiment |
| GET    | `/api/export/{exp_id}`     | Download experiment data as a CSV file            |

#### `GET /api/export/{exp_id}`

Returns a CSV file download with headers:
```
Total Time, Phase Time, Cycle, State, IR Temp, TC Temp, Recorded At
```

Filename format: `<sample_name>_<operator_name>.csv`

---

## Database Schema

### `experiments`

| Column            | Type         | Description                                     |
| ----------------- | ------------ | ----------------------------------------------- |
| `id`              | SERIAL PK    | Auto-incrementing experiment ID                  |
| `operator_name`   | VARCHAR(50)  | Name of the operator running the experiment      |
| `sample_name`     | VARCHAR(100) | Name/label of the sample being tested            |
| `description`     | TEXT         | Optional experiment description                  |
| `target_duration` | INT          | Target duration per cycle (seconds)              |
| `target_cycles`   | INT          | Target number of heating/cooling cycles          |
| `max_temp`        | FLOAT        | Maximum temperature cutoff (°C)                  |
| `target_lux`      | FLOAT        | Target Lux level for closed-loop dimming         |
| `log_interval`    | INT          | Sensor logging interval (seconds)                |
| `status`          | VARCHAR(20)  | `WAITING` (active), `STOPPED`, or `COMPLETED`    |
| `started_at`      | TIMESTAMP    | Experiment creation timestamp                    |
| `ended_at`        | TIMESTAMP    | Experiment end timestamp (NULL if still running)  |

### `sensor_logs`

| Column          | Type        | Description                                        |
| --------------- | ----------- | -------------------------------------------------- |
| `id`            | BIGSERIAL PK| Auto-incrementing log entry ID                     |
| `experiment_id` | INT FK      | References `experiments.id`                         |
| `total_time`    | INT         | Elapsed time since experiment start (seconds)       |
| `phase_time`    | INT         | Elapsed time within current phase (seconds)         |
| `cycle_num`     | INT         | Current cycle number                                |
| `state_code`    | INT         | Numeric state code (0–6)                            |
| `state_label`   | VARCHAR(20) | Human-readable state name                           |
| `ir_temp`       | FLOAT       | Infrared sensor temperature (°C)                    |
| `tc_temp`       | FLOAT       | Thermocouple sensor temperature (°C)                |
| `current_lux`   | FLOAT       | Ambient Light level via GY-302 sensor (lx)          |
| `recorded_at`   | TIMESTAMP   | Server-side timestamp when data was recorded         |

### `device_config`

| Column          | Type        | Description                                        |
| --------------- | ----------- | -------------------------------------------------- |
| `key`           | VARCHAR(50) | Setting key (e.g., `max_hardware_lux`)             |
| `value`         | VARCHAR(100)| Setting value                                      |

---

## Getting Started

### Prerequisites

- **Docker** and **Docker Compose** installed on the local server.
- **WireGuard** configured on both the local server and the public server.
- **Nginx Proxy Manager** running on the public server.
- **ESP32** with Arduino connected and programmed to communicate with this API.

### Installation & Deployment

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd pt-kit-backend
   ```

2. **Start all services:**
   ```bash
   docker compose up -d --build
   ```

   This starts three containers:
   | Service   | Port (Host)   | Description                |
   | --------- | ------------- | -------------------------- |
   | `web`     | `8000`        | FastAPI application        |
   | `db`      | `5433`        | PostgreSQL 13 database     |
   | `adminer` | `8081`        | Database admin web UI      |

3. **Verify the server is running:**
   ```bash
   curl http://localhost:8000/api/current_status
   ```

4. **Access the dashboard:**
   Open `http://localhost:8000` in a browser.

5. **Access the database admin panel:**
   Open `http://localhost:8081` and log in with:
   - **System:** PostgreSQL
   - **Server:** `db`
   - **Username:** `ptkit_user`
   - **Password:** `pt154`
   - **Database:** `ptkit_db`

### Environment Variables

| Variable            | Default       | Description                     |
| ------------------- | ------------- | ------------------------------- |
| `DB_HOST`           | `db`          | PostgreSQL host                 |
| `POSTGRES_DB`       | `ptkit_db`    | Database name                   |
| `POSTGRES_USER`     | `ptkit_user`  | Database user                   |
| `POSTGRES_PASSWORD` | `pt154`       | Database password               |

> ⚠️ **Security Note:** Change the default database password in production. Update both `docker-compose.yml` and ensure the `web` service environment variables match.

---

## Network & Infrastructure Setup

### WireGuard VPN Tunnel

The local server (behind NAT) establishes an outbound WireGuard tunnel to the main server with a public IP. This allows the public server to route traffic back to the local server.

#### Local Server (Peer / Client) — `/etc/wireguard/wg0.conf`

```ini
[Interface]
PrivateKey = <LOCAL_PRIVATE_KEY>
Address = 10.0.0.2/24        # VPN IP for the local server

[Peer]
PublicKey = <MAIN_SERVER_PUBLIC_KEY>
Endpoint = <PUBLIC_IP>:51820  # Public server's WireGuard port
AllowedIPs = 10.0.0.0/24     # Route VPN subnet through tunnel
PersistentKeepalive = 25     # Keep NAT mapping alive
```

#### Main Server (Hub) — `/etc/wireguard/wg0.conf`

```ini
[Interface]
PrivateKey = <MAIN_SERVER_PRIVATE_KEY>
Address = 10.0.0.1/24        # VPN IP for the main server
ListenPort = 51820

[Peer]
PublicKey = <LOCAL_SERVER_PUBLIC_KEY>
AllowedIPs = 10.0.0.2/32     # Allow traffic from/to the local server
```

#### Enable and Start WireGuard

```bash
# On both servers:
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

# Verify connectivity:
ping 10.0.0.2    # From main server → local server
ping 10.0.0.1    # From local server → main server
```

### Nginx Proxy Manager (NPM)

NPM runs on the main server (public IP) and acts as a reverse proxy to forward incoming HTTPS traffic through the WireGuard tunnel to the local PT-Kit server.

#### Proxy Host Configuration

| Field                | Value                           |
| -------------------- | ------------------------------- |
| **Domain Name**      | `ptkit.yourdomain.com`          |
| **Scheme**           | `http`                          |
| **Forward Hostname** | `10.0.0.2` (WireGuard VPN IP)  |
| **Forward Port**     | `8000`                          |
| **SSL**              | Request a new SSL certificate via Let's Encrypt |
| **Force SSL**        | Enabled                         |
| **Websockets**       | Enabled (for future use)        |

#### Steps in NPM Web UI:

1. Open NPM at `http://<PUBLIC_IP>:81`.
2. Go to **Proxy Hosts** → **Add Proxy Host**.
3. Fill in the domain, forward hostname (`10.0.0.2`), and port (`8000`).
4. Under the **SSL** tab, select "Request a new SSL Certificate" and enable "Force SSL".
5. Save.

Now `https://ptkit.yourdomain.com` routes to your local PT-Kit server securely.

#### Optional: Adminer Access

Add another proxy host for the database admin panel:

| Field                | Value                           |
| -------------------- | ------------------------------- |
| **Domain Name**      | `dbadmin.yourdomain.com`        |
| **Forward Hostname** | `10.0.0.2`                      |
| **Forward Port**     | `8081`                          |

> ⚠️ **Security:** Restrict Adminer access with NPM's Access Lists or disable it in production.

---

## ESP32 Integration

The ESP32 communicates with the server using two endpoints in a polling loop:

### Communication Protocol

```
┌─────────────────────────────────────────────────┐
│                  ESP32 Main Loop                │
│                                                  │
│   1. GET /api/check_command                     │
│      ├─ "IDLE"  → continue monitoring           │
│      ├─ "SET:60:5:80:1" → configure & start     │
│      └─ "STOP"  → halt experiment               │
│                                                  │
│   2. Read sensors (Arduino Serial)              │
│      └─ Parse: total_time, phase_time,          │
│         cycle_num, state_code, ir_temp, tc_temp │
│                                                  │
│   3. POST /api/insert_data                      │
│      Body: {"csv_line": "45,15,2,2,65.32,63.18"}│
│                                                  │
│   4. Wait <interval> seconds                    │
│      └─ Repeat from step 1                      │
└─────────────────────────────────────────────────┘
```

### Expected ESP32 Behavior

1. **On boot:** Begin polling `/api/check_command` every 1 second.
2. **On `SET` command:** Parse parameters — `SET:<duration>:<cycles>:<max_temp>:<interval>`.
   - Configure Arduino heating parameters.
   - Begin experiment cycle (PRE-HEAT → HEATING → COOLING → STABILIZING, repeat for N cycles).
3. **During experiment:** Read sensor data from Arduino via Serial, format as CSV line, send via `POST /api/insert_data`.
4. **On `STOP` command:** Immediately halt heating, set state to IDLE.
5. **On experiment completion:** Send final data with state code `5` (DONE).

### CSV Line Format

```
<total_time>,<phase_time>,<cycle_num>,<state_code>,<ir_temp>,<tc_temp>
```

**Example:** `120,30,3,2,72.45,70.12` — 120s total elapsed, 30s into current phase, cycle 3, HEATING state, IR reads 72.45°C, TC reads 70.12°C.

---

## Utility Scripts

### `gen_data.py` — Simulated Data Generator

Generates a physics-based simulated photothermal dataset for testing without real hardware.

```bash
python gen_data.py
```

**Output:** `simulasi_fototermal_fisika.csv`

**Simulation Parameters:**
| Parameter           | Default | Description                                   |
| ------------------- | ------- | --------------------------------------------- |
| `CYCLES`            | 10      | Number of heating/cooling cycles               |
| `ROOM_TEMP`         | 28.0°C  | Ambient room temperature                       |
| `TARGET_CUTOFF`     | 80.0°C  | Temperature at which heating phase stops        |
| `HOLD_TIME`         | 20s     | Stabilization hold time at peak temperature     |
| `BASE_LASER_POWER`  | 4.5     | Simulated laser power input                    |
| `BASE_ABSORBANCE`   | 0.85    | Sample absorbance coefficient                  |
| `HEAT_CAPACITY`     | 12.0    | Thermal mass of the sample                     |
| `HEAT_LOSS_COEFF`   | 0.04    | Newton's law cooling coefficient               |
| `DEGRADATION_RATE`  | 0.005   | Per-cycle absorbance degradation               |
| `ACCUMULATION_RATE` | 0.15    | Per-cycle residual heat accumulation            |

### `import_csv.py` — CSV-to-Database Importer

Imports a CSV file into the database as a completed experiment.

```bash
# Run inside the Docker container or with DB access:
python import_csv.py
```

**Configuration (edit variables in the script):**
| Variable        | Default                      | Description              |
| --------------- | ---------------------------- | ------------------------ |
| `CSV_FILENAME`  | `data_import.csv`            | Input CSV file path      |
| `SAMPLE_NAME`   | `Simulation Data [Import]`   | Experiment sample label  |
| `OPERATOR_NAME` | `Gerald (Import)`            | Operator name            |

---

## Usage Guide

### Running an Experiment

1. Open the dashboard at `https://ptkit.yourdomain.com` (or `http://localhost:8000` locally).
2. Fill in the **Control Panel** on the right:
   - **Operator Name** — who is running the experiment.
   - **Sample Name** — label for the sample (e.g., `SiAuNPs-Batch-3`).
   - **Target Duration** — seconds per heating cycle.
   - **Total Cycles** — number of heating/cooling cycles.
   - **Max Temp** — temperature cutoff in °C.
   - **Logging Interval** — how often data is recorded (in seconds).
3. Click **🚀 START EXPERIMENT**.
4. Monitor real-time data on the chart. The state indicator shows the current phase.
5. The **Cycle Performance History** table updates after each heating phase completes.
6. When all cycles finish, the state transitions to **DONE** and you can **📥 DOWNLOAD CSV DATA**.
7. Use **⛔ EMERGENCY STOP** at any time to abort the experiment.

### Analyzing Historical Data

1. Navigate to `/history` or click **📂 Buka Data Archive** from the dashboard.
2. Filter experiments by operator or search by sample name.
3. Select one experiment and click **🔬 Experiment Analysis** to view:
   - **Expanded** — full timeline.
   - **Overlay** — all cycles superimposed on a relative time axis.
   - **Advanced** — mean ± SD confidence band, linear regression, and R² statistics for both IR and TC sensors.
4. Select two experiments and click **📈 Compare** to view side-by-side charts with automatic T-Test comparison of heating slopes.
5. Click **⬇ CSV** to download raw data.

---

## Troubleshooting

| Problem                                    | Solution                                                                 |
| ------------------------------------------ | ------------------------------------------------------------------------ |
| Dashboard shows "🔴 Disconnected"          | Check if Docker containers are running: `docker compose ps`              |
| ESP32 can't reach the server               | Verify ESP32 is on the same LAN. Check firewall allows port 8000.        |
| Data not saving to database                | Ensure an experiment is active (status `WAITING`). IDLE/DONE states are filtered out. |
| Chart not updating                         | Browser may have stale cache. Hard-refresh with `Ctrl+Shift+R`.          |
| Public URL not accessible                  | Check WireGuard tunnel: `sudo wg show`. Verify NPM proxy host config.   |
| Database connection errors                 | Check PostgreSQL container: `docker compose logs db`. Verify credentials. |
| Experiment still "WAITING" after restart   | By design — server restores active experiments on startup. Stop manually if needed. |
| Port 5433 conflict                         | PostgreSQL is exposed on host port 5433 (not 5432). Update your DB client. |

---

## License

This project is developed for academic/research use in photothermal experimentation.

---

<p align="center">
  <b>PT-Kit</b> — Photothermal Experiment Platform<br>
  Built with ❤️ for Science
</p>
