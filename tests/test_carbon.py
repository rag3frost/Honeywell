import pytest

from eco_loop.carbon import CarbonProfile

CSV = "tests/fixtures/carbon_small.csv"


@pytest.fixture(scope="module")
def profile(tmp_path_factory):
    p = tmp_path_factory.mktemp("carbon") / "carbon.csv"
    rows = ["hour,gco2_per_kwh"] + [f"{h},{200 + h * 10}" for h in range(24)]
    p.write_text("\n".join(rows))
    return CarbonProfile.from_csv(p)


def test_intensity_lookup(profile):
    assert profile.intensity(0) == 200.0
    assert profile.intensity(23) == 430.0


def test_intensity_out_of_range(profile):
    with pytest.raises(ValueError):
        profile.intensity(24)
    with pytest.raises(ValueError):
        profile.intensity(-1)


def test_real_carbon_csv_loads(cfg):
    prof = CarbonProfile.from_csv(cfg.carbon_csv)
    assert prof.intensity(18) > prof.intensity(3)  # evening peak > night
