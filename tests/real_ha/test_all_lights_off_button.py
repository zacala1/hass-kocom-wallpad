"""The "turn off all lights" button switches the known lights off one by one."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from frames import Emulator, frame, wait_until
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.kocom_wallpad.controller as controller_module
from custom_components.kocom_wallpad.button import KocomAllLightsOffButton
from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.gateway import EntityRegistry
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState

ON = bytes([0xFF, 0xFF]) + bytes(6)  # room 1: lights 0 and 1 on
ROOM2_ON = bytes([0xFF]) + bytes(7)  # room 2: light 0 on
BUTTON_UNIQUE_ID = "all-lights-off:127.0.0.1"


def light_commands(wallpad: Emulator) -> list[bytes]:
    """The frames the wallpad received that address a light."""
    return [packet for packet in wallpad.received if packet[5] == 0x0E]


def follow_every_light_command(packet: bytes) -> list[bytes]:
    """A wallpad that carries out a light command and reports the room's state."""
    if packet[5] != 0x0E:
        return []
    return [frame(0x0E, packet[6], 0x00, packet[10:18])]


def follow_room_one_only(packet: bytes) -> list[bytes]:
    """A wallpad whose room 2 never answers."""
    return follow_every_light_command(packet) if packet[6] == 1 else []


async def start(hass: HomeAssistant, wallpad: Emulator) -> tuple[MockConfigEntry, str]:
    """Set the integration up on the emulator with three lights on in two rooms."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wallpad.send(frame(0x0E, 1, 0x00, ON))
    await wallpad.send(frame(0x0E, 2, 0x00, ROOM2_ON))
    await wait_until(lambda: len(hass.states.async_all("light")) == 3)
    button = er.async_get(hass).async_get_entity_id("button", DOMAIN, BUTTON_UNIQUE_ID)
    assert button is not None
    return entry, button


def light_states(hass: HomeAssistant) -> list[str]:
    return sorted(state.state for state in hass.states.async_all("light"))


async def press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_pressing_it_switches_off_each_light_that_is_on(
    hass: HomeAssistant,
) -> None:
    async with Emulator(follow_every_light_command) as wallpad:
        entry, button = await start(hass, wallpad)
        try:
            # Given three lights that are on and a button that is ready.
            assert light_states(hass) == ["on", "on", "on"]
            assert hass.states.get(button).state != "unavailable"
            # When the button is pressed, every light gets its own off command.
            await press(hass, button)
            commands = light_commands(wallpad)
            assert len(commands) == 3
            assert light_states(hass) == ["off", "off", "off"]
            # Nothing but ordinary light commands goes out, never a broadcast.
            assert {packet[5] for packet in wallpad.received} == {0x0E}
            assert 0xFF not in {packet[6] for packet in wallpad.received}
            # When it is pressed again, the lights that are already off are left alone.
            await press(hass, button)
            assert len(light_commands(wallpad)) == 3
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_a_silent_room_is_reported_with_the_counts_and_the_rest_still_goes_off(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(controller_module, "CMD_CONFIRM_TIMEOUT", 0.1)
    async with Emulator(follow_room_one_only) as wallpad:
        entry, button = await start(hass, wallpad)
        try:
            # When room 2 never confirms its light,
            with pytest.raises(HomeAssistantError) as raised:
                await press(hass, button)
            # then the error says how many failed, and room 1 is off anyway.
            assert raised.value.translation_domain == DOMAIN
            assert raised.value.translation_key == "lights_off_incomplete"
            assert raised.value.translation_placeholders == {"failed": "1", "total": "3"}
            assert light_states(hass) == ["off", "off", "on"]
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)


def gateway_with_lights(count: int, *, connected: bool = True) -> SimpleNamespace:
    registry = EntityRegistry()
    for index in range(count):
        key = DeviceKey(DeviceType.LIGHT, 1, index, SubType.NONE)
        registry.upsert(DeviceState(key, Platform.LIGHT, {}, True))
    return SimpleNamespace(
        host="wallpad",
        connected=connected,
        registry=registry,
        get_devices_from_platform=registry.all_by_platform,
        async_send_action=AsyncMock(return_value=False),
    )


@pytest.mark.asyncio
async def test_it_gives_up_after_three_lights_in_a_row_stay_silent() -> None:
    # Given five lights on and a wallpad that confirms none of them.
    gateway = gateway_with_lights(5)
    # When the button is pressed, it stops after three tries instead of waiting on all.
    with pytest.raises(HomeAssistantError) as raised:
        await KocomAllLightsOffButton(gateway).async_press()
    assert gateway.async_send_action.await_count == 3
    assert raised.value.translation_key == "lights_off_incomplete"
    assert raised.value.translation_placeholders == {"failed": "5", "total": "5"}


@pytest.mark.asyncio
async def test_without_a_connection_it_says_so_and_sends_nothing() -> None:
    gateway = gateway_with_lights(2, connected=False)
    with pytest.raises(HomeAssistantError) as raised:
        await KocomAllLightsOffButton(gateway).async_press()
    assert raised.value.translation_key == "not_connected"
    gateway.async_send_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_with_no_known_light_pressing_it_does_nothing() -> None:
    gateway = gateway_with_lights(0)
    await KocomAllLightsOffButton(gateway).async_press()
    gateway.async_send_action.assert_not_awaited()
