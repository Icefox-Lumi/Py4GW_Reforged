"""Explain overlaps between configured Merchant Rules in their editor order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Protocol
from typing import cast

if TYPE_CHECKING:
    from Sources.icefox.MerchantRules.configuration import BuyRule
    from Sources.icefox.MerchantRules.configuration import DestroyRule
    from Sources.icefox.MerchantRules.configuration import MaterialTarget
    from Sources.icefox.MerchantRules.configuration import MerchantStockTarget
    from Sources.icefox.MerchantRules.configuration import RuneSellTarget
    from Sources.icefox.MerchantRules.configuration import RuneTraderTarget
    from Sources.icefox.MerchantRules.configuration import SellRule

type Get[T] = Callable[[], T]
type ModelLabel = Callable[[int], str]
type RuneLabel = Callable[[str], str]
type ModelKey = Callable[[object], tuple[str, int]]
type RarityLabels = Callable[[object], list[str]]
type RuleName = Callable[[object], str]


class IndexText(Protocol):
    def __call__(self, indices: list[int], limit: int = 3, rules: list[object] | None = None) -> str: ...


class Compact(Protocol):
    def __call__(self, labels: list[str], limit: int = 2) -> str: ...


@dataclass(frozen=True)
class OverlapPolicy:
    """Resolve the widget's current rule classifiers and normalizers on demand."""

    buy_rule: Get[Callable[[BuyRule], BuyRule | None]]
    sell_rule: Get[Callable[[SellRule], SellRule | None]]
    destroy_rule: Get[Callable[[DestroyRule], DestroyRule]]
    merchant_targets: Get[Callable[[object], list[MerchantStockTarget]]]
    material_targets: Get[Callable[[object], list[MaterialTarget]]]
    rune_buy_targets: Get[Callable[[object], list[RuneTraderTarget]]]
    rune_sell_targets: Get[Callable[[object], list[RuneSellTarget]]]
    is_scroll: Get[Callable[[object], bool]]
    BUY_KIND_MERCHANT_STOCK: Get[str]
    BUY_KIND_MATERIAL_TARGET: Get[str]
    BUY_KIND_RUNE_TRADER_TARGET: Get[str]
    BUY_KIND_SCROLL_TRADER_TARGET: Get[str]
    SELL_KIND_EXPLICIT_MODELS: Get[str]
    SELL_KIND_COMMON_MATERIALS: Get[str]
    SELL_KIND_RUNE_TRADER_TARGET: Get[str]
    SELL_KIND_WEAPONS: Get[str]
    SELL_KIND_ARMOR: Get[str]
    DESTROY_KIND_EXPLICIT_MODELS: Get[str]
    DESTROY_KIND_MATERIALS: Get[str]
    DESTROY_KIND_WEAPONS: Get[str]
    DESTROY_KIND_ARMOR: Get[str]


def format_indices(
    indices: list[int],
    limit: int = 3,
    rules: list[object] | None = None,
    *,
    name: Get[RuleName],
    compact: Get[Compact],
) -> str:
    labels: list[str] = []
    for index in indices:
        label = f"#{int(index) + 1}"
        if rules is not None and 0 <= int(index) < len(rules):
            custom_name = name()(rules[int(index)])
            if custom_name:
                label = f"{label} {custom_name}"
        labels.append(label)
    return compact()(labels, limit=limit)


