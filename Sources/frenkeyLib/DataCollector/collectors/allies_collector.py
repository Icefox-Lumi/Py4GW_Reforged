from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import BaseCollector, ListCollector
from Sources.frenkeyLib.DataCollector.models import Ally


class AlliesCollector(ListCollector[Ally]):
    def __init__(self, get_local_path, get_default_path, *, version = '1.0', value_type = None, key_decoder = None, key_encoder = None):
        super().__init__(get_local_path, get_default_path, version=version, value_type=value_type, key_decoder=key_decoder, key_encoder=key_encoder)
        self.map_allies: list[Ally] = []
        
    def _collect(self):        
        agent_ids = AgentArray.GetNPCMinipetArray()
        map_id = Map.GetBaseMapID()
        
        for agent_id in agent_ids:
            if agent_id in self.checked_ids:
                continue
            
            model_id = Agent.GetModelID(agent_id)
            matching_allies = [ally for ally in self.map_allies if ally.model_id == model_id]
            pos = Agent.GetXY(agent_id)
            
            if matching_allies:
                closest_ally = min(matching_allies, key=lambda ally: Utils.Distance(ally.position, pos))
                if Utils.Distance(closest_ally.position, pos) < Range.Earshot.value:  # Threshold for matching
                    self.mark_id_as_checked(agent_id)
                    continue
            
            name = Agent.GetNameByID(agent_id) or ""
            if not name:
                continue
                        
            enc_name = bytes(Agent.GetEncNameByID(agent_id))
            new_ally = Ally(name=name, model_id=model_id, encoded_name=enc_name, position=pos, map_id=map_id)
            self.add_ally(new_ally)
            self.mark_id_as_checked(agent_id)
    
    def add_ally(self, ally: Ally):
        self.map_allies.append(ally)
        self.append(ally)
        self.requires_save = True
    
    def _flush_cache(self):
        super()._flush_cache()
        self.map_allies.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_allies = [ally for ally in self if ally.map_id == self.current_map_id]
        self.map_allies.extend(map_allies)
        

ALLIES = AlliesCollector(*BaseCollector.get_path_providers("allies.json"))
