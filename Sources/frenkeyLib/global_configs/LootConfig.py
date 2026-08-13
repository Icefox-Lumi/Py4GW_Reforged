from typing import ClassVar, Self, cast

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.Routines import Routines
from Py4GWCoreLib.enums_src.GameData_enums import Range

from Py4GWCoreLib.enums_src.Item_enums import ItemAction
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot
from Sources.frenkeyLib.global_configs.RuleConfig import RuleConfig
from Sources.frenkeyLib.global_configs.SortingConfig import SlotMatcherConfig

class LootConfig(RuleConfig):
    _initialized: bool = False
    _instances: ClassVar[dict[type[Self], Self]] = {}
    disallowed_rule_types: ClassVar[tuple[type, ...]] = (SlotMatcherConfig,)

    def __new__(cls: type[Self]) -> Self:
        instance = cast(Self | None, cls._instances.get(cls))
        if instance is None:
            instance = cast(Self, super().__new__(cls))
            instance._initialized = False
            cls._instances[cls] = instance
        return instance

    def __init__(self: Self) -> None:
        if self._initialized:
            self._ensure_profile_sync()
            return

        self._initialized = True
        self.blacklisted_models: list[int] = []
        self.whitelisted_models: list[int] = []
        
        super().__init__()
        self._ensure_profile_sync()

    def _ensure_profile_sync(self) -> None:
        try:
            from Sources.frenkeyLib.global_configs.GlobalConfigProfileManager import GLOBAL_CONFIG_PROFILE_MANAGER

            GLOBAL_CONFIG_PROFILE_MANAGER.refresh_and_sync()
        except Exception:
            pass

    def reset_to_defaults(self) -> None:
        super().reset_to_defaults()
        self.blacklisted_models.clear()
        self.whitelisted_models.clear()
        
    def EvaluateItem(self, item_id):
        if not super().EvaluateItem(item_id):
            return False
        
        item = ItemSnapshot.from_item_id(item_id)
        if item:
            if item.model_id in self.blacklisted_models:
                return False
                
            if item.model_id in self.whitelisted_models:
                return True
        
        matched_rule = self.GetMatchedRule(item_id)
        return matched_rule is not None and matched_rule.action is ItemAction.PickUp
    
    def AddItemIDToBlacklist(self, item_id: int):
        if not Agent.IsValid(item_id):
            return
        
        if not item_id in self.blacklisted_items:
            self.blacklisted_items.append(item_id)

    def AddItemIDToWhitelist(self, item_id: int):
        if not Agent.IsValid(item_id):
            return
        
        if not item_id in self.whitelisted_items:
            self.whitelisted_items.append(item_id)
            
    def AddModelIDToBlacklist(self, model_id: int):
        if not model_id in self.blacklisted_models:
            self.blacklisted_models.append(model_id)
            
    def AddModelIDToWhitelist(self, model_id: int):
        if not model_id in self.whitelisted_models:
            self.whitelisted_models.append(model_id)


    def GetfilteredLootArray(self, distance: float = Range.SafeCompass.value, multibox_loot: bool = False, allow_unasigned_loot=False) -> list[int]:        
        def IsValidItem(item_id):
            if not Agent.IsValid(item_id):
                return False    
            player_agent_id = Player.GetAgentID()
            owner_id = Agent.GetItemAgentOwnerID(item_id)
            return ((owner_id == player_agent_id) or (owner_id == 0))
        
        if not Routines.Checks.Map.MapValid():
            return []
            
        item_array = AgentArray.GetItemArray()
        item_array = AgentArray.Filter.ByDistance(item_array, Player.GetXY(), distance)

        item_array = AgentArray.Filter.ByCondition(
            item_array,
            lambda item_id: IsValidItem(item_id)
        )
        
        filtered_array = []

        for agent_id in item_array[:]:  # Iterate over a copy to avoid modifying while iterating
            item_data = Agent.GetItemAgentByID(agent_id)
            if item_data is None:
                continue
            
            item_id = item_data.item_id
            
            if not self.EvaluateItem(item_id):
                continue
            
            filtered_array.append(agent_id)
            
        return AgentArray.Sort.ByDistance(filtered_array, Player.GetXY())
