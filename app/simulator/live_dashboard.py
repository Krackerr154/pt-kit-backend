"""Graphical simulator dashboard — live thermal-plant driver + web UI.

This module gives the digital twin a *graphical operator dashboard* (not just
the Swagger API explorer). It:

* drives a real :class:`app.simulator.plant.ThermalPlant` in an async loop,
* applies a simple bang-bang thermostat toward the run's target temperature,
* streams telemetry frames to browser clients over a WebSocket at a fixed rate,
* serves a Chart.js single-page UI styled after the hardware dashboard.

Isolation: this server has NO database and never touches ``/api/insert_data``.
All state is in-memory and per-process, consistent with the Phase 5 isolation
contract. It is meant for local/dev visualization of simulated runs.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .plant import PlantState, ThermalPlant
from .profiles import load_default_profile

_STATIC_DIR = Path(__file__).parent / "static"

# Lamp/fan PWM bounds
_PWM_MAX = 255
_PWM_MIN = 0


class SimState(str, Enum):
    """Lifecycle states for a dashboard-driven simulation run."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class StartRequest(BaseModel):
    """Payload to start a new simulated run."""

    operator_name: str = "operator"
    sample_name: str = "sample"
    target_temp_c: float = 80.0
    duration_s: int = 120
    max_temp_c: float = 120.0
    ambient_temp_c: float = 25.0
    tick_hz: float = 10.0          # simulation steps per second (wall clock)
    speed: float = 1.0            # virtual-seconds per wall-second multiplier


@dataclass
class RunModel:
    """Holds the live plant and derived run state for one simulation."""

    run_id: str
    config: StartRequest
    plant: ThermalPlant
    state: SimState = SimState.IDLE
    virtual_time_s: float = 0.0
    sequence: int = 0
    lamp_pwm: int = 0
    fan_pwm: int = 0
    started_wall_s: float = field(default_factory=time.time)
    history: list[dict[str, Any]] = field(default_factory=list)

    def thermostat(self, target_c: float) -> None:
        """Bang-bang control toward target using surface temperature."""
        surface = self.plant.state.surface_temp_c
        if surface < target_c - 0.5:
            self.lamp_pwm = _PWM_MAX
            self.fan_pwm = _PWM_MIN
        elif surface > target_c + 0.5:
            self.lamp_pwm = _PWM_MIN
            # engage fan proportionally when overshooting
            self.fan_pwm = _PWM_MAX
        else:
            # within deadband: hold a gentle bias to maintain temperature
            self.lamp_pwm = int(_PWM_MAX * 0.35)
            self.fan_pwm = _PWM_MIN

    def frame(self) -> dict[str, Any]:
        """Build a telemetry frame dict from current plant state."""
        st: PlantState = self.plant.state
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "virtual_time_s": round(self.virtual_time_s, 2),
            "state": self.state.value,
            "surface_temp_c": round(st.surface_temp_c, 3),
            "bulk_temp_c": round(st.bulk_temp_c, 3),
            "ambient_temp_c": round(st.ambient_temp_c, 3),
            "lux": round(st.lamp_output_lux, 1),
            "lamp_pwm": self.lamp_pwm,
            "fan_pwm": self.fan_pwm,
            "target_temp_c": self.config.target_temp_c,
            "duration_s": self.config.duration_s,
            "progress_pct": round(
                min(100.0, 100.0 * self.virtual_time_s / max(1e-9, self.config.duration_s)), 1
            ),
            "timestamp_s": round(time.time(), 3),
        }


