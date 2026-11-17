from __future__ import annotations

import os
import unicodedata
from typing import TYPE_CHECKING
from typing import Literal
from typing import Protocol

from Sources.icefox.MerchantRules.item_values import safe_int

if TYPE_CHECKING:
    from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

import json
import re
import time
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import md5
from typing import Any, cast
from uuid import uuid4


LIVE_CONFIG_DOC_NAME = 'Widgets/MerchantRules/LiveConfig.json'
ACCOUNT_PROFILES_DOC_NAME = 'Widgets/MerchantRules/Profiles.json'
SHARED_PROFILES_DOC_NAME = 'Widgets/MerchantRules/SharedProfiles.json'
PROFILE_DOCUMENT_DIR = 'Widgets/MerchantRules/Profiles'
PROFILE_MIGRATION_STATE_DOC_NAME = 'Widgets/MerchantRules/ProfileMigrationState.json'
BACKUP_DOC_NAME = 'Widgets/MerchantRules/LiveConfigBackup.json'
LOADED_PROFILE_STATE_DOC_NAME = 'Widgets/MerchantRules/LoadedProfileState.json'
BACKUP_SCHEMA = 'merchant_rules_live_config_backup_v1'
BACKUP_SCHEMA_VERSION = 1
STANDALONE_PROFILE_SCHEMA = 'merchant_rules_shared_profile_v1'
STANDALONE_PROFILE_SCHEMA_VERSION = 1
# Keep the old public constant name as a source-compatible alias.  The value now
# describes the single standalone format used by both Shared and Account files.
SHARED_PROFILE_SCHEMA = STANDALONE_PROFILE_SCHEMA
SHARED_PROFILE_SCHEMA_VERSION = STANDALONE_PROFILE_SCHEMA_VERSION
PROFILE_MIGRATION_SCHEMA = 'merchant_rules_profile_migration_v1'
PROFILE_MIGRATION_SCHEMA_VERSION = 1
LOADED_PROFILE_STATE_SCHEMA = 'merchant_rules_loaded_profile_state_v1'
LOADED_PROFILE_STATE_SCHEMA_VERSION = 1
CHARACTER_PROFILE_STATE_DOC_NAME = 'Widgets/MerchantRules/CharacterProfileState.json'
CHARACTER_PROFILE_STATE_SCHEMA = 'merchant_rules_character_profile_state_v1'
CHARACTER_PROFILE_STATE_SCHEMA_VERSION = 1
PROFILE_SCOPE_SHARED = 'shared'
PROFILE_SCOPE_ACCOUNT = 'account'
PROFILE_SCOPES: tuple[str, ...] = (
    PROFILE_SCOPE_SHARED,
    PROFILE_SCOPE_ACCOUNT,
)


@dataclass(frozen=True)
class ProfileIdentity:
    """Identify one saved profile by semantic scope and exact saved-profile key."""

    scope: str
    key: str


@dataclass(frozen=True)
class LoadedProfileProvenance:
    """Remember the exact saved profile explicitly loaded into one account's live config."""

    source_identity: ProfileIdentity
    display_name_snapshot: str
    normalized_content_fingerprint: str
    associated_at_unix_ms: int


@dataclass(frozen=True)
class CharacterProfileAssociation:
    """Remember one character's explicitly loaded saved profile."""

    profile_identity: ProfileIdentity
    character_name_snapshot: str = ''


@dataclass
class ProfileSummary:
    """Hold validated saved-profile metadata and its normalized serialized payload."""

    identity: ProfileIdentity
    display_name: str
    filename: str = ''
    saved_at_label: str = ''
    saved_at_unix_ms: int = 0
    payload: dict[str, object] = field(default_factory=dict)
    serialized_payload: str = ''
    fingerprint: str = ''
    raw_wrapper: dict[str, object] | None = None

    @property
    def scope(self) -> str:
        return self.identity.scope

    @property
    def key(self) -> str:
        return self.identity.key

    @property
    def file_name(self) -> str:
        """Compatibility spelling for callers that use a file-oriented label."""

        return self.filename


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, str):
            return int(value.strip(), 0)
        return int(cast(Any, value))
    except Exception:
        return default


def _normalize_shared_profile_display_name(raw_value: object) -> str:
    if raw_value is None:
        return ''
    normalized = ' '.join(str(raw_value).replace('\r', ' ').replace('\n', ' ').split())
    return normalized.strip()


def _normalize_profile_id(raw_value: object) -> str:
    return str(raw_value or '').strip()


def is_valid_profile_id(raw_value: object) -> bool:
    return re.fullmatch(r'profile_[0-9a-f]{32}', _normalize_profile_id(raw_value)) is not None


def new_profile_id() -> str:
    return f'profile_{uuid4().hex}'


def _looks_like_merchant_rules_payload(raw_payload: object) -> bool:
    """Return whether a decoded object has the minimum shape of a Merchant Rules profile."""

    if not isinstance(raw_payload, dict):
        return False
    return any(
        key in raw_payload
        for key in (
            'buy_rules',
            'sell_rules',
            'destroy_rules',
            'identify_settings',
            'cleanup_targets',
            'cleanup_protection_sources',
            'auto_cleanup_on_outpost_entry',
            'auto_travel_enabled',
            'target_outpost_id',
            'favorite_outpost_ids',
            'debug_logging',
        )
    )


