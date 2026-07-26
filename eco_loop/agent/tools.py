"""MCP tool server: the agent's toolbox over the shared control state.

ToolBox holds the logic (testable without HTTP); build_server wraps it in a
FastMCP server exposed over streamable-http for the orchestrator process.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from eco_loop.carbon import CarbonProfile
from eco_loop.config import Config
from eco_loop.control_state import ControlState
from eco_loop.err_parser import tail_errors


class ToolBox:
    def __init__(self, state: ControlState, cfg: Config, decisions_path: Path | None = None):
        self._state = state
        self._cfg = cfg
        self._carbon = CarbonProfile.from_csv(cfg.carbon_csv)
        self.decisions_path = decisions_path or (cfg.data_dir / "decisions.jsonl")

    def get_sensor_summary(self) -> dict[str, Any]:
        """Latest hourly sensor summary plus current set-points and loop status."""
        return self._state.snapshot()

    def set_setpoints(self, heating_c: float, cooling_c: float) -> dict[str, Any]:
        """Apply thermostat set-points (°C). Values outside safe bounds are clamped."""
        sp = self._state.set_setpoints(heating_c, cooling_c, source="ai")
        return {
            "heating_c": sp.heating_c,
            "cooling_c": sp.cooling_c,
            "clamped": (sp.heating_c, sp.cooling_c) != (heating_c, cooling_c),
        }

    def get_targets(self) -> dict[str, Any]:
        """Comfort band, PMV limit, and the hard set-point bounds."""
        c, cl = self._cfg.comfort, self._cfg.clamps
        return {
            "comfort_band_c": [c.occ_low_c, c.occ_high_c],
            "pmv_limit": c.pmv_limit,
            "occupied_hours": list(c.occupied_hours),
            "setpoint_bounds": {
                "heating_c": [cl.heat_min, cl.heat_max],
                "cooling_c": [cl.cool_min, cl.cool_max],
                "min_deadband": cl.min_deadband,
            },
        }

    def get_carbon_intensity(self, hour: int) -> float:
        """Grid carbon intensity (gCO2/kWh) for the given hour of day."""
        return self._carbon.intensity(hour)

    def read_runtime_errors(self, max_lines: int = 5) -> list[str]:
        """Most recent EnergyPlus warning/error lines from the live run."""
        return tail_errors(self._cfg.root / "output_ai" / "eplusout.err", max_lines=max_lines)

    def log_decision(
        self,
        reasoning: str,
        heating_c: float,
        cooling_c: float,
        hour_id: int | None = None,
    ) -> dict[str, Any]:
        """Record the agent's rationale for the dashboard/report.

        Pass hour_id — the id of the summary the agent acted on — so the record is
        pinned to that hour. Omitting it samples live state, which can race the sim
        thread's hourly counter and mislabel the row.
        """
        rec = {
            "ts": time.time(),
            "hour_id": hour_id if hour_id is not None else self._state.snapshot()["hour_id"],
            "reasoning": reasoning,
            "heating_c": heating_c,
            "cooling_c": cooling_c,
        }
        self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with self.decisions_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return {"logged": True}


def build_server(state: ControlState, cfg: Config):
    from mcp.server.fastmcp import FastMCP

    box = ToolBox(state, cfg)
    server = FastMCP("eco-loop", host=cfg.mcp.host, port=cfg.mcp.port)
    for fn in (
        box.get_sensor_summary,
        box.set_setpoints,
        box.get_targets,
        box.get_carbon_intensity,
        box.read_runtime_errors,
        box.log_decision,
    ):
        server.tool(name=fn.__name__, description=fn.__doc__)(fn)
    return server
