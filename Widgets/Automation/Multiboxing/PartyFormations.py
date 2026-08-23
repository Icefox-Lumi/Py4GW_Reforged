from __future__ import annotations

import json
import math
import os
import time
import traceback
from typing import Any
from typing import cast

import PyImGui

import PySystem
from Py4GWCoreLib.HeroAI.party_formations import ASSIGNMENT_ACCOUNT
from Py4GWCoreLib.HeroAI.party_formations import ASSIGNMENT_HERO
from Py4GWCoreLib.HeroAI.party_formations import ASSIGNMENT_UNASSIGNED
from Py4GWCoreLib.HeroAI.party_formations import CONFIG_BACKUP_LIMIT
from Py4GWCoreLib.HeroAI.party_formations import MAX_FORMATION_SPOTS
from Py4GWCoreLib.HeroAI.party_formations import TARGET_MODE_IDENTITY
from Py4GWCoreLib.HeroAI.party_formations import TARGET_MODE_PARTY_SLOT
from Py4GWCoreLib.HeroAI.party_formations import FormationCooldowns
from Py4GWCoreLib.HeroAI.party_formations import FormationAssignment
from Py4GWCoreLib.HeroAI.party_formations import PartyFormation
from Py4GWCoreLib.HeroAI.party_formations import LEADER_PARTY_POSITION
from Py4GWCoreLib.HeroAI.party_formations import PREFLIGHT_STATUS_WOULD_TARGET
from Py4GWCoreLib.HeroAI.party_formations import apply_formation
from Py4GWCoreLib.HeroAI.party_formations import assignment_from_member
from Py4GWCoreLib.HeroAI.party_formations import assignment_has_target
from Py4GWCoreLib.HeroAI.party_formations import assignment_spot_label
from Py4GWCoreLib.HeroAI.party_formations import capture_assignment_offset
from Py4GWCoreLib.HeroAI.party_formations import clear_assignment_target
from Py4GWCoreLib.HeroAI.party_formations import clear_formation
from Py4GWCoreLib.HeroAI.party_formations import config_load_warning
from Py4GWCoreLib.HeroAI.party_formations import create_empty_formation
from Py4GWCoreLib.HeroAI.party_formations import default_spot_label
from Py4GWCoreLib.HeroAI.party_formations import export_formation_shape
from Py4GWCoreLib.HeroAI.party_formations import formation_has_assigned_targets
from Py4GWCoreLib.HeroAI.party_formations import get_available_members
from Py4GWCoreLib.HeroAI.party_formations import import_formation_shape
from Py4GWCoreLib.HeroAI.party_formations import imgui_key_code_for_key
from Py4GWCoreLib.HeroAI.party_formations import list_config_backups
from Py4GWCoreLib.HeroAI.party_formations import load_formations
from Py4GWCoreLib.HeroAI.party_formations import preflight_apply_snapshot
from Py4GWCoreLib.HeroAI.party_formations import preflight_assignment_offset_warning
from Py4GWCoreLib.HeroAI.party_formations import restore_latest_config_backup
from Py4GWCoreLib.HeroAI.party_formations import save_formations
from Py4GWCoreLib.HeroAI.party_formations import get_ui_migration_seed
from Py4GWCoreLib.HeroAI.party_formations import load_geometry_preset_library
from Py4GWCoreLib.HeroAI.party_formations import mark_ui_migration_seed_consumed
from Py4GWCoreLib.HeroAI.party_formations import migrate_legacy_bundle
from Py4GWCoreLib.HeroAI.party_formations import save_geometry_preset_library
from Py4GWCoreLib.enums_src.GameData_enums import Range
from Py4GWCoreLib.enums_src.IO_enums import Key
from Py4GWCoreLib.enums_src.IO_enums import ModifierKey
from Py4GWCoreLib.HotkeyManager import HOTKEY_MANAGER
from Py4GWCoreLib.ImGui_src.ImGuisrc import ImGui
from Py4GWCoreLib.ImGui_src.types import Alignment
from Py4GWCoreLib.py4gwcorelib_src.Color import Color
from Py4GWCoreLib.py4gwcorelib_src.FileDialog import FileDialog

MODULE_NAME = 'Party Formations'
MODULE_ICON = 'Assets\\Textures\\Module_Icons\\Party Formations.png'
MODULE_CATEGORY = 'Automation'
MODULE_TAGS = ['Automation', 'Multiboxing', 'HeroAI', 'Formations']

formations: list[PartyFormation] = []
selected_formation_index = 0
selected_member_index = 0
last_status = 'Ready.'
last_status_needs_attention = False
status_lines: list[str] = []
status_line_attention: list[bool] = []
action_history: list[dict[str, object]] = []
registered_hotkey_ids: set[str] = set()
cooldowns = FormationCooldowns()
loaded_once = False
members_cache: list[dict] = []
last_member_refresh = 0.0
last_member_refresh_failed = 0.0
active_formation_ids: set[str] = set()
latched_hotkey_ids: set[str] = set()
last_runtime_signature = None
TARGET_MODE_CONFIRM_POPUP_ID = 'Confirm Target Mode Change##PartyFormations'
GEOMETRY_PRESET_OVERWRITE_POPUP_ID = 'Confirm Preset Overwrite##PartyFormations'
GEOMETRY_PRESET_DELETE_POPUP_ID = 'Confirm Preset Delete##PartyFormations'
pending_target_mode_formation_id = ''
pending_target_mode = ''
pending_target_mode_label = ''
pending_geometry_preset_overwrite: dict | None = None
pending_geometry_preset_overwrite_details: list[str] = []
pending_geometry_preset_delete_name = ''
pending_geometry_preset_delete_index = -1
pending_destructive_button_key = ''
pending_destructive_button_expires_at_ms = 0
canvas_selected_assignment_index = 0
canvas_selected_assignment_indexes: set[int] = set()
canvas_dragging_assignment_index = -1
canvas_drag_dirty = False
canvas_drag_owner_id = ''
canvas_drag_owner_formation_id = ''
canvas_drag_active = False
canvas_drag_start_mouse_pos: tuple[float, float] = (0.0, 0.0)
canvas_drag_cursor_to_spot: tuple[float, float] = (0.0, 0.0)
canvas_editor_open = False
canvas_editor_formation_id = ''
main_window_ini_key = ''
canvas_editor_window_ini_key = ''
floating_ui_ini_key = ''
show_main_window = False
expand_main_window_on_next_show = True
floating_button = None
legacy_import_dialog = FileDialog()
legacy_ui_seed_loaded = False
legacy_ui_seed_account_email = ''
legacy_ui_seed_state: dict[str, object] = {}
legacy_ui_seed_windows_seen: set[str] = set()
canvas_position_draft_formation_id = ''
canvas_position_draft_offsets: list[tuple[float, float]] = []
canvas_position_draft_dirty = False
canvas_range_guide_index = 0
canvas_range_guide_all_spots = False
canvas_editor_last_canvas_size: tuple[float, float] = (0.0, 0.0)
canvas_preset_name_input = ''
canvas_preset_selected_index = 0
canvas_preset_rename_active = False
canvas_preset_rename_text = ''
canvas_preset_rename_index = -1
canvas_preset_rename_original_name = ''
canvas_preset_rename_signature = ''
canvas_snap_enabled = False
canvas_snap_grid_index = 1
apply_preview_row_mode_index = 0
formation_name_edit_formation_id = ''
formation_name_edit_text = ''
formation_filter_text = ''
formation_filter_pick_index = 0

ACTION_HISTORY_LIMIT = 24
CANVAS_HEIGHT = 360.0
CANVAS_MIN_WIDTH = 260.0
CANVAS_MIN_HEIGHT = 260.0
CANVAS_MAX_WIDTH = 380.0
CANVAS_EDITOR_HEIGHT = 540.0
CANVAS_EDITOR_MAX_WIDTH = 760.0
CANVAS_SCALE = 0.35
CANVAS_SPOT_RADIUS = 13.0
CANVAS_ANCHOR_RADIUS = 10.0
CANVAS_DRAG_THRESHOLD = 5.0
CANVAS_POSITION_DIRTY_TOLERANCE = 0.001
CANVAS_SNAP_GRID_SIZES = (25.0, 50.0, 100.0)
CANVAS_SNAP_GRID_LABELS = ['25', '50', '100']
CANVAS_NUDGE_DEFAULT_STEP = 25.0
APPLY_PREVIEW_ROW_MODE_LABELS = ['Show all', 'Issues first']
APPLY_PREVIEW_ROW_MODE_SHOW_ALL = 0
APPLY_PREVIEW_ROW_MODE_ISSUES_FIRST = 1
DESTRUCTIVE_BUTTON_CONFIRM_TIMEOUT_MS = 5000
CANVAS_RANGE_GUIDE_NEARBY_ANOMALY = 240.0
CANVAS_RANGE_GUIDE_EARSHOT_ANOMALY = 1000.0
CANVAS_RANGE_GUIDE_SPIRIT_EXACT = 2512.0
CANVAS_RANGE_GUIDE_PARTY_EXACT = 5020.0
WINDOW_INI_PATH = 'Widgets/PartyFormations'
MAIN_WINDOW_INI_FILENAME = 'PartyFormations.ini'
CANVAS_EDITOR_WINDOW_INI_FILENAME = 'PartyFormationCanvasEditor.ini'
FLOATING_UI_INI_FILENAME = 'PartyFormationsFloatingIcon.ini'
FLOATING_ICON_WINDOW_ID = '##party_formations_floating_icon_button'
FLOATING_ICON_WINDOW_NAME = 'Party Formations Toggle'
FLOATING_ICON_DEFAULT_POS = (40.0, 40.0)
MAIN_WINDOW_DEFAULT_SIZE = (420, 520)
CANVAS_EDITOR_WINDOW_DEFAULT_SIZE = (820, 680)
GEOMETRY_PRESET_LIBRARY_TYPE = 'py4gw_party_formation_geometry_presets'
GEOMETRY_PRESET_LIBRARY_VERSION = 1
GEOMETRY_PRESET_FILENAME = 'party_formation_geometry_presets.json'
GEOMETRY_PRESET_MAX_NAME_LENGTH = 80
GEOMETRY_PRESET_MAX_LABEL_LENGTH = 80
GEOMETRY_PRESET_MAX_OFFSET_ABS = 100000.0
GEOMETRY_PRESET_PREVIEW_WIDTH = 250.0
GEOMETRY_PRESET_PREVIEW_HEIGHT = 150.0
GEOMETRY_PRESET_PREVIEW_PADDING = 18.0
CANVAS_RANGE_GUIDES = (
    ('Off', 0.0, (0, 0, 0, 0), 1.0),
    ('Adjacent', float(Range.Adjacent.value), (90, 160, 255, 120), 2.0),
    ('Nearby', float(Range.Nearby.value), (95, 210, 165, 115), 2.0),
    ('Nearby 240', CANVAS_RANGE_GUIDE_NEARBY_ANOMALY, (95, 210, 165, 95), 2.0),
    ('In the Area', float(Range.Area.value), (235, 125, 105, 110), 2.0),
    ('Earshot', float(Range.Earshot.value), (190, 120, 245, 95), 2.0),
    ('Earshot 1000', CANVAS_RANGE_GUIDE_EARSHOT_ANOMALY, (190, 120, 245, 75), 2.0),
    ('Spirit', float(Range.Spirit.value), (245, 205, 95, 70), 2.0),
    ('Spirit exact 2512', CANVAS_RANGE_GUIDE_SPIRIT_EXACT, (245, 205, 95, 60), 2.0),
    ('Party', float(Range.Compass.value), (235, 235, 245, 45), 2.0),
    ('Party exact 5020', CANVAS_RANGE_GUIDE_PARTY_EXACT, (235, 235, 245, 40), 2.0),
)
CANVAS_RANGE_GUIDE_LABELS = [guide[0] for guide in CANVAS_RANGE_GUIDES]
UI_COLOR_SECTION = (0.92, 0.78, 0.46, 1.0)
UI_COLOR_MUTED = (0.62, 0.66, 0.70, 1.0)
UI_COLOR_HELPER = (0.76, 0.80, 0.84, 1.0)
UI_COLOR_GOOD = (0.50, 0.82, 0.55, 1.0)
UI_COLOR_INFO = (0.52, 0.72, 0.92, 1.0)
UI_COLOR_WARN = (0.92, 0.74, 0.38, 1.0)
UI_COLOR_BAD = (0.92, 0.48, 0.44, 1.0)
MAJOR_SECTION_INDENT = 12.0


def _log(message: str, message_type=None) -> None:
    if message_type is None:
        message_type = PySystem.Console.MessageType.Info
    PySystem.Console.Log(MODULE_NAME, message, message_type)


def _message_type_needs_attention(message_type) -> bool:
    if message_type is None:
        return False

    message_type_name = str(getattr(message_type, 'name', '') or message_type).casefold()
    return any(term in message_type_name for term in ('warning', 'error', 'critical', 'exception'))


def _status_text_needs_attention(text: str) -> bool:
    normalized = ' '.join(str(text or '').casefold().split())
    if not normalized:
        return False

    attention_prefixes = (
        'blocked',
        'captured 0',
        'could not',
        'failed',
        'invalid',
        'maximum',
        'missing',
        'no ',
        'not ',
        'only one',
        'save or revert',
        'select at least',
        'skipped',
        'unable',
        'unsaved',
        'unsupported',
        'warning',
    )
    if normalized.startswith(attention_prefixes):
        return True

    ordinary_prefixes = (
        'added ',
        'aligned ',
        'assigned ',
        'cleared ',
        'deleted ',
        'duplicated ',
        'distributed ',
        'hotkey for ',
        'mirrored ',
        'nudged ',
        'removed ',
        'reverted ',
        'saved ',
        'selected ',
    )
    if normalized.startswith(ordinary_prefixes):
        return False

    padded = f' {normalized} '
    attention_phrases = (
        ' assigned target',
        ' cannot ',
        " can't ",
        ' could not ',
        ' discarded',
        ' failed',
        ' invalid',
        ' missing',
        ' no ',
        ' no longer available',
        ' not ',
        ' not explorable',
        ' requires ',
        ' skipped',
        ' stale',
        ' unavailable',
        ' unable ',
        ' unsupported',
        ' warning',
    )
    return any(phrase in padded for phrase in attention_phrases)


def _message_type_label(message_type) -> str:
    if message_type is None:
        return ''
    return str(getattr(message_type, 'name', '') or message_type)


def _record_action_history(
    message: str,
    details: list[str],
    *,
    needs_attention: bool,
    message_type=None,
) -> None:
    if not message and not details:
        return

    action_history.append(
        {
            'time': time.strftime('%H:%M:%S'),
            'message': str(message or ''),
            'details': [str(detail) for detail in details[:10]],
            'needs_attention': bool(needs_attention),
            'message_type': _message_type_label(message_type),
        }
    )
    del action_history[:-ACTION_HISTORY_LIMIT]


def _set_status(message: str, details: list[str] | None = None, log: bool = True, message_type=None) -> None:
    global last_status, status_lines
    global last_status_needs_attention, status_line_attention

    last_status = message
    status_lines = list(details or [])
    message_type_attention = _message_type_needs_attention(message_type)
    last_status_needs_attention = message_type_attention or _status_text_needs_attention(message)
    status_line_attention = [
        message_type_attention or _status_text_needs_attention(detail)
        for detail in status_lines
    ]
    _record_action_history(
        message,
        status_lines,
        needs_attention=last_status_needs_attention or any(status_line_attention),
        message_type=message_type,
    )
    if log:
        _log(message, message_type=message_type)
        for detail in status_lines[:8]:
            _log(detail, message_type=message_type)


def _clear_canvas_drag_state() -> None:
    global canvas_dragging_assignment_index
    global canvas_drag_dirty
    global canvas_drag_owner_id
    global canvas_drag_owner_formation_id
    global canvas_drag_active
    global canvas_drag_start_mouse_pos
    global canvas_drag_cursor_to_spot

    canvas_dragging_assignment_index = -1
    canvas_drag_dirty = False
    canvas_drag_owner_id = ''
    canvas_drag_owner_formation_id = ''
    canvas_drag_active = False
    canvas_drag_start_mouse_pos = (0.0, 0.0)
    canvas_drag_cursor_to_spot = (0.0, 0.0)


def _ensure_window_ini_keys() -> None:
    """Retained as a no-op for lifecycle compatibility.

    Reforged native ImGui owns window position, size, and collapsed state in imgui.ini.
    The legacy account INI files are read only by the explicit migration importer.
    """
    return


def _ensure_floating_ui_key() -> str:
    return ''


def _get_floating_icon_path() -> str:
    return os.path.join(PySystem.Console.get_projects_path(), MODULE_ICON)


def _current_account_email() -> str:
    try:
        from Py4GWCoreLib.Player import Player

        return str(Player.GetAccountEmail() or '').strip()
    except Exception:
        return ''


def _load_legacy_ui_seed() -> None:
    global legacy_ui_seed_loaded
    global legacy_ui_seed_account_email
    global legacy_ui_seed_state

    account_email = _current_account_email()
    if not account_email:
        return
    if legacy_ui_seed_loaded and legacy_ui_seed_account_email == account_email:
        return
    legacy_ui_seed_loaded = True
    legacy_ui_seed_account_email = account_email
    legacy_ui_seed_windows_seen.clear()
    try:
        seed = get_ui_migration_seed(account_email)
    except Exception:
        seed = {}
    legacy_ui_seed_state = dict(seed) if isinstance(seed, dict) else {}


def _native_window_seed(window_name: str) -> dict[str, object]:
    _load_legacy_ui_seed()
    windows = legacy_ui_seed_state.get('windows', {})
    if not isinstance(windows, dict):
        return {}
    seed = windows.get(window_name, {})
    return dict(seed) if isinstance(seed, dict) else {}


def _apply_native_window_seed(window_name: str, default_size: tuple[int, int]) -> bool:
    seed = _native_window_seed(window_name)
    if not seed:
        return False

    seed_x = _seed_float(seed, 'x')
    seed_y = _seed_float(seed, 'y')
    if seed_x is not None and seed_y is not None:
        PyImGui.set_next_window_pos(
            (seed_x, seed_y),
            PyImGui.ImGuiCond.FirstUseEver,
        )

    seed_width = _seed_float(seed, 'width')
    seed_height = _seed_float(seed, 'height')
    has_size = seed_width is not None and seed_height is not None
    if has_size:
        assert seed_width is not None and seed_height is not None
        PyImGui.set_next_window_size(
            (seed_width, seed_height),
            PyImGui.ImGuiCond.FirstUseEver,
        )
    else:
        PyImGui.set_next_window_size(default_size, PyImGui.ImGuiCond.FirstUseEver)

    if 'collapsed' in seed:
        PyImGui.set_next_window_collapsed(
            bool(seed['collapsed']),
            PyImGui.ImGuiCond.FirstUseEver,
        )

    legacy_ui_seed_windows_seen.add(window_name)
    expected_windows = {
        name
        for name in ('main', 'canvas', 'floating')
        if _native_window_seed(name)
    }
    if expected_windows and expected_windows.issubset(legacy_ui_seed_windows_seen):
        account_email = _current_account_email()
        if account_email:
            try:
                mark_ui_migration_seed_consumed(account_email)
            except Exception:
                pass
    return has_size


def _mark_ui_seed_window_seen(window_name: str) -> None:
    if not _native_window_seed(window_name):
        return
    legacy_ui_seed_windows_seen.add(window_name)
    expected_windows = {
        name
        for name in ('main', 'canvas', 'floating')
        if _native_window_seed(name)
    }
    if expected_windows and expected_windows.issubset(legacy_ui_seed_windows_seen):
        account_email = _current_account_email()
        if account_email:
            try:
                mark_ui_migration_seed_consumed(account_email)
            except Exception:
                pass


def _seed_float(seed: dict[str, object], key: str) -> float | None:
    value = seed.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _set_main_window_visible(visible: bool, *, persist: bool = False, expand_on_show: bool = True) -> None:
    global show_main_window
    global expand_main_window_on_next_show

    value = bool(visible)
    show_main_window = value
    if not value:
        _clear_pending_destructive_button()
    if value and expand_on_show:
        expand_main_window_on_next_show = True
    if floating_button is not None:
        floating_button.set_visible(value, persist=persist, invoke_callback=False)


def _on_floating_icon_visibility_toggled(visible: bool) -> None:
    _set_main_window_visible(bool(visible), persist=False, expand_on_show=bool(visible))


def _ensure_floating_ui():
    global floating_button
    global show_main_window

    _ensure_floating_ui_key()
    floating_seed = _native_window_seed('floating')
    floating_start_pos = FLOATING_ICON_DEFAULT_POS
    floating_x = _seed_float(floating_seed, 'x')
    floating_y = _seed_float(floating_seed, 'y')
    if floating_x is not None and floating_y is not None:
        floating_start_pos = (floating_x, floating_y)
    if floating_button is None:
        floating_button = ImGui.FloatingIcon(
            icon_path=_get_floating_icon_path(),
            start_pos=floating_start_pos,
            window_id=FLOATING_ICON_WINDOW_ID,
            window_name=FLOATING_ICON_WINDOW_NAME,
            tooltip_visible='Hide Party Formations window',
            tooltip_hidden='Show Party Formations window',
            visible=bool(show_main_window),
            on_toggle=_on_floating_icon_visibility_toggled,
        )
        show_main_window = bool(floating_button.visible)
    return floating_button


def _begin_persistent_window(ini_key: str, name: str, flags: int) -> bool:
    return PyImGui.begin(name, flags)


def _begin_persistent_window_with_close(
    ini_key: str,
    name: str,
    p_open: bool,
    flags: int,
) -> tuple[bool, bool]:
    return PyImGui.begin_with_close(name, p_open, flags)


def _end_persistent_window(ini_key: str) -> None:
    PyImGui.end()


def _clear_pending_destructive_button() -> None:
    global pending_destructive_button_key
    global pending_destructive_button_expires_at_ms

    pending_destructive_button_key = ''
    pending_destructive_button_expires_at_ms = 0


def _destructive_button_key(label: str, confirmation_key: str = '') -> str:
    safe_confirmation_key = str(confirmation_key or '')
    if safe_confirmation_key:
        return safe_confirmation_key
    safe_label = str(label or '')
    _visible_label, separator, hidden_id = safe_label.partition('##')
    return hidden_id if separator else safe_label


def _destructive_confirm_label(label: str) -> str:
    safe_label = str(label or '')
    _visible_label, separator, hidden_id = safe_label.partition('##')
    return f'Confirm##{hidden_id}' if separator else 'Confirm'


def _push_destructive_confirm_button_style() -> None:
    base = (0.36, 0.27, 0.09, 0.98)
    hover = (0.46, 0.35, 0.12, 1.0)
    active = (0.28, 0.20, 0.07, 1.0)
    text = (0.98, 0.94, 0.82, 1.0)
    PyImGui.push_style_color(PyImGui.ImGuiCol.Button, base)
    PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonHovered, hover)
    PyImGui.push_style_color(PyImGui.ImGuiCol.ButtonActive, active)
    PyImGui.push_style_color(PyImGui.ImGuiCol.Text, text)


def _draw_confirm_destructive_button(
    label: str,
    *,
    confirmation_key: str = '',
    width: float = 0.0,
    height: float = 0.0,
    armed_width: float = 0.0,
) -> bool:
    global pending_destructive_button_key
    global pending_destructive_button_expires_at_ms

    now_ms = int(time.time() * 1000)
    if pending_destructive_button_expires_at_ms <= now_ms:
        _clear_pending_destructive_button()

    key = _destructive_button_key(label, confirmation_key)
    is_armed = bool(key and key == pending_destructive_button_key)
    draw_label = _destructive_confirm_label(label) if is_armed else label
    draw_width = max(float(width), float(armed_width)) if is_armed and armed_width > 0.0 else float(width)

    if is_armed:
        _push_destructive_confirm_button_style()
    if draw_width > 0.0 or height > 0.0:
        clicked = PyImGui.button(draw_label, draw_width, height)
    else:
        clicked = PyImGui.button(draw_label)
    if is_armed:
        PyImGui.pop_style_color(4)

    if not clicked:
        return False
    if is_armed:
        _clear_pending_destructive_button()
        return True

    pending_destructive_button_key = key
    pending_destructive_button_expires_at_ms = now_ms + DESTRUCTIVE_BUTTON_CONFIRM_TIMEOUT_MS
    return False


def _assignment_destructive_signature(assignment) -> str:
    try:
        return json.dumps(assignment.to_dict(), sort_keys=True, separators=(',', ':'))
    except Exception:
        return repr(assignment)


def _assignment_remove_confirmation_key(formation: PartyFormation, assignment, index: int) -> str:
    signature = _assignment_destructive_signature(assignment)
    return f'assignment_remove:{formation.formation_id}:{index}:{signature}'


def _canvas_remove_selected_confirmation_key(formation: PartyFormation) -> str:
    if not formation.assignments:
        return f'canvas_remove_selected:{formation.formation_id}:empty'

    selected_index = max(0, min(canvas_selected_assignment_index, len(formation.assignments) - 1))
    selected_indexes = sorted(
        index
        for index in canvas_selected_assignment_indexes
        if 0 <= index < len(formation.assignments)
    )
    removable_indexes = [
        index
        for index in selected_indexes
        if formation.assignments[index].kind == ASSIGNMENT_UNASSIGNED
    ]
    selected_assignment = formation.assignments[selected_index]
    signature = _assignment_destructive_signature(selected_assignment)
    selected_signature = ','.join(str(index) for index in selected_indexes)
    removable_signature = ','.join(str(index) for index in removable_indexes)
    return (
        f'canvas_remove_selected:{formation.formation_id}:primary={selected_index}:'
        f'selected={selected_signature}:removable={removable_signature}:{signature}'
    )


