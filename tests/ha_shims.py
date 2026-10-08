"""Deterministic regression tests for the Kocom control path.

These offline tests use narrow module shims for deterministic protocol checks.
The development type checker resolves the real, locked Home Assistant dependency.
"""

from __future__ import annotations

import sys
import types
from enum import Enum, IntFlag


def _module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


def _set_attributes(module: types.ModuleType, **attributes: object) -> None:
    """Populate only the declared fixture surface on dynamically created modules."""
    for name, value in attributes.items():
        setattr(module, name, value)


def _install_homeassistant_shims() -> None:
    if "homeassistant" in sys.modules:
        return
    homeassistant = _module("homeassistant")
    const = _module("homeassistant.const")

    class Platform(Enum):
        LIGHT = "light"
        SWITCH = "switch"
        CLIMATE = "climate"
        FAN = "fan"
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        VALVE = "valve"
        BUTTON = "button"

    _set_attributes(const, Platform=Platform)
    _set_attributes(const, UnitOfTemperature=types.SimpleNamespace(CELSIUS="°C"))
    _set_attributes(const, ATTR_TEMPERATURE="temperature")
    _set_attributes(const, CONF_HOST="host")
    _set_attributes(const, CONF_PORT="port")
    _set_attributes(const, EVENT_HOMEASSISTANT_STOP="stop")
    _set_attributes(homeassistant, const=const)

    core = _module("homeassistant.core")
    _set_attributes(core, HomeAssistant=object)
    _set_attributes(core, Event=object)
    _set_attributes(core, callback=lambda function: function)
    config_entries = _module("homeassistant.config_entries")
    _set_attributes(config_entries, ConfigEntry=object)

    components = _module("homeassistant.components")
    climate = _module("homeassistant.components.climate")
    climate_const = _module("homeassistant.components.climate.const")
    _set_attributes(climate_const, PRESET_NONE="none")
    _set_attributes(climate_const, PRESET_AWAY="away")
    _set_attributes(climate_const, FAN_LOW="low")
    _set_attributes(climate_const, FAN_MEDIUM="medium")
    _set_attributes(climate_const, FAN_HIGH="high")
    _set_attributes(climate_const, FAN_AUTO="auto")
    _set_attributes(
        climate_const,
        HVACMode=types.SimpleNamespace(
            HEAT="heat",
            OFF="off",
            COOL="cool",
            FAN_ONLY="fan_only",
            DRY="dry",
            AUTO="auto",
        ),
    )
    _set_attributes(
        climate_const,
        HVACAction=types.SimpleNamespace(OFF="off", HEATING="heating", IDLE="idle"),
    )
    _set_attributes(
        climate_const,
        ClimateEntityFeature=types.SimpleNamespace(
            TARGET_TEMPERATURE=1, TURN_OFF=2, TURN_ON=4, FAN_MODE=8, PRESET_MODE=16
        ),
    )
    _set_attributes(climate, HVACMode=vars(climate_const)["HVACMode"])
    _set_attributes(climate, ClimateEntity=object)

    class _EntityDescription:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    _set_attributes(climate, ClimateEntityDescription=_EntityDescription)
    _set_attributes(components, climate=climate)
    light = _module("homeassistant.components.light")
    light_const = _module("homeassistant.components.light.const")
    _set_attributes(light, LightEntityDescription=_EntityDescription)
    _set_attributes(light, LightEntity=object)
    _set_attributes(light, ColorMode=types.SimpleNamespace(ONOFF="onoff"))
    _set_attributes(light_const, ColorMode=vars(light)["ColorMode"])
    _set_attributes(components, light=light)
    for package, attr, value in (
        (
            "sensor",
            "SensorDeviceClass",
            types.SimpleNamespace(
                TEMPERATURE="temperature",
                CO2="co2",
                PM10="pm10",
                PM25="pm25",
                VOLATILE_ORGANIC_COMPOUNDS="volatile_organic_compounds",
                HUMIDITY="humidity",
            ),
        ),
        (
            "binary_sensor",
            "BinarySensorDeviceClass",
            types.SimpleNamespace(PROBLEM="problem", MOTION="motion"),
        ),
        ("switch", "SwitchDeviceClass", types.SimpleNamespace(OUTLET="outlet")),
    ):
        module = _module(f"homeassistant.components.{package}")
        setattr(module, attr, value)
        if package == "switch":
            _set_attributes(module, SwitchEntity=object)
        setattr(
            module,
            f"{package.title().replace('_', '')}EntityDescription",
            _EntityDescription,
        )
        setattr(components, package, module)

    button = _module("homeassistant.components.button")
    _set_attributes(button, ButtonEntityDescription=_EntityDescription)
    _set_attributes(components, button=button)

    valve = _module("homeassistant.components.valve")
    _set_attributes(valve, ValveEntityDescription=_EntityDescription)
    _set_attributes(components, valve=valve)

    fan = _module("homeassistant.components.fan")
    _set_attributes(fan, FanEntityDescription=_EntityDescription)
    _set_attributes(fan, FanEntity=object)

    class FanEntityFeature(IntFlag):
        SET_SPEED = 1
        TURN_OFF = 2
        TURN_ON = 4
        PRESET_MODE = 8

    _set_attributes(fan, FanEntityFeature=FanEntityFeature)
    _set_attributes(components, fan=fan)

    helpers = _module("homeassistant.helpers")
    entity = _module("homeassistant.helpers.entity")

    class _RestoreEntity:
        def __init__(self):
            pass

        @property
        def unique_id(self):
            return getattr(self, "_attr_unique_id", None)

        def async_write_ha_state(self):
            pass

    class _DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    _set_attributes(entity, DeviceInfo=_DeviceInfo)
    entity_registry = _module("homeassistant.helpers.entity_registry")
    _set_attributes(entity_registry, async_get=lambda hass: None)
    _set_attributes(
        entity_registry, async_entries_for_config_entry=lambda registry, entry_id: []
    )
    device_registry = _module("homeassistant.helpers.device_registry")
    _set_attributes(device_registry, DeviceInfo=_DeviceInfo)
    _set_attributes(device_registry, async_get=lambda hass: None)
    restore_state = _module("homeassistant.helpers.restore_state")
    _set_attributes(
        restore_state, async_get=lambda hass: types.SimpleNamespace(last_states={})
    )
    _set_attributes(restore_state, RestoreEntity=_RestoreEntity)
    _set_attributes(restore_state, RestoredExtraData=lambda value: value)
    _set_attributes(restore_state, StoredState=object)
    dispatcher = _module("homeassistant.helpers.dispatcher")
    _set_attributes(dispatcher, async_dispatcher_send=lambda *args, **kwargs: None)
    _set_attributes(
        dispatcher, async_dispatcher_connect=lambda *_args, **_kwargs: lambda: None
    )
    entity_platform = _module("homeassistant.helpers.entity_platform")
    _set_attributes(entity_platform, AddEntitiesCallback=object)
    exceptions = _module("homeassistant.exceptions")
    _set_attributes(
        exceptions, HomeAssistantError=type("HomeAssistantError", (Exception,), {})
    )
    _set_attributes(helpers, entity=entity)
    _set_attributes(helpers, entity_registry=entity_registry)
    _set_attributes(helpers, device_registry=device_registry)
    _set_attributes(helpers, restore_state=restore_state)
    _set_attributes(helpers, dispatcher=dispatcher)
    _set_attributes(_module("serialx"), open_serial_connection=None)
    util = _module("homeassistant.util")
    percentage = _module("homeassistant.util.percentage")
    _set_attributes(
        percentage,
        ordered_list_item_to_percentage=lambda values, value: int(
            values.index(value) * 100 / max(len(values) - 1, 1)
        ),
    )
    _set_attributes(
        percentage,
        percentage_to_ordered_list_item=lambda values, value: values[
            round((len(values) - 1) * value / 100)
        ],
    )
    _set_attributes(util, percentage=percentage)


_install_homeassistant_shims()
_set_attributes(_module("serial_asyncio"), open_serial_connection=None)
_set_attributes(
    sys.modules["homeassistant.exceptions"],
    ConfigEntryNotReady=type("ConfigEntryNotReady", (Exception,), {}),
)
