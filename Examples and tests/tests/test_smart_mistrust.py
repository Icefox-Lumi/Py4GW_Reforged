"""Deterministic offline policy and evidence tests for Smart Mistrust D3D."""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Skills" / "SmartMistrust.py"
MODULE_NAME = "d3d_test.smart_mistrust"


class _HandlerProfession(IntEnum):
    AnyProfession = 0
    Warrior = 1
    Mesmer = 5


class _HandlerAllegiance(IntEnum):
    Ally = 1
    Enemy = 3


class _FakeBuildMgr:
    def __init__(self, **_: Any) -> None:
        self._cached_data: Any = None

    def set_cached_data(self, cached_data: Any) -> None:
        self._cached_data = cached_data


@contextmanager
def _loaded_module() -> Iterator[Any]:
    owned_names = tuple(
        name
        for name in sys.modules
        if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d3d_test.")
    )
    original = {name: sys.modules[name] for name in owned_names}
    try:
        for name in owned_names:
            sys.modules.pop(name, None)
        root_package = types.ModuleType("Py4GWCoreLib")
        root_package.__path__ = [str(ROOT / "Py4GWCoreLib")]
        sys.modules["Py4GWCoreLib"] = root_package
        build_mgr_module = types.ModuleType("Py4GWCoreLib.BuildMgr")
        setattr(build_mgr_module, "BuildMgr", _FakeBuildMgr)
        sys.modules["Py4GWCoreLib.BuildMgr"] = build_mgr_module

        spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
        assert spec is not None and spec.loader is not None, f"could not load {MODULE_PATH}"
        module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = module
        spec.loader.exec_module(module)
        yield module
    finally:
        for name in tuple(sys.modules):
            if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d3d_test."):
                sys.modules.pop(name, None)
        sys.modules.update(original)


class _HandlerRuntime:
    def __init__(self) -> None:
        self.now_ms = 1000
        self.map_id = 1
        self.player_id = 1
        self.instance_uptime = 1
        self.enemy_ids = [10, 20]
        self.enemy_positions = {10: (100.0, 0.0), 20: (200.0, 0.0)}
        self.enemy_valid = {10: True, 20: True}
        self.enemy_alive = {10: True, 20: True}
        self.enemy_casting = {10: True, 20: True}
        self.enemy_skill = {10: 200, 20: 200}
        self.enemy_model_index: dict[int, int] = {10: 10, 20: 20}
        self.cached_model_index: dict[int, int] = {}
        self.npc_models: dict[int, Any] = {
            10: types.SimpleNamespace(primary=1, model_file_id=200),
            20: types.SimpleNamespace(primary=1, model_file_id=201),
        }
        self.enemy_living_primary: dict[int, Any] = {10: 0, 20: 0}
        self.enemy_npc: dict[int, bool] = {10: True, 20: True}
        self.enemy_living: dict[int, bool] = {10: True, 20: True}
        self.skill_types: dict[int, str] = {200: "Spell", 201: "Spell"}
        self.events: list[Any] = []
        self.party_login_to_agent: dict[int, int] = {}
        self.other_agents: list[int] = []
        self.dazed = False
        self.dazed_error = False
        self.ping = 0
        self.d0_group = 7
        self.d0_rows: list[Any] = []
        self.d0_failure = False
        self.d0_read_count = 0
        self.cast_calls = 0
        self.cast_targets: list[int] = []
        self.cast_result = True
        self.target_validation = True

    def get_attributes(self, agent_id: int) -> list[Any]:
        if int(agent_id) != self.player_id:
            return []
        return [
            types.SimpleNamespace(attribute_id=0, level=0, level_base=0),
            types.SimpleNamespace(attribute_id=2, level=15, level_base=15),
        ]

    def is_valid(self, agent_id: int) -> bool:
        if int(agent_id) in self.enemy_ids:
            return bool(self.enemy_valid.get(int(agent_id), False))
        return int(agent_id) > 0

    def is_alive(self, agent_id: int) -> bool:
        if int(agent_id) in self.enemy_ids:
            return bool(self.enemy_alive.get(int(agent_id), False))
        return int(agent_id) > 0

    def is_casting(self, agent_id: int) -> bool:
        return bool(self.enemy_casting.get(int(agent_id), False))

    def casting_skill_id(self, agent_id: int) -> int:
        return int(self.enemy_skill.get(int(agent_id), 0))

    def allegiance(self, agent_id: int) -> tuple[int, str]:
        if int(agent_id) in self.enemy_ids:
            return _HandlerAllegiance.Enemy.value, "Enemy"
        return _HandlerAllegiance.Ally.value, "Ally"

    def get_xy(self, agent_id: int) -> tuple[float, float]:
        return self.enemy_positions.get(int(agent_id), (0.0, 0.0))

    def living_agent(self, agent_id: int) -> Any:
        if int(agent_id) not in self.enemy_ids or not self.enemy_living.get(int(agent_id), False):
            return None
        return types.SimpleNamespace(
            is_npc=self.enemy_npc.get(int(agent_id), False),
            primary=self.enemy_living_primary.get(int(agent_id), 0),
            player_number=self.enemy_model_index.get(int(agent_id), 0),
        )

    def model_index(self, agent_id: int) -> int:
        return self.cached_model_index.get(int(agent_id), self.enemy_model_index.get(int(agent_id), 0))

    def model_at_index(self, model_index: int) -> Any:
        return self.npc_models.get(model_index)

    def peek_events(self) -> tuple[Any, ...]:
        return tuple(self.events)

    def has_effect(self, _agent_id: int, _skill_id: int) -> bool:
        if self.dazed_error:
            raise RuntimeError("Dazed lookup failed")
        return self.dazed

    def get_all_intents(self) -> list[Any]:
        self.d0_read_count += 1
        if self.d0_failure:
            raise RuntimeError("D0 unavailable")
        return list(self.d0_rows)

    def get_all_accounts(self) -> Any:
        return types.SimpleNamespace(GetAllIntents=self.get_all_intents)

    def get_options(self, _email: str) -> Any:
        return types.SimpleNamespace(Combat=True, Skills=[True] * 8)

    def can_cast_skill_slot(self, _slot: int) -> bool:
        return True

    def validate_target(self, _skill_id: int, _target_id: int) -> bool:
        return self.target_validation

    def cast_skill(
        self,
        *,
        skill_id: int,
        log: bool = False,
        aftercast_delay: int = 0,
        target_agent_id: int = 0,
    ) -> bool:
        del skill_id, log, aftercast_delay
        self.cast_calls += 1
        self.cast_targets.append(int(target_agent_id))
        return self.cast_result


