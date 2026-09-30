"""Pure target/value policy and guarded handler for PvE Unnatural Signet."""

from __future__ import annotations

import math
from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any
from typing import Final
from typing import cast

from Py4GWCoreLib.BuildMgr import BuildMgr

UNNATURAL_SIGNET_SKILL_ID: Final[int] = 934
UNNATURAL_SIGNET_NAME: Final[str] = "Unnatural_Signet"


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
class UnnaturalSignetPolicy:
    """Rank-resolved damage and factual geometry for one policy evaluation."""

    primary_damage: float
    adjacent_damage: float
    cast_range: float
    adjacent_radius: float


@dataclass(frozen=True, slots=True)
class UnnaturalSignetTargetObservation:
    """Immutable facts for one possible primary or secondary target.

    ``current_hp`` is expressed in actual health points. The runtime adapter
    converts the normalized ``Agent.GetHealth`` value before constructing this
    observation.
    """

    agent_id: int
    x: float | None
    y: float | None
    current_hp: float | None
    distance_from_player: float | None
    has_hex: bool | None = False
    has_enchantment: bool | None = False
    is_valid: bool | None = True
    is_alive: bool | None = True
    is_hostile: bool | None = True
    is_targetable: bool | None = True

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, int) or isinstance(self.agent_id, bool):
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
            ("has_hex", self.has_hex),
            ("has_enchantment", self.has_enchantment),
            ("is_valid", self.is_valid),
            ("is_alive", self.is_alive),
            ("is_hostile", self.is_hostile),
            ("is_targetable", self.is_targetable),
        ):
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool or None")

    @property
    def position(self) -> tuple[float, float] | None:
        if self.x is None or self.y is None:
            return None
        return float(self.x), float(self.y)


@dataclass(frozen=True, slots=True)
class UnnaturalSignetCandidateEvaluation:
    """Deterministic admission and delivered-value result for one candidate."""

    target_agent_id: int
    eligible: bool
    reason: CandidateReason
    qualifies_secondary: bool
    useful_primary_damage: float
    conditional_adjacent_damage: float
    useful_delivered_damage: float
    secondary_agent_ids: tuple[int, ...]
    distance_from_player: float | None

    @property
    def primary_agent_id(self) -> int:
        return self.target_agent_id

    @property
    def secondary_hit_count(self) -> int:
        return len(self.secondary_agent_ids)

    @property
    def useful_damage(self) -> float:
        return self.useful_delivered_damage


@dataclass(frozen=True, slots=True)
class UnnaturalSignetDecision:
    """Pure policy result; it performs no runtime or native action."""

    selected: UnnaturalSignetCandidateEvaluation | None
    reason: DecisionReason
    candidates: tuple[UnnaturalSignetCandidateEvaluation, ...]

    @property
    def admitted(self) -> bool:
        return self.selected is not None

    @property
    def selected_target_agent_id(self) -> int | None:
        return None if self.selected is None else self.selected.target_agent_id

    @property
    def ranked_candidates(self) -> tuple[UnnaturalSignetCandidateEvaluation, ...]:
        return self.candidates


def _invalid_decision(reason: DecisionReason) -> UnnaturalSignetDecision:
    return UnnaturalSignetDecision(selected=None, reason=reason, candidates=())


def _valid_policy(policy: UnnaturalSignetPolicy) -> bool:
    return all(
        (
            math.isfinite(float(policy.primary_damage)),
            math.isfinite(float(policy.adjacent_damage)),
            math.isfinite(float(policy.cast_range)),
            math.isfinite(float(policy.adjacent_radius)),
            float(policy.primary_damage) > 0.0,
            float(policy.adjacent_damage) > 0.0,
            float(policy.cast_range) > 0.0,
            float(policy.adjacent_radius) > 0.0,
        )
    )


def _candidate_result(
    observation: UnnaturalSignetTargetObservation,
    *,
    reason: CandidateReason,
) -> UnnaturalSignetCandidateEvaluation:
    return UnnaturalSignetCandidateEvaluation(
        target_agent_id=observation.agent_id,
        eligible=False,
        reason=reason,
        qualifies_secondary=False,
        useful_primary_damage=0.0,
        conditional_adjacent_damage=0.0,
        useful_delivered_damage=0.0,
        secondary_agent_ids=(),
        distance_from_player=observation.distance_from_player,
    )


def _primary_reason(
    observation: UnnaturalSignetTargetObservation,
    policy: UnnaturalSignetPolicy,
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
            observation.has_hex,
            observation.has_enchantment,
            observation.is_valid,
            observation.is_alive,
            observation.is_hostile,
            observation.is_targetable,
        )
    ):
        return CandidateReason.MISSING_EVIDENCE
    if (
        observation.current_hp is None
        or observation.current_hp <= 0.0
        or observation.distance_from_player is None
        or observation.distance_from_player < 0.0
    ):
        return CandidateReason.INVALID_TARGET
    if observation.distance_from_player > policy.cast_range:
        return CandidateReason.OUT_OF_CAST_RANGE
    return CandidateReason.ELIGIBLE


