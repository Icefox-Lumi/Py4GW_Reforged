"""Bounded, passive Smart Shatter capture. Game queries belong to the Draw widget.

This module is imported by its canonical package name by both owners. No runtime
imports, configuration getters, game queries, or console writes occur here.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from threading import RLock
from typing import Any
from typing import Literal
from typing import cast

DURATION_MS = 30_000
SAMPLE_MS = 500
CONTEXT_GAP_MS = 750
MAX_SAMPLES = 60
MAX_QUERIES = 672
MAX_ROSTER = 12
MAX_EFFECTS = 64
MAX_CANDIDATES = 32
MAX_ATTEMPTS = 8
MAX_STAGES = 10
MAX_HOOKS = 32_768
MAX_RECORDS = 72
MAX_LINE_BYTES = 1536
MAX_STATE_BYTES = 512 * 1024
VOCAL_MINORITY = 883
HEROIC_REFRAIN = 3431

Mode = Literal["owner", "mesmer"]
Row = dict[str, Any]
Scalar = str | int | float | bool | None
_PLAYER_LABELS = tuple("P" + str(i) for i in range(1, 13))
_LOCAL_LABELS = tuple("L" + str(i) for i in range(1, 33))
_SCHEDULER_REASONS = frozenset(
    (
        "entry",
        "disposed",
        "dispatch_barrier",
        "process_gate",
        "process_exception",
        "coordinator_handled",
        "interrupt_handled",
        "energy_handled",
        "residual_handled",
        "offered",
        "handler_exception",
        "fallback",
        "idle",
        "lifecycle_exception",
    )
)


@dataclass(frozen=True, slots=True)
class ContextSample:
    map_id: int
    region: int
    district: int
    language: int
    uptime_ms: int
    player_id: int
    party_id: int
    roster: tuple[int, ...]
    watched_id: int

    def identity(self) -> tuple[object, ...]:
        return (
            self.map_id,
            self.region,
            self.district,
            self.language,
            self.player_id,
            self.party_id,
            self.roster,
            self.watched_id,
        )


@dataclass(frozen=True, slots=True)
class SnapshotTicket:
    epoch: object
    index: int
    phase: int = 0  # 0: decision bucket; 1/2: attempt pre-send/execution


@dataclass(slots=True)
class _Capture:
    epoch: object
    mode: Mode
    label: str
    clock: Callable[[], int]
    start: int
    last_now: int
    last_sample: int
    context: ContextSample
    actors: dict[int, str]
    actor: str
    watched: str
    fingerprint: str
    active: bool = True
    reason: str = "active"
    uncertain_after: int | None = None
    samples: int = 1
    last_opportunity: int = 0
    queries: int = 0
    query_count_upper_bound: bool = False
    hooks: int = 0
    skipped_detail: int = 0
    missed_samples: int = 0
    incomplete_inputs: int = 0
    suppressed: int = 0
    overflow: int = 0
    owner_positive: bool = False
    owner_sampled_at: int | None = None
    snapshot_reads: int = 0
    scheduler: dict[int, Row] = field(default_factory=dict[int, Row])
    decisions: dict[int, Row] = field(default_factory=dict[int, Row])
    tickets: dict[int, SnapshotTicket] = field(default_factory=dict[int, SnapshotTicket])
    attempts: list[Row] = field(default_factory=list[Row])
    revalidation_tickets: dict[tuple[int, int], SnapshotTicket] = field(
        default_factory=dict[tuple[int, int], SnapshotTicket]
    )
    owner_rows: list[Row] = field(default_factory=list[Row])
    locals: dict[int, str] = field(default_factory=dict[int, str])
    composition: tuple[object, ...] | None = None
    lifecycle: tuple[object, ...] | None = None
    profile_seen: bool = False
    profile: tuple[str, str] | None = None
    profile_generation: int | None = None
    emitted: int = 0
    output_index: int = 0
    output_done: bool = False
    formatting_failed: bool = False


# An in-place reload seals the previous capture and preserves its bounded output.
# Old callbacks carry only its epoch, never a reference to a new capture.
_lock = globals().get("_lock") or RLock()
_capture = cast(_Capture | None, globals().get("_capture"))
if _capture is not None and _capture.active:
    _capture.active = False
    _capture.reason = "reloaded"
    _capture.uncertain_after = _capture.last_sample


def _seal(capture: _Capture, reason: str, *, uncertain: bool = False) -> None:
    if capture.active:
        capture.active = False
        capture.reason = reason
        if uncertain:
            capture.uncertain_after = capture.last_sample


def _failed() -> None:
    # This recovery path neither formats nor calls a clock or a production owner.
    if _capture is not None:
        _capture.active = False
        _capture.reason = "diagnostic_failure"
        _capture.uncertain_after = _capture.last_sample


def _current(epoch: object | None, *, hook: bool = True) -> _Capture | None:
    capture = _capture
    if capture is None or not capture.active or epoch is not capture.epoch:
        return None
    if hook:
        if capture.hooks >= MAX_HOOKS:
            capture.overflow += 1
            _seal(capture, "hook_limit")
            return None
        capture.hooks += 1
    now = capture.clock()
    if type(now) is not int or not 0 <= now < (1 << 64) or now < capture.last_now:
        _seal(capture, "clock_invalid", uncertain=True)
        return None
    capture.last_now = now
    # A long Draw pause must not be disguised as a normally completed capture.
    if now - capture.last_sample > CONTEXT_GAP_MS:
        capture.missed_samples += max(1, (now - capture.last_sample) // SAMPLE_MS - 1)
        _seal(capture, "context_gap", uncertain=True)
        return None
    if now - capture.start >= DURATION_MS:
        # Completion does not validate the interval after the last Draw sample.
        _seal(capture, "completed", uncertain=True)
        return None
    return capture


def _number(value: object) -> int | float | None:
    if type(value) is int and -(1 << 63) <= value < (1 << 63):
        return value
    if type(value) is float and math.isfinite(value) and abs(value) <= 1e100:
        return value
    return None


def _type_name(value: object) -> str:
    # Identity comparisons only: even type.__getattribute__ can run metaclass descriptors.
    value_type = type(value)
    for known_type, label in (
        (int, "int"),
        (float, "float"),
        (Exception, "Exception"),
        (RuntimeError, "RuntimeError"),
        (ValueError, "ValueError"),
        (TypeError, "TypeError"),
        (OSError, "OSError"),
        (OverflowError, "OverflowError"),
        (MemoryError, "MemoryError"),
    ):
        if value_type is known_type:
            return label
    return "unexpected_type"


def _binding(value: object) -> tuple[str, Scalar]:
    if value is None:
        return "NoneType", None
    if type(value) is bool:
        return "bool", value
    number = _number(value)
    if number is not None:
        return "int" if type(value) is int else "float", number
    return _type_name(value), "value_not_retained"


def _target(capture: _Capture, agent_id: int) -> str:
    if agent_id in capture.actors:
        return capture.actors[agent_id]
    if agent_id in capture.locals:
        return capture.locals[agent_id]
    if len(capture.locals) < len(_LOCAL_LABELS):
        label = _LOCAL_LABELS[len(capture.locals)]
        capture.locals[agent_id] = label
        return label
    return "local_unlabelled"


def _candidate(capture: _Capture, candidate: Any) -> list[object]:
    return [
        _target(capture, candidate.target_agent_id),
        candidate.reason.value,
        _number(candidate.cleanse_priority),
        _number(candidate.useful_splash_damage),
        _number(candidate.ally_health_fraction),
        _number(candidate.caster_distance_squared),
    ]


def _snapshot(capture: _Capture, ticket: SnapshotTicket | None) -> Row | None:
    if ticket is None or ticket.epoch is not capture.epoch:
        return None
    if ticket.phase == 0:
        if capture.tickets.get(ticket.index) is ticket:
            return capture.decisions.get(ticket.index)
    elif capture.revalidation_tickets.get((ticket.index, ticket.phase)) is ticket:
        return cast(Row, capture.attempts[ticket.index]["pre" if ticket.phase == 1 else "exec"])
    return None


def _new_snapshot(now: int) -> Row:
    return {"t": now, "input": "not_observed", "vm_priority": "not_evaluated", "profile": "not_observed"}


def _copy_effects(capture: _Capture, row: Row, effects: Any, *, owner: bool) -> None:
    if not owner:
        if row["input"] != "not_observed":
            capture.incomplete_inputs += 1
            return
        if capture.snapshot_reads >= 46:
            capture.overflow += 1
            _seal(capture, "snapshot_limit")
            return
        capture.snapshot_reads += 1
    count = len(effects)
    inspected = min(count, MAX_EFFECTS)
    vm = 0
    hr = False
    low: int | float | None = None
    high: int | float | None = None
    unknown = 0
    for index in range(inspected):
        effect = effects[index]
        skill_id = effect.skill_id
        if owner and skill_id == HEROIC_REFRAIN:
            hr = True
        if skill_id != VOCAL_MINORITY:
            continue
        vm += 1
        remaining = _number(effect.time_remaining if owner else effect.remaining_ms)
        if remaining is None:
            unknown += 1
        else:
            low = remaining if low is None else min(low, remaining)
            high = remaining if high is None else max(high, remaining)
    complete = count <= MAX_EFFECTS
    row.update(
        input="available_input_inspected" if complete else "input_truncated",
        n=count,
        vm=["present" if vm else "absent_in_input" if complete else "unknown", vm, low, high, unknown],
    )
    if not complete:
        capture.incomplete_inputs += 1
    if owner:
        row["hr"] = "present" if hr else "absent_in_input" if complete else "unknown"
        capture.owner_positive |= vm > 0


def _classification(capture: _Capture, row: Row, priority: int, agent_id: int) -> None:
    row["vm_priority"] = _number(priority)
    module = sys.modules.get("Py4GWCoreLib.GlobalCache.HexRemovalPriority")
    if module is None:
        row["profile"] = "unavailable"
        return
    values = vars(module)
    identity: object = values.get("_resolved_profile_identity")
    generation = values.get("_priority_cache_generation")
    parts = cast(tuple[object, ...], identity) if type(identity) is tuple else ()
    if identity is not None and not (len(parts) == 2 and all(type(part) is str and len(part) <= 320 for part in parts)):
        row["profile"] = "unavailable"
        capture.incomplete_inputs += 1
        return
    copied_identity = cast(tuple[str, str] | None, identity)
    copied_generation = generation if type(generation) is int and 0 <= generation < (1 << 63) else None
    if capture.profile_seen and (capture.profile != copied_identity or capture.profile_generation != copied_generation):
        _seal(capture, "profile_changed", uncertain=True)
        return
    capture.profile_seen = True
    capture.profile = copied_identity
    capture.profile_generation = copied_generation
    row["profile"] = "profile1" if identity is not None else "unresolved"
    row["cache"] = copied_generation
    built = values.get("_HEX_REMOVAL_PRIORITY_BUILT")
    row["cache_built"] = built if type(built) is bool else None
    role_cache = values.get("_role_cache")
    cached: object = cast(dict[int, object], role_cache).get(agent_id) if type(role_cache) is dict else None
    cached_parts = cast(tuple[Any, ...], cached) if type(cached) is tuple else ()
    if len(cached_parts) == 2:
        role: Any = cached_parts[0].value
        row["role"] = role if type(role) is str and len(role) <= 16 else _number(role)
        row["profession"] = _number(cached_parts[1])


def scheduler_entry() -> object | None:
    try:
        with _lock:
            capture = _capture
            if capture is None or capture.mode != "mesmer":
                return None
            if _current(capture.epoch) is None:
                return None
            _scheduler(capture, "entry", None, False)
            return capture.epoch
    except Exception:
        _failed()
        return None


def _scheduler(capture: _Capture, reason: str, skill_id: int | None, offered: bool) -> None:
    if reason not in _SCHEDULER_REASONS:
        return
    bucket = (capture.last_now - capture.start) // 1000
    row = capture.scheduler.setdefault(bucket, {"kind": "SCH", "t": capture.last_now, "counts": {}})
    row["last"] = capture.last_now
    counts = cast(dict[str, int], row["counts"])
    if reason in counts:
        capture.suppressed += 1
    counts[reason] = counts.get(reason, 0) + 1
    if reason not in ("entry", "offered", "lifecycle_exception", "handler_exception"):
        key = "offered_pass" if offered else "not_offered"
        counts[key] = counts.get(key, 0) + 1
    if skill_id is not None:
        row["last_handler"] = _number(skill_id)


def scheduler(epoch: object | None, reason: str, skill_id: int | None = None, offered: bool = False) -> None:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is not None:
                _scheduler(capture, reason, skill_id, offered)
    except Exception:
        _failed()


def composition(epoch: object | None, generation: int, bar: tuple[int, ...] | None, slot: int | None) -> None:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is None:
                return
            if bar is not None and len(bar) > 8:
                _seal(capture, "composition_invalid", uncertain=True)
                return
            value = (generation, bar, slot)
            if capture.composition is not None and capture.composition != value:
                _seal(capture, "composition_changed", uncertain=True)
                return
            capture.composition = value
            bucket = (capture.last_now - capture.start) // 1000
            row = capture.scheduler.get(bucket)
            if row is not None:
                row["composition"] = generation
                row["shatter_slot"] = slot
    except Exception:
        _failed()


def offer(epoch: object | None, handler: Any) -> None:
    try:
        # Carries even a None/stale scheduler token; never adopt the current Arm.
        handler._shatter_observation_epoch = epoch
        scheduler(epoch, "offered", 67, True)
    except Exception:
        _failed()


def begin_evaluation(epoch: object | None) -> SnapshotTicket | None:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is None:
                return None
            bucket = (capture.last_now - capture.start) // 1000
            if capture.decisions.get(bucket, {}).get("evaluated"):
                capture.skipped_detail += 1
                return None
            ticket = SnapshotTicket(capture.epoch, bucket)
            capture.tickets[bucket] = ticket
            capture.decisions[bucket] = _new_snapshot(capture.last_now)
            return ticket
    except Exception:
        _failed()
        return None


def snapshot_event(ticket: SnapshotTicket | None, event: str, first: Any = None, second: Any = None) -> None:
    try:
        if ticket is None:
            return
        with _lock:
            capture = _current(ticket.epoch)
            if capture is None or (row := _snapshot(capture, ticket)) is None:
                return
            if event in ("effects", "summary", "classification", "classification_error"):
                if first != capture.context.watched_id:
                    return
                if event == "effects":
                    _copy_effects(capture, row, second, owner=False)
                elif event == "summary":
                    row["summary"] = [second.confirmed_hex_count, second.retained_hex_count, second.priority]
                elif event == "classification":
                    _classification(capture, row, second, first)
                else:
                    row["vm_priority"] = "classification_exception"
            elif event == "decision":
                row["evaluated"] = True
                row["reason"] = first.reason.value
                row["first"] = None if first.selected is None else _candidate(capture, first.selected)
                row["hr"] = "not_in_inspected_candidates"
                count = len(first.candidates)
                row["candidates_complete"] = count <= MAX_CANDIDATES
                if count > MAX_CANDIDATES:
                    capture.incomplete_inputs += 1
                    row["hr"] = "unknown_truncated"
                for index in range(min(count, MAX_CANDIDATES)):
                    candidate = first.candidates[index]
                    if candidate.target_agent_id == capture.context.watched_id:
                        row["hr"] = _candidate(capture, candidate)
                        row["hr_index"] = index
                        break
            elif event == "claim":
                target, acquired = first, second
                result = "acquired" if acquired else "claim_unavailable"
                if not row.get("claims_observed", 0):
                    row["first_claim"] = result
                row["claims_observed"] = row.get("claims_observed", 0) + 1
                row["claims_unavailable"] = row.get("claims_unavailable", 0) + int(not acquired)
                if target == capture.context.watched_id:
                    row["hr_claim"] = result
                if acquired:
                    row["chosen"] = _target(capture, target)
    except Exception:
        _failed()


def gate(epoch: object | None, reason: str) -> None:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is not None:
                bucket = (capture.last_now - capture.start) // 1000
                row = capture.scheduler.setdefault(bucket, {"kind": "SCH", "t": capture.last_now, "counts": {}})
                # Fixed stage names supplied only by the Shatter owner.
                if reason in (
                    "active_or_disposed",
                    "composition",
                    "runtime",
                    "slot_or_readiness",
                    "parameters",
                    "snapshot",
                    "lifecycle",
                    "no_candidates",
                ):
                    counts = cast(dict[str, int], row["counts"])
                    counts[reason] = counts.get(reason, 0) + 1
    except Exception:
        _failed()


def lifecycle(epoch: object | None, values: tuple[int, int, int, str, int] | None) -> None:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is None:
                return
            if values is None:
                _seal(capture, "lifecycle_unavailable", uncertain=True)
                return
            if len(values[3]) > 320:
                _seal(capture, "lifecycle_invalid", uncertain=True)
                return
            identity = (values[0], values[1], values[3], values[4])
            if capture.lifecycle is not None and capture.lifecycle != identity:
                _seal(capture, "lifecycle_changed", uncertain=True)
            elif (
                values[0] != capture.context.map_id
                or values[1] != capture.context.player_id
                or values[2] < capture.context.uptime_ms
            ):
                _seal(capture, "lifecycle_changed", uncertain=True)
            else:
                capture.lifecycle = identity
    except Exception:
        _failed()


def acquired(epoch: object | None, generation: int, composition_generation: int, target: int, lease_ms: int) -> int:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is None:
                return -1
            if len(capture.attempts) >= MAX_ATTEMPTS:
                capture.overflow += 1
                _seal(capture, "attempt_limit")
                return -1
            index = len(capture.attempts)
            capture.attempts.append(
                {
                    "kind": "ATT",
                    "id": index + 1,
                    "g": generation,
                    "c": composition_generation,
                    "to": _target(capture, target),
                    "lease": lease_ms,
                    "t": capture.last_now,
                    "st": [[capture.last_now - capture.start, "acquired", None]],
                    "pre": {},
                    "exec": {},
                    "terminal": "queued_at_end",
                }
            )
            return index
    except Exception:
        _failed()
        return -1


def begin_revalidation(epoch: object | None, index: int, at_execution: bool) -> SnapshotTicket | None:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is None or not 0 <= index < len(capture.attempts):
                return None
            phase = 2 if at_execution else 1
            key = (index, phase)
            if key in capture.revalidation_tickets:
                capture.incomplete_inputs += 1
                return None
            ticket = SnapshotTicket(capture.epoch, index, phase)
            capture.revalidation_tickets[key] = ticket
            capture.attempts[index]["exec" if at_execution else "pre"] = _new_snapshot(capture.last_now)
            return ticket
    except Exception:
        _failed()
        return None


def attempt_event(epoch: object | None, index: int, stage: str, value: object = None) -> None:
    try:
        with _lock:
            capture = _current(epoch)
            if capture is None or not 0 <= index < len(capture.attempts):
                return
            if stage not in (
                "pre",
                "exec",
                "queue",
                "queue_exception",
                "queue_unavailable",
                "renew",
                "binding_enter",
                "binding_return",
                "binding_exception",
                "abort",
                "cancel",
                "clear_sent",
            ):
                return
            row = capture.attempts[index]
            stages = cast(list[object], row["st"])
            if len(stages) >= MAX_STAGES:
                capture.overflow += 1
                _seal(capture, "stage_limit")
                return
            copied: object
            if stage in ("binding_return", "queue"):
                copied = _binding(value)
            elif stage == "binding_exception":
                copied = _type_name(value)
            elif stage in ("abort", "cancel", "clear_sent", "pre", "exec"):
                copied = value if type(value) is str and len(value) <= 32 and value.isascii() else "unspecified"
            else:
                copied = value if type(value) is bool else None
            stages.append([capture.last_now - capture.start, stage, copied])
            if stage == "binding_enter":
                row["terminal"] = "binding_return_not_observed"
            elif stage in ("binding_return", "binding_exception", "abort", "cancel", "clear_sent"):
                row["terminal"] = stage
            if stage == "cancel" and value in (
                "composition_changed",
                "lifecycle_changed",
                "lifecycle_unavailable",
                "equipped_slot_changed",
                "handler_disposed",
                "composition_disposed",
            ):
                _seal(capture, "lifecycle_changed", uncertain=True)
    except Exception:
        _failed()


def arm_capture(
    mode: Mode,
    label: str,
    watched_label: int,
    context: ContextSample,
    mapping: tuple[tuple[int, int], ...],
    clock: Callable[[], int],
    start_ms: int,
    sample_ms: int,
    query_count: int,
) -> object | None:
    """Called only after the widget's explicit Arm and Draw-context reads."""
    global _capture
    try:
        with _lock:
            if _capture is not None and (_capture.active or not _capture.output_done):
                return None
            if (
                mode not in ("owner", "mesmer")
                or not label
                or len(label) > 16
                or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for c in label)
            ):
                return None
            if not 1 <= len(context.roster) <= MAX_ROSTER or len(mapping) != len(context.roster):
                return None
            if tuple(pair[0] for pair in mapping) != context.roster or (
                mode == "mesmer" and not 1 <= watched_label <= len(mapping)
            ):
                return None
            if (
                not 0 <= query_count <= 23
                or not 0 <= start_ms <= sample_ms < (1 << 64)
                or sample_ms - start_ms > CONTEXT_GAP_MS
            ):
                return None
            actors = {agent: _PLAYER_LABELS[index] for index, (_login, agent) in enumerate(mapping)}
            if context.player_id not in actors or context.watched_id not in actors or len(actors) != len(mapping):
                return None
            if context.watched_id != (context.player_id if mode == "owner" else mapping[watched_label - 1][1]):
                return None
            # These fields identify compatible observations, not a unique instance.
            context_key = (
                context.map_id,
                context.region,
                context.district,
                context.language,
                context.party_id,
                context.roster,
            )
            fingerprint = hashlib.sha256(json.dumps(context_key).encode("ascii")).hexdigest()[:16]
            _capture = _Capture(
                object(),
                mode,
                label,
                clock,
                start_ms,
                sample_ms,
                sample_ms,
                context,
                actors,
                actors[context.player_id],
                actors[context.watched_id],
                fingerprint,
                queries=query_count,
                last_opportunity=sample_ms,
            )
            return _capture.epoch
    except Exception:
        _failed()
        return None


