"""Canonical plans, projections, assessment, and sale/purchase/deposit allocation.

The widget retains acquisition, phase order, other phase construction, preview
aggregation/publication, application, execution reservations and live execution.
Protection interpretation remains with the supplied current policy.
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
from Sources.icefox.MerchantRules.configuration import SELL_KIND_ARMOR
from Sources.icefox.MerchantRules.configuration import SELL_KIND_COMMON_MATERIALS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_EXPLICIT_MODELS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_RUNE_TRADER_TARGET
from Sources.icefox.MerchantRules.configuration import SELL_KIND_WEAPONS
from Sources.icefox.MerchantRules.configuration import BuyRule
from Sources.icefox.MerchantRules.configuration import CleanupProtectionSource
from Sources.icefox.MerchantRules.configuration import CleanupTarget
from Sources.icefox.MerchantRules.configuration import MerchantStockTarget
from Sources.icefox.MerchantRules.configuration import RuneSellTarget
from Sources.icefox.MerchantRules.configuration import SalvageRule
from Sources.icefox.MerchantRules.configuration import SellRule
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
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_WARNING

if TYPE_CHECKING:
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
