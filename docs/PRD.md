# PRD — Eco-Loop Building Agents

**A live, autonomous closed-loop control system where an open-source LLM (via an MCP tool bus) reads real-time sensor data from an EnergyPlus building simulation, reasons about comfort/energy/carbon targets, and injects control set-points back into the running simulation — proving quantifiable energy savings without sacrificing occupant comfort.**

- **Type:** Hackathon Physical-AI Proof-of-Concept (PoC)
- **Language:** Python 3.11+
- **Cost:** $0 — every component is free / open-source / local
- **Status:** Planning (no code written yet)

---

## 1. Objective & Success Criteria

Build a dynamic feedback loop: **EnergyPlus → LLM → EnergyPlus**. The agent must ingest live metrics, evaluate them against targets, and continuously push forward control actions that reduce total kWh while keeping occupants comfortable.

This PRD maps directly to the hackathon evaluation rubric:

| Weight | Rubric Criterion | How this design wins it |
|---|---|---|
| 30% | **System Integration** — runs long, no crash | True co-simulation via EnergyPlus Python API; every LLM call wrapped in try/except with a rule-based fallback so the sim never stalls or crashes |
| 25% | **Energy Efficiency** — kWh cut vs baseline | Identical building + weather run twice (baseline schedule vs AI loop); dashboard proves % kWh reduction |
| 20% | **Thermal Comfort** — balance, not sacrifice | PMV/PPD tracked every step; agent given hard comfort bounds; set-points clamped to a safe band; comfort violations penalized in the agent's own reasoning |
| 15% | **Agentic Autonomy & Code** — MCP, tool-calling, self-correction | Real MCP server exposing tools; LLM drives via native function-calling; self-correction from runtime error/comfort feedback |
| 10% | **Presentation & Docs** — architecture, viz | Streamlit dashboard + architecture doc + demo video |

**Definition of done:** `docker compose up` (or documented local run) executes the full loop end-to-end over a multi-day simulation, produces baseline vs AI CSVs, and renders a dashboard showing a positive kWh reduction with PMV held inside comfort bounds.

---

## 2. Assumptions (confirm or override)

1. **Dev machine:** macOS (Apple Silicon) with ≥16 GB RAM — enough to run a 7–8B LLM locally via Ollama with Metal acceleration.
2. **Building model:** start from an EnergyPlus example file that already has HVAC + thermostat set-point schedules (candidate: `5ZoneAirCooled.idf`, small & fast). Fall back to a DOE small-office prototype if needed.
3. **Weather:** a free DOE `.epw` weather file; the *same* file is used for baseline and AI runs so the comparison is fair.
4. **Simulation horizon:** a representative run period (e.g. 3–7 summer days) — long enough to prove savings, short enough to iterate.
5. **Carbon signal:** a bundled offline hourly grid-carbon-intensity CSV (representative diurnal curve). Keeps the demo deterministic and network-independent; a live API (ElectricityMaps/WattTime) is an optional stretch.
6. **LLM cadence:** the agent reasons once per **simulated hour**, not every timestep — this is the key latency/robustness decision (see §5).

---

## 3. Architecture Overview

```
                          shared control state (thread-safe)
                       ┌──────────────────────────────────────┐
                       │  setpoints_heating / setpoints_cooling │
                       └────────▲───────────────────┬──────────┘
                                │ write             │ read
   ┌───────────────────────┐    │                   │     ┌──────────────────────┐
   │   AGENT ORCHESTRATOR   │────┘                   └────▶│  SIMULATION RUNTIME   │
   │ (Ollama brain + MCP    │                              │  EnergyPlus Python API │
   │  client)               │◀─── sensor summary (JSON) ───│  timestep callbacks    │
   └──────────┬────────────┘                              └──────────┬────────────┘
              │ tool calls (stdio / in-proc)                          │
              ▼                                                       ▼
   ┌───────────────────────┐                              ┌──────────────────────┐
   │  MCP TOOL SERVER      │                              │  EnergyPlus engine    │
   │  get_sensor_summary   │                              │  + .idf building model │
   │  set_setpoints        │                              │  + .epw weather        │
   │  get_targets          │                              └──────────────────────┘
   │  get_carbon_intensity │
   │  read_runtime_errors  │
   │  log_decision         │
   └───────────────────────┘
```

**Core insight — decoupling the two clocks.** EnergyPlus fires callbacks thousands of times (every 10–15 sim-minutes). The LLM is slow (seconds per call). We decouple them through a **shared control-state object**:

- The **simulation runtime** reads/writes that state *every timestep* (fast, no LLM in the hot path).
- The **agent** updates that state on an *hourly* cadence (slow, LLM-driven).

Between agent decisions the sim simply holds the last set-points. This is what keeps the loop real-time-stable and crash-free (30% of the score).

---

## 4. Components

