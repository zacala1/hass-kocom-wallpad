"""Registered sensors follow zero readings; restored storage merges, not replaces."""

from types import SimpleNamespace

import pytest
from frames import controller_with, frame
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.kocom_wallpad.climate import KocomClimate
from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.gateway import KocomGateway
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState

HOT = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.HOTTEMP)
HEAT = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.HEATTEMP)
CO2 = DeviceKey(DeviceType.VENTILATION, 1, 0, SubType.CO2)


def thermostat(hot: int, heat: int) -> bytes:
    return frame(0x36, 1, 0x00, bytes([0x11, 0x00, 0x16, hot, 0x15, heat, 0x00, 0x00]))


def ventilation(co2_hundreds: int, co2_units: int) -> bytes:
    payload = bytes([0x11, 0x01, 0x40, 0x00, co2_hundreds, co2_units, 0x00, 0x00])
    return frame(0x48, 1, 0x00, payload)


def test_thermostat_water_temperatures_follow_a_reading_that_drops_to_zero() -> None:
    # Given sensors that were discovered with real readings.
    controller, registry = controller_with(thermostat(40, 45))
    assert registry.get(HOT).state == 40
    assert registry.get(HEAT).state == 45
    # When the wallpad reports 0 for both.
    controller._dispatch_packet(thermostat(0, 0))
    # Then the sensors show 0 instead of holding the old value.
    assert registry.get(HOT).state == 0
    assert registry.get(HEAT).state == 0


def test_thermostat_water_sensors_are_not_invented_from_zero() -> None:
    _controller, registry = controller_with(thermostat(0, 0))
    assert registry.get(HOT) is None
    assert registry.get(HEAT) is None


def test_ventilation_co2_follows_a_reading_that_drops_to_zero() -> None:
    controller, registry = controller_with(ventilation(4, 50))
    assert registry.get(CO2).state == 450
    controller._dispatch_packet(ventilation(0, 0))
    assert registry.get(CO2).state == 0
    _controller, fresh = controller_with(ventilation(0, 0))
    assert fresh.get(CO2) is None


@pytest.mark.parametrize("key_type", [DeviceType.THERMOSTAT, DeviceType.AIRCONDITIONER])
@pytest.mark.parametrize(
    ("current", "target", "expected_current", "expected_target"),
    [(0.0, 0.0, None, None), (21.0, 22.0, 21.0, 22.0)],
)
def test_climate_reports_unknown_instead_of_zero_degrees(
    key_type: DeviceType,
    current: float,
    target: float,
    expected_current: float | None,
    expected_target: float | None,
) -> None:
    device = DeviceState(
        DeviceKey(key_type, 1, 0, SubType.NONE),
        Platform.CLIMATE,
        {},
        {"current_temp": current, "target_temp": target},
    )
    entity = KocomClimate(SimpleNamespace(host="wallpad"), device)
    assert entity.current_temperature == expected_current
    assert entity.target_temperature == expected_target


def test_merge_unites_lists_ors_flags_and_takes_latest_scalar() -> None:
    controller = KocomController(SimpleNamespace())
    controller.merge_device_storage(
        {"ventil_modes": ["ventilation", "auto"], "ventil_feature": False, "step": 1.0}
    )
    controller.merge_device_storage(
        {"ventil_modes": ["ventilation", "bypass"], "ventil_feature": True, "step": 0.5}
    )
    controller.merge_device_storage({"ventil_feature": False})
    assert controller._device_storage == {
        "ventil_modes": ["ventilation", "auto", "bypass"],
        "ventil_feature": True,
        "step": 0.5,
    }


@pytest.mark.asyncio
async def test_restore_merges_every_entity_snapshot_without_aliasing(
    hass: HomeAssistant,
) -> None:
    # Given two entities whose saved snapshots learned different things.
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    first = registry.async_get_or_create(
        "light", DOMAIN, "1-1_0-0:wallpad", config_entry=entry, suggested_object_id="a"
    )
    second = registry.async_get_or_create(
        "light", DOMAIN, "1-2_0-0:wallpad", config_entry=entry, suggested_object_id="b"
    )
    lit = b"\xff" + bytes(7)
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(first.entity_id, "on"),
                {
                    "packet": frame(0x0E, 1, 0x00, lit).hex(),
                    "device_storage": {"ventil_modes": ["ventilation", "auto"]},
                },
            ),
            (
                State(second.entity_id, "on"),
                {
                    "packet": frame(0x0E, 2, 0x00, lit).hex(),
                    "device_storage": {
                        "ventil_modes": ["ventilation", "bypass"],
                        "ventil_feature": True,
                    },
                },
            ),
        ],
    )
    gateway = KocomGateway(hass, entry, "wallpad", 8899)
    # When the gateway restores both.
    await gateway.async_get_entity_registry()
    # Then nothing learned by either entity is lost.
    storage = gateway.controller._device_storage
    assert storage["ventil_modes"] == ["ventilation", "auto", "bypass"]
    assert storage["ventil_feature"] is True
    # And changing live storage does not rewrite the saved snapshot.
    storage["ventil_modes"].append("sleep")
    saved = restore_state.async_get(hass).last_states[first.entity_id]
    assert saved.extra_data.as_dict()["device_storage"]["ventil_modes"] == [
        "ventilation",
        "auto",
    ]
