from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from typing import Optional

from Py4GWCoreLib.enums_src.GameData_enums import Profession
from Py4GWCoreLib.enums_src.Item_enums import INVENTORY_BAGS, STORAGE_BAGS, Bags, ItemType
from Py4GWCoreLib.enums_src.Model_enums import ModelID
from Py4GWCoreLib.enums_src.Title_enums import TitleID
from Sources.frenkeyLib.item_data.item_snapshot import ItemSnapshot

class RecipeType(IntEnum):
    Unknown = auto()
    Material = auto()
    Armor = auto()
    Weapon = auto()
    Consumable = auto()
    Exchange = auto()

@dataclass(frozen=True)
class Ingredient:
    model_id: int
    item_type: ItemType
    quantity: int
    
@dataclass(frozen=True)
class Result:
    model_id: int
    item_type: ItemType
    quantity: int
    profession : Optional[Profession] = None

@dataclass(frozen=True)
class TitleRequirement:
    title_id: TitleID
    level: int

@dataclass(frozen=True)
class CraftingNPC:
    name: str
    encoded_name: bytes
    map_id: int
    position: tuple[float, float]
    title_requirement: Optional[TitleRequirement] = None

@dataclass(frozen=True)
class Recipe:
    name: str
    result: Result
    ingredients: list[Ingredient]
    recipe_type: RecipeType
    
    crafter: list[CraftingNPC] = field(default_factory=list)
    gold_cost: Optional[int] = None
    skill_point_cost: Optional[int] = None


@dataclass(frozen=True)
class ShoppingListEntry:
    model_id: int
    item_type: ItemType
    quantity: int


@dataclass(frozen=True)
class CraftingPlan:
    target_per_recipe: int
    recipe_counts: dict[str, int]
    total_required_ingredients: list[Ingredient]
    shopping_list: list[ShoppingListEntry]
    remaining_ingredients: list[Ingredient]

