"""Filtered tail of EnergyPlus eplusout.err — the LLM only ever sees this, never raw logs."""
from __future__ import annotations

from pathlib import Path

_MARKERS = ("** Warning", "** Severe")


def tail_errors(err_path: str | Path, max_lines: int = 10) -> list[str]:
    err_path = Path(err_path)
    if not err_path.exists():
        return []
    seen: dict[str, None] = {}  # ordered dedupe
    for line in err_path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if any(m in stripped for m in _MARKERS):
            seen[stripped] = None
    return list(seen)[-max_lines:]
