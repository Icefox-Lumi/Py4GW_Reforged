from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, cast

from Py4GWCoreLib.Merchant import Trading
from Py4GWCoreLib.UIManager import TraderWindow
from Py4GWCoreLib.enums_src.GameData_enums import Profession
from Py4GWCoreLib.enums_src.Item_enums import ItemType
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot


@dataclass(slots=True)
class TraderQuote:
    item_id: int
    model_id: int
    item_type: ItemType
    name: str
    quoted_value: int
    profession: Profession = Profession._None
    is_material: bool = False
    is_rare_material: bool = False
    is_rune_mod: bool = False
    is_insignia: bool = False
    checked_at: float = 0.0


@dataclass(slots=True)
class TraderPriceCheckInput:
    quotes: dict[int, TraderQuote] = field(default_factory=dict)
    requested_item_ids: list[int] = field(default_factory=list)
    skipped_item_ids: list[int] = field(default_factory=list)
    failed_item_ids: list[int] = field(default_factory=list)

    @property
    def quotes_by_model_id(self) -> dict[int, TraderQuote]:
        return {quote.model_id: quote for quote in self.quotes.values()}

    def get_quote_by_model_id(self, model_id: int) -> Optional[TraderQuote]:
        return self.quotes_by_model_id.get(model_id)

    def reset(self) -> None:
        self.quotes.clear()
        self.requested_item_ids.clear()
        self.skipped_item_ids.clear()
        self.failed_item_ids.clear()


@dataclass(slots=True)
class _TraderPriceCheckState:
    pending_item_ids: list[int] = field(default_factory=list)
    current_item_id: Optional[int] = None
    quote_requested_at: float = 0.0
    requested: bool = False
    retries: dict[int, int] = field(default_factory=dict)
    initialized: bool = False

    def reset_current(self) -> None:
        self.current_item_id = None
        self.quote_requested_at = 0.0
        self.requested = False


