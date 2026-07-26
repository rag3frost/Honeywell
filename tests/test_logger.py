import csv
import json

from eco_loop.logger import CsvLogger, DecisionLogger


def test_csv_logger_roundtrip(tmp_path):
    p = tmp_path / "out.csv"
    log = CsvLogger(p, ["a", "b"])
    log.write_row({"a": 1, "b": 2.5})
    log.write_row({"a": 3, "b": 4.5})
    log.close()
    rows = list(csv.DictReader(p.open()))
    assert len(rows) == 2
    assert rows[1]["b"] == "4.5"


def test_decision_logger_jsonl(tmp_path):
    p = tmp_path / "decisions.jsonl"
    log = DecisionLogger(p)
    log.log(hour_id=1, summary={"h": 9}, setpoints=(21.0, 24.0),
            reasoning="occupied", mode="llm", latency_s=1.2)
    log.log(hour_id=2, summary={"h": 10}, setpoints=(15.0, 28.0),
            reasoning="timeout", mode="fallback", latency_s=25.0)
    lines = [json.loads(l) for l in p.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["mode"] == "llm"
    assert lines[1]["setpoints"] == [15.0, 28.0]
