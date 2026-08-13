from dataclasses import dataclass
from dataclasses import field
from enum import IntEnum, auto
import json
import os
from typing import Any, Callable, Iterable, Optional, TypeVar, cast

import Py4GW
import PySystem
import PyImGui


from Py4GWCoreLib import ImGui
from Py4GWCoreLib import Merchant as MerchantTrading
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.ImGui_src.types import Alignment
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.Routines import Routines
from Py4GWCoreLib.UIManager import CollectorWindow, CrafterWindow, MerchantWindow
from Py4GWCoreLib.enums_src.GameData_enums import Allegiance, Attribute, Profession, Range
from Py4GWCoreLib.enums_src.Item_enums import ItemType
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Py4GWCoreLib.enums_src.Title_enums import TITLE_NAME, TITLE_TIERS, TitleID
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot
from Sources.frenkeyLib.item_mods_src.upgrades import Upgrade
from Py4GWCoreLib.py4gwcorelib_src.Color import Color
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils


project_path = PySystem.Console.get_projects_path()
MODULE_NAME = "Data Collection Helper"
MODULE_ICON = os.path.join("Textures", "Module_Icons", "Research Code.png")
DATA_DIRECTORY_PATH = os.path.join(project_path, 'Widgets', 'Data', 'npc_catalog')
    
class FactionRequirement(IntEnum):
    None_ = 0
    Kurzick = auto()
    Luxon = auto()
    
@dataclass
class CraftingRequirements:
    materials: dict[ModelID, int] = field(default_factory=dict)
    gold: int = 0
    skill_points: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            'materials': {str(int(model_id)): amount for model_id, amount in self.materials.items()},
            'gold': self.gold,
            'skill_points': self.skill_points,
        }

    @staticmethod
    def from_dict(data: Optional[dict]) -> 'CraftingRequirements':
        materials: dict[ModelID, int] = {}
        for model_id, amount in dict(data.get('materials', {}) if data else {}).items():
            try:
                materials[ModelID(int(model_id))] = int(amount or 0)
            except Exception:
                continue

        return CraftingRequirements(
            materials=materials,
            gold=int((data or {}).get('gold', 0) or 0),
            skill_points=None if (data or {}).get('skill_points') is None else int((data or {}).get('skill_points') or 0),
        )

@dataclass
class Item:
    name: str
    item_type: ItemType = ItemType.Unknown
    model_id: int = 0

    SERIALIZATION_KIND = 'item'
    
    def to_dict(self) -> dict:
        return {
            'kind': self.SERIALIZATION_KIND,
            'name': self.name,
            'item_type': self.item_type.name,
            'model_id': self.model_id,
        }

    @classmethod
    def _base_kwargs_from_dict(cls, data: dict) -> dict[str, Any]:
        item_type_name = str(data.get('item_type', ItemType.Unknown.name))
        return {
            'name': str(data.get('name', '')),
            'item_type': ItemType[item_type_name] if item_type_name in ItemType.__members__ else ItemType.Unknown,
            'model_id': int(data.get('model_id', 0) or 0),
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Item':
        return cls(**cls._base_kwargs_from_dict(data))

    @staticmethod
    def normalize_name(name: str) -> str:
        return ''.join(character.lower() for character in name if character.isalnum())

    @staticmethod
    def is_missing_name(name: str) -> bool:
        return not name or name.startswith('Model')

    @staticmethod
    def snapshot_name(item: ItemSnapshot) -> str:
        return item.names.plain_singular if item.names.plain_singular != 'Unknown Item' else ''

    @staticmethod
    def is_unknown_item_type(item_type: ItemType) -> bool:
        return item_type == ItemType.Unknown

    @property
    def specificity_rank(self) -> int:
        return 1

    @property
    def sort_key(self) -> tuple[str, str]:
        return self.item_type.name, self.name

    def has_specific_attribute(self) -> bool:
        return False

    def has_specific_profession(self) -> bool:
        return False

    def _matches_type(self, other: 'Item') -> bool:
        return (
            self.item_type == other.item_type
            or self.is_unknown_item_type(self.item_type)
            or self.is_unknown_item_type(other.item_type)
        )

    def _matches_attribute(self, other: 'Item') -> bool:
        return True

    def _matches_profession(self, other: 'Item') -> bool:
        return True

    def _matches_collectible(self, other: 'Item') -> bool:
        same_collectible = getattr(self, 'required_collectible', None) == getattr(other, 'required_collectible', None)
        collectible_placeholder_match = (
            same_collectible
            and same_collectible != tuple[int, int]()
            and self._matches_type(other)
            and self._matches_profession(other)
            and (
                self.is_missing_name(self.name)
                or self.is_missing_name(other.name)
                or int(self.model_id or 0) == 0
                or int(other.model_id or 0) == 0
            )
        )
        if collectible_placeholder_match:
            return True

        if same_collectible and same_collectible != tuple[int, int]():
            return (
                self.normalize_name(self.name) == self.normalize_name(other.name)
                and self._matches_type(other)
                and self._matches_attribute(other)
                and self._matches_profession(other)
            )

        return False

    def _matches_identity(self, other: 'Item') -> bool:
        if self.model_id and other.model_id and not self.has_specific_attribute() and not other.has_specific_attribute():
            return self.model_id == other.model_id and self._matches_type(other)

        if self._matches_collectible(other):
            return True

        return (
            self.normalize_name(self.name) == self.normalize_name(other.name)
            and self._matches_type(other)
            and self._matches_attribute(other)
            and self._matches_profession(other)
        )

    def _merge_base_fields_from(self, other: 'Item') -> bool:
        changed = False

        if not self.is_missing_name(other.name) and self.name != other.name:
            self.name = other.name
            changed = True

        if self.is_unknown_item_type(self.item_type) and not self.is_unknown_item_type(other.item_type):
            self.item_type = other.item_type
            changed = True

        if int(self.model_id or 0) == 0 and int(other.model_id or 0) != 0:
            self.model_id = other.model_id
            changed = True

        if hasattr(self, 'required_materials'):
            existing_requirements = getattr(self, 'required_materials', None)
            candidate_requirements = getattr(other, 'required_materials', None)
            if isinstance(existing_requirements, CraftingRequirements) and isinstance(candidate_requirements, CraftingRequirements):
                if existing_requirements == CraftingRequirements() and candidate_requirements != CraftingRequirements():
                    self.required_materials = candidate_requirements
                    changed = True

        if hasattr(self, 'required_collectible'):
            existing_collectible = getattr(self, 'required_collectible', None)
            candidate_collectible = getattr(other, 'required_collectible', None)
            if not existing_collectible and candidate_collectible:
                self.required_collectible = candidate_collectible
                changed = True

        return changed

    @classmethod
    def upsert_into(cls, items: list['TItem'], candidate: 'TItem') -> bool:
        existing_index = next((index for index, existing in enumerate(items) if existing.matches(candidate)), -1)
        if existing_index >= 0:
            existing = items[existing_index]
            if candidate.specificity_rank > existing.specificity_rank:
                replacement = candidate
                replacement.update_from(existing)
                items[existing_index] = replacement
                changed = True
            else:
                changed = existing.update_from(candidate)
            if not changed:
                return False
        else:
            items.append(candidate)
            changed = True

        items.sort(key=lambda item: item.sort_key)
        return changed

    @classmethod
    def merge_items(cls, items: list['TItem'], candidates: Iterable['TItem']) -> bool:
        changed = False
        for candidate in candidates:
            if cls.upsert_into(items, candidate):
                changed = True
        return changed

    @classmethod
    def from_snapshot(cls, item: ItemSnapshot) -> 'Item':
        item_name = cls.snapshot_name(item)
        if item.is_weapon:
            return Weapon.from_snapshot(item, item_name=item_name)
        if item.is_armor:
            return Armor.from_snapshot(item, item_name=item_name)
        return cls(
            name=item_name,
            item_type=item.item_type,
            model_id=item.model_id,
        )

    def matches(self, other: object) -> bool:
        return isinstance(other, Item) and self._matches_identity(other)

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Item):
            return False
        return self._merge_base_fields_from(other)

    @staticmethod        
    def _deserialize_item(data: dict, default_cls: Optional[type['Item']] = None) -> 'Item':
        default_cls = default_cls or Item
        kind = str(data.get('kind', '') or '')
        item_cls = ITEM_KIND_MAP.get(kind)
        if item_cls is None:
            if 'required_collectible' in data:
                if 'armor_rating' in data or 'profession' in data:
                    item_cls = CollectibleArmor
                elif 'requirement' in data or 'attribute' in data or 'damage' in data:
                    item_cls = CollectibleWeapon
                else:
                    item_cls = CollectorItem
            elif 'required_materials' in data:
                if 'armor_rating' in data or 'profession' in data:
                    item_cls = CraftableArmor
                elif 'requirement' in data or 'attribute' in data or 'damage' in data:
                    item_cls = CraftableWeapon
                else:
                    item_cls = CraftableItem
            elif 'armor_rating' in data or 'profession' in data:
                item_cls = Armor
            elif 'requirement' in data or 'attribute' in data or 'damage' in data:
                item_cls = Weapon
            else:
                item_cls = default_cls
        return item_cls.from_dict(data)

