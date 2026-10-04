"""Commands keep fields they do not change instead of sending zero for them."""

from types import SimpleNamespace

import pytest
from homeassistant.components.climate.const import HVACMode

from custom_components.kocom_wallpad.const import DeviceType, SubType
from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.gateway import EntityRegistry
from custom_components.kocom_wallpad.models import DeviceKey


def report(device_code: int, payload: bytes, room: int = 1) -> bytes:
    """Return a wallpad status report for one device, as the bus carries it."""
    body = b"\x30\xbc\x00\x01\x00" + bytes([device_code, room, 0]) + payload
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


def controller_with(*reports: bytes) -> KocomController:
    """Build a real controller whose registry holds the given reports."""
    registry = EntityRegistry()
    gateway = SimpleNamespace(
        registry=registry,
        on_device_state=lambda device: registry.upsert(device),
        _force_register_uid=None,
    )
    controller = KocomController(gateway)
    for packet in reports:
        controller._dispatch_packet(packet)
    return controller


def command(
    controller: KocomController, key: DeviceKey, action: str, **kwargs: object
) -> bytes:
    packet, _expectation, _timeout = controller.generate_command(key, action, **kwargs)
    return packet[10:18]


AIRCON = DeviceKey(DeviceType.AIRCONDITIONER, 1, 0, SubType.NONE)
VENT = DeviceKey(DeviceType.VENTILATION, 1, 0, SubType.NONE)
THERMO = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)

# Dry mode, fan high, current 21, target 22.
AIRCON_REPORT = report(0x39, b"\x10\x02\x03\x00\x15\x16\x00\x00")
# On, bypass preset, speed 0x80.
VENT_REPORT = report(0x48, b"\x11\x03\x80\x00\x00\x00\x00\x00")
# Heating on, away preset, target 22, current 21.
THERMO_REPORT = report(0x36, b"\x11\x01\x16\x00\x15\x00\x00\x00")


@pytest.mark.parametrize(
    ("action", "kwargs", "expected"),
    [
        ("set_fan", {"fan_mode": "low"}, b"\x10\x02\x01\x00\x00\x16\x00\x00"),
        ("set_temperature", {"target_temp": 24.0}, b"\x10\x02\x03\x00\x00\x18\x00\x00"),
        (
            "set_hvac",
            {"hvac_mode": HVACMode.COOL},
            b"\x10\x00\x03\x00\x00\x16\x00\x00",
        ),
        ("set_hvac", {"hvac_mode": HVACMode.OFF}, b"\x00\x02\x03\x00\x00\x16\x00\x00"),
    ],
)
def test_aircon_keeps_unchanged_mode_fan_and_target(
    action: str, kwargs: dict[str, object], expected: bytes
) -> None:
    # Given an air conditioner reporting dry mode, high fan and target 22.
    controller = controller_with(AIRCON_REPORT)
    # When one control changes, then the others are sent as last reported.
    assert command(controller, AIRCON, action, **kwargs) == expected


@pytest.mark.parametrize(
    ("action", "kwargs", "expected"),
    [
        ("set_preset", {"preset_mode": "auto"}, b"\x11\x02\x80\x00\x00\x00\x00\x00"),
        ("set_percentage", {"speed": 0x40}, b"\x11\x03\x40\x00\x00\x00\x00\x00"),
        ("set_percentage", {"speed": 0}, b"\x00\x03\x00\x00\x00\x00\x00\x00"),
        (
            "set_percentage",
            {"speed": 0xC0, "preset_mode": "auto"},
            b"\x11\x02\xc0\x00\x00\x00\x00\x00",
        ),
        # Plain on/off keeps its existing encoding.
        ("turn_on", {}, b"\x11\x00\x00\x00\x00\x00\x00\x00"),
        ("turn_off", {}, b"\x00\x00\x00\x00\x00\x00\x00\x00"),
    ],
)
def test_ventilation_keeps_unchanged_speed_and_preset(
    action: str, kwargs: dict[str, object], expected: bytes
) -> None:
    # Given a ventilation unit in bypass mode at speed 0x80.
    controller = controller_with(VENT_REPORT)
    # When preset or speed changes, then the other one is not reset.
    assert command(controller, VENT, action, **kwargs) == expected


@pytest.mark.parametrize(
    ("action", "kwargs", "expected"),
    [
        (
            "set_temperature",
            {"target_temp": 25.0},
            b"\x11\x01\x19\x00\x00\x00\x00\x00",
        ),
        ("set_hvac", {"hvac_mode": HVACMode.OFF}, b"\x00\x00\x16\x00\x00\x00\x00\x00"),
        (
            "set_preset",
            {"preset_mode": "none"},
            b"\x11\x00\x16\x00\x00\x00\x00\x00",
        ),
    ],
)
def test_thermostat_keeps_unchanged_preset_and_target(
    action: str, kwargs: dict[str, object], expected: bytes
) -> None:
    # Given a thermostat in away preset with target 22.
    controller = controller_with(THERMO_REPORT)
    # When one field changes, then the rest is not sent as zero.
    assert command(controller, THERMO, action, **kwargs) == expected


@pytest.mark.parametrize(
    ("key", "action", "kwargs", "expected"),
    [
        (AIRCON, "set_fan", {"fan_mode": "high"}, b"\x10\x00\x03\x00\x00\x00\x00\x00"),
        (VENT, "set_preset", {"preset_mode": "auto"}, b"\x11\x02\x00\x00\x00\x00\x00\x00"),
        (
            THERMO,
            "set_temperature",
            {"target_temp": 22.0},
            b"\x11\x00\x16\x00\x00\x00\x00\x00",
        ),
    ],
)
def test_unknown_device_keeps_previous_encoding(
    key: DeviceKey, action: str, kwargs: dict[str, object], expected: bytes
) -> None:
    # Given no report for the device yet.
    controller = controller_with()
    # When a command is built, then unspecified fields stay zero as before.
    assert command(controller, key, action, **kwargs) == expected
