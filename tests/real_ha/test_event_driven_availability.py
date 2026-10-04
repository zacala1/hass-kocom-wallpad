"""Devices that report only on events stay usable after restart and reconnect."""

import asyncio

import pytest
from frames import frame, wait_until
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.gateway import KocomGateway
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState

GAS_ON = frame(0x2C, 0, 0x01, bytes(8))
THERMOSTAT = frame(0x36, 1, 0x00, b"\x11\x00\x16\x00\x15\x00\x00\x00")


@pytest.mark.asyncio
async def test_only_known_event_driven_devices_skip_the_fresh_report_rule(
    hass: HomeAssistant,
) -> None:
    # Given known devices of both kinds and one event-driven device never seen.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    gas = DeviceKey(DeviceType.GASVALVE, 0, 0, SubType.NONE)
    thermostat = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)
    motion = DeviceKey(DeviceType.MOTION, 0, 0, SubType.NONE)
    gateway.registry.upsert(DeviceState(gas, Platform.VALVE, {}, True))
    gateway.registry.upsert(DeviceState(thermostat, Platform.CLIMATE, {}, {}))
    # When the link is down, nothing is available.
    assert not gateway.is_device_available(gas)
    # When it is up without any report on this connection,
    gateway.conn._set_connected(connected=True)
    # then the known event-driven device is available, the polled one is not,
    assert gateway.is_device_available(gas)
    assert not gateway.is_device_available(thermostat)
    # and an event-driven device that was never seen stays unavailable.
    assert not gateway.is_device_available(motion)
    # Losing the link blocks everything again.
    gateway.conn._set_connected(connected=False)
    assert not gateway.is_device_available(gas)


@pytest.mark.asyncio
async def test_restored_gas_valve_is_available_at_startup_but_thermostat_is_not(
    hass: HomeAssistant,
) -> None:
    # Given saved state for a gas valve and a thermostat in the entity registry.
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    gas = registry.async_get_or_create(
        "valve", DOMAIN, "8-0_0-0:127.0.0.1", config_entry=entry, suggested_object_id="gas"
    )
    heating = registry.async_get_or_create(
        "climate", DOMAIN, "5-1_0-0:127.0.0.1", config_entry=entry, suggested_object_id="heat"
    )
    mock_restore_cache_with_extra_data(
        hass,
        [
            (State(gas.entity_id, "on"), {"packet": GAS_ON.hex()}),
            (State(heating.entity_id, "heat"), {"packet": THERMOSTAT.hex()}),
        ],
    )
    finished: list[asyncio.Event] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        done = asyncio.Event()
        finished.append(done)
        try:
            while await reader.read(512):
                continue
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    hass.config_entries.async_update_entry(
        entry,
        data={"host": "127.0.0.1", "port": server.sockets[0].getsockname()[1]},
    )
    try:
        # When the integration starts and the wallpad sends nothing.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        # Then the gas valve shows its saved state; the polled device waits for a report.
        assert hass.states.get(gas.entity_id).state == "open"
        assert hass.states.get(heating.entity_id).state == "unavailable"
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        for done in finished:
            await asyncio.wait_for(done.wait(), 2)


@pytest.mark.asyncio
async def test_gas_valve_comes_back_after_reconnect_without_a_new_report(
    hass: HomeAssistant,
) -> None:
    # Given a gas valve reported on over a live connection.
    accepted: asyncio.Queue[asyncio.StreamWriter] = asyncio.Queue()
    finished: list[asyncio.Event] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        done = asyncio.Event()
        finished.append(done)
        accepted.put_nowait(writer)
        try:
            while await reader.read(512):
                continue
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "127.0.0.1", "port": server.sockets[0].getsockname()[1]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    gateway.conn.reconnect_backoff = (0.01, 0.01)

    seen: list[str] = []

    @callback
    def record(event: Event) -> None:
        new_state = event.data["new_state"]
        if event.data["entity_id"].startswith("valve.") and new_state is not None:
            seen.append(new_state.state)

    unsubscribe = hass.bus.async_listen("state_changed", record)
    try:
        writer = await asyncio.wait_for(accepted.get(), 2)
        writer.write(GAS_ON)
        await writer.drain()
        await wait_until(lambda: seen[-1:] == ["open"])
        # When the link drops and the gateway reconnects,
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(accepted.get(), 2)
        # then the entity goes unavailable and comes back with its last state,
        # although the wallpad sent no new report.
        await wait_until(lambda: seen[-3:] == ["open", "unavailable", "open"])
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        for done in finished:
            await asyncio.wait_for(done.wait(), 2)
