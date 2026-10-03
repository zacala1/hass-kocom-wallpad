"""Updates for overlapping device keys must remain within their config entry."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import EntityComponent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN


def report(target: int) -> bytes:
    body = b"\x30\xbc\x00\x01\x01\x36\x01\x00\x11\x00"
    body += bytes([target, 0, 21, 0, 0, 0])
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


@pytest_asyncio.fixture
async def peers(
    hass: HomeAssistant,
) -> AsyncGenerator[tuple[str, str, asyncio.StreamWriter]]:
    # Given two real config entries with the same thermostat key and distinct hosts.
    accepted: asyncio.Queue[asyncio.StreamWriter] = asyncio.Queue()
    ended: list[asyncio.Event] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        done = asyncio.Event()
        ended.append(done)
        accepted.put_nowait(writer)
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    entries: list[MockConfigEntry] = []
    writers: list[asyncio.StreamWriter] = []
    changed = asyncio.Event()

    @callback
    def updated(_event: Event) -> None:
        changed.set()

    unsubscribe = hass.bus.async_listen("state_changed", updated)
    try:
        for host in ("127.0.0.1", "localhost"):
            entry = MockConfigEntry(domain=DOMAIN, data={"host": host, "port": port})
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            entries.append(entry)
            writer = await asyncio.wait_for(accepted.get(), 2)
            writers.append(writer)
            changed.clear()
            writer.write(report(22))
            await writer.drain()
            await asyncio.wait_for(changed.wait(), 2)
            await hass.async_block_till_done()
        registry = er.async_get(hass)
        entity_ids = [
            registry.async_get_entity_id("climate", DOMAIN, f"5-1_0-0:{host}")
            for host in ("127.0.0.1", "localhost")
        ]
        first, second = entity_ids
        assert first is not None
        assert second is not None
        assert first != second
        yield first, second, writers[1]
    finally:
        unsubscribe()
        for entry in entries:
            assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        for done in ended:
            await asyncio.wait_for(done.wait(), 2)


@pytest.mark.asyncio
async def test_same_device_key_updates_only_its_entry_and_preserves_identity(
    hass: HomeAssistant,
    peers: tuple[str, str, asyncio.StreamWriter],
) -> None:
    # Given two attached entities with overlapping device keys and stable identities.
    first, second, writer = peers
    component = hass.data["climate"]
    assert isinstance(component, EntityComponent)
    first_entity = component.get_entity(first)
    second_entity = component.get_entity(second)
    assert first_entity is not None
    assert second_entity is not None
    identities = (first_entity.unique_id, second_entity.unique_id)
    device_info = (first_entity.device_info, second_entity.device_info)
    assert identities == ("5-1_0-0:127.0.0.1", "5-1_0-0:localhost")
    assert hass.states.get(first).attributes["temperature"] == 22
    second_updated = asyncio.Event()

    @callback
    def second_changed(event: Event) -> None:
        if event.data["entity_id"] == second:
            state = event.data["new_state"]
            if state is not None and state.attributes.get("temperature") == 27:
                second_updated.set()

    unsubscribe = hass.bus.async_listen("state_changed", second_changed)
    try:
        # When B's peer reports a different value for that identical device key.
        writer.write(report(27))
        await writer.drain()
        await asyncio.wait_for(second_updated.wait(), 2)
        await hass.async_block_till_done()
        # Then only B changes; A's state, availability and both identities persist.
        assert hass.states.get(first).attributes["temperature"] == 22
        assert hass.states.get(second).attributes["temperature"] == 27
        assert hass.states.get(first).state == "heat"
        assert (first_entity.unique_id, second_entity.unique_id) == identities
        assert (first_entity.device_info, second_entity.device_info) == device_info
    finally:
        unsubscribe()
