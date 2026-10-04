"""Pure target/value policy and guarded handler for PvE Shatter Hex."""

from __future__ import annotations

import math
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from enum import IntEnum
from typing import TYPE_CHECKING
from typing import Any
from typing import Final

from Py4GWCoreLib.BuildMgr import BuildMgr

if TYPE_CHECKING:
    from Py4GWCoreLib.GlobalCache.shared_memory_src.AllAccounts import HexRemovalClaimToken

SHATTER_HEX_SKILL_ID: Final[int] = 67
SHATTER_HEX_NAME: Final[str] = "Shatter_Hex"
LOW_SPLASH_MINIMUM_DAMAGE: Final[float] = 90.0
CLAIM_ACTIVATION_MULTIPLIER: Final[float] = 2.5
MINIMUM_NATIVE_AFTERCAST_MS: Final[int] = 250
MINIMUM_OBSERVED_PING_MS: Final[int] = 150


class DecisionReason(str, Enum):
    SELECTED = "selected"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    INVALID_POLICY = "invalid_policy"
    INVALID_EVIDENCE = "invalid_evidence"


class CandidateReason(str, Enum):
    ELIGIBLE = "eligible"
    INVALID_TARGET = "invalid_target"
    NOT_HEXED = "not_hexed"
    NO_RETAINED_HEX = "no_retained_hex"
    NONE_PRIORITY = "none_priority"
    NOT_AFFORDABLE = "not_affordable"
    ENERGY_GATE = "energy_gate"
    INSUFFICIENT_SPLASH = "insufficient_splash"
    OUT_OF_CAST_RANGE = "out_of_cast_range"


class AdmissionLane(IntEnum):
    UNCLASSIFIED = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True, slots=True)
class HexRemovalEffectObservation:
    skill_id: int
    remaining_ms: float | None


@dataclass(frozen=True, slots=True)
class HexIdentityEvidence:
    confirmed_hex_count: int
    retained_hex_count: int
    priority: int | None


@dataclass(frozen=True, slots=True)
class ShatterHexPolicy:
    caster_x: float
    caster_y: float
    cast_range: float
    splash_radius: float
    nominal_damage: float | None
    energy_fraction: float
    current_energy: float
    maximum_energy: float
    effective_energy_cost: float
    affordable: bool


@dataclass(frozen=True, slots=True)
class ShatterHexAllyObservation:
    """Immutable facts for one current party ally eligible for cleanse."""

    agent_id: int
    x: float | None
    y: float | None
    health_fraction: float | None
    is_valid: bool | None
    is_living: bool | None
    is_alive: bool | None
    is_allied: bool | None
    is_party_member: bool | None
    is_hexed: bool | None
    target_is_allowed: bool | None
    confirmed_hex_count: int
    retained_hex_count: int
    hex_priority: int | None


@dataclass(frozen=True, slots=True)
class ShatterHexEnemyObservation:
    """Immutable health and geometry facts for one direct hostile recipient."""

    agent_id: int
    x: float | None
    y: float | None
    current_hp: float | None
    is_valid: bool | None
    is_living: bool | None
    is_alive: bool | None
    is_hostile: bool | None
    is_blacklisted: bool | None


@dataclass(frozen=True, slots=True)
class ShatterHexCandidateEvaluation:
    target_agent_id: int
    eligible: bool
    reason: CandidateReason
    cleanse_priority: int
    admission_lane: AdmissionLane | None
    useful_splash_damage: float
    ally_health_fraction: float | None
    caster_distance_squared: float | None


@dataclass(frozen=True, slots=True)
class ShatterHexDecision:
    selected: ShatterHexCandidateEvaluation | None
    reason: DecisionReason
    candidates: tuple[ShatterHexCandidateEvaluation, ...]

    @property
    def admitted(self) -> bool:
        return self.selected is not None

    @property
    def ranked_candidates(self) -> tuple[ShatterHexCandidateEvaluation, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.eligible)


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        integer = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return integer if integer > 0 and integer == value else None


def _invalid_decision(reason: DecisionReason) -> ShatterHexDecision:
    return ShatterHexDecision(selected=None, reason=reason, candidates=())


def resolve_shatter_hex_damage(domination_rank: int | None) -> float | None:
    """Return nominal 30 + 6 per Domination rank only for a valid rank."""

    if isinstance(domination_rank, bool) or not isinstance(domination_rank, int):
        return None
    if not 0 <= domination_rank <= 21:
        return None
    return float(30 + 6 * domination_rank)


def calculate_shatter_hex_claim_duration_ms(
    activation_ms: int,
    native_aftercast_ms: int,
    observed_ping_ms: int,
) -> int | None:
    """Compute the finite V1 lease from current activation, aftercast, and ping."""

    values = (activation_ms, native_aftercast_ms, observed_ping_ms)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
        return None
    duration = (
        math.ceil(activation_ms * CLAIM_ACTIVATION_MULTIPLIER)
        + max(native_aftercast_ms, MINIMUM_NATIVE_AFTERCAST_MS)
        + max(observed_ping_ms, MINIMUM_OBSERVED_PING_MS)
    )
    return duration if 0 < duration < 0x80000000 else None