def buy(
    policy: OverlapPolicy,
    *,
    buy_rows: Get[list[BuyRule]],
    indices: Get[IndexText],
    model_label: Get[ModelLabel],
    rune_label: Get[RuneLabel],
    model_key: Get[ModelKey],
) -> list[str]:
    diagnostics: list[str] = []
    merchant_stock_rules: dict[int, list[int]] = {}
    material_target_rules: dict[int, list[int]] = {}
    rune_target_rules: dict[str, list[int]] = {}
    scroll_target_rules: dict[int, list[int]] = {}
    for index, raw_rule in enumerate(buy_rows()):
        rule = policy.buy_rule()(raw_rule)
        if rule is None or not rule.enabled:
            continue
        if rule.kind == policy.BUY_KIND_MERCHANT_STOCK():
            for target in policy.merchant_targets()(rule.merchant_stock_targets):
                if int(target.model_id) > 0:
                    if policy.is_scroll()(target.model_id):
                        scroll_target_rules.setdefault(int(target.model_id), []).append(index)
                    else:
                        merchant_stock_rules.setdefault(int(target.model_id), []).append(index)
        elif rule.kind == policy.BUY_KIND_MATERIAL_TARGET():
            for target in policy.material_targets()(rule.material_targets):
                if int(target.model_id) > 0:
                    material_target_rules.setdefault(int(target.model_id), []).append(index)
        elif rule.kind == policy.BUY_KIND_RUNE_TRADER_TARGET():
            for target in policy.rune_buy_targets()(rule.rune_targets):
                if target.identifier:
                    rune_target_rules.setdefault(str(target.identifier), []).append(index)
        elif rule.kind == policy.BUY_KIND_SCROLL_TRADER_TARGET():
            for target in policy.merchant_targets()(rule.merchant_stock_targets):
                if policy.is_scroll()(target.model_id):
                    scroll_target_rules.setdefault(int(target.model_id), []).append(index)

    for model_id, rule_indices in sorted(merchant_stock_rules.items()):
        if len(rule_indices) < 2:
            continue
        diagnostics.append(
            f"{model_label()(model_id)} is maintained by buy rules "
            f"{indices()(rule_indices, rules=cast('list[object]', buy_rows()))}. "
            "Later rules only see leftovers after earlier ones update the simulated stock count."
        )
    for model_id, rule_indices in sorted(material_target_rules.items()):
        if len(rule_indices) < 2:
            continue
        diagnostics.append(
            f"{model_label()(model_id)} appears in buy rules "
            f"{indices()(rule_indices, rules=cast('list[object]', buy_rows()))}. "
            "Those rules stack on the same material target."
        )
    for identifier, rule_indices in sorted(rune_target_rules.items(), key=lambda row: rune_label()(row[0]).lower()):
        if len(rule_indices) < 2:
            continue
        diagnostics.append(
            f"{rune_label()(identifier)} is maintained by buy rules "
            f"{indices()(rule_indices, rules=cast('list[object]', buy_rows()))}. "
            "Later rules only see shortages left after earlier rune targets update the simulated stock."
        )
    for model_id, rule_indices in sorted(scroll_target_rules.items(), key=lambda row: model_key()(row[0])):
        if len(rule_indices) < 2:
            continue
        diagnostics.append(
            f"{model_label()(model_id)} is maintained by buy rules "
            f"{indices()(rule_indices, rules=cast('list[object]', buy_rows()))}. "
            "Later rules only see shortages left after earlier scroll trader targets update the simulated stock."
        )
    return diagnostics


