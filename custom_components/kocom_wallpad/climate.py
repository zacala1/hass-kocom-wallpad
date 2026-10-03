"""Climate platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any, List

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
)

from homeassistant.const import Platform, UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .gateway import KocomGateway
from .models import DeviceState
from .entity_base import KocomBaseEntity
from .const import DOMAIN, LOGGER, DeviceType


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom climate platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_climate(devices=None):
        """Add climate entities."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.CLIMATE)

        entities: List[KocomClimate] = []
        for dev in devices:
            entity = KocomClimate(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.CLIMATE), async_add_climate
        )
    )
    async_add_climate()


class KocomClimate(KocomBaseEntity, ClimateEntity):
    """Representation of a Kocom climate."""
    
    _enable_turn_on_off_backwards_compatibility = False

    _attr_min_temp = 5
    _attr_max_temp = 40
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the climate."""
        super().__init__(gateway, device)
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TURN_OFF |
            ClimateEntityFeature.TURN_ON
        )
        if device.attribute.get("feature_fan", False):
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
        if device.attribute.get("feature_preset", False):
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

    @property
    def hvac_mode(self) -> HVACMode:
        return self._device.state["hvac_mode"]
    
    @property
    def hvac_modes(self) -> List[HVACMode]:
        return self._device.attribute["hvac_modes"]
    
    @property
    def fan_mode(self) -> str | None:
        return self._device.state.get("fan_mode")
    
    @property
    def fan_modes(self) -> List[str] | None:
        return self._device.attribute.get("fan_modes")

    @property
    def preset_mode(self) -> str | None:
        return self._device.state.get("preset_mode")
    
    @property
    def preset_modes(self) -> List[str] | None:
        return self._device.attribute.get("preset_modes")

    @property
    def current_temperature(self) -> float | None:
        # The wallpad reports 0 when it has no reading; that is not 0 degC.
        return self._device.state["current_temp"] or None

    @property
    def target_temperature(self) -> float | None:
        return self._device.state["target_temp"] or None
    
    @property
    def target_temperature_step(self) -> float:
        if (
            self._device.key.device_type == DeviceType.THERMOSTAT
            and self.gateway.entry.options.get("thermostat_step", "auto") == "1"
        ):
            return 1.0
        return self._device.attribute["temp_step"]
    
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        args = {"hvac_mode": hvac_mode}
        await self.async_send_command("set_hvac", **args)
        
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        args = {"fan_mode": fan_mode}
        await self.async_send_command("set_fan", **args)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        args = {"preset_mode": preset_mode}
        await self.async_send_command("set_preset", **args)

    async def async_set_temperature(self, **kwargs) -> None:
        args: dict[str, float | HVACMode] = {"target_temp": float(kwargs[ATTR_TEMPERATURE])}
        if (hvac_mode := kwargs.get("hvac_mode")) is not None:
            args["hvac_mode"] = HVACMode(hvac_mode)
        await self.async_send_command("set_temperature", **args)
