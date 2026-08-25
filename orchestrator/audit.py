"""
AUDIT LOG

Records every meaningful action taken through the orchestrator: who did
it (which API key/role), what they did, on which device, when, and what
the result was. This is the "who changed what, and when" record - the
real version of the "IAM-like interface" from the original project idea.
"""

import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from contextlib import contextmanager

DB_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": os.environ.get("POSTGRES_PORT", "5432"),
    "dbname": os.environ.get("POSTGRES_DB", "infra_automation"),
    "user": os.environ.get("POSTGRES_USER", "infra"),
    "password": os.environ.get("POSTGRES_PASSWORD", "infra_dev_password"),
}


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    device_id TEXT,
                    details JSONB,
                    result TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
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


def log_action(actor, action, device_id=None, details=None, result="success"):
    """Records one entry in the audit log. Call this any time a
    meaningful action happens - a power change, firmware upgrade, etc."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO audit_log (actor, action, device_id, details, result, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (actor, action, device_id, json.dumps(details or {}), result, datetime.now(timezone.utc)),
            )
        conn.commit()


def list_entries(device_id=None, limit=100):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if device_id:
                cur.execute(
                    "SELECT * FROM audit_log WHERE device_id = %s ORDER BY created_at DESC LIMIT %s",
                    (device_id, limit),
                )
            else:
                cur.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
            return [_row_to_dict(r) for r in rows]


def _row_to_dict(row):
    d = dict(row)
    d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
    return d