"""Standalone Identification feature configuration and runtime.

The active Item Profile selects one named ID Filter Profile. Identification owns its filter
definitions and profiles; they use the same criterion schema and matcher as Loot Filters without
sharing either feature's persisted definitions or profile selection.
"""

from .controller import IdentificationController, get_controller

__all__ = ["IdentificationController", "get_controller"]
