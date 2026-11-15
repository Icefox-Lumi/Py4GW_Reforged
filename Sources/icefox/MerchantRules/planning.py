"""Canonical plans, item selection, projections, assessment, and allocation.

The widget retains native acquisition, preview publication coordination,
application, execution reservations and live execution. Selection is evidence,
not action authority; existing protection interpretation remains with its owner.
"""

from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import TYPE_CHECKING
from typing import Protocol
from typing import TypedDict
from typing import TypeGuard

from Sources.icefox.MerchantRules.configuration import AFTER_PURCHASE_KEEP
from Sources.icefox.MerchantRules.configuration import AFTER_PURCHASE_REMOVE_ENTRY
from Sources.icefox.MerchantRules.configuration import AFTER_PURCHASE_RESET_QUANTITY
from Sources.icefox.MerchantRules.configuration import ALL_CRAFTING_MATERIAL_MODEL_IDS
from Sources.icefox.MerchantRules.configuration import BUY_KIND_CONSUMABLE_CRAFTER_TARGET
from Sources.icefox.MerchantRules.configuration import BUY_KIND_MATERIAL_TARGET
from Sources.icefox.MerchantRules.configuration import BUY_KIND_MERCHANT_STOCK
from Sources.icefox.MerchantRules.configuration import BUY_KIND_RUNE_TRADER_TARGET
from Sources.icefox.MerchantRules.configuration import BUY_KIND_SCROLL_TRADER_TARGET
from Sources.icefox.MerchantRules.configuration import CLEANUP_TARGET_SCOPE_COMMON_MATERIAL
from Sources.icefox.MerchantRules.configuration import CLEANUP_TARGET_SCOPE_EXACT
from Sources.icefox.MerchantRules.configuration import CLEANUP_TARGET_SCOPE_RARE_MATERIAL
from Sources.icefox.MerchantRules.configuration import COMMON_CRAFTING_MATERIAL_MODEL_IDS
from Sources.icefox.MerchantRules.configuration import CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT
from Sources.icefox.MerchantRules.configuration import DESTROY_KIND_ARMOR
from Sources.icefox.MerchantRules.configuration import DESTROY_KIND_EXPLICIT_MODELS
from Sources.icefox.MerchantRules.configuration import DESTROY_KIND_MATERIALS
from Sources.icefox.MerchantRules.configuration import DESTROY_KIND_WEAPONS
from Sources.icefox.MerchantRules.configuration import MATERIAL_BATCH_SIZE
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_CONSUMABLE_CRAFTER
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_INVENTORY
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_MATERIALS
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_MERCHANT
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_RUNE_TRADER
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_SCROLL_TRADER
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_STORAGE
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_TRAVEL
from Sources.icefox.MerchantRules.configuration import RARE_CRAFTING_MATERIAL_MODEL_IDS
from Sources.icefox.MerchantRules.configuration import SALVAGE_CATEGORY_ARMOR
from Sources.icefox.MerchantRules.configuration import SALVAGE_CATEGORY_MATERIALS
from Sources.icefox.MerchantRules.configuration import SALVAGE_CATEGORY_OTHER
from Sources.icefox.MerchantRules.configuration import SALVAGE_CATEGORY_WEAPONS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_ARMOR
from Sources.icefox.MerchantRules.configuration import SELL_KIND_COMMON_MATERIALS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_EXPLICIT_MODELS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_RUNE_TRADER_TARGET
from Sources.icefox.MerchantRules.configuration import SELL_KIND_WEAPONS
from Sources.icefox.MerchantRules.configuration import BuyRule
from Sources.icefox.MerchantRules.configuration import CleanupProtectionSource
from Sources.icefox.MerchantRules.configuration import CleanupTarget
from Sources.icefox.MerchantRules.configuration import DestroyRule
from Sources.icefox.MerchantRules.configuration import IdentifySettings
from Sources.icefox.MerchantRules.configuration import MaterialTarget
from Sources.icefox.MerchantRules.configuration import MerchantStockTarget
from Sources.icefox.MerchantRules.configuration import RuneSellTarget
from Sources.icefox.MerchantRules.configuration import RuneTraderTarget
from Sources.icefox.MerchantRules.configuration import SalvageRule
from Sources.icefox.MerchantRules.configuration import SalvageSettings
from Sources.icefox.MerchantRules.configuration import SellRule
from Sources.icefox.MerchantRules.configuration import WeaponModThresholdRule
from Sources.icefox.MerchantRules.configuration import WeaponModVariantRule
from Sources.icefox.MerchantRules.configuration import WeaponModVariantThresholdRule
from Sources.icefox.MerchantRules.configuration import WhitelistTarget
from Sources.icefox.MerchantRules.configuration import get_whitelist_target_model_ids
from Sources.icefox.MerchantRules.configuration import (
    infer_cleanup_target_scope_from_model_id as _infer_cleanup_target_scope_from_model_id,
)
from Sources.icefox.MerchantRules.configuration import (
    normalize_after_purchase_action as _normalize_after_purchase_action,
)
from Sources.icefox.MerchantRules.configuration import (
    normalize_cleanup_blacklist_model_ids as _normalize_cleanup_blacklist_model_ids,
)
from Sources.icefox.MerchantRules.configuration import (
    normalize_cleanup_protection_sources as _normalize_cleanup_protection_sources,
)
from Sources.icefox.MerchantRules.configuration import normalize_cleanup_target_scope as _normalize_cleanup_target_scope
from Sources.icefox.MerchantRules.configuration import normalize_cleanup_targets as _normalize_cleanup_targets
from Sources.icefox.MerchantRules.configuration import (
    normalize_consumable_crafter_count_mode as _normalize_consumable_crafter_count_mode,
)
from Sources.icefox.MerchantRules.configuration import (
    normalize_merchant_stock_targets as _normalize_merchant_stock_targets,
)
from Sources.icefox.MerchantRules.configuration import normalize_rule_id
from Sources.icefox.MerchantRules.configuration import normalize_rule_id as _normalize_rule_id
from Sources.icefox.MerchantRules.configuration import normalize_rune_identifier
from Sources.icefox.MerchantRules.configuration import normalize_rune_identifier as _normalize_rune_identifier
from Sources.icefox.MerchantRules.configuration import normalize_rune_sell_targets
from Sources.icefox.MerchantRules.configuration import normalize_rune_trader_targets as _normalize_rune_trader_targets
from Sources.icefox.MerchantRules.configuration import normalize_whitelist_targets
from Sources.icefox.MerchantRules.configuration import normalize_whitelist_targets as _normalize_whitelist_targets
from Sources.icefox.MerchantRules.configuration import sell_rule_can_include_material_storage
from Sources.icefox.MerchantRules.item_values import safe_int
from Sources.icefox.MerchantRules.item_values import safe_int as _safe_int
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_ALREADY_DONE
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_BLOCKED
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_NO_MATCH
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_PROTECTED
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_SKIPPED
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_UNSAFE
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_WARNING
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_DEFAULT
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_INSCRIPTION
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_MATERIALS
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_PREFIX
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_OPTION_SUFFIX
from Sources.icefox.MerchantRules.salvage_options import SALVAGE_UPGRADE_OPTIONS
from Sources.icefox.MerchantRules.salvage_options import get_salvage_option_label as _get_salvage_option_label
from Sources.icefox.MerchantRules.salvage_options import (
    is_auto_exact_upgrade_salvage_option as _is_auto_exact_upgrade_salvage_option,
)
from Sources.icefox.MerchantRules.salvage_options import normalize_salvage_rule_mode as _normalize_salvage_rule_mode
from Sources.icefox.MerchantRules.salvage_options import resolve_salvage_operation as _resolve_salvage_operation

if TYPE_CHECKING:
    from Sources.marks_sources.mods_parser import ModDatabase

    from Sources.icefox.MerchantRules.inventory_evidence import ArmorUpgradeIdentity
    from Sources.icefox.MerchantRules.inventory_evidence import InventoryItemInfo
    from Sources.icefox.MerchantRules.requirement_protection import ProtectionPolicy

PLAN_STATE_WILL_EXECUTE = "will execute"
PLAN_STATE_CONDITIONAL = "conditional"
PLAN_STATE_SKIPPED = "skipped"
STORAGE_PLAN_STATE_NOT_NEEDED = "not_needed"
STORAGE_PLAN_STATE_NEEDS_EXACT_SCAN = "needs_exact_scan"
STORAGE_PLAN_STATE_EXACT_READY = "exact_ready"
STORAGE_TRANSFER_WITHDRAW = "withdraw"
STORAGE_TRANSFER_DEPOSIT = "deposit"


@dataclass
class ExecutionPlanEntry:
    """Represent one user-visible planned, conditional, skipped, or blocked action."""

    action_type: str
    merchant_type: str
    label: str
    quantity: int
    state: str
    reason: str = ""
    model_id: int = 0
    status_hint: str = ""


@dataclass(frozen=True)
class PlannedSpecificUpgradeSalvageOwner:
    """Snapshot the Specific-upgrade rule that owns one final execution-plan item."""

    model_id: int
    rule_index: int
    rule_snapshot: SalvageRule


@dataclass
class PurchaseTargetCleanup:
    """Describe post-purchase routing and whether completing a target requires storage access."""

    rule_kind: str = ""
    rule_index: int = -1
    target_key: str = ""
    target_count: int = 0
    max_per_run: int = 0
    after_purchase: str = AFTER_PURCHASE_KEEP
    completes_target: bool = False
    xunlai_involved: bool = False


@dataclass
class PlannedMerchantBuy:
    """Represent an exact quantity to buy from ordinary merchant stock."""

    model_id: int
    quantity: int
    label: str
    cleanup: PurchaseTargetCleanup = field(default_factory=PurchaseTargetCleanup)
    check_xunlai_first: bool = False


@dataclass
class PlannedMaterialBuy:
    """Represent a batch-aware material purchase from a material trader."""

    merchant_type: str
    model_id: int
    quantity: int
    label: str
    batch_size: int = 1
    cleanup: PurchaseTargetCleanup = field(default_factory=PurchaseTargetCleanup)


@dataclass
class PlannedMaterialSale:
    """Represent a quoted material sale with both batch and underlying item quantities."""

    merchant_type: str
    item_id: int
    model_id: int
    label: str
    batches_to_sell: int
    quantity_to_sell: int
    batch_size: int = MATERIAL_BATCH_SIZE


@dataclass
class PlannedTraderSale:
    """Represent one standalone item sale to a specialized trader."""

    item_id: int
    model_id: int
    label: str
    expected_rune_identifiers: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class PlannedTraderBuy:
    """Represent a quantity of a rune or upgrade identifier to buy from its trader."""

    identifier: str
    quantity: int
    label: str
    cleanup: PurchaseTargetCleanup = field(default_factory=PurchaseTargetCleanup)


@dataclass
class PlannedScrollTraderBuy:
    """Represent an exact-model scroll purchase and its post-purchase cleanup policy."""

    model_id: int
    quantity: int
    label: str
    cleanup: PurchaseTargetCleanup = field(default_factory=PurchaseTargetCleanup)


@dataclass
class PlannedConsumableCraft:
    """Represent a consumable craft quantity together with the resolved crafter destination."""

    model_id: int
    quantity: int
    label: str
    vendor_key: str
    vendor_name: str
    coords: tuple[float, float]
    cleanup: PurchaseTargetCleanup = field(default_factory=PurchaseTargetCleanup)


@dataclass
class PlannedStorageTransfer:
    """Represent a bounded deposit or withdrawal selected during preview planning.

    Execution treats the quantity as an upper bound and revalidates the live source,
    destination capacity, and item safety before moving anything.
    """

    direction: str
    key: str
    label: str
    item_id: int
    quantity: int
    model_id: int = 0
    reason: str = ""
    xunlai_first_merchant_stock: bool = False


@dataclass
class PlannedDestroyAction:
    """Describe a destructive action, including any split required to preserve a keep quantity."""

    item_id: int
    model_id: int
    label: str
    quantity_to_destroy: int
    source_quantity: int
    keep_quantity: int = 0
    requires_split: bool = False


@dataclass
class PlanResult:
    """Aggregate the mutable intent produced by preview for later live execution.

    The plan records inventory counts, service requirements, conditional storage state, and
    phase-specific actions. It authorizes no operation by itself; execution rechecks current
    inventory and protection state before consuming these entries.
    """

    entries: list[ExecutionPlanEntry] = field(default_factory=list)
    supported_map: bool = False
    supported_reason: str = ""
    coords: dict[str, tuple[float, float] | None] = field(default_factory=dict)
    travel_to_outpost_id: int = 0
    travel_to_outpost_name: str = ""
    multi_stop_route: bool = False
    multi_stop_consumable_outpost_id: int = 0
    multi_stop_consumable_outpost_name: str = ""
    multi_stop_destination_outpost_id: int = 0
    multi_stop_destination_outpost_name: str = ""
    merchant_stock_buys: list[PlannedMerchantBuy] = field(default_factory=list)
    material_buys: list[PlannedMaterialBuy] = field(default_factory=list)
    rune_trader_buys: list[PlannedTraderBuy] = field(default_factory=list)
    scroll_trader_buys: list[PlannedScrollTraderBuy] = field(default_factory=list)
    consumable_crafter_buys: list[PlannedConsumableCraft] = field(default_factory=list)
    material_sales: list[PlannedMaterialSale] = field(default_factory=list)
    storage_transfers: list[PlannedStorageTransfer] = field(default_factory=list)
    cleanup_transfers: list[PlannedStorageTransfer] = field(default_factory=list)
    identify_claimed_item_ids: list[int] = field(default_factory=list)
    identify_item_ids: list[int] = field(default_factory=list)
    salvage_item_ids: list[int] = field(default_factory=list)
    salvage_specific_upgrade_owners: dict[int, PlannedSpecificUpgradeSalvageOwner] = field(default_factory=dict)
    destroy_actions: list[PlannedDestroyAction] = field(default_factory=list)
    destroy_item_ids: list[int] = field(default_factory=list)
    merchant_sell_item_ids: list[int] = field(default_factory=list)
    rune_trader_sales: list[PlannedTraderSale] = field(default_factory=list)
    storage_plan_state: str = STORAGE_PLAN_STATE_NOT_NEEDED
    storage_exact: bool = False
    inventory_snapshot_captured: bool = False
    inventory_model_counts: dict[int, int] = field(default_factory=dict)
    inventory_item_count: int = 0
    xunlai_first_merchant_stock_targets: dict[int, str] = field(default_factory=dict)
    xunlai_first_storage_scan_reliable: bool = True
    has_actions: bool = False


def get_inventory_model_counts(items: list["InventoryItemInfo"]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for item in items:
        counts[item.model_id] = counts.get(item.model_id, 0) + item.quantity
    return counts


def get_items_after_planned_pre_buy_actions(
    items: list["InventoryItemInfo"],
    plan: PlanResult,
    *,
    quantity_reader: Callable[[int], int],
) -> list["InventoryItemInfo"]:
    remaining_items: list["InventoryItemInfo"] = []
    destroy_quantities_by_item_id: dict[int, int] = {}
    material_sale_quantities_by_item_id: dict[int, int] = {}
    identify_item_ids = {
        int(item_id) for item_id in [*plan.identify_claimed_item_ids, *plan.identify_item_ids] if int(item_id) > 0
    }
    salvage_item_ids = {int(item_id) for item_id in plan.salvage_item_ids if int(item_id) > 0}
    merchant_sell_item_ids = {int(item_id) for item_id in plan.merchant_sell_item_ids if int(item_id) > 0}
    rune_sale_item_ids = {
        int(trader_sale.item_id) for trader_sale in plan.rune_trader_sales if int(trader_sale.item_id) > 0
    }

    if plan.destroy_actions:
        for destroy_action in plan.destroy_actions:
            safe_item_id = int(destroy_action.item_id)
            if safe_item_id <= 0:
                continue
            destroy_quantities_by_item_id[safe_item_id] = destroy_quantities_by_item_id.get(safe_item_id, 0) + max(
                0, int(destroy_action.quantity_to_destroy)
            )
    else:
        for item_id in plan.destroy_item_ids:
            safe_item_id = int(item_id)
            if safe_item_id <= 0:
                continue
            destroy_quantities_by_item_id[safe_item_id] = max(0, int(quantity_reader(safe_item_id)))

    for material_sale in plan.material_sales:
        safe_item_id = int(material_sale.item_id)
        if safe_item_id <= 0:
            continue
        material_sale_quantities_by_item_id[safe_item_id] = material_sale_quantities_by_item_id.get(
            safe_item_id, 0
        ) + max(0, int(material_sale.quantity_to_sell))

    for item in items:
        remaining_quantity = max(0, int(item.quantity))
        if remaining_quantity <= 0:
            continue

        safe_item_id = int(item.item_id)
        remaining_quantity -= max(0, int(destroy_quantities_by_item_id.get(safe_item_id, 0)))
        remaining_quantity -= max(0, int(material_sale_quantities_by_item_id.get(safe_item_id, 0)))
        if (
            safe_item_id in identify_item_ids
            or safe_item_id in salvage_item_ids
            or safe_item_id in merchant_sell_item_ids
            or safe_item_id in rune_sale_item_ids
        ):
            remaining_quantity = 0
        if remaining_quantity <= 0:
            continue
        if remaining_quantity == int(item.quantity):
            remaining_items.append(item)
        else:
            remaining_items.append(replace(item, quantity=remaining_quantity))

    return remaining_items


def apply_planned_transfer_quantities(
    items: list["InventoryItemInfo"],
    transfers: list[PlannedStorageTransfer],
) -> list["InventoryItemInfo"]:
    quantity_by_item_id: dict[int, int] = {}
    for transfer in transfers:
        safe_item_id = int(transfer.item_id)
        if safe_item_id <= 0:
            continue
        quantity_by_item_id[safe_item_id] = quantity_by_item_id.get(safe_item_id, 0) + max(0, int(transfer.quantity))

    next_items: list["InventoryItemInfo"] = []
    for item in items:
        remaining_quantity = max(0, int(item.quantity)) - max(0, int(quantity_by_item_id.get(int(item.item_id), 0)))
        if remaining_quantity <= 0:
            continue
        if remaining_quantity == int(item.quantity):
            next_items.append(item)
        else:
            next_items.append(replace(item, quantity=remaining_quantity))
    return next_items


def build_simulated_model_counts(items: list["InventoryItemInfo"], plan: PlanResult) -> dict[int, int]:
    simulated_counts = get_inventory_model_counts(items)
    item_by_id = {int(item.item_id): item for item in items if int(item.item_id) > 0}

    def subtract_model_quantity(model_id: int, quantity: int) -> None:
        current_quantity = max(0, int(simulated_counts.get(model_id, 0)))
        next_quantity = max(0, current_quantity - max(0, int(quantity)))
        if next_quantity > 0:
            simulated_counts[model_id] = next_quantity
        else:
            simulated_counts.pop(model_id, None)

    material_sale_quantities_by_item_id: dict[int, int] = {}

    for item_id in plan.salvage_item_ids:
        item = item_by_id.get(int(item_id))
        if item is not None:
            subtract_model_quantity(item.model_id, item.quantity)

    if plan.destroy_actions:
        for destroy_action in plan.destroy_actions:
            subtract_model_quantity(destroy_action.model_id, destroy_action.quantity_to_destroy)
    else:
        for item_id in plan.destroy_item_ids:
            item = item_by_id.get(int(item_id))
            if item is not None:
                subtract_model_quantity(item.model_id, item.quantity)

    for material_sale in plan.material_sales:
        safe_item_id = int(material_sale.item_id)
        material_sale_quantities_by_item_id[safe_item_id] = max(
            0, int(material_sale_quantities_by_item_id.get(safe_item_id, 0))
        ) + max(0, int(material_sale.quantity_to_sell))
        subtract_model_quantity(material_sale.model_id, material_sale.quantity_to_sell)

    for item_id in plan.merchant_sell_item_ids:
        item = item_by_id.get(int(item_id))
        if item is not None:
            material_sold_quantity = max(0, int(material_sale_quantities_by_item_id.get(int(item_id), 0)))
            merchant_quantity = max(0, int(item.quantity) - material_sold_quantity)
            if merchant_quantity > 0:
                subtract_model_quantity(item.model_id, merchant_quantity)

    for trader_sale in plan.rune_trader_sales:
        item = item_by_id.get(int(trader_sale.item_id))
        if item is not None:
            subtract_model_quantity(item.model_id, item.quantity)

    return simulated_counts


def is_actionable_preview_entry(entry: ExecutionPlanEntry) -> bool:
    return str(entry.state) in (PLAN_STATE_WILL_EXECUTE, PLAN_STATE_CONDITIONAL)


def split_preview_entries(
    entries: list[ExecutionPlanEntry],
) -> tuple[list[ExecutionPlanEntry], list[ExecutionPlanEntry]]:
    actionable = [entry for entry in entries if is_actionable_preview_entry(entry)]
    skipped = [entry for entry in entries if not is_actionable_preview_entry(entry)]
    return actionable, skipped


def preview_entry_needs_local_storage_access(
    entry: ExecutionPlanEntry,
    *,
    plan: PlanResult,
) -> bool:
    merchant_type = str(entry.merchant_type)
    action_type = str(entry.action_type)
    if merchant_type == MERCHANT_TYPE_STORAGE:
        return True
    if merchant_type == MERCHANT_TYPE_RUNE_TRADER and action_type == "buy":
        return plan_needs_exact_storage_scan(plan)
    if merchant_type == MERCHANT_TYPE_CONSUMABLE_CRAFTER and action_type == "buy":
        return plan_needs_exact_storage_scan(plan)
    return False


def is_preview_entry_available_here(
    entry: ExecutionPlanEntry,
    *,
    availability_here: Mapping[str, bool],
    plan: PlanResult,
) -> bool:
    merchant_type = str(entry.merchant_type)
    action_type = str(entry.action_type)
    if merchant_type == MERCHANT_TYPE_TRAVEL or action_type == "travel":
        return False
    if merchant_type == MERCHANT_TYPE_INVENTORY:
        base_available = True
    else:
        base_available = bool(availability_here.get(merchant_type, False))
    if not base_available:
        return False
    if preview_entry_needs_local_storage_access(entry, plan=plan):
        return bool(availability_here.get(MERCHANT_TYPE_STORAGE, False))
    return True


def get_locally_actionable_preview_counts(
    plan: PlanResult,
    *,
    availability_here: Mapping[str, bool],
) -> tuple[int, int]:
    actionable_entries, skipped_entries = split_preview_entries(plan.entries)
    actionable_here_count = sum(
        1
        for entry in actionable_entries
        if is_preview_entry_available_here(
            entry,
            availability_here=availability_here,
            plan=plan,
        )
    )
    skipped_here_count = len(skipped_entries) + max(0, len(actionable_entries) - actionable_here_count)
    return actionable_here_count, skipped_here_count


def get_preview_entry_counts(entries: list[ExecutionPlanEntry]) -> tuple[int, int, int]:
    direct_count = sum(1 for entry in entries if str(entry.state) == PLAN_STATE_WILL_EXECUTE)
    conditional_count = sum(1 for entry in entries if str(entry.state) == PLAN_STATE_CONDITIONAL)
    skipped_count = len(entries) - direct_count - conditional_count
    return direct_count, conditional_count, max(0, skipped_count)


def plan_has_local_destroy_actions(plan: PlanResult) -> bool:
    return bool(plan.destroy_actions or plan.destroy_item_ids)


def plan_has_local_identify_actions(plan: PlanResult) -> bool:
    return bool(plan.identify_item_ids)


def plan_has_local_salvage_actions(plan: PlanResult) -> bool:
    return bool(plan.salvage_item_ids)


def plan_has_local_storage_actions(plan: PlanResult) -> bool:
    return bool(
        plan.cleanup_transfers
        or any(str(transfer.direction) == STORAGE_TRANSFER_DEPOSIT for transfer in plan.storage_transfers)
    )


def plan_has_conditional_storage_actions(plan: PlanResult) -> bool:
    return any(
        str(entry.action_type) in {"deposit", "withdraw"} and str(entry.state) == PLAN_STATE_CONDITIONAL
        for entry in plan.entries
    )


def plan_has_direct_storage_actions(plan: PlanResult) -> bool:
    return any(
        str(entry.action_type) in {"deposit", "withdraw"} and str(entry.state) == PLAN_STATE_WILL_EXECUTE
        for entry in plan.entries
    )


def plan_has_conditional_cleanup_actions(plan: PlanResult) -> bool:
    return any(
        str(entry.action_type) == "deposit"
        and str(entry.merchant_type) == MERCHANT_TYPE_STORAGE
        and str(entry.state) == PLAN_STATE_CONDITIONAL
        for entry in plan.entries
    )


def plan_has_direct_cleanup_actions(plan: PlanResult) -> bool:
    return any(
        str(entry.action_type) == "deposit"
        and str(entry.merchant_type) == MERCHANT_TYPE_STORAGE
        and str(entry.state) == PLAN_STATE_WILL_EXECUTE
        for entry in plan.entries
    )


def plan_needs_exact_storage_scan(plan: PlanResult) -> bool:
    if str(plan.storage_plan_state) != STORAGE_PLAN_STATE_NEEDS_EXACT_SCAN:
        return False
    return any(
        str(entry.merchant_type) in (MERCHANT_TYPE_RUNE_TRADER, MERCHANT_TYPE_CONSUMABLE_CRAFTER, MERCHANT_TYPE_STORAGE)
        and str(entry.state) == PLAN_STATE_CONDITIONAL
        for entry in plan.entries
    )


MERCHANT_TYPE_RARE_MATERIALS = "rare_material_trader"
RUNE_STANDALONE_KIND = "rune"
WEAPON_MOD_STANDALONE_KIND = "weapon_mod"


def _is_common_crafting_material_model(model_id: object) -> bool:
    return max(0, safe_int(model_id, 0)) in COMMON_CRAFTING_MATERIAL_MODEL_IDS


def _is_rare_crafting_material_model(model_id: object) -> bool:
    return max(0, safe_int(model_id, 0)) in RARE_CRAFTING_MATERIAL_MODEL_IDS


is_common_crafting_material_model = _is_common_crafting_material_model
is_rare_crafting_material_model = _is_rare_crafting_material_model


def material_batch_size(model_id: object) -> int:
    return MATERIAL_BATCH_SIZE if _is_common_crafting_material_model(model_id) else 1


def _is_rune_identifier_collection(
    value: object,
) -> TypeGuard[list[object] | tuple[object, ...] | set[object] | frozenset[object]]:
    return isinstance(value, (list, tuple, set, frozenset))


def normalize_rune_identifier_tuple(identifiers: object) -> tuple[str, ...]:
    if not _is_rune_identifier_collection(identifiers):
        return ()
    values: Iterable[object] = identifiers
    return tuple(
        sorted({safe_identifier for identifier in values if (safe_identifier := normalize_rune_identifier(identifier))})
    )


def equippable_destination(item: "InventoryItemInfo", rule: SellRule) -> str:
    if rule.kind == SELL_KIND_WEAPONS:
        if item.standalone_kind == WEAPON_MOD_STANDALONE_KIND:
            return MERCHANT_TYPE_MERCHANT
        if item.is_weapon_like:
            return MERCHANT_TYPE_MERCHANT
    elif rule.kind == SELL_KIND_ARMOR:
        if rule.include_standalone_runes and item.standalone_kind == RUNE_STANDALONE_KIND:
            return MERCHANT_TYPE_RUNE_TRADER
        if item.is_armor_piece:
            return MERCHANT_TYPE_MERCHANT
    return ""


def explicit_destination(item: "InventoryItemInfo") -> str:
    if item.is_material:
        return material_destination(item.model_id)
    if item.standalone_kind == RUNE_STANDALONE_KIND:
        return MERCHANT_TYPE_RUNE_TRADER
    return MERCHANT_TYPE_MERCHANT


def material_destination(model_id: int) -> str:
    if _is_rare_crafting_material_model(model_id):
        return MERCHANT_TYPE_RARE_MATERIALS
    return MERCHANT_TYPE_MATERIALS


def _sum_item_quantities(items: list["InventoryItemInfo"]) -> int:
    return sum(max(1, int(item.quantity)) for item in items if int(item.item_id) > 0)


def _storage_keep_available(
    rule: SellRule,
    model_id: int,
    regular_storage_items: list["InventoryItemInfo"],
    material_storage_items: list["InventoryItemInfo"],
) -> int:
    if not bool(getattr(rule, "sell_from_xunlai", False)):
        return 0
    safe_model_id = max(0, int(model_id))
    if safe_model_id <= 0:
        return 0
    source_items = list(regular_storage_items)
    if bool(getattr(rule, "include_material_storage", False)) and sell_rule_can_include_material_storage(rule):
        source_items = [*material_storage_items, *source_items]
    return _sum_item_quantities([item for item in source_items if int(item.model_id) == safe_model_id])


def _storage_keep_reservations(
    source_items: list[tuple["InventoryItemInfo", str]],
    keep_count: int,
) -> tuple[dict[int, int], int]:
    remaining_keep = max(0, int(keep_count))
    if remaining_keep <= 0:
        return {}, 0

    reservations: dict[int, int] = {}
    reserved_total = 0
    reserve_order = sorted(
        source_items,
        key=lambda pair: (
            0 if str(pair[1]) == "Material Storage" else 1,
            int(pair[0].item_id),
        ),
    )
    for item, _source_label in reserve_order:
        if remaining_keep <= 0:
            break
        item_quantity = max(1, int(item.quantity))
        reserve_quantity = min(item_quantity, remaining_keep)
        if reserve_quantity <= 0:
            continue
        reservations[int(item.item_id)] = reserve_quantity
        reserved_total += reserve_quantity
        remaining_keep -= reserve_quantity
    return reservations, reserved_total


def _clone_xunlai_sell_rule(
    rule: SellRule,
    *,
    model_keep_overrides: dict[tuple[str, int], int],
    rune_keep_overrides: dict[tuple[str, str], int],
    include_equippable: bool,
) -> SellRule | None:
    safe_rule_id = normalize_rule_id(getattr(rule, "rule_id", ""))
    cloned_rule = replace(rule)
    cloned_rule.sell_from_xunlai = False
    cloned_rule.include_material_storage = False

    if rule.kind in (SELL_KIND_COMMON_MATERIALS, SELL_KIND_EXPLICIT_MODELS):
        next_targets: list[WhitelistTarget] = []
        for target in normalize_whitelist_targets(getattr(rule, "whitelist_targets", [])):
            key = (safe_rule_id, int(target.model_id))
            if key not in model_keep_overrides:
                continue
            next_targets.append(
                WhitelistTarget(
                    model_id=int(target.model_id),
                    keep_count=max(0, int(model_keep_overrides[key])),
                    deposit_to_storage=False,
                )
            )
        if not next_targets:
            return None
        cloned_rule.whitelist_targets = next_targets
        cloned_rule.model_ids = get_whitelist_target_model_ids(next_targets)
        cloned_rule.keep_count = 0
        return cloned_rule

    if rule.kind == SELL_KIND_RUNE_TRADER_TARGET:
        next_rune_targets: list[RuneSellTarget] = []
        for target in normalize_rune_sell_targets(getattr(rule, "rune_sell_targets", [])):
            key = (safe_rule_id, normalize_rune_identifier(target.identifier))
            if key not in rune_keep_overrides:
                continue
            next_rune_targets.append(
                RuneSellTarget(
                    identifier=key[1],
                    keep_count=max(0, int(rune_keep_overrides[key])),
                )
            )
        if not next_rune_targets:
            return None
        cloned_rule.rune_sell_targets = next_rune_targets
        return cloned_rule

    if rule.kind in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR) and include_equippable:
        return cloned_rule

    return None


def xunlai_model_target_has_sell_service(
    rule: SellRule,
    model_id: int,
    source_items: list[tuple["InventoryItemInfo", str]],
    coords: dict[str, tuple[float, float] | None],
    *,
    withdraw_quantity: int,
    keep_count: int,
) -> bool:
    if rule.kind == SELL_KIND_COMMON_MATERIALS:
        destination = material_destination(model_id)
        if coords.get(destination) is not None:
            return True
        return bool(
            destination == MERCHANT_TYPE_MATERIALS
            and max(0, int(keep_count)) <= 0
            and max(0, int(withdraw_quantity)) < max(1, int(material_batch_size(model_id)))
            and coords.get(MERCHANT_TYPE_MERCHANT) is not None
        )

    for item, _source_label in source_items:
        destination = explicit_destination(item)
        if coords.get(destination) is not None:
            return True
        if (
            destination == MERCHANT_TYPE_MATERIALS
            and max(0, int(keep_count)) <= 0
            and max(0, int(withdraw_quantity)) < max(1, int(material_batch_size(item.model_id)))
            and coords.get(MERCHANT_TYPE_MERCHANT) is not None
        ):
            return True
    return False


