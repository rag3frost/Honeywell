
import pytest

from eco_loop.sim.idf_prep import prepare


@pytest.fixture(scope="module")
def prep(cfg):
    if not cfg.energyplus_dir.exists():
        pytest.skip("EnergyPlus not installed")
    return prepare(cfg)


def test_outputs_exist(prep, cfg):
    assert prep.baseline_idf.exists()
    assert prep.run_idf.exists()
    assert prep.weather_epw.exists()
    assert (cfg.models_dir / "metadata.json").exists()


def test_metadata_contents(prep):
    meta = prep.metadata
    assert len(meta["zones"]) >= 5
    assert "PLENUM-1" not in meta["zones"]
    assert len(meta["people"]) >= 5
    assert meta["heat_sched"] and meta["cool_sched"]


def test_run_idf_edits(prep, cfg):
    from eppy.modeleditor import IDF

    IDF.setiddname(str(cfg.energyplus_dir / "Energy+.idd"))
    idf = IDF(str(prep.run_idf))

    rp = idf.idfobjects["RUNPERIOD"][0]
    assert (rp.Begin_Month, rp.Begin_Day_of_Month) == (7, 15)
    assert (rp.End_Month, rp.End_Day_of_Month) == (7, 21)

    sc = idf.idfobjects["SIMULATIONCONTROL"][0]
    assert sc.Run_Simulation_for_Sizing_Periods == "No"

    for p in idf.idfobjects["PEOPLE"]:
        assert p.Thermal_Comfort_Model_1_Type == "Fanger"
        assert p.Clothing_Insulation_Schedule_Name == "Clothing Sch"

    sched_names = {o.Name for o in idf.idfobjects["SCHEDULE:COMPACT"]}
    assert {"Work Eff Sch", "Clothing Sch", "Air Velo Sch"} <= sched_names
