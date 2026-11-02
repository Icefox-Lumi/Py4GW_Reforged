"""Evaluate requirement and perfect-base policy using the caller's lazy lookups.

Scalar readers preserve widget-method resolution before argument evaluation.
"""

from collections.abc import Callable
from collections.abc import Sequence
from typing import Protocol
from typing import TypeVar

from Py4GWCoreLib.enums_src.Item_enums import ItemType
from Sources.icefox.MerchantRules.item_values import MAX_WEAPON_REQUIREMENT as MAX_WEAPON_REQUIREMENT
from Sources.icefox.MerchantRules.item_values import (
    normalize_weapon_requirement_level as normalize_weapon_requirement_level,
)
from Sources.icefox.MerchantRules.item_values import safe_int as _safe_int

ATTRIBUTE_NONE_REAL_VALUE = 45

PERFECT_BASE_DAMAGE_RANGES: dict[int, tuple[int, int]] = {
    int(ItemType.Sword): (15, 22),
    int(ItemType.Axe): (6, 28),
    int(ItemType.Hammer): (19, 35),
    int(ItemType.Bow): (15, 28),
    int(ItemType.Daggers): (7, 17),
    int(ItemType.Scythe): (9, 41),
    int(ItemType.Spear): (14, 27),
    int(ItemType.Wand): (11, 22),
    int(ItemType.Staff): (11, 22),
}
PERFECT_BASE_ENERGY_VALUES: dict[int, int] = {
    int(ItemType.Staff): 10,
    int(ItemType.Offhand): 12,
}
PERFECT_BASE_ARMOR_VALUES: dict[int, int] = {
    int(ItemType.Shield): 16,
}
PERFECT_BASE_ITEM_TYPE_LABELS: dict[int, str] = {
    int(ItemType.Offhand): "Focus",
    int(ItemType.Shield): "Shield",
    int(ItemType.Staff): "Staff",
    int(ItemType.Wand): "Wand",
    int(ItemType.Sword): "Sword",
    int(ItemType.Axe): "Axe",
    int(ItemType.Hammer): "Hammer",
    int(ItemType.Bow): "Bow",
    int(ItemType.Daggers): "Daggers",
    int(ItemType.Scythe): "Scythe",
    int(ItemType.Spear): "Spear",
}


class _RequirementItem(Protocol):
    @property
    def model_id(self) -> int: ...

    @property
    def item_type_id(self) -> int: ...

    @property
    def is_weapon_like(self) -> bool: ...

    @property
    def standalone_kind(self) -> str: ...

    @property
    def identified(self) -> bool: ...

    @property
    def requirement(self) -> int: ...

    @property
    def requirement_attribute_id(self) -> int: ...

    @property
    def requirement_attribute_name(self) -> str: ...

    @property
    def damage_min(self) -> int: ...

    @property
    def damage_max(self) -> int: ...

    @property
    def energy(self) -> int: ...

    @property
    def armor(self) -> int: ...


class _RequirementRow(Protocol):
    @property
    def model_id(self) -> int: ...

    @property
    def min_requirement(self) -> int: ...

    @property
    def max_requirement(self) -> int: ...

    @property
    def perfect_stats_only(self) -> bool: ...


