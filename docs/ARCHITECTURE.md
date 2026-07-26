# Eco-Loop — System Architecture

## 1. Overview

```
                      shared control state (thread-safe, in-proc)
                   ┌────────────────────────────────────────────┐
                   │ setpoints (heat/cool) · hourly summary ·    │
                   │ awaiting_decision · sim_done                │
                   └──────▲──────────────────────────┬──────────┘
                          │ write (validated+clamped)│ read every timestep
   ┌──────────────────────┴───┐                 ┌────▼─────────────────────┐
   │  MCP TOOL SERVER          │                 │  SIMULATION RUNTIME       │
   │  FastMCP, streamable-http │                 │  pyenergyplus callbacks   │
   │  (main thread of host)    │                 │  (worker thread of host)  │
   └──────────▲───────────────┘                 └────┬─────────────────────┘
              │ tool calls (HTTP)                     │ actuates Schedule:Compact
   ┌──────────┴───────────────┐                 ┌────▼─────────────────────┐
   │  AGENT ORCHESTRATOR       │                 │  EnergyPlus 26.1 engine   │
   │  (separate process)       │                 │  5ZoneAirCooled + Chicago │
   │  MCP client + Ollama      │                 │  EPW, 15-min timesteps    │
   └──────────────────────────┘                 └──────────────────────────┘
```

One host process (`eco_loop/sim/host.py`) runs EnergyPlus in a worker thread and the MCP
server in the main thread, sharing a `ControlState`. The orchestrator is a second process
speaking real MCP over HTTP; the LLM (qwen2.5:7b on Ollama) drives it via native
tool-calling.

## 2. The two-clock problem

EnergyPlus fires the zone-timestep callback every 15 simulated minutes (~ms of wall time);
an 7-8B local LLM needs ~1-3 s per decision. Coupling them 1:1 would slow the sim ~1000×
and make every LLM hiccup a sim stall.

**Solution: decision cadence = 1 simulated hour, actuation cadence = every timestep.**

- The runtime detects the hour rollover inside the callback, publishes a compact summary
  of the finished hour, and blocks on `ControlState.await_decision(timeout=25 s)`.
- The orchestrator polls `get_sensor_summary` (0.5 s), sees `awaiting_decision` + a new
  `hour_id`, asks the LLM, and answers via `set_setpoints` — which resolves the wait.
- **Timeout ⇒ rule fallback, applied by the sim itself.** The sim never waits longer than
  25 s per simulated hour, so the loop is crash-proof by construction: kill the agent,
  kill Ollama, feed it garbage — the building keeps running under the deterministic rule.
- Between decisions the runtime holds the last set-points and actuates them every timestep.

## 3. Handling long simulation logs

The LLM never sees raw EnergyPlus output (a 7-day run logs 672 timestep rows × 19 fields,
plus a multi-MB `.eso`). Instead:

- The runtime aggregates each hour into a ~15-field JSON summary (kWh, temp mean/min/max,
  PMV mean, violation count, occupancy now/next, outdoor °C, carbon intensity).
- `read_runtime_errors` regex-filters `eplusout.err` to the last N warning/error lines;
  the hourly summary embeds a 3-line tail only when non-empty.
- Result: user prompts stay under ~120 tokens — small enough for a 7B model to answer
  in ~1.5 s with temperature 0.2 and `num_predict=200`.

## 4. Prompt engineering & tool-calling reliability

Getting a 7B model to control a building reliably took three mechanisms:

1. **A prescriptive numeric policy in the system prompt.** The first prompt described
   goals qualitatively; the model over-cooled occupied hours (down to 22 °C), missed
   pre-conditioning, and conditioned the empty building — 0% savings, 30 violations.
   The fixed prompt enumerates the cases with exact numbers (unoccupied 15/30, occupied
   or pre-conditioning 21.1/25.0, high-carbon 21.1/25.5, violation recovery ±0.5) and
   hard rules ("NEVER cool below 25.0 while occupied…"). The LLM still decides — it can
   deviate when the feedback warrants — but it deviates from a sane anchor.
2. **A strict output contract.** "You MUST call set_setpoints exactly once. Respond ONLY
   with the tool call", enforced by native tool-calling (not JSON-in-text parsing).
3. **Defense in depth for bad output.** `extract_setpoints` tolerates dict or JSON-string
   arguments and ignores malformed calls; anything invalid → `None` → rule decision in the
   agent; anything out of bounds → clamped in `ControlState`; agent silent → sim-side
   fallback after 25 s. Three independent layers between the LLM and the building.

## 5. Self-correction

Each hourly prompt carries the consequences of the previous decision: kWh consumed, mean
PMV, comfort-violation count, and filtered EnergyPlus warnings. A violation last hour
triggers the policy's recovery case (move 0.5 °C inside the band), so the agent visibly
reacts to its own mistakes — the decision log (`data/decisions.jsonl`) records every
rationale for the dashboard.

## 6. Comfort measurement

- Fanger PMV/PPD computed by EnergyPlus itself (`Zone Thermal Comfort Fanger Model PMV`),
  enabled at prep time by attaching work-efficiency / clothing (0.5 clo) / air-velocity
  schedules to every `People` object.
- Occupied window 08–18 weekdays; band 21.0–25.5 °C, |PMV| ≤ 0.7. A violation = one zone
  outside the band during one occupied timestep.
- The controller aims *inside* the band (heating 21.1, cooling 25.0) — aiming at the exact
  boundary produces float-boundary violations at the 8 am handover.

## 7. Fairness of the comparison

- Identical `run.idf` + `weather.epw` for all three runs; only thermostat schedule values
  are actuated.
- Energy read from E+ meters (`Electricity:Building/HVAC/Plant` — Facility's handle is
  unresolvable in the 26.1 API) and validated against E+'s own tabular end-use report:
  957.0 kWh logged vs 958 reported over 7 days.
- Carbon weighting uses the same bundled diurnal gCO₂/kWh curve for all runs.

## 8. Failure modes & mitigations

| Failure | Mitigation |
|---|---|
| Ollama down / model missing | agent logs the exception, answers with the rule |
| LLM slow | 20 s agent-side timeout, then rule; 25 s sim-side timeout, then fallback |
| Malformed tool call | tolerant parser → rule |
| Insane set-points | clamp to 15–23 / 22–30 °C + 2 °C deadband in `ControlState` |
| Agent process dies | sim applies fallback every hour and finishes the run |
| Unresolvable E+ handle | hard named failure at first callback (fail fast, not silently) |
