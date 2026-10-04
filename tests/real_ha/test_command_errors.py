"""Unconfirmed commands must reach HA callers as action errors."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad import gateway as gateway_module
from custom_components.kocom_wallpad.climate import KocomClimate
from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.fan import KocomFan
from custom_components.kocom_wallpad.gateway import KocomGateway
from custom_components.kocom_wallpad.light import KocomLight
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState
from custom_components.kocom_wallpad.switch import KocomSwitch

Path = Literal[
    "light_on",
    "light_off",
    "switch_on",
    "switch_off",
    "climate_hvac",
    "climate_fan",
    "climate_preset",
    "climate_temperature",
    "fan_speed",
    "fan_preset",
    "fan_on",
    "fan_on_speed",
    "fan_on_preset",
    "fan_on_both",
    "fan_on_zero",
    "fan_off",
]
PATHS: tuple[Path, ...] = (
    "light_on",
    "light_off",
    "switch_on",
    "switch_off",
    "climate_hvac",
    "climate_fan",
    "climate_preset",
    "climate_temperature",
    "fan_speed",
    "fan_preset",
    "fan_on",
    "fan_on_speed",
    "fan_on_preset",
    "fan_on_both",
    "fan_on_zero",
    "fan_off",
)


def action_for(gateway: KocomGateway, path: Path) -> Callable[[], Awaitable[None]]:
    """Return the real platform method for each command-producing branch."""
    light = KocomLight(
        gateway,
        DeviceState(
            DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE),
            Platform.LIGHT,
            {},
            state=False,
        ),
    )
    switch = KocomSwitch(
        gateway,
        DeviceState(
            DeviceKey(DeviceType.OUTLET, 1, 0, SubType.NONE),
            Platform.SWITCH,
            {},
            state=False,
        ),
    )
    climate = KocomClimate(
        gateway,
        DeviceState(
            DeviceKey(DeviceType.THERMOSTAT, 1, 0, SubType.NONE),
            Platform.CLIMATE,
            {},
            {},
        ),
    )
    fan = KocomFan(
        gateway,
        DeviceState(
            DeviceKey(DeviceType.VENTILATION, 0, 0, SubType.NONE),
            Platform.FAN,
            {"feature_preset": True, "speed_list": [1, 2, 3], "preset_modes": ["auto"]},
            {"state": False, "speed": 1, "preset_mode": "auto"},
        ),
    )
    actions: dict[Path, Callable[[], Awaitable[None]]] = {
        "light_on": light.async_turn_on,
        "light_off": light.async_turn_off,
        "switch_on": switch.async_turn_on,
        "switch_off": switch.async_turn_off,
        "climate_hvac": lambda: climate.async_set_hvac_mode(HVACMode.HEAT),
        "climate_fan": lambda: climate.async_set_fan_mode("low"),
        "climate_preset": lambda: climate.async_set_preset_mode("away"),
        "climate_temperature": lambda: climate.async_set_temperature(temperature=23),
        "fan_speed": lambda: fan.async_set_percentage(66),
        "fan_preset": lambda: fan.async_set_preset_mode("auto"),
        "fan_on": fan.async_turn_on,
        "fan_on_speed": lambda: fan.async_turn_on(percentage=66),
        "fan_on_preset": lambda: fan.async_turn_on(preset_mode="auto"),
        "fan_on_both": lambda: fan.async_turn_on(percentage=66, preset_mode="auto"),
        "fan_on_zero": lambda: fan.async_turn_on(percentage=0, preset_mode="auto"),
        "fan_off": fan.async_turn_off,
    }
    return actions[path]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("result", [False, None])
async def test_platform_action_raises_when_command_unconfirmed(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
    *,
    result: bool | None,
) -> None:
    # Given a real entity whose gateway reports no confirmed result.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    send = AsyncMock(return_value=result)
    monkeypatch.setattr(gateway, "async_send_action", send)
    action = action_for(gateway, path)
    # When any command-producing platform branch runs.
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        await action()
    # Then the failure is surfaced after precisely one gateway action.
    send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_platform_action_returns_when_command_confirmed(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
) -> None:
    # Given a real entity whose gateway confirms its command.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(gateway, "async_send_action", send)
    # When its command-producing branch runs.
    assert await action_for(gateway, path)() is None
    # Then the successful result remains normal and emits one action.
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_platform_action_propagates_cancellation(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a gateway whose command wait is cancelled.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    monkeypatch.setattr(
        gateway, "async_send_action", AsyncMock(side_effect=asyncio.CancelledError)
    )
    # When the platform awaits that command.
    with pytest.raises(asyncio.CancelledError):
        await action_for(gateway, "light_on")()
    # Then cancellation is propagated rather than converted to an action error.


@pytest.mark.asyncio
async def test_real_ha_service_raises_when_peer_never_confirms(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an actual HA thermostat and TCP peer which never confirms commands.
    monkeypatch.setattr(gateway_module, "CMD_DEADLINE_SEC", 0.05)
    ready = asyncio.Event()
    discovered = asyncio.Event()
    done = asyncio.Event()
    commands: list[bytes] = []
    body = bytes.fromhex("30bc0001013601001100160015000000")
    packet = b"\xaa\x55" + body + bytes([sum(body) % 256]) + b"\r\r"

    async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await ready.wait()
            writer.write(packet)
            await writer.drain()
            while command := await reader.read(512):
                commands.append(command)
        finally:
            writer.close()
            await writer.wait_closed()
            done.set()

    @callback
    def changed(_event: Event) -> None:
        if hass.states.async_all("climate"):
            discovered.set()

    server = await asyncio.start_server(peer, "127.0.0.1", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "127.0.0.1",
            "port": server.sockets[0].getsockname()[1],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    monkeypatch.setattr(gateway, "is_idle", lambda: True)
    unsubscribe = hass.bus.async_listen("state_changed", changed)
    try:
        ready.set()
        await asyncio.wait_for(discovered.wait(), 2)
        await hass.async_block_till_done()
        entity_id = hass.states.async_all("climate")[0].entity_id
        # When a blocking HA service sends a command without a wallpad reply.
        with pytest.raises(HomeAssistantError, match="not confirmed"):
            await asyncio.wait_for(
                hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {"entity_id": entity_id, "temperature": 23},
                    blocking=True,
                ),
                1,
            )
        # Then the error reaches the service caller and one real packet was sent.
        assert len(commands) == 1
    finally:
        unsubscribe()
        assert await hass.config_entries.async_unload(entry.entry_id)
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(done.wait(), 2)
