"""Tests for the agent's MCP toolbox (logic layer, no HTTP)."""
import json

import pytest

from eco_loop.agent.tools import ToolBox, build_server
from eco_loop.control_state import ControlState


@pytest.fixture
def state(cfg):
    return ControlState(cfg)


@pytest.fixture
def box(cfg, state, tmp_path):
    return ToolBox(state, cfg, decisions_path=tmp_path / "decisions.jsonl")


def test_sensor_summary_reflects_published_hour(box, state):
    state.publish_hour({"finished_hour": 13, "kwh_hour": 12.5})
    snap = box.get_sensor_summary()
    assert snap["awaiting_decision"] is True
    assert snap["summary"]["kwh_hour"] == 12.5


def test_set_setpoints_clamps_and_resolves_wait(box, state, cfg):
    state.publish_hour({"finished_hour": 1})
    result = box.set_setpoints(heating_c=5.0, cooling_c=45.0)
    assert result["heating_c"] == cfg.clamps.heat_min
    assert result["cooling_c"] == cfg.clamps.cool_max
    assert result["clamped"] is True
    assert state.await_decision(0.01) is True
    assert state.snapshot()["setpoints"]["source"] == "ai"


def test_set_setpoints_valid_passthrough(box):
    result = box.set_setpoints(heating_c=21.0, cooling_c=25.0)
    assert (result["heating_c"], result["cooling_c"]) == (21.0, 25.0)
    assert result["clamped"] is False


def test_get_targets_exposes_comfort_band(box, cfg):
    t = box.get_targets()
    assert t["comfort_band_c"] == [cfg.comfort.occ_low_c, cfg.comfort.occ_high_c]
    assert t["pmv_limit"] == cfg.comfort.pmv_limit
    assert t["setpoint_bounds"]["heating_c"] == [cfg.clamps.heat_min, cfg.clamps.heat_max]


def test_get_carbon_intensity(box):
    assert box.get_carbon_intensity(hour=12) > 0


def test_log_decision_appends_jsonl(box):
    box.log_decision(reasoning="setback: unoccupied", heating_c=15.0, cooling_c=30.0)
    box.log_decision(reasoning="comfort hours", heating_c=21.1, cooling_c=25.0)
    lines = box.decisions_path.read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["reasoning"] == "setback: unoccupied"
    assert rec["heating_c"] == 15.0


def test_log_decision_records_caller_hour_id_not_live_state(box, state):
    """The logged hour_id must be the hour the agent acted on, even if the sim
    has already advanced its counter before log_decision is called (the race)."""
    state.publish_hour({"hour": 8})          # hour_id -> 1: the hour agent decides
    state.publish_hour({"hour": 9})          # sim advances -> hour_id 2 before logging
    box.log_decision(reasoning="comfort hours", heating_c=21.1, cooling_c=25.0, hour_id=1)
    rec = json.loads(box.decisions_path.read_text().strip().splitlines()[-1])
    assert rec["hour_id"] == 1


def test_build_server_registers_all_tools(cfg, state):
    server = build_server(state, cfg)
    names = {t.name for t in server._tool_manager.list_tools()}
    assert {
        "get_sensor_summary",
        "set_setpoints",
        "get_targets",
        "get_carbon_intensity",
        "read_runtime_errors",
        "log_decision",
    } <= names
