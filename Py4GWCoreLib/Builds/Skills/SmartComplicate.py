"""Pure deterministic Complicate admission and proposal primitives.

This module consumes immutable observations from a runtime adapter. It owns no
runtime reads, timing calculations, casting, target selection, or claim state.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from typing import Final
from typing import TypeAlias

from Py4GWCoreLib.Builds.Skills.SmartCry import MAX_CAST_VALUE
from Py4GWCoreLib.Builds.Skills.SmartCry import CryCandidateEvaluation
from Py4GWCoreLib.Builds.Skills.SmartCry import CryCastKey

if TYPE_CHECKING:
    from Py4GWCoreLib.HeroAI.interrupt import InterruptAssessment
    from Py4GWCoreLib.HeroAI.interrupt import InterruptAssessmentReason
    from Py4GWCoreLib.HeroAI.interrupt import ObservationOnsetConfidence

COMPLICATE_SKILL_ID: Final[int] = 932

HandledCastKey: TypeAlias = CryCastKey | tuple[int, int] | tuple[int, int, tuple[int, ...] | None]


class ComplicateDecisionReason(str, Enum):
    SELECTED = "selected"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"


class ComplicateCandidateReason(str, Enum):
    ELIGIBLE = "eligible"
    PRIMARY_SKILL_UNAVAILABLE = "primary_skill_unavailable"
    MECHANICAL_ASSESSMENT_UNAVAILABLE = "mechanical_assessment_unavailable"
    ASSESSMENT_MISMATCH = "assessment_mismatch"
    ASSESSMENT_SKILL_MISMATCH = "assessment_skill_mismatch"
    MECHANICAL_RESULT_INCOMPLETE = "mechanical_result_incomplete"
    TIMING_UNTRUSTED = "timing_untrusted"
    MECHANICALLY_INFEASIBLE = "mechanically_infeasible"
    PRIMARY_CAST_HANDLED = "primary_cast_handled"
    PRIMARY_VALUE_UNAVAILABLE = "primary_value_unavailable"


@dataclass(frozen=True, slots=True)
class ComplicateCastValue:
    """Bounded value and provenance projected from a Smart Cry evaluation."""

    value: int
    source: str

    def __init__(self) -> None:
        raise TypeError("use from_smart_cry_evaluation() to create a resolved Complicate value")

    @classmethod
    def from_smart_cry_evaluation(
        cls,
        evaluation: CryCandidateEvaluation,
        *,
        expected_agent_id: int,
        expected_enemy_skill_id: int,
    ) -> ComplicateCastValue:
        """Project the value Smart Cry resolved for this exact primary cast."""

        if not isinstance(evaluation, CryCandidateEvaluation):
            raise ValueError("evaluation must be a Smart Cry CryCandidateEvaluation")
        _require_positive_id("expected_agent_id", expected_agent_id)
        _require_positive_id("expected_enemy_skill_id", expected_enemy_skill_id)
        if (
            evaluation.primary_agent_id != expected_agent_id
            or evaluation.primary_enemy_skill_id != expected_enemy_skill_id
        ):
            raise ValueError("Smart Cry evaluation must match the expected primary cast")
        if evaluation.primary_value_source == "unavailable":
            raise ValueError("Smart Cry evaluation has no resolved primary value")
        if evaluation.reason.name == "PRIMARY_HANDLED":
            raise ValueError("a handled Smart Cry primary cannot provide a Complicate value")

        value = evaluation.primary_cast_value
        source = evaluation.primary_value_source
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > MAX_CAST_VALUE:
            raise ValueError(f"resolved value must be an integer in the range 0..{MAX_CAST_VALUE}")
        if not _is_smart_cry_value_source(source):
            raise ValueError("source must match a resolved Smart Cry value source")

        projected = object.__new__(cls)
        object.__setattr__(projected, "value", value)
        object.__setattr__(projected, "source", source)
        return projected


def _is_smart_cry_value_source(source: object) -> bool:
    if not isinstance(source, str):
        return False
    if source in ("generic", "heroai_healing", "heroai_resurrection"):
        return True
    if not source.startswith("override:") or source != source.strip():
        return False
    reason = source.removeprefix("override:")
    return bool(reason) and reason == reason.strip()


def _require_positive_id(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class ComplicateInterruptEvidence:
    """Immutable view over HeroAI's shared interrupt assessment.

    This object retains the actual frozen assessment and its enum instances;
    it does not copy, rename, or recalculate HeroAI's mechanical result.
    """

    assessment: InterruptAssessment

    def __init__(self) -> None:
        raise TypeError("use from_assessment() with HeroAI InterruptAssessment")

    @classmethod
    def from_assessment(cls, assessment: InterruptAssessment) -> ComplicateInterruptEvidence:
        """Wrap a shared assessment after checking its internal consistency."""

        params = getattr(type(assessment), "__dataclass_params__", None)
        if params is None or not params.frozen:
            raise ValueError("assessment must be the immutable HeroAI InterruptAssessment")
        if not isinstance(assessment.feasible, bool) or not isinstance(assessment.strict, bool):
            raise ValueError("assessment feasibility and strictness must be bool values")
        reason = assessment.reason
        if not isinstance(reason, Enum) or not isinstance(reason.value, str):
            raise ValueError("assessment reason must retain its HeroAI enum value")
        onset = assessment.onset_confidence
        if not isinstance(onset, Enum) or not isinstance(onset.value, str):
            raise ValueError("assessment onset confidence must retain its HeroAI enum value")
        reason_is_feasible = reason.name == "FEASIBLE" and reason.value == "feasible"
        if assessment.feasible != reason_is_feasible:
            raise ValueError("assessment feasibility contradicts its reason enum")

        if onset.name not in ("UNKNOWN", "FIRST_SEEN", "CONFIRMED"):
            raise ValueError("assessment onset confidence is not a recognized HeroAI value")
        for name in ("target_agent_id", "our_skill_id", "enemy_skill_id"):
            value = getattr(assessment, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"assessment {name} must be a non-negative integer")
        identity = assessment.observation_identity
        if identity is not None:
            if (
                not isinstance(identity, tuple)
                or len(identity) != 3
                or any(not isinstance(value, int) or isinstance(value, bool) for value in identity)
                or identity[0] != assessment.target_agent_id
                or identity[1] != assessment.enemy_skill_id
                or identity[2] < 0
            ):
                raise ValueError("assessment observation identity contradicts its target or skill")
        for name in ("observation_age_ms", "enemy_remaining_ms", "interrupt_budget_ms"):
            value = getattr(assessment, name)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise ValueError(f"assessment {name} must be a non-negative integer when supplied")
        if assessment.feasible:
            _require_positive_id("assessment.target_agent_id", assessment.target_agent_id)
            _require_positive_id("assessment.our_skill_id", assessment.our_skill_id)
            _require_positive_id("assessment.enemy_skill_id", assessment.enemy_skill_id)
            remaining = assessment.enemy_remaining_ms
            budget = assessment.interrupt_budget_ms
            if (
                not isinstance(remaining, int)
                or isinstance(remaining, bool)
                or not isinstance(budget, int)
                or isinstance(budget, bool)
                or remaining < budget
            ):
                raise ValueError("feasible assessment must contain a consistent remaining-time budget")
            if assessment.strict and (
                onset.name != "CONFIRMED"
                or assessment.observation_identity is None
                or assessment.observation_age_ms is None
                or assessment.observation_stale
                or assessment.observation_untrusted
                or assessment.timing_invalid
                or not assessment.geometry_available
            ):
                raise ValueError("strict feasible assessment contradicts its observation or geometry evidence")
        elif reason.name == "INSUFFICIENT_TIME":
            remaining = assessment.enemy_remaining_ms
            budget = assessment.interrupt_budget_ms
            if remaining is None or budget is None or remaining >= budget:
                raise ValueError("insufficient-time assessment contradicts its remaining-time budget")
        elif reason.name == "CAST_FINISHED" and assessment.enemy_remaining_ms not in (None, 0):
            raise ValueError("finished-cast assessment contradicts its remaining time")

        projected = object.__new__(cls)
        object.__setattr__(projected, "assessment", assessment)
        return projected

    @property
    def target_agent_id(self) -> int:
        return self.assessment.target_agent_id

    @property
    def our_skill_id(self) -> int:
        return self.assessment.our_skill_id

    @property
    def enemy_skill_id(self) -> int:
        return self.assessment.enemy_skill_id

    @property
    def mechanically_feasible(self) -> bool:
        return self.assessment.feasible

    @property
    def strict(self) -> bool:
        return self.assessment.strict

    @property
    def reason(self) -> InterruptAssessmentReason:
        return self.assessment.reason

    @property
    def onset_confidence(self) -> ObservationOnsetConfidence:
        return self.assessment.onset_confidence

    @property
    def observation_identity(self) -> tuple[int, int, int] | None:
        return self.assessment.observation_identity

    @property
    def observation_age_ms(self) -> int | None:
        return self.assessment.observation_age_ms

    @property
    def enemy_remaining_ms(self) -> int | None:
        return self.assessment.enemy_remaining_ms

    @property
    def interrupt_budget_ms(self) -> int | None:
        return self.assessment.interrupt_budget_ms

    @property
    def cast_key(self) -> CryCastKey:
        return CryCastKey(self.target_agent_id, self.enemy_skill_id, self.observation_identity)


@dataclass(frozen=True, slots=True, init=False)
class ComplicateDisableDurationEvidence:
    """Resolved rank and duration from Complicate's checked-in progression."""

    skill_id: int
    attribute: str
    field: str
    attribute_rank: int
    duration_seconds: int
    source: str

    def __init__(self) -> None:
        raise TypeError("use from_skill_progression() to create duration evidence")

    @classmethod
    def from_skill_progression(
        cls,
        skill_id: int,
        attribute_rank: int | None,
        progression_data: Iterable[tuple[str, str, Mapping[int, float]]],
    ) -> ComplicateDisableDurationEvidence | None:
        """Resolve one Complicate rank from ``Skill.GetProgressionData`` output.

        ``None`` means rank or source metadata is unavailable. A present but
        invalid duration is rejected; it must not masquerade as unresolved.
        """

        _require_positive_id("skill_id", skill_id)
        if skill_id != COMPLICATE_SKILL_ID:
            raise ValueError("duration evidence must come from Complicate skill 932")
        if attribute_rank is None:
            return None
        if not isinstance(attribute_rank, int) or isinstance(attribute_rank, bool) or not 0 <= attribute_rank <= 21:
            raise ValueError("Domination Magic rank must be in the source progression domain 0..21")

        matches: list[Mapping[int, float]] = []
        for progression in progression_data:
            if not isinstance(progression, tuple) or len(progression) != 3:
                raise ValueError("progression data must contain (attribute, field, values) tuples")
            attribute, field, values = progression
            if not isinstance(attribute, str) or not isinstance(field, str) or not isinstance(values, Mapping):
                raise ValueError("progression data has an invalid source shape")
            if attribute == "Domination Magic" and field == "Duration":
                matches.append(values)
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("Complicate metadata must contain one Domination Magic Duration progression")
        raw_duration = matches[0].get(attribute_rank)
        if raw_duration is None:
            return None
        if isinstance(raw_duration, bool) or not isinstance(raw_duration, (int, float)):
            raise ValueError("Complicate duration must be a finite whole number of seconds")
        try:
            duration = float(raw_duration)
        except (OverflowError, TypeError, ValueError) as error:
            raise ValueError("Complicate duration must be a finite whole number of seconds") from error
        if not math.isfinite(duration) or duration < 5.0 or duration > 15.0 or not duration.is_integer():
            raise ValueError("Complicate duration is outside its source-backed 5..15 second domain")

        evidence = object.__new__(cls)
        object.__setattr__(evidence, "skill_id", COMPLICATE_SKILL_ID)
        object.__setattr__(evidence, "attribute", "Domination Magic")
        object.__setattr__(evidence, "field", "Duration")
        object.__setattr__(evidence, "attribute_rank", attribute_rank)
        object.__setattr__(evidence, "duration_seconds", int(duration))
        object.__setattr__(evidence, "source", "Py4GWCoreLib/skill_descriptions.json:932.progression")
        return evidence


