"""Canonical Merchant Rules records and normalization without runtime imports.

RuleNormalizer holds the exact static objects supplied by one widget module.
Outpost entries and crafter membership remain separate, late-read providers.
"""

import re
import time
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from enum import IntEnum
from hashlib import md5

from Sources.icefox.MerchantRules.item_values import dedupe_identifiers as _dedupe_identifiers
from Sources.icefox.MerchantRules.item_values import (
    normalize_weapon_requirement_level as _normalize_weapon_requirement_level,
)
from Sources.icefox.MerchantRules.item_values import safe_int as _safe_int
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_DEFAULT
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_MATERIALS
from Sources.icefox.MerchantRules.salvage_options import normalize_salvage_rule_mode as _normalize_salvage_rule_mode

PROFILE_VERSION = 40


HELPER_TOOLTIPS_ENABLED_DEFAULT = True


MERCHANT_TYPE_MERCHANT = "merchant"


MERCHANT_TYPE_MATERIALS = "material_trader"


MERCHANT_TYPE_RUNE_TRADER = "rune_trader"


MERCHANT_TYPE_SCROLL_TRADER = "scroll_trader"


MERCHANT_TYPE_CONSUMABLE_CRAFTER = "consumable_crafter"


BUY_KIND_MERCHANT_STOCK = "merchant_stock_target"


BUY_KIND_MATERIAL_TARGET = "buy_material_target"


BUY_KIND_RUNE_TRADER_TARGET = "buy_rune_trader_target"


BUY_KIND_SCROLL_TRADER_TARGET = "buy_scroll_trader_target"


BUY_KIND_CONSUMABLE_CRAFTER_TARGET = "consumable_crafter_target"


CONSUMABLE_CRAFTER_COUNT_MODE_MAINTAIN_STOCK = "maintain_stock"


CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT = "craft_amount"


CONSUMABLE_CRAFTER_COUNT_MODES: tuple[str, ...] = (
    CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT,
    CONSUMABLE_CRAFTER_COUNT_MODE_MAINTAIN_STOCK,
)


AFTER_PURCHASE_KEEP = "keep"


AFTER_PURCHASE_RESET_QUANTITY = "reset_quantity"


AFTER_PURCHASE_REMOVE_ENTRY = "remove_entry"


AFTER_PURCHASE_ACTIONS: tuple[str, ...] = (
    AFTER_PURCHASE_KEEP,
    AFTER_PURCHASE_RESET_QUANTITY,
    AFTER_PURCHASE_REMOVE_ENTRY,
)


LEGACY_BUY_KIND_ID_KITS = "restock_id_kits"


LEGACY_BUY_KIND_SALVAGE_KITS = "restock_salvage_kits"


LEGACY_BUY_KIND_ECTO = "buy_ectoplasm"


SELL_KIND_COMMON_MATERIALS = "sell_common_materials"


SELL_KIND_EXPLICIT_MODELS = "sell_explicit_models"


SELL_KIND_RUNE_TRADER_TARGET = "sell_rune_trader_target"


SELL_KIND_WEAPONS = "sell_weapons"


SELL_KIND_ARMOR = "sell_armor"


DESTROY_KIND_MATERIALS = "destroy_materials"


DESTROY_KIND_EXPLICIT_MODELS = "destroy_explicit_models"


DESTROY_KIND_WEAPONS = "destroy_weapons"


DESTROY_KIND_ARMOR = "destroy_armor"


LEGACY_SELL_KIND_WEAPONS_BY_RARITY = "sell_weapons_by_rarity"


LEGACY_SELL_KIND_ARMOR_BY_RARITY = "sell_armor_by_rarity"


LEGACY_SELL_KIND_NONSALVAGEABLE_GOLDS = "sell_identified_nonsalvageable_golds"


SELL_RULE_WORKSPACE_ORDER: tuple[str, ...] = (
    SELL_KIND_WEAPONS,
    SELL_KIND_ARMOR,
    SELL_KIND_RUNE_TRADER_TARGET,
    SELL_KIND_EXPLICIT_MODELS,
    SELL_KIND_COMMON_MATERIALS,
)


MANUAL_VENDOR_BUY_CATEGORY_KINDS: tuple[str, ...] = (
    BUY_KIND_MERCHANT_STOCK,
    BUY_KIND_MATERIAL_TARGET,
    BUY_KIND_RUNE_TRADER_TARGET,
    BUY_KIND_SCROLL_TRADER_TARGET,
)


MANUAL_VENDOR_SELL_CATEGORY_KINDS: tuple[str, ...] = SELL_RULE_WORKSPACE_ORDER


SALVAGE_CATEGORY_WEAPONS = "weapons"


SALVAGE_CATEGORY_ARMOR = "armor"


SALVAGE_CATEGORY_MATERIALS = "materials"


SALVAGE_CATEGORY_OTHER = "other"


SALVAGE_CATEGORY_ORDER: tuple[tuple[str, str], ...] = (
    (SALVAGE_CATEGORY_WEAPONS, "Weapons"),
    (SALVAGE_CATEGORY_ARMOR, "Armor"),
    (SALVAGE_CATEGORY_MATERIALS, "Materials"),
    (SALVAGE_CATEGORY_OTHER, "Other Items"),
)


MAX_CHARACTER_GOLD = 100_000


DEFAULT_TARGET_CARRIED_GOLD = 20_000


COMMON_CRAFTING_MATERIAL_MODEL_IDS: frozenset[int] = frozenset({
    921, 925, 929, 933, 934, 940, 946, 948, 953, 954, 955,
})


RARE_CRAFTING_MATERIAL_MODEL_IDS: frozenset[int] = frozenset({
    922, 923, 926, 927, 928, 930, 931, 932, 935, 936, 937, 938, 939,
    941, 942, 943, 944, 945, 949, 950, 951, 952, 956, 6532, 6533,
})


ALL_CRAFTING_MATERIAL_MODEL_IDS: frozenset[int] = frozenset(
    set(COMMON_CRAFTING_MATERIAL_MODEL_IDS) | set(RARE_CRAFTING_MATERIAL_MODEL_IDS)
)


CLEANUP_TARGET_SCOPE_EXACT = "exact"


CLEANUP_TARGET_SCOPE_COMMON_MATERIAL = "common_material"


CLEANUP_TARGET_SCOPE_RARE_MATERIAL = "rare_material"


CLEANUP_TARGET_SCOPES: tuple[str, ...] = (
    CLEANUP_TARGET_SCOPE_EXACT,
    CLEANUP_TARGET_SCOPE_COMMON_MATERIAL,
    CLEANUP_TARGET_SCOPE_RARE_MATERIAL,
)


RARITY_OPTION_ORDER: tuple[tuple[str, str], ...] = (
    ("white", "White"),
    ("blue", "Blue"),
    ("purple", "Purple"),
    ("gold", "Gold"),
    ("green", "Green"),
)


@dataclass
class MaterialTarget:
    model_id: int = 0
    target_count: int = 0
    max_per_run: int = 0
    after_purchase: str = AFTER_PURCHASE_KEEP


@dataclass
class MerchantStockTarget:
    model_id: int = 0
    target_count: int = 0
    max_per_run: int = 0
    after_purchase: str = AFTER_PURCHASE_KEEP
    check_xunlai_first: bool = False


@dataclass
class RuneTraderTarget:
    identifier: str = ""
    target_count: int = 0
    max_per_run: int = 0
    after_purchase: str = AFTER_PURCHASE_KEEP


@dataclass
class RuneSellTarget:
    identifier: str = ""
    keep_count: int = 0


@dataclass
class WhitelistTarget:
    model_id: int = 0
    keep_count: int = 0
    deposit_to_storage: bool = False


@dataclass
class BuyRule:
    """Configure stock targets that planning may buy from merchants, traders, or crafters."""

    enabled: bool = False
    kind: str = BUY_KIND_MERCHANT_STOCK
    merchant_type: str = MERCHANT_TYPE_MERCHANT
    model_id: int = 0
    target_count: int = 0
    max_per_run: int = 0
    merchant_stock_targets: list[MerchantStockTarget] = field(default_factory=list)
    material_targets: list[MaterialTarget] = field(default_factory=list)
    rune_targets: list[RuneTraderTarget] = field(default_factory=list)
    consumable_crafter_count_mode: str = CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT
    name: str = ""


@dataclass
class WeaponRequirementRule:
    model_id: int = 0
    min_requirement: int = 0
    max_requirement: int = 0
    perfect_stats_only: bool = False


@dataclass
class WeaponModThresholdRule:
    identifier: str = ""
    min_value: int = 0


@dataclass(frozen=True)
class WeaponModVariantRule:
    identifier: str = ""
    target_item_type: str = ""
    component_kind: str = ""


@dataclass(frozen=True)
class WeaponModVariantThresholdRule:
    identifier: str = ""
    target_item_type: str = ""
    component_kind: str = ""
    min_value: int = 0


@dataclass
class SellRule:
    """Configure sale candidates together with hard exclusions and optional storage sources.

    Protection fields are evaluated before sale routing, including when a rule can withdraw
    candidates from Xunlai storage or material storage.
    """

    enabled: bool = False
    kind: str = SELL_KIND_EXPLICIT_MODELS
    merchant_type: str = MERCHANT_TYPE_MERCHANT
    rule_id: str = ""
    model_ids: list[int] = field(default_factory=list)
    keep_count: int = 0
    whitelist_targets: list[WhitelistTarget] = field(default_factory=list)
    rarities: dict[str, bool] = field(default_factory=dict)
    blacklist_model_ids: list[int] = field(default_factory=list)
    blacklist_item_type_ids: list[int] = field(default_factory=list)
    all_weapons_min_requirement: int = 0
    all_weapons_max_requirement: int = 0
    all_weapons_perfect_stats_only: bool = False
    protected_weapon_requirement_rules: list[WeaponRequirementRule] = field(default_factory=list)
    protected_weapon_mod_identifiers: list[str] = field(default_factory=list)
    protected_weapon_mod_thresholds: list[WeaponModThresholdRule] = field(default_factory=list)
    protected_weapon_mod_variants: list[WeaponModVariantRule] = field(default_factory=list)
    protected_weapon_mod_variant_thresholds: list[WeaponModVariantThresholdRule] = field(default_factory=list)
    rune_sell_targets: list[RuneSellTarget] = field(default_factory=list)
    protected_rune_identifiers: list[str] = field(default_factory=list)
    skip_customized: bool = True
    skip_unidentified: bool = True
    include_standalone_runes: bool = False
    deposit_protected_matches: bool = False
    sell_from_xunlai: bool = False
    include_material_storage: bool = False
    name: str = ""


@dataclass
class DestroyRule:
    """Configure inventory items eligible for destruction after keep-count and protection checks."""

    enabled: bool = False
    kind: str = DESTROY_KIND_EXPLICIT_MODELS
    model_ids: list[int] = field(default_factory=list)
    keep_count: int = 0
    whitelist_targets: list[WhitelistTarget] = field(default_factory=list)
    rarities: dict[str, bool] = field(default_factory=dict)
    name: str = ""


@dataclass
class SalvageRule:
    """Configure material or exact-upgrade salvage candidates and their required selectors."""

    enabled: bool = True
    model_ids: list[int] = field(default_factory=list)
    target_common_material_model_ids: list[int] = field(default_factory=list)
    rarities: dict[str, bool] = field(default_factory=dict)
    categories: dict[str, bool] = field(default_factory=dict)
    target_weapon_mod_identifiers: list[str] = field(default_factory=list)
    target_weapon_mod_thresholds: list[WeaponModThresholdRule] = field(default_factory=list)
    target_weapon_mod_variants: list[WeaponModVariantRule] = field(default_factory=list)
    target_weapon_mod_variant_thresholds: list[WeaponModVariantThresholdRule] = field(default_factory=list)
    salvage_option: str = SALVAGE_OPTION_MATERIALS
    name: str = ""
    target_armor_upgrade_identifiers: list[str] = field(default_factory=list)


