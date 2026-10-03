"""The gas valve frame exists for one direction only; the other is refused."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError

from custom_components.kocom_wallpad.const import DeviceType, SubType
from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState
from custom_components.kocom_wallpad.switch import KocomSwitch

GAS = DeviceKey(DeviceType.GASVALVE, 0, 0, SubType.NONE)
OUTLET = DeviceKey(DeviceType.OUTLET, 1, 0, SubType.NONE)


def test_gas_valve_frame_is_only_built_for_turn_off() -> None:
    controller = KocomController(SimpleNamespace())
    packet, expectation, _timeout = controller.generate_command(GAS, "turn_off")
    assert packet[9] == 0x02
    assert expectation(DeviceState(GAS, Platform.SWITCH, {}, False))
    with pytest.raises(ValueError, match="turn_off"):
        controller.generate_command(GAS, "turn_on")


@pytest.mark.asyncio
async def test_gas_switch_refuses_turn_on_without_sending() -> None:
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    valve = KocomSwitch(gateway, DeviceState(GAS, Platform.SWITCH, {}, True))
    with pytest.raises(HomeAssistantError, match="switched off"):
        await valve.async_turn_on()
    gateway.async_send_action.assert_not_awaited()
    await valve.async_turn_off()
    gateway.async_send_action.assert_awaited_once_with(GAS, "turn_off")


@pytest.mark.asyncio
async def test_outlet_switch_still_turns_on() -> None:
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    outlet = KocomSwitch(gateway, DeviceState(OUTLET, Platform.SWITCH, {}, False))
    await outlet.async_turn_on()
    gateway.async_send_action.assert_awaited_once_with(OUTLET, "turn_on")