class _MaterialSaleRow(TypedDict):
    item: "InventoryItemInfo"
    quantity: int
    reserved: int
    batch_size: int
    merchant_type: str


class SalePlanner:
    """Allocate sale intent from borrowed evidence; retain no per-call allocation state."""

    def __init__(
        self,
        *,
        inventory_item_type: type["InventoryItemInfo"],
        choose_keep_subset: Callable[[list["InventoryItemInfo"], int], set[int]],
        sell_kind_labels: Mapping[str, str],
        merchant_type_labels: Mapping[str, str],
        model_label: Callable[[int], str],
        rune_label: Callable[[str], str],
        item_label: Callable[["InventoryItemInfo"], str],
        rule_reference: Callable[[int, SellRule], str],
        withdrawal_label: Callable[["InventoryItemInfo"], str],
        diagnostic: Callable[[str], None],
    ) -> None:
        self._inventory_item_type = inventory_item_type
        self._choose_keep_subset = choose_keep_subset
        self._sell_kind_labels = sell_kind_labels
        self._merchant_type_labels = merchant_type_labels
        self._model_label = model_label
        self._rune_label = rune_label
        self._item_label = item_label
        self._rule_reference = rule_reference
        self._withdrawal_label = withdrawal_label
        self._diagnostic = diagnostic

    def allocate_inventory_sales(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        enabled_sell_rules: list[tuple[int, SellRule]],
        sell_action_rules: list[tuple[int, SellRule]],
        claimed_item_ids: set[int],
        coords: dict[str, tuple[float, float] | None],
        storage_items: list["InventoryItemInfo"],
        xunlai_sell_material_storage_items: list["InventoryItemInfo"],
        *,
        policy: "ProtectionPolicy",
        consumable_crafter_only: bool,
        supported_map: bool,
        storage_context_ready: bool,
        supported_reason: str,
    ) -> None:
        material_quantities = {item.item_id: item.quantity for item in items if item.is_material}

        if not consumable_crafter_only and (supported_map or storage_context_ready):
            for item in items:
                if item.item_id in claimed_item_ids:
                    continue
                hard_protection = policy.get_hard_protection_hit(item, enabled_sell_rules)
                if hard_protection is None:
                    continue
                destination, detail = hard_protection
                claimed_item_ids.add(item.item_id)
                plan.entries.append(
                    ExecutionPlanEntry(
                        "sell",
                        destination,
                        item.name,
                        item.quantity,
                        PLAN_STATE_SKIPPED,
                        detail,
                        model_id=item.model_id,
                    )
                )

        reserved_rune_sell_identifiers = {
            target.identifier
            for _exact_rule_index, exact_rule in sell_action_rules
            if exact_rule.kind == SELL_KIND_RUNE_TRADER_TARGET
            for target in normalize_rune_sell_targets(getattr(exact_rule, "rune_sell_targets", []))
            if target.identifier
        }
        for rule_index, sell_rule in sell_action_rules:
            merchant_coords = coords.get(sell_rule.merchant_type)
            if not supported_map and not storage_context_ready:
                plan.entries.append(
                    ExecutionPlanEntry(
                        action_type="sell",
                        merchant_type=sell_rule.merchant_type,
                        label=self._sell_kind_labels[sell_rule.kind],
                        quantity=0,
                        state="skipped",
                        reason=supported_reason,
                    )
                )
                continue

            rule_reference = self._rule_reference(rule_index, sell_rule)
            if sell_rule.kind in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
                self.plan_equippable_sales(
                    plan=plan,
                    items=items,
                    rule=sell_rule,
                    rule_index=rule_index,
                    claimed_item_ids=claimed_item_ids,
                    coords=coords,
                    reserved_rune_sell_identifiers=reserved_rune_sell_identifiers,
                    policy=policy,
                )
                continue

            if sell_rule.kind == SELL_KIND_RUNE_TRADER_TARGET:
                self.plan_rune_target_sales(
                    plan=plan,
                    items=items,
                    rule=sell_rule,
                    rule_index=rule_index,
                    claimed_item_ids=claimed_item_ids,
                    coords=coords,
                )
                continue

            if sell_rule.kind == SELL_KIND_COMMON_MATERIALS:
                material_targets = normalize_whitelist_targets(getattr(sell_rule, "whitelist_targets", []))
                if not material_targets:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "sell",
                            sell_rule.merchant_type,
                            self._sell_kind_labels[sell_rule.kind],
                            0,
                            "skipped",
                            "No material model whitelist configured.",
                        )
                    )
                    continue

                for material_target in material_targets:
                    material_model_id = max(0, int(material_target.model_id))
                    target_keep_count = max(0, int(material_target.keep_count))
                    if target_keep_count > 0:
                        storage_keep_available = _storage_keep_available(
                            sell_rule,
                            material_model_id,
                            storage_items,
                            xunlai_sell_material_storage_items,
                        )
                        target_keep_count = max(0, target_keep_count - storage_keep_available)
                    target_label = self._model_label(material_model_id)
                    matching_items = [
                        item
                        for item in items
                        if item.item_id not in claimed_item_ids
                        and item.is_material
                        and item.model_id == material_model_id
                        and int(material_quantities.get(item.item_id, 0)) > 0
                    ]
                    if not matching_items:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "sell",
                                sell_rule.merchant_type,
                                target_label,
                                0,
                                "skipped",
                                "No matching material items found.",
                            )
                        )
                        continue

                    working_quantities = {
                        item.item_id: max(0, int(material_quantities.get(item.item_id, item.quantity)))
                        for item in matching_items
                    }
                    material_sales = self.plan_material_sales(matching_items, working_quantities, target_keep_count)
                    for item in matching_items:
                        claimed_item_ids.add(item.item_id)

                    sold_quantities_by_item_id = {
                        sale.item_id: max(0, int(sale.quantity_to_sell)) for sale in material_sales
                    }
                    for sale in material_sales:
                        sale_reason = (
                            f"{sale.batches_to_sell} full trader batch(es) of {sale.batch_size}."
                            if int(sale.batch_size) > 1
                            else f"{sale.quantity_to_sell} individual trade(s)."
                        )
                        if coords.get(sale.merchant_type) is None:
                            plan.entries.append(
                                ExecutionPlanEntry(
                                    "sell",
                                    sale.merchant_type,
                                    sale.label,
                                    sale.quantity_to_sell,
                                    PLAN_STATE_SKIPPED,
                                    (
                                        f"Blocked by {rule_reference}: "
                                        f"{self._merchant_type_labels[sale.merchant_type]} could not be found in the current map."
                                    ),
                                    model_id=sale.model_id,
                                )
                            )
                        else:
                            plan.material_sales.append(sale)
                            plan.entries.append(
                                ExecutionPlanEntry(
                                    "sell",
                                    sale.merchant_type,
                                    sale.label,
                                    sale.quantity_to_sell,
                                    PLAN_STATE_WILL_EXECUTE,
                                    sale_reason,
                                    model_id=sale.model_id,
                                )
                            )
                    fallback_merchant_coords = coords.get(MERCHANT_TYPE_MERCHANT)
                    for item in matching_items:
                        remaining_quantity = max(0, int(working_quantities.get(item.item_id, 0)))
                        if remaining_quantity <= 0:
                            continue
                        sold_quantity = sold_quantities_by_item_id.get(item.item_id, 0)
                        item_merchant_type = material_destination(item.model_id)
                        batch_size = max(1, int(material_batch_size(item.model_id)))
                        if (
                            target_keep_count <= 0
                            and item_merchant_type == MERCHANT_TYPE_MATERIALS
                            and remaining_quantity < batch_size
                        ):
                            merchant_reason = (
                                "Merchant fallback after selling full trader batches; leftover common-material quantity is below the trader batch size."
                                if sold_quantity > 0
                                else "Merchant fallback because the common-material quantity is below the trader batch size."
                            )
                            if fallback_merchant_coords is None:
                                plan.entries.append(
                                    ExecutionPlanEntry(
                                        "sell",
                                        MERCHANT_TYPE_MERCHANT,
                                        item.name,
                                        remaining_quantity,
                                        PLAN_STATE_SKIPPED,
                                        (
                                            f"Blocked by {rule_reference}: "
                                            f"{self._merchant_type_labels[MERCHANT_TYPE_MERCHANT]} could not be found in the current map."
                                        ),
                                        model_id=item.model_id,
                                    )
                                )
                            else:
                                plan.merchant_sell_item_ids.append(item.item_id)
                                plan.entries.append(
                                    ExecutionPlanEntry(
                                        "sell",
                                        MERCHANT_TYPE_MERCHANT,
                                        item.name,
                                        remaining_quantity,
                                        PLAN_STATE_WILL_EXECUTE,
                                        merchant_reason,
                                        model_id=item.model_id,
                                    )
                                )
                            continue
                        keep_reason = (
                            (
                                f"Kept by {rule_reference}: {remaining_quantity} unit(s) remain after selling full trader batches."
                                if batch_size > 1
                                else f"Kept by {rule_reference}: {remaining_quantity} unit(s) remain after selling individual trades."
                            )
                            if sold_quantity > 0
                            else (
                                f"Kept by {rule_reference}: no tradable full trader batches remained after keep count."
                                if batch_size > 1
                                else f"Kept by {rule_reference}: reserved to satisfy keep count {target_keep_count}."
                            )
                        )
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "sell",
                                item_merchant_type,
                                item.name,
                                remaining_quantity,
                                PLAN_STATE_SKIPPED,
                                keep_reason,
                                model_id=item.model_id,
                            )
                        )
                continue

            if sell_rule.kind == SELL_KIND_EXPLICIT_MODELS:
                explicit_targets = normalize_whitelist_targets(getattr(sell_rule, "whitelist_targets", []))
                if not explicit_targets:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "sell",
                            sell_rule.merchant_type,
                            self._sell_kind_labels[sell_rule.kind],
                            0,
                            "skipped",
                            "No explicit model whitelist configured.",
                        )
                    )
                    continue

                for explicit_target in explicit_targets:
                    target_model_id = max(0, int(explicit_target.model_id))
                    target_keep_count = max(0, int(explicit_target.keep_count))
                    if target_keep_count > 0:
                        storage_keep_available = _storage_keep_available(
                            sell_rule,
                            target_model_id,
                            storage_items,
                            xunlai_sell_material_storage_items,
                        )
                        target_keep_count = max(0, target_keep_count - storage_keep_available)
                    target_label = self._model_label(target_model_id)
                    matching_items = [
                        item
                        for item in items
                        if item.item_id not in claimed_item_ids and item.model_id == target_model_id
                    ]
                    if not matching_items:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "sell",
                                sell_rule.merchant_type,
                                target_label,
                                0,
                                "skipped",
                                "No matching inventory items found.",
                            )
                        )
                        continue

                    keep_ids = self._choose_keep_subset(matching_items, target_keep_count)
                    for item in matching_items:
                        claimed_item_ids.add(item.item_id)
                        if item.item_id not in keep_ids:
                            continue
                        item_destination = explicit_destination(item)
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "sell",
                                item_destination,
                                item.name,
                                item.quantity,
                                PLAN_STATE_SKIPPED,
                                f"Kept by {rule_reference}: reserved to satisfy keep count {target_keep_count}.",
                                model_id=item.model_id,
                            )
                        )

                    sell_items = [item for item in matching_items if item.item_id not in keep_ids]
                    if not sell_items:
                        continue

                    sell_items_by_destination: dict[str, list["InventoryItemInfo"]] = {}
                    for item in sell_items:
                        item_destination = explicit_destination(item)
                        sell_items_by_destination.setdefault(item_destination, []).append(item)

                    for destination, destination_items in sell_items_by_destination.items():
                        if destination == MERCHANT_TYPE_MERCHANT:
                            merchant_coords = coords.get(MERCHANT_TYPE_MERCHANT)
                            if merchant_coords is None:
                                for item in destination_items:
                                    plan.entries.append(
                                        ExecutionPlanEntry(
                                            "sell",
                                            MERCHANT_TYPE_MERCHANT,
                                            item.name,
                                            item.quantity,
                                            PLAN_STATE_SKIPPED,
                                            (
                                                f"Blocked by {rule_reference}: "
                                                f"{self._merchant_type_labels[MERCHANT_TYPE_MERCHANT]} could not be "
                                                "found in the current map."
                                            ),
                                            model_id=item.model_id,
                                        )
                                    )
                                continue

                            for item in destination_items:
                                plan.merchant_sell_item_ids.append(item.item_id)
                                plan.entries.append(
                                    ExecutionPlanEntry(
                                        "sell",
                                        MERCHANT_TYPE_MERCHANT,
                                        item.name,
                                        item.quantity,
                                        PLAN_STATE_WILL_EXECUTE,
                                        f"Matched {rule_reference}.",
                                        model_id=item.model_id,
                                    )
                                )
                            continue

                        if destination == MERCHANT_TYPE_RUNE_TRADER:
                            rune_trader_coords = coords.get(MERCHANT_TYPE_RUNE_TRADER)
                            if rune_trader_coords is None:
                                for item in destination_items:
                                    plan.entries.append(
                                        ExecutionPlanEntry(
                                            "sell",
                                            MERCHANT_TYPE_RUNE_TRADER,
                                            item.name,
                                            item.quantity,
                                            PLAN_STATE_SKIPPED,
                                            (
                                                f"Blocked by {rule_reference}: "
                                                f"{self._merchant_type_labels[MERCHANT_TYPE_RUNE_TRADER]} could not be found in the current map."
                                            ),
                                            model_id=item.model_id,
                                        )
                                    )
                                continue

                            for item in destination_items:
                                plan.rune_trader_sales.append(
                                    PlannedTraderSale(
                                        item_id=item.item_id,
                                        model_id=item.model_id,
                                        label=self._item_label(item),
                                        expected_rune_identifiers=normalize_rune_identifier_tuple(
                                            item.rune_identifiers
                                        ),
                                    )
                                )
                                plan.entries.append(
                                    ExecutionPlanEntry(
                                        "sell",
                                        MERCHANT_TYPE_RUNE_TRADER,
                                        item.name,
                                        item.quantity,
                                        PLAN_STATE_WILL_EXECUTE,
                                        f"Matched {rule_reference}: standalone rune or insignia.",
                                        model_id=item.model_id,
                                    )
                                )
                            continue

                        material_coords = coords.get(destination)
                        working_quantities = {item.item_id: max(0, int(item.quantity)) for item in destination_items}
                        material_sales: list[PlannedMaterialSale] = []
                        if material_coords is not None:
                            material_sales = self.plan_material_sales(destination_items, working_quantities, 0)

                        sold_quantities_by_item_id = {
                            sale.item_id: max(0, int(sale.quantity_to_sell)) for sale in material_sales
                        }
                        for sale in material_sales:
                            plan.material_sales.append(sale)
                            sale_reason = (
                                f"{sale.batches_to_sell} full trader batch(es) of {sale.batch_size}."
                                if int(sale.batch_size) > 1
                                else f"{sale.quantity_to_sell} individual trade(s)."
                            )
                            plan.entries.append(
                                ExecutionPlanEntry(
                                    "sell",
                                    sale.merchant_type,
                                    sale.label,
                                    sale.quantity_to_sell,
                                    PLAN_STATE_WILL_EXECUTE,
                                    sale_reason,
                                    model_id=sale.model_id,
                                )
                            )

                        for item in destination_items:
                            remaining_quantity = max(0, int(working_quantities.get(item.item_id, 0)))
                            if remaining_quantity <= 0:
                                continue

                            batch_size = max(1, int(material_batch_size(item.model_id)))
                            sold_quantity = sold_quantities_by_item_id.get(item.item_id, 0)
                            if destination == MERCHANT_TYPE_MATERIALS and remaining_quantity < batch_size:
                                merchant_coords = coords.get(MERCHANT_TYPE_MERCHANT)
                                merchant_reason = (
                                    "Merchant fallback after selling full trader batches; leftover common-material quantity is below the trader batch size."
                                    if sold_quantity > 0
                                    else "Merchant fallback because the common-material quantity is below the trader batch size."
                                )
                                if merchant_coords is None:
                                    plan.entries.append(
                                        ExecutionPlanEntry(
                                            "sell",
                                            MERCHANT_TYPE_MERCHANT,
                                            item.name,
                                            remaining_quantity,
                                            PLAN_STATE_SKIPPED,
                                            (
                                                f"Blocked by {rule_reference}: "
                                                f"{self._merchant_type_labels[MERCHANT_TYPE_MERCHANT]} could not be "
                                                "found in the current map."
                                            ),
                                            model_id=item.model_id,
                                        )
                                    )
                                else:
                                    plan.merchant_sell_item_ids.append(item.item_id)
                                    plan.entries.append(
                                        ExecutionPlanEntry(
                                            "sell",
                                            MERCHANT_TYPE_MERCHANT,
                                            item.name,
                                            remaining_quantity,
                                            PLAN_STATE_WILL_EXECUTE,
                                            merchant_reason,
                                            model_id=item.model_id,
                                        )
                                    )
                                continue

                            if material_coords is None:
                                plan.entries.append(
                                    ExecutionPlanEntry(
                                        "sell",
                                        destination,
                                        item.name,
                                        remaining_quantity,
                                        PLAN_STATE_SKIPPED,
                                        (
                                            f"Blocked by {rule_reference}: "
                                            f"{self._merchant_type_labels[destination]} could not be found in the current map."
                                        ),
                                        model_id=item.model_id,
                                    )
                                )
                                continue

                            keep_reason = (
                                f"Kept by {rule_reference}: {remaining_quantity} unit(s) remain after selling full trader batches."
                                if batch_size > 1
                                else f"Kept by {rule_reference}: {remaining_quantity} unit(s) remain after individual trades."
                            )
                            plan.entries.append(
                                ExecutionPlanEntry(
                                    "sell",
                                    destination,
                                    item.name,
                                    remaining_quantity,
                                    PLAN_STATE_SKIPPED,
                                    keep_reason,
                                    model_id=item.model_id,
                                )
                            )
                continue

    def plan_equippable_sales(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        rule: SellRule,
        rule_index: int,
        claimed_item_ids: set[int],
        coords: dict[str, tuple[float, float] | None],
        reserved_rune_sell_identifiers: set[str] | None = None,
        *,
        policy: "ProtectionPolicy",
    ) -> None:
        """Plan equipment sales while reserving protected, customized, and rune-trader items."""

        candidate_label = self._sell_kind_labels[rule.kind]
        rule_reference = self._rule_reference(rule_index, rule)
        reserved_rune_sell_identifiers = reserved_rune_sell_identifiers or set()
        had_category_candidate = False
        had_rarity_candidate = False
        planned_sale_count = 0
        category_candidates = 0
        rarity_matches = 0
        merchant_sales = 0
        rune_trader_sales = 0
        blocked_matches = 0

        for item in items:
            if item.item_id in claimed_item_ids:
                continue

            destination = equippable_destination(item, rule)
            if not destination:
                continue
            if (
                rule.kind == SELL_KIND_ARMOR
                and item.standalone_kind == RUNE_STANDALONE_KIND
                and reserved_rune_sell_identifiers
                and any(identifier in reserved_rune_sell_identifiers for identifier in item.rune_identifiers)
            ):
                continue

            had_category_candidate = True
            category_candidates += 1
            if not policy.rule_matches_selected_rarity(item, rule):
                continue

            had_rarity_candidate = True
            rarity_matches += 1
            if coords.get(destination) is None:
                claimed_item_ids.add(item.item_id)
                blocked_matches += 1
                plan.entries.append(
                    ExecutionPlanEntry(
                        "sell",
                        destination,
                        item.name,
                        item.quantity,
                        "skipped",
                        (
                            f"Blocked by {rule_reference}: "
                            f"{self._merchant_type_labels[destination]} could not be found in the current map."
                        ),
                        model_id=item.model_id,
                    )
                )
                continue

            claimed_item_ids.add(item.item_id)
            if destination == MERCHANT_TYPE_RUNE_TRADER:
                plan.rune_trader_sales.append(
                    PlannedTraderSale(
                        item_id=item.item_id,
                        model_id=item.model_id,
                        label=self._item_label(item),
                        expected_rune_identifiers=normalize_rune_identifier_tuple(item.rune_identifiers),
                    )
                )
            else:
                plan.merchant_sell_item_ids.append(item.item_id)

            reason_detail = (
                " Standalone weapon upgrade component."
                if rule.kind == SELL_KIND_WEAPONS and item.standalone_kind == WEAPON_MOD_STANDALONE_KIND
                else (
                    " Standalone rune / insignia item."
                    if rule.kind == SELL_KIND_ARMOR and item.standalone_kind == RUNE_STANDALONE_KIND
                    else ""
                )
            )
            reason = f"Matched {rule_reference}.{reason_detail}"
            plan.entries.append(
                ExecutionPlanEntry(
                    "sell",
                    destination,
                    item.name,
                    item.quantity,
                    "will execute",
                    reason,
                    model_id=item.model_id,
                )
            )
            planned_sale_count += 1
            if destination == MERCHANT_TYPE_RUNE_TRADER:
                rune_trader_sales += 1
            else:
                merchant_sales += 1

        if planned_sale_count > 0 or blocked_matches > 0:
            self._diagnostic(
                f"{candidate_label}: category_candidates={category_candidates} rarity_matches={rarity_matches} "
                f"merchant_sales={merchant_sales} rune_trader_sales={rune_trader_sales} "
                f"blocked_matches={blocked_matches}"
            )
            return
        if not had_category_candidate:
            plan.entries.append(
                ExecutionPlanEntry(
                    "sell",
                    MERCHANT_TYPE_MERCHANT,
                    candidate_label,
                    0,
                    "skipped",
                    (
                        f"No matching inventory items are available to {rule_reference} "
                        "after earlier actions and protections."
                    ),
                    status_hint=PREVIEW_STATUS_NO_MATCH,
                )
            )
        elif not had_rarity_candidate:
            plan.entries.append(
                ExecutionPlanEntry(
                    "sell",
                    MERCHANT_TYPE_MERCHANT,
                    candidate_label,
                    0,
                    "skipped",
                    f"No matching items are available to {rule_reference} for its selected rarities.",
                    status_hint=PREVIEW_STATUS_NO_MATCH,
                )
            )
        self._diagnostic(
            f"{candidate_label}: category_candidates={category_candidates} rarity_matches={rarity_matches} "
            f"merchant_sales={merchant_sales} rune_trader_sales={rune_trader_sales} "
            f"blocked_matches={blocked_matches}"
        )

    def plan_rune_target_sales(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        rule: SellRule,
        rule_index: int,
        claimed_item_ids: set[int],
        coords: dict[str, tuple[float, float] | None],
    ) -> None:
        rule_reference = self._rule_reference(rule_index, rule)
        rune_targets = normalize_rune_sell_targets(getattr(rule, "rune_sell_targets", []))
        if not rune_targets:
            plan.entries.append(
                ExecutionPlanEntry(
                    "sell",
                    MERCHANT_TYPE_RUNE_TRADER,
                    self._sell_kind_labels[SELL_KIND_RUNE_TRADER_TARGET],
                    0,
                    PLAN_STATE_SKIPPED,
                    f"{rule_reference} has no rune or insignia targets selected.",
                )
            )
            return

        rune_trader_coords = coords.get(MERCHANT_TYPE_RUNE_TRADER)
        planned_sale_count = 0
        blocked_matches = 0
        kept_matches = 0

        for rune_target in rune_targets:
            target_identifier = normalize_rune_identifier(rune_target.identifier)
            if not target_identifier:
                continue

            target_label = self._rune_label(target_identifier)
            matching_items = [
                item
                for item in items
                if item.item_id not in claimed_item_ids
                and item.standalone_kind == RUNE_STANDALONE_KIND
                and target_identifier in item.rune_identifiers
            ]
            if not matching_items:
                plan.entries.append(
                    ExecutionPlanEntry(
                        "sell",
                        MERCHANT_TYPE_RUNE_TRADER,
                        target_label,
                        0,
                        PLAN_STATE_SKIPPED,
                        f"No matching standalone rune or insignia is available to {rule_reference}.",
                        status_hint=PREVIEW_STATUS_NO_MATCH,
                    )
                )
                continue

            keep_count = max(0, int(rune_target.keep_count))
            keep_ids = self._choose_keep_subset(matching_items, keep_count)
            for item in matching_items:
                claimed_item_ids.add(item.item_id)
                if item.item_id not in keep_ids:
                    continue
                kept_matches += 1
                plan.entries.append(
                    ExecutionPlanEntry(
                        "sell",
                        MERCHANT_TYPE_RUNE_TRADER,
                        item.name,
                        item.quantity,
                        PLAN_STATE_SKIPPED,
                        f"Kept by {rule_reference}: reserved to satisfy keep count {keep_count}.",
                        model_id=item.model_id,
                    )
                )

            sell_items = [item for item in matching_items if item.item_id not in keep_ids]
            if not sell_items:
                continue

            if rune_trader_coords is None:
                blocked_matches += len(sell_items)
                for item in sell_items:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "sell",
                            MERCHANT_TYPE_RUNE_TRADER,
                            item.name,
                            item.quantity,
                            PLAN_STATE_SKIPPED,
                            (
                                f"Blocked by {rule_reference}: "
                                f"{self._merchant_type_labels[MERCHANT_TYPE_RUNE_TRADER]} could not be found in the current map."
                            ),
                            model_id=item.model_id,
                        )
                    )
                continue

            for item in sell_items:
                plan.rune_trader_sales.append(
                    PlannedTraderSale(
                        item_id=item.item_id,
                        model_id=item.model_id,
                        label=target_label,
                        expected_rune_identifiers=normalize_rune_identifier_tuple(item.rune_identifiers),
                    )
                )
                plan.entries.append(
                    ExecutionPlanEntry(
                        "sell",
                        MERCHANT_TYPE_RUNE_TRADER,
                        item.name,
                        item.quantity,
                        PLAN_STATE_WILL_EXECUTE,
                        f"Matched an exact rune or insignia target in {rule_reference}.",
                        model_id=item.model_id,
                    )
                )
                planned_sale_count += 1

        self._diagnostic(
            f"{self._sell_kind_labels[SELL_KIND_RUNE_TRADER_TARGET]}: "
            f"targets={len(rune_targets)} planned_sales={planned_sale_count} "
            f"kept_matches={kept_matches} blocked_matches={blocked_matches}"
        )

    def plan_material_sales(
        self,
        matching_items: list["InventoryItemInfo"],
        working_quantities: dict[int, int],
        keep_count: int,
    ) -> list[PlannedMaterialSale]:
        keep_count = max(0, int(keep_count))
        if not matching_items:
            return []

        rows: list[_MaterialSaleRow] = []
        reserved_total = 0
        for item in matching_items:
            quantity = max(0, int(working_quantities.get(item.item_id, 0)))
            if quantity <= 0:
                continue
            batch_size = max(1, int(material_batch_size(item.model_id)))
            reserved = quantity % batch_size
            reserved_total += reserved
            rows.append(
                {
                    "item": item,
                    "quantity": quantity,
                    "reserved": reserved,
                    "batch_size": batch_size,
                    "merchant_type": material_destination(item.model_id),
                }
            )

        extra_keep_needed = max(0, keep_count - reserved_total)
        rows.sort(key=lambda entry: int(entry["quantity"]))
        for row in rows:
            if extra_keep_needed <= 0:
                break
            quantity = int(row["quantity"])
            reserved = int(row["reserved"])
            batch_size = max(1, int(row["batch_size"]))
            while extra_keep_needed > 0 and (reserved + batch_size) <= quantity:
                reserved += batch_size
                extra_keep_needed -= batch_size
            row["reserved"] = reserved

        planned_sales: list[PlannedMaterialSale] = []
        for row in rows:
            item = row["item"]
            if not isinstance(item, self._inventory_item_type):
                continue
            quantity = int(row["quantity"])
            reserved = int(row["reserved"])
            batch_size = max(1, int(row["batch_size"]))
            merchant_type = str(row["merchant_type"])
            quantity_to_sell = max(0, quantity - reserved)
            batches_to_sell = quantity_to_sell // batch_size
            if batches_to_sell <= 0:
                continue
            sell_quantity = batches_to_sell * batch_size
            working_quantities[item.item_id] = max(0, quantity - sell_quantity)
            planned_sales.append(
                PlannedMaterialSale(
                    merchant_type=merchant_type,
                    item_id=item.item_id,
                    model_id=item.model_id,
                    label=self._item_label(item),
                    batches_to_sell=batches_to_sell,
                    quantity_to_sell=sell_quantity,
                    batch_size=batch_size,
                )
            )
        return planned_sales

    def _append_protected_withdraw_entries(
        self,
        entries: list[ExecutionPlanEntry] | None,
        source_items: list[tuple["InventoryItemInfo", str, str]],
        *,
        rule_reference: str,
    ) -> None:
        if entries is None:
            return
        for item, source_label, protection_reason in source_items:
            entries.append(
                ExecutionPlanEntry(
                    "withdraw",
                    MERCHANT_TYPE_STORAGE,
                    self._withdrawal_label(item),
                    max(1, int(item.quantity)),
                    PLAN_STATE_SKIPPED,
                    (
                        f"Will remain in {source_label} because {rule_reference} protects it from sale: "
                        f"{protection_reason}"
                    ),
                    model_id=int(item.model_id),
                    status_hint=PREVIEW_STATUS_PROTECTED,
                )
            )

    def _append_withdrawals(
        self,
        transfers: list[PlannedStorageTransfer],
        source_items: list[tuple["InventoryItemInfo", str]],
        *,
        quantity: int,
        rule_reference: str,
        key: str,
        reserved_quantities: dict[int, int] | None = None,
    ) -> None:
        remaining = max(0, int(quantity))
        if remaining <= 0:
            return

        reserved_quantities = reserved_quantities or {}
        for item, source_label in source_items:
            if remaining <= 0:
                break
            source_quantity = max(1, int(item.quantity))
            reserved_quantity = max(0, int(reserved_quantities.get(int(item.item_id), 0)))
            available_quantity = max(0, source_quantity - reserved_quantity)
            move_quantity = min(remaining, available_quantity)
            if move_quantity <= 0:
                continue
            transfers.append(
                PlannedStorageTransfer(
                    direction=STORAGE_TRANSFER_WITHDRAW,
                    key=key,
                    label=self._withdrawal_label(item),
                    item_id=int(item.item_id),
                    quantity=move_quantity,
                    model_id=int(item.model_id),
                    reason=f"{rule_reference}: Sell from Xunlai too ({source_label}).",
                )
            )
            remaining -= move_quantity

    def plan_xunlai_withdrawals(
        self,
        enabled_xunlai_rules: list[tuple[int, SellRule]],
        current_items: list["InventoryItemInfo"],
        regular_storage_items: list["InventoryItemInfo"],
        material_storage_items: list["InventoryItemInfo"],
        coords: dict[str, tuple[float, float] | None],
        *,
        all_enabled_sell_rules: list[tuple[int, SellRule]],
        policy: "ProtectionPolicy",
        protected_preview_entries: list[ExecutionPlanEntry] | None = None,
    ) -> tuple[list[PlannedStorageTransfer], list[SellRule]]:
        """Plan Xunlai withdrawals while reserving keep counts across overlapping sale rules.

        Equipment protections and unsafe storage types produce visible protected entries rather
        than withdrawal actions.
        """

        transfers: list[PlannedStorageTransfer] = []
        model_keep_overrides: dict[tuple[str, int], int] = {}
        rune_keep_overrides: dict[tuple[str, str], int] = {}
        equippable_rule_ids: set[str] = set()
        claimed_storage_item_ids: set[int] = set()

        for rule_index, rule in enabled_xunlai_rules:
            safe_rule_id = normalize_rule_id(getattr(rule, "rule_id", ""))
            if not safe_rule_id:
                continue
            rule_reference = self._rule_reference(rule_index, rule)

            regular_sources = [
                (item, "regular Xunlai item panes")
                for item in regular_storage_items
                if int(item.item_id) not in claimed_storage_item_ids
            ]
            material_sources = [
                (item, "Material Storage")
                for item in material_storage_items
                if bool(getattr(rule, "include_material_storage", False))
                and sell_rule_can_include_material_storage(rule)
                and int(item.item_id) not in claimed_storage_item_ids
                and int(item.model_id) in ALL_CRAFTING_MATERIAL_MODEL_IDS
            ]

            if rule.kind in (SELL_KIND_COMMON_MATERIALS, SELL_KIND_EXPLICIT_MODELS):
                for target in normalize_whitelist_targets(getattr(rule, "whitelist_targets", [])):
                    target_model_id = max(0, int(target.model_id))
                    if target_model_id <= 0:
                        continue
                    if (
                        rule.kind == SELL_KIND_COMMON_MATERIALS
                        and target_model_id not in ALL_CRAFTING_MATERIAL_MODEL_IDS
                    ):
                        continue

                    candidate_sources = [
                        (item, source_label)
                        for item, source_label in [*regular_sources, *material_sources]
                        if int(item.model_id) == target_model_id
                    ]
                    matching_sources: list[tuple["InventoryItemInfo", str]] = []
                    protected_sources: list[tuple["InventoryItemInfo", str, str]] = []
                    for item, source_label in candidate_sources:
                        hard_protection = policy.get_hard_protection_hit(item, all_enabled_sell_rules)
                        if hard_protection is not None:
                            _destination, protection_reason = hard_protection
                            protected_sources.append((item, source_label, protection_reason))
                            claimed_storage_item_ids.add(int(item.item_id))
                            continue
                        matching_sources.append((item, source_label))
                    self._append_protected_withdraw_entries(
                        protected_preview_entries,
                        protected_sources,
                        rule_reference=rule_reference,
                    )
                    if not matching_sources:
                        continue

                    current_matching_items = [item for item in current_items if int(item.model_id) == target_model_id]
                    current_quantity = _sum_item_quantities(current_matching_items)
                    storage_quantity = _sum_item_quantities([item for item, _source_label in matching_sources])
                    destination = (
                        material_destination(target_model_id)
                        if rule.kind == SELL_KIND_COMMON_MATERIALS
                        else explicit_destination(matching_sources[0][0])
                    )
                    storage_keep_reservations, storage_reserved_keep = _storage_keep_reservations(
                        matching_sources,
                        max(0, int(target.keep_count)),
                    )
                    inventory_keep_count = max(0, int(target.keep_count) - storage_reserved_keep)
                    withdraw_quantity = max(0, storage_quantity - storage_reserved_keep)
                    for item, _source_label in matching_sources:
                        claimed_storage_item_ids.add(int(item.item_id))
                    if withdraw_quantity <= 0:
                        continue
                    if current_quantity + withdraw_quantity <= inventory_keep_count:
                        continue
                    if not xunlai_model_target_has_sell_service(
                        rule,
                        target_model_id,
                        matching_sources,
                        coords,
                        withdraw_quantity=withdraw_quantity,
                        keep_count=inventory_keep_count,
                    ):
                        continue

                    model_keep_overrides[(safe_rule_id, target_model_id)] = inventory_keep_count
                    self._append_withdrawals(
                        transfers,
                        matching_sources,
                        quantity=withdraw_quantity,
                        rule_reference=rule_reference,
                        key=f"xunlai_sell:{safe_rule_id}:model:{target_model_id}",
                        reserved_quantities=storage_keep_reservations,
                    )
                continue

            if rule.kind == SELL_KIND_RUNE_TRADER_TARGET:
                if coords.get(MERCHANT_TYPE_RUNE_TRADER) is None:
                    continue
                for target in normalize_rune_sell_targets(getattr(rule, "rune_sell_targets", [])):
                    target_identifier = normalize_rune_identifier(target.identifier)
                    if not target_identifier:
                        continue
                    candidate_sources = [
                        (item, source_label)
                        for item, source_label in regular_sources
                        if item.standalone_kind == RUNE_STANDALONE_KIND and target_identifier in item.rune_identifiers
                    ]
                    matching_sources: list[tuple["InventoryItemInfo", str]] = []
                    protected_sources: list[tuple["InventoryItemInfo", str, str]] = []
                    for item, source_label in candidate_sources:
                        hard_protection = policy.get_hard_protection_hit(item, all_enabled_sell_rules)
                        if hard_protection is not None:
                            _destination, protection_reason = hard_protection
                            protected_sources.append((item, source_label, protection_reason))
                            claimed_storage_item_ids.add(int(item.item_id))
                            continue
                        matching_sources.append((item, source_label))
                    self._append_protected_withdraw_entries(
                        protected_preview_entries,
                        protected_sources,
                        rule_reference=rule_reference,
                    )
                    if not matching_sources:
                        continue

                    current_matching_items = [
                        item
                        for item in current_items
                        if item.standalone_kind == RUNE_STANDALONE_KIND and target_identifier in item.rune_identifiers
                    ]
                    current_quantity = _sum_item_quantities(current_matching_items)
                    storage_quantity = _sum_item_quantities([item for item, _source_label in matching_sources])
                    withdraw_quantity = max(
                        0,
                        min(
                            storage_quantity,
                            current_quantity + storage_quantity - max(0, int(target.keep_count)),
                        ),
                    )
                    for item, _source_label in matching_sources:
                        claimed_storage_item_ids.add(int(item.item_id))
                    if withdraw_quantity <= 0:
                        continue
                    rune_keep_overrides[(safe_rule_id, target_identifier)] = current_quantity
                    self._append_withdrawals(
                        transfers,
                        matching_sources,
                        quantity=withdraw_quantity,
                        rule_reference=rule_reference,
                        key=f"xunlai_sell:{safe_rule_id}:rune:{target_identifier}",
                    )
                continue

            if rule.kind in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
                matching_sources: list[tuple["InventoryItemInfo", str]] = []
                for item, source_label in regular_sources:
                    destination = equippable_destination(item, rule)
                    if not destination:
                        continue
                    if coords.get(destination) is None:
                        claimed_storage_item_ids.add(int(item.item_id))
                        continue
                    if not policy.rule_matches_selected_rarity(item, rule):
                        continue
                    hard_protection = policy.get_hard_protection_hit(item, all_enabled_sell_rules)
                    if hard_protection is not None:
                        _destination, protection_reason = hard_protection
                        self._append_protected_withdraw_entries(
                            protected_preview_entries,
                            [(item, source_label, protection_reason)],
                            rule_reference=rule_reference,
                        )
                        claimed_storage_item_ids.add(int(item.item_id))
                        continue
                    matching_sources.append((item, source_label))
                    claimed_storage_item_ids.add(int(item.item_id))
                if not matching_sources:
                    continue
                equippable_rule_ids.add(safe_rule_id)
                self._append_withdrawals(
                    transfers,
                    matching_sources,
                    quantity=_sum_item_quantities([item for item, _source_label in matching_sources]),
                    rule_reference=rule_reference,
                    key=f"xunlai_sell:{safe_rule_id}:equippable",
                )

        adjusted_rules: list[SellRule] = []
        for _rule_index, rule in enabled_xunlai_rules:
            cloned_rule = _clone_xunlai_sell_rule(
                rule,
                model_keep_overrides=model_keep_overrides,
                rune_keep_overrides=rune_keep_overrides,
                include_equippable=normalize_rule_id(getattr(rule, "rule_id", "")) in equippable_rule_ids,
            )
            if cloned_rule is not None:
                adjusted_rules.append(cloned_rule)

        return transfers, adjusted_rules


