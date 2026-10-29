# pyright: reportMissingImports=false
"""Deterministic offline regressions for Smart Shatter Hex policy and dispatch."""

from __future__ import annotations

import ast
import importlib.util
import sys
import threading
import types
from collections.abc import Callable
from dataclasses import replace
from enum import IntEnum
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import test_hex_removal_profile_cache
import test_hr_hex_observations
from test_hr_hex_observations import load_source
from test_hr_hex_observations import runtime_stub
from test_hr_hex_observations import variadic_stub

hr = test_hr_hex_observations.hr
hex_runtime = test_hex_removal_profile_cache.hex_runtime

_MISSING = object()


def _load_subject() -> types.ModuleType:
    module_name = "_smart_shatter_hex_test_subject"

    class _BuildMgr:
        pass

    corelib = types.ModuleType("Py4GWCoreLib")
    corelib.__path__ = []
    buildmgr = types.ModuleType("Py4GWCoreLib.BuildMgr")
    buildmgr.__dict__["BuildMgr"] = _BuildMgr
    builds = types.ModuleType("Py4GWCoreLib.Builds")
    builds.__path__ = []
    skills = types.ModuleType("Py4GWCoreLib.Builds.Skills")
    skills.__path__ = []
    enum_package = types.ModuleType("Py4GWCoreLib.enums_src")
    enum_package.__path__ = []

    class _Allegiance(IntEnum):
        Ally = 1
        Enemy = 3

    game_enums = types.ModuleType("Py4GWCoreLib.enums_src.GameData_enums")
    game_enums.__dict__["Allegiance"] = _Allegiance
    stub_modules = {
        "Py4GWCoreLib": corelib,
        "Py4GWCoreLib.BuildMgr": buildmgr,
        "Py4GWCoreLib.Builds": builds,
        "Py4GWCoreLib.Builds.Skills": skills,
        "Py4GWCoreLib.enums_src": enum_package,
        "Py4GWCoreLib.enums_src.GameData_enums": game_enums,
    }
    original_modules = {name: sys.modules.get(name, _MISSING) for name in stub_modules}
    observation_name = "Py4GWCoreLib.Builds.Skills.SmartShatterObservation"
    original_modules[observation_name] = sys.modules.get(observation_name, _MISSING)
    sys.modules.update(stub_modules)
    try:
        source_path = Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "Builds" / "Skills" / "SmartShatterHex.py"
        observation_spec = importlib.util.spec_from_file_location(
            observation_name, source_path.with_name("SmartShatterObservation.py")
        )
        assert observation_spec is not None and observation_spec.loader is not None
        observation = importlib.util.module_from_spec(observation_spec)
        sys.modules[observation_name] = observation
        observation_spec.loader.exec_module(observation)
        skills.__dict__["SmartShatterObservation"] = observation
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load {source_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        module.__dict__["_test_runtime_modules"] = {
            "Py4GWCoreLib": corelib,
            "Py4GWCoreLib.enums_src": enum_package,
            "Py4GWCoreLib.enums_src.GameData_enums": game_enums,
            "Py4GWCoreLib.GlobalCache.WhiteboardLocks": None,
        }
        return module
    finally:
        sys.modules.pop(module_name, None)
        for name, original in original_modules.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                assert isinstance(original, types.ModuleType)
                sys.modules[name] = original


SHATTER = _load_subject()


def arm_observation_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[int], object]:
    observation = SHATTER.ShatterObservation
    monkeypatch.setattr(observation, "_capture", None)
    clock = [10_000]
    context = observation.ContextSample(42, 1, 1, 0, 1000, 23, 7, (11, 22), 77)
    epoch = observation.arm_capture(
        "mesmer", "SH1", 2, context, ((11, 23), (22, 77)), lambda: clock[0], 10_000, 10_000, 13
    )
    assert epoch is not None, "isolated capture should arm without any runtime getter"
    return observation, clock, epoch


def _policy(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "caster_x": 0.0,
        "caster_y": 0.0,
        "cast_range": 1248.0,
        "splash_radius": 252.0,
        "nominal_damage": 120.0,
        "energy_fraction": 0.75,
        "current_energy": 20.0,
        "maximum_energy": 20.0,
        "effective_energy_cost": 10.0,
        "affordable": True,
    }
    values.update(overrides)
    return SHATTER.ShatterHexPolicy(**values)


def _ally(agent_id: int = 1, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "agent_id": agent_id,
        "x": 100.0,
        "y": 0.0,
        "health_fraction": 0.8,
        "is_valid": True,
        "is_living": True,
        "is_alive": True,
        "is_allied": True,
        "is_party_member": True,
        "is_hexed": True,
        "target_is_allowed": True,
        "confirmed_hex_count": 1,
        "retained_hex_count": 1,
        "hex_priority": 3,
    }
    values.update(overrides)
    return SHATTER.ShatterHexAllyObservation(**values)


def _enemy(agent_id: int = 100, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "agent_id": agent_id,
        "x": 100.0,
        "y": 0.0,
        "current_hp": 1000.0,
        "is_valid": True,
        "is_living": True,
        "is_alive": True,
        "is_hostile": True,
        "is_blacklisted": False,
    }
    values.update(overrides)
    return SHATTER.ShatterHexEnemyObservation(**values)


def _decision(*allies: Any, enemies: tuple[Any, ...] = (), policy: Any = None) -> Any:
    return SHATTER.evaluate_smart_shatter_hex(
        allies,
        enemies,
        policy=_policy() if policy is None else policy,
    )


# Fixture factories shared with the observation suite; no production import.
observation_ally = _ally
observation_decision = _decision


def test_high_hex_admits_when_affordable_without_splash() -> None:
    decision = _decision(_ally(), policy=_policy(nominal_damage=None, energy_fraction=0.01))

    assert decision.selected.target_agent_id == 1
    assert decision.selected.admission_lane == SHATTER.AdmissionLane.HIGH


def test_medium_energy_gate_is_inclusive_at_half() -> None:
    ally = _ally(hex_priority=2)

    assert _decision(ally, policy=_policy(energy_fraction=0.50)).admitted
    decision = _decision(ally, policy=_policy(energy_fraction=0.4999))
    assert decision.candidates[0].reason == SHATTER.CandidateReason.ENERGY_GATE


def test_low_energy_gate_and_useful_damage_floor_are_inclusive() -> None:
    ally = _ally(hex_priority=1)
    exact_damage = (_enemy(100, current_hp=90.0),)

    assert _decision(ally, enemies=exact_damage, policy=_policy(energy_fraction=0.70)).admitted
    assert not _decision(ally, enemies=exact_damage, policy=_policy(energy_fraction=0.6999)).admitted
    poor = _decision(ally, enemies=(_enemy(100, current_hp=89.99),))
    assert poor.candidates[0].reason == SHATTER.CandidateReason.INSUFFICIENT_SPLASH


def test_high_and_medium_lanes_do_not_require_splash() -> None:
    for priority in (SHATTER.AdmissionLane.HIGH, SHATTER.AdmissionLane.MEDIUM):
        threshold = 0.0 if priority is SHATTER.AdmissionLane.HIGH else 0.50
        decision = _decision(
            _ally(hex_priority=int(priority)),
            policy=_policy(energy_fraction=threshold, nominal_damage=None),
        )
        assert decision.admitted


def test_current_hex_state_overrules_stale_effect_identity() -> None:
    decision = _decision(_ally(is_hexed=False, confirmed_hex_count=1, retained_hex_count=1, hex_priority=3))

    assert decision.candidates[0].reason == SHATTER.CandidateReason.NOT_HEXED


def test_unclassified_hex_requires_opportunistic_lane() -> None:
    ally = _ally(confirmed_hex_count=0, retained_hex_count=0, hex_priority=None)
    assert _decision(ally, enemies=(_enemy(100, current_hp=90.0),), policy=_policy(energy_fraction=0.70)).admitted
    assert not _decision(ally, policy=_policy(energy_fraction=1.0)).admitted


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_valid": False},
        {"is_living": False},
        {"is_alive": False},
        {"is_party_member": False},
        {"is_allied": False},
        {"health_fraction": float("nan")},
        {"health_fraction": 0.0},
        {"target_is_allowed": False},
    ],
)
def test_invalid_ally_evidence_is_rejected(overrides: dict[str, Any]) -> None:
    decision = _decision(_ally(**overrides))

    assert decision.candidates[0].reason == SHATTER.CandidateReason.INVALID_TARGET


def test_spellcast_range_boundary_is_inclusive() -> None:
    ally = _ally(x=1248.0)
    outside = _ally(x=1248.0001)

    assert _decision(ally).admitted
    assert _decision(outside).candidates[0].reason == SHATTER.CandidateReason.OUT_OF_CAST_RANGE


def test_affordability_uses_effective_cost() -> None:
    ally = _ally(hex_priority=2)

    assert _decision(ally, policy=_policy(current_energy=9.99, effective_energy_cost=10.0)).candidates[0].reason == (
        SHATTER.CandidateReason.NOT_AFFORDABLE
    )
    assert _decision(ally, policy=_policy(current_energy=10.0, effective_energy_cost=10.0)).admitted
    assert _decision(ally, policy=_policy(affordable=False)).candidates[0].reason == (
        SHATTER.CandidateReason.NOT_AFFORDABLE
    )


@pytest.mark.parametrize("rank, damage", [(0, 30.0), (12, 102.0), (15, 120.0), (21, 156.0)])
def test_domination_damage_progression(rank: int, damage: float) -> None:
    assert SHATTER.resolve_shatter_hex_damage(rank) == damage


@pytest.mark.parametrize("rank", [None, -1, 22, True, 1.5])
def test_invalid_domination_rank_does_not_invent_damage(rank: Any) -> None:
    assert SHATTER.resolve_shatter_hex_damage(rank) is None


def test_splash_is_ally_centered_bounded_and_hp_capped() -> None:
    ally = _ally(x=1248.0, y=0.0)
    enemies = (
        _enemy(100, x=1250.0, y=0.0, current_hp=1000.0),  # Outside caster range, inside ally circle.
        _enemy(101, x=1490.0, y=0.0, current_hp=20.0),
        _enemy(102, x=1500.0001, y=0.0, current_hp=1000.0),
    )
    decision = _decision(ally, enemies=enemies, policy=_policy(nominal_damage=120.0))

    assert decision.selected.useful_splash_damage == 140.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_valid": False},
        {"is_living": False},
        {"is_alive": False},
        {"is_hostile": False},
        {"is_blacklisted": True},
        {"current_hp": 0.0},
        {"current_hp": float("nan")},
        {"x": float("inf")},
        {"y": float("nan")},
    ],
)
def test_invalid_enemy_evidence_cannot_inflate_splash(overrides: dict[str, Any]) -> None:
    decision = _decision(
        _ally(hex_priority=1),
        enemies=(_enemy(**overrides),),
        policy=_policy(nominal_damage=120.0),
    )

    assert decision.selected is None
    assert decision.candidates[0].useful_splash_damage == 0.0


def test_enemy_ids_are_deduplicated_and_group_expansion_is_not_used() -> None:
    ally = _ally(hex_priority=1)
    duplicate = _enemy(100, current_hp=30.0)
    beyond_circle = _enemy(101, x=352.0001, current_hp=120.0)

    decision = _decision(ally, enemies=(duplicate, duplicate, beyond_circle))

    assert decision.selected is None
    assert decision.candidates[0].useful_splash_damage == 30.0


def test_duplicate_ally_observations_are_counted_once_and_conflicts_fail_closed() -> None:
    ally = _ally(1)

    assert len(_decision(ally, ally).candidates) == 1
    conflicting = _decision(ally, replace(ally, x=101.0))
    assert conflicting.selected is None
    assert conflicting.candidates == ()


def test_enemy_summons_are_plain_damage_recipients() -> None:
    enemies = (_enemy(100, current_hp=45.0), _enemy(101, x=110.0, current_hp=45.0))
    decision = _decision(_ally(hex_priority=1), enemies=enemies)

    assert decision.admitted
    assert decision.selected.useful_splash_damage == 90.0


def test_deterministic_ranking_uses_priority_splash_health_distance_then_id() -> None:
    enemies = (_enemy(100, current_hp=200.0), _enemy(101, x=150.0, current_hp=120.0))
    candidates = (
        _ally(9, hex_priority=3, health_fraction=0.2, x=300.0),
        _ally(7, hex_priority=3, health_fraction=0.2, x=200.0),
        _ally(5, hex_priority=3, health_fraction=0.2, x=200.0),
        _ally(2, hex_priority=2, health_fraction=0.01, x=100.0),
    )
    first = _decision(*candidates, enemies=enemies)
    permuted = _decision(*reversed(candidates), enemies=tuple(reversed(enemies)))

    assert first.selected.target_agent_id == 5
    assert permuted.selected == first.selected


def test_splash_value_precedes_health_and_distance_in_ranking() -> None:
    candidates = (
        _ally(1, x=100.0, health_fraction=0.9),
        _ally(2, x=1200.0, health_fraction=0.1),
    )
    decision = _decision(*candidates, enemies=(_enemy(100, x=100.0, current_hp=120.0),))

    assert decision.selected.target_agent_id == 1


def test_none_only_observed_identity_never_becomes_unclassified() -> None:
    decision = _decision(_ally(confirmed_hex_count=1, retained_hex_count=1, hex_priority=0))

    assert decision.selected is None
    assert decision.candidates[0].reason == SHATTER.CandidateReason.NONE_PRIORITY


def test_lower_health_breaks_equal_priority_and_splash_tie() -> None:
    candidates = (_ally(1, health_fraction=0.6), _ally(2, health_fraction=0.3))

    assert _decision(*candidates).selected.target_agent_id == 2


def test_hex_identity_summary_handles_near_expiry_unknown_and_none() -> None:
    classify = lambda skill_id: {10: 3, 11: 1, 12: 0, 13: 2}[skill_id]

    high_at_2500 = SHATTER.summarize_hex_identity_evidence(
        (SHATTER.HexRemovalEffectObservation(10, 2500.0),),
        classify_priority=classify,
        minimum_remaining_ms=2500,
    )
    high_at_2501 = SHATTER.summarize_hex_identity_evidence(
        (SHATTER.HexRemovalEffectObservation(10, 2501.0),),
        classify_priority=classify,
        minimum_remaining_ms=2500,
    )
    none_only = SHATTER.summarize_hex_identity_evidence(
        (SHATTER.HexRemovalEffectObservation(12, None),),
        classify_priority=classify,
        minimum_remaining_ms=2500,
    )
    unknown_duration = SHATTER.summarize_hex_identity_evidence(
        (SHATTER.HexRemovalEffectObservation(11, None),),
        classify_priority=classify,
        minimum_remaining_ms=2500,
    )

    assert (high_at_2500.retained_hex_count, high_at_2500.priority) == (0, 0)
    assert (high_at_2501.retained_hex_count, high_at_2501.priority) == (1, 3)
    assert (none_only.confirmed_hex_count, none_only.retained_hex_count, none_only.priority) == (1, 1, 0)
    assert (unknown_duration.retained_hex_count, unknown_duration.priority) == (1, 1)


def test_all_known_short_lived_identities_are_not_downgraded_to_unknown() -> None:
    evidence = SHATTER.summarize_hex_identity_evidence(
        (
            SHATTER.HexRemovalEffectObservation(10, 0.0),
            SHATTER.HexRemovalEffectObservation(10, 1000.0),
        ),
        classify_priority=lambda _skill_id: 3,
        minimum_remaining_ms=2500,
    )

    assert evidence.confirmed_hex_count == 1
    assert evidence.retained_hex_count == 0


def test_claim_lease_uses_centralized_conservative_timing() -> None:
    duration = SHATTER.calculate_shatter_hex_claim_duration_ms(1000, 180, 83)

    assert duration == 2500 + 250 + 150
    assert SHATTER.calculate_shatter_hex_claim_duration_ms(-1, 250, 150) is None