def _selected_canvas_spot_is_removable(formation: PartyFormation) -> bool:
    if not formation.assignments:
        return False
    selected_index = max(0, min(canvas_selected_assignment_index, len(formation.assignments) - 1))
    return formation.assignments[selected_index].kind == ASSIGNMENT_UNASSIGNED


def _reset_toggle_state() -> None:
    active_formation_ids.clear()
    latched_hotkey_ids.clear()


def _runtime_signature():
    try:
        from Py4GWCoreLib.Map import Map
        from Py4GWCoreLib.Party import Party

        if not Map.IsMapReady() or Map.IsMapLoading():
            return ('not-ready', bool(Map.IsMapLoading()))

        region = Map.GetRegion()
        language = Map.GetLanguage()
        return (
            int(Map.GetMapID() or 0),
            int(region[0] if region else 0),
            int(Map.GetDistrict() or 0),
            int(language[0] if language else 0),
            int(Party.GetPartyID() or 0),
            int(Party.GetPartySize() or 0),
        )
    except Exception:
        return ('unknown',)


def _reset_toggle_state_if_context_changed() -> None:
    global last_runtime_signature

    signature = _runtime_signature()
    if last_runtime_signature is None:
        last_runtime_signature = signature
        return

    if signature != last_runtime_signature:
        _reset_toggle_state()
        last_runtime_signature = signature


def _valid_hotkey_key(key: Key) -> bool:
    return (
        key not in (Key.Unmapped, Key.Unused, Key.Unmappable, Key.VK_0x00)
        and imgui_key_code_for_key(key) is not None
    )


class _MappedHotkeyKey:
    """Duck-typed key passed to the shared manager at the current ImGui boundary."""

    def __init__(self, key: Key, imgui_code: int) -> None:
        self.name = key.name
        self.value = imgui_code


def _is_party_key_pressed(key: Key, repeat: bool = True) -> bool:
    imgui_code = imgui_key_code_for_key(key)
    if imgui_code is None:
        return False
    return bool(PyImGui.is_key_pressed(imgui_code, repeat))


def _party_keybinding(label: str, key: Key, modifiers: ModifierKey):
    changed = False
    popup_done = False

    display_text = ImGui.format_hotkey(key, modifiers)
    display_label = label.split('##')[0]
    popup_id = f'##KeybindPopup_{label}'

    PyImGui.begin_group()
    if display_label:
        PyImGui.columns(2, f'{label}_columns', False)

    if ImGui.button(display_text, -1, 0):
        PyImGui.open_popup(popup_id)

    _, _, size = ImGui.get_item_rect()
    ImGui.show_tooltip('Click to set hotkey')

    if display_label:
        PyImGui.next_column()
        ImGui.text_aligned(display_label, alignment=Alignment.MidLeft, height=size[1])
        PyImGui.end_columns()

    PyImGui.end_group()

    if PyImGui.begin_popup_modal(
        popup_id,
        True,
        PyImGui.WindowFlags.AlwaysAutoResize
        | PyImGui.WindowFlags.NoMove
        | PyImGui.WindowFlags.NoSavedSettings
        | PyImGui.WindowFlags.NoTitleBar,
    ):
        ImGui.text_aligned('Press a key combination', alignment=Alignment.TopCenter, height=30)
        PyImGui.separator()
        PyImGui.spacing()
        ImGui.text_aligned('Esc to cancel', alignment=Alignment.TopCenter, height=30)
        PyImGui.spacing()

        if ImGui.button('Clear', -1, 20):
            key = Key.Unmapped
            modifiers = ModifierKey.NoneKey
            changed = True
            popup_done = True
            PyImGui.close_current_popup()

        io = PyImGui.get_io()
        # Do not turn the click that opened the popup into a MouseLeft binding.
        # Capture begins on the following frame, while still allowing an
        # intentional mouse binding once the modal is already active.
        if not popup_done and not PyImGui.is_window_appearing():
            new_mods = ModifierKey.NoneKey
            if io.key_ctrl:
                new_mods |= ModifierKey.Ctrl
            if io.key_shift:
                new_mods |= ModifierKey.Shift
            if io.key_alt:
                new_mods |= ModifierKey.Alt

            for candidate in Key:
                if candidate in (
                    Key.Ctrl,
                    Key.LCtrl,
                    Key.RCtrl,
                    Key.Shift,
                    Key.LShift,
                    Key.RShift,
                    Key.Alt,
                    Key.LAlt,
                    Key.RAlt,
                    Key.Unmapped,
                    Key.Escape,
                    Key.VK_0x00,
                ):
                    continue
                if _is_party_key_pressed(candidate):
                    key = candidate
                    modifiers = new_mods
                    changed = True
                    popup_done = True
                    PyImGui.close_current_popup()
                    break

        if _is_party_key_pressed(Key.Escape):
            PyImGui.close_current_popup()

        if (
            not popup_done
            and not PyImGui.is_any_item_active()
            and (PyImGui.is_mouse_released(0) or PyImGui.is_mouse_released(1))
            and not PyImGui.is_window_hovered()
            and not PyImGui.is_window_appearing()
        ):
            PyImGui.close_current_popup()

        PyImGui.end_popup()

    return key, modifiers, changed


def _same_hotkey(formation: PartyFormation, key: Key, modifiers: ModifierKey) -> bool:
    return formation.key() == key and int(formation.modifiers()) == int(modifiers)


def _hotkey_identifier(key: Key, modifiers: ModifierKey) -> str:
    return f'{MODULE_NAME}_{key.name}_{int(modifiers)}'


def _unregister_hotkeys() -> None:
    global registered_hotkey_ids

    for identifier in list(registered_hotkey_ids):
        HOTKEY_MANAGER.unregister_hotkey(identifier)
    registered_hotkey_ids.clear()


def _keyboard_capture_active() -> bool:
    try:
        io = PyImGui.get_io()
        if bool(getattr(io, 'want_capture_keyboard', False)):
            return True
    except Exception:
        pass

    try:
        return bool(PyImGui.is_any_item_active())
    except Exception:
        return False


def _find_formation(formation_id: str) -> PartyFormation | None:
    for formation in formations:
        if formation.formation_id == formation_id:
            return formation
    return None


def _operation_status(formation: PartyFormation, action: str, result) -> str:
    success_verb = 'applied' if action == 'apply' else 'cleared'
    if result.applied > 0:
        message = f'{formation.name} {success_verb}'
    elif result.skipped > 0:
        message = f'{formation.name} {action} skipped'
    else:
        message = f'{formation.name}: no assigned flags to {action}'

    if result.skipped > 0:
        noun = 'member' if result.skipped == 1 else 'members'
        message = f'{message}. Skipped {result.skipped} unavailable {noun}'

    return message


def _apply_formation_by_id(formation_id: str, *, respect_keyboard_capture: bool, use_cooldown: bool = True) -> None:
    _reset_toggle_state_if_context_changed()
    formation = _find_formation(formation_id)
    if formation is None:
        _set_status('Formation no longer exists.', log=False)
        return

    if respect_keyboard_capture and _keyboard_capture_active():
        _set_status(f'Skipped {formation.name}: keyboard input is active.', log=False)
        return

    if use_cooldown and not cooldowns.ready(formation.formation_id):
        _set_status(f'Skipped {formation.name}: cooldown active.', log=False)
        return

    if use_cooldown:
        cooldowns.mark(formation.formation_id)
    result = apply_formation(formation)
    details = result.messages[:10]
    if result.applied > 0:
        active_formation_ids.add(formation.formation_id)
        _set_status(
            _operation_status(formation, 'apply', result),
            details=details,
            message_type=PySystem.Console.MessageType.Info,
        )
    else:
        active_formation_ids.discard(formation.formation_id)
        _set_status(
            _operation_status(formation, 'apply', result),
            details=details,
            message_type=PySystem.Console.MessageType.Warning,
        )


def _clear_formation_by_id(formation_id: str, *, respect_keyboard_capture: bool, use_cooldown: bool = True) -> None:
    _reset_toggle_state_if_context_changed()
    formation = _find_formation(formation_id)
    if formation is None:
        _set_status('Formation no longer exists.', log=False)
        return

    if respect_keyboard_capture and _keyboard_capture_active():
        _set_status(f'Skipped {formation.name}: keyboard input is active.', log=False)
        return

    if use_cooldown and not cooldowns.ready(formation.formation_id):
        _set_status(f'Skipped {formation.name}: cooldown active.', log=False)
        return

    if use_cooldown:
        cooldowns.mark(formation.formation_id)
    result = clear_formation(formation)
    active_formation_ids.discard(formation.formation_id)
    details = result.messages[:10]
    if result.applied > 0:
        _set_status(
            _operation_status(formation, 'clear', result),
            details=details,
            message_type=PySystem.Console.MessageType.Info,
        )
    else:
        _set_status(
            _operation_status(formation, 'clear', result),
            details=details,
            message_type=PySystem.Console.MessageType.Warning,
        )


def _toggle_formation_by_id(formation_id: str) -> None:
    if formation_id in latched_hotkey_ids:
        return

    latched_hotkey_ids.add(formation_id)
    if formation_id in active_formation_ids:
        _clear_formation_by_id(formation_id, respect_keyboard_capture=True)
    else:
        _apply_formation_by_id(formation_id, respect_keyboard_capture=True)


def _toggle_formation_by_hotkey(key: Key, modifiers: ModifierKey) -> None:
    matching_formations = [formation for formation in formations if _same_hotkey(formation, key, modifiers)]
    if not matching_formations:
        return

    formation = matching_formations[0]
    if len(matching_formations) > 1:
        selected = _selected_formation()
        if selected is None or not _same_hotkey(selected, key, modifiers):
            _set_status(
                f'Skipped {ImGui.format_hotkey(key, modifiers)}: selected formation does not use this hotkey.',
                log=False,
            )
            return
        formation = selected

    _toggle_formation_by_id(formation.formation_id)


def _make_hotkey_callback(key: Key, modifiers: ModifierKey):
    def _callback() -> None:
        _toggle_formation_by_hotkey(key, modifiers)

    return _callback


def _register_hotkeys() -> None:
    _unregister_hotkeys()
    registered_bindings: set[tuple[Key, int]] = set()
    for formation in formations:
        key = formation.key()
        if not _valid_hotkey_key(key):
            continue
        modifiers = formation.modifiers()
        binding = (key, int(modifiers))
        if binding in registered_bindings:
            continue
        registered_bindings.add(binding)
        imgui_code = imgui_key_code_for_key(key)
        if imgui_code is None:
            continue
        identifier = _hotkey_identifier(key, modifiers)
        HOTKEY_MANAGER.register_hotkey(
            key=cast(Any, _MappedHotkeyKey(key, imgui_code)),
            identifier=identifier,
            name=f'{MODULE_NAME}: {ImGui.format_hotkey(key, modifiers)}',
            callback=_make_hotkey_callback(key, modifiers),
            modifiers=modifiers,
        )
        registered_hotkey_ids.add(identifier)


def _release_hotkey_latches() -> None:
    for formation in formations:
        if formation.formation_id not in latched_hotkey_ids:
            continue

        key = formation.key()
        if not _valid_hotkey_key(key):
            latched_hotkey_ids.discard(formation.formation_id)
            continue

        try:
            imgui_code = imgui_key_code_for_key(key)
            if imgui_code is None or not PyImGui.is_key_down(imgui_code):
                latched_hotkey_ids.discard(formation.formation_id)
        except Exception:
            latched_hotkey_ids.discard(formation.formation_id)


def _save():
    _reset_toggle_state()
    try:
        backup_result = save_formations(formations)
    except Exception as exc:
        _set_status(
            f'Save failed: {exc}',
            log=True,
            message_type=PySystem.Console.MessageType.Warning,
        )
        raise
    _register_hotkeys()
    return backup_result


def _ensure_loaded() -> None:
    global formations, loaded_once, selected_formation_index

    if loaded_once:
        return
    formations = load_formations()
    selected_formation_index = min(selected_formation_index, max(0, len(formations) - 1))
    loaded_once = True
    _register_hotkeys()
    warning = config_load_warning()
    if warning and list_config_backups():
        _set_status(
            f'Config load warning: {warning}. Backups are available in Diagnostics.',
            log=True,
            message_type=PySystem.Console.MessageType.Warning,
        )


def _refresh_members(force: bool = False) -> list[dict]:
    global members_cache, last_member_refresh, last_member_refresh_failed

    now = PySystem.get_tick_count64()
    if not force and members_cache and now - last_member_refresh < 1000:
        return members_cache
    if not force and last_member_refresh_failed and now - last_member_refresh_failed < 1000:
        return members_cache

    try:
        heroes, accounts = get_available_members()
        members_cache = heroes + accounts
        last_member_refresh = now
        last_member_refresh_failed = 0.0
    except Exception as exc:
        members_cache = []
        last_member_refresh_failed = now
        _set_status(
            f'Could not refresh party members: {exc}',
            log=True,
            message_type=PySystem.Console.MessageType.Warning,
        )
    return members_cache


def _default_offset(assignment_count: int) -> tuple[float, float]:
    radius = 350.0
    angle = -math.pi / 2.0 + (assignment_count % 8) * (math.pi * 2.0 / 8.0)
    return math.cos(angle) * radius, math.sin(angle) * radius


def _selected_formation() -> PartyFormation | None:
    if not formations:
        return None
    index = max(0, min(selected_formation_index, len(formations) - 1))
    return formations[index]


def _formation_filter_query() -> str:
    return ' '.join(str(formation_filter_text or '').split()).casefold()


def _formation_matches_filter(formation: PartyFormation, query: str) -> bool:
    if not query:
        return True

    searchable_parts = [
        str(getattr(formation, 'name', '') or ''),
        _target_mode_label(formation),
    ]
    for index, assignment in enumerate(formation.assignments):
        searchable_parts.append(assignment_spot_label(assignment, index))
        searchable_parts.append(_canvas_target_display_label(formation, assignment))

    searchable_text = ' '.join(part for part in searchable_parts if part).casefold()
    return query in searchable_text


def _filtered_formation_indexes(query: str) -> list[int]:
    return [
        index
        for index, formation in enumerate(formations)
        if _formation_matches_filter(formation, query)
    ]


def _formation_combo_label(index: int) -> str:
    if index < 0 or index >= len(formations):
        return 'Unknown Formation'
    formation = formations[index]
    name = str(formation.name or 'Unnamed Formation')
    return f'{index + 1}. {name}' if _formation_filter_query() else name


def _cancel_formation_name_edit() -> None:
    global formation_name_edit_formation_id
    global formation_name_edit_text

    formation_name_edit_formation_id = ''
    formation_name_edit_text = ''


def _begin_formation_name_edit(formation: PartyFormation) -> None:
    global formation_name_edit_formation_id
    global formation_name_edit_text

    formation_name_edit_formation_id = formation.formation_id
    formation_name_edit_text = str(formation.name or '')


def _apply_formation_name_edit(formation: PartyFormation) -> None:
    new_name = formation_name_edit_text.strip() or formation.name
    if new_name != formation.name:
        formation.name = new_name
        _save()
    _cancel_formation_name_edit()


def _select_formation_index(new_index: int) -> bool:
    global selected_formation_index

    if not formations:
        return False
    new_index = max(0, min(int(new_index), len(formations) - 1))
    if new_index == selected_formation_index:
        return True
    if _block_if_canvas_position_draft_dirty('switching formations'):
        return False

    _finish_canvas_drag_if_needed()
    _cancel_formation_name_edit()
    selected_formation_index = new_index
    _set_canvas_selection_group_to_primary(formations[selected_formation_index])
    return True


def _draw_formation_name_control(formation: PartyFormation) -> None:
    global formation_name_edit_text

    is_editing_name = formation_name_edit_formation_id == formation.formation_id
    if not is_editing_name:
        PyImGui.set_next_item_width(260)
        PyImGui.input_text(
            f'Name##formation_name_readonly_{formation.formation_id}',
            formation.name,
            PyImGui.InputTextFlags.ReadOnly,
        )
        ImGui.show_tooltip('Click Edit Name to rename this formation.')
        PyImGui.same_line(0, 8)
        if PyImGui.small_button(f'Edit Name##edit_name_{formation.formation_id}'):
            _begin_formation_name_edit(formation)
        ImGui.show_tooltip('Rename this formation.')
        return

    PyImGui.set_next_item_width(260)
    formation_name_edit_text = PyImGui.input_text(
        f'Name##formation_name_edit_{formation.formation_id}',
        formation_name_edit_text,
    )
    ImGui.show_tooltip('Type the new formation name.')
    PyImGui.same_line(0, 8)
    if PyImGui.small_button(f'Apply Name##apply_name_{formation.formation_id}'):
        _apply_formation_name_edit(formation)
    ImGui.show_tooltip('Use this name for the formation.')
    PyImGui.same_line(0, 8)
    if PyImGui.small_button(f'Cancel##cancel_name_{formation.formation_id}'):
        _cancel_formation_name_edit()
    ImGui.show_tooltip('Keep the current name.')


def _uses_party_slot_targets(formation: PartyFormation) -> bool:
    return getattr(formation, 'target_mode', TARGET_MODE_IDENTITY) == TARGET_MODE_PARTY_SLOT


def _selected_member_for_formation(formation: PartyFormation) -> tuple[dict | None, str]:
    members = _refresh_members()
    if not members:
        return None, ''

    party_slot_mode = _uses_party_slot_targets(formation)
    labels = [_member_label(member, party_slot_mode=party_slot_mode) for member in members]
    index = max(0, min(selected_member_index, len(members) - 1))
    return members[index], labels[index]


def _assign_selected_member_to_spot(formation: PartyFormation, assignment_index: int) -> None:
    if _block_if_canvas_position_draft_dirty('editing targets', formation):
        return
    if assignment_index < 0 or assignment_index >= len(formation.assignments):
        return

    member, member_label = _selected_member_for_formation(formation)
    if member is None:
        _set_status('No selected member is available to assign.', log=False)
        return

    existing = formation.assignments[assignment_index]
    spot_label = assignment_spot_label(existing, assignment_index)
    replacement = assignment_from_member(member, float(existing.offset_x), float(existing.offset_y))
    replacement.enabled = bool(existing.enabled)
    replacement.spot_label = spot_label
    formation.assignments[assignment_index] = replacement
    _save()
    _set_status(f'Assigned {member_label} to {spot_label}.', log=False)


def _clear_assignment_target(formation: PartyFormation, assignment_index: int) -> None:
    if _block_if_canvas_position_draft_dirty('editing targets', formation):
        return
    if assignment_index < 0 or assignment_index >= len(formation.assignments):
        return

    assignment = formation.assignments[assignment_index]
    spot_label = assignment_spot_label(assignment, assignment_index)
    clear_assignment_target(assignment, spot_label)
    _save()
    _set_status(f'Cleared target for {spot_label}.', log=False)


def _unique_duplicate_name(source_name: str) -> str:
    source_base = str(source_name or 'Formation').strip() or 'Formation'
    base_name = f'{source_base} Copy'
    existing_names = {formation.name for formation in formations}
    if base_name not in existing_names:
        return base_name

    suffix = 2
    while f'{base_name} {suffix}' in existing_names:
        suffix += 1
    return f'{base_name} {suffix}'


def _duplicate_formation(formation: PartyFormation) -> None:
    global selected_formation_index

    if _block_if_canvas_position_draft_dirty('duplicating formations', formation):
        return
    _finish_canvas_drag_if_needed()
    assignments = [FormationAssignment.from_dict(assignment.to_dict()) for assignment in formation.assignments]
    duplicate = PartyFormation(
        name=_unique_duplicate_name(formation.name),
        assignments=assignments,
        target_mode=formation.target_mode,
    )
    formations.append(duplicate)
    _cancel_formation_name_edit()
    selected_formation_index = len(formations) - 1
    _set_canvas_selection_group_to_primary(duplicate)
    _save()
    _set_status(f'Duplicated {formation.name} as {duplicate.name}.', log=False)


def _canvas_color(r: int, g: int, b: int, a: int = 255) -> int:
    return Color(r, g, b, a).to_color()


def _draw_section_header(label: str) -> None:
    PyImGui.separator()
    PyImGui.text_colored(label, UI_COLOR_SECTION)


def _begin_major_section(label: str) -> None:
    PyImGui.spacing()
    PyImGui.separator()
    PyImGui.spacing()
    PyImGui.text_colored(label, UI_COLOR_SECTION)
    PyImGui.indent(MAJOR_SECTION_INDENT)
    PyImGui.spacing()


def _end_major_section() -> None:
    PyImGui.spacing()
    PyImGui.unindent(MAJOR_SECTION_INDENT)


def _draw_inline_count(label: str, value: int, color: tuple[float, float, float, float]) -> None:
    PyImGui.text_colored(f'{label}: {value}', color)


def _draw_helper_text(text: str) -> None:
    PyImGui.text_colored(text, UI_COLOR_HELPER)


def _draw_action_row_label(text: str) -> None:
    try:
        cursor_x, cursor_y = PyImGui.get_cursor_screen_pos()
        text_width, text_height = PyImGui.calc_text_size(text)
        line_height = float(PyImGui.get_text_line_height() or text_height or 0.0)
        frame_height_getter = getattr(PyImGui, 'get_frame_height', None)
        if callable(frame_height_getter):
            frame_height_value = frame_height_getter()
            frame_height = float(frame_height_value) if isinstance(frame_height_value, (int, float)) else 0.0
        else:
            frame_height = max(float(PyImGui.get_text_line_height_with_spacing() or 0.0), line_height + 8.0)
        safe_text_height = max(float(text_height or 0.0), line_height)
        safe_frame_height = max(frame_height, safe_text_height)
        text_y = cursor_y + max((safe_frame_height - safe_text_height) * 0.5, 0.0) + 2.0
        color = Color(
            int(max(0.0, min(1.0, UI_COLOR_HELPER[0])) * 255),
            int(max(0.0, min(1.0, UI_COLOR_HELPER[1])) * 255),
            int(max(0.0, min(1.0, UI_COLOR_HELPER[2])) * 255),
            int(max(0.0, min(1.0, UI_COLOR_HELPER[3])) * 255),
        ).to_color()
        PyImGui.draw_list_add_text(cursor_x, text_y, color, text)
        PyImGui.dummy((int(max(float(text_width), 1.0)), int(max(safe_frame_height, 1.0))))
    except Exception:
        _draw_helper_text(text)


def _preflight_status_color(status: str) -> tuple[float, float, float, float]:
    if status == PREFLIGHT_STATUS_WOULD_TARGET:
        return UI_COLOR_GOOD
    if status == 'Warning':
        return UI_COLOR_WARN
    if status == 'Skipped':
        return UI_COLOR_BAD
    return UI_COLOR_MUTED


def _mapping_status_color(status: str) -> tuple[float, float, float, float]:
    if status in {'Assigned', 'Available'}:
        return UI_COLOR_GOOD if status == 'Assigned' else UI_COLOR_MUTED
    if status == 'Duplicate':
        return UI_COLOR_WARN
    if status in {'Empty', 'Unavailable'}:
        return UI_COLOR_BAD
    return UI_COLOR_MUTED


def _assignment_offset_tuple(assignment) -> tuple[float, float]:
    try:
        offset_x = float(assignment.offset_x)
        offset_y = float(assignment.offset_y)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if not math.isfinite(offset_x):
        offset_x = 0.0
    if not math.isfinite(offset_y):
        offset_y = 0.0
    return offset_x, offset_y


def _live_canvas_offsets(formation: PartyFormation) -> list[tuple[float, float]]:
    return [_assignment_offset_tuple(assignment) for assignment in formation.assignments]


def _canvas_offsets_differ(
    first: tuple[float, float],
    second: tuple[float, float],
    tolerance: float = CANVAS_POSITION_DIRTY_TOLERANCE,
) -> bool:
    return abs(float(first[0]) - float(second[0])) > tolerance or abs(float(first[1]) - float(second[1])) > tolerance


def _canvas_position_draft_dirty_for(formation: PartyFormation | None = None) -> bool:
    if not canvas_position_draft_dirty:
        return False
    if formation is None:
        return True
    return canvas_position_draft_formation_id == formation.formation_id


def _block_if_canvas_position_draft_dirty(action: str, formation: PartyFormation | None = None) -> bool:
    if not _canvas_position_draft_dirty_for(formation):
        return False
    _set_status(f'Save or Revert canvas position edits before {action}.', log=False)
    return True


def _clear_canvas_position_draft() -> None:
    global canvas_position_draft_formation_id
    global canvas_position_draft_offsets
    global canvas_position_draft_dirty

    canvas_position_draft_formation_id = ''
    canvas_position_draft_offsets = []
    canvas_position_draft_dirty = False


def _canvas_position_draft_offsets_for(formation: PartyFormation) -> list[tuple[float, float]] | None:
    if canvas_position_draft_formation_id != formation.formation_id:
        return None
    if len(canvas_position_draft_offsets) != len(formation.assignments):
        return None
    return canvas_position_draft_offsets


def _ensure_canvas_position_draft(formation: PartyFormation) -> list[tuple[float, float]]:
    global canvas_position_draft_formation_id
    global canvas_position_draft_offsets

    draft_offsets = _canvas_position_draft_offsets_for(formation)
    if draft_offsets is not None:
        return draft_offsets

    canvas_position_draft_formation_id = formation.formation_id
    canvas_position_draft_offsets = _live_canvas_offsets(formation)
    return canvas_position_draft_offsets


def _recompute_canvas_position_draft_dirty(formation: PartyFormation | None = None) -> None:
    global canvas_position_draft_offsets
    global canvas_position_draft_dirty

    if formation is None:
        formation = _selected_formation()
    if formation is None or canvas_position_draft_formation_id != formation.formation_id:
        canvas_position_draft_dirty = False
        return

    saved_offsets = _live_canvas_offsets(formation)
    if len(canvas_position_draft_offsets) != len(saved_offsets):
        _clear_canvas_position_draft()
        return

    has_difference = False
    normalized_offsets: list[tuple[float, float]] = []
    for draft_offset, saved_offset in zip(canvas_position_draft_offsets, saved_offsets):
        if _canvas_offsets_differ(draft_offset, saved_offset):
            has_difference = True
            normalized_offsets.append((float(draft_offset[0]), float(draft_offset[1])))
        else:
            normalized_offsets.append(saved_offset)

    if has_difference:
        canvas_position_draft_offsets = normalized_offsets
        canvas_position_draft_dirty = True
    else:
        _clear_canvas_position_draft()