@contextmanager
def _loaded_handler_runtime() -> Iterator[tuple[Any, _HandlerRuntime]]:
    external_names = ("PyAgentEvents", "PyPing", "PySystem")
    original_external = {name: sys.modules[name] for name in external_names if name in sys.modules}
    with _loaded_module() as module:
        runtime = _HandlerRuntime()
        try:
            for name in external_names:
                sys.modules.pop(name, None)

            root_package: Any = sys.modules["Py4GWCoreLib"]
            root_package.Profession = _HandlerProfession
            root_package.Map = types.SimpleNamespace(
                IsMapReady=lambda: True,
                IsExplorable=lambda: True,
                IsInCinematic=lambda: False,
                GetMapID=lambda: runtime.map_id,
                GetInstanceUptime=lambda: runtime.instance_uptime,
            )
            root_package.Player = types.SimpleNamespace(
                GetAgentID=lambda: runtime.player_id,
                GetAccountEmail=lambda: "d3d-handler@test",
                GetXY=lambda: (0.0, 0.0),
            )
            root_package.Agent = types.SimpleNamespace(
                GetAttributes=runtime.get_attributes,
                IsValid=runtime.is_valid,
                IsAlive=runtime.is_alive,
                IsDead=lambda agent_id: not runtime.is_alive(agent_id),
                IsCasting=runtime.is_casting,
                GetCastingSkillID=runtime.casting_skill_id,
                GetAllegiance=runtime.allegiance,
                GetXY=runtime.get_xy,
                GetHealth=lambda _agent_id: 1.0,
                GetMaxHealth=lambda _agent_id: 100.0,
                IsLiving=lambda agent_id: runtime.enemy_living.get(int(agent_id), False),
                GetLivingAgentByID=runtime.living_agent,
                GetModelID=runtime.model_index,
                GetNPCModelAtIndex=runtime.model_at_index,
                IsKnockedDown=lambda _agent_id: False,
            )
            root_package.AgentArray = types.SimpleNamespace(GetEnemyArray=lambda: list(runtime.enemy_ids))
            root_package.SkillBar = types.SimpleNamespace(
                GetSkillIDBySlot=lambda slot: 979 if int(slot) == 1 else 0,
            )
            root_package.Party = types.SimpleNamespace(
                GetPlayers=lambda: [
                    types.SimpleNamespace(login_number=login) for login in runtime.party_login_to_agent
                ],
                Players=types.SimpleNamespace(
                    GetAgentIDByLoginNumber=lambda login: runtime.party_login_to_agent.get(int(login), 0)
                ),
                GetHeroes=lambda: (),
                GetHenchmen=lambda: (),
                GetOthers=lambda: list(runtime.other_agents),
            )
            root_package.Routines = types.SimpleNamespace(
                Checks=types.SimpleNamespace(
                    Map=types.SimpleNamespace(MapValid=lambda: True),
                    Player=types.SimpleNamespace(CanAct=lambda: True),
                    Skills=types.SimpleNamespace(CanCast=lambda: True),
                    Agents=types.SimpleNamespace(HasEffect=runtime.has_effect),
                )
            )
            root_package.GLOBAL_CACHE = types.SimpleNamespace(
                Skill=types.SimpleNamespace(
                    Data=types.SimpleNamespace(
                        GetActivation=lambda skill_id: 1.0 if int(skill_id) == 979 else 2.0,
                        GetAftercast=lambda _skill_id: 0.25,
                    ),
                    GetID=lambda name: 999 if name == "Dazed" else 0,
                ),
                SkillBar=types.SimpleNamespace(
                    GetCasting=lambda: 0,
                    GetSkillData=lambda _slot: types.SimpleNamespace(recharge=0.0),
                ),
                ShMem=types.SimpleNamespace(
                    GetHeroAIOptionsFromEmail=runtime.get_options,
                    GetAccountGroupByEmail=lambda _email: runtime.d0_group,
                    GetAllAccounts=runtime.get_all_accounts,
                ),
            )

            skill_module: Any = types.ModuleType("Py4GWCoreLib.Skill")
            skill_module.Skill = types.SimpleNamespace(
                Attribute=types.SimpleNamespace(GetScale=lambda _skill_id: (10, 80)),
                GetType=lambda skill_id: (0, runtime.skill_types.get(int(skill_id), "Attack")),
            )
            sys.modules["Py4GWCoreLib.Skill"] = skill_module

            enums_package: Any = types.ModuleType("Py4GWCoreLib.enums_src")
            enums_package.__path__ = []
            sys.modules["Py4GWCoreLib.enums_src"] = enums_package
            game_data_module: Any = types.ModuleType("Py4GWCoreLib.enums_src.GameData_enums")
            game_data_module.Profession = _HandlerProfession
            game_data_module.Allegiance = _HandlerAllegiance
            sys.modules["Py4GWCoreLib.enums_src.GameData_enums"] = game_data_module

            events_module: Any = types.ModuleType("PyAgentEvents")
            events_module.peek_events = runtime.peek_events
            sys.modules["PyAgentEvents"] = events_module

            system_module: Any = types.ModuleType("PySystem")
            system_module.get_tick_count64 = lambda: runtime.now_ms
            sys.modules["PySystem"] = system_module

            ping_module: Any = types.ModuleType("PyPing")

            class _PingHandler:
                def GetCurrentPing(self) -> int:
                    return runtime.ping

            ping_module.PingHandler = _PingHandler
            sys.modules["PyPing"] = ping_module
            yield module, runtime
        finally:
            for name in external_names:
                sys.modules.pop(name, None)
            sys.modules.update(original_external)


