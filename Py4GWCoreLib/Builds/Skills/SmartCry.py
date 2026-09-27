"""Pure deterministic Cry of Frustration policy primitives.

This module deliberately owns no runtime reads, clock access, casting, target
selection, BuildMgr calls, shared-memory calls, or claim state.  A future
controller supplies immutable observations and adapts HeroAI's structured
interrupt assessment into :class:`CryInterruptEvidence`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import replace
from enum import Enum
from typing import Final

from Py4GWCoreLib.Builds.Skills.SmartMesmer import CombatSnapshot
from Py4GWCoreLib.Builds.Skills.SmartMesmer import EnemyObservation
from Py4GWCoreLib.Builds.Skills.SmartMesmer import PairwiseDistances
from Py4GWCoreLib.Builds.Skills.SmartMesmer import pairwise_squared_distances


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


class CryDecisionReason(str, Enum):
    SELECTED = "selected"
    INVALID_CRY_RADIUS = "invalid_cry_radius"
    INVALID_CAST_RANGE = "invalid_cast_range"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    ALL_USEFUL_CASTS_HANDLED = "all_useful_casts_handled"


class CryCandidateReason(str, Enum):
    ELIGIBLE = "eligible"
    DEAD_PRIMARY = "dead_primary"
    NON_HOSTILE_PRIMARY = "non_hostile_primary"
    TARGET_NOT_ALLOWED = "target_not_allowed"
    OUT_OF_CAST_RANGE = "out_of_cast_range"
    NO_ACTIVE_CAST = "no_active_cast"
    INVALID_SKILL_ID = "invalid_skill_id"
    CAST_NOT_ACTIVE = "cast_not_active"
    CAST_ASSESSMENT_MISMATCH = "cast_assessment_mismatch"
    UNKNOWN_TIMING = "unknown_timing"
    MECHANICALLY_INFEASIBLE = "mechanically_infeasible"
    BELOW_MINIMUM_VALUE = "below_minimum_value"


class CrySkillCategory(str, Enum):
    UNKNOWN = "unknown"
    HEALING = "healing"
    RESURRECTION = "resurrection"
    OTHER = "other"


class CryClassificationProvenance(str, Enum):
    UNCLASSIFIED = "unclassified"
    HEROAI_METADATA = "heroai_metadata"
    DEFAULT_METADATA = "default_metadata"


class CryOnsetConfidence(str, Enum):
    UNKNOWN = "unknown"
    UNCERTAIN = "uncertain"
    TRUSTED = "trusted"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class CryPolicyParameters:
    """Explicit V1 policy tunables, not Guild Wars facts."""

    resurrection_value: int = 4
    healing_value: int = 2
    generic_value: int = 1
    unknown_value: int = 0
    minimum_candidate_value: int = 2

    def __post_init__(self) -> None:
        for name in (
            "resurrection_value",
            "healing_value",
            "generic_value",
            "unknown_value",
            "minimum_candidate_value",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


DEFAULT_POLICY: Final[CryPolicyParameters] = CryPolicyParameters()


@dataclass(frozen=True, slots=True)
class CryCastKey:
    """A local cast key; identity is process-local when supplied."""

    enemy_agent_id: int
    enemy_skill_id: int
    observation_identity: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enemy_agent_id, int) or self.enemy_agent_id <= 0:
            raise ValueError("enemy_agent_id must be a positive integer")
        if not isinstance(self.enemy_skill_id, int) or self.enemy_skill_id <= 0:
            raise ValueError("enemy_skill_id must be a positive integer")
        if self.observation_identity is not None:
            identity = tuple(self.observation_identity)
            if not identity or any(not isinstance(value, int) for value in identity):
                raise ValueError("observation_identity must be a non-empty integer tuple")
            object.__setattr__(self, "observation_identity", identity)


@dataclass(frozen=True, slots=True)
class CryInterruptEvidence:
    """Immutable adapter for HeroAI's mechanical interrupt assessment."""

    target_agent_id: int
    enemy_skill_id: int
    mechanically_feasible: bool
    timing_trusted: bool
    reason: str = "unknown"
    cast_active: bool = True
    observation_identity: tuple[int, ...] | None = None
    observation_age_ms: int | None = None
    onset_confidence: CryOnsetConfidence = CryOnsetConfidence.UNKNOWN

    def __post_init__(self) -> None:
        if self.target_agent_id <= 0 or self.enemy_skill_id <= 0:
            raise ValueError("target_agent_id and enemy_skill_id must be positive")
        if self.observation_identity is not None:
            identity = tuple(self.observation_identity)
            if not identity or any(not isinstance(value, int) for value in identity):
                raise ValueError("observation_identity must be a non-empty integer tuple")
            object.__setattr__(self, "observation_identity", identity)
        if self.observation_age_ms is not None:
            if self.observation_age_ms < 0:
                raise ValueError("observation_age_ms must be non-negative")
        try:
            object.__setattr__(self, "onset_confidence", CryOnsetConfidence(self.onset_confidence))
        except ValueError as error:
            raise ValueError("invalid onset_confidence") from error

    @property
    def cast_key(self) -> CryCastKey:
        return CryCastKey(
            self.target_agent_id,
            self.enemy_skill_id,
            self.observation_identity,
        )


