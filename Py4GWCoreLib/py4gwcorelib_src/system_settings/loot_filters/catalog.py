"""The item catalog -- shipped reference data.

**Package data**: versioned with the code, never written at runtime. It is deliberately NOT in the
JSON store -- `.gitignore` excludes `json/**` entirely, so a catalog kept there is absent from a fresh
clone, and `JsonFactory` seeds from Defaults only when a document does not already exist, so an empty
runtime copy can never self-heal. That failure emptied the catalog twice.

**Vocabulary**: a **category** contains **groups**. (The legacy data called these `group` and
`subgroup`.) Only meaningful distinctions are groups -- Materials -> Common / Rare, Keys -> the four
campaigns. **Trophies has no groups**: its A...W split was alphabetical indexing, which is a rendering
concern and is banded at draw time instead.

Every `model_id` here is real. 373 came from the `ModelID` enum; 14 were recovered by name from the
bundled item metadata after their enum entries proved missing or held placeholder values (ids far
outside the valid range, e.g. `1236547896911`). The 16 that could not be resolved are in
:data:`UNRESOLVED` -- surfaced as defects, never shipped as rows that look functional but can never
match.
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import unquote

_ATTRIBUTE_LABEL_FALLBACK: dict[int, str] = {}

try:
    from Py4GWCoreLib.enums_src.GameData_enums import Attribute
    from Py4GWCoreLib.enums_src.GameData_enums import AttributeNames
except ModuleNotFoundError:
    try:
        from Py4GWCoreLib.enums import Attribute
        from Py4GWCoreLib.enums import AttributeNames
    except ImportError:
        from Py4GWCoreLib.enums import Attribute

        AttributeNames: Any = {}
        _ATTRIBUTE_LABEL_FALLBACK = {
            0: 'Fast Casting',
            1: 'Illusion Magic',
            2: 'Domination Magic',
            3: 'Inspiration Magic',
            4: 'Blood Magic',
            5: 'Death Magic',
            6: 'Soul Reaping',
            7: 'Curses',
            8: 'Air Magic',
            9: 'Earth Magic',
            10: 'Fire Magic',
            11: 'Water Magic',
            12: 'Energy Storage',
            13: 'Healing Prayers',
            14: 'Smiting Prayers',
            15: 'Protection Prayers',
            16: 'Divine Favor',
            17: 'Strength',
            18: 'Axe Mastery',
            19: 'Hammer Mastery',
            20: 'Swordsmanship',
            21: 'Tactics',
            22: 'Beast Mastery',
            23: 'Expertise',
            24: 'Wilderness Survival',
            25: 'Marksmanship',
            29: 'Dagger Mastery',
            30: 'Deadly Arts',
            31: 'Shadow Arts',
            32: 'Communing',
            33: 'Restoration Magic',
            34: 'Channeling Magic',
            35: 'Critical Strikes',
            36: 'Spawning Power',
            37: 'Spear Mastery',
            38: 'Command',
            39: 'Motivation',
            40: 'Leadership',
            41: 'Scythe Mastery',
            42: 'Wind Prayers',
            43: 'Earth Prayers',
            44: 'Mysticism',
        }

from Py4GWCoreLib.enums_src.Model_enums import ModelID


@dataclass(frozen=True)
class CatalogEntry:
    """One shipped item. ``group`` is empty for categories that have no second level."""

    name: str
    model_id: int
    category: str
    group: str
    item_type: str = ''
    material_type: str = ''
    source: str = ''
    priority: int = 100
    alias_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnresolvedEntry:
    """A real item whose model id is unknown to every bundled source. A visible defect."""

    name: str
    category: str


CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry('Bottle Of Rice Wine', 15477, 'Alcohol', '1 Points'),
    CatalogEntry('Bottle Of Vabbian Wine', 19173, 'Alcohol', '1 Points'),
    CatalogEntry('Dwarven Ale', 5585, 'Alcohol', '1 Points'),
    CatalogEntry('Eggnog', 6375, 'Alcohol', '1 Points'),
    CatalogEntry('Hard Apple Cider', 28435, 'Alcohol', '1 Points'),
    CatalogEntry('Hunters Ale', 910, 'Alcohol', '1 Points'),
    CatalogEntry('Shamrock Ale', 22190, 'Alcohol', '1 Points'),
    CatalogEntry('Vial Of Absinthe', 6367, 'Alcohol', '1 Points'),
    CatalogEntry('Witchs Brew', 6049, 'Alcohol', '1 Points'),
    CatalogEntry('Zehtukas Jug', 19171, 'Alcohol', '1 Points'),
    CatalogEntry('Aged Dwarven Ale', 24593, 'Alcohol', '3 Points'),
    CatalogEntry('Bottle Of Grog', 30855, 'Alcohol', '3 Points'),
    CatalogEntry('Krytan Brandy', 35124, 'Alcohol', '3 Points'),
    CatalogEntry('Spiked Eggnog', 6366, 'Alcohol', '3 Points'),
    CatalogEntry('Battle Isle Iced Tea', 36682, 'Alcohol', '50 Points'),
    CatalogEntry('Fruitcake', 21492, 'Sweets', '1 Points'),
    CatalogEntry('Golden Egg', 22752, 'Sweets', '1 Points'),
    CatalogEntry('Sugary Blue Drink', 21812, 'Sweets', '1 Points'),
    CatalogEntry('Honeycomb', 26784, 'Sweets', '1 Points'),
    CatalogEntry('Slice Of Pumpkin Pie', 28436, 'Sweets', '1 Points'),
    CatalogEntry('Wintergreen Cc', 21488, 'Sweets', '1 Points'),
    CatalogEntry('Rainbow Cc', 21489, 'Sweets', '1 Points'),
    CatalogEntry('Peppermint Cc', 6370, 'Sweets', '2 Points'),
    CatalogEntry('Birthday Cupcake', 22269, 'Sweets', '2 Points'),
    CatalogEntry('Chocolate Bunny', 22644, 'Sweets', '2 Points'),
    CatalogEntry('Red Bean Cake', 15479, 'Sweets', '2 Points'),
    CatalogEntry('Creme Brulee', 15528, 'Sweets', '2 Points'),
    CatalogEntry('Delicious Cake', 36681, 'Sweets', '50 Points'),
    CatalogEntry('Bottle Rocket', 21809, 'Party', '1 Points'),
    CatalogEntry('Champagne Popper', 21810, 'Party', '1 Points'),
    CatalogEntry('Sparkler', 21813, 'Party', '1 Points'),
    CatalogEntry('Snowman Summoner', 6376, 'Party', '1 Points'),
    CatalogEntry('El Mischievious Tonic', 31021, 'Party', '2 Points'),
    CatalogEntry('El Yuletide Tonic', 29241, 'Party', '2 Points'),
    CatalogEntry('Party Beacon', 36683, 'Party', '50 Points'),
    CatalogEntry('Four Leaf Clover', 22191, 'Death Penalty Removal', 'Lucky Points'),
    CatalogEntry('Scroll Of Hunters Insight', 5976, 'Scrolls', 'Common XP Scrolls'),
    CatalogEntry('Scroll Of Rampagers Insight', 5975, 'Scrolls', 'Common XP Scrolls'),
    CatalogEntry('Scroll Of Adventurers Insight', 5853, 'Scrolls', 'Common XP Scrolls'),
    CatalogEntry('Scroll Of Heros Insight', 5594, 'Scrolls', 'Rare XP Scrolls'),
    CatalogEntry('Slayers Insight Scroll', 5611, 'Scrolls', 'Rare XP Scrolls'),
    CatalogEntry('Scroll Of Berserkers Insight', 5595, 'Scrolls', 'Rare XP Scrolls'),
    CatalogEntry('Passage Scroll Deep', 22279, 'Scrolls', 'Passage Scrolls'),
    CatalogEntry('Passage Scroll Fow', 22280, 'Scrolls', 'Passage Scrolls'),
    CatalogEntry('Passage Scroll Urgoz', 3256, 'Scrolls', 'Passage Scrolls'),
    CatalogEntry('Passage Scroll Uw', 3746, 'Scrolls', 'Passage Scrolls'),
    CatalogEntry('Assassin Tome', 21796, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Dervish Tome', 21803, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Elementalist Tome', 21799, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Mesmer Tome', 21797, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Monk Tome', 21800, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Necromancer Tome', 21798, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Paragon Tome', 21805, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Ranger Tome', 21802, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Ritualist Tome', 21804, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Warrior Tome', 21801, 'Tomes', 'Normal Tomes'),
    CatalogEntry('Assassin Elitetome', 21786, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Dervish Elitetome', 21793, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Elementalist Elitetome', 21789, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Mesmer Elitetome', 21787, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Monk Elitetome', 21790, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Necromancer Elitetome', 21788, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Paragon Elitetome', 21795, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Ranger Elitetome', 21792, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Ritualist Elitetome', 21794, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Warrior Elitetome', 21791, 'Tomes', 'Elite Tomes'),
    CatalogEntry('Lockpick', 22751, 'Keys', 'Core Keys'),
    CatalogEntry('Phantom Key', 5882, 'Keys', 'Core Keys'),
    CatalogEntry('Obsidian Key', 5971, 'Keys', 'Core Keys'),
    CatalogEntry('Ascalonian Key', 5966, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Steel Key', 5967, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Krytan Key', 5964, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Maguuma Key', 5965, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Elonian Key', 5960, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Shiverpeak Key', 5962, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Darkstone Key', 5963, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Miners Key', 5961, 'Keys', 'Prophecies Keys'),
    CatalogEntry('Shing Jea Key', 6537, 'Keys', 'Factions Keys'),
    CatalogEntry('Canthan Key', 6540, 'Keys', 'Factions Keys'),
    CatalogEntry('Kurzick Key', 6535, 'Keys', 'Factions Keys'),
    CatalogEntry('Stoneroot Key', 6536, 'Keys', 'Factions Keys'),
    CatalogEntry('Luxon Key', 6538, 'Keys', 'Factions Keys'),
    CatalogEntry('Deep Jade Key', 6539, 'Keys', 'Factions Keys'),
    CatalogEntry('Forbidden Key', 6534, 'Keys', 'Factions Keys'),
    CatalogEntry('Istani Key', 15557, 'Keys', 'Nightfall Keys'),
    CatalogEntry('Kournan Key', 15559, 'Keys', 'Nightfall Keys'),
    CatalogEntry('Vabbian Key', 15558, 'Keys', 'Nightfall Keys'),
    CatalogEntry('Ancient Elonian Key', 15556, 'Keys', 'Nightfall Keys'),
    CatalogEntry('Margonite Key', 15560, 'Keys', 'Nightfall Keys'),
    CatalogEntry('Demonic Key', 19174, 'Keys', 'Nightfall Keys'),
    CatalogEntry('Bolt Of Cloth', 925, 'Materials', 'Common Materials'),
    CatalogEntry('Bone', 921, 'Materials', 'Common Materials'),
    CatalogEntry('Chitin Fragment', 954, 'Materials', 'Common Materials'),
    CatalogEntry('Feather', 933, 'Materials', 'Common Materials'),
    CatalogEntry('Granite Slab', 955, 'Materials', 'Common Materials'),
    CatalogEntry('Iron Ingot', 948, 'Materials', 'Common Materials'),
    CatalogEntry('Pile Of Glittering Dust', 929, 'Materials', 'Common Materials'),
    CatalogEntry('Plant Fiber', 934, 'Materials', 'Common Materials'),
    CatalogEntry('Scale', 953, 'Materials', 'Common Materials'),
    CatalogEntry('Tanned Hide Square', 940, 'Materials', 'Common Materials'),
    CatalogEntry('Wood Plank', 946, 'Materials', 'Common Materials'),
    CatalogEntry('Amber Chunk', 6532, 'Materials', 'Rare Materials'),
    CatalogEntry('Bolt Of Damask', 927, 'Materials', 'Rare Materials'),
    CatalogEntry('Bolt Of Linen', 926, 'Materials', 'Rare Materials'),
    CatalogEntry('Bolt Of Silk', 928, 'Materials', 'Rare Materials'),
    CatalogEntry('Deldrimor Steel Ingot', 950, 'Materials', 'Rare Materials'),
    CatalogEntry('Diamond', 935, 'Materials', 'Rare Materials'),
    CatalogEntry('Elonian Leather Square', 943, 'Materials', 'Rare Materials'),
    CatalogEntry('Fur Square', 941, 'Materials', 'Rare Materials'),
    CatalogEntry('Glob Of Ectoplasm', 930, 'Materials', 'Rare Materials'),
    CatalogEntry('Jadeite Shard', 6533, 'Materials', 'Rare Materials'),
    CatalogEntry('Leather Square', 942, 'Materials', 'Rare Materials'),
    CatalogEntry('Lump Of Charcoal', 922, 'Materials', 'Rare Materials'),
    CatalogEntry('Monstrous Claw', 923, 'Materials', 'Rare Materials'),
    CatalogEntry('Monstrous Eye', 931, 'Materials', 'Rare Materials'),
    CatalogEntry('Monstrous Fang', 932, 'Materials', 'Rare Materials'),
    CatalogEntry('Obsidian Shard', 945, 'Materials', 'Rare Materials'),
    CatalogEntry('Onyx Gemstone', 936, 'Materials', 'Rare Materials'),
    CatalogEntry('Roll Of Parchment', 951, 'Materials', 'Rare Materials'),
    CatalogEntry('Roll Of Vellum', 952, 'Materials', 'Rare Materials'),
    CatalogEntry('Ruby', 937, 'Materials', 'Rare Materials'),
    CatalogEntry('Sapphire', 938, 'Materials', 'Rare Materials'),
    CatalogEntry('Spiritwood Plank', 956, 'Materials', 'Rare Materials'),
    CatalogEntry('Steel Ingot', 949, 'Materials', 'Rare Materials'),
    CatalogEntry('Tempered Glass Vial', 939, 'Materials', 'Rare Materials'),
    CatalogEntry('Vial Of Ink', 944, 'Materials', 'Rare Materials'),
    CatalogEntry('Abnormal Seed', 442, 'Trophies', ''),
    CatalogEntry('Alpine Seed', 497, 'Trophies', ''),
    CatalogEntry('Amphibian Tongue', 27036, 'Trophies', ''),
    CatalogEntry('Ancient Eye', 464, 'Trophies', ''),
    CatalogEntry('Ancient Kappa Shell', 856, 'Trophies', ''),
    CatalogEntry('Archaic Kappa Shell', 850, 'Trophies', ''),
    CatalogEntry('Ashen Wurm Husk', 27059, 'Trophies', ''),
    CatalogEntry('Augmented Flesh', 826, 'Trophies', ''),
    CatalogEntry('Azure Crest', 844, 'Trophies', ''),
    CatalogEntry('Azure Remains', 496, 'Trophies', ''),
    CatalogEntry('Baked Husk', 433, 'Trophies', ''),
    CatalogEntry('Beetle Egg', 27066, 'Trophies', ''),
    CatalogEntry('Behemoth Hide', 1675, 'Trophies', ''),
    CatalogEntry('Behemoth Jaw', 465, 'Trophies', ''),
    CatalogEntry('Berserker Horn', 27046, 'Trophies', ''),
    CatalogEntry('Black Pearl', 841, 'Trophies', ''),
    CatalogEntry('Bleached Carapace', 449, 'Trophies', ''),
    CatalogEntry('Blob Of Ooze', 27067, 'Trophies', ''),
    CatalogEntry('Blood Drinker Pelt', 812, 'Trophies', ''),
    CatalogEntry('Bog Skale Fin', 443, 'Trophies', ''),
    CatalogEntry('Bone Charm', 811, 'Trophies', ''),
    CatalogEntry('Branch of Juni Berries', 19194, 'Trophies', ''),
    CatalogEntry('Bull Trainer Giant Jawbone', 1680, 'Trophies', ''),
    CatalogEntry('Celestial Essence', 855, 'Trophies', ''),
    CatalogEntry('Charr Carving', 423, 'Trophies', ''),
    CatalogEntry('Chromatic Scale', 27069, 'Trophies', ''),
    CatalogEntry('Chunk Of Drake Flesh', 19185, 'Trophies', ''),
    CatalogEntry('Cobalt Talon', 1609, 'Trophies', ''),
    CatalogEntry('Copper Crimson Skull Coin', 806, 'Trophies', ''),
    CatalogEntry('Copper Shilling', 1577, 'Trophies', ''),
    CatalogEntry('Corrosive Spider Leg', 518, 'Trophies', ''),
    CatalogEntry('Curved Mintaur Horn', 495, 'Trophies', ''),
    CatalogEntry('Dark Claw', 528, 'Trophies', ''),
    CatalogEntry('Dark Remains', 522, 'Trophies', ''),
    CatalogEntry('Decayed Orr Emblem', 504, 'Trophies', ''),
    CatalogEntry('Demonic Fang', 473, 'Trophies', ''),
    CatalogEntry('Demonic Relic', 1580, 'Trophies', ''),
    CatalogEntry('Demonic Remains', 476, 'Trophies', ''),
    CatalogEntry('Dessicated Hydra Claw', 454, 'Trophies', ''),
    CatalogEntry('Destroyer Core', 27033, 'Trophies', ''),
    CatalogEntry('Diamond Djinn Essence', 19186, 'Trophies', ''),
    CatalogEntry('Diessa Chalice', 24353, 'Trophies', ''),
    CatalogEntry('Dragon Root', 819, 'Trophies', ''),
    CatalogEntry('Dregde Charm', 27064, 'Trophies', ''),
    CatalogEntry('Dredge Incisor', 818, 'Trophies', ''),
    CatalogEntry('Dryder Web', 27070, 'Trophies', ''),
    CatalogEntry('Dull Carapace', 425, 'Trophies', ''),
    CatalogEntry('Dune Burrower Jaw', 447, 'Trophies', ''),
    CatalogEntry('Dusty Insect Carapace', 1588, 'Trophies', ''),
    CatalogEntry('Ebon Spider Leg', 463, 'Trophies', ''),
    CatalogEntry('Elder Kappa Shell', 837, 'Trophies', ''),
    CatalogEntry('Enchanted Lodestone', 431, 'Trophies', ''),
    CatalogEntry('Enchanted Vine', 834, 'Trophies', ''),
    CatalogEntry('Encrusted Lodestone', 451, 'Trophies', ''),
    CatalogEntry('Enslavement Stone', 532, 'Trophies', ''),
    CatalogEntry('Feathered Avicara Scalp', 498, 'Trophies', ''),
    CatalogEntry('Feathered Caromi Scalp', 444, 'Trophies', ''),
    CatalogEntry('Feathered Crest', 835, 'Trophies', ''),
    CatalogEntry('Feathered Scalp', 836, 'Trophies', ''),
    CatalogEntry('Fetid Carapace', 479, 'Trophies', ''),
    CatalogEntry('Fetid Mass', 1665, 'Trophies', ''),
    CatalogEntry('Fibrous Mandragor Root', 27051, 'Trophies', ''),
    CatalogEntry('Fiery Crest', 508, 'Trophies', ''),
    CatalogEntry('Fledglin Skree Wing', 1596, 'Trophies', ''),
    CatalogEntry('Flesh Reaver Morsel', 27062, 'Trophies', ''),
    CatalogEntry('Forest Minotaur Horn', 440, 'Trophies', ''),
    CatalogEntry('Forgotten Seal', 459, 'Trophies', ''),
    CatalogEntry('Forgotten Trinket Box', 825, 'Trophies', ''),
    CatalogEntry('Frigid Heart', 494, 'Trophies', ''),
    CatalogEntry('Frigid Mandragor Husk', 27042, 'Trophies', ''),
    CatalogEntry('Frosted Griffon Wing', 493, 'Trophies', ''),
    CatalogEntry('Frostfire Fang', 489, 'Trophies', ''),
    CatalogEntry('Frozen Wurm Husk', 27048, 'Trophies', ''),
    CatalogEntry('Fungal Root', 27061, 'Trophies', ''),
    CatalogEntry('Gargoyle Skull', 426, 'Trophies', ''),
    CatalogEntry('Geode', 1681, 'Trophies', ''),
    CatalogEntry('Giant Tusk', 1590, 'Trophies', ''),
    CatalogEntry('Glacial Stone', 27047, 'Trophies', ''),
    CatalogEntry('Gloom Seed', 523, 'Trophies', ''),
    CatalogEntry('Glowing Heart', 439, 'Trophies', ''),
    CatalogEntry('Gold Crimson Skull Coin', 807, 'Trophies', ''),
    CatalogEntry('Gold Doubloon', 1578, 'Trophies', ''),
    CatalogEntry('Golden Rin Relic', 24354, 'Trophies', ''),
    CatalogEntry('Golem Runestone', 27065, 'Trophies', ''),
    CatalogEntry('Grawl Necklace', 432, 'Trophies', ''),
    CatalogEntry('Gruesome Ribcage', 482, 'Trophies', ''),
    CatalogEntry('Gruesome Sternum', 475, 'Trophies', ''),
    CatalogEntry('Guardian Moss', 849, 'Trophies', ''),
    CatalogEntry('Hardened Hump', 435, 'Trophies', ''),
    CatalogEntry('Heket Tongue', 19199, 'Trophies', ''),
    CatalogEntry('Huge Jawbone', 492, 'Trophies', ''),
    CatalogEntry('Hunting Minotaur Horn', 1682, 'Trophies', ''),
    CatalogEntry('Iboga Petal', 19183, 'Trophies', ''),
    CatalogEntry('Icy Hump', 490, 'Trophies', ''),
    CatalogEntry('Icy Lodestone', 424, 'Trophies', ''),
    CatalogEntry('Igneous Hump', 510, 'Trophies', ''),
    CatalogEntry('Igneous Spider Leg', 505, 'Trophies', ''),
    CatalogEntry('Immolated Djinn Essence', 1620, 'Trophies', ''),
    CatalogEntry('Incubus Wing', 27034, 'Trophies', ''),
    CatalogEntry('Inscribed Shard', 1587, 'Trophies', ''),
    CatalogEntry('Insect Appendage', 1597, 'Trophies', ''),
    CatalogEntry('Insect Carapace', 1617, 'Trophies', ''),
    CatalogEntry('Intricate Grawl Necklace', 499, 'Trophies', ''),
    CatalogEntry('Iridescant Griffon Wing', 453, 'Trophies', ''),
    CatalogEntry('Ivory Troll Tusk', 445, 'Trophies', ''),
    CatalogEntry('Jade Bracelet', 809, 'Trophies', ''),
    CatalogEntry('Jade Mandible', 457, 'Trophies', ''),
    CatalogEntry('Jade Orb', 15940, 'Trophies', ''),
    CatalogEntry('Jotun Pelt', 27045, 'Trophies', ''),
    CatalogEntry('Jungle Skale Fin', 470, 'Trophies', ''),
    CatalogEntry('Jungle Troll Tusk', 471, 'Trophies', ''),
    CatalogEntry('Juvenile Termite Leg', 1598, 'Trophies', ''),
    CatalogEntry('Kappa Hatchling Shell', 838, 'Trophies', ''),
    CatalogEntry('Kappa Shell', 839, 'Trophies', ''),
    CatalogEntry('Keen Oni Talon', 847, 'Trophies', ''),
    CatalogEntry('Kirin Horn', 846, 'Trophies', ''),
    CatalogEntry('Kournan Pendant', 1582, 'Trophies', ''),
    CatalogEntry('Krait Skin', 27729, 'Trophies', ''),
    CatalogEntry('Kraken Eye', 843, 'Trophies', ''),
    CatalogEntry('Kurzick Bauble', 604, 'Trophies', ''),
    CatalogEntry('Lavastrider Appendage', 27058, 'Trophies', ''),
    CatalogEntry('Leathery Claw', 484, 'Trophies', ''),
    CatalogEntry('Losaru Mane', 448, 'Trophies', ''),
    CatalogEntry('Luminous Stone', 1660, 'Trophies', ''),
    CatalogEntry('Lustrous Stone', 1661, 'Trophies', ''),
    CatalogEntry('Luxon Pendant', 810, 'Trophies', ''),
    CatalogEntry('Maguuma Mane', 466, 'Trophies', ''),
    CatalogEntry('Mahgo Claw', 513, 'Trophies', ''),
    CatalogEntry('Maguuma Spider Web', 234, 'Trophies', ''),
    CatalogEntry('Mandragor Husk', 1668, 'Trophies', ''),
    CatalogEntry('Mandragor Root', 1686, 'Trophies', ''),
    CatalogEntry('Mandragor Swamproot', 1671, 'Trophies', ''),
    CatalogEntry('Mantid Pincer', 815, 'Trophies', ''),
    CatalogEntry('Mantid Ungula', 27054, 'Trophies', ''),
    CatalogEntry('Mantis Pincer', 829, 'Trophies', ''),
    CatalogEntry('Margonite Mask', 1581, 'Trophies', ''),
    CatalogEntry('Massive Jawbone', 452, 'Trophies', ''),
    CatalogEntry('Mergoyle Skull', 436, 'Trophies', ''),
    CatalogEntry('Minotaur Horn', 455, 'Trophies', ''),
    CatalogEntry('Modnir Mane', 27043, 'Trophies', ''),
    CatalogEntry('Molten Claw', 503, 'Trophies', ''),
    CatalogEntry('Molten Eye', 506, 'Trophies', ''),
    CatalogEntry('Molten Heart', 514, 'Trophies', ''),
    CatalogEntry('Mossy Mandible', 469, 'Trophies', ''),
    CatalogEntry('Mountain Root', 27049, 'Trophies', ''),
    CatalogEntry('Mountain Troll Tusk', 500, 'Trophies', ''),
    CatalogEntry('Moon Shell', 1009, 'Trophies', ''),
    CatalogEntry('Mummy Wrapping', 1583, 'Trophies', ''),
    CatalogEntry('Mursaat Token', 462, 'Trophies', ''),
    CatalogEntry('Naga Hide', 832, 'Trophies', ''),
    CatalogEntry('Naga Pelt', 833, 'Trophies', ''),
    CatalogEntry('Naga Skin', 848, 'Trophies', ''),
    CatalogEntry('Obsidian Burrower Jaw', 472, 'Trophies', ''),
    CatalogEntry('Oni Claw', 817, 'Trophies', ''),
    CatalogEntry('Oni Taloon', 831, 'Trophies', ''),
    CatalogEntry('Ornate Grawl Necklace', 487, 'Trophies', ''),
    CatalogEntry('Patch Of Simian Fur', 27038, 'Trophies', ''),
    CatalogEntry('Phantom Residue', 474, 'Trophies', ''),
    CatalogEntry('Pile Of Elemental Dust', 27050, 'Trophies', ''),
    CatalogEntry('Plague Idol', 805, 'Trophies', ''),
    CatalogEntry('Pulsating Growth', 824, 'Trophies', ''),
    CatalogEntry('Putrid Cyst', 827, 'Trophies', ''),
    CatalogEntry('Quetzal Crest', 27039, 'Trophies', ''),
    CatalogEntry('Rawhide Belt', 483, 'Trophies', ''),
    CatalogEntry('Red Iris Flower', 2994, 'Trophies', ''),
    CatalogEntry('Roaring Ether Claw', 1629, 'Trophies', ''),
    CatalogEntry('Rot Wallow Tusk', 842, 'Trophies', ''),
    CatalogEntry('Ruby Djinn Essence', 19187, 'Trophies', ''),
    CatalogEntry('Saurian Bone', 27035, 'Trophies', ''),
    CatalogEntry('Sentient Lodestone', 1619, 'Trophies', ''),
    CatalogEntry('Sentient Seed', 1601, 'Trophies', ''),
    CatalogEntry('Sentient Spore', 19198, 'Trophies', ''),
    CatalogEntry('Sentient Vine', 27041, 'Trophies', ''),
    CatalogEntry('Shadowy Husk', 526, 'Trophies', ''),
    CatalogEntry('Shadowy Remnants', 441, 'Trophies', ''),
    CatalogEntry('Shiverpeak Mane', 488, 'Trophies', ''),
    CatalogEntry('Shimmering Scale', 2566, 'Trophies', ''),
    CatalogEntry('Shriveled Eye', 446, 'Trophies', ''),
    CatalogEntry('Silver Bullion Coin', 1579, 'Trophies', ''),
    CatalogEntry('Silver Crimson Skull Coin', 808, 'Trophies', ''),
    CatalogEntry('Singed Gargoyle Skull', 480, 'Trophies', ''),
    CatalogEntry('Skale Claw', 1604, 'Trophies', ''),
    CatalogEntry('Skale Fang', 27055, 'Trophies', ''),
    CatalogEntry('Skale Fin', 19184, 'Trophies', ''),
    CatalogEntry('Skale Fin (pre-Searing)', 429, 'Trophies', ''),
    CatalogEntry('Skale Tooth', 1603, 'Trophies', ''),
    CatalogEntry('Skeletal Limb', 430, 'Trophies', ''),
    CatalogEntry('Skeleton Bone', 1605, 'Trophies', ''),
    CatalogEntry('Skelk Claw', 27040, 'Trophies', ''),
    CatalogEntry('Skelk Fang', 27060, 'Trophies', ''),
    CatalogEntry('Skree Wing', 1610, 'Trophies', ''),
    CatalogEntry('Skull Juju', 814, 'Trophies', ''),
    CatalogEntry('Soul Stone', 852, 'Trophies', ''),
    CatalogEntry('Spider Leg', 422, 'Trophies', ''),
    CatalogEntry('Spider Web', 224, 'Trophies', ''),
    CatalogEntry('Spiked Crest', 434, 'Trophies', ''),
    CatalogEntry('Stolen Provisions', 851, 'Trophies', ''),
    CatalogEntry('Stolen Shipment', 1424, 'Trophies', ''),
    CatalogEntry('Stolen Supplies', 37937, 'Trophies', ''),
    CatalogEntry('Stone Carving', 820, 'Trophies', ''),
    CatalogEntry('Stone Claw', 27057, 'Trophies', ''),
    CatalogEntry('Stone Grawl Necklace', 27053, 'Trophies', ''),
    CatalogEntry('Stone Horn', 816, 'Trophies', ''),
    CatalogEntry('Stone Summit Badge', 502, 'Trophies', ''),
    CatalogEntry('Stone Summit Emblem', 27044, 'Trophies', ''),
    CatalogEntry('Stormy Eye', 477, 'Trophies', ''),
    CatalogEntry('Superb Charr Carving', 27052, 'Trophies', ''),
    CatalogEntry('Tangled Seed', 468, 'Trophies', ''),
    CatalogEntry('Thorny Carapace', 467, 'Trophies', ''),
    CatalogEntry('Topaz Crest', 450, 'Trophies', ''),
    CatalogEntry('Truffle', 813, 'Trophies', ''),
    CatalogEntry('Umbral Eye', 519, 'Trophies', ''),
    CatalogEntry('Umbral Shell', 527, 'Trophies', ''),
    CatalogEntry('Umbral Skeletal Limb', 525, 'Trophies', ''),
    CatalogEntry('Unctuous Remains', 511, 'Trophies', ''),
    CatalogEntry('Undead Bone', 27974, 'Trophies', ''),
    CatalogEntry('Unnatural Seed', 428, 'Trophies', ''),
    CatalogEntry('Vaettir Essence', 27071, 'Trophies', ''),
    CatalogEntry('Venerable Mantid Pincer', 854, 'Trophies', ''),
    CatalogEntry('Vermin Hide', 853, 'Trophies', ''),
    CatalogEntry('War Supplies', 35121, 'Trophies', ''),
    CatalogEntry('Warden Horn', 822, 'Trophies', ''),
    CatalogEntry('Water Djinn Essence', 19189, 'Trophies', ''),
    CatalogEntry('Weaver Leg', 27037, 'Trophies', ''),
    CatalogEntry('White Mantle Badge', 461, 'Trophies', ''),
    CatalogEntry('White Mantle Emblem', 460, 'Trophies', ''),
    CatalogEntry('Worn Belt', 427, 'Trophies', ''),
    CatalogEntry('Confessors Orders', 35123, 'Reward Trophies', 'Prophecies'),
    CatalogEntry('Torment Gemstone', 21131, 'Reward Trophies', 'Nightfall'),
    CatalogEntry('Margonite Gemstone', 21128, 'Reward Trophies', 'Nightfall'),
    CatalogEntry('Stygian Gemstone', 21129, 'Reward Trophies', 'Nightfall'),
    CatalogEntry('Titan Gemstone', 21130, 'Reward Trophies', 'Nightfall'),
    CatalogEntry('Deldrimor Armor Remnant', 27321, 'Reward Trophies', 'Eye Of North'),
    CatalogEntry('Cloth Of The Brotherhood', 27322, 'Reward Trophies', 'Eye Of North'),
    CatalogEntry('Ministerial Commendation', 36985, 'Reward Trophies', 'Winds Of Change'),
    CatalogEntry('Lunar Token', 21833, 'Reward Trophies', 'Special Events'),
    CatalogEntry('Blessing Of War', 37843, 'Reward Trophies', 'Special Events'),
    CatalogEntry('Victory Token', 18345, 'Reward Trophies', 'Special Events'),
    CatalogEntry('Wayfarer Mark', 37765, 'Reward Trophies', 'Special Events'),
    CatalogEntry('Cc Shard', 556, 'Reward Trophies', 'Special Events'),
    CatalogEntry('Glob Of Frozen Ectoplasm', 21509, 'Reward Trophies', 'Special Events'),
    CatalogEntry('Trick-or-treat Bag', 28434, 'Reward Trophies', 'Special Events'),
    CatalogEntry('Map Piece (Bottom-Left)', 24631, 'Quest Items', 'Map Pieces'),
    CatalogEntry('Map Piece (Bottom-Right)', 24632, 'Quest Items', 'Map Pieces'),
    CatalogEntry('Map Piece (Top-Left)', 24629, 'Quest Items', 'Map Pieces'),
    CatalogEntry('Map Piece (Top-Right)', 24630, 'Quest Items', 'Map Pieces'),
    CatalogEntry('Dungeon Key', 25410, 'Quest Items', 'Keys'),
    CatalogEntry('Boss Key', 25416, 'Quest Items', 'Keys'),
    CatalogEntry('Cell Key', 15565, 'Quest Items', 'Keys'),
    CatalogEntry('Prison Key', 25413, 'Quest Items', 'Keys'),
    CatalogEntry('Diamond Key', 19175, 'Quest Items', 'Keys'),
    CatalogEntry('Ruby Key', 19177, 'Quest Items', 'Keys'),
    CatalogEntry('Sapphire Key', 19176, 'Quest Items', 'Keys'),
    CatalogEntry('Spectral Crystal (Bloodstone Cave)', 24635, 'Quest Items', 'Dungeon quest items'),
    CatalogEntry('Shimmering Essence (Bloodstone Cave)', 24633, 'Quest Items', 'Dungeon quest items'),
    CatalogEntry('Arcane Crystal Shard (Bloodstone Cave)', 24634, 'Quest Items', 'Dungeon quest items'),
    CatalogEntry('Exquisite Surmia Carving (Cathedral of Flames)', 24352, 'Quest Items', 'Dungeon quest items'),
    CatalogEntry('Hammer of Kathandrax (Catacombs of Kathandrax)', 22374, 'Quest Items', 'Dungeon quest items'),
    CatalogEntry('Prismatic Gelatinous Material (Ooze Pit)', 22375, 'Quest Items', 'Dungeon quest items'),
    CatalogEntry('Elemental Crystal Shard', 38302, 'Trophies', ''),
    CatalogEntry('Elemental Keystone', 38301, 'Quest Items', 'Keys'),
)


UNRESOLVED: tuple[UnresolvedEntry, ...] = (
    UnresolvedEntry('Animal Hide', 'Trophies'),
    UnresolvedEntry('Bleached Shell', 'Trophies'),
    UnresolvedEntry('Bonesnap Shell', 'Trophies'),
    UnresolvedEntry('Dark Flame Fang', 'Trophies'),
    UnresolvedEntry('Dregde Manifesto', 'Trophies'),
    UnresolvedEntry('Frozen Remnant', 'Trophies'),
    UnresolvedEntry('Frozen Shell', 'Trophies'),
    UnresolvedEntry('Gargantuan Jawbone', 'Trophies'),
    UnresolvedEntry('Ghostly Remains', 'Trophies'),
    UnresolvedEntry('Kuskale Claw', 'Trophies'),
    UnresolvedEntry('Leather Belt', 'Trophies'),
    UnresolvedEntry('Mandragor Carapace', 'Trophies'),
    UnresolvedEntry('Rinkhal Talon', 'Trophies'),
    UnresolvedEntry('Smoking Remains', 'Trophies'),
    UnresolvedEntry('Spiny Seed', 'Trophies'),
    UnresolvedEntry('Vampiric Fang', 'Trophies'),
)


_BY_MODEL_ID: dict[int, CatalogEntry] = {e.model_id: e for e in CATALOG}


def categories() -> list[str]:
    """Category names, in catalog order."""
    seen: dict[str, None] = {}
    for entry in CATALOG:
        seen.setdefault(entry.category, None)
    return list(seen)


def groups(category: str) -> list[str]:
    """Group names within a category, in catalog order. Empty when the category has no groups."""
    seen: dict[str, None] = {}
    for entry in CATALOG:
        if entry.category == category and entry.group:
            seen.setdefault(entry.group, None)
    return list(seen)


def in_category(category: str) -> list[CatalogEntry]:
    return [e for e in CATALOG if e.category == category]


def in_group(category: str, group: str) -> list[CatalogEntry]:
    return [e for e in CATALOG if e.category == category and e.group == group]


def by_model_id(model_id: int) -> CatalogEntry | None:
    return _BY_MODEL_ID.get(int(model_id))


def model_ids(category: str | None = None) -> set[int]:
    if category is None:
        return set(_BY_MODEL_ID)
    return {e.model_id for e in CATALOG if e.category == category}


def alphabetical_bands(entries) -> list[tuple[str, list[CatalogEntry]]]:
    """Band entries by first letter, sorted. The render-time replacement for Trophies' A...W data."""
    bands: dict[str, list[CatalogEntry]] = {}
    for entry in sorted(entries, key=lambda e: e.name.lower()):
        bands.setdefault(entry.name[:1].upper(), []).append(entry)
    return sorted(bands.items())


