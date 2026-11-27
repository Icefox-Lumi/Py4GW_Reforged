"""Execute admitted consumable crafts against current inventory, funding and vendor offers."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.gold_transactions import GoldTopUpResult
    from Sources.icefox.MerchantRules.planning import CrafterRecipeView
    from Sources.icefox.MerchantRules.planning import PlannedConsumableCraft
    from Sources.icefox.MerchantRules.planning import PurchaseTargetCleanup

type _Steps[T] = Generator[object, None, T]
type _Get[T] = Callable[[], T]
type _Ingredients = tuple[list[int], list[int], list[str]]
type _Console = Callable[[str, str, int], None]


class _Counts(Protocol):
    completed: int
    unavailable: int
    load_failures: int
    gold_blocked: int
    depleted: int
    timeout_failures: int


class _Withdraw(Protocol):
    def __call__(self, item_id: int, /, *, ammount: int) -> bool: ...


class _CountWait(Protocol):
    def __call__(self, model_id: int, expected_count: int, /, *, timeout_ms: int, step_ms: int) -> _Steps[int]: ...


class _EnsureOpen(Protocol):
    def __call__(self, *, purpose: str) -> _Steps[bool]: ...


class _Prepare(Protocol):
    def __call__(self, rows: list[PlannedConsumableCraft], /, *, vendor_name: str) -> _Steps[bool]: ...


class _Fund(Protocol):
    def __call__(self, cost: int, /, *, purpose: str) -> _Steps[GoldTopUpResult]: ...


class _TransactionWait(Protocol):
    def __call__(self, *, timeout_ms: int, step_ms: int) -> _Steps[bool]: ...


class _Cleanup(Protocol):
    def __call__(self, cleanup: PurchaseTargetCleanup, /, *, label: str) -> bool: ...


@dataclass(frozen=True)
class WithdrawIO:
    get_sources: _Get[Callable[[int], list[int]]]
    get_quantity: _Get[Callable[[int], int]]
    get_count: _Get[Callable[[int], int]]
    get_withdraw: _Get[_Withdraw]
    get_count_wait: _Get[_CountWait]
    get_debug: _Get[Callable[[str], None]]
    get_label: _Get[Callable[[int], str]]


@dataclass(frozen=True)
class PrepareIO:
    get_recipe: _Get[Callable[[int], CrafterRecipeView | None]]
    get_is_open: _Get[Callable[[], bool]]
    get_ensure_open: _Get[_EnsureOpen]
    get_count: _Get[Callable[[int], int]]
    get_material_withdraw: _Get[Callable[[int, int], _Steps[int]]]
    get_wait: _Get[Callable[[int], _Steps[None]]]
    get_label: _Get[Callable[[int], str]]
    get_console: _Get[_Console]
    read_module: _Get[str]
    read_warning: _Get[int]


@dataclass(frozen=True)
class IngredientIO:
    get_inventory_ids: _Get[Callable[[int], list[int]]]
    get_quantity: _Get[Callable[[int], int]]
    get_label: _Get[Callable[[int], str]]


@dataclass(frozen=True)
class VendorIO[R: CrafterRecipeView]:
    get_prepare: _Get[_Prepare]
    get_open: _Get[Callable[[tuple[float, float], str], _Steps[list[int]]]]
    get_model_id: _Get[Callable[[int], int]]
    get_recipe: _Get[Callable[[int], R | None]]
    get_skill_points: _Get[Callable[[], tuple[int, int]]]
    get_fund: _Get[_Fund]
    get_collect: _Get[Callable[[R], _Ingredients]]
    get_count: _Get[Callable[[int], int]]
    get_craft: _Get[Callable[[int, int, list[int], list[int]], None]]
    get_transaction_wait: _Get[_TransactionWait]
    get_count_wait: _Get[_CountWait]
    get_cleanup: _Get[_Cleanup]
    get_debug: _Get[Callable[[str], None]]
    get_console: _Get[_Console]
    read_module: _Get[str]
    read_warning: _Get[int]


def withdraw_material(model_id: int, needed_quantity: int, *, io: WithdrawIO) -> _Steps[int]:
    safe_model_id = max(0, int(model_id))
    remaining = max(0, int(needed_quantity))
    moved_total = 0
    while safe_model_id > 0 and remaining > 0:
        source_item_ids = io.get_sources()(safe_model_id)
        if not source_item_ids:
            break
        moved_this_pass = False
        for source_item_id in source_item_ids:
            try:
                source_quantity = max(0, int(io.get_quantity()(source_item_id)))
            except Exception:
                source_quantity = 0
            if source_quantity <= 0:
                continue
            requested = min(source_quantity, remaining)
            before = max(0, int(io.get_count()(safe_model_id)))
            if bool(io.get_withdraw()(source_item_id, ammount=requested)):
                after = yield from io.get_count_wait()(
                    safe_model_id,
                    before + requested,
                    timeout_ms=1800,
                    step_ms=50,
                )
                gained = max(0, int(after) - before)
                if gained <= 0:
                    io.get_debug()(
                        f"Crafting material withdraw did not reach inventory: "
                        f"{io.get_label()(safe_model_id)} requested={requested} before={before} after={after}."
                    )
                    continue
                moved_total += gained
                remaining = max(0, remaining - gained)
                moved_this_pass = True
                break
        if not moved_this_pass:
            break
    return moved_total


def prepare_materials(planned_crafts: list[PlannedConsumableCraft], *, vendor_name: str, io: PrepareIO) -> _Steps[bool]:
    required_by_model: dict[int, int] = {}
    for craft in planned_crafts:
        recipe = io.get_recipe()(craft.model_id)
        if recipe is None:
            continue
        craft_quantity = max(0, int(craft.quantity))
        if craft_quantity <= 0:
            continue
        for ingredient_model_id, ingredient_quantity in recipe.ingredients:
            required_by_model[int(ingredient_model_id)] = required_by_model.get(int(ingredient_model_id), 0) + (
                max(0, int(ingredient_quantity)) * craft_quantity
            )

    if not required_by_model:
        return True

    if not io.get_is_open()() and not (
        yield from io.get_ensure_open()(purpose=f"{vendor_name} crafting material withdrawal")
    ):
        return False

    all_ready = True
    for ingredient_model_id, required_quantity in required_by_model.items():
        inventory_quantity = max(0, int(io.get_count()(int(ingredient_model_id))))
        missing_quantity = max(0, int(required_quantity) - inventory_quantity)
        if missing_quantity > 0:
            moved_quantity = yield from io.get_material_withdraw()(int(ingredient_model_id), missing_quantity)
            if moved_quantity > 0:
                yield from io.get_wait()(120)
        final_quantity = max(0, int(io.get_count()(int(ingredient_model_id))))
        if final_quantity < int(required_quantity):
            all_ready = False
            io.get_console()(
                io.read_module(),
                f"Cannot prepare {vendor_name} crafting materials: need {required_quantity} "
                f"{io.get_label()(int(ingredient_model_id))}; found {final_quantity} in inventory.",
                io.read_warning(),
            )
    return all_ready


def collect_ingredients(recipe: CrafterRecipeView, *, io: IngredientIO) -> _Ingredients:
    ingredient_item_ids: list[int] = []
    ingredient_quantities: list[int] = []
    blockers: list[str] = []
    for ingredient_model_id, quantity_needed in recipe.ingredients:
        remaining = max(0, int(quantity_needed))
        collected = 0
        for item_id in io.get_inventory_ids()(int(ingredient_model_id)):
            if remaining <= 0:
                break
            try:
                stack_quantity = max(0, int(io.get_quantity()(item_id)))
            except Exception:
                stack_quantity = 0
            if stack_quantity <= 0:
                continue
            take_quantity = min(stack_quantity, remaining)
            ingredient_item_ids.append(int(item_id))
            ingredient_quantities.append(int(take_quantity))
            collected += take_quantity
            remaining -= take_quantity
        if remaining > 0:
            blockers.append(f"Need {quantity_needed} {io.get_label()(int(ingredient_model_id))}; found {collected}.")
    return ingredient_item_ids, ingredient_quantities, blockers


def execute_vendor_crafts[R: CrafterRecipeView](
    planned_crafts: list[PlannedConsumableCraft], *, counts: _Counts, io: VendorIO[R]
) -> _Steps[None]:
    grouped_by_vendor: dict[str, list[PlannedConsumableCraft]] = {}
    for craft in planned_crafts:
        grouped_by_vendor.setdefault(str(craft.vendor_key), []).append(craft)

    for _vendor_key, vendor_crafts in grouped_by_vendor.items():
        first_craft = vendor_crafts[0]
        if not (yield from io.get_prepare()(vendor_crafts, vendor_name=first_craft.vendor_name)):
            counts.depleted += sum(max(0, int(craft.quantity)) for craft in vendor_crafts)
            continue

        opened_items = yield from io.get_open()(first_craft.coords, first_craft.vendor_name)
        if not opened_items:
            counts.load_failures += len(vendor_crafts)
            continue
        offered_by_model: dict[int, int] = {}
        for offered_item_id in opened_items:
            try:
                offered_by_model[int(io.get_model_id()(offered_item_id))] = int(offered_item_id)
            except Exception:
                continue

        for craft in vendor_crafts:
            recipe = io.get_recipe()(craft.model_id)
            requested_craft_quantity = max(0, int(craft.quantity))
            completed_for_craft = 0
            verified_for_craft = 0
            blocked_reason = ""
            if recipe is None:
                counts.unavailable += max(1, requested_craft_quantity)
                continue
            offered_item_id = int(offered_by_model.get(int(recipe.model_id), 0))
            if offered_item_id <= 0:
                counts.unavailable += max(1, requested_craft_quantity)
                io.get_console()(
                    io.read_module(), f"{craft.label} was not offered by {craft.vendor_name}.", io.read_warning()
                )
                continue

            for _ in range(requested_craft_quantity):
                current_skill_points, _total_skill_points = io.get_skill_points()()
                if int(current_skill_points) < int(recipe.skill_points):
                    counts.depleted += 1
                    blocked_reason = "skill points"
                    break

                gold_result = yield from io.get_fund()(
                    int(recipe.gold_cost),
                    purpose=f"{craft.vendor_name} craft {craft.label}",
                )
                if gold_result.opened_storage:
                    opened_items = yield from io.get_open()(
                        first_craft.coords,
                        first_craft.vendor_name,
                    )
                    if not opened_items:
                        counts.load_failures += 1
                        blocked_reason = "crafter inventory"
                        break
                    offered_by_model = {}
                    for offered_item_id in opened_items:
                        try:
                            offered_model_id = int(io.get_model_id()(offered_item_id))
                            offered_by_model[offered_model_id] = int(offered_item_id)
                        except Exception:
                            continue
                    offered_item_id = int(offered_by_model.get(int(recipe.model_id), 0))
                    if offered_item_id <= 0:
                        counts.unavailable += max(1, requested_craft_quantity - completed_for_craft)
                        blocked_reason = "crafter offer"
                        break
                    gold_result = yield from io.get_fund()(
                        int(recipe.gold_cost),
                        purpose=f"{craft.vendor_name} craft {craft.label}",
                    )
                if not gold_result.ready:
                    counts.gold_blocked += 1
                    blocked_reason = "gold"
                    io.get_debug()(
                        f"Consumable craft blocked by gold: label={craft.label} cost={int(recipe.gold_cost)} "
                        f"carried={gold_result.carried_gold} storage={gold_result.storage_gold} "
                        f"reason={gold_result.reason}"
                    )
                    break

                ingredient_item_ids, ingredient_quantities, blockers = io.get_collect()(recipe)
                if blockers:
                    counts.depleted += 1
                    blocked_reason = "materials"
                    io.get_console()(
                        io.read_module(), f"Cannot craft {craft.label}: {' '.join(blockers)}", io.read_warning()
                    )
                    break

                before_count = max(0, int(io.get_count()(int(recipe.model_id))))
                io.get_craft()(
                    offered_item_id,
                    int(recipe.gold_cost),
                    ingredient_item_ids,
                    ingredient_quantities,
                )
                completed = yield from io.get_transaction_wait()(
                    timeout_ms=1500,
                    step_ms=50,
                )
                after_count = yield from io.get_count_wait()(
                    int(recipe.model_id),
                    before_count + 1,
                    timeout_ms=1500,
                    step_ms=50,
                )
                if completed or after_count > before_count:
                    counts.completed += 1
                    completed_for_craft += 1
                    if after_count > before_count:
                        verified_for_craft += 1
                else:
                    counts.timeout_failures += 1
                    blocked_reason = "transaction confirmation"
                    break

            if completed_for_craft >= requested_craft_quantity and verified_for_craft >= requested_craft_quantity:
                io.get_cleanup()(craft.cleanup, label=craft.label)

            if 0 <= completed_for_craft < requested_craft_quantity:
                remaining = max(0, requested_craft_quantity - completed_for_craft)
                reason_suffix = f" blocked by {blocked_reason}" if blocked_reason else ""
                io.get_console()(
                    io.read_module(),
                    f"Crafted {completed_for_craft}/{requested_craft_quantity} {craft.label}; {remaining} remaining{reason_suffix}.",
                    io.read_warning(),
                )