def _load_hex_priority() -> tuple[types.ModuleType, types.ModuleType, types.ModuleType, types.ModuleType]:
    package_names = (
        "Py4GWCoreLib",
        "Py4GWCoreLib.enums_src",
        "Py4GWCoreLib.py4gwcorelib_src",
        "Py4GWCoreLib.GlobalCache",
    )
    modules = {name: types.ModuleType(name) for name in package_names}
    for module in modules.values():
        module.__path__ = []
    py_system = types.ModuleType("PySystem")
    py_system.__dict__["Console"] = SimpleNamespace(
        MessageType=SimpleNamespace(Info=1, Warning=2, Error=3),
        Log=lambda *args, **kwargs: None,
    )

    class _Profession(IntEnum):
        Warrior = 1
        Ranger = 2
        Monk = 3
        Necromancer = 4
        Mesmer = 5
        Elementalist = 6
        Assassin = 7
        Ritualist = 8
        Paragon = 9
        Dervish = 10

    game_enums = types.ModuleType("Py4GWCoreLib.enums_src.GameData_enums")
    game_enums.__dict__["Profession"] = _Profession
    frame_cache_module = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.FrameCache")
    frame_cache_module.__dict__["frame_cache"] = lambda **_kwargs: lambda function: function
    module_name = "Py4GWCoreLib.GlobalCache.HexRemovalPriority"
    original_names = (*package_names, game_enums.__name__, frame_cache_module.__name__, module_name, "PySystem")
    originals = {name: sys.modules.get(name, _MISSING) for name in original_names}
    sys.modules.update(modules)
    sys.modules[game_enums.__name__] = game_enums
    sys.modules[frame_cache_module.__name__] = frame_cache_module
    sys.modules["PySystem"] = py_system
    try:
        source_path = Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "GlobalCache" / "HexRemovalPriority.py"
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load {source_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module, modules["Py4GWCoreLib"], modules["Py4GWCoreLib.enums_src"], game_enums
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                assert isinstance(original, types.ModuleType)
                sys.modules[name] = original


def test_hex_priority_observations_confirm_hexes_and_keep_unknown_durations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    priority, corelib, enum_package, game_enums = _load_hex_priority()
    corelib.__dict__.update(
        GLOBAL_CACHE=SimpleNamespace(
            Effects=SimpleNamespace(
                GetBuffs=lambda _agent_id: [SimpleNamespace(skill_id=13, time_remaining=None)],
                GetEffects=lambda _agent_id: [SimpleNamespace(skill_id=12, time_remaining=2501.0)],
            ),
            Skill=SimpleNamespace(Flags=SimpleNamespace(IsHex=lambda skill_id: skill_id in {11, 12, 13})),
        ),
        Routines=SimpleNamespace(
            Checks=SimpleNamespace(
                Agents=SimpleNamespace(
                    GetBuffs=lambda _agent_id: [
                        SimpleNamespace(SkillId=11, Type=2, Remaining=2500.0),
                        SimpleNamespace(SkillId=99, Type=2, Remaining=10000.0),
                    ]
                )
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", corelib)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src", enum_package)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src.GameData_enums", game_enums)

    observations = priority.get_hex_removal_effect_observations(42)

    assert observations == ((11, 2500.0), (12, 2501.0), (13, None))


def test_existing_hex_priority_owner_applies_role_profession_and_default_rules() -> None:
    priority, _corelib, _enum_package, _game_enums = _load_hex_priority()
    entry = priority.HexRemovalEntry(
        caster=priority.HexRemovalPriority.LOW,
        ranged_martial=priority.HexRemovalPriority.MEDIUM,
        melee=priority.HexRemovalPriority.HIGH,
        by_profession={77: priority.HexRemovalPriority.HIGH},
    )
    priority.HEX_REMOVAL_PRIORITY[500] = entry

    assert priority.classify_hex_with_role(500, priority.TargetRole.MELEE, 1) == priority.HexRemovalPriority.HIGH
    assert priority.classify_hex_with_role(500, priority.TargetRole.CASTER, 77) == priority.HexRemovalPriority.HIGH
    assert priority.classify_hex_with_role(501, priority.TargetRole.MELEE, 1) == priority.DEFAULT_HEX_REMOVAL_PRIORITY


def test_enemy_current_hp_uses_health_fraction_times_maximum_hp(monkeypatch: pytest.MonkeyPatch) -> None:
    corelib = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    enum_package = SHATTER._test_runtime_modules["Py4GWCoreLib.enums_src"]
    enum_module = SHATTER._test_runtime_modules["Py4GWCoreLib.enums_src.GameData_enums"]
    corelib.__dict__["Agent"] = SimpleNamespace(
        IsValid=lambda _agent_id: True,
        IsLiving=lambda _agent_id: True,
        IsAlive=lambda _agent_id: True,
        IsDead=lambda _agent_id: False,
        GetAllegiance=lambda _agent_id: 3,
        GetXY=lambda _agent_id: (1800.0, 10.0),
        GetHealth=lambda _agent_id: 0.25,
        GetMaxHealth=lambda _agent_id: 400.0,
    )
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", corelib)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src", enum_package)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src.GameData_enums", enum_module)
    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._is_blacklisted_enemy = lambda _agent_id: False

    observation = handler._observe_enemy(77)

    assert observation.current_hp == 100.0
    assert observation.is_hostile is True


def test_common_cleanse_dispatch_acceptance_is_not_reported_as_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    priority, corelib, enum_package, game_enums = _load_hex_priority()
    logs: list[str] = []
    observations: list[int] = []
    priority.__dict__.update(
        _log_hex=logs.append,
        get_hex_skill_ids_on_agent=lambda agent_id: observations.append(agent_id) or [11],
    )
    corelib.__dict__.update(
        GLOBAL_CACHE=SimpleNamespace(Skill=SimpleNamespace(GetName=lambda skill_id: f"skill-{skill_id}"))
    )
    agent_module = types.ModuleType("Py4GWCoreLib.Agent")
    agent_module.__dict__["Agent"] = SimpleNamespace(GetNameByID=lambda _agent_id: "ally")
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", corelib)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src", enum_package)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src.GameData_enums", game_enums)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Agent", agent_module)

    class _Build:
        @staticmethod
        def CastSkillIDAndRestoreTarget(**_kwargs: Any):
            if False:
                yield None
            return True

    result = _generator_result(priority.cast_hex_removal_and_track(_Build(), 67, 42))

    assert result is True
    assert observations == [42]
    assert any("dispatch accepted" in message and "cleanse outcome unobserved" in message for message in logs)
    assert all("hex removed" not in message for message in logs)


def test_common_cleanse_selector_declines_when_atomic_reservation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    priority, corelib, enum_package, game_enums = _load_hex_priority()
    reservation_calls: list[tuple[int, int, int]] = []
    corelib.__dict__["Routines"] = SimpleNamespace(
        Checks=SimpleNamespace(
            Skills=SimpleNamespace(
                IsSkillIDReady=lambda _skill_id: True,
                HasEnoughEnergy=lambda _player_id, _skill_id: True,
            )
        )
    )
    global_cache_package = types.ModuleType("Py4GWCoreLib.GlobalCache")
    global_cache_package.__path__ = []
    locks = types.ModuleType("Py4GWCoreLib.GlobalCache.WhiteboardLocks")
    locks.__dict__.update(
        filter_unlocked_hex_targets=lambda targets: list(targets),
        post_hex_removal_lock=lambda target, *, skill_id, aftercast_delay: (
            reservation_calls.append((target, skill_id, aftercast_delay)) or -1
        ),
    )
    legacy_utils = types.ModuleType("Py4GWCoreLib.Py4GWcorelib")
    legacy_utils.__dict__["Utils"] = SimpleNamespace(GetFirstFromArray=lambda values: values[0] if values else 0)
    player_module = types.ModuleType("Py4GWCoreLib.Player")
    player_module.__dict__["Player"] = SimpleNamespace(GetAgentID=lambda: 23)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", corelib)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src", enum_package)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src.GameData_enums", game_enums)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.GlobalCache", global_cache_package)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.GlobalCache.WhiteboardLocks", locks)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Py4GWcorelib", legacy_utils)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Player", player_module)
    priority.__dict__["get_hexed_ally_array"] = lambda *_args, **_kwargs: [44]

    target = priority.get_hexed_ally_for_removal(reserve=True, skill_id=67)

    assert target == 0
    assert reservation_calls == [(44, 67, 250)]


def test_self_is_added_to_party_discovery_when_ally_array_omits_self(monkeypatch: pytest.MonkeyPatch) -> None:
    corelib = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    enum_module = SHATTER._test_runtime_modules["Py4GWCoreLib.enums_src.GameData_enums"]
    corelib.__dict__.update(
        Agent=SimpleNamespace(
            IsValid=lambda _agent_id: True,
            IsLiving=lambda _agent_id: True,
            IsAlive=lambda _agent_id: True,
            IsDead=lambda _agent_id: False,
            GetAllegiance=lambda _agent_id: 1,
            GetXY=lambda agent_id: (float(agent_id), 0.0),
            GetHealth=lambda _agent_id: 0.8,
            IsHexed=lambda _agent_id: False,
        ),
        AgentArray=SimpleNamespace(
            GetAllyArray=lambda: [10],
            GetEnemyArray=lambda: [],
            GetSpiritPetArray=lambda: [],
            GetMinionArray=lambda: [],
        ),
        Player=SimpleNamespace(GetAgentID=lambda: 99),
        Routines=SimpleNamespace(Party=SimpleNamespace(IsPartyMember=lambda agent_id: agent_id in {10, 99})),
    )
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", corelib)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src", SHATTER._test_runtime_modules["Py4GWCoreLib.enums_src"])
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.enums_src.GameData_enums", enum_module)

    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._skill_id = SHATTER.SHATTER_HEX_SKILL_ID
    handler._validate_target_for_skill_cast = lambda _skill_id, _target_id: True
    parameters = SHATTER._RuntimeParameters(_policy(), 3400, 1400)

    allies, enemies = handler._build_snapshot(parameters)

    assert {ally.agent_id for ally in allies} == {10, 99}
    assert enemies == ()


def _install_lock_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    acquire: Any = None,
    renew: Any = None,
    release: Any = None,
) -> types.ModuleType:
    corelib = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    global_cache = types.ModuleType("Py4GWCoreLib.GlobalCache")
    global_cache.__path__ = []
    lock_module = types.ModuleType("Py4GWCoreLib.GlobalCache.WhiteboardLocks")
    lock_module.__dict__.update(
        try_acquire_hex_removal_claim=acquire or (lambda *_args: None),
        renew_hex_removal_claim=renew or (lambda *_args: None),
        release_hex_removal_claim=release or (lambda *_args: False),
        hex_removal_claim_is_owned=lambda _token: True,
        get_hex_removal_owner_context=lambda: ("mesmer@example.test", 5),
    )
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", corelib)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.GlobalCache", global_cache)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.GlobalCache.WhiteboardLocks", lock_module)
    return lock_module


def _attempt(handler: Any, token: Any = "exact-token") -> Any:
    attempt = SHATTER._PendingShatterAttempt(
        attempt_generation=1,
        composition_generation=4,
        map_id=42,
        player_agent_id=23,
        instance_uptime_ms=5000,
        owner_email="mesmer@example.test",
        isolation_group_id=5,
        slot_index=4,
        target_agent_id=77,
        admission_lane=SHATTER.AdmissionLane.HIGH,
        claim_token=token,
    )
    handler._disposed = False
    handler._pending_attempt = attempt
    handler._attempt_generation = 1
    handler._composition_generation = 4
    return attempt


def _generator_result(generator: Any) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as result:
            return result.value


def test_claim_race_walks_ranked_candidates_before_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    acquired_targets: list[int] = []
    token = object()
    _install_lock_stub(
        monkeypatch,
        acquire=lambda target_id, _duration: acquired_targets.append(target_id) or (token if target_id == 2 else None),
    )
    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._disposed = False
    handler._composition_generation = 4
    handler._attempt_generation = 0
    handler._pending_attempt = None
    parameters = SHATTER._RuntimeParameters(_policy(), 3400, 1400)
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 4
    handler._skill_readiness = lambda _slot, *, at_execution: True
    handler._resolve_runtime_parameters = lambda: parameters

    def snapshot(_parameters: Any, *, observation: object | None = None) -> Any:
        return ((_ally(1), _ally(2)), ())

    handler._build_snapshot = snapshot
    handler._read_lifecycle_inputs = lambda: (42, 23, 5000, "mesmer@example.test", 5)
    handler._revalidate_selected = lambda _attempt, *, at_execution: parameters
    enqueued: list[int] = []
    handler._enqueue_guarded = lambda attempt: enqueued.append(attempt.target_agent_id) or True

    result = _generator_result(handler.try_cast())

    assert result is True
    assert acquired_targets == [1, 2]
    assert enqueued == [2]
    assert handler._pending_attempt is not None
    assert handler._pending_attempt.claim_token is token


def test_enqueue_rejection_releases_the_exact_pre_send_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    released: list[Any] = []
    _install_lock_stub(
        monkeypatch,
        acquire=lambda _target, _duration: token,
        release=lambda exact: released.append(exact) or True,
    )
    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._disposed = False
    handler._composition_generation = 4
    handler._attempt_generation = 0
    handler._pending_attempt = None
    parameters = SHATTER._RuntimeParameters(_policy(), 3400, 1400)
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 4
    handler._skill_readiness = lambda _slot, *, at_execution: True
    handler._resolve_runtime_parameters = lambda: parameters

    def snapshot(_parameters: Any, *, observation: object | None = None) -> Any:
        return ((_ally(77),), ())

    handler._build_snapshot = snapshot
    handler._read_lifecycle_inputs = lambda: (42, 23, 5000, "mesmer@example.test", 5)
    handler._revalidate_selected = lambda _attempt, *, at_execution: parameters
    queued: list[Any] = []
    handler._enqueue_guarded = lambda attempt: queued.append(attempt) or False

    assert _generator_result(handler.try_cast()) is False
    assert released == [token]
    assert handler._pending_attempt is None
    assert queued[0].state == "queued"


@pytest.mark.parametrize("renewal_succeeds", [True, False])
def test_final_execution_guard_renews_once_or_releases_without_native_send(
    monkeypatch: pytest.MonkeyPatch,
    renewal_succeeds: bool,
) -> None:
    token = object()
    renewed_token = object()
    renewals: list[tuple[Any, int]] = []
    released: list[Any] = []

    def renew(exact: Any, duration: int) -> Any:
        renewals.append((exact, duration))
        return renewed_token if renewal_succeeds else None

    _install_lock_stub(
        monkeypatch,
        renew=renew,
        release=lambda exact: released.append(exact) or True,
    )
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler, token)
    parameters = SHATTER._RuntimeParameters(_policy(), 3400, 1400)
    handler._revalidate_selected = lambda _attempt, *, at_execution: parameters
    pending_durations: list[int] = []
    handler._mark_local_cast_pending = lambda duration: pending_durations.append(duration)
    native_sends: list[tuple[int, int]] = []

    result = handler._execute_queued_guard(attempt, lambda slot, target: native_sends.append((slot, target)) or True)

    assert renewals == [(token, 3400)]
    if renewal_succeeds:
        assert result is True
        assert native_sends == [(4, 77)]
        assert attempt.claim_token is renewed_token
        assert attempt.state == "sent"
        assert pending_durations == [1400]
        assert released == []
    else:
        assert result is False
        assert native_sends == []
        assert released == [token]
        assert handler._pending_attempt is None


def test_native_send_exception_keeps_only_the_finite_renewed_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    renewed_token = object()
    released: list[Any] = []
    _install_lock_stub(
        monkeypatch,
        renew=lambda _exact, _duration: renewed_token,
        release=lambda exact: released.append(exact) or True,
    )
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler, token)
    handler._revalidate_selected = lambda _attempt, *, at_execution: SHATTER._RuntimeParameters(_policy(), 3400, 1400)
    handler._mark_local_cast_pending = lambda _duration: None

    def native_send(_slot: int, _target: int) -> bool:
        raise RuntimeError("native boundary failed")

    assert handler._execute_queued_guard(attempt, native_send) is False
    assert attempt.state == "sent"
    assert attempt.claim_token is renewed_token
    assert released == []


class _HostileBindingReturn:
    def __bool__(self) -> bool:
        raise AssertionError("diagnostics must not coerce a binding object")

    def __repr__(self) -> str:
        raise AssertionError("diagnostics must not represent a binding object")