def _new_handler(module: Any, runtime: _HandlerRuntime) -> Any:
    handler = module.SmartMistrust()
    handler.set_skill_slot(1)
    handler.CanCastSkillSlot = runtime.can_cast_skill_slot
    handler.CastSkillID = runtime.cast_skill
    handler._validate_target_for_skill_cast = runtime.validate_target
    assert handler._refresh_lifecycle() is True
    return handler


def _drain(generator: Any) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as finished:
            return finished.value


with _loaded_module() as _smart:
    CandidateReason = _smart.CandidateReason
    DecisionReason = _smart.DecisionReason
    MistrustMode = _smart.MistrustMode
    MistrustOpportunity = _smart.MistrustOpportunity
    MistrustPolicy = _smart.MistrustPolicy
    MistrustTargetObservation = _smart.MistrustTargetObservation
    SkillActivationEvidence = _smart.SkillActivationEvidence
    SmartMistrust = _smart.SmartMistrust
    calculate_local_mistrust_activation_ms = _smart.calculate_local_mistrust_activation_ms
    calculate_reactive_reserve_ms = _smart.calculate_reactive_reserve_ms
    estimate_enemy_remaining_ms = _smart.estimate_enemy_remaining_ms
    evaluate = _smart.evaluate_smart_mistrust
    is_confirmed_direct_party_target = _smart.is_confirmed_direct_party_target
    qualifies_skill_type = _smart.qualifies_mistrust_skill_type
    reactive_timing_slack_ms = _smart.reactive_timing_slack_ms
    resolve_damage = _smart.resolve_mistrust_damage


def _event(
    timestamp: int,
    *,
    event_type: int = 1,
    agent_id: int = 10,
    skill_id: int = 200,
    target_id: int = 1,
    float_value: float = 0.0,
) -> Any:
    return types.SimpleNamespace(
        timestamp=timestamp,
        event_type=event_type,
        agent_id=agent_id,
        value=skill_id,
        target_id=target_id,
        float_value=float_value,
    )


def _target(
    agent_id: int,
    *,
    x: float = 0.0,
    y: float = 0.0,
    hp: float | None = 100.0,
    distance: float | None = 100.0,
    valid: bool | None = True,
    alive: bool | None = True,
    hostile: bool | None = True,
    targetable: bool | None = True,
) -> Any:
    return MistrustTargetObservation(
        agent_id=agent_id,
        x=x,
        y=y,
        current_hp=hp,
        distance_from_player=distance,
        is_valid=valid,
        is_alive=alive,
        is_hostile=hostile,
        is_targetable=targetable,
    )


def _opportunity(
    target: Any,
    *,
    mode: Any = MistrustMode.REACTIVE,
    splash: tuple[Any, ...] = (),
    slack: int | None = 1,
    history: int | None = None,
) -> Any:
    return MistrustOpportunity(
        mode=mode,
        primary=target,
        splash_targets=splash,
        timing_slack_ms=slack if mode is MistrustMode.REACTIVE else None,
        most_recent_history_ms=history if mode is MistrustMode.PROACTIVE else None,
    )


POLICY = MistrustPolicy(primary_damage=80.0, splash_damage=60.0)


def test_spell_and_hex_are_the_only_qualifying_v1_types() -> None:
    assert qualifies_skill_type("Spell") is True
    assert qualifies_skill_type("Hex") is True
    assert qualifies_skill_type("Attack") is False
    assert qualifies_skill_type("Signet") is False


def test_direct_target_identity_requires_confirmed_party_membership() -> None:
    assert is_confirmed_direct_party_target(10, 1, True) is True
    assert is_confirmed_direct_party_target(10, 0, True) is False
    assert is_confirmed_direct_party_target(10, 10, True) is False
    assert is_confirmed_direct_party_target(10, 20, False) is False
    assert is_confirmed_direct_party_target(10, 20, None) is False


