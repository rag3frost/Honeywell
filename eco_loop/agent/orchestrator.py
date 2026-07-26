"""Agent orchestrator: Ollama brain + MCP client loop.

Polls the sim's MCP server for a fresh hourly summary, asks the local LLM for
set-points via native tool-calling, validates, and pushes the decision back
through MCP. Any failure (timeout, bad output, dead server) falls back to the
deterministic rule — the sim never waits longer than its own timeout anyway.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from eco_loop import fallback
from eco_loop.agent.prompts import SET_SETPOINTS_TOOL, SYSTEM
from eco_loop.config import Config, load_config

POLL_S = 0.5


def extract_setpoints(tool_calls) -> tuple[float, float] | None:
    """Pull (heating_c, cooling_c) from an Ollama tool-call list; None if absent/invalid."""
    for call in tool_calls or []:
        fn = call.get("function", {}) if isinstance(call, dict) else call.function
        name = fn["name"] if isinstance(fn, dict) else fn.name
        if name != "set_setpoints":
            continue
        args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                continue
        try:
            return float(args["heating_c"]), float(args["cooling_c"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def build_user_prompt(s: dict[str, Any]) -> str:
    sp = s.get("setpoints", {})
    nxt = "OCCUPIED" if s.get("next_hour_occupied") else "unoccupied"
    now = "OCCUPIED" if s.get("occupied") else "unoccupied"
    lines = [
        f"Hour {s.get('hour')} — now: {now}, next hour: {nxt}",
        (f"outdoor {s.get('outdoor_c')}C, indoor mean {s.get('temp_mean')}C, "
        f"PMV {s.get('pmv_mean')}"),
        f"last hour: {s.get('kwh_hour')} kWh, violations: {s.get('violations_last_hour')}",
        f"grid carbon: {s.get('carbon_gkwh')} gCO2/kWh",
        f"current set-points: heat {sp.get('heating_c')} / cool {sp.get('cooling_c')}",
    ]
    if s.get("err_tail"):
        lines.append("EnergyPlus warnings: " + "; ".join(s["err_tail"]))
    lines.append("Decide set-points for the next hour. Call set_setpoints now.")
    return "\n".join(lines)


def ask_llm(cfg: Config, summary: dict[str, Any]) -> tuple[float, float] | None:
    import ollama

    client = ollama.Client(host=cfg.agent.ollama_host)
    resp = client.chat(
        model=cfg.agent.model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_user_prompt(summary)},
        ],
        tools=[SET_SETPOINTS_TOOL],
        options={"temperature": cfg.agent.temperature, "num_predict": 200},
    )
    return extract_setpoints(resp.get("message", {}).get("tool_calls"))


def rule_decision(cfg: Config, s: dict[str, Any]) -> tuple[float, float]:
    sp = fallback.decide(
        bool(s.get("occupied")),
        float(s.get("outdoor_c") or 20.0),
        float(s.get("carbon_gkwh") or 0.0),
        cfg,
        next_occupied=bool(s.get("next_hour_occupied")),
    )
    return sp.heating_c, sp.cooling_c


async def run(cfg: Config) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = os.environ.get("ECO_LOOP_MCP_URL") or f"http://{cfg.mcp.host}:{cfg.mcp.port}/mcp"
    print(f"[agent] connecting to MCP {url}")
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[agent] connected; entering decision loop")
            last_hour_id = 0
            while True:
                res = await session.call_tool("get_sensor_summary", {})
                snap = json.loads(res.content[0].text)
                if snap.get("sim_done"):
                    print("[agent] sim done; exiting")
                    return
                if not snap.get("awaiting_decision") or snap["hour_id"] == last_hour_id:
                    await asyncio.sleep(POLL_S)
                    continue

                last_hour_id = snap["hour_id"]
                summary = snap.get("summary") or {}
                decision = None
                source = "llm"
                try:
                    decision = await asyncio.wait_for(
                        asyncio.to_thread(ask_llm, cfg, summary),
                        timeout=cfg.agent.decision_timeout_s - 5,
                    )
                except Exception as e:  # timeout, ollama down, bad response
                    print(f"[agent] LLM failed ({type(e).__name__}: {e}); using rule")
                if decision is None:
                    decision = rule_decision(cfg, summary)
                    source = "rule-in-agent"

                heat, cool = decision
                applied = await session.call_tool(
                    "set_setpoints", {"heating_c": heat, "cooling_c": cool}
                )
                applied = json.loads(applied.content[0].text)
                await session.call_tool(
                    "log_decision",
                    {
                        "reasoning": f"{source} h{summary.get('hour')} "
                        f"occ={summary.get('occupied')} next={summary.get('next_hour_occupied')} "
                        f"carbon={summary.get('carbon_gkwh')} viol={summary.get('violations_last_hour')}",
                        "heating_c": applied["heating_c"],
                        "cooling_c": applied["cooling_c"],
                        "hour_id": last_hour_id,
                    },
                )
                print(
                    f"[agent] hour_id={last_hour_id} {source}: "
                    f"heat={applied['heating_c']} cool={applied['cooling_c']}"
                    + (" (clamped)" if applied.get("clamped") else "")
                )


def main() -> int:
    cfg = load_config()
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
