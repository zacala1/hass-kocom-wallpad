"""Wire-frame and controller helpers shared by the real-HA tests."""

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace

from custom_components.kocom_wallpad.controller import KocomController
from custom_components.kocom_wallpad.gateway import EntityRegistry


def frame(device_code: int, room: int, command: int, payload: bytes) -> bytes:
    """Return a wallpad status report for one device, as the bus carries it."""
    body = b"\x30\xbc\x00\x01\x00" + bytes([device_code, room, command]) + payload
    return b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"


def controller_with(*packets: bytes) -> tuple[KocomController, EntityRegistry]:
    """Build a real controller whose registry holds the given reports."""
    registry = EntityRegistry()
    gateway = SimpleNamespace(
        registry=registry,
        on_device_state=lambda device: registry.upsert(device),
        _force_register_uid=None,
    )
    controller = KocomController(gateway)
    for packet in packets:
        controller._dispatch_packet(packet)
    return controller, registry


async def wait_until(
    condition: Callable[[], bool | Awaitable[bool]], timeout: float = 3.0
) -> None:
    """Poll until the condition holds; fail with a timeout otherwise."""

    async def poll() -> None:
        while True:
            result = condition()
            if (await result) if isinstance(result, Awaitable) else result:
                return
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout)


class Emulator:
    """A localhost TCP wallpad: records frames it receives and answers them."""

    def __init__(self, respond: Callable[[bytes], list[bytes]] | None = None) -> None:
        self.respond = respond
        self.received: list[bytes] = []
        self.writers: list[asyncio.StreamWriter] = []
        self.port = 0
        self._finished: list[asyncio.Event] = []
        self._server: asyncio.Server | None = None

    async def __aenter__(self) -> "Emulator":
        self._server = await asyncio.start_server(self._peer, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()
        for done in self._finished:
            await asyncio.wait_for(done.wait(), 2)

    async def _peer(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        done = asyncio.Event()
        self._finished.append(done)
        self.writers.append(writer)
        try:
            while True:
                try:
                    packet = await reader.readexactly(21)
                except asyncio.IncompleteReadError:
                    break
                self.received.append(packet)
                if self.respond is not None:
                    for answer in self.respond(packet):
                        writer.write(answer)
                    await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    async def send(self, data: bytes) -> None:
        """Send bytes to the newest connection once the integration has connected."""
        await wait_until(lambda: bool(self.writers))
        self.writers[-1].write(data)
        await self.writers[-1].drain()
