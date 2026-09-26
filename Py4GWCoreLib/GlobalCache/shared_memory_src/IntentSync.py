"""Cross-process synchronization and uint32 tick helpers for whiteboard intents."""

from __future__ import annotations

import ctypes
import hashlib
import os
from contextlib import contextmanager
from typing import Any
from typing import Iterator

UINT32_MASK = 0xFFFFFFFF
UINT32_HALF_RANGE = 0x80000000
INTENT_MUTEX_TIMEOUT_MS = 1000

WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080

_kernel32: Any = None
if os.name == "nt":
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    _kernel32.CreateMutexW.restype = wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    _kernel32.ReleaseMutex.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL


def intent_mutex_name(shared_memory_name: str) -> str:
    """Return the stable Windows mutex name for one shared-memory identity."""
    identity_hash = hashlib.sha256(shared_memory_name.encode("utf-8")).hexdigest()[:32]
    return f"Local\\Py4GW.IntentTable.{identity_hash}"


@contextmanager
def intent_table_lock(
    shared_memory_name: str,
    timeout_ms: int = INTENT_MUTEX_TIMEOUT_MS,
) -> Iterator[bool]:
    """Acquire the shared Intent-table mutex, yielding False when unavailable."""
    if _kernel32 is None:
        yield False
        return

    handle = None
    acquired = False
    try:
        handle = _kernel32.CreateMutexW(None, False, intent_mutex_name(shared_memory_name))
        if handle:
            wait_result = int(_kernel32.WaitForSingleObject(handle, int(timeout_ms)))
            acquired = wait_result in (WAIT_OBJECT_0, WAIT_ABANDONED)
    except Exception:
        acquired = False

    if not acquired:
        if handle:
            try:
                _kernel32.CloseHandle(handle)
            except Exception:
                pass
        yield False
        return

    try:
        yield True
    finally:
        try:
            _kernel32.ReleaseMutex(handle)
        except Exception:
            pass
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            pass


def normalize_tick(value: int) -> int:
    """Normalize a millisecond tick to the IntentStruct uint32 representation."""
    return int(value) & UINT32_MASK


def tick_elapsed(now_tick: int, then_tick: int) -> int:
    """Return the modular uint32 age of a timestamp."""
    return (normalize_tick(now_tick) - normalize_tick(then_tick)) & UINT32_MASK


def tick_is_expired(now_tick: int, expires_at_tick: int) -> bool:
    """Treat deadlines at/past now, or outside the valid half-range, as expired."""
    remaining = (normalize_tick(expires_at_tick) - normalize_tick(now_tick)) & UINT32_MASK
    return remaining == 0 or remaining >= UINT32_HALF_RANGE


def is_valid_future_lease(now_tick: int, expires_at_tick: int) -> bool:
    """Validate a full-width deadline before storing it in the uint32 fields."""
    distance = int(expires_at_tick) - int(now_tick)
    return 0 < distance < UINT32_HALF_RANGE
