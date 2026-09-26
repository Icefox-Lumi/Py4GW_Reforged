"""Pure Energy Surge policy evaluation for the Checkpoint B build."""

from __future__ import annotations

import math
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final

from Py4GWCoreLib.Builds.Skills.SmartMesmer import CombatSnapshot
from Py4GWCoreLib.Builds.Skills.SmartMesmer import EnemyObservation
from Py4GWCoreLib.Builds.Skills.SmartMesmer import GroupIdentity
from Py4GWCoreLib.Builds.Skills.SmartMesmer import PairwiseDistances
from Py4GWCoreLib.Builds.Skills.SmartMesmer import build_combat_groups
from Py4GWCoreLib.Builds.Skills.SmartMesmer import pairwise_squared_distances

LOW_HP_THRESHOLD: Final[float] = 0.10
MINIMUM_EXPECTED_PACKET_DAMAGE: Final[float] = 90.0
MAXIMUM_FOREIGN_RESERVATIONS: Final[int] = 2
DAMAGE_PER_ENERGY: Final[float] = 9.0
UNKNOWN_MAX_ENERGY: Final[int] = 25

PROFESSION_MAX_ENERGY: Final[Mapping[str, int]] = MappingProxyType(
    {
        "Warrior": 20,
        "Ranger": 25,
        "Assassin": 25,
        "Dervish": 25,
        "Monk": 30,
        "Necromancer": 30,
        "Mesmer": 30,
        "Ritualist": 30,
        "Paragon": 30,
        "Elementalist": 50,
    }
)
_PROFESSION_MAX_ENERGY_BY_KEY: Final[Mapping[str, int]] = MappingProxyType(
    {profession.casefold(): maximum for profession, maximum in PROFESSION_MAX_ENERGY.items()}
)


class DecisionReason(str, Enum):
    SELECTED = "selected"
    INVALID_LOCAL_DRAIN = "invalid_local_drain"
    INVALID_AOE_RADIUS = "invalid_aoe_radius"
    INVALID_CAST_RANGE = "invalid_cast_range"
    INVALID_GROUP_LINK_RADIUS = "invalid_group_link_radius"
    NO_VIABLE_CANDIDATE = "no_viable_candidate"


class CandidateReason(str, Enum):
    ELIGIBLE = "eligible"
    LOW_HP_TARGET = "low_hp_target"
    OUT_OF_CAST_RANGE = "out_of_cast_range"
    RESERVATION_CAP_REACHED = "reservation_cap_reached"
    BELOW_MINIMUM_DAMAGE = "below_minimum_damage"


@dataclass(frozen=True, slots=True)
class EnergySurgePolicy:
    """Explicit V1 policy tunables; runtime timing belongs to Checkpoint C."""

    low_hp_threshold: float = LOW_HP_THRESHOLD
    minimum_expected_packet_damage: float = MINIMUM_EXPECTED_PACKET_DAMAGE
    maximum_foreign_reservations: int = MAXIMUM_FOREIGN_RESERVATIONS
    damage_per_energy: float = DAMAGE_PER_ENERGY

    def __post_init__(self) -> None:
        if not math.isfinite(self.low_hp_threshold) or not 0.0 <= self.low_hp_threshold <= 1.0:
            raise ValueError("low_hp_threshold must be finite and in [0, 1]")
        if not math.isfinite(self.minimum_expected_packet_damage) or self.minimum_expected_packet_damage < 0.0:
            raise ValueError("minimum_expected_packet_damage must be finite and non-negative")
        if not isinstance(self.maximum_foreign_reservations, int) or self.maximum_foreign_reservations <= 0:
            raise ValueError("maximum_foreign_reservations must be a positive integer")
        if not math.isfinite(self.damage_per_energy) or self.damage_per_energy <= 0.0:
            raise ValueError("damage_per_energy must be finite and positive")


DEFAULT_POLICY: Final[EnergySurgePolicy] = EnergySurgePolicy()


@dataclass(frozen=True, slots=True)
class EnergySurgeEnemyObservation:
    """Policy facts paired with one immutable SmartMesmer geometry observation."""

    observation: EnemyObservation
    profession: str
    health_fraction: float
    distance_from_player: float
    is_caster: bool
    is_casting: bool

    def __post_init__(self) -> None:
        if not isinstance(self.profession, str):
            raise TypeError("profession must be a string name")
        if not math.isfinite(self.health_fraction) or not 0.0 <= self.health_fraction <= 1.0:
            raise ValueError("health_fraction must be finite and in [0, 1]")
        if not math.isfinite(self.distance_from_player) or self.distance_from_player < 0.0:
            raise ValueError("distance_from_player must be finite and non-negative")

    @property
    def agent_id(self) -> int:
        return self.observation.agent_id


