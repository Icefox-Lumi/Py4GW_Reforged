from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import cast
from urllib.parse import unquote

from Py4GWCoreLib.enums_src.GameData_enums import Attribute
from Py4GWCoreLib.enums_src.GameData_enums import AttributeNames
from Py4GWCoreLib.enums_src.Item_enums import ItemType
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Sources.marks_sources.mods_parser import ModifierIdentifier as LegacyModifierIdentifier
from Sources.icefox.MerchantRules.catalog_search import RankedCatalogSearch
from Sources.icefox.MerchantRules.configuration import SELL_KIND_ARMOR
from Sources.icefox.MerchantRules.configuration import SELL_KIND_WEAPONS
from Sources.icefox.MerchantRules.configuration import dedupe_model_ids as _session_dedupe_model_ids
from Sources.icefox.MerchantRules.item_values import safe_int as _session_safe_int

# The following helpers build the Merchant Rules runtime index from normalized rows.  The shipped
# ``CATALOG`` above remains the canonical package data; this index is deliberately fed by this
# feature backend and never opens feature-owned JSON files at import time.
MODEL_ID_FALLBACK_ITEM_TYPE_SUFFIXES: tuple[tuple[str, ItemType], ...] = (
    ('Daggers', ItemType.Daggers),
    ('Scythe', ItemType.Scythe),
    ('Shield', ItemType.Shield),
    ('Spear', ItemType.Spear),
    ('Staff', ItemType.Staff),
    ('Sword', ItemType.Sword),
    ('Hammer', ItemType.Hammer),
    ('Focus', ItemType.Offhand),
    ('Offhand', ItemType.Offhand),
    ('Icon', ItemType.Offhand),
    ('Prism', ItemType.Offhand),
    ('Wand', ItemType.Wand),
    ('Bow', ItemType.Bow),
    ('Axe', ItemType.Axe),
    ('Headpiece', ItemType.Headpiece),
    ('Chestpiece', ItemType.Chestpiece),
    ('Gloves', ItemType.Gloves),
    ('Leggings', ItemType.Leggings),
    ('Boots', ItemType.Boots),
    ('SalvageKit', ItemType.Salvage),
)

DEFAULT_CATALOG_ENTRY_PRIORITY: int = 100
RUNE_ATTRIBUTE_MODIFIER_IDENTIFIER: int = int(LegacyModifierIdentifier.RuneAttribute)
_EXACT_NON_RUNTIME_ITEM_TYPES = frozenset(
    {
        ItemType.Weapon,
        ItemType.MartialWeapon,
        ItemType.OffhandOrShield,
        ItemType.EquippableItem,
        ItemType.SpellcastingWeapon,
        ItemType.Unknown,
    }
)


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, str):
            return int(value.strip(), 0)
        return int(cast(Any, value))
    except Exception:
        return default


def _dedupe_model_ids(model_ids: list[int]) -> list[int]:
    unique: list[int] = []
    seen: set[int] = set()
    for value in model_ids:
        model_id = max(0, _safe_int(value, 0))
        if model_id <= 0 or model_id in seen:
            continue
        seen.add(model_id)
        unique.append(model_id)
    return unique


def _resolve_model_id_value(raw_value: object) -> int:
    if isinstance(raw_value, str):
        candidate = raw_value.strip()
        if not candidate:
            return 0
        if candidate.startswith('ModelID.'):
            enum_name = candidate.split('.', 1)[1].strip()
            enum_value = getattr(ModelID, enum_name, None)
            if enum_value is not None:
                try:
                    return int(enum_value.value)
                except Exception:
                    return _safe_int(enum_value, 0)
        return _safe_int(candidate, 0)
    return _safe_int(raw_value, 0)


