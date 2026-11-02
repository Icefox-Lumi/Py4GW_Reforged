"""Shared scalar conversions for Merchant Rules evidence and protection."""

from typing import SupportsIndex
from typing import SupportsInt
from typing import cast

MAX_WEAPON_REQUIREMENT = 13


def safe_int(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, str):
            return int(value.strip(), 0)
        return int(cast("SupportsInt | SupportsIndex | bytes | bytearray", value))
    except Exception:
        return default


def dedupe_identifiers(values: list[object]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        identifier = str(value or "").strip()
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        unique.append(identifier)
    return unique


def normalize_weapon_requirement_level(value: object) -> int:
    return min(MAX_WEAPON_REQUIREMENT, max(0, safe_int(value, 0)))
