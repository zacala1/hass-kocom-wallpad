"""Regression checks for selectively adopted fork fixes."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import ha_shims  # noqa: F401


async def _load_integration() -> None:
    import importlib

    importlib.import_module("custom_components.kocom_wallpad")


asyncio.run(_load_integration())

from custom_components.kocom_wallpad.const import DeviceType, SubType
from custom_components.kocom_wallpad.climate import KocomClimate
from custom_components.kocom_wallpad.controller import KocomController, PacketFrame
from custom_components.kocom_wallpad.gateway import KocomGateway, _CmdItem
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState
from custom_components.kocom_wallpad.transport import AsyncConnection
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
import custom_components.kocom_wallpad as integration


class ProtocolTests(unittest.TestCase):
    def test_default_temperature_step_preserves_device_value(self) -> None:
        key = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)
        device = DeviceState(key, Platform.CLIMATE, {"temp_step": 0.5}, {})
        gateway = SimpleNamespace(host="wallpad", entry=SimpleNamespace(options={}))
        self.assertEqual(0.5, KocomClimate(gateway, device).target_temperature_step)

    def test_one_degree_override_is_optional_and_thermostat_only(self) -> None:
        key = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)
        device = DeviceState(key, Platform.CLIMATE, {"temp_step": 0.5}, {})
        gateway = SimpleNamespace(
            host="wallpad", entry=SimpleNamespace(options={"thermostat_step": "1"})
        )
        self.assertEqual(1.0, KocomClimate(gateway, device).target_temperature_step)
        aircon_key = DeviceKey(DeviceType.AIRCONDITIONER, 1, 0, SubType.NONE)
        aircon = DeviceState(aircon_key, Platform.CLIMATE, {"temp_step": 0.5}, {})
        self.assertEqual(0.5, KocomClimate(gateway, aircon).target_temperature_step)

    def test_thermostat_optional_fan_properties_are_none(self) -> None:
        key = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)
        device = DeviceState(key, Platform.CLIMATE, {}, {})
        gateway = SimpleNamespace(host="wallpad")
        entity = KocomClimate(gateway, device)
        self.assertIsNone(entity.fan_mode)
        self.assertIsNone(entity.fan_modes)

    def test_split_header_survives_chunk_boundary(self) -> None:
        controller = KocomController(SimpleNamespace())
        packet = bytes.fromhex("aa5530bc0001013601001100160015000000")
        packet += bytes([sum(packet[2:]) % 256]) + b"\r\r"
        controller._rx_buf.extend(packet[:1])
        self.assertEqual([], controller._split_buf())
        controller._rx_buf.extend(packet[1:])
        self.assertEqual([packet], controller._split_buf())

    def test_thermostat_uses_latest_report(self) -> None:
        controller = KocomController(SimpleNamespace())
        body = bytes.fromhex("30bc0001013601001100160015000000")
        frame = PacketFrame(b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r")
        key = DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE)
        controller._device_storage[f"{key.unique_id}_thermo_target"] = 19.0
        controller._device_storage[f"{key.unique_id}_thermo_current"] = 18.0
        states = controller._handle_thermostat(frame)
        self.assertEqual(22.0, states[0].state["target_temp"])
        self.assertEqual(21.0, states[0].state["current_temp"])

    def test_gas_expectation_is_callable(self) -> None:
        controller = KocomController(SimpleNamespace())
        key = DeviceKey(DeviceType.GASVALVE, 0, 0, SubType.NONE)
        predicate, _timeout = controller._expect_for_gasvalve(key, "turn_on")
        state = DeviceState(key, Platform.SWITCH, {}, True)
        self.assertTrue(predicate(state))


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_tcp_round_trip(self) -> None:
        done = asyncio.Event()

        async def echo(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            try:
                packet = await reader.readexactly(7)
                writer.write(packet)
                await writer.drain()
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
                done.set()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        async with server:
            connection = AsyncConnection(
                "127.0.0.1", server.sockets[0].getsockname()[1]
            )
            await connection.open()
            try:
                self.assertEqual(7, await connection.send(b"command"))
                self.assertEqual(b"command", await connection.recv(7, timeout=1))
            finally:
                await connection.close()
            await asyncio.wait_for(done.wait(), timeout=1)

    async def test_initial_failure_does_not_recurse(self) -> None:
        connection = AsyncConnection("offline", 8899)
        with patch(
            "asyncio.open_connection", AsyncMock(side_effect=OSError("offline"))
        ):
            with patch.object(connection, "reconnect", AsyncMock()) as reconnect:
                with self.assertRaises(OSError):
                    await connection.open()
                reconnect.assert_not_awaited()

    async def test_tcp_eof_marks_disconnected(self) -> None:
        connection = AsyncConnection("wallpad", 8899)
        connection._connected = True
        connection._reader = SimpleNamespace(read=AsyncMock(return_value=b""))
        with patch.object(connection, "reconnect", AsyncMock()) as reconnect:
            self.assertEqual(b"", await connection.recv(512))
            reconnect.assert_awaited_once()
        self.assertFalse(connection._is_connected())

    async def test_send_failure_is_propagated(self) -> None:
        connection = AsyncConnection("wallpad", 8899)
        connection._writer = SimpleNamespace(write=Mock(side_effect=OSError("lost")))
        with patch.object(connection, "reconnect", AsyncMock()):
            with self.assertRaises(OSError):
                await connection.send(b"command")


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def gateway(self) -> KocomGateway:
        return KocomGateway(SimpleNamespace(), SimpleNamespace(entry_id="test"), "wallpad", 8899)

    async def test_stop_resolves_queued_commands(self) -> None:
        gateway = self.gateway()
        key = DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE)
        item = _CmdItem(key, "turn_on", {})
        gateway._tx_queue.put_nowait(item)
        await gateway.async_stop()
        self.assertTrue(item.future.done())
        self.assertFalse(item.future.result())
        await asyncio.wait_for(gateway._tx_queue.join(), timeout=0.1)

    async def test_stop_resolves_inflight_command(self) -> None:
        gateway = self.gateway()
        key = DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE)
        sent = asyncio.Event()

        async def send(_packet: bytes) -> int:
            sent.set()
            return 1

        gateway.conn._connected = True
        with patch.object(gateway, "is_idle", return_value=True):
            with patch.object(gateway.conn, "send", side_effect=send):
                with patch.object(
                    gateway.controller,
                    "generate_command",
                    return_value=(b"x", lambda dev: dev.state is True, 10),
                ):
                    gateway._task_sender = asyncio.create_task(gateway._sender_loop())
                    action = asyncio.create_task(
                        gateway.async_send_action(key, "turn_on")
                    )
                    try:
                        await asyncio.wait_for(sent.wait(), timeout=1)
                        await gateway.async_stop()
                        self.assertFalse(await asyncio.wait_for(action, timeout=1))
                        await asyncio.wait_for(gateway._tx_queue.join(), timeout=1)
                        self.assertEqual([], gateway._pendings)
                    finally:
                        await gateway.async_stop()
                        if not action.done():
                            action.cancel()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_start_cleans_gateway_and_requests_ha_retry(self) -> None:
        gateway = SimpleNamespace(
            async_get_entity_registry=AsyncMock(),
            async_start=AsyncMock(side_effect=OSError("offline")),
            async_stop=AsyncMock(),
        )
        entry = SimpleNamespace(
            data={"host": "wallpad", "port": 8899}, entry_id="entry"
        )
        hass = SimpleNamespace(data={})
        with patch.object(integration, "KocomGateway", return_value=gateway):
            with self.assertRaises(ConfigEntryNotReady):
                await integration.async_setup_entry(hass, entry)
        gateway.async_stop.assert_awaited_once()
        self.assertEqual({}, hass.data)

    async def test_failed_platform_setup_removes_runtime(self) -> None:
        gateway = SimpleNamespace(
            async_get_entity_registry=AsyncMock(),
            async_start=AsyncMock(),
            async_stop=AsyncMock(),
        )
        entry = SimpleNamespace(
            data={"host": "wallpad", "port": 8899},
            entry_id="entry",
            async_on_unload=Mock(),
            add_update_listener=Mock(return_value=lambda: None),
        )
        hass = SimpleNamespace(
            data={},
            bus=SimpleNamespace(async_listen_once=Mock()),
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(
                    side_effect=RuntimeError("platform failed")
                )
            ),
        )
        with patch.object(integration, "KocomGateway", return_value=gateway):
            with self.assertRaises(RuntimeError):
                await integration.async_setup_entry(hass, entry)
        gateway.async_stop.assert_awaited_once()
        self.assertEqual({}, hass.data["kocom_wallpad"])

    async def test_immediate_reply_confirms_command(self) -> None:
        gateway = KocomGateway(SimpleNamespace(), SimpleNamespace(entry_id="test"), "wallpad", 8899)
        key = DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE)
        state = DeviceState(key, Platform.LIGHT, {}, True)

        async def send(_packet: bytes) -> int:
            gateway._notify_pendings(state)
            return 1

        gateway.conn._connected = True
        with patch.object(gateway, "is_idle", return_value=True):
            with patch.object(gateway.conn, "send", side_effect=send):
                with patch.object(
                    gateway.controller,
                    "generate_command",
                    return_value=(b"x", lambda dev: dev.state is True, 0.02),
                ):
                    with patch(
                        "custom_components.kocom_wallpad.gateway.SEND_RETRY_MAX", 1
                    ):
                        gateway._task_sender = asyncio.create_task(
                            gateway._sender_loop()
                        )
                        try:
                            result = await asyncio.wait_for(
                                gateway.async_send_action(key, "turn_on"), timeout=0.2
                            )
                            self.assertTrue(result)
                        finally:
                            await gateway.async_stop()


if __name__ == "__main__":
    unittest.main()