class BTrees:
    NodeState = BehaviorTree.NodeState

    @staticmethod
    def _item_name(item: ItemSnapshot) -> str:
        if item.data and item.data.name:
            return item.data.name
        if item.names.plain:
            return item.names.plain
        return item.name or f"Item {item.id}"

    @staticmethod
    def _is_insignia(item: ItemSnapshot) -> bool:
        if item.item_type != ItemType.Rune_Mod:
            return False

        if item.data and item.data.name:
            return "insignia" in item.data.name.lower()

        return "insignia" in BTrees._item_name(item).lower()

    @staticmethod
    def _store_quote(output: TraderPriceCheckInput, item: ItemSnapshot, quoted_value: int, checked_at: float) -> None:
        output.quotes[item.id] = TraderQuote(
            item_id=item.id,
            model_id=item.model_id,
            item_type=item.item_type,
            name=BTrees._item_name(item),
            quoted_value=quoted_value,
            profession=item.data.profession if item.data and item.data.profession else item.profession,
            is_material=item.is_material,
            is_rare_material=item.is_rare_material,
            is_rune_mod=item.item_type == ItemType.Rune_Mod,
            is_insignia=BTrees._is_insignia(item),
            checked_at=checked_at,
        )

    class Trader:
        @staticmethod
        def CheckPrices(
            output: TraderPriceCheckInput,
            item_filter: Optional[Callable[[ItemSnapshot], bool]] = None,
            offered_item_ids: Optional[list[int]] = None,
            quote_timeout_ms: int = 750,
            max_retries: int = 1,
            clear_output: bool = True,
            succeed_if_empty: bool = True,
            blackboard_key: str = "item_manager_trader_price_check",
            aftercast_ms: int = 0,
        ):
            """
            Collect trader quotes over multiple BT ticks and write them into the provided output object.
            """
            def _check_prices(node: BehaviorTree.Node):
                now = time.monotonic()

                if not TraderWindow.IsOpen():
                    return BehaviorTree.NodeState.FAILURE

                state = cast(_TraderPriceCheckState | None, node.blackboard.get(blackboard_key))
                if state is None:
                    state = _TraderPriceCheckState()
                    node.blackboard[blackboard_key] = state

                if not state.initialized:
                    if clear_output:
                        output.reset()

                    available_item_ids = list(offered_item_ids) if offered_item_ids is not None else list(Trading.Trader.GetOfferedItems() or [])
                    matched_item_ids: list[int] = []

                    for item_id in available_item_ids:
                        item = ItemSnapshot.from_item_id(item_id)
                        if item is None or not item.is_valid:
                            output.skipped_item_ids.append(item_id)
                            continue

                        if item_filter and not item_filter(item):
                            continue

                        matched_item_ids.append(item_id)

                    state.pending_item_ids = matched_item_ids
                    state.initialized = True

                    if not state.pending_item_ids:
                        node.blackboard.pop(blackboard_key, None)
                        return BehaviorTree.NodeState.SUCCESS if succeed_if_empty else BehaviorTree.NodeState.FAILURE

                if state.current_item_id is None:
                    if not state.pending_item_ids:
                        node.blackboard.pop(blackboard_key, None)
                        return BehaviorTree.NodeState.SUCCESS

                    state.current_item_id = state.pending_item_ids.pop(0)
                    state.requested = False

                item_id = state.current_item_id
                if item_id is None:
                    return BehaviorTree.NodeState.RUNNING

                offered_items = Trading.Trader.GetOfferedItems() or []
                if item_id not in offered_items:
                    output.failed_item_ids.append(item_id)
                    state.reset_current()
                    return BehaviorTree.NodeState.RUNNING

                item = ItemSnapshot.from_item_id(item_id)
                if item is None or not item.is_valid:
                    output.failed_item_ids.append(item_id)
                    state.reset_current()
                    return BehaviorTree.NodeState.RUNNING

                if not state.requested:
                    Trading.Trader.RequestQuote(item_id)
                    state.quote_requested_at = now
                    state.requested = True
                    output.requested_item_ids.append(item_id)
                    return BehaviorTree.NodeState.RUNNING

                quote_available = Trading.Trader.GetQuotedItemID() == item_id
                quoted_value = Trading.Trader.GetQuotedValue()
                if quote_available and quoted_value is not None:
                    BTrees._store_quote(output, item, quoted_value, checked_at=time.time())
                    state.reset_current()
                    return BehaviorTree.NodeState.RUNNING

                if state.quote_requested_at and (now - state.quote_requested_at) * 1000 >= quote_timeout_ms:
                    retry_count = state.retries.get(item_id, 0)
                    if retry_count < max_retries:
                        state.retries[item_id] = retry_count + 1
                        state.requested = False
                        state.quote_requested_at = 0.0
                        return BehaviorTree.NodeState.RUNNING

                    output.failed_item_ids.append(item_id)
                    state.reset_current()
                    return BehaviorTree.NodeState.RUNNING

                return BehaviorTree.NodeState.RUNNING

            return BehaviorTree.ActionNode(name="ItemManager.Trader.CheckPrices", action_fn=_check_prices, aftercast_ms=aftercast_ms)

        @staticmethod
        def CheckMaterialPrices(
            output: TraderPriceCheckInput,
            include_common_materials: bool = True,
            include_rare_materials: bool = True,
            quote_timeout_ms: int = 750,
            max_retries: int = 1,
            clear_output: bool = True,
            succeed_if_empty: bool = True,
            blackboard_key: str = "item_manager_trader_material_price_check",
            aftercast_ms: int = 0,
        ):
            """
            Collect quotes for currently offered trader materials into the provided output object.
            """
            def _is_material(item: ItemSnapshot) -> bool:
                if include_common_materials and item.is_material and not item.is_rare_material:
                    return True
                if include_rare_materials and item.is_rare_material:
                    return True
                return False

            return BTrees.Trader.CheckPrices(
                output=output,
                item_filter=_is_material,
                quote_timeout_ms=quote_timeout_ms,
                max_retries=max_retries,
                clear_output=clear_output,
                succeed_if_empty=succeed_if_empty,
                blackboard_key=blackboard_key,
                aftercast_ms=aftercast_ms,
            )

        @staticmethod
        def CheckRuneAndInsigniaPrices(
            output: TraderPriceCheckInput,
            profession: Profession | None = None,
            include_runes: bool = True,
            include_insignias: bool = True,
            quote_timeout_ms: int = 750,
            max_retries: int = 1,
            clear_output: bool = True,
            succeed_if_empty: bool = True,
            blackboard_key: str = "item_manager_trader_rune_price_check",
            aftercast_ms: int = 0,
        ):
            """
            Collect quotes for currently offered rune and insignia trader items into the provided output object.
            """
            def _is_matching_rune_mod(item: ItemSnapshot) -> bool:
                if item.item_type != ItemType.Rune_Mod:
                    return False

                item_profession = item.data.profession if item.data and item.data.profession else item.profession
                if profession and profession != Profession._None and item_profession not in (profession, Profession._None):
                    return False

                is_insignia = BTrees._is_insignia(item)
                if is_insignia and not include_insignias:
                    return False
                if not is_insignia and not include_runes:
                    return False

                return True

            return BTrees.Trader.CheckPrices(
                output=output,
                item_filter=_is_matching_rune_mod,
                quote_timeout_ms=quote_timeout_ms,
                max_retries=max_retries,
                clear_output=clear_output,
                succeed_if_empty=succeed_if_empty,
                blackboard_key=blackboard_key,
                aftercast_ms=aftercast_ms,
            )

        @staticmethod
        def BuildMaterialPriceCheckTree(
            output: TraderPriceCheckInput,
            include_common_materials: bool = True,
            include_rare_materials: bool = True,
            quote_timeout_ms: int = 750,
            max_retries: int = 1,
            clear_output: bool = True,
            succeed_if_empty: bool = True,
            aftercast_ms: int = 0,
        ) -> BehaviorTree:
            return BehaviorTree(
                BTrees.Trader.CheckMaterialPrices(
                    output=output,
                    include_common_materials=include_common_materials,
                    include_rare_materials=include_rare_materials,
                    quote_timeout_ms=quote_timeout_ms,
                    max_retries=max_retries,
                    clear_output=clear_output,
                    succeed_if_empty=succeed_if_empty,
                    aftercast_ms=aftercast_ms,
                )
            )

        @staticmethod
        def BuildRuneAndInsigniaPriceCheckTree(
            output: TraderPriceCheckInput,
            profession: Profession | None = None,
            include_runes: bool = True,
            include_insignias: bool = True,
            quote_timeout_ms: int = 750,
            max_retries: int = 1,
            clear_output: bool = True,
            succeed_if_empty: bool = True,
            aftercast_ms: int = 0,
        ) -> BehaviorTree:
            return BehaviorTree(
                BTrees.Trader.CheckRuneAndInsigniaPrices(
                    output=output,
                    profession=profession,
                    include_runes=include_runes,
                    include_insignias=include_insignias,
                    quote_timeout_ms=quote_timeout_ms,
                    max_retries=max_retries,
                    clear_output=clear_output,
                    succeed_if_empty=succeed_if_empty,
                    aftercast_ms=aftercast_ms,
                )
            )


