"""Throwaway mock API for frontend smoke testing (no DB).

Serves app/static + stub /api, and includes a *virtual ESP32* — a stateful
in-memory simulator that walks the real firmware state machine so the RUNNING
UI (chart, phase/cycle telemetry, elapsed timer, log lines, completion panel)
can be exercised without hardware or a database.

The simulator is cosmetic: temperature/lux curves are plausible, not a real
thermal model, and time is accelerated by SIM_SPEED so a run finishes in
seconds. State codes come from app.protocol.STATE_LABELS so they cannot drift
from the real backend/firmware.
"""
import json
import math
import os
import random
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Reuse the real wire definitions so the sim can never drift from firmware codes.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from app.protocol import STATE_LABELS, ExperimentMode
except Exception:  # pragma: no cover - fallback keeps the mock standalone
    STATE_LABELS = [
        "IDLE", "PRE_HEAT", "HEATING", "COOLING", "STABILIZING", "DONE",
        "CAL_BARE", "CAL_TAPE", "CAL_FULL", "ISO_RAMP", "ISO_QUALIFY",
        "ISO_HOLD", "PLATEAU_HEATING", "PLATEAU_CONFIRM", "PLATEAU_HOLD", "ABORTED",
    ]

    class ExperimentMode:  # minimal shim
        NORMAL_CYCLIC = type("E", (), {"value": "NORMAL_CYCLIC"})()
        FIXED_TEMPERATURE = type("E", (), {"value": "FIXED_TEMPERATURE"})()
        NATURAL_PLATEAU = type("E", (), {"value": "NATURAL_PLATEAU"})()

CODE = {label: i for i, label in enumerate(STATE_LABELS)}  # label -> state_code

STATIC = Path(__file__).parent / "app" / "static"
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
        ".png": "image/png", ".ico": "image/x-icon"}

# Ambient (idle) readings the device streams when connected but not running.
AMBIENT = {"ir_temp": 31.5, "tc_temp": 30.8, "current_lux": 1200}

# --- Fake calibration flow (unchanged behaviour): phases auto-complete after 3s.
CAL = {"phase": "idle", "started": 0.0, "bare_lux": None, "taped_lux": None, "factor": None}


