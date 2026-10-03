"""The gateway's own diagnostic entities: link state and when data last arrived."""

from datetime import timedelta

import pytest
from frames import Emulator, frame, wait_until
from homeassistant.const import EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.kocom_wallpad.const import DOMAIN

CONNECTION = "binary_sensor.kocom_gateway_connection"
LAST_RECEIVED = "sensor.kocom_gateway_last_received"
THERMOSTAT = frame(0x36, 1, 0x00, b"\x11\x00\x16\x00\x15\x00\x00\x00")


@pytest.mark.asyncio
async def test_connection_and_last_received_follow_the_link_and_the_bus(
    hass: HomeAssistant,
) -> None:
    async with Emulator() as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        gateway = hass.data[DOMAIN][entry.entry_id]
        gateway.conn.reconnect_backoff = (0.01, 0.01)
        seen: list[str] = []

        @callback
        def record(event: Event) -> None:
            new_state = event.data["new_state"]
            if event.data["entity_id"] == CONNECTION and new_state is not None:
                seen.append(new_state.state)

        unsubscribe = hass.bus.async_listen("state_changed", record)
        try:
            # Given a link that is up but a bus that has been silent.
            assert hass.states.get(CONNECTION).state == "on"
            assert hass.states.get(LAST_RECEIVED).state == "unknown"
            # When data arrives, the timestamp follows at the next refresh.
            await wallpad.send(THERMOSTAT)
            await wait_until(lambda: gateway.last_receive_time is not None)
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
            await hass.async_block_till_done()
            received = dt_util.parse_datetime(hass.states.get(LAST_RECEIVED).state)
            assert received is not None
            assert abs((dt_util.utcnow() - received).total_seconds()) < 10
            # When the link drops and returns, the connection entity shows both.
            wallpad.writers[-1].close()
            await wait_until(lambda: seen[-2:] == ["off", "on"])
            # Both are diagnostics on a device of their own, with host-suffixed ids.
            registry = er.async_get(hass)
            connection = registry.async_get(CONNECTION)
            last = registry.async_get(LAST_RECEIVED)
            assert connection.unique_id == "hub-connection:127.0.0.1"
            assert last.unique_id == "hub-last_received:127.0.0.1"
            assert connection.entity_category is EntityCategory.DIAGNOSTIC
            assert last.entity_category is EntityCategory.DIAGNOSTIC
            assert connection.device_id == last.device_id
            device = dr.async_get(hass).async_get(connection.device_id)
            assert device is not None
            assert device.name == "KOCOM GATEWAY"
            assert device.identifiers == {(DOMAIN, f"gateway-{entry.entry_id}")}
        finally:
            unsubscribe()
            assert await hass.config_entries.async_unload(entry.entry_id)
