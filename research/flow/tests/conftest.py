import json
import sys
from pathlib import Path

import pytest

FLOW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FLOW))
FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def ch_events():
    return json.loads((FIX / "ch_events.json").read_text())


@pytest.fixture(scope="session")
def launch_fixture():
    return json.loads((FIX / "launch_JBfdBN1q.json").read_text())


@pytest.fixture(scope="session")
def launch_amm_fixture():
    return json.loads((FIX / "launch_HqJ4C36p.json").read_text())
