from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from Py4GWCoreLib.enums_src.Item_enums import ItemType


_CORE_CATALOG_MODULE_NAME = 'Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters.catalog'

try:
    from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters import catalog as _core_catalog_module
except ModuleNotFoundError as exc:
    if exc.name != 'Py4GWCoreLib.py4gwcorelib_src.system_settings':
        raise

    # The ignored offline harness supplies a stub CoreLib package without the real package path.
    # Production imports always take the normal package path above.
    import importlib.util
    import sys

    _CORE_CATALOG_PATH = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__),
            '..',
            '..',
            '..',
            'Py4GWCoreLib',
            'py4gwcorelib_src',
            'system_settings',
            'loot_filters',
            'catalog.py',
        )
    )
    _core_catalog_spec = importlib.util.spec_from_file_location(_CORE_CATALOG_MODULE_NAME, _CORE_CATALOG_PATH)
    if _core_catalog_spec is None or _core_catalog_spec.loader is None:
        raise ImportError(f'Could not load CoreLib catalog module: {_CORE_CATALOG_PATH}')
    _core_catalog_module = importlib.util.module_from_spec(_core_catalog_spec)
    sys.modules[_CORE_CATALOG_MODULE_NAME] = _core_catalog_module
    _core_catalog_spec.loader.exec_module(_core_catalog_module)

CoreCatalogLoadResult: type[Any] = cast(type[Any], _core_catalog_module.CatalogLoadResult)
CoreCatalogLoader: type[Any] = cast(type[Any], _core_catalog_module.CatalogLoader)
_core_dedupe_model_ids = _core_catalog_module._dedupe_model_ids
_core_build_catalog_alias_labels = _core_catalog_module._build_catalog_alias_labels
_core_get_rune_kind_label = _core_catalog_module._get_rune_kind_label
_core_get_rune_kind_sort_key = _core_catalog_module._get_rune_kind_sort_key
_core_get_rune_modifier_value = _core_catalog_module._get_rune_modifier_value
_core_get_rune_profession_label = _core_catalog_module._get_rune_profession_label
_core_get_rune_rarity_sort_key = _core_catalog_module._get_rune_rarity_sort_key
_core_humanize_model_id_enum_name = _core_catalog_module._humanize_model_id_enum_name
_core_infer_model_id_fallback_item_type = _core_catalog_module._infer_model_id_fallback_item_type
_core_iter_item_handling_catalog_entries = _core_catalog_module._iter_item_handling_catalog_entries
_core_iter_model_id_members = _core_catalog_module._iter_model_id_members
_core_normalize_catalog_search_text = _core_catalog_module._normalize_catalog_search_text
_core_normalize_catalog_rune_identifier = _core_catalog_module._normalize_catalog_rune_identifier
_core_normalize_rune_catalog_profession = _core_catalog_module._normalize_rune_catalog_profession
_core_resolve_model_id_value = _core_catalog_module._resolve_model_id_value
_core_resolve_rune_description_template = _core_catalog_module._resolve_rune_description_template
_core_safe_int = _core_catalog_module._safe_int
_core_model_id_fallback_item_type_suffixes = _core_catalog_module.MODEL_ID_FALLBACK_ITEM_TYPE_SUFFIXES


WEAPON_MOD_CHOICE_KIND_GENERIC = 'generic'
WEAPON_MOD_CHOICE_KIND_VARIANT = 'variant'
WEAPON_MOD_GENERIC_KEY_PREFIX = 'identifier:'
WEAPON_MOD_VARIANT_KEY_PREFIX = 'variant:'
WEAPON_MOD_CHOICE_SEPARATOR = '|'

_safe_int = _core_safe_int


_dedupe_model_ids = _core_dedupe_model_ids


_normalize_catalog_search_text = _core_normalize_catalog_search_text


