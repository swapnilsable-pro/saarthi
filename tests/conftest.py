import pytest
from fastapi.testclient import TestClient

from backend.ledger.db import Ledger


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "ledger.db")
    yield led
    led.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAARTHI_DB", str(tmp_path / "api.db"))
    from backend.api.app import app
    with TestClient(app) as c:
        yield c
