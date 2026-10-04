"""Actual config-entry setup and discovery using a localhost wallpad emulator."""

# HA and serialx expose asyncio streams.
import asyncio

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN


@pytest.mark.asyncio
async def test_discovery_and_unload_when_wallpad_connected(hass: HomeAssistant) -> None:
    # Given a real TCP wallpad which reports a thermostat, including a split header.
    ready = asyncio.Event()
    eof = asyncio.Event()
    body = bytes.fromhex("30bc0001013601001100160015000000")
    packet = b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"

    async def wallpad(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await ready.wait()
            writer.write(packet[:1])
            await writer.drain()
            writer.write(packet[1:])
            await writer.drain()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            eof.set()

    server = await asyncio.start_server(wallpad, "127.0.0.1", 0)
    async with server:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "host": "127.0.0.1",
                "port": server.sockets[0].getsockname()[1],
            },
        )
        entry.add_to_hass(hass)
        # When HA loads all platforms and receives the packet over the real connection.
        assert await hass.config_entries.async_setup(entry.entry_id)
        gateway = hass.data[DOMAIN][entry.entry_id]
        changed = asyncio.Event()

        @callback
        def state_changed(_event: Event) -> None:
            changed.set()

        unsubscribe = hass.bus.async_listen("state_changed", state_changed)
        try:
            ready.set()
            await asyncio.wait_for(changed.wait(), 5)
            await hass.async_block_till_done()
            states = hass.states.async_all("climate")
            # Then state and stable registry identity are published by actual HA.
            assert len(states) == 1
            assert states[0].attributes["temperature"] == 22.0
            assert states[0].attributes["current_temperature"] == 21.0
            registry_entry = er.async_get(hass).async_get(states[0].entity_id)
            assert registry_entry.unique_id == "5-1_0-0:127.0.0.1"
        finally:
            unsubscribe()
            assert await hass.config_entries.async_unload(entry.entry_id)
        await asyncio.wait_for(eof.wait(), 5)
        assert gateway._task_reader is None
        assert gateway._task_sender is None
        assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_setup_retry_when_wallpad_unreachable(hass: HomeAssistant) -> None:
    # Given a localhost port which was allocated then closed.
    server = await asyncio.start_server(
        lambda reader, writer: writer.close(), "127.0.0.1", 0
    )
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "127.0.0.1", "port": port})
    entry.add_to_hass(hass)
    # When real HA attempts config-entry setup.
    result = await asyncio.wait_for(hass.config_entries.async_setup(entry.entry_id), 5)
    # Then HA owns retry and no partial gateway is published.
    assert result is False
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


@pytest.mark.asyncio
async def test_options_when_step_selected(hass: HomeAssistant) -> None:
    # Given a registered but unloaded entry with default model-derived temperature step.
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "wallpad", "port": 8899})
    entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "form"
    # When the real HA options manager saves the explicitly selected override.
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        user_input={"thermostat_step": "1"},
    )
    # Then the setting is entry-owned without assigning OptionsFlow.config_entry.
    assert result["type"] == "create_entry"
    assert entry.options["thermostat_step"] == "1"
