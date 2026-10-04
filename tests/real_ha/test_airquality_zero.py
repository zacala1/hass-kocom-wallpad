"""Air-quality zeros preserve discovered sensors without inventing capabilities."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.restore_state import RestoredExtraData, StoredState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.gateway import KocomGateway
from custom_components.kocom_wallpad.models import DeviceKey


def report(command: int, payload: bytes, room: int = 1) -> bytes:
    body = b"\x30\xbc\x00\x01\x01\x98" + bytes([room, command]) + payload
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


@dataclass(frozen=True, slots=True)
class Wallpad:
    gateway: KocomGateway
    writer: asyncio.StreamWriter
    processed: asyncio.Event

    async def send(self, packet: bytes) -> None:
        self.processed.clear()
        self.writer.write(packet)
        await self.writer.drain()
        await asyncio.wait_for(self.processed.wait(), 2)


@pytest_asyncio.fixture
async def wallpad(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[Wallpad]:
    accepted: asyncio.Queue[asyncio.StreamWriter] = asyncio.Queue()
    done = asyncio.Event()
    processed = asyncio.Event()

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.put_nowait(writer)
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "127.0.0.1",
            "port": server.sockets[0].getsockname()[1],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    dispatch = gateway.controller._dispatch_packet

    def dispatched(packet: bytes) -> None:
        dispatch(packet)
        processed.set()

    monkeypatch.setattr(gateway.controller, "_dispatch_packet", dispatched)
    try:
        writer = await asyncio.wait_for(accepted.get(), 2)
        yield Wallpad(gateway, writer, processed)
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(done.wait(), 2)


def device_sensors(hass: HomeAssistant) -> list[State]:
    """Wallpad device sensors; the gateway's own diagnostic sensor is not one."""
    return [
        state
        for state in hass.states.async_all("sensor")
        if not state.entity_id.endswith("last_received")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [0x00, 0x3A])
async def test_existing_airquality_sensors_publish_zero(
    hass: HomeAssistant,
    wallpad: Wallpad,
    command: int,
) -> None:
    # Given three sensors discovered from positive PM10, PM25 and VOC values.
    await wallpad.send(report(command, b"\x08\x05\x00\x00\x00\x03\x00\x00"))
    await hass.async_block_till_done()
    sensors = device_sensors(hass)
    assert len(sensors) == 3
    identities = {
        state.entity_id: er.async_get(hass).async_get(state.entity_id).unique_id
        for state in sensors
    }
    # When a later packet reports all zeros, followed by zeros in another room.
    await wallpad.send(report(command, bytes(8)))
    await wallpad.send(report(command, bytes(8), room=2))
    await hass.async_block_till_done()
    # Then existing sensors update to zero and unsupported subtypes/rooms stay absent.
    states = device_sensors(hass)
    assert len(states) == 3
    assert {state.state for state in states} == {"0"}
    assert {
        state.entity_id: er.async_get(hass).async_get(state.entity_id).unique_id
        for state in states
    } == identities


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [0x00, 0x3A])
async def test_first_all_zero_airquality_packet_discovers_no_sensors(
    hass: HomeAssistant,
    wallpad: Wallpad,
    command: int,
) -> None:
    # Given a new entry without any known air-quality capability.
    assert not wallpad.gateway.get_devices_from_platform(Platform.SENSOR)
    # When its first actual TCP packet contains only zeros.
    await wallpad.send(report(command, bytes(8)))
    await hass.async_block_till_done()
    # Then no unsupported zero-only sensor is created.
    assert device_sensors(hass) == []
    assert wallpad.gateway.get_devices_from_platform(Platform.SENSOR) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [0x00, 0x3A])
async def test_restore_zero_packet_recreates_only_previously_registered_subtype(
    hass: HomeAssistant,
    wallpad: Wallpad,
    command: int,
) -> None:
    # Given the persisted registry and zero packet for one PM10 entity after restart.
    key = DeviceKey(DeviceType.AIRQUALITY, 1, 0, SubType.PM10)
    entry = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"{key.unique_id}:127.0.0.1",
        config_entry=wallpad.gateway.entry,
    )
    restore_state.async_get(hass).last_states[entry.entity_id] = StoredState(
        State(entry.entity_id, "0"),
        RestoredExtraData(
            {"packet": report(command, bytes(8)).hex(), "device_storage": {}}
        ),
        datetime.now(UTC),
    )
    # When the integration runs its real config-entry restoration path.
    await wallpad.gateway.async_get_entity_registry()
    await hass.async_block_till_done()
    # Then only that known subtype is recreated, still unavailable until fresh traffic.
    known = wallpad.gateway.get_devices_from_platform(Platform.SENSOR)
    assert len(known) == 1
    assert known[0].key == key
    assert known[0].state == 0
    assert hass.states.get(entry.entity_id).state == "unavailable"
    await wallpad.send(report(command, bytes(8)))
    await hass.async_block_till_done()
    assert hass.states.get(entry.entity_id).state == "0"
    assert len(device_sensors(hass)) == 1
