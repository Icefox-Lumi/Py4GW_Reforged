from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import md5
from typing import Any, cast


LIVE_CONFIG_DOC_NAME = 'Widgets/MerchantRules/LiveConfig.json'
ACCOUNT_PROFILES_DOC_NAME = 'Widgets/MerchantRules/Profiles.json'
SHARED_PROFILES_DOC_NAME = 'Widgets/MerchantRules/SharedProfiles.json'
BACKUP_DOC_NAME = 'Widgets/MerchantRules/LiveConfigBackup.json'
LOADED_PROFILE_STATE_DOC_NAME = 'Widgets/MerchantRules/LoadedProfileState.json'
BACKUP_SCHEMA = 'merchant_rules_live_config_backup_v1'
BACKUP_SCHEMA_VERSION = 1
SHARED_PROFILE_SCHEMA = 'merchant_rules_shared_profile_v1'
SHARED_PROFILE_SCHEMA_VERSION = 1
LOADED_PROFILE_STATE_SCHEMA = 'merchant_rules_loaded_profile_state_v1'
LOADED_PROFILE_STATE_SCHEMA_VERSION = 1
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


@dataclass
class ProfileSummary:
    """Hold validated saved-profile metadata and its normalized serialized payload."""

    identity: ProfileIdentity
    display_name: str
    saved_at_label: str = ''
    saved_at_unix_ms: int = 0
    payload: dict[str, object] = field(default_factory=dict)
    serialized_payload: str = ''
    fingerprint: str = ''

    @property
    def scope(self) -> str:
        return self.identity.scope

    @property
    def key(self) -> str:
        return self.identity.key


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
        saved_at_unix_ms: int | None = None,
        saved_at_label: str | None = None,
        payload_is_normalized: bool = False,
    ) -> dict[str, object]:
        normalized_name = _normalize_shared_profile_display_name(display_name)
        if not normalized_name:
            raise ValueError('Enter a profile name before saving.')
        effective_saved_at_unix_ms = (
            max(0, _safe_int(saved_at_unix_ms, 0))
            if saved_at_unix_ms is not None
            else int(time.time() * 1000)
        )
        shareable_payload = payload if payload_is_normalized else self._normalize_payload(payload)
        return {
            'schema': SHARED_PROFILE_SCHEMA,
            'schema_version': SHARED_PROFILE_SCHEMA_VERSION,
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
        elif _looks_like_merchant_rules_payload(raw_payload):
            payload_source = raw_payload
            display_name_source = fallback_name
        else:
            raise ValueError('This saved profile uses an unsupported format.') from ValueError(
                f'Saved Merchant Rules profile schema {schema!r} is not supported.'
            )

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

        try:
            normalized_payload = self._normalize_payload(payload_source)
        except Exception as exc:
            raise ValueError('This saved profile is incomplete or damaged.') from exc
        saved_at_unix_ms = max(0, _safe_int(raw_payload.get('saved_at_unix_ms', 0), 0))
        saved_at = str(raw_payload.get('saved_at', '') or '').strip()
        if not saved_at:
            saved_at = _format_shared_profile_timestamp(saved_at_unix_ms)

        return {
            'schema': SHARED_PROFILE_SCHEMA,
            'schema_version': SHARED_PROFILE_SCHEMA_VERSION,
            'name': display_name,
            'saved_at_unix_ms': saved_at_unix_ms,
            'saved_at': saved_at,
            'payload': normalized_payload,
        }

    def load_profile_summary_from_key(
        self,
        scope: str,
        profile_key: str,
        raw_payload: object,
    ) -> ProfileSummary:
        safe_key = str(profile_key)
        normalized_wrapper = self.normalize_shared_profile_wrapper(
            raw_payload,
            fallback_name=safe_key,
        )
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
            identity=ProfileIdentity(scope=scope, key=safe_key),
            display_name=str(normalized_wrapper.get('name', '') or safe_key),
            saved_at_label=saved_at_label,
            saved_at_unix_ms=saved_at_unix_ms,
            payload=payload,
            serialized_payload=_serialize_profile_payload(payload),
            fingerprint=_saved_profile_wrapper_fingerprint(normalized_wrapper),
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