@dataclass
class SalvageSettings:
    """Hold normalized salvage rules and the opt-in inventory-change automation switch."""

    model_ids: list[int] = field(default_factory=list)
    rarities: dict[str, bool] = field(default_factory=dict)
    categories: dict[str, bool] = field(default_factory=dict)
    on_inventory_change: bool = False
    rules: list[SalvageRule] = field(default_factory=list)


@dataclass
class IdentifySettings:
    """Select identification rarities and the two opt-in automatic identification triggers."""

    rarities: dict[str, bool] = field(default_factory=dict)
    before_execute: bool = False
    on_inventory_change: bool = False


@dataclass
class CleanupTarget:
    model_id: int = 0
    keep_on_character: int = 0
    scope: str = ""


@dataclass
class CleanupProtectionSource:
    sell_rule_id: str = ""


@dataclass(frozen=True)
class ExactProtectionTarget:
    """One Exact Items target; ``None`` preserves a legacy model-wide wildcard."""

    model_id: int
    item_type_id: int | None = None


def default_manual_vendor_category_flags(category_kinds: tuple[str, ...]) -> dict[str, bool]:
    return {
        kind: True
        for kind in category_kinds
    }


def normalize_manual_vendor_category_flags(
    raw_flags: object,
    category_kinds: tuple[str, ...],
    *,
    field_name: str,
) -> dict[str, bool]:
    if raw_flags is None:
        return default_manual_vendor_category_flags(category_kinds)
    if not isinstance(raw_flags, dict):
        raise ValueError(f"Merchant Rules {field_name} must be an object.")

    normalized = default_manual_vendor_category_flags(category_kinds)
    for kind in category_kinds:
        if kind not in raw_flags:
            continue
        value = raw_flags[kind]
        if not isinstance(value, bool):
            raise ValueError(f"Merchant Rules {field_name}.{kind} must be true or false.")
        normalized[kind] = value
    return normalized


def normalize_cleanup_blacklist_model_ids(raw_model_ids: object) -> list[int]:
    normalized: list[int] = []
    seen_model_ids: set[int] = set()
    if not isinstance(raw_model_ids, list):
        return normalized

    for entry in raw_model_ids:
        if isinstance(entry, dict):
            model_id = entry.get("model_id", 0)
        else:
            model_id = entry

        safe_model_id = max(0, _safe_int(model_id, 0))
        if safe_model_id <= 0 or safe_model_id in seen_model_ids:
            continue

        seen_model_ids.add(safe_model_id)
        normalized.append(safe_model_id)

    return normalized


def normalize_protected_item_model_ids(raw_model_ids: object) -> list[int]:
    return normalize_cleanup_blacklist_model_ids(raw_model_ids)


def strict_exact_target_integer(raw_value: object) -> int | None:
    """Return only real integer values for serialized typed Exact targets."""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        return None
    return int(raw_value)


def default_rarity_flags() -> dict[str, bool]:
    return {
        "white": True,
        "blue": True,
        "purple": True,
        "gold": True,
        "green": False,
    }


def default_salvage_rarity_flags() -> dict[str, bool]:
    return {key: False for key, _label in RARITY_OPTION_ORDER}


def default_identify_rarity_flags() -> dict[str, bool]:
    return {key: False for key, _label in RARITY_OPTION_ORDER}


def default_salvage_category_flags() -> dict[str, bool]:
    return {key: False for key, _label in SALVAGE_CATEGORY_ORDER}


def normalize_rarity_flags(raw_value: object) -> dict[str, bool]:
    flags = default_rarity_flags()
    if isinstance(raw_value, dict):
        for key, _label in RARITY_OPTION_ORDER:
            if key in raw_value:
                flags[key] = bool(raw_value.get(key, flags[key]))
    return flags


def normalize_salvage_rarity_flags(raw_value: object) -> dict[str, bool]:
    flags = default_salvage_rarity_flags()
    if isinstance(raw_value, dict):
        for key, _label in RARITY_OPTION_ORDER:
            if key in raw_value:
                flags[key] = bool(raw_value.get(key, False))
    return flags


def normalize_identify_rarity_flags(raw_value: object) -> dict[str, bool]:
    flags = default_identify_rarity_flags()
    if isinstance(raw_value, dict):
        for key, _label in RARITY_OPTION_ORDER:
            if key in raw_value:
                flags[key] = bool(raw_value.get(key, False))
    return flags


def normalize_salvage_category_flags(raw_value: object) -> dict[str, bool]:
    flags = default_salvage_category_flags()
    if isinstance(raw_value, dict):
        for key, _label in SALVAGE_CATEGORY_ORDER:
            if key in raw_value:
                flags[key] = bool(raw_value.get(key, False))
    return flags


def normalize_rule_name(raw_value: object) -> str:
    if raw_value is None:
        return ""
    normalized = " ".join(str(raw_value).replace("\r", " ").replace("\n", " ").split())
    return normalized.strip()


def normalize_gold_target(value: object) -> int:
    return min(MAX_CHARACTER_GOLD, max(0, _safe_int(value, 0)))


def coerce_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def normalize_weapon_mod_threshold_rules(values: list[object]) -> list[WeaponModThresholdRule]:
    rules: list[WeaponModThresholdRule] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        if isinstance(value, WeaponModThresholdRule):
            identifier = str(getattr(value, "identifier", "") or "").strip()
            raw_min_value = getattr(value, "min_value", None)
        elif isinstance(value, dict):
            identifier = str(value.get("identifier", "") or "").strip()
            raw_min_value = value.get("min_value", None)
        else:
            continue
        if not identifier or raw_min_value is None:
            continue
        min_value = _safe_int(raw_min_value, 0)
        key = (identifier, min_value)
        if key in seen:
            continue
        seen.add(key)
        rules.append(WeaponModThresholdRule(identifier=identifier, min_value=min_value))
    return rules


def serialize_weapon_mod_threshold_rules(values: list[object]) -> list[dict[str, object]]:
    return [
        {
            "identifier": rule.identifier,
            "min_value": int(rule.min_value),
        }
        for rule in normalize_weapon_mod_threshold_rules(values)
    ]


def dedupe_model_ids(model_ids: list[int]) -> list[int]:
    unique: list[int] = []
    seen: set[int] = set()
    for value in model_ids:
        model_id = max(0, _safe_int(value, 0))
        if model_id <= 0 or model_id in seen:
            continue
        seen.add(model_id)
        unique.append(model_id)
    return unique


def is_crafting_material_model(model_id: object) -> bool:
    return max(0, _safe_int(model_id, 0)) in ALL_CRAFTING_MATERIAL_MODEL_IDS


def infer_cleanup_target_scope_from_model_id(model_id: object) -> str:
    safe_model_id = max(0, _safe_int(model_id, 0))
    if safe_model_id in COMMON_CRAFTING_MATERIAL_MODEL_IDS:
        return CLEANUP_TARGET_SCOPE_COMMON_MATERIAL
    if safe_model_id in RARE_CRAFTING_MATERIAL_MODEL_IDS:
        return CLEANUP_TARGET_SCOPE_RARE_MATERIAL
    return CLEANUP_TARGET_SCOPE_EXACT


def normalize_cleanup_target_scope(raw_scope: object, model_id: object = 0) -> str:
    normalized_scope = str(raw_scope or "").strip().lower().replace("-", "_").replace(" ", "_")
    scope_aliases = {
        "common": CLEANUP_TARGET_SCOPE_COMMON_MATERIAL,
        "commonmaterial": CLEANUP_TARGET_SCOPE_COMMON_MATERIAL,
        "common_materials": CLEANUP_TARGET_SCOPE_COMMON_MATERIAL,
        "material": CLEANUP_TARGET_SCOPE_COMMON_MATERIAL,
        "materials": CLEANUP_TARGET_SCOPE_COMMON_MATERIAL,
        "rare": CLEANUP_TARGET_SCOPE_RARE_MATERIAL,
        "rarematerial": CLEANUP_TARGET_SCOPE_RARE_MATERIAL,
        "rare_materials": CLEANUP_TARGET_SCOPE_RARE_MATERIAL,
        "equipment": CLEANUP_TARGET_SCOPE_EXACT,
        "exact_item": CLEANUP_TARGET_SCOPE_EXACT,
        "exact_equipment": CLEANUP_TARGET_SCOPE_EXACT,
        "item": CLEANUP_TARGET_SCOPE_EXACT,
    }
    if normalized_scope in scope_aliases:
        return scope_aliases[normalized_scope]
    if normalized_scope in CLEANUP_TARGET_SCOPES:
        return normalized_scope
    return infer_cleanup_target_scope_from_model_id(model_id)


def normalize_material_targets(raw_targets: object) -> list[MaterialTarget]:
    normalized: list[MaterialTarget] = []
    seen_model_ids: set[int] = set()
    if not isinstance(raw_targets, list):
        return normalized

    for entry in raw_targets:
        if isinstance(entry, MaterialTarget):
            model_id = entry.model_id
            target_count = entry.target_count
            max_per_run = entry.max_per_run
            after_purchase = entry.after_purchase
        elif isinstance(entry, dict):
            model_id = entry.get("model_id", 0)
            target_count = entry.get("target_count", 0)
            max_per_run = entry.get("max_per_run", 0)
            after_purchase = entry.get("after_purchase", AFTER_PURCHASE_KEEP)
        else:
            continue

        safe_model_id = max(0, _safe_int(model_id, 0))
        if safe_model_id <= 0 or safe_model_id in seen_model_ids:
            continue

        seen_model_ids.add(safe_model_id)
        normalized.append(
            MaterialTarget(
                model_id=safe_model_id,
                target_count=max(0, _safe_int(target_count, 0)),
                max_per_run=max(0, _safe_int(max_per_run, 0)),
                after_purchase=normalize_after_purchase_action(after_purchase),
            )
        )

    return normalized


def normalize_merchant_stock_targets(raw_targets: object) -> list[MerchantStockTarget]:
    normalized: list[MerchantStockTarget] = []
    seen_model_ids: set[int] = set()
    if not isinstance(raw_targets, list):
        return normalized

    for entry in raw_targets:
        if isinstance(entry, MerchantStockTarget):
            model_id = entry.model_id
            target_count = entry.target_count
            max_per_run = entry.max_per_run
            after_purchase = entry.after_purchase
            check_xunlai_first = entry.check_xunlai_first
        elif isinstance(entry, dict):
            model_id = entry.get("model_id", 0)
            target_count = entry.get("target_count", 0)
            max_per_run = entry.get("max_per_run", 0)
            after_purchase = entry.get("after_purchase", AFTER_PURCHASE_KEEP)
            check_xunlai_first = entry.get("check_xunlai_first", False)
        else:
            continue

        safe_model_id = max(0, _safe_int(model_id, 0))
        if safe_model_id <= 0 or safe_model_id in seen_model_ids:
            continue

        seen_model_ids.add(safe_model_id)
        normalized.append(
            MerchantStockTarget(
                model_id=safe_model_id,
                target_count=max(0, _safe_int(target_count, 0)),
                max_per_run=max(0, _safe_int(max_per_run, 0)),
                after_purchase=normalize_after_purchase_action(after_purchase),
                check_xunlai_first=bool(check_xunlai_first),
            )
        )

    return normalized