def test_damage_scaling_uses_live_endpoints_and_rank_sixteen() -> None:
    assert resolve_damage(0, (10, 80)) == (10, 7)
    assert resolve_damage(15, (10, 80)) == (80, 60)
    assert resolve_damage(16, (10, 80)) == (85, 63)
    assert resolve_damage(21, (10, 80)) == (108, 81)
    assert resolve_damage(15, (11, 80)) is None
    assert resolve_damage(None, (10, 80)) is None


def test_local_fast_casting_calculation_uses_current_rank_without_clamping() -> None:
    assert calculate_local_mistrust_activation_ms(1.05, 0) == 1050
    assert calculate_local_mistrust_activation_ms(1.05, 15) == math.ceil(1000 * round(1.05 * (0.955**15), 3))
    assert calculate_local_mistrust_activation_ms(1.05, 16) != calculate_local_mistrust_activation_ms(1.05, 15)
    assert calculate_local_mistrust_activation_ms(1.05, None) is None


def test_reactive_remaining_time_requires_strictly_positive_slack() -> None:
    assert calculate_reactive_reserve_ms(100) == 570
    assert estimate_enemy_remaining_ms(1.0, 100, 0) == 900
    assert (
        reactive_timing_slack_ms(
            enemy_base_activation_seconds=1.0,
            dispatch_now_ms=300,
            retained_onset_ms=0,
            local_mistrust_est_ms=250,
            current_ping_ms=0,
        )
        is None
    )
    assert (
        reactive_timing_slack_ms(
            enemy_base_activation_seconds=1.0,
            dispatch_now_ms=299,
            retained_onset_ms=0,
            local_mistrust_est_ms=250,
            current_ping_ms=0,
        )
        == 1
    )
    assert (
        reactive_timing_slack_ms(
            enemy_base_activation_seconds=1.0,
            dispatch_now_ms=299,
            retained_onset_ms=0,
            local_mistrust_est_ms=300,
            current_ping_ms=None,
        )
        is None
    )


def test_primary_hp_cap_and_splash_hp_caps_exclude_primary() -> None:
    primary = _target(10, hp=80)
    splash = _target(11, x=240.0, hp=30)
    decision = evaluate((_opportunity(primary, splash=(primary, splash)),), policy=POLICY)

    assert decision.reason is DecisionReason.SELECTED
    assert decision.selected is not None
    assert decision.selected.useful_primary_damage == 80
    assert decision.selected.useful_splash_damage == 30
    assert decision.selected.splash_agent_ids == (11,)
    assert decision.selected.useful_damage == 110


def test_duplicate_splash_observations_count_each_victim_once() -> None:
    primary = _target(10, hp=100)
    splash = _target(11, x=10.0, hp=60)
    decision = evaluate((_opportunity(primary, splash=(splash, splash)),), policy=POLICY)

    assert decision.selected is not None
    assert decision.selected.splash_agent_ids == (11,)
    assert decision.selected.useful_damage == 140


def test_bad_primary_hp_rejects_only_that_primary_and_bad_splash_is_omitted() -> None:
    bad_primary = _target(10, hp=None)
    good_primary = _target(20, hp=100, x=50.0)
    bad_splash = _target(21, x=50.0, hp=None)
    decision = evaluate(
        (
            _opportunity(bad_primary),
            _opportunity(good_primary, splash=(bad_splash,)),
        ),
        policy=POLICY,
    )

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 20
    assert decision.selected.useful_damage == 80
    assert any(candidate.reason is CandidateReason.MISSING_EVIDENCE for candidate in decision.candidates)


def test_range_and_radius_boundaries_are_inclusive() -> None:
    exact_range = evaluate((_opportunity(_target(10, distance=1248.0)),), policy=POLICY)
    out_of_range = evaluate((_opportunity(_target(10, distance=1248.001)),), policy=POLICY)
    exact_radius = evaluate(
        (_opportunity(_target(10), splash=(_target(11, x=240.0),)),),
        policy=POLICY,
    )
    outside_radius = evaluate(
        (_opportunity(_target(10), splash=(_target(11, x=240.001),)),),
        policy=POLICY,
    )

    assert exact_range.selected is not None
    assert out_of_range.selected is None
    assert exact_radius.selected is not None and exact_radius.selected.splash_agent_ids == (11,)
    assert outside_radius.selected is not None and outside_radius.selected.splash_agent_ids == ()


def test_reactive_and_proactive_minimum_value_boundaries() -> None:
    reactive_exact = evaluate((_opportunity(_target(10, hp=80)),), policy=POLICY)
    reactive_short = evaluate((_opportunity(_target(10, hp=79)),), policy=POLICY)
    proactive_exact = evaluate(
        (
            _opportunity(
                _target(10, hp=80),
                mode=MistrustMode.PROACTIVE,
                splash=(_target(11, x=10.0, hp=60),),
                history=100,
            ),
        ),
        policy=POLICY,
    )
    proactive_short = evaluate(
        (
            _opportunity(
                _target(10, hp=80),
                mode=MistrustMode.PROACTIVE,
                splash=(_target(11, x=10.0, hp=59),),
                history=100,
            ),
        ),
        policy=POLICY,
    )

    assert reactive_exact.selected is not None
    assert reactive_short.selected is None
    assert proactive_exact.selected is not None
    assert proactive_short.selected is None


