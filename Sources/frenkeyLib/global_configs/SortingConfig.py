from __future__ import annotations

import json
import os
from dataclasses import dataclass, field as dataclass_field
from enum import IntEnum, StrEnum, auto
from typing import Any, ClassVar, Optional, Self, cast

from Sources.frenkeyLib.global_configs.Condition import BaseCondition, ConditionEvaluationContext
from Sources.frenkeyLib.global_configs.Rule import ConditionOperator, CustomRule
from Py4GWCoreLib.enums_src.GameData_enums import DyeColor
from Py4GWCoreLib.enums_src.Item_enums import Bags, ItemType, Rarity
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot

class SortField(StrEnum):
    ItemType = 'ItemType'
    ModelId = 'ModelId'
    Rarity = 'Rarity'
    Profession = 'Profession'
    Quantity = 'Quantity'
    Value = 'Value'
    Color = 'Color'
    Name = 'Name'
    Id = 'Id'


def _default_item_type_order() -> list[int]:
    item_type_order = [
        int(ItemType.Kit),
        int(ItemType.Key),
        int(ItemType.Usable),
        int(ItemType.Trophy),
        int(ItemType.Quest_Item),
        int(ItemType.Materials_Zcoins),
    ]
    item_type_order += [int(item_type) for item_type in ItemType if int(item_type) not in item_type_order]
    return item_type_order

class SortDirection(IntEnum):
    Ascending = auto()
    Descending = auto()

