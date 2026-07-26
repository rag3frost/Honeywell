"""EnergyPlus co-simulation runtime.

Runs E+ with a timestep callback that reads sensors, logs every step, and at each
simulated-hour boundary either applies rule decisions ("rule" mode) or publishes a
summary and waits (bounded) for the agent ("ai" mode). Set-points are injected by
actuating the thermostat set-point schedules discovered in metadata.json.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

from eco_loop import fallback
from eco_loop.carbon import CarbonProfile
from eco_loop.comfort import evaluate, is_occupied
from eco_loop.config import Config
from eco_loop.control_state import ControlState
from eco_loop.err_parser import tail_errors
from eco_loop.logger import CsvLogger

MODES = ("baseline", "rule", "ai")
J_PER_KWH = 3_600_000.0

# E+ 26.1 quirk: "Electricity:Facility" is meter index 0 and get_meter_handle
# returns -1 for it. Building + HVAC + Plant covers all loads in this model
# (no exterior lights); verified against the tabular end-use report.
ELEC_METERS = ("Electricity:Building", "Electricity:HVAC", "Electricity:Plant")


def _weekday(ep_day_of_week: int) -> int:
    """E+ day_of_week: 1=Sunday..7=Saturday → python weekday 0=Monday..6=Sunday."""
    return (ep_day_of_week + 5) % 7


class _Handles:
    """Resolved once, after api_data_fully_ready. Any -1 is a hard, named failure."""

    def __init__(self, api, s, zones: list[str], people: list[str], meta: dict):
        ex = api.exchange
        self.zone_temp = {
            z: ex.get_variable_handle(s, "Zone Mean Air Temperature", z) for z in zones
        }
        self.pmv = {
            p: ex.get_variable_handle(s, "Zone Thermal Comfort Fanger Model PMV", p)
            for p in people
        }
        self.outdoor = ex.get_variable_handle(
            s, "Site Outdoor Air Drybulb Temperature", "Environment"
        )
        self.elec_meters = {m: ex.get_meter_handle(s, m) for m in ELEC_METERS}
        self.heat_act = ex.get_actuator_handle(
            s, "Schedule:Compact", "Schedule Value", meta["heat_sched"]
        )
        self.cool_act = ex.get_actuator_handle(
            s, "Schedule:Compact", "Schedule Value", meta["cool_sched"]
        )
        bad = [name for name, h in self._named() if h == -1]
        if bad:
            raise RuntimeError(f"unresolved EnergyPlus handles: {bad}")

    def _named(self):
        yield from ((f"temp:{z}", h) for z, h in self.zone_temp.items())
        yield from ((f"pmv:{p}", h) for p, h in self.pmv.items())
        yield ("outdoor", self.outdoor)
        yield from ((f"meter:{m}", h) for m, h in self.elec_meters.items())
        yield ("actuator:heat", self.heat_act)
        yield ("actuator:cool", self.cool_act)


class _HourBuffer:
    def __init__(self):
        self.kwh = 0.0
        self.temps: list[float] = []
        self.pmvs: list[float] = []
        self.violations = 0

    def add(self, kwh: float, temp_mean: float, pmv: float, violations: int):
        self.kwh += kwh
        self.temps.append(temp_mean)
        self.pmvs.append(pmv)
        self.violations += violations


def run_simulation(cfg: Config, state: ControlState, mode: str, out_csv: Path) -> int:
    assert mode in MODES, f"mode must be one of {MODES}"
    sys.path.insert(0, str(cfg.energyplus_dir))
    from pyenergyplus.api import EnergyPlusAPI

    meta = json.loads((cfg.models_dir / "metadata.json").read_text())
    zones, people = meta["zones"], meta["people"]
    carbon = CarbonProfile.from_csv(cfg.carbon_csv)
    out_dir = cfg.root / f"output_{mode}"
    err_path = out_dir / "eplusout.err"

    fields = (
        ["month", "day", "hour", "minute", "weekday", "occupied", "outdoor_c"]
        + [f"t_{z}" for z in zones]
        + ["temp_mean", "pmv_mean", "kwh_step", "heat_sp", "cool_sp", "violations", "mode"]
    )
    log = CsvLogger(out_csv, fields)

    api = EnergyPlusAPI()
    s = api.state_manager.new_state()
    ex = api.exchange

    for z in zones:
        ex.request_variable(s, "Zone Mean Air Temperature", z)
    for p in people:
        ex.request_variable(s, "Zone Thermal Comfort Fanger Model PMV", p)
    ex.request_variable(s, "Site Outdoor Air Drybulb Temperature", "Environment")

    ctx = {"handles": None, "last_hour": None, "buf": _HourBuffer()}

    def on_hour_rollover(finished_hour: int, weekday: int, hour: int, outdoor_c: float):
        """Called at the first timestep of a new hour; decides set-points for it."""
        buf = ctx["buf"]
        occupied_now = is_occupied(weekday, hour, cfg)
        next_wd = weekday if hour < 23 else (weekday + 1) % 7
        next_occ = is_occupied(next_wd, (hour + 1) % 24, cfg)
        carbon_now = carbon.intensity(hour)
        if mode == "rule":
            sp = fallback.decide(occupied_now, outdoor_c, carbon_now, cfg, next_occupied=next_occ)
            state.set_setpoints(sp.heating_c, sp.cooling_c, source="rule")
        elif mode == "ai":
            sp_cur = state.get_setpoints()
            summary = {
                "finished_hour": finished_hour,
                "kwh_hour": round(buf.kwh, 3),
                "temp_mean": round(statistics.fmean(buf.temps), 2) if buf.temps else None,
                "temp_min": round(min(buf.temps), 2) if buf.temps else None,
                "temp_max": round(max(buf.temps), 2) if buf.temps else None,
                "pmv_mean": round(statistics.fmean(buf.pmvs), 2) if buf.pmvs else None,
                "violations_last_hour": buf.violations,
                "hour": hour,
                "weekday": weekday,
                "occupied": occupied_now,
                "next_hour_occupied": next_occ,
                "outdoor_c": round(outdoor_c, 1),
                "carbon_gkwh": carbon_now,
                "setpoints": {"heating_c": sp_cur.heating_c, "cooling_c": sp_cur.cooling_c},
                "err_tail": tail_errors(err_path, max_lines=3),
            }
            state.publish_hour(summary)
            if not state.await_decision(cfg.agent.decision_timeout_s):
                sp = fallback.decide(occupied_now, outdoor_c, carbon_now, cfg, next_occupied=next_occ)
                state.set_setpoints(sp.heating_c, sp.cooling_c, source="fallback")
        ctx["buf"] = _HourBuffer()

    def cb(st):
        if ex.warmup_flag(st) or not ex.api_data_fully_ready(st):
            return
        if ctx["handles"] is None:
            ctx["handles"] = _Handles(api, st, zones, people, meta)
        h = ctx["handles"]

        weekday = _weekday(ex.day_of_week(st))
        hour, minute = ex.hour(st), ex.minutes(st)
        month, day = ex.month(st), ex.day_of_month(st)

        if ctx["last_hour"] is not None and hour != ctx["last_hour"]:
            outdoor_now = ex.get_variable_value(st, h.outdoor)
            on_hour_rollover(ctx["last_hour"], weekday, hour, outdoor_now)
        ctx["last_hour"] = hour

        if mode != "baseline":
            sp = state.get_setpoints()
            ex.set_actuator_value(st, h.heat_act, sp.heating_c)
            ex.set_actuator_value(st, h.cool_act, sp.cooling_c)
        else:
            sp = state.get_setpoints()

        temps = [ex.get_variable_value(st, h.zone_temp[z]) for z in zones]
        pmvs = [ex.get_variable_value(st, h.pmv[p]) for p in people]
        outdoor_c = ex.get_variable_value(st, h.outdoor)
        # get_meter_value returns joules for the current timestep (not cumulative)
        meter_j = sum(ex.get_meter_value(st, mh) for mh in h.elec_meters.values())
        kwh_step = meter_j / J_PER_KWH

        temp_mean = statistics.fmean(temps)
        pmv_mean = statistics.fmean(pmvs)
        comfort = evaluate(temps, pmv_mean, weekday, hour, cfg)
        ctx["buf"].add(kwh_step, temp_mean, pmv_mean, comfort.violations)

        log.write_row(
            {
                "month": month, "day": day, "hour": hour, "minute": minute,
                "weekday": weekday, "occupied": int(comfort.occupied),
                "outdoor_c": round(outdoor_c, 2),
                **{f"t_{z}": round(t, 2) for z, t in zip(zones, temps)},
                "temp_mean": round(temp_mean, 2), "pmv_mean": round(pmv_mean, 3),
                "kwh_step": round(kwh_step, 4),
                "heat_sp": sp.heating_c, "cool_sp": sp.cooling_c,
                "violations": comfort.violations, "mode": mode,
            }
        )

    api.runtime.callback_begin_zone_timestep_after_init_heat_balance(s, cb)
    rc = api.runtime.run_energyplus(
        s,
        ["-w", str(cfg.models_dir / "weather.epw"), "-d", str(out_dir),
         str(cfg.models_dir / "run.idf")],
    )
    log.close()
    state.mark_done()
    return rc
