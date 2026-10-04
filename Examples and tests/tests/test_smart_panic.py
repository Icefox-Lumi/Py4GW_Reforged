"""Focused offline policy and lifecycle tests for Smart Panic."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Any
from typing import Iterator
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Skills" / "SmartPanic.py"
MODULE_NAME = "_d3c_b_smart_panic"
AGENT_MODULE_PATH = ROOT / "Py4GWCoreLib" / "Agent.py"
AGENT_MODULE_NAME = "Py4GWCoreLib.Agent"


class _Profession(IntEnum):
    _None = 0
    Mesmer = 5


class _Allegiance(IntEnum):
    Ally = 1
    Enemy = 3


class _FakeBuildMgr:
    def __init__(self, **_: Any) -> None:
        self._cached_data: Any = None
        self._test_runtime: Any = None

    def set_cached_data(self, cached_data: Any) -> None:
        self._cached_data = cached_data

    def _validate_target_for_skill_cast(self, _skill_id: int, agent_id: int) -> bool:
        runtime = self._test_runtime
        return runtime is None or runtime.target_allowed.get(int(agent_id), True)

    def CanCastSkillSlot(self, _slot: int) -> bool:
        runtime = self._test_runtime
        return runtime is None or runtime.skill_ready

    def CanCastSkillID(self, _skill_id: int) -> bool:
        runtime = self._test_runtime
        return runtime is None or runtime.skill_ready

    def _is_local_cast_pending(self) -> bool:
        runtime = self._test_runtime
        return runtime is not None and runtime.local_cast_pending

    def CastSkillID(
        self,
        *,
        skill_id: int,
        target_agent_id: int = 0,
        **_: Any,
    ) -> bool:
        runtime = self._test_runtime
        if runtime is None:
            return False
        runtime.cast_calls.append((int(skill_id), int(target_agent_id)))
        return runtime.cast_result


class _Runtime:
    def __init__(self) -> None:
        self.player_id = 1
        self.player_xy = (0.0, 0.0)
        self.map_id = 1
        self.instance_uptime = 100
        self.now_ms = 1000
        self.bar = [52, 0, 0, 0, 0, 0, 0, 0]
        self.enemy_ids: list[int] = []
        self.states: dict[int, Any] = {
            self.player_id: types.SimpleNamespace(
                position=self.player_xy,
                valid=True,
                living=True,
                alive=True,
                hostile=False,
                targetable=True,
                agent_is_spirit=False,
                agent_is_spirit_available=True,
                npc_flags=0,
                npc_flags_available=True,
                spawned=False,
                panic=False,
                caster=False,
                casting=False,
            )
        }
        self.target_allowed: dict[int, bool] = {}
        self.panic_ids: set[int] = set()
        self.events: list[Any] = []
        self.attributes: dict[int, list[Any]] = {}
        self.progression_data: list[tuple[str, str, dict[int, float]]] = [
            ("Domination Magic", "Duration", {rank: float(max(1, rank // 2 + 1)) for rank in range(22)})
        ]
        self.skill_ready = True
        self.local_cast_pending = False
        self.cast_result = True
        self.cast_calls: list[tuple[int, int]] = []
        self.is_spirit_calls = 0
        self.is_spawned_calls = 0
        self.legacy_npc_flags_calls = 0
        self.optional_npc_flags_calls = 0

    def add_enemy(
        self,
        agent_id: int,
        *,
        x: float,
        y: float = 0.0,
        valid: bool = True,
        living: bool = True,
        alive: bool = True,
        hostile: bool = True,
        targetable: bool = True,
        agent_is_spirit: Any = False,
        agent_is_spirit_available: bool = True,
        npc_flags: Any = 0,
        npc_flags_available: bool = True,
        spawned: bool = False,
        caster: bool = False,
        casting: bool = False,
    ) -> None:
        self.states[agent_id] = types.SimpleNamespace(
            position=(x, y),
            valid=valid,
            living=living,
            alive=alive,
            hostile=hostile,
            targetable=targetable,
            agent_is_spirit=agent_is_spirit,
            agent_is_spirit_available=agent_is_spirit_available,
            npc_flags=npc_flags,
            npc_flags_available=npc_flags_available,
            spawned=spawned,
            caster=caster,
            casting=casting,
        )
        if agent_id not in self.enemy_ids:
            self.enemy_ids.append(agent_id)
        self.target_allowed[agent_id] = targetable


@contextmanager
def _loaded_module() -> Iterator[Any]:
    owned_names = tuple(
        name
        for name in sys.modules
        if (
            name == "Py4GWCoreLib"
            or name.startswith("Py4GWCoreLib.")
            or name in {MODULE_NAME, "PySystem", "PyAgentEvents"}
        )
    )
    original = {name: sys.modules[name] for name in owned_names}
    try:
        for name in owned_names:
            sys.modules.pop(name, None)
        root_package: Any = types.ModuleType("Py4GWCoreLib")
        root_package.__path__ = [str(ROOT / "Py4GWCoreLib")]
        root_package.Profession = _Profession
        sys.modules["Py4GWCoreLib"] = root_package

        build_mgr_module: Any = types.ModuleType("Py4GWCoreLib.BuildMgr")
        build_mgr_module.BuildMgr = _FakeBuildMgr
        sys.modules["Py4GWCoreLib.BuildMgr"] = build_mgr_module

        module_spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
        assert module_spec is not None and module_spec.loader is not None
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[MODULE_NAME] = module
        module_spec.loader.exec_module(module)
        yield module
    finally:
        for name in tuple(sys.modules):
            if (
                name == "Py4GWCoreLib"
                or name.startswith("Py4GWCoreLib.")
                or name in {MODULE_NAME, "PySystem", "PyAgentEvents"}
            ):
                sys.modules.pop(name, None)
        sys.modules.update(original)


@contextmanager
def _loaded_agent() -> Iterator[Any]:
    with _loaded_module():
        dependency_packages = (
            "Py4GWCoreLib.py4gwcorelib_src",
            "Py4GWCoreLib.native_src",
            "Py4GWCoreLib.native_src.context",
            "Py4GWCoreLib.native_src.internals",
        )
        for package_name in dependency_packages:
            package = types.ModuleType(package_name)
            package.__path__ = []
            sys.modules[package_name] = package

        def _frame_cache(**_kwargs: Any) -> Any:
            return lambda function: function

        frame_cache_module = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.FrameCache")
        setattr(frame_cache_module, "frame_cache", _frame_cache)
        sys.modules[frame_cache_module.__name__] = frame_cache_module

        agent_context_module = types.ModuleType("Py4GWCoreLib.native_src.context.AgentContext")
        for name in ("AgentStruct", "AgentLivingStruct", "AgentItemStruct", "AgentGadgetStruct"):
            setattr(agent_context_module, name, type(name, (), {}))
        sys.modules[agent_context_module.__name__] = agent_context_module

        world_context_module = types.ModuleType("Py4GWCoreLib.native_src.context.WorldContext")
        setattr(world_context_module, "AttributeStruct", type("AttributeStruct", (), {}))
        setattr(world_context_module, "NPC_ModelStruct", type("NPC_ModelStruct", (), {}))
        sys.modules[world_context_module.__name__] = world_context_module

        gw_array_module = types.ModuleType("Py4GWCoreLib.native_src.internals.gw_array")
        setattr(gw_array_module, "GW_Array_Value_View", type("GW_Array_Value_View", (), {}))
        sys.modules[gw_array_module.__name__] = gw_array_module

        helpers_module = types.ModuleType("Py4GWCoreLib.native_src.internals.helpers")
        setattr(helpers_module, "encoded_wstr_to_str", lambda value: value)
        sys.modules[helpers_module.__name__] = helpers_module

        string_table_module = types.ModuleType("Py4GWCoreLib.native_src.internals.string_table")
        setattr(string_table_module, "decode", lambda value: value)
        sys.modules[string_table_module.__name__] = string_table_module

        callback_module = types.ModuleType("PyCallback")
        setattr(callback_module, "Phase", types.SimpleNamespace(PreUpdate=object()))
        setattr(callback_module, "PyCallback", types.SimpleNamespace(Register=lambda *_args, **_kwargs: None))

        sentinel = object()
        original_pyagent = sys.modules.get("PyAgent", sentinel)
        original_pycallback = sys.modules.get("PyCallback", sentinel)
        sys.modules["PyAgent"] = types.ModuleType("PyAgent")
        sys.modules["PyCallback"] = callback_module
        try:
            module_spec = importlib.util.spec_from_file_location(AGENT_MODULE_NAME, AGENT_MODULE_PATH)
            assert module_spec is not None and module_spec.loader is not None
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[AGENT_MODULE_NAME] = module
            module_spec.loader.exec_module(module)
            yield module
        finally:
            if original_pyagent is sentinel:
                sys.modules.pop("PyAgent", None)
            else:
                assert isinstance(original_pyagent, types.ModuleType)
                sys.modules["PyAgent"] = original_pyagent
            if original_pycallback is sentinel:
                sys.modules.pop("PyCallback", None)
            else:
                assert isinstance(original_pycallback, types.ModuleType)
                sys.modules["PyCallback"] = original_pycallback


@contextmanager
def _loaded_runtime() -> Iterator[tuple[Any, _Runtime]]:
    with _loaded_module() as module:
        runtime = _Runtime()
        root_package: Any = sys.modules["Py4GWCoreLib"]

        root_package.Map = types.SimpleNamespace(
            IsMapReady=lambda: True,
            IsExplorable=lambda: True,
            IsInCinematic=lambda: False,
            GetMapID=lambda: runtime.map_id,
            GetInstanceUptime=lambda: runtime.instance_uptime,
        )
        root_package.Player = types.SimpleNamespace(
            GetAgentID=lambda: runtime.player_id,
            GetXY=lambda: runtime.player_xy,
            GetAccountEmail=lambda: "smart-panic-test",
        )

        def _state(agent_id: int) -> Any:
            return runtime.states.get(int(agent_id))

        def _is_spirit(agent_id: int) -> Any:
            runtime.is_spirit_calls += 1
            state = _state(agent_id)
            if not bool(getattr(state, "agent_is_spirit_available", False)):
                raise RuntimeError("IsSpirit unavailable")
            return getattr(state, "agent_is_spirit", False)

        def _get_npc_flags(agent_id: int) -> Any:
            runtime.legacy_npc_flags_calls += 1
            state = _state(agent_id)
            return getattr(state, "npc_flags", 0) if bool(getattr(state, "npc_flags_available", False)) else 0

        def _get_npc_flags_optional(agent_id: int) -> Any:
            runtime.optional_npc_flags_calls += 1
            state = _state(agent_id)
            if not bool(getattr(state, "npc_flags_available", False)):
                return None
            return getattr(state, "npc_flags", 0)

        def _is_spawned(agent_id: int) -> bool:
            runtime.is_spawned_calls += 1
            return bool(getattr(_state(agent_id), "spawned", False))

        root_package.Agent = types.SimpleNamespace(
            IsValid=lambda agent_id: bool(getattr(_state(agent_id), "valid", False)),
            IsLiving=lambda agent_id: bool(getattr(_state(agent_id), "living", False)),
            IsAlive=lambda agent_id: bool(getattr(_state(agent_id), "alive", False)),
            IsDead=lambda agent_id: not bool(getattr(_state(agent_id), "alive", False)),
            IsKnockedDown=lambda _agent_id: False,
            IsCasting=lambda agent_id: bool(getattr(_state(agent_id), "casting", False)),
            IsCaster=lambda agent_id: bool(getattr(_state(agent_id), "caster", False)),
            IsSpirit=_is_spirit,
            IsSpawned=_is_spawned,
            GetNPCFlags=_get_npc_flags,
            GetNPCFlagsOptional=_get_npc_flags_optional,
            GetXY=lambda agent_id: getattr(_state(agent_id), "position", None),
            GetAllegiance=lambda agent_id: (
                (_Allegiance.Enemy.value, "Enemy")
                if bool(getattr(_state(agent_id), "hostile", False))
                else (_Allegiance.Ally.value, "Ally")
            ),
            GetAttributes=lambda agent_id: list(runtime.attributes.get(int(agent_id), [])),
        )
        root_package.AgentArray = types.SimpleNamespace(GetEnemyArray=lambda: list(runtime.enemy_ids))
        root_package.Range = types.SimpleNamespace(
            Spellcast=types.SimpleNamespace(value=100.0),
            Nearby=types.SimpleNamespace(value=10.0),
        )
        root_package.SkillBar = types.SimpleNamespace(
            GetSkillIDBySlot=lambda slot: runtime.bar[int(slot) - 1],
            GetCasting=lambda: 0,
            GetSkillData=lambda _slot: types.SimpleNamespace(recharge=0.0 if runtime.skill_ready else 1.0),
        )
        root_package.Routines = types.SimpleNamespace(
            Checks=types.SimpleNamespace(
                Map=types.SimpleNamespace(MapValid=lambda: True),
                Player=types.SimpleNamespace(CanAct=lambda: True),
                Skills=types.SimpleNamespace(
                    CanCast=lambda: runtime.skill_ready,
                    HasEnoughEnergy=lambda *_args: True,
                    IsSkillSlotReady=lambda _slot: runtime.skill_ready,
                ),
                Agents=types.SimpleNamespace(
                    HasEffect=lambda agent_id, skill_id: int(skill_id) == 52 and int(agent_id) in runtime.panic_ids,
                ),
            )
        )
        root_package.GLOBAL_CACHE = types.SimpleNamespace(
            Skill=types.SimpleNamespace(
                Data=types.SimpleNamespace(
                    GetAoERange=lambda _skill_id: 10.0,
                    GetActivation=lambda _skill_id: 1.0,
                    GetAftercast=lambda _skill_id: 0.25,
                )
            ),
            SkillBar=root_package.SkillBar,
            Effects=types.SimpleNamespace(
                HasEffect=lambda agent_id, skill_id: int(skill_id) == 52 and int(agent_id) in runtime.panic_ids,
                GetEffects=lambda agent_id: (
                    [types.SimpleNamespace(skill_id=52)] if int(agent_id) in runtime.panic_ids else []
                ),
                GetBuffs=lambda _agent_id: [],
            ),
            ShMem=types.SimpleNamespace(
                GetHeroAIOptionsFromEmail=lambda _email: types.SimpleNamespace(Combat=True, Skills=[True] * 8),
            ),
        )

        skill_module: Any = types.ModuleType("Py4GWCoreLib.Skill")
        skill_module.Skill = types.SimpleNamespace(GetProgressionData=lambda _skill_id: runtime.progression_data)
        sys.modules[skill_module.__name__] = skill_module

        enums_package: Any = types.ModuleType("Py4GWCoreLib.enums_src")
        enums_package.__path__ = []
        sys.modules["Py4GWCoreLib.enums_src"] = enums_package
        game_data_module: Any = types.ModuleType("Py4GWCoreLib.enums_src.GameData_enums")
        game_data_module.Allegiance = _Allegiance
        sys.modules["Py4GWCoreLib.enums_src.GameData_enums"] = game_data_module
        event_module: Any = types.ModuleType("PyAgentEvents")
        event_module.peek_events = lambda: list(runtime.events)
        sys.modules["PyAgentEvents"] = event_module
        sys.modules["PySystem"] = cast(Any, types.SimpleNamespace(get_tick_count64=lambda: runtime.now_ms))
        yield module, runtime


def _observation(module: Any, agent_id: int, x: float, *, distance: float = 10.0, **kwargs: Any) -> Any:
    kwargs.setdefault("agent_is_spirit", False)
    kwargs.setdefault("npc_flags", 0)
    return module.PanicTargetObservation(
        agent_id=agent_id,
        x=x,
        y=0.0,
        distance_from_player=distance,
        **kwargs,
    )


def _policy(module: Any, *, radius: float = 10.0, cast_range: float = 100.0) -> Any:
    return module.PanicPolicy(cast_range=cast_range, effect_radius=radius)


def _drain(generator: Any) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as finished:
            return finished.value


def _new_handler(module: Any, runtime: _Runtime) -> Any:
    handler = module.SmartPanic()
    handler._test_runtime = runtime
    handler.set_skill_slot(1)
    handler.update_lifecycle(0)
    return handler


def _event(timestamp: int, event_type: int, *, agent_id: int = 1, value: int = 52, target_id: int = 0) -> Any:
    return types.SimpleNamespace(
        timestamp=timestamp,
        event_type=event_type,
        agent_id=agent_id,
        value=value,
        target_id=target_id,
        float_value=0.0,
    )


def _complete_receipt(handler: Any, runtime: _Runtime, *, finish: bool = True) -> None:
    receipt = handler._pending_receipt
    assert receipt is not None
    activation_timestamp = receipt.dispatch_timestamp_ms + 1
    finish_timestamp = activation_timestamp + 1
    runtime.events.append(
        _event(
            activation_timestamp,
            1,
            agent_id=receipt.player_agent_id,
            value=52,
            target_id=receipt.target_agent_id,
        )
    )
    if finish:
        runtime.events.append(
            _event(
                finish_timestamp,
                4,
                agent_id=receipt.player_agent_id,
                value=52,
                target_id=receipt.target_agent_id,
            )
        )
        runtime.now_ms = finish_timestamp
        handler.update_lifecycle(0)


def test_agent_optional_npc_flags_preserves_zero_nonzero_and_missing_model() -> None:
    with _loaded_agent() as agent_module:
        living_by_agent = {
            1: types.SimpleNamespace(is_player=False, player_number=10),
            2: types.SimpleNamespace(is_player=False, player_number=20),
            3: types.SimpleNamespace(is_player=False, player_number=30),
            4: types.SimpleNamespace(is_player=True, player_number=40),
        }
        npc_by_model = {
            10: types.SimpleNamespace(npc_flags=0),
            20: types.SimpleNamespace(npc_flags=0x4000),
        }
        agent_module.Agent.GetLivingAgentByID = staticmethod(living_by_agent.get)
        agent_module.Agent.GetNPCModelByID = staticmethod(npc_by_model.get)

        assert agent_module.Agent.GetNPCFlagsOptional(1) == 0
        assert agent_module.Agent.GetNPCFlagsOptional(2) == 0x4000
        assert agent_module.Agent.GetNPCFlagsOptional(3) is None
        assert agent_module.Agent.GetNPCFlagsOptional(4) is None
        assert agent_module.Agent.GetNPCFlags(3) == 0


def test_lone_and_two_enemy_clusters_are_rejected() -> None:
    with _loaded_module() as module:
        policy = _policy(module)
        for observations in (
            [_observation(module, 1, 0.0)],
            [_observation(module, 1, 0.0), _observation(module, 2, 3.0)],
        ):
            decision = module.evaluate_smart_panic(observations, policy=policy)
            assert decision.selected is None


def test_exactly_three_and_larger_direct_clusters_are_accepted() -> None:
    with _loaded_module() as module:
        policy = _policy(module)
        exact = module.evaluate_smart_panic(
            [_observation(module, 1, 0.0), _observation(module, 2, 3.0), _observation(module, 3, 6.0)],
            policy=policy,
        )
        larger = module.evaluate_smart_panic(
            [
                _observation(module, 10, 100.0),
                _observation(module, 11, 103.0),
                _observation(module, 12, 106.0),
                _observation(module, 13, 109.0),
            ],
            policy=policy,
        )
        assert exact.admitted and exact.selected is not None
        assert exact.selected.affected_count == 3
        assert larger.admitted and larger.selected is not None
        assert larger.selected.affected_count == 4


def test_two_ordinary_enemies_plus_enemy_allegiance_spirit_are_rejected() -> None:
    with _loaded_module() as module:
        decision = module.evaluate_smart_panic(
            [
                _observation(module, 288, 0.0),
                _observation(module, 289, 3.0),
                _observation(module, 166, 6.0, agent_is_spirit=False, npc_flags=module.NPC_SPIRIT_FLAG),
            ],
            policy=_policy(module),
        )

        center = next(item for item in decision.candidates if item.target_agent_id == 288)
        assert center.affected_agent_ids == (288, 289)
        assert center.affected_count == 2
        assert center.reason is module.CandidateReason.BELOW_MINIMUM_AFFECTED
        assert decision.selected is None


def test_spirit_classifier_preserves_tri_state_and_known_zero_flags() -> None:
    with _loaded_module() as module:
        known_zero = _observation(module, 1, 0.0, agent_is_spirit=False, npc_flags=0)
        flagged_spirit = _observation(module, 2, 3.0, agent_is_spirit=False, npc_flags=module.NPC_SPIRIT_FLAG)
        primary_spirit = _observation(module, 3, 6.0, agent_is_spirit=True, npc_flags=None)
        unknown_flags = _observation(module, 4, 9.0, agent_is_spirit=False, npc_flags=None)
        unknown_clear = _observation(module, 5, 12.0, agent_is_spirit=None, npc_flags=0)
        unknown_positive = _observation(module, 6, 15.0, agent_is_spirit=None, npc_flags=module.NPC_SPIRIT_FLAG)

        assert module.classify_panic_spirit(known_zero) is module.PanicSpiritClassification.CONFIRMED_NOT_SPIRIT
        assert module.classify_panic_spirit(flagged_spirit) is module.PanicSpiritClassification.CONFIRMED_SPIRIT
        assert module.classify_panic_spirit(primary_spirit) is module.PanicSpiritClassification.CONFIRMED_SPIRIT
        assert module.classify_panic_spirit(unknown_flags) is module.PanicSpiritClassification.UNKNOWN
        assert module.classify_panic_spirit(unknown_clear) is module.PanicSpiritClassification.UNKNOWN
        assert module.classify_panic_spirit(unknown_positive) is module.PanicSpiritClassification.CONFIRMED_SPIRIT


def test_three_confirmed_members_plus_unknown_member_remain_eligible() -> None:
    with _loaded_module() as module:
        decision = module.evaluate_smart_panic(
            [
                _observation(module, 1, 0.0),
                _observation(module, 2, 3.0),
                _observation(module, 3, 6.0),
                _observation(module, 4, 9.0, agent_is_spirit=False, npc_flags=None),
            ],
            policy=_policy(module),
        )

        selected = decision.selected
        assert selected is not None
        assert selected.affected_agent_ids == (1, 2, 3)
        assert selected.affected_count == 3


def test_spirit_filter_propagates_through_counts_and_candidate_ranking() -> None:
    with _loaded_module() as module:
        decision = module.evaluate_smart_panic(
            [
                _observation(module, 1, 0.0),
                _observation(module, 2, 3.0),
                _observation(module, 3, 6.0),
                _observation(
                    module,
                    4,
                    9.0,
                    agent_is_spirit=False,
                    npc_flags=module.NPC_SPIRIT_FLAG,
                    is_caster=True,
                    is_casting=True,
                ),
                _observation(module, 10, 100.0, is_caster=True),
                _observation(module, 11, 103.0),
                _observation(module, 12, 106.0),
            ],
            policy=_policy(module),
        )

        filtered_first = next(item for item in decision.candidates if item.target_agent_id == 1)
        assert filtered_first.affected_agent_ids == (1, 2, 3)
        assert filtered_first.uncovered_affected_agent_ids == (1, 2, 3)
        assert filtered_first.caster_support_count == 0
        assert filtered_first.casting_count == 0
        assert decision.selected is not None
        assert decision.selected.target_agent_id == 10


def test_invalid_dead_and_outside_direct_radius_enemies_do_not_count() -> None:
    with _loaded_module() as module:
        observations = [
            _observation(module, 1, 0.0),
            _observation(module, 2, 3.0),
            _observation(module, 3, 30.0),
            _observation(module, 4, 4.0, is_alive=False),
            _observation(module, 5, 5.0, is_valid=False),
        ]
        decision = module.evaluate_smart_panic(observations, policy=_policy(module))
        assert decision.selected is None
        assert any(
            candidate.reason is module.CandidateReason.BELOW_MINIMUM_AFFECTED for candidate in decision.candidates
        )

        out_of_range = module.evaluate_smart_panic(
            [_observation(module, 1, 0.0, distance=101.0), _observation(module, 2, 3.0), _observation(module, 3, 6.0)],
            policy=_policy(module),
        )
        candidate = next(item for item in out_of_range.candidates if item.target_agent_id == 1)
        assert candidate.reason is module.CandidateReason.OUT_OF_CAST_RANGE
        assert out_of_range.selected is not None
        assert out_of_range.selected.target_agent_id == 2


def test_direct_radius_does_not_use_connected_component_membership() -> None:
    with _loaded_module() as module:
        observations = [
            _observation(module, 1, 0.0),
            _observation(module, 2, 9.0),
            _observation(module, 3, 18.0),
        ]
        decision = module.evaluate_smart_panic(observations, policy=_policy(module, radius=10.0))
        center = next(item for item in decision.candidates if item.target_agent_id == 1)
        assert center.affected_agent_ids == (1, 2)
        assert not center.eligible


def test_runtime_non_targetable_neighbor_still_counts_and_survives_final_revalidation() -> None:
    with _loaded_runtime() as (module, runtime):
        for agent_id, x in ((1, 0.0), (2, 3.0), (3, 6.0)):
            runtime.add_enemy(agent_id, x=x)
        runtime.target_allowed[3] = False
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        neighbor = next(observation for observation in snapshot if observation.agent_id == 3)
        assert neighbor.is_targetable is False

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is not None
        assert decision.selected.target_agent_id == 1
        assert decision.selected.affected_agent_ids == (1, 2, 3)
        assert _drain(handler._dispatch_selected(1, parameters)) is True
        assert runtime.cast_calls == [(52, 1)]


def test_runtime_non_targetable_center_is_rejected() -> None:
    with _loaded_runtime() as (module, runtime):
        for agent_id, x in ((1, 0.0), (2, 8.0), (3, -8.0)):
            runtime.add_enemy(agent_id, x=x)
        runtime.target_allowed[1] = False
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None
        rejected = next(candidate for candidate in decision.candidates if candidate.target_agent_id == 1)
        assert rejected.reason is module.CandidateReason.INVALID_TARGET


def test_runtime_enemy_allegiance_spirit_is_filtered_from_snapshot_membership() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(288, x=0.0)
        runtime.add_enemy(289, x=3.0)
        runtime.add_enemy(166, x=6.0, agent_is_spirit=False, npc_flags=module.NPC_SPIRIT_FLAG)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        spirit = next(observation for observation in snapshot if observation.agent_id == 166)
        assert spirit.agent_is_spirit is False
        assert spirit.npc_flags == module.NPC_SPIRIT_FLAG

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None
        center = next(item for item in decision.candidates if item.target_agent_id == 288)
        assert center.affected_agent_ids == (288, 289)
        assert center.affected_count == 2


def test_runtime_positive_agent_spirit_is_sufficient_when_npc_flags_are_unavailable() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0)
        runtime.add_enemy(2, x=3.0)
        runtime.add_enemy(3, x=6.0, agent_is_spirit=True, npc_flags_available=False)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        spirit = next(observation for observation in snapshot if observation.agent_id == 3)
        assert spirit.agent_is_spirit is True
        assert spirit.npc_flags is None
        assert module.classify_panic_spirit(spirit) is module.PanicSpiritClassification.CONFIRMED_SPIRIT

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None


def test_runtime_unknown_agent_spirit_with_known_clear_flags_is_unknown() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0)
        runtime.add_enemy(2, x=3.0)
        runtime.add_enemy(3, x=6.0, agent_is_spirit=None, npc_flags=0)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        unknown = next(observation for observation in snapshot if observation.agent_id == 3)
        assert unknown.agent_is_spirit is None
        assert unknown.npc_flags == 0
        assert module.classify_panic_spirit(unknown) is module.PanicSpiritClassification.UNKNOWN
        assert runtime.legacy_npc_flags_calls == 0

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None
        center = next(item for item in decision.candidates if item.target_agent_id == 1)
        assert center.affected_agent_ids == (1, 2)
        assert center.reason is module.CandidateReason.MISSING_EVIDENCE


def test_runtime_unavailable_agent_spirit_and_flags_are_unknown_without_crashing() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0)
        runtime.add_enemy(2, x=3.0)
        runtime.add_enemy(
            3,
            x=6.0,
            agent_is_spirit=False,
            agent_is_spirit_available=False,
            npc_flags_available=False,
        )
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        unknown = next(observation for observation in snapshot if observation.agent_id == 3)
        assert unknown.agent_is_spirit is None
        assert unknown.npc_flags is None
        assert module.classify_panic_spirit(unknown) is module.PanicSpiritClassification.UNKNOWN

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None


def test_runtime_unknown_agent_spirit_with_positive_npc_flag_is_excluded() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0)
        runtime.add_enemy(2, x=3.0)
        runtime.add_enemy(3, x=6.0, agent_is_spirit=None, npc_flags=module.NPC_SPIRIT_FLAG)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        spirit = next(observation for observation in snapshot if observation.agent_id == 3)
        assert spirit.agent_is_spirit is None
        assert spirit.npc_flags == module.NPC_SPIRIT_FLAG
        assert module.classify_panic_spirit(spirit) is module.PanicSpiritClassification.CONFIRMED_SPIRIT

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None


def test_runtime_unavailable_npc_flags_are_unknown_and_do_not_count() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0)
        runtime.add_enemy(2, x=3.0)
        runtime.add_enemy(3, x=6.0, agent_is_spirit=False, npc_flags_available=False)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        unknown = next(observation for observation in snapshot if observation.agent_id == 3)
        assert unknown.agent_is_spirit is False
        assert unknown.npc_flags is None
        assert module.classify_panic_spirit(unknown) is module.PanicSpiritClassification.UNKNOWN

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None
        center = next(item for item in decision.candidates if item.target_agent_id == 1)
        assert center.affected_agent_ids == (1, 2)
        assert center.reason is module.CandidateReason.MISSING_EVIDENCE


def test_runtime_known_zero_flags_count_and_spawned_minion_does_not_use_spawn_state() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0)
        runtime.add_enemy(2, x=3.0, npc_flags=0)
        runtime.add_enemy(3, x=6.0, spawned=True, npc_flags=0x0100, agent_is_spirit=False)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        zero_flags = next(observation for observation in snapshot if observation.agent_id == 2)
        spawned_minion = next(observation for observation in snapshot if observation.agent_id == 3)
        assert zero_flags.npc_flags == 0
        assert module.classify_panic_spirit(zero_flags) is module.PanicSpiritClassification.CONFIRMED_NOT_SPIRIT
        assert spawned_minion.npc_flags == 0x0100
        assert module.classify_panic_spirit(spawned_minion) is module.PanicSpiritClassification.CONFIRMED_NOT_SPIRIT
        assert runtime.is_spawned_calls == 0

        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is not None
        assert decision.selected.affected_agent_ids == (1, 2, 3)


def test_runtime_spirit_center_remains_rejected_by_direct_target_validation() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0, targetable=False, agent_is_spirit=True, npc_flags_available=False)
        runtime.add_enemy(2, x=3.0)
        runtime.add_enemy(3, x=6.0)
        runtime.add_enemy(4, x=9.0)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None

        decision = handler._evaluate_live(parameters)
        assert decision is not None
        rejected = next(candidate for candidate in decision.candidates if candidate.target_agent_id == 1)
        assert rejected.reason is module.CandidateReason.INVALID_TARGET


def test_center_panic_is_rejected_and_nearby_panic_reduces_freshness() -> None:
    with _loaded_module() as module:
        center_panicked = module.evaluate_smart_panic(
            [
                _observation(module, 1, 0.0, has_panic=True),
                _observation(module, 2, 3.0),
                _observation(module, 3, 6.0),
            ],
            policy=_policy(module),
        )
        rejected = next(item for item in center_panicked.candidates if item.target_agent_id == 1)
        assert rejected.reason is module.CandidateReason.CENTER_ALREADY_PANICKED

        nearby_panicked = module.evaluate_smart_panic(
            [
                _observation(module, 1, 0.0),
                _observation(module, 2, 3.0, has_panic=True),
                _observation(module, 3, 6.0),
            ],
            policy=_policy(module),
        )
        selected = nearby_panicked.selected
        assert selected is not None
        assert selected.affected_count == 3
        assert selected.uncovered_count == 2


def test_fresh_count_outranks_total_count_and_total_outranks_caster_signal() -> None:
    with _loaded_module() as module:
        observations = [
            _observation(module, 1, 0.0),
            _observation(module, 2, 3.0),
            _observation(module, 3, 6.0),
            _observation(module, 10, 100.0),
            _observation(module, 11, 103.0, has_panic=True),
            _observation(module, 12, 106.0, has_panic=True),
            _observation(module, 13, 109.0, is_caster=True),
        ]
        decision = module.evaluate_smart_panic(observations, policy=_policy(module))
        assert decision.selected is not None
        assert decision.selected.target_agent_id == 1

        equal_fresh = module.evaluate_smart_panic(
            [
                _observation(module, 1, 0.0),
                _observation(module, 2, 3.0),
                _observation(module, 3, 6.0),
                _observation(module, 10, 100.0),
                _observation(module, 11, 103.0),
                _observation(module, 12, 106.0),
                _observation(module, 13, 109.0, is_caster=True),
            ],
            policy=_policy(module),
        )
        assert equal_fresh.selected is not None
        assert equal_fresh.selected.target_agent_id == 10


def test_caster_and_casting_evidence_are_soft_and_casting_is_not_primary() -> None:
    with _loaded_module() as module:
        observations = [
            _observation(module, 1, 0.0, is_caster=None, is_casting=True),
            _observation(module, 2, 3.0, is_caster=None),
            _observation(module, 3, 6.0, is_caster=None),
            _observation(module, 10, 100.0, is_caster=True),
            _observation(module, 11, 103.0),
            _observation(module, 12, 106.0),
            _observation(module, 13, 109.0),
        ]
        decision = module.evaluate_smart_panic(observations, policy=_policy(module))
        assert decision.selected is not None
        assert decision.selected.target_agent_id == 10


def test_distance_then_agent_id_break_final_ties() -> None:
    with _loaded_module() as module:
        observations = [
            _observation(module, 10, 0.0, distance=20.0),
            _observation(module, 11, 3.0, distance=20.0),
            _observation(module, 12, 6.0, distance=20.0),
            _observation(module, 20, 100.0, distance=10.0),
            _observation(module, 21, 103.0, distance=10.0),
            _observation(module, 22, 106.0, distance=10.0),
        ]
        decision = module.evaluate_smart_panic(observations, policy=_policy(module))
        assert decision.selected is not None
        assert decision.selected.target_agent_id == 20

        same_distance = module.evaluate_smart_panic(
            [
                _observation(module, 10, 0.0, distance=10.0),
                _observation(module, 11, 3.0, distance=10.0),
                _observation(module, 12, 6.0, distance=10.0),
                _observation(module, 20, 100.0, distance=10.0),
                _observation(module, 21, 103.0, distance=10.0),
                _observation(module, 22, 106.0, distance=10.0),
            ],
            policy=_policy(module),
        )
        assert same_distance.selected is not None
        assert same_distance.selected.target_agent_id == 10


def test_pending_recent_and_materially_different_group_suppression() -> None:
    with _loaded_runtime() as (module, runtime):
        for agent_id, x in ((1, 0.0), (2, 3.0), (3, 6.0)):
            runtime.add_enemy(agent_id, x=x)
        handler = _new_handler(module, runtime)

        handler._pending_local_attempt = (1, handler._lifecycle_id)
        assert _drain(handler.try_cast()) is False
        assert runtime.cast_calls == []

        handler._pending_local_attempt = None
        assert _drain(handler.try_cast()) is True
        assert len(runtime.cast_calls) == 1
        _complete_receipt(handler, runtime)
        assert _drain(handler.try_cast()) is False
        assert handler._pending_receipt is None
        assert _drain(handler.try_cast()) is False
        assert len(runtime.cast_calls) == 1

        runtime.enemy_ids[:] = [10, 11, 12]
        for agent_id, x in ((10, 50.0), (11, 53.0), (12, 56.0)):
            runtime.add_enemy(agent_id, x=x)
        assert _drain(handler.try_cast()) is True
        assert len(runtime.cast_calls) == 2


def test_recent_group_signature_and_overlap_ignore_filtered_spirit() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.add_enemy(1, x=0.0)
        runtime.add_enemy(2, x=3.0)
        runtime.add_enemy(3, x=6.0)
        runtime.add_enemy(4, x=9.0, agent_is_spirit=False, npc_flags=module.NPC_SPIRIT_FLAG)
        handler = _new_handler(module, runtime)
        assert _drain(handler.try_cast()) is True
        assert handler._recent_group is not None
        assert handler._recent_group.agent_ids == frozenset({1, 2, 3})

        runtime.enemy_ids[:] = [1, 2, 4, 5]
        runtime.add_enemy(5, x=9.0)
        runtime.panic_ids.update((1, 2, 4))
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is not None
        assert decision.selected.target_agent_id == 5
        assert decision.selected.affected_agent_ids == (1, 2, 5)
        assert handler._recent_group_is_wasteful(decision.selected, runtime.now_ms) is False


def test_lifecycle_reset_clears_recent_group_memory() -> None:
    with _loaded_runtime() as (module, runtime):
        for agent_id, x in ((1, 0.0), (2, 3.0), (3, 6.0)):
            runtime.add_enemy(agent_id, x=x)
        handler = _new_handler(module, runtime)
        assert _drain(handler.try_cast()) is True
        assert _drain(handler.try_cast()) is False

        runtime.map_id = 2
        assert _drain(handler.try_cast()) is True
        assert len(runtime.cast_calls) == 2


def test_current_panic_effect_observation_prevents_redundant_center_recast() -> None:
    with _loaded_runtime() as (module, runtime):
        for agent_id, x in ((1, 0.0), (2, 3.0), (3, 6.0)):
            runtime.add_enemy(agent_id, x=x)
        runtime.panic_ids.update((1, 2, 3))
        handler = _new_handler(module, runtime)
        assert _drain(handler.try_cast()) is False
        assert runtime.cast_calls == []


def test_final_revalidation_rejects_stale_proposals() -> None:
    mutations = (
        lambda runtime: setattr(runtime.states[2], "alive", False),
        lambda runtime: setattr(runtime.states[1], "position", (200.0, 0.0)),
        lambda runtime: runtime.panic_ids.add(1),
        lambda runtime: setattr(runtime, "skill_ready", False),
        lambda runtime: setattr(runtime.states[2], "npc_flags", 0x4000),
        lambda runtime: setattr(runtime.states[2], "npc_flags_available", False),
    )
    for mutation in mutations:
        with _loaded_runtime() as (module, runtime):
            for agent_id, x in ((1, 0.0), (2, 3.0), (3, 6.0)):
                runtime.add_enemy(agent_id, x=x)
            handler = _new_handler(module, runtime)
            parameters = handler._resolve_runtime_parameters()
            assert parameters is not None
            decision = handler._evaluate_live(parameters)
            assert decision is not None and decision.selected is not None

            mutation(runtime)
            assert _drain(handler._dispatch_selected(decision.selected.target_agent_id, parameters)) is False
            assert runtime.cast_calls == []


def _add_three_enemy_cluster(runtime: _Runtime, start: int = 1, x: float = 0.0) -> None:
    for offset in range(3):
        runtime.add_enemy(start + offset, x=x + offset * 3.0)


def _cast_three_enemy_cluster(module: Any, runtime: _Runtime) -> Any:
    _add_three_enemy_cluster(runtime)
    handler = _new_handler(module, runtime)
    assert _drain(handler.try_cast()) is True
    assert handler._pending_receipt is not None
    return handler


def _advance_to(runtime: _Runtime, timestamp: int) -> None:
    runtime.now_ms = timestamp


def test_cast_skill_id_false_creates_no_receipt_or_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        runtime.cast_result = False
        handler = _new_handler(module, runtime)
        assert _drain(handler.try_cast()) is False
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_accepted_cast_without_activation_creates_no_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        _advance_to(runtime, receipt.receipt_deadline_ms + 1)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_stale_pre_dispatch_activation_is_not_a_receipt() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        runtime.events.append(_event(999, 1, target_id=1))
        handler = _new_handler(module, runtime)
        assert _drain(handler.try_cast()) is True
        _advance_to(runtime, 1001)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is not None
        assert handler._pending_receipt.activation_timestamp_ms is None
        assert handler._coverage_expiry_by_agent == {}


def test_wrong_player_activation_is_ignored() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        runtime.events.append(_event(receipt.dispatch_timestamp_ms + 1, 1, agent_id=99, target_id=1))
        _advance_to(runtime, receipt.dispatch_timestamp_ms + 1)
        handler.update_lifecycle(0)
        assert receipt.activation_timestamp_ms is None
        assert handler._coverage_expiry_by_agent == {}


def test_wrong_skill_activation_invalidates_receipt() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        runtime.events.append(_event(receipt.dispatch_timestamp_ms + 1, 1, value=53, target_id=receipt.target_agent_id))
        _advance_to(runtime, receipt.dispatch_timestamp_ms + 1)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_wrong_target_activation_invalidates_receipt() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        runtime.events.append(_event(receipt.dispatch_timestamp_ms + 1, 1, target_id=99))
        _advance_to(runtime, receipt.dispatch_timestamp_ms + 1)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_correct_activation_arms_receipt_without_granting_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        activation_timestamp = receipt.dispatch_timestamp_ms + 1
        runtime.events.append(
            _event(
                activation_timestamp,
                1,
                agent_id=receipt.player_agent_id,
                target_id=receipt.target_agent_id,
            )
        )
        _advance_to(runtime, activation_timestamp)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is receipt
        assert receipt.activation_timestamp_ms == activation_timestamp
        assert handler._coverage_expiry_by_agent == {}


def test_generic_finish_before_activation_grants_no_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        finish_timestamp = receipt.dispatch_timestamp_ms + 1
        runtime.events.append(_event(finish_timestamp, 4, target_id=receipt.target_agent_id))
        _advance_to(runtime, finish_timestamp)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_activation_and_finish_create_coverage_for_final_group() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert set(handler._coverage_expiry_by_agent) == {1, 2, 3}


def test_stop_event_invalidates_receipt_without_coverage() -> None:
    for event_type in (3, 6):
        with _loaded_runtime() as (module, runtime):
            handler = _cast_three_enemy_cluster(module, runtime)
            receipt = handler._pending_receipt
            assert receipt is not None
            timestamp = receipt.dispatch_timestamp_ms + 1
            runtime.events.append(_event(timestamp, event_type, target_id=receipt.target_agent_id))
            _advance_to(runtime, timestamp)
            handler.update_lifecycle(0)
            assert handler._pending_receipt is None
            assert handler._coverage_expiry_by_agent == {}


def test_receipt_timeout_grants_no_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        _advance_to(runtime, receipt.receipt_deadline_ms + 1)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_conflicting_newer_activation_invalidates_armed_receipt() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        activation_timestamp = receipt.dispatch_timestamp_ms + 1
        runtime.events.extend(
            (
                _event(activation_timestamp, 1, target_id=receipt.target_agent_id),
                _event(activation_timestamp + 1, 1, target_id=99),
            )
        )
        _advance_to(runtime, activation_timestamp + 1)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_future_finish_is_not_deduplicated_before_later_conflicting_activation() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None

        activation_timestamp = receipt.dispatch_timestamp_ms + 1
        finish_timestamp = activation_timestamp + 1
        conflicting_timestamp = finish_timestamp + 1
        runtime.events.append(
            _event(
                activation_timestamp,
                1,
                agent_id=receipt.player_agent_id,
                value=52,
                target_id=receipt.target_agent_id,
            )
        )
        runtime.now_ms = activation_timestamp
        handler.update_lifecycle(0)
        assert receipt.activation_timestamp_ms == activation_timestamp

        runtime.events.append(
            _event(
                finish_timestamp,
                4,
                agent_id=receipt.player_agent_id,
                value=0,
                target_id=0,
            )
        )
        runtime.now_ms = activation_timestamp
        handler.update_lifecycle(0)
        assert handler._pending_receipt is receipt

        runtime.events.append(
            _event(
                conflicting_timestamp,
                1,
                agent_id=receipt.player_agent_id,
                value=53,
                target_id=99,
            )
        )
        runtime.now_ms = conflicting_timestamp
        handler.update_lifecycle(0)

        assert handler._pending_receipt is None
        assert set(handler._coverage_expiry_by_agent) == {1, 2, 3}


def test_finish_at_receipt_deadline_survives_late_poll_after_future_deferral() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None

        activation_timestamp = receipt.dispatch_timestamp_ms + 1
        deadline = receipt.receipt_deadline_ms
        assert activation_timestamp < deadline
        runtime.events.append(
            _event(
                activation_timestamp,
                1,
                agent_id=receipt.player_agent_id,
                value=52,
                target_id=receipt.target_agent_id,
            )
        )
        runtime.now_ms = activation_timestamp
        handler.update_lifecycle(0)
        assert receipt.activation_timestamp_ms == activation_timestamp

        runtime.events.append(
            _event(
                deadline,
                4,
                agent_id=receipt.player_agent_id,
                value=0,
                target_id=0,
            )
        )
        runtime.now_ms = deadline - 1
        handler.update_lifecycle(0)
        assert handler._pending_receipt is receipt

        runtime.now_ms = deadline + 1
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert set(handler._coverage_expiry_by_agent) == {1, 2, 3}


def test_finish_after_receipt_deadline_does_not_create_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None

        activation_timestamp = receipt.dispatch_timestamp_ms + 1
        finish_timestamp = receipt.receipt_deadline_ms + 1
        runtime.events.extend(
            (
                _event(
                    activation_timestamp,
                    1,
                    agent_id=receipt.player_agent_id,
                    value=52,
                    target_id=receipt.target_agent_id,
                ),
                _event(
                    finish_timestamp,
                    4,
                    agent_id=receipt.player_agent_id,
                    value=0,
                    target_id=0,
                ),
            )
        )
        runtime.now_ms = activation_timestamp
        handler.update_lifecycle(0)
        assert receipt.activation_timestamp_ms == activation_timestamp

        runtime.now_ms = finish_timestamp
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_repeated_peek_events_are_deduplicated() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        activation_timestamp = receipt.dispatch_timestamp_ms + 1
        finish_timestamp = activation_timestamp + 1
        runtime.events.extend(
            (
                _event(activation_timestamp, 1, target_id=receipt.target_agent_id),
                _event(finish_timestamp, 4, target_id=receipt.target_agent_id),
            )
        )
        _advance_to(runtime, finish_timestamp)
        handler.update_lifecycle(0)
        first_ledger = dict(handler._coverage_expiry_by_agent)
        handler.update_lifecycle(0)
        assert handler._coverage_expiry_by_agent == first_ledger


def test_receipt_replays_accepted_activation_after_general_history_turnover() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None

        activation_timestamp = receipt.dispatch_timestamp_ms + 1
        activation = _event(
            activation_timestamp,
            1,
            agent_id=receipt.player_agent_id,
            value=52,
            target_id=receipt.target_agent_id,
        )
        stale_events = [
            _event(timestamp, 7, agent_id=99, value=timestamp, target_id=timestamp)
            for timestamp in range(module.PANIC_EVENT_HISTORY_MAX)
        ]
        runtime.events.extend((*stale_events, activation))
        runtime.now_ms = activation_timestamp
        handler.update_lifecycle(0)

        activation_key = (
            activation.timestamp,
            activation.event_type,
            activation.agent_id,
            activation.value,
            activation.target_id,
            activation.float_value,
        )
        assert handler._pending_receipt is receipt
        assert receipt.activation_timestamp_ms == activation_timestamp
        assert receipt.accepted_activation_key == activation_key
        assert handler._coverage_expiry_by_agent == {}

        finish_timestamp = activation_timestamp + 1
        runtime.events.append(
            _event(
                finish_timestamp,
                4,
                agent_id=receipt.player_agent_id,
                value=0,
                target_id=0,
            )
        )
        runtime.now_ms = finish_timestamp
        handler.update_lifecycle(0)

        assert handler._pending_receipt is None
        assert set(handler._coverage_expiry_by_agent) == {1, 2, 3}


def test_old_lifecycle_event_cannot_arm_current_receipt() -> None:
    with _loaded_runtime() as (module, runtime):
        handler = _cast_three_enemy_cluster(module, runtime)
        receipt = handler._pending_receipt
        assert receipt is not None
        handler._local_generation += 1
        handler._lifecycle_id = (receipt.lifecycle_id[0], receipt.lifecycle_id[1], handler._local_generation)
        runtime.events.append(_event(receipt.dispatch_timestamp_ms + 1, 1, target_id=receipt.target_agent_id))
        _advance_to(runtime, receipt.dispatch_timestamp_ms + 1)
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_false_hostile_effect_read_is_unknown_not_direct_freshness() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        assert all(observation.has_panic is False for observation in snapshot)
        assert all(observation.panic_state is module.PanicEffectState.UNKNOWN for observation in snapshot)
        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is not None
        assert decision.selected.uncovered_count == 3


def test_empty_effect_lists_are_not_authoritative_absence() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        root_package: Any = sys.modules["Py4GWCoreLib"]
        delattr(root_package.Routines.Checks.Agents, "HasEffect")
        delattr(root_package.GLOBAL_CACHE.Effects, "HasEffect")
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        observation = next(item for item in handler._build_snapshot(parameters) or () if item.agent_id == 1)
        assert observation.has_panic is False
        assert observation.panic_state is module.PanicEffectState.UNKNOWN


def test_true_has_effect_read_is_observed_present() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        runtime.panic_ids.add(1)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        observation = next(item for item in handler._build_snapshot(parameters) or () if item.agent_id == 1)
        assert observation.has_panic is True
        assert observation.panic_state is module.PanicEffectState.OBSERVED_PRESENT
        decision = handler._evaluate_live(parameters)
        assert decision is not None
        center = next(item for item in decision.candidates if item.target_agent_id == 1)
        assert center.reason is module.CandidateReason.CENTER_ALREADY_PANICKED


def test_effect_list_entry_for_skill_52_is_observed_present() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        root_package: Any = sys.modules["Py4GWCoreLib"]
        root_package.GLOBAL_CACHE.Effects.GetEffects = lambda agent_id: (
            [types.SimpleNamespace(skill_id=52)] if int(agent_id) == 1 else []
        )
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        observation = next(item for item in handler._build_snapshot(parameters) or () if item.agent_id == 1)
        assert observation.panic_state is module.PanicEffectState.OBSERVED_PRESENT


def test_is_hexed_does_not_identify_panic() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        root_package: Any = sys.modules["Py4GWCoreLib"]
        root_package.Agent.IsHexed = lambda _agent_id: True
        delattr(root_package.Routines.Checks.Agents, "HasEffect")
        delattr(root_package.GLOBAL_CACHE.Effects, "HasEffect")
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        observation = next(item for item in handler._build_snapshot(parameters) or () if item.agent_id == 1)
        assert observation.has_panic is False
        assert observation.panic_state is module.PanicEffectState.UNKNOWN


def test_effect_event_value_52_is_not_used_as_panic_identity() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        runtime.events.append(_event(runtime.now_ms, 40, target_id=1, value=52))
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        observation = next(item for item in handler._build_snapshot(parameters) or () if item.agent_id == 1)
        assert observation.has_panic is False
        assert observation.panic_state is module.PanicEffectState.UNKNOWN


def test_completed_receipt_uses_exact_final_group_for_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        assert set(handler._coverage_expiry_by_agent) == {1, 2, 3}
        runtime.add_enemy(99, x=1.0)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        assert next(item for item in snapshot if item.agent_id == 99).panic_state is module.PanicEffectState.UNKNOWN


def test_local_coverage_blocks_center_recast() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is None
        assert all(
            candidate.reason is module.CandidateReason.CENTER_ALREADY_PANICKED for candidate in decision.candidates
        )


def test_covered_neighbors_stay_in_total_but_not_uncovered_count() -> None:
    with _loaded_module() as module:
        observations = [
            _observation(module, 1, 0.0),
            _observation(module, 2, 3.0, has_panic=True, panic_state=module.PanicEffectState.LOCALLY_COVERED),
            _observation(module, 3, 6.0, has_panic=True, panic_state=module.PanicEffectState.OBSERVED_PRESENT),
            _observation(module, 4, 9.0),
        ]
        decision = module.evaluate_smart_panic(observations, policy=_policy(module))
        assert decision.selected is not None
        assert decision.selected.affected_count == 4
        assert decision.selected.uncovered_affected_agent_ids == (1, 4)


def test_uncovered_count_outranks_total_affected_count() -> None:
    with _loaded_module() as module:
        observations = [
            _observation(module, 1, 0.0),
            _observation(module, 2, 3.0),
            _observation(module, 3, 6.0),
            _observation(module, 10, 100.0),
            _observation(module, 11, 103.0, has_panic=True),
            _observation(module, 12, 106.0, has_panic=True),
            _observation(module, 13, 109.0, has_panic=True),
        ]
        decision = module.evaluate_smart_panic(observations, policy=_policy(module))
        assert decision.selected is not None
        assert decision.selected.target_agent_id == 1
        larger = next(item for item in decision.candidates if item.target_agent_id == 10)
        assert larger.affected_count == 4
        assert larger.uncovered_count == 1


def test_second_uncovered_group_remains_eligible_after_first_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.enemy_ids[:] = [10, 11, 12]
        for agent_id, x in ((10, 50.0), (11, 53.0), (12, 56.0)):
            runtime.add_enemy(agent_id, x=x)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        decision = handler._evaluate_live(parameters)
        assert decision is not None and decision.selected is not None
        assert decision.selected.target_agent_id == 10
        assert decision.selected.uncovered_count == 3


def test_partial_local_coverage_preserves_uncovered_members() -> None:
    with _loaded_module() as module:
        decision = module.evaluate_smart_panic(
            [
                _observation(module, 1, 0.0),
                _observation(module, 2, 3.0, has_panic=True, panic_state=module.PanicEffectState.LOCALLY_COVERED),
                _observation(module, 3, 6.0),
            ],
            policy=_policy(module),
        )
        assert decision.selected is not None
        assert decision.selected.uncovered_affected_agent_ids == (1, 3)


def test_coverage_expires_at_effect_expiry() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes[1] = [types.SimpleNamespace(attribute_id=2, level=10, level_base=1)]
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        expiry = handler._coverage_expiry_by_agent[1]
        _advance_to(runtime, expiry)
        handler.update_lifecycle(0)
        assert 1 not in handler._coverage_expiry_by_agent


def test_overlapping_coverage_expiry_is_per_agent() -> None:
    with _loaded_runtime() as (module, runtime):
        _add_three_enemy_cluster(runtime)
        runtime.add_enemy(4, x=9.0)
        handler = _new_handler(module, runtime)
        handler._coverage_expiry_by_agent.update({1: 1100, 2: 1100, 3: 1300, 4: 1300})
        _advance_to(runtime, 1100)
        handler.update_lifecycle(0)
        assert set(handler._coverage_expiry_by_agent) == {3, 4}


def test_direct_positive_and_local_coverage_have_distinct_provenance() -> None:
    with _loaded_module() as module:
        direct = _observation(module, 2, 3.0, has_panic=True, panic_state=module.PanicEffectState.OBSERVED_PRESENT)
        local = _observation(module, 3, 6.0, has_panic=True, panic_state=module.PanicEffectState.LOCALLY_COVERED)
        assert direct.panic_state is not local.panic_state
        decision = module.evaluate_smart_panic(
            [_observation(module, 1, 0.0), direct, local],
            policy=_policy(module),
        )
        assert decision.selected is not None
        assert decision.selected.uncovered_affected_agent_ids == (1,)


def _set_domination_duration(
    runtime: _Runtime,
    *,
    level: Any = 10,
    level_base: Any = 1,
    seconds: float = 7.0,
) -> None:
    runtime.attributes[1] = [
        types.SimpleNamespace(attribute_id=2, level=level, level_base=level_base),
    ]
    runtime.progression_data = [("Domination Magic", "Duration", {int(level): seconds})]


def test_duration_resolution_uses_effective_level_not_base_level() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime, level=10, level_base=1, seconds=7.0)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        assert parameters.panic_duration_ms == 7000


def test_valid_domination_rank_resolves_progression_duration() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime, level=5, level_base=5, seconds=4.0)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        assert parameters.panic_duration_ms == 4000


def test_duration_seconds_are_converted_to_milliseconds() -> None:
    with _loaded_runtime() as (module, _runtime):
        assert module.SmartPanic._duration_to_ms(1.25) == 1250


def test_unavailable_rank_disables_long_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        runtime.attributes.clear()
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        assert parameters.panic_duration_ms is None


def test_invalid_rank_does_not_guess_duration() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime, level=99, level_base=15, seconds=99.0)
        handler = _new_handler(module, runtime)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        assert parameters.panic_duration_ms is None


def test_progression_failure_keeps_short_guard_without_long_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        runtime.progression_data = []
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        assert handler._coverage_expiry_by_agent == {}
        assert handler._recent_group is not None


def test_target_death_removes_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.states[2].alive = False
        handler.update_lifecycle(0)
        assert 2 not in handler._coverage_expiry_by_agent
        assert 1 in handler._coverage_expiry_by_agent


def test_despawn_invalidity_removes_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.states[2].valid = False
        handler.update_lifecycle(0)
        assert 2 not in handler._coverage_expiry_by_agent


def test_movement_does_not_remove_stable_agent_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        original_expiry = handler._coverage_expiry_by_agent[2]
        runtime.states[2].position = (200.0, 200.0)
        handler.update_lifecycle(0)
        assert handler._coverage_expiry_by_agent[2] == original_expiry


def test_player_death_clears_pending_and_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.states[runtime.player_id].alive = False
        runtime.states[runtime.player_id].living = False
        handler.update_lifecycle(0)
        assert handler._pending_receipt is None
        assert handler._coverage_expiry_by_agent == {}


def test_player_revival_does_not_restore_old_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.states[runtime.player_id].alive = False
        runtime.states[runtime.player_id].living = False
        handler.update_lifecycle(0)
        runtime.states[runtime.player_id].alive = True
        runtime.states[runtime.player_id].living = True
        handler.update_lifecycle(0)
        assert handler._coverage_expiry_by_agent == {}


def test_map_change_clears_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.map_id = 2
        handler.update_lifecycle(0)
        assert handler._coverage_expiry_by_agent == {}


def test_instance_uptime_rollback_clears_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.instance_uptime = 50
        handler.update_lifecycle(0)
        assert handler._coverage_expiry_by_agent == {}


def test_composition_and_contract_reset_clear_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        handler.update_lifecycle(1)
        assert handler._coverage_expiry_by_agent == {}
        handler._coverage_expiry_by_agent[1] = runtime.now_ms + 1000
        handler.OnContractActivated()
        assert handler._coverage_expiry_by_agent == {}


def test_agent_id_reuse_cannot_restore_old_coverage() -> None:
    with _loaded_runtime() as (module, runtime):
        _set_domination_duration(runtime)
        handler = _cast_three_enemy_cluster(module, runtime)
        _complete_receipt(handler, runtime)
        runtime.states[2].alive = False
        handler.update_lifecycle(0)
        runtime.add_enemy(2, x=3.0, agent_is_spirit=False, npc_flags=0)
        parameters = handler._resolve_runtime_parameters()
        assert parameters is not None
        snapshot = handler._build_snapshot(parameters)
        assert snapshot is not None
        reused = next(item for item in snapshot if item.agent_id == 2)
        assert reused.panic_state is module.PanicEffectState.UNKNOWN
        assert 2 not in handler._coverage_expiry_by_agent
