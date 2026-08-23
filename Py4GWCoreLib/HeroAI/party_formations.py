from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from dataclasses import field
from typing import Any

MODULE_NAME = 'Party Formations'
CONFIG_VERSION = 3
DEFAULT_COOLDOWN_SECONDS = 0.5
UNMAPPED_KEY_NAME = 'Unmapped'
NO_MODIFIER_VALUE = 0
CONFIG_BACKUP_LIMIT = 5
PERSISTENCE_DOCUMENT_NAME = 'Widgets/PartyFormations/PartyFormations.json'
PERSISTENCE_SCHEMA = 'py4gw_party_formations'
PERSISTENCE_VERSION = 1
MIGRATION_BUNDLE_TYPE = 'py4gw_party_formations_migration'
MIGRATION_BUNDLE_VERSION = 1
PERSISTENCE_ROOT_FIELDS = frozenset(
    {
        'schema',
        'version',
        'formations',
        'geometry_presets',
        'backup_history',
        'ui_seeds',
        'migration',
    }
)
SHAPE_EXPORT_TYPE = 'py4gw_party_formation_shape'
SHAPE_EXPORT_VERSION = 1
SHAPE_COORDINATE_SPACE = 'leader_relative_facing'
MAX_FORMATION_SPOTS = 11
MAX_SHAPE_OFFSET_ABS = 100000.0

ASSIGNMENT_UNASSIGNED = 'unassigned'
ASSIGNMENT_HERO = 'hero'
ASSIGNMENT_ACCOUNT = 'account'
TARGET_MODE_IDENTITY = 'identity'
TARGET_MODE_PARTY_SLOT = 'party_slot'
TARGET_MODES = {TARGET_MODE_IDENTITY, TARGET_MODE_PARTY_SLOT}
LEADER_PARTY_POSITION = 0
PREFLIGHT_STATUS_READY = 'Ready'
PREFLIGHT_STATUS_WARNING = 'Warning'
PREFLIGHT_STATUS_SKIPPED = 'Skipped'
PREFLIGHT_STATUS_WOULD_TARGET = 'Would target'


def normalize_target_mode(value: Any, default: str = TARGET_MODE_PARTY_SLOT) -> str:
    mode = str(value or default)
    if mode in TARGET_MODES:
        return mode
    return default


def _modifier_value_from_name(modifier_name: str) -> int:
    try:
        from Py4GWCoreLib.enums_src.IO_enums import ModifierKey

        return int(ModifierKey.__members__.get(modifier_name, ModifierKey.NoneKey))
    except Exception:
        return NO_MODIFIER_VALUE


def imgui_key_code_for_key(key: Any) -> int | None:
    """Translate a persisted Win32-style Key member to a current ImGui key code.

    Party Formations keeps the legacy ``Key`` member names in its JSON so existing
    formations remain portable.  Reforged's ``PyImGui`` keyboard functions use
    ImGui named-key codes instead of those Win32 virtual-key values, so runtime
    input handling must use this boundary conversion.
    """
    try:
        raw_value = int(key.value)
    except (AttributeError, TypeError, ValueError):
        return None

    # ImGuiKey_Tab is the first named key in the current Reforged ImGui API.
    named_key_begin = 512

    fixed_offsets = {
        0x01: 144,  # MouseLeft
        0x02: 145,  # MouseRight
        0x04: 146,  # MouseMiddle
        0x05: 147,  # MouseX1
        0x06: 148,  # MouseX2
        0x09: 0,  # Tab
        0x25: 1,  # Left
        0x27: 2,  # Right
        0x26: 3,  # Up
        0x28: 4,  # Down
        0x21: 5,  # PageUp
        0x22: 6,  # PageDown
        0x24: 7,  # Home
        0x23: 8,  # End
        0x2D: 9,  # Insert
        0x2E: 10,  # Delete
        0x08: 11,  # Backspace
        0x20: 12,  # Space
        0x0D: 13,  # Enter
        0x1B: 14,  # Escape
        0x11: 15,  # Control (generic)
        0x10: 16,  # Shift (generic)
        0x12: 17,  # Alt (generic)
        0xA2: 15,  # LeftCtrl
        0xA0: 16,  # LeftShift
        0xA4: 17,  # LeftAlt
        0x5B: 18,  # LeftSuper
        0xA3: 19,  # RightCtrl
        0xA1: 20,  # RightShift
        0xA5: 21,  # RightAlt
        0x5C: 22,  # RightSuper
        0x5D: 23,  # Menu
        0x13: 99,  # Pause
        0x14: 95,  # CapsLock
        0x91: 96,  # ScrollLock
        0x90: 97,  # NumLock
        0x2C: 98,  # PrintScreen
        0xBA: 89,  # Semicolon
        0xBF: 88,  # Slash
        0xC0: 94,  # GraveAccent
        0xDB: 91,  # LeftBracket
        0xDC: 92,  # Backslash
        0xDD: 93,  # RightBracket
        0xDE: 84,  # Apostrophe
        0xBB: 90,  # Equal
        0xBD: 86,  # Minus
        0xBE: 87,  # Period
        0xBC: 85,  # Comma
        0xA6: 117,  # AppBack
        0xA7: 118,  # AppForward
        0xC3: 125,  # GamepadFaceDown (A)
        0xC4: 123,  # GamepadFaceRight (B)
        0xC5: 122,  # GamepadFaceLeft (X)
        0xC6: 124,  # GamepadFaceUp (Y)
        0xC7: 131,  # GamepadR1 (right shoulder)
        0xC8: 130,  # GamepadL1 (left shoulder)
        0xC9: 132,  # GamepadL2 (left trigger)
        0xCA: 133,  # GamepadR2 (right trigger)
        0xCB: 128,  # GamepadDpadUp
        0xCC: 129,  # GamepadDpadDown
        0xCD: 126,  # GamepadDpadLeft
        0xCE: 127,  # GamepadDpadRight
        0xCF: 120,  # GamepadStart (menu)
        0xD0: 121,  # GamepadBack (view)
        0xD1: 134,  # GamepadL3
        0xD2: 135,  # GamepadR3
        0xD3: 138,  # GamepadLStickUp
        0xD4: 139,  # GamepadLStickDown
        0xD5: 137,  # GamepadLStickRight
        0xD6: 136,  # GamepadLStickLeft
        0xD7: 142,  # GamepadRStickUp
        0xD8: 143,  # GamepadRStickDown
        0xD9: 141,  # GamepadRStickRight
        0xDA: 140,  # GamepadRStickLeft
    }
    if raw_value in fixed_offsets:
        return named_key_begin + fixed_offsets[raw_value]

    if 0x30 <= raw_value <= 0x39:
        return named_key_begin + 24 + (raw_value - 0x30)
    if 0x41 <= raw_value <= 0x5A:
        return named_key_begin + 34 + (raw_value - 0x41)
    if 0x70 <= raw_value <= 0x87:
        return named_key_begin + 60 + (raw_value - 0x70)
    if 0x60 <= raw_value <= 0x69:
        return named_key_begin + 100 + (raw_value - 0x60)

    keypad_offsets = {
        0x6E: 110,  # KeypadDecimal
        0x6F: 111,  # KeypadDivide
        0x6A: 112,  # KeypadMultiply
        0x6D: 113,  # KeypadSubtract
        0x6B: 114,  # KeypadAdd
    }
    if raw_value in keypad_offsets:
        return named_key_begin + keypad_offsets[raw_value]

    # The remaining legacy entries (IME, media, and vendor-specific buttons)
    # have no matching current ImGui named key in this input surface.
    return None


def _safe_str(value: Any, default: str = '') -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return default
    return str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def _safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return default
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        return default
    return bool(value)


def _safe_assignment_kind(value: Any) -> str:
    kind = _safe_str(value, ASSIGNMENT_HERO)
    if kind in {ASSIGNMENT_UNASSIGNED, ASSIGNMENT_HERO, ASSIGNMENT_ACCOUNT}:
        return kind
    if isinstance(value, str):
        return kind
    return ASSIGNMENT_HERO


