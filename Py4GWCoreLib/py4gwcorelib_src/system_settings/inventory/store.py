"""Global persistence for the remaining independent item-feature settings."""

import ast

from .model import ColorizeSettings, InventoryFeatureSettings, RARITIES

_DOC = "Widgets/System/InventoryFeatures.json"
_LEGACY_INI = "Inventory/InventoryPlus/InventoryPlus.ini"


def _json():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

        return JsonFactory(_DOC, "global")
    except Exception:
        return None


def _legacy_colorize() -> ColorizeSettings | None:
    """Import the legacy InventoryPlus Colorize state from its INI document.

    Restores the pre-bridge-relocation behavior where the System Settings
    Colorize feature seeded itself from InventoryPlus on first bind.
    """
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        ini = Settings(_LEGACY_INI, "global")
        colorize = ColorizeSettings(
            enabled=ini.get_bool("Colorize", "enable_colorize", False),
            imgui_frame=True,
            imgui_outline=True,
            rarities={
                "White": ini.get_bool("Colorize", "color_whites", False),
                "Blue": ini.get_bool("Colorize", "color_blues", True),
                "Green": ini.get_bool("Colorize", "color_greens", True),
                "Purple": ini.get_bool("Colorize", "color_purples", True),
                "Gold": ini.get_bool("Colorize", "color_golds", True),
            },
        )
        for rarity in RARITIES:
            raw = ini.get_str("Colorize", "%s_color" % rarity.lower(), "")
            if not raw:
                continue
            try:
                values = [int(value) for value in ast.literal_eval(raw)]
                if len(values) == 4:
                    red, green, blue, alpha = (max(0, min(255, value)) for value in values)
                    colorize.colors[rarity] = (red, green, blue, alpha)
            except (TypeError, ValueError, SyntaxError):
                pass
        return colorize
    except Exception:
        return None


def load() -> InventoryFeatureSettings:
    document = _json()
    raw = document.get_json("settings", {}) if document is not None else {}
    if isinstance(raw, dict) and raw:
        settings = InventoryFeatureSettings.from_dict(raw)
        # Heal state persisted by the earlier bug that wrote every rarity as
        # disabled: restore the legacy InventoryPlus selection once.
        if settings.colorize.enabled and not any(settings.colorize.rarities.values()):
            legacy = _legacy_colorize()
            if legacy is not None and any(legacy.rarities.values()):
                settings.colorize.rarities = legacy.rarities
                settings.colorize.colors = legacy.colors
                if document is not None:
                    document.set_json("settings", settings.to_dict())
        return settings
    legacy = _legacy_colorize()
    settings = InventoryFeatureSettings(colorize=legacy or ColorizeSettings())
    if legacy is not None and document is not None:
        document.set_json("settings", settings.to_dict())
    return settings


def save(settings: InventoryFeatureSettings) -> None:
    document = _json()
    if document is not None:
        document.set_json("settings", settings.to_dict())
