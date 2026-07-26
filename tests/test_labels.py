from dashboard.labels import action_label, parse_reasoning


def test_parse_reasoning_fields():
    r = parse_reasoning("llm h23 occ=False next=True carbon=310.0 viol=2")
    assert r == {"source": "llm", "hour": 23, "occupied": False,
                 "next_occupied": True, "carbon": 310.0, "violations": 2}


def test_parse_reasoning_malformed_is_none():
    assert parse_reasoning("free-form text") is None


def test_action_labels():
    assert action_label(15.0, 30.0, occupied=False, next_occupied=False) == "Deep setback (building empty)"
    assert action_label(21.1, 25.5, occupied=False, next_occupied=True) == "Pre-conditioning for occupancy"
    assert action_label(21.1, 27.0, occupied=True, next_occupied=True) == "Warm ceiling (dirty grid)"
    assert action_label(21.1, 26.5, occupied=True, next_occupied=True) == "Comfort hold (warm ceiling)"
    assert action_label(21.6, 25.5, occupied=True, next_occupied=True) == "Comfort hold (tightened)"
    assert action_label(21.1, 26.0, occupied=True, next_occupied=True) == "Comfort hold"
