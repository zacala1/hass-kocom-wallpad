"""Outlets, the door motion sensor, elevator floors and an air conditioner turned off."""

import asyncio

import pytest
from frames import Emulator, controller_with, frame, wait_until
from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.models import DeviceKey

FLOOR = DeviceKey(DeviceType.ELEVATOR, 1, 0, SubType.FLOOR)
DIRECTION = DeviceKey(DeviceType.ELEVATOR, 1, 0, SubType.DIRECTION)
CALL = DeviceKey(DeviceType.ELEVATOR, 1, 0, SubType.NONE)
AIRCON = DeviceKey(DeviceType.AIRCONDITIONER, 1, 0, SubType.NONE)


def elevator(floor_high: int, floor_low: int = 0, direction: int = 0x01) -> bytes:
    payload = bytes([direction, floor_high, floor_low, 0, 0, 0, 0, 0])
    return frame(0x44, 1, 0x00, payload)


@pytest.mark.parametrize(
    ("high", "low", "floor"),
    [
        (0x05, 0x00, "5"),  # a plain number
        (0x0C, 0x00, "12"),  # numbers above nine are still a number
        (0x81, 0x00, "B1"),  # high nibble 8 marks a basement floor
        (0x32, 0x00, "50"),  # the byte is the number, not a character
        (0x31, 0x32, "12"),  # two bytes are two characters of the label
    ],
)
def test_elevator_floor_is_decoded_the_way_the_wallpad_labels_it(
    high: int, low: int, floor: str
) -> None:
    _controller, registry = controller_with(elevator(high, low))
    assert registry.get(FLOOR).state == floor


def test_floor_sensor_appears_only_once_a_floor_has_been_reported() -> None:
    # Given a wallpad that has not reported any floor yet.
    controller, registry = controller_with(elevator(0x00))
    assert registry.get(FLOOR) is None
    # When a floor arrives, the sensor appears, and a later "no floor" is shown.
    controller._dispatch_packet(elevator(0x07))
    assert registry.get(FLOOR).state == "7"
    controller._dispatch_packet(elevator(0x00))
    assert registry.get(FLOOR).state == "unknown"


def test_a_call_signal_reads_as_called_and_marks_the_call_as_pending() -> None:
    # The call signal is the only elevator frame whose packet type is 0xD.
    call = frame(0x44, 1, 0x00, bytes(8), header=b"\x30\xd0")
    _controller, registry = controller_with(call)
    assert registry.get(DIRECTION).state == "called"
    assert registry.get(CALL).state is True


@pytest.mark.parametrize(
    ("payload", "fan", "current", "target"),
    [
        # Powered off while the stored mode, fan and target are still reported.
        (bytes([0x00, 0x02, 0x03, 0, 0x15, 0x16, 0, 0]), "high", 21.0, 22.0),
        (bytes([0x00, 0x00, 0x01, 0, 0x1E, 0x18, 0, 0]), "low", 30.0, 24.0),
    ],
)
def test_an_air_conditioner_that_is_off_keeps_its_other_readings(
    payload: bytes, fan: str, current: float, target: float
) -> None:
    _controller, registry = controller_with(frame(0x39, 1, 0x00, payload))
    state = registry.get(AIRCON).state
    assert state["hvac_mode"] == HVACMode.OFF
    assert (state["fan_mode"], state["current_temp"], state["target_temp"]) == (
        fan,
        current,
        target,
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [(0x00, HVACMode.COOL), (0x01, HVACMode.FAN_ONLY), (0x02, HVACMode.DRY), (0x03, HVACMode.AUTO)],
)
def test_an_air_conditioner_that_is_on_reports_its_mode(
    mode: int, expected: HVACMode
) -> None:
    payload = bytes([0x10, mode, 0x02, 0, 0x15, 0x16, 0, 0])
    _controller, registry = controller_with(frame(0x39, 1, 0x00, payload))
    assert registry.get(AIRCON).state["hvac_mode"] == expected


@pytest.mark.asyncio
async def test_outlets_appear_when_on_and_a_command_keeps_the_other_slots(
    hass: HomeAssistant,
) -> None:
    # Given a wallpad that answers every outlet command with the resulting report.
    def respond(packet: bytes) -> list[bytes]:
        return [frame(0x3B, 1, 0x00, packet[10:18])]

    async with Emulator(respond) as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            # When slots 0 and 2 are reported on and the other six off,
            await wallpad.send(frame(0x3B, 1, 0x00, bytes([0xFF, 0, 0xFF, 0, 0, 0, 0, 0])))
            await wait_until(lambda: len(hass.states.async_all("switch")) == 2)
            await hass.async_block_till_done()
            # then only the two that are on exist, as outlets.
            states = hass.states.async_all("switch")
            assert {s.state for s in states} == {"on"}
            assert {s.attributes["device_class"] for s in states} == {"outlet"}
            registry = er.async_get(hass)
            first = registry.async_get_entity_id("switch", DOMAIN, "4-1_0-0:127.0.0.1")
            assert first is not None
            # When slot 0 is switched off, slot 2 is kept on in the same frame.
            await asyncio.wait_for(
                hass.services.async_call(
                    "switch", "turn_off", {"entity_id": first}, blocking=True
                ),
                10,
            )
            await hass.async_block_till_done()
            assert wallpad.received[-1][10:18] == bytes([0, 0, 0xFF, 0, 0, 0, 0, 0])
            # The slot that went off stays registered; the unused ones never appear.
            assert hass.states.get(first).state == "off"
            assert len(hass.states.async_all("switch")) == 2
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.asyncio
async def test_the_door_motion_sensor_follows_the_wallpad(hass: HomeAssistant) -> None:
    async with Emulator() as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await wallpad.send(frame(0x60, 1, 0x04, bytes(8)))
            await wait_until(lambda: len(hass.states.async_all("binary_sensor")) >= 2)
            motion = next(
                s
                for s in hass.states.async_all("binary_sensor")
                if s.attributes.get("device_class") == "motion"
            )
            assert motion.state == "on"
            # Motion clears when the wallpad says so, and the sensor stays usable.
            await wallpad.send(frame(0x60, 1, 0x00, bytes(8)))
            await wait_until(lambda: hass.states.get(motion.entity_id).state == "off")
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)
