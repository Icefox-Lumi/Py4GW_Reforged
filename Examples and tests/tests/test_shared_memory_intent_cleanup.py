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
import time
import types
import unittest
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

OWNER = "owner@example.com"
OTHER_OWNER = "other@example.com"
SKILL_ID = 123
OTHER_SKILL_ID = 456
TARGET_ID = 789
OTHER_TARGET_ID = 987
GROUP_ID = 4
OTHER_GROUP_ID = 5
SKILL_TARGET_KIND = 1
NOW = 0x1_0000_0100


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
    @staticmethod
    def get_tick_count64() -> int:
        return NOW


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


class _DummyStruct:
    def reset(self) -> None:
        pass


def _load_accounts_class(shared_memory_name: str) -> type[Any]:
    tree = ast.parse(ALL_ACCOUNTS_PATH.read_text(encoding="utf-8"))
    class_node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "AllAccounts")
    method_names = {
        "reset",
        "_wb_log",
        "_wb_kind_display",
        "_wb_mode_display",
        "_wb_key_display",
        "_wb_lock_display",
        "GetAllIntents",
        "_reset_intent_unlocked",
        "_clear_intent_unlocked",
        "_clear_intent_if_match_unlocked",
        "ClearIntent",
        "ClearIntentIfMatch",
        "ClearIntentsByOwner",
        "ClearLockByOwnerKindTarget",
        "PostLock",
        "CountLocks",
        "PostIntent",
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
        "SHMEM_MAX_INTENTS": INTENT_COUNT,
        "SHMEM_MAX_PLAYERS": 1,
        "SHMEM_SHARED_MEMORY_FILE_NAME": shared_memory_name,
        "WHITEBOARD_DEBUG": False,
        "ConsoleLog": lambda *_args: None,
        "SHMEM_MODULE_NAME": "test",
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
        setattr(self, "Keys", [_DummyStruct()])
        setattr(self, "AccountData", [_DummyStruct()])
        setattr(self, "Inbox", [_DummyStruct()])
        setattr(self, "HeroAIOptions", [_DummyStruct()])

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
_BUILD_MGR_POST = _load_method(BUILD_MGR_PATH, "BuildMgr", "_whiteboard_post_intent", {"PySystem": _Clock})
_BUILD_MGR_CLEAR = _load_method(BUILD_MGR_PATH, "BuildMgr", "_whiteboard_owner_self_clear")


def _new_accounts(shared_memory_name: str | None = None) -> Any:
    identity = shared_memory_name or f"Py4GW_IntentUnitTest_{uuid4().hex}"
    return _load_accounts_class(identity)(INTENT_ARRAY())


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


def _mutation_result(accounts: Any, operation: str, owner_email: str = OWNER, key_id: int = SKILL_ID) -> object:
    now = _Clock.get_tick_count64()
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
) -> None:
    from multiprocessing import shared_memory

    ready_handle = _open_named_event(ready_event_name)
    start_handle = _open_named_event(start_event_name)
    started_handle = _open_named_event(started_event_name)
    memory = shared_memory.SharedMemory(name=shared_memory_name)
    intents = INTENT_ARRAY.from_buffer(cast(Any, memory.buf))
    accounts = _load_accounts_class(mutex_identity)(intents)
    try:
        _test_kernel32.SetEvent(ready_handle)
        if int(_test_kernel32.WaitForSingleObject(start_handle, 5000)) != _WAIT_OBJECT_0:
            raise TimeoutError("parent did not release worker start gate")
        _test_kernel32.SetEvent(started_handle)
        result = _mutation_result(accounts, operation, owner_email, key_id)
        print(repr(result), flush=True)
    finally:
        del accounts
        del intents
        _close_shared_table(memory)
        _test_kernel32.CloseHandle(ready_handle)
        _test_kernel32.CloseHandle(start_handle)
        _test_kernel32.CloseHandle(started_handle)


def _run_child_mode() -> bool:
    if len(sys.argv) != 10 or sys.argv[1] != "--intent-worker":
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
) -> tuple[Any, _NamedEvent, _NamedEvent, _NamedEvent]:
    ready = _NamedEvent(_new_event_name())
    start = _NamedEvent(_new_event_name())
    started = _NamedEvent(_new_event_name())
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
        self.shared_memory_name = f"Py4GW_IntentTest_{uuid4().hex}"
        self.accounts = _new_accounts(self.shared_memory_name)

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