@dataclass(frozen=True, slots=True)
class ComplicateObservedCast:
    """One directly observed foe cast inside Complicate's affected area."""

    agent_id: int
    current_skill_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, int) or isinstance(self.agent_id, bool) or self.agent_id <= 0:
            raise ValueError("agent_id must be a positive integer")
        if (
            not isinstance(self.current_skill_id, int)
            or isinstance(self.current_skill_id, bool)
            or self.current_skill_id <= 0
        ):
            raise ValueError("current_skill_id must be a positive integer")


@dataclass(frozen=True, slots=True)
class ComplicateCandidateObservation:
    """Immutable facts for one proposed primary enemy target.

    The runtime adapter supplies an already validated enemy target and a
    mechanical assessment made for Complicate. ``affected_area_casts`` is an
    adapter precondition: entries must be hostile foes whose current, validated
    geometry places them inside the skill's area. Policy sees only AgentID and
    exact current skill ID; it does not infer hostility or geometry, and
    profession, attribute, skill type, and unobserved skillbar data are not
    policy inputs.
    """

    primary_agent_id: int
    primary_enemy_skill_id: int | None
    mechanical_assessment: ComplicateInterruptEvidence | None
    primary_value: ComplicateCastValue | None
    affected_area_casts: tuple[ComplicateObservedCast, ...] = ()
    disable_duration: ComplicateDisableDurationEvidence | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.primary_agent_id, int)
            or isinstance(self.primary_agent_id, bool)
            or self.primary_agent_id <= 0
        ):
            raise ValueError("primary_agent_id must be a positive integer")
        if self.primary_enemy_skill_id is not None and (
            not isinstance(self.primary_enemy_skill_id, int)
            or isinstance(self.primary_enemy_skill_id, bool)
            or self.primary_enemy_skill_id <= 0
        ):
            raise ValueError("primary_enemy_skill_id must be a positive integer when supplied")
        if self.mechanical_assessment is not None and not isinstance(
            self.mechanical_assessment, ComplicateInterruptEvidence
        ):
            raise ValueError("mechanical_assessment must be ComplicateInterruptEvidence when supplied")
        if self.primary_value is not None and not isinstance(self.primary_value, ComplicateCastValue):
            raise ValueError("primary_value must be ComplicateCastValue when supplied")
        if self.disable_duration is not None and not isinstance(
            self.disable_duration, ComplicateDisableDurationEvidence
        ):
            raise ValueError("disable_duration must be source-backed ComplicateDisableDurationEvidence")

        affected_area_casts = tuple(self.affected_area_casts)
        if any(not isinstance(cast, ComplicateObservedCast) for cast in affected_area_casts):
            raise ValueError("affected_area_casts must contain ComplicateObservedCast values")
        affected_agent_ids = tuple(cast.agent_id for cast in affected_area_casts)
        if len(affected_agent_ids) != len(set(affected_agent_ids)):
            raise ValueError("affected_area_casts cannot contain duplicate agent IDs")
        object.__setattr__(
            self,
            "affected_area_casts",
            tuple(sorted(affected_area_casts, key=lambda cast: cast.agent_id)),
        )

    @property
    def disable_duration_seconds(self) -> int | None:
        return None if self.disable_duration is None else self.disable_duration.duration_seconds


