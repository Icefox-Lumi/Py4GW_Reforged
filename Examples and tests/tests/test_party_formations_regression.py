"""
Offline regression checks for Party Formations pure data logic.

This script intentionally avoids Guild Wars runtime state, PyImGui drawing,
injected clients, shared memory, and live party resolution. It exercises the
backend helpers in Py4GWCoreLib.HeroAI.party_formations that are safe to import offline.

Run:
    python "Examples and tests/tests/test_party_formations_regression.py"
"""

from __future__ import annotations

import ast
import copy
import json
import math
import sys
import traceback
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _find_repo_root(start_path: Path) -> Path:
    current = start_path.resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (candidate / 'Py4GWCoreLib' / 'HeroAI' / 'party_formations.py').is_file():
            return candidate

    raise RuntimeError(f'Could not locate the Py4GW repo root from {start_path}.')


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = _find_repo_root(SCRIPT_DIR)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Keep the offline regression suite on the current package path without
# importing Py4GWCoreLib's embedded-runtime facade.
if 'Py4GWCoreLib' not in sys.modules:
    offline_corelib_package = types.ModuleType('Py4GWCoreLib')
    setattr(offline_corelib_package, '__path__', [str(REPO_ROOT / 'Py4GWCoreLib')])
    setattr(offline_corelib_package, '__package__', 'Py4GWCoreLib')
    sys.modules['Py4GWCoreLib'] = offline_corelib_package

from Py4GWCoreLib.HeroAI import party_formations as pf  # noqa: E402


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _expect_close(actual: float, expected: float, message: str, tolerance: float = 1e-6) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f'{message}: expected {expected!r}, got {actual!r}.')


def _expect_offsets(actual: tuple[float, float], expected: tuple[float, float], message: str) -> None:
    _expect_close(actual[0], expected[0], f'{message} X')
    _expect_close(actual[1], expected[1], f'{message} Y')


def _shape_payload(**overrides) -> str:
    payload = {
        'type': pf.SHAPE_EXPORT_TYPE,
        'version': pf.SHAPE_EXPORT_VERSION,
        'name': 'Shape',
        'coordinate_space': pf.SHAPE_COORDINATE_SPACE,
        'spots': [{'label': 'Spot 1', 'offset_x': 1.0, 'offset_y': 2.0}],
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_rotation_round_trip() -> None:
    for offset_x, offset_y, angle in (
        (100.0, -50.0, 0.0),
        (10.0, 0.0, math.pi / 2.0),
        (-125.5, 450.25, -0.75),
        (0.0, 0.0, math.pi),
    ):
        rotated = pf.rotate_offset(offset_x, offset_y, angle)
        restored = pf.inverse_rotate_offset(rotated[0], rotated[1], angle)
        _expect_offsets(restored, (offset_x, offset_y), f'round trip {offset_x}, {offset_y}, {angle}')

    _expect_offsets(pf.rotate_offset(10.0, 0.0, math.pi / 2.0), (0.0, 10.0), '90 degree rotate')
    _expect_offsets(pf.inverse_rotate_offset(0.0, 10.0, math.pi / 2.0), (10.0, 0.0), '90 degree inverse')


def test_clear_assignment_preserves_geometry_and_spot_label() -> None:
    assignment = pf.FormationAssignment(
        kind=pf.ASSIGNMENT_ACCOUNT,
        offset_x=123.0,
        offset_y=-456.0,
        enabled=False,
        account_email='tester@example.com',
        account_name='Tester',
        character_name='Tester Character',
        account_party_position=3,
    )

    pf.clear_assignment_target(assignment, 'Backline')

    _expect(assignment.kind == pf.ASSIGNMENT_UNASSIGNED, 'clear should make assignment unassigned.')
    _expect(assignment.spot_label == 'Backline', 'clear should preserve fallback spot label.')
    _expect(assignment.offset_x == 123.0 and assignment.offset_y == -456.0, 'clear should preserve offsets.')
    _expect(assignment.enabled is False, 'clear should preserve enabled/off state.')
    _expect(not pf.assignment_has_target(assignment), 'cleared assignment should not have a target.')
    _expect(assignment.display_name() == 'Backline', 'unassigned display name should use spot label.')
    _expect(assignment.account_email == '', 'clear should remove account identity.')
    _expect(assignment.account_party_position == -1, 'clear should reset account party position.')


def test_shape_export_preserves_enabled_geometry_and_skips_invalid_spots() -> None:
    formation = pf.PartyFormation(
        name='Wedge',
        assignments=[
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_HERO,
                spot_label='Front',
                offset_x=100.5,
                offset_y=-25.25,
                hero_id=12,
                hero_name='Hero A',
            ),
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_UNASSIGNED,
                spot_label='Open',
                offset_x=0.0,
                offset_y=75.0,
            ),
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_ACCOUNT,
                enabled=False,
                spot_label='Disabled',
                offset_x=1.0,
                offset_y=2.0,
            ),
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_HERO,
                spot_label='Bool Offset',
                offset_x=True,
                offset_y=0.0,
            ),
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_HERO,
                spot_label='Huge Offset',
                offset_x=pf.MAX_SHAPE_OFFSET_ABS + 1.0,
                offset_y=0.0,
            ),
        ],
    )

    result = pf.export_formation_shape(formation)
    _expect(result.ok, 'shape export should succeed with valid enabled spots.')
    _expect(result.exported == 2, 'shape export should include two valid enabled spots.')
    _expect(result.skipped_disabled == 1, 'shape export should count disabled spots.')
    _expect(result.skipped_invalid == 2, 'shape export should count invalid offsets.')

    payload = json.loads(result.payload)
    _expect(payload['type'] == pf.SHAPE_EXPORT_TYPE, 'shape export type should be stable.')
    _expect(payload['version'] == pf.SHAPE_EXPORT_VERSION, 'shape export version should be stable.')
    _expect(payload['coordinate_space'] == pf.SHAPE_COORDINATE_SPACE, 'coordinate space should be stable.')
    _expect(payload['name'] == 'Wedge', 'shape export should preserve formation name.')
    _expect(
        payload['spots'][0] == {'label': 'Front', 'offset_x': 100.5, 'offset_y': -25.25},
        'first spot shape mismatch.',
    )
    _expect(
        payload['spots'][1] == {'label': 'Open', 'offset_x': 0.0, 'offset_y': 75.0},
        'unassigned spot shape mismatch.',
    )


