"""
RATE LIMITER (token bucket)

Protects against a single device (or the orchestrator itself) being
overwhelmed by too many requests too quickly. Uses a "token bucket":
each device has a bucket that holds a maximum number of tokens, each
request costs 1 token, and the bucket refills gradually over time.

This allows short bursts (up to the bucket size) while still capping
the sustained average rate. Stored in Redis rather than in-memory so
the limit is shared correctly even if multiple orchestrator instances
or workers are running.
"""

import os
import time
import json
from redis import Redis

redis_conn = Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
)

BUCKET_CAPACITY = 10       # max tokens (max burst size)
REFILL_RATE_PER_SEC = 2.0  # tokens added back per second


def allow_request(device_id):
    """Returns True if this request is allowed (and consumes a token),
    False if the device is being rate limited right now."""
    key = f"rate_limit:{device_id}"
    now = time.time()

    raw = redis_conn.get(key)
    if raw is None:
        bucket = {"tokens": BUCKET_CAPACITY, "last_refill": now}
    else:
        bucket = json.loads(raw)

    elapsed = now - bucket["last_refill"]
    refilled_tokens = elapsed * REFILL_RATE_PER_SEC
    bucket["tokens"] = min(BUCKET_CAPACITY, bucket["tokens"] + refilled_tokens)
    bucket["last_refill"] = now

    if bucket["tokens"] >= 1:
        bucket["tokens"] -= 1
        allowed = True
    else:
        allowed = False

    redis_conn.set(key, json.dumps(bucket), ex=60)
    return allowed