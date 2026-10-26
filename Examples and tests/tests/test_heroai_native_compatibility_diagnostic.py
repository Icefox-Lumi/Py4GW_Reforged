"""Offline diagnostic checks; never load the DLL, runtime services, or live pointers.

Run with python -B. The adjacent TESTS tree is read-only contract evidence.
Only selected existing ctypes class definitions execute against test-owned
storage; their module imports, callback registrations and pointer getters do not.
"""

# pyright: strict

from __future__ import annotations

import ast
import copy
import ctypes
import importlib.util
import sys
import unittest
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT.with_name('Py4GW_Reforged-main TESTS')
WIDGET = ROOT / 'Widgets/Coding/Debug/Py4GW/HeroAI Native Compatibility Diagnostic.py'
CONTEXT = TESTS / 'Py4GWCoreLib/native_src/context/PartyContext.py'


def existing_classes() -> dict[str, Any]:
    namespace: dict[str, Any] = {'ctypes': ctypes, 'Structure': ctypes.Structure, 'c_uint32': ctypes.c_uint32}
    sources = (
        (TESTS / 'Py4GWCoreLib/native_src/internals/gw_array.py', {'GW_Array'}),
        (CONTEXT, {'PlayerPartyMember', 'HeroPartyMember', 'HenchmanPartyMember'}),
    )
    for path, names in sources:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        selected: list[ast.stmt] = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
        if len(selected) != len(names):
            raise AssertionError(f'Existing contract classes missing: {path}')
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class NativeDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = existing_classes()

    def setUp(self) -> None:
        self.calls: list[str] = []
        self.output: list[str] = []
        self.clicked = False
        self.visible = True
        self.ended = 0
        self.constructed = 0
        self.local_login = 1987654321
        self.player_type = self.contract['PlayerPartyMember']
        self.hero_type = self.contract['HeroPartyMember']
        self.henchman_type = self.contract['HenchmanPartyMember']
        self.party = SimpleNamespace(
            party_id=123456789,
            is_party_loaded=True,
            is_party_leader=True,
            party_player_count=1,
            party_hero_count=0,
            party_henchman_count=0,
            party_size=1,
            players=[self.player_type(self.local_login, 0, 1)],
            heroes=[],
            henchmen=[],
        )
        self.map_values: dict[str, object] = {
            'get_is_map_loaded': True,
            'get_map_id': 226,
            'get_region': -2,
            'get_district': 1,
            'get_language': 0,
            'get_instance_type': 0,
            'get_instance_time': 10000,
        }
        self.map_module = ModuleType('PyMap')
        for name in self.map_values:
            setattr(self.map_module, name, self.reader('map.' + name, lambda key=name: self.map_values[key]))
        self.party_module = ModuleType('PyParty')
        for name in ('party_player_count', 'party_hero_count', 'party_henchman_count', 'party_size'):
            setattr(
                self.party_module,
                'get_' + name,
                self.reader('party.' + name, lambda key=name: getattr(self.party, key)),
            )
        setattr(
            self.party_module, 'get_is_party_loaded', self.reader('party.loaded', lambda: self.party.is_party_loaded)
        )
        setattr(self.party_module, 'PyParty', self.new_party)
        self.player_module = ModuleType('PyPlayer')
        setattr(self.player_module, 'get_player_number', self.reader('player.number', lambda: self.local_login))
        self.system_module = ModuleType('PySystem')
        setattr(self.system_module, 'Console', SimpleNamespace(Log=self.log))
        setattr(self.system_module, 'MessageType', SimpleNamespace(Info=0))
        self.imgui = ModuleType('PyImGui')
        setattr(self.imgui, 'WindowFlags', SimpleNamespace(AlwaysAutoResize=1, NoSavedSettings=256))
        setattr(self.imgui, 'begin', self.begin)
        setattr(self.imgui, 'button', self.button)
        setattr(self.imgui, 'text', self.text)
        setattr(self.imgui, 'text_wrapped', self.text)
        setattr(self.imgui, 'end', self.end)
        self.modules = {
            'PyMap': self.map_module,
            'PyParty': self.party_module,
            'PyPlayer': self.player_module,
            'PySystem': self.system_module,
            'PyImGui': self.imgui,
        }
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        spec = importlib.util.spec_from_file_location('_native_compatibility_diagnostic_test', WIDGET)
        assert spec and spec.loader
        self.widget = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.widget)

    def reader(self, name: str, read: Callable[[], object]) -> Callable[[], object]:
        def sample() -> object:
            self.calls.append(name)
            return read()

        return sample

    def new_party(self) -> object:
        self.constructed += 1
        return self.party

    def end(self) -> None:
        self.ended += 1

    def log(self, _sender: str, line: str, _level: object) -> None:
        self.output.append(line)

    def begin(self, _name: str, flags: int) -> bool:
        return self.visible

    def button(self, _label: str) -> bool:
        return self.clicked

    @staticmethod
    def text(_text: str) -> None:
        pass

    def capture(self) -> str:
        self.widget._capture_snapshot()
        return '\n'.join(self.output)

    def test_import_and_idle_frames_do_not_sample_or_log(self) -> None:
        self.assertEqual(self.calls, [])
        for _ in range(50):
            self.widget.main()
        self.assertEqual((self.calls, self.constructed, self.output, self.ended), ([], 0, [], 50))

    def test_click_only_one_snapshot_and_hidden_window_is_passive(self) -> None:
        self.clicked = True
        self.visible = False
        self.widget.main()
        self.assertEqual(self.calls, [])
        self.visible = True
        self.widget.main()
        self.assertEqual(self.constructed, 1)
        self.assertEqual(sum('BEGIN ' in line for line in self.output), 1)
        self.clicked = False
        before = list(self.calls)
        self.widget.main()
        self.assertEqual(self.calls, before)

    def test_actual_player_contract_never_becomes_confirmed_solo(self) -> None:
        output = self.capture()
        self.assertIn('players=1 heroes=0 henchmen=0', output)
        self.assertIn('roster=consistent local_member=True', output)
        self.assertIn('OTHERS unverified', output)
        self.assertIn('INSTANCE exact_identity=unverified', output)
        self.assertIn('SOLO unverified', output)

    def test_multiple_players_heroes_and_henchmen_are_observed_non_solo(self) -> None:
        self.party.players.append(self.player_type(987654321, 0, 1))
        self.party.heroes.append(self.hero_type(1234567890, self.local_login, 1, 0, 0, 20))
        self.party.henchmen.append(self.henchman_type(agent_id=987654321))
        self.party.party_player_count, self.party.party_hero_count, self.party.party_henchman_count = 2, 1, 1
        self.party.party_size = 4
        output = self.capture()
        self.assertIn('players=2 heroes=1 henchmen=1', output)
        self.assertIn('SOLO ineligible observed_non_solo_roster', output)

    def test_empty_default_arrays_and_invalid_counts_do_not_construct(self) -> None:
        for value in (0, -1, 65, True, '1', 2**100):
            with self.subTest(player_count=value):
                self.party.party_player_count = value
                self.output.clear()
                self.assertIn('PARTY uncertain', self.capture())
                self.assertEqual(self.constructed, 0)

    def test_missing_bindings_do_not_import_or_initialize(self) -> None:
        for missing in ('PyMap', 'PyParty', 'PyPlayer'):
            with self.subTest(missing=missing), patch.dict(sys.modules):
                sys.modules.pop(missing)
                self.output.clear()
                self.capture()
                self.assertNotIn(missing, sys.modules)
                self.assertEqual(self.constructed, 0)
                self.assertIn('unavailable', '\n'.join(self.output))
        with patch.dict(sys.modules):
            sys.modules.pop('PySystem')
            self.calls.clear()
            self.widget._capture_snapshot()
            self.assertEqual(self.calls, [])

    def test_lazy_and_initializing_modules_are_not_probed(self) -> None:
        def forbidden(_name: str) -> object:
            self.fail('lazy native import was invoked')

        setattr(self.map_module, '__getattr__', forbidden)
        self.assertIn('unavailable', self.capture())
        self.assertEqual(self.calls, [])
        delattr(self.map_module, '__getattr__')
        spec = ModuleSpec('PyMap', None)
        vars(spec)['_initializing'] = True
        self.map_module.__spec__ = spec
        self.output.clear()
        self.assertIn('unavailable', self.capture())
        self.assertEqual(self.calls, [])

    def test_missing_symbol_and_failed_constructor_are_classified(self) -> None:
        delattr(self.party_module, 'PyParty')
        self.assertIn('PARTY unavailable', self.capture())

        def broken() -> object:
            raise RuntimeError('secret@example.test Character Name 1987654321')

        setattr(self.party_module, 'PyParty', broken)
        self.output.clear()
        output = self.capture()
        self.assertIn('PARTY uncertain', output)
        self.assertNotIn('secret', output)
        self.assertNotIn('Character Name', output)

    def test_invalid_rosters_are_uncertain(self) -> None:
        variants: tuple[list[Any] | tuple[Any, ...], ...] = (
            [],
            [self.player_type(0, 0, 1)],
            [self.player_type(987654321, 0, 1)],
            [self.player_type(self.local_login, 0, 0)],
            [self.player_type(self.local_login, 0, 1), self.player_type(self.local_login, 0, 1)],
            [self.player_type(self.local_login, 0, 1)] * 65,
            (self.player_type(self.local_login, 0, 1),),
        )
        for index, rows in enumerate(variants):
            with self.subTest(case=index):
                self.party.players = rows
                if isinstance(rows, list) and 0 < len(rows) <= 64:
                    self.party.party_player_count = self.party.party_size = len(rows)
                self.output.clear()
                self.assertIn('PARTY uncertain', self.capture())
        self.party.players = [self.player_type(self.local_login, 0, 1)]
        self.party.party_player_count = self.party.party_size = 1
        self.party.is_party_leader = False
        self.output.clear()
        self.assertIn('PARTY uncertain', self.capture())

    def test_invalid_hero_owner_and_duplicate_agents_are_uncertain(self) -> None:
        self.party.heroes = [self.hero_type(10, 999, 1, 0, 0, 20)]
        self.party.party_hero_count, self.party.party_size = 1, 2
        self.assertIn('PARTY uncertain', self.capture())
        self.party.heroes = [self.hero_type(10, self.local_login, 1, 0, 0, 20)]
        self.party.henchmen = [self.henchman_type(agent_id=10)]
        self.party.party_henchman_count, self.party.party_size = 1, 3
        self.output.clear()
        self.assertIn('PARTY uncertain', self.capture())

    def test_readiness_and_non_outpost_gate_native_roster_copy(self) -> None:
        for loaded, kind in ((False, 0), (True, 1), (True, 2)):
            with self.subTest(loaded=loaded, kind=kind):
                self.map_values['get_is_map_loaded'] = loaded
                self.map_values['get_instance_type'] = kind
                self.output.clear()
                self.assertIn('PARTY not_sampled', self.capture())
                self.assertEqual(self.constructed, 0)
        self.map_values['get_instance_type'] = 0
        self.party.is_party_loaded = False
        self.output.clear()
        self.assertIn('PARTY unavailable', self.capture())
        self.assertEqual(self.constructed, 0)

    def test_invalid_map_values_are_not_printed(self) -> None:
        for key, value in (('get_region', -1), ('get_language', 7), ('get_district', 0), ('get_map_id', True)):
            with self.subTest(field=key), patch.dict(self.map_values, {key: value}):
                self.output.clear()
                self.assertIn('READINESS uncertain', self.capture())
                self.assertEqual(self.constructed, 0)

    def test_context_transition_invalidates_eligibility_classification(self) -> None:
        self.party.players.append(self.player_type(999, 0, 1))
        self.party.party_player_count = self.party.party_size = 2
        values = iter((10000, 100))
        setattr(self.map_module, 'get_instance_time', lambda: next(values))
        output = self.capture()
        self.assertIn('context_changed_during_capture', output)
        self.assertIn('SOLO unverified', output)
        self.assertNotIn('SOLO ineligible', output)

    def test_party_counts_changing_during_copy_are_uncertain(self) -> None:
        original = self.new_party

        def changing() -> object:
            result = original()
            self.party.party_player_count = 2
            return result

        setattr(self.party_module, 'PyParty', changing)
        self.assertIn('PARTY uncertain', self.capture())

    def test_privacy_bounds_and_read_only_value_snapshot(self) -> None:
        self.party.account_email = 'secret@example.test'
        self.party.character_name = 'Private Character'
        before = copy.deepcopy(vars(self.party))
        output = self.capture()
        for secret in ('secret@example.test', 'Private Character', str(self.local_login), str(self.party.party_id)):
            self.assertNotIn(secret, output)
        self.assertLessEqual(len(self.output), self.widget._MAX_LINES)
        self.assertTrue(
            all(len(line) <= self.widget._MAX_LINE_LENGTH + len(self.widget._PREFIX) + 1 for line in self.output)
        )
        for key in before:
            if key == 'players':
                self.assertEqual([bytes(row) for row in before[key]], [bytes(row) for row in self.party.players])
            else:
                self.assertEqual(before[key], vars(self.party)[key])

    def test_forbidden_native_pointer_paths_and_commands_are_never_touched(self) -> None:
        class Trap:
            def __getattr__(self, name: str) -> object:
                raise AssertionError('forbidden runtime access: ' + name)

        for name in (
            'InvitePlayer',
            'LeaveParty',
            'RespondToPartyRequest',
            'GetContext',
            'GetPartyContextPtr',
            'others',
        ):
            setattr(self.party, name, Trap())
        with patch.dict(sys.modules, {'Py4GWCoreLib': Trap(), 'PyCallback': Trap(), 'ctypes': Trap()}):
            self.assertIn('roster=consistent', self.capture())
        tree = ast.parse(WIDGET.read_text())
        runtime_imports = {name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names}
        self.assertEqual(runtime_imports, {'sys', 'PyImGui'})
        self.assertFalse(
            any(
                isinstance(node, ast.Attribute) and node.attr in ('contents', 'from_address', 'cast')
                for node in ast.walk(tree)
            )
        )

    def test_console_failure_stops_without_retry(self) -> None:
        attempts: list[str] = []

        def fail(_sender: str, line: str, _level: object) -> None:
            attempts.append(line)
            raise RuntimeError('private detail')

        setattr(self.system_module, 'Console', SimpleNamespace(Log=fail))
        self.widget._capture_snapshot()
        self.assertEqual(len(attempts), 1)
        self.widget.main()
        self.assertEqual(len(attempts), 1)
        self.assertNotIn('private detail', self.widget._status)

    def test_imgui_cleanup_and_no_saved_settings(self) -> None:
        flags_seen: list[int] = []

        def begin(_name: str, flags: int) -> bool:
            flags_seen.append(flags)
            return True

        def broken(_label: str) -> bool:
            raise RuntimeError('private UI error')

        setattr(self.imgui, 'begin', begin)
        setattr(self.imgui, 'button', broken)
        self.widget.main()
        self.assertEqual(flags_seen, [257])
        self.assertEqual(self.ended, 1)
        self.assertEqual(self.calls, [])

    def test_used_native_calls_exist_in_actual_tests_stubs(self) -> None:
        self.capture()
        expected = {
            'PyMap': set(self.map_values),
            'PyParty': {'get_' + name for name in self.widget._COUNT_FIELDS} | {'get_is_party_loaded', 'PyParty'},
            'PyPlayer': {'get_player_number'},
        }
        for module, names in expected.items():
            tree = ast.parse((TESTS / 'stubs' / (module + '.pyi')).read_text(encoding='utf-8-sig'))
            exported = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            self.assertLessEqual(names, exported, module)
        party_class = next(
            node
            for node in ast.parse((TESTS / 'stubs/PyParty.pyi').read_text()).body
            if isinstance(node, ast.ClassDef) and node.name == 'PyParty'
        )
        fields = {
            node.target.id
            for node in party_class.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }
        self.assertLessEqual(
            set(self.widget._COUNT_FIELDS)
            | {'players', 'heroes', 'henchmen', 'party_id', 'is_party_loaded', 'is_party_leader'},
            fields,
        )

    def test_existing_array_header_layout_is_not_runtime_pointer_proof(self) -> None:
        array_type = self.contract['GW_Array']
        self.assertEqual(ctypes.sizeof(ctypes.c_void_p), 4, 'Use the project Python 3.13 32-bit interpreter')
        self.assertEqual(ctypes.sizeof(array_type), 16)
        self.assertEqual(array_type.m_size.offset, 8)
        tree = ast.parse(CONTEXT.read_text())
        party_info = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'PartyInfoStruct'
        )
        fields = next(
            node.value
            for node in party_info.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == '_fields_' for target in node.targets)
        )
        assert isinstance(fields, ast.List)
        self.assertEqual(ast.unparse(fields.elts[4]), "('others_array', GW_Array)")
        # Structural compatibility never turns an unvisited live pointer into evidence.
        self.assertIn('PartyInfo.others_array pointer path NOT read', self.capture())


if __name__ == '__main__':
    unittest.main(verbosity=2)
