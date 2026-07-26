"""Hourly grid carbon-intensity lookup from a bundled CSV (deterministic, offline)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CarbonProfile:
    hourly: tuple[float, ...]  # index 0-23, gCO2/kWh

    @classmethod
    def from_csv(cls, path: str | Path) -> CarbonProfile:
        with open(path, newline="") as f:
            rows = {int(r["hour"]): float(r["gco2_per_kwh"]) for r in csv.DictReader(f)}
        if sorted(rows) != list(range(24)):
            raise ValueError(f"carbon csv {path} must have exactly hours 0-23, got {sorted(rows)}")
        return cls(hourly=tuple(rows[h] for h in range(24)))

    def intensity(self, hour: int) -> float:
        if not 0 <= hour <= 23:
            raise ValueError(f"hour must be 0-23, got {hour}")
        return self.hourly[hour]
