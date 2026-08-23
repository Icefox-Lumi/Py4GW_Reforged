from __future__ import annotations

import ast
import copy
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / 'Py4GWCoreLib' / 'modular' / 'hero_team_manager.py'
WIDGET_PATH = ROOT / 'Widgets' / 'Guild Wars' / 'Hero Team Manager.py'


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
            slot.template_id
            for team in config.teams
            for slot in team.slots
            if slot.template_id
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
