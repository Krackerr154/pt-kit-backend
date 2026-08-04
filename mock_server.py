"""Throwaway mock API for frontend smoke testing (no DB). Serves app/static + stub /api."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).parent / "app" / "static"
STATE = {"connected": False, "t0": time.time()}

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
            return self._send(200, json.dumps({"max_hardware_lux": 50000}))
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

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
