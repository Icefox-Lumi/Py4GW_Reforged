# pyright: reportMissingImports=false
"""Deterministic offline regressions for Smart Shatter Hex policy and dispatch."""

from __future__ import annotations

import ast
import importlib.util
import sys
import types
from dataclasses import replace
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

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
    sys.modules.update(stub_modules)
    try:
        source_path = Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "Builds" / "Skills" / "SmartShatterHex.py"
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
    handler._build_snapshot = lambda _parameters: ((_ally(1), _ally(2)), ())
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
    handler._build_snapshot = lambda _parameters: ((_ally(77),), ())
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
    handler._build_snapshot = lambda _parameters, *, selected_agent_id: (
        (replace(ally, agent_id=selected_agent_id),),
        enemies,
    )

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
    handler._build_snapshot = lambda _parameters, *, selected_agent_id: ((_ally(selected_agent_id),), ())

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


def test_reset_action_queue_then_claim_expiry_recovers_and_invalidates_stale_callback(
    monkeypatch: pytest.MonkeyPatch,
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
    handler._build_snapshot = lambda _parameters, *, selected_agent_id=None: (
        (_ally(77 if selected_agent_id is None else selected_agent_id),),
        (),
    )
    handler._read_lifecycle_inputs = lambda: lifecycle
    guard_results: list[bool] = []
    execute_guard = handler._execute_queued_guard

    def observe_guard(attempt: Any, native_use: Any) -> bool:
        result = execute_guard(attempt, native_use)
        guard_results.append(result)
        return result

    handler._execute_queued_guard = observe_guard

    assert _generator_result(handler.try_cast()) is True
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