@dataclass
class FormationAssignment:
    kind: str = ASSIGNMENT_HERO
    offset_x: float = 0.0
    offset_y: float = 0.0
    enabled: bool = True
    spot_label: str = ''
    label: str = ''
    hero_id: int = 0
    hero_name: str = ''
    hero_party_position: int = 0
    account_email: str = ''
    account_name: str = ''
    character_name: str = ''
    account_party_position: int = -1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'FormationAssignment':
        return cls(
            kind=_safe_assignment_kind(data.get('kind')),
            offset_x=_safe_float(data.get('offset_x'), 0.0),
            offset_y=_safe_float(data.get('offset_y'), 0.0),
            enabled=_safe_bool(data.get('enabled', True), True),
            spot_label=_safe_str(data.get('spot_label'), ''),
            label=_safe_str(data.get('label'), ''),
            hero_id=_safe_int(data.get('hero_id'), 0),
            hero_name=_safe_str(data.get('hero_name'), ''),
            hero_party_position=_safe_int(data.get('hero_party_position'), 0),
            account_email=_safe_str(data.get('account_email'), ''),
            account_name=_safe_str(data.get('account_name'), ''),
            character_name=_safe_str(data.get('character_name'), ''),
            account_party_position=_safe_int(data.get('account_party_position'), -1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'kind': self.kind,
            'offset_x': float(self.offset_x),
            'offset_y': float(self.offset_y),
            'enabled': bool(self.enabled),
            'spot_label': self.spot_label,
            'label': self.label,
            'hero_id': int(self.hero_id),
            'hero_name': self.hero_name,
            'hero_party_position': int(self.hero_party_position),
            'account_email': self.account_email,
            'account_name': self.account_name,
            'character_name': self.character_name,
            'account_party_position': int(self.account_party_position),
        }

    def display_name(self) -> str:
        if self.kind == ASSIGNMENT_UNASSIGNED:
            return self.spot_label or 'Unassigned spot'
        if self.label:
            return self.label
        if self.kind == ASSIGNMENT_ACCOUNT:
            return (
                self.character_name
                or self.account_name
                or self.account_email
                or f'Account slot {self.account_party_position}'
            )
        return self.hero_name or f'Hero {self.hero_id or self.hero_party_position}'


@dataclass
class PartyFormation:
    name: str
    formation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    assignments: list[FormationAssignment] = field(default_factory=list)
    hotkey_key: str = UNMAPPED_KEY_NAME
    hotkey_modifiers: int = NO_MODIFIER_VALUE
    target_mode: str = TARGET_MODE_PARTY_SLOT

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'PartyFormation':
        key_name = _safe_str(data.get('hotkey_key'), UNMAPPED_KEY_NAME) or UNMAPPED_KEY_NAME

        raw_modifier = data.get('hotkey_modifiers', NO_MODIFIER_VALUE)
        try:
            if isinstance(raw_modifier, bool):
                raise ValueError
            modifier_value = int(raw_modifier)
        except (TypeError, ValueError, OverflowError):
            modifier_name = _safe_str(raw_modifier, 'NoneKey')
            modifier_value = _modifier_value_from_name(modifier_name)

        formation_id = _safe_str(data.get('formation_id') or data.get('id'), '') or uuid.uuid4().hex
        name = _safe_str(data.get('name'), 'Formation') or 'Formation'
        raw_assignments = data.get('assignments', [])
        if not isinstance(raw_assignments, list):
            raw_assignments = []
        assignments = [FormationAssignment.from_dict(item) for item in raw_assignments if isinstance(item, dict)]
        return cls(
            name=name,
            formation_id=formation_id,
            assignments=assignments,
            hotkey_key=key_name,
            hotkey_modifiers=modifier_value,
            target_mode=normalize_target_mode(data.get('target_mode'), default=TARGET_MODE_IDENTITY),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'formation_id': self.formation_id,
            'name': self.name,
            'target_mode': normalize_target_mode(self.target_mode),
            'hotkey_key': self.hotkey_key,
            'hotkey_modifiers': int(self.hotkey_modifiers),
            'assignments': [assignment.to_dict() for assignment in self.assignments],
        }

    def key(self) -> Any:
        from Py4GWCoreLib.enums_src.IO_enums import Key

        return Key.__members__.get(self.hotkey_key, Key.Unmapped)

    def modifiers(self) -> Any:
        from Py4GWCoreLib.enums_src.IO_enums import ModifierKey

        try:
            return ModifierKey(int(self.hotkey_modifiers))
        except ValueError:
            return ModifierKey.NoneKey

    def set_hotkey(self, key: Any, modifiers: Any) -> None:
        self.hotkey_key = key.name
        self.hotkey_modifiers = int(modifiers)


@dataclass
class FormationShapeExportResult:
    payload: str = ''
    exported: int = 0
    skipped_disabled: int = 0
    skipped_invalid: int = 0
    skipped_extra: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.payload) and self.exported > 0

    def status(self) -> str:
        if not self.ok:
            return 'Export failed: no enabled valid spots to export.'

        parts = [f'Exported {self.exported} spot{"s" if self.exported != 1 else ""}']
        if self.skipped_disabled:
            parts.append(f'skipped {self.skipped_disabled} disabled spot{"s" if self.skipped_disabled != 1 else ""}')
        if self.skipped_invalid:
            parts.append(f'skipped {self.skipped_invalid} invalid spot{"s" if self.skipped_invalid != 1 else ""}')
        if self.skipped_extra:
            parts.append(f'skipped {self.skipped_extra} spot{"s" if self.skipped_extra != 1 else ""} over the limit')
        return '; '.join(parts) + '.'


@dataclass
class FormationShapeImportResult:
    formation: PartyFormation | None = None
    message: str = ''
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.formation is not None


@dataclass
class FormationApplyResult:
    applied: int = 0
    skipped: int = 0
    messages: list[str] = field(default_factory=list)

    def add_applied(self, message: str) -> None:
        self.applied += 1
        self.messages.append(message)

    def add_skipped(self, message: str) -> None:
        self.skipped += 1
        self.messages.append(message)

    def summary(self) -> str:
        return f'Applied {self.applied}, skipped {self.skipped}'


@dataclass
class FormationConfigBackupInfo:
    path: str
    name: str
    created_at: float = 0.0
    size: int = 0


@dataclass
class FormationConfigBackupResult:
    ok: bool = False
    skipped: bool = False
    message: str = ''
    backup_path: str = ''
    restored_path: str = ''
    preserved_current_path: str = ''
    removed: int = 0
    details: list[str] = field(default_factory=list)


@dataclass
class PartyFormationMigrationResult:
    ok: bool = False
    imported: bool = False
    already_imported: bool = False
    message: str = ''
    details: list[str] = field(default_factory=list)
    source_fingerprint: str = ''
    ui_seeds: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class FormationTargetDuplicate:
    target_key: tuple[str, object]
    target_label: str
    spot_labels: list[str] = field(default_factory=list)


@dataclass
class FormationPreflightCounts:
    enabled: int = 0
    disabled: int = 0
    assigned: int = 0
    unassigned: int = 0
    duplicate_targets: int = 0
    offset_warnings: int = 0


@dataclass
class FormationPreflightItem:
    spot_index: int
    spot_label: str
    target_label: str
    status: str
    message: str
    target_x: float | None = None
    target_y: float | None = None


@dataclass
class FormationPreflightSnapshot:
    counts: FormationPreflightCounts = field(default_factory=FormationPreflightCounts)
    runtime_checked: bool = False
    runtime_ready: bool = False
    would_target: int = 0
    warnings: int = 0
    skipped: int = 0
    warning_notes: list[str] = field(default_factory=list)
    items: list[FormationPreflightItem] = field(default_factory=list)

    def add_warning_note(self, message: str) -> None:
        self.warnings += 1
        self.warning_notes.append(message)

    def add_item(
        self,
        spot_index: int,
        spot_label: str,
        target_label: str,
        status: str,
        message: str,
        target_x: float | None = None,
        target_y: float | None = None,
    ) -> None:
        if status == PREFLIGHT_STATUS_WOULD_TARGET:
            self.would_target += 1
        elif status == PREFLIGHT_STATUS_WARNING:
            self.warnings += 1
        elif status == PREFLIGHT_STATUS_SKIPPED:
            self.skipped += 1

        self.items.append(
            FormationPreflightItem(
                spot_index=spot_index,
                spot_label=spot_label,
                target_label=target_label,
                status=status,
                message=message,
                target_x=target_x,
                target_y=target_y,
            )
        )


class FormationCooldowns:
    def __init__(self, cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS):
        self.cooldown_seconds = cooldown_seconds
        self._last_applied: dict[str, float] = {}

    def ready(self, formation_id: str) -> bool:
        last_applied = self._last_applied.get(formation_id, 0.0)
        return time.monotonic() - last_applied >= self.cooldown_seconds

    def mark(self, formation_id: str) -> None:
        self._last_applied[formation_id] = time.monotonic()


def rotate_offset(offset_x: float, offset_y: float, facing_angle: float) -> tuple[float, float]:
    cos_a = math.cos(facing_angle)
    sin_a = math.sin(facing_angle)
    return (
        offset_x * cos_a - offset_y * sin_a,
        offset_x * sin_a + offset_y * cos_a,
    )


def inverse_rotate_offset(delta_x: float, delta_y: float, facing_angle: float) -> tuple[float, float]:
    cos_a = math.cos(facing_angle)
    sin_a = math.sin(facing_angle)
    return (
        delta_x * cos_a + delta_y * sin_a,
        -delta_x * sin_a + delta_y * cos_a,
    )


def _get_persistence_document(document: Any = None) -> Any:
    if document is not None:
        return document

    from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

    return JsonFactory(PERSISTENCE_DOCUMENT_NAME, 'global')


def _empty_geometry_library() -> dict[str, Any]:
    return {
        'type': 'py4gw_party_formation_geometry_presets',
        'version': 1,
        'presets': [],
    }


def _empty_persistence_document() -> dict[str, Any]:
    return {
        'schema': PERSISTENCE_SCHEMA,
        'version': PERSISTENCE_VERSION,
        'formations': [],
        'geometry_presets': _empty_geometry_library(),
        'backup_history': [],
        'ui_seeds': {},
        'migration': {},
    }


def _document_root(document: Any = None) -> tuple[dict[str, Any] | None, Any, str]:
    try:
        doc = _get_persistence_document(document)
        raw = doc.get_json('', None)
    except Exception as exc:
        return None, None, f'Could not read Party Formations persistence: {exc}'

    if raw is None:
        has_root = getattr(doc, 'has', None)
        is_object = getattr(doc, 'is_object', None)
        if callable(has_root) and callable(is_object):
            try:
                if bool(has_root('')) and not bool(is_object('')):
                    return None, doc, 'Party Formations persistence root must be a JSON object.'
            except Exception:
                pass
        return {}, doc, ''
    if raw == {}:
        return {}, doc, ''
    if not isinstance(raw, dict):
        return None, doc, 'Party Formations persistence must be a JSON object.'
    return raw, doc, ''


def _normalize_formations(
    raw_formations: Any,
    *,
    strict: bool,
    label: str = 'formations',
) -> tuple[list[dict[str, Any]], list[str]]:
    if raw_formations is None:
        if strict:
            return [], [f'{label} must be a list.']
        return [], []
    if not isinstance(raw_formations, list):
        return [], [f'{label} must be a list.']

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw_formations):
        item_label = f'{label} formation {index + 1}'
        if not isinstance(item, dict):
            errors.append(f'{item_label} must be an object.')
            continue
        raw_assignments = item.get('assignments', [])
        if strict and not isinstance(raw_assignments, list):
            errors.append(f'{item_label} assignments must be a list.')
            continue
        if strict and isinstance(raw_assignments, list) and len(raw_assignments) > MAX_FORMATION_SPOTS:
            errors.append(f'{item_label} exceeds the {MAX_FORMATION_SPOTS}-spot limit.')
            continue
        if strict and isinstance(raw_assignments, list):
            invalid_assignment = next(
                (
                    assignment_index
                    for assignment_index, assignment in enumerate(raw_assignments)
                    if not isinstance(assignment, dict)
                ),
                None,
            )
            if invalid_assignment is not None:
                errors.append(
                    f'{item_label} assignment {invalid_assignment + 1} must be an object.'
                )
                continue
        try:
            json.dumps(item, allow_nan=False)
            formation = PartyFormation.from_dict(item)
        except (TypeError, ValueError, OverflowError) as exc:
            errors.append(f'{item_label} is not loadable: {exc}')
            continue
        normalized.append(formation.to_dict())

    if strict and errors:
        return [], errors
    return normalized, errors


