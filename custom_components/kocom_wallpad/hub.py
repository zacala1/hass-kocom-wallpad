"""Gateway-level diagnostic entities for Kocom Wallpad.

They describe the link to the wallpad rather than a wallpad device, so they do not
come from decoded frames and are never restored from saved packets.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .gateway import KocomGateway

# A timestamp that moves with every frame would flood the state machine.
LAST_RECEIVED_REFRESH = timedelta(seconds=60)


class KocomHubEntity(Entity):
    """Base for diagnostic entities that belong to the gateway itself."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, gateway: KocomGateway, key: str) -> None:
        self.gateway = gateway
        # Entity unique ids end with ":<host>"; reconfigure relies on that suffix.
        self._attr_unique_id = f"hub-{key}:{gateway.host}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"gateway-{gateway.entry.entry_id}")},
            manufacturer="KOCOM Co., Ltd",
            model="Smart Wallpad",
            name="KOCOM GATEWAY",
        )


class KocomConnectionSensor(KocomHubEntity, BinarySensorEntity):
    """Whether the link to the wallpad adapter is up."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, gateway: KocomGateway) -> None:
        super().__init__(gateway, "connection")

    @property
    def is_on(self) -> bool:
        return self.gateway.connected

    async def async_added_to_hass(self) -> None:
        @callback
        def _changed(_connected: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.gateway.async_signal_connection_state(), _changed
            )
        )


class KocomLastReceivedSensor(KocomHubEntity, SensorEntity):
    """When the last bytes arrived; a connected but silent bus shows up here."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, gateway: KocomGateway) -> None:
        super().__init__(gateway, "last_received")

    @property
    def native_value(self) -> datetime | None:
        received = self.gateway.last_receive_time
        return None if received is None else received.replace(microsecond=0)

    async def async_added_to_hass(self) -> None:
        @callback
        def _refresh(_now: datetime) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, _refresh, LAST_RECEIVED_REFRESH)
        )
