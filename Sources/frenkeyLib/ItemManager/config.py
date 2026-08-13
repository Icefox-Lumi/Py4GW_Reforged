import os

import Py4GW
import PySystem
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings


class Config:
    instance = None
    
    def __new__(cls):
        if cls.instance is None:
            cls.instance = super(Config, cls).__new__(cls)
            cls.instance.__init__()
        return cls.instance
    
    def __init__(self):
        if hasattr(self, 'initialized') and self.initialized:
            return
        
        self.initialized = False
        self.ini_path = "Widgets/Guild Wars/Items & Loot/Item Manager"
        self.main_ini_key = ""
        self.floating_ini_key = ""
        
        self.icon_path = os.path.join(PySystem.Console.get_projects_path(), "Textures", "Module_Icons", "item_manager.png")
        
        pass
    
    def _ensure_ini(self) -> bool:
        if self.initialized:
            return True

        self.main_ini_key = f"{self.ini_path}/ItemManager.ini"
        self.floating_ini_key = f"{self.ini_path}/ItemManager_FloatingIcon.ini"

        main_settings = Settings(self.main_ini_key, "account")
        floating_settings = Settings(self.floating_ini_key, "account")
        if not main_settings.is_ready() or not floating_settings.is_ready():
            return False

        self.initialized = True
        return True
