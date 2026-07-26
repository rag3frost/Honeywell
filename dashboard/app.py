"""Eco-Loop savings dashboard: live loop status, baseline vs rule vs AI, decision log."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard.labels import action_label, parse_reasoning

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RUNS = {"Baseline": "baseline.csv", "Rule loop": "rule_loop.csv", "AI loop": "ai_loop.csv"}
COMFORT_LOW, COMFORT_HIGH = 21.0, 25.5
OCC_START, OCC_END = 8, 18
MCP_URL = "http://127.0.0.1:8765/mcp"

st.set_page_config(page_title="Eco-Loop Building Agents", layout="wide")

# ---------- design tokens (theme-proof) ----------
# Streamlit exposes no theme CSS vars or data-theme attribute, and
# st.context.theme is unreliable across browsers. So every surface derives
# from currentColor — the text color this HTML inherits from Streamlit, which
# is always correct for the active theme: cards are a 6% tint of the text
# color (light gray on light theme, soft light film on dark), borders 14%,
# muted text 62%. The green accent #16a34a holds contrast on both.
st.markdown("""
<style>
.eco-wrap {color:inherit}
.eco-status {display:flex;align-items:center;gap:.6rem;padding:.65rem 1rem;
  border-radius:10px;font-weight:600;
  background:color-mix(in srgb, currentColor 6%, transparent);
  border:1px solid color-mix(in srgb, currentColor 14%, transparent)}
.eco-status code {background:color-mix(in srgb, currentColor 10%, transparent);
  padding:.05rem .3rem;border-radius:4px;color:inherit}
.eco-dot {width:10px;height:10px;border-radius:50%;flex:none}
.eco-dot.live {background:#16a34a;box-shadow:0 0 9px rgba(22,163,74,.6);
  animation:ecopulse 1.6s ease-in-out infinite}