STOCK_KEY_MODEL_PREFIX = "model:"

STOCK_KEY_IDENTIFIER_PREFIX = "identifier:"


@dataclass
class StockLocationCounts:
    key: str
    label: str
    inventory_count: int = 0
    storage_count: int = 0
    combined_count: int = 0
    exact: bool = False


def _cleanup_target_key(target: object) -> tuple[int, str]:
    model_id = max(0, _safe_int(getattr(target, "model_id", 0), 0))
    return model_id, _normalize_cleanup_target_scope(getattr(target, "scope", ""), model_id)


def _make_model_stock_key(model_id: object) -> str:
    safe_model_id = max(0, _safe_int(model_id, 0))
    return f"{STOCK_KEY_MODEL_PREFIX}{safe_model_id}" if safe_model_id > 0 else ""


def _make_identifier_stock_key(identifier: object) -> str:
    safe_identifier = _normalize_rune_identifier(identifier)
    return f"{STOCK_KEY_IDENTIFIER_PREFIX}{safe_identifier}" if safe_identifier else ""


def _parse_stock_key(key: object) -> tuple[str, str]:
    safe_key = str(key or "").strip()
    if safe_key.startswith(STOCK_KEY_MODEL_PREFIX):
        return STOCK_KEY_MODEL_PREFIX, safe_key[len(STOCK_KEY_MODEL_PREFIX) :]
    if safe_key.startswith(STOCK_KEY_IDENTIFIER_PREFIX):
        return STOCK_KEY_IDENTIFIER_PREFIX, safe_key[len(STOCK_KEY_IDENTIFIER_PREFIX) :]
    return "", safe_key


cleanup_target_key = _cleanup_target_key
make_model_stock_key = _make_model_stock_key
make_identifier_stock_key = _make_identifier_stock_key
parse_stock_key = _parse_stock_key


class CrafterRecipeView(Protocol):
    @property
    def model_id(self) -> int: ...
    @property
    def vendor_key(self) -> str: ...
    @property
    def vendor_name(self) -> str: ...
    @property
    def coords(self) -> tuple[float, float]: ...
    @property
    def title_id(self) -> int: ...
    @property
    def required_rank(self) -> int: ...
    @property
    def skill_points(self) -> int: ...
    @property
    def gold_cost(self) -> int: ...
    @property
    def ingredients(self) -> tuple[tuple[int, int], ...]: ...


class PurchaseTargetView(Protocol):
    @property
    def model_id(self) -> int: ...
    @property
    def target_count(self) -> int: ...


class PurchaseRequestView(Protocol):
    @property
    def merchant_stock_targets(self) -> Sequence[PurchaseTargetView]: ...


class PurchaseCatalogView(Protocol):
    @property
    def catalog_merchant_essentials(self) -> Sequence[dict[str, object]]: ...
    def get_model_entry(self, model_id: int) -> dict[str, object] | None: ...


