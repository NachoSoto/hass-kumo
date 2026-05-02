"""Cloud runtime data for Kumo devices."""
from __future__ import annotations

import json
import logging
from logging.handlers import TimedRotatingFileHandler
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pykumo.py_kumo_cloud_account_v3 import KumoCloudV3

from .const import CLOUD_RUNTIME_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)
REQUEST_LOG_NAME = "kumo_cloud_runtime_requests.jsonl"
REQUEST_LOG_BACKUP_DAYS = 7


class KumoCloudRuntimeCoordinator(DataUpdateCoordinator):
    """Fetch runtime fields exposed by the Mitsubishi Comfort v3 API."""

    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        self._client = KumoCloudV3(username, password)
        self._site_ids: list[str] | None = None
        self._request_logger = KumoCloudRuntimeRequestLogger(
            hass.config.path(REQUEST_LOG_NAME)
        )
        super().__init__(
            hass,
            _LOGGER,
            name="kumo_cloud_runtime",
            update_interval=CLOUD_RUNTIME_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        started_at = time.monotonic()
        try:
            data, details = await self.hass.async_add_executor_job(self._fetch_runtime_data)
            self._request_logger.write(
                duration_ms=elapsed_ms(started_at),
                success=True,
                details=details,
            )
            return data
        except Exception as err:
            self._request_logger.write(
                duration_ms=elapsed_ms(started_at),
                success=False,
                details={"http_status": http_status_from_error(err)},
                error=err,
            )
            raise UpdateFailed(f"Failed to update Kumo cloud runtime: {err}") from err

    def _fetch_runtime_data(self) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        login_attempted = not self._client._access_token
        if not self._client._access_token and not self._client.login():
            raise RuntimeError("V3 login failed")

        fetched_sites = False
        if self._site_ids is None:
            self._site_ids = [
                site["id"]
                for site in self._client.get_sites()
                if isinstance(site, dict) and site.get("id")
            ]
            fetched_sites = True

        runtime_by_serial: dict[str, dict[str, Any]] = {}
        zone_count = 0
        for site_id in self._site_ids:
            for zone in self._client.get_zones(site_id):
                zone_count += 1
                if not isinstance(zone, dict):
                    continue
                adapter = zone.get("adapter", {})
                if not isinstance(adapter, dict):
                    continue
                serial = adapter.get("deviceSerial")
                if not serial:
                    continue
                power = adapter.get("power")
                operation_mode = adapter.get("operationMode")
                runtime_by_serial[str(serial)] = {
                    "cloud_power": power,
                    "cloud_operation_mode": operation_mode,
                    "cloud_previous_operation_mode": adapter.get("previousOperationMode"),
                    "cloud_updated_at": adapter.get("updatedAt"),
                    "running_state": running_state_from_cloud(power, operation_mode),
                }

        return runtime_by_serial, {
            "cadence_seconds": int(CLOUD_RUNTIME_SCAN_INTERVAL.total_seconds()),
            "login_attempted": login_attempted,
            "fetched_sites": fetched_sites,
            "site_count": len(self._site_ids),
            "zone_count": zone_count,
            "runtime_count": len(runtime_by_serial),
        }


class KumoCloudRuntimeRequestLogger:
    """Write cloud request health entries to a rotated JSONL file."""

    def __init__(self, path: str) -> None:
        logger_name = f"{__name__}.requests.{path}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            handler = TimedRotatingFileHandler(
                path,
                when="midnight",
                backupCount=REQUEST_LOG_BACKUP_DAYS,
                encoding="utf-8",
                utc=True,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)

    def write(
        self,
        *,
        duration_ms: int,
        success: bool,
        details: dict[str, Any],
        error: Exception | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": utc_timestamp(),
            "duration_ms": duration_ms,
            "success": success,
            "status": "ok" if success else "error",
        }
        entry.update({key: value for key, value in details.items() if value is not None})
        if error is not None:
            entry["error_type"] = type(error).__name__
            entry["error"] = str(error)[:300]
        self._logger.info(json.dumps(entry, sort_keys=True, separators=(",", ":")))


def running_state_from_cloud(power: Any, operation_mode: Any) -> str:
    """Return actual equipment activity from cloud power plus mode."""
    try:
        is_powered = int(power) > 0
    except (TypeError, ValueError):
        is_powered = bool(power)

    if not is_powered:
        return "idle"

    mode = str(operation_mode or "").strip().lower()
    if mode in {"heat", "autoheat"}:
        return "heating"
    if mode in {"cool", "autocool"}:
        return "cooling"
    if mode == "dry":
        return "drying"
    if mode in {"vent", "fan", "fan_only"}:
        return "fan"
    return "running"


def elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def http_status_from_error(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None:
        return int(status_code)
    status_code = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status_code is not None:
        return int(status_code)
    return None
