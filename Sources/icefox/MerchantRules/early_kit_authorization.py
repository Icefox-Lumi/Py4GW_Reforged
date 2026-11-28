"""Authorize and settle kit purchases against the state of a single execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.configuration import BuyRule
    from Sources.icefox.MerchantRules.configuration import MerchantStockTarget
    from Sources.icefox.MerchantRules.planning import PlannedMerchantBuy
    from Sources.icefox.MerchantRules.planning import PlannedStorageTransfer
    from Sources.icefox.MerchantRules.planning import PlanResult
    from Sources.icefox.MerchantRules.planning import PurchaseTargetCleanup

type _Get[T] = Callable[[], T]
type _TargetKey = tuple[int, str]
type _KeyOf = Callable[[PurchaseTargetCleanup], _TargetKey]
type _Models = Callable[[str], tuple[int, ...]]


class _State(Protocol):
    purchase_budget_by_target: dict[_TargetKey, int]
    purchase_budget_ready: set[_TargetKey]
    quarantined_purchase_targets: set[_TargetKey]
    deferred_cleanups: dict[_TargetKey, PurchaseTargetCleanup]


class _ReplaceBuy(Protocol):
    def __call__(self, original: PlannedMerchantBuy, /, *, quantity: int) -> PlannedMerchantBuy: ...


class _Apply(Protocol):
    def __call__(self, cleanup: PurchaseTargetCleanup, /, *, label: str = "") -> bool: ...


@dataclass(frozen=True)
class EarlyKitPolicy:
    """Read the widget's current callables and constants at their use sites."""

    buy_rule: _Get[Callable[[BuyRule], BuyRule | None]]
    merchant_targets: _Get[Callable[[object], list[MerchantStockTarget]]]
    after_purchase: _Get[Callable[[object], str]]
    safe_int: _Get[Callable[[object, int], int]]
    replace_buy: _Get[_ReplaceBuy]
    model_count: _Get[Callable[[int], int]]
    merchant_kind: _Get[str]
    keep: _Get[str]
    withdraw: _Get[str]


def target_key(cleanup: PurchaseTargetCleanup) -> _TargetKey:
    return (
        int(getattr(cleanup, "rule_index", -1)),
        str(getattr(cleanup, "target_key", "") or ""),
    )


def capture(
    plan: PlanResult,
    state: _State,
    *,
    policy: EarlyKitPolicy,
    rules: _Get[list[BuyRule]],
    is_kit: _Get[Callable[[object], bool]],
    key: _Get[_KeyOf],
    supports: _Get[Callable[[int], bool]],
) -> None:
    """Capture each compatible target's first complete, storage-aware authorization."""

    planned_quantity_by_target: dict[tuple[int, str], int] = {}
    for merchant_buy in plan.merchant_stock_buys:
        cleanup = merchant_buy.cleanup
        if str(getattr(cleanup, "rule_kind", "")) != policy.merchant_kind():
            continue
        if not is_kit()(merchant_buy.model_id):
            continue
        target_key = key()(cleanup)
        planned_quantity_by_target[target_key] = max(0, int(planned_quantity_by_target.get(target_key, 0))) + max(
            0, int(merchant_buy.quantity)
        )

    # Request-scoped Merchant Stock targets have no persisted target entry, but their
    # PlannedMerchantBuy cleanup still carries the -1 owner identity.
    for target_key, quantity in planned_quantity_by_target.items():
        if target_key in state.purchase_budget_ready:
            continue
        state.purchase_budget_by_target[target_key] = max(0, int(quantity))
        state.purchase_budget_ready.add(target_key)

    for rule_index, raw_buy_rule in enumerate(rules()):
        buy_rule = policy.buy_rule()(raw_buy_rule)
        if buy_rule is None or not buy_rule.enabled or buy_rule.kind != policy.merchant_kind():
            continue
        for target in policy.merchant_targets()(buy_rule.merchant_stock_targets):
            model_id = max(0, int(target.model_id))
            if not is_kit()(model_id):
                continue
            if bool(target.check_xunlai_first) and supports()(model_id) and not bool(plan.storage_exact):
                # The target's first complete authorization is not knowable until the
                # existing exact Xunlai scan has run.
                continue
            target_key = (int(rule_index), str(model_id))
            if target_key in state.purchase_budget_ready:
                continue
            state.purchase_budget_by_target[target_key] = max(
                0,
                int(planned_quantity_by_target.get(target_key, 0)),
            )
            state.purchase_budget_ready.add(target_key)


def clamp(plan: PlanResult, state: _State, *, policy: EarlyKitPolicy, key: _Get[_KeyOf]) -> None:
    """Prevent rebuilt compatible Merchant Stock plans from recreating spent authorization."""

    clamped_buys: list[PlannedMerchantBuy] = []
    for merchant_buy in plan.merchant_stock_buys:
        cleanup = merchant_buy.cleanup
        target_key = key()(cleanup)
        if (
            str(getattr(cleanup, "rule_kind", "")) != policy.merchant_kind()
            or target_key not in state.purchase_budget_ready
        ):
            clamped_buys.append(merchant_buy)
            continue
        if target_key in state.quarantined_purchase_targets:
            continue
        remaining_authorized = max(
            0,
            int(state.purchase_budget_by_target.get(target_key, 0)),
        )
        remaining_quantity = min(max(0, int(merchant_buy.quantity)), remaining_authorized)
        if remaining_quantity <= 0:
            continue
        if remaining_quantity != int(merchant_buy.quantity):
            merchant_buy = policy.replace_buy()(merchant_buy, quantity=remaining_quantity)
        clamped_buys.append(merchant_buy)
    plan.merchant_stock_buys = clamped_buys