class BuyPlanner[R: CrafterRecipeView]:
    def __init__(
        self,
        *,
        rules: Callable[[], list[BuyRule]],
        normalize_rule: Callable[[BuyRule], BuyRule | None],
        scroll_stock: Callable[[object], bool],
        merchant_type: Callable[[BuyRule], str],
        recipes: Callable[[], Mapping[int, tuple[R, ...]]],
        catalog: Callable[[], PurchaseCatalogView],
        dye_model: Callable[[], int],
        title_rank: Callable[[int], tuple[int, str, int]],
        skill_points: Callable[[], tuple[int, int]],
        carried_gold: Callable[[], int],
        stored_gold: Callable[[], int],
        material_storage: Callable[[int], tuple[int, int | None, int]],
        free_slots: Callable[[], int],
        model_label: Callable[[int], str],
        model_label_short: Callable[[int], str],
        rune_label: Callable[[str], str],
        rule_reference: Callable[[int, BuyRule], str],
        scroll_service_label: Callable[[], str],
        buy_kind_labels: Callable[[], Mapping[str, str]],
        merchant_type_labels: Callable[[], Mapping[str, str]],
    ) -> None:
        self._rules = rules
        self._normalize_rule = normalize_rule
        self._scroll_stock = scroll_stock
        self._merchant_type = merchant_type
        self._recipes = recipes
        self._catalog = catalog
        self._dye_model = dye_model
        self._title_rank = title_rank
        self._skill_points = skill_points
        self._carried_gold = carried_gold
        self._stored_gold = stored_gold
        self._material_storage = material_storage
        self._free_slots = free_slots
        self._model_label = model_label
        self._model_label_short = model_label_short
        self._rune_label = rune_label
        self._rule_reference = rule_reference
        self._scroll_service_label = scroll_service_label
        self._buy_kind_labels = buy_kind_labels
        self._merchant_type_labels = merchant_type_labels

    def get_material_catalog_entry(self, model_id: int) -> dict[str, object] | None:
        entry = self._catalog().get_model_entry(model_id)
        if entry is None:
            return None
        material_type = str(entry.get("material_type", "")).strip().lower()
        if material_type not in {"common", "rare"}:
            return None
        return entry

    def get_merchant_essential(self, model_id: int) -> dict[str, object] | None:
        safe_model_id = max(0, _safe_int(model_id, 0))
        for entry in self._catalog().catalog_merchant_essentials:
            if int(entry.get("model_id", 0)) == safe_model_id:
                return entry
        return None

    def merchant_stock_target_supports_xunlai_first(self, model_id: int) -> bool:
        """Return whether v1 can identify this ordinary Merchant Stock target by model alone."""

        safe_model_id = max(0, _safe_int(model_id, 0))
        if safe_model_id <= 0 or self._scroll_stock(safe_model_id):
            return False
        if safe_model_id == self._dye_model():
            return False
        if safe_model_id in ALL_CRAFTING_MATERIAL_MODEL_IDS or safe_model_id in self._recipes():
            return False
        entry = self.get_merchant_essential(safe_model_id)
        if entry is None:
            return False
        return str(entry.get("item_type", "") or "").strip().casefold() != "dye"

    def get_configured_xunlai_first_keep_by_model(self) -> dict[int, int]:
        """Build the active cleanup floor for supported opted-in Merchant Stock targets."""

        keep_by_model: dict[int, int] = {}
        for buy_rule in self._rules():
            normalized_rule = self._normalize_rule(buy_rule)
            if (
                normalized_rule is None
                or not normalized_rule.enabled
                or normalized_rule.kind != BUY_KIND_MERCHANT_STOCK
            ):
                continue
            for target in _normalize_merchant_stock_targets(normalized_rule.merchant_stock_targets):
                model_id = max(0, int(target.model_id))
                target_count = max(0, int(target.target_count))
                if (
                    not bool(target.check_xunlai_first)
                    or target_count <= 0
                    or not self.merchant_stock_target_supports_xunlai_first(model_id)
                ):
                    continue
                keep_by_model[model_id] = max(target_count, keep_by_model.get(model_id, 0))
        return keep_by_model

    def get_standalone_rune_identifier_counts(self, items: list["InventoryItemInfo"]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            if item.standalone_kind != RUNE_STANDALONE_KIND:
                continue
            for identifier in item.rune_identifiers:
                safe_identifier = _normalize_rune_identifier(identifier)
                if not safe_identifier:
                    continue
                counts[safe_identifier] = counts.get(safe_identifier, 0) + max(0, int(item.quantity))
        return counts

    def get_storage_transfer_items_for_stock_key(
        self,
        storage_items: list["InventoryItemInfo"],
        stock_key: str,
        *,
        quantity: int,
        label: str,
        direction: str = STORAGE_TRANSFER_WITHDRAW,
    ) -> list[PlannedStorageTransfer]:
        normalized_quantity = max(0, int(quantity))
        if normalized_quantity <= 0:
            return []

        stock_prefix, stock_value = _parse_stock_key(stock_key)
        matching_items: list["InventoryItemInfo"] = []
        if stock_prefix == STOCK_KEY_IDENTIFIER_PREFIX:
            safe_identifier = _normalize_rune_identifier(stock_value)
            matching_items = [
                item
                for item in storage_items
                if item.standalone_kind == RUNE_STANDALONE_KIND and safe_identifier in item.rune_identifiers
            ]
        elif stock_prefix == STOCK_KEY_MODEL_PREFIX:
            safe_model_id = max(0, _safe_int(stock_value, 0))
            matching_items = [item for item in storage_items if int(item.model_id) == safe_model_id]

        transfers: list[PlannedStorageTransfer] = []
        remaining = normalized_quantity
        for item in matching_items:
            if remaining <= 0:
                break
            move_quantity = min(remaining, max(0, int(item.quantity)))
            if move_quantity <= 0:
                continue
            transfers.append(
                PlannedStorageTransfer(
                    direction=direction,
                    key=stock_key,
                    label=label,
                    item_id=int(item.item_id),
                    quantity=move_quantity,
                    model_id=int(item.model_id),
                )
            )
            remaining -= move_quantity
        return transfers

    def apply_max_per_run(self, needed: int, max_per_run: int) -> int:
        capped_needed = max(0, int(needed))
        cap = max(0, int(max_per_run))
        if cap > 0:
            capped_needed = min(capped_needed, cap)
        return capped_needed

    def make_purchase_target_cleanup(
        self,
        *,
        rule_kind: str,
        rule_index: int,
        target_key: object,
        target_count: int,
        max_per_run: int,
        after_purchase: object,
        completes_target: bool,
        xunlai_involved: bool = False,
    ) -> PurchaseTargetCleanup:
        return PurchaseTargetCleanup(
            rule_kind=str(rule_kind or ""),
            rule_index=int(rule_index),
            target_key=str(target_key or "").strip(),
            target_count=max(0, int(target_count)),
            max_per_run=max(0, int(max_per_run)),
            after_purchase=_normalize_after_purchase_action(after_purchase),
            completes_target=bool(completes_target),
            xunlai_involved=bool(xunlai_involved),
        )

    def get_purchase_cleanup_preview_suffix(
        self,
        after_purchase: object,
        *,
        completes_target: bool,
        xunlai_involved: bool = False,
    ) -> str:
        action = _normalize_after_purchase_action(after_purchase)
        if action == AFTER_PURCHASE_KEEP:
            return ""
        if not bool(completes_target):
            return "The configured after-purchase change will wait until a verified purchase completes the target."
        if bool(xunlai_involved):
            return "The configured after-purchase change will not run because this target uses Xunlai Storage."
        if action == AFTER_PURCHASE_RESET_QUANTITY:
            return "After a verified purchase completes the target, reset its quantity to 0."
        if action == AFTER_PURCHASE_REMOVE_ENTRY:
            return "After a verified purchase completes the target, remove this target."
        return ""

    def get_consumable_crafter_recipe_for_model(self, model_id: int) -> R | None:
        recipes = self._recipes().get(max(0, int(model_id)), ())
        if not recipes:
            return None
        for recipe in recipes:
            current_rank, _tier_name, _points = self._title_rank(recipe.title_id)
            if current_rank >= int(recipe.required_rank):
                return recipe
        return recipes[0]

    def get_consumable_craft_cap_from_reserved_resources(
        self,
        recipe: R,
        *,
        available_model_counts: dict[int, int],
        skill_points_remaining: int,
        gold_remaining: int,
        requested_quantity: int = 1,
    ) -> tuple[int, list[str]]:
        blockers: list[str] = []
        caps: list[int] = []
        safe_requested_quantity = max(1, int(requested_quantity))

        skill_points_per_craft = max(0, int(recipe.skill_points))
        safe_skill_points_remaining = max(0, int(skill_points_remaining))
        if skill_points_per_craft > 0:
            caps.append(safe_skill_points_remaining // skill_points_per_craft)
            if safe_skill_points_remaining < skill_points_per_craft:
                needed_skill_points = skill_points_per_craft * safe_requested_quantity
                blockers.append(f"Need {needed_skill_points} skill point(s); found {safe_skill_points_remaining}.")

        gold_cost = max(0, int(recipe.gold_cost))
        safe_gold_remaining = max(0, int(gold_remaining))
        if gold_cost > 0:
            caps.append(safe_gold_remaining // gold_cost)
            if safe_gold_remaining < gold_cost:
                needed_gold = gold_cost * safe_requested_quantity
                blockers.append(f"Need {needed_gold} gold; found {safe_gold_remaining}.")

        for ingredient_model_id, quantity_per_craft in recipe.ingredients:
            safe_quantity = max(0, int(quantity_per_craft))
            if safe_quantity <= 0:
                continue
            available = max(0, int(available_model_counts.get(int(ingredient_model_id), 0)))
            caps.append(available // safe_quantity)
            if available < safe_quantity:
                needed_quantity = safe_quantity * safe_requested_quantity
                blockers.append(
                    f"Need {needed_quantity} {self._model_label_short(int(ingredient_model_id))}; found {available}."
                )

        return (min(caps) if caps else 0), blockers

    def estimate_consumable_crafter_free_slots_needed(
        self,
        planned_crafts: list[PlannedConsumableCraft],
        inventory_model_counts: dict[int, int],
    ) -> int:
        if not planned_crafts:
            return 0
        safe_inventory_counts = {
            max(0, int(model_id)): max(0, int(quantity))
            for model_id, quantity in dict(inventory_model_counts or {}).items()
            if max(0, int(model_id)) > 0 and max(0, int(quantity)) > 0
        }
        output_models: set[int] = set()
        missing_material_models: set[int] = set()
        for craft in planned_crafts:
            craft_quantity = max(0, int(craft.quantity))
            if craft_quantity <= 0:
                continue
            craft_model_id = max(0, int(craft.model_id))
            if craft_model_id > 0 and safe_inventory_counts.get(craft_model_id, 0) <= 0:
                output_models.add(craft_model_id)
            recipe = self.get_consumable_crafter_recipe_for_model(craft_model_id)
            if recipe is None:
                continue
            for ingredient_model_id, ingredient_quantity in recipe.ingredients:
                safe_ingredient_model_id = max(0, int(ingredient_model_id))
                if safe_ingredient_model_id <= 0:
                    continue
                total_required = max(0, int(ingredient_quantity)) * craft_quantity
                if total_required > max(0, int(safe_inventory_counts.get(safe_ingredient_model_id, 0))):
                    missing_material_models.add(safe_ingredient_model_id)
        return len(output_models | missing_material_models)

    def plan_consumable_crafter_bag_space_warning(
        self,
        plan: PlanResult,
        *,
        inventory_model_counts: dict[int, int],
    ) -> None:
        if not plan.consumable_crafter_buys:
            return
        estimated_needed = self.estimate_consumable_crafter_free_slots_needed(
            plan.consumable_crafter_buys,
            inventory_model_counts,
        )
        if estimated_needed <= 0:
            return
        free_slots = self._free_slots()
        if free_slots < 0:
            plan.entries.append(
                ExecutionPlanEntry(
                    "buy",
                    MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                    "Inventory space",
                    0,
                    PLAN_STATE_SKIPPED,
                    f"Could not verify free inventory slots. Consumable crafting may need up to {estimated_needed} free slot(s).",
                    status_hint=PREVIEW_STATUS_WARNING,
                )
            )
            return
        if free_slots < estimated_needed:
            plan.entries.append(
                ExecutionPlanEntry(
                    "buy",
                    MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                    "Inventory space",
                    0,
                    PLAN_STATE_SKIPPED,
                    f"Low inventory space: consumable crafting may need up to {estimated_needed} free slot(s); found {free_slots}.",
                    status_hint=PREVIEW_STATUS_WARNING,
                )
            )

    def get_stock_count_for_key(
        self,
        stock_key: str,
        model_counts: dict[int, int],
        identifier_counts: dict[str, int],
    ) -> int:
        stock_prefix, stock_value = _parse_stock_key(stock_key)
        if stock_prefix == STOCK_KEY_MODEL_PREFIX:
            return max(0, int(model_counts.get(max(0, _safe_int(stock_value, 0)), 0)))
        if stock_prefix == STOCK_KEY_IDENTIFIER_PREFIX:
            return max(0, int(identifier_counts.get(_normalize_rune_identifier(stock_value), 0)))
        return 0

    def adjust_stock_count_for_key(
        self,
        stock_key: str,
        delta: int,
        *,
        model_counts: dict[int, int],
        identifier_counts: dict[str, int],
    ) -> None:
        safe_delta = int(delta)
        if safe_delta == 0:
            return

        stock_prefix, stock_value = _parse_stock_key(stock_key)
        if stock_prefix == STOCK_KEY_MODEL_PREFIX:
            model_id = max(0, _safe_int(stock_value, 0))
            if model_id <= 0:
                return
            next_count = max(0, int(model_counts.get(model_id, 0)) + safe_delta)
            if next_count > 0:
                model_counts[model_id] = next_count
            else:
                model_counts.pop(model_id, None)
            return

        if stock_prefix == STOCK_KEY_IDENTIFIER_PREFIX:
            identifier = _normalize_rune_identifier(stock_value)
            if not identifier:
                return
            next_count = max(0, int(identifier_counts.get(identifier, 0)) + safe_delta)
            if next_count > 0:
                identifier_counts[identifier] = next_count
            else:
                identifier_counts.pop(identifier, None)

    def build_stock_location_counts(
        self,
        stock_key: str,
        label: str,
        *,
        inventory_model_counts: dict[int, int],
        inventory_identifier_counts: dict[str, int],
        storage_model_counts: dict[int, int] | None = None,
        storage_identifier_counts: dict[str, int] | None = None,
        storage_exact: bool = False,
    ) -> StockLocationCounts:
        inventory_count = self.get_stock_count_for_key(
            stock_key,
            inventory_model_counts,
            inventory_identifier_counts,
        )
        storage_count = 0
        if storage_exact:
            storage_count = self.get_stock_count_for_key(
                stock_key,
                storage_model_counts or {},
                storage_identifier_counts or {},
            )
        return StockLocationCounts(
            key=stock_key,
            label=str(label or stock_key),
            inventory_count=inventory_count,
            storage_count=storage_count,
            combined_count=inventory_count + storage_count,
            exact=bool(storage_exact),
        )

    def plan_buy_actions(
        self,
        plan: PlanResult,
        sim_model_counts: dict[int, int],
        *,
        execution_context: PurchaseRequestView | None = None,
        sim_inventory_items: list["InventoryItemInfo"] | None = None,
        storage_items: list["InventoryItemInfo"] | None = None,
        consumable_crafter_only: bool = False,
        exclude_consumable_crafter: bool = False,
        allowed_rule_kinds: set[str] | None = None,
        bypass_xunlai_first: bool = False,
    ) -> None:
        """Plan purchases against simulated inventory, storage, currency, and target reservations.

        The simulation applies earlier planned moves and shared resource consumption so later
        targets cannot spend the same stock, materials, skill points, or gold twice.
        """

        supported_map = bool(plan.supported_map)
        supported_reason = str(plan.supported_reason or "")
        coords = dict(plan.coords)
        sim_inventory_items = list(sim_inventory_items or [])
        storage_items = list(storage_items or [])
        sim_storage_items = [replace(item, quantity=max(0, int(item.quantity))) for item in storage_items]
        inventory_identifier_counts = self.get_standalone_rune_identifier_counts(sim_inventory_items)
        storage_model_counts = get_inventory_model_counts(sim_storage_items) if plan.storage_exact else {}
        storage_identifier_counts = (
            self.get_standalone_rune_identifier_counts(sim_storage_items) if plan.storage_exact else {}
        )
        consumable_reserved_model_counts: dict[int, int] | None = None
        consumable_skill_points_remaining: int | None = None
        consumable_gold_remaining: int | None = None
        consumable_material_storage_counts: dict[int, int] = {}

        def _get_consumable_reserved_model_count(model_id: int) -> int:
            nonlocal consumable_reserved_model_counts
            safe_model_id = max(0, int(model_id))
            if consumable_reserved_model_counts is None:
                consumable_reserved_model_counts = {}
            if safe_model_id not in consumable_reserved_model_counts:
                available = max(0, int(sim_model_counts.get(safe_model_id, 0)))
                if plan.storage_exact:
                    available += max(0, int(storage_model_counts.get(safe_model_id, 0)))
                    if safe_model_id in ALL_CRAFTING_MATERIAL_MODEL_IDS:
                        if safe_model_id not in consumable_material_storage_counts:
                            material_quantity, _slot, _bag_size = self._material_storage(safe_model_id)
                            consumable_material_storage_counts[safe_model_id] = max(0, int(material_quantity))
                        available += max(0, int(consumable_material_storage_counts.get(safe_model_id, 0)))
                consumable_reserved_model_counts[safe_model_id] = available
            return max(0, int(consumable_reserved_model_counts.get(safe_model_id, 0)))

        def _ensure_consumable_reserved_resources(recipe: R) -> tuple[dict[int, int], int, int]:
            nonlocal consumable_skill_points_remaining, consumable_gold_remaining
            if consumable_skill_points_remaining is None:
                current_skill_points, _total_skill_points = self._skill_points()
                consumable_skill_points_remaining = max(0, int(current_skill_points))
            if consumable_gold_remaining is None:
                consumable_gold_remaining = max(0, int(self._carried_gold()))
                if plan.storage_exact:
                    consumable_gold_remaining += max(0, int(self._stored_gold()))
            for ingredient_model_id, _quantity_per_craft in recipe.ingredients:
                _get_consumable_reserved_model_count(int(ingredient_model_id))
            return (
                consumable_reserved_model_counts or {},
                max(0, int(consumable_skill_points_remaining)),
                max(0, int(consumable_gold_remaining)),
            )

        def _consume_reserved_consumable_resources(recipe: R, quantity: int) -> None:
            nonlocal consumable_skill_points_remaining, consumable_gold_remaining
            safe_quantity = max(0, int(quantity))
            if safe_quantity <= 0:
                return
            if consumable_skill_points_remaining is not None:
                consumable_skill_points_remaining = max(
                    0,
                    int(consumable_skill_points_remaining) - (max(0, int(recipe.skill_points)) * safe_quantity),
                )
            if consumable_gold_remaining is not None:
                consumable_gold_remaining = max(
                    0,
                    int(consumable_gold_remaining) - (max(0, int(recipe.gold_cost)) * safe_quantity),
                )
            if consumable_reserved_model_counts is not None:
                for ingredient_model_id, ingredient_quantity in recipe.ingredients:
                    consumable_reserved_model_counts[int(ingredient_model_id)] = max(
                        0,
                        int(consumable_reserved_model_counts.get(int(ingredient_model_id), 0))
                        - (max(0, int(ingredient_quantity)) * safe_quantity),
                    )

        buy_rule_sources: list[tuple[int, BuyRule]] = list(enumerate(self._rules()))
        request_stock_targets = execution_context.merchant_stock_targets if execution_context is not None else ()
        if request_stock_targets:
            buy_rule_sources.append(
                (
                    -1,
                    BuyRule(
                        enabled=True,
                        kind=BUY_KIND_MERCHANT_STOCK,
                        merchant_type=MERCHANT_TYPE_MERCHANT,
                        merchant_stock_targets=[
                            MerchantStockTarget(
                                model_id=max(0, int(target.model_id)),
                                target_count=max(0, int(target.target_count)),
                                max_per_run=0,
                                after_purchase=AFTER_PURCHASE_KEEP,
                                check_xunlai_first=False,
                            )
                            for target in request_stock_targets
                        ],
                        name="Request-scoped Merchant Stock",
                    ),
                )
            )

        for buy_rule_index, buy_rule in buy_rule_sources:
            normalized_buy_rule = self._normalize_rule(buy_rule)
            if normalized_buy_rule is None:
                continue
            buy_rule = normalized_buy_rule
            if not buy_rule.enabled:
                continue
            if allowed_rule_kinds is not None and buy_rule.kind not in allowed_rule_kinds:
                continue
            if consumable_crafter_only and buy_rule.kind != BUY_KIND_CONSUMABLE_CRAFTER_TARGET:
                continue
            if exclude_consumable_crafter and buy_rule.kind == BUY_KIND_CONSUMABLE_CRAFTER_TARGET:
                continue
            buy_rule_reference = (
                "Request-scoped Merchant Stock"
                if buy_rule_index < 0
                else self._rule_reference(buy_rule_index, buy_rule)
            )

            if buy_rule.kind == BUY_KIND_MATERIAL_TARGET:
                if not buy_rule.material_targets:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_MATERIALS,
                            self._buy_kind_labels()[buy_rule.kind],
                            0,
                            PLAN_STATE_SKIPPED,
                            f"{buy_rule_reference} has no crafting materials selected.",
                        )
                    )
                    continue

                for material_target in buy_rule.material_targets:
                    material_model_id = max(0, int(material_target.model_id))
                    material_label = self._model_label(material_model_id)
                    if material_model_id <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_MATERIALS,
                                self._buy_kind_labels()[buy_rule.kind],
                                0,
                                PLAN_STATE_SKIPPED,
                                f"Choose a crafting material for {buy_rule_reference}.",
                            )
                        )
                        continue

                    material_entry = self.get_material_catalog_entry(material_model_id)
                    if material_entry is None:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_MATERIALS,
                                material_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                f"{buy_rule_reference} cannot buy this item as a crafting material.",
                                status_hint=PREVIEW_STATUS_BLOCKED,
                            )
                        )
                        continue

                    merchant_type = material_destination(material_model_id)
                    merchant_coords = coords.get(merchant_type)
                    if not supported_map:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=merchant_type,
                                label=material_label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=supported_reason,
                            )
                        )
                        continue

                    if merchant_coords is None:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=merchant_type,
                                label=material_label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=f"{self._merchant_type_labels()[merchant_type]} could not be found in the current map.",
                            )
                        )
                        continue

                    current_count = sim_model_counts.get(material_model_id, 0)
                    missing = max(0, int(material_target.target_count) - current_count)
                    if missing <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                merchant_type,
                                material_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Target already met: inventory has {current_count}; "
                                    f"target is {material_target.target_count}."
                                ),
                                status_hint=PREVIEW_STATUS_ALREADY_DONE,
                            )
                        )
                        continue

                    batch_size = material_batch_size(material_model_id)
                    if batch_size > 1:
                        needed = ((missing + batch_size - 1) // batch_size) * batch_size
                        if material_target.max_per_run > 0:
                            capped_needed = (int(material_target.max_per_run) // batch_size) * batch_size
                            if capped_needed <= 0:
                                plan.entries.append(
                                    ExecutionPlanEntry(
                                        "buy",
                                        merchant_type,
                                        material_label,
                                        0,
                                        PLAN_STATE_SKIPPED,
                                        (
                                            f"Cannot buy this material because the trader sells lots of {batch_size}, "
                                            f"but Max Per Run is {material_target.max_per_run}."
                                        ),
                                        status_hint=PREVIEW_STATUS_BLOCKED,
                                    )
                                )
                                continue
                            needed = min(needed, capped_needed)
                    else:
                        needed = self.apply_max_per_run(missing, material_target.max_per_run)

                    if needed <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                merchant_type,
                                material_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Target already met: inventory has {current_count}; "
                                    f"target is {material_target.target_count}."
                                ),
                                status_hint=PREVIEW_STATUS_ALREADY_DONE,
                            )
                        )
                        continue

                    sim_model_counts[material_model_id] = current_count + needed
                    plan.material_buys.append(
                        PlannedMaterialBuy(
                            merchant_type=merchant_type,
                            model_id=material_model_id,
                            quantity=needed,
                            label=material_label,
                            batch_size=batch_size,
                            cleanup=self.make_purchase_target_cleanup(
                                rule_kind=buy_rule.kind,
                                rule_index=buy_rule_index,
                                target_key=material_model_id,
                                target_count=material_target.target_count,
                                max_per_run=material_target.max_per_run,
                                after_purchase=material_target.after_purchase,
                                completes_target=current_count + needed >= int(material_target.target_count),
                            ),
                        )
                    )
                    reason = (
                        f"Inventory has {current_count}; target is {material_target.target_count}. "
                        f"Buy {needed}. Live check: verify carried gold before each purchase."
                    )
                    if batch_size > 1:
                        reason = (
                            f"Inventory has {current_count}; target is {material_target.target_count}. "
                            f"Buy {needed} as {needed // batch_size} trader lots of {batch_size}; "
                            f"the shortage is {missing}. Live check: verify carried gold before each purchase."
                        )
                    cleanup_suffix = self.get_purchase_cleanup_preview_suffix(
                        material_target.after_purchase,
                        completes_target=current_count + needed >= int(material_target.target_count),
                    )
                    if cleanup_suffix:
                        reason = f"{reason} {cleanup_suffix}"
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy", merchant_type, material_label, needed, PLAN_STATE_WILL_EXECUTE, reason
                        )
                    )
                continue

            if buy_rule.kind == BUY_KIND_MERCHANT_STOCK:
                merchant_stock_targets = _normalize_merchant_stock_targets(buy_rule.merchant_stock_targets)
                if not merchant_stock_targets:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_MERCHANT,
                            self._buy_kind_labels()[buy_rule.kind],
                            0,
                            PLAN_STATE_SKIPPED,
                            f"{buy_rule_reference} has no merchant stock items selected.",
                        )
                    )
                    continue
                merchant_type = self._merchant_type(buy_rule)
                merchant_coords = coords.get(merchant_type)
                for merchant_stock_target in merchant_stock_targets:
                    merchant_stock_model_id = max(0, int(merchant_stock_target.model_id))
                    model_label = self._model_label(merchant_stock_model_id)
                    target_merchant_type = (
                        MERCHANT_TYPE_SCROLL_TRADER if self._scroll_stock(merchant_stock_model_id) else merchant_type
                    )
                    target_merchant_coords = coords.get(target_merchant_type)
                    use_xunlai_first = bool(
                        not bypass_xunlai_first
                        and merchant_stock_target.check_xunlai_first
                        and self.merchant_stock_target_supports_xunlai_first(merchant_stock_model_id)
                    )
                    if merchant_stock_model_id <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                target_merchant_type,
                                self._buy_kind_labels()[buy_rule.kind],
                                0,
                                PLAN_STATE_SKIPPED,
                                f"Choose an item for {buy_rule_reference}.",
                            )
                        )
                        continue
                    if not supported_map:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=target_merchant_type,
                                label=model_label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=supported_reason,
                            )
                        )
                        continue

                    if target_merchant_coords is None and not use_xunlai_first:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=target_merchant_type,
                                label=model_label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=(
                                    f"{self._scroll_service_label()} could not be found in the current map."
                                    if target_merchant_type == MERCHANT_TYPE_SCROLL_TRADER
                                    else f"{self._merchant_type_labels()[target_merchant_type]} could not be found in the current map."
                                ),
                            )
                        )
                        continue

                    current_count = sim_model_counts.get(merchant_stock_model_id, 0)
                    full_shortage = max(0, int(merchant_stock_target.target_count) - current_count)
                    if full_shortage <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                target_merchant_type,
                                model_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Target already met: inventory has {current_count}; "
                                    f"target is {merchant_stock_target.target_count}."
                                ),
                                status_hint=PREVIEW_STATUS_ALREADY_DONE,
                            )
                        )
                        continue

                    planned_xunlai_withdraw_quantity = 0
                    if use_xunlai_first:
                        plan.xunlai_first_merchant_stock_targets[merchant_stock_model_id] = model_label
                        if not plan.storage_exact:
                            reason = (
                                f"Inventory has {current_count}; target is {merchant_stock_target.target_count}. "
                                "Xunlai Storage must be checked before Merchant Rules can determine whether to withdraw or buy."
                            )
                            if target_merchant_coords is None:
                                reason = f"{reason} {self._merchant_type_labels()[target_merchant_type]} could not be found in the current map."
                            plan.entries.append(
                                ExecutionPlanEntry(
                                    "withdraw",
                                    MERCHANT_TYPE_STORAGE,
                                    model_label,
                                    full_shortage,
                                    PLAN_STATE_CONDITIONAL,
                                    reason,
                                    model_id=merchant_stock_model_id,
                                )
                            )
                            continue
                        if not plan.xunlai_first_storage_scan_reliable:
                            plan.entries.append(
                                ExecutionPlanEntry(
                                    "withdraw",
                                    MERCHANT_TYPE_STORAGE,
                                    model_label,
                                    0,
                                    PLAN_STATE_SKIPPED,
                                    "Xunlai Storage could not be checked reliably.",
                                    model_id=merchant_stock_model_id,
                                    status_hint=PREVIEW_STATUS_BLOCKED,
                                )
                            )
                            continue

                        stock_key = _make_model_stock_key(merchant_stock_model_id)
                        withdraw_quantity = min(
                            full_shortage,
                            max(0, int(storage_model_counts.get(merchant_stock_model_id, 0))),
                        )
                        if withdraw_quantity > 0:
                            raw_transfers = self.get_storage_transfer_items_for_stock_key(
                                sim_storage_items,
                                stock_key,
                                quantity=withdraw_quantity,
                                label=model_label,
                                direction=STORAGE_TRANSFER_WITHDRAW,
                            )
                            transfers = [
                                replace(
                                    transfer,
                                    reason="Check Xunlai first",
                                    xunlai_first_merchant_stock=True,
                                )
                                for transfer in raw_transfers
                            ]
                            planned_xunlai_withdraw_quantity = sum(
                                max(0, int(transfer.quantity)) for transfer in transfers
                            )
                            if planned_xunlai_withdraw_quantity > 0:
                                plan.storage_transfers.extend(transfers)
                                plan.entries.append(
                                    ExecutionPlanEntry(
                                        "withdraw",
                                        MERCHANT_TYPE_STORAGE,
                                        model_label,
                                        planned_xunlai_withdraw_quantity,
                                        PLAN_STATE_WILL_EXECUTE,
                                        "Withdraw matching items from Xunlai before buying the remaining shortage.",
                                        model_id=merchant_stock_model_id,
                                    )
                                )
                                self.adjust_stock_count_for_key(
                                    stock_key,
                                    -planned_xunlai_withdraw_quantity,
                                    model_counts=storage_model_counts,
                                    identifier_counts=storage_identifier_counts,
                                )
                                self.adjust_stock_count_for_key(
                                    stock_key,
                                    planned_xunlai_withdraw_quantity,
                                    model_counts=sim_model_counts,
                                    identifier_counts=inventory_identifier_counts,
                                )
                                sim_storage_items = apply_planned_transfer_quantities(
                                    sim_storage_items,
                                    transfers,
                                )
                                current_count += planned_xunlai_withdraw_quantity

                    remaining_shortage = max(0, int(merchant_stock_target.target_count) - current_count)
                    needed = self.apply_max_per_run(
                        remaining_shortage,
                        int(merchant_stock_target.max_per_run),
                    )
                    if needed <= 0:
                        continue
                    if target_merchant_coords is None:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=target_merchant_type,
                                label=model_label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=(
                                    f"{self._scroll_service_label()} could not be found in the current map."
                                    if target_merchant_type == MERCHANT_TYPE_SCROLL_TRADER
                                    else f"{self._merchant_type_labels()[target_merchant_type]} could not be found in the current map."
                                ),
                                model_id=merchant_stock_model_id,
                            )
                        )
                        continue
                    sim_model_counts[merchant_stock_model_id] = current_count + needed
                    if target_merchant_type == MERCHANT_TYPE_SCROLL_TRADER:
                        plan.scroll_trader_buys.append(
                            PlannedScrollTraderBuy(
                                model_id=merchant_stock_model_id,
                                quantity=needed,
                                label=model_label,
                                cleanup=self.make_purchase_target_cleanup(
                                    rule_kind=buy_rule.kind,
                                    rule_index=buy_rule_index,
                                    target_key=merchant_stock_model_id,
                                    target_count=merchant_stock_target.target_count,
                                    max_per_run=merchant_stock_target.max_per_run,
                                    after_purchase=merchant_stock_target.after_purchase,
                                    completes_target=current_count + needed >= int(merchant_stock_target.target_count),
                                    xunlai_involved=planned_xunlai_withdraw_quantity > 0,
                                ),
                            )
                        )
                        entry_reason = (
                            f"Inventory has {current_count}; target is {merchant_stock_target.target_count}. "
                            "Live check: buy only if an available Scroll Trader offers this item and returns "
                            "a valid quote."
                        )
                    else:
                        plan.merchant_stock_buys.append(
                            PlannedMerchantBuy(
                                model_id=merchant_stock_model_id,
                                quantity=needed,
                                label=model_label,
                                cleanup=self.make_purchase_target_cleanup(
                                    rule_kind=buy_rule.kind,
                                    rule_index=buy_rule_index,
                                    target_key=merchant_stock_model_id,
                                    target_count=merchant_stock_target.target_count,
                                    max_per_run=merchant_stock_target.max_per_run,
                                    after_purchase=merchant_stock_target.after_purchase,
                                    completes_target=current_count + needed >= int(merchant_stock_target.target_count),
                                    xunlai_involved=planned_xunlai_withdraw_quantity > 0,
                                ),
                                check_xunlai_first=use_xunlai_first,
                            )
                        )
                        entry_reason = (
                            f"Inventory has {current_count}; target is {merchant_stock_target.target_count}. "
                            "Live check: buy only if the Merchant offers this item with a usable price."
                        )
                    cleanup_suffix = self.get_purchase_cleanup_preview_suffix(
                        merchant_stock_target.after_purchase,
                        completes_target=current_count + needed >= int(merchant_stock_target.target_count),
                        xunlai_involved=planned_xunlai_withdraw_quantity > 0,
                    )
                    if cleanup_suffix:
                        entry_reason = f"{entry_reason} {cleanup_suffix}"
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            target_merchant_type,
                            model_label,
                            needed,
                            PLAN_STATE_CONDITIONAL,
                            entry_reason,
                        )
                    )
                continue

            if buy_rule.kind == BUY_KIND_CONSUMABLE_CRAFTER_TARGET:
                crafter_targets = [
                    target
                    for target in _normalize_merchant_stock_targets(buy_rule.merchant_stock_targets)
                    if int(target.model_id) in self._recipes()
                ]
                if not crafter_targets:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                            self._buy_kind_labels()[buy_rule.kind],
                            0,
                            PLAN_STATE_SKIPPED,
                            f"{buy_rule_reference} has no Consumable Crafter items selected.",
                        )
                    )
                    continue

                crafter_coords = coords.get(MERCHANT_TYPE_CONSUMABLE_CRAFTER)
                for crafter_target in crafter_targets:
                    crafter_model_id = max(0, int(crafter_target.model_id))
                    recipe = self.get_consumable_crafter_recipe_for_model(crafter_model_id)
                    crafter_label = self._model_label(crafter_model_id)
                    if recipe is None:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                                crafter_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                f"{buy_rule_reference} has no supported Consumable Crafter recipe for this item.",
                                status_hint=PREVIEW_STATUS_BLOCKED,
                            )
                        )
                        continue
                    if not supported_map:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                                crafter_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                supported_reason,
                            )
                        )
                        continue
                    if crafter_coords is None:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                                crafter_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                (
                                    "Cannot craft this item because its Consumable Crafter is available only "
                                    "at Embark Beach."
                                ),
                                status_hint=PREVIEW_STATUS_BLOCKED,
                            )
                        )
                        continue

                    current_rank, tier_name, _title_points = self._title_rank(recipe.title_id)
                    if current_rank < int(recipe.required_rank):
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                                crafter_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Cannot craft this item because {recipe.vendor_name} requires rank "
                                    f"{recipe.required_rank}; current rank is {current_rank} ({tier_name})."
                                ),
                                status_hint=PREVIEW_STATUS_BLOCKED,
                            )
                        )
                        continue

                    craft_requested_amount = (
                        _normalize_consumable_crafter_count_mode(buy_rule.consumable_crafter_count_mode)
                        == CONSUMABLE_CRAFTER_COUNT_MODE_CRAFT_AMOUNT
                    )
                    current_count = max(0, int(sim_model_counts.get(crafter_model_id, 0)))
                    if plan.storage_exact:
                        current_count += max(0, int(storage_model_counts.get(crafter_model_id, 0)))
                    if craft_requested_amount:
                        needed = self.apply_max_per_run(
                            int(crafter_target.target_count), int(crafter_target.max_per_run)
                        )
                    else:
                        missing = max(0, int(crafter_target.target_count) - current_count)
                        needed = self.apply_max_per_run(missing, int(crafter_target.max_per_run))
                    if needed <= 0:
                        reason = (
                            "Craft amount is 0, so no crafting is planned."
                            if craft_requested_amount
                            else (
                                f"Target already met: expected total is {current_count}; "
                                f"target is {crafter_target.target_count}."
                            )
                        )
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                                crafter_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                reason,
                                status_hint=(
                                    PREVIEW_STATUS_SKIPPED if craft_requested_amount else PREVIEW_STATUS_ALREADY_DONE
                                ),
                            )
                        )
                        continue

                    if not plan.storage_exact:
                        sim_model_counts[crafter_model_id] = current_count + needed
                        plan.consumable_crafter_buys.append(
                            PlannedConsumableCraft(
                                model_id=crafter_model_id,
                                quantity=needed,
                                label=crafter_label,
                                vendor_key=recipe.vendor_key,
                                vendor_name=recipe.vendor_name,
                                coords=recipe.coords,
                                cleanup=self.make_purchase_target_cleanup(
                                    rule_kind=buy_rule.kind,
                                    rule_index=buy_rule_index,
                                    target_key=crafter_model_id,
                                    target_count=crafter_target.target_count,
                                    max_per_run=crafter_target.max_per_run,
                                    after_purchase=crafter_target.after_purchase,
                                    completes_target=False,
                                    xunlai_involved=True,
                                ),
                            )
                        )
                        conditional_reason = (
                            f"Xunlai Storage has not been scanned. Up to {needed} may be crafted after "
                            "stored consumables, Material Storage, gold, and current resources are checked."
                        )
                        cleanup_suffix = self.get_purchase_cleanup_preview_suffix(
                            crafter_target.after_purchase,
                            completes_target=False,
                            xunlai_involved=True,
                        )
                        if cleanup_suffix:
                            conditional_reason = f"{conditional_reason} {cleanup_suffix}"
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                                crafter_label,
                                needed,
                                PLAN_STATE_CONDITIONAL,
                                conditional_reason,
                            )
                        )
                        continue

                    available_resource_counts, skill_points_remaining, gold_remaining = (
                        _ensure_consumable_reserved_resources(recipe)
                    )
                    craft_cap, blockers = self.get_consumable_craft_cap_from_reserved_resources(
                        recipe,
                        available_model_counts=available_resource_counts,
                        skill_points_remaining=skill_points_remaining,
                        gold_remaining=gold_remaining,
                        requested_quantity=needed,
                    )
                    craft_quantity = min(needed, max(0, int(craft_cap)))
                    if craft_quantity <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                                crafter_label,
                                needed,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Cannot craft any of the {needed} requested: "
                                    f"{' '.join(blockers) or 'skill points, gold, or materials are missing.'}"
                                ),
                                status_hint=PREVIEW_STATUS_BLOCKED,
                            )
                        )
                        continue

                    craft_uses_xunlai_items = any(
                        max(0, int(ingredient_quantity)) * craft_quantity
                        > max(0, int(sim_model_counts.get(int(ingredient_model_id), 0)))
                        for ingredient_model_id, ingredient_quantity in recipe.ingredients
                    )
                    _consume_reserved_consumable_resources(recipe, craft_quantity)
                    for ingredient_model_id, ingredient_quantity in recipe.ingredients:
                        sim_model_counts[int(ingredient_model_id)] = max(
                            0,
                            int(sim_model_counts.get(int(ingredient_model_id), 0))
                            - (int(ingredient_quantity) * craft_quantity),
                        )
                    sim_model_counts[crafter_model_id] = current_count + craft_quantity
                    plan.consumable_crafter_buys.append(
                        PlannedConsumableCraft(
                            model_id=crafter_model_id,
                            quantity=craft_quantity,
                            label=crafter_label,
                            vendor_key=recipe.vendor_key,
                            vendor_name=recipe.vendor_name,
                            coords=recipe.coords,
                            cleanup=self.make_purchase_target_cleanup(
                                rule_kind=buy_rule.kind,
                                rule_index=buy_rule_index,
                                target_key=crafter_model_id,
                                target_count=crafter_target.target_count,
                                max_per_run=crafter_target.max_per_run,
                                after_purchase=crafter_target.after_purchase,
                                completes_target=(
                                    craft_quantity >= int(crafter_target.target_count)
                                    if craft_requested_amount
                                    else current_count + craft_quantity >= int(crafter_target.target_count)
                                ),
                                xunlai_involved=craft_uses_xunlai_items,
                            ),
                        )
                    )
                    reason = (
                        f"Craft {craft_quantity} with {recipe.vendor_name}; current rank {current_rank} "
                        f"meets required rank {recipe.required_rank} ({tier_name})."
                    )
                    if craft_requested_amount:
                        reason = f"{reason} Craft-amount mode ignores existing finished consumables."
                    if craft_quantity < needed:
                        reason = f"{reason} Planned {craft_quantity} of {needed}; resources limit the remainder."
                        remaining_needed = max(0, int(needed) - int(craft_quantity))
                        if remaining_needed > 0:
                            post_resource_counts, post_skill_points, post_gold = _ensure_consumable_reserved_resources(
                                recipe
                            )
                            _remaining_cap, remaining_blockers = self.get_consumable_craft_cap_from_reserved_resources(
                                recipe,
                                available_model_counts=post_resource_counts,
                                skill_points_remaining=post_skill_points,
                                gold_remaining=post_gold,
                                requested_quantity=remaining_needed,
                            )
                            if remaining_blockers:
                                reason = f"{reason} Remaining request: {' '.join(remaining_blockers)}"
                    cleanup_suffix = self.get_purchase_cleanup_preview_suffix(
                        crafter_target.after_purchase,
                        completes_target=(
                            craft_quantity >= int(crafter_target.target_count)
                            if craft_requested_amount
                            else current_count + craft_quantity >= int(crafter_target.target_count)
                        ),
                        xunlai_involved=craft_uses_xunlai_items,
                    )
                    if cleanup_suffix:
                        reason = f"{reason} {cleanup_suffix}"
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_CONSUMABLE_CRAFTER,
                            crafter_label,
                            craft_quantity,
                            PLAN_STATE_CONDITIONAL,
                            reason,
                        )
                    )
                continue

            if buy_rule.kind == BUY_KIND_SCROLL_TRADER_TARGET:
                scroll_targets = [
                    target
                    for target in _normalize_merchant_stock_targets(buy_rule.merchant_stock_targets)
                    if self._scroll_stock(target.model_id)
                ]
                if not scroll_targets:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_SCROLL_TRADER,
                            self._buy_kind_labels()[buy_rule.kind],
                            0,
                            PLAN_STATE_SKIPPED,
                            f"{buy_rule_reference} has no supported Scroll Trader items selected.",
                        )
                    )
                    continue

                scroll_trader_coords = coords.get(MERCHANT_TYPE_SCROLL_TRADER)
                for scroll_target in scroll_targets:
                    scroll_model_id = max(0, int(scroll_target.model_id))
                    scroll_label = self._model_label(scroll_model_id)
                    if scroll_model_id <= 0 or not self._scroll_stock(scroll_model_id):
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_SCROLL_TRADER,
                                self._buy_kind_labels()[buy_rule.kind],
                                0,
                                PLAN_STATE_SKIPPED,
                                f"This item is not supported Scroll Trader stock for {buy_rule_reference}.",
                                status_hint=PREVIEW_STATUS_BLOCKED,
                            )
                        )
                        continue

                    if not supported_map:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=MERCHANT_TYPE_SCROLL_TRADER,
                                label=scroll_label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=supported_reason,
                            )
                        )
                        continue

                    if scroll_trader_coords is None:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=MERCHANT_TYPE_SCROLL_TRADER,
                                label=scroll_label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=f"{self._scroll_service_label()} could not be found in the current map.",
                            )
                        )
                        continue

                    current_count = sim_model_counts.get(scroll_model_id, 0)
                    needed = self.apply_max_per_run(
                        int(scroll_target.target_count) - current_count,
                        int(scroll_target.max_per_run),
                    )
                    if needed <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_SCROLL_TRADER,
                                scroll_label,
                                0,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Target already met: inventory has {current_count}; "
                                    f"target is {scroll_target.target_count}."
                                ),
                                status_hint=PREVIEW_STATUS_ALREADY_DONE,
                            )
                        )
                        continue

                    sim_model_counts[scroll_model_id] = current_count + needed
                    plan.scroll_trader_buys.append(
                        PlannedScrollTraderBuy(
                            model_id=scroll_model_id,
                            quantity=needed,
                            label=scroll_label,
                            cleanup=self.make_purchase_target_cleanup(
                                rule_kind=buy_rule.kind,
                                rule_index=buy_rule_index,
                                target_key=scroll_model_id,
                                target_count=scroll_target.target_count,
                                max_per_run=scroll_target.max_per_run,
                                after_purchase=scroll_target.after_purchase,
                                completes_target=current_count + needed >= int(scroll_target.target_count),
                            ),
                        )
                    )
                    scroll_reason = (
                        f"Inventory has {current_count}; target is {scroll_target.target_count}. "
                        "Live check: buy only if the available Scroll Trader offers this item and returns "
                        "a valid quote."
                    )
                    cleanup_suffix = self.get_purchase_cleanup_preview_suffix(
                        scroll_target.after_purchase,
                        completes_target=current_count + needed >= int(scroll_target.target_count),
                    )
                    if cleanup_suffix:
                        scroll_reason = f"{scroll_reason} {cleanup_suffix}"
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_SCROLL_TRADER,
                            scroll_label,
                            needed,
                            PLAN_STATE_CONDITIONAL,
                            scroll_reason,
                        )
                    )
                continue

            if buy_rule.kind == BUY_KIND_RUNE_TRADER_TARGET:
                rune_targets = _normalize_rune_trader_targets(buy_rule.rune_targets)
                if not rune_targets:
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_RUNE_TRADER,
                            self._buy_kind_labels()[buy_rule.kind],
                            0,
                            PLAN_STATE_SKIPPED,
                            f"{buy_rule_reference} has no rune or insignia targets selected.",
                        )
                    )
                    continue

                rune_trader_coords = coords.get(MERCHANT_TYPE_RUNE_TRADER)
                for rune_target in rune_targets:
                    identifier = _normalize_rune_identifier(rune_target.identifier)
                    label = self._rune_label(identifier)
                    if not identifier:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_RUNE_TRADER,
                                self._buy_kind_labels()[buy_rule.kind],
                                0,
                                PLAN_STATE_SKIPPED,
                                f"Choose a rune or insignia for {buy_rule_reference}.",
                            )
                        )
                        continue

                    if not supported_map:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                action_type="buy",
                                merchant_type=MERCHANT_TYPE_RUNE_TRADER,
                                label=label,
                                quantity=0,
                                state=PLAN_STATE_SKIPPED,
                                reason=supported_reason,
                            )
                        )
                        continue

                    stock_key = _make_identifier_stock_key(identifier)
                    stock_counts = self.build_stock_location_counts(
                        stock_key,
                        label,
                        inventory_model_counts=sim_model_counts,
                        inventory_identifier_counts=inventory_identifier_counts,
                        storage_model_counts=storage_model_counts,
                        storage_identifier_counts=storage_identifier_counts,
                        storage_exact=plan.storage_exact,
                    )
                    missing = max(0, int(rune_target.target_count) - int(stock_counts.inventory_count))
                    needed = self.apply_max_per_run(missing, int(rune_target.max_per_run))
                    if needed <= 0:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_RUNE_TRADER,
                                label,
                                0,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Target already met: inventory has {stock_counts.inventory_count}; "
                                    f"target is {rune_target.target_count}."
                                ),
                                status_hint=PREVIEW_STATUS_ALREADY_DONE,
                            )
                        )
                        continue

                    if not plan.storage_exact:
                        reason_parts = [
                            (
                                f"Inventory has {stock_counts.inventory_count}; target is {rune_target.target_count}. "
                                f"Xunlai Storage has not been scanned, so up to {needed} may need to be "
                                "withdrawn or bought."
                            ),
                        ]
                        if rune_trader_coords is None:
                            reason_parts.append("Rune Trader could not be found in the current map.")
                        cleanup_suffix = self.get_purchase_cleanup_preview_suffix(
                            rune_target.after_purchase,
                            completes_target=False,
                            xunlai_involved=True,
                        )
                        if cleanup_suffix:
                            reason_parts.append(cleanup_suffix)
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_RUNE_TRADER,
                                label,
                                needed,
                                PLAN_STATE_CONDITIONAL,
                                " ".join(reason_parts),
                            )
                        )
                        continue

                    rune_xunlai_involved = False
                    planned_rune_withdraw_quantity = 0
                    withdraw_quantity = min(
                        needed,
                        max(0, int(stock_counts.storage_count)),
                    )
                    if withdraw_quantity > 0:
                        transfers = self.get_storage_transfer_items_for_stock_key(
                            sim_storage_items,
                            stock_key,
                            quantity=withdraw_quantity,
                            label=label,
                            direction=STORAGE_TRANSFER_WITHDRAW,
                        )
                        planned_withdraw_quantity = sum(max(0, int(transfer.quantity)) for transfer in transfers)
                        if planned_withdraw_quantity > 0:
                            rune_xunlai_involved = True
                            planned_rune_withdraw_quantity += planned_withdraw_quantity
                            plan.storage_transfers.extend(transfers)
                            remaining_after_withdraw = max(0, needed - planned_withdraw_quantity)
                            withdraw_reason = (
                                "Move this quantity from Xunlai Storage to inventory; this satisfies the target, "
                                "so no purchase is needed."
                                if remaining_after_withdraw <= 0
                                else (
                                    "Move this quantity from Xunlai Storage to inventory first; "
                                    f"buy the remaining {remaining_after_withdraw} only if the Rune Trader "
                                    "confirms availability."
                                )
                            )
                            plan.entries.append(
                                ExecutionPlanEntry(
                                    "withdraw",
                                    MERCHANT_TYPE_STORAGE,
                                    label,
                                    planned_withdraw_quantity,
                                    PLAN_STATE_WILL_EXECUTE,
                                    withdraw_reason,
                                )
                            )
                            self.adjust_stock_count_for_key(
                                stock_key,
                                -planned_withdraw_quantity,
                                model_counts=storage_model_counts,
                                identifier_counts=storage_identifier_counts,
                            )
                            self.adjust_stock_count_for_key(
                                stock_key,
                                planned_withdraw_quantity,
                                model_counts=sim_model_counts,
                                identifier_counts=inventory_identifier_counts,
                            )
                            sim_storage_items = apply_planned_transfer_quantities(sim_storage_items, transfers)
                            needed -= planned_withdraw_quantity

                    if needed <= 0:
                        continue

                    if rune_trader_coords is None:
                        plan.entries.append(
                            ExecutionPlanEntry(
                                "buy",
                                MERCHANT_TYPE_RUNE_TRADER,
                                label,
                                needed,
                                PLAN_STATE_SKIPPED,
                                (
                                    f"Stored copies will be withdrawn, but the remaining {needed} cannot be bought "
                                    "because no Rune Trader is available here."
                                ),
                                status_hint=PREVIEW_STATUS_BLOCKED,
                            )
                        )
                        continue

                    plan.rune_trader_buys.append(
                        PlannedTraderBuy(
                            identifier=identifier,
                            quantity=needed,
                            label=label,
                            cleanup=self.make_purchase_target_cleanup(
                                rule_kind=buy_rule.kind,
                                rule_index=buy_rule_index,
                                target_key=identifier,
                                target_count=rune_target.target_count,
                                max_per_run=rune_target.max_per_run,
                                after_purchase=rune_target.after_purchase,
                                completes_target=(
                                    stock_counts.inventory_count + planned_rune_withdraw_quantity + needed
                                    >= int(rune_target.target_count)
                                ),
                                xunlai_involved=rune_xunlai_involved,
                            ),
                        )
                    )
                    self.adjust_stock_count_for_key(
                        stock_key,
                        needed,
                        model_counts=sim_model_counts,
                        identifier_counts=inventory_identifier_counts,
                    )
                    buy_reason = (
                        f"After planned withdrawals, inventory still needs {needed}. Live check: buy only if "
                        "the Rune Trader still offers this item and returns a valid quote."
                    )
                    cleanup_suffix = self.get_purchase_cleanup_preview_suffix(
                        rune_target.after_purchase,
                        completes_target=(
                            stock_counts.inventory_count + planned_rune_withdraw_quantity + needed
                            >= int(rune_target.target_count)
                        ),
                        xunlai_involved=rune_xunlai_involved,
                    )
                    if cleanup_suffix:
                        buy_reason = f"{buy_reason} {cleanup_suffix}"
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "buy",
                            MERCHANT_TYPE_RUNE_TRADER,
                            label,
                            needed,
                            PLAN_STATE_CONDITIONAL,
                            buy_reason,
                        )
                    )