@dataclass
class Craftable:
    required_materials: CraftingRequirements = field(default_factory=CraftingRequirements, kw_only=True)

    def _craftable_to_dict(self) -> dict:
        return {
            'required_materials': self.required_materials.to_dict(),
        }

    @staticmethod
    def _craftable_from_dict(data: dict) -> dict[str, Any]:
        return {
            'required_materials': CraftingRequirements.from_dict(data.get('required_materials')),
        }
    
@dataclass
class Collectible:
    required_collectible: tuple[int, int] = field(default_factory=tuple[int, int], kw_only=True)

    def _collectible_to_dict(self) -> dict:
        return {
            'required_collectible': (str(int(self.required_collectible[0])), self.required_collectible[1]) if self.required_collectible else None,
        }

    @staticmethod
    def _collectible_from_dict(data: dict) -> dict[str, Any]:
        raw_collectible = data.get('required_collectible')
        if not raw_collectible:
            return {
                'required_collectible': tuple[int, int](),
            }
        return {
            'required_collectible': (int(raw_collectible[0]), int(raw_collectible[1])),
        }

@dataclass
class Weapon(Item):
    requirement: int = 0
    attribute: Attribute = Attribute.None_
    damage: Optional[tuple[int, int]] = None  # min, max
    energy: Optional[int] = None
    prefix: Optional[Upgrade] = None
    suffix: Optional[Upgrade] = None
    inscription: Optional[Upgrade] = None
    inherent: list[Upgrade] = field(default_factory=list)

    SERIALIZATION_KIND = 'weapon'

    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload.update(
            {
                'requirement': self.requirement,
                'attribute': self.attribute.name,
                'damage': [self.damage[0], self.damage[1]] if self.damage is not None and (self.damage[0] != 0 or self.damage[1] != 0) else None,
                'energy': self.energy,
                'prefix': Upgrade.to_dict(self.prefix) if self.prefix is not None else None,
                'suffix': Upgrade.to_dict(self.suffix) if self.suffix is not None else None,
                'inscription': Upgrade.to_dict(self.inscription) if self.inscription is not None else None,
                'inherent': [Upgrade.to_dict(upg) for upg in self.inherent if upg is not None],
            }
        )
        return payload

    @classmethod
    def _weapon_kwargs_from_dict(cls, data: dict) -> dict:
        
        def _deserialize_damage(data: dict[str, Any]) -> Optional[tuple[int, int]]:
            raw_damage = data.get('damage')
            if raw_damage is None:
                return None

            damage_entries = list(raw_damage)
            if len(damage_entries) < 2:
                return None

            minimum = int(damage_entries[0] or 0)
            maximum = int(damage_entries[1] or 0)
            if minimum == 0 and maximum == 0:
                return None

            return minimum, maximum

        def _get_upgrade(upgrade_data: object) -> Optional[Upgrade]:
            if upgrade_data is None:
                return None

            if isinstance(upgrade_data, str):
                try:
                    parsed_upgrade_data = json.loads(upgrade_data)
                except json.JSONDecodeError:
                    return None
                upgrade_data = parsed_upgrade_data

            if not isinstance(upgrade_data, dict):
                return None

            return Upgrade.from_dict(upgrade_data)
        
        def _get_upgrades(upgrades_data: list[dict]) -> list[Upgrade]:
            upgrades = []
            
            for entry in upgrades_data:
                if not isinstance(entry, dict):
                    continue
                
                upgrade = _get_upgrade(entry)
                if upgrade is not None:
                    upgrades.append(upgrade)
            
            return upgrades
        
        attribute_name = str(data.get('attribute', Attribute.None_.name))
        damage_data = _deserialize_damage(data)
        energy_data = data.get('energy', None)
        
        return {
            **Weapon._base_kwargs_from_dict(data),
            'requirement': int(data.get('requirement', 0) or 0),
            'attribute': Attribute[attribute_name] if attribute_name in Attribute.__members__ else Attribute.None_,
            'damage': damage_data,
            'energy': int(energy_data) if energy_data is not None else None,
            'prefix': _get_upgrade(data.get('prefix', {})),
            'suffix': _get_upgrade(data.get('suffix', {})),
            'inscription': _get_upgrade(data.get('inscription', {})),
            'inherent': _get_upgrades(data.get('inherent', [])),
        }
                
    @classmethod
    def from_dict(cls, data: dict) -> 'Weapon':
        return cls(**cls._weapon_kwargs_from_dict(data))

    @property
    def specificity_rank(self) -> int:
        return 3

    def has_specific_attribute(self) -> bool:
        return self.attribute != Attribute.None_

    def _matches_attribute(self, other: 'Item') -> bool:
        if not isinstance(other, Weapon):
            return True
        return (
            not self.has_specific_attribute()
            or not other.has_specific_attribute()
            or self.attribute == other.attribute
        )

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Weapon):
            return False

        changed = super().update_from(other)

        if self.requirement == 0 and other.requirement != 0:
            self.requirement = other.requirement
            changed = True
        if self.attribute == Attribute.None_ and other.attribute != Attribute.None_:
            self.attribute = other.attribute
            changed = True
        if (self.damage == (0, 0) or self.damage is None) and other.damage != (0, 0):
            self.damage = other.damage
            changed = True
        if self.energy is None and other.energy is not None:
            self.energy = other.energy
            changed = True
        if self.prefix is None and other.prefix is not None:
            self.prefix = other.prefix
            changed = True
        if self.suffix is None and other.suffix is not None:
            self.suffix = other.suffix
            changed = True
        if self.inscription is None and other.inscription is not None:
            self.inscription = other.inscription
            changed = True
        if not self.inherent and other.inherent:
            self.inherent = list(other.inherent)
            changed = True

        return changed

    @classmethod
    def from_snapshot(cls, item: ItemSnapshot, *, item_name: Optional[str] = None) -> 'Weapon':
        return cls(
            name=item_name if item_name is not None else cls.snapshot_name(item),
            item_type=item.item_type,
            model_id=item.model_id,
            requirement=item.requirement,
            attribute=item.attribute,
            damage=(item.min_damage, item.max_damage),
            energy=item.energy,
            prefix=item.prefix,
            suffix=item.suffix,
            inscription=item.inscription,
            inherent=list(item.inherents or []),
        )

@dataclass
class Armor(Item):
    armor_rating: int = 0
    profession: Profession = Profession._None

    SERIALIZATION_KIND = 'armor'
    
    def to_dict(self) -> dict:
        payload = super().to_dict()
        payload.update(
            {
                'armor_rating': self.armor_rating,
                'profession': self.profession.name,
            }
        )
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> 'Armor':
        profession_name = str(data.get('profession', Profession._None.name))
        return cls(
            **Armor._base_kwargs_from_dict(data),
            armor_rating=int(data.get('armor_rating', 0) or 0),
            profession=Profession[profession_name] if profession_name in Profession.__members__ else Profession._None,
        )

    @property
    def specificity_rank(self) -> int:
        return 3

    def has_specific_profession(self) -> bool:
        return self.profession != Profession._None

    def _matches_profession(self, other: 'Item') -> bool:
        if not isinstance(other, Armor):
            return True
        return (
            not self.has_specific_profession()
            or not other.has_specific_profession()
            or self.profession == other.profession
        )

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Armor):
            return False

        changed = super().update_from(other)

        if self.armor_rating == 0 and other.armor_rating != 0:
            self.armor_rating = other.armor_rating
            changed = True
        if self.profession == Profession._None and other.profession != Profession._None:
            self.profession = other.profession
            changed = True

        return changed

    @classmethod
    def from_snapshot(cls, item: ItemSnapshot, *, item_name: Optional[str] = None) -> 'Armor':
        profession = item.profession if item.profession not in (None, Profession._None) else _get_current_profession()
        return cls(
            name=item_name if item_name is not None else cls.snapshot_name(item),
            item_type=item.item_type,
            model_id=item.model_id,
            profession=profession,
            armor_rating=item.armor,
        )

