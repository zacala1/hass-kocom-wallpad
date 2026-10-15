"""icons.json and the two translation files stay consistent with the entities."""

import json
import re
from pathlib import Path

import pytest

import custom_components.kocom_wallpad as kocom_wallpad

# The package may be the repository tree or an extracted release archive.
PACKAGE = Path(str(kocom_wallpad.__file__)).parent
ICON = re.compile(r"^mdi:[a-z0-9]+(-[a-z0-9]+)*$")


def load(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def leaves(node: object, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Every key path that ends in a text, to compare the two languages."""
    if isinstance(node, dict):
        return {leaf for key, item in node.items() for leaf in leaves(item, (*path, key))}
    return {path}


def test_korean_and_english_translate_exactly_the_same_things() -> None:
    english, korean = load("translations/en.json"), load("translations/ko.json")
    assert leaves(english) == leaves(korean)


def test_every_translation_text_is_filled_in() -> None:
    for language in ("en", "ko"):
        empty = [
            path
            for path in leaves(load(f"translations/{language}.json"))
            if not _text_at(load(f"translations/{language}.json"), path).strip()
        ]
        assert empty == [], f"{language}: empty texts {empty}"


def _text_at(node: dict, path: tuple[str, ...]) -> str:
    for key in path:
        node = node[key]
    return str(node)


def test_retired_option_and_light_names_are_gone_from_translations() -> None:
    for language in ("en", "ko"):
        data = load(f"translations/{language}.json")
        assert "options" not in data
        assert "dimminglight" not in data["entity"]["light"]


def test_icons_belong_to_real_entities_and_are_material_design_icons() -> None:
    icons, names = load("icons.json"), load("translations/en.json")["entity"]
    assert set(icons) == {"entity"}
    for platform, keys in icons["entity"].items():
        for key, spec in keys.items():
            # A typo in a key would silently show no icon, so tie each to a name.
            assert key in names.get(platform, {}), f"{platform}.{key} is not an entity"
            states = spec.get("state", {})
            for icon in (spec["default"], *states.values()):
                assert ICON.match(icon), f"{platform}.{key}: bad icon {icon!r}"
            # An icon equal to the default is noise (hassfest calls it removable).
            assert spec["default"] not in states.values(), f"{platform}.{key}"


@pytest.mark.parametrize(
    ("platform", "key", "state", "icon"),
    [
        ("sensor", "elevator-direction", "upward", "mdi:elevator-up"),
        ("sensor", "elevator-direction", "downward", "mdi:elevator-down"),
        ("fan", "ventilation", "off", "mdi:hvac-off"),
    ],
)
def test_state_icons_use_the_exact_state_names_the_entities_report(
    platform: str, key: str, state: str, icon: str
) -> None:
    assert load("icons.json")["entity"][platform][key]["state"][state] == icon