def _normalize_geometry_library(
    raw_library: Any,
    *,
    strict: bool,
) -> tuple[dict[str, Any], list[str]]:
    if raw_library is None:
        if strict:
            return _empty_geometry_library(), ['Geometry presets must be an object.']
        return _empty_geometry_library(), []
    if raw_library == {}:
        if strict:
            return _empty_geometry_library(), [
                'Geometry preset library must contain a type, version, and presets list.'
            ]
        return _empty_geometry_library(), []
    if not isinstance(raw_library, dict):
        return _empty_geometry_library(), ['Geometry presets must be an object.']
    if raw_library.get('type') != 'py4gw_party_formation_geometry_presets':
        return _empty_geometry_library(), ['Geometry preset library has an unsupported type.']
    version = raw_library.get('version')
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        return _empty_geometry_library(), ['Geometry preset library has an unsupported version.']

    raw_presets = raw_library.get('presets')
    if not isinstance(raw_presets, list):
        return _empty_geometry_library(), ['Geometry preset library must contain a presets list.']

    presets: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw_preset in enumerate(raw_presets):
        if not isinstance(raw_preset, dict):
            errors.append(f'Geometry preset {index + 1} must be an object.')
            continue
        name = str(raw_preset.get('name') or 'Formation Geometry').strip()[:80]
        raw_spots = raw_preset.get('spots')
        if not isinstance(raw_spots, list) or not raw_spots:
            errors.append(f'Geometry preset {index + 1} must contain at least one spot.')
            continue
        if len(raw_spots) > MAX_FORMATION_SPOTS:
            errors.append(
                f'Geometry preset {index + 1} exceeds the {MAX_FORMATION_SPOTS}-spot limit.'
            )
            continue

        spots: list[dict[str, Any]] = []
        preset_errors: list[str] = []
        for spot_index, raw_spot in enumerate(raw_spots):
            if not isinstance(raw_spot, dict):
                preset_errors.append(f'Geometry preset {index + 1} spot {spot_index + 1} must be an object.')
                continue
            offset_x = raw_spot.get('offset_x')
            offset_y = raw_spot.get('offset_y')
            if (
                isinstance(offset_x, bool)
                or isinstance(offset_y, bool)
                or not isinstance(offset_x, (int, float))
                or not isinstance(offset_y, (int, float))
                or not math.isfinite(float(offset_x))
                or not math.isfinite(float(offset_y))
                or abs(float(offset_x)) > MAX_SHAPE_OFFSET_ABS
                or abs(float(offset_y)) > MAX_SHAPE_OFFSET_ABS
            ):
                preset_errors.append(
                    f'Geometry preset {index + 1} spot {spot_index + 1} has an invalid offset.'
                )
                continue
            spots.append(
                {
                    'label': str(raw_spot.get('label') or f'Spot {spot_index + 1}')[:80],
                    'offset_x': float(offset_x),
                    'offset_y': float(offset_y),
                }
            )
        if preset_errors:
            errors.extend(preset_errors)
            continue
        presets.append({'name': name or 'Formation Geometry', 'spots': spots})

    if strict and errors:
        return _empty_geometry_library(), errors
    return {
        'type': 'py4gw_party_formation_geometry_presets',
        'version': 1,
        'presets': presets,
    }, errors


def _normalize_backup_history(
    raw_history: Any,
    *,
    strict: bool,
    limit: int = CONFIG_BACKUP_LIMIT,
) -> tuple[list[dict[str, Any]], list[str]]:
    if raw_history is None:
        if strict:
            return [], ['Party Formations backup history must be a list.']
        return [], []
    if not isinstance(raw_history, list):
        return [], ['Party Formations backup history must be a list.']

    history: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw_entry in enumerate(raw_history):
        if not isinstance(raw_entry, dict):
            errors.append(f'Backup {index + 1} must be an object.')
            continue
        config = raw_entry.get('config')
        if config is None:
            config = raw_entry
        if not isinstance(config, dict):
            errors.append(f'Backup {index + 1} config must be an object.')
            continue
        forms, form_errors = _normalize_formations(
            config.get('formations'),
            strict=True,
            label=f'backup {index + 1}',
        )
        if form_errors:
            errors.extend(form_errors)
            continue
        created_at = raw_entry.get('created_at', time.time())
        try:
            created_at = float(created_at)
            if not math.isfinite(created_at):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f'Backup {index + 1} has an invalid timestamp.')
            continue
        name = str(raw_entry.get('name') or f'party_formations.backup.{index + 1}.json')
        history.append(
            {
                'name': name,
                'created_at': created_at,
                'version': CONFIG_VERSION,
                'formations': forms,
            }
        )

    history.sort(key=lambda entry: (float(entry.get('created_at', 0.0)), str(entry.get('name', ''))), reverse=True)
    if strict and errors:
        return [], errors
    return history[: max(0, int(limit))], errors


