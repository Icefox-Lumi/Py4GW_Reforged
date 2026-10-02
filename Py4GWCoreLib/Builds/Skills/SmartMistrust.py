"""Pure PvE Mistrust policy and its guarded My Mesmer runtime handler."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Generator
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import replace
from enum import Enum
from typing import Any
from typing import Final
from typing import cast

from Py4GWCoreLib.BuildMgr import BuildMgr

MISTRUST_SKILL_ID: Final[int] = 979
MISTRUST_NAME: Final[str] = "Mistrust"
MISTRUST_CAST_RANGE: Final[float] = 1248.0
MISTRUST_SPLASH_RADIUS: Final[float] = 240.0
MISTRUST_HISTORY_WINDOW_MS: Final[int] = 6000
MISTRUST_REACTIVE_EVENT_MAX_AGE_MS: Final[int] = 150
MISTRUST_FAST_CASTING_ATTRIBUTE_ID: Final[int] = 0
MISTRUST_DOMINATION_ATTRIBUTE_ID: Final[int] = 2
MISTRUST_PROFESSION_MESMER_ID: Final[int] = 5
INTERRUPT_TARGET_KIND_ID: Final[int] = 11
MISTRUST_SCALE_RANK_ZERO: Final[float] = 10.0
MISTRUST_SCALE_RANK_FIFTEEN: Final[float] = 80.0
MISTRUST_QUEUE_ALLOWANCE_MS: Final[int] = 150
MISTRUST_FRAME_ALLOWANCE_MS: Final[int] = 50
MISTRUST_SAFETY_ALLOWANCE_MS: Final[int] = 250
_UINT32_MASK: Final[int] = 0xFFFFFFFF
_UINT32_HALF_RANGE: Final[int] = 0x80000000


def _intent_tick_elapsed(now_tick: int, then_tick: int) -> int:
    """Match IntentSync's uint32 timestamp age without initializing the runtime package."""

    return ((int(now_tick) & _UINT32_MASK) - (int(then_tick) & _UINT32_MASK)) & _UINT32_MASK


def _intent_tick_is_expired(now_tick: int, expires_at_tick: int) -> bool:
    """Match IntentSync's expired/deadline half-range rule for read-only claim matching."""

    remaining = ((int(expires_at_tick) & _UINT32_MASK) - (int(now_tick) & _UINT32_MASK)) & _UINT32_MASK
    return remaining == 0 or remaining >= _UINT32_HALF_RANGE


class DecisionReason(str, Enum):
    SELECTED = "selected"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
    INVALID_POLICY = "invalid_policy"
    INVALID_EVIDENCE = "invalid_evidence"


class CandidateReason(str, Enum):
    ELIGIBLE = "eligible"
    INVALID_TARGET = "invalid_target"
    INVALID_EVIDENCE = "invalid_evidence"
    MISSING_EVIDENCE = "missing_evidence"
    OUT_OF_CAST_RANGE = "out_of_cast_range"
    BELOW_MINIMUM_VALUE = "below_minimum_value"
    INVALID_MODE = "invalid_mode"
    INVALID_TIMING = "invalid_timing"


class MistrustMode(str, Enum):
    REACTIVE = "reactive"
    PROACTIVE = "proactive"


@dataclass(frozen=True, slots=True)
class MistrustPolicy:
    """Immutable damage and geometry policy for one Mistrust evaluation."""

    primary_damage: float
    splash_damage: float
    cast_range: float = MISTRUST_CAST_RANGE
    splash_radius: float = MISTRUST_SPLASH_RADIUS

    @classmethod
    def from_domination_rank(
        cls,
        domination_rank: int | None,
        scale: Any,
    ) -> "MistrustPolicy | None":
        damage = resolve_mistrust_damage(domination_rank, scale)
        if damage is None:
            return None
        return cls(
            primary_damage=float(damage[0]),
            splash_damage=float(damage[1]),
        )


@dataclass(frozen=True, slots=True)
class MistrustTargetObservation:
    """Immutable live facts for a possible Mistrust primary or splash target."""

    agent_id: int
    x: float | None
    y: float | None
    current_hp: float | None
    distance_from_player: float | None
    is_valid: bool | None = True
    is_alive: bool | None = True
    is_hostile: bool | None = True
    is_targetable: bool | None = True

    def __post_init__(self) -> None:
        if type(self.agent_id) is not int:
            raise TypeError("agent_id must be an integer")
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("current_hp", self.current_hp),
            ("distance_from_player", self.distance_from_player),
        ):
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite when supplied")
        for name, value in (
            ("is_valid", self.is_valid),
            ("is_alive", self.is_alive),
            ("is_hostile", self.is_hostile),
            ("is_targetable", self.is_targetable),
        ):
            if value is not None and type(value) is not bool:
                raise TypeError(f"{name} must be a bool or None")

    @property
    def position(self) -> tuple[float, float] | None:
        if self.x is None or self.y is None:
            return None
        return float(self.x), float(self.y)


@dataclass(frozen=True, slots=True)
class MistrustOpportunity:
    """One policy opportunity, already classified as reactive or proactive."""

    mode: MistrustMode
    primary: MistrustTargetObservation
    splash_targets: tuple[MistrustTargetObservation, ...] = ()
    timing_slack_ms: int | None = None
    most_recent_history_ms: int | None = None
    reactive_profession_evidence: _EnemyProfessionEvidence | None = None


@dataclass(frozen=True, slots=True)
class MistrustCandidateEvaluation:
    """Admission and useful HP-capped value for one opportunity."""

    target_agent_id: int
    mode: MistrustMode | None
    eligible: bool
    reason: CandidateReason
    useful_primary_damage: float
    useful_splash_damage: float
    useful_damage: float
    splash_agent_ids: tuple[int, ...]
    distance_from_player: float | None
    timing_slack_ms: int | None
    most_recent_history_ms: int | None
    reactive_profession_evidence: _EnemyProfessionEvidence | None = None

    @property
    def primary_agent_id(self) -> int:
        return self.target_agent_id

    @property
    def useful_delivered_damage(self) -> float:
        return self.useful_damage


@dataclass(frozen=True, slots=True)
class MistrustDecision:
    """Pure policy result; it performs no runtime or native action."""

    selected: MistrustCandidateEvaluation | None
    reason: DecisionReason
    candidates: tuple[MistrustCandidateEvaluation, ...]

    @property
    def admitted(self) -> bool:
        return self.selected is not None

    @property
    def selected_target_agent_id(self) -> int | None:
        return None if self.selected is None else self.selected.target_agent_id

    @property
    def ranked_candidates(self) -> tuple[MistrustCandidateEvaluation, ...]:
        return self.candidates


