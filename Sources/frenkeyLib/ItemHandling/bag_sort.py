"""Synchronous bag-sort planner, restored from the legacy BTItems.Bags catalog.

Reforged removed ``BT.Items.Bags.GetBagSortPlan``, ``GetPlannedBagLayout`` and
``CreateBagSortPlanTree``, and its ``BTNodes.Bags.SortBags`` is a provisional
rewrite that ignores the configured sort groups. This module ports the legacy
planner onto the current ``ItemSnapshot`` and ``SortingConfig`` surfaces so the
ItemManager sorting preview, the Sort Selected action, and InventoryBT's
auto-sort maintenance all agree on one plan.
"""

from typing import Optional

from Py4GWCoreLib.Inventory import Inventory
from Py4GWCoreLib.enums_src.Item_enums import Bags
from Py4GWCoreLib.py4gwcorelib_src.BehaviorTree import BehaviorTree
from Sources.frenkeyLib.global_configs.SortingConfig import (
    BagSortPlan,
    BagSortPreviewEntry,
    SlotGroupConfig,
    SortingConfig,
)
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot


class BagSortPlanner:
    @staticmethod
    def GetBagSortPlan(
        bags: list[Bags],
        sorting_config: Optional[SortingConfig] = None,
    ) -> BagSortPlan:
        snapshot = ItemSnapshot.get_bags_snapshot(bags)
        config = sorting_config or SortingConfig()
        plan = BagSortPlan()
        remaining_items: list[ItemSnapshot] = [
            item
            for bag in bags
            for _, item in sorted(snapshot.get(bag, {}).items())
            if item is not None and item.is_valid
        ]
        occupied_slots: set[tuple[Bags, int]] = set()

        for bag in bags:
            plan.layout[bag] = {
                slot: None
                for slot in sorted(snapshot.get(bag, {}).keys())
            }

        explicit_groups: list[tuple[Bags, SlotGroupConfig, list[int]]] = []
        for bag in bags:
            bag_groups = sorted(
                config.get_groups_for_bag(bag),
                key=lambda group: min(group.normalized_slots_for_bag(bag))
                if group.normalized_slots_for_bag(bag)
                else 9999,
            )
            for group in bag_groups:
                slots = [
                    slot
                    for slot in group.normalized_slots_for_bag(bag)
                    if slot in plan.layout.get(bag, {}) and (bag, slot) not in occupied_slots
                ]
                if not slots:
                    continue

                explicit_groups.append((bag, group, slots))
                occupied_slots.update((bag, slot) for slot in slots)

        for bag, group, slots in explicit_groups:
            matching_items = sorted(
                [item for item in remaining_items if group.matches(item)],
                key=lambda item: group.sorter.get_sort_key(item),
            )

            for slot_index, slot in enumerate(slots):
                planned_item = matching_items[slot_index] if slot_index < len(matching_items) else None
                if planned_item is not None:
                    remaining_items.remove(planned_item)

                plan.layout[bag][slot] = planned_item
                plan.entries.append(
                    BagSortPreviewEntry(
                        bag=bag,
                        slot=slot,
                        item=planned_item,
                        source_bag=planned_item.bag if planned_item is not None else None,
                        source_slot=planned_item.slot if planned_item is not None else None,
                        group_name=group.display_name(),
                        group_summary=group.matcher.summary(),
                        sorter=group.sorter,
                        used_fallback=False,
                    )
                )

        default_slots = [
            (bag, slot)
            for bag in bags
            for slot in sorted(plan.layout.get(bag, {}).keys())
            if (bag, slot) not in occupied_slots
        ]
        default_sorted_items = sorted(
            remaining_items,
            key=lambda item: config.default_sorter.get_sort_key(item),
        )

        assigned_default_count = 0
        for bag, slot in default_slots:
            planned_item = (
                default_sorted_items[assigned_default_count]
                if assigned_default_count < len(default_sorted_items)
                else None
            )
            if planned_item is not None:
                assigned_default_count += 1

            plan.layout[bag][slot] = planned_item
            plan.entries.append(
                BagSortPreviewEntry(
                    bag=bag,
                    slot=slot,
                    item=planned_item,
                    source_bag=planned_item.bag if planned_item is not None else None,
                    source_slot=planned_item.slot if planned_item is not None else None,
                    group_name="Default",
                    group_summary="Any item",
                    sorter=config.default_sorter,
                    used_fallback=False,
                )
            )

        remaining_items = default_sorted_items[assigned_default_count:]
        fallback_slots = [
            entry
            for entry in plan.entries
            if entry.item is None and entry.group_name != "Default"
        ]

        if remaining_items and fallback_slots:
            plan.warnings.append(
                "Some items did not match any open/default slot and were placed into reserved slots as fallback."
            )
            for fallback_entry in fallback_slots:
                if not remaining_items:
                    break

                planned_item = remaining_items.pop(0)
                fallback_entry.item = planned_item
                fallback_entry.source_bag = planned_item.bag
                fallback_entry.source_slot = planned_item.slot
                fallback_entry.used_fallback = True
                plan.layout[fallback_entry.bag][fallback_entry.slot] = planned_item

        if remaining_items:
            plan.warnings.append(
                f"{len(remaining_items)} item(s) could not be assigned by the planner "
                "and will remain unsorted until more slots are available."
            )

        plan.entries.sort(key=lambda entry: (entry.bag.value, entry.slot))
        return plan

    @staticmethod
    def GetPlannedBagLayout(
        bags: list[Bags],
        sorting_config: Optional[SortingConfig] = None,
    ) -> dict[Bags, dict[int, Optional[ItemSnapshot]]]:
        return BagSortPlanner.GetBagSortPlan(bags, sorting_config).layout

    @staticmethod
    def BuildSortBagsNode(
        bags: list[Bags],
        sorting_config: Optional[SortingConfig] = None,
        aftercast_ms: int = 250,
    ) -> BehaviorTree.Node:
        def _sort(_node: BehaviorTree.Node) -> BehaviorTree.NodeState:
            planned_layout = BagSortPlanner.GetPlannedBagLayout(bags, sorting_config)
            moved_any = False

            for bag in bags:
                for slot, planned_item in sorted(planned_layout.get(bag, {}).items()):
                    if planned_item is None or not planned_item.is_valid:
                        continue

                    if planned_item.bag == bag and planned_item.slot == slot:
                        continue

                    Inventory.MoveItem(planned_item.id, bag.value, slot, planned_item.quantity)
                    moved_any = True

            return BehaviorTree.NodeState.SUCCESS if moved_any else BehaviorTree.NodeState.FAILURE

        return BehaviorTree.ActionNode(
            name="Inventory.SortBags",
            action_fn=_sort,
            aftercast_ms=aftercast_ms,
        )
