"""Interpret item protection and requirement policy using the caller's lazy lookups.

Scalar readers preserve widget-method resolution before argument evaluation.
"""

from collections.abc import Callable
from collections.abc import Sequence
from typing import TYPE_CHECKING
from typing import Protocol
from typing import TypeVar

from Py4GWCoreLib.enums_src.Item_enums import ItemType
from Sources.icefox.MerchantRules.item_values import MAX_WEAPON_REQUIREMENT as MAX_WEAPON_REQUIREMENT
from Sources.icefox.MerchantRules.item_values import (
    normalize_weapon_requirement_level as normalize_weapon_requirement_level,
)
from Sources.icefox.MerchantRules.item_values import safe_int as _safe_int

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.configuration import RuleNormalizer
    from Sources.icefox.MerchantRules.configuration import SellRule
    from Sources.icefox.MerchantRules.configuration import WeaponModThresholdRule
    from Sources.icefox.MerchantRules.configuration import WeaponModVariantRule
    from Sources.icefox.MerchantRules.configuration import WeaponModVariantThresholdRule
    from Sources.icefox.MerchantRules.inventory_evidence import InventoryItemInfo

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


def normalize_rarity_key(raw_value: str) -> str:
    return str(raw_value or "").strip().lower()


def weapon_mod_variant_matches_parsed_match(
    rule: object,
    match: object,
    *,
    rule_key: Callable[[object], tuple[str, str, str]],
    normalize_variant_parts: Callable[[object, object, object], tuple[str, str, str]],
) -> bool:
    identifier, target_item_type, component_kind = rule_key(rule)
    match_identifier, match_target_item_type, match_component_kind = normalize_variant_parts(
        getattr(match, "identifier", ""),
        getattr(match, "target_item_type", ""),
        getattr(match, "component_kind", ""),
    )
    return (
        bool(identifier)
        and identifier == match_identifier
        and target_item_type == match_target_item_type
        and component_kind == match_component_kind
    )


def has_explicit_equippable_hard_protection(
    rule: "SellRule",
    *,
    weapon_rule_kind: str,
    armor_rule_kind: str,
) -> bool:
    """Return whether an equipment sale rule contains an exclusion that must override selling."""

    if rule.kind not in (weapon_rule_kind, armor_rule_kind):
        return False
    if rule.blacklist_model_ids:
        return True
    if rule.kind == weapon_rule_kind:
        return bool(
            rule.blacklist_item_type_ids
            or is_weapon_requirement_range_active(
                getattr(rule, "all_weapons_min_requirement", 0),
                getattr(rule, "all_weapons_max_requirement", 0),
            )
            or any(
                is_weapon_requirement_range_active(
                    getattr(requirement_rule, "min_requirement", 0),
                    getattr(requirement_rule, "max_requirement", 0),
                )
                for requirement_rule in rule.protected_weapon_requirement_rules
            )
            or rule.protected_weapon_mod_identifiers
            or rule.protected_weapon_mod_thresholds
            or rule.protected_weapon_mod_variants
            or rule.protected_weapon_mod_variant_thresholds
        )
    return bool(rule.protected_rune_identifiers)


