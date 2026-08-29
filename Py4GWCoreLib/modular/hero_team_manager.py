from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from time import monotonic
from typing import Any
from uuid import uuid4

from Py4GWCoreLib.modular.hero_setup_model import HERO_ID_TO_NAME
from Py4GWCoreLib.modular.hero_setup_model import HERO_OPTIONS
from Py4GWCoreLib.modular.hero_setup_model import safe_account_key as _shared_safe_account_key

HERO_SLOT_COUNT = 7
CONFIG_VERSION = 3
TEMPLATE_LIBRARY_VERSION = 1
GLOBAL_TEMPLATE_MIGRATION_KEY = 'global_templates_v1'
MERCENARY_HERO_IDS = set(range(28, 36))
HERO_IDS = [hero_id for hero_id, _name in HERO_OPTIONS]
HERO_ID_TO_INDEX = {hero_id: idx for idx, hero_id in enumerate(HERO_IDS)}

HERO_BEHAVIOR_DONT_CHANGE = -1
HERO_BEHAVIOR_FIGHT = 0
HERO_BEHAVIOR_GUARD = 1
HERO_BEHAVIOR_AVOID_COMBAT = 2
HERO_BEHAVIOR_CHOICES = [
    (HERO_BEHAVIOR_DONT_CHANGE, "Don't change"),
    (HERO_BEHAVIOR_FIGHT, 'Fight'),
    (HERO_BEHAVIOR_GUARD, 'Guard'),
    (HERO_BEHAVIOR_AVOID_COMBAT, 'Avoid Combat'),
]
HERO_BEHAVIOR_VALUES = [value for value, _label in HERO_BEHAVIOR_CHOICES]
HERO_BEHAVIOR_LABELS = [label for _value, label in HERO_BEHAVIOR_CHOICES]
EMPTY_SKILLBAR_TEMPLATE_NAME = 'Empty skill bar'
MIXED_LOG_SENDER = 'Hero Team Manager'
_MIXED_LOG_LAST: dict[tuple[object, ...], str] = {}

# PartyStateQuery uses the existing SharedMessageStruct payload.  Keep the
# mode names explicit: this is a protocol, not an overloaded inventory query.
PARTY_STATE_QUERY_REQUEST = 'party_state_request'
PARTY_STATE_QUERY_REPLY = 'party_state_reply'
PARTY_STATE_GUARD_RESULT = 'party_state_guard'
PARTY_INVITE_GUARD = 'party_invite_guard'


def _mixed_log(
    event: str,
    message: str,
    *,
    key: tuple[object, ...] = (),
    message_type: str = 'Info',
) -> None:
    """Write one searchable mixed-load event without repeating identical state."""
    log_key = (str(event), *key)
    rendered = str(message)
    if _MIXED_LOG_LAST.get(log_key) == rendered:
        return
    _MIXED_LOG_LAST[log_key] = rendered
    try:
        import PySystem

        console_type = getattr(PySystem.Console.MessageType, message_type, None)
        if console_type is None:
            console_type = PySystem.Console.MessageType.Info
        PySystem.Console.Log(MIXED_LOG_SENDER, f'[{event}] {rendered}', console_type)
    except Exception:
        # Logging must never make a live mixed-team operation fail.
        pass


def _masked_account_identity(account_email: str) -> str:
    """Keep diagnostics useful without placing a full account email in logs."""
    value = str(account_email or '').strip()
    if not value:
        return '<missing>'
    if '@' not in value:
        return f'{value[:1]}***'
    local, domain = value.split('@', 1)
    return f'{local[:1] if local else "?"}***@{domain}'


def hero_id_from_member(hero_member) -> int:
    try:
        hero_id_obj = getattr(hero_member, 'hero_id', None)
        if hero_id_obj is None:
            return 0
        if hasattr(hero_id_obj, 'GetID'):
            return int(hero_id_obj.GetID() or 0)
        return int(hero_id_obj or 0)
    except Exception:
        return 0


def hero_owner_player_id(hero_member) -> int:
    try:
        return int(getattr(hero_member, 'owner_player_id', 0) or 0)
    except Exception:
        return 0


def hero_owner_category(hero_member, local_login_number: int) -> str:
    owner_login = hero_owner_player_id(hero_member)
    local_login = int(local_login_number or 0)
    if local_login <= 0 or owner_login <= 0:
        return 'unknown'
    return 'local' if owner_login == local_login else 'remote'


def current_local_login_number() -> int:
    try:
        from Py4GWCoreLib.Player import Player

        return int(Player.GetLoginNumber() or 0)
    except Exception:
        return 0


def current_party_hero_members(party_api=None) -> list[Any]:
    if party_api is None:
        from Py4GWCoreLib import Party as party_api
    try:
        return list(party_api.GetHeroes() or [])
    except Exception:
        return []


def current_local_hero_members(party_api=None, local_login_number: int | None = None) -> list[Any]:
    local_login = current_local_login_number() if local_login_number is None else int(local_login_number or 0)
    if local_login <= 0:
        return []
    return [hero for hero in current_party_hero_members(party_api) if hero_owner_category(hero, local_login) == 'local']


def current_remote_hero_members(party_api=None, local_login_number: int | None = None) -> list[Any]:
    local_login = current_local_login_number() if local_login_number is None else int(local_login_number or 0)
    return [
        hero for hero in current_party_hero_members(party_api) if hero_owner_category(hero, local_login) == 'remote'
    ]


def current_unknown_owner_hero_members(party_api=None, local_login_number: int | None = None) -> list[Any]:
    local_login = current_local_login_number() if local_login_number is None else int(local_login_number or 0)
    return [
        hero for hero in current_party_hero_members(party_api) if hero_owner_category(hero, local_login) == 'unknown'
    ]


def current_local_hero_ids(party_api=None, local_login_number: int | None = None) -> set[int]:
    return {
        hero_id_from_member(hero)
        for hero in current_local_hero_members(party_api, local_login_number)
        if hero_id_from_member(hero) > 0
    }


def local_hero_party_index_one_based(
    hero_id: int,
    party_api=None,
    local_login_number: int | None = None,
) -> int:
    local_login = current_local_login_number() if local_login_number is None else int(local_login_number or 0)
    if local_login <= 0:
        return 0
    for index, hero in enumerate(current_party_hero_members(party_api), start=1):
        if hero_id_from_member(hero) == int(hero_id) and hero_owner_category(hero, local_login) == 'local':
            return int(index)
    return 0


def current_hero_ids(party_api=None) -> set[int]:
    if party_api is None:
        from Py4GWCoreLib import Party as party_api

    hero_ids: set[int] = set()
    for hero in party_api.GetHeroes() or []:
        hero_id = hero_id_from_member(hero)
        if hero_id > 0:
            hero_ids.add(hero_id)
    return hero_ids


def hero_party_index_one_based(hero_id: int, party_api=None) -> int:
    if party_api is None:
        from Py4GWCoreLib import Party as party_api

    heroes = party_api.GetHeroes() or []
    for idx, hero in enumerate(heroes, start=1):
        if hero_id_from_member(hero) == int(hero_id):
            return int(idx)
    return 0


def hero_slot_capacity(*, map_api=None, party_api=None, default: int = 7) -> int:
    if map_api is None or party_api is None:
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import Party

        map_api = map_api or Map
        party_api = party_api or Party

    try:
        map_size = int(map_api.GetMaxPartySize() or 0)
    except Exception:
        map_size = 0
    if map_size <= 0:
        try:
            map_size = int(party_api.GetPartySize() or 0)
        except Exception:
            map_size = 0
    try:
        player_count = int(party_api.GetPlayerCount() or 1)
    except Exception:
        player_count = 1

    if map_size <= 0:
        return max(0, int(default))
    return max(0, min(int(default), map_size - max(1, player_count)))


@dataclass(slots=True)
class HeroTemplateEntry:
    template_id: str
    name: str
    code: str = ''


@dataclass(slots=True)
class HeroTeamSlot:
    hero_id: int = 0
    template_id: str = ''
    template_code: str = ''
    behavior: int = HERO_BEHAVIOR_DONT_CHANGE


@dataclass(slots=True)
class AltAccountBinding:
    account_email: str = ''
    enabled: bool = True
    expected_character_name: str = ''
    alias: str = ''


@dataclass(slots=True)
class HeroTeamSetup:
    team_id: str
    name: str
    slots: list[HeroTeamSlot] = field(default_factory=list)
    alt_members: list[AltAccountBinding] = field(default_factory=list)


@dataclass(slots=True)
class HeroTeamConfig:
    version: int = CONFIG_VERSION
    active_team_id: str = ''
    teams: list[HeroTeamSetup] = field(default_factory=list)
    templates: list[HeroTemplateEntry] = field(default_factory=list)
    template_preferences: dict[str, int] = field(default_factory=dict)
    hero_names: dict[str, str] = field(default_factory=dict)
    hero_profession_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    account_key: str = ''
    migrations: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResolvedHeroSlot:
    slot_index: int
    hero_id: int
    hero_name: str
    template_code: str = ''
    template_name: str = ''
    template_assigned: bool = False
    template_missing: bool = False
    clear_skillbar: bool = False
    behavior: int = HERO_BEHAVIOR_DONT_CHANGE


@dataclass(slots=True)
class HeroTeamLoadPlan:
    slots: list[ResolvedHeroSlot] = field(default_factory=list)
    skipped_empty: list[int] = field(default_factory=list)
    skipped_duplicates: list[int] = field(default_factory=list)
    truncated_slots: list[int] = field(default_factory=list)


@dataclass(slots=True)
class HeroTeamRowWarning:
    slot_index: int
    code: str
    message: str
    severity: str = 'warning'


@dataclass(slots=True)
class HeroTeamLoadPreflight:
    plan: HeroTeamLoadPlan = field(default_factory=HeroTeamLoadPlan)
    row_warnings: dict[int, list[HeroTeamRowWarning]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blocking_messages: list[str] = field(default_factory=list)
    max_heroes: int = HERO_SLOT_COUNT
    mixed_mode: bool = False
    alt_statuses: list['AltAccountStatus'] = field(default_factory=list)
    capacity: 'MixedPartyCapacity | None' = None

    @property
    def can_load(self) -> bool:
        return not self.blocking_messages


@dataclass(slots=True)
class AltAccountStatus:
    binding_index: int = 0
    account_email: str = ''
    display_name: str = ''
    character_name: str = ''
    profession_label: str = ''
    status: str = 'unresolved'
    status_message: str = ''
    is_active: bool = False
    is_stale: bool = False
    same_map: bool = False
    in_current_party: bool = False
    expected_character_matches: bool = True
    party_id: int = 0
    party_position: int = -1
    remote_party_position: int = -1
    login_number: int = 0
    agent_id: int = 0
    map_id: int = 0
    map_region: int = 0
    map_district: int = 0
    map_language: int = 0
    party_state: str = 'unknown'
    known_party_member_count: int = 0
    party_evidence: str = ''
    is_party_leader: bool = False
    party_state_query_id: str = ''
    party_state_query_received_at: float = 0.0
    guard_result: str = ''


@dataclass(slots=True)
class MixedPartyCapacity:
    max_party_size: int = 0
    current_party_size: int = 0
    local_player_count: int = 0
    configured_alt_present_count: int = 0
    unmanaged_player_count: int = 0
    local_hero_count: int = 0
    remote_hero_count: int = 0
    unknown_hero_count: int = 0
    henchman_count: int = 0
    other_occupant_count: int = 0
    local_heroes_to_remove: int = 0
    local_heroes_to_add: int = 0
    missing_alt_count: int = 0
    target_local_hero_count: int = 0
    forecast_final_slots: int = 0


@dataclass(slots=True)
class MixedPartySnapshot:
    capacity: MixedPartyCapacity = field(default_factory=MixedPartyCapacity)
    players: list[Any] = field(default_factory=list)
    heroes: list[Any] = field(default_factory=list)
    henchmen: list[Any] = field(default_factory=list)
    others: list[Any] = field(default_factory=list)
    party_id: int = 0
    local_login_number: int = 0
    components_reconciled: bool = False
    party_loaded: bool = False


@dataclass(slots=True)
class SkillTemplatePreview:
    template_name: str = ''
    primary_profession_id: int = 0
    secondary_profession_id: int = 0
    profession_label: str = ''
    profession_icon_path: str = ''
    attribute_summary: str = ''
    skill_ids: list[int] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)
    skill_icon_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TemplateProfessionGroup:
    group_key: str
    label: str
    sort_order: int = 999
    primary_profession_id: int = 0
    is_known_profession: bool = False


@dataclass(slots=True)
class CurrentPartyHeroTarget:
    hero_index: int
    hero_id: int
    hero_name: str
    agent_id: int = 0
    primary_profession_id: int = 0
    secondary_profession_id: int = 0
    profession_label: str = ''


@dataclass(slots=True)
class ApplyTemplateToHeroResult:
    success: bool
    message: str
    hero_id: int = 0
    hero_index: int = 0


_CURRENT_HERO_PROFESSION_CACHE: dict[tuple[int, int], tuple[int, int]] = {}
_CURRENT_HERO_IDENTITY_PROFESSION_CACHE: dict[tuple[int, str], tuple[int, int]] = {}
_CURRENT_HERO_PROFESSION_CACHE_ACCOUNT_KEY = ''


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', '_', str(value or '').strip())
    cleaned = cleaned.strip(' .')
    return cleaned or 'default'


def safe_account_key() -> str:
    return _safe_filename(_shared_safe_account_key())


def resolved_account_key(account_key: str | None = None) -> str:
    return _safe_filename(account_key if account_key is not None else safe_account_key())


def _new_id(prefix: str, name: str = '') -> str:
    seed = re.sub(r'[^a-z0-9]+', '_', str(name or prefix).strip().lower()).strip('_')
    return f'{prefix}_{seed or "item"}_{uuid4().hex[:8]}'


def _coerce_hero_id(value: Any) -> int:
    try:
        hero_id = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return hero_id if hero_id in HERO_ID_TO_INDEX else 0


def _coerce_behavior(value: Any) -> int:
    try:
        behavior = int(value)
    except (TypeError, ValueError):
        return HERO_BEHAVIOR_DONT_CHANGE
    return behavior if behavior in HERO_BEHAVIOR_VALUES else HERO_BEHAVIOR_DONT_CHANGE


def _clean_display_name(value: Any) -> str:
    return str(value or '').strip()


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'0', 'false', 'no', 'off', 'disabled'}:
            return False
        if normalized in {'1', 'true', 'yes', 'on', 'enabled'}:
            return True
    return bool(value)


def alt_account_identity_key(value: Any) -> str:
    """Return the validation-only identity key for a configured account."""
    return str(value or '').strip().casefold()


def _alt_binding_from_raw(raw: Any) -> AltAccountBinding:
    if isinstance(raw, AltAccountBinding):
        return AltAccountBinding(
            account_email=str(raw.account_email or '').strip(),
            enabled=_coerce_bool(raw.enabled, True),
            expected_character_name=str(raw.expected_character_name or '').strip(),
            alias=str(raw.alias or '').strip(),
        )
    if not isinstance(raw, dict):
        # Keep malformed rows visible so normalization cannot silently change a
        # saved team definition into a different member list.
        return AltAccountBinding()
    return AltAccountBinding(
        account_email=str(raw.get('account_email', raw.get('email', '')) or '').strip(),
        enabled=_coerce_bool(raw.get('enabled', True), True),
        expected_character_name=str(
            raw.get('expected_character_name', raw.get('expected_character', raw.get('character_name', ''))) or ''
        ).strip(),
        alias=str(raw.get('alias', raw.get('display_name', '')) or '').strip(),
    )


def normalize_alt_bindings(raw_bindings: Any) -> list[AltAccountBinding]:
    source = raw_bindings if isinstance(raw_bindings, list) else []
    return [_alt_binding_from_raw(raw) for raw in source]


def alt_binding_to_dict(binding: AltAccountBinding) -> dict[str, Any]:
    return {
        'account_email': str(binding.account_email or ''),
        'enabled': bool(binding.enabled),
        'expected_character_name': str(binding.expected_character_name or ''),
        'alias': str(binding.alias or ''),
    }


def duplicate_alt_binding_indices(
    team: HeroTeamSetup,
    local_account_email: str = '',
) -> set[int]:
    keys: dict[str, list[int]] = {}
    local_key = alt_account_identity_key(local_account_email)
    for index, binding in enumerate(team.alt_members):
        key = alt_account_identity_key(binding.account_email)
        if not key or key == local_key:
            continue
        keys.setdefault(key, []).append(index)

    duplicate_indices: set[int] = set()
    for indices in keys.values():
        if len(indices) > 1:
            duplicate_indices.update(indices)
    return duplicate_indices


def validate_alt_bindings(
    team: HeroTeamSetup,
    local_account_email: str = '',
) -> list[str]:
    """Validate a team's alt rows without mutating or deduplicating them."""
    local_key = alt_account_identity_key(local_account_email)
    seen: dict[str, int] = {}
    duplicate_indices = duplicate_alt_binding_indices(team, local_account_email)
    messages: list[str] = []

    for index, binding in enumerate(team.alt_members):
        row = index + 1
        email = str(binding.account_email or '').strip()
        key = alt_account_identity_key(email)
        if not key:
            messages.append(f'Alt account row {row} has no account email.')
            continue
        if local_key and key == local_key:
            messages.append(f'Alt account row {row} is the local account and cannot be configured as an alt.')
        previous = seen.get(key)
        if previous is not None:
            messages.append(f'Alt account row {row} duplicates row {previous + 1}; remove or correct one entry.')
        else:
            seen[key] = index
        if index in duplicate_indices and previous is None:
            messages.append(f'Alt account row {row} is duplicated by another configured row; correct the entries.')
    return messages


def team_has_enabled_alt_bindings(team: HeroTeamSetup) -> bool:
    return any(bool(binding.enabled) for binding in team.alt_members)


def calculate_mixed_capacity(
    max_party_size: int,
    current_party_size: int,
    local_heroes_to_remove: int,
    missing_alt_count: int,
    target_local_hero_count: int,
    local_heroes_to_add: int | None = None,
) -> MixedPartyCapacity:
    max_size = max(0, int(max_party_size))
    current_size = max(0, int(current_party_size))
    remove_count = max(0, int(local_heroes_to_remove))
    missing_count = max(0, int(missing_alt_count))
    target_count = max(0, int(target_local_hero_count))
    add_count = target_count if local_heroes_to_add is None else max(0, int(local_heroes_to_add))
    return MixedPartyCapacity(
        max_party_size=max_size,
        current_party_size=current_size,
        local_heroes_to_remove=remove_count,
        local_heroes_to_add=add_count,
        missing_alt_count=missing_count,
        target_local_hero_count=target_count,
        forecast_final_slots=current_size - remove_count + missing_count + add_count,
    )


def empty_slots(count: int = HERO_SLOT_COUNT) -> list[HeroTeamSlot]:
    return [HeroTeamSlot() for _ in range(max(0, int(count)))]


def new_team(name: str = 'New Hero Team') -> HeroTeamSetup:
    return HeroTeamSetup(team_id=_new_id('team', name), name=str(name or 'New Hero Team'), slots=empty_slots())


def new_template(name: str = 'New Template', code: str = '') -> HeroTemplateEntry:
    return HeroTemplateEntry(
        template_id=_new_id('template', name),
        name=str(name or 'New Template'),
        code=str(code or ''),
    )


def default_config(account_key: str | None = None) -> HeroTeamConfig:
    team = new_team()
    resolved_key = resolved_account_key(account_key) if account_key is not None else ''
    return HeroTeamConfig(active_team_id=team.team_id, teams=[team], templates=[], account_key=resolved_key)


def template_to_dict(template: HeroTemplateEntry) -> dict[str, Any]:
    return {
        'id': str(template.template_id),
        'name': str(template.name),
        'code': str(template.code),
    }


def slot_to_dict(slot: HeroTeamSlot) -> dict[str, Any]:
    return {
        'hero_id': int(slot.hero_id),
        'template_id': str(slot.template_id or ''),
        'template_code': str(slot.template_code or ''),
        'behavior': _coerce_behavior(slot.behavior),
    }


def team_to_dict(team: HeroTeamSetup) -> dict[str, Any]:
    return {
        'id': str(team.team_id),
        'name': str(team.name),
        'slots': [slot_to_dict(slot) for slot in normalize_slots(team.slots)],
        'alt_members': [alt_binding_to_dict(binding) for binding in team.alt_members],
    }


def config_to_dict(config: HeroTeamConfig) -> dict[str, Any]:
    normalized = normalize_config(config_to_raw(config))
    return {
        'version': int(normalized.version),
        'active_team_id': str(normalized.active_team_id),
        'teams': [team_to_dict(team) for team in normalized.teams],
        'templates': [template_to_dict(template) for template in normalized.templates],
        'template_preferences': dict(normalized.template_preferences),
        'hero_names': dict(normalized.hero_names),
        'hero_profession_cache': dict(normalized.hero_profession_cache),
        'migrations': deepcopy(normalized.migrations),
    }


def account_config_to_dict(config: HeroTeamConfig) -> dict[str, Any]:
    normalized = normalize_config(config_to_raw(config), global_templates=[])
    return {
        'version': int(normalized.version),
        'active_team_id': str(normalized.active_team_id),
        'teams': [team_to_dict(team) for team in normalized.teams],
        'template_preferences': dict(normalized.template_preferences),
        'hero_names': dict(normalized.hero_names),
        'hero_profession_cache': dict(normalized.hero_profession_cache),
        'migrations': deepcopy(normalized.migrations),
    }


def template_library_to_dict(templates: list[HeroTemplateEntry]) -> dict[str, Any]:
    normalized = normalize_template_entries(templates)
    return {
        'version': TEMPLATE_LIBRARY_VERSION,
        'templates': {
            str(template.template_id): {
                'name': str(template.name),
                'code': str(template.code),
            }
            for template in normalized
        },
    }


