"""Combined HA controls must survive the real Kocom packet encoder."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import Platform

from custom_components.kocom_wallpad.climate import KocomClimate
from custom_components.kocom_wallpad.const import DeviceType, SubType
from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.fan import KocomFan
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("device_type", "mode", "payload"),
    [
        (DeviceType.THERMOSTAT, HVACMode.HEAT, b"\x11\x00\x16\x00\x00\x00\x00\x00"),
        (DeviceType.THERMOSTAT, HVACMode.OFF, b"\x00\x00\x16\x00\x00\x00\x00\x00"),
        (DeviceType.AIRCONDITIONER, HVACMode.DRY, b"\x10\x02\x00\x00\x00\x16\x00\x00"),
        (
            DeviceType.AIRCONDITIONER,
            HVACMode.FAN_ONLY,
            b"\x10\x01\x00\x00\x00\x16\x00\x00",
        ),
        (DeviceType.AIRCONDITIONER, HVACMode.AUTO, b"\x10\x03\x00\x00\x00\x16\x00\x00"),
        (DeviceType.AIRCONDITIONER, HVACMode.OFF, b"\x00\x00\x00\x00\x00\x16\x00\x00"),
    ],
)
async def test_temperature_wire_when_mode_explicit(
    device_type: DeviceType,
    mode: HVACMode,
    payload: bytes,
) -> None:
    # Given the real entity and encoder; only physical transmission is recorded.
    key = DeviceKey(device_type, 1, 0, SubType.NONE)
    device = DeviceState(key, Platform.CLIMATE, {}, {})
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock())
    entity = KocomClimate(gateway, device)
    controller = KocomController(gateway)
    # When HA asks for a temperature and mode in the same service request.
    await entity.async_set_temperature(temperature=22, hvac_mode=mode)
    calls = gateway.async_send_action.await_args_list
    packet, expectation, _timeout = controller.generate_command(
        *calls[-1].args, **calls[-1].kwargs
    )
    # Then the last packet contains both, including OFF, and confirmation requires both.
    assert packet[10:18] == payload
    assert len(calls) == 1
    matching = DeviceState(
        key, Platform.CLIMATE, {}, {"target_temp": 22.0, "hvac_mode": mode}
    )
    assert expectation(matching)
    wrong = HVACMode.HEAT if mode == HVACMode.OFF else HVACMode.OFF
    mismatching = DeviceState(
        key, Platform.CLIMATE, {}, {"target_temp": 22.0, "hvac_mode": wrong}
    )
    assert not expectation(mismatching)


@pytest.mark.asyncio
async def test_fan_wire_when_speed_and_preset_explicit() -> None:
    # Given a ventilation device's actual protocol speed bytes.
    key = DeviceKey(DeviceType.VENTILATION, 0, 0, SubType.NONE)
    device = DeviceState(
        key,
        Platform.FAN,
        {
            "feature_preset": True,
            "speed_list": [0x40, 0x80, 0xC0],
            "preset_modes": ["ventilation", "auto"],
        },
        {},
    )
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock())
    entity = KocomFan(gateway, device)
    controller = KocomController(gateway)
    # When the real HA handler forwards both controls.
    await entity.async_handle_turn_on_service(percentage=66, preset_mode="auto")
    calls = gateway.async_send_action.await_args_list
    packet, expectation, _timeout = controller.generate_command(
        *calls[-1].args, **calls[-1].kwargs
    )
    # Then one outgoing packet retains both bytes; a speed-only reply is insufficient.
    assert packet[10:18] == b"\x11\x02\x80\x00\x00\x00\x00\x00"
    assert len(calls) == 1
    matching = DeviceState(
        key, Platform.FAN, {}, {"speed": 0x80, "preset_mode": "auto"}
    )
    assert expectation(matching)
    mismatching = DeviceState(
        key, Platform.FAN, {}, {"speed": 0x80, "preset_mode": "ventilation"}
    )
    assert not expectation(mismatching)
