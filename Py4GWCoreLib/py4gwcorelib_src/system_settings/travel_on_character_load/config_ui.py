"""System Settings UI for automatic travel after character changes."""

import PyImGui

from Py4GWCoreLib import ImGui
from Py4GWCoreLib.enums_src.Map_enums import outposts

from . import model
from .controller import TravelOnCharacterLoadController
from .controller import get_controller


_MUTED = (0.60, 0.60, 0.65, 1.0)
_DESTINATION_LABELS = ("Guild Hall", "Outpost")
_outpost_search = ""


def _outpost_options() -> list[tuple[int, str]]:
    return sorted(
        [(int(map_id), name) for map_id, name in outposts.items() if not name.lower().startswith("guild hall -")],
        key=lambda item: (item[1].casefold(), item[0]),
    )


def _outpost_initials(name: str) -> str:
    return "".join(word[0] for word in name.split() if word)


def _filter_outpost_options(options: list[tuple[int, str]], search: str) -> list[tuple[int, str]]:
    needle = search.strip().casefold()
    if not needle:
        return options
    return [
        (map_id, name)
        for map_id, name in options
        if needle in name.casefold()
        or needle in _outpost_initials(name).casefold()
        or needle in str(map_id)
    ]


def _draw_travel_on_character_load(controller: TravelOnCharacterLoadController) -> None:
    global _outpost_search

    config = controller.config

    first_load = PyImGui.checkbox(
        "Enable travel on first character load##travel_character_first_load",
        config.travel_on_first_load,
    )
    if first_load != config.travel_on_first_load:
        controller.set_travel_on_first_load(first_load)

    character_switch = PyImGui.checkbox(
        "Enable travel on character switch##travel_character_switch",
        config.travel_on_character_switch,
    )
    if character_switch != config.travel_on_character_switch:
        controller.set_travel_on_character_switch(character_switch)

    PyImGui.text_wrapped(
        "Each enabled trigger runs once after the character and map are ready. " "The settings are account-local."
    )
    PyImGui.separator()

    destination_index = 0 if config.destination == model.DESTINATION_GUILD_HALL else 1
    new_destination_index = PyImGui.combo(
        "Travel destination##travel_character_destination",
        destination_index,
        list(_DESTINATION_LABELS),
    )
    new_destination = model.DESTINATION_GUILD_HALL if new_destination_index == 0 else model.DESTINATION_OUTPOST
    if new_destination != config.destination:
        controller.set_destination(new_destination)

    if config.destination == model.DESTINATION_OUTPOST:
        all_options = _outpost_options()
        option_ids = [map_id for map_id, _ in all_options]
        if option_ids and config.outpost_id not in option_ids:
            controller.set_outpost_id(option_ids[0])

        PyImGui.push_item_width(320)
        search_changed, new_search = ImGui.search_field(
            "##travel_character_outpost_search",
            _outpost_search,
            "Search outposts by name or map ID...",
            PyImGui.InputTextFlags.AutoSelectAll,
        )
        PyImGui.pop_item_width()
        if search_changed:
            _outpost_search = new_search

        options = _filter_outpost_options(all_options, _outpost_search)
        option_ids = [map_id for map_id, _ in options]
        option_labels = ["%s (%d)" % (name, map_id) for map_id, name in options]
        if option_ids:
            current_index = option_ids.index(config.outpost_id) if config.outpost_id in option_ids else 0
            new_index = PyImGui.combo(
                "Outpost##travel_character_outpost",
                current_index,
                option_labels,
            )
            if new_index != current_index and 0 <= new_index < len(option_ids):
                controller.set_outpost_id(option_ids[new_index])
        elif _outpost_search.strip():
            PyImGui.text_colored("No outposts match the search.", _MUTED)
        else:
            PyImGui.text_colored("No outposts are available in the map catalog.", _MUTED)


def add_sections(win, group) -> None:
    """Add automatic travel settings to Map & Missions."""

    controller = get_controller()
    win.add_section(
        group,
        "Travel On Character Load",
        lambda c=controller: _draw_travel_on_character_load(c),
    )
