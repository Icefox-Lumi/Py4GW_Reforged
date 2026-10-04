# pyright: reportMissingImports=false
"""Offline tests for the common hex-removal claim against the real Intent mutex."""

from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
import threading
import types
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Any

import pytest

_MISSING = object()
_TEST_SHARED_MEMORY_NAME = "Py4GW.SmartShatterHex.AtomicClaimRegression"


def _load_all_accounts() -> tuple[types.ModuleType, type[Any]]:
    package_names = (
        "Py4GWCoreLib",
        "Py4GWCoreLib.enums_src",
        "Py4GWCoreLib.GlobalCache",
        "Py4GWCoreLib.GlobalCache.shared_memory_src",
        "Py4GWCoreLib.py4gwcorelib_src",
    )
    stub_modules: dict[str, types.ModuleType] = {}
    for package_name in package_names:
        package = types.ModuleType(package_name)
        package.__path__ = []
        stub_modules[package_name] = package

    class _SimpleStruct(ctypes.Structure):
        pass

    setattr(_SimpleStruct, "_fields_", [])

    class _AccountStruct(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("AccountEmail", ctypes.c_wchar * 64),
            ("IsAccount", ctypes.c_bool),
            ("IsolationGroupID", ctypes.c_uint),
        ]

    class _UnusedPartyType:
        pass

    class _WhiteboardLockKind(IntEnum):
        SKILL_TARGET = 1
        HEX_REMOVAL_TARGET = 13
        INTERRUPT_TARGET = 11

    class _WhiteboardLockMode(IntEnum):
        EXCLUSIVE = 1
        SHARED = 2

    class _WhiteboardReentryPolicy(IntEnum):
        OWNER_REENTRANT = 1
        NON_REENTRANT = 2

    class _WhiteboardClaimStrength(IntEnum):
        HARD = 1
        SOFT = 2

    class _SharedCommandType(IntEnum):
        NOOP = 0

    whiteboard_enums = types.ModuleType("Py4GWCoreLib.enums_src.Whiteboard_enums")
    whiteboard_enums.__dict__.update(
        WhiteboardLockKind=_WhiteboardLockKind,
        WhiteboardLockMode=_WhiteboardLockMode,
        WhiteboardReentryPolicy=_WhiteboardReentryPolicy,
        WhiteboardClaimStrength=_WhiteboardClaimStrength,
    )
    stub_modules[whiteboard_enums.__name__] = whiteboard_enums
    multi_enums = types.ModuleType("Py4GWCoreLib.enums_src.Multiboxing_enums")
    multi_enums.__dict__["SharedCommandType"] = _SharedCommandType
    stub_modules[multi_enums.__name__] = multi_enums

    globals_module = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.Globals")
    globals_module.__dict__.update(
        SHMEM_MAX_PLAYERS=4,
        SHMEM_MAX_INTENTS=8,
        SHMEM_MAX_EMAIL_LEN=64,
        SHMEM_MAX_CHAR_LEN=64,
        SHMEM_MAX_NUMBER_OF_SKILLS=8,
        SHMEM_MODULE_NAME="Py4GW test",
        SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS=5000,
        SHMEM_PLAYER_META_UPDATE_THROTTLE_MS=1,
        SHMEM_PLAYER_PROGRESS_UPDATE_THROTTLE_MS=1,
        SHMEM_PLAYER_STATIC_UPDATE_THROTTLE_MS=1,
        SHMEM_PLAYER_INVENTORY_UPDATE_THROTTLE_MS=1,
        SHMEM_HERO_EXTRA_UPDATE_THROTTLE_MS=1,
        SHMEM_PET_EXTRA_UPDATE_THROTTLE_MS=1,
        SHMEM_SHARED_MEMORY_FILE_NAME=_TEST_SHARED_MEMORY_NAME,
    )
    stub_modules[globals_module.__name__] = globals_module

    account_struct_module = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.AccountStruct")
    account_struct_module.__dict__["AccountStruct"] = _AccountStruct
    stub_modules[account_struct_module.__name__] = account_struct_module

    simple_structs = {
        "KeyStruct": "KeyStruct",
        "SharedMessageStruct": "SharedMessageStruct",
        "HeroAIOptionStruct": "HeroAIOptionStruct",
    }
    for module_leaf, class_name in simple_structs.items():
        module = types.ModuleType(f"Py4GWCoreLib.GlobalCache.shared_memory_src.{module_leaf}")
        setattr(module, class_name, _SimpleStruct)
        stub_modules[module.__name__] = module

    system_module = types.ModuleType("PySystem")
    system_module.__dict__.update(
        get_tick_count64=lambda: 10000,
        Console=types.SimpleNamespace(
            MessageType=types.SimpleNamespace(Info=1, Warning=2, Error=3),
            Log=lambda *args, **kwargs: None,
            get_gw_window_handle=lambda: 0,
        ),
    )
    stub_modules["PySystem"] = system_module
    party_module = types.ModuleType("PyParty")
    party_module.__dict__.update(HeroPartyMember=_UnusedPartyType, PetInfo=_UnusedPartyType)
    stub_modules["PyParty"] = party_module
    console_module = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.Console")
    console_module.__dict__["ConsoleLog"] = lambda *args, **kwargs: None
    stub_modules[console_module.__name__] = console_module
    corelib = stub_modules["Py4GWCoreLib"]
    corelib.__dict__["ThrottledTimer"] = object

    original_modules = {name: sys.modules.get(name, _MISSING) for name in stub_modules}
    sys.modules.update(stub_modules)
    module_names = (
        "Py4GWCoreLib.GlobalCache.shared_memory_src.IntentStruct",
        "Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync",
        "Py4GWCoreLib.GlobalCache.shared_memory_src.AllAccounts",
    )
    originals = {name: sys.modules.get(name, _MISSING) for name in module_names}
    try:
        root = Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src"
        loaded: dict[str, types.ModuleType] = {}
        for leaf in ("IntentStruct", "IntentSync", "AllAccounts"):
            name = f"Py4GWCoreLib.GlobalCache.shared_memory_src.{leaf}"
            spec = importlib.util.spec_from_file_location(name, root / f"{leaf}.py")
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load {root / f'{leaf}.py'}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded[leaf] = module
        # AllAccounts imports IntentStruct through its package; the other stub types are
        # deliberately tiny because the tests exercise only its hex-claim methods.
        account_class = loaded["AllAccounts"].AllAccounts
        return loaded["AllAccounts"], account_class
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                assert isinstance(original, types.ModuleType)
                sys.modules[name] = original
        for name, original in original_modules.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                assert isinstance(original, types.ModuleType)
                sys.modules[name] = original