@dataclass
class CraftableWeapon(Weapon, Craftable):
    SERIALIZATION_KIND = 'craftable_weapon'

    def to_dict(self) -> dict:
        payload = Weapon.to_dict(self)
        payload.update(self._craftable_to_dict())
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> 'CraftableWeapon':
        return cls(
            **cls._weapon_kwargs_from_dict(data),
            **Craftable._craftable_from_dict(data),
        )

    @classmethod
    def from_snapshot(cls, item: ItemSnapshot, *, item_name: Optional[str] = None) -> 'CraftableWeapon':
        return cls(
            **cls._weapon_kwargs_from_dict(Weapon.from_snapshot(item, item_name=item_name).to_dict()),
            required_materials=CraftingRequirements(),
        )

@dataclass
class CraftableArmor(Armor, Craftable):
    SERIALIZATION_KIND = 'craftable_armor'

    def to_dict(self) -> dict:
        payload = Armor.to_dict(self)
        payload.update(self._craftable_to_dict())
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> 'CraftableArmor':
        profession_name = str(data.get('profession', Profession._None.name))
        return cls(
            **Armor._base_kwargs_from_dict(data),
            armor_rating=int(data.get('armor_rating', 0) or 0),
            profession=Profession[profession_name] if profession_name in Profession.__members__ else Profession._None,
            **Craftable._craftable_from_dict(data),
        )

    @classmethod
    def from_snapshot(cls, item: ItemSnapshot, *, item_name: Optional[str] = None) -> 'CraftableArmor':
        armor = Armor.from_snapshot(item, item_name=item_name)
        return cls(
            **Armor._base_kwargs_from_dict(armor.to_dict()),
            armor_rating=armor.armor_rating,
            profession=armor.profession,
            required_materials=CraftingRequirements(),
        )

@dataclass
class CollectibleWeapon(Weapon, Collectible):
    SERIALIZATION_KIND = 'collectible_weapon'
            
    def to_dict(self) -> dict:
        payload = Weapon.to_dict(self)
        payload.update(self._collectible_to_dict())
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> 'CollectibleWeapon':
        return cls(
            **cls._weapon_kwargs_from_dict(data),
            **Collectible._collectible_from_dict(data),
        )

    @property
    def specificity_rank(self) -> int:
        return 4

    @classmethod
    def from_snapshot(
        cls,
        item: ItemSnapshot,
        *,
        required_collectible: tuple[int, int] | None = None,
        item_name: Optional[str] = None,
    ) -> 'CollectibleWeapon':
        return cls(
            **cls._weapon_kwargs_from_dict(Weapon.from_snapshot(item, item_name=item_name).to_dict()),
            required_collectible=required_collectible or tuple[int, int](),
        )

@dataclass
class CollectibleArmor(Armor, Collectible):
    SERIALIZATION_KIND = 'collectible_armor'

    def to_dict(self) -> dict:
        payload = Armor.to_dict(self)
        payload.update(self._collectible_to_dict())
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> 'CollectibleArmor':
        profession_name = str(data.get('profession', Profession._None.name))
        return cls(
            **Armor._base_kwargs_from_dict(data),
            armor_rating=int(data.get('armor_rating', 0) or 0),
            profession=Profession[profession_name] if profession_name in Profession.__members__ else Profession._None,
            **Collectible._collectible_from_dict(data),
        )

    @property
    def specificity_rank(self) -> int:
        return 4

    @classmethod
    def from_snapshot(
        cls,
        item: ItemSnapshot,
        *,
        required_collectible: tuple[int, int] | None = None,
        item_name: Optional[str] = None,
    ) -> 'CollectibleArmor':
        armor = Armor.from_snapshot(item, item_name=item_name)
        return cls(
            **Armor._base_kwargs_from_dict(armor.to_dict()),
            armor_rating=armor.armor_rating,
            profession=armor.profession,
            required_collectible=required_collectible or tuple[int, int](),
        )

@dataclass
class CollectorItem(Item, Collectible):
    SERIALIZATION_KIND = 'collector_item'

    @property
    def specificity_rank(self) -> int:
        return 2

    def to_dict(self) -> dict:
        payload = Item.to_dict(self)
        payload.update(self._collectible_to_dict())
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> 'CollectorItem':
        return cls(
            **Item._base_kwargs_from_dict(data),
            **Collectible._collectible_from_dict(data),
        )

    @classmethod
    def from_snapshot(
        cls,
        item: ItemSnapshot,
        *,
        required_collectible: tuple[int, int] | None = None,
        item_name: Optional[str] = None,
    ) -> 'CollectorItem':
        return cls(
            name=item_name if item_name is not None else cls.snapshot_name(item),
            item_type=item.item_type,
            model_id=item.model_id,
            required_collectible=required_collectible or tuple[int, int](),
        )

@dataclass
class CraftableItem(Item, Craftable):
    SERIALIZATION_KIND = 'craftable_item'

    def to_dict(self) -> dict:
        payload = Item.to_dict(self)
        payload.update(self._craftable_to_dict())
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> 'CraftableItem':
        return cls(
            **Item._base_kwargs_from_dict(data),
            **Craftable._craftable_from_dict(data),
        )

    @classmethod
    def from_snapshot(cls, item: ItemSnapshot, *, item_name: Optional[str] = None) -> 'CraftableItem | CraftableWeapon | CraftableArmor':
        item_name = item_name if item_name is not None else cls.snapshot_name(item)
        if item.is_weapon:
            return CraftableWeapon.from_snapshot(item, item_name=item_name)
        if item.is_armor:
            return CraftableArmor.from_snapshot(item, item_name=item_name)
        return cls(
            name=item_name,
            item_type=item.item_type,
            model_id=item.model_id,
        )


ITEM_KIND_MAP = {
    Item.SERIALIZATION_KIND: Item,
    Weapon.SERIALIZATION_KIND: Weapon,
    Armor.SERIALIZATION_KIND: Armor,
    CraftableItem.SERIALIZATION_KIND: CraftableItem,
    CraftableWeapon.SERIALIZATION_KIND: CraftableWeapon,
    CraftableArmor.SERIALIZATION_KIND: CraftableArmor,
    CollectorItem.SERIALIZATION_KIND: CollectorItem,
    CollectibleWeapon.SERIALIZATION_KIND: CollectibleWeapon,
    CollectibleArmor.SERIALIZATION_KIND: CollectibleArmor,
}


TItem = TypeVar('TItem', bound=Item)

