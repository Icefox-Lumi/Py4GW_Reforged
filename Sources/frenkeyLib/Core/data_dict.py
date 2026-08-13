import json
import msvcrt
import os
import re
import tempfile
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass
from functools import total_ordering
import time
from typing import TYPE_CHECKING, Callable, IO, Mapping, Optional, cast

import PySystem

from Sources.frenkeyLib.Core.json_serializable import JsonSerializableDictionary
from Sources.frenkeyLib.Core.json_serializable import JsonSerializableList
from Sources.frenkeyLib.Core.json_serializable import T_DICT_KEY
from Sources.frenkeyLib.Core.json_serializable import T_SERIALIZABLE_VALUE


_VERSION_PATTERN = re.compile(r'"version"\s*:\s*("([^"\\]|\\.)*"|-?\d+(?:\.\d+)?)')
_VERSION_SCAN_BYTES = 512
_DEFAULT_LOCK_TIMEOUT_SECONDS = 5.0
_DEFAULT_LOCK_POLL_INTERVAL_SECONDS = 0.05
_LOCK_SIZE_BYTES = 1


@total_ordering
@dataclass(frozen=True)
class FileVersion:
    raw: str

    def __post_init__(self) -> None:
        object.__setattr__(self, 'raw', str(self.raw))

    def _parts(self) -> tuple[int | str, ...]:
        parts: list[int | str] = []
        for piece in self.raw.split('.'):
            parts.append(int(piece) if piece.isdigit() else piece)
        return tuple(parts)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, FileVersion):
            return NotImplemented
        return self._parts() < other._parts()

    def __str__(self) -> str:
        return self.raw


class FileLockTimeoutError(TimeoutError):
    def __init__(self, target_path: str, timeout_seconds: float):
        super().__init__(f'Timed out after {timeout_seconds:.2f}s waiting for lock: {target_path}')
        self.target_path = target_path
        self.timeout_seconds = timeout_seconds


class _WindowsFileLock:
    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self._file: Optional[IO[bytes]] = None

    def acquire(
        self,
        *,
        timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds: float = _DEFAULT_LOCK_POLL_INTERVAL_SECONDS,
    ) -> None:
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        directory = os.path.dirname(self.lock_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        while True:
            lock_file = open(self.lock_path, 'a+b')
            try:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, _LOCK_SIZE_BYTES)
                lock_file.seek(0)
                lock_file.truncate()
                lock_file.write(str(os.getpid()).encode('ascii', errors='ignore'))
                lock_file.flush()
                self._file = lock_file
                return
            except OSError:
                lock_file.close()
                if time.monotonic() >= deadline:
                    raise FileLockTimeoutError(self.lock_path, timeout_seconds)
                time.sleep(max(poll_interval_seconds, 0.0))

    def release(self) -> None:
        if self._file is None:
            return

        lock_file = self._file
        self._file = None

        try:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, _LOCK_SIZE_BYTES)
        finally:
            lock_file.close()
            self._cleanup_lock_file()

    def _cleanup_lock_file(self) -> None:
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass
        except OSError:
            # Another client may already be reopening/relocking this file.
            pass

    def __enter__(self) -> '_WindowsFileLock':
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


