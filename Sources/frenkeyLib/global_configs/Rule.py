from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, auto
from typing import Any, Callable, ClassVar, Optional, Sequence, cast

from Py4GWCoreLib.enums_src.GameData_enums import DyeColor
from Py4GWCoreLib.enums_src.Item_enums import ItemAction, ItemType, SalvageMode
from Sources.frenkeyLib.item_mods_src.upgrades import ArmorUpgrade, Inherent, Upgrade
from Sources.frenkeyLib.global_configs.Condition import (
    ArmorUpgradesCondition,
    AttributeRequirement,
    BaseCondition,
    ConditionEvaluationContext,
    DyeColorsCondition,
    EncodedNamesCondition,
    ExactItemTypeCondition,
    InherentFilter,
    InherentFiltersCondition,
    IsMaterialCondition,
    ItemTypesCondition,
    MaxWeaponUpgradesCondition,
    ModelFileIdsAndItemTypesCondition,
    ModelFileIdsCondition,
    ModelIdsAndItemTypesCondition,
    ModelIdsCondition,
    NickItemCondition,
    RangedUpgrade,
    RaritiesCondition,
    SalvagesToMaterialsCondition,
    StackQuantityCondition,
    UnidentifiedCondition,
    UpgradeAndItemType,
    UpgradeMatchCondition,
    UpgradeRangesCondition,
    WeaponRequirementCondition,
    WeaponRequirementRanges,
)
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot

__all__ = [
    'BaseRule',
    'ConditionOperator',
    'CustomRule',
    'DyesRule',
    'NickItemRule',
    'ArmorUpgradeRule',
    'WeaponUpgradeRule',
    'CustomWeaponUpgradeRule',
    'ResultInterpretation',
    'RulePreset',
    'get_rule_presets',
    'get_rule_preset',
    'create_rule_from_preset',
]


class ResultInterpretation(IntEnum):
    Match = auto()
    NoMatch = auto()


class ConditionOperator(IntEnum):
    All = auto()
    Any = auto()


