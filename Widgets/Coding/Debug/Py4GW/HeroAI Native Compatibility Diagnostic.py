"""Temporary, click-only Option A v3 observation tool; no formation imports.

Uses already-loaded PyMap/PyParty/PyPlayer bindings. PyParty() constructs a
local value snapshot; its constructor already calls GetContext. It does not
start a service. No Python native-context pointer is obtained or dereferenced.

Source limits: party_bindings.cpp leaves PyParty.others empty; party_methods.cpp
excludes others from party_size. PartyContext.player_party and CharContext's
token1/host require unverified ctypes pointer contracts, so remain unread.
Supported binding reads are observations, not proof of deployed build identity,
atomicity, complete solo eligibility, exact instance, or safe invite dispatch.
"""

# pyright: strict

from __future__ import annotations

import sys
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Callable, cast

import PyImGui

MODULE_NAME = 'HeroAI Native Compatibility Diagnostic'
MODULE_ICON = 'Assets/Textures/Module_Icons/HeroAI.png'
OPTIONAL = True

_PREFIX = 'HA_NATIVE_V3'
_MAX_MEMBERS = 64
_MAX_LINES = 12
_MAX_LINE_LENGTH = 240
_status = 'Idle. Capture Snapshot performs one read-only observation.'
_COUNT_FIELDS = ('party_player_count', 'party_hero_count', 'party_henchman_count', 'party_size')


class _Unavailable(Exception):
    pass


class _Invalid(Exception):
    pass


def _loaded(module_name: str, member: str) -> object | None:
    module = sys.modules.get(module_name)
    # Do not trigger lazy imports or inspect partially initialized services.
    if type(module) is not ModuleType:
        return None
    namespace = vars(module)
    spec = namespace.get('__spec__')
    if '__getattr__' in namespace or (isinstance(spec, ModuleSpec) and vars(spec).get('_initializing')):
        return None
    return namespace.get(member)


def _call(module_name: str, member: str) -> object:
    function = _loaded(module_name, member)
    if not callable(function):
        raise _Unavailable()
    return cast(Callable[[], object], function)()


def _integer(value: object, minimum: int = 0, maximum: int = 0xFFFFFFFF) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _Invalid()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise _Invalid()
    return value


def _field(owner: object, name: str) -> object:
    return cast(object, getattr(owner, name))


def _rows(owner: object, name: str) -> list[object]:
    value = _field(owner, name)
    # The binding returns copied std::vectors as lists, not native array views.
    if type(value) is not list:
        raise _Invalid()
    rows = cast(list[object], value)
    if len(rows) > _MAX_MEMBERS:
        raise _Invalid()
    return rows


def _counts() -> tuple[int, ...]:
    values = tuple(_integer(_call('PyParty', 'get_' + name), maximum=_MAX_MEMBERS) for name in _COUNT_FIELDS)
    if values[0] == 0 or values[3] != sum(values[:3]):
        raise _Invalid()
    return values


def _map_sample() -> tuple[int, int, int, int, int, int] | None:
    if not _boolean(_call('PyMap', 'get_is_map_loaded')):
        return None
    map_id = _integer(_call('PyMap', 'get_map_id'), 1)
    region = _integer(_call('PyMap', 'get_region'), -2, 4)
    district = _integer(_call('PyMap', 'get_district'), 1)
    language = _integer(_call('PyMap', 'get_language'), maximum=17)
    kind = _integer(_call('PyMap', 'get_instance_type'), maximum=2)
    age = _integer(_call('PyMap', 'get_instance_time'))
    if region not in (-2, 0, 1, 2, 3, 4) or language not in (0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 17):
        raise _Invalid()
    return map_id, region, district, language, kind, age


def _party_sample() -> tuple[str, bool]:
    before = _counts()  # Bound reported sizes before the native vector-copy constructor.
    if not _boolean(_call('PyParty', 'get_is_party_loaded')):
        return 'PARTY unavailable reason=native_not_loaded', False
    local_login = _integer(_call('PyPlayer', 'get_player_number'), 1)
    party = _call('PyParty', 'PyParty')
    if not _boolean(_field(party, 'is_party_loaded')):
        raise _Invalid()
    _integer(_field(party, 'party_id'), 1)
    counts = tuple(_integer(_field(party, name), maximum=_MAX_MEMBERS) for name in _COUNT_FIELDS)
    players, heroes, henchmen = (_rows(party, name) for name in ('players', 'heroes', 'henchmen'))
    if counts != before or counts[:3] != (len(players), len(heroes), len(henchmen)):
        raise _Invalid()
    logins = tuple(_integer(_field(player, 'login_number'), 1) for player in players)
    if len(set(logins)) != len(logins) or local_login not in logins:
        raise _Invalid()
    if not all(_boolean(_field(player, 'is_connected')) for player in players):
        raise _Invalid()
    leader = _boolean(_field(party, 'is_party_leader'))
    if leader != (logins[0] == local_login):
        raise _Invalid()
    agents = tuple(_integer(_field(member, 'agent_id'), 1) for member in heroes + henchmen)
    if len(set(agents)) != len(agents):
        raise _Invalid()
    if any(_integer(_field(hero, 'owner_player_id'), 1) not in logins for hero in heroes):
        raise _Invalid()
    if (
        _counts() != before
        or not _boolean(_call('PyParty', 'get_is_party_loaded'))
        or _integer(_call('PyPlayer', 'get_player_number'), 1) != local_login
    ):
        raise _Invalid()
    # Identifiers exist only in this local comparison, never in output or retained state.
    return (
        f'PARTY observed players={counts[0]} heroes={counts[1]} henchmen={counts[2]} '
        f'size_excluding_others={counts[3]} roster=consistent local_member=True local_leader={leader}',
        counts != (1, 0, 0, 1),
    )


