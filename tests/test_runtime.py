"""Integration test: one simulated day through the real EnergyPlus runtime."""
import csv
import re

import pytest

from eco_loop.control_state import ControlState
from eco_loop.sim import idf_prep
from eco_loop.sim.host import _with_days
from eco_loop.sim.runtime import run_simulation


@pytest.fixture(scope="module")
def baseline_rows(cfg, tmp_path_factory):
    if not cfg.energyplus_dir.exists():
        pytest.skip("EnergyPlus not installed")
    cfg1 = _with_days(cfg, 1)
    idf_prep.prepare(cfg1)
    out = tmp_path_factory.mktemp("run") / "baseline.csv"
    rc = run_simulation(cfg1, ControlState(cfg1), "baseline", out)
    assert rc == 0
    with out.open() as f:
        return list(csv.DictReader(f))


def test_one_day_produces_every_timestep(baseline_rows, cfg):
    assert len(baseline_rows) == 24 * cfg.timesteps_per_hour


def test_energy_total_is_physical(baseline_rows):
    """One July day of this 5-zone office is ~100-200 kWh (E+ tabular report:
    ~1022 kWh site energy over 7 days). Guards against meter-arithmetic bugs."""
    total = sum(float(r["kwh_step"]) for r in baseline_rows)
    assert 50 < total < 500, f"implausible daily total {total:.1f} kWh"


def test_csv_total_matches_eplus_report(baseline_rows, cfg):
    """CSV kWh must agree with E+'s own end-use electricity total for the run,
    otherwise we're missing a sub-meter (Building/HVAC/Plant)."""
    html = (cfg.root / "output_baseline" / "eplustbl.htm").read_text()
    row = next(r for r in re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL) if "Total End Uses" in r)
    elec_gj = float(re.findall(r"<td[^>]*>\s*([\d.]+)", row)[0])
    expected_kwh = elec_gj * 1e9 / 3.6e6
    csv_kwh = sum(float(r["kwh_step"]) for r in baseline_rows)
    assert abs(csv_kwh - expected_kwh) / expected_kwh < 0.05, (
        f"csv={csv_kwh:.1f} kWh vs E+ report={expected_kwh:.1f} kWh"
    )


def test_sensors_are_sane(baseline_rows):
    for r in baseline_rows:
        assert 10 <= float(r["temp_mean"]) <= 40
        assert -4 <= float(r["pmv_mean"]) <= 4
