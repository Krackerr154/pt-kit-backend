from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, root_validator, validator
from typing import Optional
from app.protocol import (ExperimentMode, IlluminationMode, PostPlateauMode, STATE_LABELS, parse_telemetry,
                          serialize_fixed_command, serialize_normal_command, serialize_plateau_command)
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import time
import csv
import io
import collections
import logging

logger = logging.getLogger("ptkit")

app = FastAPI()

# --- MOUNT STATIC FILES ---
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- DATABASE CONFIG ---
DB_HOST = os.getenv("DB_HOST", "db")
DB_NAME = os.getenv("POSTGRES_DB", "ptkit_db")
DB_USER = os.getenv("POSTGRES_USER", "ptkit_user")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "pt154")

def get_db_connection(max_retries=5):
    """Buat koneksi DB dengan retry. max_retries=0 untuk infinite (startup only)."""
    attempts = 0
    while max_retries == 0 or attempts < max_retries:
        try:
            return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        except Exception as e:
            attempts += 1
            logger.warning(f"DB connection attempt {attempts} failed: {e}")
            time.sleep(2)
    raise HTTPException(status_code=503, detail="Database unavailable")

# --- GLOBAL VARS ---
pending_command = None 
current_experiment_id = None
recent_sensors_cache = collections.deque(maxlen=20)
calibration_state = {"phase": "idle", "bare_lux": None, "taped_lux": None, "factor": None}

# --- MODELS ---
class ExperimentConfig(BaseModel):
    operator_name: str 
    sample_name: str
    description: str = ""
    duration: int = 60
    cycles: int = 5
    max_temp: float = 80.0
    interval: int = 1
    target_lux: Optional[float] = 38000.0
    illumination_mode: IlluminationMode = IlluminationMode.TARGET_LUX
    mode: ExperimentMode = ExperimentMode.NORMAL_CYCLIC
    target_temperature: Optional[float] = None
    hold_duration_s: Optional[int] = None
    temperature_tolerance: Optional[float] = None
    qualification_dwell_s: Optional[int] = None
    control_sensor: str = "IR"
    ramp_rate: Optional[float] = None
    plateau_window_s: Optional[int] = None
    plateau_max_slope: Optional[float] = None
    plateau_max_range: Optional[float] = None
    plateau_confirmation_s: Optional[int] = None
    plateau_max_discovery_s: Optional[int] = None
    post_plateau_mode: PostPlateauMode = PostPlateauMode.PASSIVE

    @validator("duration")
    def valid_duration(cls, value):
        if value <= 0: raise ValueError("must be positive")
        if value > 4294967: raise ValueError("must be at most 4294967")
        return value

    @validator("cycles", "interval")
    def valid_small_integer(cls, value):
        if value <= 0: raise ValueError("must be positive")
        if value > 32767: raise ValueError("must be at most 32767")
        return value

    @validator("control_sensor")
    def valid_sensor(cls, value):
        if value not in ("TC", "IR"): raise ValueError("control_sensor must be TC or IR")
        return value

    @root_validator(pre=True)
    def reject_fixed_max_output(cls, values):
        mode = values.get("mode", ExperimentMode.NORMAL_CYCLIC)
        illumination = values.get("illumination_mode")
        fixed = mode in (ExperimentMode.FIXED_TEMPERATURE, ExperimentMode.FIXED_TEMPERATURE.value)
        maximum = illumination in (IlluminationMode.MAX_OUTPUT, IlluminationMode.MAX_OUTPUT.value)
        if fixed and maximum:
            raise ValueError("MAX_OUTPUT is incompatible with fixed-temperature control")
        return values

    @root_validator(skip_on_failure=True)
    def validate_mode(cls, values):
        import math
        mode = values.get("mode")
        illumination = values.get("illumination_mode")
        target_lux = values.get("target_lux")
        if mode == ExperimentMode.FIXED_TEMPERATURE:
            values["illumination_mode"] = IlluminationMode.TEMPERATURE_CONTROLLED
            values["target_lux"] = None
        elif illumination == IlluminationMode.TEMPERATURE_CONTROLLED:
            raise ValueError("TEMPERATURE_CONTROLLED is only valid for fixed-temperature mode")
        elif illumination == IlluminationMode.MAX_OUTPUT:
            values["target_lux"] = None
        elif target_lux is None or not math.isfinite(target_lux) or target_lux < 0:
            raise ValueError("target_lux must be finite and non-negative in TARGET_LUX mode")
        elif mode == ExperimentMode.NATURAL_PLATEAU and target_lux <= 0:
            raise ValueError("natural plateau TARGET_LUX must be greater than zero")
        required = {ExperimentMode.FIXED_TEMPERATURE: ("target_temperature", "hold_duration_s", "temperature_tolerance", "qualification_dwell_s", "ramp_rate"), ExperimentMode.NATURAL_PLATEAU: ("hold_duration_s", "plateau_window_s", "plateau_max_slope", "plateau_max_range", "plateau_confirmation_s", "plateau_max_discovery_s")}.get(mode, ())
        missing = [n for n in required if values.get(n) is None]
        if missing: raise ValueError("missing mode configuration: " + ", ".join(missing))
        for n in required:
            if not math.isfinite(values[n]) or values[n] <= 0: raise ValueError(n + " must be finite and positive")
        if mode == ExperimentMode.FIXED_TEMPERATURE and values["max_temp"] <= values["target_temperature"]: raise ValueError("max_temp must exceed target_temperature")
        if mode == ExperimentMode.NATURAL_PLATEAU:
            if values["plateau_window_s"] > 60: raise ValueError("plateau_window_s exceeds firmware capacity")
            if values["plateau_max_discovery_s"] < values["plateau_window_s"]: raise ValueError("discovery must cover window")
            if values["plateau_max_discovery_s"] > 6500: raise ValueError("plateau_max_discovery_s must be at most 6500")
        for n in ("hold_duration_s", "qualification_dwell_s", "plateau_window_s", "plateau_confirmation_s", "plateau_max_discovery_s"):
            if values.get(n) is not None and values[n] > 4294967: raise ValueError(n + " is too large")
        return values