def normalize_consumable_crafter_count_mode(mode: object) -> str:
    safe_mode = str(mode or "").strip()
    if safe_mode in CONSUMABLE_CRAFTER_COUNT_MODES:
        return safe_mode
    return CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT


def normalize_after_purchase_action(action: object) -> str:
    safe_action = str(action or "").strip()
    if safe_action in AFTER_PURCHASE_ACTIONS:
        return safe_action
    return AFTER_PURCHASE_KEEP


def normalize_rune_identifier(identifier: object) -> str:
    return str(identifier or "").strip()


def normalize_rune_trader_targets(raw_targets: object) -> list[RuneTraderTarget]:
    normalized: list[RuneTraderTarget] = []
    seen_identifiers: set[str] = set()
    if not isinstance(raw_targets, list):
        return normalized

    for entry in raw_targets:
        if isinstance(entry, RuneTraderTarget):
            identifier = entry.identifier
            target_count = entry.target_count
            max_per_run = entry.max_per_run
            after_purchase = entry.after_purchase
        elif isinstance(entry, dict):
            identifier = entry.get("identifier", "")
            target_count = entry.get("target_count", 0)
            max_per_run = entry.get("max_per_run", 0)
            after_purchase = entry.get("after_purchase", AFTER_PURCHASE_KEEP)
        else:
            continue

        safe_identifier = normalize_rune_identifier(identifier)
        if not safe_identifier or safe_identifier in seen_identifiers:
            continue

        seen_identifiers.add(safe_identifier)
        normalized.append(
            RuneTraderTarget(
                identifier=safe_identifier,
                target_count=max(0, _safe_int(target_count, 0)),
                max_per_run=max(0, _safe_int(max_per_run, 0)),
                after_purchase=normalize_after_purchase_action(after_purchase),
            )
        )

    return normalized


def normalize_rune_sell_targets(raw_targets: object) -> list[RuneSellTarget]:
    normalized: list[RuneSellTarget] = []
    seen_identifiers: set[str] = set()
    if not isinstance(raw_targets, list):
        return normalized

    for entry in raw_targets:
        if isinstance(entry, RuneSellTarget):
            identifier = entry.identifier
            keep_count = entry.keep_count
        elif isinstance(entry, RuneTraderTarget):
            identifier = entry.identifier
            keep_count = entry.target_count
        elif isinstance(entry, dict):
            identifier = entry.get("identifier", "")
            keep_count = entry.get("keep_count", entry.get("target_count", 0))
        else:
            continue

        safe_identifier = normalize_rune_identifier(identifier)
        if not safe_identifier or safe_identifier in seen_identifiers:
            continue

        seen_identifiers.add(safe_identifier)
        normalized.append(
            RuneSellTarget(
                identifier=safe_identifier,
                keep_count=max(0, _safe_int(keep_count, 0)),
            )
        )

    return normalized


def normalize_whitelist_targets(raw_targets: object) -> list[WhitelistTarget]:
    normalized: list[WhitelistTarget] = []
    seen_model_ids: set[int] = set()
    if not isinstance(raw_targets, list):
        return normalized

    for entry in raw_targets:
        if isinstance(entry, WhitelistTarget):
            model_id = entry.model_id
            keep_count = entry.keep_count
            deposit_to_storage = bool(getattr(entry, "deposit_to_storage", False))
        elif isinstance(entry, dict):
            model_id = entry.get("model_id", 0)
            keep_count = entry.get("keep_count", 0)
            deposit_to_storage = bool(entry.get("deposit_to_storage", False))
        else:
            continue

        safe_model_id = max(0, _safe_int(model_id, 0))
        if safe_model_id <= 0 or safe_model_id in seen_model_ids:
            continue

        seen_model_ids.add(safe_model_id)
        normalized.append(
            WhitelistTarget(
                model_id=safe_model_id,
                keep_count=max(0, _safe_int(keep_count, 0)),
                deposit_to_storage=bool(deposit_to_storage),
            )
        )

    return normalized


def normalize_cleanup_targets(raw_targets: object) -> list[CleanupTarget]:
    normalized: list[CleanupTarget] = []
    seen_targets: set[tuple[int, str]] = set()
    if not isinstance(raw_targets, list):
        return normalized

    for entry in raw_targets:
        if isinstance(entry, CleanupTarget):
            model_id = entry.model_id
            keep_on_character = entry.keep_on_character
            scope = getattr(entry, "scope", "")
        elif isinstance(entry, dict):
            model_id = entry.get("model_id", 0)
            keep_on_character = entry.get("keep_on_character", entry.get("keep_count", 0))
            scope = entry.get("scope", "")
        else:
            continue

        safe_model_id = max(0, _safe_int(model_id, 0))
        safe_scope = normalize_cleanup_target_scope(scope, safe_model_id)
        target_key = (safe_model_id, safe_scope)
        if safe_model_id <= 0 or target_key in seen_targets:
            continue

        seen_targets.add(target_key)
        normalized.append(
            CleanupTarget(
                model_id=safe_model_id,
                keep_on_character=max(0, _safe_int(keep_on_character, 0)),
                scope=safe_scope,
            )
        )

    return normalized


def normalize_cleanup_protection_sources(raw_sources: object) -> list[CleanupProtectionSource]:
    normalized: list[CleanupProtectionSource] = []
    seen_rule_ids: set[str] = set()
    if not isinstance(raw_sources, list):
        return normalized

    for entry in raw_sources:
        if isinstance(entry, CleanupProtectionSource):
            sell_rule_id = entry.sell_rule_id
        elif isinstance(entry, dict):
            sell_rule_id = entry.get("sell_rule_id", "")
        else:
            continue

        safe_rule_id = str(sell_rule_id or "").strip()
        if not safe_rule_id or safe_rule_id in seen_rule_ids:
            continue

        seen_rule_ids.add(safe_rule_id)
        normalized.append(CleanupProtectionSource(sell_rule_id=safe_rule_id))

    return normalized


def serialize_whitelist_targets(raw_targets: object) -> list[dict[str, object]]:
    return [
        {
            "model_id": int(target.model_id),
            "keep_count": max(0, int(target.keep_count)),
            "deposit_to_storage": bool(getattr(target, "deposit_to_storage", False)),
        }
        for target in normalize_whitelist_targets(raw_targets)
    ]


def serialize_cleanup_targets(raw_targets: object) -> list[dict[str, object]]:
    return [
        {
            "model_id": int(target.model_id),
            "keep_on_character": max(0, int(target.keep_on_character)),
            "scope": normalize_cleanup_target_scope(getattr(target, "scope", ""), target.model_id),
        }
        for target in normalize_cleanup_targets(raw_targets)
    ]


def serialize_cleanup_protection_sources(raw_sources: object) -> list[dict[str, str]]:
    return [
        {
            "sell_rule_id": str(source.sell_rule_id or "").strip(),
        }
        for source in normalize_cleanup_protection_sources(raw_sources)
    ]


def serialize_cleanup_blacklist_model_ids(raw_model_ids: object) -> list[int]:
    return [int(model_id) for model_id in normalize_cleanup_blacklist_model_ids(raw_model_ids)]


def serialize_protected_item_model_ids(raw_model_ids: object) -> list[int]:
    return [int(model_id) for model_id in normalize_protected_item_model_ids(raw_model_ids)]


def normalize_rule_id(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "", str(value or "").strip())


def make_generated_rule_id(prefix: str, fallback_seed: object = "") -> str:
    safe_prefix = normalize_rule_id(prefix) or "rule"
    seed = f"{safe_prefix}:{fallback_seed}:{time.time_ns()}"
    return f"{safe_prefix}_{md5(seed.encode()).hexdigest()[:10]}"


def ensure_unique_rule_id(
    raw_value: object,
    *,
    seen_ids: set[str],
    prefix: str,
    fallback_seed: object = "",
) -> str:
    candidate = normalize_rule_id(raw_value)
    if not candidate or candidate in seen_ids:
        candidate = make_generated_rule_id(prefix, fallback_seed)
        while candidate in seen_ids:
            candidate = make_generated_rule_id(prefix, f"{fallback_seed}:{len(seen_ids)}")
    seen_ids.add(candidate)
    return candidate


def merge_whitelist_targets_with_legacy_model_ids(
    legacy_model_ids: list[int],
    existing_targets: object = None,
    *,
    default_keep_count: int = 0,
) -> list[WhitelistTarget]:
    normalized_targets = normalize_whitelist_targets(existing_targets)
    merged_targets = [
        WhitelistTarget(
            model_id=int(target.model_id),
            keep_count=max(0, int(target.keep_count)),
            deposit_to_storage=bool(getattr(target, "deposit_to_storage", False)),
        )
        for target in normalized_targets
    ]
    existing_model_ids = {int(target.model_id) for target in merged_targets}
    safe_default_keep_count = max(0, _safe_int(default_keep_count, 0))
    for model_id in dedupe_model_ids(legacy_model_ids):
        if model_id in existing_model_ids:
            continue
        merged_targets.append(
            WhitelistTarget(
                model_id=model_id,
                keep_count=safe_default_keep_count,
                deposit_to_storage=False,
            )
        )
    return merged_targets


def get_whitelist_target_model_ids(raw_targets: object) -> list[int]:
    return [
        int(target.model_id)
        for target in normalize_whitelist_targets(raw_targets)
    ]


def default_buy_rules() -> list[BuyRule]:
    return [
        BuyRule(enabled=False, kind=BUY_KIND_MERCHANT_STOCK, merchant_type=MERCHANT_TYPE_MERCHANT, model_id=0, target_count=0, max_per_run=0),
        BuyRule(enabled=False, kind=BUY_KIND_MATERIAL_TARGET, merchant_type=MERCHANT_TYPE_MATERIALS, model_id=0, target_count=0, max_per_run=0),
        BuyRule(enabled=False, kind=BUY_KIND_RUNE_TRADER_TARGET, merchant_type=MERCHANT_TYPE_RUNE_TRADER, model_id=0, target_count=0, max_per_run=0),
        BuyRule(enabled=False, kind=BUY_KIND_SCROLL_TRADER_TARGET, merchant_type=MERCHANT_TYPE_SCROLL_TRADER, model_id=0, target_count=0, max_per_run=0),
        BuyRule(
            enabled=False,
            kind=BUY_KIND_CONSUMABLE_CRAFTER_TARGET,
            merchant_type=MERCHANT_TYPE_CONSUMABLE_CRAFTER,
            model_id=0,
            target_count=0,
            max_per_run=0,
            consumable_crafter_count_mode=CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT,
        ),
    ]


def default_sell_rules() -> list[SellRule]:
    return [
        SellRule(enabled=False, kind=SELL_KIND_COMMON_MATERIALS, merchant_type=MERCHANT_TYPE_MATERIALS, model_ids=[], keep_count=0),
        SellRule(enabled=False, kind=SELL_KIND_EXPLICIT_MODELS, merchant_type=MERCHANT_TYPE_MERCHANT, model_ids=[], keep_count=0),
        SellRule(
            enabled=False,
            kind=SELL_KIND_WEAPONS,
            merchant_type=MERCHANT_TYPE_MERCHANT,
            rarities=default_rarity_flags(),
            skip_customized=True,
            skip_unidentified=True,
        ),
        SellRule(
            enabled=False,
            kind=SELL_KIND_ARMOR,
            merchant_type=MERCHANT_TYPE_MERCHANT,
            rarities=default_rarity_flags(),
            skip_customized=True,
            skip_unidentified=True,
        ),
        SellRule(
            enabled=False,
            kind=SELL_KIND_RUNE_TRADER_TARGET,
            merchant_type=MERCHANT_TYPE_RUNE_TRADER,
            rune_sell_targets=[],
        ),
    ]