@dataclass
class AgentEntity:
    name: str = ''
    model_id: int = 0
    encoded_name: bytes = b''
    allegiance : Allegiance = Allegiance.Neutral
    required_title_id: Optional[TitleID] = None
    required_title_rank: Optional[int] = None
    required_faction: Optional[FactionRequirement] = None
    last_collection_had_pending_names: bool = field(default=False, repr=False, compare=False)
    unreachable: Optional[bool] = None

    def _base_to_dict(self) -> dict:
        return {
            'name': self.name,
            'encoded_name': list(self.encoded_name),
            'model_id': self.model_id,
            'allegiance': self.allegiance.name,
            'required_title_id': self.required_title_id.name if self.required_title_id is not None else None,
            'required_title_rank': self.required_title_rank,
            'required_faction': self.required_faction.name if self.required_faction is not None else None,
            'unreachable': self.unreachable,
        }

    @staticmethod
    def _base_from_dict(data: dict) -> dict:
        allegiance_name = str(data.get('allegiance', Allegiance.Neutral.name))
        raw_title_name = data.get('required_title_id', None)
        raw_faction_name = data.get('required_faction', None)
        title_name = str(raw_title_name) if raw_title_name is not None else ''
        faction_name = str(raw_faction_name) if raw_faction_name is not None else ''

        required_title_id: Optional[TitleID] = None
        if title_name and title_name != TitleID._None.name and title_name in TitleID.__members__:
            required_title_id = TitleID[title_name]

        required_faction: Optional[FactionRequirement] = None
        if faction_name and faction_name != FactionRequirement.None_.name and faction_name in FactionRequirement.__members__:
            required_faction = FactionRequirement[faction_name]

        required_title_rank_raw = data.get('required_title_rank', None)
        required_title_rank = None if required_title_rank_raw is None else int(required_title_rank_raw or 0)
        if required_title_id is None or required_title_rank == 0:
            required_title_rank = None

        return {
            'name': str(data.get('name', '')),
            'encoded_name': bytes(data.get('encoded_name', [])),
            'model_id': int(data.get('model_id', 0) or 0),
            'allegiance': Allegiance[allegiance_name] if allegiance_name in Allegiance.__members__ else Allegiance.Neutral,
            'required_title_id': required_title_id,
            'required_title_rank': required_title_rank,
            'required_faction': required_faction,
            'unreachable': data.get('unreachable', None),
        }

    def service_label(self) -> str:
        return self.__class__.__name__

    def interaction_label(self) -> str:
        restrictions: list[str] = []
        if self.required_title_id is not None and self.required_title_rank is not None and self.required_title_rank > 0:
            restrictions.append(f'{TITLE_NAME.get(int(self.required_title_id), self.required_title_id.name)} r{self.required_title_rank}')
        if self.required_faction is not None and self.required_faction != FactionRequirement.None_:
            restrictions.append(self.required_faction.name)
        return ', '.join(restrictions) if restrictions else 'Open'

    def HasMapUnlocked(self) -> bool:
        return True

    def GetMapIDs(self) -> list[int]:
        return []

    def GetDisplayMapID(self) -> int:
        map_ids = self.GetMapIDs()
        return map_ids[0] if map_ids else 0

    def GetDisplayPosition(self) -> tuple[float, float]:
        return (0.0, 0.0)

    def HasStationaryData(self) -> bool:
        return False

    def GetAgentId(self) -> int:
        return 0

    def MoveTo(self):
        return

    def CanInteract(self) -> bool:        
        
        if self.required_faction is not None and self.required_faction != FactionRequirement.None_ and not self._meets_faction_requirement(self.required_faction):
            return False
        
        if self.required_title_id is not None and self.required_title_rank is not None and self.required_title_rank > 0:
            return self._get_title_rank(self.required_title_id) >= self.required_title_rank
        
        if self.unreachable is not None:
            return not self.unreachable
        
        return True


    def _get_title_rank(self, title_id: TitleID) -> int:
        title = Player.GetTitle(int(title_id))
        if title is None:
            return 0

        tiers = TITLE_TIERS.get(int(title_id), [])
        if tiers:
            return sum(1 for tier in tiers if title.current_points >= tier.required)
        return int(title.current_title_tier_index or 0)

    def _meets_faction_requirement(self, requirement: FactionRequirement) -> bool:
        kurzick_current = int(Player.GetKurzickData()[0] or 0)
        luxon_current = int(Player.GetLuxonData()[0] or 0)
        if requirement == FactionRequirement.Kurzick:
            return kurzick_current > luxon_current
        if requirement == FactionRequirement.Luxon:
            return luxon_current > kurzick_current
        return True
    
    def _service_window_is_open(self) -> bool:
        return CrafterWindow.IsOpen()

    def _close_service_window(self):
        CrafterWindow.Close()

    def _get_offered_items(self) -> list[int]:
        offered_items = MerchantTrading.Trading.Crafter.GetOfferedItems()
        return list(offered_items or [])

    @staticmethod
    def _normalize_name(name: str) -> str:
        return ''.join(character.lower() for character in name if character.isalnum())

    @staticmethod
    def _log_collection_result(crafter_name: str, collected_count: int, item_label: str):
        if collected_count > 0:
            PySystem.Console.Log(MODULE_NAME, f"Collected {collected_count} {item_label} entries from '{crafter_name}'.", PySystem.Console.MessageType.Success)

    def _merge_item_collection(self, items: list[TItem], candidates: Iterable[TItem]) -> bool:
        return Item.merge_items(items, candidates)

    def _collect_simple_items(
        self,
        items: list[TItem],
        *,
        builder: Callable[[ItemSnapshot, str], TItem],
        item_label: str,
    ) -> bool:
        self.last_collection_had_pending_names = False
        if not self.IsCrafterOpen():
            return False

        snapshots = [ItemSnapshot.from_item_id(item_id) for item_id in self._get_offered_items()]
        collected_count = 0
        pending_name_update = False

        for snapshot in snapshots:
            if snapshot is None or not snapshot.is_valid:
                continue

            item_name = Item.snapshot_name(snapshot)
            if not item_name:
                pending_name_update = True
                continue

            if Item.upsert_into(items, builder(snapshot, item_name)):
                collected_count += 1

        self._log_collection_result(self.name, collected_count, item_label)
        self.last_collection_had_pending_names = pending_name_update
        if pending_name_update:
            PySystem.Console.Log(MODULE_NAME, f"Some collected items from '{self.name}' are missing names and will be updated once the names are available. Please collect from this crafter again...", PySystem.Console.MessageType.Warning)
        return collected_count > 0

    def IsCrafterOpen(self) -> bool:
        return False

    def CloseCrafter(self):
        if self._service_window_is_open():
            self._close_service_window()

    def CollectData(self) -> bool:
        return False

    def GetCollectedCount(self) -> int:
        return 0

    def GetCollectionSummary(self) -> str:
        return 'N/A'

    def matches(self, other: object) -> bool:
        if not isinstance(other, AgentEntity) or type(self) is not type(other):
            return False

        if self.model_id != 0 and other.model_id != 0:
            return self.model_id == other.model_id and self.allegiance == other.allegiance

        return self._normalize_name(self.name) == self._normalize_name(other.name) and self.allegiance == other.allegiance

    def update_from(self, other: object) -> bool:
        if not isinstance(other, AgentEntity):
            return False

        changed = False

        if not self.name and other.name:
            self.name = other.name
            changed = True

        if self.model_id == 0 and other.model_id != 0:
            self.model_id = other.model_id
            changed = True

        if not self.encoded_name and other.encoded_name:
            self.encoded_name = other.encoded_name
            changed = True

        if self.allegiance == Allegiance.Neutral and other.allegiance != Allegiance.Neutral:
            self.allegiance = other.allegiance
            changed = True

        if self.required_title_id is None and other.required_title_id is not None:
            self.required_title_id = other.required_title_id
            changed = True

        if self.required_title_rank is None and other.required_title_rank is not None:
            self.required_title_rank = other.required_title_rank
            changed = True

        if self.required_faction is None and other.required_faction is not None:
            self.required_faction = other.required_faction
            changed = True

        if self.unreachable is None and other.unreachable is not None:
            self.unreachable = other.unreachable
            changed = True

        return changed

@dataclass
class FoeSpawn:
    map_id: int
    position: tuple[float, float]
    level: int
    has_boss_aura: bool
    
    def to_dict(self) -> dict:
        return {
            'map_id': self.map_id,
            'position': [self.position[0], self.position[1]],
            'level': self.level,
            'has_boss_aura': self.has_boss_aura,
        }
        
    @staticmethod
    def from_dict(data: dict) -> 'FoeSpawn':
        return FoeSpawn(
            map_id=int(data.get('map_id', 0) or 0),
            position=(
                float(data.get('position', [0.0, 0.0])[0] or 0.0),
                float(data.get('position', [0.0, 0.0])[1] or 0.0),
            ),
            level=int(data.get('level', 0) or 0),
            has_boss_aura=bool(data.get('has_boss_aura', False)),
        )
    
    def matches(self, other: object) -> bool:
        if not isinstance(other, FoeSpawn):
            return False
        
        return self.map_id == other.map_id and self.level == other.level and self.has_boss_aura == other.has_boss_aura and Utils.Distance(self.position, other.position) < Range.Earshot.value
    