def test_shape_export_respects_max_spot_limit() -> None:
    formation = pf.PartyFormation(
        name='Too Many',
        assignments=[
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_UNASSIGNED,
                spot_label=f'Spot {index + 1}',
                offset_x=float(index),
                offset_y=float(-index),
            )
            for index in range(pf.MAX_FORMATION_SPOTS + 2)
        ],
    )

    result = pf.export_formation_shape(formation)
    _expect(result.ok, 'shape export should succeed up to the max spot limit.')
    _expect(result.exported == pf.MAX_FORMATION_SPOTS, 'shape export should cap exported spots.')
    _expect(result.skipped_extra == 2, 'shape export should count extra spots over the limit.')


def test_shape_import_creates_unassigned_party_slot_formation() -> None:
    payload = _shape_payload(
        name='Wedge',
        spots=[
            {'label': 'Front', 'offset_x': 100.5, 'offset_y': -25.25},
            {'label': 'Open', 'offset_x': 0.0, 'offset_y': 75.0},
        ],
    )

    result = pf.import_formation_shape(payload, [pf.PartyFormation(name='Wedge')])
    _expect(result.ok and result.formation is not None, 'shape import should succeed.')
    if result.formation is None:
        raise AssertionError('shape import unexpectedly returned no formation.')
    formation = result.formation
    _expect(formation.name == 'Wedge (Imported 2)', 'shape import should make duplicate names unique.')
    _expect(formation.hotkey_key == pf.UNMAPPED_KEY_NAME, 'imported shape should not map a hotkey.')
    _expect(formation.hotkey_modifiers == pf.NO_MODIFIER_VALUE, 'imported shape should not map modifiers.')
    _expect(formation.target_mode == pf.TARGET_MODE_PARTY_SLOT, 'imported shape should use party-slot target mode.')
    _expect(len(formation.assignments) == 2, 'imported shape should create two assignments.')
    _expect(
        all(item.kind == pf.ASSIGNMENT_UNASSIGNED for item in formation.assignments),
        'imported spots should be unassigned.',
    )
    _expect(formation.assignments[0].spot_label == 'Front', 'first imported label mismatch.')
    _expect(formation.assignments[1].spot_label == 'Open', 'second imported label mismatch.')
    _expect(formation.assignments[0].offset_x == 100.5, 'first imported X mismatch.')
    _expect(formation.assignments[1].offset_y == 75.0, 'second imported Y mismatch.')


def test_shape_import_deduplicates_labels_and_defaults_blank_labels() -> None:
    payload = _shape_payload(
        name='Labels',
        spots=[
            {'label': 'Same', 'offset_x': 1.0, 'offset_y': 2.0},
            {'label': 'Same', 'offset_x': 3.0, 'offset_y': 4.0},
            {'label': '', 'offset_x': 5.0, 'offset_y': 6.0},
            {'offset_x': 7.0, 'offset_y': 8.0},
        ],
    )

    result = pf.import_formation_shape(payload, [])
    _expect(result.ok and result.formation is not None, 'duplicate-label shape import should succeed.')
    if result.formation is None:
        raise AssertionError('duplicate-label shape import unexpectedly returned no formation.')
    labels = [assignment.spot_label for assignment in result.formation.assignments]
    _expect(labels == ['Same', 'Same 2', 'Spot 3', 'Spot 4'], f'unexpected imported labels: {labels!r}.')
    _expect(bool(result.details), 'duplicate-label import should include a detail message.')


def test_shape_import_rejects_invalid_payloads() -> None:
    invalid_cases = [
        ('', 'empty clipboard'),
        ('not json', 'invalid JSON'),
        (json.dumps([]), 'non-object payload'),
        (_shape_payload(type='wrong'), 'unsupported type'),
        (_shape_payload(version=True), 'boolean version'),
        (_shape_payload(version=pf.SHAPE_EXPORT_VERSION + 1), 'unsupported version'),
        (_shape_payload(coordinate_space='screen'), 'unsupported coordinate_space'),
        (_shape_payload(spots=[]), 'empty spots'),
        (
            _shape_payload(
                spots=[
                    {'label': f'Spot {index + 1}', 'offset_x': float(index), 'offset_y': 0.0}
                    for index in range(pf.MAX_FORMATION_SPOTS + 1)
                ]
            ),
            'too many spots',
        ),
        (_shape_payload(spots=[{'label': 'Bad', 'offset_x': True, 'offset_y': 0.0}]), 'boolean offset'),
        (
            _shape_payload(
                spots=[
                    {
                        'label': 'Huge',
                        'offset_x': pf.MAX_SHAPE_OFFSET_ABS + 1.0,
                        'offset_y': 0.0,
                    }
                ]
            ),
            'offset over limit',
        ),
    ]

    for payload, name in invalid_cases:
        result = pf.import_formation_shape(payload, [])
        _expect(not result.ok and result.formation is None, f'{name} should fail shape import.')
        _expect(bool(result.message), f'{name} should provide a failure message.')