def test_reactive_opportunity_precedes_proactive_inside_mistrust() -> None:
    proactive = _opportunity(
        _target(20),
        mode=MistrustMode.PROACTIVE,
        splash=(_target(21, x=10.0, hp=60),),
        history=5000,
    )
    reactive = _opportunity(_target(10), mode=MistrustMode.REACTIVE, slack=1)

    decision = evaluate((proactive, reactive), policy=POLICY)

    assert decision.selected is not None
    assert decision.selected.mode is MistrustMode.REACTIVE
    assert decision.selected.target_agent_id == 10


def test_reactive_ties_use_timing_slack_then_agent_id() -> None:
    first = _opportunity(_target(10), slack=2)
    second = _opportunity(_target(20), slack=3)
    decision = evaluate((first, second), policy=POLICY)

    assert decision.selected is not None
    assert decision.selected.target_agent_id == 20


def test_activation_evidence_rejects_target_zero_and_deduplicates() -> None:
    evidence = SkillActivationEvidence()
    target_zero = _event(900, target_id=0)
    valid = _event(950, target_id=1)

    evidence.update(1000, (target_zero, valid, valid))

    assert len(evidence.history_records(1000)) == 1
    assert evidence.history_records(1000)[0].target_id == 1


def test_activation_evidence_requires_activation_seen_within_150_ms() -> None:
    evidence = SkillActivationEvidence()

    evidence.update(1000, (_event(849),))
    assert evidence.get_reactive(10, 200, 1000) is None

    evidence.clear()
    evidence.update(1000, (_event(850),))
    assert evidence.get_reactive(10, 200, 1000) is not None


def test_activation_evidence_rejects_changed_conflicting_cast() -> None:
    evidence = SkillActivationEvidence()

    evidence.update(1000, (_event(950, skill_id=200, target_id=1),))
    evidence.update(1000, (_event(950, skill_id=201, target_id=1),))

    assert evidence.get_reactive(10, 200, 1000) is None
    assert evidence.history_records(1000) == ()


def test_terminal_event_keeps_target_identity_but_clears_reactive_admission() -> None:
    evidence = SkillActivationEvidence()

    evidence.update(1000, (_event(950, skill_id=200, target_id=1),))
    evidence.update(1000, (_event(980, event_type=3, skill_id=200, target_id=0),))

    records = evidence.history_records(1000)
    assert records[0].target_id == 1
    assert records[0].terminal_ms == 980
    assert evidence.get_reactive(10, 200, 1000) is None


def test_activation_history_expires_at_six_second_boundary_and_clears() -> None:
    evidence = SkillActivationEvidence()
    evidence.update(1000, (_event(1000),))

    assert len(evidence.history_records(6999)) == 1
    assert evidence.history_records(7000) == ()
    evidence.clear()
    assert evidence.history_records(1000) == ()


def test_current_attribute_rank_uses_effective_level_not_level_base() -> None:
    agent = types.SimpleNamespace(
        GetAttributes=lambda _agent_id: [types.SimpleNamespace(attribute_id=0, level=16, level_base=3)]
    )

    assert SmartMistrust._current_attribute_rank(agent, 1, 0) == 16


def test_d0_matching_requires_live_group_identity_and_post_onset_claim() -> None:
    intent = types.SimpleNamespace(
        Active=True,
        KindID=11,
        IsolationGroupID=4,
        SkillID=200,
        TargetAgentID=10,
        PostedAtTick=950,
        ExpiresAtTick=1200,
    )
    compatible = SmartMistrust._d0_claim_compatible(
        intent,
        group_id=4,
        enemy_agent_id=10,
        enemy_skill_id=200,
        now_ms=1000,
        retained_onset_ms=900,
    )
    precast = SmartMistrust._d0_claim_compatible(
        types.SimpleNamespace(**{**vars(intent), "PostedAtTick": 850}),
        group_id=4,
        enemy_agent_id=10,
        enemy_skill_id=200,
        now_ms=1000,
        retained_onset_ms=900,
    )
    expired = SmartMistrust._d0_claim_compatible(
        types.SimpleNamespace(**{**vars(intent), "ExpiresAtTick": 1000}),
        group_id=4,
        enemy_agent_id=10,
        enemy_skill_id=200,
        now_ms=1000,
        retained_onset_ms=900,
    )

    assert compatible is True
    assert precast is False
    assert expired is False
    assert (
        SmartMistrust._d0_claim_compatible(
            intent,
            group_id=4,
            enemy_agent_id=11,
            enemy_skill_id=200,
            now_ms=1000,
            retained_onset_ms=900,
        )
        is False
    )


def test_local_duplicate_suppression_is_bounded_and_does_not_use_enemy_effects() -> None:
    handler = object.__new__(SmartMistrust)
    handler._recent_success_by_target = {10: 1000}
    handler._pending_local_attempt = (10, (1, 1, 0))

    assert handler._recent_success_is_live(10, 5999) is True
    assert handler._recent_success_is_live(10, 7000) is False
    assert handler.has_active_dispatch() is True
    handler.cancel_pending("test")
    assert handler.has_active_dispatch() is False


