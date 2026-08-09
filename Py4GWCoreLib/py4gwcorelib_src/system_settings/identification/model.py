"""Pure persisted configuration for the standalone Identification feature."""

from dataclasses import dataclass, field


RARITIES: tuple[str, ...] = ("White", "Blue", "Green", "Purple", "Gold")


def _rarities(defaults: dict[str, bool]) -> dict[str, bool]:
    return dict(defaults)


@dataclass
class IdentificationConfig:
    auto_enabled: bool = False
    interval_ms: int = 15000
    auto_rarities: dict[str, bool] = field(default_factory=lambda: _rarities({
        "White": False, "Blue": True, "Green": False, "Purple": True, "Gold": False,
    }))
    menu_rarities: dict[str, bool] = field(default_factory=lambda: _rarities({
        "White": False, "Blue": False, "Green": False, "Purple": False, "Gold": False,
    }))
    menu_identify_all: bool = False
    menu_all_rarities: dict[str, bool] = field(default_factory=lambda: _rarities({
        "White": False, "Blue": False, "Green": False, "Purple": False, "Gold": False,
    }))
    menu_identify_single: bool = True
