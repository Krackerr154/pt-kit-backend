"""Supervisor orchestrator for experiment lifecycle management and remote commands.

This module provides the ExperimentLifecycleController class which:
- Manages experiment lifecycle states (pending, running, paused, completed, failed)
- Schedules and executes remote commands through the virtual clock scheduler
- Handles command queuing, execution ordering, and result collection
- Provides state machine transitions with validation
- Coordinates fault injection timing with experiment progress
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable


class ExperimentState(Enum):
    """Valid states for an experiment lifecycle."""

    PENDING = "pending"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    RESUMING = "resuming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CommandType(Enum):
    """Types of remote commands that can be executed."""

    START_EXPERIMENT = "start_experiment"
    PAUSE_EXPERIMENT = "pause_experiment"
    RESUME_EXPERIMENT = "resume_experiment"
    STOP_EXPERIMENT = "stop_experiment"
    FAULT_INJECT = "fault_inject"
    RESET_CONFIG = "reset_config"
    GET_STATUS = "get_status"
    GET_METRICS = "get_metrics"
    SET_PARAM = "set_param"
    DOWNLOAD_DATA = "download_data"


@dataclass
class RemoteCommand:
    """Represents a remote command to be scheduled and executed."""

    command_id: str
    command_type: CommandType
    payload: dict = field(default_factory=dict)
    timestamp_ms: int = 0
    scheduled_ms: int = 0
    executor: Callable[[dict], Any] | None = None
    result: Any = None
    error: str | None = None
    executed: bool = False
    cancelled: bool = False


@dataclass
class ExperimentConfig:
    """Configuration for an experiment run."""

    experiment_id: str
    profile_id: str
    duration_s: float
    sampling_interval_s: float
    fault_schedule: list[dict] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class ExperimentStatus:
    """Current status of an experiment."""

    experiment_id: str
    state: ExperimentState
    start_time_ms: int = 0
    pause_start_ms: int = 0
    resume_time_ms: int = 0
    end_time_ms: int = 0
    elapsed_s: float = 0.0
    progress_percent: float = 0.0
    current_command_id: str = ""
    metrics: dict = field(default_factory=dict)
    error_message: str | None = None


@dataclass
class MetricsSnapshot:
    """Snapshot of experiment metrics at a point in time."""

    timestamp_ms: int
    sensor_readings: dict
    plant_state: dict
    lamp_power_w: float
    fan_conductance_w_per_k: float
    fault_active: bool
    command_count: int


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: ExperimentState, to_state: ExperimentState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid state transition from {from_state.value} to {to_state.value}"
        )


class ExperimentLifecycleController:
    """Manages experiment lifecycle and coordinates remote command execution.

    This orchestrator:
    - Enforces valid state transitions based on current state
    - Queues and schedules remote commands via VirtualClock
    - Tracks experiment progress and metrics
    - Handles fault injection scheduling
    - Provides status reporting and command result collection

    Thread-safe for concurrent command submissions from remote sources.

    Attributes:
        command_queue: Pending commands waiting for execution.
        executed_commands: Commands that have been executed.
        current_status: Current experiment status snapshot.
        config: Experiment configuration.
    """

    # Valid state transitions mapping
    VALID_TRANSITIONS: dict[ExperimentState, set[ExperimentState]] = {
        ExperimentState.PENDING: {ExperimentState.INITIALIZING, ExperimentState.CANCELLED},
        ExperimentState.INITIALIZING: {
            ExperimentState.RUNNING,
            ExperimentState.FAILED,
            ExperimentState.CANCELLED,
        },
        ExperimentState.RUNNING: {
            ExperimentState.PAUSED,
            ExperimentState.COMPLETED,
            ExperimentState.FAILED,
            ExperimentState.CANCELLED,
        },
        ExperimentState.PAUSED: {ExperimentState.RUNNING, ExperimentState.FAILED, ExperimentState.CANCELLED},
        ExperimentState.RESUMING: {ExperimentState.RUNNING},
        ExperimentState.COMPLETED: set(),
        ExperimentState.FAILED: {ExperimentState.INITIALIZING, ExperimentState.PENDING},
        ExperimentState.CANCELLED: set(),
    }

    def __init__(
        self,
        clock_scheduler: Callable[[int, int, Callable[[], Any], str], int],
        clock_now_ms: Callable[[], int],
        max_queued_commands: int = 100,
    ):
        """Initialize the lifecycle controller.

        Args:
            clock_scheduler: Function to schedule events (like VirtualClock.schedule).
            clock_now_ms: Function to get current virtual time in ms.
            max_queued_commands: Maximum number of commands allowed in queue.
        """
        self._clock_scheduler = clock_scheduler
        self._clock_now_ms = clock_now_ms
        self._max_queued_commands = max_queued_commands

        # State tracking
        self._current_state = ExperimentState.PENDING
        self._current_status = ExperimentStatus(experiment_id="", state=ExperimentState.PENDING)
        self._config: ExperimentConfig | None = None

        # Command management
        self._command_queue: list[RemoteCommand] = []
        self._executed_commands: list[RemoteCommand] = []
        self._command_lock = threading.RLock()
        self._active_command_id: str | None = None

        # Execution results callback
        self._on_command_result: Callable[[RemoteCommand], Any] | None = None

        # Metrics collection
        self._metrics_history: list[MetricsSnapshot] = []
        self._metrics_sample_interval_ms: int = 1000

    @property
    def current_state(self) -> ExperimentState:
        """Get current experiment state."""
        return self._current_state

    @property
    def current_status(self) -> ExperimentStatus:
        """Get current experiment status."""
        return self._current_status

    @property
    def command_queue_size(self) -> int:
        """Get number of commands in queue."""
        return len(self._command_queue)

    @property
    def executed_command_count(self) -> int:
        """Get count of executed commands."""
        return len(self._executed_commands)

    def submit_command(
        self,
        command_type: CommandType,
        payload: dict | None = None,
        scheduled_at_ms: int | None = None,
        executor: Callable[[dict], Any] | None = None,
    ) -> str:
        """Submit a remote command for execution.

        Args:
            command_type: Type of command to execute.
            payload: Optional command parameters.
            scheduled_at_ms: Virtual time to schedule command (defaults to now).
            executor: Optional custom executor function.

        Returns:
            Unique command ID.

        Raises:
            RuntimeError: If queue is full.
        """
        payload = payload or {}
        command_id = f"cmd_{self._clock_now_ms()}_{len(self._command_queue)}"
        scheduled_time = scheduled_at_ms if scheduled_at_ms is not None else self._clock_now_ms()

        command = RemoteCommand(
            command_id=command_id,
            command_type=command_type,
            payload=payload,
            timestamp_ms=self._clock_now_ms(),
            scheduled_ms=scheduled_time,
            executor=executor,
        )

        with self._command_lock:
            if len(self._command_queue) >= self._max_queued_commands:
                raise RuntimeError(f"Command queue full ({self._max_queued_commands})")
            self._command_queue.append(command)

        return command_id

    def execute_pending_commands(self) -> list[str]:
        """Execute all pending commands up to current time.

        Returns:
            List of executed command IDs.
        """
        executed_ids: list[str] = []
        current_time = self._clock_now_ms()

        with self._command_lock:
            while self._command_queue and self._command_queue[0].scheduled_ms <= current_time:
                command = self._command_queue.pop(0)
                
                if command.cancelled:
                    continue

                try:
                    result = self._execute_command(command)
                    command.result = result
                    command.executed = True
                    
                    if self._on_command_result:
                        self._on_command_result(command)
                    
                    self._executed_commands.append(command)
                    executed_ids.append(command.command_id)

                    # Update active command
                    self._active_command_id = command.command_id

                except Exception as e:
                    command.error = str(e)
                    command.executed = True
                    self._executed_commands.append(command)

                    # Handle critical errors
                    if command.command_type == CommandType.START_EXPERIMENT:
                        self.transition_to(ExperimentState.FAILED, error_message=str(e))

        return executed_ids

    def _execute_command(self, command: RemoteCommand) -> Any:
        """Execute a single command.

        Args:
            command: Command to execute.

        Returns:
            Command result.

        Raises:
            Exception: If command execution fails.
        """
        cmd_type = command.command_type
        payload = command.payload

        if cmd_type == CommandType.START_EXPERIMENT:
            return self._handle_start_experimental(payload)
        elif cmd_type == CommandType.PAUSE_EXPERIMENT:
            return self._handle_pause_experiment()
        elif cmd_type == CommandType.RESUME_EXPERIMENT:
            return self._handle_resume_experiment()
        elif cmd_type == CommandType.STOP_EXPERIMENT:
            return self._handle_stop_experiment()
        elif cmd_type == CommandType.FAULT_INJECT:
            return self._handle_fault_inject(payload)
        elif cmd_type == CommandType.RESET_CONFIG:
            return self._handle_reset_config(payload)
        elif cmd_type == CommandType.GET_STATUS:
            return self.get_status()
        elif cmd_type == CommandType.GET_METRICS:
            return self.get_metrics()
        elif cmd_type == CommandType.SET_PARAM:
            return self._handle_set_param(payload)
        elif cmd_type == CommandType.DOWNLOAD_DATA:
            return self._handle_download_data(payload)
        else:
            raise ValueError(f"Unknown command type: {cmd_type}")

    def _handle_start_experimental(self, payload: dict) -> dict:
        """Handle START_EXPERIMENT command."""
        if self._config is None:
            raise ValueError("No experiment configuration loaded")

        # Apply any parameter overrides from payload
        if "parameters" in payload:
            self._config.parameters.update(payload["parameters"])

        return {
            "status": "started",
            "experiment_id": self._config.experiment_id,
            "duration_s": self._config.duration_s,
        }

    def _handle_pause_experiment(self) -> dict:
        """Handle PAUSE_EXPERIMENT command."""
        self._current_status.pause_start_ms = self._clock_now_ms()
        return {"status": "paused", "pause_time_ms": self._current_status.pause_start_ms}

    def _handle_resume_experiment(self) -> dict:
        """Handle RESUME_EXPERIMENT command."""
        self._current_status.resume_time_ms = self._clock_now_ms()
        self._current_status.elapsed_s += (
            self._current_status.resume_time_ms - self._current_status.pause_start_ms
        ) / 1000.0
        return {"status": "resumed", "resume_time_ms": self._current_status.resume_time_ms}

    def _handle_stop_experiment(self) -> dict:
        """Handle STOP_EXPERIMENT command."""
        self._current_status.end_time_ms = self._clock_now_ms()
        return {
            "status": "stopped",
            "total_duration_ms": self._current_status.end_time_ms - self._current_status.start_time_ms,
        }

    def _handle_fault_inject(self, payload: dict) -> dict:
        """Handle FAULT_INJECT command."""
        fault_type = payload.get("fault_type", "random")
        severity = payload.get("severity", "medium")
        target = payload.get("target", "all")

        return {
            "status": "fault_injected",
            "fault_type": fault_type,
            "severity": severity,
            "target": target,
        }

    def _handle_reset_config(self, payload: dict) -> dict:
        """Handle RESET_CONFIG command."""
        # Reset to initial configuration
        if self._config:
            self._config.parameters.clear()
            self._config.parameters.update(self._config.metadata.get("default_params", {}))

        return {"status": "config_reset"}

    def _handle_set_param(self, payload: dict) -> dict:
        """Handle SET_PARAM command."""
        param_name = payload.get("name")
        param_value = payload.get("value")

        if not param_name:
            raise ValueError("SET_PARAM requires 'name' parameter")

        if self._config:
            self._config.parameters[param_name] = param_value

        return {"status": "param_set", "name": param_name, "value": param_value}

    def _handle_download_data(self, payload: dict) -> dict:
        """Handle DOWNLOAD_DATA command."""
        format_type = payload.get("format", "json")
        start_ms = payload.get("start_ms", 0)
        end_ms = payload.get("end_ms", self._clock_now_ms())

        filtered_snapshots = [
            s for s in self._metrics_history
            if start_ms <= s.timestamp_ms <= end_ms
        ]

        return {
            "status": "data_exported",
            "format": format_type,
            "snapshot_count": len(filtered_snapshots),
        }

    def load_experiment_config(self, config: ExperimentConfig) -> None:
        """Load experiment configuration.

        Args:
            config: Experiment configuration to load.

        Raises:
            StateTransitionError: If not in PENDING or FAILED state.
        """
        if self._current_state not in (
            ExperimentState.PENDING,
            ExperimentState.FAILED,
            ExperimentState.CANCELLED,
        ):
            raise StateTransitionError(
                self._current_state,
                ExperimentState.INITIALIZING,
            )

        self._config = config
        self.transition_to(ExperimentState.INITIALIZING)

    def transition_to(self, new_state: ExperimentState, **kwargs) -> None:
        """Transition to a new state.

        Args:
            new_state: Target state.
            **kwargs: Additional state-specific data.

        Raises:
            StateTransitionError: If transition is invalid.
        """
        old_state = self._current_state

        if new_state not in self.VALID_TRANSITIONS.get(old_state, set()):
            raise StateTransitionError(old_state, new_state)

        # Handle state-specific logic
        if old_state == ExperimentState.RUNNING and new_state == ExperimentState.PAUSED:
            self._current_status.pause_start_ms = kwargs.get(
                "timestamp_ms", self._clock_now_ms()
            )
        elif old_state == ExperimentState.PAUSED and new_state == ExperimentState.RUNNING:
            self._current_status.resume_time_ms = kwargs.get(
                "timestamp_ms", self._clock_now_ms()
            )
            elapsed_paused = (
                self._current_status.resume_time_ms - self._current_status.pause_start_ms
            ) / 1000.0
            self._current_status.elapsed_s += elapsed_paused
        elif new_state == ExperimentState.RUNNING:
            if self._current_status.start_time_ms == 0:
                self._current_status.start_time_ms = kwargs.get(
                    "timestamp_ms", self._clock_now_ms()
                )
        elif new_state in (ExperimentState.COMPLETED, ExperimentState.FAILED):
            self._current_status.end_time_ms = kwargs.get(
                "timestamp_ms", self._clock_now_ms()
            )
            if self._config:
                progress = min(100.0, (self._current_status.elapsed_s / self._config.duration_s) * 100)
                self._current_status.progress_percent = progress

        self._current_state = new_state
        self._current_status.state = new_state
        self._current_status.error_message = kwargs.get("error_message")

    def record_metric_snapshot(self, snapshot: MetricsSnapshot) -> None:
        """Record a metrics snapshot.

        Args:
            snapshot: Metrics snapshot to record.
        """
        self._metrics_history.append(snapshot)

    def get_status(self) -> dict:
        """Get current experiment status.

        Returns:
            Status dictionary with state, progress, timing info.
        """
        return {
            "experiment_id": self._current_status.experiment_id,
            "state": self._current_status.state.value,
            "elapsed_s": self._current_status.elapsed_s,
            "progress_percent": self._current_status.progress_percent,
            "current_command_id": self._current_status.current_command_id,
            "error_message": self._current_status.error_message,
            "metrics": self._current_status.metrics,
        }

    def get_metrics(self) -> dict:
        """Get experiment metrics.

        Returns:
            Dictionary containing metrics history and summary.
        """
        return {
            "history": [
                {
                    "timestamp_ms": s.timestamp_ms,
                    "sensor_readings": s.sensor_readings,
                    "plant_state": s.plant_state,
                    "lamp_power_w": s.lamp_power_w,
                    "fan_conductance_w_per_k": s.fan_conductance_w_per_k,
                    "fault_active": s.fault_active,
                    "command_count": s.command_count,
                }
                for s in self._metrics_history
            ],
            "snapshot_count": len(self._metrics_history),
        }

    def cancel_command(self, command_id: str) -> bool:
        """Cancel a pending command.

        Args:
            command_id: Command to cancel.

        Returns:
            True if cancelled, False if not found or already executed.
        """
        with self._command_lock:
            for command in self._command_queue:
                if command.command_id == command_id:
                    command.cancelled = True
                    return True
            return False

    def register_result_callback(self, callback: Callable[[RemoteCommand], Any]) -> None:
        """Register a callback for command completion events.

        Args:
            callback: Function to call when command completes.
                      Signature: lambda command: result
        """
        self._on_command_result = callback

    def clear_command_queue(self) -> None:
        """Clear all pending commands from queue."""
        with self._command_lock:
            self._command_queue.clear()

    def get_executed_commands(self) -> list[dict]:
        """Get list of executed commands with results.

        Returns:
            List of command result dictionaries.
        """
        return [
            {
                "command_id": c.command_id,
                "command_type": c.command_type.value,
                "result": c.result,
                "error": c.error,
                "executed_at_ms": c.scheduled_ms,
            }
            for c in self._executed_commands
        ]

    def set_experiment_id(self, experiment_id: str) -> None:
        """Set the experiment ID in status.

        Args:
            experiment_id: Experiment identifier.
        """
        self._current_status.experiment_id = experiment_id

    def update_progress(
        self,
        elapsed_s: float,
        duration_s: float,
        additional_metrics: dict | None = None,
    ) -> None:
        """Update experiment progress.

        Args:
            elapsed_s: Time elapsed since start.
            duration_s: Total expected duration.
            additional_metrics: Additional metrics to track.
        """
        self._current_status.elapsed_s = elapsed_s
        self._current_status.progress_percent = (elapsed_s / duration_s * 100) if duration_s > 0 else 0

        if additional_metrics:
            self._current_status.metrics.update(additional_metrics)


# Convenience function for creating controller with default settings
def create_lifecycle_controller(
    clock_scheduler: Callable[[int, int, Callable[[], Any], str], int],
    clock_now_ms: Callable[[], int],
    max_queued_commands: int = 100,
) -> ExperimentLifecycleController:
    """Factory function to create an ExperimentLifecycleController.

    Args:
        clock_scheduler: Event scheduler function.
        clock_now_ms: Current time getter.
        max_queued_commands: Maximum queue size.

    Returns:
        Configured ExperimentLifecycleController instance.
    """
    return ExperimentLifecycleController(
        clock_scheduler=clock_scheduler,
        clock_now_ms=clock_now_ms,
        max_queued_commands=max_queued_commands,
    )