class VirtualESP32:
    """A tiny state-machine that emits telemetry samples like the real firmware.

    Thread-safe: a background ticker advances the run; HTTP handlers read/mutate
    under a lock. Everything lives in memory — no DB, matching the mock's design.
    """

    def __init__(self, speed=None):
        self.lock = threading.RLock()
        self.connected = False
        # speed multiplier: sim seconds advance this many x wall seconds.
        env_speed = os.environ.get("SIM_SPEED")
        self.speed = float(speed if speed is not None else (env_speed or 8.0))
        self._reset_idle()
        self.exp = None            # active experiment dict (mirrors DB row shape)
        self._next_id = 1
        self._last_wall = time.time()

    # ---- lifecycle -------------------------------------------------------
    def _reset_idle(self):
        self.state = "IDLE"
        self.sim_t = 0.0           # accelerated seconds since run/connect start
        self.phase_t = 0.0
        self.cycle = 0
        self.plan = None           # per-run plan (durations, targets)
        self.qualified_elapsed = 0.0
        self.done_dwell = 0.0      # sim-seconds held in DONE before auto-reset

    def set_connected(self, value):
        with self.lock:
            self.connected = bool(value)
            if not self.connected:
                self.exp = None
                self._reset_idle()
            return self.connected

    def set_speed(self, x):
        with self.lock:
            self.speed = max(0.1, min(60.0, float(x)))
            return self.speed

    def start(self, cfg):
        """Begin a virtual run. cfg is the parsed /api/start_experiment body."""
        with self.lock:
            if not self.connected:
                return None, 409, "ESP32 disconnected; reconnect device before starting"
            mode = cfg.get("mode", "NORMAL_CYCLIC")
            eid = self._next_id
            self._next_id += 1
            # Plan drives the state machine. All times are in *sim* seconds.
            self.plan = self._build_plan(mode, cfg)
            self.exp = {
                "id": eid, "status": "WAITING", "mode": mode,
                "operator_name": cfg.get("operator_name"), "sample_name": cfg.get("sample_name"),
                "illumination_mode": cfg.get("illumination_mode", "TARGET_LUX"),
                "target_lux": cfg.get("target_lux"), "target_temperature": cfg.get("target_temperature"),
                "max_temp": cfg.get("max_temp"), "target_cycles": cfg.get("cycles"),
                "target_duration": cfg.get("duration"),
            }
            self.sim_t = 0.0
            self.phase_t = 0.0
            self.cycle = 1 if mode == "NORMAL_CYCLIC" else 0
            self.qualified_elapsed = 0.0
            self.state = {"NORMAL_CYCLIC": "PRE_HEAT",
                          "FIXED_TEMPERATURE": "ISO_RAMP",
                          "NATURAL_PLATEAU": "PLATEAU_HEATING"}.get(mode, "PRE_HEAT")
            return eid, 200, mode

    def stop(self):
        with self.lock:
            if self.exp:
                self.exp["status"] = "STOPPED"
            self.exp = None
            self._reset_idle()

    def _build_plan(self, mode, cfg):
        def num(key, default):
            try:
                v = cfg.get(key)
                return float(v) if v is not None else float(default)
            except (TypeError, ValueError):
                return float(default)
        if mode == "FIXED_TEMPERATURE":
            return {"ramp_s": 8.0, "qualify_s": 6.0,
                    "hold_s": max(4.0, num("hold_duration_s", 600) / 60.0),  # minutes->compressed
                    "target": num("target_temperature", 60), "tol": num("temperature_tolerance", 1)}
        if mode == "NATURAL_PLATEAU":
            return {"rise_s": 10.0, "confirm_s": max(2.0, num("plateau_confirmation_s", 60) / 20.0),
                    "hold_s": max(4.0, num("hold_duration_s", 600) / 60.0),
                    "target": 55.0}
        # NORMAL_CYCLIC
        return {"pre_s": 4.0, "cycles": int(num("cycles", 5)),
                "heat_s": max(3.0, num("duration", 60) / 12.0),
                "cool_s": max(2.0, num("duration", 60) / 16.0)}

    # ---- ticking ---------------------------------------------------------
    def tick(self):
        """Advance the simulation by wall-elapsed * speed sim-seconds."""
        with self.lock:
            now = time.time()
            dt = (now - self._last_wall) * self.speed
            self._last_wall = now
            if not self.connected:
                return
            # After a run finishes, dwell briefly in DONE then reset to IDLE,
            # mimicking the real "Arduino/ESP32 reset" the UI waits for.
            if self.state in ("DONE", "ABORTED"):
                self.done_dwell += dt
                if self.done_dwell >= 8.0:
                    self.exp = None
                    self._reset_idle()
                return
            if not self.exp or self.state == "IDLE":
                return
            self.sim_t += dt
            self.phase_t += dt
            p = self.plan
            m = self.exp["mode"]
            if m == "NORMAL_CYCLIC":
                self._tick_normal(p)
            elif m == "FIXED_TEMPERATURE":
                self._tick_fixed(p)
            elif m == "NATURAL_PLATEAU":
                self._tick_plateau(p)

    def _advance(self, new_state):
        self.state = new_state
        self.phase_t = 0.0

    def _tick_normal(self, p):
        if self.state == "PRE_HEAT" and self.phase_t >= p["pre_s"]:
            self._advance("HEATING")
        elif self.state == "HEATING" and self.phase_t >= p["heat_s"]:
            self._advance("COOLING")
        elif self.state == "COOLING" and self.phase_t >= p["cool_s"]:
            if self.cycle >= p["cycles"]:
                self._advance("DONE")
            else:
                self.cycle += 1
                self._advance("HEATING")

    def _tick_fixed(self, p):
        if self.state == "ISO_RAMP" and self.phase_t >= p["ramp_s"]:
            self._advance("ISO_QUALIFY")
        elif self.state == "ISO_QUALIFY" and self.phase_t >= p["qualify_s"]:
            self._advance("ISO_HOLD")
        elif self.state == "ISO_HOLD":
            self.qualified_elapsed += 0  # advanced in sample()
            if self.phase_t >= p["hold_s"]:
                self._advance("DONE")

    def _tick_plateau(self, p):
        if self.state == "PLATEAU_HEATING" and self.phase_t >= p["rise_s"]:
            self._advance("PLATEAU_CONFIRM")
        elif self.state == "PLATEAU_CONFIRM" and self.phase_t >= p["confirm_s"]:
            self._advance("PLATEAU_HOLD")
        elif self.state == "PLATEAU_HOLD" and self.phase_t >= p["hold_s"]:
            self._advance("DONE")

    # ---- telemetry -------------------------------------------------------
    def sample(self):
        """Return one telemetry sample dict in the shape the frontend reads."""
        with self.lock:
            code = CODE.get(self.state, 0)
            base = dict(total_time=int(self.sim_t), phase_time=int(self.phase_t),
                        cycle_num=self.cycle, state_code=code, state_label=self.state,
                        ir_temp=AMBIENT["ir_temp"], tc_temp=AMBIENT["tc_temp"],
                        current_lux=AMBIENT["current_lux"], mode=None, control_temp=None,
                        temp_setpoint=None, temp_error=None, lamp_pwm=None,
                        hold_wall_elapsed_s=None, hold_qualified_elapsed_s=None,
                        qualified=None, detected_plateau_temp=None)
            if not self.exp or self.state == "IDLE":
                # Light jitter so idle monitoring looks live, not frozen.
                base["ir_temp"] = round(AMBIENT["ir_temp"] + random.uniform(-0.3, 0.3), 2)
                base["tc_temp"] = round(AMBIENT["tc_temp"] + random.uniform(-0.3, 0.3), 2)
                base["current_lux"] = round(AMBIENT["current_lux"] + random.uniform(-40, 40))
                return base
            p, m = self.plan, self.exp["mode"]
            base["mode"] = m
            lux = self.exp.get("target_lux") or AMBIENT["current_lux"]
            if m == "NORMAL_CYCLIC":
                # sawtooth around ambient..target
                lo, hi = 30.0, float(self.exp.get("max_temp") or 80) * 0.8
                if self.state == "HEATING":
                    frac = min(1.0, self.phase_t / max(0.1, p["heat_s"]))
                    temp = lo + (hi - lo) * frac
                elif self.state == "COOLING":
                    frac = min(1.0, self.phase_t / max(0.1, p["cool_s"]))
                    temp = hi - (hi - lo) * frac
                else:
                    temp = lo
                base.update(ir_temp=round(temp + 0.6, 2), tc_temp=round(temp, 2),
                            current_lux=lux, lamp_pwm=100.0 if self.state == "HEATING" else 0.0)
            elif m == "FIXED_TEMPERATURE":
                target = p["target"]
                if self.state == "ISO_RAMP":
                    temp = 30.0 + (target - 30.0) * min(1.0, self.phase_t / p["ramp_s"])
                else:
                    temp = target + math.sin(self.sim_t) * (p["tol"] * 0.4)
                if self.state == "ISO_HOLD":
                    self.qualified_elapsed = self.phase_t
                base.update(ir_temp=round(temp + 0.4, 2), tc_temp=round(temp, 2),
                            control_temp=round(temp, 2), temp_setpoint=target,
                            temp_error=round(temp - target, 2), lamp_pwm=70.0,
                            qualified=self.state in ("ISO_QUALIFY", "ISO_HOLD"),
                            hold_qualified_elapsed_s=int(self.qualified_elapsed),
                            hold_wall_elapsed_s=int(self.phase_t) if self.state == "ISO_HOLD" else 0,
                            current_lux=lux)
            elif m == "NATURAL_PLATEAU":
                target = p["target"]
                if self.state == "PLATEAU_HEATING":
                    temp = 30.0 + (target - 30.0) * (1 - math.exp(-3 * self.phase_t / p["rise_s"]))
                    detected = None
                else:
                    temp = target + math.sin(self.sim_t) * 0.2
                    detected = round(target, 2)
                base.update(ir_temp=round(temp + 0.5, 2), tc_temp=round(temp, 2),
                            control_temp=round(temp, 2), detected_plateau_temp=detected,
                            lamp_pwm=100.0, current_lux=lux,
                            hold_qualified_elapsed_s=int(self.phase_t) if self.state == "PLATEAU_HOLD" else 0)
            return base

    def status_payload(self):
        with self.lock:
            if not self.connected:
                return {"active_experiment": None, "recent_data": []}
            exp = None
            if self.exp:
                exp = dict(self.exp)
                # Reflect terminal state so the UI's status checks stay consistent.
                if self.state == "DONE":
                    exp["status"] = "COMPLETED"
                elif self.state == "ABORTED":
                    exp["status"] = "ABORTED"
            return {"active_experiment": exp, "recent_data": [self.sample()]}


