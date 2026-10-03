"""Preset discovery publishes capabilities on the same packet and later updates."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from homeassistant.components.fan import FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN
from custom_components.kocom_wallpad.controller import PacketFrame
from custom_components.kocom_wallpad.gateway import KocomGateway


def report(preset: int) -> bytes:
    body = b"\x30\xbc\x00\x01\x01\x48\x00\x00"
    body += bytes([0x11, preset, 0x40, 0, 0, 0, 0, 0])
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


@pytest.mark.parametrize("existing_modes", [False, True])
def test_first_nondefault_packet_includes_feature_and_learned_mode(
    hass: HomeAssistant,
    *,
    existing_modes: bool,
) -> None:
    # Given a controller with no confirmed preset feature, even if a list exists.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    if existing_modes:
        gateway.controller._device_storage["ventil_modes"] = ["ventilation"]
    # When the first auto packet is decoded.
    device = gateway.controller._handle_ventilation(PacketFrame(report(2)))[0]
    # Then that same device carries the learned capability and list.
    assert device.attribute["feature_preset"] is True
    assert device.attribute["preset_modes"] == ["ventilation", "auto"]


@pytest.mark.parametrize("preset", [0, 1])
def test_default_or_unknown_packet_does_not_invent_preset_support(
    hass: HomeAssistant,
    preset: int,
) -> None:
    # Given an ordinary fan with no learned nondefault mode.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    # When only an unknown/default mode is observed.
    device = gateway.controller._handle_ventilation(PacketFrame(report(preset)))[0]
    # Then no preset capability or control list is invented.
    assert device.attribute["feature_preset"] is False
    assert device.attribute["preset_modes"] == []


def test_later_learning_does_not_mutate_previous_state_or_duplicate_modes(
    hass: HomeAssistant,
) -> None:
    # Given a previously published state with auto support already learned.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    gateway.controller._device_storage.update(
        {
            "ventil_feature": True,
            "ventil_modes": ["ventilation", "auto"],
        }
    )
    previous = gateway.controller._handle_ventilation(PacketFrame(report(2)))[0]
    # When another known mode is learned twice.
    latest = gateway.controller._handle_ventilation(PacketFrame(report(3)))[0]
    duplicate = gateway.controller._handle_ventilation(PacketFrame(report(3)))[0]
    # Then old attributes remain a snapshot and the current list has no duplicates.
    assert previous.attribute["preset_modes"] == ["ventilation", "auto"]
    assert latest.attribute["preset_modes"] == ["ventilation", "auto", "bypass"]
    assert duplicate.attribute["preset_modes"] == latest.attribute["preset_modes"]


@dataclass(frozen=True, slots=True)
class Wallpad:
    writer: asyncio.StreamWriter
    processed: asyncio.Event
    commands: list[bytes]

    async def send(self, preset: int) -> None:
        self.processed.clear()
        self.writer.write(report(preset))
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
    commands: list[bytes] = []

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.put_nowait(writer)
        try:
            while True:
                try:
                    packet = await reader.readexactly(21)
                except asyncio.IncompleteReadError:
                    break
                commands.append(packet)
                writer.write(report(packet[11]))
                await writer.drain()
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
        yield Wallpad(writer, processed, commands)
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(done.wait(), 2)


@pytest.mark.asyncio
async def test_live_fan_refreshes_capability_lists_registry_and_accepts_preset_service(
    hass: HomeAssistant,
    wallpad: Wallpad,
) -> None:
    # Given an attached ordinary fan without preset control capabilities.
    await wallpad.send(1)
    await hass.async_block_till_done()
    entity_id = hass.states.async_all("fan")[0].entity_id
    initial = hass.states.get(entity_id)
    assert not initial.attributes["supported_features"] & FanEntityFeature.PRESET_MODE
    # When a later auto packet and then bypass packet arrive without a restart.
    await wallpad.send(2)
    await hass.async_block_till_done()
    learned = hass.states.get(entity_id)
    assert learned.attributes["supported_features"] & FanEntityFeature.PRESET_MODE
    assert learned.attributes["preset_modes"] == ["ventilation", "auto"]
    await wallpad.send(3)
    await hass.async_block_till_done()
    latest = hass.states.get(entity_id)
    # Then the same entity and registry reflect each newly learned mode immediately.
    assert latest.attributes["preset_modes"] == ["ventilation", "auto", "bypass"]
    assert (
        er.async_get(hass).async_get(entity_id).supported_features
        & FanEntityFeature.PRESET_MODE
    )
    assert initial.attributes["preset_modes"] == []
    assert learned.attributes["preset_modes"] == ["ventilation", "auto"]
    await asyncio.wait_for(
        hass.services.async_call(
            "fan",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": "auto"},
            blocking=True,
        ),
        2,
    )
    assert len(wallpad.commands) == 1
    assert wallpad.commands[0][11] == 2
    assert hass.states.get(entity_id).attributes["preset_mode"] == "auto"
