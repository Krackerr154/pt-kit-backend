import csv
import random
import math

# ==========================================
# 🎛️ PANEL KONTROL SIMULASI
# ==========================================

FILENAME = "simulasi_fototermal_fisika.csv"
CYCLES = 10              

# --- 1. SETTING DASAR ---
ROOM_TEMP = 28.0         
TARGET_CUTOFF = 80.0     
HOLD_TIME = 20           
COOL_UNTIL_DELTA = 3.0   

# --- 2. FISIKA ALAT (DIPERKUAT BIAR SAMPAI TARGET) ---
# REVISI: Power dinaikkan dari 2.5 ke 4.5 supaya kuat naik sampai 80 derajat
BASE_LASER_POWER = 4.5   
BASE_ABSORBANCE = 0.85   
HEAT_CAPACITY = 12.0     
# REVISI: Loss coeff dikecilkan dikit biar gak bocor parah
HEAT_LOSS_COEFF = 0.04   

# --- 3. FAKTOR SEBARAN ---
DEGRADATION_RATE = 0.005  
ACCUMULATION_RATE = 0.15  
LASER_NOISE_PERCENT = 0.02 

# ==========================================

def generate_sensor_noise():
    return random.uniform(-0.15, 0.15)

def main():
    print(f"🚀 Generasi Data Anti-Stuck...")
    
    total_time = 0
    tc_buffer = [ROOM_TEMP] * 6 

    with open(FILENAME, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["TotalTime", "PhaseTime", "Cycle", "State", "IR_Temp", "TC_Temp", "SaveFlag"])
        
        current_temp = ROOM_TEMP 

        for cycle in range(1, CYCLES + 1):
            
            # Variabel Dinamis
            actual_absorbance = BASE_ABSORBANCE * (1 - (cycle * DEGRADATION_RATE))
            actual_power = BASE_LASER_POWER * random.gauss(1, LASER_NOISE_PERCENT)
            
            start_temp_cycle = ROOM_TEMP + (cycle * ACCUMULATION_RATE)
            current_temp = max(current_temp, start_temp_cycle)
            
            print(f"   ⚙️ Siklus {cycle}: Start={current_temp:.2f}°C -> Target={TARGET_CUTOFF}°C")

            # === FASE 1: HEATING ===
            state = "HEATING"
            phase_time = 0
            
            # Loop dengan TARGET CUTOFF
            while current_temp < TARGET_CUTOFF:
                Q_in = actual_power * actual_absorbance
                Q_out = HEAT_LOSS_COEFF * (current_temp - ROOM_TEMP)
                dT = (Q_in - Q_out) / HEAT_CAPACITY
                
                current_temp += dT  
                
                ir_val = current_temp + generate_sensor_noise()
                
                tc_buffer.append(current_temp - random.uniform(1.0, 2.5)) 
                tc_buffer.pop(0)
                tc_val = sum(tc_buffer) / len(tc_buffer)
                
                writer.writerow([total_time, phase_time, cycle, state, round(ir_val, 2), round(tc_val, 2), 1])
                total_time += 1
                phase_time += 1

                # --- PENGAMAN ANTI STUCK (TIMEOUT) ---
                # Jika sudah 1000 detik (16 menit) gak nyampe-nyampe, paksa stop fase ini
                if phase_time > 1000:
                    print(f"      ⚠️ Warning: Siklus {cycle} timeout (Gak kuat naik)! Force lanjut.")
                    break

            # === FASE 2: HOLDING ===
            state = "STABILIZING"
            target_hold = current_temp 
            
            for _ in range(HOLD_TIME):
                wobble = math.sin(phase_time * 0.6) * 0.4
                actual = target_hold + wobble + generate_sensor_noise()
                
                tc_buffer.append(actual)
                tc_buffer.pop(0)
                tc_val = sum(tc_buffer) / len(tc_buffer)
                
                writer.writerow([total_time, phase_time, cycle, state, round(actual, 2), round(tc_val, 2), 1])
                total_time += 1
                phase_time += 1

            # === FASE 3: COOLING ===
            state = "COOLING"
            phase_time = 0
            target_cool = start_temp_cycle + COOL_UNTIL_DELTA
            
            while current_temp > target_cool:
                Q_in = 0 
                Q_out = HEAT_LOSS_COEFF * (current_temp - ROOM_TEMP)
                dT = (Q_in - Q_out) / HEAT_CAPACITY
                
                current_temp += dT
                
                ir_val = current_temp + generate_sensor_noise()
                tc_buffer.append(current_temp + random.uniform(0.5, 1.5))
                tc_buffer.pop(0)
                tc_val = sum(tc_buffer) / len(tc_buffer)

                writer.writerow([total_time, phase_time, cycle, state, round(ir_val, 2), round(tc_val, 2), 1])
                total_time += 1
                phase_time += 1
                
                # Timeout Cooling juga (biar gak stuck kalau target cool terlalu rendah)
                if phase_time > 1000: break

            # === FASE 4: IDLE ===
            state = "IDLE"
            for _ in range(5): 
                base = current_temp + generate_sensor_noise()
                writer.writerow([total_time, phase_time, cycle, state, round(base, 2), round(base, 2), 1])
                total_time += 1
                phase_time += 1

    print(f"\n✅ Data Siap: {FILENAME}")

if __name__ == "__main__":
    main()
