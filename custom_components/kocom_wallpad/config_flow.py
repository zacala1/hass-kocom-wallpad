"""Config flow for Kocom Wallpad."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, DEFAULT_TCP_PORT, LOGGER
from .options_flow import KocomOptionsFlow
from .transport import AsyncConnection

CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_TCP_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
)


async def _async_can_connect(host: str, port: int | None) -> bool:
    """Open and close one connection to prove the address is reachable."""
    connection = AsyncConnection(host=host, port=port)
    try:
        await connection.open()
    except Exception as err:  # serial libraries raise errors that are not OSError
        LOGGER.debug("Connection test to %s:%s failed: %r", host, port, err)
        return False
    finally:
        await connection.close()
    return True


def _normalize(user_input: dict[str, Any]) -> tuple[str, int | None]:
    """Return the trimmed host and the port (None for a serial device path)."""
    host: str = user_input[CONF_HOST].strip()
    # 시리얼의 경우 host가 "/"로 시작하면 장치 경로로 간주하고 port 무시
    port: int | None = None if host.startswith("/") else user_input[CONF_PORT]
    return host, port


class KocomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Kocom Wallpad."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return options using the HA-owned config entry."""
        return KocomOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host, port = _normalize(user_input)
            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                if await _async_can_connect(host, port):
                    return self.async_create_entry(
                        title=host, data={CONF_HOST: host, CONF_PORT: port}
                    )
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address of an existing entry without losing its entities."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host, port = _normalize(user_input)
            old_host: str = entry.data[CONF_HOST]
            old_port: int | None = entry.data[CONF_PORT]
            if not host:
                errors[CONF_HOST] = "invalid_host"
            elif any(
                other.entry_id != entry.entry_id and other.unique_id == host
                for other in self._async_current_entries(include_ignore=False)
            ):
                return self.async_abort(reason="already_configured")
            elif (host, port) == (old_host, old_port) or await _async_can_connect(
                host, port
            ):
                if host != old_host:
                    self._migrate_entity_unique_ids(entry, old_host, host)
                # Updating the entry reloads it through the entry's update listener.
                self.hass.config_entries.async_update_entry(
                    entry,
                    title=host if entry.title == old_host else entry.title,
                    unique_id=host,
                    data={CONF_HOST: host, CONF_PORT: port},
                )
                return self.async_abort(reason="reconfigure_successful")
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CONNECTION_SCHEMA,
                user_input
                or {CONF_HOST: entry.data[CONF_HOST], CONF_PORT: entry.data[CONF_PORT] or DEFAULT_TCP_PORT},
            ),
            errors=errors,
        )

    def _migrate_entity_unique_ids(
        self, entry: ConfigEntry, old_host: str, new_host: str
    ) -> None:
        """Entity unique ids end with ':<host>'; keep entities when the host changes."""
        registry = er.async_get(self.hass)
        suffix = f":{old_host}"
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if not entity.unique_id.endswith(suffix):
                continue
            new_unique_id = f"{entity.unique_id.removesuffix(suffix)}:{new_host}"
            try:
                registry.async_update_entity(
                    entity.entity_id, new_unique_id=new_unique_id
                )
            except ValueError:
                LOGGER.warning(
                    "Could not move %s to unique id %s", entity.entity_id, new_unique_id
                )