def _secondary_is_eligible(
    observation: UnnaturalSignetTargetObservation,
    primary: UnnaturalSignetTargetObservation,
    *,
    adjacent_radius_squared: float,
) -> bool:
    if observation.agent_id == primary.agent_id:
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
    return delta_x * delta_x + delta_y * delta_y <= adjacent_radius_squared


def _candidate_sort_key(
    candidate: UnnaturalSignetCandidateEvaluation,
) -> tuple[int, float, int, float, int]:
    distance = math.inf if candidate.distance_from_player is None else candidate.distance_from_player
    return (
        0 if candidate.eligible else 1,
        -candidate.useful_delivered_damage,
        -candidate.secondary_hit_count,
        distance,
        candidate.target_agent_id,
    )


def evaluate_smart_unnatural_signet(
    candidates: Iterable[UnnaturalSignetTargetObservation],
    *,
    policy: UnnaturalSignetPolicy | None = None,
    primary_damage: float | None = None,
    adjacent_damage: float | None = None,
    cast_range: float | None = None,
    adjacent_radius: float | None = None,
) -> UnnaturalSignetDecision:
    """Select the highest useful PvE Unnatural Signet target deterministically."""

    if policy is None:
        if any(value is None for value in (primary_damage, adjacent_damage, cast_range, adjacent_radius)):
            return _invalid_decision(DecisionReason.INVALID_POLICY)
        assert primary_damage is not None
        assert adjacent_damage is not None
        assert cast_range is not None
        assert adjacent_radius is not None
        try:
            policy = UnnaturalSignetPolicy(
                primary_damage=float(primary_damage),
                adjacent_damage=float(adjacent_damage),
                cast_range=float(cast_range),
                adjacent_radius=float(adjacent_radius),
            )
        except (TypeError, ValueError, OverflowError):
            return _invalid_decision(DecisionReason.INVALID_POLICY)
    if not _valid_policy(policy):
        return _invalid_decision(DecisionReason.INVALID_POLICY)

    try:
        observations = tuple(candidates)
    except Exception:
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    if any(not isinstance(observation, UnnaturalSignetTargetObservation) for observation in observations):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)
    agent_ids = tuple(observation.agent_id for observation in observations)
    if len(agent_ids) != len(set(agent_ids)):
        return _invalid_decision(DecisionReason.INVALID_EVIDENCE)

    observations = tuple(sorted(observations, key=lambda observation: observation.agent_id))
    by_agent_id = {observation.agent_id: observation for observation in observations}
    adjacent_radius_squared = float(policy.adjacent_radius) * float(policy.adjacent_radius)
    evaluations: list[UnnaturalSignetCandidateEvaluation] = []

    for observation in observations:
        reason = _primary_reason(observation, policy)
        if reason is not CandidateReason.ELIGIBLE:
            evaluations.append(_candidate_result(observation, reason=reason))
            continue

        assert observation.current_hp is not None
        primary_damage_value = min(float(policy.primary_damage), float(observation.current_hp))
        qualifies_secondary = bool(observation.has_hex or observation.has_enchantment)
        secondary_agent_ids: tuple[int, ...] = ()
        conditional_damage = 0.0
        if qualifies_secondary:
            secondary_agent_ids = tuple(
                sorted(
                    candidate.agent_id
                    for candidate in observations
                    if _secondary_is_eligible(
                        candidate,
                        observation,
                        adjacent_radius_squared=adjacent_radius_squared,
                    )
                )
            )
            conditional_damage = sum(
                min(float(policy.adjacent_damage), float(by_agent_id[agent_id].current_hp or 0.0))
                for agent_id in secondary_agent_ids
            )
        evaluations.append(
            UnnaturalSignetCandidateEvaluation(
                target_agent_id=observation.agent_id,
                eligible=True,
                reason=CandidateReason.ELIGIBLE,
                qualifies_secondary=qualifies_secondary,
                useful_primary_damage=primary_damage_value,
                conditional_adjacent_damage=conditional_damage,
                useful_delivered_damage=primary_damage_value + conditional_damage,
                secondary_agent_ids=secondary_agent_ids,
                distance_from_player=observation.distance_from_player,
            )
        )

    ranked = tuple(sorted(evaluations, key=_candidate_sort_key))
    selected = next((candidate for candidate in ranked if candidate.eligible), None)
    return UnnaturalSignetDecision(
        selected=selected,
        reason=DecisionReason.SELECTED if selected is not None else DecisionReason.NO_ELIGIBLE_CANDIDATE,
        candidates=ranked,
    )


