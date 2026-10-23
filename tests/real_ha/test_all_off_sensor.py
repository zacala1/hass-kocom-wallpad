"""The wallpad's all-off signal is a binary sensor: it is received, never sent."""

import pytest
from frames import Emulator, controller_with, frame, wait_until
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.models import DeviceKey

ALL_OFF = DeviceKey(DeviceType.LIGHTCUTOFF, 0, 0, SubType.NONE)
ALL_OFF_UNIQUE_ID = "2-0_0-0:127.0.0.1"


def signal(command: int) -> bytes:
    """The wallpad's broadcast: a light frame to room 0xFF, 0x65 on and 0x66 off."""
    return frame(0x0E, 0xFF, command, bytes(8))


def test_there_is_no_frame_that_sends_the_all_off_signal() -> None:
    # The signal is only ever received, so a command for it must not be encodable.
    controller, _registry = controller_with()
    for action in ("turn_on", "turn_off"):
        with pytest.raises(ValueError, match="Invalid device type"):
            controller.generate_command(ALL_OFF, action)


@pytest.mark.asyncio
async def test_the_signal_shows_up_as_a_sensor_that_follows_the_wallpad(
    hass: HomeAssistant,
) -> None:
    async with Emulator() as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await wallpad.send(signal(0x65))
            registry = er.async_get(hass)
            await wait_until(
                lambda: registry.async_get_entity_id(
                    "binary_sensor", DOMAIN, ALL_OFF_UNIQUE_ID
                )
                is not None
            )
            sensor = registry.async_get_entity_id(
                "binary_sensor", DOMAIN, ALL_OFF_UNIQUE_ID
            )
            # It is a sensor, not a light with a switch that could only fail.
            assert hass.states.async_all("light") == []
            await wait_until(lambda: hass.states.get(sensor).state == "on")
            await wallpad.send(signal(0x66))
            await wait_until(lambda: hass.states.get(sensor).state == "off")
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_the_old_all_off_light_is_replaced_by_the_sensor_on_setup(
    hass: HomeAssistant,
) -> None:
    # Given the all-off light an earlier version saved, and an unrelated light.
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "light", DOMAIN, ALL_OFF_UNIQUE_ID, config_entry=entry, suggested_object_id="all_off"
    )
    room_light = registry.async_get_or_create(
        "light", DOMAIN, "1-1_0-0:127.0.0.1", config_entry=entry, suggested_object_id="hall"
    )
    mock_restore_cache_with_extra_data(
        hass, [(State(old.entity_id, "on"), {"packet": signal(0x65).hex()})]
    )
    async with Emulator() as wallpad:
        hass.config_entries.async_update_entry(
            entry, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await hass.async_block_till_done()
            # Then the saved signal becomes a sensor with its last state, and only
            # the old all-off light is removed.
            sensor = registry.async_get_entity_id(
                "binary_sensor", DOMAIN, ALL_OFF_UNIQUE_ID
            )
            assert sensor is not None
            assert hass.states.get(sensor).state == "on"
            assert registry.async_get(old.entity_id) is None
            assert registry.async_get(room_light.entity_id) is not None
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)
