# Phase 9 — Implementation Bugs Found & Fixed

All bugs below were surfaced by Phase 9 full-system integration testing. Each had
been invisible to per-phase testing because each layer was only ever tested alone.

## FIXED

### 1. Test-suite contamination via `sys.modules` poisoning (55 collection ERRORs)
**File:** `tests/test_websocket_manager.py:11`
`sys.modules['fastapi'] = MagicMock()` at import time poisoned the module cache for
every later-collected test module, which then failed with `'fastapi' is not a package`.
Killed 30 tests in `test_isolated_backend_api.py` and 25 in `test_dashboard_server.py`
— all of which passed when run standalone. **Fix:** removed the mock; fastapi is installed.

### 2. UART frame layout contradicted the protocol spec
**File:** `app/simulator/virtual_uart.py` — `encode_packet()`
The CRC-16 checksum was appended to the *header*, landing it **before** the payload.
`docs/phase4-uart-protocol-spec.md` specifies header → payload → checksum. Every
encode→decode round-trip failed checksum validation. **Fix:** checksum now trails the payload.

### 3. Thermal controller could never reach steady state
**File:** `app/simulator/controller_implementation.py` — `step()`
The lamp was hard-wired `lamp_on=True` in STABILIZING / HOLDING / QUALIFY_CYCLE /
PLATEAU_VALIDATE. With no thermostat the plant ran away to its ~175 °C equilibrium, so
`_check_stabilization()` (`|T − target| ≤ 0.5`) could never be satisfied and **every**
ISO1/PLAT1 run stalled in STABILIZING forever. **Fix:** added `_thermostat_lamp_on()`
bang-bang control with hysteresis = ½ × stabilization tolerance.

### 4. COOLING state was an infinite trap after STOP
**File:** `app/simulator/controller_implementation.py` — `step()`, COOLING branch
Exit threshold was `target_temp_c * 0.3` — for an 80 °C target that is 24 °C, but ambient
is 25 °C, so the plant asymptotes *above* the threshold and can never cross it. After any
STOP the controller cooled forever and never returned to IDLE. **Fix:** threshold is now
`max(target * 0.3, ambient + 1.0)`.

### 5. `SUPERVISOR_ABORT` silently ignored when issued from IDLE
**File:** `app/simulator/controller_implementation.py` — `_handle_command()`
Guarded by `if self.state != ControllerState.IDLE`, so a supervisor abort from IDLE set the
flag but left the state untouched, breaking the STOP ≠ ABORT ≠ SUPERVISOR_ABORT contract.
**Fix:** always transitions to ABORTED.

### 6. Batch processor could not execute any job
**File:** `app/simulator/batch_processor.py` — `_process_single_job()`
Three defects: (a) `progress_callback` awaited unconditionally → `'NoneType' object is not
callable` when unset, failing every job through the retry path; (b) job status never
transitioned to RUNNING/COMPLETED, so jobs stayed PENDING forever; (c) synchronous processor
functions were unsupported. **Fix:** added `_notify()` tolerating sync/async/absent callbacks,
proper status + timestamp transitions, and `inspect.isawaitable()` dispatch.
Test runtime dropped 110 s → 0.11 s.

### 7. Missing 17th telemetry field
**File:** `app/simulator/controller_implementation.py` — `ExtendedTelemetry`
Docstring and interface contract promise 17 fields; `to_dict()` emitted 16.
**Fix:** added `cycle_elapsed_s` (populated during QUALIFY_CYCLE).

### 8. Invalid-sensor flag did not reach telemetry from passive states
**File:** `app/simulator/controller_implementation.py` — `step()`
States that do not advance the plant (e.g. IDLE) reported the last *valid* temperature
instead of the `-273.15` sentinel. **Fix:** sentinel applied to plant state as soon as the
`INVALID_SENSOR` supervision flag is set.

### 9. `FAULT_INJECT` validation bypassed by empty payload
**File:** `app/simulator/dashboard_server.py` — `validate_payload_structure()`
Guard was `if cmd_type == "FAULT_INJECT" and v:` — an empty dict `{}` is falsy, so a
`FAULT_INJECT` with no `fault_type` passed validation and returned 200 instead of 422.
**Fix:** `if not v or 'fault_type' not in v`.

### 10. Active run never resolvable (IntEnum compared against strings)
**File:** `app/simulator/dashboard_server.py` — `_get_active_run_id()`
`RunState` is an `IntEnum`, so `state.value` is `2`, compared against `('RUNNING',
'EXPERIMENT_RUNNING', 'PAUSED')` — never matched. `/simulator/status` therefore always
returned an empty state instead of the running experiment. **Fix:** compare `state.name`.

### 11. `/simulator/history` never returned 404
**File:** `app/simulator/dashboard_server.py` — `get_history()`
Docstring promises `HTTPException(404)` for unknown runs; code silently returned `[]`.
**Fix:** explicit existence check before falling back to internal storage.

---

## OPEN — cross-layer protocol divergence (NOT fixed; needs a decision)

### A. `virtual_uart.py` and `esp32_bridge_simulator.py` speak incompatible wire formats
These two layers are supposed to be the two ends of the same serial link, but their
frames do not interoperate:

| Aspect | `virtual_uart.py` (Arduino side) | `esp32_bridge_simulator.py` (ESP32 side) |
|---|---|---|
| Byte order | big-endian (`abcd0101…`) | little-endian (`cdab0100…`) |
| Header size | 9 bytes | 7 bytes |
| Field order | sync, ver, type, seq, len | sync, **seq**, ver, type, len |
| Checksum | true CRC-16-CCITT (poly 0x1021) | `zlib.crc32() & 0xFFFF` — **not** CCITT |

`docs/phase4-uart-protocol-spec.md` describes the big-endian 9-byte layout and specifies
CRC-16-CCITT, so `virtual_uart.py` is the spec-conformant side and the ESP32 bridge
diverges on all four axes.

**Why it was not fixed here:** aligning the bridge is a real protocol change that affects
the ESP32 firmware contract, not a test defect. It needs an explicit decision on whether
the simulator should mirror the *spec* or mirror what the *deployed ESP32 firmware*
actually does. Both existing test suites pass because each layer only ever round-trips
against itself.

**Recommendation:** align `esp32_bridge_simulator.UARTPacket` to the spec (big-endian,
9-byte header, real CRC-16-CCITT), then add a cross-layer test asserting
`VirtualUARTEngine.encode_packet()` output is decodable by `ESP32Bridge.unpack()` and
vice-versa. Until then the two layers must not be wired directly together.
