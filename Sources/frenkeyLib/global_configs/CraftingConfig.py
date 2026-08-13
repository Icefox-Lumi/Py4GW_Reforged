from __future__ import annotations

import json
import os
from typing import Any, ClassVar, Self, cast

from Py4GWCoreLib.Item import Bag

    
class CraftingConfig():
    _initialized: bool = False    
    _instance : ClassVar[Self | None] = None

    def __new__(cls: type[Self]) -> Self:
        instance = cast(Self | None, cls._instance)
        if instance is None:
            instance = cast(Self, super().__new__(cls))
            instance._initialized = False
            cls._instance = instance
        return instance
            
    def __init__(self):
        if self._initialized:
            self._ensure_profile_sync()
            return

        self._initialized = True
        self.reset_to_defaults()
        self._ensure_profile_sync()

    def _ensure_profile_sync(self) -> None:
        try:
            from Sources.frenkeyLib.global_configs.GlobalConfigProfileManager import GLOBAL_CONFIG_PROFILE_MANAGER

            GLOBAL_CONFIG_PROFILE_MANAGER.refresh_and_sync()
        except Exception:
            pass

    def reset_to_defaults(self) -> None:
        self.selected_recipe_keys: list[str] = []
        self.allow_shopping: bool = False

    def reload_from_file(self, file_path: str) -> None:
        if not os.path.isfile(file_path):
            self.reset_to_defaults()
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)

        self.load_dict(json_data if isinstance(json_data, dict) else {})

    def to_dict(self) -> dict[str, Any]:
        return {
            'selected_recipe_keys': [
                str(recipe_key)
                for recipe_key in self.selected_recipe_keys
                if isinstance(recipe_key, str) and recipe_key != ''
            ],
            'allow_shopping': bool(self.allow_shopping),
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        recipe_keys = data.get('selected_recipe_keys', [])
        if isinstance(recipe_keys, list):
            self.selected_recipe_keys = [str(recipe_key) for recipe_key in recipe_keys if recipe_key]
        else:
            self.selected_recipe_keys = []

        self.allow_shopping = bool(data.get('allow_shopping', False))
        
    
    @classmethod
    def Load(cls: type[Self], file_path: str) -> Self:
        '''
        Loads the config from a JSON file at the specified file path and returns a new instance of the config with the loaded rules.
        '''
        instance = cls()
        instance.reload_from_file(file_path)
        return instance
