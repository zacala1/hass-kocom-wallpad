"""A frame we sent that comes straight back is an echo, never a device report."""

import time

import pytest
from frames import Emulator, controller_with, frame, wait_until
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.kocom_wallpad.controller as controller_module
from custom_components.kocom_wallpad.const import DOMAIN, DeviceType, SubType
from custom_components.kocom_wallpad.models import DeviceKey

LIGHT = DeviceKey(DeviceType.LIGHT, 1, 0, SubType.NONE)
LIGHT_ON = frame(0x0E, 1, 0x00, b"\xff" + bytes(7))


def turn_off_frame(controller: controller_module.KocomController) -> bytes:
    packet, _expectation, _timeout = controller.generate_command(LIGHT, "turn_off")
    return packet


def test_an_unannounced_copy_of_the_command_is_processed() -> None:
    # Without a transmission on record, the same bytes are a real frame.
    controller, registry = controller_with(LIGHT_ON)
    controller.feed(turn_off_frame(controller))
    assert registry.get(LIGHT).state is False
    assert controller.diagnostics_snapshot()["stats"]["echoed"] == 0


def test_the_echo_of_a_sent_frame_is_ignored() -> None:
    controller, registry = controller_with(LIGHT_ON)
    packet = turn_off_frame(controller)
    controller.note_transmitted(packet)
    controller.feed(packet)
    # The light keeps its state: our own command is not evidence that it changed.
    assert registry.get(LIGHT).state is True
    assert controller.diagnostics_snapshot()["stats"]["echoed"] == 1


def test_a_device_reply_is_not_mistaken_for_an_echo() -> None:
    controller, registry = controller_with(LIGHT_ON)
    controller.note_transmitted(turn_off_frame(controller))
    controller.feed(frame(0x0E, 1, 0x00, bytes(8)))  # the light's own report
    assert registry.get(LIGHT).state is False
    assert controller.diagnostics_snapshot()["stats"]["echoed"] == 0


def test_each_transmission_explains_only_one_received_frame() -> None:
    controller, registry = controller_with(LIGHT_ON)
    packet = turn_off_frame(controller)
    controller.note_transmitted(packet)
    controller.note_transmitted(packet)
    controller.feed(packet + packet)
    assert registry.get(LIGHT).state is True
    controller.feed(packet)  # a third copy has no transmission behind it
    assert registry.get(LIGHT).state is False
    assert controller.diagnostics_snapshot()["stats"]["echoed"] == 2


def test_an_old_transmission_no_longer_explains_a_frame() -> None:
    controller, registry = controller_with(LIGHT_ON)
    packet = turn_off_frame(controller)
    controller.note_transmitted(packet)
    controller._sent[0] = (packet, time.monotonic() - 60)
    controller.feed(packet)
    assert registry.get(LIGHT).state is False
    assert controller.diagnostics_snapshot()["stats"]["echoed"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [False, True])
async def test_an_echoing_adapter_cannot_confirm_a_command(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, *, reply: bool
) -> None:
    # Given an adapter that hears its own transmission, and a wallpad that either
    # stays silent or answers with the light's real report.
    monkeypatch.setattr(controller_module, "CMD_CONFIRM_TIMEOUT", 0.1)

    def respond(packet: bytes) -> list[bytes]:
        answers = [packet]
        if reply:
            answers.append(frame(0x0E, 1, 0x00, packet[10:18]))
        return answers

    async with Emulator(respond) as wallpad:
        entry = MockConfigEntry(
            domain=DOMAIN, data={"host": "127.0.0.1", "port": wallpad.port}
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        try:
            await wallpad.send(LIGHT_ON)
            await wait_until(lambda: len(hass.states.async_all("light")) == 1)
            entity_id = hass.states.async_all("light")[0].entity_id
            assert hass.states.get(entity_id).state == "on"
            # When the light is switched off.
            turn_off = hass.services.async_call(
                "light", "turn_off", {"entity_id": entity_id}, blocking=True
            )
            if reply:
                await turn_off
            else:
                # Then the echo alone does not count as the wallpad's answer.
                with pytest.raises(HomeAssistantError):
                    await turn_off
            await hass.async_block_till_done()
            assert hass.states.get(entity_id).state == ("off" if reply else "on")
            gateway = hass.data[DOMAIN][entry.entry_id]
            assert gateway.controller.diagnostics_snapshot()["stats"]["echoed"] >= 1
        finally:
            assert await hass.config_entries.async_unload(entry.entry_id)