@dataclass
class Foe(AgentEntity):
    primary_profession: Optional[Profession] = None
    secondary_profession: Optional[Profession] = None
    spawns: dict[int, list[FoeSpawn]] = field(default_factory=dict)
    skills: dict[int, list[int]] = field(default_factory=dict)
    
    def __post_init__(self):
        self.allegiance = Allegiance.Enemy

    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload.update(
            {
                'primary_profession': self.primary_profession.name if self.primary_profession is not None else None,
                'secondary_profession': self.secondary_profession.name if self.secondary_profession is not None else None,
                'spawns': {map_id: [spawn.to_dict() for spawn in spawns] for map_id, spawns in self.spawns.items()},
                'skills': self.skills,
            }
        )
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Foe':
        raw_primary_name = data.get('primary_profession', None)
        raw_secondary_name = data.get('secondary_profession', None)
        primary_name = str(raw_primary_name) if raw_primary_name is not None else ''
        secondary_name = str(raw_secondary_name) if raw_secondary_name is not None else ''
        raw_spawns = data.get('spawns', {})
        spawns: dict[int, list[FoeSpawn]] = {}
        for map_id, spawn_data in raw_spawns.items():
            parsed_map_id = int(map_id)
            if isinstance(spawn_data, list):
                spawns[parsed_map_id] = [FoeSpawn.from_dict(entry) for entry in spawn_data if isinstance(entry, dict)]
            elif isinstance(spawn_data, dict):
                spawns[parsed_map_id] = [FoeSpawn.from_dict(spawn_data)]

        raw_skills = data.get('skills', {})
        skills: dict[int, list[int]] = {}
        for level, skill_ids in dict(raw_skills or {}).items():
            try:
                parsed_level = int(level)
            except (TypeError, ValueError):
                continue

            normalized_skill_ids: list[int] = []
            for skill_id in list(skill_ids or []):
                try:
                    parsed_skill_id = int(skill_id)
                except (TypeError, ValueError):
                    continue
                if parsed_skill_id not in normalized_skill_ids:
                    normalized_skill_ids.append(parsed_skill_id)

            skills[parsed_level] = normalized_skill_ids
            
        return Foe(
            **AgentEntity._base_from_dict(data),
            primary_profession=Profession[primary_name] if primary_name and primary_name != Profession._None.name and primary_name in Profession.__members__ else None,
            secondary_profession=Profession[secondary_name] if secondary_name and secondary_name != Profession._None.name and secondary_name in Profession.__members__ else None,
            spawns=spawns,
            skills=skills,
        )

    def GetCollectedCount(self) -> int:
        return sum(len(spawns) for spawns in self.spawns.values())

    def GetCollectionSummary(self) -> str:
        primary = self.primary_profession.name if self.primary_profession is not None else '?'
        secondary = self.secondary_profession.name if self.secondary_profession is not None else '?'
        return f'{self.GetCollectedCount()} spawn(s) / {primary}-{secondary}'

    def GetMapIDs(self) -> list[int]:
        return list(self.spawns.keys())

    def HasStationaryData(self) -> bool:
        return bool(self.spawns)

    def matches(self, other: object) -> bool:
        if not isinstance(other, Foe):
            return False

        if self.model_id != 0 and other.model_id != 0 and self.model_id != other.model_id:
            return False

        same_name = self._normalize_name(self.name) == self._normalize_name(other.name)
        same_primary = self.primary_profession in (None, other.primary_profession) or other.primary_profession is None
        same_secondary = self.secondary_profession in (None, other.secondary_profession) or other.secondary_profession is None
        return same_name and same_primary and same_secondary

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Foe):
            return False

        changed = AgentEntity.update_from(self, other)

        if self.primary_profession is None and other.primary_profession is not None:
            self.primary_profession = other.primary_profession
            changed = True

        if self.secondary_profession is None and other.secondary_profession is not None:
            self.secondary_profession = other.secondary_profession
            changed = True

        if self._merge_spawn_positions(self.spawns, other.spawns):
            changed = True

        return changed
    
    def _merge_spawn_positions(self,
        existing_spawns: dict[int, list[FoeSpawn]],
        candidate_spawns: dict[int, list[FoeSpawn]],
    ) -> bool:
        changed = False

        for map_id, candidate_spawn_entries in candidate_spawns.items():
            existing_spawn_entries = existing_spawns.setdefault(int(map_id), [])

            for candidate_spawn in candidate_spawn_entries:
                existing_spawn = next(
                    (
                        spawn
                        for spawn in existing_spawn_entries
                        if spawn.matches(candidate_spawn)
                    ),
                    None,
                )

                if existing_spawn is None:
                    existing_spawn_entries.append(candidate_spawn)
                    changed = True
                    continue

                if existing_spawn.position == (0.0, 0.0) and candidate_spawn.position != (0.0, 0.0):
                    existing_spawn.position = candidate_spawn.position
                    changed = True

                if existing_spawn.level == 0 and candidate_spawn.level != 0:
                    existing_spawn.level = candidate_spawn.level
                    changed = True

                if not existing_spawn.has_boss_aura and candidate_spawn.has_boss_aura:
                    existing_spawn.has_boss_aura = candidate_spawn.has_boss_aura
                    changed = True

        return changed

@dataclass
class Chest(AgentEntity):
    primary_profession: Optional[Profession] = None
    secondary_profession: Optional[Profession] = None
    spawns: dict[int, list[tuple[float, float]]] = field(default_factory=dict)

    def __post_init__(self):
        self.allegiance = Allegiance.Neutral

    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload.update(
            {
                'primary_profession': self.primary_profession.name if self.primary_profession is not None else None,
                'secondary_profession': self.secondary_profession.name if self.secondary_profession is not None else None,
                'spawns': self.spawns,
            }
        )
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Chest':
        raw_primary_name = data.get('primary_profession', None)
        raw_secondary_name = data.get('secondary_profession', None)
        primary_name = str(raw_primary_name) if raw_primary_name is not None else ''
        secondary_name = str(raw_secondary_name) if raw_secondary_name is not None else ''
        raw_spawns = data.get('spawns', {})
        spawns: dict[int, list[tuple[float, float]]] = {}
        for map_id, positions in dict(raw_spawns or {}).items():
            try:
                parsed_map_id = int(map_id)
            except (TypeError, ValueError):
                continue

            normalized_positions: list[tuple[float, float]] = []
            for position in list(positions or []):
                if not isinstance(position, (list, tuple)) or len(position) < 2:
                    continue
                normalized_positions.append((float(position[0] or 0.0), float(position[1] or 0.0)))

            spawns[parsed_map_id] = normalized_positions
                
        return Chest(
            **AgentEntity._base_from_dict(data),
            primary_profession=Profession[primary_name] if primary_name and primary_name != Profession._None.name and primary_name in Profession.__members__ else None,
            secondary_profession=Profession[secondary_name] if secondary_name and secondary_name != Profession._None.name and secondary_name in Profession.__members__ else None,
            spawns=spawns,
        )

    def GetCollectedCount(self) -> int:
        return len(self.spawns)

    def GetCollectionSummary(self) -> str:
        primary = self.primary_profession.name if self.primary_profession is not None else '?'
        secondary = self.secondary_profession.name if self.secondary_profession is not None else '?'
        return f'{len(self.spawns)} spawn(s) / {primary}-{secondary}'

    def GetMapIDs(self) -> list[int]:
        return list(self.spawns.keys())

    def HasStationaryData(self) -> bool:
        return bool(self.spawns)

    def matches(self, other: object) -> bool:
        if not isinstance(other, Chest):
            return False

        if self.encoded_name and other.encoded_name:
            return self.encoded_name == other.encoded_name

        if self.model_id != 0 and other.model_id != 0:
            return self.model_id == other.model_id

        return self._normalize_name(self.name) == self._normalize_name(other.name)

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Chest):
            return False

        changed = AgentEntity.update_from(self, other)

        if self.primary_profession is None and other.primary_profession is not None:
            self.primary_profession = other.primary_profession
            changed = True

        if self.secondary_profession is None and other.secondary_profession is not None:
            self.secondary_profession = other.secondary_profession
            changed = True

        if self._merge_spawn_positions(self.spawns, other.spawns):
            changed = True

        return changed
        
    def _merge_spawn_positions(
        self,
        existing_spawns: dict[int, list[tuple[float, float]]],
        candidate_spawns: dict[int, list[tuple[float, float]]],
    ) -> bool:
        changed = False

        for map_id, positions in candidate_spawns.items():
            existing_positions = existing_spawns.setdefault(int(map_id), [])
            for position in positions:
                normalized_position = (float(position[0]), float(position[1]))
                if normalized_position not in existing_positions:
                    existing_positions.append(normalized_position)
                    changed = True

        return changed

