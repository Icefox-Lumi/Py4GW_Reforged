"""Focused regression for shared whiteboard claim ownership and synchronization."""

from __future__ import annotations

import ast
import ctypes
import gc
import hashlib
import inspect
import os
import subprocess
import sys
import threading
import time
import types
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import replace
from enum import IntEnum
from importlib.util import module_from_spec
from importlib.util import spec_from_file_location
from pathlib import Path
from typing import Any
from typing import Callable
from typing import cast
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
ALL_ACCOUNTS_PATH = ROOT / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src" / "AllAccounts.py"
INTENT_STRUCT_PATH = ROOT / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src" / "IntentStruct.py"
INTENT_SYNC_PATH = ROOT / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src" / "IntentSync.py"
SHARED_MEMORY_PATH = ROOT / "Py4GWCoreLib" / "GlobalCache" / "SharedMemory.py"
BUILD_MGR_PATH = ROOT / "Py4GWCoreLib" / "BuildMgr.py"
WHITEBOARD_LOCKS_PATH = ROOT / "Py4GWCoreLib" / "GlobalCache" / "WhiteboardLocks.py"
WHITEBOARD_ENUMS_PATH = ROOT / "Py4GWCoreLib" / "enums_src" / "Whiteboard_enums.py"
GLOBALS_PATH = ROOT / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src" / "Globals.py"
ISOLATION_PATH = ROOT / "Py4GWCoreLib" / "botting_tree_src" / "isolation.py"

OWNER = "owner@example.com"
OTHER_OWNER = "other@example.com"
SKILL_ID = 123
OTHER_SKILL_ID = 456
TARGET_ID = 789
OTHER_TARGET_ID = 987
GROUP_ID = 4
OTHER_GROUP_ID = 5
SKILL_TARGET_KIND = 1
INTERRUPT_KIND = 11
NOW = 0x1_0000_0100


class _ObservableConsole:
    records: list[tuple[str, str, tuple[object, ...]]] = []

    class MessageType:
        Error = "error"


def _record_console_log(module: str, message: str, *args: object, **_kwargs: object) -> None:
    _ObservableConsole.records.append((module, str(message), args))


def _read_integer_constant(name: str) -> int:
    tree = ast.parse(GLOBALS_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, int):
                return value
    raise ValueError(f"Integer constant {name} not found in {GLOBALS_PATH}")


SHMEM_MAX_EMAIL_LEN = _read_integer_constant("SHMEM_MAX_EMAIL_LEN")
INTENT_COUNT = _read_integer_constant("SHMEM_MAX_INTENTS")


class _Clock:
    value = NOW
    Console = _ObservableConsole

    @staticmethod
    def get_tick_count64() -> int:
        return _Clock.value


class _LiveClock:
    value = NOW
    sequence: list[int] = []
    exception: Exception | None = None
    calls = 0

    @classmethod
    def reset(cls) -> None:
        cls.value = NOW
        cls.sequence = []
        cls.exception = None
        cls.calls = 0

    @classmethod
    def get_uncached_tick_count64(cls) -> int:
        cls.calls += 1
        if cls.exception is not None:
            raise cls.exception
        if cls.sequence:
            return cls.sequence.pop(0)
        return cls.value


class _FakeTiming:
    monotonic_value = 0.0
    advance_clock = True
    advance_live_clock = True
    sleep_calls = 0

    @classmethod
    def reset(cls) -> None:
        cls.monotonic_value = 0.0
        cls.advance_clock = True
        cls.advance_live_clock = True
        cls.sleep_calls = 0

    @classmethod
    def monotonic(cls) -> float:
        return cls.monotonic_value

    @classmethod
    def sleep(cls, seconds: float) -> None:
        cls.sleep_calls += 1
        cls.monotonic_value += seconds
        if cls.advance_clock:
            _Clock.value += max(1, int(seconds * 1000))
        if cls.advance_live_clock:
            _LiveClock.value += max(1, int(seconds * 1000))


@dataclass(frozen=True, slots=True)
class InterruptLockReceipt:
    slot_index: int
    owner_email: str
    kind_id: int
    enemy_skill_id: int
    target_agent_id: int
    isolation_group_id: int
    lock_mode: int
    max_holders: int
    reentry_policy: int
    claim_strength: int
    posted_at_tick64: int
    expires_at_tick64: int


@dataclass(frozen=True, slots=True)
class InterruptClaimResult:
    receipt: InterruptLockReceipt | None
    reason: str


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INTENT_SYNC = _load_module("_py4gw_intent_sync_under_test", INTENT_SYNC_PATH)

_test_kernel32: Any = None
if os.name == "nt":
    from ctypes import wintypes

    _test_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _test_kernel32.CreateEventW.argtypes = (
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    _test_kernel32.CreateEventW.restype = wintypes.HANDLE
    _test_kernel32.OpenEventW.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    _test_kernel32.OpenEventW.restype = wintypes.HANDLE
    _test_kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
    _test_kernel32.SetEvent.restype = wintypes.BOOL
    _test_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _test_kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _test_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _test_kernel32.CloseHandle.restype = wintypes.BOOL

_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0


class _NamedEvent:
    def __init__(self, name: str) -> None:
        if _test_kernel32 is None:
            raise OSError("Named test events require Windows")
        self.name = name
        self.handle = _test_kernel32.CreateEventW(None, True, False, name)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateEventW failed")

    def set(self) -> None:
        if not _test_kernel32.SetEvent(self.handle):
            raise OSError(ctypes.get_last_error(), "SetEvent failed")

    def wait(self, timeout_ms: int = 5000) -> bool:
        return int(_test_kernel32.WaitForSingleObject(self.handle, timeout_ms)) == _WAIT_OBJECT_0

    def close(self) -> None:
        if self.handle:
            _test_kernel32.CloseHandle(self.handle)
            self.handle = None


def _open_named_event(name: str) -> Any:
    if _test_kernel32 is None:
        raise OSError("Named test events require Windows")
    handle = _test_kernel32.OpenEventW(_EVENT_MODIFY_STATE | _SYNCHRONIZE, False, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), f"OpenEventW failed for {name}")
    return handle


def _load_intent_struct() -> type[ctypes.Structure]:
    tree = ast.parse(INTENT_STRUCT_PATH.read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "IntentStruct")
    namespace: dict[str, object] = {
        "Structure": ctypes.Structure,
        "c_wchar": ctypes.c_wchar,
        "c_uint": ctypes.c_uint,
        "c_bool": ctypes.c_bool,
        "SHMEM_MAX_EMAIL_LEN": SHMEM_MAX_EMAIL_LEN,
    }
    isolated = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(isolated)
    exec(compile(isolated, str(INTENT_STRUCT_PATH), "exec"), namespace)
    return cast(type[ctypes.Structure], namespace["IntentStruct"])


INTENT_STRUCT = _load_intent_struct()
INTENT_ARRAY = INTENT_STRUCT * INTENT_COUNT


def _load_whiteboard_enums() -> dict[str, type[IntEnum]]:
    tree = ast.parse(WHITEBOARD_ENUMS_PATH.read_text(encoding="utf-8"))
    nodes = [item for item in tree.body if isinstance(item, ast.ClassDef)]
    namespace: dict[str, object] = {"IntEnum": IntEnum}
    isolated = ast.Module(body=cast(list[ast.stmt], nodes), type_ignores=[])
    ast.fix_missing_locations(isolated)
    exec(compile(isolated, str(WHITEBOARD_ENUMS_PATH), "exec"), namespace)
    return {
        name: cast(type[IntEnum], namespace[name])
        for name in (
            "WhiteboardClaimStrength",
            "WhiteboardLockKind",
            "WhiteboardLockMode",
            "WhiteboardReentryPolicy",
        )
    }


WHITEBOARD_ENUMS = _load_whiteboard_enums()
LOCK_EXCLUSIVE = 1
LOCK_SHARED = 2
REENTRY_OWNER = 1
REENTRY_NONREENTRANT = 2
CLAIM_HARD = 1
CLAIM_SOFT = 2
POLICY_KIND = int(WHITEBOARD_ENUMS["WhiteboardLockKind"].ACCOUNT_ISOLATION_POLICY)
POLICY_TARGET = 0
POLICY_GROUP = 0


class _DummyStruct:
    AccountEmail: str
    IsAccount: bool
    IsolationGroupID: int

    def reset(self) -> None:
        pass


def _load_accounts_class(shared_memory_name: str) -> type[Any]:
    tree = ast.parse(ALL_ACCOUNTS_PATH.read_text(encoding="utf-8"))
    class_node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "AllAccounts")
    method_names = {
        "reset",
        "_find_account_slot_by_email",
        "SetAccountGroupByEmail",
        "_wb_log",
        "_wb_kind_display",
        "_wb_mode_display",
        "_wb_key_display",
        "_wb_lock_display",
        "GetAllIntents",
        "_reset_intent_unlocked",
        "_clear_intent_unlocked",
        "_clear_intent_if_match_unlocked",
        "_log_interrupt_clock_failure",
        "_get_interrupt_issuance_tick",
        "_is_valid_interrupt_receipt",
        "ClearIntent",
        "ClearIntentIfMatch",
        "ClearInterruptLockIfMatch",
        "ClearIntentsByOwner",
        "ClearLockByOwnerKindTarget",
        "UpsertLockByOwnerKindTarget",
        "PostLock",
        "CountLocks",
        "PostIntent",
        "TryPostInterruptLock",
        "SweepExpiredIntents",
    }
    methods = [
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in method_names
    ]
    namespace: dict[str, object] = {
        "ctypes": ctypes,
        "IntentStruct": INTENT_STRUCT,
        "PySystem": _Clock,
        "get_uncached_tick_count64": _LiveClock.get_uncached_tick_count64,
        "SHMEM_MAX_INTENTS": INTENT_COUNT,
        "SHMEM_MAX_PLAYERS": 4,
        "SHMEM_SHARED_MEMORY_FILE_NAME": shared_memory_name,
        "SHMEM_MAX_EMAIL_LEN": SHMEM_MAX_EMAIL_LEN,
        "WHITEBOARD_DEBUG": False,
        "ConsoleLog": _record_console_log,
        "SHMEM_MODULE_NAME": "test",
        "InterruptClaimResult": InterruptClaimResult,
        "InterruptLockReceipt": InterruptLockReceipt,
        "_INTERRUPT_ISSUANCE_WAIT_SECONDS": 0.050,
        "_INTERRUPT_ISSUANCE_SLEEP_SECONDS": 0.001,
        "_INTERRUPT_CLOCK_DIAGNOSTIC_COOLDOWN_SECONDS": 5.0,
        "_INTERRUPT_CLOCK_DIAGNOSTIC_MAX_SIGNATURES": 16,
        "_INTERRUPT_CLOCK_DIAGNOSTIC_LAST_LOGGED": {},
        "time": _FakeTiming,
        "intent_table_lock": INTENT_SYNC.intent_table_lock,
        "is_valid_future_lease": INTENT_SYNC.is_valid_future_lease,
        "normalize_tick": INTENT_SYNC.normalize_tick,
        "tick_elapsed": INTENT_SYNC.tick_elapsed,
        "tick_is_expired": INTENT_SYNC.tick_is_expired,
        **WHITEBOARD_ENUMS,
    }
    isolated = ast.Module(body=cast(list[ast.stmt], methods), type_ignores=[])
    ast.fix_missing_locations(isolated)
    exec(compile(isolated, str(ALL_ACCOUNTS_PATH), "exec"), namespace)

    def initialize(self: Any, intents: Any) -> None:
        setattr(self, "Intents", intents)
        account_data = []
        for _ in range(4):
            account = _DummyStruct()
            account.AccountEmail = ""
            account.IsAccount = False
            account.IsolationGroupID = 0
            account_data.append(account)
        setattr(self, "Keys", [_DummyStruct() for _ in range(4)])
        setattr(self, "AccountData", account_data)
        setattr(self, "Inbox", [_DummyStruct() for _ in range(4)])
        setattr(self, "HeroAIOptions", [_DummyStruct() for _ in range(4)])

    return type(
        "IntentAccounts",
        (),
        {name: namespace[name] for name in method_names if name in namespace} | {"__init__": initialize},
    )


def _load_method(
    source_path: Path,
    class_name: str,
    method_name: str,
    namespace: dict[str, object] | None = None,
) -> Callable[..., Any]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    class_node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == class_name)
    method_node = next(
        item
        for item in class_node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name
    )
    scope: dict[str, object] = dict(namespace or {})
    isolated = ast.Module(body=[method_node], type_ignores=[])
    ast.fix_missing_locations(isolated)
    exec(compile(isolated, str(source_path), "exec"), scope)
    return cast(Callable[..., Any], scope[method_name])


