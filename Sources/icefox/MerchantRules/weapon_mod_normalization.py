"""Normalize captured weapon-mod matches without observing items or owning caches."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from typing import cast

from Py4GWCoreLib.enums_src.Item_enums import ItemType
from Sources.icefox.MerchantRules.catalog import get_weapon_mod_type_name as _get_weapon_mod_type_name
from Sources.icefox.MerchantRules.catalog import (
    normalize_weapon_mod_component_kind as _normalize_weapon_mod_component_kind,
)
from Sources.icefox.MerchantRules.catalog import (
    normalize_weapon_mod_target_item_type as _normalize_weapon_mod_target_item_type,
)

__all__ = [
    "ParsedUpgradeMatch",
    "WEAPON_MOD_TARGET_ITEM_TYPE_MODIFIER_ID",
    "build_parsed_weapon_mod_match",
    "get_weapon_mod_variable_range",
]

WEAPON_MOD_TARGET_ITEM_TYPE_MODIFIER_ID = 9656


@dataclass(frozen=True)
class ParsedUpgradeMatch:
    identifier: str = ""
    target_item_type: str = ""
    component_kind: str = ""
    mod_type: str = ""
    value: int | None = None
    min_value: int = 0
    max_value: int = 0
    is_maxed: bool = False


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, str):
            return int(value.strip(), 0)
        return int(cast(Any, value))
    except Exception:
        return default


def _get_weapon_mod_variable_range(weapon_mod: object) -> tuple[int, int] | None:
    for modifier in getattr(weapon_mod, "modifiers", []) or []:
        value_arg = getattr(modifier, "modifier_value_arg", None)
        value_arg_name = str(getattr(value_arg, "name", value_arg) or "")
        if value_arg_name not in ("Arg1", "Arg2"):
            continue
        min_value = _safe_int(getattr(modifier, "min", 0), 0)
        max_value = _safe_int(getattr(modifier, "max", 0), 0)
        if min_value == max_value:
            continue
        if min_value > max_value:
            min_value, max_value = max_value, min_value
        return min_value, max_value
    return None


def _get_weapon_mod_component_kind_for_target(weapon_mod: object, target_item_type: object) -> str:
    safe_target_item_type = _normalize_weapon_mod_target_item_type(target_item_type)
    if not safe_target_item_type:
        return ""
    item_mods = getattr(weapon_mod, "item_mods", {}) or {}
    if not isinstance(item_mods, dict):
        return ""
    for raw_target_item_type, raw_component_kind in cast(dict[object, object], item_mods).items():
        if _normalize_weapon_mod_target_item_type(raw_target_item_type) == safe_target_item_type:
            return _normalize_weapon_mod_component_kind(raw_component_kind)
    return ""


def _get_weapon_mod_target_item_type_from_raw_modifiers(raw_modifiers: object) -> str:
    for raw_modifier in cast(Iterable[Any], raw_modifiers or ()):
        try:
            identifier, arg1, _arg2 = raw_modifier
        except Exception:
            continue
        if _safe_int(identifier, 0) != WEAPON_MOD_TARGET_ITEM_TYPE_MODIFIER_ID:
            continue
        return _normalize_weapon_mod_target_item_type(arg1)
    return ""


def _resolve_parsed_weapon_mod_variant_context(
    match: object,
    raw_modifiers: object,
    item_type_enum: ItemType,
    parse_item_type: ItemType,
) -> tuple[str, str, str]:
    weapon_mod = getattr(match, "weapon_mod", None)
    mod_type_name = _get_weapon_mod_type_name(match) or _get_weapon_mod_type_name(weapon_mod)
    if weapon_mod is None:
        return "", "", mod_type_name

    if item_type_enum == ItemType.Rune_Mod:
        target_item_type = _get_weapon_mod_target_item_type_from_raw_modifiers(raw_modifiers)
    else:
        target_item_type = _normalize_weapon_mod_target_item_type(parse_item_type)

    component_kind = _get_weapon_mod_component_kind_for_target(weapon_mod, target_item_type)
    if not component_kind:
        return "", "", mod_type_name
    return target_item_type, component_kind, mod_type_name


def _build_parsed_weapon_mod_match(
    match: object,
    *,
    raw_modifiers: object = (),
    item_type_enum: ItemType = ItemType.Unknown,
    parse_item_type: ItemType = ItemType.Unknown,
) -> ParsedUpgradeMatch | None:
    weapon_mod = getattr(match, "weapon_mod", None)
    identifier = str(getattr(weapon_mod, "identifier", "") or "").strip()
    if not identifier:
        return None
    range_values = _get_weapon_mod_variable_range(weapon_mod)
    raw_value = getattr(match, "value", None) if hasattr(match, "value") else None
    parsed_value = None if raw_value is None else _safe_int(raw_value, 0)
    target_item_type, component_kind, mod_type = _resolve_parsed_weapon_mod_variant_context(
        match,
        raw_modifiers,
        item_type_enum,
        parse_item_type,
    )
    return ParsedUpgradeMatch(
        identifier=identifier,
        target_item_type=target_item_type,
        component_kind=component_kind,
        mod_type=mod_type,
        value=parsed_value,
        min_value=int(range_values[0]) if range_values is not None else 0,
        max_value=int(range_values[1]) if range_values is not None else 0,
        is_maxed=bool(getattr(match, "is_maxed", False)),
    )


build_parsed_weapon_mod_match = _build_parsed_weapon_mod_match
get_weapon_mod_variable_range = _get_weapon_mod_variable_range
