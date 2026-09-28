"""Pure local choice between already-admitted smart interrupt proposals.

This module owns only local resource arbitration. It does not read runtime
state, queue work, claim D0, or dispatch a skill. Smart Cry proposals are
constructed publicly through the existing pure Smart Cry evaluator; Complicate
proposals retain the existing D2A immutable proposal as their payload.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from Py4GWCoreLib.Builds.Skills.SmartComplicate import COMPLICATE_SKILL_ID
from Py4GWCoreLib.Builds.Skills.SmartComplicate import SmartComplicateProposal
from Py4GWCoreLib.Builds.Skills.SmartCry import DEFAULT_POLICY
from Py4GWCoreLib.Builds.Skills.SmartCry import CryCandidateEvaluation
from Py4GWCoreLib.Builds.Skills.SmartCry import CryCandidateReason
from Py4GWCoreLib.Builds.Skills.SmartCry import CryCastKey
from Py4GWCoreLib.Builds.Skills.SmartCry import CryDecision
from Py4GWCoreLib.Builds.Skills.SmartCry import CryDecisionReason
from Py4GWCoreLib.Builds.Skills.SmartCry import CryEnemyObservation
from Py4GWCoreLib.Builds.Skills.SmartCry import CryPolicyParameters
from Py4GWCoreLib.Builds.Skills.SmartCry import evaluate_smart_cry
from Py4GWCoreLib.Builds.Skills.SmartMesmer import CombatSnapshot
from Py4GWCoreLib.Builds.Skills.SmartMesmer import PairwiseDistances


class SmartInterruptFamily(str, Enum):
    """The small set of smart-interrupt resources D2B can arbitrate."""

    CRY = "cry"
    COMPLICATE = "complicate"


CryHandledCastKey: TypeAlias = CryCastKey | tuple[int, int] | tuple[int, int, tuple[int, ...] | None]


@dataclass(frozen=True, slots=True, init=False)
class SmartCryInterruptProposal:
    """Chooser-facing adapter for one canonical Smart Cry policy result.

    The class is intentionally not directly constructible. Its public factory
    runs ``evaluate_smart_cry`` and adapts only that evaluator's selected
    result, while retaining the complete immutable Cry payload for later
    runtime validation.
    """

    interrupt_skill_id: int
    primary_cast_key: CryCastKey
    primary_cast_value: int
    primary_value_source: str
    decision: CryDecision
    evaluation: CryCandidateEvaluation

    @classmethod
    def from_smart_cry(
        cls,
        snapshot: CombatSnapshot,
        enemies: Iterable[CryEnemyObservation],
        *,
        cry_radius: float,
        cast_range: float,
        interrupt_skill_id: int,
        pairwise_distances: PairwiseDistances | None = None,
        handled_cast_keys: Iterable[CryHandledCastKey] = (),
        policy: CryPolicyParameters = DEFAULT_POLICY,
    ) -> SmartCryInterruptProposal | None:
        """Evaluate real Smart Cry inputs and adapt its canonical selection."""

        if not isinstance(snapshot, CombatSnapshot):
            raise ValueError("snapshot must be a Smart Mesmer CombatSnapshot")
        _require_skill_id(interrupt_skill_id)
        decision = evaluate_smart_cry(
            snapshot,
            enemies,
            cry_radius=cry_radius,
            cast_range=cast_range,
            pairwise_distances=pairwise_distances,
            handled_cast_keys=handled_cast_keys,
            policy=policy,
        )
        if decision.selected is None:
            return None
        return cls._from_canonical_decision(decision, interrupt_skill_id=interrupt_skill_id)

    @classmethod
    def _from_canonical_decision(
        cls,
        decision: CryDecision,
        *,
        interrupt_skill_id: int,
    ) -> SmartCryInterruptProposal:
        """Adapt an evaluator result; callers must use :meth:`from_smart_cry`."""

        _require_skill_id(interrupt_skill_id)
        if not isinstance(decision, CryDecision):
            raise ValueError("decision must be produced by Smart Cry policy")
        evaluation = decision.selected
        if (
            decision.reason is not CryDecisionReason.SELECTED
            or evaluation is None
            or evaluation.reason is not CryCandidateReason.ELIGIBLE
            or not evaluation.eligible
            or not any(candidate is evaluation for candidate in decision.canonical_candidates)
        ):
            raise ValueError("Smart Cry decision must contain an admitted canonical selection")

        primary_matches = tuple(
            cast_key
            for cast_key in evaluation.covered_cast_keys
            if cast_key.enemy_agent_id == evaluation.primary_agent_id
            and cast_key.enemy_skill_id == evaluation.primary_enemy_skill_id
        )
        if len(primary_matches) != 1:
            raise ValueError("Smart Cry selection must preserve its primary cast identity")
        primary_cast_key = primary_matches[0]
        proposal = object.__new__(cls)
        object.__setattr__(proposal, "interrupt_skill_id", interrupt_skill_id)
        object.__setattr__(proposal, "primary_cast_key", primary_cast_key)
        object.__setattr__(proposal, "primary_cast_value", evaluation.primary_cast_value)
        object.__setattr__(proposal, "primary_value_source", evaluation.primary_value_source)
        object.__setattr__(proposal, "decision", decision)
        object.__setattr__(proposal, "evaluation", evaluation)
        proposal._validate_complete_payload()
        return proposal

    def _validate_complete_payload(self) -> None:
        """Guard the private adapter boundary against contradictory test state."""

        evaluation = self.evaluation
        covered = tuple(evaluation.covered_cast_keys)
        feasible = frozenset(evaluation.feasible_covered_cast_keys)
        values = tuple(evaluation.covered_cast_values)
        if not covered or len(covered) != len(set(covered)) or any(key not in feasible for key in covered):
            raise ValueError("Smart Cry payload has inconsistent covered cast keys")
        if len(values) != len(covered) or len({key for key, _value in values}) != len(values):
            raise ValueError("Smart Cry payload must provide one value for every covered cast")
        values_by_key = dict(values)
        if set(values_by_key) != set(covered):
            raise ValueError("Smart Cry payload values must match covered cast keys")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 4
            for value in values_by_key.values()
        ):
            raise ValueError("Smart Cry covered cast values must remain in the established 0..4 domain")
        primary_key = self.primary_cast_key
        if primary_key not in values_by_key:
            raise ValueError("Smart Cry payload must include its primary cast value")
        if (
            primary_key.enemy_agent_id != evaluation.primary_agent_id
            or primary_key.enemy_skill_id != evaluation.primary_enemy_skill_id
            or self.primary_cast_value != evaluation.primary_cast_value
            or values_by_key[primary_key] != self.primary_cast_value
            or self.primary_value_source != evaluation.primary_value_source
            or self.primary_value_source == "unavailable"
        ):
            raise ValueError("Smart Cry proposal must faithfully preserve primary cast facts")
        additional_values = tuple(value for key, value in values_by_key.items() if key != primary_key)
        if (
            evaluation.additional_interrupt_count != len(additional_values)
            or evaluation.additional_interrupt_value != sum(additional_values)
            or evaluation.total_interrupt_value
            != evaluation.primary_cast_value + evaluation.additional_interrupt_value + evaluation.damage_bonus
            or evaluation.damage_bonus not in (0, 1)
        ):
            raise ValueError("Smart Cry payload has inconsistent collateral or damage facts")

    @property
    def family(self) -> SmartInterruptFamily:
        return SmartInterruptFamily.CRY

    @property
    def additional_interrupt_count(self) -> int:
        return self.evaluation.additional_interrupt_count

    @property
    def additional_interrupt_value(self) -> int:
        return self.evaluation.additional_interrupt_value

    @property
    def damage_bonus(self) -> int:
        return self.evaluation.damage_bonus


@dataclass(frozen=True, slots=True)
class SmartComplicateInterruptProposal:
    """Chooser-facing wrapper that preserves D2A's immutable proposal payload."""

    proposal: SmartComplicateProposal

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, SmartComplicateProposal):
            raise ValueError("proposal must be an admitted SmartComplicateProposal")

    @property
    def family(self) -> SmartInterruptFamily:
        return SmartInterruptFamily.COMPLICATE

    @property
    def interrupt_skill_id(self) -> int:
        return COMPLICATE_SKILL_ID

    @property
    def primary_cast_key(self) -> CryCastKey:
        return self.proposal.primary_cast_key

    @property
    def primary_cast_value(self) -> int:
        return self.proposal.primary_cast_value

    @property
    def primary_value_source(self) -> str:
        return self.proposal.primary_value_source

    @property
    def observed_same_skill_area_count(self) -> int:
        return len(self.proposal.observed_same_skill_area_agent_ids)