def draw_request() -> tuple[object, Mode, ContextSample] | None:
    """Reserve at most one sample opportunity; this function makes no game reads."""
    try:
        with _lock:
            capture = _capture
            if capture is None or _current(capture.epoch, hook=False) is None:
                return None
            if capture.last_now - capture.last_opportunity < SAMPLE_MS or capture.samples >= MAX_SAMPLES:
                return None
            capture.samples += 1
            capture.last_opportunity = capture.last_now
            return capture.epoch, capture.mode, capture.context
    except Exception:
        _failed()
        return None


def accept_draw_sample(epoch: object, context: ContextSample, now: int, queries: int) -> bool:
    try:
        with _lock:
            capture = _capture
            if capture is None or capture.epoch is not epoch:
                return False
            capture.queries += queries
            if not 0 <= queries <= 11 or capture.queries > MAX_QUERIES:
                capture.overflow += 1
                _seal(capture, "query_limit")
                return False
            if _current(epoch, hook=False) is None:
                return False
            if context.identity() != capture.context.identity() or context.uptime_ms < capture.context.uptime_ms:
                _seal(capture, "context_changed", uncertain=True)
                return False
            if now < capture.last_sample or now - capture.last_sample > CONTEXT_GAP_MS:
                _seal(capture, "context_gap", uncertain=True)
                return False
            capture.last_sample = now
            capture.context = context
            return True
    except Exception:
        _failed()
        return False


