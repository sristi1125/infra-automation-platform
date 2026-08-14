"""
ORCHESTRATOR API (Phase 1 skeleton)

This is the "brain" - the API that will eventually manage real
infrastructure. Right now it's intentionally simple: it lists devices
and checks/changes their state by going through the DeviceClient
abstraction, which currently points at the simulator.

Nothing in this file talks to fake_server.py directly - it always goes
through device_client.py. That's the whole point: when real hardware is
ready, we swap in a new DeviceClient implementation and this file barely
changes.
"""

import os
from flask import Flask, jsonify, request
from device_client import SimulatorDeviceClient, DeviceClientError

app = Flask(__name__)

# In Phase 2 this becomes a proper device registry (Postgres). For now,
# one client pointed at the simulator is enough to prove the pattern.
device_client = SimulatorDeviceClient(
    base_url=os.environ.get("SIMULATOR_URL", "http://localhost:5001")
)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "orchestrator"})


@app.route("/devices", methods=["GET"])
def list_devices():
    try:
        devices = device_client.list_devices()
    except DeviceClientError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify(devices)


@app.route("/devices/<device_id>/status", methods=["GET"])
def get_device_status(device_id):
    try:
        status = device_client.get_status(device_id)
    except DeviceClientError as e:
        code = e.status_code if e.status_code in (404,) else 502
        return jsonify({"error": str(e)}), code
    return jsonify(status)


@app.route("/devices/<device_id>/power", methods=["POST"])
def set_device_power(device_id):
    payload = request.get_json(silent=True)
    if not payload or "power" not in payload:
        return jsonify({"error": "request body must include 'power'"}), 400

    power = payload["power"]
    if power not in ("on", "off"):
        return jsonify({"error": "power must be 'on' or 'off'"}), 400

    try:
        result = device_client.set_power(device_id, power)
    except DeviceClientError as e:
        code = e.status_code if e.status_code in (404,) else 502
        return jsonify({"error": str(e)}), code
    return jsonify(result)


@app.route("/devices/<device_id>/reset", methods=["POST"])
def reset_device(device_id):
    try:
        result = device_client.reset(device_id)
    except DeviceClientError as e:
        code = e.status_code if e.status_code in (404,) else 502
        return jsonify({"error": str(e)}), code
    return jsonify(result)


@app.route("/devices/<device_id>/firmware", methods=["POST"])
def upgrade_firmware(device_id):
    payload = request.get_json(silent=True)
    if not payload or "target_version" not in payload:
        return jsonify({"error": "request body must include 'target_version'"}), 400

    try:
        result = device_client.upgrade_firmware(device_id, payload["target_version"])
    except DeviceClientError as e:
        code = e.status_code if e.status_code in (404, 409) else 502
        return jsonify({"error": str(e)}), code
    return jsonify(result), 202


if __name__ == "__main__":
    print("Orchestrator API running on http://localhost:5000")
    print(f"Talking to simulator at: {device_client.base_url}")
    app.run(host="0.0.0.0", port=5000, debug=False)