Each unit has one job, a clear interface, and is independently testable.

### 4.1 Simulation Runtime (`sim/runtime.py`)
- Wraps the **EnergyPlus Python API** (`pyenergyplus`).
- Registers a timestep callback (`callback_begin_zone_timestep_after_init_heat_balance`).
- Guards with `api_data_fully_ready()` and the warm-up flag before touching handles.
- **Reads** sensor handles: zone mean air temp, zone relative humidity, facility electricity meter, Fanger PMV/PPD.
- **Writes** actuator handles: heating & cooling thermostat set-point schedules (clamped to a safe band, e.g. 18–28 °C).
- Pushes a per-timestep record to the data logger.
- Exposes: `run(idf, epw, control_state, logger) -> results`.

### 4.2 MCP Tool Server (`agent/mcp_server.py`)
Real MCP server (Python `mcp` SDK) exposing the agent's toolbox. Satisfies the MCP requirement genuinely and is demoable in the video. Tools:
- `get_sensor_summary()` → compact JSON (rolling mean/min/max temp, kWh this hour, PMV, comfort-violation count).
- `set_setpoints(heating_c, cooling_c)` → writes to shared control state (validated + clamped).
- `get_targets()` → comfort band, peak-demand threshold, PMV limits.
- `get_carbon_intensity(hour)` → gCO₂/kWh for current hour from bundled CSV.
- `read_runtime_errors()` → parses EnergyPlus `.err` file, returns only top-N warnings/errors.
- `log_decision(reasoning, actions)` → records the agent's rationale for the dashboard/report.

### 4.3 Agent Orchestrator (`agent/orchestrator.py`)
- MCP **client** + **Ollama** reasoning engine (Llama 3.1 8B / Qwen2.5 7B, native tool-calling).
- On each hourly tick: pull sensor summary + targets + carbon → prompt LLM → LLM calls `set_setpoints`.
- **Self-correction:** if last hour violated comfort or the `.err` file shows warnings, feed that back so the agent adjusts.
- **Robustness:** invalid/timeout/malformed tool output → clamp or fall back to a safe rule-based set-point; log; never crash.
- Low temperature (~0.2), small `max_tokens`, tight system prompt for latency + determinism.

### 4.4 Data Logger (`common/logger.py`)
- Appends per-timestep rows to CSV: `time, zone_temp, rh, kWh, pmv, ppd, heat_sp, cool_sp, carbon, mode`.
- One file per run (`baseline.csv`, `ai_loop.csv`).

### 4.5 Baseline Runner (`sim/baseline.py`)
- Runs the same IDF/EPW with **no** agent overrides (stock schedules) → `baseline.csv`.
- Guarantees an apples-to-apples comparison.

### 4.6 Savings Dashboard (`dashboard/app.py`)
- **Streamlit** app reading both CSVs.
- Panels: total kWh baseline vs AI (+ **% reduction** headline), time-series temp with comfort band shaded, PMV/PPD distribution (proof comfort held), carbon-weighted savings, agent decision log.
- Exports a static HTML/PNG summary for the repo + video.

---

## 5. Data Flow (one hourly cycle)

1. EnergyPlus advances timesteps; runtime logs sensors and applies current set-points every step.
2. On the hour, orchestrator calls `get_sensor_summary` + `get_targets` + `get_carbon_intensity`.
3. Orchestrator builds a **compact** prompt (summarized aggregates, never raw logs) and asks the LLM.
4. LLM reasons (comfort vs energy vs carbon) and calls `set_setpoints(heating_c, cooling_c)`.
5. Values are validated/clamped and written to shared control state.
6. Next timestep, the runtime reads the new set-points and actuates them. Loop repeats.

---

## 6. Handling the Hard Problems (deliverable #4 requires this)

- **Long simulation logs:** the LLM never sees raw output. Tools return *summarized aggregates* (rolling stats, counts) and *filtered* `.err` lines (regex, top-N). Keeps prompts tiny.
- **Prompt latency:** hourly cadence + local small model + low max-tokens + set-point hold between calls. Optional async agent thread as a stretch.
- **Prompt engineering:** system prompt fixes role ("building energy manager"), hard safety bounds, target definitions, tool schemas, and a strict "you must call `set_setpoints`" output contract. Low temperature.
- **Self-correction:** comfort violations and `.err` warnings are fed back into the next prompt; the agent explicitly reacts to its own prior mistakes.

---

## 7. Tech Stack (100% free)

