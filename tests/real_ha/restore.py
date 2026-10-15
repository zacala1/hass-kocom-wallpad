"""Seed and read Home Assistant's saved entity states on every supported version."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state
from homeassistant.helpers.restore_state import StoredState


def seed(hass: HomeAssistant, stored: StoredState) -> None:
    """Save a state as if the entity had stored it before the restart."""
    data = restore_state.async_get(hass)
    entity_id = stored.state.entity_id
    if hasattr(data, "last_states_by_entity_registry_id"):
        # 2026.11 and later: states of registered entities follow the registry id.
        registry_entry = er.async_get(hass).async_get(entity_id)
        if registry_entry is None:
            data.last_states_by_entity_id[entity_id] = stored
        else:
            stored.entity_registry_id = registry_entry.id
            data.last_states_by_entity_registry_id[registry_entry.id] = stored
    else:
        data.last_states[entity_id] = stored


def stored(hass: HomeAssistant, entity_id: str) -> StoredState | None:
    """Read the saved state of an entity, however this version indexes it."""
    data = restore_state.async_get(hass)
    getter = getattr(data, "async_get_stored_state", None)
    return getter(entity_id) if getter is not None else data.last_states.get(entity_id)
