"""Author independent ID filters and the profiles that select them."""

import PyImGui

from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory import config_ui as factory_ui
from Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.model import Rule

from . import store
from .model import IdentificationFilterProfile


GRAY = (0.66, 0.67, 0.70, 1.0)
_state = {"new_name": ""}


def add_sections(win, group) -> None:
    """Expose the same author/select workflow as Loot Filters with independent ID definitions."""
    win.add_section(group, "ID Filters")
    win.add_tab("ID Filters", "Profiles", draw_profiles)
    win.add_tab("ID Filters", "Filters", draw_filters)


def _replace_item_profile_reference(old_name: str, new_name: str) -> None:
    """Keep reference-only Item Profiles valid when this global profile is renamed or removed."""
    try:
        from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller

        controller = get_controller()
        changed = False
        for item_profile in controller.profiles():
            if item_profile.identification_profile == old_name:
                item_profile.identification_profile = new_name
                changed = True
        if changed:
            controller.save_active()
    except Exception:
        # The profile document is still the source of truth. The next Settings load will surface
        # a missing selection as "(none)" if the inventory runtime is not available yet.
        pass


def _active_item_profile() -> tuple[object | None, str]:
    """Return the active Item Profile and a readable label without duplicating its state."""
    try:
        from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller

        profile = get_controller().active()
        return profile, str(profile.name)
    except Exception:
        return None, "unavailable"


def _use_for_active_item_profile(name: str) -> None:
    try:
        from Py4GWCoreLib.py4gwcorelib_src.system_settings.inventory import get_controller

        controller = get_controller()
        controller.active().identification_profile = name
        controller.save_active()
    except Exception:
        pass


def draw_profiles() -> None:
    profiles = store.load_profiles()
    rules = store.load_rules()
    active_item_profile, active_item_profile_name = _active_item_profile()
    PyImGui.text_colored("Active Item Profile: %s" % active_item_profile_name, GRAY)
    PyImGui.text_colored(
        "Create ID rules in the Filters tab, attach them to an ID profile here, then use that profile for the active Item Profile.",
        GRAY,
    )
    PyImGui.separator()
    _state["new_name"] = PyImGui.input_text("New ID filter profile##id_filter_profile_name", _state["new_name"])
    PyImGui.same_line(0, 8)
    if PyImGui.button("Create##id_filter_profile_create"):
        name = _state["new_name"].strip()
        if name and store.profile_by_name(profiles, name) is None:
            profiles.append(IdentificationFilterProfile(name=name))
            store.save_profiles(profiles)
            _state["new_name"] = ""
            return
    PyImGui.text_colored("Always ID overrides automatic rarity selection. Never ID is a hard veto for every ID action.", GRAY)
    if not profiles:
        PyImGui.text_colored("No ID filter profiles yet.", GRAY)
        return
    for index, profile in enumerate(list(profiles)):
        if not PyImGui.collapsing_header("%s  (always: %d, never: %d)###id_filter_profile_%s" % (
            profile.name, len(profile.always_filter_ids), len(profile.never_filter_ids), profile.name
        )):
            continue
        active_reference = getattr(active_item_profile, "identification_profile", "")
        if active_reference == profile.name:
            PyImGui.text_colored("Used by the active Item Profile.", GRAY)
        elif PyImGui.button("Use for active Item Profile##id_filter_profile_use_%s" % profile.name):
            _use_for_active_item_profile(profile.name)
            return
        name = PyImGui.input_text("Name##id_filter_profile_rename_%s" % profile.name, profile.name)
        if name != profile.name and name.strip() and store.profile_by_name(profiles, name.strip()) is None:
            new_name = name.strip()
            profiles[index] = IdentificationFilterProfile(
                name=new_name,
                always_filter_ids=list(profile.always_filter_ids),
                never_filter_ids=list(profile.never_filter_ids),
            )
            store.save_profiles(profiles)
            _replace_item_profile_reference(profile.name, new_name)
            return
        for label, attribute, opposite, suffix in (
            ("Always ID these filters", "always_filter_ids", "never_filter_ids", "always"),
            ("Never ID these filters", "never_filter_ids", "always_filter_ids", "never"),
        ):
            if not PyImGui.collapsing_header("%s  (%d)###id_filter_%s_%s" % (
                label, len(getattr(profile, attribute)), suffix, profile.name
            )):
                continue
            for rule in rules:
                selected = rule.id in getattr(profile, attribute)
                if PyImGui.checkbox("%s##id_filter_%s_%s_%s" % (rule.name, suffix, profile.name, rule.id), selected) == selected:
                    continue
                chosen = list(getattr(profile, attribute))
                other = [rule_id for rule_id in getattr(profile, opposite) if rule_id != rule.id]
                chosen = [rule_id for rule_id in chosen if rule_id != rule.id] if selected else chosen + [rule.id]
                profiles[index] = IdentificationFilterProfile(
                    name=profile.name,
                    always_filter_ids=chosen if attribute == "always_filter_ids" else other,
                    never_filter_ids=chosen if attribute == "never_filter_ids" else other,
                )
                store.save_profiles(profiles)
                return
        if not rules:
            PyImGui.text_colored("No ID rules yet. Create one in this section's Filters tab.", GRAY)
        if PyImGui.small_button("Duplicate##id_filter_profile_duplicate_%s" % profile.name):
            base = profile.name + " Copy"
            suffix = 1
            copy_name = "%s %d" % (base, suffix)
            while store.profile_by_name(profiles, copy_name) is not None:
                suffix += 1
                copy_name = "%s %d" % (base, suffix)
            profiles.insert(index + 1, IdentificationFilterProfile(
                name=copy_name,
                always_filter_ids=list(profile.always_filter_ids),
                never_filter_ids=list(profile.never_filter_ids),
            ))
            store.save_profiles(profiles)
            return
        PyImGui.same_line(0, 8)
        if PyImGui.small_button("Delete##id_filter_profile_delete_%s" % profile.name):
            profiles.pop(index)
            store.save_profiles(profiles)
            _replace_item_profile_reference(profile.name, "")
            return


