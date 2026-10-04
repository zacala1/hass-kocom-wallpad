"""The gas valve is a close-only valve entity and replaces its old switch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from frames import Emulator, frame, wait_until
from homeassistant.components.valve import ValveDeviceClass, ValveEntityFeature
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState
from custom_components.kocom_wallpad.switch import KocomSwitch
from custom_components.kocom_wallpad.valve import KocomValve

GAS = DeviceKey(DeviceType.GASVALVE, 0, 0, SubType.NONE)
OUTLET = DeviceKey(DeviceType.OUTLET, 1, 0, SubType.NONE)
GAS_OPEN = frame(0x2C, 0, 0x01, bytes(8))
GAS_CLOSED = frame(0x2C, 0, 0x02, bytes(8))


def test_gas_valve_frame_is_only_built_for_turn_off() -> None:
    controller = KocomController(SimpleNamespace())
    packet, expectation, _timeout = controller.generate_command(GAS, "turn_off")
    assert packet[9] == 0x02
    assert expectation(DeviceState(GAS, Platform.VALVE, {}, False))
    with pytest.raises(ValueError, match="turn_off"):
        controller.generate_command(GAS, "turn_on")


def test_gas_valve_reports_are_decoded_for_the_valve_platform() -> None:
    states: list[DeviceState] = []
    controller = KocomController(SimpleNamespace(on_device_state=states.append))
    controller._dispatch_packet(GAS_OPEN)
    controller._dispatch_packet(GAS_CLOSED)
    assert [(s.platform, s.state) for s in states] == [
        (Platform.VALVE, True),
        (Platform.VALVE, False),
    ]


@pytest.mark.parametrize(("state", "closed"), [(True, False), (False, True)])
def test_valve_maps_the_reported_state_and_offers_only_close(
    *, state: bool, closed: bool
) -> None:
    valve = KocomValve(
        SimpleNamespace(host="wallpad"), DeviceState(GAS, Platform.VALVE, {}, state)
    )
    assert valve.is_closed is closed
    assert valve.device_class == ValveDeviceClass.GAS
    assert valve.supported_features == ValveEntityFeature.CLOSE
    assert valve.reports_position is False


@pytest.mark.asyncio
async def test_closing_the_valve_sends_the_close_frame() -> None:
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    valve = KocomValve(gateway, DeviceState(GAS, Platform.VALVE, {}, True))
    await valve.async_close_valve()
    gateway.async_send_action.assert_awaited_once_with(GAS, "turn_off")


@pytest.mark.asyncio
async def test_outlet_switch_still_turns_on() -> None:
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    outlet = KocomSwitch(gateway, DeviceState(OUTLET, Platform.SWITCH, {}, False))
    await outlet.async_turn_on()
    gateway.async_send_action.assert_awaited_once_with(OUTLET, "turn_on")


@pytest.mark.asyncio
async def test_valve_services_close_through_the_wire_and_refuse_open(
    hass: HomeAssistant,
) -> None:
    # Given a wallpad that confirms the close frame with a closed report.
    async with Emulator(lambda _packet: [GAS_CLOSED]) as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await wallpad.send(GAS_OPEN)
            await wait_until(lambda: len(hass.states.async_all("valve")) == 1)
            entity_id = hass.states.async_all("valve")[0].entity_id
            assert hass.states.get(entity_id).state == "open"
            # When Home Assistant is asked to close it, the close frame goes out.
            await hass.services.async_call(
                "valve", "close_valve", {"entity_id": entity_id}, blocking=True
            )
            await hass.async_block_till_done()
            assert [packet[9] for packet in wallpad.received] == [0x02]
            assert hass.states.get(entity_id).state == "closed"
            # Opening is not offered and sends nothing.
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "valve", "open_valve", {"entity_id": entity_id}, blocking=True
                )
            assert len(wallpad.received) == 1
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_old_gas_switch_is_replaced_by_the_valve_on_setup(
    hass: HomeAssistant,
) -> None:
    # Given an install from before the valve platform: a saved gas switch and an outlet.
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old_gas = registry.async_get_or_create(
        "switch", DOMAIN, "8-0_0-0:127.0.0.1", config_entry=entry, suggested_object_id="gas"
    )
    outlet = registry.async_get_or_create(
        "switch", DOMAIN, "4-1_0-0:127.0.0.1", config_entry=entry, suggested_object_id="plug"
    )
    mock_restore_cache_with_extra_data(
        hass, [(State(old_gas.entity_id, "on"), {"packet": GAS_OPEN.hex()})]
    )
    async with Emulator() as wallpad:
        hass.config_entries.async_update_entry(
            entry, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        # When the integration starts.
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await hass.async_block_till_done()
            # Then the saved frame becomes a valve and the old switch is gone.
            assert [s.state for s in hass.states.async_all("valve")] == ["open"]
            assert registry.async_get(old_gas.entity_id) is None
            assert registry.async_get(outlet.entity_id) is not None
            valve = registry.async_get(hass.states.async_all("valve")[0].entity_id)
            assert valve.unique_id == "8-0_0-0:127.0.0.1"
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)
