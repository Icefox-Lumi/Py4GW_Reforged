"""System Settings > Items sections for the first Inventory+ migration slice."""

import PyImGui

from Py4GWCoreLib.py4gwcorelib_src.Color import Color
from Py4GWCoreLib.py4gwcorelib_src.system_settings.identification_filters import store as identification_filter_store

from . import model
from .controller import InventorySettingsController, get_controller


MUTED = (0.66, 0.67, 0.70, 1.0)
WARN = (0.86, 0.65, 0.28, 1.0)


def _rgba(color: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    return Color(*color).to_tuple_normalized()


def _to_color(value) -> tuple[int, int, int, int]:
    return tuple(Color.from_tuple_normalized(tuple(value)).to_tuple())


def add_sections(win, group) -> None:
    controller = get_controller()
    win.add_section(group, "Item Profiles", lambda: _draw_profiles(controller))
    win.add_section(group, "Open Xunlai Vault", lambda: _draw_xunlai(controller))
    win.add_section(group, "Colorize", lambda: _draw_colorize(controller))


def _draw_profiles(controller: InventorySettingsController) -> None:
    profiles = controller.profiles()
    names = [profile.name for profile in profiles]
    current = names.index(controller.active().name) if controller.active().name in names else 0
    selected = PyImGui.combo("Active profile##items_profile", current, names)
    if selected != current:
        controller.set_active(names[selected])
    if PyImGui.button("New profile##items_new"):
        controller.create_profile()
    PyImGui.same_line(0, 8)
    if PyImGui.button("Duplicate active##items_duplicate"):
        controller.duplicate_active()
    identification_profiles = identification_filter_store.load_profiles()
    id_names = ["(none)"] + [profile.name for profile in identification_profiles]
    id_current = id_names.index(controller.active().identification_profile) \
        if controller.active().identification_profile in id_names else 0
    id_picked = PyImGui.combo("ID filter profile##items_identification_profile", id_current, id_names)
    if id_picked != id_current:
        controller.active().identification_profile = "" if id_picked == 0 else id_names[id_picked]
        controller.save_active()
    PyImGui.text_colored("Item Profiles reference separate ID Filter Profiles; edit those under Items > ID Filter Profiles.", MUTED)
    PyImGui.text_colored("Salvage and Inventory filter-profile references remain for their migrations.", MUTED)


def _draw_xunlai(controller: InventorySettingsController) -> None:
    PyImGui.text_wrapped("Open the Xunlai Vault without enabling an automatic handler.")
    profile = controller.active()
    visible = profile.context_menu_xunlai
    new_visible = PyImGui.checkbox("Show Open Xunlai in item context menu##items_xunlai_menu", visible)
    if new_visible != visible:
        profile.context_menu_xunlai = new_visible
        controller.save_active()
    if PyImGui.button("Open Xunlai Vault##items_xunlai"):
        controller.open_xunlai()
    status = controller.xunlai_status()
    if status:
        PyImGui.text_colored(status, MUTED)


def _draw_colorize(controller: InventorySettingsController) -> None:
    profile = controller.active().colorize
    changed = False
    profile.enabled, changed = _checkbox("Enable Colorize##items_colorize", profile.enabled, changed)
    profile.context_menu_toggle, changed = _checkbox(
        "Show Colorize toggle in item context menu##items_colorize_menu",
        profile.context_menu_toggle,
        changed,
    )
    PyImGui.text_colored("Bags and the regular inventory are monitored as the same item sources. If both are open, both are tinted.", MUTED)
    PyImGui.separator()
    PyImGui.text("Render targets")
    for label, attr in (("ImGui frame", "imgui_frame"), ("ImGui outline", "imgui_outline"),
                        ("Native frame", "native_frame"), ("Native outline", "native_outline")):
        value = bool(getattr(profile, attr))
        new_value = PyImGui.checkbox("%s##items_%s" % (label, attr), value)
        if new_value != value:
            setattr(profile, attr, new_value)
            changed = True
    if profile.native_outline:
        PyImGui.text_colored("Native outline is not available from the current native UI binding; the option is recorded but has no effect.", WARN)
    PyImGui.separator()
    PyImGui.text("Rarities")
    for rarity in model.RARITIES:
        enabled = bool(profile.rarities.get(rarity, False))
        new_enabled = PyImGui.checkbox("%s##items_rarity_%s" % (rarity, rarity), enabled)
        if new_enabled != enabled:
            profile.rarities[rarity] = new_enabled
            changed = True
        picked = _to_color(PyImGui.color_edit4("%s color##items_color_%s" % (rarity, rarity), _rgba(profile.colors[rarity])))
        if picked != profile.colors[rarity]:
            profile.colors[rarity] = picked
            changed = True
    if changed:
        controller.save_active()


def _checkbox(label: str, value: bool, changed: bool) -> tuple[bool, bool]:
    new_value = PyImGui.checkbox(label, value)
    return bool(new_value), changed or new_value != value
