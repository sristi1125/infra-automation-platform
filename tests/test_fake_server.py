"""
Tests for the fake_server simulator.

Run with: pytest tests/test_fake_server.py -v

These use Flask's test client directly (no need to have the server
running separately) so they're fast and deterministic. We reset
chaos settings and device state before each test so tests don't
interfere with each other.
"""

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulator"))

import fake_server  # noqa: E402


@pytest.fixture
def client():
    fake_server.app.config["TESTING"] = True
    # Reset chaos + device state before every test
    fake_server.chaos_state["fail_rate"] = 0.0
    fake_server.chaos_state["min_latency_ms"] = 0
    fake_server.chaos_state["max_latency_ms"] = 0
    with fake_server.devices_lock:
        fake_server.devices["switch-1"]["power"] = "on"
        fake_server.devices["switch-1"]["firmware_status"] = "idle"
        fake_server.devices["switch-1"]["firmware_version"] = "16.10.0012"
        fake_server.devices["pdu-1"]["power"] = "on"
        fake_server.devices["pdu-1"]["firmware_status"] = "idle"
    with fake_server.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# /devices and /status
# ---------------------------------------------------------------------------

def test_list_devices_returns_both_types(client):
    resp = client.get("/devices")
    assert resp.status_code == 200
    types = {d["type"] for d in resp.get_json()}
    assert types == {"switch", "pdu"}


def test_get_status_known_device(client):
    resp = client.get("/devices/switch-1/status")
    assert resp.status_code == 200
    assert resp.get_json()["id"] == "switch-1"


def test_get_status_unknown_device_returns_404(client):
    resp = client.get("/devices/does-not-exist/status")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /power
# ---------------------------------------------------------------------------

def test_set_power_valid(client):
    resp = client.post("/devices/switch-1/power", json={"power": "off"})
    assert resp.status_code == 200
    assert resp.get_json()["power"] == "off"


def test_set_power_invalid_value_rejected(client):
    resp = client.post("/devices/switch-1/power", json={"power": "sideways"})
    assert resp.status_code == 400


def test_set_power_missing_body_rejected(client):
    resp = client.post("/devices/switch-1/power", json={})
    assert resp.status_code == 400


def test_set_power_unknown_device_404(client):
    resp = client.post("/devices/nope/power", json={"power": "on"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /reset
# ---------------------------------------------------------------------------

def test_reset_turns_device_back_on(client):
    client.post("/devices/pdu-1/power", json={"power": "off"})
    resp = client.post("/devices/pdu-1/reset")
    assert resp.status_code == 200
    assert resp.get_json()["state"]["power"] == "on"


# ---------------------------------------------------------------------------
# /firmware (async upgrade)
# ---------------------------------------------------------------------------

def test_firmware_upgrade_requires_target_version(client):
    resp = client.post("/devices/switch-1/firmware", json={})
    assert resp.status_code == 400


def test_firmware_upgrade_starts_and_completes(client):
    resp = client.post(
        "/devices/switch-1/firmware", json={"target_version": "16.11.0001"}
    )
    assert resp.status_code == 202

    # Poll until it's out of "updating"/"verifying" or we time out
    deadline = time.time() + 10
    status = None
    while time.time() < deadline:
        status = client.get("/devices/switch-1/status").get_json()["firmware_status"]
        if status in ("done", "failed"):
            break
        time.sleep(0.2)

    assert status in ("done", "failed")


def test_firmware_upgrade_rejects_concurrent_upgrade(client):
    client.post("/devices/switch-1/firmware", json={"target_version": "16.11.0001"})
    resp = client.post("/devices/switch-1/firmware", json={"target_version": "16.12.0000"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Chaos injection
# ---------------------------------------------------------------------------

def test_chaos_fail_rate_of_one_forces_failures(client):
    client.post("/chaos", json={"fail_rate": 1.0})
    resp = client.post("/devices/switch-1/power", json={"power": "off"})
    assert resp.status_code == 503


def test_chaos_invalid_fail_rate_rejected(client):
    resp = client.post("/chaos", json={"fail_rate": 5})
    assert resp.status_code == 400


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
