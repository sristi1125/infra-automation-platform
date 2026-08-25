"""
ORCHESTRATOR API

This is the "brain" - the API that manages infrastructure. It lists
devices and checks/changes their state by going through the DeviceClient
abstraction, which currently points at the simulator.

Nothing in this file talks to fake_server.py directly - it always goes
through device_client.py. That's the whole point: when real hardware is
ready, we swap in a new DeviceClient implementation and this file barely
changes.

Firmware upgrades are handled via a Redis-backed job queue (RQ) instead
of a background thread - the orchestrator only ever enqueues work here.
A separate worker process (worker.py) is what actually picks jobs up and
runs them, which is what lets us scale workers independently of the API.

Every request requires a valid API key (viewer or operator role - see
auth.py). Actions that change state are also recorded in the audit log
(see audit.py) - who did what, on which device, and the result.
"""

import os
from flask import Flask, jsonify, request
from device_client import SimulatorDeviceClient, DeviceClientError
from redis import Redis
from rq import Queue
import jobs
import audit
from auth import require_role
from tasks import run_firmware_upgrade_job

app = Flask(__name__)
jobs.init_db()
audit.init_db()

# In Phase 2 this becomes a proper device registry (Postgres). For now,
# one client pointed at the simulator is enough to prove the pattern.
device_client = SimulatorDeviceClient(
    base_url=os.environ.get("SIMULATOR_URL", "http://localhost:5001")
)

redis_conn = Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
)
task_queue = Queue("firmware_upgrades", connection=redis_conn)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "orchestrator"})


@app.route("/devices", methods=["GET"])
@require_role("viewer")
def list_devices():
    try:
        devices = device_client.list_devices()
    except DeviceClientError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify(devices)


@app.route("/devices/<device_id>/status", methods=["GET"])
@require_role("viewer")
def get_device_status(device_id):
    try:
        status = device_client.get_status(device_id)
    except DeviceClientError as e:
        code = e.status_code if e.status_code in (404,) else 502
        return jsonify({"error": str(e)}), code
    return jsonify(status)


@app.route("/devices/<device_id>/power", methods=["POST"])
@require_role("operator")
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
        audit.log_action(request.actor, "set_power", device_id, {"power": power}, result="failed")
        code = e.status_code if e.status_code in (404,) else 502
        return jsonify({"error": str(e)}), code

    audit.log_action(request.actor, "set_power", device_id, {"power": power}, result="success")
    return jsonify(result)


@app.route("/devices/batch/power", methods=["POST"])
@require_role("operator")
def batch_set_power():
    """Set power on multiple devices at once. Each device is tried
    independently - one device failing doesn't stop the others, and
    we report a clear per-device result instead of one big pass/fail."""
    payload = request.get_json(silent=True)
    if not payload or "device_ids" not in payload or "power" not in payload:
        return jsonify({"error": "request body must include 'device_ids' (list) and 'power'"}), 400

    device_ids = payload["device_ids"]
    power = payload["power"]

    if not isinstance(device_ids, list) or not device_ids:
        return jsonify({"error": "device_ids must be a non-empty list"}), 400
    if power not in ("on", "off"):
        return jsonify({"error": "power must be 'on' or 'off'"}), 400

    results = []
    for device_id in device_ids:
        try:
            result = device_client.set_power(device_id, power)
            results.append({"device_id": device_id, "success": True, "result": result})
            audit.log_action(request.actor, "set_power", device_id, {"power": power}, result="success")
        except DeviceClientError as e:
            results.append({"device_id": device_id, "success": False, "error": str(e)})
            audit.log_action(request.actor, "set_power", device_id, {"power": power}, result="failed")

    succeeded = sum(1 for r in results if r["success"])
    return jsonify({
        "total": len(device_ids),
        "succeeded": succeeded,
        "failed": len(device_ids) - succeeded,
        "results": results,
    })


@app.route("/devices/<device_id>/reset", methods=["POST"])
@require_role("operator")
def reset_device(device_id):
    try:
        result = device_client.reset(device_id)
    except DeviceClientError as e:
        audit.log_action(request.actor, "reset", device_id, result="failed")
        code = e.status_code if e.status_code in (404,) else 502
        return jsonify({"error": str(e)}), code

    audit.log_action(request.actor, "reset", device_id, result="success")
    return jsonify(result)


@app.route("/devices/<device_id>/firmware", methods=["POST"])
@require_role("operator")
def upgrade_firmware(device_id):
    payload = request.get_json(silent=True)
    if not payload or "target_version" not in payload:
        return jsonify({"error": "request body must include 'target_version'"}), 400

    target_version = payload["target_version"]

    if jobs.has_active_job_for_device(device_id):
        return jsonify({"error": "a job is already in progress for this device"}), 409

    try:
        device_client.upgrade_firmware(device_id, target_version)
    except DeviceClientError as e:
        audit.log_action(request.actor, "firmware_upgrade", device_id, {"target_version": target_version}, result="failed")
        code = e.status_code if e.status_code in (404, 409) else 502
        return jsonify({"error": str(e)}), code

    job = jobs.create_job(device_id, "firmware_upgrade", {"target_version": target_version})
    audit.log_action(request.actor, "firmware_upgrade", device_id, {"target_version": target_version, "job_id": job["id"]}, result="started")

    # Instead of starting our own thread, hand this off to the Redis
    # queue - a separate worker process will pick it up and run it.
    task_queue.enqueue(run_firmware_upgrade_job, job["id"], device_id, target_version)

    return jsonify(job), 202


@app.route("/jobs/<job_id>", methods=["GET"])
@require_role("viewer")
def get_job_status(job_id):
    job = jobs.get_job(job_id)
    if job is None:
        return jsonify({"error": f"unknown job '{job_id}'"}), 404
    return jsonify(job)


@app.route("/devices/summary", methods=["GET"])
@require_role("viewer")
def devices_summary():
    """One-call fleet overview: every device's current status plus its
    most recent job, if any. This is the kind of endpoint a dashboard
    would call to render an at-a-glance view of the whole fleet."""
    try:
        devices = device_client.list_devices()
    except DeviceClientError as e:
        return jsonify({"error": str(e)}), 502

    summary = []
    for device in devices:
        device_jobs = jobs.list_jobs(device_id=device["id"])
        latest_job = device_jobs[0] if device_jobs else None
        summary.append({
            "device": device,
            "latest_job": latest_job,
        })

    return jsonify(summary)


@app.route("/audit-log", methods=["GET"])
@require_role("viewer")
def get_audit_log():
    device_id = request.args.get("device_id")
    return jsonify(audit.list_entries(device_id=device_id))


if __name__ == "__main__":
    print("Orchestrator API running on http://localhost:5000")
    print(f"Talking to simulator at: {device_client.base_url}")
    app.run(host="0.0.0.0", port=5000, debug=False)