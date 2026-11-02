"""Settings-backed persistence for travel-on-character-load."""

from .model import TravelOnCharacterLoadConfig


_DOCUMENT = "Widgets/System/Travel On Character Load.ini"
_SECTION = "Travel On Character Load"


def _settings():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        return Settings(_DOCUMENT, "account")
    except Exception:
        return None


def local_is_ready() -> bool:
    settings = _settings()
    if settings is None:
        return False
    try:
        return settings.is_ready()
    except Exception:
        return False


def load() -> TravelOnCharacterLoadConfig:
    config = TravelOnCharacterLoadConfig()
    settings = _settings()
    if settings is None:
        return config

    config.travel_on_first_load = settings.get_bool(_SECTION, "travel_on_first_load", config.travel_on_first_load)
    config.travel_on_character_switch = settings.get_bool(
        _SECTION, "travel_on_character_switch", config.travel_on_character_switch
    )
    config.destination = settings.get_str(_SECTION, "destination", config.destination)
    config.outpost_id = settings.get_int(_SECTION, "outpost_id", config.outpost_id)
    return config


def save(config: TravelOnCharacterLoadConfig) -> None:
    settings = _settings()
    if settings is None:
        return

    settings.set(_SECTION, "travel_on_first_load", config.travel_on_first_load)
    settings.set(_SECTION, "travel_on_character_switch", config.travel_on_character_switch)
    settings.set(_SECTION, "destination", config.destination)
    settings.set(_SECTION, "outpost_id", config.outpost_id)
