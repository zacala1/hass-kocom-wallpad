"""Component setup for Kocom Wallpad."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .gateway import KocomGateway


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Kocom Wallpad from a config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    gateway = KocomGateway(hass, entry, host=host, port=port)
    try:
        await gateway.async_get_entity_registry()
        await gateway.async_start()
    except Exception as err:
        # Nothing may have been opened yet (async_stop() is a safe no-op in
        # that case) - either way, don't leave a partially-started gateway
        # (open connection / background tasks) running with no reference to
        # it, and let HA retry setup with its own backoff instead of us
        # blocking here or retrying internally.
        await gateway.async_stop()
        raise ConfigEntryNotReady(
            f"Unable to connect to Kocom wallpad at {host}:{port or ''}: {err}"
        ) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = gateway

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.async_stop)
    )
    entry.async_on_unload(entry.add_update_listener(async_reload_options))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await gateway.async_stop()
        raise

    return True


async def async_reload_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply device options by reloading this gateway."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        gateway: KocomGateway | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if gateway is not None:
            await gateway.async_stop()
    return unload_ok
