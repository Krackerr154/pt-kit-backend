# Lux Control & Calibration Feature Update

## Date: 2026-04-13

## Summary
Significantly overhauled the architecture to support dynamic lighting control. Migrated the legacy ON/OFF relay switch to an AOD4184 MOSFET capable of fine-grained PWM Dimming. Integrated the GY-302 (BH1750) ambient light sensor on the I2C bus to measure irradiance in real-time. Added an intelligent Max Lux calibration routine and a closed-loop PI controller to combat temperature-induced LED drooping.

## Key Changes

### 1. **Hardware Migration** ✅
- **Relay ➔ MOSFET:** Moved lamp mapping from unmodifiable `Pin 2` relay digital output down to `Pin 5` PWM-capable output.
- **GY-302 Addition:** Safely bound the BH1750 component to the shared A4/A5 I2C layout.

### 2. **Signal Filtering & Stabilization**
- **Exponential Moving Average (EMA):** Replaced raw bouncing optical integers with an EMA (`α = 0.2`) rendering jitter practically negligible.
- **PID Deadband Control:** Active `HEATING` states now compare `TargetLux` to `currentLux` across a `±50 lx` deadband, applying proportional shifts only when necessary.

### 3. **Droop-Aware Absolute Calibration** 
- **The Protocol:** New `CALIBRATING` Arduino sequence fully saturates PWM at `255`, locking the system down while monitoring dropping sensor values.
- **Stable Plateau Check:** Employs a sliding-window algorithm that confirms thermal equilibrium only when the light index changes less than `1%` over `10 seconds`.
- **EEPROM Storage:** Limits successfully logged seamlessly into persistent unpowered memory preventing user abuse.

### 4. **Backend Modifications (FastAPI & PostgreSQL)**
- Modified `app/main.py` altering tables `experiments` and `sensor_logs` pushing constraints for the appended parameter `target_lux` and `current_lux`.
- Constructed `device_config` dictionary matrix binding Hardware Max Lux.
- Buffer on ESP32 extended to comfortably gulp up to `128 Bytes` for expanded array limits.

### 5. **Frontend Dashboard UI Evolution**
- Added **Target Lux** into the Dashboard parameters setup form.
- Stretched the core telemetry grid spanning 5 visual items adding LIVE LUX metrics.
- Created standalone page widget `/static/calibration.html` incorporating real-time mathematical slope graphing using Chart.js.
