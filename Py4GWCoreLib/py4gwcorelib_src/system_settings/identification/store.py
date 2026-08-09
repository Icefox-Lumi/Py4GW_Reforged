"""Account-scoped Identification settings; Factory rules/profiles remain global owners."""

from .model import IdentificationConfig, RARITIES


_INI = "Widgets/System/Identification.ini"
_LEGACY_INI = "Inventory/InventoryPlus/InventoryPlus.ini"


def _settings():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        return Settings(_INI, "account")
    except Exception:
        return None


def load() -> tuple[IdentificationConfig, bool]:
    config = IdentificationConfig()
    settings = _settings()
    if settings is None:
        return config, False
    migrated = settings.get_bool("migration", "from_inventory_plus", False)
    if migrated:
        config.auto_enabled = settings.get_bool("general", "auto_enabled", False)
        config.interval_ms = max(1000, settings.get_int("general", "interval_ms", 15000))
        for rarity in RARITIES:
            key = rarity.lower()
            config.auto_rarities[rarity] = settings.get_bool("automatic", key, config.auto_rarities[rarity])
            config.menu_rarities[rarity] = settings.get_bool("menu", key, config.menu_rarities[rarity])
            config.menu_all_rarities[rarity] = settings.get_bool("menu_all", key, config.menu_all_rarities[rarity])
        config.menu_identify_all = settings.get_bool("menu", "identify_all", False)
        config.menu_identify_single = settings.get_bool("menu", "identify_single", True)
        return config, False
    return _load_legacy(), True


def _load_legacy() -> IdentificationConfig:
    config = IdentificationConfig()
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        settings = Settings(_LEGACY_INI, "global")
        config.auto_enabled = settings.get_bool("AutoManager", "module_active", False)
        config.interval_ms = max(1000, settings.get_int("AutoManager", "lookup_time", 15000))
        for rarity in RARITIES:
            key = rarity.lower()
            config.menu_rarities[rarity] = settings.get_bool("Identification", "identify_%ss" % key, False)
            config.menu_all_rarities[rarity] = settings.get_bool("Identification", "identify_all_%ss" % key, False)
            config.auto_rarities[rarity] = settings.get_bool("AutoIdentify", "id_%ss" % key,
                                                              config.auto_rarities[rarity])
        config.menu_identify_all = settings.get_bool("Identification", "show_identify_all", False)
    except Exception:
        pass
    return config


def legacy_model_blacklist() -> list[int]:
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        raw = Settings(_LEGACY_INI, "global").get_str("AutoIdentify", "id_model_blacklist", "")
        return [int(value) for value in raw.split(",") if value.strip().isdigit()]
    except Exception:
        return []


def save(config: IdentificationConfig, migrated: bool = True) -> None:
    settings = _settings()
    if settings is None:
        return
    settings.set("migration", "from_inventory_plus", bool(migrated))
    settings.set("general", "auto_enabled", bool(config.auto_enabled))
    settings.set("general", "interval_ms", max(1000, int(config.interval_ms)))
    for rarity in RARITIES:
        key = rarity.lower()
        settings.set("automatic", key, bool(config.auto_rarities.get(rarity, False)))
        settings.set("menu", key, bool(config.menu_rarities.get(rarity, False)))
        settings.set("menu_all", key, bool(config.menu_all_rarities.get(rarity, False)))
    settings.set("menu", "identify_all", bool(config.menu_identify_all))
    settings.set("menu", "identify_single", bool(config.menu_identify_single))