@dataclass(frozen=True, slots=True)
class SmartComplicateProposal:
    """Immutable admission contract for a later runtime validator."""

    primary_agent_id: int
    interrupted_skill_id: int
    primary_cast_key: CryCastKey
    mechanical_assessment: ComplicateInterruptEvidence
    primary_value: ComplicateCastValue
    observed_same_skill_area_agent_ids: tuple[int, ...]
    disable_duration: ComplicateDisableDurationEvidence | None = None

    def __post_init__(self) -> None:
        _require_positive_id("primary_agent_id", self.primary_agent_id)
        _require_positive_id("interrupted_skill_id", self.interrupted_skill_id)
        if not isinstance(self.primary_cast_key, CryCastKey):
            raise ValueError("primary_cast_key must be CryCastKey")
        if not isinstance(self.mechanical_assessment, ComplicateInterruptEvidence):
            raise ValueError("mechanical_assessment must be ComplicateInterruptEvidence")
        if not isinstance(self.primary_value, ComplicateCastValue):
            raise ValueError("primary_value must be ComplicateCastValue")
        if self.disable_duration is not None and not isinstance(
            self.disable_duration, ComplicateDisableDurationEvidence
        ):
            raise ValueError("disable_duration must be source-backed ComplicateDisableDurationEvidence")
        if (
            self.primary_cast_key.enemy_agent_id != self.primary_agent_id
            or self.primary_cast_key.enemy_skill_id != self.interrupted_skill_id
        ):
            raise ValueError("primary_cast_key must match the primary identity")
        if self.primary_cast_key != self.mechanical_assessment.cast_key:
            raise ValueError("primary_cast_key must preserve the assessment observation identity")
        if (
            self.mechanical_assessment.target_agent_id != self.primary_agent_id
            or self.mechanical_assessment.enemy_skill_id != self.interrupted_skill_id
        ):
            raise ValueError("mechanical_assessment must match the primary identity")
        if self.mechanical_assessment.our_skill_id != COMPLICATE_SKILL_ID:
            raise ValueError("mechanical_assessment must assess Complicate")
        if not self.mechanical_assessment.mechanically_feasible or self.mechanical_assessment.reason.name != "FEASIBLE":
            raise ValueError("a proposal requires a feasible HeroAI assessment")
        if not self.mechanical_assessment.strict or self.mechanical_assessment.onset_confidence.name != "CONFIRMED":
            raise ValueError("a proposal requires strict, confirmed-onset HeroAI evidence")
        if (
            self.mechanical_assessment.observation_identity is None
            or self.mechanical_assessment.observation_age_ms is None
            or self.mechanical_assessment.enemy_remaining_ms is None
            or self.mechanical_assessment.interrupt_budget_ms is None
            or self.mechanical_assessment.enemy_remaining_ms < self.mechanical_assessment.interrupt_budget_ms
        ):
            raise ValueError("a proposal requires complete feasible timing evidence")
        same_skill_agent_ids = tuple(self.observed_same_skill_area_agent_ids)
        if any(
            not isinstance(agent_id, int) or isinstance(agent_id, bool) or agent_id <= 0
            for agent_id in same_skill_agent_ids
        ):
            raise ValueError("observed same-skill agent IDs must be positive integers")
        if self.primary_agent_id in same_skill_agent_ids:
            raise ValueError("observed_same_skill_area_agent_ids must exclude the primary")
        if len(same_skill_agent_ids) != len(set(same_skill_agent_ids)):
            raise ValueError("observed_same_skill_area_agent_ids cannot contain duplicates")
        object.__setattr__(self, "observed_same_skill_area_agent_ids", tuple(sorted(same_skill_agent_ids)))

    @property
    def complicate_skill_id(self) -> int:
        return COMPLICATE_SKILL_ID

    @property
    def primary_cast_value(self) -> int:
        return self.primary_value.value

    @property
    def primary_value_source(self) -> str:
        return self.primary_value.source

    @property
    def disable_duration_seconds(self) -> int | None:
        return None if self.disable_duration is None else self.disable_duration.duration_seconds


