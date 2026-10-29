"""Automatic HR-local hex census. All owner probes run exclusively in Context.Draw."""

# pyright: strict
from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from threading import Lock
from typing import cast

import PyImGui

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import Effects
from Py4GWCoreLib import Map
from Py4GWCoreLib import Player
from Py4GWCoreLib import Profession
from Py4GWCoreLib import Skill
from Py4GWCoreLib import SkillBar
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Context
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Owner
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Publisher
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import current_context
from Py4GWCoreLib.GlobalCache.shared_memory_src.HrHexObservations import SAMPLE_INTERVAL_MS
from Py4GWCoreLib.GlobalCache.shared_memory_src.HrHexObservations import VM_SKILL_ID
from Py4GWCoreLib.GlobalCache.shared_memory_src.HrHexObservations import HrHexCensus
from Py4GWCoreLib.GlobalCache.shared_memory_src.HrHexObservations import collect_hex_census
from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64

_previous_stop = cast(Callable[[], None] | None, globals().get("on_disable"))
if _previous_stop is not None:
    _previous_stop()

MODULE_NAME = "HR Hex Observations"
MODULE_CATEGORY = "System"
OPTIONAL = True
_enabled = False
_publishing = True
_publisher: Publisher | None = None
_context: Context | None = None
_uptime = 0
_last_tick = 0
_next_sample = 0
_status = "Stopped"
_sample_lock = Lock()
_CONSOLE_LIMIT = 16
_CONSOLE_PERIOD_MS = 5000
# Retain the bounded budget across in-place reloads and enable/disable cycles.
_console_ticks = cast(list[int], globals().get("_console_ticks", []))
_console_identity: tuple[Owner, bytes, int, bytes, int] | None = None
_console_vm: bool | None = None
_console_last_tick = 0


def _log_publication(
    publisher: Publisher,
    owner: Owner,
    instance: bytes,
    generation: int,
    sampled_at: int,
    census: HrHexCensus,
    now: int,
) -> None:
    global _console_identity, _console_vm, _console_last_tick
    identity = (owner, instance, publisher.started, publisher.nonce, generation)
    vm_present = VM_SKILL_ID in census.hex_ids
    if _console_ticks and now - _console_ticks[-1] < 1000:
        return
    while _console_ticks and now - _console_ticks[0] >= 60_000:
        _console_ticks.pop(0)
    if len(_console_ticks) >= _CONSOLE_LIMIT:
        return
    if identity != _console_identity:
        trigger = "first"
    elif vm_present != _console_vm:
        trigger = "vm_transition"
    elif vm_present and now - _console_last_tick >= _CONSOLE_PERIOD_MS:
        trigger = "vm_periodic"
    else:
        return
    # Charge attempted output too, so a failing console cannot cause a log storm.
    _console_ticks.append(now)
    _console_identity, _console_vm, _console_last_tick = identity, vm_present, now
    owner_bind = sha256(owner.digest() + instance + publisher.nonce).hexdigest()[:16]
    remaining = "unknown" if census.vm_remaining_ms is None else format(census.vm_remaining_ms, ".17g")
    message = (
        f"HR_HEX_OWNER_V1 event=published trigger={trigger} "
        f"state={'valid_empty' if not census.hex_ids else 'valid'} "
        f"owner_bind={owner_bind} pub_nonce={publisher.nonce.hex()} pub_started_ms={publisher.started} "
        f"context_gen={generation} sample_seq={publisher.sequence} sample_tick_ms={sampled_at} "
        f"vm_present={int(vm_present)} observed_entries={census.entry_count} distinct_ids={len(census.hex_ids)} "
        f"vm_sample_ms={remaining}"
    )
    # Reject oversized diagnostics intact; slicing could change a numeric value.
    if len(message) > 600:
        return
    import PySystem

    PySystem.Console.Log(MODULE_NAME, message, PySystem.Console.MessageType.Info)


def _stop() -> None:
    global _publisher, _context, _status
    publisher, _publisher = _publisher, None
    _context = None
    _status = "Stopped"
    if publisher is not None:
        GLOBAL_CACHE.ShMem.GetHrHexTable().invalidate(publisher)


def on_enable() -> None:
    global _enabled
    _enabled = True


def on_disable() -> None:
    global _enabled
    _enabled = False
    _stop()