class ProtectionPolicy:
    """Interpret protection evidence without owning acquisition or command authority."""

    def __init__(
        self,
        *,
        normalizer: "RuleNormalizer",
        normalize_protected_model_ids: Callable[[object], list[int]],
        normalize_mod_thresholds: Callable[[list[object]], list["WeaponModThresholdRule"]],
        normalize_variant_parts: Callable[[object, object, object], tuple[str, str, str]],
        weapon_item_type_ids: set[int],
        weapon_rule_kind: str,
        armor_rule_kind: str,
        destroy_armor_kind: str,
        weapon_mod_standalone_kind: str,
        read_model_ids: Callable[[], object],
        read_typed_targets: Callable[[], object],
        equipment_rows: Callable[[object], list[dict[str, object]]],
        item_label: Callable[["InventoryItemInfo"], str],
        item_type_label: Callable[[Callable[[], int]], str],
        generic_mod_label: Callable[[str], str],
        threshold_label: Callable[["WeaponModThresholdRule"], str],
        variant_label: Callable[[object], str],
        variant_threshold_label: Callable[["WeaponModVariantThresholdRule"], str],
        rune_label: Callable[[str], str],
        rule_reference: Callable[[int, "SellRule"], str],
        equipment_destination: Callable[["InventoryItemInfo", "SellRule"], str],
        explicit_destination: Callable[["InventoryItemInfo"], str],
    ) -> None:
        self._normalizer = normalizer
        self._normalize_protected_model_ids = normalize_protected_model_ids
        self._normalize_mod_thresholds = normalize_mod_thresholds
        self._normalize_variant_parts = normalize_variant_parts
        self._weapon_item_type_ids = weapon_item_type_ids
        self._weapon_rule_kind = weapon_rule_kind
        self._armor_rule_kind = armor_rule_kind
        self._destroy_armor_kind = destroy_armor_kind
        self._weapon_mod_standalone_kind = weapon_mod_standalone_kind
        self._read_model_ids = read_model_ids
        self._read_typed_targets = read_typed_targets
        self._equipment_rows = equipment_rows
        self._item_label = item_label
        self._item_type_label = item_type_label
        self._generic_mod_label = generic_mod_label
        self._threshold_label = threshold_label
        self._variant_label = variant_label
        self._variant_threshold_label = variant_threshold_label
        self._rune_label = rune_label
        self._rule_reference = rule_reference
        self._equipment_destination = equipment_destination
        self._explicit_destination = explicit_destination

    def _variant_matches(self, rule: object, match: object) -> bool:
        return weapon_mod_variant_matches_parsed_match(
            rule,
            match,
            rule_key=self._normalizer.weapon_mod_variant_rule_key,
            normalize_variant_parts=self._normalize_variant_parts,
        )

    def rule_matches_selected_rarity(self, item: "InventoryItemInfo", rule: object) -> bool:
        rarity_key = normalize_rarity_key(item.rarity)
        rule_kind = str(getattr(rule, "kind", ""))
        rule_rarities = getattr(rule, "rarities", {})
        if rule_kind in (self._armor_rule_kind, self._destroy_armor_kind) and rarity_key == "green":
            return False
        return bool(rule_rarities.get(rarity_key, False))

    def get_protected_hit_reason(self, item: "InventoryItemInfo", rule: "SellRule") -> str:
        if rule.kind == self._weapon_rule_kind:
            matched_identifiers = [
                identifier
                for identifier in item.weapon_mod_identifiers
                if identifier in rule.protected_weapon_mod_identifiers
            ]
            if matched_identifiers:
                labels = [self._generic_mod_label(identifier) for identifier in matched_identifiers]
                return f"Contains protected weapon mod: {', '.join(labels)}."

            matched_thresholds: list[WeaponModThresholdRule] = []
            for threshold_rule in self._normalize_mod_thresholds(getattr(rule, "protected_weapon_mod_thresholds", [])):
                threshold_identifier = str(threshold_rule.identifier or "").strip()
                if not threshold_identifier:
                    continue
                for match in getattr(item, "weapon_mod_matches", []) or []:
                    if str(getattr(match, "identifier", "") or "").strip() != threshold_identifier:
                        continue
                    matched_value = getattr(match, "value", None)
                    if matched_value is None:
                        continue
                    if _safe_int(matched_value, 0) >= int(threshold_rule.min_value):
                        matched_thresholds.append(threshold_rule)
                        break
            if matched_thresholds:
                labels = [self._threshold_label(threshold_rule) for threshold_rule in matched_thresholds]
                return f"Contains protected weapon mod threshold: {', '.join(labels)}."

            matched_variants: list[WeaponModVariantRule] = []
            for variant_rule in self._normalizer.normalize_weapon_mod_variant_rules(
                getattr(rule, "protected_weapon_mod_variants", [])
            ):
                for match in getattr(item, "weapon_mod_matches", []) or []:
                    if self._variant_matches(variant_rule, match):
                        matched_variants.append(variant_rule)
                        break
            if matched_variants:
                labels = [self._variant_label(variant_rule) for variant_rule in matched_variants]
                return f"Contains protected weapon mod variant: {', '.join(labels)}."

            matched_variant_thresholds: list[WeaponModVariantThresholdRule] = []
            for threshold_rule in self._normalizer.normalize_weapon_mod_variant_threshold_rules(
                getattr(rule, "protected_weapon_mod_variant_thresholds", [])
            ):
                for match in getattr(item, "weapon_mod_matches", []) or []:
                    if not self._variant_matches(threshold_rule, match):
                        continue
                    matched_value = getattr(match, "value", None)
                    if matched_value is None:
                        continue
                    if _safe_int(matched_value, 0) >= int(threshold_rule.min_value):
                        matched_variant_thresholds.append(threshold_rule)
                        break
            if matched_variant_thresholds:
                labels = [
                    self._variant_threshold_label(threshold_rule) for threshold_rule in matched_variant_thresholds
                ]
                return f"Contains protected weapon mod variant threshold: {', '.join(labels)}."

        if rule.kind == self._armor_rule_kind:
            matched_identifiers = [
                identifier for identifier in item.rune_identifiers if identifier in rule.protected_rune_identifiers
            ]
            if matched_identifiers:
                labels = [self._rune_label(identifier) for identifier in matched_identifiers]
                return f"Contains protected rune/insignia: {', '.join(labels)}."

        return ""

    def get_concrete_weapon_item_type_ids_for_model(self, model_id: object) -> set[int] | None:
        """Return typed concrete weapon identities, or ``None`` when the catalog cannot prove them."""

        typed_entries = self._equipment_rows(model_id)
        if not typed_entries:
            return None
        concrete_item_type_ids = {
            _safe_int(entry.get("item_type_id"), -1)
            for entry in typed_entries
            if _safe_int(entry.get("item_type_id"), -1) in self._weapon_item_type_ids
        }
        return concrete_item_type_ids or None

    def is_ambiguous_weapon_model(self, model_id: object) -> bool | None:
        concrete_item_type_ids = self.get_concrete_weapon_item_type_ids_for_model(model_id)
        if concrete_item_type_ids is None:
            return None
        return len(concrete_item_type_ids) > 1

    def should_fall_back_to_global_weapon_requirement(self, model_id: object) -> bool:
        """Keep global protection available for ambiguous or unverifiable model identities."""

        return self.is_ambiguous_weapon_model(model_id) is not False

    def get_equippable_hard_protection_reason(
        self, item: "InventoryItemInfo", rule: "SellRule"
    ) -> tuple[str, str] | None:
        destination = self._equipment_destination(item, rule)
        if not destination:
            return None

        rarity_matches = self.rule_matches_selected_rarity(item, rule)
        if rarity_matches and rule.skip_customized and item.is_customized:
            return destination, "Customized item."
        perfect_unidentified_reason = get_perfect_only_unidentified_hold_reason(
            item,
            rule,
            weapon_rule_kind=self._weapon_rule_kind,
            weapon_mod_standalone_kind=self._weapon_mod_standalone_kind,
            should_fall_back_to_global=lambda read_model_id: self.should_fall_back_to_global_weapon_requirement(
                read_model_id()
            ),
            item_label=self._item_label,
            item_type_label=self._item_type_label,
        )
        if perfect_unidentified_reason:
            return destination, perfect_unidentified_reason
        if rarity_matches and rule.skip_unidentified and not item.identified:
            return destination, "Unidentified item."
        if item.model_id in rule.blacklist_model_ids:
            return destination, "Blacklisted model."
        if rule.kind == self._weapon_rule_kind and item.item_type_id in rule.blacklist_item_type_ids:
            return destination, f"Blacklisted weapon type: {self._item_type_label(lambda: item.item_type_id)}."

        requirement_reason = get_weapon_requirement_hit_reason(
            item,
            rule,
            weapon_rule_kind=self._weapon_rule_kind,
            weapon_mod_standalone_kind=self._weapon_mod_standalone_kind,
            should_fall_back_to_global=lambda read_model_id: self.should_fall_back_to_global_weapon_requirement(
                read_model_id()
            ),
            item_label=self._item_label,
            item_type_label=self._item_type_label,
        )
        if requirement_reason:
            return destination, requirement_reason

        protected_reason = self.get_protected_hit_reason(item, rule)
        if protected_reason:
            return destination, protected_reason
        return None

    def get_equippable_explicit_deposit_reason(
        self, item: "InventoryItemInfo", rule: "SellRule"
    ) -> tuple[str, str] | None:
        destination = self._equipment_destination(item, rule)
        if not destination:
            return None
        if item.model_id in rule.blacklist_model_ids:
            return destination, "Blacklisted model."
        if rule.kind == self._weapon_rule_kind and item.item_type_id in rule.blacklist_item_type_ids:
            return destination, f"Blacklisted weapon type: {self._item_type_label(lambda: item.item_type_id)}."

        requirement_reason = get_weapon_requirement_hit_reason(
            item,
            rule,
            weapon_rule_kind=self._weapon_rule_kind,
            weapon_mod_standalone_kind=self._weapon_mod_standalone_kind,
            should_fall_back_to_global=lambda read_model_id: self.should_fall_back_to_global_weapon_requirement(
                read_model_id()
            ),
            item_label=self._item_label,
            item_type_label=self._item_type_label,
        )
        if requirement_reason:
            return destination, requirement_reason

        protected_reason = self.get_protected_hit_reason(item, rule)
        if protected_reason:
            return destination, protected_reason
        return None

    def get_hard_protection_match(
        self,
        item: "InventoryItemInfo",
        enabled_sell_rules: list[tuple[int, "SellRule"]],
    ) -> tuple[int, "SellRule", str, str] | None:
        for rule_index, rule in enabled_sell_rules:
            if rule.kind not in (self._weapon_rule_kind, self._armor_rule_kind):
                continue
            protection = self.get_equippable_hard_protection_reason(item, rule)
            if protection is None:
                continue
            destination, detail = protection
            return rule_index, rule, destination, detail
        return None

    def get_protected_item_model_id_set(self) -> set[int]:
        return set(self._normalize_protected_model_ids(self._read_model_ids()))

    def get_protected_item_typed_target_set(self) -> set[tuple[int, int]]:
        return {
            (int(target.item_type_id), int(target.model_id))
            for target in self._normalizer.normalize_protected_item_targets(self._read_typed_targets())
            if target.item_type_id is not None
        }

    def get_exact_protection_target_count(self) -> int:
        return len(self.get_protected_item_model_id_set()) + len(self.get_protected_item_typed_target_set())

    def is_exact_protected_item_model_id(self, model_id: int, item_type_id: int | None = None) -> bool:
        safe_model_id = max(0, _safe_int(model_id, 0))
        if safe_model_id <= 0:
            return False
        if safe_model_id in self.get_protected_item_model_id_set():
            return True
        safe_item_type_id = _safe_int(item_type_id, -1)
        return (
            self._normalizer.is_valid_exact_item_type_id(safe_item_type_id)
            and (safe_item_type_id, safe_model_id) in self.get_protected_item_typed_target_set()
        )

    def get_exact_model_protection_hit(self, item: "InventoryItemInfo") -> tuple[str, str] | None:
        destination = self._explicit_destination(item)
        model_id = max(0, _safe_int(getattr(item, "model_id", 0), 0))
        if model_id in self.get_protected_item_model_id_set():
            return destination, "Protected by Protected Items: exact model."
        item_type_id = _safe_int(getattr(item, "item_type_id", -1), -1)
        if (
            self._normalizer.is_valid_exact_item_type_id(item_type_id)
            and (item_type_id, model_id) in self.get_protected_item_typed_target_set()
        ):
            return destination, "Protected by Protected Items: exact item type and model."
        return None

    def get_hard_protection_hit(
        self,
        item: "InventoryItemInfo",
        enabled_sell_rules: list[tuple[int, "SellRule"]],
    ) -> tuple[str, str] | None:
        exact_model_protection = self.get_exact_model_protection_hit(item)
        if exact_model_protection is not None:
            return exact_model_protection
        match = self.get_hard_protection_match(item, enabled_sell_rules)
        if match is not None:
            rule_index, rule, destination, detail = match
            return destination, f"Hard-protected by {self._rule_reference(rule_index, rule)}: {detail}"
        return None
