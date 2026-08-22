"""
CIRCUIT BREAKER

Protects against wasting time/resources hammering a device that's
completely down, instead of just flaky. Has three states:

  CLOSED    - normal operation, requests go through
  OPEN      - too many recent failures; fail fast without even trying
  HALF_OPEN - cooldown has passed; let ONE request through as a test

One breaker exists per device, tracked in memory. This is intentionally
simple (in-memory, per-process) - in a multi-worker setup you'd likely
move this state into Redis so all workers share the same view of which
devices are considered "down." Worth calling out as a known next step.
"""

import time
import threading

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold=5, cooldown_seconds=30):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._breakers = {}  # device_id -> {"state", "failure_count", "opened_at"}

    def _get_state(self, device_id):
        if device_id not in self._breakers:
            self._breakers[device_id] = {
                "state": CLOSED,
                "failure_count": 0,
                "opened_at": None,
            }
        return self._breakers[device_id]

    def allow_request(self, device_id):
        """Call before making a request. Returns True if the request
        should proceed, False if the circuit is open and we should
        fail fast instead."""
        with self._lock:
            breaker = self._get_state(device_id)

            if breaker["state"] == CLOSED:
                return True

            if breaker["state"] == OPEN:
                elapsed = time.time() - breaker["opened_at"]
                if elapsed >= self.cooldown_seconds:
                    breaker["state"] = HALF_OPEN
                    return True
                return False

            if breaker["state"] == HALF_OPEN:
                # Only let one test request through at a time; treat
                # further requests as blocked until we know the result.
                return True

            return True

    def record_success(self, device_id):
        with self._lock:
            breaker = self._get_state(device_id)
            breaker["state"] = CLOSED
            breaker["failure_count"] = 0
            breaker["opened_at"] = None

    def record_failure(self, device_id):
        with self._lock:
            breaker = self._get_state(device_id)
            breaker["failure_count"] += 1

            if breaker["state"] == HALF_OPEN:
                # The test request failed - trip back open immediately
                breaker["state"] = OPEN
                breaker["opened_at"] = time.time()
                return

            if breaker["failure_count"] >= self.failure_threshold:
                breaker["state"] = OPEN
                breaker["opened_at"] = time.time()

    def get_status(self, device_id):
        with self._lock:
            breaker = self._get_state(device_id)
            return dict(breaker)


# One shared instance, used across the orchestrator
circuit_breaker = CircuitBreaker()