@pytest.mark.parametrize("raw_return", [True, False, None, 0, 1.25, float("inf"), 2**100, _HostileBindingReturn()])
@pytest.mark.parametrize(
    "capture_state",
    ["inactive", "active", "failed", "exhausted", "stopped", "expired", "rearmed", "logger_failed", "both_failed"],
)
def test_observation_cannot_change_binding_return_or_lease(
    monkeypatch: pytest.MonkeyPatch,
    raw_return: Any,
    capture_state: str,
) -> None:
    observation, clock, epoch = arm_observation_fixture(monkeypatch)
    handler = object.__new__(SHATTER.SmartShatterHex)
    old_token, renewed = object(), object()
    attempt = _attempt(handler, old_token)
    attempt.observation_epoch = epoch
    attempt.observation_index = observation.acquired(epoch, 1, 4, 77, 3400)
    renewals: list[Any] = []
    releases: list[Any] = []
    sends: list[Any] = []
    pending: list[int] = []
    log_attempts: list[str] = []

    def log(sender: str, message: str, _level: int) -> None:
        assert sender == "SmartShatterHex"
        log_attempts.append(message)
        if capture_state in ("logger_failed", "both_failed"):
            raise RuntimeError("simulated legacy console failure")

    system = types.ModuleType("PySystem")
    system.__dict__["Console"] = SimpleNamespace(Log=log, MessageType=SimpleNamespace(Info=1))
    monkeypatch.setitem(sys.modules, "PySystem", system)

    def renew(token: object, duration: int) -> object:
        renewals.append((token, duration))
        return renewed

    def revalidate(_attempt: Any, *, at_execution: bool) -> Any:
        return SHATTER._RuntimeParameters(_policy(), 3400, 1400)

    _install_lock_stub(
        monkeypatch,
        renew=renew,
        release=releases.append,
    )
    handler._revalidate_selected = revalidate
    handler._mark_local_cast_pending = pending.append
    if capture_state == "inactive":
        observation._capture = None
    elif capture_state in ("failed", "both_failed"):

        def fail_copy(_value: object) -> Any:
            raise RuntimeError("private diagnostic copy failure")

        monkeypatch.setattr(observation, "_binding", fail_copy)
    elif capture_state == "exhausted":
        observation._capture.hooks = observation.MAX_HOOKS
    elif capture_state == "stopped":
        observation.stop_capture()
    elif capture_state == "expired":
        clock[0] += 30_000
    elif capture_state == "rearmed":
        observation.stop_capture()
        for _ in range(40):
            observation.drain_console_draw()
        previous = observation._capture
        new_epoch = observation.arm_capture(
            "mesmer", "SH2", 2, previous.context, ((11, 23), (22, 77)), lambda: clock[0], clock[0], clock[0], 13
        )
        assert new_epoch is not epoch

    def native(slot: int, target: int) -> Any:
        sends.append((slot, target))
        return raw_return

    assert handler._execute_queued_guard(attempt, native) is True
    assert (renewals, releases, sends, pending) == ([(old_token, 3400)], [], [(4, 77)], [1400])
    assert attempt.claim_token is renewed and attempt.state == "sent"
    assert handler._pending_attempt is attempt and handler._attempt_generation == 1
    assert len(log_attempts) == 1
    assert log_attempts[0].startswith("SMART_SHATTER_LIVE_V1 event=native_send_attempted ")
    assert "slot=4 target=77 callback=entered" in log_attempts[0]
    assert "claim_renewal=passed lease_ms=3400" in log_attempts[0]
    if capture_state in ("active", "logger_failed"):
        assert observation._capture is not None
        stages = observation._capture.attempts[0]["st"]
        assert stages[-1][1] == "binding_return"
        assert stages[-1][2] == observation._binding(raw_return)
    if capture_state == "rearmed":
        assert observation._capture is not None
        assert observation._capture.attempts == [], "late callback must not attach to the new capture"


@pytest.mark.parametrize("native_behavior", ["return", "exception", "base_exception"])
def test_hostile_metaclass_never_runs_at_binding_boundary(
    monkeypatch: pytest.MonkeyPatch, native_behavior: str
) -> None:
    observation, _clock, epoch = arm_observation_fixture(monkeypatch)
    touched: list[str] = []

    class DiagnosticEscape(BaseException):
        pass

    def forbidden(_value: object) -> Any:
        touched.append("hostile descriptor or conversion")
        raise DiagnosticEscape("diagnostics executed hostile code")

    # Build the deliberate type.__name__ override without evaluating it in pytest IDs.
    meta = type("HostileMeta", (type,), {"__name__": property(forbidden)})
    base = {"return": object, "exception": Exception, "base_exception": BaseException}[native_behavior]
    hostile_type = meta("HostileValue", (base,), {"__bool__": forbidden, "__repr__": forbidden, "__str__": forbidden})
    value = hostile_type()
    handler = object.__new__(SHATTER.SmartShatterHex)
    token, renewed = object(), object()
    attempt = _attempt(handler, token)
    attempt.observation_epoch = epoch
    attempt.observation_index = observation.acquired(epoch, 1, 4, 77, 3400)
    renewals: list[tuple[object, int]] = []
    released: list[object] = []
    pending: list[int] = []
    sends: list[tuple[int, int]] = []

    def renew(exact: object, duration: int) -> object:
        renewals.append((exact, duration))
        return renewed

    def revalidate(_attempt: Any, *, at_execution: bool) -> Any:
        return SHATTER._RuntimeParameters(_policy(), 3400, 1400)

    def native(slot: int, target: int) -> Any:
        sends.append((slot, target))
        if native_behavior != "return":
            assert isinstance(value, BaseException)
            raise value
        return value

    _install_lock_stub(monkeypatch, renew=renew, release=released.append)
    handler._revalidate_selected = revalidate
    handler._mark_local_cast_pending = pending.append
    result: object = None
    escaped: BaseException | None = None
    try:
        result = handler._execute_queued_guard(attempt, native)
    except BaseException as error:
        # The fixture must distinguish the original BaseException from a diagnostic replacement.
        escaped = error
    assert (renewals, released, sends, pending) == ([(token, 3400)], [], [(4, 77)], [1400])
    assert attempt.claim_token is renewed and attempt.state == "sent"
    assert handler._pending_attempt is attempt and handler._attempt_generation == 1
    assert touched == [], "no metaclass descriptor, repr, str, or truth conversion may run"
    if native_behavior == "base_exception":
        assert escaped is value, "preserve the exact original exception outside the production Exception handler"
    else:
        assert escaped is None, "post-binding diagnostics must not escape the guard"
        assert result is (native_behavior == "return")
        stage = observation._capture.attempts[0]["st"][-1]
        assert stage[1] == ("binding_return" if native_behavior == "return" else "binding_exception")
        assert stage[2] == (
            ("unexpected_type", "value_not_retained") if native_behavior == "return" else "unexpected_type"
        )


def test_binding_exception_and_diagnostic_exception_keep_renewed_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    observation, _clock, epoch = arm_observation_fixture(monkeypatch)
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler)
    attempt.observation_epoch = epoch
    attempt.observation_index = observation.acquired(epoch, 1, 4, 77, 3400)
    renewed = object()
    released: list[object] = []

    def renew(_token: object, _duration: int) -> object:
        return renewed

    def revalidate(_attempt: Any, *, at_execution: bool) -> Any:
        return SHATTER._RuntimeParameters(_policy(), 3400, 1400)

    def mark_pending(_duration: int) -> None:
        pass

    _install_lock_stub(monkeypatch, renew=renew, release=released.append)
    handler._revalidate_selected = revalidate
    handler._mark_local_cast_pending = mark_pending

    def native(_slot: int, _target: int) -> None:
        raise ValueError("private native exception message")

    def fail_name(_value: object) -> str:
        raise RuntimeError("diagnostic failure while describing original error")

    monkeypatch.setattr(observation, "_type_name", fail_name)
    assert handler._execute_queued_guard(attempt, native) is False
    assert attempt.claim_token is renewed and attempt.state == "sent" and released == []
    assert observation._capture.reason == "diagnostic_failure"


@pytest.mark.parametrize("raw_return", [True, False, None, 0, _HostileBindingReturn()])
def test_queue_return_identity_is_unchanged_with_active_observation(
    monkeypatch: pytest.MonkeyPatch, raw_return: Any
) -> None:
    observation, _clock, epoch = arm_observation_fixture(monkeypatch)
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler)
    attempt.observation_epoch = epoch
    attempt.observation_index = observation.acquired(epoch, 1, 4, 77, 3400)
    queued: list[Callable[..., Any]] = []

    def queue(callback: Callable[..., Any]) -> Any:
        queued.append(callback)
        return raw_return

    _install_lock_stub(monkeypatch)
    corelib = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    corelib.__dict__["GLOBAL_CACHE"] = SimpleNamespace(SkillBar=SimpleNamespace(QueueGuardedUseSkill=queue))
    assert handler._enqueue_guarded(attempt) is (raw_return is not False)
    assert len(queued) == 1 and attempt.state == "queued"
    assert observation._capture.attempts[0]["st"][-1][1:] == ["queue", observation._binding(raw_return)]


def test_sent_attempt_clear_is_not_reported_as_queued_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    observation, _clock, epoch = arm_observation_fixture(monkeypatch)
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler)
    attempt.observation_epoch = epoch
    attempt.observation_index = observation.acquired(epoch, 1, 4, 77, 3400)
    attempt.state = "sent"
    released: list[object] = []
    _install_lock_stub(monkeypatch, release=released.append)
    handler.cancel_pending("runtime_gate_closed")
    assert released == [] and handler._pending_attempt is None
    assert observation._capture.attempts[0]["terminal"] == "clear_sent"


@pytest.mark.parametrize("failure_point", ["none", "before_claim", "after_claim", "queue_result"])
def test_active_observation_failures_preserve_claim_walk_and_queue(
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    observation, _clock, epoch = arm_observation_fixture(monkeypatch)
    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._shatter_observation_epoch = epoch
    handler._disposed = False
    handler._pending_attempt = None
    handler._composition_generation = 4
    handler._attempt_generation = 0
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 4

    def ready(_slot: int, *, at_execution: bool) -> bool:
        return True

    handler._skill_readiness = ready
    parameters = SHATTER._RuntimeParameters(_policy(), 3400, 1400)
    handler._resolve_runtime_parameters = lambda: parameters

    def snapshot(_parameters: Any, **_kwargs: Any) -> Any:
        return ((_ally(77, health_fraction=0.2), _ally(23)), ())

    def revalidate(_attempt: Any, *, at_execution: bool) -> Any:
        return parameters

    handler._build_snapshot = snapshot
    handler._read_lifecycle_inputs = lambda: (42, 23, 5000, "private@example.test", 5)
    handler._revalidate_selected = revalidate
    claims: list[int] = []
    released: list[object] = []
    queued: list[Any] = []
    token = object()
    acquired_claim = False

    def acquire(target: int, _duration: int) -> object | None:
        nonlocal acquired_claim
        claims.append(target)
        acquired_claim = target == 23
        return token if acquired_claim else None

    def enqueue(callback: Callable[..., Any]) -> None:
        queued.append(callback)

    _install_lock_stub(
        monkeypatch,
        acquire=acquire,
        release=released.append,
    )
    corelib = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    corelib.__dict__["GLOBAL_CACHE"] = SimpleNamespace(SkillBar=SimpleNamespace(QueueGuardedUseSkill=enqueue))

    def fail(*_args: Any) -> Any:
        raise RuntimeError("diagnostic fault")

    if failure_point == "before_claim":
        monkeypatch.setattr(observation, "_candidate", fail)
    elif failure_point == "after_claim":
        original_target = observation._target

        def fail_after_claim(capture: Any, target: int) -> str:
            if acquired_claim:
                raise RuntimeError("diagnostic failure after successful acquisition")
            return original_target(capture, target)

        monkeypatch.setattr(observation, "_target", fail_after_claim)
    elif failure_point == "queue_result":
        monkeypatch.setattr(observation, "_binding", fail)
    assert _generator_result(handler.try_cast()) is True
    assert claims == [77, 23] and released == [] and len(queued) == 1
    assert handler._pending_attempt is not None
    assert handler._pending_attempt.claim_token is token
    if failure_point == "none":
        row = observation._capture.decisions[0]
        assert row["first"][0] == "P2" and row["hr_claim"] == "claim_unavailable" and row["chosen"] == "P1"
        assert row["first_claim"] == "claim_unavailable"
        assert row["claims_observed"] == 2 and row["claims_unavailable"] == 1


def test_final_execution_revalidation_failure_releases_and_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    released: list[Any] = []
    _install_lock_stub(monkeypatch, release=lambda exact: released.append(exact) or True)
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler, token)
    handler._revalidate_selected = lambda _attempt, *, at_execution: None
    native_sends: list[tuple[int, int]] = []

    assert handler._execute_queued_guard(attempt, lambda slot, target: native_sends.append((slot, target))) is False
    assert native_sends == []
    assert released == [token]


@pytest.mark.parametrize(
    "ally,enemies",
    [
        (_ally(is_hexed=False), (_enemy(),)),
        (_ally(x=1249.0), (_enemy(),)),
        (_ally(hex_priority=1), ()),
    ],
)
def test_final_revalidation_rejects_cleansed_out_of_range_or_low_splash_loss(
    ally: Any,
    enemies: tuple[Any, ...],
) -> None:
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler)
    handler._attempt_is_current = lambda _attempt: True
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 4
    handler._skill_readiness = lambda _slot, *, at_execution: True
    handler._resolve_runtime_parameters = lambda: SHATTER._RuntimeParameters(_policy(), 3400, 1400)

    def snapshot(_parameters: Any, *, selected_agent_id: int, observation: object | None = None) -> Any:
        return ((replace(ally, agent_id=selected_agent_id),), enemies)

    handler._build_snapshot = snapshot

    assert handler._revalidate_selected(attempt, at_execution=True) is None


def test_final_high_priority_cleanse_can_continue_after_splash_disappears() -> None:
    handler = object.__new__(SHATTER.SmartShatterHex)
    attempt = _attempt(handler)
    handler._attempt_is_current = lambda _attempt: True
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 4
    handler._skill_readiness = lambda _slot, *, at_execution: True
    parameters = SHATTER._RuntimeParameters(_policy(nominal_damage=None), 3400, 1400)
    handler._resolve_runtime_parameters = lambda: parameters

    def snapshot(_parameters: Any, *, selected_agent_id: int, observation: object | None = None) -> Any:
        return ((_ally(selected_agent_id),), ())

    handler._build_snapshot = snapshot

    assert handler._revalidate_selected(attempt, at_execution=True) is parameters


def test_cancelling_queued_attempt_releases_only_its_exact_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    released: list[Any] = []
    _install_lock_stub(monkeypatch, release=lambda exact: released.append(exact) or True)
    handler = object.__new__(SHATTER.SmartShatterHex)
    _attempt(handler, token)

    handler.cancel_pending("bar_removed")

    assert handler._pending_attempt is None
    assert handler._attempt_generation == 2
    assert released == [token]


@pytest.mark.parametrize(
    "current_inputs",
    [
        (43, 23, 5001, "mesmer@example.test", 5),
        (42, 23, 4999, "mesmer@example.test", 5),
        (42, 23, 5001, "other@example.test", 5),
        (42, 23, 5001, "mesmer@example.test", 6),
    ],
)
def test_lifecycle_change_invalidates_queued_attempt_and_releases_claim(
    monkeypatch: pytest.MonkeyPatch,
    current_inputs: tuple[int, int, int, str, int],
) -> None:
    token = object()
    released: list[Any] = []
    _install_lock_stub(monkeypatch, release=lambda exact: released.append(exact) or True)
    handler = object.__new__(SHATTER.SmartShatterHex)
    _attempt(handler, token)
    handler._last_lifecycle_inputs = (42, 23, 5000, "mesmer@example.test", 5)
    handler._read_lifecycle_inputs = lambda: current_inputs

    handler.update_lifecycle(4)

    assert handler._pending_attempt is None
    assert released == [token]


def test_slot_movement_cancels_queued_attempt_and_sent_dispatch_expires_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = object()
    released: list[Any] = []
    _install_lock_stub(monkeypatch, release=lambda exact: released.append(exact) or True)
    handler = object.__new__(SHATTER.SmartShatterHex)
    _attempt(handler, token)
    handler._skill_slot = 4

    handler.set_skill_slot(5)
    assert handler._pending_attempt is None
    assert released == [token]

    attempt = _attempt(handler, token)
    attempt.state = "sent"
    handler._is_local_cast_pending = lambda: True
    assert handler.has_active_dispatch()
    handler._is_local_cast_pending = lambda: False
    assert not handler.has_active_dispatch()
    assert handler._pending_attempt is None
    assert released == [token]


