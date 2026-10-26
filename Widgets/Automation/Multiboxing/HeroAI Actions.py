from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import PyImGui

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
from Py4GWCoreLib.HeroAI.command_api import HeroAICommandAPI
from Py4GWCoreLib.HeroAI.commands import Command
from Py4GWCoreLib.HeroAI.commands import HeroAICommands
from Py4GWCoreLib.ImGui import ImGui
from Py4GWCoreLib.ImGui_src.IconsFontAwesome5 import IconsFontAwesome5
from Py4GWCoreLib.Map import Map
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.py4gwcorelib_src.Console import ConsoleLog
from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory
from Py4GWCoreLib.py4gwcorelib_src.WidgetManager import get_widget_handler


MODULE_NAME = 'HeroAI Actions'
MODULE_ICON = 'Assets/Textures/Module_Icons/HeroAI.png'

_CONFIG_DOCUMENT = JsonFactory('Widgets/HeroAIActions/settings.json')
_WIDGET_HANDLER = get_widget_handler()
_COMMANDS = HeroAICommands()
_COMMAND_API = HeroAICommandAPI()
_formation_consent_text: str | None = None
_formation_consent_status = ''
_formation_consent_account = ''

DEFAULT_ACTION_ORDER = (
    'pixel_stack',
    'interact_with_target',
    'take_dialog_with_target',
    'unlock_chest',
    'open_consumables',
    'flag_heroes',
    'unflag_heroes',
    'resign',
    'donate_faction',
    'pick_up_loot',
    'combat_prep',
    'disband_party',
    'form_party',
    'travel_alts_to_leader_map',
    'leave_party_and_travel_gh',
)

_DEFAULT_COLUMNS = 5
_DEFAULT_BUTTON_SIZE = 40
_MIN_COLUMNS = 1
_MAX_COLUMNS = 8
_MIN_BUTTON_SIZE = 28
_MAX_BUTTON_SIZE = 72


@dataclass(frozen=True)
class ActionDefinition:
    key: str
    api_method: str
    command: Command
    requires_target: bool = False
    requires_heroai_widget: bool = False
    requires_messaging_widget: bool = True


@dataclass
class WidgetConfig:
    action_order: list[str]
    enabled: dict[str, bool]
    columns: int
    button_size: int
    locked: bool
    show_labels: bool

    @classmethod
    def defaults(cls) -> 'WidgetConfig':
        return cls(
            action_order=list(DEFAULT_ACTION_ORDER),
            enabled={key: True for key in DEFAULT_ACTION_ORDER},
            columns=_DEFAULT_COLUMNS,
            button_size=_DEFAULT_BUTTON_SIZE,
            locked=False,
            show_labels=False,
        )

    @classmethod
    def load(cls, document: JsonFactory) -> 'WidgetConfig':
        defaults = cls.defaults()

        raw_order = document.get_json('action_order', list(DEFAULT_ACTION_ORDER))
        if not isinstance(raw_order, list):
            raw_order = []

        action_keys = set(DEFAULT_ACTION_ORDER)
        action_order = [str(key) for key in raw_order if str(key) in action_keys]
        action_order.extend(key for key in DEFAULT_ACTION_ORDER if key not in action_order)

        raw_enabled = document.get_json('enabled', {})
        if not isinstance(raw_enabled, dict):
            raw_enabled = {}

        enabled = {
            key: raw_enabled[key] if isinstance(raw_enabled.get(key), bool) else defaults.enabled[key]
            for key in DEFAULT_ACTION_ORDER
        }

        return cls(
            action_order=action_order,
            enabled=enabled,
            columns=_bounded_int(
                document.get_json('columns', defaults.columns),
                _MIN_COLUMNS,
                _MAX_COLUMNS,
                defaults.columns,
            ),
            button_size=_bounded_int(
                document.get_json('button_size', defaults.button_size),
                _MIN_BUTTON_SIZE,
                _MAX_BUTTON_SIZE,
                defaults.button_size,
            ),
            locked=_boolean_or_default(document.get_json('locked', defaults.locked), defaults.locked),
            show_labels=_boolean_or_default(
                document.get_json('show_labels', defaults.show_labels),
                defaults.show_labels,
            ),
        )

    def save(self, document: JsonFactory) -> None:
        document.set_json('action_order', list(self.action_order))
        document.set_json('enabled', dict(self.enabled))
        document.set_int('columns', self.columns)
        document.set_int('button_size', self.button_size)
        document.set_bool('locked', self.locked)
        document.set_bool('show_labels', self.show_labels)

    def reset(self) -> None:
        defaults = self.defaults()
        self.action_order = defaults.action_order
        self.enabled = defaults.enabled
        self.columns = defaults.columns
        self.button_size = defaults.button_size
        self.locked = defaults.locked
        self.show_labels = defaults.show_labels