def sell(
    policy: OverlapPolicy,
    *,
    sell_rows: Get[list[SellRule]],
    indices: Get[IndexText],
    model_label: Get[ModelLabel],
    rune_label: Get[RuneLabel],
    rarities: Get[RarityLabels],
    compact: Get[Compact],
) -> list[str]:
    diagnostics: list[str] = []
    explicit_model_rules: dict[int, list[int]] = {}
    material_rules: dict[int, list[int]] = {}
    rune_sell_rules: dict[str, list[int]] = {}
    weapon_rules: list[tuple[int, set[str]]] = []
    armor_rules: list[tuple[int, set[str]]] = []

    for index, raw_rule in enumerate(sell_rows()):
        rule = policy.sell_rule()(raw_rule)
        if rule is None:
            continue
        if not rule.enabled:
            continue
        if rule.kind == policy.SELL_KIND_EXPLICIT_MODELS():
            for model_id in rule.model_ids:
                explicit_model_rules.setdefault(int(model_id), []).append(index)
        elif rule.kind == policy.SELL_KIND_COMMON_MATERIALS():
            for model_id in rule.model_ids:
                material_rules.setdefault(int(model_id), []).append(index)
        elif rule.kind == policy.SELL_KIND_RUNE_TRADER_TARGET():
            for target in policy.rune_sell_targets()(getattr(rule, "rune_sell_targets", [])):
                if target.identifier:
                    rune_sell_rules.setdefault(str(target.identifier), []).append(index)
        elif rule.kind == policy.SELL_KIND_WEAPONS():
            weapon_rules.append((index, set(rarities()(rule))))
        elif rule.kind == policy.SELL_KIND_ARMOR():
            armor_rules.append((index, set(rarities()(rule))))

    for model_id, rule_indices in sorted(explicit_model_rules.items()):
        if len(rule_indices) < 2:
            continue
        diagnostics.append(
            f"{model_label()(model_id)} is listed in sell rules "
            f"{indices()(rule_indices, rules=cast('list[object]', sell_rows()))}. "
            "Earlier explicit-model rules allocate matching items first."
        )
    for model_id, rule_indices in sorted(material_rules.items()):
        if len(rule_indices) < 2:
            continue
        diagnostics.append(
            f"{model_label()(model_id)} appears in material sell rules "
            f"{indices()(rule_indices, rules=cast('list[object]', sell_rows()))}. "
            "Earlier material rules consume tradable batches first."
        )
    for identifier, rule_indices in sorted(rune_sell_rules.items(), key=lambda row: rune_label()(row[0]).lower()):
        if len(rule_indices) < 2:
            continue
        diagnostics.append(
            f"{rune_label()(identifier)} appears in rune sell rules "
            f"{indices()(rule_indices, rules=cast('list[object]', sell_rows()))}. "
            "Earlier rune rules allocate matching loose runes first."
        )

    def _append_equippable_overlap_messages(rule_kind_label: str, rule_infos: list[tuple[int, set[str]]]) -> None:
        for info_index, (left_index, left_rarities) in enumerate(rule_infos):
            for right_index, right_rarities in rule_infos[info_index + 1 :]:
                overlap = sorted(left_rarities & right_rarities)
                if not overlap:
                    continue
                diagnostics.append(
                    f"{rule_kind_label} rules "
                    f"{indices()([left_index, right_index], limit=2, rules=cast('list[object]', sell_rows()))} "
                    "both include "
                    f"{compact()(overlap, limit=3)}. Earlier rules allocate matching items first."
                )

    _append_equippable_overlap_messages("Weapon", weapon_rules)
    _append_equippable_overlap_messages("Armor", armor_rules)
    return diagnostics