def sample_failed(epoch: object, reason: str, queries: int | None) -> None:
    """Account for partial Draw reads without adopting a later capture."""
    try:
        with _lock:
            capture = _capture
            if capture is None or capture.epoch is not epoch:
                return
            capture.queries += 11 if queries is None else min(11, max(0, queries))
            capture.query_count_upper_bound |= queries is None
            capture.incomplete_inputs += 1
            stop_capture(reason)
    except Exception:
        _failed()


def owner_sample(epoch: object, effects: Any) -> None:
    """Draw-only bounded extraction; never retain a native effect or its list."""
    try:
        with _lock:
            capture = _current(epoch, hook=False)
            if capture is None or capture.mode != "owner":
                return
            if capture.owner_sampled_at == capture.last_sample:
                return
            capture.owner_sampled_at = capture.last_sample
            row: Row = {"kind": "OWNER", "t": capture.last_sample, "last": capture.last_sample, "samples": 1}
            _copy_effects(capture, row, effects, owner=True)
            if capture.owner_rows:
                previous = capture.owner_rows[-1]
                if (
                    previous["input"] == row["input"]
                    and previous["vm"][:2] == row["vm"][:2]
                    and previous["hr"] == row["hr"]
                ):
                    previous["last"] = row["last"]
                    previous["samples"] += 1
                    previous["last_vm"] = row["vm"]
                    capture.suppressed += 1
                    return
            if len(capture.owner_rows) >= MAX_SAMPLES:
                capture.overflow += 1
                _seal(capture, "owner_limit")
                return
            capture.owner_rows.append(row)
    except Exception:
        _failed()


