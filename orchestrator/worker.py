"""
WORKER PROCESS

This is a separate program from the orchestrator API. It watches the
Redis queue and, whenever a job is enqueued, picks it up and actually
runs it.

Running this as its own process (separate from app.py) is the whole
point: you can run MULTIPLE workers at once, all pulling from the same
shared queue, to process jobs in parallel - something a single
background thread inside the API process could never do safely.

Uses SimpleWorker instead of RQ's default Worker class because the
default relies on os.fork(), which doesn't exist on Windows. SimpleWorker
runs jobs directly in this process instead of forking a subprocess per
job - the right choice here since we're not running many workers in
parallel yet.

Run with: python worker.py
"""

import os
from redis import Redis
from rq import SimpleWorker, Queue

import jobs

redis_conn = Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    db=int(os.environ.get("REDIS_DB", 0)),
)

if __name__ == "__main__":
    # If a previous worker crashed mid-job, its jobs are still marked
    # 'running'. Clear out any that are past the stale threshold so
    # their devices accept new work again.
    reaped = jobs.fail_stale_jobs()
    if reaped:
        print(f"Marked {len(reaped)} abandoned job(s) as failed: {', '.join(reaped)}")

    queue = Queue("firmware_upgrades", connection=redis_conn)
    worker = SimpleWorker([queue], connection=redis_conn)
    print("Worker started, listening on queue: firmware_upgrades")
    worker.work()