@dataclass
class StationaryNpc(AgentEntity):
    map_id: int = 0
    position: tuple[float, float] = (0.0, 0.0)

    def _base_to_dict(self) -> dict:
        payload = super()._base_to_dict()
        payload.update(
            {
                'map_id': self.map_id,
                'position': [self.position[0], self.position[1]],
            }
        )
        return payload

    @staticmethod
    def _base_from_dict(data: dict) -> dict:
        payload = AgentEntity._base_from_dict(data)
        position_data = list(data.get('position', [0.0, 0.0]))
        payload.update(
            {
                'map_id': int(data.get('map_id', 0) or 0),
                'position': (
                    float(position_data[0]) if len(position_data) > 0 else 0.0,
                    float(position_data[1]) if len(position_data) > 1 else 0.0,
                ),
            }
        )
        return payload

    def HasMapUnlocked(self) -> bool:
        return Map.IsMapUnlocked(self.map_id)

    def GetMapIDs(self) -> list[int]:
        return [self.map_id] if self.map_id != 0 else []

    def GetDisplayMapID(self) -> int:
        return self.map_id

    def GetDisplayPosition(self) -> tuple[float, float]:
        return self.position

    def HasStationaryData(self) -> bool:
        return self.position != (0.0, 0.0) and self.map_id != 0

    def GetAgentId(self) -> int:
        if not Routines.Checks.Map.IsMapReady():
            return 0

        if self.position == (0.0, 0.0):
            return 0

        agents = AgentArray.GetAgentArray()
        agents = AgentArray.Filter.ByDistance(agents, self.position, 100.0)

        for agent_id in agents:
            if agent_id is not None and Agent.GetModelID(agent_id) == self.model_id:
                return agent_id

        return 0

    def MoveTo(self):
        if not Routines.Checks.Map.IsMapReady():
            return

        if Map.GetBaseMapID() != Map.GetBaseMapID(self.map_id):
            if Map.IsMapUnlocked(self.map_id):
                Map.Travel(self.map_id)
                return
            PySystem.Console.Log(MODULE_NAME, f"Map '{Map.GetMapName(self.map_id)}' is not unlocked yet.", PySystem.Console.MessageType.Warning)
            return

        Player.Move(self.position[0], self.position[1])

        if not self.CanInteract():
            PySystem.Console.Log(MODULE_NAME, f"'{self.name}' requires {self.interaction_label()} before it will interact.", PySystem.Console.MessageType.Warning)
            return

        if (agent_id := self.GetAgentId()) != 0:
            Player.ChangeTarget(agent_id)
            Player.Interact(agent_id)

    def IsCrafterOpen(self) -> bool:
        if not Routines.Checks.Map.IsMapReady():
            return False

        if Map.GetBaseMapID() != Map.GetBaseMapID(self.map_id):
            return False

        agent_id = self.GetAgentId()
        if agent_id == 0:
            return False

        if Player.GetTargetID() != agent_id:
            return False

        return self._service_window_is_open()

    def matches(self, other: object) -> bool:
        if not isinstance(other, StationaryNpc) or type(self) is not type(other):
            return False

        if self.map_id != 0 and other.map_id != 0 and self.map_id != other.map_id:
            return False

        if self.model_id != 0 and other.model_id != 0:
            return self.model_id == other.model_id

        return self._normalize_name(self.name) == self._normalize_name(other.name)

    def update_from(self, other: object) -> bool:
        if not isinstance(other, StationaryNpc):
            return False

        changed = AgentEntity.update_from(self, other)

        if self.map_id == 0 and other.map_id != 0:
            self.map_id = other.map_id
            changed = True

        if self.position == (0.0, 0.0) and other.position != (0.0, 0.0):
            self.position = other.position
            changed = True

        return changed

@dataclass
class Ally(StationaryNpc):
    def __post_init__(self):
        self.allegiance = Allegiance.Ally

    def to_dict(self) -> dict:
        return self._base_to_dict()

    @staticmethod
    def from_dict(data: dict) -> 'Ally':
        return Ally(**StationaryNpc._base_from_dict(data))

    def GetCollectionSummary(self) -> str:
        return self.interaction_label()
        
@dataclass
class Merchant(Ally):
    items: list[Item] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload['items'] = [item.to_dict() for item in self.items]
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Merchant':
        return Merchant(
            **StationaryNpc._base_from_dict(data),
            items=[Item._deserialize_item(entry, Item) for entry in data.get('items', [])],
        )

    def _service_window_is_open(self) -> bool:
        return MerchantWindow.IsOpen()

    def _close_service_window(self):
        MerchantWindow.Close()

    def _get_offered_items(self) -> list[int]:
        return list(MerchantTrading.Trading.Merchant.GetOfferedItems() or [])

    def CollectData(self) -> bool:
        return self._collect_simple_items(
            self.items,
            builder=lambda snapshot, item_name: Item.from_snapshot(snapshot),
            item_label='merchant item',
        )

    def GetCollectedCount(self) -> int:
        return len(self.items)

    def GetCollectionSummary(self) -> str:
        return f'{len(self.items)} items / {self.interaction_label()}'

    def HasMissingData(self) -> bool:
        return not self.items or any(item.model_id == 0 or not item.name for item in self.items)

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Merchant):
            return False

        changed = StationaryNpc.update_from(self, other)
        if self._merge_item_collection(self.items, other.items):
            changed = True
        return changed
    
class TraderType(IntEnum):
    Unknown = auto() 
    Rune = auto() 
    Dye = auto() 
    Material = auto() 
    RareMaterial = auto()
    RareScroll = auto()
    Sigil = auto()
    
    @staticmethod
    def get_type_from_name(name: str) -> 'TraderType':
        name = name.lower()
        # name = name.replace('[', '').replace(']', '')
        
        if 'rune trader' in name:
            return TraderType.Rune
        if 'dye trader' in name:
            return TraderType.Dye
        if 'rare material trader' in name:
            return TraderType.RareMaterial
        if 'rare scroll trader' in name:
            return TraderType.RareScroll
        if 'sigil trader' in name:
            return TraderType.Sigil
        if 'material trader' in name:
            return TraderType.Material
        return TraderType.Unknown
    
@dataclass
class Trader(Ally):
    items: list[Item] = field(default_factory=list)
    _trader_type: TraderType = field(default=TraderType.Unknown, repr=False)
        
    @property
    def trader_type(self) -> TraderType:
        return self._trader_type
    
    @trader_type.setter
    def trader_type(self, value: TraderType):
        self._trader_type = value
        self.items = self._get_trader_items_by_type(value)
        
    def _get_trader_items_by_type(self, trader_type: TraderType) -> list[Item]:
        return []  # Placeholder for actual implementation to return items based on trader type, traders have a fixed set of items we don't need to ingame collect them

    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload['trader_type'] = self.trader_type.name
        payload['items'] = [item.to_dict() for item in self.items]
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Trader':
        trader_type_name = str(data.get('trader_type', TraderType.Unknown.name))
        trader = Trader(
            **StationaryNpc._base_from_dict(data),
            items=[Item._deserialize_item(entry, Item) for entry in data.get('items', [])],
            _trader_type=TraderType[trader_type_name] if trader_type_name in TraderType.__members__ else TraderType.Unknown,
        )
        return trader

    def _service_window_is_open(self) -> bool:
        return MerchantWindow.IsOpen()

    def _close_service_window(self):
        MerchantWindow.Close()

    def CollectData(self) -> bool:
        inferred_type = TraderType.get_type_from_name(self.name)
        if self.trader_type == TraderType.Unknown and inferred_type != TraderType.Unknown:
            self.trader_type = inferred_type
            return True
        return False

    def GetCollectedCount(self) -> int:
        return len(self.items)

    def GetCollectionSummary(self) -> str:
        return f'{self.trader_type.name} / {self.interaction_label()}'

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Trader):
            return False

        changed = StationaryNpc.update_from(self, other)

        if self.trader_type == TraderType.Unknown and other.trader_type != TraderType.Unknown:
            self.trader_type = other.trader_type
            changed = True

        if self._merge_item_collection(self.items, other.items):
            changed = True

        return changed
        
