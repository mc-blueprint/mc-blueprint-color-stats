import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def reset_http_host_state():
    from colorstats.collect.http import _HOST_STATES

    _HOST_STATES.clear()
    yield