class _FakeJsonDocument:
    def __init__(self, root: dict[str, Any] | None = None, *, fail_on_set: bool = False) -> None:
        self.root: dict[str, Any] = copy.deepcopy(root) if root is not None else {}
        self.fail_on_set = fail_on_set
        self.set_calls = 0

    def get_json(self, path: str = '', default=None):
        if path:
            return copy.deepcopy(default)
        return copy.deepcopy(self.root if self.root else default)

    def set_json(self, path: str, value) -> None:
        self.set_calls += 1
        if self.fail_on_set:
            raise OSError('simulated JsonFactory write failure')
        if path:
            raise AssertionError(f'unexpected non-root path: {path}')
        self.root = copy.deepcopy(value)


def _with_fake_document(document: _FakeJsonDocument):
    original = pf._get_persistence_document
    pf._get_persistence_document = lambda document_override=None: (
        document if document_override is None else document_override
    )
    return original


def test_jsonfactory_persistence_and_legacy_normalization() -> None:
    document = _FakeJsonDocument()
    original = _with_fake_document(document)
    try:
        saved = pf.PartyFormation(
            name='Saved',
            formation_id='saved-id',
            target_mode=pf.TARGET_MODE_PARTY_SLOT,
            assignments=[
                pf.FormationAssignment(
                    kind=pf.ASSIGNMENT_UNASSIGNED,
                    spot_label='Open',
                    offset_x=10.0,
                    offset_y=20.0,
                )
            ],
        )
        result = pf.save_formations([saved])
        _expect(result.ok, 'first JsonFactory save should succeed.')
        _expect(document.root['schema'] == pf.PERSISTENCE_SCHEMA, 'target schema should be present.')
        _expect(document.root['version'] == pf.PERSISTENCE_VERSION, 'target persistence version should be stable.')
        _expect(document.root['formations'][0]['formation_id'] == 'saved-id', 'formation id should round trip.')
        _expect(document.root['geometry_presets']['presets'] == [], 'empty geometry presets should be retained.')

        loaded = pf.load_formations()
        _expect(len(loaded) == 1 and loaded[0].formation_id == 'saved-id', 'saved formation should load.')
        _expect(loaded[0].assignments[0].spot_label == 'Open', 'spot label should round trip.')

        document.root = {
            'formations': [
                {
                    'id': 'legacy-id',
                    'name': 'Legacy',
                    'assignments': [{'spot_label': 'Legacy Spot', 'offset_x': 7.5, 'offset_y': -2.5}],
                }
            ]
        }
        legacy = pf.load_formations()
        _expect(len(legacy) == 1 and legacy[0].formation_id == 'legacy-id', 'legacy id alias should load.')
        _expect(
            legacy[0].target_mode == pf.TARGET_MODE_IDENTITY,
            'missing legacy target mode should default to identity.',
        )
        _expect(legacy[0].assignments[0].kind == pf.ASSIGNMENT_HERO, 'missing assignment kind should default to hero.')
    finally:
        pf._get_persistence_document = original


def test_config_backups_create_prune_and_restore() -> None:
    document = _FakeJsonDocument()
    original = _with_fake_document(document)
    try:
        first = pf.PartyFormation(name='First', formation_id='first')
        second = pf.PartyFormation(name='Second', formation_id='second')
        first_result = pf.save_formations([first])
        _expect(first_result.ok and not pf.list_config_backups(), 'first save should not create a backup.')

        second_result = pf.save_formations([second])
        _expect(second_result.ok, 'second save should back up the first config.')
        backups = pf.list_config_backups()
        _expect(len(backups) == 1, 'second save should create exactly one backup.')
        _expect(
            document.root['backup_history'][0]['formations'][0]['formation_id'] == 'first',
            'backup should contain first.',
        )

        corrupt_root = {'formations': 'not-a-list'}
        document.root = corrupt_root
        before_calls = document.set_calls
        try:
            pf.save_formations([pf.PartyFormation(name='Third', formation_id='third')])
        except ValueError:
            pass
        else:
            raise AssertionError('malformed target data should refuse overwrite.')
        _expect(document.set_calls == before_calls, 'malformed target should not be written.')
        _expect(document.root == corrupt_root, 'malformed target should remain untouched.')

        document.root = {}
        for index in range(8):
            pf.save_formations([pf.PartyFormation(name=f'Version {index}', formation_id=f'version-{index}')])
        backups = pf.list_config_backups()
        _expect(len(backups) == pf.CONFIG_BACKUP_LIMIT, 'backup retention should keep five entries.')
        latest_id = document.root['backup_history'][0]['formations'][0]['formation_id']
        restore_result = pf.restore_latest_config_backup()
        _expect(restore_result.ok, 'restore latest backup should succeed.')
        restored = pf.load_formations()
        _expect(bool(restored) and restored[0].formation_id == latest_id, 'restore should replace current formations.')
        _expect(len(pf.list_config_backups()) == pf.CONFIG_BACKUP_LIMIT, 'restore should retain the limit.')
        _expect(bool(restore_result.preserved_current_path), 'restore should preserve current config metadata.')
    finally:
        pf._get_persistence_document = original


def test_config_load_warning_and_malformed_target_are_safe() -> None:
    document = _FakeJsonDocument({'formations': 'bad'})
    original = _with_fake_document(document)
    try:
        _expect(bool(pf.config_load_warning()), 'malformed target should produce a warning.')
        _expect(pf.load_formations() == [], 'malformed target should load as empty.')
    finally:
        pf._get_persistence_document = original


