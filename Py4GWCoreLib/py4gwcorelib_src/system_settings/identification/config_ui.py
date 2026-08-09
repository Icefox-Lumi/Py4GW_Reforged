"""Standalone Identification runtime options; Item Profiles choose the separate ID Filter Profile."""

import PyImGui

from .controller import get_controller
from .model import RARITIES


GRAY = (0.66, 0.67, 0.70, 1.0)


def add_sections(win, group) -> None:
    win.add_section(group, "Identification", draw)


def draw() -> None:
    controller = get_controller()
    config = controller.config
    changed = False
    enabled = PyImGui.checkbox("Enable automatic identification##identification_auto", config.auto_enabled)
    if enabled != config.auto_enabled:
        config.auto_enabled = enabled
        changed = True
    interval = PyImGui.slider_int("Automatic interval (ms)##identification_interval", config.interval_ms, 1000, 60000)
    if interval != config.interval_ms:
        config.interval_ms = max(1000, int(interval))
        changed = True
    PyImGui.text_colored(controller.timer_status(), GRAY)
    PyImGui.text_colored("The active Item Profile supplies the ID Filter Profile; matching rules prevent identification.", GRAY)
    PyImGui.separator()
    PyImGui.text("Automatic rarities")
    changed = _rarities("id_auto", config.auto_rarities, changed)
    PyImGui.separator()
    PyImGui.text("Context menu")
    single = PyImGui.checkbox("Show Identify this item for an unidentified item##identification_single",
                              config.menu_identify_single)
    if single != config.menu_identify_single:
        config.menu_identify_single = single
        changed = True
    PyImGui.text_colored("Identification-kit actions use these rarity choices.", GRAY)
    changed = _rarities("id_menu", config.menu_rarities, changed)
    all_enabled = PyImGui.checkbox("Show Identify all configured items##identification_all", config.menu_identify_all)
    if all_enabled != config.menu_identify_all:
        config.menu_identify_all = all_enabled
        changed = True
    if config.menu_identify_all:
        PyImGui.indent(18)
        changed = _rarities("id_menu_all", config.menu_all_rarities, changed)
        PyImGui.unindent(18)
    if changed:
        controller.save()
        controller.reset_timer()
    if controller.status:
        PyImGui.text_colored(controller.status, GRAY)


def _rarities(namespace: str, values: dict[str, bool], changed: bool) -> bool:
    for rarity in RARITIES:
        current = bool(values.get(rarity, False))
        picked = PyImGui.checkbox("%s##%s_%s" % (rarity, namespace, rarity), current)
        if picked != current:
            values[rarity] = bool(picked)
            changed = True
    return changed