@dataclass(frozen=True, slots=True)
class SkillActivationRecord:
    """Retained identity for one enemy SKILL_ACTIVATED observation."""

    enemy_agent_id: int
    skill_id: int
    onset_ms: int
    target_id: int
    first_observed_ms: int
    terminal_ms: int | None = None

    @property
    def identity(self) -> tuple[int, int, int, int]:
        return self.enemy_agent_id, self.skill_id, self.onset_ms, self.target_id


@dataclass(frozen=True, slots=True)
class _EnemyProfessionEvidence:
    model_index: int
    model_primary: int
    living_primary: int | None


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


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


def _invalid_decision(reason: DecisionReason) -> MistrustDecision:
    return MistrustDecision(selected=None, reason=reason, candidates=())


def _valid_policy(policy: MistrustPolicy) -> bool:
    values = (
        policy.primary_damage,
        policy.splash_damage,
        policy.cast_range,
        policy.splash_radius,
    )
    return all(math.isfinite(float(value)) and float(value) > 0.0 for value in values)


def _valid_mode(value: Any) -> MistrustMode | None:
    if isinstance(value, MistrustMode):
        return value
    try:
        return MistrustMode(str(value))
    except ValueError:
        return None


def resolve_mistrust_damage(
    domination_rank: int | None,
    scale: Any,
) -> tuple[int, int] | None:
    """Resolve live Mistrust endpoints using the documented linear scaling."""

    rank = _valid_rank(domination_rank)
    if rank is None:
        return None
    try:
        if isinstance(scale, (str, bytes)) or len(scale) < 2:
            return None
        rank_zero = _finite_float(scale[0])
        rank_fifteen = _finite_float(scale[1])
    except (IndexError, TypeError, ValueError):
        return None
    if (
        rank_zero is None
        or rank_fifteen is None
        or rank_zero != MISTRUST_SCALE_RANK_ZERO
        or rank_fifteen != MISTRUST_SCALE_RANK_FIFTEEN
    ):
        return None
    primary = math.floor(rank_zero + (rank_fifteen - rank_zero) * rank / 15.0 + 0.5)
    splash = math.floor(0.75 * primary)
    if primary <= 0 or splash <= 0:
        return None
    return int(primary), int(splash)


def calculate_local_mistrust_activation_ms(
    base_activation_seconds: Any,
    fast_casting_rank: int | None,
) -> int | None:
    """Calculate local Mistrust activation without the Spell-only helper."""

    rank = _valid_rank(fast_casting_rank)
    base_seconds = _finite_float(base_activation_seconds)
    if rank is None or base_seconds is None or base_seconds <= 0.0:
        return None
    rounded_seconds = round(base_seconds * (0.955**rank), 3)
    result = math.ceil(1000.0 * rounded_seconds)
    return result if result > 0 else None


def qualifies_mistrust_skill_type(skill_type: Any) -> bool:
    """Return whether the exact V1 Spell/Hex evidence type is admissible."""

    type_name = getattr(skill_type, "name", skill_type)
    return str(type_name).strip() in {"Spell", "Hex"}


def is_confirmed_direct_party_target(
    enemy_agent_id: int,
    target_id: int,
    party_membership: bool | None,
) -> bool:
    """Apply the pure identity part of the direct-target admission rule."""

    return (
        int(enemy_agent_id) > 0
        and int(target_id) > 0
        and int(enemy_agent_id) != int(target_id)
        and party_membership is True
    )


def calculate_reactive_reserve_ms(current_ping_ms: Any) -> int | None:
    ping = _finite_float(current_ping_ms)
    if ping is None or ping < 0.0:
        return None
    return (
        MISTRUST_QUEUE_ALLOWANCE_MS + MISTRUST_FRAME_ALLOWANCE_MS + math.ceil(1.2 * ping) + MISTRUST_SAFETY_ALLOWANCE_MS
    )


def estimate_enemy_remaining_ms(
    base_activation_seconds: Any,
    dispatch_now_ms: Any,
    retained_onset_ms: Any,
) -> int | None:
    base_seconds = _finite_float(base_activation_seconds)
    now_ms = _finite_integer(dispatch_now_ms)
    onset_ms = _finite_integer(retained_onset_ms)
    if base_seconds is None or base_seconds <= 0.0 or now_ms is None or onset_ms is None or now_ms < onset_ms:
        return None
    return math.floor(1000.0 * base_seconds) - (now_ms - onset_ms)


def reactive_timing_slack_ms(
    *,
    enemy_base_activation_seconds: Any,
    dispatch_now_ms: Any,
    retained_onset_ms: Any,
    local_mistrust_est_ms: Any,
    current_ping_ms: Any,
) -> int | None:
    remaining_ms = estimate_enemy_remaining_ms(
        enemy_base_activation_seconds,
        dispatch_now_ms,
        retained_onset_ms,
    )
    local_ms = _finite_integer(local_mistrust_est_ms)
    reserve_ms = calculate_reactive_reserve_ms(current_ping_ms)
    if remaining_ms is None or local_ms is None or local_ms <= 0 or reserve_ms is None:
        return None
    slack = remaining_ms - local_ms - reserve_ms
    return slack if remaining_ms > local_ms + reserve_ms else None


def _candidate_result(
    opportunity: MistrustOpportunity,
    *,
    reason: CandidateReason,
) -> MistrustCandidateEvaluation:
    mode = _valid_mode(opportunity.mode)
    return MistrustCandidateEvaluation(
        target_agent_id=opportunity.primary.agent_id,
        mode=mode,
        eligible=False,
        reason=reason,
        useful_primary_damage=0.0,
        useful_splash_damage=0.0,
        useful_damage=0.0,
        splash_agent_ids=(),
        distance_from_player=opportunity.primary.distance_from_player,
        timing_slack_ms=opportunity.timing_slack_ms,
        most_recent_history_ms=opportunity.most_recent_history_ms,
        reactive_profession_evidence=opportunity.reactive_profession_evidence,
    )