class _RequirementRule(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def protected_weapon_requirement_rules(self) -> Sequence[_RequirementRow]: ...

    @property
    def all_weapons_min_requirement(self) -> int: ...

    @property
    def all_weapons_max_requirement(self) -> int: ...

    @property
    def all_weapons_perfect_stats_only(self) -> bool: ...


_ItemT = TypeVar("_ItemT", bound=_RequirementItem)


def normalize_weapon_requirement_range(min_value: object, max_value: object) -> tuple[int, int]:
    min_requirement = normalize_weapon_requirement_level(min_value)
    max_requirement = normalize_weapon_requirement_level(max_value)
    if min_requirement > 0 and max_requirement > 0 and min_requirement > max_requirement:
        min_requirement, max_requirement = max_requirement, min_requirement
    return min_requirement, max_requirement


def has_real_requirement_attribute(item: _RequirementItem) -> bool:
    attribute_name = str(getattr(item, "requirement_attribute_name", "") or "").strip()
    if attribute_name and attribute_name.lower() not in ("none", "none_"):
        return True
    attribute_id = _safe_int(getattr(item, "requirement_attribute_id", 0), 0)
    return attribute_id > 0 and attribute_id != ATTRIBUTE_NONE_REAL_VALUE


def get_item_requirement_attribute_label(item: _RequirementItem) -> str:
    attribute_name = str(getattr(item, "requirement_attribute_name", "") or "").strip()
    if attribute_name.lower() in ("none", "none_"):
        return ""
    if attribute_name:
        return attribute_name
    attribute_id = _safe_int(getattr(item, "requirement_attribute_id", 0), 0)
    if attribute_id <= 0 or attribute_id == ATTRIBUTE_NONE_REAL_VALUE:
        return ""
    return f"Attribute {attribute_id}"


def is_weapon_requirement_range_active(min_requirement: object, max_requirement: object) -> bool:
    normalized_min, normalized_max = normalize_weapon_requirement_range(min_requirement, max_requirement)
    return normalized_min > 0 and normalized_max > 0


def _get_perfect_base_spec(item: _RequirementItem) -> tuple[tuple[int, int] | None, int, int]:
    item_type_id = int(getattr(item, "item_type_id", 0))
    return (
        PERFECT_BASE_DAMAGE_RANGES.get(item_type_id),
        max(0, int(PERFECT_BASE_ENERGY_VALUES.get(item_type_id, 0))),
        max(0, int(PERFECT_BASE_ARMOR_VALUES.get(item_type_id, 0))),
    )


def _is_perfect_base_candidate_type(item: _RequirementItem) -> bool:
    item_type_id = int(getattr(item, "item_type_id", 0))
    return bool(
        item_type_id in PERFECT_BASE_DAMAGE_RANGES
        or item_type_id in PERFECT_BASE_ENERGY_VALUES
        or item_type_id in PERFECT_BASE_ARMOR_VALUES
    )


def _get_perfect_base_unavailable_reason(item: _RequirementItem, *, weapon_mod_standalone_kind: str) -> str:
    if bool(getattr(item, "identified", False)):
        return ""
    if not bool(getattr(item, "is_weapon_like", False)):
        return ""
    if str(getattr(item, "standalone_kind", "") or "") == weapon_mod_standalone_kind:
        return ""
    if not _is_perfect_base_candidate_type(item):
        return ""

    expected_damage, expected_energy, expected_armor = _get_perfect_base_spec(item)
    if normalize_weapon_requirement_level(getattr(item, "requirement", 0)) <= 0:
        return "Protected until identified: perfect-base stats unavailable."
    if not has_real_requirement_attribute(item):
        return "Protected until identified: perfect-base stats unavailable."
    if expected_damage is not None and (
        max(0, _safe_int(getattr(item, "damage_min", 0), 0)) <= 0
        or max(0, _safe_int(getattr(item, "damage_max", 0), 0)) <= 0
    ):
        return "Protected until identified: perfect-base stats unavailable."
    if expected_energy > 0 and max(0, _safe_int(getattr(item, "energy", 0), 0)) <= 0:
        return "Protected until identified: perfect-base stats unavailable."
    if expected_armor > 0 and max(0, _safe_int(getattr(item, "armor", 0), 0)) <= 0:
        return "Protected until identified: perfect-base stats unavailable."
    return ""


def _format_perfect_base_stats(item: _RequirementItem) -> str:
    item_type_id = int(getattr(item, "item_type_id", 0))
    parts: list[str] = []
    damage = PERFECT_BASE_DAMAGE_RANGES.get(item_type_id)
    if damage is not None:
        parts.append(f"{damage[0]}-{damage[1]}")
    energy = max(0, int(PERFECT_BASE_ENERGY_VALUES.get(item_type_id, 0)))
    if energy > 0:
        parts.append(f"Energy +{energy}")
    armor = max(0, int(PERFECT_BASE_ARMOR_VALUES.get(item_type_id, 0)))
    if armor > 0:
        parts.append(f"Armor {armor}")
    return ", ".join(parts)


def _get_perfect_base_range_hit_reason(
    item: _ItemT,
    min_requirement: int,
    max_requirement: int,
    *,
    source: str,
    weapon_mod_standalone_kind: str,
    item_label: Callable[[_ItemT], str],
    item_type_label: Callable[[Callable[[], int]], str],
) -> str:
    if not bool(getattr(item, "is_weapon_like", False)):
        return ""
    if str(getattr(item, "standalone_kind", "") or "") == weapon_mod_standalone_kind:
        return ""
    if not _is_perfect_base_candidate_type(item):
        return ""

    requirement = normalize_weapon_requirement_level(getattr(item, "requirement", 0))
    if requirement > 0 and not (min_requirement <= requirement <= max_requirement):
        return ""

    unavailable_reason = _get_perfect_base_unavailable_reason(
        item, weapon_mod_standalone_kind=weapon_mod_standalone_kind
    )
    if unavailable_reason:
        return unavailable_reason

    if requirement <= 0 or not has_real_requirement_attribute(item):
        return ""
    if not (min_requirement <= requirement <= max_requirement):
        return ""

    expected_damage, expected_energy, expected_armor = _get_perfect_base_spec(item)
    if expected_damage is not None:
        actual_damage = (
            max(0, _safe_int(getattr(item, "damage_min", 0), 0)),
            max(0, _safe_int(getattr(item, "damage_max", 0), 0)),
        )
        if actual_damage != expected_damage:
            return ""
    if expected_energy > 0 and max(0, _safe_int(getattr(item, "energy", 0), 0)) != expected_energy:
        return ""
    if expected_armor > 0 and max(0, _safe_int(getattr(item, "armor", 0), 0)) != expected_armor:
        return ""

    if source == "model":
        label = item_label(item)
        prefix = "model"
    else:
        label = PERFECT_BASE_ITEM_TYPE_LABELS.get(
            int(getattr(item, "item_type_id", 0)),
            item_type_label(lambda: int(getattr(item, "item_type_id", 0))),
        )
        prefix = "all-weapons"
    stats = _format_perfect_base_stats(item)
    attribute_label = get_item_requirement_attribute_label(item)
    attribute_suffix = f" {attribute_label}" if attribute_label else ""
    return f"Protected by {prefix} perfect-base range: {label} {stats}, req {requirement}{attribute_suffix}."


def get_perfect_only_unidentified_hold_reason(
    item: _ItemT,
    rule: _RequirementRule,
    *,
    weapon_rule_kind: str,
    weapon_mod_standalone_kind: str,
    should_fall_back_to_global: Callable[[Callable[[], object]], bool],
    item_label: Callable[[_ItemT], str],
    item_type_label: Callable[[Callable[[], int]], str],
) -> str:
    if rule.kind != weapon_rule_kind or bool(getattr(item, "identified", False)):
        return ""
    if not bool(getattr(item, "is_weapon_like", False)):
        return ""
    if str(getattr(item, "standalone_kind", "") or "") == weapon_mod_standalone_kind:
        return ""

    has_model_requirement_range = False
    for requirement_rule in rule.protected_weapon_requirement_rules:
        if item.model_id != int(requirement_rule.model_id):
            continue
        min_requirement, max_requirement = normalize_weapon_requirement_range(
            getattr(requirement_rule, "min_requirement", 0),
            getattr(requirement_rule, "max_requirement", 0),
        )
        if not is_weapon_requirement_range_active(min_requirement, max_requirement):
            continue
        has_model_requirement_range = True
        if bool(getattr(requirement_rule, "perfect_stats_only", False)):
            perfect_reason = _get_perfect_base_range_hit_reason(
                item,
                min_requirement,
                max_requirement,
                source="model",
                weapon_mod_standalone_kind=weapon_mod_standalone_kind,
                item_label=item_label,
                item_type_label=item_type_label,
            )
            if perfect_reason:
                return perfect_reason
            if not should_fall_back_to_global(lambda: item.model_id):
                return ""
            continue

    if has_model_requirement_range and not should_fall_back_to_global(lambda: item.model_id):
        return ""

    all_weapons_min_requirement, all_weapons_max_requirement = normalize_weapon_requirement_range(
        getattr(rule, "all_weapons_min_requirement", 0),
        getattr(rule, "all_weapons_max_requirement", 0),
    )
    if bool(getattr(rule, "all_weapons_perfect_stats_only", False)) and is_weapon_requirement_range_active(
        all_weapons_min_requirement, all_weapons_max_requirement
    ):
        return _get_perfect_base_range_hit_reason(
            item,
            all_weapons_min_requirement,
            all_weapons_max_requirement,
            source="all",
            weapon_mod_standalone_kind=weapon_mod_standalone_kind,
            item_label=item_label,
            item_type_label=item_type_label,
        )
    return ""


def get_weapon_requirement_hit_reason(
    item: _ItemT,
    rule: _RequirementRule,
    *,
    weapon_rule_kind: str,
    weapon_mod_standalone_kind: str,
    should_fall_back_to_global: Callable[[Callable[[], object]], bool],
    item_label: Callable[[_ItemT], str],
    item_type_label: Callable[[Callable[[], int]], str],
) -> str:
    if rule.kind != weapon_rule_kind:
        return ""
    if not item.is_weapon_like or item.standalone_kind == weapon_mod_standalone_kind:
        return ""

    requirement = normalize_weapon_requirement_level(item.requirement)
    has_model_requirement_range = False
    for requirement_rule in rule.protected_weapon_requirement_rules:
        if item.model_id != int(requirement_rule.model_id):
            continue
        min_requirement, max_requirement = normalize_weapon_requirement_range(
            getattr(requirement_rule, "min_requirement", 0),
            getattr(requirement_rule, "max_requirement", 0),
        )
        if not is_weapon_requirement_range_active(min_requirement, max_requirement):
            continue
        has_model_requirement_range = True
        if bool(getattr(requirement_rule, "perfect_stats_only", False)):
            perfect_reason = _get_perfect_base_range_hit_reason(
                item,
                min_requirement,
                max_requirement,
                source="model",
                weapon_mod_standalone_kind=weapon_mod_standalone_kind,
                item_label=item_label,
                item_type_label=item_type_label,
            )
            if perfect_reason:
                return perfect_reason
            continue
        if requirement <= 0:
            continue
        if min_requirement <= requirement <= max_requirement:
            item_label_text = item_label(item)
            return f"Protected by requirement range: {item_label_text} req {requirement} in {min_requirement}-{max_requirement}."

    if has_model_requirement_range and not should_fall_back_to_global(lambda: item.model_id):
        return ""

    all_weapons_min_requirement, all_weapons_max_requirement = normalize_weapon_requirement_range(
        getattr(rule, "all_weapons_min_requirement", 0),
        getattr(rule, "all_weapons_max_requirement", 0),
    )
    if bool(getattr(rule, "all_weapons_perfect_stats_only", False)) and is_weapon_requirement_range_active(
        all_weapons_min_requirement, all_weapons_max_requirement
    ):
        return _get_perfect_base_range_hit_reason(
            item,
            all_weapons_min_requirement,
            all_weapons_max_requirement,
            source="all",
            weapon_mod_standalone_kind=weapon_mod_standalone_kind,
            item_label=item_label,
            item_type_label=item_type_label,
        )
    if (
        is_weapon_requirement_range_active(all_weapons_min_requirement, all_weapons_max_requirement)
        and all_weapons_min_requirement <= requirement <= all_weapons_max_requirement
    ):
        item_label_text = item_label(item)
        return f"Protected by all-weapons requirement range: {item_label_text} req {requirement} in {all_weapons_min_requirement}-{all_weapons_max_requirement}."
    return ""