def test_skillbar_execution_guard_stays_inside_action_queue_and_plain_use_is_unchanged() -> None:
    module_name = "_skillbar_cache_guard_test_subject"
    native_calls: list[tuple[int, int]] = []

    class _Skillbar:
        def UseSkill(self, slot: int, target: int) -> bool:
            native_calls.append((slot, target))
            return True

    class _ActionQueueManager:
        pass

    queue_module = types.ModuleType("Py4GWCoreLib.Py4GWcorelib")
    queue_module.__dict__["ActionQueueManager"] = _ActionQueueManager
    py_skillbar = types.ModuleType("PySkillbar")
    py_skillbar.__dict__["Skillbar"] = _Skillbar
    corelib = types.ModuleType("Py4GWCoreLib")
    corelib.__path__ = []
    modules = {
        "Py4GWCoreLib": corelib,
        "Py4GWCoreLib.Py4GWcorelib": queue_module,
        "PySkillbar": py_skillbar,
    }
    originals = {name: sys.modules.get(name, _MISSING) for name in modules}
    sys.modules.update(modules)
    try:
        source_path = Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "GlobalCache" / "SkillbarCache.py"
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class _Queue:
            def __init__(self) -> None:
                self.actions: list[tuple[str, Any, tuple[Any, ...]]] = []

            def AddAction(self, queue: str, callback: Any, *args: Any) -> None:
                self.actions.append((queue, callback, args))

            def AddActionWithDelay(self, queue: str, delay: int, callback: Any, *args: Any) -> None:
                self.actions.append((queue, callback, (delay, *args)))

        queue = _Queue()
        skillbar = module.SkillbarCache(queue)
        guarded: list[str] = []
        skillbar.QueueGuardedUseSkill(lambda native: (guarded.append("checked"), native(4, 88)))

        assert guarded == []
        assert len(queue.actions) == 1 and queue.actions[0][0] == "ACTION"
        queued_action, queued_callback, queued_args = queue.actions.pop()
        queued_callback(*queued_args)
        assert queued_action == "ACTION"
        assert guarded == ["checked"]
        assert native_calls == [(4, 88)]

        skillbar.UseSkill(6, 99, aftercast_delay=200)
        assert queue.actions[0][0] == "ACTION"
        assert queue.actions[0][2] == (200, 6, 99)
        _, plain_callback, plain_args = queue.actions.pop()
        plain_callback(*plain_args[1:])
        assert native_calls == [(4, 88), (6, 99)]
    finally:
        sys.modules.pop(module_name, None)
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                assert isinstance(original, types.ModuleType)
                sys.modules[name] = original


@pytest.mark.parametrize("observation_state", ["inactive", "active", "stopped"])
def test_reset_action_queue_then_claim_expiry_recovers_and_invalidates_stale_callback(
    monkeypatch: pytest.MonkeyPatch,
    observation_state: str,
) -> None:
    harness_path = Path(__file__).with_name("test_hex_removal_atomic_claim.py")
    harness_spec = importlib.util.spec_from_file_location("_smart_shatter_claim_harness", harness_path)
    assert harness_spec is not None and harness_spec.loader is not None
    harness = importlib.util.module_from_spec(harness_spec)
    harness_spec.loader.exec_module(harness)
    accounts_module = getattr(harness, "ALL_ACCOUNTS_MODULE")
    table = getattr(harness, "_new_table")(("mesmer@example.test", 5))
    current_tick = [50000]
    monkeypatch.setattr(accounts_module, "get_uncached_tick_count64", lambda: current_tick[0])

    corelib = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", corelib)
    corelib_package = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src")
    corelib_package.__path__ = []
    monkeypatch.setitem(sys.modules, corelib_package.__name__, corelib_package)

    def load_production_module(module_name: str, source_path: Path) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, module_name, module)
        spec.loader.exec_module(module)
        return module

    repo_root = Path(__file__).resolve().parents[1]
    production_root = repo_root / "Py4GWCoreLib"
    load_production_module(
        "Py4GWCoreLib.py4gwcorelib_src.Timer",
        production_root / "py4gwcorelib_src" / "Timer.py",
    )
    queue_module = load_production_module(
        "Py4GWCoreLib.py4gwcorelib_src.ActionQueue",
        production_root / "py4gwcorelib_src" / "ActionQueue.py",
    )
    queue_alias = types.ModuleType("Py4GWCoreLib.Py4GWcorelib")
    queue_alias.__dict__["ActionQueueManager"] = queue_module.ActionQueueManager
    monkeypatch.setitem(sys.modules, queue_alias.__name__, queue_alias)

    native_calls: list[tuple[int, int]] = []

    class _NativeSkillbar:
        def UseSkill(self, slot: int, target: int) -> bool:
            native_calls.append((slot, target))
            return True

    py_skillbar = types.ModuleType("PySkillbar")
    py_skillbar.__dict__["Skillbar"] = _NativeSkillbar
    monkeypatch.setitem(sys.modules, "PySkillbar", py_skillbar)
    global_cache_package = types.ModuleType("Py4GWCoreLib.GlobalCache")
    global_cache_package.__path__ = []
    monkeypatch.setitem(sys.modules, global_cache_package.__name__, global_cache_package)
    skillbar_module = load_production_module(
        "Py4GWCoreLib.GlobalCache.SkillbarCache",
        production_root / "GlobalCache" / "SkillbarCache.py",
    )
    manager = queue_module.ActionQueueManager()
    skillbar = skillbar_module.SkillbarCache(manager)
    global_cache = SimpleNamespace(
        SkillBar=skillbar,
        ShMem=SimpleNamespace(GetAllAccounts=lambda: table),
    )
    monkeypatch.setitem(corelib.__dict__, "GLOBAL_CACHE", global_cache)

    acquired: list[Any] = []
    renewals: list[Any] = []
    releases: list[tuple[Any, bool]] = []

    def acquire(target_agent_id: int, lease_duration_ms: int) -> Any:
        token = table.TryAcquireHexRemovalTarget(
            "mesmer@example.test",
            target_agent_id,
            lease_duration_ms,
            5,
        ).token
        acquired.append(token)
        return token

    def renew(token: Any, lease_duration_ms: int) -> Any:
        result = table.RenewHexRemovalClaim(token, lease_duration_ms)
        renewals.append(token)
        return result.token

    def release(token: Any) -> bool:
        result = table.ReleaseHexRemovalClaim(token)
        releases.append((token, result))
        return result

    lock_module = types.ModuleType("Py4GWCoreLib.GlobalCache.WhiteboardLocks")
    lock_module.__dict__.update(
        try_acquire_hex_removal_claim=acquire,
        hex_removal_claim_is_owned=table.IsHexRemovalClaimOwned,
        renew_hex_removal_claim=renew,
        release_hex_removal_claim=release,
    )
    monkeypatch.setitem(sys.modules, lock_module.__name__, lock_module)

    lifecycle = (42, 23, 5000, "mesmer@example.test", 5)
    parameters = SHATTER._RuntimeParameters(_policy(), 3400, 1400)
    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._disposed = False
    handler._composition_generation = 8
    handler._attempt_generation = 0
    handler._pending_attempt = None
    handler._runtime_gate = lambda: True
    handler._resolve_current_slot = lambda: 4
    handler._skill_readiness = lambda _slot, *, at_execution: True
    handler._resolve_runtime_parameters = lambda: parameters

    def snapshot(_parameters: Any, *, selected_agent_id: int | None = None, observation: object | None = None) -> Any:
        return ((_ally(77 if selected_agent_id is None else selected_agent_id),), ())

    handler._build_snapshot = snapshot
    handler._read_lifecycle_inputs = lambda: lifecycle
    guard_results: list[bool] = []
    execute_guard = handler._execute_queued_guard

    def observe_guard(attempt: Any, native_use: Any) -> bool:
        result = execute_guard(attempt, native_use)
        guard_results.append(result)
        return result

    handler._execute_queued_guard = observe_guard

    observation, observation_clock, observation_epoch = arm_observation_fixture(monkeypatch)
    if observation_state == "inactive":
        observation.stop_capture()
    else:
        handler._shatter_observation_epoch = observation_epoch

    assert _generator_result(handler.try_cast()) is True
    if observation_state == "stopped":
        observation.stop_capture()
    attempt = handler._pending_attempt
    assert attempt is not None
    original_token = attempt.claim_token
    assert table.IsHexRemovalClaimOwned(original_token)
    assert handler.has_active_dispatch()
    assert len(acquired) == 1 and acquired[0] is original_token

    action_queue = manager.GetQueue("ACTION")
    assert not action_queue.is_empty()
    queued_action, queued_args, queued_kwargs = action_queue.action_queue.queue[0]
    assert queued_action.__name__ == "_execute_guarded_use_skill"
    manager.ResetAllQueues()
    assert manager.IsEmpty("ACTION")
    assert handler.has_active_dispatch()

    current_tick[0] = original_token.expires_at_tick64 + 1
    if observation_state == "active":
        for _ in range(6):
            observation_clock[0] += 500
            request = observation.draw_request()
            assert request is not None
            epoch, _mode, context = request
            assert observation.accept_draw_sample(
                epoch,
                replace(context, uptime_ms=context.uptime_ms + 500),
                observation_clock[0],
                11,
            )
        observation_clock[0] += 401
    composition_generation = handler._composition_generation
    assert not handler.has_active_dispatch()
    assert handler._pending_attempt is None
    assert handler._attempt_generation > attempt.attempt_generation
    assert handler._composition_generation == composition_generation
    assert handler._resolve_current_slot() == 4
    assert lifecycle == (42, 23, 5000, "mesmer@example.test", 5)

    for index, intent in enumerate(table.Intents[1:], start=1):
        intent.Active = True
        intent.OwnerEmail = "other@example.test"
        intent.KindID = 1
        intent.SkillID = index
        intent.TargetAgentID = 100 + index
        intent.IsolationGroupID = 5
        intent.LockMode = 1
        intent.MaxHolders = 1
        intent.ReentryPolicy = 1
        intent.ClaimStrength = 1
        intent.PostedAtTick = current_tick[0]
        intent.ExpiresAtTick = current_tick[0] + 100000

    replacement_token = acquire(77, 3400)
    assert replacement_token is not None
    assert replacement_token.intent_slot_index == original_token.intent_slot_index
    assert replacement_token.local_generation != original_token.local_generation
    assert table.IsHexRemovalClaimOwned(replacement_token)
    acquisition_count = len(acquired)

    queued_action(*queued_args, **queued_kwargs)

    assert guard_results == [False]
    assert native_calls == []
    assert len(acquired) == acquisition_count
    assert renewals == []
    assert releases == [(original_token, False), (original_token, False)]
    assert table.IsHexRemovalClaimOwned(replacement_token)
    assert not handler.has_active_dispatch()
    if observation_state == "active":
        assert observation._capture.active, "the real stale-token rejection also runs with an active recorder"


def test_personal_composition_keeps_shatter_owned_and_idle_order_unchanged() -> None:
    source_path = (
        Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "Builds" / "Mesmer" / "Me_Any" / "My Energy Surge.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MyMesmer")
    factory_method = next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_handler_factories"
    )
    assert any(
        isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Name)
        and node.value.id == "SmartShatterHex"
        and any(
            isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == "factories"
            for target in node.targets
        )
        for node in ast.walk(factory_method)
    )

    casting_method = next(
        node for node in class_node.body if isinstance(node, ast.FunctionDef) and node.name == "ProcessSkillCasting"
    )
    casting_source = ast.get_source_segment(source, casting_method)
    assert casting_source is not None
    assert casting_source.index("shatter_handler =") < casting_source.index("can_process =")
    assert casting_source.index("energy_surge_entry =") < casting_source.index(
        "for skill_id, handler in ready_handlers:"
    )
    assert casting_source.index("for skill_id, handler in ready_handlers:") < casting_source.index(
        "fallback = self.ResolveFallback()"
    )
    assert "self.SetBlockedSkills(list(owned_ids))" in source
    assert source.index("shatter_handler =") < source.index(
        "if shatter_handler is not None and self._handler_has_active_dispatch"
    )


def test_common_cleanse_log_does_not_claim_removal_from_dispatch_acceptance() -> None:
    source_path = Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "GlobalCache" / "HexRemovalPriority.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    cast_method = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "cast_hex_removal_and_track"
    )
    names = [node.id for node in ast.walk(cast_method) if isinstance(node, ast.Name)]
    assert names.count("get_hex_skill_ids_on_agent") == 1
    cast_source = ast.get_source_segment(source, cast_method)
    assert cast_source is not None
    assert "dispatch accepted" in cast_source
    assert "cleanse outcome unobserved" in cast_source


def test_live_logger_bounds_throttles_and_skips_suppressed_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = object.__new__(SHATTER.SmartShatterHex)
    clock = [10.0]
    messages: list[str] = []
    formats: list[int] = []

    def log(_sender: str, message: str, _level: int) -> None:
        messages.append(message)

    system = types.ModuleType("PySystem")
    system.__dict__["Console"] = SimpleNamespace(Log=log, MessageType=SimpleNamespace(Info=1))
    monkeypatch.setitem(sys.modules, "PySystem", system)
    monkeypatch.setattr(SHATTER.time, "monotonic", lambda: clock[0])

    def details() -> str:
        formats.append(1)
        return "x" * 2000

    handler._live_log("decision", details, throttle_key="decision", throttle_interval_ms=10_000)
    handler._live_log("decision", details, throttle_key="decision", throttle_interval_ms=10_000)
    assert len(messages) == len(formats) == 1, "throttled records must not format their payload"
    clock[0] += 10.0
    handler._live_log("decision", details, throttle_key="decision", throttle_interval_ms=10_000)
    for index in range(100):
        handler._live_log("claim_attempt", details, throttle_key=f"target:{index}")
    assert len(messages) == len(formats) == len(handler._live_log_timestamps) == 60
    assert len(handler._live_log_throttle_times) == 16
    assert all(len(message) == 1600 and message.startswith("SMART_SHATTER_LIVE_V1 ") for message in messages)
    clock[0] += 60.0
    handler._live_log("claim_attempt", details)
    assert len(messages) == len(formats) == 61 and len(handler._live_log_timestamps) == 1

    events: list[tuple[str, str, str | None, int]] = []
    for index in range(100):
        handler._defer_live_event(events, "candidate_fallback", f"id=d{index}")
    handler._emit_deferred_live_events(events)
    assert len(events) == 32 and len(messages) == 93
    assert messages[-1] == "SMART_SHATTER_LIVE_V1 event=candidate_fallback id=d31"


def test_live_details_use_one_effect_read_and_bounded_existing_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._live_capture_hex_details = True
    reads: list[int] = []
    classifications: list[tuple[int, int]] = []
    priority = types.ModuleType("Py4GWCoreLib.GlobalCache.HexRemovalPriority")

    def read_effects(target: int) -> tuple[tuple[int, int], ...]:
        reads.append(target)
        return tuple((skill_id, 5000) for skill_id in range(1, 7)) + ((7, 1000),)

    def classify(skill_id: int, target: int) -> int:
        classifications.append((skill_id, target))
        return 3

    priority.__dict__.update(
        MIN_HEX_REMAINING_MS_TO_REMOVE=2500,
        get_hex_removal_effect_observations=read_effects,
        classify_hex_for_removal=classify,
    )
    monkeypatch.setitem(sys.modules, priority.__name__, priority)
    for target in range(1, 21):
        evidence = handler._hex_identity_evidence(target)
        assert (evidence.confirmed_hex_count, evidence.retained_hex_count, evidence.priority) == (7, 6, 3)
    assert reads == list(range(1, 21))
    assert classifications == [(skill, target) for target in range(1, 21) for skill in range(1, 7)]
    assert len(handler._live_hex_details) == 16
    assert all(detail == ((1, 2, 3, 4), 1) for detail in handler._live_hex_details.values())


