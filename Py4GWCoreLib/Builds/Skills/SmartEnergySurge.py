"""Composable Smart Energy Surge policy and handler."""

from __future__ import annotations

import math
from collections.abc import Generator
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any
from typing import Final
from typing import cast

from Py4GWCoreLib.BuildMgr import BuildMgr
from Py4GWCoreLib.Builds.Skills.SmartMesmer import CombatSnapshot
from Py4GWCoreLib.Builds.Skills.SmartMesmer import EnemyObservation
from Py4GWCoreLib.Builds.Skills.SmartMesmer import FocusCandidate
from Py4GWCoreLib.Builds.Skills.SmartMesmer import FocusState
from Py4GWCoreLib.Builds.Skills.SmartMesmer import FocusTransitionParameters
from Py4GWCoreLib.Builds.Skills.SmartMesmer import GroupIdentity
from Py4GWCoreLib.Builds.Skills.SmartMesmer import PairwiseDistances
from Py4GWCoreLib.Builds.Skills.SmartMesmer import build_combat_groups
from Py4GWCoreLib.Builds.Skills.SmartMesmer import pairwise_squared_distances
from Py4GWCoreLib.Builds.Skills.SmartMesmer import transition_focus

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


MATCH_SCORE_BONUS: Final[int] = 1000
DECISION_INTERVAL_MS: Final[int] = 100
FOCUS_MINIMUM_OVERLAP_RATIO: Final[float] = 0.50
FOCUS_GAP_GRACE_MS: Final[int] = 250
FOCUS_CHALLENGER_STABILITY_MS: Final[int] = 300
FOCUS_SWITCH_VALUE_RATIO: Final[float] = 1.25
CAST_SAFETY_MARGIN_MS: Final[int] = 100
RECENT_DRAIN_PROJECTION_HOLD_MS: Final[int] = 1000
ENERGY_SURGE_SKILL_NAME: Final[str] = "Energy_Surge"
Energy_Surge_ID: int = 0


def get_energy_surge_id() -> int:
    """Resolve Energy Surge lazily so policy-only imports stay offline-safe."""

    global Energy_Surge_ID
    if not Energy_Surge_ID:
        from Py4GWCoreLib.Skill import Skill

        Energy_Surge_ID = int(Skill.GetID(ENERGY_SURGE_SKILL_NAME))
    return int(Energy_Surge_ID)


@dataclass(frozen=True, slots=True)
class _RuntimeParameters:
    skill_id: int
    aoe_radius: float
    cast_range: float
    domination_rank: int
    local_drain: float
    maximum_drain: float
    progression_values: tuple[tuple[int, float], ...]
    activation_ms: int
    native_aftercast_ms: int
    dispatch_window_ms: int
    lease_ms: int


@dataclass(frozen=True, slots=True)
class _IntentRow:
    slot_index: int
    owner_email: str
    kind_id: int
    lock_mode: int
    reentry_policy: int
    claim_strength: int
    max_holders: int
    skill_id: int
    target_agent_id: int
    isolation_group_id: int
    posted_at_tick: int
    expires_at_tick: int
    active: bool


@dataclass(frozen=True, slots=True)
class _ReservationHandle:
    slot_index: int
    owner_email: str
    skill_id: int
    target_agent_id: int
    isolation_group_id: int


@dataclass(frozen=True, slots=True)
class _ForeignOwnerSnapshot:
    owner_email: str
    active: bool
    isolation_group_id: int
    map_id: int
    agent_id: int
    skill_ids: tuple[int, ...]
    domination_rank: int | None


@dataclass(frozen=True, slots=True)
class _FinalPacket:
    target_agent_id: int
    target_profession: str
    target_health_fraction: float
    target_distance_from_player: float
    valuable_affected_count: int


