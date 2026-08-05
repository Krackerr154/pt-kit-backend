"""Throwaway mock API for frontend smoke testing (no DB). Serves app/static + stub /api."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).parent / "app" / "static"
STATE = {"connected": False, "t0": time.time()}
# Fake calibration flow: each phase auto-completes 3s after it starts.
CAL = {"phase": "idle", "started": 0.0, "bare_lux": None, "taped_lux": None, "factor": None}

MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".ico": "image/x-icon"}


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
        if path == "/":
            path = "/index.html"
        if path == "/api/current_status":
            if not STATE["connected"]:
                return self._send(200, json.dumps({"active_experiment": None, "recent_data": []}))
            t = int(time.time() - STATE["t0"])
            sample = {"total_time": t, "state_code": 0, "cycle_num": 0, "ir_temp": 31.5, "tc_temp": 30.8, "current_lux": 1200}
            return self._send(200, json.dumps({"active_experiment": None, "recent_data": [sample]}))
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
            STATE["connected"] = not STATE["connected"]
            STATE["t0"] = time.time()
            return self._send(200, json.dumps({"connected": STATE["connected"]}))
        f = STATIC / path.lstrip("/").replace("static/", "", 1) if "static" in path else STATIC / path.lstrip("/")
        if f.is_file() and f.suffix in MIME:
            return self._send(200, f.read_bytes(), MIME[f.suffix])
        return self._send(404, json.dumps({"detail": "not found"}))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/calibrate_tape":
            from urllib.parse import urlparse, parse_qs
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
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