def _save_canvas_position_draft(formation: PartyFormation) -> None:
    if not _canvas_position_draft_dirty_for(formation):
        _set_status('No unsaved canvas position edits.', log=False)
        return

    draft_offsets = _canvas_position_draft_offsets_for(formation)
    if draft_offsets is None:
        _clear_canvas_position_draft()
        _set_status('Canvas position draft was stale and has been discarded.', log=False)
        return

    _finish_canvas_drag_if_needed('editor', formation.formation_id)
    for assignment, (offset_x, offset_y) in zip(formation.assignments, draft_offsets):
        assignment.offset_x = float(offset_x)
        assignment.offset_y = float(offset_y)
    _clear_canvas_position_draft()
    _save()
    _set_status(f'Saved canvas positions for {formation.name}.', log=False)


def _revert_canvas_position_draft(formation: PartyFormation) -> None:
    if not _canvas_position_draft_dirty_for(formation):
        _set_status('No unsaved canvas position edits.', log=False)
        return

    _finish_canvas_drag_if_needed('editor', formation.formation_id)
    _clear_canvas_position_draft()
    _set_status(f'Reverted canvas positions for {formation.name}.', log=False)


def _canvas_nudge_step() -> float:
    if canvas_snap_enabled:
        return float(_selected_canvas_snap_grid_size())
    return CANVAS_NUDGE_DEFAULT_STEP


def _nudge_selected_canvas_spot(
    formation: PartyFormation,
    delta_offset_x: float,
    delta_offset_y: float,
    direction_label: str,
) -> None:
    if not formation.assignments:
        _set_status('No spot selected to nudge.', log=False)
        return

    _finish_canvas_drag_if_needed('editor', formation.formation_id)
    selected_index = _clamp_canvas_selection(formation)
    draft_offsets = _ensure_canvas_position_draft(formation)
    if selected_index < 0 or selected_index >= len(draft_offsets):
        _set_status('No spot selected to nudge.', log=False)
        return

    offset_x, offset_y = draft_offsets[selected_index]
    draft_offsets[selected_index] = (float(offset_x) + delta_offset_x, float(offset_y) + delta_offset_y)
    _recompute_canvas_position_draft_dirty(formation)

    spot_label = assignment_spot_label(formation.assignments[selected_index], selected_index)
    _set_status(f'Nudged selected spot {spot_label} {direction_label}.', log=False)


def _mirror_canvas_draft_offsets(formation: PartyFormation, axis: str) -> None:
    if not formation.assignments:
        _set_status('No spots to mirror.', log=False)
        return

    _finish_canvas_drag_if_needed('editor', formation.formation_id)
    _clamp_canvas_selection(formation)
    draft_offsets = _ensure_canvas_position_draft(formation)
    if axis == 'x':
        # Canvas horizontal position is driven by offset_y.
        for index, (offset_x, offset_y) in enumerate(draft_offsets):
            draft_offsets[index] = (float(offset_x), -float(offset_y))
        label = 'horizontally'
    else:
        # Canvas vertical position is driven by offset_x.
        for index, (offset_x, offset_y) in enumerate(draft_offsets):
            draft_offsets[index] = (-float(offset_x), float(offset_y))
        label = 'vertically'

    _recompute_canvas_position_draft_dirty(formation)
    _set_status(f'Mirrored all {len(draft_offsets)} spots {label}.', log=False)


def _align_canvas_draft_offsets(formation: PartyFormation, direction: str) -> None:
    _finish_canvas_drag_if_needed('editor', formation.formation_id)
    if not formation.assignments:
        _set_status('No spots to align.', log=False)
        return
    if len(formation.assignments) == 1:
        _set_status('Only one spot to align.', log=False)
        return

    selected_index = _clamp_canvas_selection(formation)
    draft_offsets = _ensure_canvas_position_draft(formation)
    if selected_index < 0 or selected_index >= len(draft_offsets):
        _set_status('No spot selected to align.', log=False)
        return

    selected_offset_x, selected_offset_y = draft_offsets[selected_index]
    if direction == 'row':
        for index, (_offset_x, offset_y) in enumerate(draft_offsets):
            draft_offsets[index] = (float(selected_offset_x), float(offset_y))
        label = 'row'
    else:
        for index, (offset_x, _offset_y) in enumerate(draft_offsets):
            draft_offsets[index] = (float(offset_x), float(selected_offset_y))
        label = 'column'

    _recompute_canvas_position_draft_dirty(formation)
    spot_label = assignment_spot_label(formation.assignments[selected_index], selected_index)
    _set_status(f'Aligned all spots to {spot_label}\'s {label}.', log=False)


def _distribute_canvas_selection(formation: PartyFormation, direction: str) -> None:
    _finish_canvas_drag_if_needed('editor', formation.formation_id)
    _clamp_canvas_selection(formation)
    selected_indexes = sorted(canvas_selected_assignment_indexes)
    if len(selected_indexes) < 3:
        _set_status('Select at least 3 spots to distribute.', log=False)
        return

    draft_offsets = _ensure_canvas_position_draft(formation)
    selected_indexes = [index for index in selected_indexes if 0 <= index < len(draft_offsets)]
    if len(selected_indexes) < 3:
        _set_status('Select at least 3 spots to distribute.', log=False)
        return

    if direction == 'horizontal':
        sorted_indexes = sorted(
            selected_indexes,
            key=lambda index: (
                float(draft_offsets[index][1]),
                float(draft_offsets[index][0]),
                index,
            ),
        )
        first_value = float(draft_offsets[sorted_indexes[0]][1])
        last_value = float(draft_offsets[sorted_indexes[-1]][1])
        step = (last_value - first_value) / float(len(sorted_indexes) - 1)
        for order, index in enumerate(sorted_indexes[1:-1], start=1):
            offset_x, _offset_y = draft_offsets[index]
            draft_offsets[index] = (float(offset_x), first_value + (step * order))
        label = 'horizontally'
    else:
        sorted_indexes = sorted(
            selected_indexes,
            key=lambda index: (
                float(draft_offsets[index][0]),
                float(draft_offsets[index][1]),
                index,
            ),
        )
        first_value = float(draft_offsets[sorted_indexes[0]][0])
        last_value = float(draft_offsets[sorted_indexes[-1]][0])
        step = (last_value - first_value) / float(len(sorted_indexes) - 1)
        for order, index in enumerate(sorted_indexes[1:-1], start=1):
            _offset_x, offset_y = draft_offsets[index]
            draft_offsets[index] = (first_value + (step * order), float(offset_y))
        label = 'vertically'

    _recompute_canvas_position_draft_dirty(formation)
    _set_status(f'Distributed {len(sorted_indexes)} selected spots {label}.', log=False)


def _clean_geometry_preset_name(value: object) -> str:
    name = str(value or '').strip()
    if not name:
        return 'Formation Geometry'
    return name[:GEOMETRY_PRESET_MAX_NAME_LENGTH]


def _clean_geometry_preset_label(value: object, index: int) -> str:
    label = str(value or '').strip()
    if not label:
        label = default_spot_label(index)
    return label[:GEOMETRY_PRESET_MAX_LABEL_LENGTH]


def _parse_geometry_preset_offset(value: object, field_name: str, spot_index: int) -> tuple[float | None, str | None]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f'{field_name} for spot {spot_index + 1} must be a finite number.'
    offset = float(value)
    if not math.isfinite(offset) or abs(offset) > GEOMETRY_PRESET_MAX_OFFSET_ABS:
        return None, (
            f'{field_name} for spot {spot_index + 1} must be finite and within '
            f'+/-{GEOMETRY_PRESET_MAX_OFFSET_ABS:.0f}.'
        )
    return offset, None


def _validate_geometry_preset(raw: object, index: int) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, f'Preset {index + 1} must be an object.'

    spots_raw = raw.get('spots')
    if not isinstance(spots_raw, list) or not spots_raw:
        return None, f'Preset {index + 1} must contain at least one spot.'
    if len(spots_raw) > MAX_FORMATION_SPOTS:
        return None, f'Preset {index + 1} has {len(spots_raw)} spots; maximum is {MAX_FORMATION_SPOTS}.'

    spots: list[dict] = []
    for spot_index, spot_raw in enumerate(spots_raw):
        if not isinstance(spot_raw, dict):
            return None, f'Preset {index + 1}, spot {spot_index + 1} must be an object.'

        offset_x, error = _parse_geometry_preset_offset(spot_raw.get('offset_x'), 'offset_x', spot_index)
        if error:
            return None, f'Preset {index + 1}: {error}'
        offset_y, error = _parse_geometry_preset_offset(spot_raw.get('offset_y'), 'offset_y', spot_index)
        if error:
            return None, f'Preset {index + 1}: {error}'
        if offset_x is None or offset_y is None:
            return None, f'Preset {index + 1}: spot {spot_index + 1} has invalid offsets.'

        spots.append(
            {
                'label': _clean_geometry_preset_label(spot_raw.get('label'), spot_index),
                'offset_x': float(offset_x),
                'offset_y': float(offset_y),
            }
        )

    return {'name': _clean_geometry_preset_name(raw.get('name')), 'spots': spots}, None


def _load_geometry_presets() -> tuple[list[dict], list[str]]:
    payload, error = load_geometry_preset_library()
    if error:
        return [], [f'Preset library could not be loaded: {error}']
    if not isinstance(payload, dict):
        return [], ['Preset library must be a JSON object.']

    presets_raw = payload.get('presets')
    if not isinstance(presets_raw, list):
        return [], ['Preset library must contain a presets list.']

    presets: list[dict] = []
    errors: list[str] = []
    for index, preset_raw in enumerate(presets_raw):
        preset, validation_error = _validate_geometry_preset(preset_raw, index)
        if validation_error:
            errors.append(validation_error)
            continue
        if preset is not None:
            presets.append(preset)
    return presets, errors


def _write_geometry_presets(presets: list[dict]) -> tuple[bool, str]:
    payload = {
        'type': GEOMETRY_PRESET_LIBRARY_TYPE,
        'version': GEOMETRY_PRESET_LIBRARY_VERSION,
        'presets': presets,
    }
    return save_geometry_preset_library(payload)


def _geometry_preset_from_formation(formation: PartyFormation, name: str) -> tuple[dict | None, list[str]]:
    spots: list[dict] = []
    details: list[str] = []
    for index, assignment in enumerate(formation.assignments[:MAX_FORMATION_SPOTS]):
        if isinstance(assignment.offset_x, bool) or isinstance(assignment.offset_y, bool):
            details.append(f'{assignment_spot_label(assignment, index)}: invalid offset skipped.')
            continue

        try:
            offset_x = float(assignment.offset_x)
            offset_y = float(assignment.offset_y)
        except (TypeError, ValueError):
            details.append(f'{assignment_spot_label(assignment, index)}: invalid offset skipped.')
            continue

        if (
            not math.isfinite(offset_x)
            or not math.isfinite(offset_y)
            or abs(offset_x) > GEOMETRY_PRESET_MAX_OFFSET_ABS
            or abs(offset_y) > GEOMETRY_PRESET_MAX_OFFSET_ABS
        ):
            details.append(f'{assignment_spot_label(assignment, index)}: invalid offset skipped.')
            continue

        spots.append(
            {
                'label': _clean_geometry_preset_label(assignment_spot_label(assignment, index), index),
                'offset_x': offset_x,
                'offset_y': offset_y,
            }
        )

    if not spots:
        return None, details
    return {'name': _clean_geometry_preset_name(name), 'spots': spots}, details


def _find_geometry_preset_index(presets: list[dict], preset_name: str) -> int:
    preset_name_key = str(preset_name or '').casefold()
    for index, existing in enumerate(presets):
        if str(existing.get('name') or '').casefold() == preset_name_key:
            return index
    return -1


def _geometry_preset_signature(preset: dict) -> str:
    try:
        return json.dumps(preset, sort_keys=True, separators=(',', ':'))
    except (TypeError, ValueError):
        return repr(preset)


def _finish_geometry_preset_save(
    presets: list[dict],
    selected_index: int,
    preset: dict,
    details: list[str],
    errors: list[str],
) -> bool:
    global canvas_preset_name_input
    global canvas_preset_selected_index

    ok, message = _write_geometry_presets(presets)
    if not ok:
        _set_status(message, details=errors, message_type=PySystem.Console.MessageType.Warning)
        return False

    canvas_preset_name_input = str(preset['name'])
    canvas_preset_selected_index = selected_index
    _set_status(f'Saved geometry preset {preset["name"]!r}.', details=details + errors, log=False)
    return True


def _request_geometry_preset_overwrite(preset: dict, details: list[str]) -> None:
    global pending_geometry_preset_overwrite
    global pending_geometry_preset_overwrite_details

    pending_geometry_preset_overwrite = preset
    pending_geometry_preset_overwrite_details = list(details)
    PyImGui.open_popup(GEOMETRY_PRESET_OVERWRITE_POPUP_ID)


def _save_geometry_preset(formation: PartyFormation) -> None:
    if _block_if_canvas_position_draft_dirty('saving geometry presets', formation):
        return

    preset_name = _clean_geometry_preset_name(canvas_preset_name_input or formation.name)
    preset, details = _geometry_preset_from_formation(formation, preset_name)
    if preset is None:
        _set_status('Preset save failed: no valid spot geometry to save.', details=details, log=False)
        return

    presets, errors = _load_geometry_presets()
    replaced_index = _find_geometry_preset_index(presets, str(preset['name']))
    if replaced_index >= 0:
        _request_geometry_preset_overwrite(preset, details)
        return

    if replaced_index < 0:
        presets.append(preset)
        replaced_index = len(presets) - 1

    _finish_geometry_preset_save(presets, replaced_index, preset, details, errors)


def _selected_geometry_preset(presets: list[dict]) -> dict | None:
    if not presets:
        return None
    index = max(0, min(canvas_preset_selected_index, len(presets) - 1))
    return presets[index]


def _load_selected_geometry_preset(formation: PartyFormation, presets: list[dict]) -> None:
    if _block_if_canvas_position_draft_dirty('loading geometry presets', formation):
        return

    preset = _selected_geometry_preset(presets)
    if preset is None:
        _set_status('No geometry preset selected.', log=False)
        return

    spots = preset.get('spots')
    if not isinstance(spots, list) or not spots:
        _set_status('Preset load failed: selected preset has no valid spots.', log=False)
        return

    _finish_canvas_drag_if_needed('editor', formation.formation_id)
    if canvas_position_draft_formation_id == formation.formation_id:
        _clear_canvas_position_draft()

    update_count = min(len(formation.assignments), len(spots))
    for index in range(update_count):
        spot = spots[index]
        formation.assignments[index].offset_x = float(spot['offset_x'])
        formation.assignments[index].offset_y = float(spot['offset_y'])
        formation.assignments[index].spot_label = str(spot.get('label') or default_spot_label(index))

    added_count = 0
    available_slots = max(0, MAX_FORMATION_SPOTS - len(formation.assignments))
    add_count = min(max(0, len(spots) - update_count), available_slots)
    for index in range(update_count, update_count + add_count):
        spot = spots[index]
        formation.assignments.append(
            FormationAssignment(
                kind=ASSIGNMENT_UNASSIGNED,
                offset_x=float(spot['offset_x']),
                offset_y=float(spot['offset_y']),
                spot_label=str(spot.get('label') or default_spot_label(index)),
            )
        )
        added_count += 1

    skipped_count = max(0, len(spots) - update_count - added_count)

    details: list[str] = []
    if added_count:
        details.append(f'Added {added_count} unassigned preset spot{"s" if added_count != 1 else ""}.')
    if skipped_count:
        details.append(f'Skipped {skipped_count} preset spot{"s" if skipped_count != 1 else ""} over the max limit.')
    if len(formation.assignments) > len(spots):
        unchanged_count = len(formation.assignments) - len(spots)
        details.append(
            f'Current formation has {len(formation.assignments)} spots; '
            f'left {unchanged_count} extra spots unchanged.'
        )

    _clamp_canvas_selection(formation)
    _save()
    _set_status(
        f'Applied geometry preset {preset["name"]!r} and saved formation; updated {update_count}, added {added_count}.',
        details,
        log=False,
    )


def _request_geometry_preset_delete(preset: dict, index: int) -> None:
    global pending_geometry_preset_delete_name
    global pending_geometry_preset_delete_index

    pending_geometry_preset_delete_name = str(preset.get('name') or 'Unnamed Preset')
    pending_geometry_preset_delete_index = index
    PyImGui.open_popup(GEOMETRY_PRESET_DELETE_POPUP_ID)


def _geometry_preset_delete_confirmation_key(preset: dict, index: int) -> str:
    preset_name = str(preset.get('name') or 'Unnamed Preset')
    return f'geometry_preset_delete:{index}:{preset_name}:{_geometry_preset_signature(preset)}'


def _cancel_geometry_preset_rename() -> None:
    global canvas_preset_rename_active
    global canvas_preset_rename_text
    global canvas_preset_rename_index
    global canvas_preset_rename_original_name
    global canvas_preset_rename_signature

    canvas_preset_rename_active = False
    canvas_preset_rename_text = ''
    canvas_preset_rename_index = -1
    canvas_preset_rename_original_name = ''
    canvas_preset_rename_signature = ''


def _start_geometry_preset_rename(presets: list[dict]) -> None:
    global canvas_preset_rename_active
    global canvas_preset_rename_text
    global canvas_preset_rename_index
    global canvas_preset_rename_original_name
    global canvas_preset_rename_signature

    if not presets:
        _set_status('No geometry preset selected.', log=False)
        return

    index = max(0, min(canvas_preset_selected_index, len(presets) - 1))
    preset = presets[index]
    preset_name = str(preset.get('name') or 'Unnamed Preset')
    canvas_preset_rename_active = True
    canvas_preset_rename_text = preset_name
    canvas_preset_rename_index = index
    canvas_preset_rename_original_name = preset_name
    canvas_preset_rename_signature = _geometry_preset_signature(preset)


def _find_geometry_preset_rename_target(presets: list[dict]) -> int:
    original_name = canvas_preset_rename_original_name
    original_signature = canvas_preset_rename_signature
    original_index = canvas_preset_rename_index
    if (
        0 <= original_index < len(presets)
        and str(presets[original_index].get('name') or '') == original_name
        and _geometry_preset_signature(presets[original_index]) == original_signature
    ):
        return original_index

    matches = [
        index
        for index, preset in enumerate(presets)
        if str(preset.get('name') or '') == original_name and _geometry_preset_signature(preset) == original_signature
    ]
    return matches[0] if len(matches) == 1 else -1


def _apply_geometry_preset_rename() -> None:
    global canvas_preset_selected_index

    if not canvas_preset_rename_active:
        return

    requested_name = str(canvas_preset_rename_text or '').strip()
    if not requested_name:
        _set_status('Preset rename failed: name cannot be blank.', log=False)
        return

    new_name = requested_name[:GEOMETRY_PRESET_MAX_NAME_LENGTH]
    presets, errors = _load_geometry_presets()
    target_index = _find_geometry_preset_rename_target(presets)
    if target_index < 0:
        _set_status('Preset rename failed: selected preset changed. Choose it again.', details=errors, log=False)
        _cancel_geometry_preset_rename()
        return

    current_name = str(presets[target_index].get('name') or 'Unnamed Preset')
    if new_name == current_name:
        _set_status(f'Preset name unchanged: {current_name!r}.', log=False)
        _cancel_geometry_preset_rename()
        return

    new_name_key = new_name.casefold()
    duplicate_index = next(
        (
            index
            for index, preset in enumerate(presets)
            if index != target_index and str(preset.get('name') or '').casefold() == new_name_key
        ),
        -1,
    )
    if duplicate_index >= 0:
        _set_status(f'Preset rename failed: {new_name!r} already exists.', log=False)
        return

    renamed_preset = dict(presets[target_index])
    renamed_preset['name'] = new_name
    presets[target_index] = renamed_preset
    ok, message = _write_geometry_presets(presets)
    if not ok:
        _set_status(message, details=errors, message_type=PySystem.Console.MessageType.Warning)
        return

    canvas_preset_selected_index = target_index
    _cancel_geometry_preset_rename()
    _set_status(f'Renamed geometry preset {current_name!r} to {new_name!r}.', details=errors, log=False)


def _delete_selected_geometry_preset(formation: PartyFormation, presets: list[dict]) -> None:
    global pending_geometry_preset_delete_name
    global pending_geometry_preset_delete_index

    if _block_if_canvas_position_draft_dirty('deleting geometry presets', formation):
        return
    if not presets:
        _set_status('No geometry preset selected.', log=False)
        return

    index = max(0, min(canvas_preset_selected_index, len(presets) - 1))
    pending_geometry_preset_delete_name = str(presets[index].get('name') or 'Unnamed Preset')
    pending_geometry_preset_delete_index = index
    _confirm_geometry_preset_delete()
    _clear_pending_geometry_preset_delete()


def _clear_pending_geometry_preset_overwrite() -> None:
    global pending_geometry_preset_overwrite
    global pending_geometry_preset_overwrite_details

    pending_geometry_preset_overwrite = None
    pending_geometry_preset_overwrite_details = []


def _clear_pending_geometry_preset_delete() -> None:
    global pending_geometry_preset_delete_name
    global pending_geometry_preset_delete_index

    pending_geometry_preset_delete_name = ''
    pending_geometry_preset_delete_index = -1


def _confirm_geometry_preset_overwrite() -> None:
    preset = pending_geometry_preset_overwrite
    if preset is None:
        return

    presets, errors = _load_geometry_presets()
    replaced_index = _find_geometry_preset_index(presets, str(preset.get('name') or ''))
    details = list(pending_geometry_preset_overwrite_details)
    if replaced_index >= 0:
        presets[replaced_index] = preset
    else:
        presets.append(preset)
        replaced_index = len(presets) - 1
        details.append('Original preset was no longer present; saved as new.')

    _finish_geometry_preset_save(presets, replaced_index, preset, details, errors)


def _confirm_geometry_preset_delete() -> None:
    global canvas_preset_selected_index

    presets, errors = _load_geometry_presets()
    preset_name = pending_geometry_preset_delete_name
    delete_index = pending_geometry_preset_delete_index
    if (
        delete_index < 0
        or delete_index >= len(presets)
        or str(presets[delete_index].get('name') or '') != preset_name
    ):
        delete_index = _find_geometry_preset_index(presets, preset_name)

    if delete_index < 0:
        _set_status(f'Preset {preset_name!r} is no longer available.', details=errors, log=False)
        return

    removed = presets.pop(delete_index)
    ok, message = _write_geometry_presets(presets)
    if not ok:
        _set_status(message, details=errors, message_type=PySystem.Console.MessageType.Warning)
        return

    canvas_preset_selected_index = max(0, min(delete_index, len(presets) - 1))
    _set_status(f'Deleted geometry preset {removed["name"]!r}.', log=False)


def _draw_geometry_preset_confirm_popups() -> None:
    if PyImGui.begin_popup_modal(
        GEOMETRY_PRESET_OVERWRITE_POPUP_ID,
        True,
        PyImGui.WindowFlags.AlwaysAutoResize | PyImGui.WindowFlags.NoSavedSettings,
    ):
        preset = pending_geometry_preset_overwrite
        if preset is None:
            PyImGui.close_current_popup()
        else:
            preset_name = str(preset.get('name') or 'Unnamed Preset')
            PyImGui.text_wrapped(f'Overwrite geometry preset {preset_name!r}?')
            PyImGui.spacing()
            if PyImGui.button('Cancel', 96, 0):
                _clear_pending_geometry_preset_overwrite()
                PyImGui.close_current_popup()
            PyImGui.same_line(0, 8)
            if PyImGui.button('Overwrite', 112, 0):
                _confirm_geometry_preset_overwrite()
                _clear_pending_geometry_preset_overwrite()
                PyImGui.close_current_popup()
        PyImGui.end_popup()

    if PyImGui.begin_popup_modal(
        GEOMETRY_PRESET_DELETE_POPUP_ID,
        True,
        PyImGui.WindowFlags.AlwaysAutoResize | PyImGui.WindowFlags.NoSavedSettings,
    ):
        if not pending_geometry_preset_delete_name:
            PyImGui.close_current_popup()
        else:
            PyImGui.text_wrapped(f'Delete geometry preset {pending_geometry_preset_delete_name!r}?')
            PyImGui.spacing()
            if PyImGui.button('Cancel', 96, 0):
                _clear_pending_geometry_preset_delete()
                PyImGui.close_current_popup()
            PyImGui.same_line(0, 8)
            if PyImGui.button('Delete', 96, 0):
                _confirm_geometry_preset_delete()
                _clear_pending_geometry_preset_delete()
                PyImGui.close_current_popup()
        PyImGui.end_popup()


def _clamp_canvas_selection(formation: PartyFormation) -> int:
    global canvas_selected_assignment_index
    global canvas_selected_assignment_indexes

    if not formation.assignments:
        canvas_selected_assignment_index = 0
        canvas_selected_assignment_indexes.clear()
        _clear_canvas_drag_state()
        return 0

    canvas_selected_assignment_index = max(
        0,
        min(canvas_selected_assignment_index, len(formation.assignments) - 1),
    )
    canvas_selected_assignment_indexes = {
        index for index in canvas_selected_assignment_indexes if 0 <= index < len(formation.assignments)
    }
    if canvas_dragging_assignment_index >= len(formation.assignments):
        _clear_canvas_drag_state()
    return canvas_selected_assignment_index