def _normalise_name(value: Any) -> str:
    return "".join(character.casefold() for character in str(value) if character.isalnum())


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class SmartEnergySurgeHandler(BuildMgr):
    """Composable BuildMgr-backed handler for the stable Energy Surge behavior."""

    def __init__(
        self,
        match_only: bool = False,
        *,
        standalone_fallback: bool = False,
        skill_id: int | None = None,
    ):
        from Py4GWCoreLib import Profession

        self.energy_surge_id = int(skill_id or get_energy_surge_id())

        super().__init__(
            name="Smart Energy Surge",
            required_primary=Profession.Mesmer,
            required_secondary=Profession(0),
            template_code="OQBCAswEc5Jw0zuoNopTOggD",
            required_skills=[self.energy_surge_id],
            optional_skills=[],
            is_template_only=True,
        )
        if match_only:
            return

        self._standalone_fallback = bool(standalone_fallback)
        self._disposed = False
        self._skill_slot: int | None = None
        self.SetSkillCastingFn(self._run_local_skill_logic)
        if self._standalone_fallback:
            from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI as HeroAIBuild

            self.SetFallback("HeroAI", HeroAIBuild(standalone_fallback=True))
            self.SetBlockedSkills([self.energy_surge_id])

        self._last_decision_tick: int | None = None
        self._last_instance_uptime_ms: int | None = None
        self._local_generation = 0
        self._lifecycle_id: tuple[int, int, int] | None = None
        self._focus_state = FocusState()
        self._focus_aoe_radius = 0.0
        self._active_reservation: _ReservationHandle | None = None
        self._diagnostic_state: dict[str, tuple[int, tuple[Any, ...]]] = {}

    @property
    def skill_slot(self) -> int | None:
        return self._skill_slot

    def set_skill_slot(self, slot_index: int | None) -> None:
        self._skill_slot = None if slot_index is None else int(slot_index)

    def update_lifecycle(self, _context: Any = None) -> None:
        if self._disposed:
            return
        self._refresh_lifecycle()

    def try_cast(self):
        """Run the existing local cast path without invoking a per-handler fallback."""

        if False:
            yield
        if self._disposed:
            return False

        process_phase = getattr(self, "_process_skill_casting_phase", None)
        if callable(process_phase):
            phase_result = process_phase(self._local_skill_casting_handler)
            yield from cast(Generator[None, None, Any], phase_result)
            return bool(self.DidTickSucceed())

        result = self._run_local_skill_logic()
        if hasattr(result, "__next__"):
            result = yield from result
        return bool(result)

    def cancel_pending(self, reason: str) -> None:
        self._release_reservation(reason)
        self._last_decision_tick = None
        if self._lifecycle_id is None:
            self._focus_state = FocusState()
        else:
            self._focus_state = FocusState(lifecycle_id=self._lifecycle_id)
        self._focus_aoe_radius = 0.0
        reset_tick_state = getattr(self, "ResetTickState", None)
        if callable(reset_tick_state):
            reset_tick_state()

    def dispose(self, reason: str = "handler_disposed") -> None:
        if self._disposed:
            return
        self.cancel_pending(reason)
        self._disposed = True

    def OnContractActivated(self, cached_data: Any = None) -> None:
        self._disposed = False
        activate = getattr(super(), "OnContractActivated", None)
        if callable(activate):
            activate(cached_data)

    def ScoreMatch(
        self,
        current_primary=None,
        current_secondary=None,
        current_skills: list[int] | None = None,
    ) -> int:
        if current_skills is None:
            current_skills = self._get_current_skills()
        base_score = super().ScoreMatch(
            current_primary=current_primary,
            current_secondary=current_secondary,
            current_skills=current_skills,
        )
        if base_score < 0:
            return -1
        return MATCH_SCORE_BONUS + base_score

    @staticmethod
    def _now_tick() -> int:
        try:
            import PySystem

            return int(PySystem.get_tick_count64())
        except Exception:
            return 0

    @staticmethod
    def _intent_tick_expired(now_tick: int, expires_at_tick: int) -> bool:
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import tick_is_expired

        return bool(tick_is_expired(int(now_tick), int(expires_at_tick)))

    @staticmethod
    def _duration_to_ms(value: Any) -> int | None:
        unit: str | None = None
        raw_value = value
        if isinstance(value, Mapping):
            for key in ("milliseconds", "millisecond", "ms"):
                if key in value:
                    raw_value = value[key]
                    unit = "ms"
                    break
            else:
                for key in ("seconds", "second", "s"):
                    if key in value:
                        raw_value = value[key]
                        unit = "seconds"
                        break
                else:
                    raw_value = value.get("value")
                    unit = str(value.get("unit", "")) or None
        else:
            for attribute_name in ("milliseconds", "millisecond", "ms"):
                if hasattr(value, attribute_name):
                    raw_value = getattr(value, attribute_name)
                    unit = "ms"
                    break
            else:
                for attribute_name in ("seconds", "second"):
                    if hasattr(value, attribute_name):
                        raw_value = getattr(value, attribute_name)
                        unit = "seconds"
                        break

        numeric = _finite_float(raw_value)
        if numeric is None or numeric < 0.0:
            return None
        if unit is not None:
            normalized_unit = _normalise_name(unit)
            if normalized_unit in {"ms", "millisecond", "milliseconds"}:
                return int(round(numeric))
            if normalized_unit in {"s", "second", "seconds"}:
                return int(round(numeric * 1000.0))
            return None

        # SkillCache's current contract is seconds. Values larger than a
        # normal skill duration are accepted as already-normalized ms so the
        # controller remains compatible with explicit native timing fakes.
        return int(round(numeric if numeric > 20.0 else numeric * 1000.0))

    @staticmethod
    def _progression_entry(
        progression_data: Any,
    ) -> tuple[tuple[int, float], ...] | None:
        if not progression_data:
            return None
        selected_values: Any = None
        for entry in progression_data:
            attribute_name: Any = None
            field_name: Any = None
            values: Any = None
            if isinstance(entry, Mapping):
                attribute_name = entry.get("attribute", entry.get("attribute_name"))
                field_name = entry.get("field", entry.get("field_name"))
                values = entry.get("values", entry.get("progression"))
            elif isinstance(entry, (tuple, list)) and len(entry) >= 3:
                attribute_name, field_name, values = entry[0], entry[1], entry[2]

            is_domination = (
                _normalise_name(attribute_name) in {"dominationmagic", "domination"}
                or str(attribute_name).strip() == "2"
            )
            if not is_domination or not isinstance(values, Mapping):
                continue
            converted: list[tuple[int, float]] = []
            for rank, amount in values.items():
                try:
                    rank_value = int(rank)
                except (TypeError, ValueError):
                    continue
                if rank_value < 0:
                    continue
                amount_value = _finite_float(amount)
                if amount_value is None or amount_value < 0.0:
                    continue
                converted.append((rank_value, amount_value))
            if not converted:
                continue
            converted_values = tuple(sorted(converted))
            field_key = _normalise_name(field_name)
            if field_key in {"energyloss", "energydrain", "energylost"}:
                selected_values = converted_values
                break

        return selected_values

    @staticmethod
    def _current_domination_rank(agent: Any, player_agent_id: int) -> int | None:
        try:
            attributes = agent.GetAttributes(int(player_agent_id))
        except Exception:
            return None
        if attributes is None:
            return None
        for attribute in attributes:
            attribute_id = getattr(attribute, "attribute_id", getattr(attribute, "Id", -1))
            try:
                if int(attribute_id) != 2:
                    continue
            except (TypeError, ValueError):
                continue
            effective_level = getattr(attribute, "level", None)
            if effective_level is None:
                effective_level = getattr(attribute, "Value", None)
            if effective_level is None:
                return None
            numeric_level = _finite_float(effective_level)
            if numeric_level is None or numeric_level < 0.0 or not numeric_level.is_integer():
                return None
            return int(numeric_level)
        return None

    def _resolve_runtime_parameters(self) -> _RuntimeParameters | None:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Range
        from Py4GWCoreLib.Skill import Skill

        player_agent_id = int(Player.GetAgentID() or 0)
        rank = self._current_domination_rank(Agent, player_agent_id)
        if rank is None:
            return None

        progression_values = self._progression_entry(Skill.GetProgressionData(self.energy_surge_id))
        if progression_values is None:
            return None
        progression_by_rank = dict(progression_values)
        local_drain = progression_by_rank.get(rank)
        if local_drain is None or not math.isfinite(local_drain) or local_drain <= 0.0:
            return None
        maximum_drain = max(amount for _, amount in progression_values)
        if not math.isfinite(maximum_drain) or maximum_drain <= 0.0:
            return None

        try:
            aoe_radius = float(GLOBAL_CACHE.Skill.Data.GetAoERange(self.energy_surge_id))
        except Exception:
            return None
        cast_range = _finite_float(getattr(Range.Spellcast, "value", None))
        if not math.isfinite(aoe_radius) or aoe_radius <= 0.0 or cast_range is None or cast_range <= 0.0:
            return None

        try:
            activation_ms = self._duration_to_ms(GLOBAL_CACHE.Skill.Data.GetActivation(self.energy_surge_id))
            native_aftercast_ms = self._duration_to_ms(GLOBAL_CACHE.Skill.Data.GetAftercast(self.energy_surge_id))
        except Exception:
            return None
        if activation_ms is None or native_aftercast_ms is None:
            return None

        dispatch_window_ms = max(
            250,
            activation_ms + native_aftercast_ms + CAST_SAFETY_MARGIN_MS,
        )
        from Py4GWCoreLib.GlobalCache.shared_memory_src.Globals import SHMEM_INTENT_DEFAULT_PING_BUDGET_MS

        lease_ms = dispatch_window_ms + int(SHMEM_INTENT_DEFAULT_PING_BUDGET_MS) + RECENT_DRAIN_PROJECTION_HOLD_MS
        return _RuntimeParameters(
            skill_id=self.energy_surge_id,
            aoe_radius=aoe_radius,
            cast_range=cast_range,
            domination_rank=rank,
            local_drain=float(local_drain),
            maximum_drain=float(maximum_drain),
            progression_values=progression_values,
            activation_ms=activation_ms,
            native_aftercast_ms=native_aftercast_ms,
            dispatch_window_ms=dispatch_window_ms,
            lease_ms=lease_ms,
        )

    @staticmethod
    def _lifecycle_inputs() -> tuple[int, int, int]:
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import Player

        return (
            int(Map.GetMapID() or 0),
            int(Player.GetAgentID() or 0),
            int(Map.GetInstanceUptime() or 0),
        )

    def _refresh_lifecycle(self) -> tuple[int, int, int]:
        map_id, player_agent_id, uptime_ms = self._lifecycle_inputs()
        previous_id = self._lifecycle_id
        if previous_id is not None and (
            previous_id[0] != map_id
            or previous_id[1] != player_agent_id
            or (self._last_instance_uptime_ms is not None and uptime_ms < self._last_instance_uptime_ms)
        ):
            self._local_generation += 1
            self._focus_state = FocusState()
            self._last_decision_tick = None
            self._release_reservation("lifecycle_reset")

        lifecycle_id = (map_id, player_agent_id, self._local_generation)
        self._lifecycle_id = lifecycle_id
        self._last_instance_uptime_ms = uptime_ms
        if self._focus_state.lifecycle_id != lifecycle_id:
            self._focus_state = FocusState(lifecycle_id=lifecycle_id)
        return lifecycle_id

    def _runtime_gate(self) -> bool:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import Player

        try:
            if not Map.IsMapReady() or not Map.IsExplorable():
                return False
        except Exception:
            return False
        try:
            from Py4GWCoreLib import Routines
        except ImportError:
            Routines = None
        if Routines is not None:
            try:
                map_checks = getattr(getattr(Routines, "Checks", None), "Map", None)
                map_valid = getattr(map_checks, "MapValid", None)
                if callable(map_valid) and not map_valid():
                    return False
            except Exception:
                return False
        player_agent_id = int(Player.GetAgentID() or 0)
        if player_agent_id <= 0:
            return False
        try:
            if not Agent.IsValid(player_agent_id) or Agent.IsDead(player_agent_id):
                return False
            is_knocked_down = getattr(Agent, "IsKnockedDown", None)
            if callable(is_knocked_down) and is_knocked_down(player_agent_id):
                return False
            if Agent.IsCasting(player_agent_id):
                return False
        except Exception:
            return False
        return True

    @staticmethod
    def _local_owner_context() -> tuple[str, int] | None:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Player

        owner_email = str(Player.GetAccountEmail() or "").strip()
        if not owner_email:
            return None
        try:
            group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(owner_email))
        except Exception:
            return None
        return owner_email, group_id

    @staticmethod
    def _copy_intent_row(slot_index: Any, intent: Any) -> _IntentRow:
        return _IntentRow(
            slot_index=int(slot_index),
            owner_email=str(getattr(intent, "OwnerEmail", "") or "").strip(),
            kind_id=int(getattr(intent, "KindID", 0) or 0),
            lock_mode=int(getattr(intent, "LockMode", 0) or 0),
            reentry_policy=int(getattr(intent, "ReentryPolicy", 0) or 0),
            claim_strength=int(getattr(intent, "ClaimStrength", 0) or 0),
            max_holders=int(getattr(intent, "MaxHolders", 0) or 0),
            skill_id=int(getattr(intent, "SkillID", 0) or 0),
            target_agent_id=int(getattr(intent, "TargetAgentID", 0) or 0),
            isolation_group_id=int(getattr(intent, "IsolationGroupID", 0) or 0),
            posted_at_tick=int(getattr(intent, "PostedAtTick", 0) or 0),
            expires_at_tick=int(getattr(intent, "ExpiresAtTick", 0) or 0),
            active=bool(getattr(intent, "Active", False)),
        )

    @staticmethod
    def _raw_intent_method(all_accounts: Any) -> Any:
        method = getattr(type(all_accounts), "GetAllIntents", None)
        if method is None:
            return getattr(all_accounts, "GetAllIntents")
        return getattr(method, "__wrapped__", method)

    def _read_raw_intents(self) -> tuple[_IntentRow, ...] | None:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            all_accounts = GLOBAL_CACHE.ShMem.GetAllAccounts()
            class_method = getattr(type(all_accounts), "GetAllIntents", None)
            if class_method is None:
                raw_method = getattr(all_accounts, "GetAllIntents")
                try:
                    raw_rows = raw_method()
                except TypeError:
                    raw_rows = raw_method(all_accounts)
            else:
                raw_method = self._raw_intent_method(all_accounts)
                raw_rows = raw_method(all_accounts)
            copied_rows: list[_IntentRow] = []
            for entry in raw_rows or ():
                if not isinstance(entry, (tuple, list)) or len(entry) < 2:
                    continue
                copied_rows.append(self._copy_intent_row(entry[0], entry[1]))
            return tuple(copied_rows)
        except Exception:
            return None

    def _is_energy_intent(
        self,
        row: _IntentRow,
        group_id: int,
        now_tick: int,
    ) -> bool:
        from Py4GWCoreLib.enums_src.Whiteboard_enums import WhiteboardLockKind

        return (
            row.active
            and not self._intent_tick_expired(now_tick, row.expires_at_tick)
            and row.kind_id == int(WhiteboardLockKind.SKILL_TARGET)
            and row.skill_id == self.energy_surge_id
            and row.target_agent_id > 0
            and row.isolation_group_id == int(group_id)
        )

    @staticmethod
    def _is_exact_contract(row: _IntentRow) -> bool:
        from Py4GWCoreLib.enums_src.Whiteboard_enums import WhiteboardClaimStrength
        from Py4GWCoreLib.enums_src.Whiteboard_enums import WhiteboardLockKind
        from Py4GWCoreLib.enums_src.Whiteboard_enums import WhiteboardLockMode
        from Py4GWCoreLib.enums_src.Whiteboard_enums import WhiteboardReentryPolicy

        return (
            row.kind_id == int(WhiteboardLockKind.SKILL_TARGET)
            and row.lock_mode == int(WhiteboardLockMode.EXCLUSIVE)
            and row.reentry_policy == int(WhiteboardReentryPolicy.OWNER_REENTRANT)
            and row.claim_strength == int(WhiteboardClaimStrength.HARD)
            and row.max_holders == 1
        )

    def _matching_foreign_rows(
        self,
        rows: tuple[_IntentRow, ...],
        owner_email: str,
        group_id: int,
        now_tick: int,
        target_agent_id: int | None = None,
    ) -> tuple[_IntentRow, ...]:
        return tuple(
            row
            for row in rows
            if self._is_energy_intent(row, group_id, now_tick)
            and row.owner_email
            and row.owner_email != owner_email
            and (target_agent_id is None or row.target_agent_id == target_agent_id)
        )

    @staticmethod
    def _copy_attribute_rank(agent_data: Any) -> int | None:
        attributes = getattr(getattr(agent_data, "Attributes", None), "Attributes", ())
        for attribute in attributes or ():
            attribute_id = getattr(attribute, "Id", getattr(attribute, "attribute_id", -1))
            attribute_id_value = _finite_float(attribute_id)
            if attribute_id_value is None or int(attribute_id_value) != 2:
                continue
            value = getattr(attribute, "Value", getattr(attribute, "level", None))
            if value is None:
                return None
            numeric_value = _finite_float(value)
            if numeric_value is None or numeric_value < 0.0 or not numeric_value.is_integer():
                return None
            return int(numeric_value)
        return None

    def _copy_foreign_owner_snapshots(
        self,
        owner_emails: set[str],
        now_tick: int,
        current_map_id: int,
    ) -> dict[str, _ForeignOwnerSnapshot]:
        snapshots: dict[str, _ForeignOwnerSnapshot] = {}
        if not owner_emails:
            return snapshots
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib.GlobalCache.shared_memory_src.Globals import SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS

            all_accounts = GLOBAL_CACHE.ShMem.GetAllAccounts()
            account_data = getattr(all_accounts, "AccountData", ())
        except Exception:
            return snapshots

        candidates: list[tuple[bool, _ForeignOwnerSnapshot]] = []
        for account in account_data or ():
            owner_email = str(getattr(account, "AccountEmail", "") or "").strip()
            if owner_email not in owner_emails:
                continue
            last_updated = int(getattr(account, "LastUpdated", 0) or 0)
            slot_active = bool(getattr(account, "IsSlotActive", True))
            is_current = (
                slot_active and last_updated > 0 and now_tick - last_updated < int(SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS)
            )
            agent_data = getattr(account, "AgentData", None)
            map_data = getattr(agent_data, "Map", None)
            skillbar = getattr(agent_data, "Skillbar", None)
            skills = getattr(skillbar, "Skills", ())
            skill_ids: list[int] = []
            for skill in skills or ():
                try:
                    skill_ids.append(int(getattr(skill, "Id", 0) or 0))
                except (TypeError, ValueError):
                    continue
            snapshot = _ForeignOwnerSnapshot(
                owner_email=owner_email,
                active=is_current,
                isolation_group_id=int(getattr(account, "IsolationGroupID", 0) or 0),
                map_id=int(getattr(map_data, "MapID", 0) or 0),
                agent_id=int(getattr(agent_data, "AgentID", 0) or 0),
                skill_ids=tuple(skill_ids),
                domination_rank=self._copy_attribute_rank(agent_data),
            )
            candidates.append((bool(getattr(account, "IsAccount", False)), snapshot))

        for owner_email in owner_emails:
            owner_candidates = [
                candidate
                for is_account, candidate in candidates
                if candidate.owner_email == owner_email
                and (
                    is_account
                    or not any(
                        account_candidate.owner_email == owner_email and account_flag
                        for account_flag, account_candidate in candidates
                    )
                )
            ]
            if owner_candidates:
                snapshots[owner_email] = max(
                    owner_candidates,
                    key=lambda candidate: (candidate.active, candidate.agent_id),
                )
        return snapshots

    def _foreign_drain(
        self,
        row: _IntentRow,
        snapshots: Mapping[str, _ForeignOwnerSnapshot],
        params: _RuntimeParameters,
        current_map_id: int,
    ) -> float:
        if not self._is_exact_contract(row):
            return params.maximum_drain
        owner = snapshots.get(row.owner_email)
        if owner is None:
            return params.maximum_drain
        if not owner.active or owner.agent_id <= 0:
            return params.maximum_drain
        if owner.isolation_group_id != row.isolation_group_id:
            return params.maximum_drain
        if current_map_id and owner.map_id and owner.map_id != current_map_id:
            return params.maximum_drain
        if self.energy_surge_id not in owner.skill_ids:
            return params.maximum_drain
        if owner.domination_rank is None:
            return params.maximum_drain
        values = dict(params.progression_values)
        drain = values.get(owner.domination_rank)
        if drain is None or not math.isfinite(drain) or drain < 0.0:
            return params.maximum_drain
        return float(drain)

    def _foreign_projections(
        self,
        rows: tuple[_IntentRow, ...],
        owner_email: str,
        group_id: int,
        now_tick: int,
        params: _RuntimeParameters,
        current_map_id: int,
    ) -> tuple[tuple[_IntentRow, ...], tuple[ForeignReservationProjection, ...]]:
        foreign_rows = self._matching_foreign_rows(
            rows,
            owner_email,
            group_id,
            now_tick,
        )
        unexpected_rows = tuple(
            (
                row.target_agent_id,
                row.lock_mode,
                row.max_holders,
                row.reentry_policy,
                row.claim_strength,
            )
            for row in foreign_rows
            if not self._is_exact_contract(row)
        )
        if unexpected_rows:
            self._emit_diagnostic(
                "decision_rejected",
                ("unexpected_foreign_contract", unexpected_rows),
            )
        snapshots = self._copy_foreign_owner_snapshots(
            {row.owner_email for row in foreign_rows},
            now_tick,
            current_map_id,
        )
        projections = tuple(
            ForeignReservationProjection(
                target_agent_id=row.target_agent_id,
                projected_drain=self._foreign_drain(
                    row,
                    snapshots,
                    params,
                    current_map_id,
                ),
            )
            for row in foreign_rows
        )
        return foreign_rows, projections

    def _build_snapshot(
        self,
        params: _RuntimeParameters,
        lifecycle_id: tuple[int, int, int],
        observed_at_ms: int,
    ) -> tuple[CombatSnapshot, tuple[EnergySurgeEnemyObservation, ...], PairwiseDistances] | None:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player
        from Py4GWCoreLib.enums_src.GameData_enums import Allegiance

        player_position = Player.GetXY()
        if not player_position or len(player_position) < 2:
            return None
        player_x = _finite_float(player_position[0])
        player_y = _finite_float(player_position[1])
        if player_x is None or player_y is None:
            return None
        scan_radius = params.cast_range + params.aoe_radius
        scan_radius_squared = scan_radius * scan_radius
        observations: list[EnemyObservation] = []
        policy_observations: list[EnergySurgeEnemyObservation] = []
        seen_ids: set[int] = set()
        try:
            enemy_ids = AgentArray.GetEnemyArray()
        except Exception:
            return None

        for raw_agent_id in enemy_ids or ():
            try:
                agent_id = int(raw_agent_id)
            except (TypeError, ValueError):
                continue
            if agent_id <= 0 or agent_id in seen_ids:
                continue
            seen_ids.add(agent_id)
            try:
                if not Agent.IsValid(agent_id) or Agent.IsDead(agent_id):
                    continue
                allegiance = Agent.GetAllegiance(agent_id)
                allegiance_value = int(allegiance[0] if isinstance(allegiance, tuple) else allegiance)
                if allegiance_value != int(Allegiance.Enemy.value):
                    continue
                position = Agent.GetXY(agent_id)
                if not position or len(position) < 2:
                    continue
                x_value = _finite_float(position[0])
                y_value = _finite_float(position[1])
                health_fraction = _finite_float(Agent.GetHealth(agent_id))
                if x_value is None or y_value is None or health_fraction is None or not 0.0 <= health_fraction <= 1.0:
                    continue
                delta_x = x_value - player_x
                delta_y = y_value - player_y
                distance_squared = delta_x * delta_x + delta_y * delta_y
                if distance_squared > scan_radius_squared:
                    continue
                profession_names = Agent.GetProfessionNames(agent_id)
                profession = str(profession_names[0] if profession_names else "Unknown")
                observation = EnemyObservation(agent_id, x_value, y_value)
                observations.append(observation)
                policy_observations.append(
                    EnergySurgeEnemyObservation(
                        observation=observation,
                        profession=profession,
                        health_fraction=health_fraction,
                        distance_from_player=math.sqrt(distance_squared),
                        is_caster=bool(Agent.IsCaster(agent_id)),
                        is_casting=bool(Agent.IsCasting(agent_id)),
                    )
                )
            except Exception:
                continue

        snapshot = CombatSnapshot(
            enemies=tuple(observations),
            observed_at=float(observed_at_ms) / 1000.0,
            lifecycle_id=lifecycle_id,
        )
        distances = pairwise_squared_distances(snapshot)
        return snapshot, tuple(policy_observations), distances

    def _focus_candidate(
        self,
        decision: EnergySurgeDecision,
        snapshot: CombatSnapshot,
        distances: PairwiseDistances,
    ) -> EnergySurgeCandidateEvaluation | None:
        groups = build_combat_groups(
            snapshot,
            self._focus_aoe_radius,
            distances=distances,
        )
        evaluation_by_group = {evaluation.group_identity: evaluation for evaluation in decision.groups}
        focus_candidates = tuple(
            FocusCandidate(
                group=group,
                value=max(0.0, float(evaluation_by_group[group.canonical_id].policy_value)),
                viable=bool(
                    evaluation_by_group[group.canonical_id].viable
                    and evaluation_by_group[group.canonical_id].best_candidate is not None
                ),
            )
            for group in groups
            if group.canonical_id in evaluation_by_group
        )
        viable_exists = any(candidate.viable for candidate in focus_candidates)
        focused_group_id = (
            self._focus_state.focused_group.canonical_id if self._focus_state.focused_group is not None else None
        )
        if focused_group_id in evaluation_by_group and viable_exists:
            focused_evaluation = evaluation_by_group[focused_group_id]
            if not focused_evaluation.viable:
                self._focus_state = FocusState(lifecycle_id=snapshot.lifecycle_id)

        previous_focus_id = focused_group_id
        parameters = FocusTransitionParameters(
            minimum_overlap_ratio=FOCUS_MINIMUM_OVERLAP_RATIO,
            gap_grace_seconds=float(FOCUS_GAP_GRACE_MS) / 1000.0,
            challenger_stability_seconds=float(FOCUS_CHALLENGER_STABILITY_MS) / 1000.0,
            switch_value_ratio=FOCUS_SWITCH_VALUE_RATIO,
        )
        self._focus_state = transition_focus(
            self._focus_state,
            snapshot,
            focus_candidates,
            parameters,
        )
        new_focus_id = (
            self._focus_state.focused_group.canonical_id if self._focus_state.focused_group is not None else None
        )
        if previous_focus_id != new_focus_id:
            self._emit_diagnostic(
                "focus_changed",
                (previous_focus_id, new_focus_id),
            )
        if new_focus_id is None:
            return None
        focused_evaluation = evaluation_by_group.get(new_focus_id)
        if focused_evaluation is None or not focused_evaluation.viable:
            return None
        return focused_evaluation.best_candidate

    def _emit_diagnostic(self, family: str, signature: tuple[Any, ...]) -> None:
        now_tick = self._now_tick()
        previous = self._diagnostic_state.get(family)
        if previous is not None:
            previous_tick, previous_signature = previous
            if previous_signature == signature and now_tick - previous_tick < 1000:
                return
        self._diagnostic_state[family] = (now_tick, signature)
        try:
            from PySystem import Console

            from Py4GWCoreLib import ConsoleLog

            values = ", ".join(str(value) for value in signature)
            ConsoleLog(
                self.build_name,
                f"{family}: {values}",
                Console.MessageType.Info,
            )
        except Exception:
            return

    def _release_reservation(self, reason: str) -> None:
        handle = self._active_reservation
        self._active_reservation = None
        if handle is None:
            return
        released = False
        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            released = bool(
                GLOBAL_CACHE.ShMem.ClearIntentIfMatch(
                    handle.slot_index,
                    handle.owner_email,
                    handle.skill_id,
                    handle.target_agent_id,
                    handle.isolation_group_id,
                )
            )
        except Exception:
            released = False
        self._emit_diagnostic(
            "reservation_released",
            (handle.target_agent_id, reason, released),
        )

    def _acquire_reservation(
        self,
        target_agent_id: int,
        params: _RuntimeParameters,
    ) -> _ReservationHandle | None:
        context = self._local_owner_context()
        if context is None:
            self._emit_diagnostic("reservation_rejected", (target_agent_id, "owner_context"))
            return None
        owner_email, group_id = context
        now_tick = self._now_tick()
        rows = self._read_raw_intents()
        if rows is None:
            self._emit_diagnostic("reservation_rejected", (target_agent_id, "raw_read"))
            return None
        foreign_rows = self._matching_foreign_rows(
            rows,
            owner_email,
            group_id,
            now_tick,
            target_agent_id,
        )
        if len(foreign_rows) >= MAXIMUM_FOREIGN_RESERVATIONS:
            self._emit_diagnostic("reservation_rejected", (target_agent_id, "foreign_cap"))
            return None

        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            expires_at_tick = now_tick + params.lease_ms
            slot_index = int(
                GLOBAL_CACHE.ShMem.PostIntent(
                    owner_email,
                    self.energy_surge_id,
                    int(target_agent_id),
                    int(expires_at_tick),
                    isolation_group_id=int(group_id),
                )
            )
        except Exception:
            slot_index = -1
        if slot_index < 0:
            self._emit_diagnostic("reservation_rejected", (target_agent_id, "post_failed"))
            return None

        handle = _ReservationHandle(
            slot_index=slot_index,
            owner_email=owner_email,
            skill_id=self.energy_surge_id,
            target_agent_id=int(target_agent_id),
            isolation_group_id=group_id,
        )
        self._active_reservation = handle
        post_rows = self._read_raw_intents()
        expected = post_rows is not None and any(
            row.slot_index == handle.slot_index
            and row.owner_email == handle.owner_email
            and row.skill_id == handle.skill_id
            and row.target_agent_id == handle.target_agent_id
            and row.isolation_group_id == handle.isolation_group_id
            and self._is_exact_contract(row)
            and row.active
            and not self._intent_tick_expired(self._now_tick(), row.expires_at_tick)
            for row in post_rows
        )
        if not expected:
            self._release_reservation("post_validation")
            self._emit_diagnostic("reservation_rejected", (target_agent_id, "post_validation"))
            return None

        post_foreign_rows = self._matching_foreign_rows(
            post_rows or (),
            owner_email,
            group_id,
            self._now_tick(),
            target_agent_id,
        )
        if len(post_foreign_rows) >= MAXIMUM_FOREIGN_RESERVATIONS:
            self._release_reservation("post_race")
            self._emit_diagnostic("reservation_rejected", (target_agent_id, "post_race"))
            return None
        self._emit_diagnostic(
            "reservation_posted",
            (target_agent_id, slot_index, params.lease_ms),
        )
        return handle

    def _fresh_final_packet(
        self,
        target_agent_id: int,
        params: _RuntimeParameters,
    ) -> _FinalPacket | None:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player
        from Py4GWCoreLib.enums_src.GameData_enums import Allegiance

        player_position = Player.GetXY()
        if not player_position or len(player_position) < 2:
            return None
        player_x = _finite_float(player_position[0])
        player_y = _finite_float(player_position[1])
        if player_x is None or player_y is None:
            return None
        try:
            enemy_ids = AgentArray.GetEnemyArray()
        except Exception:
            return None

        scan_radius = params.cast_range + params.aoe_radius
        scan_radius_squared = scan_radius * scan_radius
        aoe_radius_squared = params.aoe_radius * params.aoe_radius
        target_seen = False
        target_profession = "Unknown"
        target_health_fraction: float | None = None
        target_distance: float | None = None
        target_position: tuple[float, float] | None = None
        fresh_members: list[tuple[float, float, float]] = []
        seen_ids: set[int] = set()

        for raw_agent_id in enemy_ids or ():
            try:
                agent_id = int(raw_agent_id)
            except (TypeError, ValueError):
                continue
            if agent_id <= 0 or agent_id in seen_ids:
                continue
            seen_ids.add(agent_id)
            try:
                if not Agent.IsValid(agent_id) or Agent.IsDead(agent_id):
                    continue
                allegiance = Agent.GetAllegiance(agent_id)
                allegiance_value = int(allegiance[0] if isinstance(allegiance, tuple) else allegiance)
                if allegiance_value != int(Allegiance.Enemy.value):
                    continue
                position = Agent.GetXY(agent_id)
                health_fraction = _finite_float(Agent.GetHealth(agent_id))
                if not position or len(position) < 2 or health_fraction is None:
                    continue
                x_value = _finite_float(position[0])
                y_value = _finite_float(position[1])
                if x_value is None or y_value is None or not 0.0 <= health_fraction <= 1.0:
                    continue
                from_player_x = x_value - player_x
                from_player_y = y_value - player_y
                player_distance_squared = from_player_x * from_player_x + from_player_y * from_player_y
                if player_distance_squared > scan_radius_squared:
                    continue
                if agent_id == target_agent_id:
                    target_seen = True
                    target_position = (x_value, y_value)
                    target_health_fraction = health_fraction
                    target_distance = math.sqrt(player_distance_squared)
                    profession_names = Agent.GetProfessionNames(agent_id)
                    target_profession = str(profession_names[0] if profession_names else "Unknown")
                fresh_members.append((x_value, y_value, health_fraction))
            except Exception:
                continue

        if not target_seen or target_position is None or target_health_fraction is None or target_distance is None:
            return None
        if target_distance > params.cast_range:
            return None
        valuable_affected_count = 0
        for x_value, y_value, health_fraction in fresh_members:
            delta_x = x_value - target_position[0]
            delta_y = y_value - target_position[1]
            if delta_x * delta_x + delta_y * delta_y <= aoe_radius_squared:
                if health_fraction > LOW_HP_THRESHOLD:
                    valuable_affected_count += 1
        return _FinalPacket(
            target_agent_id=target_agent_id,
            target_profession=target_profession,
            target_health_fraction=target_health_fraction,
            target_distance_from_player=target_distance,
            valuable_affected_count=valuable_affected_count,
        )

    def _final_revalidate(
        self,
        target_agent_id: int,
        lifecycle_id: tuple[int, int, int],
        params: _RuntimeParameters,
        handle: _ReservationHandle,
    ) -> tuple[bool, _RuntimeParameters | None, str]:
        current_map_id, current_player_id, current_uptime = self._lifecycle_inputs()
        if (
            self._lifecycle_id != lifecycle_id
            or current_map_id != lifecycle_id[0]
            or current_player_id != lifecycle_id[1]
            or (self._last_instance_uptime_ms is not None and current_uptime < self._last_instance_uptime_ms)
            or not self._runtime_gate()
        ):
            return False, None, "runtime_gate"

        context = self._local_owner_context()
        if context is None or context != (handle.owner_email, handle.isolation_group_id):
            return False, None, "owner_context"
        try:
            if not self.CanCastSkillID(self.energy_surge_id):
                return False, None, "can_cast"
        except Exception:
            return False, None, "can_cast"

        final_params = self._resolve_runtime_parameters()
        if final_params is None:
            return False, None, "live_data"

        now_tick = self._now_tick()
        rows = self._read_raw_intents()
        if rows is None:
            return False, None, "raw_read"
        owned = any(
            row.slot_index == handle.slot_index
            and row.owner_email == handle.owner_email
            and row.skill_id == handle.skill_id
            and row.target_agent_id == handle.target_agent_id
            and row.isolation_group_id == handle.isolation_group_id
            and row.active
            and self._is_exact_contract(row)
            and not self._intent_tick_expired(now_tick, row.expires_at_tick)
            for row in rows
        )
        if not owned:
            return False, None, "owned_reservation"

        foreign_rows, projections = self._foreign_projections(
            rows,
            handle.owner_email,
            handle.isolation_group_id,
            now_tick,
            final_params,
            current_map_id,
        )
        target_foreign_count = sum(row.target_agent_id == target_agent_id for row in foreign_rows)
        if target_foreign_count >= MAXIMUM_FOREIGN_RESERVATIONS:
            return False, None, "foreign_cap"

        packet = self._fresh_final_packet(target_agent_id, final_params)
        if packet is None:
            return False, None, "target_packet"
        if packet.target_health_fraction <= LOW_HP_THRESHOLD:
            return False, None, "low_hp_target"

        foreign_drain = sum(
            projection.projected_drain for projection in projections if projection.target_agent_id == target_agent_id
        )
        inferred_max_energy = infer_max_energy(packet.target_profession)
        projected_energy = max(0.0, float(inferred_max_energy) - foreign_drain)
        effective_drain = min(final_params.local_drain, projected_energy)
        expected_packet_damage = effective_drain * DEFAULT_POLICY.damage_per_energy * packet.valuable_affected_count
        if expected_packet_damage < DEFAULT_POLICY.minimum_expected_packet_damage:
            return False, None, "below_minimum_damage"
        return True, final_params, "ok"

    def _dispatch_selected(
        self,
        target_agent_id: int,
        lifecycle_id: tuple[int, int, int],
        params: _RuntimeParameters,
    ):
        if False:
            yield
        handle = self._acquire_reservation(target_agent_id, params)
        if handle is None:
            return False
        valid, final_params, failure_reason = self._final_revalidate(
            target_agent_id,
            lifecycle_id,
            params,
            handle,
        )
        if not valid or final_params is None:
            self._release_reservation(failure_reason)
            self._emit_diagnostic(
                "revalidation_failed",
                (target_agent_id, failure_reason),
            )
            return False
        try:
            cast_result = yield from self.CastSkillID(
                skill_id=self.energy_surge_id,
                log=False,
                aftercast_delay=final_params.dispatch_window_ms,
                target_agent_id=target_agent_id,
            )
        except Exception:
            self._release_reservation("dispatch_exception")
            return False
        if not cast_result:
            self._release_reservation("dispatch_rejected")
            return False
        self._active_reservation = None
        self._emit_diagnostic(
            "dispatch_accepted",
            (target_agent_id, final_params.dispatch_window_ms),
        )
        return True

    def _run_local_skill_logic(self):
        if False:
            yield
        if self._disposed:
            return False
        try:
            lifecycle_id = self._refresh_lifecycle()
            now_tick = self._now_tick()
            if not self._runtime_gate():
                self._emit_diagnostic("runtime_gate", ("not_ready",))
                return False
            if (
                self._last_decision_tick is not None
                and now_tick >= self._last_decision_tick
                and now_tick - self._last_decision_tick < DECISION_INTERVAL_MS
            ):
                return False
            self._last_decision_tick = now_tick
            try:
                if not self.CanCastSkillID(self.energy_surge_id):
                    self._emit_diagnostic("runtime_gate", ("can_cast",))
                    return False
            except Exception:
                self._emit_diagnostic("runtime_gate", ("can_cast",))
                return False

            params = self._resolve_runtime_parameters()
            if params is None:
                self._emit_diagnostic("decision_rejected", ("live_data",))
                return False
            self._focus_aoe_radius = params.aoe_radius
            context = self._local_owner_context()
            if context is None:
                self._emit_diagnostic("decision_rejected", ("owner_context",))
                return False
            owner_email, group_id = context
            rows = self._read_raw_intents()
            if rows is None:
                self._emit_diagnostic("decision_rejected", ("raw_read",))
                return False
            _, projections = self._foreign_projections(
                rows,
                owner_email,
                group_id,
                now_tick,
                params,
                lifecycle_id[0],
            )
            snapshot_data = self._build_snapshot(params, lifecycle_id, now_tick)
            if snapshot_data is None:
                self._emit_diagnostic("decision_rejected", ("snapshot",))
                return False
            snapshot, enemies, distances = snapshot_data
            decision = evaluate_energy_surge(
                snapshot,
                enemies,
                aoe_radius=params.aoe_radius,
                cast_range=params.cast_range,
                group_link_radius=params.aoe_radius,
                local_resolved_drain=params.local_drain,
                reservations=projections,
                pairwise_distances=distances,
            )
            selected = self._focus_candidate(decision, snapshot, distances)
            if selected is None:
                self._emit_diagnostic(
                    "decision_rejected",
                    (str(decision.reason),),
                )
                return False
            self._emit_diagnostic(
                "decision_selected",
                (selected.target_agent_id, selected.expected_packet_damage),
            )
            return (
                yield from self._dispatch_selected(
                    selected.target_agent_id,
                    lifecycle_id,
                    params,
                )
            )
        except Exception:
            self._release_reservation("controller_exception")
            self._emit_diagnostic("decision_rejected", ("controller_exception",))
            return False


