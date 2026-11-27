"""Coordinate admitted Xunlai withdrawals, replanning, and resale against live storage and inventory."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.configuration import SellRule
    from Sources.icefox.MerchantRules.inventory_evidence import InventoryItemInfo
    from Sources.icefox.MerchantRules.planning import PlannedMaterialSale
    from Sources.icefox.MerchantRules.planning import PlannedStorageTransfer
    from Sources.icefox.MerchantRules.planning import PlannedTraderSale
    from Sources.icefox.MerchantRules.planning import PlanResult

type _Steps[T] = Generator[object, None, T]
type _Get[T] = Callable[[], T]
type _Coords = tuple[float, float]
type _Scan = Callable[[], list[InventoryItemInfo]]
type _WithdrawalPlan = Callable[
    [
        list[tuple[int, SellRule]],
        list[InventoryItemInfo],
        list[InventoryItemInfo],
        list[InventoryItemInfo],
        dict[str, _Coords | None],
    ],
    tuple[list[PlannedStorageTransfer], list[SellRule]],
]


class _Outcome(Protocol):
    label: str
    timeout_failures: int
    load_failures: int
    depleted: int

    @property
    def completed(self) -> int: ...


class _Phase[Arg, O](Protocol):
    def __call__(self, arg: Arg, /, *, phase_label: str) -> _Steps[O]: ...


class _TraderSale[Row, O](Protocol):
    def __call__(self, coords: _Coords, rows: list[Row], /, *, phase_label: str) -> _Steps[O]: ...


@dataclass(frozen=True)
class XunlaiSaleIO[O: _Outcome]:
    """Resolve each widget operation at the original point of use, including after a yield."""

    get_inventory: _Get[_Scan]
    get_regular_storage: _Get[_Scan]
    get_material_storage: _Get[_Scan]
    get_material_permission: _Get[Callable[[SellRule], bool]]
    get_withdrawal_plan: _Get[_WithdrawalPlan]
    get_transfers: _Get[_Phase[list[PlannedStorageTransfer], O]]
    get_subplan: _Get[Callable[[list[SellRule]], PlanResult]]
    get_resale: _Get[_Phase[PlanResult, O]]
    get_material_sales: _Get[_TraderSale[PlannedMaterialSale, O]]
    get_merchant_sales: _Get[Callable[[_Coords | None, list[int]], _Steps[O]]]
    get_rune_sales: _Get[_TraderSale[PlannedTraderSale, O]]
    get_merge: _Get[Callable[[O, O], None]]
    get_debug: _Get[Callable[[str], None]]
    get_wait: _Get[Callable[[int], _Steps[None]]]
    materials_kind: _Get[str]
    rare_materials_kind: _Get[str]
    merchant_kind: _Get[str]
    rune_kind: _Get[str]


def pre_pull[O: _Outcome](
    plan: PlanResult, enabled_rules: list[tuple[int, SellRule]], *, counts: O, io: XunlaiSaleIO[O]
) -> _Steps[None]:
    current_items = io.get_inventory()()
    regular_storage_items = io.get_regular_storage()()
    include_material_storage = any(
        bool(getattr(rule, "include_material_storage", False)) and io.get_material_permission()(rule)
        for _rule_index, rule in enabled_rules
    )
    material_storage_items = io.get_material_storage()() if include_material_storage else []
    transfers, _adjusted_rules = io.get_withdrawal_plan()(
        enabled_rules,
        current_items,
        regular_storage_items,
        material_storage_items,
        plan.coords,
    )
    io.get_debug()(
        f"Xunlai sell pre-pull: enabled_rules={len(enabled_rules)} "
        f"inventory_items={len(current_items)} regular_storage_items={len(regular_storage_items)} "
        f"material_storage_items={len(material_storage_items)} include_material_storage={include_material_storage} "
        f"transfers={len(transfers)} quantity={sum(max(0, int(transfer.quantity)) for transfer in transfers)}"
    )
    if not transfers:
        return

    transfer_outcome = yield from io.get_transfers()(
        transfers,
        phase_label="Xunlai sell pre-pull",
    )
    io.get_merge()(counts, transfer_outcome)


def recover[O: _Outcome](
    plan: PlanResult, enabled_rules: list[tuple[int, SellRule]], *, counts: O, io: XunlaiSaleIO[O]
) -> _Steps[None]:
    max_passes = 40
    for pass_index in range(max_passes):
        current_items = io.get_inventory()()
        regular_storage_items = io.get_regular_storage()()
        include_material_storage = any(
            bool(getattr(rule, "include_material_storage", False)) and io.get_material_permission()(rule)
            for _rule_index, rule in enabled_rules
        )
        material_storage_items = io.get_material_storage()() if include_material_storage else []
        io.get_debug()(
            f"Xunlai sell pass {pass_index + 1}: enabled_rules={len(enabled_rules)} "
            f"inventory_items={len(current_items)} regular_storage_items={len(regular_storage_items)} "
            f"material_storage_items={len(material_storage_items)} include_material_storage={include_material_storage}"
        )
        transfers, adjusted_rules = io.get_withdrawal_plan()(
            enabled_rules,
            current_items,
            regular_storage_items,
            material_storage_items,
            plan.coords,
        )
        if not transfers or not adjusted_rules:
            io.get_debug()(
                f"Xunlai sell pass {pass_index + 1}: no withdrawable matching storage stacks "
                f"(transfers={len(transfers)} adjusted_rules={len(adjusted_rules)})."
            )
            break

        io.get_debug()(
            f"Xunlai sell pass {pass_index + 1}: transfers={len(transfers)} "
            f"quantity={sum(max(0, int(transfer.quantity)) for transfer in transfers)} "
            f"rules={len(adjusted_rules)}"
        )
        transfer_outcome = yield from io.get_transfers()(
            transfers,
            phase_label="Xunlai sell withdraws",
        )
        counts.timeout_failures += max(0, int(transfer_outcome.timeout_failures))
        counts.load_failures += max(0, int(transfer_outcome.load_failures))
        counts.depleted += max(0, int(transfer_outcome.depleted))
        if transfer_outcome.completed <= 0:
            break

        yield from io.get_wait()(150)
        sell_plan = io.get_subplan()(adjusted_rules)
        sell_outcome = yield from io.get_resale()(
            sell_plan,
            phase_label="Xunlai sells",
        )
        io.get_merge()(counts, sell_outcome)
        if sell_outcome.completed <= 0:
            break
        yield from io.get_wait()(100)


def sell_plan[O: _Outcome](plan: PlanResult, *, phase_label: str, counts: O, io: XunlaiSaleIO[O]) -> _Steps[None]:
    material_coords = plan.coords.get(io.materials_kind())
    common_material_sales = [sale for sale in plan.material_sales if sale.merchant_type == io.materials_kind()]
    if material_coords and common_material_sales:
        material_outcome = yield from io.get_material_sales()(
            material_coords,
            common_material_sales,
            phase_label=f"{phase_label} material sales",
        )
        io.get_merge()(counts, material_outcome)

    rare_material_coords = plan.coords.get(io.rare_materials_kind())
    rare_material_sales = [sale for sale in plan.material_sales if sale.merchant_type == io.rare_materials_kind()]
    if rare_material_coords and rare_material_sales:
        rare_outcome = yield from io.get_material_sales()(
            rare_material_coords,
            rare_material_sales,
            phase_label=f"{phase_label} rare material sales",
        )
        io.get_merge()(counts, rare_outcome)

    merchant_outcome = yield from io.get_merchant_sales()(
        plan.coords.get(io.merchant_kind()),
        plan.merchant_sell_item_ids,
    )
    merchant_outcome.label = f"{phase_label} merchant sales"
    io.get_merge()(counts, merchant_outcome)

    rune_trader_coords = plan.coords.get(io.rune_kind())
    if rune_trader_coords and plan.rune_trader_sales:
        rune_outcome = yield from io.get_rune_sales()(
            rune_trader_coords,
            plan.rune_trader_sales,
            phase_label=f"{phase_label} rune trader sales",
        )
        io.get_merge()(counts, rune_outcome)
