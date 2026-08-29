from __future__ import annotations

import ast
import copy
import ctypes
import importlib.util
import sys
import time
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / 'Py4GWCoreLib' / 'modular' / 'hero_team_manager.py'
WIDGET_PATH = ROOT / 'Widgets' / 'Guild Wars' / 'Hero Team Manager.py'
MESSAGING_PATH = ROOT / 'Widgets' / 'System' / 'Messaging.py'
ALL_ACCOUNTS_PATH = ROOT / 'Py4GWCoreLib' / 'GlobalCache' / 'shared_memory_src' / 'AllAccounts.py'


class _FakeJsonDocument:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.operations: list[tuple[str, str]] = []

    def get_json(self, path: str = '', default=None):
        if not path:
            return copy.deepcopy(self.data) if self.data else default
        node: object = self.data
        for part in str(path).strip('/').split('/'):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return copy.deepcopy(node)

    def set_json(self, path: str, value) -> None:
        self.operations.append(('set_json', str(path)))
        if not path:
            self.data = copy.deepcopy(value)
            return
        parts = str(path).strip('/').split('/')
        node = self.data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = copy.deepcopy(value)

    def set(self, path: str, value) -> None:
        self.set_json(path, value)

    def set_int(self, path: str, value: int) -> None:
        self.set(path, int(value))

    def set_str(self, path: str, value: str) -> None:
        self.set(path, str(value))

    def delete(self, path: str) -> bool:
        self.operations.append(('delete', str(path)))
        parts = str(path).strip('/').split('/') if str(path).strip('/') else []
        if not parts:
            return False
        node = self.data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                return False
            node = child
        return node.pop(parts[-1], None) is not None

    def save(self) -> bool:
        self.operations.append(('save', ''))
        return True

    def reload(self) -> bool:
        self.operations.append(('reload', ''))
        return True


class _FakeJsonFactory(_FakeJsonDocument):
    documents: dict[tuple[str, str], _FakeJsonFactory] = {}

    def __new__(cls, name: str, scope: str = 'account'):
        key = (str(name), str(scope))
        existing = cls.documents.get(key)
        if existing is not None:
            return existing
        instance = super().__new__(cls)
        _FakeJsonDocument.__init__(instance)
        cls.documents[key] = instance
        return instance

    def __init__(self, name: str, scope: str = 'account') -> None:
        pass


def _load_helper():
    fake_core = types.ModuleType('Py4GWCoreLib')
    fake_core.__path__ = []
    fake_modular = types.ModuleType('Py4GWCoreLib.modular')
    fake_modular.__path__ = []
    fake_setup = types.ModuleType('Py4GWCoreLib.modular.hero_setup_model')
    hero_options = [(hero_id, f'Hero {hero_id}') for hero_id in range(40)]
    setattr(fake_setup, 'HERO_OPTIONS', hero_options)
    setattr(fake_setup, 'HERO_ID_TO_NAME', {hero_id: name for hero_id, name in hero_options})
    setattr(fake_setup, 'safe_account_key', lambda: 'test-account')
    fake_support = types.ModuleType('Py4GWCoreLib.py4gwcorelib_src')
    fake_support.__path__ = []
    fake_json = types.ModuleType('Py4GWCoreLib.py4gwcorelib_src.JsonFactory')
    setattr(fake_json, 'JsonFactory', _FakeJsonFactory)
    names = {
        'Py4GWCoreLib': fake_core,
        'Py4GWCoreLib.modular': fake_modular,
        'Py4GWCoreLib.modular.hero_setup_model': fake_setup,
        'Py4GWCoreLib.py4gwcorelib_src': fake_support,
        'Py4GWCoreLib.py4gwcorelib_src.JsonFactory': fake_json,
    }
    previous = {name: sys.modules.get(name) for name in names}
    sys.modules.update(names)
    _FakeJsonFactory.documents.clear()
    module_name = '_hero_team_manager_port_under_test'
    spec = importlib.util.spec_from_file_location(module_name, HELPER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError('Could not create helper import spec')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, previous, module_name


def _load_widget(helper):
    fake_imgui = types.ModuleType('Py4GWCoreLib.ImGui')
    setattr(fake_imgui, 'ImGui', types.SimpleNamespace())

    fake_settings = types.ModuleType('Py4GWCoreLib.py4gwcorelib_src.Settings')

    class _FakeSettings:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_bool(self, _section: str, _key: str, default: bool = False) -> bool:
            return bool(default)

        def set_bool(self, _section: str, _key: str, _value: bool) -> None:
            pass

    setattr(fake_settings, 'Settings', _FakeSettings)

    fake_system = types.ModuleType('PySystem')
    setattr(
        fake_system,
        'Console',
        types.SimpleNamespace(Log=lambda *args, **kwargs: None, MessageType=types.SimpleNamespace(Error='error')),
    )
    fake_pyimgui = types.ModuleType('PyImGui')

    names = {
        'Py4GWCoreLib.modular.hero_team_manager': helper,
        'Py4GWCoreLib.ImGui': fake_imgui,
        'Py4GWCoreLib.py4gwcorelib_src.Settings': fake_settings,
        'PySystem': fake_system,
        'PyImGui': fake_pyimgui,
    }
    previous = {name: sys.modules.get(name) for name in names}
    sys.modules.update(names)
    module_name = '_hero_team_manager_widget_port_under_test'
    spec = importlib.util.spec_from_file_location(module_name, WIDGET_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError('Could not create widget import spec')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, previous, module_name


def _load_messaging_party_state_functions() -> dict[str, Any]:
    source = MESSAGING_PATH.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(MESSAGING_PATH))
    wanted = {
        '_party_state_int',
        '_party_state_map_scalar',
        '_party_state_map_signature',
        '_party_state_map_text',
        '_party_state_local_snapshot',
        '_party_state_params',
        '_party_state_metadata',
        '_party_state_is_solo',
        '_send_party_state_result',
        '_guarded_party_invite_result',
        'PartyStateQuery',
        'InviteToParty',
    }
    nodes: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict[str, Any] = {
        '__name__': '_messaging_party_state_port',
        'Any': Any,
        'SharedMessageStruct': object,
        'time': time,
        '_PARTY_STATE_QUERY_REQUEST': 'party_state_request',
        '_PARTY_STATE_QUERY_REPLY': 'party_state_reply',
        '_PARTY_STATE_GUARD_RESULT': 'party_state_guard',
        '_PARTY_INVITE_GUARD': 'party_invite_guard',
    }
    exec(compile(module, str(MESSAGING_PATH), 'exec'), namespace)
    return namespace


def _load_authoritative_shared_command_type():
    source_path = ROOT / 'Py4GWCoreLib' / 'enums_src' / 'Multiboxing_enums.py'
    source = source_path.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(source_path))
    enum_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SharedCommandType')
    module = ast.Module(body=[enum_node], type_ignores=[])
    ast.fix_missing_locations(module)
    from enum import IntEnum, auto

    namespace: dict[str, Any] = {'IntEnum': IntEnum, 'auto': auto}
    exec(compile(module, str(source_path), 'exec'), namespace)
    return namespace['SharedCommandType']


def _load_authoritative_all_accounts_send_message():
    source = ALL_ACCOUNTS_PATH.read_text(encoding='utf-8')
    tree = ast.parse(source, filename=str(ALL_ACCOUNTS_PATH))
    send_node = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'SendMessage'
    )
    module = ast.Module(body=[send_node], type_ignores=[])
    ast.fix_missing_locations(module)
    console = types.SimpleNamespace(MessageType=types.SimpleNamespace(Error='error', Warning='warning'))
    system = types.SimpleNamespace(
        Console=console,
        get_tick_count64=lambda: 1234,
    )
    namespace: dict[str, Any] = {
        'SharedCommandType': _load_authoritative_shared_command_type(),
        'SHMEM_MAX_PLAYERS': 64,
        'SHMEM_MAX_CHAR_LEN': 64,
        'SHMEM_MODULE_NAME': 'Shared Memory',
        'ConsoleLog': lambda *_args, **_kwargs: None,
        'PySystem': system,
    }
    exec(compile(module, str(ALL_ACCOUNTS_PATH), 'exec'), namespace)
    return namespace['SendMessage'], namespace['SharedCommandType']


class _RealSharedMemorySendHarness:
    def __init__(self, receiver_email: str) -> None:
        self.receiver_email = str(receiver_email)
        self.Inbox = [
            types.SimpleNamespace(
                Active=False,
                Running=False,
                SenderEmail='',
                ReceiverEmail='',
                Command=0,
                Params=(),
                ExtraData=(),
                Timestamp=0,
            )
            for _ in range(64)
        ]

    def GetSlotByEmail(self, email: str) -> int:
        return 0 if str(email) == self.receiver_email else -1

    def _can_communicate(self, _sender_email: str, _receiver_email: str) -> bool:
        return True

    def GetInbox(self, index: int):
        return self.Inbox[index]

    def _str_to_c_wchar_array(self, value: str, maxlen: int):
        array_type = ctypes.c_wchar * maxlen
        result = array_type()
        for index, character in enumerate(str(value)[: maxlen - 1]):
            result[index] = character
        return result

    @staticmethod
    def _c_wchar_array_to_str(value) -> str:
        return ''.join(character for character in value if character != '\0').rstrip()