class EspSensorData(BaseModel):
    csv_line: str 

# --- STARTUP EVENT (DATABASE & RESTORE STATE) ---
@app.on_event("startup")
def startup_db():
    global current_experiment_id
    conn = get_db_connection(max_retries=0)  # Infinite retry saat startup
    cur = conn.cursor()
    
    # 1. Buat Tabel Experiments
    cur.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            id SERIAL PRIMARY KEY,
            operator_name VARCHAR(50), 
            sample_name VARCHAR(100),
            description TEXT,
            target_duration INT,
            target_cycles INT,
            max_temp FLOAT,
            log_interval INT,
            target_lux FLOAT DEFAULT 0,
            illumination_mode VARCHAR(24) DEFAULT 'TARGET_LUX',
            status VARCHAR(20) DEFAULT 'WAITING',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP
        );
    """)
    cur.execute("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS target_lux FLOAT DEFAULT 0;")
    for ddl in ["illumination_mode VARCHAR(24) DEFAULT 'TARGET_LUX'", "mode VARCHAR(30) DEFAULT 'NORMAL_CYCLIC'", "target_temperature FLOAT", "hold_duration_s INT", "temperature_tolerance FLOAT", "qualification_dwell_s INT", "control_sensor VARCHAR(10)", "ramp_rate FLOAT", "plateau_window_s INT", "plateau_max_slope FLOAT", "plateau_max_range FLOAT", "plateau_confirmation_s INT", "plateau_max_discovery_s INT", "post_plateau_mode VARCHAR(12)", "detected_plateau_temperature FLOAT", "hold_qualified_progress FLOAT", "completion_reason VARCHAR(100)"]:
        cur.execute(f"ALTER TABLE experiments ADD COLUMN IF NOT EXISTS {ddl};")
    cur.execute("UPDATE experiments SET illumination_mode='TEMPERATURE_CONTROLLED', target_lux=NULL WHERE mode='FIXED_TEMPERATURE' AND illumination_mode='TARGET_LUX';")
    
    # 2. Buat Tabel Sensor Logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensor_logs (
            id BIGSERIAL PRIMARY KEY,
            experiment_id INTEGER REFERENCES experiments(id),
            total_time INT,
            phase_time INT,
            cycle_num INT,
            state_code INT,
            state_label VARCHAR(20),
            ir_temp FLOAT,
            tc_temp FLOAT,
            current_lux FLOAT DEFAULT 0,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cur.execute("ALTER TABLE sensor_logs ADD COLUMN IF NOT EXISTS current_lux FLOAT DEFAULT 0;")
    for ddl in ["mode VARCHAR(30)", "control_temp FLOAT", "temp_setpoint FLOAT", "temp_error FLOAT", "lamp_pwm FLOAT", "hold_wall_elapsed_s INT", "hold_qualified_elapsed_s INT", "qualified BOOLEAN", "detected_plateau_temp FLOAT"]:
        cur.execute(f"ALTER TABLE sensor_logs ADD COLUMN IF NOT EXISTS {ddl};")

    # 3. Buat Tabel Device Config
    cur.execute("""
        CREATE TABLE IF NOT EXISTS device_config (
            key VARCHAR(50) PRIMARY KEY,
            value VARCHAR(100)
        );
    """)
    conn.commit()

    # [FITUR RESTORE STATE]
    print("Checking for active experiments...")
    cur.execute("SELECT id FROM experiments WHERE status = 'WAITING' ORDER BY id DESC LIMIT 1")  # COMPLETED/STOPPED tidak di-restore
    row = cur.fetchone()
    if row:
        current_experiment_id = row[0]
        print(f"Restored Active Experiment ID: {current_experiment_id}")
    else:
        print("No active experiment found.")

    cur.close()
    conn.close()
    print("System Ready!")

# --- ENDPOINTS UTAMA ---

@app.get("/")
def read_index():
    return FileResponse('app/static/index.html')

@app.get("/history")
def read_history():
    return FileResponse('app/static/history.html')

@app.post("/api/start_experiment")
def start_experiment(config: ExperimentConfig):
    global current_experiment_id, pending_command, recent_sensors_cache

    # Build and validate the hardware command before clearing live data or writing to the DB.
    if config.mode == ExperimentMode.FIXED_TEMPERATURE:
        values = (config.target_temperature, config.hold_duration_s, config.temperature_tolerance, config.qualification_dwell_s, config.ramp_rate)
        if any(v is None for v in values): raise HTTPException(422, "Missing fixed-temperature configuration")
        command = serialize_fixed_command(values[0], values[1], values[2], values[3], config.max_temp, config.interval, config.control_sensor, values[4])
    elif config.mode == ExperimentMode.NATURAL_PLATEAU:
        values = (config.hold_duration_s, config.plateau_window_s, config.plateau_max_slope, config.plateau_max_range, config.plateau_confirmation_s, config.plateau_max_discovery_s)
        if any(v is None for v in values): raise HTTPException(422, "Missing natural-plateau configuration")
        command = serialize_plateau_command(config.target_lux, *values, config.max_temp, config.interval, config.control_sensor, config.post_plateau_mode, config.illumination_mode)
    else:
        command = serialize_normal_command(config.duration, config.cycles, config.max_temp, config.interval, config.target_lux, config.illumination_mode)

    # [FITUR] Reset Grafik di Memori Server saat Start
    recent_sensors_cache.clear()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO experiments
        (operator_name, sample_name, description, target_duration, target_cycles, max_temp, log_interval, target_lux, illumination_mode, status,
         mode, target_temperature, hold_duration_s, temperature_tolerance, qualification_dwell_s, control_sensor, ramp_rate,
         plateau_window_s, plateau_max_slope, plateau_max_range, plateau_confirmation_s, plateau_max_discovery_s, post_plateau_mode)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'WAITING',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (config.operator_name, config.sample_name, config.description, config.duration, config.cycles, config.max_temp,
          config.interval, config.target_lux, config.illumination_mode.value, config.mode.value, config.target_temperature,
          config.hold_duration_s, config.temperature_tolerance, config.qualification_dwell_s, config.control_sensor,
          config.ramp_rate, config.plateau_window_s, config.plateau_max_slope, config.plateau_max_range,
          config.plateau_confirmation_s, config.plateau_max_discovery_s, config.post_plateau_mode.value))

    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    current_experiment_id = new_id
    pending_command = command

    return {"status": "success", "id": new_id, "mode": config.mode.value,
            "illumination_mode": config.illumination_mode.value}

@app.post("/api/stop_experiment")
def stop_experiment():
    global current_experiment_id, pending_command, recent_sensors_cache
    pending_command = "STOP"
    
    # [PERBAIKAN PENTING] Hapus ingatan grafik saat STOP
    # Agar saat New Experiment nanti, grafik benar-benar bersih dari nol
    recent_sensors_cache.clear()
    
    if current_experiment_id:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE experiments SET status='STOPPED', ended_at=NOW() WHERE id=%s", (current_experiment_id,))
        conn.commit()
        cur.close()
        conn.close()
        current_experiment_id = None
        
    return {"status": "stopped"}

@app.get("/api/current_status")
def get_status():
    global recent_sensors_cache, current_experiment_id
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    exp_info = None
    if current_experiment_id:
        cur.execute("SELECT * FROM experiments WHERE id = %s", (current_experiment_id,))
        exp_info = cur.fetchone()
    
    cur.close()
    conn.close()
    
    return {"active_experiment": exp_info, "recent_data": list(recent_sensors_cache)}

@app.get("/api/check_command")
def check_command():
    global pending_command
    if pending_command:
        cmd = pending_command
        pending_command = None
        return {"command": cmd}
    return {"command": "IDLE"}

@app.post("/api/insert_data")
def insert_data(data: EspSensorData):
    global current_experiment_id, recent_sensors_cache
    try:
        if data.csv_line.startswith("MAXLUX:"):
            try:
                max_lux = data.csv_line.split(":")[1].strip()
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO device_config (key, value) VALUES ('max_hardware_lux', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (max_lux,))
                conn.commit()
                cur.close()
                conn.close()
                return {"status": "max_lux_saved", "val": max_lux}
            except Exception as e:
                logger.error(f"Error parsing MAXLUX: {e}")
                return {"status": "error_maxlux"}

        if data.csv_line.startswith("CALBARE:"):
            try:
                bare_lux = float(data.csv_line.split(":")[1].strip())
                calibration_state["phase"] = "bare_done"
                calibration_state["bare_lux"] = bare_lux
                return {"status": "cal_bare_saved", "bare_lux": bare_lux}
            except Exception as e:
                logger.error(f"Error parsing CALBARE: {e}")
                return {"status": "error_calbare"}

        if data.csv_line.startswith("CALTAPE:"):
            try:
                parts = data.csv_line.replace("CALTAPE:", "").split(":")
                taped_lux = float(parts[0].strip())
                factor = float(parts[1].strip())
                calibration_state["phase"] = "tape_done"
                calibration_state["taped_lux"] = taped_lux
                calibration_state["factor"] = factor
                return {"status": "cal_tape_saved", "taped_lux": taped_lux, "factor": factor}
            except Exception as e:
                logger.error(f"Error parsing CALTAPE: {e}")
                return {"status": "error_caltape"}

        if data.csv_line.startswith("CALRESULT:"):
            try:
                vals = data.csv_line.replace("CALRESULT:", "").split(",")
                bare = vals[0].strip()
                taped = vals[1].strip()
                factor = vals[2].strip()
                corrected_max = vals[3].strip()
                
                conn = get_db_connection()
                cur = conn.cursor()
                for k, v in [
                    ("max_hardware_lux", corrected_max),
                    ("lux_attenuation_factor", factor),
                    ("cal_bare_lux", bare),
                    ("cal_taped_lux", taped),
                    ("cal_timestamp", str(time.time()))
                ]:
                    cur.execute(
                        "INSERT INTO device_config (key, value) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (k, v)
                    )
                conn.commit()
                cur.close()
                conn.close()
                
                calibration_state["phase"] = "done"
                return {"status": "cal_complete", "factor": factor, "max_lux": corrected_max}
            except Exception as e:
                logger.error(f"Error parsing CALRESULT: {e}")
                return {"status": "error_calresult"}

        parts = data.csv_line.split(',')
        if len(parts) < 7: return {"status": "error_format"}
        
        # Parsing Data (legacy prefix remains unchanged)
        telemetry = parse_telemetry(data.csv_line)
        total_time = telemetry["total_time"]
        phase_time = telemetry["phase_time"]
        cycle_num = telemetry["cycle_num"]
        state_code = telemetry["state_code"]
        ir_temp = telemetry["ir_temp"]
        tc_temp = telemetry["tc_temp"]
        current_lux = telemetry["current_lux"]
        
        state_label = STATE_LABELS[state_code] if 0 <= state_code < len(STATE_LABELS) else "UNKNOWN"

        # 1. Masukkan ke Buffer (Agar Grafik Live tetap jalan untuk Monitoring IDLE)
        # Data IDLE tetap masuk ke sini supaya user bisa liat suhu sebelum start
        # Calibration data ALSO goes here so the calibration page live chart works
        new_data = {
            "total_time": total_time,
            "phase_time": phase_time,
            "cycle_num": cycle_num,
            "state_code": state_code,
            "state_label": state_label,
            "ir_temp": ir_temp,
            "tc_temp": tc_temp,
            "current_lux": current_lux,
            **{key: telemetry[key] for key in ("mode", "control_temp", "temp_setpoint", "temp_error", "lamp_pwm", "hold_wall_elapsed_s", "hold_qualified_elapsed_s", "qualified", "detected_plateau_temp")}
        }
        
        recent_sensors_cache.append(new_data)
        # deque(maxlen=20) otomatis buang data lama

        # Track calibration lux readings (backup detection if CALBARE/CALTAPE messages are lost)
        if state_code in (6, 7, 8):
            calibration_state["last_cal_lux"] = current_lux
            calibration_state["last_cal_state"] = state_code
            return {"status": "cal_live_only"}
        
        # Fallback: detect calibration phase completion via state transition
        # When Arduino finishes a cal phase, state drops from CAL_x (6/7/8) back to IDLE (0)
        # If the dedicated CALBARE/CALTAPE message was lost, we catch it here
        if state_code == 0 and calibration_state.get("last_cal_state") is not None:
            last_cal = calibration_state.pop("last_cal_state", None)
            last_lux = calibration_state.pop("last_cal_lux", None)
            
            if last_cal == 6 and calibration_state["phase"] != "bare_done" and last_lux:
                # CAL_BARE just finished, CALBARE message was likely lost
                calibration_state["phase"] = "bare_done"
                calibration_state["bare_lux"] = last_lux
                logger.info(f"Fallback: bare calibration detected via state transition. Lux={last_lux}")
            elif last_cal == 7 and calibration_state["phase"] != "tape_done" and last_lux:
                # CAL_TAPE just finished
                bare = calibration_state.get("bare_lux")
                if bare and bare > 0:
                    factor = bare / last_lux if last_lux > 0 else 1.0
                    calibration_state["phase"] = "tape_done"
                    calibration_state["taped_lux"] = last_lux
                    calibration_state["factor"] = factor
                    logger.info(f"Fallback: tape calibration detected. Lux={last_lux}, factor={factor}")
        
        # 2. LOGIKA PENYIMPANAN DATABASE (FILTER KETAT)
        if current_experiment_id: 
            
            # [FILTER] Data IDLE tidak disimpan ke DB
            if state_label == "IDLE":
                return {"status": "ignored_idle_data"}

            # [FITUR] Deteksi DONE → Finalisasi eksperimen di DB
            if state_label == "DONE":
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("UPDATE experiments SET status='COMPLETED', ended_at=NOW() WHERE id=%s", (current_experiment_id,))
                conn.commit()
                cur.close()
                conn.close()
                logger.info(f"Experiment #{current_experiment_id} COMPLETED.")
                current_experiment_id = None
                return {"status": "experiment_completed"}

            if state_label == "ABORTED":
                conn = get_db_connection(); cur = conn.cursor()
                cur.execute("UPDATE experiments SET status='ABORTED', completion_reason='FIRMWARE_ABORT', ended_at=NOW() WHERE id=%s", (current_experiment_id,))
                conn.commit(); cur.close(); conn.close()
                current_experiment_id = None
                return {"status": "experiment_aborted"}

            # Jika status Valid (PRE_HEAT s/d STABILIZING), Simpan!
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sensor_logs 
                (experiment_id, total_time, phase_time, cycle_num, state_code, state_label, ir_temp, tc_temp, current_lux,
                 mode, control_temp, temp_setpoint, temp_error, lamp_pwm, hold_wall_elapsed_s, hold_qualified_elapsed_s, qualified, detected_plateau_temp)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (current_experiment_id, total_time, phase_time, cycle_num, state_code, state_label, ir_temp, tc_temp, current_lux,
                  telemetry["mode"], telemetry["control_temp"], telemetry["temp_setpoint"], telemetry["temp_error"], telemetry["lamp_pwm"],
                  telemetry["hold_wall_elapsed_s"], telemetry["hold_qualified_elapsed_s"], telemetry["qualified"], telemetry["detected_plateau_temp"]))
            if telemetry["mode"]:
                cur.execute("UPDATE experiments SET hold_qualified_progress=%s, detected_plateau_temperature=COALESCE(%s, detected_plateau_temperature) WHERE id=%s",
                            (telemetry["hold_qualified_elapsed_s"], telemetry["detected_plateau_temp"], current_experiment_id))
            conn.commit()
            cur.close()
            conn.close()
            return {"status": "saved"}
        
        return {"status": "live_only"}
    except Exception as e:
        print(f"Error insert: {e}")
        return {"status": "error"}

# --- HISTORY & EXPORT API ---
@app.get("/api/experiments")
def list_experiments():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, operator_name, sample_name, started_at, status, mode, illumination_mode, target_lux, target_temperature, hold_duration_s, detected_plateau_temperature, hold_qualified_progress, completion_reason FROM experiments ORDER BY id DESC")
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results

@app.get("/api/experiment/{exp_id}")
def get_experiment_data(exp_id: int):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT total_time, phase_time, cycle_num, state_label, ir_temp, tc_temp, current_lux, mode, control_temp, temp_setpoint, temp_error, lamp_pwm, hold_wall_elapsed_s, hold_qualified_elapsed_s, qualified, detected_plateau_temp
        FROM sensor_logs 
        WHERE experiment_id = %s 
        ORDER BY id ASC
    """, (exp_id,))
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results

