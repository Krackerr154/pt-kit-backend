"""ctypes binding for the shared host Arduino controller core.

The binding deliberately contains no Arduino state-machine logic. It only loads
PTKitSimulationCAPI and converts POD snapshots/byte buffers into Python values.
"""

from __future__ import annotations

import ctypes
import math
from pathlib import Path
from typing import Iterable


class PTKitSimSnapshot(ctypes.Structure):
    _fields_ = [
        ("now_ms", ctypes.c_uint32),
        ("total_seconds", ctypes.c_uint32),
        ("state_seconds", ctypes.c_uint32),
        ("hold_elapsed_seconds", ctypes.c_uint32),
        ("hold_qualified_seconds", ctypes.c_uint32),
        ("cycle", ctypes.c_int32),
        ("state", ctypes.c_int32),
        ("mode", ctypes.c_int32),
        ("illumination_mode", ctypes.c_int32),
        ("temp_ir_c", ctypes.c_float),
        ("temp_tc_c", ctypes.c_float),
        ("smoothed_lux", ctypes.c_float),
        ("control_temp_c", ctypes.c_float),
        ("temp_setpoint_c", ctypes.c_float),
        ("temp_error_c", ctypes.c_float),
        ("detected_plateau_temp_c", ctypes.c_float),
        ("lamp_pwm", ctypes.c_uint8),
        ("fan_pwm", ctypes.c_uint8),
        ("temp_ir_valid", ctypes.c_uint8),
        ("temp_tc_valid", ctypes.c_uint8),
        ("control_temp_valid", ctypes.c_uint8),
        ("qualified", ctypes.c_uint8),
    ]


class ArduinoBindingError(RuntimeError):
    """Raised when the shared controller library rejects an operation."""


class ArduinoHostController:
    """Own one host controller instance backed by the C++ firmware core."""

    def __init__(self, library: ctypes.CDLL) -> None:
        self._library = library
        self._handle = library.ptkit_sim_create()
        if not self._handle:
            raise ArduinoBindingError("ptkit_sim_create returned a null handle")
        self._closed = False

    @classmethod
    def load(cls, library_path: str | Path) -> "ArduinoHostController":
        """Load a compiled PTKitSimulationCAPI shared library."""

        path = Path(library_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        library = ctypes.CDLL(str(path))
        library.ptkit_sim_create.argtypes = []
        library.ptkit_sim_create.restype = ctypes.c_void_p
        library.ptkit_sim_destroy.argtypes = [ctypes.c_void_p]
        library.ptkit_sim_destroy.restype = None
        library.ptkit_sim_set_time.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        library.ptkit_sim_set_time.restype = None
        library.ptkit_sim_set_raw_sensors.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.c_float,
        ]
        library.ptkit_sim_set_raw_sensors.restype = None
        library.ptkit_sim_send_command.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        library.ptkit_sim_send_command.restype = ctypes.c_int
        library.ptkit_sim_step.argtypes = [ctypes.c_void_p]
        library.ptkit_sim_step.restype = ctypes.c_int
        library.ptkit_sim_get_snapshot.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(PTKitSimSnapshot),
        ]
        library.ptkit_sim_get_snapshot.restype = ctypes.c_int
        library.ptkit_sim_output_size.argtypes = [ctypes.c_void_p]
        library.ptkit_sim_output_size.restype = ctypes.c_size_t
        library.ptkit_sim_read_output.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        library.ptkit_sim_read_output.restype = ctypes.c_size_t
        library.ptkit_sim_clear_output.argtypes = [ctypes.c_void_p]
        library.ptkit_sim_clear_output.restype = None
        return cls(library)

    def __enter__(self) -> "ArduinoHostController":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._library.ptkit_sim_destroy(self._handle)
            self._closed = True
            self._handle = None

    def _require_open(self) -> None:
        if self._closed or not self._handle:
            raise ArduinoBindingError("controller handle is closed")

    def set_time(self, now_ms: int) -> None:
        self._require_open()
        if not isinstance(now_ms, int) or isinstance(now_ms, bool):
            raise TypeError("now_ms must be an integer")
        if not 0 <= now_ms <= 0xFFFFFFFF:
            raise ValueError("now_ms must fit in uint32_t")
        self._library.ptkit_sim_set_time(self._handle, ctypes.c_uint32(now_ms))

    def set_raw_sensors(self, ir_c: float, tc_c: float, lux: float) -> None:
        self._require_open()
        self._library.ptkit_sim_set_raw_sensors(
            self._handle,
            ctypes.c_float(ir_c),
            ctypes.c_float(tc_c),
            ctypes.c_float(lux),
        )

    def send_command(self, command: str | bytes) -> bool:
        self._require_open()
        payload = command.encode("ascii") if isinstance(command, str) else bytes(command)
        if b"\x00" in payload:
            raise ValueError("commands cannot contain NUL bytes")
        buffer = ctypes.create_string_buffer(payload, len(payload) + 1)
        accepted = self._library.ptkit_sim_send_command(
            self._handle, ctypes.cast(buffer, ctypes.c_void_p), len(payload)
        )
        return bool(accepted)

    def step(self) -> bool:
        self._require_open()
        return bool(self._library.ptkit_sim_step(self._handle))

    def snapshot(self) -> dict[str, object]:
        self._require_open()
        value = PTKitSimSnapshot()
        if not self._library.ptkit_sim_get_snapshot(self._handle, ctypes.byref(value)):
            raise ArduinoBindingError("ptkit_sim_get_snapshot failed")
        result: dict[str, object] = {}
        for name, _ctype in PTKitSimSnapshot._fields_:
            raw = getattr(value, name)
            if name.endswith("_valid") or name == "qualified":
                result[name] = bool(raw)
            elif isinstance(raw, float) and not math.isfinite(raw):
                result[name] = None
            else:
                result[name] = raw
        return result

    def read_output(self) -> bytes:
        self._require_open()
        size = int(self._library.ptkit_sim_output_size(self._handle))
        if size == 0:
            return b""
        buffer = ctypes.create_string_buffer(size)
        copied = int(
            self._library.ptkit_sim_read_output(
                self._handle, ctypes.cast(buffer, ctypes.c_void_p), size
            )
        )
        return bytes(buffer.raw[:copied])

    def clear_output(self) -> None:
        self._require_open()
        self._library.ptkit_sim_clear_output(self._handle)

    def step_with_time(
        self,
        now_ms: int,
        *,
        ir_c: float,
        tc_c: float,
        lux: float,
    ) -> tuple[dict[str, object], bytes]:
        """Set inputs, execute one controller call, and return snapshot plus UART."""

        self.set_time(now_ms)
        self.set_raw_sensors(ir_c, tc_c, lux)
        self.step()
        return self.snapshot(), self.read_output()


__all__ = ["ArduinoBindingError", "ArduinoHostController", "PTKitSimSnapshot"]
