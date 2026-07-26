"""Load config.yaml into frozen dataclasses — single source of truth for all modules."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RunPeriod:
    begin_month: int
    begin_day: int
    end_month: int
    end_day: int


@dataclass(frozen=True)
class Comfort:
    occ_low_c: float
    occ_high_c: float
    pmv_limit: float
    occupied_hours: tuple[int, int]
    occupied_weekdays_only: bool


@dataclass(frozen=True)
class Clamps:
    heat_min: float
    heat_max: float
    cool_min: float
    cool_max: float
    min_deadband: float


@dataclass(frozen=True)
class Setpoints:
    heating_c: float
    cooling_c: float


@dataclass(frozen=True)
class Agent:
    model: str
    fallback_model: str
    decision_timeout_s: float
    max_tool_rounds: int
    ollama_host: str
    temperature: float


@dataclass(frozen=True)
class Mcp:
    host: str
    port: int


@dataclass(frozen=True)
class Config:
    root: Path
    energyplus_dir: Path
    idf_example: str
    weather_glob: str
    run_period: RunPeriod
    timesteps_per_hour: int
    comfort: Comfort
    clamps: Clamps
    baseline_setpoints: Setpoints
    agent: Agent
    mcp: Mcp
    data_dir: Path
    models_dir: Path
    carbon_csv: Path


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text())
    root = path.parent
    # Deployment overrides (Docker/CI) — see Dockerfile / docker-compose.yml.
    if v := os.environ.get("ECO_LOOP_ENERGYPLUS_DIR"):
        raw["energyplus_dir"] = v
    if v := os.environ.get("ECO_LOOP_OLLAMA_HOST"):
        raw["agent"]["ollama_host"] = v
    if v := os.environ.get("ECO_LOOP_MCP_HOST"):
        raw["mcp"]["host"] = v
    return Config(
        root=root,
        energyplus_dir=Path(raw["energyplus_dir"]).expanduser(),
        idf_example=raw["idf_example"],
        weather_glob=raw["weather_glob"],
        run_period=RunPeriod(**raw["run_period"]),
        timesteps_per_hour=raw["timesteps_per_hour"],
        comfort=Comfort(
            occ_low_c=raw["comfort"]["occ_low_c"],
            occ_high_c=raw["comfort"]["occ_high_c"],
            pmv_limit=raw["comfort"]["pmv_limit"],
            occupied_hours=tuple(raw["comfort"]["occupied_hours"]),
            occupied_weekdays_only=raw["comfort"]["occupied_weekdays_only"],
        ),
        clamps=Clamps(**raw["clamps"]),
        baseline_setpoints=Setpoints(**raw["baseline_setpoints"]),
        agent=Agent(**raw["agent"]),
        mcp=Mcp(**raw["mcp"]),
        data_dir=root / raw["paths"]["data_dir"],
        models_dir=root / raw["paths"]["models_dir"],
        carbon_csv=root / raw["carbon_csv"],
    )
