"""Two-node thermal plant with a first-order analytic update.

The plant models two lumped thermal nodes:

* **surface** -- the IR-sensor-facing surface (small thermal mass, sees the
  lamp directly and exchanges heat with the bulk and the ambient), and
* **bulk** -- the sample/body (large thermal mass, exchanges heat with the
  surface and the ambient).

Actuators (lamp, fan) are first-order lags driven by PWM commands.  The base
plant is fully deterministic: there is no randomness anywhere in this module.
Disturbances and sensor noise are layered on by other components.

Numerical method
----------------
With the actuators held constant over a substep, the two-node temperatures
obey a linear, time-invariant system::

    d/dt [T_s, T_b]^T = A @ [T_s, T_b]^T + b

where ``A`` is a 2x2 matrix of conductances/capacities and ``b`` carries the
ambient forcing and lamp power.  Each substep is advanced *analytically* with
the matrix exponential (closed-form 2x2 ``expm``), so the result is exact for
constant inputs regardless of substep size.  ``step`` splits ``dt_s`` into
substeps no larger than ``config.max_substep_s``; because the update is exact,
irregular call intervals reproduce a fine-stepped reference to floating-point
precision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .config import PlantConfig

__all__ = ["PlantState", "ThermalPlant"]

_PWM_MIN = 0
_PWM_MAX = 255


@dataclass
class PlantState:
    """Two-node thermal plant state.

    Attributes:
        surface_temp_c: Surface temperature (°C).
        bulk_temp_c: Bulk/sample temperature (°C).
        ambient_temp_c: Ambient temperature (°C).
        lamp_output_lux: Lamp optical output (lux), 0..lamp_max_lux.
        fan_airflow: Effective fan airflow, normalized 0.0-1.0.
        lamp_pwm: Current commanded lamp PWM, 0-255.
        fan_pwm: Current commanded fan PWM, 0-255.
        time_s: Elapsed virtual time (seconds).
    """

    surface_temp_c: float  # °C
    bulk_temp_c: float  # °C
    ambient_temp_c: float  # °C
    lamp_output_lux: float  # lux
    fan_airflow: float  # normalized 0.0-1.0
    lamp_pwm: int  # 0-255
    fan_pwm: int  # 0-255
    time_s: float  # seconds


def _validate_pwm(value: object, *, name: str) -> int:
    """Return ``value`` as a validated PWM duty value in [0, 255]."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer PWM value in [0, 255]")
    if value < _PWM_MIN or value > _PWM_MAX:
        raise ValueError(f"{name} must be within [{_PWM_MIN}, {_PWM_MAX}]")
    return value


def _validate_dt(dt_s: object) -> float:
    """Return ``dt_s`` as a validated, non-negative float duration (seconds)."""

    if isinstance(dt_s, bool) or not isinstance(dt_s, (int, float)):
        raise TypeError("dt_s must be a non-negative number of seconds")
    dt = float(dt_s)
    if not math.isfinite(dt):
        raise ValueError("dt_s must be finite")
    if dt < 0.0:
        raise ValueError("dt_s must not be negative")
    return dt


def _expm2(a: float, b: float, c: float, d: float, h: float) -> tuple[float, float, float, float]:
    """Closed-form matrix exponential of ``[[a, b], [c, d]] * h``.

    Uses the eigenvalue formula.  When the discriminant collapses (repeated
    eigenvalue) the two-exponential expression is ill-conditioned, so we fall
    back to the repeated-root limit ``expm(M h) = e^{λh}(I + (M - λI) h)``.
    """

    tr = a + d
    det = a * d - b * c
    disc = tr * tr - 4.0 * det
    if disc < 0.0:
        # Cannot happen for this plant (similar matrix is symmetric => real
        # eigenvalues); clamp to keep the result real and finite.
        disc = 0.0
    sqrt_disc = math.sqrt(disc)
    lam1 = 0.5 * (tr + sqrt_disc)
    lam2 = 0.5 * (tr - sqrt_disc)

    e1 = math.exp(lam1 * h)
    e2 = math.exp(lam2 * h)

    if sqrt_disc <= 1e-9 * (abs(tr) + 1.0):
        # Repeated eigenvalue λ = tr/2.
        lam = 0.5 * tr
        e = math.exp(lam * h)
        m00 = e * (1.0 + (a - lam) * h)
        m01 = e * (b * h)
        m10 = e * (c * h)
        m11 = e * (1.0 + (d - lam) * h)
        return m00, m01, m10, m11

    inv = 1.0 / sqrt_disc
    m00 = ((lam1 - d) * e1 - (lam2 - d) * e2) * inv
    m01 = b * (e1 - e2) * inv
    m10 = c * (e1 - e2) * inv
    m11 = ((lam1 - a) * e1 - (lam2 - a) * e2) * inv
    return m00, m01, m10, m11


