"""Prepare the building model: copy the E+ example, apply run-period/comfort edits via eppy,
and emit metadata (zones, people, schedule names) discovered from the IDF — never hardcoded.

Outputs: models/baseline.idf, models/run.idf, models/weather.epw, models/metadata.json
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from eppy.modeleditor import IDF

from eco_loop.config import Config, load_config

# Schedules added so People objects can compute Fanger PMV.
_COMFORT_SCHEDULES = [
    ("Work Eff Sch", "Any Number", 0.0),      # work efficiency (0 = all metabolic heat)
    ("Clothing Sch", "Any Number", 0.5),      # summer clothing, clo
    ("Air Velo Sch", "Any Number", 0.137),    # indoor air velocity, m/s
]


@dataclass(frozen=True)
class PrepResult:
    baseline_idf: Path
    run_idf: Path
    weather_epw: Path
    metadata: dict


def _find_setpoint_schedules(idf: IDF) -> tuple[str, str]:
    """Discover heating/cooling schedule names from the DualSetpoint thermostat objects."""
    duals = idf.idfobjects["THERMOSTATSETPOINT:DUALSETPOINT"]
    if not duals:
        raise RuntimeError("no ThermostatSetpoint:DualSetpoint found in IDF")
    heat = duals[0].Heating_Setpoint_Temperature_Schedule_Name
    cool = duals[0].Cooling_Setpoint_Temperature_Schedule_Name
    if not heat or not cool:
        raise RuntimeError(f"dual setpoint schedules missing: heat={heat!r} cool={cool!r}")
    return heat, cool


def _conditioned_zones(idf: IDF) -> list[str]:
    """Zones that have a thermostat — the plenum has none and must not be counted."""
    return [t.Zone_or_ZoneList_Name for t in idf.idfobjects["ZONECONTROL:THERMOSTAT"]]


def _add_any_number_limits(idf: IDF) -> None:
    if not any(
        o.Name.lower() == "any number" for o in idf.idfobjects["SCHEDULETYPELIMITS"]
    ):
        idf.newidfobject("SCHEDULETYPELIMITS", Name="Any Number")


def _add_comfort_schedules(idf: IDF) -> None:
    existing = {o.Name for o in idf.idfobjects["SCHEDULE:COMPACT"]}
    for name, limits, value in _COMFORT_SCHEDULES:
        if name in existing:
            continue
        idf.newidfobject(
            "SCHEDULE:COMPACT",
            Name=name,
            Schedule_Type_Limits_Name=limits,
            Field_1="Through: 12/31",
            Field_2="For: AllDays",
            Field_3=f"Until: 24:00,{value}",
        )


def _enable_fanger(idf: IDF) -> list[str]:
    people_names = []
    for p in idf.idfobjects["PEOPLE"]:
        p.Work_Efficiency_Schedule_Name = "Work Eff Sch"
        p.Clothing_Insulation_Calculation_Method = "ClothingInsulationSchedule"
        p.Clothing_Insulation_Schedule_Name = "Clothing Sch"
        p.Air_Velocity_Schedule_Name = "Air Velo Sch"
        p.Thermal_Comfort_Model_1_Type = "Fanger"
        people_names.append(p.Name)
    if not people_names:
        raise RuntimeError("no People objects in IDF — cannot compute PMV")
    return people_names


def _request_meters(idf: IDF) -> None:
    """Force meter instantiation — the runtime API cannot resolve a facility meter
    handle unless an Output:Meter object exists in the IDF."""
    existing = {o.Key_Name for o in idf.idfobjects["OUTPUT:METER"]}
    if "Electricity:Facility" not in existing:
        idf.newidfobject(
            "OUTPUT:METER", Key_Name="Electricity:Facility", Reporting_Frequency="Timestep"
        )


def _set_run_period(idf: IDF, cfg: Config) -> None:
    rp = idf.idfobjects["RUNPERIOD"][0]
    rp.Begin_Month = cfg.run_period.begin_month
    rp.Begin_Day_of_Month = cfg.run_period.begin_day
    rp.End_Month = cfg.run_period.end_month
    rp.End_Day_of_Month = cfg.run_period.end_day
    sc = idf.idfobjects["SIMULATIONCONTROL"][0]
    sc.Run_Simulation_for_Sizing_Periods = "No"
    sc.Run_Simulation_for_Weather_File_Run_Periods = "Yes"
    idf.idfobjects["TIMESTEP"][0].Number_of_Timesteps_per_Hour = cfg.timesteps_per_hour


def prepare(cfg: Config) -> PrepResult:
    cfg.models_dir.mkdir(parents=True, exist_ok=True)

    src_idf = cfg.energyplus_dir / cfg.idf_example
    epw_matches = sorted(cfg.energyplus_dir.glob(cfg.weather_glob))
    if not epw_matches:
        raise FileNotFoundError(f"no weather file matching {cfg.weather_glob}")
    baseline_idf = cfg.models_dir / "baseline.idf"
    run_idf_path = cfg.models_dir / "run.idf"
    weather = cfg.models_dir / "weather.epw"
    shutil.copy(src_idf, baseline_idf)
    shutil.copy(epw_matches[0], weather)

    IDF.setiddname(str(cfg.energyplus_dir / "Energy+.idd"))
    idf = IDF(str(baseline_idf))

    heat_sched, cool_sched = _find_setpoint_schedules(idf)
    zones = _conditioned_zones(idf)
    _set_run_period(idf, cfg)
    _request_meters(idf)
    _add_any_number_limits(idf)
    _add_comfort_schedules(idf)
    people = _enable_fanger(idf)

    idf.saveas(str(run_idf_path))

    metadata = {
        "zones": zones,
        "people": people,
        "heat_sched": heat_sched,
        "cool_sched": cool_sched,
    }
    (cfg.models_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    return PrepResult(
        baseline_idf=baseline_idf,
        run_idf=run_idf_path,
        weather_epw=weather,
        metadata=metadata,
    )


if __name__ == "__main__":
    result = prepare(load_config())
    print(f"prepared {result.run_idf}")
    print(json.dumps(result.metadata, indent=2))
