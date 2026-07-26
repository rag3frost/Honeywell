"""Occupancy and thermal-comfort evaluation against config targets."""
from __future__ import annotations

from dataclasses import dataclass

from eco_loop.config import Config


@dataclass(frozen=True)
class ComfortResult:
    occupied: bool
    violations: int
    pmv_ok: bool
    detail: str


def is_occupied(weekday: int, hour: int, cfg: Config) -> bool:
    """weekday: 0=Monday .. 6=Sunday. Occupied window is [start, end) hours."""
    start, end = cfg.comfort.occupied_hours
    if cfg.comfort.occupied_weekdays_only and weekday >= 5:
        return False
    return start <= hour < end


def evaluate(
    zone_temps: list[float],
    pmv: float | None,
    weekday: int,
    hour: int,
    cfg: Config,
) -> ComfortResult:
    occupied = is_occupied(weekday, hour, cfg)
    if not occupied:
        return ComfortResult(occupied=False, violations=0, pmv_ok=True, detail="unoccupied")

    low, high = cfg.comfort.occ_low_c, cfg.comfort.occ_high_c
    violations = sum(1 for t in zone_temps if t < low or t > high)
    pmv_ok = pmv is None or abs(pmv) <= cfg.comfort.pmv_limit
    detail = (
        f"{violations} zone(s) outside {low}-{high}C"
        + ("" if pmv_ok else f"; |PMV| {abs(pmv):.2f} > {cfg.comfort.pmv_limit}")
    )
    return ComfortResult(occupied=True, violations=violations, pmv_ok=pmv_ok, detail=detail)