class LiveDashboardServer:
    """FastAPI app: live plant driver, control endpoints, WebSocket stream, UI."""

    def __init__(self) -> None:
        self.app = FastAPI(title="PT-Kit Simulator Dashboard", version="1.0.0")
        self._runs: dict[str, RunModel] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._clients: dict[str, set[WebSocket]] = {}
        self._profile = load_default_profile()
        if _STATIC_DIR.exists():
            self.app.mount(
                "/sim-static", StaticFiles(directory=str(_STATIC_DIR)), name="sim-static"
            )
        self._setup_routes()

    # ------------------------------------------------------------------
    def _new_plant(self, ambient_c: float) -> ThermalPlant:
        cfg = self._profile.to_plant_config()
        cfg.ambient_temp_c = ambient_c
        return ThermalPlant(cfg)

    async def _run_loop(self, run_id: str) -> None:
        """Background driver: step the plant, broadcast frames until done."""
        run = self._runs[run_id]
        dt = 1.0 / max(0.1, run.config.tick_hz)
        virtual_dt = dt * max(0.1, run.config.speed)
        try:
            while run.state in (SimState.RUNNING, SimState.PAUSED):
                if run.state == SimState.PAUSED:
                    await asyncio.sleep(dt)
                    continue

                run.thermostat(run.config.target_temp_c)
                run.plant.step(run.lamp_pwm, run.fan_pwm, virtual_dt)
                run.virtual_time_s += virtual_dt
                run.sequence += 1

                # Safety abort on over-temperature
                if run.plant.state.surface_temp_c > run.config.max_temp_c:
                    run.state = SimState.ABORTED

                frame = run.frame()
                run.history.append(frame)
                if len(run.history) > 5000:
                    run.history = run.history[-5000:]
                await self._broadcast(run_id, frame)

                if run.virtual_time_s >= run.config.duration_s and run.state == SimState.RUNNING:
                    run.state = SimState.COMPLETED
                    await self._broadcast(run_id, run.frame())
                    break

                await asyncio.sleep(dt)
        except asyncio.CancelledError:
            pass

    async def _broadcast(self, run_id: str, frame: dict[str, Any]) -> None:
        dead = set()
        for ws in self._clients.get(run_id, set()):
            try:
                await ws.send_text(json.dumps(frame))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._clients.get(run_id, set()).discard(ws)

    # ------------------------------------------------------------------
    def _setup_routes(self) -> None:
        app = self.app

        @app.get("/")
        async def index():
            html = _STATIC_DIR / "sim_dashboard.html"
            if not html.exists():
                raise HTTPException(500, "dashboard html missing")
            return FileResponse(str(html))

        @app.get("/health")
        async def health():
            return {
                "status": "healthy",
                "service": "simulator-live-dashboard",
                "active_runs": len(self._runs),
                "isolated_from_production": True,
            }

        @app.post("/api/sim/start")
        async def start(req: StartRequest):
            run_id = str(uuid.uuid4())[:8]
            run = RunModel(
                run_id=run_id,
                config=req,
                plant=self._new_plant(req.ambient_temp_c),
                state=SimState.RUNNING,
            )
            self._runs[run_id] = run
            self._clients[run_id] = set()
            self._tasks[run_id] = asyncio.create_task(self._run_loop(run_id))
            return {"status": "started", "run_id": run_id, "config": req.model_dump()}

        @app.post("/api/sim/{run_id}/pause")
        async def pause(run_id: str):
            run = self._get(run_id)
            if run.state != SimState.RUNNING:
                raise HTTPException(400, "can only pause a RUNNING sim")
            run.state = SimState.PAUSED
            return {"status": "paused", "run_id": run_id}

        @app.post("/api/sim/{run_id}/resume")
        async def resume(run_id: str):
            run = self._get(run_id)
            if run.state != SimState.PAUSED:
                raise HTTPException(400, "can only resume a PAUSED sim")
            run.state = SimState.RUNNING
            return {"status": "resumed", "run_id": run_id}

        @app.post("/api/sim/{run_id}/stop")
        async def stop(run_id: str):
            run = self._get(run_id)
            run.state = SimState.COMPLETED
            task = self._tasks.get(run_id)
            if task:
                task.cancel()
            return {"status": "stopped", "run_id": run_id, "frames": len(run.history)}

        @app.get("/api/sim/{run_id}/status")
        async def get_status(run_id: str):
            run = self._get(run_id)
            return {
                "run_id": run_id,
                "state": run.state.value,
                "config": run.config.model_dump(),
                "frame_count": len(run.history),
                "last_frame": run.history[-1] if run.history else None,
            }

        @app.get("/api/sim/{run_id}/history")
        async def get_history(run_id: str, limit: int = 500):
            run = self._get(run_id)
            return {"run_id": run_id, "count": len(run.history), "frames": run.history[-limit:]}

        @app.get("/api/sim/runs")
        async def list_runs():
            return {
                "runs": [
                    {"run_id": r.run_id, "state": r.state.value,
                     "sample": r.config.sample_name, "frames": len(r.history)}
                    for r in self._runs.values()
                ]
            }

        @app.websocket("/ws/sim/{run_id}")
        async def ws_stream(websocket: WebSocket, run_id: str):
            await websocket.accept()
            if run_id not in self._runs:
                await websocket.send_text(json.dumps({"error": "run not found"}))
                await websocket.close()
                return
            self._clients.setdefault(run_id, set()).add(websocket)
            # push the latest frame immediately so a late client sees state
            run = self._runs[run_id]
            if run.history:
                await websocket.send_text(json.dumps(run.history[-1]))
            try:
                while True:
                    await websocket.receive_text()  # keepalive / ignore inbound
            except WebSocketDisconnect:
                self._clients.get(run_id, set()).discard(websocket)

    def _get(self, run_id: str) -> RunModel:
        if run_id not in self._runs:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found")
        return self._runs[run_id]


def create_app() -> FastAPI:
    """Factory for uvicorn: ``uvicorn app.simulator.live_dashboard:create_app --factory``."""
    return LiveDashboardServer().app
