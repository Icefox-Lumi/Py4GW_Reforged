"""Pure PvE Spiritual Pain evidence, classification, and target-value policy."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final

SPIRITUAL_PAIN_SKILL_ID: Final[int] = 1336
SPIRITUAL_PAIN_CAST_RANGE: Final[float] = 1248.0
SPIRITUAL_PAIN_AREA_RADIUS: Final[float] = 322.0
SPIRITUAL_PAIN_AREA_RADIUS_SQUARED: Final[float] = 103684.0

NPC_MINION_FLAG: Final[int] = 0x0100
NPC_SPIRIT_FLAG: Final[int] = 0x4000
TYPE_MAP_SPIRIT_BIT: Final[int] = 0x040000

DOMINATION_RANK_MIN: Final[int] = 0
DOMINATION_RANK_MAX: Final[int] = 21
SPIRITUAL_PAIN_PRIMARY_DAMAGE_BY_RANK: Final[tuple[int, ...]] = (
    15,
    19,
    23,
    27,
    31,
    35,
    39,
    43,
    47,
    51,
    55,
    59,
    63,
    67,
    71,
    75,
    79,
    83,
    87,
    91,
    95,
    99,
)
SPIRITUAL_PAIN_SUMMON_DAMAGE_BY_RANK: Final[tuple[int, ...]] = (
    25,
    32,
    38,
    45,
    52,
    58,
    65,
    72,
    78,
    85,
    92,
    98,
    105,
    112,
    118,
    125,
    132,
    138,
    145,
    152,
    158,
    165,
)


class HostileSummonClassification(str, Enum):
    """The only two classifier outcomes permitted by the D3C-B contract."""

    CONFIRMED_HOSTILE_SUMMON = "confirmed_hostile_summon"
    NOT_CONFIRMED_HOSTILE_SUMMON = "not_confirmed_hostile_summon"


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


@dataclass(frozen=True, slots=True)
class SpiritualPainEvidence:
    """Small immutable factual evidence surface used by the summon classifier."""

    is_valid: bool | None = None
    is_living: bool | None = None
    is_alive: bool | None = None
    is_direct_enemy: bool | None = None
    npc_flags: int | None = None
    type_map: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("is_valid", self.is_valid),
            ("is_living", self.is_living),
            ("is_alive", self.is_alive),
            ("is_direct_enemy", self.is_direct_enemy),
        ):
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool or None")
        for name, value in (("npc_flags", self.npc_flags), ("type_map", self.type_map)):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(f"{name} must be an int or None")
                if value < 0:
                    raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class SpiritualPainTargetObservation:
    """Immutable policy facts for one possible primary or special victim."""

    agent_id: int
    x: float | None
    y: float | None
    current_hp: float | None
    distance_from_player: float | None
    evidence: SpiritualPainEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, int) or isinstance(self.agent_id, bool):
            raise TypeError("agent_id must be an integer")
        if not isinstance(self.evidence, SpiritualPainEvidence):
            raise TypeError("evidence must be SpiritualPainEvidence")
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("current_hp", self.current_hp),
            ("distance_from_player", self.distance_from_player),
        ):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError(f"{name} must be a finite number or None")
                finite = _finite_float(value)
                if finite is None:
                    raise ValueError(f"{name} must be finite when supplied")
                object.__setattr__(self, name, finite)

    @property
    def position(self) -> tuple[float, float] | None:
        if self.x is None or self.y is None:
            return None
        return float(self.x), float(self.y)

    @property
    def hostile_summon_classification(self) -> HostileSummonClassification:
        return classify_hostile_summon(self.evidence)


@dataclass(frozen=True, slots=True)
class SpiritualPainRankDamage:
    """Exact checked-in Spiritual Pain damage for one Domination rank."""

    attribute_rank: int
    primary_damage: int
    summon_damage: int


def resolve_spiritual_pain_damage(attribute_rank: int | None) -> SpiritualPainRankDamage | None:
    """Resolve one exact rank without clamping unsupported or missing input."""

    if (
        attribute_rank is None
        or isinstance(attribute_rank, bool)
        or not isinstance(attribute_rank, int)
        or not DOMINATION_RANK_MIN <= attribute_rank <= DOMINATION_RANK_MAX
    ):
        return None
    return SpiritualPainRankDamage(
        attribute_rank=attribute_rank,
        primary_damage=SPIRITUAL_PAIN_PRIMARY_DAMAGE_BY_RANK[attribute_rank],
        summon_damage=SPIRITUAL_PAIN_SUMMON_DAMAGE_BY_RANK[attribute_rank],
    )


@dataclass(frozen=True, slots=True)
class SpiritualPainPolicy:
    """Rank-resolved damage and fixed PvE geometry for one pure evaluation."""

    primary_damage: float
    summon_damage: float
    cast_range: float = SPIRITUAL_PAIN_CAST_RANGE
    area_radius: float = SPIRITUAL_PAIN_AREA_RADIUS

    @classmethod
    def from_domination_rank(cls, attribute_rank: int | None) -> SpiritualPainPolicy | None:
        resolved = resolve_spiritual_pain_damage(attribute_rank)
        if resolved is None:
            return None
        return cls(
            primary_damage=resolved.primary_damage,
            summon_damage=resolved.summon_damage,
        )

    @classmethod
    def from_rank(cls, attribute_rank: int | None) -> SpiritualPainPolicy | None:
        return cls.from_domination_rank(attribute_rank)


@dataclass(frozen=True, slots=True)
class SpiritualPainCandidateEvaluation:
    """Immutable admission and useful-value result for one primary candidate."""

    target_agent_id: int
    eligible: bool
    reason: CandidateReason
    primary_summon_classification: HostileSummonClassification
    useful_primary_damage: float
    useful_special_summon_damage: float
    useful_total_damage: float
    special_summon_agent_ids: tuple[int, ...]
    distance_from_player: float | None

    @property
    def primary_agent_id(self) -> int:
        return self.target_agent_id

    @property
    def special_summon_count(self) -> int:
        return len(self.special_summon_agent_ids)

    @property
    def summon_hit_count(self) -> int:
        return self.special_summon_count

    @property
    def useful_damage(self) -> float:
        return self.useful_total_damage

    @property
    def total_value(self) -> float:
        return self.useful_total_damage


@dataclass(frozen=True, slots=True)
class SpiritualPainDecision:
    """Pure target-selection result; it performs no runtime or native action."""

    selected: SpiritualPainCandidateEvaluation | None
    reason: DecisionReason
    candidates: tuple[SpiritualPainCandidateEvaluation, ...]

    @property
    def admitted(self) -> bool:
        return self.selected is not None

    @property
    def selected_target_agent_id(self) -> int | None:
        return None if self.selected is None else self.selected.target_agent_id

    @property
    def ranked_candidates(self) -> tuple[SpiritualPainCandidateEvaluation, ...]:
        return self.candidates


def classify_hostile_summon(evidence: SpiritualPainEvidence) -> HostileSummonClassification:
    """Classify only directly evidenced hostile minions and spirits."""

    if not isinstance(evidence, SpiritualPainEvidence):
        return HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    if any(
        value is not True
        for value in (
            evidence.is_valid,
            evidence.is_living,
            evidence.is_alive,
            evidence.is_direct_enemy,
        )
    ):
        return HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    if evidence.npc_flags is None:
        return HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    if evidence.npc_flags & NPC_MINION_FLAG:
        return HostileSummonClassification.CONFIRMED_HOSTILE_SUMMON
    if evidence.npc_flags & NPC_SPIRIT_FLAG:
        if evidence.type_map is not None and evidence.type_map & TYPE_MAP_SPIRIT_BIT:
            return HostileSummonClassification.CONFIRMED_HOSTILE_SUMMON
    return HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON


def useful_damage(raw_damage: float | None, current_hp: float | None) -> float:
    """Return damage useful against current HP, failing closed for bad inputs."""

    if isinstance(raw_damage, bool) or isinstance(current_hp, bool):
        return 0.0
    try:
        damage = float(raw_damage) if raw_damage is not None else math.nan
        hp = float(current_hp) if current_hp is not None else math.nan
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(damage) or not math.isfinite(hp) or damage <= 0.0 or hp <= 0.0:
        return 0.0
    return min(damage, hp)


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return converted if math.isfinite(converted) else None


def _valid_policy(policy: SpiritualPainPolicy) -> bool:
    return all(
        value is not None and value > 0.0
        for value in (
            _finite_float(policy.primary_damage),
            _finite_float(policy.summon_damage),
            _finite_float(policy.cast_range),
            _finite_float(policy.area_radius),
        )
    )


def _invalid_decision(reason: DecisionReason) -> SpiritualPainDecision:
    return SpiritualPainDecision(selected=None, reason=reason, candidates=())


def _candidate_result(
    observation: SpiritualPainTargetObservation,
    *,
    reason: CandidateReason,
) -> SpiritualPainCandidateEvaluation:
    return SpiritualPainCandidateEvaluation(
        target_agent_id=observation.agent_id,
        eligible=False,
        reason=reason,
        primary_summon_classification=observation.hostile_summon_classification,
        useful_primary_damage=0.0,
        useful_special_summon_damage=0.0,
        useful_total_damage=0.0,
        special_summon_agent_ids=(),
        distance_from_player=observation.distance_from_player,
    )


def _primary_reason(
    observation: SpiritualPainTargetObservation,
    policy: SpiritualPainPolicy,
) -> CandidateReason:
    if observation.agent_id <= 0 or any(
        value is False
        for value in (
            observation.evidence.is_valid,
            observation.evidence.is_living,
            observation.evidence.is_alive,
            observation.evidence.is_direct_enemy,
        )
    ):
        return CandidateReason.INVALID_TARGET
    if any(
        value is None
        for value in (
            observation.x,
            observation.y,
            observation.current_hp,
            observation.distance_from_player,
            observation.evidence.is_valid,
            observation.evidence.is_living,
            observation.evidence.is_alive,
            observation.evidence.is_direct_enemy,
        )
    ):
        return CandidateReason.MISSING_EVIDENCE
    assert observation.current_hp is not None
    assert observation.distance_from_player is not None
    if observation.current_hp <= 0.0 or observation.distance_from_player < 0.0:
        return CandidateReason.INVALID_TARGET
    if observation.distance_from_player > policy.cast_range:
        return CandidateReason.OUT_OF_CAST_RANGE
    return CandidateReason.ELIGIBLE


def _special_summon_is_eligible(
    observation: SpiritualPainTargetObservation,
    primary: SpiritualPainTargetObservation,
    *,
    area_radius_squared: float,
) -> bool:
    if observation.agent_id <= 0 or observation.agent_id == primary.agent_id:
        return False
    if observation.hostile_summon_classification is not HostileSummonClassification.CONFIRMED_HOSTILE_SUMMON:
        return False
    if (
        observation.x is None
        or observation.y is None
        or observation.current_hp is None
        or observation.current_hp <= 0.0
        or primary.x is None
        or primary.y is None
    ):
        return False
    delta_x = float(observation.x) - float(primary.x)
    delta_y = float(observation.y) - float(primary.y)
    return delta_x * delta_x + delta_y * delta_y <= area_radius_squared


def _candidate_sort_key(
    candidate: SpiritualPainCandidateEvaluation,
) -> tuple[int, float, int, float, int]:
    distance = math.inf if candidate.distance_from_player is None else float(candidate.distance_from_player)
    return (
        0 if candidate.eligible else 1,
        -candidate.useful_total_damage,
        -candidate.special_summon_count,
        distance,
        candidate.target_agent_id,
    )


def evaluate_smart_spiritual_pain(
    candidates: Iterable[SpiritualPainTargetObservation],
    *,
    policy: SpiritualPainPolicy | None = None,
    primary_damage: float | None = None,
    summon_damage: float | None = None,
    cast_range: float = SPIRITUAL_PAIN_CAST_RANGE,
    area_radius: float = SPIRITUAL_PAIN_AREA_RADIUS,
) -> SpiritualPainDecision:
    """Select the highest useful PvE Spiritual Pain target deterministically."""

    if policy is None:
        if primary_damage is None or summon_damage is None:
            return _invalid_decision(DecisionReason.INVALID_POLICY)
        try:
            policy = SpiritualPainPolicy(
                primary_damage=primary_damage,
                summon_damage=summon_damage,
                cast_range=cast_range,
                area_radius=area_radius,
            )
        except (TypeError, ValueError, OverflowError):
            return _invalid_decision(DecisionReason.INVALID_POLICY)
    if not isinstance(policy, SpiritualPainPolicy) or not _valid_policy(policy):
        return _invalid_decision(DecisionReason.INVALID_POLICY)

    try:
        observations = tuple(candidates)
    except Exception:
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    if any(not isinstance(observation, SpiritualPainTargetObservation) for observation in observations):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    agent_ids = tuple(observation.agent_id for observation in observations)
    if len(agent_ids) != len(set(agent_ids)):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)

    observations = tuple(sorted(observations, key=lambda observation: observation.agent_id))
    area_radius_squared = float(policy.area_radius) * float(policy.area_radius)
    evaluations: list[SpiritualPainCandidateEvaluation] = []

    for observation in observations:
        reason = _primary_reason(observation, policy)
        if reason is not CandidateReason.ELIGIBLE:
            evaluations.append(_candidate_result(observation, reason=reason))
            continue

        assert observation.current_hp is not None
        assert observation.distance_from_player is not None
        primary_summon_classification = observation.hostile_summon_classification
        primary_damage = policy.primary_damage
        if primary_summon_classification is HostileSummonClassification.CONFIRMED_HOSTILE_SUMMON:
            primary_damage += policy.summon_damage
        primary_value = useful_damage(primary_damage, observation.current_hp)
        special_agent_ids = tuple(
            candidate.agent_id
            for candidate in observations
            if _special_summon_is_eligible(
                candidate,
                observation,
                area_radius_squared=area_radius_squared,
            )
        )
        special_value = sum(
            useful_damage(policy.summon_damage, candidate.current_hp)
            for candidate in observations
            if candidate.agent_id in special_agent_ids
        )
        evaluations.append(
            SpiritualPainCandidateEvaluation(
                target_agent_id=observation.agent_id,
                eligible=True,
                reason=CandidateReason.ELIGIBLE,
                primary_summon_classification=primary_summon_classification,
                useful_primary_damage=primary_value,
                useful_special_summon_damage=special_value,
                useful_total_damage=primary_value + special_value,
                special_summon_agent_ids=special_agent_ids,
                distance_from_player=observation.distance_from_player,
            )
        )

    ranked = tuple(sorted(evaluations, key=_candidate_sort_key))
    selected = next((candidate for candidate in ranked if candidate.eligible), None)
    return SpiritualPainDecision(
        selected=selected,
        reason=DecisionReason.SELECTED if selected is not None else DecisionReason.NO_ELIGIBLE_CANDIDATE,
        candidates=ranked,
    )


evaluate_spiritual_pain = evaluate_smart_spiritual_pain
classify_summon = classify_hostile_summon
resolve_spiritual_pain_rank = resolve_spiritual_pain_damage
SpiritualPainAgentObservation = SpiritualPainTargetObservation


__all__ = [
    "CandidateReason",
    "DecisionReason",
    "DOMINATION_RANK_MAX",
    "DOMINATION_RANK_MIN",
    "HostileSummonClassification",
    "NPC_MINION_FLAG",
    "NPC_SPIRIT_FLAG",
    "SPIRITUAL_PAIN_AREA_RADIUS",
    "SPIRITUAL_PAIN_AREA_RADIUS_SQUARED",
    "SPIRITUAL_PAIN_CAST_RANGE",
    "SPIRITUAL_PAIN_PRIMARY_DAMAGE_BY_RANK",
    "SPIRITUAL_PAIN_SKILL_ID",
    "SPIRITUAL_PAIN_SUMMON_DAMAGE_BY_RANK",
    "SpiritualPainAgentObservation",
    "SpiritualPainCandidateEvaluation",
    "SpiritualPainDecision",
    "SpiritualPainEvidence",
    "SpiritualPainPolicy",
    "SpiritualPainRankDamage",
    "SpiritualPainTargetObservation",
    "TYPE_MAP_SPIRIT_BIT",
    "classify_hostile_summon",
    "classify_summon",
    "evaluate_smart_spiritual_pain",
    "evaluate_spiritual_pain",
    "resolve_spiritual_pain_damage",
    "resolve_spiritual_pain_rank",
    "useful_damage",
]
