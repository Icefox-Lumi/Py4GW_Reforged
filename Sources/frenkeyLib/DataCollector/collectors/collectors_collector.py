
import Py4GW

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.UIManager import CollectorWindow
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import BaseCollector, ListCollector
from Sources.frenkeyLib.DataCollector.models import Collector


class CollectorsCollector(ListCollector[Collector]):
    def __init__(self, get_local_path, get_default_path, *, version = '1.0', value_type = None, key_decoder = None, key_encoder = None):
        super().__init__(get_local_path, get_default_path, version=version, value_type=value_type, key_decoder=key_decoder, key_encoder=key_encoder)
        self.map_collectors : list[Collector] = []
        self.unrevealed_map_collectors : list[Collector] = []
        
    def _collect(self):   
        if not self.map_collectors:
            return
        
        if CollectorWindow.IsOpen():
            for collector in self.map_collectors:
                if collector.CollectData():
                    self.requires_save = True
                
        if self.unrevealed_map_collectors:            
            agent_ids = AgentArray.GetNPCMinipetArray()
            
            for agent_id in agent_ids:
                if agent_id in self.checked_ids:
                    continue
                
                name = Agent.GetNameByID(agent_id) or ""
                if not name:
                    continue
                            
                model_id = Agent.GetModelID(agent_id)
                pos = Agent.GetXY(agent_id)
                updated_collector = None
                
                for collector in self.unrevealed_map_collectors:
                    if collector.position != (0.0, 0.0) and Utils.Distance(collector.position, pos) > Range.Touch.value:
                        continue
                    
                    if collector.model_id != 0 and model_id not in (0, collector.model_id):
                        continue
                    
                    if not collector.name.lower() in name.lower():
                        continue
                    
                    collector.position = pos
                    collector.model_id = model_id
                    collector.name = name
                    collector.encoded_name = bytes(Agent.GetEncNameByID(agent_id))
                    updated_collector = collector
                    self.requires_save = True
                    break
                
                if updated_collector:
                    self.unrevealed_map_collectors.remove(updated_collector)
                
                self.mark_id_as_checked(agent_id)
            
    def _flush_cache(self):
        super()._flush_cache()
        self.map_collectors.clear()
        self.unrevealed_map_collectors.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_collectors = [collector for collector in self if collector.map_id == Map.GetBaseMapID(self.current_map_id) and collector.HasMissingData()]
        self.map_collectors.extend(map_collectors)
        self.unrevealed_map_collectors.extend([collector for collector in map_collectors if collector.position == (0.0, 0.0) or collector.map_id == 0 or collector.model_id == 0])
        


COLLECTORS = CollectorsCollector(*BaseCollector.get_path_providers("collectors.json"))