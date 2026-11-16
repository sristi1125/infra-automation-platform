"""
JOB MODEL (Postgres version)

Tracks orchestrator actions (like firmware upgrades) as jobs with an ID,
so we can check "is this done yet?" instead of just firing a request and
hoping for the best.

This now talks to Postgres (running in Docker) instead of SQLite - the
same logic as before, just backed by a real database that can safely
handle multiple processes reading/writing at once, which we'll need
once we introduce a real job queue with multiple workers.
"""

import os
import uuid
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": os.environ.get("POSTGRES_PORT", "5432"),
    "dbname": os.environ.get("POSTGRES_DB", "infra_automation"),
    "user": os.environ.get("POSTGRES_USER", "infra"),
    "password": os.environ.get("POSTGRES_PASSWORD", "infra_dev_password"),
}

# How long a job may sit in an active state before we assume whoever
# owned it is gone. A worker gives up on a device after 30s (tasks.py),
# so a job still 'running' after 120s means the worker died mid-job.
# A job still 'pending' after 600s was never picked up (no worker
# running, or the enqueue to Redis failed after the row was written).
STALE_RUNNING_SECONDS = int(os.environ.get("STALE_RUNNING_SECONDS", 120))
STALE_PENDING_SECONDS = int(os.environ.get("STALE_PENDING_SECONDS", 600))


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    params JSONB,
                    result JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
            """)
        conn.commit()


@contextmanager
def get_conn():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        yield conn
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc)


def create_job(device_id, action, params=None):
    job_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO jobs (id, device_id, action, status, params, result, error, created_at, updated_at)
                   VALUES (%s, %s, %s, 'pending', %s, NULL, NULL, %s, %s)""",
                (job_id, device_id, action, json.dumps(params or {}), now, now),
            )
        conn.commit()
    return get_job(job_id)


def update_job(job_id, status, result=None, error=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE jobs SET status = %s, result = %s, error = %s, updated_at = %s
                   WHERE id = %s""",
                (status, json.dumps(result) if result is not None else None, error, _now(), job_id),
            )
        conn.commit()
    return get_job(job_id)


def get_job(job_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return _row_to_dict(row)


def list_jobs(device_id=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if device_id:
                cur.execute(
                    "SELECT * FROM jobs WHERE device_id = %s ORDER BY created_at DESC", (device_id,)
                )
            else:
                cur.execute("SELECT * FROM jobs ORDER BY created_at DESC")
            rows = cur.fetchall()
            return [_row_to_dict(r) for r in rows]


def fail_stale_jobs(device_id=None):
    """Mark abandoned 'pending'/'running' jobs as failed so they stop
    blocking their device forever. Returns the ids of jobs it failed.

    Without this, a worker crash (or a job that never reached a worker)
    leaves the device permanently rejecting new jobs with 409."""
    now = _now()
    running_cutoff = now - timedelta(seconds=STALE_RUNNING_SECONDS)
    pending_cutoff = now - timedelta(seconds=STALE_PENDING_SECONDS)
    query = """
        UPDATE jobs
        SET status = 'failed',
            error = CASE status
                WHEN 'running' THEN 'abandoned: worker stopped reporting progress (likely crashed)'
                ELSE 'abandoned: never picked up by a worker'
            END,
            updated_at = %s
        WHERE ((status = 'running' AND updated_at < %s)
            OR (status = 'pending' AND updated_at < %s))
    """
    params = [now, running_cutoff, pending_cutoff]
    if device_id is not None:
        query += " AND device_id = %s"
        params.append(device_id)
    query += " RETURNING id"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            ids = [row[0] for row in cur.fetchall()]
        conn.commit()
    return ids


def has_active_job_for_device(device_id):
    fail_stale_jobs(device_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM jobs WHERE device_id = %s AND status IN ('pending', 'running') LIMIT 1",
                (device_id,),
            )
            row = cur.fetchone()
            return row is not None


def _row_to_dict(row):
    d = dict(row)
    d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
    d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
    return d