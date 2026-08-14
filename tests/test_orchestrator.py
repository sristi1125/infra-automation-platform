"""
Integration tests for the orchestrator.

These spin up the REAL simulator (fake_server.py) on a background thread
on a test port, then exercise the orchestrator's Flask test client
against it. This proves the orchestrator correctly talks to a real
running device over HTTP - not just against mocks.

Run with: pytest tests/test_orchestrator.py -v
"""

import sys
import os
import threading
import time
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

import fake_server  # noqa: E402

SIMULATOR_TEST_PORT = 5099
SIMULATOR_TEST_URL = f"http://localhost:{SIMULATOR_TEST_PORT}"


@pytest.fixture(scope="module", autouse=True)
def run_simulator():
    """Start the real simulator Flask app on a background thread for the
    duration of these tests."""
    thread = threading.Thread(
        target=lambda: fake_server.app.run(
            host="127.0.0.1", port=SIMULATOR_TEST_PORT, debug=False, use_reloader=False
        ),
        daemon=True,
    )
    thread.start()

    # Wait for it to actually be up before running any tests
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            requests.get(f"{SIMULATOR_TEST_URL}/healthz", timeout=0.5)
            break
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
    else:
        pytest.fail("simulator did not start in time")

    yield


@pytest.fixture
def orchestrator_client(run_simulator):
    """Flask test client for the orchestrator, pointed at the test simulator."""
    os.environ["SIMULATOR_URL"] = SIMULATOR_TEST_URL

    # Import here (after env var is set) so device_client picks up the URL
    import app as orchestrator_app
    orchestrator_app.device_client.base_url = SIMULATOR_TEST_URL

    orchestrator_app.app.config["TESTING"] = True
    with orchestrator_app.app.test_client() as client:
        yield client


def test_health(orchestrator_client):
    resp = orchestrator_client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_list_devices_proxies_simulator(orchestrator_client):
    resp = orchestrator_client.get("/devices")
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.get_json()}
    assert "switch-1" in ids
    assert "pdu-1" in ids


def test_get_device_status(orchestrator_client):
    resp = orchestrator_client.get("/devices/switch-1/status")
    assert resp.status_code == 200
    assert resp.get_json()["id"] == "switch-1"


def test_get_unknown_device_status_returns_404(orchestrator_client):
    resp = orchestrator_client.get("/devices/nonexistent/status")
    assert resp.status_code == 404


def test_set_power_through_orchestrator(orchestrator_client):
    resp = orchestrator_client.post("/devices/pdu-1/power", json={"power": "off"})
    assert resp.status_code == 200
    assert resp.get_json()["power"] == "off"

    # put it back
    orchestrator_client.post("/devices/pdu-1/power", json={"power": "on"})


def test_set_power_invalid_value_rejected(orchestrator_client):
    resp = orchestrator_client.post("/devices/pdu-1/power", json={"power": "invalid"})
    assert resp.status_code == 400


def test_reset_through_orchestrator(orchestrator_client):
    resp = orchestrator_client.post("/devices/switch-1/reset")
    assert resp.status_code == 200
    assert resp.get_json()["state"]["power"] == "on"


def test_firmware_upgrade_through_orchestrator(orchestrator_client):
    resp = orchestrator_client.post(
        "/devices/switch-1/firmware", json={"target_version": "99.0.0"}
    )
    assert resp.status_code == 202
    assert resp.get_json()["target_version"] == "99.0.0"


def test_firmware_upgrade_missing_field_rejected(orchestrator_client):
    resp = orchestrator_client.post("/devices/switch-1/firmware", json={})
    assert resp.status_code == 400