@dataclass(frozen=True, slots=True)
class ComplicateCandidateEvaluation:
    """Immutable admission result and exact-skill area observations."""

    primary_agent_id: int
    primary_enemy_skill_id: int | None
    primary_cast_key: CryCastKey | None
    primary_value: ComplicateCastValue | None
    observed_same_skill_area_agent_ids: tuple[int, ...]
    eligible: bool
    reason: ComplicateCandidateReason
    proposal: SmartComplicateProposal | None

    @property
    def primary_cast_value(self) -> int | None:
        return None if self.primary_value is None else self.primary_value.value

    @property
    def primary_value_source(self) -> str | None:
        return None if self.primary_value is None else self.primary_value.source


@dataclass(frozen=True, slots=True)
class ComplicateDecision:
    """Pure deterministic policy result; it performs no action."""

    selected: SmartComplicateProposal | None
    reason: ComplicateDecisionReason
    candidates: tuple[ComplicateCandidateEvaluation, ...]

    @property
    def admitted(self) -> bool:
        return self.selected is not None

    @property
    def ranked_candidates(self) -> tuple[ComplicateCandidateEvaluation, ...]:
        return self.candidates


def _normalise_cast_key(value: HandledCastKey) -> CryCastKey:
    if isinstance(value, CryCastKey):
        return value
    if len(value) == 2:
        return CryCastKey(int(value[0]), int(value[1]))
    if len(value) == 3:
        return CryCastKey(int(value[0]), int(value[1]), value[2])
    raise ValueError("handled cast keys must contain two or three values")


