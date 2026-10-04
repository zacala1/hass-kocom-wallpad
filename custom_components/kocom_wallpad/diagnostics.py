"""Diagnostics for Kocom Wallpad."""

from __future__ import annotations

from enum import Enum
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACTED = "**REDACTED**"


def _plain(value: Any) -> Any:
    """Reduce states and attributes to what a JSON diagnostics file can hold."""
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return what is needed to understand a report, without the address.

    The host (an IP, a name or a serial device path) is redacted everywhere. Frames
    carry only device codes, rooms and values, so they are included as they are:
    they are what lets the protocol be checked or extended for another model.
    """
    host: str = entry.data.get(CONF_HOST) or ""
    data: dict[str, Any] = {
        "entry": {
            "title": REDACTED,
            "version": entry.version,
            "data": {
                CONF_HOST: REDACTED,
                CONF_PORT: entry.data.get(CONF_PORT),
                "transport": "serial" if host.startswith("/") else "tcp",
            },
            "options": _plain(dict(entry.options)),
        },
        "loaded": False,
    }
    gateway = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if gateway is None:
        return data
    data["loaded"] = True
    data.update(_plain(gateway.diagnostics_snapshot()))
    return data
