"""Canonical plans, projections, assessment and supplied-evidence sale allocation.

The widget retains acquisition, overall phase order, non-sale phase construction,
preview aggregation, publication and live execution. Protection interpretation
remains with the supplied current policy.
"""

from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import TYPE_CHECKING
from typing import TypedDict
from typing import TypeGuard

from Sources.icefox.MerchantRules.configuration import AFTER_PURCHASE_KEEP
from Sources.icefox.MerchantRules.configuration import ALL_CRAFTING_MATERIAL_MODEL_IDS
from Sources.icefox.MerchantRules.configuration import COMMON_CRAFTING_MATERIAL_MODEL_IDS
from Sources.icefox.MerchantRules.configuration import MATERIAL_BATCH_SIZE
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_CONSUMABLE_CRAFTER
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_INVENTORY
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_MATERIALS
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_MERCHANT
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_RUNE_TRADER
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_STORAGE
from Sources.icefox.MerchantRules.configuration import MERCHANT_TYPE_TRAVEL
from Sources.icefox.MerchantRules.configuration import RARE_CRAFTING_MATERIAL_MODEL_IDS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_ARMOR
from Sources.icefox.MerchantRules.configuration import SELL_KIND_COMMON_MATERIALS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_EXPLICIT_MODELS
from Sources.icefox.MerchantRules.configuration import SELL_KIND_RUNE_TRADER_TARGET
from Sources.icefox.MerchantRules.configuration import SELL_KIND_WEAPONS
from Sources.icefox.MerchantRules.configuration import RuneSellTarget
from Sources.icefox.MerchantRules.configuration import SalvageRule
from Sources.icefox.MerchantRules.configuration import SellRule
from Sources.icefox.MerchantRules.configuration import WhitelistTarget
from Sources.icefox.MerchantRules.configuration import get_whitelist_target_model_ids
from Sources.icefox.MerchantRules.configuration import normalize_rule_id
from Sources.icefox.MerchantRules.configuration import normalize_rune_identifier
from Sources.icefox.MerchantRules.configuration import normalize_rune_sell_targets
from Sources.icefox.MerchantRules.configuration import normalize_whitelist_targets
from Sources.icefox.MerchantRules.configuration import sell_rule_can_include_material_storage
from Sources.icefox.MerchantRules.item_values import safe_int
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_NO_MATCH
from Sources.icefox.MerchantRules.preview_status import PREVIEW_STATUS_PROTECTED

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