def test_live_decision_reports_only_three_candidates_without_changing_ranking() -> None:
    handler = object.__new__(SHATTER.SmartShatterHex)
    allies = tuple(_ally(agent_id) for agent_id in range(1, 6))
    policy = _policy()
    decision = _decision(*allies, policy=policy)
    before = tuple(candidate.target_agent_id for candidate in decision.ranked_candidates)
    message = handler._format_live_decision(
        7, 4, SHATTER._RuntimeParameters(policy, 3400, 1400, 23), allies, (), decision
    )
    assert message.startswith("id=d7 local=23 slot=4 ")
    assert "considered=5 eligible=5 selected=1 top_cap=3" in message
    assert message.count("{ally=") == 3 and "ally=4," not in message and "ally=5," not in message
    assert tuple(candidate.target_agent_id for candidate in decision.ranked_candidates) == before == (1, 2, 3, 4, 5)


@pytest.fixture
def urgent_runtime(monkeypatch: pytest.MonkeyPatch, hr: Any) -> Any:
    harness = load_source(
        "_hr_claim_fixture", Path(__file__).with_name("test_hex_removal_atomic_claim.py"), monkeypatch
    )
    accounts = harness._new_table(("mesmer@example.test", 5), ("second@example.test", 5))
    monkeypatch.setattr(harness.ALL_ACCOUNTS_MODULE, "get_uncached_tick_count64", runtime_stub(lambda: hr.clock[0]))
    state = SimpleNamespace(
        hr=hr,
        accounts=accounts,
        email="mesmer@example.test",
        priority=3,
        ready=True,
        valid=True,
        hexed=True,
        x=100.0,
        native=[],
        native_result=True,
        parameters=SHATTER._RuntimeParameters(_policy(), 3400, 1400, 23),
        queries=[],
    )
    lock = _install_lock_stub(
        monkeypatch,
        acquire=runtime_stub(
            lambda target, duration: accounts.TryAcquireHexRemovalTarget(state.email, target, duration, 5).token
        ),
        renew=runtime_stub(lambda token, duration: accounts.RenewHexRemovalClaim(token, duration).token),
        release=accounts.ReleaseHexRemovalClaim,
    )
    lock.__dict__["hex_removal_claim_is_owned"] = accounts.IsHexRemovalClaimOwned
    core = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    monkeypatch.setitem(
        sys.modules,
        "Py4GWCoreLib.enums_src.GameData_enums",
        SHATTER._test_runtime_modules["Py4GWCoreLib.enums_src.GameData_enums"],
    )
    priority = types.ModuleType("Py4GWCoreLib.GlobalCache.HexRemovalPriority")
    priority.__dict__.update(
        HexRemovalPriority=SimpleNamespace(HIGH=3),
        MIN_HEX_REMAINING_MS_TO_REMOVE=2500,
        TargetRole=SimpleNamespace(RANGED_MARTIAL=2),
        classify_hex_with_role=runtime_stub(
            lambda skill, role, profession: state.queries.append((skill, role, profession)) or state.priority
        ),
    )
    monkeypatch.setitem(sys.modules, priority.__name__, priority)
    root = Path(__file__).resolve().parents[1] / "Py4GWCoreLib"
    package = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    load_source(package.__name__ + ".Timer", root / "py4gwcorelib_src/Timer.py", monkeypatch)
    queue_module = load_source(package.__name__ + ".ActionQueue", root / "py4gwcorelib_src/ActionQueue.py", monkeypatch)
    alias = types.ModuleType("Py4GWCoreLib.Py4GWcorelib")
    alias.__dict__["ActionQueueManager"] = queue_module.ActionQueueManager
    monkeypatch.setitem(sys.modules, alias.__name__, alias)

    class NativeSkillbar:
        def UseSkill(self, slot: int, target: int) -> bool:
            state.native.append((slot, target))
            if isinstance(state.native_result, Exception):
                raise state.native_result
            return state.native_result

    native = types.ModuleType("PySkillbar")
    native.__dict__["Skillbar"] = NativeSkillbar
    monkeypatch.setitem(sys.modules, "PySkillbar", native)
    skillbar = load_source("_hr_skillbar", root / "GlobalCache/SkillbarCache.py", monkeypatch)
    manager = queue_module.ActionQueueManager()
    state.queue = manager.queues["ACTION"].action_queue
    core.__dict__.update(
        GLOBAL_CACHE=SimpleNamespace(
            SkillBar=skillbar.SkillbarCache(manager),
            ShMem=SimpleNamespace(
                ReadHrHexObservation=variadic_stub(lambda *_: hr.table.read(hr.owner, hr.context.instance))
            ),
        ),
        Agent=SimpleNamespace(
            IsValid=runtime_stub(lambda _: state.valid),
            IsLiving=runtime_stub(lambda _: True),
            IsAlive=runtime_stub(lambda _: True),
            IsDead=runtime_stub(lambda _: False),
            GetAllegiance=runtime_stub(lambda _: 1),
            GetXY=runtime_stub(lambda _: (state.x, 0)),
            GetHealth=runtime_stub(lambda _: 0.8),
            IsHexed=runtime_stub(lambda _: state.hexed),
            GetLoginNumber=runtime_stub(lambda _: hr.owner.login),
            GetNameByID=runtime_stub(lambda _: hr.owner.character),
        ),
        Profession=SimpleNamespace(Paragon=SimpleNamespace(value=9)),
        Routines=SimpleNamespace(Party=SimpleNamespace(IsPartyMember=runtime_stub(lambda _: True))),
        Party=SimpleNamespace(
            GetPlayers=runtime_stub(lambda: [SimpleNamespace(is_connected=True, login_number=hr.owner.login)]),
            Players=SimpleNamespace(GetAgentIDByLoginNumber=runtime_stub(lambda _: hr.owner.agent)),
        ),
    )

    def handler(email: str = "mesmer@example.test") -> Any:
        result = object.__new__(SHATTER.SmartShatterHex)
        result._disposed = False
        result._composition_generation = 4
        result._attempt_generation = 0
        result._pending_attempt = None
        result._skill_id = 67
        result._runtime_gate = runtime_stub(lambda: True)
        result._resolve_current_slot = runtime_stub(lambda: 4)

        def readiness(_slot: int, *, at_execution: bool) -> bool:
            return state.ready

        result._skill_readiness = readiness
        result._resolve_runtime_parameters = runtime_stub(lambda: state.parameters)
        result._read_lifecycle_inputs = runtime_stub(lambda: (42, 23, 5000, email, 5))
        result._validate_target_for_skill_cast = variadic_stub(lambda *_: True)
        result._build_enemy_snapshot = runtime_stub(lambda: ())
        result._is_local_cast_pending = runtime_stub(lambda: False)
        result._mark_local_cast_pending = runtime_stub(lambda _: None)
        result._hex_identity_evidence = variadic_stub(
            lambda *_: pytest.fail("Urgency must not scan or require the legacy reader")
        )
        return result

    state.new_handler = handler
    state.handler = handler()
    state.publish = runtime_stub(
        lambda ids=frozenset({883}), remaining=6000, count=1: hr.table.publish(
            hr.publisher, hr.owner, hr.context.instance, hr.clock[0], hr.module.HrHexCensus(ids, count, remaining)
        )
    )
    assert state.publish()
    return state


def urgent_offer(handler: Any) -> bool:
    return _generator_result(
        handler.try_cast_urgent(handler.prepare_pass(), getattr(handler, "_shatter_observation_epoch", None))
    )


def test_owner_positive_without_legacy_qualifies_and_uses_real_queue(urgent_runtime: Any) -> None:
    runtime = urgent_runtime
    assert urgent_offer(runtime.handler)
    attempt = runtime.handler._pending_attempt
    assert runtime.native == [] and attempt.enqueue_accepted
    assert runtime.handler._hr_samples_used[0].sequence == 1
    assert runtime.queue.execute_next()
    assert runtime.native == [(4, 77)]
    assert attempt.state == "sent"
    assert runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)
    assert runtime.queries and all(value == (883, 2, 9) for value in runtime.queries)


@pytest.mark.parametrize("reason", ["missing", "stale", "future", "unknown", "no_vm", "low_vm"])
def test_legacy_positive_cannot_supply_early_evidence(urgent_runtime: Any, reason: str) -> None:
    runtime = urgent_runtime
    hr = runtime.hr
    if reason == "missing":
        hr.table.invalidate(hr.publisher)
    elif reason == "stale":
        hr.clock[0] += 750
    elif reason == "future":
        hr.clock[0] -= 1
    elif reason == "low_vm":
        runtime.priority = 1
    else:
        hr.clock[0] += 250
        assert runtime.publish(frozenset({883}) if reason == "unknown" else frozenset({123}), None)
    runtime.handler._hex_identity_evidence = variadic_stub(lambda *_: SHATTER.HexIdentityEvidence(1, 1, 3))
    runtime.handler._build_enemy_snapshot = runtime_stub(
        lambda: pytest.fail("No owner candidate should trigger an enemy scan")
    )
    assert not urgent_offer(runtime.handler)
    assert runtime.queue.is_empty()


@pytest.mark.parametrize(
    "age,remaining,expected",
    [(749, 3250, True), (749, 3249, False), (0, 2500, False), (0, 2501, True), (750, 9000, False)],
)
def test_vm_duration_is_aged_at_strict_boundary(urgent_runtime: Any, age: int, remaining: int, expected: bool) -> None:
    runtime = urgent_runtime
    runtime.hr.clock[0] += 250
    assert runtime.publish(remaining=remaining)
    runtime.hr.clock[0] += age
    assert urgent_offer(runtime.handler) is expected


def test_repeated_urgency_requires_new_sample_even_after_cancel(urgent_runtime: Any) -> None:
    runtime = urgent_runtime
    handler = runtime.handler
    assert urgent_offer(handler)
    handler.cancel_pending("cancel accepted work")
    assert not urgent_offer(handler), "accepted enqueue consumes the sample even when later cancelled"
    runtime.hr.clock[0] += 250
    assert runtime.publish(count=4)
    assert urgent_offer(handler), "continuous hexed flag and increased entry count do not prevent a new opportunity"
    accepted = handler._pending_attempt
    runtime.hr.clock[0] += 250
    assert runtime.publish(count=1)
    assert handler._revalidate_selected(accepted, at_execution=True) is not None
    assert handler._hr_samples_used[0].sequence == 3
    handler.cancel_pending("later cancellation")
    assert not urgent_offer(handler), "a newer sample used by the accepted callback remains consumed"
    assert runtime.native == []


def test_two_mesmers_share_record_but_contend_through_existing_claims(urgent_runtime: Any) -> None:
    runtime = urgent_runtime
    first, second = runtime.handler, runtime.new_handler("second@example.test")
    assert urgent_offer(first)
    token = first._pending_attempt.claim_token
    runtime.email = "second@example.test"
    assert not urgent_offer(second)
    assert not getattr(second, "_hr_samples_used", {})
    first.cancel_pending("pre-send cancellation")
    assert urgent_offer(second), "different clients keep local watermarks; exact common target claim coordinates them"
    assert second._pending_attempt.hr_observation.sequence == 1
    assert not runtime.accounts.ReleaseHexRemovalClaim(token), "stale release must not touch successor"
    assert runtime.accounts.IsHexRemovalClaimOwned(second._pending_attempt.claim_token)


def test_failed_hr_claim_never_promotes_ordinary_target_and_is_not_reacquired_same_pass(urgent_runtime: Any) -> None:
    runtime = urgent_runtime
    foreign = runtime.accounts.TryAcquireHexRemovalTarget("second@example.test", 77, 3400, 5).token
    assert foreign is not None
    preparation = runtime.handler.prepare_pass()
    assert not _generator_result(runtime.handler.try_cast_urgent(preparation))
    assert runtime.queue.is_empty() and preparation.attempted_targets == {77}
    assert runtime.accounts.ReleaseHexRemovalClaim(foreign)
    runtime.handler._build_snapshot = variadic_stub(lambda *_args, **_kwargs: ((_ally(77), _ally(88)), ()))
    runtime.handler._revalidate_selected = variadic_stub(lambda *_args, **_kwargs: runtime.parameters)
    assert _generator_result(runtime.handler.try_cast(preparation))
    assert runtime.handler._pending_attempt.target_agent_id == 88


@pytest.mark.parametrize(
    "reason",
    [
        "disappeared",
        "equipment",
        "stale",
        "profile",
        "energy",
        "range",
        "readiness",
        "binding",
        "regression",
        "invalid_target",
        "not_hexed",
    ],
)
def test_final_urgent_admission_cancels_precisely(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    runtime = urgent_runtime
    assert urgent_offer(runtime.handler)
    attempt = runtime.handler._pending_attempt
    before = attempt.hr_observation
    if reason == "stale":
        runtime.hr.clock[0] += 750
    elif reason in {"disappeared", "equipment"}:
        runtime.hr.table.invalidate(runtime.hr.publisher, stop=False)
    elif reason == "profile":
        runtime.priority = 0
    elif reason == "energy":
        runtime.parameters = replace(runtime.parameters, policy=_policy(affordable=False))
    elif reason == "range":
        runtime.x = 1249
    elif reason == "readiness":
        runtime.ready = False
    elif reason == "invalid_target":
        runtime.valid = False
    elif reason == "not_hexed":
        runtime.hexed = False
    else:
        value = (
            replace(before, sequence=0) if reason == "regression" else replace(before, incarnation=(999, b"n" * 16, 1))
        )
        monkeypatch.setattr(runtime.hr.table, "read", variadic_stub(lambda *_: value))
    assert runtime.queue.execute_next()
    assert runtime.native == [] and runtime.handler._pending_attempt is None
    assert not runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)
    assert runtime.handler._hr_samples_used[0] == before


@pytest.mark.parametrize("native_result", [True, False, RuntimeError("native uncertainty")])
def test_urgent_native_boundary_keeps_finite_lease(urgent_runtime: Any, native_result: Any) -> None:
    runtime = urgent_runtime
    runtime.native_result = native_result
    assert urgent_offer(runtime.handler)
    attempt = runtime.handler._pending_attempt
    old_token = attempt.claim_token
    assert runtime.queue.execute_next()
    assert runtime.native == [(4, 77)] and attempt.state == "sent"
    assert attempt.claim_token is not old_token
    assert not runtime.accounts.ReleaseHexRemovalClaim(old_token)
    assert runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)
    runtime.hr.clock[0] += 3400
    assert not runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)


def test_stale_callback_cannot_advance_successor_accounting(urgent_runtime: Any) -> None:
    runtime = urgent_runtime
    assert urgent_offer(runtime.handler)
    old = runtime.handler._pending_attempt
    runtime.handler.cancel_pending("composition changed")
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    assert urgent_offer(runtime.handler)
    successor = runtime.handler._pending_attempt
    watermark = runtime.handler._hr_samples_used[0]
    assert not runtime.handler._execute_queued_guard(
        old, variadic_stub(lambda *_: pytest.fail("stale native callback"))
    )
    assert runtime.handler._pending_attempt is successor
    assert runtime.handler._hr_samples_used[0] == watermark
    assert runtime.accounts.IsHexRemovalClaimOwned(successor.claim_token)


