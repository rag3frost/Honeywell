"""Tests for the orchestrator's decision-validation logic (no LLM needed)."""

from eco_loop.agent.orchestrator import build_user_prompt, extract_setpoints


def test_extract_from_tool_call():
    calls = [{"function": {"name": "set_setpoints",
                           "arguments": {"heating_c": 21.1, "cooling_c": 25.0}}}]
    assert extract_setpoints(calls) == (21.1, 25.0)


def test_extract_string_arguments():
    calls = [{"function": {"name": "set_setpoints",
                           "arguments": '{"heating_c": 20, "cooling_c": 26}'}}]
    assert extract_setpoints(calls) == (20.0, 26.0)


def test_extract_ignores_other_tools_and_bad_args():
    calls = [
        {"function": {"name": "log_decision", "arguments": {}}},
        {"function": {"name": "set_setpoints", "arguments": {"heating_c": "x"}}},
    ]
    assert extract_setpoints(calls) is None


def test_extract_none_on_empty():
    assert extract_setpoints([]) is None
    assert extract_setpoints(None) is None


def test_user_prompt_contains_key_signals():
    summary = {"hour": 7, "occupied": False, "next_hour_occupied": True,
               "outdoor_c": 24.5, "kwh_hour": 8.2, "pmv_mean": -0.4,
               "violations_last_hour": 2, "carbon_gkwh": 450,
               "setpoints": {"heating_c": 15.0, "cooling_c": 30.0},
               "temp_mean": 23.1, "err_tail": []}
    p = build_user_prompt(summary)
    for token in ("next hour: OCCUPIED", "450", "8.2", "violations: 2"):
        assert token in p
