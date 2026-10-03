"""Config flow input handling, connection test and entity-preserving reconfigure."""

import asyncio
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from frames import frame, wait_until
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN

THERMOSTAT = frame(0x36, 1, 0x00, b"\x11\x00\x16\x00\x15\x00\x00\x00")


@pytest_asyncio.fixture
async def wallpad_port() -> AsyncGenerator[int]:
    """A reachable TCP endpoint standing in for the wallpad adapter."""

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while await reader.read(512):
                continue
        finally:
            writer.close()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    yield server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()


@pytest_asyncio.fixture
async def closed_port() -> int:
    """A localhost port that was allocated and released, so nothing listens."""
    server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


@contextmanager
def entry_setup_disabled() -> Iterator[None]:
    """Stop a created entry from connecting; these tests cover the flow only."""
    with (
        patch("custom_components.kocom_wallpad.async_setup_entry", return_value=True),
        patch("custom_components.kocom_wallpad.async_unload_entry", return_value=True),
    ):
        yield


async def start_user(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    return result["flow_id"]


@pytest.mark.asyncio
async def test_user_flow_trims_host_and_creates_entry(
    hass: HomeAssistant, wallpad_port: int
) -> None:
    with entry_setup_disabled():
        flow_id = await start_user(hass)
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"host": "  127.0.0.1 ", "port": wallpad_port}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "127.0.0.1"
    assert result["data"] == {"host": "127.0.0.1", "port": wallpad_port}
    assert result["result"].unique_id == "127.0.0.1"


@pytest.mark.asyncio
async def test_user_flow_reports_unreachable_address_and_keeps_input(
    hass: HomeAssistant, closed_port: int
) -> None:
    flow_id = await start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"host": "127.0.0.1", "port": closed_port}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description
    }
    assert suggested == {"host": "127.0.0.1", "port": closed_port}
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.asyncio
async def test_user_flow_rejects_blank_host_without_connecting(
    hass: HomeAssistant,
) -> None:
    flow_id = await start_user(hass)
    with patch(
        "custom_components.kocom_wallpad.config_flow._async_can_connect",
        AsyncMock(return_value=True),
    ) as can_connect:
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"host": "   ", "port": 8899}
        )
    assert result["errors"] == {"host": "invalid_host"}
    can_connect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("port", [0, 65536, -1])
async def test_user_flow_rejects_port_outside_range(
    hass: HomeAssistant, port: int
) -> None:
    flow_id = await start_user(hass)
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            flow_id, {"host": "127.0.0.1", "port": port}
        )


@pytest.mark.asyncio
async def test_user_flow_aborts_for_an_already_configured_host(
    hass: HomeAssistant, wallpad_port: int
) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="127.0.0.1",
        data={"host": "127.0.0.1", "port": wallpad_port},
    ).add_to_hass(hass)
    flow_id = await start_user(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"host": "127.0.0.1", "port": wallpad_port}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_user_flow_serial_path_ignores_port(hass: HomeAssistant) -> None:
    flow_id = await start_user(hass)
    with (
        entry_setup_disabled(),
        patch(
            "custom_components.kocom_wallpad.config_flow.AsyncConnection.open",
            AsyncMock(),
        ) as open_connection,
    ):
        result = await hass.config_entries.flow.async_configure(
            flow_id, {"host": "/dev/ttyUSB0", "port": 8899}
        )
    open_connection.assert_awaited_once()
    assert result["data"] == {"host": "/dev/ttyUSB0", "port": None}


def make_entry(hass: HomeAssistant, port: int, host: str = "127.0.0.1") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=host,
        unique_id=host,
        data={"host": host, "port": port},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.asyncio
async def test_reconfigure_moves_entities_to_the_new_host(
    hass: HomeAssistant, wallpad_port: int
) -> None:
    # Given an entry with entities whose unique ids end with the host.
    entry = make_entry(hass, wallpad_port)
    registry = er.async_get(hass)
    climate = registry.async_get_or_create(
        "climate", DOMAIN, "5-1_0-0:127.0.0.1", config_entry=entry
    )
    sensor = registry.async_get_or_create(
        "sensor", DOMAIN, "5-1_0-4:127.0.0.1", config_entry=entry
    )
    # When the host is changed to one that is reachable.
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    with entry_setup_disabled():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "localhost", "port": wallpad_port}
        )
    # Then the entry follows and every entity keeps its entity id.
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"host": "localhost", "port": wallpad_port}
    assert entry.unique_id == "localhost"
    assert entry.title == "localhost"
    assert registry.async_get(climate.entity_id).unique_id == "5-1_0-0:localhost"
    assert registry.async_get(sensor.entity_id).unique_id == "5-1_0-4:localhost"


