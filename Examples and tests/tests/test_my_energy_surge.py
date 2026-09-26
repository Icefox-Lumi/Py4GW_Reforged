"""Deterministic offline behavior tests for the pure Checkpoint B policy."""

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"
POLICY_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Mesmer" / "Me_Any" / "My Energy Surge.py"
SMART_NAME = "Py4GWCoreLib.Builds.Skills.SmartMesmer"
POLICY_NAME = "Py4GWCoreLib.Builds.Mesmer.Me_Any.My_Energy_Surge"


def _install_package(name: str, path: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package


_install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
_install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
_install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
_install_package("Py4GWCoreLib.Builds.Mesmer", ROOT / "Py4GWCoreLib" / "Builds" / "Mesmer")
_install_package("Py4GWCoreLib.Builds.Mesmer.Me_Any", POLICY_PATH.parent)


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smart_mesmer = _load_module(SMART_NAME, SKILLS_DIR / "SmartMesmer.py")
policy = _load_module(POLICY_NAME, POLICY_PATH)

CombatSnapshot = smart_mesmer.CombatSnapshot
EnemyObservation = smart_mesmer.EnemyObservation
DecisionReason = policy.DecisionReason
CandidateReason = policy.CandidateReason
EnergySurgeEnemyObservation = policy.EnergySurgeEnemyObservation
EnergySurgePolicy = policy.EnergySurgePolicy
ForeignReservationProjection = policy.ForeignReservationProjection


def _enemy(
    agent_id: int,
    x: float,
    *,
    profession: str = "Warrior",
    hp: float = 0.50,
    distance: float = 10.0,
    caster: bool = False,
    casting: bool = False,
) -> Any:
    return EnergySurgeEnemyObservation(
        observation=EnemyObservation(agent_id, x, 0.0),
        profession=profession,
        health_fraction=hp,
        distance_from_player=distance,
        is_caster=caster,
        is_casting=casting,
    )


def _snapshot(*enemies: Any) -> Any:
    return CombatSnapshot(
        enemies=tuple(enemy.observation for enemy in enemies),
        observed_at=0.0,
        lifecycle_id="policy-test",
    )


def _evaluate(
    enemies: tuple[Any, ...],
    *,
    local_drain: float | None = 10.0,
    aoe_radius: float = 4.0,
    cast_range: float = 50.0,
    group_link_radius: float = 4.0,
    reservations: tuple[Any, ...] = (),
    policy: Any = None,
) -> Any:
    return policy_module().evaluate_energy_surge(
        _snapshot(*enemies),
        enemies,
        aoe_radius=aoe_radius,
        cast_range=cast_range,
        group_link_radius=group_link_radius,
        local_resolved_drain=local_drain,
        reservations=reservations,
        policy=policy if policy is not None else policy_module().DEFAULT_POLICY,
    )


def policy_module() -> Any:
    return policy


def test_dense_useful_packet_beats_isolated_lower_value_target() -> None:
    enemies = (
        _enemy(10, 0.0, profession="Elementalist"),
        _enemy(11, 2.0, profession="Warrior"),
        _enemy(12, 3.0, profession="Warrior"),
        _enemy(20, 20.0, profession="Warrior"),
    )

    decision = _evaluate(enemies)

    assert decision.selected_target_agent_id == 10
    assert decision.selected is not None
    assert decision.selected.valuable_affected_count == 3
    assert decision.selected.expected_packet_damage == 270.0


def test_isolated_candidate_below_minimum_damage_is_rejected() -> None:
    decision = _evaluate((_enemy(10, 0.0, profession="Warrior"),), local_drain=5.0)

    assert decision.selected is None
    assert decision.reason is DecisionReason.NO_VIABLE_CANDIDATE
    assert decision.candidates[0].reason is CandidateReason.BELOW_MINIMUM_DAMAGE


def test_exact_ninety_damage_passes_and_lower_damage_fails() -> None:
    exact = _evaluate((_enemy(10, 0.0, profession="Warrior"),), local_drain=10.0)
    below = _evaluate((_enemy(10, 0.0, profession="Warrior"),), local_drain=9.0)

    assert exact.selected_target_agent_id == 10
    assert exact.selected is not None and exact.selected.expected_packet_damage == 90.0
    assert below.selected is None


def test_lower_inferred_energy_changes_candidate_value() -> None:
    elementalist = _evaluate((_enemy(10, 0.0, profession="Elementalist"),), local_drain=30.0)
    warrior = _evaluate((_enemy(10, 0.0, profession="Warrior"),), local_drain=30.0)

    assert elementalist.selected is not None
    assert elementalist.selected.projected_energy == 50.0
    assert elementalist.selected.effective_drain == 30.0
    assert elementalist.selected.expected_packet_damage == 270.0
    assert warrior.selected is not None and warrior.selected.projected_energy == 20.0
    assert warrior.selected.expected_packet_damage == 180.0


def test_one_foreign_reservation_reduces_value_using_explicit_projected_drain() -> None:
    enemy = _enemy(10, 0.0, profession="Elementalist")
    decision = _evaluate(
        (enemy,),
        local_drain=40.0,
        reservations=(ForeignReservationProjection(target_agent_id=10, projected_drain=20.0),),
    )

    assert decision.selected is not None
    assert decision.selected.foreign_reservation_count == 1
    assert decision.selected.foreign_projected_drain == 20.0
    assert decision.selected.projected_energy == 30.0
    assert decision.selected.effective_drain == 30.0
    assert decision.selected.expected_packet_damage == 270.0


def test_two_foreign_reservations_reach_the_normal_safety_cap() -> None:
    enemy = _enemy(10, 0.0, profession="Elementalist")
    decision = _evaluate(
        (enemy,),
        local_drain=40.0,
        reservations=(
            ForeignReservationProjection(target_agent_id=10, projected_drain=1.0),
            ForeignReservationProjection(target_agent_id=10, projected_drain=2.0),
        ),
    )

    assert decision.selected is None
    assert decision.candidates[0].foreign_reservation_count == 2
    assert decision.candidates[0].reason is CandidateReason.RESERVATION_CAP_REACHED


def test_foreign_projection_does_not_multiply_by_local_drain() -> None:
    enemy = _enemy(10, 0.0, profession="Elementalist")
    decision = _evaluate(
        (enemy,),
        local_drain=50.0,
        reservations=(ForeignReservationProjection(target_agent_id=10, projected_drain=5.0),),
    )

    assert decision.selected is not None
    assert decision.selected.projected_energy == 45.0
    assert decision.selected.effective_drain == 45.0


def test_invalid_local_resolved_drain_fails_closed() -> None:
    for invalid_drain in (None, 0.0, -1.0, float("nan"), float("inf")):
        decision = _evaluate((_enemy(10, 0.0),), local_drain=invalid_drain)
        assert decision.selected is None
        assert decision.reason is DecisionReason.INVALID_LOCAL_DRAIN


def test_low_hp_target_is_excluded_and_exact_ten_percent_is_low_hp() -> None:
    at_threshold = _evaluate((_enemy(10, 0.0, hp=0.10),))
    above_threshold = _evaluate((_enemy(10, 0.0, hp=0.100001),))

    assert at_threshold.selected is None
    assert at_threshold.candidates[0].reason is CandidateReason.LOW_HP_TARGET
    assert above_threshold.selected_target_agent_id == 10


def test_low_hp_collateral_does_not_inflate_valuable_packet_value() -> None:
    enemies = (
        _enemy(10, 0.0),
        _enemy(11, 1.0, hp=0.10),
        _enemy(12, 2.0),
    )

    decision = _evaluate(enemies)

    assert decision.selected is not None
    assert decision.selected.raw_affected_count == 3
    assert decision.selected.valuable_affected_count == 2
    assert decision.selected.expected_packet_damage == 180.0


def test_casting_status_only_breaks_a_lower_order_tie() -> None:
    enemies = (
        _enemy(20, 0.0, casting=False),
        _enemy(10, 10.0, casting=True),
    )

    decision = _evaluate(enemies)

    assert decision.selected_target_agent_id == 10


def test_caster_status_only_breaks_a_lower_order_tie() -> None:
    enemies = (
        _enemy(20, 0.0, caster=False),
        _enemy(10, 10.0, caster=True),
    )

    decision = _evaluate(enemies)

    assert decision.selected_target_agent_id == 10


def test_current_nine_damage_per_energy_formula_is_used() -> None:
    enemies = (_enemy(10, 0.0), _enemy(11, 2.0))

    decision = _evaluate(enemies, local_drain=7.0)

    assert decision.selected is not None
    assert decision.selected.expected_packet_damage == 126.0


def test_supplied_aoe_radius_changes_affected_membership() -> None:
    enemies = (_enemy(10, 0.0), _enemy(11, 3.0))
    narrow = _evaluate(enemies, aoe_radius=2.0)
    wide = _evaluate(enemies, aoe_radius=3.0)

    assert narrow.selected is not None and narrow.selected.raw_affected_count == 1
    assert wide.selected is not None and wide.selected.raw_affected_count == 2
    assert wide.selected.expected_packet_damage == 180.0


def test_cast_range_is_supplied_and_no_live_range_default_is_used() -> None:
    enemy = _enemy(10, 0.0, distance=5.0)
    out_of_range = _evaluate((enemy,), cast_range=4.0)
    in_range = _evaluate((enemy,), cast_range=5.0)

    assert out_of_range.selected is None
    assert out_of_range.candidates[0].reason is CandidateReason.OUT_OF_CAST_RANGE
    assert in_range.selected_target_agent_id == 10


def test_equal_final_ties_use_lower_agent_id_and_ignore_input_order() -> None:
    first = (_enemy(20, 0.0), _enemy(10, 10.0))
    reversed_input = tuple(reversed(first))

    first_decision = _evaluate(first)
    reversed_decision = _evaluate(reversed_input)

    assert first_decision.selected_target_agent_id == 10
    assert reversed_decision.selected_target_agent_id == 10


def test_policy_observations_must_use_the_same_smart_mesmer_geometry() -> None:
    snapshot_enemy = _enemy(10, 0.0)
    mismatched_enemy = _enemy(10, 1.0)

    try:
        policy.evaluate_energy_surge(
            _snapshot(snapshot_enemy),
            (mismatched_enemy,),
            aoe_radius=4.0,
            cast_range=50.0,
            group_link_radius=4.0,
            local_resolved_drain=10.0,
        )
    except ValueError as error:
        assert "geometry" in str(error)
    else:
        raise AssertionError("policy metadata must not silently replace snapshot geometry")


def test_profession_prior_mapping_includes_elementalist_and_unknown_fallback() -> None:
    expected = {
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

    for profession, maximum_energy in expected.items():
        assert policy.infer_max_energy(profession) == maximum_energy
    assert policy.infer_max_energy("Unknown Profession") == 25


def test_group_evaluation_exposes_deterministic_viability_and_value() -> None:
    enemies = (
        _enemy(10, 0.0, profession="Elementalist"),
        _enemy(11, 2.0, profession="Warrior"),
        _enemy(20, 20.0, profession="Warrior"),
    )
    decision = _evaluate(enemies, local_drain=5.0)

    assert tuple(group.group_identity for group in decision.groups) == ((10, 11), (20,))
    dense, isolated = decision.groups
    assert dense.viable is True
    assert dense.best_candidate is not None
    assert dense.best_candidate.target_agent_id == 10
    assert dense.policy_value == dense.best_candidate.expected_packet_damage == 90.0
    assert isolated.viable is False
    assert isolated.best_candidate is None
    assert isolated.policy_value == 0.0
