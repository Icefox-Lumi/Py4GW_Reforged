"""
Item Manager UI.

This file is intentionally large because it owns the full editor surface for:
- top-level config navigation
- rule creation / editing
- buy config editing
- upgrade-specific editors

To keep it navigable, the class is organized in broad sections:
1. setup / static formatting helpers
2. shared data caches and selector helpers
3. upgrade editors
4. item / model / weapon / material rule editors
5. window layout and config rendering
6. rule dispatch and per-rule editors
"""

import json
import inspect
import math
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Generic, NamedTuple, Optional, TypeVar, cast

import Py4GW
import PySystem
import PyImGui
import PyInventory

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
from Py4GWCoreLib.ImGui_src.Style import Style
from Py4GWCoreLib.Item import Item
from Py4GWCoreLib.Overlay import Overlay
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.ImGui_src.IconsFontAwesome5 import IconsFontAwesome5
from Py4GWCoreLib.ImGui_src.ImGuisrc import ImGui
from Py4GWCoreLib.ImGui_src.types import Alignment, ImGuiStyleVar
from Py4GWCoreLib.UIManager import TraderWindow
from Py4GWCoreLib.enums_src.GameData_enums import Attribute, DyeColor, Gender, Profession, Range
from Py4GWCoreLib.enums_src.IO_enums import ImGuiKey, Key
from Py4GWCoreLib.enums_src.Item_enums import BAG_ROW_SLOTS, DAMAGE_RANGES as ITEM_DAMAGE_RANGES, INVENTORY_BAGS, ITEM_TYPE_META_TYPES, MAX_STACK_SIZE, NICK_CYCLE_COUNT, STORAGE_BAGS, MAX_BAG_SIZES, WEAPON_TYPES, Bags, BowType, ItemAction, ItemType, Rarity, WeaponType
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Py4GWCoreLib.enums_src.Texture_enums import ProfessionTextureMap
from Sources.frenkeyLib.item_mods_src.item_mod import ItemMod
from Sources.frenkeyLib.item_mods_src.types import ItemUpgradeType
from Sources.frenkeyLib.item_mods_src.upgrades import (
    ArmorUpgrade,
    HalvesCastingTimeAttributeUpgrade,
    HalvesRechargeTimeAttributeUpgrade,
    Inherent,
    Inscription,
    Insignia,
    RangeInstruction,
    Rune,
    _INHERENT_UPGRADES,
    AppliesToRune,
    Upgrade,
    _UPGRADES,
    UpgradeRune,
    WeaponUpgrade,
)
from Py4GWCoreLib.native_src.internals import string_table
from Py4GWCoreLib.native_src.internals.encoded_strings import GWEncoded
from Py4GWCoreLib.py4gwcorelib_src.Color import Color, ColorPalette
from Py4GWCoreLib.py4gwcorelib_src.Timer import ThrottledTimer
from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
from Py4GWCoreLib.routines_src.BehaviourTrees import BT
from Sources.frenkeyLib.global_configs.BuyConfig import BuyConfig, BuyConfigEntry
from Sources.frenkeyLib.global_configs.CraftingConfig import CraftingConfig
from Sources.frenkeyLib.global_configs.InventoryConfig import InventoryConfig
from Sources.frenkeyLib.global_configs.LootConfig import LootConfig
from Sources.frenkeyLib.global_configs.GlobalConfigProfileManager import GlobalConfigProfileManager
from Sources.frenkeyLib.global_configs.SortingConfig import BagSortPlan, BagSortPreviewEntry, SortArgument, SortDirection, SortField, SlotGroupConfig, SlotMatcherConfig, SlotReference, Sorter, SortingConfig
from Sources.frenkeyLib.ItemHandling.Recipe import CraftingRecipe, Recipe
from Sources.frenkeyLib.global_configs.Rule import (
    ArmorUpgradeRule,
    BaseRule,
    ConditionOperator,
    create_rule_from_preset,
    CustomRule,
    DyesRule,
    ExtractUpgradeRule,
    get_rule_presets,
    WeaponUpgradeRule,
    NickItemRule,
    ResultInterpretation,
    RulePreset,
    CustomWeaponUpgradeRule,
)
from Sources.frenkeyLib.global_configs.Condition import (
    ArmorUpgradesCondition,
    BaseCondition,
    BowTypeCondition,
    DamageRange,
    DyeColorsCondition,
    EncodedNamesCondition,
    ExactItemTypeCondition,
    AttributeRequirement,
    InherentFilter,
    InherentFiltersCondition,
    InscribableCondition,
    IsCustomizedCondition,
    IsMaterialCondition,
    ItemTypesCondition,
    MaxWeaponUpgradesCondition,
    ModelFileIdAndItemType,
    ModelFileIdsAndItemTypesCondition,
    ModelFileIdsCondition,
    ModelIdAndItemType,
    ModelIdsAndItemTypesCondition,
    ModelIdsCondition,
    NickItemCondition,
    QuantityMatchCountMode,
    QuantityMatchCountScope,
    QuantityMatchTarget,
    QuantityMatchCondition,
    RangedUpgrade,
    UpgradeAndItemType,
    WeaponRequirementCondition,
    StackQuantityCondition,
    RaritiesCondition,
    SalvagesToMaterialsCondition,
    HalvesCastAndRechargeAttributeCondition,
    UnidentifiedCondition,
    UpgradeRangesCondition,
)
from Sources.frenkeyLib.global_configs.RuleConfig import RuleConfig
from Sources.frenkeyLib.ItemHandling.InventoryBT import InventoryBT, InventoryPreviewEntry
from Sources.frenkeyLib.item_data.ItemData import ItemData
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot
from Sources.frenkeyLib.ItemManager.btrees import TraderPriceCheckManager, TraderQuote
from Sources.frenkeyLib.ItemManager.config import Config


TConfig = TypeVar("TConfig", bound=Any)


@dataclass
class RecalculationCacheEntry:
    signature: Any
    value: Any


@dataclass
class InherentConditionRowState:
    inherent_type: type[Upgrade]
    inherent: Inherent
    label: str
    description: str
    range_instructions: tuple[RangeInstruction, ...]
    inherent_filter: InherentFilter | None
    description_text_size: tuple[float, float]

    @property
    def already_selected(self) -> bool:
        return self.inherent_filter is not None


class ConfigInfo(Generic[TConfig]):
    def __init__(
        self,
        config: TConfig,
        name: str,
        description: str,
        folder_path: str | Callable[[], str],
        storage_key: str | None = None,
        tabs: list["ConfigInfo[Any]"] | None = None,
        on_save: Callable[["ConfigInfo[Any]"], None] | None = None,
    ):
        self.config = config
        self.name = name
        self.description = description
        self.folder_path = folder_path
        self.storage_key = storage_key or self.config.__class__.__name__.lower()
        self.tabs = tabs or []
        self.selected_tab_index = 0
        self.on_save = on_save

    @property
    def config_type(self) -> str:
        return self.config.__class__.__name__

    @property
    def file_path(self) -> str:
        folder_path = self.folder_path() if callable(self.folder_path) else self.folder_path
        return os.path.join(folder_path, f"{self.storage_key}.json")

    def save(self):
        if self.tabs:
            for tab in self.tabs:
                tab.save()
            return

        if isinstance(self.config, RuleConfig):
            self.config.Save(self.file_path)
            if self.on_save is not None:
                self.on_save(self)
            return

        if isinstance(self.config, BuyConfig):
            directory = os.path.dirname(self.file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

            json_data = self.config.to_dict()

            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(json_data, file, indent=4, ensure_ascii=False)

            # configured_entries = sum(1 for entry in self.config.get_entries() if entry.quantity > 0)
            if self.on_save is not None:
                self.on_save(self)
            return

        if isinstance(self.config, CraftingConfig):
            directory = os.path.dirname(self.file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(self.config.to_dict(), file, indent=4, ensure_ascii=False)

            if self.on_save is not None:
                self.on_save(self)
            return

        if isinstance(self.config, SortingConfig):
            directory = os.path.dirname(self.file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

            with open(self.file_path, 'w', encoding='utf-8') as file:
                json.dump(self.config.to_dict(), file, indent=4, ensure_ascii=False)

            if self.on_save is not None:
                self.on_save(self)
            return

        PySystem.Console.Log("Item Manager", f"No save handler available for {self.name}.", PySystem.Console.MessageType.Warning)

    def load(self):
        if self.tabs:
            for tab in self.tabs:
                tab.load()
            return

        if isinstance(self.config, RuleConfig):
            self.config.reload_from_file(self.file_path)
            PySystem.Console.Log("Item Manager", f"Loaded config for {self.name} from {self.file_path} with {len(self.config)} rules.", PySystem.Console.MessageType.Info)
            return

        if isinstance(self.config, BuyConfig):
            self.config.reload_from_file(self.file_path)
            configured_entries = sum(1 for entry in self.config.get_entries() if entry.quantity > 0)
            PySystem.Console.Log("Item Manager", f"Loaded config for {self.name} from {self.file_path} with {configured_entries} configured consumables.", PySystem.Console.MessageType.Info)
            return

        if isinstance(self.config, CraftingConfig):
            self.config.reload_from_file(self.file_path)
            PySystem.Console.Log(
                "Item Manager",
                f"Loaded config for {self.name} from {self.file_path} with {len(self.config.selected_recipe_keys)} selected recipes.",
                PySystem.Console.MessageType.Info,
            )
            return

        if isinstance(self.config, SortingConfig):
            self.config.reload_from_file(self.file_path)
            PySystem.Console.Log(
                "Item Manager",
                f"Loaded config for {self.name} from {self.file_path} with {len(self.config.slot_groups)} slot groups.",
                PySystem.Console.MessageType.Info,
            )
            return

        PySystem.Console.Log("Item Manager", f"No load handler available for {self.name}.", PySystem.Console.MessageType.Warning)

class UpgradeTexture(NamedTuple):
    prefix: int = 0
    suffix: int = 0
    inherent: int = 0
    
class UI:
    PROJECT_PATH = PySystem.Console.get_projects_path()
    CREME_COLOR : Color = ColorPalette.GetColor("creme")
    GREEN_COLOR : Color = ColorPalette.GetColor("gw_green")
    RANDOM_COLORS : list[Color] = [
        Color.random(50) for _ in range(100)
    ]
    
    SELECTABLE_SELECTED_COLOR : Color = ColorPalette.GetColor("gw_green").opacity(0.5)
    SELECTABLE_HOVERED_COLOR : Color = ColorPalette.GetColor("gw_green").opacity(0.3)
    SELECTABLE_ACTIVE_COLOR : Color = ColorPalette.GetColor("gw_green").opacity(0.7)
    
    GENDER : Gender = Gender.Unknown
    RED_COLOR : Color = ColorPalette.GetColor("red")
    OPAGUE_RED_COLOR : Color = ColorPalette.GetColor("red").opacity(0.5)
    
    SUBTLE_TEXT_COLOR : Color = Color(90, 90, 90)
    SCREEN_SIZE : tuple[float, float] = (0.0, 0.0)
    CUSTOM_RULE_CONTENT_RECT : tuple[float, float] = (0.0, 0.0)
    
    LEADING_SEARCH_AMOUNT_RE = re.compile(r"(?<!\S)(?:[1-9]|[1-9]\d|1\d\d|2[0-4]\d|250)\s+")
    _RULE_TYPES_CACHE: list[type[BaseRule]] | None = None
    _CONDITION_TYPES_CACHE: list[type[BaseCondition]] | None = None
    _ALL_CONDITION_TYPES_CACHE: list[type[BaseCondition]] | None = None
    INVENTORY_PREVIEW_BAGS: list[Bags] = [
        Bags.Backpack,
        Bags.BeltPouch,
        Bags.Bag1,
        Bags.Bag2,
        Bags.EquipmentPack,
        Bags.Storage1,
        Bags.Storage2,
        Bags.Storage3,
        Bags.Storage4,
        Bags.Storage5,
        Bags.Storage6,
        Bags.Storage7,
        Bags.Storage8,
        Bags.Storage9,
        Bags.Storage10,
        Bags.Storage11,
        Bags.Storage12,
        Bags.Storage13,
        Bags.Storage14,
        Bags.MaterialStorage,
    ]
    ITEM_TYPE_ATTRIBUTES = {
        ItemType.Axe : Attribute.AxeMastery,
        ItemType.Bow : Attribute.Marksmanship,
        ItemType.Daggers : Attribute.DaggerMastery,
        ItemType.Hammer : Attribute.HammerMastery,
        ItemType.Sword : Attribute.Swordsmanship,
        ItemType.Scythe : Attribute.ScytheMastery,
        ItemType.Spear : Attribute.SpearMastery,
        ItemType.Offhand : Attribute.None_,
        ItemType.Shield : Attribute.None_,
        ItemType.Staff : Attribute.None_,
        ItemType.Wand : Attribute.None_,
    }
    
    caster_attributes = [
        Attribute.FastCasting,
        Attribute.IllusionMagic,
        Attribute.DominationMagic,
        Attribute.InspirationMagic,
        Attribute.BloodMagic,
        Attribute.DeathMagic,
        Attribute.SoulReaping,
        Attribute.Curses,
        Attribute.AirMagic,
        Attribute.EarthMagic,
        Attribute.FireMagic,
        Attribute.WaterMagic,
        Attribute.EnergyStorage,
        Attribute.HealingPrayers,
        Attribute.SmitingPrayers,
        Attribute.ProtectionPrayers,
        Attribute.DivineFavor,
        Attribute.Communing,
        Attribute.RestorationMagic,
        Attribute.ChannelingMagic,
        Attribute.SpawningPower,
    ]
    
    META_ITEM_TYPE_ATTRIBUTES : dict[ItemType, list[Attribute] | Attribute] = {
        ItemType.Axe : Attribute.AxeMastery,
        ItemType.Bow : Attribute.Marksmanship,
        ItemType.Daggers : Attribute.DaggerMastery,
        ItemType.Hammer : Attribute.HammerMastery,
        ItemType.Sword : Attribute.Swordsmanship,
        ItemType.Scythe : Attribute.ScytheMastery,
        ItemType.Spear : Attribute.SpearMastery,
        
        ItemType.SpellcastingWeapon : caster_attributes,
        ItemType.Offhand : caster_attributes,
        ItemType.Shield : [Attribute.Strength, Attribute.Tactics, Attribute.Command, Attribute.Leadership],
    }
    
    ITEM_TYPE_NAMES = {item_type: item_type.name for item_type in ItemType}
    BOW_TYPE_NAMES = {
        BowType.Shortbow: "Shortbow",
        BowType.Longbow: "Longbow",
        BowType.Flatbow: "Flatbow",
        BowType.Recurvebow: "Recurve Bow",
        BowType.Hornbow: "Hornbow",
    }
    
    ITEM_UPGRADE_MODEL_FILE_IDS = {
        ItemType.Bow : (91655, 91653),
    }
    
    
    ITEM_TYPE_REPRESENTATIVE_MODELFILE_IDS = {
        ItemType.Salvage : 24886,
        ItemType.Rune_Mod : 151854,
        ItemType.Materials_Zcoins : 19672,
        ItemType.Dye : 9383,
        ItemType.Usable : 205878,
        
        ItemType.Axe : 9483, 
        ItemType.Bow : 97341,        
        ItemType.Hammer : 39779,
        ItemType.Wand : 94904,
        ItemType.Shield : 15449,
        ItemType.Staff : 87301,
        ItemType.Sword : 231460,
        ItemType.Daggers : 164910,
        ItemType.Scythe : 205952,
        ItemType.Spear : 205960,
        ItemType.Offhand : 341789,
        
        ItemType.Headpiece : 73,        
        ItemType.Chestpiece : 71,
        ItemType.Gloves : 72,
        ItemType.Leggings : 74,
        ItemType.Boots : 70,
        
        ItemType.CC_Shards : 158543,
        ItemType.Key : 153939,
        ItemType.Gold_Coin : 231507,
        ItemType.Kit : 79229,
        ItemType.Trophy : 123464,
        ItemType.Scroll : 275575,
        
        ItemType.Bag : 111926,
        ItemType.Storybook : 330029,
        ItemType.Present : 193281,        
        ItemType.Minipet : 284865,
        
        ItemType.Quest_Item : 88537,
        ItemType.Bundle : 358543,
        
        ItemType.Costume_Headpiece : 2654,
        ItemType.Costume : 2656,
        
        ItemType.Weapon : 205892,
        ItemType.MartialWeapon : 205890,
        ItemType.OffhandOrShield : 205891,
        ItemType.EquippableItem : 205889,
        ItemType.SpellcastingWeapon : 205889,
        # ItemType.Unknown : ModelID.Unknown
    }
    
    HalvesCastingTimeAttributeUpgrade_INSTANCE = HalvesCastingTimeAttributeUpgrade()
    HalvesRechargeTimeAttributeUpgrade_INSTANCE = HalvesRechargeTimeAttributeUpgrade()

    # -------------------------------------------------------------------------
    # Construction / state
    # -------------------------------------------------------------------------
    def __init__(self, module_config: Config):
        self.module_config = module_config
        self.queue_data_refresh_on_main_window_open = False
        
        self.floating_button = ImGui.FloatingIcon(
                icon_path=self.module_config.icon_path,
                window_id="##item_manager_floating_button",
                window_name="Item Manager##FloatingButton",
                tooltip_visible="Hide Item Manager",
                tooltip_hidden="Show Item Manager",
                toggle_ini_key=self.module_config.floating_ini_key,
                toggle_var_name="show_main_window",
                toggle_default=False,
                draw_callback=self.draw_main_window,
            )
        
        self.window_pos : tuple[float, float] | None = None
        self.window_flags = PyImGui.WindowFlags.NoFlag
        self.main_window_focused = False
        self.rules_hovered = False
        self.show_preview_window: bool = False
        self.show_manage_profile_window: bool = False
        self.preview_window_config_type: str = 'BuyConfig'
        self.manage_profile_window_config_type: str = 'BuyConfig'
        self.profile_manager = GlobalConfigProfileManager()
        self.profile_manager.refresh()
        self._last_seen_profile_context_signatures: dict[str, tuple[str, str, str]] = {}
        self._profile_context_refresh_timer: ThrottledTimer = ThrottledTimer(1000)
        self.preview_entries : Optional[list[InventoryPreviewEntry]] = None
        self.preview_throttle : ThrottledTimer = ThrottledTimer(1000)
        self._manual_inventory_bt: InventoryBT | None = None
        self._manual_inventory_bt_config_id: int | None = None
        self._manual_inventory_tick_repeat_timer: ThrottledTimer = ThrottledTimer(125)
        self._manual_inventory_tick_status: str = ''
        self.sorting_preview_throttle : ThrottledTimer = ThrottledTimer(1000)
        self.sorting_preview_plan: Optional[BagSortPlan] = None
        self._sorting_preview_cache_key: tuple[tuple[int, ...], str] | None = None
        self._sorting_preview_plan_tree = None
        self._sorting_preview_plan_status: str = ''
        self._sorting_preview_plan_error: str = ''

        self.configs : list[ConfigInfo] = [
            ConfigInfo(
                BuyConfig(),
                "Merchant Buying",
                "Configure how many kits, keys and lockpicks to keep in stock",
                lambda: self.profile_manager.get_active_config_folder('BuyConfig'),
                on_save=self._handle_config_saved,
            ),
            ConfigInfo(
                LootConfig(),
                "Loot Filtering",
                "Configure which items to pick up and which to ignore",
                lambda: self.profile_manager.get_active_config_folder('LootConfig'),
                on_save=self._handle_config_saved,
            ),
            ConfigInfo(
                InventoryConfig(),
                "Inventory Processing",
                "Configure how to process items (Stash, Salvage, Extract Upgrades, Sell, ...)",
                lambda: self.profile_manager.get_active_config_folder('InventoryConfig'),
                on_save=self._handle_config_saved,
            ),
            ConfigInfo(
                SortingConfig(),
                "Xunlai- & Bag-Sorting",
                "Configure slot groups and sort policies for inventory bags and Xunlai storage tabs",
                lambda: self.profile_manager.get_active_config_folder('SortingConfig'),
                on_save=self._handle_config_saved,
            ),
            # ConfigInfo(
            #     CraftingConfig(),
            #     "Crafting",
            #     "Configure crafting settings",
            #     lambda: self.profile_manager.get_active_config_folder('CraftingConfig'),
            #     on_save=self._handle_config_saved,
            # ),
        ]

        for config_info in self.configs:
            config_info.load()
        self._update_profile_context_signatures()

        self.config : Optional[ConfigInfo] = None
        self.rule : Optional[BaseRule] = None
        self.rule_index : Optional[int] = None

        self.switch_to_config(self.configs[0] if len(self.configs) > 0 else None)
        available_upgrade_types: list[type[Upgrade]] = list(_UPGRADES)

        #Remove all subclasses and class of UpgradeRune, AppliesToRune
        self.available_inherent_upgrade_types: list[type[Upgrade]] = list(_INHERENT_UPGRADES)
        self.available_upgrade_types = [
            upgrade_type for upgrade_type in available_upgrade_types
            if not issubclass(upgrade_type, (UpgradeRune, AppliesToRune)) and upgrade_type is not UpgradeRune and upgrade_type is not AppliesToRune
        ]
        self._armor_upgrade_types_by_profession: dict[Profession, list[type[Upgrade]]] = {}
        self._weapon_upgrade_types_by_mod_type: dict[ItemUpgradeType, list[type[Upgrade]]] = {}
        self._inherent_option_entries: list[tuple[type[Upgrade], str, str, str]] = []
        self._inherent_search_cache: dict[str, list[tuple[type[Upgrade], str, str]]] = {}
        self._range_upgrade_option_entries: list[tuple[type[WeaponUpgrade | Inscription], RangeInstruction, str]] = []
        self._range_upgrade_search_cache: dict[str, list[tuple[type[WeaponUpgrade | Inscription], RangeInstruction]]] = {}

        self.selected_upgrade_type_index = 0

        self.context_menu_id : str | None = None
        self.context_menu_rule : BaseRule | None = None
        self.context_menu_config : ConfigInfo | None = None
        self.context_menu_sorting_group : SlotGroupConfig | None = None
        self._condition_clipboard_payload: dict[str, Any] | None = None
        self._condition_clipboard_label: str = ''
        self._condition_drag_handle_state: dict[int, tuple[bool, bool]] = {}
        self._weapon_requirement_and_damage_add_item_type_state: dict[int, ItemType] = {}
        self._weapon_requirement_and_damage_add_requirement_level_state: dict[int, int] = {}
        
        self._drag_start_time: float = 0.0
        self._dragging: bool = False
        self._drag_clicked_item: Any | None = None
        self._drag_window_pos: tuple[float, float] | None = None
        
        self._drag_rule: BaseRule | None = None
        self._drag_rule_source_config: ConfigInfo[RuleConfig] | None = None
        self._drag_rule_source_index: int = -1
        self._drag_rule_target_index: int = -1
        self._drag_rule_target_rect: tuple[float, float, float, float] | None = None
        self._drag_rule_target_after: bool = False
        self._drag_rule_preview_label: str = ""
        self._drag_rule_preview_subtitle: str = ""
        self._drag_condition: BaseCondition | None = None
        self._drag_condition_source_rule: CustomRule | None = None
        self._drag_condition_source_index: int = -1
        self._drag_condition_target_index: int = -1
        self._drag_condition_target_rect: tuple[float, float, float, float] | None = None
        self._drag_condition_target_after: bool = False
        self._drag_condition_preview_label: str = ""
        self._drag_condition_preview_subtitle: str = ""
        self._drag_sorting_group: SlotGroupConfig | None = None
        self._drag_sorting_group_source_config: ConfigInfo[SortingConfig] | None = None
        self._drag_sorting_group_source_index: int = -1
        self._drag_sorting_group_target_index: int = -1
        self._drag_sorting_group_target_rect: tuple[float, float, float, float] | None = None
        self._drag_sorting_group_target_after: bool = False
        self._drag_sorting_group_preview_label: str = ""
        self._drag_sorting_group_preview_subtitle: str = ""

        self.profession : Profession = Profession._None
        self.mod_type : ItemUpgradeType = ItemUpgradeType.Prefix
        self.armor_upgrade_price_threshold: int = 250
        self._armor_upgrade_quote_cache_generation: int | None = None
        self._armor_upgrade_quote_cache_profession: Profession | None = None
        self._armor_upgrade_quote_cache_processed_item_ids: set[int] = set()
        self._armor_upgrade_quote_cache: dict[Any, TraderQuote] = {}
        self.texture_path = os.path.join(PySystem.Console.get_projects_path(), "Assets", "Textures")

        self.weapon_upgrade_textures : dict[ItemType, UpgradeTexture] = {
                ItemType.Axe : UpgradeTexture(
                    prefix=19872,
                    suffix=91650,
                ),
                ItemType.Bow : UpgradeTexture(
                    prefix=91655,
                    suffix=91653,
                ),
                ItemType.Daggers : UpgradeTexture(
                    prefix=164837,
                    suffix=164856,
                ),
                ItemType.Hammer : UpgradeTexture(
                    prefix=19873,
                    suffix=91654,
                ),
                ItemType.Offhand : UpgradeTexture(
                    suffix=205913,
                    inherent=205889,
                ),
                ItemType.Scythe : UpgradeTexture(
                    prefix=205895,
                    suffix=205917,
                ),
                ItemType.Shield : UpgradeTexture(
                    suffix=205920,
                ),
                ItemType.Spear : UpgradeTexture(
                    prefix=205896,
                    suffix=205921,
                ),
                ItemType.Staff : UpgradeTexture(
                    prefix=164795,
                    suffix=164796,
                ),
                ItemType.Sword : UpgradeTexture(
                    prefix=20015,
                    suffix=91656,
                ),
                ItemType.Wand : UpgradeTexture(
                    suffix=205916,
                ),
                
                ItemType.Weapon : UpgradeTexture(inherent=205892),
                ItemType.MartialWeapon : UpgradeTexture(inherent=205890),
                ItemType.OffhandOrShield : UpgradeTexture(inherent=205891),
                ItemType.EquippableItem : UpgradeTexture(inherent=205889),
                ItemType.SpellcastingWeapon : UpgradeTexture(inherent=205889),
            }

        self.dye_textures: dict[int, str] = {
            DyeColor.NoColor: os.path.join(self.texture_path, "Dyes", "Gray.png"),
            DyeColor.Blue: os.path.join(self.texture_path, "Dyes", "Blue.png"),
            DyeColor.Green: os.path.join(self.texture_path, "Dyes", "Green.png"),
            DyeColor.Purple: os.path.join(self.texture_path, "Dyes", "Purple.png"),
            DyeColor.Red: os.path.join(self.texture_path, "Dyes", "Red.png"),
            DyeColor.Yellow: os.path.join(self.texture_path, "Dyes", "Yellow.png"),
            DyeColor.Brown: os.path.join(self.texture_path, "Dyes", "Brown.png"),
            DyeColor.Orange: os.path.join(self.texture_path, "Dyes", "Orange.png"),
            DyeColor.Silver: os.path.join(self.texture_path, "Dyes", "Silver.png"),
            DyeColor.Black: os.path.join(self.texture_path, "Dyes", "Black.png"),
            DyeColor.Gray: os.path.join(self.texture_path, "Dyes", "Gray.png"),
            DyeColor.White: os.path.join(self.texture_path, "Dyes", "White.png"),
            DyeColor.Pink: os.path.join(self.texture_path, "Dyes", "Pink.png"),
        }

        self._all_item_data_cache: list[ItemData] = []
        self._item_by_model_file_id: dict[int, ItemData] = {}
        self._item_by_model_id: dict[int, ItemData] = {}
        self._item_by_model_id_and_item_type: dict[tuple[int, ItemType], ItemData] = {}
        self._item_by_model_file_id_and_item_type: dict[tuple[int, ItemType], ItemData] = {}
        self._item_by_encoded_name: dict[bytes, ItemData] = {}
        self._sorted_model_ids: list[ModelID] = sorted([model_id for model_id in ModelID], key=lambda model_id: model_id.name)
        self._sorted_model_id_values: set[int] = {int(model_id.value) for model_id in self._sorted_model_ids}
        self._sorted_item_types: list[ItemType] = sorted(ItemType, key=lambda item_type: item_type.name)
        self._sorted_rarities: list[Rarity] = sorted(Rarity, key=lambda rarity: rarity.value)
        self._sorted_dye_colors: list[DyeColor] = sorted(DyeColor, key=lambda dye_color: dye_color.name)
        self._unique_encoded_name_items: list[ItemData] = []
        self._unique_model_file_id_items: list[ItemData] = []
        self._nick_cycle_items: list[ItemData] = []
        self._salvage_material_options: list[ItemData] = []
        self._model_id_search_entries: list[tuple[ModelID, str]] = []
        self._encoded_name_search_entries: list[tuple[ItemData, str]] = []
        self._model_file_id_search_entries: list[tuple[ItemData, str]] = []
        self._model_id_item_search_entries: list[tuple[ItemData, str]] = []
        self._salvage_material_search_entries: list[tuple[ItemData, str]] = []
        self._model_id_search_cache: dict[str, list[ModelID]] = {}
        self._encoded_name_search_cache: dict[str, list[ItemData]] = {}
        self._model_file_id_search_cache: dict[str, list[ItemData]] = {}
        self._model_id_item_search_cache: dict[str, list[ItemData]] = {}
        self._nick_item_preview_cache: dict[int, list[ItemData]] = {}
        self._salvage_material_search_cache: dict[str, list[ItemData]] = {}
        self._live_search_normalized_cache: dict[str, tuple[str, str]] = {}
        self._live_search_results_cache: dict[str, tuple[str, list[Any]]] = {}
        self._search_field_state: dict[str, str] = {}
        self._recalculation_cache: dict[str, RecalculationCacheEntry] = {}
        self.inventory_preview_search: str = ""
        self.inventory_preview_show_no_action: bool = False
        self.inventory_preview_show_hold: bool = False
        self.inventory_preview_selected_bags: list[Bags] = [
            Bags.Backpack,
            Bags.BeltPouch,
            Bags.Bag1,
            Bags.Bag2,
        ]
        self.sorting_selected_bag: Bags = Bags.Backpack
        self.sorting_preview_selected_bags: list[Bags] = list(INVENTORY_BAGS)
        self.loot_preview_search: str = ""
        self.loot_preview_show_no_action: bool = False
        self.loot_preview_distance: int = int(Range.SafeCompass.value)
        self.buy_preview_search: str = ""
        self.crafting_recipe_add_key: str = ""
        self.global_config_new_profile_name: str = ""
        self._save_as_profile_popup_id: str = '##save_as_profile_popup'
        self._save_as_profile_popup_requested: bool = False
        self._empty_profile_popup_id: str = '##empty_profile_popup'
        self._empty_profile_popup_requested: bool = False
        self._empty_profile_name: str = ''
        self._manage_profile_selected_name: str = GlobalConfigProfileManager.SHARED_PROFILE_NAME
        self._profile_action_popup_id: str = '##profile_action_popup'
        self._profile_action_popup_requested: bool = False
        self._profile_action_mode: str = ''
        self._profile_action_source_name: str = ''
        self._profile_action_target_name: str = ''
        self._rule_delete_popup_id: str = '##rule_delete_popup'
        self._rule_delete_popup_requested: bool = False
        self._rule_delete_target_config: ConfigInfo[RuleConfig] | None = None
        self._rule_delete_target_rule: BaseRule | None = None
        self._sorting_group_delete_popup_id: str = '##sorting_group_delete_popup'
        self._sorting_group_delete_popup_requested: bool = False
        self._sorting_group_delete_target_config: ConfigInfo[SortingConfig] | None = None
        self._sorting_group_delete_target_group: SlotGroupConfig | None = None
        self.buy_preview_show_satisfied: bool = True
        
        self.selected_bag_slots : list[tuple[Bags, int]] = []
        self._sorting_slot_picker_selection: list[tuple[Bags, int]] = []
        self._sorting_bag_size_cache: dict[Bags, int] = {}
        self._sorting_assigned_slot_cache: set[tuple[Bags, int]] = set()
        self._sorting_slot_selector_popup_id: str | None = None
        self._sorting_slot_selector_group: Optional[SlotGroupConfig] = None
        self.sorting_group: Optional[SlotGroupConfig] = None
        self.sorting_group_index: Optional[int] = None
        self._sorting_pending_slot_group: Optional[SlotGroupConfig] = None
        self._sorting_pending_slot_refs: list[SlotReference] = []
        self._sorting_pending_conflict_groups: list[SlotGroupConfig] = []
        self._sorting_slot_override_popup_id: str = '##sorting_slot_override_popup'
        self._sorting_slot_override_popup_requested: bool = False
        
        UI.ITEM_TYPE_NAMES[ItemType.Offhand] = "Focus"
        UI.ITEM_TYPE_NAMES[ItemType.Rune_Mod] = "Upgrades & Runes"
        UI.ITEM_TYPE_NAMES[ItemType.OffhandOrShield] = "Focus Or Shield"
        UI.ITEM_TYPE_NAMES[ItemType.CC_Shards] = "Stackable Salvage"
        UI.ITEM_TYPE_NAMES[ItemType.Salvage] = "Armor Salvage"
        UI.ITEM_TYPE_NAMES[ItemType.Materials_Zcoins] = "Materials & Z-Coins"
        
        UI.ITEM_TYPE_NAMES = {item_type: self._humanize_name(name) for item_type, name in UI.ITEM_TYPE_NAMES.items()} 
        
        self._rebuild_upgrade_ui_caches()
        self._rebuild_item_ui_caches()    

    def _get_all_crafting_recipe_entries(self) -> list[tuple[str, Recipe]]:
        return [(recipe_entry.name, recipe_entry.value) for recipe_entry in CraftingRecipe]

    def _get_crafting_recipe_by_key(self, recipe_key: str) -> Recipe | None:
        recipe_entry = CraftingRecipe.__members__.get(recipe_key)
        return recipe_entry.value if recipe_entry is not None else None

    def _get_selected_crafting_recipes(self, config: CraftingConfig) -> list[tuple[str, Recipe]]:
        selected_recipes: list[tuple[str, Recipe]] = []
        seen_keys: set[str] = set()

        for recipe_key in config.selected_recipe_keys:
            if recipe_key in seen_keys:
                continue

            recipe = self._get_crafting_recipe_by_key(recipe_key)
            if recipe is None:
                continue

            selected_recipes.append((recipe_key, recipe))
            seen_keys.add(recipe_key)

        return selected_recipes

    def _get_item_label(self, model_id: int, item_type: ItemType, fallback: str | None = None, plain : bool = True) -> str:
        from Sources.frenkeyLib.DataCollector.collectors.items_collector import ITEMS
        item_data = ITEMS.get_item_data(item_type=item_type, model_id=model_id)
        if item_data is not None:
            return (item_data.names.plain_singular if plain else item_data.names.singular) or (fallback or f"Model {model_id}")

        if fallback:
            return fallback

        try:
            model_name = ModelID(model_id).name
            return self._humanize_name(model_name)
        except ValueError:
            return f"Model {model_id}"

    # -------------------------------------------------------------------------
    # General formatting / discovery helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_confirm_key_pressed() -> bool:
        return (
            PyImGui.is_key_pressed(ImGuiKey.Enter.value)
            or PyImGui.is_key_pressed(ImGuiKey.KeypadEnter.value)
        )

    @staticmethod
    def _is_cancel_key_pressed() -> bool:
        return PyImGui.is_key_pressed(Key.Escape.value)

    def _set_active_rule(self, rule: Optional[BaseRule]) -> None:
        if self.config and isinstance(self.config.config, RuleConfig):
            self.rule = rule if rule in self.config.config else None
            self.rule_index = self.config.config.index(self.rule) if self.rule is not None else None

    def _set_active_sorting_group(self, group: Optional[SlotGroupConfig]) -> None:
        if self.config and isinstance(self.config.config, SortingConfig):
            self.sorting_group = group if group in self.config.config.slot_groups else None
            self.sorting_group_index = self.config.config.slot_groups.index(self.sorting_group) if self.sorting_group is not None else None
        else:
            self.sorting_group = None
            self.sorting_group_index = None
        
    @staticmethod
    def format_currency(value: int) -> str:
        plat, gold = GWEncoded._formatted_currency_amount_bytes(value)

        return (string_table.decode(plat) + " " if plat else "") + string_table.decode(gold)

    @staticmethod
    def format_time_ago(timestamp: float) -> str:
        elapsed = max(0, int(time.time() - timestamp))
        units = [
            ("year", 365 * 24 * 60 * 60),
            ("month", 30 * 24 * 60 * 60),
            ("day", 24 * 60 * 60),
            ("hour", 60 * 60),
            ("minute", 60),
            ("second", 1),
        ]

        parts: list[str] = []
        remaining = elapsed

        for label, unit_seconds in units:
            value, remaining = divmod(remaining, unit_seconds)
            if value <= 0:
                continue

            parts.append(f"{value} {label}{'' if value == 1 else 's'}")

        return f"{' '.join(parts) if parts else '0 seconds'} ago"

    @staticmethod
    def _get_rule_types() -> list[type[BaseRule]]:
        if UI._RULE_TYPES_CACHE is not None:
            return UI._RULE_TYPES_CACHE

        discovered_rule_types: list[type[BaseRule]] = []

        def visit(rule_type: type[BaseRule]) -> None:
            for child_rule_type in rule_type.__subclasses__():
                if child_rule_type not in discovered_rule_types:
                    discovered_rule_types.append(child_rule_type)
                visit(child_rule_type)

        visit(BaseRule)
        types = [
            rule_type
            for rule_type in discovered_rule_types
            if getattr(rule_type, "ui_selectable", True)
        ]
        UI._RULE_TYPES_CACHE = sorted(types, key=lambda t: t.__name__)
        return UI._RULE_TYPES_CACHE

    @staticmethod
    def _get_condition_types() -> list[type[BaseCondition]]:
        if UI._CONDITION_TYPES_CACHE is not None:
            return UI._CONDITION_TYPES_CACHE

        discovered_condition_types: list[type[BaseCondition]] = []

        def visit(condition_type: type[BaseCondition]) -> None:
            for child_condition_type in condition_type.__subclasses__():
                if child_condition_type not in discovered_condition_types:
                    discovered_condition_types.append(child_condition_type)
                visit(child_condition_type)

        visit(BaseCondition)
        types = [
            condition_type
            for condition_type in discovered_condition_types
            if getattr(condition_type, "ui_selectable", True)
            and condition_type is not BaseCondition
            and not inspect.isabstract(condition_type)
        ]
        UI._CONDITION_TYPES_CACHE = sorted(types, key=lambda t: t.__name__)
        return UI._CONDITION_TYPES_CACHE

    @staticmethod
    def _get_all_condition_types() -> list[type[BaseCondition]]:
        if UI._ALL_CONDITION_TYPES_CACHE is not None:
            return UI._ALL_CONDITION_TYPES_CACHE

        discovered_condition_types: list[type[BaseCondition]] = []

        def visit(condition_type: type[BaseCondition]) -> None:
            for child_condition_type in condition_type.__subclasses__():
                if child_condition_type not in discovered_condition_types:
                    discovered_condition_types.append(child_condition_type)
                visit(child_condition_type)

        visit(BaseCondition)
        types = [
            condition_type
            for condition_type in discovered_condition_types
            if condition_type is not BaseCondition
            and condition_type.__name__ != 'UpgradeMatchCondition'
            and not inspect.isabstract(condition_type)
        ]
        UI._ALL_CONDITION_TYPES_CACHE = sorted(types, key=lambda t: t.__name__)
        return UI._ALL_CONDITION_TYPES_CACHE

    @staticmethod
    def _humanize_name(value: str) -> str:
        return Utils.humanize_string(value.replace("NONE", "None").replace("None_", "None").replace("_None", "None")).replace("  ", " ").strip()

    @staticmethod
    def _item_type_name(item_type: ItemType) -> str:
        return UI.ITEM_TYPE_NAMES.get(item_type, UI._humanize_name(item_type.name))

    @staticmethod
    def _bow_type_name(bow_type: BowType) -> str:
        return UI.BOW_TYPE_NAMES.get(bow_type, UI._humanize_name(bow_type.name))

    @staticmethod
    def _get_relative_luminance(color: Color) -> float:
        return (0.2126 * color.r) + (0.7152 * color.g) + (0.0722 * color.b)

    @staticmethod
    def _build_subtle_text_color(text_color: Color) -> Color:
        text_luminance = UI._get_relative_luminance(text_color)
        subtle_color = text_color.desaturate(0.25)

        dark_lift = 0.55
        if text_luminance >= 110:
            return Color(
                max(0, min(255, int(round(subtle_color.r * dark_lift)))),
                max(0, min(255, int(round(subtle_color.g * dark_lift)))),
                max(0, min(255, int(round(subtle_color.b * dark_lift)))),
                text_color.a,
            )

        strongest_channel = max(subtle_color.r, subtle_color.g, subtle_color.b)
        if strongest_channel <= 0:
            return Color(90, 90, 90, text_color.a)

        lift = 120.0 / strongest_channel
        return Color(
            max(0, min(255, int(round(subtle_color.r * lift)))),
            max(0, min(255, int(round(subtle_color.g * lift)))),
            max(0, min(255, int(round(subtle_color.b * lift)))),
            text_color.a,
        )

    @staticmethod
    def _normalize_search_query(value: str) -> str:
        normalized = UI._strip_diacritics(value.strip())
        normalized = UI.LEADING_SEARCH_AMOUNT_RE.sub("", normalized, count=1).lower()
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _normalize_searchable_text(value: str) -> str:
        normalized = UI._strip_diacritics(value.strip())
        normalized = UI.LEADING_SEARCH_AMOUNT_RE.sub("", normalized).lower()
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _strip_diacritics(value: str) -> str:
        normalized = unicodedata.normalize('NFKD', value)
        return ''.join(character for character in normalized if not unicodedata.combining(character))

    @staticmethod
    def _singularize_search_query(value: str) -> str:
        return re.sub(r"\b([a-zA-Z]{4,})s\b", r"\1", value)

    @staticmethod
    def _search_tokens_match(search_query: str, searchable_text: str) -> bool:
        if search_query in searchable_text:
            return True

        query_tokens = [token for token in search_query.split(" ") if token]
        if not query_tokens:
            return True

        if all(token in searchable_text for token in query_tokens):
            return True

        singular_tokens = [UI._singularize_search_query(token) for token in query_tokens]
        return all(token in searchable_text for token in singular_tokens if token)

    @staticmethod
    def _search_text_matches(search_query: str, *values: Any) -> bool:
        if not search_query:
            return True

        raw_text = " ".join(str(value) for value in values if value is not None)
        searchable_text = UI._normalize_searchable_text(raw_text)
        return UI._search_tokens_match(search_query, searchable_text)

    @staticmethod
    def _build_search_blob(*values: Any) -> str:
        raw_text = " ".join(str(value) for value in values if value is not None)
        return UI._normalize_searchable_text(raw_text)

    @staticmethod
    def _search_blob_matches(search_query: str, search_blob: str) -> bool:
        if not search_query:
            return True

        return UI._search_tokens_match(search_query, search_blob)

    @staticmethod
    def _focus_popup_search_field_on_appearing() -> None:
        if PyImGui.is_window_appearing():
            PyImGui.set_keyboard_focus_here(0)

    @staticmethod
    def _filter_cached_entries(cache: dict[str, list[Any]], search_query: str, entries: list[tuple[Any, str]]) -> list[Any]:
        cached = cache.get(search_query)
        if cached is not None:
            return cached

        if not search_query:
            result = [entry for entry, _ in entries]
        else:
            result = [entry for entry, search_blob in entries if UI._search_blob_matches(search_query, search_blob)]

        cache[search_query] = result
        return result

    @staticmethod
    def show_rule_type_tooltip(rule_type: type, wrap_width: float = 420.0):
        if not PyImGui.is_item_hovered():
            return
        
        title = UI._humanize_name(rule_type.__name__)
        doc = inspect.getdoc(rule_type) or ""
        doc = re.sub(r":class:`([^`]+)`", r"\1", doc)
        doc = doc.replace("**", "")
        doc = doc.replace("\n", "\n\n").strip()
        # inversion_note = "Enable Inverted on a rule to apply it to items that do not match the configured criteria."
        drag_note = "Drag and drop rules to reorder them.\nThe higher in the list a rule is, the higher its priority."
        
        PyImGui.begin_tooltip()
        PyImGui.push_text_wrap_pos(PyImGui.get_cursor_pos_x() + wrap_width)
        ImGui.text_colored(title, color=UI.CREME_COLOR.color_tuple, font_size=16)
        if doc:
            PyImGui.text_wrapped(doc)    
        PyImGui.pop_text_wrap_pos()
        
        ImGui.text_colored(drag_note, color=UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
        
        PyImGui.end_tooltip()
        
    @staticmethod
    def show_custom_rule_tooltip(rule: CustomRule, wrap_width: float = 420.0):
        if not PyImGui.is_item_hovered():
            return
        
        title = UI._humanize_name(rule.__class__.__name__)
        drag_note = "Drag and drop rules to reorder them.\nThe higher in the list a rule is, the higher its priority."
        
        PyImGui.begin_tooltip()
        PyImGui.push_text_wrap_pos(PyImGui.get_cursor_pos_x() + wrap_width)
        ImGui.text_colored(title, color=UI.CREME_COLOR.color_tuple, font_size=16)
        ImGui.text("Conditions")
        ImGui.separator()
        for c in rule.conditions:
            condition_type = type(c)
            condition_title = UI._humanize_name(condition_type.__name__).replace("Condition", "")
            ImGui.text(f"- {condition_title}", font_size=14)
        PyImGui.pop_text_wrap_pos()
        
        ImGui.text_colored(drag_note, color=UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
        
        PyImGui.end_tooltip()

    @staticmethod
    def show_rule_preset_tooltip(rule_preset: RulePreset, wrap_width: float = 420.0):
        if not PyImGui.is_item_hovered():
            return

        drag_note = 'Creates a Custom Rule seeded with the preset conditions.'

        PyImGui.begin_tooltip()
        PyImGui.push_text_wrap_pos(PyImGui.get_cursor_pos_x() + wrap_width)
        ImGui.text_colored(rule_preset.label, color=UI.CREME_COLOR.color_tuple, font_size=16)
        if rule_preset.description:
            PyImGui.text_wrapped(rule_preset.description)
        PyImGui.pop_text_wrap_pos()

        ImGui.text_colored(drag_note, color=UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
        PyImGui.end_tooltip()

    @staticmethod
    def _format_condition_type_tooltip(condition_type: type) -> str:
        title = UI._humanize_name(condition_type.__name__)
        doc = inspect.getdoc(condition_type) or ""
        doc = re.sub(r":class:`([^`]+)`", r"\1", doc)
        doc = doc.replace("**", "")
        doc = doc.replace("\n", "\n\n").strip()
        return f"{title}\n\n{doc}" if doc else title

    @staticmethod
    def _show_wrapped_tooltip(text: str, wrap_width: float = 420.0) -> None:
        if not PyImGui.is_item_hovered():
            return

        PyImGui.begin_tooltip()
        PyImGui.push_text_wrap_pos(PyImGui.get_cursor_pos_x() + wrap_width)
        PyImGui.text_wrapped(text)
        PyImGui.pop_text_wrap_pos()
        PyImGui.end_tooltip()

    def _format_upgrade_type_label(self, upgrade_type: type[Upgrade]) -> str:
        type_name = upgrade_type.__name__.replace("Upgrade", "")
        return self._humanize_name(type_name)

    def _format_upgrade_label(self, upgrade: Upgrade) -> str:
        name = upgrade.name_plain if getattr(upgrade, "name_plain", "") else ""
        return name or self._format_upgrade_type_label(type(upgrade))

    @staticmethod
    def _get_all_item_data() -> list[ItemData]:
        from Sources.frenkeyLib.DataCollector.collectors.items_collector import ITEMS
        return [item for sublist in ITEMS.values() for item in sublist.values()]

    @staticmethod
    def _get_item_display_name(item: Any) -> str:
        return item.name or f"Model {item.model_id}"

    @staticmethod
    def _get_item_encoded_name_string(item: Any) -> str:
        if getattr(item, "name_encoded", bytes()):
            return ", ".join(f"0x{byte:X}" for byte in item.name_encoded)
        return ""

    @staticmethod
    def _format_snapshot_value(value: Any) -> str:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, IntEnum):
            return value.name
        if isinstance(value, tuple):
            return ", ".join(UI._format_snapshot_value(entry) for entry in value)
        if isinstance(value, list):
            return ", ".join(UI._format_snapshot_value(entry) for entry in value)
        return str(value)

    def _draw_item_snapshot_tooltip(self, item: ItemSnapshot) -> None:
        rows: list[tuple[str, Any]] = [
            ("ID", item.id),
            ("Name", item.name or "-"),
            ("Singular", item.singular_name or "-"),
            ("Complete", item.complete_name or "-"),
            ("Bag", item.bag),
            ("Slot", item.slot),
            ("Model ID", item.model_id),
            ("Model File ID", item.model_file_id),
            ("Item Type", item.item_type),
            ("Target Type", item.target_item_type),
            ("Rarity", item.rarity),
            ("Profession", item.profession),
            ("Quantity", item.quantity),
            ("Uses", item.uses),
            ("Value", item.value),
            ("Requirement", item.requirement),
            ("Attribute", item.attribute),
            ("Min Damage", item.min_damage),
            ("Max Damage", item.max_damage),
            ("Armor", item.armor),
            ("Energy", item.energy),
            ("Color", item.color),
            ("Stackable", item.is_stackable),
            ("Weapon", item.is_weapon),
            ("Armor Item", item.is_armor),
            ("Identified", item.is_identified),
            ("Customized", item.is_customized),
            ("Inscribable", item.is_inscribable),
            ("Prefix Upgradable", item.is_prefix_upgradable),
            ("Suffix Upgradable", item.is_suffix_upgradable),
            ("Usable", item.is_usable),
            ("Salvageable", item.is_salvageable),
            ("Salvage Kit", item.is_salvage_kit),
            ("Perfect Salvage Kit", item.is_perfect_salvage_kit),
            ("Inventory Item", item.is_inventory_item),
            ("Storage Item", item.is_storage_item),
            ("Material", item.is_material),
            ("Rare Material", item.is_rare_material),
            ("Material Salvageable", item.is_material_salvageable),
        ]

        PyImGui.set_next_window_size((520, 0), cond=PyImGui.ImGuiCond.Appearing)
        ImGui.begin_tooltip()
        ImGui.text(item.complete_name or item.singular_name or item.name or f"Item {item.id}", font_size=16)
        ImGui.separator()

        if ImGui.begin_table(
            f"##item_snapshot_tooltip_{item.id}",
            2,
            PyImGui.TableFlags.BordersInnerV | PyImGui.TableFlags.SizingStretchProp,
        ):
            PyImGui.table_setup_column("Field", PyImGui.TableColumnFlags.WidthFixed, 170)
            PyImGui.table_setup_column("Value")

            for label, value in rows:
                PyImGui.table_next_row()
                PyImGui.table_next_column()
                ImGui.text_colored(label, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                PyImGui.table_next_column()
                ImGui.text_wrapped(UI._format_snapshot_value(value))

            ImGui.end_table()

        ImGui.end_tooltip()

    @staticmethod
    def _prefer_lower_model_id(existing_item: ItemData | None, candidate_item: ItemData) -> ItemData:
        if existing_item is None:
            return candidate_item

        existing_model_id = int(getattr(existing_item, "model_id", -1))
        candidate_model_id = int(getattr(candidate_item, "model_id", -1))

        if existing_model_id <= 0:
            return candidate_item if candidate_model_id > 0 else existing_item
        if candidate_model_id <= 0:
            return existing_item

        return candidate_item if candidate_model_id < existing_model_id else existing_item

    @staticmethod
    def _draw_item_action_texture(item_action : ItemAction, size: tuple[float, float] = (32, 32)) -> None:
        path = os.path.join(UI.PROJECT_PATH, "Sources", "frenkeyLib", "Core", "textures", f"item_actions.png")         
        step = 1.0 / 14
        uv = ((item_action.value - 1) * step, 0.0, item_action.value * step, 1)
        if uv:
            UI._draw_texture_or_dummy(path, size, uv0=uv[:2], uv1=uv[2:])
        else:
            UI._draw_texture_or_dummy(None, size)
            
    @staticmethod
    def _draw_item_texture(item: Optional[ItemData], size: tuple[float, float] = (32, 32)) -> None:
        UI._draw_texture_from_model_file_id(getattr(item, "model_file_id", -1), size)
        # texture = get_texture_for_model(item.model_id) if item and getattr(item, "model_id", -1) > 0 else None
        # if texture and "0-File_Not_found.png" in texture:
        #     texture = None

        # UI._draw_texture_or_dummy(texture, size)

    def _rebuild_item_ui_caches(self) -> None:
        from Sources.frenkeyLib.DataCollector.collectors.items_collector import ITEMS
        
        all_items = self._get_all_item_data()
        self._all_item_data_cache = all_items

        self._item_by_model_file_id = {}
        self._item_by_model_id = {}
        self._item_by_model_id_and_item_type = {}
        self._item_by_model_file_id_and_item_type = {}
        self._item_by_encoded_name = {}
        encoded_name_items: dict[tuple[ItemType, str], ItemData] = {}
        model_file_id_items: dict[tuple[ItemType, int], ItemData] = {}
        salvage_materials: list[ItemData] = []
        for item in all_items:
            model_id = int(getattr(item, "model_id", -1))
            item_type = getattr(item, "item_type", ItemType.Unknown)
            model_file_id = int(getattr(item, "model_file_id", -1))
            encoded_name = self._get_item_encoded_name_string(item)

            if model_file_id > 0:
                self._item_by_model_file_id[model_file_id] = self._prefer_lower_model_id(
                    self._item_by_model_file_id.get(model_file_id),
                    item,
                )

            if model_id > 0:
                self._item_by_model_id[model_id] = self._prefer_lower_model_id(
                    self._item_by_model_id.get(model_id),
                    item,
                )

            if model_id > 0:
                key = (model_id, item_type)
                self._item_by_model_id_and_item_type[key] = self._prefer_lower_model_id(
                    self._item_by_model_id_and_item_type.get(key),
                    item,
                )

            if model_file_id > 0:
                key = (model_file_id, item_type)
                self._item_by_model_file_id_and_item_type[key] = self._prefer_lower_model_id(
                    self._item_by_model_file_id_and_item_type.get(key),
                    item,
                )

            if item.name_encoded and item.name_encoded not in self._item_by_encoded_name:
                self._item_by_encoded_name[item.name_encoded] = item

            if encoded_name:
                encoded_name_items.setdefault((item_type, encoded_name), item)

            if model_file_id > 0:
                key = (item_type, model_file_id)
                model_file_id_items[key] = self._prefer_lower_model_id(model_file_id_items.get(key), item)

            if item.category == "Material":
                salvage_materials.append(item)

        sort_key = lambda item: (self._get_item_display_name(item), self._item_type_name(item.item_type), int(getattr(item, "model_id", -1)))
        self._unique_encoded_name_items = sorted(encoded_name_items.values(), key=sort_key)
        self._unique_model_file_id_items = sorted(model_file_id_items.values(), key=sort_key)
        self._nick_cycle_items = sorted(
            [item for item in ITEMS.Nick_Cycle if item.weeks_until_next_nick is not None],
            key=lambda item: (cast(int, item.weeks_until_next_nick), self._get_item_display_name(item), item.model_id),
        )
        self._salvage_material_options = sorted(salvage_materials, key=lambda material: material.name)
        self._model_id_item_search_entries = [
            (
                item,
                self._build_search_blob(
                    item.name,
                    item.plural_name,
                    item.model_id,
                    item.item_type.name,
                    *(attribute.name for attribute in getattr(item, "attributes", [])),
                ),
            )
            for item in sorted(all_items, key=lambda item: item.name)
        ]
        self._encoded_name_search_entries = [
            (
                item,
                self._build_search_blob(
                    item.name,
                    item.plural_name,
                    self._get_item_encoded_name_string(item),
                    item.item_type.name,
                    item.model_id,
                ),
            )
            for item in self._unique_encoded_name_items
        ]
        self._model_file_id_search_entries = [
            (
                item,
                self._build_search_blob(
                    self._get_item_display_name(item),
                    item.plural_name,
                    item.model_file_id,
                    item.item_type.name,
                    item.model_id,
                ),
            )
            for item in self._unique_model_file_id_items
        ]
        self._salvage_material_search_entries = [
            (
                material,
                self._build_search_blob(material.name, material.plural_name, int(material.model_id)),
            )
            for material in self._salvage_material_options
        ]
        self._model_id_search_entries = [
            (
                model_id,
                self._build_search_blob(model_id.name, int(model_id.value)),
            )
            for model_id in self._sorted_model_ids
        ]
        self._model_id_search_cache.clear()
        self._encoded_name_search_cache.clear()
        self._model_file_id_search_cache.clear()
        self._model_id_item_search_cache.clear()
        self._nick_item_preview_cache.clear()
        self._salvage_material_search_cache.clear()
        self._live_search_normalized_cache.clear()
        self._live_search_results_cache.clear()
        
        self.cache_timestamp = ITEMS.last_change

    def _rebuild_upgrade_ui_caches(self) -> None:
        self._armor_upgrade_types_by_profession = {
            profession: sorted(
                [
                    upgrade_type
                    for upgrade_type in self.available_upgrade_types
                    if issubclass(upgrade_type, ArmorUpgrade) and getattr(upgrade_type, "profession", None) == profession
                ],
                key=lambda upgrade_type: (getattr(upgrade_type, "rarity", 0), self._format_upgrade_type_label(upgrade_type)),
            )
            for profession in Profession
        }
        self._weapon_upgrade_types_by_mod_type = {
            mod_type: sorted(
                [
                    upgrade_type
                    for upgrade_type in self.available_upgrade_types
                    if (issubclass(upgrade_type, WeaponUpgrade) or issubclass(upgrade_type, Inscription))
                    and getattr(upgrade_type, "mod_type", None) == mod_type
                ],
                key=lambda upgrade_type: self._format_upgrade_type_label(upgrade_type),
            )
            for mod_type in (ItemUpgradeType.Prefix, ItemUpgradeType.Suffix, ItemUpgradeType.Inscription)
        }
        self._inherent_option_entries = []
        for inherent_type in self.available_inherent_upgrade_types:
            inherent = inherent_type()
            if not isinstance(inherent, Inherent):
                continue

            label = inherent.name_plain or self._humanize_name(inherent_type.__name__)
            description = inherent.description_plain
            self._inherent_option_entries.append(
                (
                    inherent_type,
                    label,
                    description,
                    self._build_search_blob(label, description, inherent_type.__name__),
                )
            )

        self._range_upgrade_option_entries = [
            (
                upgrade_type,
                instruction,
                self._build_search_blob(self._format_upgrade_type_label(upgrade_type), upgrade_type().__class__.__name__, upgrade_type().description_plain, instruction.target),
            )
            for upgrade_type, instruction in self._get_range_upgrade_options()
        ]
        self._inherent_search_cache.clear()
        self._range_upgrade_search_cache.clear()
        self._live_search_normalized_cache.clear()
        self._live_search_results_cache.clear()

    def _get_filtered_inherent_option_entries(self, search_query: str) -> list[tuple[type[Upgrade], str, str]]:
        entries: list[tuple[type[Upgrade], str, str, str]] = []
        for inherent_type in self.available_inherent_upgrade_types:
            inherent = inherent_type()
            if not isinstance(inherent, Inherent):
                continue

            label = inherent.name_plain or self._humanize_name(inherent_type.__name__)
            description = inherent.description_plain
            entries.append(
                (
                    inherent_type,
                    label,
                    description,
                    self._build_search_blob(label, description, inherent_type.__name__),
                )
            )

        if not search_query:
            return [(inherent_type, label, description) for inherent_type, label, description, _ in entries]

        return [
            (inherent_type, label, description)
            for inherent_type, label, description, search_blob in entries
            if self._search_blob_matches(search_query, search_blob)
        ]

    def _get_armor_upgrade_types_for_profession(self, profession: Profession) -> list[type[Upgrade]]:
        return self._armor_upgrade_types_by_profession.get(profession, [])

    def _get_all_armor_upgrade_types(self) -> list[type[Upgrade]]:
        all_upgrade_types: list[type[Upgrade]] = []
        seen_upgrade_types: set[type[Upgrade]] = set()

        for profession in Profession:
            for upgrade_type in self._get_armor_upgrade_types_for_profession(profession):
                if upgrade_type in seen_upgrade_types:
                    continue

                seen_upgrade_types.add(upgrade_type)
                all_upgrade_types.append(upgrade_type)

        return all_upgrade_types

    def _get_weapon_upgrade_types_for_mod_type(self, mod_type: ItemUpgradeType) -> list[type[Upgrade]]:
        return self._weapon_upgrade_types_by_mod_type.get(mod_type, [])

    def _get_filtered_range_upgrade_options(self, search_query: str) -> list[tuple[type[WeaponUpgrade | Inscription], RangeInstruction]]:
        entries = [
            (
                upgrade_type,
                instruction,
                self._build_search_blob(
                    self._format_upgrade_type_label(upgrade_type),
                    upgrade_type().__class__.__name__,
                    upgrade_type().description_plain,
                    instruction.target,
                ),
            )
            for upgrade_type, instruction in self._get_range_upgrade_options()
        ]

        if not search_query:
            return [(upgrade_type, instruction) for upgrade_type, instruction, _ in entries]

        return [
            (upgrade_type, instruction)
            for upgrade_type, instruction, search_blob in entries
            if self._search_blob_matches(search_query, search_blob)
        ]

    def _find_item_by_model_file_id(self, model_file_id: int, item_type: ItemType | None = None) -> ItemData | None:
        if item_type is not None:
            typed_item = self._item_by_model_file_id_and_item_type.get((int(model_file_id), item_type))
            if typed_item is not None:
                return typed_item

        return self._item_by_model_file_id.get(int(model_file_id))

    def _find_item_by_model_id(self, model_id: int, item_type: ItemType | None = None) -> ItemData | None:
        if item_type is not None:
            typed_item = self._item_by_model_id_and_item_type.get((int(model_id), item_type))
            if typed_item is not None:
                return typed_item

        return self._item_by_model_id.get(int(model_id))

    def _find_item_by_model_file_id_and_item_type(self, model_file_id: int, item_type: ItemType) -> ItemData | None:
        return self._find_item_by_model_file_id(model_file_id, item_type)

    def _find_item_by_encoded_name(self, encoded_name: bytes) -> ItemData | None:
        return self._item_by_encoded_name.get(encoded_name)

    def _get_live_search_results(
        self,
        key: str,
        raw_query: str,
        resolver: Callable[[str], list[Any]],
    ) -> tuple[str, list[Any]]:
        normalized_entry = self._live_search_normalized_cache.get(key)
        if normalized_entry is None or normalized_entry[0] != raw_query:
            search_query = self._normalize_search_query(raw_query)
            self._live_search_normalized_cache[key] = (raw_query, search_query)
        else:
            search_query = normalized_entry[1]

        result_entry = self._live_search_results_cache.get(key)
        if result_entry is None or result_entry[0] != search_query:
            results = resolver(search_query)
            self._live_search_results_cache[key] = (search_query, results)
        else:
            results = result_entry[1]

        return search_query, results

    def _get_search_field_value(self, key: str) -> str:
        return self._search_field_state.get(key, '')

    def _set_search_field_value(self, key: str, value: str) -> str:
        self._search_field_state[key] = value
        return value

    def _clear_search_field_value(self, key: str) -> None:
        self._search_field_state.pop(key, None)

    def _get_recalculated_value(
        self,
        key: str,
        signature: Any,
        calculator: Callable[[], TConfig],
    ) -> TConfig:
        entry = self._recalculation_cache.get(key)
        if entry is None or entry.signature != signature:
            value = calculator()
            self._recalculation_cache[key] = RecalculationCacheEntry(signature=signature, value=value)
            return value

        return cast(TConfig, entry.value)

    @staticmethod
    def _build_inherent_filter_condition_signature(condition: InherentFiltersCondition) -> tuple[Any, ...]:
        return tuple(
            sorted(
                (
                    type(inherent_filter.inherent).__name__,
                    tuple(
                        sorted(
                            (target, value_range.min_value, value_range.max_value)
                            for target, value_range in inherent_filter.ranges.items()
                        )
                    ),
                )
                for inherent_filter in condition.inherents
            )
        )

    def _build_inherent_condition_row_states(
        self,
        condition: InherentFiltersCondition,
        inherent_entries: list[tuple[type[Upgrade], str, str]],
    ) -> list[InherentConditionRowState]:
        selected_by_type: dict[type[Upgrade], InherentFilter] = {
            type(inherent_filter.inherent): inherent_filter
            for inherent_filter in condition.inherents
        }

        row_states: list[InherentConditionRowState] = []
        for inherent_type, label, description in inherent_entries:
            inherent = inherent_type()
            if not isinstance(inherent, Inherent):
                continue

            row_states.append(
                InherentConditionRowState(
                    inherent_type=inherent_type,
                    inherent=inherent,
                    label=label,
                    description=description,
                    range_instructions=tuple(self._get_range_instructions(inherent)),
                    inherent_filter=selected_by_type.get(inherent_type),
                    description_text_size=PyImGui.calc_text_size(description),
                )
            )

        return row_states

    @staticmethod
    def _build_bytes_signature(values: set[bytes] | list[bytes] | tuple[bytes, ...]) -> tuple[bytes, ...]:
        return tuple(sorted(values))

    @staticmethod
    def _build_int_signature(values: set[int] | list[int] | tuple[int, ...]) -> tuple[int, ...]:
        return tuple(sorted(int(value) for value in values))

    def _build_encoded_name_candidate_rows(
        self,
        matching_items: list[ItemData],
        selected_encoded_names: set[bytes],
    ) -> list[tuple[ItemData, bytes, str]]:
        rows: list[tuple[ItemData, bytes, str]] = []
        for item in matching_items:
            if item.name_encoded in selected_encoded_names:
                continue

            rows.append((item, item.name_encoded, self._get_item_display_name(item)))

        return rows

    def _build_model_file_id_candidate_rows(
        self,
        matching_items: list[ItemData],
        selected_model_file_ids: set[int],
    ) -> list[tuple[ItemData, int, str]]:
        return [
            (item, int(item.model_file_id), self._get_item_display_name(item))
            for item in matching_items
            if int(item.model_file_id) not in selected_model_file_ids
        ]

    def _build_model_file_id_item_type_candidate_rows(
        self,
        matching_items: list[ItemData],
        selected_entries: set[tuple[int, ItemType]],
    ) -> list[tuple[ItemData, tuple[int, ItemType], str]]:
        return [
            (item, (int(item.model_file_id), item.item_type), self._get_item_display_name(item))
            for item in matching_items
            if (int(item.model_file_id), item.item_type) not in selected_entries
        ]

    def _build_model_id_item_type_candidate_rows(
        self,
        matching_items: list[ItemData],
        selected_entries: set[tuple[int, ItemType]],
    ) -> list[tuple[ItemData, tuple[int, ItemType], str]]:
        return [
            (item, (int(item.model_id), item.item_type), item.name or f"Model {item.model_id}")
            for item in matching_items
            if (int(item.model_id), item.item_type) not in selected_entries
        ]

    def _build_salvage_material_candidate_rows(
        self,
        matching_materials: list[ItemData],
        selected_materials: set[int],
    ) -> list[tuple[ItemData, int, str]]:
        return [
            (material, int(material.model_id), material.name)
            for material in matching_materials
            if int(material.model_id) not in selected_materials
        ]

    @staticmethod
    def _format_nick_weeks_label(weeks_until_next_nick: int) -> str:
        if weeks_until_next_nick <= 0:
            return "current week"
        if weeks_until_next_nick == 1:
            return "next week"
        return f"{weeks_until_next_nick} weeks"

    @staticmethod
    def _get_nick_weeks_color(weeks_until_next_nick: int) -> tuple[float, float, float, float]:
        if weeks_until_next_nick <= 0:
            return (0.2, 1.0, 0.2, 1.0)
        if weeks_until_next_nick <= 4:
            return (0.45, 0.95, 0.2, 1.0)
        if weeks_until_next_nick <= 12:
            return (0.95, 0.85, 0.2, 1.0)
        return (1.0, 0.65, 0.2, 1.0)

    def _get_nick_item_preview_items(self, weeks_before_next_cycle: int) -> list[ItemData]:
        clamped_weeks = max(0, min(NICK_CYCLE_COUNT, int(weeks_before_next_cycle)))
        cached = self._nick_item_preview_cache.get(clamped_weeks)
        if cached is not None:
            return cached

        result = [
            item
            for item in self._nick_cycle_items
            if item.weeks_until_next_nick is not None and item.weeks_until_next_nick <= clamped_weeks
        ]
        self._nick_item_preview_cache[clamped_weeks] = result
        return result

    @staticmethod
    def _get_requirement_popup_attributes(item_type: Optional[ItemType]) -> list[Attribute]:
        if item_type is None:
            return []
        
        attribute_s = UI.META_ITEM_TYPE_ATTRIBUTES.get(item_type)
        
        if attribute_s is None:
            attribute_s = next((UI.META_ITEM_TYPE_ATTRIBUTES.get(itype) for itype in UI.META_ITEM_TYPE_ATTRIBUTES if item_type in itype.item_types), None)
            
        if attribute_s is None:
            attribute_s = next((UI.META_ITEM_TYPE_ATTRIBUTES.get(sub_type) for sub_type in item_type.item_types), None)
        
        return attribute_s if isinstance(attribute_s, list) else [attribute_s] if attribute_s is not None else []

    @staticmethod
    def _get_requirement_popup_attributes_for_requirement(item_type: Optional[ItemType], requirement_level: int) -> list[Attribute]:
        return UI._get_requirement_popup_attributes(item_type)

    @staticmethod
    def _apply_weapon_requirement_row_defaults(requirement: AttributeRequirement, item_type: ItemType, requirement_level: int) -> None:
        requirement.weapon_type = item_type
        requirement.attribute_level = requirement_level

        valid_attributes = UI._get_requirement_popup_attributes_for_requirement(item_type, requirement_level)
        
        if len(valid_attributes) == 1:
            requirement.attributes = [valid_attributes[0]]
        else:
            requirement.attributes = [attribute for attribute in requirement.attributes if attribute in valid_attributes]

        requirement.apply_max_ranges(item_type)

    @staticmethod
    def _get_default_weapon_value_range(item_type: Optional[ItemType], requirement: int) -> Optional[tuple[int, int]]:
        if item_type is None:
            return None

        return ITEM_DAMAGE_RANGES.get(item_type, {}).get(min(requirement, 9))

    @staticmethod
    def _get_item_data_texture(item: Optional[ItemData]) -> str:
        if not item:
            return ""
        
        match UI.GENDER:
            case Gender.Male:
                return item.male_texture_path or ""
            
            case Gender.Female:
                return item.female_texture_path or ""
            
            case _:
                return item.real_texture_path or ""
            
    @staticmethod
    def _get_texture_path_for_model_file_id_direct(model_file_id: Optional[int]) -> str:
        return f"gwdat://{int(model_file_id)}" if model_file_id is not None and int(model_file_id) > 0 else ""
    
    @staticmethod
    def _get_texture_path_for_model_file_id(model_file_id: Optional[int]) -> str:
        model_file_id = Item.GetTrueModelFileID(model_file_id) if model_file_id is not None else None
        return f"gwdat://{int(model_file_id)}" if model_file_id is not None and int(model_file_id) > 0 else ""
    
    @staticmethod
    def _draw_texture_from_model_file_id(model_file_id: Optional[int], size: tuple[float, float]) -> None:
        model_file_texture = UI._get_texture_path_for_model_file_id(model_file_id)
        UI._draw_texture_or_dummy(model_file_texture, size)

    @staticmethod
    def _draw_texture_or_dummy(texture: Optional[str], size: tuple[float, float], 
                            uv0: tuple[float, float] = (0.0, 0.0),
                            uv1: tuple[float, float] = (1.0, 1.0),
                            tint: tuple[int, int, int, int] = (255, 255, 255, 255),
                            border_color: tuple[int, int, int, int] = (0, 0, 0, 0)) -> None:
        if texture is not None and texture != "":
            ImGui.image(texture, size, uv0, uv1, tint, border_color)
        else:
            ImGui.dummy(*size)

    @staticmethod
    def _get_rarity_color(rarity) -> Color:
        rarity_colors = {
            Rarity.White: Color(255, 255, 255, 255),
            Rarity.Blue: Color(153, 238, 255, 255),
            Rarity.Green: Color(0, 255, 0, 255),
            Rarity.Purple: Color(187, 136, 238, 255),
            Rarity.Gold: Color(255, 204, 85, 255),
        }

        if (rarity in rarity_colors):
            return rarity_colors[rarity]
        else:
            return ColorPalette.GetColor("white")

    # -------------------------------------------------------------------------
    # Upgrade editor helpers
    # -------------------------------------------------------------------------
    def _expand_item_type(self, item_type: ItemType) -> list[ItemType]:
        expanded = ITEM_TYPE_META_TYPES.get(item_type)
        if expanded is None:
            return [item_type] if item_type != ItemType.Unknown else []

        concrete_item_types: list[ItemType] = []
        for nested_item_type in expanded:
            for concrete_item_type in self._expand_item_type(nested_item_type):
                if concrete_item_type not in concrete_item_types:
                    concrete_item_types.append(concrete_item_type)

        return concrete_item_types

    def _get_allowed_item_types(self, upgrade: Upgrade) -> list[ItemType]:
        allowed_item_types: list[ItemType] = []

        for item_type in type(upgrade).id.item_type_id_map.keys():
            for concrete_item_type in self._expand_item_type(item_type):
                if concrete_item_type not in allowed_item_types:
                    allowed_item_types.append(concrete_item_type)

        if len(allowed_item_types) == 0:
            return []

        return allowed_item_types

    def _get_trader_armor_upgrade_quotes(self, filter_by_profession: bool = True) -> list[TraderQuote]:
        trader_output = TraderPriceCheckManager.get_output()
        quotes = [quote for quote in trader_output.quotes.values() if quote.is_rune_mod]

        if filter_by_profession and self.profession != Profession._None:
            quotes = [quote for quote in quotes if quote.profession in (self.profession, Profession._None)]

        return quotes

    @staticmethod
    def _upgrade_equals(left: ArmorUpgrade, right: ArmorUpgrade) -> bool:
        return left._comparison_data() == right._comparison_data()

    def _extract_armor_upgrades_from_trader_quote(self, quote: TraderQuote) -> list[ArmorUpgrade]:
        prefix, suffix, inscription, inherent = ItemMod.get_item_upgrades(quote.item_id)
        upgrades = [upgrade for upgrade in [prefix, suffix, inscription, *(inherent or [])] if isinstance(upgrade, ArmorUpgrade)]

        # PySystem.Console.Log(
        #     "Item Manager",
        #     f"Parsed {len(upgrades)} armor upgrades from trader item {quote.item_id} ('{quote.name}') model={quote.model_id}.",
        #     PySystem.Console.MessageType.Info,
        # )

        # for upgrade in upgrades:
        #     PySystem.Console.Log(
        #         "Item Manager",
        #         f"Parsed trader upgrade '{upgrade.name_plain}' ({type(upgrade).__name__}) from item {quote.item_id}.",
        #         PySystem.Console.MessageType.Info,
        #     )

        return upgrades

    def _get_armor_upgrade_quote_lookup(self, filter_by_profession: bool = True) -> dict[Any, TraderQuote]:
        quotes = self._get_trader_armor_upgrade_quotes(filter_by_profession=filter_by_profession)
        generation = TraderPriceCheckManager.get_generation()

        if not filter_by_profession:
            quote_lookup: dict[Any, TraderQuote] = {}
            for quote in quotes:
                for parsed_upgrade in self._extract_armor_upgrades_from_trader_quote(quote):
                    comparison_key = parsed_upgrade._comparison_data()
                    current_quote = quote_lookup.get(comparison_key)
                    if current_quote is None or quote.quoted_value > current_quote.quoted_value:
                        quote_lookup[comparison_key] = quote
            return quote_lookup

        if (
            self._armor_upgrade_quote_cache_generation != generation
            or self._armor_upgrade_quote_cache_profession != self.profession
        ):
            self._armor_upgrade_quote_cache_generation = generation
            self._armor_upgrade_quote_cache_profession = self.profession
            self._armor_upgrade_quote_cache_processed_item_ids.clear()
            self._armor_upgrade_quote_cache = {}

        current_quote_ids = {quote.item_id for quote in quotes}
        if not current_quote_ids.issuperset(self._armor_upgrade_quote_cache_processed_item_ids):
            self._armor_upgrade_quote_cache_processed_item_ids.clear()
            self._armor_upgrade_quote_cache = {}

        for quote in quotes:
            if quote.item_id in self._armor_upgrade_quote_cache_processed_item_ids:
                continue

            for parsed_upgrade in self._extract_armor_upgrades_from_trader_quote(quote):
                comparison_key = parsed_upgrade._comparison_data()
                current_quote = self._armor_upgrade_quote_cache.get(comparison_key)
                if current_quote is None or quote.quoted_value > current_quote.quoted_value:
                    self._armor_upgrade_quote_cache[comparison_key] = quote
            self._armor_upgrade_quote_cache_processed_item_ids.add(quote.item_id)

        return self._armor_upgrade_quote_cache

    def _get_trader_quote_for_armor_upgrade(
        self,
        upgrade: ArmorUpgrade,
        filter_by_profession: bool = True,
    ) -> TraderQuote | None:
        return self._get_armor_upgrade_quote_lookup(filter_by_profession=filter_by_profession).get(upgrade._comparison_data())

    def _get_range_instructions(self, upgrade: Upgrade) -> list[RangeInstruction]:
        return [instruction for instruction in type(upgrade).upgrade_info if isinstance(instruction, RangeInstruction)]

    def _get_range_instruction(self, upgrade: Upgrade, target: str) -> RangeInstruction | None:
        return next((instruction for instruction in self._get_range_instructions(upgrade) if instruction.target == target), None)

    def _get_range_upgrade_options(self) -> list[tuple[type[WeaponUpgrade | Inscription], RangeInstruction]]:
        options: list[tuple[type[WeaponUpgrade | Inscription], RangeInstruction]] = []
        for upgrade_type in self.available_upgrade_types:
            if not issubclass(upgrade_type, (WeaponUpgrade, Inscription)):
                continue

            range_instructions = [instruction for instruction in upgrade_type.upgrade_info if isinstance(instruction, RangeInstruction)]
            for instruction in range_instructions:
                options.append((upgrade_type, instruction))

        return sorted(
            options,
            key=lambda option: (
                self._format_upgrade_type_label(option[0]),
                self._humanize_name(option[1].target),
            ),
        )

    def _convert_str_to_encoded_bytes(self, text: str) -> bytes:
        try:
            return bytes(int(x, 16) for x in text.replace(",", " ").split())
        except ValueError:
            return text.encode("utf-8")
        
    def draw_main_window(self) -> None:
        active_rule_drag = self._drag_rule_source_config is self.config and self._drag_rule is not None
        active_condition_drag = self._drag_condition_source_rule is self.rule and self._drag_condition is not None
        active_sorting_drag = self._drag_sorting_group_source_config is self.config and self._drag_sorting_group is not None
        active_drag = active_rule_drag or active_condition_drag or active_sorting_drag
        
        if active_drag and self._drag_window_pos is not None:
            PyImGui.set_next_window_pos(self._drag_window_pos, PyImGui.ImGuiCond.Always)
            
        expanded, open_ = ImGui.BeginWithClose(
            ini_key=self.module_config.main_ini_key,
            name="Item Manager",
            p_open=self.floating_button.visible,
        )
        self.floating_button.sync_begin_with_close(open_)

        if expanded:
            if self.queue_data_refresh_on_main_window_open:
                from Sources.frenkeyLib.DataCollector.collectors.items_collector import ITEMS
                
                if ITEMS.last_change != self.cache_timestamp:
                    PySystem.Console.Log("Item Manager", "Refreshing item and upgrade data caches after main window opened.", PySystem.Console.MessageType.Info)
                    self._rebuild_item_ui_caches()
                    self._rebuild_upgrade_ui_caches()
                    self.queue_data_refresh_on_main_window_open = False
                
            mouse_down = PyImGui.is_mouse_down(0)
            time_now = time.monotonic()
            
            if self._drag_start_time == 0 and mouse_down:
                self._drag_start_time = time_now
            
            elif not mouse_down:
                self._drag_start_time = 0
                self._dragging = False
                self._drag_clicked_item = None
            
            else:
                self._dragging = self._drag_start_time > 0 and (time_now - self._drag_start_time) >= 0.085
            
            self.main_window_focused = PyImGui.is_window_focused()
            self.window_pos = PyImGui.get_window_pos()
            self.draw_explorer()
            
            preview_config = self._get_config_info_by_type(self.preview_window_config_type)
            if self.show_preview_window and preview_config is not None:
                self.draw_preview_window(preview_config)

            manage_config = self._get_config_info_by_type(self.manage_profile_window_config_type)
            if self.show_manage_profile_window and manage_config is not None:
                self._draw_manage_profile_window(manage_config)
            
        ImGui.End(self.module_config.main_ini_key)
        
        if active_rule_drag:
            self._draw_rule_drag_preview()
            
        if active_condition_drag:
            self._draw_condition_drag_preview()
            
        if active_sorting_drag:
            self._draw_sorting_group_drag_preview()

        
    def draw(self):
        self.floating_button.draw(self.module_config.floating_ini_key)
        
        if not self.floating_button.visible:
            self.queue_data_refresh_on_main_window_open = True

    def _get_active_config_info(self, config_info: ConfigInfo | None = None) -> ConfigInfo | None:
        return config_info or self.config

    def _get_config_info_by_type(self, config_type: str) -> ConfigInfo | None:
        normalized_config_type = str(config_type or '').strip()
        for config_info in self.configs:
            if config_info.config_type == normalized_config_type:
                return config_info
        return None

    def _get_config_type_options(self) -> list[ConfigInfo]:
        return self.configs

    def _sync_selected_rule(self) -> None:
        active_config = self._get_active_config_info()
        if active_config is None or not isinstance(active_config.config, RuleConfig):
            self._set_active_rule(None)
            return

        if self.rule not in active_config.config:
            self._set_active_rule(active_config.config[0] if len(active_config.config) > 0 else None)

    def _sync_selected_sorting_group(self) -> None:
        active_config = self._get_active_config_info()
        if active_config is None or not isinstance(active_config.config, SortingConfig):
            self._set_active_sorting_group(None)
            return

        if self.sorting_group is not None and self.sorting_group not in active_config.config.slot_groups:
            self._set_active_sorting_group(active_config.config.slot_groups[0] if len(active_config.config.slot_groups) > 0 else None)

    def _save_active_config(self) -> None:
        active_config = self._get_active_config_info()
        if active_config is not None:
            active_config.save()

    def _save_all_configs(self) -> None:
        for config_info in self.configs:
            config_info.save()

    def _reload_all_configs(self) -> None:
        self.profile_manager.sync_loaded_configs(force=True)
        self._update_profile_context_signatures()
        self._after_global_config_reload()

    def _reset_selected_config_state(self) -> None:
        self.rule = None
        self.rule_index = None
        self.sorting_group = None
        self.sorting_group_index = None

    def _after_global_config_reload(self) -> None:
        self._reset_selected_config_state()
        self._sync_selected_rule()
        self._sync_selected_sorting_group()
        self._refresh_sorting_assigned_slot_cache()
        self._reset_manual_inventory_bt()
        self._invalidate_inventory_preview_cache()
        self._invalidate_sorting_preview_cache()

    def _profile_context_signature(self, config_type: str) -> tuple[str, str, str]:
        return (
            self.profile_manager.get_current_character(),
            self.profile_manager.get_active_profile_name(config_type),
            self.profile_manager.get_active_config_file_path(config_type),
        )

    def _update_profile_context_signatures(self) -> None:
        for config_info in self.configs:
            self._last_seen_profile_context_signatures[config_info.config_type] = self._profile_context_signature(config_info.config_type)

    def _watch_global_config_profile_context(self) -> None:
        if not self._profile_context_refresh_timer.IsExpired():
            return

        self._profile_context_refresh_timer.Reset()
        profile_context_changed = False
        for config_info in self.configs:
            config_type = config_info.config_type
            next_signature = self._profile_context_signature(config_type)
            if self._last_seen_profile_context_signatures.get(config_type) != next_signature:
                self._last_seen_profile_context_signatures[config_type] = next_signature
                profile_context_changed = True

        if profile_context_changed:
            self._after_global_config_reload()

    def _invalidate_sorting_preview_cache(self) -> None:
        self.sorting_preview_plan = None
        self._sorting_preview_cache_key = None
        self._sorting_preview_plan_tree = None
        self._sorting_preview_plan_status = ''
        self._sorting_preview_plan_error = ''
        self.sorting_preview_throttle.Reset()

    def _invalidate_inventory_preview_cache(self) -> None:
        self.preview_entries = None

    def _reset_manual_inventory_bt(self) -> None:
        self._manual_inventory_bt = None
        self._manual_inventory_bt_config_id = None
        self._manual_inventory_tick_status = ''
        self._manual_inventory_tick_repeat_timer.Stop()

    def _get_manual_inventory_bt(self, config: InventoryConfig) -> InventoryBT:
        config_id = id(config)
        if self._manual_inventory_bt is None or self._manual_inventory_bt_config_id != config_id:
            self._manual_inventory_bt = InventoryBT(config)
            self._manual_inventory_bt_config_id = config_id
            self._manual_inventory_tick_status = 'Ready'
            self._manual_inventory_tick_repeat_timer.Stop()
        return self._manual_inventory_bt

    def _tick_inventory_bt_once(self, config: InventoryConfig) -> None:
        inventory_bt = self._get_manual_inventory_bt(config)
        state = inventory_bt.tick()
        self._manual_inventory_tick_status = f'Last tick: {state.name}'
        self._manual_inventory_tick_repeat_timer.Reset()
        self._invalidate_inventory_preview_cache()

    @staticmethod
    def _build_sorting_preview_cache_key(config: SortingConfig, bags: list[Bags]) -> tuple[tuple[int, ...], str]:
        normalized_bags = tuple(sorted((int(bag.value) for bag in bags)))
        config_signature = json.dumps(config.to_dict(), sort_keys=True, ensure_ascii=False)
        return normalized_bags, config_signature

    def _handle_config_saved(self, config_info: ConfigInfo[Any]) -> None:
        if isinstance(config_info.config, SortingConfig):
            self._refresh_sorting_assigned_slot_cache()
            self._invalidate_sorting_preview_cache()
        GlobalConfigProfileManager.broadcast_reload(config_info.config_type)

    def _switch_global_config_profile(self, profile_name: str, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        self._save_all_configs()
        
        self.profile_manager.refresh(force=True)
        
        if self.profile_manager.set_profile_for_current_character(target_config.config_type, profile_name):
            self.profile_manager.ensure_active_config_folder(target_config.config_type)
            self._profile_context_refresh_timer.Reset()
            self._reload_all_configs()
            self.config = target_config

    def _create_global_config_profile(self, profile_name: str, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        created_profile_name = self.profile_manager.create_profile(
            target_config.config_type,
            profile_name,
            source_profile_name=self.profile_manager.get_active_profile_name(target_config.config_type),
            overwrite_existing=True,
        )
        if created_profile_name is None:
            return

        self.global_config_new_profile_name = ''
        self._switch_global_config_profile(created_profile_name, target_config)

    def _create_empty_global_config_profile(self, profile_name: str, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        normalized_profile_name = GlobalConfigProfileManager.sanitize_profile_name(profile_name)
        if normalized_profile_name == '' or normalized_profile_name == GlobalConfigProfileManager.SHARED_PROFILE_NAME:
            return

        self.profile_manager.refresh(force=True)
        if self.profile_manager.profile_exists(target_config.config_type, normalized_profile_name):
            return

        created_profile_name = self.profile_manager.create_profile(
            target_config.config_type,
            normalized_profile_name,
            source_profile_name=None,
            overwrite_existing=False,
        )
        if created_profile_name is None:
            return

        self._empty_profile_name = ''
        self._switch_global_config_profile(created_profile_name, target_config)

    def _delete_global_config_profile(self, profile_name: str, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        if not self.profile_manager.delete_profile(target_config.config_type, profile_name):
            return

        GlobalConfigProfileManager.broadcast_reload(target_config.config_type)
        self._profile_context_refresh_timer.Reset()
        self._reload_all_configs()

    def _duplicate_global_config_profile(self, source_profile_name: str, target_profile_name: str, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        duplicated_profile_name = self.profile_manager.duplicate_profile(
            target_config.config_type,
            source_profile_name,
            target_profile_name,
        )
        if duplicated_profile_name is None:
            return

        GlobalConfigProfileManager.broadcast_reload(target_config.config_type)
        self._profile_context_refresh_timer.Reset()
        self._reload_all_configs()

    def _rename_global_config_profile(self, source_profile_name: str, target_profile_name: str, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        renamed_profile_name = self.profile_manager.rename_profile(
            target_config.config_type,
            source_profile_name,
            target_profile_name,
        )
        if renamed_profile_name is None:
            return

        GlobalConfigProfileManager.broadcast_reload(target_config.config_type)
        self._profile_context_refresh_timer.Reset()
        self._reload_all_configs()

    def _open_save_as_profile_popup(self, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        active_profile_name = self.profile_manager.get_active_profile_name(target_config.config_type)
        self.global_config_new_profile_name = '' if active_profile_name == GlobalConfigProfileManager.SHARED_PROFILE_NAME else active_profile_name
        self._save_as_profile_popup_requested = True

    def _open_empty_profile_popup(self, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        self.profile_manager.refresh(force=True)
        self._empty_profile_name = ''
        self._empty_profile_popup_requested = True

    def _draw_save_as_profile_popup(self, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return
        
        if self._save_as_profile_popup_requested:
            PyImGui.open_popup(f"Save {self._humanize_name(target_config.config_type)} as Profile##{self._save_as_profile_popup_id}")
            self._save_as_profile_popup_requested = False

        PyImGui.set_next_window_size((360, 0), PyImGui.ImGuiCond.Always)
        if not PyImGui.begin_popup_modal(f"Save {self._humanize_name(target_config.config_type)} as Profile##{self._save_as_profile_popup_id}", True, PyImGui.WindowFlags.AlwaysAutoResize):
            return

        ImGui.text_wrapped(f'Enter a name for the profile you want to create or overwrite for this config type. You can reuse an existing profile name to overwrite it with the current config values.')

        PyImGui.set_next_item_width(-1)
        self.global_config_new_profile_name = ImGui.input_text(
            'Profile Name',
            self.global_config_new_profile_name,
        )

        normalized_profile_name = GlobalConfigProfileManager.sanitize_profile_name(self.global_config_new_profile_name)
        overwrite_existing = normalized_profile_name != '' and self.profile_manager.profile_exists(target_config.config_type, normalized_profile_name)
        if overwrite_existing:
            ImGui.text_colored(
                'Warning: this profile already exists. Saving now will overwrite it.',
                color=UI.RED_COLOR.color_tuple,
                font_size=12,
            )

        btn_width = (PyImGui.get_window_content_region_max()[0] - 8) / 2
        create_disabled = normalized_profile_name == ''
        PyImGui.begin_disabled(create_disabled)        
        if ImGui.button('Overwrite' if overwrite_existing else 'Save As', btn_width):
            self._save_active_config()
            self._create_global_config_profile(self.global_config_new_profile_name, target_config)
            PyImGui.close_current_popup()
        PyImGui.end_disabled()

        PyImGui.same_line(0, 8)
        if ImGui.button('Cancel', btn_width):
            self.global_config_new_profile_name = ''
            PyImGui.close_current_popup()

        ImGui.show_tooltip('Creates a profile for this config type and assigns it to the current character. If the name already exists, it overwrites that profile.')
        PyImGui.end_popup_modal()

    def _draw_empty_profile_popup(self, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        popup_title = f"Create Empty {self._humanize_name(target_config.config_type)} Profile##{self._empty_profile_popup_id}"
        if self._empty_profile_popup_requested:
            PyImGui.open_popup(popup_title)
            self._empty_profile_popup_requested = False

        PyImGui.set_next_window_size((360, 0), PyImGui.ImGuiCond.Always)
        if not PyImGui.begin_popup_modal(popup_title, True, PyImGui.WindowFlags.AlwaysAutoResize):
            return

        ImGui.text_wrapped('Enter a name for the new empty profile. It will start without any saved rules or settings and be assigned to the current character.')

        PyImGui.set_next_item_width(-1)
        self._empty_profile_name = ImGui.input_text('Profile Name', self._empty_profile_name)

        normalized_profile_name = GlobalConfigProfileManager.sanitize_profile_name(self._empty_profile_name)
        is_shared_name = normalized_profile_name == GlobalConfigProfileManager.SHARED_PROFILE_NAME
        profile_exists = normalized_profile_name != '' and self.profile_manager.profile_exists(target_config.config_type, normalized_profile_name)

        if is_shared_name:
            ImGui.text_colored(
                'SHARED is reserved and cannot be created as a custom profile.',
                color=UI.RED_COLOR.color_tuple,
                font_size=12,
            )
        elif profile_exists:
            ImGui.text_colored(
                'A profile with this name already exists for this config type.',
                color=UI.RED_COLOR.color_tuple,
                font_size=12,
            )

        btn_width = (PyImGui.get_window_content_region_max()[0] - 8) / 2
        create_disabled = normalized_profile_name == '' or is_shared_name or profile_exists
        confirm_with_enter = not create_disabled and self._is_confirm_key_pressed()
        PyImGui.begin_disabled(create_disabled)
        if ImGui.button('Create Empty', btn_width) or confirm_with_enter:
            self._create_empty_global_config_profile(self._empty_profile_name, target_config)
            PyImGui.close_current_popup()
        PyImGui.end_disabled()

        PyImGui.same_line(0, 8)
        if ImGui.button('Cancel', btn_width) or self._is_cancel_key_pressed():
            self._empty_profile_name = ''
            PyImGui.close_current_popup()

        ImGui.show_tooltip('Creates a fresh empty profile for this config type and switches the current character to it.')
        PyImGui.end_popup_modal()

    def _open_manage_profile_popup(self, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        if not self.show_manage_profile_window:
            self.manage_profile_window_config_type = target_config.config_type

        profile_names = [
            profile_name
            for profile_name in self.profile_manager.list_profiles(target_config.config_type)
            if profile_name != GlobalConfigProfileManager.SHARED_PROFILE_NAME
        ]
        active_profile_name = self.profile_manager.get_active_profile_name(target_config.config_type)
        if active_profile_name in profile_names:
            self._manage_profile_selected_name = active_profile_name
        elif profile_names:
            self._manage_profile_selected_name = profile_names[0]
        else:
            self._manage_profile_selected_name = GlobalConfigProfileManager.SHARED_PROFILE_NAME

        self.show_manage_profile_window = True

    def _open_profile_action_popup(self, mode: str, source_profile_name: str, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        normalized_mode = str(mode or '').strip().lower()
        if normalized_mode not in ('rename', 'duplicate', 'delete'):
            return

        normalized_source_name = GlobalConfigProfileManager.sanitize_profile_name(source_profile_name)
        if normalized_source_name == '' or normalized_source_name == GlobalConfigProfileManager.SHARED_PROFILE_NAME:
            return

        self._profile_action_mode = normalized_mode
        self._profile_action_source_name = normalized_source_name
        self._profile_action_target_name = normalized_source_name if normalized_mode == 'rename' else ''
        self._profile_action_popup_requested = True

    def _draw_profile_action_popup(self, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_active_config_info(config_info)
        if target_config is None:
            return

        if self._profile_action_mode not in ('rename', 'duplicate', 'delete'):
            return

        action_label = 'Delete' if self._profile_action_mode == 'delete' else ('Rename' if self._profile_action_mode == 'rename' else 'Duplicate')
        popup_title = f'{action_label} Profile##{self._profile_action_popup_id}'
        if self._profile_action_popup_requested:
            PyImGui.open_popup(popup_title)
            self._profile_action_popup_requested = False

        PyImGui.set_next_window_size((380, 0), PyImGui.ImGuiCond.Always)
        if not PyImGui.begin_popup_modal(popup_title, True, PyImGui.WindowFlags.AlwaysAutoResize):
            return

        ImGui.text(f'Config Type: {self._humanize_name(target_config.config_type)}')
        if self._profile_action_mode == 'delete':
            ImGui.text_wrapped(
                f'Are you sure you want to delete profile "{self._profile_action_source_name}"? '
                'This action is synced across accounts and characters using it will fall back to SHARED.'
            )
        else:
            ImGui.text_wrapped(
                f'{action_label} profile "{self._profile_action_source_name}" by entering the target profile name below.'
            )
            PyImGui.set_next_item_width(-1)
            self._profile_action_target_name = ImGui.input_text('Profile Name', self._profile_action_target_name)

        btn_width = (PyImGui.get_window_content_region_max()[0] - 8) / 2
        target_name = GlobalConfigProfileManager.sanitize_profile_name(self._profile_action_target_name)
        action_disabled = False if self._profile_action_mode == 'delete' else target_name == ''
        confirm_with_enter = self._profile_action_mode == 'delete' and self._is_confirm_key_pressed()
        PyImGui.begin_disabled(action_disabled)
        if ImGui.button(action_label, btn_width) or (confirm_with_enter and not action_disabled):
            if self._profile_action_mode == 'rename':
                self._rename_global_config_profile(
                    self._profile_action_source_name,
                    self._profile_action_target_name,
                    target_config,
                )
            elif self._profile_action_mode == 'delete':
                self._delete_global_config_profile(
                    self._profile_action_source_name,
                    target_config,
                )
            else:
                self._duplicate_global_config_profile(
                    self._profile_action_source_name,
                    self._profile_action_target_name,
                    target_config,
                )
            self._profile_action_mode = ''
            self._profile_action_popup_requested = False
            self._profile_action_source_name = ''
            self._profile_action_target_name = ''
            PyImGui.close_current_popup()
        PyImGui.end_disabled()

        PyImGui.same_line(0, 8)
        if ImGui.button('Cancel', btn_width) or self._is_cancel_key_pressed():
            self._profile_action_mode = ''
            self._profile_action_popup_requested = False
            self._profile_action_source_name = ''
            self._profile_action_target_name = ''
            PyImGui.close_current_popup()

        PyImGui.end_popup_modal()

    def _open_rule_delete_popup(self, config_info: ConfigInfo[RuleConfig], rule: BaseRule) -> None:
        self._rule_delete_target_config = config_info
        self._rule_delete_target_rule = rule
        self._rule_delete_popup_requested = True

    def _open_sorting_group_delete_popup(self, config_info: ConfigInfo[SortingConfig], group: SlotGroupConfig) -> None:
        self._sorting_group_delete_target_config = config_info
        self._sorting_group_delete_target_group = group
        self._sorting_group_delete_popup_requested = True

    def _draw_rule_delete_popup(self) -> None:
        if self._rule_delete_popup_requested:
            PyImGui.open_popup(f'Delete Rule##{self._rule_delete_popup_id}')
            self._rule_delete_popup_requested = False

        target_config = self._rule_delete_target_config
        target_rule = self._rule_delete_target_rule
        if target_config is None or target_rule is None:
            return

        popup_width = 380
        popup_height = 120
        popup_x = max(0.0, (UI.SCREEN_SIZE[0] - popup_width) * 0.5)
        popup_y = max(0.0, (UI.SCREEN_SIZE[1] - popup_height) * 0.5)
        PyImGui.set_next_window_pos((popup_x, popup_y), PyImGui.ImGuiCond.Always)
        PyImGui.set_next_window_size((380, 0), PyImGui.ImGuiCond.Always)
        if not PyImGui.begin_popup_modal(
            f'Delete Rule##{self._rule_delete_popup_id}',
            True,
            PyImGui.WindowFlags.AlwaysAutoResize | PyImGui.WindowFlags.NoMove,
        ):
            return

        rule_name = target_rule.name or self._humanize_name(target_rule.__class__.__name__)
        ImGui.text_wrapped(f'Are you sure you want to delete rule "{rule_name}"?')

        btn_width = (PyImGui.get_window_content_region_max()[0] - 8) / 2
        if ImGui.button('Delete', btn_width) or self._is_confirm_key_pressed():
            if target_rule in target_config.config:
                deleted_index = target_config.config.index(target_rule)
                target_config.config.remove(target_rule)
                target_config.save()
                replacement_rule = target_config.config[min(deleted_index, len(target_config.config) - 1)] if target_config.config else None
                self._set_active_rule(replacement_rule)
            self._rule_delete_target_config = None
            self._rule_delete_target_rule = None
            PyImGui.close_current_popup()

        PyImGui.same_line(0, 8)
        if ImGui.button('Cancel', btn_width) or self._is_cancel_key_pressed():
            self._rule_delete_target_config = None
            self._rule_delete_target_rule = None
            PyImGui.close_current_popup()

        PyImGui.end_popup_modal()

    def _draw_sorting_group_delete_popup(self) -> None:
        if self._sorting_group_delete_popup_requested:
            PyImGui.open_popup(f'Delete Sort Policy##{self._sorting_group_delete_popup_id}')
            self._sorting_group_delete_popup_requested = False

        target_config = self._sorting_group_delete_target_config
        target_group = self._sorting_group_delete_target_group
        if target_config is None or target_group is None:
            return

        popup_width = 380
        popup_height = 120
        popup_x = max(0.0, (UI.SCREEN_SIZE[0] - popup_width) * 0.5)
        popup_y = max(0.0, (UI.SCREEN_SIZE[1] - popup_height) * 0.5)
        PyImGui.set_next_window_pos((popup_x, popup_y), PyImGui.ImGuiCond.Always)
        PyImGui.set_next_window_size((380, 0), PyImGui.ImGuiCond.Always)
        if not PyImGui.begin_popup_modal(
            f'Delete Sort Policy##{self._sorting_group_delete_popup_id}',
            True,
            PyImGui.WindowFlags.AlwaysAutoResize | PyImGui.WindowFlags.NoMove,
        ):
            return

        group_name = target_group.display_name()
        ImGui.text_wrapped(f'Are you sure you want to delete sort policy "{group_name}"?')

        btn_width = (PyImGui.get_window_content_region_max()[0] - 8) / 2
        if ImGui.button('Delete', btn_width) or self._is_confirm_key_pressed():
            if target_group in target_config.config.slot_groups:
                deleted_index = target_config.config.slot_groups.index(target_group)
                target_config.config.slot_groups.remove(target_group)
                target_config.save()
                replacement_group = target_config.config.slot_groups[min(deleted_index, len(target_config.config.slot_groups) - 1)] if target_config.config.slot_groups else None
                self._set_active_sorting_group(replacement_group)
            self._sorting_group_delete_target_config = None
            self._sorting_group_delete_target_group = None
            PyImGui.close_current_popup()

        PyImGui.same_line(0, 8)
        if ImGui.button('Cancel', btn_width) or self._is_cancel_key_pressed():
            self._sorting_group_delete_target_config = None
            self._sorting_group_delete_target_group = None
            PyImGui.close_current_popup()

        PyImGui.end_popup_modal()

    def _draw_manage_profile_window(self, config_info: ConfigInfo | None = None) -> None:
        target_config = self._get_config_info_by_type(self.manage_profile_window_config_type)
        if target_config is None or not self.show_manage_profile_window:
            return

        PyImGui.set_next_window_size((520, 420), PyImGui.ImGuiCond.FirstUseEver)
        expanded, open_ = ImGui.BeginWithClose(
            ini_key=self.module_config.main_ini_key,
            name=f'Manage Profiles',
            p_open=self.show_manage_profile_window,
            flags=PyImGui.WindowFlags.NoFlag,
        )
        self.show_manage_profile_window = open_
        if not expanded:
            ImGui.End(self.module_config.main_ini_key)
            return

        config_type_options = self._get_config_type_options()
        config_type_labels = [config_option.name for config_option in config_type_options]
        current_config_type_index = next(
            (
                index
                for index, config_option in enumerate(config_type_options)
                if config_option.config_type == target_config.config_type
            ),
            0,
        )

        PyImGui.set_next_item_width(-1)
        selected_config_type_index = ImGui.combo('Config Type', current_config_type_index, config_type_labels)
        if selected_config_type_index != current_config_type_index:
            self.manage_profile_window_config_type = config_type_options[selected_config_type_index].config_type
            self._profile_action_mode = ''
            self._profile_action_popup_requested = False
            self._profile_action_source_name = ''
            self._profile_action_target_name = ''
            ImGui.End(self.module_config.main_ini_key)
            return

        profile_names = [
            profile_name
            for profile_name in self.profile_manager.list_profiles(target_config.config_type)
            if profile_name != GlobalConfigProfileManager.SHARED_PROFILE_NAME
        ]
        ImGui.text_wrapped('Manage profiles for the current config type. Rename and delete are synced across accounts.\nDeleting a profile makes users fall back to SHARED.')

        if profile_names:            
            style = ImGui.get_style()
            style.CellPadding.push_style_var_direct(2, 6)
            if ImGui.begin_table('##manage_profile_table', 4, PyImGui.TableFlags.BordersInnerH | PyImGui.TableFlags.BordersOuterV | PyImGui.TableFlags.BordersOuterH | PyImGui.TableFlags.RowBg | PyImGui.TableFlags.SizingStretchProp):
                PyImGui.table_setup_column('Profile', PyImGui.TableColumnFlags.WidthStretch)
                PyImGui.table_setup_column('##Rename', PyImGui.TableColumnFlags.WidthFixed, 30)
                PyImGui.table_setup_column('##Duplicate', PyImGui.TableColumnFlags.WidthFixed, 30)
                PyImGui.table_setup_column('##Delete', PyImGui.TableColumnFlags.WidthFixed, 30)

                active_profile_name = self.profile_manager.get_active_profile_name(target_config.config_type)
                for profile_name in profile_names:
                    PyImGui.table_next_row()
                    PyImGui.table_next_column()
                    PyImGui.same_line(0, 4)
                    label = profile_name if profile_name != active_profile_name else f'{profile_name} (Active)'
                    ImGui.text_aligned(label, alignment=Alignment.MidLeft, height=25)

                    PyImGui.table_next_column()
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_EDIT}##{profile_name}', -1):
                        self._open_profile_action_popup('rename', profile_name, target_config)
                    ImGui.show_tooltip('Rename this profile. This action is synced across accounts.')

                    PyImGui.table_next_column()
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_COPY}##{profile_name}', -1):
                        self._open_profile_action_popup('duplicate', profile_name, target_config)
                    ImGui.show_tooltip('Duplicate this profile. This action is synced across accounts.')

                    PyImGui.table_next_column()
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_TRASH}##{profile_name}', -1):
                        self._open_profile_action_popup('delete', profile_name, target_config)
                    ImGui.show_tooltip('Delete this profile. This action is synced across accounts and makes users fall back to the shared profile.')

                ImGui.end_table()
            style.CellPadding.pop_style_var_direct()
        else:
            ImGui.text_colored('No custom profiles available for this config type.', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=11)

        if ImGui.button('Close', -1):
            self.show_manage_profile_window = False
            self._profile_action_mode = ''
            self._profile_action_popup_requested = False
            self._profile_action_source_name = ''
            self._profile_action_target_name = ''
        ImGui.End(self.module_config.main_ini_key)
        self._draw_profile_action_popup(target_config)

    def switch_to_config(self, rule_config: ConfigInfo | None):
        self.config = rule_config or (self.configs[0] if len(self.configs) > 0 else None)
        self._sync_selected_rule()
        self._sync_selected_sorting_group()
        self._refresh_sorting_assigned_slot_cache()

    def _can_convert_rule_to_custom(self, rule: BaseRule) -> bool:
        if isinstance(rule, CustomRule):
            return False

        # Only surface conversion when we can preserve all editable rule state.
        if isinstance(rule, (ExtractUpgradeRule)):
            return False

        return all(self._supports_custom_condition_editor(type(condition)) for condition in rule.conditions)

    def _convert_rule_to_custom(self, config_info: ConfigInfo[RuleConfig], rule: BaseRule) -> CustomRule | None:
        if not self._can_convert_rule_to_custom(rule):
            return None

        try:
            rule_index = config_info.config.index(rule)
        except ValueError:
            return None

        custom_conditions: list[BaseCondition] = []
        for condition in rule.conditions:
            cloned_condition = BaseCondition.from_dict(condition.to_dict())
            if cloned_condition is None:
                return None
            custom_conditions.append(cloned_condition)

        custom_rule = CustomRule(custom_conditions, action=rule.action, condition_operator=rule.condition_operator)
        custom_rule.name = rule.name
        custom_rule.enabled = rule.enabled
        custom_rule.result_interpretation = rule.result_interpretation

        config_info.config[rule_index] = custom_rule
        config_info.save()
        self._set_active_rule(custom_rule)

        return custom_rule

    def _get_condition_clipboard(self) -> BaseCondition | None:
        if self._condition_clipboard_payload is None:
            return None

        return BaseCondition.from_dict(self._condition_clipboard_payload)

    def _copy_condition_to_clipboard(self, condition: BaseCondition) -> None:
        self._condition_clipboard_payload = condition.to_dict()
        self._condition_clipboard_label = self._humanize_name(type(condition).__name__).replace('Condition', '')

    def _remember_drag_clicked_item(self, item_key: Any, clicked: bool) -> None:
        if clicked:
            self._drag_clicked_item = item_key

    def _can_start_drag_from_item(self, item_key: Any, hovered: bool) -> bool:
        return hovered and self._dragging and self._drag_clicked_item == item_key

    def _can_paste_condition_into_rule(self, rule: BaseRule) -> bool:
        clipboard_condition = self._get_condition_clipboard()
        if clipboard_condition is None:
            return False

        clipboard_type = type(clipboard_condition)
        if isinstance(rule, SlotMatcherConfig):
            return True

        if isinstance(rule, CustomRule):
            return self._supports_custom_condition_editor(clipboard_type)

        return any(type(existing_condition) is clipboard_type for existing_condition in rule.conditions)

    def _paste_condition_into_rule(self, rule: BaseRule) -> bool:
        clipboard_condition = self._get_condition_clipboard()
        if clipboard_condition is None:
            return False

        clipboard_type = type(clipboard_condition)
        replacement_index = next((index for index, existing_condition in enumerate(rule.conditions) if type(existing_condition) is clipboard_type), None)

        if replacement_index is not None:
            rule.conditions[replacement_index] = clipboard_condition
            return True

        if isinstance(rule, SlotMatcherConfig):
            rule.conditions.append(clipboard_condition)
            return True

        if isinstance(rule, CustomRule) and self._supports_custom_condition_editor(clipboard_type):
            rule.conditions.append(clipboard_condition)
            return True

        return False

    def _can_paste_condition_over(self, rule: BaseRule, condition: BaseCondition) -> bool:
        clipboard_condition = self._get_condition_clipboard()
        if clipboard_condition is None:
            return False

        if isinstance(rule, SlotMatcherConfig):
            return True

        if isinstance(rule, CustomRule):
            return self._supports_custom_condition_editor(type(clipboard_condition))

        return type(clipboard_condition) is type(condition)

    def _paste_condition_over(self, rule: BaseRule, condition: BaseCondition) -> bool:
        clipboard_condition = self._get_condition_clipboard()
        if clipboard_condition is None:
            return False

        if isinstance(rule, SlotMatcherConfig):
            try:
                condition_index = rule.conditions.index(condition)
            except ValueError:
                rule.conditions.append(clipboard_condition)
                return True

            rule.conditions[condition_index] = clipboard_condition
            return True

        if isinstance(rule, CustomRule):
            if not self._supports_custom_condition_editor(type(clipboard_condition)):
                return False
            try:
                condition_index = rule.conditions.index(condition)
            except ValueError:
                rule.conditions.append(clipboard_condition)
                return True

            rule.conditions.insert(condition_index + 1, clipboard_condition)
            return True

        try:
            condition_index = rule.conditions.index(condition)
        except ValueError:
            return False

        if type(clipboard_condition) is not type(condition):
            return False

        rule.conditions[condition_index] = clipboard_condition
        return True

    def draw_preview_window(self, config_info: ConfigInfo):    
        preview_config = self._get_config_info_by_type(self.preview_window_config_type)
        if preview_config is None:
            self.show_preview_window = False
            return

        if not self.show_preview_window:
            return

        PyImGui.set_next_window_size((800, 600), PyImGui.ImGuiCond.FirstUseEver)      
        expanded, open_ = ImGui.BeginWithClose(
            ini_key=self.module_config.main_ini_key,
            name="Item Manager - Preview",
            p_open=self.show_preview_window,
            flags=PyImGui.WindowFlags.NoFlag,
        )

        config_type_options = self._get_config_type_options()
        config_type_labels = [config_option.name for config_option in config_type_options]
        current_config_type_index = next(
            (
                index
                for index, config_option in enumerate(config_type_options)
                if config_option.config_type == preview_config.config_type
            ),
            0,
        )

        if expanded:
            PyImGui.set_next_item_width(-1)
            selected_config_type_index = ImGui.combo('Config Type', current_config_type_index, config_type_labels)
            if selected_config_type_index != current_config_type_index:
                self.preview_window_config_type = config_type_options[selected_config_type_index].config_type
                preview_config = config_type_options[selected_config_type_index]

        match preview_config.config:
            case InventoryConfig():
                self.draw_inventory_config_preview(preview_config.config)
            
            case LootConfig():
                self.draw_loot_config_preview(preview_config.config)
            
            case BuyConfig():
                self.draw_buy_config_preview(preview_config.config)

            case SortingConfig():
                self.draw_sorting_config_preview(preview_config.config)

            case CraftingConfig():
                self.draw_crafting_config(preview_config)
                
        ImGui.End(self.module_config.main_ini_key)
        
        if not open_:
            self.show_preview_window = False

    def _get_player_gender(self) -> Gender:
        agent = Player.GetAgent()
        living_agent = agent.GetAsAgentLiving() if agent else None
        return (Gender.Female if living_agent.is_female else Gender.Male) if living_agent else Gender.Unknown

    def draw_explorer(self):
        self._watch_global_config_profile_context()
        if self.config is not None:
            
            live_config = self._get_config_info_by_type(self.config.config_type)
            if live_config is not None and self.config is not live_config:
                PySystem.Console.Log("Item Manager", f"Change detected for config type {self.config.config_type}. We changed from {self.config.name} to {live_config.name}.", PySystem.Console.MessageType.Info)
                PySystem.Console.Log("Item Manager", f"Active config '{self.config.name}' was reloaded externally. Switching to the latest version of the config.", PySystem.Console.MessageType.Warning)
                self.config = live_config

        style = ImGui.get_style()
        io = PyImGui.get_io()
        
        UI.SCREEN_SIZE = (io.display_size_x, io.display_size_y)
        UI.SELECTABLE_SELECTED_COLOR = style.Header.opacity(0.8)
        UI.SELECTABLE_ACTIVE_COLOR = style.HeaderActive.opacity(0.95)
        UI.SELECTABLE_HOVERED_COLOR = style.HeaderHovered.opacity(0.75)
        UI.SUBTLE_TEXT_COLOR = UI._build_subtle_text_color(style.Text)
        
        UI.GENDER = self._get_player_gender()
                
        # style.TableBorderLight.push_color_direct((255,255,255,255))
        # style.TableBorderStrong.push_color_direct((255,255,255,255))

        style.CellPadding.push_style_var_direct(10, 10)
        if ImGui.begin_table("##item_manager_explorer", 2, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable):
            PyImGui.table_setup_column("Navigation", PyImGui.TableColumnFlags.WidthFixed, 200)
            PyImGui.table_setup_column("Content", PyImGui.TableColumnFlags.WidthStretch)

            PyImGui.table_next_row()
            PyImGui.table_next_column()

            if ImGui.begin_child("##navigation", (0, 0), border=False):
                for _, config in enumerate(self.configs):
                    if ImGui.begin_selectable(f"##{config.name}", selected=self.config == config, size=(0, 35), border=True, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                        ImGui.text(config.name)
                        x, y = PyImGui.get_cursor_pos()
                        PyImGui.set_cursor_pos((x, y - 5))
                        ImGui.text_colored(config.config.__class__.__name__, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                    if ImGui.end_selectable():
                        self.switch_to_config(config)

                    ImGui.show_tooltip(config.description)

            ImGui.end_child()

            PyImGui.table_next_column()

            if ImGui.begin_child("##content", (0, 0), border=False):
                if self.config:
                    active_config = self._get_active_config_info(self.config)
                    if active_config is not None and self.config is not active_config:
                        self.config = active_config
                    active_config_name = active_config.name if active_config is not None and active_config is not self.config else None
                    title = self.config.name if active_config_name is None else f"{self.config.name} / {active_config_name}"

                    style.CellPadding.push_style_var_direct(2, 2)
                    if ImGui.begin_table("##config_header", 4, PyImGui.TableFlags.NoBordersInBody, height=20):
                        PyImGui.table_setup_column("Title", PyImGui.TableColumnFlags.WidthStretch)
                        PyImGui.table_setup_column("Profile", PyImGui.TableColumnFlags.WidthStretch)
                        PyImGui.table_setup_column("Export", PyImGui.TableColumnFlags.WidthFixed, 100)
                        PyImGui.table_setup_column("Preview", PyImGui.TableColumnFlags.WidthFixed, 100)

                        PyImGui.table_next_row()
                        PyImGui.table_next_column()

                        ImGui.text(title, font_size=18)
                        PyImGui.table_next_column()
                        active_config = self._get_active_config_info()
                        if active_config is not None:
                            active_config_type = active_config.config_type
                            profile_names = self.profile_manager.list_profiles(active_config_type)
                            active_profile_name = self.profile_manager.get_active_profile_name(active_config_type)
                            current_profile_index = profile_names.index(active_profile_name) if active_profile_name in profile_names else 0
                            PyImGui.set_next_item_width(-64)
                            selected_profile_index = ImGui.combo('##global_config_profile', current_profile_index, profile_names)
                            if selected_profile_index != current_profile_index:
                                self._switch_global_config_profile(profile_names[selected_profile_index], active_config)
                            ImGui.show_tooltip('The selected profile is stored per character on this account.')
                            PyImGui.same_line(0, 6)
                            if ImGui.button('...##manage_profiles', 26):
                                self._open_manage_profile_popup(active_config)
                            ImGui.show_tooltip('Manage profiles for this config type.')
                            
                            PyImGui.same_line(0, 6)
                            if ImGui.button('+##manage_profiles', 26):
                                self._open_empty_profile_popup(active_config)
                            ImGui.show_tooltip('Add an empty profile for this config type.')
                            
                        PyImGui.table_next_column()
                        if ImGui.button("Save As##export_config", -1):
                            self._open_save_as_profile_popup(active_config)

                        PyImGui.table_next_column()
                        if ImGui.button("Preview##preview_config", -1):
                            if not self.show_preview_window and active_config is not None:
                                self.preview_window_config_type = active_config.config_type
                            self.show_preview_window = not self.show_preview_window
                        
                        ImGui.end_table()
                    style.CellPadding.pop_style_var_direct()

                    self._draw_save_as_profile_popup(active_config)
                    self._draw_empty_profile_popup(active_config)
                    self.draw_config(active_config or self.config)

            ImGui.end_child()

            ImGui.end_table()
        style.CellPadding.pop_style_var_direct()

        # style.TableBorderLight.pop_color_direct()
        # style.TableBorderStrong.pop_color_direct()

    def draw_context_menu(self, popup_id: str, config_info: ConfigInfo, rule: BaseRule) -> bool:
        if PyImGui.begin_popup(popup_id):
            ImGui.text_colored(rule.name or popup_id, color=UI.CREME_COLOR.color_tuple, font_size=16)
            ImGui.separator()

            if ImGui.menu_item("Move Up"):
                index = config_info.config.index(rule)
                if index > 0:
                    config_info.config.remove(rule)
                    config_info.config.insert(index - 1, rule)
                config_info.save()
                self._set_active_rule(None)

            if ImGui.menu_item("Move Down"):
                index = config_info.config.index(rule)
                if index < len(config_info.config) - 1:
                    config_info.config.remove(rule)
                    config_info.config.insert(index + 1, rule)
                config_info.save()
                self._set_active_rule(None)

            ImGui.separator()

            if ImGui.menu_item("Duplicate"):
                index = config_info.config.index(rule)
                duplicated_rule = BaseRule.from_dict(rule.to_dict())
                if duplicated_rule is not None:
                    config_info.config.insert(index + 1, duplicated_rule)
                    config_info.save()
                    self._set_active_rule(duplicated_rule)

            if self._can_convert_rule_to_custom(rule):
                if ImGui.menu_item("Convert To Custom Rule"):
                    converted_rule = self._convert_rule_to_custom(config_info, rule)
                    if converted_rule is not None:
                        self.context_menu_rule = converted_rule
                        PyImGui.close_current_popup()

            if self._can_paste_condition_into_rule(rule):
                paste_label = f'Paste Condition: {self._condition_clipboard_label}' if self._condition_clipboard_label else 'Paste Condition'
                if ImGui.menu_item(paste_label):
                    if self._paste_condition_into_rule(rule):
                        config_info.save()
                        self._set_active_rule(rule)
                        PyImGui.close_current_popup()

            ImGui.separator()

            copy_target = self._get_rule_copy_target_config(config_info)
            if copy_target is not None and ImGui.menu_item(f"Copy To {copy_target.name}"):
                duplicated_rule = BaseRule.from_dict(rule.to_dict())
                if duplicated_rule is not None:
                    copy_target.config.append(duplicated_rule)
                    copy_target.save()

            if copy_target is not None:
                ImGui.separator()

            if ImGui.menu_item("Delete Rule"):
                self._open_rule_delete_popup(config_info, rule)

            ImGui.end_popup()
            return True

        return False

    def draw_sorting_group_context_menu(self, popup_id: str, config_info: ConfigInfo[SortingConfig], group: SlotGroupConfig) -> bool:
        if PyImGui.begin_popup(popup_id):
            ImGui.text_colored(group.name or group.display_name(), color=UI.CREME_COLOR.color_tuple, font_size=16)
            ImGui.separator()

            try:
                index = config_info.config.slot_groups.index(group)
            except ValueError:
                ImGui.end_popup()
                return False

            if ImGui.menu_item("Move Up"):
                if index > 0:
                    config_info.config.slot_groups.remove(group)
                    config_info.config.slot_groups.insert(index - 1, group)
                config_info.save()
                self._set_active_sorting_group(group)

            if ImGui.menu_item("Move Down"):
                if index < len(config_info.config.slot_groups) - 1:
                    config_info.config.slot_groups.remove(group)
                    config_info.config.slot_groups.insert(index + 1, group)
                config_info.save()
                self._set_active_sorting_group(group)

            ImGui.separator()

            if ImGui.menu_item("Duplicate"):
                duplicated_group = SlotGroupConfig.from_dict(group.to_dict())
                if duplicated_group is not None:
                    duplicated_group.is_default = False
                    duplicated_group.name = f"{group.name} Copy" if group.name else ""
                    config_info.config.slot_groups.insert(index + 1, duplicated_group)
                    config_info.save()
                    self._set_active_sorting_group(duplicated_group)

            ImGui.separator()

            if ImGui.menu_item("Delete Group"):
                self._open_sorting_group_delete_popup(config_info, group)

            ImGui.end_popup()
            return True

        return False

    def _clear_rule_drag(self) -> None:
        self._drag_rule = None
        self._drag_rule_source_config = None
        self._drag_rule_source_index = -1
        self._drag_rule_target_index = -1
        self._drag_rule_target_rect = None
        self._drag_rule_target_after = False
        self._drag_rule_preview_label = ""
        self._drag_rule_preview_subtitle = ""
        self._drag_window_pos = None

    def _clear_condition_drag(self) -> None:
        self._drag_condition = None
        self._drag_condition_source_rule = None
        self._drag_condition_source_index = -1
        self._drag_condition_target_index = -1
        self._drag_condition_target_rect = None
        self._drag_condition_target_after = False
        self._drag_condition_preview_label = ""
        self._drag_condition_preview_subtitle = ""
        self._drag_window_pos = None

    def _clear_sorting_group_drag(self) -> None:
        self._drag_sorting_group = None
        self._drag_sorting_group_source_config = None
        self._drag_sorting_group_source_index = -1
        self._drag_sorting_group_target_index = -1
        self._drag_sorting_group_target_rect = None
        self._drag_sorting_group_target_after = False
        self._drag_sorting_group_preview_label = ""
        self._drag_sorting_group_preview_subtitle = ""
        self._drag_window_pos = None

    def _begin_rule_drag(self, config_info: ConfigInfo[RuleConfig], rule: BaseRule, index: int) -> None:
        self._drag_clicked_item = None
        self._drag_rule = rule
        self._drag_rule_source_config = config_info
        self._drag_rule_source_index = index
        self._drag_rule_target_index = -1
        self._drag_rule_target_rect = None
        self._drag_rule_target_after = False
        self._drag_rule_preview_label = rule.name or f"{rule.__class__.__name__} #{index}"
        self._drag_rule_preview_subtitle = UI._humanize_name(rule.action.name)
        self._drag_window_pos = self.window_pos

    def _begin_condition_drag(self, rule: CustomRule, condition: BaseCondition, index: int) -> None:
        self._drag_clicked_item = None
        self._drag_condition = condition
        self._drag_condition_source_rule = rule
        self._drag_condition_source_index = index
        self._drag_condition_target_index = -1
        self._drag_condition_target_rect = None
        self._drag_condition_target_after = False
        self._drag_condition_preview_label = self._humanize_name(type(condition).__name__).replace("Condition", "")
        self._drag_condition_preview_subtitle = inspect.getdoc(type(condition)) or ""
        self._drag_condition_preview_subtitle = re.sub(r":class:`([^`]+)`", r"\1", self._drag_condition_preview_subtitle).replace("**", "").strip()
        self._drag_window_pos = self.window_pos

    def _begin_sorting_group_drag(self, config_info: ConfigInfo[SortingConfig], group: SlotGroupConfig, index: int) -> None:
        self._drag_clicked_item = None
        self._drag_sorting_group = group
        self._drag_sorting_group_source_config = config_info
        self._drag_sorting_group_source_index = index
        self._drag_sorting_group_target_index = -1
        self._drag_sorting_group_target_rect = None
        self._drag_sorting_group_target_after = False
        self._drag_sorting_group_preview_label = group.name or f"Slot Group #{index + 1}"
        self._drag_sorting_group_preview_subtitle = self._slot_group_selection_summary(group)
        self._drag_window_pos = self.window_pos

    def _apply_rule_drag(self, config_info: ConfigInfo[RuleConfig]) -> None:
        if self._drag_rule_source_config is not config_info or self._drag_rule is None:
            self._clear_rule_drag()
            return

        if self._drag_rule_target_rect is None:
            self._clear_rule_drag()
            return

        if self._drag_rule_target_index < 0 or self._drag_rule_source_index < 0:
            self._clear_rule_drag()
            return

        try:
            source_index = config_info.config.index(self._drag_rule)
        except ValueError:
            self._clear_rule_drag()
            return

        insert_index = self._drag_rule_target_index + (1 if self._drag_rule_target_after else 0)
        if insert_index > source_index:
            insert_index -= 1

        insert_index = max(0, min(insert_index, len(config_info.config) - 1))
        if insert_index != source_index:
            config_info.config.remove(self._drag_rule)
            config_info.config.insert(insert_index, self._drag_rule)
            config_info.save()
            self._set_active_rule(self._drag_rule)

        self._clear_rule_drag()

    def _apply_condition_drag(self, rule: CustomRule) -> bool:
        if self._drag_condition_source_rule is not rule or self._drag_condition is None:
            self._clear_condition_drag()
            return False

        if self._drag_condition_target_rect is None:
            self._clear_condition_drag()
            return False

        if self._drag_condition_target_index < 0 or self._drag_condition_source_index < 0:
            self._clear_condition_drag()
            return False

        try:
            source_index = rule.conditions.index(self._drag_condition)
        except ValueError:
            self._clear_condition_drag()
            return False

        insert_index = self._drag_condition_target_index + (1 if self._drag_condition_target_after else 0)
        if insert_index > source_index:
            insert_index -= 1

        insert_index = max(0, min(insert_index, len(rule.conditions) - 1))
        changed = False
        if insert_index != source_index:
            rule.conditions.remove(self._drag_condition)
            rule.conditions.insert(insert_index, self._drag_condition)
            changed = True

        self._clear_condition_drag()
        return changed

    def _apply_sorting_group_drag(self, config_info: ConfigInfo[SortingConfig]) -> None:
        if self._drag_sorting_group_source_config is not config_info or self._drag_sorting_group is None:
            self._clear_sorting_group_drag()
            return

        if self._drag_sorting_group_target_rect is None:
            self._clear_sorting_group_drag()
            return

        if self._drag_sorting_group_target_index < 0 or self._drag_sorting_group_source_index < 0:
            self._clear_sorting_group_drag()
            return

        try:
            source_index = config_info.config.slot_groups.index(self._drag_sorting_group)
        except ValueError:
            self._clear_sorting_group_drag()
            return

        insert_index = self._drag_sorting_group_target_index + (1 if self._drag_sorting_group_target_after else 0)
        if insert_index > source_index:
            insert_index -= 1

        insert_index = max(0, min(insert_index, len(config_info.config.slot_groups) - 1))
        if insert_index != source_index:
            config_info.config.slot_groups.remove(self._drag_sorting_group)
            config_info.config.slot_groups.insert(insert_index, self._drag_sorting_group)
            config_info.save()
            self._set_active_sorting_group(self._drag_sorting_group)

        self._clear_sorting_group_drag()

    def _trim_and_single_line_preview_subtitle(self, subtitle: str, max_length: int = 45) -> str:
        single_line = subtitle.splitlines()[0] if subtitle else ""
        if len(single_line) > max_length:
            return single_line[:max_length - 3] + "..."
        return single_line

    def _draw_rule_drag_preview(self) -> None:
        if self._drag_rule is None:
            return

        io = PyImGui.get_io()
        preview_x = io.mouse_pos_x
        preview_y = io.mouse_pos_y
        preview_w = 240
        preview_h = 42

        insert_color = Utils.TupleToColor((1.0, 1.0, 1.0, 0.95))
        outer_color = Utils.TupleToColor((0.18, 0.45, 0.72, 0.92))
        inner_color = Utils.TupleToColor((0.10, 0.16, 0.24, 0.95))
        text_color = Utils.TupleToColor((0.97, 0.95, 0.88, 1.0))
        subtitle_color = Utils.TupleToColor(UI.SUBTLE_TEXT_COLOR.color_tuple)

        overlay = Overlay()

            
        overlay.BeginDraw()
        if self._drag_rule_target_rect is not None:
            x1, y1, x2, y2 = self._drag_rule_target_rect            
            overlay.DrawQuadFilled(x1 - 2, y1, x2 + 4, y1, x2 + 4, y2, x1 - 2, y2, insert_color)
            
        overlay.DrawQuadFilled(
            preview_x,
            preview_y,
            preview_x + preview_w,
            preview_y,
            preview_x + preview_w,
            preview_y + preview_h,
            preview_x,
            preview_y + preview_h,
            outer_color,
        )
        overlay.DrawQuadFilled(
            preview_x + 2,
            preview_y + 2,
            preview_x + preview_w - 2,
            preview_y + 2,
            preview_x + preview_w - 2,
            preview_y + preview_h - 2,
            preview_x + 2,
            preview_y + preview_h - 2,
            inner_color,
        )
        overlay.DrawText(
            preview_x + 10,
            preview_y + 8,
            self._drag_rule_preview_label,
            text_color,
            centered=False,
            scale=1.0,
        )
        overlay.DrawText(
            preview_x + 10,
            preview_y + 24,
            self._trim_and_single_line_preview_subtitle(self._drag_rule_preview_subtitle),
            subtitle_color,
            centered=False,
            scale=1.0,
        )
        overlay.EndDraw()

    def _draw_condition_drag_preview(self) -> None:
        if self._drag_condition is None:
            return

        io = PyImGui.get_io()
        preview_x = io.mouse_pos_x
        preview_y = io.mouse_pos_y
        preview_w = 300
        preview_h = 42

        insert_color = Utils.TupleToColor((1.0, 1.0, 1.0, 0.95))
        outer_color = Utils.TupleToColor((0.18, 0.45, 0.72, 0.92))
        inner_color = Utils.TupleToColor((0.10, 0.16, 0.24, 0.95))
        text_color = Utils.TupleToColor((0.97, 0.95, 0.88, 1.0))
        subtitle_color = Utils.TupleToColor(UI.SUBTLE_TEXT_COLOR.color_tuple)

        overlay = Overlay()
        overlay.BeginDraw()
        if self._drag_condition_target_rect is not None:
            x1, y1, x2, y2 = self._drag_condition_target_rect
            overlay.DrawQuadFilled(x1 - 2, y1, x2 + 4, y1, x2 + 4, y2, x1 - 2, y2, insert_color)

        overlay.DrawQuadFilled(
            preview_x,
            preview_y,
            preview_x + preview_w,
            preview_y,
            preview_x + preview_w,
            preview_y + preview_h,
            preview_x,
            preview_y + preview_h,
            outer_color,
        )
        overlay.DrawQuadFilled(
            preview_x + 2,
            preview_y + 2,
            preview_x + preview_w - 2,
            preview_y + 2,
            preview_x + preview_w - 2,
            preview_y + preview_h - 2,
            preview_x + 2,
            preview_y + preview_h - 2,
            inner_color,
        )
        overlay.DrawText(
            preview_x + 10,
            preview_y + 8,
            self._drag_condition_preview_label,
            text_color,
            centered=False,
            scale=1.0,
        )
        overlay.DrawText(
            preview_x + 10,
            preview_y + 24,
            self._trim_and_single_line_preview_subtitle(self._drag_condition_preview_subtitle),
            subtitle_color,
            centered=False,
            scale=1.0,
        )
        overlay.EndDraw()

    def _draw_sorting_group_drag_preview(self) -> None:
        if self._drag_sorting_group is None:
            return

        io = PyImGui.get_io()
        preview_x = io.mouse_pos_x
        preview_y = io.mouse_pos_y
        preview_w = 260
        preview_h = 42

        insert_color = Utils.TupleToColor((1.0, 1.0, 1.0, 0.95))
        outer_color = Utils.TupleToColor((0.18, 0.45, 0.72, 0.92))
        inner_color = Utils.TupleToColor((0.10, 0.16, 0.24, 0.95))
        text_color = Utils.TupleToColor((0.97, 0.95, 0.88, 1.0))
        subtitle_color = Utils.TupleToColor(UI.SUBTLE_TEXT_COLOR.color_tuple)

        overlay = Overlay()
        overlay.BeginDraw()
        if self._drag_sorting_group_target_rect is not None:
            x1, y1, x2, y2 = self._drag_sorting_group_target_rect
            overlay.DrawQuadFilled(x1 - 2, y1, x2 + 4, y1, x2 + 4, y2, x1 - 2, y2, insert_color)

        overlay.DrawQuadFilled(
            preview_x,
            preview_y,
            preview_x + preview_w,
            preview_y,
            preview_x + preview_w,
            preview_y + preview_h,
            preview_x,
            preview_y + preview_h,
            outer_color,
        )
        overlay.DrawQuadFilled(
            preview_x + 2,
            preview_y + 2,
            preview_x + preview_w - 2,
            preview_y + 2,
            preview_x + preview_w - 2,
            preview_y + preview_h - 2,
            preview_x + 2,
            preview_y + preview_h - 2,
            inner_color,
        )
        overlay.DrawText(preview_x + 10, preview_y + 8, self._drag_sorting_group_preview_label, text_color, centered=False, scale=1.0)
        overlay.DrawText(preview_x + 10, preview_y + 24, self._trim_and_single_line_preview_subtitle(self._drag_sorting_group_preview_subtitle), subtitle_color, centered=False, scale=1.0)
        overlay.EndDraw()

    def _get_rule_copy_target_config(self, config_info: ConfigInfo) -> ConfigInfo | None:
        if not isinstance(config_info.config, RuleConfig):
            return None

        match config_info.config:
            case LootConfig():
                target_type = InventoryConfig
            case InventoryConfig():
                target_type = LootConfig
            case _:
                return None

        return next(
            (
                candidate
                for candidate in self.configs
                if isinstance(candidate.config, target_type)
            ),
            None,
        )

    def draw_config(self, config_info: ConfigInfo):
        if isinstance(config_info.config, RuleConfig):
            self.draw_rule_config(config_info)
            return

        if isinstance(config_info.config, BuyConfig):
            self.draw_buy_config(config_info)
            return

        if isinstance(config_info.config, SortingConfig):
            self.draw_sorting_config(config_info)
            return
        
        if isinstance(config_info.config, CraftingConfig):
            self.draw_crafting_config(config_info)
            return

        ImGui.text("No editor available for this config.")

    def _slot_group_selection_summary(self, group: SlotGroupConfig) -> str:
        sort_arguments = len(group.sorter.arguments)
        conditions = len(group.matcher.conditions)
        
        parts = []
        
        if sort_arguments == 0 and conditions == 0:
            return 'No sort arguments or conditions'
        
        if sort_arguments > 0:
            parts.append(f'{sort_arguments} Sort {"Argument" if sort_arguments == 1 else "Arguments"}')
            
        if conditions > 0:
            parts.append(f'{conditions} Filter {"Condition" if conditions == 1 else "Conditions"}')
        
        
        return '\n'.join(parts)
            

    def _format_sort_argument_custom_order_summary(self, argument: SortArgument) -> str:
        if not argument.has_custom_order:
            return 'Natural field order'

        if argument.field == SortField.ModelId:
            return f'{len(argument.custom_order)} item(s) prioritized'
        if argument.field == SortField.ItemType:
            return f'{len(argument.custom_order)} item type(s) prioritized'
        if argument.field == SortField.Rarity:
            return f'{len(argument.custom_order)} rarity tier(s) prioritized'
        if argument.field == SortField.Color:
            return f'{len(argument.custom_order)} color(s) prioritized'
        return f'{len(argument.custom_order)} custom entries'

    @staticmethod
    def _get_sort_argument_natural_item_type_order() -> list[ItemType]:
        prioritized_values = [
            int(ItemType.Kit),
            int(ItemType.Key),
            int(ItemType.Usable),
            int(ItemType.Trophy),
            int(ItemType.Quest_Item),
            int(ItemType.Materials_Zcoins),
        ]
        prioritized_types = [
            item_type
            for item_type in ItemType
            if int(item_type) in prioritized_values
        ]
        remaining_types = [
            item_type
            for item_type in ItemType
            if int(item_type) not in prioritized_values
        ]
        prioritized_types.sort(key=lambda item_type: prioritized_values.index(int(item_type)))
        return prioritized_types + remaining_types

    def _get_sort_argument_named_entry_labels(self, argument: SortArgument) -> tuple[list[str], list[str], str]:
        if argument.field == SortField.ItemType:
            natural_entries = self._get_sort_argument_natural_item_type_order()
            valid_names = [
                entry
                for entry in argument.custom_order
                if isinstance(entry, str) and entry in ItemType.__members__
            ]
            label_lookup = {
                item_type.name: self._item_type_name(item_type)
                for item_type in natural_entries
            }
        elif argument.field == SortField.Rarity:
            natural_entries = sorted(Rarity, key=lambda rarity: int(rarity.value))
            valid_names = [
                entry
                for entry in argument.custom_order
                if isinstance(entry, str) and entry in Rarity.__members__
            ]
            label_lookup = {
                rarity.name: self._humanize_name(rarity.name)
                for rarity in natural_entries
            }
        elif argument.field == SortField.Color:
            natural_entries = sorted(
                [color for color in DyeColor if color != DyeColor.NoColor],
                key=lambda color: int(color.value),
            )
            valid_names = [
                entry
                for entry in argument.custom_order
                if isinstance(entry, str) and entry in DyeColor.__members__ and entry != DyeColor.NoColor.name
            ]
            label_lookup = {
                color.name: self._humanize_name(color.name)
                for color in natural_entries
            }
        else:
            return [], [], ''

        prioritized_names = list(valid_names)
        if argument.direction == SortDirection.Descending:
            prioritized_names.reverse()

        natural_names = [entry.name for entry in natural_entries]
        remaining_names = [entry_name for entry_name in natural_names if entry_name not in valid_names]
        return (
            [label_lookup[entry_name] for entry_name in prioritized_names if entry_name in label_lookup],
            [label_lookup[entry_name] for entry_name in remaining_names if entry_name in label_lookup],
            self._humanize_name(argument.field.value),
        )

    def _draw_sort_argument_order_tooltip(self, argument: SortArgument) -> None:
        PyImGui.set_next_window_size((400, 0), cond=PyImGui.ImGuiCond.Appearing)
        if not PyImGui.begin_tooltip():
            return

        field_label = self._humanize_name(argument.field.value)
        ImGui.text_colored(f'{field_label} Order Preview', UI.CREME_COLOR.color_tuple, font_size=14)
        ImGui.separator()

        if argument.field in {SortField.ItemType, SortField.Rarity, SortField.Color}:
            prioritized_labels, remaining_labels, _ = self._get_sort_argument_named_entry_labels(argument)

            if not argument.has_custom_order:
                ImGui.text_wrapped('Natural order for this field:')
                preview_labels = remaining_labels
            else:
                ImGui.text_wrapped('Prioritized entries come first in this order:')
                preview_labels = prioritized_labels

            for index, label in enumerate(preview_labels[:12], start=1):
                ImGui.text(f'{index}. {label}')

            if len(preview_labels) > 12:
                ImGui.text_colored(f'... and {len(preview_labels) - 12} more', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

            if argument.has_custom_order:
                ImGui.separator()
                ImGui.text_wrapped('Remaining entries are equal priority in this argument. Later sort arguments decide their order.')
                ImGui.text_colored('Natural remainder reference:', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                for label in remaining_labels[:8]:
                    ImGui.text(label)
                if len(remaining_labels) > 8:
                    ImGui.text_colored(f'... and {len(remaining_labels) - 8} more', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
        elif argument.field == SortField.ModelId:
            if not argument.has_custom_order:
                natural_text = 'lower model IDs first' if argument.direction == SortDirection.Ascending else 'higher model IDs first'
                ImGui.text_wrapped(f'Natural order: {natural_text}.')
            else:
                ImGui.text_wrapped('Prioritized items come first in this order:')
                normalized_entries = [
                    self._normalize_sort_argument_model_item_entry(entry)
                    for entry in argument.custom_order
                ]
                visible_entries = [entry for entry in normalized_entries if entry is not None]
                if argument.direction == SortDirection.Descending:
                    visible_entries.reverse()
                for index, (model_id, item_type) in enumerate(visible_entries[:10], start=1):
                    label, subtitle = self._get_sort_argument_model_item_label(model_id, item_type)
                    ImGui.text(f'{index}. {label}')
                if len(visible_entries) > 10:
                    ImGui.text_colored(f'... and {len(visible_entries) - 10} more', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                ImGui.separator()
                ImGui.text_wrapped('Remaining items are equal priority in this argument. Later sort arguments decide their order.')
        else:
            natural_text = 'low to high' if argument.direction == SortDirection.Ascending else 'high to low'
            ImGui.text_wrapped(f'Natural order: {natural_text}.')

        PyImGui.end_tooltip()

    @staticmethod
    def _normalize_sort_argument_model_item_entry(entry: Any) -> tuple[int, ItemType | None] | None:
        if isinstance(entry, int):
            return int(entry), None
        if not isinstance(entry, dict):
            return None

        model_id = entry.get('model_id')
        item_type_name = entry.get('item_type')
        if not isinstance(model_id, int):
            return None
        if isinstance(item_type_name, str) and item_type_name in ItemType.__members__:
            return int(model_id), ItemType[item_type_name]
        return int(model_id), None

    def _get_sort_argument_model_item_label(self, model_id: int, item_type: ItemType | None) -> tuple[str, str]:
        effective_item_type = item_type or ItemType.Unknown
        label = self._get_item_label(model_id, effective_item_type, fallback=f'Model {model_id}')
        if item_type is None:
            subtitle = f'Model ID: {model_id}'
        else:
            subtitle = f'{self._item_type_name(item_type)} | Model ID: {model_id}'
        return label, subtitle

    @staticmethod
    def _move_list_entry(entries: list[Any], source_index: int, target_index: int) -> None:
        if source_index == target_index or source_index < 0 or target_index < 0:
            return
        if source_index >= len(entries) or target_index >= len(entries):
            return
        entry = entries.pop(source_index)
        entries.insert(target_index, entry)

    def _draw_sort_argument_model_id_order(self, argument: SortArgument, unique_id: str) -> bool:
        changed = False
        popup_id = f'##sort_argument_model_ids_{unique_id}'
        search_state_key = f'sort_argument_model_ids_{unique_id}'
        selected_entries = {
            normalized_entry
            for normalized_entry in (
                self._normalize_sort_argument_model_item_entry(entry)
                for entry in argument.custom_order
            )
            if normalized_entry is not None
        }
        style = ImGui.get_style()
        spacing = style.ItemSpacing.value2 or 0
        element_height = 48

        if ImGui.button(f'Add Item##{unique_id}', -1):
            PyImGui.open_popup(popup_id)

        PyImGui.set_next_window_size((320, 0), cond=PyImGui.ImGuiCond.Appearing)
        if PyImGui.begin_popup(popup_id):
            ImGui.text('Add Prioritized Item')
            PyImGui.set_next_item_width(-1)
            self._focus_popup_search_field_on_appearing()
            current_search = self._get_search_field_value(search_state_key)
            _, current_search = ImGui.search_field(
                f'##sort_argument_model_id_search_{unique_id}',
                current_search,
                'Search items...',
            )
            self._set_search_field_value(search_state_key, current_search)
            search_query, matching_model_ids_raw = self._get_live_search_results(
                search_state_key,
                current_search,
                lambda normalized_query: cast(list[Any], self._filter_cached_entries(self._model_id_item_search_cache, normalized_query, self._model_id_item_search_entries)),
            )
            matching_items = cast(list[ItemData], matching_model_ids_raw)

            if ImGui.begin_child(f'##sort_argument_model_id_candidates_{unique_id}', (0, 320), border=True):
                for item in matching_items:
                    entry_key = (int(item.model_id), item.item_type)
                    already_selected = entry_key in selected_entries
                    if not already_selected:
                        if PyImGui.is_rect_visible((0, 34)):
                            if ImGui.begin_selectable(f'##sort_argument_model_id_{unique_id}_{item.model_id}_{item.item_type.name}', False, (0, 34), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                ImGui.text(self._get_item_display_name(item))
                                x, y = PyImGui.get_cursor_pos()
                                PyImGui.set_cursor_pos((x, y - 4))
                                ImGui.text_colored(
                                    f'{self._item_type_name(item.item_type)} | Model ID: {int(item.model_id)}',
                                    UI.SUBTLE_TEXT_COLOR.color_tuple,
                                    font_size=12,
                                )
                            if ImGui.end_selectable() and not already_selected:
                                argument.custom_order.append({
                                    'model_id': int(item.model_id),
                                    'item_type': item.item_type.name,
                                })
                                changed = True
                                PyImGui.close_current_popup()
                        else:
                            PyImGui.dummy((0, 34))
            ImGui.end_child()

            if ImGui.button('Cancel', -1):
                PyImGui.close_current_popup()

            PyImGui.end_popup()

        normalized_entries = [
            (index, normalized_entry)
            for index, normalized_entry in (
                (index, self._normalize_sort_argument_model_item_entry(entry))
                for index, entry in enumerate(argument.custom_order)
            )
            if normalized_entry is not None
        ]

        if ImGui.begin_child(f'##sort_argument_model_id_selected_{unique_id}', (0, 0), border=False):
            for visible_index, (entry_index, (model_id, item_type)) in enumerate(normalized_entries):
                label, subtitle = self._get_sort_argument_model_item_label(model_id, item_type)
                item_unique_id = f'sort_argument_model_id_order_{unique_id}_{model_id}_{item_type.name if item_type is not None else "any"}_{entry_index}'
                if ImGui.begin_child(f'##{item_unique_id}', (0, element_height), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_ARROW_UP}##{item_unique_id}_up', 26, 30) and visible_index > 0:
                        previous_entry_index = normalized_entries[visible_index - 1][0]
                        self._move_list_entry(argument.custom_order, entry_index, previous_entry_index)
                        changed = True
                    PyImGui.same_line(0, 4)
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_ARROW_DOWN}##{item_unique_id}_down', 26, 30) and visible_index < len(normalized_entries) - 1:
                        next_entry_index = normalized_entries[visible_index + 1][0]
                        self._move_list_entry(argument.custom_order, entry_index, next_entry_index)
                        changed = True
                    PyImGui.same_line(0, 4)
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_TRASH}##{item_unique_id}_delete', 26, 30):
                        argument.custom_order.pop(entry_index)
                        changed = True
                        ImGui.end_child()
                        break

                    PyImGui.same_line(0, 8)
                    PyImGui.begin_group()
                    ImGui.text(label)
                    x, y = PyImGui.get_cursor_pos()
                    PyImGui.set_cursor_pos((x, y - 4))
                    ImGui.text_colored(subtitle, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                    PyImGui.end_group()
                ImGui.end_child()
        ImGui.end_child()

        return changed

    def _draw_sort_argument_named_order(self, argument: SortArgument, unique_id: str) -> bool:
        changed = False
        if argument.field == SortField.ItemType:
            available_entries = list(self._sorted_item_types)
            selected_names = [entry for entry in argument.custom_order if isinstance(entry, str) and entry in ItemType.__members__]
            label_getter = lambda entry: self._humanize_name(entry.name)
            add_label = 'Add Item Type'
        elif argument.field == SortField.Rarity:
            available_entries = list(self._sorted_rarities)
            selected_names = [entry for entry in argument.custom_order if isinstance(entry, str) and entry in Rarity.__members__]
            label_getter = lambda entry: self._humanize_name(entry.name)
            add_label = 'Add Rarity'
        elif argument.field == SortField.Color:
            available_entries = [entry for entry in self._sorted_dye_colors if entry != DyeColor.NoColor]
            selected_names = [entry for entry in argument.custom_order if isinstance(entry, str) and entry in DyeColor.__members__]
            label_getter = lambda entry: self._humanize_name(entry.name)
            add_label = 'Add Color'
        else:
            return False

        remaining_entries = [entry for entry in available_entries if entry.name not in selected_names]
        add_index = 0
        add_labels = [label_getter(entry) for entry in remaining_entries]

        PyImGui.set_next_item_width(-1)
        next_index = ImGui.combo(f'##sort_argument_named_order_add_{unique_id}', add_index, ['Select entry to add'] + add_labels)
        if next_index > 0:
            argument.custom_order.append(remaining_entries[next_index - 1].name)
            changed = True

        ImGui.text_colored(add_label, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

        if ImGui.begin_child(f'##sort_argument_named_selected_{unique_id}', (0, 0), border=False):
            for index, entry_name in enumerate(list(selected_names)):
                item_unique_id = f'sort_argument_named_order_{unique_id}_{entry_name}_{index}'
                if argument.field == SortField.ItemType:
                    color_tuple = UI.SUBTLE_TEXT_COLOR.color_tuple
                elif argument.field == SortField.Rarity:
                    color_tuple = self._get_rarity_color(Rarity[entry_name]).color_tuple if entry_name in Rarity.__members__ else UI.SUBTLE_TEXT_COLOR.color_tuple
                else:
                    color_tuple = UI.SUBTLE_TEXT_COLOR.color_tuple

                if ImGui.begin_child(f'##{item_unique_id}', (0, 40), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_ARROW_UP}##{item_unique_id}_up', 26, 24) and index > 0:
                        self._move_list_entry(argument.custom_order, index, index - 1)
                        changed = True
                    PyImGui.same_line(0, 4)
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_ARROW_DOWN}##{item_unique_id}_down', 26, 24) and index < len(selected_names) - 1:
                        self._move_list_entry(argument.custom_order, index, index + 1)
                        changed = True
                    PyImGui.same_line(0, 4)
                    if ImGui.icon_button(f'{IconsFontAwesome5.ICON_TRASH}##{item_unique_id}_delete', 26, 24):
                        argument.custom_order.pop(index)
                        changed = True
                        ImGui.end_child()
                        break
                    PyImGui.same_line(0, 8)
                    ImGui.text_colored(self._humanize_name(entry_name), color_tuple)
                ImGui.end_child()
        ImGui.end_child()

        return changed

    def _draw_sort_argument_custom_order_popup(self, argument: SortArgument, popup_id: str, unique_id: str) -> bool:
        changed = False
        PyImGui.set_next_window_size((420, 520), cond=PyImGui.ImGuiCond.Always)
        if not PyImGui.begin_popup(popup_id):
            return False

        ImGui.text(f'Prioritized {self._humanize_name(argument.field.value)}')
        ImGui.text_wrapped('Listed entries are ranked first in this exact order. Items with the same priority still fall back to the default sort arguments.')
        ImGui.separator()

        if argument.field == SortField.ModelId:
            changed = self._draw_sort_argument_model_id_order(argument, unique_id) or changed
            
        elif argument.field in {SortField.ItemType, SortField.Rarity, SortField.Color}:
            changed = self._draw_sort_argument_named_order(argument, unique_id) or changed
        else:
            ImGui.text_wrapped('This sort field does not support a custom prioritized order.')

        if ImGui.button('Close', -1):
            PyImGui.close_current_popup()

        PyImGui.end_popup()
        return changed

    def _draw_sort_argument_editor(self, sorter: Sorter, unique_id: str) -> bool:
        changed = False
        field_options = list(SortField)
        field_labels = [self._humanize_name(field.value) for field in field_options]

        if ImGui.begin_child(f'##sort_arguments_{unique_id}', (0, 0), border=True):
            if ImGui.button(f'{IconsFontAwesome5.ICON_PLUS} Add Sort Argument##{unique_id}', -1):
                sorter.arguments.append(SortArgument())
                changed = True

            if ImGui.begin_child(f'##sort_arguments_members_{unique_id}', (0, 0), border=False):
                style = ImGui.get_style()
            
                style.CellPadding.push_style_var_direct(2, 2)
                if ImGui.begin_table(f'##sort_arguments_table_{unique_id}', 6, PyImGui.TableFlags.SizingStretchProp):
                    PyImGui.table_setup_column('##Up', PyImGui.TableColumnFlags.WidthFixed, 30)
                    PyImGui.table_setup_column('##Down', PyImGui.TableColumnFlags.WidthFixed, 30)
                    PyImGui.table_setup_column('Argument', PyImGui.TableColumnFlags.WidthStretch, 100)
                    PyImGui.table_setup_column('Direction', PyImGui.TableColumnFlags.WidthFixed, 120)
                    PyImGui.table_setup_column('Priority', PyImGui.TableColumnFlags.WidthFixed, 160)
                    PyImGui.table_setup_column('##Delete', PyImGui.TableColumnFlags.WidthFixed, 30)
                
                    PyImGui.table_headers_row()
                    PyImGui.table_next_row()
                    PyImGui.table_next_column()
                                        
                    for index, argument in enumerate(list(sorter.arguments)):
                        row_id = f'sort_argument_{unique_id}_{index}'
                        popup_id = f'##sort_argument_custom_order_popup_{row_id}'
                        
                        if ImGui.icon_button(f'{IconsFontAwesome5.ICON_ARROW_UP}##{row_id}_up', -1, 24) and index > 0:
                            sorter.arguments[index - 1], sorter.arguments[index] = sorter.arguments[index], sorter.arguments[index - 1]
                            changed = True
                            
                        PyImGui.table_next_column()
                        
                        if ImGui.icon_button(f'{IconsFontAwesome5.ICON_ARROW_DOWN}##{row_id}_down', -1, 24) and index < len(sorter.arguments) - 1:
                            sorter.arguments[index + 1], sorter.arguments[index] = sorter.arguments[index], sorter.arguments[index + 1]
                            changed = True
                            
                        PyImGui.table_next_column()
                        
                        current_field_index = field_options.index(argument.field) if argument.field in field_options else 0
                        PyImGui.set_next_item_width(-1)
                        next_field_index = ImGui.combo(f'##{row_id}_field', current_field_index, field_labels)
                        if next_field_index != current_field_index:
                            argument.field = field_options[next_field_index]
                            argument.custom_order = []
                            changed = True
                            
                        PyImGui.table_next_column()
                        PyImGui.set_next_item_width(-1)
                        if PyImGui.begin_combo(f'##{row_id}_direction', argument.direction.name, PyImGui.ImGuiComboFlags.NoFlag):
                            for direction in SortDirection:
                                is_selected = argument.direction == direction
                                if ImGui.selectable(direction.name, is_selected, flags=PyImGui.SelectableFlags.NoFlag, size=(0, 24)):
                                    argument.direction = direction
                                    changed = True
                            PyImGui.end_combo()
                        
                        PyImGui.table_next_column()
                        if argument.supports_custom_order:
                            button_label = self._format_sort_argument_custom_order_summary(argument)
                            if ImGui.button(f'{button_label}##{row_id}_priority', -1, 24):
                                PyImGui.open_popup(popup_id)
                            
                            if PyImGui.is_item_hovered():
                                self._draw_sort_argument_order_tooltip(argument)
                            
                            
                            changed = self._draw_sort_argument_custom_order_popup(argument, popup_id, row_id) or changed
                        else:
                            ImGui.text_colored('Natural only', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                        PyImGui.table_next_column()
                        if ImGui.icon_button(f'{IconsFontAwesome5.ICON_TRASH}##{row_id}_delete', -1, 24):
                            sorter.arguments.pop(index)
                            changed = True
                        PyImGui.table_next_column()
                    
                
                    ImGui.end_table()
                style.CellPadding.pop_style_var_direct()
                    
            ImGui.end_child()
            
        ImGui.end_child()

        return changed

    def _execute_bag_sort(self, bags: list[Bags]) -> None:
        action_node = BT.Items.Bags.SortBags(bags)
        action_node.tick()
        self._invalidate_inventory_preview_cache()
        self.preview_throttle.Reset()

    def _execute_bag_compact(self, bags: list[Bags]) -> None:
        action_node = BT.Items.Bags.CompactBags(bags)
        action_node.tick()
        self._invalidate_inventory_preview_cache()
        self.preview_throttle.Reset()

    def _refresh_sorting_bag_size_cache(self) -> None:
        self._sorting_bag_size_cache = {
            bag: PyInventory.Bag(bag.value, bag.name).GetSize()
            for bag in [*INVENTORY_BAGS, *STORAGE_BAGS]
        }

    def _refresh_sorting_assigned_slot_cache(self) -> None:
        if self.config is None or not isinstance(self.config.config, SortingConfig):
            self._sorting_assigned_slot_cache = set()
            return

        self._sorting_assigned_slot_cache = {
            (slot_ref.bag, slot_ref.slot)
            for group in self.config.config.slot_groups
            if group.enabled
            for slot_ref in group.normalized_slot_refs()
        }

    def _draw_slot_group_slot_selector_popup(self, group: SlotGroupConfig, popup_id: str) -> bool:
        changed = False
        PyImGui.set_next_window_size((900, 700), cond=PyImGui.ImGuiCond.Always)
        popup_open = PyImGui.begin_popup(popup_id)
        if popup_open:
            self._sorting_slot_selector_popup_id = popup_id
            self._sorting_slot_selector_group = group
            ImGui.text('Select Slots')
            ImGui.text_wrapped('Pick the slots that belong to this group. You can combine slots from any inventory bag or storage tab.')
            ImGui.separator()

            changed = self.draw_slot_selector() or changed

            selected_slot_refs = [
                SlotReference(bag, slot)
                for bag, slot in sorted(self._sorting_slot_picker_selection, key=lambda entry: (entry[0].value, entry[1]))
            ]

            ImGui.separator()
            ImGui.text_colored(
                f'{len(selected_slot_refs)} slot(s) selected',
                UI.SUBTLE_TEXT_COLOR.color_tuple,
                font_size=12,
            )
            
            PyImGui.end_popup()
        elif self._sorting_slot_selector_popup_id == popup_id and self._sorting_slot_selector_group is group:
            selected_slot_refs = [
                SlotReference(bag, slot)
                for bag, slot in sorted(self._sorting_slot_picker_selection, key=lambda entry: (entry[0].value, entry[1]))
            ]
            changed = self._apply_slot_group_assignment(group, selected_slot_refs, override_existing=False) or changed
            self._sorting_slot_selector_popup_id = None
            self._sorting_slot_selector_group = None

            
        return self._draw_sorting_slot_override_popup() or changed

    def draw_slot_selector(self, config_info: Optional[ConfigInfo[SortingConfig]] = None) -> bool:
        style = ImGui.get_style()
        changed = False
        selected_slot_set = set(self._sorting_slot_picker_selection)
        
        slot_size = 24
        grid_size = (slot_size * BAG_ROW_SLOTS) + 4
        
        width, height = PyImGui.get_content_region_avail()
        item_spacing = style.ItemSpacing.value1
        columns = max(1, int((width - 4) / (grid_size + item_spacing)))
        PyImGui.columns(columns, '##inventory_sorting_columns', False)
        
        style.CellPadding.push_style_var_direct(1, 1)
        for b in INVENTORY_BAGS:
            changed = self.draw_bag_selector(b, slot_size, grid_size, style, selected_slot_set) or changed
            PyImGui.next_column()
        PyImGui.end_columns()
        
        
        PyImGui.columns(columns, '##storage_sorting_columns', False)
        for b in STORAGE_BAGS:
            changed = self.draw_bag_selector(b, slot_size, grid_size, style, selected_slot_set) or changed
            PyImGui.next_column()
            pass
        style.CellPadding.pop_style_var_direct()
        
        PyImGui.end_columns()
        return changed

    def draw_bag_selector(self, b : Bags, slot_size : float, grid_size : float, style : Style, selected_slot_set: set[tuple[Bags, int]]) -> bool:
        changed = False
        bag_size = MAX_BAG_SIZES.get(b, 0)        
        PyImGui.begin_group()
        if ImGui.button(self._humanize_name(b.name), width=grid_size, height=20):
            any_selected_in_bag = any((b, slot) in selected_slot_set for slot in range(bag_size))
            if any_selected_in_bag:
                self._sorting_slot_picker_selection = [(bag, slot) for (bag, slot) in self._sorting_slot_picker_selection if bag != b]
            else:
                self._sorting_slot_picker_selection.extend([(b, slot) for slot in range(bag_size) if (b, slot) not in selected_slot_set])
            changed = True
    
        inventory_bag_size = self._sorting_bag_size_cache.get(b, 0)
            
        if ImGui.begin_table(f'##sorting_bag_{b}', BAG_ROW_SLOTS, PyImGui.TableFlags.NoHostExtendX, width=grid_size + 4, height=grid_size):
            PyImGui.table_next_row()
            PyImGui.table_next_column()
                
            for slot in range(bag_size):
                slot_id = (b, slot)
                is_selected = slot_id in selected_slot_set
                has_rule = self._sorting_slot_has_rule(slot_id)
                
                is_available = slot < inventory_bag_size
                if has_rule:
                    style.ChildBg.push_color_direct(UI.OPAGUE_RED_COLOR.rgb_tuple)
                
                elif not is_available:
                    style.ChildBg.push_color_direct(UI.SUBTLE_TEXT_COLOR.rgb_tuple)
                    
                if ImGui.begin_selectable(f'##sorting_bag_{b}_slot_{slot}', size=(slot_size, slot_size), border=True, border_color=UI.SUBTLE_TEXT_COLOR.rgb_tuple, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple, selected=is_selected):
                    pass
                    
                if ImGui.end_selectable():
                    if is_selected:
                        self._sorting_slot_picker_selection.remove(slot_id)
                    else:
                        self._sorting_slot_picker_selection.append(slot_id)
                    changed = True
                        
                if has_rule or not is_available:
                    style.ChildBg.pop_color_direct()
                    
                if has_rule:
                    ImGui.show_tooltip('This slot is already assigned to a slot group. Selecting it will move it to the current group and remove it from the other group.')
                
                elif not is_available:
                    ImGui.show_tooltip('This slot index exceeds the current size of the bag. It may become available if you add an expansion or buy more storage tabs.')
                    
                PyImGui.table_next_column()
                    
            ImGui.end_table()
        PyImGui.end_group()
        return changed
        
    def _sorting_slot_has_rule(self, slot_id: tuple[Bags, int]) -> bool:
        return slot_id in self._sorting_assigned_slot_cache

    def _get_sorting_slot_conflict_groups(self, target_group: SlotGroupConfig, slot_refs: list[SlotReference]) -> list[SlotGroupConfig]:
        if self.config is None or not isinstance(self.config.config, SortingConfig):
            return []

        conflicts: list[SlotGroupConfig] = []
        target_slot_refs = set(slot_refs)
        for group in self.config.config.slot_groups:
            if group is target_group:
                continue
            if not group.enabled:
                continue
            if target_slot_refs.intersection(group.normalized_slot_refs()):
                conflicts.append(group)
        return conflicts

    def _apply_slot_group_assignment(self, target_group: SlotGroupConfig, slot_refs: list[SlotReference], override_existing: bool) -> bool:
        normalized_slot_refs = sorted(set(slot_refs), key=lambda slot_ref: (slot_ref.bag.value, slot_ref.slot))
        conflicts = self._get_sorting_slot_conflict_groups(target_group, normalized_slot_refs)
        if conflicts and not override_existing:
            self._sorting_pending_slot_group = target_group
            self._sorting_pending_slot_refs = list(normalized_slot_refs)
            self._sorting_pending_conflict_groups = conflicts
            self._sorting_slot_override_popup_requested = True
            return False

        slot_ref_set = set(normalized_slot_refs)
        for group in conflicts:
            group.slot_refs = [
                slot_ref
                for slot_ref in group.normalized_slot_refs()
                if slot_ref not in slot_ref_set
            ]

        target_group.slot_refs = list(normalized_slot_refs)
        self._sorting_slot_picker_selection = [(slot_ref.bag, slot_ref.slot) for slot_ref in target_group.normalized_slot_refs()]
        self.selected_bag_slots = list(self._sorting_slot_picker_selection)
        self._save_active_config()
        return True

    def _draw_sorting_slot_override_popup(self) -> bool:
        changed = False
        if self._sorting_slot_override_popup_requested:
            PyImGui.open_popup(self._sorting_slot_override_popup_id)

        PyImGui.set_next_window_size((460, 0), cond=PyImGui.ImGuiCond.Appearing)
        if PyImGui.begin_popup_modal(self._sorting_slot_override_popup_id, True, PyImGui.WindowFlags.AlwaysAutoResize):
            self._sorting_slot_override_popup_requested = False
            ImGui.text('Override Slot Assignments')
            ImGui.text_wrapped('Some selected slots are already assigned to another slot group. Overriding will remove those slots from the other groups.')
            ImGui.separator()

            for group in self._sorting_pending_conflict_groups:
                ImGui.text_wrapped(f'- {group.display_name()}')

            if ImGui.button('Override', 160):
                if self._sorting_pending_slot_group is not None:
                    changed = self._apply_slot_group_assignment(
                        self._sorting_pending_slot_group,
                        self._sorting_pending_slot_refs,
                        override_existing=True,
                    )
                self._sorting_slot_override_popup_requested = False
                self._sorting_pending_slot_group = None
                self._sorting_pending_slot_refs = []
                self._sorting_pending_conflict_groups = []
                PyImGui.close_current_popup()

            PyImGui.same_line(0, 8)
            if ImGui.button('Cancel', 160):
                self._sorting_slot_override_popup_requested = False
                self._sorting_pending_slot_group = None
                self._sorting_pending_slot_refs = []
                self._sorting_pending_conflict_groups = []
                PyImGui.close_current_popup()

            PyImGui.end_popup()

        return changed
    
    def draw_slot_group_config(self, config_info: ConfigInfo[SortingConfig], group: SlotGroupConfig) -> None:
        changed = False
        unique_id = f'{id(group)}'
        slot_popup_id = f'##sorting_slot_selector_popup_{unique_id}'

        ImGui.text_aligned("Name", alignment=Alignment.MidLeft, height=25)
        PyImGui.same_line(60, 5)

        PyImGui.begin_disabled(group.is_default)
        PyImGui.set_next_item_width(-1)
        rule_name_input_id = f"##rule_name_{id(group)}"
        name = ImGui.input_text(rule_name_input_id, group.name or "")
        if name != group.name:
            group.name = name
            self._save_active_config()

        ImGui.text_aligned("Enabled" if group.enabled else "Disabled", alignment=Alignment.MidLeft, height=25, color=UI.GREEN_COLOR.color_tuple if group.enabled else UI.RED_COLOR.color_tuple)
        PyImGui.same_line(60, 5)
        enabled = PyImGui.checkbox("##rule_enabled", group.enabled)
        
        if not group.is_default:
            if enabled != group.enabled:
                group.enabled = enabled
                self._save_active_config()
            ImGui.show_tooltip("Whether this rule is active. Disabled rules are ignored but keep their settings.")
            PyImGui.same_line(0, 5)
            if ImGui.button(f'Choose Slots##sorting_group_slots_{unique_id}', -1):
                self._sorting_slot_picker_selection = [(slot_ref.bag, slot_ref.slot) for slot_ref in group.normalized_slot_refs()]
                self.selected_bag_slots = list(self._sorting_slot_picker_selection)
                self._sorting_slot_selector_popup_id = slot_popup_id
                self._sorting_slot_selector_group = group
                self._refresh_sorting_bag_size_cache()
                PyImGui.open_popup(slot_popup_id)
            
            if PyImGui.is_item_hovered():
                if PyImGui.begin_tooltip():
                    PyImGui.push_text_wrap_pos(300)
                    ImGui.text_wrapped(self._slot_group_selection_summary(group))
                    PyImGui.pop_text_wrap_pos()
                    PyImGui.end_tooltip()
        PyImGui.end_disabled()

        if group.is_default:
            PyImGui.same_line(0, 5)
            ImGui.text_aligned('This policy is used for every slot that is not assigned to a special slot group.', alignment=Alignment.MidLeft, height=23)
            PyImGui.set_cursor_pos_y(PyImGui.get_cursor_pos_y() + 10)
                                
        if self._draw_slot_group_slot_selector_popup(group, slot_popup_id):
            changed = True
            
        
        if PyImGui.begin_tab_bar(f'##sorting_group_tabs_{unique_id}'):
            if PyImGui.begin_tab_item('Sort Items By'):
                ImGui.text_wrapped('Items will be sorted in the order of these sort arguments (Top to Bottom). The default arguments are usually sufficient for most sorting needs, but you can add custom arguments or change their priority if you want to fine-tune the sorting behavior.')
                changed = self._draw_sort_argument_editor(group.sorter, unique_id) or changed
                PyImGui.end_tab_item()
            
            if not group.is_default and PyImGui.begin_tab_item('Filter Conditions'):
                ImGui.text_wrapped('Only items matching these conditions will be sorted into this slot group. Leave the list empty to allow any item that reaches this group.')
                ImGui.separator()
                changed = self._draw_custom_rule(
                    group.matcher,
                    condition_types=self._get_all_condition_types(),
                    editable_only=False,
                ) or changed
                PyImGui.end_tab_item()
            PyImGui.end_tab_bar()
            
        if changed:
            self._save_active_config()

    def draw_sorting_config(self, config_info: ConfigInfo[SortingConfig]) -> None:
        config = config_info.config
        self._sync_selected_sorting_group()
        active_drag = self._drag_sorting_group_source_config is config_info and self._drag_sorting_group is not None
        self._drag_sorting_group_target_rect = None
        scroll_y = 0.0
        self._draw_sorting_group_delete_popup()

        if ImGui.begin_table('##sorting_config_table', 2, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable):
            PyImGui.table_setup_column('Navigation', PyImGui.TableColumnFlags.WidthFixed, 220)
            PyImGui.table_setup_column('Content', PyImGui.TableColumnFlags.WidthStretch)

            PyImGui.table_next_row()
            PyImGui.table_next_column()

            if ImGui.button('Add Sort Policy', -1):
                new_group = SlotGroupConfig(
                    slot_refs=[],
                    sorter=type(config.default_group.sorter)(),
                )
                config.slot_groups.append(new_group)
                config_info.save()
                self._set_active_sorting_group(new_group)

            ImGui.separator()
            PyImGui.spacing()

            item_height = 46
            self.rules_hovered = False
            if ImGui.begin_child('##sorting_groups', (0, 0), border=False):
                io = PyImGui.get_io()
                child_pos = PyImGui.get_window_pos()
                child_size = PyImGui.get_window_size()
                child_visible_left = child_pos[0]
                child_visible_top = child_pos[1]
                child_visible_right = child_pos[0] + child_size[0]
                child_visible_bottom = child_pos[1] + child_size[1]
                default_policy_rect: tuple[float, float, float, float] | None = None
                group_rects: dict[int, tuple[float, float, float, float]] = {}
                group_gap_values: list[float] = []
                style = ImGui.get_style()

                style.ButtonActive.push_color_direct((0,0,0,0))
                style.Button.push_color_direct((0,0,0,0))
                style.ButtonHovered.push_color_direct((0,0,0,0))

                cx, cy = PyImGui.get_cursor_pos()
                PyImGui.button('##sorting_default_sorter_button', -1, 48)
                PyImGui.set_next_item_allow_overlap()
                PyImGui.set_cursor_pos((cx, cy))

                if ImGui.begin_selectable('##sorting_default_sorter', selected=self.sorting_group is None, size=(0, 48), border=True, child_flags=PyImGui.WindowFlags.NoInputs|PyImGui.WindowFlags.NoBringToFrontOnFocus|PyImGui.WindowFlags.NoScrollWithMouse|PyImGui.WindowFlags.NoScrollbar, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                    ImGui.text('Default Sort Policy')
                    x, y = PyImGui.get_cursor_pos()
                    PyImGui.set_cursor_pos((x, y - 4))
                    ImGui.text_colored(f'{len(config.default_group.sorter.arguments)} Sort {"Argument" if len(config.default_group.sorter.arguments) == 1 else "Arguments"}', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                if ImGui.end_selectable():
                    self._set_active_sorting_group(None)
                default_item_min, default_item_max, _ = ImGui.get_item_rect()
                default_policy_rect = (default_item_min[0], default_item_min[1], default_item_max[0], default_item_max[1])

                default_hovered = PyImGui.is_item_hovered()
                self.rules_hovered = self.rules_hovered or default_hovered
                if default_hovered:
                    ImGui.show_tooltip('This is the default sort policy that applies to any slot that is not assigned to a custom slot group.')

                for i, group in enumerate(config.slot_groups):
                    if PyImGui.is_rect_visible((5, item_height)):
                        group_label = group.name or f'Slot Group #{i + 1}'
                        group_summary = self._slot_group_selection_summary(group)

                        cx, cy = PyImGui.get_cursor_pos()
                        PyImGui.button(f"##sorting_group_nav_button_{i}", -1, item_height)
                        PyImGui.set_next_item_allow_overlap()
                        PyImGui.set_cursor_pos((cx, cy))

                        if ImGui.begin_selectable(f'##sorting_group_nav_{i}', selected=self.sorting_group is group, size=(0, item_height), border=True, child_flags=PyImGui.WindowFlags.NoInputs|PyImGui.WindowFlags.NoBringToFrontOnFocus|PyImGui.WindowFlags.NoScrollWithMouse|PyImGui.WindowFlags.NoScrollbar, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                            PyImGui.begin_disabled(not group.enabled)
                            ImGui.text(group_label)
                            x, y = PyImGui.get_cursor_pos()
                            PyImGui.set_cursor_pos((x, y - 4))
                            ImGui.text_colored(group_summary, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                            PyImGui.end_disabled()
                        
                        if ImGui.end_selectable():
                            self._set_active_sorting_group(group)

                        hovered = PyImGui.is_item_hovered()
                        self.rules_hovered = self.rules_hovered or hovered

                        if hovered and PyImGui.is_mouse_clicked(1):
                            self.context_menu_id = f"sorting_group_{i}"
                            self.context_menu_sorting_group = group
                            self.context_menu_config = config_info
                            PyImGui.open_popup(self.context_menu_id)

                        item_min, item_max, item_size = ImGui.get_item_rect()
                        hovered = PyImGui.is_item_hovered()
                        clicked = PyImGui.is_item_clicked(0)
                        in_rect = ImGui.is_mouse_in_rect((item_min[0], item_min[1], item_size[0], item_size[1]))
                        item_key = ('sorting_group', id(group))
                        self._remember_drag_clicked_item(item_key, clicked)
                        
                        if self._drag_sorting_group is None and self._can_start_drag_from_item(item_key, hovered):
                            self._begin_sorting_group_drag(config_info, group, i)

                        if self._drag_sorting_group_source_config is config_info and self._drag_sorting_group is not None:
                            group_rects[i] = (item_min[0], item_min[1], item_max[0], item_max[1])
                            if i > 0 and (i - 1) in group_rects:
                                previous_rect = group_rects[i - 1]
                                gap = item_min[1] - previous_rect[3]
                                if gap > 0.0:
                                    group_gap_values.append(gap)

                            if in_rect:
                                self._drag_sorting_group_target_index = i
                                self._drag_sorting_group_target_after = io.mouse_pos_y >= ((item_min[1] + item_max[1]) / 2.0)

                        if hovered:
                            PyImGui.set_next_window_size((300, 0), cond=PyImGui.ImGuiCond.Appearing)
                            if PyImGui.begin_tooltip():
                                ImGui.text_colored(group_label, color=UI.CREME_COLOR.color_tuple, font_size=16)
                            
                                sort_arguments = len(group.sorter.arguments)
                                conditions = len(group.matcher.conditions)
                                                                    
                                if sort_arguments > 0:
                                    ImGui.text(f'{sort_arguments} Sort {("Argument" if sort_arguments == 1 else "Arguments")}', font_size=14)
                                    
                                    PyImGui.columns(3, '##sorting_arguments_tooltip_columns', False)
                                    
                                    for argument_index, argument in enumerate(group.sorter.arguments):
                                        ImGui.text(f'{self._humanize_name(argument.field.value)}', font_size=12)
                                        PyImGui.next_column()
                                        ImGui.text(f'{argument.direction.name}', font_size=12)
                                        PyImGui.next_column()
                                        ImGui.text(f'{"Custom order" if argument.has_custom_order else "Default"}', font_size=12)
                                        if argument_index < sort_arguments - 1:
                                            PyImGui.next_column()
                                        
                                    PyImGui.end_columns()
                                
                                if sort_arguments > 0 and conditions > 0:
                                    PyImGui.separator()
                                
                                if conditions > 0:
                                    ImGui.text(f'{conditions} Filter {("Condition" if conditions == 1 else "Conditions")}', font_size=14)
                                    for condition in group.matcher.conditions:
                                        condition_name = self._humanize_name(type(condition).__name__).replace("Condition", "")
                                        ImGui.text(f"{condition_name}", font_size=12)
                                
                                PyImGui.separator()
                                ImGui.text_colored('Drag to reorder or right-click for more options', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                
                                PyImGui.end_tooltip()
                    else:
                        PyImGui.dummy((0, item_height))

                style.ButtonActive.pop_color_direct()
                style.Button.pop_color_direct()
                style.ButtonHovered.pop_color_direct()

                if len(config.slot_groups) > 0:
                    PyImGui.dummy((0, 10))
                    if self._drag_sorting_group_source_config is config_info and self._drag_sorting_group is not None and PyImGui.is_item_hovered():
                        self._drag_sorting_group_target_index = len(config.slot_groups) - 1
                        self._drag_sorting_group_target_after = True

                if active_drag:
                    edge_threshold = 18.0
                    scroll_y = PyImGui.get_scroll_y()
                    scroll_max_y = PyImGui.get_scroll_max_y()
                    mouse_y = io.mouse_pos_y

                    if mouse_y < child_visible_top and scroll_y > 0.0:
                        overshoot = min(child_visible_top - mouse_y, 40.0)
                        scroll_step = 6.0 + (overshoot / 40.0) * 18.0
                        PyImGui.set_scroll_y(max(0.0, scroll_y - scroll_step))
                    elif mouse_y > child_visible_bottom and scroll_y < scroll_max_y:
                        overshoot = min(mouse_y - child_visible_bottom, 40.0)
                        scroll_step = 6.0 + (overshoot / 40.0) * 18.0
                        PyImGui.set_scroll_y(min(scroll_max_y, scroll_y + scroll_step))

                    if group_rects:
                        if mouse_y <= child_visible_top + edge_threshold:
                            self._drag_sorting_group_target_index = min(group_rects.keys())
                            self._drag_sorting_group_target_after = False
                        elif mouse_y >= child_visible_bottom - edge_threshold:
                            self._drag_sorting_group_target_index = max(group_rects.keys())
                            self._drag_sorting_group_target_after = True

                if active_drag and self._drag_sorting_group_target_index in group_rects:
                    current_rect = group_rects[self._drag_sorting_group_target_index]
                    usual_gap = group_gap_values[0] if group_gap_values else 10.0
                    x1 = max(current_rect[0] + 4, child_visible_left + 4)
                    x2 = min(current_rect[2] - 4, child_visible_right - 4)
                    can_draw_target_rect = True
                    line_y = 0.0

                    if self._drag_sorting_group_target_after:
                        if self._drag_sorting_group_target_index + 1 in group_rects:
                            next_rect = group_rects[self._drag_sorting_group_target_index + 1]
                            line_y = (current_rect[3] + next_rect[1]) / 2.0
                        else:
                            if current_rect[3] < child_visible_bottom:
                                bottom_gap = child_visible_bottom - current_rect[3]
                                effective_gap = min(bottom_gap, usual_gap)
                                line_y = current_rect[3] + (effective_gap / 2.0)
                            else:
                                can_draw_target_rect = False
                    else:
                        if self._drag_sorting_group_target_index - 1 in group_rects:
                            previous_rect = group_rects[self._drag_sorting_group_target_index - 1]
                            line_y = (previous_rect[3] + current_rect[1]) / 2.0
                        elif default_policy_rect is not None:
                            line_y = (default_policy_rect[3] + current_rect[1]) / 2.0
                        else:
                            if current_rect[1] > child_visible_top:
                                line_y = (child_visible_top + current_rect[1]) / 2.0
                            elif scroll_y <= 0.0:
                                top_gap = max(current_rect[1] - child_visible_top, 0.0)
                                effective_gap = min(top_gap if top_gap > 0.0 else usual_gap, usual_gap)
                                line_y = child_visible_top + max(effective_gap / 2.0, 1.0)
                            else:
                                can_draw_target_rect = False

                    rect_y1 = max(line_y - 1, child_visible_top) if can_draw_target_rect else 0.0
                    rect_y2 = min(line_y + 1, child_visible_bottom) if can_draw_target_rect else 0.0
                    if can_draw_target_rect and x1 < x2 and rect_y1 < rect_y2:
                        self._drag_sorting_group_target_rect = (x1, rect_y1, x2, rect_y2)
                    else:
                        self._drag_sorting_group_target_rect = None

                if self.context_menu_id and self.context_menu_sorting_group and self.context_menu_config is config_info:
                    if not self.draw_sorting_group_context_menu(self.context_menu_id, config_info, self.context_menu_sorting_group):
                        self.context_menu_id = None
                        self.context_menu_sorting_group = None
                        self.context_menu_config = None
            ImGui.end_child()

            c_min, c_max, c_size = ImGui.get_item_rect()
            if active_drag and not ImGui.is_mouse_in_rect((c_min[0], c_min[1], c_size[0], c_size[1])):
                self._drag_sorting_group_target_rect = None

            PyImGui.table_next_column()

            if ImGui.begin_child('##sorting_group_content', (0, 0), border=False):
                if self.sorting_group is None:
                    self.draw_slot_group_config(config_info, config.default_group)
                    
                else:
                    self.draw_slot_group_config(config_info, self.sorting_group)
                    
            ImGui.end_child()

            ImGui.end_table()

        if active_drag and not PyImGui.is_mouse_down(0):
            self._apply_sorting_group_drag(config_info)

    def draw_sorting_config_preview(self, config: SortingConfig) -> None:
        ImGui.text('Preview', font_size=18)
        ImGui.text_wrapped('Preview the planned bag layout for the current sorting config. This shows the target slot layout before any moves are executed.')

        button_width = 110
        if ImGui.button('Inventory', button_width):
            self.sorting_preview_selected_bags = list(INVENTORY_BAGS)
            self._invalidate_sorting_preview_cache()
        PyImGui.same_line(0, 5)
        if ImGui.button('Storage', button_width):
            self.sorting_preview_selected_bags = list(STORAGE_BAGS)
            self._invalidate_sorting_preview_cache()
        PyImGui.same_line(0, 5)
        if ImGui.button('All', button_width):
            self.sorting_preview_selected_bags = [bag for bag in self.INVENTORY_PREVIEW_BAGS if bag != Bags.MaterialStorage]
            self._invalidate_sorting_preview_cache()
        PyImGui.same_line(0, 5)
        if ImGui.button('Sort Selected', button_width):
            self._execute_bag_sort(self.sorting_preview_selected_bags)
        ImGui.show_tooltip('Apply the current sorting policy to the selected bags.')
        PyImGui.same_line(0, 5)
        if ImGui.button('Compact Bags', button_width):
            self._execute_bag_compact(self.sorting_preview_selected_bags)
        ImGui.show_tooltip('Merge partial stacks across the selected bags to free up space.')

        if ImGui.begin_child('##sorting_preview_bags', (0, 90), border=True):
            width = PyImGui.get_content_region_avail()[0]
            columns = max(1, int(width // 170))
            PyImGui.columns(columns, 'sorting_preview_bag_columns', False)
            for bag in self.INVENTORY_PREVIEW_BAGS:
                is_selected = bag in self.sorting_preview_selected_bags
                selected = ImGui.checkbox(f'{self._humanize_name(bag.name)}##sorting_preview_{bag.name}', is_selected)
                if selected != is_selected:
                    if selected:
                        self.sorting_preview_selected_bags.append(bag)
                    else:
                        self.sorting_preview_selected_bags = [entry for entry in self.sorting_preview_selected_bags if entry != bag]
                    self._invalidate_sorting_preview_cache()
                PyImGui.next_column()
            PyImGui.end_columns()
        ImGui.end_child()

        if not self.sorting_preview_selected_bags:
            ImGui.text_wrapped('Select at least one bag or storage tab to preview.')
            return

        cache_key = self._build_sorting_preview_cache_key(config, self.sorting_preview_selected_bags)
        needs_rebuild = self._sorting_preview_cache_key != cache_key or self.sorting_preview_throttle.IsExpired()
        if self._sorting_preview_plan_tree is None and (self.sorting_preview_plan is None or needs_rebuild):
            self._sorting_preview_cache_key = cache_key
            self._sorting_preview_plan_tree = BT.Items.Bags.CreateBagSortPlanTree(self.sorting_preview_selected_bags)
            self._sorting_preview_plan_status = 'Starting sorting preview...'
            self._sorting_preview_plan_error = ''
            self.sorting_preview_throttle.Reset()

        if self._sorting_preview_plan_tree is not None:
            planner_state = BT.NodeState.RUNNING
            try:
                planner_state = self._sorting_preview_plan_tree.tick()
            except Exception as exc:
                planner_state = BT.NodeState.FAILURE
                self._sorting_preview_plan_error = f'{type(exc).__name__}: {exc!r}'

            self._sorting_preview_plan_status = getattr(self._sorting_preview_plan_tree, 'progress_text', self._sorting_preview_plan_status)
            self._sorting_preview_plan_error = getattr(self._sorting_preview_plan_tree, 'error_text', self._sorting_preview_plan_error)

            if planner_state == BT.NodeState.SUCCESS:
                self.sorting_preview_plan = cast(Optional[BagSortPlan], getattr(self._sorting_preview_plan_tree, 'plan_result', None))
                self._sorting_preview_plan_tree = None
            elif planner_state == BT.NodeState.FAILURE:
                self._sorting_preview_plan_tree = None

        plan = self.sorting_preview_plan
        if plan is None:
            if self._sorting_preview_plan_error:
                ImGui.text_colored(self._sorting_preview_plan_error, UI.RED_COLOR.color_tuple)
            else:
                ImGui.text_wrapped(self._sorting_preview_plan_status or 'Building sorting preview...')
            return
        for warning in plan.warnings:
            ImGui.text_colored(warning, UI.RED_COLOR.color_tuple)

        entries_by_bag: dict[Bags, list[BagSortPreviewEntry]] = {}
        for entry in plan.entries:
            if entry.bag not in entries_by_bag:
                entries_by_bag[entry.bag] = []
            
            entries_by_bag[entry.bag].append(entry)
        
        style = ImGui.get_style()
        if ImGui.begin_table('##sorting_preview_table', 8, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable | PyImGui.TableFlags.ScrollY | PyImGui.TableFlags.ScrollX | PyImGui.TableFlags.RowBg):
            PyImGui.table_setup_column('Bag', PyImGui.TableColumnFlags.WidthFixed, 110)
            PyImGui.table_setup_column('Slot', PyImGui.TableColumnFlags.WidthFixed, 45)
            PyImGui.table_setup_column('Target Item', PyImGui.TableColumnFlags.WidthFixed, 200)
            PyImGui.table_setup_column('From', PyImGui.TableColumnFlags.WidthFixed, 120)
            PyImGui.table_setup_column('Group', PyImGui.TableColumnFlags.WidthFixed, 150)
            PyImGui.table_setup_column('Allowed', PyImGui.TableColumnFlags.WidthFixed, 170)
            PyImGui.table_setup_column('Notes', PyImGui.TableColumnFlags.WidthFixed, 120)
            PyImGui.table_setup_column('Policy', PyImGui.TableColumnFlags.WidthStretch)
            PyImGui.table_headers_row()

            for bag, entries in entries_by_bag.items():
                style.TableRowBg.push_color_direct(UI.RANDOM_COLORS[bag.value % len(UI.RANDOM_COLORS)].rgb_tuple)
                style.TableRowBgAlt.push_color_direct(UI.RANDOM_COLORS[bag.value % len(UI.RANDOM_COLORS)].rgb_tuple)
                for entry in entries:
                    item_name = entry.item.complete_name or entry.item.singular_name or entry.item.name if entry.item is not None else '(empty)'
                    source_text = f'{self._humanize_name(entry.source_bag.name)}:{entry.source_slot}' if entry.source_bag is not None and entry.source_slot is not None else '-'
                    note_text = 'Fallback placement' if entry.used_fallback else ('Already in place' if entry.item is not None and entry.source_bag == entry.bag and entry.source_slot == entry.slot else '')

                    PyImGui.table_next_row()
                    PyImGui.table_next_column()
                    ImGui.text(self._humanize_name(entry.bag.name))
                    PyImGui.table_next_column()
                    ImGui.text(str(entry.slot))
                    PyImGui.table_next_column()
                    ImGui.text(item_name or '(unnamed item)', render_markdown=True)
                    PyImGui.table_next_column()
                    ImGui.text(source_text)
                    PyImGui.table_next_column()
                    ImGui.text(entry.group_name)
                    PyImGui.table_next_column()
                    ImGui.text_wrapped(entry.group_summary)
                    PyImGui.table_next_column()
                    ImGui.text(note_text if note_text else '-')
                    PyImGui.table_next_column()
                    ImGui.text(entry.sorter.display_name)
                style.TableRowBg.pop_color_direct()
                style.TableRowBgAlt.pop_color_direct()
            ImGui.end_table()

    def draw_buy_config(self, config_info: ConfigInfo[BuyConfig]) -> None:
        from Sources.frenkeyLib.DataCollector.collectors.items_collector import ITEMS
        changed = False
        entries = config_info.config.get_entries()

        ImGui.text_wrapped("Configure how many common consumables should be kept in stock.")
        ImGui.separator()

        for index, entry in enumerate(entries):
            item_data = None
            if entry.model_id is not None and entry.item_type is not None:
                model_id_value = int(entry.model_id.value) if isinstance(entry.model_id, ModelID) else int(entry.model_id)
                item_data = ITEMS.get_item_data(item_type=entry.item_type, model_id=model_id_value)

            unique_id = f"buy_config_{entry.key}_{index}"
            if ImGui.begin_child(f"##{unique_id}", (0, 64), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                PyImGui.columns(2, "##buy_config_columns", False)
                if item_data is not None:
                    self._draw_item_texture(item_data, (40, 40))
                else:
                    ImGui.dummy(40, 40)

                PyImGui.same_line(0, 10)
                PyImGui.begin_group()
                ImGui.text(entry.label)
                x, y = PyImGui.get_cursor_pos()
                PyImGui.set_cursor_pos((x, y - 4))
                helper_text = entry.description or "Target quantity to keep in inventory."
                ImGui.text_colored(helper_text, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                PyImGui.end_group()

                PyImGui.next_column()
                PyImGui.set_next_item_width(-1)
                quantity = ImGui.slider_int(f"##Quantity{unique_id}", v=entry.quantity, v_min=0, v_max=500 if entry.model_id == ModelID.Lockpick else 50)
                if quantity != entry.quantity:
                    setattr(config_info.config, entry.key, max(0, int(quantity)))
                    changed = True
                PyImGui.end_columns()
            ImGui.end_child()

        if changed:
            config_info.save()

    def draw_crafting_config(self, config_info: ConfigInfo[CraftingConfig]):
        config = config_info.config
        selected_recipes = self._get_selected_crafting_recipes(config)
        selected_recipe_keys = {recipe_key for recipe_key, _ in selected_recipes}
        available_recipe_entries = [
            (recipe_key, recipe)
            for recipe_key, recipe in self._get_all_crafting_recipe_entries()
            if recipe_key not in selected_recipe_keys
        ]

        ImGui.text_wrapped("Select the items which should be craft to consume excess materials and balance crafting output.")
        ImGui.separator()

        toggle_value = ImGui.checkbox("Allow Shopping", config.allow_shopping)
        if toggle_value != config.allow_shopping:
            config.allow_shopping = toggle_value
            config_info.save()

        ImGui.show_tooltip("When enabled, the planner may suggest missing ingredients so all selected recipes can reach the same target amount.")

        selected_add_label = "Add Recipe"
        if self.crafting_recipe_add_key:
            selected_recipe = self._get_crafting_recipe_by_key(self.crafting_recipe_add_key)
            if selected_recipe is not None:
                selected_add_label = selected_recipe.name

        if PyImGui.begin_combo("##crafting_add_recipe", selected_add_label, PyImGui.ImGuiComboFlags.NoFlag):
            for recipe_key, recipe in available_recipe_entries:
                is_selected = self.crafting_recipe_add_key == recipe_key
                if ImGui.selectable(recipe.name, is_selected):
                    self.crafting_recipe_add_key = recipe_key
            ImGui.end_combo()

        PyImGui.same_line(0, 8)
        add_disabled = self.crafting_recipe_add_key == "" or self.crafting_recipe_add_key in selected_recipe_keys
        PyImGui.begin_disabled(add_disabled)
        if ImGui.button("Add Selected Recipe", 150):
            config.selected_recipe_keys.append(self.crafting_recipe_add_key)
            config_info.save()
            self.crafting_recipe_add_key = ""
            selected_recipes = self._get_selected_crafting_recipes(config)
        PyImGui.end_disabled()

        PyImGui.same_line(0, 8)
        clear_disabled = len(config.selected_recipe_keys) <= 0
        PyImGui.begin_disabled(clear_disabled)
        if ImGui.button("Clear Recipes", 110):
            config.selected_recipe_keys = []
            config_info.save()
            selected_recipes = []
        PyImGui.end_disabled()

        if not selected_recipes:
            ImGui.text_wrapped("No recipes selected yet. Add one or more recipes to calculate a balanced crafting plan.")
            return

        if ImGui.begin_child("##crafting_selected_recipes", (0, 120), border=True):
            removed_recipe = False
            for index, (recipe_key, recipe) in enumerate(selected_recipes):
                unique_id = f"crafting_recipe_{recipe_key}_{index}"
                if ImGui.begin_child(f"##{unique_id}", (0, 48), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                    ImGui.text(recipe.name)
                    PyImGui.same_line(0, 10)
                    ImGui.text_colored(
                        self._get_item_label(recipe.result.model_id, recipe.result.item_type, fallback=recipe.name),
                        UI.SUBTLE_TEXT_COLOR.color_tuple,
                        font_size=12,
                    )
                    PyImGui.same_line(PyImGui.get_content_region_avail()[0] - 75, 0)
                    if ImGui.button(f"Remove##{unique_id}", 70):
                        config.selected_recipe_keys = [key for key in config.selected_recipe_keys if key != recipe_key]
                        config_info.save()
                        selected_recipes = self._get_selected_crafting_recipes(config)
                        removed_recipe = True
                ImGui.end_child()
                if removed_recipe:
                    break
        ImGui.end_child()

    def draw_rule_config(self, config_info: ConfigInfo[RuleConfig]):
        active_drag = self._drag_rule_source_config is config_info and self._drag_rule is not None
        self._drag_rule_target_rect = None
        style = ImGui.get_style()
        self._draw_rule_delete_popup()
        
        if ImGui.begin_table("##config_table", 2, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable):
            PyImGui.table_setup_column("Navigation", PyImGui.TableColumnFlags.WidthFixed, 200)
            PyImGui.table_setup_column("Content", PyImGui.TableColumnFlags.WidthStretch)

            PyImGui.table_next_row()
            PyImGui.table_next_column()

            PyImGui.set_next_item_width(-1)
            if ImGui.begin_combo("##add_rule", "Add Rule", PyImGui.ImGuiComboFlags.HeightLargest):
                visible_rule_types = [
                    rule_type
                    for rule_type in self._get_rule_types()
                    if config_info.config.IsAllowedRuleType(rule_type)
                ]
                if visible_rule_types:
                    ImGui.text_colored('Rules', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                    ImGui.separator()
                    for rule_type in visible_rule_types:
                        if ImGui.selectable(UI._humanize_name(rule_type.__name__), False):
                            new_rule = rule_type()
                            config_info.config.AddRule(new_rule)
                            config_info.save()
                            self._set_active_rule(new_rule)
                        self.show_rule_type_tooltip(rule_type)

                rule_presets = get_rule_presets()
                if rule_presets:
                    if visible_rule_types:
                        PyImGui.spacing()
                    ImGui.text_colored('Custom Rule Presets', UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                    ImGui.separator()
                    for rule_preset in rule_presets:
                        if ImGui.selectable(rule_preset.label, False):
                            new_rule = create_rule_from_preset(rule_preset.preset_id)
                            if new_rule is not None:
                                config_info.config.AddRule(new_rule)
                                config_info.save()
                                self._set_active_rule(new_rule)
                        self.show_rule_preset_tooltip(rule_preset)
                ImGui.end_combo()

            ImGui.separator()
            PyImGui.spacing()

            item_height = 50
            item_height = 40
            self.rules_hovered = False
            scroll_y = 0.0           
            selected_rule = self.rule if self.rule in config_info.config else None
                    
            if ImGui.begin_child("##rules", (0, 0), border=False):                
                io = PyImGui.get_io()
                child_pos = PyImGui.get_window_pos()
                child_size = PyImGui.get_window_size()
                child_visible_left = child_pos[0]
                child_visible_top = child_pos[1]
                child_visible_right = child_pos[0] + child_size[0]
                child_visible_bottom = child_pos[1] + child_size[1]
                rule_rects: dict[int, tuple[float, float, float, float]] = {}
                rule_gap_values: list[float] = []
        
                style.ButtonActive.push_color_direct((0,0,0,0))
                style.Button.push_color_direct((0,0,0,0))
                style.ButtonHovered.push_color_direct((0,0,0,0))
                for i, rule in enumerate(config_info.config):
                    if PyImGui.is_rect_visible((5, item_height)):
                        cx,cy = PyImGui.get_cursor_pos()
                        
                        PyImGui.button(f"##rule_{i}", -1, item_height)                        
                        PyImGui.set_next_item_allow_overlap()
                        PyImGui.set_cursor_pos((cx, cy))
                        
                        selected_rule = self.draw_rule_card(item_height, selected_rule, i, rule)

                        hovered = PyImGui.is_item_hovered()
                        self.rules_hovered = self.rules_hovered or hovered
                        
                        if hovered and PyImGui.is_mouse_clicked(1):
                            self.context_menu_id = f"{rule.__class__.__name__} #{i}"
                            self.context_menu_rule = rule
                            self.context_menu_config = config_info
                            PyImGui.open_popup(self.context_menu_id)
                            
                        item_min, item_max, item_size = ImGui.get_item_rect()
                        hovered = PyImGui.is_item_hovered()
                        clicked = PyImGui.is_item_clicked(0)
                        in_rect = ImGui.is_mouse_in_rect((item_min[0], item_min[1], item_size[0], item_size[1]))
                        item_key = ('rule', id(rule))
                        self._remember_drag_clicked_item(item_key, clicked)
                        
                        if self._drag_condition is None and self._drag_rule is None and self._can_start_drag_from_item(item_key, hovered):
                            self._begin_rule_drag(config_info, rule, i)
                            
                        if self._drag_rule_source_config is config_info and self._drag_rule is not None:
                            rule_rects[i] = (item_min[0], item_min[1], item_max[0], item_max[1])

                            if i > 0 and (i - 1) in rule_rects:
                                previous_rect = rule_rects[i - 1]
                                gap = item_min[1] - previous_rect[3]
                                if gap > 0.0:
                                    rule_gap_values.append(gap)
                            
                            if in_rect:
                                self._drag_rule_target_index = i
                                self._drag_rule_target_after = io.mouse_pos_y >= ((item_min[1] + item_max[1]) / 2.0)
                        else:
                            if not isinstance(rule, CustomRule):
                                self.show_rule_type_tooltip(rule.__class__)
                            else:
                                self.show_custom_rule_tooltip(rule)
                    
                    else:
                        PyImGui.dummy((0, item_height))

                style.ButtonActive.pop_color_direct()
                style.Button.pop_color_direct()
                style.ButtonHovered.pop_color_direct()
                
                if len(config_info.config) > 0:
                    PyImGui.dummy((0, 10))
                    if self._drag_rule_source_config is config_info and self._drag_rule is not None and PyImGui.is_item_hovered():
                        self._drag_rule_target_index = len(config_info.config) - 1
                        self._drag_rule_target_after = True

                if active_drag:
                    edge_threshold = 18.0
                    scroll_y = PyImGui.get_scroll_y()
                    scroll_max_y = PyImGui.get_scroll_max_y()
                    mouse_y = io.mouse_pos_y

                    if mouse_y < child_visible_top and scroll_y > 0.0:
                        overshoot = min(child_visible_top - mouse_y, 40.0)
                        scroll_step = 6.0 + (overshoot / 40.0) * 18.0
                        PyImGui.set_scroll_y(max(0.0, scroll_y - scroll_step))
                    elif mouse_y > child_visible_bottom and scroll_y < scroll_max_y:
                        overshoot = min(mouse_y - child_visible_bottom, 40.0)
                        scroll_step = 6.0 + (overshoot / 40.0) * 18.0
                        PyImGui.set_scroll_y(min(scroll_max_y, scroll_y + scroll_step))

                    if rule_rects:
                        if mouse_y <= child_visible_top + edge_threshold:
                            self._drag_rule_target_index = min(rule_rects.keys())
                            self._drag_rule_target_after = False
                        elif mouse_y >= child_visible_bottom - edge_threshold:
                            self._drag_rule_target_index = max(rule_rects.keys())
                            self._drag_rule_target_after = True

                if active_drag and self._drag_rule_target_index in rule_rects:
                    current_rect = rule_rects[self._drag_rule_target_index]
                    usual_gap = rule_gap_values[0] if rule_gap_values else 10.0
                    x1 = max(current_rect[0] + 4, child_visible_left + 4)
                    x2 = min(current_rect[2] - 4, child_visible_right - 4)
                    can_draw_target_rect = True
                    line_y = 0.0

                    if self._drag_rule_target_after:
                        if self._drag_rule_target_index + 1 in rule_rects:
                            next_rect = rule_rects[self._drag_rule_target_index + 1]
                            line_y = (current_rect[3] + next_rect[1]) / 2.0
                        else:
                            if current_rect[3] < child_visible_bottom:
                                bottom_gap = child_visible_bottom - current_rect[3]
                                effective_gap = min(bottom_gap, usual_gap)
                                line_y = current_rect[3] + (effective_gap / 2.0)
                            else:
                                can_draw_target_rect = False
                    else:
                        if self._drag_rule_target_index - 1 in rule_rects:
                            previous_rect = rule_rects[self._drag_rule_target_index - 1]
                            line_y = (previous_rect[3] + current_rect[1]) / 2.0
                        else:
                            if current_rect[1] > child_visible_top:
                                line_y = (child_visible_top + current_rect[1]) / 2.0
                            elif scroll_y <= 0.0:
                                top_gap = max(current_rect[1] - child_visible_top, 0.0)
                                effective_gap = min(top_gap if top_gap > 0.0 else usual_gap, usual_gap)
                                line_y = child_visible_top + max(effective_gap / 2.0, 1.0)
                            else:
                                can_draw_target_rect = False

                    rect_y1 = max(line_y - 1, child_visible_top) if can_draw_target_rect else 0.0
                    rect_y2 = min(line_y + 1, child_visible_bottom) if can_draw_target_rect else 0.0
                    if can_draw_target_rect and x1 < x2 and rect_y1 < rect_y2:
                        self._drag_rule_target_rect = (
                            x1,
                            rect_y1,
                            x2,
                            rect_y2,
                        )
                    else:
                        self._drag_rule_target_rect = None

                if self.context_menu_id and self.context_menu_rule and self.context_menu_config:
                    if not self.draw_context_menu(self.context_menu_id, self.context_menu_config, self.context_menu_rule):
                        self.context_menu_id = None
                        self.context_menu_rule = None
                        self.context_menu_config = None
            ImGui.end_child()
            
            c_min, c_max, c_size = ImGui.get_item_rect()
            if active_drag and not ImGui.is_mouse_in_rect((c_min[0], c_min[1], c_size[0], c_size[1])):
                self._drag_rule_target_rect = None
                
            PyImGui.table_next_column()

            if ImGui.begin_child("##rule content", (0, 0), border=False):
                if selected_rule:
                    self.draw_rule(selected_rule)
                
            ImGui.end_child()
            
            ImGui.end_table()
        
        if active_drag:
            if not PyImGui.is_mouse_down(0):
                self._apply_rule_drag(config_info)

    def draw_rule_card(self, item_height, selected_rule, i, rule):
        if ImGui.begin_selectable(f"##rule_{i}", selected=selected_rule is rule, size=(0, item_height), child_flags=PyImGui.WindowFlags.NoInputs|PyImGui.WindowFlags.NoBringToFrontOnFocus|PyImGui.WindowFlags.NoScrollWithMouse|PyImGui.WindowFlags.NoScrollbar, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
            
            self._draw_item_action_texture(rule.action, (item_height - 4, item_height - 4))
            PyImGui.same_line(0, 5)
            
            PyImGui.begin_group()
            PyImGui.begin_disabled(not rule.enabled)
            ImGui.text(rule.name or f"{rule.__class__.__name__} #{i}")
            PyImGui.set_cursor_pos_y(PyImGui.get_cursor_pos_y() - 5)
            PyImGui.separator()
            x, y = PyImGui.get_cursor_pos()
            PyImGui.set_cursor_pos((x, y - 2))
            # ImGui.text(f"{UI._humanize_name(rule.action.name)}" + (" (Disabled)" if not rule.enabled else ""), font_size=13)
            ImGui.text_colored(f"{UI._humanize_name(rule.action.name)}" + (" (Disabled)" if not rule.enabled else ""), UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=13)
            
            # PyImGui.set_cursor_pos(x, PyImGui.get_cursor_pos_y() - 5)
            # ImGui.text_colored(f"{rule.__class__.__name__}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=11)

            PyImGui.end_disabled()
            PyImGui.end_group()
                            
        if ImGui.end_selectable():
            self._set_active_rule(rule)
            selected_rule = rule
        return selected_rule
    
    def _set_inventory_preview_bags(self, bags: list[Bags]) -> None:
        self.inventory_preview_selected_bags = list(bags)
        self._invalidate_inventory_preview_cache()

    @staticmethod
    def _get_first_matching_rule(config: RuleConfig, item_id: int) -> BaseRule | None:
        if item_id in config.blacklisted_items:
            return None

        for rule in config:
            if rule.applies(item_id):
                return rule

        return None

    @staticmethod
    def _is_valid_loot_agent(agent_id: int) -> bool:
        if not Agent.IsValid(agent_id):
            return False

        player_agent_id = Player.GetAgentID()
        owner_id = Agent.GetItemAgentOwnerID(agent_id)
        return owner_id in (0, player_agent_id)

    @staticmethod
    def _get_buy_entry_inventory_quantity(entry: BuyConfigEntry) -> int:
        inventory_snapshot = ItemSnapshot.get_bags_snapshot([Bags.Backpack, Bags.BeltPouch, Bags.Bag1, Bags.Bag2, Bags.EquipmentPack])
        total_quantity = 0

        for bag_items in inventory_snapshot.values():
            for item in bag_items.values():
                if item is None or not item.is_valid or not item.is_inventory_item:
                    continue

                if entry.model_id is not None:
                    model_id_value = int(entry.model_id.value) if isinstance(entry.model_id, ModelID) else int(entry.model_id)
                    if item.model_id != model_id_value:
                        continue
                elif entry.item_type is not None and item.item_type != entry.item_type:
                    continue

                if entry.key == "keys" and item.model_id == int(ModelID.Lockpick.value):
                    continue

                total_quantity += item.quantity if item.is_stackable else 1

        return total_quantity

    def draw_inventory_config_preview(self, config: InventoryConfig) -> None:
        try:
            ImGui.text("Preview", font_size=18)
            ImGui.text_wrapped("Preview how the current Item Processing config would classify items in the selected bags. This does not execute any actions. InventoryBT itself still only processes live inventory bags.")

            if self.preview_entries is None or self.preview_throttle.IsExpired():
                self.preview_entries = InventoryBT.Preview(config, bags=self.inventory_preview_selected_bags)
                self.preview_throttle.Reset()

            preview_entries = self.preview_entries or []
                
            action_counts: dict[ItemAction, int] = {}
            visible_entries : list[InventoryPreviewEntry] = []
        
            button_width = 110
            if ImGui.button("Inventory", button_width):
                self._set_inventory_preview_bags(INVENTORY_BAGS)
            PyImGui.same_line(0, 5)
            if ImGui.button("Storage", button_width):
                self._set_inventory_preview_bags(STORAGE_BAGS)
            PyImGui.same_line(0, 5)
            if ImGui.button("All", button_width):
                self._set_inventory_preview_bags(list(self.INVENTORY_PREVIEW_BAGS))
            PyImGui.same_line(0, 5)
            if ImGui.button("Clear", button_width):
                self._set_inventory_preview_bags([])
            PyImGui.same_line(0, 5)
            manual_tick_clicked = ImGui.button("Manual Tick", button_width)
            manual_tick_active = PyImGui.is_item_active()
            if manual_tick_clicked:
                self._tick_inventory_bt_once(config)
            elif manual_tick_active and PyImGui.is_mouse_down(0):
                if self._manual_inventory_tick_repeat_timer.IsStopped():
                    self._manual_inventory_tick_repeat_timer.Reset()
                elif self._manual_inventory_tick_repeat_timer.IsExpired():
                    self._tick_inventory_bt_once(config)
            elif not PyImGui.is_mouse_down(0):
                self._manual_inventory_tick_repeat_timer.Stop()
            ImGui.show_tooltip("Click to advance InventoryBT by one tick. Hold to keep ticking about every 125 ms.")
            PyImGui.same_line(0, 5)
            if ImGui.button("Reset BT", button_width):
                self._reset_manual_inventory_bt()
                self._invalidate_inventory_preview_cache()
            manual_tick_status = self._manual_inventory_tick_status
            if manual_tick_status:
                ImGui.text_colored(manual_tick_status, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

            self.inventory_preview_search = ImGui.input_text("Search##inventory_preview_search", self.inventory_preview_search)
            self.inventory_preview_show_no_action = ImGui.checkbox("Show No Action", self.inventory_preview_show_no_action)
            self.inventory_preview_show_hold = ImGui.checkbox("Show Hold", self.inventory_preview_show_hold)
            inventory_preview_search_query = self._normalize_search_query(self.inventory_preview_search)

            if ImGui.begin_child("##inventory_preview_bags", (0, 90), border=True):
                width = PyImGui.get_content_region_avail()[0]
                columns = max(1, int(width // 170))
                PyImGui.columns(columns, "inventory_preview_bag_columns", False)

                for bag in self.INVENTORY_PREVIEW_BAGS:
                    is_selected = bag in self.inventory_preview_selected_bags
                    selected = ImGui.checkbox(f"{self._humanize_name(bag.name)}", is_selected)
                    if selected != is_selected:
                        if selected:
                            self.inventory_preview_selected_bags.append(bag)
                        else:
                            self.inventory_preview_selected_bags = [selected_bag for selected_bag in self.inventory_preview_selected_bags if selected_bag != bag]
                        self._invalidate_inventory_preview_cache()
                    PyImGui.next_column()

                PyImGui.end_columns()
            ImGui.end_child()

            for entry in preview_entries:
                action = entry.action
                if action is None and not self.inventory_preview_show_no_action:
                    continue
                if action == ItemAction.Hold and not self.inventory_preview_show_hold:
                    continue

                search_blob = " ".join(
                    [
                        entry.item.names.plain or entry.item.name or "",
                        entry.rule.name if entry.rule and entry.rule.name else entry.rule.__class__.__name__ if entry.rule else "",
                        entry.note,
                        entry.item.bag.name,
                        action.name if action else "No Action",
                    ]
                )
                if not self._search_text_matches(inventory_preview_search_query, search_blob):
                    continue

                if action is not None:
                    action_counts[action] = action_counts.get(action, 0) + 1

                visible_entries.append(entry)

            summary_text = ", ".join(
                f"{self._humanize_name(action.name)}: {count}"
                for action, count in sorted(action_counts.items(), key=lambda item: item[0].name)
            )
            ImGui.text_wrapped(summary_text if summary_text else "No matching preview entries for the current filters.")

            if not self.inventory_preview_selected_bags:
                ImGui.text_wrapped("Select at least one bag to preview items.")
                return

            if not visible_entries:
                return

            if ImGui.begin_table("##inventory_preview_table", 6, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable | PyImGui.TableFlags.ScrollY | PyImGui.TableFlags.ScrollX):
                PyImGui.table_setup_column("Bag", PyImGui.TableColumnFlags.WidthFixed, 110)
                PyImGui.table_setup_column("Slot", PyImGui.TableColumnFlags.WidthFixed, 45)
                PyImGui.table_setup_column("Item", PyImGui.TableColumnFlags.WidthFixed, 200)
                PyImGui.table_setup_column("Action", PyImGui.TableColumnFlags.WidthFixed, 120)
                PyImGui.table_setup_column("Rule", PyImGui.TableColumnFlags.WidthFixed, 160)
                PyImGui.table_setup_column("Notes", PyImGui.TableColumnFlags.WidthStretch)
                PyImGui.table_headers_row()

                for entry in visible_entries:
                    rule_name = entry.rule.name if entry.rule and entry.rule.name else entry.rule.__class__.__name__ if entry.rule else "-"
                    action_name = self._humanize_name(entry.action.name) if entry.action is not None else "No Action"
                    item_name = entry.item.complete_name or entry.item.singular_name or entry.item.name or f"Item {entry.item.id}"

                    PyImGui.table_next_row()
                    PyImGui.table_next_column()
                    ImGui.text(self._humanize_name(entry.item.bag.name))
                    PyImGui.table_next_column()
                    ImGui.text(str(entry.item.slot))
                    PyImGui.table_next_column()
                    ImGui.text(item_name, render_markdown=True)
                    if PyImGui.is_item_hovered():
                        self._draw_item_snapshot_tooltip(entry.item)
                    PyImGui.table_next_column()
                    ImGui.text(action_name)
                    PyImGui.table_next_column()
                    ImGui.text(rule_name)
                    PyImGui.table_next_column()
                    ImGui.text(entry.note if entry.note else ("Ready" if entry.executable else "-"))

                ImGui.end_table()
        except Exception as e:
            ImGui.text_wrapped(f"Error generating inventory preview: {str(e)}")

    def draw_loot_config_preview(self, config: LootConfig) -> None:
        ImGui.text("Preview", font_size=18)
        ImGui.text_wrapped("Preview how the current loot config would classify nearby ground items. This does not pick up anything.")

        self.loot_preview_search = ImGui.input_text("Search##loot_preview_search", self.loot_preview_search)
        self.loot_preview_show_no_action = ImGui.checkbox("Show No Action", self.loot_preview_show_no_action)
        self.loot_preview_distance = ImGui.slider_int(
            "Distance##loot_preview_distance",
            self.loot_preview_distance,
            0,
            int(Range.SafeCompass.value),
        )
        loot_preview_search_query = self._normalize_search_query(self.loot_preview_search)

        if not Player.GetAgentID():
            ImGui.text_wrapped("Loot preview is only available while the player is in-game.")
            return

        item_array = AgentArray.GetItemArray() or []
        item_array = AgentArray.Filter.ByDistance(item_array, Player.GetXY(), self.loot_preview_distance)
        item_array = AgentArray.Sort.ByDistance(item_array, Player.GetXY())

        visible_entries: list[tuple[ItemSnapshot, BaseRule | None, ItemAction | None, str, float]] = []
        action_counts: dict[str, int] = {}
        player_pos = Player.GetXY()

        for agent_id in item_array:
            if not self._is_valid_loot_agent(agent_id):
                continue

            item_agent = Agent.GetItemAgentByID(agent_id)
            if item_agent is None:
                continue

            item = ItemSnapshot.from_item_id(item_agent.item_id)
            if item is None or not item.is_valid:
                continue

            rule = self._get_first_matching_rule(config, item.id)
            action = rule.action if rule is not None else None
            note = ""

            if action in (ItemAction.NONE, ItemAction.Hold):
                note = "No loot action will be executed."
            elif action is None:
                note = "No matching rule."

            item_name = item.names.plain or item.name or f"Item {item.id}"
            distance = Utils.Distance(player_pos, Agent.GetXY(agent_id))
            action_name = self._humanize_name(action.name) if action is not None else "No Action"
            rule_name = rule.name if rule and rule.name else rule.__class__.__name__ if rule else ""
            search_blob = " ".join([item_name, action_name, rule_name, note])

            if not self.loot_preview_show_no_action and action is None:
                continue

            if not self._search_text_matches(loot_preview_search_query, search_blob):
                continue

            if action is not None:
                action_counts[action_name] = action_counts.get(action_name, 0) + 1

            visible_entries.append((item, rule, action, note, distance))

        summary_text = ", ".join(f"{action}: {count}" for action, count in sorted(action_counts.items()))
        ImGui.text_wrapped(summary_text if summary_text else "No matching preview entries for the current filters.")

        if not visible_entries:
            ImGui.text_wrapped("No nearby loot entries matched the current preview filters.")
            return

        if ImGui.begin_table("##loot_preview_table", 5, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable | PyImGui.TableFlags.ScrollY | PyImGui.TableFlags.ScrollX):
            PyImGui.table_setup_column("Distance", PyImGui.TableColumnFlags.WidthFixed, 70)
            PyImGui.table_setup_column("Item", PyImGui.TableColumnFlags.WidthFixed, 200)
            PyImGui.table_setup_column("Action", PyImGui.TableColumnFlags.WidthFixed, 120)
            PyImGui.table_setup_column("Rule", PyImGui.TableColumnFlags.WidthFixed, 180)
            PyImGui.table_setup_column("Notes", PyImGui.TableColumnFlags.WidthStretch)
            PyImGui.table_headers_row()

            for item, rule, action, note, distance in visible_entries:
                item_name = item.names.plain or item.name or f"Item {item.id}"
                action_name = self._humanize_name(action.name) if action is not None else "No Action"
                rule_name = rule.name if rule and rule.name else rule.__class__.__name__ if rule else "-"

                PyImGui.table_next_row()
                PyImGui.table_next_column()
                ImGui.text(str(distance))
                PyImGui.table_next_column()
                ImGui.text(item_name)
                if PyImGui.is_item_hovered():
                    self._draw_item_snapshot_tooltip(item)
                PyImGui.table_next_column()
                ImGui.text(action_name)
                PyImGui.table_next_column()
                ImGui.text(rule_name)
                PyImGui.table_next_column()
                ImGui.text(note if note else "Ready")

            ImGui.end_table()
    
    def draw_buy_config_preview(self, config: BuyConfig) -> None:
        ImGui.text("Preview", font_size=18)
        ImGui.text_wrapped("Preview the current inventory stock against your configured target amounts. This does not buy anything.")

        self.buy_preview_search = ImGui.input_text("Search##buy_preview_search", self.buy_preview_search)
        self.buy_preview_show_satisfied = ImGui.checkbox("Show Satisfied", self.buy_preview_show_satisfied)
        buy_preview_search_query = self._normalize_search_query(self.buy_preview_search)

        entries = config.get_entries()
        if not entries:
            ImGui.text("No buy rules configured.")
            return

        visible_entries: list[tuple[BuyConfigEntry, int, int]] = []

        for entry in entries:
            current_quantity = self._get_buy_entry_inventory_quantity(entry)
            missing_quantity = max(0, entry.quantity - current_quantity)
            search_blob = " ".join([entry.label, entry.description, str(entry.quantity), str(current_quantity), str(missing_quantity)])

            if not self.buy_preview_show_satisfied and missing_quantity <= 0:
                continue

            if not self._search_text_matches(buy_preview_search_query, search_blob):
                continue

            visible_entries.append((entry, current_quantity, missing_quantity))

        configured_total = sum(1 for entry in entries if entry.quantity > 0)
        pending_total = sum(1 for _, _, missing_quantity in visible_entries if missing_quantity > 0)
        ImGui.text_wrapped(f"Configured entries: {configured_total}, still below target: {pending_total}")

        if not visible_entries:
            ImGui.text_wrapped("No buy entries matched the current preview filters.")
            return

        if ImGui.begin_table("##buy_preview_table", 5, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable | PyImGui.TableFlags.ScrollY | PyImGui.TableFlags.ScrollX):
            PyImGui.table_setup_column("Item", PyImGui.TableColumnFlags.WidthFixed, 200)
            PyImGui.table_setup_column("Target", PyImGui.TableColumnFlags.WidthFixed, 70)
            PyImGui.table_setup_column("Current", PyImGui.TableColumnFlags.WidthFixed, 70)
            PyImGui.table_setup_column("Missing", PyImGui.TableColumnFlags.WidthFixed, 70)
            PyImGui.table_setup_column("Notes", PyImGui.TableColumnFlags.WidthStretch)
            PyImGui.table_headers_row()

            for entry, current_quantity, missing_quantity in visible_entries:
                note = "Ready" if missing_quantity <= 0 else f"Needs {missing_quantity} more."

                PyImGui.table_next_row()
                PyImGui.table_next_column()
                ImGui.text(entry.label)
                PyImGui.table_next_column()
                ImGui.text(str(entry.quantity))
                PyImGui.table_next_column()
                ImGui.text(str(current_quantity))
                PyImGui.table_next_column()
                ImGui.text(str(missing_quantity))
                PyImGui.table_next_column()
                ImGui.text(note if entry.description == "" else f"{note} {entry.description}")

            ImGui.end_table()

    # -------------------------------------------------------------------------
    # Rule rendering / dispatch
    # -------------------------------------------------------------------------
    def _draw_rule_header(self, rule: BaseRule) -> None:
            
        ImGui.text_aligned("Name", alignment=Alignment.MidLeft, height=25)
        PyImGui.same_line(60, 5)

        PyImGui.set_next_item_width(-1)
        rule_name_input_id = f"##rule_name_{id(rule)}"
        name = ImGui.input_text(rule_name_input_id, rule.name or "")
        if name != rule.name:
            rule.name = name
            self._save_active_config()

        ImGui.text_aligned("Enabled" if rule.enabled else "Disabled", alignment=Alignment.MidLeft, height=25, color=UI.GREEN_COLOR.color_tuple if rule.enabled else UI.RED_COLOR.color_tuple)
        PyImGui.same_line(60, 5)
        enabled = PyImGui.checkbox("##rule_enabled", rule.enabled)
        if enabled != rule.enabled:
            rule.enabled = enabled
            self._save_active_config()
        ImGui.show_tooltip("Whether this rule is active. Disabled rules are ignored but keep their settings.")

        PyImGui.same_line(0, 5)
        width = PyImGui.get_content_region_avail()[0]
        PyImGui.set_next_item_width(width - 155)

        style = ImGui.get_style()
        unset = rule.action == ItemAction.NONE
        if unset:
            style.FrameBg.push_color_direct((229, 62, 48, 200))
            style.FrameBgHovered.push_color_direct((231, 95, 81, 200))

        open = PyImGui.begin_combo(f"##rule_action_{id(rule)}", UI._humanize_name(rule.action.name)  if rule.action != ItemAction.NONE else "Select an action", PyImGui.ImGuiComboFlags.NoFlag)

        if unset:
            style.FrameBg.pop_color_direct()
            style.FrameBgHovered.pop_color_direct()

        if open:
            sorted_actions = sorted(ItemAction, key=lambda action: action.name)
            for action in sorted_actions:
                if ImGui.selectable(UI._humanize_name(action.name), selected=rule.action == action):
                    rule.action = action
                    self._save_active_config()
            ImGui.end_combo()
        ImGui.show_tooltip("The action to perform on items that match this rule.")

        PyImGui.same_line(0, 5)
        PyImGui.set_next_item_width(150)
        if PyImGui.begin_combo(
            f"##rule_result_interpretation_{id(rule)}",
            self._humanize_name(rule.result_interpretation.name),
            PyImGui.ImGuiComboFlags.NoFlag,
        ):
            interpretations = {
                ResultInterpretation.Match: "Handle items that match the specified conditions.",
                ResultInterpretation.NoMatch: "Handle items that do not match the specified conditions.",
            }

            for interpretation, description in interpretations.items():
                if ImGui.selectable(interpretation.name, selected=rule.result_interpretation == interpretation):
                    rule.result_interpretation = interpretation
                    self._save_active_config()
                ImGui.show_tooltip(description)

            ImGui.end_combo()
        ImGui.show_tooltip("Controls whether the rule handles matching items or non-matching items.")


        ImGui.separator()
        PyImGui.spacing()

    def _begin_no_header_table(self, id: str, column_count: int, flags : Optional[int] = None, size: tuple[float, float] = (0, 0)) -> bool:
        flags = flags if flags is not None else PyImGui.TableFlags.ScrollY | PyImGui.TableFlags.NoSavedSettings | PyImGui.TableFlags.NoPadOuterX
        style = ImGui.get_style()
        style.CellPadding.push_style_var_direct(4, 4)
        open = ImGui.begin_table(id, column_count, flags, size[0], size[1])
        
        if open:
            PyImGui.table_next_row()
            PyImGui.table_next_column()
            
            return True
        
        style.CellPadding.pop_style_var_direct()
        return False
    
    def _end_no_header_table(self) -> None:        
        style = ImGui.get_style()
        style.CellPadding.pop_style_var_direct()
        ImGui.end_table()
    
    class ConditionEditor:
        NO_HEADER_TABLE_CELL_PADDING_Y = 4
        NO_HEADER_TABLE_CELL_PADDING_X = 4
                
        @staticmethod
        def GetSizes(rule : BaseRule, condition : BaseCondition, size: Optional[tuple[float, float]] = None) -> dict[str, int]:
            sizes = {}
            style = ImGui.get_style()
            
            is_custom_rule = isinstance(rule, CustomRule)
            single_condition = len(rule.conditions) == 1
            show_condition_wrapper = not single_condition or is_custom_rule
            
            header_height = 24
            spacing_x = style.ItemSpacing.value1 or 0
            spacing_y = style.ItemSpacing.value2 or 0
            
            window_padding_y = style.WindowPadding.value2 or 0
            button_padding_y = style.ButtonPadding.get_current().value2 or 0
            
            sizes["spacing"] = spacing_y
            
            avail = PyImGui.get_content_region_avail()
            avail_width = avail[0] if size is None else size[0]
            avail_height = avail[1] if size is None else size[1]
            
            max_height = UI.CUSTOM_RULE_CONTENT_RECT[1] if isinstance(rule, CustomRule) else avail[1]
            
            is_last_condition = rule.conditions and condition == rule.conditions[-1]
    
            sizes["element_height"] = 0
            sizes["element_width"] = 0
            items_amount = 0
            base_height = 0
            content_height = -1
                        
            match condition:                
                case ModelIdsCondition():
                    base_height = math.ceil(PyImGui.get_text_line_height() + (button_padding_y * 2))
                    sizes["element_height"] = 48
                    sizes["element_width"] = 250
                    items_amount = len(condition.model_ids)
                    
                case ItemTypesCondition():
                    sizes["element_height"] = 32
                    sizes["element_width"] = 180
                    items_amount = len(UI.ITEM_TYPE_REPRESENTATIVE_MODELFILE_IDS.keys())
        
                case ModelFileIdsCondition():
                    base_height = math.ceil(PyImGui.get_text_line_height() + (button_padding_y * 2))
                    sizes["element_height"] = 48
                    sizes["element_width"] = 250
                    items_amount = len(condition.model_file_ids)

                case EncodedNamesCondition():
                    base_height = math.ceil(PyImGui.get_text_line_height() + (button_padding_y * 2))
                    sizes["element_height"] = 56
                    sizes["element_width"] = 250
                    items_amount = len(condition.encoded_names)

                case ModelFileIdsAndItemTypesCondition():
                    base_height = math.ceil(PyImGui.get_text_line_height() + (button_padding_y * 2))
                    sizes["element_height"] = 56
                    sizes["element_width"] = 250
                    items_amount = len(condition.model_file_ids_and_item_types)

                case ModelIdsAndItemTypesCondition():
                    base_height = math.ceil(PyImGui.get_text_line_height() + (button_padding_y * 2))
                    sizes["element_height"] = 50
                    sizes["element_width"] = 250
                    items_amount = len(condition.modelids_and_itemtypes)

                case RaritiesCondition():
                    sizes["element_height"] = 25
                    sizes["element_width"] = 150
                    items_amount = len(Rarity)

                case DyeColorsCondition():
                    sizes["element_height"] = 32
                    sizes["element_width"] = 200
                    items_amount = len(DyeColor) - 1

                case SalvagesToMaterialsCondition():
                    base_height = math.ceil(PyImGui.get_text_line_height() + (button_padding_y * 2))
                    sizes["element_height"] = 48
                    sizes["element_width"] = 250
                    items_amount = len(condition.materials)

                case ExactItemTypeCondition()| InscribableCondition()| StackQuantityCondition()| UnidentifiedCondition() | IsCustomizedCondition():
                    content_height = 20

                case BowTypeCondition():
                    content_height = (20 + spacing_y) * 6 + 10
                    
                case QuantityMatchCondition():
                    content_height = 102

                case NickItemCondition():
                    base_height = 25
                    sizes["element_height"] = 24
                    sizes["element_width"] = avail_width
                    items_amount = condition.weeks_before_next_cycle + 1

                case IsMaterialCondition():
                    content_height = 40 + spacing_y

                case InherentFiltersCondition():
                    content_height = math.ceil(140 + max(1, len(condition.inherents)) * 90)

                case WeaponRequirementCondition():
                    base_height = math.ceil(PyImGui.get_text_line_height() + (button_padding_y * 2))
                    sizes["element_height"] = 58
                    sizes["element_width"] = avail_width
                    items_amount = len(condition.requirements)

                case HalvesCastAndRechargeAttributeCondition():
                    content_height = 30

                case ArmorUpgradesCondition():
                    content_height = 0

                case MaxWeaponUpgradesCondition():
                    content_height = 0

                case UpgradeRangesCondition():
                    content_height = 0

                case _:
                    content_height = 180
                    
            sizes["title_height"] = (window_padding_y + (header_height + spacing_y)) if show_condition_wrapper else 0
            sizes["wrapper_height"] = (sizes["title_height"] + (base_height + spacing_y) + spacing_y)
            sizes["width"] = avail_width
            
            if content_height >= 0:
                sizes["content_height"] = max(0, content_height)
                
            else:         
                sizes["columns"] = min(max(1, int(avail_width // (sizes["element_width"] + UI.ConditionEditor.NO_HEADER_TABLE_CELL_PADDING_X))), max(items_amount, 1))
                sizes["rows"] = (items_amount + sizes["columns"] - 1) // sizes["columns"]
                table_row_height = sizes["element_height"] + (UI.ConditionEditor.NO_HEADER_TABLE_CELL_PADDING_Y * 2)
                table_height = math.ceil(sizes["rows"] * table_row_height)
                
                sizes["content_height"] = min(table_height, max_height - sizes["wrapper_height"])
                
            if size is None:                      
                height = sizes["wrapper_height"] + sizes["content_height"]
                sizes["height"] = max(height, avail_height) if is_last_condition else height            
            
            else:
                sizes["content_height"] = 0
                sizes["width"] = size[0]
                sizes["height"] = size[1]
            
            return sizes
        
        @staticmethod
        def BeginConditionContainer(ui : "UI", rule : BaseRule, condition : BaseCondition, size: Optional[tuple[float, float]] = None) -> bool:
            is_custom_rule = isinstance(rule, CustomRule)
            active_condition_drag = ui._drag_condition_source_rule is rule and ui._drag_condition is not None
            single_condition = len(rule.conditions) == 1
            show_condition_wrapper = not single_condition or is_custom_rule
            size = size if size is not None else (0, 0)
            title = ui._humanize_name(type(condition).__name__).replace("Condition", "")
            
            unique_condition_id = id(condition)
            
            delete_popup_id = f"Delete Condition##{unique_condition_id}"
            context_popup_id = f"##condition_context_{unique_condition_id}"
            request_delete_popup = False
            child_flags = PyImGui.WindowFlags.NoBringToFrontOnFocus
            if active_condition_drag:
                child_flags |= PyImGui.WindowFlags.NoInputs
            
            
            is_open = ImGui.begin_child(f"##condition_container{unique_condition_id}", size, border=show_condition_wrapper, flags=child_flags)
            if is_open:
                description = inspect.getdoc(type(condition)) or ""
                description = re.sub(r":class:`([^`]+)`", r"\1", description).replace("**", "").strip()
                style = ImGui.get_style()
                y = PyImGui.get_cursor_pos_y()
                width = PyImGui.get_content_region_avail()[0]
                
                if show_condition_wrapper:
                    est_text_width = PyImGui.calc_text_size(title)[0] * 1.15
                    PyImGui.begin_group()
                    ImGui.text_colored(title, color=UI.CREME_COLOR.color_tuple, font_size=16)
                    PyImGui.same_line(0, 0)
                    ImGui.dummy(width - est_text_width - 12, 0)
                    PyImGui.end_group()
                    
                    ui._condition_drag_handle_state[unique_condition_id] = (PyImGui.is_item_hovered(), PyImGui.is_item_clicked(0))
                    if description:
                        if PyImGui.is_item_hovered():
                            if PyImGui.begin_tooltip():
                                ImGui.text(description)
                                ImGui.separator()
                                ImGui.text_colored("Drag to reorder or right-click for more options", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                            PyImGui.end_tooltip()
                    
                    if is_custom_rule:      
                        PyImGui.set_cursor_pos_y(y - 4)
                        PyImGui.set_cursor_pos_x(width - 3)
                                    
                        style.FramePadding.push_style_var_direct(4, 1)
                        clicked = PyImGui.button(f"x##{unique_condition_id}", 16, 16)                
                        style.FramePadding.pop_style_var_direct()
                        
                        if clicked:
                            PyImGui.open_popup(delete_popup_id)
                        
                    ImGui.separator()
                else:
                    ui._condition_drag_handle_state[unique_condition_id] = (False, False)

                PyImGui.set_next_window_size((360, 0), PyImGui.ImGuiCond.Always)
                if PyImGui.begin_popup_modal(delete_popup_id, True, PyImGui.WindowFlags.AlwaysAutoResize):
                    ImGui.text_wrapped(f'Are you sure you want to delete the "{title}" condition?')

                    btn_width = (PyImGui.get_window_content_region_max()[0] - 8) / 2
                    if ImGui.button('Delete', btn_width) or ui._is_confirm_key_pressed():
                        if condition in rule.conditions:
                            rule.conditions.remove(condition)
                            ui._save_active_config()
                        PyImGui.close_current_popup()
                        PyImGui.end_popup_modal()
                        return False

                    PyImGui.same_line(0, 8)
                    if ImGui.button('Cancel', btn_width) or ui._is_cancel_key_pressed():
                        PyImGui.close_current_popup()

                    PyImGui.end_popup_modal()

                if ui._condition_drag_handle_state[unique_condition_id][0] and PyImGui.is_mouse_clicked(1):
                    PyImGui.open_popup(context_popup_id)

                if PyImGui.begin_popup(context_popup_id):
                    ImGui.text_colored(title, color=UI.CREME_COLOR.color_tuple, font_size=16)
                    ImGui.separator()

                    if ImGui.menu_item('Copy Condition'):
                        ui._copy_condition_to_clipboard(condition)
                        PyImGui.close_current_popup()

                    if ui._can_paste_condition_over(rule, condition):
                        paste_label = f'Paste Condition: {ui._condition_clipboard_label}' if ui._condition_clipboard_label else 'Paste Condition'
                        if ImGui.menu_item(paste_label):
                            if ui._paste_condition_over(rule, condition):
                                ui._save_active_config()
                                PyImGui.close_current_popup()

                    if is_custom_rule:
                        try:
                            condition_index = rule.conditions.index(condition)
                        except ValueError:
                            condition_index = -1
                        
                        conditions_amount = len(rule.conditions)
                        
                        ImGui.separator()
                        
                        if conditions_amount > 1:
                            if condition_index > 0 and ImGui.menu_item('Move Up'):
                                rule.conditions[condition_index - 1], rule.conditions[condition_index] = rule.conditions[condition_index], rule.conditions[condition_index - 1]
                                ui._save_active_config()
                                PyImGui.close_current_popup()

                            if 0 <= condition_index < len(rule.conditions) - 1 and ImGui.menu_item('Move Down'):
                                rule.conditions[condition_index], rule.conditions[condition_index + 1] = rule.conditions[condition_index + 1], rule.conditions[condition_index]
                                ui._save_active_config()
                                PyImGui.close_current_popup()

                            if condition_index >= 0:
                                ImGui.separator()

                        if ImGui.menu_item('Delete Condition'):
                            request_delete_popup = True

                    ImGui.end_popup()

                if request_delete_popup:
                    PyImGui.close_current_popup()
                    PyImGui.open_popup(delete_popup_id)
                    
                return True
            
            return False
        
        @staticmethod
        def EndConditionContainer() -> None:
            ImGui.end_child()
            
        @staticmethod
        def DrawCard(id : str, title: str, description: str, texture: Optional[str] = None, show_delete: bool = True, height: float = 0, on_delete: Optional[Callable] = None) -> bool:
            clicked = False
            
            if ImGui.begin_child(f"##{id}", (0, height), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                avail = PyImGui.get_content_region_avail()
                if height <= 0:
                    height = avail[1]
                                    
                if texture is not None:
                    UI._draw_texture_or_dummy(texture, (height - 20, height - 20))

                PyImGui.same_line(0, 8)
                PyImGui.begin_group()
                ImGui.text(title)
                x, y = PyImGui.get_cursor_pos()
                PyImGui.set_cursor_pos((x, y - 4))
                ImGui.text_colored(description, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                PyImGui.end_group()
                
                if show_delete:
                    delete_btn_size = (16, 16)
                    PyImGui.set_cursor_pos((avail[0], 4))
                    
                    PyImGui.push_style_var_vec2(ImGuiStyleVar.FramePadding, (4, 1))
                    if PyImGui.button(f"x##{id}", *delete_btn_size):
                        if on_delete:
                            on_delete()
                            clicked = True
                            
                    PyImGui.pop_style_var(1)
                        
            ImGui.end_child()
            
            return clicked
        
        @staticmethod
        def ForModelIdsCondition(ui : "UI", rule : BaseRule, condition: ModelIdsCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            popup_id = "##model_ids_rule_add_popup"
            search_state_key = f"model_ids_condition_{id(condition)}"
            selected_model_ids = {
                int(model_id.value) if isinstance(model_id, ModelID) else int(model_id)
                for model_id in condition.model_ids
            }
            
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            element_height = sizes.get("element_height", 0)
            columns = sizes.get("columns", 1)
            condition_id = f"model_ids_condition_{id(condition)}"
            
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Model ID", -1):
                    PyImGui.open_popup(popup_id)

                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(condition.model_ids) - 1
                    
                    for index, model_id in enumerate(condition.model_ids[:]):
                        model_id_value = int(model_id.value) if isinstance(model_id, ModelID) else int(model_id)
                        label = ui._humanize_name(model_id.name) if isinstance(model_id, ModelID) else f"Manual ID {model_id_value}"
                        unique_id = f"model_ids_rule_{id(condition)}_{model_id_value}_{index}"

                        if UI.ConditionEditor.DrawCard(unique_id, 
                                                    label, 
                                                    f"Model ID: {model_id_value}", 
                                                    height=element_height, 
                                                    on_delete=lambda index=index: condition.model_ids.pop(index)):
                            changed = True
                        
                        if index != last_index:
                            PyImGui.table_next_column()
                        
                            
                        
                    ui._end_no_header_table()
                
                PyImGui.set_next_window_size((300, 0), cond=PyImGui.ImGuiCond.Appearing)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Model ID")

                    PyImGui.set_next_item_width(-1)
                    ui._focus_popup_search_field_on_appearing()
                    current_search = ui._get_search_field_value(search_state_key)
                    _, current_search = ImGui.search_field("##model_id_enum_search", current_search, "Search model ids or enter an integer...")
                    ui._set_search_field_value(search_state_key, current_search)
                    search_query, matching_model_ids_raw = ui._get_live_search_results(
                        search_state_key,
                        current_search,
                        lambda normalized_query: cast(list[Any], ui._filter_cached_entries(ui._model_id_search_cache, normalized_query, ui._model_id_search_entries)),
                    )
                    matching_model_ids = cast(list[ModelID], matching_model_ids_raw)
                    available_model_ids = [
                        model_id
                        for model_id in matching_model_ids
                        if int(model_id.value) not in selected_model_ids
                    ]

                    manual_value: int | None = None
                    if search_query:
                        try:
                            manual_value = int(search_query)
                        except ValueError:
                            manual_value = None

                    exact_enum_match = manual_value in ui._sorted_model_id_values if manual_value is not None else False

                    if manual_value is not None and not exact_enum_match and manual_value not in selected_model_ids:
                        if ImGui.begin_selectable(f"##manual_model_id_{manual_value}", False, (0, 34), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                            ImGui.text(f"Manual Model ID: {manual_value}")

                        if ImGui.end_selectable():
                            condition.model_ids.append(manual_value)
                            changed = True
                            PyImGui.close_current_popup()

                        if PyImGui.is_item_hovered():
                            ImGui.show_tooltip("Add this raw integer model id even if it is not part of the ModelID enum yet.")

                    if ImGui.begin_child("##model_id_enum_candidates", (0, 320), border=True):
                        for model_id in available_model_ids:
                            model_id_value = int(model_id.value)
                            if ImGui.begin_selectable(f"##model_id_enum_{model_id.name}", False, (0, 34), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                ImGui.text(ui._humanize_name(model_id.name))
                                x, y = PyImGui.get_cursor_pos()
                                PyImGui.set_cursor_pos((x, y - 4))
                                ImGui.text_colored(f"{model_id_value}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                            if ImGui.end_selectable():
                                condition.model_ids.append(model_id)
                                changed = True
                                PyImGui.close_current_popup()

                            if PyImGui.is_item_hovered():
                                tooltip = f"{ui._humanize_name(model_id.name)}\nModel ID: {model_id_value}"
                                ImGui.show_tooltip(tooltip)
                    ImGui.end_child()

                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()

                    PyImGui.end_popup()
                    
            UI.ConditionEditor.EndConditionContainer()

            return changed
        
        @staticmethod
        def ForItemTypesCondition(ui : "UI", rule : BaseRule, condition: ItemTypesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            condition_id = f"item_types_condition_{id(condition)}"
            
            spacing = sizes.get("spacing", 0)
            element_height = sizes.get("element_height", 32)            
            
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(UI.ITEM_TYPE_REPRESENTATIVE_MODELFILE_IDS) - 1
                    
                    for index, (item_type, model_file_id) in enumerate(UI.ITEM_TYPE_REPRESENTATIVE_MODELFILE_IDS.items()):
                        is_selected = item_type in condition.item_types
                        
                        if ImGui.begin_selectable(f"##item_type_{item_type.name}", is_selected, (0, element_height), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                            ui._draw_texture_from_model_file_id(model_file_id, (element_height - spacing, element_height - spacing))
                            PyImGui.same_line(0, 5)
                            ImGui.text_aligned(ui._item_type_name(item_type), alignment=Alignment.MidLeft, height=element_height - spacing)
                        
                        if ImGui.end_selectable():
                            if item_type in condition.item_types:
                                condition.item_types.remove(item_type)
                            else:
                                condition.item_types.append(item_type)
                            changed = True
                            
                        ImGui.show_tooltip(ui._item_type_name(item_type))

                        if index != last_index:
                            PyImGui.table_next_column()
                        
                    ui._end_no_header_table()
                
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForModelFileIdsCondition(ui: "UI", rule: BaseRule, condition: ModelFileIdsCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            
            condition_id = f"model_file_ids_condition_{id(condition)}"
            popup_id = f"##model_file_id_condition_add_popup_{id(condition)}"
            search_state_key = f"model_file_ids_condition_{id(condition)}"
            popup_rows_cache_key = f"condition_editor:model_file_id_rows:{id(condition)}"
            selected_model_file_ids = set(condition.model_file_ids)

            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            element_height = sizes.get("element_height", 56)    
            columns = sizes.get("columns", 1)

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Model File ID", -1):
                    PyImGui.open_popup(popup_id)
                    
                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(condition.model_file_ids) - 1
                    
                    for index, model_file_id in enumerate(condition.model_file_ids):
                        item = ui._find_item_by_model_file_id(model_file_id)
                        unique_id = f"model_file_id_condition_{id(condition)}_{model_file_id}_{index}"

                        if UI.ConditionEditor.DrawCard(unique_id,
                                                    ui._get_item_display_name(item) if item is not None else f"Unknown Item ({model_file_id})",
                                                    f"Model File ID: {model_file_id}",
                                                    height=element_height,
                                                    texture=UI._get_item_data_texture(item) if item is not None else None,
                                                    on_delete=lambda index=index: condition.model_file_ids.pop(index)):
                            changed = True
                                            
                        if index != last_index:
                            PyImGui.table_next_column()
                            
                    ui._end_no_header_table()


                PyImGui.set_next_window_size((450, 0), cond=PyImGui.ImGuiCond.Appearing)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Model File ID")
                    ImGui.separator()

                    PyImGui.set_next_item_width(-1)
                    ui._focus_popup_search_field_on_appearing()
                    current_search = ui._get_search_field_value(search_state_key)
                    _, current_search = ImGui.search_field(f"##model_file_id_search_{id(condition)}", current_search, "Search by item name or enter a model file id...")
                    ui._set_search_field_value(search_state_key, current_search)
                    search_query, matching_items_raw = ui._get_live_search_results(
                        search_state_key,
                        current_search,
                        lambda normalized_query: cast(list[Any], ui._filter_cached_entries(ui._model_file_id_search_cache, normalized_query, ui._model_file_id_search_entries)),
                    )
                    matching_items = cast(list[ItemData], matching_items_raw)
                    candidate_rows = ui._get_recalculated_value(
                        popup_rows_cache_key,
                        (current_search, ui._build_int_signature(selected_model_file_ids)),
                        lambda: ui._build_model_file_id_candidate_rows(matching_items, selected_model_file_ids),
                    )

                    manual_value: int | None = None
                    if search_query:
                        try:
                            manual_value = int(search_query)
                        except ValueError:
                            manual_value = None

                    if manual_value is not None and manual_value not in selected_model_file_ids:
                        if ImGui.begin_selectable(f"##manual_model_file_id_{id(condition)}_{manual_value}", False, (0, 36), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                            ImGui.text(f"Manual Model File ID: {manual_value}")

                        if ImGui.end_selectable():
                            condition.model_file_ids.append(manual_value)
                            changed = True
                            PyImGui.close_current_popup()

                    if ImGui.begin_child(f"##model_file_id_candidates_{id(condition)}", (0, 320), border=True):
                        for item, model_file_id, item_name in candidate_rows:

                            if PyImGui.is_rect_visible((10, 36)):
                                if ImGui.begin_selectable(f"##model_file_id_{id(condition)}_{item.item_type.name}_{item.model_id}", False, (0, 36), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                    ui._draw_item_texture(item)
                                    PyImGui.same_line(0, 8)
                                    PyImGui.begin_group()
                                    ImGui.text(item_name)
                                    x, y = PyImGui.get_cursor_pos()
                                    PyImGui.set_cursor_pos((x, y - 4))
                                    ImGui.text_colored(f"Model File ID: {model_file_id}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                    PyImGui.end_group()

                                if ImGui.end_selectable():
                                    condition.model_file_ids.append(model_file_id)
                                    changed = True
                                    PyImGui.close_current_popup()

                                if PyImGui.is_item_hovered():
                                    tooltip = f"{item_name}\nModel File ID: {model_file_id}"
                                    ImGui.show_tooltip(tooltip)
                            else:
                                ImGui.dummy(0, 36)
                    ImGui.end_child()

                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()

                    PyImGui.end_popup()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForModelFileIdsAndItemTypesCondition(ui: "UI", rule: BaseRule, condition: ModelFileIdsAndItemTypesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            condition_id = f"model_file_id_item_type_condition_{id(condition)}"
            popup_id = f"##model_file_id_item_type_condition_add_popup_{id(condition)}"
            search_state_key = f"model_file_id_item_types_condition_{id(condition)}"
            popup_rows_cache_key = f"condition_editor:model_file_id_item_type_rows:{id(condition)}"
            selected_entries = {(entry.model_file_id, entry.item_type) for entry in condition.model_file_ids_and_item_types}
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            element_height = sizes.get("element_height", 56)
            
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Model File ID", -1):
                    PyImGui.open_popup(popup_id)

                PyImGui.set_next_window_size((450, 0), cond=PyImGui.ImGuiCond.Appearing)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Item By Model File ID")
                    ImGui.separator()

                    PyImGui.set_next_item_width(-1)
                    ui._focus_popup_search_field_on_appearing()
                    current_search = ui._get_search_field_value(search_state_key)
                    _, current_search = ImGui.search_field(f"##model_file_id_item_type_search_{id(condition)}", current_search, "Search by item name or model file id...")
                    ui._set_search_field_value(search_state_key, current_search)
                    search_query, matching_items_raw = ui._get_live_search_results(
                        search_state_key,
                        current_search,
                        lambda normalized_query: cast(list[Any], ui._filter_cached_entries(ui._model_file_id_search_cache, normalized_query, ui._model_file_id_search_entries)),
                    )
                    matching_items = cast(list[ItemData], matching_items_raw)
                    candidate_rows = ui._get_recalculated_value(
                        popup_rows_cache_key,
                        (
                            current_search,
                            tuple(sorted((model_file_id, item_type.name) for model_file_id, item_type in selected_entries)),
                        ),
                        lambda: ui._build_model_file_id_item_type_candidate_rows(matching_items, selected_entries),
                    )

                    if ImGui.begin_child(f"##model_file_id_item_type_candidates_{id(condition)}", (0, 320), border=True):
                        for item, key, item_name in candidate_rows:
                            if PyImGui.is_rect_visible((10, 36)):
                                if ImGui.begin_selectable(f"##model_file_id_item_type_{id(condition)}_{item.item_type.name}_{item.model_id}", False, (0, 36), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                    ui._draw_item_texture(item)
                                    PyImGui.same_line(0, 8)
                                    PyImGui.begin_group()
                                    ImGui.text(item_name)
                                    x, y = PyImGui.get_cursor_pos()
                                    PyImGui.set_cursor_pos((x, y - 4))
                                    ImGui.text_colored(
                                        f"{ui._item_type_name(item.item_type)} | Model File ID: {item.model_file_id}",
                                        UI.SUBTLE_TEXT_COLOR.color_tuple,
                                        font_size=12,
                                    )
                                    PyImGui.end_group()

                                if ImGui.end_selectable():
                                    condition.model_file_ids_and_item_types.append(
                                        ModelFileIdAndItemType(
                                            model_file_id=key[0],
                                            item_type=key[1],
                                        )
                                    )
                                    changed = True
                                    PyImGui.close_current_popup()

                                if PyImGui.is_item_hovered():
                                    tooltip = f"{item_name}\n{ui._item_type_name(item.item_type)}\nModel File ID: {item.model_file_id}"
                                    ImGui.show_tooltip(tooltip)
                            else:
                                ImGui.dummy(0, 36)
                                
                    ImGui.end_child()

                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()

                    PyImGui.end_popup()

                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(condition.model_file_ids_and_item_types) - 1
                    for index, entry in enumerate(list(condition.model_file_ids_and_item_types)):
                        item = ui._find_item_by_model_file_id_and_item_type(entry.model_file_id, entry.item_type)
                        unique_id = f"model_file_id_item_type_condition_{id(condition)}_{entry.model_file_id}_{entry.item_type.name}_{index}"

                        if UI.ConditionEditor.DrawCard(unique_id,
                                                    ui._get_item_display_name(item) if item is not None else f"Unknown Item ({entry.model_file_id})",
                                f"{ui._item_type_name(entry.item_type)} | Model File ID: {entry.model_file_id}",
                                                    height=element_height,
                                                    texture=UI._get_item_data_texture(item),
                                                    on_delete=lambda index=index: condition.model_file_ids_and_item_types.pop(index)):
                            changed = True

                        if index != last_index:
                            PyImGui.table_next_column()
                    ui._end_no_header_table()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForModelIdsAndItemTypesCondition(ui: "UI", rule: BaseRule, condition: ModelIdsAndItemTypesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            condition_id = f"model_id_item_type_condition_{id(condition)}"
            popup_id = f"##model_id_item_type_condition_add_popup_{id(condition)}"
            search_state_key = f"model_id_item_types_condition_{id(condition)}"
            popup_rows_cache_key = f"condition_editor:model_id_item_type_rows:{id(condition)}"
            selected_entries = {
                (
                    int(entry.model_id.value) if isinstance(entry.model_id, ModelID) else int(entry.model_id),
                    entry.item_type,
                )
                for entry in condition.modelids_and_itemtypes
            }
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            element_height = sizes.get("element_height", 50)
            
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Model ID", -1):
                    PyImGui.open_popup(popup_id)

                PyImGui.set_next_window_size((400, 0), cond=PyImGui.ImGuiCond.Appearing)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Item By Model ID")
                    ImGui.separator()

                    PyImGui.set_next_item_width(-1)
                    ui._focus_popup_search_field_on_appearing()
                    current_search = ui._get_search_field_value(search_state_key)
                    search_changed, current_search = ImGui.search_field(f"##model_id_search_{id(condition)}", current_search, "Search by name or model id...")
                    ui._set_search_field_value(search_state_key, current_search)
                    search_query, matching_items_raw = ui._get_live_search_results(
                        search_state_key,
                        current_search,
                        lambda normalized_query: cast(list[Any], ui._filter_cached_entries(ui._model_id_item_search_cache, normalized_query, ui._model_id_item_search_entries)),
                    )
                    matching_items = cast(list[ItemData], matching_items_raw)
                    candidate_rows = ui._get_recalculated_value(
                        popup_rows_cache_key,
                        (
                            current_search,
                            tuple(sorted((model_id, item_type.name) for model_id, item_type in selected_entries)),
                        ),
                        lambda: ui._build_model_id_item_type_candidate_rows(matching_items, selected_entries),
                    )

                    if ImGui.begin_child(f"##model_id_candidates_{id(condition)}", (0, 320), border=True):
                        if search_changed:
                            PyImGui.set_scroll_y(0)

                        for item, entry_key, item_name in candidate_rows:
                            model_id_value, item_type = entry_key

                            if PyImGui.is_rect_visible((10, 36)):
                                if ImGui.begin_selectable(f"##model_id_candidate_{id(condition)}_{item_type.name}_{model_id_value}", False, (0, 36), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                    UI._draw_item_texture(item, (32, 32))
                                    PyImGui.same_line(0, 8)
                                    PyImGui.begin_group()
                                    x, _ = PyImGui.get_cursor_pos()
                                    ImGui.text(item_name)
                                    if len(item.attributes) == 1:
                                        PyImGui.same_line(0, 8)
                                        ImGui.text_colored(f"[{ui._humanize_name(item.attributes[0].name)}]", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                                    _, y = PyImGui.get_cursor_pos()
                                    PyImGui.set_cursor_pos((x, y - 4))
                                    ImGui.text_colored(
                                        f"{ui._item_type_name(item_type)} | Model ID: {model_id_value}",
                                        UI.SUBTLE_TEXT_COLOR.color_tuple,
                                        font_size=12,
                                    )
                                    PyImGui.end_group()

                                if ImGui.end_selectable():
                                    try:
                                        condition.modelids_and_itemtypes.append(ModelIdAndItemType(ModelID(model_id_value), item_type))
                                    except ValueError:
                                        condition.modelids_and_itemtypes.append(ModelIdAndItemType(model_id_value, item_type))
                                    changed = True
                                    PyImGui.close_current_popup()

                                if PyImGui.is_item_hovered():
                                    if PyImGui.begin_tooltip():
                                        ImGui.text(item_name)
                                        if len(item.attributes) == 1:
                                            PyImGui.same_line(0, 8)
                                            ImGui.text_colored(f"[{ui._humanize_name(item.attributes[0].name)}]", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                        ImGui.separator()
                                        ImGui.text_colored(f"Model ID: {model_id_value}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                        ImGui.text_colored(f"Item Type: {ui._item_type_name(item_type)}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                    PyImGui.end_tooltip()
                            else:
                                ImGui.dummy(0, 36)
                    ImGui.end_child()

                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()

                    PyImGui.end_popup()

                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    selected_items: list[tuple[ModelIdAndItemType, Any]] = []
                    for model_id, item_type in condition.modelids_and_itemtypes:
                        modelid_item_type = int(model_id.value) if isinstance(model_id, ModelID) else int(model_id)
                        item_data = ui._find_item_by_model_id(modelid_item_type, item_type)
                        selected_items.append((ModelIdAndItemType(model_id, item_type), item_data))

                    last_index = len(selected_items) - 1
                    for index, (modelid_item_type, item_data) in enumerate(selected_items):
                        unique_id = f"model_id_condition_{id(condition)}_{modelid_item_type}_{index}"
                        item_name = item_data.name if item_data is not None else f"Unknown Item ({modelid_item_type})"

                        if UI.ConditionEditor.DrawCard(unique_id,
                                                    item_name,
                                f"{ui._item_type_name(modelid_item_type.item_type)} | Model ID: {modelid_item_type.model_id}" + (f" | {item_data.attributes[0].name}" if item_data is not None and len(item_data.attributes) == 1 else ""),
                                                    height=element_height,
                                                    texture=UI._get_item_data_texture(item_data),
                                                    on_delete=lambda index=index: condition.modelids_and_itemtypes.pop(index)):
                            changed = True
                        
                        if index != last_index:
                            PyImGui.table_next_column()
                    ui._end_no_header_table()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForEncodedNamesCondition(ui: "UI", rule: BaseRule, condition: EncodedNamesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            condition_id = f"encoded_names_condition_{id(condition)}"
            popup_id = f"##encoded_name_condition_add_popup_{id(condition)}"
            search_state_key = f"encoded_names_condition_{id(condition)}"
            popup_rows_cache_key = f"condition_editor:encoded_name_rows:{id(condition)}"
            selected_encoded_names = set(condition.encoded_names)
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            element_height = sizes.get("element_height", 56)
                        
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Encoded Name", -1):
                    PyImGui.open_popup(popup_id)

                PyImGui.set_next_window_size((500, 0), cond=PyImGui.ImGuiCond.Appearing)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Encoded Name")
                    ImGui.separator()

                    PyImGui.set_next_item_width(-1)
                    ui._focus_popup_search_field_on_appearing()
                    current_search = ui._get_search_field_value(search_state_key)
                    _, current_search = ImGui.search_field(f"##encoded_name_search_{id(condition)}", current_search, "Search by item name or paste an encoded name...")
                    ui._set_search_field_value(search_state_key, current_search)
                    search_query, matching_items_raw = ui._get_live_search_results(
                        search_state_key,
                        current_search,
                        lambda normalized_query: cast(list[Any], ui._filter_cached_entries(ui._encoded_name_search_cache, normalized_query, ui._encoded_name_search_entries)),
                    )
                    matching_items = cast(list[ItemData], matching_items_raw)
                    candidate_rows = ui._get_recalculated_value(
                        popup_rows_cache_key,
                        (current_search, ui._build_bytes_signature(selected_encoded_names)),
                        lambda: ui._build_encoded_name_candidate_rows(matching_items, selected_encoded_names),
                    )

                    if current_search.strip() and current_search.strip() not in selected_encoded_names:
                        manual_encoded_name = current_search.strip()

                        if PyImGui.is_rect_visible((10, 40)):
                            if ImGui.begin_selectable(f"##manual_encoded_name_{id(condition)}", False, (0, 40), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                ImGui.text("Use typed encoded name")
                                x, y = PyImGui.get_cursor_pos()
                                PyImGui.set_cursor_pos((x, y - 4))
                                ImGui.text_colored(manual_encoded_name, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                            if ImGui.end_selectable():
                                condition.encoded_names.append(ui._convert_str_to_encoded_bytes(manual_encoded_name))
                                changed = True
                                PyImGui.close_current_popup()
                        else:
                            ImGui.dummy(0, 40)

                    if ImGui.begin_child(f"##encoded_name_candidates_{id(condition)}", (0, 320), border=True):
                        for item, encoded_name, item_name in candidate_rows:

                            if PyImGui.is_rect_visible((10, 40)):
                                if ImGui.begin_selectable(f"##encoded_name_{id(condition)}_{item.item_type.name}_{item.model_id}", False, (0, 40), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                    ui._draw_item_texture(item)
                                    PyImGui.same_line(0, 8)
                                    PyImGui.begin_group()
                                    ImGui.text(item_name)
                                    x, y = PyImGui.get_cursor_pos()
                                    PyImGui.set_cursor_pos((x, y - 4))
                                    ImGui.text_colored(item_name, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                    PyImGui.end_group()

                                if ImGui.end_selectable():
                                    condition.encoded_names.append(encoded_name)
                                    changed = True
                                    PyImGui.close_current_popup()

                                if PyImGui.is_item_hovered():
                                    tooltip = f"{item_name}\n{ui._item_type_name(item.item_type)}\nModel ID: {item.model_id}"
                                    ImGui.show_tooltip(tooltip)
                            else:
                                ImGui.dummy(0, 40)
                    ImGui.end_child()

                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()

                    PyImGui.end_popup()

                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(condition.encoded_names) - 1
                    for index, encoded_name in enumerate(condition.encoded_names):
                        item = ui._find_item_by_encoded_name(encoded_name)
                        unique_id = f"encoded_name_condition_{id(condition)}_{index}"

                        if UI.ConditionEditor.DrawCard(unique_id,
                                                    ui._get_item_display_name(item) if item is not None else "Custom Encoded Name",
                                                    string_table.decode(encoded_name),
                                                    height=element_height,
                                                    texture=UI._get_item_data_texture(item),
                                                    on_delete=lambda index=index: condition.encoded_names.pop(index)):
                            changed = True
                        
                        if index != last_index:
                            PyImGui.table_next_column()
                    ui._end_no_header_table()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForExactItemTypeCondition(ui: "UI", rule: BaseRule, condition: ExactItemTypeCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                selected_label = ui._item_type_name(condition.item_type) if condition.item_type is not None else "Select an item type"
                PyImGui.set_next_item_width(-1)
                if PyImGui.begin_combo(f"##exact_item_type_{id(condition)}", selected_label, PyImGui.ImGuiComboFlags.NoFlag):
                    for item_type in ui._sorted_item_types:
                        if ImGui.selectable(ui._item_type_name(item_type), selected=condition.item_type == item_type):
                            condition.item_type = item_type
                            changed = True
                    ImGui.end_combo()
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForBowTypeCondition(ui: "UI", rule: BaseRule, condition: BowTypeCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            bow_types = list(BowType)

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                for index, bow_type in enumerate(bow_types):
                    is_selected = bow_type in condition.bow_types
                    selected = ImGui.checkbox(f"{ui._bow_type_name(bow_type)}##bow_type_{id(condition)}_{bow_type.name}", is_selected)
                    if selected != is_selected:
                        if selected:
                            condition.bow_types.append(bow_type)
                        else:
                            condition.bow_types.remove(bow_type)
                        changed = True

                    # if index < len(bow_types) - 1:
                    #     PyImGui.same_line(0, 12)

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForStackQuantityCondition(ui: "UI", rule: BaseRule, condition: StackQuantityCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                available_width = PyImGui.get_content_region_avail()[0]
                slider_width = max(80, (available_width - 8) / 2)

                PyImGui.push_item_width(slider_width)
                new_min = ImGui.slider_int(f"##stack_quantity_min_{id(condition)}", condition.min_quantity, 0, 250)
                ImGui.show_tooltip("Minimum stack quantity required for the rule to apply")
                
                PyImGui.same_line(0, 8)
                new_max = ImGui.slider_int(f"##stack_quantity_max_{id(condition)}", condition.max_quantity, 0, 250)
                ImGui.show_tooltip("Maximum stack quantity allowed for the rule to apply")
                PyImGui.pop_item_width()

                if new_min > new_max:
                    new_min, new_max = new_max, new_min

                if new_min != condition.min_quantity or new_max != condition.max_quantity:
                    condition.min_quantity = new_min
                    condition.max_quantity = new_max
                    changed = True

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForNickItemCondition(ui: "UI", rule: BaseRule, condition: NickItemCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            preview_items = ui._get_nick_item_preview_items(condition.weeks_before_next_cycle)
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            last_index = len(preview_items) - 1

            style = ImGui.get_style()

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                PyImGui.set_next_item_width(-1)
                new_weeks = ImGui.slider_int(
                    f"##nick_item_weeks_{id(condition)}",
                    condition.weeks_before_next_cycle,
                    0,
                    NICK_CYCLE_COUNT,
                )
                ImGui.show_tooltip("Match Nicholas the Traveler items that return within this many weeks.")

                if new_weeks != condition.weeks_before_next_cycle:
                    condition.weeks_before_next_cycle = new_weeks
                    preview_items = ui._get_nick_item_preview_items(condition.weeks_before_next_cycle)
                    changed = True
                style = ImGui.get_style()
                style.CellPadding.push_style_var_direct(4, 4)
                if not preview_items:
                    ImGui.text_wrapped("No Nicholas the Traveler items match the current week threshold.")
                elif ImGui.begin_table(
                    f"##nick_item_preview_{id(condition)}",
                    3,
                    PyImGui.TableFlags.ScrollY | PyImGui.TableFlags.BordersOuterV | PyImGui.TableFlags.BordersOuterH,
                    height=sizes.get("content_height", 0)
                ):
                    PyImGui.table_setup_column("Icon", PyImGui.TableColumnFlags.WidthFixed, 34)
                    PyImGui.table_setup_column("Name")
                    PyImGui.table_setup_column("Next Cycle", PyImGui.TableColumnFlags.WidthFixed, 90)
                    PyImGui.table_next_row()
                    PyImGui.table_next_column()

                    for index, item in enumerate(preview_items):
                        weeks_until_next_nick = item.weeks_until_next_nick
                        if weeks_until_next_nick is None:
                            continue

                        ui._draw_item_texture(item, size=(24, 24))
                        hovered = PyImGui.is_item_hovered()
                        PyImGui.table_next_column()
                        
                        ImGui.text_aligned(ui._get_item_display_name(item), alignment=Alignment.MidLeft, height=24)
                        hovered = PyImGui.is_item_hovered() or hovered
                        PyImGui.table_next_column()
                        
                        ImGui.text_aligned(
                            ui._format_nick_weeks_label(weeks_until_next_nick),
                            alignment=Alignment.MidLeft,
                            color=ui._get_nick_weeks_color(weeks_until_next_nick),
                            height=24
                        )
                        hovered = PyImGui.is_item_hovered() or hovered

                        if hovered:
                            PyImGui.set_next_window_size(420, 0)
                            ImGui.begin_tooltip()
                            ui._draw_item_texture(item, size=(40, 40))
                            PyImGui.same_line(0, 8)
                            PyImGui.begin_group()
                            ImGui.text(ui._get_item_display_name(item))
                            ImGui.text_colored(
                                f"Nick cycle: {ui._format_nick_weeks_label(weeks_until_next_nick)}",
                                ui._get_nick_weeks_color(weeks_until_next_nick),
                                font_size=12,
                            )
                            if item.next_nick_week is not None:
                                ImGui.text_colored(f"Next week starts: {item.next_nick_week.isoformat()}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                            PyImGui.end_group()
                            if item.acquisition:
                                ImGui.separator()
                                ImGui.text_wrapped(item.acquisition)
                            ImGui.end_tooltip()

                        if index != last_index:
                            PyImGui.table_next_column()
                    
                    ImGui.end_table()
                    
                style.CellPadding.pop_style_var_direct()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForIsMaterialCondition(ui: "UI", rule: BaseRule, condition: IsMaterialCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                rare_materials = ImGui.checkbox("Include rare materials", condition.rare_materials)
                ImGui.show_tooltip("Enable this to match rare materials.")

                if rare_materials != condition.rare_materials:
                    condition.rare_materials = rare_materials
                    changed = True
                    
                common_materials = ImGui.checkbox("Include common materials", condition.common_materials)
                if common_materials != condition.common_materials:
                    condition.common_materials = common_materials
                    changed = True
                ImGui.show_tooltip("Enable this to match common materials.")

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForQuantityMatchCondition(ui: "UI", rule: BaseRule, condition: QuantityMatchCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            count_modes = list(QuantityMatchCountMode)
            count_scopes = list(QuantityMatchCountScope)
            match_targets = list(QuantityMatchTarget)
            count_mode_labels = {
                QuantityMatchCountMode.TotalQuantity: "Total quantity",
                QuantityMatchCountMode.FullStacks: "Full stacks",
            }
            count_scope_labels = {
                QuantityMatchCountScope.InventoryOnly: "In Inventory",
                QuantityMatchCountScope.InventoryAndStorage: "In Inventory + Xunlai storage",
            }
            match_target_labels = {
                QuantityMatchTarget.Kept: "Match up to {quantity} {unit} of the specified items",
                QuantityMatchTarget.Excess: "Match the excess items beyond {quantity} {unit}",
            }

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                
                ImGui.text_aligned("Threshold", alignment= Alignment.MidLeft, height = 25)
                PyImGui.same_line(0, 5)
                
                avail = PyImGui.get_content_region_avail()
                PyImGui.set_next_item_width(max(50, avail[0] - 150 - 5 - 250 - 5))
                keep_quantity = ImGui.input_int(f"##quantity_match_condition_keep_quantity_{id(condition)}", condition.quantity_limit, step_fast=1)
                if keep_quantity != condition.quantity_limit:
                    condition.quantity_limit = max(0, min(5000, int(keep_quantity)))
                    changed = True
                ImGui.show_tooltip("Keep the same-kind stack combination that reaches at least this threshold using as few stacks as possible.")

                PyImGui.same_line(0, 5)
                PyImGui.set_next_item_width(150)
                count_mode_index = count_modes.index(condition.count_mode)
                next_count_mode_index = ImGui.combo(
                    f"##quantity_match_condition_count_mode_{id(condition)}",
                    count_mode_index,
                    [count_mode_labels[mode] for mode in count_modes],
                )
                if next_count_mode_index != count_mode_index:
                    condition.count_mode = count_modes[next_count_mode_index]
                    changed = True
                ImGui.show_tooltip("Choose whether the threshold counts raw item quantities or only complete 250-stacks.")

                PyImGui.same_line(0, 5)
                PyImGui.set_next_item_width(250)
                count_scope_index = count_scopes.index(condition.count_scope)
                next_count_scope_index = ImGui.combo(
                    f"##quantity_match_condition_count_scope_{id(condition)}",
                    count_scope_index,
                    [count_scope_labels[scope] for scope in count_scopes],
                )
                if next_count_scope_index != count_scope_index:
                    condition.count_scope = count_scopes[next_count_scope_index]
                    changed = True
                ImGui.show_tooltip("Choose whether the quantity check only looks at the current character inventory or also includes Xunlai storage.")

                PyImGui.begin_group()
                selected_match_target = match_targets.index(condition.match_target)
                next_match_target = selected_match_target

                threshold_label = "full stacks" if condition.count_mode == QuantityMatchCountMode.FullStacks else "total quantity"
                for index, match_target in enumerate(match_targets):
                    label = match_target_labels[match_target].format(quantity=condition.quantity_limit, unit=threshold_label)
                    next_match_target = ImGui.radio_button(label, next_match_target, index)

                if next_match_target != selected_match_target:
                    condition.match_target = match_targets[next_match_target]
                    changed = True

                PyImGui.end_group()
                ImGui.show_tooltip("Choose whether this rule should match the retained stacks or the excess stacks beyond the configured threshold.")

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForRaritiesCondition(ui: "UI", rule: BaseRule, condition: RaritiesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            condition_id = f"rarities_condition_{id(condition)}"
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            style = ImGui.get_style()
            
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(Rarity) - 1
                    for index, rarity in enumerate(Rarity):
                        is_selected = rarity in condition.rarities
                        
                        
                        style.Text.push_color_direct(ui._get_rarity_color(rarity).rgb_tuple)
                        selected = ImGui.checkbox(rarity.name, is_selected)
                        style.Text.pop_color_direct()
                        if selected != is_selected:
                            if selected:
                                condition.rarities.append(rarity)
                            else:
                                condition.rarities.remove(rarity)
                            changed = True
                            
                        if index != last_index:
                            PyImGui.table_next_column()
                    ui._end_no_header_table()
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForDyeColorsCondition(ui: "UI", rule: BaseRule, condition: DyeColorsCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            condition_id = f"dye_colors_condition_{id(condition)}"
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            element_height = sizes.get("element_height", 32)
            
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                visible_dye_colors = [dye_color for dye_color in ui._sorted_dye_colors if dye_color != DyeColor.NoColor]
                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(visible_dye_colors) - 1
                    for index, dye_color in enumerate(visible_dye_colors):
                        if dye_color == DyeColor.NoColor:
                            continue

                        is_selected = dye_color in condition.dye_colors
                        if ImGui.begin_selectable(
                            f"##dye_{id(condition)}_{dye_color.name}",
                            is_selected,
                            (0, element_height),
                            selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple,
                            hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple,
                        ):
                            ImGui.image(ui.dye_textures.get(dye_color, ''), (24, 24))
                            PyImGui.same_line(0, 5)
                            ImGui.text_aligned(dye_color.name, height=24, alignment=Alignment.MidLeft)

                        if ImGui.end_selectable():
                            if dye_color in condition.dye_colors:
                                condition.dye_colors.remove(dye_color)
                            else:
                                condition.dye_colors.append(dye_color)
                            changed = True
                        if index != last_index:
                            PyImGui.table_next_column()
                    ui._end_no_header_table()
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForSalvagesToMaterialsCondition(ui: "UI", rule: BaseRule, condition: SalvagesToMaterialsCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            condition_id = f"salvage_materials_condition_{id(condition)}"
            popup_id = f"##salvage_material_condition_add_popup_{id(condition)}"
            search_state_key = f"salvage_materials_condition_{id(condition)}"
            popup_rows_cache_key = f"condition_editor:salvage_material_rows:{id(condition)}"
            selected_materials = set(condition.materials)
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            element_height = sizes.get("element_height", 48)
            
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Material", -1):
                    PyImGui.open_popup(popup_id)

                PyImGui.set_next_window_size((420, 0), cond=PyImGui.ImGuiCond.Appearing)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Salvage Material")
                    ImGui.separator()

                    PyImGui.set_next_item_width(-1)
                    ui._focus_popup_search_field_on_appearing()
                    current_search = ui._get_search_field_value(search_state_key)
                    _, current_search = ImGui.search_field(f"##salvage_material_search_{id(condition)}", current_search, "Search material name or model id...")
                    ui._set_search_field_value(search_state_key, current_search)
                    search_query, matching_materials_raw = ui._get_live_search_results(
                        search_state_key,
                        current_search,
                        lambda normalized_query: cast(list[Any], ui._filter_cached_entries(ui._salvage_material_search_cache, normalized_query, ui._salvage_material_search_entries)),
                    )
                    ImGui.show_tooltip("Search by material name or model id.")
                    matching_materials = cast(list[ItemData], matching_materials_raw)
                    candidate_rows = ui._get_recalculated_value(
                        popup_rows_cache_key,
                        (current_search, ui._build_int_signature(selected_materials)),
                        lambda: ui._build_salvage_material_candidate_rows(matching_materials, selected_materials),
                    )

                    if ImGui.begin_child(f"##salvage_material_candidates_{id(condition)}", (0, 320), border=True):
                        for material, model_id, label in candidate_rows:

                            if ImGui.begin_selectable(f"##salvage_material_{id(condition)}_{material.name}", False, (0, 34), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                UI._draw_item_texture(material, (32, 32))
                                PyImGui.same_line(0, 8)
                                PyImGui.begin_group()
                                ImGui.text(label)
                                x, y = PyImGui.get_cursor_pos()
                                PyImGui.set_cursor_pos((x, y - 4))
                                ImGui.text_colored(f"Model ID: {model_id}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                PyImGui.end_group()

                            if ImGui.end_selectable():
                                condition.materials.append(model_id)
                                changed = True
                                PyImGui.close_current_popup()

                            if PyImGui.is_item_hovered():
                                tooltip = f"{label}\nModel ID: {model_id}"
                                ImGui.show_tooltip(tooltip)
                    ImGui.end_child()

                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()

                    PyImGui.end_popup()

                if ui._begin_no_header_table(condition_id, sizes.get("columns", 1), size=(0, sizes.get("content_height", 0))):
                    last_index = len(condition.materials) - 1
                    for index, mid in enumerate(condition.materials):
                        material = ui._find_item_by_model_id(int(mid))
                        unique_id = f"salvage_material_condition_{id(condition)}_{material.name}_{index}" if material is not None else f"salvage_material_condition_{id(condition)}_{mid}_{index}"
                        
                        if UI.ConditionEditor.DrawCard(unique_id,
                                                    ui._get_item_display_name(material) if material is not None else f"Unknown Material ({mid})",
                                                    f"Model ID: {mid}",
                                                    height=element_height,
                                                    texture=UI._get_item_data_texture(material),
                                                    on_delete=lambda index=index: condition.materials.pop(index)):
                            changed = True
                        
                        if index != last_index:
                            PyImGui.table_next_column()
                    ui._end_no_header_table()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForInherentFiltersCondition(ui: "UI", rule: BaseRule, condition: InherentFiltersCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            unique_id = str(id(condition))
            search_state_key = f"inherent_filters_condition_{unique_id}"
            recalc_cache_key = f"condition_editor:inherent_rows:{unique_id}"
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                try:
                    selectable_size = (0, 45)
                    selected_selectable_size = (0, 90)
                    if ImGui.begin_child(f"##inherent_candidates_{unique_id}", (0, 0), border=True):
                        PyImGui.set_next_item_width(-1)
                        current_search = ui._get_search_field_value(search_state_key)
                        _, current_search = ImGui.search_field(f"##inherent_search_{unique_id}", current_search, "Search inherent upgrades...")
                        ui._set_search_field_value(search_state_key, current_search)
                        _, inherent_entries_raw = ui._get_live_search_results(
                            search_state_key,
                            current_search,
                            lambda normalized_query: cast(list[Any], ui._get_filtered_inherent_option_entries(normalized_query)),
                        )
                        inherent_entries = cast(list[tuple[type[Upgrade], str, str]], inherent_entries_raw)
                        row_states = ui._get_recalculated_value(
                            recalc_cache_key,
                            (
                                current_search,
                                ui._build_inherent_filter_condition_signature(condition),
                            ),
                            lambda: ui._build_inherent_condition_row_states(condition, inherent_entries),
                        )

                        if ImGui.begin_child(f"##inherent_selectables_{unique_id}", (0, 0), border=False):
                            if ImGui.begin_selectable(f"##inherent_candidate_{unique_id}_inscribable", selected=condition.inscribable, size=selectable_size, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                ImGui.text("Inscription Slot")
                                x, y = PyImGui.get_cursor_pos()
                                PyImGui.set_cursor_pos((x, y - 4))
                                ImGui.text_colored("Any inscribable version", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                            
                            if ImGui.end_selectable():
                                condition.inscribable = not condition.inscribable
                                changed = True
                            
                            if PyImGui.is_item_hovered():
                                PyImGui.set_next_window_size((200, 0), cond=PyImGui.ImGuiCond.Appearing)
                                ImGui.begin_tooltip()
                                ImGui.text("Inscription Slot", font_size=16)
                                ImGui.separator()
                                ImGui.text_colored("Matches any item with an inscription slot, regardless of the inherent upgrade.", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                ImGui.end_tooltip()
                                    
                            for index, row_state in enumerate(row_states):
                                inherent = row_state.inherent
                                inherent_type = row_state.inherent_type
                                inherent_filter = row_state.inherent_filter
                                already_selected = row_state.already_selected
                                entry_size = (selected_selectable_size if already_selected else selectable_size)
                                
                                if PyImGui.is_rect_visible((10, entry_size[1])):
                                    if ImGui.begin_selectable(f"##inherent_candidate_{unique_id}_{inherent_type.__name__}", selected=already_selected, size=entry_size, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                        ImGui.text(row_state.label)
                                        x, y = PyImGui.get_cursor_pos()
                                        PyImGui.set_cursor_pos((x, y - 4))
                                        ImGui.text_colored(row_state.description, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                                        if already_selected and inherent_filter is not None:
                                            PyImGui.begin_group()
                                            if len(row_state.range_instructions) == 0:
                                                ImGui.text_colored("Fixed inherent upgrade.", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                            else:
                                                for instruction in row_state.range_instructions:
                                                    current_range = inherent_filter.ranges.get(
                                                        instruction.target,
                                                        DamageRange(int(instruction.min_value), int(instruction.max_value)),
                                                    )
                                                    min_value = max(int(instruction.min_value), min(int(instruction.max_value), int(current_range.min_value)))
                                                    max_value = max(min_value, min(int(instruction.max_value), int(current_range.max_value)))
                                                    ImGui.text_colored(ui._humanize_name(instruction.target), UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                                    PyImGui.same_line(0, 8)
                                                    PyImGui.set_next_item_width(80)
                                                    new_min = ImGui.slider_int(
                                                        f"Min##inherent_min_{unique_id}_{index}_{instruction.target}",
                                                        min_value,
                                                        int(instruction.min_value),
                                                        int(instruction.max_value),
                                                    )
                                                    PyImGui.same_line(0, 6)
                                                    PyImGui.set_next_item_width(80)
                                                    new_max = ImGui.slider_int(
                                                        f"Max##inherent_max_{unique_id}_{index}_{instruction.target}",
                                                        max_value,
                                                        int(instruction.min_value),
                                                        int(instruction.max_value),
                                                    )
                                                    new_min = max(int(instruction.min_value), min(int(new_min), int(instruction.max_value)))
                                                    new_max = max(int(instruction.min_value), min(int(new_max), int(instruction.max_value)))
                                                    if new_min > new_max:
                                                        new_min, new_max = new_max, new_min
                                                    if new_min != min_value or new_max != max_value:
                                                        inherent_filter.ranges[instruction.target] = DamageRange(new_min, new_max)
                                                        changed = True
                                            PyImGui.end_group()

                                    if ImGui.end_selectable():
                                        if not already_selected:
                                            condition.inherents.append(InherentFilter.from_inherent(inherent, use_full_ranges=False))
                                        else:
                                            condition.inherents[:] = [existing for existing in condition.inherents if type(existing.inherent) is not inherent_type]
                                        changed = True

                                    if PyImGui.is_item_hovered():
                                        text_size = row_state.description_text_size
                                        PyImGui.set_next_window_size(((text_size[0] + 20) * (1 if inherent_filter is None else 2), 0), cond=PyImGui.ImGuiCond.Appearing)
                                        ImGui.begin_tooltip()
                                        ImGui.text(row_state.label, font_size=16)
                                        _, _, item_size = ImGui.get_item_rect()
                                        ImGui.separator()
 
                                        if inherent_filter is not None:
                                            width = max((text_size[0] + 20) * 2, item_size[0])
                                            if PyImGui.begin_child(f"##instruction_details_{unique_id}_{index}", (width, text_size[1] + 0), border=False):
                                                PyImGui.columns(2, "##inherent_tooltip_columns", False)
                                                for instruction in row_state.range_instructions:
                                                    setattr(inherent, instruction.target, inherent_filter.ranges[instruction.target].min_value)
                                                    ImGui.text(inherent.description_plain)
                                                    PyImGui.next_column()
                                                    setattr(inherent, instruction.target, inherent_filter.ranges[instruction.target].max_value)
                                                    ImGui.text(inherent.description_plain)
                                                PyImGui.end_columns()
                                            PyImGui.end_child()
                                        else:
                                            ImGui.text(row_state.description)
                                        ImGui.end_tooltip()
                                else:
                                    ImGui.dummy(*entry_size)  
                        ImGui.end_child()
                    ImGui.end_child()
                except Exception as e:
                    PySystem.Console.Log("Item Manager", f"Error in ConditionEditor.ForInherentFiltersCondition: {type(e).__name__}: {e!r}")
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForInscribableCondition(ui: "UI", rule: BaseRule, condition: InscribableCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                inscribable = ImGui.checkbox("Must be inscribable", condition.inscribable)
                if inscribable != condition.inscribable:
                    condition.inscribable = inscribable
                    changed = True
            UI.ConditionEditor.EndConditionContainer()
            
            return changed

        @staticmethod
        def ForUnidentifiedCondition(ui: "UI", rule: BaseRule, condition: UnidentifiedCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                identified = ImGui.checkbox(f"Item has to be {("identified" if condition.identified else "unidentified")}", condition.identified)
                if identified != condition.identified:
                    condition.identified = identified
                    changed = True
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForIsCustomizedCondition(ui: "UI", rule: BaseRule, condition: IsCustomizedCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                customized = ImGui.checkbox(f"Item has to be {("customized" if condition.customized else "not customized")}", condition.customized)
                if customized != condition.customized:
                    condition.customized = customized
                    changed = True
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForWeaponRequirementAndDamageCondition(ui: "UI", rule: BaseRule, condition: WeaponRequirementCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            condition_id = id(condition)
            popup_id = f"##requirements_condition_add_popup_{condition_id}"
            search_state_key = f"weapon_requirement_and_damage_condition_attribute_search_{condition_id}"
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            weapon_types = sorted(WEAPON_TYPES, key=lambda item_type: item_type.name)
            selected_add_weapon_type = ui._weapon_requirement_and_damage_add_item_type_state.get(condition_id, weapon_types[0] if weapon_types else ItemType.Unknown)
            selected_add_requirement_level = ui._weapon_requirement_and_damage_add_requirement_level_state.get(condition_id, 0)
            if selected_add_weapon_type not in weapon_types and weapon_types:
                selected_add_weapon_type = weapon_types[0]
            ui._weapon_requirement_and_damage_add_item_type_state[condition_id] = selected_add_weapon_type
            ui._weapon_requirement_and_damage_add_requirement_level_state[condition_id] = max(0, min(13, int(selected_add_requirement_level)))

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Requirement", -1):
                    PyImGui.open_popup(popup_id)

                PyImGui.set_next_window_size((320, 160), cond=PyImGui.ImGuiCond.Always)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Requirement")
                    ImGui.separator()

                    selected_add_weapon_type = ui._weapon_requirement_and_damage_add_item_type_state.get(condition_id, selected_add_weapon_type)
                    add_weapon_type_label = ui._item_type_name(selected_add_weapon_type) if selected_add_weapon_type != ItemType.Unknown else "Select Item Type"
                    PyImGui.set_next_item_width(-1)
                    if PyImGui.begin_combo(f"##weapon_requirement_and_damage_condition_add_item_type_{condition_id}", add_weapon_type_label, PyImGui.ImGuiComboFlags.NoFlag):
                        for weapon_type in weapon_types:
                            if ImGui.selectable(
                                ui._item_type_name(weapon_type),
                                selected=selected_add_weapon_type == weapon_type,
                            ):
                                ui._weapon_requirement_and_damage_add_item_type_state[condition_id] = weapon_type
                                selected_add_weapon_type = weapon_type
                        PyImGui.end_combo()
                    ImGui.show_tooltip("Choose the weapon item type for the requirement you want to add.")

                    requirement_labels = [f"Requirement {value}" for value in range(14)]
                    PyImGui.set_next_item_width(-1)
                    selected_add_requirement_level = ImGui.combo(
                        f"##weapon_requirement_and_damage_condition_add_requirement_{condition_id}",
                        selected_add_requirement_level,
                        requirement_labels,
                    )
                    ui._weapon_requirement_and_damage_add_requirement_level_state[condition_id] = selected_add_requirement_level
                    count = sum(
                        1
                        for entry in condition.requirements
                        if entry.attribute_level == selected_add_requirement_level and entry.weapon_type == selected_add_weapon_type
                    )
                    if count > 0:
                        ImGui.text_colored(f"{count} existing for {ui._item_type_name(selected_add_weapon_type)}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                    if ImGui.button("Add Selected Requirement", -1):
                        selected_weapon_type: WeaponType | None = cast(WeaponType, selected_add_weapon_type) if selected_add_weapon_type in WEAPON_TYPES else None
                        new_requirement = AttributeRequirement(attribute=[], attribute_level=selected_add_requirement_level, weapon_type=selected_weapon_type)
                        if selected_add_weapon_type in WEAPON_TYPES:
                            new_requirement.apply_max_ranges(selected_add_weapon_type)
                        condition.requirements.append(new_requirement)
                        changed = True
                        PyImGui.close_current_popup()

                    if ImGui.button("Close", -1):
                        PyImGui.close_current_popup()

                    PyImGui.end_popup()

                if ImGui.begin_child(f"##requirements_condition_rows_{condition_id}", (0, 0), border=False):
                    for index, requirement in enumerate(condition.requirements):
                        requirement_id = id(requirement)
                        unique_id = f"weapon_requirement_and_damage_condition_{condition_id}_{requirement_id}"
                        attribute_popup_id = f"##weapon_requirement_and_damage_condition_attributes_popup_{unique_id}"
                        summary_text = "Any Attribute" if not requirement.attributes else ", ".join(ui._humanize_name(attribute.name) for attribute in requirement.attributes)
                        
                        attribute_name = ui._humanize_name(requirement.attributes[0].name) if len(requirement.attributes) == 1 else "Item Attribute"
                        requirement_title = f"{ui._item_type_name(requirement.weapon_type)} | Requires {requirement.attribute_level} {attribute_name}"
                        value_summary = ""
                        if requirement.has_energy_range:
                            value_summary = (
                                f"Energy {requirement.min_values[0]}-{requirement.min_values[1]}"
                                if requirement.min_values[0] != requirement.min_values[1]
                                else f"Energy {requirement.min_values[0]}"
                            )
                        elif requirement.has_armor_range:
                            value_summary = (
                                f"Armor {requirement.min_values[0]}-{requirement.min_values[1]}"
                                if requirement.min_values[0] != requirement.min_values[1]
                                else f"Armor {requirement.min_values[0]}"
                            )
                        elif requirement.has_damage_ranges:
                            value_summary = f"Damage {requirement.min_values[0]}-{requirement.min_values[1]}"

                        open_config_popup = False
                        if ImGui.begin_child(f"##{unique_id}", (0, 58), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                            avail = PyImGui.get_content_region_avail()
                            
                            if ImGui.button(f"{IconsFontAwesome5.ICON_COG}##{unique_id}", avail[1], avail[1]):
                                open_config_popup = True

                            PyImGui.same_line(0, 8)
                            model_file_id = UI.ITEM_TYPE_REPRESENTATIVE_MODELFILE_IDS.get(requirement.weapon_type)
                            ui._draw_texture_from_model_file_id(model_file_id, (avail[1], avail[1]))
                            
                            PyImGui.same_line(0, 8)
                            PyImGui.begin_group()
                            ImGui.text(requirement_title)
                            x, y = PyImGui.get_cursor_pos()
                            PyImGui.set_cursor_pos((x, y - 4))
                            if value_summary:
                                ImGui.text_colored(value_summary + " | ", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                PyImGui.same_line(0, 3)
                                
                            ImGui.text_colored(summary_text, UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                            PyImGui.end_group()
                                    
                                    
                            delete_btn_size = (16, 16)
                            PyImGui.set_cursor_pos((avail[0], 4))
                            
                            PyImGui.push_style_var_vec2(ImGuiStyleVar.FramePadding, (4, 1))
                            if PyImGui.button(f"x##{id}", *delete_btn_size):
                                condition.requirements.pop(index)
                                changed = True
                                ImGui.end_child()
                                break                                    
                            PyImGui.pop_style_var(1)

                        ImGui.end_child()

                        if open_config_popup:
                            PyImGui.open_popup(attribute_popup_id)

                        PyImGui.set_next_window_size((360, 0), cond=PyImGui.ImGuiCond.Appearing)
                        if PyImGui.begin_popup(attribute_popup_id):
                            ImGui.text(requirement_title)
                            ImGui.separator()

                            requirement_weapon_type_index = weapon_types.index(requirement.weapon_type) if requirement.weapon_type in weapon_types else 0
                            requirement_weapon_type_label = ui._item_type_name(weapon_types[requirement_weapon_type_index]) if weapon_types else "Select Item Type"
                            PyImGui.set_next_item_width(-1)
                            if PyImGui.begin_combo(f"##weapon_requirement_and_damage_condition_row_item_type_{unique_id}", requirement_weapon_type_label, PyImGui.ImGuiComboFlags.NoFlag):
                                for weapon_type in weapon_types:
                                    if ImGui.selectable(ui._item_type_name(weapon_type), selected=requirement.weapon_type == weapon_type,):
                                        ui._apply_weapon_requirement_row_defaults(requirement, weapon_type, requirement.attribute_level)
                                        changed = True
                                ImGui.end_combo()
                            ImGui.show_tooltip("Choose which weapon item type this requirement row applies to.")

                            requirement_level_labels = [f"Requirement {value}" for value in range(14)]
                            PyImGui.set_next_item_width(-1)
                            next_requirement_level = ImGui.combo(
                                f"##weapon_requirement_and_damage_condition_row_requirement_{unique_id}",
                                requirement.attribute_level,
                                requirement_level_labels,
                            )
                            if next_requirement_level != requirement.attribute_level:
                                ui._apply_weapon_requirement_row_defaults(requirement, requirement.weapon_type, next_requirement_level)
                                changed = True
                            
                            ImGui.show_tooltip("Choose the required attribute level this row matches.")

                            popup_bounds = requirement.get_ranges_for_weapon_type(requirement.weapon_type) if requirement.weapon_type in WEAPON_TYPES else None

                            ImGui.separator()
                            if requirement.has_energy_range and popup_bounds is not None:
                                min_energy = ImGui.slider_int("Minimum Energy", requirement.min_values[0], popup_bounds[0][0], popup_bounds[1][0])
                                ImGui.show_tooltip(f"Require at least {min_energy} energy")
                                if min_energy != requirement.min_values[0] or min_energy != requirement.min_values[1]:
                                    requirement.min_values = (min_energy, min_energy)
                                    changed = True

                            elif requirement.has_armor_range and popup_bounds is not None:
                                min_armor = ImGui.slider_int("Minimum Armor", requirement.min_values[0], popup_bounds[0][0], popup_bounds[1][0])
                                ImGui.show_tooltip(f"Require at least {min_armor} armor")
                                if min_armor != requirement.min_values[0] or min_armor != requirement.min_values[1]:
                                    requirement.min_values = (min_armor, min_armor)
                                    changed = True

                            elif requirement.has_damage_ranges and popup_bounds is not None:
                                min_damage = ImGui.slider_int("Minimum Damage", requirement.min_values[0], popup_bounds[0][0], popup_bounds[1][0])
                                ImGui.show_tooltip(f"Require at least a lower damage of {min_damage}")
                                max_damage = ImGui.slider_int("Maximum Damage", requirement.min_values[1], popup_bounds[1][0], popup_bounds[1][1])
                                ImGui.show_tooltip(f"Require at least an upper damage of {max_damage}")
                                if min_damage != requirement.min_values[0] or max_damage != requirement.min_values[1]:
                                    requirement.min_values = (min_damage, max_damage)
                                    changed = True

                            available_attributes = ui._get_requirement_popup_attributes_for_requirement(requirement.weapon_type, requirement.attribute_level)
                            if len(available_attributes) > 1:
                                ImGui.separator()
                                PyImGui.set_next_item_width(-1)
                                ui._focus_popup_search_field_on_appearing()
                                current_search = ui._get_search_field_value(search_state_key)
                                _, current_search = ImGui.search_field(f"##weapon_requirement_and_damage_condition_attribute_search_{unique_id}", current_search, "Search attributes...")
                                ui._set_search_field_value(search_state_key, current_search)
                                normalized_query = current_search.strip().lower()

                                if ImGui.button("Clear Attributes", -1):
                                    requirement.attributes.clear()
                                    changed = True
                                    
                                if ImGui.begin_child(f"##weapon_requirement_and_damage_condition_attribute_list_{unique_id}", (0, 180), border=True):
                                    for attribute in available_attributes:
                                        attribute_label = ui._humanize_name(attribute.name)
                                        if normalized_query and normalized_query not in attribute_label.lower() and normalized_query not in attribute.name.lower():
                                            continue

                                        selected = attribute in requirement.attributes
                                        if ImGui.begin_selectable(f"##weapon_requirement_and_damage_condition_attribute_{unique_id}_{attribute.name}", selected, (0, 28), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                            ImGui.text(attribute_label)
                                        if ImGui.end_selectable():
                                            if len(available_attributes) > 1:
                                                if selected:
                                                    requirement.attributes = [entry for entry in requirement.attributes if entry != attribute]
                                                else:
                                                    requirement.attributes.append(attribute)
                                                changed = True
                                elif requirement.attribute_level == 0:
                                    requirement.attributes.clear()
                                    ImGui.text_wrapped("Requirement 0 means the item must not have an attribute. No attribute filters are available.")
                                ImGui.end_child()
                                
                            if ImGui.button("Close", -1):
                                PyImGui.close_current_popup()

                            PyImGui.end_popup()
                ImGui.end_child()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForHalvesCastAndRechargeAttributeCondition(ui: "UI", rule: BaseRule, condition: HalvesCastAndRechargeAttributeCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                ImGui.text_wrapped(f"Match items with a '{UI.HalvesCastingTimeAttributeUpgrade_INSTANCE.description_plain}' or '{UI.HalvesRechargeTimeAttributeUpgrade_INSTANCE.description_plain}' modifier of the items attribute.")
            UI.ConditionEditor.EndConditionContainer()
            
            return changed

        @staticmethod
        def ForArmorUpgradesCondition(ui: "UI", rule: BaseRule, condition: ArmorUpgradesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            popup_id = f"##armor_upgrade_price_popup_{id(condition)}"
            trader_open = TraderWindow.IsOpen()
            kind = TraderPriceCheckManager.get_kind()
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)

            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                PyImGui.begin_disabled(not trader_open or kind != "runes")
                if ImGui.button("Select From Trader Prices", -1):
                    PyImGui.open_popup(popup_id)
                PyImGui.end_disabled()
                
                if PyImGui.is_item_hovered():
                    if not trader_open or kind != "runes":
                        ImGui.show_tooltip("Open the rune trader window to enable this option.")
                    else:
                        ImGui.show_tooltip("Open a popup to select runes and insignias priced at or above a threshold.")

                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Select Upgrades By Price")
                    ImGui.separator()
                    new_threshold = ImGui.input_int("Minimum trader value", ui.armor_upgrade_price_threshold, min_value=0, step_fast=1)
                    if new_threshold != ui.armor_upgrade_price_threshold:
                        ui.armor_upgrade_price_threshold = max(0, new_threshold)

                    quote_count = len(ui._get_trader_armor_upgrade_quotes(filter_by_profession=False))
                    ImGui.text_colored(f"Available trader quotes: {quote_count}", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)

                    if ImGui.button("Apply Threshold", -1):
                        all_quote_lookup = ui._get_armor_upgrade_quote_lookup(filter_by_profession=False)
                        desired_upgrades: list[ArmorUpgrade] = []
                        for upgrade_type in ui._get_all_armor_upgrade_types():
                            default_upgrade = cast(ArmorUpgrade, upgrade_type())
                            quote = all_quote_lookup.get(default_upgrade._comparison_data())
                            if quote is not None and quote.quoted_value >= ui.armor_upgrade_price_threshold:
                                desired_upgrades.append(default_upgrade)
                                continue

                            if quote is None:
                                desired_upgrades.append(default_upgrade)

                        previous_upgrade_keys = [upgrade._comparison_data() for upgrade in condition.armor_upgrades]
                        next_upgrade_keys = [upgrade._comparison_data() for upgrade in desired_upgrades]
                        if previous_upgrade_keys == next_upgrade_keys:
                            PySystem.Console.Log("Item Manager", "Trader-based selection already matches the current threshold.", PySystem.Console.MessageType.Warning)
                        else:
                            previous_upgrades_by_key = {upgrade._comparison_data(): upgrade for upgrade in condition.armor_upgrades}
                            next_upgrades_by_key = {upgrade._comparison_data(): upgrade for upgrade in desired_upgrades}
                            added_count = len([key for key in next_upgrades_by_key if key not in previous_upgrades_by_key])
                            removed_count = len([key for key in previous_upgrades_by_key if key not in next_upgrades_by_key])
                            condition.armor_upgrades = desired_upgrades
                            changed = True
                            PySystem.Console.Log(
                                "Item Manager",
                                f"Trader-based selection synced upgrades to the current threshold. Added {added_count}, removed {removed_count}.",
                                PySystem.Console.MessageType.Success,
                            )
                        PyImGui.close_current_popup()

                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()
                    PyImGui.end_popup()

                if ImGui.begin_table(f"##armor_upgrade_condition_table_{id(condition)}", 2, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable):
                    PyImGui.table_setup_column("Profession", PyImGui.TableColumnFlags.WidthFixed, 150)
                    PyImGui.table_setup_column("Upgrades", PyImGui.TableColumnFlags.WidthStretch)
                    PyImGui.table_next_row()
                    PyImGui.table_next_column()
                    selected_upgrade_keys = {existing_upgrade._comparison_data() for existing_upgrade in condition.armor_upgrades}

                    if ImGui.begin_child(f"##armor_upgrade_condition_profession_{id(condition)}", (0, 0), border=False):
                        for profession in Profession:
                            is_selected = profession == ui.profession
                            decoded_profession_name = string_table.decode(GWEncoded.PROFESSION.get(profession, bytes())) or ui._humanize_name(profession.name)
                            if ImGui.begin_selectable(f"##profession_{id(condition)}_{profession.value}", is_selected, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                ImGui.image(os.path.join(ui.texture_path, "Profession_Icons", ProfessionTextureMap.get(profession.value, "")), (24, 24))
                                PyImGui.same_line(0, 5)
                                ImGui.text_aligned(decoded_profession_name, height=24, alignment=Alignment.MidLeft)
                            if ImGui.end_selectable():
                                ui.profession = profession
                    ImGui.end_child()

                    PyImGui.table_next_column()
                    if ImGui.begin_child(f"##armor_upgrade_condition_upgrades_{id(condition)}", (0, 0), border=False):
                        try:
                            sorted_upgrades = ui._get_armor_upgrade_types_for_profession(ui.profession)
                            insignias = [upgrade_type for upgrade_type in sorted_upgrades if issubclass(upgrade_type, Insignia)]
                            runes = [upgrade_type for upgrade_type in sorted_upgrades if issubclass(upgrade_type, Rune)]

                            for upgrade_type in [*insignias, *runes]:
                                upgrade: ArmorUpgrade = upgrade_type()
                                upgrade_label = ui._format_upgrade_label(upgrade)
                                upgrade_key = upgrade._comparison_data()
                                is_upgrade_selected = upgrade_key in selected_upgrade_keys
                                if ImGui.begin_selectable(f"##armor_upgrade_{id(condition)}_{upgrade_type.__name__}", is_upgrade_selected, (0, 20), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                    rarity_color = UI._get_rarity_color(upgrade.rarity)
                                    ImGui.text_colored(upgrade_label, rarity_color.color_tuple, font_size=14)
                                if ImGui.end_selectable():
                                    if is_upgrade_selected:
                                        condition.armor_upgrades = [
                                            existing_upgrade
                                            for existing_upgrade in condition.armor_upgrades
                                            if existing_upgrade._comparison_data() != upgrade_key
                                        ]
                                        selected_upgrade_keys.discard(upgrade_key)
                                    else:
                                        condition.armor_upgrades.append(upgrade)
                                        selected_upgrade_keys.add(upgrade_key)
                                    changed = True

                                if PyImGui.is_item_hovered():
                                    PyImGui.set_next_window_size((400, 50), cond=PyImGui.ImGuiCond.Appearing)
                                    PyImGui.begin_tooltip()
                                    quote = ui._get_trader_quote_for_armor_upgrade(upgrade)
                                    PyImGui.text_wrapped(upgrade.description_plain)
                                    if quote is not None:
                                        ImGui.text_colored(f"Trader Value: {UI.format_currency(quote.quoted_value)}\n", UI._get_rarity_color(Rarity.Gold).color_tuple, font_size=13)
                                        PyImGui.separator()
                                        ImGui.text_colored(f"Updated: {UI.format_time_ago(quote.checked_at)}\n", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                    else:
                                        PyImGui.separator()
                                        ImGui.text_colored("No matching trader quote found for this upgrade.", UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                                    PyImGui.end_tooltip()
                                    
                        except Exception as e:
                            ImGui.text_colored(f"Error loading upgrades: {str(e)}", (255, 0, 0, 255), font_size=12)
                    ImGui.end_child()
                    ImGui.end_table()

            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForMaxWeaponUpgradesCondition(ui: "UI", rule: BaseRule, condition: MaxWeaponUpgradesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            search_state_key = f"max_weapon_upgrades_condition_{id(condition)}"
            weapon_upgrades_by_type: dict[type[Upgrade], UpgradeAndItemType] = {}
            for existing_upgrade in condition.weapon_upgrades:
                weapon_upgrades_by_type.setdefault(type(existing_upgrade.upgrade), existing_upgrade)
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.begin_table(f"##weapon_upgrade_condition_table_{id(condition)}", 2, PyImGui.TableFlags.Borders | PyImGui.TableFlags.Resizable):
                    PyImGui.table_setup_column("Mod Type", PyImGui.TableColumnFlags.WidthFixed, 150)
                    PyImGui.table_setup_column("Upgrades", PyImGui.TableColumnFlags.WidthStretch)
                    PyImGui.table_next_row()
                    PyImGui.table_next_column()

                    if ImGui.begin_child(f"##mod_type_selection_{id(condition)}", (0, 0), border=False):
                        for mod_type in [ItemUpgradeType.Prefix, ItemUpgradeType.Suffix, ItemUpgradeType.Inscription]:
                            is_selected = mod_type == ui.mod_type
                            mod_type_name = ui._humanize_name(mod_type.name)
                            if ImGui.begin_selectable(f"##mod_type_{id(condition)}_{mod_type.value}", is_selected, selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                ImGui.text_aligned(mod_type_name, height=24, alignment=Alignment.MidLeft)
                            if ImGui.end_selectable():
                                if ui.mod_type != mod_type:
                                    ui._clear_search_field_value(search_state_key)
                                ui.mod_type = mod_type
                    ImGui.end_child()

                    PyImGui.table_next_column()
                    style = ImGui.get_style()
                    style.ToggleButtonEnabled.push_color(ui._get_rarity_color(Rarity.Gold).opacity(0.85).rgb_tuple)
                    style.ToggleButtonDisabled.push_color((0, 0, 0, 85))
                    PyImGui.set_next_item_width(-1)
                    current_search = ui._get_search_field_value(search_state_key)
                    _, current_search = ImGui.search_field(f"##upgrade_search_{id(condition)}", current_search, "Search Upgrades...")
                    ui._set_search_field_value(search_state_key, current_search)
                    _, matching_upgrade_types_raw = ui._get_live_search_results(
                        f"max_weapon_upgrades_condition_{id(condition)}_{ui.mod_type.name}",
                        current_search,
                        lambda normalized_query: cast(
                            list[Any],
                            [
                                upgrade_type
                                for upgrade_type in ui._get_weapon_upgrade_types_for_mod_type(ui.mod_type)
                                if not normalized_query or ui._search_text_matches(normalized_query, ui._format_upgrade_type_label(upgrade_type), getattr(upgrade_type, "name", ""))
                            ],
                        ),
                    )
                    matching_upgrade_types = cast(list[type[Upgrade]], matching_upgrade_types_raw)
                    ImGui.separator()

                    if ImGui.begin_child(f"##weapon_upgrade_condition_upgrades_{id(condition)}", (0, 0), border=False):
                        for upgrade_type in matching_upgrade_types:
                            for variant in [upgrade_type]:
                                upgrade = cast(WeaponUpgrade | Inscription, variant())
                                upgrade_label = ui._format_upgrade_label(upgrade)

                                if isinstance(upgrade, WeaponUpgrade):
                                    item_types = ui._get_allowed_item_types(upgrade)
                                    rarity_color = UI._get_rarity_color(upgrade.rarity)
                                    existing_entry = weapon_upgrades_by_type.get(upgrade_type)
                                    selected_item_types = set(existing_entry.item_types) if existing_entry is not None else set()
                                    hovered = False
                                    if PyImGui.is_rect_visible((10, 70)):
                                        if ImGui.begin_child(f"##upgrade_item_types_{id(condition)}_{variant}", (0, 70), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                                            ImGui.text_colored(upgrade_label, rarity_color.color_tuple, font_size=14)
                                            ImGui.separator()
                                            for item_type in item_types:
                                                is_upgrade_selected = item_type in selected_item_types
                                                upgrade_textures = ui.weapon_upgrade_textures.get(item_type)
                                                if upgrade_textures:
                                                    model_file_id = ui._get_texture_path_for_model_file_id_direct(upgrade_textures.prefix if ui.mod_type == ItemUpgradeType.Prefix else upgrade_textures.suffix)
                                                    ImGui.image_toggle_button(f"##{id(condition)}_{variant}_{item_type.name}", model_file_id, is_upgrade_selected, 24, 24)
                                                    encoded = upgrade.create_upgrade_name(item_type)
                                                    if PyImGui.is_item_clicked(0):
                                                        io = PyImGui.get_io()
                                                        if io.key_ctrl:
                                                            should_select_all = not is_upgrade_selected
                                                            if should_select_all:
                                                                if existing_entry:
                                                                    existing_entry.item_types.clear()
                                                                    existing_entry.item_types.extend(item_types)
                                                                    selected_item_types = set(item_types)
                                                                else:
                                                                    existing_entry = UpgradeAndItemType(upgrade=upgrade, item_types=list(item_types))
                                                                    condition.weapon_upgrades.append(existing_entry)
                                                                    weapon_upgrades_by_type[upgrade_type] = existing_entry
                                                                    selected_item_types = set(item_types)
                                                            elif existing_entry:
                                                                condition.weapon_upgrades.remove(existing_entry)
                                                                weapon_upgrades_by_type.pop(upgrade_type, None)
                                                                existing_entry = None
                                                                selected_item_types.clear()
                                                        else:
                                                            if existing_entry and item_type in existing_entry.item_types:
                                                                existing_entry.item_types.remove(item_type)
                                                                selected_item_types.discard(item_type)
                                                                if not existing_entry.item_types:
                                                                    condition.weapon_upgrades.remove(existing_entry)
                                                                    weapon_upgrades_by_type.pop(upgrade_type, None)
                                                                    existing_entry = None
                                                            elif existing_entry:
                                                                existing_entry.item_types.append(item_type)
                                                                selected_item_types.add(item_type)
                                                            else:
                                                                existing_entry = UpgradeAndItemType(upgrade=upgrade, item_types=[item_type])
                                                                condition.weapon_upgrades.append(existing_entry)
                                                                weapon_upgrades_by_type[upgrade_type] = existing_entry
                                                                selected_item_types = {item_type}
                                                        changed = True
                                                    ImGui.show_tooltip(encoded.plain if encoded else ui._item_type_name(item_type))
                                                    hovered = hovered or PyImGui.is_item_hovered()
                                                    PyImGui.same_line(0, 5)
                                        ImGui.end_child()
                                        if not hovered:
                                            
                                            ImGui.show_tooltip(upgrade.description_plain)
                                    else:
                                        ImGui.dummy(0, 70)
                                else:
                                    is_upgrade_selected = upgrade_type in weapon_upgrades_by_type
                                    if PyImGui.is_rect_visible((10, 25)):
                                        if ImGui.begin_selectable(f"##weapon_upgrade_{id(condition)}_{upgrade_type.__name__}", is_upgrade_selected, (0, 28), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                            
                                            upgrade_textures = ui.weapon_upgrade_textures.get(upgrade.target_item_type, None)
                                            model_file_id = upgrade_textures.inherent if upgrade_textures else None
                                            ui._draw_texture_from_model_file_id(model_file_id, (20, 20))
                                            
                                            PyImGui.same_line(0, 5)
                                            
                                            rarity_color = UI._get_rarity_color(upgrade.rarity)
                                            ImGui.text_aligned(upgrade_label, color=rarity_color.color_tuple, font_size=14, height=20, alignment=Alignment.MidLeft)
                                        if ImGui.end_selectable():
                                            if is_upgrade_selected:
                                                condition.weapon_upgrades = [existing_upgrade for existing_upgrade in condition.weapon_upgrades if not isinstance(existing_upgrade.upgrade, upgrade_type)]
                                                weapon_upgrades_by_type.pop(upgrade_type, None)
                                            else:
                                                existing_entry = UpgradeAndItemType(upgrade=upgrade, item_types=[])
                                                condition.weapon_upgrades.append(existing_entry)
                                                weapon_upgrades_by_type[upgrade_type] = existing_entry
                                            changed = True
                                        ImGui.show_tooltip(upgrade.description_plain)
                                    else:
                                        ImGui.dummy(0, 25)
                    ImGui.end_child()
                    style.ToggleButtonDisabled.pop_color()
                    style.ToggleButtonEnabled.pop_color()
                    ImGui.end_table()
            UI.ConditionEditor.EndConditionContainer()
            return changed

        @staticmethod
        def ForUpgradeRangesCondition(ui: "UI", rule: BaseRule, condition: UpgradeRangesCondition, size: Optional[tuple[float, float]] = None) -> bool:
            changed = False
            popup_id = f"##upgrade_range_add_popup_{id(condition)}"
            search_state_key = f"upgrade_ranges_condition_{id(condition)}"
            selected_upgrade_range_keys: set[tuple[type[Upgrade], str]] = {
                (type(existing.upgrade), existing.target)
                for existing in condition.upgrade_ranges
            }
            upgrade_ranges_by_type: dict[type[Upgrade], RangedUpgrade] = {}
            for existing_upgrade in condition.upgrade_ranges:
                upgrade_ranges_by_type.setdefault(type(existing_upgrade.upgrade), existing_upgrade)
            sizes = UI.ConditionEditor.GetSizes(rule, condition, size)
            if UI.ConditionEditor.BeginConditionContainer(ui, rule, condition, (sizes.get("width", 0), sizes.get("height", 0))):
                if ImGui.button("Add Range Upgrade", -1):
                    PyImGui.open_popup(popup_id)

                PyImGui.set_next_window_size((300, 0), cond=PyImGui.ImGuiCond.Appearing)
                if PyImGui.begin_popup(popup_id):
                    ImGui.text("Add Upgrade Range Rule")
                    ImGui.separator()
                    PyImGui.set_next_item_width(-1)
                    ui._focus_popup_search_field_on_appearing()
                    current_search = ui._get_search_field_value(search_state_key)
                    _, current_search = ImGui.search_field(f"##upgrade_range_search_{id(condition)}", current_search, "Search Upgrades...")
                    ui._set_search_field_value(search_state_key, current_search)
                    _, range_options_raw = ui._get_live_search_results(
                        search_state_key,
                        current_search,
                        lambda normalized_query: cast(list[Any], ui._get_filtered_range_upgrade_options(normalized_query)),
                    )
                    range_options = cast(list[tuple[type[WeaponUpgrade | Inscription], RangeInstruction]], range_options_raw)

                    if ImGui.begin_child(f"##upgrade_range_candidates_{id(condition)}", (0, 300), border=True):
                        for upgrade_type, instruction in range_options:
                            upgrade = cast(WeaponUpgrade | Inscription, upgrade_type())
                            option_label = ui._format_upgrade_label(upgrade)
                            already_selected = (upgrade_type, instruction.target) in selected_upgrade_range_keys
                            if ImGui.begin_selectable(f"##upgrade_range_option_{id(condition)}_{upgrade_type.__name__}_{instruction.target}", False, (0, 36), selected_color=UI.SELECTABLE_SELECTED_COLOR.rgb_tuple, hover_color=UI.SELECTABLE_HOVERED_COLOR.rgb_tuple):
                                rarity_color = UI._get_rarity_color(upgrade.rarity)
                                ImGui.text_colored(option_label, rarity_color.color_tuple, font_size=14)
                                x, y = PyImGui.get_cursor_pos()
                                PyImGui.set_cursor_pos((x, y - 4))
                                ImGui.text_colored(f"{instruction.target}: {instruction.min_value} - {instruction.max_value}" + ("%" if instruction.target == "chance" else ""), UI.SUBTLE_TEXT_COLOR.color_tuple, font_size=12)
                            if ImGui.end_selectable() and not already_selected:
                                new_entry = RangedUpgrade(upgrade=upgrade, target=instruction.target, min_value=float(instruction.min_value), max_value=float(instruction.max_value), item_types=[])
                                condition.upgrade_ranges.append(new_entry)
                                selected_upgrade_range_keys.add((upgrade_type, instruction.target))
                                upgrade_ranges_by_type.setdefault(upgrade_type, new_entry)
                                changed = True
                                PyImGui.close_current_popup()
                            if PyImGui.is_item_hovered():
                                ImGui.show_tooltip(upgrade.description_plain)
                    ImGui.end_child()
                    if ImGui.button("Cancel", -1):
                        PyImGui.close_current_popup()
                    PyImGui.end_popup()

                style = ImGui.get_style()
                style.ToggleButtonEnabled.push_color(ui._get_rarity_color(Rarity.Gold).opacity(0.85).rgb_tuple)
                style.ToggleButtonDisabled.push_color((0, 0, 0, 85))
                if ImGui.begin_child(f"##existing_upgrade_ranges_{id(condition)}", (0, 0), border=False):
                    for index, upgrade_range in enumerate(condition.upgrade_ranges):
                        unique_id = f"upgrade_range_condition_{id(condition)}_{index}"
                        instruction = ui._get_range_instruction(upgrade_range.upgrade, upgrade_range.target)
                        if instruction is None:
                            continue
                        if ImGui.begin_child(f"##{unique_id}", (0, 105), border=True):
                            style.CellPadding.push_style_var_direct(4, 4)
                            if ImGui.begin_table(f"##{unique_id}_table", 3, PyImGui.TableFlags.NoBordersInBody):
                                PyImGui.table_setup_column("Name", PyImGui.TableColumnFlags.WidthFixed, 200)
                                PyImGui.table_setup_column("ItemTypes", PyImGui.TableColumnFlags.WidthStretch)
                                PyImGui.table_setup_column("Delete", PyImGui.TableColumnFlags.WidthFixed, 50)
                                PyImGui.table_next_row()
                                PyImGui.table_next_column()
                                rarity_color = UI._get_rarity_color(upgrade_range.upgrade.rarity)
                                ImGui.text_colored(ui._format_upgrade_label(upgrade_range.upgrade), rarity_color.color_tuple, font_size=14)
                                PyImGui.table_next_column()
                                item_types = ui._get_allowed_item_types(upgrade_range.upgrade)
                                if item_types:
                                    existing_entry = upgrade_ranges_by_type.get(type(upgrade_range.upgrade))
                                    selected_item_types = set(existing_entry.item_types) if existing_entry is not None else set()
                                    style.ChildBg.push_color_direct((0, 0, 0, 80))
                                    style.WindowPadding.push_style_var_direct(4, 4)
                                    if ImGui.begin_child(f"##{unique_id}_item_types", (0, 32), border=True, flags=PyImGui.WindowFlags.NoScrollbar | PyImGui.WindowFlags.NoScrollWithMouse):
                                        for item_type in item_types:
                                            is_upgrade_selected = item_type in selected_item_types
                                            texture = ui.weapon_upgrade_textures.get(item_type)
                                            if texture:
                                                texture_path = ui._get_texture_path_for_model_file_id_direct(texture.prefix if upgrade_range.upgrade.mod_type == ItemUpgradeType.Prefix else texture.suffix)
                                                ImGui.image_toggle_button(f"##{id(condition)}_{index}_{item_type.name}", texture_path, is_upgrade_selected, 24, 24)
                                                encoded = upgrade_range.upgrade.create_upgrade_name(item_type)
                                                if PyImGui.is_item_clicked(0):
                                                    io = PyImGui.get_io()
                                                    if io.key_ctrl:
                                                        should_select_all = not is_upgrade_selected
                                                        if should_select_all:
                                                            if existing_entry:
                                                                existing_entry.item_types.clear()
                                                                existing_entry.item_types.extend(item_types)
                                                                selected_item_types = set(item_types)
                                                            else:
                                                                existing_entry = RangedUpgrade(upgrade=upgrade_range.upgrade, target=upgrade_range.target, min_value=upgrade_range.min_value, max_value=upgrade_range.max_value, item_types=list(item_types))
                                                                condition.upgrade_ranges.append(existing_entry)
                                                                upgrade_ranges_by_type[type(upgrade_range.upgrade)] = existing_entry
                                                                selected_item_types = set(item_types)
                                                    else:
                                                        if existing_entry and item_type in existing_entry.item_types:
                                                            existing_entry.item_types.remove(item_type)
                                                            selected_item_types.discard(item_type)
                                                        elif existing_entry:
                                                            existing_entry.item_types.append(item_type)
                                                            selected_item_types.add(item_type)
                                                        else:
                                                            existing_entry = RangedUpgrade(upgrade=upgrade_range.upgrade, target=upgrade_range.target, min_value=upgrade_range.min_value, max_value=upgrade_range.max_value, item_types=[item_type])
                                                            condition.upgrade_ranges.append(existing_entry)
                                                            upgrade_ranges_by_type[type(upgrade_range.upgrade)] = existing_entry
                                                            selected_item_types = {item_type}
                                                    changed = True
                                                ImGui.show_tooltip(encoded.plain if encoded else ui._item_type_name(item_type))
                                                PyImGui.same_line(0, 5)
                                    ImGui.end_child()
                                    style.WindowPadding.pop_style_var()
                                    style.ChildBg.pop_color_direct()
                                PyImGui.table_next_column()
                                if ImGui.button(f"{IconsFontAwesome5.ICON_TRASH}##{unique_id}", 40, 40):
                                    condition.upgrade_ranges.pop(index)
                                    changed = True
                                ImGui.end_table()
                            style.CellPadding.pop_style_var()

                            ImGui.separator()
                            value_is_int = isinstance(instruction.min_value, int) and isinstance(instruction.max_value, int)
                            current_min = int(upgrade_range.min_value) if value_is_int else upgrade_range.min_value
                            current_max = int(upgrade_range.max_value) if value_is_int else upgrade_range.max_value
                            width = PyImGui.get_content_region_avail()[0]
                            PyImGui.push_item_width(width / 2 - 10)
                            if value_is_int:
                                new_min = ImGui.slider_int(f"##Minimum##{unique_id}", int(current_min), int(instruction.min_value), int(instruction.max_value))
                                if PyImGui.is_item_hovered():
                                    upgrade_range.upgrade.__setattr__(upgrade_range.target, new_min)
                                    ImGui.show_tooltip(upgrade_range.upgrade.description_plain)
                                PyImGui.same_line(0, 8)
                                new_max = ImGui.slider_int(f"###Maximum##{unique_id}", int(current_max), int(instruction.min_value), int(instruction.max_value))
                                if PyImGui.is_item_hovered():
                                    upgrade_range.upgrade.__setattr__(upgrade_range.target, new_max)
                                    ImGui.show_tooltip(upgrade_range.upgrade.description_plain)
                            else:
                                new_min = ImGui.slider_float(f"###Minimum##{unique_id}", current_min, float(instruction.min_value), float(instruction.max_value))
                                PyImGui.same_line(0, 8)
                                new_max = ImGui.slider_float(f"##Maximum##{unique_id}", current_max, float(instruction.min_value), float(instruction.max_value))
                            PyImGui.pop_item_width()

                            new_min_value = min(new_min, new_max)
                            new_max_value = max(new_min, new_max)
                            if new_min_value != upgrade_range.min_value or new_max_value != upgrade_range.max_value:
                                condition.upgrade_ranges[index] = RangedUpgrade(upgrade=upgrade_range.upgrade, target=upgrade_range.target, min_value=float(new_min_value), max_value=float(new_max_value), item_types=upgrade_range.item_types)
                                changed = True
                        ImGui.end_child()
                ImGui.end_child()
                style.ToggleButtonDisabled.pop_color()
                style.ToggleButtonEnabled.pop_color()
                
            UI.ConditionEditor.EndConditionContainer()
            return changed

    def _draw_condition_editor(self, rule: BaseRule, condition: BaseCondition, size: Optional[tuple[float, float]] = None) -> bool:
        match condition:
            case ModelIdsCondition():
                return UI.ConditionEditor.ForModelIdsCondition(self, rule, condition, size)
            
            case ItemTypesCondition():
                return UI.ConditionEditor.ForItemTypesCondition(self, rule, condition, size)
            
            case EncodedNamesCondition():
                return UI.ConditionEditor.ForEncodedNamesCondition(self, rule, condition, size)
            
            case ModelFileIdsCondition():
                return UI.ConditionEditor.ForModelFileIdsCondition(self, rule, condition, size)
            
            case ModelFileIdsAndItemTypesCondition():
                return UI.ConditionEditor.ForModelFileIdsAndItemTypesCondition(self, rule, condition, size)
            
            case ModelIdsAndItemTypesCondition():
                return UI.ConditionEditor.ForModelIdsAndItemTypesCondition(self, rule, condition, size)
            
            case ExactItemTypeCondition():
                return UI.ConditionEditor.ForExactItemTypeCondition(self, rule, condition, size)
            
            case BowTypeCondition():
                return UI.ConditionEditor.ForBowTypeCondition(self, rule, condition, size)

            case StackQuantityCondition():
                return UI.ConditionEditor.ForStackQuantityCondition(self, rule, condition, size)
            
            case NickItemCondition():
                return UI.ConditionEditor.ForNickItemCondition(self, rule, condition, size)

            case WeaponRequirementCondition():
                return UI.ConditionEditor.ForWeaponRequirementAndDamageCondition(self, rule, condition, size)

            case IsMaterialCondition():
                return UI.ConditionEditor.ForIsMaterialCondition(self, rule, condition, size)

            case QuantityMatchCondition():
                return UI.ConditionEditor.ForQuantityMatchCondition(self, rule, condition, size)
             
            case RaritiesCondition():
                return UI.ConditionEditor.ForRaritiesCondition(self, rule, condition, size)
            
            case DyeColorsCondition():
                return UI.ConditionEditor.ForDyeColorsCondition(self, rule, condition, size)
            
            case SalvagesToMaterialsCondition():
                return UI.ConditionEditor.ForSalvagesToMaterialsCondition(self, rule, condition, size)
            
            case InherentFiltersCondition():
                return UI.ConditionEditor.ForInherentFiltersCondition(self, rule, condition, size)
            
            case InscribableCondition():
                return UI.ConditionEditor.ForInscribableCondition(self, rule, condition, size)
            
            case UnidentifiedCondition():
                return UI.ConditionEditor.ForUnidentifiedCondition(self, rule, condition, size)

            case IsCustomizedCondition():
                return UI.ConditionEditor.ForIsCustomizedCondition(self, rule, condition, size)

            case HalvesCastAndRechargeAttributeCondition():
                return UI.ConditionEditor.ForHalvesCastAndRechargeAttributeCondition(self, rule, condition, size)
            
            case ArmorUpgradesCondition():
                return UI.ConditionEditor.ForArmorUpgradesCondition(self, rule, condition, size)
            
            case MaxWeaponUpgradesCondition():
                return UI.ConditionEditor.ForMaxWeaponUpgradesCondition(self, rule, condition, size)
            
            case UpgradeRangesCondition():
                return UI.ConditionEditor.ForUpgradeRangesCondition(self, rule, condition, size)
            
            case _:
                ImGui.text("No editor available for this condition.")
                return False

    def _supports_custom_condition_editor(self, condition_type: type[BaseCondition]) -> bool:
        supported_types = (
            ModelIdsCondition,
            EncodedNamesCondition,
            ModelFileIdsCondition,
            ModelFileIdsAndItemTypesCondition,
            ModelIdsAndItemTypesCondition,
            ItemTypesCondition,
            ExactItemTypeCondition,
            BowTypeCondition,
            StackQuantityCondition,
            NickItemCondition,
            WeaponRequirementCondition,
            IsMaterialCondition,
            QuantityMatchCondition,
            RaritiesCondition,
            DyeColorsCondition,
            SalvagesToMaterialsCondition,
            InherentFiltersCondition,
            InscribableCondition,
            UnidentifiedCondition,
            IsCustomizedCondition,
            HalvesCastAndRechargeAttributeCondition,
            ArmorUpgradesCondition,
            MaxWeaponUpgradesCondition,
            UpgradeRangesCondition,
        )
        return issubclass(condition_type, supported_types)

    def _draw_custom_rule(
        self,
        rule: CustomRule,
        condition_types: list[type[BaseCondition]] | None = None,
        editable_only: bool = True,
    ) -> bool:
        changed = False
        active_drag = self._drag_condition_source_rule is rule and self._drag_condition is not None
        available_condition_types = condition_types if condition_types is not None else self._get_condition_types()
        conditions_context_popup_id = f'##custom_rule_conditions_context_{id(rule)}'
        PyImGui.set_next_item_width(180)
        if PyImGui.begin_combo(f"##custom_rule_operator_{id(rule)}", self._humanize_name(rule.condition_operator.name), PyImGui.ImGuiComboFlags.NoFlag):
            for operator in ConditionOperator:
                if ImGui.selectable(self._humanize_name(operator.name), selected=rule.condition_operator == operator):
                    rule.condition_operator = operator
                    changed = True
            ImGui.end_combo()
        ImGui.show_tooltip("Choose whether all conditions must match or whether any single condition is enough.")

        PyImGui.same_line(0, 8)
        if PyImGui.begin_combo(f"##custom_rule_add_condition_{id(rule)}", "Add Condition", PyImGui.ImGuiComboFlags.HeightLargest):
            if self._can_paste_condition_into_rule(rule):
                paste_label = f'Paste Condition: {self._condition_clipboard_label}' if self._condition_clipboard_label else 'Paste Condition'
                if ImGui.selectable(paste_label, False):
                    if self._paste_condition_into_rule(rule):
                        changed = True
                ImGui.separator()

            for condition_type in available_condition_types:
                if editable_only and not self._supports_custom_condition_editor(condition_type):
                    continue

                if ImGui.selectable(self._humanize_name(condition_type.__name__).replace("Condition", ""), False):
                    rule.conditions.append(condition_type())
                    changed = True
                self._show_wrapped_tooltip(self._format_condition_type_tooltip(condition_type))
            ImGui.end_combo()

        ImGui.separator()
        
        if ImGui.begin_child(f"##custom_rule_conditions_{id(rule)}", (0, 0), border=True):
            if PyImGui.is_window_hovered() and PyImGui.is_mouse_clicked(1):
                PyImGui.open_popup(conditions_context_popup_id)

            if PyImGui.begin_popup(conditions_context_popup_id):
                ImGui.text_colored('Conditions', color=UI.CREME_COLOR.color_tuple, font_size=16)
                ImGui.separator()
                if self._can_paste_condition_into_rule(rule):
                    paste_label = f'Paste Condition: {self._condition_clipboard_label}' if self._condition_clipboard_label else 'Paste Condition'
                    if ImGui.menu_item(paste_label):
                        if self._paste_condition_into_rule(rule):
                            changed = True
                            PyImGui.close_current_popup()
                ImGui.end_popup()

            self._condition_drag_handle_state.clear()
            io = PyImGui.get_io()
            child_pos = PyImGui.get_window_pos()
            child_size = PyImGui.get_window_size()
            child_visible_left = child_pos[0]
            child_visible_right = child_pos[0] + child_size[0]
            child_visible_top = child_pos[1]
            child_visible_bottom = child_pos[1] + child_size[1]
            condition_rects: dict[int, tuple[float, float, float, float]] = {}
            condition_gap_values: list[float] = []
            self._drag_condition_target_rect = None if active_drag else self._drag_condition_target_rect
            avail = PyImGui.get_content_region_avail()
            UI.CUSTOM_RULE_CONTENT_RECT = (avail[0], avail[1])
            
            if not rule.conditions:
                ImGui.text_wrapped("Add one or more conditions to build a custom rule.")
            else:
                for index, condition in enumerate(rule.conditions[:]):
                    if self._draw_condition_editor(rule, condition):
                        changed = True
                        
                    item_min, item_max, item_size = ImGui.get_item_rect()
                    header_hovered, header_clicked = self._condition_drag_handle_state.get(id(condition), (False, False))
                    in_rect = ImGui.is_mouse_in_rect((item_min[0], item_min[1], item_size[0], item_size[1]))
                    
                    if self._drag_condition is None and header_clicked and header_hovered:
                        self._begin_condition_drag(rule, condition, index)
                        active_drag = True

                    if self._drag_condition_source_rule is rule and self._drag_condition is not None:
                        condition_rects[index] = (item_min[0], item_min[1], item_max[0], item_max[1])
                        if index > 0 and (index - 1) in condition_rects:
                            previous_rect = condition_rects[index - 1]
                            gap = item_min[1] - previous_rect[3]
                            if gap > 0.0:
                                condition_gap_values.append(gap)

                        if in_rect:
                            self._drag_condition_target_index = index
                            self._drag_condition_target_after = io.mouse_pos_y >= ((item_min[1] + item_max[1]) / 2.0)

                if active_drag:
                    edge_threshold = 18.0
                    scroll_y = PyImGui.get_scroll_y()
                    scroll_max_y = PyImGui.get_scroll_max_y()
                    mouse_y = io.mouse_pos_y

                    if mouse_y < child_visible_top and scroll_y > 0.0:
                        overshoot = min(child_visible_top - mouse_y, 40.0)
                        scroll_step = 6.0 + (overshoot / 40.0) * 18.0
                        PyImGui.set_scroll_y(max(0.0, scroll_y - scroll_step))
                    elif mouse_y > child_visible_bottom and scroll_y < scroll_max_y:
                        overshoot = min(mouse_y - child_visible_bottom, 40.0)
                        scroll_step = 6.0 + (overshoot / 40.0) * 18.0
                        PyImGui.set_scroll_y(min(scroll_max_y, scroll_y + scroll_step))

                    if condition_rects:
                        if mouse_y <= child_visible_top + edge_threshold:
                            self._drag_condition_target_index = min(condition_rects.keys())
                            self._drag_condition_target_after = False
                        elif mouse_y >= child_visible_bottom - edge_threshold:
                            self._drag_condition_target_index = max(condition_rects.keys())
                            self._drag_condition_target_after = True

                    if self._drag_condition_target_index in condition_rects:
                        current_rect = condition_rects[self._drag_condition_target_index]
                        usual_gap = condition_gap_values[0] if condition_gap_values else 10.0
                        x1 = max(current_rect[0] + 4, child_visible_left + 4)
                        x2 = min(current_rect[2] - 4, child_visible_right - 4)
                        can_draw_target_rect = True
                        line_y = 0.0
                        if self._drag_condition_target_after:
                            if self._drag_condition_target_index + 1 in condition_rects:
                                next_rect = condition_rects[self._drag_condition_target_index + 1]
                                line_y = (current_rect[3] + next_rect[1]) / 2.0
                            else:
                                if current_rect[3] < child_visible_bottom:
                                    bottom_gap = child_visible_bottom - current_rect[3]
                                    effective_gap = min(bottom_gap, usual_gap)
                                    line_y = current_rect[3] + (effective_gap / 2.0)
                                else:
                                    can_draw_target_rect = False
                        else:
                            if self._drag_condition_target_index - 1 in condition_rects:
                                previous_rect = condition_rects[self._drag_condition_target_index - 1]
                                line_y = (previous_rect[3] + current_rect[1]) / 2.0
                            else:
                                scroll_y = PyImGui.get_scroll_y()
                                if current_rect[1] > child_visible_top:
                                    line_y = (child_visible_top + current_rect[1]) / 2.0
                                elif scroll_y <= 0.0:
                                    top_gap = max(current_rect[1] - child_visible_top, 0.0)
                                    effective_gap = min(top_gap if top_gap > 0.0 else usual_gap, usual_gap)
                                    line_y = child_visible_top + max(effective_gap / 2.0, 1.0)
                                else:
                                    can_draw_target_rect = False

                        rect_y1 = max(line_y - 1, child_visible_top) if can_draw_target_rect else 0.0
                        rect_y2 = min(line_y + 1, child_visible_bottom) if can_draw_target_rect else 0.0
                        if can_draw_target_rect and x1 < x2 and rect_y1 < rect_y2:
                            self._drag_condition_target_rect = (x1, rect_y1, x2, rect_y2)
                        else:
                            self._drag_condition_target_rect = None
                    else:
                        self._drag_condition_target_rect = None
        ImGui.end_child()

        if active_drag and not PyImGui.is_mouse_down(0):
            changed = self._apply_condition_drag(rule) or changed
        
        return changed

    def _draw_rule_body(self, rule: BaseRule) -> bool:
        PyImGui.spacing()
        
        match rule:
            case CustomRule():
                ImGui.text_wrapped("Build this rule from reusable condition sections. Add any supported conditions, reorder the rule itself in the list, and choose whether all or any conditions must match.")
                return self._draw_custom_rule(rule)

            case NickItemRule():
                ImGui.text_wrapped("This rule matches Nicholas the Traveler items that come up within the configured number of weeks, and previews the affected cycle items.")
                return UI.ConditionEditor.ForNickItemCondition(self, rule, rule.condition)
            
            case DyesRule():
                ImGui.text_wrapped("This rule matches items based on their dye color. You can specify one or more dye colors to match against the item.")
                return UI.ConditionEditor.ForDyeColorsCondition(self, rule, rule.condition)

            case ArmorUpgradeRule():
                ImGui.text_wrapped("This rule matches items based on their armor upgrades. You can specify one or more armor upgrades to match against the item.")
                changed = self.draw_extracted_action(rule)
                return UI.ConditionEditor.ForArmorUpgradesCondition(self, rule, rule.condition) or changed

            case WeaponUpgradeRule():
                ImGui.text_wrapped("This rule matches items based on their weapon upgrades. You can specify one or more weapon upgrades to match against the item.")
                changed = self.draw_extracted_action(rule) 
                return UI.ConditionEditor.ForMaxWeaponUpgradesCondition(self, rule, rule.condition) or changed

            case CustomWeaponUpgradeRule():
                ImGui.text_wrapped("This rule matches items based on their upgrades that have a numeric value within a specified range.")
                changed = self.draw_extracted_action(rule)
                return UI.ConditionEditor.ForUpgradeRangesCondition(self, rule, rule.condition) or changed

            case _:
                ImGui.text_wrapped("This rule type is no longer supported by the editor. Create a Custom Rule Preset instead for new rules.")
                return False

    def draw_extracted_action(self, rule : ArmorUpgradeRule | WeaponUpgradeRule | CustomWeaponUpgradeRule) -> bool:
        changed = False
        style = ImGui.get_style()
        unset = rule.extracted_action == ItemAction.NONE
        if unset:
            style.FrameBg.push_color_direct((229, 62, 48, 200))
            style.FrameBgHovered.push_color_direct((231, 95, 81, 200))

        PyImGui.set_next_item_width(-1)
        open = PyImGui.begin_combo(f"##rule_extracted_action_{id(rule)}", UI._humanize_name(rule.extracted_action.name)  if rule.extracted_action != ItemAction.NONE else "Select an action", PyImGui.ImGuiComboFlags.NoFlag)

        if unset:
            style.FrameBg.pop_color_direct()
            style.FrameBgHovered.pop_color_direct()

        if open:
            sorted_actions = sorted(ItemAction, key=lambda action: action.name)
            for action in sorted_actions:
                if ImGui.selectable(UI._humanize_name(action.name), selected=rule.extracted_action == action):
                    rule.extracted_action = action
                    changed = True
            ImGui.end_combo()
        ImGui.show_tooltip("The action to perform on the upgrade once extracted.")
        
        return changed

    def draw_rule(self, rule: BaseRule):
        self._draw_rule_header(rule)
        if self._draw_rule_body(rule):
            self._save_active_config()
