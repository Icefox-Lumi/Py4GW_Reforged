"""Account-scoped persistence for Item Profiles and the legacy Colorize import."""

import ast

from .model import ColorizeProfile, ItemProfile, RARITIES


_DOC = "Widgets/System/InventoryProfiles.json"
_LEGACY_INI = "Inventory/InventoryPlus/InventoryPlus.ini"


def _json():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

        return JsonFactory(_DOC, "account")
    except Exception:
        return None


def _legacy_colorize() -> ColorizeProfile | None:
    """Read legacy Colorize once when no Item Profile document exists yet."""
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        settings = Settings(_LEGACY_INI, "global")
        profile = ColorizeProfile(
            enabled=settings.get_bool("Colorize", "enable_colorize", False),
            imgui_frame=True,
            imgui_outline=True,
            rarities={
                "White": settings.get_bool("Colorize", "color_whites", False),
                "Blue": settings.get_bool("Colorize", "color_blues", True),
                "Green": settings.get_bool("Colorize", "color_greens", True),
                "Purple": settings.get_bool("Colorize", "color_purples", True),
                "Gold": settings.get_bool("Colorize", "color_golds", True),
            },
        )
        for rarity in RARITIES:
            raw = settings.get_str("Colorize", "%s_color" % rarity.lower(), "")
            if not raw:
                continue
            try:
                values = [int(value) for value in ast.literal_eval(raw)]
                if len(values) == 4:
                    red, green, blue, alpha = (max(0, min(255, value)) for value in values)
                    profile.colors[rarity] = (red, green, blue, alpha)
            except (TypeError, ValueError, SyntaxError):
                pass
        return profile
    except Exception:
        return None


def load() -> tuple[str, list[ItemProfile], bool]:
    """Return ``(active_name, profiles, imported_legacy_colorize)``."""
    doc = _json()
    if doc is None:
        return "Default", [ItemProfile()], False
    raw_profiles = doc.get_json("profiles", [])
    if not isinstance(raw_profiles, list) or not raw_profiles:
        colorize = _legacy_colorize()
        profile = ItemProfile(colorize=colorize or ColorizeProfile())
        save("Default", [profile], migrated_legacy=colorize is not None)
        return "Default", [profile], colorize is not None
    profiles = [ItemProfile.from_dict(raw) for raw in raw_profiles if isinstance(raw, dict)] or [ItemProfile()]
    active = str(doc.get_json("active_profile", profiles[0].name))
    if active not in {profile.name for profile in profiles}:
        active = profiles[0].name
    return active, profiles, False


def save(active_name: str, profiles: list[ItemProfile], migrated_legacy: bool = True) -> None:
    doc = _json()
    if doc is not None:
        doc.set_json("active_profile", str(active_name))
        doc.set_json("profiles", [profile.to_dict() for profile in profiles])
        doc.set_json("migrated_from_inventory_plus", bool(migrated_legacy))
