"""Long-term statistics, diagnostic categories and the brand images."""

import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory, Platform

import custom_components.kocom_wallpad as kocom_wallpad
from custom_components.kocom_wallpad.binary_sensor import KocomBinarySensor
from custom_components.kocom_wallpad.const import DeviceType, SubType
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState
from custom_components.kocom_wallpad.sensor import KocomSensor

GATEWAY = SimpleNamespace(host="wallpad")


@pytest.mark.parametrize(
    "device_class",
    [
        SensorDeviceClass.TEMPERATURE,
        SensorDeviceClass.HUMIDITY,
        SensorDeviceClass.CO2,
        SensorDeviceClass.PM10,
        SensorDeviceClass.PM25,
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
    ],
)
def test_numeric_readings_record_long_term_statistics(
    device_class: SensorDeviceClass,
) -> None:
    key = DeviceKey(DeviceType.AIRQUALITY, 1, 0, SubType.TEMP)
    sensor = KocomSensor(
        GATEWAY, DeviceState(key, Platform.SENSOR, {"device_class": device_class}, 21)
    )
    assert sensor.state_class is SensorStateClass.MEASUREMENT


def test_text_sensors_have_no_state_class() -> None:
    key = DeviceKey(DeviceType.ELEVATOR, 1, 0, SubType.FLOOR)
    sensor = KocomSensor(GATEWAY, DeviceState(key, Platform.SENSOR, {}, "B1"))
    assert sensor.state_class is None


@pytest.mark.parametrize(
    ("device_type", "sub_type", "category"),
    [
        (DeviceType.THERMOSTAT, SubType.ERRCODE, EntityCategory.DIAGNOSTIC),
        (DeviceType.VENTILATION, SubType.ERRCODE, EntityCategory.DIAGNOSTIC),
        (DeviceType.MOTION, SubType.NONE, None),
    ],
)
def test_only_error_codes_are_diagnostic_binary_sensors(
    device_type: DeviceType, sub_type: SubType, category: EntityCategory | None
) -> None:
    key = DeviceKey(device_type, 1, 0, sub_type)
    attribute = {"device_class": BinarySensorDeviceClass.PROBLEM}
    sensor = KocomBinarySensor(
        GATEWAY, DeviceState(key, Platform.BINARY_SENSOR, attribute, False)
    )
    assert sensor.entity_category is category


@pytest.mark.parametrize(("name", "size"), [("icon.png", 256), ("icon@2x.png", 512)])
def test_brand_images_are_square_rgba_pngs(name: str, size: int) -> None:
    # The package may be the repository tree or an extracted release archive.
    data = (Path(str(kocom_wallpad.__file__)).parent / "brand" / name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, depth, color_type = struct.unpack(">IIBB", data[16:26])
    assert (width, height, depth, color_type) == (size, size, 8, 6)