class CleanupPlanner:
    def __init__(
        self,
        *,
        targets: Callable[[], list[CleanupTarget]],
        sources: Callable[[], list[CleanupProtectionSource]],
        keep_out: Callable[[], list[int]],
        rules: Callable[[], list[SellRule]],
        normalize_rule: Callable[[SellRule], SellRule | None],
        collect_enabled_rules: Callable[[], list[tuple[int, SellRule]]],
        policy: Callable[[], "ProtectionPolicy"],
        storage_available: Callable[[], bool],
        keep_floors: Callable[[], dict[int, int]],
        choose_keep: Callable[[list["InventoryItemInfo"], int], tuple[set[int], int]],
        target_label: Callable[[CleanupTarget], str],
        rule_reference: Callable[[int, SellRule], str],
    ) -> None:
        self._targets = targets
        self._sources = sources
        self._keep_out = keep_out
        self._rules = rules
        self._normalize_rule = normalize_rule
        self._collect_enabled_rules = collect_enabled_rules
        self._policy = policy
        self._storage_available = storage_available
        self._keep_floors = keep_floors
        self._choose_keep = choose_keep
        self._target_label = target_label
        self._rule_reference = rule_reference

    def get_sell_rule_by_id(self, sell_rule_id: object) -> SellRule | None:
        safe_rule_id = _normalize_rule_id(sell_rule_id)
        if not safe_rule_id:
            return None
        for sell_rule in self._rules():
            normalized_rule = self._normalize_rule(sell_rule)
            if normalized_rule is None:
                continue
            if str(normalized_rule.rule_id or "").strip() == safe_rule_id:
                return normalized_rule
        return None

    def get_sell_rule_index_by_id(self, sell_rule_id: object) -> int:
        safe_rule_id = _normalize_rule_id(sell_rule_id)
        if not safe_rule_id:
            return -1
        for index, sell_rule in enumerate(self._rules()):
            normalized_rule = self._normalize_rule(sell_rule)
            if normalized_rule is None:
                continue
            if str(normalized_rule.rule_id or "").strip() == safe_rule_id:
                return index
        return -1

    def append_cleanup_transfer_entry(
        self,
        plan: PlanResult,
        *,
        item_id: int,
        quantity: int,
        label: str,
        reason: str,
        model_id: int = 0,
        key: str = "",
        storage_open: bool = False,
    ) -> None:
        safe_item_id = int(item_id)
        safe_quantity = max(0, int(quantity))
        safe_model_id = max(0, int(model_id))
        if safe_item_id <= 0 or safe_quantity <= 0:
            return
        default_key = f"item:{safe_item_id}"
        transfer = PlannedStorageTransfer(
            direction=STORAGE_TRANSFER_DEPOSIT,
            key=str(key or default_key),
            label=str(label or f"Item {safe_item_id}"),
            item_id=safe_item_id,
            quantity=safe_quantity,
            model_id=safe_model_id,
            reason=str(reason or ""),
        )
        plan.cleanup_transfers.append(transfer)
        plan.storage_transfers.append(transfer)
        plan.entries.append(
            ExecutionPlanEntry(
                action_type="deposit",
                merchant_type=MERCHANT_TYPE_STORAGE,
                label=str(label or f"Item {safe_item_id}"),
                quantity=safe_quantity,
                state=PLAN_STATE_WILL_EXECUTE if bool(storage_open) else PLAN_STATE_CONDITIONAL,
                reason=str(reason or ""),
                model_id=safe_model_id,
            )
        )

    def build_cleanup_target_transfers(
        self,
        matching_items: list["InventoryItemInfo"],
        keep_on_character: int,
    ) -> list[PlannedStorageTransfer]:
        normalized_items = [item for item in matching_items if int(item.item_id) > 0 and max(1, int(item.quantity)) > 0]
        safe_keep_count = max(0, int(keep_on_character))
        if not normalized_items:
            return []

        keep_ids, kept_quantity = self._choose_keep(normalized_items, safe_keep_count)
        remaining_keep_quantity = max(0, safe_keep_count - kept_quantity)
        transfers: list[PlannedStorageTransfer] = []
        for item in normalized_items:
            item_quantity = max(1, int(item.quantity))
            if int(item.item_id) in keep_ids:
                continue

            keep_from_item = 0
            if remaining_keep_quantity > 0:
                keep_from_item = min(item_quantity, remaining_keep_quantity)
                remaining_keep_quantity -= keep_from_item

            transfer_quantity = max(0, item_quantity - keep_from_item)
            if transfer_quantity <= 0:
                continue
            transfers.append(
                PlannedStorageTransfer(
                    direction=STORAGE_TRANSFER_DEPOSIT,
                    key=_make_model_stock_key(item.model_id),
                    label=item.name,
                    item_id=item.item_id,
                    quantity=transfer_quantity,
                    model_id=item.model_id,
                )
            )
        return transfers

    def get_effective_cleanup_targets(
        self,
        enabled_sell_rules: list[tuple[int, SellRule]] | None = None,
    ) -> list[CleanupTarget]:
        targets_by_key: dict[tuple[int, str], CleanupTarget] = {
            _cleanup_target_key(target): CleanupTarget(
                model_id=int(target.model_id),
                keep_on_character=max(0, int(target.keep_on_character)),
                scope=_normalize_cleanup_target_scope(getattr(target, "scope", ""), target.model_id),
            )
            for target in _normalize_cleanup_targets(self._targets())
        }
        if enabled_sell_rules is None:
            enabled_sell_rules = self._collect_enabled_rules()
        for _rule_index, sell_rule in enabled_sell_rules:
            if sell_rule.kind not in (SELL_KIND_COMMON_MATERIALS, SELL_KIND_EXPLICIT_MODELS):
                continue
            for whitelist_target in _normalize_whitelist_targets(getattr(sell_rule, "whitelist_targets", [])):
                if not bool(getattr(whitelist_target, "deposit_to_storage", False)):
                    continue
                safe_model_id = max(0, int(whitelist_target.model_id))
                target_scope = (
                    _infer_cleanup_target_scope_from_model_id(safe_model_id)
                    if sell_rule.kind == SELL_KIND_COMMON_MATERIALS
                    else CLEANUP_TARGET_SCOPE_EXACT
                )
                target_key = (safe_model_id, target_scope)
                if safe_model_id <= 0 or target_key in targets_by_key:
                    continue
                # Sell-rule keep counts already decide what remains after sales; cleanup deposits that remainder.
                targets_by_key[target_key] = CleanupTarget(
                    model_id=safe_model_id,
                    keep_on_character=0,
                    scope=target_scope,
                )
        return _normalize_cleanup_targets([asdict(target) for target in targets_by_key.values()])

    def get_effective_cleanup_protection_sources(
        self,
        enabled_sell_rules: list[tuple[int, SellRule]] | None = None,
    ) -> list[CleanupProtectionSource]:
        sources_by_rule_id: dict[str, CleanupProtectionSource] = {
            str(source.sell_rule_id): CleanupProtectionSource(sell_rule_id=str(source.sell_rule_id))
            for source in _normalize_cleanup_protection_sources(self._sources())
        }
        if enabled_sell_rules is None:
            enabled_sell_rules = self._collect_enabled_rules()
        for _rule_index, sell_rule in enabled_sell_rules:
            if sell_rule.kind not in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
                continue
            if not bool(getattr(sell_rule, "deposit_protected_matches", False)):
                continue
            safe_rule_id = _normalize_rule_id(getattr(sell_rule, "rule_id", ""))
            if not safe_rule_id or safe_rule_id in sources_by_rule_id:
                continue
            sources_by_rule_id[safe_rule_id] = CleanupProtectionSource(sell_rule_id=safe_rule_id)
        return _normalize_cleanup_protection_sources([asdict(source) for source in sources_by_rule_id.values()])

    def get_cleanup_blacklist_model_id_set(self) -> set[int]:
        return set(_normalize_cleanup_blacklist_model_ids(self._keep_out()))

    def cleanup_target_matches_item(self, cleanup_target: CleanupTarget, item: "InventoryItemInfo") -> bool:
        target_model_id = max(0, int(cleanup_target.model_id))
        if target_model_id <= 0 or int(item.model_id) != target_model_id or int(item.item_id) <= 0:
            return False
        target_scope = _normalize_cleanup_target_scope(getattr(cleanup_target, "scope", ""), target_model_id)
        if target_scope == CLEANUP_TARGET_SCOPE_COMMON_MATERIAL:
            return bool(item.is_material and not item.is_rare_material)
        if target_scope == CLEANUP_TARGET_SCOPE_RARE_MATERIAL:
            return bool(item.is_rare_material)
        if target_model_id in ALL_CRAFTING_MATERIAL_MODEL_IDS and bool(item.is_material or item.is_rare_material):
            return False
        return True

    def plan_cleanup_actions(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        enabled_sell_rules: list[tuple[int, SellRule]],
        *,
        storage_open: bool = False,
        storage_context_available: bool | None = None,
    ) -> None:
        """Plan bounded deposits for explicit cleanup targets and enabled protection sources.

        Storage availability and target scope determine whether entries are direct or
        conditional; protected keep-out models are never converted into transfer actions.
        """

        if storage_context_available is None:
            storage_context_available = self._storage_available()
        if not storage_context_available:
            return

        cleanup_items = list(items)
        cleanup_blacklist_model_ids = self.get_cleanup_blacklist_model_id_set()
        cleanup_targets = self.get_effective_cleanup_targets(enabled_sell_rules)
        xunlai_first_keep_by_model = self._keep_floors()
        for cleanup_target in cleanup_targets:
            target_model_id = max(0, int(cleanup_target.model_id))
            configured_keep_on_character = max(0, int(cleanup_target.keep_on_character))
            xunlai_first_keep = max(0, int(xunlai_first_keep_by_model.get(target_model_id, 0)))
            keep_on_character = max(configured_keep_on_character, xunlai_first_keep)
            xunlai_first_keep_controls = xunlai_first_keep > configured_keep_on_character
            target_label = self._target_label(cleanup_target)
            matching_items = [item for item in cleanup_items if self.cleanup_target_matches_item(cleanup_target, item)]
            if not matching_items:
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        target_label,
                        0,
                        PLAN_STATE_SKIPPED,
                        "No matching inventory items found for this deposit target.",
                        status_hint=PREVIEW_STATUS_NO_MATCH,
                    )
                )
                continue

            total_quantity = sum(max(1, int(item.quantity)) for item in matching_items)
            if target_model_id in cleanup_blacklist_model_ids:
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        target_label,
                        total_quantity,
                        PLAN_STATE_SKIPPED,
                        "Skipped by deposit keep-out.",
                        model_id=target_model_id,
                        status_hint=PREVIEW_STATUS_PROTECTED,
                    )
                )
                blacklisted_item_ids = {int(item.item_id) for item in matching_items}
                cleanup_items = [item for item in cleanup_items if int(item.item_id) not in blacklisted_item_ids]
                continue

            if total_quantity <= keep_on_character:
                keep_reason = (
                    f"Keeping {keep_on_character} on character for Check Xunlai first."
                    if xunlai_first_keep_controls
                    else (
                        f"All {total_quantity} matching items remain in inventory because "
                        f"the keep amount is {keep_on_character}."
                    )
                )
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        target_label,
                        total_quantity,
                        PLAN_STATE_SKIPPED,
                        keep_reason,
                    )
                )
                continue

            planned_transfers = self.build_cleanup_target_transfers(matching_items, keep_on_character)
            if not planned_transfers:
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        target_label,
                        total_quantity,
                        PLAN_STATE_SKIPPED,
                        "Deposit reserve left nothing eligible to move.",
                    )
                )
                continue

            for transfer in planned_transfers:
                self.append_cleanup_transfer_entry(
                    plan,
                    item_id=transfer.item_id,
                    quantity=transfer.quantity,
                    label=transfer.label,
                    model_id=transfer.model_id,
                    key=transfer.key,
                    reason=(
                        f"Keeping {keep_on_character} on character for Check Xunlai first."
                        if xunlai_first_keep_controls
                        else f"Deposit target keeps {keep_on_character} on character."
                    ),
                    storage_open=storage_open,
                )
            cleanup_items = apply_planned_transfer_quantities(cleanup_items, planned_transfers)

        cleanup_sources = self.get_effective_cleanup_protection_sources(enabled_sell_rules)
        for cleanup_source in cleanup_sources:
            sell_rule_id = _normalize_rule_id(cleanup_source.sell_rule_id)
            if not sell_rule_id:
                continue

            sell_rule_index = self.get_sell_rule_index_by_id(sell_rule_id)
            sell_rule = self.get_sell_rule_by_id(sell_rule_id)
            if sell_rule is None or sell_rule_index < 0:
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        "Linked protection rule",
                        0,
                        PLAN_STATE_SKIPPED,
                        "Linked sell rule no longer exists.",
                        status_hint=PREVIEW_STATUS_BLOCKED,
                    )
                )
                continue

            rule_reference = self._rule_reference(sell_rule_index, sell_rule)
            if sell_rule.kind not in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        rule_reference,
                        0,
                        PLAN_STATE_SKIPPED,
                        "Linked deposit sources only support weapon or armor sell protections.",
                        status_hint=PREVIEW_STATUS_BLOCKED,
                    )
                )
                continue

            if not sell_rule.enabled:
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        rule_reference,
                        0,
                        PLAN_STATE_SKIPPED,
                        "Linked sell rule is disabled.",
                    )
                )
                continue

            planned_transfers: list[PlannedStorageTransfer] = []
            blacklisted_matches_found = False
            for item in cleanup_items:
                protection_match = self._policy().get_hard_protection_match(item, enabled_sell_rules)
                if protection_match is None:
                    continue
                _, matched_rule, _, detail = protection_match
                if str(getattr(matched_rule, "rule_id", "") or "").strip() != sell_rule_id:
                    continue
                explicit_deposit = self._policy().get_equippable_explicit_deposit_reason(item, sell_rule)
                if explicit_deposit is None:
                    continue
                if int(item.model_id) in cleanup_blacklist_model_ids:
                    blacklisted_matches_found = True
                    plan.entries.append(
                        ExecutionPlanEntry(
                            "deposit",
                            MERCHANT_TYPE_STORAGE,
                            item.name,
                            item.quantity,
                            PLAN_STATE_SKIPPED,
                            f"Skipped by deposit keep-out. Protected by {rule_reference}: {detail}",
                            model_id=item.model_id,
                            status_hint=PREVIEW_STATUS_PROTECTED,
                        )
                    )
                    continue
                planned_transfers.append(
                    PlannedStorageTransfer(
                        direction=STORAGE_TRANSFER_DEPOSIT,
                        key=_make_model_stock_key(item.model_id),
                        label=item.name,
                        item_id=item.item_id,
                        quantity=item.quantity,
                        model_id=item.model_id,
                    )
                )
                self.append_cleanup_transfer_entry(
                    plan,
                    item_id=item.item_id,
                    quantity=item.quantity,
                    label=item.name,
                    model_id=item.model_id,
                    key=_make_model_stock_key(item.model_id),
                    reason=f"Protected by {rule_reference}: {detail}",
                    storage_open=storage_open,
                )

            if not planned_transfers:
                if blacklisted_matches_found:
                    continue
                plan.entries.append(
                    ExecutionPlanEntry(
                        "deposit",
                        MERCHANT_TYPE_STORAGE,
                        rule_reference,
                        0,
                        PLAN_STATE_SKIPPED,
                        "No protected inventory items matched this linked deposit source.",
                        status_hint=PREVIEW_STATUS_NO_MATCH,
                    )
                )
                continue

            cleanup_items = apply_planned_transfer_quantities(cleanup_items, planned_transfers)


# Same-valued source-kind markers; widget record definitions/defaults remain untouched.
ARMOR_UPGRADE_SOURCE_KIND = "armor"
WEAPON_UPGRADE_SOURCE_KIND = "weapon"


class SalvageCandidateView(Protocol):
    @property
    def item(self) -> "InventoryItemInfo": ...
    @property
    def rule_index(self) -> int: ...
    @property
    def rule(self) -> SalvageRule: ...
    @property
    def reason(self) -> str: ...


class SalvageUpgradeMatchView(Protocol):
    @property
    def label(self) -> str: ...
    @property
    def required_option(self) -> str: ...
    @property
    def identifier(self) -> str: ...
    @property
    def source_kind(self) -> str: ...


class SalvageSlotResolutionView(Protocol):
    @property
    def selected_option(self) -> str: ...
    @property
    def matched_labels(self) -> tuple[str, ...]: ...
    @property
    def block_reason(self) -> str: ...


class SalvageCandidateFactory[C: SalvageCandidateView](Protocol):
    def __call__(self, item: "InventoryItemInfo", rule_index: int, rule: SalvageRule, reason: str = "") -> C: ...


class SalvageUpgradeMatchFactory[M: SalvageUpgradeMatchView](Protocol):
    def __call__(
        self, label: str = "", required_option: str = "", identifier: str = "", source_kind: str = "weapon"
    ) -> M: ...


class SalvageSlotResolutionFactory[S: SalvageSlotResolutionView](Protocol):
    def __call__(
        self, selected_option: str = "", matched_labels: tuple[str, ...] = (), block_reason: str = ""
    ) -> S: ...


class PlanEntryFactory(Protocol):
    def __call__(
        self,
        action_type: str,
        merchant_type: str,
        label: str,
        quantity: int,
        state: str,
        reason: str = "",
        model_id: int = 0,
        status_hint: str = "",
    ) -> ExecutionPlanEntry: ...


class SpecificUpgradeOwnerFactory(Protocol):
    def __call__(
        self, model_id: int, rule_index: int, rule_snapshot: SalvageRule
    ) -> PlannedSpecificUpgradeSalvageOwner: ...


class DestroyActionFactory(Protocol):
    def __call__(
        self,
        item_id: int,
        model_id: int,
        label: str,
        quantity_to_destroy: int,
        source_quantity: int,
        keep_quantity: int = 0,
        requires_split: bool = False,
    ) -> PlannedDestroyAction: ...


class HardProtectionReader(Protocol):
    def __call__(
        self, item: "InventoryItemInfo", enabled_sell_rules: list[tuple[int, SellRule]]
    ) -> tuple[str, str] | None: ...


class SalvageKitReader(Protocol):
    def __call__(self, option: object, *, preferred_kit_id: int = 0, preferred_kit_model_id: int = 0) -> int: ...


class ArmorIdentityReader(Protocol):
    def __call__(self, identifier: object, *, mod_db: "ModDatabase") -> tuple["ArmorUpgradeIdentity | None", str]: ...


class ArmorSignatureReader(Protocol):
    def __call__(
        self,
        raw_modifiers: tuple[tuple[int, int, int], ...],
        identity: "ArmorUpgradeIdentity",
        *,
        require_generic_carrier: bool = False,
    ) -> bool: ...


class CompactLabeler(Protocol):
    def __call__(self, labels: list[str], limit: int = 2) -> str: ...


class EmptySlotReader(Protocol):
    def __call__(self, inventory_items: list["InventoryItemInfo"] | None = None) -> object | None: ...


class StackQuantityView(Protocol):
    @property
    def item_id(self) -> int: ...
    @property
    def quantity(self) -> int: ...


class SalvageDestroySelection(Protocol):
    def get_salvage_destroy_claim_reason(
        self, item: "InventoryItemInfo", enabled_sell_rules: list[tuple[int, SellRule]]
    ) -> str: ...


class _DestroyTargetStage(TypedDict):
    label: str
    target_keep_count: int
    matching_items: list["InventoryItemInfo"]
    protected_items: list[tuple["InventoryItemInfo", str]]
    salvage_items: list[tuple["InventoryItemInfo", str]]
    destroy_pool: list[tuple["InventoryItemInfo", str]]
    keep_quantities: dict[int, int]
    planned_actions: list[PlannedDestroyAction]
    destroy_block_reason: str
    split_keep_quantity_needed: int


@dataclass(frozen=True)
class SelectorNormalizers:
    """Late getters for existing canonical normalization aliases; no selection algorithms."""

    get_identify_settings: Callable[[], Callable[[object], IdentifySettings]]
    get_salvage_settings: Callable[[], Callable[[object], SalvageSettings]]
    get_salvage_rule: Callable[[], Callable[[object], SalvageRule | None]]
    get_destroy_rule: Callable[[], Callable[[DestroyRule], DestroyRule]]
    get_coerce_list: Callable[[], Callable[[object], list[object]]]
    get_dedupe_identifiers: Callable[[], Callable[[list[object]], list[str]]]
    get_dedupe_model_ids: Callable[[], Callable[[list[int]], list[int]]]
    get_thresholds: Callable[[], Callable[[list[object]], list[WeaponModThresholdRule]]]
    get_variants: Callable[[], Callable[[list[object]], list[WeaponModVariantRule]]]
    get_variant_thresholds: Callable[[], Callable[[list[object]], list[WeaponModVariantThresholdRule]]]
    get_common_materials: Callable[[], Callable[[object], list[int]]]
    get_rarity_flags: Callable[[], Callable[[object], dict[str, bool]]]
    get_category_flags: Callable[[], Callable[[object], dict[str, bool]]]
    get_whitelist_targets: Callable[[], Callable[[object], list[WhitelistTarget]]]
    get_rarity_key: Callable[[], Callable[[str], str]]


def get_salvage_rule_upgrade_target_count(rule: object, *, normalizers: SelectorNormalizers) -> int:
    target_armor_identifiers = normalizers.get_dedupe_identifiers()(
        normalizers.get_coerce_list()(getattr(rule, "target_armor_upgrade_identifiers", []))
    )
    target_identifiers = normalizers.get_dedupe_identifiers()(
        normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_identifiers", []))
    )
    target_thresholds = normalizers.get_thresholds()(
        normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_thresholds", []))
    )
    target_variants = normalizers.get_variants()(
        normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_variants", []))
    )
    target_variant_thresholds = normalizers.get_variant_thresholds()(
        normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_variant_thresholds", []))
    )
    return (
        len(target_armor_identifiers)
        + len(target_identifiers)
        + len(target_thresholds)
        + len(target_variants)
        + len(target_variant_thresholds)
    )


def salvage_rule_has_armor_upgrade_targets(rule: object, *, normalizers: SelectorNormalizers) -> bool:
    return bool(
        normalizers.get_dedupe_identifiers()(
            normalizers.get_coerce_list()(getattr(rule, "target_armor_upgrade_identifiers", []))
        )
    )