def test_definite_enqueue_exception_does_not_consume_sample(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = urgent_runtime
    skillbar = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.SkillBar

    def reject(_callback: Any) -> None:
        raise ValueError("queue missing")

    monkeypatch.setattr(skillbar, "QueueGuardedUseSkill", reject)
    assert not urgent_offer(runtime.handler)
    assert runtime.handler._pending_attempt is None
    assert not getattr(runtime.handler, "_hr_samples_used", {})


def test_urgent_diagnostic_failure_preserves_claim_and_result(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = urgent_runtime
    observation, _clock, epoch = arm_observation_fixture(monkeypatch)
    runtime.handler._shatter_observation_epoch = epoch

    def fail(*_args: Any) -> Any:
        raise RuntimeError("diagnostic fault")

    monkeypatch.setattr(observation, "_binding", fail)
    runtime.handler._format_live_decision = fail
    assert urgent_offer(runtime.handler)
    assert runtime.queue.execute_next()
    assert runtime.native == [(4, 77)]
    assert runtime.accounts.IsHexRemovalClaimOwned(runtime.handler._pending_attempt.claim_token)


def test_vm_urgency_uses_real_saved_profession_override(
    hr: Any, hex_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = sys.modules["Py4GWCoreLib"]
    priority, config = hex_runtime.priority, hex_runtime.config
    core.GLOBAL_CACHE.Skill.GetID = runtime_stub(lambda name: 883 if name == "Vocal_Minority" else 0)
    core.GLOBAL_CACHE.Skill.Flags.IsHex = runtime_stub(lambda skill_id: skill_id == 883)
    core.__dict__["Agent"] = SimpleNamespace(
        GetLoginNumber=runtime_stub(lambda _: 22), GetNameByID=runtime_stub(lambda _: "Fixture HR")
    )
    core.__dict__["Profession"] = SimpleNamespace(Paragon=SimpleNamespace(value=9))
    assert hr.table.publish(
        hr.publisher, hr.owner, hr.context.instance, hr.clock[0], hr.module.HrHexCensus(frozenset({883}), 1, 6000)
    )
    core.GLOBAL_CACHE.ShMem = SimpleNamespace(
        ReadHrHexObservation=variadic_stub(lambda *_: hr.table.read(hr.owner, hr.context.instance))
    )
    for character, override in (("Character A", 3), ("Character B", 0)):
        entry = priority.HexRemovalEntry(caster=3, ranged_martial=3, melee=3, by_profession={9: override})
        hex_runtime.profile_states[("account-a@example.test", character)] = config.ConfigState(
            hexes={"Vocal_Minority": config.HexEntryState(entry=entry)}
        )
    handler = object.__new__(SHATTER.SmartShatterHex)
    handler._observe_urgent_ally = runtime_stub(lambda _: _ally(77))
    assert handler._read_urgent_hr(77) is not None
    assert handler._failed_hr_claim_is_urgent(77, _policy())
    assert len(hex_runtime.profile_loads) == 1, "preservation must reuse the effective profile cache"
    hex_runtime.active_identity[:] = ["account-a@example.test", "Character B"]
    assert handler._read_urgent_hr(77) is None
    assert not handler._failed_hr_claim_is_urgent(77, _policy())
    assert len(hex_runtime.profile_loads) == 2


def test_post_acquisition_loss_does_not_consume_sample(urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = urgent_runtime
    locks = sys.modules["Py4GWCoreLib.GlobalCache.WhiteboardLocks"]
    acquire = locks.try_acquire_hex_removal_claim
    acquired: list[Any] = []

    def acquire_then_invalidate(target: int, duration: int) -> Any:
        token = acquire(target, duration)
        acquired.append(token)
        runtime.hr.table.invalidate(runtime.hr.publisher, stop=False)
        return token

    monkeypatch.setattr(locks, "try_acquire_hex_removal_claim", acquire_then_invalidate)
    assert not urgent_offer(runtime.handler)
    assert len(acquired) == 1 and acquired[0] is not None
    assert not runtime.accounts.IsHexRemovalClaimOwned(acquired[0])
    assert runtime.queue.is_empty() and not getattr(runtime.handler, "_hr_samples_used", {})


def test_newer_sample_seen_by_accepted_attempt_is_not_replayed_after_target_failure(urgent_runtime: Any) -> None:
    runtime = urgent_runtime
    assert urgent_offer(runtime.handler)
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    runtime.x = 1249
    assert runtime.queue.execute_next()
    assert runtime.native == [] and runtime.handler._hr_samples_used[0].sequence == 2
    runtime.x = 100
    assert not urgent_offer(runtime.handler)


def test_pass_generation_change_does_not_reuse_preparation(urgent_runtime: Any) -> None:
    runtime = urgent_runtime
    preparation = runtime.handler.prepare_pass()
    runtime.handler._composition_generation += 1
    assert not _generator_result(runtime.handler.try_cast_urgent(preparation))
    assert runtime.queue.is_empty()


@pytest.mark.parametrize("completion", ["cancel", "decline", "native", "newer_decline"])
def test_accepted_enqueue_consumed_when_callback_thread_finishes_before_return(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch, completion: str
) -> None:
    runtime = urgent_runtime
    errors: list[BaseException] = []
    overlap: list[bool] = []
    handler = runtime.handler
    skillbar = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.SkillBar
    enqueue = skillbar.QueueGuardedUseSkill
    claims: list[int] = []
    locks = sys.modules["Py4GWCoreLib.GlobalCache.WhiteboardLocks"]
    acquire = locks.try_acquire_hex_removal_claim

    def counted_claim(target: int, duration: int) -> Any:
        claims.append(target)
        return acquire(target, duration)

    def after_append() -> None:
        try:
            if completion == "cancel":
                handler.cancel_pending("accepted queue canceled before bookkeeping")
            else:
                if completion == "decline":
                    runtime.ready = False
                elif completion == "newer_decline":
                    runtime.hr.clock[0] += 250
                    assert runtime.publish()
                    runtime.x = 1249
                assert runtime.queue.execute_next()
                runtime.ready, runtime.x = True, 100
            overlap.append(urgent_offer(handler))
        except BaseException as error:
            errors.append(error)

    def enqueue_and_complete(callback: Any) -> None:
        result = enqueue(callback)
        assert result is None and len(runtime.queue.queue) == 1
        thread = threading.Thread(target=after_append)
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), "submission must not hold a lock required by cancellation/callback"

    monkeypatch.setattr(locks, "try_acquire_hex_removal_claim", counted_claim)
    monkeypatch.setattr(skillbar, "QueueGuardedUseSkill", enqueue_and_complete)
    assert urgent_offer(handler)
    assert not errors and overlap == [False] and claims == [77]
    expected_sequence = 2 if completion == "newer_decline" else 1
    assert handler._hr_samples_used[0].sequence == expected_sequence
    assert runtime.native == ([(4, 77)] if completion == "native" else [])
    monkeypatch.setattr(skillbar, "QueueGuardedUseSkill", enqueue)
    assert not urgent_offer(handler), "accepted enqueue is never refunded by callback completion/cancellation"
    assert claims == [77]
    if completion != "native":
        runtime.hr.clock[0] += 250
        assert runtime.publish()
        assert urgent_offer(handler)
        assert claims == [77, 77]


@pytest.mark.parametrize("transition", ["cancel", "slot", "composition", "profile"])
def test_cancellation_transitions_do_not_refund_accepted_owner_sample(urgent_runtime: Any, transition: str) -> None:
    runtime = urgent_runtime
    handler = runtime.handler
    assert urgent_offer(handler)
    if transition == "slot":
        handler.set_skill_slot(5)
    elif transition == "composition":
        handler.update_lifecycle(5)
    elif transition == "profile":
        runtime.priority = 0
        assert runtime.queue.execute_next()
        runtime.priority = 3
    else:
        handler.cancel_pending("ordinary cancellation")
    assert handler._hr_samples_used[0].sequence == 1
    assert not urgent_offer(handler)


def test_new_owner_scope_and_late_old_accounting_protect_successor(urgent_runtime: Any) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    assert urgent_offer(handler)
    old = handler._pending_attempt
    handler.cancel_pending("replace owner context")
    runtime.hr.clock[0] += 250
    runtime.hr.publisher = runtime.hr.identity.Publisher()
    assert runtime.publish()
    assert urgent_offer(handler), "a genuine new publisher incarnation permits its first sequence"
    successor = handler._pending_attempt
    saved = handler._hr_samples_used[0]
    assert saved.sequence == 1 and saved.binding != old.hr_observation.binding
    handler._consume_accepted_hr_sample(old)
    assert not handler._advance_hr_sample(old, replace(old.hr_observation, sequence=99))
    assert handler._hr_samples_used[0] == saved
    assert runtime.accounts.IsHexRemovalClaimOwned(successor.claim_token)
    assert len(handler._hr_samples_used) == len(handler._hr_sample_generations) == 1


@pytest.fixture
def production_cost_runtime(urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    runtime = urgent_runtime
    handler = runtime.handler
    core = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    path = Path(__file__).resolve().parents[1] / "Py4GWCoreLib/routines_src/Checks.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    checks = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Checks")
    skills = next(node for node in checks.body if isinstance(node, ast.ClassDef) and node.name == "Skills")
    skills.body = [
        node
        for node in skills.body
        if isinstance(node, ast.FunctionDef) and node.name in ("GetEnergyCostWithEffects", "HasEnoughEnergy")
    ]
    checks.body = [skills]
    namespace: dict[str, Any] = {
        "__name__": "Py4GWCoreLib.routines_src.Checks",
        "__package__": "Py4GWCoreLib.routines_src",
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[checks], type_ignores=[])), str(path), "exec"), namespace)
    runtime.energy, runtime.position, runtime.scans, runtime.readiness_calls = 1.0, (0.0, 0.0), [], []
    agent = types.ModuleType("Py4GWCoreLib.Agent")
    agent.__dict__["Agent"] = core.Agent
    monkeypatch.setitem(sys.modules, agent.__name__, agent)
    core.Agent.GetEnergy = runtime_stub(lambda _: runtime.energy)
    core.Agent.GetMaxEnergy = runtime_stub(lambda _: 40)
    core.__dict__["Player"] = SimpleNamespace(
        GetAgentID=runtime_stub(lambda: 23), GetXY=runtime_stub(lambda: runtime.position)
    )
    core.__dict__["Range"] = SimpleNamespace(Spellcast=SimpleNamespace(value=1248), Nearby=SimpleNamespace(value=252))
    core.GLOBAL_CACHE.Effects = SimpleNamespace(
        GetEffects=runtime_stub(lambda agent_id: runtime.scans.append(agent_id) or [])
    )
    core.GLOBAL_CACHE.Skill = SimpleNamespace(
        Data=SimpleNamespace(
            GetEnergyCost=runtime_stub(lambda _: 10),
            GetActivation=runtime_stub(lambda _: 1),
            GetAftercast=runtime_stub(lambda _: 0.25),
        )
    )
    core.Routines.Checks = SimpleNamespace(Skills=namespace["Checks"].Skills)
    sys.modules["Py4GWCoreLib.GlobalCache"].__dict__["GLOBAL_CACHE"] = core.GLOBAL_CACHE
    handler._resolve_runtime_parameters = types.MethodType(SHATTER.SmartShatterHex._resolve_runtime_parameters, handler)
    handler._current_domination_rank = variadic_stub(lambda *_: 12)
    handler._observed_ping_ms = runtime_stub(lambda: 150)
    handler._build_snapshot = variadic_stub(lambda *_args, **_kwargs: ((), ()))

    def readiness(slot: int, *, at_execution: bool) -> bool:
        runtime.readiness_calls.append((slot, at_execution))
        return runtime.ready

    handler._skill_readiness = readiness
    return runtime


@pytest.mark.parametrize("reason", ["missing", "stale", "unauthorized", "no_vm", "low_priority", "short_duration"])
def test_no_urgent_owner_avoids_production_energy_effect_reads(
    production_cost_runtime: Any, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    runtime = production_cost_runtime
    handler = runtime.handler
    if reason == "missing":
        runtime.hr.table.invalidate(runtime.hr.publisher)
    elif reason == "stale":
        runtime.hr.clock[0] += 750
    elif reason == "unauthorized":
        shmem = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem
        monkeypatch.setattr(shmem, "ReadHrHexObservation", variadic_stub(lambda *_: None))
    elif reason == "low_priority":
        runtime.priority = 1
    else:
        runtime.hr.clock[0] += 250
        assert runtime.publish(
            frozenset({123}) if reason == "no_vm" else frozenset({883}), None if reason == "no_vm" else 2500
        )
    preparation = handler.prepare_pass()
    assert not _generator_result(handler.try_cast_urgent(preparation))
    assert runtime.scans == [] and runtime.readiness_calls == []
    assert not _generator_result(handler.try_cast(preparation))
    assert runtime.scans == [23, 23], "ordinary-only production cost baseline is two enumerations"
    assert runtime.readiness_calls == [(4, False)] and runtime.native == [] and runtime.queue.is_empty()


def test_qualifying_urgent_cost_reads_remain_fresh_at_both_admission_boundaries(production_cost_runtime: Any) -> None:
    runtime = production_cost_runtime
    assert urgent_offer(runtime.handler)
    assert runtime.scans == [23] * 4, "selection and post-acquisition must each resolve fresh production cost"
    assert runtime.queue.execute_next()
    assert runtime.scans == [23] * 6 and runtime.native == [(4, 77)]


@pytest.fixture
def preservation_runtime(production_cost_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    runtime = production_cost_runtime
    runtime.fallback_priority = 2
    runtime.claims = []
    runtime.owner_reads = []
    runtime.authorized = True
    runtime.allowed = True
    core = SHATTER._test_runtime_modules["Py4GWCoreLib"]

    def read_owner(target: int, _login: int, _name: str) -> Any:
        runtime.owner_reads.append(target)
        return (
            runtime.hr.table.read(runtime.hr.owner, runtime.hr.context.instance)
            if target == 77 and runtime.authorized
            else None
        )

    monkeypatch.setattr(core.GLOBAL_CACHE.ShMem, "ReadHrHexObservation", read_owner)
    runtime.handler._validate_target_for_skill_cast = runtime_stub(
        lambda _skill, target: target != 77 or runtime.allowed
    )

    def snapshot(_parameters: Any, *, selected_agent_id: int | None = None, observation: Any = None) -> Any:
        allies = (
            _ally(77, is_valid=runtime.valid, is_hexed=runtime.hexed, x=runtime.x, target_is_allowed=runtime.allowed),
            _ally(88, hex_priority=runtime.fallback_priority),
        )
        return tuple(ally for ally in allies if selected_agent_id is None or ally.agent_id == selected_agent_id), (
            _enemy(),
        )

    runtime.handler._build_snapshot = snapshot
    locks = sys.modules["Py4GWCoreLib.GlobalCache.WhiteboardLocks"]
    acquire = locks.try_acquire_hex_removal_claim

    def counted_acquire(target: int, duration: int) -> Any:
        runtime.claims.append(target)
        return acquire(target, duration)

    monkeypatch.setattr(locks, "try_acquire_hex_removal_claim", counted_acquire)
    runtime.foreign = runtime.accounts.TryAcquireHexRemovalTarget("second@example.test", 77, 3400, 5).token
    assert runtime.foreign is not None
    return runtime


@pytest.mark.parametrize("early", [True, False])
@pytest.mark.parametrize("priority", [1, 2, None])
def test_hr_claim_failure_preserves_shatter_below_high(
    preservation_runtime: Any, early: bool, priority: int | None
) -> None:
    runtime, handler = preservation_runtime, preservation_runtime.handler
    runtime.fallback_priority = priority
    preparation = handler.prepare_pass() if early else None
    if early:
        assert not _generator_result(handler.try_cast_urgent(preparation))
    assert not _generator_result(handler.try_cast(preparation)), (early, priority, runtime.claims)
    assert runtime.claims == [77] and runtime.queue.is_empty() and runtime.native == []
    assert not handler.has_active_dispatch() and not getattr(handler, "_hr_samples_used", {})
    assert runtime.accounts.IsHexRemovalClaimOwned(runtime.foreign)
    assert runtime.scans == [23, 23], "preservation adds no energy or legacy effect enumerations"
    assert runtime.owner_reads == ([77, 77] if early else [77])
    assert len(runtime.queries) == (2 if early else 1), "only VM's effective priority is queried"


@pytest.mark.parametrize("early", [True, False])
def test_hr_claim_failure_keeps_high_alternative_and_real_queue(preservation_runtime: Any, early: bool) -> None:
    runtime, handler = preservation_runtime, preservation_runtime.handler
    runtime.fallback_priority = 3
    preparation = handler.prepare_pass() if early else None
    if early:
        assert not _generator_result(handler.try_cast_urgent(preparation))
    assert _generator_result(handler.try_cast(preparation))
    attempt = handler._pending_attempt
    assert runtime.claims == [77, 88] and attempt.target_agent_id == 88 and attempt.hr_observation is None
    assert runtime.owner_reads == ([77] if early else []), "HIGH alternatives need no preservation probe"
    assert runtime.queue.execute_next() and runtime.native == [(4, 88)]
    assert attempt.state == "sent" and runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)
    assert runtime.accounts.IsHexRemovalClaimOwned(runtime.foreign)
    assert runtime.scans == [23] * 6


@pytest.mark.parametrize("early", [True, False])
@pytest.mark.parametrize(
    "loss",
    [
        "missing",
        "stale",
        "future",
        "empty",
        "unknown",
        "short",
        "unauthorized",
        "invalid",
        "range",
        "cleansed",
        "blocked",
        "none",
        "low",
        "medium",
    ],
)
def test_hr_preservation_requires_current_owner_evidence_and_eligibility(
    preservation_runtime: Any, early: bool, loss: str
) -> None:
    runtime, handler = preservation_runtime, preservation_runtime.handler
    preparation = handler.prepare_pass()
    if early:
        assert not _generator_result(handler.try_cast_urgent(preparation))
        preparation.invalidate_parameters()  # The scheduler may suspend on intervening offense.
    if loss == "missing":
        runtime.hr.table.invalidate(runtime.hr.publisher)
    elif loss == "stale":
        runtime.hr.clock[0] += 750
    elif loss == "future":
        runtime.hr.clock[0] += 250
        assert runtime.publish()
        runtime.hr.clock[0] -= 1  # Publication is future-dated; the older claim remains within its lease.
    elif loss == "unauthorized":
        runtime.authorized = False
    elif loss == "invalid":
        runtime.valid = False
    elif loss == "range":
        runtime.x = 1249.0
    elif loss == "cleansed":
        runtime.hexed = False
    elif loss == "blocked":
        runtime.allowed = False
    elif loss in ("none", "low", "medium"):
        runtime.priority = {"none": 0, "low": 1, "medium": 2}[loss]
    else:
        runtime.hr.clock[0] += 250
        assert runtime.publish(
            frozenset() if loss == "empty" else frozenset({883}),
            None if loss != "short" else 2500,
            0 if loss == "empty" else 1,
        )
    if not early:
        assert not _generator_result(handler.try_cast_urgent(preparation))
    assert _generator_result(handler.try_cast(preparation)), (early, loss, runtime.claims)
    assert runtime.claims.count(77) <= 1 and runtime.claims[-1] == 88
    assert runtime.queue.execute_next() and runtime.native == [(4, 88)]
    assert runtime.accounts.IsHexRemovalClaimOwned(runtime.foreign)


def test_hr_preservation_expires_with_pass_and_does_not_consume_owner_sample(preservation_runtime: Any) -> None:
    runtime, handler = preservation_runtime, preservation_runtime.handler
    preparation = handler.prepare_pass()
    assert not _generator_result(handler.try_cast_urgent(preparation))
    assert not _generator_result(handler.try_cast(preparation))
    assert runtime.accounts.ReleaseHexRemovalClaim(runtime.foreign)
    assert urgent_offer(handler), "a new pass can retry the still-unused owner sample"
    attempt = handler._pending_attempt
    assert runtime.claims == [77, 77] and handler._hr_samples_used[0].sequence == 1
    assert runtime.queue.execute_next() and runtime.native == [(4, 77)]
    assert runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)


