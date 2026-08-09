"""System Settings item features.

The package owns Item Profiles, Colorize, the Xunlai-opening command, shared frame monitoring, and
the cross-feature item-operation gate. An Item Profile stores only a reference to a separately owned
ID Filter Profile; Identification owns its timer, actions, and settings.
"""

from .controller import InventorySettingsController, get_controller

__all__ = ["InventorySettingsController", "get_controller"]
