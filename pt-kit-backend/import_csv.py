import csv
import psycopg2
import os

# --- KONFIGURASI ---
CSV_FILENAME = 'data_import.csv'  
SAMPLE_NAME = 'Simulation Data [Import]'
OPERATOR_NAME = 'Gerald (Import)'

# --- KONEKSI DB ---
DB_HOST = 'db'
DB_NAME = 'ptkit_db'
DB_USER = 'ptkit_user'
DB_PASS = 'pt154'

# --- MAP STATUS (harus sinkron dengan main.py states array) ---
STATE_MAP = {
    'IDLE': 0,
    'PRE_HEAT': 1, 'PRE-HEAT': 1,   # Support kedua format
    'HEATING': 2,
    'COOLING': 3,
    'STABILIZING': 4,
    'DONE': 5
}

def main():
    print(f"🚀 IMPORT V5 (FIXED): {CSV_FILENAME}")
    try:
        conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
        conn.autocommit = True
        cur = conn.cursor()

        # 1. INSERT EKSPERIMEN
        print("1️⃣  Buat Header Eksperimen...")
        # Perhatikan kolom: status, started_at (tanpa stopped_at/ended_at dulu biar aman)
        cur.execute("""
            INSERT INTO experiments (sample_name, operator_name, status, started_at)
            VALUES (%s, %s, 'STOPPED', NOW())
            RETURNING id;
        """, (SAMPLE_NAME, OPERATOR_NAME))
        exp_id = cur.fetchone()[0]
        print(f"   ✅ ID Baru: #{exp_id}")

        # 2. INSERT SENSOR LOGS
        print("2️⃣  Input Data Sensor...")
        if not os.path.exists(CSV_FILENAME):
            print("❌ File CSV tidak ditemukan!")
            return

        with open(CSV_FILENAME, 'r') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    state_code = STATE_MAP.get(row['State'], 0)
                    
                    # FIX: Pakai 'recorded_at' bukan 'created_at'
                    cur.execute("""
                        INSERT INTO sensor_logs 
                        (experiment_id, total_time, phase_time, cycle_num, state_code, state_label, ir_temp, tc_temp, recorded_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (exp_id, row['TotalTime'], row['PhaseTime'], row['Cycle'], state_code, row['State'], row['IR_Temp'], row['TC_Temp']))
                    
                    count += 1
                    if count % 1000 == 0: print(f"   ... {count} data")
                except Exception as e:
                    print(f"❌ Error Baris: {e}")
                    break

        print(f"\n🎉 SUKSES! {count} data masuk ke ID #{exp_id}")
        conn.close()

    except Exception as e:
        print(f"\n❌ ERROR SYSTEM: {e}")

if __name__ == "__main__":
    main()
