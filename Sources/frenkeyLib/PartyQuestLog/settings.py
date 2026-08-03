
import os
from typing import Optional

import PySystem
from Py4GWCoreLib.GlobalCache.SharedMemory import AccountStruct
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings as NativeSettings
from Py4GWCoreLib.py4gwcorelib_src.Console import Console, ConsoleLog
from Py4GWCoreLib.py4gwcorelib_src.Timer import ThrottledTimer


class Settings:
    _instance = None
    _initialized = False    
        
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
        return cls._instance
    
    def __init__(self): 
        # guard: only initialize once
        if self.__class__._initialized:
            return
        
        self.__class__._initialized = True
        
        base_path = PySystem.Console.get_projects_path()
        self.ini_path = os.path.join(base_path, "Widgets", "Config", "PartyQuestLog.ini")
        
        self.save_requested = False        
        if not os.path.exists(self.ini_path):
            ConsoleLog("Party Quest Log", "Settings file not found. Creating default settings...")
            self.save_requested = True  
        
        self.save_throttle_timer = ThrottledTimer(1000)
        self.ini_handler = NativeSettings("Widgets/Config/PartyQuestLog.ini", "global")
        
        self.ShowOnlyInParty : bool = True
        self.ShowOnlyOnLeader : bool = True
        self.ShowFollowerActiveQuestOnMinimap : bool = True
        self.ShowFollowerActiveQuestOnMissionMap : bool = True
        
        self.show_quests_for_accounts : dict[str, bool] = {}
            
    def save_settings(self):
        self.save_requested = True
    
    def write_settings(self):               
        if not self.save_requested:
            return
        
        if not self.save_throttle_timer.IsExpired():
            return        
        
        self.save_throttle_timer.Reset()
        self.save_requested = False
        
        self.ini_handler.set("QuestLog", "ShowOnlyInParty", str(self.ShowOnlyInParty))
        self.ini_handler.set("QuestLog", "ShowOnlyOnLeader", str(self.ShowOnlyOnLeader))
        
        self.ini_handler.set("Overlays", "ShowFollowerActiveQuestOnMinimap", str(self.ShowFollowerActiveQuestOnMinimap))
        self.ini_handler.set("Overlays", "ShowFollowerActiveQuestOnMissionMap", str(self.ShowFollowerActiveQuestOnMissionMap))
        
        for account_email, enabled in self.show_quests_for_accounts.items():
            self.ini_handler.set("OverlayAccounts", account_email, str(enabled))
        
    def load_settings(self):
        self.ShowOnlyInParty = self.ini_handler.get_bool("QuestLog", "ShowOnlyInParty", self.ShowOnlyInParty)
        self.ShowOnlyOnLeader = self.ini_handler.get_bool("QuestLog", "ShowOnlyOnLeader", self.ShowOnlyOnLeader)
        self.ShowFollowerActiveQuestOnMinimap = self.ini_handler.get_bool("Overlays", "ShowFollowerActiveQuestOnMinimap", self.ShowFollowerActiveQuestOnMinimap)
        self.ShowFollowerActiveQuestOnMissionMap = self.ini_handler.get_bool("Overlays", "ShowFollowerActiveQuestOnMissionMap", self.ShowFollowerActiveQuestOnMissionMap)
        
        account_section = self.ini_handler.items("OverlayAccounts")

        if account_section:
            for account_email, _ in account_section.items():
                self.show_quests_for_accounts[account_email] = self.ini_handler.get_bool("OverlayAccounts", account_email, True)
        pass

    