def stop_capture(reason: str = "manual_stop") -> None:
    try:
        with _lock:
            if _capture is not None:
                if reason == "console_failure":
                    _capture.formatting_failed = True
                    _capture.active = False
                    _capture.reason = "console_failure"
                    return
                if _capture.active:
                    _current(_capture.epoch, hook=False)
                allowed = {
                    "manual_stop",
                    "widget_disabled",
                    "reloaded",
                    "enabled_idle",
                    "sample_failure",
                    "context_invalid",
                    "roster_limit",
                    "console_failure",
                }
                _seal(_capture, reason if reason in allowed else "diagnostic_failure", uncertain=True)
    except Exception:
        _failed()


def capture_status() -> str:
    capture = _capture
    if capture is None:
        return "Idle; enabling does not Arm."
    return ("Active" if capture.active else capture.reason) + ": " + capture.actor + "; watched " + capture.watched


def can_arm() -> bool:
    return _capture is None or (not _capture.active and _capture.output_done)


def _end(capture: _Capture) -> Row:
    complete = capture.reason in ("completed", "manual_stop") and not (
        capture.overflow or capture.incomplete_inputs or capture.formatting_failed
    )
    outcome = "OBSERVED" if complete else "INCOMPLETE"
    if complete and capture.mode == "owner" and not capture.owner_positive:
        outcome = "NOT_EXERCISED"
    return {
        "kind": "END",
        "t": capture.last_now,
        "reason": capture.reason,
        "outcome": outcome,
        "scheduler": (
            "observed"
            if capture.scheduler
            else "no_observed_scheduler_pass" if capture.mode == "mesmer" else "not_applicable"
        ),
        "samples": capture.samples,
        "queries": capture.queries,
        "query_count_upper_bound": capture.query_count_upper_bound,
        "hooks": capture.hooks,
        "target_snapshots": capture.snapshot_reads,
        "skipped_detail": capture.skipped_detail,
        "missed_samples": capture.missed_samples,
        "incomplete_inputs": capture.incomplete_inputs,
        "suppressed": capture.suppressed,
        "overflow": capture.overflow,
        "last_context": capture.last_sample,
        "uncertain_after": capture.uncertain_after,
        "removal": "UNRESOLVED",
        "record_count": capture.emitted + 1,
    }


