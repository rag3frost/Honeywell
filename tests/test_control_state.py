import threading
import time

import pytest

from eco_loop.control_state import ControlState


@pytest.fixture
def state(cfg):
    return ControlState(cfg)


def test_initial_setpoints_are_baseline(state, cfg):
    sp = state.get_setpoints()
    assert sp.heating_c == cfg.baseline_setpoints.heating_c
    assert sp.cooling_c == cfg.baseline_setpoints.cooling_c


def test_set_setpoints_clamps(state, cfg):
    sp = state.set_setpoints(40.0, 10.0, source="test")
    assert cfg.clamps.heat_min <= sp.heating_c <= cfg.clamps.heat_max
    assert sp.cooling_c - sp.heating_c >= cfg.clamps.min_deadband


def test_publish_and_snapshot(state):
    state.publish_hour({"hour": 9, "kwh_hour": 12.5})
    snap = state.snapshot()
    assert snap["hour_id"] == 1
    assert snap["awaiting_decision"] is True
    assert snap["summary"]["kwh_hour"] == 12.5
    assert snap["sim_done"] is False


def test_await_decision_timeout(state):
    state.publish_hour({"hour": 1})
    assert state.await_decision(timeout_s=0.05) is False


def test_await_decision_resolves(state):
    state.publish_hour({"hour": 1})

    def decider():
        time.sleep(0.05)
        state.set_setpoints(20.0, 26.0, source="llm")

    t = threading.Thread(target=decider)
    t.start()
    assert state.await_decision(timeout_s=2.0) is True
    t.join()
    assert state.snapshot()["awaiting_decision"] is False


def test_mark_done(state):
    state.mark_done()
    assert state.snapshot()["sim_done"] is True
