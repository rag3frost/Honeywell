from pathlib import Path

from eco_loop.config import load_config


def test_load_config_types(cfg):
    assert isinstance(cfg.energyplus_dir, Path)
    assert cfg.run_period.begin_month == 7
    assert cfg.timesteps_per_hour == 4
    assert cfg.comfort.occ_low_c == 21.0
    assert cfg.clamps.min_deadband == 2.0
    assert cfg.agent.model == "qwen2.5:7b"
    assert cfg.mcp.port == 8765


def test_energyplus_dir_expanded(cfg):
    assert "~" not in str(cfg.energyplus_dir)


def test_baseline_setpoints_valid(cfg):
    sp = cfg.baseline_setpoints
    assert sp.cooling_c - sp.heating_c >= cfg.clamps.min_deadband


def test_env_overrides(monkeypatch, tmp_path):
    import shutil
    shutil.copy("config.yaml", tmp_path / "config.yaml")
    monkeypatch.setenv("ECO_LOOP_ENERGYPLUS_DIR", "/EnergyPlus-26-1-0")
    monkeypatch.setenv("ECO_LOOP_OLLAMA_HOST", "http://ollama:11434")
    monkeypatch.setenv("ECO_LOOP_MCP_HOST", "0.0.0.0")
    c = load_config(tmp_path / "config.yaml")
    assert str(c.energyplus_dir) == "/EnergyPlus-26-1-0"
    assert c.agent.ollama_host == "http://ollama:11434"
    assert c.mcp.host == "0.0.0.0"
