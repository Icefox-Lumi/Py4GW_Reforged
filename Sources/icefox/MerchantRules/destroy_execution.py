"""Execute admitted destroy actions and account for observed changes to their source stacks."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.planning import PlannedDestroyAction

type _Steps[T] = Generator[object, None, T]
type _Get[T] = Callable[[], T]


class DestroyCounts(Protocol):
    completed: int
    timeout_failures: int
    depleted: int


class SplitDestinationView(Protocol):
    @property
    def bag_id(self) -> int: ...

    @property
    def slot(self) -> int: ...


class _TargetWait(Protocol):
    def __call__(self, item_id: int, expected_quantity: int, /, *, timeout_ms: int, step_ms: int) -> _Steps[int]: ...


class _ConfirmationWait(Protocol):
    def __call__(
        self, previous_quantities: dict[int, int], /, *, timeout_ms: int, step_ms: int
    ) -> _Steps[tuple[set[int], set[int]]]: ...


@dataclass(frozen=True)
class DestroyIO:
    read_action_type: _Get[type[PlannedDestroyAction]]
    get_stack_quantities: _Get[Callable[[list[int]], dict[int, int]]]
    get_quantity: _Get[Callable[[int], int]]
    get_empty_slot: _Get[Callable[[], SplitDestinationView | None]]
    get_move: _Get[Callable[[int, int, int, int], object]]
    get_target_wait: _Get[_TargetWait]
    get_destroy: _Get[Callable[[int], object]]
    get_confirmation: _Get[_ConfirmationWait]
    get_wait: _Get[Callable[[int], _Steps[None]]]
    get_debug: _Get[Callable[[str], None]]
    read_timeout_ms: _Get[int]


def execute_destroy_actions(
    raw_actions: Sequence[PlannedDestroyAction | int],
    tracked_ids: list[int],
    *,
    counts: DestroyCounts,
    io: DestroyIO,
) -> Generator[object, None, None]:
    pre_destroy_quantities = io.get_stack_quantities()(tracked_ids)
    normalized_actions: list[PlannedDestroyAction] = []
    for raw_action in raw_actions:
        if isinstance(raw_action, io.read_action_type()):
            normalized_actions.append(raw_action)
            continue
        if TYPE_CHECKING:
            # The runtime class supplier prevents static narrowing of the legacy branch.
            assert isinstance(raw_action, int)
        safe_item_id = int(raw_action)
        previous_quantity = max(0, int(pre_destroy_quantities.get(safe_item_id, 0)))
        normalized_actions.append(
            io.read_action_type()(
                item_id=safe_item_id,
                model_id=0,
                label=f"Item {safe_item_id}",
                quantity_to_destroy=previous_quantity,
                source_quantity=previous_quantity,
            )
        )

    destroy_queue = sorted(
        normalized_actions,
        key=lambda action: (
            1 if bool(action.requires_split) else 0,
            str(action.label or "").lower(),
            int(action.item_id),
        ),
    )

    missing_item_count = max(0, len(tracked_ids) - len(pre_destroy_quantities))
    if missing_item_count > 0:
        counts.depleted += missing_item_count

    io.get_debug()(f"Destroy phase: planned_items={len(tracked_ids)} present_items={len(pre_destroy_quantities)}")
    for action in destroy_queue:
        item_id = int(action.item_id)
        previous_quantity = max(0, int(io.get_quantity()(item_id)))
        if previous_quantity <= 0:
            previous_quantity = max(0, int(pre_destroy_quantities.get(item_id, 0)))
        if previous_quantity <= 0:
            continue

        planned_destroy_quantity = max(0, int(action.quantity_to_destroy))
        planned_keep_quantity = max(0, int(action.keep_quantity))
        if planned_destroy_quantity <= 0:
            continue

        if bool(action.requires_split):
            split_destination = io.get_empty_slot()()
            if split_destination is None:
                counts.timeout_failures += 1
                io.get_debug()(
                    f"Destroy split skipped: item_id={item_id} keep={planned_keep_quantity} destroy={planned_destroy_quantity} "
                    "no empty slot was available at execution time."
                )
                continue

            expected_source_quantity = max(0, previous_quantity - planned_keep_quantity)
            io.get_move()(
                item_id,
                int(split_destination.bag_id),
                int(split_destination.slot),
                planned_keep_quantity,
            )
            updated_quantity = yield from io.get_target_wait()(
                item_id,
                expected_source_quantity,
                timeout_ms=io.read_timeout_ms(),
                step_ms=50,
            )
            if updated_quantity != expected_source_quantity or updated_quantity != planned_destroy_quantity:
                counts.timeout_failures += 1
                io.get_debug()(
                    f"Destroy split verification failed: item_id={item_id} expected={planned_destroy_quantity} "
                    f"observed={updated_quantity} keep={planned_keep_quantity}"
                )
                continue
            previous_quantity = updated_quantity

        if previous_quantity != planned_destroy_quantity:
            counts.timeout_failures += 1
            io.get_debug()(
                f"Destroy quantity mismatch: item_id={item_id} planned={planned_destroy_quantity} current={previous_quantity}"
            )
            continue

        io.get_destroy()(int(item_id))
        confirmed_item_ids, pending_item_ids = yield from io.get_confirmation()(
            {int(item_id): previous_quantity},
            timeout_ms=io.read_timeout_ms(),
            step_ms=50,
        )
        if confirmed_item_ids:
            counts.completed += 1
        else:
            counts.timeout_failures += len(pending_item_ids) or 1
        yield from io.get_wait()(40)