def summarize_hex_identity_evidence(
    observations: Iterable[HexRemovalEffectObservation],
    *,
    classify_priority: Callable[[int], int],
    minimum_remaining_ms: int,
) -> HexIdentityEvidence:
    """Summarize observed identities without treating the list as complete."""

    try:
        entries = tuple(observations)
    except Exception:
        return HexIdentityEvidence(0, 0, None)

    remaining_by_skill: dict[int, list[float | None]] = {}
    for entry in entries:
        if not isinstance(entry, HexRemovalEffectObservation):
            continue
        skill_id = _positive_integer(entry.skill_id)
        if skill_id is None:
            continue
        remaining = _finite_float(entry.remaining_ms)
        remaining_by_skill.setdefault(skill_id, []).append(remaining)

    if not remaining_by_skill:
        return HexIdentityEvidence(0, 0, None)

    retained_skill_ids: list[int] = []
    for skill_id, durations in remaining_by_skill.items():
        if any(
            remaining is None or (remaining > 0.0 and remaining > float(minimum_remaining_ms))
            for remaining in durations
        ):
            retained_skill_ids.append(skill_id)
    retained_skill_ids.sort()

    if not retained_skill_ids:
        return HexIdentityEvidence(
            confirmed_hex_count=len(remaining_by_skill),
            retained_hex_count=0,
            priority=0,
        )

    priorities: list[int] = []
    for skill_id in retained_skill_ids:
        try:
            raw_priority = classify_priority(skill_id)
            if isinstance(raw_priority, bool):
                return HexIdentityEvidence(
                    len(remaining_by_skill),
                    len(retained_skill_ids),
                    None,
                )
            priority = int(raw_priority)
        except Exception:
            return HexIdentityEvidence(len(remaining_by_skill), len(retained_skill_ids), None)
        if priority not in (0, 1, 2, 3):
            return HexIdentityEvidence(len(remaining_by_skill), len(retained_skill_ids), None)
        priorities.append(priority)
    return HexIdentityEvidence(
        confirmed_hex_count=len(remaining_by_skill),
        retained_hex_count=len(retained_skill_ids),
        priority=max(priorities, default=0),
    )


def _valid_policy(policy: ShatterHexPolicy) -> bool:
    finite_values = (
        policy.caster_x,
        policy.caster_y,
        policy.cast_range,
        policy.splash_radius,
        policy.energy_fraction,
        policy.current_energy,
        policy.maximum_energy,
        policy.effective_energy_cost,
    )
    if any(_finite_float(value) is None for value in finite_values):
        return False
    if policy.nominal_damage is not None and _finite_float(policy.nominal_damage) is None:
        return False
    if (
        policy.cast_range <= 0.0
        or policy.splash_radius <= 0.0
        or not 0.0 <= policy.energy_fraction <= 1.0
        or policy.current_energy < 0.0
        or policy.maximum_energy <= 0.0
        or policy.effective_energy_cost < 0.0
        or (policy.nominal_damage is not None and policy.nominal_damage <= 0.0)
        or type(policy.affordable) is not bool
    ):
        return False
    return True


def _unique_allies(
    observations: Iterable[ShatterHexAllyObservation],
) -> tuple[ShatterHexAllyObservation, ...] | None:
    try:
        entries = tuple(observations)
    except Exception:
        return None
    if any(not isinstance(entry, ShatterHexAllyObservation) for entry in entries):
        return None
    grouped: dict[int, set[ShatterHexAllyObservation]] = {}
    for entry in entries:
        agent_id = _positive_integer(entry.agent_id)
        if agent_id is None:
            continue
        grouped.setdefault(agent_id, set()).add(entry)
    return tuple(next(iter(group)) for agent_id, group in sorted(grouped.items()) if len(group) == 1)


def _unique_enemies(
    observations: Iterable[ShatterHexEnemyObservation],
) -> tuple[ShatterHexEnemyObservation, ...] | None:
    try:
        entries = tuple(observations)
    except Exception:
        return None
    if any(not isinstance(entry, ShatterHexEnemyObservation) for entry in entries):
        return None
    grouped: dict[int, list[ShatterHexEnemyObservation]] = {}
    for entry in entries:
        agent_id = _positive_integer(entry.agent_id)
        if agent_id is not None:
            grouped.setdefault(agent_id, []).append(entry)

    unique: list[ShatterHexEnemyObservation] = []
    for agent_id, group in sorted(grouped.items()):
        if len(group) == 1:
            unique.append(group[0])
            continue
        positions: set[tuple[float, float]] = set()
        hit_points: list[float] = []
        malformed = False
        for entry in group:
            x = _finite_float(entry.x)
            y = _finite_float(entry.y)
            current_hp = _finite_float(entry.current_hp)
            if (
                entry.is_valid is not True
                or entry.is_living is not True
                or entry.is_alive is not True
                or entry.is_hostile is not True
                or entry.is_blacklisted is not False
                or x is None
                or y is None
                or current_hp is None
                or current_hp <= 0.0
            ):
                malformed = True
                break
            positions.add((x, y))
            hit_points.append(current_hp)
        if malformed or len(positions) != 1:
            continue
        position = next(iter(positions))
        unique.append(
            ShatterHexEnemyObservation(
                agent_id=agent_id,
                x=position[0],
                y=position[1],
                current_hp=min(hit_points),
                is_valid=True,
                is_living=True,
                is_alive=True,
                is_hostile=True,
                is_blacklisted=False,
            )
        )
    return tuple(unique)


def _enemy_is_usable(observation: ShatterHexEnemyObservation) -> bool:
    current_hp = _finite_float(observation.current_hp)
    return (
        _positive_integer(observation.agent_id) is not None
        and observation.is_valid is True
        and observation.is_living is True
        and observation.is_alive is True
        and observation.is_hostile is True
        and observation.is_blacklisted is False
        and _finite_float(observation.x) is not None
        and _finite_float(observation.y) is not None
        and current_hp is not None
        and current_hp > 0.0
    )