def _set_canvas_selection_group_to_primary(formation: PartyFormation) -> None:
    global canvas_selected_assignment_indexes

    if not formation.assignments:
        canvas_selected_assignment_indexes.clear()
        return

    selected_index = _clamp_canvas_selection(formation)
    canvas_selected_assignment_indexes = {selected_index}


def _select_all_canvas_spots(formation: PartyFormation) -> None:
    global canvas_selected_assignment_indexes

    if not formation.assignments:
        canvas_selected_assignment_indexes.clear()
        _set_status('No spots to select.', log=False)
        return

    _clamp_canvas_selection(formation)
    canvas_selected_assignment_indexes = set(range(len(formation.assignments)))
    _set_status(f'Selected {len(canvas_selected_assignment_indexes)} spots.', log=False)


def _clear_canvas_selection_group() -> None:
    canvas_selected_assignment_indexes.clear()
    _set_status('Cleared selection group.', log=False)


def _toggle_canvas_selection_group_spot(formation: PartyFormation, spot_index: int) -> None:
    global canvas_selected_assignment_index

    if spot_index < 0 or spot_index >= len(formation.assignments):
        return

    _clamp_canvas_selection(formation)
    if spot_index in canvas_selected_assignment_indexes:
        canvas_selected_assignment_indexes.discard(spot_index)
        if spot_index == canvas_selected_assignment_index and canvas_selected_assignment_indexes:
            canvas_selected_assignment_index = min(canvas_selected_assignment_indexes)
    else:
        canvas_selected_assignment_indexes.add(spot_index)
        canvas_selected_assignment_index = spot_index


def _canvas_selection_group_count(formation: PartyFormation) -> int:
    _clamp_canvas_selection(formation)
    return len(canvas_selected_assignment_indexes)


def _assignment_to_canvas(
    center_x: float,
    center_y: float,
    assignment,
    scale: float = CANVAS_SCALE,
) -> tuple[float, float]:
    offset_x, offset_y = _assignment_offset_tuple(assignment)
    return _offset_to_canvas(center_x, center_y, offset_x, offset_y, scale)


def _canvas_assignment_position(
    formation: PartyFormation,
    index: int,
    center_x: float,
    center_y: float,
    draft_offsets: list[tuple[float, float]] | None = None,
) -> tuple[float, float]:
    if draft_offsets is not None and index < len(draft_offsets):
        return _offset_to_canvas(center_x, center_y, draft_offsets[index][0], draft_offsets[index][1])
    return _assignment_to_canvas(center_x, center_y, formation.assignments[index])


def _offset_to_canvas(
    center_x: float,
    center_y: float,
    offset_x: float,
    offset_y: float,
    scale: float = CANVAS_SCALE,
) -> tuple[float, float]:
    return (
        center_x - (offset_y * scale),
        center_y - (offset_x * scale),
    )


def _canvas_to_assignment_offset(
    center_x: float,
    center_y: float,
    mouse_x: float,
    mouse_y: float,
    scale: float = CANVAS_SCALE,
) -> tuple[float, float]:
    safe_scale = max(scale, 0.01)
    return (
        -(mouse_y - center_y) / safe_scale,
        -(mouse_x - center_x) / safe_scale,
    )


def _selected_canvas_snap_grid_size() -> float:
    index = max(0, min(canvas_snap_grid_index, len(CANVAS_SNAP_GRID_SIZES) - 1))
    return CANVAS_SNAP_GRID_SIZES[index]


def _snap_canvas_offset(offset_x: float, offset_y: float) -> tuple[float, float]:
    grid_size = max(_selected_canvas_snap_grid_size(), 1.0)
    return (
        round(offset_x / grid_size) * grid_size,
        round(offset_y / grid_size) * grid_size,
    )


def _find_canvas_assignment(
    formation: PartyFormation,
    center_x: float,
    center_y: float,
    mouse_x: float,
    mouse_y: float,
    draft_offsets: list[tuple[float, float]] | None = None,
) -> int:
    best_index = -1
    best_distance_squared = (CANVAS_SPOT_RADIUS + 6.0) * (CANVAS_SPOT_RADIUS + 6.0)
    for index, assignment in enumerate(formation.assignments):
        point_x, point_y = _canvas_assignment_position(formation, index, center_x, center_y, draft_offsets)
        delta_x = mouse_x - point_x
        delta_y = mouse_y - point_y
        distance_squared = (delta_x * delta_x) + (delta_y * delta_y)
        if distance_squared <= best_distance_squared:
            best_index = index
            best_distance_squared = distance_squared
    return best_index


def _add_unassigned_spot(formation: PartyFormation) -> None:
    global canvas_selected_assignment_index

    if _block_if_canvas_position_draft_dirty('adding spots', formation):
        return
    if len(formation.assignments) >= MAX_FORMATION_SPOTS:
        _set_status(f'Maximum {MAX_FORMATION_SPOTS} assignable spots reached.', log=False)
        return

    offset_x, offset_y = _default_offset(len(formation.assignments))
    assignment = FormationAssignment(
        kind=ASSIGNMENT_UNASSIGNED,
        offset_x=offset_x,
        offset_y=offset_y,
        spot_label=default_spot_label(len(formation.assignments)),
    )
    formation.assignments.append(assignment)
    canvas_selected_assignment_index = len(formation.assignments) - 1
    _set_canvas_selection_group_to_primary(formation)
    _save()
    _set_status(f'Added {assignment_spot_label(assignment, canvas_selected_assignment_index)}.', log=False)


def _remove_selected_unassigned_spot(formation: PartyFormation) -> None:
    global canvas_selected_assignment_index

    if _block_if_canvas_position_draft_dirty('removing spots', formation):
        return
    if not formation.assignments:
        _set_status('No spot selected.', log=False)
        return

    selected_index = _clamp_canvas_selection(formation)
    assignment = formation.assignments[selected_index]
    spot_label = assignment_spot_label(assignment, selected_index)
    if assignment.kind != ASSIGNMENT_UNASSIGNED:
        _set_status(f'{spot_label} has an assigned target. Remove assigned spots from the table.', log=False)
        return

    formation.assignments.pop(selected_index)
    canvas_selected_assignment_index = max(0, min(selected_index, len(formation.assignments) - 1))
    _set_canvas_selection_group_to_primary(formation)
    _save()
    _set_status(f'Removed {spot_label}.', log=False)


def _finish_canvas_drag_if_needed(canvas_owner_id: str | None = None, formation_id: str | None = None) -> None:
    if canvas_owner_id is not None and canvas_drag_owner_id and canvas_drag_owner_id != canvas_owner_id:
        return
    if formation_id is not None and canvas_drag_owner_formation_id and canvas_drag_owner_formation_id != formation_id:
        return

    _clear_canvas_drag_state()


def _draw_canvas_grid(left: float, top: float, right: float, bottom: float, center_x: float, center_y: float) -> None:
    axis_color = _canvas_color(135, 145, 155, 85)
    PyImGui.draw_list_add_line(left, center_y, right, center_y, axis_color, 1.0)
    PyImGui.draw_list_add_line(center_x, top, center_x, bottom, axis_color, 1.0)


def _draw_canvas_snap_grid(
    left: float,
    top: float,
    right: float,
    bottom: float,
    center_x: float,
    center_y: float,
) -> None:
    grid_px = max(float(_selected_canvas_snap_grid_size()) * CANVAS_SCALE, 1.0)
    minor_color = _canvas_color(135, 145, 155, 26)
    major_color = _canvas_color(135, 145, 155, 42)

    line_index = 1
    x = center_x + grid_px
    while x <= right:
        color = major_color if line_index % 4 == 0 else minor_color
        PyImGui.draw_list_add_line(x, top, x, bottom, color, 1.0)
        x += grid_px
        line_index += 1

    line_index = 1
    x = center_x - grid_px
    while x >= left:
        color = major_color if line_index % 4 == 0 else minor_color
        PyImGui.draw_list_add_line(x, top, x, bottom, color, 1.0)
        x -= grid_px
        line_index += 1

    line_index = 1
    y = center_y + grid_px
    while y <= bottom:
        color = major_color if line_index % 4 == 0 else minor_color
        PyImGui.draw_list_add_line(left, y, right, y, color, 1.0)
        y += grid_px
        line_index += 1

    line_index = 1
    y = center_y - grid_px
    while y >= top:
        color = major_color if line_index % 4 == 0 else minor_color
        PyImGui.draw_list_add_line(left, y, right, y, color, 1.0)
        y -= grid_px
        line_index += 1


def _selected_canvas_range_guide() -> tuple[str, float, tuple[int, int, int, int], float]:
    index = max(0, min(canvas_range_guide_index, len(CANVAS_RANGE_GUIDES) - 1))
    return CANVAS_RANGE_GUIDES[index]


def _draw_canvas_range_guides(
    formation: PartyFormation,
    center_x: float,
    center_y: float,
    draft_offsets: list[tuple[float, float]] | None,
) -> None:
    _, radius, color_rgba, thickness = _selected_canvas_range_guide()
    if radius <= 0.0 or not formation.assignments:
        return

    if canvas_range_guide_all_spots:
        indexes = range(len(formation.assignments))
    else:
        indexes = [canvas_selected_assignment_index]

    radius_px = float(radius) * CANVAS_SCALE
    segments = 96 if radius_px >= 300.0 else 64
    color = _canvas_color(*color_rgba)
    for index in indexes:
        if index < 0 or index >= len(formation.assignments):
            continue
        if draft_offsets is not None and index < len(draft_offsets):
            point_x, point_y = _offset_to_canvas(center_x, center_y, draft_offsets[index][0], draft_offsets[index][1])
        else:
            point_x, point_y = _assignment_to_canvas(center_x, center_y, formation.assignments[index])
        PyImGui.draw_list_add_circle(point_x, point_y, radius_px, color, segments, thickness)


def _target_mode_label(formation: PartyFormation) -> str:
    return 'Party Slot' if _uses_party_slot_targets(formation) else 'Identity'


def _canvas_target_display_label(formation: PartyFormation, assignment) -> str:
    if assignment.kind == ASSIGNMENT_UNASSIGNED:
        return 'Unassigned'
    if _uses_party_slot_targets(formation):
        return _assignment_display_label(formation, assignment)
    if assignment.kind == ASSIGNMENT_ACCOUNT:
        return assignment.character_name or assignment.account_name or 'Account'
    if assignment.kind == ASSIGNMENT_HERO:
        return assignment.hero_name or assignment.label or 'Hero'
    return 'Unknown'


def _draw_canvas_spot_tooltip(
    formation: PartyFormation,
    assignment,
    index: int,
    point_x: float,
    point_y: float,
    draft_offset: tuple[float, float] | None = None,
) -> None:
    io = PyImGui.get_io()
    delta_x = float(io.mouse_pos_x) - point_x
    delta_y = float(io.mouse_pos_y) - point_y
    hover_radius = CANVAS_SPOT_RADIUS + 4.0
    if (delta_x * delta_x) + (delta_y * delta_y) > hover_radius * hover_radius:
        return

    if not PyImGui.begin_tooltip():
        return

    PyImGui.text(f'Spot {index + 1}')
    PyImGui.separator()
    PyImGui.text(f'Label: {assignment_spot_label(assignment, index)}')
    PyImGui.text(f'Target: {_canvas_target_display_label(formation, assignment)}')
    PyImGui.text(f'Type: {_assignment_kind_label(formation, assignment)}')
    PyImGui.text(f'Target mode: {_target_mode_label(formation)}')
    PyImGui.text(f'Enabled: {"Yes" if bool(getattr(assignment, "enabled", True)) else "No"}')
    offset_x, offset_y = draft_offset if draft_offset is not None else _assignment_offset_tuple(assignment)
    PyImGui.text(f'Offset: X {float(offset_x):.3f}, Y {float(offset_y):.3f}')
    PyImGui.text(f'Draft: {"Dirty" if _canvas_position_draft_dirty_for(formation) else "Clean"}')
    PyImGui.text(f'Status: {_canvas_spot_status(formation, assignment)}')
    PyImGui.end_tooltip()


def _draw_formation_canvas_spot(
    formation: PartyFormation,
    assignment,
    index: int,
    center_x: float,
    center_y: float,
    draft_offset: tuple[float, float] | None = None,
) -> None:
    if draft_offset is not None:
        point_x, point_y = _offset_to_canvas(center_x, center_y, draft_offset[0], draft_offset[1])
    else:
        point_x, point_y = _assignment_to_canvas(center_x, center_y, assignment)
    selected = index == canvas_selected_assignment_index
    group_selected = index in canvas_selected_assignment_indexes
    assigned = assignment.kind != ASSIGNMENT_UNASSIGNED
    enabled = bool(getattr(assignment, 'enabled', True))

    if assigned:
        fill_color = _canvas_color(75, 135, 205, 145 if enabled else 70)
        border_color = _canvas_color(125, 185, 245, 235 if enabled else 130)
    else:
        fill_color = _canvas_color(120, 130, 140, 120 if enabled else 60)
        border_color = _canvas_color(185, 190, 195, 220 if enabled else 120)

    if selected:
        border_color = _canvas_color(245, 190, 70, 255)

    if group_selected and not selected:
        PyImGui.draw_list_add_circle(
            point_x,
            point_y,
            CANVAS_SPOT_RADIUS + 4.0,
            _canvas_color(245, 190, 70, 170),
            28,
            2.0,
        )

    PyImGui.draw_list_add_circle_filled(point_x, point_y, CANVAS_SPOT_RADIUS, fill_color, 28)
    PyImGui.draw_list_add_circle(
        point_x,
        point_y,
        CANVAS_SPOT_RADIUS,
        border_color,
        28,
        3.0 if selected else 2.0,
    )
    text = str(index + 1)
    text_x = point_x - (7.0 if len(text) > 1 else 4.0)
    PyImGui.draw_list_add_text(text_x, point_y - 6.0, _canvas_color(255, 255, 255, 245), text)
    _draw_canvas_spot_tooltip(formation, assignment, index, point_x, point_y, draft_offset)


def _draw_canvas_spot_action_controls(formation: PartyFormation) -> None:
    if PyImGui.button('Add Unassigned Spot'):
        _add_unassigned_spot(formation)
    ImGui.show_tooltip('Add a blank spot with no target assigned yet.')

    PyImGui.same_line(0, 8)
    remove_selected_label = f'Remove Selected Spot##canvas_remove_selected_{formation.formation_id}'
    can_remove_selected = (
        _selected_canvas_spot_is_removable(formation)
        and not _canvas_position_draft_dirty_for(formation)
    )
    if can_remove_selected:
        remove_clicked = _draw_confirm_destructive_button(
            remove_selected_label,
            confirmation_key=_canvas_remove_selected_confirmation_key(formation),
            armed_width=112.0,
        )
    else:
        remove_clicked = PyImGui.button(remove_selected_label)
    ImGui.show_tooltip('Requires confirmation. Only unassigned spots can be removed here.')
    if remove_clicked:
        _remove_selected_unassigned_spot(formation)


def _draw_formation_canvas(
    formation: PartyFormation,
    *,
    child_id: str = 'PartyFormationCanvasChild',
    canvas_height: float = CANVAS_HEIGHT,
    max_canvas_width: float = CANVAS_MAX_WIDTH,
    canvas_owner_id: str = 'inline',
    use_position_draft: bool = False,
    draw_range_guides: bool = False,
    fill_available_size: bool = False,
    show_selected_label: bool = True,
    show_spot_actions: bool = True,
) -> None:
    global canvas_selected_assignment_index
    global canvas_dragging_assignment_index
    global canvas_drag_dirty
    global canvas_drag_owner_id
    global canvas_drag_owner_formation_id
    global canvas_drag_active
    global canvas_drag_start_mouse_pos
    global canvas_drag_cursor_to_spot
    global canvas_editor_last_canvas_size

    _clamp_canvas_selection(formation)
    draft_offsets = _canvas_position_draft_offsets_for(formation) if use_position_draft else None

    if show_spot_actions:
        _draw_canvas_spot_action_controls(formation)

    if show_selected_label:
        selected_label = 'None'
        if formation.assignments:
            selected_assignment = formation.assignments[canvas_selected_assignment_index]
            selected_label = assignment_spot_label(selected_assignment, canvas_selected_assignment_index)
        _draw_helper_text(f'Selected spot: {selected_label}')

    available_width, available_height = PyImGui.get_content_region_avail()
    available_width = float(available_width or max_canvas_width)
    available_height = float(available_height or canvas_height)
    if fill_available_size:
        canvas_width = max(CANVAS_MIN_WIDTH, available_width)
        canvas_height = max(CANVAS_MIN_HEIGHT, available_height)
    else:
        canvas_width = max(CANVAS_MIN_WIDTH, min(available_width, max_canvas_width))
        canvas_height = max(CANVAS_MIN_HEIGHT, canvas_height)

    if canvas_owner_id == 'editor':
        last_width, last_height = canvas_editor_last_canvas_size
        if abs(last_width - canvas_width) > 0.5 or abs(last_height - canvas_height) > 0.5:
            if canvas_drag_owner_id == 'editor' and canvas_dragging_assignment_index >= 0:
                _finish_canvas_drag_if_needed('editor')
            canvas_editor_last_canvas_size = (canvas_width, canvas_height)

    child_flags = PyImGui.WindowFlags.NoTitleBar | PyImGui.WindowFlags.NoResize | PyImGui.WindowFlags.NoMove
    if not PyImGui.begin_child(child_id, (canvas_width, canvas_height), True, child_flags):
        return

    canvas_pos = PyImGui.get_cursor_screen_pos()
    left = float(canvas_pos[0])
    top = float(canvas_pos[1])
    right = left + canvas_width
    bottom = top + canvas_height
    center_x = left + (canvas_width / 2.0)
    center_y = top + (canvas_height / 2.0)

    if canvas_owner_id == 'editor' and canvas_snap_enabled:
        _draw_canvas_snap_grid(left, top, right, bottom, center_x, center_y)
    _draw_canvas_grid(left, top, right, bottom, center_x, center_y)
    if draw_range_guides:
        _draw_canvas_range_guides(formation, center_x, center_y, draft_offsets)

    PyImGui.draw_list_add_circle_filled(
        center_x,
        center_y,
        CANVAS_ANCHOR_RADIUS,
        _canvas_color(70, 185, 120, 130),
        28,
    )
    PyImGui.draw_list_add_circle(
        center_x,
        center_y,
        CANVAS_ANCHOR_RADIUS,
        _canvas_color(105, 235, 155, 240),
        28,
        2.0,
    )
    PyImGui.draw_list_add_text(center_x - 4.0, center_y - 7.0, _canvas_color(255, 255, 255, 245), 'L')

    for index, assignment in enumerate(formation.assignments):
        draft_offset = draft_offsets[index] if draft_offsets is not None and index < len(draft_offsets) else None
        _draw_formation_canvas_spot(formation, assignment, index, center_x, center_y, draft_offset)

    io = PyImGui.get_io()
    mouse_x = float(io.mouse_pos_x)
    mouse_y = float(io.mouse_pos_y)
    inside = left <= mouse_x <= right and top <= mouse_y <= bottom and PyImGui.is_window_hovered()
    drag_owned_here = (
        canvas_dragging_assignment_index >= 0
        and canvas_drag_owner_id == canvas_owner_id
        and canvas_drag_owner_formation_id == formation.formation_id
    )

    if drag_owned_here:
        if PyImGui.is_mouse_down(0):
            if inside and canvas_dragging_assignment_index < len(formation.assignments):
                if not canvas_drag_active:
                    start_mouse_x, start_mouse_y = canvas_drag_start_mouse_pos
                    drag_delta_x = mouse_x - start_mouse_x
                    drag_delta_y = mouse_y - start_mouse_y
                    drag_distance_squared = (drag_delta_x * drag_delta_x) + (drag_delta_y * drag_delta_y)
                    canvas_drag_active = drag_distance_squared >= CANVAS_DRAG_THRESHOLD * CANVAS_DRAG_THRESHOLD

                if canvas_drag_active:
                    drag_assignment = formation.assignments[canvas_dragging_assignment_index]
                    spot_x = mouse_x + canvas_drag_cursor_to_spot[0]
                    spot_y = mouse_y + canvas_drag_cursor_to_spot[1]
                    offset_x, offset_y = _canvas_to_assignment_offset(center_x, center_y, spot_x, spot_y)
                    if canvas_owner_id == 'editor' and canvas_snap_enabled:
                        offset_x, offset_y = _snap_canvas_offset(offset_x, offset_y)
                    if use_position_draft:
                        draft_offsets = _ensure_canvas_position_draft(formation)
                        assert draft_offsets is not None
                        old_offset_x, old_offset_y = draft_offsets[canvas_dragging_assignment_index]
                    else:
                        old_offset_x, old_offset_y = _assignment_offset_tuple(drag_assignment)
                    if (
                        abs(float(old_offset_x) - offset_x) > 0.001
                        or abs(float(old_offset_y) - offset_y) > 0.001
                    ):
                        if use_position_draft:
                            assert draft_offsets is not None
                            draft_offsets[canvas_dragging_assignment_index] = (offset_x, offset_y)
                            _recompute_canvas_position_draft_dirty(formation)
                        else:
                            drag_assignment.offset_x = offset_x
                            drag_assignment.offset_y = offset_y
                        canvas_drag_dirty = True
        elif PyImGui.is_mouse_released(0):
            if canvas_drag_dirty and _canvas_position_draft_dirty_for(formation):
                _set_status('Unsaved canvas position edits. Use Save Positions or Revert Positions.', log=False)
            _clear_canvas_drag_state()
    elif canvas_dragging_assignment_index < 0 and inside and PyImGui.is_mouse_clicked(0):
        hit_index = _find_canvas_assignment(formation, center_x, center_y, mouse_x, mouse_y, draft_offsets)
        if hit_index >= 0:
            spot_x, spot_y = _canvas_assignment_position(formation, hit_index, center_x, center_y, draft_offsets)
            if bool(getattr(io, 'key_ctrl', False)):
                _toggle_canvas_selection_group_spot(formation, hit_index)
            else:
                canvas_selected_assignment_index = hit_index
                canvas_selected_assignment_indexes.clear()
                canvas_selected_assignment_indexes.add(hit_index)
            canvas_dragging_assignment_index = hit_index
            canvas_drag_dirty = False
            canvas_drag_active = False
            canvas_drag_start_mouse_pos = (mouse_x, mouse_y)
            canvas_drag_cursor_to_spot = (spot_x - mouse_x, spot_y - mouse_y)
            canvas_drag_owner_id = canvas_owner_id
            canvas_drag_owner_formation_id = formation.formation_id

    PyImGui.end_child()


def _open_canvas_editor(formation: PartyFormation) -> None:
    global canvas_editor_open
    global canvas_editor_formation_id

    if canvas_editor_formation_id != formation.formation_id and _block_if_canvas_position_draft_dirty(
        'opening another formation in the Canvas Editor',
    ):
        return
    if canvas_editor_formation_id and canvas_editor_formation_id != formation.formation_id:
        _finish_canvas_drag_if_needed()
    canvas_editor_open = True
    canvas_editor_formation_id = formation.formation_id


def _close_canvas_editor_from_button(formation: PartyFormation | None) -> bool:
    global canvas_editor_open

    if _canvas_position_draft_dirty_for(formation):
        _set_status('Save or Revert canvas position edits before closing the Canvas Editor.', log=False)
        return False
    _finish_canvas_drag_if_needed()
    canvas_editor_open = False
    return True


def _sync_canvas_editor_formation(formation: PartyFormation | None) -> None:
    global canvas_editor_formation_id

    formation_id = formation.formation_id if formation is not None else ''
    if formation_id != canvas_editor_formation_id:
        if _canvas_position_draft_dirty_for():
            _set_status('Save or Revert canvas position edits before switching formations.', log=False)
            return
        _finish_canvas_drag_if_needed()
        canvas_editor_formation_id = formation_id
        if formation is not None:
            _set_canvas_selection_group_to_primary(formation)


def _draw_canvas_position_controls(formation: PartyFormation) -> None:
    if PyImGui.button('Save Positions'):
        _save_canvas_position_draft(formation)
    ImGui.show_tooltip('Keep the spot positions you changed in the editor and write them to this formation.')

    PyImGui.same_line(0, 8)
    if PyImGui.button('Revert Positions'):
        _revert_canvas_position_draft(formation)
    ImGui.show_tooltip('Undo unsaved editor movement and return spots to their saved positions.')

    if _canvas_position_draft_dirty_for(formation):
        PyImGui.text_colored('Unsaved canvas position edits.', UI_COLOR_WARN)
    else:
        _draw_helper_text('Position edits saved.')


def _draw_canvas_range_guide_controls() -> None:
    global canvas_range_guide_index
    global canvas_range_guide_all_spots

    canvas_range_guide_index = PyImGui.combo(
        'Range Guide',
        max(0, min(canvas_range_guide_index, len(CANVAS_RANGE_GUIDE_LABELS) - 1)),
        CANVAS_RANGE_GUIDE_LABELS,
    )
    ImGui.show_tooltip('Show a distance circle on the canvas.')
    canvas_range_guide_index = max(0, min(canvas_range_guide_index, len(CANVAS_RANGE_GUIDE_LABELS) - 1))
    PyImGui.same_line(0, 8)
    canvas_range_guide_all_spots = PyImGui.checkbox('All spots', canvas_range_guide_all_spots)
    ImGui.show_tooltip('Show the guide around every spot instead of only the selected one.')


def _draw_canvas_snap_controls() -> None:
    global canvas_snap_enabled
    global canvas_snap_grid_index

    canvas_snap_enabled = PyImGui.checkbox('Snap', canvas_snap_enabled)
    ImGui.show_tooltip('Make dragged spots jump to grid points.')
    PyImGui.same_line(0, 8)
    PyImGui.set_next_item_width(90)
    canvas_snap_grid_index = PyImGui.combo(
        'Grid',
        max(0, min(canvas_snap_grid_index, len(CANVAS_SNAP_GRID_LABELS) - 1)),
        CANVAS_SNAP_GRID_LABELS,
    )
    ImGui.show_tooltip('Choose how far apart snap points are.')
    canvas_snap_grid_index = max(0, min(canvas_snap_grid_index, len(CANVAS_SNAP_GRID_LABELS) - 1))


