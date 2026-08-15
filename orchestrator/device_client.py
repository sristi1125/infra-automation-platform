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
"""

from abc import ABC, abstractmethod
import requests
import time


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


class SimulatorDeviceClient(DeviceClient):
    """Talks to fake_server.py over HTTP. This stands in for a real
    device driver until real hardware is available."""

    def __init__(self, base_url: str = "http://localhost:5001", timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, max_retries: int = 3, **kwargs) -> dict:
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
                    raise DeviceClientError(detail, status_code=resp.status_code)
                else:
                    return resp.json()

            if attempt < max_retries:
                wait_time = 0.5 * (2 ** attempt)
                time.sleep(wait_time)

        raise last_error

    def list_devices(self) -> list:
        return self._request("GET", "/devices")

    def get_status(self, device_id: str) -> dict:
        return self._request("GET", f"/devices/{device_id}/status")

    def set_power(self, device_id: str, power: str) -> dict:
        return self._request(
            "POST", f"/devices/{device_id}/power", json={"power": power}
        )

    def reset(self, device_id: str) -> dict:
        return self._request("POST", f"/devices/{device_id}/reset")

    def upgrade_firmware(self, device_id: str, target_version: str) -> dict:
        return self._request(
            "POST",
            f"/devices/{device_id}/firmware",
            json={"target_version": target_version},
        )