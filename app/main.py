from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
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

# --- MODELS ---
class ExperimentConfig(BaseModel):
    operator_name: str 
    sample_name: str
    description: str = ""
    duration: int = 60
    cycles: int = 5
    max_temp: float = 80.0
    interval: int = 1
    target_lux: float = 5000.0

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
            status VARCHAR(20) DEFAULT 'WAITING',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP
        );
    """)
    cur.execute("ALTER TABLE experiments ADD COLUMN IF NOT EXISTS target_lux FLOAT DEFAULT 0;")
    
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
    
    # [FITUR] Reset Grafik di Memori Server saat Start
    recent_sensors_cache.clear()
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO experiments 
        (operator_name, sample_name, description, target_duration, target_cycles, max_temp, log_interval, target_lux, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'WAITING') RETURNING id
    """, (config.operator_name, config.sample_name, config.description, config.duration, config.cycles, config.max_temp, config.interval, config.target_lux))
    
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    
    current_experiment_id = new_id
    pending_command = f"SET:{config.duration}:{config.cycles}:{config.max_temp}:{config.interval}:{config.target_lux}"
    
    return {"status": "success", "id": new_id}

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

        parts = data.csv_line.split(',')
        if len(parts) < 7: return {"status": "error_format"}
        
        # Parsing Data
        total_time = int(parts[0])
        phase_time = int(parts[1])
        cycle_num  = int(parts[2])
        state_code = int(parts[3])
        ir_temp    = float(parts[4])
        tc_temp    = float(parts[5])
        current_lux = float(parts[6])
        
        states = ["IDLE", "PRE_HEAT", "HEATING", "COOLING", "STABILIZING", "DONE"]
        state_label = states[state_code] if 0 <= state_code < len(states) else "UNKNOWN"

        # 1. Masukkan ke Buffer (Agar Grafik Live tetap jalan untuk Monitoring IDLE)
        # Data IDLE tetap masuk ke sini supaya user bisa liat suhu sebelum start
        new_data = {
            "total_time": total_time,
            "phase_time": phase_time,
            "cycle_num": cycle_num,
            "state_code": state_code,
            "state_label": state_label,
            "ir_temp": ir_temp,
            "tc_temp": tc_temp,
            "current_lux": current_lux
        }
        
        recent_sensors_cache.append(new_data)
        # deque(maxlen=20) otomatis buang data lama
        
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

            # Jika status Valid (PRE_HEAT s/d STABILIZING), Simpan!
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO sensor_logs 
                (experiment_id, total_time, phase_time, cycle_num, state_code, state_label, ir_temp, tc_temp, current_lux)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (current_experiment_id, total_time, phase_time, cycle_num, state_code, state_label, ir_temp, tc_temp, current_lux))
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
    cur.execute("SELECT id, operator_name, sample_name, started_at, status FROM experiments ORDER BY id DESC")
    results = cur.fetchall()
    cur.close()
    conn.close()
    return results

@app.get("/api/experiment/{exp_id}")
def get_experiment_data(exp_id: int):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT total_time, phase_time, cycle_num, state_label, ir_temp, tc_temp, current_lux 
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
    cur.execute("SELECT total_time, phase_time, cycle_num, state_label, ir_temp, tc_temp, current_lux, recorded_at FROM sensor_logs WHERE experiment_id = %s ORDER BY id ASC", (exp_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["TotalTime", "PhaseTime", "Cycle", "State", "IR_Temp", "TC_Temp", "Lux", "Recorded At"])
    writer.writerows(rows)
    output.seek(0)
    
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})

@app.post("/api/calibrate_lux")
def trigger_calibrate_lux():
    global pending_command
    pending_command = "CAL_LUX"
    return {"status": "calibrating"}

@app.get("/api/get_config")
def get_config():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT key, value FROM device_config")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {row["key"]: row["value"] for row in rows}
