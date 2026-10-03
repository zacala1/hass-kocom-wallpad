"""Fan platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any, List

from homeassistant.components.fan import FanEntity, FanEntityFeature

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .gateway import KocomGateway
from .models import DeviceState
from .entity_base import KocomBaseEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom fan platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_fan(devices=None):
        """Add fan entities."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.FAN)

        entities: List[KocomFan] = []
        for dev in devices:
            entity = KocomFan(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.FAN), async_add_fan
        )
    )
    async_add_fan()


class KocomFan(KocomBaseEntity, FanEntity):
    """Representation of a Kocom fan."""

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the fan."""
        super().__init__(gateway, device)
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.TURN_ON
        )
        if device.attribute["feature_preset"]:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE

    @callback
    def update_from_state(self) -> None:
        """Refresh learned preset capability flags with each device report."""
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.TURN_ON
        )
        if self._device.attribute.get("feature_preset", False):
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE
        super().update_from_state()

    @property
    def is_on(self) -> bool:
        return self._device.state["state"]

    @property
    def speed_count(self) -> int:
        return len(self._device.attribute["speed_list"])

    @property
    def percentage(self) -> int | None:
        speed = self._device.state["speed"]
        if not self._device.state["state"] or speed == 0:
            return 0
        speed_list = self._device.attribute["speed_list"]
        if speed not in speed_list:
            # A speed code this integration does not know has no known percentage.
            return None
        return ordered_list_item_to_percentage(speed_list, speed)

    @property
    def preset_mode(self) -> str:
        return self._device.state["preset_mode"]

    @property
    def preset_modes(self) -> List[str]:
        return self._device.attribute["preset_modes"]

    async def async_set_percentage(self, percentage: int) -> None:
        args = {"speed": 0}
        if percentage > 0:
            args["speed"] = percentage_to_ordered_list_item(
                self._device.attribute["speed_list"], percentage
            )
        await self.async_send_command("set_percentage", **args)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        args = {"preset_mode": preset_mode}
        await self.async_send_command("set_preset", **args)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        if percentage == 0:
            await self.async_set_percentage(0)
            return
        if percentage is not None and preset_mode is not None:
            speed = percentage_to_ordered_list_item(
                self._device.attribute["speed_list"], percentage
            )
            await self.async_send_command(
                "set_percentage", speed=speed, preset_mode=preset_mode
            )
        elif preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self.async_send_command("turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_send_command("turn_off")
