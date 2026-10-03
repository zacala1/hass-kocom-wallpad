"""Gateway for Kocom Wallpad."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CMD_DEADLINE_SEC,
    DOMAIN,
    EVENT_DRIVEN_DEVICE_TYPES,
    IDLE_GAP_SEC,
    LOGGER,
    LOOP_ERROR_BACKOFF_SEC,
    RECV_POLL_SEC,
    SEND_RETRY_GAP,
    SEND_RETRY_MAX,
    DeviceType,
)
from .controller import KocomController
from .models import DeviceKey, DeviceState
from .transport import AsyncConnection


@dataclass(slots=True)
class _CmdItem:
    key: DeviceKey
    action: str
    kwargs: dict[str, bool | int | float | str]
    future: asyncio.Future[bool] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    deadline: float = field(
        default_factory=lambda: asyncio.get_running_loop().time() + CMD_DEADLINE_SEC
    )


class _PendingWaiter:

    __slots__ = ("key", "predicate", "future")

    def __init__(
        self, 
        key: DeviceKey,
        predicate: Callable[[DeviceState], bool],
        loop: asyncio.AbstractEventLoop
    ) -> None:
        self.key = key
        self.predicate = predicate
        self.future: asyncio.Future[DeviceState] = loop.create_future()


class EntityRegistry:
    """In-memory entity registry (for gateway internal use)."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._states: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self._shadow: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self.by_platform: Dict[Platform, Dict[str, DeviceState]] = {}

    def upsert(self, dev: DeviceState, allow_insert: bool = True) -> tuple[bool, bool]:
        k = dev.key.key
        old = self._states.get(k)
        is_new = old is None

        if is_new and not allow_insert:
            return False, False
        if is_new:
            self._states[k] = dev
            self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
            return True, True

        platform_changed = (old.platform != dev.platform)
        state_changed = (old.state != dev.state)
        attr_changed = (old.attribute != dev.attribute)
        changed = platform_changed or state_changed or attr_changed

        if changed:
            if platform_changed:
                self.by_platform.get(old.platform, {}).pop(old.key.unique_id, None)
            self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
            self._states[k] = dev
        return False, changed

    def get(self, key: DeviceKey, include_shadow: bool = False) -> Optional[DeviceState]:
        dev = self._states.get(key.key)
        if dev is None and include_shadow:
            return self._shadow.get(key.key)
        return dev

    def promote(self, key: DeviceKey) -> bool:
        """shadow -> real promotion (becomes a target for entity creation)"""
        k = key.key
        dev = self._shadow.pop(k, None)
        if dev is None:
            return False
        self._states[k] = dev
        self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
        return True

    def all_by_platform(self, platform: Platform) -> List[DeviceState]:
        return list(self.by_platform.get(platform, {}).values())