_SHARED_MEMORY_CLEAR_IF_MATCH = _load_method(
    SHARED_MEMORY_PATH,
    "Py4GWSharedMemoryManager",
    "ClearIntentIfMatch",
)
_SHARED_MEMORY_TRY_INTERRUPT = _load_method(
    SHARED_MEMORY_PATH,
    "Py4GWSharedMemoryManager",
    "TryPostInterruptLock",
    {"InterruptClaimResult": InterruptClaimResult},
)
_SHARED_MEMORY_CLEAR_INTERRUPT = _load_method(
    SHARED_MEMORY_PATH,
    "Py4GWSharedMemoryManager",
    "ClearInterruptLockIfMatch",
    {"InterruptLockReceipt": InterruptLockReceipt},
)
_SHARED_MEMORY_UPSERT_LOCK = _load_method(
    SHARED_MEMORY_PATH,
    "Py4GWSharedMemoryManager",
    "UpsertLockByOwnerKindTarget",
)
_BUILD_MGR_POST = _load_method(BUILD_MGR_PATH, "BuildMgr", "_whiteboard_post_intent", {"PySystem": _Clock})
_BUILD_MGR_CLEAR = _load_method(BUILD_MGR_PATH, "BuildMgr", "_whiteboard_owner_self_clear")


def _new_accounts(shared_memory_name: str | None = None) -> Any:
    identity = shared_memory_name or f"Py4GW_IntentUnitTest_{uuid4().hex}"
    accounts = _load_accounts_class(identity)(INTENT_ARRAY())
    _register_owner(accounts, OWNER, GROUP_ID, 0)
    _register_owner(accounts, OTHER_OWNER, GROUP_ID, 1)
    _register_owner(accounts, "group-five@example.com", OTHER_GROUP_ID, 2)
    return accounts


def _new_list_backed_accounts(shared_memory_name: str | None = None) -> Any:
    identity = shared_memory_name or f"Py4GW_IntentUnitTest_{uuid4().hex}"
    accounts = _load_accounts_class(identity)([INTENT_STRUCT() for _ in range(INTENT_COUNT)])
    _register_owner(accounts, OWNER, GROUP_ID, 0)
    _register_owner(accounts, OTHER_OWNER, GROUP_ID, 1)
    _register_owner(accounts, "group-five@example.com", OTHER_GROUP_ID, 2)
    return accounts


def _register_owner(accounts: Any, owner_email: str, group_id: int, index: int) -> None:
    account = getattr(accounts, "AccountData")[index]
    account.AccountEmail = owner_email
    account.IsAccount = True
    account.IsolationGroupID = group_id


def _seed_intent(
    accounts: Any,
    index: int,
    *,
    owner_email: str = OWNER,
    kind_id: int = SKILL_TARGET_KIND,
    skill_id: int = SKILL_ID,
    target_agent_id: int = TARGET_ID,
    group_id: int = GROUP_ID,
    posted_at_tick: int = NOW - 100,
    expires_at_tick: int = NOW + 5000,
    lock_mode: int = 1,
    max_holders: int = 1,
    reentry_policy: int = 1,
    claim_strength: int = 1,
) -> None:
    intent = getattr(accounts, "Intents")[index]
    intent.Active = False
    intent.OwnerEmail = owner_email
    intent.KindID = kind_id
    intent.LockMode = lock_mode
    intent.ReentryPolicy = reentry_policy
    intent.ClaimStrength = claim_strength
    intent.MaxHolders = max_holders
    intent.SkillID = skill_id
    intent.TargetAgentID = target_agent_id
    intent.IsolationGroupID = group_id
    intent.PostedAtTick = posted_at_tick
    intent.ExpiresAtTick = expires_at_tick
    intent.Active = True


def _seed_interrupt_intent(
    accounts: Any,
    index: int,
    *,
    owner_email: str = OWNER,
    enemy_skill_id: int = SKILL_ID,
    target_agent_id: int = TARGET_ID,
    group_id: int = GROUP_ID,
    posted_at_tick: int = NOW - 100,
    expires_at_tick: int = NOW + 5000,
    lock_mode: int = LOCK_EXCLUSIVE,
    max_holders: int = 1,
    reentry_policy: int = REENTRY_NONREENTRANT,
    claim_strength: int = CLAIM_HARD,
) -> None:
    _seed_intent(
        accounts,
        index,
        owner_email=owner_email,
        kind_id=INTERRUPT_KIND,
        skill_id=enemy_skill_id,
        target_agent_id=target_agent_id,
        group_id=group_id,
        posted_at_tick=posted_at_tick,
        expires_at_tick=expires_at_tick,
        lock_mode=lock_mode,
        max_holders=max_holders,
        reentry_policy=reentry_policy,
        claim_strength=claim_strength,
    )


def _seed_policy_heartbeat(
    accounts: Any,
    index: int,
    *,
    owner_email: str = OWNER,
    enabled: bool = False,
    posted_at_tick: int = NOW - 100,
    expires_at_tick: int = NOW + 3000,
) -> None:
    _seed_intent(
        accounts,
        index,
        owner_email=owner_email,
        kind_id=POLICY_KIND,
        skill_id=int(enabled),
        target_agent_id=POLICY_TARGET,
        group_id=POLICY_GROUP,
        posted_at_tick=posted_at_tick,
        expires_at_tick=expires_at_tick,
        lock_mode=LOCK_SHARED,
        max_holders=255,
        reentry_policy=REENTRY_OWNER,
        claim_strength=CLAIM_SOFT,
    )


def _claim_interrupt(
    accounts: Any,
    *,
    owner_email: str = OWNER,
    enemy_skill_id: int = SKILL_ID,
    target_agent_id: int = TARGET_ID,
    group_id: int = GROUP_ID,
    expires_at_tick: int | None = None,
) -> InterruptClaimResult:
    expires = _Clock.get_tick_count64() + 5000 if expires_at_tick is None else expires_at_tick
    return cast(
        InterruptClaimResult,
        getattr(accounts, "TryPostInterruptLock")(
            owner_email,
            enemy_skill_id,
            target_agent_id,
            expires,
            group_id,
        ),
    )


def _clear_identity(accounts: Any, index: int = 0, **overrides: object) -> bool:
    identity: dict[str, object] = {
        "owner_email": OWNER,
        "skill_id": SKILL_ID,
        "target_agent_id": TARGET_ID,
        "group_id": GROUP_ID,
    }
    identity.update(overrides)
    return bool(getattr(accounts, "ClearIntentIfMatch")(index, **identity))


def _shared_table_size() -> int:
    return ctypes.sizeof(INTENT_STRUCT) * INTENT_COUNT


def _close_shared_table(memory: Any) -> None:
    gc.collect()
    memory.close()


def _mutation_result(
    accounts: Any,
    operation: str,
    owner_email: str = OWNER,
    key_id: int = SKILL_ID,
    receipt: InterruptLockReceipt | None = None,
) -> object:
    now = _Clock.get_tick_count64()
    if operation == "post_interrupt":
        result = getattr(accounts, "TryPostInterruptLock")(
            owner_email,
            key_id,
            TARGET_ID,
            now + 60_000,
            GROUP_ID,
        )
        receipt = result.receipt
        return result.reason, receipt is not None, receipt.slot_index if receipt is not None else -1
    if operation == "clear_interrupt":
        if receipt is None:
            return False
        return bool(getattr(accounts, "ClearInterruptLockIfMatch")(receipt))
    if operation == "post_lock":
        return getattr(accounts, "PostLock")(
            owner_email,
            SKILL_TARGET_KIND,
            key_id,
            TARGET_ID,
            now + 60_000,
            GROUP_ID,
        )
    if operation == "post_intent":
        return getattr(accounts, "PostIntent")(OWNER, SKILL_ID, TARGET_ID, now + 60_000, GROUP_ID)
    if operation == "clear_intent":
        getattr(accounts, "ClearIntent")(0)
        return not getattr(accounts, "Intents")[0].Active
    if operation == "clear_exact":
        return _clear_identity(accounts, 0)
    if operation == "clear_owner":
        return getattr(accounts, "ClearIntentsByOwner")(OWNER)
    if operation == "clear_kind_target":
        return getattr(accounts, "ClearLockByOwnerKindTarget")(OWNER, SKILL_TARGET_KIND, TARGET_ID, GROUP_ID)
    if operation == "sweep":
        return getattr(accounts, "SweepExpiredIntents")(now)
    if operation == "reset":
        getattr(accounts, "reset")()
        return not getattr(accounts, "Intents")[0].Active
    raise ValueError(f"Unknown operation: {operation}")


def _intent_worker(
    shared_memory_name: str,
    mutex_identity: str,
    operation: str,
    owner_email: str,
    key_id: int,
    ready_event_name: str,
    start_event_name: str,
    started_event_name: str,
    receipt_payload: str,
) -> None:
    from multiprocessing import shared_memory

    ready_handle = _open_named_event(ready_event_name)
    start_handle = _open_named_event(start_event_name)
    started_handle = _open_named_event(started_event_name)
    memory = shared_memory.SharedMemory(name=shared_memory_name)
    intents = INTENT_ARRAY.from_buffer(cast(Any, memory.buf))
    accounts = _load_accounts_class(mutex_identity)(intents)
    _register_owner(accounts, owner_email, GROUP_ID, 0)
    try:
        _test_kernel32.SetEvent(ready_handle)
        if int(_test_kernel32.WaitForSingleObject(start_handle, 5000)) != _WAIT_OBJECT_0:
            raise TimeoutError("parent did not release worker start gate")
        _test_kernel32.SetEvent(started_handle)
        receipt = None
        if receipt_payload:
            receipt = InterruptLockReceipt(*cast(tuple[Any, ...], ast.literal_eval(receipt_payload)))
        result = _mutation_result(accounts, operation, owner_email, key_id, receipt)
        print(repr(result), flush=True)
    finally:
        del accounts
        del intents
        _close_shared_table(memory)
        _test_kernel32.CloseHandle(ready_handle)
        _test_kernel32.CloseHandle(start_handle)
        _test_kernel32.CloseHandle(started_handle)


def _run_child_mode() -> bool:
    if len(sys.argv) != 11 or sys.argv[1] != "--intent-worker":
        return False
    _intent_worker(
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
        sys.argv[5],
        int(sys.argv[6]),
        sys.argv[7],
        sys.argv[8],
        sys.argv[9],
        sys.argv[10],
    )
    return True


def _new_event_name() -> str:
    return f"Local\\Py4GW.IntentTest.{uuid4().hex}"


def _start_intent_worker(
    shared_memory_name: str,
    mutex_identity: str,
    operation: str,
    owner_email: str,
    key_id: int,
    receipt: InterruptLockReceipt | None = None,
) -> tuple[Any, _NamedEvent, _NamedEvent, _NamedEvent]:
    ready = _NamedEvent(_new_event_name())
    start = _NamedEvent(_new_event_name())
    started = _NamedEvent(_new_event_name())
    receipt_payload = ""
    if receipt is not None:
        receipt_payload = repr(
            (
                receipt.slot_index,
                receipt.owner_email,
                receipt.kind_id,
                receipt.enemy_skill_id,
                receipt.target_agent_id,
                receipt.isolation_group_id,
                receipt.lock_mode,
                receipt.max_holders,
                receipt.reentry_policy,
                receipt.claim_strength,
                receipt.posted_at_tick64,
                receipt.expires_at_tick64,
            )
        )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--intent-worker",
        shared_memory_name,
        mutex_identity,
        operation,
        owner_email,
        str(key_id),
        ready.name,
        start.name,
        started.name,
        receipt_payload,
    ]
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, ready, start, started


def _finish_worker(process: Any) -> tuple[int, str, str]:
    stdout, stderr = process.communicate(timeout=5)
    return int(process.returncode), stdout.strip(), stderr.strip()


class _SharedMemoryWrapper:
    ClearIntentIfMatch = _SHARED_MEMORY_CLEAR_IF_MATCH
    TryPostInterruptLock = _SHARED_MEMORY_TRY_INTERRUPT
    ClearInterruptLockIfMatch = _SHARED_MEMORY_CLEAR_INTERRUPT
    UpsertLockByOwnerKindTarget = _SHARED_MEMORY_UPSERT_LOCK

    def __init__(self, accounts: object, group_id: int = GROUP_ID) -> None:
        self.accounts = accounts
        self.group_id = group_id

    def GetAllAccounts(self) -> object:
        return self.accounts

    def GetAccountGroupByEmail(self, _owner_email: str) -> int:
        return self.group_id

    def PostIntent(
        self,
        owner_email: str,
        skill_id: int,
        target_agent_id: int,
        expires_at_tick: int,
        isolation_group_id: int,
    ) -> int:
        return int(
            getattr(self.accounts, "PostIntent")(
                owner_email,
                skill_id,
                target_agent_id,
                expires_at_tick,
                isolation_group_id,
            )
        )


