"""Connection loss and fresh per-device recovery through real HA and TCP."""

import asyncio
import errno
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN
from custom_components.kocom_wallpad.gateway import KocomGateway


def report(room: int) -> bytes:
    body = b"\x30\xbc\x00\x01\x01\x36" + bytes([room, 0])
    body += b"\x11\x00\x16\x00\x15\x00\x00\x00"
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


@dataclass(frozen=True, slots=True)
class Wallpad:
    gateway: KocomGateway
    accepted: asyncio.Queue[asyncio.StreamWriter]
    writer: asyncio.StreamWriter
    entities: tuple[str, str]


@pytest_asyncio.fixture
async def wallpad(hass: HomeAssistant) -> AsyncGenerator[Wallpad]:
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
    discovered = asyncio.Event()

    @callback
    def changed(_event: Event) -> None:
        if len(hass.states.async_all("climate")) == 2:
            discovered.set()

    unsubscribe = hass.bus.async_listen("state_changed", changed)
    assert await hass.config_entries.async_setup(entry.entry_id)
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    gateway.conn.reconnect_backoff = (0.01, 0.01)
    try:
        writer = await asyncio.wait_for(accepted.get(), 2)
        writer.write(report(1) + report(2))
        await writer.drain()
        await asyncio.wait_for(discovered.wait(), 2)
        await hass.async_block_till_done()
        entities = tuple(
            sorted(state.entity_id for state in hass.states.async_all("climate"))
        )
        yield Wallpad(gateway, accepted, writer, (entities[0], entities[1]))
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        for done in finished:
            await asyncio.wait_for(done.wait(), 2)


def state_event(
    hass: HomeAssistant,
    gateway: KocomGateway,
    entity: str,
    expected: str,
) -> asyncio.Event:
    """Subscribe on the HA event loop before triggering a state transition."""
    reached = asyncio.Event()

    @callback
    def changed(event: Event) -> None:
        if event.data["entity_id"] == entity:
            state = event.data["new_state"]
            if state is not None and state.state == expected:
                reached.set()

    gateway.entry.async_on_unload(hass.bus.async_listen("state_changed", changed))
    return reached


@pytest.mark.asyncio
async def test_eof_requires_fresh_packet_for_each_device_even_when_unchanged(
    hass: HomeAssistant,
    wallpad: Wallpad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given two discovered entities with stable registry identities.
    first, second = wallpad.entities
    identities = [
        er.async_get(hass).async_get(entity).unique_id for entity in wallpad.entities
    ]
    unavailable = state_event(hass, wallpad.gateway, first, "unavailable")
    reconnected = asyncio.Event()
    connect = wallpad.gateway.conn._connect_once

    async def reconnect_once() -> None:
        await connect()
        reconnected.set()

    monkeypatch.setattr(wallpad.gateway.conn, "_connect_once", reconnect_once)
    # When TCP EOF is followed by a reconnect with no device reports.
    wallpad.writer.close()
    await wallpad.writer.wait_closed()
    await asyncio.wait_for(unavailable.wait(), 1)
    writer = await asyncio.wait_for(wallpad.accepted.get(), 2)
    await asyncio.wait_for(reconnected.wait(), 2)
    await hass.async_block_till_done()
    assert hass.states.get(first).state == "unavailable"
    assert hass.states.get(second).state == "unavailable"
    wallpad.gateway._restore_mode = True
    try:
        wallpad.gateway.controller.feed(report(1) + report(2))
    finally:
        wallpad.gateway._restore_mode = False
    await hass.async_block_till_done()
    assert hass.states.get(first).state == "unavailable"
    assert hass.states.get(second).state == "unavailable"
    # Then one unchanged device report restores only that device.
    recovered = state_event(hass, wallpad.gateway, first, "heat")
    writer.write(report(1))
    await writer.drain()
    await asyncio.wait_for(recovered.wait(), 1)
    assert hass.states.get(second).state == "unavailable"
    recovered_second = state_event(hass, wallpad.gateway, second, "heat")
    writer.write(report(2))
    await writer.drain()
    await asyncio.wait_for(recovered_second.wait(), 1)
    assert [
        er.async_get(hass).async_get(entity).unique_id for entity in wallpad.entities
    ] == identities


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["write", "drain_cancel", "read"])
async def test_entities_unavailable_when_transport_fails(
    hass: HomeAssistant,
    wallpad: Wallpad,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    # Given discovered entities and a physical transport seam that fails.
    unavailable = state_event(hass, wallpad.gateway, wallpad.entities[0], "unavailable")
    writer = wallpad.gateway.conn._writer
    assert writer is not None

    def fail(_packet: bytes) -> None:
        raise OSError(errno.EPIPE, "writer failed")

    async def read_fail(_count: int) -> bytes:
        raise OSError(errno.ECONNRESET, "reader failed")

    # When the write, drain or reader fails.
    match failure:
        case "write":
            monkeypatch.setattr(writer, "write", fail)
            with pytest.raises(OSError, match="writer failed"):
                await wallpad.gateway.conn.send(b"command")
        case "drain_cancel":
            entered = asyncio.Event()

            async def stall() -> None:
                entered.set()
                await asyncio.Event().wait()

            monkeypatch.setattr(writer, "drain", stall)
            task = asyncio.create_task(wallpad.gateway.conn.send(b"command"))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        case "read":
            reader = wallpad.gateway.conn._reader
            assert reader is not None
            monkeypatch.setattr(reader, "read", read_fail)
    # Then all entities become unavailable without waiting for recovery.
    await asyncio.wait_for(unavailable.wait(), 1)
    assert all(
        hass.states.get(entity).state == "unavailable" for entity in wallpad.entities
    )


@pytest.mark.asyncio
async def test_connection_notifications_are_entry_scoped(
    hass: HomeAssistant,
    wallpad: Wallpad,
) -> None:
    # Given a subscriber on one entry and an independent gateway on another.
    notified = asyncio.Event()
    other = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "other", 8899)

    @callback
    def changed(*_connected: bool) -> None:
        notified.set()

    unsubscribe = async_dispatcher_connect(
        hass,
        wallpad.gateway.async_signal_connection_state(),
        changed,
    )
    try:
        # When the other entry loses its connection.
        other._on_connection_state(connected=False)
        await hass.async_block_till_done()
        # Then the subscribed entry stays available and receives no notification.
        assert not notified.is_set()
        assert all(
            hass.states.get(entity).state == "heat" for entity in wallpad.entities
        )
    finally:
        unsubscribe()
