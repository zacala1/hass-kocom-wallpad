"""Exercise option forms with real voluptuous schemas and a narrow HA shim."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import voluptuous as vol

import ha_shims  # noqa: F401


class _OptionsFlow:
    """Expose only the result methods used by this option handler."""

    def async_show_form(self, **kwargs):
        return kwargs

    def async_create_entry(self, **kwargs):
        return kwargs


config_entries = sys.modules["homeassistant.config_entries"]
config_entries.OptionsFlow = _OptionsFlow
config_entries.ConfigFlowResult = dict

from custom_components.kocom_wallpad.options_flow import KocomOptionsFlow


class OptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_is_auto(self) -> None:
        flow = KocomOptionsFlow()
        flow.config_entry = SimpleNamespace(options={})
        form = await flow.async_step_init()
        self.assertEqual({"thermostat_step": "auto"}, form["data_schema"]({}))

    async def test_existing_override_is_preserved(self) -> None:
        flow = KocomOptionsFlow()
        flow.config_entry = SimpleNamespace(options={"thermostat_step": "1"})
        form = await flow.async_step_init()
        self.assertEqual({"thermostat_step": "1"}, form["data_schema"]({}))
        with self.assertRaises(vol.Invalid):
            form["data_schema"]({"thermostat_step": "0.5"})

    async def test_selected_value_is_saved(self) -> None:
        flow = KocomOptionsFlow()
        flow.async_create_entry = Mock(return_value={"result": "saved"})
        self.assertEqual({"result": "saved"}, await flow.async_step_init({"thermostat_step": "1"}))
        flow.async_create_entry.assert_called_once_with(title="", data={"thermostat_step": "1"})