class KocomGateway:
    """Connection/Receive Loop/Transmission Queue/Entity Registry Management Hub."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        entry: ConfigEntry,
        host: str,
        port: int | None
    ) -> None:
        """Initialize the gateway."""
        self.hass = hass
        self.entry = entry
        self.host = host
        self.port = port
        self.conn = AsyncConnection(host=host, port=port)
        self.conn.connection_state_callback = self._on_connection_state
        self.controller = KocomController(self)
        self.registry = EntityRegistry()
        self._tx_queue: asyncio.Queue[_CmdItem] = asyncio.Queue()
        self._current_item: _CmdItem | None = None
        self._task_reader: asyncio.Task[None] | None = None
        self._task_sender: asyncio.Task[None] | None = None
        self._pendings: list[_PendingWaiter] = []
        self._last_rx_monotonic: float = 0.0
        self._last_tx_monotonic: float = 0.0
        self._restore_mode: bool = False
        self._force_register_uid: str | None = None
        self._fresh_keys: set[tuple[int, int, int, int]] = set()

    async def async_start(self) -> None:
        LOGGER.info("Starting gateway - %s:%s", self.host, self.port or "")
        await self.conn.open()
        self._last_rx_monotonic = self.conn.idle_since()
        self._last_tx_monotonic = self.conn.idle_since()
        self._task_reader = asyncio.create_task(self._read_loop())
        self._task_sender = asyncio.create_task(self._sender_loop())
        for task in (self._task_reader, self._task_sender):
            task.add_done_callback(self._on_task_done)

    async def async_stop(self, event: Event | None = None) -> None:
        LOGGER.info("Stopping gateway - %s:%s", self.host, self.port or "")
        if self._task_reader:
            self._task_reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_reader
        if self._task_sender:
            self._task_sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_sender
        if self._current_item is not None:
            if not self._current_item.future.done():
                self._current_item.future.set_result(False)
            self._tx_queue.task_done()
            self._current_item = None
        while not self._tx_queue.empty():
            item = self._tx_queue.get_nowait()
            if not item.future.done():
                item.future.set_result(False)
            self._tx_queue.task_done()
        self._task_reader = None
        self._task_sender = None
        for waiter in self._pendings:
            if not waiter.future.done():
                waiter.future.cancel()
        self._pendings.clear()
        await self.conn.close()

    def is_idle(self) -> bool:
        return self.conn.idle_since() >= IDLE_GAP_SEC

    @callback
    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """Reload the entry if a background loop ends without being cancelled."""
        if task.cancelled():
            return
        LOGGER.error(
            "Gateway task %s stopped unexpectedly; reloading the integration",
            task.get_name(),
            exc_info=task.exception(),
        )
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def _read_loop(self) -> None:
        try:
            LOGGER.debug("Starting read loop")
            while True:
                try:
                    if not self.conn._is_connected():
                        await self.conn.reconnect()
                        continue
                    chunk = await self.conn.recv(512, RECV_POLL_SEC)
                    if chunk:
                        self._last_rx_monotonic = asyncio.get_running_loop().time()
                        self.controller.feed(chunk)
                except Exception:
                    # Never let one failure end the loop: treat the link as lost so
                    # the next pass reconnects, and avoid a tight error spin.
                    LOGGER.exception("Unexpected error in read loop; reconnecting")
                    self.conn.mark_disconnected()
                    await asyncio.sleep(LOOP_ERROR_BACKOFF_SEC)
        except asyncio.CancelledError:
            LOGGER.debug("Read loop cancelled")
            raise

    async def async_send_action(
        self, key: DeviceKey, action: str, **kwargs: bool | int | float | str
    ) -> bool:
        item = _CmdItem(key=key, action=action, kwargs=kwargs)
        await self._tx_queue.put(item)
        try:
            async with asyncio.timeout_at(item.deadline):
                return bool(await item.future)
        except TimeoutError:
            return False
        except asyncio.CancelledError:
            # 정지 중이라면 False로 정리
            if not item.future.done():
                item.future.set_result(False)
            raise

    def on_device_state(self, dev: DeviceState) -> None:  
        was_available = self.is_device_available(dev.key)
        if self.conn._is_connected() and not self._restore_mode:
            self._fresh_keys.add(dev.key.key)
        allow_insert = True
        if dev.key.device_type in (DeviceType.LIGHT, DeviceType.OUTLET):
            allow_insert = bool(getattr(dev, "_is_register", True))
            if getattr(self, "_force_register_uid", None) == dev.key.unique_id:
                allow_insert = True

        is_new, changed = self.registry.upsert(dev, allow_insert=allow_insert)
        if is_new:
            LOGGER.info("New device has been detected. Register -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_new_device(dev.platform),
                [dev],
            )
            self._notify_pendings(dev)
            return

        if changed or (not was_available and self.is_device_available(dev.key)):
            LOGGER.debug("Device state has been changed. Update -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_device_updated(dev.key.unique_id),
                dev,
            )
        self._notify_pendings(dev)

    @callback
    def async_signal_new_device(self, platform: Platform) -> str:
        return f"{DOMAIN}_new_{platform.value}_{self.entry.entry_id}"

    @callback
    def async_signal_device_updated(self, unique_id: str) -> str:
        return f"{DOMAIN}_updated_{self.entry.entry_id}_{unique_id}"

    @callback
    def async_signal_connection_state(self) -> str:
        """Return the connection signal owned by this config entry."""
        return f"{DOMAIN}_connection_{self.entry.entry_id}"

    @callback
    # The transport callback contract passes its boolean state positionally.
    def _on_connection_state(self, connected: bool) -> None:  # noqa: FBT001
        if not connected:
            self._fresh_keys.clear()
        async_dispatcher_send(
            self.hass, self.async_signal_connection_state(), connected
        )

    def is_device_available(self, key: DeviceKey) -> bool:
        """Require a fresh report for this device on the current connection.

        Event-driven devices (gas valve, elevator, motion) are the exception: once
        known they stay available while connected, keeping the last known state.
        """
        if not self.conn._is_connected():
            return False
        if key.key in self._fresh_keys:
            return True
        return (
            key.device_type in EVENT_DRIVEN_DEVICE_TYPES
            and self.registry.get(key) is not None
        )

    def get_devices_from_platform(self, platform: Platform) -> list[DeviceState]:
        return self.registry.all_by_platform(platform)

    async def _async_put_entity_dispatch_packet(self, entity_id: str) -> None:
        state = restore_state.async_get(self.hass).last_states.get(entity_id)
        if not (state and state.extra_data):
            return
        packet = state.extra_data.as_dict().get("packet")
        if not packet:
            return
        ent_reg = er.async_get(self.hass)
        ent_entry = ent_reg.async_get(entity_id)
        if ent_entry and ent_entry.unique_id:
            self._force_register_uid = ent_entry.unique_id.split(":")[0]
        LOGGER.debug("Restore state -> packet: %s", packet)
        try:
            self.controller._dispatch_packet(bytes.fromhex(packet))
        finally:
            self._force_register_uid = None
        device_storage = state.extra_data.as_dict().get("device_storage", {})
        LOGGER.debug("Restore state -> device_storage: %s", device_storage)
        if isinstance(device_storage, dict):
            self.controller.merge_device_storage(device_storage)

    async def async_get_entity_registry(self) -> None:
        self._restore_mode = True
        try:
            entity_registry = er.async_get(self.hass)
            entities = er.async_entries_for_config_entry(entity_registry, self.entry.entry_id)
            for entity in entities:
                try:
                    await self._async_put_entity_dispatch_packet(entity.entity_id)
                except Exception:
                    # Damaged saved state must not keep the integration from loading.
                    LOGGER.warning(
                        "Skipping unrestorable saved state for %s",
                        entity.entity_id,
                        exc_info=True,
                    )
        finally:
            self._restore_mode = False

    def _notify_pendings(self, dev: DeviceState) -> None:
        if not self._pendings:
            return
        hit: list[_PendingWaiter] = []
        for p in self._pendings:
            try:
                if p.key.key == dev.key.key and p.predicate(dev):
                    hit.append(p)
            except Exception:
                # predicate 내부 오류 방어
                continue
        if hit:
            for p in hit:
                if not p.future.done():
                    p.future.set_result(dev)
                try:
                    self._pendings.remove(p)
                except ValueError:
                    pass

    async def _wait_for_confirmation(
        self,
        key: DeviceKey,
        predicate: Callable[[DeviceState], bool],
        timeout: float,
    ) -> DeviceState:
        loop = asyncio.get_running_loop()
        waiter = _PendingWaiter(key, predicate, loop)
        self._pendings.append(waiter)
        try:
            return await asyncio.wait_for(waiter.future, timeout=timeout)
        finally:
            # 타임아웃 등으로 끝났을 때 누수 방지
            if waiter in self._pendings:
                try:
                    self._pendings.remove(waiter)
                except ValueError:
                    pass

    async def _sender_loop(self) -> None:
        LOGGER.debug("Starting sender loop")
        try:
            while True:
                item = await self._tx_queue.get()
                self._current_item = item
                try:
                    if item.future.done() or asyncio.get_running_loop().time() >= item.deadline:
                        continue
                    async with asyncio.timeout_at(item.deadline) as deadline:
                        def abort(
                            _future: asyncio.Future[bool],
                            scope: asyncio.Timeout = deadline,
                            current: _CmdItem = item,
                        ) -> None:
                            if self._current_item is current and not scope.expired():
                                scope.reschedule(asyncio.get_running_loop().time())

                        item.future.add_done_callback(abort)
                        try:
                            success = await self._send_command(item)
                        finally:
                            item.future.remove_done_callback(abort)
                    if not item.future.done():
                        item.future.set_result(success)
                except TimeoutError:
                    LOGGER.warning("Command '%s' exceeded its deadline or was cancelled.", item.action)
                except Exception:
                    # A failing command must not stop the queue for later commands.
                    LOGGER.exception("Command '%s' failed unexpectedly.", item.action)
                finally:
                    if not item.future.done():
                        item.future.set_result(False)
                    self._current_item = None
                    self._tx_queue.task_done()
        except asyncio.CancelledError:
            LOGGER.debug("Sender loop cancelled")
            raise

    async def _send_command(self, item: _CmdItem) -> bool:
        """Send and confirm one item within the sender's deadline scope."""
        try:
            packet, expect_predicate, timeout = self.controller.generate_command(
                item.key, item.action, **item.kwargs
            )
        except Exception as e:
            LOGGER.exception("generate_command failed: %s", e)
            return False

        for attempt in range(1, SEND_RETRY_MAX + 1):
            LOGGER.debug("TX idle wait (max 1.0s) before '%s'...", item.action)
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            while not self.is_idle():
                await asyncio.sleep(0.01)
                if loop.time() - t0 > 1.0:
                    LOGGER.debug("Idle wait timeout (%.2fs).", loop.time() - t0)
                    break

            if item.future.done() or loop.time() >= item.deadline:
                return False
            if not self.conn._is_connected():
                LOGGER.warning("Connection not ready. '%s' abort.", item.action)
                return False

            waiter = _PendingWaiter(item.key, expect_predicate, loop)
            self._pendings.append(waiter)
            # Register before sending so an immediate reply is not lost.
            try:
                try:
                    await self.conn.send(packet)
                except Exception as e:  # transport errors, incl. non-OSError serial ones
                    LOGGER.warning("Send failed on attempt %d: %s", attempt, e)
                else:
                    self._last_tx_monotonic = loop.time()
                    try:
                        await asyncio.wait_for(waiter.future, timeout=timeout)
                    except TimeoutError:
                        LOGGER.warning(
                            "No confirmation for '%s' (attempt %d/%d).",
                            item.action, attempt, SEND_RETRY_MAX,
                        )
                    else:
                        LOGGER.debug("Command '%s' confirmed (attempt %d).", item.action, attempt)
                        return True
            finally:
                if waiter in self._pendings:
                    self._pendings.remove(waiter)
                if not waiter.future.done():
                    waiter.future.cancel()
            if attempt < SEND_RETRY_MAX:
                await asyncio.sleep(SEND_RETRY_GAP)
        LOGGER.error("Command '%s' failed after %d attempts.", item.action, SEND_RETRY_MAX)
        return False