class _DataFileMixin:
    get_local_path: Callable[..., str]
    get_default_path: Callable[..., str]
    version: FileVersion
    
    last_change : float = time.monotonic()
    _requires_save: bool
    _known_active_path: Optional[str]
    _known_active_mtime_ns: Optional[int]

    if TYPE_CHECKING:
        def clear(self) -> None:
            ...

    def resolve_local_path(self) -> str:
        return self.get_local_path()

    def resolve_default_path(self) -> str:
        return self.get_default_path()

    def resolve_active_path(self) -> str:
        local_path = self.resolve_local_path()
        if os.path.exists(local_path):
            return local_path
        return self.resolve_default_path()

    def resolve_lock_path(self, path: Optional[str] = None) -> str:
        target_path = path or self.resolve_local_path()
        return f'{target_path}.lock'

    def is_locked(self, path: Optional[str] = None) -> bool:
        lock = _WindowsFileLock(self.resolve_lock_path(path))
        try:
            lock.acquire(timeout_seconds=0.0, poll_interval_seconds=0.0)
        except FileLockTimeoutError:
            return True
        else:
            lock.release()
            return False

    def wait_for_unlock(
        self,
        path: Optional[str] = None,
        *,
        timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
        poll_interval_seconds: float = _DEFAULT_LOCK_POLL_INTERVAL_SECONDS,
    ) -> bool:
        lock = _WindowsFileLock(self.resolve_lock_path(path))
        try:
            lock.acquire(
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        except FileLockTimeoutError:
            return False
        else:
            lock.release()
            return True

    @property
    def requires_save(self) -> bool:
        return getattr(self, '_requires_save', False)

    @requires_save.setter
    def requires_save(self, value: bool) -> None:
        self._requires_save = bool(value)

    def _initialize_save_state(self) -> None:
        self._requires_save = False
        self._known_active_path = None
        self._known_active_mtime_ns = None

    def queue_save(self) -> None:
        self.requires_save = True

    def _to_file_payload(self) -> dict:
        raise NotImplementedError

    def _load_path(self, path: str, *, replace: bool, merge_missing: bool = False, update_version: bool = True) -> None:
        raise NotImplementedError

    def _log_load_error(self, message: str) -> None:
        PySystem.Console.Log(self.__class__.__name__, message, PySystem.Console.MessageType.Error)

    def _corrupted_path_for(self, path: str) -> str:
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        return f'{path}.corrupted.{timestamp}'

    def _quarantine_corrupted_file(self, path: str) -> Optional[str]:
        if not path or not os.path.exists(path):
            return None

        corrupted_path = self._corrupted_path_for(path)
        suffix = 1
        while os.path.exists(corrupted_path):
            corrupted_path = f'{self._corrupted_path_for(path)}.{suffix}'
            suffix += 1

        os.replace(path, corrupted_path)
        return corrupted_path

    def _safe_load_path(
        self,
        path: str,
        *,
        replace: bool,
        merge_missing: bool = False,
        update_version: bool = True,
        quarantine_on_failure: bool,
        source_label: str,
    ) -> bool:
        if not path or not os.path.exists(path):
            return False

        try:
            self._load_path(
                path,
                replace=replace,
                merge_missing=merge_missing,
                update_version=update_version,
            )
            return True
        except Exception as exc:
            if quarantine_on_failure:
                corrupted_path = self._quarantine_corrupted_file(path)
                if corrupted_path is not None:
                    self._log_load_error(
                        f'Failed to load {source_label} file "{path}": {exc}. '
                        f'Renamed it to "{corrupted_path}".'
                    )
                else:
                    self._log_load_error(f'Failed to load {source_label} file "{path}": {exc}.')
            else:
                self._log_load_error(
                    f'Failed to load {source_label} file "{path}": {exc}. '
                    'Continuing with empty data.'
                )
            return False

    def refresh_from_disk_if_changed(self) -> bool:
        active_path = self.resolve_active_path()
        if not active_path or not os.path.exists(active_path):
            if self._known_active_path is None and self._known_active_mtime_ns is None:
                return False
            self.load()
            return True

        active_mtime_ns = self._get_file_mtime_ns(active_path)
        if active_path == self._known_active_path and active_mtime_ns == self._known_active_mtime_ns:
            return False

        self.load()
        return True

    def save(
        self,
        path: Optional[str] = None,
        *,
        indent: Optional[int] = 4,
        lock_timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
        lock_poll_interval_seconds: float = _DEFAULT_LOCK_POLL_INTERVAL_SECONDS,
    ) -> None:
        target_path = path or self.resolve_local_path()
        lock = _WindowsFileLock(self.resolve_lock_path(target_path))
        lock.acquire(
            timeout_seconds=lock_timeout_seconds,
            poll_interval_seconds=lock_poll_interval_seconds,
        )
        try:
            self._save_locked(target_path, indent=indent)
        except FileLockTimeoutError:
            return
        finally:
            lock.release()

        self.requires_save = False

    def try_save(
        self,
        path: Optional[str] = None,
        *,
        indent: Optional[int] = 4,
    ) -> bool:
        if not self.requires_save:
            return False
        
        target_path = path or self.resolve_local_path()
        lock = _WindowsFileLock(self.resolve_lock_path(target_path))
        try:
            lock.acquire(timeout_seconds=0.0, poll_interval_seconds=0.0)
        except FileLockTimeoutError:
            return False

        try:
            self._save_locked(target_path, indent=indent)
        except FileLockTimeoutError:
            return False
        finally:
            lock.release()

        self.requires_save = False
        return True

    def _save_locked(self, target_path: str, *, indent: Optional[int] = 4) -> None:
        current_target_mtime_ns = self._get_file_mtime_ns(target_path)
        expected_target_mtime_ns = self._known_active_mtime_ns if self._known_active_path == target_path else None
        if current_target_mtime_ns != expected_target_mtime_ns:
            raise FileLockTimeoutError(target_path, 0.0)

        self._write_payload(target_path, self._to_file_payload(), indent=indent)
        self.last_change = time.monotonic()
        
    def _write_payload(self, target_path: str, payload_data: dict, *, indent: Optional[int] = 4) -> None:
        directory = os.path.dirname(target_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        sanitized_payload = self._remove_none_values(payload_data)
        payload = json.dumps(
            sanitized_payload,
            ensure_ascii=False,
            separators=(',', ':') if indent is None else None,
            indent=indent,
        ).encode('utf-8')
        self._atomic_write_bytes(target_path, payload)
        self._record_known_file_state(target_path)

    @classmethod
    def _remove_none_values(cls, value: object) -> object:
        if isinstance(value, dict):
            return {
                key: cls._remove_none_values(child_value)
                for key, child_value in value.items()
                if child_value is not None
            }

        if isinstance(value, list):
            return [
                cls._remove_none_values(item)
                for item in value
                if item is not None
            ]

        return value

    @staticmethod
    def _atomic_write_bytes(target_path: str, payload: bytes) -> None:
        directory = os.path.dirname(target_path) or '.'
        temp_file: Optional[IO[bytes]] = None
        temp_path = ''

        try:
            temp_file = tempfile.NamedTemporaryFile(
                mode='wb',
                delete=False,
                dir=directory,
                prefix=f'{os.path.basename(target_path)}.',
                suffix='.tmp',
            )
            temp_path = temp_file.name
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_file.close()
            temp_file = None

            os.replace(temp_path, target_path)

            with open(target_path, 'r+b') as target_file:
                os.fsync(target_file.fileno())
        finally:
            if temp_file is not None:
                temp_file.close()
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _get_file_mtime_ns(path: str) -> Optional[int]:
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return None

    def _record_known_file_state(self, path: Optional[str]) -> None:
        self._known_active_path = path
        self._known_active_mtime_ns = self._get_file_mtime_ns(path) if path else None

    def load(self) -> None:
        self.clear()

        default_path = self.resolve_default_path()
        local_path = self.resolve_local_path()
        default_version = self.read_version(default_path)
        local_version = self.read_version(local_path)

        if default_version is not None and (local_version is None or default_version > local_version):
            default_loaded = self._safe_load_path(
                default_path,
                replace=True,
                update_version=True,
                quarantine_on_failure=False,
                source_label='default',
            )
            if default_loaded:
                self._safe_load_path(
                    local_path,
                    replace=False,
                    merge_missing=True,
                    update_version=False,
                    quarantine_on_failure=True,
                    source_label='local',
                )
                self.version = default_version

        elif os.path.exists(local_path):
            local_loaded = self._safe_load_path(
                local_path,
                replace=True,
                update_version=True,
                quarantine_on_failure=True,
                source_label='local',
            )
            if not local_loaded:
                self.clear()
                default_loaded = self._safe_load_path(
                    default_path,
                    replace=True,
                    update_version=True,
                    quarantine_on_failure=False,
                    source_label='default',
                )
                if default_loaded and default_version is not None:
                    self.version = default_version

        else:
            default_loaded = self._safe_load_path(
                default_path,
                replace=True,
                update_version=True,
                quarantine_on_failure=False,
                source_label='default',
            )
            if default_loaded and default_version is not None:
                self.version = default_version

        self._record_known_file_state(self.resolve_active_path())
        self.requires_save = False

    def read_version(self, path: Optional[str] = None) -> Optional[FileVersion]:
        resolved_path = path or self.resolve_active_path()
        if not resolved_path or not os.path.exists(resolved_path):
            return None

        with open(resolved_path, 'rb') as file:
            prefix = file.read(_VERSION_SCAN_BYTES)

        if not prefix:
            return None

        match = _VERSION_PATTERN.search(prefix.decode('utf-8', errors='ignore'))
        if not match:
            return None

        raw_value = match.group(1)
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = raw_value.strip('"')
        return FileVersion(str(parsed))

    def requires_update(self) -> bool:
        default_version = self.read_version(self.resolve_default_path())
        local_version = self.read_version(self.resolve_local_path())

        if default_version is None:
            return False

        if local_version is None:
            return True

        return default_version > local_version


class DataList(_DataFileMixin, JsonSerializableList[T_SERIALIZABLE_VALUE]):
    def __init__(
        self,
        get_local_path: Callable[..., str],
        get_default_path: Callable[..., str],
        data: Optional[list[T_SERIALIZABLE_VALUE]] = None,
        *,
        version: str = '1.0',
        value_type: Optional[type[T_SERIALIZABLE_VALUE]] = None,
        key_decoder: Optional[Callable[[str], T_DICT_KEY]] = None,
        key_encoder: Optional[Callable[[T_DICT_KEY], str]] = None,
    ):
        super().__init__(item_type=value_type, data=data)
        self.get_local_path = get_local_path
        self.get_default_path = get_default_path
        self.version = FileVersion(version)
        self._initialize_save_state()

    def _to_file_payload(self) -> dict:
        return {
            'version': str(self.version),
            'data': [item.to_dict() for item in self],
        }

    def _load_path(self, path: str, *, replace: bool, merge_missing: bool = False, update_version: bool = True) -> None:
        if not path or not os.path.exists(path):
            return

        with open(path, 'r', encoding='utf-8') as file:
            payload = json.load(file)

        file_version = payload.get('version', None)
        if update_version and file_version is not None:
            self.version = FileVersion(str(file_version))

        raw_data = payload.get('data', payload.get('entries', []))
        if isinstance(raw_data, dict):
            raw_data = raw_data.get('data', [])

        if not isinstance(raw_data, list):
            raise TypeError(f'Expected list data in {path}, got {type(raw_data).__name__}')

        typed_raw_data = cast(list[dict], raw_data)
        if replace:
            self.replace_from_dict(typed_raw_data)
        elif merge_missing:
            self.merge_missing_from_dict(typed_raw_data)


class DataDict(
    _DataFileMixin,
    JsonSerializableDictionary[T_DICT_KEY, T_SERIALIZABLE_VALUE],
):
    def __init__(
        self,
        get_local_path: Callable[..., str],
        get_default_path: Callable[..., str],
        data: Optional[dict[T_DICT_KEY, T_SERIALIZABLE_VALUE]] = None,
        *,
        version: str = '1.0',
        value_type: Optional[type[T_SERIALIZABLE_VALUE]] = None,
        key_decoder: Optional[Callable[[str], T_DICT_KEY]] = None,
        key_encoder: Optional[Callable[[T_DICT_KEY], str]] = None,
    ):
        super().__init__(value_type=value_type, data=data, key_decoder=key_decoder, key_encoder=key_encoder)
        self.get_local_path = get_local_path
        self.get_default_path = get_default_path
        self.version = FileVersion(version)
        self._initialize_save_state()

    def _to_file_payload(self) -> dict:
        return {
            'version': str(self.version),
            'data': JsonSerializableDictionary.to_dict(self),
        }

    def _load_path(self, path: str, *, replace: bool, merge_missing: bool = False, update_version: bool = True) -> None:
        if not path or not os.path.exists(path):
            return

        with open(path, 'r', encoding='utf-8') as file:
            payload = json.load(file)

        file_version = payload.get('version', None)
        if update_version and file_version is not None:
            self.version = FileVersion(str(file_version))

        raw_data = payload.get('data', {})
        if not isinstance(raw_data, MappingABC):
            raise TypeError(f'Expected dictionary data in {path}, got {type(raw_data).__name__}')

        typed_raw_data = cast(Mapping[str, dict], raw_data)
        if replace:
            self.replace_from_dict(typed_raw_data)
        elif merge_missing:
            self.merge_missing_from_dict(typed_raw_data)