def config_to_raw(config: HeroTeamConfig | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(config, HeroTeamConfig):
        return {
            'version': config.version,
            'active_team_id': config.active_team_id,
            'teams': [team_to_dict(team) for team in config.teams],
            'templates': [template_to_dict(template) for template in config.templates],
            'template_preferences': dict(config.template_preferences),
            'hero_names': dict(config.hero_names),
            'hero_profession_cache': dict(config.hero_profession_cache),
            'account_key': str(config.account_key or ''),
            'migrations': deepcopy(config.migrations),
        }
    return config if isinstance(config, dict) else {}


def _template_from_raw(raw: Any, used_ids: set[str]) -> HeroTemplateEntry | None:
    if isinstance(raw, HeroTemplateEntry):
        name = str(raw.name or '').strip() or 'New Template'
        template_id = str(raw.template_id or '').strip()
        if not template_id or template_id in used_ids:
            template_id = _new_id('template', name)
        used_ids.add(template_id)
        return HeroTemplateEntry(
            template_id=template_id,
            name=name,
            code=str(raw.code or ''),
        )
    if not isinstance(raw, dict):
        return None
    name = str(raw.get('name', '') or '').strip() or 'New Template'
    template_id = str(raw.get('id', raw.get('template_id', '')) or '').strip()
    if not template_id or template_id in used_ids:
        template_id = _new_id('template', name)
    used_ids.add(template_id)
    return HeroTemplateEntry(
        template_id=template_id,
        name=name,
        code=str(raw.get('code', raw.get('template', '')) or ''),
    )


def _slot_from_raw(raw: Any) -> HeroTeamSlot:
    if isinstance(raw, HeroTeamSlot):
        return HeroTeamSlot(
            hero_id=_coerce_hero_id(raw.hero_id),
            template_id=str(raw.template_id or ''),
            template_code=str(raw.template_code or ''),
            behavior=_coerce_behavior(getattr(raw, 'behavior', HERO_BEHAVIOR_DONT_CHANGE)),
        )
    if not isinstance(raw, dict):
        return HeroTeamSlot()
    return HeroTeamSlot(
        hero_id=_coerce_hero_id(raw.get('hero_id', 0)),
        template_id=str(raw.get('template_id', '') or ''),
        template_code=str(raw.get('template_code', raw.get('template', '')) or ''),
        behavior=_coerce_behavior(raw.get('behavior', raw.get('hero_behavior', HERO_BEHAVIOR_DONT_CHANGE))),
    )


def _is_valid_primary_profession_id(profession_id: int) -> bool:
    try:
        profession_id = int(profession_id or 0)
    except Exception:
        return False
    return 1 <= profession_id <= 10


def _is_valid_secondary_profession_id(profession_id: int) -> bool:
    try:
        profession_id = int(profession_id or 0)
    except Exception:
        return False
    return profession_id == 0 or _is_valid_primary_profession_id(profession_id)


def _hero_profession_cache_storage_key(hero_id: int, identity_name: str) -> str:
    identity_key = _hero_profession_identity_key(hero_id, identity_name)
    if identity_key is None:
        return ''
    return f'{identity_key[0]}:{identity_key[1]}'


def _split_hero_profession_cache_storage_key(value: Any) -> tuple[int, str]:
    hero_id_text, separator, identity_name = str(value or '').partition(':')
    if not separator:
        return 0, ''
    return _coerce_hero_id(hero_id_text), _normalize_hero_identity_name(identity_name)


def _normalize_hero_profession_cache(raw_cache: Any) -> dict[str, dict[str, Any]]:
    source = raw_cache if isinstance(raw_cache, dict) else {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_entry in source.items():
        if not isinstance(raw_entry, dict):
            continue

        key_hero_id, key_identity_name = _split_hero_profession_cache_storage_key(raw_key)
        hero_id = _coerce_hero_id(raw_entry.get('hero_id', 0)) or key_hero_id
        identity_name = _clean_display_name(raw_entry.get('identity_name', raw_entry.get('display_name', '')))
        if not identity_name:
            identity_name = key_identity_name

        primary_id = _profession_id(
            raw_entry.get('primary_profession_id', raw_entry.get('primary_id', raw_entry.get('primary', 0)))
        )
        secondary_id = _profession_id(
            raw_entry.get('secondary_profession_id', raw_entry.get('secondary_id', raw_entry.get('secondary', 0)))
        )
        if not _is_valid_primary_profession_id(primary_id):
            continue
        if not _is_valid_secondary_profession_id(secondary_id):
            secondary_id = 0

        storage_key = _hero_profession_cache_storage_key(hero_id, identity_name)
        if not storage_key:
            continue
        normalized[storage_key] = {
            'hero_id': int(hero_id),
            'identity_name': str(identity_name),
            'primary_profession_id': int(primary_id),
            'secondary_profession_id': int(secondary_id),
        }
    return normalized


def normalize_slots(raw_slots: Any, count: int = HERO_SLOT_COUNT) -> list[HeroTeamSlot]:
    source = raw_slots if isinstance(raw_slots, list) else []
    slots = [_slot_from_raw(source[index]) if index < len(source) else HeroTeamSlot() for index in range(int(count))]
    return slots[: int(count)]


def ensure_team_slots(team: HeroTeamSetup, count: int = HERO_SLOT_COUNT) -> list[HeroTeamSlot]:
    while len(team.slots) < int(count):
        team.slots.append(HeroTeamSlot())
    return team.slots[: int(count)]


def _team_from_raw(raw: Any, used_ids: set[str]) -> HeroTeamSetup | None:
    if isinstance(raw, HeroTeamSetup):
        name = str(raw.name or '').strip() or 'New Hero Team'
        team_id = str(raw.team_id or '').strip()
        if not team_id or team_id in used_ids:
            team_id = _new_id('team', name)
        used_ids.add(team_id)
        return HeroTeamSetup(
            team_id=team_id,
            name=name,
            slots=normalize_slots(raw.slots),
            alt_members=normalize_alt_bindings(raw.alt_members),
        )
    if not isinstance(raw, dict):
        return None
    name = str(raw.get('name', '') or '').strip() or 'New Hero Team'
    team_id = str(raw.get('id', raw.get('team_id', '')) or '').strip()
    if not team_id or team_id in used_ids:
        team_id = _new_id('team', name)
    used_ids.add(team_id)
    return HeroTeamSetup(
        team_id=team_id,
        name=name,
        slots=normalize_slots(raw.get('slots', [])),
        alt_members=normalize_alt_bindings(raw.get('alt_members', raw.get('alt_accounts', raw.get('alts', [])))),
    )


def _template_source_entries(raw: Any) -> list[Any]:
    source = raw
    if isinstance(source, dict) and 'templates' in source:
        source = source.get('templates', [])
    if isinstance(source, dict):
        return [
            {'id': key, **(value if isinstance(value, dict) else {'code': value})}
            for key, value in source.items()
        ]
    return list(source) if isinstance(source, list) else []


def normalize_template_entries(raw: Any) -> list[HeroTemplateEntry]:
    used_ids: set[str] = set()
    templates = [
        template
        for template in (_template_from_raw(entry, used_ids) for entry in _template_source_entries(raw))
        if template is not None
    ]
    return templates


def _normalize_template_preferences(raw_preferences: Any) -> dict[str, int]:
    source = raw_preferences if isinstance(raw_preferences, dict) else {}
    normalized: dict[str, int] = {}
    for raw_id, raw_value in source.items():
        template_id = str(raw_id or '').strip()
        if not template_id:
            continue
        value = raw_value.get('preferred_hero_id', 0) if isinstance(raw_value, dict) else raw_value
        normalized[template_id] = _coerce_hero_id(value)
    return normalized


def _legacy_template_preferences(raw_templates: Any) -> dict[str, int]:
    preferences: dict[str, int] = {}
    for entry in _template_source_entries(raw_templates):
        if isinstance(entry, HeroTemplateEntry):
            template_id = str(entry.template_id or '').strip()
            hero_id = 0
        elif isinstance(entry, dict):
            template_id = str(entry.get('id', entry.get('template_id', '')) or '').strip()
            hero_id = _coerce_hero_id(entry.get('hero_id', 0))
        else:
            continue
        if template_id and hero_id > 0 and template_id not in preferences:
            preferences[template_id] = hero_id
    return preferences


def normalize_config(
    raw: dict[str, Any] | HeroTeamConfig | None,
    *,
    global_templates: Any = None,
) -> HeroTeamConfig:
    source = config_to_raw(raw)
    legacy_template_source = source.get('templates', [])
    template_source = legacy_template_source if global_templates is None else global_templates
    team_source = source.get('teams', [])
    hero_names_source = source.get('hero_names', {})
    hero_profession_cache_source = source.get('hero_profession_cache', {})

    if isinstance(team_source, dict):
        team_source = [
            {'id': key, **(value if isinstance(value, dict) else {'slots': value})}
            for key, value in team_source.items()
        ]

    templates = normalize_template_entries(template_source)
    template_preferences = _normalize_template_preferences(source.get('template_preferences', {}))
    for template_id, hero_id in _legacy_template_preferences(legacy_template_source).items():
        template_preferences.setdefault(template_id, hero_id)

    used_team_ids: set[str] = set()
    teams = [team for team in (_team_from_raw(entry, used_team_ids) for entry in team_source) if team is not None]
    if not teams:
        teams = [new_team()]

    active_team_id = str(source.get('active_team_id', '') or '').strip()
    if active_team_id not in {team.team_id for team in teams}:
        active_team_id = teams[0].team_id

    hero_names: dict[str, str] = {}
    if isinstance(hero_names_source, dict):
        for key, value in hero_names_source.items():
            hero_id = _coerce_hero_id(key)
            name = _clean_display_name(value)
            if hero_id > 0 and name:
                hero_names[str(hero_id)] = name

    migrations = source.get('migrations', {})
    if not isinstance(migrations, dict):
        migrations = {}

    return HeroTeamConfig(
        version=CONFIG_VERSION,
        active_team_id=active_team_id,
        teams=teams,
        templates=templates,
        template_preferences=template_preferences,
        hero_names=hero_names,
        hero_profession_cache=_normalize_hero_profession_cache(hero_profession_cache_source),
        account_key=str(source.get('account_key', '') or '').strip(),
        migrations=deepcopy(migrations),
    )


CONFIG_DOCUMENT_NAME = 'Widgets/Hero Team Manager/HeroTeamManager.json'
TEMPLATE_LIBRARY_DOCUMENT_NAME = 'Widgets/Hero Team Manager/Templates.json'


def _config_document():
    from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

    return JsonFactory(CONFIG_DOCUMENT_NAME, 'account')


def _template_library_document():
    from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

    return JsonFactory(TEMPLATE_LIBRARY_DOCUMENT_NAME, 'global')


def _template_signature(template: HeroTemplateEntry | dict[str, Any]) -> tuple[str, str]:
    if isinstance(template, HeroTemplateEntry):
        return str(template.name or '').strip(), str(template.code or '').strip()
    return str(template.get('name', '') or '').strip(), str(template.get('code', '') or '').strip()


def _template_id_is_path_safe(template_id: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9_-]+', str(template_id or '').strip()))


def _migration_template_id(
    account_key: str,
    source_id: str,
    template: HeroTemplateEntry,
    occurrence: int,
    used_ids: set[str],
) -> str:
    seed = '\x00'.join(
        [
            str(account_key or ''),
            str(source_id or ''),
            str(template.name or '').strip(),
            str(template.code or '').strip(),
            str(int(occurrence)),
        ]
    )
    digest = hashlib.sha256(seed.encode('utf-8')).hexdigest()
    for length in (16, 24, 32, 40, 64):
        candidate = f'template_migrated_{digest[:length]}'
        if candidate not in used_ids:
            return candidate
    raise ValueError('Could not allocate a deterministic migrated template ID.')


def _legacy_template_records(raw_templates: Any) -> list[tuple[str, HeroTemplateEntry, int]]:
    records: list[tuple[str, HeroTemplateEntry, int]] = []
    for index, entry in enumerate(_template_source_entries(raw_templates)):
        if isinstance(entry, HeroTemplateEntry):
            template_id = str(entry.template_id or '').strip()
            template = HeroTemplateEntry(
                template_id=template_id,
                name=str(entry.name or '').strip() or 'New Template',
                code=str(entry.code or ''),
            )
            hero_id = 0
        elif isinstance(entry, dict):
            template_id = str(entry.get('id', entry.get('template_id', '')) or '').strip()
            template = HeroTemplateEntry(
                template_id=template_id,
                name=str(entry.get('name', '') or '').strip() or 'New Template',
                code=str(entry.get('code', entry.get('template', '')) or ''),
            )
            hero_id = _coerce_hero_id(entry.get('hero_id', 0))
        else:
            continue
        records.append((template_id, template, hero_id))
    return records


def _migration_completed(raw: dict[str, Any]) -> bool:
    migrations = raw.get('migrations', {})
    marker = migrations.get(GLOBAL_TEMPLATE_MIGRATION_KEY) if isinstance(migrations, dict) else None
    return bool(isinstance(marker, dict) and marker.get('completed'))


def _migrate_account_templates(raw: dict[str, Any], account_key: str) -> dict[str, Any]:
    if _migration_completed(raw):
        return raw

    legacy_records = _legacy_template_records(raw.get('templates', []))
    template_doc = _template_library_document()
    try:
        global_raw = template_doc.get_json('', {})
    except Exception:
        global_raw = {}
    global_templates = {template.template_id: template for template in normalize_template_entries(global_raw)}
    original_global_ids = set(global_templates)
    semantic_ids: dict[tuple[str, str], list[str]] = {}
    for template_id, template in global_templates.items():
        semantic_ids.setdefault(_template_signature(template), []).append(template_id)
    for ids in semantic_ids.values():
        ids.sort()

    id_remap: dict[str, str] = {}
    preference_remap: dict[str, int] = {}
    account_semantic_targets: dict[tuple[tuple[str, str], int], str] = {}
    used_ids = set(global_templates)
    source_occurrences: dict[str, int] = {}

    sorted_records = sorted(legacy_records, key=lambda item: (item[0], item[1].name, item[2]))
    for source_id, template, preferred_hero_id in sorted_records:
        occurrence = source_occurrences.get(source_id, 0)
        source_occurrences[source_id] = occurrence + 1
        signature = _template_signature(template)
        preference_key = (signature, preferred_hero_id)
        target_id = account_semantic_targets.get(preference_key)

        if (
            target_id is None
            and source_id
            and source_id in global_templates
            and source_id not in account_semantic_targets.values()
        ):
            existing = global_templates[source_id]
            if _template_signature(existing) == signature:
                target_id = source_id

        if target_id is None:
            semantic_candidates = semantic_ids.get(signature, [])
            for candidate in semantic_candidates:
                if candidate not in account_semantic_targets.values():
                    target_id = candidate
                    break

        if target_id is None and source_id and _template_id_is_path_safe(source_id) and source_id not in used_ids:
            target_id = source_id

        if target_id is None:
            target_id = _migration_template_id(account_key, source_id, template, occurrence, used_ids)

        if target_id in global_templates and _template_signature(global_templates[target_id]) != signature:
            target_id = _migration_template_id(account_key, source_id, template, occurrence, used_ids)

        used_ids.add(target_id)
        account_semantic_targets.setdefault(preference_key, target_id)
        global_templates[target_id] = HeroTemplateEntry(
            template_id=target_id,
            name=str(template.name),
            code=str(template.code),
        )
        semantic_ids.setdefault(signature, [])
        if target_id not in semantic_ids[signature]:
            semantic_ids[signature].append(target_id)
            semantic_ids[signature].sort()
        if source_id and source_id not in id_remap:
            id_remap[source_id] = target_id
        if source_id and preferred_hero_id > 0:
            preference_remap[target_id] = preferred_hero_id

    try:
        template_doc.set_int('version', TEMPLATE_LIBRARY_VERSION)
        for template_id, template in global_templates.items():
            if template_id not in original_global_ids:
                template_doc.set_json(
                    f'templates/{template_id}',
                    {'name': str(template.name), 'code': str(template.code)},
                )
        if not bool(template_doc.save()):
            try:
                template_doc.reload()
            except Exception:
                pass
            return raw
    except Exception:
        try:
            template_doc.reload()
        except Exception:
            pass
        return raw

    migrated = deepcopy(raw)
    migrated['version'] = CONFIG_VERSION
    migrated.pop('templates', None)
    preferences = _normalize_template_preferences(migrated.get('template_preferences', {}))
    preferences.update(preference_remap)
    migrated['template_preferences'] = preferences
    for team in migrated.get('teams', []) if isinstance(migrated.get('teams', []), list) else []:
        if not isinstance(team, dict):
            continue
        for slot in team.get('slots', []) if isinstance(team.get('slots', []), list) else []:
            if isinstance(slot, dict):
                template_id = str(slot.get('template_id', '') or '')
                if template_id in id_remap:
                    slot['template_id'] = id_remap[template_id]
    migrations = migrated.get('migrations', {})
    if not isinstance(migrations, dict):
        migrations = {}
    migrations[GLOBAL_TEMPLATE_MIGRATION_KEY] = {
        'completed': True,
        'version': TEMPLATE_LIBRARY_VERSION,
        'id_remap': dict(id_remap),
    }
    migrated['migrations'] = migrations
    try:
        account_doc = _config_document()
        account_doc.set_json('', migrated)
        if not bool(account_doc.save()):
            return migrated
    except Exception:
        return migrated
    return migrated


def load_global_templates() -> list[HeroTemplateEntry]:
    try:
        raw = _template_library_document().get_json('', {})
    except Exception:
        raw = {}
    return normalize_template_entries(raw)


def reload_global_templates() -> list[HeroTemplateEntry]:
    try:
        _template_library_document().reload()
    except Exception:
        pass
    return load_global_templates()


def _template_records(templates: list[HeroTemplateEntry]) -> dict[str, dict[str, str]]:
    return {
        str(template.template_id): {
            'name': str(template.name),
            'code': str(template.code),
        }
        for template in normalize_template_entries(templates)
    }


def merge_template_libraries(
    base_templates: list[HeroTemplateEntry],
    local_templates: list[HeroTemplateEntry],
    remote_templates: list[HeroTemplateEntry],
) -> tuple[list[HeroTemplateEntry], list[str]]:
    base = _template_records(base_templates)
    local = _template_records(local_templates)
    remote = _template_records(remote_templates)
    merged: dict[str, dict[str, str]] = {}
    conflicts: list[str] = []
    for template_id in sorted(set(base) | set(local) | set(remote)):
        base_value = base.get(template_id)
        local_value = local.get(template_id)
        remote_value = remote.get(template_id)
        local_changed = local_value != base_value
        remote_changed = remote_value != base_value
        if local_changed and remote_changed and local_value != remote_value:
            conflicts.append(template_id)
            continue
        value = local_value if local_changed else remote_value if remote_changed else base_value
        if value is not None:
            merged[template_id] = value
    return (
        [
            HeroTemplateEntry(template_id=template_id, name=value['name'], code=value['code'])
            for template_id, value in sorted(merged.items())
        ],
        conflicts,
    )


def load_config(account_key: str | None = None) -> HeroTeamConfig:
    key = resolved_account_key(account_key)
    try:
        raw = _config_document().get_json('', {})
    except Exception:
        raw = {}
    if not isinstance(raw, dict) or not raw:
        config = default_config(account_key=key)
        config.templates = load_global_templates()
        return config

    if key != 'default' and not _migration_completed(raw):
        migrated = _migrate_account_templates(raw, key)
        if migrated is not raw:
            raw = migrated
        else:
            try:
                raw = _config_document().get_json('', raw)
            except Exception:
                pass

    global_templates = load_global_templates()
    if raw.get('templates') and not _migration_completed(raw):
        fallback_templates = normalize_template_entries(raw.get('templates', []))
        seen_ids = {template.template_id for template in global_templates}
        global_templates.extend(template for template in fallback_templates if template.template_id not in seen_ids)
    config = normalize_config(raw, global_templates=global_templates)
    config.account_key = key
    return config


def save_account_config(config: HeroTeamConfig, account_key: str | None = None) -> None:
    key = resolved_account_key(account_key if account_key is not None else config.account_key or None)
    config.account_key = key
    document = _config_document()
    document.set_json('', account_config_to_dict(config))
    if not bool(document.save()):
        raise OSError('Hero Team Manager account document could not be saved.')


def save_global_templates(
    templates: list[HeroTemplateEntry],
    *,
    deleted_template_ids: set[str] | list[str] | tuple[str, ...] = (),
) -> None:
    document = _template_library_document()
    document.set_int('version', TEMPLATE_LIBRARY_VERSION)
    for template in normalize_template_entries(templates):
        if not _template_id_is_path_safe(template.template_id):
            raise ValueError(f'Unsafe template ID: {template.template_id!r}')
        document.set_json(
            f'templates/{template.template_id}',
            {'name': str(template.name), 'code': str(template.code)},
        )
    for template_id in deleted_template_ids:
        if str(template_id or '').strip():
            document.delete(f'templates/{str(template_id).strip()}')
    if not bool(document.save()):
        raise OSError('Hero Team Manager global template library could not be saved.')


def save_template_name(template_id: str, name: str) -> None:
    if not _template_id_is_path_safe(template_id):
        raise ValueError(f'Unsafe template ID: {template_id!r}')
    document = _template_library_document()
    document.set_str(f'templates/{str(template_id).strip()}/name', str(name or '').strip())
    if not bool(document.save()):
        raise OSError('Hero Team Manager global template name could not be saved.')


def save_config(
    config: HeroTeamConfig,
    account_key: str | None = None,
    *,
    deleted_template_ids: set[str] | list[str] | tuple[str, ...] = (),
) -> None:
    save_account_config(config, account_key)
    save_global_templates(config.templates, deleted_template_ids=deleted_template_ids)


def is_pristine_default_config(config: HeroTeamConfig) -> bool:
    if config.templates or config.template_preferences or config.hero_names or len(config.teams) != 1:
        return False
    team = config.teams[0]
    if team.alt_members:
        return False
    if str(team.name or '') != 'New Hero Team':
        return False
    return all(
        slot.hero_id == 0
        and not slot.template_id
        and not slot.template_code
        and _coerce_behavior(slot.behavior) == HERO_BEHAVIOR_DONT_CHANGE
        for slot in normalize_slots(team.slots)
    )


def get_team(config: HeroTeamConfig, team_id: str | None = None) -> HeroTeamSetup | None:
    wanted = str(team_id or config.active_team_id or '').strip()
    for team in config.teams:
        if team.team_id == wanted:
            return team
    return config.teams[0] if config.teams else None


def get_template(config: HeroTeamConfig, template_id: str) -> HeroTemplateEntry | None:
    wanted = str(template_id or '').strip()
    if not wanted:
        return None
    for template in config.templates:
        if template.template_id == wanted:
            return template
    return None


def template_preferred_hero_id(config: HeroTeamConfig | None, template_id: str) -> int:
    if config is None:
        return 0
    wanted = str(template_id or '').strip()
    if not wanted:
        return 0
    return _coerce_hero_id(config.template_preferences.get(wanted, 0))


def set_template_preferred_hero_id(config: HeroTeamConfig, template_id: str, hero_id: int) -> int:
    wanted = str(template_id or '').strip()
    if not wanted:
        return 0
    preferred = _coerce_hero_id(hero_id)
    if preferred > 0:
        config.template_preferences[wanted] = preferred
    else:
        config.template_preferences.pop(wanted, None)
    return preferred


def hero_default_name(hero_id: int) -> str:
    hero_id = _coerce_hero_id(hero_id)
    if hero_id <= 0:
        return 'Empty'
    return HERO_ID_TO_NAME.get(hero_id, f'Hero {hero_id}')


def hero_alias(config: HeroTeamConfig | None, hero_id: int) -> str:
    hero_id = _coerce_hero_id(hero_id)
    if config is None or hero_id <= 0:
        return ''
    return _clean_display_name(config.hero_names.get(str(hero_id), ''))


def set_hero_alias(config: HeroTeamConfig, hero_id: int, alias: str) -> str:
    hero_id = _coerce_hero_id(hero_id)
    if hero_id <= 0:
        return ''
    cleaned = _clean_display_name(alias)[:128]
    if cleaned and cleaned != hero_default_name(hero_id):
        config.hero_names[str(hero_id)] = cleaned
        return cleaned
    config.hero_names.pop(str(hero_id), None)
    return ''


def clear_hero_alias(config: HeroTeamConfig, hero_id: int) -> None:
    hero_id = _coerce_hero_id(hero_id)
    if hero_id > 0:
        config.hero_names.pop(str(hero_id), None)


def hero_display_name(config: HeroTeamConfig | None, hero_id: int) -> str:
    hero_id = _coerce_hero_id(hero_id)
    if hero_id <= 0:
        return 'Empty'
    if config is not None:
        custom_name = hero_alias(config, hero_id)
        if custom_name:
            return custom_name
    return hero_default_name(hero_id)


def _hero_display_name_from_aliases(hero_names: dict[str, str] | None, hero_id: int) -> str:
    hero_id = _coerce_hero_id(hero_id)
    if hero_id <= 0:
        return 'Empty'
    if isinstance(hero_names, dict):
        custom_name = _clean_display_name(hero_names.get(str(hero_id), ''))
        if custom_name:
            return custom_name
    return hero_default_name(hero_id)


def hero_labels(config: HeroTeamConfig | None = None) -> list[str]:
    return [f'{hero_display_name(config, hero_id)} ({hero_id})' for hero_id in HERO_IDS]


def _human_enum_name(name: str) -> str:
    cleaned = str(name or '').replace('_', ' ').strip()
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', cleaned).strip()


def _profession_id_from_text(value: Any) -> int:
    normalized = re.sub(r'[^a-z0-9]+', '', str(value or '').strip().lower())
    if not normalized:
        return 0
    names = {
        'warrior': 1,
        'w': 1,
        'ranger': 2,
        'r': 2,
        'monk': 3,
        'mo': 3,
        'necromancer': 4,
        'n': 4,
        'mesmer': 5,
        'me': 5,
        'elementalist': 6,
        'e': 6,
        'assassin': 7,
        'a': 7,
        'ritualist': 8,
        'rt': 8,
        'paragon': 9,
        'p': 9,
        'dervish': 10,
        'd': 10,
    }
    return int(names.get(normalized, 0))


def _profession_id(value: Any) -> int:
    def _method_int(method_name: str) -> int:
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _profession_id(method())
            except Exception:
                return 0
        return 0

    def _method_text(method_name: str) -> str:
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return str(method() or '').strip()
            except Exception:
                return ''
        return ''

    if value is None:
        return 0
    if isinstance(value, int):
        return int(value)

    try:
        for method_name in ('ToInt', 'Get', 'to_int', 'get'):
            profession_id = _method_int(method_name)
            if profession_id > 0:
                return profession_id
        direct_id = int(value or 0)
        if direct_id > 0:
            return direct_id
    except Exception:
        pass

    for attr_name in ('value', 'id', 'profession', 'primary'):
        try:
            attr_value = getattr(value, attr_name)
        except Exception:
            continue
        if callable(attr_value) or attr_value is value:
            continue
        profession_id = _profession_id(attr_value)
        if profession_id > 0:
            return profession_id

    for text in (_method_text('GetName'), _method_text('GetShortName'), str(value or '').strip()):
        profession_id = _profession_id_from_text(text)
        if profession_id > 0:
            return profession_id
    return 0


def _profession_short_label(primary_id: int, secondary_id: int = 0) -> str:
    try:
        from Py4GWCoreLib.enums_src.GameData_enums import ProfessionShort
        from Py4GWCoreLib.enums_src.GameData_enums import ProfessionShort_Names

        primary = ProfessionShort_Names.get(ProfessionShort(int(primary_id or 0)), '')
        secondary = ProfessionShort_Names.get(ProfessionShort(int(secondary_id or 0)), '')
        return '/'.join(label for label in [primary, secondary] if label and label != 'None')
    except Exception:
        return ''


def _profession_name(profession_id: int) -> str:
    try:
        from Py4GWCoreLib.enums_src.GameData_enums import Profession
        from Py4GWCoreLib.enums_src.GameData_enums import Profession_Names

        return str(Profession_Names.get(Profession(int(profession_id or 0)), '') or '').strip()
    except Exception:
        return ''


def _agent_profession_ids(agent_id: int) -> tuple[int, int]:
    agent_id = int(agent_id or 0)
    if agent_id <= 0:
        return 0, 0
    try:
        from Py4GWCoreLib.Agent import Agent

        primary_id, secondary_id = Agent.GetProfessionIDs(agent_id)
        primary_id = _profession_id(primary_id)
        secondary_id = _profession_id(secondary_id)
        if primary_id > 0:
            return primary_id, secondary_id

        living = Agent.GetLivingAgentByID(agent_id)
        if living is None:
            return primary_id, secondary_id
        primary_id = _profession_id(getattr(living, 'primary', 0)) or _profession_id(getattr(living, 'profession', 0))
        secondary_id = _profession_id(getattr(living, 'secondary', 0)) or _profession_id(
            getattr(living, 'secondary_profession', 0)
        )
        return primary_id, secondary_id
    except Exception:
        return 0, 0


def _hero_object_primary_profession_id(hero_member) -> int:
    try:
        hero_id_obj = getattr(hero_member, 'hero_id', None)
        get_profession = getattr(hero_id_obj, 'GetProfession', None)
        if callable(get_profession):
            return _profession_id(get_profession())
    except Exception:
        pass
    return 0


def _hero_agent_id_by_party_position(party_api, hero_index: int) -> int:
    hero_index = int(hero_index or 0)
    if party_api is None or hero_index <= 0:
        return 0

    lookups = [
        (getattr(party_api, 'Heroes', None), 'GetHeroAgentIDByPartyPosition'),
        (party_api, 'GetHeroAgentID'),
    ]
    for owner, method_name in lookups:
        if owner is None:
            continue
        method = getattr(owner, method_name, None)
        if not callable(method):
            continue
        try:
            agent_result: Any = method(hero_index)
            agent_id = int(agent_result or 0)
        except Exception:
            agent_id = 0
        if agent_id > 0:
            return agent_id
    return 0


def _hero_member_by_party_position(party_api, hero_index: int):
    hero_index = int(hero_index or 0)
    if party_api is None or hero_index <= 0:
        return None
    try:
        heroes = party_api.GetHeroes() or []
    except Exception:
        return None
    if hero_index > len(heroes):
        return None
    return heroes[hero_index - 1]


def _normalize_hero_identity_name(value: Any) -> str:
    cleaned = re.sub(r'\s+', ' ', _clean_display_name(value))
    return cleaned.casefold()


def _hero_profession_identity_name(hero_member, hero_id: int) -> str:
    hero_id = _coerce_hero_id(hero_id)
    if hero_id <= 0:
        return ''

    display_name = _detect_current_party_hero_display_name(hero_member, hero_id)
    if display_name:
        return display_name

    if hero_id in MERCENARY_HERO_IDS:
        return ''
    return hero_default_name(hero_id)


def _hero_profession_identity_key(hero_id: int, identity_name: str = '') -> tuple[int, str] | None:
    hero_id = _coerce_hero_id(hero_id)
    normalized_name = _normalize_hero_identity_name(identity_name)
    if hero_id <= 0 or not normalized_name:
        return None
    return hero_id, normalized_name


def _sync_current_party_hero_profession_cache_account() -> None:
    global _CURRENT_HERO_PROFESSION_CACHE_ACCOUNT_KEY
    try:
        account_key = safe_account_key()
    except Exception:
        return
    if not _CURRENT_HERO_PROFESSION_CACHE_ACCOUNT_KEY:
        _CURRENT_HERO_PROFESSION_CACHE_ACCOUNT_KEY = account_key
        return
    if account_key == _CURRENT_HERO_PROFESSION_CACHE_ACCOUNT_KEY:
        return
    _CURRENT_HERO_PROFESSION_CACHE.clear()
    _CURRENT_HERO_IDENTITY_PROFESSION_CACHE.clear()
    _CURRENT_HERO_PROFESSION_CACHE_ACCOUNT_KEY = account_key


def _write_hero_profession_cache_entry_to_disk(
    config: HeroTeamConfig | None,
    storage_key: str,
    entry: dict[str, Any],
) -> None:
    if config is None or not storage_key:
        return
    try:
        # Profession observations are intentionally persisted independently of the editable team
        # document. This preserves the legacy immediate-cache behavior without making JsonFactory
        # autosave ordinary team edits that are still behind the explicit Save button.
        _config_document().set_json(f'hero_profession_cache/{storage_key}', dict(entry))
    except Exception:
        return


def _remember_persisted_hero_profession(
    config: HeroTeamConfig | None,
    hero_id: int,
    identity_name: str,
    primary_id: int,
    secondary_id: int = 0,
) -> None:
    if config is None:
        return
    hero_id = _coerce_hero_id(hero_id)
    primary_id = _profession_id(primary_id)
    secondary_id = _profession_id(secondary_id)
    if not _is_valid_primary_profession_id(primary_id):
        return
    if not _is_valid_secondary_profession_id(secondary_id):
        secondary_id = 0

    storage_key = _hero_profession_cache_storage_key(hero_id, identity_name)
    if not storage_key:
        return
    entry = {
        'hero_id': int(hero_id),
        'identity_name': str(identity_name),
        'primary_profession_id': int(primary_id),
        'secondary_profession_id': int(secondary_id),
    }
    if not hasattr(config, 'hero_profession_cache') or not isinstance(config.hero_profession_cache, dict):
        config.hero_profession_cache = {}
    if config.hero_profession_cache.get(storage_key) == entry:
        return
    config.hero_profession_cache[storage_key] = entry
    _write_hero_profession_cache_entry_to_disk(config, storage_key, entry)


def _persisted_current_party_hero_profession(
    config: HeroTeamConfig | None,
    hero_id: int,
    identity_name: str,
) -> tuple[int, int]:
    if config is None:
        return 0, 0
    cache = getattr(config, 'hero_profession_cache', {})
    if not isinstance(cache, dict):
        return 0, 0
    storage_key = _hero_profession_cache_storage_key(hero_id, identity_name)
    if not storage_key:
        return 0, 0
    entry = cache.get(storage_key)
    if not isinstance(entry, dict):
        return 0, 0
    primary_id = _profession_id(entry.get('primary_profession_id', 0))
    secondary_id = _profession_id(entry.get('secondary_profession_id', 0))
    if not _is_valid_primary_profession_id(primary_id):
        return 0, 0
    if not _is_valid_secondary_profession_id(secondary_id):
        secondary_id = 0
    return primary_id, secondary_id


def _remember_current_party_hero_profession(
    hero_id: int,
    agent_id: int,
    primary_id: int,
    secondary_id: int = 0,
    identity_name: str = '',
    config: HeroTeamConfig | None = None,
    persist: bool = False,
) -> None:
    _sync_current_party_hero_profession_cache_account()
    hero_id = _coerce_hero_id(hero_id)
    try:
        agent_id = int(agent_id or 0)
    except Exception:
        agent_id = 0
    primary_id = _profession_id(primary_id)
    secondary_id = _profession_id(secondary_id)
    if hero_id <= 0 or primary_id <= 0:
        return
    cached_profession = (primary_id, max(0, secondary_id))
    if agent_id > 0:
        _CURRENT_HERO_PROFESSION_CACHE[(hero_id, agent_id)] = cached_profession
    identity_key = _hero_profession_identity_key(hero_id, identity_name)
    if identity_key is not None:
        _CURRENT_HERO_IDENTITY_PROFESSION_CACHE[identity_key] = cached_profession
    if persist:
        _remember_persisted_hero_profession(config, hero_id, identity_name, primary_id, secondary_id)


def _cached_current_party_hero_profession(
    hero_id: int,
    agent_id: int,
    identity_name: str = '',
) -> tuple[int, int]:
    _sync_current_party_hero_profession_cache_account()
    hero_id = _coerce_hero_id(hero_id)
    try:
        agent_id = int(agent_id or 0)
    except Exception:
        agent_id = 0
    if hero_id <= 0:
        return 0, 0
    if agent_id > 0:
        cached_profession = _CURRENT_HERO_PROFESSION_CACHE.get((hero_id, agent_id))
        if cached_profession is not None:
            return cached_profession
    identity_key = _hero_profession_identity_key(hero_id, identity_name)
    if identity_key is not None:
        return _CURRENT_HERO_IDENTITY_PROFESSION_CACHE.get(identity_key, (0, 0))
    return 0, 0


def _current_party_hero_profession_cache_keys(party_api) -> set[tuple[int, int]] | None:
    if party_api is None:
        return None
    try:
        heroes = party_api.GetHeroes() or []
    except Exception:
        return None

    keys: set[tuple[int, int]] = set()
    for hero_index, hero_member in enumerate(heroes, start=1):
        hero_id = _coerce_hero_id(hero_id_from_member(hero_member))
        if hero_id <= 0:
            continue
        try:
            agent_id = int(getattr(hero_member, 'agent_id', 0) or 0)
        except Exception:
            agent_id = 0
        if agent_id <= 0:
            agent_id = _hero_agent_id_by_party_position(party_api, hero_index)
        if agent_id > 0:
            keys.add((hero_id, agent_id))
    return keys


def _current_party_hero_profession_identity_keys(party_api) -> set[tuple[int, str]] | None:
    if party_api is None:
        return None
    try:
        heroes = party_api.GetHeroes() or []
    except Exception:
        return None

    keys: set[tuple[int, str]] = set()
    for hero_member in heroes:
        hero_id = _coerce_hero_id(hero_id_from_member(hero_member))
        identity_key = _hero_profession_identity_key(
            hero_id,
            _hero_profession_identity_name(hero_member, hero_id),
        )
        if identity_key is not None:
            keys.add(identity_key)
    return keys


def _prune_current_party_hero_profession_cache(party_api) -> None:
    _sync_current_party_hero_profession_cache_account()
    keys = _current_party_hero_profession_cache_keys(party_api)
    if keys is None:
        return
    if not keys:
        _CURRENT_HERO_PROFESSION_CACHE.clear()
    else:
        for key in list(_CURRENT_HERO_PROFESSION_CACHE):
            if key not in keys:
                _CURRENT_HERO_PROFESSION_CACHE.pop(key, None)

    identity_keys = _current_party_hero_profession_identity_keys(party_api)
    if not identity_keys:
        return
    current_identity_hero_ids = {hero_id for hero_id, _name in identity_keys}
    for key in list(_CURRENT_HERO_IDENTITY_PROFESSION_CACHE):
        hero_id, _identity_name = key
        if hero_id in current_identity_hero_ids and key not in identity_keys:
            _CURRENT_HERO_IDENTITY_PROFESSION_CACHE.pop(key, None)


def _object_int(value: Any, *attr_names: str) -> int:
    for attr_name in attr_names:
        try:
            candidate = getattr(value, attr_name)
        except Exception:
            continue
        try:
            candidate_value: Any = candidate() if callable(candidate) else candidate
            return int(candidate_value)
        except Exception:
            continue
    try:
        return int(value)
    except Exception:
        return 0


def _agent_primary_profession_id_from_attributes(agent_id: int) -> int:
    agent_id = int(agent_id or 0)
    if agent_id <= 0:
        return 0

    try:
        from Py4GWCoreLib.Agent import Agent
        from Py4GWCoreLib.enums_src.GameData_enums import Attribute

        attributes = Agent.GetAttributes(agent_id) or []
    except Exception:
        return 0

    detected_professions: set[int] = set()
    for attribute_data in attributes:
        attribute_id = _object_int(attribute_data, 'attribute_id', 'Id', 'id')
        level = max(
            _object_int(attribute_data, 'level_base', 'BaseValue', 'base_value'),
            _object_int(attribute_data, 'level', 'Value', 'value'),
        )
        if level <= 0:
            continue
        try:
            attribute = Attribute(attribute_id)
        except Exception:
            continue
        if not bool(getattr(attribute, 'is_primary', False)):
            continue
        profession_id = _profession_id(attribute.get_profession())
        if profession_id > 0:
            detected_professions.add(profession_id)

    if len(detected_professions) == 1:
        return detected_professions.pop()
    return 0


def _current_party_hero_profession_ids(
    hero_member,
    party_api,
    hero_index: int,
    hero_id: int = 0,
    config: HeroTeamConfig | None = None,
) -> tuple[int, int, int]:
    hero_id = _coerce_hero_id(hero_id)
    identity_name = _hero_profession_identity_name(hero_member, hero_id)
    try:
        agent_id = int(getattr(hero_member, 'agent_id', 0) or 0)
    except Exception:
        agent_id = 0

    primary_id = _profession_id(getattr(hero_member, 'primary', 0))
    secondary_id = _profession_id(getattr(hero_member, 'secondary', 0))

    if primary_id <= 0:
        primary_id = _hero_object_primary_profession_id(hero_member)

    candidate_agent_ids = [agent_id]
    position_agent_id = _hero_agent_id_by_party_position(party_api, hero_index)
    if position_agent_id > 0 and position_agent_id not in candidate_agent_ids:
        candidate_agent_ids.append(position_agent_id)
    if agent_id <= 0 and position_agent_id > 0:
        agent_id = position_agent_id

    for candidate_agent_id in candidate_agent_ids:
        if candidate_agent_id <= 0:
            continue
        if primary_id > 0 and secondary_id > 0:
            break
        agent_primary_id, agent_secondary_id = _agent_profession_ids(candidate_agent_id)
        if primary_id <= 0 and agent_primary_id > 0:
            primary_id = _profession_id(agent_primary_id)
        if primary_id <= 0:
            primary_id = _agent_primary_profession_id_from_attributes(candidate_agent_id)
        if secondary_id <= 0 and agent_secondary_id > 0:
            secondary_id = _profession_id(agent_secondary_id)
        if agent_id <= 0 and (primary_id > 0 or agent_primary_id > 0 or agent_secondary_id > 0):
            agent_id = candidate_agent_id

    live_primary_id = primary_id
    live_secondary_id = secondary_id
    cached_primary_id, cached_secondary_id = _cached_current_party_hero_profession(
        hero_id,
        agent_id,
        identity_name,
    )
    if primary_id <= 0 and cached_primary_id > 0:
        primary_id = cached_primary_id
    if secondary_id <= 0 and cached_secondary_id > 0:
        secondary_id = cached_secondary_id

    if primary_id <= 0:
        persisted_primary_id, persisted_secondary_id = _persisted_current_party_hero_profession(
            config,
            hero_id,
            identity_name,
        )
        if persisted_primary_id > 0:
            primary_id = persisted_primary_id
        if secondary_id <= 0 and persisted_secondary_id > 0:
            secondary_id = persisted_secondary_id

    if primary_id > 0:
        _remember_current_party_hero_profession(
            hero_id,
            agent_id,
            primary_id,
            live_secondary_id if live_primary_id > 0 else secondary_id,
            identity_name,
            config,
            persist=live_primary_id > 0,
        )

    return primary_id, secondary_id, agent_id


def summarize_skill_template(
    template: HeroTemplateEntry | str,
    template_name: str | None = None,
) -> SkillTemplatePreview | None:
    if isinstance(template, HeroTemplateEntry):
        code = str(template.code or '').strip()
        name = str(template_name if template_name is not None else template.name or '').strip()
    else:
        code = str(template or '').strip()
        name = str(template_name or '').strip()

    if len(code) < 16 or not re.fullmatch(r'[A-Za-z0-9+/]+', code):
        return None

    try:
        from Py4GWCoreLib.enums_src.GameData_enums import Attribute
        from Py4GWCoreLib.enums_src.GameData_enums import Profession
        from Py4GWCoreLib.enums_src.GameData_enums import ProfessionShort
        from Py4GWCoreLib.enums_src.GameData_enums import ProfessionShort_Names
        from Py4GWCoreLib.enums_src.Texture_enums import ProfessionTextureMap
        from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils
        from Py4GWCoreLib.Skill import Skill

        encoded = ''.join(Utils.base64_to_bin64(char) for char in code)
        if len(encoded) < 4 or Utils.bin64_to_dec(encoded[:4]) != 14:
            return None

        primary, secondary, attributes, skills = Utils.ParseSkillbarTemplate(code)
        primary_id = int(primary or 0)
        secondary_id = int(secondary or 0)
        profession_ids = {int(profession) for profession in Profession}
        if primary_id not in profession_ids:
            return None
        if secondary_id not in profession_ids:
            return None
        if not isinstance(skills, list) or len(skills) != 8:
            return None

        primary_label = ProfessionShort_Names.get(ProfessionShort(primary_id), '') if primary_id else ''
        secondary_label = ProfessionShort_Names.get(ProfessionShort(secondary_id), '') if secondary_id else ''
        profession_label = '/'.join(label for label in [primary_label, secondary_label] if label and label != 'None')
        profession_icon_name = ProfessionTextureMap.get(primary_id, '')
        profession_icon_path = f'Assets\\Textures\\Profession_Icons\\{profession_icon_name}' if profession_icon_name else ''

        attribute_parts: list[str] = []
        if isinstance(attributes, dict):
            for attribute_id, level in attributes.items():
                level = int(level or 0)
                if level <= 0:
                    continue
                try:
                    attribute_name = _human_enum_name(Attribute(int(attribute_id)).name)
                except Exception:
                    attribute_name = f'Attribute {int(attribute_id)}'
                attribute_parts.append(f'{attribute_name} {level}')

        skill_ids = [max(0, int(skill_id or 0)) for skill_id in skills[:8]]
        skill_names: list[str] = []
        skill_icon_paths: list[str] = []
        for skill_id in skill_ids:
            if skill_id <= 0:
                skill_names.append('')
                skill_icon_paths.append('')
                continue
            try:
                skill_name = Skill.GetNameFromWiki(skill_id) or Skill.GetName(skill_id) or f'Skill {skill_id}'
            except Exception:
                skill_name = f'Skill {skill_id}'
            try:
                icon_path = Skill.ExtraData.GetTexturePath(skill_id)
            except Exception:
                icon_path = ''
            skill_names.append(str(skill_name or f'Skill {skill_id}'))
            skill_icon_paths.append(str(icon_path or ''))

        return SkillTemplatePreview(
            template_name=name or 'Template',
            primary_profession_id=primary_id,
            secondary_profession_id=secondary_id,
            profession_label=profession_label,
            profession_icon_path=profession_icon_path,
            attribute_summary=', '.join(attribute_parts),
            skill_ids=skill_ids,
            skill_names=skill_names,
            skill_icon_paths=skill_icon_paths,
        )
    except Exception:
        return None


def classify_template_profession(template: HeroTemplateEntry | str) -> TemplateProfessionGroup:
    if isinstance(template, HeroTemplateEntry):
        code = str(template.code or '').strip()
    else:
        code = str(template or '').strip()

    if not code:
        return TemplateProfessionGroup(
            group_key='unknown_empty',
            label='Unknown / Empty',
            sort_order=900,
        )
    if len(code) < 16 or not re.fullmatch(r'[A-Za-z0-9+/]+', code):
        return TemplateProfessionGroup(
            group_key='unknown_invalid',
            label='Unknown / Invalid',
            sort_order=901,
        )

    try:
        from Py4GWCoreLib.enums_src.GameData_enums import Profession
        from Py4GWCoreLib.enums_src.GameData_enums import Profession_Names
        from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils

        encoded = ''.join(Utils.base64_to_bin64(char) for char in code)
        if len(encoded) < 4 or Utils.bin64_to_dec(encoded[:4]) != 14:
            return TemplateProfessionGroup(
                group_key='unknown_invalid',
                label='Unknown / Invalid',
                sort_order=901,
            )

        primary, _secondary, _attributes, _skills = Utils.ParseSkillbarTemplate(code)
        primary_id = int(primary or 0)
        profession = Profession(primary_id)
        label = str(Profession_Names.get(profession, '') or '').strip()
        if primary_id <= 0 or not label or label == 'None':
            return TemplateProfessionGroup(
                group_key='unknown_no_profession',
                label='Unknown / No Profession',
                sort_order=902,
            )
        return TemplateProfessionGroup(
            group_key=f'profession_{primary_id}',
            label=label,
            sort_order=primary_id,
            primary_profession_id=primary_id,
            is_known_profession=True,
        )
    except Exception:
        return TemplateProfessionGroup(
            group_key='unknown_invalid',
            label='Unknown / Invalid',
            sort_order=901,
        )


def add_team(config: HeroTeamConfig, name: str = 'New Hero Team') -> HeroTeamSetup:
    team = new_team(name)
    config.teams.append(team)
    config.active_team_id = team.team_id
    return team


def duplicate_team(config: HeroTeamConfig, team_id: str) -> HeroTeamSetup | None:
    source = get_team(config, team_id)
    if source is None:
        return None
    team = HeroTeamSetup(
        team_id=_new_id('team', f'{source.name} Copy'),
        name=f'{source.name} Copy',
        slots=deepcopy(normalize_slots(source.slots)),
        alt_members=deepcopy(source.alt_members),
    )
    config.teams.append(team)
    config.active_team_id = team.team_id
    return team


def delete_team(config: HeroTeamConfig, team_id: str) -> bool:
    if len(config.teams) <= 1:
        return False
    before = len(config.teams)
    config.teams = [team for team in config.teams if team.team_id != team_id]
    if len(config.teams) == before:
        return False
    if config.active_team_id == team_id:
        config.active_team_id = config.teams[0].team_id
    return True


def add_template(
    config: HeroTeamConfig,
    name: str = 'New Template',
    code: str = '',
    hero_id: int = 0,
) -> HeroTemplateEntry:
    template = new_template(name=name, code=code)
    config.templates.append(template)
    set_template_preferred_hero_id(config, template.template_id, hero_id)
    return template


def delete_template(config: HeroTeamConfig, template_id: str) -> bool:
    before = len(config.templates)
    config.templates = [template for template in config.templates if template.template_id != template_id]
    if len(config.templates) == before:
        return False
    return True


def dedupe_team_slots(team: HeroTeamSetup) -> tuple[int, list[int]]:
    seen: set[int] = set()
    cleared: list[int] = []
    slots = normalize_slots(team.slots)
    for index, slot in enumerate(slots):
        hero_id = _coerce_hero_id(slot.hero_id)
        if hero_id <= 0:
            continue
        if hero_id in seen:
            slot.hero_id = 0
            slot.template_id = ''
            slot.template_code = ''
            slot.behavior = HERO_BEHAVIOR_DONT_CHANGE
            cleared.append(index)
            continue
        seen.add(hero_id)
    team.slots = slots
    return len(cleared), cleared


def _existing_slot_assignments(team: HeroTeamSetup | None) -> dict[int, tuple[str, str]]:
    assignments: dict[int, tuple[str, str]] = {}
    if team is None:
        return assignments
    for slot in normalize_slots(team.slots):
        hero_id = _coerce_hero_id(slot.hero_id)
        if hero_id > 0 and hero_id not in assignments:
            assignments[hero_id] = (str(slot.template_id or ''), str(slot.template_code or ''))
    return assignments


def _detect_current_party_hero_display_name(hero_member, hero_id: int) -> str:
    if hero_id not in MERCENARY_HERO_IDS:
        return ''
    agent_id = int(getattr(hero_member, 'agent_id', 0) or 0)
    name = ''
    if agent_id > 0:
        try:
            from Py4GWCoreLib.Agent import Agent

            name = _clean_display_name(Agent.GetNameByID(agent_id))
        except Exception:
            name = ''
    if not name:
        try:
            hero_id_obj = getattr(hero_member, 'hero_id', None)
            if hero_id_obj is not None and hasattr(hero_id_obj, 'GetName'):
                name = _clean_display_name(hero_id_obj.GetName())
        except Exception:
            name = ''

    generic_name = HERO_ID_TO_NAME.get(hero_id, '')
    return name if name and name != generic_name else ''


def save_current_party_as_team(
    config: HeroTeamConfig,
    *,
    team_id: str | None = None,
    team_name: str | None = None,
    party_api=None,
) -> tuple[HeroTeamSetup, int]:
    if party_api is None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        party_api = GLOBAL_CACHE.Party

    team = get_team(config, team_id)
    existing_assignments = _existing_slot_assignments(team)
    slots: list[HeroTeamSlot] = []
    seen: set[int] = set()
    detected_names: dict[str, str] = {}
    local_login_number = current_local_login_number()

    for hero_member in party_api.GetHeroes() or []:
        if hero_owner_category(hero_member, local_login_number) != 'local':
            continue
        hero_id = _coerce_hero_id(hero_id_from_member(hero_member))
        if hero_id <= 0 or hero_id in seen:
            continue
        seen.add(hero_id)
        template_id, template_code = existing_assignments.get(hero_id, ('', ''))
        slots.append(
            HeroTeamSlot(
                hero_id=hero_id,
                template_id=template_id,
                template_code=template_code,
                behavior=HERO_BEHAVIOR_DONT_CHANGE,
            )
        )

        display_name = _detect_current_party_hero_display_name(hero_member, hero_id)
        if display_name:
            detected_names[str(hero_id)] = display_name

        if len(slots) >= HERO_SLOT_COUNT:
            break

    if not seen:
        if team is None:
            raise ValueError('No selected team and no current party heroes to save.')
        return team, 0

    if team is None:
        team = add_team(config, team_name or 'Current Hero Team')
    if team_name is not None:
        team.name = str(team_name or 'Current Hero Team')

    while len(slots) < HERO_SLOT_COUNT:
        slots.append(HeroTeamSlot())

    team.slots = slots
    config.active_team_id = team.team_id
    for hero_id, display_name in detected_names.items():
        if not hero_alias(config, int(hero_id)):
            config.hero_names[hero_id] = display_name
    return team, min(len(seen), HERO_SLOT_COUNT)


def current_party_hero_targets(
    config: HeroTeamConfig | None = None,
    *,
    party_api=None,
    player_agent_id: int | None = None,
    only_owned: bool = True,
) -> list[CurrentPartyHeroTarget]:
    if party_api is None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        party_api = GLOBAL_CACHE.Party
    if player_agent_id is None:
        try:
            from Py4GWCoreLib.Player import Player

            player_agent_id = int(Player.GetAgentID() or 0)
        except Exception:
            player_agent_id = 0

    try:
        player_count = int(party_api.GetPlayerCount() or 0)
    except Exception:
        player_count = 0

    _prune_current_party_hero_profession_cache(party_api)

    targets: list[CurrentPartyHeroTarget] = []
    for hero_index, hero_member in enumerate(party_api.GetHeroes() or [], start=1):
        owner_agent_id = 0
        try:
            players_api = getattr(party_api, 'Players', None)
            owner_login = int(getattr(hero_member, 'owner_player_id', 0) or 0)
            if players_api is not None and owner_login > 0:
                owner_agent_id = int(players_api.GetAgentIDByLoginNumber(owner_login) or 0)
        except Exception:
            owner_agent_id = 0
        if only_owned and int(player_agent_id or 0) > 0:
            if owner_agent_id > 0 and owner_agent_id != int(player_agent_id):
                continue
            if player_count > 1 and owner_agent_id <= 0:
                continue

        hero_id = _coerce_hero_id(hero_id_from_member(hero_member))
        if hero_id <= 0:
            continue
        primary_id, secondary_id, agent_id = _current_party_hero_profession_ids(
            hero_member,
            party_api,
            hero_index,
            hero_id,
            config,
        )
        detected_name = _detect_current_party_hero_display_name(hero_member, hero_id)
        hero_name = hero_alias(config, hero_id) if config is not None else ''
        hero_name = hero_name or detected_name or hero_default_name(hero_id)
        targets.append(
            CurrentPartyHeroTarget(
                hero_index=int(hero_index),
                hero_id=hero_id,
                hero_name=hero_name,
                agent_id=agent_id,
                primary_profession_id=primary_id,
                secondary_profession_id=secondary_id,
                profession_label=_profession_short_label(primary_id, secondary_id),
            )
        )
    return targets


def current_party_hero_targets_for_template(
    config: HeroTeamConfig | None,
    template: HeroTemplateEntry,
    *,
    party_api=None,
    player_agent_id: int | None = None,
    only_owned: bool = True,
) -> list[CurrentPartyHeroTarget]:
    preview = summarize_skill_template(template)
    if preview is None:
        return []
    template_primary_id = int(preview.primary_profession_id or 0)
    if template_primary_id <= 0:
        return []
    return [
        target
        for target in current_party_hero_targets(
            config,
            party_api=party_api,
            player_agent_id=player_agent_id,
            only_owned=only_owned,
        )
        if int(target.primary_profession_id or 0) == template_primary_id
    ]


def _find_current_party_hero_target(
    targets: list[CurrentPartyHeroTarget],
    *,
    target_hero_id: int = 0,
    target_hero_index: int = 0,
) -> CurrentPartyHeroTarget | None:
    hero_id = _coerce_hero_id(target_hero_id)
    hero_index = int(target_hero_index or 0)
    if hero_id > 0 and hero_index > 0:
        for target in targets:
            if target.hero_id == hero_id and target.hero_index == hero_index:
                return target
    if hero_id > 0:
        matches = [target for target in targets if target.hero_id == hero_id]
        if len(matches) == 1:
            return matches[0]
    if hero_id <= 0 and hero_index > 0:
        for target in targets:
            if target.hero_index == hero_index:
                return target
    return None


def apply_template_to_current_party_hero(
    config: HeroTeamConfig | None,
    template: HeroTemplateEntry,
    *,
    target_hero_id: int = 0,
    target_hero_index: int = 0,
    party_api=None,
    skillbar_api=None,
    map_api=None,
) -> ApplyTemplateToHeroResult:
    template_name = str(getattr(template, 'name', '') or 'Template')
    template_code = str(getattr(template, 'code', '') or '').strip()
    preview = summarize_skill_template(template)
    if not template_code or preview is None:
        return ApplyTemplateToHeroResult(False, 'Template not applied: template code could not be parsed.')

    if party_api is None or skillbar_api is None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        party_api = party_api or GLOBAL_CACHE.Party
        skillbar_api = skillbar_api or GLOBAL_CACHE.SkillBar
    if map_api is None:
        from Py4GWCoreLib.Map import Map

        map_api = Map

    try:
        if not map_api.IsOutpost():
            return ApplyTemplateToHeroResult(False, 'Template not applied: current map is not an outpost.')
    except Exception:
        return ApplyTemplateToHeroResult(False, 'Template not applied: could not verify current map.')
    try:
        if not party_api.IsPartyLoaded():
            return ApplyTemplateToHeroResult(False, 'Template not applied: party is not loaded.')
    except Exception:
        return ApplyTemplateToHeroResult(False, 'Template not applied: could not read current party.')
    try:
        if not party_api.IsPartyLeader():
            return ApplyTemplateToHeroResult(False, 'Template not applied: current character is not party leader.')
    except Exception:
        return ApplyTemplateToHeroResult(False, 'Template not applied: could not verify party leader.')

    targets = current_party_hero_targets(config, party_api=party_api, only_owned=True)
    target = _find_current_party_hero_target(
        targets,
        target_hero_id=target_hero_id,
        target_hero_index=target_hero_index,
    )
    if target is None:
        return ApplyTemplateToHeroResult(False, 'Template not applied: selected hero is not in the current party.')

    template_primary_id = int(preview.primary_profession_id or 0)
    target_primary_id = int(target.primary_profession_id or 0)
    if template_primary_id <= 0:
        return ApplyTemplateToHeroResult(False, 'Template not applied: template code could not be parsed.')
    if target_primary_id <= 0:
        return ApplyTemplateToHeroResult(
            False,
            f'Template not applied: could not read profession for {target.hero_name}.',
            hero_id=target.hero_id,
            hero_index=target.hero_index,
        )
    if template_primary_id != target_primary_id:
        template_profession = _profession_name(template_primary_id) or f'profession {template_primary_id}'
        target_profession = _profession_name(target_primary_id) or f'profession {target_primary_id}'
        return ApplyTemplateToHeroResult(
            False,
            f'Template not applied: {template_name} is {template_profession}, '
            f'but {target.hero_name} is {target_profession}.',
            hero_id=target.hero_id,
            hero_index=target.hero_index,
        )

    try:
        skillbar_api.LoadHeroSkillTemplate(int(target.hero_index), template_code)
    except Exception as exc:
        return ApplyTemplateToHeroResult(
            False,
            f'Template apply failed for {target.hero_name}: {exc}',
            hero_id=target.hero_id,
            hero_index=target.hero_index,
        )

    return ApplyTemplateToHeroResult(
        True,
        f'Template apply queued: {template_name} -> {target.hero_name}.',
        hero_id=target.hero_id,
        hero_index=target.hero_index,
    )


def resolve_slot_template_code(slot: HeroTeamSlot, templates: list[HeroTemplateEntry]) -> tuple[str, str]:
    inline_code = str(slot.template_code or '').strip()
    if inline_code:
        return inline_code, 'Inline'
    template_id = str(slot.template_id or '').strip()
    if not template_id:
        return '', ''
    for template in templates:
        if template.template_id == template_id:
            return str(template.code or '').strip(), str(template.name or '')
    return '', ''


def build_load_plan(
    team: HeroTeamSetup,
    templates: list[HeroTemplateEntry],
    max_heroes: int = HERO_SLOT_COUNT,
    hero_names: dict[str, str] | None = None,
) -> HeroTeamLoadPlan:
    plan = HeroTeamLoadPlan()
    seen: set[int] = set()
    max_heroes = max(0, int(max_heroes))
    for index, slot in enumerate(normalize_slots(team.slots)):
        hero_id = _coerce_hero_id(slot.hero_id)
        if hero_id <= 0:
            plan.skipped_empty.append(index)
            continue
        if hero_id in seen:
            plan.skipped_duplicates.append(index)
            continue
        if len(plan.slots) >= max_heroes:
            plan.truncated_slots.append(index)
            continue
        seen.add(hero_id)
        template_code, template_name = resolve_slot_template_code(slot, templates)
        template_assigned = bool(str(slot.template_id or '').strip() or str(slot.template_code or '').strip())
        clear_skillbar = not template_assigned
        plan.slots.append(
            ResolvedHeroSlot(
                slot_index=index,
                hero_id=hero_id,
                hero_name=_hero_display_name_from_aliases(hero_names, hero_id),
                template_code=template_code,
                template_name=template_name or (EMPTY_SKILLBAR_TEMPLATE_NAME if clear_skillbar else ''),
                template_assigned=template_assigned,
                template_missing=template_assigned and not bool(template_code),
                clear_skillbar=clear_skillbar,
                behavior=_coerce_behavior(slot.behavior),
            )
        )
    return plan


def _add_row_warning(
    preflight: HeroTeamLoadPreflight,
    slot_index: int,
    code: str,
    message: str,
    severity: str = 'warning',
) -> None:
    warnings = preflight.row_warnings.setdefault(int(slot_index), [])
    if any(warning.code == code for warning in warnings):
        return
    warnings.append(
        HeroTeamRowWarning(
            slot_index=int(slot_index),
            code=str(code),
            message=str(message),
            severity=str(severity or 'warning'),
        )
    )


def _runtime_preflight_max_heroes(
    preflight: HeroTeamLoadPreflight,
    *,
    include_runtime: bool,
    leave_party_first: bool,
    clear_existing: bool,
    map_api=None,
    party_api=None,
) -> int:
    max_heroes = HERO_SLOT_COUNT
    if not include_runtime:
        return max_heroes

    if map_api is None:
        try:
            from Py4GWCoreLib.Map import Map

            map_api = Map
        except Exception:
            map_api = None
    if party_api is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            party_api = GLOBAL_CACHE.Party
        except Exception:
            party_api = None

    if map_api is None:
        preflight.blocking_messages.append('Load skipped: could not verify current map.')
    else:
        try:
            if not map_api.IsOutpost():
                preflight.blocking_messages.append('Load skipped: current map is not an outpost.')
        except Exception:
            preflight.blocking_messages.append('Load skipped: could not verify current map.')

    if party_api is not None and not leave_party_first:
        try:
            if not party_api.IsPartyLeader():
                preflight.blocking_messages.append('Load skipped: current character is not party leader.')
        except Exception:
            preflight.blocking_messages.append('Load skipped: could not verify party leader.')

    if leave_party_first:
        try:
            map_size = int(map_api.GetMaxPartySize() or 0) if map_api is not None else 0
        except Exception:
            map_size = 0
        if map_size > 0:
            max_heroes = max(0, min(HERO_SLOT_COUNT, map_size - 1))
        if party_api is not None:
            try:
                if (
                    int(party_api.GetPlayerCount() or 0) > 1
                    or int(party_api.GetHeroCount() or 0) > 0
                    or int(party_api.GetHenchmanCount() or 0) > 0
                    or not bool(party_api.IsPartyLeader())
                ):
                    preflight.warnings.append('Load will leave the current party before loading this team.')
            except Exception:
                pass
    elif clear_existing:
        try:
            map_size = int(map_api.GetMaxPartySize() or 0) if map_api is not None else 0
        except Exception:
            map_size = 0
        if map_size > 0:
            try:
                player_count = int(party_api.GetPlayerCount() or 1) if party_api is not None else 1
            except Exception:
                player_count = 1
            max_heroes = max(0, min(HERO_SLOT_COUNT, map_size - max(1, player_count)))
    else:
        try:
            max_heroes = hero_slot_capacity(map_api=map_api, party_api=party_api, default=HERO_SLOT_COUNT)
        except Exception:
            max_heroes = HERO_SLOT_COUNT

    if max_heroes <= 0:
        preflight.blocking_messages.append('Load skipped: there is no available hero slot in this party.')
    return max_heroes


def build_load_preflight(
    config: HeroTeamConfig,
    team_id: str | None = None,
    *,
    include_runtime: bool = False,
    leave_party_first: bool = False,
    clear_existing: bool = True,
    map_api=None,
    party_api=None,
) -> HeroTeamLoadPreflight:
    preflight = HeroTeamLoadPreflight()
    team = get_team(config, team_id)
    if team is None:
        preflight.blocking_messages.append('Load skipped: no team selected.')
        return preflight

    max_heroes = _runtime_preflight_max_heroes(
        preflight,
        include_runtime=include_runtime,
        leave_party_first=leave_party_first,
        clear_existing=clear_existing,
        map_api=map_api,
        party_api=party_api,
    )
    preflight.max_heroes = max_heroes
    preflight.plan = build_load_plan(
        team,
        config.templates,
        max_heroes=max_heroes,
        hero_names=config.hero_names,
    )

    slots = normalize_slots(team.slots)
    templates_by_id = {str(template.template_id): template for template in config.templates}

    for slot_index in preflight.plan.skipped_empty:
        _add_row_warning(preflight, slot_index, 'skipped_empty', 'Empty slot will be skipped.', 'info')
    for slot_index in preflight.plan.skipped_duplicates:
        _add_row_warning(
            preflight,
            slot_index,
            'duplicate_hero',
            'Duplicate hero; only the first copy will load.',
            'warning',
        )
    for slot_index in preflight.plan.truncated_slots:
        _add_row_warning(
            preflight,
            slot_index,
            'truncated_slot',
            'No available party slot; this row will not load.',
            'warning',
        )

    for slot_index, slot in enumerate(slots):
        hero_id = _coerce_hero_id(slot.hero_id)
        if hero_id <= 0:
            continue
        template_id = str(slot.template_id or '').strip()
        inline_code = str(slot.template_code or '').strip()
        if not template_id:
            continue
        template = templates_by_id.get(template_id)
        if template is None:
            if inline_code:
                _add_row_warning(
                    preflight,
                    slot_index,
                    'missing_template_reference_inline_override',
                    'Global template is missing; the inline override will be applied.',
                    'info',
                )
                continue
            _add_row_warning(
                preflight,
                slot_index,
                'missing_template_reference',
                'Assigned template is missing; no template will be applied.',
                'warning',
            )
            continue
        if not inline_code and not str(template.code or '').strip():
            _add_row_warning(
                preflight,
                slot_index,
                'empty_assigned_template',
                'Assigned template has no code; no template will be applied.',
                'warning',
            )

    for resolved_slot in preflight.plan.slots:
        if resolved_slot.template_missing:
            _add_row_warning(
                preflight,
                resolved_slot.slot_index,
                'missing_template_code',
                'Assigned template could not be resolved; no template will be applied.',
                'warning',
            )

    if not preflight.plan.slots:
        preflight.blocking_messages.append('Load skipped: selected team has no non-empty hero slots.')

    warning_count = sum(
        1 for warnings in preflight.row_warnings.values() for warning in warnings if warning.severity != 'info'
    )
    if warning_count:
        preflight.warnings.append(f'{warning_count} row warning{"s" if warning_count != 1 else ""}.')
    return preflight


def _current_hero_slot_capacity() -> int:
    try:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
        from Py4GWCoreLib.Map import Map

        return hero_slot_capacity(map_api=Map, party_api=GLOBAL_CACHE.Party, default=HERO_SLOT_COUNT)
    except Exception:
        return HERO_SLOT_COUNT


def _empty_skillbar_template_for_hero_position(hero_index: int, party_api=None) -> str:
    hero_index = int(hero_index or 0)
    if hero_index <= 0:
        return ''

    if party_api is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            party_api = GLOBAL_CACHE.Party
        except Exception:
            party_api = None

    hero_member = _hero_member_by_party_position(party_api, hero_index)
    hero_id = _coerce_hero_id(hero_id_from_member(hero_member)) if hero_member is not None else 0
    if hero_member is not None:
        primary_id, secondary_id, agent_id = _current_party_hero_profession_ids(
            hero_member,
            party_api,
            hero_index,
            hero_id,
        )
    else:
        agent_id = _hero_agent_id_by_party_position(party_api, hero_index)
        primary_id, secondary_id = _agent_profession_ids(agent_id)
        if primary_id <= 0:
            primary_id = _agent_primary_profession_id_from_attributes(agent_id)
        if primary_id > 0:
            _remember_current_party_hero_profession(hero_id, agent_id, primary_id, secondary_id)
    if primary_id <= 0:
        return ''

    try:
        from Py4GWCoreLib.py4gwcorelib_src.Utils import Utils

        return Utils.GenerateSkillbarTemplateFrom(primary_id, secondary_id, {}, [0] * 8)
    except Exception:
        return ''


class HeroTeamApplyOperation:
    def __init__(
        self,
        team: HeroTeamSetup,
        templates: list[HeroTemplateEntry],
        *,
        hero_names: dict[str, str] | None = None,
        leave_party_first: bool = False,
        clear_existing: bool = True,
        leave_timeout_ms: int = 5000,
        leave_poll_ms: int = 250,
        add_delay_ms: int = 250,
        post_kick_wait_ms: int = 500,
        post_add_wait_ms: int = 1000,
        template_delay_ms: int = 500,
    ) -> None:
        self.team = deepcopy(team)
        self.templates = deepcopy(templates)
        self.hero_names = dict(hero_names or {})
        self.leave_party_first = bool(leave_party_first)
        self.clear_existing = bool(clear_existing)
        self.leave_timeout_ms = max(0, int(leave_timeout_ms))
        self.leave_poll_ms = max(50, int(leave_poll_ms))
        self.add_delay_ms = max(0, int(add_delay_ms))
        self.post_kick_wait_ms = max(0, int(post_kick_wait_ms))
        self.post_add_wait_ms = max(0, int(post_add_wait_ms))
        self.template_delay_ms = max(0, int(template_delay_ms))

        self.plan = HeroTeamLoadPlan()
        self.state = 'pending'
        self.message = 'Pending.'
        self.done = False
        self.success = False
        self.added_hero_ids: list[int] = []
        self.applied_template_hero_ids: list[int] = []
        self.cleared_skillbar_hero_ids: list[int] = []
        self.applied_behavior_hero_ids: list[int] = []
        self.missing_hero_ids: list[int] = []
        self.failed_template_slots: list[ResolvedHeroSlot] = []

        self._phase = 'leave_party' if self.leave_party_first else 'validate'
        self._next_at = 0.0
        self._leave_dispatched = False
        self._leave_deadline = 0.0
        self._add_index = 0
        self._behavior_index = 0
        self._template_index = 0

    def _wait(self, ms: int) -> None:
        self._next_at = monotonic() + (max(0, int(ms)) / 1000.0)

    def _ready(self) -> bool:
        return monotonic() >= self._next_at

    def _finish(self, success: bool, message: str) -> None:
        self.done = True
        self.success = bool(success)
        self.state = 'done' if success else 'failed'
        self.message = message

    def _party_loaded(self, party_api) -> bool:
        try:
            return bool(party_api.IsPartyLoaded())
        except Exception:
            return False

    def _party_player_count(self, party_api) -> int:
        try:
            return int(party_api.GetPlayerCount() or 0)
        except Exception:
            return 0

    def _party_hero_count(self, party_api) -> int:
        try:
            return int(party_api.GetHeroCount() or 0)
        except Exception:
            return 0

    def _party_henchman_count(self, party_api) -> int:
        try:
            return int(party_api.GetHenchmanCount() or 0)
        except Exception:
            return 0

    def _is_party_leader(self, party_api) -> bool:
        try:
            return bool(party_api.IsPartyLeader())
        except Exception:
            return False

    def _needs_leave_party(self, party_api) -> bool:
        return (
            self._party_player_count(party_api) > 1
            or self._party_hero_count(party_api) > 0
            or self._party_henchman_count(party_api) > 0
            or not self._is_party_leader(party_api)
        )

    def _party_settled_after_leave(self, party_api) -> bool:
        if not self._party_loaded(party_api):
            return False
        return (
            self._party_player_count(party_api) <= 1
            and self._party_henchman_count(party_api) <= 0
            and self._is_party_leader(party_api)
        )

    def _slot_label(self, slot: ResolvedHeroSlot, *, include_slot: bool = False) -> str:
        label = str(slot.hero_name or hero_default_name(slot.hero_id))
        return f'H{slot.slot_index + 1}: {label}' if include_slot else label

    def _template_slot_label(self, slot: ResolvedHeroSlot) -> str:
        label = self._slot_label(slot, include_slot=True)
        template_name = str(slot.template_name or '').strip()
        return f'{label} ({template_name})' if template_name else label

    def _join_labels(self, values: list[str]) -> str:
        return ', '.join(str(value) for value in values if str(value or '').strip())

    def _count_label(self, count: int, singular: str, plural: str | None = None) -> str:
        count = int(count)
        return f'{count} {singular if count == 1 else plural or singular + "s"}'

    def _final_status(self) -> str:
        missing_ids = set(int(hero_id) for hero_id in self.missing_hero_ids)
        loaded_count = len([slot for slot in self.plan.slots if int(slot.hero_id) not in missing_ids])
        template_count = len(self.applied_template_hero_ids)
        clear_count = len(self.cleared_skillbar_hero_ids)
        behavior_count = len(self.applied_behavior_hero_ids)
        details: list[str] = [f'Loaded {self._count_label(loaded_count, "hero", "heroes")}']
        if behavior_count:
            details.append(f'applied {self._count_label(behavior_count, "behavior setting")}')
        if template_count:
            details.append(f'applied {self._count_label(template_count, "template")}')
        if clear_count:
            details.append(f'cleared {self._count_label(clear_count, "skill bar")}')
        if self.plan.skipped_duplicates:
            details.append(f'skipped {self._count_label(len(self.plan.skipped_duplicates), "duplicate")}')
        if self.plan.truncated_slots:
            details.append(f'truncated {self._count_label(len(self.plan.truncated_slots), "slot")}')
        if missing_ids:
            details.append(f'missing {self._count_label(len(missing_ids), "hero", "heroes")}')

        messages = [', '.join(details) + '.']
        missing_slots = [slot for slot in self.plan.slots if int(slot.hero_id) in missing_ids]
        if missing_slots:
            messages.append(f'Failed to add: {self._join_labels([self._slot_label(slot) for slot in missing_slots])}.')

        missing_template_slots = [slot for slot in self.plan.slots if slot.template_missing]
        if missing_template_slots:
            labels = [self._template_slot_label(slot) for slot in missing_template_slots]
            messages.append(f'Missing template for: {self._join_labels(labels)}.')

        applied_template_ids = set(int(hero_id) for hero_id in self.applied_template_hero_ids)
        cleared_skillbar_ids = set(int(hero_id) for hero_id in self.cleared_skillbar_hero_ids)
        unapplied_template_slots = [
            slot
            for slot in self.plan.slots
            if (
                (slot.template_code and int(slot.hero_id) not in applied_template_ids)
                or (slot.clear_skillbar and int(slot.hero_id) not in cleared_skillbar_ids)
            )
        ]
        if self.failed_template_slots:
            failed_ids = {int(slot.hero_id) for slot in self.failed_template_slots}
            unapplied_template_slots = [
                slot for slot in unapplied_template_slots if int(slot.hero_id) not in failed_ids
            ] + self.failed_template_slots
        if unapplied_template_slots:
            labels = [self._template_slot_label(slot) for slot in unapplied_template_slots]
            messages.append(f'Template not applied for: {self._join_labels(labels)}.')

        return ' '.join(messages)

    def tick(self) -> bool:
        if self.done:
            return True
        if not self._ready():
            return False

        try:
            self._tick()
        except Exception as exc:
            self._finish(False, f'Hero team load failed: {exc}')
        return self.done

    def _tick(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
        from Py4GWCoreLib.Map import Map

        if self._phase == 'leave_party':
            if not Map.IsOutpost():
                self._finish(False, 'Load skipped: current map is not an outpost.')
                return

            if self._leave_deadline <= 0:
                self._leave_deadline = monotonic() + (self.leave_timeout_ms / 1000.0)

            if not self._party_loaded(GLOBAL_CACHE.Party):
                if monotonic() >= self._leave_deadline:
                    self._finish(False, 'Load skipped: could not leave current party.')
                    return
                self.message = 'Waiting for party state.'
                self._wait(self.leave_poll_ms)
                return

            if not self._leave_dispatched and not self._needs_leave_party(GLOBAL_CACHE.Party):
                self._phase = 'validate'
            elif not self._leave_dispatched:
                GLOBAL_CACHE.Party.LeaveParty()
                self._leave_dispatched = True
                self.message = 'Leaving current party.'
                self._wait(self.leave_poll_ms)
                return
            elif self._party_settled_after_leave(GLOBAL_CACHE.Party):
                self._phase = 'validate'
                self.message = 'Current party left. Loading team.'
            elif monotonic() >= self._leave_deadline:
                self._finish(False, 'Load skipped: could not leave current party.')
                return
            else:
                self.message = 'Waiting to leave current party.'
                self._wait(self.leave_poll_ms)
                return

        if self._phase == 'validate':
            if not Map.IsOutpost():
                self._finish(False, 'Load skipped: current map is not an outpost.')
                return
            if not GLOBAL_CACHE.Party.IsPartyLeader():
                self._finish(False, 'Load skipped: current character is not party leader.')
                return

            capacity = _current_hero_slot_capacity()
            if capacity <= 0:
                self._finish(False, 'Load skipped: there is no available hero slot in this party.')
                return
            self.plan = build_load_plan(
                self.team,
                self.templates,
                max_heroes=capacity,
                hero_names=self.hero_names,
            )
            if not self.plan.slots:
                self._finish(False, 'Load skipped: selected team has no non-empty hero slots.')
                return

            if self.clear_existing:
                GLOBAL_CACHE.Party.Heroes.KickAllHeroes()
                self.message = 'Clearing current heroes.'
                self._phase = 'add'
                self._wait(self.post_kick_wait_ms)
                return

            self._phase = 'add'
            self.message = 'Adding heroes.'

        if self._phase == 'add':
            if self._add_index >= len(self.plan.slots):
                self._phase = 'wait_after_add'
                self.message = 'Waiting for heroes to join.'
                self._wait(self.post_add_wait_ms)
                return
            slot = self.plan.slots[self._add_index]
            GLOBAL_CACHE.Party.Heroes.AddHero(int(slot.hero_id))
            self.added_hero_ids.append(int(slot.hero_id))
            self._add_index += 1
            self.message = f'Adding {slot.hero_name}.'
            self._wait(self.add_delay_ms)
            return

        if self._phase == 'wait_after_add':
            existing = current_hero_ids(party_api=GLOBAL_CACHE.Party)
            self.missing_hero_ids = [slot.hero_id for slot in self.plan.slots if slot.hero_id not in existing]
            self._phase = 'behavior'
            self.message = 'Applying hero behavior.'

        if self._phase == 'behavior':
            while self._behavior_index < len(self.plan.slots):
                slot = self.plan.slots[self._behavior_index]
                self._behavior_index += 1
                if slot.behavior == HERO_BEHAVIOR_DONT_CHANGE:
                    continue
                position = hero_party_index_one_based(slot.hero_id, party_api=GLOBAL_CACHE.Party)
                if position <= 0:
                    if slot.hero_id not in self.missing_hero_ids:
                        self.missing_hero_ids.append(slot.hero_id)
                    continue
                hero_agent_id = GLOBAL_CACHE.Party.Heroes.GetHeroAgentIDByPartyPosition(position)
                if int(hero_agent_id or 0) <= 0:
                    if slot.hero_id not in self.missing_hero_ids:
                        self.missing_hero_ids.append(slot.hero_id)
                    continue
                GLOBAL_CACHE.Party.Heroes.SetHeroBehavior(int(hero_agent_id), int(slot.behavior))
                self.applied_behavior_hero_ids.append(int(slot.hero_id))
                self.message = f'Applying behavior to {slot.hero_name}.'
                self._wait(100)
                return

            self._phase = 'templates'
            self.message = 'Applying templates.'

        if self._phase == 'templates':
            while self._template_index < len(self.plan.slots):
                slot = self.plan.slots[self._template_index]
                self._template_index += 1
                if not slot.template_code and not slot.clear_skillbar:
                    continue
                position = hero_party_index_one_based(slot.hero_id, party_api=GLOBAL_CACHE.Party)
                if position <= 0:
                    if slot.hero_id not in self.missing_hero_ids:
                        self.missing_hero_ids.append(slot.hero_id)
                    continue
                template_code = slot.template_code
                if slot.clear_skillbar:
                    template_code = _empty_skillbar_template_for_hero_position(position, party_api=GLOBAL_CACHE.Party)
                    if not template_code:
                        self.failed_template_slots.append(slot)
                        continue
                try:
                    GLOBAL_CACHE.SkillBar.LoadHeroSkillTemplate(position, template_code)
                except Exception:
                    self.failed_template_slots.append(slot)
                    continue
                if slot.clear_skillbar:
                    self.cleared_skillbar_hero_ids.append(int(slot.hero_id))
                    self.message = f'Clearing skill bar for {slot.hero_name}.'
                else:
                    self.applied_template_hero_ids.append(int(slot.hero_id))
                    self.message = f'Applying template to {slot.hero_name}.'
                self._wait(self.template_delay_ms)
                return

            self._finish(True, self._final_status())


def _party_component_list(party_api, method_name: str) -> tuple[list[Any], bool]:
    method = getattr(party_api, method_name, None)
    if not callable(method):
        return [], False
    try:
        values: Any = method()
    except Exception:
        return [], False
    if values is None:
        return [], True
    try:
        return list(values), True
    except Exception:
        return [], False


def snapshot_mixed_party(
    *,
    map_api=None,
    party_api=None,
    local_login_number: int | None = None,
) -> MixedPartySnapshot:
    if map_api is None:
        try:
            from Py4GWCoreLib.Map import Map

            map_api = Map
        except Exception:
            map_api = None
    if party_api is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            party_api = GLOBAL_CACHE.Party
        except Exception:
            party_api = None

    local_login = current_local_login_number() if local_login_number is None else int(local_login_number or 0)
    if party_api is None:
        return MixedPartySnapshot(local_login_number=local_login)

    players, players_ok = _party_component_list(party_api, 'GetPlayers')
    heroes, heroes_ok = _party_component_list(party_api, 'GetHeroes')
    henchmen, henchmen_ok = _party_component_list(party_api, 'GetHenchmen')
    others, others_ok = _party_component_list(party_api, 'GetOthers')
    components_ok = players_ok and heroes_ok and henchmen_ok and others_ok

    try:
        current_size = int(party_api.GetPartySize() or 0)
    except Exception:
        current_size = 0
        components_ok = False
    try:
        party_id = int(party_api.GetPartyID() or 0)
    except Exception:
        party_id = 0

    try:
        player_count = int(party_api.GetPlayerCount() or 0)
        hero_count = int(party_api.GetHeroCount() or 0)
        henchman_count = int(party_api.GetHenchmanCount() or 0)
        components_ok = components_ok and (
            player_count == len(players) and hero_count == len(heroes) and henchman_count == len(henchmen)
        )
    except Exception:
        player_count = len(players)
        hero_count = len(heroes)
        henchman_count = len(henchmen)
        components_ok = False

    components_ok = components_ok and current_size == len(players) + len(heroes) + len(henchmen) + len(others)
    try:
        party_loaded = bool(party_api.IsPartyLoaded())
    except Exception:
        party_loaded = bool(current_size > 0)
    components_ok = components_ok and party_loaded

    if map_api is not None:
        try:
            max_party_size = int(map_api.GetMaxPartySize() or 0)
        except Exception:
            max_party_size = 0
    else:
        max_party_size = 0

    local_player_count = sum(
        1 for player in players if int(getattr(player, 'login_number', 0) or 0) == local_login and local_login > 0
    )
    local_heroes = [hero for hero in heroes if hero_owner_category(hero, local_login) == 'local']
    remote_heroes = [hero for hero in heroes if hero_owner_category(hero, local_login) == 'remote']
    unknown_heroes = [hero for hero in heroes if hero_owner_category(hero, local_login) == 'unknown']

    capacity = calculate_mixed_capacity(
        max_party_size,
        current_size,
        0,
        0,
        0,
    )
    capacity.local_player_count = local_player_count
    capacity.local_hero_count = len(local_heroes)
    capacity.remote_hero_count = len(remote_heroes)
    capacity.unknown_hero_count = len(unknown_heroes)
    capacity.henchman_count = len(henchmen)
    capacity.other_occupant_count = len(others)
    return MixedPartySnapshot(
        capacity=capacity,
        players=players,
        heroes=heroes,
        henchmen=henchmen,
        others=others,
        party_id=party_id,
        local_login_number=local_login,
        components_reconciled=components_ok,
        party_loaded=party_loaded,
    )


def _map_tuple_from_api(map_api) -> tuple[int, int, int, int] | None:
    if map_api is None:
        return None
    try:
        region_value = map_api.GetRegion()
        language_value = map_api.GetLanguage()
        region = int(region_value[0] if isinstance(region_value, (tuple, list)) else region_value or 0)
        language = int(language_value[0] if isinstance(language_value, (tuple, list)) else language_value or 0)
        return (
            int(map_api.GetMapID() or 0),
            region,
            int(map_api.GetDistrict() or 0),
            language,
        )
    except Exception:
        return None


def _map_tuple_from_account(account: Any) -> tuple[int, int, int, int] | None:
    map_data = getattr(getattr(account, 'AgentData', None), 'Map', None)
    if map_data is None:
        return None
    try:
        result = (
            int(getattr(map_data, 'MapID', 0) or 0),
            int(getattr(map_data, 'Region', 0) or 0),
            int(getattr(map_data, 'District', 0) or 0),
            int(getattr(map_data, 'Language', 0) or 0),
        )
    except Exception:
        return None
    return result if result[0] > 0 else None


def _account_email(account: Any) -> str:
    return str(getattr(account, 'AccountEmail', '') or '').strip()


def _account_character_name(account: Any) -> str:
    return str(getattr(getattr(account, 'AgentData', None), 'CharacterName', '') or '').strip()


def _account_login_number(account: Any) -> int:
    try:
        return int(getattr(getattr(account, 'AgentData', None), 'LoginNumber', 0) or 0)
    except Exception:
        return 0


def _account_agent_id(account: Any) -> int:
    try:
        return int(getattr(getattr(account, 'AgentData', None), 'AgentID', 0) or 0)
    except Exception:
        return 0


def _account_profession_label(account: Any) -> str:
    profession = getattr(getattr(account, 'AgentData', None), 'Profession', ())
    try:
        primary = int(profession[0] or 0) if len(profession) > 0 else 0
        secondary = int(profession[1] or 0) if len(profession) > 1 else 0
    except Exception:
        primary = 0
        secondary = 0
    return _profession_short_label(primary, secondary) or 'Unknown'


def _account_party_id(account: Any) -> int:
    try:
        return int(getattr(getattr(account, 'AgentPartyData', None), 'PartyID', 0) or 0)
    except Exception:
        return 0


def _account_party_position(account: Any) -> int:
    try:
        party_data = getattr(account, 'AgentPartyData', None)
        position = getattr(party_data, 'PartyPosition', None)
        return -1 if position is None else int(position)
    except Exception:
        return -1


def _account_is_party_leader(account: Any) -> bool:
    return bool(getattr(getattr(account, 'AgentPartyData', None), 'IsPartyLeader', False))


def _account_is_isolated(account: Any) -> bool:
    return bool(getattr(account, 'IsIsolated', False))


def _shared_memory_account_records(shared_memory) -> tuple[list[Any], list[Any]]:
    if shared_memory is None:
        return [], []
    try:
        active = list(shared_memory.GetAllAccountData(sort_results=True, include_isolated=True) or [])
    except TypeError:
        try:
            active = list(shared_memory.GetAllAccountData() or [])
        except Exception:
            active = []
    except Exception:
        active = []

    all_records = list(active)
    try:
        all_accounts = shared_memory.GetAllAccounts()
        raw_records = getattr(all_accounts, 'AccountData', [])
        all_records = [record for record in raw_records if bool(getattr(record, 'IsAccount', False))]
    except Exception:
        pass
    return active, all_records


def _party_player_position_and_login(
    account: Any,
    party_api,
    players: list[Any],
) -> tuple[int, int]:
    account_login = _account_login_number(account)
    account_agent = _account_agent_id(account)
    players_api = getattr(party_api, 'Players', None)
    for position, player in enumerate(players):
        login_number = int(getattr(player, 'login_number', 0) or 0)
        if login_number > 0 and login_number == account_login:
            return position, login_number
        if account_agent > 0 and players_api is not None:
            try:
                agent_id = int(players_api.GetAgentIDByLoginNumber(login_number) or 0)
            except Exception:
                agent_id = 0
            if agent_id > 0 and agent_id == account_agent:
                return position, login_number
    return -1, account_login


def _known_shared_party_peers(
    account: Any,
    active_accounts: list[Any],
    account_map: tuple[int, int, int, int] | None,
) -> list[Any]:
    """Return other active injected account records sharing this party/map."""
    party_id = _account_party_id(account)
    account_key = alt_account_identity_key(_account_email(account))
    if party_id <= 0 or account_map is None:
        return []
    peers: list[Any] = []
    for candidate in active_accounts:
        if not bool(getattr(candidate, 'IsAccount', False)) or not bool(getattr(candidate, 'IsSlotActive', True)):
            continue
        if alt_account_identity_key(_account_email(candidate)) == account_key:
            continue
        if _account_party_id(candidate) != party_id:
            continue
        if _map_tuple_from_account(candidate) != account_map:
            continue
        peers.append(candidate)
    return peers


def _map_fields(map_value: tuple[int, int, int, int] | None) -> tuple[int, int, int, int]:
    return map_value if map_value is not None else (0, 0, 0, 0)


def _party_state_map_signature(map_value: tuple[int, int, int, int] | None) -> str:
    return ','.join(str(int(value)) for value in _map_fields(map_value))


def _party_state_query_cache() -> dict[tuple[str, str], dict[str, Any]]:
    """Return the per-client PartyStateQuery reply cache owned by GLOBAL_CACHE."""
    try:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
    except Exception:
        return {}

    cache = getattr(GLOBAL_CACHE, '_hero_team_party_state_query_cache', None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(GLOBAL_CACHE, '_hero_team_party_state_query_cache', cache)
    return cache


def _party_state_cache_key(sender_email: str, request_id: str) -> tuple[str, str]:
    return (str(sender_email or '').strip().casefold(), str(request_id or '').strip())


def reset_party_state_query(sender_email: str, request_id: str) -> None:
    _party_state_query_cache().pop(_party_state_cache_key(sender_email, request_id), None)


def get_party_state_query(sender_email: str, request_id: str) -> dict[str, Any] | None:
    return _party_state_query_cache().get(_party_state_cache_key(sender_email, request_id))


def new_party_state_query_id() -> str:
    """Create a unique text correlation ID that fits one ExtraData field."""
    return uuid4().hex


def _party_state_reply_int(reply: dict[str, Any], key: str, default: int = -1) -> int:
    try:
        return int(reply.get(key, default))
    except (TypeError, ValueError):
        return int(default)


def _party_state_reply_bool(reply: dict[str, Any], key: str) -> bool | None:
    value = reply.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip() in {'0', '1'}:
        return value.strip() == '1'
    return None


def validate_party_state_reply(
    reply: dict[str, Any] | None,
    *,
    request_id: str,
    expected_sender_email: str,
    expected_receiver_email: str,
    expected_character_name: str,
    expected_map: tuple[int, int, int, int] | None,
    sent_at: float,
    now: float | None = None,
) -> tuple[str, str]:
    """Classify one cached reply without treating malformed data as safe."""
    if not isinstance(reply, dict):
        return 'failure', 'No authoritative party-state reply was received.'

    if str(reply.get('request_id', '')).strip() != str(request_id or '').strip():
        return 'failure', 'Party-state reply correlation ID did not match the request.'
    if str(reply.get('sender_email', '')).strip().casefold() != str(expected_sender_email or '').strip().casefold():
        return 'failure', 'Party-state reply came from an unexpected account.'
    if str(reply.get('receiver_email', '')).strip().casefold() != str(expected_receiver_email or '').strip().casefold():
        return 'failure', 'Party-state reply was addressed to an unexpected account.'
    if str(reply.get('mode', '')).strip() != PARTY_STATE_QUERY_REPLY:
        return 'failure', 'Party-state reply used an unexpected response mode.'

    received_at = reply.get('received_at')
    try:
        received_at_value = float(str(received_at if received_at is not None else '').strip())
    except (TypeError, ValueError):
        return 'failure', 'Party-state reply has no valid receipt timestamp.'
    if _party_state_reply_int(reply, 'message_timestamp', 0) <= 0:
        return 'failure', 'Party-state reply has no valid message timestamp.'
    current_time = monotonic() if now is None else float(now)
    if received_at_value < float(sent_at) or received_at_value > current_time + 0.5:
        return 'failure', 'Party-state reply is stale or has an invalid timestamp.'

    character_name = str(reply.get('character_name', '') or '').strip()
    expected_name = str(expected_character_name or '').strip()
    if not character_name or (expected_name and character_name.casefold() != expected_name.casefold()):
        return 'failure', 'Party-state reply character identity did not match the configured account.'

    reported_map = reply.get('map_signature')
    if not isinstance(reported_map, tuple) or len(reported_map) != 4:
        return 'failure', 'Party-state reply has no valid map signature.'
    try:
        reported_map_tuple = tuple(int(value) for value in reported_map)
        expected_map_tuple = tuple(int(value) for value in expected_map) if expected_map is not None else None
    except (TypeError, ValueError):
        return 'failure', 'Party-state reply has no valid map signature.'
    if expected_map_tuple is None or reported_map_tuple != expected_map_tuple:
        return 'failure', 'Alt party-state reply is not from the expected map and district.'

    loaded = _party_state_reply_bool(reply, 'is_loaded')
    leader = _party_state_reply_bool(reply, 'is_party_leader')
    if loaded is not True:
        return 'failure', 'Alt party-state reply is not fully loaded.'
    if leader is not True:
        return 'incompatible_party', 'Alt is not the leader of its current party.'

    party_size = _party_state_reply_int(reply, 'party_size')
    player_count = _party_state_reply_int(reply, 'player_count')
    hero_count = _party_state_reply_int(reply, 'hero_count')
    henchman_count = _party_state_reply_int(reply, 'henchman_count')
    other_count = _party_state_reply_int(reply, 'other_count')
    party_id = _party_state_reply_int(reply, 'party_id')
    party_position = _party_state_reply_int(reply, 'party_position')
    values = (party_size, player_count, hero_count, henchman_count, other_count, party_id, party_position)
    if any(value < 0 for value in values):
        return 'failure', 'Alt party-state reply contains malformed counts or identity.'
    if party_id <= 0:
        return 'failure', 'Alt party-state reply has no valid party identity.'
    if party_size != player_count + hero_count + henchman_count + other_count:
        return 'failure', 'Alt party-state components are inconsistent.'
    if (
        party_position != 0
        or party_size != 1
        or player_count != 1
        or hero_count != 0
        or henchman_count != 0
        or other_count != 0
    ):
        return 'incompatible_party', 'Alt is not solo; reciprocal invitation is blocked.'
    return 'ready', 'Authoritative PartyStateQuery verified the alt is solo.'


def _log_alt_resolution(
    status: AltAccountStatus,
    *,
    team: HeroTeamSetup,
    current_map: tuple[int, int, int, int] | None,
    local_party_id: int,
    local_party_size: int,
) -> None:
    local_map_id, local_region, local_district, local_language = _map_fields(current_map)
    _mixed_log(
        'AltResolution',
        (
            f'row={status.binding_index + 1} account={_masked_account_identity(status.account_email)} '
            f'char={status.character_name or "<none>"!r} active={int(status.is_active)} '
            f'stale={int(status.is_stale)} '
            f'local_map={local_map_id}/{local_region}/{local_district}/{local_language} '
            f'alt_map={status.map_id}/{status.map_region}/{status.map_district}/{status.map_language} '
            f'local_party_id={local_party_id} local_party_size={local_party_size} '
            f'alt_party_id={status.party_id} alt_party_position={status.remote_party_position} '
            f'alt_party_leader={int(status.is_party_leader)} '
            f'known_party_members={status.known_party_member_count} '
            f'in_local_party={int(status.in_current_party)} '
            f'classification={status.status} party_state={status.party_state} '
            f'evidence={status.party_evidence or "none"}'
        ),
        key=('team', id(team), 'row', status.binding_index),
        message_type='Warning' if status.status not in {'ready', 'in_party', 'disabled'} else 'Info',
    )


def _status_for_binding_error(
    binding_index: int,
    binding: AltAccountBinding,
    status: str,
    message: str,
) -> AltAccountStatus:
    return AltAccountStatus(
        binding_index=binding_index,
        account_email=str(binding.account_email or '').strip(),
        display_name=str(binding.alias or binding.account_email or '').strip(),
        status=status,
        status_message=message,
        expected_character_matches=True,
    )


def active_alt_account_choices(*, player_api=None, shared_memory=None) -> list[AltAccountStatus]:
    """Return selectable active accounts using the existing shared-memory discovery surface."""
    if player_api is None:
        try:
            from Py4GWCoreLib.Player import Player

            player_api = Player
        except Exception:
            player_api = None
    if shared_memory is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            shared_memory = GLOBAL_CACHE.ShMem
        except Exception:
            shared_memory = None

    try:
        local_email = str(player_api.GetAccountEmail() or '').strip() if player_api is not None else ''
    except Exception:
        local_email = ''
    local_key = alt_account_identity_key(local_email)
    active, _all_records = _shared_memory_account_records(shared_memory)
    choices: list[AltAccountStatus] = []
    seen: set[str] = set()
    for account in active:
        email = _account_email(account)
        key = alt_account_identity_key(email)
        if not key or key == local_key or key in seen:
            continue
        seen.add(key)
        character_name = _account_character_name(account)
        isolated = _account_is_isolated(account)
        choices.append(
            AltAccountStatus(
                binding_index=-1,
                account_email=email,
                display_name=character_name or email,
                character_name=character_name,
                profession_label=_account_profession_label(account),
                status='isolated' if isolated else 'active',
                status_message='Active but isolated.' if isolated else 'Active.',
                is_active=True,
                is_stale=False,
                login_number=_account_login_number(account),
                agent_id=_account_agent_id(account),
                party_id=_account_party_id(account),
                party_position=_account_party_position(account),
            )
        )
    return choices


def resolve_alt_account_statuses(
    team: HeroTeamSetup,
    *,
    party_api=None,
    map_api=None,
    player_api=None,
    shared_memory=None,
    snapshot: MixedPartySnapshot | None = None,
    local_account_email: str = '',
) -> list[AltAccountStatus]:
    """Resolve configured alt rows without changing their persisted bindings."""
    if player_api is None:
        try:
            from Py4GWCoreLib.Player import Player

            player_api = Player
        except Exception:
            player_api = None
    if shared_memory is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            shared_memory = GLOBAL_CACHE.ShMem
        except Exception:
            shared_memory = None
    if party_api is None and snapshot is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            party_api = GLOBAL_CACHE.Party
        except Exception:
            party_api = None
    if map_api is None:
        try:
            from Py4GWCoreLib.Map import Map

            map_api = Map
        except Exception:
            map_api = None
    if snapshot is None:
        snapshot = snapshot_mixed_party(map_api=map_api, party_api=party_api)

    if not local_account_email:
        try:
            local_account_email = str(player_api.GetAccountEmail() or '').strip() if player_api is not None else ''
        except Exception:
            local_account_email = ''
    local_key = alt_account_identity_key(local_account_email)
    duplicate_indices = duplicate_alt_binding_indices(team, local_account_email)
    active, all_records = _shared_memory_account_records(shared_memory)
    current_map = _map_tuple_from_api(map_api)
    current_party_id = int(snapshot.party_id or 0)
    current_party_size = int(snapshot.capacity.current_party_size or 0)
    statuses: list[AltAccountStatus] = []

    def append_status(status: AltAccountStatus) -> None:
        statuses.append(status)
        _log_alt_resolution(
            status,
            team=team,
            current_map=current_map,
            local_party_id=current_party_id,
            local_party_size=current_party_size,
        )

    for binding_index, binding in enumerate(team.alt_members):
        email = str(binding.account_email or '').strip()
        key = alt_account_identity_key(email)
        if not binding.enabled:
            append_status(_status_for_binding_error(binding_index, binding, 'disabled', 'Disabled for this team.'))
            continue
        if not key:
            append_status(
                _status_for_binding_error(binding_index, binding, 'invalid', 'No account email is configured.')
            )
            continue
        if key == local_key:
            append_status(
                _status_for_binding_error(
                    binding_index,
                    binding,
                    'local_account',
                    'This is the local account; choose another account.',
                )
            )
            continue
        if binding_index in duplicate_indices:
            append_status(
                _status_for_binding_error(
                    binding_index,
                    binding,
                    'duplicate',
                    'Duplicate account identity; correct the saved team before loading.',
                )
            )
            continue

        active_candidates = [account for account in active if alt_account_identity_key(_account_email(account)) == key]
        all_candidates = [
            account for account in all_records if alt_account_identity_key(_account_email(account)) == key
        ]
        if len(active_candidates) > 1:
            append_status(
                _status_for_binding_error(
                    binding_index,
                    binding,
                    'ambiguous',
                    'More than one active shared-memory record matches this account email.',
                )
            )
            continue
        if not active_candidates:
            stale = bool(all_candidates)
            stale_status = _status_for_binding_error(
                binding_index,
                binding,
                'stale' if stale else 'offline',
                'Account data is stale.' if stale else 'Account is offline or not discovered.',
            )
            stale_status.is_stale = stale
            append_status(stale_status)
            continue

        account = active_candidates[0]
        resolved_email = _account_email(account) or email
        character_name = _account_character_name(account)
        account_map = _map_tuple_from_account(account)
        login_number = _account_login_number(account)
        agent_id = _account_agent_id(account)
        local_party_position, matched_login = _party_player_position_and_login(account, party_api, snapshot.players)
        in_current_party = local_party_position >= 0
        account_party_id = _account_party_id(account)
        account_party_position = _account_party_position(account)
        account_party_leader = _account_is_party_leader(account)
        known_party_peers = _known_shared_party_peers(account, active, account_map)
        same_map = current_map is not None and account_map is not None and current_map == account_map
        expected = str(binding.expected_character_name or '').strip()
        expected_matches = not expected or expected.casefold() == character_name.casefold()
        account_map_id, account_region, account_district, account_language = _map_fields(account_map)
        status = AltAccountStatus(
            binding_index=binding_index,
            account_email=resolved_email,
            display_name=str(binding.alias or character_name or email).strip(),
            character_name=character_name,
            profession_label=_account_profession_label(account),
            status='active',
            status_message='Active.',
            is_active=True,
            is_stale=False,
            same_map=same_map,
            in_current_party=in_current_party,
            expected_character_matches=expected_matches,
            party_id=account_party_id,
            party_position=local_party_position,
            remote_party_position=account_party_position,
            login_number=matched_login or login_number,
            agent_id=agent_id,
            map_id=account_map_id,
            map_region=account_region,
            map_district=account_district,
            map_language=account_language,
            known_party_member_count=1 + len(known_party_peers) if account_party_id > 0 else 0,
            is_party_leader=account_party_leader,
        )
        if not character_name:
            status.status = 'unresolved'
            status.status_message = 'Active account has no current character identity.'
            status.party_state = 'unresolved'
            status.party_evidence = 'character identity unavailable'
        elif not expected_matches:
            status.status = 'wrong_character'
            status.status_message = f'Wrong character: expected {expected}, found {character_name}.'
            status.party_state = 'wrong_character'
            status.party_evidence = 'expected character does not match'
        elif in_current_party:
            status.status = 'in_party'
            status.status_message = 'Already in the current party.'
            status.party_state = 'in_party'
            status.party_evidence = 'live local Party.GetPlayers membership'
        elif not same_map:
            status.status = 'different_map'
            status.status_message = 'Account is active but not on the local map.'
            status.party_state = 'different_map'
            status.party_evidence = 'full map/district/language signature differs'
        elif _account_is_isolated(account):
            status.status = 'isolated'
            status.status_message = 'Account is isolated and cannot be coordinated safely.'
            status.party_state = 'isolated'
            status.party_evidence = 'shared-memory isolation flag'
        elif account_party_position < 0:
            status.status = 'query_required'
            status.status_message = 'Party state requires an authoritative query before invitation.'
            status.party_state = 'unknown'
            status.party_evidence = 'shared-memory party position is unavailable; PartyStateQuery required'
        elif current_party_id <= 0:
            status.status = 'ambiguous_party'
            status.status_message = 'Local party identity is unavailable; mixed loading is blocked.'
            status.party_state = 'ambiguous'
            status.party_evidence = 'local Party.GetPartyID returned no valid party ID'
        elif account_party_position == 0 and not account_party_leader:
            status.status = 'ambiguous_party'
            status.status_message = 'Account party metadata is contradictory; mixed loading is blocked.'
            status.party_state = 'ambiguous'
            status.party_evidence = 'zero party position without party-leader state'
        elif current_party_id > 0 and account_party_id == current_party_id:
            status.status = 'ambiguous_party'
            status.status_message = (
                'Shared-memory party matches the local party, but live membership could not be verified.'
            )
            status.party_state = 'ambiguous'
            status.party_evidence = 'party ID matches local party without live player membership'
        elif account_party_position > 0 or known_party_peers:
            status.status = 'incompatible_party'
            status.status_message = 'Account is already in a different party.'
            status.party_state = 'other_party'
            status.party_evidence = (
                'party position is not zero'
                if account_party_position > 0
                else 'another active shared-memory account shares the party ID and map'
            )
        else:
            status.status = 'query_required'
            status.status_message = 'Party state requires an authoritative query before invitation.'
            status.party_state = 'unknown'
            status.party_evidence = 'shared-memory metadata is insufficient; PartyStateQuery required'
        append_status(status)
    return statuses


def build_mixed_team_preflight(
    config: HeroTeamConfig,
    team_id: str | None = None,
    *,
    map_api=None,
    party_api=None,
    player_api=None,
    shared_memory=None,
) -> HeroTeamLoadPreflight:
    preflight = HeroTeamLoadPreflight(mixed_mode=True)
    team = get_team(config, team_id)
    if team is None:
        preflight.blocking_messages.append('Load skipped: no team selected.')
        return preflight

    if map_api is None:
        try:
            from Py4GWCoreLib.Map import Map

            map_api = Map
        except Exception:
            map_api = None
    if party_api is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            party_api = GLOBAL_CACHE.Party
        except Exception:
            party_api = None
    if player_api is None:
        try:
            from Py4GWCoreLib.Player import Player

            player_api = Player
        except Exception:
            player_api = None
    if shared_memory is None:
        try:
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            shared_memory = GLOBAL_CACHE.ShMem
        except Exception:
            shared_memory = None

    try:
        local_email = str(player_api.GetAccountEmail() or '').strip() if player_api is not None else ''
    except Exception:
        local_email = ''
    try:
        local_login = int(player_api.GetLoginNumber() or 0) if player_api is not None else 0
    except Exception:
        local_login = 0
    if not local_email:
        preflight.blocking_messages.append('Load skipped: local account identity could not be resolved.')
    if local_login <= 0:
        preflight.blocking_messages.append('Load skipped: local player login identity could not be resolved.')

    snapshot = snapshot_mixed_party(
        map_api=map_api,
        party_api=party_api,
        local_login_number=local_login,
    )
    target_local_hero_ids = {int(slot.hero_id) for slot in normalize_slots(team.slots) if int(slot.hero_id) > 0}
    _mixed_log(
        'MixedPreflight',
        (
            f'start team={team.name!r} alts={sum(1 for binding in team.alt_members if binding.enabled)} '
            f'hero_targets={len(target_local_hero_ids)} '
            f'party={snapshot.capacity.current_party_size}/{snapshot.capacity.max_party_size}'
        ),
        key=('team', team.team_id, 'preflight-start'),
    )
    preflight.alt_statuses = resolve_alt_account_statuses(
        team,
        party_api=party_api,
        map_api=map_api,
        player_api=player_api,
        shared_memory=shared_memory,
        snapshot=snapshot,
        local_account_email=local_email,
    )
    preflight.blocking_messages.extend(validate_alt_bindings(team, local_email))

    for status in preflight.alt_statuses:
        if status.status in {'disabled', 'ready', 'query_required', 'in_party'}:
            continue
        preflight.blocking_messages.append(
            f'Alt account row {status.binding_index + 1}: {status.status_message or status.status}.'
        )

    hero_preflight = build_load_preflight(
        config,
        team_id,
        include_runtime=False,
        leave_party_first=False,
        clear_existing=False,
    )
    preflight.plan = hero_preflight.plan
    preflight.row_warnings = hero_preflight.row_warnings
    preflight.warnings = list(hero_preflight.warnings)
    preflight.max_heroes = HERO_SLOT_COUNT

    if map_api is None:
        preflight.blocking_messages.append('Load skipped: could not verify current map.')
    else:
        try:
            if not map_api.IsOutpost():
                preflight.blocking_messages.append('Load skipped: current map is not an outpost.')
        except Exception:
            preflight.blocking_messages.append('Load skipped: could not verify current map.')
    if party_api is None:
        preflight.blocking_messages.append('Load skipped: could not access the current party.')
    else:
        try:
            if not party_api.IsPartyLeader():
                preflight.blocking_messages.append('Load skipped: current character is not party leader.')
        except Exception:
            preflight.blocking_messages.append('Load skipped: could not verify party leader.')

    if not snapshot.party_loaded:
        preflight.blocking_messages.append('Load skipped: current party is not fully loaded.')
    if not snapshot.components_reconciled:
        preflight.blocking_messages.append('Load skipped: current party components are inconsistent.')
    if snapshot.capacity.max_party_size <= 0:
        preflight.blocking_messages.append('Load skipped: current map party capacity is unavailable.')
    if snapshot.party_id <= 0:
        preflight.blocking_messages.append('Load skipped: current party identity is unavailable.')
    if snapshot.capacity.current_party_size <= 0:
        preflight.blocking_messages.append('Load skipped: current party size is unavailable.')
    if snapshot.capacity.local_player_count != 1:
        preflight.blocking_messages.append('Load skipped: local player is not uniquely present in the party.')

    enabled_statuses = [status for status in preflight.alt_statuses if status.status != 'disabled']
    present_alt_statuses = [status for status in enabled_statuses if status.in_current_party]
    present_party_positions = [int(status.party_position) for status in present_alt_statuses]
    present_party_logins = [int(status.login_number) for status in present_alt_statuses]
    present_alt_count = len(set(present_party_positions))
    missing_alt_count = max(0, len(enabled_statuses) - present_alt_count)
    if (
        len(set(present_party_positions)) != len(present_party_positions)
        or len(set(present_party_logins)) != len(present_party_logins)
        or any(login_number <= 0 or login_number == local_login for login_number in present_party_logins)
    ):
        preflight.blocking_messages.append(
            'Load skipped: configured alt identities do not map uniquely to non-local party players.'
        )

    target_local_hero_ids = {int(slot.hero_id) for slot in preflight.plan.slots if int(slot.hero_id) > 0}
    local_hero_members = current_local_hero_members(party_api, local_login)
    local_hero_ids = current_local_hero_ids(party_api, local_login)
    unmanaged_hero_count = snapshot.capacity.remote_hero_count + snapshot.capacity.unknown_hero_count

    local_heroes_to_remove = len(local_hero_members)
    local_heroes_to_add = len(target_local_hero_ids)
    if unmanaged_hero_count > 0:
        if len(local_hero_members) != len(local_hero_ids) or not local_hero_ids.issubset(target_local_hero_ids):
            preflight.blocking_messages.append(
                'Load skipped: remote or unknown-owner heroes prevent a safe local hero replacement.'
            )
        local_heroes_to_remove = 0
        local_heroes_to_add = len(target_local_hero_ids - local_hero_ids)

    capacity = calculate_mixed_capacity(
        snapshot.capacity.max_party_size,
        snapshot.capacity.current_party_size,
        local_heroes_to_remove,
        missing_alt_count,
        len(target_local_hero_ids),
        local_heroes_to_add,
    )
    capacity.local_player_count = snapshot.capacity.local_player_count
    capacity.configured_alt_present_count = present_alt_count
    capacity.unmanaged_player_count = max(
        0,
        len(snapshot.players) - snapshot.capacity.local_player_count - present_alt_count,
    )
    capacity.local_hero_count = snapshot.capacity.local_hero_count
    capacity.remote_hero_count = snapshot.capacity.remote_hero_count
    capacity.unknown_hero_count = snapshot.capacity.unknown_hero_count
    capacity.henchman_count = snapshot.capacity.henchman_count
    capacity.other_occupant_count = snapshot.capacity.other_occupant_count
    preflight.capacity = capacity

    ownership_blocked = any(
        'remote or unknown-owner heroes prevent a safe local hero replacement' in message
        for message in preflight.blocking_messages
    )
    _mixed_log(
        'Ownership',
        (
            f'team={team.name!r} local_heroes={capacity.local_hero_count} '
            f'protected_remote={capacity.remote_hero_count} unknown_owner={capacity.unknown_hero_count} '
            f'replacement={"blocked" if ownership_blocked else "safe"}'
        ),
        key=('team', team.team_id, 'ownership'),
        message_type='Warning' if ownership_blocked else 'Info',
    )
    _mixed_log(
        'Capacity',
        (
            f'team={team.name!r} current={capacity.current_party_size} '
            f'local_heroes={capacity.local_hero_count} remove_local={capacity.local_heroes_to_remove} '
            f'missing_alts={capacity.missing_alt_count} hero_targets={capacity.target_local_hero_count} '
            f'add_local={capacity.local_heroes_to_add} forecast={capacity.forecast_final_slots} '
            f'max={capacity.max_party_size}'
        ),
        key=('team', team.team_id, 'capacity'),
        message_type='Warning' if capacity.forecast_final_slots > capacity.max_party_size > 0 else 'Info',
    )

    if capacity.current_party_size > capacity.max_party_size:
        preflight.blocking_messages.append('Load skipped: current party already exceeds this map capacity.')
    if capacity.forecast_final_slots > capacity.max_party_size:
        preflight.blocking_messages.append(
            f'Load skipped: requested party would use {capacity.forecast_final_slots} '
            f'of {capacity.max_party_size} available slots.'
        )
    if preflight.blocking_messages:
        _mixed_log(
            'MixedPreflight',
            f'blocked team={team.name!r} reason={" | ".join(preflight.blocking_messages)}',
            key=('team', team.team_id, 'preflight-result'),
            message_type='Warning',
        )
    else:
        _mixed_log(
            'MixedPreflight',
            f'passed team={team.name!r} party={capacity.current_party_size}/{capacity.max_party_size}',
            key=('team', team.team_id, 'preflight-result'),
        )
    return preflight


class MixedHeroTeamApplyOperation:
    """Apply a team without leaving the party or claiming unmanaged occupants."""

    def __init__(
        self,
        config: HeroTeamConfig,
        team_id: str | None = None,
        *,
        clear_existing: bool = True,
        invite_timeout_ms: int = 5000,
        poll_ms: int = 250,
        hero_add_delay_ms: int = 250,
        post_clear_wait_ms: int = 500,
        template_delay_ms: int = 500,
    ) -> None:
        team = get_team(config, team_id)
        if team is None:
            raise ValueError('No team selected.')
        self.config = deepcopy(config)
        self.team = deepcopy(team)
        self.templates = deepcopy(self.config.templates)
        self.hero_names = dict(self.config.hero_names)
        self.clear_existing = bool(clear_existing)
        self.invite_timeout_ms = max(500, int(invite_timeout_ms))
        self.poll_ms = max(50, int(poll_ms))
        self.hero_add_delay_ms = max(0, int(hero_add_delay_ms))
        self.post_clear_wait_ms = max(0, int(post_clear_wait_ms))
        self.template_delay_ms = max(0, int(template_delay_ms))

        self.plan = HeroTeamLoadPlan()
        self.preflight = HeroTeamLoadPreflight(mixed_mode=True)
        self.state = 'pending'
        self.message = 'Pending.'
        self.done = False
        self.success = False
        self.added_hero_ids: list[int] = []
        self.applied_template_hero_ids: list[int] = []
        self.cleared_skillbar_hero_ids: list[int] = []
        self.applied_behavior_hero_ids: list[int] = []

        self._phase = 'validate'
        self._next_at = 0.0
        self._invite_indices: list[int] = []
        self._invite_cursor = 0
        self._invite_binding_index = -1
        self._invite_deadline = 0.0
        self._party_query_binding_index = -1
        self._party_query_id = ''
        self._party_query_sent_at = 0.0
        self._party_query_deadline = 0.0
        self._invite_sent_at = 0.0
        self._guard_result_received = False
        self._joined_observed = False
        self._runtime_alt_states: dict[int, dict[str, Any]] = {}
        self._joined_binding_indices: set[int] = set()
        self._clear_deadline = 0.0
        self._clear_dispatched = False
        self._hero_add_slots: list[ResolvedHeroSlot] = []
        self._hero_add_index = 0
        self._hero_add_target_id = 0
        self._hero_add_deadline = 0.0
        self._behavior_index = 0
        self._template_index = 0
        self._operation_log_key = id(self)
        self._last_logged_phase = ''
        self._operation_start_logged = False

    def _wait(self, ms: int) -> None:
        self._next_at = monotonic() + (max(0, int(ms)) / 1000.0)

    def _ready(self) -> bool:
        return monotonic() >= self._next_at

    def _log_phase_transition(self) -> None:
        phase = str(self._phase)
        if phase == self._last_logged_phase:
            return
        self._last_logged_phase = phase
        _mixed_log(
            'MixedLoad',
            f'team={self.team.name!r} phase={phase}',
            key=('operation', self._operation_log_key, 'phase', phase),
        )

    def _log_operation_start(self, preflight: HeroTeamLoadPreflight) -> None:
        if self._operation_start_logged:
            return
        capacity = preflight.capacity
        current_size = int(capacity.current_party_size) if capacity is not None else 0
        max_size = int(capacity.max_party_size) if capacity is not None else 0
        hero_target_count = len(self._target_ids())
        alt_count = sum(1 for binding in self.team.alt_members if binding.enabled)
        _mixed_log(
            'MixedLoad',
            (
                f'Starting team {self.team.name!r} alts={alt_count} '
                f'hero_targets={hero_target_count} party={current_size}/{max_size}'
            ),
            key=('operation', self._operation_log_key, 'start'),
        )
        self._operation_start_logged = True

    def _finish(self, success: bool, message: str) -> None:
        self.done = True
        self.success = bool(success)
        self.state = 'done' if success else 'failed'
        self.message = str(message)
        _mixed_log(
            'MixedLoad',
            f'{"completed" if success else "failed"} team={self.team.name!r} reason={self.message}',
            key=('operation', self._operation_log_key, 'finish'),
            message_type='Success' if success else 'Error',
        )

    def _refresh_preflight(self) -> HeroTeamLoadPreflight:
        self.preflight = build_mixed_team_preflight(self.config, self.team.team_id)
        if self._joined_binding_indices:
            status_by_index = {status.binding_index: status for status in self.preflight.alt_statuses}
            for binding_index in sorted(self._joined_binding_indices):
                status = status_by_index.get(binding_index)
                if status is None or not status.in_current_party:
                    _mixed_log(
                        'Invite',
                        (
                            f'unexpected state change row={binding_index + 1}: '
                            'configured alt left or changed state during the load'
                        ),
                        key=('operation', self._operation_log_key, 'alt-state', binding_index),
                        message_type='Warning',
                    )
                    self.preflight.blocking_messages.append(
                        f'Alt account row {binding_index + 1} left or changed state during the load.'
                    )
        self.plan = deepcopy(self.preflight.plan)
        self._apply_runtime_alt_states()
        return self.preflight

    def _status_by_index(self, binding_index: int) -> AltAccountStatus | None:
        return next(
            (status for status in self.preflight.alt_statuses if status.binding_index == int(binding_index)),
            None,
        )

    def _apply_runtime_alt_states(self) -> None:
        for binding_index, runtime in self._runtime_alt_states.items():
            status = self._status_by_index(binding_index)
            if status is None:
                continue

            status.party_state_query_id = str(runtime.get('query_id', '') or '')
            status.guard_result = str(runtime.get('guard_result', '') or '')
            reply = runtime.get('reply')
            if isinstance(reply, dict):
                status.party_state_query_received_at = float(reply.get('received_at', 0.0) or 0.0)
                status.party_id = _party_state_reply_int(reply, 'party_id', status.party_id)
                status.remote_party_position = _party_state_reply_int(
                    reply,
                    'party_position',
                )
                status.is_party_leader = bool(reply.get('is_party_leader'))
                status.known_party_member_count = max(
                    0,
                    _party_state_reply_int(reply, 'party_size', status.known_party_member_count),
                )
                map_signature = reply.get('map_signature')
                if isinstance(map_signature, tuple) and len(map_signature) == 4:
                    status.map_id, status.map_region, status.map_district, status.map_language = (
                        int(value) for value in map_signature
                    )

            phase = str(runtime.get('phase', '') or '')
            if phase == 'checking_party':
                status.status = 'checking_party'
                status.status_message = 'Checking authoritative local party state.'
                status.party_state = 'checking'
                status.party_evidence = 'PartyStateQuery request is pending'
            elif phase == 'verified_solo':
                status.status = 'ready'
                status.status_message = 'Verified solo by authoritative PartyStateQuery.'
                status.party_state = 'solo'
                status.party_evidence = 'authoritative local Party API reply'
            elif phase == 'invite_waiting':
                status.status = 'invite_waiting'
                status.status_message = 'Invite sent; waiting for observed party membership.'
                status.party_state = 'invite_pending'
                status.party_evidence = 'main invite and guarded reciprocal invite dispatched'
            elif phase == 'party_changed_before_invite':
                status.status = 'party_changed_before_invite'
                status.status_message = 'Party changed before the reciprocal invite; no reciprocal invite was sent.'
                status.party_state = 'changed'
                status.party_evidence = 'alt-side immediate PartyState guard failed'
            elif phase == 'incompatible_party':
                status.status = 'incompatible_party'
                status.status_message = str(
                    runtime.get('message', '') or 'Alt is not solo; reciprocal invitation is blocked.'
                )
                status.party_state = 'other_party'
                status.party_evidence = 'authoritative local PartyStateQuery reply'
            elif phase == 'joined':
                status.status = 'joined'
                status.status_message = 'Joined the main account party.'
                status.party_state = 'in_party'
                status.party_evidence = 'live local Party.GetPlayers membership'
                status.in_current_party = True
            elif phase == 'timeout':
                status.status = 'timeout'
                status.status_message = 'Timed out waiting for query, guard result, or party membership.'
                status.party_state = 'unknown'
                status.party_evidence = 'no complete correlated handshake'
            elif phase == 'failure':
                status.status = 'failure'
                status.status_message = str(runtime.get('message', '') or 'Party handshake failed.')
                status.party_state = 'unknown'
                status.party_evidence = 'correlated handshake failure'

    def _set_runtime_alt_state(self, binding_index: int, phase: str, **values: Any) -> None:
        runtime = self._runtime_alt_states.setdefault(int(binding_index), {})
        runtime['phase'] = str(phase)
        runtime.update(values)
        self._apply_runtime_alt_states()

    def _target_ids(self) -> set[int]:
        return {int(slot.hero_id) for slot in self.plan.slots if int(slot.hero_id) > 0}

    def _owner_safe_position(self, hero_id: int, party_api) -> int:
        local_login = current_local_login_number()
        position = local_hero_party_index_one_based(hero_id, party_api, local_login)
        if position <= 0:
            return 0
        heroes = current_party_hero_members(party_api)
        if position > len(heroes):
            return 0
        member = heroes[position - 1]
        if hero_id_from_member(member) != int(hero_id) or hero_owner_category(member, local_login) != 'local':
            return 0
        return position

    def _begin_party_query(self, status: AltAccountStatus) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
        from Py4GWCoreLib.Player import Player
        from Py4GWCoreLib.Map import Map
        from Py4GWCoreLib.enums_src.Multiboxing_enums import SharedCommandType

        target_email = str(status.account_email or '').strip()
        sender_email = str(Player.GetAccountEmail() or '').strip()
        target_name = str(status.character_name or '').strip()
        map_signature = _map_tuple_from_api(Map)
        if not target_email or not sender_email or not target_name or map_signature is None:
            self._set_runtime_alt_state(
                status.binding_index,
                'failure',
                message='Party-state query identity or map could not be resolved.',
            )
            self._finish(False, 'Mixed load failed: party-state query identity or map could not be resolved.')
            return

        request_id = new_party_state_query_id()
        reset_party_state_query(target_email, request_id)
        sent_at = monotonic()
        try:
            message_index = GLOBAL_CACHE.ShMem.SendMessage(
                sender_email,
                target_email,
                SharedCommandType.PartyStateQuery,
                (0, 0, 0, 0),
                (
                    PARTY_STATE_QUERY_REQUEST,
                    request_id,
                    target_name,
                    _party_state_map_signature(map_signature),
                ),
            )
        except Exception as exc:
            self._set_runtime_alt_state(
                status.binding_index,
                'failure',
                message=f'Party-state query could not be queued: {exc}',
            )
            self._finish(False, f'Mixed load failed while querying {target_name}: {exc}')
            return

        if int(message_index) < 0:
            self._set_runtime_alt_state(
                status.binding_index,
                'failure',
                message='Party-state query could not be queued.',
            )
            self._finish(False, f'Mixed load failed: party-state query could not be sent to {target_name}.')
            return

        self._party_query_binding_index = int(status.binding_index)
        self._party_query_id = request_id
        self._party_query_sent_at = sent_at
        self._party_query_deadline = sent_at + (self.invite_timeout_ms / 1000.0)
        self._set_runtime_alt_state(
            status.binding_index,
            'checking_party',
            query_id=request_id,
        )
        _mixed_log(
            'PartyStateQuery',
            (
                f'sent row={status.binding_index + 1} account={_masked_account_identity(target_email)} '
                f'char={target_name!r} request={request_id!r} message_index={int(message_index)}'
            ),
            key=('operation', self._operation_log_key, 'query-sent', status.binding_index),
        )
        self._phase = 'wait_party_query'
        self.message = f'Checking party state for {target_name}.'
        self._wait(self.poll_ms)

    def _tick_wait_party_query(self) -> None:
        from Py4GWCoreLib.Map import Map
        from Py4GWCoreLib.Player import Player

        status = self._status_by_index(self._party_query_binding_index)
        if status is None:
            self._finish(False, 'Mixed load failed: queried alt account row disappeared.')
            return

        reply = get_party_state_query(status.account_email, self._party_query_id)
        if reply is None:
            if monotonic() >= self._party_query_deadline:
                self._set_runtime_alt_state(status.binding_index, 'timeout', query_id=self._party_query_id)
                _mixed_log(
                    'PartyStateQuery',
                    (
                        f'timeout row={status.binding_index + 1} '
                        f'request={self._party_query_id!r} no authoritative reply'
                    ),
                    key=('operation', self._operation_log_key, 'query-timeout', status.binding_index),
                    message_type='Warning',
                )
                self._finish(False, 'Mixed load failed: authoritative alt party-state query timed out.')
                return
            self.message = f'Checking party state for {status.character_name or status.account_email}.'
            self._wait(self.poll_ms)
            return

        expected_map = _map_tuple_from_api(Map)
        receiver_email = str(Player.GetAccountEmail() or '').strip()
        result, reason = validate_party_state_reply(
            reply,
            request_id=self._party_query_id,
            expected_sender_email=status.account_email,
            expected_receiver_email=receiver_email,
            expected_character_name=status.character_name,
            expected_map=expected_map,
            sent_at=self._party_query_sent_at,
        )
        _mixed_log(
            'PartyStateQuery',
            (
                f'received row={status.binding_index + 1} account={_masked_account_identity(status.account_email)} '
                f'request={self._party_query_id!r} result={result} reason={reason} '
                f'party={_party_state_reply_int(reply, "party_size", -1)} '
                f'players={_party_state_reply_int(reply, "player_count", -1)} '
                f'heroes={_party_state_reply_int(reply, "hero_count", -1)} '
                f'henchmen={_party_state_reply_int(reply, "henchman_count", -1)} '
                f'others={_party_state_reply_int(reply, "other_count", -1)}'
            ),
            key=('operation', self._operation_log_key, 'query-reply', status.binding_index),
            message_type='Warning' if result != 'ready' else 'Info',
        )
        if result == 'ready':
            self._set_runtime_alt_state(
                status.binding_index,
                'verified_solo',
                query_id=self._party_query_id,
                reply=reply,
            )
            status = self._status_by_index(status.binding_index) or status
            self._dispatch_invite(status)
            return

        phase = 'incompatible_party' if result == 'incompatible_party' else 'failure'
        self._set_runtime_alt_state(
            status.binding_index,
            phase,
            query_id=self._party_query_id,
            reply=reply,
            message=reason,
        )
        self._finish(
            False,
            f'Mixed load blocked for {status.character_name or status.account_email}: {reason}',
        )

    def _dispatch_invite(self, status: AltAccountStatus) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
        from Py4GWCoreLib.Player import Player
        from Py4GWCoreLib.Map import Map
        from Py4GWCoreLib.enums_src.Multiboxing_enums import SharedCommandType

        target_name = str(status.character_name or '').strip()
        target_email = str(status.account_email or '').strip()
        sender_email = str(Player.GetAccountEmail() or '').strip()
        query_id = str(self._party_query_id or '').strip()
        map_signature = _map_tuple_from_api(Map)
        _mixed_log(
            'Invite',
            (
                f'preparing row={status.binding_index + 1} char={target_name or "<none>"!r} '
                f'classification={status.status} query={query_id!r}'
            ),
            key=('operation', self._operation_log_key, 'invite-prepare', status.binding_index),
        )
        if not target_name or not target_email or not sender_email or not query_id or map_signature is None:
            self._finish(False, 'Mixed load failed: correlated invite identity or map could not be resolved.')
            return
        try:
            GLOBAL_CACHE.Party.Players.InvitePlayer(target_name)
            message_index = GLOBAL_CACHE.ShMem.SendMessage(
                sender_email,
                target_email,
                SharedCommandType.InviteToParty,
                (0, 0, 0, 0),
                (
                    PARTY_INVITE_GUARD,
                    query_id,
                    target_name,
                    _party_state_map_signature(map_signature),
                ),
            )
        except Exception as exc:
            self._finish(False, f'Mixed load failed while inviting {target_name}: {exc}')
            return
        if int(message_index) < 0:
            _mixed_log(
                'Invite',
                (
                    f'main invite was sent to {target_name!r}, but guarded command could not be queued '
                    f'query={query_id!r}'
                ),
                key=('operation', self._operation_log_key, 'guard-command-failed', status.binding_index),
                message_type='Warning',
            )
            self._finish(False, f'Mixed load failed: guarded invite command could not reach {target_name}.')
            return
        self._invite_binding_index = int(status.binding_index)
        self._invite_sent_at = monotonic()
        self._invite_deadline = monotonic() + (self.invite_timeout_ms / 1000.0)
        self._guard_result_received = False
        self._joined_observed = False
        self._set_runtime_alt_state(
            status.binding_index,
            'invite_waiting',
            query_id=query_id,
        )
        self._phase = 'wait_invite'
        _mixed_log(
            'Invite',
            (
                f'requested row={status.binding_index + 1} char={target_name!r} '
                f'shared_message_index={int(message_index)} query={query_id!r}'
            ),
            key=('operation', self._operation_log_key, 'invite-requested', status.binding_index),
        )
        _mixed_log(
            'Invite',
            f'waiting row={status.binding_index + 1} for guard result and observed local-party join',
            key=('operation', self._operation_log_key, 'invite-waiting', status.binding_index),
        )
        self.message = f'Invite sent to {target_name}; waiting for guarded reciprocal invite.'
        self._wait(self.poll_ms)

    def _read_guard_result(self, status: AltAccountStatus) -> tuple[str, str, dict[str, Any]] | None:
        reply = get_party_state_query(status.account_email, self._party_query_id)
        if reply is None or str(reply.get('mode', '') or '') != PARTY_STATE_GUARD_RESULT:
            return None
        from Py4GWCoreLib.Player import Player
        from Py4GWCoreLib.Map import Map

        expected_receiver = str(Player.GetAccountEmail() or '').strip().casefold()
        if str(reply.get('request_id', '') or '').strip() != self._party_query_id:
            return 'invalid', 'Guard result correlation ID did not match the request.', reply
        if str(reply.get('sender_email', '') or '').strip().casefold() != status.account_email.casefold():
            return 'invalid', 'Guard result came from an unexpected account.', reply
        if str(reply.get('receiver_email', '') or '').strip().casefold() != expected_receiver:
            return 'invalid', 'Guard result was addressed to an unexpected account.', reply
        if _party_state_reply_int(reply, 'message_timestamp', 0) <= 0:
            return 'invalid', 'Guard result has no valid message timestamp.', reply
        try:
            received_at = float(reply.get('received_at', 0.0))
        except (TypeError, ValueError):
            return 'invalid', 'Guard result has no valid receipt timestamp.', reply
        if received_at < self._invite_sent_at or received_at > monotonic() + 0.5:
            return 'invalid', 'Guard result is stale or has an invalid timestamp.', reply

        result = str(reply.get('result', '') or '').strip()
        if result.startswith('guard_failed:'):
            return 'failed', result, reply
        if result != 'reciprocal_invite_sent':
            return 'invalid', 'Guard result used an unexpected outcome.', reply

        expected_map = _map_tuple_from_api(Map)
        map_signature = reply.get('map_signature')
        if expected_map is None or not isinstance(map_signature, tuple) or tuple(map_signature) != tuple(expected_map):
            return 'invalid', 'Guard result is not from the current map and district.', reply
        party_size = _party_state_reply_int(reply, 'party_size', -1)
        player_count = _party_state_reply_int(reply, 'player_count', -1)
        hero_count = _party_state_reply_int(reply, 'hero_count', -1)
        henchman_count = _party_state_reply_int(reply, 'henchman_count', -1)
        other_count = _party_state_reply_int(reply, 'other_count', -1)
        if (
            reply.get('is_loaded') is not True
            or reply.get('is_party_leader') is not True
            or _party_state_reply_int(reply, 'party_id', -1) <= 0
            or _party_state_reply_int(reply, 'party_position', -1) != 0
            or party_size != 1
            or player_count != 1
            or hero_count != 0
            or henchman_count != 0
            or other_count != 0
            or party_size != player_count + hero_count + henchman_count + other_count
        ):
            return 'invalid', 'Alt reported a reciprocal invite without a verified solo guard.', reply
        return 'sent', result, reply

    def _prepare_hero_mutation(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        self.plan = deepcopy(preflight.plan)
        local_members = current_local_hero_members(GLOBAL_CACHE.Party, current_local_login_number())
        local_ids = current_local_hero_ids(GLOBAL_CACHE.Party, current_local_login_number())
        unmanaged_hero_count = int(
            (preflight.capacity.remote_hero_count if preflight.capacity is not None else 0)
            + (preflight.capacity.unknown_hero_count if preflight.capacity is not None else 0)
        )
        target_ids = self._target_ids()
        if not self.clear_existing and not local_ids.issubset(target_ids):
            self._finish(False, 'Mixed load blocked: existing local heroes would require removal.')
            return

        self._hero_add_slots = [slot for slot in self.plan.slots if int(slot.hero_id) not in local_ids]
        self._hero_add_index = 0
        self._behavior_index = 0
        self._template_index = 0

        if unmanaged_hero_count <= 0 and self.clear_existing and local_members:
            # This call is permitted only after the snapshot proved that every
            # current hero is locally owned. Mixed mode never uses it around a
            # remote or unknown-owner hero.
            GLOBAL_CACHE.Party.Heroes.KickAllHeroes()
            self._clear_dispatched = True
            self._clear_deadline = monotonic() + (max(1000, self.post_clear_wait_ms * 4) / 1000.0)
            self.message = 'Clearing locally owned heroes; unmanaged occupants are retained.'
            self._phase = 'wait_local_clear'
            self._wait(self.post_clear_wait_ms)
            return

        if not self._hero_add_slots:
            self._phase = 'behaviors'
            self.message = 'Applying local hero behavior.'
        else:
            self._phase = 'add_local_heroes'
            self.message = 'Adding locally owned heroes.'

    def _tick_invite(self) -> None:
        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        while self._invite_cursor < len(self._invite_indices):
            binding_index = self._invite_indices[self._invite_cursor]
            status = self._status_by_index(binding_index)
            if status is None:
                self._finish(False, f'Mixed load failed: alt account row {binding_index + 1} disappeared.')
                return
            if status.in_current_party:
                _mixed_log(
                    'Invite',
                    f'row={binding_index + 1} already-in-party; no invite required',
                    key=('operation', self._operation_log_key, 'invite-present', binding_index),
                )
                self._joined_binding_indices.add(binding_index)
                self._invite_cursor += 1
                continue
            if status.status not in {'ready', 'query_required'}:
                _mixed_log(
                    'Invite',
                    (
                        f'row={binding_index + 1} invite blocked by state={status.status}: '
                        f'{status.status_message or "no reason"}'
                    ),
                    key=('operation', self._operation_log_key, 'invite-blocked', binding_index),
                    message_type='Warning',
                )
                self._finish(False, f'Mixed load failed: {status.status_message or status.status}.')
                return
            self._begin_party_query(status)
            return
        self._phase = 'prepare_heroes'
        self.message = 'All configured alts are present; rechecking local hero ownership.'

    def _tick_wait_invite(self) -> None:
        status_before_refresh = self._status_by_index(self._invite_binding_index)
        guard_state = (
            self._read_guard_result(status_before_refresh)
            if status_before_refresh is not None and self._party_query_id
            else None
        )
        preflight = self._refresh_preflight()
        status = self._status_by_index(self._invite_binding_index)
        if guard_state is not None:
            guard_kind, guard_reason, guard_reply = guard_state
            if guard_kind == 'failed':
                self._guard_result_received = True
                guard_phase = (
                    'party_changed_before_invite' if guard_reason == 'guard_failed: party_changed' else 'failure'
                )
                self._set_runtime_alt_state(
                    self._invite_binding_index,
                    guard_phase,
                    query_id=self._party_query_id,
                    reply=guard_reply,
                    guard_result=guard_reason,
                )
                _mixed_log(
                    'InviteGuard',
                    (
                        f'row={self._invite_binding_index + 1} request={self._party_query_id!r} '
                        f'result={guard_reason}'
                    ),
                    key=('operation', self._operation_log_key, 'guard-failed', self._invite_binding_index),
                    message_type='Warning',
                )
                self._finish(
                    False,
                    f'Mixed load blocked: {status.character_name if status is not None else "alt"} ' f'{guard_reason}.',
                )
                return
            if guard_kind == 'invalid':
                self._set_runtime_alt_state(
                    self._invite_binding_index,
                    'failure',
                    query_id=self._party_query_id,
                    reply=guard_reply,
                    message=guard_reason,
                )
                _mixed_log(
                    'InviteGuard',
                    f'row={self._invite_binding_index + 1} invalid result: {guard_reason}',
                    key=('operation', self._operation_log_key, 'guard-invalid', self._invite_binding_index),
                    message_type='Warning',
                )
                self._finish(False, f'Mixed load failed: {guard_reason}')
                return
            if guard_kind == 'sent':
                self._guard_result_received = True
                _mixed_log(
                    'InviteGuard',
                    (
                        f'row={self._invite_binding_index + 1} request={self._party_query_id!r} '
                        'reciprocal invite sent after immediate solo recheck'
                    ),
                    key=('operation', self._operation_log_key, 'guard-sent', self._invite_binding_index),
                )
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        if status is not None and status.in_current_party:
            if self._guard_result_received:
                _mixed_log(
                    'Invite',
                    (
                        f'observed row={self._invite_binding_index + 1} char={status.character_name!r} '
                        f'in local party after guarded reciprocal invite; recalculating capacity'
                    ),
                    key=('operation', self._operation_log_key, 'invite-observed', self._invite_binding_index),
                )
                self._set_runtime_alt_state(
                    self._invite_binding_index,
                    'joined',
                    query_id=self._party_query_id,
                    guard_result='reciprocal_invite_sent',
                )
                self._joined_binding_indices.add(self._invite_binding_index)
                self._invite_cursor += 1
                self._invite_binding_index = -1
                self._party_query_binding_index = -1
                self._party_query_id = ''
                self._phase = 'invite'
                self.message = 'Alt joined; recalculating live party capacity.'
                self._wait(0)
                return
            self._joined_observed = True
            self.message = 'Alt joined; confirming the guarded reciprocal invite result.'
        if status is None or status.status not in {'ready', 'invite_waiting', 'joined', 'in_party'}:
            _mixed_log(
                'Invite',
                (
                    f'row={self._invite_binding_index + 1} unexpected invite state '
                    f'{status.status if status is not None else "missing"}: '
                    f'{status.status_message if status is not None else "identity disappeared"}'
                ),
                key=('operation', self._operation_log_key, 'invite-state-failed', self._invite_binding_index),
                message_type='Warning',
            )
            self._finish(
                False,
                f'Mixed load failed: {status.status_message if status is not None else "invite identity disappeared"}.',
            )
            return
        if monotonic() >= self._invite_deadline:
            _mixed_log(
                'Invite',
                (
                    f'timeout row={self._invite_binding_index + 1}: '
                    f'guard_received={int(self._guard_result_received)} '
                    f'join_observed={int(self._joined_observed)}'
                ),
                key=('operation', self._operation_log_key, 'invite-timeout', self._invite_binding_index),
                message_type='Warning',
            )
            self._set_runtime_alt_state(self._invite_binding_index, 'timeout', query_id=self._party_query_id)
            self._finish(False, 'Mixed load failed: guarded invite/join result could not be verified.')
            return
        if not self._guard_result_received:
            self.message = f'Waiting for {status.character_name or status.account_email} guard result.'
        elif not self._joined_observed:
            self.message = f'Waiting for {status.character_name or status.account_email} to join.'
        self._wait(self.poll_ms)

    def _tick_wait_local_clear(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        if current_local_hero_members(GLOBAL_CACHE.Party, current_local_login_number()):
            if monotonic() >= self._clear_deadline:
                self._finish(False, 'Mixed load failed: locally owned heroes did not leave the party.')
            else:
                self.message = 'Waiting for local heroes to leave.'
                self._wait(self.poll_ms)
            return
        self._hero_add_slots = list(self.plan.slots)
        self._hero_add_index = 0
        self._phase = 'add_local_heroes' if self._hero_add_slots else 'behaviors'
        self.message = 'Adding locally owned heroes.' if self._hero_add_slots else 'Applying local hero behavior.'
        self._wait(0)

    def _tick_add_local_heroes(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        local_ids = current_local_hero_ids(GLOBAL_CACHE.Party, current_local_login_number())
        while self._hero_add_index < len(self._hero_add_slots):
            slot = self._hero_add_slots[self._hero_add_index]
            hero_id = int(slot.hero_id)
            if hero_id in local_ids:
                self._hero_add_index += 1
                continue
            GLOBAL_CACHE.Party.Heroes.AddHero(hero_id)
            self.added_hero_ids.append(hero_id)
            self._hero_add_target_id = hero_id
            self._hero_add_deadline = monotonic() + 4.0
            self.message = f'Adding {slot.hero_name or hero_default_name(hero_id)}.'
            self._phase = 'wait_local_hero'
            self._wait(self.hero_add_delay_ms)
            return
        self._phase = 'behaviors'
        self.message = 'Applying local hero behavior.'

    def _tick_wait_local_hero(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        if self._hero_add_target_id in current_local_hero_ids(GLOBAL_CACHE.Party, current_local_login_number()):
            self._hero_add_index += 1
            self._hero_add_target_id = 0
            self._phase = 'add_local_heroes'
            self._wait(0)
            return
        if monotonic() >= self._hero_add_deadline:
            self._finish(False, 'Mixed load failed: a requested local hero could not be observed after adding.')
            return
        self.message = 'Waiting for the requested local hero to appear.'
        self._wait(self.poll_ms)

    def _tick_behaviors(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        while self._behavior_index < len(self.plan.slots):
            slot = self.plan.slots[self._behavior_index]
            self._behavior_index += 1
            if slot.behavior == HERO_BEHAVIOR_DONT_CHANGE:
                continue
            position = self._owner_safe_position(int(slot.hero_id), GLOBAL_CACHE.Party)
            if position <= 0:
                self._finish(False, f'Mixed load failed: local owner could not be verified for {slot.hero_name}.')
                return
            hero_agent_id = GLOBAL_CACHE.Party.Heroes.GetHeroAgentIDByPartyPosition(position)
            if int(hero_agent_id or 0) <= 0:
                self._finish(False, f'Mixed load failed: local hero agent could not be resolved for {slot.hero_name}.')
                return
            GLOBAL_CACHE.Party.Heroes.SetHeroBehavior(int(hero_agent_id), int(slot.behavior))
            self.applied_behavior_hero_ids.append(int(slot.hero_id))
            self.message = f'Applying behavior to {slot.hero_name or hero_default_name(slot.hero_id)}.'
            self._wait(100)
            return
        self._phase = 'templates'
        self.message = 'Applying local hero templates.'

    def _tick_templates(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
            return
        while self._template_index < len(self.plan.slots):
            slot = self.plan.slots[self._template_index]
            self._template_index += 1
            if not slot.template_code and not slot.clear_skillbar:
                continue
            position = self._owner_safe_position(int(slot.hero_id), GLOBAL_CACHE.Party)
            if position <= 0:
                self._finish(False, f'Mixed load failed: local owner could not be verified for {slot.hero_name}.')
                return
            template_code = slot.template_code
            if slot.clear_skillbar:
                template_code = _empty_skillbar_template_for_hero_position(position, party_api=GLOBAL_CACHE.Party)
                if not template_code:
                    self._finish(False, f'Mixed load failed: empty skill bar could not be built for {slot.hero_name}.')
                    return
            try:
                GLOBAL_CACHE.SkillBar.LoadHeroSkillTemplate(position, template_code)
            except Exception as exc:
                self._finish(False, f'Mixed load failed while applying {slot.hero_name}: {exc}')
                return
            if slot.clear_skillbar:
                self.cleared_skillbar_hero_ids.append(int(slot.hero_id))
                self.message = f'Clearing skill bar for {slot.hero_name or hero_default_name(slot.hero_id)}.'
            else:
                self.applied_template_hero_ids.append(int(slot.hero_id))
                self.message = f'Applying template to {slot.hero_name or hero_default_name(slot.hero_id)}.'
            self._wait(self.template_delay_ms)
            return
        self._phase = 'final'
        self.message = 'Rechecking final mixed party composition.'
        self._wait(0)

    def _tick_final(self) -> None:
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

        preflight = self._refresh_preflight()
        if not preflight.can_load:
            self._finish(False, f'Mixed load failed final verification: {" ".join(preflight.blocking_messages)}')
            return
        target_ids = self._target_ids()
        local_members = current_local_hero_members(GLOBAL_CACHE.Party, current_local_login_number())
        local_ids = current_local_hero_ids(GLOBAL_CACHE.Party, current_local_login_number())
        enabled_statuses = [status for status in preflight.alt_statuses if status.status != 'disabled']
        if any(not status.in_current_party for status in enabled_statuses):
            self._finish(False, 'Mixed load failed final verification: a configured alt is no longer in the party.')
            return
        if local_ids != target_ids or len(local_members) != len(target_ids):
            self._finish(False, 'Mixed load failed final verification: local hero composition does not match the team.')
            return
        capacity = preflight.capacity
        party_summary = (
            f'party {capacity.current_party_size}/{capacity.max_party_size}'
            if capacity is not None
            else 'party state verified'
        )
        self._finish(
            True,
            f'Mixed team loaded: {len(enabled_statuses)} alt(s), {len(target_ids)} local hero(es), {party_summary}.',
        )

    def tick(self) -> bool:
        if self.done:
            return True
        if not self._ready():
            return False
        self._log_phase_transition()
        try:
            if self._phase == 'validate':
                preflight = self._refresh_preflight()
                self._log_operation_start(preflight)
                if not preflight.can_load:
                    self._finish(False, f'Mixed load blocked: {" ".join(preflight.blocking_messages)}')
                    return True
                self._joined_binding_indices = {
                    status.binding_index for status in preflight.alt_statuses if status.status == 'in_party'
                }
                self._invite_indices = [
                    status.binding_index
                    for status in preflight.alt_statuses
                    if status.status in {'ready', 'query_required'}
                ]
                self._invite_cursor = 0
                self._phase = 'invite' if self._invite_indices else 'prepare_heroes'
                self.message = (
                    'Preparing configured alt accounts.' if self._invite_indices else 'Preparing local heroes.'
                )

            if self._phase == 'invite':
                self._tick_invite()
                return self.done
            if self._phase == 'wait_party_query':
                self._tick_wait_party_query()
                return self.done
            if self._phase == 'wait_invite':
                self._tick_wait_invite()
                return self.done
            if self._phase == 'prepare_heroes':
                self._prepare_hero_mutation()
                return self.done
            if self._phase == 'wait_local_clear':
                self._tick_wait_local_clear()
                return self.done
            if self._phase == 'add_local_heroes':
                self._tick_add_local_heroes()
                return self.done
            if self._phase == 'wait_local_hero':
                self._tick_wait_local_hero()
                return self.done
            if self._phase == 'behaviors':
                self._tick_behaviors()
                return self.done
            if self._phase == 'templates':
                self._tick_templates()
                return self.done
            if self._phase == 'final':
                self._tick_final()
                return self.done
            self._finish(False, f'Mixed load failed: unknown operation phase {self._phase}.')
        except Exception as exc:
            self._finish(False, f'Mixed team load failed: {exc}')
        return self.done


def create_apply_operation(
    config: HeroTeamConfig,
    team_id: str | None = None,
    *,
    leave_party_first: bool = False,
    clear_existing: bool = True,
) -> HeroTeamApplyOperation | MixedHeroTeamApplyOperation:
    team = get_team(config, team_id)
    if team is None:
        raise ValueError('No team selected.')
    if team_has_enabled_alt_bindings(team):
        return MixedHeroTeamApplyOperation(
            config,
            team_id,
            clear_existing=clear_existing,
        )
    return HeroTeamApplyOperation(
        team,
        config.templates,
        hero_names=config.hero_names,
        leave_party_first=leave_party_first,
        clear_existing=clear_existing,
    )
