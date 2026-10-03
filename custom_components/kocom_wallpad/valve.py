"""Valve platform for Kocom Wallpad."""

from __future__ import annotations

from typing import List

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
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
    """Set up Kocom valve platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_valve(devices=None):
        """Add valve entities."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.VALVE)

        entities: List[KocomValve] = [KocomValve(gateway, dev) for dev in devices]
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.VALVE), async_add_valve
        )
    )
    async_add_valve()


class KocomValve(KocomBaseEntity, ValveEntity):
    """The wallpad gas valve: the wallpad can close it but never open it."""

    _attr_device_class = ValveDeviceClass.GAS
    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.CLOSE

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the valve."""
        super().__init__(gateway, device)

    @property
    def is_closed(self) -> bool:
        # The wallpad's closed status maps to the "off" state of the decoded frame.
        return not self._device.state

    async def async_close_valve(self) -> None:
        await self.async_send_command("turn_off")
