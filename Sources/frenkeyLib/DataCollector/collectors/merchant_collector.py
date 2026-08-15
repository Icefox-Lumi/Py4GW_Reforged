
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.UIManager import MerchantWindow
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils

from Sources.frenkeyLib.DataCollector.collectors.base_collectors import ListCollector
from Sources.frenkeyLib.DataCollector.models import Merchant


class MerchantCollector(ListCollector[Merchant]):
    def __init__(self, document_name: str, *, version: str = '1.0', value_type=None):
        super().__init__(document_name, version=version, value_type=value_type)
        self.map_merchants : list[Merchant] = []
        
        
    def _collect(self):        
        agent_ids = AgentArray.GetNPCMinipetArray()
        map_id = Map.GetBaseMapID()
        
        for agent_id in agent_ids:
            if agent_id in self.checked_ids:
                continue
            
            model_id = Agent.GetModelID(agent_id)
            matching_merchants = [merchant for merchant in self.map_merchants if merchant.model_id == model_id]
            pos = Agent.GetXY(agent_id)
            
            if matching_merchants:
                closest_merchant = min(matching_merchants, key=lambda merchant: Utils.Distance(merchant.position, pos))
                if Utils.Distance(closest_merchant.position, pos) < Range.Earshot.value:  # Threshold for matching
                    self.mark_id_as_checked(agent_id)
                    continue
            
            name = Agent.GetNameByID(agent_id) or ""
            if not name:
                continue
            
            if not name.replace("[", "").replace("]", "").lower().endswith("merchant"):
                self.mark_id_as_checked(agent_id)
                continue
            
            enc_name = bytes(Agent.GetEncNameByID(agent_id))
            new_merchant = Merchant(name=name, model_id=model_id, encoded_name=enc_name, position=pos, map_id=map_id)
            self.add_merchant(new_merchant)
            self.mark_id_as_checked(agent_id)
            
        if self.map_merchants:
            if MerchantWindow.IsOpen():
                for merchant in self.map_merchants:
                    if merchant.CollectData():
                        self.requires_save = True
                
    def add_merchant(self, merchant: Merchant):
        self.map_merchants.append(merchant)
        self.append(merchant)
        self.requires_save = True
    
    def _flush_cache(self):
        super()._flush_cache()
        self.map_merchants.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_merchants = [merchant for merchant in self if merchant.map_id == self.current_map_id]
        self.map_merchants.extend(map_merchants)

MERCHANTS = MerchantCollector("Widgets/Data Collector/merchants.json")