def default_destroy_rules() -> list[DestroyRule]:
    return [
        DestroyRule(enabled=False, kind=DESTROY_KIND_WEAPONS, rarities=default_rarity_flags()),
        DestroyRule(enabled=False, kind=DESTROY_KIND_ARMOR, rarities=default_rarity_flags()),
        DestroyRule(enabled=False, kind=DESTROY_KIND_EXPLICIT_MODELS, model_ids=[], keep_count=0),
        DestroyRule(enabled=False, kind=DESTROY_KIND_MATERIALS, model_ids=[], keep_count=0),
    ]


def sell_rule_can_include_material_storage(rule: SellRule) -> bool:
    return str(getattr(rule, "kind", "")) == SELL_KIND_COMMON_MATERIALS


def normalize_common_material_model_ids(raw_model_ids: object) -> list[int]:
    return [
        model_id
        for model_id in dedupe_model_ids(
            [_safe_int(value, 0) for value in coerce_list(raw_model_ids)]
        )
        if model_id in COMMON_CRAFTING_MATERIAL_MODEL_IDS
    ]


def normalize_identify_settings(raw_settings: object) -> IdentifySettings:
    if isinstance(raw_settings, IdentifySettings):
        return IdentifySettings(
            rarities=normalize_identify_rarity_flags(raw_settings.rarities),
            before_execute=bool(raw_settings.before_execute),
            on_inventory_change=bool(raw_settings.on_inventory_change),
        )

    if not isinstance(raw_settings, dict):
        raw_settings = {}

    return IdentifySettings(
        rarities=normalize_identify_rarity_flags(raw_settings.get("rarities", {})),
        before_execute=bool(raw_settings.get("before_execute", False)),
        on_inventory_change=bool(raw_settings.get("on_inventory_change", False)),
    )


def serialize_identify_settings(settings: IdentifySettings) -> dict[str, object]:
    normalized_settings = normalize_identify_settings(settings)
    return {
        "rarities": dict(normalized_settings.rarities),
        "before_execute": bool(normalized_settings.before_execute),
        "on_inventory_change": bool(normalized_settings.on_inventory_change),
    }


def normalize_outpost_ids(
    values: list[int], *, get_outpost_entries: Callable[[], list[dict[str, object]]]
) -> list[int]:
    valid_ids = {int(entry.get("id", 0)) for entry in get_outpost_entries()}
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values:
        outpost_id = max(0, _safe_int(value, 0))
        if outpost_id <= 0 or outpost_id in seen or outpost_id not in valid_ids:
            continue
        seen.add(outpost_id)
        normalized.append(outpost_id)
    return normalized


