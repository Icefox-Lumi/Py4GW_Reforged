"""Deterministic offline policy tests for Spiritual Pain D3C-B."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import FrozenInstanceError
from dataclasses import fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Skills" / "SmartSpiritualPain.py"
MODULE_NAME = "_d3c_b_smart_spiritual_pain"
MODULE_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None, f"could not load {MODULE_PATH}"
smart_spiritual_pain: Any = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_NAME] = smart_spiritual_pain
MODULE_SPEC.loader.exec_module(smart_spiritual_pain)


CandidateReason = smart_spiritual_pain.CandidateReason
DecisionReason = smart_spiritual_pain.DecisionReason
HostileSummonClassification = smart_spiritual_pain.HostileSummonClassification
Evidence = smart_spiritual_pain.SpiritualPainEvidence
Policy = smart_spiritual_pain.SpiritualPainPolicy
TargetObservation = smart_spiritual_pain.SpiritualPainTargetObservation

MINION_FLAG = smart_spiritual_pain.NPC_MINION_FLAG
SPIRIT_FLAG = smart_spiritual_pain.NPC_SPIRIT_FLAG
SPIRIT_TYPE_BIT = smart_spiritual_pain.TYPE_MAP_SPIRIT_BIT


def _evidence(
    *,
    valid: bool | None = True,
    living: bool | None = True,
    alive: bool | None = True,
    enemy: bool | None = True,
    npc_flags: int | None = None,
    type_map: int | None = None,
) -> Any:
    return Evidence(
        is_valid=valid,
        is_living=living,
        is_alive=alive,
        is_direct_enemy=enemy,
        npc_flags=npc_flags,
        type_map=type_map,
    )


def _target(
    agent_id: int,
    *,
    x: float = 0.0,
    y: float = 0.0,
    hp: float = 100.0,
    distance: float = 20.0,
    valid: bool | None = True,
    living: bool | None = True,
    alive: bool | None = True,
    enemy: bool | None = True,
    npc_flags: int | None = None,
    type_map: int | None = None,
) -> Any:
    return TargetObservation(
        agent_id=agent_id,
        x=x,
        y=y,
        current_hp=hp,
        distance_from_player=distance,
        evidence=_evidence(
            valid=valid,
            living=living,
            alive=alive,
            enemy=enemy,
            npc_flags=npc_flags,
            type_map=type_map,
        ),
    )


def _policy(*, primary: float = 60.0, summon: float = 30.0) -> Any:
    return Policy(primary_damage=primary, summon_damage=summon)


def _decision(candidates: tuple[Any, ...], *, primary: float = 60.0, summon: float = 30.0) -> Any:
    return smart_spiritual_pain.evaluate_smart_spiritual_pain(
        candidates,
        policy=_policy(primary=primary, summon=summon),
    )


def _confirmed_minion(agent_id: int, **kwargs: Any) -> Any:
    return _target(agent_id, npc_flags=MINION_FLAG, **kwargs)


def _confirmed_spirit(agent_id: int, **kwargs: Any) -> Any:
    return _target(agent_id, npc_flags=SPIRIT_FLAG, type_map=SPIRIT_TYPE_BIT, **kwargs)


def test_minion_rule_requires_direct_enemy_living_evidence_and_npc_flag() -> None:
    confirmed = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=MINION_FLAG))
    missing_flag = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=0))
    non_enemy = smart_spiritual_pain.classify_hostile_summon(_evidence(enemy=False, npc_flags=MINION_FLAG))
    invalid = smart_spiritual_pain.classify_hostile_summon(_evidence(valid=False, npc_flags=MINION_FLAG))
    non_living = smart_spiritual_pain.classify_hostile_summon(_evidence(living=False, npc_flags=MINION_FLAG))
    dead = smart_spiritual_pain.classify_hostile_summon(_evidence(alive=False, npc_flags=MINION_FLAG))
    missing_flags = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=None))

    assert confirmed is HostileSummonClassification.CONFIRMED_HOSTILE_SUMMON
    assert missing_flag is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert non_enemy is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert invalid is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert non_living is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert dead is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert missing_flags is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON


def test_spirit_rule_requires_both_npc_flag_and_type_map_bit() -> None:
    confirmed = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=SPIRIT_FLAG, type_map=SPIRIT_TYPE_BIT))
    missing_type_bit = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=SPIRIT_FLAG, type_map=0))
    missing_npc_flag = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=0, type_map=SPIRIT_TYPE_BIT))
    non_enemy = smart_spiritual_pain.classify_hostile_summon(
        _evidence(enemy=False, npc_flags=SPIRIT_FLAG, type_map=SPIRIT_TYPE_BIT)
    )
    missing_type_map = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=SPIRIT_FLAG, type_map=None))
    missing_npc_flags = smart_spiritual_pain.classify_hostile_summon(
        _evidence(npc_flags=None, type_map=SPIRIT_TYPE_BIT)
    )

    assert confirmed is HostileSummonClassification.CONFIRMED_HOSTILE_SUMMON
    assert missing_type_bit is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert missing_npc_flag is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert non_enemy is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert missing_type_map is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert missing_npc_flags is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON


def test_classifier_fails_closed_for_unknown_and_rejected_inference_signals() -> None:
    generic_spawned_state = smart_spiritual_pain.classify_hostile_summon(
        _evidence(npc_flags=0, type_map=SPIRIT_TYPE_BIT)
    )
    ordinary_enemy = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=0, type_map=0))
    pet_style_flag = smart_spiritual_pain.classify_hostile_summon(_evidence(npc_flags=0x0008, type_map=0))
    friendly_spirit = smart_spiritual_pain.classify_hostile_summon(
        _evidence(enemy=False, npc_flags=SPIRIT_FLAG, type_map=SPIRIT_TYPE_BIT)
    )
    friendly_minion = smart_spiritual_pain.classify_hostile_summon(_evidence(enemy=False, npc_flags=MINION_FLAG))
    forbidden_fields = {field.name for field in fields(Evidence)}

    assert generic_spawned_state is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert ordinary_enemy is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert pet_style_flag is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert friendly_spirit is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert friendly_minion is HostileSummonClassification.NOT_CONFIRMED_HOSTILE_SUMMON
    assert forbidden_fields.isdisjoint({"owner", "owner_id", "profession", "model_id", "name", "is_spawned"})


def test_evidence_and_target_observations_are_immutable() -> None:
    evidence = _evidence(npc_flags=MINION_FLAG)
    target = _target(10)

    try:
        evidence.npc_flags = 0
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("Spiritual Pain evidence must be immutable")
    try:
        target.current_hp = 1.0
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("Spiritual Pain target observations must be immutable")


def test_ordinary_primary_without_summons_gets_unconditional_primary_value() -> None:
    decision = _decision((_target(10, hp=40.0),))

    assert decision.reason is DecisionReason.SELECTED
    assert decision.selected is not None
    assert decision.selected.target_agent_id == 10
    assert decision.selected.useful_primary_damage == 40.0
    assert decision.selected.useful_special_summon_damage == 0.0
    assert decision.selected.useful_total_damage == 40.0
    assert decision.selected.special_summon_agent_ids == ()


def test_one_confirmed_hostile_summon_in_area_adds_special_value() -> None:
    decision = _decision((_target(10), _confirmed_minion(11, x=100.0, y=0.0, hp=20.0)))

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 10
    assert decision.selected.special_summon_agent_ids == (11,)
    assert decision.selected.useful_special_summon_damage == 20.0
    assert decision.selected.useful_total_damage == 80.0


def test_multiple_confirmed_hostile_summons_are_all_counted_in_area() -> None:
    decision = _decision(
        (
            _target(10),
            _confirmed_minion(11, x=100.0, hp=20.0),
            _confirmed_spirit(12, x=200.0, hp=40.0),
        )
    )

    assert decision.selected is not None
    assert decision.selected.special_summon_agent_ids == (11, 12)
    assert decision.selected.special_summon_count == 2
    assert decision.selected.useful_special_summon_damage == 50.0
    assert decision.selected.useful_total_damage == 110.0


def test_ordinary_unknown_and_unconfirmed_enemies_contribute_no_special_value() -> None:
    decision = _decision(
        (
            _target(10),
            _target(11, x=10.0, hp=20.0),
            _target(12, x=20.0, hp=20.0, npc_flags=SPIRIT_FLAG, type_map=0),
            _target(13, x=30.0, hp=20.0, npc_flags=None, type_map=SPIRIT_TYPE_BIT),
        )
    )

    assert decision.selected is not None
    assert decision.selected.special_summon_agent_ids == ()
    assert decision.selected.useful_special_summon_damage == 0.0
    assert decision.selected.useful_total_damage == 60.0


def test_dead_invalid_and_non_enemy_summons_contribute_no_special_value() -> None:
    decision = _decision(
        (
            _target(10),
            _confirmed_minion(11, x=10.0, alive=False),
            _confirmed_minion(12, x=20.0, valid=False),
            _confirmed_minion(13, x=30.0, enemy=False),
        )
    )

    assert decision.selected is not None
    assert decision.selected.special_summon_agent_ids == ()


def test_summon_outside_area_has_zero_special_value() -> None:
    decision = _decision((_target(10), _confirmed_minion(11, x=322.001, hp=100.0)))

    assert decision.selected is not None
    assert decision.selected.special_summon_agent_ids == ()
    assert decision.selected.useful_total_damage == 60.0


def test_exact_area_boundary_is_inclusive() -> None:
    decision = _decision((_target(10), _confirmed_minion(11, x=322.0, hp=100.0)))

    assert decision.selected is not None
    assert decision.selected.special_summon_agent_ids == (11,)
    assert decision.selected.useful_total_damage == 90.0


def test_primary_and_summon_useful_damage_are_capped_by_current_hp() -> None:
    decision = _decision(
        (
            _target(10, hp=5.0),
            _confirmed_minion(11, x=10.0, hp=7.0),
            _confirmed_spirit(12, x=20.0, hp=100.0),
        )
    )

    capped_candidate = next(candidate for candidate in decision.candidates if candidate.target_agent_id == 10)
    assert capped_candidate.useful_primary_damage == 5.0
    assert capped_candidate.useful_special_summon_damage == 37.0
    assert capped_candidate.useful_total_damage == 42.0


def test_observation_numeric_fields_reject_text_and_non_finite_values() -> None:
    base_values: dict[str, Any] = {
        "agent_id": 10,
        "x": 0.0,
        "y": 0.0,
        "current_hp": 100.0,
        "distance_from_player": 20.0,
        "evidence": _evidence(),
    }
    invalid_values = (
        ("x", "3.14"),
        ("y", "3.14"),
        ("current_hp", "100"),
        ("distance_from_player", "10"),
        ("current_hp", float("nan")),
        ("distance_from_player", float("inf")),
        ("x", float("-inf")),
    )

    for field_name, invalid_value in invalid_values:
        malformed_values = {**base_values, field_name: invalid_value}
        try:
            TargetObservation(**malformed_values)
        except (TypeError, ValueError):
            continue
        raise AssertionError(f"invalid {field_name} value must be rejected")

    normalized = TargetObservation(
        agent_id=10,
        x=1,
        y=2,
        current_hp=100,
        distance_from_player=20,
        evidence=_evidence(),
    )
    assert (normalized.x, normalized.y, normalized.current_hp, normalized.distance_from_player) == (
        1.0,
        2.0,
        100.0,
        20.0,
    )


def test_primary_itself_is_excluded_even_when_confirmed_as_a_summon() -> None:
    decision = _decision((_confirmed_minion(10, hp=40.0),))

    assert decision.selected is not None
    assert decision.selected.primary_summon_classification is HostileSummonClassification.CONFIRMED_HOSTILE_SUMMON
    assert decision.selected.special_summon_agent_ids == ()
    assert decision.selected.useful_primary_damage == 40.0
    assert decision.selected.useful_total_damage == 40.0


def test_non_positive_special_summon_agent_ids_fail_closed() -> None:
    for invalid_agent_id in (0, -1):
        decision = _decision((_target(1), _confirmed_minion(invalid_agent_id, x=10.0, hp=100.0)))

        assert decision.selected is not None
        assert decision.selected.target_agent_id == 1
        assert decision.selected.special_summon_agent_ids == ()
        assert decision.selected.special_summon_count == 0
        assert decision.selected.useful_special_summon_damage == 0.0
        assert decision.selected.useful_total_damage == 60.0

    positive_id_decision = _decision((_target(1), _confirmed_minion(2, x=10.0, hp=100.0)))

    assert positive_id_decision.selected is not None
    assert positive_id_decision.selected.target_agent_id == 1
    assert positive_id_decision.selected.special_summon_agent_ids == (2,)
    assert positive_id_decision.selected.special_summon_count == 1
    assert positive_id_decision.selected.useful_special_summon_damage == 30.0
    assert positive_id_decision.selected.useful_total_damage == 90.0


def test_ordinary_primary_surrounded_by_summons_and_summoned_primary_with_other_summon() -> None:
    ordinary_primary = _decision(
        (
            _target(10),
            _confirmed_minion(11, x=10.0, hp=20.0),
            _confirmed_spirit(12, x=20.0, hp=30.0),
        )
    )
    summoned_primary = _decision(
        (
            _confirmed_minion(20),
            _confirmed_spirit(21, x=10.0, hp=30.0),
        )
    )

    assert ordinary_primary.selected is not None
    assert ordinary_primary.selected.target_agent_id == 10
    assert ordinary_primary.selected.useful_total_damage == 110.0
    assert summoned_primary.selected is not None
    assert summoned_primary.selected.target_agent_id == 20
    assert summoned_primary.selected.special_summon_agent_ids == (21,)


def test_highest_total_useful_value_wins_without_a_summon_preference() -> None:
    decision = _decision(
        (
            _target(10, hp=100.0),
            _confirmed_minion(20, x=500.0, hp=100.0),
        )
    )

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 10


def test_ties_use_special_victim_count_then_distance_then_agent_id() -> None:
    count_tie = _decision(
        (
            _target(10, hp=60.0, distance=30.0),
            _confirmed_minion(11, x=10.0, hp=15.0),
            _confirmed_minion(12, x=20.0, hp=15.0),
            _target(20, x=1000.0, hp=60.0, distance=20.0),
            _confirmed_minion(21, x=1010.0, hp=30.0),
        )
    )
    distance_tie = _decision((_target(10, distance=30.0), _target(20, distance=20.0)))
    agent_id_tie = _decision((_target(20, distance=20.0), _target(10, distance=20.0)))

    count_candidates = {candidate.target_agent_id: candidate for candidate in count_tie.candidates}
    assert count_candidates[10].useful_total_damage == count_candidates[20].useful_total_damage == 90.0
    assert count_candidates[10].special_summon_count == 2
    assert count_candidates[20].special_summon_count == 1
    assert count_tie.selected is not None
    assert count_tie.selected.target_agent_id == 10
    assert distance_tie.selected is not None
    assert distance_tie.selected.target_agent_id == 20
    assert agent_id_tie.selected is not None
    assert agent_id_tie.selected.target_agent_id == 10


def test_selection_is_independent_of_input_iteration_order() -> None:
    ordered = (
        _target(30, x=900.0, hp=50.0),
        _target(10, hp=60.0),
        _confirmed_minion(20, x=10.0, hp=30.0),
        _confirmed_spirit(40, x=20.0, hp=40.0),
    )
    reversed_input = tuple(reversed(ordered))

    first = _decision(ordered)
    second = _decision(reversed_input)

    assert first == second
    assert first.selected is not None
    assert first.selected.target_agent_id == 10


def test_primary_candidates_require_valid_living_alive_direct_enemy_and_cast_range() -> None:
    decision = _decision(
        (
            _target(10, valid=False),
            _target(11, living=False),
            _target(12, alive=False),
            _target(13, enemy=False),
            _target(14, distance=1248.001),
            _target(15, hp=25.0),
        )
    )

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 15
    reasons = {candidate.target_agent_id: candidate.reason for candidate in decision.candidates}
    assert reasons[10] is CandidateReason.INVALID_TARGET
    assert reasons[11] is CandidateReason.INVALID_TARGET
    assert reasons[12] is CandidateReason.INVALID_TARGET
    assert reasons[13] is CandidateReason.INVALID_TARGET
    assert reasons[14] is CandidateReason.OUT_OF_CAST_RANGE


def test_missing_primary_evidence_is_not_selected() -> None:
    missing = TargetObservation(
        agent_id=10,
        x=None,
        y=None,
        current_hp=None,
        distance_from_player=None,
        evidence=Evidence(),
    )
    decision = _decision((missing,))

    assert decision.selected is None
    assert decision.reason is DecisionReason.NO_ELIGIBLE_CANDIDATE
    assert decision.candidates[0].reason is CandidateReason.MISSING_EVIDENCE


def test_invalid_policy_fails_closed() -> None:
    decision = smart_spiritual_pain.evaluate_smart_spiritual_pain(
        (_target(10),),
        policy=Policy(primary_damage=0.0, summon_damage=30.0),
    )

    assert decision.selected is None
    assert decision.reason is DecisionReason.INVALID_POLICY


def test_rank_zero_normal_rank_and_rank_twenty_one_use_exact_progression() -> None:
    rank_zero = smart_spiritual_pain.resolve_spiritual_pain_damage(0)
    rank_ten = smart_spiritual_pain.resolve_spiritual_pain_damage(10)
    rank_twenty_one = smart_spiritual_pain.resolve_spiritual_pain_damage(21)

    assert rank_zero is not None and (rank_zero.primary_damage, rank_zero.summon_damage) == (15, 25)
    assert rank_ten is not None and (rank_ten.primary_damage, rank_ten.summon_damage) == (55, 92)
    assert rank_twenty_one is not None and (rank_twenty_one.primary_damage, rank_twenty_one.summon_damage) == (99, 165)
    assert Policy.from_domination_rank(21) == Policy(primary_damage=99, summon_damage=165)


def test_missing_invalid_and_out_of_range_rank_fails_closed_without_clamping() -> None:
    for rank in (None, -1, 22, 100, 1.0, True, "10"):
        assert smart_spiritual_pain.resolve_spiritual_pain_damage(rank) is None, f"rank {rank!r} must fail closed"
        assert Policy.from_domination_rank(rank) is None, f"rank {rank!r} must not be clamped"


def test_useful_damage_helper_fails_closed_and_caps_positive_damage() -> None:
    assert smart_spiritual_pain.useful_damage(60.0, 5.0) == 5.0
    assert smart_spiritual_pain.useful_damage(5.0, 60.0) == 5.0
    assert smart_spiritual_pain.useful_damage(60.0, 0.0) == 0.0
    assert smart_spiritual_pain.useful_damage(None, 60.0) == 0.0