def test_config_load_normalizes_malformed_assignment_data() -> None:
    document = _FakeJsonDocument(
        {
            'formations': [
                {
                    'name': 'Mixed',
                    'assignments': [
                        {
                            'kind': ['bad'],
                            'offset_x': 'oops',
                            'offset_y': None,
                            'enabled': 'maybe',
                            'spot_label': ['bad'],
                            'label': {'bad': True},
                            'hero_id': 'bad',
                            'hero_name': ['bad'],
                            'hero_party_position': {},
                            'account_email': ['bad'],
                            'account_name': {'bad': True},
                            'character_name': ['bad'],
                            'account_party_position': None,
                        },
                        {
                            'kind': pf.ASSIGNMENT_UNASSIGNED,
                            'offset_x': 12.0,
                            'offset_y': -8.0,
                            'enabled': False,
                            'spot_label': 'Valid',
                        },
                    ],
                },
                {'name': 'Null Assignments', 'assignments': None},
                {'name': 'Object Assignments', 'assignments': {'not': 'a list'}},
            ]
        }
    )
    original = _with_fake_document(document)
    try:
        loaded = pf.load_formations()
        _expect(len(loaded) == 3, 'malformed assignment containers should not drop formations.')
        malformed = loaded[0].assignments[0]
        _expect(malformed.kind == pf.ASSIGNMENT_HERO, 'bad assignment kind should use the default.')
        _expect(malformed.offset_x == 0.0 and malformed.offset_y == 0.0, 'bad offsets should default to zero.')
        _expect(malformed.enabled is True, 'bad enabled value should use the default.')
        _expect(malformed.spot_label == '' and malformed.label == '', 'bad labels should default to blank.')
        _expect(malformed.hero_id == 0 and malformed.hero_party_position == 0, 'bad hero values should default.')
        _expect(
            malformed.account_email == '' and malformed.account_party_position == -1,
            'bad account values should default.',
        )
        _expect(
            loaded[1].assignments == [] and loaded[2].assignments == [],
            'bad assignment lists should become empty.',
        )
    finally:
        pf._get_persistence_document = original


def test_migration_import_is_idempotent_and_preserves_all_owned_data() -> None:
    document = _FakeJsonDocument()
    original = _with_fake_document(document)
    try:
        bundle = {
            'type': pf.MIGRATION_BUNDLE_TYPE,
            'version': pf.MIGRATION_BUNDLE_VERSION,
            'config': {
                'version': pf.CONFIG_VERSION,
                'formations': [
                    {
                        'formation_id': 'legacy-id',
                        'name': 'Legacy',
                        'target_mode': pf.TARGET_MODE_IDENTITY,
                        'hotkey_key': 'VK_SPACE',
                        'hotkey_modifiers': 2,
                        'assignments': [
                            {
                                'kind': pf.ASSIGNMENT_ACCOUNT,
                                'account_email': 'tester@example.com',
                                'character_name': 'Itati',
                                'account_party_position': 3,
                                'offset_x': -350.0,
                                'offset_y': 0.0,
                            }
                        ],
                    }
                ],
            },
            'geometry_presets': {
                'type': 'py4gw_party_formation_geometry_presets',
                'version': 1,
                'presets': [{'name': 'Spread', 'spots': [{'label': 'Front', 'offset_x': 1.0, 'offset_y': 2.0}]}],
            },
            'backups': [
                {
                    'name': 'party_formations.legacy.json',
                    'created_at': 123.0,
                    'config': {'version': pf.CONFIG_VERSION, 'formations': []},
                }
            ],
            'ui': {
                'tester@example.com': {
                    'consumed': False,
                    'windows': {'main': {'x': 10.0, 'y': 20.0, 'width': 420.0, 'height': 520.0, 'collapsed': False}},
                }
            },
        }

        imported = pf.migrate_legacy_bundle(bundle)
        _expect(imported.ok and imported.imported, 'valid migration should import.')
        _expect(document.set_calls == 1, 'migration should use one target root write.')
        _expect(document.root['formations'][0]['hotkey_key'] == 'VK_SPACE', 'hotkey should migrate.')
        _expect(document.root['formations'][0]['hotkey_modifiers'] == 2, 'hotkey modifiers should migrate.')
        migrated = pf.PartyFormation.from_dict(document.root['formations'][0])
        _expect(migrated.target_mode == pf.TARGET_MODE_IDENTITY, 'target mode should migrate.')
        _expect(len(migrated.assignments) == 1, 'assignments should migrate.')
        _expect(
            migrated.assignments[0].account_email == 'tester@example.com'
            and migrated.assignments[0].character_name == 'Itati'
            and migrated.assignments[0].account_party_position == 3,
            'account assignment identity should migrate.',
        )
        _expect(
            migrated.assignments[0].offset_x == -350.0 and migrated.assignments[0].offset_y == 0.0,
            'assignment geometry should migrate.',
        )
        _expect(document.root['geometry_presets']['presets'][0]['name'] == 'Spread', 'geometry should migrate.')
        _expect(document.root['backup_history'][0]['name'] == 'party_formations.legacy.json', 'backup should migrate.')
        ui_seed = pf.get_ui_migration_seed('tester@example.com')
        _expect(ui_seed is not None, 'UI seed should migrate.')
        if ui_seed is not None:
            _expect(ui_seed['windows']['main']['x'] == 10.0, 'UI seed should preserve the main window position.')

        calls_after_import = document.set_calls
        repeated = pf.migrate_legacy_bundle(bundle)
        _expect(repeated.ok and repeated.already_imported, 'repeated migration should be idempotent.')
        _expect(document.set_calls == calls_after_import, 'repeated migration should not write again.')
        _expect(pf.mark_ui_migration_seed_consumed('tester@example.com'), 'UI seed should be consumable.')
        _expect(not pf.get_ui_migration_seed('tester@example.com'), 'consumed UI seed should not be returned.')
    finally:
        pf._get_persistence_document = original