def _draw_canvas_selection_controls(formation: PartyFormation) -> None:
    selected_count = _canvas_selection_group_count(formation)
    selected_color = UI_COLOR_INFO if selected_count else UI_COLOR_HELPER
    PyImGui.text_colored(f'Selected: {selected_count}', selected_color)

    PyImGui.same_line(0, 8)
    if PyImGui.button('Select All##canvas_select_all'):
        _select_all_canvas_spots(formation)
    ImGui.show_tooltip('Select every spot in this formation.')

    PyImGui.same_line(0, 4)
    if PyImGui.button('Clear Selection##canvas_clear_selection'):
        _clear_canvas_selection_group()
    ImGui.show_tooltip('Clear the current spot selection.')


def _draw_canvas_transform_controls(formation: PartyFormation) -> None:
    step = _canvas_nudge_step()
    _draw_helper_text(f'Nudge selected spot: {step:.0f}')
    ImGui.show_tooltip('Nudge moves the primary selected spot by this amount.')

    PyImGui.same_line(0, 8)
    if PyImGui.button('Left##canvas_nudge_left'):
        _nudge_selected_canvas_spot(formation, 0.0, step, 'left')
    ImGui.show_tooltip('Move the primary selected spot left.')

    PyImGui.same_line(0, 4)
    if PyImGui.button('Right##canvas_nudge_right'):
        _nudge_selected_canvas_spot(formation, 0.0, -step, 'right')
    ImGui.show_tooltip('Move the primary selected spot right.')

    PyImGui.same_line(0, 4)
    if PyImGui.button('Up##canvas_nudge_up'):
        _nudge_selected_canvas_spot(formation, step, 0.0, 'up')
    ImGui.show_tooltip('Move the primary selected spot up.')

    PyImGui.same_line(0, 4)
    if PyImGui.button('Down##canvas_nudge_down'):
        _nudge_selected_canvas_spot(formation, -step, 0.0, 'down')
    ImGui.show_tooltip('Move the primary selected spot down.')

    PyImGui.same_line(0, 12)
    if PyImGui.button('Mirror Horizontal##canvas_mirror_x'):
        _mirror_canvas_draft_offsets(formation, 'x')
    ImGui.show_tooltip('Flip every spot left/right around the leader on the visible canvas.')

    PyImGui.same_line(0, 4)
    if PyImGui.button('Mirror Vertical##canvas_mirror_y'):
        _mirror_canvas_draft_offsets(formation, 'y')
    ImGui.show_tooltip('Flip every spot up/down around the leader on the visible canvas.')

    PyImGui.same_line(0, 12)
    if PyImGui.button('Align Row##canvas_align_row'):
        _align_canvas_draft_offsets(formation, 'row')
    ImGui.show_tooltip('Put every spot on the primary selected spot\'s horizontal line.')

    PyImGui.same_line(0, 4)
    if PyImGui.button('Align Column##canvas_align_column'):
        _align_canvas_draft_offsets(formation, 'column')
    ImGui.show_tooltip('Put every spot on the primary selected spot\'s vertical line.')

    if PyImGui.button('Distribute Horizontal##canvas_distribute_h'):
        _distribute_canvas_selection(formation, 'horizontal')
    ImGui.show_tooltip('Evenly space the selected spots from left to right. Requires at least 3 selected spots.')

    PyImGui.same_line(0, 4)
    if PyImGui.button('Distribute Vertical##canvas_distribute_v'):
        _distribute_canvas_selection(formation, 'vertical')
    ImGui.show_tooltip('Evenly space the selected spots from top to bottom. Requires at least 3 selected spots.')


def _geometry_preset_preview_points(preset: dict) -> list[tuple[float, float]]:
    spots = preset.get('spots')
    if not isinstance(spots, list):
        return []

    points: list[tuple[float, float]] = []
    for spot in spots:
        if not isinstance(spot, dict):
            continue
        try:
            offset_x = float(spot.get('offset_x', 0.0))
            offset_y = float(spot.get('offset_y', 0.0))
        except (TypeError, ValueError):
            continue
        if math.isfinite(offset_x) and math.isfinite(offset_y):
            points.append((offset_x, offset_y))
    return points


def _geometry_preset_preview_summary(points: list[tuple[float, float]]) -> str:
    if not points:
        return 'Preview: no valid spots'

    min_x = min([0.0] + [point[0] for point in points])
    max_x = max([0.0] + [point[0] for point in points])
    min_y = min([0.0] + [point[1] for point in points])
    max_y = max([0.0] + [point[1] for point in points])
    approx_width = max_y - min_y
    approx_height = max_x - min_x
    spot_label = 'spot' if len(points) == 1 else 'spots'
    return f'Preview: {len(points)} {spot_label}, approx {approx_width:.0f} x {approx_height:.0f}'


def _geometry_preset_preview_scale(presets: list[dict]) -> float:
    all_points: list[tuple[float, float]] = []
    for preset in presets:
        all_points.extend(_geometry_preset_preview_points(preset))
    if not all_points:
        return 0.6

    preview_width = GEOMETRY_PRESET_PREVIEW_WIDTH
    preview_height = GEOMETRY_PRESET_PREVIEW_HEIGHT
    padding = GEOMETRY_PRESET_PREVIEW_PADDING
    half_width = max(1.0, (preview_width - padding * 2.0) / 2.0)
    half_height = max(1.0, (preview_height - padding * 2.0) / 2.0)
    max_abs_x = max([1.0] + [abs(point[0]) for point in all_points])
    max_abs_y = max([1.0] + [abs(point[1]) for point in all_points])
    return min(0.6, half_height / max_abs_x, half_width / max_abs_y)


def _draw_geometry_preset_preview(preset: dict, preview_scale: float) -> None:
    points = _geometry_preset_preview_points(preset)
    _draw_helper_text(_geometry_preset_preview_summary(points))
    if not points:
        return

    preview_width = GEOMETRY_PRESET_PREVIEW_WIDTH
    preview_height = GEOMETRY_PRESET_PREVIEW_HEIGHT
    child_flags = PyImGui.WindowFlags.NoTitleBar | PyImGui.WindowFlags.NoResize | PyImGui.WindowFlags.NoMove
    opened = PyImGui.begin_child(
        'PartyFormationGeometryPresetPreview',
        (preview_width, preview_height),
        True,
        child_flags,
    )
    if opened:
        canvas_pos = PyImGui.get_cursor_screen_pos()
        left = float(canvas_pos[0])
        top = float(canvas_pos[1])
        right = left + preview_width
        bottom = top + preview_height
        center_x = left + (preview_width / 2.0)
        center_y = top + (preview_height / 2.0)
        padding = GEOMETRY_PRESET_PREVIEW_PADDING
        if preview_scale <= 0.0 or not math.isfinite(preview_scale):
            preview_scale = 0.6

        axis_color = _canvas_color(135, 145, 155, 70)
        PyImGui.draw_list_add_line(left + padding, center_y, right - padding, center_y, axis_color, 1.0)
        PyImGui.draw_list_add_line(center_x, top + padding, center_x, bottom - padding, axis_color, 1.0)

        PyImGui.draw_list_add_circle_filled(
            center_x,
            center_y,
            7.0,
            _canvas_color(70, 185, 120, 125),
            24,
        )
        PyImGui.draw_list_add_circle(center_x, center_y, 7.0, _canvas_color(105, 235, 155, 225), 24, 1.5)
        PyImGui.draw_list_add_text(center_x - 3.0, center_y - 6.0, _canvas_color(255, 255, 255, 230), 'L')

        for index, (offset_x, offset_y) in enumerate(points):
            point_x, point_y = _offset_to_canvas(center_x, center_y, offset_x, offset_y, preview_scale)
            PyImGui.draw_list_add_circle_filled(
                point_x,
                point_y,
                7.0,
                _canvas_color(75, 135, 205, 130),
                24,
            )
            PyImGui.draw_list_add_circle(point_x, point_y, 7.0, _canvas_color(125, 185, 245, 220), 24, 1.5)
            label = str(index + 1)
            text_x = point_x - (5.5 if len(label) > 1 else 3.0)
            PyImGui.draw_list_add_text(text_x, point_y - 6.0, _canvas_color(255, 255, 255, 235), label)

    PyImGui.end_child()


def _draw_geometry_preset_controls(formation: PartyFormation) -> None:
    global canvas_preset_name_input
    global canvas_preset_selected_index
    global canvas_preset_rename_text

    presets, errors = _load_geometry_presets()
    previous_selected_index = canvas_preset_selected_index
    if presets:
        canvas_preset_selected_index = max(0, min(canvas_preset_selected_index, len(presets) - 1))
        preset_names = [str(preset.get('name') or 'Unnamed Preset') for preset in presets]
    else:
        canvas_preset_selected_index = 0
        preset_names = ['No presets']
    if canvas_preset_rename_active and (not presets or canvas_preset_selected_index != previous_selected_index):
        _cancel_geometry_preset_rename()

    PyImGui.set_next_item_width(220)
    canvas_preset_name_input = PyImGui.input_text('Preset Name', canvas_preset_name_input)
    ImGui.show_tooltip('Name the saved spot layout.')
    PyImGui.same_line(0, 8)
    if PyImGui.button('Save Preset'):
        _save_geometry_preset(formation)
    ImGui.show_tooltip('Save the current spot layout for reuse.')

    PyImGui.set_next_item_width(220)
    selected_index = PyImGui.combo('Geometry Preset', canvas_preset_selected_index, preset_names)
    ImGui.show_tooltip('Choose a saved spot layout.')
    new_selected_index = max(0, min(selected_index, len(preset_names) - 1))
    if new_selected_index != canvas_preset_selected_index:
        _cancel_geometry_preset_rename()
    canvas_preset_selected_index = new_selected_index

    PyImGui.same_line(0, 8)
    if PyImGui.button('Load Preset'):
        _load_selected_geometry_preset(formation, presets)
    ImGui.show_tooltip('Apply the chosen layout to this formation and save positions/labels immediately.')

    PyImGui.same_line(0, 8)
    if PyImGui.button('Rename Preset'):
        _start_geometry_preset_rename(presets)
    ImGui.show_tooltip('Rename the chosen saved layout without changing its spots.')

    PyImGui.same_line(0, 8)
    delete_preset_clicked = False
    if presets:
        delete_index = max(0, min(canvas_preset_selected_index, len(presets) - 1))
        delete_preset_clicked = _draw_confirm_destructive_button(
            'Delete Preset##geometry_delete_preset',
            confirmation_key=_geometry_preset_delete_confirmation_key(presets[delete_index], delete_index),
            armed_width=96.0,
        )
    else:
        delete_preset_clicked = PyImGui.button('Delete Preset##geometry_delete_preset')
    if delete_preset_clicked:
        _cancel_geometry_preset_rename()
        _delete_selected_geometry_preset(formation, presets)
    ImGui.show_tooltip('Requires confirmation. Removes this saved layout from the preset library.')

    if canvas_preset_rename_active:
        PyImGui.spacing()
        PyImGui.set_next_item_width(220)
        canvas_preset_rename_text = PyImGui.input_text('New Preset Name', canvas_preset_rename_text)
        ImGui.show_tooltip('Set a new name for the selected saved layout.')
        PyImGui.same_line(0, 8)
        if PyImGui.button('Apply Name'):
            _apply_geometry_preset_rename()
        ImGui.show_tooltip('Apply the new preset name only.')
        PyImGui.same_line(0, 8)
        if PyImGui.button('Cancel##geometry_preset_rename'):
            _cancel_geometry_preset_rename()
        ImGui.show_tooltip('Cancel renaming this preset.')

    PyImGui.spacing()
    if presets:
        preview_index = max(0, min(canvas_preset_selected_index, len(presets) - 1))
        _draw_geometry_preset_preview(presets[preview_index], _geometry_preset_preview_scale(presets))
    else:
        _draw_helper_text('Preview: no preset selected')

    if errors:
        suffix = f' (+{len(errors) - 1} more)' if len(errors) > 1 else ''
        PyImGui.text_colored(f'Preset library warning: {errors[0]}{suffix}', UI_COLOR_WARN)

    _draw_geometry_preset_confirm_popups()


def _begin_canvas_tools_subsection(label: str, tooltip: str) -> bool:
    PyImGui.spacing()
    PyImGui.separator()
    opened = PyImGui.collapsing_header(label)
    ImGui.show_tooltip(tooltip)
    if opened:
        PyImGui.indent(12.0)
        PyImGui.spacing()
    return opened


def _end_canvas_tools_subsection() -> None:
    PyImGui.spacing()
    PyImGui.unindent(12.0)


def _draw_canvas_tools_settings(formation: PartyFormation) -> None:
    if not PyImGui.collapsing_header('Canvas Settings##PartyFormationCanvasToolsSection'):
        return

    _draw_helper_text('These settings are shared with the Canvas Editor.')
    PyImGui.set_next_item_width(160)
    _draw_canvas_range_guide_controls()
    PyImGui.same_line(0, 12)
    _draw_canvas_snap_controls()

    if _begin_canvas_tools_subsection(
        'Geometry Presets##PartyFormationMainCanvasPresets',
        'Save or load spot geometry using the current formation.',
    ):
        _draw_geometry_preset_controls(formation)
        _end_canvas_tools_subsection()

    if _begin_canvas_tools_subsection(
        'Transform##PartyFormationMainCanvasTransformSection',
        'Nudge uses the primary selected spot; mirror and align affect every spot; '
        'distribute uses the selection group.',
    ):
        _draw_canvas_transform_controls(formation)
        _end_canvas_tools_subsection()

    if _begin_canvas_tools_subsection(
        'Selected Spot Details##PartyFormationMainCanvasSelectedDetails',
        'Selection follows the current Canvas Editor spot selection.',
    ):
        _draw_canvas_selection_controls(formation)
        _draw_canvas_selected_spot_details(formation)
        _end_canvas_tools_subsection()


def _canvas_spot_status(formation: PartyFormation, assignment) -> str:
    status_parts: list[str] = []
    if not assignment_has_target(assignment):
        status_parts.append('No target')
    else:
        target_key, _target_label = _assignment_target_key(formation, assignment)
        if target_key is not None:
            duplicate_count = 0
            for other in formation.assignments:
                other_key, _other_label = _assignment_target_key(formation, other)
                if other_key == target_key:
                    duplicate_count += 1
            if duplicate_count > 1:
                status_parts.append('Duplicate target')

        lookup = _member_lookup(_refresh_members())
        available, label = _assignment_available_label(formation, assignment, lookup)
        if not available:
            status_parts.append(f'Unavailable: {label}')

    if not bool(getattr(assignment, 'enabled', True)):
        status_parts.append('Off')
    return ', '.join(status_parts) if status_parts else 'OK'


def _draw_canvas_editor_status_details(formation: PartyFormation) -> None:
    draft_dirty = _canvas_position_draft_dirty_for(formation)
    selected_count = _canvas_selection_group_count(formation)
    range_label, _radius, _color_rgba, _thickness = _selected_canvas_range_guide()

    _draw_helper_text(f'Formation: {formation.name}')
    PyImGui.same_line(0, 12)
    if draft_dirty:
        PyImGui.text_colored('Draft: unsaved', UI_COLOR_WARN)
    else:
        _draw_helper_text('Draft: clean')
    PyImGui.same_line(0, 12)
    PyImGui.text_colored(f'Selected spots: {selected_count}', UI_COLOR_INFO if selected_count else UI_COLOR_HELPER)

    PyImGui.text_colored(
        f'Snap: {"on" if canvas_snap_enabled else "off"}',
        UI_COLOR_INFO if canvas_snap_enabled else UI_COLOR_HELPER,
    )
    PyImGui.same_line(0, 12)
    PyImGui.text_colored(f'Range guide: {range_label}', UI_COLOR_INFO if range_label != 'Off' else UI_COLOR_HELPER)
    PyImGui.same_line(0, 12)
    PyImGui.text_colored(
        'Guide scope: all spots' if canvas_range_guide_all_spots else 'Guide scope: selected spot',
        UI_COLOR_HELPER,
    )


def _draw_canvas_editor_detail_row(
    label: str,
    value: str,
    color: tuple[float, float, float, float] = UI_COLOR_HELPER,
) -> None:
    PyImGui.table_next_row()
    PyImGui.table_next_column()
    PyImGui.text_colored(label, UI_COLOR_HELPER)
    PyImGui.table_next_column()
    PyImGui.text_colored(value, color)


def _draw_canvas_selected_spot_details(formation: PartyFormation) -> None:
    if not formation.assignments:
        _draw_helper_text('No selected spot.')
        return

    selected_index = max(0, min(canvas_selected_assignment_index, len(formation.assignments) - 1))
    assignment = formation.assignments[selected_index]
    draft_offsets = _canvas_position_draft_offsets_for(formation)
    if draft_offsets is not None and selected_index < len(draft_offsets):
        using_draft = True
        offset_x, offset_y = draft_offsets[selected_index]
    else:
        using_draft = False
        offset_x, offset_y = _assignment_offset_tuple(assignment)
    enabled = bool(getattr(assignment, 'enabled', True))
    status = _canvas_spot_status(formation, assignment)
    selected_count = _canvas_selection_group_count(formation)

    table_flags = PyImGui.TableFlags.RowBg | PyImGui.TableFlags.SizingFixedFit
    if not PyImGui.begin_table('PartyFormationCanvasSelectedSpotDetails', 2, table_flags, 0, 0):
        return

    PyImGui.table_setup_column('##canvas_detail_label', PyImGui.TableColumnFlags.WidthFixed, 92)
    PyImGui.table_setup_column('##canvas_detail_value', PyImGui.TableColumnFlags.WidthStretch)

    spot_label = assignment_spot_label(assignment, selected_index)
    _draw_canvas_editor_detail_row('Spot', f'{selected_index + 1}/{len(formation.assignments)} - {spot_label}')
    _draw_canvas_editor_detail_row(
        'Target',
        _canvas_target_display_label(formation, assignment),
        UI_COLOR_INFO if assignment_has_target(assignment) else UI_COLOR_HELPER,
    )
    _draw_canvas_editor_detail_row('Type', _assignment_kind_label(formation, assignment))
    _draw_canvas_editor_detail_row('Enabled', 'Yes' if enabled else 'No', UI_COLOR_GOOD if enabled else UI_COLOR_HELPER)
    _draw_canvas_editor_detail_row(
        'Offset',
        f'{"Draft" if using_draft else "Stored"} X {float(offset_x):.3f}, Y {float(offset_y):.3f}',
    )
    _draw_canvas_editor_detail_row(
        'Draft',
        'Unsaved position edits' if _canvas_position_draft_dirty_for(formation) else 'Clean',
        UI_COLOR_WARN if _canvas_position_draft_dirty_for(formation) else UI_COLOR_HELPER,
    )
    _draw_canvas_editor_detail_row('Selection', f'{selected_count} selected')
    _draw_canvas_editor_detail_row('Status', status, UI_COLOR_GOOD if status == 'OK' else UI_COLOR_WARN)

    PyImGui.end_table()


def _draw_canvas_editor_window() -> None:
    global canvas_editor_open

    if not canvas_editor_open:
        return

    _ensure_window_ini_keys()
    formation = _selected_formation()
    _sync_canvas_editor_formation(formation)

    if not _apply_native_window_seed('canvas', CANVAS_EDITOR_WINDOW_DEFAULT_SIZE):
        PyImGui.set_next_window_size((820, 680), PyImGui.ImGuiCond.FirstUseEver)
    expanded, editor_open = _begin_persistent_window_with_close(
        canvas_editor_window_ini_key,
        'Party Formation Canvas Editor',
        canvas_editor_open,
        PyImGui.WindowFlags.NoFlag,
    )
    if not editor_open:
        if _canvas_position_draft_dirty_for(formation):
            _set_status('Save or Revert canvas position edits before closing the Canvas Editor.', log=False)
            canvas_editor_open = True
            _end_persistent_window(canvas_editor_window_ini_key)
            return
        _finish_canvas_drag_if_needed('editor', canvas_editor_formation_id)
        canvas_editor_open = False
        _end_persistent_window(canvas_editor_window_ini_key)
        return

    if expanded:
        if PyImGui.button('Close'):
            _close_canvas_editor_from_button(formation)
            _end_persistent_window(canvas_editor_window_ini_key)
            return

        if formation is None:
            _draw_helper_text('No formation selected.')
        else:
            PyImGui.same_line(0, 8)
            if PyImGui.button('Save Positions'):
                _save_canvas_position_draft(formation)

            PyImGui.same_line(0, 8)
            if PyImGui.button('Revert Positions'):
                _revert_canvas_position_draft(formation)

            PyImGui.same_line(0, 12)
            if _canvas_position_draft_dirty_for(formation):
                PyImGui.text_colored('Draft: unsaved', UI_COLOR_WARN)
            else:
                _draw_helper_text('Draft: clean')

            PyImGui.same_line(0, 12)
            selected_count = _canvas_selection_group_count(formation)
            PyImGui.text_colored(
                f'Selected: {selected_count}',
                UI_COLOR_INFO if selected_count else UI_COLOR_HELPER,
            )

            PyImGui.same_line(0, 12)
            _draw_helper_text(f'Formation: {formation.name}')

            _draw_canvas_spot_action_controls(formation)

            _draw_formation_canvas(
                formation,
                child_id='PartyFormationCanvasEditorChild',
                canvas_height=CANVAS_EDITOR_HEIGHT,
                max_canvas_width=CANVAS_EDITOR_MAX_WIDTH,
                canvas_owner_id='editor',
                use_position_draft=True,
                draw_range_guides=True,
                fill_available_size=True,
                show_selected_label=False,
                show_spot_actions=False,
            )
    else:
        _finish_canvas_drag_if_needed('editor', canvas_editor_formation_id)
    _end_persistent_window(canvas_editor_window_ini_key)


