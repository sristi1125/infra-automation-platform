"""
JOB MODEL

Tracks orchestrator actions (like firmware upgrades) as jobs with an ID,
so we can check "is this done yet?" instead of just firing a request and
hoping for the best.
"""

import sqlite3
import uuid
import json
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = "jobs.db"


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                params TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def create_job(device_id, action, params=None):
    job_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO jobs (id, device_id, action, status, params, result, error, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, NULL, NULL, ?, ?)""",
            (job_id, device_id, action, json.dumps(params or {}), now, now),
        )
        conn.commit()
    return get_job(job_id)


def update_job(job_id, status, result=None, error=None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE jobs SET status = ?, result = ?, error = ?, updated_at = ?
               WHERE id = ?""",
            (status, json.dumps(result) if result is not None else None, error, _now(), job_id),
        )
        conn.commit()
    return get_job(job_id)


def get_job(job_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def list_jobs(device_id=None):
    with get_conn() as conn:
        if device_id:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE device_id = ? ORDER BY created_at DESC", (device_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [_row_to_dict(r) for r in rows]


def has_active_job_for_device(device_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM jobs WHERE device_id = ? AND status IN ('pending', 'running') LIMIT 1",
            (device_id,),
        ).fetchone()
        return row is not None


def _row_to_dict(row):
    d = dict(row)
    d["params"] = json.loads(d["params"]) if d["params"] else {}
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d