DEV = VirtualESP32()


def _ticker():
    while True:
        DEV.tick()
        time.sleep(0.25)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        query = parse_qs(urlparse(self.path).query)
        if path == "/":
            path = "/index.html"
        elif path == "/history":
            path = "/history.html"
        elif path in ("/preview", "/device-preview"):
            path = "/device-preview.html"
        if path == "/api/current_status":
            return self._send(200, json.dumps(DEV.status_payload()))
        if path == "/api/get_config":
            return self._send(200, json.dumps({"max_hardware_lux": 50000, "lux_attenuation_factor": 2.5, "cal_timestamp": 1754200000}))
        if path == "/api/calibration_status":
            if CAL["phase"].endswith("_running") and time.time() - CAL["started"] > 3:
                done = CAL["phase"].replace("_running", "_done")
                if done == "bare_done":
                    CAL.update(phase="bare_done", bare_lux=25000.0)
                elif done == "tape_done":
                    CAL.update(phase="tape_done", taped_lux=5000.0, factor=5.0)
                elif done == "full_done":
                    CAL["phase"] = "done"
            config = {"max_hardware_lux": 55000, "lux_attenuation_factor": CAL["factor"] or 2.5,
                      "cal_timestamp": int(time.time()) if CAL["phase"] == "done" else 1754200000}
            state = {"phase": CAL["phase"], "bare_lux": CAL["bare_lux"], "taped_lux": CAL["taped_lux"], "factor": CAL["factor"]}
            return self._send(200, json.dumps({"state": state, "config": config}))
        if path == "/api/archive/count":
            return self._send(200, json.dumps({"count": 3}))
        if path == "/api/toggle_mock":
            connected = DEV.set_connected(not DEV.connected)
            return self._send(200, json.dumps({"connected": connected}))
        if path == "/api/sim_speed":
            # Speed knob: /api/sim_speed?x=8  (GET reads/sets, no body needed)
            x = query.get("x", [None])[0]
            if x is not None:
                DEV.set_speed(x)
            return self._send(200, json.dumps({"speed": DEV.speed}))
        f = STATIC / path.lstrip("/").replace("static/", "", 1) if "static" in path else STATIC / path.lstrip("/")
        if f.is_file() and f.suffix in MIME:
            return self._send(200, f.read_bytes(), MIME[f.suffix])
        return self._send(404, json.dumps({"detail": "not found"}))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/start_experiment":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                cfg = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return self._send(422, json.dumps({"detail": "invalid JSON body"}))
            eid, code, info = DEV.start(cfg)
            if code != 200:
                return self._send(code, json.dumps({"detail": info}))
            return self._send(200, json.dumps({"status": "success", "id": eid, "mode": info,
                                                "illumination_mode": cfg.get("illumination_mode", "TARGET_LUX")}))
        if path == "/api/stop_experiment":
            DEV.stop()
            return self._send(200, json.dumps({"status": "stopped"}))
        if path == "/api/calibrate_tape":
            phase = parse_qs(urlparse(self.path).query).get("phase", ["bare"])[0]
            if phase not in ("bare", "tape", "full"):
                return self._send(400, json.dumps({"detail": "Invalid phase"}))
            CAL["phase"] = phase + "_running"
            CAL["started"] = time.time()
            return self._send(200, json.dumps({"status": "calibrating", "phase": phase}))
        return self._send(404, json.dumps({"detail": "not found"}))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=_ticker, daemon=True).start()
    print(f"Virtual ESP32 mock on http://127.0.0.1:8765  (SIM_SPEED={DEV.speed}x)")
    print("  toggle connect:  GET /api/toggle_mock")
    print("  set speed:       GET /api/sim_speed?x=8")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