def _hr_equipped(context: Context) -> bool:
    # Draw-only: Player.GetAgentID transitively uses the renderer's loaded check.
    if Player.GetAgentID() != context.agent or Agent.GetProfessionIDs(context.agent)[0] != Profession.Paragon.value:
        return False
    hr_id = Skill.GetID("Heroic_Refrain")
    read_slot = cast(Callable[[int], int], getattr(SkillBar, "GetSkillIDBySlot"))
    bar = tuple(read_slot(slot) for slot in range(1, 9))
    return hr_id > 0 and all(type(skill_id) is int and skill_id >= 0 for skill_id in bar) and hr_id in bar


def _advance() -> None:
    global _publisher, _context, _uptime, _last_tick, _next_sample, _status
    if not _enabled or not _publishing:
        return
    attempted = False
    accepted = False
    publisher: Publisher | None = None
    owner: Owner | None = None
    context: Context | None = None
    census: HrHexCensus | None = None
    generation = sampled_at = completed_at = 0
    try:
        now = get_uncached_tick_count64()
        context, uptime = current_context(), Map.GetInstanceUptime()
        clock_reset = now < _last_tick
        if context != _context or uptime < _uptime or clock_reset:
            if _publisher is not None:
                GLOBAL_CACHE.ShMem.GetHrHexTable().invalidate(_publisher, stop=False)
            _context = context
        _uptime, _last_tick = uptime, now
        if clock_reset:
            _next_sample = now + SAMPLE_INTERVAL_MS
        if context is None:
            _status = "Waiting for an explorable party"
            return
        if now < _next_sample:
            return
        attempted = True
        _next_sample = now + SAMPLE_INTERVAL_MS
        owner = GLOBAL_CACHE.ShMem.GetHrHexOwner(context)
        if owner is None or not _hr_equipped(context):
            if _publisher is not None:
                GLOBAL_CACHE.ShMem.GetHrHexTable().invalidate(_publisher, stop=False)
            _status = "Waiting for an HR-equipped Paragon"
            return
        if _publisher is None:
            _publisher = Publisher()
        publisher = _publisher
        if not publisher.active:
            _status = "Superseded; stop and start to publish again"
            return
        if publisher.owner is not None and publisher.owner != owner:
            GLOBAL_CACHE.ShMem.GetHrHexTable().invalidate(publisher, stop=False)
        generation = publisher.generation
        # This timestamp includes native enumeration and all subsequent processing.
        sampled_at = get_uncached_tick_count64()
        census = collect_hex_census(
            Effects.GetEffects(context.agent), cast(Callable[[int], bool], getattr(Skill.Flags, "IsHex"))
        )
        if (
            not _enabled
            or not _publishing
            or _publisher is not publisher
            or not publisher.active
            or publisher.generation != generation
        ):
            return
        if (
            census is None
            or current_context() != context
            or GLOBAL_CACHE.ShMem.GetHrHexOwner(context) != owner
            or not _hr_equipped(context)
        ):
            GLOBAL_CACHE.ShMem.GetHrHexTable().invalidate(publisher, stop=False)
            _status = "HR hex evidence unavailable"
            return
        accepted = GLOBAL_CACHE.ShMem.GetHrHexTable().publish(publisher, owner, context.instance, sampled_at, census)
        _status = "Publishing owner-observed hexes" if accepted else "HR hex evidence unavailable"
    except Exception:
        if _publisher is not None:
            GLOBAL_CACHE.ShMem.GetHrHexTable().invalidate(_publisher, stop=False)
        _status = "HR hex evidence unavailable"
    finally:
        # No catch-up, including after a slow or failed read. Waiting frames must
        # not keep extending the deadline, so only a due census advances it.
        if attempted:
            completed_at = get_uncached_tick_count64()
            _next_sample = max(_next_sample, completed_at + SAMPLE_INTERVAL_MS)
    # Publication and cadence are already settled, and the table mutex is free.
    # Diagnostic failure must never enter the publication invalidation handler.
    if accepted and publisher is not None and owner is not None and context is not None and census is not None:
        try:
            _log_publication(publisher, owner, context.instance, generation, sampled_at, census, completed_at)
        except Exception:
            pass


def draw() -> None:
    if _sample_lock.acquire(blocking=False):
        try:
            _advance()
        finally:
            _sample_lock.release()


def configure() -> None:
    global _publishing
    visible = PyImGui.begin(MODULE_NAME)
    try:
        if visible:
            PyImGui.text("Share fresh local hex observations when this Paragon equips Heroic Refrain.")
            requested = not PyImGui.checkbox("Pause publishing (this session)", not _publishing)
            if requested != _publishing:
                _publishing = requested
                if not requested:
                    _stop()
            PyImGui.text(_status if _publishing else "Publishing paused for this session")
    finally:
        PyImGui.end()