class Crafter(Enum):
    Alcus_Nailbiter_Embark = CraftingNPC(
        name="Alcus Nailbiter",
        encoded_name=bytes([0x2, 0x81, 0xCC, 0x1E, 0x56, 0x91, 0x7D, 0xD8, 0x91, 0x43, 0x0, 0x0]),
        map_id=857,
        position=(3743.00, -106.00),
        title_requirement=TitleRequirement(title_id=TitleID.Deldrimor, level=3),
    )
    
    Alcus_Nailbiter_CentralTransferChamber = CraftingNPC(
        name="Alcus Nailbiter",
        encoded_name=bytes([0x2, 0x81, 0xCC, 0x1E, 0x56, 0x91, 0x7D, 0xD8, 0x91, 0x43, 0x0, 0x0]),
        map_id=652,
        position=(3327.00, 892.00),
        title_requirement=TitleRequirement(title_id=TitleID.Deldrimor, level=3),
    )
    
    Kwat_Embark = CraftingNPC(
        name="Kwat",
        encoded_name=bytes([0x2, 0x81, 0x9E, 0x1E, 0x22, 0xCE, 0x44, 0xDB, 0x71, 0x73, 0x0, 0x0]),
        map_id=857,
        position=(3666.00, 90.00),
        title_requirement=TitleRequirement(title_id=TitleID.Asuran, level=3),
    )
    
    Kwat_RataSum = CraftingNPC(
        name="Kwat",
        encoded_name=bytes([0x2, 0x81, 0x9E, 0x1E, 0x22, 0xCE, 0x44, 0xDB, 0x71, 0x73, 0x0, 0x0]),
        map_id=640,
        position=(13665.00, 17811.00),
        title_requirement=TitleRequirement(title_id=TitleID.Asuran, level=3),
    )
    
    Edwin_Embark = CraftingNPC(
        name="Edwin",
        encoded_name=bytes([0x2, 0x81, 0xAD, 0x1E, 0xCA, 0xCA, 0x8E, 0xF5, 0xE0, 0x74, 0x0, 0x0]),
        map_id=857,
        position=(3588.00, 371.00),
        title_requirement=TitleRequirement(title_id=TitleID.Ebon_Vanguard, level=3),
    )
    
    Edwin_EotN = CraftingNPC(
        name="Edwin",
        encoded_name=bytes([0x2, 0x81, 0xAD, 0x1E, 0xCA, 0xCA, 0x8E, 0xF5, 0xE0, 0x74, 0x0, 0x0]),
        map_id=642,
        position=(-774.97, 1188.94),
        title_requirement=TitleRequirement(title_id=TitleID.Ebon_Vanguard, level=3),
    )
    
    Eyja_Embark = CraftingNPC(
        name="Eyja",
        encoded_name=bytes([0x2, 0x81, 0xBD, 0x1E, 0x6D, 0xC2, 0xE4, 0xFC, 0xED, 0x2E, 0x0, 0x0]),
        map_id=857,
        position=(3414.00, 644.00),
        title_requirement=TitleRequirement(title_id=TitleID.Norn, level=3),
    )
    
    Eyja_Gunnars = CraftingNPC(
        name="Eyja",
        encoded_name=bytes([0x2, 0x81, 0xBD, 0x1E, 0x6D, 0xC2, 0xE4, 0xFC, 0xED, 0x2E, 0x0, 0x0]),
        map_id=644,
        position=(18605.00, -3751.00),
        title_requirement=TitleRequirement(title_id=TitleID.Norn, level=3),
    )

    Tesla_Embark = CraftingNPC(
        name="Tesla",
        encoded_name=bytes([0x2, 0x81, 0x50, 0x54, 0x91, 0xD8, 0x76, 0xA6, 0xDD, 0xD, 0x0, 0x0]),
        map_id=857,
        position=(-823.00, -3217.00),
    )
    
    Tesla_GtoB = CraftingNPC(
        name="Tesla",
        encoded_name=bytes([0x2, 0x81, 0x50, 0x54, 0x91, 0xD8, 0x76, 0xA6, 0xDD, 0xD, 0x0, 0x0]),
        map_id=248,
        position=(-4968.00, -5665.00),
    )
    
    Pokhe_Embark = CraftingNPC(
        name="Pokhe",
        encoded_name=bytes([0x2, 0x81, 0x51, 0x54, 0xE2, 0x8F, 0x33, 0xAE, 0x2E, 0x57, 0x0, 0x0]),
        map_id=857,
        position=(-882.00, -3167.00),
    )
    
    Pokhe_GtoB = CraftingNPC(
        name="Pokhe",
        encoded_name=bytes([0x2, 0x81, 0x51, 0x54, 0xE2, 0x8F, 0x33, 0xAE, 0x2E, 0x57, 0x0, 0x0]),
        map_id=248,
        position=(-5043.92, -5820.56),
    )
    
    Jessie_Llam_Embark = CraftingNPC(
        name="Jessie Llam",
        encoded_name=bytes([0x2, 0x81, 0x52, 0x54, 0xB, 0xAA, 0xD6, 0x8D, 0xD7, 0x17, 0x0, 0x0]),
        map_id=857,
        position=(-983.00, -3100.00),
    )
    
    Jessie_Llam_GtoB = CraftingNPC(
        name="Jessie Llam",
        encoded_name=bytes([0x2, 0x81, 0x52, 0x54, 0xB, 0xAA, 0xD6, 0x8D, 0xD7, 0x17, 0x0, 0x0]),
        map_id=248,
        position=(-4955.00, -5866.00),
    )
    