def _format(capture: _Capture, row: Row) -> str:
    text = "SmartShatterObs " + json.dumps(
        {"capture": capture.label, "actor": capture.actor, **row}, ensure_ascii=True, separators=(",", ":")
    )
    if len(text) > MAX_LINE_BYTES:
        capture.formatting_failed = True
        capture.overflow += 1
        text = "SmartShatterObs " + json.dumps(
            {
                "capture": capture.label,
                "actor": capture.actor,
                "kind": row.get("kind"),
                "id": row.get("id"),
                "omitted": "line_limit",
                "outcome": "INCOMPLETE",
            },
            separators=(",", ":"),
        )
    return text


def _format_safe(capture: _Capture, row: Row) -> str:
    try:
        return _format(capture, row)
    except Exception:
        capture.formatting_failed = True
        if row.get("kind") == "END":
            return 'SmartShatterObs {"kind":"END","outcome":"INCOMPLETE","reason":"format_failure"}'
        return 'SmartShatterObs {"kind":"STATUS","outcome":"INCOMPLETE","reason":"format_failure"}'


def drain_console_draw() -> list[str]:
    """Format at most two lines. The widget alone emits them, from Draw."""
    try:
        with _lock:
            capture = _capture
            if capture is None or capture.output_done:
                return []
            lines: list[str] = []
            if capture.emitted == 0:
                lines.append(
                    _format_safe(
                        capture,
                        {
                            "kind": "BEGIN",
                            "t": capture.start,
                            "deadline": capture.start + DURATION_MS,
                            "mode": capture.mode,
                            "watch": capture.watched,
                            "context": capture.fingerprint,
                            "clock": "Windows_boot_ms_same_host_only",
                            "instance_identity": "not_proven",
                            "designation": "user_selected_not_build_recognition",
                            "reader_completeness": "unknown",
                            "candidate_fields": ["target", "reason", "priority", "splash", "hp", "distance_squared"],
                            "vm_fields": [
                                "state",
                                "count",
                                "min_remaining_ms",
                                "max_remaining_ms",
                                "unknown_remaining",
                            ],
                            "stage_fields": ["ms_since_begin", "event", "value"],
                            "binding_fields": ["type", "value"],
                        },
                    )
                )
                capture.emitted += 1
            if capture.active:
                return lines
            records = (
                list(capture.scheduler.values())
                + [{"kind": "DEC", **row} for row in capture.decisions.values() if row.get("evaluated")]
                + capture.attempts
                + capture.owner_rows
            )
            while len(lines) < 2 and capture.output_index < len(records) and capture.emitted < MAX_RECORDS - 1:
                row = records[capture.output_index]
                lines.append(_format_safe(capture, row))
                capture.output_index += 1
                capture.emitted += 1
            if len(lines) < 2:
                if capture.output_index < len(records):
                    capture.overflow += len(records) - capture.output_index
                lines.append(_format_safe(capture, _end(capture)))
                capture.emitted += 1
                capture.output_done = True
            return lines
    except Exception:
        _failed()
        return []