def _bounded_int(value: object, minimum: int, maximum: int, default: int) -> int:
    if isinstance(value, bool):
        return default
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _boolean_or_default(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _command(command_name: str) -> Command:
    command = _COMMANDS.Commands.get(command_name)
    if command is None:
        raise KeyError(f'HeroAI command metadata is missing: {command_name}')
    return command


_ACTIONS = (
    ActionDefinition('pixel_stack', 'pixel_stack', _command('Pixel Stack')),
    ActionDefinition(
        'interact_with_target',
        'interact_with_target',
        _command('Interact With Target'),
        requires_target=True,
    ),
    ActionDefinition(
        'take_dialog_with_target',
        'take_dialog_with_target',
        _command('Dialog With Target'),
        requires_target=True,
    ),
    ActionDefinition(
        'unlock_chest',
        'unlock_chest',
        _command('Unlock Chest'),
        requires_target=True,
    ),
    ActionDefinition(
        'open_consumables',
        'open_consumables',
        _command('Open Consumables'),
        requires_heroai_widget=True,
        requires_messaging_widget=False,
    ),
    ActionDefinition(
        'flag_heroes',
        'flag_heroes',
        _command('Flag Heroes'),
        requires_heroai_widget=True,
    ),
    ActionDefinition(
        'unflag_heroes',
        'unflag_heroes',
        _command('Unflag Heroes'),
        requires_heroai_widget=True,
    ),
    ActionDefinition('resign', 'resign', _command('Resign')),
    ActionDefinition('donate_faction', 'donate_faction', _command('Donate Faction')),
    ActionDefinition('pick_up_loot', 'pick_up_loot', _command('Pick up loot')),
    ActionDefinition(
        'combat_prep',
        'combat_prep',
        _command('Prepare for Combat'),
        requires_heroai_widget=True,
    ),
    ActionDefinition('disband_party', 'disband_party', _command('Disband Party')),
    ActionDefinition('form_party', 'form_party', _command('Form Party')),
    ActionDefinition(
        'travel_alts_to_leader_map',
        'travel_alts_to_leader_map',
        _command("Travel Alt Accounts to Leader's Map"),
    ),
    ActionDefinition(
        'leave_party_and_travel_gh',
        'leave_party_and_travel_gh',
        _command('Leave & Travel to GH'),
    ),
)
_ACTIONS_BY_KEY = {action.key: action for action in _ACTIONS}

_CONFIG = WidgetConfig.load(_CONFIG_DOCUMENT)
_CONFIGURE_WINDOW_OPEN = False
_LAST_REQUESTED_ACTION: Optional[str] = None


def _heroai_widget_available() -> bool:
    try:
        return _WIDGET_HANDLER.is_widget_enabled('HeroAI')
    except Exception:
        # If the widget registry is not ready, do not invent a restriction that
        # would prevent the public command façade from preserving its behavior.
        return True


def _messaging_widget_available() -> bool:
    try:
        return _WIDGET_HANDLER.is_widget_enabled('Messaging')
    except Exception:
        # Preserve the command façade's behavior if widget discovery is still
        # initializing and the registry cannot answer yet.
        return True


def _target_available() -> bool:
    target_id = Player.GetTargetID()
    if target_id <= 0:
        return False

    try:
        return Agent.IsValid(target_id)
    except Exception:
        # A positive target ID is still the strongest reliable signal available
        # if the agent cache is temporarily unavailable.
        return True


def _map_availability(command: Command) -> Optional[str]:
    if not Map.IsMapReady():
        return 'Waiting for the map to finish loading.'

    if Map.IsExplorable():
        current_map_type = 'Explorable'
    elif Map.IsOutpost():
        current_map_type = 'Outpost'
    else:
        return 'Unavailable outside an explorable area or outpost.'

    if current_map_type not in command.map_types:
        if command.map_types == ['Explorable']:
            return 'Available only in an explorable area.'
        if command.map_types == ['Outpost']:
            return 'Available only in an outpost.'
        return f"Available only in: {', '.join(command.map_types)}."

    return None


def _availability(action: ActionDefinition) -> tuple[bool, Optional[str]]:
    try:
        map_reason = _map_availability(action.command)
        if map_reason:
            return False, map_reason

        if action.requires_target and not _target_available():
            return False, 'Select a valid target first.'

        if action.requires_heroai_widget and not _heroai_widget_available():
            return False, 'The HeroAI widget must be running on this account.'

        if action.requires_messaging_widget and not _messaging_widget_available():
            return False, 'Shared account commands are currently unavailable.'

        return True, None
    except Exception:
        # Availability checks must not turn a transient game-state read failure
        # into a new command restriction. The command façade remains authoritative.
        return True, None


def _action_tooltip(action: ActionDefinition, reason: Optional[str]) -> str:
    lines = [action.command.name, action.command.tooltip]

    if action.key == 'flag_heroes':
        lines.append('After pressing, click a location in the game to place the heroes.')
    elif action.key == 'open_consumables':
        lines.append('Opens or closes the consumables setup window on this account.')
    elif action.key in {'form_party', 'travel_alts_to_leader_map'}:
        lines.append("Use this from the account that should act as the party leader.")

    if action.requires_target:
        lines.append('Requires a valid current target.')

    if reason:
        lines.append(f'Unavailable: {reason}')

    return '\n'.join(lines)


def _show_tooltip(text: str) -> None:
    ImGui.show_tooltip(text)


def _request_action(action: ActionDefinition) -> None:
    global _LAST_REQUESTED_ACTION

    try:
        getattr(_COMMAND_API, action.api_method)()
        _LAST_REQUESTED_ACTION = action.command.name
    except Exception as exc:
        ConsoleLog(MODULE_NAME, f"Unable to request '{action.command.name}': {exc}")


def _draw_action_button(action: ActionDefinition) -> None:
    enabled, reason = _availability(action)
    button_id = f'##heroai_action_{action.key}'

    if ImGui.button(
        f'{action.command.icon}{button_id}',
        _CONFIG.button_size,
        _CONFIG.button_size,
        disabled=not enabled,
    ):
        _request_action(action)

    _show_tooltip(_action_tooltip(action, reason))

    if _CONFIG.show_labels:
        PyImGui.text_wrapped(action.command.name)


def _draw_action_grid() -> None:
    visible_actions = [
        _ACTIONS_BY_KEY[key]
        for key in _CONFIG.action_order
        if _CONFIG.enabled.get(key, True) and key in _ACTIONS_BY_KEY
    ]

    if not visible_actions:
        PyImGui.text('No actions are enabled. Open the widget configuration to restore them.')
        return

    table_flags = PyImGui.TableFlags.NoBordersInBody
    if PyImGui.begin_table('##HeroAIActionsGrid', _CONFIG.columns, table_flags):
        column_width = float(_CONFIG.button_size + 12)
        for column in range(_CONFIG.columns):
            PyImGui.table_setup_column(
                f'##HeroAIActionsColumn{column}',
                PyImGui.TableColumnFlags.WidthFixed,
                column_width,
            )

        for index, action in enumerate(visible_actions):
            if index % _CONFIG.columns == 0:
                PyImGui.table_next_row()
            PyImGui.table_next_column()
            _draw_action_button(action)

        PyImGui.end_table()


def _draw_main_window() -> None:
    window_flags = PyImGui.WindowFlags.AlwaysAutoResize
    if _CONFIG.locked:
        window_flags |= PyImGui.WindowFlags.NoMove

    if PyImGui.begin(MODULE_NAME, window_flags):
        if ImGui.button(
            f"{IconsFontAwesome5.ICON_LOCK if _CONFIG.locked else IconsFontAwesome5.ICON_LOCK_OPEN}##HeroAIActionsLock",
            26,
            26,
        ):
            _CONFIG.locked = not _CONFIG.locked
            _CONFIG.save(_CONFIG_DOCUMENT)
        _show_tooltip('Unlock window position' if _CONFIG.locked else 'Lock window position')

        PyImGui.same_line(0, 4)
        if ImGui.button(f'{IconsFontAwesome5.ICON_COG}##HeroAIActionsConfigure', 26, 26):
            _WIDGET_HANDLER.set_widget_configuring(MODULE_NAME, True)
        _show_tooltip('Open HeroAI Actions configuration')

        if _LAST_REQUESTED_ACTION:
            PyImGui.same_line(0, 8)
            PyImGui.text(f'Requested: {_LAST_REQUESTED_ACTION}')

        PyImGui.separator()
        _draw_action_grid()
        try:
            formation = GLOBAL_CACHE.ShMem.GetPartyFormation()
            PyImGui.text_wrapped(f'Form Party: {formation.status}')
            for outcome in formation.outcomes():
                PyImGui.text_wrapped(f'{outcome.character}: {outcome.state} - {outcome.reason}')
        except Exception:
            PyImGui.text('Form Party: service unavailable')

    PyImGui.end()


def _swap_actions(first_index: int, second_index: int) -> None:
    _CONFIG.action_order[first_index], _CONFIG.action_order[second_index] = (
        _CONFIG.action_order[second_index],
        _CONFIG.action_order[first_index],
    )
    _CONFIG.save(_CONFIG_DOCUMENT)


def configure() -> None:
    global _CONFIGURE_WINDOW_OPEN
    global _formation_consent_text, _formation_consent_status, _formation_consent_account

    _CONFIGURE_WINDOW_OPEN = True
    expanded, _CONFIGURE_WINDOW_OPEN = PyImGui.begin(
        f'{MODULE_NAME} Configuration',
        p_open=_CONFIGURE_WINDOW_OPEN,
        flags=PyImGui.WindowFlags.AlwaysAutoResize,
    )

    if expanded:
        from Py4GWCoreLib.GlobalCache.shared_memory_src.PartyFormationRuntime import read_consent, save_consent

        consent = read_consent()
        account_email = str(Player.GetAccountEmail() or '')
        if account_email != _formation_consent_account:
            _formation_consent_account = account_email
            _formation_consent_text = None
            _formation_consent_status = ''
        if _formation_consent_text is None:
            _formation_consent_text = '; '.join(consent.leaders)
        PyImGui.text_wrapped('Party formation permission for this account only. Saved across game restarts.')
        PyImGui.text_wrapped('Named leaders may invite this account only while solo in the same instance. No travel permission.')
        _formation_consent_text = PyImGui.input_text('Leader account emails (separated by ;)##formation', _formation_consent_text)
        permitted = ImGui.checkbox('Allow named leaders to form a party##formation', consent.enabled)
        if permitted != consent.enabled or ImGui.button('Save party formation permission'):
            try:
                save_consent(permitted, _formation_consent_text)
                _formation_consent_status = 'Saved locally. Messaging handles requests; Actions can be disabled here.'
            except Exception as exc:
                _formation_consent_status = str(exc)
        if _formation_consent_status:
            PyImGui.text_wrapped(_formation_consent_status)
        PyImGui.separator()
        PyImGui.text('Choose which actions appear and change their order.')
        PyImGui.text('Buttons remain compact and keep the normal HeroAI behavior.')
        PyImGui.separator()

        new_columns = ImGui.slider_int('Columns', _CONFIG.columns, _MIN_COLUMNS, _MAX_COLUMNS)
        if new_columns != _CONFIG.columns:
            _CONFIG.columns = new_columns
            _CONFIG.save(_CONFIG_DOCUMENT)

        new_button_size = ImGui.slider_int(
            'Button size',
            _CONFIG.button_size,
            _MIN_BUTTON_SIZE,
            _MAX_BUTTON_SIZE,
        )
        if new_button_size != _CONFIG.button_size:
            _CONFIG.button_size = new_button_size
            _CONFIG.save(_CONFIG_DOCUMENT)

        new_locked = ImGui.checkbox('Lock window position', _CONFIG.locked)
        if new_locked != _CONFIG.locked:
            _CONFIG.locked = new_locked
            _CONFIG.save(_CONFIG_DOCUMENT)

        new_show_labels = ImGui.checkbox('Show action labels', _CONFIG.show_labels)
        if new_show_labels != _CONFIG.show_labels:
            _CONFIG.show_labels = new_show_labels
            _CONFIG.save(_CONFIG_DOCUMENT)

        PyImGui.separator()
        PyImGui.text('Actions')

        for index, key in enumerate(list(_CONFIG.action_order)):
            action = _ACTIONS_BY_KEY[key]
            enabled = ImGui.checkbox(
                f'{action.command.name}##HeroAIActionsEnabled_{key}',
                _CONFIG.enabled.get(key, True),
            )
            if enabled != _CONFIG.enabled.get(key, True):
                _CONFIG.enabled[key] = enabled
                _CONFIG.save(_CONFIG_DOCUMENT)

            PyImGui.same_line(0, 8)
            if ImGui.button(
                f'{IconsFontAwesome5.ICON_CHEVRON_UP}##HeroAIActionsUp_{key}',
                26,
                24,
                disabled=index == 0,
            ):
                _swap_actions(index, index - 1)

            PyImGui.same_line(0, 4)
            if ImGui.button(
                f'{IconsFontAwesome5.ICON_CHEVRON_DOWN}##HeroAIActionsDown_{key}',
                26,
                24,
                disabled=index == len(_CONFIG.action_order) - 1,
            ):
                _swap_actions(index, index + 1)

        PyImGui.separator()
        if ImGui.button(f'{IconsFontAwesome5.ICON_UNDO} Reset to defaults'):
            _CONFIG.reset()
            _CONFIG.save(_CONFIG_DOCUMENT)

        PyImGui.same_line(0, 8)
        if ImGui.button('Close'):
            _CONFIGURE_WINDOW_OPEN = False

    PyImGui.end()

    if not _CONFIGURE_WINDOW_OPEN:
        _WIDGET_HANDLER.set_widget_configuring(MODULE_NAME, False)


def tooltip() -> None:
    PyImGui.begin_tooltip()
    PyImGui.text('Compact one-click controls for the existing HeroAI multibox actions.')
    PyImGui.text('The panel preserves HeroAI account selection and multi-account behavior.')
    PyImGui.end_tooltip()


def main() -> None:
    _draw_main_window()


__all__ = ['main', 'configure', 'tooltip']
