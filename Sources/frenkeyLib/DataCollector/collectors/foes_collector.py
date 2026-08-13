
import Py4GW

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import BaseCollector, ListCollector
from Sources.frenkeyLib.DataCollector.models import Foe, FoeSpawn


class FoesCollector(ListCollector[Foe]):
    def __init__(self, get_local_path, get_default_path, *, version = '1.0', value_type = None, key_decoder = None, key_encoder = None):
        super().__init__(get_local_path, get_default_path, version=version, value_type=value_type, key_decoder=key_decoder, key_encoder=key_encoder)
        self.map_foes : list[Foe] = []
        
    def _collect(self):        
        agent_ids = AgentArray.GetEnemyArray()
        map_id = Map.GetBaseMapID()
        
        for agent_id in agent_ids:
            matching_foe = None
            
            model_id = Agent.GetModelID(agent_id)
            skill_id = Agent.GetCastingSkillID(agent_id)
            level = Agent.GetLevel(agent_id)  
            pos = Agent.GetXY(agent_id)
            
            matching_model_id_foe = next((foe for foe in self.map_foes if foe.model_id == model_id), None)
            matching_foe = next((foe for foe in self.map_foes if foe.model_id == model_id and any(Utils.Distance(s.position, pos) < Range.Earshot.value for s in foe.spawns.get(map_id, []))), None)
            if matching_foe:
                if skill_id != 0:
                    if not matching_foe.skills.get(level):
                        matching_foe.skills[level] = []
                    
                    if skill_id not in matching_foe.skills[level]:
                        matching_foe.skills[level].append(skill_id)
                        self.requires_save = True
            else:            
                candidate_spawn = FoeSpawn(
                    map_id=map_id,
                    position=pos,
                    level=level,
                    has_boss_aura=Agent.HasBossGlow(agent_id),
                )        
                
                if matching_model_id_foe:
                    existing_spawns = matching_model_id_foe.spawns.get(map_id, [])
                    if any(existing_spawn.matches(candidate_spawn) for existing_spawn in existing_spawns):
                        continue

                    if not matching_model_id_foe.spawns.get(map_id):
                        matching_model_id_foe.spawns[map_id] = []

                    matching_model_id_foe.spawns[map_id].append(candidate_spawn)
                    self.requires_save = True  
                              
                else:
                    name = Agent.GetNameByID(agent_id) or ""
                    if not name:
                        continue
                    
                    new_foe = Foe(name=name, model_id=model_id, encoded_name=bytes(Agent.GetEncNameByID(agent_id)), spawns={map_id: [candidate_spawn]}, skills={})
                    self.add_foe(new_foe)
            
    def add_foe(self, foe: Foe):
        self.map_foes.append(foe)
        self.append(foe)
        self.requires_save = True
        
    def _flush_cache(self):
        super()._flush_cache()
        self.map_foes.clear()
        self.current_map_id = Map.GetBaseMapID()
        
        map_foes = [foe for foe in self if self.current_map_id in foe.spawns]
        self.map_foes.extend(map_foes)
        
FOES = FoesCollector(*BaseCollector.get_path_providers("foes.json"))
