"""Cooperative gold transfers and readback for Merchant Rules."""

from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from typing import cast

from Sources.icefox.MerchantRules.configuration import MAX_CHARACTER_GOLD

type _InventoryProvider = Callable[[], object | None]
type _Wait = Callable[[int], Generator[object, None, None]]
type _DrainActionQueue = Callable[[int, int], Generator[object, None, bool]]
type _DebugLog = Callable[[str], None]

GOLD_TOP_UP_TIMEOUT_MS = 2000
GOLD_TOP_UP_STEP_MS = 50
GOLD_BALANCE_SERVICE_TIMEOUT_MS = 3000
GOLD_BALANCE_VERIFY_TIMEOUT_MS = 2000
GOLD_BALANCE_STEP_MS = 50

GOLD_BALANCE_STATUS_DISABLED = "disabled"
GOLD_BALANCE_STATUS_TARGET_MET = "target_met"
GOLD_BALANCE_STATUS_EXACT = "exact"
GOLD_BALANCE_STATUS_PARTIAL = "partial"
GOLD_BALANCE_STATUS_NO_PROGRESS = "no_progress"
GOLD_BALANCE_STATUS_UNAVAILABLE = "unavailable"
GOLD_BALANCE_STATUS_INVALID = "invalid"


@dataclass
class GoldTopUpResult:
    """Report whether a purchase can proceed after an optional bounded storage withdrawal."""

    ready: bool
    carried_gold: int = 0
    storage_gold: int = 0
    withdrawn: int = 0
    opened_storage: bool = False
    reason: str = ""


@dataclass
class GoldBalanceResult:
    """Report one bounded carried-gold balancing attempt."""

    status: str
    trigger: str = ""
    target_gold: int = 0
    carried_before: int = 0
    storage_before: int = 0
    carried_after: int = 0
    storage_after: int = 0
    requested: int = 0
    moved: int = 0
    reason: str = ""


def _get_inventory_api_method(get_inventory: _InventoryProvider, method_name: str) -> object | None:
    inventory_api = get_inventory()
    if inventory_api is None:
        return None
    method: object = getattr(inventory_api, str(method_name), None)
    return method if callable(method) else None


def _get_transfer(get_inventory: _InventoryProvider, method_name: str) -> Callable[[int], None] | None:
    return cast(Callable[[int], None] | None, _get_inventory_api_method(get_inventory, method_name))


def read_gold_amount(method_name: str, *, get_inventory: _InventoryProvider, debug_log: _DebugLog) -> int | None:
    method = cast(Callable[[], int] | None, _get_inventory_api_method(get_inventory, method_name))
    if method is None:
        return None
    try:
        return max(0, int(method() or 0))
    except Exception as exc:
        debug_log(f"Gold API {method_name} failed: {exc}")
        return None


def _read_gold_snapshot(get_inventory: _InventoryProvider, debug_log: _DebugLog) -> tuple[int, int] | None:
    carried_gold = read_gold_amount("GetGoldOnCharacter", get_inventory=get_inventory, debug_log=debug_log)
    storage_gold = read_gold_amount("GetGoldInStorage", get_inventory=get_inventory, debug_log=debug_log)
    if carried_gold is None or storage_gold is None:
        return None
    return max(0, int(carried_gold)), max(0, int(storage_gold))


def _wait_for_gold_balance_service(
    has_local_storage_access: Callable[[], bool], wait: _Wait
) -> Generator[object, None, bool]:
    if has_local_storage_access():
        return True

    waited_ms = 0
    while waited_ms < GOLD_BALANCE_SERVICE_TIMEOUT_MS:
        yield from wait(GOLD_BALANCE_STEP_MS)
        waited_ms += GOLD_BALANCE_STEP_MS
        if has_local_storage_access():
            return True
    return bool(has_local_storage_access())