evaluate_unnatural_signet = evaluate_smart_unnatural_signet
UnnaturalSignetDecisionReason = DecisionReason
UnnaturalSignetCandidateReason = CandidateReason


def _normalise_name(value: Any) -> str:
    return "".join(character.casefold() for character in str(value) if character.isalnum())


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


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
    primary_damage: float
    adjacent_damage: float
    cast_range: float
    adjacent_radius: float
    aftercast_delay_ms: int


class SmartUnnaturalSignet(BuildMgr):
    """Small My Mesmer-owned handler with no cross-client coordination."""

    def __init__(
        self,
        match_only: bool = False,
        *,
        skill_id: int | None = None,
    ) -> None:
        from Py4GWCoreLib import Profession

        resolved_skill_id = int(skill_id or UNNATURAL_SIGNET_SKILL_ID)
        if resolved_skill_id != UNNATURAL_SIGNET_SKILL_ID:
            raise ValueError("SmartUnnaturalSignet only supports PvE Unnatural Signet 934")
        self._skill_id = resolved_skill_id
        super().__init__(
            name="Smart Unnatural Signet",
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
    def _duration_to_ms(value: Any) -> int | None:
        numeric = _finite_float(value)
        if numeric is None or numeric < 0.0:
            return None
        return int(round(numeric * 1000.0))

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

    @staticmethod
    def _progression_values(progression_data: Any) -> tuple[dict[int, float], dict[int, float]] | None:
        primary: dict[int, float] | None = None
        adjacent: dict[int, float] | None = None
        try:
            entries = tuple(progression_data or ())
        except Exception:
            return None
        for entry in entries:
            if not isinstance(entry, (tuple, list)) or len(entry) < 3:
                return None
            attribute_name, field_name, values = entry[0], entry[1], entry[2]
            if _normalise_name(attribute_name) not in {"dominationmagic", "domination"}:
                continue
            if not isinstance(values, Mapping):
                return None
            values = cast(Mapping[Any, Any], values)
            converted: dict[int, float] = {}
            for raw_rank, raw_value in values.items():
                try:
                    rank = int(raw_rank)
                except (TypeError, ValueError):
                    return None
                amount = _finite_float(raw_value)
                if amount is None or amount <= 0.0:
                    return None
                converted[rank] = amount
            field_key = _normalise_name(field_name)
            if field_key == "damage":
                if primary is not None:
                    return None
                primary = converted
            elif field_key in {"damagetoadjacent", "damageadjacent"}:
                if adjacent is not None:
                    return None
                adjacent = converted
        if primary is None or adjacent is None:
            return None
        return primary, adjacent

    def _resolve_runtime_parameters(self) -> _RuntimeParameters | None:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Player
        from Py4GWCoreLib import Range
        from Py4GWCoreLib.Skill import Skill

        try:
            player_agent_id = int(Player.GetAgentID() or 0)
            if player_agent_id <= 0:
                return None
            rank = self._current_domination_rank(Agent, player_agent_id)
            progression = self._progression_values(Skill.GetProgressionData(self._skill_id))
            if rank is None or progression is None:
                return None
            primary_values, adjacent_values = progression
            primary_damage = primary_values.get(rank)
            adjacent_damage = adjacent_values.get(rank)
            cast_range = _finite_float(getattr(Range.Spellcast, "value", None))
            adjacent_radius = _finite_float(getattr(Range.Adjacent, "value", None))
            activation_ms = self._duration_to_ms(GLOBAL_CACHE.Skill.Data.GetActivation(self._skill_id))
            aftercast_ms = self._duration_to_ms(GLOBAL_CACHE.Skill.Data.GetAftercast(self._skill_id))
            if (
                primary_damage is None
                or adjacent_damage is None
                or cast_range is None
                or adjacent_radius is None
                or activation_ms is None
                or aftercast_ms is None
                or primary_damage <= 0.0
                or adjacent_damage <= 0.0
                or cast_range <= 0.0
                or adjacent_radius <= 0.0
            ):
                return None
            return _RuntimeParameters(
                primary_damage=primary_damage,
                adjacent_damage=adjacent_damage,
                cast_range=cast_range,
                adjacent_radius=adjacent_radius,
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
            from Py4GWCoreLib import Routines

            if self._resolve_current_slot() != slot or not self._skill_toggle_enabled(slot):
                return False
            if not bool(self.CanCastSkillSlot(slot)):
                return False
            can_cast = getattr(Routines.Checks.Skills, "CanCast", None)
            if not callable(can_cast) or not bool(can_cast()):
                return False
            skill_data = GLOBAL_CACHE.SkillBar.GetSkillData(slot)
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
            player_agent_id = int(Player.GetAgentID() or 0)
            if (
                player_agent_id <= 0
                or not bool(Agent.IsValid(player_agent_id))
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

    def _build_snapshot(self, parameters: _RuntimeParameters) -> tuple[UnnaturalSignetTargetObservation, ...] | None:
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

        observations: list[UnnaturalSignetTargetObservation] = []
        seen_ids: set[int] = set()
        for raw_agent_id in raw_enemy_ids:
            try:
                agent_id = int(raw_agent_id)
                if agent_id <= 0 or agent_id in seen_ids:
                    continue
                seen_ids.add(agent_id)
                if not Agent.IsValid(agent_id) or not Agent.IsAlive(agent_id) or Agent.IsDead(agent_id):
                    continue
                if not self._is_enemy(agent_id):
                    continue
                position = _position(Agent.GetXY(agent_id))
                normalized_health = _finite_float(Agent.GetHealth(agent_id))
                maximum_health = _finite_float(Agent.GetMaxHealth(agent_id))
                if (
                    position is None
                    or normalized_health is None
                    or maximum_health is None
                    or not 0.0 < normalized_health <= 1.0
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
                    UnnaturalSignetTargetObservation(
                        agent_id=agent_id,
                        x=position[0],
                        y=position[1],
                        current_hp=normalized_health * maximum_health,
                        distance_from_player=distance,
                        has_hex=bool(Agent.IsHexed(agent_id)),
                        has_enchantment=bool(Agent.IsEnchanted(agent_id)),
                        is_valid=True,
                        is_alive=True,
                        is_hostile=True,
                        is_targetable=self._target_is_allowed(agent_id),
                    )
                )
            except Exception:
                return None
        return tuple(sorted(observations, key=lambda observation: observation.agent_id))

    def _evaluate_live(
        self,
        parameters: _RuntimeParameters,
    ) -> UnnaturalSignetDecision | None:
        snapshot = self._build_snapshot(parameters)
        if snapshot is None:
            return None
        return evaluate_smart_unnatural_signet(
            snapshot,
            policy=UnnaturalSignetPolicy(
                primary_damage=parameters.primary_damage,
                adjacent_damage=parameters.adjacent_damage,
                cast_range=parameters.cast_range,
                adjacent_radius=parameters.adjacent_radius,
            ),
        )

    @staticmethod
    def _same_scoring_parameters(first: _RuntimeParameters, second: _RuntimeParameters) -> bool:
        return (
            first.primary_damage == second.primary_damage
            and first.adjacent_damage == second.adjacent_damage
            and first.cast_range == second.cast_range
            and first.adjacent_radius == second.adjacent_radius
        )

    def _final_revalidate(
        self,
        selected_agent_id: int,
        parameters: _RuntimeParameters,
    ) -> tuple[_RuntimeParameters, UnnaturalSignetCandidateEvaluation] | None:
        if not self._runtime_gate():
            return None
        slot = self._resolve_current_slot()
        if slot is None or not self._skill_readiness(slot):
            return None
        current_parameters = self._resolve_runtime_parameters()
        if current_parameters is None or not self._same_scoring_parameters(parameters, current_parameters):
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
        current_parameters, _selected = validated
        try:
            result = self.CastSkillID(
                skill_id=self._skill_id,
                log=False,
                aftercast_delay=current_parameters.aftercast_delay_ms,
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
        parameters = self._resolve_runtime_parameters()
        if parameters is None:
            return False
        decision = self._evaluate_live(parameters)
        if decision is None or decision.selected is None:
            return False
        return (yield from self._dispatch_selected(decision.selected.target_agent_id, parameters))


SUPPORTED_HANDLER_FACTORIES: Final[dict[int, type[SmartUnnaturalSignet]]] = {
    UNNATURAL_SIGNET_SKILL_ID: SmartUnnaturalSignet,
}


def get_supported_handler_factories() -> dict[int, type[SmartUnnaturalSignet]]:
    return dict(SUPPORTED_HANDLER_FACTORIES)


__all__ = [
    "CandidateReason",
    "DecisionReason",
    "SUPPORTED_HANDLER_FACTORIES",
    "UNNATURAL_SIGNET_NAME",
    "UNNATURAL_SIGNET_SKILL_ID",
    "UnnaturalSignetCandidateEvaluation",
    "UnnaturalSignetCandidateReason",
    "UnnaturalSignetDecision",
    "UnnaturalSignetDecisionReason",
    "UnnaturalSignetPolicy",
    "UnnaturalSignetTargetObservation",
    "SmartUnnaturalSignet",
    "evaluate_smart_unnatural_signet",
    "evaluate_unnatural_signet",
    "get_supported_handler_factories",
]
