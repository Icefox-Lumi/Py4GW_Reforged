"""Runtime owner for System Settings item features."""

from copy import deepcopy
from typing import Optional

from . import store
from .model import ColorizeProfile, ItemProfile
from .monitor import InventoryMonitor, InventorySlot
from Py4GWCoreLib.py4gwcorelib_src.Color import Color


_CONTEXT_POPUP_ID = "SystemItemsContextMenu"
_CONTEXT_CALLBACK = "SystemItemsContextMenuCallback"
_COLORIZE_CALLBACK = "SystemItemsColorize"


def _log(message: str, error: bool = False) -> None:
    try:
        import PySystem

        level = PySystem.Console.MessageType.Error if error else PySystem.Console.MessageType.Info
        PySystem.Console.Log("System Settings / Items", message, level)
    except Exception:
        pass


def _color(color: tuple[int, int, int, int], alpha: int | None = None) -> Color:
    """Build a repository Color while optionally replacing its alpha channel."""
    value = Color(*color)
    if alpha is not None:
        value.set_a(alpha)
    return value


def _map_is_ready() -> bool:
    """Keep item runtime work out of the client bootstrap and map-loading phases."""
    try:
        from Py4GWCoreLib.Map import Map

        return bool(Map.IsMapReady())
    except Exception:
        return False