@dataclass(frozen=True, slots=True)
class CrySkillClassification:
    """Classification evidence supplied by a future runtime adapter.

    A category is valuable only when the current HeroAI metadata entry is
    meaningful and explicitly populated.  Broad defaults on an empty
    ``CustomSkill`` record therefore remain generic rather than becoming
    invented healing or resurrection evidence.
    """

    category: CrySkillCategory = CrySkillCategory.UNKNOWN
    provenance: CryClassificationProvenance = CryClassificationProvenance.UNCLASSIFIED
    metadata_populated: bool = False

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "category", CrySkillCategory(self.category))
            object.__setattr__(self, "provenance", CryClassificationProvenance(self.provenance))
        except ValueError as error:
            raise ValueError("invalid skill classification") from error

    @property
    def is_explicit_supported_category(self) -> bool:
        return (
            self.metadata_populated
            and self.provenance is CryClassificationProvenance.HEROAI_METADATA
            and self.category in (CrySkillCategory.HEALING, CrySkillCategory.RESURRECTION)
        )


@dataclass(frozen=True, slots=True)
class CryCastObservation:
    """One current enemy cast and all policy facts needed to value it."""

    enemy_skill_id: int
    interrupt: CryInterruptEvidence
    classification: CrySkillClassification = CrySkillClassification()
    value_override: int | None = None
    value_reason: str | None = None

    def __post_init__(self) -> None:
        if self.enemy_skill_id <= 0:
            raise ValueError("enemy_skill_id must be positive")
        if self.interrupt.enemy_skill_id != self.enemy_skill_id:
            raise ValueError("interrupt evidence must match enemy_skill_id")
        if self.value_override is not None and (
            not isinstance(self.value_override, int) or isinstance(self.value_override, bool) or self.value_override < 0
        ):
            raise ValueError("value_override must be a non-negative integer")

    @property
    def cast_key(self) -> CryCastKey:
        return self.interrupt.cast_key


@dataclass(frozen=True, slots=True)
class CryEnemyObservation:
    """Immutable geometry, target eligibility, and current cast facts."""

    observation: EnemyObservation
    distance_from_player: float
    is_alive: bool = True
    is_hostile: bool = True
    target_allowed: bool = True
    current_cast: CryCastObservation | None = None

    def __post_init__(self) -> None:
        _require_finite("distance_from_player", self.distance_from_player)
        if self.distance_from_player < 0.0:
            raise ValueError("distance_from_player must be non-negative")

    @property
    def agent_id(self) -> int:
        return self.observation.agent_id


