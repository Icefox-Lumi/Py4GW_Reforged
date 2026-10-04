"""Pure direct-radius Panic policy and its guarded My Mesmer handler."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Generator
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Final
from typing import cast

from Py4GWCoreLib.BuildMgr import BuildMgr

PANIC_SKILL_ID: Final[int] = 52
PANIC_NAME: Final[str] = "Panic"
PANIC_MINIMUM_AFFECTED: Final[int] = 3
PANIC_RECENT_GROUP_WINDOW_MS: Final[int] = 1500
PANIC_RECENT_GROUP_OVERLAP_RATIO: Final[float] = 0.75
PANIC_RECEIPT_SAFETY_MARGIN_MS: Final[int] = 500
PANIC_EVENT_HISTORY_MAX: Final[int] = 256
PANIC_DOMINATION_ATTRIBUTE_ID: Final[int] = 2
NPC_SPIRIT_FLAG: Final[int] = 0x4000


class DecisionReason(str, Enum):
    SELECTED = "selected"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    INVALID_POLICY = "invalid_policy"
    INVALID_EVIDENCE = "invalid_evidence"


class CandidateReason(str, Enum):
    ELIGIBLE = "eligible"
    INVALID_TARGET = "invalid_target"
    MISSING_EVIDENCE = "missing_evidence"
    OUT_OF_CAST_RANGE = "out_of_cast_range"
    CENTER_ALREADY_PANICKED = "center_already_panicked"
    CENTER_EFFECT_UNKNOWN = "center_effect_unknown"
    BELOW_MINIMUM_AFFECTED = "below_minimum_affected"


class PanicSpiritClassification(str, Enum):
    """Tri-state spirit evidence used for Panic affected-member admission."""

    CONFIRMED_SPIRIT = "confirmed_spirit"
    CONFIRMED_NOT_SPIRIT = "confirmed_not_spirit"
    UNKNOWN = "unknown"


class PanicEffectState(str, Enum):
    """Semantic Panic evidence; absence is intentionally not a state."""

    OBSERVED_PRESENT = "observed_present"
    LOCALLY_COVERED = "locally_covered"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PanicPolicy:
    """Immutable geometry and admission policy for one Panic evaluation."""

    cast_range: float
    effect_radius: float
    minimum_affected: int = PANIC_MINIMUM_AFFECTED

    def __post_init__(self) -> None:
        for name, value in (("cast_range", self.cast_range), ("effect_radius", self.effect_radius)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
            if float(value) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if isinstance(self.minimum_affected, bool) or not isinstance(self.minimum_affected, int):
            raise ValueError("minimum_affected must be an integer")
        if self.minimum_affected < PANIC_MINIMUM_AFFECTED:
            raise ValueError("minimum_affected cannot be lower than three")


@dataclass(frozen=True, slots=True)
class PanicTargetObservation:
    """Immutable runtime facts for one possible Panic center or affected enemy.

    ``is_targetable`` is direct-target evidence for center eligibility. It is
    intentionally not required for direct-radius affected-member membership.
    """

    agent_id: int
    x: float | None
    y: float | None
    distance_from_player: float | None
    is_valid: bool | None = True
    is_living: bool | None = True
    is_alive: bool | None = True
    is_hostile: bool | None = True
    is_targetable: bool | None = True
    has_panic: bool | None = False
    panic_state: PanicEffectState = PanicEffectState.UNKNOWN
    is_caster: bool | None = None
    is_support: bool | None = None
    is_casting: bool | None = False
    agent_is_spirit: bool | None = None
    npc_flags: int | None = None

    def __post_init__(self) -> None:
        if type(self.agent_id) is not int or self.agent_id <= 0:
            raise ValueError("agent_id must be a positive integer")
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("distance_from_player", self.distance_from_player),
        ):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite when supplied")
        for name, value in (
            ("is_valid", self.is_valid),
            ("is_living", self.is_living),
            ("is_alive", self.is_alive),
            ("is_hostile", self.is_hostile),
            ("is_targetable", self.is_targetable),
            ("agent_is_spirit", self.agent_is_spirit),
            ("has_panic", self.has_panic),
            ("is_caster", self.is_caster),
            ("is_support", self.is_support),
            ("is_casting", self.is_casting),
        ):
            if value is not None and type(value) is not bool:
                raise TypeError(f"{name} must be bool or None")
        if self.npc_flags is not None:
            if isinstance(self.npc_flags, bool) or not isinstance(self.npc_flags, int) or self.npc_flags < 0:
                raise ValueError("npc_flags must be a non-negative integer or None")
        if not isinstance(self.panic_state, PanicEffectState):
            raise TypeError("panic_state must be a PanicEffectState")


@dataclass(frozen=True, slots=True)
class PanicCandidateEvaluation:
    """The direct-radius value and admission result for one Panic center."""

    target_agent_id: int
    eligible: bool
    reason: CandidateReason
    affected_agent_ids: tuple[int, ...]
    uncovered_affected_agent_ids: tuple[int, ...]
    caster_support_count: int
    casting_count: int
    distance_from_player: float | None

    @property
    def affected_count(self) -> int:
        return len(self.affected_agent_ids)

    @property
    def uncovered_count(self) -> int:
        return len(self.uncovered_affected_agent_ids)

    @property
    def group_agent_ids(self) -> tuple[int, ...]:
        return self.affected_agent_ids


@dataclass(frozen=True, slots=True)
class PanicDecision:
    """Pure Panic target-selection result."""

    selected: PanicCandidateEvaluation | None
    reason: DecisionReason
    candidates: tuple[PanicCandidateEvaluation, ...]

    @property
    def admitted(self) -> bool:
        return self.selected is not None

    @property
    def selected_target_agent_id(self) -> int | None:
        return None if self.selected is None else self.selected.target_agent_id

    @property
    def ranked_candidates(self) -> tuple[PanicCandidateEvaluation, ...]:
        return self.candidates


def _invalid_decision(reason: DecisionReason) -> PanicDecision:
    return PanicDecision(selected=None, reason=reason, candidates=())


def _valid_policy(policy: PanicPolicy) -> bool:
    return (
        isinstance(policy, PanicPolicy)
        and math.isfinite(float(policy.cast_range))
        and math.isfinite(float(policy.effect_radius))
        and policy.cast_range > 0.0
        and policy.effect_radius > 0.0
        and policy.minimum_affected >= PANIC_MINIMUM_AFFECTED
    )


def _complete_center_evidence(observation: PanicTargetObservation) -> CandidateReason | None:
    if any(
        value is False
        for value in (
            observation.is_valid,
            observation.is_living,
            observation.is_alive,
            observation.is_hostile,
            observation.is_targetable,
        )
    ):
        return CandidateReason.INVALID_TARGET
    if any(
        value is None
        for value in (
            observation.is_valid,
            observation.is_living,
            observation.is_alive,
            observation.is_hostile,
            observation.is_targetable,
            observation.x,
            observation.y,
            observation.distance_from_player,
        )
    ):
        return CandidateReason.MISSING_EVIDENCE
    assert observation.distance_from_player is not None
    if observation.distance_from_player < 0.0:
        return CandidateReason.INVALID_TARGET
    return None


def classify_panic_spirit(observation: PanicTargetObservation) -> PanicSpiritClassification:
    """Classify spirit evidence without inferring from targetability or spawn state."""

    if not isinstance(observation, PanicTargetObservation):
        return PanicSpiritClassification.UNKNOWN
    if observation.agent_is_spirit is True:
        return PanicSpiritClassification.CONFIRMED_SPIRIT
    if observation.npc_flags is not None and observation.npc_flags & NPC_SPIRIT_FLAG:
        return PanicSpiritClassification.CONFIRMED_SPIRIT
    if observation.agent_is_spirit is False and observation.npc_flags is not None:
        return PanicSpiritClassification.CONFIRMED_NOT_SPIRIT
    return PanicSpiritClassification.UNKNOWN


def _has_affected_member_evidence(observation: PanicTargetObservation) -> bool:
    return (
        observation.is_valid is True
        and observation.is_living is True
        and observation.is_alive is True
        and observation.is_hostile is True
        and observation.x is not None
        and observation.y is not None
    )


def _is_affected_member(observation: PanicTargetObservation) -> bool:
    return (
        _has_affected_member_evidence(observation)
        and classify_panic_spirit(observation) is PanicSpiritClassification.CONFIRMED_NOT_SPIRIT
    )


def _panic_is_present(observation: PanicTargetObservation) -> bool:
    return observation.has_panic is True or observation.panic_state in (
        PanicEffectState.OBSERVED_PRESENT,
        PanicEffectState.LOCALLY_COVERED,
    )


def _candidate_sort_key(candidate: PanicCandidateEvaluation) -> tuple[int, int, int, int, int, float, int]:
    distance = math.inf if candidate.distance_from_player is None else float(candidate.distance_from_player)
    return (
        0 if candidate.eligible else 1,
        -candidate.uncovered_count,
        -candidate.affected_count,
        -candidate.caster_support_count,
        -candidate.casting_count,
        distance,
        candidate.target_agent_id,
    )


def _evaluate_candidate(
    center: PanicTargetObservation,
    observations: tuple[PanicTargetObservation, ...],
    policy: PanicPolicy,
) -> PanicCandidateEvaluation:
    evidence_reason = _complete_center_evidence(center)
    if evidence_reason is not None:
        return PanicCandidateEvaluation(
            target_agent_id=center.agent_id,
            eligible=False,
            reason=evidence_reason,
            affected_agent_ids=(),
            uncovered_affected_agent_ids=(),
            caster_support_count=0,
            casting_count=0,
            distance_from_player=center.distance_from_player,
        )
    if center.has_panic is True:
        return PanicCandidateEvaluation(
            target_agent_id=center.agent_id,
            eligible=False,
            reason=CandidateReason.CENTER_ALREADY_PANICKED,
            affected_agent_ids=(),
            uncovered_affected_agent_ids=(),
            caster_support_count=0,
            casting_count=0,
            distance_from_player=center.distance_from_player,
        )
    if center.has_panic is None:
        return PanicCandidateEvaluation(
            target_agent_id=center.agent_id,
            eligible=False,
            reason=CandidateReason.CENTER_EFFECT_UNKNOWN,
            affected_agent_ids=(),
            uncovered_affected_agent_ids=(),
            caster_support_count=0,
            casting_count=0,
            distance_from_player=center.distance_from_player,
        )
    assert center.distance_from_player is not None
    if center.distance_from_player > policy.cast_range:
        return PanicCandidateEvaluation(
            target_agent_id=center.agent_id,
            eligible=False,
            reason=CandidateReason.OUT_OF_CAST_RANGE,
            affected_agent_ids=(),
            uncovered_affected_agent_ids=(),
            caster_support_count=0,
            casting_count=0,
            distance_from_player=center.distance_from_player,
        )

    assert center.x is not None and center.y is not None
    radius_squared = float(policy.effect_radius) * float(policy.effect_radius)
    affected: list[PanicTargetObservation] = []
    unknown_affected_member = False
    for observation in observations:
        if not _has_affected_member_evidence(observation):
            continue
        assert observation.x is not None and observation.y is not None
        delta_x = float(observation.x) - float(center.x)
        delta_y = float(observation.y) - float(center.y)
        if delta_x * delta_x + delta_y * delta_y > radius_squared:
            continue
        if _is_affected_member(observation):
            affected.append(observation)
        elif classify_panic_spirit(observation) is PanicSpiritClassification.UNKNOWN:
            unknown_affected_member = True

    affected_agent_ids = tuple(observation.agent_id for observation in affected)
    uncovered_affected_agent_ids = tuple(
        observation.agent_id for observation in affected if not _panic_is_present(observation)
    )
    caster_support_count = sum(
        observation.is_caster is True or observation.is_support is True for observation in affected
    )
    casting_count = sum(observation.is_casting is True for observation in affected)
    if len(affected_agent_ids) < policy.minimum_affected:
        return PanicCandidateEvaluation(
            target_agent_id=center.agent_id,
            eligible=False,
            reason=(
                CandidateReason.MISSING_EVIDENCE if unknown_affected_member else CandidateReason.BELOW_MINIMUM_AFFECTED
            ),
            affected_agent_ids=affected_agent_ids,
            uncovered_affected_agent_ids=uncovered_affected_agent_ids,
            caster_support_count=caster_support_count,
            casting_count=casting_count,
            distance_from_player=center.distance_from_player,
        )
    return PanicCandidateEvaluation(
        target_agent_id=center.agent_id,
        eligible=True,
        reason=CandidateReason.ELIGIBLE,
        affected_agent_ids=affected_agent_ids,
        uncovered_affected_agent_ids=uncovered_affected_agent_ids,
        caster_support_count=caster_support_count,
        casting_count=casting_count,
        distance_from_player=center.distance_from_player,
    )


def evaluate_smart_panic(
    candidates: Iterable[PanicTargetObservation],
    *,
    policy: PanicPolicy,
) -> PanicDecision:
    """Select a direct-radius Panic center deterministically."""

    if not _valid_policy(policy):
        return _invalid_decision(DecisionReason.INVALID_POLICY)
    try:
        observations = tuple(candidates)
    except Exception:
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    if any(not isinstance(observation, PanicTargetObservation) for observation in observations):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    agent_ids = tuple(observation.agent_id for observation in observations)
    if len(agent_ids) != len(set(agent_ids)):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)

    observations = tuple(sorted(observations, key=lambda observation: observation.agent_id))
    evaluations = tuple(_evaluate_candidate(observation, observations, policy) for observation in observations)
    ranked = tuple(sorted(evaluations, key=_candidate_sort_key))
    selected = next((candidate for candidate in ranked if candidate.eligible), None)
    return PanicDecision(
        selected=selected,
        reason=DecisionReason.SELECTED if selected is not None else DecisionReason.NO_ELIGIBLE_CANDIDATE,
        candidates=ranked,
    )


@dataclass(frozen=True, slots=True)
class _RuntimeParameters:
    policy: PanicPolicy
    aftercast_delay_ms: int
    activation_ms: int = 0
    panic_duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class _RecentPanicGroup:
    agent_ids: frozenset[int]
    accepted_at_ms: int
    uncovered_count: int


@dataclass(frozen=True, slots=True)
class _PanicEffectRead:
    projection: bool | None
    state: PanicEffectState


@dataclass(slots=True)
class _PendingPanicReceipt:
    lifecycle_id: tuple[int, int, int]
    composition_generation: int | None
    player_agent_id: int
    target_agent_id: int
    affected_agent_ids: tuple[int, ...]
    dispatch_timestamp_ms: int
    receipt_deadline_ms: int
    panic_duration_ms: int | None
    activation_timestamp_ms: int | None = None
    accepted_activation_key: tuple[int, int, int, int, int, float] | None = None


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _finite_integer(value: Any) -> int | None:
    numeric = _finite_float(value)
    if numeric is None or not numeric.is_integer():
        return None
    return int(numeric)


def _valid_rank(value: Any, *, maximum: int = 21) -> int | None:
    rank = _finite_integer(value)
    if rank is None or rank < 0 or rank > maximum:
        return None
    return rank


def _position(value: Any) -> tuple[float, float] | None:
    try:
        if value is None or len(value) < 2:
            return None
        x_value = _finite_float(value[0])
        y_value = _finite_float(value[1])
        if x_value is None or y_value is None:
            return None
        return x_value, y_value
    except (IndexError, TypeError, ValueError):
        return None


class SmartPanic(BuildMgr):
    """My Mesmer-owned residual Panic handler."""

    def __init__(
        self,
        match_only: bool = False,
        *,
        skill_id: int | None = None,
    ) -> None:
        from Py4GWCoreLib import Profession

        resolved_skill_id = int(skill_id or PANIC_SKILL_ID)
        if resolved_skill_id != PANIC_SKILL_ID:
            raise ValueError("SmartPanic only supports Panic 52")
        self._skill_id = resolved_skill_id
        super().__init__(
            name="Smart Panic",
            required_primary=Profession.Mesmer,
            required_secondary=Profession(0),
            template_code="OQBCAswEc5Jw0zuoNopTOggD",
            required_skills=[self._skill_id],
            optional_skills=[],
            is_template_only=True,
        )
        if match_only:
            return
        self._disposed = False
        self._skill_slot: int | None = None
        self._composition_generation: int | None = None
        self._last_lifecycle_inputs: tuple[int, int, int] | None = None
        self._lifecycle_id: tuple[int, int, int] | None = None
        self._local_generation = 0
        self._last_player_alive: bool | None = None
        self._pending_local_attempt: tuple[int, tuple[int, int, int]] | None = None
        self._pending_receipt: _PendingPanicReceipt | None = None
        self._coverage_expiry_by_agent: dict[int, int] = {}
        self._seen_event_order: deque[tuple[int, int, int, int, int, float]] = deque(maxlen=PANIC_EVENT_HISTORY_MAX)
        self._seen_event_keys: set[tuple[int, int, int, int, int, float]] = set()
        self._recent_group: _RecentPanicGroup | None = None

    @property
    def skill_id(self) -> int:
        return self._skill_id

    @property
    def skill_slot(self) -> int | None:
        return self._skill_slot

    def set_skill_slot(self, slot_index: int | None) -> None:
        if slot_index is None:
            self._skill_slot = None
            return
        slot = int(slot_index)
        self._skill_slot = slot if 1 <= slot <= 8 else None

    def update_lifecycle(self, context: Any = None) -> None:
        if getattr(self, "_disposed", True):
            return
        if context is not None:
            generation = int(context)
            if self._composition_generation is not None and self._composition_generation != generation:
                self._clear_observation_state()
            self._composition_generation = generation
        if self._refresh_lifecycle():
            now_ms = self._now_ms()
            if now_ms is not None:
                self._prune_coverage(now_ms)
                self._poll_pending_receipt(now_ms)

    def try_cast(self) -> Generator[None, None, bool]:
        if False:
            yield
        if getattr(self, "_disposed", True):
            return False
        try:
            return (yield from self._run_local_skill_logic())
        except Exception:
            self._pending_local_attempt = None
            self._pending_receipt = None
            return False

    def has_active_dispatch(self) -> bool:
        if self._pending_local_attempt is not None or self._pending_receipt is not None:
            return True
        pending_check = getattr(self, "_is_local_cast_pending", None)
        if not callable(pending_check):
            return False
        try:
            return bool(pending_check())
        except Exception:
            return True

    def cancel_pending(self, _reason: str) -> None:
        self._pending_local_attempt = None
        self._pending_receipt = None

    def dispose(self, _reason: str = "handler_disposed") -> None:
        if not getattr(self, "_disposed", True):
            self.cancel_pending(_reason)
            self._clear_observation_state()
            self._disposed = True

    def OnContractActivated(self, cached_data: Any = None) -> None:
        self._disposed = False
        self._last_lifecycle_inputs = None
        self._lifecycle_id = None
        self._last_player_alive = None
        self._clear_observation_state()
        if cached_data is not None:
            self.set_cached_data(cached_data)

    @staticmethod
    def _now_ms() -> int | None:
        try:
            import PySystem

            now_ms = int(PySystem.get_tick_count64())
            return now_ms if now_ms >= 0 else None
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None

    def _clear_observation_state(self) -> None:
        self._pending_local_attempt = None
        self._pending_receipt = None
        self._coverage_expiry_by_agent.clear()
        self._seen_event_order.clear()
        self._seen_event_keys.clear()
        self._recent_group = None

    def _read_lifecycle_inputs(self) -> tuple[int, int, int] | None:
        try:
            from Py4GWCoreLib import Map
            from Py4GWCoreLib import Player

            return (
                int(Map.GetMapID() or 0),
                int(Player.GetAgentID() or 0),
                int(Map.GetInstanceUptime() or 0),
            )
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None

    def _refresh_lifecycle(self) -> bool:
        current = self._read_lifecycle_inputs()
        if current is None:
            return False
        previous = self._last_lifecycle_inputs
        lifecycle_reset = False
        if previous is not None:
            if previous[0] != current[0]:
                lifecycle_reset = True
            elif previous[1] != current[1]:
                lifecycle_reset = True
            elif previous[2] > 0 and current[2] > 0 and current[2] < previous[2]:
                lifecycle_reset = True
        if lifecycle_reset:
            self._local_generation += 1
            self._clear_observation_state()
            self._last_player_alive = None
        self._last_lifecycle_inputs = current
        self._lifecycle_id = (current[0], current[1], self._local_generation)
        current_player_alive = self._read_player_alive(current[1])
        if current_player_alive is not None:
            if self._last_player_alive is not None and current_player_alive != self._last_player_alive:
                self._local_generation += 1
                self._clear_observation_state()
                self._lifecycle_id = (current[0], current[1], self._local_generation)
            self._last_player_alive = current_player_alive
        return True

    @staticmethod
    def _read_player_alive(agent_id: int) -> bool | None:
        try:
            from Py4GWCoreLib import Agent

            return bool(Agent.IsValid(agent_id) and Agent.IsLiving(agent_id) and Agent.IsAlive(agent_id))
        except Exception:
            return None

    @staticmethod
    def _duration_to_ms(value: Any) -> int | None:
        numeric = _finite_float(value)
        if numeric is None or numeric < 0.0:
            return None
        return int(round(numeric * 1000.0))

    @staticmethod
    def _current_attribute_rank(agent_api: Any, player_agent_id: int, attribute_id: int) -> int | None:
        try:
            attributes = agent_api.GetAttributes(int(player_agent_id))
        except Exception:
            return None
        for attribute in attributes or ():
            raw_attribute_id = getattr(attribute, "attribute_id", getattr(attribute, "Id", -1))
            try:
                if int(raw_attribute_id) != int(attribute_id):
                    continue
            except (TypeError, ValueError):
                continue
            # ``level`` includes live attribute modifiers; ``level_base`` does not.
            return _valid_rank(getattr(attribute, "level", None))
        return None

    def _resolve_panic_duration_ms(self) -> int | None:
        try:
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import Player
            from Py4GWCoreLib.Skill import Skill

            player_agent_id = int(Player.GetAgentID() or 0)
            if player_agent_id <= 0:
                return None
            domination_rank = self._current_attribute_rank(
                Agent,
                player_agent_id,
                PANIC_DOMINATION_ATTRIBUTE_ID,
            )
            if domination_rank is None:
                return None
            progressions = Skill.GetProgressionData(self._skill_id)
            for attribute_name, field_name, values in progressions or ():
                if str(attribute_name).strip() != "Domination Magic" or str(field_name).strip() != "Duration":
                    continue
                return self._duration_to_ms(values.get(domination_rank))
        except Exception:
            return None
        return None

    def _resolve_runtime_parameters(self) -> _RuntimeParameters | None:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Range

        try:
            effect_radius = _finite_float(GLOBAL_CACHE.Skill.Data.GetAoERange(self._skill_id))
            if effect_radius is None or effect_radius <= 0.0:
                effect_radius = _finite_float(getattr(Range.Nearby, "value", None))
            cast_range = _finite_float(getattr(Range.Spellcast, "value", None))
            activation_ms = self._duration_to_ms(GLOBAL_CACHE.Skill.Data.GetActivation(self._skill_id))
            aftercast_ms = self._duration_to_ms(GLOBAL_CACHE.Skill.Data.GetAftercast(self._skill_id))
            if (
                effect_radius is None
                or cast_range is None
                or activation_ms is None
                or aftercast_ms is None
                or effect_radius <= 0.0
                or cast_range <= 0.0
            ):
                return None
            return _RuntimeParameters(
                policy=PanicPolicy(
                    cast_range=cast_range,
                    effect_radius=effect_radius,
                ),
                aftercast_delay_ms=max(250, activation_ms + aftercast_ms + 100),
                activation_ms=activation_ms,
                panic_duration_ms=self._resolve_panic_duration_ms(),
            )
        except Exception:
            return None

    def _combat_option_enabled(self) -> bool:
        try:
            options = getattr(self._cached_data, "account_options", None)
            if options is None:
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
            options = getattr(self._cached_data, "account_options", None)
            if options is None:
                from Py4GWCoreLib import GLOBAL_CACHE
                from Py4GWCoreLib import Player

                owner_email = str(Player.GetAccountEmail() or "").strip()
                if not owner_email:
                    return False
                options = GLOBAL_CACHE.ShMem.GetHeroAIOptionsFromEmail(owner_email)
            skills = getattr(options, "Skills", None)
            if skills is None or not 1 <= int(slot) <= 8:
                return False
            return bool(skills[int(slot) - 1])
        except (AttributeError, IndexError, TypeError, ValueError):
            return False

    def _resolve_current_slot(self) -> int | None:
        try:
            from Py4GWCoreLib import SkillBar

            slot = self._skill_slot
            if slot is None or not 1 <= slot <= 8:
                return None
            if int(SkillBar.GetSkillIDBySlot(slot) or 0) != self._skill_id:
                return None
            return slot
        except (AttributeError, TypeError, ValueError):
            return None

    def _skill_readiness(self, slot: int) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Player
            from Py4GWCoreLib import Routines

            if self._resolve_current_slot() != slot or not self._skill_toggle_enabled(slot):
                return False
            if not bool(self.CanCastSkillSlot(slot)):
                return False
            can_cast = getattr(Routines.Checks.Skills, "CanCast", None)
            if callable(can_cast) and not bool(can_cast()):
                return False
            enough_energy = getattr(Routines.Checks.Skills, "HasEnoughEnergy", None)
            if callable(enough_energy) and not bool(enough_energy(Player.GetAgentID(), self._skill_id)):
                return False
            skill_ready = getattr(Routines.Checks.Skills, "IsSkillSlotReady", None)
            if callable(skill_ready) and not bool(skill_ready(slot)):
                return False
            skill_data = GLOBAL_CACHE.SkillBar.GetSkillData(slot)
            recharge = _finite_float(getattr(skill_data, "recharge", None))
            return recharge == 0.0
        except Exception:
            return False

    def _runtime_gate(self) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import Map
            from Py4GWCoreLib import Player
            from Py4GWCoreLib import Routines

            if not bool(Map.IsMapReady()) or not bool(Map.IsExplorable()) or bool(Map.IsInCinematic()):
                return False
            if not bool(Routines.Checks.Map.MapValid()) or not bool(Routines.Checks.Player.CanAct()):
                return False
            player_agent_id = int(Player.GetAgentID() or 0)
            if (
                player_agent_id <= 0
                or not bool(Agent.IsValid(player_agent_id))
                or not bool(Agent.IsLiving(player_agent_id))
                or not bool(Agent.IsAlive(player_agent_id))
                or bool(Agent.IsKnockedDown(player_agent_id))
                or bool(Agent.IsCasting(player_agent_id))
            ):
                return False
            if int(GLOBAL_CACHE.SkillBar.GetCasting() or 0) != 0:
                return False
            return self._combat_option_enabled()
        except Exception:
            return False

    def _skill_target_is_allowed(self, agent_id: int) -> bool:
        try:
            return bool(self._validate_target_for_skill_cast(self._skill_id, int(agent_id)))
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

    @staticmethod
    def _optional_agent_bool(agent_api: Any, name: str, agent_id: int) -> bool | None:
        try:
            function = getattr(agent_api, name, None)
            if not callable(function):
                return None
            value = function(agent_id)
            return None if value is None else bool(value)
        except Exception:
            return None

    @staticmethod
    def _read_npc_flags(agent_api: Any, agent_id: int) -> int | None:
        try:
            function = getattr(agent_api, "GetNPCFlagsOptional", None)
            if not callable(function):
                return None
            value = function(agent_id)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _effect_entry_skill_id(effect: Any) -> int | None:
        for name in ("skill_id", "SkillId", "skillId"):
            value = getattr(effect, name, None)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError, OverflowError):
                return None
        return None

    def _read_panic_effect_observation(self, agent_id: int) -> _PanicEffectRead:
        """Read positive effect evidence without treating hostile absence as proof."""

        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Routines
        except Exception:
            return _PanicEffectRead(projection=None, state=PanicEffectState.UNKNOWN)

        successful_absence = False
        checks = getattr(getattr(Routines, "Checks", None), "Agents", None)
        effects = getattr(GLOBAL_CACHE, "Effects", None)
        for owner in (checks, effects):
            has_effect = getattr(owner, "HasEffect", None)
            if not callable(has_effect):
                continue
            try:
                value = has_effect(agent_id, self._skill_id)
            except Exception:
                continue
            if isinstance(value, bool):
                if value:
                    return _PanicEffectRead(
                        projection=True,
                        state=PanicEffectState.OBSERVED_PRESENT,
                    )
                successful_absence = True

        for owner in (effects,):
            for name in ("GetEffects", "GetBuffs"):
                getter = getattr(owner, name, None)
                if not callable(getter):
                    continue
                try:
                    entries = getter(agent_id)
                    if entries is None:
                        continue
                    successful_absence = True
                    for entry in cast(Iterable[Any], entries):
                        if self._effect_entry_skill_id(entry) == self._skill_id:
                            return _PanicEffectRead(
                                projection=True,
                                state=PanicEffectState.OBSERVED_PRESENT,
                            )
                except Exception:
                    continue

        if successful_absence:
            return _PanicEffectRead(projection=False, state=PanicEffectState.UNKNOWN)
        return _PanicEffectRead(projection=None, state=PanicEffectState.UNKNOWN)

    def _read_panic_effect(self, agent_id: int) -> bool | None:
        """Compatibility projection; semantic absence remains UNKNOWN internally."""

        return self._read_panic_effect_observation(agent_id).projection

    def _agent_is_live_hostile(self, agent_id: int) -> bool:
        try:
            from Py4GWCoreLib import Agent

            return bool(
                Agent.IsValid(agent_id)
                and Agent.IsLiving(agent_id)
                and Agent.IsAlive(agent_id)
                and self._is_enemy(agent_id)
            )
        except Exception:
            return False

    def _agent_is_countable(self, agent_id: int) -> bool:
        if not self._agent_is_live_hostile(agent_id):
            return False
        try:
            from Py4GWCoreLib import Agent

            spirit_observation = PanicTargetObservation(
                agent_id=int(agent_id),
                x=0.0,
                y=0.0,
                distance_from_player=0.0,
                agent_is_spirit=self._optional_agent_bool(Agent, "IsSpirit", agent_id),
                npc_flags=self._read_npc_flags(Agent, agent_id),
            )
            return classify_panic_spirit(spirit_observation) is PanicSpiritClassification.CONFIRMED_NOT_SPIRIT
        except Exception:
            return False

    def _prune_coverage(self, now_ms: int) -> None:
        expired: list[tuple[int, int]] = []
        removed_early: list[tuple[int, int]] = []
        for agent_id, expiry_ms in tuple(self._coverage_expiry_by_agent.items()):
            if now_ms >= expiry_ms:
                expired.append((agent_id, expiry_ms))
                continue
            if not self._agent_is_countable(agent_id):
                removed_early.append((agent_id, expiry_ms))

        removed_agent_ids = {agent_id for agent_id, _ in expired}
        removed_agent_ids.update(agent_id for agent_id, _ in removed_early)
        for agent_id in removed_agent_ids:
            self._coverage_expiry_by_agent.pop(agent_id, None)

    def _build_snapshot(self, _parameters: _RuntimeParameters) -> tuple[PanicTargetObservation, ...] | None:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player

        player_position = _position(Player.GetXY())
        if player_position is None:
            return None
        try:
            raw_enemy_ids = AgentArray.GetEnemyArray()
        except Exception:
            return None
        if raw_enemy_ids is None:
            return None

        now_ms = self._now_ms()
        if now_ms is not None:
            self._prune_coverage(now_ms)

        observations: list[PanicTargetObservation] = []
        seen_ids: set[int] = set()
        for raw_agent_id in raw_enemy_ids:
            try:
                agent_id = int(raw_agent_id)
                if agent_id <= 0 or agent_id in seen_ids:
                    continue
                seen_ids.add(agent_id)
                is_valid = bool(Agent.IsValid(agent_id))
                is_living = bool(Agent.IsLiving(agent_id))
                is_alive = bool(Agent.IsAlive(agent_id))
                is_hostile = self._is_enemy(agent_id)
                is_targetable = (
                    self._skill_target_is_allowed(agent_id)
                    if is_valid and is_living and is_alive and is_hostile
                    else False
                )
                position = _position(Agent.GetXY(agent_id))
                distance = None
                if position is not None:
                    distance = math.hypot(
                        position[0] - player_position[0],
                        position[1] - player_position[1],
                    )
                    if not math.isfinite(distance):
                        distance = None
                effect_read = self._read_panic_effect_observation(agent_id)
                panic_state = effect_read.state
                has_panic = effect_read.projection
                if agent_id in self._coverage_expiry_by_agent:
                    panic_state = PanicEffectState.LOCALLY_COVERED
                    has_panic = True
                observations.append(
                    PanicTargetObservation(
                        agent_id=agent_id,
                        x=None if position is None else position[0],
                        y=None if position is None else position[1],
                        distance_from_player=distance,
                        is_valid=is_valid,
                        is_living=is_living,
                        is_alive=is_alive,
                        is_hostile=is_hostile,
                        is_targetable=is_targetable,
                        agent_is_spirit=self._optional_agent_bool(Agent, "IsSpirit", agent_id),
                        npc_flags=self._read_npc_flags(Agent, agent_id),
                        has_panic=has_panic,
                        panic_state=panic_state,
                        is_caster=self._optional_agent_bool(Agent, "IsCaster", agent_id),
                        is_support=None,
                        is_casting=self._optional_agent_bool(Agent, "IsCasting", agent_id),
                    )
                )
            except Exception:
                continue
        return tuple(sorted(observations, key=lambda observation: observation.agent_id))

    def _evaluate_live(self, parameters: _RuntimeParameters) -> PanicDecision | None:
        snapshot = self._build_snapshot(parameters)
        if snapshot is None:
            return None
        decision = evaluate_smart_panic(snapshot, policy=parameters.policy)
        return decision

    @staticmethod
    def _same_policy(first: _RuntimeParameters, second: _RuntimeParameters) -> bool:
        return first.policy == second.policy

    def _remember_event_key(self, key: tuple[int, int, int, int, int, float]) -> bool:
        if key in self._seen_event_keys:
            return False
        if len(self._seen_event_order) == self._seen_event_order.maxlen:
            oldest = self._seen_event_order.popleft()
            self._seen_event_keys.discard(oldest)
        self._seen_event_order.append(key)
        self._seen_event_keys.add(key)
        return True

    @staticmethod
    def _parse_agent_event(event: Any) -> tuple[int, int, int, int, int, float] | None:
        try:
            timestamp = int(getattr(event, "timestamp"))
            event_type = int(getattr(event, "event_type"))
            agent_id = int(getattr(event, "agent_id"))
            value = int(getattr(event, "value"))
            target_id = int(getattr(event, "target_id"))
            float_value = float(getattr(event, "float_value", 0.0))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(float_value):
            float_value = 0.0
        return timestamp, event_type, agent_id, value, target_id, float_value

    @staticmethod
    def _peek_agent_events() -> tuple[Any, ...] | None:
        try:
            import PyAgentEvents

            peek_events = getattr(PyAgentEvents, "peek_events", None)
            if not callable(peek_events):
                return None
            return tuple(cast(Iterable[Any], peek_events() or ()))
        except Exception:
            return None

    def _complete_pending_receipt(
        self,
        receipt: _PendingPanicReceipt,
        finish_timestamp_ms: int,
        now_ms: int,
    ) -> None:
        if self._pending_receipt is not receipt:
            return
        if (
            self._lifecycle_id != receipt.lifecycle_id
            or self._composition_generation != receipt.composition_generation
            or receipt.activation_timestamp_ms is None
            or finish_timestamp_ms < receipt.activation_timestamp_ms
            or finish_timestamp_ms > receipt.receipt_deadline_ms
            or now_ms < finish_timestamp_ms
            or self._read_player_alive(receipt.player_agent_id) is not True
            or not self._agent_is_countable(receipt.target_agent_id)
        ):
            self._pending_receipt = None
            return

        retained_agent_ids = tuple(
            agent_id for agent_id in receipt.affected_agent_ids if self._agent_is_countable(agent_id)
        )
        duration_ms = receipt.panic_duration_ms
        if duration_ms is None or duration_ms <= 0:
            self._pending_receipt = None
            return
        if not retained_agent_ids:
            self._pending_receipt = None
            return
        expiry_ms = finish_timestamp_ms + duration_ms
        for agent_id in retained_agent_ids:
            previous_expiry = self._coverage_expiry_by_agent.get(agent_id, 0)
            self._coverage_expiry_by_agent[agent_id] = max(previous_expiry, expiry_ms)
        self._pending_receipt = None

    def _poll_pending_receipt(self, now_ms: int) -> None:
        receipt = self._pending_receipt
        if receipt is None:
            return
        if self._lifecycle_id != receipt.lifecycle_id or self._composition_generation != receipt.composition_generation:
            self._pending_receipt = None
            return
        events = self._peek_agent_events()
        if events is None:
            return
        parsed_events = [self._parse_agent_event(event) for event in events]
        ordered_events = sorted(
            (event for event in parsed_events if event is not None),
            key=lambda event: event[0],
        )
        for timestamp, event_type, agent_id, value, target_id, float_value in ordered_events:
            key = (timestamp, event_type, agent_id, value, target_id, float_value)
            if timestamp < 0 or timestamp <= receipt.dispatch_timestamp_ms:
                self._remember_event_key(key)
                continue
            # The lifecycle clock is sampled before peek_events(). An event can
            # therefore be captured after that sample while still appearing in
            # the same snapshot. Do not deduplicate it until a later poll can
            # actually process it.
            if timestamp > now_ms:
                continue
            if not self._remember_event_key(key):
                continue
            if timestamp > receipt.receipt_deadline_ms or agent_id != receipt.player_agent_id:
                continue

            if event_type == 1:
                if receipt.accepted_activation_key == key:
                    continue
                if value != self._skill_id:
                    self._pending_receipt = None
                    return
                if receipt.activation_timestamp_ms is not None:
                    self._pending_receipt = None
                    return
                if target_id != receipt.target_agent_id:
                    self._pending_receipt = None
                    return
                receipt.activation_timestamp_ms = timestamp
                receipt.accepted_activation_key = key
                continue

            if event_type not in (3, 4, 6) or value not in (0, self._skill_id):
                continue
            if receipt.activation_timestamp_ms is None or timestamp < receipt.activation_timestamp_ms:
                self._pending_receipt = None
                return
            if event_type == 4:
                self._complete_pending_receipt(receipt, timestamp, now_ms)
            else:
                self._pending_receipt = None
            return

        # A poll can arrive after the deadline while still carrying an event
        # captured at the deadline. Resolve that event before applying timeout.
        if self._pending_receipt is receipt and now_ms > receipt.receipt_deadline_ms:
            self._pending_receipt = None

    def _prune_recent_group(self, now_ms: int) -> None:
        recent = self._recent_group
        if recent is None:
            return
        elapsed = now_ms - recent.accepted_at_ms
        if elapsed < 0 or elapsed > PANIC_RECENT_GROUP_WINDOW_MS:
            self._recent_group = None

    def _recent_group_is_wasteful(self, selected: PanicCandidateEvaluation, now_ms: int) -> bool:
        self._prune_recent_group(now_ms)
        recent = self._recent_group
        if recent is None or not selected.affected_agent_ids:
            return False
        current_ids = frozenset(selected.affected_agent_ids)
        overlap = len(current_ids.intersection(recent.agent_ids)) / min(len(current_ids), len(recent.agent_ids))
        if overlap < PANIC_RECENT_GROUP_OVERLAP_RATIO:
            return False
        return selected.uncovered_count <= recent.uncovered_count

    def _remember_recent_group(self, selected: PanicCandidateEvaluation, now_ms: int) -> None:
        self._recent_group = _RecentPanicGroup(
            agent_ids=frozenset(selected.affected_agent_ids),
            accepted_at_ms=now_ms,
            uncovered_count=selected.uncovered_count,
        )

    def _final_revalidate(
        self,
        selected_agent_id: int,
        parameters: _RuntimeParameters,
    ) -> tuple[_RuntimeParameters, PanicCandidateEvaluation] | None:
        if not self._refresh_lifecycle() or not self._runtime_gate():
            return None
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return None
        try:
            if not bool(self.CanCastSkillID(self._skill_id)):
                return None
        except Exception:
            return None
        current_parameters = self._resolve_runtime_parameters()
        if current_parameters is None or not self._same_policy(parameters, current_parameters):
            return None
        decision = self._evaluate_live(current_parameters)
        if decision is None or decision.selected is None:
            return None
        if decision.selected.target_agent_id != int(selected_agent_id):
            return None
        now_ms = self._now_ms()
        if now_ms is None or self._recent_group_is_wasteful(decision.selected, now_ms):
            return None
        return current_parameters, decision.selected

    def _dispatch_selected(
        self,
        selected_agent_id: int,
        parameters: _RuntimeParameters,
    ) -> Generator[None, None, bool]:
        if False:
            yield
        validated = self._final_revalidate(selected_agent_id, parameters)
        if validated is None or self._lifecycle_id is None:
            return False
        current_parameters, current_selected = validated
        now_ms = self._now_ms()
        if now_ms is None:
            return False
        lifecycle_id = self._lifecycle_id
        if lifecycle_id is None:
            return False
        self._pending_receipt = _PendingPanicReceipt(
            lifecycle_id=lifecycle_id,
            composition_generation=self._composition_generation,
            player_agent_id=lifecycle_id[1],
            target_agent_id=int(current_selected.target_agent_id),
            affected_agent_ids=tuple(current_selected.affected_agent_ids),
            dispatch_timestamp_ms=now_ms,
            receipt_deadline_ms=(
                now_ms
                + current_parameters.aftercast_delay_ms
                + current_parameters.activation_ms
                + PANIC_RECEIPT_SAFETY_MARGIN_MS
            ),
            panic_duration_ms=current_parameters.panic_duration_ms,
        )
        self._pending_local_attempt = (int(selected_agent_id), self._lifecycle_id)
        try:
            result = cast(
                Any,
                self.CastSkillID(
                    skill_id=self._skill_id,
                    log=False,
                    aftercast_delay=current_parameters.aftercast_delay_ms,
                    target_agent_id=int(selected_agent_id),
                ),
            )
            if hasattr(result, "__next__"):
                result = yield from cast(Generator[None, None, Any], result)
            accepted = bool(result)
            if accepted:
                self._remember_recent_group(current_selected, now_ms)
            else:
                self._pending_receipt = None
            return accepted
        except Exception:
            self._pending_receipt = None
            return False
        finally:
            self._pending_local_attempt = None

    def _run_local_skill_logic(self) -> Generator[None, None, bool]:
        if False:
            yield
        now_ms = self._now_ms()
        if now_ms is None or not self._refresh_lifecycle():
            return False
        self._prune_recent_group(now_ms)
        self._prune_coverage(now_ms)
        self._poll_pending_receipt(now_ms)
        if self.has_active_dispatch() or not self._runtime_gate():
            return False
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return False
        parameters = self._resolve_runtime_parameters()
        if parameters is None:
            return False
        decision = self._evaluate_live(parameters)
        if decision is None or decision.selected is None:
            return False
        if self._recent_group_is_wasteful(decision.selected, now_ms):
            return False
        return (yield from self._dispatch_selected(decision.selected.target_agent_id, parameters))


evaluate_panic = evaluate_smart_panic
PanicCandidateReason = CandidateReason
PanicDecisionReason = DecisionReason


__all__ = [
    "CandidateReason",
    "DecisionReason",
    "PANIC_MINIMUM_AFFECTED",
    "PANIC_NAME",
    "NPC_SPIRIT_FLAG",
    "PANIC_RECENT_GROUP_OVERLAP_RATIO",
    "PANIC_RECENT_GROUP_WINDOW_MS",
    "PANIC_RECEIPT_SAFETY_MARGIN_MS",
    "PANIC_SKILL_ID",
    "PanicCandidateEvaluation",
    "PanicCandidateReason",
    "PanicDecision",
    "PanicDecisionReason",
    "PanicEffectState",
    "PanicPolicy",
    "PanicSpiritClassification",
    "PanicTargetObservation",
    "SmartPanic",
    "classify_panic_spirit",
    "evaluate_panic",
    "evaluate_smart_panic",
]