class TraderPriceCheckManager:
    _tree: Optional[BehaviorTree] = None
    _input: TraderPriceCheckInput = TraderPriceCheckInput()
    _kind: Optional[str] = None
    _generation: int = 0

    @classmethod
    def reset(cls) -> None:
        cls._tree = None
        cls._kind = None
        cls._input.reset()
        cls._generation += 1

    @classmethod
    def get_output(cls) -> TraderPriceCheckInput:
        return cls._input

    @classmethod
    def get_kind(cls) -> Optional[str]:
        return cls._kind if cls._kind is not None else cls._detect_kind()

    @classmethod
    def get_generation(cls) -> int:
        return cls._generation

    @classmethod
    def is_running(cls) -> bool:
        return cls._tree is not None

    @classmethod
    def is_ready_for_runes(cls) -> bool:
        return cls._kind == "runes" and (cls._tree is None or len(cls._input.quotes) > 0)

    @classmethod
    def _detect_kind(cls) -> Optional[str]:
        offered_items = Trading.Trader.GetOfferedItems() or []
        offered_item = ItemSnapshot.from_item_id(offered_items[0]) if offered_items else None

        if offered_item is None:
            return None

        if offered_item.item_type == ItemType.Rune_Mod:
            return "runes"

        if offered_item.item_type == ItemType.Materials_Zcoins:
            return "materials"

        return None

    @classmethod
    def _build_tree(cls, kind: str) -> Optional[BehaviorTree]:
        if kind == "runes":
            return BTrees.Trader.BuildRuneAndInsigniaPriceCheckTree(
                output=cls._input,
                clear_output=True,
            )

        if kind == "materials":
            return BTrees.Trader.BuildMaterialPriceCheckTree(
                output=cls._input,
                clear_output=True,
            )

        return None

    @classmethod
    def tick(cls) -> BehaviorTree.NodeState | None:
        if not TraderWindow.IsOpen():
            if cls._tree is not None or cls._kind is not None:
                cls.reset()
            return None

        kind = cls._detect_kind()
        if kind is None:
            if cls._tree is not None or cls._kind is not None:
                cls.reset()
            return None

        if cls._kind != kind:
            cls.reset()
            cls._kind = kind
            cls._tree = cls._build_tree(kind)

        if cls._tree is None:
            return None

        state = cls._tree.tick()
        if state != BehaviorTree.NodeState.RUNNING:
            cls._tree = None

        return state

    @classmethod
    def summary(cls) -> tuple[int, int, int]:
        return (
            len(cls._input.quotes),
            len(cls._input.failed_item_ids),
            len(cls._input.skipped_item_ids),
        )


__all__ = [
    "BTrees",
    "TraderPriceCheckManager",
    "TraderPriceCheckInput",
    "TraderQuote",
]
