"""Automatic owner-only condition publisher, advanced solely in Context.Draw."""

# pyright: strict
from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import TYPE_CHECKING
from typing import cast

import PyImGui
import PySystem

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import Effects
from Py4GWCoreLib import Map
from Py4GWCoreLib import Party
from Py4GWCoreLib import Player
from Py4GWCoreLib import Skill
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import CONDITIONS
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import MAX_AGE_MS
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import SAMPLE_INTERVAL_MS
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Context
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Publisher
from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import current_context
from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64

if TYPE_CHECKING:
    from PyEffects import EffectType

    from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Observation

_previous_stop = cast(Callable[[], None] | None, globals().get("on_disable"))
if _previous_stop is not None:
    _previous_stop()

MODULE_NAME = "Condition Observations"
MODULE_CATEGORY = "System"
OPTIONAL = True
_enabled = False
# Session-only troubleshooting pause; no saved opt-in is required on any client.
_publishing = True
_publisher: Publisher | None = None
_context: Context | None = None
_uptime = 0
_next_sample = 0
_condition_ids: dict[int, str] = {}
_status = "Stopped"
_sample_lock = Lock()
_status_requested = False
_STATUS_PARTY_LIMIT = 12


def _stop() -> None:
    global _publisher, _context, _status
    publisher, _publisher = _publisher, None
    _context = None
    _status = "Stopped"
    if publisher is not None:
        GLOBAL_CACHE.ShMem.GetConditionTable().invalidate(publisher)


def on_enable() -> None:
    global _enabled
    _enabled = True


def on_disable() -> None:
    global _enabled, _status_requested
    _enabled = False
    _status_requested = False
    _stop()


def _advance() -> None:
    global _publisher, _context, _uptime, _next_sample, _condition_ids, _status
    if not _enabled or not _publishing:
        return
    try:
        context, uptime = current_context(), Map.GetInstanceUptime()
        if context is not None and Player.GetAgentID() != context.agent:
            context = None
        if context != _context or uptime < _uptime:
            if _publisher is not None:
                GLOBAL_CACHE.ShMem.GetConditionTable().invalidate(_publisher, stop=False)
            _context = context
        _uptime = uptime
        if context is None:
            _status = "Waiting for an explorable party"
            return
        now = get_uncached_tick_count64()
        if now < _next_sample:
            return
        _next_sample = now + SAMPLE_INTERVAL_MS
        owner = GLOBAL_CACHE.ShMem.GetConditionOwner(context)
        if owner is None:
            if _publisher is not None:
                GLOBAL_CACHE.ShMem.GetConditionTable().invalidate(_publisher, stop=False)
            _status = "Owner identity unavailable"
            return
        if _publisher is None:
            _publisher = Publisher()
        publisher = _publisher
        if not publisher.active:
            _status = "Superseded; stop and start to publish again"
            return
        if publisher.owner is not None and publisher.owner != owner:
            GLOBAL_CACHE.ShMem.GetConditionTable().invalidate(publisher, stop=False)
        if not _condition_ids:
            _condition_ids = {Skill.GetID(name): name for name in CONDITIONS}
        if not _enabled or not _publishing or _publisher is not publisher or not publisher.active:
            return
        conditions: frozenset[str] | None = None
        sampled_at = get_uncached_tick_count64()
        try:
            read = cast("Callable[[int], list[EffectType] | None]", Effects.GetEffects)
            effects = read(context.agent)
            if effects is not None and len(_condition_ids) == len(CONDITIONS) and 0 not in _condition_ids:
                if any(effect.skill_id <= 0 for effect in effects):
                    raise ValueError("Unusable effect identity")
                conditions = frozenset(_condition_ids[e.skill_id] for e in effects if e.skill_id in _condition_ids)
        except Exception:
            conditions = None
        # Native calls can release control. A disabled/reloaded or changed owner
        # cannot finish an in-flight sample, even if callbacks overlap.
        if not _enabled or not _publishing or _publisher is not publisher or not publisher.active:
            return
        if current_context() != context or GLOBAL_CACHE.ShMem.GetConditionOwner(context) != owner:
            GLOBAL_CACHE.ShMem.GetConditionTable().invalidate(publisher, stop=False)
            return
        accepted = GLOBAL_CACHE.ShMem.GetConditionTable().publish(
            publisher, owner, context.instance, sampled_at, conditions
        )
        _status = "Publishing" if accepted and conditions is not None else "Condition evidence unavailable"
        _next_sample = get_uncached_tick_count64() + SAMPLE_INTERVAL_MS
    except Exception:
        _stop()
        _status = "Condition evidence unavailable"


