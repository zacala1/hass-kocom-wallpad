"""Button platform for Kocom Wallpad."""

from __future__ import annotations

from typing import List

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DeviceType
from .entity_base import KocomBaseEntity, wallpad_device_info
from .gateway import KocomGateway
from .models import DeviceKey, DeviceState

# Stop when this many lights in a row stay silent: the wallpad is not answering.
MAX_SILENT_LIGHTS = 3


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom button platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_button(devices=None):
        """Add button entities."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.BUTTON)

        entities: List[KocomButton] = [KocomButton(gateway, dev) for dev in devices]
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.BUTTON), async_add_button
        )
    )
    async_add_button()
    async_add_entities([KocomAllLightsOffButton(gateway)])


class KocomButton(KocomBaseEntity, ButtonEntity):
    """A momentary wallpad action: calling the elevator."""

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the button."""
        super().__init__(gateway, device)

    async def async_press(self) -> None:
        # The call frame is confirmed by the elevator's next report.
        await self.async_send_command("turn_on")


class KocomAllLightsOffButton(ButtonEntity):
    """Turns off every light that is on, one ordinary light command at a time.

    The wallpad's own all-off signal is only ever received (see the all-off binary
    sensor), so this button sends no new kind of frame: it switches the known
    lights off exactly as the light entities do.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "all-lights-off"

    def __init__(self, gateway: KocomGateway) -> None:
        """Initialize the button."""
        self.gateway = gateway
        # Entity unique ids end with ":<host>"; reconfigure relies on that suffix.
        self._attr_unique_id = f"all-lights-off:{gateway.host}"
        self._attr_device_info = wallpad_device_info(
            gateway, "KOCOM LIGHT", self._attr_unique_id
        )
        self._attr_available = False

    async def async_added_to_hass(self) -> None:
        self._attr_available = self.gateway.connected

        @callback
        def _connection_changed(connected: bool) -> None:  # noqa: FBT001
            self._attr_available = connected
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self.gateway.async_signal_connection_state(),
                _connection_changed,
            )
        )

    def _is_off(self, key: DeviceKey) -> bool:
        known = self.gateway.registry.get(key)
        return known is not None and known.state is False

    async def async_press(self) -> None:
        if not self.gateway.connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            )
        lights = [
            device.key
            for device in self.gateway.get_devices_from_platform(Platform.LIGHT)
            if device.key.device_type == DeviceType.LIGHT
        ]
        pending = [key for key in lights if not self._is_off(key)]
        switched, silent_in_a_row = 0, 0
        for key in pending:
            # A report for an earlier light may already have switched this one off.
            if self._is_off(key):
                switched += 1
                continue
            if await self.gateway.async_send_action(key, "turn_off"):
                switched += 1
                silent_in_a_row = 0
                continue
            silent_in_a_row += 1
            if silent_in_a_row >= MAX_SILENT_LIGHTS or not self.gateway.connected:
                break
        if switched < len(pending):
            if not self.gateway.connected:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="not_connected"
                )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="lights_off_incomplete",
                translation_placeholders={
                    "failed": str(len(pending) - switched),
                    "total": str(len(pending)),
                },
            )
