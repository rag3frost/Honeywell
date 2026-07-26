from eco_loop.fallback import clamp, decide


def test_clamp_enforces_bounds(cfg):
    sp = clamp(10.0, 40.0, cfg)
    assert sp.heating_c == cfg.clamps.heat_min
    assert sp.cooling_c == cfg.clamps.cool_max


def test_clamp_enforces_deadband(cfg):
    sp = clamp(25.0, 24.0, cfg)  # inverted pair
    assert sp.cooling_c - sp.heating_c >= cfg.clamps.min_deadband
    assert cfg.clamps.heat_min <= sp.heating_c <= cfg.clamps.heat_max
    assert cfg.clamps.cool_min <= sp.cooling_c <= cfg.clamps.cool_max


def test_clamp_valid_passthrough(cfg):
    sp = clamp(21.0, 24.0, cfg)
    assert (sp.heating_c, sp.cooling_c) == (21.0, 24.0)


def test_decide_unoccupied_setback(cfg):
    sp = decide(occupied=False, outdoor_c=30.0, carbon_gkwh=300.0, cfg=cfg)
    assert sp.heating_c == 15.0
    assert sp.cooling_c == 30.0  # deeper setback than the stock 29.4 schedule


def test_decide_occupied_rides_warm_ceiling(cfg):
    """Occupied cooling at 26.5 C: hot-week sweep held PMV max +0.43 (well under the
    0.7 limit) while ~doubling saving vs the overcooled 25.5."""
    sp = decide(occupied=True, outdoor_c=30.0, carbon_gkwh=300.0, cfg=cfg)
    assert sp.heating_c == 21.1  # margin above the 21.0 band floor
    assert sp.cooling_c == 26.5


def test_decide_preoccupancy_recovery(cfg):
    """Hour before occupancy: pull down with margin so 8 am starts comfortable."""
    sp = decide(occupied=False, outdoor_c=30.0, carbon_gkwh=300.0, cfg=cfg, next_occupied=True)
    assert sp.heating_c == 21.1
    assert sp.cooling_c == 25.5


def test_decide_occupied_high_carbon_relaxes_cooling(cfg):
    """Dirty grid: push to the 27.0 comfort ceiling (PMV max +0.54) to cut more kWh."""
    sp = decide(occupied=True, outdoor_c=30.0, carbon_gkwh=450.0, cfg=cfg)
    assert sp.cooling_c == 27.0