def test_handler_d0_is_dispatch_only_and_rejection_does_not_reselect() -> None:
    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)
        runtime.events = [
            _event(700, agent_id=10),
            _event(900, agent_id=10),
            _event(900, agent_id=20),
        ]
        assert handler._update_activation_evidence(runtime.now_ms) is True
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        runtime.d0_rows = [
            (
                0,
                types.SimpleNamespace(
                    Active=True,
                    KindID=11,
                    IsolationGroupID=7,
                    SkillID=200,
                    TargetAgentID=10,
                    PostedAtTick=950,
                    ExpiresAtTick=2000,
                ),
            )
        ]

        decision = handler._evaluate_live(parameters, now_ms=runtime.now_ms)

        assert decision is not None and decision.selected is not None
        assert decision.selected.mode.value == "reactive"
        assert decision.selected.target_agent_id == 10
        assert runtime.d0_read_count == 0

        result = _drain(handler._dispatch_selected(decision.selected, parameters))

        assert result is False
        assert runtime.d0_read_count == 1
        assert runtime.cast_calls == 0


def test_handler_guarded_revalidation_rejects_changed_current_cast() -> None:
    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)
        runtime.enemy_ids = [10]
        runtime.events = [_event(900, agent_id=10, skill_id=200)]
        assert handler._update_activation_evidence(runtime.now_ms) is True
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        decision = handler._evaluate_live(parameters, now_ms=runtime.now_ms)
        assert decision is not None and decision.selected is not None

        runtime.enemy_skill[10] = 201
        result = _drain(handler._dispatch_selected(decision.selected, parameters))

        assert result is False
        assert runtime.cast_calls == 0
        assert runtime.d0_read_count == 0


def test_handler_d0_unavailable_or_untrusted_fails_open() -> None:
    for failure_mode in ("read", "group_unavailable", "untrusted_group"):
        with _loaded_handler_runtime() as (module, runtime):
            handler = _new_handler(module, runtime)
            runtime.enemy_ids = [10]
            runtime.events = [_event(900, agent_id=10)]
            assert handler._update_activation_evidence(runtime.now_ms) is True
            parameters = handler._resolve_runtime_parameters()
            assert parameters is not None
            decision = handler._evaluate_live(parameters, now_ms=runtime.now_ms)
            assert decision is not None and decision.selected is not None

            if failure_mode == "read":
                runtime.d0_failure = True
            elif failure_mode == "group_unavailable":
                runtime.d0_group = 0
            else:
                runtime.d0_group = -1

            result = _drain(handler._dispatch_selected(decision.selected, parameters))

            assert result is True
            assert runtime.cast_calls == 1


def test_handler_party_direct_target_wiring_accepts_only_confirmed_party_members() -> None:
    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)
        runtime.party_login_to_agent = {12: 2}

        assert handler._direct_target_is_friendly(10, 1) is True
        assert handler._direct_target_is_friendly(10, 2) is True
        assert handler._direct_target_is_friendly(10, 99) is False


def test_handler_enemy_profession_branches_require_known_non_mesmer_primary() -> None:
    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)
        record = module.SkillActivationRecord(
            enemy_agent_id=10,
            skill_id=200,
            onset_ms=900,
            target_id=1,
            first_observed_ms=900,
        )

        runtime.npc_models[10].primary = int(_HandlerProfession.Warrior)
        assert handler._enemy_remaining_slack(record, runtime.now_ms, 1000) == 450
        runtime.npc_models[10].primary = int(_HandlerProfession.Mesmer)
        assert handler._enemy_remaining_slack(record, runtime.now_ms, 1000) is None
        runtime.npc_models[10].primary = 99
        assert handler._enemy_remaining_slack(record, runtime.now_ms, 1000) is None


def test_handler_reactive_profession_requires_current_indexed_npc_primary() -> None:
    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)

        evidence = handler._enemy_profession_evidence(10)
        assert evidence is not None
        assert (evidence.model_index, evidence.model_primary, evidence.living_primary) == (10, 1, 0)

        runtime.enemy_living_primary[10] = 1
        assert handler._enemy_profession_evidence(10) is not None
        runtime.enemy_living_primary[10] = 2
        assert handler._enemy_profession_evidence(10) is None
        runtime.enemy_living_primary[10] = 99
        assert handler._enemy_profession_evidence(10) is None
        runtime.enemy_living_primary[10] = 0

        for bad_primary in (0, -1, 5, 11, "unreadable"):
            runtime.npc_models[10].primary = bad_primary
            assert handler._enemy_profession_evidence(10) is None
        runtime.npc_models[10] = types.SimpleNamespace(model_file_id=200)
        assert handler._enemy_profession_evidence(10) is None
        runtime.npc_models[10].primary = 10
        assert handler._enemy_profession_evidence(10) is not None
        runtime.npc_models[10].primary = 1

        for bad_index in (0, -1, 201, 999):
            runtime.enemy_model_index[10] = bad_index
            assert handler._enemy_profession_evidence(10) is None
        runtime.enemy_model_index[10] = 10
        removed = runtime.npc_models.pop(10)
        assert handler._enemy_profession_evidence(10) is None
        runtime.npc_models[10] = removed

        runtime.enemy_npc[10] = False
        assert handler._enemy_profession_evidence(10) is None
        runtime.enemy_npc[10] = True
        runtime.enemy_living[10] = False
        assert handler._enemy_profession_evidence(10) is None
        runtime.enemy_living[10] = True
        runtime.enemy_valid[10] = False
        assert handler._enemy_profession_evidence(10) is None


