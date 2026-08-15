
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import ListCollector
from Sources.frenkeyLib.DataCollector.models import Trader, TraderType


class TraderCollector(ListCollector[Trader]):
    def __init__(self, document_name: str, *, version: str = '1.0', value_type=None):
        super().__init__(document_name, version=version, value_type=value_type)
        self.map_traders : list[Trader] = []
        
    def _collect(self):        
        agent_ids = AgentArray.GetNPCMinipetArray()
        map_id = Map.GetBaseMapID()
        
        for agent_id in agent_ids:
            if agent_id in self.checked_ids:
                continue
            
            model_id = Agent.GetModelID(agent_id)
            matching_traders = [trader for trader in self.map_traders if trader.model_id == model_id]
            pos = Agent.GetXY(agent_id)
            
            if matching_traders:
                closest_trader = min(matching_traders, key=lambda trader: Utils.Distance(trader.position, pos))
                if Utils.Distance(closest_trader.position, pos) < Range.Earshot.value:  # Threshold for matching
                    self.mark_id_as_checked(agent_id)
                    continue
            
            name = Agent.GetNameByID(agent_id) or ""
            if not name:
                continue
            
            trader_type = TraderType.get_type_from_name(name)
            if trader_type is TraderType.Unknown:
                self.mark_id_as_checked(agent_id)
                continue
            
            enc_name = bytes(Agent.GetEncNameByID(agent_id))
            new_trader = Trader(name=name, model_id=model_id, encoded_name=enc_name, position=pos, map_id=map_id, _trader_type=trader_type)
            self.add_trader(new_trader)
            self.mark_id_as_checked(agent_id)
            
    def add_trader(self, trader: Trader):
        self.map_traders.append(trader)
        self.append(trader)
        self.requires_save = True
    
    def _flush_cache(self):
        super()._flush_cache()
        self.map_traders.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_traders = [trader for trader in self if trader.map_id == self.current_map_id]
        self.map_traders.extend(map_traders)

TRADERS = TraderCollector("Widgets/Data Collector/traders.json")