@dataclass
class Artisan(Ally):
    items: list[CraftableItem] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload['items'] = [item.to_dict() for item in self.items]
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Artisan':
        return Artisan(
            **StationaryNpc._base_from_dict(data),
            items=[cast(CraftableItem, CraftableItem._deserialize_item(entry, CraftableItem)) for entry in data.get('items', [])],
        )

    def CollectData(self) -> bool:
        return self._collect_simple_items(
            self.items,
            builder=lambda snapshot, item_name: cast(CraftableItem, CraftableItem.from_snapshot(snapshot, item_name=item_name)),
            item_label='craftable item',
        )

    def GetCollectedCount(self) -> int:
        return len(self.items)

    def GetCollectionSummary(self) -> str:
        return f'{len(self.items)} items'

    def HasMissingData(self) -> bool:
        return not self.items or any(item.model_id == 0 or not item.name for item in self.items)

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Artisan):
            return False

        changed = StationaryNpc.update_from(self, other)
        if self._merge_item_collection(self.items, other.items):
            changed = True
        return changed

@dataclass
class ConsumableCrafter(Ally):
    consumables: list[CraftableItem] = field(default_factory=list)
            
    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload['consumables'] = [item.to_dict() for item in self.consumables]
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'ConsumableCrafter':
        return ConsumableCrafter(
            **StationaryNpc._base_from_dict(data),
            consumables=[cast(CraftableItem, CraftableItem._deserialize_item(entry, CraftableItem)) for entry in data.get('consumables', [])],
        )

    def CollectData(self) -> bool:
        return self._collect_simple_items(
            self.consumables,
            builder=lambda snapshot, item_name: cast(CraftableItem, CraftableItem.from_snapshot(snapshot, item_name=item_name)),
            item_label='craftable item',
        )

    def GetCollectedCount(self) -> int:
        return len(self.consumables)

    def GetCollectionSummary(self) -> str:
        return f'{len(self.consumables)} consumables'

    def HasMissingData(self) -> bool:
        return not self.consumables or any(item.model_id == 0 or not item.name for item in self.consumables)

    def update_from(self, other: object) -> bool:
        if not isinstance(other, ConsumableCrafter):
            return False

        changed = StationaryNpc.update_from(self, other)
        if self._merge_item_collection(self.consumables, other.consumables):
            changed = True
        return changed

@dataclass
class Weaponsmith(Ally):
    weapons: list[CraftableWeapon] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload['weapons'] = [weapon.to_dict() for weapon in self.weapons]
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Weaponsmith':
        return Weaponsmith(
            **StationaryNpc._base_from_dict(data),
            weapons=[cast(CraftableWeapon, CraftableWeapon._deserialize_item(entry, CraftableWeapon)) for entry in data.get('weapons', [])],
        )

    def CollectData(self) -> bool:
        self.last_collection_had_pending_names = False
        if not self.IsCrafterOpen():
            return False

        items = [ItemSnapshot.from_item_id(item_id) for item_id in self._get_offered_items()]
        collected_count = 0
        pending_name_update = False

        for item in items:
            if item is None or not item.is_valid or not item.is_weapon:
                continue

            weapon_name = Item.snapshot_name(item)
            if not weapon_name:
                pending_name_update = True
                continue

            weapon = cast(CraftableWeapon, CraftableItem.from_snapshot(item, item_name=weapon_name))
            if Item.upsert_into(self.weapons, weapon):
                collected_count += 1

        self._log_collection_result(self.name, collected_count, 'weapon')
        self.last_collection_had_pending_names = pending_name_update
        if pending_name_update:
            PySystem.Console.Log(MODULE_NAME, f"Some collected items from '{self.name}' are missing names and will be updated once the names are available. Please collect from this crafter again...", PySystem.Console.MessageType.Warning)
        return collected_count > 0

    def GetCollectedCount(self) -> int:
        return len(self.weapons)

    def GetCollectionSummary(self) -> str:
        return f'{len(self.weapons)} weapons'

    def HasMissingData(self) -> bool:
        return (len(self.weapons) > 0 and any(weapon.model_id == 0 or not weapon.name for weapon in self.weapons))

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Weaponsmith):
            return False

        changed = StationaryNpc.update_from(self, other)
        if self._merge_item_collection(self.weapons, other.weapons):
            changed = True
        return changed

@dataclass
class Collector(Ally):
    items: list[Item] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload['items'] = [item.to_dict() for item in self.items]
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Collector':
        return Collector(
            **StationaryNpc._base_from_dict(data),
            items=[cast(Item, Item._deserialize_item(entry, CollectorItem)) for entry in data.get('items', [])],
        )

    def _service_window_is_open(self) -> bool:
        return CollectorWindow.IsOpen()

    def _close_service_window(self):
        CollectorWindow.Close()

    def _get_offered_items(self) -> list[int]:
        offered_items = MerchantTrading.Trading.Collector.GetOfferedItems()
        return list(offered_items or [])

    def _build_collectible_item_from_snapshot(
        self,
        item: ItemSnapshot,
        required_collectible: tuple[int, int] | None,
        *,
        item_name: Optional[str] = None,
    ) -> Item:
        item_name = item_name if item_name is not None else Item.snapshot_name(item)
        if item.is_weapon:
            return CollectibleWeapon.from_snapshot(
                item,
                required_collectible=required_collectible,
                item_name=item_name,
            )
        if item.is_armor:
            return CollectibleArmor.from_snapshot(
                item,
                required_collectible=required_collectible,
                item_name=item_name,
            )
        return CollectorItem.from_snapshot(
            item,
            required_collectible=required_collectible,
            item_name=item_name,
        )

    def CollectData(self) -> bool:
        self.last_collection_had_pending_names = False
        if not self.IsCrafterOpen():
            return False

        items = [ItemSnapshot.from_item_id(item_id) for item_id in self._get_offered_items()]
        collected_count = 0
        pending_name_update = False

        exchange_item = next(
            (
                entry.required_collectible
                for entry in self.items
                if isinstance(entry, Collectible) and entry.required_collectible
            ),
            None,
        )

        for item in items:
            if item is None or not item.is_valid:
                continue

            if exchange_item is not None and item.model_id == exchange_item[0]:
                continue

            item_name = Item.snapshot_name(item)
            if not item_name:
                pending_name_update = True
                continue
            
            collectible_item = cast(
                CollectibleWeapon | CollectibleArmor | CollectorItem,
                self._build_collectible_item_from_snapshot(item, exchange_item, item_name=item_name),
            )
            if Item.upsert_into(self.items, collectible_item):
                collected_count += 1

        self._log_collection_result(self.name, collected_count, 'collector')
        self.last_collection_had_pending_names = pending_name_update
        if pending_name_update:
            PySystem.Console.Log(MODULE_NAME, f"Some collected items from '{self.name}' are missing names and will be updated once the names are available. Please collect from this crafter again...", PySystem.Console.MessageType.Warning)
        return collected_count > 0

    def GetCollectedCount(self) -> int:
        return len(self.items)

    def GetCollectionSummary(self) -> str:
        unresolved = sum(
            1
            for item in self.items
            if isinstance(item, Collectible)
            and item.required_collectible
            and item.required_collectible[0] == 0
        )
        return f'{len(self.items)} items / {unresolved} unresolved'

    def HasMissingData(self) -> bool:
        profession =  _get_current_profession()
        armor_items = [item for item in self.items if isinstance(item, CollectibleArmor)]
        remaining_items = [item for item in self.items if not item in armor_items]       
        profession_armors = [item for item in armor_items if item.profession == profession]
        
        incomplete_profession_armors = [item for item in profession_armors if item.model_id == 0 or not item.name or item.armor_rating == 0]
        
        needs_profession_armor = len(incomplete_profession_armors) > 0
        has_non_armor_items = len(remaining_items) > 0
        incomplete_items = [item for item in remaining_items if item.model_id == 0 or not item.name]
        
        return needs_profession_armor or \
               (has_non_armor_items and bool(not self.items or len(incomplete_items) > 0))

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Collector):
            return False

        changed = StationaryNpc.update_from(self, other)
        if self._merge_item_collection(self.items, other.items):
            changed = True
        return changed

