"""Temporary, bounded diagnostics for the Healing Burst dispatch investigation.

This module is intentionally observational. It owns no HeroAI decisions and is
safe to remove with the temporary HBS diagnostic pass.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import PySystem

TEMPORARY_HBS_OUTER_DIAGNOSTICS_ENABLED = True
_DIAGNOSTIC_MODULE_NAME = "HeroAIOuterDiag"
_DIAGNOSTIC_PREFIX = "[HBS-OUTER-DIAG]"
_DIAGNOSTIC_HEARTBEAT_MS = 1000

_active_owner = "unknown"
_last_state: dict[tuple[str, str], tuple[tuple[Any, ...], int]] = {}
_compact_last_state: dict[str, tuple[tuple[Any, ...], int]] = {}
_compact_counters: dict[str, dict[str, int]] = {}
_build_allowed: dict[tuple[str, str, str], bool] = {}


def _tick() -> int:
    try:
        return int(PySystem.get_tick_count64())
    except Exception:
        return 0


def _safe_label(value: Any) -> str:
    try:
        text = str(value)
    except Exception:
        return "unknown"
    cleaned = "".join(
        character if character.isalnum() or character in "_-." else "_"
        for character in text
    )
    return cleaned or "unknown"


def _format_value(value: Any) -> str:
    if value is None:
        return "?"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return f"{value:.1f}"
    if isinstance(value, (tuple, list)):
        return ",".join(_format_value(item) for item in value) or "none"
    return _safe_label(value)


def _emit(owner: str, kind: str, fields: dict[str, Any] | None = None) -> None:
    if not TEMPORARY_HBS_OUTER_DIAGNOSTICS_ENABLED:
        return
    values = [
        f"kind={_safe_label(kind)}",
        f"owner={_safe_label(owner)}",
        f"tick={_tick()}",
    ]
    for key, value in (fields or {}).items():
        values.append(f"{_safe_label(key)}={_format_value(value)}")
    message = f"{_DIAGNOSTIC_PREFIX} " + " ".join(values)
    try:
        PySystem.Console.Log(
            _DIAGNOSTIC_MODULE_NAME,
            message,
            PySystem.Console.MessageType.Info,
        )
    except Exception:
        try:
            print(message)
        except Exception:
            pass


def set_active_owner(owner: str) -> None:
    """Record which HeroAI owner is currently driving this client."""
    global _active_owner
    normalized_owner = _safe_label(owner)
    if normalized_owner == _active_owner:
        return
    previous_owner = _active_owner
    _active_owner = normalized_owner
    log_event(
        normalized_owner,
        "owner_active",
        {"previous_owner": previous_owner},
    )


def get_active_owner() -> str:
    return _active_owner


def state_signature(fields: dict[str, Any]) -> tuple[Any, ...]:
    """Create a stable, compact signature for bounded state-change logging."""
    signature: list[Any] = []
    for key in sorted(fields):
        value = fields[key]
        if isinstance(value, float):
            value = round(value, 1) if math.isfinite(value) else _format_value(value)
        elif isinstance(value, list):
            value = tuple(value)
        signature.append((key, value))
    return tuple(signature)


def log_event(
    owner: str,
    kind: str,
    fields: dict[str, Any] | None = None,
) -> None:
    """Emit an event without deduplicating it."""
    _emit(owner, kind, fields)


def log_state(
    owner: str,
    kind: str,
    signature: tuple[Any, ...],
    fields: dict[str, Any] | None = None,
    *,
    heartbeat: bool = True,
) -> None:
    """Emit on state changes and, optionally, at a one-second heartbeat."""
    if not TEMPORARY_HBS_OUTER_DIAGNOSTICS_ENABLED:
        return
    normalized_owner = _safe_label(owner)
    key = (normalized_owner, _safe_label(kind))
    now = _tick()
    previous = _last_state.get(key)
    changed = previous is None or previous[0] != signature
    heartbeat_due = (
        heartbeat
        and previous is not None
        and now - previous[1] >= _DIAGNOSTIC_HEARTBEAT_MS
    )
    if not changed and not heartbeat_due:
        return
    _last_state[key] = (signature, now)
    _emit(normalized_owner, kind, fields)


def increment_counter(owner: str, name: str, amount: int = 1) -> None:
    if not TEMPORARY_HBS_OUTER_DIAGNOSTICS_ENABLED or amount <= 0:
        return
    normalized_owner = _safe_label(owner)
    counters = _compact_counters.setdefault(normalized_owner, {})
    normalized_name = _safe_label(name)
    counters[normalized_name] = counters.get(normalized_name, 0) + int(amount)


def log_compact_state(
    owner: str,
    fields: dict[str, Any],
    *,
    semantic_fields: dict[str, Any] | None = None,
    interesting: bool = False,
    force: bool = False,
) -> bool:
    """Emit a semantic state line and sparse heartbeat with a full summary."""
    if not TEMPORARY_HBS_OUTER_DIAGNOSTICS_ENABLED:
        return False
    normalized_owner = _safe_label(owner)
    now = _tick()
    signature = state_signature(fields if semantic_fields is None else semantic_fields)
    previous = _compact_last_state.get(normalized_owner)
    changed = previous is None or previous[0] != signature
    heartbeat_due = (
        interesting
        and previous is not None
        and now - previous[1] >= _DIAGNOSTIC_HEARTBEAT_MS
    )
    if not force and not changed and not heartbeat_due:
        return False

    emitted_fields = dict(fields)
    emitted_fields["event"] = "state_change" if changed else "heartbeat"
    counters = _compact_counters.get(normalized_owner, {})
    for counter_name, count in counters.items():
        if count:
            emitted_fields[f"count_{counter_name}"] = count
    _compact_counters[normalized_owner] = {}
    _compact_last_state[normalized_owner] = (signature, now)
    _emit(normalized_owner, "compact", emitted_fields)
    return True


def observe_build_process(
    owner: str,
    build: str,
    phase: str,
    allowed: bool,
    capture_state: Callable[[], dict[str, Any]],
) -> None:
    """Capture expensive gate fields only on rejection/recovery transitions."""
    if not TEMPORARY_HBS_OUTER_DIAGNOSTICS_ENABLED:
        return
    normalized_owner = _safe_label(owner)
    key = (normalized_owner, _safe_label(build), _safe_label(phase))
    previous = _build_allowed.get(key)
    current = bool(allowed)
    _build_allowed[key] = current
    if not current:
        increment_counter(normalized_owner, "build_rejections")
    if current == previous or (current and previous is None):
        return
    fields = {
        "build": build,
        "phase": phase,
        "allowed": current,
    }
    try:
        fields.update(capture_state())
    except Exception:
        fields["capture_error"] = True
    _emit(normalized_owner, "build_can_process", fields)


def cached_state_fields(cached_data: Any) -> dict[str, Any]:
    data = getattr(cached_data, "data", None)
    options = getattr(cached_data, "account_options", None)
    return {
        "in_aggro": getattr(data, "in_aggro", None),
        "local_aggro": getattr(data, "local_in_aggro", None),
        "party_aggro": getattr(data, "party_in_aggro", None),
        "leader_aggro": getattr(data, "leader_in_aggro", None),
        "is_leader": getattr(data, "is_leader", None),
        "following": getattr(options, "Following", None),
        "combat_enabled": getattr(options, "Combat", None),
    }


def node_state(value: Any) -> str:
    try:
        return str(getattr(value, "name", value)).lower()
    except Exception:
        return "unknown"


__all__ = [
    "TEMPORARY_HBS_OUTER_DIAGNOSTICS_ENABLED",
    "cached_state_fields",
    "get_active_owner",
    "increment_counter",
    "log_compact_state",
    "log_event",
    "log_state",
    "node_state",
    "observe_build_process",
    "set_active_owner",
    "state_signature",
]
