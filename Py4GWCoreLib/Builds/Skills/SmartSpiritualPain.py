"""Pure PvE Spiritual Pain policy and its guarded My Mesmer runtime handler."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Final

from Py4GWCoreLib.BuildMgr import BuildMgr

SPIRITUAL_PAIN_SKILL_ID: Final[int] = 1336
SPIRITUAL_PAIN_NAME: Final[str] = "Spiritual_Pain"
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


@dataclass(frozen=True, slots=True)
class _RuntimeParameters:
    policy: SpiritualPainPolicy


class SmartSpiritualPain(BuildMgr):
    """Small My Mesmer-owned Spiritual Pain handler with no coordination state."""

    def __init__(
        self,
        match_only: bool = False,
        *,
        skill_id: int | None = None,
    ) -> None:
        from Py4GWCoreLib import Profession

        resolved_skill_id = int(skill_id or SPIRITUAL_PAIN_SKILL_ID)
        if resolved_skill_id != SPIRITUAL_PAIN_SKILL_ID:
            raise ValueError("SmartSpiritualPain only supports PvE Spiritual Pain 1336")
        self._skill_id = resolved_skill_id
        super().__init__(
            name="Smart Spiritual Pain",
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

    def try_cast(self):
        if False:
            yield
        if getattr(self, "_disposed", True):
            return False
        try:
            return (yield from self._run_local_skill_logic())
        except Exception:
            return False

    def cancel_pending(self, _reason: str) -> None:
        return

    def dispose(self, _reason: str = "handler_disposed") -> None:
        if not getattr(self, "_disposed", True):
            self._disposed = True

    def OnContractActivated(self, cached_data: Any = None) -> None:
        self._disposed = False
        if cached_data is not None:
            self.set_cached_data(cached_data)

    @staticmethod
    def _current_domination_rank(agent: Any, player_agent_id: int) -> int | None:
        try:
            attributes = agent.GetAttributes(int(player_agent_id))
        except Exception:
            return None
        for attribute in attributes or ():
            attribute_id = getattr(attribute, "attribute_id", getattr(attribute, "Id", -1))
            try:
                if int(attribute_id) != 2:
                    continue
            except (TypeError, ValueError):
                continue
            level = getattr(attribute, "level", getattr(attribute, "Value", None))
            numeric_level = _finite_float(level)
            if numeric_level is None or not numeric_level.is_integer() or not 0 <= numeric_level <= 21:
                return None
            return int(numeric_level)
        return None

    def _resolve_runtime_parameters(self) -> _RuntimeParameters | None:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Range

        try:
            player_agent_id = int(Player.GetAgentID() or 0)
            if player_agent_id <= 0:
                return None
            rank = self._current_domination_rank(Agent, player_agent_id)
            base_policy = SpiritualPainPolicy.from_domination_rank(rank)
            cast_range = _finite_float(getattr(Range.Spellcast, "value", None))
            if base_policy is None or cast_range is None or cast_range <= 0.0:
                return None
            return _RuntimeParameters(
                policy=SpiritualPainPolicy(
                    primary_damage=base_policy.primary_damage,
                    summon_damage=base_policy.summon_damage,
                    cast_range=cast_range,
                    area_radius=SPIRITUAL_PAIN_AREA_RADIUS,
                )
            )
        except Exception:
            return None

    def _combat_option_enabled(self) -> bool:
        try:
            options = getattr(self._cached_data, "account_options", None)
            combat = getattr(options, "Combat", None)
            return combat is not None and bool(combat)
        except Exception:
            return False

    def _skill_toggle_enabled(self, slot: int) -> bool:
        try:
            if not 1 <= int(slot) <= 8:
                return False
            options = getattr(self._cached_data, "account_options", None)
            skills = getattr(options, "Skills", None)
            if skills is None:
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

            raw_allegiance = Agent.GetAllegiance(agent_id)
            allegiance = raw_allegiance[0] if isinstance(raw_allegiance, tuple) else raw_allegiance
            return int(allegiance) == int(Allegiance.Enemy.value)
        except Exception:
            return False

    @staticmethod
    def _absolute_current_hp(agent: Any, agent_id: int) -> float | None:
        normalized_health = _finite_float(agent.GetHealth(agent_id))
        maximum_health = _finite_float(agent.GetMaxHealth(agent_id))
        if (
            normalized_health is None
            or maximum_health is None
            or not 0.0 < normalized_health <= 1.0
            or maximum_health <= 0.0
        ):
            return None
        current_hp = normalized_health * maximum_health
        return current_hp if math.isfinite(current_hp) and current_hp > 0.0 else None

    @staticmethod
    def _npc_flags(agent: Any, agent_id: int) -> int | None:
        try:
            value = agent.GetNPCFlags(agent_id)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            return int(value)
        except Exception:
            return None

    def _build_snapshot(self, _parameters: _RuntimeParameters) -> tuple[SpiritualPainTargetObservation, ...] | None:
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

        observations: list[SpiritualPainTargetObservation] = []
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
                is_direct_enemy = self._is_enemy(agent_id)
                if not is_valid or not is_living or not is_alive or not is_direct_enemy:
                    continue
                if not self._target_is_allowed(agent_id):
                    continue

                position = _position(Agent.GetXY(agent_id))
                distance = None
                if position is not None:
                    distance = math.hypot(
                        position[0] - player_position[0],
                        position[1] - player_position[1],
                    )
                    if not math.isfinite(distance):
                        distance = None
                observations.append(
                    SpiritualPainTargetObservation(
                        agent_id=agent_id,
                        x=None if position is None else position[0],
                        y=None if position is None else position[1],
                        current_hp=self._absolute_current_hp(Agent, agent_id),
                        distance_from_player=distance,
                        evidence=SpiritualPainEvidence(
                            is_valid=is_valid,
                            is_living=is_living,
                            is_alive=is_alive,
                            is_direct_enemy=is_direct_enemy,
                            npc_flags=self._npc_flags(Agent, agent_id),
                            type_map=None,
                        ),
                    )
                )
            except Exception:
                continue
        return tuple(sorted(observations, key=lambda observation: observation.agent_id))

    def _evaluate_live(self, parameters: _RuntimeParameters) -> SpiritualPainDecision | None:
        snapshot = self._build_snapshot(parameters)
        if snapshot is None:
            return None
        return evaluate_smart_spiritual_pain(snapshot, policy=parameters.policy)

    @staticmethod
    def _same_scoring_parameters(first: _RuntimeParameters, second: _RuntimeParameters) -> bool:
        return first.policy == second.policy

    def _final_revalidate(
        self,
        selected_agent_id: int,
        parameters: _RuntimeParameters,
    ) -> tuple[_RuntimeParameters, SpiritualPainCandidateEvaluation] | None:
        if not self._runtime_gate():
            return None
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return None
        current_parameters = self._resolve_runtime_parameters()
        if current_parameters is None or not self._same_scoring_parameters(parameters, current_parameters):
            return None
        try:
            if not bool(self.CanCastSkillID(self._skill_id)):
                return None
        except Exception:
            return None
        decision = self._evaluate_live(current_parameters)
        if decision is None or decision.selected is None:
            return None
        if decision.selected.target_agent_id != int(selected_agent_id):
            return None
        return current_parameters, decision.selected

    def _dispatch_selected(self, selected_agent_id: int, parameters: _RuntimeParameters):
        if False:
            yield
        validated = self._final_revalidate(selected_agent_id, parameters)
        if validated is None:
            return False
        try:
            result = self.CastSkillID(
                skill_id=self._skill_id,
                log=False,
                target_agent_id=int(selected_agent_id),
            )
            if hasattr(result, "__next__"):
                result = yield from result
            return bool(result)
        except Exception:
            return False

    def _run_local_skill_logic(self):
        if False:
            yield
        if not self._runtime_gate():
            return False
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return False
        try:
            if not bool(self.CanCastSkillID(self._skill_id)):
                return False
        except Exception:
            return False
        parameters = self._resolve_runtime_parameters()
        if parameters is None:
            return False
        decision = self._evaluate_live(parameters)
        if decision is None or decision.selected is None:
            return False
        return (yield from self._dispatch_selected(decision.selected.target_agent_id, parameters))


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
    "SPIRITUAL_PAIN_NAME",
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
    "SmartSpiritualPain",
    "TYPE_MAP_SPIRIT_BIT",
    "classify_hostile_summon",
    "classify_summon",
    "evaluate_smart_spiritual_pain",
    "evaluate_spiritual_pain",
    "resolve_spiritual_pain_damage",
    "resolve_spiritual_pain_rank",
    "useful_damage",
]
