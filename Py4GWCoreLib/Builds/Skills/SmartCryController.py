"""Runtime owner for guarded Smart Cry dispatch.

``SmartCry.py`` owns only immutable policy.  This module owns the injected
runtime observations, the action-queue boundary, D0 receipt lifecycle, and
the final native call.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Final
from typing import cast

from Py4GWCoreLib.BuildMgr import BuildMgr
from Py4GWCoreLib.Builds.Skills.SmartCry import DEFAULT_POLICY
from Py4GWCoreLib.Builds.Skills.SmartCry import CryCastKey
from Py4GWCoreLib.Builds.Skills.SmartCry import CryCastObservation
from Py4GWCoreLib.Builds.Skills.SmartCry import CryClassificationProvenance
from Py4GWCoreLib.Builds.Skills.SmartCry import CryDecision
from Py4GWCoreLib.Builds.Skills.SmartCry import CryEnemyObservation
from Py4GWCoreLib.Builds.Skills.SmartCry import CryInterruptEvidence
from Py4GWCoreLib.Builds.Skills.SmartCry import CryOnsetConfidence
from Py4GWCoreLib.Builds.Skills.SmartCry import CrySkillCategory
from Py4GWCoreLib.Builds.Skills.SmartCry import CrySkillClassification
from Py4GWCoreLib.Builds.Skills.SmartCry import evaluate_smart_cry
from Py4GWCoreLib.Builds.Skills.SmartMesmer import CombatSnapshot
from Py4GWCoreLib.Builds.Skills.SmartMesmer import EnemyObservation
from Py4GWCoreLib.Builds.Skills.SmartMesmer import pairwise_squared_distances

CRY_SKILL_NAME: Final[str] = "Cry_of_Frustration"
QUEUE_DEADLINE_MS: Final[int] = 150
POST_SUBMIT_ALLOWANCE_MS: Final[int] = 100
CLAIM_TO_SUBMIT_RESERVE_MS: Final[int] = 25
MAX_REQUIRED_LEASE_MS: Final[int] = 10_100
CONFLICT_SUPPRESSION_MS: Final[int] = 150
ACTIVATION_EVENT_MAX_AGE_MS: Final[int] = 10_000
DIAGNOSTIC_COOLDOWN_MS: Final[int] = 1_000


class CryControllerState(str, Enum):
    IDLE = "idle"
    SELECTED = "selected"
    QUEUED = "queued"
    EXECUTING = "executing"
    CLAIMED = "claimed"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    UNCERTAIN = "uncertain"
    RELEASING = "releasing"


@dataclass(frozen=True, slots=True)
class _CryRequest:
    attempt_id: int
    token: int
    lifecycle_id: tuple[int, int, int]
    composition_generation: int
    bar_generation: int
    owner_email: str
    isolation_group_id: int
    player_agent_id: int
    primary_agent_id: int
    enemy_skill_id: int
    observation_identity: tuple[int, ...] | None
    covered_cast_keys: tuple[CryCastKey, ...]
    enqueue_tick: int
    deadline_tick: int
    candidate_value: int


@dataclass(frozen=True, slots=True)
class _LifecycleInputs:
    map_id: int
    player_agent_id: int
    instance_uptime_ms: int
    owner_email: str
    isolation_group_id: int


@dataclass(frozen=True, slots=True)
class _OwnerContextResult:
    context: tuple[str, int] | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class _Selection:
    decision: CryDecision
    snapshot: CombatSnapshot
    primary_assessment: Any
    runtime_rejection_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _CapturedSelection:
    request: _CryRequest
    selection: _Selection
    proposal: Any


@dataclass(frozen=True, slots=True)
class _ValidationFailure:
    reason: str
    details: tuple[Any, ...] = ()


class ActivationEvidenceAdapter:
    """Adapt matching PyAgentEvents activation records into CastObserver onset.

    The adapter uses only local event identity.  It deliberately does not
    invent a global cast-instance identifier, and a missing event keeps strict
    interrupt assessment fail-closed.
    """

    def __init__(
        self,
        *,
        max_age_ms: int = ACTIVATION_EVENT_MAX_AGE_MS,
        max_seen_events: int = 128,
    ) -> None:
        self._max_age_ms = max(0, int(max_age_ms))
        self._seen_event_keys: set[tuple[int, int, int, int, int, float]] = set()
        self._seen_event_order: deque[tuple[int, int, int, int, int, float]] = deque(
            maxlen=max(1, int(max_seen_events))
        )
        self._latest_activation_by_agent: dict[int, tuple[int, int]] = {}
        self._conflicted_agents: set[int] = set()
        self._conflict_timestamp_by_agent: dict[int, int] = {}
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def update(self, now_ms: int, cast_observer: Any) -> bool:
        """Read and deduplicate the current event buffer without consuming it."""

        try:
            import PyAgentEvents

            peek_events = getattr(PyAgentEvents, "peek_events", None)
            event_type_module = getattr(PyAgentEvents, "PyEventType", None)
            activated_type = getattr(event_type_module, "SKILL_ACTIVATED", None)
            if not callable(peek_events) or activated_type is None:
                self._available = False
                return False
            raw_events: Any = peek_events()
            events = list(raw_events or [])
        except Exception:
            self._available = False
            return False

        self._available = True
        now_value = int(now_ms)
        for event in events:
            try:
                timestamp = int(getattr(event, "timestamp", -1))
                event_type = int(getattr(event, "event_type", 0))
                agent_id = int(getattr(event, "agent_id", 0))
                skill_id = int(getattr(event, "value", 0))
                target_id = int(getattr(event, "target_id", 0))
                float_value = float(getattr(event, "float_value", 0.0))
            except (TypeError, ValueError, OverflowError):
                continue
            if event_type != int(activated_type):
                continue
            if agent_id <= 0 or skill_id <= 0 or timestamp < 0:
                continue
            if timestamp > now_value or now_value - timestamp > self._max_age_ms:
                continue
            if not math.isfinite(float_value):
                float_value = 0.0
            key = (timestamp, event_type, agent_id, skill_id, target_id, float_value)
            if not self._remember_event(key):
                continue
            conflict_timestamp = self._conflict_timestamp_by_agent.get(agent_id)
            if conflict_timestamp is not None and timestamp <= conflict_timestamp:
                continue
            latest = self._latest_activation_by_agent.get(agent_id)
            if latest is not None:
                latest_skill_id, latest_timestamp = latest
                if timestamp < latest_timestamp:
                    continue
                if timestamp == latest_timestamp and skill_id != latest_skill_id:
                    self._latest_activation_by_agent.pop(agent_id, None)
                    self._conflicted_agents.add(agent_id)
                    self._conflict_timestamp_by_agent[agent_id] = timestamp
                    continue
            self._conflicted_agents.discard(agent_id)
            self._conflict_timestamp_by_agent.pop(agent_id, None)
            self._latest_activation_by_agent[agent_id] = (skill_id, timestamp)
            try:
                cast_observer.record_observed_onset(
                    agent_id,
                    skill_id,
                    timestamp,
                    observed_at_ms=now_value,
                )
            except Exception:
                continue

        self._discard_stale_latest(now_value)
        return True

    def matches(self, agent_id: int, skill_id: int, now_ms: int) -> bool:
        if int(agent_id) in self._conflicted_agents:
            return False
        latest = self._latest_activation_by_agent.get(int(agent_id))
        if latest is None:
            return False
        latest_skill_id, latest_timestamp = latest
        return latest_skill_id == int(skill_id) and 0 <= int(now_ms) - latest_timestamp <= self._max_age_ms

    def _remember_event(self, key: tuple[int, int, int, int, int, float]) -> bool:
        if key in self._seen_event_keys:
            return False
        if len(self._seen_event_order) == self._seen_event_order.maxlen:
            oldest = self._seen_event_order.popleft()
            self._seen_event_keys.discard(oldest)
        self._seen_event_order.append(key)
        self._seen_event_keys.add(key)
        return True

    def _discard_stale_latest(self, now_ms: int) -> None:
        stale_agents = [
            agent_id
            for agent_id, (_skill_id, timestamp) in self._latest_activation_by_agent.items()
            if now_ms < timestamp or now_ms - timestamp > self._max_age_ms
        ]
        for agent_id in stale_agents:
            self._latest_activation_by_agent.pop(agent_id, None)
            self._conflicted_agents.discard(agent_id)
            self._conflict_timestamp_by_agent.pop(agent_id, None)


Cry_of_Frustration_ID: int = 0


def get_cry_of_frustration_id() -> int:
    """Resolve Cry lazily so policy-only imports remain offline-safe."""

    global Cry_of_Frustration_ID
    if not Cry_of_Frustration_ID:
        from Py4GWCoreLib.Skill import Skill

        Cry_of_Frustration_ID = int(Skill.GetID(CRY_SKILL_NAME))
    return int(Cry_of_Frustration_ID)


class SmartCryController(BuildMgr):
    """Runtime controller for one guarded, D0-coordinated Cry attempt."""

    def __init__(
        self,
        match_only: bool = False,
        *,
        skill_id: int | None = None,
        queue_deadline_ms: int = QUEUE_DEADLINE_MS,
    ) -> None:
        from Py4GWCoreLib import Profession

        self._cry_skill_id = int(skill_id or get_cry_of_frustration_id())
        super().__init__(
            name="Smart Cry",
            required_primary=Profession.Mesmer,
            required_secondary=Profession(0),
            template_code="OQBCAswEc5Jw0zuoNopTOggD",
            required_skills=[self._cry_skill_id],
            optional_skills=[],
            is_template_only=True,
        )
        if match_only:
            return

        self._disposed = False
        self._skill_slot: int | None = None
        self._state = CryControllerState.IDLE
        self._request: _CryRequest | None = None
        self._captured_selection: _CapturedSelection | None = None
        self._capture_proposal = False
        self._receipt: Any = None
        self._token_counter = 0
        self._attempt_counter = 0
        self._composition_generation = 0
        self._previous_composition_generation: int | None = None
        self._bar_generation = 0
        self._local_generation = 0
        self._lifecycle_id: tuple[int, int, int] | None = None
        self._last_lifecycle_inputs: _LifecycleInputs | None = None
        self._last_instance_uptime_ms: int | None = None
        self._native_invocation_entered = False
        self._native_result: bool | None = None
        self._post_submit_deadline: int | None = None
        self._activation_evidence = ActivationEvidenceAdapter()
        self._suppressed_cast_keys: tuple[CryCastKey, ...] = ()
        self._suppression_deadline: int | None = None
        self._diagnostic_state: dict[str, tuple[int, tuple[Any, ...]]] = {}
        self._preclaim_failure: _ValidationFailure | None = None
        self._selection_failure_reason: str | None = None
        self._queue_deadline_ms = max(0, int(queue_deadline_ms))

    @property
    def skill_id(self) -> int:
        return self._cry_skill_id

    @property
    def skill_slot(self) -> int | None:
        return self._skill_slot

    @property
    def state(self) -> CryControllerState:
        return self._state

    @property
    def d0_receipt(self) -> Any:
        return self._receipt

    @property
    def native_result(self) -> bool | None:
        return self._native_result

    @property
    def pending_request(self) -> _CryRequest | None:
        return self._request

    def has_active_dispatch(self) -> bool:
        return self._has_active_dispatch()

    def build_interrupt_proposal(self) -> Any | None:
        """Capture the existing selection before the shared queue boundary."""

        if not hasattr(self, "_state") or self._disposed or self._has_active_work():
            return None
        self._captured_selection = None
        self._capture_proposal = True
        try:
            for _ in self.try_cast():
                pass
        finally:
            self._capture_proposal = False
        captured = self._captured_selection
        return None if captured is None else captured.proposal

    def discard_interrupt_proposal(self, proposal: Any) -> None:
        captured = self._captured_selection
        if captured is not None and captured.proposal is proposal:
            self._captured_selection = None

    def try_cast_selected(self, proposal: Any) -> Generator[None, None, bool]:
        """Queue one previously captured proposal through the normal callback."""

        if False:
            yield
        if not hasattr(self, "_state") or self._disposed:
            return False
        if self._request is not None:
            return True
        if self._receipt is not None:
            return False
        captured = self._captured_selection
        if captured is None or captured.proposal is not proposal:
            return False
        self._captured_selection = None
        now_ms = self._now_ms()
        if now_ms is None:
            return False
        self._refresh_lifecycle()
        self._maintain_state(now_ms)
        if self._has_active_work() or not self._captured_selection_is_current(captured, now_ms):
            return False
        if not self._selection_dispatch_allowed(captured, now_ms):
            return False
        try:
            return self._queue_captured_selection(captured, now_ms)
        except Exception:
            self._drop_request("selection_dispatch_exception")
            return False

    def set_skill_slot(self, slot_index: int | None) -> None:
        new_slot = None if slot_index is None else int(slot_index)
        if new_slot is not None and not 1 <= new_slot <= 8:
            new_slot = None
        if new_slot == self._skill_slot:
            return
        self._skill_slot = new_slot
        self._bar_generation += 1
        self._invalidate_work("bar_slot_changed")

    def update_lifecycle(self, context: Any = None) -> None:
        """Refresh lifecycle identity and maintain finite queued/receipt state."""

        if not hasattr(self, "_state"):
            return
        try:
            if context is not None:
                composition_generation = int(context)
                if (
                    self._previous_composition_generation is not None
                    and composition_generation != self._previous_composition_generation
                ):
                    self._composition_generation = composition_generation
                    self._invalidate_work("composition_generation_changed")
                else:
                    self._composition_generation = composition_generation
                self._previous_composition_generation = composition_generation
            self._refresh_lifecycle()
            now_ms = self._now_ms()
            if now_ms is not None:
                self._maintain_state(now_ms)
        except Exception as error:
            self._emit_diagnostic("lifecycle_exception", (type(error).__name__,))

    def try_cast(self) -> Generator[None, None, bool]:
        """Select and queue one request, or report an already-owned attempt."""

        if False:
            yield
        if not hasattr(self, "_state") or self._disposed:
            return False
        now_ms = self._now_ms()
        if now_ms is None:
            self._emit_diagnostic("declined", ("clock_unavailable",))
            return False
        self._refresh_lifecycle()
        self._maintain_state(now_ms)
        if self._has_active_dispatch():
            if self._request is not None and self._receipt is None and not self._combat_option_enabled():
                self._drop_request("combat_disabled")
                return False
            return True
        if self._receipt is not None:
            return False

        try:
            from Py4GWCoreLib.HeroAI import interrupt

            if not self._combat_option_enabled():
                self._emit_diagnostic("declined", ("combat_disabled",), now_ms=now_ms)
                return False
            self._activation_evidence.update(now_ms, interrupt.cast_observer)
            owner_context = self._local_owner_context_result()
            if owner_context.context is None:
                self._emit_diagnostic(
                    "declined",
                    (owner_context.reason or "owner_context_lookup_failed",),
                )
                return False
            if self._lifecycle_id is None:
                self._emit_diagnostic("declined", ("lifecycle_missing",))
                return False
            owner_email, isolation_group_id = owner_context.context
            handled_cast_keys = self._handled_cast_keys(isolation_group_id, now_ms)
            selection = self._build_selection(now_ms, handled_cast_keys)
            if selection is None or selection.decision.selected is None:
                self._emit_diagnostic(
                    "declined",
                    self._selection_diagnostic_signature(selection),
                    now_ms=now_ms,
                    windowed=True,
                )
                return False

            selected = selection.decision.selected
            assessment = selection.primary_assessment
            if assessment is None:
                self._emit_diagnostic("declined", ("missing_primary_assessment",))
                return False
            queue_window = self._safe_queue_window_ms(assessment)
            if queue_window <= 0:
                self._emit_diagnostic("declined", ("queue_window_expired",))
                return False

            self._attempt_counter += 1
            self._token_counter += 1
            cast_key = next(
                (
                    key
                    for key in selected.covered_cast_keys
                    if key.enemy_agent_id == selected.primary_agent_id
                    and key.enemy_skill_id == selected.primary_enemy_skill_id
                ),
                None,
            )
            if cast_key is None:
                self._emit_diagnostic(
                    "declined",
                    ("primary_covered_key_missing",),
                    now_ms=now_ms,
                    windowed=True,
                )
                return False
            if cast_key.observation_identity is None:
                self._emit_diagnostic(
                    "declined",
                    ("primary_observation_identity_missing",),
                    now_ms=now_ms,
                    windowed=True,
                )
                return False
            request = _CryRequest(
                attempt_id=self._attempt_counter,
                token=self._token_counter,
                lifecycle_id=self._lifecycle_id,
                composition_generation=self._composition_generation,
                bar_generation=self._bar_generation,
                owner_email=owner_email,
                isolation_group_id=isolation_group_id,
                player_agent_id=int(self._lifecycle_id[1]),
                primary_agent_id=int(selected.primary_agent_id),
                enemy_skill_id=int(selected.primary_enemy_skill_id),
                observation_identity=cast_key.observation_identity,
                covered_cast_keys=tuple(selected.covered_cast_keys),
                enqueue_tick=now_ms,
                deadline_tick=now_ms + min(self._queue_deadline_ms, queue_window),
                candidate_value=int(selected.total_interrupt_value),
            )
            if request.deadline_tick <= now_ms:
                self._emit_diagnostic("declined", ("queue_deadline",))
                return False

            if self._capture_proposal:
                proposal = self._adapt_selection_proposal(selection)
                if proposal is None:
                    return False
                self._captured_selection = _CapturedSelection(request, selection, proposal)
                return False

            return self._queue_selection_request(request, selected, now_ms)
        except Exception as error:
            self._drop_request("selection_exception")
            self._emit_diagnostic("declined", ("selection_exception", type(error).__name__))
            return False

    def cancel_pending(self, reason: str) -> None:
        if not hasattr(self, "_state"):
            return
        self._invalidate_work(reason)
        now_ms = self._now_ms()
        if now_ms is not None:
            self._maintain_state(now_ms)

    def dispose(self, reason: str = "handler_disposed") -> None:
        if not hasattr(self, "_state") or self._disposed:
            return
        self._disposed = True
        self._invalidate_work(reason)
        now_ms = self._now_ms()
        if now_ms is not None:
            self._maintain_state(now_ms)

    def OnContractActivated(self, cached_data: Any = None) -> None:
        if not hasattr(self, "_state"):
            return
        self._disposed = False
        activate = getattr(super(), "OnContractActivated", None)
        if callable(activate):
            activate(cached_data)
        elif cached_data is not None:
            self.set_cached_data(cached_data)

    def _queue_guarded_request(self, request: _CryRequest) -> None:
        from Py4GWCoreLib import GLOBAL_CACHE

        def callback(native_use: Callable[[int, int], bool]) -> None:
            self._on_guarded_action(request.token, native_use)

        queue_guarded = getattr(GLOBAL_CACHE.SkillBar, "QueueGuardedUseSkill", None)
        if not callable(queue_guarded):
            raise RuntimeError("guarded Skillbar dispatch is unavailable")
        queue_guarded(callback)

    def _on_guarded_action(
        self,
        token: int,
        native_use: Callable[[int, int], bool],
    ) -> None:
        """Own every ordinary exception because ActionQueue does not."""

        request = self._request
        if request is None or request.token != token:
            self._emit_diagnostic(
                "preclaim_failed",
                ("reason=request_invalid", f"token={token}"),
                now_ms=self._now_ms(),
                windowed=True,
            )
            return
        now_ms = self._now_ms()
        if now_ms is None:
            self._drop_preclaim_request(request, "clock_unavailable")
            return
        request_failure = self._request_current_failure_reason(request, now_ms, enforce_deadline=True)
        if request_failure is not None:
            self._drop_preclaim_request(request, request_failure)
            return
        self._state = CryControllerState.EXECUTING
        self._emit_diagnostic("callback_start", (request.attempt_id, token), now_ms=now_ms)
        try:
            from Py4GWCoreLib.HeroAI import interrupt

            if not self._combat_option_enabled():
                self._drop_preclaim_request(request, "combat_disabled")
                return
            self._activation_evidence.update(now_ms, interrupt.cast_observer)
            self._preclaim_failure = None
            assessment = self._preclaim_validate(request, now_ms)
            if assessment is None:
                failure = self._preclaim_failure or _ValidationFailure("validation_unavailable")
                self._drop_preclaim_request(request, failure.reason, *failure.details)
                return

            lease_ms = self._required_lease_ms(assessment, now_ms)
            if lease_ms is None:
                self._drop_request("lease_infeasible")
                return
            expires_at_tick = now_ms + lease_ms
            claim_result, claim_reason = self._try_claim(request, expires_at_tick)
            receipt = self._receipt_from_claim_result(claim_result)
            self._emit_diagnostic(
                "d0_result",
                (request.attempt_id, claim_reason, receipt is not None),
                now_ms=now_ms,
            )
            if receipt is None or not self._receipt_matches_request(receipt, request):
                if claim_reason == "conflict":
                    self._suppress_conflict(request, now_ms)
                self._drop_request("d0_rejected")
                return

            self._receipt = receipt
            self._state = CryControllerState.CLAIMED
            if not self._combat_option_enabled():
                self._release_receipt("combat_disabled_after_claim")
                return
            final_assessment = self._post_claim_validate(request, receipt)
            if final_assessment is None:
                self._emit_diagnostic(
                    "postclaim_failed",
                    self._postclaim_diagnostic_signature(request, "post_claim_validation"),
                    now_ms=self._now_ms(),
                    windowed=True,
                )
                self._release_receipt("post_claim_validation")
                return
            self._emit_diagnostic(
                "postclaim_validated",
                (
                    request.attempt_id,
                    int(receipt.expires_at_tick64) - int(self._now_ms() or now_ms),
                ),
                now_ms=self._now_ms(),
            )

            slot = self._resolve_current_slot()
            if slot is None:
                self._release_receipt("slot_unavailable_before_native")
                return
            if self._final_native_boundary_validate(request, receipt) is None:
                self._emit_diagnostic(
                    "postclaim_failed",
                    self._postclaim_diagnostic_signature(request, "final_native_boundary"),
                    now_ms=self._now_ms(),
                    windowed=True,
                )
                self._release_receipt("final_native_boundary")
                return

            self._state = CryControllerState.SUBMITTING
            self._native_invocation_entered = True
            try:
                returned = native_use(int(slot), int(request.primary_agent_id))
                self._native_result = bool(returned)
            except Exception as error:
                self._native_result = None
                self._mark_submission_uncertain(request, f"native_exception:{type(error).__name__}")
                return

            self._pending_request_finished_after_native(request)
        except Exception as error:
            if self._receipt is not None and self._native_invocation_entered:
                self._mark_submission_uncertain(request, f"callback_after_native:{type(error).__name__}")
            elif self._receipt is not None:
                self._release_receipt("callback_exception")
            else:
                self._drop_request("callback_exception")
            self._emit_diagnostic("callback_exception", (request.attempt_id, type(error).__name__))

    def _preclaim_validate(self, request: _CryRequest, now_ms: int) -> Any | None:
        self._preclaim_failure = None
        request_failure = self._request_current_failure_reason(request, now_ms, enforce_deadline=True)
        if request_failure is not None:
            return self._record_validation_failure(request_failure)
        if not self._combat_option_enabled():
            return self._record_validation_failure("combat_disabled")
        if not self._runtime_gate():
            return self._record_validation_failure("runtime_gate")
        if self._local_owner_context() != (request.owner_email, request.isolation_group_id):
            return self._record_validation_failure("owner_context")
        if self._lifecycle_id != request.lifecycle_id:
            return self._record_validation_failure("lifecycle_changed")
        slot = self._resolve_current_slot()
        if slot is None:
            return self._record_validation_failure("cry_slot_changed")
        if not self._skill_readiness(slot):
            return self._record_validation_failure("skill_unready", f"slot={slot}")
        target_failure = self._target_current_failure_reason(
            request.primary_agent_id,
            request.enemy_skill_id,
        )
        if target_failure is not None:
            return self._record_validation_failure(
                target_failure,
                f"target={request.primary_agent_id}",
                f"skill={request.enemy_skill_id}",
            )
        if not self._activation_evidence.matches(request.primary_agent_id, request.enemy_skill_id, now_ms):
            return self._record_validation_failure(
                "onset_unmatched",
                f"target={request.primary_agent_id}",
                f"skill={request.enemy_skill_id}",
            )
        assessment = self._strict_assessment(request.primary_agent_id, now_ms)
        if assessment is None:
            return self._record_validation_failure("assessment_unavailable")
        if not bool(getattr(assessment, "feasible", False)):
            assessment_reason = getattr(getattr(assessment, "reason", None), "value", None)
            return self._record_validation_failure(
                "assessment_infeasible",
                f"assessment_reason={assessment_reason or 'unknown'}",
            )
        if int(getattr(assessment, "enemy_skill_id", 0) or 0) != request.enemy_skill_id:
            return self._record_validation_failure("target_skill_changed")
        if getattr(assessment, "observation_identity", None) != request.observation_identity:
            return self._record_validation_failure("observation_changed")
        if self._safe_queue_window_ms(assessment) <= 0:
            return self._record_validation_failure("insufficient_remaining_window")
        return assessment

    def _post_claim_validate(self, request: _CryRequest, receipt: Any) -> Any | None:
        now_ms = self._now_ms()
        if now_ms is None:
            return None
        if not self._request_is_current(request, now_ms, enforce_deadline=False):
            return None
        if not self._combat_option_enabled():
            return None
        if not self._receipt_is_live(receipt, now_ms):
            return None
        if not self._runtime_gate():
            return None
        if self._local_owner_context() != (request.owner_email, request.isolation_group_id):
            return None
        if self._lifecycle_id != request.lifecycle_id:
            return None
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return None
        if not self._target_is_current(request.primary_agent_id, receipt.enemy_skill_id):
            return None
        if not self._activation_evidence.matches(request.primary_agent_id, receipt.enemy_skill_id, now_ms):
            return None
        assessment = self._strict_assessment(request.primary_agent_id, now_ms)
        if assessment is None or not bool(getattr(assessment, "feasible", False)):
            return None
        if int(getattr(assessment, "enemy_skill_id", 0) or 0) != int(receipt.enemy_skill_id):
            return None
        if getattr(assessment, "observation_identity", None) != request.observation_identity:
            return None

        from Py4GWCoreLib.HeroAI import interrupt

        self._activation_evidence.update(now_ms, interrupt.cast_observer)
        selection = self._build_selection(
            now_ms,
            self._handled_cast_keys(
                request.isolation_group_id,
                now_ms,
                exclude_receipt=receipt,
            ),
        )
        if selection is None or selection.decision.selected is None:
            return None
        selected = selection.decision.selected
        if not self._selected_candidate_is_valid(selected, request, receipt):
            return None
        if request.observation_identity is None:
            return None
        selected_primary_key = next(
            (
                key
                for key in selected.covered_cast_keys
                if key.enemy_agent_id == request.primary_agent_id and key.enemy_skill_id == int(receipt.enemy_skill_id)
            ),
            None,
        )
        if selected_primary_key is None or selected_primary_key.observation_identity != request.observation_identity:
            return None

        required_lease_ms = self._required_lease_ms(assessment, now_ms)
        if required_lease_ms is None:
            return None
        remaining_lease_ms = int(receipt.expires_at_tick64) - now_ms
        minimum_remaining_ms = int(getattr(assessment, "interrupt_budget_ms", 0) or 0) + POST_SUBMIT_ALLOWANCE_MS
        if remaining_lease_ms < minimum_remaining_ms:
            return None
        return assessment

    def _final_native_boundary_validate(self, request: _CryRequest, receipt: Any) -> int | None:
        """Prove current permission, timing, and receipt coverage immediately before native entry."""

        validation_now = self._now_ms()
        if validation_now is None:
            return None
        if not self._request_is_current(request, validation_now, enforce_deadline=False):
            return None
        if not self._combat_option_enabled():
            return None
        if not self._receipt_matches_request(receipt, request) or not self._receipt_is_live(receipt, validation_now):
            return None
        minimum_remaining_ms = CLAIM_TO_SUBMIT_RESERVE_MS + POST_SUBMIT_ALLOWANCE_MS
        if int(receipt.expires_at_tick64) - validation_now < minimum_remaining_ms:
            return None
        if not self._activation_evidence.matches(request.primary_agent_id, request.enemy_skill_id, validation_now):
            return None

        assessment = self._strict_assessment(request.primary_agent_id, validation_now)
        if assessment is None or not bool(getattr(assessment, "feasible", False)):
            return None
        if int(getattr(assessment, "enemy_skill_id", 0) or 0) != request.enemy_skill_id:
            return None
        if getattr(assessment, "observation_identity", None) != request.observation_identity:
            return None
        if self._required_lease_ms(assessment, validation_now) is None:
            return None
        if self._safe_queue_window_ms(assessment) <= 0:
            return None

        final_now = self._now_ms()
        if final_now is None:
            return None
        if not self._request_is_current(request, final_now, enforce_deadline=False):
            return None
        if not self._combat_option_enabled():
            return None
        if not self._receipt_matches_request(receipt, request) or not self._receipt_is_live(receipt, final_now):
            return None
        if int(receipt.expires_at_tick64) - final_now < minimum_remaining_ms:
            return None
        return final_now

    def _pending_request_finished_after_native(self, request: _CryRequest) -> None:
        now_ms = self._now_ms()
        self._request = None
        self._post_submit_deadline = None
        self._state = CryControllerState.SUBMITTED if self._native_result is True else CryControllerState.UNCERTAIN
        result_label = "wrapper_true" if self._native_result is True else "wrapper_false_uncertain"
        self._emit_diagnostic(
            "native_result",
            (request.attempt_id, result_label),
            now_ms=now_ms,
        )

    def _mark_submission_uncertain(self, request: _CryRequest, reason: str) -> None:
        now_ms = self._now_ms()
        self._request = None
        self._post_submit_deadline = None
        self._state = CryControllerState.UNCERTAIN
        self._emit_diagnostic(
            "native_uncertain",
            (request.attempt_id, reason),
            now_ms=now_ms,
        )

    def _build_selection(
        self,
        now_ms: int,
        handled_cast_keys: set[CryCastKey],
    ) -> _Selection | None:
        self._selection_failure_reason = None
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Range

        player_position = self._position(Player.GetXY())
        if player_position is None:
            return self._record_selection_failure("player_geometry_unavailable")
        try:
            cry_radius = float(GLOBAL_CACHE.Skill.Data.GetAoERange(self.skill_id))
            cast_range = float(Range.Spellcast.value)
        except (AttributeError, TypeError, ValueError):
            return self._record_selection_failure("skill_geometry_unavailable")
        if not math.isfinite(cry_radius) or cry_radius <= 0.0 or not math.isfinite(cast_range) or cast_range <= 0.0:
            return self._record_selection_failure("skill_geometry_invalid")

        try:
            raw_enemy_ids = AgentArray.GetEnemyArray()
        except Exception:
            return self._record_selection_failure("enemy_array_unavailable")
        enemy_observations: list[CryEnemyObservation] = []
        geometry_observations: list[EnemyObservation] = []
        assessment_by_agent: dict[int, Any] = {}
        try:
            from Py4GWCoreLib.HeroAI import interrupt
        except Exception:
            return self._record_selection_failure("interrupt_unavailable")

        seen_ids: set[int] = set()
        runtime_rejections: dict[str, int] = {}

        def count_runtime_rejection(reason: str) -> None:
            runtime_rejections[reason] = runtime_rejections.get(reason, 0) + 1

        for raw_agent_id in raw_enemy_ids or ():
            try:
                agent_id = int(raw_agent_id)
            except (TypeError, ValueError):
                count_runtime_rejection("invalid_enemy")
                continue
            if agent_id <= 0:
                count_runtime_rejection("invalid_enemy")
                continue
            if agent_id in seen_ids:
                count_runtime_rejection("duplicate_enemy")
                continue
            seen_ids.add(agent_id)
            try:
                if not Agent.IsValid(agent_id):
                    count_runtime_rejection("invalid_enemy")
                    continue
                if Agent.IsDead(agent_id):
                    count_runtime_rejection("dead_enemy")
                    continue
                if not self._is_enemy(agent_id):
                    count_runtime_rejection("non_hostile_enemy")
                    continue
                position = self._position(Agent.GetXY(agent_id))
                if position is None:
                    count_runtime_rejection("geometry_unavailable")
                    continue
                distance = math.hypot(position[0] - player_position[0], position[1] - player_position[1])
                if not math.isfinite(distance):
                    count_runtime_rejection("geometry_invalid")
                    continue
                geometry = EnemyObservation(agent_id, position[0], position[1])
                current_cast: CryCastObservation | None = None
                if bool(Agent.IsCasting(agent_id)):
                    enemy_skill_id = int(Agent.GetCastingSkillID(agent_id) or 0)
                    if enemy_skill_id > 0:
                        observation = interrupt.cast_observer.get_observation(agent_id, enemy_skill_id)
                        assessment = None
                        if self._activation_evidence.matches(agent_id, enemy_skill_id, now_ms):
                            assessment = self._strict_assessment(agent_id, now_ms)
                        if assessment is not None:
                            assessment_by_agent[agent_id] = assessment
                        current_cast = CryCastObservation(
                            enemy_skill_id=enemy_skill_id,
                            interrupt=self._to_interrupt_evidence(
                                agent_id,
                                enemy_skill_id,
                                assessment,
                                observation,
                            ),
                            classification=self._classify_enemy_skill(enemy_skill_id),
                        )
                enemy_observations.append(
                    CryEnemyObservation(
                        observation=geometry,
                        distance_from_player=distance,
                        is_alive=True,
                        is_hostile=True,
                        target_allowed=self._target_is_allowed(agent_id),
                        current_cast=current_cast,
                    )
                )
                geometry_observations.append(geometry)
            except Exception:
                count_runtime_rejection("runtime_read_failure")
                continue

        lifecycle_id = self._lifecycle_id
        if lifecycle_id is None:
            return self._record_selection_failure("lifecycle_missing")
        if not enemy_observations:
            count_runtime_rejection("no_enemy_observation")
        snapshot = CombatSnapshot(
            enemies=tuple(geometry_observations),
            observed_at=float(now_ms) / 1000.0,
            lifecycle_id=lifecycle_id,
        )
        decision = evaluate_smart_cry(
            snapshot,
            enemy_observations,
            cry_radius=cry_radius,
            cast_range=cast_range,
            pairwise_distances=pairwise_squared_distances(snapshot),
            handled_cast_keys=handled_cast_keys,
            policy=self._selection_policy(),
        )
        if decision.selected is None:
            return _Selection(
                decision,
                snapshot,
                None,
                tuple(sorted(runtime_rejections.items())),
            )
        primary_assessment = assessment_by_agent.get(decision.selected.primary_agent_id)
        return _Selection(
            decision,
            snapshot,
            primary_assessment,
            tuple(sorted(runtime_rejections.items())),
        )

    def _record_selection_failure(self, reason: str) -> None:
        self._selection_failure_reason = str(reason)
        return None

    def _selection_policy(self) -> Any:
        return DEFAULT_POLICY

    def _adapt_selection_proposal(self, selection: _Selection) -> Any | None:
        from Py4GWCoreLib.Builds.Skills.SmartInterruptChooser import SmartCryInterruptProposal

        try:
            return SmartCryInterruptProposal._from_canonical_decision(
                selection.decision,
                interrupt_skill_id=self.skill_id,
            )
        except (TypeError, ValueError):
            return None

    def _selection_dispatch_allowed(self, captured: _CapturedSelection, now_ms: int) -> bool:
        del captured, now_ms
        return True

    def _captured_selection_is_current(self, captured: _CapturedSelection, now_ms: int) -> bool:
        request = captured.request
        return (
            not self._disposed
            and now_ms < request.deadline_tick
            and self._token_counter == request.token
            and self._lifecycle_id == request.lifecycle_id
            and self._composition_generation == request.composition_generation
            and self._bar_generation == request.bar_generation
        )

    def _queue_captured_selection(self, captured: _CapturedSelection, now_ms: int) -> bool:
        request = captured.request
        selected = captured.selection.decision.selected
        if selected is None:
            return False
        return self._queue_selection_request(request, selected, now_ms)

    def _queue_selection_request(self, request: _CryRequest, selected: Any, now_ms: int) -> bool:
        self._request = request
        self._state = CryControllerState.SELECTED
        self._emit_diagnostic(
            "selected",
            (
                request.attempt_id,
                request.primary_agent_id,
                request.enemy_skill_id,
                request.candidate_value,
                *self._candidate_policy_diagnostic_signature(selected),
                tuple(
                    (key.enemy_agent_id, key.enemy_skill_id, key.observation_identity)
                    for key in request.covered_cast_keys
                ),
            ),
            now_ms=now_ms,
        )
        self._queue_guarded_request(request)
        self._state = CryControllerState.QUEUED
        self._emit_diagnostic(
            "enqueued",
            (request.attempt_id, request.token, request.deadline_tick),
            now_ms=now_ms,
        )
        return True

    @staticmethod
    def _selected_candidate_is_valid(selected: Any, request: _CryRequest, receipt: Any) -> bool:
        try:
            return (
                selected.primary_agent_id == request.primary_agent_id
                and selected.primary_enemy_skill_id == int(receipt.enemy_skill_id)
                and selected.total_interrupt_value >= DEFAULT_POLICY.minimum_candidate_value
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _selection_diagnostic_signature(self, selection: _Selection | None) -> tuple[Any, ...]:
        if selection is None:
            return (
                "no_eligible_candidate",
                f"selection={self._selection_failure_reason or 'selection_unavailable'}",
            )

        decision = selection.decision
        candidate_reason_counts: dict[str, int] = {}
        handled_keys: set[CryCastKey] = set()
        score_by_key: dict[CryCastKey, int] = {}
        maximum_candidate_value = 0
        redundant_count = 0
        for candidate in decision.candidates:
            reason = str(getattr(getattr(candidate, "reason", None), "value", candidate.reason))
            candidate_reason_counts[reason] = candidate_reason_counts.get(reason, 0) + 1
            maximum_candidate_value = max(maximum_candidate_value, int(candidate.total_interrupt_value))
            if bool(getattr(candidate, "redundant", False)):
                redundant_count += 1
            handled_keys.update(candidate.handled_cast_keys)
            for cast_key, value in candidate.covered_cast_values:
                score_by_key[cast_key] = int(value)

        decision_reason = str(getattr(getattr(decision, "reason", None), "value", decision.reason))
        reason_summary = (
            ",".join(f"{reason}={count}" for reason, count in sorted(candidate_reason_counts.items())) or "none"
        )
        runtime_summary = (
            ",".join(f"{reason}={count}" for reason, count in selection.runtime_rejection_counts) or "none"
        )
        score_counts: dict[int, int] = {}
        for value in score_by_key.values():
            score_counts[value] = score_counts.get(value, 0) + 1
        score_summary = ",".join(f"{value}:{count}" for value, count in sorted(score_counts.items())) or "none"
        policy_candidate = decision.candidates[0] if decision.candidates else None
        return (
            "no_eligible_candidate",
            f"decision={decision_reason}",
            f"reasons={reason_summary}",
            f"runtime={runtime_summary}",
            f"handled={len(handled_keys)}",
            f"redundant={redundant_count}",
            f"max_value={maximum_candidate_value}",
            f"threshold={DEFAULT_POLICY.minimum_candidate_value}",
            f"scores={score_summary}",
            *self._candidate_policy_diagnostic_signature(policy_candidate),
        )

    @staticmethod
    def _candidate_policy_diagnostic_signature(candidate: Any) -> tuple[str, ...]:
        if candidate is None:
            return (
                "primary_value=0",
                "primary_source=unavailable",
                "additional_interrupt_count=0",
                "additional_interrupt_value=0",
                "damage_coverage_count=0",
                "damage_bonus=0",
                "final_policy_value=0",
                f"minimum_candidate_value={DEFAULT_POLICY.minimum_candidate_value}",
                "final_value=0",
                f"threshold={DEFAULT_POLICY.minimum_candidate_value}",
            )

        final_value = int(getattr(candidate, "final_policy_value", getattr(candidate, "total_interrupt_value", 0)))
        return (
            f"primary_value={int(getattr(candidate, 'primary_cast_value', 0))}",
            f"primary_source={str(getattr(candidate, 'primary_value_source', 'unavailable'))}",
            f"additional_interrupt_count={int(getattr(candidate, 'additional_interrupt_count', 0))}",
            f"additional_interrupt_value={int(getattr(candidate, 'additional_interrupt_value', 0))}",
            f"damage_coverage_count={int(getattr(candidate, 'damage_coverage_count', 0))}",
            f"damage_bonus={int(getattr(candidate, 'damage_bonus', 0))}",
            f"final_policy_value={final_value}",
            f"minimum_candidate_value={DEFAULT_POLICY.minimum_candidate_value}",
            f"final_value={final_value}",
            f"threshold={DEFAULT_POLICY.minimum_candidate_value}",
        )

    @staticmethod
    def _validation_diagnostic_signature(
        request: _CryRequest,
        failure: _ValidationFailure,
    ) -> tuple[Any, ...]:
        return (
            f"reason={failure.reason}",
            f"request={request.attempt_id}",
            f"target={request.primary_agent_id}",
            f"skill={request.enemy_skill_id}",
            *failure.details,
        )

    @staticmethod
    def _postclaim_diagnostic_signature(request: _CryRequest, reason: str) -> tuple[Any, ...]:
        return (
            f"reason={reason}",
            f"request={request.attempt_id}",
            f"target={request.primary_agent_id}",
            f"skill={request.enemy_skill_id}",
        )

    def _to_interrupt_evidence(
        self,
        agent_id: int,
        enemy_skill_id: int,
        assessment: Any,
        observation: Any,
    ) -> CryInterruptEvidence:
        identity = None if assessment is None else getattr(assessment, "observation_identity", None)
        if identity is None and observation is not None:
            identity = getattr(observation, "observation_identity", None)
        onset_confidence = CryOnsetConfidence.UNCERTAIN
        timing_trusted = False
        mechanically_feasible = False
        reason = "onset_unavailable"
        observation_age_ms = None
        if assessment is not None:
            timing_trusted = bool(
                getattr(getattr(assessment, "onset_confidence", None), "value", "") == "confirmed_local_onset"
            )
            onset_confidence = CryOnsetConfidence.TRUSTED if timing_trusted else CryOnsetConfidence.UNCERTAIN
            mechanically_feasible = bool(getattr(assessment, "feasible", False))
            reason = str(getattr(getattr(assessment, "reason", None), "value", "unknown"))
            observation_age_ms = getattr(assessment, "observation_age_ms", None)
        return CryInterruptEvidence(
            target_agent_id=int(agent_id),
            enemy_skill_id=int(enemy_skill_id),
            mechanically_feasible=mechanically_feasible,
            timing_trusted=timing_trusted,
            reason=reason,
            cast_active=True,
            observation_identity=identity,
            observation_age_ms=observation_age_ms,
            onset_confidence=onset_confidence,
        )

    def _classify_enemy_skill(self, enemy_skill_id: int) -> CrySkillClassification:
        try:
            from Py4GWCoreLib.HeroAI.types import SkillNature

            custom_skill = self.GetCustomSkill(enemy_skill_id)
            metadata_populated = int(getattr(custom_skill, "SkillID", 0) or 0) == int(enemy_skill_id)
            nature = getattr(custom_skill, "Nature", None)
            nature_value_raw: Any = getattr(nature, "value", nature)
            if nature_value_raw is None:
                return CrySkillClassification()
            nature_value = int(nature_value_raw)
            category = CrySkillCategory.UNKNOWN
            if nature_value == int(SkillNature.Healing.value):
                category = CrySkillCategory.HEALING
            elif nature_value == int(SkillNature.Resurrection.value):
                category = CrySkillCategory.RESURRECTION
            if metadata_populated and category is not CrySkillCategory.UNKNOWN:
                return CrySkillClassification(
                    category=category,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                )
        except Exception:
            pass
        return CrySkillClassification()

    def _strict_assessment(self, target_agent_id: int, now_ms: int) -> Any | None:
        try:
            from Py4GWCoreLib.HeroAI import interrupt

            fast_casting_level = int(interrupt._get_player_fast_casting_level())
            ping_ms = int(interrupt._PING_HANDLER.GetCurrentPing())
            assessment = interrupt.assess_interrupt(
                target_agent_id=target_agent_id,
                our_skill_id=self.skill_id,
                fast_casting_level=fast_casting_level,
                ping_ms=ping_ms,
                strict=True,
                now_ms=int(now_ms),
            )
            if getattr(assessment, "onset_confidence", None) is None:
                return None
            return assessment
        except Exception:
            return None

    def _required_lease_ms(self, assessment: Any, now_ms: int) -> int | None:
        del now_ms
        budget_value = getattr(assessment, "interrupt_budget_ms", None)
        remaining_value = getattr(assessment, "enemy_remaining_ms", None)
        if (
            isinstance(budget_value, bool)
            or not isinstance(budget_value, int)
            or isinstance(remaining_value, bool)
            or not isinstance(remaining_value, int)
        ):
            return None
        budget_ms = int(budget_value)
        remaining_ms = int(remaining_value)
        submission_horizon_ms = budget_ms + CLAIM_TO_SUBMIT_RESERVE_MS
        if budget_ms <= 0 or remaining_ms < submission_horizon_ms:
            return None
        required_ms = max(remaining_ms, submission_horizon_ms) + POST_SUBMIT_ALLOWANCE_MS
        if required_ms <= 0 or required_ms > MAX_REQUIRED_LEASE_MS:
            return None
        return required_ms

    def _safe_queue_window_ms(self, assessment: Any) -> int:
        budget_ms = int(getattr(assessment, "interrupt_budget_ms", 0) or 0)
        remaining_ms = int(getattr(assessment, "enemy_remaining_ms", 0) or 0)
        return max(0, remaining_ms - budget_ms - CLAIM_TO_SUBMIT_RESERVE_MS)

    def _try_claim(self, request: _CryRequest, expires_at_tick: int) -> tuple[Any, str]:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            result = GLOBAL_CACHE.ShMem.TryPostInterruptLock(
                request.owner_email,
                request.enemy_skill_id,
                request.primary_agent_id,
                int(expires_at_tick),
                request.isolation_group_id,
            )
            return result, str(getattr(result, "reason", "unknown"))
        except Exception as error:
            return None, f"exception:{type(error).__name__}"

    @staticmethod
    def _receipt_from_claim_result(claim_result: Any) -> Any:
        if claim_result is None:
            return None
        receipt = getattr(claim_result, "receipt", None)
        if receipt is not None:
            return receipt
        if all(hasattr(claim_result, name) for name in ("slot_index", "enemy_skill_id", "target_agent_id")):
            return claim_result
        return None

    @staticmethod
    def _receipt_matches_request(receipt: Any, request: _CryRequest) -> bool:
        try:
            return (
                int(getattr(receipt, "kind_id")) == 11
                and str(getattr(receipt, "owner_email")) == request.owner_email
                and int(getattr(receipt, "enemy_skill_id")) == request.enemy_skill_id
                and int(getattr(receipt, "target_agent_id")) == request.primary_agent_id
                and int(getattr(receipt, "isolation_group_id")) == request.isolation_group_id
                and int(getattr(receipt, "expires_at_tick64")) > int(getattr(receipt, "posted_at_tick64"))
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _receipt_is_live(self, receipt: Any, now_ms: int) -> bool:
        try:
            return not self._tick_expired(now_ms, int(receipt.expires_at_tick64))
        except (AttributeError, TypeError, ValueError):
            return False

    def _release_receipt(self, reason: str) -> bool:
        receipt = self._receipt
        if receipt is None:
            self._drop_request(reason)
            return True
        now_ms = self._now_ms()
        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            released = bool(GLOBAL_CACHE.ShMem.ClearInterruptLockIfMatch(receipt))
        except Exception:
            released = False
        if released:
            self._receipt = None
            self._request = None
            self._state = CryControllerState.IDLE
            self._native_invocation_entered = False
            self._native_result = None
            self._post_submit_deadline = None
            self._emit_diagnostic("exact_release", (reason, True), now_ms=now_ms)
            return True
        if now_ms is not None and not self._receipt_is_live(receipt, now_ms):
            self._receipt = None
            self._request = None
            self._state = CryControllerState.IDLE
            self._native_invocation_entered = False
            self._native_result = None
            self._post_submit_deadline = None
            self._emit_diagnostic("receipt_expired", (reason,), now_ms=now_ms)
            return False
        self._state = CryControllerState.RELEASING
        self._emit_diagnostic("exact_release", (reason, False), now_ms=now_ms)
        return False

    def _maintain_state(self, now_ms: int) -> None:
        if self._receipt is None:
            request = self._request
            if (
                request is not None
                and self._state in (CryControllerState.SELECTED, CryControllerState.QUEUED)
                and now_ms >= request.deadline_tick
            ):
                self._drop_request("queue_deadline_expired")
            return

        if not self._receipt_is_live(self._receipt, now_ms):
            self._receipt = None
            self._request = None
            self._state = CryControllerState.IDLE
            self._native_invocation_entered = False
            self._native_result = None
            self._post_submit_deadline = None
            self._emit_diagnostic("receipt_expired", ("lease",), now_ms=now_ms)
            return
        if self._state is CryControllerState.RELEASING:
            self._release_receipt("retry")
            return

    def _invalidate_work(self, reason: str) -> None:
        self._token_counter += 1
        self._captured_selection = None
        self._capture_proposal = False
        if self._receipt is None:
            self._request = None
            self._state = CryControllerState.IDLE
            self._native_invocation_entered = False
            self._native_result = None
            self._post_submit_deadline = None
            self._emit_diagnostic("work_invalidated", (reason,), now_ms=self._now_ms())
            return
        if self._native_invocation_entered or self._state in (
            CryControllerState.SUBMITTED,
            CryControllerState.UNCERTAIN,
        ):
            self._request = None
            self._state = CryControllerState.UNCERTAIN
            self._emit_diagnostic("work_invalidated", (reason, "native_possible"), now_ms=self._now_ms())
            return
        self._release_receipt(reason)

    def _drop_request(
        self,
        reason: str,
        *,
        diagnostic_family: str = "request_cleared",
        diagnostic_signature: tuple[Any, ...] | None = None,
        diagnostic_windowed: bool = False,
    ) -> None:
        self._token_counter += 1
        self._captured_selection = None
        self._capture_proposal = False
        self._request = None
        self._state = CryControllerState.IDLE
        self._native_invocation_entered = False
        self._native_result = None
        self._post_submit_deadline = None
        self._emit_diagnostic(
            diagnostic_family,
            (reason,) if diagnostic_signature is None else diagnostic_signature,
            now_ms=self._now_ms(),
            windowed=diagnostic_windowed,
        )

    def _has_active_dispatch(self) -> bool:
        return self._request is not None or self._captured_selection is not None

    def _has_active_work(self) -> bool:
        return self._has_active_dispatch() or self._receipt is not None

    def _request_is_current(
        self,
        request: _CryRequest,
        now_ms: int,
        *,
        enforce_deadline: bool,
    ) -> bool:
        return self._request_current_failure_reason(request, now_ms, enforce_deadline=enforce_deadline) is None

    def _request_current_failure_reason(
        self,
        request: _CryRequest,
        now_ms: int,
        *,
        enforce_deadline: bool,
    ) -> str | None:
        if self._disposed or self._request is not request:
            return "request_invalid"
        if request.token != self._token_counter:
            return "request_invalid"
        if self._lifecycle_id != request.lifecycle_id:
            return "lifecycle_changed"
        if request.composition_generation != self._composition_generation:
            return "lifecycle_changed"
        if request.bar_generation != self._bar_generation:
            return "cry_slot_changed"
        if enforce_deadline and now_ms >= request.deadline_tick:
            return "deadline_expired"
        return None

    def _record_validation_failure(self, reason: str, *details: Any) -> None:
        self._preclaim_failure = _ValidationFailure(str(reason), tuple(details))
        return None

    def _drop_preclaim_request(self, request: _CryRequest, reason: str, *details: Any) -> None:
        failure = _ValidationFailure(str(reason), tuple(details))
        self._preclaim_failure = failure
        self._drop_request(
            "preclaim_validation",
            diagnostic_family="preclaim_failed",
            diagnostic_signature=self._validation_diagnostic_signature(request, failure),
            diagnostic_windowed=True,
        )

    def _refresh_lifecycle(self) -> None:
        current = self._read_lifecycle_inputs()
        if current is None:
            return
        previous = self._last_lifecycle_inputs
        lifecycle_changed = False
        if previous is not None:
            lifecycle_changed = (
                (previous.map_id > 0 and current.map_id > 0 and previous.map_id != current.map_id)
                or (
                    previous.player_agent_id > 0
                    and current.player_agent_id > 0
                    and previous.player_agent_id != current.player_agent_id
                )
                or (
                    previous.instance_uptime_ms > 0
                    and current.instance_uptime_ms > 0
                    and current.instance_uptime_ms < previous.instance_uptime_ms
                )
                or (
                    bool(previous.owner_email)
                    and bool(current.owner_email)
                    and previous.owner_email != current.owner_email
                )
                or (
                    previous.isolation_group_id > 0
                    and current.isolation_group_id > 0
                    and previous.isolation_group_id != current.isolation_group_id
                )
            )
        if lifecycle_changed:
            self._local_generation += 1
            self._invalidate_work("runtime_lifecycle_changed")
        self._last_lifecycle_inputs = current
        self._last_instance_uptime_ms = current.instance_uptime_ms
        self._lifecycle_id = (
            current.map_id,
            current.player_agent_id,
            self._local_generation,
        )

    @staticmethod
    def _read_lifecycle_inputs() -> _LifecycleInputs | None:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Map
            from Py4GWCoreLib import Player

            owner_email = str(Player.GetAccountEmail() or "").strip()
            group_id = 0
            if owner_email:
                group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(owner_email) or 0)
            return _LifecycleInputs(
                map_id=int(Map.GetMapID() or 0),
                player_agent_id=int(Player.GetAgentID() or 0),
                instance_uptime_ms=int(Map.GetInstanceUptime() or 0),
                owner_email=owner_email,
                isolation_group_id=group_id,
            )
        except Exception:
            return None

    @staticmethod
    def _shared_owner_account_row(owner_email: str) -> tuple[bool, int]:
        from Py4GWCoreLib import GLOBAL_CACHE

        accounts = GLOBAL_CACHE.ShMem.GetAllAccounts()
        find_slot = getattr(accounts, "_find_account_slot_by_email", None)
        if not callable(find_slot):
            raise RuntimeError("shared account lookup unavailable")
        slot_index = int(cast(Callable[[str], int], find_slot)(owner_email))
        if slot_index < 0:
            return False, 0
        account_data = accounts.AccountData[slot_index]
        if not bool(getattr(account_data, "IsAccount", False)):
            return False, 0
        group_id = int(getattr(account_data, "IsolationGroupID", 0) or 0)
        return True, group_id

    @staticmethod
    def _local_owner_context_result() -> _OwnerContextResult:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Player

            owner_email = str(Player.GetAccountEmail() or "").strip()
            if not owner_email:
                return _OwnerContextResult(None, "owner_missing")
            group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(owner_email) or 0)
            if group_id > 0:
                return _OwnerContextResult((owner_email, group_id), None)
            account_present, shared_group_id = SmartCryController._shared_owner_account_row(owner_email)
            if not account_present:
                return _OwnerContextResult(None, "account_context_missing")
            if shared_group_id <= 0:
                return _OwnerContextResult(None, "isolation_group_missing")
            return _OwnerContextResult(None, "owner_context_lookup_failed")
        except Exception:
            return _OwnerContextResult(None, "owner_context_lookup_failed")

    @staticmethod
    def _local_owner_context() -> tuple[str, int] | None:
        return SmartCryController._local_owner_context_result().context

    def _runtime_gate(self) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import Map
            from Py4GWCoreLib import Player
            from Py4GWCoreLib import Routines

            if not bool(Map.IsMapReady()) or not bool(Map.IsExplorable()) or bool(Map.IsInCinematic()):
                return False
            if not bool(Routines.Checks.Map.MapValid()):
                return False
            player_id = int(Player.GetAgentID() or 0)
            if player_id <= 0 or not bool(Agent.IsValid(player_id)) or bool(Agent.IsDead(player_id)):
                return False
            if bool(Agent.IsKnockedDown(player_id)) or bool(Agent.IsCasting(player_id)):
                return False
            if bool(GLOBAL_CACHE.SkillBar.GetCasting()):
                return False
            if not bool(Routines.Checks.Player.CanAct()):
                return False
            return True
        except Exception:
            return False

    def _skill_readiness(self, slot: int) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Routines

            if int(GLOBAL_CACHE.SkillBar.GetSkillIDBySlot(slot) or 0) != self.skill_id:
                return False
            if not self._skill_toggle_enabled(slot):
                return False
            if not bool(self.CanCastSkillSlot(slot)):
                return False
            can_cast = getattr(Routines.Checks.Skills, "CanCast", None)
            if not callable(can_cast) or not bool(can_cast()):
                return False
            skill_data = GLOBAL_CACHE.SkillBar.GetSkillData(slot)
            recharge = getattr(skill_data, "recharge", None)
            if recharge is None or float(recharge) != 0.0:
                return False
            return True
        except Exception:
            return False

    def _combat_option_enabled(self) -> bool:
        """Read the current shared Combat option; missing evidence fails closed."""

        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Player

            owner_email = str(Player.GetAccountEmail() or "").strip()
            if not owner_email:
                return False
            options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(owner_email)
            combat = getattr(options, "Combat", None)
            return combat is not None and bool(combat)
        except Exception:
            return False

    def _skill_toggle_enabled(self, slot: int) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Player

            options = getattr(getattr(self, "_cached_data", None), "account_options", None)
            if options is None:
                owner_email = str(Player.GetAccountEmail() or "").strip()
                if not owner_email:
                    return False
                options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(owner_email)
            skills = getattr(options, "Skills", None)
            if skills is None:
                return False
            return bool(skills[int(slot) - 1])
        except (IndexError, TypeError, ValueError, AttributeError):
            return False

    def _resolve_current_slot(self) -> int | None:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            slot = int(GLOBAL_CACHE.SkillBar.GetSlotBySkillID(self.skill_id) or 0)
            if not 1 <= slot <= 8:
                return None
            if int(GLOBAL_CACHE.SkillBar.GetSkillIDBySlot(slot) or 0) != self.skill_id:
                return None
            return slot
        except (AttributeError, TypeError, ValueError):
            return None

    def _target_is_current(self, target_agent_id: int, expected_skill_id: int) -> bool:
        return self._target_current_failure_reason(target_agent_id, expected_skill_id) is None

    def _target_current_failure_reason(self, target_agent_id: int, expected_skill_id: int) -> str | None:
        try:
            from Py4GWCoreLib import Agent

            if not bool(Agent.IsValid(target_agent_id)):
                return "target_invalid"
            if bool(Agent.IsDead(target_agent_id)):
                return "target_dead"
            if not bool(Agent.IsCasting(target_agent_id)):
                return "target_not_casting"
            if int(Agent.GetCastingSkillID(target_agent_id) or 0) != int(expected_skill_id):
                return "target_skill_changed"
            if not self._is_enemy(target_agent_id):
                return "target_not_hostile"
            if not self._target_is_allowed(target_agent_id):
                return "target_not_allowed"
            from Py4GWCoreLib import Player

            player_position = self._position(Player.GetXY())
            target_position = self._position(Agent.GetXY(target_agent_id))
            if player_position is None or target_position is None:
                return "target_geometry_unavailable"
            from Py4GWCoreLib import Range

            distance = math.hypot(
                player_position[0] - target_position[0],
                player_position[1] - target_position[1],
            )
            if not math.isfinite(distance):
                return "target_geometry_unavailable"
            if distance > float(Range.Spellcast.value):
                return "target_out_of_range"
            return None
        except Exception:
            return "target_state_unavailable"

    def _target_is_allowed(self, target_agent_id: int) -> bool:
        try:
            return bool(self._validate_target_for_skill_cast(self.skill_id, int(target_agent_id)))
        except Exception:
            return False

    @staticmethod
    def _is_enemy(agent_id: int) -> bool:
        try:
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib.enums_src.GameData_enums import Allegiance

            raw_allegiance = Agent.GetAllegiance(agent_id)
            allegiance = raw_allegiance[0] if isinstance(raw_allegiance, tuple) else raw_allegiance
            return int(allegiance) == int(Allegiance.Enemy.value)
        except Exception:
            return False

    def _handled_cast_keys(
        self,
        group_id: int,
        now_ms: int,
        *,
        exclude_receipt: Any = None,
    ) -> set[CryCastKey]:
        handled: set[CryCastKey] = set()
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib.enums_src.Whiteboard_enums import WhiteboardLockKind

            all_accounts = GLOBAL_CACHE.ShMem.GetAllAccounts()
            class_method = getattr(type(all_accounts), "GetAllIntents", None)
            if class_method is None:
                raw_method = getattr(all_accounts, "GetAllIntents")
                rows = raw_method()
            else:
                raw_method = getattr(class_method, "__wrapped__", class_method)
                rows = raw_method(all_accounts)
            for _slot_index, intent in rows or ():
                if not bool(getattr(intent, "Active", False)):
                    continue
                if int(getattr(intent, "KindID", 0) or 0) != int(WhiteboardLockKind.INTERRUPT_TARGET):
                    continue
                if int(getattr(intent, "IsolationGroupID", 0) or 0) != int(group_id):
                    continue
                enemy_skill_id = int(getattr(intent, "SkillID", 0) or 0)
                target_agent_id = int(getattr(intent, "TargetAgentID", 0) or 0)
                expires_at_tick = int(getattr(intent, "ExpiresAtTick", 0) or 0)
                if enemy_skill_id <= 0 or target_agent_id <= 0 or self._tick_expired(now_ms, expires_at_tick):
                    continue
                if exclude_receipt is not None and self._row_matches_receipt(intent, exclude_receipt):
                    continue
                try:
                    handled.add(CryCastKey(target_agent_id, enemy_skill_id))
                except ValueError:
                    continue
        except Exception:
            pass

        if self._suppression_deadline is not None and now_ms < self._suppression_deadline:
            handled.update(self._suppressed_cast_keys)
        elif self._suppression_deadline is not None:
            self._suppression_deadline = None
            self._suppressed_cast_keys = ()
        return handled

    @staticmethod
    def _row_matches_receipt(intent: Any, receipt: Any) -> bool:
        try:
            return (
                str(getattr(intent, "OwnerEmail")) == str(getattr(receipt, "owner_email"))
                and int(getattr(intent, "KindID")) == int(getattr(receipt, "kind_id"))
                and int(getattr(intent, "SkillID")) == int(getattr(receipt, "enemy_skill_id"))
                and int(getattr(intent, "TargetAgentID")) == int(getattr(receipt, "target_agent_id"))
                and int(getattr(intent, "IsolationGroupID")) == int(getattr(receipt, "isolation_group_id"))
                and (int(getattr(intent, "PostedAtTick")) & 0xFFFFFFFF)
                == (int(getattr(receipt, "posted_at_tick64")) & 0xFFFFFFFF)
                and (int(getattr(intent, "ExpiresAtTick")) & 0xFFFFFFFF)
                == (int(getattr(receipt, "expires_at_tick64")) & 0xFFFFFFFF)
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _suppress_conflict(self, request: _CryRequest, now_ms: int) -> None:
        self._suppressed_cast_keys = tuple(request.covered_cast_keys)
        self._suppression_deadline = now_ms + CONFLICT_SUPPRESSION_MS
        self._emit_diagnostic(
            "d0_conflict_suppressed",
            (request.attempt_id, len(self._suppressed_cast_keys)),
            now_ms=now_ms,
        )

    @staticmethod
    def _tick_expired(now_ms: int, expires_at_tick: int) -> bool:
        try:
            from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import tick_is_expired

            return bool(tick_is_expired(int(now_ms), int(expires_at_tick)))
        except Exception:
            return int(now_ms) >= int(expires_at_tick)

    @staticmethod
    def _position(value: Any) -> tuple[float, float] | None:
        try:
            if value is None or len(value) < 2:
                return None
            x_value = float(value[0])
            y_value = float(value[1])
            if not math.isfinite(x_value) or not math.isfinite(y_value):
                return None
            return x_value, y_value
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _now_ms() -> int | None:
        try:
            from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64

            now_ms = int(get_uncached_tick_count64())
            return now_ms if now_ms >= 0 else None
        except (AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError, OverflowError):
            return None

    def _emit_diagnostic(
        self,
        family: str,
        signature: tuple[Any, ...],
        *,
        now_ms: int | None = None,
        windowed: bool = False,
    ) -> None:
        tick = self._now_ms() if now_ms is None else now_ms
        if tick is None:
            tick = 0
        previous = self._diagnostic_state.get(family)
        if previous is not None:
            previous_tick, previous_signature = previous
            if tick - previous_tick < DIAGNOSTIC_COOLDOWN_MS:
                if windowed or previous_signature == signature:
                    if windowed:
                        self._diagnostic_state[family] = (previous_tick, signature)
                    return
        self._diagnostic_state[family] = (tick, signature)
        try:
            from PySystem import Console

            from Py4GWCoreLib import ConsoleLog

            ConsoleLog(
                self.build_name,
                f"{family}: t={tick} values={', '.join(str(value) for value in signature)}",
                Console.MessageType.Info,
            )
        except Exception:
            return


__all__ = [
    "ActivationEvidenceAdapter",
    "CLAIM_TO_SUBMIT_RESERVE_MS",
    "CONFLICT_SUPPRESSION_MS",
    "CryControllerState",
    "Cry_of_Frustration_ID",
    "MAX_REQUIRED_LEASE_MS",
    "POST_SUBMIT_ALLOWANCE_MS",
    "QUEUE_DEADLINE_MS",
    "SmartCryController",
    "get_cry_of_frustration_id",
]
