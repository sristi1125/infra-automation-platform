"""
FAKE SERVER SIMULATOR (v2 - hardened, multi-device)

This simulates a small fleet of devices (switches and PDUs) so the
orchestrator can be built and tested without real hardware.

Key upgrades from v1:
- Multiple devices, two types (switch, pdu) with different fields
- Input validation on every endpoint
- Firmware upgrades take simulated time and go through real states
  (idle -> updating -> verifying -> done/failed) instead of being instant
- Optional chaos/failure injection so the orchestrator has something
  realistic to handle (timeouts, random failures)
- debug mode is off by default; only turn it on explicitly for local dev
"""

import os
import random
import threading
import time
import uuid
from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory device fleet
# ---------------------------------------------------------------------------
# Each device has a "type" (switch | pdu) which determines which fields
# are meaningful. This is intentionally simple in-memory state - a real
# orchestrator talking to real hardware wouldn't store state here at all,
# but this stands in for "the device's own reported state."

devices = {
    "switch-1": {
        "id": "switch-1",
        "type": "switch",
        "name": "aruba-switch-sim-1",
        "power": "on",
        "firmware_version": "16.10.0012",
        "firmware_status": "idle",   # idle | updating | verifying | done | failed
        "port_count": 48,
        "health": "healthy",         # healthy | degraded | unreachable
    },
    "pdu-1": {
        "id": "pdu-1",
        "type": "pdu",
        "name": "pdu-sim-1",
        "power": "on",
        "firmware_version": "3.2.1",
        "firmware_status": "idle",
        "outlet_count": 24,
        "load_watts": 450,
        "health": "healthy",
    },
}

devices_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Chaos / failure injection
# ---------------------------------------------------------------------------
# Global fail rate can be set via env var or the /chaos endpoint. Any
# mutating request has this chance of returning a simulated failure
# (500) or, separately, hanging briefly to simulate a slow device.

chaos_state = {
    "fail_rate": float(os.environ.get("CHAOS_FAIL_RATE", 0.0)),  # 0.0 - 1.0
    "min_latency_ms": 0,
    "max_latency_ms": 0,
}


def maybe_inject_chaos():
    """Call at the top of mutating endpoints. May sleep (simulated latency)
    and/or raise to simulate a device failure."""
    lo = chaos_state["min_latency_ms"]
    hi = chaos_state["max_latency_ms"]
    if hi > 0:
        time.sleep(random.uniform(lo, hi) / 1000.0)

    if random.random() < chaos_state["fail_rate"]:
        return True  # caller should return a failure response
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_device_or_404(device_id):
    with devices_lock:
        device = devices.get(device_id)
        return dict(device) if device else None


def run_firmware_upgrade(device_id, target_version):
    """Background thread: simulates a real upgrade taking time and going
    through multiple states, instead of flipping instantly."""
    steps = [
        ("updating", random.uniform(1.5, 3.0)),
        ("verifying", random.uniform(1.0, 2.0)),
    ]
    for status, duration in steps:
        with devices_lock:
            if device_id not in devices:
                return
            devices[device_id]["firmware_status"] = status
        time.sleep(duration)

    with devices_lock:
        if device_id not in devices:
            return
        # Small chance the upgrade itself fails during verification -
        # gives the orchestrator something real to detect and retry.
        if random.random() < chaos_state["fail_rate"]:
            devices[device_id]["firmware_status"] = "failed"
            devices[device_id]["health"] = "degraded"
        else:
            devices[device_id]["firmware_version"] = target_version
            devices[device_id]["firmware_status"] = "done"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/devices", methods=["GET"])
def list_devices():
    with devices_lock:
        return jsonify(list(devices.values()))


@app.route("/devices/<device_id>/status", methods=["GET"])
def get_status(device_id):
    device = get_device_or_404(device_id)
    if device is None:
        return jsonify({"error": f"unknown device '{device_id}'"}), 404
    return jsonify(device)


@app.route("/devices/<device_id>/power", methods=["POST"])
def set_power(device_id):
    if get_device_or_404(device_id) is None:
        return jsonify({"error": f"unknown device '{device_id}'"}), 404

    payload = request.get_json(silent=True)
    if not payload or "power" not in payload:
        return jsonify({"error": "request body must include 'power'"}), 400

    new_power = payload.get("power")
    if new_power not in ("on", "off"):
        return jsonify({"error": "power must be 'on' or 'off'"}), 400

    if maybe_inject_chaos():
        return jsonify({"error": "device unreachable (simulated failure)"}), 503

    with devices_lock:
        devices[device_id]["power"] = new_power
    return jsonify(get_device_or_404(device_id))


@app.route("/devices/<device_id>/reset", methods=["POST"])
def reset_device(device_id):
    if get_device_or_404(device_id) is None:
        return jsonify({"error": f"unknown device '{device_id}'"}), 404

    if maybe_inject_chaos():
        return jsonify({"error": "device unreachable (simulated failure)"}), 503

    with devices_lock:
        devices[device_id]["power"] = "off"
    time.sleep(0.3)  # brief simulated downtime
    with devices_lock:
        devices[device_id]["power"] = "on"
        devices[device_id]["health"] = "healthy"

    return jsonify({"message": "device reset complete", "state": get_device_or_404(device_id)})


@app.route("/devices/<device_id>/firmware", methods=["POST"])
def upgrade_firmware(device_id):
    device = get_device_or_404(device_id)
    if device is None:
        return jsonify({"error": f"unknown device '{device_id}'"}), 404

    payload = request.get_json(silent=True)
    if not payload or "target_version" not in payload:
        return jsonify({"error": "request body must include 'target_version'"}), 400

    target_version = payload["target_version"]
    if not isinstance(target_version, str) or not target_version.strip():
        return jsonify({"error": "target_version must be a non-empty string"}), 400

    with devices_lock:
        if devices[device_id]["firmware_status"] in ("updating", "verifying"):
            return jsonify({"error": "an upgrade is already in progress"}), 409
        devices[device_id]["firmware_status"] = "updating"

    thread = threading.Thread(
        target=run_firmware_upgrade, args=(device_id, target_version), daemon=True
    )
    thread.start()

    return jsonify({
        "message": "firmware upgrade started",
        "device_id": device_id,
        "target_version": target_version,
    }), 202


@app.route("/chaos", methods=["POST"])
def configure_chaos():
    """Dev/test-only endpoint to tune failure injection at runtime.
    e.g. {"fail_rate": 0.3, "min_latency_ms": 100, "max_latency_ms": 500}
    """
    payload = request.get_json(silent=True) or {}

    if "fail_rate" in payload:
        rate = payload["fail_rate"]
        if not isinstance(rate, (int, float)) or not (0 <= rate <= 1):
            return jsonify({"error": "fail_rate must be a number between 0 and 1"}), 400
        chaos_state["fail_rate"] = float(rate)

    if "min_latency_ms" in payload:
        chaos_state["min_latency_ms"] = max(0, int(payload["min_latency_ms"]))

    if "max_latency_ms" in payload:
        chaos_state["max_latency_ms"] = max(0, int(payload["max_latency_ms"]))

    return jsonify(chaos_state)


@app.route("/healthz", methods=["GET"])
def healthz():
    """Simple liveness check - useful once this runs in Docker too."""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    debug_mode = os.environ.get("SIMULATOR_DEBUG", "false").lower() == "true"
    print("Fake server simulator (v2) running on http://localhost:5001")
    print(f"Devices: {list(devices.keys())}")
    print(f"Debug mode: {debug_mode}")
    app.run(host="0.0.0.0", port=5001, debug=debug_mode)