class ThermalPlant:
    """Deterministic two-node thermal plant.

    Args:
        config: Plant parameters (see :class:`PlantConfig`).
        initial_state: Optional starting state.  Defaults to thermal
            equilibrium at the configured ambient temperature with all
            actuators off.
    """

    def __init__(self, config: PlantConfig, initial_state: PlantState | None = None) -> None:
        self._config = config
        self._ambient_temp_c = config.ambient_temp_c  # °C, per-run overridable
        # Internal actuator states (continuous, before mapping to outputs).
        self._lamp_power_w = 0.0  # W, instantaneous electrical power
        self._fan_norm = 0.0  # normalized 0.0-1.0 instantaneous airflow
        self._lamp_pwm = 0  # last commanded lamp PWM, 0-255
        self._fan_pwm = 0  # last commanded fan PWM, 0-255
        self._time_s = 0.0  # elapsed virtual time, seconds
        self._surface_temp_c = config.ambient_temp_c  # °C
        self._bulk_temp_c = config.ambient_temp_c  # °C
        if initial_state is not None:
            self._apply_initial_state(initial_state)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------
    @property
    def state(self) -> PlantState:
        """Return a snapshot of the current plant state."""

        return self._make_state()

    def reset(self, initial_state: PlantState | None = None) -> None:
        """Reset the plant to equilibrium (or ``initial_state``) at time zero."""

        self._ambient_temp_c = self._config.ambient_temp_c
        self._lamp_power_w = 0.0
        self._fan_norm = 0.0
        self._lamp_pwm = 0
        self._fan_pwm = 0
        self._time_s = 0.0
        self._surface_temp_c = self._config.ambient_temp_c
        self._bulk_temp_c = self._config.ambient_temp_c
        if initial_state is not None:
            self._apply_initial_state(initial_state)

    def step(self, lamp_pwm: int, fan_pwm: int, dt_s: float) -> PlantState:
        """Advance the plant by ``dt_s`` seconds under the given actuator commands.

        Args:
            lamp_pwm: Lamp duty cycle, integer in [0, 255].
            fan_pwm: Fan duty cycle, integer in [0, 255].
            dt_s: Elapsed time to advance (seconds), non-negative.

        Returns:
            The :class:`PlantState` after advancing.
        """

        lamp_pwm = _validate_pwm(lamp_pwm, name="lamp_pwm")
        fan_pwm = _validate_pwm(fan_pwm, name="fan_pwm")
        dt = _validate_dt(dt_s)

        self._lamp_pwm = lamp_pwm
        self._fan_pwm = fan_pwm

        if dt > 0.0:
            max_substep = self._config.max_substep_s
            if max_substep <= 0.0:
                raise ValueError("config.max_substep_s must be positive")
            n_substeps = max(1, math.ceil(dt / max_substep))
            h = dt / n_substeps  # seconds per substep
            for _ in range(n_substeps):
                self._substep(lamp_pwm, fan_pwm, h)
            self._time_s += dt

        return self._make_state()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _apply_initial_state(self, initial_state: PlantState) -> None:
        for field in (
            "surface_temp_c",
            "bulk_temp_c",
            "ambient_temp_c",
            "lamp_output_lux",
            "fan_airflow",
            "time_s",
        ):
            value = getattr(initial_state, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"initial_state.{field} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"initial_state.{field} must be finite")
        self._surface_temp_c = float(initial_state.surface_temp_c)
        self._bulk_temp_c = float(initial_state.bulk_temp_c)
        self._ambient_temp_c = float(initial_state.ambient_temp_c)
        self._time_s = float(initial_state.time_s)
        self._lamp_pwm = _validate_pwm(initial_state.lamp_pwm, name="initial_state.lamp_pwm")
        self._fan_pwm = _validate_pwm(initial_state.fan_pwm, name="initial_state.fan_pwm")
        # Recover continuous actuator states from the reported outputs.
        if self._config.lamp_max_power_w > 0.0:
            self._lamp_power_w = float(initial_state.lamp_output_lux) / self._config.lamp_max_lux
            self._lamp_power_w *= self._config.lamp_max_power_w
        else:
            self._lamp_power_w = 0.0
        self._fan_norm = min(1.0, max(0.0, float(initial_state.fan_airflow)))

    def _make_state(self) -> PlantState:
        cfg = self._config
        lamp_output_lux = 0.0
        if cfg.lamp_max_power_w > 0.0:
            lamp_output_lux = (self._lamp_power_w / cfg.lamp_max_power_w) * cfg.lamp_max_lux
        return PlantState(
            surface_temp_c=self._surface_temp_c,
            bulk_temp_c=self._bulk_temp_c,
            ambient_temp_c=self._ambient_temp_c,
            lamp_output_lux=lamp_output_lux,
            fan_airflow=self._fan_norm,
            lamp_pwm=self._lamp_pwm,
            fan_pwm=self._fan_pwm,
            time_s=self._time_s,
        )

    def _substep(self, lamp_pwm: int, fan_pwm: int, h: float) -> None:
        """Advance temperatures and actuators analytically by ``h`` seconds."""

        cfg = self._config

        # --- Actuator first-order lags (exact exponential approach). ---
        lamp_target_w = (lamp_pwm / _PWM_MAX) * cfg.lamp_max_power_w  # W
        fan_target = fan_pwm / _PWM_MAX  # normalized 0.0-1.0
        self._lamp_power_w = _lag(self._lamp_power_w, lamp_target_w, cfg.lamp_response_time_s, h)
        self._fan_norm = _lag(self._fan_norm, fan_target, cfg.fan_response_time_s, h)

        # --- Two-node linear thermal system with constant inputs. ---
        c_s = cfg.surface_capacity_j_per_k  # J/K
        c_b = cfg.bulk_capacity_j_per_k  # J/K
        g_sb = cfg.surface_bulk_conductance_w_per_k  # W/K
        g_sa = cfg.surface_ambient_conductance_w_per_k + self._fan_norm * cfg.fan_max_conductance_w_per_k  # W/K
        g_ba = cfg.bulk_ambient_conductance_w_per_k  # W/K

        t_amb = self._ambient_temp_c  # °C
        # dT_s/dt = a11*T_s + a12*T_b + q1
        a11 = -(g_sb + g_sa) / c_s  # 1/s
        a12 = g_sb / c_s  # 1/s
        a21 = g_sb / c_b  # 1/s
        a22 = -(g_sb + g_ba) / c_b  # 1/s
        q1 = (g_sa * t_amb + self._lamp_power_w) / c_s  # K/s
        q2 = (g_ba * t_amb) / c_b  # K/s

        m00, m01, m10, m11 = _expm2(a11, a12, a21, a22, h)

        t_s = self._surface_temp_c
        t_b = self._bulk_temp_c
        # Particular solution for the constant forcing over the substep:
        # integral_0^h expm(A τ) dτ @ q, computed via the same eigen-decomp.
        p1, p2 = _forcing_integral(a11, a12, a21, a22, q1, q2, h, m00, m01, m10, m11)

        self._surface_temp_c = m00 * t_s + m01 * t_b + p1
        self._bulk_temp_c = m10 * t_s + m11 * t_b + p2


def _lag(current: float, target: float, tau_s: float, h: float) -> float:
    """Exact first-order lag toward ``target`` over ``h`` seconds.

    ``tau_s`` is the response time constant (seconds).  A non-positive time
    constant means the actuator responds instantaneously.
    """

    if tau_s <= 0.0:
        return target
    alpha = math.exp(-h / tau_s)  # dimensionless
    return target + (current - target) * alpha


def _forcing_integral(
    a11: float,
    a12: float,
    a21: float,
    a22: float,
    q1: float,
    q2: float,
    h: float,
    m00: float,
    m01: float,
    m10: float,
    m11: float,
) -> tuple[float, float]:
    """Return ``∫₀ʰ expm(A τ) dτ @ q`` for the 2x2 system.

    Computed as ``A⁻¹ (expm(A h) - I) q`` when ``A`` is invertible, with a
    small-``h``/near-singular fallback using the series ``h I + (h²/2) A``.
    """

    det = a11 * a22 - a12 * a21
    # (expm(Ah) - I) @ q
    r1 = (m00 - 1.0) * q1 + m01 * q2
    r2 = m10 * q1 + (m11 - 1.0) * q2

    if abs(det) > 1e-12:
        inv_det = 1.0 / det
        # A^{-1} = (1/det) [[a22, -a12], [-a21, a11]]
        p1 = inv_det * (a22 * r1 - a12 * r2)
        p2 = inv_det * (-a21 * r1 + a11 * r2)
        return p1, p2

    # Near-singular A: use the first terms of the Magnus/Taylor series.
    # ∫₀ʰ expm(Aτ)dτ ≈ h I + (h²/2) A
    half_h2 = 0.5 * h * h
    p1 = h * q1 + half_h2 * (a11 * q1 + a12 * q2)
    p2 = h * q2 + half_h2 * (a21 * q1 + a22 * q2)
    return p1, p2