def _classify_gold_balance_snapshot(
    *,
    trigger: str,
    target_gold: int,
    direction: str,
    requested: int,
    before: tuple[int, int],
    after: tuple[int, int],
) -> GoldBalanceResult:
    carried_before, storage_before = before
    carried_after, storage_after = after
    if carried_before + storage_before != carried_after + storage_after:
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_INVALID,
            trigger=trigger,
            target_gold=target_gold,
            carried_before=carried_before,
            storage_before=storage_before,
            carried_after=carried_after,
            storage_after=storage_after,
            requested=requested,
            reason="combined gold changed unexpectedly",
        )

    carried_delta = carried_after - carried_before
    if direction == "deposit":
        if carried_delta > 0 or carried_after < target_gold:
            return GoldBalanceResult(
                status=GOLD_BALANCE_STATUS_INVALID,
                trigger=trigger,
                target_gold=target_gold,
                carried_before=carried_before,
                storage_before=storage_before,
                carried_after=carried_after,
                storage_after=storage_after,
                requested=requested,
                moved=max(0, -carried_delta),
                reason="deposit moved beyond the requested target",
            )
        moved = max(0, -carried_delta)
    else:
        if carried_delta < 0 or carried_after > target_gold:
            return GoldBalanceResult(
                status=GOLD_BALANCE_STATUS_INVALID,
                trigger=trigger,
                target_gold=target_gold,
                carried_before=carried_before,
                storage_before=storage_before,
                carried_after=carried_after,
                storage_after=storage_after,
                requested=requested,
                moved=max(0, carried_delta),
                reason="withdrawal moved beyond the requested target",
            )
        moved = max(0, carried_delta)

    if carried_after == target_gold:
        status = GOLD_BALANCE_STATUS_EXACT
    elif moved > 0:
        status = GOLD_BALANCE_STATUS_PARTIAL
    else:
        status = GOLD_BALANCE_STATUS_NO_PROGRESS
    return GoldBalanceResult(
        status=status,
        trigger=trigger,
        target_gold=target_gold,
        carried_before=carried_before,
        storage_before=storage_before,
        carried_after=carried_after,
        storage_after=storage_after,
        requested=requested,
        moved=moved,
    )


def _wait_for_gold_balance_readback(
    *,
    get_inventory: _InventoryProvider,
    wait: _Wait,
    debug_log: _DebugLog,
    trigger: str,
    target_gold: int,
    direction: str,
    requested: int,
    before: tuple[int, int],
) -> Generator[object, None, GoldBalanceResult]:
    waited_ms = 0
    last_result: GoldBalanceResult | None = None
    while waited_ms <= GOLD_BALANCE_VERIFY_TIMEOUT_MS:
        after = _read_gold_snapshot(get_inventory, debug_log)
        if after is None:
            return GoldBalanceResult(
                status=GOLD_BALANCE_STATUS_INVALID,
                trigger=trigger,
                target_gold=target_gold,
                carried_before=before[0],
                storage_before=before[1],
                requested=requested,
                reason="gold read-back was unavailable",
            )
        last_result = _classify_gold_balance_snapshot(
            trigger=trigger,
            target_gold=target_gold,
            direction=direction,
            requested=requested,
            before=before,
            after=after,
        )
        if last_result.status in {
            GOLD_BALANCE_STATUS_EXACT,
            GOLD_BALANCE_STATUS_INVALID,
        }:
            return last_result
        if waited_ms >= GOLD_BALANCE_VERIFY_TIMEOUT_MS:
            break
        yield from wait(GOLD_BALANCE_STEP_MS)
        waited_ms += GOLD_BALANCE_STEP_MS
    return last_result or GoldBalanceResult(
        status=GOLD_BALANCE_STATUS_INVALID,
        trigger=trigger,
        target_gold=target_gold,
        carried_before=before[0],
        storage_before=before[1],
        requested=requested,
        reason="gold read-back did not produce a result",
    )


