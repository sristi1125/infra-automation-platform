"""
BACKGROUND TASKS

This is the actual work a worker process runs, picked up from the Redis
queue. Moving this out of app.py means the orchestrator API never does
the slow part itself - it just hands this function's name and arguments
to RQ, and a separate worker process calls it whenever it's free.
"""

import time
from device_client import SimulatorDeviceClient, DeviceClientError
import jobs
import os

device_client = SimulatorDeviceClient(
    base_url=os.environ.get("SIMULATOR_URL", "http://localhost:5001")
)


def run_firmware_upgrade_job(job_id, device_id, target_version):
    """Watches a firmware upgrade already in progress on the device,
    polling until it finishes, then updates the job record accordingly.
    This is the function RQ workers actually call."""
    jobs.update_job(job_id, status="running")
    deadline = time.time() + 30

    while time.time() < deadline:
        try:
            status = device_client.get_status(device_id)
        except DeviceClientError as e:
            jobs.update_job(job_id, status="failed", error=str(e))
            return

        fw_status = status.get("firmware_status")
        if fw_status == "done":
            jobs.update_job(job_id, status="succeeded", result=status)
            return
        if fw_status == "failed":
            jobs.update_job(job_id, status="failed", error="device reported failure", result=status)
            return
        time.sleep(0.5)

    jobs.update_job(job_id, status="failed", error="timed out waiting for device")