"""
Shared test setup.

Tests run against their own Postgres database and Redis DB number so
they never touch dev data, and every test starts from empty tables and
an empty Redis. Without this, firmware jobs enqueued by one run stay
'pending' forever (no worker runs during tests), and the next run gets
409 "job already in progress" for those devices.

Env vars are set in pytest_configure, before any orchestrator module is
imported, because those modules read their config at import time.
"""

import os

import psycopg2
import pytest
from psycopg2 import sql

TEST_DB = "infra_automation_test"
TEST_REDIS_DB = "15"


def pytest_configure(config):
    os.environ["POSTGRES_DB"] = TEST_DB
    os.environ["REDIS_DB"] = TEST_REDIS_DB
    _create_test_db_if_missing()


def _admin_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname="postgres",
        user=os.environ.get("POSTGRES_USER", "infra"),
        password=os.environ.get("POSTGRES_PASSWORD", "infra_dev_password"),
    )


def _create_test_db_if_missing():
    try:
        conn = _admin_conn()
    except psycopg2.OperationalError:
        # Postgres isn't up; simulator-only tests can still run, and the
        # orchestrator tests will fail with a clear connection error.
        return
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    finally:
        conn.close()


@pytest.fixture
def clean_state():
    """Empty the jobs/audit tables and the test Redis DB."""
    import jobs
    import audit
    from redis import Redis

    jobs.init_db()
    audit.init_db()
    with jobs.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE jobs, audit_log")
        conn.commit()

    Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        db=int(TEST_REDIS_DB),
    ).flushdb()
    yield
