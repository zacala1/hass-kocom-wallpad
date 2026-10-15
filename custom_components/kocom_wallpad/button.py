"""Button platform for Kocom Wallpad."""

from __future__ import annotations

from typing import List

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity_base import KocomBaseEntity
from .gateway import KocomGateway
from .models import DeviceState


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


class KocomButton(KocomBaseEntity, ButtonEntity):
    """A momentary wallpad action: calling the elevator."""

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the button."""
        super().__init__(gateway, device)

    async def async_press(self) -> None:
        # The call frame is confirmed by the elevator's next report.
        await self.async_send_command("turn_on")
