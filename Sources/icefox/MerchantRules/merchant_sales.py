"""Execute admitted ordinary merchant sales against the caller's live inventory and outcome."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

type _Steps[T] = Generator[object, None, T]
type _Get[T] = Callable[[], T]
type _Confirmation = tuple[set[int], set[int]]


class MerchantSaleCounts(Protocol):
    completed: int
    timeout_failures: int
    depleted: int


class ManualSaleView(Protocol):
    @property
    def item_id(self) -> int: ...

    @property
    def quantity_to_sell(self) -> int: ...

    @property
    def label(self) -> str: ...


class SplitSlotView(Protocol):
    @property
    def bag_id(self) -> int: ...

    @property
    def slot(self) -> int: ...


class _TargetWait(Protocol):
    def __call__(self, item_id: int, quantity: int, /, *, timeout_ms: int, step_ms: int) -> _Steps[int]: ...


class _Drain(Protocol):
    def __call__(self, queue_name: str, /, *, timeout_ms: int, step_ms: int) -> _Steps[bool]: ...


class _Confirm(Protocol):
    def __call__(self, previous: dict[int, int], /, *, timeout_ms: int, step_ms: int) -> _Steps[_Confirmation]: ...


@dataclass(frozen=True)
class PlannedSaleIO:
    get_stack_quantities: _Get[Callable[[list[int]], dict[int, int]]]
    get_sell_items: _Get[Callable[[list[int]], _Steps[None]]]
    get_confirmation: _Get[Callable[[dict[int, int]], _Steps[_Confirmation]]]
    get_debug: _Get[Callable[[str], None]]
    warn_pending: Callable[[set[int]], None]


@dataclass(frozen=True)
class OpenSaleIO:
    get_quantity: _Get[Callable[[int], int]]
    get_empty_slot: _Get[Callable[[], SplitSlotView | None]]
    get_move: _Get[Callable[[int, int, int, int], object]]
    get_target_wait: _Get[_TargetWait]
    get_value: _Get[Callable[[int], int]]
    get_sell: _Get[Callable[[int, int], object]]
    get_drain: _Get[_Drain]
    get_confirmation: _Get[_Confirm]
    get_wait: _Get[Callable[[int], _Steps[None]]]
    get_debug: _Get[Callable[[str], None]]
    read_timeout_ms: _Get[int]


def execute_planned_merchant_sales(
    item_ids: list[int], *, counts: MerchantSaleCounts, io: PlannedSaleIO
) -> _Steps[None]:
    pre_sell_quantities = io.get_stack_quantities()(item_ids)
    sell_item_ids = list(pre_sell_quantities.keys())
    missing_item_count = max(0, len(item_ids) - len(sell_item_ids))
    if missing_item_count > 0:
        counts.depleted += missing_item_count
    if not sell_item_ids:
        io.get_debug()("Merchant sell phase skipped send because planned item ids were no longer in inventory.")
        return

    yield from io.get_sell_items()(sell_item_ids)
    confirmed_ids, pending_ids = yield from io.get_confirmation()(pre_sell_quantities)
    counts.completed = len(confirmed_ids)
    counts.timeout_failures += len(pending_ids)
    if pending_ids:
        io.warn_pending(pending_ids)
    io.get_debug()(
        f"Merchant sell phase completed: confirmed={len(confirmed_ids)} pending={len(pending_ids)} "
        f"missing_before_send={missing_item_count}"
    )


def execute_open_merchant_sales(
    sales: Sequence[ManualSaleView], *, counts: MerchantSaleCounts, io: OpenSaleIO
) -> _Steps[None]:
    for sale in sales:
        item_id = int(sale.item_id)
        current_quantity = max(0, int(io.get_quantity()(item_id)))
        if current_quantity <= 0:
            counts.depleted += 1
            continue

        requested_quantity = max(0, int(sale.quantity_to_sell))
        if requested_quantity <= 0:
            requested_quantity = current_quantity
        requested_quantity = min(requested_quantity, current_quantity)
        if requested_quantity <= 0:
            counts.depleted += 1
            continue

        if requested_quantity < current_quantity:
            split_destination = io.get_empty_slot()()
            if split_destination is None:
                counts.timeout_failures += 1
                io.get_debug()(
                    f"Manual merchant sale skipped {sale.label}: no empty slot to split {requested_quantity}/{current_quantity}."
                )
                continue
            keep_quantity = current_quantity - requested_quantity
            io.get_move()(
                item_id,
                int(split_destination.bag_id),
                int(split_destination.slot),
                keep_quantity,
            )
            updated_quantity = yield from io.get_target_wait()(
                item_id,
                requested_quantity,
                timeout_ms=io.read_timeout_ms(),
                step_ms=50,
            )
            if int(updated_quantity) != requested_quantity:
                counts.timeout_failures += 1
                io.get_debug()(
                    f"Manual merchant sale split verification failed for {sale.label}: "
                    f"expected {requested_quantity}, observed {updated_quantity}."
                )
                continue
            current_quantity = updated_quantity

        value = max(0, int(io.get_value()(item_id)))
        io.get_sell()(item_id, int(current_quantity) * value)
        yield from io.get_drain()("MERCHANT", timeout_ms=io.read_timeout_ms(), step_ms=50)
        confirmed_ids, pending_ids = yield from io.get_confirmation()(
            {item_id: int(current_quantity)},
            timeout_ms=io.read_timeout_ms(),
            step_ms=50,
        )
        if confirmed_ids and not pending_ids:
            counts.completed += 1
        else:
            counts.timeout_failures += 1
        yield from io.get_wait()(40)
