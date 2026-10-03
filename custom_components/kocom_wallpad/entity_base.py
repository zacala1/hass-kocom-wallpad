"""Base platform for Kocom Wallpad."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.fan import FanEntityDescription
from homeassistant.components.light import LightEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoredExtraData, RestoreEntity

from .const import DOMAIN, DeviceType, SubType

if TYPE_CHECKING:
    from .gateway import KocomGateway
    from .models import DeviceState


ENTITY_DESCRIPTION_MAP = {
    Platform.LIGHT: LightEntityDescription,
    Platform.SWITCH: SwitchEntityDescription,
    Platform.CLIMATE: ClimateEntityDescription,
    Platform.FAN: FanEntityDescription,
    Platform.SENSOR: SensorEntityDescription,
    Platform.BINARY_SENSOR: BinarySensorEntityDescription
}


class KocomBaseEntity(RestoreEntity):
    """Base class for Kocom entities."""

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the base entity."""
        super().__init__()
        self.gateway = gateway
        self._device = device
        self._unsubs: list[Callable[[], None]] = []
        self._attr_available = False

        self._attr_unique_id = f"{device.key.unique_id}:{self.gateway.host}"
        self.entity_description = ENTITY_DESCRIPTION_MAP[self._device.platform](
            key=self.format_key,
            has_entity_name=True,
            translation_key=self.format_key,
            translation_placeholders={"id": self.format_translation_placeholders}
        )
        self._attr_device_info = DeviceInfo(
            connections={(self.gateway.host, self.unique_id)},
            identifiers={(DOMAIN, f"{self.format_identifiers}")},
            manufacturer="KOCOM Co., Ltd",
            model="Smart Wallpad",
            name=f"{self.format_identifiers}",
        )

    async def async_send_command(
        self, action: str, **kwargs: bool | int | float | str
    ) -> None:
        """Raise an HA action error unless the gateway confirms the command."""
        confirmed = await self.gateway.async_send_action(
            self._device.key, action, **kwargs
        )
        if confirmed is not True:
            message = "Kocom command was not confirmed"
            raise HomeAssistantError(message)
        
    @property
    def format_key(self) -> str:
        if self._device.key.sub_type == SubType.NONE:
            return self._device.key.device_type.name.lower()
        else:
            return f"{self._device.key.device_type.name.lower()}-{self._device.key.sub_type.name.lower()}"

    @property
    def format_translation_placeholders(self) -> str:
        if self._device.key.sub_type == SubType.NONE:
            return f"{str(self._device.key.room_index)}-{str(self._device.key.device_index)}"
        else:
            return f"{str(self._device.key.room_index)}-{str(self._device.key.device_index)}"

    @property
    def format_identifiers(self) -> str:
        if self._device.key.device_type in {
            DeviceType.VENTILATION, DeviceType.GASVALVE, DeviceType.ELEVATOR, DeviceType.MOTION
        }:
            return f"KOCOM"
        elif self._device.key.device_type in {
            DeviceType.LIGHT, DeviceType.LIGHTCUTOFF, DeviceType.DIMMINGLIGHT
        }:
            return f"KOCOM LIGHT"
        else:
            return f"KOCOM {self._device.key.device_type.name}"

    async def async_added_to_hass(self) -> None:
        self._attr_available = self.gateway.is_device_available(self._device.key)
        sig = self.gateway.async_signal_device_updated(self._device.key.unique_id)

        @callback
        def _handle_update(dev: DeviceState) -> None:
            self._device = dev
            self._attr_available = self.gateway.is_device_available(dev.key)
            self.update_from_state()
        self._unsubs.append(async_dispatcher_connect(self.hass, sig, _handle_update))

        @callback
        # HA dispatcher callbacks receive this state as a positional argument.
        def _handle_connection(connected: bool) -> None:  # noqa: FBT001
            # Losing the link always blocks; regaining it only helps devices that
            # stay available without a fresh report (see is_device_available).
            available = connected and self.gateway.is_device_available(
                self._device.key
            )
            if available != self._attr_available:
                self._attr_available = available
                self.async_write_ha_state()

        self._unsubs.append(async_dispatcher_connect(
            self.hass, self.gateway.async_signal_connection_state(), _handle_connection
        ))

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()

    @callback
    def update_from_state(self) -> None:
        self.async_write_ha_state()

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        return RestoredExtraData({
            "packet": getattr(self._device, "_packet", bytes()).hex(),
            "device_storage": self.gateway.controller._device_storage
        })
