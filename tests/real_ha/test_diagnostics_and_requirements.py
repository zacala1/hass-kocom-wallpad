"""Diagnostics content, quiet logging for foreign frames and the dependency range."""

import asyncio
import json
import logging
from importlib.metadata import version
from pathlib import Path

import pytest
from frames import controller_with, frame, wait_until
from homeassistant.core import HomeAssistant
from packaging.requirements import Requirement
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.kocom_wallpad as kocom_wallpad
from custom_components.kocom_wallpad.const import (
    DIAGNOSTIC_MAX_UNHANDLED,
    DIAGNOSTIC_RECENT_FRAMES,
    DOMAIN,
)
from custom_components.kocom_wallpad.diagnostics import (
    async_get_config_entry_diagnostics,
)

# The package may be the repository tree or an extracted release archive.
MANIFEST = Path(str(kocom_wallpad.__file__)).parent / "manifest.json"
THERMOSTAT = frame(0x36, 1, 0x00, b"\x11\x00\x16\x00\x15\x00\x00\x00")


def test_serialx_requirement_is_a_minimum_not_a_pin() -> None:
    # Home Assistant ships serialx and moves it every release; a pin would make the
    # requirement manager install our version over the one core needs.
    requirements = [Requirement(item) for item in json.loads(MANIFEST.read_text())["requirements"]]
    assert [requirement.name for requirement in requirements] == ["serialx"]
    specifiers = list(requirements[0].specifier)
    assert [(item.operator, item.version) for item in specifiers] == [(">=", "1.10.0")]
    assert requirements[0].specifier.contains(version("serialx"))


def test_frame_between_other_participants_is_not_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given a frame where neither end is the wallpad address (0x01).
    controller, _registry = controller_with()
    other = frame(0x0E, 0, 0x00, bytes(8))
    other = other[:5] + b"\x0e\x00\x36\x00" + other[9:]
    other = other[:18] + bytes([sum(other[2:18]) % 256]) + other[19:]
    # When it is received.
    with caplog.at_level(logging.DEBUG, logger="custom_components.kocom_wallpad"):
        controller.feed(other)
    # Then there is no warning and the peer is resolved once, not once per accessor.
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert sum("without wallpad address" in r.getMessage() for r in caplog.records) == 1


def feed_all(*packets: bytes):  # noqa: ANN201
    controller, registry = controller_with()
    for packet in packets:
        controller.feed(packet)
    return controller, registry


def test_snapshot_counts_frames_and_records_unhandled_kinds() -> None:
    bad_checksum = bytearray(THERMOSTAT)
    bad_checksum[18] ^= 0xFF
    controller, _registry = feed_all(
        THERMOSTAT,
        frame(0x77, 1, 0x00, bytes(8)),  # a device code nobody knows
        frame(0x77, 1, 0x00, b"\x01" + bytes(7)),
        frame(0x36, 1, 0x3A, bytes(8)),  # a known device with an undecoded command
        bytes(bad_checksum),
    )
    snapshot = controller.diagnostics_snapshot()
    assert snapshot["stats"] == {
        "frames": 5,
        "bad_checksum": 1,
        "handler_errors": 0,
        "unhandled": 3,
        "unhandled_overflow": 0,
    }
    unhandled = {item["id"]: item for item in snapshot["unhandled_frames"]}
    assert set(unhandled) == {"77:00", "36:3a"}
    assert unhandled["77:00"]["count"] == 2
    assert unhandled["77:00"]["device_type"] == "unknown"
    assert unhandled["77:00"]["first_frame"] != unhandled["77:00"]["last_frame"]
    assert unhandled["36:3a"]["device_type"] == "thermostat"
    assert len(snapshot["recent_frames"]) == 5


def test_snapshot_memory_is_bounded() -> None:
    controller, _registry = feed_all(
        *(frame(0x80 + code % 0x70, 1, code, bytes(8)) for code in range(200)),
    )
    snapshot = controller.diagnostics_snapshot()
    assert len(snapshot["unhandled_frames"]) == DIAGNOSTIC_MAX_UNHANDLED
    assert snapshot["stats"]["unhandled_overflow"] > 0
    assert len(snapshot["recent_frames"]) == DIAGNOSTIC_RECENT_FRAMES
    assert snapshot["stats"]["frames"] == 200


@pytest.mark.asyncio
async def test_entry_diagnostics_redact_the_host_and_describe_the_bus(
    hass: HomeAssistant,
) -> None:
    # Given a running entry that received a thermostat report and an unknown frame.
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
        title="127.0.0.1",
        options={"thermostat_step": "1"},
        data={"host": "127.0.0.1", "port": server.sockets[0].getsockname()[1]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    try:
        writer = await asyncio.wait_for(accepted.get(), 2)
        writer.write(THERMOSTAT + frame(0x77, 1, 0x00, bytes(8)))
        await writer.drain()
        await wait_until(lambda: len(hass.states.async_all("climate")) == 1)
        # When diagnostics are downloaded.
        result = await async_get_config_entry_diagnostics(hass, entry)
        text = json.dumps(result)
        # Then the address appears nowhere, and the protocol view is complete.
        assert "127.0.0.1" not in text
        assert result["entry"]["data"]["host"] == "**REDACTED**"
        assert result["entry"]["data"]["transport"] == "tcp"
        assert result["entry"]["options"] == {"thermostat_step": "1"}
        assert result["loaded"] is True
        assert result["connection"]["connected"] is True
        assert result["connection"]["seconds_since_last_receive"] is not None
        thermostat = next(
            device
            for device in result["devices"]
            if device["device_type"] == "thermostat" and device["sub_type"] == "none"
        )
        assert thermostat["available"] is True
        assert thermostat["platform"] == "climate"
        assert thermostat["state"]["hvac_mode"] == "heat"
        assert thermostat["state"]["target_temp"] == 22.0
        assert thermostat["last_frame"] == THERMOSTAT.hex()
        assert [item["id"] for item in result["unhandled_frames"]] == ["77:00"]
        assert result["stats"]["frames"] == 2
        assert THERMOSTAT.hex() in result["recent_frames"]
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        for done in finished:
            await asyncio.wait_for(done.wait(), 2)
    # An entry that is not loaded still yields its redacted configuration.
    unloaded = await async_get_config_entry_diagnostics(hass, entry)
    assert unloaded["loaded"] is False
    assert "devices" not in unloaded
    assert "127.0.0.1" not in json.dumps(unloaded)


@pytest.mark.asyncio
async def test_serial_path_is_redacted_and_marked_serial(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="/dev/serial/by-id/usb-FTDI_SECRET123",
        data={"host": "/dev/serial/by-id/usb-FTDI_SECRET123", "port": None},
    )
    entry.add_to_hass(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["entry"]["data"]["transport"] == "serial"
    assert "SECRET123" not in json.dumps(result)