def destroy(
    policy: OverlapPolicy,
    *,
    destroy_rows: Get[list[DestroyRule]],
    sell_rows: Get[list[SellRule]],
    buy_rows: Get[list[BuyRule]],
    indices: Get[IndexText],
    model_label: Get[ModelLabel],
    rarities: Get[RarityLabels],
    compact: Get[Compact],
) -> list[str]:
    diagnostics: list[str] = []
    destroy_explicit_rules: dict[int, list[int]] = {}
    destroy_material_rules: dict[int, list[int]] = {}
    destroy_weapon_rules: list[tuple[int, set[str]]] = []
    destroy_armor_rules: list[tuple[int, set[str]]] = []

    for index, raw_rule in enumerate(destroy_rows()):
        rule = policy.destroy_rule()(raw_rule)
        if not rule.enabled:
            continue
        if rule.kind == policy.DESTROY_KIND_EXPLICIT_MODELS():
            for model_id in rule.model_ids:
                destroy_explicit_rules.setdefault(int(model_id), []).append(index)
        elif rule.kind == policy.DESTROY_KIND_MATERIALS():
            for model_id in rule.model_ids:
                destroy_material_rules.setdefault(int(model_id), []).append(index)
        elif rule.kind == policy.DESTROY_KIND_WEAPONS():
            destroy_weapon_rules.append((index, set(rarities()(rule))))
        elif rule.kind == policy.DESTROY_KIND_ARMOR():
            destroy_armor_rules.append((index, set(rarities()(rule))))

    for model_id, rule_indices in sorted(destroy_explicit_rules.items()):
        if len(rule_indices) > 1:
            diagnostics.append(
                f"{model_label()(model_id)} is listed in destroy rules "
                f"{indices()(rule_indices, rules=cast('list[object]', destroy_rows()))}. "
                "Earlier destroy rules claim matching items first."
            )
    for model_id, rule_indices in sorted(destroy_material_rules.items()):
        if len(rule_indices) > 1:
            diagnostics.append(
                f"{model_label()(model_id)} appears in material destroy rules "
                f"{indices()(rule_indices, rules=cast('list[object]', destroy_rows()))}. "
                "Earlier destroy rules claim matching stacks first."
            )

    for destroy_index, destroy_rarities in destroy_weapon_rules:
        for sell_index, sell_rule in enumerate(sell_rows()):
            normalized_sell_rule = policy.sell_rule()(sell_rule)
            if (
                normalized_sell_rule is None
                or not normalized_sell_rule.enabled
                or normalized_sell_rule.kind != policy.SELL_KIND_WEAPONS()
            ):
                continue
            overlap = sorted(destroy_rarities & set(rarities()(normalized_sell_rule)))
            if overlap:
                diagnostics.append(
                    "Destroy rule "
                    f"{indices()([destroy_index], limit=1, rules=cast('list[object]', destroy_rows()))} "
                    "overlaps weapon sell rule "
                    f"{indices()([sell_index], limit=1, rules=cast('list[object]', sell_rows()))} on "
                    f"{compact()(overlap, limit=3)}. "
                    "Destroy claims matching items first."
                )
    for destroy_index, destroy_rarities in destroy_armor_rules:
        for sell_index, sell_rule in enumerate(sell_rows()):
            normalized_sell_rule = policy.sell_rule()(sell_rule)
            if (
                normalized_sell_rule is None
                or not normalized_sell_rule.enabled
                or normalized_sell_rule.kind != policy.SELL_KIND_ARMOR()
            ):
                continue
            overlap = sorted(destroy_rarities & set(rarities()(normalized_sell_rule)))
            if overlap:
                diagnostics.append(
                    "Destroy rule "
                    f"{indices()([destroy_index], limit=1, rules=cast('list[object]', destroy_rows()))} "
                    "overlaps armor sell rule "
                    f"{indices()([sell_index], limit=1, rules=cast('list[object]', sell_rows()))} on "
                    f"{compact()(overlap, limit=3)}. "
                    "Destroy claims matching items first."
                )

    for destroy_index, raw_rule in enumerate(destroy_rows()):
        destroy_rule = policy.destroy_rule()(raw_rule)
        if not destroy_rule.enabled:
            continue
        if destroy_rule.kind not in (policy.DESTROY_KIND_EXPLICIT_MODELS(), policy.DESTROY_KIND_MATERIALS()):
            continue
        destroy_model_ids = set(int(model_id) for model_id in destroy_rule.model_ids)
        if not destroy_model_ids:
            continue

        for sell_index, raw_sell_rule in enumerate(sell_rows()):
            sell_rule = policy.sell_rule()(raw_sell_rule)
            if sell_rule is None or not sell_rule.enabled:
                continue
            if sell_rule.kind not in (policy.SELL_KIND_EXPLICIT_MODELS(), policy.SELL_KIND_COMMON_MATERIALS()):
                continue
            overlap_ids = sorted(destroy_model_ids & set(int(model_id) for model_id in sell_rule.model_ids))
            if overlap_ids:
                diagnostics.append(
                    "Destroy rule "
                    f"{indices()([destroy_index], limit=1, rules=cast('list[object]', destroy_rows()))} "
                    "overlaps sell rule "
                    f"{indices()([sell_index], limit=1, rules=cast('list[object]', sell_rows()))} on "
                    f"{compact()([model_label()(model_id) for model_id in overlap_ids], limit=2)}. "
                    "Destroy claims matching items first."
                )

        for buy_index, raw_buy_rule in enumerate(buy_rows()):
            buy_rule = policy.buy_rule()(raw_buy_rule)
            if buy_rule is None or not buy_rule.enabled:
                continue
            buy_model_ids: set[int] = set()
            if buy_rule.kind == policy.BUY_KIND_MATERIAL_TARGET():
                buy_model_ids = {int(target.model_id) for target in buy_rule.material_targets}
            elif buy_rule.kind in (policy.BUY_KIND_MERCHANT_STOCK(), policy.BUY_KIND_SCROLL_TRADER_TARGET()):
                buy_model_ids = {int(target.model_id) for target in buy_rule.merchant_stock_targets}
            overlap_ids = sorted(destroy_model_ids & buy_model_ids)
            if overlap_ids:
                diagnostics.append(
                    "Destroy rule "
                    f"{indices()([destroy_index], limit=1, rules=cast('list[object]', destroy_rows()))} "
                    "overlaps buy rule "
                    f"{indices()([buy_index], limit=1, rules=cast('list[object]', buy_rows()))} on "
                    f"{compact()([model_label()(model_id) for model_id in overlap_ids], limit=2)}. "
                    "Post-destroy inventory is what buy planning will maintain."
                )

    return diagnostics