class _BuildMgr:
    _whiteboard_post_intent = _BUILD_MGR_POST
    _whiteboard_owner_self_clear = _BUILD_MGR_CLEAR

    def __init__(self) -> None:
        self.pending = False
        self._wb_prev_cast_pending = False
        self._wb_posted_this_cast = False
        self._wb_posted_claim: tuple[int, str, int, int, int] | None = None

    def _is_local_cast_pending(self) -> bool:
        return self.pending


def _build_runtime_modules(shmem: _SharedMemoryWrapper) -> dict[str, types.ModuleType]:
    library = types.ModuleType("Py4GWCoreLib")
    library.__path__ = []
    agent = types.SimpleNamespace(IsValid=lambda _target: True, IsDead=lambda _target: False)
    setattr(library, "Agent", agent)

    skill_data = types.SimpleNamespace(GetActivation=lambda _skill: 1.0, GetAftercast=lambda _skill: 0.0)
    setattr(
        library,
        "GLOBAL_CACHE",
        types.SimpleNamespace(
            ShMem=shmem,
            Skill=types.SimpleNamespace(Data=skill_data),
        ),
    )
    setattr(library, "Player", types.SimpleNamespace(GetAccountEmail=lambda: OWNER))
    setattr(
        library,
        "Routines",
        types.SimpleNamespace(Checks=types.SimpleNamespace(Map=types.SimpleNamespace(MapValid=lambda: True))),
    )

    global_cache_package = types.ModuleType("Py4GWCoreLib.GlobalCache")
    global_cache_package.__path__ = []
    shared_memory_package = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src")
    shared_memory_package.__path__ = []
    globals_module = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.Globals")
    setattr(globals_module, "SHMEM_INTENT_DEFAULT_PING_BUDGET_MS", 250)
    return {
        "Py4GWCoreLib": library,
        "Py4GWCoreLib.GlobalCache": global_cache_package,
        "Py4GWCoreLib.GlobalCache.shared_memory_src": shared_memory_package,
        "Py4GWCoreLib.GlobalCache.shared_memory_src.Globals": globals_module,
    }


def _load_whiteboard_timestamp_consumers() -> dict[str, Callable[..., Any]]:
    tree = ast.parse(WHITEBOARD_LOCKS_PATH.read_text(encoding="utf-8"))
    class_nodes = [item for item in tree.body if isinstance(item, ast.FunctionDef)]
    names = {
        "get_resurrection_lock_owner",
        "read_resurrection_scroll_states",
        "post_hex_removal_lock",
        "post_buff_target_lock",
        "post_loot_lock",
    }
    namespace: dict[str, object] = {
        "PySystem": types.SimpleNamespace(get_tick_count64=lambda: 5),
        "tick_elapsed": INTENT_SYNC.tick_elapsed,
        "tick_is_expired": INTENT_SYNC.tick_is_expired,
        "_owner_context": lambda: (OWNER, GROUP_ID),
        "_skill_lock_duration_ms": lambda _skill, _aftercast, minimum: minimum,
        "RESURRECTION_LOCK_KEY": 0,
        "HEX_REMOVAL_LOCK_KEY": 0,
        "HEX_REMOVAL_LOCK_MIN_DURATION_MS": 500,
        "BUFF_TARGET_LOCK_KEY": 77,
        "BUFF_TARGET_LOCK_MIN_DURATION_MS": 500,
        "LOOT_LOCK_KEY": 0,
        "LOOT_LOCK_MIN_DURATION_MS": 500,
        **WHITEBOARD_ENUMS,
    }
    isolated = ast.Module(body=[node for node in class_nodes if node.name in names], type_ignores=[])
    ast.fix_missing_locations(isolated)
    exec(compile(isolated, str(WHITEBOARD_LOCKS_PATH), "exec"), namespace)
    return {name: cast(Callable[..., Any], namespace[name]) for name in names}


WHITEBOARD_TIMESTAMP_CONSUMERS = _load_whiteboard_timestamp_consumers()


def _load_policy_heartbeat_consumers(owner_context: Callable[[], tuple[str, int]]) -> dict[str, Callable[..., Any]]:
    tree = ast.parse(WHITEBOARD_LOCKS_PATH.read_text(encoding="utf-8"))
    function_names = {
        "_record_account_isolation_policy_publish_failure",
        "publish_account_isolation_policy",
        "clear_account_isolation_policy",
        "read_account_isolation_policies",
    }
    assignment_names = {
        "ACCOUNT_ISOLATION_POLICY_TARGET",
        "ACCOUNT_ISOLATION_POLICY_TTL_MS",
        "ACCOUNT_ISOLATION_POLICY_REFRESH_MS",
        "ACCOUNT_ISOLATION_POLICY_RETRY_MS",
        "_account_isolation_policy_last_publish",
        "_account_isolation_policy_last_failure",
        "_account_isolation_policy_failure_counts",
    }

    def assignment_targets(node: ast.stmt) -> set[str]:
        if isinstance(node, ast.Assign):
            return {target.id for target in node.targets if isinstance(target, ast.Name)}
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return {node.target.id}
        return set()

    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef) and node.name in function_names
        )
        or bool(assignment_targets(node) & assignment_names)
    ]
    namespace: dict[str, object] = {
        "PySystem": _Clock,
        "tick_elapsed": INTENT_SYNC.tick_elapsed,
        "tick_is_expired": INTENT_SYNC.tick_is_expired,
        "_owner_context": owner_context,
        **WHITEBOARD_ENUMS,
    }
    isolated = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(isolated)
    exec(compile(isolated, str(WHITEBOARD_LOCKS_PATH), "exec"), namespace)
    return {
        name: cast(Callable[..., Any], namespace[name])
        for name in function_names
        if name in namespace
    }


def _policy_heartbeat_runtime(
    accounts: Any,
    owner_context: Callable[[], tuple[str, int]],
    shmem: _SharedMemoryWrapper | None = None,
) -> tuple[dict[str, Callable[..., Any]], types.ModuleType]:
    runtime = types.ModuleType("Py4GWCoreLib")
    setattr(runtime, "GLOBAL_CACHE", types.SimpleNamespace(ShMem=shmem or _SharedMemoryWrapper(accounts)))
    return _load_policy_heartbeat_consumers(owner_context), runtime


class _CountingPolicySharedMemory(_SharedMemoryWrapper):
    def __init__(self, accounts: object, *, failures_remaining: int = 0) -> None:
        super().__init__(accounts)
        self.failures_remaining = failures_remaining
        self.upsert_calls = 0

    def UpsertLockByOwnerKindTarget(self, *args: object, **kwargs: object) -> int:
        self.upsert_calls += 1
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            return -1
        return int(super().UpsertLockByOwnerKindTarget(*args, **kwargs))


