"""Serialx and TCP transport checks using real streams, not serial shims."""

# Serialx exposes asyncio streams.
import asyncio

import pytest

from custom_components.kocom_wallpad.transport import AsyncConnection


@pytest.mark.asyncio
@pytest.mark.parametrize("serial", [False, True])
async def test_roundtrip_when_transport_connected(*, serial: bool) -> None:
    # Given a real echo peer; serialx supports a socket URL without physical hardware.
    done = asyncio.Event()

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            message = await reader.readexactly(7)
            writer.write(message)
            await writer.drain()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        connection = AsyncConnection(
            f"socket://127.0.0.1:{port}" if serial else "127.0.0.1",
            None if serial else port,
        )
        # When the existing public transport opens, sends, receives and closes.
        await connection.open()
        try:
            assert await connection.send(b"command") == 7
            assert await connection.recv(7, timeout=2) == b"command"
        finally:
            await connection.close()
        # Then the real peer sees EOF, proving stream cleanup.
        await asyncio.wait_for(done.wait(), 2)
        assert not connection._is_connected()