SmartInterruptProposal: TypeAlias = SmartCryInterruptProposal | SmartComplicateInterruptProposal


def _require_skill_id(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("interrupt_skill_id must be a positive integer")


def _cast_identity_key(cast_key: CryCastKey) -> tuple[int, int, tuple[int, ...]]:
    return (
        cast_key.enemy_agent_id,
        cast_key.enemy_skill_id,
        () if cast_key.observation_identity is None else cast_key.observation_identity,
    )


def _choose_same_primary(
    cry: SmartCryInterruptProposal,
    complicate: SmartComplicateInterruptProposal,
) -> SmartInterruptProposal:
    """Apply the approved explicit policy for one observed enemy cast."""

    if cry.primary_cast_value > complicate.primary_cast_value:
        return cry
    if complicate.primary_cast_value > cry.primary_cast_value:
        return complicate
    if cry.additional_interrupt_value > 0:
        return cry
    if complicate.observed_same_skill_area_count > 0:
        return complicate
    if cry.damage_bonus == 1:
        return cry
    return complicate


def _choose_different_primary(
    first: SmartInterruptProposal,
    second: SmartInterruptProposal,
) -> SmartInterruptProposal:
    """Choose by shared value and primary-cast identity only."""

    if first.primary_cast_value > second.primary_cast_value:
        return first
    if second.primary_cast_value > first.primary_cast_value:
        return second
    return min((first, second), key=lambda proposal: _cast_identity_key(proposal.primary_cast_key))


def choose_smart_interrupt(proposals: Iterable[SmartInterruptProposal]) -> SmartInterruptProposal | None:
    """Choose at most one local response, independent of input order."""

    supplied = tuple(proposals)
    families: set[SmartInterruptFamily] = set()
    for proposal in supplied:
        if not isinstance(proposal, (SmartCryInterruptProposal, SmartComplicateInterruptProposal)):
            raise ValueError("proposals must be admitted Smart Interrupt proposals")
        if proposal.family in families:
            raise ValueError("at most one admitted proposal per smart interrupt family is supported")
        families.add(proposal.family)
    if len(supplied) < 2:
        return supplied[0] if supplied else None
    first, second = supplied
    if first.primary_cast_key == second.primary_cast_key:
        if isinstance(first, SmartCryInterruptProposal):
            assert isinstance(second, SmartComplicateInterruptProposal)
            return _choose_same_primary(first, second)
        assert isinstance(first, SmartComplicateInterruptProposal)
        assert isinstance(second, SmartCryInterruptProposal)
        return _choose_same_primary(second, first)
    return _choose_different_primary(first, second)


__all__ = [
    "SmartComplicateInterruptProposal",
    "SmartCryInterruptProposal",
    "SmartInterruptFamily",
    "SmartInterruptProposal",
    "choose_smart_interrupt",
]