def draw() -> None:
    """Compatibility entry point for callers that previously used the single profile surface."""
    draw_profiles()


def draw_filters() -> None:
    """ID-owned definitions using the Factory's proven rule editor and matcher scheme."""
    current = store.load_rules()
    if PyImGui.button("New ID filter##id_filters_new"):
        current.append(Rule(id=store.next_rule_id(current), name="ID Filter %d" % (len(current) + 1)))
        store.save_rules(current)
        return
    PyImGui.same_line(0, 8)
    PyImGui.text_colored("%d ID filter(s)" % len(current), GRAY)
    PyImGui.text_colored("These definitions belong only to Identification; they use the same criteria scheme as Loot Filters.", GRAY)
    PyImGui.separator()
    if not current:
        PyImGui.text_colored("None yet. Create one above.", GRAY)
        return
    for index, rule in enumerate(list(current)):
        enabled = PyImGui.checkbox("##id_filter_enabled_%s" % rule.id, rule.enabled)
        if enabled != rule.enabled:
            current[index] = rule.with_enabled(enabled)
            store.save_rules(current)
            return
        PyImGui.same_line(0, 6)
        if not PyImGui.collapsing_header("%d. %s###id_filter_header_%s" % (index + 1, rule.name, rule.id)):
            continue
        typed = PyImGui.input_text("Name##id_filter_name_%s" % rule.id, rule.name)
        if typed != rule.name and typed.strip():
            current[index] = rule.renamed(typed.strip())
            store.save_rules(current)
            return
        replacement = factory_ui._draw_criteria(rule, index)
        if replacement is not None:
            current[index] = replacement
            store.save_rules(current)
            return
        if rule.is_empty():
            PyImGui.text_colored("No conditions set - this filter matches nothing.", (0.79, 0.63, 0.29, 1.0))
        PyImGui.separator()
        factory_ui._draw_preview(rule)
        PyImGui.separator()
        if PyImGui.small_button("Duplicate##id_filter_duplicate_%s" % rule.id):
            copy = Rule.from_dict(rule.to_dict())
            current.insert(index + 1, Rule.from_dict({
                **copy.to_dict(),
                "id": store.next_rule_id(current),
                "name": rule.name + " (copy)",
            }))
            store.save_rules(current)
            return
        PyImGui.same_line(0, 6)
        if index > 0 and PyImGui.small_button("Move up##id_filter_up_%s" % rule.id):
            current[index - 1], current[index] = current[index], current[index - 1]
            store.save_rules(current)
            return
        PyImGui.same_line(0, 6)
        if PyImGui.small_button("Delete##id_filter_delete_%s" % rule.id):
            current.pop(index)
            store.save_rules(current)
            return