def _normalize_ui_seeds(raw_seeds: Any, *, strict: bool) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if raw_seeds is None:
        if strict:
            return {}, ['Party Formations UI migration seeds must be an object.']
        return {}, []
    if not isinstance(raw_seeds, dict):
        return {}, ['Party Formations UI migration seeds must be an object.']

    normalized: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for account_email, raw_account in raw_seeds.items():
        if not isinstance(account_email, str) or not account_email.strip():
            errors.append('A UI migration seed has an invalid account key.')
            continue
        if not isinstance(raw_account, dict):
            errors.append(f'UI migration seed for {account_email} must be an object.')
            continue
        raw_consumed = raw_account.get('consumed', False)
        if not isinstance(raw_consumed, bool):
            errors.append(f'UI migration seed for {account_email} has an invalid consumed value.')
            continue
        account_seed: dict[str, Any] = {
            'consumed': raw_consumed,
            'windows': {},
        }
        raw_windows = raw_account.get('windows', {})
        if not isinstance(raw_windows, dict):
            errors.append(f'UI migration seed for {account_email} has invalid windows.')
            continue
        for window_name, raw_window in raw_windows.items():
            if window_name not in {'main', 'canvas', 'floating'}:
                continue
            if not isinstance(raw_window, dict):
                errors.append(f'UI migration seed {account_email}/{window_name} must be an object.')
                continue
            window: dict[str, Any] = {}
            for key in ('x', 'y', 'width', 'height'):
                if key not in raw_window:
                    continue
                value = raw_window[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    errors.append(f'UI migration seed {account_email}/{window_name}/{key} is invalid.')
                    continue
                if key in {'width', 'height'} and float(value) <= 0.0:
                    errors.append(f'UI migration seed {account_email}/{window_name}/{key} is invalid.')
                    continue
                window[key] = float(value)
            if 'collapsed' in raw_window:
                collapsed = raw_window['collapsed']
                if not isinstance(collapsed, bool):
                    errors.append(f'UI migration seed {account_email}/{window_name}/collapsed is invalid.')
                    continue
                window['collapsed'] = collapsed
            account_seed['windows'][window_name] = window
        normalized[account_email] = account_seed

    if strict and errors:
        return {}, errors
    return normalized, errors


def _normalize_document(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not raw:
        return _empty_persistence_document(), []

    errors: list[str] = []
    raw_schema = raw.get('schema')
    if raw_schema is not None and raw_schema != PERSISTENCE_SCHEMA:
        errors.append('Party Formations persistence has an unsupported schema.')
    if raw_schema == PERSISTENCE_SCHEMA:
        raw_version = raw.get('version', PERSISTENCE_VERSION)
        if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version > PERSISTENCE_VERSION:
            errors.append('Party Formations persistence has an unsupported future version.')

    formations, formation_errors = _normalize_formations(raw.get('formations', []), strict=True)
    errors.extend(formation_errors)
    geometry, geometry_errors = _normalize_geometry_library(
        raw.get('geometry_presets', _empty_geometry_library()),
        strict=True,
    )
    errors.extend(geometry_errors)
    history, history_errors = _normalize_backup_history(raw.get('backup_history', []), strict=True)
    errors.extend(history_errors)
    ui_seeds, ui_errors = _normalize_ui_seeds(raw.get('ui_seeds', {}), strict=True)
    errors.extend(ui_errors)
    migration = raw.get('migration', {})
    if not isinstance(migration, dict):
        errors.append('Party Formations migration metadata must be an object.')
        migration = {}

    normalized = dict(_empty_persistence_document())
    normalized.update(
        {
            'formations': formations,
            'geometry_presets': geometry,
            'backup_history': history,
            'ui_seeds': ui_seeds,
            'migration': dict(migration),
        }
    )
    return normalized, errors


def _read_normalized_document(document: Any = None) -> tuple[dict[str, Any] | None, Any, str]:
    raw, doc, error = _document_root(document)
    if error:
        return None, doc, error
    if raw is None:
        return None, doc, 'Party Formations persistence could not be read.'
    normalized, errors = _normalize_document(raw)
    if errors:
        return None, doc, '; '.join(errors)
    return normalized, doc, ''


def _backup_entry(formations: list[dict[str, Any]]) -> dict[str, Any]:
    timestamp = time.time()
    return {
        'name': f'party_formations.{time.strftime("%Y%m%d-%H%M%S")}.{time.time_ns()}.json',
        'created_at': timestamp,
        'version': CONFIG_VERSION,
        'formations': formations,
    }


def _backup_info(entry: dict[str, Any]) -> FormationConfigBackupInfo:
    name = str(entry.get('name') or 'Party Formations backup')
    try:
        created_at = float(entry.get('created_at', 0.0))
    except (TypeError, ValueError):
        created_at = 0.0
    try:
        size = len(json.dumps(entry, ensure_ascii=True, allow_nan=False))
    except (TypeError, ValueError):
        size = 0
    return FormationConfigBackupInfo(
        path=f'{PERSISTENCE_DOCUMENT_NAME}#backup/{name}',
        name=name,
        created_at=created_at,
        size=size,
    )


def list_config_backups() -> list[FormationConfigBackupInfo]:
    document, _doc, error = _read_normalized_document()
    if error or document is None:
        return []
    return [_backup_info(entry) for entry in document.get('backup_history', [])]


def config_load_warning() -> str:
    _document, _doc, error = _read_normalized_document()
    return error


def _write_normalized_document(document: dict[str, Any], doc: Any) -> None:
    doc.set_json('', document)


def _append_backup(
    document: dict[str, Any],
    formations: list[dict[str, Any]],
    *,
    limit: int = CONFIG_BACKUP_LIMIT,
) -> tuple[dict[str, Any] | None, int]:
    if not formations:
        return None, 0
    history = [_backup_entry(formations), *list(document.get('backup_history', []))]
    removed = max(0, len(history) - max(0, int(limit)))
    document['backup_history'] = history[: max(0, int(limit))]
    return history[0], removed


def create_config_backup(*, limit: int = CONFIG_BACKUP_LIMIT) -> FormationConfigBackupResult:
    document, doc, error = _read_normalized_document()
    if error or document is None or doc is None:
        return FormationConfigBackupResult(
            message=f'Config backup skipped: {error or "persistence is unavailable."}',
            details=[error] if error else [],
            skipped=True,
        )
    entry, removed = _append_backup(document, list(document.get('formations', [])), limit=limit)
    if entry is None:
        return FormationConfigBackupResult(
            skipped=True,
            message='Config backup skipped: no existing formations to back up.',
        )
    _write_normalized_document(document, doc)
    return FormationConfigBackupResult(
        ok=True,
        message=f'Config backup created: {entry["name"]}',
        backup_path=f'{PERSISTENCE_DOCUMENT_NAME}#backup/{entry["name"]}',
        removed=removed,
    )


def prune_config_backups(*, limit: int = CONFIG_BACKUP_LIMIT) -> int:
    document, doc, error = _read_normalized_document()
    if error or document is None or doc is None:
        return 0
    history = list(document.get('backup_history', []))
    keep = max(0, int(limit))
    removed = max(0, len(history) - keep)
    if removed:
        document['backup_history'] = history[:keep]
        _write_normalized_document(document, doc)
    return removed


def restore_latest_config_backup(*, limit: int = CONFIG_BACKUP_LIMIT) -> FormationConfigBackupResult:
    document, doc, error = _read_normalized_document()
    if error or document is None or doc is None:
        return FormationConfigBackupResult(
            message=f'Restore failed: {error or "persistence is unavailable."}',
            details=[error] if error else [],
        )
    history = list(document.get('backup_history', []))
    if not history:
        return FormationConfigBackupResult(message='No Party Formations config backups are available.')

    latest = history[0]
    preserved_current_path = ''
    current_entry, removed_before = _append_backup(
        document,
        list(document.get('formations', [])),
        limit=max(int(limit) + 1, CONFIG_BACKUP_LIMIT + 1),
    )
    if current_entry is not None:
        preserved_current_path = f'{PERSISTENCE_DOCUMENT_NAME}#backup/{current_entry["name"]}'
    document['formations'] = list(latest.get('formations', []))
    document['backup_history'] = list(document.get('backup_history', []))[: max(0, int(limit))]
    _write_normalized_document(document, doc)
    removed = removed_before + max(0, len(history) + (1 if current_entry else 0) - max(0, int(limit)))
    return FormationConfigBackupResult(
        ok=True,
        message=f'Restored Party Formations config from {latest["name"]}.',
        restored_path=f'{PERSISTENCE_DOCUMENT_NAME}#backup/{latest["name"]}',
        preserved_current_path=preserved_current_path,
        removed=removed,
        details=(
            [f'Current config preserved as {current_entry["name"]}.'] if current_entry is not None else []
        )
        + [f'Restored {latest["name"]}.'],
    )


def load_formations() -> list[PartyFormation]:
    raw, _doc, error = _document_root()
    if error or raw is None:
        return []
    raw_formations = raw.get('formations', [])
    normalized, _errors = _normalize_formations(raw_formations, strict=False)
    result: list[PartyFormation] = []
    for item in normalized:
        try:
            result.append(PartyFormation.from_dict(item))
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def save_formations(formations: list[PartyFormation]) -> FormationConfigBackupResult:
    document, doc, error = _read_normalized_document()
    if error or document is None or doc is None:
        raise ValueError(error or 'Party Formations persistence is unavailable.')

    formation_payload = [formation.to_dict() for formation in formations]
    entry, removed = _append_backup(document, list(document.get('formations', [])))
    document['formations'] = formation_payload
    _write_normalized_document(document, doc)
    if entry is None:
        return FormationConfigBackupResult(ok=True, message='Party Formations saved.')
    return FormationConfigBackupResult(
        ok=True,
        message=f'Party Formations saved; backup created: {entry["name"]}.',
        backup_path=f'{PERSISTENCE_DOCUMENT_NAME}#backup/{entry["name"]}',
        removed=removed,
    )


def load_geometry_preset_library() -> tuple[dict[str, Any] | None, str]:
    document, _doc, error = _read_normalized_document()
    if error or document is None:
        return None, error or 'Party Formations persistence is unavailable.'
    return dict(document.get('geometry_presets', _empty_geometry_library())), ''


def save_geometry_preset_library(payload: dict[str, Any]) -> tuple[bool, str]:
    document, doc, error = _read_normalized_document()
    if error or document is None or doc is None:
        return False, error or 'Party Formations persistence is unavailable.'
    normalized, errors = _normalize_geometry_library(payload, strict=True)
    if errors:
        return False, '; '.join(errors)
    document['geometry_presets'] = normalized
    _write_normalized_document(document, doc)
    return True, 'Geometry presets saved.'


def _migration_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _normalize_migration_bundle(bundle: Any) -> tuple[dict[str, Any] | None, str, list[str]]:
    if not isinstance(bundle, dict):
        return None, '', ['Migration input must be a JSON object.']
    if bundle.get('type') != MIGRATION_BUNDLE_TYPE:
        return None, '', [f'Unsupported migration bundle type: {bundle.get("type")!r}.']
    version = bundle.get('version')
    if isinstance(version, bool) or not isinstance(version, int) or version != MIGRATION_BUNDLE_VERSION:
        return None, '', ['Unsupported Party Formations migration bundle version.']

    config = bundle.get('config')
    if not isinstance(config, dict):
        return None, '', ['Migration bundle must contain a config object.']
    config_version = config.get('version')
    if isinstance(config_version, bool) or not isinstance(config_version, int) or config_version != CONFIG_VERSION:
        return None, '', [f'Unsupported legacy Party Formations config version: {config_version!r}.']
    if 'formations' not in config or not isinstance(config.get('formations'), list):
        return None, '', ['Migration config must contain a formations list.']

    formations, formation_errors = _normalize_formations(config.get('formations'), strict=True)
    geometry, geometry_errors = _normalize_geometry_library(bundle.get('geometry_presets'), strict=True)
    backups, backup_errors = _normalize_backup_history(bundle.get('backups', []), strict=True)
    ui_seeds, ui_errors = _normalize_ui_seeds(bundle.get('ui', {}), strict=True)
    errors = formation_errors + geometry_errors + backup_errors + ui_errors
    if errors:
        return None, '', errors

    normalized_payload = {
        'config': {
            'version': CONFIG_VERSION,
            'formations': formations,
        },
        'geometry_presets': geometry,
        'backups': backups,
        'ui': ui_seeds,
    }
    return normalized_payload, _migration_fingerprint(normalized_payload), []


def migrate_legacy_bundle(bundle: Any, *, document: Any = None) -> PartyFormationMigrationResult:
    payload, fingerprint, errors = _normalize_migration_bundle(bundle)
    if errors or payload is None:
        return PartyFormationMigrationResult(
            message='Party Formations migration rejected.',
            details=errors,
        )

    existing_raw, doc, read_error = _document_root(document)
    if read_error or doc is None:
        return PartyFormationMigrationResult(
            message='Party Formations migration could not read the target store.',
            details=[read_error or 'Target store is unavailable.'],
            source_fingerprint=fingerprint,
        )

    if existing_raw:
        existing, _existing_errors = _normalize_document(existing_raw)
        if _existing_errors:
            return PartyFormationMigrationResult(
                message='Party Formations migration refused to overwrite malformed target data.',
                details=_existing_errors,
                source_fingerprint=fingerprint,
            )
        unknown_fields = sorted(set(existing_raw) - PERSISTENCE_ROOT_FIELDS)
        if unknown_fields:
            return PartyFormationMigrationResult(
                message='Existing Party Formations target data was found; refusing to overwrite it.',
                details=[f'Unsupported target fields would be discarded: {", ".join(unknown_fields)}.'],
                source_fingerprint=fingerprint,
            )
        existing_fingerprint = str(existing.get('migration', {}).get('source_fingerprint', '') or '')
        if existing_fingerprint == fingerprint:
            return PartyFormationMigrationResult(
                ok=True,
                already_imported=True,
                message='This Party Formations migration was already imported.',
                source_fingerprint=fingerprint,
                ui_seeds=payload['ui'],
            )
        has_existing_data = bool(
            existing.get('formations')
            or existing.get('geometry_presets', {}).get('presets')
            or existing.get('backup_history')
            or existing.get('ui_seeds')
            or existing.get('migration')
        )
        if has_existing_data:
            return PartyFormationMigrationResult(
                message='Existing Party Formations data was found; refusing to overwrite it.',
                details=['Use an explicit future merge/replace action after backing up the target data.'],
                source_fingerprint=fingerprint,
            )

    new_document = _empty_persistence_document()
    new_document['formations'] = list(payload['config']['formations'])
    new_document['geometry_presets'] = dict(payload['geometry_presets'])
    new_document['backup_history'] = list(payload['backups'])[:CONFIG_BACKUP_LIMIT]
    new_document['ui_seeds'] = dict(payload['ui'])
    new_document['migration'] = {
        'source_fingerprint': fingerprint,
        'imported_at': time.time(),
        'source': str(bundle.get('source') or 'user-selected legacy Party Formations data'),
    }
    try:
        doc.set_json('', new_document)
    except Exception as exc:
        return PartyFormationMigrationResult(
            message='Party Formations migration failed without committing the target payload.',
            details=[str(exc)],
            source_fingerprint=fingerprint,
        )

    return PartyFormationMigrationResult(
        ok=True,
        imported=True,
        message='Legacy Party Formations data imported.',
        source_fingerprint=fingerprint,
        ui_seeds=payload['ui'],
    )


def _find_ui_migration_seed(
    document: dict[str, Any],
    account_email: str,
) -> tuple[str | None, dict[str, Any] | None]:
    seeds = document.get('ui_seeds', {})
    if not isinstance(seeds, dict):
        return None, None

    normalized_email = account_email.casefold()
    for key, raw_seed in seeds.items():
        if not isinstance(key, str) or key.casefold() != normalized_email:
            continue
        if isinstance(raw_seed, dict):
            return key, raw_seed
    return None, None


def get_ui_migration_seed(account_email: str) -> dict[str, Any]:
    if not account_email:
        return {}
    document, _doc, error = _read_normalized_document()
    if error or document is None:
        return {}
    _seed_key, seed = _find_ui_migration_seed(document, account_email)
    if not isinstance(seed, dict) or bool(seed.get('consumed', False)):
        return {}
    return dict(seed)


def mark_ui_migration_seed_consumed(account_email: str) -> bool:
    if not account_email:
        return False
    document, doc, error = _read_normalized_document()
    if error or document is None or doc is None:
        return False
    seed_key, seed = _find_ui_migration_seed(document, account_email)
    if not isinstance(seed, dict) or bool(seed.get('consumed', False)):
        return False
    if seed_key is None:
        return False
    seed['consumed'] = True
    document['ui_seeds'][seed_key] = seed
    _write_normalized_document(document, doc)
    return True


def make_default_formation_name(existing: list[PartyFormation]) -> str:
    used_names = {formation.name for formation in existing}
    index = len(existing) + 1
    while True:
        name = f'Formation {index}'
        if name not in used_names:
            return name
        index += 1


def create_empty_formation(existing: list[PartyFormation]) -> PartyFormation:
    return PartyFormation(name=make_default_formation_name(existing))


def default_spot_label(index: int) -> str:
    return f'Spot {index + 1}'


def assignment_spot_label(assignment: FormationAssignment, index: int) -> str:
    return str(assignment.spot_label or default_spot_label(index)).strip() or default_spot_label(index)


def assignment_has_target(assignment: FormationAssignment) -> bool:
    return assignment.kind != ASSIGNMENT_UNASSIGNED


def formation_has_assigned_targets(formation: PartyFormation) -> bool:
    return any(assignment_has_target(assignment) for assignment in formation.assignments)


def clear_assignment_target(assignment: FormationAssignment, fallback_spot_label: str = '') -> None:
    if not assignment.spot_label:
        assignment.spot_label = fallback_spot_label
    assignment.kind = ASSIGNMENT_UNASSIGNED
    assignment.label = ''
    assignment.hero_id = 0
    assignment.hero_name = ''
    assignment.hero_party_position = 0
    assignment.account_email = ''
    assignment.account_name = ''
    assignment.character_name = ''
    assignment.account_party_position = -1


def formation_assignment_target_key(
    formation: PartyFormation,
    assignment: FormationAssignment,
) -> tuple[tuple[str, object] | None, str]:
    if not assignment_has_target(assignment):
        return None, ''

    if normalize_target_mode(formation.target_mode, default=TARGET_MODE_IDENTITY) == TARGET_MODE_PARTY_SLOT:
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


def formation_duplicate_target_groups(formation: PartyFormation) -> list[FormationTargetDuplicate]:
    targets: dict[tuple[str, object], FormationTargetDuplicate] = {}
    for index, assignment in enumerate(formation.assignments):
        target_key, target_label = formation_assignment_target_key(formation, assignment)
        if target_key is None:
            continue
        duplicate = targets.setdefault(
            target_key,
            FormationTargetDuplicate(target_key=target_key, target_label=target_label, spot_labels=[]),
        )
        duplicate.spot_labels.append(assignment_spot_label(assignment, index))

    return [duplicate for duplicate in targets.values() if len(duplicate.spot_labels) > 1]


def preflight_assignment_offset_warning(assignment: FormationAssignment) -> str:
    if isinstance(assignment.offset_x, bool) or isinstance(assignment.offset_y, bool):
        return 'Offset must be numeric.'

    try:
        offset_x = float(assignment.offset_x)
        offset_y = float(assignment.offset_y)
    except (TypeError, ValueError):
        return 'Offset must be numeric.'

    if not math.isfinite(offset_x) or not math.isfinite(offset_y):
        return 'Offset must be finite.'
    if abs(offset_x) > MAX_SHAPE_OFFSET_ABS or abs(offset_y) > MAX_SHAPE_OFFSET_ABS:
        return 'Offset is unusually large.'
    return ''


def formation_preflight_counts(formation: PartyFormation) -> FormationPreflightCounts:
    counts = FormationPreflightCounts()
    for assignment in formation.assignments:
        if bool(getattr(assignment, 'enabled', True)):
            counts.enabled += 1
        else:
            counts.disabled += 1

        if assignment_has_target(assignment):
            counts.assigned += 1
        else:
            counts.unassigned += 1

        if preflight_assignment_offset_warning(assignment):
            counts.offset_warnings += 1

    counts.duplicate_targets = len(formation_duplicate_target_groups(formation))
    return counts


def _shape_label(value: Any, index: int) -> str:
    if value is None:
        return default_spot_label(index)
    label = str(value).strip()
    if not label:
        return default_spot_label(index)
    return label[:80]


def _dedupe_shape_label(label: str, used_labels: set[str]) -> str:
    if label not in used_labels:
        used_labels.add(label)
        return label

    suffix = 2
    while f'{label} {suffix}' in used_labels:
        suffix += 1
    deduped = f'{label} {suffix}'
    used_labels.add(deduped)
    return deduped


def _valid_shape_offset(value: float) -> bool:
    return math.isfinite(value) and abs(value) <= MAX_SHAPE_OFFSET_ABS


def _parse_shape_offset(value: Any, field_name: str, spot_index: int) -> tuple[float | None, str | None]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, f'Spot {spot_index + 1}: {field_name} must be a finite number.'

    offset = float(value)
    if not _valid_shape_offset(offset):
        return None, (
            f'Spot {spot_index + 1}: {field_name} must be finite and within ' f'+/-{MAX_SHAPE_OFFSET_ABS:.0f}.'
        )
    return offset, None


def _unique_imported_formation_name(name: str, existing: list[PartyFormation]) -> str:
    base = name.strip() or 'Imported Formation'
    existing_names = {formation.name for formation in existing}
    if base not in existing_names:
        return base

    suffix = 2
    while True:
        candidate = f'{base} (Imported {suffix})'
        if candidate not in existing_names:
            return candidate
        suffix += 1


def export_formation_shape(formation: PartyFormation) -> FormationShapeExportResult:
    result = FormationShapeExportResult()
    spots: list[dict[str, Any]] = []

    for index, assignment in enumerate(formation.assignments):
        if not assignment.enabled:
            result.skipped_disabled += 1
            continue

        if isinstance(assignment.offset_x, bool) or isinstance(assignment.offset_y, bool):
            result.skipped_invalid += 1
            result.details.append(f'{assignment_spot_label(assignment, index)}: invalid offset skipped.')
            continue

        try:
            offset_x = float(assignment.offset_x)
            offset_y = float(assignment.offset_y)
        except (TypeError, ValueError):
            result.skipped_invalid += 1
            result.details.append(f'{assignment_spot_label(assignment, index)}: invalid offset skipped.')
            continue

        if not _valid_shape_offset(offset_x) or not _valid_shape_offset(offset_y):
            result.skipped_invalid += 1
            result.details.append(f'{assignment_spot_label(assignment, index)}: invalid offset skipped.')
            continue

        if len(spots) >= MAX_FORMATION_SPOTS:
            result.skipped_extra += 1
            continue

        spots.append(
            {
                'label': assignment_spot_label(assignment, index),
                'offset_x': offset_x,
                'offset_y': offset_y,
            }
        )

    result.exported = len(spots)
    if not spots:
        return result

    payload = {
        'type': SHAPE_EXPORT_TYPE,
        'version': SHAPE_EXPORT_VERSION,
        'name': formation.name or 'Formation',
        'coordinate_space': SHAPE_COORDINATE_SPACE,
        'spots': spots,
    }
    result.payload = json.dumps(payload, indent=2, ensure_ascii=True)
    return result


def import_formation_shape(payload: str, existing: list[PartyFormation]) -> FormationShapeImportResult:
    raw_payload = str(payload or '').strip()
    if not raw_payload:
        return FormationShapeImportResult(message='Import failed: clipboard is empty.')

    try:
        raw = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        return FormationShapeImportResult(message=f'Import failed: invalid JSON ({exc.msg}).')

    if not isinstance(raw, dict):
        return FormationShapeImportResult(message='Import failed: shape payload must be a JSON object.')
    if raw.get('type') != SHAPE_EXPORT_TYPE:
        return FormationShapeImportResult(message='Import failed: unsupported shape type.')
    version = raw.get('version')
    if isinstance(version, bool) or not isinstance(version, int) or version != SHAPE_EXPORT_VERSION:
        return FormationShapeImportResult(message='Import failed: unsupported shape version.')
    if raw.get('coordinate_space') != SHAPE_COORDINATE_SPACE:
        return FormationShapeImportResult(message='Import failed: unsupported coordinate_space.')

    spots_raw = raw.get('spots')
    if not isinstance(spots_raw, list) or not spots_raw:
        return FormationShapeImportResult(message='Import failed: shape must contain at least one spot.')
    if len(spots_raw) > MAX_FORMATION_SPOTS:
        return FormationShapeImportResult(
            message=f'Import failed: shape has {len(spots_raw)} spots; maximum is {MAX_FORMATION_SPOTS}.'
        )

    assignments: list[FormationAssignment] = []
    used_labels: set[str] = set()
    details: list[str] = []
    for index, item in enumerate(spots_raw):
        if not isinstance(item, dict):
            return FormationShapeImportResult(message=f'Import failed: spot {index + 1} must be an object.')

        offset_x, error = _parse_shape_offset(item.get('offset_x'), 'offset_x', index)
        if error:
            return FormationShapeImportResult(message=f'Import failed: {error}')
        assert offset_x is not None
        offset_y, error = _parse_shape_offset(item.get('offset_y'), 'offset_y', index)
        if error:
            return FormationShapeImportResult(message=f'Import failed: {error}')
        assert offset_y is not None

        label = _shape_label(item.get('label'), index)
        unique_label = _dedupe_shape_label(label, used_labels)
        if unique_label != label:
            details.append(f'Disambiguated duplicate spot label {label!r} to {unique_label!r}.')

        assignments.append(
            FormationAssignment(
                kind=ASSIGNMENT_UNASSIGNED,
                offset_x=float(offset_x),
                offset_y=float(offset_y),
                spot_label=unique_label,
            )
        )

    name = _unique_imported_formation_name(str(raw.get('name') or 'Imported Formation'), existing)
    formation = PartyFormation(
        name=name,
        assignments=assignments,
        hotkey_key=UNMAPPED_KEY_NAME,
        hotkey_modifiers=NO_MODIFIER_VALUE,
        target_mode=TARGET_MODE_PARTY_SLOT,
    )
    return FormationShapeImportResult(
        formation=formation,
        message=f'Imported shape {formation.name} with {len(assignments)} unassigned spots.',
        details=details,
    )


def get_available_members() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from Py4GWCoreLib.HeroAI.utils import SameMapOrPartyAsAccount
    from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
    from Py4GWCoreLib.Party import Party

    heroes: list[dict[str, Any]] = []
    for index, hero in enumerate(Party.GetHeroes(), start=1):
        agent_id = int(getattr(hero, 'agent_id', 0) or 0)
        hero_id = int(getattr(hero, 'hero_id', 0) or 0)
        try:
            hero_name = str(Party.Heroes.GetHeroNameById(hero_id) or '')
        except Exception:
            hero_name = ''
        heroes.append(
            {
                'kind': ASSIGNMENT_HERO,
                'agent_id': agent_id,
                'hero_id': hero_id,
                'hero_name': hero_name,
                'hero_party_position': index,
                'label': hero_name or f'Hero {index}',
                'slot_label': f'Hero Slot {index}',
            }
        )

    accounts: list[dict[str, Any]] = []
    local_email = ''
    try:
        from Py4GWCoreLib.Player import Player

        local_email = str(Player.GetAccountEmail() or '')
    except Exception:
        local_email = ''

    for account in GLOBAL_CACHE.ShMem.GetAllActiveSlotsData():
        if not account or not bool(getattr(account, 'IsSlotActive', False)):
            continue
        if not bool(getattr(account, 'IsAccount', False)):
            continue
        if bool(getattr(account, 'IsHero', False)) or bool(getattr(account, 'IsPet', False)):
            continue
        account_email = str(getattr(account, 'AccountEmail', '') or '')
        if account_email and account_email == local_email:
            continue
        if not SameMapOrPartyAsAccount(account):
            continue

        agent_data = getattr(account, 'AgentData', None)
        party_data = getattr(account, 'AgentPartyData', None)
        if int(getattr(party_data, 'PartyID', 0) or 0) != int(GLOBAL_CACHE.Party.GetPartyID() or 0):
            continue
        character_name = str(getattr(agent_data, 'CharacterName', '') or '')
        account_name = str(getattr(account, 'AccountName', '') or '')
        party_position = int(getattr(party_data, 'PartyPosition', -1) or -1)
        if party_position <= LEADER_PARTY_POSITION:
            continue
        accounts.append(
            {
                'kind': ASSIGNMENT_ACCOUNT,
                'agent_id': int(getattr(agent_data, 'AgentID', 0) or 0),
                'account_email': account_email,
                'account_name': account_name,
                'character_name': character_name,
                'account_party_position': party_position,
                'label': character_name or account_name or account_email or f'Account slot {party_position}',
                'slot_label': f'Player Slot {party_position + 1}',
            }
        )

    accounts.sort(key=lambda item: (int(item.get('account_party_position', 9999)), str(item.get('label', ''))))
    return heroes, accounts


def assignment_from_member(member: dict[str, Any], offset_x: float = 0.0, offset_y: float = 0.0) -> FormationAssignment:
    if member.get('kind') == ASSIGNMENT_ACCOUNT:
        return FormationAssignment(
            kind=ASSIGNMENT_ACCOUNT,
            offset_x=offset_x,
            offset_y=offset_y,
            label=str(member.get('label') or ''),
            account_email=str(member.get('account_email') or ''),
            account_name=str(member.get('account_name') or ''),
            character_name=str(member.get('character_name') or ''),
            account_party_position=int(member.get('account_party_position', -1) or -1),
        )

    return FormationAssignment(
        kind=ASSIGNMENT_HERO,
        offset_x=offset_x,
        offset_y=offset_y,
        label=str(member.get('label') or ''),
        hero_id=int(member.get('hero_id') or 0),
        hero_name=str(member.get('hero_name') or ''),
        hero_party_position=int(member.get('hero_party_position') or 0),
    )


def _hero_slot_label(hero_position: int, occupant_label: str = '') -> str:
    if hero_position <= 0:
        return 'Hero Slot ?'
    if occupant_label:
        return f'Hero Slot {hero_position}: {occupant_label}'
    return f'Hero Slot {hero_position}'


def _player_slot_label(account_party_position: int, occupant_label: str = '') -> str:
    if account_party_position <= LEADER_PARTY_POSITION:
        return 'Leader / Anchor'
    public_slot = account_party_position + 1
    if occupant_label:
        return f'Player Slot {public_slot}: {occupant_label}'
    return f'Player Slot {public_slot}'


def _resolve_hero_assignment_with_position(assignment: FormationAssignment) -> tuple[int, int, str]:
    from Py4GWCoreLib.Party import Party

    fallback: tuple[int, int, str] = (0, 0, assignment.display_name())
    for index, hero in enumerate(Party.GetHeroes(), start=1):
        hero_id = int(getattr(hero, 'hero_id', 0) or 0)
        try:
            hero_name = str(Party.Heroes.GetHeroNameById(hero_id) or '')
        except Exception:
            hero_name = ''
        agent_id = int(getattr(hero, 'agent_id', 0) or 0)
        label = hero_name or assignment.display_name()
        if assignment.hero_id and hero_id == assignment.hero_id:
            return agent_id, index, label
        if assignment.hero_name and hero_name and hero_name == assignment.hero_name:
            fallback = (agent_id, index, label)

    if fallback[0] > 0:
        return fallback

    if assignment.hero_party_position > 0:
        return (
            int(Party.Heroes.GetHeroAgentIDByPartyPosition(assignment.hero_party_position) or 0),
            int(assignment.hero_party_position),
            assignment.display_name(),
        )

    return 0, 0, assignment.display_name()


def _resolve_hero_slot_assignment_with_position(assignment: FormationAssignment) -> tuple[int, int, str]:
    from Py4GWCoreLib.Party import Party

    hero_position = int(assignment.hero_party_position or 0)
    label = _hero_slot_label(hero_position)
    if hero_position <= 0:
        return 0, 0, label

    for index, hero in enumerate(Party.GetHeroes(), start=1):
        if index != hero_position:
            continue
        hero_id = int(getattr(hero, 'hero_id', 0) or 0)
        try:
            hero_name = str(Party.Heroes.GetHeroNameById(hero_id) or '')
        except Exception:
            hero_name = ''
        agent_id = int(getattr(hero, 'agent_id', 0) or 0)
        return agent_id, index, _hero_slot_label(hero_position, hero_name or assignment.display_name())

    return int(Party.Heroes.GetHeroAgentIDByPartyPosition(hero_position) or 0), hero_position, label


def _resolve_hero_assignment_with_position_for_mode(
    assignment: FormationAssignment,
    target_mode: str,
) -> tuple[int, int, str]:
    if normalize_target_mode(target_mode, default=TARGET_MODE_IDENTITY) == TARGET_MODE_PARTY_SLOT:
        return _resolve_hero_slot_assignment_with_position(assignment)
    return _resolve_hero_assignment_with_position(assignment)


def _resolve_hero_assignment(assignment: FormationAssignment) -> tuple[int, str]:
    agent_id, _hero_position, label = _resolve_hero_assignment_with_position(assignment)
    return agent_id, label


def _resolve_hero_assignment_for_mode(assignment: FormationAssignment, target_mode: str) -> tuple[int, str]:
    agent_id, _hero_position, label = _resolve_hero_assignment_with_position_for_mode(assignment, target_mode)
    return agent_id, label


def _resolve_account_assignment(assignment: FormationAssignment):
    from Py4GWCoreLib.HeroAI.utils import SameMapOrPartyAsAccount
    from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

    fallback = None
    for account in GLOBAL_CACHE.ShMem.GetAllActiveSlotsData():
        if not account or not bool(getattr(account, 'IsSlotActive', False)):
            continue
        if not bool(getattr(account, 'IsAccount', False)):
            continue
        if bool(getattr(account, 'IsHero', False)) or bool(getattr(account, 'IsPet', False)):
            continue

        agent_data = getattr(account, 'AgentData', None)
        party_data = getattr(account, 'AgentPartyData', None)
        account_email = str(getattr(account, 'AccountEmail', '') or '')
        character_name = str(getattr(agent_data, 'CharacterName', '') or '')
        account_name = str(getattr(account, 'AccountName', '') or '')
        party_position = int(getattr(party_data, 'PartyPosition', -1) or -1)

        if assignment.account_email and account_email == assignment.account_email:
            return account
        if assignment.character_name and character_name and character_name == assignment.character_name:
            fallback = account
        elif assignment.account_name and account_name and account_name == assignment.account_name:
            fallback = account
        elif assignment.account_party_position >= 0 and party_position == assignment.account_party_position:
            fallback = account

    if fallback is not None and SameMapOrPartyAsAccount(fallback):
        return fallback
    return fallback


def _resolve_account_slot_assignment(assignment: FormationAssignment):
    from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

    party_position = int(assignment.account_party_position)
    if party_position <= LEADER_PARTY_POSITION:
        return None

    for account in GLOBAL_CACHE.ShMem.GetAllActiveSlotsData():
        if not account or not bool(getattr(account, 'IsSlotActive', False)):
            continue
        if not bool(getattr(account, 'IsAccount', False)):
            continue
        if bool(getattr(account, 'IsHero', False)) or bool(getattr(account, 'IsPet', False)):
            continue

        party_data = getattr(account, 'AgentPartyData', None)
        account_party_position = int(getattr(party_data, 'PartyPosition', -1) or -1)
        if account_party_position == party_position:
            return account

    return None


def _resolve_account_assignment_for_mode(assignment: FormationAssignment, target_mode: str):
    if normalize_target_mode(target_mode, default=TARGET_MODE_IDENTITY) == TARGET_MODE_PARTY_SLOT:
        return _resolve_account_slot_assignment(assignment)
    return _resolve_account_assignment(assignment)


def _account_label(account) -> str:
    agent_data = getattr(account, 'AgentData', None)
    return (
        str(getattr(agent_data, 'CharacterName', '') or '')
        or str(getattr(account, 'AccountName', '') or '')
        or str(getattr(account, 'AccountEmail', '') or '')
        or 'Account'
    )


def capture_assignment_offset(
    assignment: FormationAssignment,
    target_mode: str = TARGET_MODE_IDENTITY,
) -> tuple[bool, str]:
    if assignment.kind == ASSIGNMENT_UNASSIGNED:
        return False, f'{assignment.spot_label or "Unassigned spot"}: assign a target before capture.'

    from Py4GWCoreLib.Agent import Agent
    from Py4GWCoreLib.Map import Map
    from Py4GWCoreLib.Party import Party
    from Py4GWCoreLib.Player import Player

    if not Map.IsMapReady() or Map.IsMapLoading() or not Map.IsExplorable():
        return False, 'Map is not ready for capture.'
    if not Party.IsPartyLoaded():
        return False, 'Party is not loaded.'

    leader_id = int(Party.GetPartyLeaderID() or 0)
    if leader_id <= 0 or int(Player.GetAgentID() or 0) != leader_id:
        return False, 'Only the party leader can capture formation offsets.'
    if not Agent.IsValid(leader_id):
        return False, 'Party leader agent is not valid.'

    leader_x, leader_y, _leader_z = Agent.GetXYZ(leader_id)
    facing_angle = float(Agent.GetRotationAngle(leader_id) or 0.0)

    if assignment.kind == ASSIGNMENT_HERO:
        agent_id, label = _resolve_hero_assignment_for_mode(assignment, target_mode)
        if agent_id <= 0 or not Agent.IsValid(agent_id):
            return False, f'{label}: hero is not visible.'
        member_x, member_y, _member_z = Agent.GetXYZ(agent_id)
        assignment.offset_x, assignment.offset_y = inverse_rotate_offset(
            float(member_x) - float(leader_x),
            float(member_y) - float(leader_y),
            facing_angle,
        )
        return True, f'{label}: offset captured.'

    if assignment.kind == ASSIGNMENT_ACCOUNT:
        account = _resolve_account_assignment_for_mode(assignment, target_mode)
        if account is None:
            if normalize_target_mode(target_mode, default=TARGET_MODE_IDENTITY) == TARGET_MODE_PARTY_SLOT:
                return False, f'{_player_slot_label(assignment.account_party_position)}: account slot is empty.'
            return False, f'{assignment.display_name()}: account not found.'

        label = (
            _player_slot_label(assignment.account_party_position, _account_label(account))
            if normalize_target_mode(target_mode, default=TARGET_MODE_IDENTITY) == TARGET_MODE_PARTY_SLOT
            else _account_label(account)
        )
        agent_id = int(getattr(getattr(account, 'AgentData', None), 'AgentID', 0) or 0)
        if agent_id > 0 and Agent.IsValid(agent_id):
            member_x, member_y, _member_z = Agent.GetXYZ(agent_id)
        else:
            position = getattr(getattr(account, 'AgentData', None), 'Pos', None)
            member_x = float(getattr(position, 'x', 0.0) or 0.0)
            member_y = float(getattr(position, 'y', 0.0) or 0.0)
            if abs(member_x) <= 0.001 and abs(member_y) <= 0.001:
                return False, f'{label}: account position is unavailable.'

        assignment.offset_x, assignment.offset_y = inverse_rotate_offset(
            float(member_x) - float(leader_x),
            float(member_y) - float(leader_y),
            facing_angle,
        )
        return True, f'{label}: offset captured.'

    return False, f'{assignment.display_name()}: unknown assignment type {assignment.kind}.'


def _add_static_preflight_items(snapshot: FormationPreflightSnapshot, formation: PartyFormation) -> None:
    for index, assignment in enumerate(formation.assignments):
        spot_label = assignment_spot_label(assignment, index)
        if not bool(getattr(assignment, 'enabled', True)):
            snapshot.add_item(index, spot_label, assignment.display_name(), PREFLIGHT_STATUS_SKIPPED, 'Disabled spot.')
            continue
        if assignment.kind == ASSIGNMENT_UNASSIGNED:
            snapshot.add_item(index, spot_label, '', PREFLIGHT_STATUS_SKIPPED, 'No target assigned.')
            continue

        offset_warning = preflight_assignment_offset_warning(assignment)
        if offset_warning:
            snapshot.add_item(
                index,
                spot_label,
                assignment.display_name(),
                PREFLIGHT_STATUS_WARNING,
                offset_warning,
            )


def preflight_apply_snapshot(formation: PartyFormation) -> FormationPreflightSnapshot:
    snapshot = FormationPreflightSnapshot(counts=formation_preflight_counts(formation))
    for duplicate in formation_duplicate_target_groups(formation):
        snapshot.add_warning_note(f'Duplicate {duplicate.target_label}: {", ".join(duplicate.spot_labels)}')

    try:
        from Py4GWCoreLib.HeroAI.utils import SameMapOrPartyAsAccount
        from Py4GWCoreLib.Agent import Agent
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
        from Py4GWCoreLib.Map import Map
        from Py4GWCoreLib.Party import Party
        from Py4GWCoreLib.Player import Player

        snapshot.runtime_checked = True

        if not Map.IsMapReady() or Map.IsMapLoading() or Map.IsInCinematic():
            snapshot.add_item(-1, 'Apply', '', PREFLIGHT_STATUS_SKIPPED, 'Map is not ready.')
            return snapshot
        if not Map.IsExplorable():
            snapshot.add_item(-1, 'Apply', '', PREFLIGHT_STATUS_SKIPPED, 'Current map is not explorable.')
            return snapshot
        if not Party.IsPartyLoaded():
            snapshot.add_item(-1, 'Apply', '', PREFLIGHT_STATUS_SKIPPED, 'Party is not loaded.')
            return snapshot

        leader_id = int(Party.GetPartyLeaderID() or 0)
        if leader_id <= 0 or int(Player.GetAgentID() or 0) != leader_id:
            snapshot.add_item(
                -1,
                'Apply',
                '',
                PREFLIGHT_STATUS_SKIPPED,
                'Only the party leader can apply party formations.',
            )
            return snapshot
        if not Agent.IsValid(leader_id):
            snapshot.add_item(-1, 'Apply', '', PREFLIGHT_STATUS_SKIPPED, 'Party leader agent is not valid.')
            return snapshot

        snapshot.runtime_ready = True
        leader_x, leader_y, _leader_z = Agent.GetXYZ(leader_id)
        facing_angle = float(Agent.GetRotationAngle(leader_id) or 0.0)
        target_mode = normalize_target_mode(formation.target_mode, default=TARGET_MODE_IDENTITY)
        party_slot_mode = target_mode == TARGET_MODE_PARTY_SLOT

        for index, assignment in enumerate(formation.assignments):
            spot_label = assignment_spot_label(assignment, index)
            if not assignment.enabled:
                snapshot.add_item(
                    index,
                    spot_label,
                    assignment.display_name(),
                    PREFLIGHT_STATUS_SKIPPED,
                    'Disabled spot.',
                )
                continue
            if assignment.kind == ASSIGNMENT_UNASSIGNED:
                snapshot.add_item(index, spot_label, '', PREFLIGHT_STATUS_SKIPPED, 'No target assigned.')
                continue

            offset_warning = preflight_assignment_offset_warning(assignment)
            if offset_warning and offset_warning != 'Offset is unusually large.':
                snapshot.add_item(
                    index,
                    spot_label,
                    assignment.display_name(),
                    PREFLIGHT_STATUS_WARNING,
                    offset_warning,
                )
                continue
            if offset_warning:
                snapshot.add_warning_note(f'{spot_label}: {offset_warning}')

            rotated_x, rotated_y = rotate_offset(float(assignment.offset_x), float(assignment.offset_y), facing_angle)
            target_x = float(leader_x) + rotated_x
            target_y = float(leader_y) + rotated_y

            if assignment.kind == ASSIGNMENT_HERO:
                agent_id, label = _resolve_hero_assignment_for_mode(assignment, target_mode)
                if agent_id <= 0:
                    message = (
                        f'{label}: hero slot is empty.'
                        if party_slot_mode
                        else f'{assignment.display_name()}: hero not found.'
                    )
                    snapshot.add_item(index, spot_label, label, PREFLIGHT_STATUS_SKIPPED, message)
                    continue
                if not Agent.IsValid(agent_id):
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: hero agent is not valid.',
                    )
                    continue
                if Agent.IsDead(agent_id):
                    snapshot.add_item(index, spot_label, label, PREFLIGHT_STATUS_SKIPPED, f'{label}: hero is dead.')
                    continue

                snapshot.add_item(
                    index,
                    spot_label,
                    label,
                    PREFLIGHT_STATUS_WOULD_TARGET,
                    f'{label}: hero would be flagged.',
                    target_x,
                    target_y,
                )
                continue

            if assignment.kind == ASSIGNMENT_ACCOUNT:
                account = _resolve_account_assignment_for_mode(assignment, target_mode)
                if account is None:
                    message = (
                        f'{_player_slot_label(assignment.account_party_position)}: account slot is empty.'
                        if party_slot_mode
                        else f'{assignment.display_name()}: account not found.'
                    )
                    snapshot.add_item(
                        index,
                        spot_label,
                        assignment.display_name(),
                        PREFLIGHT_STATUS_SKIPPED,
                        message,
                    )
                    continue
                label = (
                    _player_slot_label(assignment.account_party_position, _account_label(account))
                    if party_slot_mode
                    else _account_label(account)
                )
                if not bool(getattr(account, 'IsSlotActive', False)):
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: account slot is inactive.',
                    )
                    continue
                if not SameMapOrPartyAsAccount(account):
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: account is not in the same map or party.',
                    )
                    continue
                if int(getattr(getattr(account, 'AgentPartyData', None), 'PartyID', 0) or 0) != int(
                    Party.GetPartyID() or 0
                ):
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: account is not in the current party.',
                    )
                    continue

                agent_data = getattr(account, 'AgentData', None)
                agent_id = int(getattr(agent_data, 'AgentID', 0) or 0)
                if agent_id <= 0:
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: account agent id is missing.',
                    )
                    continue
                if Agent.IsValid(agent_id) and Agent.IsDead(agent_id):
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: account is dead.',
                    )
                    continue
                if not Agent.IsValid(agent_id):
                    health = getattr(agent_data, 'Health', None)
                    current_health = float(getattr(health, 'Current', 0.0) or 0.0)
                    if current_health <= 0.0:
                        snapshot.add_item(
                            index,
                            spot_label,
                            label,
                            PREFLIGHT_STATUS_SKIPPED,
                            f'{label}: account health is unavailable or dead.',
                        )
                        continue

                options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(str(getattr(account, 'AccountEmail', '') or ''))
                if options is None:
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: HeroAI options are unavailable.',
                    )
                    continue
                if not bool(getattr(options, 'Following', False)):
                    snapshot.add_item(
                        index,
                        spot_label,
                        label,
                        PREFLIGHT_STATUS_SKIPPED,
                        f'{label}: HeroAI following is disabled.',
                    )
                    continue

                snapshot.add_item(
                    index,
                    spot_label,
                    label,
                    PREFLIGHT_STATUS_WOULD_TARGET,
                    f'{label}: account flag would be set.',
                    target_x,
                    target_y,
                )
                continue

            snapshot.add_item(
                index,
                spot_label,
                assignment.display_name(),
                PREFLIGHT_STATUS_SKIPPED,
                f'{assignment.display_name()}: unknown assignment type {assignment.kind}.',
            )

        return snapshot
    except Exception as exc:
        snapshot.add_warning_note(f'Preview unavailable: {exc}')
        if not snapshot.items:
            _add_static_preflight_items(snapshot, formation)
        return snapshot


