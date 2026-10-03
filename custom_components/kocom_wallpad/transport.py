"""Transport for Kocom Wallpad."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import asyncio
import serialx
import time

from .const import LOGGER


@dataclass
class AsyncConnection:
    """Async Connection."""
    host: str
    port: Optional[int]
    serial_baud: int = 9600
    connect_timeout: float = 5.0
    reconnect_backoff: Tuple[float, float] = (1.0, 30.0)  # min, max seconds

    def __post_init__(self) -> None:
        """Initialize the connection."""
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._last_activity_mono: float = time.monotonic()
        self._last_reconn_delay: float = 0.0
        self._connected = False
        self._reconnect_lock = asyncio.Lock()

    async def _connect_once(self) -> None:
        """Attempt a single connection, without any self-healing on failure."""
        if self.port is None:
            self._reader, self._writer = await asyncio.wait_for(
                serialx.open_serial_connection(
                    url=self.host, baudrate=self.serial_baud
                ),
                timeout=self.connect_timeout,
            )
            LOGGER.info("Connection opened for serial: %s", self.host)
        else:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.connect_timeout,
            )
            LOGGER.info("Connection opened for socket: %s:%s", self.host, self.port)
        self._connected = True
        self._touch()

    async def open(self) -> None:
        """Attempt the initial connection once and raise on failure.

        This intentionally does not fall back to the infinite-retry reconnect()
        loop: the caller (KocomGateway.async_start, during config entry setup)
        needs a bounded failure so Home Assistant can raise ConfigEntryNotReady
        and use its own retry-with-backoff instead of blocking setup forever.
        Recovering an already-established connection that drops later is
        handled separately by the reader calling reconnect().
        """
        await self._connect_once()

    async def _close_writer(self) -> None:
        if self._writer is None:
            return
        self._writer.close()
        try:
            await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
        except (OSError, RuntimeError, TimeoutError) as err:
            LOGGER.debug("Connection close failed: %r", err)
        finally:
            self._writer = None

    async def close(self) -> None:
        if self._writer is not None:
            LOGGER.info("Closing connection")
        await self._close_writer()
        self._reader = None
        self._connected = False

    def _is_connected(self) -> bool:
        return self._connected

    def _touch(self) -> None:
        self._last_activity_mono = time.monotonic()

    def idle_since(self) -> float:
        return max(0.0, time.monotonic() - self._last_activity_mono)

    async def send(self, data: bytes) -> int:
        if not self._writer:
            raise RuntimeError("connection not open")
        try:
            LOGGER.debug("Sending: %s", data.hex())
            self._writer.write(data)
            await self._writer.drain()
            self._touch()
            return len(data)
        except asyncio.CancelledError:
            self._connected = False
            raise
        except (OSError, RuntimeError, ValueError) as e:
            LOGGER.warning("Send failed: %r", e)
            self._connected = False
            raise

    async def recv(self, nbytes: int, timeout: float = 0.05) -> bytes:
        if not self._reader:
            raise RuntimeError("connection not open")
        try:
            chunk = await asyncio.wait_for(self._reader.read(nbytes), timeout=timeout)
        except asyncio.TimeoutError:
            return b""
        except (OSError, RuntimeError, ValueError) as e:
            LOGGER.warning("Recv failed: %r", e)
            self._connected = False
            await self.reconnect()
            return b""
        if chunk:
            self._touch()
        elif self.port is not None:
            await self.close()
            await self.reconnect()
        return chunk

    async def reconnect(self) -> None:
        async with self._reconnect_lock:
            if self._is_connected():
                return

            await self._close_writer()

            delay_min, delay_max = self.reconnect_backoff
            delay = self._last_reconn_delay if self._last_reconn_delay > 0.0 else delay_min

            while True:
                LOGGER.info("Connection lost. Reconnecting in %.1f sec...", delay)
                await asyncio.sleep(delay)
                self._last_reconn_delay = min(delay * 2, delay_max)
                try:
                    await self._connect_once()
                except (OSError, RuntimeError, ValueError) as e:
                    LOGGER.warning("Reconnect attempt failed: %r", e)
                    delay = self._last_reconn_delay
                    continue
                LOGGER.info("Connection reconnected")
                self._last_reconn_delay = delay_min
                return