def _read_status(agent: int, login: int, character: str) -> tuple[Observation | None, str]:
    try:
        observation = GLOBAL_CACHE.ShMem.ReadConditionObservation(agent, login, character)
        if observation is not None:
            age = get_uncached_tick_count64() - observation.sampled_at
            if 0 <= age < MAX_AGE_MS:
                state = "FRESH_WITH_CONDITIONS" if observation.conditions else "FRESH_VALID_EMPTY"
                return observation, f"{state}(age_ms={age},count={len(observation.conditions)},instance=MATCH)"
    except Exception:
        pass
    # The consumer API intentionally does not disclose rejection reasons. Do not
    # inspect raw records or treat a failed read as proof of an instance mismatch.
    return None, "REJECTED_OR_UNAVAILABLE(instance=UNVERIFIED)"


def _report_publication_status() -> None:
    parts: list[str] = []
    try:
        opted_in = _enabled and _publishing
        if Map.IsOutpost():
            local = "LOCAL_WAITING_FOR_EXPLORABLE" if opted_in else "LOCAL_DISABLED"
            parts.append(f"{local}; location=OUTPOST; publication=NOT_EXPECTED; remote=NOT_CHECKED")
        elif (context := current_context()) is None:
            local = "LOCAL_CONTEXT_UNAVAILABLE" if opted_in else "LOCAL_DISABLED"
            parts.append(f"{local}; remote=NOT_CHECKED(context_unavailable)")
        else:
            publisher = _publisher
            if not opted_in:
                parts.append("LOCAL_DISABLED")
            elif publisher is None:
                parts.append("LOCAL_WAITING_FOR_SAMPLE")
            elif not publisher.active:
                parts.append("LOCAL_SUPERSEDED")
            else:
                observation, result = _read_status(context.agent, context.login, context.character)
                if observation is not None and observation.binding == (
                    publisher.owner,
                    context.instance,
                    (publisher.started, publisher.nonce, publisher.generation),
                ):
                    parts.append(f"LOCAL_PUBLISHING({result})")
                else:
                    parts.append("LOCAL_PUBLICATION_UNVERIFIED")
            players = Party.GetPlayers() or []
            peers = 0
            for position, member in enumerate(players[:_STATUS_PARTY_LIMIT], start=1):
                if not member.is_connected or member.login_number == context.login:
                    continue
                peers += 1
                try:
                    agent = Party.Players.GetAgentIDByLoginNumber(member.login_number)
                    _, result = _read_status(agent, Agent.GetLoginNumber(agent), Agent.GetNameByID(agent))
                except Exception:
                    result = "REJECTED_OR_UNAVAILABLE(instance=UNVERIFIED)"
                # Party position is sufficient for a manual check; never log the
                # account, character name, native identity or fingerprint bytes.
                parts.append(f"party[{position}]=REMOTE_{result}")
            if not peers:
                parts.append("remote=NO_CONNECTED_PEERS")
            if len(players) > _STATUS_PARTY_LIMIT:
                parts.append(f"party_scan=FIRST_{_STATUS_PARTY_LIMIT}_ONLY")
    except Exception:
        parts = ["CHECK_UNAVAILABLE; instance=UNVERIFIED"]
    PySystem.Console.Log(
        "ConditionObservations", "ConditionObservations STATUS " + "; ".join(parts), PySystem.Console.MessageType.Info
    )


def draw() -> None:
    global _status_requested
    # WidgetManager maps draw to Context.Draw. Advance outside all UI visibility
    # decisions, including a collapsed configuration window.
    if _sample_lock.acquire(blocking=False):
        try:
            _advance()
            if _status_requested and _enabled:
                _status_requested = False
                _report_publication_status()
        finally:
            _sample_lock.release()


def configure() -> None:
    global _publishing, _status_requested
    visible = PyImGui.begin(MODULE_NAME)
    try:
        if visible:
            PyImGui.text("Share this character's current conditions with permitted party accounts.")
            requested = not PyImGui.checkbox("Pause publishing (this session)", not _publishing)
            if requested != _publishing:
                _publishing = requested
                if not requested:
                    _stop()
            PyImGui.text(_status if _publishing else "Publishing paused for this session")
            if PyImGui.button("Check publication status"):
                _status_requested = True
    finally:
        PyImGui.end()