def _collect() -> list[str]:
    lines = ['BEGIN observation_only build_provenance=unverified snapshot_atomicity=unverified']
    not_solo = False
    try:
        start = _map_sample()
        if start is None:
            lines.append('MAP unavailable reason=native_not_loaded; PARTY not_sampled')
        else:
            map_id, region, district, language, kind, age = start
            lines.append(
                f'MAP observed map={map_id} region={region} district={district} language={language} '
                f'type={kind} age_ms={age}; type_0=outpost type_1=explorable type_2=loading'
            )
            if kind != 0:
                lines.append('PARTY not_sampled reason=not_outpost')
            else:
                try:
                    party_line, not_solo = _party_sample()
                    lines.append(party_line)
                except _Unavailable:
                    lines.append('PARTY unavailable reason=binding_not_loaded_or_missing')
                except Exception:
                    lines.append('PARTY uncertain reason=invalid_inconsistent_or_failed_read')
                end = _map_sample()
                if end is None or end[:5] != start[:5] or end[5] < start[5]:
                    not_solo = False
                    lines.append('READINESS uncertain reason=context_changed_during_capture')
                else:
                    lines.append(
                        'READINESS observed stable_map_bracket; binding_defaults_and_same_count_changes_possible'
                    )
    except _Unavailable:
        not_solo = False
        lines.append('READINESS unavailable reason=map_binding_not_loaded_or_missing')
    except Exception:
        not_solo = False
        lines.append('READINESS uncertain reason=invalid_or_failed_map_read')
    lines.extend(
        (
            'OTHERS unverified; PyParty.others is unpopulated in source; PartyInfo.others_array pointer path NOT read',
            'INSTANCE exact_identity=unverified; age and location are not unique; CharContext.token1/host NOT read',
            (
                'SOLO ineligible observed_non_solo_roster'
                if not_solo
                else 'SOLO unverified; no complete eligibility claim'
            ),
            'GATES open: others_layout_lifetime, exact_instance, reciprocal_membership, terminal_dispatch; guild_halls_unsupported',
            'END no gameplay, formation, shared-memory, settings, or pointer operations requested',
        )
    )
    return lines


def _capture_snapshot() -> None:
    global _status

    try:
        console = _loaded('PySystem', 'Console')
        message_type = _loaded('PySystem', 'MessageType')
        log = vars(console).get('Log') if console is not None else None
        level = vars(message_type).get('Info') if message_type is not None else None
        if not callable(log) or level is None:
            _status = 'Console unavailable. Nothing sampled; no service initialization or retry.'
            return
        lines = _collect()
        if len(lines) > _MAX_LINES:
            lines = lines[: _MAX_LINES - 1] + ['TRUNCATED snapshot_incomplete; SOLO unverified']
        for line in lines:
            cast(Callable[[str, str, object], None], log)(MODULE_NAME, f'{_PREFIX} {line[:_MAX_LINE_LENGTH]}', level)
        _status = f'Captured {len(lines)} console lines. Prefix: {_PREFIX}. Eligibility remains unverified.'
    except Exception:
        # No exception text, repr, traceback, names, addresses or stable identity hashes.
        _status = 'Capture/output failed. No automatic retry or further sampling.'


def main() -> None:
    global _status

    try:
        visible = PyImGui.begin(
            MODULE_NAME, flags=PyImGui.WindowFlags.AlwaysAutoResize | PyImGui.WindowFlags.NoSavedSettings
        )
    except Exception:
        _status = 'Diagnostic window unavailable.'
        return
    try:
        if visible:
            PyImGui.text('One read-only native snapshot. Unsupported pointer contracts stay unverified.')
            if PyImGui.button('Capture Snapshot'):
                _capture_snapshot()
            PyImGui.text_wrapped(_status)
    except Exception:
        _status = 'Diagnostic UI failed. No automatic capture or retry.'
    finally:
        try:
            PyImGui.end()
        except Exception:
            _status = 'Diagnostic window cleanup failed.'
