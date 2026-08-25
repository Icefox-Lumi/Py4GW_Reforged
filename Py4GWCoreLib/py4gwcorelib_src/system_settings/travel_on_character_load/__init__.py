"""Automatic travel after the first character load or a character switch."""

from .controller import TravelOnCharacterLoadController
from .controller import get_controller

__all__ = ["TravelOnCharacterLoadController", "get_controller"]