def test_handler_dispatch_rejects_changed_reactive_model_evidence() -> None:
    def change_model_index(runtime: _HandlerRuntime) -> None:
        runtime.enemy_model_index[10] = 20

    def leave_cached_model_index_stale(runtime: _HandlerRuntime) -> None:
        runtime.cached_model_index[10] = 10
        runtime.enemy_model_index[10] = 20

    def remove_row(runtime: _HandlerRuntime) -> None:
        runtime.npc_models.pop(10)

    changes: tuple[Callable[[_HandlerRuntime], None], ...] = (
        change_model_index,
        leave_cached_model_index_stale,
        remove_row,
        lambda runtime: setattr(runtime.npc_models[10], "primary", 5),
        lambda runtime: setattr(runtime.npc_models[10], "primary", 0),
        lambda runtime: setattr(runtime.npc_models[10], "primary", 2),
        lambda runtime: runtime.enemy_living_primary.__setitem__(10, 2),
        lambda runtime: runtime.enemy_npc.__setitem__(10, False),
        lambda runtime: runtime.enemy_valid.__setitem__(10, False),
    )
    for change in changes:
        with _loaded_handler_runtime() as (module, runtime):
            handler = _new_handler(module, runtime)
            runtime.enemy_ids = [10]
            runtime.events = [_event(900, agent_id=10)]
            assert handler._update_activation_evidence(runtime.now_ms) is True
            parameters = handler._resolve_runtime_parameters()
            assert parameters is not None
            decision = handler._evaluate_live(parameters, now_ms=runtime.now_ms)
            assert decision is not None and decision.selected is not None
            assert decision.selected.mode is module.MistrustMode.REACTIVE

            change(runtime)
            assert _drain(handler._dispatch_selected(decision.selected, parameters)) is False
            assert runtime.cast_calls == 0
            assert runtime.d0_read_count == 0


def test_agent_current_npc_model_lookup_is_strict_and_preserves_legacy_fallback() -> None:
    def no_op(*_args: Any, **_kwargs: Any) -> None:
        return None

    def frame_cache(**_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return lambda function: function

    def identity(value: Any) -> Any:
        return value

    original_py_agent = sys.modules.get("PyAgent")
    original_py_callback = sys.modules.get("PyCallback")
    try:
        with _loaded_module():
            sys.modules["PyAgent"] = types.ModuleType("PyAgent")
            callback_module: Any = types.ModuleType("PyCallback")
            callback_module.Phase = types.SimpleNamespace(PreUpdate=1)
            callback_module.PyCallback = types.SimpleNamespace(Register=no_op)
            sys.modules["PyCallback"] = callback_module
            frame_cache_module: Any = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.FrameCache")
            frame_cache_module.frame_cache = frame_cache
            sys.modules[frame_cache_module.__name__] = frame_cache_module

            agent_context = types.ModuleType("Py4GWCoreLib.native_src.context.AgentContext")
            for name in ("AgentStruct", "AgentLivingStruct", "AgentItemStruct", "AgentGadgetStruct"):
                setattr(agent_context, name, type(name, (), {}))
            sys.modules[agent_context.__name__] = agent_context
            world_context: Any = types.ModuleType("Py4GWCoreLib.native_src.context.WorldContext")
            world_context.AttributeStruct = type("AttributeStruct", (), {})
            world_context.NPC_ModelStruct = type("NPC_ModelStruct", (), {})
            sys.modules[world_context.__name__] = world_context

            class _ArrayView:
                def __init__(self, rows: Any, _row_type: Any) -> None:
                    self.rows = rows

                def get(self, index: int) -> Any:
                    if self.rows is None or not 0 <= index < len(self.rows):
                        return None
                    return self.rows[index]

            array_module: Any = types.ModuleType("Py4GWCoreLib.native_src.internals.gw_array")
            array_module.GW_Array_Value_View = _ArrayView
            sys.modules[array_module.__name__] = array_module
            helpers: Any = types.ModuleType("Py4GWCoreLib.native_src.internals.helpers")
            helpers.encoded_wstr_to_str = identity
            sys.modules[helpers.__name__] = helpers
            string_table: Any = types.ModuleType("Py4GWCoreLib.native_src.internals.string_table")
            string_table.decode = identity
            sys.modules[string_table.__name__] = string_table

            first = types.SimpleNamespace(model_file_id=400, is_valid=True)
            fallback_only = types.SimpleNamespace(model_file_id=3, is_valid=True)
            world = types.SimpleNamespace(npc_models_array=[first, first, fallback_only], npc_models=[first, fallback_only])
            context_module: Any = types.ModuleType("Py4GWCoreLib.Context")
            context_module.GWContext = types.SimpleNamespace(World=types.SimpleNamespace(GetContext=lambda: world))
            sys.modules[context_module.__name__] = context_module

            spec = importlib.util.spec_from_file_location("Py4GWCoreLib.Agent", ROOT / "Py4GWCoreLib" / "Agent.py")
            assert spec is not None and spec.loader is not None
            agent_module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = agent_module
            spec.loader.exec_module(agent_module)
            agent_api = agent_module.Agent

            assert agent_api.GetNPCModelAtIndex(2) is fallback_only
            assert agent_api.GetNPCModelAtIndex(0) is None
            assert agent_api.GetNPCModelAtIndex(-1) is None
            assert agent_api.GetNPCModelAtIndex(3) is None
            assert agent_api.GetNPCModelAtIndex(400) is None
            assert agent_api.GetNPCModelByID(3) is fallback_only
            fallback_only.is_valid = False
            assert agent_api.GetNPCModelAtIndex(2) is None
            fallback_only.is_valid = True
            world.npc_models_array = None
            assert agent_api.GetNPCModelAtIndex(2) is None
    finally:
        if original_py_agent is None:
            sys.modules.pop("PyAgent", None)
        else:
            sys.modules["PyAgent"] = original_py_agent
        if original_py_callback is None:
            sys.modules.pop("PyCallback", None)
        else:
            sys.modules["PyCallback"] = original_py_callback


def test_handler_dazed_presence_or_lookup_failure_blocks_reactive_admission() -> None:
    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)
        runtime.enemy_ids = [10]
        runtime.events = [_event(900, agent_id=10)]
        assert handler._update_activation_evidence(runtime.now_ms) is True
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        runtime.dazed = True
        present = handler._evaluate_live(parameters, now_ms=runtime.now_ms)
        runtime.dazed = False
        runtime.dazed_error = True
        failed = handler._evaluate_live(parameters, now_ms=runtime.now_ms)

        assert present is not None and present.selected is None
        assert failed is not None and failed.selected is None