def quarantine(state: _State, merchant_buy: PlannedMerchantBuy, *, policy: EarlyKitPolicy, key: _Get[_KeyOf]) -> None:
    cleanup = merchant_buy.cleanup
    if str(getattr(cleanup, "rule_kind", "")) != policy.merchant_kind():
        return
    state.quarantined_purchase_targets.add(key()(cleanup))


def consume(
    state: _State,
    merchant_buy: PlannedMerchantBuy,
    completed: int,
    *,
    policy: EarlyKitPolicy,
    key: _Get[_KeyOf],
) -> None:
    cleanup = merchant_buy.cleanup
    if str(getattr(cleanup, "rule_kind", "")) != policy.merchant_kind():
        return
    target_key = key()(cleanup)
    if target_key not in state.purchase_budget_ready:
        return
    state.purchase_budget_by_target[target_key] = max(
        0,
        int(state.purchase_budget_by_target.get(target_key, 0)) - max(0, int(completed)),
    )


def record_cleanup(
    state: _State,
    merchant_buy: PlannedMerchantBuy,
    completed: int,
    *,
    policy: EarlyKitPolicy,
    key: _Get[_KeyOf],
) -> None:
    if max(0, int(completed)) <= 0:
        return
    cleanup = merchant_buy.cleanup
    if (
        policy.after_purchase()(getattr(cleanup, "after_purchase", policy.keep())) == policy.keep()
        or not bool(getattr(cleanup, "completes_target", False))
        or bool(getattr(cleanup, "xunlai_involved", False))
    ):
        return
    state.deferred_cleanups[key()(cleanup)] = cleanup


def apply_deferred(
    state: _State,
    *,
    policy: EarlyKitPolicy,
    key: _Get[_KeyOf],
    apply: _Get[_Apply],
    label: _Get[Callable[[int], str]],
) -> None:
    for cleanup in list(state.deferred_cleanups.values()):
        model_id = max(0, policy.safe_int()(getattr(cleanup, "target_key", 0), 0))
        target_count = max(0, int(getattr(cleanup, "target_count", 0)))
        if model_id <= 0 or target_count <= 0:
            continue
        try:
            carried_count = max(0, int(policy.model_count()(model_id)))
        except Exception:
            continue
        if carried_count < target_count:
            continue
        cleanup_applied = apply()(
            cleanup,
            label=label()(model_id),
        )
        if cleanup_applied:
            state.deferred_cleanups.pop(key()(cleanup), None)


def clear_satisfied(
    state: _State,
    merchant_buy: PlannedMerchantBuy,
    completed: int,
    *,
    policy: EarlyKitPolicy,
    key: _Get[_KeyOf],
) -> None:
    if max(0, int(completed)) <= 0:
        return
    cleanup = merchant_buy.cleanup
    if (
        policy.after_purchase()(getattr(cleanup, "after_purchase", policy.keep())) == policy.keep()
        or not bool(getattr(cleanup, "completes_target", False))
        or bool(getattr(cleanup, "xunlai_involved", False))
    ):
        return
    model_id = max(0, policy.safe_int()(getattr(cleanup, "target_key", 0), 0))
    target_count = max(0, int(getattr(cleanup, "target_count", 0)))
    if model_id <= 0 or target_count <= 0:
        return
    try:
        carried_count = max(0, int(policy.model_count()(model_id)))
    except Exception:
        return
    if carried_count >= target_count:
        state.deferred_cleanups.pop(key()(cleanup), None)


def filter_blocked(plan: PlanResult, blocked_models: set[int]) -> None:
    if not blocked_models:
        return
    plan.storage_transfers = [
        transfer
        for transfer in plan.storage_transfers
        if not (bool(transfer.xunlai_first_merchant_stock) and max(0, int(transfer.model_id)) in blocked_models)
    ]
    plan.merchant_stock_buys = [
        merchant_buy
        for merchant_buy in plan.merchant_stock_buys
        if not (bool(merchant_buy.check_xunlai_first) and max(0, int(merchant_buy.model_id)) in blocked_models)
    ]


def has_xunlai_target(plan: PlanResult, model_ids: set[int]) -> bool:
    if bool(plan.storage_exact):
        return False
    if any(max(0, int(model_id)) in model_ids for model_id in plan.xunlai_first_merchant_stock_targets):
        return True
    return False


def storage_source(
    plan: PlanResult,
    category: str,
    blocked_models: set[int],
    *,
    policy: EarlyKitPolicy,
    models: _Get[_Models],
) -> PlannedStorageTransfer | None:
    model_ids = set(models()(category))
    for transfer in plan.storage_transfers:
        model_id = max(0, int(transfer.model_id))
        if (
            str(transfer.direction) == policy.withdraw()
            and bool(transfer.xunlai_first_merchant_stock)
            and model_id in model_ids
            and model_id not in blocked_models
            and max(0, int(transfer.quantity)) > 0
        ):
            return transfer
    return None


def merchant_source(
    plan: PlanResult,
    category: str,
    state: _State,
    blocked_models: set[int],
    *,
    policy: EarlyKitPolicy,
    models: _Get[_Models],
    key: _Get[_KeyOf],
) -> PlannedMerchantBuy | None:
    model_ids = set(models()(category))
    for merchant_buy in plan.merchant_stock_buys:
        model_id = max(0, int(merchant_buy.model_id))
        cleanup = merchant_buy.cleanup
        target_key = key()(cleanup)
        if (
            model_id in model_ids
            and model_id not in blocked_models
            and str(getattr(cleanup, "rule_kind", "")) == policy.merchant_kind()
            and target_key in state.purchase_budget_ready
            and target_key not in state.quarantined_purchase_targets
            and max(0, int(state.purchase_budget_by_target.get(target_key, 0))) > 0
            and max(0, int(merchant_buy.quantity)) > 0
        ):
            return merchant_buy
    return None