# The following helpers form the reusable runtime index used by feature modules.  The shipped
# ``CATALOG`` above remains the canonical package data; this index is deliberately fed normalized
# rows by callers and never opens feature-owned JSON files.
MODEL_ID_FALLBACK_ITEM_TYPE_SUFFIXES: tuple[tuple[str, str], ...] = (
    ('Daggers', 'Daggers'),
    ('Scythe', 'Scythe'),
    ('Shield', 'Shield'),
    ('Spear', 'Spear'),
    ('Staff', 'Staff'),
    ('Sword', 'Sword'),
    ('Hammer', 'Hammer'),
    ('Focus', 'Offhand'),
    ('Offhand', 'Offhand'),
    ('Icon', 'Offhand'),
    ('Prism', 'Offhand'),
    ('Wand', 'Wand'),
    ('Bow', 'Bow'),
    ('Axe', 'Axe'),
    ('Headpiece', 'Headpiece'),
    ('Chestpiece', 'Chestpiece'),
    ('Gloves', 'Gloves'),
    ('Leggings', 'Leggings'),
    ('Boots', 'Boots'),
    ('SalvageKit', 'Salvage'),
)

DEFAULT_CATALOG_ENTRY_PRIORITY: int = 100
RUNE_ATTRIBUTE_MODIFIER_IDENTIFIER: int = 8680


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