def _export_shape_to_clipboard(formation: PartyFormation) -> None:
    result = export_formation_shape(formation)
    if not result.ok:
        _set_status(
            result.status(),
            details=result.details,
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    try:
        PyImGui.set_clipboard_text(result.payload)
    except Exception as exc:
        _set_status(
            f'Export failed: clipboard error: {exc}',
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    _set_status(result.status(), details=result.details, message_type=PySystem.Console.MessageType.Info)


def _import_shape_from_clipboard() -> None:
    global selected_formation_index
    global canvas_selected_assignment_index

    if _block_if_canvas_position_draft_dirty('importing shapes'):
        return

    try:
        payload = PyImGui.get_clipboard_text() or ''
    except Exception as exc:
        _set_status(
            f'Import failed: clipboard error: {exc}',
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    result = import_formation_shape(payload, formations)
    if not result.ok or result.formation is None:
        _set_status(
            result.message or 'Import failed.',
            details=result.details,
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    _finish_canvas_drag_if_needed()
    formations.append(result.formation)
    _cancel_formation_name_edit()
    selected_formation_index = len(formations) - 1
    canvas_selected_assignment_index = 0
    _set_canvas_selection_group_to_primary(result.formation)
    _save()
    _set_status(result.message, details=result.details, message_type=PySystem.Console.MessageType.Info)


def _clear_pending_target_mode_change() -> None:
    global pending_target_mode
    global pending_target_mode_formation_id
    global pending_target_mode_label

    pending_target_mode_formation_id = ''
    pending_target_mode = ''
    pending_target_mode_label = ''


def _apply_target_mode(formation: PartyFormation, target_mode: str, target_label: str) -> None:
    formation.target_mode = target_mode
    _save()
    _set_status(f'{formation.name} targets by {target_label}.', log=False)


def _request_target_mode_change(formation: PartyFormation, target_mode: str, target_label: str) -> None:
    global pending_target_mode
    global pending_target_mode_formation_id
    global pending_target_mode_label

    if not formation_has_assigned_targets(formation):
        _apply_target_mode(formation, target_mode, target_label)
        return

    pending_target_mode_formation_id = formation.formation_id
    pending_target_mode = target_mode
    pending_target_mode_label = target_label
    PyImGui.open_popup(TARGET_MODE_CONFIRM_POPUP_ID)


def _draw_target_mode_change_popup() -> None:
    if not PyImGui.begin_popup_modal(
        TARGET_MODE_CONFIRM_POPUP_ID,
        True,
        PyImGui.WindowFlags.AlwaysAutoResize | PyImGui.WindowFlags.NoSavedSettings,
    ):
        return

    formation = _find_formation(pending_target_mode_formation_id)
    if formation is None or not pending_target_mode:
        _clear_pending_target_mode_change()
        PyImGui.close_current_popup()
        PyImGui.end_popup()
        return

    PyImGui.text_wrapped('Changing target mode changes how assignments are resolved.')
    PyImGui.text_wrapped(
        'Existing assignments may not behave like a newly created formation in the new mode. '
        'For best results, rebuild assignments from the current party after switching.'
    )
    PyImGui.spacing()

    if PyImGui.button('Cancel', 96, 0):
        _clear_pending_target_mode_change()
        PyImGui.close_current_popup()

    PyImGui.same_line(0, 8)
    if PyImGui.button('Switch Mode', 120, 0):
        _apply_target_mode(formation, pending_target_mode, pending_target_mode_label)
        _clear_pending_target_mode_change()
        PyImGui.close_current_popup()

    PyImGui.end_popup()


def _member_label(member: dict, *, party_slot_mode: bool) -> str:
    label = str(member.get('label') or 'Member')
    if party_slot_mode:
        slot_label = str(member.get('slot_label') or '')
        if not slot_label:
            if member.get('kind') == ASSIGNMENT_HERO:
                slot_label = f"Hero Slot {int(member.get('hero_party_position') or 0)}"
            else:
                slot_label = f"Player Slot {int(member.get('account_party_position') or -1) + 1}"
        return f'{slot_label}: {label}'

    return f"{'Hero' if member.get('kind') == ASSIGNMENT_HERO else 'Account'}: {label}"


def _assignment_slot_label(assignment) -> str:
    if assignment.kind == ASSIGNMENT_UNASSIGNED:
        return 'Unassigned'

    members = _refresh_members()

    if assignment.kind == ASSIGNMENT_HERO:
        slot = int(assignment.hero_party_position or 0)
        current = next(
            (
                str(member.get('label') or '')
                for member in members
                if member.get('kind') == ASSIGNMENT_HERO and int(member.get('hero_party_position') or 0) == slot
            ),
            '',
        )
        if current:
            return f'Hero Slot {slot}: {current}'
        return f'Hero Slot {slot}' if slot > 0 else 'Hero Slot ?'

    party_position = int(assignment.account_party_position)
    if party_position <= 0:
        return 'Leader / Anchor'

    current = next(
        (
            str(member.get('label') or '')
            for member in members
            if member.get('kind') == ASSIGNMENT_ACCOUNT
            and int(member.get('account_party_position') or -1) == party_position
        ),
        '',
    )
    public_slot = party_position + 1
    if current:
        return f'Player Slot {public_slot}: {current}'
    return f'Player Slot {public_slot}'


def _assignment_display_label(formation: PartyFormation, assignment) -> str:
    if assignment.kind == ASSIGNMENT_UNASSIGNED:
        return 'Unassigned'
    if _uses_party_slot_targets(formation):
        return _assignment_slot_label(assignment)
    return assignment.display_name()


def _assignment_kind_label(formation: PartyFormation, assignment) -> str:
    if assignment.kind == ASSIGNMENT_UNASSIGNED:
        return 'No target'
    if not _uses_party_slot_targets(formation):
        return 'Hero' if assignment.kind == ASSIGNMENT_HERO else 'Account'
    return 'Hero slot' if assignment.kind == ASSIGNMENT_HERO else 'Player slot'


def _assignment_kind_color(formation: PartyFormation, assignment) -> tuple[float, float, float, float]:
    if assignment.kind == ASSIGNMENT_UNASSIGNED:
        return UI_COLOR_MUTED
    if assignment.kind == ASSIGNMENT_HERO:
        return UI_COLOR_INFO
    if assignment.kind == ASSIGNMENT_ACCOUNT:
        return UI_COLOR_GOOD
    return UI_COLOR_HELPER


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _member_lookup(members: list[dict]) -> dict[str, set]:
    lookup = {
        'hero_slots': set(),
        'hero_ids': set(),
        'hero_names': set(),
        'account_positions': set(),
        'account_emails': set(),
        'account_names': set(),
        'character_names': set(),
    }
    for member in members:
        kind = member.get('kind')
        if kind == ASSIGNMENT_HERO:
            hero_position = _safe_int(member.get('hero_party_position'), 0)
            hero_id = _safe_int(member.get('hero_id'), 0)
            hero_name = str(member.get('hero_name') or '').strip().casefold()
            if hero_position > 0:
                lookup['hero_slots'].add(hero_position)
            if hero_id > 0:
                lookup['hero_ids'].add(hero_id)
            if hero_name:
                lookup['hero_names'].add(hero_name)
        elif kind == ASSIGNMENT_ACCOUNT:
            party_position = _safe_int(member.get('account_party_position'), -1)
            account_email = str(member.get('account_email') or '').strip().casefold()
            account_name = str(member.get('account_name') or '').strip().casefold()
            character_name = str(member.get('character_name') or '').strip().casefold()
            if party_position > LEADER_PARTY_POSITION:
                lookup['account_positions'].add(party_position)
            if account_email:
                lookup['account_emails'].add(account_email)
            if account_name:
                lookup['account_names'].add(account_name)
            if character_name:
                lookup['character_names'].add(character_name)
    return lookup


def _assignment_target_key(formation: PartyFormation, assignment) -> tuple[tuple[str, object], str] | tuple[None, str]:
    if not assignment_has_target(assignment):
        return None, ''

    if _uses_party_slot_targets(formation):
        if assignment.kind == ASSIGNMENT_HERO:
            hero_position = _safe_int(getattr(assignment, 'hero_party_position', 0), 0)
            if hero_position <= 0:
                return None, ''
            return ('hero_slot', hero_position), f'Hero Slot {hero_position}'
        if assignment.kind == ASSIGNMENT_ACCOUNT:
            party_position = _safe_int(getattr(assignment, 'account_party_position', -1), -1)
            if party_position <= LEADER_PARTY_POSITION:
                return None, ''
            return ('account_slot', party_position), f'Player Slot {party_position + 1}'
        return None, ''

    if assignment.kind == ASSIGNMENT_HERO:
        hero_id = _safe_int(getattr(assignment, 'hero_id', 0), 0)
        hero_name = str(getattr(assignment, 'hero_name', '') or '').strip()
        hero_position = _safe_int(getattr(assignment, 'hero_party_position', 0), 0)
        if hero_id > 0:
            return ('hero_id', hero_id), hero_name or f'Hero {hero_id}'
        if hero_name:
            return ('hero_name', hero_name.casefold()), hero_name
        if hero_position > 0:
            return ('hero_slot', hero_position), f'Hero Slot {hero_position}'
        return None, ''

    if assignment.kind == ASSIGNMENT_ACCOUNT:
        account_email = str(getattr(assignment, 'account_email', '') or '').strip()
        character_name = str(getattr(assignment, 'character_name', '') or '').strip()
        account_name = str(getattr(assignment, 'account_name', '') or '').strip()
        party_position = _safe_int(getattr(assignment, 'account_party_position', -1), -1)
        if account_email:
            return ('account_email', account_email.casefold()), character_name or account_name or account_email
        if character_name:
            return ('character_name', character_name.casefold()), character_name
        if account_name:
            return ('account_name', account_name.casefold()), account_name
        if party_position > LEADER_PARTY_POSITION:
            return ('account_slot', party_position), f'Player Slot {party_position + 1}'
    return None, ''


def _assignment_available_label(formation: PartyFormation, assignment, lookup: dict[str, set]) -> tuple[bool, str]:
    if not assignment_has_target(assignment):
        return True, ''

    if assignment.kind == ASSIGNMENT_HERO:
        hero_position = _safe_int(getattr(assignment, 'hero_party_position', 0), 0)
        if _uses_party_slot_targets(formation):
            label = f'Hero Slot {hero_position}' if hero_position > 0 else 'Hero Slot ?'
            return hero_position in lookup['hero_slots'], label

        hero_id = _safe_int(getattr(assignment, 'hero_id', 0), 0)
        hero_name = str(getattr(assignment, 'hero_name', '') or '').strip().casefold()
        if hero_id > 0 and hero_id in lookup['hero_ids']:
            return True, ''
        if hero_name and hero_name in lookup['hero_names']:
            return True, ''
        if hero_position > 0 and hero_position in lookup['hero_slots']:
            return True, ''
        return False, assignment.display_name()

    if assignment.kind == ASSIGNMENT_ACCOUNT:
        party_position = _safe_int(getattr(assignment, 'account_party_position', -1), -1)
        if _uses_party_slot_targets(formation):
            label = f'Player Slot {party_position + 1}' if party_position > LEADER_PARTY_POSITION else 'Player Slot ?'
            return party_position in lookup['account_positions'], label

        account_email = str(getattr(assignment, 'account_email', '') or '').strip().casefold()
        character_name = str(getattr(assignment, 'character_name', '') or '').strip().casefold()
        account_name = str(getattr(assignment, 'account_name', '') or '').strip().casefold()
        if account_email and account_email in lookup['account_emails']:
            return True, ''
        if character_name and character_name in lookup['character_names']:
            return True, ''
        if account_name and account_name in lookup['account_names']:
            return True, ''
        if party_position > LEADER_PARTY_POSITION and party_position in lookup['account_positions']:
            return True, ''
        return False, assignment.display_name()

    return False, assignment.display_name()


def _duplicate_target_details(formation: PartyFormation) -> list[str]:
    targets: dict[tuple[str, object], dict[str, Any]] = {}
    for index, assignment in enumerate(formation.assignments):
        target_key, target_label = _assignment_target_key(formation, assignment)
        if target_key is None:
            continue
        entry = targets.setdefault(target_key, {'label': target_label, 'spots': []})
        entry['spots'].append(assignment_spot_label(assignment, index))

    details: list[str] = []
    for entry in targets.values():
        spots = entry['spots']
        if len(spots) > 1:
            details.append(f'Duplicate {entry["label"]}: {", ".join(spots)}')
    return details


def _missing_target_details(formation: PartyFormation, lookup: dict[str, set]) -> list[str]:
    details: list[str] = []
    for index, assignment in enumerate(formation.assignments):
        available, label = _assignment_available_label(formation, assignment, lookup)
        if not available:
            details.append(f'Missing {assignment_spot_label(assignment, index)}: {label}')
    return details


def _hotkey_conflict_details(formation: PartyFormation) -> list[str]:
    key = formation.key()
    modifiers = formation.modifiers()
    if not _valid_hotkey_key(key):
        return []

    conflicts = [
        other.name or 'Unnamed Formation'
        for other in formations
        if other.formation_id != formation.formation_id and _same_hotkey(other, key, modifiers)
    ]
    if not conflicts:
        return []
    return [f'Hotkey also used by: {", ".join(conflicts)}']


def _formation_name_key(formation: PartyFormation) -> str:
    name = ' '.join(str(getattr(formation, 'name', '') or 'Unnamed Formation').split())
    return name.casefold() or 'unnamed formation'


def _formation_name_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for formation in formations:
        key = _formation_name_key(formation)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _duplicate_formation_name_details(
    formation: PartyFormation,
    name_counts: dict[str, int] | None = None,
) -> list[str]:
    counts = name_counts or _formation_name_counts()
    duplicate_count = counts.get(_formation_name_key(formation), 0)
    if duplicate_count <= 1:
        return []
    name = str(getattr(formation, 'name', '') or 'Unnamed Formation')
    return [f'Duplicate formation name {name!r}: {duplicate_count} formations use this visible name.']


def _duplicate_spot_label_details(formation: PartyFormation) -> list[str]:
    labels: dict[str, dict[str, Any]] = {}
    for index, assignment in enumerate(formation.assignments):
        label = assignment_spot_label(assignment, index)
        key = ' '.join(label.split()).casefold()
        entry = labels.setdefault(key, {'label': label, 'spots': []})
        entry['spots'].append(str(index + 1))

    details: list[str] = []
    for entry in labels.values():
        spots = entry['spots']
        if isinstance(spots, list) and len(spots) > 1:
            details.append(f'Duplicate spot label {entry["label"]!r}: spots {", ".join(spots)}')
    return details


def _offset_warning_details(formation: PartyFormation) -> list[str]:
    details: list[str] = []
    for index, assignment in enumerate(formation.assignments):
        warning = preflight_assignment_offset_warning(assignment)
        if warning:
            details.append(f'Offset {assignment_spot_label(assignment, index)}: {warning}')
    return details


def _formation_issue_groups(
    formation: PartyFormation,
    lookup: dict[str, set],
    name_counts: dict[str, int] | None = None,
) -> dict[str, list[str]]:
    return {
        'name': _duplicate_formation_name_details(formation, name_counts),
        'spot': _duplicate_spot_label_details(formation),
        'target': _duplicate_target_details(formation),
        'missing': _missing_target_details(formation, lookup),
        'hotkey': _hotkey_conflict_details(formation),
        'offset': _offset_warning_details(formation),
    }


def _formation_issue_details(issue_groups: dict[str, list[str]]) -> list[str]:
    details: list[str] = []
    for group_details in issue_groups.values():
        details.extend(group_details)
    return details


def _formation_issue_summary(issue_groups: dict[str, list[str]]) -> str:
    labels = {
        'name': 'name',
        'spot': 'spot',
        'target': 'target',
        'missing': 'missing',
        'hotkey': 'hotkey',
        'offset': 'offset',
    }
    parts = [
        f'{labels.get(group_key, group_key)} {len(group_details)}'
        for group_key, group_details in issue_groups.items()
        if group_details
    ]
    return ', '.join(parts) if parts else 'none'


def _formation_spot_counts(formation: PartyFormation) -> tuple[int, int, int]:
    enabled_count = sum(1 for assignment in formation.assignments if bool(getattr(assignment, 'enabled', True)))
    assigned_count = sum(1 for assignment in formation.assignments if assignment_has_target(assignment))
    unassigned_count = max(0, len(formation.assignments) - assigned_count)
    return enabled_count, assigned_count, unassigned_count


def _diagnostic_offset_tuple(assignment) -> tuple[float, float] | None:
    if isinstance(getattr(assignment, 'offset_x', None), bool) or isinstance(
        getattr(assignment, 'offset_y', None),
        bool,
    ):
        return None
    try:
        offset_x = float(assignment.offset_x)
        offset_y = float(assignment.offset_y)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(offset_x) or not math.isfinite(offset_y):
        return None
    return offset_x, offset_y


def _formation_footprint(formation: PartyFormation) -> tuple[str, list[str]]:
    points: list[tuple[float, float, str]] = []
    skipped_disabled = 0
    skipped_invalid = 0

    for index, assignment in enumerate(formation.assignments):
        if not bool(getattr(assignment, 'enabled', True)):
            skipped_disabled += 1
            continue
        offset = _diagnostic_offset_tuple(assignment)
        if offset is None:
            skipped_invalid += 1
            continue
        points.append((offset[0], offset[1], assignment_spot_label(assignment, index)))

    if not points:
        details = ['No enabled spots with valid offsets.']
        if skipped_disabled:
            details.append(f'Skipped {skipped_disabled} disabled spot{"s" if skipped_disabled != 1 else ""}.')
        if skipped_invalid:
            details.append(f'Skipped {skipped_invalid} invalid offset{"s" if skipped_invalid != 1 else ""}.')
        return 'no enabled spots', details

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    width = max_x - min_x
    height = max_y - min_y
    farthest_x, farthest_y, farthest_label = max(points, key=lambda point: math.hypot(point[0], point[1]))
    farthest_radius = math.hypot(farthest_x, farthest_y)

    spot_word = 'spot' if len(points) == 1 else 'spots'
    summary = f'{len(points)} {spot_word}, radius {farthest_radius:.0f}, {width:.0f} x {height:.0f}'
    details = [
        f'Enabled valid spots: {len(points)}',
        f'Farthest spot: {farthest_label} at {farthest_radius:.0f}',
        f'Approx width: {width:.0f}',
        f'Approx height: {height:.0f}',
    ]
    if skipped_disabled:
        details.append(f'Skipped {skipped_disabled} disabled spot{"s" if skipped_disabled != 1 else ""}.')
    if skipped_invalid:
        details.append(f'Skipped {skipped_invalid} invalid offset{"s" if skipped_invalid != 1 else ""}.')
    return summary, details


def _draw_formation_health_summary(formation: PartyFormation) -> None:
    enabled_count, assigned_count, unassigned_count = _formation_spot_counts(formation)

    members = _refresh_members()
    lookup = _member_lookup(members)
    issue_groups = _formation_issue_groups(formation, lookup)
    issue_details = _formation_issue_details(issue_groups)
    footprint_summary, footprint_details = _formation_footprint(formation)

    _draw_helper_text('Health:')
    ImGui.show_tooltip('Read-only formation summary.')
    PyImGui.same_line(0, 8)
    _draw_inline_count('Enabled', enabled_count, UI_COLOR_GOOD)
    PyImGui.same_line(0, 8)
    _draw_inline_count('Assigned', assigned_count, UI_COLOR_INFO)
    PyImGui.same_line(0, 8)
    _draw_inline_count('Unassigned', unassigned_count, UI_COLOR_MUTED)

    issue_color = UI_COLOR_GOOD if not issue_details else UI_COLOR_WARN
    PyImGui.text_colored('Issues: ' + _formation_issue_summary(issue_groups), issue_color)
    if issue_details:
        ImGui.show_tooltip('\n'.join(issue_details[:12]))
    else:
        ImGui.show_tooltip(
            'No duplicate names, duplicate spots, duplicate targets, missing targets, '
            'hotkey conflicts, or offset warnings detected.'
        )

    _draw_helper_text(f'Footprint: {footprint_summary}')
    ImGui.show_tooltip('\n'.join(footprint_details[:8]))


def _all_formations_diagnostic_rows(lookup: dict[str, set], name_counts: dict[str, int]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, formation in enumerate(formations):
        issue_groups = _formation_issue_groups(formation, lookup, name_counts)
        issue_details = _formation_issue_details(issue_groups)
        enabled_count, assigned_count, unassigned_count = _formation_spot_counts(formation)
        footprint_summary, footprint_details = _formation_footprint(formation)
        rows.append(
            {
                'index': index,
                'formation': formation,
                'issue_groups': issue_groups,
                'issue_details': issue_details,
                'enabled_count': enabled_count,
                'assigned_count': assigned_count,
                'unassigned_count': unassigned_count,
                'footprint_summary': footprint_summary,
                'footprint_details': footprint_details,
            }
        )
    return rows


def _draw_all_formations_diagnostics(selected_formation: PartyFormation) -> None:
    if not PyImGui.collapsing_header('All Formations##PartyFormationAllDiagnosticsSection'):
        return

    members = _refresh_members()
    lookup = _member_lookup(members)
    rows = _all_formations_diagnostic_rows(lookup, _formation_name_counts())
    issue_rows = sum(1 for row in rows if row['issue_details'])
    issue_color = UI_COLOR_GOOD if issue_rows == 0 else UI_COLOR_WARN

    _draw_helper_text('Read-only warning summary across saved formations.')
    PyImGui.same_line(0, 8)
    _draw_inline_count('Total', len(rows), UI_COLOR_INFO)
    PyImGui.same_line(0, 8)
    PyImGui.text_colored(f'Need review: {issue_rows}', issue_color)
    ImGui.show_tooltip('Warnings here do not block saving, applying, editing, importing, or hotkeys.')

    if not rows:
        _draw_helper_text('No formations to inspect.')
        return

    table_flags = (
        PyImGui.TableFlags.Borders
        | PyImGui.TableFlags.RowBg
        | PyImGui.TableFlags.SizingFixedFit
        | PyImGui.TableFlags.Resizable
        | PyImGui.TableFlags.ScrollX
    )
    if not PyImGui.begin_table('PartyFormationAllDiagnostics', 5, table_flags, 0, 0):
        return

    PyImGui.table_setup_column('Formation', PyImGui.TableColumnFlags.WidthFixed, 170)
    PyImGui.table_setup_column('Mode', PyImGui.TableColumnFlags.WidthFixed, 80)
    PyImGui.table_setup_column('Spots', PyImGui.TableColumnFlags.WidthFixed, 135)
    PyImGui.table_setup_column('Issues', PyImGui.TableColumnFlags.WidthFixed, 160)
    PyImGui.table_setup_column('Footprint', PyImGui.TableColumnFlags.WidthFixed, 190)
    PyImGui.table_headers_row()

    for row in rows:
        formation = row['formation']
        if not isinstance(formation, PartyFormation):
            continue
        issue_groups = row['issue_groups']
        issue_details = row['issue_details']
        footprint_details = row['footprint_details']
        issue_summary = _formation_issue_summary(issue_groups) if isinstance(issue_groups, dict) else 'none'
        current_marker = '> ' if formation.formation_id == selected_formation.formation_id else ''
        enabled_count_value = row.get('enabled_count')
        assigned_count_value = row.get('assigned_count')
        unassigned_count_value = row.get('unassigned_count')
        enabled_count = int(enabled_count_value) if isinstance(enabled_count_value, (int, float)) else 0
        assigned_count = int(assigned_count_value) if isinstance(assigned_count_value, (int, float)) else 0
        unassigned_count = int(unassigned_count_value) if isinstance(unassigned_count_value, (int, float)) else 0
        issue_details = issue_details if isinstance(issue_details, list) else []
        footprint_details = footprint_details if isinstance(footprint_details, list) else []

        PyImGui.table_next_row()
        PyImGui.table_next_column()
        PyImGui.text_wrapped(f'{current_marker}{formation.name or "Unnamed Formation"}')
        ImGui.show_tooltip('> marks the currently selected formation.' if current_marker else 'Saved formation.')

        PyImGui.table_next_column()
        _draw_helper_text(_target_mode_label(formation))

        PyImGui.table_next_column()
        _draw_helper_text(f'{enabled_count} on / {assigned_count} assigned / {unassigned_count} open')

        PyImGui.table_next_column()
        color = UI_COLOR_GOOD if not issue_details else UI_COLOR_WARN
        PyImGui.text_colored(issue_summary, color)
        if issue_details:
            ImGui.show_tooltip('\n'.join(str(detail) for detail in issue_details[:12]))
        else:
            ImGui.show_tooltip('No warning-only diagnostics for this formation.')

        PyImGui.table_next_column()
        _draw_helper_text(str(row['footprint_summary']))
        if isinstance(footprint_details, list):
            ImGui.show_tooltip('\n'.join(str(detail) for detail in footprint_details[:8]))

    PyImGui.end_table()


def _format_history_entry(entry: dict[str, object]) -> str:
    timestamp = str(entry.get('time') or '--:--:--')
    message = str(entry.get('message') or '')
    prefix = '!' if bool(entry.get('needs_attention')) else '-'
    message_type = str(entry.get('message_type') or '')
    if message_type:
        return f'{prefix} [{timestamp}] {message_type}: {message}'
    return f'{prefix} [{timestamp}] {message}'


def _apply_preview_diagnostic_lines(formation: PartyFormation) -> list[str]:
    lines: list[str] = []
    try:
        snapshot = preflight_apply_snapshot(formation)
    except Exception as exc:
        return [f'Apply Preview unavailable: {exc}']

    counts = snapshot.counts
    lines.append(
        f'Apply Preview: would target {snapshot.would_target}, skipped {snapshot.skipped}, '
        f'warnings {snapshot.warnings}, runtime checked {snapshot.runtime_checked}, ready {snapshot.runtime_ready}'
    )
    lines.append(
        f'Apply Counts: enabled {counts.enabled}, disabled {counts.disabled}, assigned {counts.assigned}, '
        f'unassigned {counts.unassigned}, duplicate targets {counts.duplicate_targets}, '
        f'offset warnings {counts.offset_warnings}'
    )
    for note in snapshot.warning_notes[:8]:
        lines.append(f'Apply Warning: {note}')
    for item in snapshot.items[:12]:
        detail = _preflight_detail_text(item)
        lines.append(f'Apply Row: {item.spot_label} | {item.status} | {detail}')
    if len(snapshot.items) > 12:
        lines.append(f'Apply Row: ... {len(snapshot.items) - 12} more')
    return lines


def _selected_formation_diagnostic_lines(formation: PartyFormation, lookup: dict[str, set]) -> list[str]:
    enabled_count, assigned_count, unassigned_count = _formation_spot_counts(formation)
    footprint_summary, footprint_details = _formation_footprint(formation)
    issue_groups = _formation_issue_groups(formation, lookup, _formation_name_counts())
    issue_details = _formation_issue_details(issue_groups)

    lines = [
        f'Selected Formation: {formation.name or "Unnamed Formation"}',
        f'Formation ID: {formation.formation_id}',
        f'Target Mode: {_target_mode_label(formation)}',
        f'Spots: {enabled_count} enabled, {assigned_count} assigned, {unassigned_count} unassigned',
        f'Issues: {_formation_issue_summary(issue_groups)}',
        f'Footprint: {footprint_summary}',
    ]
    for detail in issue_details[:12]:
        lines.append(f'Issue Detail: {detail}')
    for detail in footprint_details[:8]:
        lines.append(f'Footprint Detail: {detail}')
    return lines


def _all_formations_diagnostic_lines(lookup: dict[str, set]) -> list[str]:
    rows = _all_formations_diagnostic_rows(lookup, _formation_name_counts())
    issue_rows = sum(1 for row in rows if row['issue_details'])
    lines = [f'All Formations: {len(rows)} total, {issue_rows} need review']
    for row in rows[:24]:
        formation = row['formation']
        if not isinstance(formation, PartyFormation):
            continue
        issue_groups = row['issue_groups']
        issue_summary = _formation_issue_summary(issue_groups) if isinstance(issue_groups, dict) else 'none'
        lines.append(
            f'- {formation.name or "Unnamed Formation"} | {_target_mode_label(formation)} | '
            f'{row["enabled_count"]} on / {row["assigned_count"]} assigned / '
            f'{row["unassigned_count"]} open | issues {issue_summary} | {row["footprint_summary"]}'
        )
    if len(rows) > 24:
        lines.append(f'- ... {len(rows) - 24} more formations')
    return lines


def _action_history_diagnostic_lines() -> list[str]:
    if not action_history:
        return ['Recent Actions: none recorded']

    lines = ['Recent Actions:']
    for entry in action_history[-ACTION_HISTORY_LIMIT:]:
        lines.append(_format_history_entry(entry))
        details = entry.get('details')
        if isinstance(details, list):
            for detail in details[:5]:
                lines.append(f'    {detail}')
    return lines


def _build_diagnostics_text(formation: PartyFormation) -> str:
    members = _refresh_members()
    lookup = _member_lookup(members)

    lines = [
        f'{MODULE_NAME} Diagnostics',
        f'Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        '',
        'Current Status:',
        str(last_status or ''),
    ]
    for detail in status_lines[:10]:
        lines.append(f'  {detail}')

    lines.extend(['', 'Selected Formation:'])
    lines.extend(_selected_formation_diagnostic_lines(formation, lookup))
    lines.extend(['', 'Apply Preview:'])
    lines.extend(_apply_preview_diagnostic_lines(formation))
    lines.extend(['', 'All Formations:'])
    lines.extend(_all_formations_diagnostic_lines(lookup))
    lines.extend(['', 'Action History:'])
    lines.extend(_action_history_diagnostic_lines())
    return '\n'.join(lines)


def _copy_diagnostics_to_clipboard(formation: PartyFormation) -> None:
    try:
        diagnostics_text = _build_diagnostics_text(formation)
        PyImGui.set_clipboard_text(diagnostics_text)
    except Exception as exc:
        _set_status(
            f'Copy diagnostics failed: {exc}',
            log=False,
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    _set_status(
        f'Copied diagnostics for {formation.name}.',
        details=[f'Recent actions included: {len(action_history)}'],
        log=False,
        message_type=PySystem.Console.MessageType.Info,
    )


def _draw_action_history() -> None:
    if not PyImGui.collapsing_header('Recent Actions##PartyFormationActionHistorySection'):
        return

    PyImGui.same_line(0, 8)
    if PyImGui.button('Clear History##party_formation_clear_action_history'):
        _set_status('Cleared Party Formations action history.', log=False)
        action_history.clear()
        return
    ImGui.show_tooltip('Clear only this in-memory diagnostics history.')

    if not action_history:
        _draw_helper_text('No recent actions recorded yet.')
        return

    table_flags = (
        PyImGui.TableFlags.Borders
        | PyImGui.TableFlags.RowBg
        | PyImGui.TableFlags.SizingFixedFit
        | PyImGui.TableFlags.Resizable
        | PyImGui.TableFlags.ScrollY
    )
    if not PyImGui.begin_table('PartyFormationActionHistory', 3, table_flags, 0, 180):
        return

    PyImGui.table_setup_column('Time', PyImGui.TableColumnFlags.WidthFixed, 70)
    PyImGui.table_setup_column('Status', PyImGui.TableColumnFlags.WidthFixed, 230)
    PyImGui.table_setup_column('Details', PyImGui.TableColumnFlags.WidthFixed, 340)
    PyImGui.table_headers_row()

    for entry in reversed(action_history):
        details = entry.get('details')
        detail_text = ''
        if isinstance(details, list):
            detail_text = '\n'.join(str(detail) for detail in details[:5])
        color = UI_COLOR_WARN if bool(entry.get('needs_attention')) else UI_COLOR_HELPER

        PyImGui.table_next_row()
        PyImGui.table_next_column()
        _draw_helper_text(str(entry.get('time') or ''))
        PyImGui.table_next_column()
        PyImGui.text_colored(str(entry.get('message') or ''), color)
        PyImGui.table_next_column()
        if detail_text:
            PyImGui.text_wrapped(detail_text)
        else:
            _draw_helper_text('-')

    PyImGui.end_table()


def _read_selected_json(path: str, label: str) -> object:
    """Read a file only after the user selected it in the explicit importer."""
    try:
        with open(path, 'r', encoding='utf-8') as handle:  # user-directed import exception
            return json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f'Could not read {label}: {exc}') from exc


def _parse_legacy_window_ini(path: str, label: str) -> dict[str, object]:
    """Read only the legacy Window config section for one-time native ImGui seeding."""
    state: dict[str, object] = {}
    if not os.path.isfile(path):
        return state

    section = ''
    try:
        with open(path, 'r', encoding='utf-8') as handle:  # user-directed import exception
            lines = handle.readlines()
    except OSError as exc:
        raise ValueError(f'Could not read {label}: {exc}') from exc

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().casefold()
            continue
        if section != 'window config' or '=' not in line:
            continue
        key, value = (part.strip() for part in line.split('=', 1))
        key = key.casefold()
        if key in {'x', 'y', 'width', 'height'}:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f'{label} has an invalid {key} value.') from exc
            if not math.isfinite(number):
                raise ValueError(f'{label} has a non-finite {key} value.')
            if key in {'width', 'height'} and number <= 0:
                raise ValueError(f'{label} has a non-positive {key} value.')
            state[key] = number
        elif key == 'collapsed':
            normalized = value.casefold()
            if normalized not in {'true', 'false', '1', '0', 'yes', 'no', 'on', 'off'}:
                raise ValueError(f'{label} has an invalid collapsed value.')
            state[key] = normalized in {'true', '1', 'yes', 'on'}

    return state


def _legacy_ui_seeds_from_selected_config(selected_path: str) -> dict[str, dict[str, object]]:
    config_directory = os.path.dirname(os.path.abspath(selected_path))
    legacy_root = os.path.abspath(os.path.join(config_directory, os.pardir, os.pardir))
    settings_root = os.path.join(legacy_root, 'Settings')
    seeds: dict[str, dict[str, object]] = {}
    if not os.path.isdir(settings_root):
        return seeds

    for account_name in os.listdir(settings_root):  # explicit importer scope only
        account_directory = os.path.join(settings_root, account_name)
        party_formations_directory = os.path.join(account_directory, 'Widgets', 'PartyFormations')
        if not os.path.isdir(party_formations_directory):
            continue

        windows: dict[str, dict[str, object]] = {}
        for window_name, filename in (
            ('main', MAIN_WINDOW_INI_FILENAME),
            ('canvas', CANVAS_EDITOR_WINDOW_INI_FILENAME),
            ('floating', FLOATING_UI_INI_FILENAME),
        ):
            ini_path = os.path.join(party_formations_directory, filename)
            state = _parse_legacy_window_ini(ini_path, ini_path)
            if state:
                windows[window_name] = state
        if windows:
            seeds[account_name] = {'consumed': False, 'windows': windows}

    return seeds


def _build_legacy_migration_bundle(selected_path: str) -> tuple[dict[str, object], list[str]]:
    selected_path = os.path.abspath(str(selected_path or ''))
    if not selected_path or os.path.basename(selected_path).casefold() != 'party_formations.json':
        raise ValueError('Select the legacy Widgets/Config/party_formations.json file.')

    config_directory = os.path.dirname(selected_path)
    config = _read_selected_json(selected_path, 'Party Formations config')
    if not isinstance(config, dict):
        raise ValueError('Legacy Party Formations config must be a JSON object.')

    details: list[str] = []
    geometry_path = os.path.join(config_directory, GEOMETRY_PRESET_FILENAME)
    if os.path.isfile(geometry_path):
        geometry = _read_selected_json(geometry_path, 'Party Formations geometry presets')
    else:
        geometry = {
            'type': GEOMETRY_PRESET_LIBRARY_TYPE,
            'version': GEOMETRY_PRESET_LIBRARY_VERSION,
            'presets': [],
        }
        details.append('Geometry preset file was not found; no presets were imported.')

    backups: list[dict[str, object]] = []
    backup_directory = os.path.join(config_directory, 'party_formations_backups')
    if os.path.isdir(backup_directory):
        backup_names = sorted(
            (
                name
                for name in os.listdir(backup_directory)  # explicit importer scope only
                if name.startswith('party_formations.') and name.endswith('.json')
            ),
            reverse=True,
        )
        for name in backup_names:
            backup_path = os.path.join(backup_directory, name)
            if not os.path.isfile(backup_path):
                continue
            backup_config = _read_selected_json(backup_path, f'Party Formations backup {name}')
            if not isinstance(backup_config, dict):
                raise ValueError(f'Legacy Party Formations backup {name} must be a JSON object.')
            try:
                created_at = float(os.path.getmtime(backup_path))
            except OSError as exc:
                raise ValueError(f'Could not inspect Party Formations backup {name}: {exc}') from exc
            backups.append({'name': name, 'created_at': created_at, 'config': backup_config})
        if len(backups) > CONFIG_BACKUP_LIMIT:
            details.append(f'Only the newest {CONFIG_BACKUP_LIMIT} legacy backups will be imported.')
    else:
        details.append('Legacy backup directory was not found; no historical backups were imported.')

    bundle = {
        'type': 'py4gw_party_formations_migration',
        'version': 1,
        'source': 'user-selected legacy Party Formations data',
        'config': config,
        'geometry_presets': geometry,
        'backups': backups,
        'ui': _legacy_ui_seeds_from_selected_config(selected_path),
    }
    return bundle, details


def _import_legacy_party_formations_from_path(selected_path: str) -> None:
    global formations
    global selected_formation_index
    global formation_filter_pick_index
    global legacy_ui_seed_loaded
    global legacy_ui_seed_account_email
    global legacy_ui_seed_state
    global legacy_ui_seed_windows_seen

    try:
        bundle, details = _build_legacy_migration_bundle(selected_path)
        result = migrate_legacy_bundle(bundle)
    except Exception as exc:
        _set_status(
            f'Legacy Party Formations import failed: {exc}',
            log=True,
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    if not result.ok:
        _set_status(
            result.message or 'Legacy Party Formations import was rejected.',
            details=result.details,
            log=True,
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    formations = load_formations()
    selected_formation_index = min(selected_formation_index, max(0, len(formations) - 1))
    formation_filter_pick_index = 0
    legacy_ui_seed_loaded = False
    legacy_ui_seed_account_email = ''
    legacy_ui_seed_state = {}
    legacy_ui_seed_windows_seen.clear()
    _reset_toggle_state()
    _register_hotkeys()
    _set_status(
        result.message,
        details=details,
        log=True,
        message_type=PySystem.Console.MessageType.Info,
    )


def _backup_time_label(created_at: float) -> str:
    if created_at <= 0.0:
        return 'unknown time'
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_at))
    except Exception:
        return 'unknown time'


def _restore_latest_config_backup_from_ui() -> None:
    global formations
    global selected_formation_index
    global formation_filter_pick_index

    if _block_if_canvas_position_draft_dirty('restoring config backups'):
        return

    _finish_canvas_drag_if_needed()
    result = restore_latest_config_backup()
    if not result.ok:
        _set_status(
            result.message or 'Restore backup failed.',
            details=result.details,
            log=True,
            message_type=PySystem.Console.MessageType.Warning,
        )
        return

    formations = load_formations()
    selected_formation_index = min(selected_formation_index, max(0, len(formations) - 1))
    formation_filter_pick_index = 0
    _cancel_formation_name_edit()
    _clear_canvas_position_draft()
    _reset_toggle_state()
    if formations:
        _set_canvas_selection_group_to_primary(formations[selected_formation_index])
    else:
        canvas_selected_assignment_indexes.clear()
    _register_hotkeys()
    _set_status(
        result.message,
        details=result.details,
        log=True,
        message_type=PySystem.Console.MessageType.Info,
    )


def _draw_config_backups() -> None:
    if PyImGui.button('Import Legacy Party Formations##party_formation_import_legacy'):
        legacy_import_dialog.open_open(
            'Select legacy Party Formations config',
            valid_types='.json',
            tag='legacy_party_formations',
        )
    ImGui.show_tooltip(
        'Explicitly import a user-selected legacy party_formations.json and its known sibling data. '
        'Nothing is scanned during normal startup.'
    )
    selected_path = legacy_import_dialog.draw()
    if selected_path:
        _import_legacy_party_formations_from_path(str(selected_path))

    backups = list_config_backups()
    newest = backups[0] if backups else None
    newest_label = _backup_time_label(float(newest.created_at)) if newest is not None else 'none'
    summary_color = UI_COLOR_INFO if backups else UI_COLOR_HELPER
    PyImGui.text_colored(f'Config backups: {len(backups)} available, newest: {newest_label}', summary_color)
    ImGui.show_tooltip(
        'Backups are kept in the Party Formations JsonFactory document and restored only when you choose '
        'Restore Latest Backup.'
    )

    warning = config_load_warning()
    if warning and backups:
        PyImGui.text_colored('Config load warning: backups are available.', UI_COLOR_WARN)
        ImGui.show_tooltip(warning)

    if not PyImGui.collapsing_header('Config Backups##PartyFormationConfigBackupsSection'):
        return

    if not backups:
        _draw_helper_text('No backups have been created yet. Backups are created before overwriting a valid config.')
        if warning:
            PyImGui.text_colored(f'Config warning: {warning}', UI_COLOR_WARN)
        return

    _draw_helper_text('Backups are created before valid configs are overwritten. The newest 5 are kept.')
    latest = backups[0]
    restore_clicked = _draw_confirm_destructive_button(
        'Restore Latest Backup##party_formation_restore_latest_backup',
        confirmation_key=f'restore_latest_config:{latest.name}:{int(latest.created_at)}',
        width=138,
        height=0,
        armed_width=178,
    )
    ImGui.show_tooltip('Restore the newest backup. The current valid config is backed up first when possible.')
    if restore_clicked:
        _restore_latest_config_backup_from_ui()
        return

    _draw_helper_text('Latest backups:')
    for backup in backups[:5]:
        _draw_helper_text(f'{_backup_time_label(float(backup.created_at))} - {backup.name}')
        ImGui.show_tooltip('A saved copy of an older Party Formations config.')


def _draw_diagnostics_tools(formation: PartyFormation) -> None:
    if PyImGui.button('Copy Diagnostics##party_formation_copy_diagnostics'):
        _copy_diagnostics_to_clipboard(formation)
    ImGui.show_tooltip(
        'Copy selected formation diagnostics, Apply Preview, all-formation warnings, and recent actions.'
    )
    PyImGui.same_line(0, 8)
    _draw_helper_text(f'Recent actions: {len(action_history)}')
    ImGui.show_tooltip('Recent UI outcomes kept in memory for testing and diagnostics.')
    _draw_config_backups()
    _draw_action_history()


def _preflight_detail_text(item) -> str:
    detail = str(getattr(item, 'message', '') or '')
    target_x = getattr(item, 'target_x', None)
    target_y = getattr(item, 'target_y', None)
    if target_x is not None and target_y is not None:
        detail = f'{detail} ({float(target_x):.0f}, {float(target_y):.0f})'
    return detail


def _preflight_display_items(snapshot, row_mode_index: int) -> list:
    if row_mode_index == APPLY_PREVIEW_ROW_MODE_ISSUES_FIRST:
        issue_items = [item for item in snapshot.items if item.status != PREFLIGHT_STATUS_WOULD_TARGET]
        target_items = [item for item in snapshot.items if item.status == PREFLIGHT_STATUS_WOULD_TARGET]
        return issue_items + target_items

    return list(snapshot.items)


def _draw_apply_preflight_snapshot(formation: PartyFormation) -> None:
    global apply_preview_row_mode_index

    if not PyImGui.collapsing_header('Apply Preview##PartyFormationPreflightSection'):
        return

    try:
        snapshot = preflight_apply_snapshot(formation)
    except Exception as exc:
        _draw_helper_text(f'Preview unavailable: {exc}')
        return

    counts = snapshot.counts
    _draw_helper_text('Current check before Apply. State may change before Apply.')
    ImGui.show_tooltip('This only checks the current state; Apply may differ if party/map/account state changes.')
    _draw_helper_text(f'Checked: {time.strftime("%H:%M:%S")} (updates while open)')
    _draw_helper_text('Preview:')
    PyImGui.same_line(0, 8)
    _draw_inline_count('Would target', snapshot.would_target, UI_COLOR_GOOD)
    PyImGui.same_line(0, 8)
    _draw_inline_count('Skipped', snapshot.skipped, UI_COLOR_BAD if snapshot.skipped else UI_COLOR_MUTED)
    PyImGui.same_line(0, 8)
    _draw_inline_count('Warnings', snapshot.warnings, UI_COLOR_WARN if snapshot.warnings else UI_COLOR_MUTED)
    warning_details = list(snapshot.warning_notes[:8])
    if warning_details:
        ImGui.show_tooltip('\n'.join(warning_details))

    _draw_helper_text(
        f'{counts.enabled} enabled / {counts.disabled} off / {counts.unassigned} unassigned / '
        f'dup {counts.duplicate_targets} / offset {counts.offset_warnings}'
    )
    ImGui.show_tooltip('Preview counts only. This does not move heroes or change active flags.')

    apply_preview_row_mode_index = max(0, min(apply_preview_row_mode_index, len(APPLY_PREVIEW_ROW_MODE_LABELS) - 1))
    PyImGui.set_next_item_width(140)
    apply_preview_row_mode_index = PyImGui.combo(
        'Preview Rows',
        apply_preview_row_mode_index,
        APPLY_PREVIEW_ROW_MODE_LABELS,
    )
    ImGui.show_tooltip('Choose whether to show every row or only problems first.')
    apply_preview_row_mode_index = max(0, min(apply_preview_row_mode_index, len(APPLY_PREVIEW_ROW_MODE_LABELS) - 1))

    display_items = _preflight_display_items(snapshot, apply_preview_row_mode_index)
    _draw_helper_text(f'Rows shown: {len(display_items)} of {len(snapshot.items)}')
    ImGui.show_tooltip('Rows describe what Apply would try from the current live party state.')
    if not display_items:
        _draw_helper_text('No enabled assigned targets to preview.')
        return

    table_flags = (
        PyImGui.TableFlags.Borders
        | PyImGui.TableFlags.RowBg
        | PyImGui.TableFlags.SizingFixedFit
        | PyImGui.TableFlags.Resizable
    )
    if not PyImGui.begin_table('PartyFormationPreflightSnapshot', 3, table_flags, 0, 0):
        return

    PyImGui.table_setup_column('Spot', PyImGui.TableColumnFlags.WidthFixed, 120)
    PyImGui.table_setup_column('Status', PyImGui.TableColumnFlags.WidthFixed, 90)
    PyImGui.table_setup_column('Detail', PyImGui.TableColumnFlags.WidthFixed, 260)
    PyImGui.table_headers_row()

    for item in display_items:
        PyImGui.table_next_row()
        PyImGui.table_next_column()
        PyImGui.text_wrapped(str(getattr(item, 'spot_label', '') or 'Apply'))
        PyImGui.table_next_column()
        status = str(getattr(item, 'status', '') or '')
        PyImGui.text_colored(status, _preflight_status_color(status))
        ImGui.show_tooltip('Would target means Apply can currently send this spot. Other statuses need review.')
        PyImGui.table_next_column()
        PyImGui.text_wrapped(_preflight_detail_text(item))

    PyImGui.end_table()


def _member_mapping_keys(member: dict) -> list[tuple[str, object]]:
    keys: list[tuple[str, object]] = []
    kind = member.get('kind')
    if kind == ASSIGNMENT_HERO:
        hero_position = _safe_int(member.get('hero_party_position'), 0)
        hero_id = _safe_int(member.get('hero_id'), 0)
        hero_name = str(member.get('hero_name') or '').strip().casefold()
        if hero_id > 0:
            keys.append(('hero_id', hero_id))
        if hero_name:
            keys.append(('hero_name', hero_name))
        if hero_position > 0:
            keys.append(('hero_slot', hero_position))
    elif kind == ASSIGNMENT_ACCOUNT:
        party_position = _safe_int(member.get('account_party_position'), -1)
        account_email = str(member.get('account_email') or '').strip().casefold()
        character_name = str(member.get('character_name') or '').strip().casefold()
        account_name = str(member.get('account_name') or '').strip().casefold()
        if account_email:
            keys.append(('account_email', account_email))
        if character_name:
            keys.append(('character_name', character_name))
        if account_name:
            keys.append(('account_name', account_name))
        if party_position > LEADER_PARTY_POSITION:
            keys.append(('account_slot', party_position))
    return keys


def _member_slot_display(member: dict) -> str:
    slot_label = str(member.get('slot_label') or '').strip()
    if slot_label:
        return slot_label
    if member.get('kind') == ASSIGNMENT_HERO:
        hero_position = _safe_int(member.get('hero_party_position'), 0)
        return f'Hero Slot {hero_position}' if hero_position > 0 else 'Hero Slot ?'
    party_position = _safe_int(member.get('account_party_position'), -1)
    return f'Player Slot {party_position + 1}' if party_position > LEADER_PARTY_POSITION else 'Player Slot ?'


def _member_primary_mapping_key(formation: PartyFormation, member: dict) -> tuple[str, object] | None:
    keys = _member_mapping_keys(member)
    if not keys:
        return None

    if _uses_party_slot_targets(formation):
        slot_prefix = 'hero_slot' if member.get('kind') == ASSIGNMENT_HERO else 'account_slot'
        for key in keys:
            if key[0] == slot_prefix:
                return key
    return keys[0]


def _mapping_sort_key(row: dict) -> tuple[int, int, str]:
    key = row.get('key')
    label = str(row.get('target') or '')
    if isinstance(key, tuple) and len(key) == 2:
        key_kind, key_value = key
        if key_kind == 'hero_slot':
            return 0, _safe_int(key_value, 999), label
        if key_kind == 'account_slot':
            return 1, _safe_int(key_value, 999), label
        if str(key_kind).startswith('hero_'):
            return 2, 999, label
        return 3, 999, label
    return 4, 999, label


def _mapping_missing_status(row: dict) -> str:
    key = row.get('key')
    if isinstance(key, tuple) and key and key[0] in {'hero_slot', 'account_slot'}:
        return 'Empty'
    return 'Unavailable'


def _mapping_row_status(row: dict) -> str:
    member = str(row.get('member') or '')
    raw_spots = row.get('spots')
    spots: list[object] = raw_spots if isinstance(raw_spots, list) else []
    if not member:
        return _mapping_missing_status(row)
    if len(spots) > 1:
        return 'Duplicate'
    if spots:
        return 'Assigned'
    return 'Available'


def _mapping_status_tooltip(status: str) -> str:
    if status == 'Assigned':
        return 'This current party member is used by one formation spot.'
    if status == 'Duplicate':
        return 'More than one formation spot resolves to this same current party member.'
    if status == 'Unavailable':
        return 'The saved target was not found in the current party.'
    if status == 'Empty':
        return 'The saved party slot is currently empty.'
    if status == 'Available':
        return 'This current party member is available but not assigned in this formation.'
    return 'Current-party lookup status for this saved target.'


def _mapping_summary_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = _mapping_row_status(row)
        counts[status] = counts.get(status, 0) + 1
    return counts


def _mapping_spot_label(assignment, index: int) -> str:
    spot_label = assignment_spot_label(assignment, index)
    if not bool(getattr(assignment, 'enabled', True)):
        return f'{spot_label} (off)'
    return spot_label


def _current_party_mapping_rows(formation: PartyFormation) -> list[dict]:
    members = _refresh_members()
    rows: list[dict] = []
    alias_to_row: dict[tuple[str, object], int] = {}

    for member in members:
        primary_key = _member_primary_mapping_key(formation, member)
        if primary_key is None:
            continue
        row_index = len(rows)
        rows.append(
            {
                'key': primary_key,
                'target': _member_slot_display(member),
                'member': str(member.get('label') or 'Member'),
                'spots': [],
            }
        )
        for key in _member_mapping_keys(member):
            alias_to_row.setdefault(key, row_index)

    for index, assignment in enumerate(formation.assignments):
        target_key, target_label = _assignment_target_key(formation, assignment)
        if target_key is None:
            continue

        row_index = alias_to_row.get(target_key)
        if row_index is None:
            row_index = len(rows)
            rows.append(
                {
                    'key': target_key,
                    'target': target_label,
                    'member': '',
                    'spots': [],
                }
            )
            alias_to_row[target_key] = row_index
        rows[row_index]['spots'].append(_mapping_spot_label(assignment, index))

    return sorted(rows, key=_mapping_sort_key)


def _draw_mapping_summary_segment(
    status: str,
    count: int,
    label: str,
    wrote_segment: bool,
    *,
    plural_label: str | None = None,
    show_zero: bool = False,
) -> bool:
    if count <= 0 and not show_zero:
        return wrote_segment
    PyImGui.same_line(0, 4)
    prefix = ', ' if wrote_segment else ''
    display_label = label if count == 1 or plural_label is None else plural_label
    PyImGui.text_colored(f'{prefix}{count} {display_label}', _mapping_status_color(status))
    return True


def _draw_current_party_mapping_summary(rows: list[dict]) -> None:
    if not rows:
        _draw_helper_text('Mapping: no current-party mapping data.')
        return

    counts = _mapping_summary_counts(rows)
    _draw_helper_text('Mapping:')
    ImGui.show_tooltip('Live lookup of this formation against the current party.')
    wrote_segment = False
    wrote_segment = _draw_mapping_summary_segment(
        'Assigned',
        counts.get('Assigned', 0),
        'assigned',
        wrote_segment,
        show_zero=True,
    )
    wrote_segment = _draw_mapping_summary_segment(
        'Duplicate',
        counts.get('Duplicate', 0),
        'duplicate',
        wrote_segment,
        plural_label='duplicates',
    )
    wrote_segment = _draw_mapping_summary_segment(
        'Unavailable',
        counts.get('Unavailable', 0),
        'unavailable',
        wrote_segment,
    )
    wrote_segment = _draw_mapping_summary_segment('Empty', counts.get('Empty', 0), 'empty', wrote_segment)
    _draw_mapping_summary_segment('Available', counts.get('Available', 0), 'available', wrote_segment)


def _draw_current_party_mapping(formation: PartyFormation, rows: list[dict] | None = None) -> None:
    if rows is None:
        rows = _current_party_mapping_rows(formation)
    if not rows:
        _draw_helper_text('No current-party mapping data.')
        return

    table_flags = (
        PyImGui.TableFlags.Borders
        | PyImGui.TableFlags.RowBg
        | PyImGui.TableFlags.SizingFixedFit
        | PyImGui.TableFlags.Resizable
    )
    if not PyImGui.begin_table('PartyFormationCurrentMapping', 4, table_flags, 0, 0):
        return

    PyImGui.table_setup_column('Target / Slot', PyImGui.TableColumnFlags.WidthFixed, 130)
    PyImGui.table_setup_column('Current Member', PyImGui.TableColumnFlags.WidthFixed, 170)
    PyImGui.table_setup_column('Formation Spot', PyImGui.TableColumnFlags.WidthFixed, 150)
    PyImGui.table_setup_column('Status', PyImGui.TableColumnFlags.WidthFixed, 90)
    PyImGui.table_headers_row()

    for row in rows:
        spots = row.get('spots') if isinstance(row.get('spots'), list) else []
        PyImGui.table_next_row()
        PyImGui.table_next_column()
        PyImGui.text_wrapped(str(row.get('target') or 'Unknown'))
        ImGui.show_tooltip('Saved party slot or identity key being checked.')
        PyImGui.table_next_column()
        PyImGui.text_wrapped(str(row.get('member') or '-'))
        ImGui.show_tooltip('Current party member matched to that saved target, if any.')
        PyImGui.table_next_column()
        PyImGui.text_wrapped(', '.join(spots) if spots else 'None')
        ImGui.show_tooltip('Formation spots that resolve to this target.')
        PyImGui.table_next_column()
        status = _mapping_row_status(row)
        PyImGui.text_colored(status, _mapping_status_color(status))
        ImGui.show_tooltip(_mapping_status_tooltip(status))

    PyImGui.end_table()


def _draw_status() -> None:
    if last_status_needs_attention:
        PyImGui.push_style_color(PyImGui.ImGuiCol.Text, UI_COLOR_BAD)
        PyImGui.text_wrapped(last_status)
        PyImGui.pop_style_color(1)
    else:
        PyImGui.text_wrapped(last_status)

    for index, line in enumerate(status_lines[:5]):
        if index < len(status_line_attention) and status_line_attention[index]:
            PyImGui.push_style_color(PyImGui.ImGuiCol.Text, UI_COLOR_BAD)
            PyImGui.text_wrapped(line)
            PyImGui.pop_style_color(1)
        else:
            _draw_helper_text(line)


def _draw_member_adder(formation: PartyFormation) -> None:
    global selected_member_index

    members = _refresh_members()
    _draw_helper_text('Pick a current party member to add or use with row Assign/Replace.')

    if not members:
        if PyImGui.button('Refresh Members'):
            members = _refresh_members(force=True)
        ImGui.show_tooltip('Refresh controllable heroes and follower accounts from the current party.')
        _draw_helper_text('No controllable current-party heroes or follower accounts found.')
        return

    party_slot_mode = _uses_party_slot_targets(formation)
    labels = [_member_label(member, party_slot_mode=party_slot_mode) for member in members]
    selected_member_index = max(0, min(selected_member_index, len(labels) - 1))
    PyImGui.set_next_item_width(250)
    selected_member_index = PyImGui.combo('Selected Member', selected_member_index, labels)
    ImGui.show_tooltip('This selected member is used by Add Assignment and by Assign/Replace in the table.')
    PyImGui.same_line(0, 8)
    if PyImGui.button('Refresh'):
        members = _refresh_members(force=True)
    ImGui.show_tooltip('Refresh controllable heroes and follower accounts from the current party.')

    if len(formation.assignments) >= MAX_FORMATION_SPOTS:
        _draw_helper_text(f'Maximum {MAX_FORMATION_SPOTS} assignable spots reached.')
        return

    add_assignment_clicked = PyImGui.button('Add Assignment')
    ImGui.show_tooltip('Add the selected member as a new formation spot. Existing rows are unchanged.')
    if add_assignment_clicked:
        if _block_if_canvas_position_draft_dirty('adding assignments', formation):
            return
        offset_x, offset_y = _default_offset(len(formation.assignments))
        assignment = assignment_from_member(members[selected_member_index], offset_x, offset_y)
        assignment.spot_label = default_spot_label(len(formation.assignments))
        formation.assignments.append(assignment)
        _clamp_canvas_selection(formation)
        _save()
        _set_status(f'Added {labels[selected_member_index]} to {formation.name}.', log=False)


def _draw_assignment_table(formation: PartyFormation) -> None:
    if not formation.assignments:
        _draw_helper_text('No assignments yet.')
        return

    draft_dirty = _canvas_position_draft_dirty_for(formation)
    remove_index = -1
    capture_all_clicked = PyImGui.button('Capture All Offsets')
    ImGui.show_tooltip('Capture current offsets for every assigned target in this formation.')
    if capture_all_clicked:
        if _block_if_canvas_position_draft_dirty('capturing offsets', formation):
            return
        messages: list[str] = []
        captured = 0
        for index, assignment in enumerate(formation.assignments):
            if not assignment_has_target(assignment):
                messages.append(f'{assignment_spot_label(assignment, index)}: no target assigned.')
                continue
            ok, message = capture_assignment_offset(assignment, formation.target_mode)
            messages.append(message)
            if ok:
                captured += 1
        if captured:
            _save()
        _set_status(f'Captured {captured} assignment offsets.', details=messages, log=True)

    _draw_helper_text('Assign/Replace uses the selected member from Members.')
    if draft_dirty:
        PyImGui.text_colored('Canvas draft unsaved: offset fields are read-only until Save/Revert.', UI_COLOR_WARN)

    table_flags = (
        PyImGui.TableFlags.Borders
        | PyImGui.TableFlags.RowBg
        | PyImGui.TableFlags.SizingFixedFit
        | PyImGui.TableFlags.Resizable
        | PyImGui.TableFlags.ScrollX
    )
    if PyImGui.begin_table('PartyFormationAssignments', 6, table_flags, 0, 0):
        PyImGui.table_setup_column('Enabled', PyImGui.TableColumnFlags.WidthFixed, 62)
        PyImGui.table_setup_column('Spot', PyImGui.TableColumnFlags.WidthFixed, 126)
        PyImGui.table_setup_column('Target', PyImGui.TableColumnFlags.WidthFixed, 155)
        PyImGui.table_setup_column('X', PyImGui.TableColumnFlags.WidthFixed, 84)
        PyImGui.table_setup_column('Y', PyImGui.TableColumnFlags.WidthFixed, 84)
        PyImGui.table_setup_column('Actions', PyImGui.TableColumnFlags.WidthFixed, 242)
        PyImGui.table_headers_row()

        for index, assignment in enumerate(formation.assignments):
            PyImGui.table_next_row()

            PyImGui.table_next_column()
            new_enabled = PyImGui.checkbox(f'##enabled_{formation.formation_id}_{index}', assignment.enabled)
            if new_enabled != assignment.enabled:
                assignment.enabled = new_enabled
                _save()
            PyImGui.same_line(0, 4)
            PyImGui.text_colored('Yes' if new_enabled else 'No', UI_COLOR_GOOD if new_enabled else UI_COLOR_MUTED)
            ImGui.show_tooltip('Enable or disable this formation spot without removing it.')

            PyImGui.table_next_column()
            spot_label = assignment_spot_label(assignment, index)
            PyImGui.set_next_item_width(120)
            new_spot_label = PyImGui.input_text(f'##spot_label_{formation.formation_id}_{index}', spot_label)
            ImGui.show_tooltip('Short label shown in the canvas, diagnostics, and imported/exported shapes.')
            if new_spot_label.strip() != spot_label:
                assignment.spot_label = new_spot_label.strip()
                _save()

            PyImGui.table_next_column()
            PyImGui.text_wrapped(_assignment_display_label(formation, assignment))
            ImGui.show_tooltip('The saved target for this spot. Assign/Replace changes it.')
            PyImGui.text_colored(
                _assignment_kind_label(formation, assignment),
                _assignment_kind_color(formation, assignment),
            )
            ImGui.show_tooltip('How this spot is resolved when Apply runs.')

            PyImGui.table_next_column()
            if draft_dirty:
                _draw_helper_text(f'{float(assignment.offset_x):.3f}')
                ImGui.show_tooltip('Stored X offset. In the Canvas Editor this controls visible up/down placement.')
            else:
                PyImGui.set_next_item_width(70)
                new_x = PyImGui.input_float(f'##offset_x_{formation.formation_id}_{index}', float(assignment.offset_x))
                ImGui.show_tooltip('Stored X offset. In the Canvas Editor this controls visible up/down placement.')
                if abs(float(new_x) - float(assignment.offset_x)) > 0.001:
                    assignment.offset_x = float(new_x)
                    _save()

            PyImGui.table_next_column()
            if draft_dirty:
                _draw_helper_text(f'{float(assignment.offset_y):.3f}')
                ImGui.show_tooltip('Stored Y offset. In the Canvas Editor this controls visible left/right placement.')
            else:
                PyImGui.set_next_item_width(70)
                new_y = PyImGui.input_float(f'##offset_y_{formation.formation_id}_{index}', float(assignment.offset_y))
                ImGui.show_tooltip('Stored Y offset. In the Canvas Editor this controls visible left/right placement.')
                if abs(float(new_y) - float(assignment.offset_y)) > 0.001:
                    assignment.offset_y = float(new_y)
                    _save()

            PyImGui.table_next_column()
            if not assignment_has_target(assignment):
                _draw_helper_text('No target')
                ImGui.show_tooltip('Assign a target before capturing an offset.')
                PyImGui.same_line(0, 3)
            else:
                capture_clicked = PyImGui.button(f'Capture##capture_{formation.formation_id}_{index}', 58, 0)
                ImGui.show_tooltip('Capture this spot offset from its assigned target.')
                if capture_clicked:
                    if _block_if_canvas_position_draft_dirty('capturing offsets', formation):
                        continue
                    ok, message = capture_assignment_offset(assignment, formation.target_mode)
                    if ok:
                        _save()
                    _set_status(
                        message,
                        log=True,
                        message_type=PySystem.Console.MessageType.Info if ok else PySystem.Console.MessageType.Warning,
                    )
                PyImGui.same_line(0, 3)

            action_label = 'Assign' if not assignment_has_target(assignment) else 'Replace'
            assign_clicked = PyImGui.button(f'{action_label}##assign_{formation.formation_id}_{index}', 58, 0)
            ImGui.show_tooltip('Use the selected member from Members for this spot.')
            if assign_clicked:
                _assign_selected_member_to_spot(formation, index)
            if assignment_has_target(assignment):
                PyImGui.same_line(0, 3)
                clear_clicked = PyImGui.button(f'Clear##clear_target_{formation.formation_id}_{index}', 46, 0)
                ImGui.show_tooltip('Clear only this spot target; geometry and spot label stay in place.')
                if clear_clicked:
                    _clear_assignment_target(formation, index)

            PyImGui.same_line(0, 3)
            remove_label = f'Remove##remove_{formation.formation_id}_{index}'
            if draft_dirty:
                remove_clicked = PyImGui.button(remove_label, 58, 0)
            else:
                remove_clicked = _draw_confirm_destructive_button(
                    remove_label,
                    confirmation_key=_assignment_remove_confirmation_key(formation, assignment, index),
                    width=58,
                    height=0,
                    armed_width=70,
                )
            ImGui.show_tooltip('Requires confirmation. Removes this row, including its target and geometry.')
            if remove_clicked:
                if not _block_if_canvas_position_draft_dirty('removing assignments', formation):
                    remove_index = index

        PyImGui.end_table()

    if remove_index >= 0:
        removed = formation.assignments.pop(remove_index)
        _set_canvas_selection_group_to_primary(formation)
        _save()
        _set_status(f'Removed {removed.display_name()} from {formation.name}.', log=False)


def _draw_formation_filter_controls() -> tuple[bool, list[int]]:
    global formation_filter_text

    PyImGui.set_next_item_width(220)
    new_filter_text = PyImGui.input_text('Filter##party_formation_filter', formation_filter_text)
    if new_filter_text != formation_filter_text:
        formation_filter_text = new_filter_text

    query = _formation_filter_query()
    filtered_indexes = _filtered_formation_indexes(query)
    filter_active = bool(query)
    ImGui.show_tooltip(
        'Filter formations by name, target mode, spot label, or target label. Filtering does not edit them.'
    )

    if filter_active:
        PyImGui.same_line(0, 8)
        if PyImGui.button('Clear Filter##party_formation_filter_clear'):
            formation_filter_text = ''
            query = ''
            filtered_indexes = _filtered_formation_indexes(query)
            filter_active = False
        ImGui.show_tooltip('Show every formation again.')

    if filter_active:
        _draw_helper_text(f'Filter: showing {len(filtered_indexes)} of {len(formations)} formations.')
    else:
        _draw_helper_text(f'Filter: off ({len(formations)} formations).')

    return filter_active, filtered_indexes


def _draw_formation_controls() -> PartyFormation | None:
    global selected_formation_index
    global formation_filter_pick_index

    _draw_section_header('Formation')
    selected_formation_index = max(0, min(selected_formation_index, len(formations) - 1))
    filter_active, filtered_indexes = _draw_formation_filter_controls()

    if filter_active:
        filtered_names = [_formation_combo_label(index) for index in filtered_indexes]
        if not filtered_indexes:
            formation = _selected_formation()
            if formation is not None:
                PyImGui.set_next_item_width(260)
                PyImGui.input_text(
                    f'Formation##formation_filter_no_matches_{formation.formation_id}',
                    formation.name,
                    PyImGui.InputTextFlags.ReadOnly,
                )
                ImGui.show_tooltip('Still selected. The active filter only hides it from the visible match list.')
            _draw_helper_text('No formations match the filter. Clear it to choose from the full list.')
        elif selected_formation_index in filtered_indexes:
            filtered_selected_index = filtered_indexes.index(selected_formation_index)
            PyImGui.set_next_item_width(260)
            new_filtered_index = PyImGui.combo('Formation', filtered_selected_index, filtered_names)
            ImGui.show_tooltip('Choose which visible formation to edit.')
            if new_filtered_index != filtered_selected_index:
                _select_formation_index(filtered_indexes[new_filtered_index])
        else:
            formation = _selected_formation()
            if formation is not None:
                PyImGui.set_next_item_width(260)
                PyImGui.input_text(
                    f'Formation##formation_filter_hidden_{formation.formation_id}',
                    formation.name,
                    PyImGui.InputTextFlags.ReadOnly,
                )
                ImGui.show_tooltip('Still selected. Apply, Clear, and Save still use this formation.')
            _draw_helper_text('Filter hides the selected formation; actions still use the selected formation.')
            formation_filter_pick_index = max(0, min(formation_filter_pick_index, len(filtered_indexes) - 1))
            PyImGui.set_next_item_width(220)
            formation_filter_pick_index = PyImGui.combo(
                'Visible Match##party_formation_filter_match',
                formation_filter_pick_index,
                filtered_names,
            )
            ImGui.show_tooltip('Pick a filtered formation, then press Select Match.')
            PyImGui.same_line(0, 8)
            if PyImGui.button('Select Match##party_formation_filter_select'):
                if _select_formation_index(filtered_indexes[formation_filter_pick_index]):
                    formation_filter_pick_index = 0
            ImGui.show_tooltip('Switch to the visible filtered formation.')
    else:
        names = [_formation_combo_label(index) for index in range(len(formations))]
        PyImGui.set_next_item_width(260)
        new_selected_formation_index = PyImGui.combo('Formation', selected_formation_index, names)
        ImGui.show_tooltip('Choose which formation to edit.')
        if new_selected_formation_index != selected_formation_index:
            _select_formation_index(new_selected_formation_index)

    formation = _selected_formation()
    if formation is None:
        return None

    _draw_formation_name_control(formation)

    target_modes = [TARGET_MODE_PARTY_SLOT, TARGET_MODE_IDENTITY]
    target_labels = ['Party Slot', 'Identity']
    current_mode_index = 0 if _uses_party_slot_targets(formation) else 1
    PyImGui.set_next_item_width(180)
    new_mode_index = PyImGui.combo('Track Targets By', current_mode_index, target_labels)
    if PyImGui.is_item_hovered():
        PyImGui.set_next_window_size((300, 0), PyImGui.ImGuiCond.Always)
        if ImGui.begin_tooltip():
            ImGui.text_wrapped(
                'Party Slot: follows the party slot number, like Hero Slot 1. Use this when whoever is in that slot '
                'should use the spot.\n\n'
                'Identity: follows the same named member, account, or character identity. Use this when that member '
                'should keep the spot even if party order changes.\n\n'
                'Changing mode asks for confirmation and may require rebuilding assignments.'
            )
            ImGui.end_tooltip()
    if new_mode_index != current_mode_index:
        _request_target_mode_change(formation, target_modes[new_mode_index], target_labels[new_mode_index])
    if formation_has_assigned_targets(formation):
        _draw_helper_text('Changing mode may require rebuilding assignments.')
    _draw_target_mode_change_popup()

    key, modifiers, changed = _party_keybinding('Hotkey', formation.key(), formation.modifiers())
    ImGui.show_tooltip('Press this shortcut to apply the formation. Shared hotkeys are reported in Diagnostics.')
    if changed:
        formation.set_hotkey(key, modifiers)
        _save()
        _set_status(f'Hotkey for {formation.name}: {ImGui.format_hotkey(key, modifiers)}', log=False)

    return formation


def _draw_actions_controls(formation: PartyFormation) -> bool:
    global selected_formation_index

    _draw_section_header('Actions')
    _draw_action_row_label('Edit')
    PyImGui.same_line(0, 8)
    if PyImGui.button('New'):
        if _block_if_canvas_position_draft_dirty('creating formations'):
            return True
        _finish_canvas_drag_if_needed()
        formations.append(create_empty_formation(formations))
        _cancel_formation_name_edit()
        selected_formation_index = len(formations) - 1
        _set_canvas_selection_group_to_primary(formations[selected_formation_index])
        _save()
        return True
    ImGui.show_tooltip('Create a blank formation and select it for editing.')

    PyImGui.same_line(0, 6)
    if PyImGui.button('Duplicate'):
        _duplicate_formation(formation)
        return True
    ImGui.show_tooltip('Copy this formation as a new editable formation. Hotkeys are not copied.')

    PyImGui.same_line(0, 6)
    delete_label = f'Delete##delete_formation_{formation.formation_id}'
    if _canvas_position_draft_dirty_for(formation):
        delete_clicked = PyImGui.button(delete_label)
    else:
        delete_clicked = _draw_confirm_destructive_button(
            delete_label,
            confirmation_key=f'formation_delete:{formation.formation_id}',
        )
    if delete_clicked:
        if _block_if_canvas_position_draft_dirty('deleting formations', formation):
            return True
        _finish_canvas_drag_if_needed()
        removed = formations.pop(selected_formation_index)
        _cancel_formation_name_edit()
        selected_formation_index = min(selected_formation_index, max(0, len(formations) - 1))
        if formations:
            _set_canvas_selection_group_to_primary(formations[selected_formation_index])
        else:
            canvas_selected_assignment_indexes.clear()
        _save()
        _set_status(f'Deleted {removed.name}.', log=False)
        return True
    ImGui.show_tooltip('Requires confirmation. Deletes this saved formation from the config.')

    PyImGui.same_line(0, 6)
    if PyImGui.button('Save'):
        if _block_if_canvas_position_draft_dirty('using the main Save button', formation):
            return True
        else:
            _save()
            _set_status(f'Saved {formation.name}.', log=False)
    ImGui.show_tooltip('Write formation changes to config. The previous valid config is backed up first.')

    _draw_action_row_label('In-Game')
    PyImGui.same_line(0, 8)
    if PyImGui.button('Apply'):
        if not _block_if_canvas_position_draft_dirty('applying formations', formation):
            _apply_formation_by_id(formation.formation_id, respect_keyboard_capture=False, use_cooldown=False)
    ImGui.show_tooltip('Send in-game flags now for this formation. Check Apply Preview first if unsure.')

    PyImGui.same_line(0, 6)
    if PyImGui.button('Clear Flags'):
        _clear_formation_by_id(formation.formation_id, respect_keyboard_capture=False, use_cooldown=False)
    ImGui.show_tooltip('Clear in-game flags for this formation only.')

    _draw_action_row_label('Files')
    PyImGui.same_line(0, 8)
    if PyImGui.button('Export Shape'):
        _export_shape_to_clipboard(formation)
    ImGui.show_tooltip('Copy enabled spot labels and offsets to the clipboard. Targets and hotkeys are not included.')

    PyImGui.same_line(0, 6)
    if PyImGui.button('Import Shape'):
        _import_shape_from_clipboard()
    ImGui.show_tooltip('Import spot labels and offsets from the clipboard as a new unassigned formation.')

    _draw_action_row_label('Editor')
    PyImGui.same_line(0, 8)
    canvas_editor_button_label = 'Close Canvas Editor' if canvas_editor_open else 'Open Canvas Editor'
    if PyImGui.button(canvas_editor_button_label):
        if canvas_editor_open:
            _close_canvas_editor_from_button(formation)
        else:
            _open_canvas_editor(formation)
    ImGui.show_tooltip('Open the larger position editor. Movement stays draft-only until Save Positions.')

    return False


def _draw_top_formation_actions() -> tuple[PartyFormation | None, bool]:
    available_width, _available_height = PyImGui.get_content_region_avail()
    if float(available_width or 0.0) < 720.0:
        formation = _draw_formation_controls()
        if formation is None:
            return None, False
        return formation, _draw_actions_controls(formation)

    table_flags = PyImGui.TableFlags.SizingStretchProp | PyImGui.TableFlags.NoSavedSettings
    if not PyImGui.begin_table('PartyFormationTopBlock', 2, table_flags, 0, 0):
        formation = _draw_formation_controls()
        if formation is None:
            return None, False
        return formation, _draw_actions_controls(formation)

    PyImGui.table_setup_column('Formation##PartyFormationTopLeft', PyImGui.TableColumnFlags.WidthStretch, 0.58)
    PyImGui.table_setup_column('Actions##PartyFormationTopRight', PyImGui.TableColumnFlags.WidthStretch, 0.42)
    PyImGui.table_next_row()
    PyImGui.table_next_column()
    formation = _draw_formation_controls()
    stop_drawing = False
    PyImGui.table_next_column()
    if formation is not None:
        stop_drawing = _draw_actions_controls(formation)
    PyImGui.end_table()
    return formation, stop_drawing


def _draw_formation_body_tabs(formation: PartyFormation) -> None:
    PyImGui.spacing()
    if not PyImGui.begin_tab_bar('PartyFormationMainBodyTabs'):
        return

    if PyImGui.begin_tab_item('Assignments##PartyFormationAssignmentsTab'):
        _begin_major_section('Members')
        _draw_member_adder(formation)
        _end_major_section()

        _begin_major_section('Assignments')
        if PyImGui.collapsing_header('Assignment Table##PartyFormationAssignmentsSection'):
            _draw_assignment_table(formation)
        _end_major_section()

        PyImGui.end_tab_item()

    if PyImGui.begin_tab_item('Diagnostics##PartyFormationDiagnosticsTab'):
        _begin_major_section('Diagnostics')
        _draw_diagnostics_tools(formation)
        _draw_all_formations_diagnostics(formation)
        _draw_apply_preflight_snapshot(formation)
        mapping_rows = _current_party_mapping_rows(formation)
        _draw_current_party_mapping_summary(mapping_rows)
        if PyImGui.collapsing_header('Current Party Mapping##PartyFormationCurrentMappingSection'):
            _draw_current_party_mapping(formation, mapping_rows)
        _end_major_section()

        PyImGui.end_tab_item()

    if PyImGui.begin_tab_item('Canvas##PartyFormationCanvasTab'):
        _begin_major_section('Canvas Tools')
        _draw_canvas_tools_settings(formation)
        _end_major_section()

        PyImGui.end_tab_item()

    PyImGui.end_tab_bar()


def _draw_formation_editor() -> None:
    global selected_formation_index

    if not formations:
        _draw_section_header('Formation')
        _draw_helper_text('No formations saved yet.')
        if PyImGui.button('Create Formation'):
            formations.append(create_empty_formation(formations))
            _cancel_formation_name_edit()
            selected_formation_index = len(formations) - 1
            _set_canvas_selection_group_to_primary(formations[selected_formation_index])
            _save()
        ImGui.show_tooltip('Create the first blank formation.')
        PyImGui.same_line(0, 8)
        if PyImGui.button('Import Shape'):
            _import_shape_from_clipboard()
        ImGui.show_tooltip('Import spot labels and offsets from the clipboard as a new unassigned formation.')
        _draw_section_header('Status')
        _draw_status()
        _draw_section_header('Persistence')
        _draw_config_backups()
        return

    formation, stop_drawing = _draw_top_formation_actions()
    if formation is None or stop_drawing:
        return

    _draw_section_header('Status')
    _draw_formation_health_summary(formation)

    PyImGui.spacing()
    _draw_status()

    _draw_formation_body_tabs(formation)


def on_enable() -> None:
    _ensure_loaded()


def on_disable() -> None:
    _unregister_hotkeys()


def configure() -> None:
    _ensure_loaded()
    _reset_toggle_state_if_context_changed()
    _release_hotkey_latches()
    PyImGui.set_next_window_size((420, 520), PyImGui.ImGuiCond.FirstUseEver)
    if PyImGui.begin('Party Formations Config', PyImGui.WindowFlags.NoFlag):
        _draw_formation_editor()
    PyImGui.end()
    _draw_canvas_editor_window()


def main() -> None:
    global show_main_window
    global expand_main_window_on_next_show

    _ensure_loaded()
    _reset_toggle_state_if_context_changed()
    _release_hotkey_latches()
    _ensure_window_ini_keys()

    floating = _ensure_floating_ui()
    floating.draw(floating_ui_ini_key)
    _mark_ui_seed_window_seen('floating')
    show_main_window = bool(floating.visible)
    if not show_main_window:
        return

    if expand_main_window_on_next_show:
        if not _native_window_seed('main'):
            PyImGui.set_next_window_collapsed(False, PyImGui.ImGuiCond.Always)
        expand_main_window_on_next_show = False

    if not _apply_native_window_seed('main', MAIN_WINDOW_DEFAULT_SIZE):
        PyImGui.set_next_window_size(MAIN_WINDOW_DEFAULT_SIZE, PyImGui.ImGuiCond.FirstUseEver)
    window_expanded, window_open = _begin_persistent_window_with_close(
        main_window_ini_key,
        'Party Formations',
        show_main_window,
        PyImGui.WindowFlags.NoFlag,
    )
    _set_main_window_visible(window_open, persist=False, expand_on_show=False)
    if window_expanded and window_open:
        _draw_formation_editor()
    _end_persistent_window(main_window_ini_key)
    if not window_open:
        return
    _draw_canvas_editor_window()