def salvage_rule_has_weapon_upgrade_targets(rule: object, *, normalizers: SelectorNormalizers) -> bool:
    return bool(
        normalizers.get_dedupe_identifiers()(
            normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_identifiers", []))
        )
        or normalizers.get_thresholds()(
            normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_thresholds", []))
        )
        or normalizers.get_variants()(normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_variants", [])))
        or normalizers.get_variant_thresholds()(
            normalizers.get_coerce_list()(getattr(rule, "target_weapon_mod_variant_thresholds", []))
        )
    )


def salvage_rule_has_upgrade_targets(rule: object, *, normalizers: SelectorNormalizers) -> bool:
    return get_salvage_rule_upgrade_target_count(rule, normalizers=normalizers) > 0


def salvage_rule_has_selectors(rule: SalvageRule, *, normalizers: SelectorNormalizers) -> bool:
    return bool(
        normalizers.get_dedupe_model_ids()(getattr(rule, "model_ids", []))
        or (
            _resolve_salvage_operation(getattr(rule, "salvage_option", SALVAGE_OPTION_DEFAULT))
            == SALVAGE_OPTION_MATERIALS
            and normalizers.get_common_materials()(getattr(rule, "target_common_material_model_ids", []))
        )
        or any(bool(value) for value in normalizers.get_rarity_flags()(getattr(rule, "rarities", {})).values())
        or any(bool(value) for value in normalizers.get_category_flags()(getattr(rule, "categories", {})).values())
        or salvage_rule_has_upgrade_targets(rule, normalizers=normalizers)
    )


class IdentifyPlanner:
    """Own supplied-evidence selection/allocation without runtime authority."""

    def __init__(
        self,
        *,
        normalizers: SelectorNormalizers,
        read_settings: Callable[[], IdentifySettings],
        get_id_kit: Callable[[], Callable[[], int]],
        read_rarity_order: Callable[[], tuple[tuple[str, str], ...]],
        get_entry_factory: Callable[[], PlanEntryFactory],
    ) -> None:
        self._normalizers = normalizers
        self._read_settings = read_settings
        self._get_id_kit = get_id_kit
        self._read_rarity_order = read_rarity_order
        self._get_entry_factory = get_entry_factory

    def has_enabled_identify_settings(self) -> bool:
        settings = self._normalizers.get_identify_settings()(self._read_settings())
        return any(bool(value) for value in settings.rarities.values())

    def should_identify_before_execute(self) -> bool:
        settings = self._normalizers.get_identify_settings()(self._read_settings())
        return bool(settings.before_execute and any(bool(value) for value in settings.rarities.values()))

    def get_identify_selection_reason(self, item: "InventoryItemInfo") -> str:
        if bool(item.identified):
            return ""
        settings = self._normalizers.get_identify_settings()(self._read_settings())
        rarity_key = self._normalizers.get_rarity_key()(str(item.rarity or ""))
        if not bool(settings.rarities.get(rarity_key, False)):
            return ""
        rarity_label = next(
            (label for key, label in self._read_rarity_order() if key == rarity_key),
            str(item.rarity or rarity_key).strip() or rarity_key,
        )
        return f"selected exact rarity {rarity_label}"

    def collect_identify_candidates(self, items: list["InventoryItemInfo"]) -> list["InventoryItemInfo"]:
        candidates: list["InventoryItemInfo"] = []
        for item in items:
            if int(item.item_id) <= 0:
                continue
            if not self.get_identify_selection_reason(item):
                continue
            candidates.append(item)
        return candidates

    def plan_identify_actions(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        claimed_item_ids: set[int],
    ) -> None:
        """Claim and preview identification targets before destructive or sale planning."""

        if not self.should_identify_before_execute():
            return

        candidates = self.collect_identify_candidates(items)
        if not candidates:
            plan.entries.append(
                self._get_entry_factory()(
                    "identify",
                    MERCHANT_TYPE_INVENTORY,
                    "Identify selected rarities",
                    0,
                    PLAN_STATE_SKIPPED,
                    "No unidentified items found for the selected exact rarities.",
                    status_hint=PREVIEW_STATUS_NO_MATCH,
                )
            )
            return

        id_kit_id = self._get_id_kit()()
        for item in candidates:
            claimed_item_ids.add(int(item.item_id))
            plan.identify_claimed_item_ids.append(int(item.item_id))
            reason = self.get_identify_selection_reason(item)
            if id_kit_id <= 0:
                plan.entries.append(
                    self._get_entry_factory()(
                        "identify",
                        MERCHANT_TYPE_INVENTORY,
                        item.name,
                        item.quantity,
                        PLAN_STATE_SKIPPED,
                        "No ID kit found.",
                        model_id=item.model_id,
                        status_hint=PREVIEW_STATUS_BLOCKED,
                    )
                )
                continue

            plan.identify_item_ids.append(int(item.item_id))
            plan.entries.append(
                self._get_entry_factory()(
                    "identify",
                    MERCHANT_TYPE_INVENTORY,
                    item.name,
                    item.quantity,
                    PLAN_STATE_WILL_EXECUTE,
                    reason,
                    model_id=item.model_id,
                )
            )


class SalvagePlanner[C: SalvageCandidateView, M: SalvageUpgradeMatchView, S: SalvageSlotResolutionView]:
    """Own supplied-evidence selection/allocation without runtime authority."""

    def __init__(
        self,
        *,
        normalizers: SelectorNormalizers,
        read_settings: Callable[[], SalvageSettings],
        read_mod_db: Callable[[], "ModDatabase"],
        read_weapon_mod_names: Callable[[], Mapping[str, str]],
        read_common_outputs: Callable[[], Mapping[tuple[int, int], tuple[int, ...]]],
        get_mod_type: Callable[[], Callable[[object], str]],
        get_armor_identity: Callable[[], ArmorIdentityReader],
        get_armor_signature: Callable[[], ArmorSignatureReader],
        read_rune_mod_type: Callable[[], int],
        read_alt_minor_vigor: Callable[[], tuple[int, int, int]],
        read_category_order: Callable[[], tuple[tuple[str, str], ...]],
        read_backend_unavailable_reason: Callable[[], str],
        get_hard_protection: Callable[[], HardProtectionReader],
        get_kit: Callable[[], SalvageKitReader],
        get_armor_support: Callable[[], Callable[[], tuple[bool, str]]],
        get_weapon_support: Callable[[], Callable[[], tuple[bool, str]]],
        get_model_label: Callable[[], Callable[[int], str]],
        get_model_name: Callable[[], Callable[[int], str]],
        get_generic_mod_label: Callable[[], Callable[[str], str]],
        get_threshold_label: Callable[[], Callable[[WeaponModThresholdRule], str]],
        get_variant_label: Callable[[], Callable[[object], str]],
        get_variant_threshold_label: Callable[[], Callable[[WeaponModVariantThresholdRule], str]],
        get_compact_labels: Callable[[], CompactLabeler],
        get_rule_reference: Callable[[], Callable[[int, SalvageRule], str]],
        get_item_label: Callable[[], Callable[["InventoryItemInfo"], str]],
        get_diagnostic: Callable[[], Callable[[str], None]],
        get_variant_match: Callable[[], Callable[[object, object], bool]],
        get_candidate_factory: Callable[[], SalvageCandidateFactory[C]],
        get_match_factory: Callable[[], SalvageUpgradeMatchFactory[M]],
        get_slot_factory: Callable[[], SalvageSlotResolutionFactory[S]],
        get_entry_factory: Callable[[], PlanEntryFactory],
        get_owner_factory: Callable[[], SpecificUpgradeOwnerFactory],
    ) -> None:
        self._normalizers = normalizers
        self._read_settings = read_settings
        self._read_mod_db = read_mod_db
        self._read_weapon_mod_names = read_weapon_mod_names
        self._read_common_outputs = read_common_outputs
        self._get_mod_type = get_mod_type
        self._get_armor_identity = get_armor_identity
        self._get_armor_signature = get_armor_signature
        self._read_rune_mod_type = read_rune_mod_type
        self._read_alt_minor_vigor = read_alt_minor_vigor
        self._read_category_order = read_category_order
        self._read_backend_unavailable_reason = read_backend_unavailable_reason
        self._get_hard_protection = get_hard_protection
        self._get_kit = get_kit
        self._get_armor_support = get_armor_support
        self._get_weapon_support = get_weapon_support
        self._get_model_label = get_model_label
        self._get_model_name = get_model_name
        self._get_generic_mod_label = get_generic_mod_label
        self._get_threshold_label = get_threshold_label
        self._get_variant_label = get_variant_label
        self._get_variant_threshold_label = get_variant_threshold_label
        self._get_compact_labels = get_compact_labels
        self._get_rule_reference = get_rule_reference
        self._get_item_label = get_item_label
        self._get_diagnostic = get_diagnostic
        self._get_variant_match = get_variant_match
        self._get_candidate_factory = get_candidate_factory
        self._get_match_factory = get_match_factory
        self._get_slot_factory = get_slot_factory
        self._get_entry_factory = get_entry_factory
        self._get_owner_factory = get_owner_factory

    def has_enabled_salvage_settings(self) -> bool:
        settings = self._normalizers.get_salvage_settings()(self._read_settings())
        return any(
            bool(rule.enabled) and salvage_rule_has_selectors(rule, normalizers=self._normalizers)
            for rule in settings.rules
        )

    def get_salvage_category_key_for_item(self, item: "InventoryItemInfo") -> str:
        if bool(item.is_weapon_like):
            return SALVAGE_CATEGORY_WEAPONS
        if bool(item.is_armor_piece):
            return SALVAGE_CATEGORY_ARMOR
        if bool(item.is_material):
            return SALVAGE_CATEGORY_MATERIALS
        return SALVAGE_CATEGORY_OTHER

    def get_salvage_category_label(self, category_key: object) -> str:
        safe_key = str(category_key or "").strip()
        for key, label in self._read_category_order():
            if key == safe_key:
                return label
        return safe_key or "Unknown"

    def get_weapon_mod_required_salvage_option(
        self,
        identifier: object,
        match: object | None = None,
    ) -> str:
        safe_identifier = str(identifier or "").strip()
        if not safe_identifier:
            return ""

        weapon_mod = self._read_mod_db().weapon_mods.get(safe_identifier)
        weapon_mod_name = str(
            getattr(weapon_mod, "name", "") or self._read_weapon_mod_names().get(safe_identifier, "") or safe_identifier
        ).strip()
        if weapon_mod_name.startswith('"'):
            return SALVAGE_OPTION_INSCRIPTION

        mod_type = str(getattr(match, "mod_type", "") or "").strip()
        if not mod_type:
            mod_type = self._get_mod_type()(weapon_mod)
        normalized_mod_type = mod_type.casefold()
        if normalized_mod_type == "prefix":
            return SALVAGE_OPTION_PREFIX
        if normalized_mod_type == "suffix":
            return SALVAGE_OPTION_SUFFIX
        return ""

    def build_salvage_upgrade_target_match(
        self,
        label: object,
        identifier: object,
        match: object | None,
        *,
        source_kind: str = WEAPON_UPGRADE_SOURCE_KIND,
        required_option: str = "",
    ) -> M:
        safe_identifier = str(identifier or "").strip()
        safe_label = str(label or "").strip() or self._get_generic_mod_label()(safe_identifier)
        return self._get_match_factory()(
            label=safe_label,
            required_option=(
                str(required_option or "").strip()
                if str(required_option or "").strip()
                else self.get_weapon_mod_required_salvage_option(safe_identifier, match)
            ),
            identifier=safe_identifier,
            source_kind=str(source_kind or WEAPON_UPGRADE_SOURCE_KIND),
        )

    def get_salvage_rule_upgrade_target_matches(
        self,
        rule: SalvageRule,
        item: "InventoryItemInfo",
    ) -> list[M]:
        normalized_rule = self._normalizers.get_salvage_rule()(rule)
        if normalized_rule is None or not salvage_rule_has_upgrade_targets(
            normalized_rule, normalizers=self._normalizers
        ):
            return []

        target_matches: list[M] = []
        seen_matches: set[tuple[str, str, str, str]] = set()
        item_weapon_mod_identifiers = set(
            self._normalizers.get_dedupe_identifiers()(getattr(item, "weapon_mod_identifiers", []))
        )
        item_weapon_mod_matches = tuple(getattr(item, "weapon_mod_matches", []) or ())

        def append_match(
            label: object,
            identifier: object,
            match: object | None,
            *,
            source_kind: str = WEAPON_UPGRADE_SOURCE_KIND,
            required_option: str = "",
        ) -> None:
            target_match = self.build_salvage_upgrade_target_match(
                label,
                identifier,
                match,
                source_kind=source_kind,
                required_option=required_option,
            )
            match_key = (
                target_match.source_kind,
                target_match.identifier,
                target_match.label,
                target_match.required_option,
            )
            if match_key in seen_matches:
                return
            seen_matches.add(match_key)
            target_matches.append(target_match)

        if not bool(getattr(item, "is_armor_piece", False)):
            for identifier in normalized_rule.target_weapon_mod_identifiers:
                if identifier not in item_weapon_mod_identifiers:
                    continue
                parsed_matches = [
                    match
                    for match in item_weapon_mod_matches
                    if str(getattr(match, "identifier", "") or "").strip() == identifier
                ]
                if parsed_matches:
                    for match in parsed_matches:
                        append_match(self._get_generic_mod_label()(identifier), identifier, match)
                else:
                    append_match(self._get_generic_mod_label()(identifier), identifier, None)

            for threshold_rule in normalized_rule.target_weapon_mod_thresholds:
                threshold_identifier = str(threshold_rule.identifier or "").strip()
                if not threshold_identifier:
                    continue
                for match in item_weapon_mod_matches:
                    if str(getattr(match, "identifier", "") or "").strip() != threshold_identifier:
                        continue
                    matched_value = getattr(match, "value", None)
                    if matched_value is None:
                        continue
                    if _safe_int(matched_value, 0) >= int(threshold_rule.min_value):
                        append_match(
                            self._get_threshold_label()(threshold_rule),
                            threshold_identifier,
                            match,
                        )
                        break

            for variant_rule in normalized_rule.target_weapon_mod_variants:
                for match in item_weapon_mod_matches:
                    if self._get_variant_match()(variant_rule, match):
                        append_match(
                            self._get_variant_label()(variant_rule),
                            getattr(variant_rule, "identifier", ""),
                            match,
                        )
                        break

            for threshold_rule in normalized_rule.target_weapon_mod_variant_thresholds:
                for match in item_weapon_mod_matches:
                    if not self._get_variant_match()(threshold_rule, match):
                        continue
                    matched_value = getattr(match, "value", None)
                    if matched_value is None:
                        continue
                    if _safe_int(matched_value, 0) >= int(threshold_rule.min_value):
                        append_match(
                            self._get_variant_threshold_label()(threshold_rule),
                            getattr(threshold_rule, "identifier", ""),
                            match,
                        )
                        break

        if bool(getattr(item, "is_armor_piece", False)) and int(getattr(item, "item_type_id", 0)) != int(
            self._read_rune_mod_type()
        ):
            raw_modifiers = tuple(getattr(item, "raw_modifiers", ()) or ())
            for identifier in normalized_rule.target_armor_upgrade_identifiers:
                identity, _identity_error = self._get_armor_identity()(identifier, mod_db=self._read_mod_db())
                if identity is None:
                    continue
                target_signature_present = self._get_armor_signature()(
                    raw_modifiers,
                    identity,
                    require_generic_carrier=True,
                )
                alternate_minor_vigor_present = bool(
                    identity.signature == ((9224, 0, 0x00FF),) and self._read_alt_minor_vigor() in raw_modifiers
                )
                if not target_signature_present and not alternate_minor_vigor_present:
                    continue
                append_match(
                    identity.name,
                    identity.identifier,
                    identity,
                    source_kind=ARMOR_UPGRADE_SOURCE_KIND,
                    required_option=identity.option,
                )

        return target_matches

    def get_salvage_rule_armor_upgrade_target_matches(
        self,
        rule: SalvageRule,
        item: "InventoryItemInfo",
    ) -> list[M]:
        return [
            target_match
            for target_match in self.get_salvage_rule_upgrade_target_matches(rule, item)
            if target_match.source_kind == ARMOR_UPGRADE_SOURCE_KIND
        ]

    def get_salvage_rule_upgrade_target_reason(self, rule: SalvageRule, item: "InventoryItemInfo") -> str:
        target_matches = self.get_salvage_rule_upgrade_target_matches(rule, item)
        if not target_matches:
            return ""
        labels = self._normalizers.get_dedupe_identifiers()([target_match.label for target_match in target_matches])
        return f"specific upgrade target {self._get_compact_labels()(labels, limit=3)}"

    def get_auto_salvage_upgrade_slot_resolution(
        self,
        rule: SalvageRule,
        item: "InventoryItemInfo",
    ) -> S:
        target_matches = self.get_salvage_rule_upgrade_target_matches(rule, item)
        matched_labels = tuple(
            self._normalizers.get_dedupe_identifiers()([target_match.label for target_match in target_matches])
        )
        if not target_matches:
            return self._get_slot_factory()(
                matched_labels=matched_labels,
                block_reason="specific upgrade salvage requires a matching specific upgrade target",
            )

        unknown_option_labels = [
            target_match.label for target_match in target_matches if not str(target_match.required_option or "").strip()
        ]
        if unknown_option_labels:
            return self._get_slot_factory()(
                matched_labels=matched_labels,
                block_reason=(
                    "specific upgrade salvage cannot infer slot for target: "
                    f"{self._get_compact_labels()(self._normalizers.get_dedupe_identifiers()(unknown_option_labels), limit=3)}"
                ),
            )

        required_options = sorted(
            {
                str(target_match.required_option or "").strip()
                for target_match in target_matches
                if str(target_match.required_option or "").strip()
            }
        )
        if len(required_options) != 1:
            required_option_labels = [
                _get_salvage_option_label(required_option) for required_option in required_options
            ]
            return self._get_slot_factory()(
                matched_labels=matched_labels,
                block_reason=(
                    "specific upgrade salvage ambiguous: matched targets require "
                    f"{self._get_compact_labels()(required_option_labels, limit=3)}"
                ),
            )

        inferred_option = required_options[0]
        if inferred_option not in SALVAGE_UPGRADE_OPTIONS:
            return self._get_slot_factory()(
                matched_labels=matched_labels,
                block_reason=(
                    "specific upgrade salvage cannot infer slot for target: "
                    f"{self._get_compact_labels()(matched_labels, limit=3)}"
                ),
            )
        return self._get_slot_factory()(selected_option=inferred_option, matched_labels=matched_labels)

    def get_salvage_upgrade_target_option_block_reason(
        self,
        rule: SalvageRule,
        item: "InventoryItemInfo",
        selected_option: object,
    ) -> str:
        armor_target_matches = self.get_salvage_rule_armor_upgrade_target_matches(rule, item)
        if len(armor_target_matches) > 1:
            return (
                "specific upgrade salvage ambiguous: one rule matched both installed armor upgrades "
                f"({self._get_compact_labels()([match.label for match in armor_target_matches], limit=3)})"
            )
        if _is_auto_exact_upgrade_salvage_option(selected_option):
            return self.get_auto_salvage_upgrade_slot_resolution(rule, item).block_reason

        target_matches = self.get_salvage_rule_upgrade_target_matches(rule, item)
        if not target_matches:
            return ""

        unknown_option_labels = [
            target_match.label for target_match in target_matches if not str(target_match.required_option or "").strip()
        ]
        if unknown_option_labels:
            return (
                "specific upgrade target option unknown: "
                f"{self._get_compact_labels()(self._normalizers.get_dedupe_identifiers()(unknown_option_labels), limit=3)}"
            )

        safe_selected_option = _resolve_salvage_operation(selected_option)
        if safe_selected_option not in SALVAGE_UPGRADE_OPTIONS:
            return "specific upgrade target requires prefix, suffix, or inscription salvage option"

        required_options = {
            str(target_match.required_option or "").strip()
            for target_match in target_matches
            if str(target_match.required_option or "").strip()
        }
        if safe_selected_option in required_options:
            return ""

        required_option_labels = [
            _get_salvage_option_label(required_option) for required_option in sorted(required_options)
        ]
        return (
            f"specific upgrade target requires {self._get_compact_labels()(required_option_labels, limit=3)}; "
            f"rule is configured for {_get_salvage_option_label(safe_selected_option)}"
        )

    def get_common_material_target_match(
        self,
        rule: SalvageRule,
        item: "InventoryItemInfo",
    ) -> tuple[bool, str]:
        target_model_ids = self._normalizers.get_common_materials()(
            getattr(rule, "target_common_material_model_ids", [])
        )
        if not target_model_ids:
            return True, ""
        if (
            _resolve_salvage_operation(getattr(rule, "salvage_option", SALVAGE_OPTION_DEFAULT))
            != SALVAGE_OPTION_MATERIALS
        ):
            return True, ""

        item_key = (
            max(0, _safe_int(getattr(item, "item_type_id", 0), 0)),
            max(0, _safe_int(getattr(item, "model_id", 0), 0)),
        )
        possible_outputs = self._read_common_outputs().get(item_key)
        if not possible_outputs:
            return False, "Skipped: salvage output data unavailable"

        possible_output_ids = set(int(model_id) for model_id in possible_outputs)
        matched_model_ids = [model_id for model_id in target_model_ids if model_id in possible_output_ids]
        if not matched_model_ids:
            return False, ""

        labels = [self._get_model_name()(model_id) or f"Model {model_id}" for model_id in matched_model_ids]
        return True, f"Known possible common salvage: {self._get_compact_labels()(labels, limit=3)}"

    def get_salvage_rule_filter_reason(self, rule: SalvageRule, item: "InventoryItemInfo") -> str:
        normalized_rule = self._normalizers.get_salvage_rule()(rule)
        if normalized_rule is None or not bool(normalized_rule.enabled):
            return ""

        is_targeted_specific_upgrade = _is_auto_exact_upgrade_salvage_option(
            normalized_rule.salvage_option
        ) and salvage_rule_has_upgrade_targets(normalized_rule, normalizers=self._normalizers)
        targeted_specific_upgrade_reason = (
            self.get_salvage_rule_upgrade_target_reason(normalized_rule, item) if is_targeted_specific_upgrade else ""
        )
        if is_targeted_specific_upgrade and not targeted_specific_upgrade_reason:
            return ""

        rarity_filter_active = any(bool(value) for value in normalized_rule.rarities.values())
        category_filter_active = any(bool(value) for value in normalized_rule.categories.values())
        normal_selector_active = bool(normalized_rule.model_ids) or rarity_filter_active or category_filter_active
        model_matches = int(item.model_id) in set(int(model_id) for model_id in normalized_rule.model_ids)

        base_reason = ""
        if model_matches:
            base_reason = f"selected model {self._get_model_label()(int(item.model_id))}"
        else:
            upgrade_target_reason = ""
            if not is_targeted_specific_upgrade:
                upgrade_target_reason = self.get_salvage_rule_upgrade_target_reason(normalized_rule, item)
            if upgrade_target_reason:
                base_reason = upgrade_target_reason
            else:
                rarity_key = self._normalizers.get_rarity_key()(str(item.rarity or ""))
                category_key = self.get_salvage_category_key_for_item(item)
                rarity_matches = bool(normalized_rule.rarities.get(rarity_key, False))
                category_matches = bool(normalized_rule.categories.get(category_key, False))
                if rarity_filter_active and not rarity_matches:
                    return ""
                if category_filter_active and not category_matches:
                    return ""
                if rarity_filter_active or category_filter_active:
                    reason_parts: list[str] = []
                    if rarity_filter_active:
                        reason_parts.append(f"rarity {str(item.rarity or rarity_key).strip() or rarity_key}")
                    if category_filter_active:
                        reason_parts.append(f"category {self.get_salvage_category_label(category_key)}")
                    base_reason = f"selected {' and '.join(reason_parts)}"

        if is_targeted_specific_upgrade:
            if not base_reason and normal_selector_active:
                return ""
            if not model_matches:
                base_reason = targeted_specific_upgrade_reason

        target_model_ids = self._normalizers.get_common_materials()(
            getattr(normalized_rule, "target_common_material_model_ids", [])
        )
        if target_model_ids and _resolve_salvage_operation(normalized_rule.salvage_option) == SALVAGE_OPTION_MATERIALS:
            if not base_reason:
                base_reason = "selected common material output"
            target_matches, target_reason = self.get_common_material_target_match(normalized_rule, item)
            if not target_matches:
                return ""
            if target_reason:
                return f"{base_reason}; {target_reason}"

        return base_reason

    def collect_enabled_salvage_rules(self) -> list[tuple[int, SalvageRule]]:
        settings = self._normalizers.get_salvage_settings()(self._read_settings())
        enabled_rules: list[tuple[int, SalvageRule]] = []
        for rule_index, raw_rule in enumerate(settings.rules):
            rule = self._normalizers.get_salvage_rule()(raw_rule)
            if rule is None or not bool(rule.enabled):
                continue
            if not salvage_rule_has_selectors(rule, normalizers=self._normalizers):
                continue
            enabled_rules.append((rule_index, rule))
        return enabled_rules

    def get_matching_salvage_rule(self, item: "InventoryItemInfo") -> tuple[int, SalvageRule, str] | None:
        for rule_index, rule in self.collect_enabled_salvage_rules():
            reason = self.get_salvage_rule_filter_reason(rule, item)
            if reason:
                return rule_index, rule, reason
        return None

    def get_planned_specific_upgrade_salvage_rule(
        self,
        owner: PlannedSpecificUpgradeSalvageOwner,
    ) -> tuple[int, SalvageRule] | None:
        """Resolve only the rule identity retained by the final live Execute plan."""

        expected_rule = self._normalizers.get_salvage_rule()(owner.rule_snapshot)
        expected_rule_index = int(owner.rule_index)
        if (
            expected_rule is None
            or expected_rule_index < 0
            or not _is_auto_exact_upgrade_salvage_option(expected_rule.salvage_option)
            or not salvage_rule_has_upgrade_targets(expected_rule, normalizers=self._normalizers)
        ):
            return None

        for current_rule_index, current_rule in self.collect_enabled_salvage_rules():
            if int(current_rule_index) != expected_rule_index:
                continue
            if self._normalizers.get_salvage_rule()(current_rule) != expected_rule:
                return None
            return int(current_rule_index), current_rule
        return None

    def get_salvage_selection_reason(self, item: "InventoryItemInfo") -> str:
        match = self.get_matching_salvage_rule(item)
        if match is None:
            return ""
        rule_index, rule, reason = match
        option_label = _get_salvage_option_label(rule.salvage_option)
        return f"{reason}; {option_label} via {self._get_rule_reference()(rule_index, rule)}"

    def get_specific_upgrade_salvage_reservation_reason(self, item: "InventoryItemInfo") -> str:
        """Reserve a first-rule Specific Upgrade match even when extraction must fail closed."""

        match = self.get_matching_salvage_rule(item)
        if match is None:
            return ""
        rule_index, rule, reason = match
        if not self.get_salvage_rule_upgrade_target_matches(rule, item):
            return ""
        option_label = _get_salvage_option_label(rule.salvage_option)
        return f"{reason}; {option_label} via {self._get_rule_reference()(rule_index, rule)}"

    def get_salvage_candidate_block_reason(
        self,
        item: "InventoryItemInfo",
        enabled_sell_rules: list[tuple[int, SellRule]],
        *,
        salvage_rule: SalvageRule | None = None,
        require_salvage_kit: bool = False,
        salvage_kit_id: int = 0,
        mode: str = "manual",
    ) -> str:
        """Return the first safety or capability reason that forbids salvaging an item.

        Hard protections, customization, identification state, kit suitability, exact-slot
        capability, and rule-option compatibility are evaluated before execution can claim it.
        """

        hard_protection = self._get_hard_protection()(item, enabled_sell_rules)
        if hard_protection is not None:
            return f"protected: {hard_protection[1]}"
        if not bool(item.salvageable):
            return "unsalvageable: the game says this item is not salvageable"
        if bool(item.is_customized):
            return "customized: customized items are never salvaged"
        rarity_key = self._normalizers.get_rarity_key()(str(item.rarity or ""))
        if not bool(item.identified) and rarity_key != "white":
            return "unidentified non-white: identify before salvaging"
        selected_rule = salvage_rule
        if selected_rule is not None:
            selection_reason = self.get_salvage_rule_filter_reason(selected_rule, item)
        else:
            rule_match = self.get_matching_salvage_rule(item)
            selected_rule = rule_match[1] if rule_match is not None else None
            selection_reason = rule_match[2] if rule_match is not None else ""
        if not selection_reason:
            return "not selected by salvage settings"
        raw_selected_option = _normalize_salvage_rule_mode(
            getattr(selected_rule, "salvage_option", SALVAGE_OPTION_DEFAULT)
        )
        armor_target_matches = (
            self.get_salvage_rule_armor_upgrade_target_matches(selected_rule, item) if selected_rule is not None else []
        )
        if armor_target_matches:
            armor_parse_error = str(getattr(item, "armor_upgrade_parse_error", "") or "").strip()
            if armor_parse_error:
                return f"armor specific upgrade identity invalid: {armor_parse_error}"
        if (
            selected_rule is not None
            and _is_auto_exact_upgrade_salvage_option(raw_selected_option)
            and not self.get_salvage_rule_upgrade_target_matches(selected_rule, item)
        ):
            return "specific upgrade salvage requires a matching specific upgrade target"
        if require_salvage_kit:
            selected_option = _resolve_salvage_operation(raw_selected_option)
            if selected_rule is not None:
                option_block_reason = self.get_salvage_upgrade_target_option_block_reason(
                    selected_rule,
                    item,
                    selected_option,
                )
                if option_block_reason:
                    return option_block_reason
                if _is_auto_exact_upgrade_salvage_option(selected_option):
                    selected_option = self.get_auto_salvage_upgrade_slot_resolution(
                        selected_rule,
                        item,
                    ).selected_option
            if selected_option in SALVAGE_UPGRADE_OPTIONS:
                if armor_target_matches:
                    upgrade_supported, support_reason = self._get_armor_support()()
                else:
                    upgrade_supported, support_reason = self._get_weapon_support()()
                if not upgrade_supported:
                    return support_reason or self._read_backend_unavailable_reason()
            if int(salvage_kit_id) <= 0:
                if selected_option in SALVAGE_UPGRADE_OPTIONS:
                    return "no upgrade salvage kit"
                return "no normal salvage kit"
        if str(mode or "").strip().lower() == "auto" and not bool(
            self._normalizers.get_salvage_settings()(self._read_settings()).on_inventory_change
        ):
            return "immediate salvage is disabled"
        return ""

    def get_salvage_destroy_claim_reason(
        self,
        item: "InventoryItemInfo",
        enabled_sell_rules: list[tuple[int, SellRule]],
    ) -> str:
        specific_upgrade_reservation = self.get_specific_upgrade_salvage_reservation_reason(item)
        if specific_upgrade_reservation:
            return specific_upgrade_reservation
        block_reason = self.get_salvage_candidate_block_reason(
            item,
            enabled_sell_rules,
            require_salvage_kit=False,
            mode="manual",
        )
        if block_reason:
            return ""
        return self.get_salvage_selection_reason(item)

    def get_salvage_block_bucket(self, reason: str) -> str:
        safe_reason = str(reason or "").strip()
        if not safe_reason:
            return ""
        lowered = safe_reason.lower()
        for prefix, label in (
            ("protected:", "protected"),
            ("unsalvageable:", "unsalvageable"),
            ("customized:", "customized"),
            ("unidentified non-white:", "unidentified non-white"),
            ("exact-upgrade salvage disabled:", "exact-upgrade salvage disabled"),
            ("upgrade salvage backend unavailable:", "upgrade salvage backend unavailable"),
            ("specific upgrade salvage requires", "specific upgrade salvage not executable"),
            ("specific upgrade salvage cannot infer", "specific upgrade salvage not executable"),
            ("specific upgrade salvage ambiguous", "specific upgrade salvage not executable"),
            ("armor specific upgrade identity invalid:", "armor specific upgrade identity invalid"),
            ("specific upgrade target option unknown:", "specific upgrade target option unknown"),
            ("specific upgrade target requires", "specific upgrade target not executable"),
            ("no normal salvage kit", "no normal salvage kit"),
            ("no upgrade salvage kit", "no upgrade salvage kit"),
            ("salvage option unavailable", "option unavailable"),
            ("salvage popup mismatch", "popup mismatch"),
            ("not selected", "not selected"),
            ("immediate salvage is disabled", "immediate disabled"),
        ):
            if lowered.startswith(prefix):
                return label
        return safe_reason

    def collect_salvage_candidates(
        self,
        items: list["InventoryItemInfo"],
        enabled_sell_rules: list[tuple[int, SellRule]],
        *,
        require_salvage_kit: bool = False,
        mode: str = "manual",
        preferred_salvage_kit_id: int = 0,
        preferred_salvage_kit_model_id: int = 0,
        include_not_selected_blocks: bool = False,
        manual_salvage_rule: SalvageRule | None = None,
        planned_specific_upgrade_owners: dict[int, PlannedSpecificUpgradeSalvageOwner] | None = None,
    ) -> tuple[list[C], dict[str, int]]:
        """Select salvage candidates by rule precedence and bucket every blocked reason."""

        candidates: list[C] = []
        blocked_counts: dict[str, int] = {}
        explicit_rule = (
            self._normalizers.get_salvage_rule()(manual_salvage_rule) if manual_salvage_rule is not None else None
        )
        for item in items:
            rule_index = -1
            salvage_rule: SalvageRule | None = None
            selection_reason = ""
            planned_owner = (
                planned_specific_upgrade_owners.get(int(item.item_id))
                if explicit_rule is None and planned_specific_upgrade_owners is not None
                else None
            )
            if planned_owner is not None:
                if int(item.model_id) != int(planned_owner.model_id):
                    owner_block_reason = "planned Specific upgrade item identity changed before execution"
                    blocked_counts[owner_block_reason] = blocked_counts.get(owner_block_reason, 0) + 1
                    self._get_diagnostic()(
                        f"MR Salvage skipped {self._get_item_label()(item)} ({item.item_id}): " f"{owner_block_reason}."
                    )
                    continue
                planned_rule_match = self.get_planned_specific_upgrade_salvage_rule(planned_owner)
                if planned_rule_match is None:
                    owner_block_reason = "planned Specific upgrade owner changed before execution"
                    blocked_counts[owner_block_reason] = blocked_counts.get(owner_block_reason, 0) + 1
                    self._get_diagnostic()(
                        f"MR Salvage skipped {self._get_item_label()(item)} ({item.item_id}): " f"{owner_block_reason}."
                    )
                    continue
                rule_index, salvage_rule = planned_rule_match
                selection_reason = self.get_salvage_rule_filter_reason(salvage_rule, item)
                if not selection_reason:
                    owner_block_reason = self.get_salvage_candidate_block_reason(
                        item,
                        enabled_sell_rules,
                        salvage_rule=salvage_rule,
                        require_salvage_kit=False,
                        mode=mode,
                    )
                    if owner_block_reason in {"", "not selected by salvage settings"}:
                        owner_block_reason = "planned Specific upgrade owner no longer matches"
                    bucket = self.get_salvage_block_bucket(owner_block_reason) or owner_block_reason
                    blocked_counts[bucket] = blocked_counts.get(bucket, 0) + 1
                    self._get_diagnostic()(
                        f"MR Salvage skipped {self._get_item_label()(item)} ({item.item_id}): " f"{owner_block_reason}."
                    )
                    continue
            elif explicit_rule is not None:
                explicit_reason = self.get_salvage_rule_filter_reason(explicit_rule, item)
                if explicit_reason:
                    salvage_rule = explicit_rule
                    selection_reason = f"{explicit_reason}; right-click salvage selection"
            else:
                rule_match = self.get_matching_salvage_rule(item)
                if rule_match is not None:
                    rule_index = int(rule_match[0])
                    salvage_rule = rule_match[1]
                    selection_reason = rule_match[2]
            if salvage_rule is None or not selection_reason:
                if include_not_selected_blocks:
                    bucket = self.get_salvage_block_bucket("not selected by salvage settings")
                    if bucket:
                        blocked_counts[bucket] = blocked_counts.get(bucket, 0) + 1
                continue
            salvage_kit_id = 0
            if salvage_rule is not None:
                salvage_option = _normalize_salvage_rule_mode(
                    getattr(salvage_rule, "salvage_option", SALVAGE_OPTION_DEFAULT)
                )
                if max(0, _safe_int(preferred_salvage_kit_id, 0)) > 0:
                    salvage_kit_id = self._get_kit()(
                        salvage_option,
                        preferred_kit_id=preferred_salvage_kit_id,
                        preferred_kit_model_id=preferred_salvage_kit_model_id,
                    )
                else:
                    salvage_kit_id = self._get_kit()(salvage_option)
            reason = self.get_salvage_candidate_block_reason(
                item,
                enabled_sell_rules,
                salvage_rule=salvage_rule,
                require_salvage_kit=require_salvage_kit,
                salvage_kit_id=salvage_kit_id,
                mode=mode,
            )
            if reason:
                bucket = self.get_salvage_block_bucket(reason)
                if bucket and (include_not_selected_blocks or bucket != "not selected"):
                    blocked_counts[bucket] = blocked_counts.get(bucket, 0) + 1
                if bucket not in {"not selected", "unsalvageable"}:
                    item_label = self._get_item_label()(item)
                    self._get_diagnostic()(f"MR Salvage skipped {item_label} ({item.item_id}): {reason}")
                continue
            candidates.append(
                self._get_candidate_factory()(
                    item=item,
                    rule_index=rule_index,
                    rule=salvage_rule or SalvageRule(),
                    reason=selection_reason,
                )
            )
        return candidates, blocked_counts

    def plan_salvage_actions(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        enabled_sell_rules: list[tuple[int, SellRule]],
        claimed_item_ids: set[int],
    ) -> None:
        """Plan salvage actions before overlapping sell and destroy rules can claim the items."""

        if not self.has_enabled_salvage_settings():
            return

        candidates, blocked_counts = self.collect_salvage_candidates(
            items,
            enabled_sell_rules,
            require_salvage_kit=True,
            mode="manual",
        )
        candidate_item_ids = {
            max(0, int(candidate.item.item_id)) for candidate in candidates if max(0, int(candidate.item.item_id)) > 0
        }
        for item in items:
            item_id = max(0, int(item.item_id))
            if item_id <= 0 or item_id in candidate_item_ids:
                continue
            if self.get_specific_upgrade_salvage_reservation_reason(item):
                claimed_item_ids.add(item_id)

        for candidate in candidates:
            item = candidate.item
            item_id = max(0, int(item.item_id))
            if item_id <= 0:
                continue
            rule = self._normalizers.get_salvage_rule()(candidate.rule) or SalvageRule()
            if (
                int(candidate.rule_index) >= 0
                and _is_auto_exact_upgrade_salvage_option(rule.salvage_option)
                and salvage_rule_has_upgrade_targets(rule, normalizers=self._normalizers)
            ):
                plan.salvage_specific_upgrade_owners[item_id] = self._get_owner_factory()(
                    model_id=int(item.model_id),
                    rule_index=int(candidate.rule_index),
                    rule_snapshot=self._normalizers.get_salvage_rule()(rule) or SalvageRule(),
                )
            rule_reference = (
                self._get_rule_reference()(int(candidate.rule_index), rule)
                if int(candidate.rule_index) >= 0
                else "salvage selection"
            )
            reason = str(candidate.reason or "").strip()
            if not reason:
                reason = "Selected for salvage"
            option_label = _get_salvage_option_label(rule.salvage_option)
            if _is_auto_exact_upgrade_salvage_option(rule.salvage_option):
                slot_resolution = self.get_auto_salvage_upgrade_slot_resolution(rule, item)
                if slot_resolution.selected_option:
                    option_label = _get_salvage_option_label(slot_resolution.selected_option)
            reason = f"{reason}; {option_label} via {rule_reference}."
            if self.salvage_candidate_allows_stack_drain(candidate):
                reason = (
                    f"{reason} Up to {item.quantity} from this stack; stop early if it no longer qualifies "
                    "or a safety check fails."
                )
            plan.salvage_item_ids.append(item_id)
            claimed_item_ids.add(item_id)
            plan.entries.append(
                self._get_entry_factory()(
                    "salvage",
                    MERCHANT_TYPE_INVENTORY,
                    item.name,
                    item.quantity,
                    PLAN_STATE_WILL_EXECUTE,
                    reason,
                    model_id=item.model_id,
                )
            )

        for reason, count in sorted(blocked_counts.items()):
            safe_count = max(0, int(count))
            if safe_count <= 0:
                continue
            status_hint = (
                PREVIEW_STATUS_PROTECTED
                if reason == "protected"
                else (
                    PREVIEW_STATUS_SKIPPED
                    if reason in {"not selected", "immediate disabled"}
                    else PREVIEW_STATUS_BLOCKED
                )
            )
            plan.entries.append(
                self._get_entry_factory()(
                    "salvage",
                    MERCHANT_TYPE_INVENTORY,
                    "Salvage",
                    safe_count,
                    PLAN_STATE_SKIPPED,
                    f"Skipped {safe_count} {reason}.",
                    status_hint=status_hint,
                )
            )

    def salvage_candidate_allows_stack_drain(self, candidate: C) -> bool:
        item = getattr(candidate, "item", None)
        if not bool(getattr(item, "is_stackable", False)):
            return False
        rule = self._normalizers.get_salvage_rule()(getattr(candidate, "rule", None))
        if rule is None:
            return False
        configured_option = _normalize_salvage_rule_mode(getattr(rule, "salvage_option", SALVAGE_OPTION_DEFAULT))
        if _is_auto_exact_upgrade_salvage_option(configured_option):
            return False
        return _resolve_salvage_operation(configured_option) not in SALVAGE_UPGRADE_OPTIONS


class DestroyPlanner:
    """Own supplied-evidence selection/allocation without runtime authority."""

    def __init__(
        self,
        *,
        normalizers: SelectorNormalizers,
        read_rules: Callable[[], list[DestroyRule]],
        read_include_protected: Callable[[], bool],
        read_kind_labels: Callable[[], Mapping[str, str]],
        read_salvage: Callable[[], SalvageDestroySelection],
        get_empty_slot: Callable[[], EmptySlotReader],
        get_hard_protection: Callable[[], HardProtectionReader],
        get_rarity_match: Callable[[], Callable[["InventoryItemInfo", object], bool]],
        get_model_label: Callable[[], Callable[[int], str]],
        get_rule_reference: Callable[[], Callable[[int, DestroyRule], str]],
        get_diagnostic: Callable[[], Callable[[str], None]],
        get_choose_keep: Callable[[], Callable[[Sequence[StackQuantityView], int], set[int]]],
        get_choose_keep_at_most: Callable[[], Callable[[Sequence[StackQuantityView], int], tuple[set[int], int]]],
        get_action_factory: Callable[[], DestroyActionFactory],
        get_entry_factory: Callable[[], PlanEntryFactory],
    ) -> None:
        self._normalizers = normalizers
        self._read_rules = read_rules
        self._read_include_protected = read_include_protected
        self._read_kind_labels = read_kind_labels
        self._read_salvage = read_salvage
        self._get_empty_slot = get_empty_slot
        self._get_hard_protection = get_hard_protection
        self._get_rarity_match = get_rarity_match
        self._get_model_label = get_model_label
        self._get_rule_reference = get_rule_reference
        self._get_diagnostic = get_diagnostic
        self._get_choose_keep = get_choose_keep
        self._get_choose_keep_at_most = get_choose_keep_at_most
        self._get_action_factory = get_action_factory
        self._get_entry_factory = get_entry_factory

    def collect_enabled_destroy_rules(self) -> list[tuple[int, DestroyRule]]:
        enabled_destroy_rules: list[tuple[int, DestroyRule]] = []
        for rule_index, raw_destroy_rule in enumerate(self._read_rules()):
            destroy_rule = self._normalizers.get_destroy_rule()(raw_destroy_rule)
            if not destroy_rule.enabled:
                continue
            enabled_destroy_rules.append((rule_index, destroy_rule))
        return enabled_destroy_rules

    def plan_stackable_destroy_actions(
        self,
        items: list["InventoryItemInfo"],
        keep_count: int,
    ) -> tuple[list[PlannedDestroyAction], dict[int, int], str, int]:
        keep_count = max(0, int(keep_count))
        if not items:
            return [], {}, "", 0

        total_quantity = sum(max(1, int(item.quantity)) for item in items)
        if keep_count >= total_quantity:
            return [], {item.item_id: max(1, int(item.quantity)) for item in items}, "", 0

        whole_keep_ids, kept_total = self._get_choose_keep_at_most()(items, keep_count)
        keep_quantities: dict[int, int] = {
            int(item.item_id): max(1, int(item.quantity)) for item in items if item.item_id in whole_keep_ids
        }

        remaining_keep = max(0, keep_count - kept_total)
        if remaining_keep > 0:
            partial_candidates = [
                item for item in items if item.item_id not in whole_keep_ids and int(item.quantity) > remaining_keep
            ]
            if not partial_candidates:
                return [], {}, self.get_destroy_split_block_reason(remaining_keep), 0

            partial_item = min(
                partial_candidates,
                key=lambda item: (
                    max(1, int(item.quantity)),
                    str(item.name or "").lower(),
                    int(item.item_id),
                ),
            )
            keep_quantities[int(partial_item.item_id)] = remaining_keep

        planned_actions: list[PlannedDestroyAction] = []
        for item in items:
            source_quantity = max(1, int(item.quantity))
            keep_quantity = max(0, int(keep_quantities.get(int(item.item_id), 0)))
            destroy_quantity = max(0, source_quantity - keep_quantity)
            if destroy_quantity <= 0:
                continue
            planned_actions.append(
                self._get_action_factory()(
                    item_id=int(item.item_id),
                    model_id=int(item.model_id),
                    label=str(item.name or f"Model {int(item.model_id)}"),
                    quantity_to_destroy=destroy_quantity,
                    source_quantity=source_quantity,
                    keep_quantity=keep_quantity,
                    requires_split=keep_quantity > 0 and destroy_quantity < source_quantity,
                )
            )
        requires_external_free_slot = 0
        if any(bool(action.requires_split) for action in planned_actions) and not any(
            not bool(action.requires_split) for action in planned_actions
        ):
            requires_external_free_slot = remaining_keep
        return planned_actions, keep_quantities, "", requires_external_free_slot

    def get_destroy_split_block_reason(self, keep_quantity: int) -> str:
        safe_keep_quantity = max(0, int(keep_quantity))
        return (
            f"Keep count requires splitting a stack to preserve {safe_keep_quantity} unit(s), "
            "but no empty inventory slot was available and no earlier destroy action would free one."
        )

    def plan_destroy_rule(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        rule: DestroyRule,
        rule_index: int,
        claimed_item_ids: set[int],
        enabled_sell_rules: list[tuple[int, SellRule]],
    ) -> None:
        """Plan one destroy rule after applying claims, keep counts, and hard protections.

        Partial stack destruction is emitted only when a safe split destination is available.
        Session-only protected-item override state is reflected visibly in skipped entries.
        """

        include_protected_items = bool(self._read_include_protected())
        candidate_label = self._read_kind_labels().get(rule.kind, "Destroy Rule")
        rule_reference = self._get_rule_reference()(rule_index, rule)
        if rule.kind in (DESTROY_KIND_EXPLICIT_MODELS, DESTROY_KIND_MATERIALS):
            whitelist_targets = self._normalizers.get_whitelist_targets()(getattr(rule, "whitelist_targets", []))
            if not whitelist_targets:
                missing_reason = (
                    "No material model whitelist configured."
                    if rule.kind == DESTROY_KIND_MATERIALS
                    else "No explicit model whitelist configured."
                )
                plan.entries.append(
                    self._get_entry_factory()(
                        "destroy",
                        MERCHANT_TYPE_INVENTORY,
                        candidate_label,
                        0,
                        PLAN_STATE_SKIPPED,
                        missing_reason,
                    )
                )
                return

            target_plans: list[_DestroyTargetStage] = []
            for target in whitelist_targets:
                target_model_id = max(0, int(target.model_id))
                target_keep_count = max(0, int(target.keep_count))
                target_label = self._get_model_label()(target_model_id)
                matching_items = [
                    item
                    for item in items
                    if item.item_id not in claimed_item_ids
                    and (
                        (rule.kind == DESTROY_KIND_EXPLICIT_MODELS and item.model_id == target_model_id)
                        or (
                            rule.kind == DESTROY_KIND_MATERIALS
                            and item.is_material
                            and item.model_id == target_model_id
                        )
                    )
                ]
                if not matching_items:
                    missing_reason = (
                        "No matching material items found."
                        if rule.kind == DESTROY_KIND_MATERIALS
                        else "No matching inventory items found."
                    )
                    plan.entries.append(
                        self._get_entry_factory()(
                            "destroy",
                            MERCHANT_TYPE_INVENTORY,
                            target_label,
                            0,
                            PLAN_STATE_SKIPPED,
                            missing_reason,
                            status_hint=PREVIEW_STATUS_NO_MATCH,
                        )
                    )
                    continue

                protected_items: list[tuple["InventoryItemInfo", str]] = []
                salvage_items: list[tuple["InventoryItemInfo", str]] = []
                destroy_pool: list[tuple["InventoryItemInfo", str]] = []
                for item in matching_items:
                    hard_protection = self._get_hard_protection()(item, enabled_sell_rules)
                    protection_reason = hard_protection[1] if hard_protection is not None else ""
                    salvage_reason = self._read_salvage().get_salvage_destroy_claim_reason(item, enabled_sell_rules)
                    if protection_reason and (not include_protected_items or salvage_reason):
                        protected_items.append((item, protection_reason))
                    elif salvage_reason:
                        salvage_items.append((item, salvage_reason))
                    else:
                        destroy_pool.append((item, protection_reason))

                keep_quantities: dict[int, int] = {}
                planned_actions: list[PlannedDestroyAction] = []
                destroy_block_reason = ""
                split_keep_quantity_needed = 0
                effective_keep_count = max(0, target_keep_count)
                if not include_protected_items:
                    effective_keep_count = max(
                        0,
                        effective_keep_count - sum(max(1, int(item.quantity)) for item, _reason in protected_items),
                    )
                effective_keep_count = max(
                    0,
                    effective_keep_count - sum(max(1, int(item.quantity)) for item, _reason in salvage_items),
                )

                destroy_items = [item for item, _reason in destroy_pool]
                if any(int(item.quantity) > 1 for item in destroy_items):
                    planned_actions, keep_quantities, destroy_block_reason, split_keep_quantity_needed = (
                        self.plan_stackable_destroy_actions(
                            destroy_items,
                            effective_keep_count,
                        )
                    )
                else:
                    keep_ids = self._get_choose_keep()(destroy_items, effective_keep_count)
                    keep_quantities = {
                        int(item.item_id): max(1, int(item.quantity))
                        for item in destroy_items
                        if item.item_id in keep_ids
                    }
                    planned_actions = [
                        self._get_action_factory()(
                            item_id=int(item.item_id),
                            model_id=int(item.model_id),
                            label=str(item.name or f"Model {int(item.model_id)}"),
                            quantity_to_destroy=max(1, int(item.quantity)),
                            source_quantity=max(1, int(item.quantity)),
                        )
                        for item in destroy_items
                        if item.item_id not in keep_ids
                    ]

                target_plans.append(
                    {
                        "label": target_label,
                        "target_keep_count": target_keep_count,
                        "matching_items": matching_items,
                        "protected_items": protected_items,
                        "salvage_items": salvage_items,
                        "destroy_pool": destroy_pool,
                        "keep_quantities": keep_quantities,
                        "planned_actions": planned_actions,
                        "destroy_block_reason": destroy_block_reason,
                        "split_keep_quantity_needed": split_keep_quantity_needed,
                    }
                )

            has_empty_slot_now = self._get_empty_slot()(items) is not None
            has_non_split_destroy_anywhere = any(not bool(action.requires_split) for action in plan.destroy_actions)
            has_non_split_destroy_anywhere = has_non_split_destroy_anywhere or any(
                any(not bool(action.requires_split) for action in target_plan["planned_actions"])
                for target_plan in target_plans
                if not str(target_plan["destroy_block_reason"] or "").strip()
            )

            total_matched = 0
            total_protected = 0
            total_salvage_reserved = 0
            total_kept_quantity = 0
            total_planned_destroys = 0
            total_planned_destroy_quantity = 0
            for target_plan in target_plans:
                matching_items = list(target_plan["matching_items"])
                protected_items = list(target_plan["protected_items"])
                salvage_items = list(target_plan["salvage_items"])
                destroy_pool = list(target_plan["destroy_pool"])
                keep_quantities = dict(target_plan["keep_quantities"])
                planned_actions = list(target_plan["planned_actions"])
                destroy_block_reason = str(target_plan["destroy_block_reason"] or "")
                split_keep_quantity_needed = max(0, int(target_plan["split_keep_quantity_needed"]))
                target_keep_count = max(0, int(target_plan["target_keep_count"]))
                target_label = str(target_plan["label"] or candidate_label)

                for item in matching_items:
                    claimed_item_ids.add(item.item_id)

                if (
                    not destroy_block_reason
                    and split_keep_quantity_needed > 0
                    and not (has_empty_slot_now or has_non_split_destroy_anywhere)
                ):
                    destroy_block_reason = self.get_destroy_split_block_reason(split_keep_quantity_needed)
                    keep_quantities = {}
                    planned_actions = []

                planned_actions_by_item_id = {int(action.item_id): action for action in planned_actions}
                kept_quantity_total = sum(max(0, int(quantity)) for quantity in keep_quantities.values())
                planned_destroys = 0
                planned_destroy_quantity = 0

                total_matched += len(matching_items)
                total_protected += len(protected_items)
                total_salvage_reserved += len(salvage_items)
                total_kept_quantity += kept_quantity_total

                for item, protection_reason in protected_items:
                    plan.entries.append(
                        self._get_entry_factory()(
                            "destroy",
                            MERCHANT_TYPE_INVENTORY,
                            item.name,
                            item.quantity,
                            PLAN_STATE_SKIPPED,
                            f"Blocked by {rule_reference}: {protection_reason}",
                            model_id=item.model_id,
                            status_hint=PREVIEW_STATUS_PROTECTED,
                        )
                    )

                for item, salvage_reason in salvage_items:
                    plan.entries.append(
                        self._get_entry_factory()(
                            "destroy",
                            MERCHANT_TYPE_INVENTORY,
                            item.name,
                            item.quantity,
                            PLAN_STATE_SKIPPED,
                            f"Blocked by {rule_reference}: selected for MR Salvage ({salvage_reason}); salvage wins over destroy.",
                            model_id=item.model_id,
                            status_hint=PREVIEW_STATUS_SKIPPED,
                        )
                    )

                if destroy_block_reason:
                    destroy_status_hint = (
                        PREVIEW_STATUS_UNSAFE
                        if "Keep count requires splitting" in destroy_block_reason
                        else PREVIEW_STATUS_BLOCKED
                    )
                    plan.entries.append(
                        self._get_entry_factory()(
                            "destroy",
                            MERCHANT_TYPE_INVENTORY,
                            target_label,
                            0,
                            PLAN_STATE_SKIPPED,
                            f"Blocked by {rule_reference}: {destroy_block_reason}",
                            status_hint=destroy_status_hint,
                        )
                    )

                for item, protection_reason in destroy_pool:
                    keep_quantity = max(0, int(keep_quantities.get(int(item.item_id), 0)))
                    action = planned_actions_by_item_id.get(int(item.item_id))
                    if action is not None:
                        reason_parts = [f"Matched by {rule_reference}."]
                        if action.requires_split:
                            reason_parts.append(f"Split stack to keep {max(0, int(action.keep_quantity))} unit(s).")
                        if protection_reason:
                            reason_parts.append(f"Included protected item: {protection_reason}")
                        plan.destroy_actions.append(action)
                        plan.destroy_item_ids.append(int(action.item_id))
                        plan.entries.append(
                            self._get_entry_factory()(
                                "destroy",
                                MERCHANT_TYPE_INVENTORY,
                                item.name,
                                max(0, int(action.quantity_to_destroy)),
                                PLAN_STATE_WILL_EXECUTE,
                                " ".join(reason_parts),
                                model_id=item.model_id,
                            )
                        )
                        planned_destroys += 1
                        planned_destroy_quantity += max(0, int(action.quantity_to_destroy))

                    if keep_quantity > 0:
                        keep_reason = (
                            f"Kept by {rule_reference}: reserved to satisfy keep count {target_keep_count}."
                            if keep_quantity >= max(1, int(item.quantity))
                            else (
                                f"Kept by {rule_reference}: reserved {keep_quantity} unit(s) "
                                f"to satisfy keep count {target_keep_count}."
                            )
                        )
                        plan.entries.append(
                            self._get_entry_factory()(
                                "destroy",
                                MERCHANT_TYPE_INVENTORY,
                                item.name,
                                keep_quantity,
                                PLAN_STATE_SKIPPED,
                                keep_reason,
                                model_id=item.model_id,
                            )
                        )

                if (
                    planned_destroys <= 0
                    and not protected_items
                    and kept_quantity_total > 0
                    and not destroy_block_reason
                ):
                    plan.entries.append(
                        self._get_entry_factory()(
                            "destroy",
                            MERCHANT_TYPE_INVENTORY,
                            target_label,
                            0,
                            PLAN_STATE_SKIPPED,
                            f"Kept by {rule_reference}: matching items were reserved to satisfy keep count {target_keep_count}.",
                        )
                    )

                total_planned_destroys += planned_destroys
                total_planned_destroy_quantity += planned_destroy_quantity

            self._get_diagnostic()(
                f"{candidate_label}: matched={total_matched} protected={total_protected} salvage_reserved={total_salvage_reserved} "
                f"kept_quantity={total_kept_quantity} planned_destroys={total_planned_destroys} "
                f"planned_destroy_quantity={total_planned_destroy_quantity} include_protected={include_protected_items}"
            )
            return

        matching_items: list["InventoryItemInfo"] = []
        had_category_candidate = False
        had_rarity_candidate = False
        for item in items:
            if item.item_id in claimed_item_ids:
                continue
            if rule.kind == DESTROY_KIND_WEAPONS:
                if not item.is_weapon_like:
                    continue
            elif rule.kind == DESTROY_KIND_ARMOR:
                if not item.is_armor_piece:
                    continue
            else:
                continue

            had_category_candidate = True
            if not self._get_rarity_match()(item, rule):
                continue
            had_rarity_candidate = True
            matching_items.append(item)

        if not matching_items:
            reason = (
                "No matching items found for the enabled rarities."
                if had_category_candidate and not had_rarity_candidate
                else "No matching inventory items found."
            )
            plan.entries.append(
                self._get_entry_factory()(
                    "destroy",
                    MERCHANT_TYPE_INVENTORY,
                    candidate_label,
                    0,
                    PLAN_STATE_SKIPPED,
                    reason,
                    status_hint=PREVIEW_STATUS_NO_MATCH,
                )
            )
            return

        for item in matching_items:
            claimed_item_ids.add(item.item_id)

        protected_items: list[tuple["InventoryItemInfo", str]] = []
        salvage_items: list[tuple["InventoryItemInfo", str]] = []
        destroy_pool: list[tuple["InventoryItemInfo", str]] = []
        for item in matching_items:
            hard_protection = self._get_hard_protection()(item, enabled_sell_rules)
            protection_reason = hard_protection[1] if hard_protection is not None else ""
            salvage_reason = self._read_salvage().get_salvage_destroy_claim_reason(item, enabled_sell_rules)
            if protection_reason and (not include_protected_items or salvage_reason):
                protected_items.append((item, protection_reason))
            elif salvage_reason:
                salvage_items.append((item, salvage_reason))
            else:
                destroy_pool.append((item, protection_reason))

        planned_actions = [
            self._get_action_factory()(
                item_id=int(item.item_id),
                model_id=int(item.model_id),
                label=str(item.name or f"Model {int(item.model_id)}"),
                quantity_to_destroy=max(1, int(item.quantity)),
                source_quantity=max(1, int(item.quantity)),
            )
            for item, _reason in destroy_pool
        ]
        planned_actions_by_item_id = {int(action.item_id): action for action in planned_actions}

        planned_destroys = 0
        planned_destroy_quantity = 0
        for item, protection_reason in protected_items:
            plan.entries.append(
                self._get_entry_factory()(
                    "destroy",
                    MERCHANT_TYPE_INVENTORY,
                    item.name,
                    item.quantity,
                    PLAN_STATE_SKIPPED,
                    f"Blocked by {rule_reference}: {protection_reason}",
                    model_id=item.model_id,
                    status_hint=PREVIEW_STATUS_PROTECTED,
                )
            )

        for item, salvage_reason in salvage_items:
            plan.entries.append(
                self._get_entry_factory()(
                    "destroy",
                    MERCHANT_TYPE_INVENTORY,
                    item.name,
                    item.quantity,
                    PLAN_STATE_SKIPPED,
                    f"Blocked by {rule_reference}: selected for MR Salvage ({salvage_reason}); salvage wins over destroy.",
                    model_id=item.model_id,
                    status_hint=PREVIEW_STATUS_SKIPPED,
                )
            )

        for item, protection_reason in destroy_pool:
            action = planned_actions_by_item_id.get(int(item.item_id))
            if action is None:
                continue
            reason_parts = [f"Matched by {rule_reference}."]
            if protection_reason:
                reason_parts.append(f"Included protected item: {protection_reason}")
            plan.destroy_actions.append(action)
            plan.destroy_item_ids.append(int(action.item_id))
            plan.entries.append(
                self._get_entry_factory()(
                    "destroy",
                    MERCHANT_TYPE_INVENTORY,
                    item.name,
                    max(0, int(action.quantity_to_destroy)),
                    PLAN_STATE_WILL_EXECUTE,
                    " ".join(reason_parts),
                    model_id=item.model_id,
                )
            )
            planned_destroys += 1
            planned_destroy_quantity += max(0, int(action.quantity_to_destroy))

        self._get_diagnostic()(
            f"{candidate_label}: matched={len(matching_items)} protected={len(protected_items)} salvage_reserved={len(salvage_items)} "
            f"kept_quantity=0 planned_destroys={planned_destroys} "
            f"planned_destroy_quantity={planned_destroy_quantity} include_protected={include_protected_items}"
        )

    def plan_destroy_actions(
        self,
        plan: PlanResult,
        items: list["InventoryItemInfo"],
        enabled_destroy_rules: list[tuple[int, DestroyRule]],
        enabled_sell_rules: list[tuple[int, SellRule]],
        claimed_item_ids: set[int],
    ) -> None:
        for rule_index, destroy_rule in enabled_destroy_rules:
            self.plan_destroy_rule(
                plan,
                items,
                destroy_rule,
                rule_index,
                claimed_item_ids,
                enabled_sell_rules,
            )


class RuleIdAllocator(Protocol):
    def __call__(self, raw_value: object, *, seen_ids: set[str], prefix: str, fallback_seed: object = "") -> str: ...


class SupportedContextReader(Protocol):
    def __call__(self, *, passive: bool = False) -> tuple[bool, str, dict[str, tuple[float, float] | None]]: ...


class TravelTargetReachedReader(Protocol):
    def __call__(self, target_outpost_id: int, current_map_id: int | None = None) -> bool: ...


class PlanSummaryLogger(Protocol):
    def __call__(self, prefix: str, plan: PlanResult) -> None: ...


@dataclass
class CompositionNormalizers:
    """Late aliases to existing normalizers; no rule-selection algorithms."""

    get_buy_rule: Callable[[], Callable[[BuyRule], BuyRule | None]]
    get_sell_rule: Callable[[], Callable[[SellRule], SellRule | None]]
    get_material_targets: Callable[[], Callable[[object], list[MaterialTarget]]]
    get_merchant_stock_targets: Callable[[], Callable[[object], list[MerchantStockTarget]]]
    get_rune_sell_targets: Callable[[], Callable[[object], list[RuneSellTarget]]]
    get_rune_trader_targets: Callable[[], Callable[[object], list[RuneTraderTarget]]]
    get_whitelist_targets: Callable[[], Callable[[object], list[WhitelistTarget]]]
    get_unique_rule_id: Callable[[], RuleIdAllocator]
    get_safe_int: Callable[[], Callable[[object, int], int]]
    get_scroll_stock: Callable[[], Callable[[object], bool]]
    get_material_storage_permission: Callable[[], Callable[[SellRule], bool]]


def projected_preview_reason_suffix(
    merchant_type: str,
    target_outpost_name: str,
    *,
    read_merchant_labels: Callable[[], Mapping[str, str]],
) -> str:
    target_label = str(target_outpost_name or "").strip() or "the selected outpost"
    if str(merchant_type) == MERCHANT_TYPE_STORAGE:
        return f"Projected after travel to {target_label}. Travel + Execute will reopen Xunlai after arrival."
    merchant_label = read_merchant_labels().get(str(merchant_type), "merchant handling")
    return (
        f"Projected after travel to {target_label}. "
        f"Travel + Execute will confirm live {merchant_label} access on arrival."
    )


class PlanComposer[
    R: CrafterRecipeView, C: SalvageCandidateView, M: SalvageUpgradeMatchView, S: SalvageSlotResolutionView
]:
    """Compose intent using current owners and observations; retain only diagnostic duration."""

    def __init__(
        self,
        *,
        normalizers: CompositionNormalizers,
        read_buy_rules: Callable[[], list[BuyRule]],
        read_sell_rules: Callable[[], list[SellRule]],
        read_destroy_rules: Callable[[], list[DestroyRule]],
        read_auto_travel: Callable[[], bool],
        read_target_outpost: Callable[[], int],
        read_reservation_active: Callable[[], bool],
        read_reserved_item_ids: Callable[[], set[int]],
        read_sale_planner: Callable[[], SalePlanner],
        read_buy_planner: Callable[[], BuyPlanner[R]],
        read_cleanup_planner: Callable[[], CleanupPlanner],
        read_identify_planner: Callable[[], IdentifyPlanner],
        read_salvage_planner: Callable[[], SalvagePlanner[C, M, S]],
        read_destroy_planner: Callable[[], DestroyPlanner],
        read_policy: Callable[[], "ProtectionPolicy"],
        get_inventory_items: Callable[[], Callable[[], list["InventoryItemInfo"]]],
        get_storage_items: Callable[[], Callable[[], list["InventoryItemInfo"]]],
        get_reliable_storage_items: Callable[[], Callable[[], tuple[list["InventoryItemInfo"], bool]]],
        get_material_storage_items: Callable[[], Callable[[], list["InventoryItemInfo"]]],
        get_supported_context: Callable[[], SupportedContextReader],
        get_local_storage_ready: Callable[[], Callable[[], bool]],
        get_storage_open: Callable[[], Callable[[], bool]],
        get_map_id: Callable[[], Callable[[], int | None]],
        get_outpost_name: Callable[[], Callable[[int], str]],
        get_guild_hall_target: Callable[[], Callable[[int], bool]],
        get_target_reached: Callable[[], TravelTargetReachedReader],
        get_embark_name: Callable[[], Callable[[], str]],
        read_embark_id: Callable[[], int],
        read_projected_coords: Callable[[], tuple[float, float]],
        read_merchant_labels: Callable[[], Mapping[str, str]],
        read_recipes: Callable[[], Mapping[int, tuple[R, ...]]],
        get_early_kit_models: Callable[[], Callable[[str], tuple[int, ...]]],
        read_live_check_status: Callable[[], str],
        get_quantity: Callable[[], Callable[[int], int]],
        get_clock: Callable[[], Callable[[], float]],
        get_diagnostic: Callable[[], Callable[[str], None]],
        get_plan_summary: Callable[[], PlanSummaryLogger],
        get_plan_factory: Callable[[], type[PlanResult]],
        get_entry_factory: Callable[[], PlanEntryFactory],
    ) -> None:
        self._normalizers = normalizers
        self._read_buy_rules = read_buy_rules
        self._read_sell_rules = read_sell_rules
        self._read_destroy_rules = read_destroy_rules
        self._read_auto_travel = read_auto_travel
        self._read_target_outpost = read_target_outpost
        self._read_reservation_active = read_reservation_active
        self._read_reserved_item_ids = read_reserved_item_ids
        self._read_sale_planner = read_sale_planner
        self._read_buy_planner = read_buy_planner
        self._read_cleanup_planner = read_cleanup_planner
        self._read_identify_planner = read_identify_planner
        self._read_salvage_planner = read_salvage_planner
        self._read_destroy_planner = read_destroy_planner
        self._read_policy = read_policy
        self._get_inventory_items = get_inventory_items
        self._get_storage_items = get_storage_items
        self._get_reliable_storage_items = get_reliable_storage_items
        self._get_material_storage_items = get_material_storage_items
        self._get_supported_context = get_supported_context
        self._get_local_storage_ready = get_local_storage_ready
        self._get_storage_open = get_storage_open
        self._get_map_id = get_map_id
        self._get_outpost_name = get_outpost_name
        self._get_guild_hall_target = get_guild_hall_target
        self._get_target_reached = get_target_reached
        self._get_embark_name = get_embark_name
        self._read_embark_id = read_embark_id
        self._read_projected_coords = read_projected_coords
        self._read_merchant_labels = read_merchant_labels
        self._read_recipes = read_recipes
        self._get_early_kit_models = get_early_kit_models
        self._read_live_check_status = read_live_check_status
        self._get_quantity = get_quantity
        self._get_clock = get_clock
        self._get_diagnostic = get_diagnostic
        self._get_plan_summary = get_plan_summary
        self._get_plan_factory = get_plan_factory
        self._get_entry_factory = get_entry_factory
        self.last_plan_build_duration_ms = 0.0

    def get_consumable_crafter_multi_stop_target(self) -> tuple[int, str]:
        if not self._read_auto_travel() or not self.has_enabled_consumable_crafter_buy_rules():
            return 0, ""
        target_outpost_id = max(0, self._normalizers.get_safe_int()(self._read_target_outpost(), 0))
        if target_outpost_id <= 0 or target_outpost_id == self._read_embark_id():
            return 0, ""
        target_outpost_name = self._get_outpost_name()(target_outpost_id)
        if not target_outpost_name:
            return 0, ""
        return target_outpost_id, target_outpost_name

    def should_use_consumable_crafter_multi_stop_route(self) -> bool:
        target_outpost_id, _target_outpost_name = self.get_consumable_crafter_multi_stop_target()
        return target_outpost_id > 0

    def get_preview_projection_target(self) -> tuple[int, str]:
        target_outpost_id = max(0, int(self._read_target_outpost())) if self._read_auto_travel() else 0
        if target_outpost_id <= 0:
            return 0, ""
        target_outpost_name = self._get_outpost_name()(target_outpost_id)
        if not target_outpost_name:
            return 0, ""
        if self._get_target_reached()(target_outpost_id):
            return 0, ""
        return target_outpost_id, target_outpost_name

    def get_required_service_types(self) -> set[str]:
        """Return only merchant/trader services that enabled rules can actually use."""

        required: set[str] = set()

        for raw_rule in self._read_buy_rules():
            rule = self._normalizers.get_buy_rule()(raw_rule)
            if rule is None or not rule.enabled:
                continue

            if rule.kind == BUY_KIND_MATERIAL_TARGET:
                for target in self._normalizers.get_material_targets()(rule.material_targets):
                    model_id = max(0, int(target.model_id))
                    if model_id > 0:
                        required.add(material_destination(model_id))
                continue

            if rule.kind == BUY_KIND_RUNE_TRADER_TARGET:
                if self._normalizers.get_rune_trader_targets()(rule.rune_targets):
                    required.add(MERCHANT_TYPE_RUNE_TRADER)
                continue

            if rule.kind == BUY_KIND_SCROLL_TRADER_TARGET:
                if any(
                    self._normalizers.get_scroll_stock()(target.model_id)
                    for target in self._normalizers.get_merchant_stock_targets()(rule.merchant_stock_targets)
                ):
                    required.add(MERCHANT_TYPE_SCROLL_TRADER)
                continue

            if rule.kind == BUY_KIND_CONSUMABLE_CRAFTER_TARGET:
                if any(
                    int(target.model_id) in self._read_recipes()
                    for target in self._normalizers.get_merchant_stock_targets()(rule.merchant_stock_targets)
                ):
                    required.add(MERCHANT_TYPE_CONSUMABLE_CRAFTER)
                continue

            if rule.kind == BUY_KIND_MERCHANT_STOCK:
                for target in self._normalizers.get_merchant_stock_targets()(rule.merchant_stock_targets):
                    if int(target.model_id) <= 0:
                        continue
                    required.add(
                        MERCHANT_TYPE_SCROLL_TRADER
                        if self._normalizers.get_scroll_stock()(target.model_id)
                        else MERCHANT_TYPE_MERCHANT
                    )

        for raw_rule in self._read_sell_rules():
            rule = self._normalizers.get_sell_rule()(raw_rule)
            if rule is None or not rule.enabled:
                continue

            if rule.kind in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
                if any(bool(value) for value in getattr(rule, "rarities", {}).values()):
                    required.add(MERCHANT_TYPE_MERCHANT)
                if rule.kind == SELL_KIND_ARMOR and bool(getattr(rule, "include_standalone_runes", False)):
                    required.add(MERCHANT_TYPE_RUNE_TRADER)
                continue

            if rule.kind == SELL_KIND_RUNE_TRADER_TARGET:
                if self._normalizers.get_rune_sell_targets()(getattr(rule, "rune_sell_targets", [])):
                    required.add(MERCHANT_TYPE_RUNE_TRADER)
                continue

            if rule.kind == SELL_KIND_COMMON_MATERIALS:
                # A material rule may contain common and/or rare materials.  Keep
                # this conservative unless the plan has already narrowed the item set.
                required.add(MERCHANT_TYPE_MATERIALS)
                required.add(MERCHANT_TYPE_RARE_MATERIALS)
                continue

            if rule.kind == SELL_KIND_EXPLICIT_MODELS:
                if self._normalizers.get_whitelist_targets()(getattr(rule, "whitelist_targets", [])):
                    # Explicit items can route to merchant, material traders or the
                    # rune trader depending on the actual item type.
                    required.update(
                        {
                            MERCHANT_TYPE_MERCHANT,
                            MERCHANT_TYPE_MATERIALS,
                            MERCHANT_TYPE_RARE_MATERIALS,
                            MERCHANT_TYPE_RUNE_TRADER,
                        }
                    )

        return required

    def get_projected_supported_context(
        self, target_outpost_id: int
    ) -> tuple[bool, str, dict[str, tuple[float, float] | None]]:
        safe_outpost_id = max(0, self._normalizers.get_safe_int()(target_outpost_id, 0))
        outpost_name = self._get_outpost_name()(safe_outpost_id)
        coords: dict[str, tuple[float, float] | None] = {
            MERCHANT_TYPE_MERCHANT: self._read_projected_coords(),
            MERCHANT_TYPE_MATERIALS: self._read_projected_coords(),
            MERCHANT_TYPE_RUNE_TRADER: self._read_projected_coords(),
            MERCHANT_TYPE_SCROLL_TRADER: self._read_projected_coords(),
            MERCHANT_TYPE_RARE_MATERIALS: self._read_projected_coords(),
            MERCHANT_TYPE_CONSUMABLE_CRAFTER: (
                self._read_projected_coords() if safe_outpost_id == self._read_embark_id() else None
            ),
        }
        if safe_outpost_id <= 0 or not outpost_name:
            return (
                False,
                "Projected preview target is not configured.",
                {
                    MERCHANT_TYPE_MERCHANT: None,
                    MERCHANT_TYPE_MATERIALS: None,
                    MERCHANT_TYPE_RUNE_TRADER: None,
                    MERCHANT_TYPE_SCROLL_TRADER: None,
                    MERCHANT_TYPE_RARE_MATERIALS: None,
                    MERCHANT_TYPE_CONSUMABLE_CRAFTER: None,
                },
            )

        arrival_label = "Guild Hall arrival" if self._get_guild_hall_target()(safe_outpost_id) else "arrival"
        reason = (
            f"Projected preview for {outpost_name} ({safe_outpost_id}). "
            f"Travel + Execute will auto-travel, then recheck current items and available services after {arrival_label}. "
            "Destination NPC and storage access will be confirmed on arrival."
        )
        return True, reason, coords

    def is_projected_destination_entry(self, entry: ExecutionPlanEntry) -> bool:
        action_type = str(entry.action_type)
        merchant_type = str(entry.merchant_type)
        if merchant_type in (
            MERCHANT_TYPE_MERCHANT,
            MERCHANT_TYPE_MATERIALS,
            MERCHANT_TYPE_RUNE_TRADER,
            MERCHANT_TYPE_SCROLL_TRADER,
            MERCHANT_TYPE_RARE_MATERIALS,
            MERCHANT_TYPE_CONSUMABLE_CRAFTER,
        ):
            return action_type in {"buy", "sell"}
        if merchant_type == MERCHANT_TYPE_STORAGE:
            return action_type in {"deposit", "withdraw"}
        return False

    def get_projected_preview_reason_suffix(self, merchant_type: str, target_outpost_name: str) -> str:
        return projected_preview_reason_suffix(
            merchant_type, target_outpost_name, read_merchant_labels=self._read_merchant_labels
        )

    def append_projected_preview_reason(self, reason: str, merchant_type: str, target_outpost_name: str) -> str:
        suffix = self.get_projected_preview_reason_suffix(merchant_type, target_outpost_name)
        normalized_reason = str(reason or "").strip()
        if suffix and suffix in normalized_reason:
            return normalized_reason
        if not normalized_reason:
            return suffix
        return f"{normalized_reason} {suffix}".strip()

    def apply_projected_preview_post_processing(self, plan: PlanResult, target_outpost_name: str) -> None:
        for entry in plan.entries:
            if not self.is_projected_destination_entry(entry):
                continue
            if str(entry.state) == PLAN_STATE_WILL_EXECUTE:
                entry.state = PLAN_STATE_CONDITIONAL
            if str(entry.state) == PLAN_STATE_CONDITIONAL:
                entry.reason = self.append_projected_preview_reason(
                    entry.reason, entry.merchant_type, target_outpost_name
                )

    def build_travel_preview(self, target_outpost_id: int) -> PlanResult:
        safe_outpost_id = max(0, self._normalizers.get_safe_int()(target_outpost_id, 0))
        outpost_name = self._get_outpost_name()(safe_outpost_id)
        if safe_outpost_id <= 0 or not outpost_name:
            return self._get_plan_factory()(
                supported_map=False,
                supported_reason="Auto-travel target is not configured.",
                has_actions=False,
            )

        is_guild_hall_target = self._get_guild_hall_target()(safe_outpost_id)
        arrival_label = "Guild Hall arrival" if is_guild_hall_target else "arrival"
        travel_reason = (
            "Travel to the Guild Hall. After arrival, Merchant Rules will recheck current items and available "
            "services before executing."
            if is_guild_hall_target
            else ("After arrival, Merchant Rules will recheck current items and available services before executing.")
        )
        result = self._get_plan_factory()(
            supported_map=True,
            supported_reason=(
                f"Previewing travel to {outpost_name} ({safe_outpost_id}). "
                f"Merchant actions will be checked and re-planned after {arrival_label}."
            ),
            travel_to_outpost_id=safe_outpost_id,
            travel_to_outpost_name=outpost_name,
            has_actions=True,
        )
        result.entries.append(
            self._get_entry_factory()(
                action_type="travel",
                merchant_type=MERCHANT_TYPE_TRAVEL,
                label=outpost_name,
                quantity=1,
                state=PLAN_STATE_WILL_EXECUTE,
                reason=travel_reason,
            )
        )
        return result

    def build_consumable_crafter_multi_stop_preview(
        self,
        destination_outpost_id: int,
        *,
        execution_context: PurchaseRequestView | None = None,
    ) -> PlanResult:
        safe_destination_id = max(0, self._normalizers.get_safe_int()(destination_outpost_id, 0))
        destination_name = self._get_outpost_name()(safe_destination_id)
        if safe_destination_id <= 0 or not destination_name:
            return self._get_plan_factory()(
                supported_map=False,
                supported_reason="Auto-travel target is not configured.",
                has_actions=False,
            )

        embark_name = self._get_embark_name()()
        embark_plan = self.build_plan(
            projected_preview=True,
            projected_target_override_outpost_id=self._read_embark_id(),
            allow_consumable_multi_stop=False,
            consumable_crafter_only=True,
            execution_context=execution_context,
        )
        destination_plan = self.build_plan(
            projected_preview=True,
            projected_target_override_outpost_id=safe_destination_id,
            allow_consumable_multi_stop=False,
            exclude_consumable_crafter=True,
            execution_context=execution_context,
        )

        if not embark_plan.has_actions:
            return destination_plan

        storage_states = {str(embark_plan.storage_plan_state), str(destination_plan.storage_plan_state)}
        if STORAGE_PLAN_STATE_NEEDS_EXACT_SCAN in storage_states:
            storage_plan_state = STORAGE_PLAN_STATE_NEEDS_EXACT_SCAN
        elif STORAGE_PLAN_STATE_EXACT_READY in storage_states:
            storage_plan_state = STORAGE_PLAN_STATE_EXACT_READY
        else:
            storage_plan_state = STORAGE_PLAN_STATE_NOT_NEEDED

        coords = dict(destination_plan.coords)
        coords[MERCHANT_TYPE_CONSUMABLE_CRAFTER] = embark_plan.coords.get(MERCHANT_TYPE_CONSUMABLE_CRAFTER)
        destination_has_work = bool(destination_plan.has_actions)
        entries: list[ExecutionPlanEntry] = []
        if not self._get_target_reached()(self._read_embark_id()):
            entries.append(
                self._get_entry_factory()(
                    action_type="travel",
                    merchant_type=MERCHANT_TYPE_TRAVEL,
                    label=embark_name,
                    quantity=1,
                    state=PLAN_STATE_WILL_EXECUTE,
                    reason="Travel to Embark Beach first for Consumable Crafter buys.",
                )
            )
        entries.extend(
            replace(entry)
            for entry in embark_plan.entries
            if str(entry.merchant_type) == MERCHANT_TYPE_CONSUMABLE_CRAFTER
        )
        if destination_has_work:
            entries.append(
                self._get_entry_factory()(
                    action_type="travel",
                    merchant_type=MERCHANT_TYPE_TRAVEL,
                    label=destination_name,
                    quantity=1,
                    state=PLAN_STATE_WILL_EXECUTE,
                    reason="Travel to the selected Auto Travel destination for remaining Merchant Rules work.",
                )
            )
        entries.extend(
            replace(entry)
            for entry in destination_plan.entries
            if str(entry.merchant_type) != MERCHANT_TYPE_CONSUMABLE_CRAFTER
        )

        result = self._get_plan_factory()(
            entries=entries,
            supported_map=True,
            supported_reason=(
                f"Multi-stop preview: craft Consumable Crafter targets at {embark_name}"
                + (f", then run remaining work at {destination_name}." if destination_has_work else " and stop there.")
            ),
            coords=coords,
            multi_stop_route=True,
            multi_stop_consumable_outpost_id=self._read_embark_id(),
            multi_stop_consumable_outpost_name=embark_name,
            multi_stop_destination_outpost_id=safe_destination_id if destination_has_work else 0,
            multi_stop_destination_outpost_name=destination_name if destination_has_work else "",
            merchant_stock_buys=list(destination_plan.merchant_stock_buys),
            material_buys=list(destination_plan.material_buys),
            rune_trader_buys=list(destination_plan.rune_trader_buys),
            scroll_trader_buys=list(destination_plan.scroll_trader_buys),
            consumable_crafter_buys=list(embark_plan.consumable_crafter_buys),
            material_sales=list(destination_plan.material_sales),
            storage_transfers=list(destination_plan.storage_transfers),
            cleanup_transfers=list(destination_plan.cleanup_transfers),
            identify_claimed_item_ids=list(destination_plan.identify_claimed_item_ids),
            identify_item_ids=list(destination_plan.identify_item_ids),
            salvage_item_ids=list(destination_plan.salvage_item_ids),
            salvage_specific_upgrade_owners=dict(destination_plan.salvage_specific_upgrade_owners),
            destroy_actions=list(destination_plan.destroy_actions),
            destroy_item_ids=list(destination_plan.destroy_item_ids),
            merchant_sell_item_ids=list(destination_plan.merchant_sell_item_ids),
            rune_trader_sales=list(destination_plan.rune_trader_sales),
            storage_plan_state=storage_plan_state,
            storage_exact=bool(
                embark_plan.storage_exact and (destination_plan.storage_exact or not destination_has_work)
            ),
            inventory_snapshot_captured=bool(
                embark_plan.inventory_snapshot_captured or destination_plan.inventory_snapshot_captured
            ),
            inventory_model_counts=dict(embark_plan.inventory_model_counts or destination_plan.inventory_model_counts),
            inventory_item_count=max(int(embark_plan.inventory_item_count), int(destination_plan.inventory_item_count)),
            xunlai_first_merchant_stock_targets=dict(destination_plan.xunlai_first_merchant_stock_targets),
            xunlai_first_storage_scan_reliable=bool(destination_plan.xunlai_first_storage_scan_reliable),
            has_actions=bool(embark_plan.has_actions or destination_plan.has_actions),
        )
        return result

    def plan_has_authorized_early_kit_source(
        self,
        plan: PlanResult,
        model_ids: set[int],
    ) -> bool:
        if any(
            max(0, int(merchant_buy.model_id)) in model_ids
            and max(0, int(merchant_buy.quantity)) > 0
            and str(getattr(merchant_buy.cleanup, "rule_kind", "")) == BUY_KIND_MERCHANT_STOCK
            for merchant_buy in plan.merchant_stock_buys
        ):
            return True
        if any(
            str(transfer.direction) == STORAGE_TRANSFER_WITHDRAW
            and bool(transfer.xunlai_first_merchant_stock)
            and max(0, int(transfer.model_id)) in model_ids
            and max(0, int(transfer.quantity)) > 0
            for transfer in plan.storage_transfers
        ):
            return True
        if not plan.storage_exact and any(
            max(0, int(model_id)) in model_ids for model_id in plan.xunlai_first_merchant_stock_targets
        ):
            return True
        return False

    def annotate_early_kit_preview(self, plan: PlanResult) -> None:
        identification_models = set(self._get_early_kit_models()("identification"))
        normal_salvage_models = set(self._get_early_kit_models()("normal_salvage"))
        upgrade_salvage_models = set(self._get_early_kit_models()("upgrade_salvage"))
        identification_source = self.plan_has_authorized_early_kit_source(plan, identification_models)
        normal_source = self.plan_has_authorized_early_kit_source(plan, normal_salvage_models)
        upgrade_source = self.plan_has_authorized_early_kit_source(plan, upgrade_salvage_models)

        for entry in plan.entries:
            if (
                str(entry.action_type) == "identify"
                and str(entry.state) == PLAN_STATE_SKIPPED
                and str(entry.reason) == "No ID kit found."
                and identification_source
            ):
                entry.state = PLAN_STATE_CONDITIONAL
                entry.reason = "Identify after acquiring the configured Identification Kit."
                entry.status_hint = self._read_live_check_status()
                continue
            if str(entry.action_type) != "salvage" or str(entry.state) != PLAN_STATE_SKIPPED:
                continue
            if "no normal salvage kit" in str(entry.reason).lower() and normal_source:
                entry.state = PLAN_STATE_CONDITIONAL
                entry.reason = "Salvage after acquiring the configured normal Salvage Kit."
                entry.status_hint = self._read_live_check_status()
            elif "no upgrade salvage kit" in str(entry.reason).lower() and upgrade_source:
                entry.state = PLAN_STATE_CONDITIONAL
                entry.reason = "Salvage after acquiring the configured Expert or Superior Salvage Kit."
                entry.status_hint = self._read_live_check_status()

    def has_enabled_rune_buy_rules(self) -> bool:
        for raw_rule in self._read_buy_rules():
            rule = self._normalizers.get_buy_rule()(raw_rule)
            if rule is None or not rule.enabled or rule.kind != BUY_KIND_RUNE_TRADER_TARGET:
                continue
            if self._normalizers.get_rune_trader_targets()(rule.rune_targets):
                return True
        return False

    def has_enabled_scroll_trader_buy_rules(self) -> bool:
        for raw_rule in self._read_buy_rules():
            rule = self._normalizers.get_buy_rule()(raw_rule)
            if rule is None or not rule.enabled:
                continue
            if rule.kind == BUY_KIND_SCROLL_TRADER_TARGET:
                if any(
                    self._normalizers.get_scroll_stock()(target.model_id)
                    for target in self._normalizers.get_merchant_stock_targets()(rule.merchant_stock_targets)
                ):
                    return True
            elif rule.kind == BUY_KIND_MERCHANT_STOCK:
                if any(
                    self._normalizers.get_scroll_stock()(target.model_id)
                    for target in self._normalizers.get_merchant_stock_targets()(rule.merchant_stock_targets)
                ):
                    return True
        return False

    def has_enabled_consumable_crafter_buy_rules(self) -> bool:
        for raw_rule in self._read_buy_rules():
            rule = self._normalizers.get_buy_rule()(raw_rule)
            if rule is None or not rule.enabled or rule.kind != BUY_KIND_CONSUMABLE_CRAFTER_TARGET:
                continue
            if any(
                int(target.model_id) in self._read_recipes()
                for target in self._normalizers.get_merchant_stock_targets()(rule.merchant_stock_targets)
            ):
                return True
        return False

    def has_enabled_rules_excluding_consumable_crafters(self) -> bool:
        return bool(
            self._read_identify_planner().should_identify_before_execute()
            or any(
                bool(rule.enabled)
                and (normalized_rule := self._normalizers.get_buy_rule()(rule)) is not None
                and normalized_rule.kind != BUY_KIND_CONSUMABLE_CRAFTER_TARGET
                for rule in self._read_buy_rules()
            )
            or any(bool(rule.enabled) for rule in self._read_sell_rules())
            or self._read_salvage_planner().has_enabled_salvage_settings()
            or any(bool(rule.enabled) for rule in self._read_destroy_rules())
            or self.has_cleanup_sources()
        )

    def get_buy_rules_excluding_consumable_crafters(self) -> list[BuyRule]:
        filtered_rules: list[BuyRule] = []
        for raw_rule in self._read_buy_rules():
            rule = self._normalizers.get_buy_rule()(raw_rule)
            if rule is None or rule.kind == BUY_KIND_CONSUMABLE_CRAFTER_TARGET:
                continue
            filtered_rules.append(rule)
        return filtered_rules

    def has_cleanup_sources(self) -> bool:
        return bool(
            self._read_cleanup_planner().get_effective_cleanup_targets()
            or self._read_cleanup_planner().get_effective_cleanup_protection_sources()
        )

    def has_enabled_rules(self) -> bool:
        return (
            self._read_identify_planner().should_identify_before_execute()
            or any(bool(rule.enabled) for rule in self._read_buy_rules())
            or any(bool(rule.enabled) for rule in self._read_sell_rules())
            or self._read_salvage_planner().has_enabled_salvage_settings()
            or any(bool(rule.enabled) for rule in self._read_destroy_rules())
            or self.has_cleanup_sources()
        )

    def collect_enabled_sell_rules(self) -> list[tuple[int, SellRule]]:
        enabled_sell_rules: list[tuple[int, SellRule]] = []
        seen_rule_ids: set[str] = set()
        for rule_index, raw_sell_rule in enumerate(self._read_sell_rules()):
            sell_rule = self._normalizers.get_sell_rule()(raw_sell_rule)
            if sell_rule is None or not sell_rule.enabled:
                continue
            sell_rule.rule_id = self._normalizers.get_unique_rule_id()(
                sell_rule.rule_id,
                seen_ids=seen_rule_ids,
                prefix="sell",
                fallback_seed=f"{rule_index}:{sell_rule.kind}:{sell_rule.name}",
            )
            enabled_sell_rules.append((rule_index, sell_rule))
        return enabled_sell_rules

    def collect_enabled_xunlai_sell_rules(
        self,
        enabled_sell_rules: list[tuple[int, SellRule]] | None = None,
    ) -> list[tuple[int, SellRule]]:
        source_rules = self.collect_enabled_sell_rules() if enabled_sell_rules is None else enabled_sell_rules
        return [
            (rule_index, sell_rule)
            for rule_index, sell_rule in source_rules
            if bool(getattr(sell_rule, "sell_from_xunlai", False))
        ]

    def has_enabled_xunlai_sell_rules(self) -> bool:
        return bool(self.collect_enabled_xunlai_sell_rules())

    def has_ready_xunlai_sell_rules(
        self,
        enabled_sell_rules: list[tuple[int, SellRule]] | None = None,
    ) -> bool:
        for _rule_index, rule in self.collect_enabled_xunlai_sell_rules(enabled_sell_rules):
            if rule.kind in (SELL_KIND_COMMON_MATERIALS, SELL_KIND_EXPLICIT_MODELS):
                if self._normalizers.get_whitelist_targets()(getattr(rule, "whitelist_targets", [])):
                    return True
            elif rule.kind == SELL_KIND_RUNE_TRADER_TARGET:
                if self._normalizers.get_rune_sell_targets()(getattr(rule, "rune_sell_targets", [])):
                    return True
            elif rule.kind in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
                if any(bool(value) for value in getattr(rule, "rarities", {}).values()):
                    return True
        return False

    def has_enabled_xunlai_first_merchant_stock_targets(self) -> bool:
        return bool(self._read_buy_planner().get_configured_xunlai_first_keep_by_model())

    def plan_xunlai_sell_withdrawals(
        self,
        enabled_xunlai_rules: list[tuple[int, SellRule]],
        current_items: list["InventoryItemInfo"],
        regular_storage_items: list["InventoryItemInfo"],
        material_storage_items: list["InventoryItemInfo"],
        coords: dict[str, tuple[float, float] | None],
        *,
        protected_preview_entries: list[ExecutionPlanEntry] | None = None,
    ) -> tuple[list[PlannedStorageTransfer], list[SellRule]]:
        """Plan Xunlai withdrawals while reserving keep counts across overlapping sale rules.

        Equipment protections and unsafe storage types produce visible protected entries rather
        than withdrawal actions.
        """

        all_enabled_sell_rules = self.collect_enabled_sell_rules()
        return self._read_sale_planner().plan_xunlai_withdrawals(
            enabled_xunlai_rules,
            current_items,
            regular_storage_items,
            material_storage_items,
            coords,
            all_enabled_sell_rules=all_enabled_sell_rules,
            policy=self._read_policy(),
            protected_preview_entries=protected_preview_entries,
        )

    def build_plan(
        self,
        *,
        execution_context: PurchaseRequestView | None = None,
        cleanup_only: bool = False,
        projected_preview: bool = False,
        ignore_travel_target: bool = False,
        projected_target_override_outpost_id: int = 0,
        allow_consumable_multi_stop: bool = True,
        consumable_crafter_only: bool = False,
        exclude_consumable_crafter: bool = False,
        buy_action_rule_kinds: set[str] | None = None,
        sell_action_rule_kinds: set[str] | None = None,
        supported_context_override: tuple[bool, str, dict[str, tuple[float, float] | None]] | None = None,
        bypass_xunlai_first: bool = False,
    ) -> PlanResult:
        """Build the complete preview plan without performing live merchant actions.

        Planning snapshots inventory, applies rule precedence and hard protections, models
        storage certainty and travel services, and records conditional or blocked work. The
        resulting plan is intent only; every execution phase revalidates its live inputs.
        """

        started_at = self._get_clock()()
        projected_target_outpost_id = 0
        projected_target_outpost_name = ""
        projected_destination_context = False
        if not cleanup_only:
            target_outpost_id = (
                0
                if ignore_travel_target
                else (max(0, int(self._read_target_outpost())) if self._read_auto_travel() else 0)
            )
            current_map_id = int(self._get_map_id()() or 0)
            if projected_preview:
                if (
                    allow_consumable_multi_stop
                    and not consumable_crafter_only
                    and not exclude_consumable_crafter
                    and self.should_use_consumable_crafter_multi_stop_route()
                ):
                    target_outpost_id, _target_outpost_name = self.get_consumable_crafter_multi_stop_target()
                    multi_stop_plan = self.build_consumable_crafter_multi_stop_preview(
                        target_outpost_id,
                        execution_context=execution_context,
                    )
                    self._get_plan_summary()("Plan built", multi_stop_plan)
                    self.last_plan_build_duration_ms = max(0.0, (self._get_clock()() - started_at) * 1000.0)
                    return multi_stop_plan
                projected_target_override = max(
                    0, self._normalizers.get_safe_int()(projected_target_override_outpost_id, 0)
                )
                if projected_target_override > 0:
                    projected_target_outpost_id = projected_target_override
                    projected_target_outpost_name = self._get_outpost_name()(projected_target_override)
                    if projected_target_override == self._read_embark_id():
                        projected_target_outpost_name = self._get_embark_name()()
                else:
                    projected_target_outpost_id, projected_target_outpost_name = self.get_preview_projection_target()
                projected_destination_context = projected_target_outpost_id > 0 and bool(projected_target_outpost_name)
            if (
                not projected_destination_context
                and target_outpost_id > 0
                and not self._get_target_reached()(target_outpost_id, current_map_id)
            ):
                travel_plan = self.build_travel_preview(target_outpost_id)
                self._get_plan_summary()("Plan built", travel_plan)
                self.last_plan_build_duration_ms = max(0.0, (self._get_clock()() - started_at) * 1000.0)
                return travel_plan

        if projected_destination_context:
            supported_map, supported_reason, coords = self.get_projected_supported_context(projected_target_outpost_id)
        elif supported_context_override is not None:
            supported_map, supported_reason, coords = supported_context_override
        else:
            supported_map, supported_reason, coords = self._get_supported_context()(passive=bool(cleanup_only))
        plan = self._get_plan_factory()(
            supported_map=supported_map,
            supported_reason=supported_reason,
            coords=coords,
        )
        if consumable_crafter_only:
            has_enabled_rules = self.has_enabled_consumable_crafter_buy_rules()
        elif exclude_consumable_crafter:
            has_enabled_rules = self.has_enabled_rules_excluding_consumable_crafters()
        else:
            has_enabled_rules = self.has_enabled_rules()
        has_request_stock_targets = bool(
            not cleanup_only
            and not consumable_crafter_only
            and (buy_action_rule_kinds is None or BUY_KIND_MERCHANT_STOCK in buy_action_rule_kinds)
            and execution_context is not None
            and any(
                int(target.model_id) > 0 and int(target.target_count) > 0
                for target in execution_context.merchant_stock_targets
            )
        )
        if not has_enabled_rules and not has_request_stock_targets:
            self._get_diagnostic()(
                "Plan build skipped inventory snapshot because no buy, sell, salvage, destroy, or cleanup rules "
                "are enabled and no request-scoped Merchant Stock targets apply."
            )
            self._get_plan_summary()("Plan built", plan)
            self.last_plan_build_duration_ms = max(0.0, (self._get_clock()() - started_at) * 1000.0)
            return plan

        items = self._get_inventory_items()()
        if bool(self._read_reservation_active()):
            reserved_item_ids = set(self._read_reserved_item_ids() or set())
            if reserved_item_ids:
                items = [item for item in items if int(item.item_id) not in reserved_item_ids]
        model_counts = get_inventory_model_counts(items)
        plan.inventory_snapshot_captured = True
        plan.inventory_model_counts = dict(model_counts)
        plan.inventory_item_count = len(items)
        storage_context_ready = projected_destination_context or self._get_local_storage_ready()()
        storage_open = self._get_storage_open()()
        storage_items: list["InventoryItemInfo"] = []
        xunlai_sell_material_storage_items: list["InventoryItemInfo"] = []
        enabled_sell_rules = [] if consumable_crafter_only else self.collect_enabled_sell_rules()
        sell_action_rules = (
            enabled_sell_rules
            if sell_action_rule_kinds is None
            else [(rule_index, rule) for rule_index, rule in enabled_sell_rules if rule.kind in sell_action_rule_kinds]
        )
        enabled_xunlai_sell_action_rules = self.collect_enabled_xunlai_sell_rules(sell_action_rules)
        needs_rune_storage_context = bool(not consumable_crafter_only and self.has_enabled_rune_buy_rules())
        needs_consumable_storage_context = bool(
            not exclude_consumable_crafter and self.has_enabled_consumable_crafter_buy_rules()
        )
        needs_xunlai_sell_storage_context = bool(
            not cleanup_only and not consumable_crafter_only and self.has_ready_xunlai_sell_rules(sell_action_rules)
        )
        needs_xunlai_first_storage_context = bool(
            not cleanup_only
            and not consumable_crafter_only
            and not bypass_xunlai_first
            and (buy_action_rule_kinds is None or BUY_KIND_MERCHANT_STOCK in buy_action_rule_kinds)
            and self.has_enabled_xunlai_first_merchant_stock_targets()
        )
        if (
            needs_rune_storage_context
            or needs_consumable_storage_context
            or needs_xunlai_sell_storage_context
            or needs_xunlai_first_storage_context
        ):
            if storage_open:
                if needs_xunlai_first_storage_context:
                    storage_items, plan.xunlai_first_storage_scan_reliable = self._get_reliable_storage_items()()
                else:
                    storage_items = self._get_storage_items()()
                if needs_xunlai_sell_storage_context:
                    include_xunlai_material_storage = any(
                        bool(getattr(rule, "include_material_storage", False))
                        and self._normalizers.get_material_storage_permission()(rule)
                        for _rule_index, rule in enabled_xunlai_sell_action_rules
                    )
                    if include_xunlai_material_storage:
                        xunlai_sell_material_storage_items = self._get_material_storage_items()()
                plan.storage_plan_state = STORAGE_PLAN_STATE_EXACT_READY
                plan.storage_exact = True
            else:
                plan.storage_plan_state = STORAGE_PLAN_STATE_NEEDS_EXACT_SCAN
                plan.storage_exact = False

        enabled_destroy_rules = (
            [] if consumable_crafter_only else self._read_destroy_planner().collect_enabled_destroy_rules()
        )
        claimed_item_ids: set[int] = set()
        if not cleanup_only and not consumable_crafter_only:
            self._read_identify_planner().plan_identify_actions(plan, items, claimed_item_ids)
        if not consumable_crafter_only:
            self._read_destroy_planner().plan_destroy_actions(
                plan, items, enabled_destroy_rules, enabled_sell_rules, claimed_item_ids
            )
        if not cleanup_only and not consumable_crafter_only:
            self._read_salvage_planner().plan_salvage_actions(plan, items, enabled_sell_rules, claimed_item_ids)
        self._read_sale_planner().allocate_inventory_sales(
            plan,
            items,
            enabled_sell_rules,
            sell_action_rules,
            claimed_item_ids,
            coords,
            storage_items,
            xunlai_sell_material_storage_items,
            policy=self._read_policy(),
            consumable_crafter_only=consumable_crafter_only,
            supported_map=supported_map,
            storage_context_ready=storage_context_ready,
            supported_reason=supported_reason,
        )

        has_xunlai_sell_withdrawals = False
        if needs_xunlai_sell_storage_context:
            xunlai_sell_transfers: list[PlannedStorageTransfer] = []
            xunlai_sell_protected_preview_entries: list[ExecutionPlanEntry] = []
            include_material_storage = any(
                bool(getattr(rule, "include_material_storage", False))
                and self._normalizers.get_material_storage_permission()(rule)
                for _rule_index, rule in enabled_xunlai_sell_action_rules
            )
            source_detail = (
                "regular Xunlai item panes and Material Storage"
                if include_material_storage
                else "regular Xunlai item panes"
            )
            if storage_open:
                xunlai_sell_transfers, _adjusted_rules = self.plan_xunlai_sell_withdrawals(
                    enabled_xunlai_sell_action_rules,
                    items,
                    storage_items,
                    xunlai_sell_material_storage_items,
                    coords,
                    protected_preview_entries=xunlai_sell_protected_preview_entries,
                )
                self._get_diagnostic()(
                    f"Xunlai sell preview: enabled_rules={len(enabled_xunlai_sell_action_rules)} "
                    f"inventory_items={len(items)} regular_storage_items={len(storage_items)} "
                    f"material_storage_items={len(xunlai_sell_material_storage_items)} "
                    f"include_material_storage={include_material_storage} transfers={len(xunlai_sell_transfers)} "
                    f"quantity={sum(max(0, int(transfer.quantity)) for transfer in xunlai_sell_transfers)} "
                    f"protected_skips={len(xunlai_sell_protected_preview_entries)}"
                )
            if xunlai_sell_transfers:
                has_xunlai_sell_withdrawals = True
                plan.entries.append(
                    self._get_entry_factory()(
                        "sell",
                        MERCHANT_TYPE_STORAGE,
                        "Sell from Xunlai too",
                        sum(max(0, int(transfer.quantity)) for transfer in xunlai_sell_transfers),
                        PLAN_STATE_WILL_EXECUTE if storage_open else PLAN_STATE_CONDITIONAL,
                        (
                            f"Move matching item stacks from {source_detail} to inventory, then sell them under "
                            "the enabled Sell from Xunlai rules."
                        ),
                    )
                )
            elif not storage_open:
                plan.entries.append(
                    self._get_entry_factory()(
                        "sell",
                        MERCHANT_TYPE_STORAGE,
                        "Sell from Xunlai too",
                        0,
                        PLAN_STATE_CONDITIONAL,
                        (
                            "Xunlai Storage has not been scanned. Use Open Xunlai + Refresh to confirm "
                            f"matching item stacks in {source_detail}."
                        ),
                    )
                )
            if xunlai_sell_protected_preview_entries:
                plan.entries.extend(xunlai_sell_protected_preview_entries)

        sim_model_counts = build_simulated_model_counts(items, plan)
        sim_inventory_items = self._items_after_pre_buy(items, plan)
        pre_buy_model_counts = dict(sim_model_counts)
        self._read_buy_planner().plan_buy_actions(
            plan,
            sim_model_counts,
            execution_context=execution_context,
            sim_inventory_items=sim_inventory_items,
            storage_items=storage_items,
            consumable_crafter_only=consumable_crafter_only,
            exclude_consumable_crafter=exclude_consumable_crafter,
            allowed_rule_kinds=buy_action_rule_kinds,
            bypass_xunlai_first=bypass_xunlai_first,
        )
        self._read_buy_planner().plan_consumable_crafter_bag_space_warning(
            plan,
            inventory_model_counts=pre_buy_model_counts,
        )
        if not consumable_crafter_only:
            self._read_cleanup_planner().plan_cleanup_actions(
                plan,
                sim_inventory_items,
                enabled_sell_rules,
                storage_open=storage_open,
                storage_context_available=storage_context_ready,
            )
        if not cleanup_only and not consumable_crafter_only:
            self.annotate_early_kit_preview(plan)
        if projected_destination_context:
            self.apply_projected_preview_post_processing(plan, projected_target_outpost_name)
        plan.has_actions = bool(
            plan.identify_item_ids
            or plan.salvage_item_ids
            or plan.destroy_actions
            or plan.destroy_item_ids
            or plan.merchant_stock_buys
            or plan.material_buys
            or plan.material_sales
            or plan.merchant_sell_item_ids
            or plan.rune_trader_sales
            or plan.rune_trader_buys
            or plan.scroll_trader_buys
            or plan.consumable_crafter_buys
            or plan.storage_transfers
            or plan.cleanup_transfers
            or has_xunlai_sell_withdrawals
            or plan_needs_exact_storage_scan(plan)
        )
        self._get_plan_summary()("Plan built", plan)
        self.last_plan_build_duration_ms = max(0.0, (self._get_clock()() - started_at) * 1000.0)
        return plan

    def _items_after_pre_buy(self, items: list["InventoryItemInfo"], plan: PlanResult) -> list["InventoryItemInfo"]:
        return get_items_after_planned_pre_buy_actions(
            items, plan, quantity_reader=lambda item_id: self._get_quantity()(item_id)
        )