def test_handler_proactive_history_requires_two_distinct_ingested_casts() -> None:
    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)
        runtime.enemy_ids = [10, 11]
        runtime.enemy_positions[11] = (150.0, 0.0)
        runtime.enemy_valid[11] = True
        runtime.enemy_alive[11] = True
        runtime.enemy_casting[10] = False
        runtime.enemy_casting[11] = False
        runtime.enemy_skill[11] = 0
        runtime.enemy_model_index[11] = 11
        runtime.npc_models[11] = types.SimpleNamespace(primary=1, model_file_id=202)
        runtime.enemy_living_primary[11] = 0
        runtime.enemy_npc[11] = True
        runtime.enemy_living[11] = True
        first = _event(900, agent_id=10)
        runtime.events = [first]
        assert handler._update_activation_evidence(1000) is True
        assert len(handler._proactive_history.get(10, ())) == 1
        initial_parameters = handler._resolve_runtime_parameters()
        assert initial_parameters is not None
        initial_decision = handler._evaluate_live(initial_parameters, now_ms=1000)
        assert initial_decision is not None and initial_decision.selected is None

        runtime.now_ms = 1100
        assert handler._update_activation_evidence(runtime.now_ms) is True
        assert len(handler._proactive_history.get(10, ())) == 1

        second = _event(1900, agent_id=10)
        runtime.events.append(second)
        runtime.now_ms = 2000
        assert handler._update_activation_evidence(runtime.now_ms) is True
        assert len(handler._history_for(10, runtime.now_ms)) == 2
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        decision = handler._evaluate_live(parameters, now_ms=runtime.now_ms)
        assert decision is not None and decision.selected is not None
        assert decision.selected.mode.value == "proactive"
        runtime.npc_models[10].primary = 5
        still_proactive = handler._evaluate_live(parameters, now_ms=runtime.now_ms)
        assert still_proactive is not None and still_proactive.selected is not None
        assert still_proactive.selected.mode.value == "proactive"

        runtime.now_ms = 7900
        handler._prune_history(runtime.now_ms)
        assert handler._history_for(10, runtime.now_ms) == ()
        assert handler._activation_evidence.history_records(runtime.now_ms) == ()


def test_handler_lifecycle_and_disposal_clear_observation_state() -> None:
    for changed_input, changed_value in (("map_id", 2), ("instance_uptime", 2), ("player_id", 2)):
        with _loaded_handler_runtime() as (module, runtime):
            runtime.instance_uptime = 10
            handler = _new_handler(module, runtime)
            runtime.events = [_event(900, agent_id=10)]
            assert handler._update_activation_evidence(runtime.now_ms) is True
            handler._recent_success_by_target = {10: runtime.now_ms}
            handler._pending_local_attempt = (10, handler._lifecycle_id)

            setattr(runtime, changed_input, changed_value)
            assert handler._refresh_lifecycle() is True

            assert handler._activation_evidence.history_records(runtime.now_ms) == ()
            assert handler._proactive_history == {}
            assert handler._recent_success_by_target == {}
            assert handler.has_active_dispatch() is False

    with _loaded_handler_runtime() as (module, runtime):
        handler = _new_handler(module, runtime)
        runtime.events = [_event(900, agent_id=10)]
        assert handler._update_activation_evidence(runtime.now_ms) is True
        handler._recent_success_by_target = {10: runtime.now_ms}
        runtime.enemy_alive[10] = False
        handler._prune_history(runtime.now_ms + 1)
        assert handler._activation_evidence.history_records(runtime.now_ms + 1) == ()
        assert handler._proactive_history == {}
        assert handler._recent_success_by_target == {}

        handler._pending_local_attempt = (10, handler._lifecycle_id)
        handler.cancel_pending("test_cancel")
        assert handler.has_active_dispatch() is False
        handler._pending_local_attempt = (10, handler._lifecycle_id)
        handler.dispose("test_disposal")
        assert handler.has_active_dispatch() is False
        assert handler._activation_evidence.history_records(runtime.now_ms + 1) == ()