@dataclass(frozen=True, slots=True)
class ForeignReservationProjection:
    """One immutable foreign reservation's explicit target drain projection."""

    target_agent_id: int
    projected_drain: float

    def __post_init__(self) -> None:
        if not isinstance(self.target_agent_id, int):
            raise TypeError("target_agent_id must be an int")
        if not math.isfinite(self.projected_drain) or self.projected_drain < 0.0:
            raise ValueError("projected_drain must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class EnergySurgeCandidateEvaluation:
    """Pure diagnostics and eligibility result for one possible cast target."""

    target_agent_id: int
    group_identity: GroupIdentity
    eligible: bool
    reason: CandidateReason
    raw_affected_count: int
    valuable_affected_count: int
    inferred_max_energy: int
    foreign_reservation_count: int
    foreign_projected_drain: float
    projected_energy: float
    effective_drain: float
    expected_packet_damage: float
    target_health_fraction: float
    is_caster: bool
    is_casting: bool
    distance_from_player: float


@dataclass(frozen=True, slots=True)
class EnergySurgeGroupEvaluation:
    """Small group-level value surface for later SmartMesmer focus integration."""

    group_identity: GroupIdentity
    viable: bool
    best_candidate: EnergySurgeCandidateEvaluation | None
    policy_value: float


@dataclass(frozen=True, slots=True)
class EnergySurgeDecision:
    """Immutable pure decision and diagnostic result; it performs no action."""

    selected: EnergySurgeCandidateEvaluation | None
    reason: DecisionReason
    candidates: tuple[EnergySurgeCandidateEvaluation, ...]
    groups: tuple[EnergySurgeGroupEvaluation, ...]

    @property
    def selected_target_agent_id(self) -> int | None:
        return None if self.selected is None else self.selected.target_agent_id


def infer_max_energy(profession: str) -> int:
    """Return the V1 inferred maximum Energy prior for a profession name."""

    return _PROFESSION_MAX_ENERGY_BY_KEY.get(profession.strip().casefold(), UNKNOWN_MAX_ENERGY)


def _is_finite_non_negative(value: float) -> bool:
    return math.isfinite(value) and value >= 0.0


def _empty_decision(reason: DecisionReason) -> EnergySurgeDecision:
    return EnergySurgeDecision(selected=None, reason=reason, candidates=(), groups=())


def _normalise_enemy_observations(
    snapshot: CombatSnapshot,
    enemies: Iterable[EnergySurgeEnemyObservation],
) -> tuple[EnergySurgeEnemyObservation, ...]:
    supplied = tuple(sorted(tuple(enemies), key=lambda enemy: enemy.agent_id))
    agent_ids = tuple(enemy.agent_id for enemy in supplied)
    if len(agent_ids) != len(set(agent_ids)):
        raise ValueError("policy observations cannot contain duplicate agent IDs")
    if agent_ids != snapshot.agent_ids:
        raise ValueError("policy observations must cover exactly the snapshot agent IDs")
    geometry_key = tuple((enemy.observation.agent_id, enemy.observation.x, enemy.observation.y) for enemy in supplied)
    if geometry_key != snapshot.geometry_key:
        raise ValueError("policy observations must use the snapshot geometry")
    return supplied


def _validate_pairwise_distances(
    snapshot: CombatSnapshot,
    distances: PairwiseDistances,
) -> None:
    if distances.agent_ids != snapshot.agent_ids or distances.geometry_key != snapshot.geometry_key:
        raise ValueError("pairwise distances must belong to this snapshot")


def _reservation_projection(
    reservations: Iterable[ForeignReservationProjection],
) -> tuple[dict[int, int], dict[int, float]]:
    counts: dict[int, int] = {}
    drains: dict[int, float] = {}
    for reservation in reservations:
        counts[reservation.target_agent_id] = counts.get(reservation.target_agent_id, 0) + 1
        drains[reservation.target_agent_id] = drains.get(reservation.target_agent_id, 0.0) + reservation.projected_drain
    return counts, drains


def _candidate_order_key(
    candidate: EnergySurgeCandidateEvaluation,
) -> tuple[int, float, int, float, int, int, float, float, int]:
    return (
        0 if candidate.eligible else 1,
        -candidate.expected_packet_damage,
        -candidate.valuable_affected_count,
        -candidate.effective_drain,
        0 if candidate.is_casting else 1,
        0 if candidate.is_caster else 1,
        -candidate.target_health_fraction,
        candidate.distance_from_player,
        candidate.target_agent_id,
    )


def evaluate_energy_surge(
    snapshot: CombatSnapshot,
    enemies: Iterable[EnergySurgeEnemyObservation],
    *,
    aoe_radius: float,
    cast_range: float,
    group_link_radius: float,
    local_resolved_drain: float | None,
    reservations: Iterable[ForeignReservationProjection] = (),
    policy: EnergySurgePolicy = DEFAULT_POLICY,
    pairwise_distances: PairwiseDistances | None = None,
) -> EnergySurgeDecision:
    """Evaluate one immutable snapshot without reading or mutating runtime state."""

    if local_resolved_drain is None or not math.isfinite(local_resolved_drain) or local_resolved_drain <= 0.0:
        return _empty_decision(DecisionReason.INVALID_LOCAL_DRAIN)
    if not _is_finite_non_negative(aoe_radius):
        return _empty_decision(DecisionReason.INVALID_AOE_RADIUS)
    if not _is_finite_non_negative(cast_range):
        return _empty_decision(DecisionReason.INVALID_CAST_RANGE)
    if not _is_finite_non_negative(group_link_radius):
        return _empty_decision(DecisionReason.INVALID_GROUP_LINK_RADIUS)

    observations = _normalise_enemy_observations(snapshot, enemies)
    distances = pairwise_distances or pairwise_squared_distances(snapshot)
    _validate_pairwise_distances(snapshot, distances)
    groups = build_combat_groups(snapshot, group_link_radius, distances=distances)
    group_by_agent_id = {member.agent_id: group for group in groups for member in group.members}
    index_by_agent_id = {agent_id: index for index, agent_id in enumerate(distances.agent_ids)}
    observation_by_agent_id = {enemy.agent_id: enemy for enemy in observations}
    reservation_counts, reservation_drains = _reservation_projection(reservations)
    aoe_radius_squared = aoe_radius * aoe_radius
    evaluations: list[EnergySurgeCandidateEvaluation] = []

    for candidate in observations:
        candidate_index = index_by_agent_id[candidate.agent_id]
        affected_agent_ids = tuple(
            agent_id
            for agent_id in snapshot.agent_ids
            if distances.matrix[candidate_index][index_by_agent_id[agent_id]] <= aoe_radius_squared
        )
        valuable_affected_count = sum(
            observation_by_agent_id[agent_id].health_fraction > policy.low_hp_threshold
            for agent_id in affected_agent_ids
        )
        reservation_count = reservation_counts.get(candidate.agent_id, 0)
        foreign_projected_drain = reservation_drains.get(candidate.agent_id, 0.0)
        inferred_energy = infer_max_energy(candidate.profession)
        projected_energy = max(0.0, inferred_energy - foreign_projected_drain)
        effective_drain = min(local_resolved_drain, projected_energy)
        expected_packet_damage = effective_drain * policy.damage_per_energy * valuable_affected_count

        if candidate.health_fraction <= policy.low_hp_threshold:
            reason = CandidateReason.LOW_HP_TARGET
        elif candidate.distance_from_player > cast_range:
            reason = CandidateReason.OUT_OF_CAST_RANGE
        elif reservation_count >= policy.maximum_foreign_reservations:
            reason = CandidateReason.RESERVATION_CAP_REACHED
        elif expected_packet_damage < policy.minimum_expected_packet_damage:
            reason = CandidateReason.BELOW_MINIMUM_DAMAGE
        else:
            reason = CandidateReason.ELIGIBLE

        evaluations.append(
            EnergySurgeCandidateEvaluation(
                target_agent_id=candidate.agent_id,
                group_identity=group_by_agent_id[candidate.agent_id].canonical_id,
                eligible=reason is CandidateReason.ELIGIBLE,
                reason=reason,
                raw_affected_count=len(affected_agent_ids),
                valuable_affected_count=valuable_affected_count,
                inferred_max_energy=inferred_energy,
                foreign_reservation_count=reservation_count,
                foreign_projected_drain=foreign_projected_drain,
                projected_energy=projected_energy,
                effective_drain=effective_drain,
                expected_packet_damage=expected_packet_damage,
                target_health_fraction=candidate.health_fraction,
                is_caster=candidate.is_caster,
                is_casting=candidate.is_casting,
                distance_from_player=candidate.distance_from_player,
            )
        )

    ordered_candidates = tuple(sorted(evaluations, key=_candidate_order_key))
    selected = next((candidate for candidate in ordered_candidates if candidate.eligible), None)
    group_evaluations = tuple(
        EnergySurgeGroupEvaluation(
            group_identity=group.canonical_id,
            viable=any(
                candidate.eligible and candidate.group_identity == group.canonical_id
                for candidate in ordered_candidates
            ),
            best_candidate=next(
                (
                    candidate
                    for candidate in ordered_candidates
                    if candidate.eligible and candidate.group_identity == group.canonical_id
                ),
                None,
            ),
            policy_value=next(
                (
                    candidate.expected_packet_damage
                    for candidate in ordered_candidates
                    if candidate.eligible and candidate.group_identity == group.canonical_id
                ),
                0.0,
            ),
        )
        for group in groups
    )
    return EnergySurgeDecision(
        selected=selected,
        reason=DecisionReason.SELECTED if selected is not None else DecisionReason.NO_VIABLE_CANDIDATE,
        candidates=ordered_candidates,
        groups=group_evaluations,
    )


__all__ = [
    "CandidateReason",
    "DAMAGE_PER_ENERGY",
    "DEFAULT_POLICY",
    "DecisionReason",
    "EnergySurgeCandidateEvaluation",
    "EnergySurgeDecision",
    "EnergySurgeEnemyObservation",
    "EnergySurgeGroupEvaluation",
    "EnergySurgePolicy",
    "ForeignReservationProjection",
    "LOW_HP_THRESHOLD",
    "MAXIMUM_FOREIGN_RESERVATIONS",
    "MINIMUM_EXPECTED_PACKET_DAMAGE",
    "PROFESSION_MAX_ENERGY",
    "UNKNOWN_MAX_ENERGY",
    "evaluate_energy_surge",
    "infer_max_energy",
]
