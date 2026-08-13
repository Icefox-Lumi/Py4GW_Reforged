import os
from typing import Callable, Optional

import Py4GW
import PySystem
from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.enums_src.Multiboxing_enums import ReloadType, SharedCommandType
from Py4GWCoreLib.py4gwcorelib_src.Timer import ThrottledTimer
from Sources.frenkeyLib.Core.data_dict import DataDict, DataList
from Sources.frenkeyLib.Core.json_serializable import T_DICT_KEY, T_SERIALIZABLE_VALUE

class BaseCollector:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.run_throttle = ThrottledTimer(250)
        self.save_throttle = ThrottledTimer(1_000)
        self.current_context_key = ''
        self.checked_ids: list[int] = []

    def _get_reload_type(self) -> ReloadType:
        for reload_type in ReloadType:
            if reload_type.name.lower().startswith(self.__class__.__name__.replace("Collector", "").lower()):
                return reload_type
        
        return ReloadType.Unknown
    
    def mark_id_as_checked(self, agent_id: int):
        self.checked_ids.append(agent_id)
            
    def run(self):
        self._handle_context_change()

        if isinstance(self, (DataDict, DataList)) and self.refresh_from_disk_if_changed():
            self._flush_cache()
        
        if not self._is_ready():
            return
        
        if self.run_throttle.IsExpired():
            self.run_throttle.Reset()
            self._collect()

        if self.save_throttle.IsExpired():
            self.save_throttle.Reset()

            if isinstance(self, (DataDict, DataList)):
                if self.try_save():
                    broadcast_save = False
                    
                    if broadcast_save:
                        own_mail = Player.GetAccountEmail()
                        for acc in GLOBAL_CACHE.ShMem.GetAllAccountData():
                            if acc.IsAccount:
                                GLOBAL_CACHE.ShMem.SendMessage(acc.AccountEmail, own_mail, SharedCommandType.Reload, (self._get_reload_type(),))

    def _is_ready(self) -> bool:
        return Map.IsMapReady() and Player.IsPlayerLoaded()
    
    def _collect(self):
        raise NotImplementedError

    def _flush_cache(self):
        self.checked_ids.clear()

    def _handle_context_change(self):
        context_key = self._get_context_key()
        if context_key == self.current_context_key:
            return

        self.current_context_key = context_key
        self._flush_cache()

    def _get_context_key(self) -> str:
        account_email = str(Player.GetAccountEmail() or '').strip()
        player_name = str(Player.GetName() or '').strip()
        map_id = int(Map.GetMapID() or 0)
        return f'{account_email}|{player_name}|{map_id}'
    
    @staticmethod
    def get_path_providers(file_name : str) -> tuple[Callable[..., str], Callable[..., str]]:        
        def local_path_provider() -> str:
            return os.path.join(PySystem.Console.get_projects_path(), "Settings", "Global", "Widgets", "Data Collector", file_name)

        def default_path_provider() -> str:
            return os.path.join(PySystem.Console.get_projects_path(), "Sources", "frenkeyLib", "data", file_name)

        return local_path_provider, default_path_provider

class ListCollector(BaseCollector, DataList[T_SERIALIZABLE_VALUE]):
    def __init__(self,
        get_local_path: Callable[..., str],
        get_default_path: Callable[..., str],
        *,
        version: str = '1.0',
        value_type: Optional[type[T_SERIALIZABLE_VALUE]] = None,
        key_decoder: Optional[Callable[[str], T_DICT_KEY]] = None,
        key_encoder: Optional[Callable[[T_DICT_KEY], str]] = None,
    ):
        super().__init__(
            get_local_path,
            get_default_path,
            version=version,
            value_type=value_type,
            key_decoder=key_decoder,
            key_encoder=key_encoder,
        )
        self.load()
