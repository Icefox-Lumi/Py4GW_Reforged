"""Reconcile storage moves against the observed source and destination quantities."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.planning import PlannedStorageTransfer

type Steps[T] = Generator[object, None, T]
type QuantityRead = Callable[[int], int]
type Delay = Callable[[int], Steps[None]]
type Debug = Callable[[str], None]
type SlotScan = Callable[[int], tuple[int, int | None, int]]
type SlotLookup = Callable[[int], int | None]
type MoveItem = Callable[[int, int, int, int], object]


class TransferCounts(Protocol):
    completed: int
    timeout_failures: int
    depleted: int


class MaterialProgress(Protocol):
    attempted: bool
    moved_quantity: int
    remaining_quantity: int
    abort_regular_fallback: bool


class MaterialStep(Protocol):
    def __call__(
        self, item_id: int, requested_quantity: int, /, *, current_quantity: int | None, planned_model_id: int
    ) -> Steps[MaterialProgress]: ...


class MaterialTest(Protocol):
    def __call__(self, item_id: int, /, *, model_id: int) -> bool: ...


class RegularMove(Protocol):
    def __call__(self, item_id: int, /, *, ammount: int) -> object: ...


class ActionDrain(Protocol):
    def __call__(self, queue_name: str, /, *, timeout_ms: int, step_ms: int) -> Steps[bool]: ...


class TargetWait(Protocol):
    def __call__(self, id: int, target: int, /, *, timeout_ms: int, step_ms: int) -> Steps[int]: ...


@dataclass(frozen=True)
class TransferIO:
    """Resolve the live widget and inventory operations anew at each point of use."""

    deposit_direction: Callable[[], str]
    withdraw_direction: Callable[[], str]
    get_scoped_quantity: Callable[[], QuantityRead]
    get_global_quantity: Callable[[], QuantityRead]
    get_model_count: Callable[[], QuantityRead]
    get_regular_deposit: Callable[[], RegularMove]
    get_regular_withdraw: Callable[[], RegularMove]
    get_action_drain: Callable[[], ActionDrain]
    get_scoped_target: Callable[[], TargetWait]
    get_global_target: Callable[[], TargetWait]
    get_model_target: Callable[[], TargetWait]
    get_delay: Callable[[], Delay]
    get_debug: Callable[[], Debug]


@dataclass(frozen=True)
class MaterialSlotIO:
    get_live_model: Callable[[], QuantityRead]
    get_classify: Callable[[], MaterialTest]
    is_known_material: Callable[[int], bool]
    get_slot_scan: Callable[[], SlotScan]
    get_slot_lookup: Callable[[], SlotLookup]
    max_stack: Callable[[], int]
    get_move_item: Callable[[], MoveItem | None]
    bag_id: Callable[[], int]
    get_scoped_quantity: Callable[[], QuantityRead]
    get_action_drain: Callable[[], ActionDrain]
    get_scoped_target: Callable[[], TargetWait]
    get_debug: Callable[[], Debug]


def execute_transfers(
    transfers: list[PlannedStorageTransfer],
    *,
    phase_label: str,
    counts: TransferCounts,
    get_material_step: Callable[[], MaterialStep],
    io: TransferIO,
) -> Steps[None]:
    for transfer in transfers:
        item_id = int(transfer.item_id)
        quantity = max(0, int(transfer.quantity))
        transfer_label = str(transfer.label or f"Item {item_id}")
        transfer_model_id = max(0, int(getattr(transfer, "model_id", 0)))
        transfer_reason = str(getattr(transfer, "reason", "") or "")
        if quantity <= 0:
            continue

        current_quantity = (
            io.get_scoped_quantity()(item_id)
            if transfer.direction == io.deposit_direction()
            else max(0, int(io.get_global_quantity()(item_id)))
        )
        if current_quantity <= 0:
            io.get_debug()(
                f"{phase_label} transfer skipped: direction={transfer.direction} label={transfer_label} "
                f"model={transfer_model_id} item_id={item_id} planned={quantity} current=0"
                + (f" reason={transfer_reason}" if transfer_reason else "")
            )
            counts.depleted += quantity
            continue
        requested_quantity = min(current_quantity, quantity)
        depleted_quantity = max(0, quantity - current_quantity)
        if requested_quantity <= 0:
            io.get_debug()(
                f"{phase_label} transfer skipped: direction={transfer.direction} label={transfer_label} "
                f"model={transfer_model_id} item_id={item_id} planned={quantity} move=0"
                + (f" reason={transfer_reason}" if transfer_reason else "")
            )
            counts.depleted += quantity
            continue

        io.get_debug()(
            f"{phase_label} transfer: direction={transfer.direction} label={transfer_label} "
            f"model={transfer_model_id} item_id={item_id} planned={quantity} current={current_quantity} move={requested_quantity}"
            + (f" reason={transfer_reason}" if transfer_reason else "")
        )

        moved = False
        before_inventory_model_count = 0
        if transfer.direction == io.withdraw_direction():
            if transfer_model_id > 0:
                try:
                    before_inventory_model_count = max(0, int(io.get_model_count()(transfer_model_id)))
                except Exception:
                    before_inventory_model_count = 0
            moved = bool(io.get_regular_withdraw()(item_id, ammount=requested_quantity))
        elif transfer.direction == io.deposit_direction():
            material_storage_result = yield from get_material_step()(
                item_id,
                requested_quantity,
                current_quantity=current_quantity,
                planned_model_id=transfer.model_id,
            )
            if material_storage_result.attempted:
                if material_storage_result.moved_quantity > 0:
                    counts.completed += int(material_storage_result.moved_quantity)
                if material_storage_result.abort_regular_fallback:
                    counts.timeout_failures += max(
                        0,
                        requested_quantity - max(0, int(material_storage_result.moved_quantity)),
                    )
                    counts.depleted += depleted_quantity
                    yield from io.get_delay()(60)
                    continue

                requested_quantity = max(0, int(material_storage_result.remaining_quantity))
                if requested_quantity <= 0:
                    counts.depleted += depleted_quantity
                    yield from io.get_delay()(60)
                    continue

                current_quantity = io.get_scoped_quantity()(item_id)
                post_material_depleted_quantity = max(0, requested_quantity - current_quantity)
                requested_quantity = min(requested_quantity, current_quantity)
                if requested_quantity <= 0:
                    counts.depleted += depleted_quantity + post_material_depleted_quantity
                    yield from io.get_delay()(60)
                    continue
                depleted_quantity += post_material_depleted_quantity

            moved = bool(io.get_regular_deposit()(item_id, ammount=requested_quantity))

        if not moved:
            io.get_debug()(
                f"{phase_label} transfer queued-noop: direction={transfer.direction} label={transfer_label} "
                f"model={transfer_model_id} item_id={item_id} requested={requested_quantity}"
                + (f" reason={transfer_reason}" if transfer_reason else "")
            )
            counts.timeout_failures += requested_quantity
            counts.depleted += depleted_quantity
            continue

        queue_cleared = yield from io.get_action_drain()("ACTION", timeout_ms=2000, step_ms=50)
        final_quantity = (
            io.get_scoped_quantity()(item_id)
            if transfer.direction == io.deposit_direction()
            else max(0, int(io.get_global_quantity()(item_id)))
        )
        moved_quantity = 0
        if transfer.direction == io.withdraw_direction() and transfer_model_id > 0:
            final_inventory_model_count = yield from io.get_model_target()(
                transfer_model_id,
                before_inventory_model_count + requested_quantity,
                timeout_ms=2000 if queue_cleared else 1000,
                step_ms=50,
            )
            moved_quantity = max(0, int(final_inventory_model_count) - before_inventory_model_count)
        elif transfer.direction == io.deposit_direction() and queue_cleared:
            expected_quantity = max(0, current_quantity - requested_quantity)
            final_quantity = yield from io.get_scoped_target()(
                item_id,
                expected_quantity,
                timeout_ms=2000,
                step_ms=50,
            )
        elif queue_cleared:
            expected_quantity = max(0, current_quantity - requested_quantity)
            final_quantity = yield from io.get_global_target()(
                item_id,
                expected_quantity,
                timeout_ms=2000,
                step_ms=50,
            )

        if moved_quantity <= 0:
            moved_quantity = max(0, current_quantity - max(0, int(final_quantity)))
        if moved_quantity > 0:
            counts.completed += moved_quantity
        shortfall = max(0, requested_quantity - moved_quantity)
        if shortfall > 0:
            counts.timeout_failures += shortfall
        counts.depleted += depleted_quantity
        io.get_debug()(
            f"{phase_label} transfer result: direction={transfer.direction} label={transfer_label} "
            f"model={transfer_model_id} item_id={item_id} moved={moved_quantity} shortfall={shortfall} "
            f"final={max(0, int(final_quantity))}" + (f" reason={transfer_reason}" if transfer_reason else "")
        )
        yield from io.get_delay()(60)


def attempt_material_slot(
    item_id: int,
    quantity: int,
    *,
    current_quantity: int | None,
    planned_model_id: int,
    result: MaterialProgress,
    io: MaterialSlotIO,
) -> Steps[None]:
    safe_planned_model_id = max(0, int(planned_model_id))
    try:
        live_model_id = max(0, int(io.get_live_model()(item_id)))
    except Exception:
        live_model_id = 0
    model_id = live_model_id if live_model_id > 0 else safe_planned_model_id
    if model_id <= 0:
        return
    if not io.get_classify()(item_id, model_id=model_id):
        if io.is_known_material(model_id):
            io.get_debug()(
                f"Material storage skipped: item_id={item_id} model={model_id} was not classified as a live material."
            )
        return

    current_storage_quantity, resolved_slot, storage_bag_size = io.get_slot_scan()(model_id)
    target_slot = resolved_slot
    if target_slot is None:
        target_slot = io.get_slot_lookup()(model_id)
    if target_slot is None:
        io.get_debug()(
            f"Material storage slot unresolved for item_id={item_id} model={model_id}; falling back to regular storage panes."
        )
        return
    if storage_bag_size > 0 and not (0 <= int(target_slot) < storage_bag_size):
        io.get_debug()(
            f"Material storage slot invalid for item_id={item_id} model={model_id}: "
            f"slot={int(target_slot)} bag_size={storage_bag_size}; falling back to regular storage panes."
        )
        return

    available_capacity = max(0, io.max_stack() - max(0, int(current_storage_quantity)))
    reported_full = available_capacity <= 0
    if reported_full:
        io.get_debug()(
            f"Material storage reported full for model={model_id}; probing known slot={int(target_slot)} before regular fallback."
        )

    source_before = max(0, int(current_quantity)) if current_quantity is not None else io.get_scoped_quantity()(item_id)
    if source_before <= 0:
        return

    material_move_quantity = min(
        quantity,
        source_before,
        available_capacity if not reported_full else quantity,
    )
    if material_move_quantity <= 0:
        return

    move_item = io.get_move_item()
    if move_item is None:
        return

    io.get_debug()(
        f"Material storage deposit attempt: item_id={item_id} model={model_id} "
        f"source={source_before} storage={current_storage_quantity} "
        f"slot={int(target_slot)} move={material_move_quantity}"
    )
    try:
        move_item(item_id, io.bag_id(), int(target_slot), int(material_move_quantity))
    except Exception as exc:
        io.get_debug()(
            f"Material storage deposit fallback: item_id={item_id} model={model_id} "
            f"move failed before queueing: {exc}"
        )
        return

    result.attempted = True
    queue_cleared = yield from io.get_action_drain()("ACTION", timeout_ms=2000, step_ms=50)
    final_quantity = io.get_scoped_quantity()(item_id)
    if queue_cleared:
        expected_quantity = max(0, source_before - material_move_quantity)
        final_quantity = yield from io.get_scoped_target()(
            item_id,
            expected_quantity,
            timeout_ms=2000,
            step_ms=50,
        )

    moved_quantity = min(material_move_quantity, max(0, source_before - max(0, int(final_quantity))))
    result.moved_quantity = moved_quantity
    result.remaining_quantity = max(0, quantity - moved_quantity)
    if moved_quantity <= 0:
        if reported_full and queue_cleared:
            io.get_debug()(
                f"Material storage reported-full probe moved nothing: item_id={item_id} model={model_id} "
                f"requested={material_move_quantity}; falling back to regular storage panes."
            )
        else:
            result.abort_regular_fallback = True
            io.get_debug()(
                f"Material storage deposit unverified: item_id={item_id} model={model_id} "
                f"requested={material_move_quantity}; regular storage fallback skipped for this pass."
            )
    else:
        io.get_debug()(
            f"Material storage deposit: item_id={item_id} model={model_id} "
            f"moved={moved_quantity} remaining={result.remaining_quantity}"
        )
