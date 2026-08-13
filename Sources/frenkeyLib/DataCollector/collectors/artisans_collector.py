
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.UIManager import CrafterWindow
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import BaseCollector, ListCollector
from Sources.frenkeyLib.DataCollector.models import Artisan


class ArtisanCollector(ListCollector[Artisan]):
    def __init__(self, get_local_path, get_default_path, *, version = '1.0', value_type = None, key_decoder = None, key_encoder = None):
        super().__init__(get_local_path, get_default_path, version=version, value_type=value_type, key_decoder=key_decoder, key_encoder=key_encoder)
        self.map_artisans : list[Artisan] = []
        self.unrevealed_map_artisans : list[Artisan] = []
        
    def _collect(self):   
        if not self.map_artisans:
            return
        
        if CrafterWindow.IsOpen():
            for artisan in self.map_artisans:
                if artisan.CollectData():
                    self.requires_save = True
                
        if self.unrevealed_map_artisans:            
            agent_ids = AgentArray.GetNPCMinipetArray()
            
            for agent_id in agent_ids:
                if agent_id in self.checked_ids:
                    continue
                
                name = Agent.GetNameByID(agent_id) or ""
                if not name:
                    continue
                            
                model_id = Agent.GetModelID(agent_id)
                pos = Agent.GetXY(agent_id)
                updated_artisan = None
                
                for artisan in self.unrevealed_map_artisans:
                    if artisan.position != (0.0, 0.0) and Utils.Distance(artisan.position, pos) > Range.Touch.value:
                        continue
                    
                    if artisan.model_id != 0 and model_id not in (0, artisan.model_id):
                        continue
                    
                    if not artisan.name.lower() in name.lower():
                        continue
                    
                    artisan.position = pos
                    artisan.model_id = model_id
                    artisan.name = name
                    artisan.encoded_name = bytes(Agent.GetEncNameByID(agent_id))
                    updated_artisan = artisan
                    self.requires_save = True
                    break
                
                if updated_artisan:
                    self.unrevealed_map_artisans.remove(updated_artisan)
                    
                self.mark_id_as_checked(agent_id)
                                
            
    def _flush_cache(self):
        super()._flush_cache()
        self.map_artisans.clear()
        self.unrevealed_map_artisans.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_artisans = [artisan for artisan in self if artisan.map_id == self.current_map_id and artisan.HasMissingData()]
        self.map_artisans.extend(map_artisans)
        self.unrevealed_map_artisans.extend([artisan for artisan in map_artisans if artisan.position == (0.0, 0.0) or artisan.map_id == 0 or artisan.model_id == 0])
        
        
ARTISANS = ArtisanCollector(*BaseCollector.get_path_providers("artisans.json"))