@app.get("/api/export/{exp_id}")
def export_csv(exp_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT sample_name, operator_name, started_at FROM experiments WHERE id = %s", (exp_id,))
    info = cur.fetchone()
    if not info: raise HTTPException(404, "Not Found")
    
    filename = f"{info[0]}_{info[1]}.csv".replace(" ", "_")
    cur.execute("SELECT s.total_time, s.phase_time, s.cycle_num, s.state_label, s.ir_temp, s.tc_temp, s.current_lux, s.recorded_at, s.mode, s.control_temp, s.temp_setpoint, s.temp_error, s.lamp_pwm, s.hold_wall_elapsed_s, s.hold_qualified_elapsed_s, s.qualified, s.detected_plateau_temp, e.illumination_mode, e.target_lux FROM sensor_logs s JOIN experiments e ON e.id=s.experiment_id WHERE s.experiment_id = %s ORDER BY s.id ASC", (exp_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["TotalTime", "PhaseTime", "Cycle", "State", "IR_Temp", "TC_Temp", "Lux", "Recorded At", "Mode", "ControlTemp", "TempSetpoint", "TempError", "LampPWM", "HoldWallElapsedS", "HoldQualifiedElapsedS", "Qualified", "DetectedPlateauTemp", "IlluminationMode", "TargetLux"])
    writer.writerows(rows)
    output.seek(0)
    
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.post("/api/calibrate_tape")
def trigger_calibrate_tape(phase: str = "bare"):
    """
    Start a calibration phase.
    phase: "bare" | "tape" | "full"
    """
    global pending_command, calibration_state
    
    cmd_map = {"bare": "CAL_BARE", "tape": "CAL_TAPE", "full": "CAL_FULL"}
    if phase not in cmd_map:
        raise HTTPException(400, "Invalid phase. Use: bare, tape, full")
    
    pending_command = cmd_map[phase]
    calibration_state["phase"] = phase + "_running"
    return {"status": "calibrating", "phase": phase}

@app.get("/api/calibration_status")
def get_calibration_status():
    """Returns current calibration state + stored config."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT key, value FROM device_config")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    config = {row["key"]: row["value"] for row in rows}
    return {"state": calibration_state, "config": config}

@app.get("/api/get_config")
def get_config():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT key, value FROM device_config")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {row["key"]: row["value"] for row in rows}