class InventorySettingsController:
    def __init__(self) -> None:
        self._active_name, self._profiles, self._migrated = store.load()
        self._monitor = InventoryMonitor()
        self._context_monitor = InventoryMonitor()
        self._booted = False
        self._native_tints: dict[int, int] = {}
        self._xunlai_status = ""
        self._native_outline_warned = False
        self._callbacks_registered = False
        self._context_item: InventorySlot | None = None
        self._active_item_operation: str | None = None

    def boot(self) -> None:
        if self._booted:
            return
        self._booted = True
        if self._migrated:
            _log("Imported legacy Inventory+ Colorize settings into item profile '%s'." % self._active_name)
        self._register_callbacks()

    def _register_callbacks(self) -> None:
        """Register isolated draw callbacks for item interaction and Colorize."""
        try:
            import PyCallback

            from Py4GWCoreLib.py4gwcorelib_src.Profiling import ProfilingRegistry

            PyCallback.PyCallback.RemoveByName(_CONTEXT_CALLBACK)
            PyCallback.PyCallback.RemoveByName(_COLORIZE_CALLBACK)
            PyCallback.PyCallback.Register(
                _CONTEXT_CALLBACK,
                PyCallback.Phase.Update,
                self._context_pass,
                priority=99,
                context=PyCallback.Context.Draw,
            )
            PyCallback.PyCallback.Register(
                _COLORIZE_CALLBACK,
                PyCallback.Phase.Update,
                self._colorize_pass,
                priority=99,
                context=PyCallback.Context.Draw,
            )
            registry = ProfilingRegistry()
            registry.register(_CONTEXT_CALLBACK)
            registry.register(_COLORIZE_CALLBACK)
            self._callbacks_registered = True
        except Exception as exc:
            self._callbacks_registered = False
            _log("item callback registration error: %s" % exc, error=True)

    def profiles(self) -> list[ItemProfile]:
        return self._profiles

    def active(self) -> ItemProfile:
        for profile in self._profiles:
            if profile.name == self._active_name:
                return profile
        self._active_name = self._profiles[0].name
        return self._profiles[0]

    def set_active(self, name: str) -> None:
        if name in {profile.name for profile in self._profiles}:
            self._active_name = name
            self._save()

    def create_profile(self) -> None:
        index = 1
        names = {profile.name for profile in self._profiles}
        while "Profile %d" % index in names:
            index += 1
        self._profiles.append(ItemProfile(name="Profile %d" % index))
        self._active_name = self._profiles[-1].name
        self._save()

    def duplicate_active(self) -> None:
        source = self.active()
        index = 1
        names = {profile.name for profile in self._profiles}
        while "%s Copy %d" % (source.name, index) in names:
            index += 1
        duplicate = deepcopy(source)
        duplicate.name = "%s Copy %d" % (source.name, index)
        self._profiles.append(duplicate)
        self._active_name = duplicate.name
        self._save()

    def save_active(self) -> None:
        self._save()

    def _save(self) -> None:
        store.save(self._active_name, self._profiles, migrated_legacy=True)

    def open_xunlai(self) -> None:
        if not _map_is_ready():
            self._xunlai_status = "Map is not ready."
            return
        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            if GLOBAL_CACHE.Inventory.IsStorageOpen():
                self._xunlai_status = "Xunlai Vault is already open."
                return
            opened = bool(GLOBAL_CACHE.Inventory.OpenXunlaiWindow())
            self._xunlai_status = "Xunlai Vault is already open." if opened else "Xunlai Vault open requested."
        except Exception as exc:
            self._xunlai_status = "Open Xunlai failed: %s" % exc
            _log(self._xunlai_status, error=True)

    def xunlai_status(self) -> str:
        return self._xunlai_status

    def toggle_colorize(self) -> None:
        profile = self.active().colorize
        profile.enabled = not profile.enabled
        self._save()
        _log("Colorize %s from the shared item context menu." % ("enabled" if profile.enabled else "disabled"))

    def active_item_operation(self) -> str | None:
        """The exclusive item mutation currently owned by this item profile runtime."""
        return self._active_item_operation

    def begin_item_operation(self, operation: str) -> bool:
        """Acquire the shared item-operation gate for Identification, Salvage, or later Inventory work."""
        if self._active_item_operation is not None:
            return False
        self._active_item_operation = operation
        return True

    def end_item_operation(self, operation: str) -> None:
        if self._active_item_operation == operation:
            self._active_item_operation = None

    def draw_context_menu_items(self, prepend_separator: bool = True) -> bool:
        """Draw the migrated item actions inside a context-menu popup."""
        if not _map_is_ready():
            return False
        import PyImGui

        from Py4GWCoreLib import GLOBAL_CACHE

        profile = self.active()
        has_identification_entries = self._has_identification_context_entries()
        has_entries = profile.context_menu_xunlai or profile.colorize.context_menu_toggle or has_identification_entries
        if not has_entries:
            return False

        if prepend_separator:
            PyImGui.separator()
        if profile.context_menu_xunlai and not GLOBAL_CACHE.Inventory.IsStorageOpen():
            if PyImGui.menu_item("Open Xunlai Vault##system_items_xunlai"):
                self.open_xunlai()
                PyImGui.close_current_popup()
        if profile.colorize.context_menu_toggle:
            label = "Disable Colorize" if profile.colorize.enabled else "Enable Colorize"
            if PyImGui.menu_item(label + "##system_items_colorize"):
                self.toggle_colorize()
                PyImGui.close_current_popup()
        self._draw_identification_context_items(self._context_item)
        return True

    def update(self) -> None:
        """Compatibility fallback for hosts without the callback service."""
        self._context_pass()
        self._colorize_pass()

    def _context_pass(self) -> None:
        if not _map_is_ready():
            return
        self._draw_context_menu()

    def _colorize_pass(self) -> None:
        if not _map_is_ready():
            return
        profile = self.active().colorize
        slots = self._monitor.scan() if profile.enabled else []
        self._draw_imgui(profile, slots)
        self._reconcile_native(profile, slots)

    def _draw_context_menu(self) -> None:
        """Inventory+'s right-click trigger, owned by the always-on System Settings host.

        It copies Inventory+'s parent-frame hit behavior, which also makes Xunlai available from
        empty inventory space.  The context monitor resolves a slot only on a right click so kit and
        single-item actions can be item-aware without coupling this callback to Colorize's timer.
        """
        import PyImGui

        from Py4GWCoreLib.FrameTree import Frame, FrameId
        from Py4GWCoreLib.enums_src.IO_enums import MouseButton

        profile = self.active()
        has_identification_entries = self._has_identification_context_entries()
        if not (profile.context_menu_xunlai or profile.colorize.context_menu_toggle or has_identification_entries):
            return

        if PyImGui.is_mouse_clicked(MouseButton.Right.value):
            self._context_item = self._context_monitor.hovered_slot()
            hit = (Frame(FrameId.InventoryBagsWindow).is_mouse_over()
                   or Frame(FrameId.InventoryWindow).is_mouse_over())
            if hit:
                PyImGui.open_popup(_CONTEXT_POPUP_ID)

        if PyImGui.begin_popup(_CONTEXT_POPUP_ID):
            self.draw_context_menu_items(prepend_separator=False)
            PyImGui.end_popup()

    def _draw_identification_context_items(self, selected_item: InventorySlot | None) -> None:
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.identification import get_controller

            get_controller().draw_context_menu_items(selected_item)
        except Exception as exc:
            _log("Identification context menu unavailable: %s" % exc, error=True)

    def _has_identification_context_entries(self) -> bool:
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.identification import get_controller

            return bool(get_controller().has_context_entries())
        except Exception:
            return False

    def _color_for(self, profile: ColorizeProfile, rarity: str) -> tuple[int, int, int, int] | None:
        if not profile.rarities.get(rarity, False):
            return None
        return profile.colors.get(rarity)

    def _draw_imgui(self, profile: ColorizeProfile, slots) -> None:
        if not profile.enabled or not (profile.imgui_frame or profile.imgui_outline):
            return
        for entry in slots:
            color = self._color_for(profile, entry.rarity)
            if color is None:
                continue
            if profile.imgui_frame:
                for frame in (entry.bag_frame, entry.inventory_frame):
                    if frame is not None:
                        frame.draw(_color(color, 25).to_color())
            if profile.imgui_outline:
                for frame in (entry.bag_frame, entry.inventory_frame):
                    if frame is not None:
                        frame.draw_outline(_color(color, 125).to_color())

    def _reconcile_native(self, profile: ColorizeProfile, slots) -> None:
        desired: dict[int, int] = {}
        if profile.enabled and profile.native_frame:
            for entry in slots:
                color = self._color_for(profile, entry.rarity)
                if color is None:
                    continue
                for frame in (entry.bag_frame, entry.inventory_frame):
                    if frame is not None:
                        desired[int(frame.frame_id)] = _color(color).to_dx_color()
        try:
            import PyUIManager

            for frame_id in set(self._native_tints) - set(desired):
                PyUIManager.UIManager.clear_item_frame_tint_by_frame_id(frame_id)
            for frame_id, color in desired.items():
                if self._native_tints.get(frame_id) != color:
                    PyUIManager.UIManager.set_item_frame_tint_by_frame_id(frame_id, color)
            self._native_tints = desired
        except Exception as exc:
            if desired:
                _log("Native Colorize unavailable: %s" % exc, error=True)
        if profile.native_outline and not self._native_outline_warned:
            self._native_outline_warned = True
            _log("Native outline Colorize is not exposed by the current native UI owner; no native outline was applied.")


_controller: Optional[InventorySettingsController] = None


def get_controller() -> InventorySettingsController:
    global _controller
    if _controller is None:
        _controller = InventorySettingsController()
    return _controller
