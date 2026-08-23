"""
DEVICE STATUS CACHE

Caches device status reads in Redis for a short time (a few seconds),
so repeated calls (e.g. a dashboard polling frequently) don't hammer
the device with a fresh request every single time.

This intentionally only caches READS (get_status) - actions that change
something (power, reset, firmware) always go straight to the real
device, since caching those would mean the action might not actually
happen when the caller thinks it did.
"""

import os
import json
from redis import Redis

redis_conn = Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
)

DEFAULT_TTL_SECONDS = 5


def get_cached_status(device_id):
    """Returns the cached status dict for a device, or None if there's
    nothing cached (or it expired)."""
    key = f"device_status:{device_id}"
    raw = redis_conn.get(key)
    if raw is None:
        return None
    return json.loads(raw)


def set_cached_status(device_id, status, ttl_seconds=DEFAULT_TTL_SECONDS):
    """Saves a device's status in the cache, automatically expiring
    after ttl_seconds."""
    key = f"device_status:{device_id}"
    redis_conn.set(key, json.dumps(status), ex=ttl_seconds)


def invalidate_status(device_id):
    """Removes any cached status for a device - useful right after an
    action (power, reset, firmware) changes its state, so the next read
    doesn't return stale cached data."""
    key = f"device_status:{device_id}"
    redis_conn.delete(key)