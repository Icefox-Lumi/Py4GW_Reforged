from __future__ import annotations

import os
import unicodedata
from typing import TYPE_CHECKING

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