_build_catalog_alias_labels = _core_build_catalog_alias_labels
_iter_item_handling_catalog_entries = _core_iter_item_handling_catalog_entries
_resolve_rune_description_template = _core_resolve_rune_description_template
_humanize_model_id_enum_name = _core_humanize_model_id_enum_name
_iter_model_id_members = _core_iter_model_id_members
_get_rune_modifier_value = _core_get_rune_modifier_value
_infer_model_id_fallback_item_type = _core_infer_model_id_fallback_item_type
_resolve_model_id_value = _core_resolve_model_id_value


MODEL_ID_FALLBACK_ITEM_TYPE_SUFFIXES = _core_model_id_fallback_item_type_suffixes
MODIFIER_IDENTIFIER_RUNE_ATTRIBUTE = _core_catalog_module.RUNE_ATTRIBUTE_MODIFIER_IDENTIFIER


def _get_mirrored_item_priority(item_type: object) -> int:
    normalized_type = str(item_type or '').strip().lower()
    if normalized_type in {
        'axe',
        'bow',
        'daggers',
        'hammer',
        'offhand',
        'scythe',
        'shield',
        'spear',
        'staff',
        'sword',
        'wand',
        'headpiece',
        'chestpiece',
        'gloves',
        'leggings',
        'boots',
    }:
        return 10
    if normalized_type in {'rune_mod', 'salvage'}:
        return 20
    return 30


def _get_catalog_entry_priority(
    model_id: object,
    item_type: object,
    category: object = '',
    sub_category: object = '',
    *,
    scroll_trader_stock_model_ids: frozenset[int] = frozenset(),
) -> int:
    priority = _get_mirrored_item_priority(item_type)
    if max(0, _safe_int(model_id, 0)) not in scroll_trader_stock_model_ids:
        return priority

    normalized_type = _normalize_catalog_search_text(item_type)
    normalized_category = _normalize_catalog_search_text(category)
    normalized_sub_category = _normalize_catalog_search_text(sub_category)
    if (
        normalized_type == 'scroll'
        or normalized_category == 'scroll'
        or normalized_sub_category.endswith('scroll')
    ):
        return min(priority, 15)
    return priority


def _normalize_weapon_mod_target_item_type(raw_value: object) -> str:
    if raw_value is None:
        return ''
    enum_name = str(getattr(raw_value, 'name', '') or '').strip()
    if enum_name:
        return enum_name
    if isinstance(raw_value, str):
        candidate = raw_value.strip()
        if not candidate:
            return ''
        if candidate in getattr(ItemType, '__members__', {}):
            return candidate
        try:
            return ItemType(int(candidate, 0)).name
        except Exception:
            return candidate
    try:
        return ItemType(int(cast(Any, raw_value))).name
    except Exception:
        return str(raw_value or '').strip()


def _normalize_weapon_mod_component_kind(raw_value: object) -> str:
    return str(raw_value or '').strip()


def _normalize_weapon_mod_variant_parts(
    identifier: object,
    target_item_type: object,
    component_kind: object,
) -> tuple[str, str, str]:
    return (
        str(identifier or '').strip(),
        _normalize_weapon_mod_target_item_type(target_item_type),
        _normalize_weapon_mod_component_kind(component_kind),
    )


def _make_weapon_mod_identifier_choice_key(identifier: object) -> str:
    safe_identifier = str(identifier or '').strip()
    return f'{WEAPON_MOD_GENERIC_KEY_PREFIX}{safe_identifier}' if safe_identifier else ''


def _make_weapon_mod_variant_choice_key(
    identifier: object,
    target_item_type: object,
    component_kind: object,
) -> str:
    safe_identifier, safe_target_item_type, safe_component_kind = _normalize_weapon_mod_variant_parts(
        identifier,
        target_item_type,
        component_kind,
    )
    if not safe_identifier or not safe_target_item_type or not safe_component_kind:
        return ''
    return (
        f'{WEAPON_MOD_VARIANT_KEY_PREFIX}{safe_identifier}'
        f'{WEAPON_MOD_CHOICE_SEPARATOR}{safe_target_item_type}'
        f'{WEAPON_MOD_CHOICE_SEPARATOR}{safe_component_kind}'
    )


