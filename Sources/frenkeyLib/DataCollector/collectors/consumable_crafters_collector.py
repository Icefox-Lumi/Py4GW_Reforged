
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.UIManager import CrafterWindow
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils

from Sources.frenkeyLib.DataCollector.collectors.base_collectors import ListCollector
from Sources.frenkeyLib.DataCollector.models import ConsumableCrafter


class ConsumableCraftersCollector(ListCollector[ConsumableCrafter]):
    def __init__(self, document_name: str, *, version: str = '1.0', value_type=None):
        super().__init__(document_name, version=version, value_type=value_type)
        self.map_consumable_crafters : list[ConsumableCrafter] = []
        self.unrevealed_map_consumable_crafters : list[ConsumableCrafter] = []
        
    def _collect(self):   
        if not self.map_consumable_crafters:
            return
        
        if CrafterWindow.IsOpen():
            for consumable_crafter in self.map_consumable_crafters:
                if consumable_crafter.CollectData():
                    self.requires_save = True
                
        if self.unrevealed_map_consumable_crafters:            
            agent_ids = AgentArray.GetNPCMinipetArray()
            
            for agent_id in agent_ids:
                if agent_id in self.checked_ids:
                    continue
                
                name = Agent.GetNameByID(agent_id) or ""
                if not name:
                    continue
                            
                model_id = Agent.GetModelID(agent_id)
                pos = Agent.GetXY(agent_id)
                updated_consumable_crafter = None
                
                for consumable_crafter in self.unrevealed_map_consumable_crafters:
                    if consumable_crafter.position != (0.0, 0.0) and Utils.Distance(consumable_crafter.position, pos) > Range.Touch.value:
                        continue
                    
                    if consumable_crafter.model_id != 0 and model_id not in (0, consumable_crafter.model_id):
                        continue
                    
                    if not consumable_crafter.name.lower() in name.lower():
                        continue
                    
                    consumable_crafter.position = pos
                    consumable_crafter.model_id = model_id
                    consumable_crafter.name = name
                    consumable_crafter.encoded_name = bytes(Agent.GetEncNameByID(agent_id))
                    updated_consumable_crafter = consumable_crafter
                    self.requires_save = True
                    break
                
                if updated_consumable_crafter:
                    self.unrevealed_map_consumable_crafters.remove(updated_consumable_crafter)
                
                self.mark_id_as_checked(agent_id)
            
    def _flush_cache(self):
        super()._flush_cache()
        self.map_consumable_crafters.clear()
        self.unrevealed_map_consumable_crafters.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_consumable_crafters = [consumable_crafter for consumable_crafter in self if consumable_crafter.map_id == self.current_map_id and consumable_crafter.HasMissingData()]
        self.map_consumable_crafters.extend(map_consumable_crafters)
        self.unrevealed_map_consumable_crafters.extend([consumable_crafter for consumable_crafter in map_consumable_crafters if consumable_crafter.position == (0.0, 0.0) or consumable_crafter.map_id == 0 or consumable_crafter.model_id == 0])
        
CONSUMABLE_CRAFTERS = ConsumableCraftersCollector("Widgets/Data Collector/consumable_crafters.json")