class CraftingRecipe(Enum):
    Armor_Of_Salvation = Recipe(
        name="Armor of Salvation",
        result=Result(model_id=ModelID.Armor_Of_Salvation, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Iron_Ingot, item_type=ItemType.Materials_Zcoins, quantity=50),
            Ingredient(model_id=ModelID.Bone, item_type=ItemType.Materials_Zcoins, quantity=50),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=250,
        skill_point_cost=1,
        crafter=[
            Crafter.Alcus_Nailbiter_Embark.value,
            Crafter.Alcus_Nailbiter_CentralTransferChamber.value,
        ],
    )
    
    Essence_Of_Celerity = Recipe(
        name="Essence of Celerity",
        result=Result(model_id=ModelID.Essence_Of_Celerity, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Feather, item_type=ItemType.Materials_Zcoins, quantity=50),
            Ingredient(model_id=ModelID.Pile_Of_Glittering_Dust, item_type=ItemType.Materials_Zcoins, quantity=50),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=250,
        skill_point_cost=1,
        crafter=[
            Crafter.Kwat_Embark.value,
            Crafter.Kwat_RataSum.value,
        ],
    )
    
    Powerstone_Of_Courage = Recipe(
        name="Powerstone of Courage",
        result=Result(model_id=ModelID.Powerstone_Of_Courage, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Granite_Slab, item_type=ItemType.Materials_Zcoins, quantity=100),
            Ingredient(model_id=ModelID.Pile_Of_Glittering_Dust, item_type=ItemType.Materials_Zcoins, quantity=100),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=1000,
        skill_point_cost=1,
        crafter=[
            Crafter.Edwin_Embark.value,
            Crafter.Edwin_EotN.value,
        ],
    )
    
    Grail_Of_Might = Recipe(
        name="Grail of Might",
        result=Result(model_id=ModelID.Grail_Of_Might, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Iron_Ingot, item_type=ItemType.Materials_Zcoins, quantity=50),
            Ingredient(model_id=ModelID.Pile_Of_Glittering_Dust, item_type=ItemType.Materials_Zcoins, quantity=50),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=250,
        skill_point_cost=1,
        crafter=[
            Crafter.Eyja_Embark.value,
            Crafter.Eyja_Gunnars.value,
        ],
    )
    
    Scroll_Of_Resurrection = Recipe(
        name="Scroll of Resurrection",
        result=Result(model_id=ModelID.Scroll_Of_Resurrection, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Plant_Fiber, item_type=ItemType.Materials_Zcoins, quantity=25),
            Ingredient(model_id=ModelID.Bone, item_type=ItemType.Materials_Zcoins, quantity=25),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=250,
        skill_point_cost=1,
        crafter=[
            Crafter.Alcus_Nailbiter_Embark.value,
            Crafter.Kwat_Embark.value,
            Crafter.Edwin_Embark.value,
            Crafter.Eyja_Embark.value,
            
            Crafter.Alcus_Nailbiter_CentralTransferChamber.value,
            Crafter.Kwat_RataSum.value,
            Crafter.Edwin_EotN.value,
            Crafter.Eyja_Gunnars.value,
        ],
    )
    
    Star_Of_Transference = Recipe(
        name="Star of Transference",
        result=Result(model_id=ModelID.Star_Of_Transference, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Wood_Plank, item_type=ItemType.Materials_Zcoins, quantity=25),
            Ingredient(model_id=ModelID.Plant_Fiber, item_type=ItemType.Materials_Zcoins, quantity=25),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=250,
        skill_point_cost=1,
        crafter=[
            Crafter.Alcus_Nailbiter_Embark.value,
            Crafter.Kwat_Embark.value,
            Crafter.Edwin_Embark.value,
            Crafter.Eyja_Embark.value,
            
            Crafter.Alcus_Nailbiter_CentralTransferChamber.value,
            Crafter.Kwat_RataSum.value,
            Crafter.Edwin_EotN.value,
            Crafter.Eyja_Gunnars.value,
        ],
    )
    
    Perfect_Salvage_Kit = Recipe(
        name="Perfect Salvage Kit",
        result=Result(model_id=ModelID.Perfect_Salvage_Kit, item_type=ItemType.Kit, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Iron_Ingot, item_type=ItemType.Materials_Zcoins, quantity=25),
            Ingredient(model_id=ModelID.Wood_Plank, item_type=ItemType.Materials_Zcoins, quantity=25),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=250,
        skill_point_cost=1,
        crafter=[
            Crafter.Alcus_Nailbiter_Embark.value,
            Crafter.Kwat_Embark.value,
            Crafter.Edwin_Embark.value,
            Crafter.Eyja_Embark.value,
            
            Crafter.Alcus_Nailbiter_CentralTransferChamber.value,
            Crafter.Kwat_RataSum.value,
            Crafter.Edwin_EotN.value,
            Crafter.Eyja_Gunnars.value,
        ],
    )
    
    Gelatinous_Summoning_Stone = Recipe(
        name="Gelatinous Summoning Stone",
        result=Result(model_id=ModelID.Gelatinous_Summon, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Granite_Slab, item_type=ItemType.Materials_Zcoins, quantity=10),
            Ingredient(model_id=ModelID.Pile_Of_Glittering_Dust, item_type=ItemType.Materials_Zcoins, quantity=100),
            Ingredient(model_id=ModelID.Diamond, item_type=ItemType.Materials_Zcoins, quantity=1),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=1000,
        skill_point_cost=1,
        crafter=[
            Crafter.Alcus_Nailbiter_Embark.value,
            Crafter.Alcus_Nailbiter_CentralTransferChamber.value,
        ],
    )
    
    Fossilized_Summoning_Stone = Recipe(
        name="Fossilized Summoning Stone",
        result=Result(model_id=ModelID.Fossilized_Summon, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Granite_Slab, item_type=ItemType.Materials_Zcoins, quantity=10),
            Ingredient(model_id=ModelID.Bone, item_type=ItemType.Materials_Zcoins, quantity=100),
            Ingredient(model_id=ModelID.Monstrous_Claw, item_type=ItemType.Materials_Zcoins, quantity=1),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=1000,
        skill_point_cost=1,
        crafter=[
            Crafter.Kwat_Embark.value,
            Crafter.Kwat_RataSum.value,
        ],
    )
    
    Chitinous_Summoning_Stone = Recipe(
        name="Chitinous Summoning Stone",
        result=Result(model_id=ModelID.Chitinous_Summon, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Granite_Slab, item_type=ItemType.Materials_Zcoins, quantity=10),
            Ingredient(model_id=ModelID.Chitin_Fragment, item_type=ItemType.Materials_Zcoins, quantity=100),
            Ingredient(model_id=ModelID.Monstrous_Eye, item_type=ItemType.Materials_Zcoins, quantity=4),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=1000,
        skill_point_cost=1,
        crafter=[
            Crafter.Edwin_Embark.value,
            Crafter.Edwin_EotN.value,
        ],
    )
    
    Arctic_Summoning_Stone = Recipe(
        name="Arctic Summoning Stone",
        result=Result(model_id=ModelID.Arctic_Summon, item_type=ItemType.Usable, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Granite_Slab, item_type=ItemType.Materials_Zcoins, quantity=10),
            Ingredient(model_id=ModelID.Bone, item_type=ItemType.Materials_Zcoins, quantity=100),
            Ingredient(model_id=ModelID.Fur_Square, item_type=ItemType.Materials_Zcoins, quantity=4),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=1000,
        skill_point_cost=1,
        crafter=[
            Crafter.Eyja_Embark.value,
            Crafter.Eyja_Gunnars.value,
        ],
    )
    
    Silver_Zaishen_Coin = Recipe(
        name="Silver Zaishen Coin",
        result=Result(model_id=ModelID.Silver_Zaishen_Coin, item_type=ItemType.Materials_Zcoins, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Copper_Zaishen_Coin, item_type=ItemType.Materials_Zcoins, quantity=50),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=10,
        crafter=[
            Crafter.Tesla_Embark.value,
            Crafter.Tesla_GtoB.value,
        ],
    )
    
    Gold_Zaishen_Coin = Recipe(
        name="Gold Zaishen Coin",
        result=Result(model_id=ModelID.Gold_Zaishen_Coin, item_type=ItemType.Materials_Zcoins, quantity=1),
        ingredients=[
            Ingredient(model_id=ModelID.Silver_Zaishen_Coin, item_type=ItemType.Materials_Zcoins, quantity=10),
        ],
        recipe_type=RecipeType.Consumable,
        gold_cost=50,
        crafter=[
            Crafter.Pokhe_Embark.value,
            Crafter.Pokhe_GtoB.value,
        ],
    )
    
