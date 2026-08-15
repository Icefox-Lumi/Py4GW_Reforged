import PySystem
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings
from Py4GWCoreLib.py4gwcorelib_src.Timer import ThrottledTimer
from Py4GWCoreLib.py4gwcorelib_src.WidgetManager import get_widget_handler
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import BaseCollector
from Sources.frenkeyLib.DataCollector.collectors.items_collector import ITEMS
from Sources.frenkeyLib.DataCollector.config import DataCollectorConfig


class DataCollectorRuntime:
    def __init__(self, module_name: str, module_icon: str):
        self.module_name = module_name
        self.module_icon = module_icon
        self.config = DataCollectorConfig()
        self.run_throttle = ThrottledTimer(250)
        # Only the item catalog is wired into the runtime. The other legacy
        # collectors (allies, armorers, artisans, chests, collectors,
        # consumable crafters, foes, merchants, traders, weaponsmiths) are
        # dormant: their modules remain importable but are not driven here.
        self.collectors : dict[str, BaseCollector] = {
            # 'Allies': ALLIES,
            # 'Armorers': ARMORERS,
            # 'Artisans': ARTISANS,
            # 'Collectors': COLLECTORS,
            # 'Consumable Crafters': CONSUMABLE_CRAFTERS,
            # 'Foes': FOES,
            # 'Merchants': MERCHANTS,
            # 'Traders': TRADERS,
            # 'Weaponsmiths': WEAPONSMITHS,
            'Items': ITEMS,
            # 'Chests': CHESTS,
        }
        
        self.collector_enabled = True
        self.collecting : dict[str, bool] = {name: False for name in self.collectors.keys()}
        self._settings_loaded = False
        self.widget_handler = get_widget_handler()

    def _ensure_initialized(self) -> bool:
        if not self.config.ensure_ini():
            return False

        if not self._settings_loaded:
            self._load_settings()
            self._settings_loaded = True

        return True

    def ensure_state(self) -> bool:
        if not self._ensure_initialized():
            return False

        if not self.collector_enabled and self.widget_handler.discovered:
            self.widget_handler.disable_widget(self.module_name)

        return True

    def _load_settings(self):
        self.collector_enabled = bool(
            Settings(self.config.main_ini_key, "global").get_bool(
                self.config.settings_section,
                self.config.enabled_var_name,
                True,
            )
        )
        
        for collector_name, _ in self.collectors.items():
            enabled = bool(
                Settings(self.config.main_ini_key, "global").get_bool(
                    self.config.settings_section,
                    f"Collect{collector_name.replace(' ', '')}",
                    True,
                )
            )
            self.collecting[collector_name] = enabled

    def _save_collector_setting(self, collector_name: str, enabled: bool):
        Settings(self.config.main_ini_key, "global").set_bool(
            self.config.settings_section,
            f"Collect{collector_name.replace(' ', '')}",
            bool(enabled),
        )

    def _save_settings(self):
        Settings(self.config.main_ini_key, "global").set_bool(
            self.config.settings_section,
            self.config.enabled_var_name,
            bool(self.collector_enabled),
        )

    def set_collector_enabled(self, enabled: bool):
        if not self._ensure_initialized():
            return

        enabled = bool(enabled)
        if enabled:
            PySystem.Console.Log(
                self.module_name,
                'Data collector is enabled. Thank you for contributing by collecting data!',
                PySystem.Console.MessageType.Success,
            )
        else:
            PySystem.Console.Log(
                self.module_name,
                'Data collector is disabled. Enable the collector again to start contributing by collecting data.',
                PySystem.Console.MessageType.Warning,
            )

        self.collector_enabled = enabled
        self._save_settings()

    def run(self):
        if not self.ensure_state():
            return

        for collector_name, collector in self.collectors.items():
            if self.collecting[collector_name]:
                collector.run()
