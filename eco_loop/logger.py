"""CSV per-timestep logging and JSONL decision logging."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any


class CsvLogger:
    def __init__(self, path: str | Path, fieldnames: list[str]):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self._path.open("w", newline="")
        self._writer = csv.DictWriter(self._f, fieldnames=fieldnames)
        self._writer.writeheader()

    def write_row(self, row: dict[str, Any]) -> None:
        self._writer.writerow(row)
        self._f.flush()  # dashboard tails this file live

    def close(self) -> None:
        self._f.close()


class DecisionLogger:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self._path.open("w")

    def log(
        self,
        hour_id: int,
        summary: dict[str, Any],
        setpoints: tuple[float, float],
        reasoning: str,
        mode: str,
        latency_s: float,
    ) -> None:
        rec = {
            "ts": time.time(),
            "hour_id": hour_id,
            "summary": summary,
            "setpoints": list(setpoints),
            "reasoning": reasoning,
            "mode": mode,
            "latency_s": round(latency_s, 2),
        }
        self._f.write(json.dumps(rec) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()
