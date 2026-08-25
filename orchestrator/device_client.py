"""
DEVICE ABSTRACTION LAYER

This is the key piece that makes the orchestrator "swappable" - it defines
a standard way to talk to a device (get_status, set_power, reset,
upgrade_firmware) without the rest of the orchestrator needing to know
HOW that device is actually reached.

Right now we only have one implementation: SimulatorDeviceClient, which
talks to fake_server.py over HTTP. Later, we could add a
RealArubaSwitchClient or RealPduClient that talks to actual hardware
using whatever protocol it needs (SSH, SNMP, a vendor API, etc) - and the
orchestrator's logic wouldn't need to change at all, because it only ever
talks to the abstract "DeviceClient" interface.

Every request goes through, in order: a rate limiter (protects against
too many requests too quickly), a circuit breaker (fails fast if a
device has been consistently failing), then the actual HTTP call with
retries. Status reads are also cached briefly in Redis.
"""

from abc import ABC, abstractmethod
import requests
import time
from circuit_breaker import circuit_breaker
from cache import get_cached_status, set_cached_status
from rate_limiter import allow_request as rate_limiter_allow


class DeviceClient(ABC):
    """Abstract interface every device client must implement."""

    @abstractmethod
    def get_status(self, device_id: str) -> dict:
        ...

    @abstractmethod
    def set_power(self, device_id: str, power: str) -> dict:
        ...

    @abstractmethod
    def reset(self, device_id: str) -> dict:
        ...

    @abstractmethod
    def upgrade_firmware(self, device_id: str, target_version: str) -> dict:
        ...

    @abstractmethod
    def list_devices(self) -> list:
        ...


class DeviceClientError(Exception):
    """Raised when a device call fails (unreachable, bad response, etc)."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class CircuitOpenError(DeviceClientError):
    """Raised when the circuit breaker is open for a device - we're
    deliberately not even attempting the request."""
    def __init__(self, device_id):
        super().__init__(f"circuit open for device '{device_id}' - too many recent failures", status_code=503)


class RateLimitedError(DeviceClientError):
    """Raised when a device's rate limit has been exceeded."""
    def __init__(self, device_id):
        super().__init__(f"rate limit exceeded for device '{device_id}' - slow down", status_code=429)


class SimulatorDeviceClient(DeviceClient):
    """Talks to fake_server.py over HTTP. This stands in for a real
    device driver until real hardware is available."""

    def __init__(self, base_url: str = "http://localhost:5001", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, device_id: str = None, max_retries: int = 3, **kwargs) -> dict:
        if device_id and not rate_limiter_allow(device_id):
            raise RateLimitedError(device_id)

        # If this call is tied to a specific device, check the circuit
        # breaker before even attempting anything.
        if device_id and not circuit_breaker.allow_request(device_id):
            raise CircuitOpenError(device_id)

        url = f"{self.base_url}{path}"
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                resp = requests.request(method, url, timeout=self.timeout, **kwargs)
            except requests.exceptions.ConnectionError as e:
                last_error = DeviceClientError(f"could not reach device simulator at {url}: {e}")
            except requests.exceptions.Timeout:
                last_error = DeviceClientError(f"device simulator timed out: {url}")
            else:
                if resp.status_code == 503:
                    try:
                        detail = resp.json().get("error", resp.text)
                    except ValueError:
                        detail = resp.text
                    last_error = DeviceClientError(detail, status_code=503)
                elif resp.status_code >= 400:
                    try:
                        detail = resp.json().get("error", resp.text)
                    except ValueError:
                        detail = resp.text
                    if device_id:
                        circuit_breaker.record_failure(device_id)
                    raise DeviceClientError(detail, status_code=resp.status_code)
                else:
                    if device_id:
                        circuit_breaker.record_success(device_id)
                    return resp.json()

            if attempt < max_retries:
                wait_time = 0.5 * (2 ** attempt)
                time.sleep(wait_time)

        if device_id:
            circuit_breaker.record_failure(device_id)
        raise last_error

    def list_devices(self) -> list:
        return self._request("GET", "/devices")

    def get_status(self, device_id: str) -> dict:
        cached = get_cached_status(device_id)
        if cached is not None:
            return cached

        result = self._request("GET", f"/devices/{device_id}/status", device_id=device_id)
        set_cached_status(device_id, result)
        return result

    def set_power(self, device_id: str, power: str) -> dict:
        return self._request(
            "POST", f"/devices/{device_id}/power", device_id=device_id, json={"power": power}
        )

    def reset(self, device_id: str) -> dict:
        return self._request("POST", f"/devices/{device_id}/reset", device_id=device_id)

    def upgrade_firmware(self, device_id: str, target_version: str) -> dict:
        return self._request(
            "POST",
            f"/devices/{device_id}/firmware",
            device_id=device_id,
            json={"target_version": target_version},
        )