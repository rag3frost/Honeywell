# 🌿 Eco-Loop Building Agents

**A live, autonomous closed-loop control system: an open-source LLM (via MCP) reads real-time
sensor data from a running EnergyPlus building simulation, reasons about comfort / energy /
carbon, and injects thermostat set-points back into the simulation — proving quantifiable
energy savings without sacrificing occupant comfort.**

Live dashboard: https://honeywell-gegblqsajwnzayseqo3h4y.streamlit.app

```
EnergyPlus (5-zone office, live co-sim) ──sensor summary──▶ MCP tool server ──▶ Ollama LLM
        ▲                                                                          │
        └───────────────── validated + clamped set-points ◀── set_setpoints ───────┘
```

## Results (7 July days, Chicago EPW, identical building + weather)

| Run | Energy | vs baseline | Comfort violations |
|---|---|---|---|
| Baseline (stock schedules) | 957 kWh | — | 0 |
| Rule controller | 922 kWh | **−3.6%** | 0 |
| AI loop (qwen2.5:7b) | 924 kWh | **−3.4%** | 0 |

Every kWh number is validated against EnergyPlus's own tabular end-use report (within 0.1%).

## How it works

- **Two decoupled clocks.** EnergyPlus fires a callback every simulated 15 min; the LLM is slow.
  A thread-safe `ControlState` sits between them: the sim reads set-points every timestep
  (fast path, no LLM), the agent updates them once per simulated hour. Between decisions the
  sim holds the last set-points, and a bounded wait + rule fallback means the sim **never
  stalls and never crashes**, whatever the LLM does.
- **Real MCP.** The sim host runs a FastMCP server (`get_sensor_summary`, `set_setpoints`,
  `get_targets`, `get_carbon_intensity`, `read_runtime_errors`, `log_decision`) over
  streamable-http. The orchestrator is a genuine MCP client; the LLM drives it with native
  tool-calling.
- **Self-correction.** Each hourly prompt includes last hour's kWh, PMV, comfort violations
  and the tail of the EnergyPlus `.err` file — the agent reacts to its own mistakes.
- **Safety.** Every set-point is validated and clamped to 15–23 °C heating / 22–30 °C cooling
  with a 2 °C deadband, whether it comes from the LLM, the rule, or a fallback.

## Quick start

Requirements: macOS/Linux, Python 3.12+, [uv](https://docs.astral.sh/uv/),
[EnergyPlus 26.1](https://energyplus.net/downloads) at `~/energyplus-26.1.0`
(path configurable in `config.yaml`), [Ollama](https://ollama.com).

```bash
uv sync                      # install deps
ollama pull qwen2.5:7b       # the brain (~4.7 GB)
make test                    # 50 unit + integration tests (runs a real 1-day sim)

make baseline                # 1) the number to beat  → data/baseline.csv
make rule                    # 2) deterministic loop  → data/rule_loop.csv
make sim                     # 3) AI loop: sim + MCP server (terminal 1)
make agent                   #    LLM orchestrator     (terminal 2)
make dashboard               # 4) savings dashboard   → http://localhost:8501
```

### Docker path (alternative)

```bash
docker compose up --build    # ollama + model pull + sim host + agent + dashboard
```

Brings up the whole stack: `ollama` (pulls qwen2.5:7b on first start), `sim`
(EnergyPlus co-sim + MCP server on :8765), `agent` (orchestrator), and the
`dashboard` on http://localhost:8501. Config is overridable via
`ECO_LOOP_ENERGYPLUS_DIR`, `ECO_LOOP_OLLAMA_HOST`, `ECO_LOOP_MCP_HOST`,
`ECO_LOOP_MCP_URL` env vars. *(Compose file authored/validated for structure;
the local path above is the tested one.)*

## Repository layout

```
eco_loop/
  config.py         # typed config loaded from config.yaml
  carbon.py         # offline hourly grid-carbon profile
  comfort.py        # occupancy + comfort-band/PMV evaluation
  fallback.py       # deterministic safe controller + clamping
  control_state.py  # thread-safe sim⇄agent handoff
  err_parser.py     # filtered EnergyPlus .err tail
  logger.py         # per-timestep CSV logging
  sim/
    idf_prep.py     # builds models/run.idf from the E+ example (eppy), discovers metadata
    runtime.py      # EnergyPlus Python API co-simulation + hourly rollover
    host.py         # CLI: baseline | rule | ai (sim thread + MCP server)
  agent/
    tools.py        # MCP ToolBox + FastMCP server
    prompts.py      # system prompt + tool schema
    orchestrator.py # MCP client + Ollama tool-calling loop
dashboard/app.py    # Streamlit: kWh headline, comfort proof, decision log
docs/               # PRD + architecture
models/             # baseline.idf, run.idf, weather.epw, metadata.json
data/               # carbon.csv + run outputs
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the hard-problem write-up
(long logs, prompt latency, prompt engineering, self-correction).