def _is_handled(cast_key: CryCastKey, handled: frozenset[CryCastKey]) -> bool:
    return cast_key in handled or (
        cast_key.observation_identity is not None
        and CryCastKey(cast_key.enemy_agent_id, cast_key.enemy_skill_id) in handled
    )


def _candidate_sort_key(
    candidate: ComplicateCandidateEvaluation,
) -> tuple[int, int, int, int]:
    value = -1 if candidate.primary_cast_value is None else candidate.primary_cast_value
    return (
        0 if candidate.eligible else 1,
        -value,
        -len(candidate.observed_same_skill_area_agent_ids),
        candidate.primary_agent_id,
    )


def _evaluate_candidate(
    observation: ComplicateCandidateObservation,
    handled: frozenset[CryCastKey],
) -> ComplicateCandidateEvaluation:
    skill_id = observation.primary_enemy_skill_id
    evidence = observation.mechanical_assessment
    cast_key: CryCastKey | None = None
    if skill_id is not None:
        observation_identity = None
        if (
            evidence is not None
            and evidence.target_agent_id == observation.primary_agent_id
            and evidence.enemy_skill_id == skill_id
        ):
            observation_identity = evidence.observation_identity
        cast_key = CryCastKey(observation.primary_agent_id, skill_id, observation_identity)

    same_skill_agent_ids = ()
    if skill_id is not None:
        same_skill_agent_ids = tuple(
            cast.agent_id
            for cast in observation.affected_area_casts
            if cast.agent_id != observation.primary_agent_id and cast.current_skill_id == skill_id
        )

    if skill_id is None:
        reason = ComplicateCandidateReason.PRIMARY_SKILL_UNAVAILABLE
    elif cast_key is not None and _is_handled(cast_key, handled):
        reason = ComplicateCandidateReason.PRIMARY_CAST_HANDLED
    elif evidence is None:
        reason = ComplicateCandidateReason.MECHANICAL_ASSESSMENT_UNAVAILABLE
    elif evidence.target_agent_id != observation.primary_agent_id or evidence.enemy_skill_id != skill_id:
        reason = ComplicateCandidateReason.ASSESSMENT_MISMATCH
    elif evidence.our_skill_id != COMPLICATE_SKILL_ID:
        reason = ComplicateCandidateReason.ASSESSMENT_SKILL_MISMATCH
    elif not evidence.mechanically_feasible or evidence.reason.name != "FEASIBLE":
        reason = ComplicateCandidateReason.MECHANICALLY_INFEASIBLE
    elif not evidence.strict or evidence.onset_confidence.name != "CONFIRMED":
        reason = ComplicateCandidateReason.TIMING_UNTRUSTED
    elif (
        evidence.observation_identity is None
        or evidence.observation_age_ms is None
        or evidence.enemy_remaining_ms is None
        or evidence.interrupt_budget_ms is None
        or evidence.enemy_remaining_ms < evidence.interrupt_budget_ms
    ):
        reason = ComplicateCandidateReason.MECHANICAL_RESULT_INCOMPLETE
    elif observation.primary_value is None:
        reason = ComplicateCandidateReason.PRIMARY_VALUE_UNAVAILABLE
    else:
        reason = ComplicateCandidateReason.ELIGIBLE

    proposal = None
    if reason is ComplicateCandidateReason.ELIGIBLE:
        assert skill_id is not None
        assert cast_key is not None
        assert evidence is not None
        assert observation.primary_value is not None
        proposal = SmartComplicateProposal(
            primary_agent_id=observation.primary_agent_id,
            interrupted_skill_id=skill_id,
            primary_cast_key=cast_key,
            mechanical_assessment=evidence,
            primary_value=observation.primary_value,
            observed_same_skill_area_agent_ids=same_skill_agent_ids,
            disable_duration=observation.disable_duration,
        )

    return ComplicateCandidateEvaluation(
        primary_agent_id=observation.primary_agent_id,
        primary_enemy_skill_id=skill_id,
        primary_cast_key=cast_key,
        primary_value=observation.primary_value,
        observed_same_skill_area_agent_ids=same_skill_agent_ids,
        eligible=proposal is not None,
        reason=reason,
        proposal=proposal,
    )