@dataclass
class Armorer(Ally):
    professions_armor_rating: dict[Profession, int] = field(default_factory=dict)
    armors: dict[Profession, list[CraftableArmor]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = self._base_to_dict()
        payload.update(
            {
                'professions_armor_rating': {
                profession.name: armor_rating
                for profession, armor_rating in self.professions_armor_rating.items()
                },
                'armors': {
                profession.name: [armor.to_dict() for armor in armors]
                for profession, armors in self.armors.items()
                },
            }
        )
        return payload

    @staticmethod
    def from_dict(data: dict) -> 'Armorer':
        professions_armor_rating: dict[Profession, int] = {}
        for profession_name, armor_rating in dict(data.get('professions_armor_rating', {})).items():
            if profession_name not in Profession.__members__:
                continue
            professions_armor_rating[Profession[profession_name]] = int(armor_rating or 0)

        armors: dict[Profession, list[CraftableArmor]] = {}
        for profession_name, entries in dict(data.get('armors', {})).items():
            if profession_name not in Profession.__members__:
                continue
            profession = Profession[profession_name]
            armors[profession] = [cast(CraftableArmor, CraftableArmor._deserialize_item(entry, CraftableArmor)) for entry in data.get('armors', {}).get(profession_name, [])]

        return Armorer(
            **StationaryNpc._base_from_dict(data),
            professions_armor_rating=professions_armor_rating,
            armors=armors,
        )
    

    def _build_craftable_armor_from_snapshot(self, item: ItemSnapshot) -> CraftableArmor:
        return cast(CraftableArmor, CraftableItem.from_snapshot(item))

    def CollectData(self) -> bool:
        self.last_collection_had_pending_names = False
        if not self.IsCrafterOpen():
            return False
        
        items = [ItemSnapshot.from_item_id(item_id) for item_id in self._get_offered_items()]
        collected_count = 0
        offered_type_counts: dict[tuple[Profession, ItemType], int] = {}

        for item in items:
            if item is None or not item.is_valid or not item.is_armor:
                continue
            profession = item.profession if item.profession not in (None, Profession._None) else _get_current_profession()
            if profession in (None, Profession._None):
                continue
            offer_key = (profession, item.item_type)
            offered_type_counts[offer_key] = offered_type_counts.get(offer_key, 0) + 1

        pending_name_update = False
        for item in items:
            if item is None or not item.is_valid or not item.is_armor:
                continue

            profession = item.profession if item.profession not in (None, Profession._None) else _get_current_profession()
            if profession in (None, Profession._None):
                continue

            armor_name = Item.snapshot_name(item)
            if not armor_name:
                pending_name_update = True
                continue

            armor = self._build_craftable_armor_from_snapshot(item)
            armor.name = armor_name
            armor.armor_rating = int(self.professions_armor_rating.get(profession, 0) or 0)
            armor.profession = profession
            generic_armors = {
                'Crown',
                'Bandana',
                'Blindfold',
                'Dread Mask',
                'Highlander Woad',
                'Mask of the Mo Zing',
                'Norn Woad',
                'Slim Spectacles',
                'Spectacles',
                'Tinted Spectacles',
                'Chaos Gloves',
                'Destroyer Gauntlets',
                'Dragon Gauntlets',
                'Glacial Gauntlets',
                'Stone Gauntlets',
            }
            armor_key = (armor.profession, armor.item_type)
            same_slot_entries = [
                existing_armor
                for entries in self.armors.values()
                for existing_armor in entries
                if (
                    getattr(existing_armor, 'profession', None) == armor.profession
                    and (
                        existing_armor.item_type == armor.item_type
                        or Item.is_unknown_item_type(existing_armor.item_type)
                        or Item.is_unknown_item_type(armor.item_type)
                    )
                )
            ]
            unresolved_same_slot_entries = [
                existing_armor
                for existing_armor in same_slot_entries
                if existing_armor.model_id == 0 or existing_armor.armor_rating == 0 or Item.is_missing_name(existing_armor.name)
            ]

            existing: CraftableArmor | None = None
            if offered_type_counts.get(armor_key, 0) == 1:
                if len(unresolved_same_slot_entries) == 1:
                    existing = unresolved_same_slot_entries[0]
                elif len(same_slot_entries) == 1:
                    existing = same_slot_entries[0]

            if existing is None:
                candidate_words = self._split_item_name_words(armor.name)
                candidate_core_words = self._strip_elite_prefix(candidate_words)
                candidate_first_word = candidate_core_words[0] if candidate_core_words else ''

                scored_matches: list[tuple[int, CraftableArmor]] = []
                for existing_armor in same_slot_entries:
                    if existing_armor.name in generic_armors:
                        continue

                    existing_words = self._split_item_name_words(existing_armor.name)
                    existing_core_words = self._strip_elite_prefix(existing_words)
                    existing_first_word = existing_core_words[0] if existing_core_words else ''
                    shared_words = set(candidate_core_words) & set(existing_core_words)
                    score = 0

                    if candidate_first_word and candidate_first_word == existing_first_word:
                        score += 5
                    if shared_words:
                        score += len(shared_words) * 2
                    if armor.name.lower() in existing_armor.name.lower() or existing_armor.name.lower() in armor.name.lower():
                        score += 1

                    if score > 0:
                        scored_matches.append((score, existing_armor))

                if scored_matches:
                    scored_matches.sort(key=lambda entry: entry[0], reverse=True)
                    best_score = scored_matches[0][0]
                    best_matches = [match for score, match in scored_matches if score == best_score]
                    if len(best_matches) == 1:
                        existing = best_matches[0]

            if existing is not None:
                if existing.update_from(armor):
                    collected_count += 1
                else:
                    # Keep these aligned even when nothing else changed so future identity matches stay stable.
                    existing.name = armor_name
                    existing.model_id = item.model_id
                continue

            if self._upsert_craftable_armor(armor):
                collected_count += 1

        self._log_collection_result(self.name, collected_count, 'armor')
        self.last_collection_had_pending_names = pending_name_update
        if pending_name_update:
            PySystem.Console.Log(MODULE_NAME, f"Some collected items from '{self.name}' are missing names and will be updated once the names are available. Please collect from this crafter again...", PySystem.Console.MessageType.Warning)
            
        return collected_count > 0

    def _upsert_craftable_armor(self, armor: CraftableArmor) -> bool:
        entries = self.armors.setdefault(armor.profession, [])
        existing_index = next(
            (
                index for index, existing in enumerate(entries)
                if existing.matches(armor)
            ),
            -1,
        )

        if existing_index >= 0:
            existing = entries[existing_index]
            if not existing.update_from(armor):
                return False
        else:
            entries.append(armor)

        entries.sort(key=lambda entry: entry.sort_key)
        return True

    @staticmethod
    def _split_item_name_words(name: str) -> list[str]:
        return [word for word in ''.join(character.lower() if character.isalnum() else ' ' for character in name).split() if word]

    @staticmethod
    def _strip_elite_prefix(words: list[str]) -> list[str]:
        if words and words[0] == 'elite':
            return words[1:]
        return words
        
    def GetCollectedCount(self) -> int:
        return sum(len(entries) for entries in self.armors.values())

    def HasMissingData(self) -> bool:        
        if self.position == (0.0, 0.0) or self.map_id == 0 or self.model_id == 0:
            return True
        
        profession = _get_current_profession()
        if profession == Profession._None or profession not in self.professions_armor_rating:
            return False
        armors = self.armors.get(profession, [])
        return not armors or any(not armor.name or armor.name.startswith('Model') or armor.model_id == 0 or armor.armor_rating == 0 for armor in armors)

    def update_from(self, other: object) -> bool:
        if not isinstance(other, Armorer):
            return False

        changed = StationaryNpc.update_from(self, other)

        for profession, armor_rating in other.professions_armor_rating.items():
            if int(self.professions_armor_rating.get(profession, 0) or 0) == 0 and int(armor_rating or 0) != 0:
                self.professions_armor_rating[profession] = armor_rating
                changed = True

        for profession, armors in other.armors.items():
            if profession not in self.armors:
                self.armors[profession] = list(armors)
                changed = True
                continue

            if self._merge_item_collection(self.armors[profession], armors):
                changed = True

        return changed
    
def _get_current_profession() -> Profession:
    agent = Agent.GetAgentByID(Player.GetAgentID())
    living_agent = agent.GetAsAgentLiving() if agent is not None else None

    if living_agent is None:
        return Profession._None

    try:
        return Profession(living_agent.primary)
    except Exception:
        return Profession._None