class RuleNormalizer:
    """Normalize rules using one widget module's exact static references."""

    def __init__(
        self,
        *,
        item_type: type[IntEnum],
        exact_non_runtime_item_types: frozenset[IntEnum],
        weapon_item_type_ids: set[int],
        scroll_trader_stock_model_ids: frozenset[int],
        ectoplasm_model_id: int,
        salvage_kit_model_id: int,
        buy_rule_kinds: list[str],
        sell_rule_kinds: list[str],
        destroy_rule_kinds: list[str],
        buy_kind_to_merchant_type: dict[str, str],
        sell_kind_to_merchant_type: dict[str, str],
        normalize_weapon_requirement_range: Callable[[object, object], tuple[int, int]],
        normalize_weapon_mod_variant_parts: Callable[[object, object, object], tuple[str, str, str]],
    ) -> None:
        self._item_type = item_type
        self._exact_non_runtime_item_types = exact_non_runtime_item_types
        self._weapon_item_type_ids = weapon_item_type_ids
        self._scroll_trader_stock_model_ids = scroll_trader_stock_model_ids
        self._ectoplasm_model_id = ectoplasm_model_id
        self._salvage_kit_model_id = salvage_kit_model_id
        self._buy_rule_kinds = buy_rule_kinds
        self._sell_rule_kinds = sell_rule_kinds
        self._destroy_rule_kinds = destroy_rule_kinds
        self._buy_kind_to_merchant_type = buy_kind_to_merchant_type
        self._sell_kind_to_merchant_type = sell_kind_to_merchant_type
        self._normalize_weapon_requirement_range = normalize_weapon_requirement_range
        self._normalize_weapon_mod_variant_parts = normalize_weapon_mod_variant_parts

    def is_valid_exact_item_type_id(self, raw_item_type_id: object) -> bool:
        if isinstance(raw_item_type_id, bool):
            return False
        try:
            item_type = self._item_type(_safe_int(raw_item_type_id, -1))
        except (TypeError, ValueError):
            return False
        return item_type not in self._exact_non_runtime_item_types

    def normalize_protected_item_targets(
        self,
        raw_targets: object,
        *,
        strict: bool = False,
    ) -> list[ExactProtectionTarget]:
        if not isinstance(raw_targets, list):
            if strict:
                raise ValueError("Merchant Rules protected_item_targets must be a list.")
            return []

        normalized: list[ExactProtectionTarget] = []
        seen_keys: set[tuple[int, int]] = set()
        for raw_target in raw_targets:
            if isinstance(raw_target, ExactProtectionTarget):
                model_id = raw_target.model_id
                item_type_id = raw_target.item_type_id
            elif isinstance(raw_target, dict):
                model_id = raw_target.get("model_id", 0)
                item_type_id = raw_target.get("item_type_id")
            else:
                model_id = 0
                item_type_id = None

            if strict:
                strict_model_id = strict_exact_target_integer(model_id)
                safe_item_type_id = (
                    strict_exact_target_integer(item_type_id)
                    if item_type_id is not None
                    else None
                )
                safe_model_id = max(0, strict_model_id) if strict_model_id is not None else 0
            else:
                safe_model_id = max(0, _safe_int(model_id, 0))
                safe_item_type_id = (
                    _safe_int(item_type_id, -1)
                    if item_type_id is not None
                    else None
                )
            valid_target = (
                safe_model_id > 0
                and safe_item_type_id is not None
                and self.is_valid_exact_item_type_id(safe_item_type_id)
            )
            if not valid_target:
                if strict:
                    raise ValueError("Merchant Rules protected_item_targets contains an invalid typed target.")
                continue

            if safe_item_type_id is None:
                continue
            target_key = (safe_item_type_id, safe_model_id)
            if target_key in seen_keys:
                continue
            seen_keys.add(target_key)
            normalized.append(
                ExactProtectionTarget(
                    model_id=safe_model_id,
                    item_type_id=safe_item_type_id,
                )
            )
        return normalized

    def weapon_mod_variant_rule_key(self, rule: object) -> tuple[str, str, str]:
        return self._normalize_weapon_mod_variant_parts(
            getattr(rule, "identifier", ""),
            getattr(rule, "target_item_type", ""),
            getattr(rule, "component_kind", ""),
        )

    def normalize_weapon_mod_variant_rules(self, values: list[object]) -> list[WeaponModVariantRule]:
        rules: list[WeaponModVariantRule] = []
        seen: set[tuple[str, str, str]] = set()
        for value in values:
            if isinstance(value, WeaponModVariantRule):
                identifier, target_item_type, component_kind = self.weapon_mod_variant_rule_key(value)
            elif isinstance(value, dict):
                identifier, target_item_type, component_kind = self._normalize_weapon_mod_variant_parts(
                    value.get("identifier", ""),
                    value.get("target_item_type", ""),
                    value.get("component_kind", ""),
                )
            else:
                continue
            if not identifier or not target_item_type or not component_kind:
                continue
            key = (identifier, target_item_type, component_kind)
            if key in seen:
                continue
            seen.add(key)
            rules.append(
                WeaponModVariantRule(
                    identifier=identifier,
                    target_item_type=target_item_type,
                    component_kind=component_kind,
                )
            )
        return rules

    def normalize_weapon_mod_variant_threshold_rules(self, values: list[object]) -> list[WeaponModVariantThresholdRule]:
        rules: list[WeaponModVariantThresholdRule] = []
        seen: set[tuple[str, str, str, int]] = set()
        for value in values:
            if isinstance(value, WeaponModVariantThresholdRule):
                identifier, target_item_type, component_kind = self.weapon_mod_variant_rule_key(value)
                raw_min_value = getattr(value, "min_value", None)
            elif isinstance(value, dict):
                identifier, target_item_type, component_kind = self._normalize_weapon_mod_variant_parts(
                    value.get("identifier", ""),
                    value.get("target_item_type", ""),
                    value.get("component_kind", ""),
                )
                raw_min_value = value.get("min_value", None)
            else:
                continue
            if not identifier or not target_item_type or not component_kind or raw_min_value is None:
                continue
            min_value = _safe_int(raw_min_value, 0)
            key = (identifier, target_item_type, component_kind, min_value)
            if key in seen:
                continue
            seen.add(key)
            rules.append(
                WeaponModVariantThresholdRule(
                    identifier=identifier,
                    target_item_type=target_item_type,
                    component_kind=component_kind,
                    min_value=min_value,
                )
            )
        return rules

    def serialize_weapon_mod_variant_rules(self, values: list[object]) -> list[dict[str, object]]:
        return [
            {
                "identifier": rule.identifier,
                "target_item_type": rule.target_item_type,
                "component_kind": rule.component_kind,
            }
            for rule in self.normalize_weapon_mod_variant_rules(values)
        ]

    def serialize_weapon_mod_variant_threshold_rules(self, values: list[object]) -> list[dict[str, object]]:
        return [
            {
                "identifier": rule.identifier,
                "target_item_type": rule.target_item_type,
                "component_kind": rule.component_kind,
                "min_value": int(rule.min_value),
            }
            for rule in self.normalize_weapon_mod_variant_threshold_rules(values)
        ]

    def dedupe_weapon_item_type_ids(self, item_type_ids: list[object]) -> list[int]:
        unique: list[int] = []
        seen: set[int] = set()
        for value in item_type_ids:
            item_type_id = _safe_int(value, 0)
            if item_type_id not in self._weapon_item_type_ids or item_type_id in seen:
                continue
            seen.add(item_type_id)
            unique.append(item_type_id)
        return unique

    def is_scroll_trader_stock_model(self, model_id: object) -> bool:
        return max(0, _safe_int(model_id, 0)) in self._scroll_trader_stock_model_ids

    def normalize_all_weapons_requirement_range_from_payload(self, entry: dict[str, object]) -> tuple[int, int]:
        raw_max_requirement = entry.get("all_weapons_max_requirement", 0)
        raw_min_requirement = entry.get(
            "all_weapons_min_requirement",
            1 if _normalize_weapon_requirement_level(raw_max_requirement) > 0 else 0,
        )
        return self._normalize_weapon_requirement_range(raw_min_requirement, raw_max_requirement)

    def serialize_protected_item_targets(self, raw_targets: object) -> list[dict[str, int]]:
        return [
            {
                "item_type_id": int(target.item_type_id),
                "model_id": int(target.model_id),
            }
            for target in self.normalize_protected_item_targets(raw_targets)
            if target.item_type_id is not None
        ]

    def normalize_weapon_requirement_rules(self, raw_rules: object) -> list[WeaponRequirementRule]:
        normalized: list[WeaponRequirementRule] = []
        seen_model_ids: set[int] = set()
        if not isinstance(raw_rules, list):
            return normalized

        for entry in raw_rules:
            if isinstance(entry, WeaponRequirementRule):
                model_id = entry.model_id
                min_requirement = getattr(entry, "min_requirement", 0)
                max_requirement = entry.max_requirement
                perfect_stats_only = getattr(entry, "perfect_stats_only", False)
            elif isinstance(entry, dict):
                model_id = entry.get("model_id", 0)
                max_requirement = entry.get("max_requirement", 0)
                min_requirement = entry.get(
                    "min_requirement",
                    1 if _normalize_weapon_requirement_level(max_requirement) > 0 else 0,
                )
                perfect_stats_only = bool(entry.get("perfect_stats_only", entry.get("perfect_only", False)))
            else:
                continue

            safe_model_id = max(0, _safe_int(model_id, 0))
            if safe_model_id <= 0 or safe_model_id in seen_model_ids:
                continue

            min_requirement, max_requirement = self._normalize_weapon_requirement_range(
                min_requirement, max_requirement
            )
            seen_model_ids.add(safe_model_id)
            normalized.append(
                WeaponRequirementRule(
                    model_id=safe_model_id,
                    min_requirement=min_requirement,
                    max_requirement=max_requirement,
                    perfect_stats_only=bool(perfect_stats_only),
                )
            )

        return normalized

    def get_buy_rule_merchant_type(self, rule: BuyRule) -> str:
        if rule.kind == BUY_KIND_MATERIAL_TARGET:
            return MERCHANT_TYPE_MATERIALS
        if rule.kind == BUY_KIND_RUNE_TRADER_TARGET:
            return MERCHANT_TYPE_RUNE_TRADER
        if rule.kind == BUY_KIND_SCROLL_TRADER_TARGET:
            return MERCHANT_TYPE_SCROLL_TRADER
        return self._buy_kind_to_merchant_type.get(rule.kind, MERCHANT_TYPE_MERCHANT)

    def materialize_profile_buy_rules(self, raw_entries: object) -> list[BuyRule]:
        return [
            BuyRule(
                enabled=bool(entry.get("enabled", False)),
                kind=str(entry.get("kind", BUY_KIND_MERCHANT_STOCK)),
                merchant_type=str(entry.get("merchant_type", MERCHANT_TYPE_MERCHANT)),
                model_id=_safe_int(entry.get("model_id", 0), 0),
                target_count=_safe_int(entry.get("target_count", 0), 0),
                max_per_run=_safe_int(entry.get("max_per_run", 0), 0),
                merchant_stock_targets=normalize_merchant_stock_targets(coerce_list(entry.get("merchant_stock_targets", []))),
                material_targets=normalize_material_targets(coerce_list(entry.get("material_targets", []))),
                rune_targets=normalize_rune_trader_targets(coerce_list(entry.get("rune_targets", []))),
                consumable_crafter_count_mode=normalize_consumable_crafter_count_mode(
                    entry.get("consumable_crafter_count_mode", CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT)
                ),
                name=normalize_rule_name(entry.get("name", "")),
            )
            for entry in coerce_list(raw_entries)
            if isinstance(entry, dict)
        ]

    def materialize_profile_sell_rules(self, raw_entries: object) -> list[SellRule]:
        return self.normalize_sell_rules([
            SellRule(
                enabled=bool(entry.get("enabled", False)),
                kind=str(entry.get("kind", SELL_KIND_EXPLICIT_MODELS)),
                merchant_type=str(entry.get("merchant_type", MERCHANT_TYPE_MERCHANT)),
                rule_id=normalize_rule_id(entry.get("rule_id", "")),
                model_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("model_ids", []))],
                keep_count=_safe_int(entry.get("keep_count", 0), 0),
                whitelist_targets=normalize_whitelist_targets(coerce_list(entry.get("whitelist_targets", []))),
                rarities=normalize_rarity_flags(entry.get("rarities", {})),
                blacklist_model_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("blacklist_model_ids", []))],
                blacklist_item_type_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("blacklist_item_type_ids", []))],
                all_weapons_min_requirement=self.normalize_all_weapons_requirement_range_from_payload(entry)[0],
                all_weapons_max_requirement=self.normalize_all_weapons_requirement_range_from_payload(entry)[1],
                all_weapons_perfect_stats_only=bool(entry.get("all_weapons_perfect_stats_only", False)),
                protected_weapon_requirement_rules=self.normalize_weapon_requirement_rules(coerce_list(entry.get("protected_weapon_requirement_rules", []))),
                protected_weapon_mod_identifiers=_dedupe_identifiers(coerce_list(entry.get("protected_weapon_mod_identifiers", []))),
                protected_weapon_mod_thresholds=normalize_weapon_mod_threshold_rules(coerce_list(entry.get("protected_weapon_mod_thresholds", []))),
                protected_weapon_mod_variants=self.normalize_weapon_mod_variant_rules(coerce_list(entry.get("protected_weapon_mod_variants", []))),
                protected_weapon_mod_variant_thresholds=self.normalize_weapon_mod_variant_threshold_rules(coerce_list(entry.get("protected_weapon_mod_variant_thresholds", []))),
                rune_sell_targets=normalize_rune_sell_targets(coerce_list(entry.get("rune_sell_targets", []))),
                protected_rune_identifiers=_dedupe_identifiers(coerce_list(entry.get("protected_rune_identifiers", []))),
                skip_customized=bool(entry.get("skip_customized", True)),
                skip_unidentified=bool(entry.get("skip_unidentified", True)),
                include_standalone_runes=bool(entry.get("include_standalone_runes", False)),
                deposit_protected_matches=bool(entry.get("deposit_protected_matches", False)),
                sell_from_xunlai=bool(entry.get("sell_from_xunlai", False)),
                include_material_storage=bool(entry.get("include_material_storage", False)),
                name=normalize_rule_name(entry.get("name", "")),
            )
            for entry in coerce_list(raw_entries)
            if isinstance(entry, dict)
        ])

    def materialize_profile_destroy_rules(self, raw_entries: object) -> list[DestroyRule]:
        return self.normalize_destroy_rules([
            DestroyRule(
                enabled=bool(entry.get("enabled", False)),
                kind=str(entry.get("kind", DESTROY_KIND_EXPLICIT_MODELS)),
                model_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("model_ids", []))],
                keep_count=_safe_int(entry.get("keep_count", 0), 0),
                whitelist_targets=normalize_whitelist_targets(coerce_list(entry.get("whitelist_targets", []))),
                rarities=normalize_rarity_flags(entry.get("rarities", {})),
                name=normalize_rule_name(entry.get("name", "")),
            )
            for entry in coerce_list(raw_entries)
            if isinstance(entry, dict)
        ])

    def normalize_buy_rule(self, rule: BuyRule, *, has_crafter_recipe: Callable[[int], bool]) -> BuyRule | None:
        """Canonicalize a buy rule and discard kinds that cannot produce a valid target."""

        legacy_model_id = max(0, _safe_int(rule.model_id, 0))
        legacy_target_count = max(0, _safe_int(rule.target_count, 0))
        legacy_max_per_run = max(0, _safe_int(rule.max_per_run, 0))

        if rule.kind == LEGACY_BUY_KIND_ID_KITS:
            return None
        if rule.kind == LEGACY_BUY_KIND_SALVAGE_KITS:
            rule.kind = BUY_KIND_MERCHANT_STOCK
            legacy_model_id = self._salvage_kit_model_id
        elif rule.kind == LEGACY_BUY_KIND_ECTO:
            rule.kind = BUY_KIND_MATERIAL_TARGET
            legacy_model_id = self._ectoplasm_model_id
        if rule.kind not in self._buy_rule_kinds:
            rule.kind = BUY_KIND_MERCHANT_STOCK

        rule.model_id = legacy_model_id
        rule.target_count = legacy_target_count
        rule.max_per_run = legacy_max_per_run
        rule.merchant_stock_targets = normalize_merchant_stock_targets(getattr(rule, "merchant_stock_targets", []))
        rule.material_targets = normalize_material_targets(getattr(rule, "material_targets", []))
        rule.rune_targets = normalize_rune_trader_targets(getattr(rule, "rune_targets", []))
        rule.consumable_crafter_count_mode = normalize_consumable_crafter_count_mode(
            getattr(rule, "consumable_crafter_count_mode", CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT)
        )

        if rule.kind == BUY_KIND_MATERIAL_TARGET:
            if not rule.material_targets and legacy_model_id > 0 and is_crafting_material_model(legacy_model_id):
                rule.material_targets = [
                    MaterialTarget(
                        model_id=legacy_model_id,
                        target_count=legacy_target_count,
                        max_per_run=legacy_max_per_run,
                    )
                ]
            rule.merchant_stock_targets = []
            rule.rune_targets = []
            rule.model_id = 0
            rule.target_count = 0
            rule.max_per_run = 0
        elif rule.kind == BUY_KIND_RUNE_TRADER_TARGET:
            rule.merchant_stock_targets = []
            rule.material_targets = []
            rule.model_id = 0
            rule.target_count = 0
            rule.max_per_run = 0
        elif rule.kind == BUY_KIND_SCROLL_TRADER_TARGET:
            if (
                not rule.merchant_stock_targets
                and legacy_model_id > 0
                and self.is_scroll_trader_stock_model(legacy_model_id)
            ):
                rule.merchant_stock_targets = [
                    MerchantStockTarget(
                        model_id=legacy_model_id,
                        target_count=legacy_target_count,
                        max_per_run=legacy_max_per_run,
                    )
                ]
            rule.merchant_stock_targets = [
                target
                for target in rule.merchant_stock_targets
                if self.is_scroll_trader_stock_model(target.model_id)
            ]
            rule.material_targets = []
            rule.rune_targets = []
            rule.model_id = 0
            rule.target_count = 0
            rule.max_per_run = 0
        elif rule.kind == BUY_KIND_CONSUMABLE_CRAFTER_TARGET:
            rule.consumable_crafter_count_mode = normalize_consumable_crafter_count_mode(rule.consumable_crafter_count_mode)
            if not rule.merchant_stock_targets and legacy_model_id > 0 and has_crafter_recipe(legacy_model_id):
                rule.merchant_stock_targets = [
                    MerchantStockTarget(
                        model_id=legacy_model_id,
                        target_count=legacy_target_count,
                        max_per_run=legacy_max_per_run,
                    )
                ]
            rule.merchant_stock_targets = [
                target for target in rule.merchant_stock_targets if has_crafter_recipe(int(target.model_id))
            ]
            rule.material_targets = []
            rule.rune_targets = []
            rule.model_id = 0
            rule.target_count = 0
            rule.max_per_run = 0
        else:
            if not rule.merchant_stock_targets and legacy_model_id > 0:
                rule.merchant_stock_targets = [
                    MerchantStockTarget(
                        model_id=legacy_model_id,
                        target_count=legacy_target_count,
                        max_per_run=legacy_max_per_run,
                    )
                ]
            rule.material_targets = []
            rule.rune_targets = []
            rule.model_id = 0
            rule.target_count = 0
            rule.max_per_run = 0

        rule.name = normalize_rule_name(getattr(rule, "name", ""))
        rule.merchant_type = self.get_buy_rule_merchant_type(rule)
        return rule

    def normalize_buy_rules(self, rules: list[BuyRule], *, has_crafter_recipe: Callable[[int], bool]) -> list[BuyRule]:
        normalized_rules: list[BuyRule] = []
        for rule in rules:
            normalized = self.normalize_buy_rule(rule, has_crafter_recipe=has_crafter_recipe)
            if normalized is not None:
                normalized_rules.append(normalized)
        return normalized_rules

    def normalize_sell_rule(self, rule: SellRule) -> SellRule | None:
        """Canonicalize sale routing while preserving hard protections and legacy profile meaning.

        Unsupported legacy rule kinds are either migrated to their current equivalent or removed
        when retaining them could route items unsafely.
        """

        legacy_model_ids = dedupe_model_ids(getattr(rule, "model_ids", []))
        legacy_keep_count = max(0, int(getattr(rule, "keep_count", 0)))
        if rule.kind == LEGACY_SELL_KIND_WEAPONS_BY_RARITY:
            rule.kind = SELL_KIND_WEAPONS
        elif rule.kind == LEGACY_SELL_KIND_ARMOR_BY_RARITY:
            rule.kind = SELL_KIND_ARMOR
        elif rule.kind == LEGACY_SELL_KIND_NONSALVAGEABLE_GOLDS:
            return None
        if rule.kind not in self._sell_rule_kinds:
            rule.kind = SELL_KIND_EXPLICIT_MODELS
        rule.merchant_type = self._sell_kind_to_merchant_type[rule.kind]
        rule.rule_id = normalize_rule_id(getattr(rule, "rule_id", ""))
        rule.keep_count = legacy_keep_count
        rule.model_ids = legacy_model_ids
        rule.whitelist_targets = merge_whitelist_targets_with_legacy_model_ids(
            legacy_model_ids,
            getattr(rule, "whitelist_targets", []),
            default_keep_count=legacy_keep_count,
        )
        rule.rarities = normalize_rarity_flags(rule.rarities)
        rule.blacklist_model_ids = dedupe_model_ids(rule.blacklist_model_ids)
        rule.blacklist_item_type_ids = self.dedupe_weapon_item_type_ids(rule.blacklist_item_type_ids)
        (
            rule.all_weapons_min_requirement,
            rule.all_weapons_max_requirement,
        ) = self._normalize_weapon_requirement_range(
            getattr(rule, "all_weapons_min_requirement", 0),
            getattr(rule, "all_weapons_max_requirement", 0),
        )
        rule.all_weapons_perfect_stats_only = bool(getattr(rule, "all_weapons_perfect_stats_only", False))
        rule.protected_weapon_requirement_rules = self.normalize_weapon_requirement_rules(getattr(rule, "protected_weapon_requirement_rules", []))
        rule.protected_weapon_mod_identifiers = _dedupe_identifiers(rule.protected_weapon_mod_identifiers)
        rule.protected_weapon_mod_thresholds = normalize_weapon_mod_threshold_rules(
            coerce_list(getattr(rule, "protected_weapon_mod_thresholds", []))
        )
        rule.protected_weapon_mod_variants = self.normalize_weapon_mod_variant_rules(
            coerce_list(getattr(rule, "protected_weapon_mod_variants", []))
        )
        rule.protected_weapon_mod_variant_thresholds = self.normalize_weapon_mod_variant_threshold_rules(
            coerce_list(getattr(rule, "protected_weapon_mod_variant_thresholds", []))
        )
        rule.rune_sell_targets = normalize_rune_sell_targets(getattr(rule, "rune_sell_targets", []))
        rule.protected_rune_identifiers = _dedupe_identifiers(rule.protected_rune_identifiers)
        rule.skip_customized = bool(rule.skip_customized)
        rule.skip_unidentified = bool(rule.skip_unidentified)
        rule.include_standalone_runes = bool(rule.include_standalone_runes)
        rule.deposit_protected_matches = bool(getattr(rule, "deposit_protected_matches", False))
        rule.sell_from_xunlai = bool(getattr(rule, "sell_from_xunlai", False))
        rule.include_material_storage = (
            bool(getattr(rule, "include_material_storage", False))
            and bool(rule.sell_from_xunlai)
            and sell_rule_can_include_material_storage(rule)
        )
        rule.name = normalize_rule_name(getattr(rule, "name", ""))
        rule.whitelist_targets = normalize_whitelist_targets(rule.whitelist_targets)
        if rule.kind in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
            rule.model_ids = []
            rule.keep_count = 0
            rule.whitelist_targets = []
            rule.rune_sell_targets = []
            if rule.kind != SELL_KIND_WEAPONS:
                rule.blacklist_item_type_ids = []
        elif rule.kind == SELL_KIND_RUNE_TRADER_TARGET:
            rule.model_ids = []
            rule.keep_count = 0
            rule.whitelist_targets = []
            rule.rarities = default_rarity_flags()
            rule.blacklist_model_ids = []
            rule.blacklist_item_type_ids = []
            rule.deposit_protected_matches = False
        else:
            rule.model_ids = get_whitelist_target_model_ids(rule.whitelist_targets)
            rule.keep_count = 0
            rule.blacklist_item_type_ids = []
            rule.rune_sell_targets = []
            rule.deposit_protected_matches = False
        return rule

    def normalize_sell_rules(self, rules: list[SellRule]) -> list[SellRule]:
        normalized_rules: list[SellRule] = []
        seen_rule_ids: set[str] = set()
        for index, rule in enumerate(rules):
            normalized = self.normalize_sell_rule(rule)
            if normalized is not None:
                normalized.rule_id = ensure_unique_rule_id(
                    normalized.rule_id,
                    seen_ids=seen_rule_ids,
                    prefix="sell",
                    fallback_seed=f"{index}:{normalized.kind}:{normalized.name}",
                )
                normalized_rules.append(normalized)
        return normalized_rules

    def normalize_destroy_rule(self, rule: DestroyRule) -> DestroyRule:
        """Canonicalize a destroy rule, including per-target keep counts and rarity selectors."""

        legacy_model_ids = dedupe_model_ids(getattr(rule, "model_ids", []))
        legacy_keep_count = max(0, int(getattr(rule, "keep_count", 0)))
        if rule.kind not in self._destroy_rule_kinds:
            rule.kind = DESTROY_KIND_EXPLICIT_MODELS
        rule.keep_count = legacy_keep_count
        rule.model_ids = legacy_model_ids
        rule.whitelist_targets = merge_whitelist_targets_with_legacy_model_ids(
            legacy_model_ids,
            getattr(rule, "whitelist_targets", []),
            default_keep_count=legacy_keep_count,
        )
        rule.rarities = normalize_rarity_flags(getattr(rule, "rarities", {}))
        rule.name = normalize_rule_name(getattr(rule, "name", ""))
        if rule.kind in (DESTROY_KIND_WEAPONS, DESTROY_KIND_ARMOR):
            rule.model_ids = []
            rule.keep_count = 0
            rule.whitelist_targets = []
        else:
            rule.model_ids = get_whitelist_target_model_ids(rule.whitelist_targets)
            rule.keep_count = 0
        return rule

    def normalize_destroy_rules(self, rules: list[DestroyRule]) -> list[DestroyRule]:
        return [self.normalize_destroy_rule(rule) for rule in rules]

    def normalize_salvage_rule(self, raw_rule: object) -> SalvageRule | None:
        """Convert a saved or live salvage rule into its bounded canonical representation."""

        if isinstance(raw_rule, SalvageRule):
            rule = SalvageRule(
                enabled=bool(raw_rule.enabled),
                model_ids=dedupe_model_ids(raw_rule.model_ids),
                target_common_material_model_ids=normalize_common_material_model_ids(
                    getattr(raw_rule, "target_common_material_model_ids", [])
                ),
                rarities=normalize_salvage_rarity_flags(raw_rule.rarities),
                categories=normalize_salvage_category_flags(raw_rule.categories),
                target_armor_upgrade_identifiers=_dedupe_identifiers(
                    coerce_list(getattr(raw_rule, "target_armor_upgrade_identifiers", []))
                ),
                target_weapon_mod_identifiers=_dedupe_identifiers(
                    coerce_list(getattr(raw_rule, "target_weapon_mod_identifiers", []))
                ),
                target_weapon_mod_thresholds=normalize_weapon_mod_threshold_rules(
                    coerce_list(getattr(raw_rule, "target_weapon_mod_thresholds", []))
                ),
                target_weapon_mod_variants=self.normalize_weapon_mod_variant_rules(
                    coerce_list(getattr(raw_rule, "target_weapon_mod_variants", []))
                ),
                target_weapon_mod_variant_thresholds=self.normalize_weapon_mod_variant_threshold_rules(
                    coerce_list(getattr(raw_rule, "target_weapon_mod_variant_thresholds", []))
                ),
                salvage_option=_normalize_salvage_rule_mode(raw_rule.salvage_option),
                name=normalize_rule_name(getattr(raw_rule, "name", "")),
            )
        elif isinstance(raw_rule, dict):
            rule = SalvageRule(
                enabled=bool(raw_rule.get("enabled", True)),
                model_ids=dedupe_model_ids([
                    _safe_int(value, 0)
                    for value in coerce_list(raw_rule.get("model_ids", []))
                ]),
                target_common_material_model_ids=normalize_common_material_model_ids(
                    raw_rule.get("target_common_material_model_ids", [])
                ),
                rarities=normalize_salvage_rarity_flags(raw_rule.get("rarities", {})),
                categories=normalize_salvage_category_flags(raw_rule.get("categories", {})),
                target_armor_upgrade_identifiers=_dedupe_identifiers(
                    coerce_list(raw_rule.get("target_armor_upgrade_identifiers", []))
                ),
                target_weapon_mod_identifiers=_dedupe_identifiers(
                    coerce_list(raw_rule.get("target_weapon_mod_identifiers", []))
                ),
                target_weapon_mod_thresholds=normalize_weapon_mod_threshold_rules(
                    coerce_list(raw_rule.get("target_weapon_mod_thresholds", []))
                ),
                target_weapon_mod_variants=self.normalize_weapon_mod_variant_rules(
                    coerce_list(raw_rule.get("target_weapon_mod_variants", []))
                ),
                target_weapon_mod_variant_thresholds=self.normalize_weapon_mod_variant_threshold_rules(
                    coerce_list(raw_rule.get("target_weapon_mod_variant_thresholds", []))
                ),
                salvage_option=_normalize_salvage_rule_mode(raw_rule.get("salvage_option", SALVAGE_OPTION_DEFAULT)),
                name=normalize_rule_name(raw_rule.get("name", "")),
            )
        else:
            return None

        return rule

    def normalize_salvage_rules(self, raw_rules: object) -> list[SalvageRule]:
        normalized_rules: list[SalvageRule] = []
        for raw_rule in coerce_list(raw_rules):
            normalized_rule = self.normalize_salvage_rule(raw_rule)
            if normalized_rule is None:
                continue
            normalized_rules.append(normalized_rule)
        return normalized_rules

    def normalize_salvage_settings(self, raw_settings: object) -> SalvageSettings:
        """Normalize salvage automation and migrate legacy single-rule settings without enabling it."""

        if isinstance(raw_settings, SalvageSettings):
            legacy_model_ids = dedupe_model_ids(raw_settings.model_ids)
            legacy_rarities = normalize_salvage_rarity_flags(raw_settings.rarities)
            legacy_categories = normalize_salvage_category_flags(raw_settings.categories)
            normalized_rules = self.normalize_salvage_rules(raw_settings.rules)
            if not normalized_rules and (
                legacy_model_ids
                or any(bool(value) for value in legacy_rarities.values())
                or any(bool(value) for value in legacy_categories.values())
            ):
                normalized_rules = [
                    SalvageRule(
                        enabled=True,
                        model_ids=list(legacy_model_ids),
                        rarities=dict(legacy_rarities),
                        categories=dict(legacy_categories),
                        salvage_option=SALVAGE_OPTION_MATERIALS,
                    )
                ]
            return SalvageSettings(
                model_ids=legacy_model_ids,
                rarities=legacy_rarities,
                categories=legacy_categories,
                on_inventory_change=bool(raw_settings.on_inventory_change),
                rules=normalized_rules,
            )

        if not isinstance(raw_settings, dict):
            raw_settings = {}

        legacy_model_ids = dedupe_model_ids([
            _safe_int(value, 0)
            for value in coerce_list(raw_settings.get("model_ids", []))
        ])
        legacy_rarities = normalize_salvage_rarity_flags(raw_settings.get("rarities", {}))
        legacy_categories = normalize_salvage_category_flags(raw_settings.get("categories", {}))
        rules = self.normalize_salvage_rules(raw_settings.get("rules", []))
        if not rules and (
            legacy_model_ids
            or any(bool(value) for value in legacy_rarities.values())
            or any(bool(value) for value in legacy_categories.values())
        ):
            rules = [
                SalvageRule(
                    enabled=True,
                    model_ids=list(legacy_model_ids),
                    rarities=dict(legacy_rarities),
                    categories=dict(legacy_categories),
                    salvage_option=SALVAGE_OPTION_MATERIALS,
                )
            ]

        return SalvageSettings(
            model_ids=legacy_model_ids,
            rarities=legacy_rarities,
            categories=legacy_categories,
            on_inventory_change=bool(raw_settings.get("on_inventory_change", False)),
            rules=rules,
        )

    def serialize_salvage_settings(self, settings: SalvageSettings) -> dict[str, object]:
        normalized_settings = self.normalize_salvage_settings(settings)
        return {
            "model_ids": list(normalized_settings.model_ids),
            "rarities": dict(normalized_settings.rarities),
            "categories": dict(normalized_settings.categories),
            "on_inventory_change": bool(normalized_settings.on_inventory_change),
            "rules": [
                self.serialize_salvage_rule(rule)
                for rule in normalized_settings.rules
            ],
        }

    def serialize_salvage_rule(self, rule: SalvageRule) -> dict[str, object]:
        normalized_rule = self.normalize_salvage_rule(rule) or SalvageRule()
        payload: dict[str, object] = {
            "enabled": bool(normalized_rule.enabled),
            "model_ids": list(normalized_rule.model_ids),
            "rarities": dict(normalized_rule.rarities),
            "categories": dict(normalized_rule.categories),
            "salvage_option": _normalize_salvage_rule_mode(normalized_rule.salvage_option),
            "name": normalize_rule_name(normalized_rule.name),
        }
        if normalized_rule.target_common_material_model_ids:
            payload["target_common_material_model_ids"] = list(normalized_rule.target_common_material_model_ids)
        if normalized_rule.target_armor_upgrade_identifiers:
            payload["target_armor_upgrade_identifiers"] = list(normalized_rule.target_armor_upgrade_identifiers)
        if normalized_rule.target_weapon_mod_identifiers:
            payload["target_weapon_mod_identifiers"] = list(normalized_rule.target_weapon_mod_identifiers)
        if normalized_rule.target_weapon_mod_thresholds:
            payload["target_weapon_mod_thresholds"] = serialize_weapon_mod_threshold_rules(
                normalized_rule.target_weapon_mod_thresholds
            )
        if normalized_rule.target_weapon_mod_variants:
            payload["target_weapon_mod_variants"] = self.serialize_weapon_mod_variant_rules(
                normalized_rule.target_weapon_mod_variants
            )
        if normalized_rule.target_weapon_mod_variant_thresholds:
            payload["target_weapon_mod_variant_thresholds"] = self.serialize_weapon_mod_variant_threshold_rules(
                normalized_rule.target_weapon_mod_variant_thresholds
            )
        return payload

    def serialize_sell_rule(self, rule: SellRule) -> dict[str, object]:
        normalized_rule = self.normalize_sell_rule(rule)
        if normalized_rule is None:
            return {}

        payload = asdict(normalized_rule)
        payload["rule_id"] = str(normalized_rule.rule_id or "").strip()
        payload["whitelist_targets"] = serialize_whitelist_targets(normalized_rule.whitelist_targets)
        payload["protected_weapon_mod_thresholds"] = serialize_weapon_mod_threshold_rules(
            normalized_rule.protected_weapon_mod_thresholds
        )
        payload["protected_weapon_mod_variants"] = self.serialize_weapon_mod_variant_rules(
            normalized_rule.protected_weapon_mod_variants
        )
        payload["protected_weapon_mod_variant_thresholds"] = self.serialize_weapon_mod_variant_threshold_rules(
            normalized_rule.protected_weapon_mod_variant_thresholds
        )
        return payload

    def serialize_destroy_rule(self, rule: DestroyRule) -> dict[str, object]:
        normalized_rule = self.normalize_destroy_rule(rule)
        payload = asdict(normalized_rule)
        payload["whitelist_targets"] = serialize_whitelist_targets(normalized_rule.whitelist_targets)
        return payload

    def build_default_profile_payload(self, *, include_rule_templates: bool) -> dict[str, object]:
        """Build a fresh current payload without reading or changing live settings."""

        return {
            "version": PROFILE_VERSION,
            "auto_cleanup_on_outpost_entry": False,
            "gold_balance_enabled": False,
            "gold_balance_on_outpost_entry": False,
            "gold_balance_after_mr_trading": False,
            "gold_balance_after_manual_session": False,
            "target_carried_gold": DEFAULT_TARGET_CARRIED_GOLD,
            "auto_sell_on_manual_vendor_interaction": False,
            "auto_buy_on_manual_vendor_interaction": False,
            "manual_vendor_auto_buy_categories": default_manual_vendor_category_flags(MANUAL_VENDOR_BUY_CATEGORY_KINDS),
            "manual_vendor_auto_sell_categories": default_manual_vendor_category_flags(
                MANUAL_VENDOR_SELL_CATEGORY_KINDS
            ),
            "auto_sell_to_any_merchant": False,
            "auto_sell_any_merchant_normal_items": False,
            "auto_sell_any_merchant_materials": False,
            "auto_sell_any_merchant_runes": False,
            "inventory_right_click_shortcuts_enabled": False,
            "inventory_right_click_live_actions_enabled": False,
            "destroy_auto_enabled": False,
            "auto_travel_enabled": False,
            "target_outpost_id": 0,
            "favorite_outpost_ids": [],
            "debug_logging": False,
            "helper_tooltips_enabled": HELPER_TOOLTIPS_ENABLED_DEFAULT,
            "detailed_preview": False,
            "buy_rules": (
                [asdict(rule) for rule in default_buy_rules()]
                if include_rule_templates
                else []
            ),
            "sell_rules": (
                [asdict(rule) for rule in default_sell_rules()]
                if include_rule_templates
                else []
            ),
            "destroy_rules": (
                [asdict(rule) for rule in default_destroy_rules()]
                if include_rule_templates
                else []
            ),
            "identify_settings": serialize_identify_settings(IdentifySettings()),
            "salvage_settings": self.serialize_salvage_settings(SalvageSettings()),
            "cleanup_targets": [],
            "cleanup_blacklist_model_ids": [],
            "cleanup_protection_sources": [],
            "protected_item_model_ids": [],
            "protected_item_targets": [],
        }

    def normalize_profile_payload(
        self,
        raw_payload: object,
        *,
        get_outpost_entries: Callable[[], list[dict[str, object]]],
        has_crafter_recipe: Callable[[int], bool],
    ) -> dict[str, object]:
        """Validate and migrate a decoded profile without weakening safe defaults.

        Missing automatic, destructive, and live-action fields remain disabled. Legacy rule
        shapes are converted to current structures, while malformed container types raise so
        the caller can preserve and snapshot the unreadable source file.
        """

        if not isinstance(raw_payload, dict):
            raise ValueError("Merchant Rules profile must be a JSON object.")

        buy_rules_raw = raw_payload.get("buy_rules", [asdict(rule) for rule in default_buy_rules()])
        if not isinstance(buy_rules_raw, list):
            raise ValueError("Merchant Rules buy_rules must be a list.")

        sell_rules_raw = raw_payload.get("sell_rules", [asdict(rule) for rule in default_sell_rules()])
        if not isinstance(sell_rules_raw, list):
            raise ValueError("Merchant Rules sell_rules must be a list.")

        destroy_rules_raw = raw_payload.get("destroy_rules", [asdict(rule) for rule in default_destroy_rules()])
        if not isinstance(destroy_rules_raw, list):
            raise ValueError("Merchant Rules destroy_rules must be a list.")

        identify_settings_raw = raw_payload.get("identify_settings", {})
        if identify_settings_raw is None:
            identify_settings_raw = {}
        if not isinstance(identify_settings_raw, dict):
            raise ValueError("Merchant Rules identify_settings must be an object.")

        salvage_settings_raw = raw_payload.get("salvage_settings", {})
        if salvage_settings_raw is None:
            salvage_settings_raw = {}
        if not isinstance(salvage_settings_raw, dict):
            raise ValueError("Merchant Rules salvage_settings must be an object.")

        cleanup_targets_present = "cleanup_targets" in raw_payload
        cleanup_targets_raw = raw_payload.get("cleanup_targets", [])
        if cleanup_targets_raw is None:
            cleanup_targets_raw = []
        if not isinstance(cleanup_targets_raw, list):
            raise ValueError("Merchant Rules cleanup_targets must be a list.")

        cleanup_blacklist_present = "cleanup_blacklist_model_ids" in raw_payload
        cleanup_blacklist_raw = raw_payload.get("cleanup_blacklist_model_ids", [])
        if cleanup_blacklist_raw is None:
            cleanup_blacklist_raw = []
        if not isinstance(cleanup_blacklist_raw, list):
            raise ValueError("Merchant Rules cleanup_blacklist_model_ids must be a list.")

        cleanup_sources_present = "cleanup_protection_sources" in raw_payload
        cleanup_sources_raw = raw_payload.get("cleanup_protection_sources", [])
        if cleanup_sources_raw is None:
            cleanup_sources_raw = []
        if not isinstance(cleanup_sources_raw, list):
            raise ValueError("Merchant Rules cleanup_protection_sources must be a list.")

        protected_item_model_ids_raw = raw_payload.get("protected_item_model_ids", [])
        if protected_item_model_ids_raw is None:
            protected_item_model_ids_raw = []
        if not isinstance(protected_item_model_ids_raw, list):
            raise ValueError("Merchant Rules protected_item_model_ids must be a list.")

        protected_item_targets_raw = raw_payload.get("protected_item_targets", [])
        if protected_item_targets_raw is None:
            protected_item_targets_raw = []
        if not isinstance(protected_item_targets_raw, list):
            raise ValueError("Merchant Rules protected_item_targets must be a list.")

        manual_vendor_auto_buy_categories = normalize_manual_vendor_category_flags(
            raw_payload.get("manual_vendor_auto_buy_categories"),
            MANUAL_VENDOR_BUY_CATEGORY_KINDS,
            field_name="manual_vendor_auto_buy_categories",
        )
        manual_vendor_auto_sell_categories = normalize_manual_vendor_category_flags(
            raw_payload.get("manual_vendor_auto_sell_categories"),
            MANUAL_VENDOR_SELL_CATEGORY_KINDS,
            field_name="manual_vendor_auto_sell_categories",
        )

        favorite_outpost_ids_raw = raw_payload.get("favorite_outpost_ids", [])
        if favorite_outpost_ids_raw is None:
            favorite_outpost_ids_raw = []
        if not isinstance(favorite_outpost_ids_raw, list):
            raise ValueError("Merchant Rules favorite_outpost_ids must be a list.")

        normalized_buy_rules: list[BuyRule] = []
        for entry in buy_rules_raw:
            if not isinstance(entry, dict):
                raise ValueError("Merchant Rules buy rule entries must be objects.")
            rule = BuyRule(
                enabled=bool(entry.get("enabled", False)),
                kind=str(entry.get("kind", BUY_KIND_MERCHANT_STOCK)),
                merchant_type=str(entry.get("merchant_type", MERCHANT_TYPE_MERCHANT)),
                model_id=_safe_int(entry.get("model_id", 0), 0),
                target_count=_safe_int(entry.get("target_count", 0), 0),
                max_per_run=_safe_int(entry.get("max_per_run", 0), 0),
                merchant_stock_targets=normalize_merchant_stock_targets(coerce_list(entry.get("merchant_stock_targets", []))),
                material_targets=normalize_material_targets(coerce_list(entry.get("material_targets", []))),
                rune_targets=normalize_rune_trader_targets(coerce_list(entry.get("rune_targets", []))),
                consumable_crafter_count_mode=normalize_consumable_crafter_count_mode(
                    entry.get("consumable_crafter_count_mode", CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT)
                ),
                name=normalize_rule_name(entry.get("name", "")),
            )
            normalized_buy_rule = self.normalize_buy_rule(rule, has_crafter_recipe=has_crafter_recipe)
            if normalized_buy_rule is not None:
                normalized_buy_rules.append(normalized_buy_rule)

        normalized_sell_rules: list[SellRule] = []
        migrated_cleanup_targets_by_key: dict[tuple[int, str], CleanupTarget] = {}
        migrated_cleanup_sources: list[CleanupProtectionSource] = []
        seen_sell_rule_ids: set[str] = set()
        for entry in sell_rules_raw:
            if not isinstance(entry, dict):
                raise ValueError("Merchant Rules sell rule entries must be objects.")
            raw_whitelist_targets = normalize_whitelist_targets(coerce_list(entry.get("whitelist_targets", [])))
            normalized_rule = self.normalize_sell_rule(
                SellRule(
                    enabled=bool(entry.get("enabled", False)),
                    kind=str(entry.get("kind", SELL_KIND_EXPLICIT_MODELS)),
                    merchant_type=str(entry.get("merchant_type", MERCHANT_TYPE_MERCHANT)),
                    rule_id=normalize_rule_id(entry.get("rule_id", "")),
                    model_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("model_ids", []))],
                    keep_count=_safe_int(entry.get("keep_count", 0), 0),
                    whitelist_targets=raw_whitelist_targets,
                    rarities=normalize_rarity_flags(entry.get("rarities", {})),
                    blacklist_model_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("blacklist_model_ids", []))],
                    blacklist_item_type_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("blacklist_item_type_ids", []))],
                    all_weapons_min_requirement=self.normalize_all_weapons_requirement_range_from_payload(entry)[0],
                    all_weapons_max_requirement=self.normalize_all_weapons_requirement_range_from_payload(entry)[1],
                    all_weapons_perfect_stats_only=bool(entry.get("all_weapons_perfect_stats_only", False)),
                    protected_weapon_requirement_rules=self.normalize_weapon_requirement_rules(coerce_list(entry.get("protected_weapon_requirement_rules", []))),
                    protected_weapon_mod_identifiers=_dedupe_identifiers(coerce_list(entry.get("protected_weapon_mod_identifiers", []))),
                    protected_weapon_mod_thresholds=normalize_weapon_mod_threshold_rules(coerce_list(entry.get("protected_weapon_mod_thresholds", []))),
                    protected_weapon_mod_variants=self.normalize_weapon_mod_variant_rules(coerce_list(entry.get("protected_weapon_mod_variants", []))),
                    protected_weapon_mod_variant_thresholds=self.normalize_weapon_mod_variant_threshold_rules(coerce_list(entry.get("protected_weapon_mod_variant_thresholds", []))),
                    rune_sell_targets=normalize_rune_sell_targets(coerce_list(entry.get("rune_sell_targets", []))),
                    protected_rune_identifiers=_dedupe_identifiers(coerce_list(entry.get("protected_rune_identifiers", []))),
                    skip_customized=bool(entry.get("skip_customized", True)),
                    skip_unidentified=bool(entry.get("skip_unidentified", True)),
                    include_standalone_runes=bool(entry.get("include_standalone_runes", False)),
                    deposit_protected_matches=bool(entry.get("deposit_protected_matches", False)),
                    sell_from_xunlai=bool(entry.get("sell_from_xunlai", False)),
                    include_material_storage=bool(entry.get("include_material_storage", False)),
                    name=normalize_rule_name(entry.get("name", "")),
                )
            )
            if normalized_rule is None:
                continue
            normalized_rule.rule_id = ensure_unique_rule_id(
                normalized_rule.rule_id,
                seen_ids=seen_sell_rule_ids,
                prefix="sell",
                fallback_seed=f"{len(normalized_sell_rules)}:{normalized_rule.kind}:{normalized_rule.name}",
            )
            normalized_sell_rules.append(normalized_rule)

            if not cleanup_targets_present:
                for whitelist_target in raw_whitelist_targets:
                    if not bool(getattr(whitelist_target, "deposit_to_storage", False)):
                        continue
                    safe_model_id = max(0, int(whitelist_target.model_id))
                    if safe_model_id <= 0:
                        continue
                    target_scope = (
                        infer_cleanup_target_scope_from_model_id(safe_model_id)
                        if normalized_rule.kind == SELL_KIND_COMMON_MATERIALS
                        else CLEANUP_TARGET_SCOPE_EXACT
                    )
                    target_key = (safe_model_id, target_scope)
                    existing_target = migrated_cleanup_targets_by_key.get(target_key)
                    keep_on_character = 0
                    if existing_target is None or keep_on_character > existing_target.keep_on_character:
                        migrated_cleanup_targets_by_key[target_key] = CleanupTarget(
                            model_id=safe_model_id,
                            keep_on_character=keep_on_character,
                            scope=target_scope,
                        )

            if (
                not cleanup_sources_present
                and normalized_rule.kind in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR)
                and bool(entry.get("deposit_protected_matches", False))
            ):
                migrated_cleanup_sources.append(
                    CleanupProtectionSource(sell_rule_id=normalized_rule.rule_id)
                )

        destroy_rules_to_normalize: list[DestroyRule] = []
        for entry in destroy_rules_raw:
            if not isinstance(entry, dict):
                raise ValueError("Merchant Rules destroy rule entries must be objects.")
            destroy_rules_to_normalize.append(
                DestroyRule(
                    enabled=bool(entry.get("enabled", False)),
                    kind=str(entry.get("kind", DESTROY_KIND_EXPLICIT_MODELS)),
                    model_ids=[_safe_int(value, 0) for value in coerce_list(entry.get("model_ids", []))],
                    keep_count=_safe_int(entry.get("keep_count", 0), 0),
                    whitelist_targets=normalize_whitelist_targets(coerce_list(entry.get("whitelist_targets", []))),
                    rarities=normalize_rarity_flags(entry.get("rarities", {})),
                    name=normalize_rule_name(entry.get("name", "")),
                )
            )
        normalized_destroy_rules = self.normalize_destroy_rules(destroy_rules_to_normalize)
        normalized_cleanup_targets = normalize_cleanup_targets(cleanup_targets_raw)
        if not cleanup_targets_present:
            normalized_cleanup_targets = normalize_cleanup_targets(
                [asdict(target) for target in migrated_cleanup_targets_by_key.values()]
            )

        normalized_cleanup_blacklist_model_ids = normalize_cleanup_blacklist_model_ids(cleanup_blacklist_raw)
        if not cleanup_blacklist_present:
            normalized_cleanup_blacklist_model_ids = normalize_cleanup_blacklist_model_ids([])

        normalized_cleanup_sources = normalize_cleanup_protection_sources(cleanup_sources_raw)
        if not cleanup_sources_present:
            normalized_cleanup_sources = normalize_cleanup_protection_sources(
                [asdict(source) for source in migrated_cleanup_sources]
            )

        normalized_protected_item_model_ids = normalize_protected_item_model_ids(protected_item_model_ids_raw)
        normalized_protected_item_targets = self.normalize_protected_item_targets(
            protected_item_targets_raw,
            strict=True,
        )

        return {
            "version": PROFILE_VERSION,
            "auto_cleanup_on_outpost_entry": bool(raw_payload.get("auto_cleanup_on_outpost_entry", False)),
            "gold_balance_enabled": bool(raw_payload.get("gold_balance_enabled", False)),
            "gold_balance_on_outpost_entry": bool(raw_payload.get("gold_balance_on_outpost_entry", False)),
            "gold_balance_after_mr_trading": bool(raw_payload.get("gold_balance_after_mr_trading", False)),
            "gold_balance_after_manual_session": bool(raw_payload.get("gold_balance_after_manual_session", False)),
            "target_carried_gold": normalize_gold_target(
                raw_payload.get("target_carried_gold", DEFAULT_TARGET_CARRIED_GOLD)
            ),
            "auto_sell_on_manual_vendor_interaction": bool(raw_payload.get("auto_sell_on_manual_vendor_interaction", False)),
            "auto_buy_on_manual_vendor_interaction": bool(raw_payload.get("auto_buy_on_manual_vendor_interaction", False)),
            "manual_vendor_auto_buy_categories": manual_vendor_auto_buy_categories,
            "manual_vendor_auto_sell_categories": manual_vendor_auto_sell_categories,
            "auto_sell_to_any_merchant": bool(raw_payload.get("auto_sell_to_any_merchant", False)),
            "auto_sell_any_merchant_normal_items": bool(raw_payload.get("auto_sell_any_merchant_normal_items", False)),
            "auto_sell_any_merchant_materials": bool(raw_payload.get("auto_sell_any_merchant_materials", False)),
            "auto_sell_any_merchant_runes": bool(raw_payload.get("auto_sell_any_merchant_runes", False)),
            "inventory_right_click_shortcuts_enabled": bool(
                raw_payload.get("inventory_right_click_shortcuts_enabled", False)
            ),
            "inventory_right_click_live_actions_enabled": bool(
                raw_payload.get("inventory_right_click_live_actions_enabled", False)
            ),
            "destroy_auto_enabled": bool(raw_payload.get("destroy_auto_enabled", False)),
            "auto_travel_enabled": bool(raw_payload.get("auto_travel_enabled", False)),
            "target_outpost_id": max(0, _safe_int(raw_payload.get("target_outpost_id", 0), 0)),
            "favorite_outpost_ids": normalize_outpost_ids(
                coerce_list(favorite_outpost_ids_raw), get_outpost_entries=get_outpost_entries
            ),
            "debug_logging": bool(raw_payload.get("debug_logging", False)),
            "helper_tooltips_enabled": bool(
                raw_payload.get("helper_tooltips_enabled", HELPER_TOOLTIPS_ENABLED_DEFAULT)
            ),
            "detailed_preview": bool(raw_payload.get("detailed_preview", False)),
            "buy_rules": [asdict(rule) for rule in normalized_buy_rules],
            "sell_rules": [self.serialize_sell_rule(rule) for rule in normalized_sell_rules],
            "destroy_rules": [self.serialize_destroy_rule(rule) for rule in normalized_destroy_rules],
            "identify_settings": serialize_identify_settings(normalize_identify_settings(identify_settings_raw)),
            "salvage_settings": self.serialize_salvage_settings(self.normalize_salvage_settings(salvage_settings_raw)),
            "cleanup_targets": serialize_cleanup_targets(normalized_cleanup_targets),
            "cleanup_blacklist_model_ids": serialize_cleanup_blacklist_model_ids(normalized_cleanup_blacklist_model_ids),
            "cleanup_protection_sources": serialize_cleanup_protection_sources(normalized_cleanup_sources),
            "protected_item_model_ids": serialize_protected_item_model_ids(normalized_protected_item_model_ids),
            "protected_item_targets": self.serialize_protected_item_targets(normalized_protected_item_targets),
        }
