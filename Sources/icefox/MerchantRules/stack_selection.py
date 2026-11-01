"""Select whole stacks without owning inventory eligibility or actions."""

from collections.abc import Sequence
from typing import Protocol
from typing import cast


class _StackQuantity(Protocol):
    @property
    def item_id(self) -> int: ...

    @property
    def quantity(self) -> int: ...


def choose_keep_subset(items: Sequence[_StackQuantity], keep_count: int) -> set[int]:
    """Retain the smallest reachable total at least equal to the requested keep."""
    keep_count = max(0, int(keep_count))
    if keep_count <= 0 or not items:
        return set()

    total_quantity = sum(max(1, int(item.quantity)) for item in items)
    if keep_count >= total_quantity:
        return {item.item_id for item in items}

    max_quantity = max(max(1, int(item.quantity)) for item in items)
    sum_cap = min(total_quantity, keep_count + max_quantity)

    parents: dict[int, tuple[int, int] | None] = {0: None}
    for index, item in enumerate(items):
        item_quantity = max(1, int(item.quantity))
        existing_sums = sorted(parents.keys(), reverse=True)
        for current_sum in existing_sums:
            new_sum = current_sum + item_quantity
            if new_sum > sum_cap or new_sum in parents:
                continue
            parents[new_sum] = (current_sum, index)

    candidate_sums = [value for value in parents.keys() if value >= keep_count]
    if not candidate_sums:
        return {item.item_id for item in items}

    best_sum = min(candidate_sums)
    keep_ids: set[int] = set()
    cursor = best_sum
    while cursor and parents.get(cursor) is not None:
        previous_sum, index = cast(tuple[int, int], parents[cursor])
        keep_ids.add(items[index].item_id)
        cursor = previous_sum
    return keep_ids


def choose_keep_subset_at_most(items: Sequence[_StackQuantity], keep_count: int) -> tuple[set[int], int]:
    """Retain the largest reachable whole-stack total no greater than the keep."""
    keep_count = max(0, int(keep_count))
    if keep_count <= 0 or not items:
        return set(), 0

    parents: dict[int, tuple[int, int] | None] = {0: None}
    for index, item in enumerate(items):
        item_quantity = max(1, int(item.quantity))
        existing_sums = sorted(parents.keys(), reverse=True)
        for current_sum in existing_sums:
            new_sum = current_sum + item_quantity
            if new_sum > keep_count or new_sum in parents:
                continue
            parents[new_sum] = (current_sum, index)

    best_sum = max(parents.keys())
    keep_ids: set[int] = set()
    cursor = best_sum
    while cursor and parents.get(cursor) is not None:
        previous_sum, index = cast(tuple[int, int], parents[cursor])
        keep_ids.add(items[index].item_id)
        cursor = previous_sum
    return keep_ids, best_sum
