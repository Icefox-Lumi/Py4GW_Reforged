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

    def reload_from_document(self, document, profile_key: str | None = None) -> None:
        if document is None:
            self.reset_to_defaults()
            return

        path = "config" if profile_key is None else f"profiles/{profile_key}"
        json_data = document.get_json(path, {})
        self.load_dict(json_data if isinstance(json_data, dict) else {})

    def save_to_document(self, document, profile_key: str | None = None) -> None:
        if document is None:
            return
        path = "config" if profile_key is None else f"profiles/{profile_key}"
        document.set_json(path, self.to_dict())

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
        
    
