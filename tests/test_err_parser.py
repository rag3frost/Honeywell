from pathlib import Path

from eco_loop.err_parser import tail_errors

SAMPLE = """Program Version,EnergyPlus, Version 26.1.0
   ** Warning ** Weather file location will be used
   **   ~~~   ** ..Location object=CHICAGO
   ** Warning ** SetPointManager: missing something
   ** Severe  ** Node connection error
   ************* EnergyPlus Completed Successfully
"""


def test_tail_errors_filters(tmp_path):
    p = tmp_path / "eplusout.err"
    p.write_text(SAMPLE)
    lines = tail_errors(p)
    assert len(lines) == 3
    assert any("Severe" in l for l in lines)
    assert not any("~~~" in l for l in lines)
    assert not any("Completed" in l for l in lines)


def test_tail_errors_max_lines(tmp_path):
    p = tmp_path / "eplusout.err"
    p.write_text("\n".join(f"   ** Warning ** w{i}" for i in range(30)))
    lines = tail_errors(p, max_lines=5)
    assert len(lines) == 5
    assert "w29" in lines[-1]


def test_tail_errors_dedupes(tmp_path):
    p = tmp_path / "eplusout.err"
    p.write_text("   ** Warning ** same\n" * 10)
    assert len(tail_errors(p)) == 1


def test_tail_errors_missing_file():
    assert tail_errors(Path("/nonexistent/eplusout.err")) == []