def _humanize_weapon_mod_component_kind(component_kind: object) -> str:
    safe_component_kind = _normalize_weapon_mod_component_kind(component_kind)
    if not safe_component_kind:
        return ''
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', safe_component_kind).strip()


def _get_weapon_mod_type_name(weapon_mod: object) -> str:
    mod_type = getattr(weapon_mod, 'mod_type', None)
    return str(getattr(mod_type, 'name', mod_type) or '').strip()


def _is_expandable_weapon_mod_type(weapon_mod: object) -> bool:
    return _get_weapon_mod_type_name(weapon_mod) in ('Prefix', 'Suffix')


def _format_weapon_mod_variant_label(weapon_mod: object, component_kind: object) -> str:
    base_name = str(getattr(weapon_mod, 'name', '') or getattr(weapon_mod, 'identifier', '') or '').strip()
    component_label = _humanize_weapon_mod_component_kind(component_kind)
    if not base_name:
        base_name = 'Unknown Weapon Mod'
    if not component_label:
        return base_name
    mod_type_name = _get_weapon_mod_type_name(weapon_mod)
    if mod_type_name == 'Prefix':
        return f'{base_name} {component_label}'
    if mod_type_name == 'Suffix':
        return f'{component_label} {base_name}'
    return base_name


_normalize_rune_catalog_profession = _core_normalize_rune_catalog_profession
_normalize_catalog_rune_identifier = _core_normalize_catalog_rune_identifier


_get_rune_profession_label = _core_get_rune_profession_label
_get_rune_kind_label = _core_get_rune_kind_label
_get_rune_kind_sort_key = _core_get_rune_kind_sort_key
_resolve_rune_description_template = _core_resolve_rune_description_template
_get_rune_rarity_sort_key = _core_get_rune_rarity_sort_key


@dataclass
class CatalogLoadResult(CoreCatalogLoadResult):
    catalog_common_material_ids: list[int] = field(default_factory=list)
    catalog_merchant_essentials: list[dict[str, object]] = field(default_factory=list)
    catalog_rare_materials: list[dict[str, object]] = field(default_factory=list)
    catalog_stats: dict[str, int | bool] = field(default_factory=dict)
    catalog_load_error: str = ''
    weapon_mod_entries: list[dict[str, str]] = field(default_factory=list)
    rune_entries: list[dict[str, str]] = field(default_factory=list)
    armor_upgrade_entries: list[dict[str, str]] = field(default_factory=list)
    weapon_mod_names: dict[str, str] = field(default_factory=dict)
    weapon_mod_generic_names: dict[str, str] = field(default_factory=dict)
    weapon_mod_variant_names: dict[str, str] = field(default_factory=dict)
    rune_names: dict[str, str] = field(default_factory=dict)
    rune_buy_entries: list[dict[str, object]] = field(default_factory=list)
    rune_buy_entries_by_identifier: dict[str, dict[str, object]] = field(default_factory=dict)
    rune_buy_identifier_by_exact_label: dict[str, str] = field(default_factory=dict)
    rune_buy_entries_by_profession: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    rune_buy_professions: list[str] = field(default_factory=list)