@dataclass(frozen=True, slots=True)
class CryCandidateEvaluation:
    """Pure value, eligibility, affected-area, and overlap diagnostics."""

    primary_agent_id: int
    primary_enemy_skill_id: int
    eligible: bool
    reason: CryCandidateReason
    affected_enemy_ids: tuple[int, ...]
    feasible_covered_cast_keys: tuple[CryCastKey, ...]
    covered_cast_keys: tuple[CryCastKey, ...]
    handled_cast_keys: tuple[CryCastKey, ...]
    covered_cast_values: tuple[tuple[CryCastKey, int], ...]
    total_interrupt_value: int
    primary_cast_value: int
    feasible_covered_cast_count: int
    overlapping_primary_agent_ids: tuple[int, ...] = ()
    redundant: bool = False
    canonical_primary_agent_id: int | None = None

    @property
    def candidate_total_value(self) -> int:
        return self.total_interrupt_value

    @property
    def covered_feasible_cast_count(self) -> int:
        return self.feasible_covered_cast_count

    @property
    def actual_affected_enemy_ids(self) -> tuple[int, ...]:
        return self.affected_enemy_ids


@dataclass(frozen=True, slots=True)
class CryDecision:
    """Immutable pure Cry decision; it performs no action."""

    selected: CryCandidateEvaluation | None
    reason: CryDecisionReason
    candidates: tuple[CryCandidateEvaluation, ...]
    canonical_candidates: tuple[CryCandidateEvaluation, ...]

    @property
    def admitted(self) -> bool:
        return self.selected is not None

    @property
    def selected_primary_agent_id(self) -> int | None:
        return None if self.selected is None else self.selected.primary_agent_id


def _empty_decision(reason: CryDecisionReason) -> CryDecision:
    return CryDecision(selected=None, reason=reason, candidates=(), canonical_candidates=())


def _normalise_enemies(
    snapshot: CombatSnapshot,
    enemies: Iterable[CryEnemyObservation],
) -> tuple[CryEnemyObservation, ...]:
    supplied = tuple(sorted(tuple(enemies), key=lambda enemy: enemy.agent_id))
    agent_ids = tuple(enemy.agent_id for enemy in supplied)
    if len(agent_ids) != len(set(agent_ids)):
        raise ValueError("Cry observations cannot contain duplicate agent IDs")
    if agent_ids != snapshot.agent_ids:
        raise ValueError("Cry observations must cover exactly the snapshot agent IDs")
    geometry_key = tuple((enemy.observation.agent_id, enemy.observation.x, enemy.observation.y) for enemy in supplied)
    if geometry_key != snapshot.geometry_key:
        raise ValueError("Cry observations must use the snapshot geometry")
    return supplied


def _validate_pairwise_distances(snapshot: CombatSnapshot, distances: PairwiseDistances) -> None:
    if distances.agent_ids != snapshot.agent_ids or distances.geometry_key != snapshot.geometry_key:
        raise ValueError("pairwise distances must belong to this snapshot")


def _normalise_cast_key(value: CryCastKey | tuple[int, int] | tuple[int, int, tuple[int, ...] | None]) -> CryCastKey:
    if isinstance(value, CryCastKey):
        return value
    if len(value) == 2:
        return CryCastKey(int(value[0]), int(value[1]))
    if len(value) == 3:
        identity = value[2]
        return CryCastKey(int(value[0]), int(value[1]), identity)
    raise ValueError("cast keys must contain two or three values")


def _normalise_handled_casts(
    handled_cast_keys: Iterable[CryCastKey | tuple[int, int] | tuple[int, int, tuple[int, ...] | None]],
) -> frozenset[CryCastKey]:
    return frozenset(_normalise_cast_key(value) for value in handled_cast_keys)


def _cast_is_handled(cast_key: CryCastKey, handled: frozenset[CryCastKey]) -> bool:
    return cast_key in handled or (
        cast_key.observation_identity is not None
        and CryCastKey(cast_key.enemy_agent_id, cast_key.enemy_skill_id) in handled
    )


def _assessment_reason(
    cast: CryCastObservation,
    expected_agent_id: int | None = None,
) -> CryCandidateReason | None:
    assessment = cast.interrupt
    if expected_agent_id is not None and assessment.target_agent_id != expected_agent_id:
        return CryCandidateReason.CAST_ASSESSMENT_MISMATCH
    if not assessment.cast_active:
        return CryCandidateReason.CAST_NOT_ACTIVE
    if not assessment.timing_trusted:
        return CryCandidateReason.UNKNOWN_TIMING
    if not assessment.mechanically_feasible:
        return CryCandidateReason.MECHANICALLY_INFEASIBLE
    return None


