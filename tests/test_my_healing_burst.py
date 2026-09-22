"""Focused offline tests for the HBS-local emergency-healing policy."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_MISSING = object()


def _load_hbs_module() -> types.ModuleType:
    """Load the build with minimal runtime stubs for pure policy helpers."""
    module_name = "_hbs_policy_test_subject"

    class _BuildMgr:
        pass

    class _Skill:
        _ids: dict[str, int] = {}

        @classmethod
        def GetID(cls, name: str) -> int:
            if name not in cls._ids:
                cls._ids[name] = len(cls._ids) + 1
            return cls._ids[name]

    class _HeroAI_Build:
        pass

    class _SkillsTemplate:
        pass

    class _WhiteboardLockKind:
        RESURRECT_TARGET = 1

    class _Globals:
        SHMEM_AGENT_FAST_UPDATE_THROTTLE_MS = 37
        SHMEM_AGENT_MEDIUM_UPDATE_THROTTLE_MS = 86

    stub_modules: dict[str, types.ModuleType] = {}

    def add_module(name: str, **attributes: Any) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        stub_modules[name] = module
        return module

    corelib = add_module(
        "Py4GWCoreLib",
        GLOBAL_CACHE=SimpleNamespace(),
        Agent=SimpleNamespace(),
        BuildMgr=_BuildMgr,
        Map=SimpleNamespace(),
        Player=SimpleNamespace(),
        Profession=SimpleNamespace(Monk=1),
        Range=SimpleNamespace(),
        Routines=SimpleNamespace(),
        SkillBar=SimpleNamespace(),
        Utils=SimpleNamespace(),
    )
    corelib.__path__ = []
    add_module("Py4GWCoreLib.Builds").__path__ = []
    add_module("Py4GWCoreLib.Builds.Any").__path__ = []
    add_module("Py4GWCoreLib.Builds.Monk").__path__ = []
    add_module(
        "Py4GWCoreLib.Builds.Any.HeroAI",
        HeroAI_Build=_HeroAI_Build,
    )
    add_module(
        "Py4GWCoreLib.Builds.Skills",
        HexRemovalPriority=SimpleNamespace(HIGH=1, LOW=2),
        SkillsTemplate=_SkillsTemplate,
    )
    add_module("Py4GWCoreLib.Skill", Skill=_Skill)
    add_module(
        "Py4GWCoreLib.enums_src",
    ).__path__ = []
    add_module(
        "Py4GWCoreLib.enums_src.GameData_enums",
        Attribute=SimpleNamespace(
            HealingPrayers=1,
            DivineFavor=2,
            ProtectionPrayers=3,
        ),
    )
    add_module(
        "Py4GWCoreLib.enums_src.Whiteboard_enums",
        WhiteboardLockKind=_WhiteboardLockKind,
    )
    add_module("Py4GWCoreLib.GlobalCache").__path__ = []
    add_module(
        "Py4GWCoreLib.GlobalCache.shared_memory_src",
        Globals=_Globals,
    ).__path__ = []
    add_module(
        "Py4GWCoreLib.GlobalCache.WhiteboardLocks",
        claim_resurrection_target=lambda *args, **kwargs: 0,
    )
    add_module(
        "PySystem",
        get_tick_count64=lambda: 0,
        Console=SimpleNamespace(
            Log=lambda *args, **kwargs: None,
            MessageType=SimpleNamespace(Info=1),
        ),
    )

    original_modules = {name: sys.modules.get(name, _MISSING) for name in stub_modules}
    original_modules["PySystem"] = sys.modules.get("PySystem", _MISSING)
    sys.modules.update(stub_modules)
    try:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "Py4GWCoreLib"
            / "Builds"
            / "Monk"
            / "Mo_Any"
            / "My Healing Burst.py"
        )
        spec = importlib.util.spec_from_file_location(module_name, source_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load {source_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        for name, original in original_modules.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                assert isinstance(original, types.ModuleType)
                sys.modules[name] = original


HBS = _load_hbs_module()


def _member(
    agent_id: int,
    *,
    health: float,
    recent_drop: float = 0.0,
    critical: bool | None = None,
    pressure: bool | None = None,
    self_member: bool = False,
    falling: bool = False,
) -> Any:
    return HBS._PartyMemberSnapshot(
        agent_id=agent_id,
        party_order=agent_id,
        is_self=self_member,
        valid=True,
        alive=True,
        health=health,
        maximum_health=1000.0,
        missing_hp=1000.0 * (1.0 - health),
        position=(0.0, 0.0),
        distance_from_player=100.0,
        recent_health_drop=recent_drop,
        health_is_falling=falling,
        is_critical=(health <= HBS.COMBAT_CRITICAL_HEALTH_THRESHOLD)
        if critical is None
        else critical,
        is_pressure_target=(recent_drop >= HBS.COMBAT_PRESSURE_DROP_THRESHOLD)
        if pressure is None
        else pressure,
        is_aegis_spike_target=recent_drop >= HBS.AEGIS_PRESSURE_DROP_THRESHOLD,
        is_injured=health < 1.0,
        is_martial=False,
        is_melee=False,
        is_attacking=False,
        is_casting=False,
    )


def _candidate(
    agent_id: int,
    *,
    health: float,
    recent_drop: float,
    urgency: Any,
    primary: float = 0.5,
    evaluator_order: int = 0,
) -> Any:
    return HBS._CombatActionCandidate(
        skill_id=agent_id,
        target_agent_id=agent_id,
        urgency=urgency,
        primary_value=primary,
        secondary_value=0.0,
        time_to_primary_effect=1.0,
        energy_spend_fraction=0.1,
        evaluator_order=evaluator_order,
        target_order=agent_id,
        preempts_high_cure=False,
        revalidate=lambda: True,
        execute=lambda: True,
        diagnostic_reason="test",
        target_health=health,
        target_recent_health_drop=recent_drop,
    )


def _context(
    *members: Any,
    critical_ids: tuple[int, ...] = (),
    pressure_ids: tuple[int, ...] = (),
    enemies: int = 0,
):
    return SimpleNamespace(
        party_members=members,
        party_by_id={member.agent_id: member for member in members},
        critical_ids=critical_ids,
        pressure_ids=pressure_ids,
        nearby_enemy_count=enemies,
    )


def _subject_with_fresh_policy(
    fresh_context: Any,
    emergency_ids: frozenset[int] | None = None,
) -> Any:
    subject = object.__new__(HBS.My_Healing_Burst)
    if emergency_ids is None:
        emergency_ids = HBS.My_Healing_Burst._patient_party_emergency_ids(
            fresh_context
        )
    subject._fresh_policy_context = lambda _context: (
        fresh_context,
        emergency_ids,
    )
    subject._revalidate_party_target = lambda *args, **kwargs: True
    return subject


def _combat_context(
    member: Any,
    *,
    critical_ids: tuple[int, ...] = (),
    pressure_ids: tuple[int, ...] = (),
    nearby_enemy_count: int = 0,
) -> Any:
    missing_hp = member.missing_hp
    return HBS._CombatContext(
        tick_ms=300,
        player_id=99,
        player_position=(0.0, 0.0),
        party_members=(member,),
        party_by_id={member.agent_id: member},
        critical_ids=critical_ids,
        pressure_ids=pressure_ids,
        aegis_actionable_ids=(),
        injured_ids=(member.agent_id,) if member.is_injured else (),
        critical_missing_hp=missing_hp if member.agent_id in critical_ids else 0.0,
        pressure_missing_hp=missing_hp if member.agent_id in pressure_ids else 0.0,
        injured_missing_hp=missing_hp if member.is_injured else 0.0,
        healing_prayers_rank=15,
        divine_favor_rank=15,
        protection_prayers_rank=15,
        current_energy=100.0,
        maximum_energy=100.0,
        skill_states={
            HBS.PATIENT_SPIRIT_ID: HBS._SkillSnapshot(
                skill_id=HBS.PATIENT_SPIRIT_ID,
                equipped=True,
                castable=True,
                energy_cost=5.0,
                activation_seconds=0.25,
                scale_0=400.0,
                scale_15=400.0,
            ),
            HBS.SEED_OF_LIFE_ID: HBS._SkillSnapshot(
                skill_id=HBS.SEED_OF_LIFE_ID,
                equipped=True,
                castable=True,
                energy_cost=5.0,
                activation_seconds=0.25,
            ),
        },
        specialized_spike_candidates=(),
        nearby_enemy_count=nearby_enemy_count,
        nearby_martial_enemy_count=0,
        nearby_attacking_martial_enemy_count=0,
        party_player_ids=frozenset(),
    )


def _configure_actual_runtime(
    monkeypatch: Any,
    state: dict[str, Any],
) -> Any:
    subject = object.__new__(HBS.My_Healing_Burst)
    subject._diagnostic_episodes = {}
    subject._health_trend_history = {}
    subject.UpdatePartyHealthMonitor = lambda **_kwargs: {
        1: {
            "health": float(state["health"]),
            "drop": float(state["drop"]),
            "sample_ms": int(state["tick"]),
        }
    }
    subject._get_actual_party_ids = lambda: [1]
    subject._get_current_party_player_ids = lambda: set()
    subject._is_castable = lambda _skill_id: True
    subject.GetCustomSkill = lambda _skill_id: None
    subject._diagnostic_target_ids = lambda _context: ()
    subject._diagnostic_record_skill_state_rejection = lambda *_args, **_kwargs: False
    subject._context_distance = lambda *_args, **_kwargs: 0.0
    subject._diagnostic_effect_rejection = lambda *_args, **_kwargs: ""
    subject._has_verified_effect_absence = lambda *_args, **_kwargs: True
    subject._has_effect_cached = lambda *_args, **_kwargs: False

    monkeypatch.setattr(
        HBS.PySystem,
        "get_tick_count64",
        lambda: int(state["tick"]),
    )
    monkeypatch.setattr(
        HBS.Agent,
        "IsValid",
        lambda agent_id: int(agent_id) in {1, 99},
        raising=False,
    )
    monkeypatch.setattr(
        HBS.Agent,
        "GetMaxHealth",
        lambda _agent_id: 1000.0,
        raising=False,
    )
    monkeypatch.setattr(
        HBS.Agent,
        "GetXY",
        lambda _agent_id: (0.0, 0.0),
        raising=False,
    )
    monkeypatch.setattr(HBS.Player, "GetXY", lambda: (0.0, 0.0), raising=False)
    monkeypatch.setattr(
        HBS.Range,
        "Spellcast",
        SimpleNamespace(value=1000.0),
        raising=False,
    )
    monkeypatch.setattr(
        HBS.Range,
        "Earshot",
        SimpleNamespace(value=1000.0),
        raising=False,
    )
    monkeypatch.setattr(HBS.Utils, "Distance", lambda *_args: 0.0, raising=False)

    def current_health(agent_id: int) -> float:
        return float(state["health"]) if agent_id == 1 else 1.0

    checks = SimpleNamespace(
        Agents=SimpleNamespace(
            IsAlive=lambda _agent_id: True,
            GetHealth=current_health,
        ),
        Effects=SimpleNamespace(HasEffect=lambda *_args: False),
    )
    monkeypatch.setattr(HBS.Routines, "Checks", checks, raising=False)
    monkeypatch.setattr(
        HBS.Routines,
        "Party",
        SimpleNamespace(IsPartyMember=lambda agent_id: agent_id == 1),
        raising=False,
    )

    def get_filtered_enemies(*_args: Any) -> list[int]:
        state["enemy_queries"] = int(state.get("enemy_queries", 0)) + 1
        return list(state.get("enemy_ids", []))

    monkeypatch.setattr(
        HBS.Routines,
        "Agents",
        SimpleNamespace(GetFilteredEnemyArray=get_filtered_enemies),
        raising=False,
    )
    monkeypatch.setattr(
        HBS.GLOBAL_CACHE,
        "Effects",
        SimpleNamespace(HasEffect=lambda *_args: False),
        raising=False,
    )
    return subject


def _actual_seed_candidate(
    monkeypatch: Any,
    *,
    health: float,
    recent_drop: float,
    falling: bool,
    nearby_enemy_count: int,
    enemy_ids: list[int],
    history: tuple[tuple[int, float], ...],
) -> tuple[dict[str, Any], Any, Any, Any]:
    state: dict[str, Any] = {
        "tick": 400,
        "health": health,
        "drop": recent_drop,
        "enemy_ids": enemy_ids,
        "enemy_queries": 0,
    }
    subject = _configure_actual_runtime(monkeypatch, state)
    for tick_ms, sample_health in history:
        subject._record_health_trend_sample(1, tick_ms, sample_health)
    member = _member(
        1,
        health=health,
        recent_drop=recent_drop,
        falling=falling,
    )
    context = _combat_context(
        member,
        pressure_ids=(1,) if recent_drop >= HBS.COMBAT_PRESSURE_DROP_THRESHOLD else (),
        nearby_enemy_count=nearby_enemy_count,
    )
    candidates = subject._evaluate_seed_of_life(context, 0)
    assert len(candidates) == 1
    return state, subject, context, candidates[0]


def _actual_patient_candidate(
    monkeypatch: Any,
) -> tuple[dict[str, Any], Any, Any, Any]:
    state: dict[str, Any] = {
        "tick": 400,
        "health": 0.60,
        "drop": 0.0,
        "enemy_ids": [],
        "enemy_queries": 0,
    }
    subject = _configure_actual_runtime(monkeypatch, state)
    member = _member(1, health=0.60, recent_drop=0.0)
    context = _combat_context(member)
    candidates = subject._evaluate_patient_spirit(context, 0)
    assert len(candidates) == 1
    return state, subject, context, candidates[0]


def test_survival_first_arbitration_beats_healthier_recent_pressure_target():
    current_injury = _candidate(
        1,
        health=0.556,
        recent_drop=0.0,
        urgency=HBS._CombatUrgency.CURRENT_INJURY,
    )
    healthier_pressure = _candidate(
        2,
        health=0.785,
        recent_drop=0.215,
        urgency=HBS._CombatUrgency.URGENT_REACTIVE,
    )

    selected = HBS.My_Healing_Burst._select_candidate(
        [current_injury, healthier_pressure]
    )

    assert selected is current_injury


def test_pressure_can_outweigh_a_small_health_difference():
    stable_target = _candidate(
        1,
        health=0.60,
        recent_drop=0.0,
        urgency=HBS._CombatUrgency.CURRENT_INJURY,
    )
    collapsing_target = _candidate(
        2,
        health=0.70,
        recent_drop=0.40,
        urgency=HBS._CombatUrgency.URGENT_REACTIVE,
    )

    selected = HBS.My_Healing_Burst._select_candidate(
        [stable_target, collapsing_target]
    )

    assert selected is collapsing_target


def test_rapidly_collapsing_65_percent_target_beats_stable_55_percent_target():
    stable_target = _candidate(
        1,
        health=0.55,
        recent_drop=0.0,
        urgency=HBS._CombatUrgency.CURRENT_INJURY,
    )
    collapsing_target = _candidate(
        2,
        health=0.65,
        recent_drop=0.25,
        urgency=HBS._CombatUrgency.URGENT_REACTIVE,
    )

    assert (
        HBS.My_Healing_Burst._select_candidate([stable_target, collapsing_target])
        is collapsing_target
    )


def test_true_critical_still_dominates_noncritical_pressure():
    critical = _candidate(
        1,
        health=0.34,
        recent_drop=0.0,
        urgency=HBS._CombatUrgency.CURRENT_INJURY,
    )
    pressure = _candidate(
        2,
        health=0.50,
        recent_drop=0.40,
        urgency=HBS._CombatUrgency.URGENT_REACTIVE,
    )

    assert HBS.My_Healing_Burst._select_candidate([pressure, critical]) is critical


def test_candidate_ties_remain_deterministic():
    first = _candidate(
        1,
        health=0.60,
        recent_drop=0.10,
        urgency=HBS._CombatUrgency.CURRENT_INJURY,
        evaluator_order=1,
    )
    second = _candidate(
        2,
        health=0.60,
        recent_drop=0.10,
        urgency=HBS._CombatUrgency.CURRENT_INJURY,
        evaluator_order=1,
    )

    assert HBS.My_Healing_Burst._select_candidate([second, first]) is first


def test_patient_accepts_safe_gradual_injury():
    target = _member(1, health=0.60, recent_drop=0.04, falling=True)

    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(
            _context(target),
            target,
            delayed_heal_hp=100.0,
        )
        == ""
    )


def test_patient_local_gate_accepts_moderate_injury_and_rejects_trivial_loss():
    for health in (0.72, 0.78, 0.80):
        target = _member(1, health=health, recent_drop=0.0)
        assert (
            HBS.My_Healing_Burst._patient_safety_rejection(
                _context(target),
                target,
                delayed_heal_hp=100.0,
            )
            == ""
        )

    nearly_full = _member(1, health=0.92, recent_drop=0.0)
    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(
            _context(nearly_full),
            nearly_full,
            delayed_heal_hp=100.0,
        )
        == "health_threshold"
    )

    large_delayed_heal = _member(1, health=0.84, recent_drop=0.0)
    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(
            _context(large_delayed_heal),
            large_delayed_heal,
            delayed_heal_hp=400.0,
        )
        == "trivial_missing_health"
    )


def test_patient_log6_pressure_does_not_create_party_emergency():
    target = _member(49, health=0.799, recent_drop=0.0)
    remote_pressure = _member(47, health=0.901, recent_drop=0.099)
    monk_pressure = _member(50, health=0.851, recent_drop=0.092, self_member=True)

    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(
            _context(target, remote_pressure, monk_pressure),
            target,
            delayed_heal_hp=120.0,
        )
        == ""
    )


def test_patient_rejects_rapid_drop_and_true_party_emergency():
    target = _member(1, health=0.60, recent_drop=0.12, falling=True)
    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(_context(target), target)
        == "rapid_drop"
    )

    emergency = _member(2, health=0.30, recent_drop=0.0)
    safe_target = _member(1, health=0.60, recent_drop=0.04, falling=True)
    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(
            _context(safe_target, emergency, critical_ids=(2,)),
            safe_target,
        )
        == "party_emergency"
    )


def test_patient_rejects_low_health_member_with_continuing_pressure():
    target = _member(1, health=0.60, recent_drop=0.0)
    pressured_danger = _member(
        2,
        health=0.44,
        recent_drop=0.12,
        falling=True,
    )

    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(
            _context(target, pressured_danger),
            target,
            delayed_heal_hp=120.0,
        )
        == "party_emergency"
    )


def test_patient_healthy_pressure_member_is_not_a_shared_blocker():
    target = _member(1, health=0.60, recent_drop=0.0)
    healthy_pressure = _member(2, health=0.90, recent_drop=0.12, falling=False)

    assert (
        HBS.My_Healing_Burst._patient_party_blocker_reason(healthy_pressure)
        == ""
    )
    assert (
        HBS.My_Healing_Burst._patient_safety_rejection(
            _context(target, healthy_pressure),
            target,
            delayed_heal_hp=120.0,
        )
        == ""
    )


def test_seed_requires_a_continuing_meaningful_spike():
    one_off = _member(1, health=0.60, recent_drop=0.08)
    assert (
        HBS.My_Healing_Burst._seed_spike_rejection(
            _context(one_off, pressure_ids=(1,)), one_off
        )
        == "insufficient_pressure"
    )

    isolated_spike = _member(1, health=0.60, recent_drop=0.12)
    assert (
        HBS.My_Healing_Burst._seed_spike_rejection(
            _context(isolated_spike, pressure_ids=(1,), enemies=1),
            isolated_spike,
        )
        == "spike_not_continuing"
    )

    continuing_spike = _member(1, health=0.60, recent_drop=0.12, falling=True)
    assert (
        HBS.My_Healing_Burst._seed_spike_rejection(
            _context(continuing_spike, pressure_ids=(1,), enemies=1),
            continuing_spike,
        )
        == ""
    )


def test_seed_trend_requires_two_declines_but_allows_a_large_active_spike():
    subject = object.__new__(HBS.My_Healing_Burst)
    subject._health_trend_history = {}
    assert not subject._record_health_trend_sample(1, 100, 0.85)
    assert not subject._record_health_trend_sample(1, 200, 0.70)
    assert not subject._record_health_trend_sample(1, 300, 0.70)

    stable_after_one_hit = _member(1, health=0.70, recent_drop=0.15)
    assert (
        HBS.My_Healing_Burst._seed_spike_rejection(
            _context(stable_after_one_hit, pressure_ids=(1,)),
            stable_after_one_hit,
        )
        == "spike_not_continuing"
    )

    subject._health_trend_history = {}
    assert not subject._record_health_trend_sample(1, 100, 0.80)
    assert not subject._record_health_trend_sample(1, 200, 0.68)
    assert subject._record_health_trend_sample(1, 300, 0.58)
    continuing_spike = _member(
        1,
        health=0.58,
        recent_drop=0.12,
        falling=True,
    )
    assert (
        HBS.My_Healing_Burst._seed_spike_rejection(
            _context(continuing_spike, pressure_ids=(1,), enemies=1),
            continuing_spike,
        )
        == ""
    )

    large_single_spike = _member(1, health=0.50, recent_drop=0.22)
    assert (
        HBS.My_Healing_Burst._seed_spike_rejection(
            _context(large_single_spike, pressure_ids=(1,), enemies=1),
            large_single_spike,
        )
        == ""
    )


def test_seed_never_delays_a_true_critical_target():
    critical = _member(1, health=0.34, recent_drop=0.30, falling=True)

    assert (
        HBS.My_Healing_Burst._seed_spike_rejection(
            _context(critical, pressure_ids=(1,), enemies=1), critical
        )
        == "critical_direct_rescue"
    )


def test_patient_final_revalidation_refreshes_policy_before_final_gate():
    initial_target = _member(1, health=0.60, recent_drop=0.04)
    fresh_target = _member(1, health=0.80, recent_drop=0.0)
    context = _context(initial_target)
    fresh_context = _context(fresh_target)
    subject = _subject_with_fresh_policy(fresh_context)
    observed_contexts: list[Any] = []
    subject._revalidate_party_target = lambda candidate_context, *args, **kwargs: (
        observed_contexts.append(candidate_context) or True
    )

    assert (
        HBS.My_Healing_Burst._revalidate_patient_candidate(subject, context, 1)
        is True
    )
    assert observed_contexts == [fresh_context]


def test_patient_final_revalidation_rejects_new_critical_rapid_or_party_emergency():
    initial_target = _member(1, health=0.60, recent_drop=0.04)
    context = _context(initial_target)

    critical_target = _member(1, health=0.34, recent_drop=0.20)
    critical_context = _context(critical_target)
    critical_subject = _subject_with_fresh_policy(critical_context)
    assert not HBS.My_Healing_Burst._revalidate_patient_candidate(
        critical_subject,
        context,
        1,
    )

    rapidly_dropping_target = _member(1, health=0.60, recent_drop=0.12)
    rapid_context = _context(rapidly_dropping_target)
    rapid_subject = _subject_with_fresh_policy(rapid_context)
    assert not HBS.My_Healing_Burst._revalidate_patient_candidate(
        rapid_subject,
        context,
        1,
    )

    emergency_target = _member(1, health=0.80, recent_drop=0.0)
    emergency_member = _member(2, health=0.30, recent_drop=0.0)
    emergency_context = _context(
        emergency_target,
        emergency_member,
    )
    emergency_subject = _subject_with_fresh_policy(emergency_context)
    assert not HBS.My_Healing_Burst._revalidate_patient_candidate(
        emergency_subject,
        context,
        1,
    )

    healthy_pressure_target = _member(1, health=0.80, recent_drop=0.0)
    healthy_pressure_member = _member(2, health=0.90, recent_drop=0.12)
    healthy_pressure_context = _context(
        healthy_pressure_target,
        healthy_pressure_member,
    )
    healthy_pressure_subject = _subject_with_fresh_policy(
        healthy_pressure_context,
    )
    assert HBS.My_Healing_Burst._revalidate_patient_candidate(
        healthy_pressure_subject,
        context,
        1,
    )

    continuing_pressure_target = _member(1, health=0.80, recent_drop=0.0)
    continuing_pressure_member = _member(
        2,
        health=0.44,
        recent_drop=0.12,
        falling=True,
    )
    continuing_pressure_context = _context(
        continuing_pressure_target,
        continuing_pressure_member,
    )
    continuing_pressure_subject = _subject_with_fresh_policy(
        continuing_pressure_context,
    )
    assert not HBS.My_Healing_Burst._revalidate_patient_candidate(
        continuing_pressure_subject,
        context,
        1,
    )


def test_seed_final_revalidation_repeats_current_spike_policy():
    initial_target = _member(1, health=0.60, recent_drop=0.12, falling=True)
    context = _context(initial_target)

    critical_target = _member(
        1,
        health=0.34,
        recent_drop=0.30,
        falling=True,
    )
    critical_context = _context(
        critical_target,
        critical_ids=(1,),
        pressure_ids=(1,),
        enemies=1,
    )
    critical_subject = _subject_with_fresh_policy(critical_context)
    assert not HBS.My_Healing_Burst._revalidate_seed_candidate(
        critical_subject,
        context,
        1,
    )

    single_hit_target = _member(1, health=0.58, recent_drop=0.12)
    single_hit_context = _context(
        single_hit_target,
        pressure_ids=(1,),
        enemies=1,
    )
    single_hit_subject = _subject_with_fresh_policy(single_hit_context)
    assert not HBS.My_Healing_Burst._revalidate_seed_candidate(
        single_hit_subject,
        context,
        1,
    )

    continuing_target = _member(
        1,
        health=0.58,
        recent_drop=0.12,
        falling=True,
    )
    continuing_context = _context(
        continuing_target,
        pressure_ids=(1,),
        enemies=1,
    )
    continuing_subject = _subject_with_fresh_policy(continuing_context)
    assert HBS.My_Healing_Burst._revalidate_seed_candidate(
        continuing_subject,
        context,
        1,
    )


def test_actual_seed_revalidation_keeps_unchanged_later_tick_trend(monkeypatch):
    state, subject, _context_value, candidate = _actual_seed_candidate(
        monkeypatch,
        health=0.58,
        recent_drop=0.12,
        falling=True,
        nearby_enemy_count=0,
        enemy_ids=[],
        history=((100, 0.80), (200, 0.68), (300, 0.58)),
    )

    original_history = subject._health_trend_history[1]
    state["tick"] = 450

    assert candidate.revalidate()
    assert subject._health_trend_history[1] == original_history


def test_actual_seed_revalidation_rejects_recovery(monkeypatch):
    state, subject, _context_value, candidate = _actual_seed_candidate(
        monkeypatch,
        health=0.58,
        recent_drop=0.12,
        falling=True,
        nearby_enemy_count=1,
        enemy_ids=[55],
        history=((100, 0.80), (200, 0.68), (300, 0.58)),
    )

    state["health"] = 0.70
    state["drop"] = 0.22
    state["tick"] = 450

    assert not candidate.revalidate()


def test_actual_seed_revalidation_keeps_a_continued_decline_valid(monkeypatch):
    state, _subject, _context_value, candidate = _actual_seed_candidate(
        monkeypatch,
        health=0.58,
        recent_drop=0.12,
        falling=True,
        nearby_enemy_count=0,
        enemy_ids=[],
        history=((100, 0.80), (200, 0.68), (300, 0.58)),
    )

    state["health"] = 0.49
    state["drop"] = 0.12
    state["tick"] = 450

    assert candidate.revalidate()


def test_actual_seed_revalidation_rejects_critical_transition(monkeypatch):
    state, _subject, _context_value, candidate = _actual_seed_candidate(
        monkeypatch,
        health=0.58,
        recent_drop=0.12,
        falling=True,
        nearby_enemy_count=0,
        enemy_ids=[],
        history=((100, 0.80), (200, 0.68), (300, 0.58)),
    )

    state["health"] = 0.34
    state["drop"] = 0.30
    state["tick"] = 450

    assert not candidate.revalidate()


def test_actual_seed_revalidation_refreshes_large_spike_enemy_pressure(monkeypatch):
    state, _subject, _context_value, candidate = _actual_seed_candidate(
        monkeypatch,
        health=0.50,
        recent_drop=0.22,
        falling=False,
        nearby_enemy_count=1,
        enemy_ids=[55],
        history=((300, 0.50),),
    )
    assert candidate.target_agent_id == 1

    state["enemy_ids"] = []
    state["tick"] = 450

    assert not candidate.revalidate()
    assert state["enemy_queries"] == 1


def test_actual_patient_revalidation_reuses_delayed_heal_usefulness_gate(
    monkeypatch,
):
    state, _subject, _context_value, candidate = _actual_patient_candidate(monkeypatch)
    assert candidate.target_agent_id == 1

    state["health"] = 0.84
    state["tick"] = 450

    assert not candidate.revalidate()


def test_diagnostic_rejection_format_keeps_skill_and_reason_visible():
    context = SimpleNamespace(
        diagnostic_rejections={
            1: {
                HBS.HEALING_BURST_ID: ["recharge"],
                HBS.PATIENT_SPIRIT_ID: ["effect_state_stale", "rapid_drop"],
            }
        }
    )
    subject = object.__new__(HBS.My_Healing_Burst)
    subject._diagnostic_skill_label = lambda skill_id: {
        HBS.HEALING_BURST_ID: "Healing_Burst",
        HBS.PATIENT_SPIRIT_ID: "Patient_Spirit",
    }.get(skill_id, str(skill_id))

    label = HBS.My_Healing_Burst._diagnostic_rejection_label(subject, context, 1)

    assert (
        label == "Healing_Burst[recharge];Patient_Spirit[effect_state_stale,rapid_drop]"
    )


def test_diagnostic_castability_reasons_distinguish_known_gates():
    skill_id = HBS.HEALING_BURST_ID
    ready = True
    enough_energy = True
    pending = False
    HBS.Player.GetAgentID = lambda: 1
    HBS.SkillBar.GetSlotBySkillID = lambda _skill_id: 1
    HBS.Routines.Checks = SimpleNamespace(
        Map=SimpleNamespace(IsExplorable=lambda: True),
        Skills=SimpleNamespace(
            HasEnoughEnergy=lambda _agent_id, _skill_id: enough_energy,
            IsSkillIDReady=lambda _skill_id: ready,
            HasEnoughAdrenalineBySlot=lambda _slot: True,
        ),
    )
    subject = object.__new__(HBS.My_Healing_Burst)
    subject._is_local_cast_pending = lambda: pending
    subject.IsSharedSkillToggleEnabled = lambda _slot: True
    subject._meets_custom_skill_weapon_requirement = lambda _skill_id: True
    subject._meets_custom_skill_shared_conditions = lambda _skill_id: True
    subject.SpiritBuffExists = lambda _skill_id: False

    def reasons(*, equipped: bool, castable: bool) -> tuple[str, ...]:
        context = SimpleNamespace(
            skill_states={
                skill_id: HBS._SkillSnapshot(
                    skill_id=skill_id,
                    equipped=equipped,
                    castable=castable,
                    energy_cost=10.0,
                )
            },
            current_energy=5.0,
        )
        return HBS.My_Healing_Burst._diagnostic_skill_state_reasons(
            subject,
            context,
            skill_id,
        )

    assert reasons(equipped=False, castable=False) == ("not_equipped",)

    ready = False
    enough_energy = True
    assert reasons(equipped=True, castable=False) == ("recharge",)

    ready = True
    enough_energy = False
    assert reasons(equipped=True, castable=False) == ("insufficient_energy",)

    ready = True
    enough_energy = True
    pending = True
    assert reasons(equipped=True, castable=False) == ("cast_pending",)

    unsupported = SimpleNamespace(skill_states={}, current_energy=5.0)
    assert HBS.My_Healing_Burst._diagnostic_skill_state_reasons(
        subject,
        unsupported,
        skill_id,
    ) == ("unsupported",)


def test_diagnostic_effect_reasons_distinguish_present_and_stale_remote_state():
    subject = object.__new__(HBS.My_Healing_Burst)
    subject._has_effect_cached = lambda _context, _agent_id, _skill_id: True
    local_context = SimpleNamespace(
        player_id=1,
        party_player_ids=frozenset(),
        shared_effect_snapshots={},
        tick_ms=1000,
    )
    assert (
        HBS.My_Healing_Burst._diagnostic_effect_rejection(
            subject,
            local_context,
            1,
            HBS.PATIENT_SPIRIT_ID,
        )
        == "effect_present"
    )

    remote_context = SimpleNamespace(
        player_id=1,
        party_player_ids=frozenset({2}),
        shared_effect_snapshots={
            2: HBS._SharedAgentSnapshot(
                last_updated=0,
                effect_ids=frozenset(),
                exact_effects_available=True,
                is_enchanted=False,
                is_hexed=False,
                is_attacking=False,
                is_casting=False,
            )
        },
        tick_ms=1000,
    )
    assert (
        HBS.My_Healing_Burst._diagnostic_effect_rejection(
            subject,
            remote_context,
            2,
            HBS.PATIENT_SPIRIT_ID,
        )
        == "effect_state_stale"
    )

    remote_context.shared_effect_snapshots = {}
    assert (
        HBS.My_Healing_Burst._diagnostic_effect_rejection(
            subject,
            remote_context,
            2,
            HBS.PATIENT_SPIRIT_ID,
        )
        == "effect_state_unknown"
    )
