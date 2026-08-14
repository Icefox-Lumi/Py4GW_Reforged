from __future__ import annotations

import json
import os
from typing import ClassVar, Self, cast

import Py4GW
import PySystem
from Py4GWCoreLib.enums_src.GameData_enums import DyeColor
from Py4GWCoreLib.enums_src.Item_enums import ItemType, Rarity
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Sources.frenkeyLib.global_configs.Condition import ItemTypesCondition
from Sources.frenkeyLib.global_configs.Condition import ModelIdsCondition
from Sources.frenkeyLib.global_configs.Condition import RaritiesCondition
from Sources.frenkeyLib.global_configs.Condition import UpgradesCondition
from Sources.frenkeyLib.item_mods_src.upgrades import Upgrade
from Sources.frenkeyLib.global_configs import Rule


class RuleConfig(list[Rule.BaseRule]):
    allowed_rule_types: ClassVar[tuple[type[Rule.BaseRule], ...] | None] = None
    disallowed_rule_types: ClassVar[tuple[type[Rule.BaseRule], ...]] = ()
    
    def __init__(self):        
        self.blacklisted_items : list[int] = []
        self.whitelisted_items : list[int] = []

    def reset_to_defaults(self) -> None:
        '''
        Resets the persisted and transient state for this config instance.
        '''
        self.clear()
        self.reset()

    def reload_from_document(self, document, profile_key: str | None = None) -> None:
        '''
        Reloads the current singleton instance in place from the provided document.
        '''
        if document is None:
            self.reset_to_defaults()
            return

        path = "config" if profile_key is None else f"profiles/{profile_key}"
        json_data = document.get_json(path, None)
        if json_data is None:
            self.reset_to_defaults()
            return

        loaded = type(self).from_json(json_data)
        if loaded is not self:
            self.clear()
            self.extend(loaded)
            self.blacklisted_items = list(getattr(loaded, 'blacklisted_items', []))
            self.whitelisted_items = list(getattr(loaded, 'whitelisted_items', []))
        
    def reset(self):
        '''
        Clears all blacklisted and whitelisted items from the config.
        This should be called on each map load since item ids reset on each load.
        '''
        
        self.blacklisted_items.clear()
        self.whitelisted_items.clear()

    @classmethod
    def GetAllowedRuleTypes(cls) -> tuple[type[Rule.BaseRule], ...] | None:
        return cls.allowed_rule_types

    @classmethod
    def GetDisallowedRuleTypes(cls) -> tuple[type[Rule.BaseRule], ...]:
        return cls.disallowed_rule_types

    @classmethod
    def IsAllowedRuleType(cls, rule: Rule.BaseRule | type[Rule.BaseRule]) -> bool:
        rule_type = rule if isinstance(rule, type) else type(rule)
        allowed_rule_types = cls.GetAllowedRuleTypes()
        if allowed_rule_types is not None and not issubclass(rule_type, allowed_rule_types):
            return False

        disallowed_rule_types = cls.GetDisallowedRuleTypes()
        if disallowed_rule_types and issubclass(rule_type, disallowed_rule_types):
            return False

        return True

    @classmethod
    def _is_allowed_rule_type(cls, rule: Rule.BaseRule) -> bool:
        return cls.IsAllowedRuleType(rule)

    @classmethod
    def _cast_rule(cls, rule: Rule.BaseRule) -> Rule.BaseRule:
        if not cls._is_allowed_rule_type(rule):
            raise TypeError(
                f"{type(rule).__name__} is not allowed in {cls.__name__}."
            )

        return cast(Rule.BaseRule, rule)

    def GetMatchedRule(self, item_id: int) -> Rule.BaseRule | None:
        '''
        Returns the first rule that matches the item id, or None if no rule matches.
        '''
        for rule in self:
            if rule.applies(item_id):
                return rule
            
        return None

    def EvaluateItem(self, item_id: int) -> bool:        
        # --- Hard block: blacklists ---
        if item_id in self.blacklisted_items:
            return False
        
        # --- Whitelists ---
        if item_id in self.whitelisted_items:
            return True
        
        for rule in self:
            if rule.applies(item_id):
                return True
            
        return False
    
    def EvaluateItems(self, item_ids: list[int]) -> list[int]:
        '''
        Evaluates a list of items against the current rules and returns a list of items that match the rules. Takes the blacklist and whitelist into account as well, with the blacklist having the highest priority, then the whitelist and then the rules. 
        This means that if an item is blacklisted, it will not match the rules even if it would normally match them, and if an item is whitelisted, it will match the rules even if it would not normally match them.
        '''
        
        filtered_items = []
        
        for item_id in item_ids:
            if self.EvaluateItem(item_id):
                filtered_items.append(item_id)
                
        return filtered_items

    def AddRule(self, rule: Rule.BaseRule):
        '''
        Adds a rule to the config if an equivalent rule is not already contained in the config. This is to prevent duplicate rules from being added, which would be redundant and adds unnecessary overhead when evaluating items against the rules.
        '''
        typed_rule = self._cast_rule(rule)

        if not self.HasMatchingRule(rule):
            self.append(typed_rule)
        
    def RemoveRule(self, rule: Rule.BaseRule):
        '''
        Removes a rule from the config if an equivalent rule is contained in the config.
        '''
        for existing_rule in self:
            if existing_rule.equals(rule):
                self.remove(existing_rule)
                break

    def HasMatchingRule(self, rule: Rule.BaseRule) -> bool:
        '''
        Checks whether an equivalent rule is already contained in the config.
        '''
        return any(existing_rule.equals(rule) for existing_rule in self)

    @staticmethod
    def _build_custom_rule(*conditions) -> Rule.CustomRule:
        return Rule.CustomRule(list(conditions))
            
    #region Helpers 
    """
    Helper methods to add and create rules easily without the need to create the rule objects manually.
    These methods create supported rules and add them to the config in one step.
    This is just for convenience and readability when setting up the configs and is only a wrapper for the basic rule presets.
    
        Example usage:
        config = RuleConfig() // LootConfig() // SalvageConfig()
        config.AddModelId(1234)
        config.AddModelIds([1234, ModelID.SomeModel])
        
        config.AddRarity(Rarity.Gold)
        config.AddRarities([Rarity.Purple, Rarity.Gold, Rarity.Green])     
           
        config.AddItemType(ItemType.Axe)
        config.AddItemTypes([ItemType.Axe, ItemType.Sword])
        
        config.AddDyeColor(DyeColor.Black)
        config.AddDyeColors([DyeColor.White, DyeColor.Black])
    """
    #region Adding helper methods for creating and adding rules in one step
    def AddModelId(self, model_id: int):
        '''
        Helper method to add a model ID custom rule to the config.
        '''
        rule = self._build_custom_rule(ModelIdsCondition([model_id]))
        self.AddRule(rule)
    
    def AddModelIds(self, model_ids: list[int|ModelID]):
        '''
        Helper method to add a model IDs custom rule to the config.
        '''
        rule = self._build_custom_rule(ModelIdsCondition(model_ids))
        self.AddRule(rule)
        
    def AddRarity(self, rarity: Rarity):
        '''
        Helper method to add a rarity custom rule to the config.
        '''
        rule = self._build_custom_rule(RaritiesCondition([rarity]))
        self.AddRule(rule)
    
    def AddRarities(self, rarities: list[Rarity]):
        '''
        Helper method to add a rarities custom rule to the config.
        '''
        rule = self._build_custom_rule(RaritiesCondition(rarities))
        self.AddRule(rule)
    
    def AddItemType(self, item_type: ItemType):
        '''
        Helper method to add an item type custom rule to the config.
        '''
        rule = self._build_custom_rule(ItemTypesCondition([item_type]))
        self.AddRule(rule)      
        
    def AddItemTypes(self, item_types: list[ItemType]):
        '''
        Helper method to add an item types custom rule to the config.
        '''
        rule = self._build_custom_rule(ItemTypesCondition(item_types))
        self.AddRule(rule)      
        
    def AddDyeColor(self, dye_color: DyeColor):
        '''
        Helper method to add a dye rule to the config.
        '''
        rule = Rule.DyesRule([dye_color])
        self.AddRule(rule)
    
    def AddDyeColors(self, dye_colors: list[DyeColor]):
        '''
        Helper method to add a dye colors rule to the config.
        '''
        rule = Rule.DyesRule(dye_colors)
        self.AddRule(rule)

    def AddUpgrade(self, upgrade: Upgrade):
        '''
        Helper method to add a generic upgrades custom rule to the config.
        '''
        rule = self._build_custom_rule(UpgradesCondition([upgrade]))
        self.AddRule(rule)

    def AddUpgrades(self, upgrades: list[(tuple[Upgrade, list[ItemType]] | Upgrade)]):
        '''
        Helper method to add a generic upgrades custom rule to the config.
        '''
        rule = self._build_custom_rule(UpgradesCondition(upgrades))
        self.AddRule(rule)

    #endregion Adding helper methods for creating and adding rules in one step
    
    #region Deleting helper methods for creating and adding rules in one step
    def RemoveModelId(self, model_id: int):
        '''
        Helper method to remove a model ID custom rule from the config.
        '''
        rule = self._build_custom_rule(ModelIdsCondition([model_id]))
        self.RemoveRule(rule)
        
    def RemoveModelIds(self, model_ids: list[int|ModelID]):
        '''
        Helper method to remove a model IDs custom rule from the config.
        '''
        rule = self._build_custom_rule(ModelIdsCondition(model_ids))
        self.RemoveRule(rule)
        
    def RemoveRarity(self, rarity: Rarity):
        '''
        Helper method to remove a rarity custom rule from the config.
        '''
        rule = self._build_custom_rule(RaritiesCondition([rarity]))
        self.RemoveRule(rule)
        
    def RemoveRarities(self, rarities: list[Rarity]):
        '''
        Helper method to remove a rarities custom rule from the config.
        '''
        rule = self._build_custom_rule(RaritiesCondition(rarities))
        self.RemoveRule(rule)
        
    def RemoveItemType(self, item_type: ItemType):
        '''
        Helper method to remove an item type custom rule from the config.
        '''
        rule = self._build_custom_rule(ItemTypesCondition([item_type]))
        self.RemoveRule(rule)
        
    def RemoveItemTypes(self, item_types: list[ItemType]):
        '''
        Helper method to remove an item types custom rule from the config.
        '''
        rule = self._build_custom_rule(ItemTypesCondition(item_types))
        self.RemoveRule(rule)
        
    def RemoveDyeColor(self, dye_color: DyeColor):
        '''
        Helper method to remove a dye rule from the config.
        '''
        rule = Rule.DyesRule([dye_color])
        self.RemoveRule(rule)
        
    def RemoveDyeColors(self, dye_colors: list[DyeColor]):
        '''
        Helper method to remove a dye colors rule from the config.
        '''
        rule = Rule.DyesRule(dye_colors)
        self.RemoveRule(rule)

    def RemoveUpgrade(self, upgrade: Upgrade):
        '''
        Helper method to remove a generic upgrades custom rule from the config.
        '''
        rule = self._build_custom_rule(UpgradesCondition([upgrade]))
        self.RemoveRule(rule)

    def RemoveUpgrades(self, upgrades: list[(tuple[Upgrade, list[ItemType]] | Upgrade)]):
        '''
        Helper method to remove a generic upgrades custom rule from the config.
        '''
        rule = self._build_custom_rule(UpgradesCondition(upgrades))
        self.RemoveRule(rule)
    #endregion Deleting helper methods for creating and adding rules in one step
    
    #endregion Helpers

    #region Json Serialization
    def to_json_format(self) -> list[dict]:
        '''
        Serializes the rules to a JSON-compatible structure.
        '''
        
        return [rule.to_dict() for rule in self]
    
    @classmethod
    def from_json(cls: type[Self], json_data: list[dict]) -> Self:
        '''
        Deserializes the rules from a JSON-compatible structure into this config class' singleton instance.
        '''
        if not isinstance(json_data, list):
            raise ValueError("RuleConfig JSON payload must be a list of rule objects.")

        parsed_rules: list[Rule.BaseRule] = []
        skipped_rule_types: dict[str, int] = {}

        for rule_data in json_data:
            if not isinstance(rule_data, dict):
                continue

            rule = Rule.BaseRule.from_dict(rule_data)
            if rule is None:
                rule_type_name = rule_data.get('rule_type')
                if isinstance(rule_type_name, str) and rule_type_name:
                    skipped_rule_types[rule_type_name] = skipped_rule_types.get(rule_type_name, 0) + 1
                continue

            if not cls._is_allowed_rule_type(rule):
                skipped_rule_types[type(rule).__name__] = skipped_rule_types.get(type(rule).__name__, 0) + 1
                continue

            typed_rule = cast(Rule.BaseRule, rule)

            if any(existing_rule.equals(typed_rule) for existing_rule in parsed_rules):
                continue

            parsed_rules.append(typed_rule)

        if skipped_rule_types:
            skipped_summary = ', '.join(
                f'{rule_type} x{count}'
                for rule_type, count in sorted(skipped_rule_types.items())
            )
            PySystem.Console.Log(
                'RuleConfig',
                f'Skipped unsupported rule types while loading {cls.__name__}: {skipped_summary}.',
                PySystem.Console.MessageType.Warning,
            )

        instance = cls()
        instance.reset_to_defaults()
        instance.extend(parsed_rules)
        
        return instance
    #endregion Json Serialization
    
    #region Loading and Saving
    def save_to_document(self, document, profile_key: str | None = None) -> None:
        '''
        Saves the config into the provided JsonFactory document.
        '''
        if document is None:
            return
        path = "config" if profile_key is None else f"profiles/{profile_key}"
        document.set_json(path, self.to_json_format())
    #endregion Loading and Saving
