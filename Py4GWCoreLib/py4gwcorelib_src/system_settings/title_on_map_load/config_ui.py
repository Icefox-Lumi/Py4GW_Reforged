"""System Settings UI for automatic title selection."""

import PyImGui

from . import model
from .controller import TitleOnMapLoadController
from .controller import get_controller


_MUTED = (0.60, 0.60, 0.65, 1.0)


def _draw_title_on_map_load(controller: TitleOnMapLoadController) -> None:
    config = controller.config
    enabled = PyImGui.checkbox("Enable title on map load##title_on_map_load_enabled", config.enabled)
    if enabled != config.enabled:
        controller.set_enabled(enabled)

    PyImGui.text_wrapped(
        "Sets the matching reputation title after entering a supported explorable map. "
        "Quest overrides take priority over the map list."
    )
    PyImGui.text_colored("Supported maps", _MUTED)
    PyImGui.separator()

    for entry in model.TITLE_MAP_ENTRIES:
        header = "%s (%d maps)###title_maps_%s" % (
            entry.title_name,
            len(entry.map_names),
            int(entry.title_id),
        )
        if not PyImGui.collapsing_header(header):
            continue
        for map_name in entry.map_names:
            PyImGui.bullet_text(map_name)
        if entry.map_ids:
            PyImGui.text_colored("Alternate map IDs: %s" % ", ".join(str(map_id) for map_id in entry.map_ids), _MUTED)


def add_sections(win, group) -> None:
    """Add title selection and its supported-map reference to Map & Missions."""

    controller = get_controller()
    win.add_section(group, "Title On Map Load", lambda c=controller: _draw_title_on_map_load(c))
