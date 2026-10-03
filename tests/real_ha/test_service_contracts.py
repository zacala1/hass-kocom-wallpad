"""Service contracts against real Home Assistant, never the offline shims."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import ATTR_TEMPERATURE, Platform
from homeassistant.exceptions import HomeAssistantError

from custom_components.kocom_wallpad.climate import KocomClimate
from custom_components.kocom_wallpad.const import DeviceType, SubType
from custom_components.kocom_wallpad.fan import KocomFan
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState


def fan_entity() -> KocomFan:
    """Given a ventilation device with its protocol-defined speeds and presets."""
    key = DeviceKey(DeviceType.VENTILATION, 0, 0, SubType.NONE)
    device = DeviceState(
        key,
        Platform.FAN,
        {
            "feature_preset": True,
            "speed_list": [1, 2, 3],
            "preset_modes": ["ventilation", "auto"],
        },
        {"state": False, "speed": 1, "preset_mode": "ventilation"},
    )
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    return KocomFan(gateway, device)


@pytest.mark.asyncio
@pytest.mark.parametrize(("percentage", "speed"), [(0, 0), (33, 1), (66, 2), (100, 3)])
async def test_fan_turn_on_when_percentage_supplied(
    percentage: int, speed: int
) -> None:
    entity = fan_entity()
    # When HA's real service handler forwards percentage positionally.
    await entity.async_handle_turn_on_service(percentage=percentage)
    # Then the existing protocol setter receives the requested speed, including off.
    entity.gateway.async_send_action.assert_awaited_once_with(
        entity._device.key,
        "set_percentage",
        speed=speed,
    )


@pytest.mark.asyncio
async def test_fan_turn_on_when_preset_supplied() -> None:
    entity = fan_entity()
    # When HA forwards a validated preset as the second positional argument.
    await entity.async_handle_turn_on_service(preset_mode="auto")
    # Then the preset is sent rather than ignored.
    entity.gateway.async_send_action.assert_awaited_once_with(
        entity._device.key,
        "set_preset",
        preset_mode="auto",
    )


@pytest.mark.asyncio
async def test_fan_turn_on_when_no_controls_supplied() -> None:
    entity = fan_entity()
    # When no optional control is requested.
    await entity.async_handle_turn_on_service()
    # Then the original ordinary turn-on command is preserved.
    entity.gateway.async_send_action.assert_awaited_once_with(
        entity._device.key, "turn_on"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("percentage", "actions"),
    [
        (66, ["set_percentage"]),
        (0, ["set_percentage"]),
    ],
)
async def test_fan_turn_on_when_both_controls_supplied(
    percentage: int,
    actions: list[str],
) -> None:
    entity = fan_entity()
    # When both controls are provided, zero must remain off rather than apply a preset.
    await entity.async_handle_turn_on_service(percentage=percentage, preset_mode="auto")
    # Then one combined command applies both; zero never activates a preset.
    assert [
        call.args[1] for call in entity.gateway.async_send_action.await_args_list
    ] == actions


@pytest.mark.asyncio
async def test_fan_turn_on_when_preset_invalid() -> None:
    entity = fan_entity()
    # When HA validates an unsupported preset.
    with pytest.raises(HomeAssistantError):
        await entity.async_handle_turn_on_service(preset_mode="unsupported")
    # Then no protocol command reaches the gateway.
    entity.gateway.async_send_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_climate_temperature_when_mode_supplied() -> None:
    # Given a thermostat using the existing protocol commands.
    key = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)
    device = DeviceState(key, Platform.CLIMATE, {}, {})
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    entity = KocomClimate(gateway, device)
    # When a climate temperature service also requests a mode.
    await entity.async_set_temperature(
        **{ATTR_TEMPERATURE: 22, "hvac_mode": HVACMode.HEAT}
    )
    # Then the mode and temperature remain in the same protocol command.
    gateway.async_send_action.assert_awaited_once_with(
        key,
        "set_temperature",
        target_temp=22.0,
        hvac_mode=HVACMode.HEAT,
    )


def test_device_info_when_no_gateway_parent_exists() -> None:
    entity = fan_entity()
    # When device metadata is consumed by the real HA registry.
    info = entity.device_info
    # Then no deprecated, nonexistent parent is declared; existing identity is kept.
    assert "via_device" not in info
    assert info["identifiers"] == {("kocom_wallpad", "KOCOM")}
    assert entity.unique_id == f"{entity._device.key.unique_id}:wallpad"