ALL_ACCOUNTS_MODULE, AllAccounts = _load_all_accounts()


def _new_table(*owners: tuple[str, int]) -> Any:
    table = AllAccounts()
    for index, (email, group_id) in enumerate(owners):
        account = table.AccountData[index]
        account.AccountEmail = email
        account.IsAccount = True
        account.IsolationGroupID = group_id
    return table


def _set_tick(monkeypatch: pytest.MonkeyPatch, tick: int) -> None:
    monkeypatch.setattr(ALL_ACCOUNTS_MODULE, "get_uncached_tick_count64", lambda: tick)


def test_same_owner_and_other_owner_cannot_reenter_same_target(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 10000)
    table = _new_table(("one@example.test", 7), ("two@example.test", 7))

    first = table.TryAcquireHexRemovalTarget("one@example.test", 501, 3000, 7)
    same_owner = table.TryAcquireHexRemovalTarget("one@example.test", 501, 3000, 7)
    other_owner = table.TryAcquireHexRemovalTarget("two@example.test", 501, 3000, 7)

    assert first.token is not None
    assert same_owner.token is None and same_owner.reason == "conflict"
    assert other_owner.token is None and other_owner.reason == "conflict"


def test_common_key_zero_scope_ignores_removal_skill_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 20000)
    table = _new_table(("one@example.test", 3), ("two@example.test", 3))

    first = table.TryAcquireHexRemovalTarget("one@example.test", 502, 3000, 3)
    second = table.TryAcquireHexRemovalTarget("two@example.test", 502, 4000, 3)

    assert first.token is not None and first.token.key_id == 0
    assert second.token is None


def test_missing_identity_invalid_group_scope_and_mutex_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 30000)
    table = _new_table(("one@example.test", 3))

    assert table.TryAcquireHexRemovalTarget("", 503, 3000, 3).token is None
    assert table.TryAcquireHexRemovalTarget("missing@example.test", 503, 3000, 3).token is None
    assert table.TryAcquireHexRemovalTarget("one@example.test", 503, 3000, 4).reason == "group_mismatch"

    @contextmanager
    def unavailable_mutex(*args: Any, **kwargs: Any):
        yield False

    monkeypatch.setattr(ALL_ACCOUNTS_MODULE, "intent_table_lock", unavailable_mutex)
    result = table.TryAcquireHexRemovalTarget("one@example.test", 503, 3000, 3)
    assert result.token is None and result.reason == "mutex_unavailable"