def _primary_reason(
    observation: MistrustTargetObservation,
    policy: MistrustPolicy,
) -> CandidateReason:
    if observation.agent_id <= 0 or any(
        value is False
        for value in (
            observation.is_valid,
            observation.is_alive,
            observation.is_hostile,
            observation.is_targetable,
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
            observation.is_valid,
            observation.is_alive,
            observation.is_hostile,
            observation.is_targetable,
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


def _splash_is_eligible(
    observation: MistrustTargetObservation,
    primary: MistrustTargetObservation,
    *,
    radius_squared: float,
) -> bool:
    if observation.agent_id <= 0 or observation.agent_id == primary.agent_id:
        return False
    if any(
        value is not True
        for value in (
            observation.is_valid,
            observation.is_alive,
            observation.is_hostile,
            observation.is_targetable,
        )
    ):
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
    return delta_x * delta_x + delta_y * delta_y <= radius_squared


def _candidate_sort_key(
    candidate: MistrustCandidateEvaluation,
) -> tuple[int, int, float, float, float, int]:
    mode_rank = 0 if candidate.mode is MistrustMode.REACTIVE else 1
    timing_rank = (
        -float(candidate.timing_slack_ms)
        if candidate.mode is MistrustMode.REACTIVE and candidate.timing_slack_ms is not None
        else 0.0
    )
    history_rank = (
        -float(candidate.most_recent_history_ms)
        if candidate.mode is MistrustMode.PROACTIVE and candidate.most_recent_history_ms is not None
        else 0.0
    )
    return (
        0 if candidate.eligible else 1,
        mode_rank,
        -candidate.useful_damage,
        timing_rank,
        history_rank,
        candidate.target_agent_id,
    )


def evaluate_smart_mistrust(
    opportunities: Iterable[object],
    *,
    policy: object | None = None,
) -> MistrustDecision:
    """Select one useful Mistrust opportunity deterministically."""

    if policy is None or not isinstance(policy, MistrustPolicy) or not _valid_policy(policy):
        return _invalid_decision(DecisionReason.INVALID_POLICY)
    try:
        supplied_objects = tuple(opportunities)
    except Exception:
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    if any(not isinstance(opportunity, MistrustOpportunity) for opportunity in supplied_objects):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    supplied = cast(tuple[MistrustOpportunity, ...], supplied_objects)
    opportunity_keys = {(opportunity.primary.agent_id, _valid_mode(opportunity.mode)) for opportunity in supplied}
    if len(opportunity_keys) != len(supplied):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)

    evaluations: list[MistrustCandidateEvaluation] = []
    radius_squared = float(policy.splash_radius) * float(policy.splash_radius)
    for opportunity in sorted(supplied, key=lambda item: item.primary.agent_id):
        mode = _valid_mode(opportunity.mode)
        if mode is None:
            evaluations.append(_candidate_result(opportunity, reason=CandidateReason.INVALID_MODE))
            continue
        if mode is MistrustMode.REACTIVE:
            if opportunity.timing_slack_ms is None or opportunity.timing_slack_ms <= 0:
                evaluations.append(_candidate_result(opportunity, reason=CandidateReason.INVALID_TIMING))
                continue
        elif opportunity.most_recent_history_ms is None or opportunity.most_recent_history_ms < 0:
            evaluations.append(_candidate_result(opportunity, reason=CandidateReason.INVALID_EVIDENCE))
            continue

        reason = _primary_reason(opportunity.primary, policy)
        if reason is not CandidateReason.ELIGIBLE:
            evaluations.append(_candidate_result(opportunity, reason=reason))
            continue

        assert opportunity.primary.current_hp is not None
        primary_damage = min(float(policy.primary_damage), float(opportunity.primary.current_hp))
        splash_ids = tuple(
            sorted(
                {
                    observation.agent_id
                    for observation in opportunity.splash_targets
                    if _splash_is_eligible(
                        observation,
                        opportunity.primary,
                        radius_squared=radius_squared,
                    )
                }
            )
        )
        by_agent_id = {observation.agent_id: observation for observation in opportunity.splash_targets}
        splash_damage = sum(
            min(float(policy.splash_damage), float(by_agent_id[agent_id].current_hp or 0.0)) for agent_id in splash_ids
        )
        useful_damage = primary_damage + splash_damage
        minimum_value = float(policy.primary_damage)
        if mode is MistrustMode.PROACTIVE:
            minimum_value += float(policy.splash_damage)
        if useful_damage < minimum_value:
            evaluations.append(
                MistrustCandidateEvaluation(
                    target_agent_id=opportunity.primary.agent_id,
                    mode=mode,
                    eligible=False,
                    reason=CandidateReason.BELOW_MINIMUM_VALUE,
                    useful_primary_damage=primary_damage,
                    useful_splash_damage=splash_damage,
                    useful_damage=useful_damage,
                    splash_agent_ids=splash_ids,
                    distance_from_player=opportunity.primary.distance_from_player,
                    timing_slack_ms=opportunity.timing_slack_ms,
                    most_recent_history_ms=opportunity.most_recent_history_ms,
                    reactive_profession_evidence=opportunity.reactive_profession_evidence,
                )
            )
            continue
        evaluations.append(
            MistrustCandidateEvaluation(
                target_agent_id=opportunity.primary.agent_id,
                mode=mode,
                eligible=True,
                reason=CandidateReason.ELIGIBLE,
                useful_primary_damage=primary_damage,
                useful_splash_damage=splash_damage,
                useful_damage=useful_damage,
                splash_agent_ids=splash_ids,
                distance_from_player=opportunity.primary.distance_from_player,
                timing_slack_ms=opportunity.timing_slack_ms,
                most_recent_history_ms=opportunity.most_recent_history_ms,
                reactive_profession_evidence=opportunity.reactive_profession_evidence,
            )
        )

    ranked = tuple(sorted(evaluations, key=_candidate_sort_key))
    selected = next((candidate for candidate in ranked if candidate.eligible), None)
    return MistrustDecision(
        selected=selected,
        reason=DecisionReason.SELECTED if selected is not None else DecisionReason.NO_ELIGIBLE_CANDIDATE,
        candidates=ranked,
    )


class SkillActivationEvidence:
    """Deduplicate and retain fresh activation identity without consuming events."""

    _ACTIVATED = 1
    _TERMINAL_TYPES = frozenset((3, 4, 6))

    def __init__(
        self,
        *,
        max_event_age_ms: int = MISTRUST_HISTORY_WINDOW_MS,
        max_seen_events: int = 256,
    ) -> None:
        self._max_event_age_ms = max(0, int(max_event_age_ms))
        self._seen_order: deque[tuple[int, int, int, int, int, float]] = deque(maxlen=max(1, int(max_seen_events)))
        self._seen_keys: set[tuple[int, int, int, int, int, float]] = set()
        self._latest_by_agent: dict[int, SkillActivationRecord] = {}
        self._history_by_agent: dict[int, list[SkillActivationRecord]] = {}
        self._conflict_onset_by_agent: dict[int, int] = {}

    def clear(self) -> None:
        self._seen_order.clear()
        self._seen_keys.clear()
        self._latest_by_agent.clear()
        self._history_by_agent.clear()
        self._conflict_onset_by_agent.clear()

    def clear_agent(self, agent_id: int) -> None:
        self._latest_by_agent.pop(int(agent_id), None)
        self._history_by_agent.pop(int(agent_id), None)
        self._conflict_onset_by_agent.pop(int(agent_id), None)

    def update(self, now_ms: int, events: Iterable[Any]) -> tuple[SkillActivationRecord, ...]:
        now = int(now_ms)
        try:
            supplied = tuple(events)
        except Exception:
            return ()
        for event in supplied:
            try:
                timestamp = int(getattr(event, "timestamp"))
                event_type = int(getattr(event, "event_type"))
                agent_id = int(getattr(event, "agent_id"))
                skill_id = int(getattr(event, "value"))
                target_id = int(getattr(event, "target_id"))
                float_value = float(getattr(event, "float_value", 0.0))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            if agent_id <= 0 or timestamp < 0 or timestamp > now or now - timestamp > self._max_event_age_ms:
                continue
            if not math.isfinite(float_value):
                float_value = 0.0
            key = (timestamp, event_type, agent_id, skill_id, target_id, float_value)
            if not self._remember_event(key):
                continue
            if event_type == self._ACTIVATED:
                self._observe_activation(now, timestamp, agent_id, skill_id, target_id)
            elif event_type in self._TERMINAL_TYPES:
                self._observe_terminal(timestamp, agent_id, skill_id)
        self.prune(now)
        return self.records(now)

    def records(self, now_ms: int | None = None) -> tuple[SkillActivationRecord, ...]:
        if now_ms is not None:
            self.prune(int(now_ms))
        return tuple(sorted(self._latest_by_agent.values(), key=lambda record: record.enemy_agent_id))

    def history_records(self, now_ms: int | None = None) -> tuple[SkillActivationRecord, ...]:
        if now_ms is not None:
            self.prune(int(now_ms))
        return tuple(
            sorted(
                (record for records in self._history_by_agent.values() for record in records),
                key=lambda record: (record.enemy_agent_id, record.onset_ms),
            )
        )

    def get_reactive(
        self,
        enemy_agent_id: int,
        skill_id: int,
        now_ms: int,
    ) -> SkillActivationRecord | None:
        record = self._latest_by_agent.get(int(enemy_agent_id))
        if record is None or record.skill_id != int(skill_id) or record.target_id <= 0:
            return None
        if int(enemy_agent_id) in self._conflict_onset_by_agent:
            return None
        now = int(now_ms)
        if (
            now < record.onset_ms
            or now - record.onset_ms > MISTRUST_REACTIVE_EVENT_MAX_AGE_MS
            or now - record.first_observed_ms > MISTRUST_REACTIVE_EVENT_MAX_AGE_MS
            or record.terminal_ms is not None
        ):
            return None
        return record

    def prune(self, now_ms: int) -> None:
        now = int(now_ms)
        for agent_id, records in tuple(self._history_by_agent.items()):
            retained = [record for record in records if 0 <= now - record.onset_ms < self._max_event_age_ms]
            if retained:
                self._history_by_agent[agent_id] = retained
            else:
                self.clear_agent(agent_id)
        stale_latest = [
            agent_id
            for agent_id, record in self._latest_by_agent.items()
            if now < record.onset_ms or now - record.onset_ms > self._max_event_age_ms
        ]
        for agent_id in stale_latest:
            self.clear_agent(agent_id)

    def _observe_activation(
        self,
        observed_at_ms: int,
        timestamp: int,
        agent_id: int,
        skill_id: int,
        target_id: int,
    ) -> None:
        if skill_id <= 0 or target_id <= 0:
            return
        conflict_onset = self._conflict_onset_by_agent.get(agent_id)
        if conflict_onset is not None:
            if timestamp <= conflict_onset:
                return
            self._conflict_onset_by_agent.pop(agent_id, None)
        previous = self._latest_by_agent.get(agent_id)
        if previous is not None:
            if timestamp < previous.onset_ms:
                return
            if timestamp == previous.onset_ms:
                if previous.skill_id != skill_id or previous.target_id != target_id:
                    self._latest_by_agent.pop(agent_id, None)
                    self._history_by_agent[agent_id] = [
                        record for record in self._history_by_agent.get(agent_id, ()) if record.onset_ms != timestamp
                    ]
                    self._conflict_onset_by_agent[agent_id] = timestamp
                return
        record = SkillActivationRecord(
            enemy_agent_id=agent_id,
            skill_id=skill_id,
            onset_ms=timestamp,
            target_id=target_id,
            first_observed_ms=observed_at_ms,
        )
        self._latest_by_agent[agent_id] = record
        self._history_by_agent.setdefault(agent_id, []).append(record)

    def _observe_terminal(self, timestamp: int, agent_id: int, skill_id: int) -> None:
        previous = self._latest_by_agent.get(agent_id)
        if previous is None or timestamp < previous.onset_ms:
            return
        if skill_id > 0 and skill_id != previous.skill_id:
            return
        if previous.terminal_ms is None or timestamp < previous.terminal_ms:
            updated = replace(previous, terminal_ms=timestamp)
            self._latest_by_agent[agent_id] = updated
            self._history_by_agent[agent_id] = [
                updated if record.identity == previous.identity else record
                for record in self._history_by_agent.get(agent_id, ())
            ]

    def _remember_event(self, key: tuple[int, int, int, int, int, float]) -> bool:
        if key in self._seen_keys:
            return False
        if len(self._seen_order) == self._seen_order.maxlen:
            oldest = self._seen_order.popleft()
            self._seen_keys.discard(oldest)
        self._seen_order.append(key)
        self._seen_keys.add(key)
        return True


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


@dataclass(frozen=True, slots=True)
class _RuntimeParameters:
    policy: MistrustPolicy
    local_activation_ms: int | None
    aftercast_delay_ms: int


class SmartMistrust(BuildMgr):
    """Guarded local Mistrust owner for My Mesmer's residual tier."""

    def __init__(
        self,
        match_only: bool = False,
        *,
        skill_id: int | None = None,
    ) -> None:
        from Py4GWCoreLib import Profession

        resolved_skill_id = int(skill_id or MISTRUST_SKILL_ID)
        if resolved_skill_id != MISTRUST_SKILL_ID:
            raise ValueError("SmartMistrust only supports PvE Mistrust 979")
        self._skill_id = resolved_skill_id
        super().__init__(
            name="Smart Mistrust",
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
        self._activation_evidence = SkillActivationEvidence()
        self._proactive_history: dict[int, list[SkillActivationRecord]] = {}
        self._history_keys: set[tuple[int, int, int, int]] = set()
        self._recent_success_by_target: dict[int, int] = {}
        self._pending_local_attempt: tuple[int, tuple[int, int, int]] | None = None

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
            self._composition_generation = int(context)
        self._refresh_lifecycle()

    def try_cast(self) -> Generator[None, None, bool]:
        if False:
            yield
        if getattr(self, "_disposed", True):
            return False
        try:
            return (yield from self._run_local_skill_logic())
        except Exception:
            self._pending_local_attempt = None
            return False

    def has_active_dispatch(self) -> bool:
        return self._pending_local_attempt is not None

    def cancel_pending(self, _reason: str) -> None:
        self._pending_local_attempt = None

    def dispose(self, _reason: str = "handler_disposed") -> None:
        if not getattr(self, "_disposed", True):
            self.cancel_pending(_reason)
            self._clear_observation_state()
            self._disposed = True

    def OnContractActivated(self, cached_data: Any = None) -> None:
        self._disposed = False
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
        self._activation_evidence.clear()
        self._proactive_history.clear()
        self._history_keys.clear()
        self._recent_success_by_target.clear()
        self._pending_local_attempt = None

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
        if previous is not None and (
            previous[0] != current[0]
            or previous[1] != current[1]
            or (previous[2] > 0 and current[2] > 0 and current[2] < previous[2])
        ):
            self._local_generation += 1
            self._clear_observation_state()
        self._last_lifecycle_inputs = current
        self._lifecycle_id = (current[0], current[1], self._local_generation)
        return True

    @staticmethod
    def _duration_to_ms(value: Any) -> int | None:
        numeric = _finite_float(value)
        if numeric is None or numeric < 0.0:
            return None
        return int(round(numeric * 1000.0))

    @staticmethod
    def _current_attribute_rank(agent: Any, player_agent_id: int, attribute_id: int) -> int | None:
        try:
            attributes = agent.GetAttributes(int(player_agent_id))
        except Exception:
            return None
        for attribute in attributes or ():
            raw_attribute_id = getattr(attribute, "attribute_id", getattr(attribute, "Id", -1))
            try:
                if int(raw_attribute_id) != int(attribute_id):
                    continue
            except (TypeError, ValueError):
                continue
            # ``level`` is the effective runtime rank.  ``level_base`` is not a
            # substitute: it omits the current attribute modifiers.
            raw_level = getattr(attribute, "level", None)
            rank = _valid_rank(raw_level)
            return rank
        return None

    def _resolve_runtime_parameters(self) -> _RuntimeParameters | None:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Player
        from Py4GWCoreLib.Skill import Skill

        try:
            cache: Any = GLOBAL_CACHE
            agent_api: Any = Agent
            skill_api: Any = Skill
            player_id = int(Player.GetAgentID() or 0)
            if player_id <= 0:
                return None
            domination_rank = self._current_attribute_rank(
                agent_api,
                player_id,
                MISTRUST_DOMINATION_ATTRIBUTE_ID,
            )
            scale = skill_api.Attribute.GetScale(self._skill_id)
            policy = MistrustPolicy.from_domination_rank(domination_rank, scale)
            base_activation_seconds = cache.Skill.Data.GetActivation(self._skill_id)
            activation_ms = self._duration_to_ms(base_activation_seconds)
            if policy is None or activation_ms is None or activation_ms <= 0:
                return None
            aftercast_ms = self._duration_to_ms(cache.Skill.Data.GetAftercast(self._skill_id))
            if aftercast_ms is None:
                return None
            fast_casting_rank = self._current_attribute_rank(
                agent_api,
                player_id,
                MISTRUST_FAST_CASTING_ATTRIBUTE_ID,
            )
            local_activation_ms = calculate_local_mistrust_activation_ms(
                base_activation_seconds,
                fast_casting_rank,
            )
            return _RuntimeParameters(
                policy=policy,
                local_activation_ms=local_activation_ms,
                aftercast_delay_ms=max(250, activation_ms + aftercast_ms + 100),
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

            skill_bar: Any = SkillBar
            slot = self._skill_slot
            if slot is None or not 1 <= slot <= 8:
                return None
            if int(skill_bar.GetSkillIDBySlot(slot) or 0) != self._skill_id:
                return None
            return slot
        except (AttributeError, TypeError, ValueError):
            return None

    def _skill_readiness(self, slot: int) -> bool:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Routines

            cache: Any = GLOBAL_CACHE
            if self._resolve_current_slot() != slot or not self._skill_toggle_enabled(slot):
                return False
            if not bool(self.CanCastSkillSlot(slot)):
                return False
            can_cast = getattr(Routines.Checks.Skills, "CanCast", None)
            if not callable(can_cast) or not bool(can_cast()):
                return False
            skill_data = cache.SkillBar.GetSkillData(slot)
            recharge = getattr(skill_data, "recharge", None)
            return recharge is not None and float(recharge) == 0.0
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
            player_id = int(Player.GetAgentID() or 0)
            if (
                player_id <= 0
                or not bool(Agent.IsValid(player_id))
                or not bool(Agent.IsAlive(player_id))
                or bool(Agent.IsKnockedDown(player_id))
                or bool(Agent.IsCasting(player_id))
            ):
                return False
            if int(GLOBAL_CACHE.SkillBar.GetCasting() or 0) != 0:
                return False
            return self._combat_option_enabled()
        except Exception:
            return False

    def _target_is_allowed(self, agent_id: int) -> bool:
        try:
            return bool(self._validate_target_for_skill_cast(self._skill_id, int(agent_id)))
        except Exception:
            return False

    @staticmethod
    def _is_enemy(agent_id: int) -> bool:
        try:
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib.enums_src.GameData_enums import Allegiance

            agent_api: Any = Agent
            raw_allegiance: Any = agent_api.GetAllegiance(agent_id)
            allegiance: Any = cast(Any, raw_allegiance[0]) if isinstance(raw_allegiance, tuple) else raw_allegiance
            return int(allegiance) == int(Allegiance.Enemy.value)
        except Exception:
            return False

    @staticmethod
    def _living_enemy(agent_id: int) -> bool:
        try:
            from Py4GWCoreLib import Agent

            return (
                int(agent_id) > 0
                and bool(Agent.IsValid(agent_id))
                and bool(Agent.IsAlive(agent_id))
                and not bool(Agent.IsDead(agent_id))
                and SmartMistrust._is_enemy(agent_id)
            )
        except Exception:
            return False

    def _party_membership(self, target_id: int) -> bool | None:
        try:
            from Py4GWCoreLib import Party
            from Py4GWCoreLib import Player

            party: Any = Party
            target = int(target_id)
            if target <= 0:
                return False
            if target == int(Player.GetAgentID() or 0):
                return True
            for member in party.GetPlayers() or ():
                if int(party.Players.GetAgentIDByLoginNumber(member.login_number) or 0) == target:
                    return True
            if any(int(getattr(member, "agent_id", 0) or 0) == target for member in party.GetHeroes() or ()):
                return True
            if any(int(getattr(member, "agent_id", 0) or 0) == target for member in party.GetHenchmen() or ()):
                return True
            if target in {int(value) for value in party.GetOthers() or ()}:
                return True
            return False
        except Exception:
            return None

    def _direct_target_is_friendly(self, enemy_id: int, target_id: int) -> bool | None:
        if int(target_id) <= 0 or int(enemy_id) <= 0 or int(target_id) == int(enemy_id):
            return False
        try:
            from Py4GWCoreLib import Agent

            if not bool(Agent.IsValid(target_id)) or not bool(Agent.IsAlive(target_id)):
                return False
        except Exception:
            return None
        return is_confirmed_direct_party_target(enemy_id, target_id, self._party_membership(target_id))

    @staticmethod
    def _skill_type_is_qualifying(skill_id: int) -> bool | None:
        try:
            from Py4GWCoreLib.Skill import Skill

            skill_api: Any = Skill
            return qualifies_mistrust_skill_type(skill_api.GetType(int(skill_id))[1])
        except Exception:
            return None

    def _update_activation_evidence(self, now_ms: int) -> bool:
        try:
            import PyAgentEvents

            peek_events = getattr(PyAgentEvents, "peek_events", None)
            if not callable(peek_events):
                return False
            events = list(cast(Iterable[Any], peek_events() or ()))
        except Exception:
            return False
        self._activation_evidence.update(now_ms, events)
        for record in self._activation_evidence.history_records(now_ms):
            if not self._living_enemy(record.enemy_agent_id):
                continue
            if self._skill_type_is_qualifying(record.skill_id) is not True:
                continue
            if self._direct_target_is_friendly(record.enemy_agent_id, record.target_id) is not True:
                continue
            if record.identity in self._history_keys:
                continue
            history = self._proactive_history.setdefault(record.enemy_agent_id, [])
            history.append(record)
            self._history_keys.add(record.identity)
        return True

    def _prune_history(self, now_ms: int) -> None:
        invalid_evidence_agents = {
            record.enemy_agent_id
            for record in self._activation_evidence.history_records(now_ms)
            if not self._living_enemy(record.enemy_agent_id)
        }
        for agent_id in invalid_evidence_agents:
            self._activation_evidence.clear_agent(agent_id)
            self._recent_success_by_target.pop(agent_id, None)
        for agent_id, records in tuple(self._proactive_history.items()):
            if not self._living_enemy(agent_id):
                self._proactive_history.pop(agent_id, None)
                self._recent_success_by_target.pop(agent_id, None)
                for record in records:
                    self._history_keys.discard(record.identity)
                continue
            retained = [record for record in records if 0 <= now_ms - record.onset_ms < MISTRUST_HISTORY_WINDOW_MS]
            if retained:
                self._proactive_history[agent_id] = retained
            else:
                self._proactive_history.pop(agent_id, None)
            for record in records:
                if record not in retained:
                    self._history_keys.discard(record.identity)
        for agent_id in tuple(self._recent_success_by_target):
            if not self._living_enemy(agent_id):
                self._recent_success_by_target.pop(agent_id, None)
        expired_successes = [
            agent_id
            for agent_id, timestamp in self._recent_success_by_target.items()
            if now_ms - timestamp >= MISTRUST_HISTORY_WINDOW_MS
        ]
        for agent_id in expired_successes:
            self._recent_success_by_target.pop(agent_id, None)

    def _recent_success_is_live(self, agent_id: int, now_ms: int) -> bool:
        timestamp = self._recent_success_by_target.get(int(agent_id))
        if timestamp is None:
            return False
        if now_ms - timestamp >= MISTRUST_HISTORY_WINDOW_MS:
            self._recent_success_by_target.pop(int(agent_id), None)
            return False
        return now_ms >= timestamp

    def _history_for(self, agent_id: int, now_ms: int) -> tuple[SkillActivationRecord, ...]:
        records = tuple(
            record
            for record in self._proactive_history.get(int(agent_id), ())
            if 0 <= now_ms - record.onset_ms < MISTRUST_HISTORY_WINDOW_MS
        )
        identities = {record.identity for record in records}
        if len(identities) < 2:
            return ()
        return tuple(sorted(records, key=lambda record: record.onset_ms))

    def _current_fast_casting_dazed(self) -> bool | None:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Player
            from Py4GWCoreLib import Routines

            dazed_id = int(GLOBAL_CACHE.Skill.GetID("Dazed") or 0)
            has_effect = getattr(Routines.Checks.Agents, "HasEffect", None)
            player_id = int(Player.GetAgentID() or 0)
            if dazed_id <= 0 or player_id <= 0 or not callable(has_effect):
                return None
            return bool(has_effect(player_id, dazed_id))
        except Exception:
            return None

    @staticmethod
    def _enemy_profession_evidence(enemy_id: int) -> _EnemyProfessionEvidence | None:
        try:
            from Py4GWCoreLib import Agent

            if not SmartMistrust._living_enemy(enemy_id) or not bool(Agent.IsLiving(enemy_id)):
                return None
            living = Agent.GetLivingAgentByID(enemy_id)
            if living is None or not bool(living.is_npc):
                return None
            model_index = Agent.GetModelID(enemy_id)
            if type(model_index) is not int or model_index <= 0:
                return None
            if type(living.player_number) is not int or living.player_number != model_index:
                return None
            model = Agent.GetNPCModelAtIndex(model_index)
            if model is None:
                return None
            model_primary = model.primary
            if type(model_primary) is not int or not 1 <= model_primary <= 10:
                return None
            living_primary: Any = living.primary
            if living_primary is not None:
                if type(living_primary) is not int or not 0 <= living_primary <= 10:
                    return None
                if living_primary != 0 and living_primary != model_primary:
                    return None
            if model_primary == MISTRUST_PROFESSION_MESMER_ID:
                return None
            return _EnemyProfessionEvidence(model_index, model_primary, living_primary)
        except Exception:
            return None

    def _enemy_remaining_slack(
        self,
        record: SkillActivationRecord,
        now_ms: int,
        local_activation_ms: int | None,
        profession_evidence: _EnemyProfessionEvidence | None = None,
    ) -> int | None:
        if local_activation_ms is None:
            return None
        if profession_evidence is None and self._enemy_profession_evidence(record.enemy_agent_id) is None:
            return None
        try:
            from PyPing import PingHandler

            from Py4GWCoreLib import GLOBAL_CACHE

            cache: Any = GLOBAL_CACHE
            base_activation = cache.Skill.Data.GetActivation(record.skill_id)
            current_ping = PingHandler().GetCurrentPing()
        except Exception:
            return None
        return reactive_timing_slack_ms(
            enemy_base_activation_seconds=base_activation,
            dispatch_now_ms=now_ms,
            retained_onset_ms=record.onset_ms,
            local_mistrust_est_ms=local_activation_ms,
            current_ping_ms=current_ping,
        )

    @staticmethod
    def _d0_claim_compatible(
        intent: Any,
        *,
        group_id: int,
        enemy_agent_id: int,
        enemy_skill_id: int,
        now_ms: int,
        retained_onset_ms: int,
    ) -> bool:
        try:
            if not bool(getattr(intent, "Active")):
                return False
            if int(getattr(intent, "KindID")) != INTERRUPT_TARGET_KIND_ID:
                return False
            if int(getattr(intent, "IsolationGroupID")) != int(group_id):
                return False
            if int(getattr(intent, "SkillID")) != int(enemy_skill_id):
                return False
            if int(getattr(intent, "TargetAgentID")) != int(enemy_agent_id):
                return False
            posted_tick = int(getattr(intent, "PostedAtTick"))
            expires_tick = int(getattr(intent, "ExpiresAtTick"))
            if _intent_tick_is_expired(int(now_ms), expires_tick):
                return False
            elapsed_since_onset = int(now_ms) - int(retained_onset_ms)
            if elapsed_since_onset < 0:
                return False
            # The uint32 whiteboard timestamp must not predate this retained
            # cast onset; that rejects stale/pre-cast claims without mutating D0.
            return _intent_tick_elapsed(int(now_ms), posted_tick) <= elapsed_since_onset
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False

    def _read_matching_d0_claim(
        self,
        *,
        enemy_agent_id: int,
        enemy_skill_id: int,
        now_ms: int,
        retained_onset_ms: int,
    ) -> bool | None:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Player

            owner_email = str(Player.GetAccountEmail() or "").strip()
            if not owner_email:
                return None
            group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(owner_email) or 0)
            if group_id <= 0:
                return None
            all_accounts = GLOBAL_CACHE.ShMem.GetAllAccounts()
            class_method = getattr(type(all_accounts), "GetAllIntents", None)
            if class_method is None:
                rows = all_accounts.GetAllIntents()
            else:
                raw_method = getattr(class_method, "__wrapped__", class_method)
                rows = raw_method(all_accounts)
            rows = cast(Iterable[Any], rows)
            for row in rows or ():
                if isinstance(row, tuple):
                    row_items = cast(tuple[Any, ...], row)
                    intent = row_items[1] if len(row_items) >= 2 else row_items
                else:
                    intent = row
                if self._d0_claim_compatible(
                    intent,
                    group_id=group_id,
                    enemy_agent_id=enemy_agent_id,
                    enemy_skill_id=enemy_skill_id,
                    now_ms=now_ms,
                    retained_onset_ms=retained_onset_ms,
                ):
                    return True
            return False
        except Exception:
            return None

    def _build_snapshot(self, parameters: _RuntimeParameters) -> tuple[MistrustTargetObservation, ...] | None:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray
        from Py4GWCoreLib import Player

        agent_array: Any = AgentArray
        player_position = _position(Player.GetXY())
        if player_position is None:
            return None
        try:
            raw_enemy_ids = agent_array.GetEnemyArray()
        except Exception:
            return None
        observations: list[MistrustTargetObservation] = []
        seen_ids: set[int] = set()
        for raw_agent_id in raw_enemy_ids:
            try:
                agent_id = int(raw_agent_id)
                if agent_id <= 0 or agent_id in seen_ids:
                    continue
                seen_ids.add(agent_id)
                if not self._living_enemy(agent_id):
                    continue
                position = _position(Agent.GetXY(agent_id))
                health_fraction = _finite_float(Agent.GetHealth(agent_id))
                maximum_health = _finite_float(Agent.GetMaxHealth(agent_id))
                if (
                    position is None
                    or health_fraction is None
                    or maximum_health is None
                    or not 0.0 < health_fraction <= 1.0
                    or maximum_health <= 0.0
                ):
                    continue
                distance = math.hypot(
                    position[0] - player_position[0],
                    position[1] - player_position[1],
                )
                if not math.isfinite(distance):
                    continue
                observations.append(
                    MistrustTargetObservation(
                        agent_id=agent_id,
                        x=position[0],
                        y=position[1],
                        current_hp=health_fraction * maximum_health,
                        distance_from_player=distance,
                        is_valid=True,
                        is_alive=True,
                        is_hostile=True,
                        is_targetable=self._target_is_allowed(agent_id),
                    )
                )
            except Exception:
                continue
        return tuple(sorted(observations, key=lambda observation: observation.agent_id))

    def _evaluate_live(
        self,
        parameters: _RuntimeParameters,
        *,
        now_ms: int,
    ) -> MistrustDecision | None:
        snapshot = self._build_snapshot(parameters)
        if snapshot is None:
            return None
        if self._pending_local_attempt is not None:
            return MistrustDecision(None, DecisionReason.NO_ELIGIBLE_CANDIDATE, ())

        opportunities: list[MistrustOpportunity] = []
        local_dazed = self._current_fast_casting_dazed()
        if local_dazed is False and parameters.local_activation_ms is not None:
            for observation in snapshot:
                if self._recent_success_is_live(observation.agent_id, now_ms):
                    continue
                try:
                    from Py4GWCoreLib import Agent

                    if not bool(Agent.IsCasting(observation.agent_id)):
                        continue
                    current_skill_id = int(Agent.GetCastingSkillID(observation.agent_id) or 0)
                    if current_skill_id <= 0 or self._skill_type_is_qualifying(current_skill_id) is not True:
                        continue
                    record = self._activation_evidence.get_reactive(
                        observation.agent_id,
                        current_skill_id,
                        now_ms,
                    )
                    if record is None:
                        continue
                    if self._direct_target_is_friendly(observation.agent_id, record.target_id) is not True:
                        continue
                    profession_evidence = self._enemy_profession_evidence(observation.agent_id)
                    if profession_evidence is None:
                        continue
                    slack = self._enemy_remaining_slack(
                        record,
                        now_ms,
                        parameters.local_activation_ms,
                        profession_evidence,
                    )
                    if slack is None:
                        continue
                    opportunities.append(
                        MistrustOpportunity(
                            mode=MistrustMode.REACTIVE,
                            primary=observation,
                            splash_targets=snapshot,
                            timing_slack_ms=slack,
                            reactive_profession_evidence=profession_evidence,
                        )
                    )
                except Exception:
                    continue

        for observation in snapshot:
            if self._recent_success_is_live(observation.agent_id, now_ms):
                continue
            history = self._history_for(observation.agent_id, now_ms)
            if len(history) < 2:
                continue
            opportunities.append(
                MistrustOpportunity(
                    mode=MistrustMode.PROACTIVE,
                    primary=observation,
                    splash_targets=snapshot,
                    most_recent_history_ms=history[-1].onset_ms,
                )
            )

        decision = evaluate_smart_mistrust(
            opportunities,
            policy=parameters.policy,
        )
        return decision

    def _final_revalidate(
        self,
        selected: MistrustCandidateEvaluation,
        parameters: _RuntimeParameters,
    ) -> tuple[_RuntimeParameters, MistrustCandidateEvaluation] | None:
        if not self._runtime_gate():
            return None
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return None
        current_parameters = self._resolve_runtime_parameters()
        if current_parameters is None:
            return None
        now_ms = self._now_ms()
        if now_ms is None:
            return None
        self._update_activation_evidence(now_ms)
        decision = self._evaluate_live(current_parameters, now_ms=now_ms)
        if decision is None or decision.selected is None:
            return None
        if decision.selected.target_agent_id != selected.target_agent_id or decision.selected.mode is not selected.mode:
            return None
        current_selected = decision.selected
        if current_selected.mode is MistrustMode.REACTIVE:
            if (
                selected.reactive_profession_evidence is None
                or current_selected.reactive_profession_evidence != selected.reactive_profession_evidence
            ):
                return None
            # D0 is a dispatch-only coordination read; it must not affect candidate ranking.
            selected_id = current_selected.target_agent_id
            try:
                from Py4GWCoreLib import Agent

                current_skill_id = int(Agent.GetCastingSkillID(selected_id) or 0)
            except Exception:
                return None
            record = self._activation_evidence.get_reactive(selected_id, current_skill_id, now_ms)
            if record is None:
                return None
            d0_state = self._read_matching_d0_claim(
                enemy_agent_id=selected_id,
                enemy_skill_id=current_skill_id,
                now_ms=now_ms,
                retained_onset_ms=record.onset_ms,
            )
            if d0_state is True:
                return None
        return current_parameters, current_selected

    def _dispatch_selected(
        self,
        selected: MistrustCandidateEvaluation,
        parameters: _RuntimeParameters,
    ) -> Generator[None, None, bool]:
        if False:
            yield
        validated = self._final_revalidate(selected, parameters)
        if validated is None or self._lifecycle_id is None:
            return False
        current_parameters, _current_selected = validated
        target_id = int(selected.target_agent_id)
        self._pending_local_attempt = (target_id, self._lifecycle_id)
        try:
            result = cast(
                Any,
                self.CastSkillID(
                    skill_id=self._skill_id,
                    log=False,
                    aftercast_delay=current_parameters.aftercast_delay_ms,
                    target_agent_id=target_id,
                ),
            )
            if hasattr(result, "__next__"):
                result = yield from cast(Generator[None, None, Any], result)
            accepted = bool(result)
            if accepted:
                now_ms = self._now_ms()
                if now_ms is not None:
                    self._recent_success_by_target[target_id] = now_ms
            return accepted
        except Exception:
            return False
        finally:
            self._pending_local_attempt = None

    def _run_local_skill_logic(self) -> Generator[None, None, bool]:
        if False:
            yield
        now_ms = self._now_ms()
        if now_ms is None or not self._refresh_lifecycle():
            return False
        self._prune_history(now_ms)
        self._update_activation_evidence(now_ms)
        if not self._runtime_gate():
            return False
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return False
        parameters = self._resolve_runtime_parameters()
        if parameters is None:
            return False
        decision = self._evaluate_live(parameters, now_ms=now_ms)
        if decision is None or decision.selected is None:
            return False
        return (yield from self._dispatch_selected(decision.selected, parameters))


SUPPORTED_HANDLER_FACTORIES: Final[dict[int, type[SmartMistrust]]] = {
    MISTRUST_SKILL_ID: SmartMistrust,
}


def get_supported_handler_factories() -> dict[int, type[SmartMistrust]]:
    return dict(SUPPORTED_HANDLER_FACTORIES)


evaluate_mistrust = evaluate_smart_mistrust
MistrustDecisionReason = DecisionReason
MistrustCandidateReason = CandidateReason


__all__ = [
    "CandidateReason",
    "DecisionReason",
    "MISTRUST_CAST_RANGE",
    "MISTRUST_DOMINATION_ATTRIBUTE_ID",
    "MISTRUST_FAST_CASTING_ATTRIBUTE_ID",
    "MISTRUST_HISTORY_WINDOW_MS",
    "MISTRUST_NAME",
    "MISTRUST_PROFESSION_MESMER_ID",
    "MISTRUST_REACTIVE_EVENT_MAX_AGE_MS",
    "MISTRUST_SCALE_RANK_FIFTEEN",
    "MISTRUST_SCALE_RANK_ZERO",
    "MISTRUST_SKILL_ID",
    "MISTRUST_SPLASH_RADIUS",
    "MistrustCandidateEvaluation",
    "MistrustCandidateReason",
    "MistrustDecision",
    "MistrustDecisionReason",
    "MistrustMode",
    "MistrustOpportunity",
    "MistrustPolicy",
    "MistrustTargetObservation",
    "SkillActivationEvidence",
    "SkillActivationRecord",
    "SmartMistrust",
    "SUPPORTED_HANDLER_FACTORIES",
    "calculate_local_mistrust_activation_ms",
    "calculate_reactive_reserve_ms",
    "estimate_enemy_remaining_ms",
    "evaluate_mistrust",
    "evaluate_smart_mistrust",
    "get_supported_handler_factories",
    "is_confirmed_direct_party_target",
    "qualifies_mistrust_skill_type",
    "reactive_timing_slack_ms",
    "resolve_mistrust_damage",
]
