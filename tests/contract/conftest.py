from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def pacts_dir() -> Path:
    return Path(__file__).parent / "consumer" / "pacts"