def test_hotkey_mapping_preserves_legacy_names_and_uses_current_imgui_codes() -> None:
    formation = pf.PartyFormation.from_dict(
        {
            'name': 'Migrated shortcut',
            'hotkey_key': 'VK_SPACE',
            'hotkey_modifiers': 2,
        }
    )
    _expect(formation.hotkey_key == 'VK_SPACE', 'legacy hotkey name should remain persisted unchanged.')
    _expect(formation.hotkey_modifiers == 2, 'legacy Ctrl modifier bit should remain persisted unchanged.')

    space = SimpleNamespace(value=0x20)
    junja = SimpleNamespace(value=0x17)
    letter_a = SimpleNamespace(value=0x41)
    _expect(
        pf.imgui_key_code_for_key(space) == 524,
        'legacy Space should map to the current ImGui Space key code.',
    )
    _expect(
        pf.imgui_key_code_for_key(junja) is None,
        'the old Win32 Junja value must never be used as a current ImGui key code.',
    )
    _expect(
        pf.imgui_key_code_for_key(letter_a) == 546,
        'letter hotkeys should map to the current ImGui named-key range.',
    )


def test_migration_rejects_malformed_or_existing_target_without_write() -> None:
    malformed = {
        'type': pf.MIGRATION_BUNDLE_TYPE,
        'version': pf.MIGRATION_BUNDLE_VERSION,
        'config': {'version': pf.CONFIG_VERSION, 'formations': 'bad'},
    }
    document = _FakeJsonDocument()
    original = _with_fake_document(document)
    try:
        rejected = pf.migrate_legacy_bundle(malformed)
        _expect(not rejected.ok, 'malformed migration should be rejected.')
        _expect(document.set_calls == 0, 'malformed migration should not write.')

        malformed_inputs = [
            {
                'backups': [{'name': 'missing-formations', 'config': {'version': pf.CONFIG_VERSION}}],
            },
            {
                'geometry_presets': None,
            },
            {
                'geometry_presets': {},
            },
            {
                'ui': {'tester@example.com': {'consumed': 'false', 'windows': {}}},
            },
            {
                'ui': {
                    'tester@example.com': {
                        'consumed': False,
                        'windows': {'main': {'width': 0.0}},
                    }
                },
            },
        ]
        for overrides in malformed_inputs:
            malformed_bundle = {
                'type': pf.MIGRATION_BUNDLE_TYPE,
                'version': pf.MIGRATION_BUNDLE_VERSION,
                'config': {'version': pf.CONFIG_VERSION, 'formations': []},
            }
            malformed_bundle.update(overrides)
            rejected = pf.migrate_legacy_bundle(malformed_bundle)
            _expect(not rejected.ok, 'incomplete or malformed migration data should be rejected.')
            _expect(document.set_calls == 0, 'malformed migration data should not write.')

        document.root = {'schema': 'some-other-feature'}
        before_schema = copy.deepcopy(document.root)
        rejected_schema = pf.migrate_legacy_bundle(
            {
                'type': pf.MIGRATION_BUNDLE_TYPE,
                'version': pf.MIGRATION_BUNDLE_VERSION,
                'config': {'version': pf.CONFIG_VERSION, 'formations': []},
            }
        )
        _expect(not rejected_schema.ok, 'migration should refuse an incompatible target schema.')
        _expect(document.set_calls == 0, 'incompatible target schema should not be written.')
        _expect(document.root == before_schema, 'incompatible target schema should remain unchanged.')

        document.root = {'unrelated_target_data': {'keep': True}}
        before_unknown = copy.deepcopy(document.root)
        rejected_unknown = pf.migrate_legacy_bundle(
            {
                'type': pf.MIGRATION_BUNDLE_TYPE,
                'version': pf.MIGRATION_BUNDLE_VERSION,
                'config': {'version': pf.CONFIG_VERSION, 'formations': []},
            }
        )
        _expect(not rejected_unknown.ok, 'migration should refuse unknown non-empty target data.')
        _expect(document.set_calls == 0, 'unknown target data should not be written.')
        _expect(document.root == before_unknown, 'unknown target data should remain unchanged.')

        document.root = {'formations': [{'formation_id': 'existing', 'name': 'Existing', 'assignments': []}]}
        before = copy.deepcopy(document.root)
        existing = pf.migrate_legacy_bundle(
            {
                'type': pf.MIGRATION_BUNDLE_TYPE,
                'version': pf.MIGRATION_BUNDLE_VERSION,
                'config': {'version': pf.CONFIG_VERSION, 'formations': []},
            }
        )
        _expect(not existing.ok, 'migration should refuse an existing target.')
        _expect(document.set_calls == 0, 'existing target should not be written.')
        _expect(document.root == before, 'existing target should remain unchanged.')

        document.root = {}
        failing = _FakeJsonDocument(fail_on_set=True)
        pf._get_persistence_document = lambda document_override=None: failing
        failed = pf.migrate_legacy_bundle(
            {
                'type': pf.MIGRATION_BUNDLE_TYPE,
                'version': pf.MIGRATION_BUNDLE_VERSION,
                'config': {'version': pf.CONFIG_VERSION, 'formations': []},
            }
        )
        _expect(not failed.ok, 'JsonFactory write failure should fail migration.')
        _expect(failing.root == {}, 'failed migration should not leave a partial fake payload.')
    finally:
        pf._get_persistence_document = original


