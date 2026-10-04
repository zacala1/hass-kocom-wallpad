"""The all-off signal has its own identity, and fan speeds never break state writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError

from custom_components.kocom_wallpad.const import DeviceType, SubType
from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.fan import KocomFan
from custom_components.kocom_wallpad.gateway import EntityRegistry
from custom_components.kocom_wallpad.light import KocomLight
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState


def frame(device_code: int, room: int, command: int, payload: bytes) -> bytes:
    body = b"\x30\xbc\x00\x01\x00" + bytes([device_code, room, command]) + payload
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


def controller_with_registry() -> tuple[KocomController, EntityRegistry]:
    registry = EntityRegistry()
    gateway = SimpleNamespace(
        registry=registry,
        on_device_state=lambda device: registry.upsert(device),
        _force_register_uid=None,
    )
    return KocomController(gateway), registry


ROOM0_LIGHT0 = DeviceKey(DeviceType.LIGHT, 0, 0, SubType.NONE)
ALL_OFF = DeviceKey(DeviceType.LIGHTCUTOFF, 0, 0, SubType.NONE)


@pytest.mark.parametrize(("command", "state"), [(0x65, True), (0x66, False)])
def test_all_off_signal_does_not_touch_room_zero_light(
    command: int, state: bool
) -> None:
    # Given room 0 light 0 is on.
    controller, registry = controller_with_registry()
    controller._dispatch_packet(frame(0x0E, 0, 0x00, b"\xff" + bytes(7)))
    assert registry.get(ROOM0_LIGHT0).state is True
    # When the wallpad broadcasts the all-off signal (destination room 0xFF).
    controller._dispatch_packet(frame(0x0E, 0xFF, command, bytes(8)))
    # Then it is a separate device and the light keeps its own state.
    assert registry.get(ROOM0_LIGHT0).state is True
    cutoff = registry.get(ALL_OFF)
    assert cutoff is not None
    assert cutoff.platform == Platform.LIGHT
    assert cutoff.state is state
    assert cutoff.key.unique_id != ROOM0_LIGHT0.unique_id


def test_all_off_signal_does_not_invent_a_room_zero_light() -> None:
    # Given a wallpad that has never reported room 0 light 0.
    controller, registry = controller_with_registry()
    # When only the all-off signal arrives.
    controller._dispatch_packet(frame(0x0E, 0xFF, 0x66, bytes(8)))
    # Then no regular light appears.
    assert registry.get(ROOM0_LIGHT0) is None
    assert registry.get(ALL_OFF) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["async_turn_on", "async_turn_off"])
async def test_all_off_light_refuses_control_without_sending(action: str) -> None:
    # Given the all-off state entity and a regular light.
    gateway = SimpleNamespace(host="wallpad", async_send_action=AsyncMock(return_value=True))
    cutoff = KocomLight(gateway, DeviceState(ALL_OFF, Platform.LIGHT, {}, True))
    regular = KocomLight(gateway, DeviceState(ROOM0_LIGHT0, Platform.LIGHT, {}, True))
    # When control is requested, the all-off entity fails clearly and sends nothing.
    with pytest.raises(HomeAssistantError, match="all-off"):
        await getattr(cutoff, action)()
    gateway.async_send_action.assert_not_awaited()
    # The regular light still sends its command.
    await getattr(regular, action)()
    gateway.async_send_action.assert_awaited_once()


FAN_KEY = DeviceKey(DeviceType.VENTILATION, 0, 0, SubType.NONE)


@pytest.mark.parametrize(
    ("on", "speed", "expected"),
    [
        (True, 0x40, 33),
        (True, 0x80, 66),
        (True, 0xC0, 100),
        (True, 0x00, 0),
        (False, 0x80, 0),
        # A speed code this integration does not know must not raise.
        (True, 0x01, None),
        (True, 0x60, None),
    ],
)
def test_fan_percentage_maps_known_speeds_and_tolerates_unknown(
    *, on: bool, speed: int, expected: int | None
) -> None:
    device = DeviceState(
        FAN_KEY,
        Platform.FAN,
        {"feature_preset": False, "speed_list": [0x40, 0x80, 0xC0], "preset_modes": []},
        {"state": on, "preset_mode": "ventilation", "speed": speed},
    )
    entity = KocomFan(SimpleNamespace(host="wallpad"), device)
    assert entity.percentage == expected