| Layer | Tool | Notes |
|---|---|---|
| Simulation | **EnergyPlus** + `pyenergyplus` API | Free (NREL/DOE); ships the runtime Python API |
| IDF helper | `eppy` | Free; inspect/modify `.idf` if needed |
| LLM runtime | **Ollama** | Free, local, Metal-accelerated |
| LLM model | **Llama 3.1 8B** or **Qwen2.5 7B** | Free, open weights, native tool-calling |
| Agent protocol | **MCP** (`mcp` Python SDK) | Free; real tool bus |
| Comfort | EnergyPlus Fanger PMV/PPD output | Built-in |
| Dashboard | **Streamlit** + **Plotly** | Free |
| Packaging | **Docker Compose** (`nrel/energyplus` + `ollama/ollama` images) | Free; deployment-ready |
| Carbon data | Bundled offline CSV | Deterministic; live API optional |

---

## 8. Milestones (build order)

**M0 — Skeleton & data flow (proves the plumbing).**
Run EnergyPlus via the Python API, read one sensor, actuate one set-point on a fixed schedule (no LLM). Log to CSV. → *This retires the biggest technical risk first.*

**M1 — Baseline run + dashboard shell.**
Baseline CSV + Streamlit reading it. Establishes the number we must beat.

**M2 — Tools + rule-based controller.**
Implement MCP tools; drive set-points with a simple deterministic rule. Full closed loop working *without* the LLM — a safe fallback that already satisfies "no crash."

**M3 — Swap in the LLM brain.**
Ollama + tool-calling replaces the rule engine (which stays as fallback). Hourly cadence, validation, self-correction.

**M4 — Prove savings + comfort.**
Tune targets/prompt; confirm kWh down and PMV in band. Finalize dashboard with % reduction headline.

**M5 — Package & deliverables.**
Dockerfile/compose, README, architecture doc, demo video, presentation slides.

Each milestone is independently demoable — if time runs out, the last completed milestone is still a working submission.

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| EnergyPlus runtime actuation is fiddly (handles, warm-up) | Blocks everything | Retire in M0 before anything else; use documented `api_data_fully_ready` guard |
| LLM too slow / stalls the sim | Fails "no crash" (30%) | Hourly cadence, set-point hold, timeout + fallback, small local model |
| LLM emits invalid set-points | Comfort/crash | Validate + clamp to safe band; rule-based fallback |
| Agent saves energy by freezing occupants | Loses 20% | Hard comfort bounds in prompt + clamp; PMV penalized in reasoning; dashboard proves band held |
| Model can't do reliable tool-calling | Agentic score | Use Llama 3.1 / Qwen2.5 (strong tool-calling); strict output contract; retry-then-fallback |
| Docker/EnergyPlus image friction | Deployment | Provide *both* a local venv path and Docker path in README |

---

## 10. Deployment / Reproducibility

- **Local path:** `pip install -e .`, install EnergyPlus, `ollama pull llama3.1`, `make baseline && make run && make dashboard`.
- **Container path:** `docker compose up` — services: `energyplus-agent` (orchestrator + sim) and `ollama` (model server); dashboard exposed on a port.
- README documents both, plus expected outputs and how to read the savings number.

---

## 11. Repository Layout

```
eco-loop-building-agents/
├── README.md
├── pyproject.toml
├── Makefile
├── docker-compose.yml
├── models/
│   ├── baseline.idf            # base building
│   ├── ai_modified.idf         # runtime-generated variant(s)
│   └── weather.epw
├── sim/
│   ├── runtime.py              # EnergyPlus Python API wrapper + callbacks
│   └── baseline.py             # no-agent baseline run
├── agent/
│   ├── mcp_server.py           # MCP tool server
│   ├── orchestrator.py         # Ollama brain + MCP client + loop
│   ├── prompts.py              # system prompt / tool schemas
│   └── fallback.py             # rule-based safe controller
├── common/
│   ├── control_state.py        # thread-safe shared set-points
│   ├── logger.py               # CSV logging
│   └── carbon.csv              # offline grid intensity
├── dashboard/
│   └── app.py                  # Streamlit savings dashboard
├── docs/
│   ├── PRD.md
│   └── ARCHITECTURE.md         # deliverable #4
└── data/
    ├── baseline.csv
    └── ai_loop.csv
```

---

## 12. Deliverables Mapping (submission checklist)

| Required deliverable | Produced by |
|---|---|
| Fully functional source code (unified Python) | entire repo |
| Building models (base + runtime-modified `.idf`) | `models/` |
| Quantitative savings dashboard (% kWh, comfort held) | `dashboard/app.py` + `data/*.csv` |
| System architecture document (tool-calling, prompts, latency, long logs) | `docs/ARCHITECTURE.md` |
| PoC demo video (≤3 min, loop live) | recorded from dashboard + console |
| Presentation slides | provided template |

---

## 13. Open Questions

1. Confirm the assumptions in §2 (machine/RAM, building file, run horizon).
2. Live carbon API or bundled CSV? (Recommend CSV for a robust demo.)
3. Streamlit interactive dashboard vs static HTML export? (Recommend Streamlit, export static for the video.)
4. Async agent thread — build it, or keep the simpler inline-throttled loop? (Recommend inline for robustness first.)