def test_widget_static_reforged_entrypoints_and_persistence_contract() -> None:
    widget_path = REPO_ROOT / 'Widgets' / 'Automation' / 'Multiboxing' / 'PartyFormations.py'
    backend_path = REPO_ROOT / 'Py4GWCoreLib' / 'HeroAI' / 'party_formations.py'
    widget_text = widget_path.read_text(encoding='utf-8')
    backend_text = backend_path.read_text(encoding='utf-8')
    widget_tree = ast.parse(widget_text, filename=str(widget_path))
    entrypoints = {
        node.name
        for node in widget_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    _expect(
        {'main', 'configure', 'on_enable', 'on_disable'}.issubset(entrypoints),
        'widget should expose current WidgetManager entrypoints.',
    )
    _expect('JsonFactory' in backend_text, 'backend should use the current JsonFactory persistence facility.')
    _expect(
        'from Py4GWCoreLib.HeroAI.party_formations import' in widget_text,
        'widget should import its backend from the current HeroAI package.',
    )
    _expect(
        'from HeroAI.party_formations import' not in widget_text,
        'widget should not import the removed root-level HeroAI package.',
    )
    _expect(
        'from Py4GWCoreLib.HeroAI.utils import SameMapOrPartyAsAccount' in backend_text,
        'backend should import current HeroAI utilities.',
    )
    _expect(
        'from HeroAI.utils import SameMapOrPartyAsAccount' not in backend_text,
        'backend should not import the removed root-level HeroAI utilities.',
    )
    _expect(
        "MODULE_ICON = 'Assets\\\\Textures\\\\Module_Icons\\\\Party Formations.png'" in widget_text,
        'widget should use the current Assets texture root.',
    )
    _expect('migrate_legacy_bundle' in widget_text, 'widget should expose the explicit legacy importer.')
    _expect('FileDialog' in widget_text, 'legacy import should use the current in-overlay file dialog.')
    _expect('_party_keybinding' in widget_text, 'Party Formations should own current-API key capture.')
    _expect('ImGui.keybinding(' not in widget_text, 'Party Formations must not use stale VK-based key capture.')
    _expect(
        'key=cast(Any, _MappedHotkeyKey(key, imgui_code))' in widget_text,
        'runtime hotkeys should register a current ImGui-code adapter.',
    )
    _expect(
        'PyImGui.is_key_down(imgui_code)' in widget_text,
        'hotkey latches should release using current ImGui key codes.',
    )
    parser_start = widget_text.index('def _parse_legacy_window_ini')
    parser_end = widget_text.index('def _legacy_ui_seeds_from_selected_config', parser_start)
    _expect(
        'show_main_window' not in widget_text[parser_start:parser_end],
        'legacy UI parsing should not restore the stale show_main_window setting.',
    )
    editor_start = widget_text.index('def _draw_formation_editor')
    editor_end = widget_text.index('def on_enable', editor_start)
    _expect(
        '_draw_config_backups()' in widget_text[editor_start:editor_end],
        'empty-state UI should expose the explicit legacy importer.',
    )
    for forbidden in ('IniManager', 'write_json_file_atomic', 'CONFIG_BACKUP_DIR_SUFFIX', 'Py4GW.Console'):
        _expect(forbidden not in widget_text + backend_text, f'legacy persistence/API reference remains: {forbidden}.')
    _expect(
        'canvas_drag_active = drag_distance_squared >= CANVAS_DRAG_THRESHOLD * CANVAS_DRAG_THRESHOLD\n\n'
        '                if canvas_drag_active:' in widget_text,
        'canvas dragging should continue updating offsets after the drag threshold is crossed.',
    )
    _expect(
        (
            "if not _native_window_seed('main'):\n"
            '            PyImGui.set_next_window_collapsed(False, PyImGui.ImGuiCond.Always)'
        ) in widget_text,
        'legacy first-show expansion should not override a migrated main-window collapse seed.',
    )


@contextmanager
def _fake_party_runtime():
    module_names = (
        'Py4GWCoreLib.HeroAI.utils',
        'Py4GWCoreLib.Agent',
        'Py4GWCoreLib.GlobalCache',
        'Py4GWCoreLib.Map',
        'Py4GWCoreLib.Party',
        'Py4GWCoreLib.Player',
    )
    previous_modules = {name: sys.modules.get(name) for name in module_names}
    calls = {'hero_flags': [], 'hero_unflags': []}
    options = SimpleNamespace(
        Following=True,
        IsFlagged=False,
        FlagPosX=0.0,
        FlagPosY=0.0,
        FlagFacingAngle=0.0,
        FlagPos=SimpleNamespace(x=0.0, y=0.0),
    )
    account = SimpleNamespace(
        IsSlotActive=True,
        IsAccount=True,
        IsHero=False,
        IsPet=False,
        AccountEmail='remote@example.com',
        AccountName='Remote',
        AgentData=SimpleNamespace(
            AgentID=300,
            CharacterName='Remote Character',
            Health=SimpleNamespace(Current=1.0),
            Pos=SimpleNamespace(x=900.0, y=2000.0),
        ),
        AgentPartyData=SimpleNamespace(PartyID=77, PartyPosition=1),
    )
    positions = {
        100: (1000.0, 2000.0, 0.0),
        200: (1000.0, 2000.0, 0.0),
        300: (900.0, 2000.0, 0.0),
    }

    class _Agent:
        @staticmethod
        def GetXYZ(agent_id: int):
            return positions[int(agent_id)]

        @staticmethod
        def GetRotationAngle(agent_id: int) -> float:
            return math.pi / 2.0

        @staticmethod
        def IsValid(agent_id: int) -> bool:
            return int(agent_id) in positions

        @staticmethod
        def IsDead(agent_id: int) -> bool:
            return False

    class _Heroes:
        @staticmethod
        def GetHeroAgentIDByPartyPosition(position: int) -> int:
            return 200 if int(position) == 1 else 0

        @staticmethod
        def GetHeroNameById(hero_id: int) -> str:
            return f'Hero {int(hero_id)}'

        @staticmethod
        def FlagHero(agent_id: int, x: float, y: float) -> None:
            calls['hero_flags'].append((int(agent_id), float(x), float(y)))

        @staticmethod
        def UnflagHero(position: int) -> None:
            calls['hero_unflags'].append(int(position))

    class _Party:
        Heroes = _Heroes

        @staticmethod
        def IsPartyLoaded() -> bool:
            return True

        @staticmethod
        def GetPartyLeaderID() -> int:
            return 100

        @staticmethod
        def GetPartyID() -> int:
            return 77

        @staticmethod
        def GetHeroes():
            return [SimpleNamespace(agent_id=200, hero_id=28)]

    class _Map:
        @staticmethod
        def IsMapReady() -> bool:
            return True

        @staticmethod
        def IsMapLoading() -> bool:
            return False

        @staticmethod
        def IsInCinematic() -> bool:
            return False

        @staticmethod
        def IsExplorable() -> bool:
            return True

    class _Player:
        @staticmethod
        def GetAgentID() -> int:
            return 100

    class _SharedMemory:
        @staticmethod
        def GetAllActiveSlotsData():
            return [account]

        @staticmethod
        def GetHeroAIOptionsFromEmail(email: str):
            return options if email == account.AccountEmail else None

    fake_utils = types.ModuleType('Py4GWCoreLib.HeroAI.utils')
    setattr(fake_utils, 'SameMapOrPartyAsAccount', lambda candidate: candidate is account)
    fake_agent = types.ModuleType('Py4GWCoreLib.Agent')
    setattr(fake_agent, 'Agent', _Agent)
    fake_global_cache = types.ModuleType('Py4GWCoreLib.GlobalCache')
    setattr(fake_global_cache, 'GLOBAL_CACHE', SimpleNamespace(ShMem=_SharedMemory()))
    fake_map = types.ModuleType('Py4GWCoreLib.Map')
    setattr(fake_map, 'Map', _Map)
    fake_party = types.ModuleType('Py4GWCoreLib.Party')
    setattr(fake_party, 'Party', _Party)
    fake_player = types.ModuleType('Py4GWCoreLib.Player')
    setattr(fake_player, 'Player', _Player)
    fake_modules = {
        'Py4GWCoreLib.HeroAI.utils': fake_utils,
        'Py4GWCoreLib.Agent': fake_agent,
        'Py4GWCoreLib.GlobalCache': fake_global_cache,
        'Py4GWCoreLib.Map': fake_map,
        'Py4GWCoreLib.Party': fake_party,
        'Py4GWCoreLib.Player': fake_player,
    }
    sys.modules.update(fake_modules)
    try:
        yield calls, options
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def test_runtime_apply_and_clear_preserve_hero_and_account_flags() -> None:
    with _fake_party_runtime() as (calls, options):
        formation = pf.PartyFormation(
            name='Runtime Flags',
            target_mode=pf.TARGET_MODE_IDENTITY,
            assignments=[
                pf.FormationAssignment(
                    kind=pf.ASSIGNMENT_HERO,
                    hero_id=28,
                    hero_name='Hero 28',
                    hero_party_position=1,
                    offset_x=100.0,
                    offset_y=-50.0,
                ),
                pf.FormationAssignment(
                    kind=pf.ASSIGNMENT_ACCOUNT,
                    account_email='remote@example.com',
                    account_party_position=1,
                    offset_x=0.0,
                    offset_y=100.0,
                ),
            ],
        )

        applied = pf.apply_formation(formation)
        _expect(applied.applied == 2, 'runtime apply should flag both hero and account assignments.')
        _expect(applied.skipped == 0, 'runtime apply should not skip valid fake assignments.')
        _expect(calls['hero_flags'] == [(200, 1050.0, 2100.0)], 'hero geometry rotation or flag API mismatch.')
        _expect(options.IsFlagged is True, 'account apply should set the direct HeroAI flag.')
        _expect_close(options.FlagPos.x, 900.0, 'account flag X')
        _expect_close(options.FlagPos.y, 2000.0, 'account flag Y')
        _expect_close(options.FlagPosX, 900.0, 'account scalar flag X')
        _expect_close(options.FlagPosY, 2000.0, 'account scalar flag Y')
        _expect_close(options.FlagFacingAngle, math.pi / 2.0, 'account flag facing angle')

        cleared = pf.clear_formation(formation)
        _expect(cleared.applied == 2, 'runtime clear should clear both hero and account assignments.')
        _expect(calls['hero_unflags'] == [1], 'hero clear should use the hero party position.')
        _expect(options.IsFlagged is False, 'account clear should clear the direct HeroAI flag.')
        _expect_close(options.FlagPos.x, 0.0, 'cleared account flag X')
        _expect_close(options.FlagPos.y, 0.0, 'cleared account flag Y')
        _expect_close(options.FlagFacingAngle, 0.0, 'cleared account flag facing angle')

        formation.target_mode = pf.TARGET_MODE_PARTY_SLOT
        formation.assignments[0].hero_id = 999
        formation.assignments[0].hero_name = 'Changed Hero'
        formation.assignments[1].account_email = 'changed@example.com'
        slot_applied = pf.apply_formation(formation)
        _expect(slot_applied.applied == 2, 'party-slot apply should resolve current occupants.')
        _expect(
            calls['hero_flags'][-1] == (200, 1050.0, 2100.0),
            'party-slot hero assignment should use the current hero slot.',
        )
        _expect(options.IsFlagged is True, 'party-slot account assignment should set the direct flag.')

        slot_cleared = pf.clear_formation(formation)
        _expect(slot_cleared.applied == 2, 'party-slot clear should resolve current occupants.')
        _expect(calls['hero_unflags'] == [1, 1], 'party-slot hero clear should use the current hero position.')
        _expect(options.IsFlagged is False, 'party-slot account clear should clear the direct flag.')


def test_target_mode_and_default_names() -> None:
    _expect(
        pf.normalize_target_mode(pf.TARGET_MODE_PARTY_SLOT) == pf.TARGET_MODE_PARTY_SLOT,
        'party-slot mode should normalize.',
    )
    _expect(
        pf.normalize_target_mode(pf.TARGET_MODE_IDENTITY) == pf.TARGET_MODE_IDENTITY,
        'identity mode should normalize.',
    )
    _expect(
        pf.normalize_target_mode('invalid', default=pf.TARGET_MODE_IDENTITY) == pf.TARGET_MODE_IDENTITY,
        'invalid mode should use supplied default.',
    )

    existing = [pf.PartyFormation(name='Formation 1'), pf.PartyFormation(name='Formation 2')]
    created = pf.create_empty_formation(existing)
    _expect(created.name == 'Formation 3', 'default formation name should skip existing names.')
    _expect(created.assignments == [], 'empty formation should start without assignments.')


def test_preflight_static_counts_duplicates_and_offsets() -> None:
    formation = pf.PartyFormation(
        name='Preflight',
        target_mode=pf.TARGET_MODE_PARTY_SLOT,
        assignments=[
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_HERO,
                spot_label='Front',
                hero_party_position=1,
                offset_x=100.0,
                offset_y=0.0,
            ),
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_HERO,
                spot_label='Back',
                hero_party_position=1,
                offset_x=-100.0,
                offset_y=0.0,
            ),
            pf.FormationAssignment(kind=pf.ASSIGNMENT_UNASSIGNED, spot_label='Open'),
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_ACCOUNT,
                enabled=False,
                spot_label='Off',
                account_party_position=2,
            ),
            pf.FormationAssignment(
                kind=pf.ASSIGNMENT_HERO,
                spot_label='Bad Offset',
                hero_party_position=3,
                offset_x=True,
                offset_y=0.0,
            ),
        ],
    )

    counts = pf.formation_preflight_counts(formation)
    _expect(counts.enabled == 4, 'preflight counts should include four enabled spots.')
    _expect(counts.disabled == 1, 'preflight counts should include one disabled spot.')
    _expect(counts.assigned == 4, 'preflight counts should include assigned disabled targets.')
    _expect(counts.unassigned == 1, 'preflight counts should include unassigned spots.')
    _expect(counts.duplicate_targets == 1, 'preflight counts should detect duplicate target groups.')
    _expect(counts.offset_warnings == 1, 'preflight counts should detect offset warnings.')

    duplicates = pf.formation_duplicate_target_groups(formation)
    _expect(len(duplicates) == 1, 'duplicate target grouping should return one group.')
    _expect(duplicates[0].target_label == 'Hero Slot 1', 'duplicate target label mismatch.')
    _expect(duplicates[0].spot_labels == ['Front', 'Back'], 'duplicate spot labels mismatch.')

    account_key, account_label = pf.formation_assignment_target_key(formation, formation.assignments[3])
    _expect(account_key == ('account_slot', 2), 'party-slot account target key mismatch.')
    _expect(account_label == 'Player Slot 3', 'party-slot account target label mismatch.')

    huge = pf.FormationAssignment(offset_x=pf.MAX_SHAPE_OFFSET_ABS + 1.0, offset_y=0.0)
    _expect(
        pf.preflight_assignment_offset_warning(huge) == 'Offset is unusually large.',
        'huge offset should produce an unusual-offset warning.',
    )