def _build_catalog_alias_labels(name: object, skin: object = '', wiki_url: object = '') -> dict[str, str]:
    alias_labels: dict[str, str] = {}

    def _add_alias(raw_alias: object, display_label: object = '') -> None:
        normalized = _normalize_catalog_search_text(raw_alias)
        if not normalized:
            return
        display = str(display_label or raw_alias or '').strip()
        if not display:
            display = normalized.title()
        alias_labels.setdefault(normalized, display)

    safe_name = str(name or '').strip()
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
        raw_members = [
            (name, getattr(model_id_type, name))
            for name in dir(model_id_type)
            if not name.startswith('_')
        ]

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
                return item_type
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
            fallback_label = _ATTRIBUTE_LABEL_FALLBACK.get(attribute_id)
            if fallback_label:
                return fallback_label
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
class CatalogLoadResult:
    """Reusable catalog index result; feature adapters may subclass it with policy projections."""

    catalog_by_model_id: dict[int, dict[str, object]] = field(default_factory=dict)
    catalog_alias_to_model_ids: dict[str, list[int]] = field(default_factory=dict)
    catalog_alias_display_names: dict[str, str] = field(default_factory=dict)


class CatalogLoader:
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
            lambda _model_id, _item_type, _category, _sub_category: DEFAULT_CATALOG_ENTRY_PRIORITY
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
        safe_name = str(name or '').strip()
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

            loaded_entry = {
                'model_id': model_id,
                'name': str(entry.get('name', '') or f'Model {model_id}'),
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
            name = str(row.get('name', '')).strip()
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
    ) -> int:
        loaded_count = 0
        resolve_priority = priority_resolver or self.item_priority_resolver
        for entry in _iter_item_handling_catalog_entries(raw_catalog):
            model_id = _resolve_model_id_value(entry.get('model_id', entry.get('ModelID', 0)))
            name = str(entry.get('name') or entry.get('Name') or '').strip()
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

            extra: dict[str, object] = {
                'alias_labels': _build_catalog_alias_labels(name, skin, wiki_url),
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
            loaded_count += 1
        return loaded_count

    def load_rune_model_catalog(
        self,
        catalog_by_model_id: dict[int, dict[str, object]],
        raw_catalog: object,
        *,
        source: str = 'runes_catalog',
        priority: int = DEFAULT_CATALOG_ENTRY_PRIORITY,
    ) -> int:
        if not isinstance(raw_catalog, dict):
            return 0

        grouped_entries: dict[int, tuple[set[str], set[str]]] = {}
        for raw_identifier, raw_entry in raw_catalog.items():
            if not isinstance(raw_entry, dict):
                continue
            model_id = max(0, _safe_int(raw_entry.get('ModelId', 0), 0))
            if model_id <= 0:
                continue

            names = raw_entry.get('Names', {})
            display_name = str(names.get('English', '') or '').strip() if isinstance(names, dict) else ''
            if not display_name:
                display_name = str(raw_entry.get('Identifier', raw_identifier) or '').strip()
            if not display_name:
                continue

            mod_type = str(raw_entry.get('ModType', '') or '').strip()
            normalized_name = _normalize_catalog_search_text(display_name)
            if mod_type == 'Prefix' or 'insignia' in normalized_name:
                kind = 'insignia'
            elif mod_type == 'Suffix' or 'rune' in normalized_name:
                kind = 'rune'
            else:
                kind = ''

            names_for_model, kinds_for_model = grouped_entries.setdefault(model_id, (set(), set()))
            names_for_model.add(display_name)
            if kind:
                kinds_for_model.add(kind)

        loaded_count = 0
        for model_id, (names_for_model, kinds_for_model) in grouped_entries.items():
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

                current_alias_labels = current.get('alias_labels', {})
                if not isinstance(current_alias_labels, dict):
                    current_alias_labels = {}
                current_alias_labels.update(alias_labels)
                current['alias_labels'] = current_alias_labels
            loaded_count += 1

        return loaded_count

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
            for normalized_alias, display_name in normalized_alias_labels.items():
                alias_model_ids = alias_to_model_ids.setdefault(normalized_alias, [])
                if model_id not in alias_model_ids:
                    alias_model_ids.append(model_id)
                alias_display_names.setdefault(normalized_alias, display_name)

        return alias_to_model_ids, alias_display_names

    @staticmethod
    def get_catalog_alias_group_count(alias_to_model_ids: dict[str, list[int]]) -> int:
        return sum(1 for model_ids in alias_to_model_ids.values() if len(model_ids) > 1)


__all__ = [
    'CATALOG',
    'UNRESOLVED',
    'CatalogEntry',
    'UnresolvedEntry',
    'CatalogLoadResult',
    'CatalogLoader',
    'DEFAULT_CATALOG_ENTRY_PRIORITY',
    'MODEL_ID_FALLBACK_ITEM_TYPE_SUFFIXES',
    '_build_catalog_alias_labels',
    '_dedupe_model_ids',
    '_get_rune_kind_label',
    '_get_rune_kind_sort_key',
    '_get_rune_profession_label',
    '_get_rune_rarity_sort_key',
    '_humanize_model_id_enum_name',
    '_infer_model_id_fallback_item_type',
    '_iter_item_handling_catalog_entries',
    '_iter_model_id_members',
    '_normalize_catalog_search_text',
    '_normalize_catalog_rune_identifier',
    '_normalize_rune_catalog_profession',
    '_resolve_model_id_value',
    '_resolve_rune_description_template',
    '_safe_int',
]