def test_hr_preservation_does_not_infer_why_claim_returned_none(
    preservation_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, handler = preservation_runtime, preservation_runtime.handler
    assert runtime.accounts.ReleaseHexRemovalClaim(runtime.foreign)
    locks = sys.modules["Py4GWCoreLib.GlobalCache.WhiteboardLocks"]
    monkeypatch.setattr(
        locks, "try_acquire_hex_removal_claim", runtime_stub(lambda target, _duration: runtime.claims.append(target))
    )
    assert not _generator_result(handler.try_cast())
    assert runtime.claims == [77] and runtime.queue.is_empty() and runtime.native == []


@pytest.mark.parametrize("winner", ["energy", "residual", "fallback"])
def test_hr_preservation_keeps_real_composition_scheduling(
    preservation_runtime: Any, monkeypatch: pytest.MonkeyPatch, winner: str
) -> None:
    runtime, handler = preservation_runtime, preservation_runtime.handler
    fixture = load_source(
        "_hr_preservation_composition_fixture",
        Path(__file__).resolve().parents[1] / "Examples and tests/tests/test_my_mesmer_composition.py",
        monkeypatch,
    )
    # Reuse the composition harness, then reconnect its real scheduler to this
    # test's real Shatter/claim/ACTION boundary and isolated game observations.
    modules = {name: module for name, module in sys.modules.items() if name.startswith("Py4GWCoreLib")}
    with fixture._loaded_runtime() as (module, scheduling, _smart_energy):
        build = fixture._composition(scheduling, module)
        energy = scheduling.factory(skill_id=39)
        residual = scheduling.factory(skill_id=934)
        scheduling.handler_results[39] = winner == "energy"
        scheduling.handler_results[934] = winner == "residual"
        build._active_handlers = {67: handler, 39: energy, 934: residual}
        build._composition_generation = 4
        build._equipped_bar = (0, 0, 0, 67, 39, 934, 0, 0)
        build._skill_slots = {67: 4, 39: 5, 934: 6}
        build._refresh_composition = runtime_stub(lambda: None)
        module.get_energy_surge_id = runtime_stub(lambda: 39)
        module.get_cry_of_frustration_id = runtime_stub(lambda: 55)
        sys.modules.update(modules)
        assert _generator_result(build.ProcessSkillCasting()), winner
        assert scheduling.attempt_order == ([39] if winner == "energy" else [39, 934])
        assert build.fallback.calls == int(winner == "fallback")
        assert runtime.claims == [77] and runtime.queue.is_empty() and runtime.native == []
        assert not handler.has_active_dispatch() and runtime.accounts.IsHexRemovalClaimOwned(runtime.foreign)
        assert runtime.owner_reads == ([77] if winner == "energy" else [77, 77])


def test_hr_post_acquisition_loss_does_not_activate_claim_failure_preservation(
    preservation_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, handler = preservation_runtime, preservation_runtime.handler
    assert runtime.accounts.ReleaseHexRemovalClaim(runtime.foreign)
    locks = sys.modules["Py4GWCoreLib.GlobalCache.WhiteboardLocks"]
    acquire = locks.try_acquire_hex_removal_claim

    def lose_hr_claim(target: int, duration: int) -> Any:
        token = acquire(target, duration)
        if target == 77:
            assert runtime.accounts.ReleaseHexRemovalClaim(token)
        return token

    monkeypatch.setattr(locks, "try_acquire_hex_removal_claim", lose_hr_claim)
    assert _generator_result(handler.try_cast())
    assert runtime.claims == [77, 88] and runtime.owner_reads == []
    assert runtime.queue.execute_next() and runtime.native == [(4, 88)]


def test_failed_early_claim_reuses_cost_only_for_ordinary_selection(production_cost_runtime: Any) -> None:
    runtime, handler = production_cost_runtime, production_cost_runtime.handler
    foreign = runtime.accounts.TryAcquireHexRemovalTarget("second@example.test", 77, 3400, 5).token
    assert foreign is not None
    preparation = handler.prepare_pass()
    assert not _generator_result(handler.try_cast_urgent(preparation))
    assert runtime.scans == [23, 23]

    def ordinary_snapshot(_parameters: Any, *, selected_agent_id: int | None = None, observation: Any = None) -> Any:
        return ((_ally(selected_agent_id),), ()) if selected_agent_id else ((_ally(77), _ally(88)), ())

    handler._build_snapshot = ordinary_snapshot
    assert _generator_result(handler.try_cast(preparation))
    assert handler._pending_attempt.target_agent_id == 88
    assert runtime.scans == [23] * 4, "ordinary admission is fresh; ordinary selection reuses this uninterrupted pass"
    assert runtime.queue.execute_next()
    assert runtime.scans == [23] * 6 and runtime.native == [(4, 88)]
    assert runtime.accounts.IsHexRemovalClaimOwned(foreign)


@pytest.mark.parametrize("change", ["yield", "context", "readiness", "energy", "position", "cancel"])
def test_state_change_discards_pass_parameters(production_cost_runtime: Any, change: str) -> None:
    runtime, handler = production_cost_runtime, production_cost_runtime.handler
    assert runtime.accounts.TryAcquireHexRemovalTarget("second@example.test", 77, 3400, 5).token is not None
    preparation = handler.prepare_pass()
    assert not _generator_result(handler.try_cast_urgent(preparation))
    assert runtime.scans == [23, 23]
    if change == "yield":
        preparation.invalidate_parameters()
    elif change == "context":
        handler._read_lifecycle_inputs = runtime_stub(lambda: (43, 23, 5001, "mesmer@example.test", 5))
    elif change == "readiness":
        runtime.ready = False
        assert not _generator_result(handler.try_cast(preparation))
        assert preparation.parameters is None
        runtime.ready = True
    elif change == "energy":
        runtime.energy = 0.5
    elif change == "position":
        runtime.position = (1.0, 0.0)
    else:
        handler.cancel_pending("lifecycle changed between offers")
    assert not _generator_result(handler.try_cast(preparation))
    assert runtime.scans == [23] * 4 and runtime.native == []


class _FailingAccountingWrites(dict[int, Any]):
    def __init__(self, failure: type[Exception] = MemoryError) -> None:
        super().__init__()
        self.failure = failure
        self.writes = 0

    def __setitem__(self, key: int, value: Any) -> None:
        self.writes += 1
        raise self.failure("injected actual accounting assignment failure")


@pytest.mark.parametrize("failure", [RuntimeError, MemoryError])
@pytest.mark.parametrize("storage", ["_hr_samples_used", "_hr_sample_generations"])
def test_accepted_assignment_failure_is_sticky_for_same_owner_scope(
    urgent_runtime: Any, failure: type[Exception], storage: str
) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    broken = _FailingAccountingWrites(failure)
    setattr(handler, storage, broken)
    with pytest.raises(failure, match="actual accounting assignment"):
        urgent_offer(handler)
    attempt = handler._pending_attempt
    assert attempt.enqueue_accepted and broken.writes == 1 and len(runtime.queue.queue) == 1
    assert runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)
    handler.cancel_pending("urgent_handler_exception")
    assert not runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)
    setattr(handler, storage, {})
    for _ in range(3):
        assert not urgent_offer(handler), "neither the same sample nor newer samples repair uncertain accounting"
        runtime.hr.clock[0] += 250
        assert runtime.publish()
    assert len(runtime.queue.queue) == 1 and runtime.native == []
    assert handler._hr_accounting_attempts[0] is attempt and attempt.hr_accounting_failed


@pytest.mark.parametrize("timing", ["before_return", "after_failure"])
@pytest.mark.parametrize("completion", ["cancel", "decline", "native"])
def test_accounting_failure_keeps_callback_and_lease_safety(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch, timing: str, completion: str
) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    skillbar = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.SkillBar
    enqueue = skillbar.QueueGuardedUseSkill
    errors: list[BaseException] = []
    overlap: list[bool] = []
    handler._hr_samples_used = _FailingAccountingWrites()

    def complete() -> None:
        try:
            if completion == "cancel":
                handler.cancel_pending("callback canceled accepted work")
            else:
                runtime.ready = completion != "decline"
                assert runtime.queue.execute_next()
                runtime.ready = True
            overlap.append(urgent_offer(handler))
        except BaseException as error:
            errors.append(error)

    def complete_on_thread() -> None:
        thread = threading.Thread(target=complete)
        thread.start()
        thread.join(5)
        assert not thread.is_alive(), "accounting protection must not deadlock a queued callback"

    def submit(callback: Any) -> None:
        assert enqueue(callback) is None and len(runtime.queue.queue) == 1
        if timing == "before_return":
            complete_on_thread()

    monkeypatch.setattr(skillbar, "QueueGuardedUseSkill", submit)
    with pytest.raises(MemoryError):
        urgent_offer(handler)
    attempt = handler._hr_accounting_attempts[0]
    assert attempt.enqueue_accepted and attempt.hr_accounting_failed
    handler._hr_samples_used = {}
    if timing == "after_failure":
        complete_on_thread()
    assert errors == [] and overlap == [False]
    assert runtime.native == ([(4, 77)] if completion == "native" else [])
    token = attempt.claim_token
    handler.cancel_pending("urgent_handler_exception")
    assert runtime.accounts.IsHexRemovalClaimOwned(token) is (completion == "native")
    assert not urgent_offer(handler)
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    assert not urgent_offer(handler), "a successful late callback cannot clear a prior accounting failure"
    if completion == "native":
        runtime.hr.clock[0] += 3400
        assert not runtime.accounts.IsHexRemovalClaimOwned(token), "the original finite lease still expires"


def test_later_callback_assignment_failure_preserves_newer_sample_uncertainty(urgent_runtime: Any) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    assert urgent_offer(handler)
    attempt = handler._pending_attempt
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    handler._hr_samples_used = _FailingAccountingWrites()
    with pytest.raises(MemoryError):
        runtime.queue.execute_next()
    assert attempt.enqueue_accepted and attempt.hr_observation.sequence == 2 and attempt.hr_accounting_failed
    handler.cancel_pending("callback_exception")
    handler._hr_samples_used = {}
    assert not urgent_offer(handler)
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    assert not urgent_offer(handler)
    assert runtime.native == [] and not runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)


@pytest.mark.parametrize("replacement", ["character", "context", "incarnation"])
def test_failed_accounting_allows_only_new_owner_binding_and_protects_successor(
    urgent_runtime: Any, replacement: str
) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    handler._hr_samples_used = _FailingAccountingWrites()
    with pytest.raises(MemoryError):
        urgent_offer(handler)
    old = handler._pending_attempt
    handler.cancel_pending("urgent_handler_exception")
    runtime.hr.clock[0] += 250
    if replacement == "character":
        runtime.hr.owner = replace(runtime.hr.owner, character="Replacement HR")
    elif replacement == "context":
        runtime.hr.context = replace(runtime.hr.context, instance=b"x" * 32)
    else:
        runtime.hr.publisher = runtime.hr.identity.Publisher()
    assert runtime.publish()
    handler._hr_samples_used = {}
    assert urgent_offer(handler)
    successor = handler._pending_attempt
    assert successor.hr_observation.binding != old.hr_observation.binding
    handler._consume_accepted_hr_sample(old)
    assert runtime.queue.execute_next(), "the old accepted callback remains queued"
    assert handler._pending_attempt is successor and runtime.native == []
    assert handler._hr_accounting_attempts[0] is successor and not successor.hr_accounting_failed
    assert runtime.accounts.IsHexRemovalClaimOwned(successor.claim_token)
    handler.cancel_pending("next normal attempt")
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    assert urgent_offer(handler), "normal newer-sample eligibility resumes only in the verified replacement scope"


@pytest.mark.parametrize("transition", ["cancel", "slot", "composition", "profile", "lifecycle"])
def test_accounting_suppression_survives_routine_transitions(urgent_runtime: Any, transition: str) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    handler._hr_samples_used = _FailingAccountingWrites()
    with pytest.raises(MemoryError):
        urgent_offer(handler)
    guarded = handler._pending_attempt
    handler._hr_samples_used = {}
    if transition == "slot":
        handler.set_skill_slot(5)
    elif transition == "composition":
        handler.update_lifecycle(5)
    elif transition == "profile":
        runtime.priority = 0
        assert runtime.queue.execute_next()
        runtime.priority = 3
    else:
        handler.cancel_pending("lifecycle_changed" if transition == "lifecycle" else "ordinary cancellation")
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    assert not urgent_offer(handler)
    assert handler._hr_accounting_attempts[0] is guarded and guarded.hr_accounting_failed


