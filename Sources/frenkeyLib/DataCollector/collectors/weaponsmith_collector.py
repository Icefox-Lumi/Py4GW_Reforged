
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.UIManager import CrafterWindow
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import ListCollector
from Sources.frenkeyLib.DataCollector.models import Weaponsmith


    
class WeaponsmithCollector(ListCollector[Weaponsmith]):
    def __init__(self, document_name: str, *, version: str = '1.0', value_type=None):
        super().__init__(document_name, version=version, value_type=value_type)
        self.map_weaponsmiths : list[Weaponsmith] = []
        self.unrevealed_map_weaponsmiths : list[Weaponsmith] = []
        
    def _collect(self):   
        if not self.map_weaponsmiths:
            return
        
        if CrafterWindow.IsOpen():
            for weaponsmith in self.map_weaponsmiths:
                if weaponsmith.CollectData():
                    self.requires_save = True
                
        if self.unrevealed_map_weaponsmiths:            
            agent_ids = AgentArray.GetNPCMinipetArray()
            
            for agent_id in agent_ids:
                if agent_id in self.checked_ids:
                    continue
                
                name = Agent.GetNameByID(agent_id) or ""
                if not name:
                    continue
                            
                model_id = Agent.GetModelID(agent_id)
                pos = Agent.GetXY(agent_id)
                updated_weaponsmith = None
                
                for weaponsmith in self.unrevealed_map_weaponsmiths:
                    if weaponsmith.position != (0.0, 0.0) and Utils.Distance(weaponsmith.position, pos) > Range.Touch.value:
                        continue
                    
                    if weaponsmith.model_id != 0 and model_id not in (0, weaponsmith.model_id):
                        continue
                    
                    if not weaponsmith.name.lower() in name.lower():
                        continue
                    
                    weaponsmith.position = pos
                    weaponsmith.model_id = model_id
                    weaponsmith.name = name
                    weaponsmith.encoded_name = bytes(Agent.GetEncNameByID(agent_id))
                    updated_weaponsmith = weaponsmith
                    self.requires_save = True
                    break
                
                if updated_weaponsmith:
                    self.unrevealed_map_weaponsmiths.remove(updated_weaponsmith)
                
                self.mark_id_as_checked(agent_id)            
            
    def _flush_cache(self):
        super()._flush_cache()
        self.map_weaponsmiths.clear()
        self.unrevealed_map_weaponsmiths.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_weaponsmiths = [weaponsmith for weaponsmith in self if weaponsmith.map_id == self.current_map_id and weaponsmith.HasMissingData()]
        self.map_weaponsmiths.extend(map_weaponsmiths)
        self.unrevealed_map_weaponsmiths.extend([weaponsmith for weaponsmith in map_weaponsmiths if weaponsmith.position == (0.0, 0.0) or weaponsmith.map_id == 0 or weaponsmith.model_id == 0])
    
WEAPONSMITHS = WeaponsmithCollector("Widgets/Data Collector/weaponsmiths.json")