def _cast_value(cast: CryCastObservation, policy: CryPolicyParameters) -> int:
    if cast.value_override is not None:
        return cast.value_override
    classification = cast.classification
    if not classification.is_explicit_supported_category:
        return policy.generic_value
    if classification.category is CrySkillCategory.RESURRECTION:
        return policy.resurrection_value
    if classification.category is CrySkillCategory.HEALING:
        return policy.healing_value
    return policy.generic_value


def _cast_sort_key(cast_key: CryCastKey) -> tuple[int, int, tuple[int, ...]]:
    return (
        cast_key.enemy_agent_id,
        cast_key.enemy_skill_id,
        () if cast_key.observation_identity is None else cast_key.observation_identity,
    )


def _candidate_sort_key(candidate: CryCandidateEvaluation) -> tuple[int, int, int, int, int]:
    return (
        0 if candidate.eligible else 1,
        -candidate.total_interrupt_value,
        -candidate.feasible_covered_cast_count,
        -candidate.primary_cast_value,
        candidate.primary_agent_id,
    )


def evaluate_smart_cry(
    snapshot: CombatSnapshot,
    enemies: Iterable[CryEnemyObservation],
    *,
    cry_radius: float,
    cast_range: float,
    pairwise_distances: PairwiseDistances | None = None,
    handled_cast_keys: Iterable[CryCastKey | tuple[int, int] | tuple[int, int, tuple[int, ...] | None]] = (),
    policy: CryPolicyParameters = DEFAULT_POLICY,
) -> CryDecision:
    """Evaluate one coherent immutable snapshot without runtime dependencies."""

    if not math.isfinite(cry_radius) or cry_radius < 0.0:
        return _empty_decision(CryDecisionReason.INVALID_CRY_RADIUS)
    if not math.isfinite(cast_range) or cast_range < 0.0:
        return _empty_decision(CryDecisionReason.INVALID_CAST_RANGE)

    observations = _normalise_enemies(snapshot, enemies)
    distances = pairwise_distances or pairwise_squared_distances(snapshot)
    _validate_pairwise_distances(snapshot, distances)
    handled = _normalise_handled_casts(handled_cast_keys)
    index_by_agent_id = {agent_id: index for index, agent_id in enumerate(distances.agent_ids)}
    observation_by_agent_id = {enemy.agent_id: enemy for enemy in observations}
    radius_squared = cry_radius * cry_radius
    evaluations: list[CryCandidateEvaluation] = []
    any_feasible_cast = False
    any_unhandled_feasible_cast = False

    for primary in observations:
        primary_cast = primary.current_cast
        primary_skill_id = 0 if primary_cast is None else primary_cast.enemy_skill_id
        reason: CryCandidateReason | None = None
        if not primary.is_alive:
            reason = CryCandidateReason.DEAD_PRIMARY
        elif not primary.is_hostile:
            reason = CryCandidateReason.NON_HOSTILE_PRIMARY
        elif not primary.target_allowed:
            reason = CryCandidateReason.TARGET_NOT_ALLOWED
        elif primary.distance_from_player > cast_range:
            reason = CryCandidateReason.OUT_OF_CAST_RANGE
        elif primary_cast is None:
            reason = CryCandidateReason.NO_ACTIVE_CAST
        elif primary_skill_id <= 0:
            reason = CryCandidateReason.INVALID_SKILL_ID
        else:
            reason = _assessment_reason(primary_cast, primary.agent_id)

        primary_index = index_by_agent_id[primary.agent_id]
        affected_enemy_ids = tuple(
            enemy.agent_id
            for enemy in observations
            if enemy.is_alive
            and enemy.is_hostile
            and distances.matrix[primary_index][index_by_agent_id[enemy.agent_id]] <= radius_squared
        )

        feasible_keys: list[CryCastKey] = []
        covered_keys: list[CryCastKey] = []
        handled_keys: list[CryCastKey] = []
        covered_values: list[tuple[CryCastKey, int]] = []
        primary_value = 0
        for affected_agent_id in affected_enemy_ids:
            affected = observation_by_agent_id[affected_agent_id]
            cast = affected.current_cast
            if cast is None or _assessment_reason(cast, affected.agent_id) is not None:
                continue
            any_feasible_cast = True
            cast_key = cast.cast_key
            feasible_keys.append(cast_key)
            if _cast_is_handled(cast_key, handled):
                handled_keys.append(cast_key)
                continue
            value = _cast_value(cast, policy)
            any_unhandled_feasible_cast = True
            covered_keys.append(cast_key)
            covered_values.append((cast_key, value))
            if affected.agent_id == primary.agent_id:
                primary_value = value

        feasible_keys.sort(key=_cast_sort_key)
        covered_keys.sort(key=_cast_sort_key)
        handled_keys.sort(key=_cast_sort_key)
        covered_values.sort(key=lambda item: _cast_sort_key(item[0]))
        total_value = sum(value for _, value in covered_values)
        eligible = reason is None and total_value >= policy.minimum_candidate_value
        if reason is None and not eligible:
            reason = CryCandidateReason.BELOW_MINIMUM_VALUE
        if reason is None:
            reason = CryCandidateReason.ELIGIBLE

        evaluations.append(
            CryCandidateEvaluation(
                primary_agent_id=primary.agent_id,
                primary_enemy_skill_id=primary_skill_id,
                eligible=eligible,
                reason=reason,
                affected_enemy_ids=affected_enemy_ids,
                feasible_covered_cast_keys=tuple(feasible_keys),
                covered_cast_keys=tuple(covered_keys),
                handled_cast_keys=tuple(handled_keys),
                covered_cast_values=tuple(covered_values),
                total_interrupt_value=total_value,
                primary_cast_value=primary_value,
                feasible_covered_cast_count=len(covered_keys),
            )
        )

    ordered = sorted(evaluations, key=_candidate_sort_key)
    eligible_candidates = [candidate for candidate in ordered if candidate.eligible]
    annotated: list[CryCandidateEvaluation] = []
    for candidate in ordered:
        if not candidate.eligible:
            annotated.append(candidate)
            continue
        current_keys = set(candidate.covered_cast_keys)
        higher = eligible_candidates[: eligible_candidates.index(candidate)]
        overlap_ids = tuple(
            other.primary_agent_id for other in higher if current_keys.intersection(other.covered_cast_keys)
        )
        covering_higher = [other for other in higher if current_keys.issubset(set(other.covered_cast_keys))]
        redundant = bool(current_keys) and bool(covering_higher)
        canonical_id = covering_higher[0].primary_agent_id if redundant else None
        annotated.append(
            replace(
                candidate,
                overlapping_primary_agent_ids=overlap_ids,
                redundant=redundant,
                canonical_primary_agent_id=canonical_id,
            )
        )

    ordered_candidates = tuple(annotated)
    canonical_candidates = tuple(
        candidate for candidate in ordered_candidates if candidate.eligible and not candidate.redundant
    )
    selected = next((candidate for candidate in canonical_candidates), None)
    if selected is not None:
        decision_reason = CryDecisionReason.SELECTED
    elif any_feasible_cast and not any_unhandled_feasible_cast:
        decision_reason = CryDecisionReason.ALL_USEFUL_CASTS_HANDLED
    else:
        decision_reason = CryDecisionReason.NO_ELIGIBLE_CANDIDATE
    return CryDecision(
        selected=selected,
        reason=decision_reason,
        candidates=ordered_candidates,
        canonical_candidates=canonical_candidates,
    )


evaluate_cry = evaluate_smart_cry
CryPolicy = CryPolicyParameters
SmartCryDecision = CryDecision
SmartCryCandidateEvaluation = CryCandidateEvaluation


__all__ = [
    "CryCandidateEvaluation",
    "CryCandidateReason",
    "CryCastKey",
    "CryCastObservation",
    "CryClassificationProvenance",
    "CryDecision",
    "CryDecisionReason",
    "CryEnemyObservation",
    "CryInterruptEvidence",
    "CryOnsetConfidence",
    "CryPolicy",
    "CryPolicyParameters",
    "CrySkillCategory",
    "CrySkillClassification",
    "DEFAULT_POLICY",
    "SmartCryCandidateEvaluation",
    "SmartCryDecision",
    "evaluate_cry",
    "evaluate_smart_cry",
]