class BaseRule:
    """Base rule that evaluates one or more reusable conditions against an item."""

    _registry: ClassVar[dict[str, type['BaseRule']]] = {}
    ui_selectable: ClassVar[bool] = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        BaseRule._registry[cls.__name__] = cls

    def __init__(
        self,
        conditions: Optional[list[BaseCondition]] = None,
        *,
        action: ItemAction = ItemAction.NONE,
        condition_operator: ConditionOperator = ConditionOperator.All,
    ):
        self.name = ''
        self.action = action
        self.enabled = True
        self.result_interpretation: ResultInterpretation = ResultInterpretation.Match
        self.condition_operator = condition_operator
        self.conditions: list[BaseCondition] = list(conditions) if conditions is not None else []

    def get_item(self, item_id: int) -> Optional[ItemSnapshot]:
        try:
            return ItemSnapshot.from_item_id(item_id)
        except Exception:
            return None

    def add_condition(self, condition: BaseCondition) -> None:
        self.conditions.append(condition)

    def remove_condition(self, condition: BaseCondition) -> None:
        self.conditions = [entry for entry in self.conditions if entry != condition]

    def clear_conditions(self) -> None:
        self.conditions.clear()

    def is_valid(self) -> bool:
        return self.enabled and len(self.conditions) > 0 and all(condition.is_valid() for condition in self.conditions)

    def _create_context(self, item_id: int) -> ConditionEvaluationContext:
        return ConditionEvaluationContext(item_id=item_id, item_snapshot=self.get_item(item_id))

    def _evaluate_conditions(self, context: ConditionEvaluationContext) -> bool:
        if not self.conditions:
            return False

        evaluations = [condition.evaluate(context) for condition in self.conditions]
        if self.condition_operator == ConditionOperator.Any:
            return any(evaluations)

        return all(evaluations)

    def applies(self, item_id: int) -> bool:
        if not self.is_valid():
            return False

        context = self._create_context(item_id)
        if context.item_snapshot is None:
            return False

        return self._apply_result_interpretation(self._evaluate_conditions(context))

    def _apply_result_interpretation(self, matched: bool) -> bool:
        if self.result_interpretation == ResultInterpretation.NoMatch:
            return not matched

        return matched

    def _comparison_data(self) -> Any:
        return (
            self.condition_operator.name,
            self.action.name,
            tuple((type(condition).__name__, condition._comparison_data()) for condition in self.conditions),
        )

    def equals(self, other: object) -> bool:
        return (
            isinstance(other, BaseRule)
            and type(self) is type(other)
            and self.result_interpretation == other.result_interpretation
            and self._comparison_data() == other._comparison_data()
        )

    def __eq__(self, other: object) -> bool:
        return self.equals(other)

    def _serialize_data(self) -> dict[str, Any]:
        return {
            'condition_operator': self.condition_operator.name,
            'conditions': [condition.to_dict() for condition in self.conditions],
        }

    def _deserialize_conditions(self, serialized_conditions: Any) -> None:
        parsed_conditions: list[BaseCondition] = []
        for entry in serialized_conditions if isinstance(serialized_conditions, list) else []:
            if not isinstance(entry, dict):
                continue

            condition = BaseCondition.from_dict(entry)
            if condition is not None:
                parsed_conditions.append(condition)

        if not self.conditions:
            self.conditions = parsed_conditions
            return

        merged_conditions = list(self.conditions)
        consumed_indices: set[int] = set()
        extra_conditions: list[BaseCondition] = []

        for parsed_condition in parsed_conditions:
            replacement_index = next(
                (
                    index
                    for index, existing_condition in enumerate(merged_conditions)
                    if index not in consumed_indices and type(existing_condition) is type(parsed_condition)
                ),
                None,
            )

            if replacement_index is None:
                extra_conditions.append(parsed_condition)
                continue

            merged_conditions[replacement_index] = parsed_condition
            consumed_indices.add(replacement_index)

        self.conditions = merged_conditions + extra_conditions

    def _deserialize_data(self, data: dict[str, Any]) -> None:
        operator_name = data.get('condition_operator')
        if isinstance(operator_name, str) and operator_name in ConditionOperator.__members__:
            self.condition_operator = ConditionOperator[operator_name]
        else:
            self.condition_operator = ConditionOperator.All

        self._deserialize_conditions(data.get('conditions', []))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'rule_type': type(self).__name__,
            'name': self.name,
            'action': self.action.name,
            'enabled': self.enabled,
            'result_interpretation': self.result_interpretation.name,
        }
        payload.update(self._serialize_data())
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> 'BaseRule | None':
        rule_type_name = str(payload.get('rule_type', ''))
        rule_cls = cls._registry.get(rule_type_name)
        if rule_cls is None:
            return None

        try:
            rule = rule_cls()
            rule.name = payload.get('name', '')
            action_name = payload.get('action', 'NONE')
            if isinstance(action_name, str) and action_name in ItemAction.__members__:
                rule.action = ItemAction[action_name]
            else:
                rule.action = ItemAction.NONE
            rule.enabled = bool(payload.get('enabled', True))

            result_interpretation_name = payload.get('result_interpretation')
            if isinstance(result_interpretation_name, str) and result_interpretation_name in ResultInterpretation.__members__:
                rule.result_interpretation = ResultInterpretation[result_interpretation_name]
            elif bool(payload.get('inverted', False)):
                rule.result_interpretation = ResultInterpretation.NoMatch

            rule._deserialize_data(payload)
            return rule
        except Exception:
            return None


class CustomRule(BaseRule):
    """User-defined rule that can combine any supported condition sections."""


class NickItemRule(BaseRule):
    """Matches Nicholas the Traveler items that come up within the configured number of weeks."""

    def __init__(self, weeks_before_next_cycle: int = 0):
        super().__init__([NickItemCondition(weeks_before_next_cycle)])

    @property
    def condition(self) -> NickItemCondition:
        return cast(NickItemCondition, self.conditions[0])

    @property
    def weeks_before_next_cycle(self) -> int:
        return self.condition.weeks_before_next_cycle

    @weeks_before_next_cycle.setter
    def weeks_before_next_cycle(self, value: int) -> None:
        self.condition.weeks_before_next_cycle = max(0, min(137, int(value)))


class DyesRule(BaseRule):
    """Matches dye items whose color is one of the selected dye colors."""

    def __init__(self, dye_colors: Optional[list[DyeColor]] = None):
        super().__init__([DyeColorsCondition(dye_colors)])

    @property
    def condition(self) -> DyeColorsCondition:
        return cast(DyeColorsCondition, self.conditions[0])

    @property
    def dye_colors(self) -> list[DyeColor]:
        return self.condition.dye_colors

    @dye_colors.setter
    def dye_colors(self, value: list[DyeColor]) -> None:
        self.condition.dye_colors = value