class MerchantRulesCatalogLoader:
    def __init__(
        self,
        *,
        catalog_path: str,
        drop_data_path: str,
        item_handling_path: str,
        runes_catalog_path: str,
        mod_db: object,
        mod_db_load_error: str,
        model_id_members: Callable[[], list[tuple[str, int]]],
        armor_upgrade_identity: Callable[[object], tuple[object | None, str]],
        scroll_trader_stock_model_ids: frozenset[int],
    ) -> None:
        self.catalog_path = str(catalog_path)
        self.drop_data_path = str(drop_data_path)
        self.item_handling_path = str(item_handling_path)
        self.runes_catalog_path = str(runes_catalog_path)
        self.mod_db = mod_db
        self.mod_db_load_error = str(mod_db_load_error or '')
        self.model_id_members = model_id_members
        self.armor_upgrade_identity = armor_upgrade_identity
        self.scroll_trader_stock_model_ids = frozenset(scroll_trader_stock_model_ids)
        self._core_loader = CoreCatalogLoader(
            item_priority_resolver=lambda model_id, item_type, category, sub_category: _get_catalog_entry_priority(
                model_id,
                item_type,
                category,
                sub_category,
                scroll_trader_stock_model_ids=self.scroll_trader_stock_model_ids,
            )
        )

    def load(self) -> CatalogLoadResult:
        result = CatalogLoadResult()
        load_errors: list[str] = []
        common_entries: list[dict[str, object]] = []
        rare_entries: list[dict[str, object]] = []
        merchant_entries: list[dict[str, object]] = []
        item_handling_items_count = 0
        rune_model_catalog_count = 0
        drop_data_count = 0
        model_id_fallback_count = 0
        item_handling_present = os.path.exists(self.item_handling_path)

        try:
            with open(self.catalog_path, 'r', encoding='utf-8') as file:
                raw_catalog = json.load(file)

            materials = raw_catalog.get('materials', {})
            merchant_items = raw_catalog.get('merchant_items', {})

            common_entries = self._load_catalog_group(
                result,
                entries=list(materials.get('common', [])),
                source='merchant_rules_catalog.common',
                priority=0,
                default_item_type='material',
                default_material_type='common',
            )
            rare_entries = self._load_catalog_group(
                result,
                entries=list(materials.get('rare', [])),
                source='merchant_rules_catalog.rare',
                priority=0,
                default_item_type='material',
                default_material_type='rare',
            )
            merchant_entries = self._load_catalog_group(
                result,
                entries=list(merchant_items.get('essentials', [])),
                source='merchant_rules_catalog.essentials',
                priority=0,
            )

            result.catalog_common_material_ids = _dedupe_model_ids(
                [int(cast(Any, entry['model_id'])) for entry in common_entries]
            )
            result.catalog_rare_materials = rare_entries
            result.catalog_merchant_essentials = merchant_entries
        except Exception as exc:
            load_errors.append(f'Catalog load failed: {exc}')

        try:
            item_handling_items_count = self._load_item_handling_catalog(result)
        except Exception as exc:
            load_errors.append(f'ItemHandling item catalog load failed: {exc}')

        try:
            drop_data_count = self._load_drop_data_catalog(result)
        except Exception as exc:
            load_errors.append(f'Drop-data name load failed: {exc}')

        try:
            self._load_modifier_catalogs(result)
        except Exception as exc:
            load_errors.append(f'Modifier data load failed: {exc}')

        try:
            self._load_rune_buy_catalog(result)
        except Exception as exc:
            load_errors.append(f'Rune buy catalog load failed: {exc}')

        try:
            rune_model_catalog_count = self._load_rune_model_catalog(result)
        except Exception as exc:
            load_errors.append(f'Rune model catalog load failed: {exc}')

        if self.mod_db_load_error:
            load_errors.append(self.mod_db_load_error)

        try:
            model_id_fallback_count = self._load_model_id_fallback_catalog(result)
        except Exception as exc:
            load_errors.append(f'ModelID fallback catalog load failed: {exc}')

        self._rebuild_catalog_alias_index(result)
        result.catalog_stats = {
            'curated_common': len(common_entries),
            'curated_rare': len(rare_entries),
            'curated_essentials': len(merchant_entries),
            'curated_total': len(common_entries) + len(rare_entries) + len(merchant_entries),
            'item_handling_present': item_handling_present,
            'item_handling_items': item_handling_items_count,
            'rune_models': rune_model_catalog_count,
            'drop_data': drop_data_count,
            'modelid_fallback_items': model_id_fallback_count,
            'final_models': len(result.catalog_by_model_id),
            'alias_groups': self._get_catalog_alias_group_count(result),
        }
        if load_errors:
            result.catalog_load_error = ' | '.join(load_errors)
        return result

    def load_catalog_group(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
        entries: list[dict[str, object]],
        source: str,
        priority: int,
        default_item_type: str = '',
        default_material_type: str = '',
    ) -> list[dict[str, object]]:
        result = CatalogLoadResult(catalog_by_model_id=catalog_by_model_id)
        return self._load_catalog_group(
            result,
            entries,
            source,
            priority,
            default_item_type,
            default_material_type,
        )

    def load_drop_data_catalog(self, catalog_by_model_id: dict[int, dict[str, object]]) -> int:
        return self._load_drop_data_catalog(CatalogLoadResult(catalog_by_model_id=catalog_by_model_id))

    def load_item_handling_catalog(self, catalog_by_model_id: dict[int, dict[str, object]]) -> int:
        return self._load_item_handling_catalog(CatalogLoadResult(catalog_by_model_id=catalog_by_model_id))

    def load_rune_model_catalog(self, catalog_by_model_id: dict[int, dict[str, object]]) -> int:
        return self._load_rune_model_catalog(CatalogLoadResult(catalog_by_model_id=catalog_by_model_id))

    def load_model_id_fallback_catalog(self, catalog_by_model_id: dict[int, dict[str, object]]) -> int:
        return self._load_model_id_fallback_catalog(CatalogLoadResult(catalog_by_model_id=catalog_by_model_id))

    def rebuild_catalog_alias_index(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
    ) -> tuple[dict[str, list[int]], dict[str, str]]:
        result = CatalogLoadResult(catalog_by_model_id=catalog_by_model_id)
        self._rebuild_catalog_alias_index(result)
        return result.catalog_alias_to_model_ids, result.catalog_alias_display_names

    def load_modifier_catalogs(self) -> CatalogLoadResult:
        result = CatalogLoadResult()
        self._load_modifier_catalogs(result)
        return result

    def load_rune_buy_catalog(self) -> CatalogLoadResult:
        result = CatalogLoadResult()
        self._load_rune_buy_catalog(result)
        return result

    @staticmethod
    def _register_catalog_entry(
        result: CatalogLoadResult,
        model_id: int,
        name: str,
        item_type: str = '',
        material_type: str = '',
        source: str = '',
        priority: int = 100,
        extra: dict[str, object] | None = None,
    ) -> None:
        CoreCatalogLoader.register_catalog_entry(
            result.catalog_by_model_id,
            model_id,
            name,
            item_type,
            material_type,
            source,
            priority,
            extra,
        )

    def _load_catalog_group(
        self,
        result: CatalogLoadResult,
        entries: list[dict[str, object]],
        source: str,
        priority: int,
        default_item_type: str = '',
        default_material_type: str = '',
    ) -> list[dict[str, object]]:
        return self._core_loader.load_catalog_group(
            result.catalog_by_model_id,
            entries,
            source,
            priority,
            default_item_type,
            default_material_type,
        )

    def _load_drop_data_catalog(self, result: CatalogLoadResult) -> int:
        if not os.path.exists(self.drop_data_path):
            return 0

        with open(self.drop_data_path, 'r', encoding='utf-8') as file:
            rows = json.load(file)
        return self._core_loader.load_drop_data_catalog(result.catalog_by_model_id, rows, priority=50)

    def _load_item_handling_catalog(self, result: CatalogLoadResult) -> int:
        if not os.path.exists(self.item_handling_path):
            return 0

        with open(self.item_handling_path, 'r', encoding='utf-8') as file:
            raw_catalog = json.load(file)

        return self._core_loader.load_item_handling_catalog(
            result.catalog_by_model_id,
            raw_catalog,
            priority_resolver=lambda model_id, item_type, category, sub_category: _get_catalog_entry_priority(
                model_id,
                item_type,
                category,
                sub_category,
                scroll_trader_stock_model_ids=self.scroll_trader_stock_model_ids,
            ),
        )

    def _load_rune_model_catalog(self, result: CatalogLoadResult) -> int:
        if not os.path.exists(self.runes_catalog_path):
            return 0

        with open(self.runes_catalog_path, 'r', encoding='utf-8') as file:
            raw_catalog = json.load(file)

        return self._core_loader.load_rune_model_catalog(result.catalog_by_model_id, raw_catalog, priority=18)

    def _load_model_id_fallback_catalog(self, result: CatalogLoadResult) -> int:
        return self._core_loader.load_model_id_fallback_catalog(
            result.catalog_by_model_id,
            self.model_id_members,
            priority=90,
        )

    @staticmethod
    def _rebuild_catalog_alias_index(result: CatalogLoadResult) -> None:
        (
            result.catalog_alias_to_model_ids,
            result.catalog_alias_display_names,
        ) = CoreCatalogLoader.rebuild_catalog_alias_index(result.catalog_by_model_id)

    @staticmethod
    def _get_catalog_alias_group_count(result: CatalogLoadResult) -> int:
        return CoreCatalogLoader.get_catalog_alias_group_count(result.catalog_alias_to_model_ids)

    @staticmethod
    def get_catalog_alias_group_count(alias_to_model_ids: dict[str, list[int]]) -> int:
        return CoreCatalogLoader.get_catalog_alias_group_count(alias_to_model_ids)

    def _load_modifier_catalogs(self, result: CatalogLoadResult) -> None:
        mod_db = cast(Any, self.mod_db)
        for identifier, weapon_mod in sorted(
            mod_db.weapon_mods.items(),
            key=lambda row: row[1].name.lower() or row[0].lower(),
        ):
            display_name = str(weapon_mod.name or identifier).strip()
            safe_identifier = str(identifier)
            generic_label = (
                f'{display_name} (all supported weapons)'
                if _is_expandable_weapon_mod_type(weapon_mod)
                else display_name
            )
            entry = {
                'identifier': _make_weapon_mod_identifier_choice_key(safe_identifier),
                'name': generic_label,
                'base_identifier': safe_identifier,
                'entry_kind': WEAPON_MOD_CHOICE_KIND_GENERIC,
            }
            result.weapon_mod_entries.append(entry)
            result.weapon_mod_names[safe_identifier] = display_name
            result.weapon_mod_generic_names[safe_identifier] = generic_label

            if _is_expandable_weapon_mod_type(weapon_mod):
                for target_item_type, component_kind in getattr(weapon_mod, 'item_mods', {}).items():
                    target_item_type_name = _normalize_weapon_mod_target_item_type(target_item_type)
                    safe_component_kind = _normalize_weapon_mod_component_kind(component_kind)
                    variant_key = _make_weapon_mod_variant_choice_key(
                        safe_identifier,
                        target_item_type_name,
                        safe_component_kind,
                    )
                    if not variant_key:
                        continue
                    variant_label = _format_weapon_mod_variant_label(weapon_mod, safe_component_kind)
                    result.weapon_mod_entries.append(
                        {
                            'identifier': variant_key,
                            'name': variant_label,
                            'base_identifier': safe_identifier,
                            'entry_kind': WEAPON_MOD_CHOICE_KIND_VARIANT,
                            'target_item_type': target_item_type_name,
                            'component_kind': safe_component_kind,
                        }
                    )
                    result.weapon_mod_variant_names[variant_key] = variant_label

        for identifier, rune in sorted(
            mod_db.runes.items(),
            key=lambda row: row[1].name.lower() or row[0].lower(),
        ):
            display_name = str(rune.name or identifier).strip()
            entry = {'identifier': str(identifier), 'name': display_name}
            result.rune_entries.append(entry)
            result.rune_names[str(identifier)] = display_name
            armor_identity, _identity_error = self.armor_upgrade_identity(identifier)
            if armor_identity is not None:
                result.armor_upgrade_entries.append(entry)

    def _load_rune_buy_catalog(self, result: CatalogLoadResult) -> None:
        if not os.path.exists(self.runes_catalog_path):
            raise FileNotFoundError(f'Rune catalog missing: {self.runes_catalog_path}')

        with open(self.runes_catalog_path, 'r', encoding='utf-8') as file:
            raw_catalog = json.load(file)

        if not isinstance(raw_catalog, dict):
            raise ValueError('Rune catalog must be a JSON object.')

        entries: list[dict[str, object]] = []
        for raw_identifier, raw_entry in raw_catalog.items():
            if not isinstance(raw_entry, dict):
                continue
            identifier = _normalize_catalog_rune_identifier(raw_entry.get('Identifier', raw_identifier))
            if not identifier:
                continue
            names = raw_entry.get('Names', {})
            if isinstance(names, dict):
                display_name = str(names.get('English', identifier) or identifier).strip()
            else:
                display_name = identifier
            profession = _normalize_rune_catalog_profession(raw_entry.get('Profession', '_None'))
            rarity = str(raw_entry.get('Rarity', '') or '').strip()
            mod_type = str(raw_entry.get('ModType', '') or '').strip()
            vendor_value = max(0, _safe_int(raw_entry.get('VendorValue', 0), 0))
            descriptions = raw_entry.get('Descriptions', {})
            if isinstance(descriptions, dict):
                english_description = str(descriptions.get('English', '') or '').strip()
            else:
                english_description = ''
            english_description = _resolve_rune_description_template(
                english_description,
                raw_entry.get('Modifiers', []),
            )
            entry = {
                'identifier': identifier,
                'name': display_name,
                'description': english_description,
                'profession': profession,
                'profession_label': _get_rune_profession_label(profession),
                'rarity': rarity,
                'mod_type': mod_type,
                'kind_label': _get_rune_kind_label(mod_type),
                'vendor_value': vendor_value,
            }
            entries.append(entry)

        entries.sort(
            key=lambda entry: (
                str(entry.get('profession_label', '')).lower(),
                _get_rune_kind_sort_key(entry.get('mod_type', '')),
                _get_rune_rarity_sort_key(entry.get('rarity', '')),
                str(entry.get('name', '')).lower(),
                str(entry.get('identifier', '')).lower(),
            )
        )
        grouped_entries: dict[str, list[dict[str, object]]] = {}
        for entry in entries:
            profession = str(entry.get('profession', '_None') or '_None')
            grouped_entries.setdefault(profession, []).append(entry)

        profession_order = sorted(
            grouped_entries.keys(),
            key=lambda profession: (
                0 if profession == '_None' else 1,
                _get_rune_profession_label(profession).lower(),
            ),
        )

        result.rune_buy_entries = entries
        result.rune_buy_entries_by_identifier = {
            str(entry.get('identifier', '')).strip(): entry
            for entry in entries
            if str(entry.get('identifier', '')).strip()
        }
        self._rebuild_rune_exact_display_lookup(result)
        result.rune_buy_entries_by_profession = grouped_entries
        result.rune_buy_professions = profession_order

    @staticmethod
    def _rebuild_rune_exact_display_lookup(result: CatalogLoadResult) -> None:
        identifiers_by_label: dict[str, set[str]] = {}
        for entry in result.rune_buy_entries:
            identifier = str(entry.get('identifier', '') or '').strip()
            if not identifier:
                continue
            for label in (
                str(entry.get('name', '') or '').strip(),
                identifier,
            ):
                normalized_label = _normalize_catalog_search_text(label)
                if normalized_label:
                    identifiers_by_label.setdefault(normalized_label, set()).add(identifier)

        result.rune_buy_identifier_by_exact_label = {
            label: next(iter(identifiers))
            for label, identifiers in identifiers_by_label.items()
            if len(identifiers) == 1
        }


# Compatibility name retained for the widget; the reusable loader itself lives in CoreLib.
CatalogLoader = MerchantRulesCatalogLoader
