
from dataclasses import dataclass
from typing import Callable, Optional

import Py4GW
import PyItem

from Py4GWCoreLib.Inventory import Inventory
from Py4GWCoreLib.Item import Item
from Py4GWCoreLib.enums_src.GameData_enums import Attribute, Profession
from Py4GWCoreLib.enums_src.Item_enums import INVENTORY_BAGS, NICK_CYCLE_COUNT, STORAGE_BAGS, Bags, ItemType
from Py4GWCoreLib.enums_src.Region_enums import ServerLanguage
from Sources.frenkeyLib.item_data.ItemData import ItemData
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot
from Py4GWCoreLib.native_src.internals import string_table
from Py4GWCoreLib.py4gwcorelib_src.Timer import ThrottledTimer
from Sources.frenkeyLib.Core.data_dict import DataDict
from Sources.frenkeyLib.Core.json_serializable import T_DICT_KEY, T_SERIALIZABLE_VALUE
from Sources.frenkeyLib.DataCollector.collectors.base_collectors import BaseCollector
from Py4GWCoreLib import Merchant as Py4GW_Merchant


@dataclass
class ModelIdDict(dict[int, ItemData]):
    def to_dict(self) -> dict:
        return {
            str(key): value.to_dict()
            for key, value in self.items()            
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ModelIdDict':
        instance = cls()
        
        for key, value in data.items():
            instance[int(key)] = ItemData.from_dict(value)
        
        return instance

    def update_from(self, other: object) -> bool:
        if not isinstance(other, ModelIdDict):
            return False

        changed = False

        for model_id, candidate in other.items():
            existing = self.get(model_id)
            if existing is None:
                self[model_id] = candidate
                changed = True
                continue
            
            changed = existing.update_from(candidate) or changed
            
        return changed
    
class ItemCollector(BaseCollector, DataDict[ItemType, ModelIdDict]):
    def __init__(self,
        get_local_path: Callable[..., str],
        get_default_path: Callable[..., str],
        *,
        version: str = '1.0',
        value_type: Optional[type[T_SERIALIZABLE_VALUE]] = None,
        key_decoder: Optional[Callable[[str], T_DICT_KEY]] = None,
        key_encoder: Optional[Callable[[T_DICT_KEY], str]] = None,
    ):
        resolved_key_decoder = key_decoder or (lambda key: ItemType[key] if key in ItemType.__members__ else ItemType.Unknown)
        resolved_key_encoder = key_encoder or (lambda key: key.name if isinstance(key, ItemType) else str(key))
        super().__init__(
            get_local_path,
            get_default_path,
            version=version,
            value_type=value_type,
            key_decoder=resolved_key_decoder,
            key_encoder=resolved_key_encoder,
        )
        self.Nick_Items: dict[int, ItemData] = {}
        self.Nick_Cycle: list[ItemData] = []
        
        self.load()
        
        self.storage_checked_for_context = False
        self.force_scan = False
        self.checked_model_keys: list[tuple[ItemType, int]] = []
        
    @property
    def all_items(self) -> list[ItemData]:
        return [item for type_dict in self.values() for item in type_dict.values()]
    
    def _flush_cache(self):
        super()._flush_cache()
        self.storage_checked_for_context = False
        self.force_scan = False
        self.checked_model_keys.clear()
    
    def _collect(self):        
        if not self.storage_checked_for_context:
            self._scan_bags(STORAGE_BAGS)
            self.storage_checked_for_context = True

        
        self.force_inventory_scan = False
        self._scan_bags(INVENTORY_BAGS)        
        self._scan_trader_items()
        self._scan_hovered_item()
        
    def _scan_bags(self, bags: list[Bags]):
        import PyInventory

        snapshot: dict[Bags, dict[int, Optional[ItemSnapshot]]] = {}

        for bag in bags:
            inventory_bag = PyInventory.Bag(bag.value, bag.name)
            bag_snapshot: dict[int, Optional[ItemSnapshot]] = {}

            bag_size = inventory_bag.GetSize()

            for slot in range(bag_size):
                bag_snapshot[slot] = None

            for entry in inventory_bag.GetItems():
                slot = entry.get("slot", -1)
                py_item = PyItem.PyItem(entry["item_id"])
                bag_snapshot[slot] = ItemSnapshot.from_item_id(entry["item_id"], py_item)

            snapshot[bag] = bag_snapshot

        items = [item for bag in snapshot.values() for item in bag.values() if item is not None]

        for item in items:
            self._collect_item(item)

    def _scan_trader_items(self):
        offered_items = Py4GW_Merchant.Trading.Merchant.GetOfferedItems()
        offered_items = offered_items + Py4GW_Merchant.Trading.Trader.GetOfferedItems()
        offered_items = offered_items + Py4GW_Merchant.Trading.Trader.GetOfferedItems2()
        offered_items = offered_items + Py4GW_Merchant.Trading.Crafter.GetOfferedItems()
        offered_items = offered_items + Py4GW_Merchant.Trading.Collector.GetOfferedItems()

        for item_id in offered_items:
            item = ItemSnapshot.from_item_id(item_id) if item_id else None
            if item is None:
                continue
            self._collect_item(item)

    def _scan_hovered_item(self):
        hovered_item_id = Inventory.GetHoveredItemID()
        if not hovered_item_id:
            return

        item = ItemSnapshot.from_item_id(hovered_item_id)
        if item is None or not item.is_valid:
            return

        self._collect_item(item)

    def _collect_item(self, item: ItemSnapshot):
        if not item.is_valid or item.model_id <= 0 or item.item_type == ItemType.Unknown:
            return

        model_key = (item.item_type, item.model_id)
        item_data = self.get_or_create_item_data(item.item_type, item.model_id)
        if (item.id in self.checked_ids or model_key in self.checked_model_keys) and not self._item_needs_more_data(item_data):
            return

        changed = False

        if item_data.model_file_id <= 0 and item.model_file_id > 0:
            item_data.model_file_id = item.model_file_id
            changed = True

        name_encoded = self._get_name_enc_encoded(item)
        if name_encoded and item_data.name_encoded != name_encoded:
            item_data.name_encoded = name_encoded
            changed = True

        name_enc = self._get_name_enc(item)
        if name_enc and item_data.english_name != name_enc:
            item_data.english_name = name_enc
            changed = True

        if item.attribute not in (None, Attribute.None_) and item.attribute not in item_data.attributes:
            item_data.attributes = sorted(item_data.attributes + [item.attribute], key=lambda attr: attr.name)
            changed = True

        if item.profession not in (None, Profession._None) and item_data.profession != item.profession:
            item_data.profession = item.profession
            changed = True

        if changed:
            self.requires_save = True

        if not self._item_needs_more_data(item_data):
            self.checked_ids.append(item.id)
            self.checked_model_keys.append(model_key)

    def _item_needs_more_data(self, item_data: ItemData) -> bool:
        return (
            item_data.model_file_id <= 0
            or not item_data.name_encoded
            or not item_data.english_name
            or (
                item_data.item_type in {
                    ItemType.Axe,
                    ItemType.Bow,
                    ItemType.Daggers,
                    ItemType.Hammer,
                    ItemType.Offhand,
                    ItemType.Scythe,
                    ItemType.Shield,
                    ItemType.Spear,
                    ItemType.Staff,
                    ItemType.Sword,
                    ItemType.Wand,
                    ItemType.Headpiece,
                    ItemType.Chestpiece,
                    ItemType.Gloves,
                    ItemType.Leggings,
                    ItemType.Boots,
                }
                and len(item_data.attributes) == 0
            )
        )

    def _get_name_enc_encoded(self, item: ItemSnapshot) -> bytes:
        name_enc = item.name_enc
        try:
            if isinstance(name_enc, bytes):
                return name_enc
            if isinstance(name_enc, bytearray):
                return bytes(name_enc)
            if isinstance(name_enc, (list, tuple)):
                return bytes(name_enc)
        except Exception:
            pass

        return bytes()

    def _get_name_enc(self, item: ItemSnapshot) -> str:
        candidate = self._coerce_bytes(item.name_enc)
        if candidate:
            try:
                decoded = string_table.decode_plain(candidate, language=ServerLanguage.English)
                if decoded:
                    return decoded
            except Exception:
                pass

        return ''

    def _coerce_bytes(self, value) -> bytes:
        try:
            if isinstance(value, bytes):
                return value
            if isinstance(value, bytearray):
                return bytes(value)
            if isinstance(value, (list, tuple)):
                return bytes(value)
        except Exception:
            pass

        return bytes()
    
    def _request_scan(self):
        self.force_scan = True
    
    def get_item_data(self, item_id: Optional[int] = None, item_type: Optional[ItemType] = None, model_id : Optional[int] = None) -> Optional[ItemData]:     
        """
        Get item data for a given item ID or item type + model ID.
        Args:
            item_id (Optional[int]): The runtime item ID to get data for. If no item type and model ID are provided, these will be looked up using the item ID.
            item_type (Optional[ItemType]): The item type to look up. Required if item_id is not provided.
            model_id (Optional[int]): The model ID to look up. Required if item_id is not provided.
        Returns:
            Optional[ItemData]: The item data for the given item ID or item type + model ID, or None if no data is found.
        """   
        item = ItemSnapshot.from_item_id(item_id) if item_id else None
        item_type = item.item_type if item else item_type
        model_id = item.model_id if item else model_id
        
        if item_type is None or model_id is None:
            return None
        
        return self.get(item_type, {}).get(model_id, None)

    def get_or_create_item_data(self, item_type: ItemType, model_id: int) -> ItemData:
        if item_type not in self:
            self[item_type] = ModelIdDict()

        if model_id not in self[item_type]:
            self[item_type][model_id] = ItemData(model_id=model_id, item_type=item_type)

        return self[item_type][model_id]
    
    def load(self):
        super().load()
        
        self.Nick_Items = {item.nick_index: item for item in self.all_items if item.nick_index is not None}
        self.Nick_Cycle = [self.Nick_Items[index] for index in range(1, NICK_CYCLE_COUNT + 1) if index in self.Nick_Items]
    
ITEMS = ItemCollector(*BaseCollector.get_path_providers("items.json"))
