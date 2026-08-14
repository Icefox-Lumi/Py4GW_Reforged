from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, cast

import Py4GW
import PySystem
from Py4GWCoreLib.Inventory import Inventory
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.UIManager import AnySalvageWindow, MerchantWindow, TraderWindow
from Py4GWCoreLib.enums_src.Item_enums import INVENTORY_BAGS, STORAGE_BAGS, Bags, ItemAction, ItemType, SalvageMode
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Py4GWCoreLib.py4gwcorelib_src.FrameCache import frame_cache
from Sources.frenkeyLib.ItemHandling.BTNodes import BTNodes
from Sources.frenkeyLib.ItemHandling.bag_sort import BagSortPlanner
from Sources.frenkeyLib.global_configs.InventoryConfig import InventoryConfig
from Sources.frenkeyLib.global_configs.Rule import ExtractUpgradeRule, BaseRule
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot

@dataclass(slots=True)
class InventoryPreviewEntry:
    item: ItemSnapshot
    action: Optional[ItemAction]
    rule: Optional[BaseRule]
    note: str = ""
    executable: bool = True


class InventoryBT:
    NodeState = BehaviorTree.NodeState

    _ACTIVE_NODE_KEY = "inventory_bt_active_node"
    _ACTIVE_ACTION_KEY = "inventory_bt_active_action"
    _ACTIVE_ITEM_IDS_KEY = "inventory_bt_active_item_ids"
    _EXTRACT_WARNING_CACHE_KEY = "inventory_bt_extract_warning_cache"
    _ITEM_COOLDOWNS_KEY = "inventory_bt_item_cooldowns"
    _ITEM_FAILURES_KEY = "inventory_bt_item_failures"
    _SUCCESS_COOLDOWN_TICKS = 1
    _FAILURE_COOLDOWN_TICKS = 15
    _MAX_CONSECUTIVE_FAILURES = 3

    ACTION_PRIORITY: tuple[ItemAction, ...] = (
        ItemAction.Sell_To_Merchant,
        ItemAction.Sell_To_Trader,
        ItemAction.Stash,
        ItemAction.Destroy,
        ItemAction.Drop,
        ItemAction.Use,
        ItemAction.Identify,
        ItemAction.Salvage_Common_Materials,
        ItemAction.Salvage_Rare_Materials,
        ItemAction.ExtractUpgrade,
    )

    def __init__(self, config: Optional[InventoryConfig] = None):
        self.config = config or InventoryConfig()
        self.tree = self.Build(self.config)

    def tick(self) -> BehaviorTree.NodeState:
        return self.tree.tick()

    def reset(self) -> None:
        self.tree.reset()
        self.tree.blackboard.pop(self._ACTIVE_NODE_KEY, None)
        self.tree.blackboard.pop(self._ACTIVE_ACTION_KEY, None)
        self.tree.blackboard.pop(self._ACTIVE_ITEM_IDS_KEY, None)
        self.tree.blackboard.pop(self._EXTRACT_WARNING_CACHE_KEY, None)
        self.tree.blackboard.pop(self._ITEM_COOLDOWNS_KEY, None)
        self.tree.blackboard.pop(self._ITEM_FAILURES_KEY, None)

    @classmethod
    def Build(cls, config: Optional[InventoryConfig] = None) -> BehaviorTree:
        inventory_config = config or InventoryConfig()
        return BehaviorTree(cls._build_root_node(inventory_config))

    @classmethod
    @frame_cache(category="InventoryBT", source_lib="Preview")
    def Preview(
        cls,
        config: Optional[InventoryConfig] = None,
        bags: Optional[Sequence[Bags]] = None,
    ) -> list[InventoryPreviewEntry]:
        inventory_config = config or InventoryConfig()
        preview_entries: list[InventoryPreviewEntry] = []
        preview_bags = list(bags) if bags is not None else INVENTORY_BAGS

        if not preview_bags:
            return preview_entries

        snapshot = ItemSnapshot.get_bags_snapshot(preview_bags)
        for bag in preview_bags:
            for item in snapshot.get(bag, {}).values():
                if item is None or not item.is_valid:
                    continue

                preview_entries.append(cls._build_preview_entry(inventory_config, item))

        return preview_entries

    @classmethod
    @frame_cache(category="InventoryBT", source_lib="GetExecuteableInventoryActions")
    def GetExecuteableInventoryActions(cls, config: InventoryConfig):
        entries = cls.Preview(config)
        return [
            entry for entry in entries
            if entry.executable and entry.action is not None and entry.action not in (ItemAction.NONE, ItemAction.Ignore)
        ]
    
    @classmethod
    @frame_cache(category="InventoryBT", source_lib="HasExecuteableInventoryActions")
    def HasExecuteableInventoryActions(cls, config: InventoryConfig) -> bool:
        entries = cls.Preview(config)
        return any(
             entry.executable and entry.action is not None and entry.action not in (ItemAction.NONE, ItemAction.Ignore)
             for entry in entries
        ) or cls._needs_inventory_sorting()
        
    @classmethod
    def _build_root_node(cls, config: InventoryConfig) -> BehaviorTree.Node:
        def _tick(node: BehaviorTree.Node) -> BehaviorTree.NodeState:            
            cls._advance_item_cooldowns(node.blackboard)
            cls._prune_item_failures(node.blackboard)
            active_node = cast(BehaviorTree.Node | None, node.blackboard.get(cls._ACTIVE_NODE_KEY))
            if active_node is not None:                
                active_node.blackboard = node.blackboard
                active_state = active_node.tick()

                if active_state == BehaviorTree.NodeState.RUNNING:
                    return BehaviorTree.NodeState.RUNNING

                active_item_ids = cast(list[int], node.blackboard.get(cls._ACTIVE_ITEM_IDS_KEY, []))
                active_action = cast(str | None, node.blackboard.get(cls._ACTIVE_ACTION_KEY))
                node.blackboard.pop(cls._ACTIVE_NODE_KEY, None)
                node.blackboard.pop(cls._ACTIVE_ITEM_IDS_KEY, None)

                if active_state == BehaviorTree.NodeState.FAILURE:
                    cls._record_item_failure(node.blackboard, active_item_ids, active_action)
                    cls._set_item_cooldown(node.blackboard, active_item_ids, cls._FAILURE_COOLDOWN_TICKS)
                    node.blackboard.pop(cls._ACTIVE_ACTION_KEY, None)
                    return BehaviorTree.NodeState.FAILURE

                cls._clear_item_failure(node.blackboard, active_item_ids, active_action)
                cls._set_item_cooldown(node.blackboard, active_item_ids, cls._SUCCESS_COOLDOWN_TICKS)
                node.blackboard.pop(cls._ACTIVE_ACTION_KEY, None)
                return active_state

            action_batches = cls._collect_action_batches(config, node.blackboard)
            if not action_batches:
                if cls._needs_inventory_sorting():
                    if cls._should_defer_sorting(node.blackboard):
                        return BehaviorTree.NodeState.RUNNING

                    action_node = BagSortPlanner.BuildSortBagsNode(INVENTORY_BAGS)
                    PySystem.Console.Log(
                        "InventoryBT",
                        "Dispatching inventory sort maintenance.",
                        PySystem.Console.MessageType.Info,
                    )
                    node.blackboard[cls._ACTIVE_NODE_KEY] = action_node
                    node.blackboard[cls._ACTIVE_ACTION_KEY] = "SortInventory"
                    node.blackboard[cls._ACTIVE_ITEM_IDS_KEY] = []
                    action_node.blackboard = node.blackboard
                    return action_node.tick()

                return BehaviorTree.NodeState.SUCCESS

            for action in cls.ACTION_PRIORITY:
                item_ids = action_batches.get(action, [])
                if not item_ids:
                    continue

                action_node, active_item_ids = cls._build_action_node(config, action, item_ids, node.blackboard)
                if action_node is None:
                    continue

                PySystem.Console.Log(
                    "InventoryBT",
                    f"Dispatching {action.name} for {len(item_ids)} item(s).",
                    PySystem.Console.MessageType.Info,
                )

                node.blackboard[cls._ACTIVE_NODE_KEY] = action_node
                node.blackboard[cls._ACTIVE_ACTION_KEY] = action.name
                node.blackboard[cls._ACTIVE_ITEM_IDS_KEY] = active_item_ids
                action_node.blackboard = node.blackboard
                return action_node.tick()

            if cls._needs_inventory_sorting():
                if cls._should_defer_sorting(node.blackboard):
                    return BehaviorTree.NodeState.RUNNING

                action_node = BagSortPlanner.BuildSortBagsNode(INVENTORY_BAGS)
                PySystem.Console.Log(
                    "InventoryBT",
                    "Dispatching inventory sort maintenance after blocked item actions.",
                    PySystem.Console.MessageType.Info,
                )
                node.blackboard[cls._ACTIVE_NODE_KEY] = action_node
                node.blackboard[cls._ACTIVE_ACTION_KEY] = "SortInventory"
                node.blackboard[cls._ACTIVE_ITEM_IDS_KEY] = []
                action_node.blackboard = node.blackboard
                return action_node.tick()

            return BehaviorTree.NodeState.SUCCESS

        return BehaviorTree.ActionNode(name="InventoryBT.ProcessInventory", action_fn=_tick)

    @classmethod
    def _collect_action_batches(cls, config: InventoryConfig, blackboard: Optional[dict] = None) -> dict[ItemAction, list[int]]:
        action_batches: dict[ItemAction, list[int]] = {}
        item_cooldowns = cast(dict[int, int], blackboard.setdefault(cls._ITEM_COOLDOWNS_KEY, {})) if blackboard is not None else {}
        inventory_item_ids = cls._get_inventory_item_ids()

        if item_cooldowns:
            current_item_ids = set(inventory_item_ids)
            stale_item_ids = [item_id for item_id in item_cooldowns if item_id not in current_item_ids]
            for item_id in stale_item_ids:
                item_cooldowns.pop(item_id, None)

        for item_id in inventory_item_ids:
            if item_cooldowns.get(item_id, 0) > 0:
                continue

            action = cls._get_action_for_item(config, item_id)
            if action in (None, ItemAction.NONE, ItemAction.Ignore, ItemAction.Hold):
                continue

            if blackboard is not None and cls._is_item_blocked_after_failures(blackboard, item_id, action):
                continue

            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item:
                continue

            if action in (ItemAction.Salvage_Common_Materials, ItemAction.Salvage_Rare_Materials) and not item.is_salvageable:
                continue

            if action == ItemAction.ExtractUpgrade:
                if cls._get_single_extractable_match(config, item_id, blackboard) is None:
                    continue
            
            if action == ItemAction.Stash:
                depositable_item_ids = cls._get_depositable_item_ids([item_id])
                if item_id not in depositable_item_ids:
                    continue

            action_batches.setdefault(action, []).append(item_id)

        return action_batches

    @classmethod
    def _build_preview_entry(cls, config: InventoryConfig, item: ItemSnapshot) -> InventoryPreviewEntry:
        rule = cls._get_first_matching_rule(config, item.id)
        if rule is None:
            return InventoryPreviewEntry(item=item, action=None, rule=None, note="No matching rule.", executable=False)

        action = cls._get_rule_action(rule, item.id)
        if action in (ItemAction.NONE, ItemAction.Ignore, ItemAction.Hold):
            return InventoryPreviewEntry(
                item=item,
                action=action,
                rule=rule,
                note="No inventory action will be executed.",
                executable=False,
            )

        if not cls._is_action_dispatchable(action):
            return InventoryPreviewEntry(
                item=item,
                action=action,
                rule=rule,
                note=cls._get_blocked_action_note(action),
                executable=False,
            )

        if action == ItemAction.Stash:
            depositable_item_ids = cls._get_depositable_item_ids([item.id])
            if item.id not in depositable_item_ids:
                return InventoryPreviewEntry(
                    item=item,
                    action=action,
                    rule=rule,
                    note="Skipped because the full item quantity does not fit in storage or material storage.",
                    executable=False,
            )

        if action in (ItemAction.Salvage_Common_Materials, ItemAction.Salvage_Rare_Materials) and not item.is_salvageable:
            return InventoryPreviewEntry(
                item=item,
                action=action,
                rule=rule,
                note="Skipped because the item is not salvageable.",
                executable=False,
            )

        if action == ItemAction.ExtractUpgrade:
            matches = rule.get_matching_upgrades(item.id) if isinstance(rule, ExtractUpgradeRule) else []
            if len(matches) == 1 and item.is_salvageable and item.item_type is not ItemType.Rune_Mod:
                _, salvage_mode = matches[0]
                return InventoryPreviewEntry(
                    item=item,
                    action=action,
                    rule=rule,
                    note=f"Will extract {cls._format_upgrade_match_name(salvage_mode, item.id)}.",
                )

            elif len(matches) > 1:
                match_names = ", ".join(cls._format_upgrade_match_name(salvage_mode, item.id) for _, salvage_mode in matches)
                return InventoryPreviewEntry(
                    item=item,
                    action=action,
                    rule=rule,
                    note=f"Skipped because multiple upgrades match: {match_names}.",
                    executable=False,
                )
                
            elif not item.is_salvageable or item.item_type is ItemType.Rune_Mod:
                return InventoryPreviewEntry(
                    item=item,
                    action=action,
                    rule=rule,
                    note="Skipped because the item is not salvageable or is an Upgrade.",
                    executable=False,
                )

            return InventoryPreviewEntry(
                item=item,
                action=action,
                rule=rule,
                note="Skipped because no extractable upgrade matched the rule.",
                executable=False,
            )

        if isinstance(rule, ExtractUpgradeRule) and item.item_type is ItemType.Rune_Mod:
            return InventoryPreviewEntry(
                item=item,
                action=action,
                rule=rule,
                note=f"Already extracted upgrade matched the rule. Using {action.name}.",
            )

        return InventoryPreviewEntry(item=item, action=action, rule=rule, note="")

    @staticmethod
    def _get_inventory_item_ids() -> list[int]:
        items = ItemSnapshot.get_bags_items(INVENTORY_BAGS)
        item_ids: list[int] = []

        for item in items:
            if item is None or not item.is_valid or not item.is_inventory_item:
                continue
            
            if item.is_customized:
                continue

            item_ids.append(item.id)

        return item_ids

    @classmethod
    def _get_action_for_item(cls, config: InventoryConfig, item_id: int) -> Optional[ItemAction]:
        rule = cls._get_first_matching_rule(config, item_id)
        if rule is None:
            return None

        return cls._get_rule_action(rule, item_id)

    @staticmethod
    def _get_rule_action(rule: BaseRule, item_id: int) -> ItemAction:
        if isinstance(rule, ExtractUpgradeRule):
            return rule.get_effective_action(item_id)

        return rule.action

    @classmethod
    def _needs_inventory_sorting(cls) -> bool:
        snapshot = ItemSnapshot.get_bags_snapshot(INVENTORY_BAGS)
        planned_layout = BagSortPlanner.GetPlannedBagLayout(INVENTORY_BAGS)

        for bag in INVENTORY_BAGS:
            current_bag = snapshot.get(bag, {})
            planned_bag = planned_layout.get(bag, {})

            for slot in sorted(current_bag.keys()):
                current_item = current_bag.get(slot)
                planned_item = planned_bag.get(slot)

                current_signature = (
                    current_item.id,
                    current_item.quantity,
                ) if current_item is not None and current_item.is_valid else None
                planned_signature = (
                    planned_item.id,
                    planned_item.quantity,
                ) if planned_item is not None and planned_item.is_valid else None

                if current_signature != planned_signature:
                    return True

        return False

    @staticmethod
    def _get_first_matching_rule(config: InventoryConfig, item_id: int) -> Optional[BaseRule]:
        if item_id in config.blacklisted_items:
            return None

        for rule in config:
            if rule.applies(item_id):
                return rule

        return None

    @classmethod
    def _build_action_node(
        cls,
        config: InventoryConfig,
        action: ItemAction,
        item_ids: list[int],
        blackboard: Optional[dict] = None,
    ) -> tuple[Optional[BehaviorTree | BehaviorTree.Node], list[int]]:
        if not cls._is_action_dispatchable(action):
            return None, []

        valid_item_ids = cls._get_valid_inventory_item_ids(item_ids)
        if not valid_item_ids:
            return None, []

        match action:
            case ItemAction.Identify:
                unidentified_item_ids = cls._get_unidentified_inventory_item_ids(valid_item_ids)
                if not unidentified_item_ids:
                    return None, []
                return BTNodes.Items.IdentifyItems(unidentified_item_ids), unidentified_item_ids
            
            case ItemAction.Use:
                return BTNodes.Items.UseItems(valid_item_ids), valid_item_ids
            
            case ItemAction.Drop:
                if Map.IsExplorable():
                    return BTNodes.Items.DropItems(valid_item_ids), valid_item_ids
            
            case ItemAction.Destroy:
                return BTNodes.Items.DestroyItems(valid_item_ids), valid_item_ids
            
            case ItemAction.Stash:
                if Map.IsOutpost() or Map.IsGuildHall():
                    instructions = BTNodes.Items.GetTransferInstructions(
                        valid_item_ids,
                        STORAGE_BAGS,  # type: ignore[arg-type]
                        fill_materials_first=True,
                    )
                    depositable_item_ids = cls._planned_transfer_item_ids(instructions)
                    if depositable_item_ids:
                        return BTNodes.Items.DepositItems(
                            depositable_item_ids,
                            target=STORAGE_BAGS,  # type: ignore[arg-type]
                            fill_materials_first=True,
                        ), depositable_item_ids
            
            case ItemAction.Sell_To_Merchant:
                if MerchantWindow.IsOpen():
                    return BTNodes.Merchant.SellItems(valid_item_ids), valid_item_ids
                
            case ItemAction.Sell_To_Trader:
                if TraderWindow.IsOpen():
                    sell_requests, active_item_ids = cls._build_trader_sell_requests(valid_item_ids)
                    if sell_requests:
                        return cls._build_trader_sell_items_node(sell_requests), active_item_ids
            
            case ItemAction.Salvage_Common_Materials:
                salvageable_item_ids = cls._get_salvageable_inventory_item_ids(valid_item_ids)
                if salvageable_item_ids:
                    return cls._build_salvage_items_node(
                        salvageable_item_ids,
                        SalvageMode.LesserCraftingMaterials,
                        allow_expert_for_common_materials=True,
                    ), salvageable_item_ids
                    
            case ItemAction.Salvage_Rare_Materials:
                salvageable_item_ids = cls._get_salvageable_inventory_item_ids(valid_item_ids)
                if salvageable_item_ids:
                    return cls._build_salvage_items_node(
                        salvageable_item_ids,
                        SalvageMode.RareCraftingMaterials,
                    ), salvageable_item_ids
                
            case ItemAction.ExtractUpgrade:
                item_id, salvage_mode = cls._get_first_extractable_item(config, valid_item_ids, blackboard)
                if item_id is not None and salvage_mode is not None:
                    return BTNodes.Items.SalvageItem(
                        item_id,
                        salvage_mode=salvage_mode,
                        state_key=f"inventory_bt_extract_{item_id}",
                        debug_enabled=True,
                    ), [item_id]
            
            case _:
                return None, []

        return None, []

    @staticmethod
    def _planned_transfer_item_ids(instructions) -> list[int]:
        """Collect planned item ids from a BTNodes transfer-instruction tree."""
        planned_item_ids: list[int] = []
        if not instructions:
            return planned_item_ids
        for bag_instructions in instructions.values():
            for destination in bag_instructions.values():
                for item, _quantity in getattr(destination, "items", []) or []:
                    planned_item_ids.append(item.id)
        return planned_item_ids

    @classmethod
    def _get_depositable_item_ids(cls, item_ids: list[int]) -> list[int]:
        try:
            instructions = BTNodes.Items.GetTransferInstructions(
                list(item_ids),
                STORAGE_BAGS,  # type: ignore[arg-type]
                fill_materials_first=True,
            )
            return cls._planned_transfer_item_ids(instructions)
        except Exception:
            return []

    @staticmethod
    def _build_salvage_items_node(
        item_ids: list[int],
        salvage_mode: SalvageMode,
        allow_expert_for_common_materials: bool = False,
    ) -> Optional[BehaviorTree.Node]:
        children = [
            BTNodes.Items.SalvageItem(
                item_id,
                salvage_mode=salvage_mode,
                allow_expert_for_common_materials=allow_expert_for_common_materials,
                state_key=f"inventory_bt_salvage_{item_id}",
                debug_enabled=True,
            )
            for item_id in item_ids
        ]
        if not children:
            return None
        if len(children) == 1:
            return children[0]
        return BehaviorTree.SequenceNode(children, name="InventoryBT.SalvageBatch")

    @staticmethod
    def _isolate_trader_progress(child: BehaviorTree.Node) -> BehaviorTree.Node:
        """Wrap a Trader.SellItem node so its shared blackboard progress key is
        cleared before every tick, keeping sequential batch entries independent."""
        def _run(node: BehaviorTree.Node) -> BehaviorTree.NodeState:
            node.blackboard.pop("trader_sell_progress", None)
            child.blackboard = node.blackboard
            return child.tick()

        return BehaviorTree.ActionNode(action_fn=_run, name=child.name)

    @staticmethod
    def _build_trader_sell_items_node(
        sell_requests: list[tuple[int, int]],
    ) -> Optional[BehaviorTree.Node]:
        if not sell_requests:
            return None
        children = [
            InventoryBT._isolate_trader_progress(
                BTNodes.Trader.SellItem(item_id, quantity)
            )
            for item_id, quantity in sell_requests
        ]
        if len(children) == 1:
            return children[0]
        return BehaviorTree.SequenceNode(children, name="InventoryBT.TraderSellBatch")

    @staticmethod
    def _is_action_dispatchable(action: ItemAction) -> bool:
        match action:
            case ItemAction.Drop:
                return Map.IsExplorable()
            case ItemAction.Stash:
                return Map.IsOutpost() or Map.IsGuildHall()
            case ItemAction.Sell_To_Merchant:
                return MerchantWindow.IsOpen()
            case ItemAction.Sell_To_Trader:
                return TraderWindow.IsOpen()
            case _:
                return True

    @staticmethod
    def _get_blocked_action_note(action: ItemAction) -> str:
        match action:
            case ItemAction.Drop:
                return "Waiting until the item can be processed in an explorable area."
            case ItemAction.Stash:
                return "Waiting until storage is available in an outpost or guild hall."
            case ItemAction.Sell_To_Merchant:
                return "Waiting until a merchant window is open."
            case ItemAction.Sell_To_Trader:
                return "Waiting until a trader window is open."
            case _:
                return "Waiting until the action can be dispatched."

    @staticmethod
    def _get_valid_inventory_item_ids(item_ids: Sequence[int]) -> list[int]:
        valid_item_ids: list[int] = []
        for item_id in item_ids:
            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item:
                continue
            valid_item_ids.append(item_id)
        return valid_item_ids

    @staticmethod
    def _get_unidentified_inventory_item_ids(item_ids: Sequence[int]) -> list[int]:
        unidentified_item_ids: list[int] = []
        for item_id in item_ids:
            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item or item.is_identified:
                continue
            unidentified_item_ids.append(item_id)
        return unidentified_item_ids

    @staticmethod
    def _get_salvageable_inventory_item_ids(item_ids: Sequence[int]) -> list[int]:
        salvageable_item_ids: list[int] = []
        for item_id in item_ids:
            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item or not item.is_salvageable:
                continue
            salvageable_item_ids.append(item_id)
        return salvageable_item_ids

    @staticmethod
    def _build_trader_sell_requests(item_ids: Sequence[int]) -> tuple[list[tuple[int, int]], list[int]]:
        sell_requests: list[tuple[int, int]] = []
        active_item_ids: list[int] = []

        for item_id in item_ids:
            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item or item.quantity <= 0:
                continue
            sell_requests.append((item_id, item.quantity))
            active_item_ids.append(item_id)

        return sell_requests, active_item_ids

    @classmethod
    def _get_first_extractable_item(
        cls,
        config: InventoryConfig,
        item_ids: list[int],
        blackboard: Optional[dict] = None,
    ) -> tuple[Optional[int], Optional[SalvageMode]]:
        for item_id in item_ids:
            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item or not item.is_salvageable:
                continue

            match = cls._get_single_extractable_match(config, item_id, blackboard)
            if match is not None:
                _, salvage_mode = match
                return item_id, salvage_mode

        return None, None

    @staticmethod
    def _format_upgrade_match_name(salvage_mode: SalvageMode, item_id: int) -> str:
        item = ItemSnapshot.from_item_id(item_id)
        if item is None:
            return salvage_mode.name

        if salvage_mode == SalvageMode.Prefix and item.prefix is not None:
            return f"{salvage_mode.name}: {type(item.prefix).__name__}"

        if salvage_mode == SalvageMode.Suffix and item.suffix is not None:
            return f"{salvage_mode.name}: {type(item.suffix).__name__}"

        if salvage_mode == SalvageMode.Inscription and item.inscription is not None:
            return f"{salvage_mode.name}: {type(item.inscription).__name__}"

        return salvage_mode.name

    @classmethod
    def _get_single_extractable_match(
        cls,
        config: InventoryConfig,
        item_id: int,
        blackboard: Optional[dict] = None,
    ) -> Optional[tuple[object, SalvageMode]]:
        rule = cls._get_first_matching_rule(config, item_id)
        if not isinstance(rule, ExtractUpgradeRule):
            return None

        matches = rule.get_matching_upgrades(item_id)
        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            cls._log_ambiguous_extract_upgrade(item_id, rule, matches, blackboard)

        return None

    @classmethod
    def _log_ambiguous_extract_upgrade(
        cls,
        item_id: int,
        rule: ExtractUpgradeRule,
        matches: Sequence[tuple[object, SalvageMode]],
        blackboard: Optional[dict],
    ) -> None:
        if blackboard is not None:
            warning_cache = cast(set[int], blackboard.setdefault(cls._EXTRACT_WARNING_CACHE_KEY, set()))
            if item_id in warning_cache:
                return
            warning_cache.add(item_id)

        item = ItemSnapshot.from_item_id(item_id)
        item_name = item.names.plain if item is not None and item.names.plain else f"Item {item_id}"
        match_names = ", ".join(cls._format_upgrade_match_name(salvage_mode, item_id) for _, salvage_mode in matches)

        PySystem.Console.Log(
            "InventoryBT",
            f"Skipping upgrade extraction for '{item_name}' (ID: {item_id}) because rule '{rule.name or type(rule).__name__}' matched multiple upgrades: {match_names}.",
            PySystem.Console.MessageType.Warning,
        )

    @classmethod
    def _advance_item_cooldowns(cls, blackboard: dict) -> None:
        item_cooldowns = cast(dict[int, int], blackboard.setdefault(cls._ITEM_COOLDOWNS_KEY, {}))
        expired_item_ids: list[int] = []

        for item_id, remaining_ticks in item_cooldowns.items():
            next_ticks = remaining_ticks - 1
            if next_ticks <= 0:
                expired_item_ids.append(item_id)
            else:
                item_cooldowns[item_id] = next_ticks

        for item_id in expired_item_ids:
            item_cooldowns.pop(item_id, None)

    @classmethod
    def _set_item_cooldown(cls, blackboard: dict, item_ids: Sequence[int], ticks: int) -> None:
        if ticks <= 0:
            return

        item_cooldowns = cast(dict[int, int], blackboard.setdefault(cls._ITEM_COOLDOWNS_KEY, {}))
        for item_id in item_ids:
            item_cooldowns[item_id] = max(ticks, item_cooldowns.get(item_id, 0))

    @staticmethod
    def _is_salvage_action_name(action_name: Optional[str]) -> bool:
        return action_name in {
            ItemAction.Salvage_Common_Materials.name,
            ItemAction.Salvage_Rare_Materials.name,
            ItemAction.ExtractUpgrade.name,
        }

    @staticmethod
    def _native_salvage_is_active() -> bool:
        try:
            inventory_instance = Inventory.inventory_instance()
        except Exception:
            return False

        try:
            is_salvaging = getattr(inventory_instance, "IsSalvaging", None)
            if callable(is_salvaging) and bool(is_salvaging()):
                return True
        except Exception:
            pass

        try:
            transaction_done = getattr(inventory_instance, "IsSalvageTransactionDone", None)
            if callable(transaction_done) and bool(transaction_done()):
                return True
        except Exception:
            pass

        return False

    @classmethod
    def _should_defer_sorting(cls, blackboard: dict) -> bool:
        active_action = cast(Optional[str], blackboard.get(cls._ACTIVE_ACTION_KEY))
        if cls._is_salvage_action_name(active_action):
            return True

        if AnySalvageWindow.IsOpen():
            return True

        return cls._native_salvage_is_active()

    @staticmethod
    def _format_item_for_log(item_id: int) -> str:
        item = ItemSnapshot.from_item_id(item_id)
        if item is None:
            return f"id={item_id} missing"

        item_name = item.names.plain if item.names.plain and item.names.plain != item.names.fallback else item.complete_name or "Unknown Item"
        return f"id={item.id} name='{item_name}' model={item.model_id}"

    @staticmethod
    def _get_item_failure_signature(item: ItemSnapshot, action: ItemAction) -> tuple[object, ...]:
        return (
            action.name,
            item.model_id,
            item.quantity,
            item.slot,
            item.bag.value if item.bag is not None else -1,
            item.is_identified,
            item.is_salvageable,
            item.is_inventory_item,
        )

    @classmethod
    def _prune_item_failures(cls, blackboard: dict) -> None:
        item_failures = cast(dict[int, tuple[tuple[object, ...], int]], blackboard.setdefault(cls._ITEM_FAILURES_KEY, {}))
        if not item_failures:
            return

        stale_item_ids: list[int] = []
        for item_id, (stored_signature, _) in item_failures.items():
            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item:
                stale_item_ids.append(item_id)
                continue

            action_name = stored_signature[0] if stored_signature else None
            if not isinstance(action_name, str) or action_name not in ItemAction.__members__:
                stale_item_ids.append(item_id)
                continue

            action = ItemAction[action_name]
            current_signature = cls._get_item_failure_signature(item, action)
            if current_signature != stored_signature:
                stale_item_ids.append(item_id)

        for item_id in stale_item_ids:
            item_failures.pop(item_id, None)

    @classmethod
    def _record_item_failure(cls, blackboard: dict, item_ids: Sequence[int], action_name: Optional[str]) -> None:
        if not action_name or action_name not in ItemAction.__members__:
            return

        action = ItemAction[action_name]
        item_failures = cast(dict[int, tuple[tuple[object, ...], int]], blackboard.setdefault(cls._ITEM_FAILURES_KEY, {}))

        for item_id in item_ids:
            item = ItemSnapshot.from_item_id(item_id)
            if item is None or not item.is_valid or not item.is_inventory_item:
                item_failures.pop(item_id, None)
                continue

            signature = cls._get_item_failure_signature(item, action)
            previous_signature, previous_count = item_failures.get(item_id, ((), 0))
            next_count = previous_count + 1 if previous_signature == signature else 1
            item_failures[item_id] = (signature, next_count)

            PySystem.Console.Log(
                "InventoryBT",
                f"{action.name} failed for {cls._format_item_for_log(item_id)}. consecutive_failures={next_count}/{cls._MAX_CONSECUTIVE_FAILURES}.",
                PySystem.Console.MessageType.Warning,
            )

            if next_count == cls._MAX_CONSECUTIVE_FAILURES:
                PySystem.Console.Log(
                    "InventoryBT",
                    f"Suppressing {action.name} retries for {cls._format_item_for_log(item_id)} after {next_count} identical failures. Retries resume when the item changes.",
                    PySystem.Console.MessageType.Warning,
                )

    @classmethod
    def _clear_item_failure(cls, blackboard: dict, item_ids: Sequence[int], action_name: Optional[str]) -> None:
        item_failures = cast(dict[int, tuple[tuple[object, ...], int]], blackboard.setdefault(cls._ITEM_FAILURES_KEY, {}))
        if not item_failures:
            return

        for item_id in item_ids:
            if action_name is None:
                item_failures.pop(item_id, None)
                continue

            stored = item_failures.get(item_id)
            if stored is None:
                continue

            stored_signature, _ = stored
            stored_action_name = stored_signature[0] if stored_signature else None
            if stored_action_name == action_name:
                item_failures.pop(item_id, None)

    @classmethod
    def _is_item_blocked_after_failures(cls, blackboard: dict, item_id: int, action: ItemAction) -> bool:
        item_failures = cast(dict[int, tuple[tuple[object, ...], int]], blackboard.setdefault(cls._ITEM_FAILURES_KEY, {}))
        stored = item_failures.get(item_id)
        if stored is None:
            return False

        stored_signature, failure_count = stored
        if failure_count < cls._MAX_CONSECUTIVE_FAILURES:
            return False

        item = ItemSnapshot.from_item_id(item_id)
        if item is None or not item.is_valid or not item.is_inventory_item:
            item_failures.pop(item_id, None)
            return False

        current_signature = cls._get_item_failure_signature(item, action)
        if current_signature != stored_signature:
            item_failures.pop(item_id, None)
            return False

        return True


__all__ = ["InventoryBT", "InventoryPreviewEntry"]
