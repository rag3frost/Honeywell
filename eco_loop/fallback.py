"""Deterministic rule-based controller: safety net when the LLM is absent, slow, or invalid."""
from __future__ import annotations

from eco_loop.config import Config, Setpoints

HIGH_CARBON_GKWH = 420.0
UNOCCUPIED = Setpoints(heating_c=15.0, cooling_c=30.0)
# Occupied cooling is the dominant lever (the stock baseline already night/weekend
# setbacks). The real comfort constraint is PMV <= 0.7, not the old 25.5 band —
# hot-week sweep: 26.5 C holds PMV max +0.43, 27.0 C holds +0.54, both well under
# 0.7, while cutting far more kWh than the overcooled 25.5 (PMV -0.02).
OCCUPIED = Setpoints(heating_c=21.1, cooling_c=26.5)
OCCUPIED_HIGH_CARBON = Setpoints(heating_c=21.1, cooling_c=27.0)  # dirty grid: warmer
RECOVERY = Setpoints(heating_c=21.1, cooling_c=25.5)  # pull-down margin for 8am start


def clamp(heating_c: float, cooling_c: float, cfg: Config) -> Setpoints:
    """Always returns a valid pair inside bounds with deadband enforced."""
    c = cfg.clamps
    h = min(max(heating_c, c.heat_min), c.heat_max)
    cl = min(max(cooling_c, c.cool_min), c.cool_max)
    if cl - h < c.min_deadband:
        # push cooling up first, then heating down, staying inside bounds
        cl = min(h + c.min_deadband, c.cool_max)
        h = min(h, cl - c.min_deadband)
        h = max(h, c.heat_min)
    return Setpoints(heating_c=h, cooling_c=cl)


def decide(
    occupied: bool,
    outdoor_c: float,
    carbon_gkwh: float,
    cfg: Config,
    next_occupied: bool = False,
) -> Setpoints:
    if not occupied and next_occupied:
        sp = RECOVERY  # recovery hour: pre-condition so occupancy starts in-band
    elif not occupied:
        sp = UNOCCUPIED
    elif carbon_gkwh > HIGH_CARBON_GKWH:
        sp = OCCUPIED_HIGH_CARBON
    else:
        sp = OCCUPIED
    return clamp(sp.heating_c, sp.cooling_c, cfg)
