import json
from pathlib import Path

import pytest

from alap.contracts import ContractCatalog

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def catalog():
    return ContractCatalog(ROOT / "contracts")


@pytest.fixture
def example():
    def load(name):
        return json.loads((ROOT / f"contracts/examples/{name}.json").read_text(encoding="utf-8"))

    return load


@pytest.fixture
def proposal(example):
    return example("plan_proposal")


@pytest.fixture
def skills(example):
    return example("simulator_skills")
