"""The elevator call is a button; its progress is shown by the direction sensor."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from frames import Emulator, controller_with, frame, wait_until
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

import custom_components.kocom_wallpad.controller as controller_module
from custom_components.kocom_wallpad.button import KocomButton
from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState

ELEVATOR = DeviceKey(DeviceType.ELEVATOR, 1, 0, SubType.NONE)
DIRECTION = DeviceKey(DeviceType.ELEVATOR, 1, 0, SubType.DIRECTION)


def report(direction: int) -> bytes:
    """An elevator report: 0 idle, 1 downward, 2 upward, 3 arrival (floor unknown)."""
    return frame(0x44, 1, 0x00, bytes([direction]) + bytes(7))


def direction_states(hass: HomeAssistant) -> list[str]:
    return [
        state.state
        for state in hass.states.async_all("sensor")
        if "direction" in state.entity_id
    ]


@pytest.mark.parametrize(
    ("direction", "moving", "label"),
    [(0x00, False, "idle"), (0x01, True, "downward"), (0x02, True, "upward"), (0x03, False, "arrival")],
)
def test_a_report_becomes_a_button_and_a_direction_sensor(
    direction: int, *, moving: bool, label: str
) -> None:
    _controller, registry = controller_with(report(direction))
    button = registry.get(ELEVATOR)
    # The call is a button; the boolean stays on its state to confirm a call.
    assert button.platform == Platform.BUTTON
    assert button.state is moving
    assert registry.get(DIRECTION).state == label
    assert registry.all_by_platform(Platform.SWITCH) == []


def test_only_a_call_frame_exists() -> None:
    controller, _registry = controller_with()
    packet, expectation, _timeout = controller.generate_command(ELEVATOR, "turn_on")
    assert packet[9] == 0x01  # the call command
    assert packet[7] == 0x44  # sent as the elevator device, room 1
    assert expectation(DeviceState(ELEVATOR, Platform.BUTTON, {}, True))
    assert not expectation(DeviceState(ELEVATOR, Platform.BUTTON, {}, False))
    # There is no frame that cancels a call: "off" must not send the call again.
    with pytest.raises(ValueError, match="turn_on"):
        controller.generate_command(ELEVATOR, "turn_off")


@pytest.mark.asyncio
async def test_pressing_the_button_sends_one_call() -> None:
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    button = KocomButton(gateway, DeviceState(ELEVATOR, Platform.BUTTON, {}, False))
    await button.async_press()
    gateway.async_send_action.assert_awaited_once_with(ELEVATOR, "turn_on")


def answer_calls(packet: bytes) -> list[bytes]:
    """A wallpad that starts moving the elevator when it receives a call."""
    return [report(0x01)] if packet[9] == 0x01 else []


@pytest.mark.asyncio
async def test_button_press_reaches_the_wire_and_the_report_confirms_it(
    hass: HomeAssistant,
) -> None:
    async with Emulator(answer_calls) as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await wallpad.send(report(0x00))
            await wait_until(lambda: len(hass.states.async_all("button")) == 1)
            await wait_until(lambda: direction_states(hass) == ["idle"])
            assert hass.states.async_all("switch") == []
            entity_id = hass.states.async_all("button")[0].entity_id
            assert hass.states.get(entity_id).state == "unknown"  # never pressed
            # When the button is pressed, one call frame goes out and is confirmed.
            await hass.services.async_call(
                "button", "press", {"entity_id": entity_id}, blocking=True
            )
            await hass.async_block_till_done()
            assert [packet[9] for packet in wallpad.received] == [0x01]
            # Progress shows on the direction sensor; the button records the press.
            assert direction_states(hass) == ["downward"]
            assert hass.states.get(entity_id).state != "unknown"
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_an_unanswered_call_is_an_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(controller_module, "CMD_CONFIRM_TIMEOUT", 0.1)
    async with Emulator() as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await wallpad.send(report(0x00))
            await wait_until(lambda: len(hass.states.async_all("button")) == 1)
            entity_id = hass.states.async_all("button")[0].entity_id
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "button", "press", {"entity_id": entity_id}, blocking=True
                )
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_old_elevator_switch_is_replaced_by_the_button_on_setup(
    hass: HomeAssistant,
) -> None:
    # Given a saved elevator switch from an earlier version, and an unrelated outlet.
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "switch", DOMAIN, "9-1_0-0:127.0.0.1", config_entry=entry, suggested_object_id="lift"
    )
    outlet = registry.async_get_or_create(
        "switch", DOMAIN, "4-1_0-0:127.0.0.1", config_entry=entry, suggested_object_id="plug"
    )
    mock_restore_cache_with_extra_data(
        hass, [(State(old.entity_id, "off"), {"packet": report(0x00).hex()})]
    )
    async with Emulator() as wallpad:
        hass.config_entries.async_update_entry(
            entry, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await hass.async_block_till_done()
            # Then the saved report becomes a button and the old switch is gone.
            assert len(hass.states.async_all("button")) == 1
            assert registry.async_get(old.entity_id) is None
            assert registry.async_get(outlet.entity_id) is not None
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)
