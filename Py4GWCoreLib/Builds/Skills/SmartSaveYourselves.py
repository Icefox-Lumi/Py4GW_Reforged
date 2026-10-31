"""Observation-led SY coordination. Local scheduling holds are not coverage receipts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from math import dist
from math import isfinite
from typing import TYPE_CHECKING
from typing import Literal
from typing import cast

if TYPE_CHECKING:
    from PyEffects import EffectType
    from PyParty import HenchmanPartyMember
    from PyParty import HeroPartyMember
    from PyParty import PlayerPartyMember
    from PySkillbar import SkillbarSkill

    from Py4GWCoreLib.BuildMgr import BuildMgr

_Kind = Literal["sy", "myt", "fgj"]
_Recipient = tuple[int, int]
_Context = tuple[int, ...]
_EffectScope = tuple[int, int, int]  # Recipient, life, skill.
_EffectKey = tuple[int, int, int, int, int]  # Scope, effect_id, timestamp.

# Temporary capture: enable only in a separately reviewed/deployed capture copy.
# Consumed only by a validated normal owner execution, never by discovery,
# construction, ordinary observation, or a guarded ACTION callback.
# Reconstruction cannot rearm; a fresh module load with True can. Restore False
# before the next normal deployment/reload. No persistent configuration is used.
_DIAGNOSTIC_ARM_ONCE = False
_diagnostic_consumed = False
# reload reuses the globals dictionary seen by surviving old recorder methods.
_diagnostic_lifetime = object()


class _Capture:
    """Bounded, owner-local observations; never an input to the casting policy."""

    def __init__(self, now: int) -> None:
        self._lifetime = _diagnostic_lifetime
        self.state = "ARMED"
        self.armed = self.now = self.last_seen = now
        self.started: int | None = None
        self.last_status = now - 1000
        self.lines = 0
        self.logger_failures = 0
        self.truncated = False
        self.deferred = False
        self.pending: list[tuple[int, str, dict[str, object]]] = []
        self.counts: dict[str, int] = {
            kind + "_" + stage: 0
            for kind in ("sy", "myt", "fgj")
            for stage in (
                "queued",
                "native_calls",
                "native_true",
                "native_false",
                "native_exception",
                "observation_success",
                "observation_failure",
                "observation_unresolved",
            )
        }
        self.values: dict[str, object] = {}
        self.value_times: dict[str, int] = {}
        self.gates: dict[str, bool] = {}
        self.previous: dict[str, object] = {}
        self.labels: dict[_Recipient, int] = {}
        self.exclusions: dict[int, str] = {}
        self.next_label = 0
        self.coverage: dict[int, tuple[str, int]] = {}
        self.coverage_at: int | None = None
        self.observed_ms = self.inferred_ms = self.unknown_ms = 0
        self.unobserved_ms = 0
        self.due_at: int | None = None
        self.due_ms = 0
        self.due_episode_ms = 0
        self.gap_announced = False
        self.stop_reason = ""
        self.stop_requested = ""
        self.clock_discontinuity = False

    @property
    def active(self) -> bool:
        return self._lifetime is _diagnostic_lifetime and self.state in ("ARMED", "CAPTURING")

    def label(self, key: _Recipient) -> int:
        if key not in self.labels and self.next_label < 64:
            self.next_label += 1
            self.labels[key] = self.next_label
        return self.labels.get(key, 0)  # Overflow is anonymous/unobservable.

    def count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def event(self, category: str, **data: object) -> None:
        if not self.active:
            return
        if self.deferred:
            if len(self.pending) < 64:
                self.pending.append((self.now, category, data))
            else:
                self.truncated = True
            return
        if self.lines >= 396:
            self.truncated = True
            self.finish("line_limit")
            return
        self.send(self.now, category, data)

    def send(self, now: int, category: str, data: dict[str, object]) -> None:
        if self._lifetime is not _diagnostic_lifetime or self.lines >= 400 or self.logger_failures:
            return
        import Py4GWCoreLib

        # Count attempted sends too: a logger may emit and then raise.
        self.lines += 1
        try:
            details = " ".join(f"{key}={value}" for key, value in data.items())
            log = cast(Callable[[str, str], None], getattr(Py4GWCoreLib, "ConsoleLog"))
            stamp = "t=unknown" if self.clock_discontinuity else f"+{max(0, now - self.armed)}ms"
            log("HR-DIAG", f"{stamp} {category} {details}")
        except Exception:
            self.logger_failures += 1
            self.stop_reason = "logger_failure"
            self.state = "FINISHED"
            self.pending.clear()

    def flush(self) -> None:
        if self.stop_requested:
            self.finish(self.stop_requested)
            return
        pending, self.pending = self.pending, []
        for now, category, data in pending:
            if not self.active:
                break
            if self.lines >= 396:
                self.truncated = True
                self.finish("line_limit")
                break
            self.send(now, category, data)
        if self.active and self.truncated:
            self.finish("event_buffer_limit")
        self.bounds()

    def bounds(self) -> None:
        if not self.active:
            return
        deadline = self.armed + 180000
        reason = "arm_limit"
        if self.started is not None and self.started + 120000 <= deadline:
            deadline, reason = self.started + 120000, "combat_limit"
        if self.now >= deadline:
            if self.deferred:
                self.stop_requested = reason
            else:
                self.finish(reason)

    def step(self, now: int) -> None:
        gap = now - self.last_seen
        self.now = now
        self.last_seen = now
        if gap < 0:
            self.clock_discontinuity = True
            self.pending.clear()
            if self.deferred:
                self.stop_requested = "clock_discontinuity"
            else:
                self.finish("clock_discontinuity")
            return
        if gap > 1000:
            self.unobserved_ms += max(0, gap)
            self.coverage.clear()
            self.coverage_at = None
            self.due_at = None
            self.due_episode_ms = 0
            self.gap_announced = False
            self.event("observation_gap", elapsed_ms=gap, evidence="unknown_no_pause_timestamp")
        self.bounds()

    def transition(self, channel: str, signature: object, **data: object) -> None:
        if self.previous.get(channel) == signature:
            return
        self.previous[channel] = signature
        self.event(channel, **data)

    def pressure(self, active: bool, reason: str) -> None:
        previous = self.previous.get("pressure", False)
        if active and not previous:
            if self.started is None:
                self.started = self.now
                self.state = "CAPTURING"
                self.coverage.clear()
                self.coverage_at = None
                self.event("CAPTURING", reason="pressure_entry")
            self.count("pressure_episodes")
        self.transition(
            "pressure",
            active,
            active=active,
            reason=reason,
            health=self.values.get("health", ()),
            hostile=self.values.get("hostile", "not_evaluated"),
            health_fields="recipient,health,accumulated_drop,monitor_age_ms,event,exclusion_remaining_ms,exclusion_cause",
        )

    def decision(self, reason: str, preparation: bool, skill: int = 0) -> None:
        phase = "preparation" if preparation else "payload"
        self.count("decision_" + phase + "_" + reason)
        signature = (reason, skill, tuple(self.gates.items()))
        self.transition(
            "decision_" + phase,
            signature,
            reason=reason,
            skill=skill,
            gates=dict(self.gates),
            enabled_sy=self.values.get("enabled_sy"),
            deadline_remaining_ms=self.values.get("deadline_remaining_ms")
            if reason != "demand_gate"
            else "not_evaluated",
            energy=self.values.get("energy")
            if "myt_energy" in self.gates or "fgj_energy" in self.gates
            else "not_evaluated",
            myt_candidates=self.values.get("myt_candidates") if "myt_candidates" in self.gates else "not_evaluated",
        )
        due = bool(self.values.get("sy_due", False)) and self.state == "CAPTURING"
        if due:
            if self.due_at is not None and 0 <= self.now - self.due_at <= 1000:
                self.due_ms += self.now - self.due_at
                self.due_episode_ms += self.now - self.due_at
            self.due_at = self.now
            if self.due_episode_ms >= 500 and not self.gap_announced:
                self.count("refresh_demand_gaps")
                self.gap_announced = True
                self.event(
                    "refresh_demand_gap",
                    reason=reason,
                    evidence="overdue_scheduling_demand_not_proven_loss",
                )
        else:
            self.due_at = None
            self.due_episode_ms = 0
            self.gap_announced = False

    def observe_coverage(self, current: dict[int, tuple[str, int]]) -> None:
        if self.state == "CAPTURING" and self.coverage_at is not None:
            elapsed = self.now - self.coverage_at
            if 0 <= elapsed <= 1000:
                for label, (kind, expires) in self.coverage.items():
                    if label not in current:
                        continue
                    supported = max(0, min(self.now, expires) - self.coverage_at)
                    if kind == "observed":
                        self.observed_ms += supported
                    elif kind == "inferred":
                        self.inferred_ms += supported
                    self.unknown_ms += elapsed - supported
            elif elapsed > 1000:
                self.unobserved_ms += elapsed
                self.event("coverage_observation_gap", elapsed_ms=elapsed, evidence="unknown")
        self.coverage, self.coverage_at = current, self.now
        signature = tuple((label, kind, expires) for label, (kind, expires) in current.items())
        self.transition(
            "coverage",
            signature,
            recipients={label: (kind, max(0, expires - self.armed)) for label, (kind, expires) in current.items()},
            deadline_units="capture_relative_ms",
            evidence="positive_effect_or_inferred_hold_or_unknown",
        )

    def finish(self, reason: str) -> None:
        if not self.active:
            return
        self.stop_reason = reason
        self.state = "INCONCLUSIVE" if self.started is None else "FINISHED"
        # No interval is extended to the stop time without an observation.
        self.send(
            self.now,
            self.state,
            {
                "reason": reason,
                "pressure_seen": self.started is not None,
                "capture_ms": "unknown"
                if self.clock_discontinuity
                else 0
                if self.started is None
                else min(self.now, self.started + 120000, self.armed + 180000) - self.started,
                "last_coverage_observation_ms": "unknown"
                if self.clock_discontinuity
                else None
                if self.coverage_at is None
                else self.coverage_at - self.armed,
                "unobserved_ms": "unknown" if self.clock_discontinuity else self.unobserved_ms,
                "truncated": self.truncated,
            },
        )
        self.send(self.now, "SUMMARY", dict(self.counts))
        self.send(
            self.now,
            "EVIDENCE_TOTALS",
            {
                "observed_effect_recipient_ms": "unknown" if self.clock_discontinuity else self.observed_ms,
                "inferred_hold_recipient_ms": "unknown" if self.clock_discontinuity else self.inferred_ms,
                "unknown_recipient_ms": "unknown" if self.clock_discontinuity else self.unknown_ms,
                "overdue_demand_sampled_ms": "unknown" if self.clock_discontinuity else self.due_ms,
                "logger_failures": self.logger_failures,
                "uptime": "not_computed",
                "intervals": "unavailable_clock_discontinuity"
                if self.clock_discontinuity
                else "sample_supported_not_server_receipts",
            },
        )
        self.pending.clear()


@dataclass
class _Retry:
    failures: int = 0
    not_before: int = 0


@dataclass
class _Effect:
    first_seen: int
    expires: int


@dataclass
class _RetiredEffects:
    timestamp: int = -1
    expired_first_seen: int = -1


@dataclass
class _Health:
    sample_ms: int
    health: float
    maximum: int
    last_loss: int = -10000
    excluded_until: int = 0


@dataclass
class _Request:
    request_id: int
    generation: int
    context: _Context
    kind: _Kind
    skill_id: int
    sy_id: int
    queued_ms: int
    submitted_ms: int | None = None
    pre_adrenaline: int | None = None
    action_sequence: int = 0
    recipients: tuple[_Recipient, ...] = ()
    pre_effects: set[_EffectKey] = field(default_factory=set[_EffectKey])


class SmartSaveYourselves:
    """One helper per operational stock controller; never a discoverable build."""

    SY_IDS = (1954, 2097)
    QUEUE_MS = 250
    GUARD_MS = 250
    OBSERVE_MS = 750
    REFRESH_MS = 500
    PREPARE_MS = 1500
    INFERRED_HOLD_MS = 3500
    MAX_EFFECT_INSTANCES = 64  # Per recipient/life/skill, not a game-effect limit.

    def __init__(self, owner: BuildMgr, bootstrap_ready: Callable[[], bool]) -> None:
        from Py4GWCoreLib import Skill

        self._owner = owner
        self._bootstrap_ready = bootstrap_ready
        self._hr = int(Skill.GetID("Heroic_Refrain"))
        self._tof = int(Skill.GetID("Theyre_on_Fire"))
        self._myt = int(Skill.GetID("Make_Your_Time"))
        self._fgj = int(Skill.GetID("For_Great_Justice"))
        self._bip = int(Skill.GetID("Blood_is_Power"))
        self._generation = owner.GetPolicyGeneration()
        self._context: _Context | None = None
        self._request: _Request | None = None
        self._next_request = 0
        self._retry: dict[_Kind, _Retry] = {kind: _Retry() for kind in ("sy", "myt", "fgj")}
        self._effects: dict[_EffectKey, _Effect] = {}
        self._retired_effects: dict[_EffectScope, _RetiredEffects] = {}
        self._holds: dict[_Recipient, tuple[int, int]] = {}
        self._alive: dict[int, bool] = {}
        self._lives: dict[int, int] = {}
        self._health: dict[int, _Health] = {}
        self._recipients: tuple[_Recipient, ...] = ()
        self._local_recipients: set[int] = set[int]()
        self._pressure = False
        self._last_activity = 0
        self._last_now = 0
        self._dispatch_guard_until = 0
        self._myt_latched = False
        self._myt_busy_seen = False
        self.last_outcome: str = "idle"
        self._capture: _Capture | None = None
        self._diagnostic_deferred = False

    def _diagnostic(self, action: str, *args: object, **data: object) -> None:
        """Fail closed for the recorder only, including formatting/bookkeeping faults."""
        capture = self._capture
        if capture is None or not capture.active:
            return
        if capture.stop_requested and action != "flush":
            return
        try:
            if action == "value":
                capture.values[str(args[0])] = args[1]
                capture.value_times[str(args[0])] = capture.now
            elif action == "gate":
                capture.gates[str(args[0])] = bool(args[1])
            elif action == "readiness":
                skill_id, ready = int(cast(int, args[0])), bool(args[1])
                capture.values["ready_" + str(skill_id)] = ready
                capture.value_times["ready_" + str(skill_id)] = capture.now
                capture.transition(
                    "readiness_" + str(skill_id),
                    ready,
                    skill=skill_id,
                    ready=ready,
                    resource=capture.values.get("resource_" + str(skill_id)),
                )
            elif action == "selection":
                capture.gates.clear()
            elif action == "decision":
                capture.decision(str(args[0]), bool(args[1]), int(cast(int, args[2])))
            elif action == "pressure":
                capture.pressure(bool(args[0]), str(args[1]))
            elif action == "event":
                category = str(args[0])
                capture.count(category)
                capture.transition(category, tuple(data.items()), **data)
            elif action in ("request", "native"):
                request = cast(_Request, args[0])
                stage = str(args[1])
                if action == "native" or stage not in ("native_false", "native_exception"):
                    capture.count(request.kind + "_" + stage)
                if action == "native":
                    capture.count(request.kind + "_native_calls")
                if data.get("useful_observation"):
                    capture.count(request.kind + "_observation_success")
                if data.get("failed"):
                    capture.count(request.kind + "_failure")
                if stage == "observation_unresolved":
                    capture.count(request.kind + "_observation_failure")
                capture.event(
                    action,
                    request=request.request_id,
                    skill=request.skill_id,
                    kind=request.kind,
                    stage=stage,
                    pre_adrenaline=request.pre_adrenaline,
                    resource_observation=capture.values.get("request_resource"),
                    native_at_ms=None if request.submitted_ms is None else request.submitted_ms - capture.armed,
                    **data,
                )
            elif action == "reset":
                capture.coverage.clear()
                capture.coverage_at = None
                capture.due_at = None
                capture.due_episode_ms = 0
                capture.values.clear()
                capture.value_times.clear()
                capture.labels.clear()
                capture.pressure(False, "context_reset")
                capture.transition(
                    "context",
                    (self._context, self._generation),
                    reason="observed_context_or_generation_invalidation",
                    generation=self._generation,
                    context_available=self._context is not None,
                )
            elif action == "health":
                health = cast(list[object], capture.values.setdefault("health", []))
                if len(health) < 8:
                    label = capture.label(cast(_Recipient, args[0]))
                    health.append((label, *args[1:], capture.exclusions.get(label, "none")))
            elif action == "exclusion":
                label = capture.label(cast(_Recipient, args[0]))
                capture.exclusions[label] = str(args[1])
            elif action == "frame":
                current: dict[int, tuple[str, int]] = {}
                for key in self._recipients[:64]:
                    label = capture.label(key)
                    expires = max(
                        (e.expires for e in self._matching_effects(key, self.SY_IDS).values()),
                        default=0,
                    )
                    hold, submitted = self._holds.get(key, (0, -1))
                    contrary = any(
                        retired.expired_first_seen >= submitted
                        for skill_id in self.SY_IDS
                        if (retired := self._retired_effects.get((*key, skill_id))) is not None
                    )
                    current[label] = (
                        ("observed", expires)
                        if label and expires > capture.now
                        else ("inferred", hold)
                        if label and hold > capture.now and not contrary
                        else ("unknown", 0)
                    )
                capture.observe_coverage(current)
                capture.values["recipient_counts"] = (
                    len(self._recipients),
                    len(self._local_recipients),
                    sum(kind == "unknown" for kind, _ in current.values()),
                )
                capture.value_times["recipient_counts"] = capture.now
                fgj_until = max(
                    (e.expires for key, e in self._effects.items() if key[2] == self._fgj),
                    default=0,
                )
                capture.transition(
                    "fgj_effect",
                    fgj_until > capture.now,
                    skill=self._fgj,
                    evidence="positive_active" if fgj_until > capture.now else "no_positive_evidence",
                    remaining_ms=max(0, fgj_until - capture.now),
                )
                if capture.now - capture.last_status >= 1000:
                    capture.last_status = capture.now
                    capture.event(
                        "status",
                        pressure=self._pressure,
                        last_observed_values=dict(capture.values),
                        observation_ages_ms={key: capture.now - value for key, value in capture.value_times.items()},
                    )
            elif action == "stock":
                name, result = str(args[0]), bool(args[1])
                capture.step(self._now())
                if not capture.active or capture.stop_requested:
                    return
                capture.count(name + "_" + str(result))
                capture.transition(
                    "stock_" + name,
                    result,
                    helper=name,
                    result=result,
                    evidence="attack_request" if name == "AutoAttack" else "helper_admission_not_application",
                )
            elif action == "flush":
                capture.deferred = False
                capture.flush()
        except Exception:
            capture.logger_failures += 1
            capture.state = "FINISHED"
            capture.stop_reason = "recorder_failure"
            capture.pending.clear()

    def _diagnostic_arm(self, now: int) -> None:
        """Only the validated normal controller entry may claim the module's arm."""
        global _diagnostic_consumed
        try:
            if self._capture is None and _DIAGNOSTIC_ARM_ONCE and not _diagnostic_consumed:
                _diagnostic_consumed = True
                self._capture = _Capture(now)
                self._capture.previous["pressure"] = self._pressure
                self._capture.event(
                    "ARMED",
                    owner="My Heroic Refrain",
                    combat_limit_ms=120000,
                    arm_limit_ms=180000,
                    line_limit=400,
                    start="next_pressure_entry",
                )
        except Exception:
            if self._capture is not None:
                self._capture.state = "FINISHED"
                self._capture.stop_reason = "recorder_failure"

    def _diagnostic_step(self, now: int) -> None:
        """Recording may continue in callbacks; stepping never creates a capture."""
        try:
            if self._capture is not None and self._capture.active:
                self._capture.deferred = self._diagnostic_deferred
                self._capture.step(now)
        except Exception:
            if self._capture is not None:
                self._capture.state = "FINISHED"
                self._capture.stop_reason = "recorder_failure"

    def _gate(self, name: str, value: bool) -> bool:
        self._diagnostic("gate", name, value)
        return value

    def ObserveStock(self, helper: str, result: bool) -> None:
        """Observe only an existing return value; never call a gameplay predicate."""
        self._diagnostic("stock", helper, result)

    @staticmethod
    def _now() -> int:
        import PySystem

        return int(PySystem.get_tick_count64())

    def HasSaveYourselves(self) -> bool:
        return any(self._owner.IsSkillEquipped(skill_id) for skill_id in self.SY_IDS)

    def _enabled_sy(self) -> list[int]:
        return [skill_id for skill_id in self.SY_IDS if self._enabled(skill_id)]

    def _enabled(self, skill_id: int) -> bool:
        slot = self._owner.GetEquippedSkillSlot(skill_id)
        return 1 <= slot <= 8 and self._owner.IsSharedSkillToggleEnabled(slot)

    @staticmethod
    def _current_context() -> _Context:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import SkillBar

        get_id = cast(Callable[[int], int], getattr(SkillBar, "GetSkillIDBySlot"))
        return (
            int(Player.GetAgentID()),
            int(Map.GetMapID()),
            int(Map.GetRegion()[0]),
            int(Map.GetDistrict()),
            int(Map.GetLanguage()[0]),
            int(GLOBAL_CACHE.Party.GetPartyID()),
            *(int(profession) for profession in Agent.GetProfessions(Player.GetAgentID())),
            *(int(get_id(slot) or 0) for slot in range(1, 9)),
        )

    def _runtime_available(self) -> bool:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Map

        options = getattr(getattr(self._owner, "_cached_data", None), "account_options", None)
        return (
            self._owner.CanProcess()
            and GLOBAL_CACHE.Party.IsPartyLoaded()
            and not Map.IsInCinematic()
            and (options is None or bool(options.Combat))
        )

    def _finish(
        self,
        request: _Request,
        outcome: str,
        *,
        failed: bool = False,
        useful: bool = False,
    ) -> None:
        if self._request is not request:
            return
        retry = self._retry[request.kind]
        if failed:
            retry.failures += 1
            retry.not_before = self._now() + (1000 if retry.failures == 1 else 5000)
            if request.kind == "myt":
                self._myt_latched = False
        elif useful:
            retry.failures = 0
            retry.not_before = 0
        self.last_outcome = outcome
        self._request = None
        self._diagnostic(
            "request",
            request,
            outcome,
            failed=failed,
            useful_observation=useful,
            retry_failures=retry.failures,
            retry_wait_ms=max(0, retry.not_before - self._last_now),
        )

    def _reset_context(self, context: _Context | None, generation: int) -> None:
        if self._request is not None:
            self._finish(self._request, "context_cancelled")
        self._context = context
        self._generation = generation
        self._effects.clear()
        self._retired_effects.clear()
        self._holds.clear()
        self._alive.clear()
        self._lives.clear()
        self._health.clear()
        self._recipients = ()
        self._pressure = False
        self._myt_latched = False
        self._myt_busy_seen = False
        # A suspend/resume or pressure flicker must not forgive failed attempts.
        self._diagnostic("reset")

    def _update_recipients(self) -> None:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Range

        party = GLOBAL_CACHE.Party
        player = int(Player.GetAgentID())
        heroes = {int(hero.agent_id) for hero in cast("list[HeroPartyMember]", party.GetHeroes())}
        roster = heroes | {int(hench.agent_id) for hench in cast("list[HenchmanPartyMember]", party.GetHenchmen())}
        get_agent = cast(Callable[[int], int], getattr(party.Players, "GetAgentIDByLoginNumber"))
        roster.update(
            int(get_agent(member.login_number)) for member in cast("list[PlayerPartyMember]", party.GetPlayers())
        )
        roster.discard(0)
        roster.discard(player)
        self._local_recipients = heroes
        recipients: list[_Recipient] = []
        for agent_id in set(self._alive) - roster:
            self._alive.pop(agent_id)
            self._lives[agent_id] = self._lives.get(agent_id, 0) + 1
            self._health.pop(agent_id, None)
        for agent_id in sorted(roster):
            alive = bool(Agent.IsAlive(agent_id))
            if self._alive.get(agent_id) is False and alive:
                self._lives[agent_id] = self._lives.get(agent_id, 0) + 1
                self._health.pop(agent_id, None)
            self._alive[agent_id] = alive
            if alive and dist(Agent.GetXY(agent_id), Player.GetXY()) <= Range.Earshot.value:
                recipients.append((agent_id, self._lives.get(agent_id, 0)))
        self._recipients = tuple(recipients)
        live_keys = {(agent_id, self._lives.get(agent_id, 0)) for agent_id in roster if self._alive[agent_id]}
        self._holds = {key: hold for key, hold in self._holds.items() if key in live_keys}
        self._effects = {key: value for key, value in self._effects.items() if key[0] == player or key[:2] in live_keys}
        self._retired_effects = {
            key: value for key, value in self._retired_effects.items() if key[0] == player or key[:2] in live_keys
        }

    def _retire_effect(self, key: _EffectKey, *, expired: bool = False) -> None:
        effect = self._effects.pop(key)
        retired = self._retired_effects.setdefault(key[:3], _RetiredEffects())
        retired.timestamp = max(retired.timestamp, key[4])
        if expired:
            retired.expired_first_seen = max(retired.expired_first_seen, effect.first_seen)

    def _prune_effects(self, now: int) -> None:
        for key, effect in list(self._effects.items()):
            if effect.expires <= now:
                self._retire_effect(key, expired=True)

    def _matching_effects(self, recipient: _Recipient, skill_ids: tuple[int, ...]) -> dict[_EffectKey, _Effect]:
        return {key: effect for key, effect in self._effects.items() if key[:2] == recipient and key[2] in skill_ids}

    def _observe_effects(self, agent_id: int, life: int, skill_ids: tuple[int, ...], now: int) -> None:
        from Py4GWCoreLib import GLOBAL_CACHE

        # GetEffects has no valid-empty-census receipt. Missing entries never prove absence.
        observations: dict[_EffectKey, int] = {}
        for effect in cast("list[EffectType]", GLOBAL_CACHE.Effects.GetEffects(agent_id)) or []:
            skill_id = int(effect.skill_id)
            if skill_id not in skill_ids:
                continue
            remaining = int(effect.time_remaining)
            if remaining < 0:
                continue
            key = (
                agent_id,
                life,
                skill_id,
                int(effect.effect_id),
                int(effect.timestamp),
            )
            retired = self._retired_effects.get(key[:3])
            # A bounded timestamp floor prevents relearning pruned snapshots. It
            # is a conservative rejection rule, not a server-clock conversion:
            # unseen older/equal (including wrapped) stamps remain unknown until
            # context/life reset. Already tracked overlapping instances still age.
            if key not in self._effects and retired is not None and key[4] <= retired.timestamp:
                continue
            observations[key] = min(observations.get(key, remaining), remaining)

        # Process the whole snapshot against the prior retirement floors so list
        # order cannot suppress another usable instance in this same observation.
        for key, remaining in observations.items():
            incarnations = [old_key for old_key in self._effects if old_key[:4] == key[:4]]
            if any(old_key[4] > key[4] for old_key in incarnations):
                continue
            old = self._effects.get(key)
            expires = now + remaining
            if old is not None:
                old.expires = min(old.expires, expires)
            else:
                for old_key in incarnations:
                    self._retire_effect(old_key)
                self._effects[key] = _Effect(now, expires)

        self._prune_effects(now)
        for skill_id in skill_ids:
            instances = self._matching_effects((agent_id, life), (skill_id,))
            # Retain the latest coverage if an anomalously large snapshot exceeds
            # the local budget. Retired identities cannot return as fresh evidence.
            ordered = sorted(instances, key=lambda key: (instances[key].expires, key))
            for key in ordered[: max(0, len(ordered) - self.MAX_EFFECT_INSTANCES)]:
                self._retire_effect(key)

    def _active_effect(self, agent_id: int, skill_id: int, now: int) -> bool:
        recipient = (agent_id, self._lives.get(agent_id, 0))
        return any(effect.expires > now for effect in self._matching_effects(recipient, (skill_id,)).values())

    def _deadline(self, now: int) -> int:
        deadlines: list[int] = []
        for key in self._recipients:
            hold_until, submitted = self._holds.get(key, (now, -1))
            observed = [
                effect.expires for effect in self._matching_effects(key, self.SY_IDS).values() if effect.expires > now
            ]
            contrary = any(
                retired.expired_first_seen >= submitted
                for skill_id in self.SY_IDS
                if (retired := self._retired_effects.get((*key, skill_id))) is not None
            )
            if observed:
                deadlines.append(max(observed) - self.REFRESH_MS)
            else:
                deadlines.append(now if contrary else hold_until)
        return min(deadlines, default=now)

    def _hostile_activity(self) -> bool:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Range

        return any(
            Agent.IsAlive(enemy)
            and (Agent.IsAttacking(enemy) or Agent.IsCasting(enemy))
            and any(
                dist(Agent.GetXY(enemy), Agent.GetXY(recipient)) <= Range.Earshot.value
                for recipient, _ in self._recipients
            )
            for enemy in AgentArray.GetEnemyArray()
        )

    def _update_pressure(self, now: int) -> None:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Utils

        if not self._recipients or not self._owner.IsInAggro():
            self._pressure = False
            self._diagnostic("pressure", False, "no_recipients_or_no_aggro")
            return
        self._diagnostic("value", "health", [])
        samples = self._owner.UpdatePartyHealthMonitor()
        # The existing monitor stamps UTC-midnight milliseconds, not tick_count64.
        # Keep its sample age in that domain; policy deadlines remain monotonic.
        sample_now = int(Utils.GetBaseTimestamp())
        endangered = False
        spike = False
        spread = 0
        spread_new = False
        for agent_id, _ in self._recipients:
            sample = samples.get(agent_id)
            if sample is None:
                continue
            sample_ms = int(sample["sample_ms"])
            health = float(sample["health"])
            loss = float(sample["drop"])
            maximum = int(Agent.GetMaxHealth(agent_id))
            previous = self._health.get(agent_id)
            if previous is None or sample_ms < previous.sample_ms:
                previous = _Health(sample_ms, health, maximum)
                self._health[agent_id] = previous
            if Agent.GetCastingSkillID(agent_id) == self._bip:
                previous.excluded_until = max(previous.excluded_until, now + 750)
                self._diagnostic("exclusion", (agent_id, self._lives.get(agent_id, 0)), "bip")
            if maximum > 0 and previous.maximum > 0 and maximum != previous.maximum:
                previous.excluded_until = max(previous.excluded_until, now + 1000)
                previous.last_loss = -10000
                self._diagnostic(
                    "exclusion",
                    (agent_id, self._lives.get(agent_id, 0)),
                    "max_health_change",
                )
            advancing = sample_ms > previous.sample_ms
            # Freshness is separate from trigger magnitude; only numerical noise
            # is ignored here. Health/accumulated-loss thresholds remain below.
            new_loss = advancing and previous.health - health > 1e-9
            if advancing:
                previous.sample_ms = sample_ms
                previous.health = health
                previous.maximum = maximum
            if now < previous.excluded_until or not 0 <= sample_now - sample_ms <= 450 or not isfinite(health):
                self._diagnostic(
                    "health",
                    (agent_id, self._lives.get(agent_id, 0)),
                    health,
                    loss,
                    sample_now - sample_ms,
                    "excluded_or_stale",
                    max(0, previous.excluded_until - now),
                )
                continue
            self._diagnostic(
                "health",
                (agent_id, self._lives.get(agent_id, 0)),
                health,
                loss,
                sample_now - sample_ms,
                "fresh_loss" if new_loss else "no_new_loss",
                0,
            )
            if new_loss:
                previous.last_loss = now
                endangered |= health <= 0.60
                spike |= loss >= 0.10
            if loss >= 0.05 and now - previous.last_loss <= 1000:
                spread += 1
                spread_new |= new_loss
        hostile = self._hostile_activity()
        entry = endangered or spike or (spread >= 2 and spread_new)
        if hostile and (entry or self._pressure):
            self._pressure = True
            self._last_activity = now
        elif self._pressure and now - self._last_activity >= 2000:
            self._pressure = False
        self._diagnostic("value", "hostile", hostile)
        self._diagnostic("value", "pressure_triggers", (endangered, spike, spread, spread_new))
        self._diagnostic(
            "pressure",
            self._pressure,
            "endangered"
            if endangered
            else "accumulated_loss"
            if spike
            else "spread"
            if spread >= 2 and spread_new
            else "hostile_maintenance"
            if hostile
            else "inactivity_or_no_entry",
        )

    def _resource(self, skill_id: int) -> tuple[int, int] | None:
        from Py4GWCoreLib import SkillBar

        slot = self._owner.GetEquippedSkillSlot(skill_id)
        if not 1 <= slot <= 8:
            if self._capture is not None and self._capture.active:
                self._diagnostic("value", "resource_" + str(skill_id), None)
            return None
        # This owning wrapper constructs a fresh native skillbar snapshot. The
        # global cache's GetSkillData instead returns its retained snapshot.
        get_data = cast("Callable[[int], SkillbarSkill]", getattr(SkillBar, "GetSkillData"))
        data = get_data(slot)
        if int(data.id.id) != skill_id:
            if self._capture is not None and self._capture.active:
                self._diagnostic("value", "resource_" + str(skill_id), None)
            return None
        resource = int(data.adrenaline_a), int(data.recharge)
        if self._capture is not None and self._capture.active:
            self._diagnostic("value", "resource_" + str(skill_id), resource)
        return resource

    def _resource_ready(self, skill_id: int) -> bool:
        from Py4GWCoreLib import GLOBAL_CACHE

        resource = self._resource(skill_id)
        adrenaline_cost = cast(Callable[[int], int], getattr(GLOBAL_CACHE.Skill.Data, "GetAdrenaline"))
        ready = bool(resource is not None and resource[1] == 0 and resource[0] >= adrenaline_cost(skill_id))
        if self._capture is not None and self._capture.active:
            self._diagnostic("readiness", skill_id, ready)
        return ready

    def _observe_request(self, now: int) -> None:
        from Py4GWCoreLib import Player

        request = self._request
        if request is None or request.submitted_ms is None:
            return
        elapsed = now - request.submitted_ms
        if elapsed <= 0:
            return
        if elapsed > self.OBSERVE_MS:
            self._finish(request, "observation_unresolved", failed=True)
            return
        uncontaminated = self._owner.GetLocalActionSequence() == request.action_sequence
        resource = self._resource(request.sy_id)
        self._diagnostic(
            "value",
            "request_resource",
            (
                request.request_id,
                request.pre_adrenaline,
                resource,
                uncontaminated,
                elapsed,
            ),
        )
        if uncontaminated and resource is not None and request.pre_adrenaline is not None:
            if request.kind == "sy" and resource[0] < request.pre_adrenaline:
                current = set(self._recipients)
                for key in request.recipients:
                    if key in current:
                        self._holds[key] = (
                            request.submitted_ms + self.INFERRED_HOLD_MS,
                            request.submitted_ms,
                        )
                self._myt_latched = False
                self._finish(request, "sy_resource_consequence", useful=True)
                return
            if request.kind == "myt" and resource[0] > request.pre_adrenaline:
                self._finish(request, "myt_observed_progress", useful=True)
                return
        if request.kind == "fgj":
            if any(
                effect.expires > now and key not in request.pre_effects
                for key, effect in self._matching_effects((int(Player.GetAgentID()), 0), (self._fgj,)).items()
            ):
                self._finish(request, "fgj_observed_effect", useful=True)
                return
        if request.kind == "sy" and any(
            effect.expires > now and key not in request.pre_effects
            for recipient in request.recipients
            if recipient in self._recipients
            for key, effect in self._matching_effects(recipient, self.SY_IDS).items()
        ):
            self._finish(request, "sy_observed_effect", useful=True)
            return
        if elapsed >= self.OBSERVE_MS:
            self._finish(request, "observation_unresolved", failed=True)

    def Advance(self, *, owner_execution: bool = False) -> bool:
        """Observe without casting; only the selected controller's normal handlers pass owner_execution."""
        from Py4GWCoreLib import Player

        now = self._now()
        self._diagnostic_step(now)
        generation = self._owner.GetPolicyGeneration()
        if not self.HasSaveYourselves():
            self._reset_context(None, generation)
            self._diagnostic("value", "sy_equipped", False)
            return now < self._dispatch_guard_until
        if not self._runtime_available():
            self._reset_context(None, generation)
            return False
        context = self._current_context()
        if context != self._context or generation != self._generation or now < self._last_now:
            self._reset_context(context, generation)
        self._last_now = now
        if owner_execution and not self._diagnostic_deferred:
            self._diagnostic_arm(now)
        self._diagnostic("value", "sy_equipped", True)
        self._update_recipients()
        self._prune_effects(now)
        player = int(Player.GetAgentID())
        self._observe_effects(player, 0, (self._fgj, self._tof), now)
        for agent_id, life in self._recipients:
            if agent_id in self._local_recipients:
                self._observe_effects(agent_id, life, self.SY_IDS, now)
        self._update_pressure(now)
        myt = self._resource(self._myt)
        if myt is not None and myt[1] != 0:
            self._myt_busy_seen = True
        elif myt is not None and self._myt_busy_seen:
            self._myt_latched = False
            self._myt_busy_seen = False
        self._observe_request(now)
        if not self._diagnostic_deferred:
            self._diagnostic("frame")
        request = self._request
        if request is not None and request.submitted_ms is None:
            if not self._pressure or not self._enabled_sy():
                self._finish(request, "demand_cancelled")
            elif request.kind != "sy" and any(self._resource_ready(skill_id) for skill_id in self._enabled_sy()):
                self._finish(request, "preparation_superseded")
            elif now - request.queued_ms >= self.QUEUE_MS:
                self._finish(request, "queue_expired", failed=True)
            else:
                return True
        return now < self._dispatch_guard_until

    def _energy_available(self, skill_id: int, now: int) -> bool:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Routines

        player = int(Player.GetAgentID())
        obligation = 0
        if self._enabled(self._hr) and (
            not self._bootstrap_ready() or self._owner.ResolveAllyTarget(self._hr, self._owner.GetCustomSkill(self._hr))
        ):
            obligation = self._hr
        elif self._enabled(self._tof):
            expires = max(
                (effect.expires for effect in self._matching_effects((player, 0), (self._tof,)).values()),
                default=now,
            )
            if expires - now <= 2000:
                obligation = self._tof
        adjusted_cost = cast(
            Callable[[int, int], float],
            getattr(Routines.Checks.Skills, "GetEnergyCostWithEffects"),
        )
        cost = float(adjusted_cost(skill_id, player))
        reserve = float(adjusted_cost(obligation, player)) if obligation else 0.0
        energy = float(Agent.GetEnergy(player)) * float(Agent.GetMaxEnergy(player))
        self._diagnostic("value", "energy", (skill_id, energy, cost, reserve, obligation))
        return all(isfinite(value) and value >= 0 for value in (cost, reserve, energy)) and energy >= cost + reserve

    def _myt_candidates(self) -> bool:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Range
        from Py4GWCoreLib.HeroAI import utils

        candidates = AgentArray.GetAllyArray() + AgentArray.GetSpiritPetArray()
        is_party_member = cast(Callable[[int], bool], getattr(utils, "IsPartyMember"))
        count = sum(
            1
            for agent_id in candidates
            if dist(Agent.GetXY(agent_id), Player.GetXY()) <= Range.Earshot.value
            and Agent.IsAlive(agent_id)
            and is_party_member(agent_id)
        )
        self._diagnostic("value", "myt_candidates", count)
        return count >= 3

    def _attack_opportunity(self) -> bool:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Range

        return bool(
            Agent.IsAttacking(Player.GetAgentID())
            and any(
                Agent.IsAlive(enemy) and dist(Agent.GetXY(enemy), Player.GetXY()) <= Range.Earshot.value
                for enemy in AgentArray.GetEnemyArray()
            )
        )

    def _select(self, preparation: bool, now: int) -> tuple[_Kind, int, int] | None:
        from Py4GWCoreLib import Player

        enabled = self._enabled_sy()
        self._diagnostic("selection")
        self._diagnostic("value", "enabled_sy", tuple(enabled))
        if (
            not self._gate("sy_enabled", bool(enabled))
            or not self._gate("pressure", self._pressure)
            or not self._gate("recipients", bool(self._recipients))
            or not self._gate("bootstrap", self._bootstrap_ready())
        ):
            self._diagnostic("value", "sy_due", False)
            self._diagnostic("decision", "demand_gate", preparation, 0)
            return None
        ready = [skill_id for skill_id in enabled if self._resource_ready(skill_id)]
        deadline = self._deadline(now)
        self._diagnostic("value", "deadline_remaining_ms", deadline - now)
        self._diagnostic("value", "sy_due", now >= deadline)
        if ready:
            if preparation or now < deadline or now < self._retry["sy"].not_before:
                self._diagnostic(
                    "decision",
                    "sy_ready_boosters_held" if preparation else "sy_coverage_hold" if now < deadline else "sy_backoff",
                    preparation,
                    ready[0],
                )
                return None
            for skill_id in ready:
                if self._owner.CanCastSkillID(skill_id):
                    self._diagnostic("decision", "sy_ready_due", preparation, skill_id)
                    return "sy", skill_id, skill_id
            self._diagnostic("decision", "sy_owner_admission_blocked", preparation, ready[0])
            return None
        if not preparation:
            self._diagnostic("decision", "sy_not_ready", preparation, enabled[0])
            return None
        sy_id = enabled[0]
        if self._resource(sy_id) is None:
            self._diagnostic("decision", "sy_resource_unknown", preparation, sy_id)
            return None
        if (
            self._gate("myt_near_deadline", deadline - now <= self.PREPARE_MS)
            and self._gate("myt_unlatched", not self._myt_latched)
            and self._gate("myt_retry", now >= self._retry["myt"].not_before)
            and self._gate("myt_enabled", self._enabled(self._myt))
            and self._gate("myt_ready", self._resource_ready(self._myt))
            and self._gate("myt_candidates", self._myt_candidates())
            and self._gate("myt_admission", self._owner.CanCastSkillID(self._myt))
            and self._gate("myt_energy", self._energy_available(self._myt, now))
        ):
            self._diagnostic("decision", "myt_near_term_need", preparation, self._myt)
            return "myt", self._myt, sy_id
        if (
            self._gate("fgj_retry", now >= self._retry["fgj"].not_before)
            and self._gate("fgj_enabled", self._enabled(self._fgj))
            and self._gate("fgj_ready", self._resource_ready(self._fgj))
            and self._gate(
                "fgj_no_positive_effect",
                not self._active_effect(int(Player.GetAgentID()), self._fgj, now),
            )
            and self._gate("fgj_attack_opportunity", self._attack_opportunity())
            and self._gate("fgj_admission", self._owner.CanCastSkillID(self._fgj))
            and self._gate("fgj_energy", self._energy_available(self._fgj, now))
        ):
            self._diagnostic("decision", "fgj_ongoing_opportunity", preparation, self._fgj)
            return "fgj", self._fgj, sy_id
        self._diagnostic("decision", "supports_blocked", preparation, 0)
        return None

    def TryCast(self, *, preparation: bool = False) -> bool:
        from Py4GWCoreLib import GLOBAL_CACHE

        if self.Advance():
            self._diagnostic("event", "reservation", reason="pending_queue_or_dispatch_guard")
            return False
        if self._request is not None or not self._runtime_available():
            return False
        now = self._now()
        selection = self._select(preparation, now)
        if selection is None or self._context is None:
            return False
        kind, skill_id, sy_id = selection
        self._next_request += 1
        request = _Request(
            self._next_request,
            self._generation,
            self._context,
            kind,
            skill_id,
            sy_id,
            now,
        )
        self._request = request
        try:
            GLOBAL_CACHE.SkillBar.QueueGuardedUseSkill(lambda native: self._dispatch(request, native))
        except Exception:
            self._finish(request, "queue_exception", failed=True)
            return False
        self._owner.SetTickSuccess()
        self.last_outcome = "queued"
        self._diagnostic("request", request, "queued", evidence="queue_admission_only")
        return True

    def _dispatch(self, request: _Request, native: Callable[[int, int], bool]) -> None:
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Routines
        from Py4GWCoreLib import SkillBar

        if self._request is not request or request.submitted_ms is not None:
            return
        self._diagnostic_deferred = True
        try:
            self.Advance()
            if self._request is not request:
                return
            now = self._now()
            if request.generation != self._owner.GetPolicyGeneration() or request.context != self._current_context():
                self._finish(request, "context_cancelled")
                return
            selection = self._select(request.kind != "sy", now)
            if selection != (request.kind, request.skill_id, request.sy_id):
                self._finish(request, "policy_cancelled")
                return
            slot = self._owner.GetEquippedSkillSlot(request.skill_id)
            get_id = cast(Callable[[int], int], getattr(SkillBar, "GetSkillIDBySlot"))
            target = int(Player.GetAgentID()) if request.kind == "myt" else 0
            if (
                not Routines.Checks.Skills.CanCast()
                or not 1 <= slot <= 8
                or int(get_id(slot)) != request.skill_id
                or not self._owner.AdmitPolicySkill(request.skill_id, target)
            ):
                self._finish(request, "guard_rejected")
                return
            resource = self._resource(request.sy_id)
            if resource is None:
                self._finish(request, "guard_rejected")
                return
            request.pre_adrenaline = resource[0]
            request.recipients = self._recipients
            request.pre_effects = set(self._matching_effects((int(Player.GetAgentID()), 0), (self._fgj,)))
            if request.kind == "sy":
                request.pre_effects = {
                    key for recipient in request.recipients for key in self._matching_effects(recipient, self.SY_IDS)
                }
            dispatch_ms = self._now()
            if dispatch_ms - request.queued_ms >= self.QUEUE_MS:
                self._finish(request, "queue_expired", failed=True)
                return
            request.submitted_ms = dispatch_ms
            try:
                accepted = native(slot, target)
            except Exception:
                self._diagnostic("native", request, "native_exception", evidence="native_call_exception")
                self._dispatch_guard_until = dispatch_ms + self.GUARD_MS
                self._owner.MarkPolicySkillSubmitted(self.GUARD_MS)
                self._finish(request, "native_exception", failed=True)
                return
            self._diagnostic(
                "native",
                request,
                "native_true" if accepted else "native_false",
                evidence="native_acceptance_not_application" if accepted else "native_rejection",
            )
            if not accepted:
                self._finish(request, "native_false", failed=True)
                return
            self._dispatch_guard_until = dispatch_ms + self.GUARD_MS
            self._owner.MarkPolicySkillSubmitted(self.GUARD_MS)
            request.action_sequence = self._owner.GetLocalActionSequence()
            if request.kind == "myt":
                self._myt_latched = True
            self.last_outcome = "submitted"
        except Exception:
            self._finish(request, "dispatch_exception", failed=True)
        finally:
            self._diagnostic_deferred = False
            self._diagnostic("flush")
