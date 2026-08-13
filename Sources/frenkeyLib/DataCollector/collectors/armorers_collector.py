
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.UIManager import CrafterWindow
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import BaseCollector, ListCollector
from Sources.frenkeyLib.DataCollector.models import Armorer

class ArmorerCollector(ListCollector[Armorer]):
    def __init__(self, get_local_path, get_default_path, *, version = '1.0', value_type = None, key_decoder = None, key_encoder = None):
        super().__init__(get_local_path, get_default_path, version=version, value_type=value_type, key_decoder=key_decoder, key_encoder=key_encoder)
        self.map_armorers : list[Armorer] = []
        self.unrevealed_map_armorers : list[Armorer] = []
        
    def _collect(self):   
        if not self.map_armorers:
            return
        
        if CrafterWindow.IsOpen():
            for armorer in self.map_armorers:
                if armorer.CollectData():
                    self.requires_save = True
                
        if self.unrevealed_map_armorers:            
            agent_ids = AgentArray.GetNPCMinipetArray()
            
            for agent_id in agent_ids:
                if agent_id in self.checked_ids:
                    continue
                
                name = Agent.GetNameByID(agent_id) or ""
                if not name:
                    continue
                            
                model_id = Agent.GetModelID(agent_id)
                pos = Agent.GetXY(agent_id)
                updated_armorer = None
                
                for armorer in self.unrevealed_map_armorers:
                    if armorer.position != (0.0, 0.0) and Utils.Distance(armorer.position, pos) > Range.Touch.value:
                        continue
                    
                    if armorer.model_id != 0 and model_id not in (0, armorer.model_id):
                        continue
                    
                    if not armorer.name.lower() in name.lower():
                        continue
                    
                    armorer.position = pos
                    armorer.model_id = model_id
                    armorer.name = name
                    armorer.encoded_name = bytes(Agent.GetEncNameByID(agent_id))
                    updated_armorer = armorer
                    self.requires_save = True
                    break
                
                if updated_armorer:
                    self.unrevealed_map_armorers.remove(updated_armorer)
                    
                self.mark_id_as_checked(agent_id)
                                
            
    def _flush_cache(self):
        super()._flush_cache()
        self.map_armorers.clear()
        self.unrevealed_map_armorers.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_armorers = [armorer for armorer in self if armorer.map_id == self.current_map_id and armorer.HasMissingData()]
        self.map_armorers.extend(map_armorers)
        self.unrevealed_map_armorers.extend([armorer for armorer in map_armorers if armorer.position == (0.0, 0.0) or armorer.map_id == 0 or armorer.model_id == 0])
        
ARMORERS = ArmorerCollector(*BaseCollector.get_path_providers("armorers.json"))