.eco-dot.done {background:#d97706}
.eco-dot.off {background:#8b96a5}
@keyframes ecopulse {50% {opacity:.35}}
@media (prefers-reduced-motion: reduce) {.eco-dot.live {animation:none}}
.eco-pipe {display:flex;align-items:stretch;gap:.5rem;flex-wrap:wrap;
  margin:.8rem 0 .2rem}
.eco-stage {flex:1 1 150px;min-width:150px;
  background:color-mix(in srgb, currentColor 6%, transparent);
  border:1px solid color-mix(in srgb, currentColor 14%, transparent);
  border-radius:12px;padding:.7rem .8rem;transition:border-color .2s ease}
.eco-stage.live {border-color:rgba(22,163,74,.55)}
.eco-stage svg {width:20px;height:20px;stroke:#16a34a;flex:none}
.eco-stage .t {font-weight:700;font-size:.92rem;margin:.35rem 0 .1rem}
.eco-stage .s {font-size:.78rem;line-height:1.25;
  color:color-mix(in srgb, currentColor 62%, transparent)}
.eco-arrow {align-self:center;font-size:1.1rem;flex:none;
  color:color-mix(in srgb, currentColor 45%, transparent)}
.eco-cards {display:flex;gap:.6rem;flex-wrap:wrap;margin:.4rem 0 .6rem}
.eco-card {flex:1 1 170px;min-width:170px;
  background:color-mix(in srgb, currentColor 6%, transparent);
  border:1px solid color-mix(in srgb, currentColor 14%, transparent);
  border-radius:12px;padding:.7rem .9rem}
.eco-card .k {font-size:.75rem;letter-spacing:.06em;text-transform:uppercase;
  color:color-mix(in srgb, currentColor 62%, transparent);margin-bottom:.25rem}
.eco-card .v {font-size:1.3rem;font-weight:700;line-height:1.2}
.eco-card .d {font-size:.78rem;margin-top:.2rem;
  color:color-mix(in srgb, currentColor 62%, transparent)}
.eco-card.hero {border-color:rgba(22,163,74,.55)}
.eco-card.hero .v {color:#16a34a}
</style>
""", unsafe_allow_html=True)

st.title("🌿 Eco-Loop Building Agents — Savings Dashboard")

_ICONS = {
    "building": "<svg viewBox='0 0 24 24' fill='none' stroke-width='2' "
                "stroke-linecap='round'><path d='M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 "
                "0 1 2 2v16M9 7h1m4 0h1M9 11h1m4 0h1M9 15h1m4 0h1'/></svg>",
    "server": "<svg viewBox='0 0 24 24' fill='none' stroke-width='2' "
              "stroke-linecap='round'><rect x='3' y='4' width='18' height='7' rx='2'/>"
              "<rect x='3' y='13' width='18' height='7' rx='2'/>"
              "<path d='M7 7.5h.01M7 16.5h.01'/></svg>",
    "brain": "<svg viewBox='0 0 24 24' fill='none' stroke-width='2' "
             "stroke-linecap='round'><rect x='5' y='5' width='14' height='14' rx='3'/>"
             "<path d='M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3'/>"
             "<rect x='9.5' y='9.5' width='5' height='5' rx='1'/></svg>",
    "target": "<svg viewBox='0 0 24 24' fill='none' stroke-width='2' "
              "stroke-linecap='round'><circle cx='12' cy='12' r='9'/>"
              "<circle cx='12' cy='12' r='5'/><circle cx='12' cy='12' r='1'/></svg>",
}


def live_snapshot(timeout_s: float = 2.0) -> dict | None:
    """Query the sim host's MCP server for its live state; None when offline."""
    async def go():
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(MCP_URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool("get_sensor_summary", {})
                return json.loads(res.content[0].text)

    try:
        return asyncio.run(asyncio.wait_for(go(), timeout_s))
    except Exception:
        return None


snap = live_snapshot()
live = snap is not None and not snap.get("sim_done")

# ---------- live loop status + pipeline ----------
st.subheader("Live loop status")
if live:
    status_html = ("<div class='eco-status'><span class='eco-dot live'></span>"
                   "Simulation LIVE — EnergyPlus co-sim running, MCP server up, "
                   "agent in the loop</div>")
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=5000, key="live-refresh")
elif snap is not None:
    status_html = ("<div class='eco-status'><span class='eco-dot done'></span>"
                   "Sim finished — MCP server still serving the final snapshot</div>")
else:
    status_html = ("<div class='eco-status'><span class='eco-dot off'></span>"
                   "Offline — showing recorded results "
                   "(start with <code>make sim</code> + <code>make agent</code>)</div>")
st.markdown(status_html, unsafe_allow_html=True)

stages = [
    ("building", "EnergyPlus", "5-zone office co-sim"),
    ("server", "MCP server", "sensor-summary tools"),
    ("brain", "LLM agent", "qwen2.5:7b reasons"),
    ("target", "Set-points", "validated + clamped"),
    ("building", "EnergyPlus", "actuated next timestep"),
]
cls = "eco-stage live" if live else "eco-stage"
stage_html = "<div class='eco-pipe'>"
for i, (icon, name, sub) in enumerate(stages):
    if i:
        stage_html += "<div class='eco-arrow'>➜</div>"
    stage_html += (f"<div class='{cls}'>{_ICONS[icon]}"
                   f"<div class='t'>{name}</div><div class='s'>{sub}</div></div>")
stage_html += "</div>"
st.markdown(stage_html, unsafe_allow_html=True)

# ---------- latest AI action ----------
dec_path = DATA / "decisions.jsonl"
dec_recs = (
    [json.loads(line) for line in dec_path.read_text().strip().splitlines()]
    if dec_path.exists() else []
)
st.subheader("Latest AI action")
summary = (snap or {}).get("summary") or {}
sp = (snap or {}).get("setpoints") or {}
if not summary and dec_recs:  # offline: reconstruct from last decision + last csv row
    last = dec_recs[-1]
    parsed = parse_reasoning(last["reasoning"]) or {}
    sp = {"heating_c": last["heating_c"], "cooling_c": last["cooling_c"],
          "source": parsed.get("source", "?")}
    summary = {"hour": parsed.get("hour"), "occupied": parsed.get("occupied"),
               "carbon_gkwh": parsed.get("carbon"),
               "violations_last_hour": parsed.get("violations")}
    ai_df = None
    if (DATA / "ai_loop.csv").exists():
        ai_df = pd.read_csv(DATA / "ai_loop.csv")
    if ai_df is not None and not ai_df.empty:
        row = ai_df.iloc[-1]
        summary.update({"temp_mean": row.temp_mean, "pmv_mean": row.pmv_mean,
                        "outdoor_c": row.outdoor_c, "kwh_hour": None})
if summary:
    label = action_label(
        float(sp.get("heating_c", 0)), float(sp.get("cooling_c", 0)),
        bool(summary.get("occupied")), bool(summary.get("next_hour_occupied",
                                                        summary.get("occupied"))),
    )
    cards = [("hero", "Decision", label,
              f"decided by {sp.get('source', '?').upper()}")]
    cards.append(("", "Set-points",
                  f"{sp.get('heating_c')} / {sp.get('cooling_c')} °C",
                  "heating / cooling"))
    occ_txt = "occupied" if summary.get("occupied") else "empty"
    cards.append(("", "Sim hour", f"{summary.get('hour', '—')}:00", occ_txt))
    if summary.get("temp_mean") is not None:
        io_val = (f"{summary['temp_mean']:.1f} / "
                  f"{summary.get('outdoor_c', float('nan')):.1f} °C")
        cards.append(("", "Indoor / outdoor", io_val, "zone mean vs drybulb"))
    if summary.get("pmv_mean") is not None:
        cards.append(("", "Comfort (PMV)", f"{summary['pmv_mean']:+.2f}",
                      "target |PMV| ≤ 0.7"))
    if summary.get("carbon_gkwh") is not None:
        cards.append(("", "Grid carbon", f"{summary['carbon_gkwh']:.0f} g/kWh",
                      f"{summary.get('violations_last_hour', 0)} violations last hour"))
    html = "<div class='eco-cards'>"
    for extra, k, v, d in cards:
        html += (f"<div class='eco-card {extra}'><div class='k'>{k}</div>"
                 f"<div class='v'>{v}</div><div class='d'>{d}</div></div>")
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)
else:
    st.caption("No decisions recorded yet.")


@st.cache_data(ttl=30)
def load(name: str) -> pd.DataFrame | None:
    p = DATA / name
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    df["t"] = pd.to_datetime(
        {"year": 2026, "month": df.month, "day": df.day, "hour": df.hour.clip(0, 23),
             "minute": df.minute.clip(0, 59)}
    )
    return df


runs = {label: df for label, f in RUNS.items() if (df := load(f)) is not None}
if "Baseline" not in runs:
    st.warning("No baseline yet — run `make baseline` first.")
    st.stop()

base = runs["Baseline"]
base_kwh = base.kwh_step.sum()

# ---------- headline metrics ----------
cols = st.columns(len(runs) + 1)
cols[0].metric("Baseline energy", f"{base_kwh:.0f} kWh")
for i, (label, df) in enumerate([(l, d) for l, d in runs.items() if l != "Baseline"]):
    kwh = df.kwh_step.sum()
    cols[i + 1].metric(
        f"{label} energy", f"{kwh:.0f} kWh", f"{(kwh - base_kwh) / base_kwh * 100:+.1f}%",
        delta_color="inverse",
    )
cols[-1].metric(
    "Comfort violations",
    " / ".join(f"{int(df.violations.sum())}" for df in runs.values()),
    help="baseline / rule / ai — zone-timesteps outside the comfort band while occupied",
)

# ---------- carbon-weighted savings ----------
carbon = pd.read_csv(DATA / "carbon.csv")
carbon_map = dict(zip(carbon.hour, carbon.gco2_per_kwh))
st.subheader("Carbon-weighted emissions")
ccols = st.columns(len(runs))
for i, (label, df) in enumerate(runs.items()):
    kg = (df.kwh_step * df.hour.map(carbon_map)).sum() / 1000
    delta = None
    if label != "Baseline":
        base_kg = (base.kwh_step * base.hour.map(carbon_map)).sum() / 1000
        delta = f"{(kg - base_kg) / base_kg * 100:+.1f}%"
    ccols[i].metric(f"{label} CO₂", f"{kg:.1f} kg", delta, delta_color="inverse")

# ---------- temperature time series ----------
st.subheader("Zone mean temperature (comfort band shaded)")
fig = go.Figure()
for label, df in runs.items():
    fig.add_trace(go.Scatter(x=df.t, y=df.temp_mean, name=label, mode="lines"))
fig.add_hrect(y0=COMFORT_LOW, y1=COMFORT_HIGH, fillcolor="green", opacity=0.08,
              line_width=0, annotation_text="comfort band")
fig.update_layout(height=380, margin={"t": 10, "b": 10}, yaxis_title="°C")
st.plotly_chart(fig, use_container_width=True)

# ---------- energy + setpoints ----------
c1, c2 = st.columns(2)
with c1:
    st.subheader("Hourly energy")
    fig = go.Figure()
    for label, df in runs.items():
        hourly = df.groupby(pd.Grouper(key="t", freq="1h")).kwh_step.sum()
        fig.add_trace(go.Scatter(x=hourly.index, y=hourly.values, name=label, mode="lines"))
    fig.update_layout(height=320, margin={"t": 10, "b": 10}, yaxis_title="kWh/h")
    st.plotly_chart(fig, use_container_width=True)
with c2:
    st.subheader("Applied set-points (controlled runs)")
    fig = go.Figure()
    for label, df in runs.items():
        if label == "Baseline":
            continue
        fig.add_trace(go.Scatter(x=df.t, y=df.cool_sp, name=f"{label} cool", mode="lines"))
        fig.add_trace(go.Scatter(x=df.t, y=df.heat_sp, name=f"{label} heat",
                                 mode="lines", line={"dash": "dot"}))
    fig.update_layout(height=320, margin={"t": 10, "b": 10}, yaxis_title="°C")
    st.plotly_chart(fig, use_container_width=True)

# ---------- PMV distribution ----------
st.subheader("PMV while occupied (|PMV| ≤ 0.7 target)")
fig = go.Figure()
for label, df in runs.items():
    occ = df[df.occupied == 1]
    fig.add_trace(go.Histogram(x=occ.pmv_mean, name=label, opacity=0.6, nbinsx=40))
fig.add_vline(x=-0.7, line_dash="dash", line_color="red")
fig.add_vline(x=0.7, line_dash="dash", line_color="red")
fig.update_layout(height=300, barmode="overlay", margin={"t": 10, "b": 10},
                  xaxis_title="PMV")
st.plotly_chart(fig, use_container_width=True)

# ---------- decision log ----------
if dec_recs:
    st.subheader("Agent decision log")
    rows = []
    for rec in dec_recs:
        parsed = parse_reasoning(rec["reasoning"])
        if parsed:
            rows.append({
                "Hour": f"{parsed['hour']:02d}:00",
                "Decided by": {"llm": "LLM", "rule": "Rule",
                               "rule-in-agent": "Rule (agent)",
                               "fallback": "Fallback"}.get(parsed["source"],
                                                           parsed["source"]),
                "Building": "Occupied" if parsed["occupied"] else (
                    "Empty → occupied soon" if parsed["next_occupied"] else "Empty"),
                "Action": action_label(rec["heating_c"], rec["cooling_c"],
                                       parsed["occupied"], parsed["next_occupied"]),
                "Heat °C": rec["heating_c"],
                "Cool °C": rec["cooling_c"],
                "Grid g/kWh": parsed["carbon"],
                "Violations": parsed["violations"],
            })
        else:  # legacy/free-form reasoning: show as-is
            rows.append({"Hour": "—", "Decided by": "?", "Building": "—",
                         "Action": rec["reasoning"], "Heat °C": rec["heating_c"],
                         "Cool °C": rec["cooling_c"], "Grid g/kWh": None,
                         "Violations": None})
    st.dataframe(pd.DataFrame(rows[::-1]), use_container_width=True, height=340)
