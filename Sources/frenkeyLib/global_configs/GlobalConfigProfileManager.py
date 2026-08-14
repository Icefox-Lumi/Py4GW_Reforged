from __future__ import annotations

import re
from typing import Any, Optional
from typing import ClassVar

import Py4GW
import PySystem
from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.enums_src.Multiboxing_enums import ReloadType
from Py4GWCoreLib.enums_src.Multiboxing_enums import SharedCommandType
from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory
from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings


class GlobalConfigProfileManager:
    SHARED_PROFILE_NAME = 'SHARED'
    _ACCOUNT_DEFAULT_CHARACTER = '__ACCOUNT_DEFAULT__'
    _instance: ClassVar['GlobalConfigProfileManager | None'] = None
    _PROFILE_NAME_RE = re.compile(r'[^A-Za-z0-9 _-]+')
    _CONFIG_TYPES = (
        'BuyConfig',
        'LootConfig',
        'InventoryConfig',
        'CraftingConfig',
        'SortingConfig',
    )
    _RELOAD_TYPES_BY_CONFIG_TYPE = {
        'BuyConfig': ReloadType.Buying,
        'LootConfig': ReloadType.Looting,
        'InventoryConfig': ReloadType.Inventory,
        'CraftingConfig': ReloadType.Crafting,
        'SortingConfig': ReloadType.Sorting,
    }

    def __new__(cls) -> 'GlobalConfigProfileManager':
        instance = cls._instance
        if instance is None:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instance = instance
        return instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._initialized = True
        self._ini_path = 'Item & Inventory'
        self._ini_filename = 'ItemManager.ini'
        self._ini_key: str = ''
        self._current_character: str = ''
        self._active_profile_names: dict[str, str] = {
            config_type: self.SHARED_PROFILE_NAME
            for config_type in self._CONFIG_TYPES
        }
        self._sync_in_progress = False
        self._last_loaded_signatures: dict[str, tuple[str, str, str]] = {}
        self._sync_classes_by_config_type: dict[str, type[Any]] | None = None

    def _get_sync_classes_by_config_type(self) -> dict[str, type[Any]]:
        if self._sync_classes_by_config_type is not None:
            return self._sync_classes_by_config_type

        from Sources.frenkeyLib.global_configs.BuyConfig import BuyConfig
        from Sources.frenkeyLib.global_configs.CraftingConfig import CraftingConfig
        from Sources.frenkeyLib.global_configs.InventoryConfig import InventoryConfig
        from Sources.frenkeyLib.global_configs.LootConfig import LootConfig
        from Sources.frenkeyLib.global_configs.SortingConfig import SortingConfig

        self._sync_classes_by_config_type = {
            'BuyConfig': BuyConfig,
            'LootConfig': LootConfig,
            'InventoryConfig': InventoryConfig,
            'CraftingConfig': CraftingConfig,
            'SortingConfig': SortingConfig,
        }
        return self._sync_classes_by_config_type

    @classmethod
    def sanitize_profile_name(cls, profile_name: str) -> str:
        sanitized = cls._PROFILE_NAME_RE.sub('', str(profile_name or '').strip())
        sanitized = re.sub(r'\s+', ' ', sanitized).strip(' .')
        return sanitized

    def _ensure_ini_key(self) -> str:
        if self._ini_key:
            return self._ini_key

        self._ini_key = f"{self._ini_path}/{self._ini_filename}"
        return self._ini_key

    def _get_character_storage_key(self, character_name: str | None = None) -> str:
        character_name = str(character_name or '').strip()
        return character_name if character_name else self._ACCOUNT_DEFAULT_CHARACTER

    @classmethod
    def normalize_config_type(cls, config_type: str) -> str:
        normalized = str(config_type or '').strip()
        if normalized not in cls._CONFIG_TYPES:
            raise ValueError(f'Unsupported config type: {config_type}')
        return normalized

    @classmethod
    def get_storage_key(cls, config_type: str) -> str:
        return cls.normalize_config_type(config_type).lower()

    def _shared_document(self, config_type: str) -> JsonFactory:
        normalized_config_type = self.normalize_config_type(config_type)
        key = self.get_storage_key(normalized_config_type)
        return JsonFactory(f"Item & Inventory/Configs/{key}_shared.json", "global")

    def _profiles_document(self, config_type: str) -> JsonFactory:
        normalized_config_type = self.normalize_config_type(config_type)
        key = self.get_storage_key(normalized_config_type)
        return JsonFactory(f"Item & Inventory/Configs/{key}_profiles.json", "account")

    def get_profile_document(self, config_type: str, profile_name: str) -> JsonFactory:
        normalized_config_type = self.normalize_config_type(config_type)
        if profile_name.upper() == self.SHARED_PROFILE_NAME or profile_name == '':
            return self._shared_document(normalized_config_type)
        return self._profiles_document(normalized_config_type)

    def get_active_config_document(self, config_type: str) -> JsonFactory:
        normalized_config_type = self.normalize_config_type(config_type)
        return self.get_profile_document(normalized_config_type, self._active_profile_names[normalized_config_type])

    def get_active_profile_key(self, config_type: str) -> Optional[str]:
        normalized_config_type = self.normalize_config_type(config_type)
        profile_name = self._active_profile_names[normalized_config_type]
        return None if profile_name.upper() == self.SHARED_PROFILE_NAME else profile_name

    @staticmethod
    def _profile_path(profile_name: str) -> str:
        return f"profiles/{profile_name}"

    def _get_profile_storage_key(self, character_name: str, config_type: str) -> str:
        return f'{self._get_character_storage_key(character_name)}::{self.normalize_config_type(config_type)}'

    def _replace_profile_assignments(self, config_type: str, old_profile_name: str, new_profile_name: str) -> None:
        normalized_config_type = self.normalize_config_type(config_type)
        normalized_old_name = self.sanitize_profile_name(old_profile_name)
        normalized_new_name = self.sanitize_profile_name(new_profile_name)
        if normalized_old_name == '' or normalized_old_name == normalized_new_name:
            return

        section_name = 'Character Config Profiles'
        storage_key_suffix = f'::{normalized_config_type}'.lower()
        settings = Settings(self._ensure_ini_key(), "account")
        if not settings.is_ready():
            return

        for option_name, option_value in list(settings.items(section_name).items()):
            if not option_name.endswith(storage_key_suffix):
                continue
            if self.sanitize_profile_name(option_value) != normalized_old_name:
                continue

            settings.set(section_name, option_name, normalized_new_name)

    def list_profiles(self, config_type: str) -> list[str]:
        normalized_config_type = self.normalize_config_type(config_type)
        profiles = [self.SHARED_PROFILE_NAME]
        try:
            stored_profiles = self._profiles_document(normalized_config_type).get_json("profiles", {})
        except Exception:
            stored_profiles = {}
        if isinstance(stored_profiles, dict):
            profiles.extend(sorted(stored_profiles.keys(), key=str.lower))
        return profiles

    def profile_exists(self, config_type: str, profile_name: str) -> bool:
        normalized_config_type = self.normalize_config_type(config_type)
        normalized = self.sanitize_profile_name(profile_name)
        if not normalized:
            return False
        if normalized.upper() == self.SHARED_PROFILE_NAME:
            return True
        return self._profiles_document(normalized_config_type).has(self._profile_path(normalized))

    def get_current_character(self) -> str:
        return self._current_character

    def get_active_profile_name(self, config_type: str) -> str:
        normalized_config_type = self.normalize_config_type(config_type)
        return self._active_profile_names[normalized_config_type]

    def _read_selected_profile_name(self, character_name: str, config_type: str) -> str:
        normalized_config_type = self.normalize_config_type(config_type)
        ini_key = self._ensure_ini_key()
        if not ini_key:
            return self.SHARED_PROFILE_NAME

        stored_profile_name = Settings(ini_key, "account").get_str(
            "Character Config Profiles",
            self._get_profile_storage_key(character_name, normalized_config_type),
            self.SHARED_PROFILE_NAME,
        )

        normalized = self.sanitize_profile_name(stored_profile_name)
        if normalized.upper() == self.SHARED_PROFILE_NAME:
            return self.SHARED_PROFILE_NAME
        return normalized or self.SHARED_PROFILE_NAME

    def _write_selected_profile_name(self, character_name: str, config_type: str, profile_name: str) -> None:
        normalized_config_type = self.normalize_config_type(config_type)
        ini_key = self._ensure_ini_key()
        if not ini_key:
            return

        Settings(ini_key, "account").set(
            "Character Config Profiles",
            self._get_profile_storage_key(character_name, normalized_config_type),
            profile_name,
        )

    def refresh(self, force: bool = False) -> bool:
        previous_character = self._current_character
        previous_profiles = dict(self._active_profile_names)

        next_character = str(Player.GetName() or '').strip()
        if next_character == '' and previous_character != '' and not force:
            next_character = previous_character
        character_changed = next_character != self._current_character
        self._current_character = next_character

        if force:
            ini_key = self._ensure_ini_key()
            if ini_key:
                Settings(ini_key, "account").reload()

        for config_type in self._CONFIG_TYPES:
            if force or character_changed:
                selected_profile = self._read_selected_profile_name(self._current_character, config_type)
            else:
                selected_profile = self._active_profile_names.get(config_type, self.SHARED_PROFILE_NAME)

            if not self.profile_exists(config_type, selected_profile):
                selected_profile = self.SHARED_PROFILE_NAME
                if force or character_changed or previous_profiles.get(config_type) != selected_profile:
                    self._write_selected_profile_name(self._current_character, config_type, selected_profile)

            self._active_profile_names[config_type] = selected_profile

        return previous_character != self._current_character or previous_profiles != self._active_profile_names

    def sync_loaded_configs(self, force: bool = False) -> bool:
        if self._sync_in_progress:
            return False

        self._sync_in_progress = True
        try:
            reloaded_any_config = False

            for config_type, config_class in self._get_sync_classes_by_config_type().items():
                profile_name = self._active_profile_names[config_type]
                document = self.get_active_config_document(config_type)
                profile_key = self.get_active_profile_key(config_type)
                signature = (self._current_character, profile_name, document.name)

                if not force and self._last_loaded_signatures.get(config_type) == signature:
                    continue

                config_instance = config_class()
                reload_from_document = getattr(config_instance, 'reload_from_document', None)
                if callable(reload_from_document):
                    reload_from_document(document, profile_key)
                self._last_loaded_signatures[config_type] = signature
                reloaded_any_config = True

            return reloaded_any_config
        finally:
            self._sync_in_progress = False

    def refresh_and_sync(self, force: bool = False) -> bool:
        profile_context_changed = self.refresh(force=force)
        reloaded_any_config = self.sync_loaded_configs(force=force)
        return profile_context_changed or reloaded_any_config

    def set_profile_for_current_character(self, config_type: str, profile_name: str) -> bool:
        normalized_config_type = self.normalize_config_type(config_type)
        normalized = self.sanitize_profile_name(profile_name)
        if normalized.upper() == self.SHARED_PROFILE_NAME:
            normalized = self.SHARED_PROFILE_NAME

        if normalized == '' or not self.profile_exists(normalized_config_type, normalized):
            return False

        self._write_selected_profile_name(self._current_character, normalized_config_type, normalized)
        self._active_profile_names[normalized_config_type] = normalized
        return True

    def delete_profile(self, config_type: str, profile_name: str) -> bool:
        normalized_config_type = self.normalize_config_type(config_type)
        normalized_profile_name = self.sanitize_profile_name(profile_name)
        if normalized_profile_name == '' or normalized_profile_name.upper() == self.SHARED_PROFILE_NAME:
            return False

        document = self._profiles_document(normalized_config_type)
        if not document.has(self._profile_path(normalized_profile_name)):
            return False

        if self._active_profile_names.get(normalized_config_type) == normalized_profile_name:
            self._write_selected_profile_name(
                self._current_character,
                normalized_config_type,
                self.SHARED_PROFILE_NAME,
            )
            self._active_profile_names[normalized_config_type] = self.SHARED_PROFILE_NAME

        document.delete(self._profile_path(normalized_profile_name))

        return True

    def create_profile(
        self,
        config_type: str,
        profile_name: str,
        source_profile_name: str | None = None,
        overwrite_existing: bool = False,
    ) -> str | None:
        normalized_config_type = self.normalize_config_type(config_type)
        normalized = self.sanitize_profile_name(profile_name)
        if normalized == '':
            return None

        if normalized.upper() == self.SHARED_PROFILE_NAME:
            return self.SHARED_PROFILE_NAME

        profile_exists = self.profile_exists(normalized_config_type, normalized)
        if profile_exists and not overwrite_existing:
            return normalized

        document = self._profiles_document(normalized_config_type)
        target_path = self._profile_path(normalized)
        if source_profile_name:
            source_profile = self.sanitize_profile_name(source_profile_name)
            if source_profile.upper() == self.SHARED_PROFILE_NAME:
                payload = self._shared_document(normalized_config_type).get_json("config", None)
            else:
                payload = document.get_json(self._profile_path(source_profile), None)
            document.set_json(target_path, payload if payload is not None else {})
        else:
            document.set_json(target_path, {})

        return normalized

    def duplicate_profile(self, config_type: str, source_profile_name: str, target_profile_name: str) -> str | None:
        normalized_config_type = self.normalize_config_type(config_type)
        normalized_source_name = self.sanitize_profile_name(source_profile_name)
        normalized_target_name = self.sanitize_profile_name(target_profile_name)
        if normalized_source_name == '' or normalized_target_name == '':
            return None
        if normalized_target_name.upper() == self.SHARED_PROFILE_NAME:
            return None
        if not self.profile_exists(normalized_config_type, normalized_source_name):
            return None

        if normalized_source_name.upper() == self.SHARED_PROFILE_NAME:
            payload = self._shared_document(normalized_config_type).get_json("config", None)
        else:
            payload = self._profiles_document(normalized_config_type).get_json(
                self._profile_path(normalized_source_name),
                None,
            )

        self._profiles_document(normalized_config_type).set_json(
            self._profile_path(normalized_target_name),
            payload if payload is not None else {},
        )

        return normalized_target_name

    def rename_profile(self, config_type: str, old_profile_name: str, new_profile_name: str) -> str | None:
        normalized_config_type = self.normalize_config_type(config_type)
        normalized_old_name = self.sanitize_profile_name(old_profile_name)
        normalized_new_name = self.sanitize_profile_name(new_profile_name)
        if normalized_old_name == '' or normalized_new_name == '':
            return None
        if normalized_old_name.upper() == self.SHARED_PROFILE_NAME or normalized_new_name.upper() == self.SHARED_PROFILE_NAME:
            return None
        if not self.profile_exists(normalized_config_type, normalized_old_name):
            return None
        if normalized_new_name != normalized_old_name and self.profile_exists(normalized_config_type, normalized_new_name):
            return None

        if normalized_new_name == normalized_old_name:
            return normalized_new_name

        document = self._profiles_document(normalized_config_type)
        payload = document.get_json(self._profile_path(normalized_old_name), None)
        document.set_json(self._profile_path(normalized_new_name), payload if payload is not None else {})
        document.delete(self._profile_path(normalized_old_name))
        self._replace_profile_assignments(normalized_config_type, normalized_old_name, normalized_new_name)

        if self._active_profile_names.get(normalized_config_type) == normalized_old_name:
            self._write_selected_profile_name(self._current_character, normalized_config_type, normalized_new_name)
            self._active_profile_names[normalized_config_type] = normalized_new_name

        return normalized_new_name

    @classmethod
    def broadcast_reload(cls, config_type: str) -> None:
        normalized_config_type = cls.normalize_config_type(config_type)
        reload_type = cls._RELOAD_TYPES_BY_CONFIG_TYPE.get(normalized_config_type)
        current_mail = Player.GetAccountEmail()
        
        if reload_type is None or current_mail == '':
            return


        for acc in GLOBAL_CACHE.ShMem.GetAllAccounts().AccountData:
            if acc.IsAccount and acc.AccountEmail != current_mail:
                GLOBAL_CACHE.ShMem.SendMessage(
                    current_mail,
                    acc.AccountEmail,
                    SharedCommandType.Reload,
                    (reload_type,),
                )

GLOBAL_CONFIG_PROFILE_MANAGER = GlobalConfigProfileManager()
