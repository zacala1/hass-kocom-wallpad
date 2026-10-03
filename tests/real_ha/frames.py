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
