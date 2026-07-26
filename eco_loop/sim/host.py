"""Sim host CLI.

baseline/rule: run the simulation directly (fast, no server).
ai: run the simulation in a worker thread + FastMCP server in the main thread so the
orchestrator (separate process) can read state and inject set-points live.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import threading

from eco_loop.config import Config, load_config
from eco_loop.control_state import ControlState
from eco_loop.sim import idf_prep
from eco_loop.sim.runtime import run_simulation

_OUT_CSV = {"baseline": "baseline.csv", "rule": "rule_loop.csv", "ai": "ai_loop.csv"}


def _with_days(cfg: Config, days: int | None) -> Config:
    if days is None:
        return cfg
    rp = dataclasses.replace(cfg.run_period, end_day=cfg.run_period.begin_day + days - 1)
    return dataclasses.replace(cfg, run_period=rp)


def main() -> int:
    parser = argparse.ArgumentParser(description="Eco-Loop sim host")
    parser.add_argument("--mode", choices=("baseline", "rule", "ai"), required=True)
    parser.add_argument("--days", type=int, default=None, help="override run length")
    args = parser.parse_args()

    cfg = _with_days(load_config(), args.days)
    idf_prep.prepare(cfg)  # cheap; guarantees run.idf matches config
    state = ControlState(cfg)
    out_csv = cfg.data_dir / _OUT_CSV[args.mode]

    if args.mode in ("baseline", "rule"):
        rc = run_simulation(cfg, state, args.mode, out_csv)
        print(f"[host] {args.mode} run finished rc={rc} → {out_csv}")
        return rc

    # ai mode: sim in worker thread, MCP server in main thread
    from eco_loop.agent.tools import build_server

    rc_box: dict[str, int] = {}

    def sim():
        rc_box["rc"] = run_simulation(cfg, state, "ai", out_csv)
        print(f"[host] ai sim finished rc={rc_box['rc']} → {out_csv}")
        print("[host] MCP server still serving final snapshot; Ctrl-C to exit")

    t = threading.Thread(target=sim, daemon=True, name="energyplus")
    t.start()
    server = build_server(state, cfg)
    print(f"[host] MCP server on http://{cfg.mcp.host}:{cfg.mcp.port}/mcp")
    server.run(transport="streamable-http")  # blocks; Ctrl-C to stop
    return rc_box.get("rc", 0)


if __name__ == "__main__":
    sys.exit(main())