class Crafting:
    def __init__(self, recipes: list[Recipe], available_ingredients: Optional[list[Ingredient]] = None, bags : Optional[list[Bags]] = None):
        self.available_ingredients = available_ingredients
        self.recipes = recipes
        self.bags = bags

    def get_available_ingredients(self) -> list[Ingredient]:
        if self.available_ingredients is None:
            bags = self.bags if self.bags is not None else [*INVENTORY_BAGS, *STORAGE_BAGS, Bags.MaterialStorage]
            items = ItemSnapshot.get_bags_items(bags=bags)
                
            ingredient_map: dict[tuple[int, ItemType], Ingredient] = {}
            def count_item(model_id : int, item_type: ItemType) -> None:
                key = (model_id, item_type)
                if key in ingredient_map:
                    return
                
                matching_items = [i for i in items if i.model_id == model_id and i.item_type == item_type]
                total_quantity = sum(int(i.quantity or 0) for i in matching_items)

                ingredient_map[key] = Ingredient(
                    model_id=model_id,
                    item_type=item_type,
                    quantity=total_quantity,
                )
                
            for recipe in self.recipes:
                for ingredient in recipe.ingredients:
                    key = (ingredient.model_id, ingredient.item_type)
                    if key in ingredient_map:
                        continue
                    
                    count_item(ingredient.model_id, ingredient.item_type)

            return sorted(
                ingredient_map.values(),
                key=lambda ingredient: (int(ingredient.item_type), int(ingredient.model_id)),
            )
        
        else:
            return self.available_ingredients

    @staticmethod
    def _ingredient_key(ingredient: Ingredient | ShoppingListEntry) -> tuple[int, ItemType]:
        return ingredient.model_id, ingredient.item_type

    @classmethod
    def _to_inventory_map(cls, ingredients: list[Ingredient]) -> dict[tuple[int, ItemType], int]:
        inventory: dict[tuple[int, ItemType], int] = {}
        for ingredient in ingredients:
            key = cls._ingredient_key(ingredient)
            inventory[key] = inventory.get(key, 0) + ingredient.quantity
        return inventory

    @classmethod
    def _to_ingredient_list(cls, inventory: dict[tuple[int, ItemType], int]) -> list[Ingredient]:
        return [
            Ingredient(model_id=model_id, item_type=item_type, quantity=quantity)
            for (model_id, item_type), quantity in sorted(inventory.items())
            if quantity > 0
        ]

    @classmethod
    def _to_shopping_list(cls, inventory: dict[tuple[int, ItemType], int]) -> list[ShoppingListEntry]:
        return [
            ShoppingListEntry(model_id=model_id, item_type=item_type, quantity=quantity)
            for (model_id, item_type), quantity in sorted(inventory.items())
            if quantity > 0
        ]

    @classmethod
    def _calculate_required_ingredients(
        cls,
        recipes: list[Recipe],
        target_per_recipe: int,
    ) -> dict[tuple[int, ItemType], int]:
        required: dict[tuple[int, ItemType], int] = {}
        if target_per_recipe <= 0:
            return required

        for recipe in recipes:
            for ingredient in recipe.ingredients:
                key = cls._ingredient_key(ingredient)
                required[key] = required.get(key, 0) + (ingredient.quantity * target_per_recipe)

        return required

    @classmethod
    def _max_crafts_for_recipe(
        cls,
        recipe: Recipe,
        inventory: dict[tuple[int, ItemType], int],
    ) -> int:
        if not recipe.ingredients:
            return 0

        crafts_per_ingredient = []
        for ingredient in recipe.ingredients:
            key = cls._ingredient_key(ingredient)
            available_quantity = inventory.get(key, 0)
            crafts_per_ingredient.append(available_quantity // ingredient.quantity)

        return min(crafts_per_ingredient, default=0)

    @classmethod
    def _build_plan(
        cls,
        recipes: list[Recipe],
        available_inventory: dict[tuple[int, ItemType], int],
        target_per_recipe: int,
    ) -> CraftingPlan:
        total_required = cls._calculate_required_ingredients(recipes, target_per_recipe)
        shortages: dict[tuple[int, ItemType], int] = {}
        remaining: dict[tuple[int, ItemType], int] = {}

        for key, required_quantity in total_required.items():
            available_quantity = available_inventory.get(key, 0)
            if required_quantity > available_quantity:
                shortages[key] = required_quantity - available_quantity
                remaining[key] = 0
            else:
                remaining[key] = available_quantity - required_quantity

        for key, available_quantity in available_inventory.items():
            if key not in total_required:
                remaining[key] = available_quantity

        return CraftingPlan(
            target_per_recipe=target_per_recipe,
            recipe_counts={recipe.name: target_per_recipe for recipe in recipes},
            total_required_ingredients=cls._to_ingredient_list(total_required),
            shopping_list=cls._to_shopping_list(shortages),
            remaining_ingredients=cls._to_ingredient_list(remaining),
        )

    def calculate_equal_distribution(self) -> CraftingPlan:
        available_inventory = self._to_inventory_map(self.get_available_ingredients())
        if not self.recipes:
            return self._build_plan([], available_inventory, 0)

        target_per_recipe = min(
            self._max_crafts_for_recipe(recipe, available_inventory)
            for recipe in self.recipes
        )
        return self._build_plan(self.recipes, available_inventory, target_per_recipe)

    def calculate_equal_distribution_with_shopping(
        self,
        target_per_recipe: Optional[int] = None,
    ) -> CraftingPlan:
        available_inventory = self._to_inventory_map(self.get_available_ingredients())
        if not self.recipes:
            return self._build_plan([], available_inventory, 0)

        if target_per_recipe is None:
            target_per_recipe = max(
                self._max_crafts_for_recipe(recipe, available_inventory)
                for recipe in self.recipes
            )

        target_per_recipe = max(target_per_recipe, 0)
        return self._build_plan(self.recipes, available_inventory, target_per_recipe)
        
