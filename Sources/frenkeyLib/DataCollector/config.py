from dataclasses import dataclass

from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings


@dataclass
class DataCollectorConfig:
    ini_path: str = 'Widgets/System/'
    main_ini_filename: str = 'DataCollector.ini'
    floating_ini_filename: str = 'DataCollectorFloating.ini'
    settings_section: str = 'Settings'
    
    enabled_var_name: str = 'collector_enabled'    

    main_ini_key: str = ''
    floating_ini_key: str = ''
    ini_init: bool = False

    def ensure_ini(self) -> bool:
        if self.ini_init:
            return True

        self.main_ini_key = f"{self.ini_path}{self.main_ini_filename}"
        self.floating_ini_key = f"{self.ini_path}{self.floating_ini_filename}"

        main_settings = Settings(self.main_ini_key, "global")
        floating_settings = Settings(self.floating_ini_key, "global")
        if not main_settings.is_ready() or not floating_settings.is_ready():
            return False

        default_enabled = {
            self.enabled_var_name: True,
            "CollectAllies": True,
            "CollectArmorer": True,
            "CollectArtisans": True,
            "CollectCollectors": True,
            "CollectConsumableCrafters": True,
            "CollectFoes": True,
            "CollectMerchants": True,
            "CollectTraders": True,
            "CollectWeaponsmiths": True,
            "CollectItems": True,
            "CollectChests": True,
        }
        for key, value in default_enabled.items():
            if not main_settings.has(self.settings_section, key):
                main_settings.set_bool(self.settings_section, key, value)

        self.ini_init = True
        return True

