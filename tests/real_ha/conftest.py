"""Real HA fixtures kept isolated from the offline regression shims."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest_asyncio
from homeassistant.core import HomeAssistant
from homeassistant.loader import DATA_CUSTOM_COMPONENTS
from pytest_homeassistant_custom_component.common import async_test_home_assistant


@pytest_asyncio.fixture
async def hass(tmp_path: Path) -> AsyncGenerator[HomeAssistant]:
    """Use the core's real test instance without its Linux-only runner plugin."""
    async with async_test_home_assistant(config_dir=str(tmp_path)) as instance:
        instance.data.pop(DATA_CUSTOM_COMPONENTS)
        yield instance