def apply_formation(formation: PartyFormation) -> FormationApplyResult:
    from Py4GWCoreLib.HeroAI.utils import SameMapOrPartyAsAccount
    from Py4GWCoreLib.Agent import Agent
    from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
    from Py4GWCoreLib.Map import Map
    from Py4GWCoreLib.Party import Party
    from Py4GWCoreLib.Player import Player

    result = FormationApplyResult()

    if not Map.IsMapReady() or Map.IsMapLoading() or Map.IsInCinematic():
        result.add_skipped('Map is not ready.')
        return result
    if not Map.IsExplorable():
        result.add_skipped('Current map is not explorable.')
        return result
    if not Party.IsPartyLoaded():
        result.add_skipped('Party is not loaded.')
        return result

    leader_id = int(Party.GetPartyLeaderID() or 0)
    if leader_id <= 0 or int(Player.GetAgentID() or 0) != leader_id:
        result.add_skipped('Only the party leader can apply party formations.')
        return result
    if not Agent.IsValid(leader_id):
        result.add_skipped('Party leader agent is not valid.')
        return result

    leader_x, leader_y, _leader_z = Agent.GetXYZ(leader_id)
    facing_angle = float(Agent.GetRotationAngle(leader_id) or 0.0)
    target_mode = normalize_target_mode(formation.target_mode, default=TARGET_MODE_IDENTITY)
    party_slot_mode = target_mode == TARGET_MODE_PARTY_SLOT

    for assignment in formation.assignments:
        if not assignment.enabled:
            continue
        if assignment.kind == ASSIGNMENT_UNASSIGNED:
            continue

        rotated_x, rotated_y = rotate_offset(float(assignment.offset_x), float(assignment.offset_y), facing_angle)
        target_x = float(leader_x) + rotated_x
        target_y = float(leader_y) + rotated_y

        if assignment.kind == ASSIGNMENT_HERO:
            agent_id, label = _resolve_hero_assignment_for_mode(assignment, target_mode)
            if agent_id <= 0:
                message = (
                    f'{label}: hero slot is empty.'
                    if party_slot_mode
                    else f'{assignment.display_name()}: hero not found.'
                )
                result.add_skipped(message)
                continue
            if not Agent.IsValid(agent_id):
                result.add_skipped(f'{label}: hero agent is not valid.')
                continue
            if Agent.IsDead(agent_id):
                result.add_skipped(f'{label}: hero is dead.')
                continue

            Party.Heroes.FlagHero(agent_id, target_x, target_y)
            result.add_applied(f'{label}: hero flagged.')
            continue

        if assignment.kind == ASSIGNMENT_ACCOUNT:
            account = _resolve_account_assignment_for_mode(assignment, target_mode)
            if account is None:
                message = (
                    f'{_player_slot_label(assignment.account_party_position)}: account slot is empty.'
                    if party_slot_mode
                    else f'{assignment.display_name()}: account not found.'
                )
                result.add_skipped(message)
                continue
            label = (
                _player_slot_label(assignment.account_party_position, _account_label(account))
                if party_slot_mode
                else _account_label(account)
            )
            if not bool(getattr(account, 'IsSlotActive', False)):
                result.add_skipped(f'{label}: account slot is inactive.')
                continue
            if not SameMapOrPartyAsAccount(account):
                result.add_skipped(f'{label}: account is not in the same map or party.')
                continue
            if int(getattr(getattr(account, 'AgentPartyData', None), 'PartyID', 0) or 0) != int(
                Party.GetPartyID() or 0
            ):
                result.add_skipped(f'{label}: account is not in the current party.')
                continue

            agent_data = getattr(account, 'AgentData', None)
            agent_id = int(getattr(agent_data, 'AgentID', 0) or 0)
            if agent_id <= 0:
                result.add_skipped(f'{label}: account agent id is missing.')
                continue
            if Agent.IsValid(agent_id) and Agent.IsDead(agent_id):
                result.add_skipped(f'{label}: account is dead.')
                continue
            if not Agent.IsValid(agent_id):
                health = getattr(agent_data, 'Health', None)
                current_health = float(getattr(health, 'Current', 0.0) or 0.0)
                if current_health <= 0.0:
                    result.add_skipped(f'{label}: account health is unavailable or dead.')
                    continue

            options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(str(getattr(account, 'AccountEmail', '') or ''))
            if options is None:
                result.add_skipped(f'{label}: HeroAI options are unavailable.')
                continue
            if not bool(getattr(options, 'Following', False)):
                result.add_skipped(f'{label}: HeroAI following is disabled.')
                continue

            options.FlagPos.x = target_x
            options.FlagPos.y = target_y
            options.FlagPosX = target_x
            options.FlagPosY = target_y
            options.FlagFacingAngle = facing_angle
            options.IsFlagged = True
            result.add_applied(f'{label}: account flag set.')
            continue

        result.add_skipped(f'{assignment.display_name()}: unknown assignment type {assignment.kind}.')

    return result


