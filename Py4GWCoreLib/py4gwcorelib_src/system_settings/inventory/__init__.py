"""System Settings item features.

The package owns the first Inventory+ migration slice: item profiles, Colorize, and the
Xunlai-opening command. Identification, salvage, and inventory handling have independent
profile objects but are intentionally not active yet.
"""

from .controller import InventorySettingsController, get_controller

__all__ = ["InventorySettingsController", "get_controller"]
