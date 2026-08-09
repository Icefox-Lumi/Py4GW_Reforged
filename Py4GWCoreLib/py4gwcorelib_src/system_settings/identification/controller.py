"""Standalone automatic/manual Identification runtime, driven by the active Item Profile reference."""

from typing import Optional

from Py4GWCoreLib.py4gwcorelib_src.Timer import ThrottledTimer

from . import store
from .model import IdentificationConfig


_CALLBACK = "SystemItemsIdentification"


def _log(message: str, error: bool = False) -> None:
    try:
        import PySystem

        level = PySystem.Console.MessageType.Error if error else PySystem.Console.MessageType.Info
        PySystem.Console.Log("System Settings / Identification", message, level)
    except Exception:
        pass


def _map_is_ready() -> bool:
    try:
        from Py4GWCoreLib.Map import Map

        return bool(Map.IsMapReady())
    except Exception:
        return False


class IdentificationController:
    _instance: "IdentificationController | None" = None

    def __new__(cls) -> "IdentificationController":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialise()
        return cls._instance

    def _initialise(self) -> None:
        self.config, self._legacy_pending = store.load()
        self._timer = ThrottledTimer()
        self._registered = False
        self._active = False
        self.status = ""

    def boot(self) -> None:
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.identification_filters import store as id_store

            id_store.migrate_factory_references()
        except Exception as exc:
            _log("ID filter definition migration failed: %s" % exc, error=True)
        if self._legacy_pending:
            self._migrate_legacy_filter_profile()
        self.register()

    def register(self) -> None:
        if self._registered:
            return
        try:
            import PyCallback

            from Py4GWCoreLib.py4gwcorelib_src.Profiling import ProfilingRegistry

            PyCallback.PyCallback.RemoveByName(_CALLBACK)
            PyCallback.PyCallback.Register(
                _CALLBACK,
                PyCallback.Phase.Data,
                self._pass,
                priority=99,
                context=PyCallback.Context.Update,
            )
            ProfilingRegistry().register(_CALLBACK)
            self._registered = True
        except Exception as exc:
            self.status = "Identification callback registration failed: %s" % exc
            _log(self.status, error=True)

    def save(self) -> None:
        store.save(self.config)

    def reset_timer(self) -> None:
        self._timer.Reset()

    def reload_factory(self) -> None:
        """Factory/ID-profile changes are read on the next selection; no independent cache exists."""

    def active_filter_profile_name(self) -> str:
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller as inventory

            return inventory().active().identification_profile
        except Exception:
            return ""

    def active_filter_sets(self):
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.identification_filters import store as id_store

            profile = id_store.profile_by_name(id_store.load_profiles(), self.active_filter_profile_name())
            return id_store.rule_sets_in_profile(id_store.load_rules(), profile)
        except Exception:
            return [], []

    def always_filters(self):
        return self.active_filter_sets()[0]

    def never_filters(self):
        return self.active_filter_sets()[1]

    def timer_status(self) -> str:
        if not self._registered:
            return "Automatic callback is not registered. Check System Settings / Identification errors."
        if not self.config.auto_enabled:
            return "Automatic identification is disabled."
        if self._active:
            return "Automatic identification is running."
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller as inventory

            operation = inventory().active_item_operation()
            if operation:
                return "Waiting for %s to finish." % operation
        except Exception:
            pass
        if not _map_is_ready():
            return "Waiting for the map to finish loading."
        if not any(self.config.auto_rarities.values()) and not self.always_filters():
            return "Automatic identification has no selected rarities or Always ID filters."
        remaining = max(0, int(self.config.interval_ms) - int(self._timer.timer.GetElapsedTime()))
        return "Next automatic identification pass in %.1f s." % (remaining / 1000.0)

    def _pass(self) -> None:
        self._timer.SetThrottleTime(max(1000, int(self.config.interval_ms)))
        if not self.config.auto_enabled or self._active or not _map_is_ready():
            return
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller as inventory

            if inventory().active_item_operation():
                return
        except Exception:
            return
        if self._timer.IsExpired():
            self._timer.Reset()
            rarities = [rarity for rarity, enabled in self.config.auto_rarities.items() if enabled]
            if rarities or self.always_filters():
                self.identify_rarities(rarities, "Automatic identification", include_always=True)

    def identify_rarities(self, rarities: list[str], label: str, include_always: bool = False) -> bool:
        item_ids = self._eligible_items(set(rarities), include_always=include_always)
        if not item_ids:
            self.status = "%s: no eligible unidentified items." % label
            return False
        return self._queue(item_ids, label)

    def identify_item(self, item_id: int) -> bool:
        item_ids = self._eligible_items(None, [item_id])
        if not item_ids:
            self.status = "Identify item: item is identified, excluded, or unavailable."
            return False
        return self._queue(item_ids, "Identify item")

    def _queue(self, item_ids: list[int], label: str) -> bool:
        owner = None
        acquired = False
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller as inventory

            owner = inventory()
            if self._active or not owner.begin_item_operation("identification"):
                self.status = "%s is unavailable while %s is running." % (label, owner.active_item_operation())
                return False
            acquired = True
            if int(GLOBAL_CACHE.Inventory.GetFirstIDKit()) == 0:
                owner.end_item_operation("identification")
                acquired = False
                self.status = "%s: no identification kit available." % label
                return False
            self._active = True
            self.status = "%s queued for %d item(s)." % (label, len(item_ids))
            GLOBAL_CACHE.Coroutines.append(self._run(item_ids))
            return True
        except Exception as exc:
            self._active = False
            if acquired and owner is not None:
                owner.end_item_operation("identification")
            self.status = "%s failed to queue: %s" % (label, exc)
            _log(self.status, error=True)
            return False

    def _run(self, item_ids: list[int]):
        try:
            from Py4GWCoreLib.Routines import Routines

            yield from Routines.Yield.Items.IdentifyItemsAndVerify(item_ids, log=True)
        except Exception as exc:
            self.status = "Identification failed: %s" % exc
            _log(self.status, error=True)
        finally:
            self._active = False
            try:
                from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller as inventory

                inventory().end_item_operation("identification")
            except Exception:
                pass

    def _eligible_items(
        self,
        rarities: set[str] | None,
        candidates: list[int] | None = None,
        include_always: bool = False,
    ) -> list[int]:
        from Py4GWCoreLib import GLOBAL_CACHE, Item
        from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.matcher import any_match

        always_rules, never_rules = self.active_filter_sets()
        source = candidates if candidates is not None else GLOBAL_CACHE.Inventory.GetAllInventoryItemIds()
        selected: list[int] = []
        seen: set[int] = set()
        for raw_id in source:
            item_id = int(raw_id or 0)
            if item_id == 0 or item_id in seen:
                continue
            seen.add(item_id)
            try:
                item = Item.item_instance(item_id)
                if item is None or not item.is_inventory_item or item.is_identified:
                    continue
                if item.is_id_kit or item.is_salvage_kit:
                    continue
                if any_match(never_rules, item_id, int(item.model_id)):
                    continue
                matches_always = include_always and any_match(always_rules, item_id, int(item.model_id))
                if rarities is not None and item.rarity.name not in rarities and not matches_always:
                    continue
            except Exception:
                continue
            selected.append(item_id)
        return selected

    def is_excluded(self, item_id: int) -> bool:
        try:
            from Py4GWCoreLib import Item
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.matcher import any_match

            item = Item.item_instance(item_id)
            return bool(item is not None and any_match(self.never_filters(), item_id, int(item.model_id)))
        except Exception:
            return False

    def has_context_entries(self) -> bool:
        return bool(self.config.menu_identify_single or any(self.config.menu_rarities.values())
                    or self.config.menu_identify_all)

    def draw_context_menu_items(self, selected_item) -> bool:
        import PyImGui

        shown = False
        if selected_item is not None and selected_item.is_id_kit:
            from Py4GWCoreLib.py4gwcorelib_src.Color import ColorPalette

            for rarity, enabled in self.config.menu_rarities.items():
                if not enabled:
                    continue
                PyImGui.push_style_color(PyImGui.ImGuiCol.Text,
                                         ColorPalette.GetColor("GW_%s" % rarity).to_tuple_normalized())
                clicked = PyImGui.menu_item("Identify %s items##identification_%s" % (rarity, rarity))
                PyImGui.pop_style_color(1)
                if clicked:
                    self.identify_rarities([rarity], "Identify %s items" % rarity)
                    PyImGui.close_current_popup()
                shown = True
            if self.config.menu_identify_all:
                if PyImGui.menu_item("Identify all configured items##identification_all"):
                    self.identify_rarities([rarity for rarity, on in self.config.menu_all_rarities.items() if on],
                                           "Identify all configured items")
                    PyImGui.close_current_popup()
                shown = True
        elif (selected_item is not None and not selected_item.is_identified and not selected_item.is_id_kit
              and not selected_item.is_salvage_kit):
            if self.is_excluded(selected_item.item_id):
                from Py4GWCoreLib.py4gwcorelib_src.Color import ColorPalette

                PyImGui.text_colored("Excluded by the active ID Filter Profile - this item will not be identified.",
                                     ColorPalette.GetColor("red").to_tuple_normalized())
                shown = True
            elif self.config.menu_identify_single and PyImGui.menu_item("Identify this item##identification_single"):
                self.identify_item(selected_item.item_id)
                PyImGui.close_current_popup()
                shown = True
        if shown:
            PyImGui.separator()
        return shown

    def _migrate_legacy_filter_profile(self) -> None:
        """Create an ID Filter Profile for the legacy model blacklist and point existing Item Profiles at it."""
        try:
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.identification_filters import store as id_store
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.identification_filters.model import IdentificationFilterProfile
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.model import MATCH_ANY, Rule
            from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller as inventory

            name = "Imported Inventory+ Identification"
            profiles = id_store.load_profiles()
            profile = id_store.profile_by_name(profiles, name)
            if profile is None:
                profile = IdentificationFilterProfile(name=name)
                models = store.legacy_model_blacklist()
                if models:
                    rules = id_store.load_rules()
                    rule = Rule(id=id_store.next_rule_id(rules), name="Identification: imported model blacklist",
                                mode=MATCH_ANY, model_ids=tuple(models))
                    rules.append(rule)
                    id_store.save_rules(rules)
                    profile.never_filter_ids.append(rule.id)
                profiles.append(profile)
                id_store.save_profiles(profiles)
            inventory_controller = inventory()
            for item_profile in inventory_controller.profiles():
                if not item_profile.identification_profile:
                    item_profile.identification_profile = profile.name
            inventory_controller.save_active()
            store.save(self.config, migrated=True)
            self._legacy_pending = False
        except Exception as exc:
            self.status = "Legacy Identification migration failed: %s" % exc
            _log(self.status, error=True)


_controller: Optional[IdentificationController] = None


def get_controller() -> IdentificationController:
    global _controller
    if _controller is None:
        _controller = IdentificationController()
    return _controller
