"""Command failures name the cause the user can act on, in the user's language."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import translation
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.gateway import KocomGateway
from custom_components.kocom_wallpad.light import KocomLight
from custom_components.kocom_wallpad.models import DeviceKey, DeviceState

LIGHT = DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE)
ALL_OFF = DeviceKey(DeviceType.LIGHTCUTOFF, 0, 0, SubType.NONE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connected", "expected"),
    [(False, "not_connected"), (True, "command_not_confirmed")],
)
async def test_failed_command_names_the_lost_link_or_the_silent_device(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *,
    connected: bool,
    expected: str,
) -> None:
    # Given a command the gateway could not complete, with the link up or down.
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    gateway.conn._set_connected(connected=connected)
    monkeypatch.setattr(gateway, "async_send_action", AsyncMock(return_value=False))
    light = KocomLight(gateway, DeviceState(LIGHT, Platform.LIGHT, {}, True))
    # When the light is switched.
    with pytest.raises(HomeAssistantError) as raised:
        await light.async_turn_on()
    # Then the error carries a translatable key that tells the two cases apart.
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == expected


@pytest.mark.asyncio
async def test_all_off_signal_error_is_translatable(hass: HomeAssistant) -> None:
    gateway = KocomGateway(hass, MockConfigEntry(domain=DOMAIN), "wallpad", 8899)
    light = KocomLight(gateway, DeviceState(ALL_OFF, Platform.LIGHT, {}, True))
    with pytest.raises(HomeAssistantError) as raised:
        await light.async_turn_off()
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "all_off_state_only"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "needle"),
    [("en", "did not confirm"), ("ko", "확인하지 않았습니다")],
)
async def test_home_assistant_resolves_every_message_in_both_languages(
    hass: HomeAssistant, language: str, needle: str
) -> None:
    # When Home Assistant loads the integration's error texts.
    texts = await translation.async_get_translations(
        hass, language, "exceptions", {DOMAIN}
    )
    # Then each key the code can raise has a message, and the language is right.
    prefix = f"component.{DOMAIN}.exceptions."
    resolved = {
        key.removeprefix(prefix).removesuffix(".message"): text
        for key, text in texts.items()
        if key.startswith(prefix)
    }
    assert set(resolved) == {
        "command_not_confirmed",
        "not_connected",
        "all_off_state_only",
    }
    assert needle in resolved["command_not_confirmed"]
    assert all(text.strip() for text in resolved.values())
