from eco_loop.comfort import evaluate, is_occupied


def test_occupied_weekday_working_hours(cfg):
    assert is_occupied(weekday=0, hour=9, cfg=cfg)  # Monday 9am
    assert is_occupied(weekday=4, hour=17, cfg=cfg)  # Friday 5pm


def test_unoccupied_night_and_weekend(cfg):
    assert not is_occupied(weekday=0, hour=7, cfg=cfg)  # before 8
    assert not is_occupied(weekday=0, hour=18, cfg=cfg)  # 18 is end (exclusive)
    assert not is_occupied(weekday=5, hour=12, cfg=cfg)  # Saturday
    assert not is_occupied(weekday=6, hour=12, cfg=cfg)  # Sunday


def test_evaluate_all_comfortable(cfg):
    r = evaluate([22.0, 23.0, 24.0], pmv=0.3, weekday=1, hour=10, cfg=cfg)
    assert r.occupied
    assert r.violations == 0
    assert r.pmv_ok


def test_evaluate_violations_counted(cfg):
    r = evaluate([20.0, 27.5, 23.0], pmv=0.9, weekday=1, hour=10, cfg=cfg)
    assert r.violations == 2  # 20.0 below 21.0 floor, 27.5 above 27.0 ceiling
    assert not r.pmv_ok


def test_evaluate_unoccupied_never_violates(cfg):
    r = evaluate([15.0, 30.0], pmv=2.0, weekday=6, hour=3, cfg=cfg)
    assert not r.occupied
    assert r.violations == 0
    assert r.pmv_ok


def test_evaluate_none_pmv_is_ok(cfg):
    r = evaluate([22.0], pmv=None, weekday=1, hour=10, cfg=cfg)
    assert r.pmv_ok
