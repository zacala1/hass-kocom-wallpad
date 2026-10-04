"""Command deadlines exercise the real queue and TCP transport under real HA."""

import asyncio
import contextlib
import errno
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad import gateway as gateway_module
from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.gateway import KocomGateway
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState

KEY = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)


@pytest_asyncio.fixture
async def gateway(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[KocomGateway]:
    # Given real streams, with only the time budget shortened for regression tests.
    monkeypatch.setattr(gateway_module, "CMD_DEADLINE_SEC", 0.1, raising=False)
    ended = asyncio.Event()

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            ended.set()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    instance = KocomGateway(
        hass,
        MockConfigEntry(domain=DOMAIN),
        "127.0.0.1",
        server.sockets[0].getsockname()[1],
    )
    await instance.async_start()
    monkeypatch.setattr(instance, "is_idle", lambda: True)
    try:
        yield instance
    finally:
        await instance.async_stop()
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(ended.wait(), 2)


@pytest.mark.asyncio
async def test_failed_send_returns_when_reconnect_unavailable(
    gateway: KocomGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a failed writer and a closed localhost port for reconnect attempts.
    unavailable = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
    gateway.conn.port = unavailable.sockets[0].getsockname()[1]
    unavailable.close()
    await unavailable.wait_closed()
    writer = gateway.conn._writer
    assert writer is not None

    def fail(_packet: bytes) -> None:
        raise OSError(errno.EPIPE, "writer failed")

    monkeypatch.setattr(writer, "write", fail)
    # When one command encounters failure and another follows it.
    first = asyncio.create_task(
        gateway.async_send_action(KEY, "set_temperature", target_temp=22)
    )
    second = asyncio.create_task(
        gateway.async_send_action(KEY, "set_temperature", target_temp=23)
    )
    try:
        # Then both calls resolve while the independent reader continues recovering.
        assert await asyncio.wait_for(asyncio.gather(first, second), 1) == [
            False,
            False,
        ]
        await asyncio.wait_for(gateway._tx_queue.join(), 1)
        assert gateway._task_sender is not None
        assert not gateway._task_sender.done()
    finally:
        for task in (first, second):
            task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
async def test_stalled_drain_expires_without_killing_sender(
    gateway: KocomGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a write whose drain never completes.
    entered = asyncio.Event()
    writer = gateway.conn._writer
    assert writer is not None

    async def stall() -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(writer, "drain", stall)
    # When the caller waits on the command's whole-operation budget.
    task = asyncio.create_task(
        gateway.async_send_action(KEY, "set_temperature", target_temp=22)
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        # Then the call fails and the sender remains available for subsequent items.
        assert await asyncio.wait_for(task, 1) is False
        await asyncio.wait_for(gateway._tx_queue.join(), 1)
        assert not gateway._pendings
        assert gateway._current_item is None
        assert gateway._task_sender is not None
        assert not gateway._task_sender.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_queued_command_expires_without_later_write(
    gateway: KocomGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a paused sender and a command that cannot leave its queue.
    assert gateway._task_sender is not None
    gateway._task_sender.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await gateway._task_sender
    writes: list[bytes] = []
    writer = gateway.conn._writer
    assert writer is not None
    monkeypatch.setattr(writer, "write", writes.append)
    # When the queued command reaches its deadline.
    task = asyncio.create_task(
        gateway.async_send_action(KEY, "set_temperature", target_temp=22)
    )
    try:
        assert await asyncio.wait_for(task, 1) is False
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        gateway._task_sender = asyncio.create_task(gateway._sender_loop())
    # Then resuming transmission drains the queue without emitting an expired packet.
    await asyncio.wait_for(gateway._tx_queue.join(), 1)
    assert writes == []


@pytest.mark.asyncio
async def test_cancellation_during_idle_never_sends(
    gateway: KocomGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an active command waiting for idle, before its first write.
    entered = asyncio.Event()
    released = False
    writes: list[bytes] = []
    writer = gateway.conn._writer
    assert writer is not None
    monkeypatch.setattr(writer, "write", writes.append)

    def idle() -> bool:
        entered.set()
        return released

    monkeypatch.setattr(gateway, "is_idle", idle)
    task = asyncio.create_task(
        gateway.async_send_action(KEY, "set_temperature", target_temp=22)
    )
    await asyncio.wait_for(entered.wait(), 1)
    # When the original caller cancels before the bus becomes idle.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    released = True
    # Then the canceled item is discarded and no late write occurs.
    await asyncio.wait_for(gateway._tx_queue.join(), 1)
    assert writes == []
    assert not gateway._pendings


@pytest.mark.asyncio
async def test_cancellation_during_confirmation_never_retries(
    gateway: KocomGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an emitted packet with no reply from the real peer.
    sent = asyncio.Event()
    writer = gateway.conn._writer
    assert writer is not None
    original_write = writer.write
    writes: list[bytes] = []

    def record(packet: bytes) -> None:
        original_write(packet)
        writes.append(packet)
        sent.set()

    monkeypatch.setattr(writer, "write", record)
    task = asyncio.create_task(
        gateway.async_send_action(KEY, "set_temperature", target_temp=22),
    )
    await asyncio.wait_for(sent.wait(), 1)
    # When the caller cancels while confirmation is pending.
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Then the item releases the queue and waiter without another write.
    await asyncio.wait_for(gateway._tx_queue.join(), 1)
    assert len(writes) == 1
    assert not gateway._pendings


@pytest.mark.asyncio
async def test_transport_send_raises_without_waiting_for_reconnect(
    gateway: KocomGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a failed write while the independent reader owns recovery.
    writer = gateway.conn._writer
    assert writer is not None
    recovering = asyncio.Event()

    def fail(_packet: bytes) -> None:
        raise OSError(errno.EPIPE, "writer failed")

    async def reconnect() -> None:
        recovering.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(writer, "write", fail)
    monkeypatch.setattr(gateway.conn, "reconnect", reconnect)
    # When the transport attempts the failed write.
    with pytest.raises(OSError, match="writer failed"):
        await asyncio.wait_for(gateway.conn.send(b"command"), 1)
    # Then send returns its error and the reader starts recovery independently.
    await asyncio.wait_for(recovering.wait(), 1)


@pytest.mark.asyncio
async def test_cancellation_and_reply_same_turn_do_not_reschedule_closed_scope(
    gateway: KocomGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a reply and cancellation arriving before the sender next yields.
    loop = asyncio.get_running_loop()
    errors: list[str] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(
        lambda _loop, context: errors.append(str(context.get("exception"))),
    )
    writer = gateway.conn._writer
    assert writer is not None
    task = asyncio.create_task(
        gateway.async_send_action(KEY, "set_temperature", target_temp=22),
    )

    def cancel_and_confirm(_packet: bytes) -> None:
        task.cancel()
        gateway._notify_pendings(
            DeviceState(KEY, Platform.CLIMATE, {}, {"target_temp": 22}),
        )

    async def drained() -> None:
        return

    monkeypatch.setattr(writer, "write", cancel_and_confirm)
    monkeypatch.setattr(writer, "drain", drained)
    try:
        # When synchronous confirmation lets the scope exit before its queued callback.
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(gateway._tx_queue.join(), 1)
        # Then the late callback is harmless and the sender remains alive.
        assert errors == []
        assert gateway._task_sender is not None
        assert not gateway._task_sender.done()
    finally:
        loop.set_exception_handler(previous_handler)