def _normalize_catalog_search_text(raw_value: object) -> str:
    text = str(raw_value or '').strip().lower()
    if not text:
        return ''
    text = unquote(text)
    text = text.replace('_', ' ')
    text = re.sub(r'\.[a-z0-9]+$', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _strip_catalog_display_markup(raw_value: object) -> str:
    text = str(raw_value or '').strip()
    if not text:
        return ''
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r'<c=@[^>]+>(.*?)</c>', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _normalize_catalog_display_name(raw_value: object, model_id: object = 0) -> str:
    raw_text = str(raw_value or '').strip()
    if not raw_text:
        return ''

    clean_text = _strip_catalog_display_markup(raw_text)
    if clean_text:
        return clean_text

    safe_model_id = max(0, _safe_int(model_id, 0))
    return f'Model {safe_model_id}' if safe_model_id > 0 else ''


def _build_catalog_alias_labels(
    name: object,
    skin: object = '',
    wiki_url: object = '',
    attributes: object = (),
) -> dict[str, str]:
    alias_labels: dict[str, str] = {}

    def _add_alias(raw_alias: object, display_label: object = '') -> None:
        clean_alias = _strip_catalog_display_markup(raw_alias)
        normalized = _normalize_catalog_search_text(clean_alias)
        if not normalized:
            return
        display = _strip_catalog_display_markup(display_label or clean_alias)
        if not display:
            display = normalized.title()
        alias_labels.setdefault(normalized, display)

    safe_name = _normalize_catalog_display_name(name)
    if safe_name:
        _add_alias(safe_name, safe_name)

    safe_skin = str(skin or '').strip()
    if safe_skin:
        skin_label = os.path.splitext(os.path.basename(safe_skin))[0].strip()
        if skin_label:
            _add_alias(skin_label, skin_label)

    safe_wiki_url = str(wiki_url or '').strip()
    if safe_wiki_url:
        wiki_stem = safe_wiki_url.rsplit('/', 1)[-1].split('?', 1)[0].split('#', 1)[0].strip()
        wiki_label = unquote(wiki_stem).replace('_', ' ').strip()
        if wiki_label:
            _add_alias(wiki_label, wiki_label)

    if isinstance(attributes, (list, tuple, set)) and safe_name:
        for raw_attribute in attributes:
            attribute_label = _humanize_model_id_enum_name(raw_attribute)
            if not attribute_label or attribute_label.casefold() == 'none':
                continue
            qualified_label = f'{safe_name} {attribute_label}'
            _add_alias(qualified_label, qualified_label)

    return alias_labels


def _humanize_model_id_enum_name(raw_name: object) -> str:
    text = str(raw_name or '').strip()
    if not text:
        return ''
    text = text.replace('_', ' ')
    text = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', text)
    text = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _iter_model_id_members(model_id_type: object = ModelID) -> list[tuple[str, int]]:
    members = getattr(model_id_type, '__members__', None)
    if isinstance(members, dict):
        raw_members = list(members.items())
    else:
        raw_members = [(name, getattr(model_id_type, name)) for name in dir(model_id_type) if not name.startswith('_')]

    resolved_members: list[tuple[str, int]] = []
    for raw_name, raw_value in raw_members:
        name = str(raw_name or '').strip()
        if not name:
            continue
        try:
            model_id = int(raw_value.value)
        except Exception:
            model_id = _safe_int(raw_value, 0)
        if model_id > 0:
            resolved_members.append((name, model_id))
    return resolved_members


def _infer_model_id_fallback_item_type(enum_names: list[str], display_name: str) -> str:
    candidates = [display_name, *enum_names]
    for candidate in candidates:
        compact = re.sub(r'[^A-Za-z0-9]+', '', str(candidate or ''))
        normalized = _normalize_catalog_search_text(_humanize_model_id_enum_name(candidate))
        tokens = set(normalized.split())
        for suffix, item_type in MODEL_ID_FALLBACK_ITEM_TYPE_SUFFIXES:
            suffix_lower = suffix.lower()
            if compact.lower().endswith(suffix_lower) or suffix_lower in tokens:
                return str(getattr(item_type, 'name', item_type))
    return ''


def _iter_item_handling_catalog_entries(raw_catalog: object) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []

    def _walk(raw_value: object) -> None:
        if isinstance(raw_value, dict):
            if ('model_id' in raw_value or 'ModelID' in raw_value) and ('name' in raw_value or 'Name' in raw_value):
                entries.append(raw_value)
                return
            for child_value in raw_value.values():
                _walk(child_value)
        elif isinstance(raw_value, list):
            for child_value in raw_value:
                _walk(child_value)

    _walk(raw_catalog)
    return entries


def _resolve_item_type_id(raw_value: object) -> int | None:
    """Resolve one current ItemType value without falling back to an untyped model lookup."""

    if isinstance(raw_value, ItemType):
        item_type = raw_value
    elif isinstance(raw_value, str):
        candidate = raw_value.strip()
        if not candidate:
            return None
        if candidate.startswith("ItemType."):
            candidate = candidate.split(".", 1)[1].strip()
        item_type = next(
            (
                enum_value
                for enum_name, enum_value in ItemType.__members__.items()
                if enum_name.casefold() == candidate.casefold()
            ),
            None,
        )
        if item_type is None:
            try:
                item_type = ItemType(int(candidate, 0))
            except (TypeError, ValueError):
                return None
    else:
        try:
            item_type = ItemType(_safe_int(raw_value, -1))
        except ValueError:
            return None

    if item_type == ItemType.Unknown:
        return None
    return int(item_type)


def _get_common_salvage_model_ids(raw_entry: dict[str, object]) -> tuple[int, ...] | None:
    """Read only valid common-salvage output model IDs from one typed ItemHandling row."""

    raw_salvage = raw_entry.get("common_salvage")
    if not isinstance(raw_salvage, dict):
        return None

    output_model_ids: list[int] = []
    for raw_output in raw_salvage.values():
        if not isinstance(raw_output, dict):
            continue
        output_model_id = _resolve_model_id_value(
            raw_output.get("model_id", raw_output.get("ModelID", 0))
        )
        if output_model_id > 0 and output_model_id not in output_model_ids:
            output_model_ids.append(output_model_id)
    if not output_model_ids:
        return None
    return tuple(output_model_ids)


def _get_rune_profession_label(value: object) -> str:
    profession = _normalize_rune_catalog_profession(value)
    return 'Common' if profession == '_None' else profession


def _normalize_rune_catalog_profession(value: object) -> str:
    return str(value or '').strip() or '_None'


def _normalize_catalog_rune_identifier(value: object) -> str:
    return str(value or '').strip()


def _get_rune_kind_label(mod_type: object) -> str:
    return 'Insignia' if str(mod_type or '').strip().lower() == 'prefix' else 'Rune'


def _get_rune_kind_sort_key(mod_type: object) -> int:
    return 0 if _get_rune_kind_label(mod_type) == 'Insignia' else 1


def _get_rune_rarity_sort_key(rarity: object) -> int:
    rarity_order = {'blue': 0, 'purple': 1, 'gold': 2}
    return rarity_order.get(str(rarity or '').strip().lower(), 99)


def _get_rune_modifier_value(modifier: object, field_name: str) -> object:
    if not isinstance(modifier, dict):
        return ''
    normalized_field = str(field_name or '').strip().lower()
    if normalized_field == 'arg1':
        return modifier.get('Arg1', '')
    if normalized_field == 'arg2':
        return modifier.get('Arg2', '')
    if normalized_field == 'arg':
        return modifier.get('Arg', '')
    return ''


def _resolve_rune_description_template(description: str, modifiers: object) -> str:
    safe_description = str(description or '').strip()
    if not safe_description or '{' not in safe_description:
        return safe_description
    if not isinstance(modifiers, list):
        return safe_description

    modifiers_by_identifier: dict[int, dict[str, object]] = {}
    for modifier in modifiers:
        if not isinstance(modifier, dict):
            continue
        modifier_identifier = _safe_int(modifier.get('Identifier', 0), 0)
        if modifier_identifier:
            modifiers_by_identifier[modifier_identifier] = modifier

    def replace_placeholder(match: re.Match) -> str:
        field_name = str(match.group(1) or '')
        modifier_identifier = _safe_int(match.group(2), 0)
        modifier = modifiers_by_identifier.get(modifier_identifier)
        if modifier is None:
            return str(match.group(0))

        value = _get_rune_modifier_value(modifier, field_name)
        if modifier_identifier == RUNE_ATTRIBUTE_MODIFIER_IDENTIFIER and field_name.lower() == 'arg1':
            attribute_id = _safe_int(value, 0)
            try:
                attribute = Attribute(attribute_id)
            except ValueError:
                return f'Attribute {attribute_id}'
            return AttributeNames.get(attribute, f'Attribute {attribute_id}')
        try:
            return str(int(cast(Any, value)))
        except Exception:
            return str(value or match.group(0))

    return re.sub(r'\{(arg1|arg2|arg)\[(\d+)\]\}', replace_placeholder, safe_description)


@dataclass
class _CatalogIndexResult:
    """Merchant Rules catalog index result with feature-specific policy projections."""

    catalog_by_model_id: dict[int, dict[str, object]] = field(default_factory=dict)
    catalog_alias_to_model_ids: dict[str, list[int]] = field(default_factory=dict)
    catalog_alias_display_names: dict[str, str] = field(default_factory=dict)
    exact_catalog_by_item_key: dict[tuple[int, int], dict[str, object]] = field(default_factory=dict)
    exact_catalog_untyped_by_model_id: dict[int, dict[str, object]] = field(default_factory=dict)


class _CatalogIndexLoader:
    """Build a runtime item index from caller-supplied rows.

    This class owns normalization, precedence, aliases, and ModelID fallback only. It deliberately
    has no feature paths, JSON-store access, merchant targets, or modifier database ownership.
    """

    def __init__(
        self,
        *,
        item_priority_resolver: Callable[[object, object, object, object], int] | None = None,
    ) -> None:
        self.item_priority_resolver = item_priority_resolver or (
            lambda _model_id, _item_type, _category, _sub_category: (DEFAULT_CATALOG_ENTRY_PRIORITY)
        )

    @staticmethod
    def register_catalog_entry(
        catalog_by_model_id: dict[int, dict[str, object]],
        model_id: int,
        name: str,
        item_type: str = '',
        material_type: str = '',
        source: str = '',
        priority: int = 100,
        extra: dict[str, object] | None = None,
    ) -> None:
        safe_model_id = max(0, _safe_int(model_id, 0))
        safe_name = _normalize_catalog_display_name(name, safe_model_id)
        if safe_model_id <= 0 or not safe_name:
            return

        current = catalog_by_model_id.get(safe_model_id)
        if current is not None and _safe_int(current.get('priority', 999), 999) <= priority:
            return

        entry: dict[str, object] = {
            'model_id': safe_model_id,
            'name': safe_name,
            'item_type': str(item_type or '').strip(),
            'material_type': str(material_type or '').strip(),
            'source': source,
            'priority': int(priority),
        }
        if extra:
            for key, value in extra.items():
                if value not in (None, ''):
                    entry[key] = value

        catalog_by_model_id[safe_model_id] = entry

    @staticmethod
    def register_exact_catalog_entry(
        exact_catalog_by_item_key: dict[tuple[int, int], dict[str, object]],
        item_type_id: int,
        model_id: int,
        name: str,
        item_type: str = '',
        material_type: str = '',
        source: str = '',
        priority: int = 100,
        extra: dict[str, object] | None = None,
    ) -> None:
        safe_item_type_id = _safe_int(item_type_id, -1)
        safe_model_id = max(0, _safe_int(model_id, 0))
        safe_name = _normalize_catalog_display_name(name, safe_model_id)
        if safe_item_type_id < 0 or safe_model_id <= 0 or not safe_name:
            return
        try:
            if ItemType(safe_item_type_id) in _EXACT_NON_RUNTIME_ITEM_TYPES:
                return
        except ValueError:
            return

        item_key = (safe_item_type_id, safe_model_id)
        current = exact_catalog_by_item_key.get(item_key)
        if current is not None and _safe_int(current.get('priority', 999), 999) <= priority:
            return

        entry: dict[str, object] = {
            'item_type_id': safe_item_type_id,
            'model_id': safe_model_id,
            'name': safe_name,
            'item_type': str(item_type or '').strip(),
            'material_type': str(material_type or '').strip(),
            'source': source,
            'priority': int(priority),
        }
        if extra:
            for key, value in extra.items():
                if value not in (None, ''):
                    entry[key] = value

        exact_catalog_by_item_key[item_key] = entry

    def load_catalog_group(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
        entries: list[dict[str, object]],
        source: str,
        priority: int,
        default_item_type: str = '',
        default_material_type: str = '',
    ) -> list[dict[str, object]]:
        loaded_entries: list[dict[str, object]] = []
        for entry in entries:
            model_id = max(0, _safe_int(entry.get('model_id', 0), 0))
            if model_id <= 0:
                continue

            name = _normalize_catalog_display_name(
                entry.get('name', '') or f'Model {model_id}',
                model_id,
            ) or f'Model {model_id}'
            loaded_entry = {
                'model_id': model_id,
                'name': name,
                'item_type': str(entry.get('item_type', default_item_type) or default_item_type),
                'material_type': str(entry.get('material_type', default_material_type) or default_material_type),
            }
            if 'default_target' in entry:
                loaded_entry['default_target'] = max(0, _safe_int(entry.get('default_target', 0), 0))

            self.register_catalog_entry(
                catalog_by_model_id,
                model_id=model_id,
                name=str(loaded_entry['name']),
                item_type=str(loaded_entry['item_type']),
                material_type=str(loaded_entry['material_type']),
                source=source,
                priority=priority,
                extra={'default_target': loaded_entry.get('default_target', 0)},
            )
            loaded_entries.append(loaded_entry)
        return loaded_entries

    def load_drop_data_catalog(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
        rows: object,
        *,
        source: str = 'modelid_drop_data',
        priority: int = DEFAULT_CATALOG_ENTRY_PRIORITY,
    ) -> int:
        loaded_count = 0
        if not isinstance(rows, list):
            return loaded_count
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = _resolve_model_id_value(row.get('model_id', 0))
            name = _normalize_catalog_display_name(row.get('name', ''), model_id)
            if model_id <= 0 or not name:
                continue
            self.register_catalog_entry(
                catalog_by_model_id,
                model_id=model_id,
                name=name,
                item_type=str(row.get('group', '')).strip(),
                material_type=str(row.get('subgroup', '')).strip(),
                source=source,
                priority=priority,
            )
            loaded_count += 1
        return loaded_count

    def load_item_handling_catalog(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
        raw_catalog: object,
        *,
        priority_resolver: Callable[[object, object, object, object], int] | None = None,
        source: str = 'item_handling_items_catalog',
        common_salvage_model_ids_by_item_key: dict[tuple[int, int], tuple[int, ...]] | None = None,
        common_salvage_ambiguous_item_keys: set[tuple[int, int]] | None = None,
        exact_catalog_by_item_key: dict[tuple[int, int], dict[str, object]] | None = None,
    ) -> int:
        loaded_count = 0
        resolve_priority = priority_resolver or self.item_priority_resolver
        for entry in _iter_item_handling_catalog_entries(raw_catalog):
            model_id = _resolve_model_id_value(entry.get('model_id', entry.get('ModelID', 0)))
            name = _normalize_catalog_display_name(
                entry.get('name') or entry.get('Name') or '',
                model_id,
            )
            if model_id <= 0 or not name:
                continue

            item_type = str(entry.get('item_type') or entry.get('ItemType') or '').strip()
            skin = str(entry.get('skin') or entry.get('Skin') or '').strip()
            wiki_url = str(entry.get('wiki_url') or entry.get('WikiURL') or '').strip()
            category = str(entry.get('category') or '').strip()
            sub_category = str(entry.get('sub_category') or '').strip()
            raw_attributes = entry.get('attributes', [])
            attributes = (
                [str(attribute).strip() for attribute in raw_attributes if str(attribute or '').strip()]
                if isinstance(raw_attributes, list)
                else []
            )

            if common_salvage_model_ids_by_item_key is not None:
                item_type_id = _resolve_item_type_id(item_type)
                common_salvage_model_ids = _get_common_salvage_model_ids(entry)
                if item_type_id is not None and common_salvage_model_ids:
                    item_key = (int(item_type_id), int(model_id))
                    if common_salvage_ambiguous_item_keys is None or item_key not in common_salvage_ambiguous_item_keys:
                        existing_outputs = common_salvage_model_ids_by_item_key.get(item_key)
                        if existing_outputs is None:
                            common_salvage_model_ids_by_item_key[item_key] = common_salvage_model_ids
                        elif existing_outputs != common_salvage_model_ids:
                            common_salvage_model_ids_by_item_key.pop(item_key, None)
                            if common_salvage_ambiguous_item_keys is not None:
                                common_salvage_ambiguous_item_keys.add(item_key)

            extra: dict[str, object] = {
                'alias_labels': _build_catalog_alias_labels(name, skin, wiki_url, attributes),
                'attributes': attributes,
            }
            if skin:
                extra['skin'] = skin
            if wiki_url:
                extra['wiki_url'] = wiki_url
            if category:
                extra['category'] = category
            if sub_category:
                extra['sub_category'] = sub_category

            self.register_catalog_entry(
                catalog_by_model_id,
                model_id=model_id,
                name=name,
                item_type=item_type,
                source=source,
                priority=resolve_priority(model_id, item_type, category, sub_category),
                extra=extra,
            )
            if exact_catalog_by_item_key is not None:
                item_type_id = _resolve_item_type_id(item_type)
                if item_type_id is not None:
                    exact_extra = dict(extra)
                    exact_extra['item_type_id'] = int(item_type_id)
                    self.register_exact_catalog_entry(
                        exact_catalog_by_item_key,
                        item_type_id=int(item_type_id),
                        model_id=model_id,
                        name=name,
                        item_type=item_type,
                        material_type=str(entry.get('material_type') or '').strip(),
                        source=source,
                        priority=resolve_priority(model_id, item_type, category, sub_category),
                        extra=exact_extra,
                    )
            loaded_count += 1
        return loaded_count

    def load_rune_model_catalog(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
        raw_catalog: object,
        *,
        source: str = 'runes_catalog',
        priority: int = DEFAULT_CATALOG_ENTRY_PRIORITY,
        exact_catalog_by_item_key: dict[tuple[int, int], dict[str, object]] | None = None,
    ) -> int:
        if not isinstance(raw_catalog, dict):
            return 0

        grouped_entries: dict[int, tuple[set[str], set[str], set[str]]] = {}
        for raw_identifier, raw_entry in raw_catalog.items():
            if not isinstance(raw_entry, dict):
                continue
            model_id = max(0, _safe_int(raw_entry.get('ModelId', 0), 0))
            if model_id <= 0:
                continue

            names = raw_entry.get('Names', {})
            raw_display_name = names.get('English', '') if isinstance(names, dict) else ''
            display_name = _normalize_catalog_display_name(raw_display_name, model_id)
            if not display_name:
                display_name = _normalize_catalog_display_name(
                    raw_entry.get('Identifier', raw_identifier),
                    model_id,
                )
            if not display_name:
                continue

            identifier = str(raw_entry.get('Identifier', raw_identifier) or raw_identifier).strip()
            mod_type = str(raw_entry.get('ModType', '') or '').strip()
            normalized_name = _normalize_catalog_search_text(display_name)
            if mod_type == 'Prefix' or 'insignia' in normalized_name:
                kind = 'insignia'
            elif mod_type == 'Suffix' or 'rune' in normalized_name:
                kind = 'rune'
            else:
                kind = ''

            names_for_model, kinds_for_model, identifiers_for_model = grouped_entries.setdefault(
                model_id,
                (set(), set(), set()),
            )
            names_for_model.add(display_name)
            if kind:
                kinds_for_model.add(kind)
            if identifier:
                identifiers_for_model.add(identifier)

        loaded_count = 0
        for model_id, (names_for_model, kinds_for_model, identifiers_for_model) in grouped_entries.items():
            names = sorted(str(name) for name in names_for_model if str(name or '').strip())
            kinds = sorted(str(kind) for kind in kinds_for_model if str(kind or '').strip())
            if not names:
                continue

            if len(names) == 1:
                display_name = names[0]
            elif kinds == ['insignia']:
                display_name = 'Insignia'
            elif kinds == ['rune']:
                display_name = 'Rune'
            else:
                display_name = 'Rune / Insignia'

            alias_labels = _build_catalog_alias_labels(display_name)
            for name in names:
                alias_labels.update(_build_catalog_alias_labels(name))

            extra: dict[str, object] = {
                'alias_labels': alias_labels,
                'rune_model_kinds': kinds,
                'rune_model_names': names,
            }
            current = catalog_by_model_id.get(model_id)
            if current is None:
                self.register_catalog_entry(
                    catalog_by_model_id,
                    model_id=model_id,
                    name=display_name,
                    item_type='Rune_Mod',
                    source=source,
                    priority=priority,
                    extra=extra,
                )
            else:
                if not str(current.get('item_type', '') or '').strip():
                    current['item_type'] = 'Rune_Mod'
                current_kinds = [
                    str(kind)
                    for kind in cast(list[object], current.get('rune_model_kinds', []))
                    if str(kind or '').strip()
                ]
                merged_kinds = sorted(set(current_kinds) | set(kinds))
                if merged_kinds:
                    current['rune_model_kinds'] = merged_kinds

                current_names = [
                    str(name)
                    for name in cast(list[object], current.get('rune_model_names', []))
                    if str(name or '').strip()
                ]
                merged_names = sorted(set(current_names) | set(names))
                if merged_names:
                    current['rune_model_names'] = merged_names

                current_name = _normalize_catalog_search_text(current.get('name', ''))
                current_item_type = _normalize_catalog_search_text(current.get('item_type', ''))
                rich_name = merged_names[0] if len(merged_names) == 1 else ''
                normalized_rich_name = _normalize_catalog_search_text(rich_name)
                rich_kind = merged_kinds[0] if len(merged_kinds) == 1 else ''
                if (
                    current_name in {'rune', 'insignia'}
                    and current_item_type == 'rune mod'
                    and rich_name
                    and normalized_rich_name not in {'rune', 'insignia'}
                    and rich_kind in normalized_rich_name.split()
                    and len(identifiers_for_model) == 1
                ):
                    # Keep the ItemHandling record and provenance, but use an unambiguous
                    # rich rune/insignia name as the shared Merchant Rules display label.
                    current['name'] = _normalize_catalog_display_name(rich_name, model_id) or current.get('name', '')

                current_alias_labels = current.get('alias_labels', {})
                if not isinstance(current_alias_labels, dict):
                    current_alias_labels = {}
                current_alias_labels.update(alias_labels)
                current['alias_labels'] = current_alias_labels
            if exact_catalog_by_item_key is not None:
                typed_entry = exact_catalog_by_item_key.get((int(ItemType.Rune_Mod), model_id))
                if typed_entry is not None:
                    self._merge_rune_catalog_metadata(
                        typed_entry,
                        names=names,
                        kinds=kinds,
                        identifiers=identifiers_for_model,
                    )
            loaded_count += 1

        return loaded_count

    @staticmethod
    def _merge_rune_catalog_metadata(
        entry: dict[str, object],
        *,
        names: list[str],
        kinds: list[str],
        identifiers: set[str],
    ) -> None:
        current_kinds = [
            str(kind)
            for kind in cast(list[object], entry.get('rune_model_kinds', []))
            if str(kind or '').strip()
        ]
        merged_kinds = sorted(set(current_kinds) | set(kinds))
        if merged_kinds:
            entry['rune_model_kinds'] = merged_kinds

        current_names = [
            str(name)
            for name in cast(list[object], entry.get('rune_model_names', []))
            if str(name or '').strip()
        ]
        merged_names = sorted(set(current_names) | set(names))
        if merged_names:
            entry['rune_model_names'] = merged_names

        alias_labels = entry.get('alias_labels', {})
        if not isinstance(alias_labels, dict):
            alias_labels = {}
        for name in names:
            alias_labels.update(_build_catalog_alias_labels(name))
        entry['alias_labels'] = alias_labels

        current_name = _normalize_catalog_search_text(entry.get('name', ''))
        current_item_type = _normalize_catalog_search_text(entry.get('item_type', ''))
        rich_name = names[0] if len(names) == 1 else ''
        normalized_rich_name = _normalize_catalog_search_text(rich_name)
        rich_kind = kinds[0] if len(kinds) == 1 else ''
        if (
            current_name in {'rune', 'insignia'}
            and current_item_type == 'rune mod'
            and rich_name
            and normalized_rich_name not in {'rune', 'insignia'}
            and rich_kind in normalized_rich_name.split()
            and len(identifiers) == 1
        ):
            entry['name'] = _normalize_catalog_display_name(rich_name, entry.get('model_id', 0)) or entry.get('name', '')

    def load_model_id_fallback_catalog(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
        model_id_members: Callable[[], list[tuple[str, int]]] | list[tuple[str, int]],
        *,
        source: str = 'modelid_enum_fallback',
        priority: int = DEFAULT_CATALOG_ENTRY_PRIORITY,
    ) -> int:
        enum_names_by_model_id: dict[int, list[str]] = {}
        members = model_id_members() if callable(model_id_members) else model_id_members
        for enum_name, model_id in members:
            if model_id <= 0:
                continue
            names = enum_names_by_model_id.setdefault(model_id, [])
            if enum_name not in names:
                names.append(enum_name)

        loaded_count = 0
        for model_id, enum_names in enum_names_by_model_id.items():
            if model_id in catalog_by_model_id or not enum_names:
                continue

            display_name = _humanize_model_id_enum_name(enum_names[0]) or f'Model {model_id}'
            alias_labels = _build_catalog_alias_labels(display_name)
            for enum_name in enum_names:
                raw_name = str(enum_name or '').strip()
                if not raw_name:
                    continue
                alias_labels.setdefault(_normalize_catalog_search_text(raw_name), raw_name)
                humanized_name = _humanize_model_id_enum_name(raw_name)
                if humanized_name:
                    alias_labels.setdefault(_normalize_catalog_search_text(humanized_name), humanized_name)

            self.register_catalog_entry(
                catalog_by_model_id,
                model_id=model_id,
                name=display_name,
                item_type=_infer_model_id_fallback_item_type(enum_names, display_name),
                source=source,
                priority=priority,
                extra={'alias_labels': alias_labels, 'enum_names': list(enum_names)},
            )
            loaded_count += 1
        return loaded_count

    @staticmethod
    def rebuild_catalog_alias_index(
        catalog_by_model_id: dict[int, dict[str, object]],
    ) -> tuple[dict[str, list[int]], dict[str, str]]:
        alias_to_model_ids: dict[str, list[int]] = {}
        alias_display_names: dict[str, str] = {}

        for model_id, entry in catalog_by_model_id.items():
            alias_labels = entry.get('alias_labels', {})
            normalized_alias_labels: dict[str, str] = {}
            if isinstance(alias_labels, dict):
                for raw_alias, display_name in alias_labels.items():
                    normalized_alias = _normalize_catalog_search_text(_strip_catalog_display_markup(raw_alias))
                    if normalized_alias:
                        clean_display_name = _strip_catalog_display_markup(display_name)
                        normalized_alias_labels[normalized_alias] = (
                            clean_display_name or normalized_alias.title()
                        )

            name = _normalize_catalog_display_name(entry.get('name', ''), model_id)
            if name:
                entry['name'] = name
            normalized_name = _normalize_catalog_search_text(name)
            if normalized_name and normalized_name not in normalized_alias_labels:
                normalized_alias_labels[normalized_name] = name

            entry['alias_labels'] = normalized_alias_labels
            for normalized_alias, display_name in normalized_alias_labels.items():
                alias_model_ids = alias_to_model_ids.setdefault(normalized_alias, [])
                if model_id not in alias_model_ids:
                    alias_model_ids.append(model_id)
                alias_display_names.setdefault(normalized_alias, display_name)

        return alias_to_model_ids, alias_display_names

    @staticmethod
    def get_catalog_alias_group_count(alias_to_model_ids: dict[str, list[int]]) -> int:
        return sum(1 for model_ids in alias_to_model_ids.values() if len(model_ids) > 1)


WEAPON_MOD_CHOICE_KIND_GENERIC = 'generic'
WEAPON_MOD_CHOICE_KIND_VARIANT = 'variant'
WEAPON_MOD_GENERIC_KEY_PREFIX = 'identifier:'
WEAPON_MOD_VARIANT_KEY_PREFIX = 'variant:'
WEAPON_MOD_CHOICE_SEPARATOR = '|'


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
    if normalized_type == 'scroll' or normalized_category == 'scroll' or normalized_sub_category.endswith('scroll'):
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


@dataclass
class CatalogLoadResult(_CatalogIndexResult):
    catalog_common_material_ids: list[int] = field(default_factory=list)
    common_salvage_model_ids_by_item_key: dict[tuple[int, int], tuple[int, ...]] = field(default_factory=dict)
    common_salvage_ambiguous_item_keys: set[tuple[int, int]] = field(default_factory=set)
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
        self._index_loader = _CatalogIndexLoader(
            item_priority_resolver=lambda model_id, item_type, category, sub_category: (
                _get_catalog_entry_priority(
                    model_id,
                    item_type,
                    category,
                    sub_category,
                    scroll_trader_stock_model_ids=self.scroll_trader_stock_model_ids,
                )
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
            self._enrich_exact_catalog_material_metadata(result, common_entries + rare_entries)
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
        self._normalize_exact_catalog_aliases(result)
        self._rebuild_exact_untyped_catalog(result)
        result.catalog_stats = {
            'curated_common': len(common_entries),
            'curated_rare': len(rare_entries),
            'curated_essentials': len(merchant_entries),
            'curated_total': len(common_entries) + len(rare_entries) + len(merchant_entries),
            'item_handling_present': item_handling_present,
            'item_handling_items': item_handling_items_count,
            'common_salvage_typed_items': len(result.common_salvage_model_ids_by_item_key),
            'common_salvage_ambiguous_items': len(result.common_salvage_ambiguous_item_keys),
            'rune_models': rune_model_catalog_count,
            'drop_data': drop_data_count,
            'modelid_fallback_items': model_id_fallback_count,
            'final_models': len(result.catalog_by_model_id),
            'exact_typed_items': len(result.exact_catalog_by_item_key),
            'exact_untyped_items': len(result.exact_catalog_untyped_by_model_id),
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
    def register_catalog_entry(
        result: CatalogLoadResult,
        model_id: int,
        name: str,
        item_type: str = '',
        material_type: str = '',
        source: str = '',
        priority: int = 100,
        extra: dict[str, object] | None = None,
    ) -> None:
        _CatalogIndexLoader.register_catalog_entry(
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
        return self._index_loader.load_catalog_group(
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
        return self._index_loader.load_drop_data_catalog(result.catalog_by_model_id, rows, priority=50)

    def _load_item_handling_catalog(self, result: CatalogLoadResult) -> int:
        if not os.path.exists(self.item_handling_path):
            return 0

        with open(self.item_handling_path, 'r', encoding='utf-8') as file:
            raw_catalog = json.load(file)

        return self._index_loader.load_item_handling_catalog(
            result.catalog_by_model_id,
            raw_catalog,
            priority_resolver=lambda model_id, item_type, category, sub_category: (
                _get_catalog_entry_priority(
                    model_id,
                    item_type,
                    category,
                    sub_category,
                    scroll_trader_stock_model_ids=self.scroll_trader_stock_model_ids,
                )
            ),
            common_salvage_model_ids_by_item_key=result.common_salvage_model_ids_by_item_key,
            common_salvage_ambiguous_item_keys=result.common_salvage_ambiguous_item_keys,
            exact_catalog_by_item_key=result.exact_catalog_by_item_key,
        )

    @staticmethod
    def _enrich_exact_catalog_material_metadata(
        result: CatalogLoadResult,
        entries: list[dict[str, object]],
    ) -> None:
        material_type_id = int(ItemType.Materials_Zcoins)
        for entry in entries:
            model_id = max(0, _safe_int(entry.get('model_id', 0), 0))
            if model_id <= 0:
                continue
            typed_entry = result.exact_catalog_by_item_key.get((material_type_id, model_id))
            if typed_entry is None:
                continue
            material_type = str(entry.get('material_type', '') or '').strip()
            if material_type:
                typed_entry['material_type'] = material_type

    @staticmethod
    def _rebuild_exact_untyped_catalog(result: CatalogLoadResult) -> None:
        typed_model_ids = {
            int(model_id)
            for _item_type_id, model_id in result.exact_catalog_by_item_key.keys()
            if int(model_id) > 0
        }
        result.exact_catalog_untyped_by_model_id = {}
        for model_id, flat_entry in result.catalog_by_model_id.items():
            safe_model_id = max(0, _safe_int(model_id, 0))
            if safe_model_id <= 0 or safe_model_id in typed_model_ids:
                continue
            if not isinstance(flat_entry, dict):
                continue
            fallback_entry = dict(flat_entry)
            fallback_entry['item_type_id'] = None
            fallback_entry['exact_match_mode'] = 'wildcard'
            result.exact_catalog_untyped_by_model_id[safe_model_id] = fallback_entry

    @staticmethod
    def _normalize_exact_catalog_aliases(result: CatalogLoadResult) -> None:
        for entry in result.exact_catalog_by_item_key.values():
            alias_labels = entry.get('alias_labels', {})
            normalized_alias_labels: dict[str, str] = {}
            if isinstance(alias_labels, dict):
                for raw_alias, display_name in alias_labels.items():
                    normalized_alias = _normalize_catalog_search_text(raw_alias)
                    if normalized_alias:
                        normalized_alias_labels[normalized_alias] = (
                            str(display_name or '').strip() or normalized_alias.title()
                        )
            name = str(entry.get('name', '')).strip()
            normalized_name = _normalize_catalog_search_text(name)
            if normalized_name and normalized_name not in normalized_alias_labels:
                normalized_alias_labels[normalized_name] = name
            entry['alias_labels'] = normalized_alias_labels

        for entry in result.exact_catalog_untyped_by_model_id.values():
            alias_labels = entry.get('alias_labels', {})
            normalized_alias_labels: dict[str, str] = {}
            if isinstance(alias_labels, dict):
                for raw_alias, display_name in alias_labels.items():
                    normalized_alias = _normalize_catalog_search_text(_strip_catalog_display_markup(raw_alias))
                    if normalized_alias:
                        clean_display_name = _strip_catalog_display_markup(display_name)
                        normalized_alias_labels[normalized_alias] = (
                            clean_display_name or normalized_alias.title()
                        )
            name = _normalize_catalog_display_name(entry.get('name', ''), entry.get('model_id', 0))
            if name:
                entry['name'] = name
            normalized_name = _normalize_catalog_search_text(name)
            if normalized_name and normalized_name not in normalized_alias_labels:
                normalized_alias_labels[normalized_name] = name
            entry['alias_labels'] = normalized_alias_labels

    def _load_rune_model_catalog(self, result: CatalogLoadResult) -> int:
        if not os.path.exists(self.runes_catalog_path):
            return 0

        with open(self.runes_catalog_path, 'r', encoding='utf-8') as file:
            raw_catalog = json.load(file)

        return self._index_loader.load_rune_model_catalog(
            result.catalog_by_model_id,
            raw_catalog,
            priority=18,
            exact_catalog_by_item_key=result.exact_catalog_by_item_key,
        )

    def _load_model_id_fallback_catalog(self, result: CatalogLoadResult) -> int:
        return self._index_loader.load_model_id_fallback_catalog(
            result.catalog_by_model_id,
            self.model_id_members,
            priority=90,
        )

    @staticmethod
    def _rebuild_catalog_alias_index(result: CatalogLoadResult) -> None:
        (
            result.catalog_alias_to_model_ids,
            result.catalog_alias_display_names,
        ) = _CatalogIndexLoader.rebuild_catalog_alias_index(result.catalog_by_model_id)

    @staticmethod
    def _get_catalog_alias_group_count(result: CatalogLoadResult) -> int:
        return _CatalogIndexLoader.get_catalog_alias_group_count(result.catalog_alias_to_model_ids)

    @staticmethod
    def get_catalog_alias_group_count(alias_to_model_ids: dict[str, list[int]]) -> int:
        return _CatalogIndexLoader.get_catalog_alias_group_count(alias_to_model_ids)

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
        self.rebuild_rune_exact_display_lookup(result)
        result.rune_buy_entries_by_profession = grouped_entries
        result.rune_buy_professions = profession_order

    @staticmethod
    def rebuild_rune_exact_display_lookup(result: CatalogLoadResult) -> None:
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


MODIFIER_IDENTIFIER_RUNE_ATTRIBUTE = RUNE_ATTRIBUTE_MODIFIER_IDENTIFIER

# Public operations used by the Merchant Rules widget. The implementation helpers remain local to
# this feature backend so no CoreLib-private names cross the module boundary.
build_catalog_alias_labels = _build_catalog_alias_labels
get_catalog_entry_priority = _get_catalog_entry_priority
humanize_model_id_enum_name = _humanize_model_id_enum_name
get_rune_profession_label = _get_rune_profession_label
get_weapon_mod_type_name = _get_weapon_mod_type_name
humanize_weapon_mod_component_kind = _humanize_weapon_mod_component_kind
is_expandable_weapon_mod_type = _is_expandable_weapon_mod_type
make_weapon_mod_identifier_choice_key = _make_weapon_mod_identifier_choice_key
make_weapon_mod_variant_choice_key = _make_weapon_mod_variant_choice_key
iter_item_handling_catalog_entries = _iter_item_handling_catalog_entries
iter_model_id_members = _iter_model_id_members
normalize_catalog_search_text = _normalize_catalog_search_text
strip_catalog_display_markup = _strip_catalog_display_markup
normalize_weapon_mod_component_kind = _normalize_weapon_mod_component_kind
normalize_weapon_mod_target_item_type = _normalize_weapon_mod_target_item_type
normalize_weapon_mod_variant_parts = _normalize_weapon_mod_variant_parts
resolve_rune_description_template = _resolve_rune_description_template
format_weapon_mod_variant_label = _format_weapon_mod_variant_label

CatalogLoader = MerchantRulesCatalogLoader


def humanize_exact_item_type(
    item_type_id: object,
    raw_item_type: object = "",
    *,
    item_type_enum: type[ItemType],
) -> str:
    raw_name = str(raw_item_type or "").strip()
    if not raw_name:
        try:
            raw_name = item_type_enum(_session_safe_int(item_type_id, -1)).name
        except (TypeError, ValueError):
            raw_name = f"Item type {_session_safe_int(item_type_id, -1)}"
    return re.sub(r"\s+", " ", raw_name.replace("_", " ")).strip()


class CatalogSession:
    """Own one widget's published Catalog state, indexes and queries."""

    def __init__(
        self,
        *,
        ranker: RankedCatalogSearch,
        item_type_enum: type[ItemType],
        weapon_item_type_ids: set[int],
        weapon_like_item_types: frozenset[ItemType],
        armor_piece_types: frozenset[ItemType],
        is_valid_exact_item_type_id: Callable[[object], bool],
        is_weapon_catalog_item_type: Callable[[object], bool],
        is_armor_catalog_item_type: Callable[[object], bool],
        is_weapon_mod_catalog_name: Callable[[Callable[[], object]], bool],
        is_armor_rune_catalog_name: Callable[[Callable[[], object]], bool],
        is_armor_salvage_catalog_name: Callable[[Callable[[], object]], bool],
        get_search_result_limit: Callable[[], int],
    ) -> None:
        self._ranked_catalog_search = ranker
        self._item_type_enum = item_type_enum
        self._weapon_item_type_ids = weapon_item_type_ids
        self._weapon_like_item_types = weapon_like_item_types
        self._armor_piece_types = armor_piece_types
        self._is_valid_exact_item_type_id = is_valid_exact_item_type_id
        self._is_weapon_catalog_item_type = is_weapon_catalog_item_type
        self._is_armor_catalog_item_type = is_armor_catalog_item_type
        self._is_weapon_mod_catalog_name = is_weapon_mod_catalog_name
        self._is_armor_rune_catalog_name = is_armor_rune_catalog_name
        self._is_armor_salvage_catalog_name = is_armor_salvage_catalog_name
        self._get_search_result_limit = get_search_result_limit
        self.catalog_loaded: bool = False
        self.catalog_load_error: str = ""
        self.catalog_by_model_id: dict[int, dict[str, object]] = {}
        self.exact_catalog_by_item_key: dict[tuple[int, int], dict[str, object]] = {}
        self.exact_catalog_untyped_by_model_id: dict[int, dict[str, object]] = {}
        self._equipment_typed_entries_by_model_id: dict[int, tuple[dict[str, object], ...]] = {}
        self._equipment_model_search_entry_cache: dict[tuple[int, str, bool, bool], dict[str, object]] = {}
        self._catalog_generation: int = 0
        self._catalog_building: bool = False
        self.catalog_alias_to_model_ids: dict[str, list[int]] = {}
        self.catalog_alias_display_names: dict[str, str] = {}
        self.common_salvage_model_ids_by_item_key: dict[tuple[int, int], tuple[int, ...]] = {}
        self.catalog_common_material_ids: list[int] = []
        self.catalog_merchant_essentials: list[dict[str, object]] = []
        self.catalog_rare_materials: list[dict[str, object]] = []
        self.catalog_stats: dict[str, int | bool] = {}
        self.weapon_mod_entries: list[dict[str, str]] = []
        self.rune_entries: list[dict[str, str]] = []
        self.armor_upgrade_entries: list[dict[str, str]] = []
        self.weapon_mod_names: dict[str, str] = {}
        self.weapon_mod_generic_names: dict[str, str] = {}
        self.weapon_mod_variant_names: dict[str, str] = {}
        self.rune_names: dict[str, str] = {}
        self.rune_buy_entries: list[dict[str, object]] = []
        self.rune_buy_entries_by_identifier: dict[str, dict[str, object]] = {}
        self.rune_buy_identifier_by_exact_label: dict[str, str] = {}
        self.rune_buy_entries_by_profession: dict[str, list[dict[str, object]]] = {}
        self.rune_buy_professions: list[str] = []

    @property
    def equipment_typed_entries_by_model_id(self) -> dict[int, tuple[dict[str, object], ...]]:
        return self._equipment_typed_entries_by_model_id

    @equipment_typed_entries_by_model_id.setter
    def equipment_typed_entries_by_model_id(self, value: dict[int, tuple[dict[str, object], ...]]) -> None:
        self._equipment_typed_entries_by_model_id = value

    @property
    def equipment_model_search_entry_cache(self) -> dict[tuple[int, str, bool, bool], dict[str, object]]:
        return self._equipment_model_search_entry_cache

    @equipment_model_search_entry_cache.setter
    def equipment_model_search_entry_cache(self, value: dict[tuple[int, str, bool, bool], dict[str, object]]) -> None:
        self._equipment_model_search_entry_cache = value

    @property
    def catalog_generation(self) -> int:
        return self._catalog_generation

    @catalog_generation.setter
    def catalog_generation(self, value: int) -> None:
        self._catalog_generation = value

    @property
    def catalog_building(self) -> bool:
        return self._catalog_building

    @catalog_building.setter
    def catalog_building(self, value: bool) -> None:
        self._catalog_building = value

    def load_modifier_catalogs(self, *, get_loader: Callable[[], CatalogLoader]) -> None:
        result = get_loader().load_modifier_catalogs()
        self.weapon_mod_entries = result.weapon_mod_entries
        self.rune_entries = result.rune_entries
        self.armor_upgrade_entries = result.armor_upgrade_entries
        self.weapon_mod_names = result.weapon_mod_names
        self.weapon_mod_generic_names = result.weapon_mod_generic_names
        self.weapon_mod_variant_names = result.weapon_mod_variant_names
        self.rune_names = result.rune_names

    def load_rune_buy_catalog(self, *, get_loader: Callable[[], CatalogLoader]) -> None:
        result = get_loader().load_rune_buy_catalog()
        self.rune_buy_entries = result.rune_buy_entries
        self.rune_buy_entries_by_identifier = result.rune_buy_entries_by_identifier
        self.rune_buy_identifier_by_exact_label = result.rune_buy_identifier_by_exact_label
        self.rune_buy_entries_by_profession = result.rune_buy_entries_by_profession
        self.rune_buy_professions = result.rune_buy_professions

    def get_catalog_alias_group_count(self) -> int:
        return CatalogLoader.get_catalog_alias_group_count(self.catalog_alias_to_model_ids)

    def clear_ranked_search_caches(self) -> None:
        self._ranked_catalog_search.clear()

    @staticmethod
    def catalog_entry_search_signature(entry: dict[str, object]) -> tuple[object, ...]:
        alias_labels = entry.get("alias_labels", {})
        alias_signature: tuple[str, ...] = ()
        if isinstance(alias_labels, dict):
            alias_signature = tuple(sorted(str(raw_alias) for raw_alias in alias_labels))
        return (
            str(entry.get("name", "")).strip(),
            max(0, _session_safe_int(entry.get("model_id", 0), 0)),
            normalize_catalog_search_text(entry.get("item_type", "")),
            normalize_catalog_search_text(entry.get("material_type", "")),
            normalize_catalog_search_text(entry.get("category", "")),
            normalize_catalog_search_text(entry.get("sub_category", "")),
            _session_safe_int(entry.get("item_type_id", -1), -1),
            alias_signature,
        )

    def capture_catalog_search_state(
        self,
    ) -> dict[int, tuple[dict[str, object], tuple[object, ...]]]:
        return {
            int(model_id): (entry, self.catalog_entry_search_signature(entry))
            for model_id, entry in self.catalog_by_model_id.items()
        }

    def catalog_search_state_changed(
        self,
        previous_state: dict[int, tuple[dict[str, object], tuple[object, ...]]],
    ) -> bool:
        if len(previous_state) != len(self.catalog_by_model_id):
            return True
        for model_id, entry in self.catalog_by_model_id.items():
            previous_entry_state = previous_state.get(int(model_id))
            if previous_entry_state is None:
                return True
            previous_entry, previous_signature = previous_entry_state
            if entry is not previous_entry or self.catalog_entry_search_signature(entry) != previous_signature:
                return True
        return False

    def invalidate_ranked_search_caches_for_catalog_mutation(self) -> None:
        """Invalidate ranked results after a published searchable-catalog mutation."""
        if self._catalog_building:
            # _load_catalog publishes one fresh result after all source loaders finish.
            return
        if self.catalog_loaded:
            self._catalog_generation += 1
        self.clear_ranked_search_caches()

    def register_catalog_entry(
        self,
        model_id: int,
        name: str,
        item_type: str = "",
        material_type: str = "",
        source: str = "",
        priority: int = 100,
        extra: dict[str, object] | None = None,
    ) -> None:
        previous_state = self.capture_catalog_search_state()
        try:
            result = CatalogLoadResult(catalog_by_model_id=self.catalog_by_model_id)
            CatalogLoader.register_catalog_entry(
                result,
                model_id,
                name,
                item_type,
                material_type,
                source,
                priority,
                extra,
            )
        finally:
            if self.catalog_search_state_changed(previous_state):
                self.invalidate_ranked_search_caches_for_catalog_mutation()

    def load_catalog_group(
        self,
        entries: list[dict[str, object]],
        source: str,
        priority: int,
        default_item_type: str = "",
        default_material_type: str = "",
        *,
        get_loader: Callable[[], CatalogLoader],
    ) -> list[dict[str, object]]:
        previous_state = self.capture_catalog_search_state()
        try:
            return get_loader().load_catalog_group(
                self.catalog_by_model_id,
                entries,
                source,
                priority,
                default_item_type,
                default_material_type,
            )
        finally:
            if self.catalog_search_state_changed(previous_state):
                self.invalidate_ranked_search_caches_for_catalog_mutation()

    def load_drop_data_catalog(self, *, get_loader: Callable[[], CatalogLoader]) -> int:
        previous_state = self.capture_catalog_search_state()
        try:
            return get_loader().load_drop_data_catalog(self.catalog_by_model_id)
        finally:
            if self.catalog_search_state_changed(previous_state):
                self.invalidate_ranked_search_caches_for_catalog_mutation()

    def load_item_handling_catalog(self, *, get_loader: Callable[[], CatalogLoader]) -> int:
        previous_state = self.capture_catalog_search_state()
        try:
            return get_loader().load_item_handling_catalog(self.catalog_by_model_id)
        finally:
            if self.catalog_search_state_changed(previous_state):
                self.invalidate_ranked_search_caches_for_catalog_mutation()

    def load_rune_model_catalog(self, *, get_loader: Callable[[], CatalogLoader]) -> int:
        previous_state = self.capture_catalog_search_state()
        try:
            return get_loader().load_rune_model_catalog(self.catalog_by_model_id)
        finally:
            if self.catalog_search_state_changed(previous_state):
                self.invalidate_ranked_search_caches_for_catalog_mutation()

    def load_model_id_fallback_catalog(self, *, get_loader: Callable[[], CatalogLoader]) -> int:
        previous_state = self.capture_catalog_search_state()
        try:
            return get_loader().load_model_id_fallback_catalog(self.catalog_by_model_id)
        finally:
            if self.catalog_search_state_changed(previous_state):
                self.invalidate_ranked_search_caches_for_catalog_mutation()

    def rebuild_catalog_alias_index(self, *, get_loader: Callable[[], CatalogLoader]) -> None:
        previous_state = self.capture_catalog_search_state()
        try:
            aliases, display_names = get_loader().rebuild_catalog_alias_index(self.catalog_by_model_id)
            self.catalog_alias_to_model_ids = aliases
            self.catalog_alias_display_names = display_names
        finally:
            if self.catalog_search_state_changed(previous_state):
                self.invalidate_ranked_search_caches_for_catalog_mutation()

    def load_catalog(
        self,
        *,
        get_loader: Callable[[], CatalogLoader],
        invalidate_cleanup_filter_targets: Callable[[], None],
        invalidate_cleanup_target_display: Callable[[], None],
        report_warning: Callable[[Callable[[], str]], None],
    ) -> None:
        self._catalog_building = True
        try:
            self.catalog_loaded = False
            self.clear_ranked_search_caches()
            self.catalog_by_model_id = {}
            self.exact_catalog_by_item_key = {}
            self.exact_catalog_untyped_by_model_id = {}
            self.catalog_alias_to_model_ids = {}
            self.catalog_alias_display_names = {}
            self.common_salvage_model_ids_by_item_key = {}
            self.catalog_common_material_ids = []
            self.catalog_merchant_essentials = []
            self.catalog_rare_materials = []
            self.catalog_stats = {}
            self.catalog_load_error = ""

            result: CatalogLoadResult = get_loader().load()
            self.catalog_by_model_id = result.catalog_by_model_id
            self.exact_catalog_by_item_key = result.exact_catalog_by_item_key
            self.exact_catalog_untyped_by_model_id = result.exact_catalog_untyped_by_model_id
            self.rebuild_equipment_typed_entry_index()
            self.catalog_alias_to_model_ids = result.catalog_alias_to_model_ids
            self.catalog_alias_display_names = result.catalog_alias_display_names
            self.common_salvage_model_ids_by_item_key = result.common_salvage_model_ids_by_item_key
            self.catalog_common_material_ids = result.catalog_common_material_ids
            self.catalog_merchant_essentials = result.catalog_merchant_essentials
            self.catalog_rare_materials = result.catalog_rare_materials
            self.catalog_stats = result.catalog_stats
            self.catalog_load_error = result.catalog_load_error
            self.weapon_mod_entries = result.weapon_mod_entries
            self.rune_entries = result.rune_entries
            self.armor_upgrade_entries = result.armor_upgrade_entries
            self.weapon_mod_names = result.weapon_mod_names
            self.weapon_mod_generic_names = result.weapon_mod_generic_names
            self.weapon_mod_variant_names = result.weapon_mod_variant_names
            self.rune_names = result.rune_names
            self.rune_buy_entries = result.rune_buy_entries
            self.rune_buy_entries_by_identifier = result.rune_buy_entries_by_identifier
            self.rune_buy_identifier_by_exact_label = result.rune_buy_identifier_by_exact_label
            self.rune_buy_entries_by_profession = result.rune_buy_entries_by_profession
            self.rune_buy_professions = result.rune_buy_professions
            self._catalog_generation += 1
            invalidate_cleanup_filter_targets()
            invalidate_cleanup_target_display()
            self.catalog_loaded = True
            if self.catalog_load_error:
                report_warning(lambda: self.catalog_load_error)
        finally:
            self._catalog_building = False
            self.clear_ranked_search_caches()

    def get_model_entry(self, model_id: int) -> dict[str, object] | None:
        return self.catalog_by_model_id.get(max(0, _session_safe_int(model_id, 0)))

    def get_model_name(self, model_id: int) -> str:
        entry = self.get_model_entry(model_id)
        if entry is None:
            return ""
        return str(entry.get("name", "")).strip()

    def get_model_descriptor(self, model_id: int) -> str:
        entry = self.get_model_entry(model_id)
        if entry is None:
            return ""
        material_type = str(entry.get("material_type", "")).strip()
        if material_type:
            return material_type
        return str(entry.get("item_type", "")).strip()

    def get_model_item_type(self, model_id: int) -> str:
        entry = self.get_model_entry(model_id)
        if entry is None:
            return ""
        return str(entry.get("item_type", "")).strip()

    def rebuild_equipment_typed_entry_index(self) -> None:
        """Index the typed catalog rows used by Equipment's collision projections."""

        self._equipment_model_search_entry_cache = {}
        entries_by_model_id: dict[int, list[dict[str, object]]] = {}
        for (raw_item_type_id, raw_model_id), entry in self.exact_catalog_by_item_key.items():
            model_id = max(0, _session_safe_int(raw_model_id, 0))
            item_type_id = _session_safe_int(raw_item_type_id, -1)
            if model_id <= 0 or not self._is_valid_exact_item_type_id(item_type_id) or not isinstance(entry, dict):
                continue
            entries_by_model_id.setdefault(model_id, []).append(entry)
        self._equipment_typed_entries_by_model_id = {
            model_id: tuple(entries)
            for model_id, entries in entries_by_model_id.items()
        }

    def get_equipment_typed_entries_for_model(self, model_id: object) -> list[dict[str, object]]:
        safe_model_id = max(0, _session_safe_int(model_id, 0))
        if safe_model_id <= 0:
            return []

        indexed_entries = getattr(self, "_equipment_typed_entries_by_model_id", {})
        if not indexed_entries and self.exact_catalog_by_item_key:
            self.rebuild_equipment_typed_entry_index()
            indexed_entries = self._equipment_typed_entries_by_model_id
        return list(indexed_entries.get(safe_model_id, ()))

    def catalog_entry_matches_equipment_family(
        self,
        entry: dict[str, object],
        rule_kind: str,
        *,
        include_standalone_weapon_mods: bool = False,
        include_standalone_runes: bool = False,
    ) -> bool:
        item_type_id = _session_safe_int(entry.get("item_type_id"), -1)
        item_type: ItemType | None = None
        if self._is_valid_exact_item_type_id(item_type_id):
            try:
                item_type = self._item_type_enum(item_type_id)
            except ValueError:
                item_type = None

        if rule_kind == SELL_KIND_WEAPONS:
            if item_type in self._weapon_like_item_types:
                return True
            if item_type == self._item_type_enum.Rune_Mod:
                return include_standalone_weapon_mods and not self._is_armor_rune_catalog_name(
                    lambda: entry.get("name", "")
                )
            item_type_name = str(entry.get("item_type", "")).strip()
            if self._is_weapon_catalog_item_type(item_type_name):
                return True
            return (
                include_standalone_weapon_mods
                and item_type_name.casefold() == "rune_mod"
                and self._is_weapon_mod_catalog_name(lambda: entry.get("name", ""))
            )

        if rule_kind == SELL_KIND_ARMOR:
            if item_type in self._armor_piece_types:
                return True
            if item_type == self._item_type_enum.Rune_Mod:
                return include_standalone_runes and self._is_armor_rune_catalog_name(lambda: entry.get("name", ""))
            item_type_name = str(entry.get("item_type", "")).strip()
            if self._is_armor_catalog_item_type(item_type_name):
                return True
            if item_type_name.casefold() == "salvage":
                return self._is_armor_salvage_catalog_name(lambda: entry.get("name", ""))
            return include_standalone_runes and (
                item_type_name.casefold() == "rune_mod"
                and self._is_armor_rune_catalog_name(lambda: entry.get("name", ""))
            )

        return False

    def get_equipment_model_family_entries(
        self,
        model_id: object,
        rule_kind: str,
        *,
        include_standalone_weapon_mods: bool = False,
        include_standalone_runes: bool = False,
    ) -> list[dict[str, object]]:
        typed_entries = self.get_equipment_typed_entries_for_model(model_id)
        if typed_entries:
            return [
                entry
                for entry in typed_entries
                if self.catalog_entry_matches_equipment_family(
                    entry,
                    rule_kind,
                    include_standalone_weapon_mods=include_standalone_weapon_mods,
                    include_standalone_runes=include_standalone_runes,
                )
            ]

        safe_model_id = max(0, _session_safe_int(model_id, 0))
        flat_entry = self.get_model_entry(safe_model_id)
        if flat_entry is None or not self.catalog_entry_matches_equipment_family(
            flat_entry,
            rule_kind,
            include_standalone_weapon_mods=include_standalone_weapon_mods,
            include_standalone_runes=include_standalone_runes,
        ):
            return []
        return [flat_entry]

    def get_equipment_catalog_type_label(self, entry: dict[str, object], rule_kind: str) -> str:
        item_type_id = _session_safe_int(entry.get("item_type_id"), -1)
        if item_type_id == int(self._item_type_enum.Rune_Mod):
            return "Weapon Mod" if rule_kind == SELL_KIND_WEAPONS else "Armor Upgrade"
        raw_item_type = str(entry.get("item_type", "")).strip()
        if raw_item_type:
            return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw_item_type.replace("_", " ")).strip()
        if self._is_valid_exact_item_type_id(item_type_id):
            return humanize_exact_item_type(item_type_id, item_type_enum=self._item_type_enum)
        return "Item"

    def get_equipment_model_search_entry(
        self,
        model_id: object,
        rule_kind: str,
        *,
        include_standalone_weapon_mods: bool = False,
        include_standalone_runes: bool = False,
    ) -> dict[str, object] | None:
        safe_model_id = max(0, _session_safe_int(model_id, 0))
        if safe_model_id <= 0:
            return None
        cache_key = (
            safe_model_id,
            str(rule_kind),
            bool(include_standalone_weapon_mods),
            bool(include_standalone_runes),
        )
        cached_entry = self._equipment_model_search_entry_cache.get(cache_key)
        if cached_entry is not None:
            return cached_entry
        family_entries = self.get_equipment_model_family_entries(
            safe_model_id,
            rule_kind,
            include_standalone_weapon_mods=include_standalone_weapon_mods,
            include_standalone_runes=include_standalone_runes,
        )
        if not family_entries:
            return None

        def is_concrete_entry(entry: dict[str, object]) -> bool:
            item_type_id = _session_safe_int(entry.get("item_type_id"), -1)
            if rule_kind == SELL_KIND_WEAPONS:
                return item_type_id in self._weapon_item_type_ids
            return item_type_id in {
                int(item_type.value)
                for item_type in self._armor_piece_types
                if item_type != self._item_type_enum.Salvage
            }

        preferred_entry = next((entry for entry in family_entries if is_concrete_entry(entry)), family_entries[0])
        ordered_entries = [preferred_entry] + [entry for entry in family_entries if entry is not preferred_entry]
        result = dict(preferred_entry)
        names: list[str] = []
        type_labels: list[str] = []
        alias_labels: dict[str, str] = {}

        def add_unique(values: list[str], raw_value: object) -> None:
            value = str(raw_value or "").strip()
            if value and value.casefold() not in {existing.casefold() for existing in values}:
                values.append(value)

        for entry in ordered_entries:
            add_unique(names, entry.get("name", ""))
            add_unique(type_labels, self.get_equipment_catalog_type_label(entry, rule_kind))
            raw_alias_labels = entry.get("alias_labels", {})
            if isinstance(raw_alias_labels, dict):
                for raw_alias, display_name in raw_alias_labels.items():
                    normalized_alias = normalize_catalog_search_text(raw_alias)
                    if normalized_alias:
                        alias_labels.setdefault(
                            normalized_alias,
                            str(display_name or raw_alias or "").strip() or normalized_alias.title(),
                        )

        for value in names + type_labels:
            normalized_value = normalize_catalog_search_text(value)
            if normalized_value:
                alias_labels.setdefault(normalized_value, value)

        is_group = len(family_entries) > 1
        group_label = ""
        if is_group:
            name_label = " / ".join(names) or f"Model {safe_model_id}"
            type_label = " + ".join(type_labels)
            group_label = f"{name_label} ({safe_model_id})"
            if type_label:
                group_label = f"{group_label} - {type_label}"
            normalized_group_label = normalize_catalog_search_text(group_label)
            if normalized_group_label:
                alias_labels.setdefault(normalized_group_label, group_label)

        result["equipment_group"] = is_group
        result["equipment_group_label"] = group_label
        result["equipment_group_names"] = names
        result["equipment_group_types"] = type_labels
        result["equipment_family"] = rule_kind
        result["alias_labels"] = alias_labels
        result["equipment_search_text"] = normalize_catalog_search_text(
            " ".join(
                [
                    str(safe_model_id),
                    str(result.get("name", "")),
                    str(result.get("item_type", "")),
                    group_label,
                    " ".join(names),
                    " ".join(type_labels),
                    " ".join(alias_labels.keys()),
                ]
            )
        )
        self._equipment_model_search_entry_cache[cache_key] = result
        return result

    def iter_exact_catalog_entries(self) -> Iterable[dict[str, object]]:
        yield from self.exact_catalog_by_item_key.values()
        yield from self.exact_catalog_untyped_by_model_id.values()

    def get_exact_catalog_entry(self, item_type_id: object, model_id: object) -> dict[str, object] | None:
        safe_model_id = max(0, _session_safe_int(model_id, 0))
        safe_item_type_id = _session_safe_int(item_type_id, -1)
        if safe_model_id <= 0 or safe_item_type_id < 0:
            return None
        return self.exact_catalog_by_item_key.get((safe_item_type_id, safe_model_id))

    def get_exact_catalog_entry_key(self, entry: dict[str, object]) -> tuple[int | None, int] | None:
        safe_model_id = max(0, _session_safe_int(entry.get("model_id", 0), 0))
        if safe_model_id <= 0:
            return None
        raw_item_type_id = entry.get("item_type_id")
        if raw_item_type_id is None:
            return None, safe_model_id
        safe_item_type_id = _session_safe_int(raw_item_type_id, -1)
        if not self._is_valid_exact_item_type_id(safe_item_type_id):
            return None
        return safe_item_type_id, safe_model_id

    def get_exact_catalog_entries_for_model(self, model_id: object) -> list[dict[str, object]]:
        safe_model_id = max(0, _session_safe_int(model_id, 0))
        if safe_model_id <= 0:
            return []
        typed_entries = [
            entry
            for (item_type_id, entry_model_id), entry in self.exact_catalog_by_item_key.items()
            if int(entry_model_id) == safe_model_id and self._is_valid_exact_item_type_id(item_type_id)
        ]
        if typed_entries:
            return typed_entries
        fallback = self.exact_catalog_untyped_by_model_id.get(safe_model_id)
        return [fallback] if isinstance(fallback, dict) else []

    def search_exact_catalog(
        self,
        raw_query: str,
        limit: int,
    ) -> list[dict[str, object]]:
        return self._ranked_catalog_search.search_exact(
            raw_query,
            generation=self._catalog_generation,
            typed_entries=self.exact_catalog_by_item_key,
            untyped_entries=self.exact_catalog_untyped_by_model_id,
            limit=limit,
        )

    def search_exact_catalog_with_predicate(
        self,
        raw_query: str,
        *,
        entry_predicate: Callable[[dict[str, object]], bool],
        limit: int,
    ) -> list[dict[str, object]]:
        catalog_limit = max(max(1, len(self.exact_catalog_by_item_key) + len(self.exact_catalog_untyped_by_model_id)), limit * 4)
        results = self.search_exact_catalog(raw_query, limit=catalog_limit)
        filtered_results: list[dict[str, object]] = []
        seen_keys: set[tuple[int | None, int]] = set()
        for entry in results:
            entry_key = self.get_exact_catalog_entry_key(entry)
            if entry_key is None or entry_key in seen_keys:
                continue
            if not entry_predicate(entry):
                continue
            seen_keys.add(entry_key)
            filtered_results.append(entry)
            if len(filtered_results) >= max(1, int(limit)):
                break
        return filtered_results

    def search_catalog(self, raw_query: str, limit: int) -> list[dict[str, object]]:
        return self._ranked_catalog_search.search_flat(
            raw_query,
            generation=self._catalog_generation,
            entries=self.catalog_by_model_id,
            limit=limit,
        )

    def search_catalog_with_predicate(
        self,
        raw_query: str,
        *,
        entry_predicate: Callable[[dict[str, object]], bool],
        limit: int,
    ) -> list[dict[str, object]]:
        catalog_limit = max(max(1, len(self.catalog_by_model_id)), limit * 4, self._get_search_result_limit() * 4)
        results = self.search_catalog(raw_query, limit=catalog_limit)
        filtered_results: list[dict[str, object]] = []
        seen_model_ids: set[int] = set()
        for entry in results:
            model_id = max(0, _session_safe_int(entry.get("model_id", 0), 0))
            if model_id <= 0 or model_id in seen_model_ids:
                continue
            if not entry_predicate(entry):
                continue
            seen_model_ids.add(model_id)
            filtered_results.append(entry)
            if len(filtered_results) >= max(1, int(limit)):
                break
        return filtered_results

    def search_equipment_catalog(
        self,
        raw_query: str,
        rule_kind: str,
        *,
        include_standalone_weapon_mods: bool = False,
        include_standalone_runes: bool = False,
        entry_predicate: Callable[[dict[str, object]], bool] | None = None,
        limit: int,
    ) -> list[dict[str, object]]:
        query = normalize_catalog_search_text(raw_query)
        if not query or rule_kind not in (SELL_KIND_WEAPONS, SELL_KIND_ARMOR):
            return []

        model_ids = {
            max(0, _session_safe_int(model_id, 0))
            for model_id in self.catalog_by_model_id
            if max(0, _session_safe_int(model_id, 0)) > 0
        }
        model_ids.update(
            max(0, _session_safe_int(model_id, 0))
            for _item_type_id, model_id in self.exact_catalog_by_item_key
            if max(0, _session_safe_int(model_id, 0)) > 0
        )

        matches: list[tuple[tuple[object, ...], dict[str, object]]] = []
        for model_id in model_ids:
            entry = self.get_equipment_model_search_entry(
                model_id,
                rule_kind,
                include_standalone_weapon_mods=include_standalone_weapon_mods,
                include_standalone_runes=include_standalone_runes,
            )
            if entry is None:
                continue
            if entry_predicate is not None:
                family_entries = self.get_equipment_model_family_entries(
                    model_id,
                    rule_kind,
                    include_standalone_weapon_mods=include_standalone_weapon_mods,
                    include_standalone_runes=include_standalone_runes,
                )
                if not any(entry_predicate(family_entry) for family_entry in family_entries):
                    continue

            name = str(entry.get("name", "")).strip()
            normalized_search_text = str(entry.get("equipment_search_text", "")).strip()
            if not name or query not in normalized_search_text:
                continue

            name_lower = normalize_catalog_search_text(name)
            model_id_text = str(model_id)
            item_type = normalize_catalog_search_text(entry.get("item_type", ""))
            alias_labels = entry.get("alias_labels", {})
            alias_matches = [
                str(alias)
                for alias in alias_labels
                if query in str(alias or "")
            ] if isinstance(alias_labels, dict) else []
            exact_alias_hit = any(alias == query for alias in alias_matches)
            prefix_alias_hit = any(alias.startswith(query) for alias in alias_matches)
            group_search_values: list[str] = []
            for key in ("equipment_group_names", "equipment_group_types"):
                raw_values = entry.get(key, [])
                if isinstance(raw_values, (list, tuple, set)):
                    group_search_values.extend(str(value or "") for value in raw_values)
            grouped_identity_hit = bool(
                entry.get("equipment_group", False)
                and query in normalize_catalog_search_text(" ".join(group_search_values))
            )
            display_label = str(entry.get("equipment_group_label", "")).strip() or name
            score = (
                0 if query == model_id_text else 1,
                0 if grouped_identity_hit else 1,
                0 if name_lower.startswith(query) else 1,
                0 if query in name_lower else 1,
                0 if exact_alias_hit else 1,
                0 if prefix_alias_hit else 1,
                0 if alias_matches else 1,
                0 if query in item_type else 1,
                len(display_label),
                display_label.casefold(),
                model_id,
            )
            matches.append((score, entry))

        matches.sort(key=lambda match: match[0])
        return [entry for _, entry in matches[: max(1, int(limit))]]

    def search_catalog_alias_groups(
        self,
        raw_query: str,
        *,
        exclude_model_ids: list[int] | None = None,
        entry_predicate: Callable[[dict[str, object]], bool] | None = None,
        limit: int,
    ) -> list[dict[str, object]]:
        query = normalize_catalog_search_text(raw_query)
        if not query:
            return []

        excluded_ids = set(_session_dedupe_model_ids(exclude_model_ids or []))
        matches: list[tuple[tuple[int, int, int, int], dict[str, object]]] = []
        for normalized_alias, model_ids in self.catalog_alias_to_model_ids.items():
            if len(model_ids) < 2 or query not in normalized_alias:
                continue

            remaining_model_ids = [model_id for model_id in model_ids if model_id not in excluded_ids]
            if entry_predicate is not None:
                remaining_model_ids = [
                    model_id
                    for model_id in remaining_model_ids
                    if entry_predicate(self.catalog_by_model_id.get(model_id, {}))
                ]
            if len(remaining_model_ids) < 2:
                continue

            display_name = self.catalog_alias_display_names.get(normalized_alias, normalized_alias.title())
            score = (
                0 if normalized_alias == query else 1,
                0 if normalized_alias.startswith(query) else 1,
                len(remaining_model_ids),
                len(display_name),
            )
            matches.append(
                (
                    score,
                    {
                        "alias": normalized_alias,
                        "display_name": display_name,
                        "model_ids": remaining_model_ids,
                    },
                )
            )

        matches.sort(key=lambda match: match[0])
        return [entry for _, entry in matches[: max(1, int(limit))]]

    def search_identifier_catalog(
        self, raw_query: str, entries: list[dict[str, str]], limit: int
    ) -> list[dict[str, str]]:
        query = str(raw_query or "").strip().lower()
        if not query:
            return []

        matches: list[tuple[tuple[int, int, int], dict[str, str]]] = []
        for entry in entries:
            identifier = str(entry.get("identifier", "")).strip()
            name = str(entry.get("name", "")).strip()
            if not identifier or not name:
                continue

            identifier_lower = identifier.lower()
            name_lower = name.lower()
            if query not in identifier_lower and query not in name_lower:
                continue

            score = (
                0 if name_lower.startswith(query) else 1,
                0 if query in name_lower else 1,
                len(name_lower),
            )
            matches.append((score, entry))

        matches.sort(key=lambda match: match[0])
        return [entry for _, entry in matches[: max(1, int(limit))]]


__all__ = [
    'CatalogSession',
    'humanize_exact_item_type',
    'CatalogLoadResult',
    'CatalogLoader',
    'MerchantRulesCatalogLoader',
    'DEFAULT_CATALOG_ENTRY_PRIORITY',
    'MODEL_ID_FALLBACK_ITEM_TYPE_SUFFIXES',
    'MODIFIER_IDENTIFIER_RUNE_ATTRIBUTE',
    'WEAPON_MOD_CHOICE_KIND_GENERIC',
    'WEAPON_MOD_CHOICE_KIND_VARIANT',
    'WEAPON_MOD_GENERIC_KEY_PREFIX',
    'WEAPON_MOD_VARIANT_KEY_PREFIX',
    'WEAPON_MOD_CHOICE_SEPARATOR',
    'build_catalog_alias_labels',
    'get_catalog_entry_priority',
    'humanize_model_id_enum_name',
    'get_rune_profession_label',
    'get_weapon_mod_type_name',
    'humanize_weapon_mod_component_kind',
    'is_expandable_weapon_mod_type',
    'make_weapon_mod_identifier_choice_key',
    'make_weapon_mod_variant_choice_key',
    'iter_item_handling_catalog_entries',
    'iter_model_id_members',
    'normalize_catalog_search_text',
    'normalize_weapon_mod_component_kind',
    'normalize_weapon_mod_target_item_type',
    'normalize_weapon_mod_variant_parts',
    'resolve_rune_description_template',
    'format_weapon_mod_variant_label',
]