def balance_to_target(
    target_gold: int,
    trigger: str,
    *,
    get_inventory: _InventoryProvider,
    wait: _Wait,
    drain_action_queue: _DrainActionQueue,
    has_local_storage_access: Callable[[], bool],
    debug_log: _DebugLog,
) -> Generator[object, None, GoldBalanceResult]:
    """Balance to the widget-normalized target and report the observed transfer."""
    before = _read_gold_snapshot(get_inventory, debug_log)
    if before is None:
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_UNAVAILABLE,
            trigger=trigger,
            target_gold=target_gold,
            reason="gold balances unavailable",
        )

    carried_gold, storage_gold = before
    if carried_gold == target_gold:
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_TARGET_MET,
            trigger=trigger,
            target_gold=target_gold,
            carried_before=carried_gold,
            storage_before=storage_gold,
            carried_after=carried_gold,
            storage_after=storage_gold,
        )

    service_ready = yield from _wait_for_gold_balance_service(has_local_storage_access, wait)
    if not service_ready:
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_UNAVAILABLE,
            trigger=trigger,
            target_gold=target_gold,
            carried_before=carried_gold,
            storage_before=storage_gold,
            reason="Xunlai service was not found nearby",
        )

    live_before = _read_gold_snapshot(get_inventory, debug_log)
    if live_before is None:
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_INVALID,
            trigger=trigger,
            target_gold=target_gold,
            reason="gold read-back was unavailable before the transfer",
        )
    carried_gold, storage_gold = live_before
    if carried_gold == target_gold:
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_TARGET_MET,
            trigger=trigger,
            target_gold=target_gold,
            carried_before=carried_gold,
            storage_before=storage_gold,
            carried_after=carried_gold,
            storage_after=storage_gold,
        )

    if carried_gold > target_gold:
        direction = "deposit"
        requested = carried_gold - target_gold
        method_name = "DepositGold"
    else:
        direction = "withdraw"
        requested = min(
            target_gold - carried_gold,
            max(0, storage_gold),
            max(0, MAX_CHARACTER_GOLD - carried_gold),
        )
        method_name = "WithdrawGold"

    if requested <= 0:
        reason = (
            "storage does not contain enough gold"
            if direction == "withdraw"
            else "the carried-gold difference was zero"
        )
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_NO_PROGRESS,
            trigger=trigger,
            target_gold=target_gold,
            carried_before=carried_gold,
            storage_before=storage_gold,
            carried_after=carried_gold,
            storage_after=storage_gold,
            reason=reason,
        )

    transfer = _get_transfer(get_inventory, method_name)
    if transfer is None:
        debug_log(f"Gold balance transfer method unavailable: {method_name}")
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_UNAVAILABLE,
            trigger=trigger,
            target_gold=target_gold,
            carried_before=carried_gold,
            storage_before=storage_gold,
            requested=requested,
            reason=f"gold {direction} unavailable",
        )

    try:
        transfer(int(requested))
    except Exception as exc:
        debug_log(f"Gold balance transfer failed using {method_name}: {exc}")
        return GoldBalanceResult(
            status=GOLD_BALANCE_STATUS_UNAVAILABLE,
            trigger=trigger,
            target_gold=target_gold,
            carried_before=carried_gold,
            storage_before=storage_gold,
            requested=requested,
            reason=f"gold {direction} failed",
        )

    yield from drain_action_queue(GOLD_BALANCE_VERIFY_TIMEOUT_MS, GOLD_BALANCE_STEP_MS)
    return (
        yield from _wait_for_gold_balance_readback(
            get_inventory=get_inventory,
            wait=wait,
            debug_log=debug_log,
            trigger=trigger,
            target_gold=target_gold,
            direction=direction,
            requested=requested,
            before=live_before,
        )
    )


def _wait_for_character_gold_at_least(
    target_gold: int,
    *,
    get_inventory: _InventoryProvider,
    wait: _Wait,
    debug_log: _DebugLog,
    timeout_ms: int = GOLD_TOP_UP_TIMEOUT_MS,
    step_ms: int = GOLD_TOP_UP_STEP_MS,
) -> Generator[object, None, int]:
    safe_target = max(0, int(target_gold))
    waited_ms = 0
    current_gold = read_gold_amount("GetGoldOnCharacter", get_inventory=get_inventory, debug_log=debug_log)
    while waited_ms <= max(0, int(timeout_ms)):
        if current_gold is not None and int(current_gold) >= safe_target:
            return max(0, int(current_gold))
        if waited_ms >= max(0, int(timeout_ms)):
            break
        waited_ms += max(1, int(step_ms))
        yield from wait(max(1, int(step_ms)))
        current_gold = read_gold_amount("GetGoldOnCharacter", get_inventory=get_inventory, debug_log=debug_log)
    return max(0, int(current_gold or 0))