def clear_formation(formation: PartyFormation) -> FormationApplyResult:
    from Py4GWCoreLib.HeroAI.utils import SameMapOrPartyAsAccount
    from Py4GWCoreLib.Agent import Agent
    from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
    from Py4GWCoreLib.Map import Map
    from Py4GWCoreLib.Party import Party
    from Py4GWCoreLib.Player import Player

    result = FormationApplyResult()

    if not Map.IsMapReady() or Map.IsMapLoading() or Map.IsInCinematic():
        result.add_skipped('Map is not ready.')
        return result
    if not Map.IsExplorable():
        result.add_skipped('Current map is not explorable.')
        return result
    if not Party.IsPartyLoaded():
        result.add_skipped('Party is not loaded.')
        return result

    leader_id = int(Party.GetPartyLeaderID() or 0)
    if leader_id <= 0 or int(Player.GetAgentID() or 0) != leader_id:
        result.add_skipped('Only the party leader can clear party formations.')
        return result

    target_mode = normalize_target_mode(formation.target_mode, default=TARGET_MODE_IDENTITY)
    party_slot_mode = target_mode == TARGET_MODE_PARTY_SLOT

    for assignment in formation.assignments:
        if not assignment.enabled:
            continue
        if assignment.kind == ASSIGNMENT_UNASSIGNED:
            continue

        if assignment.kind == ASSIGNMENT_HERO:
            agent_id, hero_position, label = _resolve_hero_assignment_with_position_for_mode(assignment, target_mode)
            if agent_id <= 0:
                message = (
                    f'{label}: hero slot is empty.'
                    if party_slot_mode
                    else f'{assignment.display_name()}: hero not found.'
                )
                result.add_skipped(message)
                continue
            if hero_position <= 0:
                result.add_skipped(f'{label}: hero party position is unavailable.')
                continue
            if not Agent.IsValid(agent_id):
                result.add_skipped(f'{label}: hero agent is not valid.')
                continue
            if Agent.IsDead(agent_id):
                result.add_skipped(f'{label}: hero is dead.')
                continue

            Party.Heroes.UnflagHero(hero_position)
            result.add_applied(f'{label}: hero flag cleared.')
            continue

        if assignment.kind == ASSIGNMENT_ACCOUNT:
            account = _resolve_account_assignment_for_mode(assignment, target_mode)
            if account is None:
                message = (
                    f'{_player_slot_label(assignment.account_party_position)}: account slot is empty.'
                    if party_slot_mode
                    else f'{assignment.display_name()}: account not found.'
                )
                result.add_skipped(message)
                continue
            label = (
                _player_slot_label(assignment.account_party_position, _account_label(account))
                if party_slot_mode
                else _account_label(account)
            )
            if not bool(getattr(account, 'IsSlotActive', False)):
                result.add_skipped(f'{label}: account slot is inactive.')
                continue
            if not SameMapOrPartyAsAccount(account):
                result.add_skipped(f'{label}: account is not in the same map or party.')
                continue
            if int(getattr(getattr(account, 'AgentPartyData', None), 'PartyID', 0) or 0) != int(
                Party.GetPartyID() or 0
            ):
                result.add_skipped(f'{label}: account is not in the current party.')
                continue

            options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(str(getattr(account, 'AccountEmail', '') or ''))
            if options is None:
                result.add_skipped(f'{label}: HeroAI options are unavailable.')
                continue

            options.IsFlagged = False
            options.FlagPos.x = 0.0
            options.FlagPos.y = 0.0
            options.FlagPosX = 0.0
            options.FlagPosY = 0.0
            options.FlagFacingAngle = 0.0
            result.add_applied(f'{label}: account flag cleared.')
            continue

        result.add_skipped(f'{assignment.display_name()}: unknown assignment type {assignment.kind}.')

    return result