def _useful_splash_damage(
    ally: ShatterHexAllyObservation,
    enemies: tuple[ShatterHexEnemyObservation, ...],
    policy: ShatterHexPolicy,
) -> float:
    if policy.nominal_damage is None:
        return 0.0
    damage = float(policy.nominal_damage)
    radius_squared = float(policy.splash_radius) * float(policy.splash_radius)
    ally_x = _finite_float(ally.x)
    ally_y = _finite_float(ally.y)
    if ally_x is None or ally_y is None:
        return 0.0
    contributions: list[float] = []
    for enemy in enemies:
        if not _enemy_is_usable(enemy):
            continue
        enemy_x = _finite_float(enemy.x)
        enemy_y = _finite_float(enemy.y)
        current_hp = _finite_float(enemy.current_hp)
        if enemy_x is None or enemy_y is None or current_hp is None:
            continue
        delta_x = enemy_x - ally_x
        delta_y = enemy_y - ally_y
        if delta_x * delta_x + delta_y * delta_y <= radius_squared:
            contributions.append(min(damage, current_hp))
    return math.fsum(contributions)


def _candidate_evaluation(
    ally: ShatterHexAllyObservation,
    enemies: tuple[ShatterHexEnemyObservation, ...],
    policy: ShatterHexPolicy,
) -> ShatterHexCandidateEvaluation:
    agent_id = _positive_integer(ally.agent_id) or 0
    ally_x = _finite_float(ally.x)
    ally_y = _finite_float(ally.y)
    health_fraction = _finite_float(ally.health_fraction)
    missing_or_invalid = (
        ally.is_valid is not True
        or ally.is_living is not True
        or ally.is_alive is not True
        or ally.is_allied is not True
        or ally.is_party_member is not True
        or ally.target_is_allowed is not True
        or ally_x is None
        or ally_y is None
        or health_fraction is None
        or not 0.0 < health_fraction <= 1.0
    )
    if missing_or_invalid:
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.INVALID_TARGET, 0, None, 0.0, health_fraction, None
        )
    if ally_x is None or ally_y is None or health_fraction is None:
        return ShatterHexCandidateEvaluation(agent_id, False, CandidateReason.INVALID_TARGET, 0, None, 0.0, None, None)
    if ally.is_hexed is not True:
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.NOT_HEXED, 0, None, 0.0, health_fraction, None
        )
    delta_x = ally_x - float(policy.caster_x)
    delta_y = ally_y - float(policy.caster_y)
    distance_squared = delta_x * delta_x + delta_y * delta_y
    if not math.isfinite(distance_squared) or distance_squared > float(policy.cast_range) ** 2:
        return ShatterHexCandidateEvaluation(
            agent_id,
            False,
            CandidateReason.OUT_OF_CAST_RANGE,
            0,
            None,
            0.0,
            health_fraction,
            distance_squared if math.isfinite(distance_squared) else None,
        )
    if (
        type(ally.confirmed_hex_count) is not int
        or type(ally.retained_hex_count) is not int
        or (ally.hex_priority is not None and (type(ally.hex_priority) is not int or not 0 <= ally.hex_priority <= 3))
        or ally.confirmed_hex_count < 0
        or ally.retained_hex_count < 0
        or ally.retained_hex_count > ally.confirmed_hex_count
    ):
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.INVALID_TARGET, 0, None, 0.0, health_fraction, distance_squared
        )
    splash = _useful_splash_damage(ally, enemies, policy)
    if not policy.affordable or policy.current_energy < policy.effective_energy_cost:
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.NOT_AFFORDABLE, 0, None, splash, health_fraction, distance_squared
        )
    if ally.confirmed_hex_count > 0 and ally.retained_hex_count == 0:
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.NO_RETAINED_HEX, 0, None, splash, health_fraction, distance_squared
        )
    if ally.confirmed_hex_count > 0 and ally.hex_priority == 0:
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.NONE_PRIORITY, 0, None, splash, health_fraction, distance_squared
        )

    if ally.confirmed_hex_count == 0 or ally.hex_priority is None:
        lane = AdmissionLane.UNCLASSIFIED
        priority = 0
        energy_floor = 0.70
        requires_splash = True
    elif ally.hex_priority == 3:
        lane = AdmissionLane.HIGH
        priority = 3
        energy_floor = 0.0
        requires_splash = False
    elif ally.hex_priority == 2:
        lane = AdmissionLane.MEDIUM
        priority = 2
        energy_floor = 0.50
        requires_splash = False
    elif ally.hex_priority == 1:
        lane = AdmissionLane.LOW
        priority = 1
        energy_floor = 0.70
        requires_splash = True
    else:
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.INVALID_TARGET, 0, None, splash, health_fraction, distance_squared
        )

    if policy.energy_fraction < energy_floor:
        return ShatterHexCandidateEvaluation(
            agent_id, False, CandidateReason.ENERGY_GATE, priority, lane, splash, health_fraction, distance_squared
        )
    if requires_splash and splash < LOW_SPLASH_MINIMUM_DAMAGE:
        return ShatterHexCandidateEvaluation(
            agent_id,
            False,
            CandidateReason.INSUFFICIENT_SPLASH,
            priority,
            lane,
            splash,
            health_fraction,
            distance_squared,
        )
    return ShatterHexCandidateEvaluation(
        agent_id,
        True,
        CandidateReason.ELIGIBLE,
        priority,
        lane,
        splash,
        health_fraction,
        distance_squared,
    )