class _ObservingIntent:
    def __init__(self, intent: Any, observer: Callable[[], None]) -> None:
        object.__setattr__(self, "_intent", intent)
        object.__setattr__(self, "_observer", observer)

    def __getattr__(self, name: str) -> object:
        return getattr(object.__getattribute__(self, "_intent"), name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(object.__getattribute__(self, "_intent"), name, value)
        if name in {"ExpiresAtTick", "SkillID", "PostedAtTick"}:
            object.__getattribute__(self, "_observer")()

    def reset(self) -> None:
        object.__getattribute__(self, "_intent").reset()
        object.__getattribute__(self, "_observer")()


class _PartyAccount:
    def __init__(self, email: str, *, group_id: int, party_id: int, isolated: bool) -> None:
        self.AccountEmail = email
        self.IsAccount = True
        self.IsolationGroupID = group_id
        self.IsIsolated = isolated
        self.AgentPartyData = types.SimpleNamespace(PartyID=party_id)


class _PartySharedMemory:
    def __init__(self, accounts: list[_PartyAccount], intent_accounts: Any) -> None:
        self.accounts = accounts
        self.intent_accounts = intent_accounts
        self.group_writes: list[tuple[str, int]] = []
        self.isolation_writes: list[tuple[str, bool]] = []

    def _find(self, email: str) -> _PartyAccount | None:
        return next((account for account in self.accounts if account.AccountEmail == email), None)

    def GetAccountDataFromEmail(self, email: str) -> _PartyAccount | None:
        return self._find(email)

    def GetAllAccountData(
        self,
        *,
        sort_results: bool = True,
        include_isolated: bool = False,
    ) -> list[_PartyAccount]:
        del sort_results, include_isolated
        return list(self.accounts)

    def GetAccountGroupByEmail(self, email: str) -> int:
        account = self._find(email)
        return int(account.IsolationGroupID) if account is not None else 0

    def SetAccountGroupByEmail(self, email: str, group_id: int) -> bool:
        account = self._find(email)
        if account is None:
            return False
        account.IsolationGroupID = int(group_id)
        self.group_writes.append((email, int(group_id)))
        return True

    def IsAccountIsolated(self, email: str) -> bool:
        account = self._find(email)
        return bool(account and account.IsIsolated)

    def SetAccountIsolationByEmail(self, email: str, isolated: bool) -> bool:
        account = self._find(email)
        if account is None:
            return False
        account.IsIsolated = bool(isolated)
        self.isolation_writes.append((email, bool(isolated)))
        return True

    def GetAllAccounts(self) -> Any:
        return self.intent_accounts

    def UpsertLockByOwnerKindTarget(self, *args: object, **kwargs: object) -> int:
        return int(self.intent_accounts.UpsertLockByOwnerKindTarget(*args, **kwargs))


@contextmanager
def _loaded_policy_party_isolation(
    runtime: types.ModuleType,
    shared_memory: _PartySharedMemory,
    settings_assignments: dict[str, int],
    settings_groups: dict[int, str],
    local_email: str,
    policy_functions: dict[str, Callable[..., Any]],
) -> Any:
    class _Settings:
        def __init__(self, _name: str, _scope: str = "account") -> None:
            pass

        def has(self, section: str, key: str) -> bool:
            return section == "Assignments" and key in settings_assignments

        def get_int(self, section: str, key: str, default: int = 0) -> int:
            if section == "Assignments":
                return int(settings_assignments.get(key, default))
            if section != "Groups":
                return default
            group_ids = sorted(settings_groups)
            if key == "count":
                return len(group_ids)
            if key.startswith("id_"):
                try:
                    return int(group_ids[int(key.removeprefix("id_"))])
                except (IndexError, ValueError):
                    return default
            return default

        def get_str(self, section: str, key: str, default: str = "") -> str:
            if section != "Groups" or not key.startswith("name_"):
                return default
            try:
                group_id = sorted(settings_groups)[int(key.removeprefix("name_"))]
            except (IndexError, ValueError):
                return default
            return settings_groups.get(group_id, default)

    class _Timer:
        def __init__(self, _milliseconds: int) -> None:
            pass

        def IsExpired(self) -> bool:
            return True

        def Reset(self) -> None:
            pass

    runtime.__path__ = [str(ROOT / "Py4GWCoreLib")]
    setattr(runtime, "GLOBAL_CACHE", types.SimpleNamespace(ShMem=shared_memory))
    global_cache = types.ModuleType("Py4GWCoreLib.GlobalCache")
    global_cache.__path__ = [str(ROOT / "Py4GWCoreLib" / "GlobalCache")]
    setattr(global_cache, "GLOBAL_CACHE", runtime.GLOBAL_CACHE)
    whiteboard_locks = types.ModuleType("Py4GWCoreLib.GlobalCache.WhiteboardLocks")
    for name, function in policy_functions.items():
        setattr(whiteboard_locks, name, function)
    setattr(global_cache, "WhiteboardLocks", whiteboard_locks)
    botting_tree = types.ModuleType("Py4GWCoreLib.botting_tree_src")
    botting_tree.__path__ = [str(ROOT / "Py4GWCoreLib" / "botting_tree_src")]
    core = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src")
    core.__path__ = [str(ROOT / "Py4GWCoreLib" / "py4gwcorelib_src")]
    player = types.ModuleType("Py4GWCoreLib.Player")
    setattr(player, "Player", types.SimpleNamespace(GetAccountEmail=lambda: local_email))
    behavior_tree = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.BehaviorTree")
    setattr(behavior_tree, "BehaviorTree", type("BehaviorTree", (), {}))
    timer = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.Timer")
    setattr(timer, "ThrottledTimer", _Timer)
    settings = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.Settings")
    setattr(settings, "Settings", _Settings)
    py_system = types.ModuleType("PySystem")
    setattr(py_system, "Console", _ObservableConsole)
    modules = {
        "Py4GWCoreLib": runtime,
        "Py4GWCoreLib.GlobalCache": global_cache,
        "Py4GWCoreLib.GlobalCache.WhiteboardLocks": whiteboard_locks,
        "Py4GWCoreLib.botting_tree_src": botting_tree,
        "Py4GWCoreLib.py4gwcorelib_src": core,
        "Py4GWCoreLib.Player": player,
        "Py4GWCoreLib.py4gwcorelib_src.BehaviorTree": behavior_tree,
        "Py4GWCoreLib.py4gwcorelib_src.Timer": timer,
        "Py4GWCoreLib.py4gwcorelib_src.Settings": settings,
        "PySystem": py_system,
    }
    module_name = "Py4GWCoreLib.botting_tree_src._policy_heartbeat_party_test"
    with patch.dict(sys.modules, modules):
        spec = spec_from_file_location(module_name, ISOLATION_PATH)
        assert spec is not None and spec.loader is not None
        module = module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            yield module
        finally:
            sys.modules.pop(module_name, None)


class _ReadOnlyAccounts:
    def __init__(self, intents: list[Any]) -> None:
        self.intents = intents

    def GetAllIntents(self) -> list[tuple[int, Any]]:
        return [(index, intent) for index, intent in enumerate(self.intents) if intent.Active]


class _ReadOnlySharedMemory:
    def __init__(self, intents: list[Any]) -> None:
        self.accounts = _ReadOnlyAccounts(intents)
        self.posts: list[tuple[object, ...]] = []

    def GetAllAccounts(self) -> _ReadOnlyAccounts:
        return self.accounts

    def PostLock(self, *args: object) -> int:
        self.posts.append(args)
        return 17


class IntentSynchronizationTests(unittest.TestCase):
    def setUp(self) -> None:
        _Clock.value = NOW
        _LiveClock.reset()
        _FakeTiming.reset()
        _ObservableConsole.records.clear()
        self.shared_memory_name = f"Py4GW_IntentTest_{uuid4().hex}"
        self.accounts = _new_accounts(self.shared_memory_name)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_public_surface_is_uncached_and_fixed(self) -> None:
        wrapper = _SharedMemoryWrapper(self.accounts)
        result = wrapper.TryPostInterruptLock(
            OWNER,
            SKILL_ID,
            TARGET_ID,
            NOW + 5000,
            GROUP_ID,
        )
        self.assertEqual(result.reason, "claimed")
        self.assertIsNotNone(result.receipt)
        self.assertTrue(wrapper.ClearInterruptLockIfMatch(result.receipt))
        self.assertEqual(
            list(inspect.signature(self.accounts.TryPostInterruptLock).parameters),
            [
                "owner_email",
                "enemy_skill_id",
                "target_agent_id",
                "expires_at_tick",
                "isolation_group_id",
            ],
        )

        tree = ast.parse(SHARED_MEMORY_PATH.read_text(encoding="utf-8"))
        manager = next(item for item in tree.body if isinstance(item, ast.ClassDef))
        for method_name in ("TryPostInterruptLock", "ClearInterruptLockIfMatch"):
            method = next(
                item for item in manager.body if isinstance(item, ast.FunctionDef) and item.name == method_name
            )
            self.assertFalse(method.decorator_list, method_name)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_claim_uses_live_progress_when_frame_clock_is_frozen(self) -> None:
        _Clock.value = NOW
        _LiveClock.value = NOW
        _FakeTiming.advance_clock = False
        _FakeTiming.advance_live_clock = True

        result = _claim_interrupt(self.accounts, expires_at_tick=NOW + 5000)

        self.assertEqual(result.reason, "claimed")
        receipt = cast(InterruptLockReceipt, result.receipt)
        self.assertEqual(_Clock.value, NOW)
        self.assertGreater(receipt.posted_at_tick64, NOW)
        self.assertGreater(_LiveClock.value, NOW)
        self.assertEqual(
            self.accounts.Intents[receipt.slot_index].PostedAtTick,
            receipt.posted_at_tick64 & 0xFFFFFFFF,
        )
        self.assertEqual(receipt.expires_at_tick64, NOW + 5000)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_same_frame_repost_gets_new_receipt_and_rejects_stale_clear(self) -> None:
        _Clock.value = NOW
        _LiveClock.value = NOW
        _FakeTiming.advance_clock = False
        _FakeTiming.advance_live_clock = True
        expires_at_tick = NOW + 5000

        first = _claim_interrupt(self.accounts, expires_at_tick=expires_at_tick)
        first_receipt = cast(InterruptLockReceipt, first.receipt)
        self.assertTrue(self.accounts.ClearInterruptLockIfMatch(first_receipt))

        replacement = _claim_interrupt(self.accounts, expires_at_tick=expires_at_tick)
        replacement_receipt = cast(InterruptLockReceipt, replacement.receipt)

        self.assertEqual(replacement.reason, "claimed")
        self.assertEqual(first_receipt.slot_index, replacement_receipt.slot_index)
        self.assertEqual(first_receipt.expires_at_tick64, replacement_receipt.expires_at_tick64)
        self.assertNotEqual(first_receipt.posted_at_tick64, replacement_receipt.posted_at_tick64)
        self.assertFalse(self.accounts.ClearInterruptLockIfMatch(first_receipt))
        self.assertTrue(self.accounts.Intents[replacement_receipt.slot_index].Active)
        self.assertTrue(self.accounts.ClearInterruptLockIfMatch(replacement_receipt))

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_lease_expiry_during_publication_fails_closed_without_mutation(self) -> None:
        _LiveClock.sequence = [NOW, NOW + 1, NOW + 101]

        result = _claim_interrupt(self.accounts, expires_at_tick=NOW + 100)

        self.assertEqual(result.reason, "invalid")
        self.assertIsNone(result.receipt)
        self.assertFalse(any(intent.Active for intent in self.accounts.Intents))

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_live_clock_exception_fails_closed_without_mutation(self) -> None:
        _LiveClock.exception = RuntimeError("GetTickCount64 test failure")

        result = _claim_interrupt(self.accounts)

        self.assertEqual(result.reason, "issuance_tick_unavailable")
        self.assertIsNone(result.receipt)
        self.assertEqual(_LiveClock.calls, 1)
        self.assertFalse(any(intent.Active for intent in self.accounts.Intents))
        self.assertEqual(len(_ObservableConsole.records), 1)
        self.assertIn("stage=entry", _ObservableConsole.records[0][1])
        self.assertIn("RuntimeError", _ObservableConsole.records[0][1])
        self.assertIn("GetTickCount64 test failure", _ObservableConsole.records[0][1])

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_clock_failure_diagnostics_are_bounded_and_distinct(self) -> None:
        _seed_intent(self.accounts, 1, owner_email=OTHER_OWNER, skill_id=OTHER_SKILL_ID)
        unrelated_before = (
            self.accounts.Intents[1].Active,
            self.accounts.Intents[1].OwnerEmail,
            self.accounts.Intents[1].KindID,
            self.accounts.Intents[1].SkillID,
            self.accounts.Intents[1].TargetAgentID,
            self.accounts.Intents[1].IsolationGroupID,
            self.accounts.Intents[1].PostedAtTick,
            self.accounts.Intents[1].ExpiresAtTick,
        )
        _LiveClock.exception = RuntimeError("persistent GetTickCount64 failure")

        for _ in range(20):
            result = _claim_interrupt(self.accounts)
            self.assertEqual(result.reason, "issuance_tick_unavailable")
            self.assertIsNone(result.receipt)

        self.assertEqual(len(_ObservableConsole.records), 1)
        self.assertIn("stage=entry", _ObservableConsole.records[0][1])
        self.assertIn("RuntimeError", _ObservableConsole.records[0][1])
        self.assertIn("persistent GetTickCount64 failure", _ObservableConsole.records[0][1])
        self.assertEqual(
            unrelated_before,
            (
                self.accounts.Intents[1].Active,
                self.accounts.Intents[1].OwnerEmail,
                self.accounts.Intents[1].KindID,
                self.accounts.Intents[1].SkillID,
                self.accounts.Intents[1].TargetAgentID,
                self.accounts.Intents[1].IsolationGroupID,
                self.accounts.Intents[1].PostedAtTick,
                self.accounts.Intents[1].ExpiresAtTick,
            ),
        )

        _LiveClock.exception = None
        claimed = _claim_interrupt(self.accounts)
        self.assertEqual(claimed.reason, "claimed")
        receipt = cast(InterruptLockReceipt, claimed.receipt)
        _LiveClock.exception = OSError("release GetTickCount64 failure")
        self.assertFalse(self.accounts.ClearInterruptLockIfMatch(receipt))
        self.assertTrue(self.accounts.Intents[receipt.slot_index].Active)
        self.assertEqual(len(_ObservableConsole.records), 2)
        self.assertIn("stage=release", _ObservableConsole.records[1][1])
        self.assertIn("OSError", _ObservableConsole.records[1][1])
        self.assertIn("release GetTickCount64 failure", _ObservableConsole.records[1][1])
        self.assertEqual(
            unrelated_before,
            (
                self.accounts.Intents[1].Active,
                self.accounts.Intents[1].OwnerEmail,
                self.accounts.Intents[1].KindID,
                self.accounts.Intents[1].SkillID,
                self.accounts.Intents[1].TargetAgentID,
                self.accounts.Intents[1].IsolationGroupID,
                self.accounts.Intents[1].PostedAtTick,
                self.accounts.Intents[1].ExpiresAtTick,
            ),
        )

        diagnostic_globals = self.accounts._log_interrupt_clock_failure.__globals__
        for index in range(32):
            self.accounts._log_interrupt_clock_failure(
                f"stage-{index}",
                RuntimeError(f"unique failure {index}"),
            )
        self.assertEqual(
            len(diagnostic_globals["_INTERRUPT_CLOCK_DIAGNOSTIC_LAST_LOGGED"]),
            diagnostic_globals["_INTERRUPT_CLOCK_DIAGNOSTIC_MAX_SIGNATURES"],
        )

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_kind_one_post_intent_remains_independent_of_d0_live_clock(self) -> None:
        _LiveClock.exception = RuntimeError("D0-only live clock failure")

        index = self.accounts.PostIntent(OWNER, SKILL_ID, TARGET_ID, NOW + 5000, GROUP_ID)

        self.assertEqual(index, 0)
        row = self.accounts.Intents[index]
        self.assertTrue(row.Active)
        self.assertEqual(row.KindID, SKILL_TARGET_KIND)
        self.assertEqual(row.PostedAtTick, NOW & 0xFFFFFFFF)
        self.assertEqual(_LiveClock.calls, 0)
        self.assertTrue(_clear_identity(self.accounts, index))

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_claim_uses_fixed_exclusive_nonreentrant_contract(self) -> None:
        first = _claim_interrupt(self.accounts, owner_email=OWNER)
        self.assertEqual(first.reason, "claimed")
        self.assertIsNotNone(first.receipt)
        receipt = cast(InterruptLockReceipt, first.receipt)
        row = self.accounts.Intents[receipt.slot_index]
        self.assertEqual(row.KindID, INTERRUPT_KIND)
        self.assertEqual(row.SkillID, SKILL_ID)
        self.assertEqual(row.TargetAgentID, TARGET_ID)
        self.assertEqual(row.IsolationGroupID, GROUP_ID)
        self.assertEqual(row.LockMode, LOCK_EXCLUSIVE)
        self.assertEqual(row.MaxHolders, 1)
        self.assertEqual(row.ReentryPolicy, REENTRY_NONREENTRANT)
        self.assertEqual(row.ClaimStrength, CLAIM_HARD)

        self.assertEqual(_claim_interrupt(self.accounts).reason, "conflict")
        self.assertEqual(
            _claim_interrupt(self.accounts, owner_email=OTHER_OWNER).reason,
            "conflict",
        )
        self.assertNotIn(
            "max_holders",
            inspect.signature(self.accounts.TryPostInterruptLock).parameters,
        )

        independent = (
            _claim_interrupt(self.accounts, target_agent_id=OTHER_TARGET_ID),
            _claim_interrupt(self.accounts, enemy_skill_id=OTHER_SKILL_ID),
            _claim_interrupt(
                self.accounts,
                owner_email="group-five@example.com",
                group_id=OTHER_GROUP_ID,
            ),
        )
        self.assertTrue(all(item.reason == "claimed" and item.receipt is not None for item in independent))
        self.assertEqual(sum(bool(intent.Active) for intent in self.accounts.Intents), 4)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_exact_receipt_mismatches_preserve_live_row(self) -> None:
        mismatch_values: tuple[tuple[str, object], ...] = (
            ("slot_index", 1),
            ("owner_email", OTHER_OWNER),
            ("kind_id", SKILL_TARGET_KIND),
            ("enemy_skill_id", OTHER_SKILL_ID),
            ("target_agent_id", OTHER_TARGET_ID),
            ("isolation_group_id", OTHER_GROUP_ID),
            ("lock_mode", LOCK_SHARED),
            ("max_holders", 2),
            ("reentry_policy", REENTRY_OWNER),
            ("claim_strength", CLAIM_SOFT),
        )
        for field_name, value in mismatch_values:
            with self.subTest(field_name=field_name):
                accounts = _new_accounts(self.shared_memory_name)
                result = _claim_interrupt(accounts)
                receipt = cast(InterruptLockReceipt, result.receipt)
                row = accounts.Intents[receipt.slot_index]
                before = (
                    row.Active,
                    row.OwnerEmail,
                    row.KindID,
                    row.SkillID,
                    row.TargetAgentID,
                    row.IsolationGroupID,
                    row.PostedAtTick,
                    row.ExpiresAtTick,
                )
                self.assertFalse(accounts.ClearInterruptLockIfMatch(replace(receipt, **{field_name: value})))
                self.assertEqual(
                    before,
                    (
                        row.Active,
                        row.OwnerEmail,
                        row.KindID,
                        row.SkillID,
                        row.TargetAgentID,
                        row.IsolationGroupID,
                        row.PostedAtTick,
                        row.ExpiresAtTick,
                    ),
                )
                self.assertTrue(accounts.ClearInterruptLockIfMatch(receipt))

        for field_name in ("posted_at_tick64", "expires_at_tick64"):
            with self.subTest(field_name=field_name):
                accounts = _new_accounts(self.shared_memory_name)
                result = _claim_interrupt(accounts)
                fresh_receipt = cast(InterruptLockReceipt, result.receipt)
                wrong_value = getattr(fresh_receipt, field_name) + 1
                self.assertFalse(
                    accounts.ClearInterruptLockIfMatch(replace(fresh_receipt, **{field_name: wrong_value}))
                )
                self.assertTrue(accounts.Intents[fresh_receipt.slot_index].Active)

        with self.assertRaises(AttributeError):
            receipt.owner_email = OTHER_OWNER  # type: ignore[misc]

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_row_mismatches_preserve_live_claim(self) -> None:
        row_mismatches: tuple[tuple[str, object], ...] = (
            ("OwnerEmail", OTHER_OWNER),
            ("KindID", SKILL_TARGET_KIND),
            ("SkillID", OTHER_SKILL_ID),
            ("TargetAgentID", OTHER_TARGET_ID),
            ("IsolationGroupID", OTHER_GROUP_ID),
            ("LockMode", LOCK_SHARED),
            ("MaxHolders", 2),
            ("ReentryPolicy", REENTRY_OWNER),
            ("ClaimStrength", CLAIM_SOFT),
        )
        for field_name, value in row_mismatches:
            with self.subTest(field_name=field_name):
                accounts = _new_accounts(self.shared_memory_name)
                result = _claim_interrupt(accounts)
                receipt = cast(InterruptLockReceipt, result.receipt)
                row = accounts.Intents[receipt.slot_index]
                setattr(row, field_name, value)
                self.assertFalse(accounts.ClearInterruptLockIfMatch(receipt))
                self.assertTrue(row.Active)

        for field_name in ("PostedAtTick", "ExpiresAtTick"):
            with self.subTest(field_name=field_name):
                accounts = _new_accounts(self.shared_memory_name)
                result = _claim_interrupt(accounts)
                receipt = cast(InterruptLockReceipt, result.receipt)
                row = accounts.Intents[receipt.slot_index]
                setattr(row, field_name, (int(getattr(row, field_name)) + 1) & 0xFFFFFFFF)
                self.assertFalse(accounts.ClearInterruptLockIfMatch(receipt))
                self.assertTrue(row.Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_expiry_and_sweep_use_existing_wrap_safe_semantics(self) -> None:
        result = _claim_interrupt(self.accounts, expires_at_tick=NOW + 5)
        receipt = cast(InterruptLockReceipt, result.receipt)
        _Clock.value = NOW + 5
        _LiveClock.value = NOW + 5
        self.assertFalse(self.accounts.ClearInterruptLockIfMatch(receipt))
        self.assertEqual(self.accounts.SweepExpiredIntents(_Clock.value), 1)
        self.assertFalse(self.accounts.Intents[receipt.slot_index].Active)

        _Clock.value = 0xFFFFFFFE
        _LiveClock.value = 0xFFFFFFFE
        _FakeTiming.reset()
        result = _claim_interrupt(self.accounts, expires_at_tick=0x1_0000_0005)
        receipt = cast(InterruptLockReceipt, result.receipt)
        self.assertEqual(receipt.expires_at_tick64, 0x1_0000_0005)
        self.assertFalse(
            self.accounts.CountLocks(
                INTERRUPT_KIND,
                SKILL_ID,
                TARGET_ID,
                GROUP_ID,
                "",
                0xFFFFFFFE,
            )
            == 0
        )
        _Clock.value = 0x1_0000_0005
        _LiveClock.value = 0x1_0000_0005
        self.assertFalse(self.accounts.ClearInterruptLockIfMatch(receipt))
        self.assertEqual(self.accounts.SweepExpiredIntents(_Clock.value), 1)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_malformed_live_rows_fail_closed(self) -> None:
        _seed_interrupt_intent(self.accounts, 0, enemy_skill_id=0)
        before = (
            self.accounts.Intents[0].Active,
            self.accounts.Intents[0].SkillID,
            self.accounts.Intents[0].TargetAgentID,
        )
        result = _claim_interrupt(self.accounts, enemy_skill_id=OTHER_SKILL_ID)
        self.assertEqual(result.reason, "malformed_row")
        self.assertEqual(
            before,
            (
                self.accounts.Intents[0].Active,
                self.accounts.Intents[0].SkillID,
                self.accounts.Intents[0].TargetAgentID,
            ),
        )

        self.accounts.Intents[0].SkillID = SKILL_ID
        self.accounts.Intents[0].LockMode = LOCK_SHARED
        result = _claim_interrupt(self.accounts)
        self.assertEqual(result.reason, "malformed_row")
        self.assertTrue(self.accounts.Intents[0].Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_failure_paths_do_not_claim_or_evict_live_rows(self) -> None:
        invalid = _claim_interrupt(self.accounts, expires_at_tick=NOW)
        self.assertEqual(invalid.reason, "invalid")
        self.assertFalse(any(intent.Active for intent in self.accounts.Intents))
        self.assertEqual(
            _claim_interrupt(self.accounts, group_id=0).reason,
            "invalid",
        )
        self.assertEqual(
            _claim_interrupt(self.accounts, group_id=OTHER_GROUP_ID).reason,
            "owner_unavailable",
        )
        self.assertEqual(_claim_interrupt(self.accounts, owner_email="missing@example.com").reason, "owner_unavailable")

        _FakeTiming.advance_clock = False
        _FakeTiming.advance_live_clock = False
        stalled = _claim_interrupt(self.accounts)
        self.assertEqual(stalled.reason, "issuance_tick_unavailable")
        self.assertFalse(any(intent.Active for intent in self.accounts.Intents))
        self.assertGreater(_FakeTiming.sleep_calls, 0)
        _FakeTiming.advance_clock = True
        _FakeTiming.advance_live_clock = True

        class _FailingKernel32:
            def __init__(self, wait_result: int | None = None, create_error: bool = False) -> None:
                self.wait_result = wait_result
                self.create_error = create_error

            def CreateMutexW(self, *_args: object) -> int:
                if self.create_error:
                    raise OSError("creation failed")
                return 1

            def WaitForSingleObject(self, *_args: object) -> int:
                if self.wait_result is None:
                    raise OSError("wait failed")
                return self.wait_result

            def CloseHandle(self, _handle: object) -> bool:
                return True

        for fake in (_FailingKernel32(create_error=True), _FailingKernel32(), _FailingKernel32(0x102)):
            with patch.object(INTENT_SYNC, "_kernel32", fake):
                result = _claim_interrupt(self.accounts)
                self.assertEqual(result.reason, "mutex_unavailable")
                self.assertFalse(any(intent.Active for intent in self.accounts.Intents))

        for index in range(INTENT_COUNT):
            _seed_intent(
                self.accounts,
                index,
                owner_email=OWNER,
                skill_id=index + 1,
                target_agent_id=index + 100,
                expires_at_tick=NOW + 60_000,
            )
        full_table = _claim_interrupt(self.accounts, enemy_skill_id=9999, target_agent_id=9998)
        self.assertEqual(full_table.reason, "table_full")
        self.assertTrue(all(intent.Active for intent in self.accounts.Intents))

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_group_mutation_cannot_race_d0_owner_validation(self) -> None:
        claim_observed = threading.Event()
        allow_claim_observation = threading.Event()

        class _ObservedAccount:
            def __init__(self, source: Any) -> None:
                self.AccountEmail = source.AccountEmail
                self.IsAccount = source.IsAccount
                self._group_id = int(source.IsolationGroupID)

            @property
            def IsolationGroupID(self) -> int:
                observed_group_id = self._group_id
                if threading.current_thread().name == "d0-claimant":
                    claim_observed.set()
                    if not allow_claim_observation.wait(2000 / 1000):
                        raise TimeoutError("claim observation was not released")
                return observed_group_id

            @IsolationGroupID.setter
            def IsolationGroupID(self, group_id: int) -> None:
                self._group_id = int(group_id)

        class _CoordinatedIntentLock:
            def __init__(self) -> None:
                self._condition = threading.Condition()
                self._gate_open = False
                self._held = False
                self._waiters: list[str] = []
                self.claim_waiting = threading.Event()
                self.mutation_waiting = threading.Event()

            def open(self) -> None:
                with self._condition:
                    self._gate_open = True
                    self._condition.notify_all()

            @contextmanager
            def __call__(self, _shared_memory_name: str, timeout_ms: int = 1000) -> Any:
                role = "mutation" if threading.current_thread().name == "d0-group-mutation" else "claim"
                acquired = False
                deadline = time.monotonic() + timeout_ms / 1000
                with self._condition:
                    self._waiters.append(role)
                    if role == "mutation":
                        self.mutation_waiting.set()
                    else:
                        self.claim_waiting.set()
                    while not self._gate_open or self._held or (role == "claim" and "mutation" in self._waiters):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            self._waiters.remove(role)
                            break
                        self._condition.wait(remaining)
                    else:
                        self._waiters.remove(role)
                        self._held = True
                        acquired = True
                if not acquired:
                    yield False
                    return
                try:
                    yield True
                finally:
                    with self._condition:
                        self._held = False
                        self._condition.notify_all()

        mutex = _CoordinatedIntentLock()
        self.accounts.AccountData[0] = _ObservedAccount(self.accounts.AccountData[0])
        self.accounts.TryPostInterruptLock.__globals__["intent_table_lock"] = mutex
        self.accounts.SetAccountGroupByEmail.__globals__["intent_table_lock"] = mutex

        claim_result: list[InterruptClaimResult] = []

        def claim() -> None:
            claim_result.append(_claim_interrupt(self.accounts))

        mutation_done = threading.Event()
        mutation_result: list[bool] = []

        def move_owner() -> None:
            try:
                mutation_result.append(bool(self.accounts.SetAccountGroupByEmail(OWNER, OTHER_GROUP_ID)))
            finally:
                mutation_done.set()

        claimant = threading.Thread(target=claim, name="d0-claimant")
        claimant.start()
        deadline = time.monotonic() + 2
        while not (claim_observed.is_set() or mutex.claim_waiting.is_set()):
            if time.monotonic() >= deadline:
                self.fail("claim did not reach owner validation or the Intent mutex")
            time.sleep(0.001)

        mutator = threading.Thread(target=move_owner, name="d0-group-mutation")
        mutator.start()
        deadline = time.monotonic() + 2
        while not (mutation_done.is_set() or mutex.mutation_waiting.is_set()):
            if time.monotonic() >= deadline:
                self.fail("group mutation did not reach its synchronized writer")
            time.sleep(0.001)

        mutex.open()
        self.assertTrue(mutation_done.wait(2))
        allow_claim_observation.set()
        claimant.join(timeout=2)
        mutator.join(timeout=2)
        self.assertFalse(claimant.is_alive())
        self.assertFalse(mutator.is_alive())
        self.assertEqual(mutation_result, [True])
        self.assertEqual(len(claim_result), 1)
        self.assertEqual(claim_result[0].reason, "owner_unavailable")
        self.assertEqual(self.accounts.AccountData[0].IsolationGroupID, OTHER_GROUP_ID)
        self.assertFalse(any(intent.Active for intent in self.accounts.Intents))

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_publication_and_clear_order_are_active_gate_first_last(self) -> None:
        class _RecordingIntent:
            writes: list[str]

            def __init__(self) -> None:
                object.__setattr__(self, "writes", [])
                for name, value in (
                    ("OwnerEmail", ""),
                    ("KindID", 0),
                    ("LockMode", 0),
                    ("ReentryPolicy", 0),
                    ("ClaimStrength", 0),
                    ("MaxHolders", 0),
                    ("SkillID", 0),
                    ("TargetAgentID", 0),
                    ("IsolationGroupID", 0),
                    ("PostedAtTick", 0),
                    ("ExpiresAtTick", 0),
                    ("Active", False),
                ):
                    object.__setattr__(self, name, value)

            def __setattr__(self, name: str, value: object) -> None:
                if name != "writes":
                    self.writes.append(name)
                object.__setattr__(self, name, value)

            def reset(self) -> None:
                self.Active = False
                self.OwnerEmail = ""
                self.KindID = 0
                self.LockMode = 0
                self.ReentryPolicy = 0
                self.ClaimStrength = 0
                self.MaxHolders = 0
                self.SkillID = 0
                self.TargetAgentID = 0
                self.IsolationGroupID = 0
                self.PostedAtTick = 0
                self.ExpiresAtTick = 0

        self.accounts.Intents = [_RecordingIntent() for _ in range(INTENT_COUNT)]
        result = _claim_interrupt(self.accounts)
        receipt = cast(InterruptLockReceipt, result.receipt)
        row = self.accounts.Intents[receipt.slot_index]
        self.assertEqual(row.writes[-1], "Active")
        self.assertEqual(row.writes[-2:], ["ExpiresAtTick", "Active"])
        row.writes.clear()
        self.assertTrue(self.accounts.ClearInterruptLockIfMatch(receipt))
        self.assertEqual(row.writes[0], "Active")

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_abandoned_mutex_overwrites_partial_inactive_row_safely(self) -> None:
        row = self.accounts.Intents[0]
        row.Active = False
        row.OwnerEmail = "partial@example.com"
        row.KindID = INTERRUPT_KIND
        row.SkillID = 999
        row.TargetAgentID = TARGET_ID
        row.IsolationGroupID = GROUP_ID

        class _AbandonedKernel32:
            def CreateMutexW(self, *_args: object) -> int:
                return 1

            def WaitForSingleObject(self, *_args: object) -> int:
                return INTENT_SYNC.WAIT_ABANDONED

            def ReleaseMutex(self, _handle: object) -> bool:
                return True

            def CloseHandle(self, _handle: object) -> bool:
                return True

        with patch.object(INTENT_SYNC, "_kernel32", _AbandonedKernel32()):
            result = _claim_interrupt(self.accounts)
        self.assertEqual(result.reason, "claimed")
        receipt = cast(InterruptLockReceipt, result.receipt)
        self.assertEqual(receipt.slot_index, 0)
        self.assertTrue(row.Active)
        self.assertEqual(row.OwnerEmail, OWNER)
        self.assertEqual(row.SkillID, SKILL_ID)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_receipt_reuse_and_rollover_reject_stale_receipts(self) -> None:
        old_result = _claim_interrupt(self.accounts)
        old_receipt = cast(InterruptLockReceipt, old_result.receipt)
        self.assertTrue(self.accounts.ClearInterruptLockIfMatch(old_receipt))
        replacement_result = _claim_interrupt(self.accounts)
        replacement = cast(InterruptLockReceipt, replacement_result.receipt)
        self.assertEqual(old_receipt.slot_index, replacement.slot_index)
        self.assertNotEqual(old_receipt.posted_at_tick64, replacement.posted_at_tick64)
        self.assertFalse(self.accounts.ClearInterruptLockIfMatch(old_receipt))
        self.assertTrue(self.accounts.Intents[replacement.slot_index].Active)
        self.assertTrue(self.accounts.ClearInterruptLockIfMatch(replacement))

        _Clock.value = 0xFFFFFFF0
        _LiveClock.value = 0xFFFFFFF0
        _FakeTiming.reset()
        rollover_result = _claim_interrupt(
            self.accounts,
            expires_at_tick=0x1_0000_0005,
        )
        rollover_receipt = cast(InterruptLockReceipt, rollover_result.receipt)
        self.assertTrue(self.accounts.ClearInterruptLockIfMatch(rollover_receipt))
        _Clock.value = rollover_receipt.expires_at_tick64
        _LiveClock.value = rollover_receipt.expires_at_tick64
        replacement_result = _claim_interrupt(self.accounts)
        replacement = cast(InterruptLockReceipt, replacement_result.receipt)
        self.assertFalse(self.accounts.ClearInterruptLockIfMatch(rollover_receipt))
        self.assertTrue(self.accounts.Intents[replacement.slot_index].Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_exact_matching_claim_clears_and_sibling_claim_survives(self) -> None:
        _seed_intent(self.accounts, 0)
        _seed_intent(self.accounts, 1, skill_id=OTHER_SKILL_ID)
        self.assertTrue(_clear_identity(self.accounts, 0))
        self.assertFalse(self.accounts.Intents[0].Active)
        self.assertTrue(self.accounts.Intents[1].Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_wrong_identity_and_post_intent_policy_mismatches_survive(self) -> None:
        mismatches = (
            {"owner_email": OTHER_OWNER},
            {"kind_id": 2},
            {"skill_id": OTHER_SKILL_ID},
            {"target_agent_id": OTHER_TARGET_ID},
            {"group_id": OTHER_GROUP_ID},
            {"lock_mode": 2},
            {"max_holders": 2},
            {"reentry_policy": 2},
            {"claim_strength": 2},
        )
        for mismatch in mismatches:
            with self.subTest(mismatch=mismatch):
                self.accounts = _new_accounts(self.shared_memory_name)
                _seed_intent(self.accounts, 0, **cast(Any, mismatch))
                self.assertFalse(_clear_identity(self.accounts, 0))
                self.assertTrue(self.accounts.Intents[0].Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_expiry_is_not_claim_identity_and_old_expiry_argument_is_rejected(
        self,
    ) -> None:
        _seed_intent(self.accounts, 0, expires_at_tick=NOW + 9000)
        self.assertNotIn(
            "expires_at_tick",
            inspect.signature(self.accounts.ClearIntentIfMatch).parameters,
        )
        with self.assertRaises(TypeError):
            self.accounts.ClearIntentIfMatch(0, OWNER, SKILL_ID, TARGET_ID, GROUP_ID, (1 << 32) + 1)
        self.assertTrue(_clear_identity(self.accounts, 0))
        self.assertFalse(self.accounts.Intents[0].Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_broad_owner_clear_retains_existing_behavior(self) -> None:
        _seed_intent(self.accounts, 0)
        _seed_intent(self.accounts, 1, skill_id=OTHER_SKILL_ID, group_id=OTHER_GROUP_ID)
        _seed_intent(self.accounts, 2, owner_email=OTHER_OWNER)
        self.assertEqual(self.accounts.ClearIntentsByOwner(OWNER), 2)
        self.assertFalse(self.accounts.Intents[0].Active)
        self.assertFalse(self.accounts.Intents[1].Active)
        self.assertTrue(self.accounts.Intents[2].Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_build_mgr_completion_and_rejection_clear_only_the_retained_claim(
        self,
    ) -> None:
        _seed_intent(self.accounts, 1, skill_id=OTHER_SKILL_ID)
        wrapper = _SharedMemoryWrapper(self.accounts)
        build = _BuildMgr()
        with patch.dict(sys.modules, _build_runtime_modules(wrapper)):
            build._whiteboard_post_intent(SKILL_ID, TARGET_ID)
            self.assertEqual(build._wb_posted_claim, (0, OWNER, SKILL_ID, TARGET_ID, GROUP_ID))
            build.pending = True
            build._whiteboard_owner_self_clear()
            self.assertTrue(self.accounts.Intents[0].Active)
            build.pending = False
            build._whiteboard_owner_self_clear()
        self.assertFalse(self.accounts.Intents[0].Active)
        self.assertTrue(self.accounts.Intents[1].Active)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_post_lock_normalizes_both_ticks_and_rejects_invalid_leases(self) -> None:
        self.assertEqual(
            self.accounts.PostLock(OWNER, INTERRUPT_KIND, SKILL_ID, TARGET_ID, NOW + 5000, GROUP_ID),
            -1,
        )
        self.assertEqual(
            self.accounts.PostLock(OWNER, SKILL_TARGET_KIND, SKILL_ID, TARGET_ID, NOW, GROUP_ID),
            -1,
        )
        self.assertEqual(
            self.accounts.PostLock(OWNER, SKILL_TARGET_KIND, SKILL_ID, TARGET_ID, NOW - 1, GROUP_ID),
            -1,
        )
        self.assertEqual(
            self.accounts.PostLock(
                OWNER,
                SKILL_TARGET_KIND,
                SKILL_ID,
                TARGET_ID,
                NOW + 0x80000000,
                GROUP_ID,
            ),
            -1,
        )
        index = self.accounts.PostLock(
            OWNER,
            SKILL_TARGET_KIND,
            SKILL_ID,
            TARGET_ID,
            NOW + 5000,
            GROUP_ID,
        )
        self.assertEqual(index, 0)
        self.assertEqual(self.accounts.Intents[index].PostedAtTick, NOW & 0xFFFFFFFF)
        self.assertEqual(self.accounts.Intents[index].ExpiresAtTick, (NOW + 5000) & 0xFFFFFFFF)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_count_and_sweep_handle_a_lease_crossing_uint32_wrap(self) -> None:
        _seed_intent(
            self.accounts,
            0,
            posted_at_tick=0xFFFFFFF0,
            expires_at_tick=0x00000005,
        )
        count_args = (SKILL_TARGET_KIND, SKILL_ID, TARGET_ID, GROUP_ID, "", 0xFFFFFFFE)
        self.assertEqual(self.accounts.CountLocks(*count_args), 1)
        self.assertEqual(self.accounts.SweepExpiredIntents(0xFFFFFFFE), 0)
        self.assertTrue(self.accounts.Intents[0].Active)
        self.assertEqual(self.accounts.CountLocks(*count_args[:-1], 0x00000005), 0)
        self.assertEqual(self.accounts.SweepExpiredIntents(0x00000005), 1)
        self.assertFalse(self.accounts.Intents[0].Active)

    def test_tick_helpers_use_modular_uint32_time(self) -> None:
        self.assertEqual(INTENT_SYNC.normalize_tick(0x1_0000_0001), 1)
        self.assertEqual(INTENT_SYNC.tick_elapsed(0x00000005, 0xFFFFFFF0), 21)
        self.assertFalse(INTENT_SYNC.tick_is_expired(0xFFFFFFFE, 0x00000005))
        self.assertTrue(INTENT_SYNC.tick_is_expired(0x00000005, 0x00000005))
        self.assertTrue(INTENT_SYNC.tick_is_expired(0x00000006, 0x00000005))
        self.assertTrue(INTENT_SYNC.is_valid_future_lease(0xFFFFFFFF, 0x1_0000_0000))
        self.assertFalse(INTENT_SYNC.is_valid_future_lease(100, 100))
        self.assertFalse(INTENT_SYNC.is_valid_future_lease(100, 99))
        self.assertFalse(INTENT_SYNC.is_valid_future_lease(100, 100 + 0x80000000))

    def test_mutex_name_is_stable_and_scoped_to_shared_memory_identity(self) -> None:
        name = INTENT_SYNC.intent_mutex_name("Py4GW_Shared_Mem")
        digest = hashlib.sha256(b"Py4GW_Shared_Mem").hexdigest()[:32]
        self.assertEqual(name, f"Local\\Py4GW.IntentTable.{digest}")
        self.assertEqual(name, INTENT_SYNC.intent_mutex_name("Py4GW_Shared_Mem"))
        self.assertNotEqual(name, INTENT_SYNC.intent_mutex_name("Other_Shared_Mem"))

    def test_abandoned_mutex_is_treated_as_acquired(self) -> None:
        class _FakeKernel32:
            released = 0
            closed = 0

            def CreateMutexW(self, *_args: object) -> int:
                return 1

            def WaitForSingleObject(self, *_args: object) -> int:
                return INTENT_SYNC.WAIT_ABANDONED

            def ReleaseMutex(self, _handle: object) -> bool:
                self.released += 1
                return True

            def CloseHandle(self, _handle: object) -> bool:
                self.closed += 1
                return True

        fake = _FakeKernel32()
        with patch.object(INTENT_SYNC, "_kernel32", fake):
            with INTENT_SYNC.intent_table_lock(self.shared_memory_name, timeout_ms=20) as acquired:
                self.assertTrue(acquired)
        self.assertEqual(fake.released, 1)
        self.assertEqual(fake.closed, 1)

    def test_mutex_creation_or_wait_failure_leaves_mutators_fail_safe(self) -> None:
        class _FailingKernel32:
            def __init__(self, wait_result: int | None = None, create_error: bool = False) -> None:
                self.wait_result = wait_result
                self.create_error = create_error
                self.closed = 0

            def CreateMutexW(self, *_args: object) -> int:
                if self.create_error:
                    raise OSError("creation failed")
                return 1

            def WaitForSingleObject(self, *_args: object) -> int:
                if self.wait_result is None:
                    raise OSError("wait failed")
                return self.wait_result

            def CloseHandle(self, _handle: object) -> bool:
                self.closed += 1
                return True

        _seed_intent(self.accounts, 0)
        for fake in (
            _FailingKernel32(create_error=True),
            _FailingKernel32(),
            _FailingKernel32(0x00000102),
        ):
            with patch.object(INTENT_SYNC, "_kernel32", fake):
                self.assertEqual(
                    self.accounts.PostLock(
                        OWNER,
                        SKILL_TARGET_KIND,
                        SKILL_ID,
                        TARGET_ID,
                        NOW + 5000,
                        GROUP_ID,
                    ),
                    -1,
                )
                self.assertFalse(_clear_identity(self.accounts, 0))
                self.assertEqual(self.accounts.SweepExpiredIntents(NOW + 100_000), 0)
                self.accounts.ClearIntent(0)
                self.assertEqual(self.accounts.ClearIntentsByOwner(OWNER), 0)
                self.assertEqual(
                    self.accounts.ClearLockByOwnerKindTarget(OWNER, SKILL_TARGET_KIND, TARGET_ID, GROUP_ID),
                    0,
                )
                self.accounts.reset()
                self.assertTrue(self.accounts.Intents[0].Active)
            self.assertEqual(fake.closed, 0 if fake.create_error else 7)

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_public_mutators_block_on_the_same_cross_process_mutex(self) -> None:
        from multiprocessing import shared_memory

        memory = shared_memory.SharedMemory(create=True, size=_shared_table_size())
        intents = INTENT_ARRAY.from_buffer(cast(Any, memory.buf))
        accounts = _load_accounts_class(memory.name)(intents)
        operations = (
            "post_lock",
            "post_intent",
            "clear_intent",
            "clear_exact",
            "clear_owner",
            "clear_kind_target",
            "sweep",
            "reset",
        )
        try:
            for operation in operations:
                for index in range(INTENT_COUNT):
                    intents[index].reset()
                if operation in (
                    "clear_intent",
                    "clear_exact",
                    "clear_owner",
                    "clear_kind_target",
                    "reset",
                ):
                    _seed_intent(accounts, 0)
                if operation == "sweep":
                    _seed_intent(accounts, 0, expires_at_tick=(NOW & 0xFFFFFFFF) - 1)

                process: Any = None
                worker_events: tuple[_NamedEvent, _NamedEvent, _NamedEvent] | None = None
                try:
                    with INTENT_SYNC.intent_table_lock(memory.name, timeout_ms=1500) as acquired:
                        self.assertTrue(acquired)
                        process, ready, start, started = _start_intent_worker(
                            memory.name,
                            memory.name,
                            operation,
                            OWNER,
                            SKILL_ID,
                        )
                        worker_events = (ready, start, started)
                        self.assertTrue(ready.wait())
                        start.set()
                        self.assertTrue(started.wait())
                        time.sleep(0.1)
                        self.assertIsNone(
                            process.poll(),
                            f"{operation} must wait for the shared mutex",
                        )
                    return_code, stdout, stderr = _finish_worker(process)
                    self.assertEqual(return_code, 0, stderr)
                    result = ast.literal_eval(stdout)
                    if operation == "post_lock" or operation == "post_intent":
                        self.assertGreaterEqual(int(result), 0)
                    elif operation == "clear_exact":
                        self.assertTrue(result)
                    elif operation in ("clear_owner", "clear_kind_target", "sweep"):
                        self.assertEqual(result, 1)
                    elif operation in ("clear_intent", "reset"):
                        self.assertTrue(result)
                        self.assertFalse(intents[0].Active)
                finally:
                    if process is not None and process.poll() is None:
                        if worker_events is not None:
                            worker_events[1].set()
                        process.kill()
                        process.wait(timeout=2)
                    if worker_events is not None:
                        for event in worker_events:
                            event.close()
        finally:
            del accounts
            del intents
            _close_shared_table(memory)
            memory.unlink()

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_exact_release_and_replacement_are_serialized_across_processes(
        self,
    ) -> None:
        from multiprocessing import shared_memory

        memory = shared_memory.SharedMemory(create=True, size=_shared_table_size())
        intents = INTENT_ARRAY.from_buffer(cast(Any, memory.buf))
        accounts = _load_accounts_class(memory.name)(intents)
        _seed_intent(accounts, 0)
        poster: Any = None
        ready: _NamedEvent | None = None
        start: _NamedEvent | None = None
        started: _NamedEvent | None = None
        try:
            with INTENT_SYNC.intent_table_lock(memory.name, timeout_ms=1500) as acquired:
                self.assertTrue(acquired)
                self.assertTrue(accounts._clear_intent_if_match_unlocked(0, OWNER, SKILL_ID, TARGET_ID, GROUP_ID))
                poster, ready, start, started = _start_intent_worker(
                    memory.name,
                    memory.name,
                    "post_lock",
                    OTHER_OWNER,
                    OTHER_SKILL_ID,
                )
                self.assertTrue(ready.wait())
                start.set()
                self.assertTrue(started.wait())
                time.sleep(0.1)
                self.assertIsNone(
                    poster.poll(),
                    "replacement must wait while exact release owns the mutex",
                )
            return_code, stdout, stderr = _finish_worker(poster)
            self.assertEqual(return_code, 0, stderr)
            replacement_slot = ast.literal_eval(stdout)
            self.assertEqual(replacement_slot, 0)
            self.assertTrue(intents[replacement_slot].Active)
            self.assertEqual(intents[replacement_slot].OwnerEmail, OTHER_OWNER)
            self.assertEqual(intents[replacement_slot].SkillID, OTHER_SKILL_ID)
        finally:
            if poster is not None and poster.poll() is None:
                poster.kill()
                poster.wait(timeout=2)
            for event in (ready, start, started):
                if event is not None:
                    event.set()
                    event.close()
            del accounts
            del intents
            _close_shared_table(memory)
            memory.unlink()

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_simultaneous_post_lock_processes_get_independent_slots(self) -> None:
        from multiprocessing import shared_memory

        memory = shared_memory.SharedMemory(create=True, size=_shared_table_size())
        intents = INTENT_ARRAY.from_buffer(cast(Any, memory.buf))
        workers: list[tuple[Any, _NamedEvent, _NamedEvent, _NamedEvent]] = []
        try:
            workers = [
                _start_intent_worker(memory.name, memory.name, "post_lock", owner, key_id)
                for owner, key_id in ((OWNER, SKILL_ID), (OTHER_OWNER, OTHER_SKILL_ID))
            ]
            for _, ready, _, _ in workers:
                self.assertTrue(ready.wait())
            for _, _, start, _ in workers:
                start.set()
            for _, _, _, started in workers:
                self.assertTrue(started.wait())
            worker_results = [_finish_worker(process) for process, _, _, _ in workers]
            for return_code, _, stderr in worker_results:
                self.assertEqual(return_code, 0, stderr)
            slots = [int(ast.literal_eval(stdout)) for _, stdout, _ in worker_results]
            self.assertEqual(len(set(slots)), 2)
            self.assertEqual(set(slots), {0, 1})
            self.assertTrue(all(intents[slot].Active for slot in slots))
            self.assertEqual({intents[slot].OwnerEmail for slot in slots}, {OWNER, OTHER_OWNER})
        finally:
            for process, ready, start, started in workers:
                start.set()
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                ready.close()
                start.close()
                started.close()
            del intents
            _close_shared_table(memory)
            memory.unlink()

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_simultaneous_interrupt_claims_for_same_key_elect_one_repeatedly(self) -> None:
        from multiprocessing import shared_memory

        memory = shared_memory.SharedMemory(create=True, size=_shared_table_size())
        intents = INTENT_ARRAY.from_buffer(cast(Any, memory.buf))
        workers: list[tuple[Any, _NamedEvent, _NamedEvent, _NamedEvent]] = []
        active_rows: list[Any] = []
        intent: Any = None
        try:
            for _ in range(5):
                for intent in intents:
                    intent.reset()
                workers = [
                    _start_intent_worker(memory.name, memory.name, "post_interrupt", owner, SKILL_ID)
                    for owner in (OWNER, OTHER_OWNER)
                ]
                for _, ready, _, _ in workers:
                    self.assertTrue(ready.wait())
                for _, _, start, _ in workers:
                    start.set()
                for _, _, _, started in workers:
                    self.assertTrue(started.wait())
                worker_results = [_finish_worker(process) for process, _, _, _ in workers]
                for return_code, _, stderr in worker_results:
                    self.assertEqual(return_code, 0, stderr)
                outcomes = [ast.literal_eval(stdout) for _, stdout, _ in worker_results]
                self.assertEqual(sum(outcome[0] == "claimed" for outcome in outcomes), 1)
                self.assertEqual(sum(outcome[0] == "conflict" for outcome in outcomes), 1)
                self.assertEqual(sum(outcome[1] for outcome in outcomes), 1)
                active_rows = [intent for intent in intents if intent.Active]
                self.assertEqual(len(active_rows), 1)
                self.assertEqual(active_rows[0].KindID, INTERRUPT_KIND)
                self.assertEqual(active_rows[0].SkillID, SKILL_ID)
                self.assertEqual(active_rows[0].TargetAgentID, TARGET_ID)
                for process, ready, start, started in workers:
                    ready.close()
                    start.close()
                    started.close()
                workers = []
        finally:
            for process, ready, start, started in workers:
                start.set()
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=2)
                ready.close()
                start.close()
                started.close()
            active_rows.clear()
            intent = None
            del intents
            _close_shared_table(memory)
            memory.unlink()

    @unittest.skipUnless(os.name == "nt", "the production table guard is a Windows named mutex")
    def test_interrupt_stale_cross_process_clear_cannot_erase_replacement(self) -> None:
        from multiprocessing import shared_memory

        memory = shared_memory.SharedMemory(create=True, size=_shared_table_size())
        intents = INTENT_ARRAY.from_buffer(cast(Any, memory.buf))
        accounts = _load_accounts_class(memory.name)(intents)
        _register_owner(accounts, OWNER, GROUP_ID, 0)
        _register_owner(accounts, OTHER_OWNER, GROUP_ID, 1)
        process: Any = None
        worker_events: tuple[_NamedEvent, _NamedEvent, _NamedEvent] | None = None
        replacement: Any = None
        try:
            result = _claim_interrupt(accounts)
            receipt = cast(InterruptLockReceipt, result.receipt)
            with INTENT_SYNC.intent_table_lock(memory.name, timeout_ms=1500) as acquired:
                self.assertTrue(acquired)
                process, ready, start, started = _start_intent_worker(
                    memory.name,
                    memory.name,
                    "clear_interrupt",
                    OWNER,
                    SKILL_ID,
                    receipt,
                )
                worker_events = (ready, start, started)
                self.assertTrue(ready.wait())
                start.set()
                self.assertTrue(started.wait())
                time.sleep(0.1)
                self.assertIsNone(process.poll(), "exact clear must wait for the shared mutex")
                _seed_interrupt_intent(
                    accounts,
                    receipt.slot_index,
                    owner_email=OTHER_OWNER,
                    enemy_skill_id=OTHER_SKILL_ID,
                    posted_at_tick=receipt.posted_at_tick64 + 1,
                    expires_at_tick=NOW + 5000,
                )
            return_code, stdout, stderr = _finish_worker(process)
            self.assertEqual(return_code, 0, stderr)
            self.assertFalse(ast.literal_eval(stdout))
            replacement = intents[receipt.slot_index]
            self.assertTrue(replacement.Active)
            self.assertEqual(replacement.OwnerEmail, OTHER_OWNER)
            self.assertEqual(replacement.SkillID, OTHER_SKILL_ID)
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=2)
            if worker_events is not None:
                for event in worker_events:
                    event.set()
                    event.close()
            replacement = None
            del accounts
            del intents
            _close_shared_table(memory)
            memory.unlink()

    def test_policy_heartbeat_refresh_never_exposes_an_absent_policy(self) -> None:
        for initial_enabled, desired_enabled in ((True, True), (False, False), (True, False), (False, True)):
            with self.subTest(initial_enabled=initial_enabled, desired_enabled=desired_enabled):
                _Clock.value = NOW
                accounts = _new_list_backed_accounts()
                _seed_policy_heartbeat(accounts, 0, enabled=initial_enabled)
                functions, runtime = _policy_heartbeat_runtime(accounts, lambda: (OWNER, POLICY_GROUP))
                publish = functions["publish_account_isolation_policy"]
                read = functions["read_account_isolation_policies"]
                observations: list[dict[str, bool]] = []
                accounts.Intents[0] = _ObservingIntent(
                    accounts.Intents[0],
                    lambda: observations.append(dict(read())),
                )

                with patch.dict(sys.modules, {"Py4GWCoreLib": runtime}):
                    self.assertTrue(publish(desired_enabled, force=True))
                    self.assertEqual(read(), {OWNER: desired_enabled})

                self.assertTrue(observations)
                self.assertTrue(all(OWNER in policies for policies in observations))
                self.assertTrue(
                    all(policies[OWNER] in (initial_enabled, desired_enabled) for policies in observations)
                )

    def test_policy_heartbeat_failed_refresh_preserves_old_policy_until_expiry(self) -> None:
        accounts = _new_accounts()
        original_expiry = NOW + 3000
        _seed_policy_heartbeat(accounts, 0, enabled=False, expires_at_tick=original_expiry)
        shmem = _CountingPolicySharedMemory(accounts, failures_remaining=1)
        functions, runtime = _policy_heartbeat_runtime(
            accounts,
            lambda: (OWNER, POLICY_GROUP),
            shmem,
        )
        publish = functions["publish_account_isolation_policy"]
        read = functions["read_account_isolation_policies"]

        with patch.dict(sys.modules, {"Py4GWCoreLib": runtime}):
            self.assertFalse(publish(False, force=True))
            self.assertEqual(shmem.upsert_calls, 1)
            self.assertEqual(read(), {OWNER: False})
            self.assertEqual(int(accounts.Intents[0].ExpiresAtTick), original_expiry & 0xFFFFFFFF)

            self.assertFalse(publish(False))
            self.assertEqual(shmem.upsert_calls, 1)

            _Clock.value = original_expiry
            self.assertEqual(read(), {})

    def test_policy_heartbeat_initial_failure_is_throttled_then_recovers(self) -> None:
        accounts = _new_accounts()
        shmem = _CountingPolicySharedMemory(accounts, failures_remaining=1)
        functions, runtime = _policy_heartbeat_runtime(
            accounts,
            lambda: (OWNER, POLICY_GROUP),
            shmem,
        )
        publish = functions["publish_account_isolation_policy"]
        read = functions["read_account_isolation_policies"]

        with patch.dict(sys.modules, {"Py4GWCoreLib": runtime}):
            self.assertFalse(publish(True))
            self.assertEqual(shmem.upsert_calls, 1)
            self.assertEqual(read(), {})

            for _ in range(4):
                self.assertFalse(publish(True))
            self.assertEqual(shmem.upsert_calls, 1)

            _Clock.value += 249
            self.assertFalse(publish(True))
            self.assertEqual(shmem.upsert_calls, 1)

            _Clock.value += 1
            self.assertTrue(publish(True))
            self.assertEqual(shmem.upsert_calls, 2)
            self.assertEqual(read(), {OWNER: True})

            self.assertTrue(publish(True))
            self.assertEqual(shmem.upsert_calls, 2)
            _Clock.value += 1000
            self.assertTrue(publish(True))
            self.assertEqual(shmem.upsert_calls, 3)

    def test_policy_heartbeat_failed_refresh_recovers_to_the_new_policy(self) -> None:
        accounts = _new_accounts()
        _seed_policy_heartbeat(accounts, 0, enabled=False)
        shmem = _CountingPolicySharedMemory(accounts, failures_remaining=1)
        functions, runtime = _policy_heartbeat_runtime(
            accounts,
            lambda: (OWNER, POLICY_GROUP),
            shmem,
        )
        publish = functions["publish_account_isolation_policy"]
        read = functions["read_account_isolation_policies"]

        with patch.dict(sys.modules, {"Py4GWCoreLib": runtime}):
            self.assertFalse(publish(False, force=True))
            self.assertEqual(read(), {OWNER: False})

            _Clock.value += 250
            self.assertTrue(publish(True))
            self.assertEqual(shmem.upsert_calls, 2)
            self.assertEqual(read(), {OWNER: True})
            self.assertEqual(
                int(accounts.Intents[0].ExpiresAtTick),
                (_Clock.value + 3000) & 0xFFFFFFFF,
            )

    def test_policy_heartbeat_keeps_kind_eleven_and_old_account_separate(self) -> None:
        accounts = _new_accounts()
        _seed_interrupt_intent(accounts, 1, owner_email=OTHER_OWNER, enemy_skill_id=OTHER_SKILL_ID)
        interrupt_before = (
            bool(accounts.Intents[1].Active),
            str(accounts.Intents[1].OwnerEmail),
            int(accounts.Intents[1].KindID),
            int(accounts.Intents[1].SkillID),
            int(accounts.Intents[1].TargetAgentID),
            int(accounts.Intents[1].IsolationGroupID),
        )
        owner = {"email": OWNER}
        functions, runtime = _policy_heartbeat_runtime(
            accounts,
            lambda: (str(owner["email"]), POLICY_GROUP),
        )
        publish = functions["publish_account_isolation_policy"]
        clear = functions["clear_account_isolation_policy"]
        read = functions["read_account_isolation_policies"]

        with patch.dict(sys.modules, {"Py4GWCoreLib": runtime}):
            self.assertTrue(publish(False))
            self.assertEqual(read(), {OWNER: False})
            self.assertTrue(clear())

            owner["email"] = OTHER_OWNER
            self.assertTrue(publish(True, force=True))
            self.assertEqual(read(), {OTHER_OWNER: True})

        interrupt_after = (
            bool(accounts.Intents[1].Active),
            str(accounts.Intents[1].OwnerEmail),
            int(accounts.Intents[1].KindID),
            int(accounts.Intents[1].SkillID),
            int(accounts.Intents[1].TargetAgentID),
            int(accounts.Intents[1].IsolationGroupID),
        )
        self.assertEqual(interrupt_after, interrupt_before)

    def test_policy_heartbeat_reader_expires_across_uint32_wrap(self) -> None:
        _Clock.value = 0xFFFFFFFE
        accounts = _new_accounts()
        _seed_policy_heartbeat(
            accounts,
            0,
            enabled=False,
            posted_at_tick=0xFFFFFFF0,
            expires_at_tick=0x00000020,
        )
        functions, runtime = _policy_heartbeat_runtime(accounts, lambda: (OWNER, POLICY_GROUP))
        read = functions["read_account_isolation_policies"]

        with patch.dict(sys.modules, {"Py4GWCoreLib": runtime}):
            self.assertEqual(read(), {OWNER: False})
            _Clock.value = 0x00000020
            self.assertEqual(read(), {})

    def test_disabled_policy_refresh_cannot_admit_peer_during_party_reconciliation(self) -> None:
        _Clock.value = NOW
        policy_accounts = _new_list_backed_accounts()
        enabled_email = "enabled@example.com"
        disabled_email = "disabled@example.com"
        _seed_policy_heartbeat(policy_accounts, 0, owner_email=enabled_email, enabled=True)
        _seed_policy_heartbeat(policy_accounts, 1, owner_email=disabled_email, enabled=False)

        enabled_account = _PartyAccount(enabled_email, group_id=101, party_id=42, isolated=True)
        disabled_account = _PartyAccount(disabled_email, group_id=0, party_id=42, isolated=False)
        shared_memory = _PartySharedMemory([enabled_account, disabled_account], policy_accounts)
        owner = {"email": disabled_email}
        policy_functions, runtime = _policy_heartbeat_runtime(
            policy_accounts,
            lambda: (str(owner["email"]), POLICY_GROUP),
        )
        read = policy_functions["read_account_isolation_policies"]
        observations: list[dict[str, bool]] = []

        with _loaded_policy_party_isolation(
            runtime,
            shared_memory,
            {disabled_email: 202},
            {202: "Manager preference"},
            disabled_email,
            policy_functions,
        ) as isolation:
            def reconcile_during_refresh() -> None:
                observations.append(dict(read()))
                isolation.sync_party_isolation_group(enabled_email, 101)

            policy_accounts.Intents[1] = _ObservingIntent(
                policy_accounts.Intents[1],
                reconcile_during_refresh,
            )
            self.assertTrue(policy_functions["publish_account_isolation_policy"](False, force=True))

        self.assertTrue(observations)
        self.assertTrue(all(policies.get(disabled_email) is False for policies in observations))
        self.assertEqual(shared_memory.group_writes, [])
        self.assertEqual(shared_memory.isolation_writes, [])
        self.assertEqual(disabled_account.IsolationGroupID, 0)
        self.assertFalse(disabled_account.IsIsolated)

    def test_all_direct_whiteboard_timestamp_readers_handle_wrap(self) -> None:
        intents: list[Any] = [INTENT_STRUCT() for _ in range(5)]
        _seed_intent(
            _accounts_for_intent_list(intents),
            0,
            kind_id=5,
            skill_id=0,
            target_agent_id=55,
            posted_at_tick=0xFFFFFFF0,
            expires_at_tick=0x00000020,
            owner_email="older@example.com",
        )
        _seed_intent(
            _accounts_for_intent_list(intents),
            1,
            kind_id=5,
            skill_id=0,
            target_agent_id=55,
            posted_at_tick=0xFFFFFFF5,
            expires_at_tick=0x00000020,
            owner_email="newer@example.com",
        )
        _seed_intent(
            _accounts_for_intent_list(intents),
            2,
            kind_id=5,
            skill_id=0,
            target_agent_id=55,
            posted_at_tick=0xFFFFFFF0,
            expires_at_tick=0xFFFFFFFE,
            owner_email="expired@example.com",
        )
        _seed_intent(
            _accounts_for_intent_list(intents),
            3,
            kind_id=14,
            skill_id=3,
            expires_at_tick=0x00000003,
            owner_email="expired-state@example.com",
        )
        _seed_intent(
            _accounts_for_intent_list(intents),
            4,
            kind_id=14,
            skill_id=3,
            expires_at_tick=0x00000020,
            owner_email="live-state@example.com",
        )
        shmem = _ReadOnlySharedMemory(intents)
        runtime = types.ModuleType("Py4GWCoreLib")
        setattr(runtime, "GLOBAL_CACHE", types.SimpleNamespace(ShMem=shmem))
        readers = WHITEBOARD_TIMESTAMP_CONSUMERS
        with patch.dict(sys.modules, {"Py4GWCoreLib": runtime}):
            self.assertEqual(readers["get_resurrection_lock_owner"](55, 5), ("older@example.com", 0))
            self.assertEqual(
                readers["read_resurrection_scroll_states"](),
                {"live-state@example.com": (True, True)},
            )
            self.assertEqual(readers["post_hex_removal_lock"](55), 17)
            self.assertEqual(readers["post_buff_target_lock"](55), 17)
            self.assertEqual(readers["post_loot_lock"](55), 17)
        self.assertEqual(len(shmem.posts), 3)


def _accounts_for_intent_list(intents: list[Any]) -> Any:
    class _AccountsView:
        Intents = intents

    return _AccountsView()


if __name__ == "__main__":
    if not _run_child_mode():
        unittest.main()
