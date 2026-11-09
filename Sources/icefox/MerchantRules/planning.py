"""Canonical plan records, inventory projections and plan assessment.

Evidence acquisition, phase construction and live execution remain widget-owned.
"""

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import TYPE_CHECKING

from Sources.icefox.MerchantRules.configuration import AFTER_PURCHASE_KEEP
from Sources.icefox.MerchantRules.configuration import MATERIAL_BATCH_SIZE
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_CONSUMABLE_CRAFTER
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_INVENTORY
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_RUNE_TRADER
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_STORAGE
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_TRAVEL
from Sources.icefox.MerchantRules.configuration import SalvageRule

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.inventory_evidence import InventoryItemInfo

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