def _candidate_sort_key(
    candidate: ShatterHexCandidateEvaluation,
) -> tuple[int, float, float, float, int]:
    return (
        -candidate.cleanse_priority,
        -candidate.useful_splash_damage,
        math.inf if candidate.ally_health_fraction is None else candidate.ally_health_fraction,
        math.inf if candidate.caster_distance_squared is None else candidate.caster_distance_squared,
        candidate.target_agent_id,
    )


def evaluate_smart_shatter_hex(
    allies: Iterable[ShatterHexAllyObservation],
    enemies: Iterable[ShatterHexEnemyObservation],
    *,
    policy: ShatterHexPolicy,
) -> ShatterHexDecision:
    """Return a deterministic cleanse decision without reading runtime state."""

    if not isinstance(policy, ShatterHexPolicy) or not _valid_policy(policy):
        return _invalid_decision(DecisionReason.INVALID_POLICY)
    unique_allies = _unique_allies(allies)
    unique_enemies = _unique_enemies(enemies)
    if unique_allies is None or unique_enemies is None:
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)

    evaluations = tuple(_candidate_evaluation(ally, unique_enemies, policy) for ally in unique_allies)
    ranked = tuple(
        sorted(
            evaluations,
            key=lambda candidate: (
                not candidate.eligible,
                *_candidate_sort_key(candidate),
            ),
        )
    )
    eligible = tuple(candidate for candidate in ranked if candidate.eligible)
    return ShatterHexDecision(
        selected=eligible[0] if eligible else None,
        reason=DecisionReason.SELECTED if eligible else DecisionReason.NO_ELIGIBLE_CANDIDATE,
        candidates=ranked,
    )


def _position(value: Any) -> tuple[float, float] | None:
    try:
        if value is None or len(value) < 2:
            return None
        x = _finite_float(value[0])
        y = _finite_float(value[1])
    except (IndexError, TypeError, ValueError):
        return None
    if x is None or y is None:
        return None
    return x, y


def _duration_to_ms(value: Any) -> int | None:
    seconds = _finite_float(value)
    if seconds is None or seconds < 0.0:
        return None
    return int(round(seconds * 1000.0))


@dataclass(frozen=True, slots=True)
class _RuntimeParameters:
    policy: ShatterHexPolicy
    claim_duration_ms: int
    local_dispatch_duration_ms: int


@dataclass(slots=True)
class _PendingShatterAttempt:
    attempt_generation: int
    composition_generation: int
    map_id: int
    player_agent_id: int
    instance_uptime_ms: int
    owner_email: str
    isolation_group_id: int
    slot_index: int
    target_agent_id: int
    admission_lane: AdmissionLane
    claim_token: HexRemovalClaimToken
    state: str = "queued"


