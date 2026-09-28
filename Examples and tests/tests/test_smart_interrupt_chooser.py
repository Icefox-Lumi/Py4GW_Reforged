"""Offline D2B tests for pure local Smart Cry / Complicate arbitration."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"


def _install_package(name: str, path: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _isolated_smart_modules() -> Iterator[tuple[Any, Any, Any, Any]]:
    original = {
        name: module
        for name, module in sys.modules.items()
        if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.")
    }
    try:
        for name in tuple(sys.modules):
            if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib."):
                sys.modules.pop(name, None)
        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
        _install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
        mesmer = _load_module("Py4GWCoreLib.Builds.Skills.SmartMesmer", SKILLS_DIR / "SmartMesmer.py")
        cry = _load_module("Py4GWCoreLib.Builds.Skills.SmartCry", SKILLS_DIR / "SmartCry.py")
        complicate = _load_module("Py4GWCoreLib.Builds.Skills.SmartComplicate", SKILLS_DIR / "SmartComplicate.py")
        chooser = _load_module(
            "Py4GWCoreLib.Builds.Skills.SmartInterruptChooser", SKILLS_DIR / "SmartInterruptChooser.py"
        )
        yield mesmer, cry, complicate, chooser
    finally:
        for name in tuple(sys.modules):
            if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib."):
                sys.modules.pop(name, None)
        sys.modules.update(original)


with _isolated_smart_modules() as (smart_mesmer, smart_cry, smart_complicate, smart_chooser):
    CombatSnapshot = smart_mesmer.CombatSnapshot
    EnemyObservation = smart_mesmer.EnemyObservation
    CryCandidateEvaluation = smart_cry.CryCandidateEvaluation
    CryCandidateReason = smart_cry.CryCandidateReason
    CryCastKey = smart_cry.CryCastKey
    CryCastObservation = smart_cry.CryCastObservation
    CryDecision = smart_cry.CryDecision
    CryDecisionReason = smart_cry.CryDecisionReason
    CryEnemyObservation = smart_cry.CryEnemyObservation
    CryInterruptEvidence = smart_cry.CryInterruptEvidence
    CryOnsetConfidence = smart_cry.CryOnsetConfidence
    CrySkillCategory = smart_cry.CrySkillCategory
    CrySkillClassification = smart_cry.CrySkillClassification
    CryProposal = smart_chooser.SmartCryInterruptProposal
    ComplicateProposal = smart_chooser.SmartComplicateInterruptProposal
    choose_smart_interrupt = smart_chooser.choose_smart_interrupt
    evaluate_smart_cry = smart_cry.evaluate_smart_cry


class _AssessmentReason(str, Enum):
    FEASIBLE = "feasible"
    INSUFFICIENT_TIME = "insufficient_time"


class _OnsetConfidence(str, Enum):
    CONFIRMED = "confirmed_local_onset"


@dataclass(frozen=True, slots=True)
class _Assessment:
    feasible: bool
    reason: _AssessmentReason
    strict: bool
    target_agent_id: int
    our_skill_id: int
    enemy_skill_id: int
    observation_identity: tuple[int, int, int] | None
    observation_age_ms: int | None
    onset_confidence: _OnsetConfidence
    enemy_remaining_ms: int | None
    interrupt_budget_ms: int | None
    observation_stale: bool = False
    observation_untrusted: bool = False
    timing_invalid: bool = False
    geometry_available: bool = True


def _cry_evidence(
    agent_id: int,
    skill_id: int,
    *,
    sequence: int = 1,
    observation_identity: tuple[int, int, int] | None = None,
    omit_identity: bool = False,
    feasible: bool = True,
) -> Any:
    return CryInterruptEvidence(
        target_agent_id=agent_id,
        enemy_skill_id=skill_id,
        mechanically_feasible=feasible,
        timing_trusted=feasible,
        reason="feasible" if feasible else "not_feasible",
        cast_active=True,
        observation_identity=(
            None
            if omit_identity
            else (agent_id, skill_id, sequence) if observation_identity is None else observation_identity
        ),
        observation_age_ms=100,
        onset_confidence=CryOnsetConfidence.TRUSTED if feasible else CryOnsetConfidence.UNCERTAIN,
    )


def _cry_cast(
    agent_id: int,
    skill_id: int,
    *,
    sequence: int = 1,
    value_override: int | None = None,
    value_reason: str | None = None,
    observation_identity: tuple[int, int, int] | None = None,
    omit_identity: bool = False,
    feasible: bool = True,
) -> Any:
    return CryCastObservation(
        enemy_skill_id=skill_id,
        interrupt=_cry_evidence(
            agent_id,
            skill_id,
            sequence=sequence,
            observation_identity=observation_identity,
            omit_identity=omit_identity,
            feasible=feasible,
        ),
        classification=CrySkillClassification(),
        value_override=value_override,
        value_reason=value_reason,
    )


def _enemy(agent_id: int, x: float, *, cast: Any = None, target_allowed: bool = True) -> Any:
    return CryEnemyObservation(
        observation=EnemyObservation(agent_id, x, 0.0),
        distance_from_player=abs(x),
        target_allowed=target_allowed,
        current_cast=cast,
    )


def _snapshot(enemies: tuple[Any, ...]) -> Any:
    return CombatSnapshot(
        enemies=tuple(enemy.observation for enemy in enemies),
        observed_at=0.0,
        lifecycle_id="d2b-test",
    )


def _cry_decision(
    *,
    agent_id: int = 10,
    skill_id: int = 100,
    primary_value: int | None = None,
    collateral_values: tuple[int, ...] = (),
    damage_coverage: int = 0,
    sequence: int = 1,
    observation_identity: tuple[int, int, int] | None = None,
    handled: tuple[Any, ...] = (),
) -> Any:
    primary_cast = _cry_cast(
        agent_id,
        skill_id,
        sequence=sequence,
        value_override=primary_value,
        value_reason="d2b_primary" if primary_value is not None else None,
        observation_identity=observation_identity,
    )
    enemies = [_enemy(agent_id, 0.0, cast=primary_cast)]
    for index, value in enumerate(collateral_values, start=1):
        collateral_agent_id = agent_id + index
        collateral_skill_id = skill_id + index
        enemies.append(
            _enemy(
                collateral_agent_id,
                float(index),
                target_allowed=False,
                cast=_cry_cast(
                    collateral_agent_id,
                    collateral_skill_id,
                    value_override=value,
                    value_reason="d2b_collateral",
                ),
            )
        )
    while len(enemies) < damage_coverage:
        index = len(enemies)
        enemies.append(_enemy(agent_id + index, float(index)))
    return evaluate_smart_cry(
        _snapshot(tuple(enemies)),
        tuple(enemies),
        cry_radius=4.0,
        cast_range=20.0,
        handled_cast_keys=handled,
    )


def _cry_proposal(
    *,
    agent_id: int = 10,
    skill_id: int = 100,
    primary_value: int | None = None,
    collateral_values: tuple[int, ...] = (),
    damage_coverage: int = 0,
    sequence: int = 1,
    observation_identity: tuple[int, int, int] | None = None,
    omit_identity: bool = False,
    handled: tuple[Any, ...] = (),
) -> Any:
    enemies = [
        _enemy(
            agent_id,
            0.0,
            cast=_cry_cast(
                agent_id,
                skill_id,
                sequence=sequence,
                value_override=primary_value,
                value_reason="d2b_primary" if primary_value is not None else None,
                observation_identity=observation_identity,
                omit_identity=omit_identity,
            ),
        )
    ]
    for index, value in enumerate(collateral_values, start=1):
        collateral_agent_id = agent_id + index
        collateral_skill_id = skill_id + index
        enemies.append(
            _enemy(
                collateral_agent_id,
                float(index),
                target_allowed=False,
                cast=_cry_cast(
                    collateral_agent_id,
                    collateral_skill_id,
                    value_override=value,
                    value_reason="d2b_collateral",
                ),
            )
        )
    while len(enemies) < damage_coverage:
        index = len(enemies)
        enemies.append(_enemy(agent_id + index, float(index)))
    enemies_tuple = tuple(enemies)
    proposal = CryProposal.from_smart_cry(
        _snapshot(enemies_tuple),
        enemies_tuple,
        cry_radius=4.0,
        cast_range=20.0,
        interrupt_skill_id=57,
        handled_cast_keys=handled,
    )
    assert proposal is not None, "fixture expected an admitted authentic Smart Cry result"
    return proposal


def _complicate_proposal(
    *,
    agent_id: int = 10,
    skill_id: int = 100,
    value: int = 2,
    sequence: int = 1,
    same_skill_agents: tuple[int, ...] = (),
    duration_rank: int | None = None,
) -> Any:
    cry_decision = _cry_decision(agent_id=agent_id, skill_id=skill_id, primary_value=value, collateral_values=(1,))
    assert cry_decision.selected is not None
    cast_value = smart_complicate.ComplicateCastValue.from_smart_cry_evaluation(
        cry_decision.selected,
        expected_agent_id=agent_id,
        expected_enemy_skill_id=skill_id,
    )
    assessment = _Assessment(
        feasible=True,
        reason=_AssessmentReason.FEASIBLE,
        strict=True,
        target_agent_id=agent_id,
        our_skill_id=smart_complicate.COMPLICATE_SKILL_ID,
        enemy_skill_id=skill_id,
        observation_identity=(agent_id, skill_id, sequence),
        observation_age_ms=100,
        onset_confidence=_OnsetConfidence.CONFIRMED,
        enemy_remaining_ms=800,
        interrupt_budget_ms=400,
    )
    duration = None
    if duration_rank is not None:
        duration = smart_complicate.ComplicateDisableDurationEvidence.from_skill_progression(
            smart_complicate.COMPLICATE_SKILL_ID,
            duration_rank,
            [("Domination Magic", "Duration", {duration_rank: float(duration_rank)})],
        )
    decision = smart_complicate.evaluate_smart_complicate(
        (
            smart_complicate.ComplicateCandidateObservation(
                primary_agent_id=agent_id,
                primary_enemy_skill_id=skill_id,
                mechanical_assessment=smart_complicate.ComplicateInterruptEvidence.from_assessment(assessment),
                primary_value=cast_value,
                affected_area_casts=tuple(
                    smart_complicate.ComplicateObservedCast(other_id, skill_id) for other_id in same_skill_agents
                ),
                disable_duration=duration,
            ),
        )
    )
    assert decision.selected is not None
    return ComplicateProposal(decision.selected)


def test_no_proposals_returns_no_choice() -> None:
    assert choose_smart_interrupt(()) is None


def test_only_cry_and_complicate_are_selected() -> None:
    cry = _cry_proposal(primary_value=2)
    complicate = _complicate_proposal(value=2)
    assert choose_smart_interrupt((cry,)) is cry
    assert choose_smart_interrupt((complicate,)) is complicate


def test_public_cry_factory_requires_authentic_evaluator_output() -> None:
    proposal = _cry_proposal(primary_value=2)
    assert proposal.decision.selected is proposal.evaluation
    assert proposal.primary_cast_key == CryCastKey(10, 100, (10, 100, 1))
    try:
        CryProposal(1, proposal.primary_cast_key, 2, "generic", proposal.decision, proposal.evaluation)
    except TypeError:
        pass
    else:
        raise AssertionError("Smart Cry proposal was directly constructible")

    evaluation = replace(
        proposal.evaluation,
        covered_cast_values=proposal.evaluation.covered_cast_values[:-1],
    )
    malformed = CryDecision(
        selected=evaluation,
        reason=CryDecisionReason.SELECTED,
        candidates=(evaluation,),
        canonical_candidates=(evaluation,),
    )
    try:
        CryProposal._from_canonical_decision(malformed, interrupt_skill_id=57)
    except ValueError:
        pass
    else:
        raise AssertionError("contradictory Cry payload entered the private adapter")


def test_authentic_zero_primary_and_positive_collateral_are_preserved() -> None:
    proposal = _cry_proposal(primary_value=0, collateral_values=(1, 1))
    assert proposal.primary_cast_value == 0
    assert proposal.additional_interrupt_value == 2
    assert proposal.additional_interrupt_count == 2
    assert len(proposal.evaluation.covered_cast_values) == 3
    assert choose_smart_interrupt((proposal,)) is proposal


def test_same_primary_unequal_value_wins_before_secondary_facts() -> None:
    cry = _cry_proposal(primary_value=3, collateral_values=(0,))
    complicate = _complicate_proposal(value=2, same_skill_agents=(11,), duration_rank=9)
    assert choose_smart_interrupt((complicate, cry)) is cry


def test_same_primary_positive_additional_interrupt_value_prefers_cry() -> None:
    cry = _cry_proposal(primary_value=2, collateral_values=(1,))
    complicate = _complicate_proposal(value=2)
    assert cry.additional_interrupt_value == 1
    assert choose_smart_interrupt((complicate, cry)) is cry


def test_same_primary_zero_value_collateral_does_not_activate_cry_preference() -> None:
    cry = _cry_proposal(primary_value=2, collateral_values=(0,))
    complicate = _complicate_proposal(value=2)
    assert cry.additional_interrupt_count == 1
    assert cry.additional_interrupt_value == 0
    assert choose_smart_interrupt((cry, complicate)) is complicate


def test_same_primary_collateral_payload_preserves_multiple_values() -> None:
    cry = _cry_proposal(primary_value=2, collateral_values=(3, 1))
    assert cry.additional_interrupt_count == 2
    assert cry.additional_interrupt_value == 4
    assert choose_smart_interrupt((cry, _complicate_proposal(value=2))) is cry


def test_same_primary_complicate_exact_skill_area_evidence_is_next_branch() -> None:
    cry = _cry_proposal(primary_value=2)
    complicate = _complicate_proposal(value=2, same_skill_agents=(11, 12))
    assert complicate.observed_same_skill_area_count == 2
    assert choose_smart_interrupt((cry, complicate)) is complicate


def test_same_primary_bounded_cry_damage_is_used_after_other_factors() -> None:
    cry = _cry_proposal(primary_value=None, damage_coverage=4)
    complicate = _complicate_proposal(value=1)
    assert cry.damage_bonus == 1
    assert choose_smart_interrupt((cry, complicate)) is cry


def test_complicate_duration_never_affects_same_primary_choice() -> None:
    cry = _cry_proposal(primary_value=2)
    unresolved = _complicate_proposal(value=2)
    resolved = _complicate_proposal(value=2, duration_rank=9)
    assert unresolved.proposal.disable_duration is None
    assert resolved.proposal.disable_duration is not None
    assert choose_smart_interrupt((cry, unresolved)) is unresolved
    assert choose_smart_interrupt((cry, resolved)) is resolved
    damage_cry = _cry_proposal(primary_value=2, damage_coverage=4)
    assert choose_smart_interrupt((damage_cry, resolved)) is damage_cry


def test_same_primary_final_tie_explicitly_prefers_complicate() -> None:
    cry = _cry_proposal(primary_value=2)
    complicate = _complicate_proposal(value=2)
    assert choose_smart_interrupt((cry, complicate)) is complicate


def test_different_primary_unequal_value_ignores_secondary_facts() -> None:
    cry = _cry_proposal(agent_id=20, primary_value=2, collateral_values=(3,), damage_coverage=4)
    complicate = _complicate_proposal(agent_id=10, value=3, same_skill_agents=(11,), duration_rank=12)
    assert choose_smart_interrupt((cry, complicate)) is complicate


def test_different_primary_equal_value_uses_primary_cast_identity_only() -> None:
    cry = _cry_proposal(agent_id=20, primary_value=2, collateral_values=(3,), damage_coverage=4)
    complicate = _complicate_proposal(agent_id=10, value=2, same_skill_agents=(11,), duration_rank=12)
    assert choose_smart_interrupt((cry, complicate)) is complicate
    assert choose_smart_interrupt((complicate, cry)) is complicate


def test_different_primary_cry_collateral_cannot_redirect_target_choice() -> None:
    cry = _cry_proposal(agent_id=20, primary_value=2, collateral_values=(3,))
    complicate = _complicate_proposal(agent_id=10, value=2)
    assert choose_smart_interrupt((cry, complicate)) is complicate


def test_different_primary_complicate_area_cannot_redirect_target_choice() -> None:
    cry = _cry_proposal(agent_id=10, primary_value=2)
    complicate = _complicate_proposal(agent_id=20, value=2, same_skill_agents=(21,))
    assert choose_smart_interrupt((cry, complicate)) is cry


def test_different_primary_cry_damage_cannot_redirect_target_choice() -> None:
    cry = _cry_proposal(agent_id=20, primary_value=2, damage_coverage=4)
    complicate = _complicate_proposal(agent_id=10, value=2)
    assert choose_smart_interrupt((cry, complicate)) is complicate


def test_different_primary_duration_cannot_redirect_target_choice() -> None:
    cry = _cry_proposal(agent_id=10, primary_value=2)
    complicate = _complicate_proposal(agent_id=20, value=2, duration_rank=15)
    assert choose_smart_interrupt((cry, complicate)) is cry


def test_repeated_and_reversed_choices_are_deterministic() -> None:
    cry = _cry_proposal(agent_id=20, primary_value=2, damage_coverage=4)
    complicate = _complicate_proposal(agent_id=10, value=2, same_skill_agents=(11,))
    first = choose_smart_interrupt((cry, complicate))
    assert first is not None
    assert first is choose_smart_interrupt((complicate, cry))
    assert first is choose_smart_interrupt((cry, complicate))


def test_none_observation_identity_is_valid_and_preserved() -> None:
    proposal = _cry_proposal(primary_value=0, collateral_values=(2,), omit_identity=True)
    assert proposal.primary_cast_key.observation_identity is None


def test_handled_or_unavailable_cry_inputs_are_rejected_by_upstream_policy() -> None:
    handled = _cry_decision(agent_id=10, skill_id=100, primary_value=2, handled=(CryCastKey(10, 100),))
    assert handled.selected is None
    unavailable_enemy = _enemy(10, 0.0)
    unavailable = evaluate_smart_cry(
        _snapshot((unavailable_enemy,)),
        (unavailable_enemy,),
        cry_radius=4.0,
        cast_range=20.0,
    )
    assert unavailable.selected is None


def test_duplicate_cry_and_complicate_inputs_are_rejected() -> None:
    cry = _cry_proposal(primary_value=2)
    complicate = _complicate_proposal(value=2)
    for duplicate in (
        (cry, _cry_proposal(agent_id=11, primary_value=2)),
        (complicate, _complicate_proposal(agent_id=11, value=2)),
    ):
        try:
            choose_smart_interrupt(duplicate)
        except ValueError as error:
            assert "one admitted proposal per" in str(error)
        else:
            raise AssertionError("duplicate proposal family was accepted")


def test_d2a_complicate_payload_is_preserved_without_duration_policy() -> None:
    complicate = _complicate_proposal(value=2, same_skill_agents=(12, 11), duration_rank=9)
    assert complicate.proposal.observed_same_skill_area_agent_ids == (11, 12)
    assert complicate.proposal.disable_duration_seconds == 9
    assert complicate.proposal.primary_cast_key == CryCastKey(10, 100, (10, 100, 1))


def test_unsupported_raw_input_cannot_enter_selection() -> None:
    try:
        choose_smart_interrupt((object(),))
    except ValueError as error:
        assert "admitted Smart Interrupt proposals" in str(error)
    else:
        raise AssertionError("untyped input entered selection")
