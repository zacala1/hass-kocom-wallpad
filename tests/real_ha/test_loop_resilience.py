"""Receive/send loops, transport and saved-state restore survive unexpected failures."""

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import serialx
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

import custom_components.kocom_wallpad.gateway as gateway_module
from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.gateway import KocomGateway
from custom_components.kocom_wallpad.models import DeviceKey
from custom_components.kocom_wallpad.transport import AsyncConnection


def frame(device_code: int, room: int, payload: bytes) -> bytes:
    body = b"\x30\xbc\x00\x01\x00" + bytes([device_code, room, 0]) + payload
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


async def stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# serialx.SerialException derives from Exception, not OSError.


@pytest.mark.asyncio
async def test_reconnect_keeps_retrying_after_serial_library_error() -> None:
    connection = AsyncConnection("/dev/ttyUSB0", None, reconnect_backoff=(0.0, 0.0))
    attempts: list[int] = []

    async def connect_once() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise serialx.SerialException("device busy")
        connection._set_connected(connected=True)

    with patch.object(connection, "_connect_once", connect_once):
        await asyncio.wait_for(connection.reconnect(), 1)
    assert len(attempts) == 2
    assert connection._is_connected()


@pytest.mark.asyncio
async def test_recv_serial_library_error_marks_link_lost_and_reconnects() -> None:
    connection = AsyncConnection("/dev/ttyUSB0", None)
    connection._connected = True
    connection._reader = SimpleNamespace(
        read=AsyncMock(side_effect=serialx.SerialException("lost"))
    )
    with patch.object(connection, "reconnect", AsyncMock()) as reconnect:
        assert await connection.recv(512) == b""
        reconnect.assert_awaited_once()
    assert not connection._is_connected()


@pytest.mark.asyncio
async def test_send_serial_library_error_marks_link_lost() -> None:
    connection = AsyncConnection("/dev/ttyUSB0", None)
    connection._connected = True
    connection._writer = SimpleNamespace(
        write=Mock(side_effect=serialx.SerialException("lost"))
    )
    with pytest.raises(serialx.SerialException):
        await connection.send(b"command")
    assert not connection._is_connected()


def test_bad_packet_does_not_drop_following_packets() -> None:
    controller = KocomController(SimpleNamespace())
    first = frame(0x0E, 1, bytes(8))
    second = frame(0x0E, 2, bytes(8))
    seen: list[bytes] = []

    def dispatch(packet: bytes) -> None:
        seen.append(packet)
        if len(seen) == 1:
            raise ValueError("malformed")

    with patch.object(controller, "_dispatch_packet", dispatch):
        controller.feed(first + second)
    assert seen == [first, second]


@pytest.mark.asyncio
async def test_read_loop_reconnects_and_continues_after_unexpected_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    monkeypatch.setattr(gateway_module, "LOOP_ERROR_BACKOFF_SEC", 0.0)
    gateway.conn._set_connected(connected=True)
    delivered = asyncio.Event()
    calls = 0

    async def recv(_nbytes: int, _timeout: float) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("unexpected")
        if calls == 2:
            return b"chunk"
        delivered.set()
        await asyncio.sleep(3600)
        return b""

    reconnect = AsyncMock(side_effect=lambda: gateway.conn._set_connected(connected=True))
    feed = Mock()
    monkeypatch.setattr(gateway.conn, "recv", recv)
    monkeypatch.setattr(gateway.conn, "reconnect", reconnect)
    monkeypatch.setattr(gateway.controller, "feed", feed)
    task = asyncio.create_task(gateway._read_loop())
    try:
        # Given a receive error that is not a transport error,
        # then the loop reconnects and keeps delivering data.
        await asyncio.wait_for(delivered.wait(), 2)
        assert not task.done()
        reconnect.assert_awaited_once()
        feed.assert_called_once_with(b"chunk")
    finally:
        await stop(task)


@pytest.mark.asyncio
async def test_sender_loop_continues_after_unexpected_command_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    monkeypatch.setattr(
        gateway, "_send_command", AsyncMock(side_effect=[ValueError("boom"), True])
    )
    key = DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE)
    task = asyncio.create_task(gateway._sender_loop())
    try:
        # When the first command fails unexpectedly, it reports failure,
        # and the next command is still processed.
        assert await asyncio.wait_for(gateway.async_send_action(key, "turn_on"), 2) is False
        assert await asyncio.wait_for(gateway.async_send_action(key, "turn_on"), 2) is True
        assert not task.done()
    finally:
        await stop(task)


@pytest.mark.asyncio
async def test_unexpected_task_end_schedules_reload_but_cancel_does_not(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    gateway = KocomGateway(hass, entry, "wallpad", 8899)
    reload = Mock()
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", reload)

    async def crash() -> None:
        raise RuntimeError("loop died")

    cancelled = asyncio.create_task(asyncio.sleep(3600))
    cancelled.add_done_callback(gateway._on_task_done)
    await stop(cancelled)  # pyright: ignore[reportArgumentType]
    await asyncio.sleep(0)
    reload.assert_not_called()

    crashed = asyncio.create_task(crash())
    crashed.add_done_callback(gateway._on_task_done)
    await asyncio.gather(crashed, return_exceptions=True)
    await asyncio.sleep(0)
    reload.assert_called_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_damaged_saved_state_does_not_stop_restore(hass: HomeAssistant) -> None:
    # Given one entity with undecodable saved data and one with a valid packet
    # whose saved storage has the wrong type.
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    bad = registry.async_get_or_create(
        "light", DOMAIN, "1-1_1-0:wallpad", config_entry=entry, suggested_object_id="bad"
    )
    good = registry.async_get_or_create(
        "light", DOMAIN, "1-1_0-0:wallpad", config_entry=entry, suggested_object_id="good"
    )
    mock_restore_cache_with_extra_data(
        hass,
        [
            (State(bad.entity_id, "on"), {"packet": "not-hex", "device_storage": {}}),
            (
                State(good.entity_id, "on"),
                {
                    "packet": frame(0x0E, 1, b"\xff" + bytes(7)).hex(),
                    "device_storage": "damaged",
                },
            ),
        ],
    )
    gateway = KocomGateway(hass, entry, "wallpad", 8899)
    # When the gateway restores its saved state.
    await gateway.async_get_entity_registry()
    # Then restore finishes, keeps the valid device and a usable storage dict.
    assert gateway.registry.get(DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE))
    assert isinstance(gateway.controller._device_storage, dict)
    assert gateway._restore_mode is False
    assert gateway._force_register_uid is None