class SmartShatterHex(BuildMgr):
    """My Mesmer-owned Shatter Hex handler with one bounded shared attempt."""

    def __init__(self, match_only: bool = False, *, skill_id: int | None = None) -> None:
        from Py4GWCoreLib import Profession

        resolved_skill_id = int(skill_id or SHATTER_HEX_SKILL_ID)
        if resolved_skill_id != SHATTER_HEX_SKILL_ID:
            raise ValueError("SmartShatterHex only supports PvE Shatter Hex 67")
        self._skill_id = resolved_skill_id
        super().__init__(
            name="Smart Shatter Hex",
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
        self._attempt_generation = 0
        self._pending_attempt: _PendingShatterAttempt | None = None
        self._last_lifecycle_inputs: tuple[int, int, int, str, int] | None = None

    @property
    def skill_id(self) -> int:
        return self._skill_id

    @property
    def skill_slot(self) -> int | None:
        return self._skill_slot

    def set_skill_slot(self, slot_index: int | None) -> None:
        if slot_index is None:
            next_slot = None
        else:
            slot = int(slot_index)
            next_slot = slot if 1 <= slot <= 8 else None
        if next_slot != getattr(self, "_skill_slot", None):
            self.cancel_pending("skill_slot_changed")
        self._skill_slot = next_slot

    def update_lifecycle(self, context: Any = None) -> None:
        if getattr(self, "_disposed", True):
            return
        if context is not None:
            try:
                generation = int(context)
            except (TypeError, ValueError, OverflowError):
                self.cancel_pending("invalid_composition_generation")
                return
            previous_generation = getattr(self, "_composition_generation", None)
            if previous_generation is not None and generation != previous_generation:
                self.cancel_pending("composition_changed")
            self._composition_generation = generation

        lifecycle_inputs = self._read_lifecycle_inputs()
        if lifecycle_inputs is None:
            self.cancel_pending("lifecycle_unavailable")
            return
        previous = getattr(self, "_last_lifecycle_inputs", None)
        if previous is not None:
            reset = (
                previous[0] != lifecycle_inputs[0]
                or previous[1] != lifecycle_inputs[1]
                or previous[3] != lifecycle_inputs[3]
                or previous[4] != lifecycle_inputs[4]
                or lifecycle_inputs[2] < previous[2]
            )
            if reset:
                self.cancel_pending("lifecycle_changed")
        self._last_lifecycle_inputs = lifecycle_inputs
        if self._pending_attempt is not None and self._pending_attempt.state == "queued":
            if not self._runtime_gate():
                self.cancel_pending("runtime_gate_closed")
                return
            if self._resolve_current_slot() != self._pending_attempt.slot_index:
                self.cancel_pending("equipped_slot_changed")

    def try_cast(self):
        if False:
            yield
        if getattr(self, "_disposed", True) or self.has_active_dispatch():
            return False
        if self._composition_generation is None:
            return False
        if not self._runtime_gate():
            return False
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot, at_execution=False):
            return False
        parameters = self._resolve_runtime_parameters()
        if parameters is None:
            return False
        snapshot = self._build_snapshot(parameters)
        if snapshot is None:
            return False
        decision = evaluate_smart_shatter_hex(
            snapshot[0],
            snapshot[1],
            policy=parameters.policy,
        )
        if not decision.ranked_candidates:
            return False

        lifecycle_inputs = self._read_lifecycle_inputs()
        if lifecycle_inputs is None:
            return False
        from Py4GWCoreLib.GlobalCache.WhiteboardLocks import try_acquire_hex_removal_claim

        for candidate in decision.ranked_candidates:
            token = try_acquire_hex_removal_claim(
                candidate.target_agent_id,
                parameters.claim_duration_ms,
            )
            if token is None:
                continue
            self._attempt_generation += 1
            attempt = _PendingShatterAttempt(
                attempt_generation=self._attempt_generation,
                composition_generation=self._composition_generation,
                map_id=lifecycle_inputs[0],
                player_agent_id=lifecycle_inputs[1],
                instance_uptime_ms=lifecycle_inputs[2],
                owner_email=lifecycle_inputs[3],
                isolation_group_id=lifecycle_inputs[4],
                slot_index=slot,
                target_agent_id=candidate.target_agent_id,
                admission_lane=candidate.admission_lane or AdmissionLane.UNCLASSIFIED,
                claim_token=token,
            )
            self._pending_attempt = attempt
            validated = self._revalidate_selected(attempt, at_execution=False)
            if not validated:
                self._abort_pre_send(attempt)
                continue
            if not self._enqueue_guarded(attempt):
                self._abort_pre_send(attempt)
                return False
            return True
        return False

    def has_active_dispatch(self) -> bool:
        attempt = getattr(self, "_pending_attempt", None)
        if attempt is None:
            return False
        if attempt.state == "queued":
            try:
                from Py4GWCoreLib.GlobalCache.WhiteboardLocks import hex_removal_claim_is_owned

                if hex_removal_claim_is_owned(attempt.claim_token):
                    return True
            except Exception:
                pass
            self.cancel_pending("claim_expired_or_lost")
            return False
        if attempt.state == "sent":
            try:
                if self._is_local_cast_pending():
                    return True
            except Exception:
                return True
            self._pending_attempt = None
        return False

    def cancel_pending(self, _reason: str) -> None:
        attempt = getattr(self, "_pending_attempt", None)
        self._attempt_generation = getattr(self, "_attempt_generation", 0) + 1
        self._pending_attempt = None
        if attempt is not None and attempt.state == "queued":
            self._release_claim(attempt.claim_token)

    def dispose(self, reason: str = "handler_disposed") -> None:
        if not getattr(self, "_disposed", True):
            self.cancel_pending(reason)
            self._disposed = True

    def OnContractActivated(self, cached_data: Any = None) -> None:
        self._disposed = False
        if cached_data is not None:
            self.set_cached_data(cached_data)

    @staticmethod
    def _read_lifecycle_inputs() -> tuple[int, int, int, str, int] | None:
        try:
            from Py4GWCoreLib import Map
            from Py4GWCoreLib import Player
            from Py4GWCoreLib.GlobalCache.WhiteboardLocks import get_hex_removal_owner_context

            map_id = int(Map.GetMapID() or 0)
            player_agent_id = int(Player.GetAgentID() or 0)
            uptime = int(Map.GetInstanceUptime() or 0)
            owner_email, group_id = get_hex_removal_owner_context()
            if map_id <= 0 or player_agent_id <= 0 or not owner_email or group_id <= 0:
                return None
            return map_id, player_agent_id, uptime, owner_email, group_id
        except Exception:
            return None

    def _runtime_gate(self) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import Map
            from Py4GWCoreLib import Player
            from Py4GWCoreLib import Routines

            if not Map.IsMapReady() or not Map.IsExplorable() or Map.IsInCinematic():
                return False
            if not Routines.Checks.Map.MapValid() or not Routines.Checks.Player.CanAct():
                return False
            player_id = int(Player.GetAgentID() or 0)
            if (
                player_id <= 0
                or not Agent.IsValid(player_id)
                or not Agent.IsLiving(player_id)
                or not Agent.IsAlive(player_id)
                or Agent.IsDead(player_id)
                or Agent.IsKnockedDown(player_id)
                or Agent.IsCasting(player_id)
            ):
                return False
            if int(GLOBAL_CACHE.SkillBar.GetCasting() or 0) != 0:
                return False
            return self._combat_option_enabled()
        except Exception:
            return False

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
        except Exception:
            return False

    def _resolve_current_slot(self) -> int | None:
        try:
            from Py4GWCoreLib.Skillbar import SkillBar

            slot = self._skill_slot
            if slot is None or not 1 <= slot <= 8:
                return None
            if int(SkillBar.GetSkillIDBySlot(slot) or 0) != self._skill_id:
                return None
            return slot
        except Exception:
            return None

    def _skill_readiness(self, slot: int, *, at_execution: bool) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Player
            from Py4GWCoreLib import Routines

            if (
                self._resolve_current_slot() != slot
                or not self._combat_option_enabled()
                or not self._skill_toggle_enabled(slot)
            ):
                return False
            if not at_execution and not bool(self.CanCastSkillSlot(slot)):
                return False
            can_cast = getattr(Routines.Checks.Skills, "CanCast", None)
            if not callable(can_cast) or not bool(can_cast()):
                return False
            skill_ready = getattr(Routines.Checks.Skills, "IsSkillSlotReady", None)
            if not callable(skill_ready) or not bool(skill_ready(slot)):
                return False
            has_enough_energy = getattr(Routines.Checks.Skills, "HasEnoughEnergy", None)
            if not callable(has_enough_energy) or not bool(has_enough_energy(Player.GetAgentID(), self._skill_id)):
                return False
            skill_data = GLOBAL_CACHE.SkillBar.GetSkillData(slot)
            recharge = _finite_float(getattr(skill_data, "recharge", None))
            if recharge != 0.0:
                return False
            return True
        except Exception:
            return False

    def _resolve_runtime_parameters(self) -> _RuntimeParameters | None:
        try:
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import Player
            from Py4GWCoreLib import Range
            from Py4GWCoreLib import Routines
            from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE

            player_id = int(Player.GetAgentID() or 0)
            if player_id <= 0:
                return None
            caster_position = _position(Player.GetXY())
            if caster_position is None:
                return None
            energy_fraction = _finite_float(Agent.GetEnergy(player_id))
            maximum_energy = _finite_float(Agent.GetMaxEnergy(player_id))
            if energy_fraction is None or maximum_energy is None or maximum_energy <= 0.0:
                return None
            current_energy = energy_fraction * maximum_energy
            cost_value = Routines.Checks.Skills.GetEnergyCostWithEffects(self._skill_id, player_id)
            effective_cost = _finite_float(cost_value)
            if effective_cost is None or effective_cost < 0.0:
                return None
            affordable_check = Routines.Checks.Skills.HasEnoughEnergy(player_id, self._skill_id)
            affordable = bool(affordable_check) and current_energy >= effective_cost

            rank = self._current_domination_rank(Agent, player_id)
            damage = resolve_shatter_hex_damage(rank)
            cast_range = _finite_float(getattr(Range.Spellcast, "value", None))
            splash_radius = _finite_float(getattr(Range.Nearby, "value", None))
            if cast_range is None or splash_radius is None:
                return None

            activation_ms = _duration_to_ms(GLOBAL_CACHE.Skill.Data.GetActivation(self._skill_id))
            native_aftercast_ms = _duration_to_ms(GLOBAL_CACHE.Skill.Data.GetAftercast(self._skill_id))
            if activation_ms is None or native_aftercast_ms is None:
                return None
            ping_ms = self._observed_ping_ms()
            claim_duration_ms = calculate_shatter_hex_claim_duration_ms(
                activation_ms,
                native_aftercast_ms,
                ping_ms,
            )
            if claim_duration_ms is None:
                return None
            local_dispatch_duration_ms = (
                activation_ms
                + max(native_aftercast_ms, MINIMUM_NATIVE_AFTERCAST_MS)
                + max(ping_ms, MINIMUM_OBSERVED_PING_MS)
            )

            policy = ShatterHexPolicy(
                caster_x=caster_position[0],
                caster_y=caster_position[1],
                cast_range=cast_range,
                splash_radius=splash_radius,
                nominal_damage=damage,
                energy_fraction=energy_fraction,
                current_energy=current_energy,
                maximum_energy=maximum_energy,
                effective_energy_cost=effective_cost,
                affordable=affordable,
            )
            if not _valid_policy(policy):
                return None
            return _RuntimeParameters(
                policy=policy,
                claim_duration_ms=claim_duration_ms,
                local_dispatch_duration_ms=local_dispatch_duration_ms,
            )
        except Exception:
            return None

    @staticmethod
    def _current_domination_rank(agent_api: Any, player_id: int) -> int | None:
        try:
            attributes = agent_api.GetAttributes(int(player_id))
        except Exception:
            return None
        for attribute in attributes or ():
            raw_attribute_id = getattr(attribute, "attribute_id", getattr(attribute, "Id", -1))
            try:
                if int(raw_attribute_id) != 2:
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            raw_rank = getattr(attribute, "level", getattr(attribute, "Value", None))
            rank = _finite_float(raw_rank)
            if rank is None or not rank.is_integer() or not 0 <= rank <= 21:
                return None
            return int(rank)
        return None

    @staticmethod
    def _observed_ping_ms() -> int:
        try:
            from Py4GWCoreLib.HeroAI.interrupt import _PING_HANDLER

            ping = _finite_float(_PING_HANDLER.GetCurrentPing())
            return 0 if ping is None or ping < 0.0 else int(math.ceil(ping))
        except Exception:
            return 0

    def _hex_identity_evidence(self, agent_id: int) -> HexIdentityEvidence:
        try:
            from Py4GWCoreLib.GlobalCache.HexRemovalPriority import MIN_HEX_REMAINING_MS_TO_REMOVE
            from Py4GWCoreLib.GlobalCache.HexRemovalPriority import classify_hex_for_removal
            from Py4GWCoreLib.GlobalCache.HexRemovalPriority import get_hex_removal_effect_observations

            effects = tuple(
                HexRemovalEffectObservation(int(skill_id), remaining_ms)
                for skill_id, remaining_ms in get_hex_removal_effect_observations(agent_id)
            )
            evidence = summarize_hex_identity_evidence(
                effects,
                classify_priority=lambda skill_id: int(classify_hex_for_removal(skill_id, agent_id)),
                minimum_remaining_ms=MIN_HEX_REMAINING_MS_TO_REMOVE,
            )
            return evidence
        except Exception:
            return HexIdentityEvidence(0, 0, None)

    @staticmethod
    def _is_allied(agent_api: Any, agent_id: int) -> bool:
        try:
            from Py4GWCoreLib.enums_src.GameData_enums import Allegiance

            raw_value = agent_api.GetAllegiance(agent_id)
            allegiance = raw_value[0] if isinstance(raw_value, (tuple, list)) else raw_value
            return int(allegiance) == int(Allegiance.Ally.value)
        except Exception:
            return False

    def _observe_ally(
        self,
        agent_id: int,
    ) -> ShatterHexAllyObservation:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Routines

        valid = False
        living = False
        alive = False
        allied = False
        party_member = False
        target_allowed = False
        position: tuple[float, float] | None = None
        health_fraction: float | None = None
        is_hexed = False
        evidence = HexIdentityEvidence(0, 0, None)
        try:
            valid = bool(Agent.IsValid(agent_id))
            living = valid and bool(Agent.IsLiving(agent_id))
            alive = living and bool(Agent.IsAlive(agent_id)) and not bool(Agent.IsDead(agent_id))
            allied = alive and self._is_allied(Agent, agent_id)
            party_member = allied and bool(Routines.Party.IsPartyMember(agent_id))
            if party_member:
                position = _position(Agent.GetXY(agent_id))
                health_fraction = _finite_float(Agent.GetHealth(agent_id))
                is_hexed = bool(Agent.IsHexed(agent_id))
                target_allowed = bool(self._validate_target_for_skill_cast(self._skill_id, agent_id))
                evidence = self._hex_identity_evidence(agent_id) if is_hexed else HexIdentityEvidence(0, 0, None)
        except Exception:
            pass
        return ShatterHexAllyObservation(
            agent_id=agent_id,
            x=None if position is None else position[0],
            y=None if position is None else position[1],
            health_fraction=health_fraction,
            is_valid=valid,
            is_living=living,
            is_alive=alive,
            is_allied=allied,
            is_party_member=party_member,
            is_hexed=is_hexed,
            target_is_allowed=target_allowed,
            confirmed_hex_count=evidence.confirmed_hex_count,
            retained_hex_count=evidence.retained_hex_count,
            hex_priority=evidence.priority,
        )

    @staticmethod
    def _is_direct_enemy(agent_api: Any, agent_id: int) -> bool:
        try:
            from Py4GWCoreLib.enums_src.GameData_enums import Allegiance

            raw_value = agent_api.GetAllegiance(agent_id)
            allegiance = raw_value[0] if isinstance(raw_value, (tuple, list)) else raw_value
            return int(allegiance) == int(Allegiance.Enemy.value)
        except Exception:
            return False

    def _observe_enemy(self, agent_id: int) -> ShatterHexEnemyObservation:
        from Py4GWCoreLib import Agent

        valid = False
        living = False
        alive = False
        hostile = False
        blacklisted = True
        position: tuple[float, float] | None = None
        current_hp: float | None = None
        try:
            valid = bool(Agent.IsValid(agent_id))
            living = valid and bool(Agent.IsLiving(agent_id))
            alive = living and bool(Agent.IsAlive(agent_id)) and not bool(Agent.IsDead(agent_id))
            hostile = alive and self._is_direct_enemy(Agent, agent_id)
            if hostile:
                position = _position(Agent.GetXY(agent_id))
                health_fraction = _finite_float(Agent.GetHealth(agent_id))
                maximum_health = _finite_float(Agent.GetMaxHealth(agent_id))
                if (
                    health_fraction is not None
                    and 0.0 < health_fraction <= 1.0
                    and maximum_health is not None
                    and maximum_health > 0.0
                ):
                    current_hp = health_fraction * maximum_health
                try:
                    blacklisted = bool(self._is_blacklisted_enemy(agent_id))
                except Exception:
                    blacklisted = True
        except Exception:
            pass
        return ShatterHexEnemyObservation(
            agent_id=agent_id,
            x=None if position is None else position[0],
            y=None if position is None else position[1],
            current_hp=current_hp,
            is_valid=valid,
            is_living=living,
            is_alive=alive,
            is_hostile=hostile,
            is_blacklisted=blacklisted,
        )

    def _build_enemy_snapshot(self) -> tuple[ShatterHexEnemyObservation, ...] | None:
        from Py4GWCoreLib import AgentArray

        try:
            raw_ids: list[Any] = []
            raw_ids.extend(AgentArray.GetEnemyArray() or ())
            raw_ids.extend(AgentArray.GetSpiritPetArray() or ())
            raw_ids.extend(AgentArray.GetMinionArray() or ())
        except Exception:
            return None
        seen_ids: set[int] = set()
        observations: list[ShatterHexEnemyObservation] = []
        for raw_agent_id in raw_ids:
            agent_id = _positive_integer(raw_agent_id)
            if agent_id is None or agent_id in seen_ids:
                continue
            seen_ids.add(agent_id)
            observations.append(self._observe_enemy(agent_id))
        return tuple(sorted(observations, key=lambda observation: observation.agent_id))

    def _build_snapshot(
        self,
        parameters: _RuntimeParameters,
        *,
        selected_agent_id: int | None = None,
    ) -> tuple[tuple[ShatterHexAllyObservation, ...], tuple[ShatterHexEnemyObservation, ...]] | None:
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Routines

        if selected_agent_id is not None:
            raw_ally_ids: tuple[Any, ...] = (selected_agent_id,)
        else:
            try:
                discovered = list(AgentArray.GetAllyArray() or ())
            except Exception:
                return None
            self_id = int(Player.GetAgentID() or 0)
            if self_id > 0:
                discovered.append(self_id)
            raw_ally_ids = tuple(discovered)

        seen_ids: set[int] = set()
        allies: list[ShatterHexAllyObservation] = []
        for raw_agent_id in raw_ally_ids:
            agent_id = _positive_integer(raw_agent_id)
            if agent_id is None or agent_id in seen_ids:
                continue
            seen_ids.add(agent_id)
            if selected_agent_id is None:
                try:
                    if not Routines.Party.IsPartyMember(agent_id):
                        continue
                except Exception:
                    continue
            allies.append(self._observe_ally(agent_id))

        enemies = self._build_enemy_snapshot()
        if enemies is None:
            return None
        return tuple(allies), enemies

    def _revalidate_selected(
        self,
        attempt: _PendingShatterAttempt,
        *,
        at_execution: bool,
    ) -> _RuntimeParameters | None:
        if not self._attempt_is_current(attempt):
            return None
        if not self._runtime_gate():
            return None
        if self._resolve_current_slot() != attempt.slot_index:
            return None
        if not self._skill_readiness(attempt.slot_index, at_execution=at_execution):
            return None
        parameters = self._resolve_runtime_parameters()
        if parameters is None:
            return None
        snapshot = self._build_snapshot(parameters, selected_agent_id=attempt.target_agent_id)
        if snapshot is None:
            return None
        decision = evaluate_smart_shatter_hex(snapshot[0], snapshot[1], policy=parameters.policy)
        selected = decision.selected
        if selected is None or selected.target_agent_id != attempt.target_agent_id:
            return None
        if not at_execution:
            try:
                from Py4GWCoreLib.GlobalCache.WhiteboardLocks import hex_removal_claim_is_owned

                if not hex_removal_claim_is_owned(attempt.claim_token):
                    return None
            except Exception:
                return None
        return parameters

    def _attempt_is_current(self, attempt: _PendingShatterAttempt) -> bool:
        if (
            getattr(self, "_disposed", True)
            or self._pending_attempt is not attempt
            or attempt.attempt_generation != self._attempt_generation
            or attempt.composition_generation != self._composition_generation
            or attempt.state != "queued"
        ):
            return False
        lifecycle_inputs = self._read_lifecycle_inputs()
        if lifecycle_inputs is None:
            return False
        return (
            lifecycle_inputs[0] == attempt.map_id
            and lifecycle_inputs[1] == attempt.player_agent_id
            and lifecycle_inputs[2] >= attempt.instance_uptime_ms
            and lifecycle_inputs[3] == attempt.owner_email
            and lifecycle_inputs[4] == attempt.isolation_group_id
        )

    def _enqueue_guarded(self, attempt: _PendingShatterAttempt) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE

            queue_guard = getattr(GLOBAL_CACHE.SkillBar, "QueueGuardedUseSkill", None)
            if not callable(queue_guard):
                return False
            result = queue_guard(
                lambda native_use_skill: self._execute_queued_guard(
                    attempt,
                    native_use_skill,
                )
            )
            return result is not False
        except Exception:
            return False

    def _execute_queued_guard(
        self,
        attempt: _PendingShatterAttempt,
        native_use_skill: Callable[[int, int], Any],
    ) -> bool:
        parameters = self._revalidate_selected(attempt, at_execution=True)
        if parameters is None:
            self._abort_pre_send(attempt)
            return False
        try:
            from Py4GWCoreLib.GlobalCache.WhiteboardLocks import renew_hex_removal_claim

            renewed_token = renew_hex_removal_claim(
                attempt.claim_token,
                parameters.claim_duration_ms,
            )
        except Exception:
            renewed_token = None
        if renewed_token is None:
            self._abort_pre_send(attempt)
            return False

        attempt.claim_token = renewed_token
        attempt.state = "sent"
        try:
            self._mark_local_cast_pending(parameters.local_dispatch_duration_ms)
        except Exception:
            pass
        try:
            native_use_skill(attempt.slot_index, attempt.target_agent_id)
        except Exception:
            # The native boundary was entered; keep the finite shared lease.
            return False
        return True

    def _abort_pre_send(self, attempt: _PendingShatterAttempt) -> None:
        if self._pending_attempt is attempt and attempt.state == "queued":
            self._pending_attempt = None
            self._attempt_generation += 1
        if attempt.state == "queued":
            self._release_claim(attempt.claim_token)

    @staticmethod
    def _release_claim(token: HexRemovalClaimToken) -> None:
        try:
            from Py4GWCoreLib.GlobalCache.WhiteboardLocks import release_hex_removal_claim

            release_hex_removal_claim(token)
        except Exception:
            return


__all__ = [
    "AdmissionLane",
    "CLAIM_ACTIVATION_MULTIPLIER",
    "CandidateReason",
    "DecisionReason",
    "HexIdentityEvidence",
    "HexRemovalEffectObservation",
    "LOW_SPLASH_MINIMUM_DAMAGE",
    "MINIMUM_NATIVE_AFTERCAST_MS",
    "MINIMUM_OBSERVED_PING_MS",
    "SHATTER_HEX_NAME",
    "SHATTER_HEX_SKILL_ID",
    "ShatterHexAllyObservation",
    "ShatterHexCandidateEvaluation",
    "ShatterHexDecision",
    "ShatterHexEnemyObservation",
    "ShatterHexPolicy",
    "SmartShatterHex",
    "calculate_shatter_hex_claim_duration_ms",
    "evaluate_smart_shatter_hex",
    "resolve_shatter_hex_damage",
    "summarize_hex_identity_evidence",
]
