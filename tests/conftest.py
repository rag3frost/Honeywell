from pathlib import Path

import pytest

from eco_loop.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def cfg():
    return load_config(PROJECT_ROOT / "config.yaml")