def test_expired_claim_is_reclaimed_and_stale_token_cannot_release_or_renew(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 40000)
    table = _new_table(("one@example.test", 5), ("two@example.test", 5))
    for intent in table.Intents[1:]:
        intent.Active = True
        intent.OwnerEmail = "other@example.test"
        intent.KindID = 1
        intent.SkillID = 1
        intent.TargetAgentID = 1
        intent.IsolationGroupID = 5
        intent.LockMode = 1
        intent.MaxHolders = 1
        intent.ReentryPolicy = 1
        intent.ClaimStrength = 1
        intent.PostedAtTick = 40000
        intent.ExpiresAtTick = 50000
    first = table.TryAcquireHexRemovalTarget("one@example.test", 504, 1000, 5).token
    assert first is not None

    _set_tick(monkeypatch, first.expires_at_tick64)
    replacement = table.TryAcquireHexRemovalTarget("two@example.test", 504, 1000, 5).token

    assert replacement is not None
    assert replacement.intent_slot_index == first.intent_slot_index
    assert not table.ReleaseHexRemovalClaim(first)
    assert table.RenewHexRemovalClaim(first, 2000).token is None
    assert table.IsHexRemovalClaimOwned(replacement)


def test_renewal_changes_exact_expiry_identity_and_stale_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 50000)
    table = _new_table(("one@example.test", 6))
    token = table.TryAcquireHexRemovalTarget("one@example.test", 505, 1500, 6).token
    assert token is not None

    renewed = table.RenewHexRemovalClaim(token, 2500).token

    assert renewed is not None and renewed.expires_at_tick64 == 52500
    assert not table.IsHexRemovalClaimOwned(token)
    assert table.IsHexRemovalClaimOwned(renewed)
    assert not table.ReleaseHexRemovalClaim(token)
    assert table.ReleaseHexRemovalClaim(renewed)


def test_same_tick_republication_rejects_stale_same_owner_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 55000)
    table = _new_table(("one@example.test", 6))
    original = table.TryAcquireHexRemovalTarget("one@example.test", 505, 1500, 6).token
    assert original is not None
    assert table.ReleaseHexRemovalClaim(original)

    replacement = table.TryAcquireHexRemovalTarget("one@example.test", 505, 1500, 6).token

    assert replacement is not None
    assert replacement.intent_slot_index == original.intent_slot_index
    assert replacement.posted_at_tick64 == original.posted_at_tick64
    assert replacement.expires_at_tick64 == original.expires_at_tick64
    assert replacement.local_generation != original.local_generation
    assert not table.ReleaseHexRemovalClaim(original)
    assert table.IsHexRemovalClaimOwned(replacement)


def test_uint32_tick_wrap_keeps_a_short_claim_live_until_its_wrapped_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    start = 0xFFFFFFFE
    _set_tick(monkeypatch, start)
    table = _new_table(("one@example.test", 9))
    token = table.TryAcquireHexRemovalTarget("one@example.test", 506, 4, 9).token
    assert token is not None
    assert token.expires_at_tick64 == 0x100000002

    _set_tick(monkeypatch, 0xFFFFFFFF)
    assert table.IsHexRemovalClaimOwned(token)
    _set_tick(monkeypatch, 0x100000002)
    assert not table.IsHexRemovalClaimOwned(token)


def test_full_intent_table_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 60000)
    table = _new_table(("one@example.test", 10))
    for intent in table.Intents:
        intent.Active = True
        intent.OwnerEmail = "other@example.test"
        intent.KindID = 1
        intent.SkillID = 1
        intent.TargetAgentID = 1
        intent.IsolationGroupID = 10
        intent.LockMode = 1
        intent.MaxHolders = 1
        intent.ReentryPolicy = 1
        intent.ClaimStrength = 1
        intent.PostedAtTick = 60000
        intent.ExpiresAtTick = 70000

    result = table.TryAcquireHexRemovalTarget("one@example.test", 507, 3000, 10)

    assert result.token is None and result.reason == "table_full"


def _thread_claim_worker(
    table: Any,
    owner_email: str,
    start_barrier: threading.Barrier,
    results: list[bool],
    results_lock: Any,
) -> None:
    start_barrier.wait(timeout=10)
    result = table.TryAcquireHexRemovalTarget(owner_email, 508, 3000, 11)
    with results_lock:
        results.append(result.token is not None)


@pytest.mark.skipif(os.name != "nt", reason="requires the repository's Windows named Intent mutex")
def test_two_concurrent_claim_attempts_share_one_atomic_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_tick(monkeypatch, 70000)
    table = _new_table(("one@example.test", 11), ("two@example.test", 11))
    barrier = threading.Barrier(2)
    results: list[bool] = []
    results_lock = threading.Lock()
    threads = [
        threading.Thread(
            target=_thread_claim_worker,
            args=(table, email, barrier, results, results_lock),
        )
        for email in ("one@example.test", "two@example.test")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(results) == 1
