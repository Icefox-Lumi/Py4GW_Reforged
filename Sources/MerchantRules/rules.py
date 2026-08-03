from dataclasses import dataclass
from dataclasses import field


@dataclass
class MaterialTarget:
    model_id: int = 0
    target_count: int = 0
    max_per_run: int = 0
    after_purchase: str = "keep"


@dataclass
class MerchantStockTarget:
    model_id: int = 0
    target_count: int = 0
    max_per_run: int = 0
    after_purchase: str = "keep"


@dataclass
class RuneTraderTarget:
    identifier: str = ""
    target_count: int = 0
    max_per_run: int = 0
    after_purchase: str = "keep"


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
    kind: str = "merchant_stock_target"
    merchant_type: str = "merchant"
    model_id: int = 0
    target_count: int = 0
    max_per_run: int = 0
    merchant_stock_targets: list[MerchantStockTarget] = field(default_factory=list)
    material_targets: list[MaterialTarget] = field(default_factory=list)
    rune_targets: list[RuneTraderTarget] = field(default_factory=list)
    consumable_crafter_count_mode: str = "craft_amount"
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
    kind: str = "sell_explicit_models"
    merchant_type: str = "merchant"
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
    kind: str = "destroy_explicit_models"
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
    rarities: dict[str, bool] = field(default_factory=dict)
    categories: dict[str, bool] = field(default_factory=dict)
    target_weapon_mod_identifiers: list[str] = field(default_factory=list)
    target_weapon_mod_thresholds: list[WeaponModThresholdRule] = field(default_factory=list)
    target_weapon_mod_variants: list[WeaponModVariantRule] = field(default_factory=list)
    target_weapon_mod_variant_thresholds: list[WeaponModVariantThresholdRule] = field(default_factory=list)
    salvage_option: str = "materials"
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