def _serialize_profile_payload(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def _serialize_saved_profile_wrapper(wrapper: object) -> str:
    normalized_wrapper = dict(wrapper) if isinstance(wrapper, dict) else {}
    return json.dumps(normalized_wrapper, sort_keys=True, separators=(',', ':'))


def _saved_profile_wrapper_fingerprint(wrapper: object) -> str:
    serialized_wrapper = _serialize_saved_profile_wrapper(wrapper)
    return md5(serialized_wrapper.encode('utf-8')).hexdigest()


def _format_shared_profile_timestamp(saved_at_unix_ms: int) -> str:
    safe_timestamp = max(0, _safe_int(saved_at_unix_ms, 0))
    if safe_timestamp <= 0:
        return ''
    try:
        return time.strftime(
            '%Y-%m-%d %H:%M:%S',
            time.localtime(float(safe_timestamp) / 1000.0),
        )
    except Exception:
        return ''


class ProfileStore:
    """Provide pure Merchant Rules profile models, validation, and transformations."""

    def __init__(
        self,
        normalize_payload: Callable[[object], dict[str, object]],
        profile_version: int,
    ) -> None:
        self._normalize_payload = normalize_payload
        self._profile_version = max(0, int(profile_version))

    def serialize_profile_payload(self, payload: dict[str, object]) -> str:
        return _serialize_profile_payload(payload)

    def shareable_profile_content_fingerprint(self, serialized_payload: str) -> str:
        return md5(str(serialized_payload or '').encode('utf-8')).hexdigest()

    def serialize_saved_profile_wrapper(self, wrapper: object) -> str:
        return _serialize_saved_profile_wrapper(wrapper)

    def saved_profile_wrapper_fingerprint(self, wrapper: object) -> str:
        return _saved_profile_wrapper_fingerprint(wrapper)

    def format_shared_profile_timestamp(self, saved_at_unix_ms: int) -> str:
        return _format_shared_profile_timestamp(saved_at_unix_ms)

    def build_shared_profile_wrapper(
        self,
        display_name: str,
        payload: dict[str, object],
        *,
        profile_id: str | None = None,
        saved_at_unix_ms: int | None = None,
        saved_at_label: str | None = None,
        payload_is_normalized: bool = False,
    ) -> dict[str, object]:
        normalized_name = _normalize_shared_profile_display_name(display_name)
        if not normalized_name:
            raise ValueError('Enter a profile name before saving.')
        safe_profile_id = _normalize_profile_id(profile_id) or new_profile_id()
        if not is_valid_profile_id(safe_profile_id):
            raise ValueError('The saved profile identity is invalid.')
        effective_saved_at_unix_ms = (
            max(0, _safe_int(saved_at_unix_ms, 0))
            if saved_at_unix_ms is not None
            else int(time.time() * 1000)
        )
        shareable_payload = payload if payload_is_normalized else self._normalize_payload(payload)
        return {
            'schema': SHARED_PROFILE_SCHEMA,
            'schema_version': SHARED_PROFILE_SCHEMA_VERSION,
            'profile_id': safe_profile_id,
            'name': normalized_name,
            'saved_at_unix_ms': effective_saved_at_unix_ms,
            'saved_at': (
                str(saved_at_label or '').strip()
                if saved_at_label is not None
                else _format_shared_profile_timestamp(effective_saved_at_unix_ms)
            ),
            'payload': shareable_payload,
        }

    def normalize_shared_profile_wrapper(
        self,
        raw_payload: object,
        *,
        fallback_name: str = '',
        require_profile_id: bool = False,
    ) -> dict[str, object]:
        """Validate a saved-profile wrapper and normalize its embedded payload."""

        if not isinstance(raw_payload, dict):
            raise ValueError('This saved profile is incomplete or damaged.') from ValueError(
                f'Saved Merchant Rules profile must be a JSON object, got {type(raw_payload).__name__}.'
            )

        schema = str(raw_payload.get('schema', '') or '').strip()
        if schema == SHARED_PROFILE_SCHEMA:
            raw_schema_version = _safe_int(raw_payload.get('schema_version', 0), 0)
            if raw_schema_version > SHARED_PROFILE_SCHEMA_VERSION:
                raise ValueError('This profile was created by a newer Merchant Rules version.') from ValueError(
                    f'Saved profile schema v{raw_schema_version} is newer than supported schema '
                    f'v{SHARED_PROFILE_SCHEMA_VERSION}.'
                )
            payload_source = raw_payload.get('payload', {})
            display_name_source = raw_payload.get('name', fallback_name)
            profile_id_source = raw_payload.get('profile_id', '')
        elif _looks_like_merchant_rules_payload(raw_payload):
            if require_profile_id:
                raise ValueError('This saved profile is missing its standalone identity.')
            payload_source = raw_payload
            display_name_source = fallback_name
            profile_id_source = ''
        else:
            raise ValueError('This saved profile uses an unsupported format.') from ValueError(
                f'Saved Merchant Rules profile schema {schema!r} is not supported.'
            )

        if require_profile_id and schema != SHARED_PROFILE_SCHEMA:
            raise ValueError('This saved profile uses an unsupported format.')

        profile_id = _normalize_profile_id(profile_id_source)
        if require_profile_id and not is_valid_profile_id(profile_id):
            raise ValueError('This saved profile is missing a valid standalone identity.')

        display_name = _normalize_shared_profile_display_name(display_name_source)
        if not display_name:
            raise ValueError(
                'This saved profile is incomplete or damaged because its name is missing.'
            ) from ValueError('Saved Merchant Rules profile name is missing.')

        payload_version = (
            _safe_int(payload_source.get('version', 0), 0)
            if isinstance(payload_source, dict)
            else 0
        )
        if payload_version > self._profile_version:
            raise ValueError('This profile was created by a newer Merchant Rules version.') from ValueError(
                f'Saved profile settings version {payload_version} is newer than Merchant Rules version '
                f'{self._profile_version}.'
            )

        if not isinstance(payload_source, dict):
            raise ValueError('This saved profile is incomplete or damaged.') from ValueError(
                'Saved Merchant Rules profile settings are missing.'
            )

        try:
            normalized_payload = self._normalize_payload(payload_source)
        except Exception as exc:
            raise ValueError('This saved profile is incomplete or damaged.') from exc
        saved_at_unix_ms = max(0, _safe_int(raw_payload.get('saved_at_unix_ms', 0), 0))
        saved_at = str(raw_payload.get('saved_at', '') or '').strip()
        if not saved_at:
            saved_at = _format_shared_profile_timestamp(saved_at_unix_ms)

        normalized_wrapper: dict[str, object] = {
            'schema': SHARED_PROFILE_SCHEMA,
            'schema_version': SHARED_PROFILE_SCHEMA_VERSION,
            'name': display_name,
            'saved_at_unix_ms': saved_at_unix_ms,
            'saved_at': saved_at,
            'payload': normalized_payload,
        }
        if profile_id:
            normalized_wrapper['profile_id'] = profile_id
        return normalized_wrapper

    def build_migrated_profile_wrapper(
        self,
        raw_payload: object,
        *,
        profile_id: str,
        fallback_name: str,
    ) -> dict[str, object]:
        """Wrap one legacy entry without normalizing or rewriting its payload."""

        safe_profile_id = _normalize_profile_id(profile_id)
        if not is_valid_profile_id(safe_profile_id):
            raise ValueError('The migrated profile identity is invalid.')
        if not isinstance(raw_payload, dict):
            raise ValueError('This saved profile is incomplete or damaged.')

        schema = str(raw_payload.get('schema', '') or '').strip()
        if schema == SHARED_PROFILE_SCHEMA:
            raw_schema_version = _safe_int(raw_payload.get('schema_version', 0), 0)
            if raw_schema_version > SHARED_PROFILE_SCHEMA_VERSION:
                raise ValueError('This profile was created by a newer Merchant Rules version.')
            payload_source = raw_payload.get('payload')
            display_name_source = raw_payload.get('name', fallback_name)
            saved_at_unix_ms = max(0, _safe_int(raw_payload.get('saved_at_unix_ms', 0), 0))
            saved_at = str(raw_payload.get('saved_at', '') or '').strip()
        elif _looks_like_merchant_rules_payload(raw_payload):
            payload_source = raw_payload
            display_name_source = fallback_name
            saved_at_unix_ms = 0
            saved_at = ''
        else:
            raise ValueError('This saved profile uses an unsupported format.')

        if not isinstance(payload_source, dict):
            raise ValueError('This saved profile is incomplete or damaged.')
        raw_version = _safe_int(payload_source.get('version', 0), 0)
        if raw_version > self._profile_version:
            raise ValueError('This profile was created by a newer Merchant Rules version.')
        display_name = _normalize_shared_profile_display_name(display_name_source)
        if not display_name:
            raise ValueError('This saved profile is incomplete or damaged because its name is missing.')
        if not saved_at and saved_at_unix_ms:
            saved_at = _format_shared_profile_timestamp(saved_at_unix_ms)

        return {
            'schema': SHARED_PROFILE_SCHEMA,
            'schema_version': SHARED_PROFILE_SCHEMA_VERSION,
            'profile_id': safe_profile_id,
            'name': display_name,
            'saved_at_unix_ms': saved_at_unix_ms,
            'saved_at': saved_at,
            'payload': deepcopy(payload_source),
        }

    def rename_profile_wrapper(
        self,
        raw_wrapper: object,
        *,
        profile_id: str,
        display_name: str,
        fallback_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Change only the standalone display name while retaining stored payload bytes semantically."""

        safe_profile_id = _normalize_profile_id(profile_id)
        if not is_valid_profile_id(safe_profile_id):
            raise ValueError('The saved profile identity is invalid.')
        normalized_name = _normalize_shared_profile_display_name(display_name)
        if not normalized_name:
            raise ValueError('Enter a profile name before saving.')
        if isinstance(raw_wrapper, dict):
            raw_saved_at_unix_ms = max(0, _safe_int(raw_wrapper.get('saved_at_unix_ms', 0), 0))
            raw_saved_at = str(raw_wrapper.get('saved_at', '') or '').strip()
            payload = raw_wrapper.get('payload', fallback_payload or {})
            renamed = {
                'schema': SHARED_PROFILE_SCHEMA,
                'schema_version': SHARED_PROFILE_SCHEMA_VERSION,
                'saved_at_unix_ms': raw_saved_at_unix_ms,
                'saved_at': raw_saved_at or _format_shared_profile_timestamp(raw_saved_at_unix_ms),
                'payload': deepcopy(payload),
            }
        else:
            renamed = {
                'schema': SHARED_PROFILE_SCHEMA,
                'schema_version': SHARED_PROFILE_SCHEMA_VERSION,
                'saved_at_unix_ms': 0,
                'saved_at': '',
                'payload': deepcopy(fallback_payload or {}),
            }
        renamed['schema'] = SHARED_PROFILE_SCHEMA
        renamed['schema_version'] = SHARED_PROFILE_SCHEMA_VERSION
        renamed['profile_id'] = safe_profile_id
        renamed['name'] = normalized_name
        return renamed

    def load_profile_summary_from_key(
        self,
        scope: str,
        profile_key: str,
        raw_payload: object,
        *,
        filename: str = '',
    ) -> ProfileSummary:
        safe_key = str(profile_key)
        normalized_wrapper = self.normalize_shared_profile_wrapper(
            raw_payload,
            fallback_name='',
            require_profile_id=True,
        )
        normalized_profile_id = _normalize_profile_id(normalized_wrapper.get('profile_id', ''))
        if normalized_profile_id != safe_key:
            raise ValueError('This saved profile identity changed while it was being read.')
        normalized_payload = normalized_wrapper.get('payload', {})
        if not isinstance(normalized_payload, dict):
            raise ValueError('This saved profile is incomplete or damaged.') from ValueError(
                'Saved Merchant Rules profile settings are missing.'
            )
        payload: dict[str, object] = {}
        for raw_key, value in normalized_payload.items():
            if not isinstance(raw_key, str):
                raise ValueError('This saved profile is incomplete or damaged.') from ValueError(
                    'Saved Merchant Rules profile settings contain a non-string key.'
                )
            payload[raw_key] = value
        saved_at_unix_ms = max(
            0,
            _safe_int(normalized_wrapper.get('saved_at_unix_ms', 0), 0),
        )
        saved_at_label = str(normalized_wrapper.get('saved_at', '') or '').strip()
        if not saved_at_label:
            saved_at_label = _format_shared_profile_timestamp(saved_at_unix_ms)
        return ProfileSummary(
            identity=ProfileIdentity(scope=scope, key=normalized_profile_id),
            display_name=str(normalized_wrapper.get('name', '') or safe_key),
            filename=str(filename or ''),
            saved_at_label=saved_at_label,
            saved_at_unix_ms=saved_at_unix_ms,
            payload=payload,
            serialized_payload=_serialize_profile_payload(payload),
            fingerprint=_saved_profile_wrapper_fingerprint(normalized_wrapper),
            raw_wrapper=deepcopy(raw_payload) if isinstance(raw_payload, dict) else None,
        )

    def get_backup_payload(self, raw_backup: object) -> dict[str, object] | None:
        if not isinstance(raw_backup, dict):
            return None
        if str(raw_backup.get('schema', '') or '') != BACKUP_SCHEMA:
            return None
        schema_version = _safe_int(raw_backup.get('schema_version', 0), 0)
        if schema_version > BACKUP_SCHEMA_VERSION:
            raise ValueError(
                f'Backup schema v{schema_version} is newer than supported schema v{BACKUP_SCHEMA_VERSION}.'
            )
        last_known_good = raw_backup.get('last_known_good', {})
        if not isinstance(last_known_good, dict):
            return None
        raw_payload = last_known_good.get('payload')
        if not isinstance(raw_payload, dict):
            return None
        raw_version = _safe_int(raw_payload.get('version', 0), 0)
        if raw_version > self._profile_version:
            raise ValueError(
                f'Backup profile version {raw_version} is newer than Merchant Rules version '
                f'{self._profile_version}.'
            )
        return self._normalize_payload(raw_payload)

    def build_backup_root(
        self,
        existing_root: object,
        payload: dict[str, object],
        *,
        slot: str = 'last_known_good',
    ) -> dict[str, object]:
        raw_version = _safe_int(payload.get('version', 0), 0)
        if raw_version > self._profile_version:
            raise ValueError(f'Cannot back up future Merchant Rules profile version {raw_version}.')
        normalized_payload = self._normalize_payload(payload)
        backup_root = dict(existing_root) if isinstance(existing_root, dict) else {}
        backup_root['schema'] = BACKUP_SCHEMA
        backup_root['schema_version'] = BACKUP_SCHEMA_VERSION
        backup_root[slot] = {
            'saved_at_unix_ms': int(time.time() * 1000),
            'payload': normalized_payload,
        }
        return backup_root

    def provenance_to_json(self, provenance: LoadedProfileProvenance) -> dict[str, object]:
        return {
            'schema': LOADED_PROFILE_STATE_SCHEMA,
            'schema_version': LOADED_PROFILE_STATE_SCHEMA_VERSION,
            'source_scope': provenance.source_identity.scope,
            'source_key': provenance.source_identity.key,
            'display_name_snapshot': provenance.display_name_snapshot,
            'normalized_content_fingerprint': provenance.normalized_content_fingerprint,
            'associated_at_unix_ms': max(0, int(provenance.associated_at_unix_ms)),
        }

    def normalize_provenance(self, raw_state: object) -> LoadedProfileProvenance:
        if not isinstance(raw_state, dict):
            raise ValueError('Loaded-profile provenance must be a JSON object.')
        if str(raw_state.get('schema', '') or '').strip() != LOADED_PROFILE_STATE_SCHEMA:
            raise ValueError('Loaded-profile provenance schema is not supported.')
        schema_version = _safe_int(raw_state.get('schema_version', 0), 0)
        if schema_version <= 0:
            raise ValueError('Loaded-profile provenance schema version is missing.')
        if schema_version > LOADED_PROFILE_STATE_SCHEMA_VERSION:
            raise ValueError(
                f'Loaded-profile provenance schema v{schema_version} is newer than supported schema '
                f'v{LOADED_PROFILE_STATE_SCHEMA_VERSION}.'
            )
        source_scope = str(raw_state.get('source_scope', '') or '').strip()
        if source_scope not in PROFILE_SCOPES:
            raise ValueError('Loaded-profile provenance source scope is invalid.')
        source_key = str(raw_state.get('source_key', '') or '').strip()
        if not source_key:
            raise ValueError('Loaded-profile provenance source key is missing.')
        display_name_snapshot = _normalize_shared_profile_display_name(
            raw_state.get('display_name_snapshot', '')
        )
        if not display_name_snapshot:
            display_name_snapshot = source_key
        content_fingerprint = str(raw_state.get('normalized_content_fingerprint', '') or '').strip().lower()
        if re.fullmatch(r'[0-9a-f]{32}', content_fingerprint) is None:
            raise ValueError('Loaded-profile provenance content fingerprint is invalid.')
        return LoadedProfileProvenance(
            source_identity=ProfileIdentity(source_scope, source_key),
            display_name_snapshot=display_name_snapshot,
            normalized_content_fingerprint=content_fingerprint,
            associated_at_unix_ms=max(0, _safe_int(raw_state.get('associated_at_unix_ms', 0), 0)),
        )


def normalize_character_profile_state_root(raw_state: object) -> dict[str, object]:
    """Validate the independent root schema for per-character profile memory."""

    if not isinstance(raw_state, dict):
        raise ValueError('Character profile state must be a JSON object.')
    state = cast(dict[str, object], raw_state)
    if str(state.get('schema', '') or '').strip() != CHARACTER_PROFILE_STATE_SCHEMA:
        raise ValueError('Character profile state schema is not supported.')
    schema_version = _safe_int(state.get('schema_version', 0), 0)
    if schema_version != CHARACTER_PROFILE_STATE_SCHEMA_VERSION:
        if schema_version > CHARACTER_PROFILE_STATE_SCHEMA_VERSION:
            raise ValueError(
                f'Character profile state schema v{schema_version} is newer than supported schema '
                f'v{CHARACTER_PROFILE_STATE_SCHEMA_VERSION}.'
            )
        raise ValueError('Character profile state schema version is not supported.')
    characters = state.get('characters', {})
    if not isinstance(characters, dict):
        raise ValueError('Character profile state entries must be a JSON object.')
    return state


def character_profile_association_from_json(raw_entry: object) -> CharacterProfileAssociation:
    """Validate one character mapping without making other entries authoritative."""

    if not isinstance(raw_entry, dict):
        raise ValueError('Character profile association must be a JSON object.')
    entry = cast(dict[str, object], raw_entry)
    source_scope = str(entry.get('source_scope', '') or '').strip()
    source_key = str(entry.get('source_key', '') or '').strip()
    if source_scope not in PROFILE_SCOPES:
        raise ValueError('Character profile association scope is invalid.')
    if not is_valid_profile_id(source_key):
        raise ValueError('Character profile association key is invalid.')
    name_snapshot = _normalize_shared_profile_display_name(entry.get('character_name_snapshot', ''))[:128]
    return CharacterProfileAssociation(
        profile_identity=ProfileIdentity(source_scope, source_key),
        character_name_snapshot=name_snapshot,
    )


def character_profile_association_to_json(
    association: CharacterProfileAssociation,
) -> dict[str, object]:
    """Serialize one mapping using the stable saved-profile identity only."""

    identity = association.profile_identity
    if identity.scope not in PROFILE_SCOPES or not is_valid_profile_id(identity.key):
        raise ValueError('Character profile association identity is invalid.')
    return {
        'source_scope': identity.scope,
        'source_key': identity.key,
        'character_name_snapshot': _normalize_shared_profile_display_name(association.character_name_snapshot)[:128],
    }


PROFILE_FILENAME_MAX_STEM_LENGTH = 180

PROFILE_FILENAME_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

PROFILE_FILENAME_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)


class SavedProfileSession:
    def __init__(
        self,
        *,
        store: ProfileStore,
        factory_type: Callable[[], type[JsonFactory]],
        current_payload: Callable[[], dict[str, object]],
        default_payload: Callable[[], dict[str, object]],
        clear_generic_confirmation: Callable[[], None],
        publish_migrated_provenance: Callable[[LoadedProfileProvenance], None],
        warning: Callable[[Callable[[], str]], None],
    ) -> None:
        self._store = store
        self._factory_type = factory_type
        self._current_payload = current_payload
        self._default_payload = default_payload
        self._clear_generic_confirmation = clear_generic_confirmation
        self._publish_migrated_provenance = publish_migrated_provenance
        self._warning = warning
        self.profile_entries: dict[str, list[ProfileSummary]] = {scope: [] for scope in PROFILE_SCOPES}
        self.profile_known_filenames: dict[str, set[str]] = {scope: set() for scope in PROFILE_SCOPES}
        self.profile_selection_cleared_due_to_disappearance: dict[str, bool] = {
            scope: False for scope in PROFILE_SCOPES
        }
        self.profile_scan_conflicts: dict[str, dict[str, str]] = {scope: {} for scope in PROFILE_SCOPES}
        self.migration_in_progress: set[str] = set()
        self.profile_selected_identities: dict[str, ProfileIdentity | None] = {scope: None for scope in PROFILE_SCOPES}
        self.profile_name_inputs: dict[str, str] = {scope: "" for scope in PROFILE_SCOPES}
        self.profile_name_input_dirty: dict[str, bool] = {scope: False for scope in PROFILE_SCOPES}
        self.saved_profile_warnings: dict[str, str] = {scope: "" for scope in PROFILE_SCOPES}
        self.saved_profile_notices: dict[str, str] = {scope: "" for scope in PROFILE_SCOPES}
        self.saved_profile_scan_warnings: dict[str, str] = {scope: "" for scope in PROFILE_SCOPES}
        self.saved_profile_failure_signatures: dict[str, dict[str, tuple[str, str]]] = {
            scope: {} for scope in PROFILE_SCOPES
        }
        self.profile_entries_loaded: dict[str, bool] = {scope: False for scope in PROFILE_SCOPES}
        self.profile_document_reload_failed: dict[str, bool] = {scope: False for scope in PROFILE_SCOPES}
        self.active_profiles_scope = PROFILE_SCOPE_ACCOUNT
        self.profile_scroll_to_identity: ProfileIdentity | None = None
        self.pending_profile_confirmation_identity: ProfileIdentity | None = None
        self.pending_profile_confirmation_fingerprint = ""
        self.pending_profile_confirmation_action = ""

    def profile_doc(self, scope: str) -> JsonFactory:
        """Return a legacy bundled profile document for migration input only."""
        if scope == PROFILE_SCOPE_SHARED:
            return self._factory_type()(SHARED_PROFILES_DOC_NAME, "global")
        if scope == PROFILE_SCOPE_ACCOUNT:
            return self._factory_type()(ACCOUNT_PROFILES_DOC_NAME)
        raise ValueError(f"Unsupported Merchant Rules profile scope: {scope!r}")

    def profile_migration_doc(self, scope: str) -> JsonFactory:
        """Return the additive migration journal for one profile scope."""

        if scope == PROFILE_SCOPE_SHARED:
            return self._factory_type()(PROFILE_MIGRATION_STATE_DOC_NAME, "global")
        if scope == PROFILE_SCOPE_ACCOUNT:
            return self._factory_type()(PROFILE_MIGRATION_STATE_DOC_NAME)
        raise ValueError(f"Unsupported Merchant Rules profile scope: {scope!r}")

    @staticmethod
    def profile_json_scope(scope: str) -> str:
        if scope == PROFILE_SCOPE_SHARED:
            return "global"
        if scope == PROFILE_SCOPE_ACCOUNT:
            return "account"
        raise ValueError(f"Unsupported Merchant Rules profile scope: {scope!r}")

    @staticmethod
    def validate_profile_filename(filename: str) -> str:
        safe_filename = str(filename or "")
        if (
            not safe_filename
            or safe_filename in {".", ".."}
            or "/" in safe_filename
            or "\\" in safe_filename
            or os.path.basename(safe_filename) != safe_filename
            or not safe_filename.casefold().endswith(".json")
        ):
            raise ValueError("The profile filename is not safe.")
        stem = safe_filename[:-5]
        if (
            not stem
            or len(stem) > PROFILE_FILENAME_MAX_STEM_LENGTH
            or PROFILE_FILENAME_INVALID_CHARS.search(safe_filename)
        ):
            raise ValueError("The profile filename is not safe.")
        if stem[-1:] in {".", " "}:
            raise ValueError("The profile filename is not safe.")
        if stem.upper().split(".", 1)[0] in PROFILE_FILENAME_RESERVED_NAMES:
            raise ValueError("The profile filename is reserved by Windows.")
        return safe_filename

    @staticmethod
    def sanitize_profile_filename_stem(display_name: str) -> str:
        stem = unicodedata.normalize("NFC", str(display_name or "").strip())
        stem = PROFILE_FILENAME_INVALID_CHARS.sub("-", stem)
        stem = " ".join(stem.split()).rstrip(" .")
        if not stem:
            stem = "Profile"
        if stem.upper().split(".", 1)[0] in PROFILE_FILENAME_RESERVED_NAMES:
            stem = f"_{stem}"
        stem = stem[:PROFILE_FILENAME_MAX_STEM_LENGTH].rstrip(" .")
        return stem or "Profile"

    def profile_document_name(self, filename: str) -> str:
        safe_filename = self.validate_profile_filename(filename)
        return f"{PROFILE_DOCUMENT_DIR}/{safe_filename}"

    def profile_file_doc(self, scope: str, filename: str) -> JsonFactory:
        return self._factory_type()(
            self.profile_document_name(filename),
            self.profile_json_scope(scope),
        )

    def profile_directory_from_bound_doc(self, scope: str) -> str:
        doc_path = str(self.profile_doc(scope).path() or "").strip()
        if not doc_path:
            return ""
        document_directory = os.path.dirname(os.path.abspath(doc_path))
        return os.path.abspath(os.path.join(document_directory, "Profiles"))

    def ensure_profiles_dir(self, scope: str, *, create: bool = True) -> str:
        folder_path = self.profile_directory_from_bound_doc(scope)
        if not folder_path:
            return ""
        if os.path.islink(folder_path):
            raise OSError("The Merchant Rules profiles directory must not be a symbolic link.")
        if create:
            os.makedirs(folder_path, exist_ok=True)
        if os.path.islink(folder_path) or not os.path.isdir(folder_path):
            raise OSError("The Merchant Rules profiles directory is not a regular directory.")
        return folder_path

    def profile_file_path(self, scope: str, filename: str) -> str:
        safe_filename = self.validate_profile_filename(filename)
        folder_path = self.ensure_profiles_dir(scope, create=True)
        if not folder_path:
            raise RuntimeError(f"{self.profile_scope_label(scope)} are not ready for this account yet.")
        candidate_path = os.path.abspath(os.path.join(folder_path, safe_filename))
        try:
            common_path = os.path.commonpath((os.path.normcase(folder_path), os.path.normcase(candidate_path)))
        except ValueError as exc:
            raise ValueError("The profile filename is outside the Merchant Rules profiles folder.") from exc
        if common_path != os.path.normcase(folder_path) or os.path.normcase(
            os.path.dirname(candidate_path)
        ) != os.path.normcase(folder_path):
            raise ValueError("The profile filename is outside the Merchant Rules profiles folder.")
        return candidate_path

    def is_profile_file_present(self, scope: str, filename: str) -> bool:
        try:
            file_path = self.profile_file_path(scope, filename)
        except Exception:
            return False
        return bool(os.path.isfile(file_path) and not os.path.islink(file_path))

    def enumerate_profile_filenames(self, scope: str) -> list[str]:
        folder_path = self.ensure_profiles_dir(scope, create=True)
        if not folder_path:
            return []
        filenames: list[str] = []
        with os.scandir(folder_path) as entries:
            for entry in entries:
                filename = str(entry.name)
                if not filename.casefold().endswith(".json"):
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                filenames.append(filename)
        return sorted(filenames, key=lambda value: (value.casefold(), value))

    def allocate_profile_filename(self, scope: str, display_name: str) -> str:
        base_stem = self.sanitize_profile_filename_stem(display_name)
        existing_names = {filename.casefold() for filename in self.enumerate_profile_filenames(scope)}
        for suffix in range(1, 10000):
            stem = base_stem if suffix == 1 else f"{base_stem} ({suffix})"
            candidate = f"{stem}.json"
            if candidate.casefold() not in existing_names:
                return candidate
        raise RuntimeError("Merchant Rules could not allocate a unique profile filename.")

    def profile_scope_label(self, scope: str) -> str:
        if scope == PROFILE_SCOPE_SHARED:
            return "Shared Profiles — All Accounts"
        if scope == PROFILE_SCOPE_ACCOUNT:
            return "Account Profiles — This Account Only"
        return "Profiles"

    def profile_scope_badge(self, scope: str) -> str:
        return "SHARED" if scope == PROFILE_SCOPE_SHARED else "ACCOUNT"

    def build_shared_profile_wrapper(
        self,
        display_name: str,
        *,
        profile_id: str | None = None,
        payload: dict[str, object] | None = None,
        saved_at_unix_ms: int | None = None,
        saved_at_label: str | None = None,
    ) -> dict[str, object]:
        source_payload = self._current_payload() if payload is None else payload
        return self._store.build_shared_profile_wrapper(
            display_name,
            source_payload,
            profile_id=profile_id,
            saved_at_unix_ms=saved_at_unix_ms,
            saved_at_label=saved_at_label,
            payload_is_normalized=payload is None,
        )

    def normalize_shared_profile_wrapper(
        self,
        raw_payload: object,
        *,
        fallback_name: str = "",
        require_profile_id: bool = False,
    ) -> dict[str, object]:
        return self._store.normalize_shared_profile_wrapper(
            raw_payload,
            fallback_name=fallback_name,
            require_profile_id=require_profile_id,
        )

    def load_profile_summary_from_key(
        self,
        scope: str,
        profile_key: str,
        raw_payload: object,
        *,
        filename: str = "",
    ) -> ProfileSummary:
        return self._store.load_profile_summary_from_key(
            scope,
            profile_key,
            raw_payload,
            filename=filename,
        )

    def get_saved_profile_read_error_text(self, exc: Exception) -> str:
        message = str(exc or "").strip()
        recognized_messages = (
            "This profile was created by a newer Merchant Rules version.",
            "This saved profile uses an unsupported format.",
            "This saved profile is incomplete or damaged",
        )
        if any(message.startswith(prefix) for prefix in recognized_messages):
            return message
        return "A saved profile could not be read."

    def format_exception_chain_for_log(self, exc: Exception) -> str:
        details: list[str] = []
        current: BaseException | None = exc
        while current is not None and len(details) < 4:
            details.append(f"{type(current).__name__}: {current}")
            current = current.__cause__
        return " <- ".join(details)

    def get_saved_profile_raw_fingerprint(self, raw_payload: object) -> str:
        if isinstance(raw_payload, dict):
            try:
                return self._store.saved_profile_wrapper_fingerprint(raw_payload)
            except Exception:
                pass
        try:
            raw_text = f"{type(raw_payload).__name__}:{raw_payload!r}"
        except Exception:
            raw_text = type(raw_payload).__name__
        return md5(raw_text.encode("utf-8", errors="backslashreplace")).hexdigest()

    def get_profile_by_identity(
        self,
        identity: ProfileIdentity | None,
    ) -> ProfileSummary | None:
        if identity is None or identity.scope not in PROFILE_SCOPES:
            return None
        for entry in self.profile_entries[identity.scope]:
            if entry.identity == identity:
                return entry
        return None

    def get_selected_profile(self, scope: str) -> ProfileSummary | None:
        return self.get_profile_by_identity(self.profile_selected_identities.get(scope))

    def clear_profile_confirmation_state(self) -> None:
        self.pending_profile_confirmation_identity = None
        self.pending_profile_confirmation_fingerprint = ""
        self.pending_profile_confirmation_action = ""
        self._clear_generic_confirmation()

    def set_selected_profile_key(self, scope: str, profile_key: str) -> None:
        safe_key = str(profile_key or "")
        next_identity = ProfileIdentity(scope=scope, key=safe_key) if safe_key else None
        selection_changed = self.profile_selected_identities.get(scope) != next_identity
        if selection_changed:
            self.clear_profile_confirmation_state()
        self.profile_selected_identities[scope] = next_identity
        if safe_key:
            self.profile_selection_cleared_due_to_disappearance[scope] = False
        selected_profile = self.get_selected_profile(scope)
        if selected_profile is not None and (selection_changed or not self.profile_name_input_dirty[scope]):
            self.profile_name_inputs[scope] = str(selected_profile.display_name)
            self.profile_name_input_dirty[scope] = False
        elif not safe_key and selection_changed:
            self.profile_name_inputs[scope] = ""
            self.profile_name_input_dirty[scope] = False

    def set_active_profiles_scope(self, scope: str) -> None:
        next_scope = scope if scope in PROFILE_SCOPES else PROFILE_SCOPE_ACCOUNT
        if next_scope == self.active_profiles_scope:
            return
        self.active_profiles_scope = next_scope
        self.clear_profile_confirmation_state()

    def select_profile_after_action(
        self,
        scope: str,
        profile_key: str,
        *,
        activate_scope: bool = False,
    ) -> None:
        self.set_selected_profile_key(scope, profile_key)
        identity = self.profile_selected_identities.get(scope)
        self.profile_scroll_to_identity = identity
        if activate_scope:
            self.set_active_profiles_scope(scope)

    def find_profile_by_name(
        self,
        scope: str,
        display_name: str,
        *,
        exclude_key: str = "",
    ) -> ProfileSummary | None:
        normalized_name = _normalize_shared_profile_display_name(display_name).casefold()
        if not normalized_name:
            return None
        for entry in self.profile_entries[scope]:
            if exclude_key and entry.key == exclude_key:
                continue
            if str(entry.display_name).casefold() == normalized_name:
                return entry
        return None

    def ensure_profile_name_available(
        self,
        scope: str,
        display_name: str,
        *,
        exclude_key: str = "",
    ) -> str:
        normalized_name = _normalize_shared_profile_display_name(display_name)
        if not normalized_name:
            raise ValueError("Enter a profile name before saving.")

        existing_by_name = self.find_profile_by_name(
            scope,
            normalized_name,
            exclude_key=exclude_key,
        )
        if existing_by_name is not None:
            raise ValueError(
                f"A {self.profile_scope_badge(scope).lower()} profile named "
                f"'{existing_by_name.display_name}' already exists."
            )
        return normalized_name

    def load_profile_migration_state(
        self,
        scope: str,
    ) -> tuple[JsonFactory, dict[str, object]]:
        doc = self.profile_migration_doc(scope)
        raw_state = doc.get_json("", None)
        if raw_state in (None, {}):
            return doc, {
                "schema": PROFILE_MIGRATION_SCHEMA,
                "schema_version": PROFILE_MIGRATION_SCHEMA_VERSION,
                "complete": False,
                "entries": {},
            }
        if not isinstance(raw_state, dict):
            raise ValueError("Merchant Rules profile migration state is malformed.")
        schema = str(raw_state.get("schema", "") or "").strip()
        if schema != PROFILE_MIGRATION_SCHEMA:
            raise ValueError("Merchant Rules profile migration state is unsupported.")
        schema_version = safe_int(raw_state.get("schema_version", 0), 0)
        if schema_version > PROFILE_MIGRATION_SCHEMA_VERSION:
            raise ValueError("Merchant Rules profile migration state is newer than this version.")
        entries = raw_state.get("entries", {})
        if not isinstance(entries, dict):
            raise ValueError("Merchant Rules profile migration state is malformed.")
        return doc, {
            "schema": PROFILE_MIGRATION_SCHEMA,
            "schema_version": PROFILE_MIGRATION_SCHEMA_VERSION,
            "complete": bool(raw_state.get("complete", False)),
            "entries": dict(entries),
        }

    @staticmethod
    def migration_state_error_text(entry: object) -> str:
        if not isinstance(entry, dict):
            return "A legacy profile could not be migrated."
        error = str(entry.get("error", "") or "").strip()
        return error or "A legacy profile could not be migrated."

    def save_profile_migration_state(
        self,
        doc: JsonFactory,
        state: dict[str, object],
    ) -> None:
        doc.set_json("", state)
        if not doc.save():
            doc.reload()
            raise OSError("Merchant Rules could not save profile migration progress.")
        if not doc.reload():
            raise OSError("Merchant Rules could not verify profile migration progress.")
        if doc.get_json("", None) != state:
            raise RuntimeError("Merchant Rules profile migration progress failed verification.")

    def remap_migrated_account_provenance(
        self,
        legacy_key: str,
        profile_id: str,
    ) -> str:
        """Update one valid legacy Account provenance key without touching unrelated state."""

        doc = self._factory_type()(LOADED_PROFILE_STATE_DOC_NAME)
        raw_state = doc.get_json("", None)
        if raw_state in (None, {}):
            return ""
        if not isinstance(raw_state, dict):
            return ""
        try:
            provenance = self._store.normalize_provenance(raw_state)
        except Exception:
            return ""
        if provenance.source_identity != ProfileIdentity(PROFILE_SCOPE_ACCOUNT, legacy_key):
            return ""

        remapped_state = dict(raw_state)
        remapped_state["source_key"] = profile_id
        try:
            doc.set_json("", remapped_state)
            if not doc.save():
                doc.reload()
                return "Merchant Rules could not update the last-loaded Account profile record during migration."
            if not doc.reload():
                return "Merchant Rules could not verify the last-loaded Account profile record during migration."
            verified = self._store.normalize_provenance(doc.get_json("", None))
            if verified.source_identity != ProfileIdentity(PROFILE_SCOPE_ACCOUNT, profile_id):
                return "Merchant Rules could not verify the migrated Account profile provenance."
            self._publish_migrated_provenance(verified)
            return ""
        except Exception as exc:
            try:
                doc.reload()
            except Exception:
                pass
            return f"Merchant Rules could not update the last-loaded Account profile record during migration: {exc}"

    def migrate_legacy_profiles(self, scope: str) -> list[str]:
        """Copy legacy bundled entries to standalone files without changing the source document."""

        if scope in self.migration_in_progress:
            return []
        if not self.ensure_profiles_dir(scope, create=True):
            return []

        migration_doc, state = self.load_profile_migration_state(scope)
        raw_entries = state.get("entries", {})
        if not isinstance(raw_entries, dict):
            raise ValueError("Merchant Rules profile migration state is malformed.")
        if bool(state.get("complete", False)) and not any(
            isinstance(entry, dict) and str(entry.get("status", "") or "") == "pending"
            for entry in raw_entries.values()
        ):
            return [
                self.migration_state_error_text(entry)
                for entry in raw_entries.values()
                if isinstance(entry, dict) and str(entry.get("status", "") or "") in {"invalid", "conflict"}
            ]
        state["complete"] = False

        legacy_root = self.profile_doc(scope).get_json("", None)
        if legacy_root in (None, {}):
            return []
        if not isinstance(legacy_root, dict):
            state["complete"] = True
            state["entries"] = raw_entries
            self.save_profile_migration_state(migration_doc, state)
            return ["The old Merchant Rules profile collection is not a JSON object."]

        warnings: list[str] = []
        self.migration_in_progress.add(scope)
        try:
            for raw_key, raw_entry in legacy_root.items():
                legacy_key = str(raw_key or "").strip()
                if not legacy_key:
                    warnings.append("A legacy Merchant Rules profile had no saved key and was skipped.")
                    continue
                source_fingerprint = self.get_saved_profile_raw_fingerprint(raw_entry)
                existing_record = raw_entries.get(legacy_key)
                if isinstance(existing_record, dict):
                    existing_status = str(existing_record.get("status", "") or "")
                    if existing_status == "migrated":
                        continue
                    if (
                        existing_status in {"invalid", "conflict"}
                        and str(existing_record.get("source_fingerprint", "") or "") == source_fingerprint
                    ):
                        warnings.append(self.migration_state_error_text(existing_record))
                        continue

                try:
                    previous_profile_id = (
                        str(existing_record.get("profile_id", "") or "") if isinstance(existing_record, dict) else ""
                    )
                    if is_valid_profile_id(previous_profile_id):
                        profile_id = previous_profile_id
                    elif scope == PROFILE_SCOPE_SHARED and is_valid_profile_id(legacy_key):
                        profile_id = legacy_key
                    else:
                        profile_id = new_profile_id()

                    migrated_wrapper = self._store.build_migrated_profile_wrapper(
                        raw_entry,
                        profile_id=profile_id,
                        fallback_name=legacy_key,
                    )

                    previous_filename = (
                        str(existing_record.get("filename", "") or "") if isinstance(existing_record, dict) else ""
                    )
                    if previous_filename:
                        filename = self.validate_profile_filename(previous_filename)
                    else:
                        filename = self.allocate_profile_filename(
                            scope,
                            str(migrated_wrapper.get("name", legacy_key) or legacy_key),
                        )

                    pending_record = {
                        "profile_id": profile_id,
                        "filename": filename,
                        "source_fingerprint": source_fingerprint,
                        "status": "pending",
                    }
                    raw_entries[legacy_key] = pending_record
                    state["entries"] = raw_entries
                    # Account mappings are durable before the first target write; this is also
                    # what makes a crash between allocation and creation resumable.
                    self.save_profile_migration_state(migration_doc, state)

                    expected = self.load_profile_summary_from_key(
                        scope,
                        profile_id,
                        migrated_wrapper,
                        filename=filename,
                    )
                    target_exists = self.is_profile_file_present(scope, filename)
                    if target_exists:
                        target_doc = self.profile_file_doc(scope, filename)
                        if not target_doc.reload() or not self.is_profile_file_present(scope, filename):
                            raise RuntimeError("The migrated profile file disappeared during verification.")
                        observed = self.load_profile_summary_from_key(
                            scope,
                            profile_id,
                            target_doc.get_json("", None),
                            filename=filename,
                        )
                        if observed.fingerprint != expected.fingerprint:
                            raise RuntimeError(f"The target file {filename!r} already contains different profile data.")
                    else:
                        self.persist_profile_wrapper(
                            scope,
                            profile_id,
                            migrated_wrapper,
                            filename=filename,
                            preserve_wrapper=True,
                            refresh_after=False,
                        )

                    if scope == PROFILE_SCOPE_ACCOUNT:
                        provenance_warning = self.remap_migrated_account_provenance(
                            legacy_key,
                            profile_id,
                        )
                        if provenance_warning:
                            warnings.append(provenance_warning)
                            pending_record["status"] = "pending"
                            pending_record["error"] = provenance_warning
                            state["complete"] = False
                            state["entries"] = raw_entries
                            self.save_profile_migration_state(migration_doc, state)
                            continue

                    pending_record["status"] = "migrated"
                    pending_record.pop("error", None)
                    state["entries"] = raw_entries
                    self.save_profile_migration_state(migration_doc, state)
                except Exception as exc:
                    error_text = f"Legacy profile {legacy_key!r} was not migrated: {exc}"
                    record = raw_entries.get(legacy_key)
                    if not isinstance(record, dict):
                        record = {
                            "source_fingerprint": source_fingerprint,
                        }
                        raw_entries[legacy_key] = record
                    if "different profile data" in str(exc):
                        record["status"] = "conflict"
                    elif isinstance(exc, ValueError):
                        record["status"] = "invalid"
                    else:
                        record["status"] = "pending"
                    record["source_fingerprint"] = source_fingerprint
                    record["error"] = error_text
                    state["entries"] = raw_entries
                    try:
                        self.save_profile_migration_state(migration_doc, state)
                    except Exception as state_exc:
                        warnings.append(f"{error_text} Migration progress could not be saved: {state_exc}")
                    warnings.append(error_text)

            state["complete"] = all(
                isinstance(entry, dict) and str(entry.get("status", "") or "") in {"migrated", "invalid", "conflict"}
                for entry in raw_entries.values()
            )
            state["entries"] = raw_entries
            self.save_profile_migration_state(migration_doc, state)
        finally:
            self.migration_in_progress.discard(scope)
        return warnings

    def refresh_profile_entries(
        self,
        scope: str,
        *,
        reload_document: bool = False,
        report_reload_failure: bool = True,
    ) -> bool:
        """Refresh standalone profile files while retaining exact identity selection."""

        if scope not in PROFILE_SCOPES:
            return False
        previous_identity = self.profile_selected_identities.get(scope)
        previous_selected = self.get_profile_by_identity(previous_identity)
        previous_fingerprint = previous_selected.fingerprint if previous_selected is not None else ""

        if scope == PROFILE_SCOPE_ACCOUNT and not self.profile_directory_from_bound_doc(scope):
            self.profile_entries[scope] = []
            self.profile_entries_loaded[scope] = False
            self.profile_known_filenames[scope].clear()
            self.profile_scan_conflicts[scope].clear()
            self.saved_profile_failure_signatures[scope].clear()
            self.profile_selected_identities[scope] = None
            self.profile_name_inputs[scope] = ""
            self.profile_name_input_dirty[scope] = False
            self.clear_profile_confirmation_state()
            return False

        try:
            migration_warnings = self.migrate_legacy_profiles(scope)
            filenames = self.enumerate_profile_filenames(scope)
        except Exception as exc:
            self.profile_document_reload_failed[scope] = True
            self.profile_entries_loaded[scope] = True
            if report_reload_failure:
                self.saved_profile_scan_warnings[scope] = (
                    f"Could not refresh {self.profile_scope_label(scope)}. "
                    "Showing the last profile list Merchant Rules could read."
                )
            self._warning(
                lambda error=exc: (
                    f"Could not enumerate {scope} Merchant Rules profile files: {self.format_exception_chain_for_log(error)}"
                )
            )
            return False

        entries: list[ProfileSummary] = []
        load_failures: list[str] = []
        previous_failure_signatures = self.saved_profile_failure_signatures[scope]
        current_failure_signatures: dict[str, tuple[str, str]] = {}
        previous_known_filenames = set(self.profile_known_filenames[scope])
        self.profile_known_filenames[scope] = set(filenames)

        for filename in filenames:
            raw_payload: object = None
            try:
                profile_doc = self.profile_file_doc(scope, filename)
                if reload_document or filename not in previous_known_filenames:
                    if not profile_doc.reload():
                        raise OSError("Merchant Rules could not reload this profile file.")
                if not self.is_profile_file_present(scope, filename):
                    raise FileNotFoundError("The profile file disappeared during refresh.")
                raw_payload = profile_doc.get_json("", None)
                if not isinstance(raw_payload, dict):
                    raise ValueError("This saved profile is incomplete or damaged.")
                normalized_wrapper = self.normalize_shared_profile_wrapper(
                    raw_payload,
                    require_profile_id=True,
                )
                profile_id = str(normalized_wrapper.get("profile_id", "") or "").strip()
                summary = self.load_profile_summary_from_key(
                    scope,
                    profile_id,
                    raw_payload,
                    filename=filename,
                )
                entries.append(summary)
            except Exception as exc:
                failure_text = self.format_exception_chain_for_log(exc)
                failure_signature = (
                    self.get_saved_profile_raw_fingerprint(raw_payload),
                    failure_text,
                )
                current_failure_signatures[filename] = failure_signature
                load_failures.append(self.get_saved_profile_read_error_text(exc))
                if previous_failure_signatures.get(filename) != failure_signature:
                    self._warning(
                        lambda: (
                            f"Could not read [{self.profile_scope_badge(scope)}] saved profile "
                            f"file {filename!r}: {failure_text}"
                        )
                    )

        duplicate_warnings: dict[str, str] = {}
        unique_entries: list[ProfileSummary] = []
        entries_by_identity: dict[str, ProfileSummary | None] = {}
        for entry in entries:
            profile_id = entry.key
            previous_entry = entries_by_identity.get(profile_id)
            if previous_entry is None and profile_id not in entries_by_identity:
                entries_by_identity[profile_id] = entry
                unique_entries.append(entry)
                continue
            if previous_entry is None:
                continue
            if previous_entry.serialized_payload == entry.serialized_payload:
                duplicate_warnings[entry.filename] = (
                    f"Profile ID {profile_id} appears in {previous_entry.filename!r} and "
                    f"{entry.filename!r}; only {previous_entry.filename!r} is shown."
                )
                continue
            unique_entries = [candidate for candidate in unique_entries if candidate.key != profile_id]
            entries_by_identity[profile_id] = None
            duplicate_warnings[previous_entry.filename] = (
                f"Profile ID {profile_id} has conflicting contents in {previous_entry.filename!r} "
                f"and {entry.filename!r}; neither file is available until the conflict is resolved."
            )
            duplicate_warnings[entry.filename] = duplicate_warnings[previous_entry.filename]

        unique_entries.sort(
            key=lambda entry: (
                str(entry.display_name).casefold(),
                str(entry.filename).casefold(),
            )
        )
        self.profile_entries[scope] = unique_entries
        self.profile_entries_loaded[scope] = True
        self.saved_profile_failure_signatures[scope] = current_failure_signatures
        self.profile_scan_conflicts[scope] = duplicate_warnings
        self.profile_document_reload_failed[scope] = False

        all_warnings = [*migration_warnings, *load_failures, *duplicate_warnings.values()]
        if all_warnings:
            preview = " | ".join(all_warnings[:3])
            if len(all_warnings) > 3:
                preview = f"{preview} | ...and {len(all_warnings) - 3} more."
            self.saved_profile_scan_warnings[scope] = (
                f"Some {self.profile_scope_badge(scope).title()} profile files need attention: {preview}"
            )
        else:
            self.saved_profile_scan_warnings[scope] = ""

        matching_entry = next(
            (entry for entry in unique_entries if entry.identity == previous_identity),
            None,
        )
        if matching_entry is not None:
            if previous_fingerprint and matching_entry.fingerprint != previous_fingerprint:
                self.clear_profile_confirmation_state()
            self.set_selected_profile_key(scope, matching_entry.key)
            self.profile_selection_cleared_due_to_disappearance[scope] = False
        elif previous_identity is not None:
            self.clear_profile_confirmation_state()
            self.set_selected_profile_key(scope, "")
            self.profile_selection_cleared_due_to_disappearance[scope] = True
        elif unique_entries and not self.profile_selection_cleared_due_to_disappearance[scope]:
            self.set_selected_profile_key(scope, unique_entries[0].key)
        else:
            self.set_selected_profile_key(scope, "")
        return True

    def set_saved_profile_feedback(
        self,
        scope: str,
        *,
        warning: str = "",
        notice: str = "",
    ) -> None:
        self.saved_profile_warnings[scope] = str(warning or "").strip()
        self.saved_profile_notices[scope] = str(notice or "").strip()

    def persist_profile_wrapper(
        self,
        scope: str,
        profile_key: str,
        wrapper: dict[str, object],
        *,
        filename: str,
        preserve_wrapper: bool = False,
        refresh_after: bool = True,
        require_existing: bool = False,
        expected_existing_fingerprint: str = "",
    ) -> ProfileSummary:
        """Save one standalone file through JsonFactory and verify its exact identity."""

        safe_filename = self.validate_profile_filename(filename)
        safe_profile_id = str(profile_key or "").strip()
        if not is_valid_profile_id(safe_profile_id):
            raise ValueError("The saved profile identity is invalid.")
        if not preserve_wrapper:
            expected_wrapper = self.normalize_shared_profile_wrapper(
                wrapper,
                require_profile_id=True,
            )
            if str(expected_wrapper.get("profile_id", "") or "").strip() != safe_profile_id:
                raise ValueError("The saved profile identity does not match its destination.")
            wrapper_to_write = expected_wrapper
        else:
            wrapper_to_write = wrapper
            expected_wrapper = self.normalize_shared_profile_wrapper(
                wrapper_to_write,
                require_profile_id=True,
            )
            if str(expected_wrapper.get("profile_id", "") or "").strip() != safe_profile_id:
                raise ValueError("The saved profile identity does not match its destination.")

        profile_path = self.profile_file_path(scope, safe_filename)
        path_exists = os.path.lexists(profile_path)
        if path_exists and not self.is_profile_file_present(scope, safe_filename):
            raise OSError("The selected profile path is not a regular profile file.")
        if require_existing and not path_exists:
            raise FileNotFoundError("The selected profile file disappeared; no file was recreated.")
        if not require_existing and path_exists:
            raise FileExistsError(f"The profile filename {safe_filename!r} is already in use; no file was overwritten.")
        doc = self.profile_file_doc(scope, safe_filename)
        if require_existing:
            if not doc.reload() or not self.is_profile_file_present(scope, safe_filename):
                raise FileNotFoundError("The selected profile file disappeared; no file was recreated.")
            existing = self.load_profile_summary_from_key(
                scope,
                safe_profile_id,
                doc.get_json("", None),
                filename=safe_filename,
            )
            if expected_existing_fingerprint and existing.fingerprint != expected_existing_fingerprint:
                raise RuntimeError("The selected profile changed elsewhere. Review it and confirm the action again.")
        doc.set_json("", wrapper_to_write)
        if not doc.save():
            doc.reload()
            raise OSError(f"Merchant Rules could not save {self.profile_scope_label(scope)}.")
        if not doc.reload():
            raise OSError(
                f"The change was saved, but Merchant Rules could not verify " f"{self.profile_scope_label(scope)}."
            )
        if not self.is_profile_file_present(scope, safe_filename):
            raise OSError("The profile file could not be found after saving.")
        verified = self.load_profile_summary_from_key(
            scope,
            safe_profile_id,
            doc.get_json("", None),
            filename=safe_filename,
        )
        expected = self.load_profile_summary_from_key(
            scope,
            safe_profile_id,
            expected_wrapper,
            filename=safe_filename,
        )
        if (
            verified.fingerprint != expected.fingerprint
            or verified.serialized_payload != expected.serialized_payload
            or verified.display_name != expected.display_name
        ):
            raise RuntimeError(
                f"Merchant Rules could not verify the saved {self.profile_scope_badge(scope).title()} profile."
            )
        self.profile_document_reload_failed[scope] = False
        self.profile_known_filenames[scope].add(safe_filename)
        if refresh_after:
            self.refresh_profile_entries(scope)
        return verified

    def resolve_profile_for_action(
        self,
        identity: ProfileIdentity,
        *,
        expected_fingerprint: str = "",
        reload_shared: bool = True,
    ) -> ProfileSummary:
        """Re-resolve an exact key and reject stale confirmed shared actions."""

        if identity.scope not in PROFILE_SCOPES:
            raise RuntimeError("The selected profile scope is invalid.")
        refresh_succeeded = self.refresh_profile_entries(
            identity.scope,
            reload_document=(reload_shared or identity.scope == PROFILE_SCOPE_ACCOUNT),
        )
        if not refresh_succeeded:
            raise OSError(
                f"{self.profile_scope_label(identity.scope)} could not be refreshed, so no changes were made."
            )

        current = self.get_profile_by_identity(identity)
        if current is None:
            raise RuntimeError("The selected profile changed or disappeared; review the refreshed list.")
        if not current.filename or not self.is_profile_file_present(identity.scope, current.filename):
            self.clear_profile_confirmation_state()
            raise RuntimeError("The selected profile file disappeared; review the refreshed list.")
        if expected_fingerprint and current.fingerprint != expected_fingerprint:
            self.clear_profile_confirmation_state()
            raise RuntimeError("The selected profile changed elsewhere. Review it and confirm the action again.")
        if identity.scope == PROFILE_SCOPE_SHARED and not expected_fingerprint:
            raise RuntimeError("Select the Shared profile again, then confirm the action.")
        return current

    def prepare_scope_for_new_profile(self, scope: str) -> None:
        refreshed = self.refresh_profile_entries(
            scope,
            reload_document=True,
        )
        if not refreshed:
            raise OSError(f"{self.profile_scope_label(scope)} could not be refreshed, so no changes were made.")

    def save_current_as_new_profile(self, scope: str) -> None:
        requested_profile_name = self.profile_name_inputs[scope]
        try:
            self.prepare_scope_for_new_profile(scope)
            profile_name = self.ensure_profile_name_available(
                scope,
                requested_profile_name,
            )
            profile_id = new_profile_id()
            filename = self.allocate_profile_filename(scope, profile_name)
            wrapper = self.build_shared_profile_wrapper(
                profile_name,
                profile_id=profile_id,
            )
            self.persist_profile_wrapper(
                scope,
                profile_id,
                wrapper,
                filename=filename,
            )
            self.select_profile_after_action(scope, profile_id)
            self.clear_profile_confirmation_state()
            self.set_saved_profile_feedback(
                scope,
                notice=(f"Saved {self.profile_scope_badge(scope).title()} profile " f"'{profile_name}'."),
            )
        except Exception as exc:
            self.set_saved_profile_feedback(
                scope,
                warning=(f"Failed to save {self.profile_scope_badge(scope).title()} profile: {exc}"),
            )

    def create_blank_saved_profile(
        self,
        scope: str,
        display_name: str,
        *,
        refresh_scope: bool = True,
    ) -> ProfileSummary:
        if scope not in PROFILE_SCOPES:
            raise ValueError("The saved profile scope is invalid.")
        if refresh_scope:
            self.prepare_scope_for_new_profile(scope)
        profile_name = self.ensure_profile_name_available(scope, display_name)
        profile_id = new_profile_id()
        filename = self.allocate_profile_filename(scope, profile_name)
        wrapper = self.build_shared_profile_wrapper(
            profile_name,
            profile_id=profile_id,
            payload=self._default_payload(),
        )
        profile = self.persist_profile_wrapper(
            scope,
            profile_id,
            wrapper,
            filename=filename,
        )
        self.select_profile_after_action(scope, profile_id)
        self.clear_profile_confirmation_state()
        return profile

    def create_blank_profile(self, scope: str) -> None:
        requested_profile_name = self.profile_name_inputs[scope]
        try:
            profile = self.create_blank_saved_profile(scope, requested_profile_name)
            self.set_saved_profile_feedback(
                scope,
                notice=(
                    f"Created blank {self.profile_scope_badge(scope).title()} profile " f"'{profile.display_name}'."
                ),
            )
        except Exception as exc:
            self.set_saved_profile_feedback(
                scope,
                warning=(f"Failed to create blank {self.profile_scope_badge(scope).title()} profile: {exc}"),
            )

    def rename_selected_profile(
        self,
        scope: str,
        expected_fingerprint: str = "",
    ) -> None:
        selected_profile = self.get_selected_profile(scope)
        if selected_profile is None:
            self.set_saved_profile_feedback(
                scope,
                warning=f"Select a {self.profile_scope_badge(scope).title()} profile to rename.",
            )
            return

        requested_profile_name = self.profile_name_inputs[scope]
        try:
            current = self.resolve_profile_for_action(
                selected_profile.identity,
                expected_fingerprint=expected_fingerprint,
                reload_shared=True,
            )
            new_name = self.ensure_profile_name_available(
                scope,
                requested_profile_name,
                exclude_key=current.key,
            )
            wrapper = self._store.rename_profile_wrapper(
                current.raw_wrapper,
                profile_id=current.key,
                display_name=new_name,
                fallback_payload=current.payload,
            )
            self.persist_profile_wrapper(
                scope,
                current.key,
                wrapper,
                filename=current.filename,
                preserve_wrapper=True,
                require_existing=True,
                expected_existing_fingerprint=current.fingerprint,
            )
            self.select_profile_after_action(scope, current.key)
            self.profile_name_inputs[scope] = new_name
            self.profile_name_input_dirty[scope] = False
            self.clear_profile_confirmation_state()
            self.set_saved_profile_feedback(
                scope,
                notice=(
                    f"Renamed {self.profile_scope_badge(scope).title()} profile "
                    f"'{current.display_name}' to '{new_name}'."
                ),
            )
        except Exception as exc:
            self.set_saved_profile_feedback(
                scope,
                warning=(f"Failed to rename {self.profile_scope_badge(scope).title()} profile: {exc}"),
            )

    def save_current_over_selected_profile(
        self,
        scope: str,
        expected_fingerprint: str = "",
    ) -> None:
        selected_profile = self.get_selected_profile(scope)
        if selected_profile is None:
            self.set_saved_profile_feedback(
                scope,
                warning=f"Select a {self.profile_scope_badge(scope).title()} profile to replace.",
            )
            return

        try:
            current = self.resolve_profile_for_action(
                selected_profile.identity,
                expected_fingerprint=expected_fingerprint,
                reload_shared=True,
            )
            wrapper = self.build_shared_profile_wrapper(
                current.display_name,
                profile_id=current.key,
            )
            self.persist_profile_wrapper(
                scope,
                current.key,
                wrapper,
                filename=current.filename,
                require_existing=True,
                expected_existing_fingerprint=current.fingerprint,
            )
            self.select_profile_after_action(scope, current.key)
            self.clear_profile_confirmation_state()
            self.set_saved_profile_feedback(
                scope,
                notice=(
                    f"Replaced {self.profile_scope_badge(scope).title()} profile "
                    f"'{current.display_name}' with the current settings."
                ),
            )
        except Exception as exc:
            self.set_saved_profile_feedback(
                scope,
                warning=(f"Failed to replace {self.profile_scope_badge(scope).title()} profile: {exc}"),
            )

    def copy_selected_profile_to_other_scope(
        self,
        source_scope: str,
        expected_fingerprint: str = "",
    ) -> None:
        source = self.get_selected_profile(source_scope)
        destination_scope = PROFILE_SCOPE_ACCOUNT if source_scope == PROFILE_SCOPE_SHARED else PROFILE_SCOPE_SHARED
        if source is None:
            self.set_saved_profile_feedback(
                source_scope,
                warning=f"Select a {self.profile_scope_badge(source_scope).title()} profile to copy.",
            )
            return

        try:
            current = self.resolve_profile_for_action(
                source.identity,
                expected_fingerprint=expected_fingerprint,
                reload_shared=True,
            )
            self.prepare_scope_for_new_profile(destination_scope)
            destination_name = self.ensure_profile_name_available(
                destination_scope,
                current.display_name,
            )
            destination_key = new_profile_id()
            destination_filename = self.allocate_profile_filename(
                destination_scope,
                destination_name,
            )
            destination_wrapper = self.build_shared_profile_wrapper(
                destination_name,
                profile_id=destination_key,
                payload=current.payload,
                saved_at_unix_ms=current.saved_at_unix_ms,
                saved_at_label=current.saved_at_label,
            )
            copied = self.persist_profile_wrapper(
                destination_scope,
                destination_key,
                destination_wrapper,
                filename=destination_filename,
            )
            self.select_profile_after_action(
                destination_scope,
                copied.key,
                activate_scope=True,
            )
            self.clear_profile_confirmation_state()
            self.set_saved_profile_feedback(
                destination_scope,
                notice=(
                    f"Copied '{current.display_name}' to "
                    f"{self.profile_scope_badge(destination_scope).title()} profiles."
                ),
            )
            self.set_saved_profile_feedback(
                source_scope,
                notice=(
                    f"The original {self.profile_scope_badge(source_scope).title()} profile "
                    f"'{current.display_name}' was not changed."
                ),
            )
        except Exception as exc:
            self.set_saved_profile_feedback(
                source_scope,
                warning=(f"Failed to copy {self.profile_scope_badge(source_scope).title()} profile: {exc}"),
            )

    def reset_account(self) -> None:
        self.profile_entries[PROFILE_SCOPE_ACCOUNT] = []
        self.profile_entries_loaded[PROFILE_SCOPE_ACCOUNT] = False
        self.profile_selection_cleared_due_to_disappearance[PROFILE_SCOPE_ACCOUNT] = False
        self.profile_known_filenames[PROFILE_SCOPE_ACCOUNT].clear()
        self.profile_scan_conflicts[PROFILE_SCOPE_ACCOUNT].clear()
        self.saved_profile_failure_signatures[PROFILE_SCOPE_ACCOUNT].clear()
        self.profile_selected_identities[PROFILE_SCOPE_ACCOUNT] = None
        self.profile_name_inputs[PROFILE_SCOPE_ACCOUNT] = ""
        self.profile_name_input_dirty[PROFILE_SCOPE_ACCOUNT] = False


LiveProfileLogLevel = Literal["Info", "Warning", "Error"]


class LiveProfileRuntime(Protocol):

    @property
    def account_key(self) -> str:
        raise NotImplementedError

    @property
    def initialized(self) -> bool:
        raise NotImplementedError

    @property
    def active_workspace(self) -> str:
        raise NotImplementedError

    @active_workspace.setter
    def active_workspace(self, value: str) -> None:
        raise NotImplementedError

    @property
    def active_rules_workspace(self) -> str:
        raise NotImplementedError

    @active_rules_workspace.setter
    def active_rules_workspace(self, value: str) -> None:
        raise NotImplementedError

    @property
    def status_message(self) -> str:
        raise NotImplementedError

    @status_message.setter
    def status_message(self, value: str) -> None:
        raise NotImplementedError

    def get_account_key(self) -> str:
        raise NotImplementedError

    def get_current_character_observation(self) -> tuple[str, str] | None:
        raise NotImplementedError

    def get_profile_application_block_message(
        self,
        action: str,
        *,
        include_remote_dispatch: bool = True,
        include_pending_reload: bool = True,
    ) -> str:
        raise NotImplementedError

    def merchant_rules_has_pending_or_active_work(
        self,
        *,
        include_remote_dispatch: bool = True,
        include_pending_reload: bool = True,
    ) -> bool:
        raise NotImplementedError

    def merchant_rules_lifecycle_block_reason(
        self,
        *,
        require_service: bool = False,
        require_character_profile: bool = True,
    ) -> str:
        raise NotImplementedError

    def ensure_initialized(self) -> None:
        raise NotImplementedError

    def reset_runtime_after_profile_load(
        self,
        *,
        status_message: str = "",
        profile_display_name: str = "",
        log_profile_load_summary: bool = True,
    ) -> None:
        raise NotImplementedError

    def write_profile_payload_for_account(
        self,
        account_key: str,
        payload: dict[str, object],
    ) -> str:
        raise NotImplementedError

    def merchant_rules_is_generation_current(self, generation: int | None = None) -> bool:
        raise NotImplementedError

    def debug_log(self, message: str) -> None:
        raise NotImplementedError

    def log_profile_loaded_summary(self) -> None:
        raise NotImplementedError

    def clear_multibox_batch_runtime(self) -> None:
        raise NotImplementedError

    def clear_unresolved_preview(self) -> None:
        raise NotImplementedError

    def advance_profile_generation(self) -> None:
        raise NotImplementedError

    def publish_configuration_rescans(self) -> None:
        raise NotImplementedError

    def capture_log(self) -> Callable[[str, LiveProfileLogLevel], None]:
        raise NotImplementedError


class LiveDefaultProfilePayloadFactory(Protocol):
    def __call__(self, *, include_rule_templates: bool) -> dict[str, object]:
        raise NotImplementedError


class LiveProfileConfiguration(Protocol):

    @property
    def build_profile_payload(self) -> Callable[[], dict[str, object]]:
        raise NotImplementedError

    @property
    def build_default_profile_payload(self) -> LiveDefaultProfilePayloadFactory:
        raise NotImplementedError

    @property
    def normalize_profile_payload(self) -> Callable[[object], dict[str, object]]:
        raise NotImplementedError

    @property
    def apply_profile_payload(self) -> Callable[[dict[str, object]], None]:
        raise NotImplementedError


@dataclass(frozen=True)
class LiveProfileBindings:
    factory_type: Callable[[], type[JsonFactory]]
    profile_store: Callable[[], ProfileStore]
    saved_session: Callable[[], SavedProfileSession]
    safe_int: Callable[[], Callable[[object, int], int]]
    profile_version: Callable[[], int]
    confirmation_ticks: Callable[[], int]
    retry_interval: Callable[[], float]
    wall_time: Callable[[], float]
    monotonic: Callable[[], float]
    workspace_rules: Callable[[], str]
    workspace_overview: Callable[[], str]
    rules_workspace_buy: Callable[[], str]
    live_doc_name: Callable[[], str]
    backup_doc_name: Callable[[], str]
    loaded_doc_name: Callable[[], str]
    character_doc_name: Callable[[], str]
    character_schema: Callable[[], str]
    character_schema_version: Callable[[], int]
    association_type: Callable[[], type[CharacterProfileAssociation]]
    provenance_type: Callable[[], type[LoadedProfileProvenance]]
    normalize_character_root: Callable[[], Callable[[object], dict[str, object]]]
    association_from_json: Callable[[], Callable[[object], CharacterProfileAssociation]]
    association_to_json: Callable[[], Callable[[CharacterProfileAssociation], dict[str, object]]]
    copy_payload: Callable[[], Callable[[dict[str, object]], dict[str, object]]]
    path_lexists: Callable[[], Callable[[str], bool]]
    path_basename: Callable[[], Callable[[str], str]]
    path_splitext: Callable[[], Callable[[str], tuple[str, str]]]


class LiveProfileSession:
    config_path: str
    active_profile_display_name: str
    loaded_profile_provenance: LoadedProfileProvenance | None
    loaded_profile_provenance_warning: str
    character_profile_ready: bool
    character_profile_resolved_identity: tuple[str, str] | None
    character_profile_resolved_observation: tuple[str, str] | None
    character_profile_resolved_profile_identity: ProfileIdentity | None
    character_profile_candidate_identity: tuple[str, str] | None
    character_profile_candidate_observation: tuple[str, str] | None
    character_profile_candidate_ticks: int
    character_profile_resolution_target: tuple[str, str] | None
    character_profile_pending_association: CharacterProfileAssociation | None
    character_profile_pending_profile: ProfileSummary | None
    character_profile_pending_needs_persist: bool
    character_profile_pending_is_new_blank: bool
    character_profile_pending_message: str
    character_profile_last_attempt_at: float
    character_profile_resolution_error: str
    character_profile_last_failure_signature: tuple[str, str, str] | None
    character_profile_resolution_started: bool
    new_profile_session: bool
    profile_warning: str
    profile_notice: str
    profile_write_blocked: bool

    def __init__(
        self,
        *,
        runtime: LiveProfileRuntime,
        configuration: LiveProfileConfiguration,
        bindings: LiveProfileBindings,
    ) -> None:
        self._runtime = runtime
        self._configuration = configuration
        self._bindings = bindings

    @property
    def _profile_store(self) -> ProfileStore:
        return self._bindings.profile_store()

    @property
    def _saved_profile_session(self) -> SavedProfileSession:
        return self._bindings.saved_session()

    def live_config_doc(self) -> JsonFactory:
        """The current account's live working config (account-scoped, self-persisting)."""
        return self._bindings.factory_type()(self._bindings.live_doc_name())

    def backup_doc(self) -> JsonFactory:
        """Account-scoped last-known-good live profile used by the Restore Backup action."""
        return self._bindings.factory_type()(self._bindings.backup_doc_name())

    def loaded_profile_state_doc(self) -> JsonFactory:
        """Account-scoped provenance for the exact saved profile last loaded explicitly."""
        return self._bindings.factory_type()(self._bindings.loaded_doc_name())

    def character_profile_state_doc(self) -> JsonFactory:
        """Account-scoped character-to-profile associations, separate from load provenance."""
        return self._bindings.factory_type()(self._bindings.character_doc_name(), "account")

    def get_live_profile_display_name(self) -> str:
        config_path = str(self.config_path or "").strip()
        if config_path:
            profile_name = self._bindings.path_splitext()(self._bindings.path_basename()(config_path))[0].strip()
            if profile_name:
                return profile_name
        account_key = str(self._runtime.account_key or '').strip()
        return account_key or "default"

    def mark_character_profile_unresolved(self, message: str = "") -> None:
        self.character_profile_ready = False
        self._runtime.clear_unresolved_preview()
        self._clear_profile_confirmation_state()
        status = str(message or "").strip()
        if not status:
            status = "Waiting for this character to finish loading."
        self._runtime.status_message = status

    def read_character_profile_state_root(self, doc: JsonFactory) -> dict[str, object] | None:
        if not doc.is_ready():
            raise OSError("The account-scoped character profile state is not ready.")
        if not doc.reload():
            try:
                document_path = str(doc.path() or "").strip()
                if not document_path:
                    raise OSError("The character profile state path is not available.")
                if not self._bindings.path_lexists()(document_path):
                    return None
            except Exception as exc:
                raise OSError("The character profile state path could not be checked.") from exc
            raise OSError("The character profile state could not be refreshed.")
        raw_state = doc.get_json("", None)
        if raw_state is None:
            if doc.has(""):
                raise ValueError("The character profile state root is malformed.")
            return None
        if raw_state == {}:
            return {}
        return self._bindings.normalize_character_root()(raw_state)

    def read_character_profile_association_state(
        self,
        character_uuid_key: str,
    ) -> tuple[CharacterProfileAssociation | None, bool]:
        doc = self.character_profile_state_doc()
        root = self.read_character_profile_state_root(doc)
        if root is None or root == {}:
            return None, False
        characters = root.get("characters", {})
        if not isinstance(characters, dict):
            raise ValueError("The character profile state entries are malformed.")
        if character_uuid_key not in characters:
            return None, False
        try:
            return self._bindings.association_from_json()(characters[character_uuid_key]), False
        except Exception as exc:
            self._runtime.capture_log()(
                (
                    "The current character's saved profile association is malformed; "
                    f"it will be removed after safe blank settings are verified. Technical detail: {exc}"
                ),
                'Warning',
            )
            return None, True

    def load_character_profile_association(
        self,
        character_uuid_key: str,
    ) -> CharacterProfileAssociation | None:
        association, _malformed = self.read_character_profile_association_state(character_uuid_key)
        return association

    def persist_character_profile_association(
        self,
        character_uuid_key: str,
        association: CharacterProfileAssociation,
    ) -> None:
        doc = self.character_profile_state_doc()
        root = self.read_character_profile_state_root(doc)
        if root not in (None, {}):
            self._bindings.normalize_character_root()(root)
        serialized_entry = self._bindings.association_to_json()(association)
        if not doc.has("schema"):
            doc.set_str("schema", self._bindings.character_schema())
        if not doc.has("schema_version"):
            doc.set_int("schema_version", self._bindings.character_schema_version())
        doc.set_json(f"characters/{character_uuid_key}", serialized_entry)
        if not doc.save():
            doc.reload()
            raise OSError("JsonFactory could not flush the character profile association.")
        if not doc.reload():
            raise OSError("The character profile association was saved but could not be reloaded.")
        verified_root = doc.get_json("", None)
        normalized_root = self._bindings.normalize_character_root()(verified_root)
        verified_characters = normalized_root.get("characters", {})
        if not isinstance(verified_characters, dict):
            raise RuntimeError("The saved character profile state entries are malformed.")
        verified_association = self._bindings.association_from_json()(verified_characters.get(character_uuid_key))
        expected_association = self._bindings.association_from_json()(serialized_entry)
        if verified_association != expected_association:
            raise RuntimeError("The character profile association failed post-save verification.")

    def delete_character_profile_association(self, character_uuid_key: str) -> None:
        """Remove a stale current-character leaf after its safe replacement is live."""

        doc = self.character_profile_state_doc()
        root = self.read_character_profile_state_root(doc)
        if root is None or root == {}:
            return
        characters = root.get("characters", {})
        if not isinstance(characters, dict):
            raise ValueError("The character profile state entries are malformed.")
        if character_uuid_key not in characters:
            return

        expected_root = self._bindings.copy_payload()(root)
        expected_characters = expected_root.get("characters", {})
        if not isinstance(expected_characters, dict):
            raise ValueError("The character profile state entries are malformed.")
        expected_characters.pop(character_uuid_key, None)

        if not doc.delete(f"characters/{character_uuid_key}"):
            raise OSError("The stale character profile association could not be removed.")
        if not doc.save():
            doc.reload()
            raise OSError("JsonFactory could not flush the removed character profile association.")
        if not doc.reload():
            raise OSError("The removed character profile association could not be reloaded.")

        verified_raw = doc.get_json("", None)
        if verified_raw is None:
            raise RuntimeError("The character profile state disappeared while removing a stale association.")
        verified_root = self._bindings.normalize_character_root()(verified_raw)
        verified_characters = verified_root.get("characters", {})
        if not isinstance(verified_characters, dict):
            raise RuntimeError("The saved character profile state entries are malformed.")
        if character_uuid_key in verified_characters:
            raise RuntimeError("The stale character profile association remained after removal.")
        if verified_root != expected_root:
            raise RuntimeError("Unrelated character profile state changed while removing a stale association.")

    def refresh_character_profile_scope(self, scope: str) -> None:
        if not self._refresh_profile_entries(scope, reload_document=True):
            raise OSError(f"{self._profile_scope_label(scope)} could not be refreshed.")
        if (
            self._saved_profile_session.profile_document_reload_failed[scope]
            or self._saved_profile_session.saved_profile_failure_signatures[scope]
            or self._saved_profile_session.profile_scan_conflicts[scope]
            or self._saved_profile_session.saved_profile_scan_warnings[scope]
        ):
            raise OSError(f"Some {self._profile_scope_label(scope)} could not be verified during refresh.")

    def set_character_profile_resolution_failure(self, exc: Exception) -> None:
        self.mark_character_profile_unresolved(
            "Merchant Rules could not finish loading this character's profile. " "Automatic actions are paused."
        )
        failure_text = self._format_exception_chain_for_log(exc)
        target = self.character_profile_resolution_target or self.character_profile_candidate_identity
        target_context = repr((target, self.character_profile_candidate_observation))
        try:
            document_path = str(self.character_profile_state_doc().path() or '').strip() or "<unbound>"
        except Exception:
            document_path = "<unavailable>"
        failure_signature = (target_context, document_path, failure_text)
        self.character_profile_resolution_error = str(exc or type(exc).__name__)
        self.character_profile_last_attempt_at = self._bindings.monotonic()
        if failure_signature != self.character_profile_last_failure_signature:
            self._runtime.capture_log()(
                ("Character profile resolution remains blocked. " f"Technical detail: {failure_text}"),
                'Warning',
            )
            self.character_profile_last_failure_signature = failure_signature

    def retain_profile_load_for_character_retry(
        self,
        profile: ProfileSummary,
        exc: Exception,
    ) -> None:
        resolved_identity = self.character_profile_resolved_identity
        resolved_observation = self.character_profile_resolved_observation
        if resolved_identity is None:
            self.set_character_profile_resolution_failure(exc)
            return
        self.character_profile_resolution_target = resolved_identity
        self.character_profile_pending_association = self._bindings.association_type()(
            profile_identity=profile.identity,
            character_name_snapshot=(resolved_observation[1] if resolved_observation else ""),
        )
        self.character_profile_pending_profile = profile
        self.character_profile_pending_needs_persist = True
        self.character_profile_pending_is_new_blank = False
        self.character_profile_pending_message = (
            f"Loaded {self._profile_scope_badge(profile.scope).title()} profile "
            f"'{profile.display_name}' for this character."
        )
        self.set_character_profile_resolution_failure(exc)

    def clear_character_profile_pending_target(self) -> None:
        self.character_profile_pending_association = None
        self.character_profile_pending_profile = None
        self.character_profile_pending_needs_persist = False
        self.character_profile_pending_is_new_blank = False
        self.character_profile_pending_message = ""

    def prepare_character_profile_pending_target(
        self,
        character_uuid_key: str,
    ) -> tuple[ProfileSummary | None, CharacterProfileAssociation | None, bool]:
        if self.character_profile_pending_association is not None:
            identity = self.character_profile_pending_association.profile_identity
            if self.character_profile_pending_profile is not None:
                return (
                    self.character_profile_pending_profile,
                    self.character_profile_pending_association,
                    False,
                )
            self.refresh_character_profile_scope(identity.scope)
            profile = self._get_profile_by_identity(identity)
            if profile is not None:
                self.character_profile_pending_profile = profile
                return profile, self.character_profile_pending_association, False
            self.character_profile_pending_association = None

        association, malformed = self.read_character_profile_association_state(character_uuid_key)
        if association is None:
            self.character_profile_pending_association = None
            self.character_profile_pending_profile = None
            self.character_profile_pending_needs_persist = False
            self.character_profile_pending_is_new_blank = False
            self.character_profile_pending_message = (
                "This character has no saved profile assigned; using safe blank settings."
                if not malformed
                else "This character's saved profile association was stale; using safe blank settings."
            )
            return None, None, malformed

        identity = association.profile_identity
        self.refresh_character_profile_scope(identity.scope)
        profile = self._get_profile_by_identity(identity)
        if profile is not None:
            self.character_profile_pending_association = association
            self.character_profile_pending_profile = profile
            self.character_profile_pending_needs_persist = False
            self.character_profile_pending_is_new_blank = False
            return profile, association, False

        self.character_profile_pending_association = None
        self.character_profile_pending_profile = None
        self.character_profile_pending_needs_persist = False
        self.character_profile_pending_is_new_blank = False
        self.character_profile_pending_message = (
            "This character's saved profile could not be found; using safe blank settings."
        )
        return None, None, True

    def apply_verified_profile_payload(
        self,
        payload: dict[str, object],
        *,
        expected_serialized_payload: str,
        operation_description: str = "the verified profile payload",
        status_message: str = "",
        preserve_workspace_state: bool = True,
        profile_display_name: str = "",
        log_profile_load_summary: bool = False,
        include_remote_dispatch: bool = True,
        include_pending_reload: bool = True,
    ) -> None:
        normalized_payload = self._configuration.normalize_profile_payload(self._bindings.copy_payload()(payload))
        live_doc = self.live_config_doc()
        self._runtime.write_profile_payload_for_account(self._runtime.account_key, normalized_payload)
        if not live_doc.save():
            rollback_loaded = live_doc.reload()
            rollback_detail = (
                "" if rollback_loaded else " Merchant Rules also could not restore the previous current settings."
            )
            raise OSError(
                f"Merchant Rules could not save {operation_description} as the current settings." f"{rollback_detail}"
            )
        if not live_doc.reload():
            raise OSError("Merchant Rules could not verify the saved current settings.")
        if not self.reload_profile_from_disk(
            status_message=status_message,
            preserve_workspace_state=preserve_workspace_state,
            log_profile_load_summary=log_profile_load_summary,
            profile_display_name=profile_display_name,
            include_remote_dispatch=include_remote_dispatch,
            include_pending_reload=include_pending_reload,
        ):
            raise OSError(f"Merchant Rules could not apply {operation_description}.")
        loaded_payload_serialized = self._serialize_shareable_profile_payload(self._build_shareable_profile_payload())
        if loaded_payload_serialized != expected_serialized_payload:
            raise RuntimeError(f"The current settings do not match {operation_description} after loading.")

    def apply_saved_profile_summary(
        self,
        profile: ProfileSummary,
        *,
        status_message: str = "",
        preserve_workspace_state: bool = True,
        log_profile_load_summary: bool = False,
        include_remote_dispatch: bool = True,
        include_pending_reload: bool = True,
    ) -> None:
        self.apply_verified_profile_payload(
            profile.payload,
            expected_serialized_payload=profile.serialized_payload,
            operation_description="the selected profile",
            status_message=status_message,
            preserve_workspace_state=preserve_workspace_state,
            profile_display_name=f"[{self._profile_scope_badge(profile.scope)}] {profile.display_name}",
            log_profile_load_summary=log_profile_load_summary,
            include_remote_dispatch=include_remote_dispatch,
            include_pending_reload=include_pending_reload,
        )

    def character_profile_gate_block_reason(self) -> str:
        if self.character_profile_resolution_error:
            return "Merchant Rules could not finish loading this character's profile. " "Automatic actions are paused."
        if not self.character_profile_ready:
            return "Waiting for this character to finish loading."
        resolved_identity = self.character_profile_resolved_identity
        resolved_observation = self.character_profile_resolved_observation
        current_account = self._runtime.get_account_key()
        current_observation = self._runtime.get_current_character_observation()
        if (
            resolved_identity is None
            or resolved_observation is None
            or not current_account
            or resolved_identity[0] != current_account
            or current_observation is None
            or current_observation != resolved_observation
        ):
            return "Waiting for this character to finish loading."
        return ""

    def is_character_profile_observation_current(
        self,
        identity: tuple[str, str],
        observation: tuple[str, str],
    ) -> bool:
        return bool(
            self._runtime.get_account_key() == identity[0]
            and observation[0] == identity[1]
            and self._runtime.get_current_character_observation() == observation
        )

    def advance_character_profile_resolution(self) -> None:
        self.character_profile_resolution_started = True
        lifecycle_reason = self._runtime.merchant_rules_lifecycle_block_reason(
            require_character_profile=False,
        )
        if lifecycle_reason:
            self.character_profile_candidate_identity = None
            self.character_profile_candidate_observation = None
            self.character_profile_candidate_ticks = 0
            self.mark_character_profile_unresolved()
            return

        current_account = self._runtime.get_account_key()
        observation = self._runtime.get_current_character_observation()
        if not current_account or observation is None:
            self.character_profile_candidate_identity = None
            self.character_profile_candidate_observation = None
            self.character_profile_candidate_ticks = 0
            self.mark_character_profile_unresolved()
            return

        identity = (current_account, observation[0])
        if (
            self.character_profile_candidate_identity == identity
            and self.character_profile_candidate_observation == observation
        ):
            self.character_profile_candidate_ticks += 1
        else:
            self.character_profile_candidate_identity = identity
            self.character_profile_candidate_observation = observation
            self.character_profile_candidate_ticks = 1

        if (
            self.character_profile_resolved_identity != identity
            or self.character_profile_resolved_observation != observation
        ):
            self.mark_character_profile_unresolved()

        if self.character_profile_candidate_ticks < self._bindings.confirmation_ticks():
            return

        if identity == self.character_profile_resolved_identity and self.character_profile_resolution_target is None:
            self.character_profile_resolved_observation = observation
            self.character_profile_ready = True
            self.character_profile_resolution_error = ""
            self.character_profile_last_failure_signature = None
            return

        if self.character_profile_resolution_target != identity:
            self._runtime.advance_profile_generation()
            self._runtime.clear_multibox_batch_runtime()
            self.character_profile_resolution_target = identity
            self.clear_character_profile_pending_target()
            self.character_profile_resolution_error = ""
            self.character_profile_last_failure_signature = None
            self.character_profile_last_attempt_at = 0.0
            self.mark_character_profile_unresolved()

        if self._runtime.merchant_rules_has_pending_or_active_work(
            include_remote_dispatch=False,
            include_pending_reload=False,
        ):
            self._runtime.status_message = "Waiting for Merchant Rules to finish current work."
            return

        if not self._runtime.initialized or self._runtime.account_key != current_account:
            self._runtime.status_message = "Waiting for this character to finish loading."
            return

        if self._bindings.monotonic() - self.character_profile_last_attempt_at < self._bindings.retry_interval():
            return

        try:
            profile, association, remove_stale_association = self.prepare_character_profile_pending_target(
                observation[0]
            )
            if profile is None or association is None:
                blank_payload = self._configuration.normalize_profile_payload(
                    self._configuration.build_default_profile_payload(include_rule_templates=False)
                )
                self.apply_verified_profile_payload(
                    blank_payload,
                    expected_serialized_payload=self._serialize_shareable_profile_payload(blank_payload),
                    operation_description="safe blank settings",
                    status_message=(
                        self.character_profile_pending_message
                        or "This character has no saved profile assigned; using safe blank settings."
                    ),
                    preserve_workspace_state=True,
                    profile_display_name="",
                    log_profile_load_summary=False,
                    include_remote_dispatch=False,
                    include_pending_reload=False,
                )
                if not self.is_character_profile_observation_current(identity, observation):
                    raise RuntimeError("The current character changed while safe blank settings were loading.")
                if remove_stale_association:
                    self.delete_character_profile_association(observation[0])
                if not self.is_character_profile_observation_current(identity, observation):
                    raise RuntimeError("The current character changed before its blank settings could be confirmed.")
                resolved_profile_identity = None
            else:
                self.apply_saved_profile_summary(
                    profile,
                    preserve_workspace_state=True,
                    log_profile_load_summary=False,
                    include_remote_dispatch=False,
                    include_pending_reload=False,
                )
                if not self.is_character_profile_observation_current(identity, observation):
                    raise RuntimeError("The current character changed while its saved profile was loading.")
                if self.character_profile_pending_needs_persist:
                    self.persist_character_profile_association(observation[0], association)
                if not self.is_character_profile_observation_current(identity, observation):
                    raise RuntimeError("The current character changed before its profile could be confirmed.")
                resolved_profile_identity = association.profile_identity

            self.character_profile_resolved_identity = identity
            self.character_profile_resolved_observation = observation
            self.character_profile_resolved_profile_identity = resolved_profile_identity
            self.character_profile_ready = True
            self.character_profile_resolution_target = None
            self.character_profile_resolution_error = ""
            self.character_profile_last_failure_signature = None
            self.character_profile_last_attempt_at = 0.0
            if self.character_profile_pending_message:
                self._runtime.status_message = self.character_profile_pending_message
            elif profile is not None:
                self._runtime.status_message = (
                    f"Loaded {self._profile_scope_badge(profile.scope).title()} profile "
                    f"'{profile.display_name}' for this character."
                )
            else:
                self._runtime.status_message = (
                    "This character has no saved profile assigned; using safe blank settings."
                )
            self._runtime.publish_configuration_rescans()
            self.clear_character_profile_pending_target()
        except Exception as exc:
            self.set_character_profile_resolution_failure(exc)

    def load_loaded_profile_provenance(self) -> None:
        self.loaded_profile_provenance = None
        self.loaded_profile_provenance_warning = ""
        try:
            raw_state = self.loaded_profile_state_doc().get_json("", None)
            if raw_state in (None, {}):
                return
            provenance = self._normalize_loaded_profile_provenance(raw_state)
            self.loaded_profile_provenance = provenance
            self.active_profile_display_name = (
                f"[{self._profile_scope_badge(provenance.source_identity.scope)}] "
                f"{provenance.display_name_snapshot}"
            )
        except Exception as exc:
            self.loaded_profile_provenance_warning = (
                "Merchant Rules could not read which profile was last loaded for this account. "
                "The existing record was left unchanged."
            )
            self._runtime.capture_log()(
                f"{self.loaded_profile_provenance_warning} Technical detail: {exc}",
                'Warning',
            )

    def require_loaded_profile_state_writable(self, doc: JsonFactory) -> None:
        raw_state = doc.get_json("", None)
        if raw_state in (None, {}):
            return
        try:
            self._normalize_loaded_profile_provenance(raw_state)
        except Exception as exc:
            raise ValueError(
                "The existing last-loaded profile record is unreadable or was created by a newer "
                "Merchant Rules version, so it was left unchanged."
            ) from exc

    def record_loaded_profile_provenance(self, profile: ProfileSummary) -> None:
        provenance = self._bindings.provenance_type()(
            source_identity=profile.identity,
            display_name_snapshot=profile.display_name,
            normalized_content_fingerprint=self._shareable_profile_content_fingerprint(profile.serialized_payload),
            associated_at_unix_ms=int(self._bindings.wall_time() * 1000),
        )
        doc = self.loaded_profile_state_doc()
        self.require_loaded_profile_state_writable(doc)
        expected_state = self._loaded_profile_provenance_to_json(provenance)
        doc.set_json("", expected_state)
        if not doc.save():
            doc.reload()
            raise OSError("JsonFactory could not flush loaded-profile provenance.")
        if not doc.reload():
            raise OSError("Loaded-profile provenance was saved but could not be reloaded.")
        verified = self._normalize_loaded_profile_provenance(doc.get_json("", None))
        if self._loaded_profile_provenance_to_json(verified) != expected_state:
            raise RuntimeError("Loaded-profile provenance failed post-save verification.")
        self.loaded_profile_provenance = verified
        self.loaded_profile_provenance_warning = ""
        self.active_profile_display_name = f"[{self._profile_scope_badge(profile.scope)}] {profile.display_name}"

    def clear_loaded_profile_provenance(self, reason: str = "") -> bool:
        self.loaded_profile_provenance = None
        self.active_profile_display_name = self.get_live_profile_display_name()
        doc = self.loaded_profile_state_doc()
        try:
            if doc.get_json("", None) in (None, {}):
                self.loaded_profile_provenance_warning = ""
                return True
            self.require_loaded_profile_state_writable(doc)
            doc.set_json("", {})
            if not doc.save():
                doc.reload()
                raise OSError("JsonFactory could not clear loaded-profile provenance.")
            if not doc.reload():
                raise OSError("Loaded-profile provenance was cleared but could not be reloaded.")
            if doc.get_json("", None) not in (None, {}):
                raise RuntimeError("Loaded-profile provenance is still present after clearing it.")
            self.loaded_profile_provenance_warning = ""
            return True
        except Exception as exc:
            reason_suffix = f" after {reason}" if reason else ""
            self.loaded_profile_provenance_warning = (
                f"Merchant Rules could not clear the last-loaded profile record{reason_suffix}. "
                "The existing record was left unchanged."
            )
            self._runtime.capture_log()(
                f"{self.loaded_profile_provenance_warning} Technical detail: {exc}",
                'Warning',
            )
            return False

    def load_selected_profile(
        self,
        scope: str,
        expected_fingerprint: str = "",
    ) -> bool | None:
        if self._runtime.get_profile_application_block_message("loading another profile"):
            return False
        gate_reason = self.character_profile_gate_block_reason()
        if gate_reason:
            self._runtime.status_message = gate_reason
            self._set_saved_profile_feedback(scope, warning=gate_reason)
            return False
        self._runtime.ensure_initialized()
        gate_reason = self.character_profile_gate_block_reason()
        if gate_reason:
            self._runtime.status_message = gate_reason
            self._set_saved_profile_feedback(scope, warning=gate_reason)
            return False
        selected_profile = self._get_selected_profile(scope)
        if selected_profile is None:
            self._set_saved_profile_feedback(
                scope,
                warning=f"Select a {self._profile_scope_badge(scope).title()} profile to load.",
            )
            return

        current: ProfileSummary | None = None
        application_started = False
        try:
            current = self._resolve_profile_for_action(
                selected_profile.identity,
                expected_fingerprint=expected_fingerprint,
                reload_shared=True,
            )
            observation = self._runtime.get_current_character_observation()
            resolved_identity = self.character_profile_resolved_identity
            if observation is None or resolved_identity is None or observation[0] != resolved_identity[1]:
                raise RuntimeError("The current character is still loading.")
            application_started = True
            self.apply_saved_profile_summary(
                current,
                status_message="",
                preserve_workspace_state=True,
                log_profile_load_summary=False,
            )
            if not self.is_character_profile_observation_current(
                resolved_identity,
                observation,
            ):
                raise RuntimeError("The current character changed while the selected profile was loading.")
            association = self._bindings.association_type()(
                profile_identity=current.identity,
                character_name_snapshot=observation[1],
            )
            self.persist_character_profile_association(observation[0], association)
            if not self.is_character_profile_observation_current(
                resolved_identity,
                observation,
            ):
                raise RuntimeError("The current character changed before its profile could be confirmed.")
            self.character_profile_resolved_profile_identity = current.identity
            badge = self._profile_scope_badge(scope)
            provenance_warning = ""
            self.loaded_profile_provenance = None
            self.active_profile_display_name = self.get_live_profile_display_name()
            try:
                self.record_loaded_profile_provenance(current)
            except Exception as provenance_exc:
                clear_succeeded = self.clear_loaded_profile_provenance("a loaded-profile provenance write failure")
                provenance_warning = (
                    "The profile loaded successfully, but Merchant Rules could not update this account's "
                    "record of the last profile loaded."
                )
                if not clear_succeeded:
                    provenance_warning += " The previous last-loaded profile record also could not be cleared."
                self.loaded_profile_provenance_warning = provenance_warning
                self._runtime.capture_log()(
                    f"{provenance_warning} Technical detail: {provenance_exc}",
                    'Warning',
                )
            self._runtime.status_message = (
                f"Loaded {badge.title()} profile '{current.display_name}' for this character."
            )
            self._runtime.log_profile_loaded_summary()
            self._refresh_profile_entries(scope)
            self._select_profile_after_action(scope, current.key)
            self._clear_profile_confirmation_state()
            self._set_saved_profile_feedback(
                scope,
                notice=(
                    f"Loaded {badge.title()} profile '{current.display_name}'. "
                    "Use Sync Rules to Selected when you want followers updated."
                    + (
                        " The account's record of the last profile loaded could not be updated."
                        if provenance_warning
                        else ""
                    )
                ),
            )
        except Exception as exc:
            if application_started and current is not None:
                self.retain_profile_load_for_character_retry(current, exc)
                warning = (
                    "Merchant Rules could not finish loading this character's profile. "
                    f"Automatic actions are paused. The saved profile remains selected for retry: {exc}"
                )
            else:
                warning = f"Failed to load {self._profile_scope_badge(scope).title()} profile: {exc}"
            self._runtime.status_message = warning
            self._set_saved_profile_feedback(scope, warning=warning)

    def get_backup_payload(self) -> dict[str, object] | None:
        return self._profile_store.get_backup_payload(self.backup_doc().get_json("", None))

    def store_backup_payload(
        self,
        payload: dict[str, object],
        *,
        slot: str = "last_known_good",
    ) -> None:
        backup_doc = self.backup_doc()
        backup_root = self._profile_store.build_backup_root(
            backup_doc.get_json("", {}),
            payload,
            slot=slot,
        )
        backup_doc.set_json("", backup_root)

    def write_live_profile_payload(
        self,
        payload: dict[str, object],
        *,
        create_backup: bool = True,
        force_save: bool = False,
    ) -> None:
        raw_version = self._bindings.safe_int()(payload.get("version", 0), 0)
        if raw_version > self._bindings.profile_version():
            raise ValueError(f"Cannot write future Merchant Rules profile version {raw_version}.")
        normalized_payload = self._configuration.normalize_profile_payload(payload)
        live_doc = self.live_config_doc()
        existing = live_doc.get_json("", None)
        if create_backup and existing not in (None, {}):
            if not isinstance(existing, dict):
                raise ValueError("Stored Merchant Rules live config is malformed; refusing to overwrite it.")
            existing_version = self._bindings.safe_int()(existing.get("version", 0), 0)
            if existing_version > self._bindings.profile_version():
                raise ValueError(
                    f"Stored live config version {existing_version} is newer than Merchant Rules "
                    f"version {self._bindings.profile_version()}; refusing to overwrite it."
                )
            self.store_backup_payload(existing)
        live_doc.set_json("", normalized_payload)
        if force_save and not live_doc.save():
            raise OSError("JsonFactory could not flush the Merchant Rules live config")

    def restore_profile_from_backup(self) -> bool:
        """Restore the account-scoped last-known-good JsonFactory profile."""

        if self._runtime.get_profile_application_block_message("restoring the backup"):
            return False

        try:
            normalized_payload = self.get_backup_payload()
        except Exception as exc:
            self.profile_warning = f"Failed to validate Merchant Rules backup: {exc}"
            self._runtime.capture_log()(self.profile_warning, 'Error')
            return False
        if normalized_payload is None:
            self.profile_warning = "No valid Merchant Rules JsonFactory backup was found to restore."
            return False

        try:
            current_payload = self.live_config_doc().get_json("", None)
            if isinstance(current_payload, dict) and current_payload:
                current_version = self._bindings.safe_int()(current_payload.get("version", 0), 0)
                if current_version <= self._bindings.profile_version():
                    try:
                        self.store_backup_payload(current_payload, slot="pre_restore")
                    except Exception:
                        pass
            if not self.backup_doc().save():
                raise OSError("JsonFactory could not flush the Merchant Rules backup document")
            self.write_live_profile_payload(
                normalized_payload,
                create_backup=False,
                force_save=True,
            )
            self.clear_loaded_profile_provenance("Restore Backup")
            self.profile_write_blocked = False
            self.reload_profile_from_disk(
                status_message="Merchant Rules live config restored from the last backup.",
                preserve_workspace_state=True,
            )
            self.profile_warning = ""
            self.profile_notice = "Restored current settings from this account's backup."
            return True
        except Exception as exc:
            self.profile_warning = f"Failed to restore Merchant Rules live config backup: {exc}"
            self._runtime.capture_log()(self.profile_warning, 'Error')
            return False

    def reload_profile_from_disk(
        self,
        *,
        status_message: str = "Merchant Rules live config reloaded from disk.",
        preserve_workspace_state: bool = False,
        preserve_window_geometry: bool | None = None,
        profile_display_name: str = "",
        log_profile_load_summary: bool = True,
        include_remote_dispatch: bool = True,
        include_pending_reload: bool = True,
    ) -> bool:
        """Reload the active profile and optionally preserve workspace state."""

        if self._runtime.get_profile_application_block_message(
            "reloading the active profile",
            include_remote_dispatch=include_remote_dispatch,
            include_pending_reload=include_pending_reload,
        ):
            return False
        if preserve_window_geometry is not None:
            preserve_workspace_state = bool(preserve_window_geometry)
        workspace_snapshot = self._runtime.active_workspace if preserve_workspace_state else ""
        rules_workspace_snapshot = self._runtime.active_rules_workspace if preserve_workspace_state else ""
        self._runtime.ensure_initialized()
        # Pick up any external write (e.g. a multibox leader's cross-account overlay) before reloading.
        self.live_config_doc().reload()
        self.load_profile()
        if preserve_workspace_state:
            self._runtime.active_workspace = workspace_snapshot or self._runtime.active_workspace
            self._runtime.active_rules_workspace = rules_workspace_snapshot or self._runtime.active_rules_workspace
        self._runtime.reset_runtime_after_profile_load(
            status_message=status_message,
            profile_display_name=profile_display_name,
            log_profile_load_summary=log_profile_load_summary,
        )
        return True

    def load_profile(self) -> None:
        """Load the account-scoped JsonFactory profile with fail-closed version safeguards."""

        doc = self.live_config_doc()
        stored_payload = doc.get_json("", None)
        profile_exists = stored_payload not in (None, {})
        self.new_profile_session = not profile_exists
        self.active_profile_display_name = self.get_live_profile_display_name()
        self._runtime.active_workspace = (
            self._bindings.workspace_rules() if self.new_profile_session else self._bindings.workspace_overview()
        )
        self._runtime.active_rules_workspace = self._bindings.rules_workspace_buy()
        self.profile_warning = ""
        self.profile_notice = ""
        self.profile_write_blocked = False

        stored_version = (
            self._bindings.safe_int()(stored_payload.get("version", 0), 0) if isinstance(stored_payload, dict) else 0
        )
        if profile_exists and stored_version > self._bindings.profile_version():
            self.profile_write_blocked = True
            self._runtime.active_workspace = self._bindings.workspace_rules()
            self.profile_warning = (
                f"Live config version {stored_version} is newer than Merchant Rules version {self._bindings.profile_version()}. "
                "The config was not applied and will not be rewritten."
            )
            self._runtime.capture_log()(self.profile_warning, 'Error')
            return

        default_payload = self._configuration.build_default_profile_payload(
            include_rule_templates=profile_exists,
        )
        self._configuration.apply_profile_payload(default_payload)

        if not profile_exists:
            return

        should_save_normalized = False
        allow_normalized_save = True
        raw_version = 0
        normalized_payload: dict[str, object] | None = None
        try:
            raw_payload = doc.get_json("", {})
            raw_version = (
                self._bindings.safe_int()(raw_payload.get("version", 0), 0) if isinstance(raw_payload, dict) else 0
            )
            normalized_payload = self._configuration.normalize_profile_payload(raw_payload)
            should_save_normalized = self._serialize_profile_payload(raw_payload) != self._serialize_profile_payload(
                normalized_payload
            )
            self._configuration.apply_profile_payload(normalized_payload)
        except Exception as exc:
            # Native JSON writes are atomic, so the stored document cannot be half-written;
            # a failure here is a normalization/shape problem. Keep the stored file and fall
            # back to in-memory defaults - no recovery snapshot is needed.
            self.profile_warning = "Live config load failed; using in-memory defaults and preserving the stored file."
            self.profile_write_blocked = True
            self._runtime.active_workspace = self._bindings.workspace_rules()
            self._runtime.capture_log()(f"Failed to load live config {self.config_path}: {exc}", 'Error')
            return

        if raw_version <= 0 and not self.profile_warning:
            self.profile_notice = "Loaded a legacy live config without a version marker."
        elif 0 < raw_version < self._bindings.profile_version() and not self.profile_warning:
            self.profile_notice = "Merchant Rules loaded older settings and updated them to the current format."

        if should_save_normalized and allow_normalized_save and normalized_payload is not None:
            if self.save_profile():
                if raw_version <= 0:
                    self.profile_notice = (
                        f"Legacy live config normalized and saved safely to v{self._bindings.profile_version()}."
                    )
                elif raw_version < self._bindings.profile_version():
                    self.profile_notice = f"Live config migrated from v{raw_version} to v{self._bindings.profile_version()} and saved safely."
                else:
                    self.profile_notice = "Live config normalized and saved safely."

    def save_profile(self) -> bool:
        """Persist through JsonFactory while retaining a last-known-good account backup."""

        if not self._runtime.merchant_rules_is_generation_current():
            self._runtime.debug_log("Skipped a stale Merchant Rules profile save.")
            return False
        payload = self._configuration.build_profile_payload()
        if self.profile_write_blocked:
            self.profile_warning = (
                "Merchant Rules live-config writes are blocked because the stored profile "
                "could not be handled safely."
            )
            return False
        try:
            self.write_live_profile_payload(payload)
            return True
        except Exception as exc:
            self.profile_warning = f"Failed to save Merchant Rules live config safely: {exc}"
            self._runtime.capture_log()(f"Failed to save live config {self.config_path}: {exc}", 'Error')
            return False

    def _profile_scope_label(self, scope: str) -> str:
        return self._saved_profile_session.profile_scope_label(scope)

    def _profile_scope_badge(self, scope: str) -> str:
        return self._saved_profile_session.profile_scope_badge(scope)

    def _refresh_profile_entries(
        self,
        scope: str,
        *,
        reload_document: bool = False,
        report_reload_failure: bool = True,
    ) -> bool:
        return self._saved_profile_session.refresh_profile_entries(
            scope, reload_document=reload_document, report_reload_failure=report_reload_failure
        )

    def _format_exception_chain_for_log(self, exc: Exception) -> str:
        return self._saved_profile_session.format_exception_chain_for_log(exc)

    def _get_profile_by_identity(
        self,
        identity: ProfileIdentity | None,
    ) -> ProfileSummary | None:
        return self._saved_profile_session.get_profile_by_identity(identity)

    def _get_selected_profile(self, scope: str) -> ProfileSummary | None:
        return self._saved_profile_session.get_selected_profile(scope)

    def _resolve_profile_for_action(
        self,
        identity: ProfileIdentity,
        *,
        expected_fingerprint: str = "",
        reload_shared: bool = True,
    ) -> ProfileSummary:
        return self._saved_profile_session.resolve_profile_for_action(
            identity, expected_fingerprint=expected_fingerprint, reload_shared=reload_shared
        )

    def _select_profile_after_action(
        self,
        scope: str,
        profile_key: str,
        *,
        activate_scope: bool = False,
    ) -> None:
        return self._saved_profile_session.select_profile_after_action(
            scope, profile_key, activate_scope=activate_scope
        )

    def _clear_profile_confirmation_state(self) -> None:
        return self._saved_profile_session.clear_profile_confirmation_state()

    def _set_saved_profile_feedback(
        self,
        scope: str,
        *,
        warning: str = "",
        notice: str = "",
    ) -> None:
        return self._saved_profile_session.set_saved_profile_feedback(scope, warning=warning, notice=notice)

    def _serialize_profile_payload(self, payload: dict[str, object]) -> str:
        return self._profile_store.serialize_profile_payload(payload)

    def _serialize_shareable_profile_payload(self, payload: dict[str, object]) -> str:
        return self._profile_store.serialize_profile_payload(payload)

    def _shareable_profile_content_fingerprint(self, serialized_payload: str) -> str:
        return self._profile_store.shareable_profile_content_fingerprint(serialized_payload)

    def _loaded_profile_provenance_to_json(
        self,
        provenance: LoadedProfileProvenance,
    ) -> dict[str, object]:
        return self._profile_store.provenance_to_json(provenance)

    def _normalize_loaded_profile_provenance(
        self,
        raw_state: object,
    ) -> LoadedProfileProvenance:
        return self._profile_store.normalize_provenance(raw_state)

    def _build_shareable_profile_payload(self) -> dict[str, object]:
        return self._configuration.normalize_profile_payload(self._configuration.build_profile_payload())