@dataclass(slots=True)
class SortArgument:
    field: SortField = SortField.ItemType
    direction: SortDirection = SortDirection.Ascending
    custom_order: list[Any] = dataclass_field(default_factory=list)

    @property
    def display_name(self) -> str:
        return f'{self.field.value}{"*" if self.has_custom_order else ""}'

    @property
    def has_custom_order(self) -> bool:
        return len(self.custom_order) > 0

    @property
    def supports_custom_order(self) -> bool:
        return self.field in {SortField.ItemType, SortField.ModelId, SortField.Rarity, SortField.Color}

    @staticmethod
    def _invert_string(value: str) -> tuple[int, ...]:
        return tuple(-ord(character) for character in value)

    @classmethod
    def _transform_value(cls, value: Any, descending: bool) -> Any:
        if not descending:
            return value
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return -value
        if isinstance(value, str):
            return cls._invert_string(value)
        if isinstance(value, tuple):
            return tuple(cls._transform_value(entry, descending) for entry in value)
        return value

    def _get_natural_value(self, item: ItemSnapshot) -> Any:
        if self.field == SortField.ItemType:
            item_type_order = _default_item_type_order()
            if item.item_type == ItemType.Unknown:
                return len(item_type_order) + 1
            return item_type_order.index(item.item_type)
        if self.field == SortField.Profession:
            return int(item.profession)
        if self.field == SortField.ModelId:
            return int(item.model_id)
        if self.field == SortField.Rarity:
            return int(item.rarity.value)
        if self.field == SortField.Quantity:
            return int(item.quantity)
        if self.field == SortField.Value:
            return int(item.value)
        if self.field == SortField.Color:
            return int(item.color.value)
        if self.field == SortField.Name:
            return (item.complete_name or item.singular_name or item.name or '').lower()
        return int(item.id)

    def _get_custom_rank(self, item: ItemSnapshot) -> int | None:
        if not self.has_custom_order:
            return None

        if self.field == SortField.ModelId:
            normalized_entries: list[tuple[int, ItemType | None]] = []
            for entry in self.custom_order:
                if isinstance(entry, int):
                    normalized_entries.append((int(entry), None))
                    continue
                if not isinstance(entry, dict):
                    continue
                model_id = entry.get('model_id')
                item_type_name = entry.get('item_type')
                if not isinstance(model_id, int):
                    continue
                if isinstance(item_type_name, str) and item_type_name in ItemType.__members__:
                    normalized_entries.append((int(model_id), ItemType[item_type_name]))
                else:
                    normalized_entries.append((int(model_id), None))

            for index, (model_id, item_type) in enumerate(normalized_entries):
                if int(item.model_id) != model_id:
                    continue
                if item_type is None or item.item_type.matches(item_type):
                    return index
            return None

        if self.field == SortField.ItemType:
            normalized_item_types = [
                ItemType[entry]
                for entry in self.custom_order
                if isinstance(entry, str) and entry in ItemType.__members__
            ]
            for index, item_type in enumerate(normalized_item_types):
                if item.item_type.matches(item_type):
                    return index
            return None

        if self.field == SortField.Rarity:
            normalized_rarities = [
                Rarity[entry]
                for entry in self.custom_order
                if isinstance(entry, str) and entry in Rarity.__members__
            ]
            return normalized_rarities.index(item.rarity) if item.rarity in normalized_rarities else None

        if self.field == SortField.Color:
            normalized_colors = [
                DyeColor[entry]
                for entry in self.custom_order
                if isinstance(entry, str) and entry in DyeColor.__members__
            ]
            return normalized_colors.index(item.color) if item.color in normalized_colors else None

        return None

    def get_sort_key_part(self, item: ItemSnapshot) -> Any:
        natural_value = self._get_natural_value(item)
        if not self.has_custom_order:
            return self._transform_value(
                natural_value,
                self.direction == SortDirection.Descending,
            )

        custom_rank = self._get_custom_rank(item)
        if custom_rank is None:
            # Keep every non-match in the same bucket so later sort arguments
            # can continue refining the order instead of being short-circuited
            # by this argument's natural field value.
            return (1, )

        effective_rank = custom_rank
        if self.direction == SortDirection.Descending:
            effective_rank = max(0, len(self.custom_order) - 1 - custom_rank)

        return (0, effective_rank)

    def to_dict(self) -> dict[str, Any]:
        return {
            'field': self.field.value,
            'direction': self.direction.name,
            'custom_order': [
                {
                    'model_id': int(entry.get('model_id', 0)),
                    'item_type': str(entry.get('item_type')),
                }
                if self.field == SortField.ModelId and isinstance(entry, dict) and isinstance(entry.get('model_id'), int) and isinstance(entry.get('item_type'), str)
                else int(entry)
                if self.field == SortField.ModelId and isinstance(entry, int)
                else str(entry)
                if isinstance(entry, str)
                else entry
                for entry in self.custom_order
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'SortArgument | None':
        field_name = data.get('field')
        if not isinstance(field_name, str) or field_name not in SortField._value2member_map_:
            return None
        direction_name = data.get('direction', 'Ascending')
        direction = SortDirection[direction_name] if direction_name in SortDirection.__members__ else SortDirection.Ascending
        return cls(
            field=SortField(field_name),
            direction=direction,
            custom_order=[
                entry
                for entry in data.get('custom_order', [])
                if isinstance(entry, (int, str, dict))
            ] if isinstance(data.get('custom_order', []), list) else [],
        )


def _default_sort_arguments() -> list[SortArgument]:
    return [
        SortArgument(SortField.ItemType, direction=SortDirection.Ascending),
        SortArgument(SortField.ModelId, direction=SortDirection.Ascending),
        SortArgument(SortField.Rarity, direction=SortDirection.Descending),
        SortArgument(SortField.Profession, direction=SortDirection.Ascending),
        SortArgument(SortField.Quantity, direction=SortDirection.Descending),
        SortArgument(SortField.Value, direction=SortDirection.Descending),
        SortArgument(SortField.Color, direction=SortDirection.Ascending),
        SortArgument(SortField.Id, direction=SortDirection.Ascending),
    ]


class Sorter:
    def __init__(self, arguments: Optional[list[SortArgument]] = None):
        self.arguments: list[SortArgument] = list(arguments) if arguments is not None else _default_sort_arguments()

    @property
    def display_name(self) -> str:
        if not self.arguments:
            return 'No Sort Arguments'
        preview = ', '.join(
            f'{argument.display_name} {argument.direction.name}'
            for argument in self.arguments[:3]
        )
        return f'{preview}{"..." if len(self.arguments) > 3 else ""}'

    def get_sort_key(self, item: ItemSnapshot) -> tuple[Any, ...]:
        default_arguments = _default_sort_arguments()
        primary_arguments = self.arguments or default_arguments
        fallback_arguments = [] if primary_arguments == default_arguments else default_arguments
        key_parts = [argument.get_sort_key_part(item) for argument in primary_arguments]
        key_parts.extend(argument.get_sort_key_part(item) for argument in fallback_arguments)
        if not any(argument.field == SortField.Id for argument in [*primary_arguments, *fallback_arguments]):
            key_parts.append(int(item.id))
        return tuple(key_parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            'arguments': [argument.to_dict() for argument in self.arguments],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | str | None) -> 'Sorter | None':
        if not isinstance(payload, dict):
            return None

        raw_arguments = payload.get('arguments', [])
        arguments: list[SortArgument] = []
        if isinstance(raw_arguments, list):
            for raw_argument in raw_arguments:
                if not isinstance(raw_argument, dict):
                    continue
                argument = SortArgument.from_dict(raw_argument)
                if argument is not None:
                    arguments.append(argument)

        return cls(arguments=arguments or _default_sort_arguments())


class DefaultSorter(Sorter):
    def __init__(self):
        super().__init__(_default_sort_arguments())


class SlotMatcherConfig(CustomRule):
    def __init__(
        self,
        conditions: Optional[list[BaseCondition]] = None,
        condition_operator: ConditionOperator = ConditionOperator.All,
    ):
        super().__init__(conditions=conditions, condition_operator=condition_operator)

    def matches(self, item: Optional[ItemSnapshot]) -> bool:
        if item is None or not item.is_valid:
            return False
        if not self.conditions:
            return True

        context = ConditionEvaluationContext(item_id=int(item.id), item_snapshot=item)
        evaluations = [condition.evaluate(context) for condition in self.conditions if condition.is_valid()]
        if not evaluations:
            return True

        if self.condition_operator == ConditionOperator.Any:
            return any(evaluations)

        return all(evaluations)

    def is_restrictive(self) -> bool:
        return any(condition.is_valid() for condition in self.conditions)

    def summary(self) -> str:
        valid_conditions = [condition for condition in self.conditions if condition.is_valid()]
        if not valid_conditions:
            return 'Any item'

        condition_names = [
            type(condition).__name__.replace('Condition', '')
            for condition in valid_conditions[:3]
        ]
        operator = 'Any' if self.condition_operator == ConditionOperator.Any else 'All'
        suffix = '...' if len(valid_conditions) > 3 else ''
        return f'{operator}: {", ".join(condition_names)}{suffix}'

    def to_dict(self) -> dict[str, Any]:
        return {
            'condition_operator': self.condition_operator.name,
            'conditions': [condition.to_dict() for condition in self.conditions],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'SlotMatcherConfig':
        operator_name = payload.get('condition_operator')
        condition_operator = (
            ConditionOperator[operator_name]
            if isinstance(operator_name, str) and operator_name in ConditionOperator.__members__
            else ConditionOperator.All
        )
        conditions: list[BaseCondition] = []
        raw_conditions = payload.get('conditions', [])
        if isinstance(raw_conditions, list):
            for raw_condition in raw_conditions:
                if not isinstance(raw_condition, dict):
                    continue
                condition = BaseCondition.from_dict(raw_condition)
                if condition is not None:
                    conditions.append(condition)

        return cls(conditions=conditions, condition_operator=condition_operator)


@dataclass(frozen=True, slots=True)
class SlotReference:
    bag: Bags
    slot: int

    def to_dict(self) -> dict[str, Any]:
        return {
            'bag': self.bag.name,
            'slot': max(0, int(self.slot)),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'SlotReference | None':
        bag_name = data.get('bag')
        slot = data.get('slot')
        if not isinstance(bag_name, str) or bag_name not in Bags.__members__:
            return None
        if not isinstance(slot, int):
            return None
        return cls(bag=Bags[bag_name], slot=max(0, int(slot)))


@dataclass(slots=True)
class SlotGroupConfig:
    slot_refs: list[SlotReference] = dataclass_field(default_factory=list)
    sorter: Sorter = dataclass_field(default_factory=DefaultSorter)
    matcher: SlotMatcherConfig = dataclass_field(default_factory=SlotMatcherConfig)
    name: str = ''
    enabled: bool = True
    is_default: bool = False

    def normalized_slot_refs(self) -> list[SlotReference]:
        unique_slot_refs = {
            SlotReference(slot_ref.bag, max(0, int(slot_ref.slot)))
            for slot_ref in self.slot_refs
            if isinstance(slot_ref, SlotReference)
        }
        return sorted(unique_slot_refs, key=lambda slot_ref: (slot_ref.bag.value, slot_ref.slot))

    def normalized_slots_for_bag(self, bag: Bags) -> list[int]:
        return [
            slot_ref.slot
            for slot_ref in self.normalized_slot_refs()
            if slot_ref.bag == bag
        ]

    def bags(self) -> list[Bags]:
        return sorted({slot_ref.bag for slot_ref in self.normalized_slot_refs()}, key=lambda bag: bag.value)

    def display_name(self) -> str:
        if self.is_default:
            return self.name.strip() or 'Default Sort Policy'
        return self.name.strip() or self.slot_range_text()

    def slot_range_text(self) -> str:
        if self.is_default:
            return 'All unassigned slots'
        slot_refs = self.normalized_slot_refs()
        if not slot_refs:
            return 'No Slots'
        grouped_slots: dict[Bags, list[int]] = {}
        for slot_ref in slot_refs:
            grouped_slots.setdefault(slot_ref.bag, []).append(slot_ref.slot)
        return ' | '.join(
            f'{bag.name}: {", ".join(str(slot) for slot in slots)}'
            for bag, slots in sorted(grouped_slots.items(), key=lambda item: item[0].value)
        )

    def owns_slot(self, bag: Bags, slot: int) -> bool:
        return any(slot_ref.bag == bag and slot_ref.slot == slot for slot_ref in self.normalized_slot_refs())

    def matches(self, item: Optional[ItemSnapshot]) -> bool:
        return self.enabled and self.matcher.matches(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            'slot_refs': [slot_ref.to_dict() for slot_ref in self.normalized_slot_refs()],
            'sorter': self.sorter.to_dict(),
            'matcher': self.matcher.to_dict(),
            'name': self.name,
            'enabled': self.enabled,
            'is_default': self.is_default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'SlotGroupConfig | None':
        raw_sorter = data.get('sorter', data.get('sort_policy', 'DefaultSorter'))

        sorter = Sorter.from_dict(raw_sorter) or DefaultSorter()
        matcher_data = data.get('matcher', {})
        matcher = SlotMatcherConfig.from_dict(matcher_data if isinstance(matcher_data, dict) else {})
        slot_refs: list[SlotReference] = []
        raw_slot_refs = data.get('slot_refs', [])
        if isinstance(raw_slot_refs, list):
            for raw_slot_ref in raw_slot_refs:
                if not isinstance(raw_slot_ref, dict):
                    continue
                slot_ref = SlotReference.from_dict(raw_slot_ref)
                if slot_ref is not None:
                    slot_refs.append(slot_ref)
        else:
            bag_name = data.get('bag')
            raw_slots = data.get('slots', [])
            if isinstance(bag_name, str) and bag_name in Bags.__members__ and isinstance(raw_slots, list):
                for slot in raw_slots:
                    try:
                        slot_refs.append(SlotReference(Bags[bag_name], max(0, int(slot))))
                    except (TypeError, ValueError):
                        continue

        return cls(
            slot_refs=slot_refs,
            sorter=sorter,
            matcher=matcher,
            name=str(data.get('name', '') or ''),
            enabled=bool(data.get('enabled', True)),
            is_default=bool(data.get('is_default', False)),
        )


@dataclass(slots=True)
class BagSortPreviewEntry:
    bag: Bags
    slot: int
    item: Optional[ItemSnapshot]
    source_bag: Optional[Bags]
    source_slot: Optional[int]
    group_name: str
    group_summary: str
    sorter: Sorter
    used_fallback: bool = False


@dataclass(slots=True)
class BagSortPlan:
    layout: dict[Bags, dict[int, Optional[ItemSnapshot]]] = dataclass_field(default_factory=dict)
    entries: list[BagSortPreviewEntry] = dataclass_field(default_factory=list)
    warnings: list[str] = dataclass_field(default_factory=list)


class SortingConfig:
    _initialized: bool = False
    _instance: ClassVar[Self | None] = None

    def __new__(cls: type[Self]) -> Self:
        instance = cast(Self | None, cls._instance)
        if instance is None:
            instance = cast(Self, super().__new__(cls))
            instance._initialized = False
            cls._instance = instance
        return instance

    def __init__(self) -> None:
        if self._initialized:
            self._ensure_profile_sync()
            return

        self._initialized = True
        self.reset_to_defaults()
        self._ensure_profile_sync()

    def _ensure_profile_sync(self) -> None:
        try:
            from Sources.frenkeyLib.global_configs.GlobalConfigProfileManager import GLOBAL_CONFIG_PROFILE_MANAGER

            GLOBAL_CONFIG_PROFILE_MANAGER.refresh_and_sync()
        except Exception:
            pass

    def reset_to_defaults(self) -> None:
        self.default_group: SlotGroupConfig = SlotGroupConfig(
            sorter=DefaultSorter(),
            name='Default Sort Policy',
            enabled=True,
            is_default=True,
        )
        self.slot_groups: list[SlotGroupConfig] = []

    def reload_from_file(self, file_path: str) -> None:
        if not os.path.isfile(file_path):
            self.reset_to_defaults()
            return

        with open(file_path, 'r', encoding='utf-8') as file:
            json_data = json.load(file)

        self.load_dict(json_data if isinstance(json_data, dict) else {})

    def get_groups_for_bag(self, bag: Bags) -> list[SlotGroupConfig]:
        return [
            group
            for group in self.slot_groups
            if group.enabled and group.normalized_slots_for_bag(bag)
        ]

    def get_group_for_slot(self, bag: Bags, slot: int) -> SlotGroupConfig | None:
        for group in self.slot_groups:
            if group.owns_slot(bag, slot):
                return group
        return None

    @property
    def default_sorter(self) -> Sorter:
        return self.default_group.sorter

    @default_sorter.setter
    def default_sorter(self, sorter: Sorter) -> None:
        self.default_group.sorter = sorter

    def to_dict(self) -> dict[str, Any]:
        return {
            'default_group': self.default_group.to_dict(),
            'slot_groups': [group.to_dict() for group in self.slot_groups],
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        raw_default_group = data.get('default_group')
        
        if isinstance(raw_default_group, dict):
            default_group = SlotGroupConfig.from_dict(raw_default_group)
            if default_group is not None:
                default_group.is_default = True
                default_group.slot_refs = []
                if default_group.name.strip() == '':
                    default_group.name = 'Default Sort Policy'
                self.default_group = default_group
            else:
                self.default_group = SlotGroupConfig(sorter=DefaultSorter(), name='Default Sort Policy', enabled=True, is_default=True)
        else:
            raw_default_sorter = data.get('default_sorter', data.get('default_sort_policy', 'DefaultSorter'))
            self.default_group = SlotGroupConfig(
                sorter=Sorter.from_dict(raw_default_sorter) or DefaultSorter(),
                name='Default Sort Policy',
                enabled=True,
                is_default=True,
            )

        self.slot_groups.clear()
        raw_groups = data.get('slot_groups', [])
        if not isinstance(raw_groups, list):
            raw_groups = []

        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                continue
            group = SlotGroupConfig.from_dict(raw_group)
            if group is not None:
                group.is_default = False
                self.slot_groups.append(group)

    @classmethod
    def Load(cls: type[Self], file_path: str) -> Self:
        instance = cls()
        instance.reload_from_file(file_path)
        return instance