class LegacyEnergySurgeController(SmartEnergySurgeHandler):
    """Compatibility owner for callers that still load the old personal module."""

    def __init__(self, match_only: bool = False):
        super().__init__(match_only=match_only, standalone_fallback=True)


SUPPORTED_HANDLER_FACTORIES: dict[int, type[SmartEnergySurgeHandler]] = {}


def get_supported_handler_factories() -> dict[int, type[SmartEnergySurgeHandler]]:
    """Return the explicit D1A smart-handler registry."""

    skill_id = get_energy_surge_id()
    SUPPORTED_HANDLER_FACTORIES.clear()
    SUPPORTED_HANDLER_FACTORIES[skill_id] = SmartEnergySurgeHandler
    return dict(SUPPORTED_HANDLER_FACTORIES)


My_Energy_Surge = LegacyEnergySurgeController
EnergySurgeController = LegacyEnergySurgeController


__all__ = [
    "CandidateReason",
    "DECISION_INTERVAL_MS",
    "DAMAGE_PER_ENERGY",
    "DEFAULT_POLICY",
    "DecisionReason",
    "EnergySurgeController",
    "LegacyEnergySurgeController",
    "EnergySurgeCandidateEvaluation",
    "EnergySurgeDecision",
    "EnergySurgeEnemyObservation",
    "EnergySurgeGroupEvaluation",
    "EnergySurgePolicy",
    "ForeignReservationProjection",
    "FOCUS_CHALLENGER_STABILITY_MS",
    "FOCUS_GAP_GRACE_MS",
    "FOCUS_MINIMUM_OVERLAP_RATIO",
    "FOCUS_SWITCH_VALUE_RATIO",
    "LOW_HP_THRESHOLD",
    "MATCH_SCORE_BONUS",
    "MAXIMUM_FOREIGN_RESERVATIONS",
    "MINIMUM_EXPECTED_PACKET_DAMAGE",
    "My_Energy_Surge",
    "PROFESSION_MAX_ENERGY",
    "SUPPORTED_HANDLER_FACTORIES",
    "SmartEnergySurgeHandler",
    "UNKNOWN_MAX_ENERGY",
    "Energy_Surge_ID",
    "evaluate_energy_surge",
    "get_energy_surge_id",
    "get_supported_handler_factories",
    "infer_max_energy",
]