class ExtractUpgradeRule(BaseRule):
    """Internal base rule for matching extractable upgrades on items."""

    ui_selectable: ClassVar[bool] = False

    def __init__(self, conditions: Optional[list[BaseCondition]] = None):
        super().__init__(conditions)
        self.extracted_action: ItemAction = ItemAction.Stash

    def get_effective_action(self, item_id: int) -> ItemAction:
        item_snapshot = self.get_item(item_id)
        if item_snapshot is not None and item_snapshot.item_type is ItemType.Rune_Mod:
            return self.extracted_action

        return self.action

    def get_matching_upgrades(self, item_id: int) -> list[tuple[Upgrade, SalvageMode]]:
        if not self.is_valid():
            return []

        context = self._create_context(item_id)
        if context.item_snapshot is None:
            return []

        matches: list[tuple[Upgrade, SalvageMode]] = []
        for condition in self.conditions:
            if isinstance(condition, UpgradeMatchCondition):
                matches.extend(condition.get_matching_upgrades(context))

        deduped: list[tuple[Upgrade, SalvageMode]] = []
        seen_modes: set[SalvageMode] = set()
        for upgrade, salvage_mode in matches:
            if salvage_mode in seen_modes:
                continue

            seen_modes.add(salvage_mode)
            deduped.append((upgrade, salvage_mode))

        return deduped

    def _comparison_data(self) -> Any:
        return (
            super()._comparison_data(),
            self.extracted_action.name,
        )

    def _serialize_data(self) -> dict[str, Any]:
        payload = super()._serialize_data()
        payload['extracted_action'] = self.extracted_action.name
        return payload

    def _deserialize_data(self, data: dict[str, Any]) -> None:
        super()._deserialize_data(data)

        extracted_action_name = data.get('extracted_action', ItemAction.Stash.name)
        if isinstance(extracted_action_name, str) and extracted_action_name in ItemAction.__members__:
            self.extracted_action = ItemAction[extracted_action_name]
        else:
            self.extracted_action = ItemAction.Stash


class WeaponUpgradeRule(ExtractUpgradeRule):
    """Matches weapons containing selected max-value weapon upgrades or inscriptions."""

    ui_selectable: ClassVar[bool] = True

    def __init__(self, upgrades: Optional[list[UpgradeAndItemType]] = None):
        super().__init__([MaxWeaponUpgradesCondition(upgrades)])

    @property
    def condition(self) -> MaxWeaponUpgradesCondition:
        return cast(MaxWeaponUpgradesCondition, self.conditions[0])

    @property
    def weapon_upgrades(self) -> list[UpgradeAndItemType]:
        return self.condition.weapon_upgrades

    @weapon_upgrades.setter
    def weapon_upgrades(self, value: list[UpgradeAndItemType]) -> None:
        self.condition.weapon_upgrades = value


class ArmorUpgradeRule(ExtractUpgradeRule):
    """Matches armor containing selected runes or insignias."""

    ui_selectable: ClassVar[bool] = True

    def __init__(self, runes: Optional[list[ArmorUpgrade]] = None):
        super().__init__([ArmorUpgradesCondition(runes)])
        self.extracted_action = ItemAction.Sell_To_Trader

    @property
    def condition(self) -> ArmorUpgradesCondition:
        return cast(ArmorUpgradesCondition, self.conditions[0])

    @property
    def armor_upgrades(self) -> list[ArmorUpgrade]:
        return self.condition.armor_upgrades

    @armor_upgrades.setter
    def armor_upgrades(self, value: list[ArmorUpgrade]) -> None:
        self.condition.armor_upgrades = value


class CustomWeaponUpgradeRule(ExtractUpgradeRule):
    """Matches upgrades whose numeric values fall inside configured ranges."""

    ui_selectable: ClassVar[bool] = True

    def __init__(self, upgrade_ranges: Optional[list[RangedUpgrade]] = None):
        super().__init__([UpgradeRangesCondition(upgrade_ranges)])

    @property
    def condition(self) -> UpgradeRangesCondition:
        return cast(UpgradeRangesCondition, self.conditions[0])

    @property
    def upgrade_ranges(self) -> list[RangedUpgrade]:
        return self.condition.upgrade_ranges

    @upgrade_ranges.setter
    def upgrade_ranges(self, value: list[RangedUpgrade]) -> None:
        self.condition.upgrade_ranges = value


