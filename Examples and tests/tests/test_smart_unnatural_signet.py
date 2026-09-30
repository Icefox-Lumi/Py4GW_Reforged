"""Deterministic offline policy and guarded-boundary tests for Unnatural Signet."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Skills" / "SmartUnnaturalSignet.py"


class _FakeBuildMgr:
    def __init__(self, **_: Any) -> None:
        self._cached_data: Any = None

    def set_cached_data(self, cached_data: Any) -> None:
        self._cached_data = cached_data


@contextmanager
def _loaded_module() -> Iterator[Any]:
    original = {
        name: module
        for name, module in sys.modules.items()
        if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d3b_test.")
    }
    try:
        for name in tuple(sys.modules):
            if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d3b_test."):
                sys.modules.pop(name, None)
        root_package = types.ModuleType("Py4GWCoreLib")
        root_package.__path__ = [str(ROOT / "Py4GWCoreLib")]
        sys.modules["Py4GWCoreLib"] = root_package
        build_mgr_module = types.ModuleType("Py4GWCoreLib.BuildMgr")
        setattr(build_mgr_module, "BuildMgr", _FakeBuildMgr)
        sys.modules["Py4GWCoreLib.BuildMgr"] = build_mgr_module

        spec = importlib.util.spec_from_file_location("d3b_test.smart_unnatural_signet", MODULE_PATH)
        assert spec is not None and spec.loader is not None, f"could not load {MODULE_PATH}"
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        for name in tuple(sys.modules):
            if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d3b_test."):
                sys.modules.pop(name, None)
        sys.modules.update(original)


with _loaded_module() as _smart:
    CandidateReason = _smart.CandidateReason
    DecisionReason = _smart.DecisionReason
    SmartUnnaturalSignet = _smart.SmartUnnaturalSignet
    UnnaturalSignetPolicy = _smart.UnnaturalSignetPolicy
    TargetObservation = _smart.UnnaturalSignetTargetObservation
    evaluate = _smart.evaluate_smart_unnatural_signet


def _target(
    agent_id: int,
    *,
    x: float = 0.0,
    y: float = 0.0,
    hp: float = 100.0,
    distance: float = 20.0,
    hexed: bool = False,
    enchanted: bool = False,
    valid: bool = True,
    alive: bool = True,
    hostile: bool = True,
    targetable: bool = True,
) -> Any:
    return TargetObservation(
        agent_id=agent_id,
        x=x,
        y=y,
        current_hp=hp,
        distance_from_player=distance,
        has_hex=hexed,
        has_enchantment=enchanted,
        is_valid=valid,
        is_alive=alive,
        is_hostile=hostile,
        is_targetable=targetable,
    )


def _decision(candidates: tuple[Any, ...], *, primary: float = 60.0, adjacent: float = 30.0) -> Any:
    return evaluate(
        candidates,
        policy=UnnaturalSignetPolicy(
            primary_damage=primary,
            adjacent_damage=adjacent,
            cast_range=100.0,
            adjacent_radius=10.0,
        ),
    )


def test_unqualified_target_still_gets_unconditional_primary_damage() -> None:
    decision = _decision((_target(10, hp=40),))

    assert decision.reason is DecisionReason.SELECTED
    assert decision.selected is not None
    assert decision.selected.useful_primary_damage == 40
    assert decision.selected.conditional_adjacent_damage == 0
    assert decision.selected.useful_delivered_damage == 40
    assert decision.selected.qualifies_secondary is False


def test_hex_or_enchantment_qualifies_secondary_damage_without_double_counting() -> None:
    hexed = _decision((_target(10, hexed=True), _target(11, x=5.0)))
    enchanted = _decision((_target(10, enchanted=True), _target(11, x=5.0)))
    both = _decision((_target(10, hexed=True, enchanted=True), _target(11, x=5.0)))

    assert hexed.selected is not None and hexed.selected.useful_delivered_damage == 90
    assert enchanted.selected is not None and enchanted.selected.useful_delivered_damage == 90
    assert both.selected is not None and both.selected.useful_delivered_damage == 90
    assert both.selected.secondary_hit_count == 1


def test_one_and_several_adjacent_foes_are_counted_only_when_qualified() -> None:
    decision = _decision(
        (
            _target(10, hexed=True),
            _target(11, x=5.0),
            _target(12, x=0.0, y=9.0, hp=20.0),
        )
    )

    assert decision.selected is not None
    assert decision.selected.secondary_agent_ids == (11, 12)
    assert decision.selected.conditional_adjacent_damage == 50
    assert decision.selected.useful_delivered_damage == 110


def test_primary_target_is_excluded_from_its_own_splash_set() -> None:
    decision = _decision((_target(10, hexed=True),))

    assert decision.selected is not None
    assert decision.selected.secondary_agent_ids == ()
    assert decision.selected.secondary_hit_count == 0


def test_non_adjacent_foe_is_excluded_and_exact_radius_is_inclusive() -> None:
    decision = _decision(
        (
            _target(10, hexed=True),
            _target(11, x=10.0),
            _target(12, x=10.001),
        )
    )

    assert decision.selected is not None
    assert decision.selected.secondary_agent_ids == (11,)


def test_invalid_dead_and_non_hostile_candidates_are_not_valued() -> None:
    decision = _decision(
        (
            _target(10, valid=False),
            _target(11, alive=False),
            _target(12, hostile=False),
            _target(13, targetable=False),
            _target(14, hp=25),
        )
    )

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 14
    assert all(not candidate.eligible for candidate in decision.candidates if candidate.target_agent_id != 14)


def test_current_hp_caps_primary_and_secondary_useful_damage() -> None:
    decision = _decision((_target(10, hp=5, hexed=True), _target(11, x=5.0, hp=7)))

    assert decision.selected is not None
    assert decision.selected.useful_primary_damage == 5
    assert decision.selected.conditional_adjacent_damage == 7
    assert decision.selected.useful_delivered_damage == 12


def test_low_hp_primary_does_not_beat_a_better_alternative() -> None:
    decision = _decision(
        (
            _target(10, hp=5, hexed=True),
            _target(11, x=5.0, hp=10.0),
            _target(20, x=50.0, hp=100.0),
        ),
        primary=80.0,
    )

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 20


def test_qualification_does_not_automatically_beat_a_higher_primary_target() -> None:
    decision = _decision(
        (
            _target(10, hp=10, hexed=True),
            _target(11, x=5.0, hp=20.0),
            _target(20, x=50.0, hp=100.0),
        )
    )

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 20


def test_ties_use_splash_hits_then_distance_then_agent_id() -> None:
    splash_tie = _decision(
        (
            _target(10, x=30.0, hexed=True),
            _target(11, x=35.0),
            _target(20, x=40.0, hexed=True),
        )
    )
    distance_tie = _decision(
        (
            _target(10, x=30.0, distance=30.0),
            _target(20, x=40.0, distance=20.0),
        )
    )
    agent_id_tie = _decision(
        (
            _target(20, x=30.0, distance=20.0),
            _target(10, x=40.0, distance=20.0),
        )
    )

    assert splash_tie.selected is not None
    assert splash_tie.selected.target_agent_id == 10
    assert distance_tie.selected is not None
    assert distance_tie.selected.target_agent_id == 20
    assert agent_id_tie.selected is not None
    assert agent_id_tie.selected.target_agent_id == 10


def test_missing_evidence_fails_safely_and_mistrust_is_not_a_policy_input() -> None:
    missing = TargetObservation(
        agent_id=10,
        x=None,
        y=None,
        current_hp=None,
        distance_from_player=None,
    )
    decision = _decision((missing,))

    assert decision.selected is None
    assert decision.reason is DecisionReason.NO_ELIGIBLE_CANDIDATE
    assert decision.candidates[0].reason is CandidateReason.MISSING_EVIDENCE
    assert "mistrust" not in TargetObservation.__dataclass_fields__


def test_invalid_damage_or_geometry_policy_fails_closed() -> None:
    decision = evaluate(
        (_target(10),),
        primary_damage=None,
        adjacent_damage=30.0,
        cast_range=100.0,
        adjacent_radius=10.0,
    )

    assert decision.selected is None
    assert decision.reason is DecisionReason.INVALID_POLICY


def test_handler_reads_combat_and_slot_permissions_from_existing_options() -> None:
    handler = object.__new__(SmartUnnaturalSignet)
    handler._cached_data = types.SimpleNamespace(
        account_options=types.SimpleNamespace(Combat=False, Skills=[True, False, True, True, True, True, True, True])
    )

    assert handler._combat_option_enabled() is False
    assert handler._skill_toggle_enabled(1) is True
    assert handler._skill_toggle_enabled(2) is False


def test_final_revalidation_uses_fresh_policy_result_instead_of_stale_splash() -> None:
    initial = _decision((_target(10, hexed=True), _target(11, x=5.0)))
    fresh = _decision((_target(10), _target(11, x=5.0)))
    assert initial.selected is not None and fresh.selected is not None

    handler = object.__new__(SmartUnnaturalSignet)
    parameters = _smart._RuntimeParameters(60.0, 30.0, 100.0, 10.0, 250)
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 1
    handler._skill_readiness = lambda _slot: True
    handler._resolve_runtime_parameters = lambda: parameters
    handler._evaluate_live = lambda _parameters: fresh

    validated = handler._final_revalidate(10, parameters)

    assert validated is not None
    assert validated[1].conditional_adjacent_damage == 0


def test_final_revalidation_rejects_a_changed_best_target() -> None:
    selected_elsewhere = _decision((_target(20, hp=100.0),))
    handler = object.__new__(SmartUnnaturalSignet)
    parameters = _smart._RuntimeParameters(60.0, 30.0, 100.0, 10.0, 250)
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 1
    handler._skill_readiness = lambda _slot: True
    handler._resolve_runtime_parameters = lambda: parameters
    handler._evaluate_live = lambda _parameters: selected_elsewhere

    assert handler._final_revalidate(10, parameters) is None