def evaluate_smart_complicate(
    candidates: Iterable[ComplicateCandidateObservation],
    *,
    handled_cast_keys: Iterable[HandledCastKey] = (),
) -> ComplicateDecision:
    """Admit and rank source-backed candidates without runtime dependencies."""

    observations = tuple(candidates)
    agent_ids = tuple(observation.primary_agent_id for observation in observations)
    if len(agent_ids) != len(set(agent_ids)):
        raise ValueError("Complicate candidates cannot contain duplicate primary agent IDs")
    observations = tuple(sorted(observations, key=lambda item: item.primary_agent_id))
    handled = frozenset(_normalise_cast_key(value) for value in handled_cast_keys)
    evaluations = tuple(
        sorted(
            (_evaluate_candidate(observation, handled) for observation in observations),
            key=_candidate_sort_key,
        )
    )
    selected = next((item.proposal for item in evaluations if item.proposal is not None), None)
    return ComplicateDecision(
        selected=selected,
        reason=(
            ComplicateDecisionReason.SELECTED
            if selected is not None
            else ComplicateDecisionReason.NO_ELIGIBLE_CANDIDATE
        ),
        candidates=evaluations,
    )


__all__ = [
    "COMPLICATE_SKILL_ID",
    "ComplicateCandidateEvaluation",
    "ComplicateCandidateObservation",
    "ComplicateCandidateReason",
    "ComplicateCastValue",
    "ComplicateDisableDurationEvidence",
    "ComplicateDecision",
    "ComplicateDecisionReason",
    "ComplicateInterruptEvidence",
    "ComplicateObservedCast",
    "HandledCastKey",
    "SmartComplicateProposal",
    "evaluate_smart_complicate",
]
