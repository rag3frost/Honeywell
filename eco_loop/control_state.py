"""Thread-safe shared state between the EnergyPlus sim thread and the MCP/agent side.

The sim publishes an hourly summary then blocks on `await_decision`; the agent
(via MCP `set_setpoints`) resolves it. Timeout means the caller applies fallback —
the sim can never deadlock on the agent.
"""
from __future__ import annotations

import threading
from typing import Any

from eco_loop import fallback
from eco_loop.config import Config, Setpoints


class ControlState:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._lock = threading.Lock()
        self._decision_event = threading.Event()
        self._setpoints = cfg.baseline_setpoints
        self._source = "baseline"
        self._summary: dict[str, Any] | None = None
        self._hour_id = 0
        self._awaiting = False
        self._sim_done = False

    def get_setpoints(self) -> Setpoints:
        with self._lock:
            return self._setpoints

    def set_setpoints(self, heating_c: float, cooling_c: float, source: str) -> Setpoints:
        sp = fallback.clamp(heating_c, cooling_c, self._cfg)
        with self._lock:
            self._setpoints = sp
            self._source = source
            self._awaiting = False
        self._decision_event.set()
        return sp

    def publish_hour(self, summary: dict[str, Any]) -> None:
        with self._lock:
            self._summary = summary
            self._hour_id += 1
            self._awaiting = True
        self._decision_event.clear()

    def await_decision(self, timeout_s: float) -> bool:
        return self._decision_event.wait(timeout=timeout_s)

    def mark_done(self) -> None:
        with self._lock:
            self._sim_done = True
            self._awaiting = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "hour_id": self._hour_id,
                "awaiting_decision": self._awaiting,
                "summary": self._summary,
                "setpoints": {
                    "heating_c": self._setpoints.heating_c,
                    "cooling_c": self._setpoints.cooling_c,
                    "source": self._source,
                },
                "sim_done": self._sim_done,
            }