@dataclass(frozen=True, slots=True)
class RulePreset:
    preset_id: str
    label: str
    description: str
    factory: Callable[[], CustomRule]


def _create_custom_rule(conditions: Sequence[BaseCondition]) -> CustomRule:
    return CustomRule(list(conditions))


_RULE_PRESETS: tuple[RulePreset, ...] = (
    RulePreset(
        'model_ids',
        'Model IDs',
        'Create a custom rule seeded with a model ID condition.',
        lambda: _create_custom_rule([ModelIdsCondition()]),
    ),
    RulePreset(
        'item_types',
        'Item Types',
        'Create a custom rule seeded with an item type condition.',
        lambda: _create_custom_rule([ItemTypesCondition()]),
    ),
    RulePreset(
        'quantity',
        'Stack Quantity',
        'Create a custom rule seeded with a stack quantity range condition.',
        lambda: _create_custom_rule([StackQuantityCondition()]),
    ),
    RulePreset(
        'model_ids_and_item_types',
        'Model IDs And Item Types',
        'Create a custom rule seeded with a combined model ID and item type condition.',
        lambda: _create_custom_rule([ModelIdsAndItemTypesCondition()]),
    ),
    RulePreset(
        'encoded_names',
        'Encoded Names',
        'Create a custom rule seeded with an encoded item name condition.',
        lambda: _create_custom_rule([EncodedNamesCondition()]),
    ),
    RulePreset(
        'model_file_ids',
        'Model File IDs',
        'Create a custom rule seeded with a model file ID condition.',
        lambda: _create_custom_rule([ModelFileIdsCondition()]),
    ),
    RulePreset(
        'model_file_ids_and_item_types',
        'Model File IDs And Item Types',
        'Create a custom rule seeded with a combined model file ID and item type condition.',
        lambda: _create_custom_rule([ModelFileIdsAndItemTypesCondition()]),
    ),
    RulePreset(
        'weapon_skin',
        'Weapon Skin',
        'Create a custom rule seeded with weapon skin, requirement, and inherent filter conditions.',
        lambda: _create_custom_rule(
            [
                ModelFileIdsCondition(),
                WeaponRequirementCondition(AttributeRequirement.from_requirement_ranges(None, None, 0, 13)),
                InherentFiltersCondition(InherentFilter.normalize_collection(None)),
            ]
        ),
    ),
    RulePreset(
        'weapon_type',
        'Weapon Type',
        'Create a custom rule seeded with item type, requirement, and inherent filter conditions.',
        lambda: _create_custom_rule(
            [
                ExactItemTypeCondition(),
                WeaponRequirementCondition(AttributeRequirement.from_requirement_ranges(None, None, 0, 13)),
                InherentFiltersCondition(InherentFilter.normalize_collection(None)),
            ]
        ),
    ),
    RulePreset(
        'salvages_to_material',
        'Salvages To Materials',
        'Create a custom rule seeded with a salvage materials condition.',
        lambda: _create_custom_rule([SalvagesToMaterialsCondition()]),
    ),
    RulePreset(
        'rarities',
        'Rarities',
        'Create a custom rule seeded with a rarity condition.',
        lambda: _create_custom_rule([RaritiesCondition()]),
    ),
    RulePreset(
        'rarities_and_item_types',
        'Rarities And Item Types',
        'Create a custom rule seeded with rarity and item type conditions.',
        lambda: _create_custom_rule([RaritiesCondition(), ItemTypesCondition()]),
    ),
    RulePreset(
        'unidentified',
        'Unidentified',
        'Create a custom rule seeded with an unidentified-items condition.',
        lambda: _create_custom_rule([UnidentifiedCondition()]),
    ),
    RulePreset(
        'unidentified_and_rarity',
        'Unidentified And Rarity',
        'Create a custom rule seeded with unidentified and rarity conditions.',
        lambda: _create_custom_rule([UnidentifiedCondition(), RaritiesCondition()]),
    ),
)

_RULE_PRESET_BY_ID: dict[str, RulePreset] = {preset.preset_id: preset for preset in _RULE_PRESETS}


def get_rule_presets() -> tuple[RulePreset, ...]:
    return _RULE_PRESETS


def get_rule_preset(preset_id: str) -> RulePreset | None:
    return _RULE_PRESET_BY_ID.get(str(preset_id or '').strip())


def create_rule_from_preset(preset_id: str) -> CustomRule | None:
    preset = get_rule_preset(preset_id)
    if preset is None:
        return None

    return preset.factory()
