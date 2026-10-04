"""Device-specific options without changing existing installation defaults."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow


class KocomOptionsFlow(OptionsFlow):
    """Select an optional thermostat UI step override."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        schema = vol.Schema(
            {
                vol.Optional(
                    "thermostat_step",
                    default=self.config_entry.options.get("thermostat_step", "auto"),
                ): vol.In(["auto", "1"]),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