def test_preflight_snapshot_summary_counts() -> None:
    snapshot = pf.FormationPreflightSnapshot()
    snapshot.add_warning_note('Duplicate Hero Slot 1: Front, Back')
    snapshot.add_item(0, 'Front', 'Hero Slot 1', pf.PREFLIGHT_STATUS_WOULD_TARGET, 'Hero would be flagged.')
    snapshot.add_item(1, 'Open', '', pf.PREFLIGHT_STATUS_SKIPPED, 'No target assigned.')
    snapshot.add_item(2, 'Bad', 'Hero Slot 2', pf.PREFLIGHT_STATUS_WARNING, 'Offset must be numeric.')

    _expect(snapshot.would_target == 1, 'snapshot should count would-target rows.')
    _expect(snapshot.skipped == 1, 'snapshot should count skipped rows.')
    _expect(snapshot.warnings == 2, 'snapshot should count warning notes and warning rows.')
    _expect(len(snapshot.items) == 3, 'snapshot should retain item rows.')
    _expect(snapshot.warning_notes == ['Duplicate Hero Slot 1: Front, Back'], 'snapshot warning notes mismatch.')


def main() -> int:
    tests = [
        test_rotation_round_trip,
        test_clear_assignment_preserves_geometry_and_spot_label,
        test_shape_export_preserves_enabled_geometry_and_skips_invalid_spots,
        test_shape_export_respects_max_spot_limit,
        test_shape_import_creates_unassigned_party_slot_formation,
        test_shape_import_deduplicates_labels_and_defaults_blank_labels,
        test_shape_import_rejects_invalid_payloads,
        test_jsonfactory_persistence_and_legacy_normalization,
        test_config_backups_create_prune_and_restore,
        test_config_load_warning_and_malformed_target_are_safe,
        test_config_load_normalizes_malformed_assignment_data,
        test_migration_import_is_idempotent_and_preserves_all_owned_data,
        test_hotkey_mapping_preserves_legacy_names_and_uses_current_imgui_codes,
        test_migration_rejects_malformed_or_existing_target_without_write,
        test_widget_static_reforged_entrypoints_and_persistence_contract,
        test_runtime_apply_and_clear_preserve_hero_and_account_flags,
        test_target_mode_and_default_names,
        test_preflight_static_counts_duplicates_and_offsets,
        test_preflight_snapshot_summary_counts,
    ]

    failures: list[str] = []
    for test in tests:
        try:
            test()
            print(f'PASS: {test.__name__}')
        except Exception:
            failures.append(test.__name__)
            print(f'FAIL: {test.__name__}')
            traceback.print_exc()

    if failures:
        print(f'{len(failures)} Party Formations regression check(s) failed: {", ".join(failures)}')
        return 1

    print(f'PASS: {len(tests)} Party Formations regression checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
