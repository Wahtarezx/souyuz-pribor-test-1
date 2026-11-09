import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def product():
    return json.loads((EXAMPLES / "testo-510.input.json").read_text())


@pytest.fixture
def content():
    return json.loads((EXAMPLES / "testo-510.content.json").read_text())


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", _env_file=None)
    with TestClient(create_app(settings)) as client:
        yield client
