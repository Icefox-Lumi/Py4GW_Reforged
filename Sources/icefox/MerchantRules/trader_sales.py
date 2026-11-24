"""Execute trader sales with a fresh quote, live identity checks, and exact quantity readback."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol
from typing import cast

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.inventory_evidence import InventoryItemInfo
    from Sources.icefox.MerchantRules.planning import PlannedMaterialSale
    from Sources.icefox.MerchantRules.planning import PlannedTraderSale

type Sale = PlannedMaterialSale | PlannedTraderSale
type Steps[T] = Generator[object, None, T]
type Get[T] = Callable[[], T]
type Checked = tuple[InventoryItemInfo | None, str]
type Confirmed = tuple[bool, bool, str]
type Reacquire = Callable[[int], Checked]
type MaterialCheck = Callable[[PlannedMaterialSale, int], Checked]
type RuneCheck = Callable[[PlannedTraderSale], Checked]
type Destination = Callable[[int], str]
type SafeInt = Callable[[object, int], int]
type Wait = Callable[[int], Steps[None]]


class SaleCounters(Protocol):
    completed: int
    unavailable: int
    quote_failures: int
    timeout_failures: int


class _ReadItem(Protocol):
    def __call__(self, item_id: int, /, *, include_runtime_name: bool) -> InventoryItemInfo | None: ...


class _Confirm(Protocol):
    def __call__(self, sale: Sale, expected_quantity: int, /, *, timeout_ms: int, step_ms: int) -> Steps[Confirmed]: ...


class QuoteWaiter(Protocol):
    def __call__(
        self, request: Callable[[int], None], item_id: int, /, *, timeout_ms: int, step_ms: int
    ) -> Steps[int]: ...


@dataclass(frozen=True)
class EvidenceReads:
    """Resolve each inventory read separately, including reads in the same poll."""

    get_inventory_ids: Get[Callable[[], list[int]]]
    get_item_reader: Get[_ReadItem]


@dataclass(frozen=True)
class RuneIdentity:
    get_standalone_kind: Get[str]
    get_normalize: Get[Callable[[object], tuple[str, ...]]]


@dataclass(frozen=True)
class LoopOps[V]:
    """Look up the current widget or runtime callable at each transaction step."""

    get_validate: Get[V]
    get_confirm: Get[_Confirm]
    get_quote_waiter: Get[QuoteWaiter]
    get_request_sell_quote: Get[Callable[[int], None]]
    get_sell_item: Get[Callable[[int, int], None]]
    get_wait: Get[Wait]
    get_abort: Get[Callable[[str, int, int, str], None]]
    get_debug: Get[Callable[[str], None]]


def reacquire_item(item_id: int, *, reads: EvidenceReads, safe_int: Get[SafeInt]) -> Checked:
    safe_item_id = max(0, safe_int()(item_id, 0))
    if safe_item_id <= 0:
        return None, "the planned item ID is invalid"
    try:
        inventory_item_ids = {int(current_id) for current_id in reads.get_inventory_ids()()}
    except Exception:
        return None, "the current inventory could not be read"
    if safe_item_id not in inventory_item_ids:
        return None, "the planned item is no longer in the inventory"

    item = reads.get_item_reader()(safe_item_id, include_runtime_name=False)
    if item is None:
        return None, "the planned item could not be read"
    if int(item.item_id) != safe_item_id:
        return None, "the current item ID no longer matches the planned item"
    return item, ""


def validate_material(
    sale: PlannedMaterialSale,
    required_quantity: int,
    *,
    reacquire: Get[Reacquire],
    destination: Get[Destination],
    safe_int: Get[SafeInt],
) -> Checked:
    item, reason = reacquire()(sale.item_id)
    if item is None:
        return None, reason

    planned_model_id = max(0, safe_int()(sale.model_id, 0))
    if planned_model_id <= 0 or int(item.model_id) != planned_model_id:
        return None, "the current model ID no longer matches the planned material"
    if int(item.quantity) < max(1, int(required_quantity)):
        return None, "the current stack quantity is no longer sufficient for the planned sale"
    if not bool(item.is_material):
        return None, "the current item is no longer classified as a material"
    current_merchant_type = destination()(int(item.model_id))
    if current_merchant_type != str(sale.merchant_type or ""):
        return None, "the current material trader destination no longer matches the plan"
    return item, ""


def validate_rune(
    sale: PlannedTraderSale, *, reacquire: Get[Reacquire], rune: RuneIdentity, safe_int: Get[SafeInt]
) -> Checked:
    item, reason = reacquire()(sale.item_id)
    if item is None:
        return None, reason

    planned_model_id = max(0, safe_int()(sale.model_id, 0))
    if planned_model_id <= 0 or int(item.model_id) != planned_model_id:
        return None, "the current model ID no longer matches the planned rune or insignia"
    if int(item.quantity) < 1:
        return None, "the rune or insignia is no longer available"
    if str(item.standalone_kind or "") != rune.get_standalone_kind():
        return None, "the current item is no longer a standalone rune or insignia"

    expected_identifiers = rune.get_normalize()(sale.expected_rune_identifiers)
    if not expected_identifiers:
        return None, "the plan has no exact rune or insignia modifier identity"
    current_identifiers = rune.get_normalize()(item.rune_identifiers)
    if current_identifiers != expected_identifiers:
        return None, "the exact rune or insignia modifier identity changed after Preview"
    return item, ""


def confirm_quantity(
    sale: Sale,
    expected_quantity: int,
    *,
    timeout_ms: int = 350,
    step_ms: int = 10,
    reads: EvidenceReads,
    destination: Get[Destination],
    material_type: Get[type[PlannedMaterialSale]],
    rune: RuneIdentity,
    safe_int: Get[SafeInt],
    wait: Get[Wait],
) -> Steps[Confirmed]:
    safe_item_id = max(0, safe_int()(sale.item_id, 0))
    safe_model_id = max(0, safe_int()(sale.model_id, 0))
    safe_expected_quantity = max(0, safe_int()(expected_quantity, 0))
    safe_timeout_ms = max(0, safe_int()(timeout_ms, 0))
    safe_step_ms = max(1, safe_int()(step_ms, 1))
    elapsed_ms = 0
    last_quantity: int | None = None
    last_reason = "the expected inventory quantity was not observed"
    if safe_item_id <= 0 or safe_model_id <= 0:
        return False, True, "the planned sale identity is invalid"

    while True:
        try:
            inventory_item_ids = {int(item_id) for item_id in reads.get_inventory_ids()()}
        except Exception:
            inventory_item_ids = None
            last_reason = "the current inventory could not be read"

        if inventory_item_ids is not None:
            if safe_item_id not in inventory_item_ids:
                if safe_expected_quantity == 0:
                    return True, False, ""
                last_reason = (
                    f"the planned item disappeared while {safe_expected_quantity} unit(s) were expected to remain"
                )
            else:
                item = reads.get_item_reader()(safe_item_id, include_runtime_name=False)
                if item is None:
                    return False, True, "the current item could not be read after the sale"
                if int(item.item_id) != safe_item_id:
                    return False, True, "the current item ID no longer matches the planned item"
                if safe_model_id <= 0 or int(item.model_id) != safe_model_id:
                    return False, True, "the current model ID no longer matches the planned item"

                if isinstance(sale, material_type()):
                    if not bool(item.is_material):
                        return False, True, "the current item is no longer classified as a material"
                    current_merchant_type = destination()(int(item.model_id))
                    if current_merchant_type != str(sale.merchant_type or ""):
                        return False, True, "the current material trader destination no longer matches the plan"
                else:
                    if str(item.standalone_kind or "") != rune.get_standalone_kind():
                        return False, True, "the current item is no longer a standalone rune or insignia"
                    expected_identifiers = rune.get_normalize()(
                        cast("PlannedTraderSale", sale).expected_rune_identifiers
                    )
                    current_identifiers = rune.get_normalize()(item.rune_identifiers)
                    if not expected_identifiers or current_identifiers != expected_identifiers:
                        return False, True, "the exact rune or insignia modifier identity changed after the sale"

                last_quantity = max(0, int(item.quantity))
                if last_quantity == safe_expected_quantity:
                    return True, False, ""
                last_reason = f"expected {safe_expected_quantity} unit(s) after the sale, but observed {last_quantity}"

        if elapsed_ms >= safe_timeout_ms:
            return False, False, last_reason
        wait_ms = min(safe_step_ms, safe_timeout_ms - elapsed_ms)
        if wait_ms <= 0:
            return False, False, last_reason
        yield from wait()(wait_ms)
        elapsed_ms += wait_ms


def execute_material_sales(
    sales: list[PlannedMaterialSale], *, phase_label: str, counts: SaleCounters, ops: LoopOps[MaterialCheck]
) -> Steps[None]:
    for sale in sales:
        planned_batches = max(0, int(sale.batches_to_sell))
        for batch_index in range(planned_batches):
            remaining_batches = planned_batches - batch_index
            required_quantity = remaining_batches * max(1, int(sale.batch_size))
            live_item, identity_failure = ops.get_validate()(
                sale,
                required_quantity,
            )
            if live_item is None:
                counts.unavailable += remaining_batches
                ops.get_abort()(
                    phase_label,
                    sale.item_id,
                    sale.model_id,
                    identity_failure,
                )
                break

            quoted_value = yield from ops.get_quote_waiter()(
                ops.get_request_sell_quote(),
                sale.item_id,
                timeout_ms=350,
                step_ms=10,
            )
            if quoted_value <= 0:
                counts.quote_failures += 1
                break

            live_item, identity_failure = ops.get_validate()(
                sale,
                required_quantity,
            )
            if live_item is None:
                counts.unavailable += remaining_batches
                ops.get_abort()(
                    phase_label,
                    sale.item_id,
                    sale.model_id,
                    identity_failure,
                )
                break
            previous_quantity = int(live_item.quantity)
            ops.get_sell_item()(sale.item_id, quoted_value)
            expected_quantity = max(0, previous_quantity - max(1, int(sale.batch_size)))
            (
                completed,
                post_sale_identity_failure,
                completion_reason,
            ) = yield from ops.get_confirm()(
                sale,
                expected_quantity,
                timeout_ms=350,
                step_ms=10,
            )
            if post_sale_identity_failure:
                counts.unavailable += remaining_batches
                ops.get_abort()(
                    phase_label,
                    sale.item_id,
                    sale.model_id,
                    completion_reason,
                )
                break
            if not completed:
                counts.timeout_failures += 1
                ops.get_debug()(
                    f"{phase_label} completion check failed: item_id={sale.item_id} "
                    f"expected_quantity={expected_quantity} reason={completion_reason}."
                )
                break
            counts.completed += 1
            yield from ops.get_wait()(40)


def execute_rune_sales(
    sales: list[PlannedTraderSale], *, phase_label: str, counts: SaleCounters, ops: LoopOps[RuneCheck]
) -> Steps[None]:
    for sale in sales:
        live_item, identity_failure = ops.get_validate()(sale)
        if live_item is None:
            counts.unavailable += 1
            ops.get_abort()(
                phase_label,
                sale.item_id,
                sale.model_id,
                identity_failure,
            )
            continue

        quoted_value = yield from ops.get_quote_waiter()(
            ops.get_request_sell_quote(),
            sale.item_id,
            timeout_ms=350,
            step_ms=10,
        )
        if quoted_value <= 0:
            counts.quote_failures += 1
            continue

        live_item, identity_failure = ops.get_validate()(sale)
        if live_item is None:
            counts.unavailable += 1
            ops.get_abort()(
                phase_label,
                sale.item_id,
                sale.model_id,
                identity_failure,
            )
            continue
        previous_quantity = int(live_item.quantity)
        ops.get_sell_item()(sale.item_id, quoted_value)
        expected_quantity = max(0, previous_quantity - 1)
        (
            completed,
            post_sale_identity_failure,
            completion_reason,
        ) = yield from ops.get_confirm()(
            sale,
            expected_quantity,
            timeout_ms=350,
            step_ms=10,
        )
        if post_sale_identity_failure:
            counts.unavailable += 1
            ops.get_abort()(
                phase_label,
                sale.item_id,
                sale.model_id,
                completion_reason,
            )
            continue
        if not completed:
            counts.timeout_failures += 1
            ops.get_debug()(
                f"{phase_label} completion check failed: item_id={sale.item_id} "
                f"expected_quantity={expected_quantity} reason={completion_reason}."
            )
            continue
        counts.completed += 1
        yield from ops.get_wait()(40)