@pytest.mark.asyncio
async def test_reconfigure_with_unreachable_address_changes_nothing(
    hass: HomeAssistant, wallpad_port: int, closed_port: int
) -> None:
    entry = make_entry(hass, wallpad_port)
    registry = er.async_get(hass)
    climate = registry.async_get_or_create(
        "climate", DOMAIN, "5-1_0-0:127.0.0.1", config_entry=entry
    )
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "localhost", "port": closed_port}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == {"host": "127.0.0.1", "port": wallpad_port}
    assert registry.async_get(climate.entity_id).unique_id == "5-1_0-0:127.0.0.1"


@pytest.mark.asyncio
async def test_reconfigure_without_changes_skips_the_connection_test(
    hass: HomeAssistant, closed_port: int
) -> None:
    # The live connection may block a second one, so an unchanged address is accepted.
    entry = make_entry(hass, closed_port)
    result = await entry.start_reconfigure_flow(hass)
    with (
        entry_setup_disabled(),
        patch(
            "custom_components.kocom_wallpad.config_flow._async_can_connect",
            AsyncMock(return_value=False),
        ) as can_connect,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "127.0.0.1", "port": closed_port}
        )
    assert result["reason"] == "reconfigure_successful"
    can_connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconfigure_refuses_a_host_used_by_another_entry(
    hass: HomeAssistant, wallpad_port: int
) -> None:
    entry = make_entry(hass, wallpad_port)
    make_entry(hass, wallpad_port, host="other")
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "other", "port": wallpad_port}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_reconfigured_live_entry_reloads_with_the_same_entities(
    hass: HomeAssistant,
) -> None:
    # Given a running entry with a discovered thermostat.
    # The flow's connection test also connects, so find the gateway's peer by port.
    peers: dict[int, asyncio.StreamWriter] = {}
    finished: list[asyncio.Event] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        done = asyncio.Event()
        finished.append(done)
        peers[writer.get_extra_info("peername")[1]] = writer
        try:
            while await reader.read(512):
                continue
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    entry = make_entry(hass, port)
    assert await hass.config_entries.async_setup(entry.entry_id)
    registry = er.async_get(hass)
    try:
        gateway = hass.data[DOMAIN][entry.entry_id]
        await wait_until(lambda: gateway.conn._writer is not None and peers)
        writer = peers[gateway.conn._writer.get_extra_info("sockname")[1]]
        writer.write(THERMOSTAT)
        await writer.drain()
        await wait_until(lambda: len(hass.states.async_all("climate")) == 1)
        entity_id = hass.states.async_all("climate")[0].entity_id
        assert registry.async_get(entity_id).unique_id == "5-1_0-0:127.0.0.1"
        # When the host is reconfigured to another name of the same wallpad.
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "localhost", "port": port}
        )
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()
        # Then the entry reloads on the new host and the same entity returns on a report.
        await wait_until(lambda: entry.state is ConfigEntryState.LOADED)
        assert hass.data[DOMAIN][entry.entry_id].host == "localhost"
        gateway = hass.data[DOMAIN][entry.entry_id]
        await wait_until(lambda: gateway.conn._writer is not None)
        local_port = gateway.conn._writer.get_extra_info("sockname")[1]
        await wait_until(lambda: local_port in peers)
        new_writer = peers[local_port]
        new_writer.write(THERMOSTAT)
        await new_writer.drain()
        await wait_until(lambda: hass.states.get(entity_id).state == "heat")
        assert registry.async_get(entity_id).unique_id == "5-1_0-0:localhost"
        assert len(hass.states.async_all("climate")) == 1
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        for done in finished:
            await asyncio.wait_for(done.wait(), 2)
