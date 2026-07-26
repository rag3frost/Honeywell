"""Turn raw decision-log records into human-readable labels for the dashboard."""
from __future__ import annotations

import re

_PATTERN = re.compile(
    r"^(?P<source>\S+) h(?P<hour>\d+) occ=(?P<occ>True|False) "
    r"next=(?P<next>True|False) carbon=(?P<carbon>[\d.]+) viol=(?P<viol>\d+)$"
)


def parse_reasoning(reasoning: str) -> dict | None:
    """Parse 'llm h23 occ=False next=True carbon=310.0 viol=0' into fields."""
    m = _PATTERN.match(reasoning.strip())
    if not m:
        return None
    return {
        "source": m["source"],
        "hour": int(m["hour"]),
        "occupied": m["occ"] == "True",
        "next_occupied": m["next"] == "True",
        "carbon": float(m["carbon"]),
        "violations": int(m["viol"]),
    }


def action_label(heating_c: float, cooling_c: float, occupied: bool, next_occupied: bool) -> str:
    """Name the control action the set-point pair represents."""
    if not occupied and not next_occupied:
        return "Deep setback (building empty)"
    if not occupied and next_occupied:
        return "Pre-conditioning for occupancy"
    if cooling_c >= 27.0:
        return "Warm ceiling (dirty grid)"
    if cooling_c >= 26.5:
        return "Comfort hold (warm ceiling)"
    if heating_c >= 21.6 or cooling_c <= 25.5:
        return "Comfort hold (tightened)"
    return "Comfort hold"