def test_definite_real_queue_rejection_restores_urgent_eligibility(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    skillbar = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.SkillBar
    queues = skillbar._action_queue_manager.queues
    action = queues["ACTION"]
    monkeypatch.delitem(queues, "ACTION")
    assert not urgent_offer(handler)
    assert handler._hr_accounting_attempts[0] is None and runtime.queue.is_empty()
    assert not getattr(handler, "_hr_samples_used", {})
    monkeypatch.setitem(queues, "ACTION", action)
    assert urgent_offer(handler)


def test_queue_metadata_failure_after_append_retains_uncertainty(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    skillbar = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.SkillBar
    action = skillbar._action_queue_manager.queues["ACTION"]

    class BrokenDelays:
        def append(self, _delay: int) -> None:
            raise MemoryError("aftercast bookkeeping failed after real ACTION append")

    with monkeypatch.context() as patch:
        patch.setattr(action, "_aftercast_delays", BrokenDelays())
        assert not urgent_offer(handler)
    guarded = handler._hr_accounting_attempts[0]
    assert not guarded.enqueue_accepted and not guarded.hr_accounting_complete
    assert len(runtime.queue.queue) == 1 and handler._pending_attempt is None
    assert not urgent_offer(handler), "queue-side exceptions cannot prove that no callback was appended"
    assert runtime.queue.execute_next() and runtime.native == []


def test_ordinary_shatter_and_cost_work_remain_available_during_urgent_suppression(
    production_cost_runtime: Any,
) -> None:
    runtime, handler = production_cost_runtime, production_cost_runtime.handler
    handler._hr_samples_used = _FailingAccountingWrites()
    with pytest.raises(MemoryError):
        urgent_offer(handler)
    handler.cancel_pending("urgent_handler_exception")
    handler._hr_samples_used = {}
    runtime.scans.clear()
    preparation = handler.prepare_pass()
    assert not _generator_result(handler.try_cast_urgent(preparation))
    assert runtime.scans == [], "suppression must not reintroduce the fixed urgent effect reads"
    handler._build_snapshot = variadic_stub(lambda *_args, **_kwargs: ((_ally(77), _ally(88)), ()))
    assert _generator_result(handler.try_cast(preparation))
    ordinary = handler._pending_attempt
    assert ordinary.hr_observation is None and ordinary.target_agent_id == 77
    assert runtime.scans == [23] * 4, "ordinary selection plus fresh post-acquisition validation"
    assert runtime.queue.execute_next() and runtime.native == []
    assert runtime.accounts.IsHexRemovalClaimOwned(ordinary.claim_token)
    assert runtime.queue.execute_next()
    assert runtime.scans == [23] * 6 and runtime.native == [(4, 77)]
    assert runtime.accounts.IsHexRemovalClaimOwned(ordinary.claim_token)
    assert handler._hr_accounting_attempts[0].hr_accounting_failed


def test_accounting_suppression_is_bounded_to_owner_slots(urgent_runtime: Any) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    handler._hr_samples_used = _FailingAccountingWrites()
    for slot in (*range(64), 0):
        runtime.hr.owner = replace(runtime.hr.owner, slot=slot)
        runtime.hr.clock[0] += 250
        runtime.hr.publisher = runtime.hr.identity.Publisher()
        assert runtime.publish()
        with pytest.raises(MemoryError):
            urgent_offer(handler)
        handler.cancel_pending("urgent_handler_exception")
    assert len(handler._hr_accounting_attempts) == 64
    assert all(attempt is not None and attempt.hr_accounting_failed for attempt in handler._hr_accounting_attempts)
    assert not urgent_offer(handler)


def test_accounting_guard_does_not_swallow_fatal_exceptions(
    urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    handler = urgent_runtime.handler

    def interrupt(_attempt: Any) -> None:
        raise KeyboardInterrupt("fatal fixture interruption")

    monkeypatch.setattr(handler, "_record_hr_sample", interrupt)
    with pytest.raises(KeyboardInterrupt, match="fatal fixture"):
        urgent_offer(handler)
    guarded = handler._pending_attempt
    handler.cancel_pending("fixture interrupted")
    assert guarded.enqueue_accepted and guarded.hr_accounting_failed
    assert not handler._submission_gate.locked() and not urgent_offer(handler)


def test_late_old_accounting_cannot_regress_a_partially_recorded_successor(urgent_runtime: Any) -> None:
    runtime, handler = urgent_runtime, urgent_runtime.handler
    assert urgent_offer(handler)
    old = handler._pending_attempt
    handler.cancel_pending("owner replacement")
    runtime.hr.clock[0] += 250
    runtime.hr.publisher = runtime.hr.identity.Publisher()
    assert runtime.publish()
    broken = _FailingAccountingWrites()
    broken.update(handler._hr_sample_generations)
    handler._hr_sample_generations = broken
    with pytest.raises(MemoryError):
        urgent_offer(handler)
    successor = handler._pending_attempt
    saved = handler._hr_samples_used[0]
    assert saved.binding == successor.hr_observation.binding != old.hr_observation.binding
    handler._consume_accepted_hr_sample(old)
    assert handler._hr_samples_used[0] == saved and handler._hr_accounting_attempts[0] is successor
    assert successor.hr_accounting_failed and runtime.accounts.IsHexRemovalClaimOwned(successor.claim_token)
    handler.cancel_pending("urgent_handler_exception")
    handler._hr_sample_generations = dict(broken)
    assert not urgent_offer(handler)


@pytest.fixture
def urgent_console(urgent_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    runtime = urgent_runtime
    runtime.console = []
    runtime.console_hook = runtime_stub(lambda _message: None)

    def log(sender: str, message: str, _level: int) -> None:
        assert sender == "SmartShatterHex"
        runtime.console.append(message)
        runtime.console_hook(message)

    system = types.ModuleType("PySystem")
    system.__dict__["Console"] = SimpleNamespace(Log=log, MessageType=SimpleNamespace(Info=1))
    monkeypatch.setitem(sys.modules, "PySystem", system)
    monkeypatch.setattr(SHATTER.time, "monotonic", runtime_stub(lambda: runtime.hr.clock[0] / 1000))
    return runtime


def _console_event(runtime: Any, event: str) -> list[dict[str, str]]:
    return [
        dict(part.split("=", 1) for part in message.split()[1:] if "=" in part)
        for message in runtime.console
        if f" event={event} " in message
    ]


def test_urgent_console_accepted_sample_is_consumed_and_uses_existing_read_age(urgent_console: Any) -> None:
    runtime, handler = urgent_console, urgent_console.handler
    runtime.hr.clock[0] += 100
    assert urgent_offer(handler)
    attempt = handler._pending_attempt
    consumed = handler._hr_samples_used[0]
    (event,) = _console_event(runtime, "action_queued")
    assert event["evidence"] == "hr_owner_vm" and event["sample_stage"] == "accepted_enqueue"
    assert event["sample_seq"] == event["enqueue_seq"] == str(consumed.sequence) == "1"
    assert event["sample_tick_ms"] == str(consumed.sampled_at) == "10000"
    assert event["sample_age_ms"] == "100" and event["age_basis"] == "owner_read"
    assert event["vm_sample_ms"] == "6000.0" and event["vm_aged_ms"] == "5900.0"
    assert event["attempt"] == str(attempt.attempt_generation) and event["id"] == f"d{attempt.diagnostic_id}"
    assert (
        event["owner_bind"]
        == sha256(consumed.owner.digest() + consumed.instance + consumed.incarnation[1]).hexdigest()[:16]
    )
    assert event["pub_nonce"] == consumed.incarnation[1].hex()
    assert event["pub_started_ms"] == str(consumed.incarnation[0])
    assert event["context_gen"] == str(consumed.incarnation[2])
    assert runtime.hr.owner.email not in " ".join(runtime.console)
    assert runtime.hr.owner.character not in " ".join(runtime.console)
    assert attempt.hr_enqueue_observation is consumed and runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)


def test_urgent_console_repeated_opportunities_report_increasing_committed_sequences(urgent_console: Any) -> None:
    runtime, handler = urgent_console, urgent_console.handler
    for sequence in range(1, 4):
        assert urgent_offer(handler)
        assert handler._hr_samples_used[0].sequence == sequence
        handler.cancel_pending("new opportunity")
        assert not urgent_offer(handler)
        runtime.hr.clock[0] += 250
        assert runtime.publish()
    events = _console_event(runtime, "action_queued")
    assert [event["sample_seq"] for event in events] == ["1", "2", "3"]
    assert len({event["owner_bind"] for event in events}) == 1
    assert len({event["attempt"] for event in events}) == 3 and runtime.native == []


@pytest.mark.parametrize("callback_during_logging", [False, True])
def test_urgent_console_freezes_enqueue_sample_when_final_guard_advances(
    urgent_console: Any, callback_during_logging: bool
) -> None:
    runtime, handler = urgent_console, urgent_console.handler

    def finish() -> None:
        runtime.hr.clock[0] += 250
        assert runtime.publish()
        assert runtime.queue.execute_next()

    if callback_during_logging:

        def on_log(message: str) -> None:
            if " event=decision " in message:
                finish()

        runtime.console_hook = on_log
    assert urgent_offer(handler)
    if not callback_during_logging:
        finish()
    (queued,) = _console_event(runtime, "action_queued")
    (native,) = _console_event(runtime, "native_send_attempted")
    assert queued["sample_seq"] == queued["enqueue_seq"] == "1"
    assert native["sample_stage"] == "final_guard" and native["sample_seq"] == "2" and native["enqueue_seq"] == "1"
    assert native["owner_bind"] == queued["owner_bind"] and native["attempt"] == queued["attempt"]
    assert handler._hr_samples_used[0].sequence == 2 and runtime.native == [(4, 77)]


def test_urgent_console_callback_before_enqueue_return_reports_actual_consumed_sample(
    urgent_console: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, handler = urgent_console, urgent_console.handler
    skillbar = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.SkillBar
    enqueue = skillbar.QueueGuardedUseSkill
    errors: list[BaseException] = []

    def finish() -> None:
        try:
            runtime.hr.clock[0] += 250
            assert runtime.publish()
            assert runtime.queue.execute_next()
        except BaseException as error:
            errors.append(error)

    def submit(callback: Any) -> None:
        assert enqueue(callback) is None
        thread = threading.Thread(target=finish)
        thread.start()
        thread.join(5)
        assert not thread.is_alive()

    monkeypatch.setattr(skillbar, "QueueGuardedUseSkill", submit)
    assert urgent_offer(handler) and not errors
    (queued,) = _console_event(runtime, "action_queued")
    (native,) = _console_event(runtime, "native_send_attempted")
    assert queued["sample_seq"] == queued["enqueue_seq"] == str(handler._hr_samples_used[0].sequence) == "2"
    assert native["sample_seq"] == "2" and native["enqueue_seq"] == "pending"
    assert runtime.native == [(4, 77)]


@pytest.mark.parametrize("reason", ["claim", "queue", "missing", "stale", "unauthorized"])
def test_urgent_console_does_not_label_rejected_work_as_accepted(
    urgent_console: Any, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    runtime, handler = urgent_console, urgent_console.handler
    if reason == "claim":
        assert runtime.accounts.TryAcquireHexRemovalTarget("second@example.test", 77, 3400, 5).token is not None
    elif reason == "queue":
        skillbar = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.SkillBar
        monkeypatch.delitem(skillbar._action_queue_manager.queues, "ACTION")
    elif reason == "missing":
        runtime.hr.table.invalidate(runtime.hr.publisher)
    elif reason == "stale":
        runtime.hr.clock[0] += 750
    else:
        shmem = SHATTER._test_runtime_modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem
        monkeypatch.setattr(shmem, "ReadHrHexObservation", variadic_stub(lambda *_: None))
    assert not urgent_offer(handler)
    assert _console_event(runtime, "action_queued") == _console_event(runtime, "native_send_attempted") == []
    if reason == "queue":
        assert _console_event(runtime, "claim_attempt"), "claim acquisition alone is not queue acceptance"
    assert runtime.native == [] and runtime.queue.is_empty()


def test_ordinary_console_event_meanings_are_unchanged(urgent_console: Any) -> None:
    runtime, handler = urgent_console, urgent_console.handler
    handler._build_snapshot = variadic_stub(lambda *_args, **_kwargs: ((_ally(77),), ()))
    assert _generator_result(handler.try_cast())
    assert runtime.queue.execute_next()
    (queued,) = _console_event(runtime, "action_queued")
    (native,) = _console_event(runtime, "native_send_attempted")
    assert queued["evidence"] == "legacy_merged"
    assert "sample_seq" not in queued and "sample_seq" not in native and "evidence" not in native
    assert runtime.native == [(4, 77)]


@pytest.mark.parametrize("failure", [RuntimeError, MemoryError])
@pytest.mark.parametrize("where", ["format", "console"])
def test_urgent_console_failure_cannot_change_acceptance_native_or_lease(
    urgent_console: Any, monkeypatch: pytest.MonkeyPatch, failure: type[Exception], where: str
) -> None:
    runtime, handler = urgent_console, urgent_console.handler
    faults: list[str] = []

    def fail_format(attempt: Any, *, at_enqueue: bool) -> str:
        assert attempt.enqueue_accepted and handler._hr_samples_used[0].sequence == 1
        faults.append("enqueue" if at_enqueue else "native")
        raise failure("consumer formatting failed")

    def fail_console(message: str) -> None:
        faults.append(message)
        raise failure("consumer console failed")

    if where == "format":
        monkeypatch.setattr(handler, "_live_hr_evidence", fail_format)
    else:
        runtime.console_hook = fail_console
    assert urgent_offer(handler)
    attempt = handler._pending_attempt
    assert attempt.enqueue_accepted and attempt.hr_accounting_complete and not attempt.hr_accounting_failed
    assert runtime.accounts.IsHexRemovalClaimOwned(attempt.claim_token)
    assert runtime.queue.execute_next()
    token = attempt.claim_token
    handler.cancel_pending("clear sent local state")
    assert faults and runtime.native == [(4, 77)] and runtime.accounts.IsHexRemovalClaimOwned(token)
    assert not urgent_offer(handler) and handler._hr_samples_used[0].sequence == 1


def test_urgent_console_never_runs_between_acceptance_and_failed_accounting(urgent_console: Any) -> None:
    runtime, handler = urgent_console, urgent_console.handler
    handler._hr_samples_used = _FailingAccountingWrites()
    with pytest.raises(MemoryError):
        urgent_offer(handler)
    attempt = handler._pending_attempt
    assert attempt.enqueue_accepted and attempt.hr_accounting_failed and attempt.hr_enqueue_observation is None
    assert runtime.console == [], "new formatting/output must follow irreversible accounting"
    handler.cancel_pending("urgent_handler_exception")
    handler._hr_samples_used = {}
    assert not urgent_offer(handler)
    runtime.hr.clock[0] += 250
    assert runtime.publish()
    assert not urgent_offer(handler) and runtime.native == []


def test_urgent_console_adds_no_effect_authorization_or_claim_operations(
    production_cost_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, handler = production_cost_runtime, production_cost_runtime.handler
    core = SHATTER._test_runtime_modules["Py4GWCoreLib"]
    read = core.GLOBAL_CACHE.ShMem.ReadHrHexObservation
    reads: list[int] = []
    logs: list[str] = []
    locks = sys.modules["_hr_claim_fixture"].ALL_ACCOUNTS_MODULE
    acquired: list[bool] = []
    owner_acquired: list[bool] = []
    operations: list[str] = []

    def counted(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            operations.append(name)
            return function(*args, **kwargs)

        return call

    claims = sys.modules["Py4GWCoreLib.GlobalCache.WhiteboardLocks"]
    for name in ("try_acquire_hex_removal_claim", "renew_hex_removal_claim", "release_hex_removal_claim"):
        monkeypatch.setattr(claims, name, counted(name, getattr(claims, name)))
    monkeypatch.setattr(
        core.GLOBAL_CACHE.SkillBar,
        "QueueGuardedUseSkill",
        counted("enqueue", core.GLOBAL_CACHE.SkillBar.QueueGuardedUseSkill),
    )

    def read_owner(*args: Any) -> Any:
        reads.append(1)
        return read(*args)

    def log(_sender: str, message: str, _level: int) -> None:
        def inspect() -> None:
            with locks.intent_table_lock(locks.SHMEM_SHARED_MEMORY_FILE_NAME, timeout_ms=0) as owned:
                acquired.append(owned)
            with runtime.hr.sync.intent_table_lock(runtime.hr.module.TABLE_NAME, timeout_ms=0) as owner_owned:
                owner_acquired.append(owner_owned)

        thread = threading.Thread(target=inspect)
        thread.start()
        thread.join(5)
        assert not thread.is_alive()
        logs.append(message)

    system = types.ModuleType("PySystem")
    system.__dict__["Console"] = SimpleNamespace(Log=log, MessageType=SimpleNamespace(Info=1))
    monkeypatch.setitem(sys.modules, "PySystem", system)
    monkeypatch.setattr(core.GLOBAL_CACHE.ShMem, "ReadHrHexObservation", read_owner)
    assert urgent_offer(handler)
    assert len(reads) == len(runtime.queries) == 3 and runtime.scans == [23] * 4
    assert runtime.queue.execute_next()
    assert len(reads) == len(runtime.queries) == 5 and runtime.scans == [23] * 6
    assert runtime.native == [(4, 77)] and acquired == [True] * len(logs)
    assert owner_acquired == acquired
    assert operations == ["try_acquire_hex_removal_claim", "enqueue", "renew_hex_removal_claim"]
    assert sum(" event=action_queued " in message for message in logs) == 1
    assert sum(" event=native_send_attempted " in message for message in logs) == 1