def _current_reforged_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a stable current-format account and shared-template fixture."""
    template_records = [
        {
            'id': f'current-template-{index:02d}',
            'name': f'Current Build {index:02d}',
            'code': f'CODE-{index:02d}',
        }
        for index in range(16)
    ]
    template_ids = [str(template['id']) for template in template_records]
    hero_ids = [28, 29, 30, 31, 32, 33, 34]
    teams = []
    for team_index in range(3):
        start = team_index * len(hero_ids)
        slots = [
            {'hero_id': hero_ids[offset], 'template_id': template_id}
            for offset, template_id in enumerate(template_ids[start : start + len(hero_ids)])
        ]
        teams.append(
            {
                'id': f'current-team-{team_index}',
                'name': f'Current Team {team_index}',
                'slots': slots,
            }
        )

    account_source = {
        'version': 2,
        'active_team_id': 'current-team-0',
        'hero_names': {'28': 'Mali'},
        'hero_profession_cache': {},
        'template_preferences': {template_ids[0]: 28},
        'teams': teams,
        'migrations': {
            'global_templates_v1': {
                'completed': True,
                'version': 1,
                'id_remap': {template_id: template_id for template_id in template_ids},
            }
        },
    }
    global_source = {
        'version': 1,
        'templates': {
            str(template['id']): {
                'name': str(template['name']),
                'code': str(template['code']),
            }
            for template in template_records
        },
    }
    return account_source, global_source


class _FakePartyPlayer:
    def __init__(self, login_number: int) -> None:
        self.login_number = int(login_number)


class _FakePartyHero:
    def __init__(self, hero_id: int, owner_player_id: int) -> None:
        self.hero_id = int(hero_id)
        self.owner_player_id = int(owner_player_id)
        self.agent_id = 1000 + int(hero_id)


class _FakePartyApi:
    def __init__(
        self,
        players: list[_FakePartyPlayer],
        heroes: list[_FakePartyHero] | None = None,
        henchmen: list[Any] | None = None,
        others: list[Any] | None = None,
        *,
        party_id: int = 10,
        loaded: bool = True,
        leader: bool = True,
        reported_size: int | None = None,
    ) -> None:
        self.players = list(players)
        self.heroes = list(heroes or [])
        self.henchmen = list(henchmen or [])
        self.others = list(others or [])
        self.party_id = int(party_id)
        self.loaded = bool(loaded)
        self.leader = bool(leader)
        self.reported_size = reported_size
        self.kick_all_calls = 0
        self.leave_party_calls = 0
        self.invites: list[str] = []
        self.added_heroes: list[int] = []
        self.Players = types.SimpleNamespace(
            GetAgentIDByLoginNumber=lambda login_number: 2000 + int(login_number or 0),
            GetPlayerNameByLoginNumber=lambda login_number: (
                'Main' if int(login_number or 0) == 1 else f'Player {int(login_number or 0)}'
            ),
            InvitePlayer=lambda character_name: self.invites.append(str(character_name)),
        )
        self.Heroes = types.SimpleNamespace(
            KickAllHeroes=self._kick_all_heroes,
            AddHero=self._add_hero,
            GetHeroAgentIDByPartyPosition=lambda _position: 3000,
            SetHeroBehavior=lambda *_args: None,
        )

    def _kick_all_heroes(self) -> None:
        self.kick_all_calls += 1

    def LeaveParty(self) -> None:
        self.leave_party_calls += 1

    def _add_hero(self, hero_id: int) -> None:
        self.added_heroes.append(int(hero_id))

    def GetPlayers(self) -> list[_FakePartyPlayer]:
        return list(self.players)

    def GetHeroes(self) -> list[_FakePartyHero]:
        return list(self.heroes)

    def GetHenchmen(self) -> list[Any]:
        return list(self.henchmen)

    def GetOthers(self) -> list[Any]:
        return list(self.others)

    def GetPartySize(self) -> int:
        if self.reported_size is not None:
            return int(self.reported_size)
        return len(self.players) + len(self.heroes) + len(self.henchmen) + len(self.others)

    def GetPlayerCount(self) -> int:
        return len(self.players)

    def GetHeroCount(self) -> int:
        return len(self.heroes)

    def GetHenchmanCount(self) -> int:
        return len(self.henchmen)

    def GetPartyID(self) -> int:
        return self.party_id

    def GetOwnPartyNumber(self) -> int:
        for index, player in enumerate(self.players):
            if int(getattr(player, 'login_number', 0) or 0) == 1:
                return index
        return -1

    def IsPartyLoaded(self) -> bool:
        return self.loaded

    def IsPartyLeader(self) -> bool:
        return self.leader


class _FakeMapApi:
    def __init__(self, max_party_size: int, *, outpost: bool = True) -> None:
        self.max_party_size = int(max_party_size)
        self.outpost = bool(outpost)

    def GetMaxPartySize(self) -> int:
        return self.max_party_size

    def IsOutpost(self) -> bool:
        return self.outpost

    def GetMapID(self) -> int:
        return 100

    def GetRegion(self) -> tuple[int, str]:
        return (1, 'America')

    def GetDistrict(self) -> int:
        return 1

    def GetLanguage(self) -> tuple[int, str]:
        return (0, 'English')


class _FakePlayerApi:
    def __init__(self, email: str = 'main@example.com', login_number: int = 1) -> None:
        self.email = str(email)
        self.login_number = int(login_number)

    def GetAccountEmail(self) -> str:
        return self.email

    def GetLoginNumber(self) -> int:
        return self.login_number


class _FakeAccountRecord:
    def __init__(
        self,
        email: str,
        login_number: int,
        character_name: str,
        *,
        active: bool = True,
        isolated: bool = False,
        party_id: int | None = None,
        party_position: int = 0,
        is_party_leader: bool = True,
        map_id: int = 100,
    ) -> None:
        self.AccountEmail = str(email)
        self.IsAccount = True
        self.IsSlotActive = bool(active)
        self.IsIsolated = bool(isolated)
        self.AgentData = types.SimpleNamespace(
            CharacterName=str(character_name),
            AgentID=4000 + int(login_number),
            LoginNumber=int(login_number),
            Map=types.SimpleNamespace(MapID=int(map_id), Region=1, District=1, Language=0),
            Profession=(1, 2),
        )
        self.AgentPartyData = types.SimpleNamespace(
            PartyID=10000 + int(login_number) if party_id is None else int(party_id),
            PartyPosition=int(party_position),
            IsPartyLeader=bool(is_party_leader),
        )


class _FakeSharedMemory:
    def __init__(self, active: list[_FakeAccountRecord], all_records: list[_FakeAccountRecord] | None = None) -> None:
        self.active = list(active)
        self.all_records = list(all_records if all_records is not None else active)
        self.messages: list[tuple[Any, ...]] = []

    def GetAllAccountData(self, **_kwargs) -> list[_FakeAccountRecord]:
        return list(self.active)

    def GetAllAccounts(self):
        return types.SimpleNamespace(AccountData=list(self.all_records))

    def SendMessage(self, *args) -> int:
        self.messages.append(tuple(args))
        return len(self.messages) - 1

    def GetAccountDataFromEmail(self, email: str):
        target = str(email or '').strip().casefold()
        return next(
            (record for record in self.all_records if str(record.AccountEmail).strip().casefold() == target),
            None,
        )

    def MarkMessageAsRunning(self, *_args) -> None:
        pass

    def MarkMessageAsFinished(self, *_args) -> None:
        pass


class HeroTeamManagerPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module, cls.previous_modules, cls.module_name = _load_helper()
        cls.widget, cls.widget_previous_modules, cls.widget_module_name = _load_widget(cls.module)

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop(cls.widget_module_name, None)
        for name, previous in cls.widget_previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        sys.modules.pop(cls.module_name, None)
        for name, previous in cls.previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def _install_runtime_modules(self, party, shared_memory, map_api=None):
        map_api = map_api or _FakeMapApi(8)
        fake_global_cache = types.ModuleType('Py4GWCoreLib.GlobalCache')
        setattr(
            fake_global_cache,
            'GLOBAL_CACHE',
            types.SimpleNamespace(
                Party=party,
                ShMem=shared_memory,
                SkillBar=types.SimpleNamespace(LoadHeroSkillTemplate=lambda *_args: None),
            ),
        )
        fake_player = types.ModuleType('Py4GWCoreLib.Player')
        setattr(fake_player, 'Player', _FakePlayerApi())
        fake_map = types.ModuleType('Py4GWCoreLib.Map')
        setattr(fake_map, 'Map', map_api)
        fake_enums = types.ModuleType('Py4GWCoreLib.enums_src')
        fake_multibox_enums = types.ModuleType('Py4GWCoreLib.enums_src.Multiboxing_enums')
        setattr(
            fake_multibox_enums,
            'SharedCommandType',
            types.SimpleNamespace(
                InviteToParty='InviteToParty',
                PartyStateQuery='PartyStateQuery',
            ),
        )
        names = {
            'Py4GWCoreLib.GlobalCache': fake_global_cache,
            'Py4GWCoreLib.Player': fake_player,
            'Py4GWCoreLib.Map': fake_map,
            'Py4GWCoreLib.enums_src': fake_enums,
            'Py4GWCoreLib.enums_src.Multiboxing_enums': fake_multibox_enums,
        }
        previous = {name: sys.modules.get(name) for name in names}
        sys.modules.update(names)
        return previous

    @staticmethod
    def _restore_runtime_modules(previous) -> None:
        for name, prior in previous.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior

    def _team_with_alts(self, emails: list[str], hero_ids: list[int] | None = None):
        team = self.module.new_team('Mixed team')
        team.alt_members = [self.module.AltAccountBinding(account_email=email) for email in emails]
        for slot, hero_id in zip(team.slots, hero_ids or []):
            slot.hero_id = int(hero_id)
        return team

    def _mixed_preflight(
        self,
        team,
        *,
        max_party_size: int = 8,
        players: list[_FakePartyPlayer] | None = None,
        heroes: list[_FakePartyHero] | None = None,
        henchmen: list[Any] | None = None,
        others: list[Any] | None = None,
        active_accounts: list[_FakeAccountRecord] | None = None,
        all_accounts: list[_FakeAccountRecord] | None = None,
        reported_size: int | None = None,
    ):
        party = _FakePartyApi(
            players or [_FakePartyPlayer(1)],
            heroes,
            henchmen,
            others,
            reported_size=reported_size,
        )
        accounts = list(active_accounts or [])
        shared_memory = _FakeSharedMemory(accounts, all_accounts if all_accounts is not None else accounts)
        config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
        return self.module.build_mixed_team_preflight(
            config,
            team.team_id,
            map_api=_FakeMapApi(max_party_size),
            party_api=party,
            player_api=_FakePlayerApi(),
            shared_memory=shared_memory,
        )

    def test_alt_bindings_migrate_empty_and_round_trip_in_saved_order(self) -> None:
        legacy = self.module.normalize_config(
            {
                'version': 2,
                'active_team_id': 'team-a',
                'teams': [{'id': 'team-a', 'name': 'A', 'slots': []}],
            }
        )
        self.assertEqual(legacy.teams[0].alt_members, [])

        config = self.module.normalize_config(
            {
                'version': 3,
                'active_team_id': 'team-a',
                'teams': [
                    {
                        'id': 'team-a',
                        'name': 'A',
                        'slots': [],
                        'alt_members': [
                            {'account_email': 'first@example.com', 'alias': 'First', 'enabled': False},
                            {'account_email': 'second@example.com', 'expected_character_name': 'Second'},
                        ],
                    }
                ],
            }
        )
        payload = self.module.config_to_dict(config)

        self.assertEqual(
            [(binding.account_email, binding.enabled, binding.alias) for binding in config.teams[0].alt_members],
            [('first@example.com', False, 'First'), ('second@example.com', True, '')],
        )
        self.assertEqual(
            [binding['account_email'] for binding in payload['teams'][0]['alt_members']],
            ['first@example.com', 'second@example.com'],
        )
        account_document = self.module._config_document()
        account_document.data = {}
        self.module.save_account_config(config, 'test-account')
        round_tripped = self.module.load_config('test-account')
        self.assertEqual(
            [binding.account_email for binding in round_tripped.teams[0].alt_members],
            ['first@example.com', 'second@example.com'],
        )

    def test_duplicate_alt_bindings_are_preserved_and_block_mixed_load(self) -> None:
        team = self._team_with_alts(['duplicate@example.com', 'DUPLICATE@EXAMPLE.COM'])
        config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])

        self.assertEqual(self.module.duplicate_alt_binding_indices(team), {0, 1})
        self.assertTrue(self.module.validate_alt_bindings(team))
        preflight = self._mixed_preflight(team)

        self.assertFalse(preflight.can_load)
        self.assertTrue(any('Duplicate account identity' in message for message in preflight.blocking_messages))
        self.assertEqual(
            [binding['account_email'] for binding in self.module.config_to_dict(config)['teams'][0]['alt_members']],
            ['duplicate@example.com', 'DUPLICATE@EXAMPLE.COM'],
        )

    def test_duplicate_team_preserves_alt_order_and_binding_fields(self) -> None:
        source = self._team_with_alts(['zulu@example.com', 'alpha@example.com', 'middle@example.com'])
        source.alt_members[0].enabled = False
        source.alt_members[0].alias = 'Zulu'
        source.alt_members[1].expected_character_name = 'Alpha'
        config = self.module.HeroTeamConfig(active_team_id=source.team_id, teams=[source])

        duplicate = self.module.duplicate_team(config, source.team_id)

        self.assertIsNotNone(duplicate)
        self.assertEqual(
            [binding.account_email for binding in duplicate.alt_members],
            ['zulu@example.com', 'alpha@example.com', 'middle@example.com'],
        )
        self.assertEqual(duplicate.alt_members[0].enabled, False)
        self.assertEqual(duplicate.alt_members[0].alias, 'Zulu')
        self.assertEqual(duplicate.alt_members[1].expected_character_name, 'Alpha')
        self.assertIsNot(duplicate.alt_members[0], source.alt_members[0])

    def test_widget_alt_reorder_preserves_bindings_and_marks_account_dirty(self) -> None:
        team = self._team_with_alts(['first@example.com', 'second@example.com', 'third@example.com'])
        first, second, third = team.alt_members
        first.alias = 'First'
        first.expected_character_name = 'First Character'
        first.enabled = False

        widget = self.widget
        old_mark_dirty = widget._mark_dirty
        had_mouse_down = hasattr(widget.PyImGui, 'is_mouse_down')
        old_mouse_down = getattr(widget.PyImGui, 'is_mouse_down', None)
        dirty_messages: list[str] = []
        try:
            setattr(widget, '_mark_dirty', lambda message: dirty_messages.append(str(message)))
            setattr(widget.PyImGui, 'is_mouse_down', lambda _button: False)
            setattr(widget, '_alt_drag_team_id', team.team_id)
            setattr(widget, '_alt_drag_from', 0)
            setattr(widget, '_alt_drag_to', 2)
            widget._finish_alt_drag(team, disabled=False)
        finally:
            setattr(widget, '_mark_dirty', old_mark_dirty)
            if had_mouse_down:
                setattr(widget.PyImGui, 'is_mouse_down', old_mouse_down)
            else:
                delattr(widget.PyImGui, 'is_mouse_down')

        self.assertEqual(
            [binding.account_email for binding in team.alt_members],
            ['second@example.com', 'third@example.com', 'first@example.com'],
        )
        self.assertIs(team.alt_members[2], first)
        self.assertIs(team.alt_members[0], second)
        self.assertIs(team.alt_members[1], third)
        self.assertEqual(team.alt_members[2].alias, 'First')
        self.assertEqual(team.alt_members[2].expected_character_name, 'First Character')
        self.assertFalse(team.alt_members[2].enabled)
        self.assertEqual(dirty_messages, ['Account order changed. Click Save to keep it.'])
        self.assertIsNone(widget._alt_drag_from)
        self.assertIsNone(widget._alt_drag_to)

    def test_mixed_load_uses_configured_alt_order_without_sorting(self) -> None:
        order = ['zulu@example.com', 'alpha@example.com', 'middle@example.com']
        team = self._team_with_alts(order)
        accounts = [
            _FakeAccountRecord('alpha@example.com', 3, 'Alpha'),
            _FakeAccountRecord('middle@example.com', 4, 'Middle'),
            _FakeAccountRecord('zulu@example.com', 2, 'Zulu'),
        ]
        preflight = self._mixed_preflight(team, active_accounts=accounts, all_accounts=accounts)

        self.assertEqual([status.account_email for status in preflight.alt_statuses], order)

        party = _FakePartyApi([_FakePartyPlayer(1)])
        shared_memory = _FakeSharedMemory(accounts)
        previous = self._install_runtime_modules(party, shared_memory)
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertFalse(operation.tick())

            self.assertEqual(operation._invite_indices, [0, 1, 2])
            self.assertEqual(shared_memory.messages[0][0:2], ('main@example.com', 'zulu@example.com'))
        finally:
            self._restore_runtime_modules(previous)

    def test_local_account_cannot_be_configured_as_an_alt(self) -> None:
        team = self._team_with_alts(['main@example.com'])
        messages = self.module.validate_alt_bindings(team, 'main@example.com')

        self.assertTrue(any('local account' in message for message in messages))
        preflight = self._mixed_preflight(team)
        self.assertFalse(preflight.can_load)
        self.assertTrue(any(status.status == 'local_account' for status in preflight.alt_statuses))

    def test_distinct_alt_bindings_cannot_share_one_live_party_player_slot(self) -> None:
        team = self._team_with_alts(['alt1@example.com', 'alt2@example.com'])
        preflight = self._mixed_preflight(
            team,
            players=[_FakePartyPlayer(1), _FakePartyPlayer(2)],
            active_accounts=[
                _FakeAccountRecord('alt1@example.com', 2, 'Alt 1', party_id=10),
                _FakeAccountRecord('alt2@example.com', 2, 'Alt 2', party_id=10),
            ],
        )

        self.assertFalse(preflight.can_load)
        self.assertTrue(
            any('do not map uniquely to non-local party players' in message for message in preflight.blocking_messages)
        )
        self.assertEqual(preflight.capacity.configured_alt_present_count, 1)
        self.assertEqual(preflight.capacity.unmanaged_player_count, 0)

    def test_active_alt_discovery_excludes_local_and_has_no_three_account_limit(self) -> None:
        accounts = [
            _FakeAccountRecord('main@example.com', 1, 'Main'),
            *[_FakeAccountRecord(f'alt{index}@example.com', index + 2, f'Alt {index}') for index in range(7)],
        ]
        choices = self.module.active_alt_account_choices(
            player_api=_FakePlayerApi(),
            shared_memory=_FakeSharedMemory(accounts),
        )

        self.assertEqual(
            [choice.account_email for choice in choices],
            [f'alt{index}@example.com' for index in range(7)],
        )
        self.assertNotIn('main@example.com', [choice.account_email for choice in choices])

    def test_dynamic_capacity_supports_full_party_compositions_without_an_alt_cap(self) -> None:
        def accounts(count: int) -> list[_FakeAccountRecord]:
            return [
                _FakeAccountRecord(
                    f'alt{index}@example.com',
                    index + 2,
                    f'Alt {index}',
                )
                for index in range(count)
            ]

        seven_alt_team = self._team_with_alts([f'alt{index}@example.com' for index in range(7)])
        seven_alt_preflight = self._mixed_preflight(seven_alt_team, active_accounts=accounts(7))
        self.assertTrue(seven_alt_preflight.can_load)
        self.assertEqual(seven_alt_preflight.capacity.missing_alt_count, 7)
        self.assertEqual(seven_alt_preflight.capacity.forecast_final_slots, 8)

        four_alt_team = self._team_with_alts(
            [f'alt{index}@example.com' for index in range(4)],
            [28, 29, 30],
        )
        four_alt_preflight = self._mixed_preflight(
            four_alt_team,
            heroes=[_FakePartyHero(hero_id, 1) for hero_id in [28, 29, 30]],
            active_accounts=accounts(4),
        )
        self.assertTrue(four_alt_preflight.can_load)
        self.assertEqual(four_alt_preflight.capacity.forecast_final_slots, 8)

        two_alt_team = self._team_with_alts(
            [f'alt{index}@example.com' for index in range(2)],
            [28, 29, 30, 31, 32],
        )
        two_alt_preflight = self._mixed_preflight(
            two_alt_team,
            heroes=[_FakePartyHero(hero_id, 1) for hero_id in [28, 29, 30, 31, 32]],
            active_accounts=accounts(2),
        )
        self.assertTrue(two_alt_preflight.can_load)
        self.assertEqual(two_alt_preflight.capacity.forecast_final_slots, 8)

        twelve_slot_team = self._team_with_alts([f'alt{index}@example.com' for index in range(10)], [28])
        twelve_slot_preflight = self._mixed_preflight(
            twelve_slot_team,
            max_party_size=12,
            heroes=[_FakePartyHero(28, 1)],
            active_accounts=accounts(10),
        )
        self.assertTrue(twelve_slot_preflight.can_load)
        self.assertEqual(twelve_slot_preflight.capacity.forecast_final_slots, 12)

    def test_capacity_rejects_overflow_and_does_not_double_count_existing_alt_or_local_heroes(self) -> None:
        eight_alt_team = self._team_with_alts([f'alt{index}@example.com' for index in range(8)])
        over_capacity = self._mixed_preflight(
            eight_alt_team,
            max_party_size=8,
            active_accounts=[
                _FakeAccountRecord(f'alt{index}@example.com', index + 2, f'Alt {index}') for index in range(8)
            ],
        )
        self.assertFalse(over_capacity.can_load)
        self.assertEqual(over_capacity.capacity.forecast_final_slots, 9)
        self.assertTrue(any('would use 9 of 8' in message for message in over_capacity.blocking_messages))

        team = self._team_with_alts(['alt1@example.com', 'alt2@example.com'], [28, 29])
        existing_alt = self._mixed_preflight(
            team,
            players=[_FakePartyPlayer(1), _FakePartyPlayer(2)],
            heroes=[_FakePartyHero(28, 1), _FakePartyHero(29, 1)],
            active_accounts=[
                _FakeAccountRecord('alt1@example.com', 2, 'Alt 1', party_id=10),
                _FakeAccountRecord('alt2@example.com', 3, 'Alt 2'),
            ],
        )
        self.assertTrue(existing_alt.can_load)
        self.assertEqual(existing_alt.capacity.configured_alt_present_count, 1)
        self.assertEqual(existing_alt.capacity.missing_alt_count, 1)
        self.assertEqual(existing_alt.capacity.forecast_final_slots, 5)

        replacement = self.module.calculate_mixed_capacity(8, 4, 3, 4, 3)
        self.assertEqual(replacement.forecast_final_slots, 8)

    def test_solo_candidate_requires_authoritative_party_query(self) -> None:
        team = self._team_with_alts(['solo@example.com'])
        preflight = self._mixed_preflight(
            team,
            max_party_size=6,
            active_accounts=[
                _FakeAccountRecord(
                    'solo@example.com',
                    2,
                    'Solo Alt',
                    party_id=20,
                    party_position=0,
                )
            ],
        )

        self.assertTrue(preflight.can_load)
        status = preflight.alt_statuses[0]
        self.assertEqual(status.status, 'query_required')
        self.assertEqual(status.party_state, 'unknown')
        self.assertEqual(status.known_party_member_count, 1)
        self.assertEqual(preflight.capacity.missing_alt_count, 1)
        self.assertEqual(preflight.capacity.forecast_final_slots, 2)

    def test_alt_with_known_remote_party_peer_remains_incompatible(self) -> None:
        team = self._team_with_alts(['grouped@example.com'])
        preflight = self._mixed_preflight(
            team,
            active_accounts=[
                _FakeAccountRecord(
                    'grouped@example.com',
                    2,
                    'Grouped Alt',
                    party_id=20,
                    party_position=0,
                ),
                _FakeAccountRecord(
                    'other@example.com',
                    3,
                    'Other Player',
                    party_id=20,
                    party_position=1,
                    is_party_leader=False,
                ),
            ],
        )

        self.assertFalse(preflight.can_load)
        self.assertEqual(preflight.alt_statuses[0].status, 'incompatible_party')
        self.assertEqual(preflight.alt_statuses[0].party_state, 'other_party')
        self.assertTrue(any('different party' in message for message in preflight.blocking_messages))

    def test_nonleader_alt_is_incompatible_even_without_visible_peer_record(self) -> None:
        team = self._team_with_alts(['nonleader@example.com'])
        preflight = self._mixed_preflight(
            team,
            active_accounts=[
                _FakeAccountRecord(
                    'nonleader@example.com',
                    2,
                    'Nonleader Alt',
                    party_id=20,
                    party_position=1,
                    is_party_leader=False,
                )
            ],
        )

        self.assertFalse(preflight.can_load)
        self.assertEqual(preflight.alt_statuses[0].status, 'incompatible_party')
        self.assertEqual(preflight.alt_statuses[0].party_evidence, 'party position is not zero')

    def test_alt_with_unavailable_shared_party_identity_requires_query(self) -> None:
        team = self._team_with_alts(['ambiguous@example.com'])
        preflight = self._mixed_preflight(
            team,
            active_accounts=[
                _FakeAccountRecord(
                    'ambiguous@example.com',
                    2,
                    'Ambiguous Alt',
                    party_id=0,
                    party_position=0,
                )
            ],
        )

        self.assertTrue(preflight.can_load)
        self.assertEqual(preflight.alt_statuses[0].status, 'query_required')
        self.assertEqual(preflight.alt_statuses[0].party_state, 'unknown')

    def test_joined_alt_is_present_and_not_counted_as_missing(self) -> None:
        team = self._team_with_alts(['joining@example.com'])
        config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
        party = _FakePartyApi([_FakePartyPlayer(1)])
        account = _FakeAccountRecord(
            'joining@example.com',
            2,
            'Joining Alt',
            party_id=20,
            party_position=0,
        )
        shared_memory = _FakeSharedMemory([account])
        map_api = _FakeMapApi(6)

        before = self.module.build_mixed_team_preflight(
            config,
            team.team_id,
            map_api=map_api,
            party_api=party,
            player_api=_FakePlayerApi(),
            shared_memory=shared_memory,
        )

        self.assertTrue(before.can_load)
        self.assertEqual(before.capacity.missing_alt_count, 1)
        self.assertEqual(before.capacity.forecast_final_slots, 2)

        party.players = [_FakePartyPlayer(1), _FakePartyPlayer(2)]
        account.AgentPartyData.PartyID = 10
        account.AgentPartyData.PartyPosition = 1
        account.AgentPartyData.IsPartyLeader = False
        after = self.module.build_mixed_team_preflight(
            config,
            team.team_id,
            map_api=map_api,
            party_api=party,
            player_api=_FakePlayerApi(),
            shared_memory=shared_memory,
        )

        self.assertTrue(after.can_load)
        self.assertEqual(after.alt_statuses[0].status, 'in_party')
        self.assertEqual(after.capacity.configured_alt_present_count, 1)
        self.assertEqual(after.capacity.missing_alt_count, 0)
        self.assertEqual(after.capacity.current_party_size, 2)
        self.assertEqual(after.capacity.forecast_final_slots, 2)

    def _cache_party_state_result(
        self,
        operation,
        *,
        mode: str,
        result: str = '',
        party_size: int = 1,
        player_count: int = 1,
        hero_count: int = 0,
        henchman_count: int = 0,
        other_count: int = 0,
        party_id: int = 20,
        party_position: int = 0,
        is_party_leader: bool = True,
        is_loaded: bool = True,
    ) -> None:
        status = operation._status_by_index(operation._party_query_binding_index)
        self.assertIsNotNone(status)
        request_id = operation._party_query_id
        received_after = (
            operation._party_query_sent_at if mode == self.module.PARTY_STATE_QUERY_REPLY else operation._invite_sent_at
        )
        cache = sys.modules['Py4GWCoreLib.GlobalCache'].GLOBAL_CACHE._hero_team_party_state_query_cache
        cache[(status.account_email, request_id)] = {
            'mode': mode,
            'request_id': request_id,
            'sender_email': status.account_email,
            'receiver_email': 'main@example.com',
            'character_name': status.character_name if mode == self.module.PARTY_STATE_QUERY_REPLY else '',
            'result': result,
            'party_size': party_size,
            'player_count': player_count,
            'hero_count': hero_count,
            'henchman_count': henchman_count,
            'other_count': other_count,
            'party_id': party_id,
            'party_position': party_position,
            'is_party_leader': is_party_leader,
            'is_loaded': is_loaded,
            'map_signature': (100, 1, 1, 0),
            'message_timestamp': 1,
            'received_at': max(float(received_after) + 0.001, time.monotonic()),
        }
        operation._next_at = 0.0

    def test_capacity_categories_are_authoritative_and_remote_occupants_are_retained(self) -> None:
        team = self._team_with_alts(['alt@example.com'])
        preflight = self._mixed_preflight(
            team,
            max_party_size=5,
            players=[_FakePartyPlayer(1), _FakePartyPlayer(99)],
            heroes=[_FakePartyHero(20, 99)],
            henchmen=[types.SimpleNamespace()],
            others=[types.SimpleNamespace()],
            active_accounts=[_FakeAccountRecord('alt@example.com', 2, 'Alt')],
        )

        self.assertFalse(preflight.can_load)
        self.assertEqual(preflight.capacity.current_party_size, 5)
        self.assertEqual(preflight.capacity.local_player_count, 1)
        self.assertEqual(preflight.capacity.configured_alt_present_count, 0)
        self.assertEqual(preflight.capacity.unmanaged_player_count, 1)
        self.assertEqual(preflight.capacity.remote_hero_count, 1)
        self.assertEqual(preflight.capacity.unknown_hero_count, 0)
        self.assertEqual(preflight.capacity.henchman_count, 1)
        self.assertEqual(preflight.capacity.other_occupant_count, 1)
        self.assertEqual(preflight.capacity.forecast_final_slots, 6)
        self.assertEqual(
            preflight.capacity.local_player_count
            + preflight.capacity.configured_alt_present_count
            + preflight.capacity.unmanaged_player_count
            + preflight.capacity.local_hero_count
            + preflight.capacity.remote_hero_count
            + preflight.capacity.unknown_hero_count
            + preflight.capacity.henchman_count
            + preflight.capacity.other_occupant_count,
            preflight.capacity.current_party_size,
        )

    def test_remote_hero_with_same_id_does_not_satisfy_local_target(self) -> None:
        team = self._team_with_alts(['alt@example.com'], [2])
        party = _FakePartyApi(
            [_FakePartyPlayer(1), _FakePartyPlayer(2)],
            [_FakePartyHero(2, 2)],
        )
        account = _FakeAccountRecord('alt@example.com', 2, 'Alt', party_id=10)
        config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
        preflight = self.module.build_mixed_team_preflight(
            config,
            team.team_id,
            map_api=_FakeMapApi(4),
            party_api=party,
            player_api=_FakePlayerApi(),
            shared_memory=_FakeSharedMemory([account]),
        )

        self.assertTrue(preflight.can_load)
        self.assertEqual(self.module.current_local_hero_ids(party, 1), set())
        self.assertEqual(preflight.plan.slots[0].hero_id, 2)
        self.assertEqual(preflight.capacity.remote_hero_count, 1)
        self.assertEqual(preflight.capacity.target_local_hero_count, 1)
        self.assertEqual(preflight.capacity.local_heroes_to_add, 1)
        self.assertEqual(preflight.capacity.forecast_final_slots, 4)

    def test_save_current_team_captures_only_locally_owned_heroes(self) -> None:
        team = self._team_with_alts([])
        config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
        party = _FakePartyApi(
            [_FakePartyPlayer(1), _FakePartyPlayer(2)],
            [_FakePartyHero(28, 1), _FakePartyHero(29, 2)],
        )
        previous = self._install_runtime_modules(party, _FakeSharedMemory([]))
        try:
            saved_team, saved_count = self.module.save_current_party_as_team(config, party_api=party)

            self.assertEqual(saved_count, 1)
            self.assertEqual([slot.hero_id for slot in saved_team.slots if slot.hero_id > 0], [28])
        finally:
            self._restore_runtime_modules(previous)

    def test_unknown_owner_blocks_unsafe_local_replacement(self) -> None:
        team = self._team_with_alts([], [4])
        preflight = self._mixed_preflight(
            team,
            heroes=[_FakePartyHero(2, 1), _FakePartyHero(3, 0)],
        )

        self.assertFalse(preflight.can_load)
        self.assertTrue(
            any(
                'remote or unknown-owner heroes prevent a safe local hero replacement' in message
                for message in preflight.blocking_messages
            )
        )
        self.assertEqual(preflight.capacity.unknown_hero_count, 1)

    def test_alt_statuses_distinguish_ready_wrong_character_stale_and_offline(self) -> None:
        team = self._team_with_alts(
            ['ready@example.com', 'wrong@example.com', 'stale@example.com', 'offline@example.com']
        )
        team.alt_members[1].expected_character_name = 'Expected'
        ready = _FakeAccountRecord('ready@example.com', 2, 'Ready')
        wrong = _FakeAccountRecord('wrong@example.com', 3, 'Actual')
        stale = _FakeAccountRecord('stale@example.com', 4, 'Stale', active=False)
        preflight = self._mixed_preflight(
            team,
            active_accounts=[ready, wrong],
            all_accounts=[ready, wrong, stale],
        )
        statuses = {status.account_email: status for status in preflight.alt_statuses}

        self.assertEqual(statuses['ready@example.com'].status, 'query_required')
        self.assertEqual(statuses['ready@example.com'].party_state, 'unknown')
        self.assertEqual(statuses['wrong@example.com'].status, 'wrong_character')
        self.assertEqual(statuses['stale@example.com'].status, 'stale')
        self.assertTrue(statuses['stale@example.com'].is_stale)
        self.assertEqual(statuses['offline@example.com'].status, 'offline')

    def test_inconsistent_party_components_fail_closed(self) -> None:
        team = self._team_with_alts([])
        preflight = self._mixed_preflight(team, reported_size=2)

        self.assertFalse(preflight.can_load)
        self.assertTrue(any('party components are inconsistent' in message for message in preflight.blocking_messages))

    def test_mixed_dispatch_uses_owner_safe_operation_without_leave_party(self) -> None:
        hero_only_team = self._team_with_alts([], [28])
        hero_only_config = self.module.HeroTeamConfig(
            active_team_id=hero_only_team.team_id,
            teams=[hero_only_team],
        )
        legacy_operation = self.module.create_apply_operation(hero_only_config, hero_only_team.team_id)

        mixed_team = self._team_with_alts(['alt@example.com'], [28])
        mixed_config = self.module.HeroTeamConfig(active_team_id=mixed_team.team_id, teams=[mixed_team])
        mixed_operation = self.module.create_apply_operation(mixed_config, mixed_team.team_id)

        self.assertIsInstance(legacy_operation, self.module.HeroTeamApplyOperation)
        self.assertIsInstance(mixed_operation, self.module.MixedHeroTeamApplyOperation)
        mixed_source = HELPER_PATH.read_text(encoding='utf-8').split('class MixedHeroTeamApplyOperation:', 1)[1]
        mixed_source = mixed_source.split('def create_apply_operation', 1)[0]
        self.assertNotIn('LeaveParty', mixed_source)

    def test_mixed_operation_invites_missing_alt_through_existing_invite_surfaces(self) -> None:
        team = self._team_with_alts(['alt@example.com'])
        party = _FakePartyApi([_FakePartyPlayer(1)])
        shared_memory = _FakeSharedMemory([_FakeAccountRecord('alt@example.com', 2, 'Alt')])
        previous = self._install_runtime_modules(party, shared_memory)
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertFalse(operation.tick())
            self.assertEqual(party.invites, [])
            self.assertEqual(len(shared_memory.messages), 1)
            self.assertEqual(shared_memory.messages[0][0:2], ('main@example.com', 'alt@example.com'))
            self.assertEqual(shared_memory.messages[0][2], 'PartyStateQuery')
            self.assertEqual(shared_memory.messages[0][4][0], self.module.PARTY_STATE_QUERY_REQUEST)
            self.assertEqual(operation._phase, 'wait_party_query')

            self._cache_party_state_result(
                operation,
                mode=self.module.PARTY_STATE_QUERY_REPLY,
            )
            self.assertFalse(operation.tick())
            self.assertEqual(party.invites, ['Alt'])
            self.assertEqual(len(shared_memory.messages), 2)
            self.assertEqual(shared_memory.messages[1][2], 'InviteToParty')
            self.assertEqual(shared_memory.messages[1][4][0], self.module.PARTY_INVITE_GUARD)
            self.assertEqual(operation._phase, 'wait_invite')

            self._cache_party_state_result(
                operation,
                mode=self.module.PARTY_STATE_GUARD_RESULT,
                result='reciprocal_invite_sent',
            )
            party.players = [_FakePartyPlayer(1), _FakePartyPlayer(2)]
            self.assertFalse(operation.tick())
            self.assertEqual(operation._phase, 'invite')
            self.assertEqual(operation.preflight.alt_statuses[0].status, 'joined')
        finally:
            self._restore_runtime_modules(previous)

    def test_mixed_operation_blocks_reciprocal_invite_when_alt_guard_reports_party_change(self) -> None:
        team = self._team_with_alts(['alt@example.com'])
        party = _FakePartyApi([_FakePartyPlayer(1)])
        shared_memory = _FakeSharedMemory([_FakeAccountRecord('alt@example.com', 2, 'Alt')])
        previous = self._install_runtime_modules(party, shared_memory)
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertFalse(operation.tick())
            self._cache_party_state_result(operation, mode=self.module.PARTY_STATE_QUERY_REPLY)
            self.assertFalse(operation.tick())
            self.assertEqual(party.invites, ['Alt'])

            self._cache_party_state_result(
                operation,
                mode=self.module.PARTY_STATE_GUARD_RESULT,
                result='guard_failed: party_changed',
                party_size=2,
                player_count=2,
                party_position=0,
            )
            self.assertTrue(operation.tick())
            self.assertFalse(operation.success)
            self.assertIn('guard_failed: party_changed', operation.message)
            self.assertEqual(party.invites, ['Alt'])
            self.assertEqual(operation.preflight.alt_statuses[0].status, 'party_changed_before_invite')
        finally:
            self._restore_runtime_modules(previous)

    def test_mixed_operation_blocks_non_solo_party_state_before_main_invite(self) -> None:
        team = self._team_with_alts(['grouped@example.com'])
        party = _FakePartyApi([_FakePartyPlayer(1)])
        shared_memory = _FakeSharedMemory([_FakeAccountRecord('grouped@example.com', 2, 'Grouped')])
        previous = self._install_runtime_modules(party, shared_memory)
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertFalse(operation.tick())
            self._cache_party_state_result(
                operation,
                mode=self.module.PARTY_STATE_QUERY_REPLY,
                party_size=2,
                player_count=2,
                party_position=0,
            )
            self.assertTrue(operation.tick())
            self.assertFalse(operation.success)
            self.assertIn('not solo', operation.message)
            self.assertEqual(party.invites, [])
            self.assertEqual(len(shared_memory.messages), 1)
            self.assertEqual(operation.preflight.alt_statuses[0].status, 'incompatible_party')
        finally:
            self._restore_runtime_modules(previous)

    def test_messaging_guard_rechecks_live_party_before_reciprocal_invite(self) -> None:
        functions = _load_messaging_party_state_functions()
        console = types.SimpleNamespace(
            MessageType=types.SimpleNamespace(Info='info', Warning='warning', Error='error')
        )
        main_account = _FakeAccountRecord('main@example.com', 1, 'Main')
        shared_memory = _FakeSharedMemory([], [main_account])
        message = types.SimpleNamespace(
            SenderEmail='main@example.com',
            ReceiverEmail='alt@example.com',
            ExtraData=('party_invite_guard', 'request-1', 'Player 2', '100,1,1,0'),
            Params=(0, 0, 0, 0),
            Timestamp=1,
        )
        query_message = types.SimpleNamespace(
            SenderEmail='main@example.com',
            ReceiverEmail='alt@example.com',
            ExtraData=('party_state_request', 'request-1', 'Alt', '100,1,1,0'),
            Params=(0, 0, 0, 0),
            Timestamp=1,
        )

        for players, expected_size, expected_result, expected_invites in (
            ([_FakePartyPlayer(2)], 1, 'reciprocal_invite_sent', ['Main']),
            ([_FakePartyPlayer(2), _FakePartyPlayer(99)], 2, 'guard_failed: party_changed', []),
        ):
            party = _FakePartyApi(players)
            party.GetOwnPartyNumber = lambda: 0
            functions.update(
                {
                    'GLOBAL_CACHE': types.SimpleNamespace(Party=party, ShMem=shared_memory),
                    'Player': _FakePlayerApi('alt@example.com', 2),
                    'Map': _FakeMapApi(8),
                    'SharedCommandType': types.SimpleNamespace(PartyStateQuery='PartyStateQuery'),
                    'MODULE_NAME': 'Messaging',
                    'Console': console,
                    'ConsoleLog': lambda *_args, **_kwargs: None,
                    '_extra_data': lambda current_message: tuple(current_message.ExtraData),
                }
            )
            shared_memory.messages.clear()

            list(functions['PartyStateQuery'](0, query_message))
            self.assertEqual(len(shared_memory.messages), 1)
            self.assertEqual(shared_memory.messages[0][2], 'PartyStateQuery')
            self.assertEqual(shared_memory.messages[0][3][0], float(expected_size))
            self.assertEqual(shared_memory.messages[0][3][1], float(expected_size))
            self.assertEqual(shared_memory.messages[0][4][0], 'party_state_reply')
            self.assertEqual(shared_memory.messages[0][4][2], 'Player 2')
            shared_memory.messages.clear()

            list(functions['InviteToParty'](0, message))

            self.assertEqual(party.invites, expected_invites)
            self.assertEqual(len(shared_memory.messages), 1)
            self.assertEqual(shared_memory.messages[0][2], 'PartyStateQuery')
            self.assertEqual(shared_memory.messages[0][4][0], 'party_state_guard')
            self.assertEqual(shared_memory.messages[0][4][2], expected_result)

    def test_party_state_query_send_path_resolves_legacy_command_members(self) -> None:
        send_message, command_type = _load_authoritative_all_accounts_send_message()

        self.assertEqual(int(command_type.AddModelToLootWhitelist), 71)
        self.assertEqual(int(command_type.AccountSettingsSync), 72)
        self.assertEqual(int(command_type.AccountSettingsSyncResult), 73)
        self.assertEqual(int(command_type.PartyStateQuery), 74)

        harness = _RealSharedMemorySendHarness('alt@example.com')
        message_index = send_message(
            harness,
            'main@example.com',
            'alt@example.com',
            command_type.PartyStateQuery,
            (0, 0, 0, 0),
            ('party_state_request', 'request-1', 'Alt', '100,1,1,0'),
        )

        self.assertEqual(message_index, 0)
        self.assertEqual(harness.Inbox[message_index].Command, int(command_type.PartyStateQuery))
        self.assertTrue(harness.Inbox[message_index].Active)

    def test_mixed_operation_revalidates_alt_departure_before_hero_mutation(self) -> None:
        team = self._team_with_alts(['alt@example.com'])
        party = _FakePartyApi([_FakePartyPlayer(1), _FakePartyPlayer(2)])
        account = _FakeAccountRecord('alt@example.com', 2, 'Alt', party_id=10)
        shared_memory = _FakeSharedMemory([account])
        previous = self._install_runtime_modules(party, shared_memory)
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)
            operation._joined_binding_indices = {0}
            party.players = [_FakePartyPlayer(1)]

            preflight = operation._refresh_preflight()

            self.assertFalse(preflight.can_load)
            self.assertTrue(any('left or changed state' in message for message in preflight.blocking_messages))
            self.assertEqual(party.kick_all_calls, 0)
            self.assertEqual(party.leave_party_calls, 0)
        finally:
            self._restore_runtime_modules(previous)

    def test_mixed_operation_blocks_over_capacity_before_invites_or_mutations(self) -> None:
        team = self._team_with_alts([f'alt{index}@example.com' for index in range(8)])
        party = _FakePartyApi([_FakePartyPlayer(1)])
        accounts = [_FakeAccountRecord(f'alt{index}@example.com', index + 2, f'Alt {index}') for index in range(8)]
        shared_memory = _FakeSharedMemory(accounts)
        previous = self._install_runtime_modules(party, shared_memory, _FakeMapApi(8))
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertTrue(operation.tick())
            self.assertFalse(operation.success)
            self.assertEqual(party.invites, [])
            self.assertEqual(shared_memory.messages, [])
            self.assertEqual(party.kick_all_calls, 0)
            self.assertEqual(party.leave_party_calls, 0)
        finally:
            self._restore_runtime_modules(previous)

    def test_mixed_operation_preserves_unmanaged_real_players_when_capacity_blocks(self) -> None:
        team = self._team_with_alts(['alt@example.com'])
        party = _FakePartyApi([_FakePartyPlayer(1), _FakePartyPlayer(99)])
        shared_memory = _FakeSharedMemory([_FakeAccountRecord('alt@example.com', 2, 'Alt')])
        previous = self._install_runtime_modules(party, shared_memory, _FakeMapApi(2))
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertTrue(operation.tick())
            self.assertFalse(operation.success)
            self.assertEqual([player.login_number for player in party.players], [1, 99])
            self.assertEqual(party.invites, [])
            self.assertEqual(party.kick_all_calls, 0)
            self.assertEqual(party.leave_party_calls, 0)
        finally:
            self._restore_runtime_modules(previous)

    def test_mixed_operation_uses_unscoped_clear_only_after_all_heroes_are_local(self) -> None:
        team = self._team_with_alts(['alt@example.com'], [28])
        party = _FakePartyApi(
            [_FakePartyPlayer(1), _FakePartyPlayer(2)],
            [_FakePartyHero(28, 1)],
        )
        account = _FakeAccountRecord('alt@example.com', 2, 'Alt', party_id=10)
        shared_memory = _FakeSharedMemory([account])
        previous = self._install_runtime_modules(party, shared_memory)
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertFalse(operation.tick())
            self.assertEqual(party.kick_all_calls, 1)
            self.assertEqual(party.leave_party_calls, 0)
            self.assertEqual(operation._phase, 'wait_local_clear')
        finally:
            self._restore_runtime_modules(previous)

    def test_mixed_operation_never_clears_or_leaves_around_remote_heroes(self) -> None:
        team = self._team_with_alts(['alt@example.com'], [4])
        party = _FakePartyApi(
            [_FakePartyPlayer(1), _FakePartyPlayer(2)],
            [_FakePartyHero(2, 1), _FakePartyHero(3, 2)],
        )
        account = _FakeAccountRecord('alt@example.com', 2, 'Alt', party_id=10)
        shared_memory = _FakeSharedMemory([account])
        previous = self._install_runtime_modules(party, shared_memory)
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            self.assertTrue(operation.tick())
            self.assertFalse(operation.success)
            self.assertEqual(party.kick_all_calls, 0)
            self.assertEqual(party.leave_party_calls, 0)
            self.assertEqual([player.login_number for player in party.players], [1, 2])
        finally:
            self._restore_runtime_modules(previous)

    def test_mixed_operation_retains_remote_hero_when_no_local_replacement_is_needed(self) -> None:
        team = self._team_with_alts(['alt@example.com'])
        party = _FakePartyApi(
            [_FakePartyPlayer(1), _FakePartyPlayer(2)],
            [_FakePartyHero(3, 2)],
        )
        account = _FakeAccountRecord('alt@example.com', 2, 'Alt', party_id=10)
        previous = self._install_runtime_modules(party, _FakeSharedMemory([account]), _FakeMapApi(3))
        try:
            config = self.module.HeroTeamConfig(active_team_id=team.team_id, teams=[team])
            operation = self.module.MixedHeroTeamApplyOperation(config, team.team_id)

            for _ in range(5):
                operation.tick()

            self.assertTrue(operation.done)
            self.assertTrue(operation.success)
            self.assertEqual([(hero.hero_id, hero.owner_player_id) for hero in party.heroes], [(3, 2)])
            self.assertEqual(party.kick_all_calls, 0)
            self.assertEqual(party.leave_party_calls, 0)
        finally:
            self._restore_runtime_modules(previous)

    def test_legacy_shape_normalizes_and_round_trips_all_persisted_data(self) -> None:
        raw = {
            'version': 1,
            'active_team_id': 'team-b',
            'hero_names': {'28': 'Mali', '34': 'Yazumi'},
            'hero_profession_cache': {
                '28:mali': {
                    'hero_id': 28,
                    'identity_name': 'Mali',
                    'primary_profession_id': 5,
                    'secondary_profession_id': 0,
                },
                '34:yazumi': {
                    'hero_id': 34,
                    'identity_name': 'Yazumi',
                    'primary_profession_id': 4,
                    'secondary_profession_id': 0,
                },
            },
            'teams': [
                {'id': 'team-a', 'name': 'A', 'slots': [{'hero_id': 34, 'template_id': 'template-1'}]},
                {'id': 'team-b', 'name': 'B', 'slots': [{'hero_id': 2, 'behavior': 1}]},
            ],
            'templates': [
                {
                    'id': 'template-1',
                    'name': 'Build',
                    'code': 'CODE',
                    'hero_id': 28,
                }
            ],
        }
        config = self.module.normalize_config(raw)
        payload = self.module.config_to_dict(config)

        self.assertEqual(config.active_team_id, 'team-b')
        self.assertEqual(len(config.teams), 2)
        self.assertEqual(len(config.teams[0].slots), self.module.HERO_SLOT_COUNT)
        self.assertEqual(config.teams[0].slots[0].hero_id, 34)
        self.assertEqual(config.templates[0].template_id, 'template-1')
        self.assertEqual(config.template_preferences['template-1'], 28)
        self.assertEqual(config.hero_names['28'], 'Mali')
        self.assertEqual(config.hero_names['34'], 'Yazumi')
        self.assertEqual(config.hero_profession_cache['28:mali']['primary_profession_id'], 5)
        self.assertEqual(config.hero_profession_cache['34:yazumi']['primary_profession_id'], 4)
        self.assertEqual(payload['active_team_id'], 'team-b')
        self.assertEqual(payload['teams'][0]['slots'][0]['template_id'], 'template-1')
        self.assertEqual(payload['templates'][0]['code'], 'CODE')
        self.assertNotIn('hero_id', payload['templates'][0])
        self.assertEqual(payload['hero_names']['28'], 'Mali')
        self.assertIn('28:mali', payload['hero_profession_cache'])

    def test_editable_data_waits_for_explicit_save_but_profession_cache_is_immediate(self) -> None:
        document = self.module._config_document()
        document.data = {}
        global_document = self.module._template_library_document()
        global_document.data = {}
        config = self.module.default_config('test-account')
        config.teams[0].name = 'Unsaved team edit'
        self.assertEqual(document.data, {})

        self.module.save_config(config, 'test-account')
        self.assertEqual(document.data['teams'][0]['name'], 'Unsaved team edit')
        self.assertNotIn('templates', document.data)
        saved_teams = copy.deepcopy(document.data['teams'])
        config.teams[0].name = 'Still not saved'
        self.assertEqual(document.data['teams'], saved_teams)

        self.module._remember_persisted_hero_profession(config, 28, 'Mali', 5)
        self.assertEqual(document.data['teams'], saved_teams)
        self.assertEqual(document.data['hero_profession_cache']['28:mali']['primary_profession_id'], 5)

    def test_global_template_save_uses_per_template_paths_and_account_preferences_stay_local(self) -> None:
        account_document = self.module._config_document()
        global_document = self.module._template_library_document()
        account_document.data = {}
        global_document.data = {}
        config = self.module.default_config('test-account')
        template = self.module.add_template(config, 'Mercenary Build', 'CODE', hero_id=28)

        self.module.save_config(config, 'test-account')

        self.assertEqual(
            global_document.data['templates'][template.template_id],
            {'name': 'Mercenary Build', 'code': 'CODE'},
        )
        self.assertEqual(account_document.data['template_preferences'][template.template_id], 28)
        self.assertNotIn('templates', account_document.data)
        self.assertIn(('set_json', f'templates/{template.template_id}'), global_document.operations)

        self.module.save_template_name(template.template_id, 'Renamed Mercenary Build')
        self.assertEqual(
            global_document.data['templates'][template.template_id],
            {'name': 'Renamed Mercenary Build', 'code': 'CODE'},
        )
        self.assertIn(('set_json', f'templates/{template.template_id}/name'), global_document.operations)

        config.templates = []
        self.module.save_config(config, 'test-account', deleted_template_ids={template.template_id})
        self.assertNotIn(template.template_id, global_document.data.get('templates', {}))
        self.assertIn(('delete', f'templates/{template.template_id}'), global_document.operations)

    def test_migration_is_idempotent_and_preserves_team_references(self) -> None:
        account_document = self.module._config_document()
        global_document = self.module._template_library_document()
        account_document.data = {
            'version': 1,
            'active_team_id': 'team-a',
            'teams': [
                {
                    'id': 'team-a',
                    'name': 'Main',
                    'slots': [{'hero_id': 28, 'template_id': 'template-1'}],
                }
            ],
            'templates': [
                {'id': 'template-1', 'name': 'Mercenary Build', 'code': 'CODE', 'hero_id': 28},
                {'id': 'template-2', 'name': 'Empty Build', 'code': '', 'hero_id': 0},
            ],
            'hero_names': {'28': 'Mali'},
            'hero_profession_cache': {},
        }
        global_document.data = {}

        config = self.module.load_config('test-account')

        self.assertEqual([template.template_id for template in config.templates], ['template-1', 'template-2'])
        self.assertEqual(config.template_preferences['template-1'], 28)
        self.assertEqual(config.teams[0].slots[0].template_id, 'template-1')
        self.assertNotIn('templates', account_document.data)
        self.assertTrue(account_document.data['migrations']['global_templates_v1']['completed'])
        first_account = copy.deepcopy(account_document.data)
        first_global = copy.deepcopy(global_document.data)

        second = self.module.load_config('test-account')

        self.assertEqual(second.teams[0].slots[0].template_id, 'template-1')
        self.assertEqual(account_document.data, first_account)
        self.assertEqual(global_document.data, first_global)

    def test_current_reforged_fixture_preserves_all_sixteen_templates_and_references(self) -> None:
        source, global_source = _current_reforged_fixture()
        account_document = self.module._config_document()
        global_document = self.module._template_library_document()
        account_document.data = copy.deepcopy(source)
        global_document.data = copy.deepcopy(global_source)
        expected_templates = {
            str(template_id): (str(template['name']), str(template['code']))
            for template_id, template in global_source['templates'].items()
        }

        config = self.module.load_config('guildwars1c.postcard534@simplelogin.com')

        expected_ids = set(expected_templates)
        actual_ids = {template.template_id for template in config.templates}
        actual_templates = {
            template.template_id: (template.name, template.code) for template in config.templates
        }
        referenced_ids = {
            str(slot['template_id'])
            for team in source['teams']
            for slot in team['slots']
            if str(slot.get('template_id', '') or '')
        }
        expected_reference_sequence = [
            str(slot['template_id'])
            for team in source['teams']
            for slot in team['slots']
            if str(slot.get('template_id', '') or '')
        ]
        actual_references = {
            slot.template_id
            for team in config.teams
            for slot in team.slots
            if slot.template_id
        }
        actual_reference_sequence = [
            slot.template_id for team in config.teams for slot in team.slots if slot.template_id
        ]

        self.assertEqual(actual_ids, expected_ids)
        self.assertEqual(actual_templates, expected_templates)
        self.assertEqual(len(expected_templates), 16)
        self.assertEqual(len(config.templates), len(expected_templates))
        self.assertEqual(len(actual_references), len(referenced_ids))
        self.assertTrue(actual_references.issubset(actual_ids))
        self.assertEqual(actual_reference_sequence, expected_reference_sequence)
        self.assertNotIn('templates', account_document.data)
        self.assertEqual(set(global_document.data['templates']), expected_ids)

    def test_conflicting_id_gets_deterministic_remap_without_overwrite(self) -> None:
        account_document = self.module._config_document()
        global_document = self.module._template_library_document()
        account_document.data = {
            'version': 1,
            'teams': [{'id': 'team-a', 'name': 'A', 'slots': [{'hero_id': 2, 'template_id': 'same-id'}]}],
            'templates': [{'id': 'same-id', 'name': 'Account Build', 'code': 'ACCOUNT'}],
        }
        global_document.data = {
            'version': 1,
            'templates': {'same-id': {'name': 'Other Build', 'code': 'OTHER'}},
        }

        config = self.module.load_config('test-account')

        remapped_id = config.teams[0].slots[0].template_id
        self.assertNotEqual(remapped_id, 'same-id')
        self.assertEqual(global_document.data['templates']['same-id'], {'name': 'Other Build', 'code': 'OTHER'})
        self.assertEqual(global_document.data['templates'][remapped_id], {'name': 'Account Build', 'code': 'ACCOUNT'})
        self.assertEqual(account_document.data['migrations']['global_templates_v1']['id_remap']['same-id'], remapped_id)

    def test_migration_keeps_migrated_view_if_account_marker_write_fails(self) -> None:
        account_document = self.module._config_document()
        global_document = self.module._template_library_document()
        account_document.data = {
            'version': 1,
            'teams': [{'id': 'team-a', 'name': 'A', 'slots': [{'hero_id': 2, 'template_id': 'same-id'}]}],
            'templates': [{'id': 'same-id', 'name': 'Account Build', 'code': 'ACCOUNT'}],
        }
        global_document.data = {
            'version': 1,
            'templates': {'same-id': {'name': 'Other Build', 'code': 'OTHER'}},
        }
        original_save = account_document.save
        setattr(account_document, 'save', lambda: False)
        try:
            config = self.module.load_config('test-account')
        finally:
            setattr(account_document, 'save', original_save)

        remapped_id = config.teams[0].slots[0].template_id
        self.assertNotEqual(remapped_id, 'same-id')
        self.assertEqual(config.templates[0].template_id, 'same-id')
        self.assertIn(remapped_id, {template.template_id for template in config.templates})

    def test_missing_global_template_reference_is_preserved_and_reported(self) -> None:
        raw = {
            'version': 2,
            'active_team_id': 'team-a',
            'teams': [
                {
                    'id': 'team-a',
                    'name': 'A',
                    'slots': [{'hero_id': 2, 'template_id': 'deleted-template'}],
                }
            ],
            'template_preferences': {'deleted-template': 28},
        }
        config = self.module.normalize_config(
            raw,
            global_templates=[{'id': 'other-template', 'name': 'Other', 'code': 'OTHER'}],
        )

        self.assertEqual(config.teams[0].slots[0].template_id, 'deleted-template')
        self.assertEqual(config.template_preferences['deleted-template'], 28)
        preflight = self.module.build_load_preflight(config, include_runtime=False)
        warnings = [warning.code for warning in preflight.row_warnings.get(0, [])]
        self.assertIn('missing_template_reference', warnings)
        self.assertTrue(preflight.plan.slots[0].template_missing)
        self.assertFalse(preflight.plan.slots[0].clear_skillbar)

        delete_config = self.module.normalize_config(
            raw,
            global_templates=[{'id': 'deleted-template', 'name': 'Deleted', 'code': 'CODE'}],
        )
        self.assertTrue(self.module.delete_template(delete_config, 'deleted-template'))
        self.assertEqual(delete_config.teams[0].slots[0].template_id, 'deleted-template')

        inline_config = self.module.normalize_config(
            {
                'version': 2,
                'active_team_id': 'team-a',
                'teams': [
                    {
                        'id': 'team-a',
                        'name': 'A',
                        'slots': [
                            {
                                'hero_id': 2,
                                'template_id': 'deleted-template',
                                'template_code': 'OQAA...inline',
                            }
                        ],
                    }
                ],
                'template_preferences': {'deleted-template': 28},
            },
            global_templates=[],
        )
        inline_preflight = self.module.build_load_preflight(inline_config, include_runtime=False)
        inline_warning = inline_preflight.row_warnings[0][0]
        self.assertEqual(inline_warning.code, 'missing_template_reference_inline_override')
        self.assertEqual(inline_warning.severity, 'info')
        self.assertEqual(inline_preflight.plan.slots[0].template_code, 'OQAA...inline')
        self.assertFalse(inline_preflight.plan.slots[0].template_missing)

    def test_three_way_merge_preserves_independent_peer_changes_and_reports_same_id_conflicts(self) -> None:
        base = [self.module.HeroTemplateEntry('a', 'A', '1')]
        local = [self.module.HeroTemplateEntry('a', 'A local', '1'), self.module.HeroTemplateEntry('b', 'B', '2')]
        remote = [self.module.HeroTemplateEntry('a', 'A', '1'), self.module.HeroTemplateEntry('c', 'C', '3')]

        merged, conflicts = self.module.merge_template_libraries(base, local, remote)

        self.assertEqual(conflicts, [])
        self.assertEqual({template.template_id for template in merged}, {'a', 'b', 'c'})

        conflicting_remote = [self.module.HeroTemplateEntry('a', 'A remote', '1')]
        _merged, conflicts = self.module.merge_template_libraries(base, local, conflicting_remote)
        self.assertEqual(conflicts, ['a'])

    def test_widget_save_keeps_account_and_global_drafts_separate(self) -> None:
        widget = self.widget
        config = self.module.default_config('test-account')
        template = self.module.add_template(config, 'Build', 'ORIGINAL')
        setattr(widget, '_config', config)
        widget._capture_saved_editable_state(config)

        remote_templates = [self.module.HeroTemplateEntry(template.template_id, template.name, template.code)]
        calls: list[str] = []
        original_reload = widget.reload_global_templates
        original_save_global = widget.save_global_templates
        original_save_account = widget.save_account_config
        try:
            def fake_reload_global():
                return [
                    self.module.HeroTemplateEntry(item.template_id, item.name, item.code)
                    for item in remote_templates
                ]

            def fake_save_global(templates, *, deleted_template_ids=()):
                calls.append('global')
                remote_templates[:] = [
                    self.module.HeroTemplateEntry(item.template_id, item.name, item.code)
                    for item in templates
                ]

            def fake_save_account(_config):
                calls.append('account')

            setattr(widget, 'reload_global_templates', fake_reload_global)
            setattr(widget, 'save_global_templates', fake_save_global)
            setattr(widget, 'save_account_config', fake_save_account)

            template.code = 'GLOBAL DRAFT'
            widget._save_status()
            self.assertEqual(calls, ['global'])

            config.teams[0].name = 'ACCOUNT DRAFT'
            widget._save_status()
            self.assertEqual(calls, ['global', 'account'])
        finally:
            setattr(widget, 'reload_global_templates', original_reload)
            setattr(widget, 'save_global_templates', original_save_global)
            setattr(widget, 'save_account_config', original_save_account)
            setattr(widget, '_config', None)

    def test_widget_account_switch_discards_account_draft_but_preserves_shared_draft(self) -> None:
        widget = self.widget
        old_config = self.module.default_config('account-a')
        old_template = self.module.add_template(old_config, 'Shared', 'ORIGINAL')
        setattr(widget, '_config', old_config)
        widget._capture_saved_editable_state(old_config)
        old_config.teams[0].name = 'Account A draft'
        old_template.code = 'Shared draft'

        new_config = self.module.default_config('account-b')
        new_config.templates = [self.module.HeroTemplateEntry('remote', 'Remote', 'REMOTE')]
        original_safe_key = widget.safe_account_key
        original_load_config = widget.load_config
        try:
            setattr(widget, 'safe_account_key', lambda: 'account-b')
            setattr(widget, 'load_config', lambda _account_key: new_config)
            setattr(widget, '_status', '')

            switched = widget._ensure_config()

            self.assertEqual(switched.account_key, 'account-b')
            self.assertEqual(switched.teams[0].name, 'New Hero Team')
            self.assertEqual(switched.templates[0].template_id, old_template.template_id)
            self.assertEqual(switched.templates[0].code, 'Shared draft')
            self.assertIn('unsaved account edits were discarded', widget._status)
        finally:
            setattr(widget, 'safe_account_key', original_safe_key)
            setattr(widget, 'load_config', original_load_config)
            setattr(widget, '_config', None)

    def test_widget_reload_shared_requires_confirmation_for_dirty_global_draft(self) -> None:
        widget = self.widget
        config = self.module.default_config('test-account')
        template = self.module.add_template(config, 'Build', 'ORIGINAL')
        setattr(widget, '_config', config)
        widget._capture_saved_editable_state(config)
        template.code = 'LOCAL DRAFT'
        remote_templates = [self.module.HeroTemplateEntry(template.template_id, template.name, 'REMOTE')]
        original_reload = widget.reload_global_templates
        try:
            setattr(widget, 'reload_global_templates', lambda: list(remote_templates))
            setattr(widget, '_confirm_action', '')

            widget._reload_shared_templates()
            self.assertEqual(widget._confirm_action, 'reload_shared_templates')
            self.assertEqual(config.templates[0].code, 'LOCAL DRAFT')

            widget._reload_shared_templates(discard_unsaved=True)
            self.assertEqual(config.templates[0].code, 'REMOTE')
            self.assertFalse(widget._global_dirty(config))
        finally:
            setattr(widget, 'reload_global_templates', original_reload)
            setattr(widget, '_confirm_action', '')
            setattr(widget, '_config', None)

    def test_widget_and_helper_are_free_of_legacy_persistence_and_use_modular_helper(self) -> None:
        widget_text = WIDGET_PATH.read_text(encoding='utf-8')
        helper_text = HELPER_PATH.read_text(encoding='utf-8')
        ast.parse(widget_text, filename=str(WIDGET_PATH))
        ast.parse(helper_text, filename=str(HELPER_PATH))
        self.assertIn('from Py4GWCoreLib.modular.hero_team_manager import', widget_text)
        self.assertIn("JsonFactory(CONFIG_DOCUMENT_NAME, 'account')", helper_text)
        for forbidden in (
            'IniManager',
            'Py4GW.Console',
            'import json',
            'json.load',
            'json.dump',
            'settings_root',
            'account_config_path',
        ):
            self.assertNotIn(forbidden, widget_text + helper_text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
