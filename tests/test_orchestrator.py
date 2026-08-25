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

    import jobs
    jobs.init_db()

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
    job = resp.get_json()
    assert job["params"]["target_version"] == "99.0.0"
    assert job["device_id"] == "switch-1"
    assert job["action"] == "firmware_upgrade"


def test_firmware_upgrade_missing_field_rejected(orchestrator_client):
    resp = orchestrator_client.post("/devices/switch-1/firmware", json={})
    assert resp.status_code == 400


def test_batch_power_all_succeed(orchestrator_client):
    resp = orchestrator_client.post(
        "/devices/batch/power",
        json={"device_ids": ["switch-1", "pdu-1"], "power": "off"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0

    orchestrator_client.post(
        "/devices/batch/power",
        json={"device_ids": ["switch-1", "pdu-1"], "power": "on"},
    )


def test_batch_power_partial_failure(orchestrator_client):
    resp = orchestrator_client.post(
        "/devices/batch/power",
        json={"device_ids": ["switch-1", "fake-device-99"], "power": "off"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 2
    assert data["succeeded"] == 1
    assert data["failed"] == 1

    results_by_device = {r["device_id"]: r for r in data["results"]}
    assert results_by_device["switch-1"]["success"] is True
    assert results_by_device["fake-device-99"]["success"] is False

    orchestrator_client.post(
        "/devices/batch/power", json={"device_ids": ["switch-1"], "power": "on"}
    )


def test_batch_power_missing_fields_rejected(orchestrator_client):
    resp = orchestrator_client.post("/devices/batch/power", json={"power": "on"})
    assert resp.status_code == 400

    resp2 = orchestrator_client.post(
        "/devices/batch/power", json={"device_ids": ["switch-1"]}
    )
    assert resp2.status_code == 400


def test_batch_power_empty_list_rejected(orchestrator_client):
    resp = orchestrator_client.post(
        "/devices/batch/power", json={"device_ids": [], "power": "on"}
    )
    assert resp.status_code == 400


def test_devices_summary_includes_all_devices(orchestrator_client):
    resp = orchestrator_client.get("/devices/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    ids = {entry["device"]["id"] for entry in data}
    assert "switch-1" in ids
    assert "pdu-1" in ids


def test_devices_summary_includes_latest_job(orchestrator_client):
    resp1 = orchestrator_client.post(
        "/devices/pdu-1/firmware", json={"target_version": "50.0.0"}
    )
    assert resp1.status_code == 202

    resp = orchestrator_client.get("/devices/summary")
    data = resp.get_json()
    pdu_entry = next(e for e in data if e["device"]["id"] == "pdu-1")
    assert pdu_entry["latest_job"] is not None
    assert pdu_entry["latest_job"]["params"]["target_version"] == "50.0.0"


def test_devices_summary_latest_job_field_is_present(orchestrator_client):
    """latest_job should always be a key in the response - either a real
    job dict, or None if the device has no history. We don't assume
    which, since the shared database may carry real history between
    test runs and manual testing sessions."""
    resp = orchestrator_client.get("/devices/summary")
    data = resp.get_json()
    for entry in data:
        assert "latest_job" in entry
        assert entry["latest_job"] is None or isinstance(entry["latest_job"], dict)