def fund_purchase(
    required_gold: int,
    *,
    purpose: str = "merchant purchase",
    get_inventory: _InventoryProvider,
    wait: _Wait,
    drain_action_queue: _DrainActionQueue,
    is_storage_open: Callable[[], bool],
    can_use_local_storage_actions: Callable[[], bool],
    ensure_storage_open: Callable[[str], Generator[object, None, bool]],
    debug_log: _DebugLog,
) -> Generator[object, None, GoldTopUpResult]:
    """Yield while topping up only the verified gold shortfall required for a purchase.

    Storage is opened only when character plus storage gold can cover the target. The
    generator reports failure when balances or withdrawal progress cannot be verified.
    """

    safe_required_gold = max(0, int(required_gold))
    character_gold = read_gold_amount("GetGoldOnCharacter", get_inventory=get_inventory, debug_log=debug_log)
    if character_gold is None:
        return GoldTopUpResult(False, reason="carried gold API unavailable")
    if safe_required_gold <= 0 or character_gold >= safe_required_gold:
        return GoldTopUpResult(True, carried_gold=character_gold)

    storage_gold = read_gold_amount("GetGoldInStorage", get_inventory=get_inventory, debug_log=debug_log)
    withdraw_gold = _get_transfer(get_inventory, "WithdrawGold")
    if storage_gold is None or withdraw_gold is None:
        return GoldTopUpResult(
            False,
            carried_gold=character_gold,
            reason="Xunlai gold API unavailable",
        )

    if character_gold + storage_gold < safe_required_gold:
        return GoldTopUpResult(
            False,
            carried_gold=character_gold,
            storage_gold=storage_gold,
            reason="not enough total gold",
        )

    opened_storage = False
    if not is_storage_open():
        if not can_use_local_storage_actions():
            return GoldTopUpResult(
                False,
                carried_gold=character_gold,
                storage_gold=storage_gold,
                reason="Xunlai not available here",
            )
        opened_storage = bool((yield from ensure_storage_open(f"{purpose} gold top-up")))
        if not opened_storage:
            return GoldTopUpResult(
                False,
                carried_gold=character_gold,
                storage_gold=storage_gold,
                reason="could not open Xunlai",
            )
        # Opening storage can invalidate the buyer's offer even if carried gold is now enough.
        yield from wait(100)
        character_gold = read_gold_amount("GetGoldOnCharacter", get_inventory=get_inventory, debug_log=debug_log)
        storage_gold = read_gold_amount("GetGoldInStorage", get_inventory=get_inventory, debug_log=debug_log)
        if character_gold is None or storage_gold is None:
            return GoldTopUpResult(
                False,
                opened_storage=opened_storage,
                reason="gold API unavailable after opening Xunlai",
            )
        if character_gold >= safe_required_gold:
            return GoldTopUpResult(
                True,
                carried_gold=character_gold,
                storage_gold=storage_gold,
                opened_storage=opened_storage,
            )
        if character_gold + storage_gold < safe_required_gold:
            return GoldTopUpResult(
                False,
                carried_gold=character_gold,
                storage_gold=storage_gold,
                opened_storage=opened_storage,
                reason="not enough total gold",
            )
        return GoldTopUpResult(
            False,
            carried_gold=character_gold,
            storage_gold=storage_gold,
            opened_storage=opened_storage,
            reason="Xunlai opened; revalidate purchase before withdrawal",
        )

    missing_gold = max(0, safe_required_gold - character_gold)
    character_gold_room = max(0, MAX_CHARACTER_GOLD - character_gold)
    withdraw_amount = min(missing_gold, max(0, int(storage_gold)), character_gold_room)
    if withdraw_amount <= 0:
        return GoldTopUpResult(
            False,
            carried_gold=character_gold,
            storage_gold=storage_gold,
            opened_storage=opened_storage,
            reason="character gold cap prevents withdrawal",
        )

    debug_log(
        f"Withdrawing {withdraw_amount} gold for {purpose}: "
        f"carried={character_gold} storage={storage_gold} required={safe_required_gold}."
    )
    try:
        withdraw_gold(int(withdraw_amount))
    except Exception as exc:
        return GoldTopUpResult(
            False,
            carried_gold=character_gold,
            storage_gold=storage_gold,
            opened_storage=opened_storage,
            reason=f"withdraw failed: {exc}",
        )

    queue_cleared = yield from drain_action_queue(1000, 50)
    wait_timeout_ms = GOLD_TOP_UP_TIMEOUT_MS if queue_cleared else 1000
    character_gold = yield from _wait_for_character_gold_at_least(
        safe_required_gold,
        get_inventory=get_inventory,
        wait=wait,
        debug_log=debug_log,
        timeout_ms=wait_timeout_ms,
        step_ms=GOLD_TOP_UP_STEP_MS,
    )
    storage_gold_after = read_gold_amount("GetGoldInStorage", get_inventory=get_inventory, debug_log=debug_log)
    ready = character_gold >= safe_required_gold
    reason = "" if ready else "withdrawal did not reach required carried gold"
    return GoldTopUpResult(
        ready,
        carried_gold=character_gold,
        storage_gold=max(0, int(storage_gold_after or 0)),
        withdrawn=withdraw_amount,
        opened_storage=opened_storage,
        reason=reason,
    )
