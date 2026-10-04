"""Drive real HA services through the queue, socket, reply parser and state machine."""

# HA and serialx require native asyncio streams at the physical transport seam.
import asyncio

import pytest
from homeassistant.core import Event, HomeAssistant, callback
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN


def report(device_code: int, payload: bytes) -> bytes:
    """Return a wallpad reply addressed to the controller, room one."""
    body = b"\x30\xbc\x00\x01\x00" + bytes([device_code, 1, 0]) + payload
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("device_code", "domain", "service", "controls", "initial", "expected", "state"),
    [
        (
            0x36,
            "climate",
            "set_temperature",
            {"temperature": 23, "hvac_mode": "off"},
            b"\x11\x00\x16\x00\x15\x00\x00\x00",
            b"\x00\x00\x17\x00\x00\x00\x00\x00",
            "off",
        ),
        (
            0x39,
            "climate",
            "set_temperature",
            {"temperature": 23, "hvac_mode": "dry"},
            b"\x10\x00\x01\x00\x15\x16\x00\x00",
            # Mode and target change; the reported fan code (0x01) is kept.
            b"\x10\x02\x01\x00\x00\x17\x00\x00",
            "dry",
        ),
        (
            0x48,
            "fan",
            "turn_on",
            {"percentage": 66, "preset_mode": "auto"},
            b"\x11\x01\x40\x00\x00\x00\x00\x00",
            b"\x11\x02\x80\x00\x00\x00\x00\x00",
            "on",
        ),
    ],
)
async def test_service_roundtrip_when_controls_combined(  # noqa: PLR0913
    hass: HomeAssistant,
    device_code: int,
    domain: str,
    service: str,
    controls: dict[str, str | int],
    initial: bytes,
    expected: bytes,
    state: str,
) -> None:
    # Given a real HA entry, emulator and existing device capabilities.
    ready = asyncio.Event()
    discovered = asyncio.Event()
    eof = asyncio.Event()
    commands: list[bytes] = []

    async def wallpad(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await ready.wait()
            writer.write(report(device_code, initial))
            await writer.drain()
            while packet := await reader.read(21):
                while len(packet) < 21:
                    packet += await reader.readexactly(21 - len(packet))
                commands.append(packet)
                writer.write(report(device_code, packet[10:18]))
                await writer.drain()
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
        assert await hass.config_entries.async_setup(entry.entry_id)
        gateway = hass.data[DOMAIN][entry.entry_id]
        if domain == "fan":
            gateway.controller._device_storage.update(
                {
                    "ventil_feature": True,
                    "ventil_modes": ["ventilation", "auto"],
                }
            )

        @callback
        def state_changed(event: Event) -> None:
            if event.data["entity_id"].startswith(f"{domain}."):
                discovered.set()

        unsubscribe = hass.bus.async_listen("state_changed", state_changed)
        try:
            ready.set()
            await asyncio.wait_for(discovered.wait(), 5)
            await hass.async_block_till_done()
            entity_id = hass.states.async_all(domain)[0].entity_id
            # When a real HA service reaches the queue and physical socket seam.
            await asyncio.wait_for(
                hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": entity_id, **controls},
                    blocking=True,
                ),
                5,
            )
            await hass.async_block_till_done()
            # Then one packet contains both fields; its reply becomes HA state.
            assert len(commands) == 1
            assert commands[0][10:18] == expected
            updated = hass.states.get(entity_id)
            assert updated.state == state
            if domain == "fan":
                assert updated.attributes["preset_mode"] == "auto"
                assert updated.attributes["percentage"] == 66
            else:
                assert updated.attributes["temperature"] == 23.0
        finally:
            unsubscribe()
            assert await hass.config_entries.async_unload(entry.entry_id)
        await asyncio.wait_for(eof.wait(), 5)
