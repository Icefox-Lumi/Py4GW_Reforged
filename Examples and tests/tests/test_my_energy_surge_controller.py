"""Recording-fake regression tests for the Checkpoint C Energy Surge owner."""

from __future__ import annotations

import importlib.util
import sys
import types
from enum import IntEnum
from importlib import import_module
from pathlib import Path
from typing import Any

pytest: Any = import_module("pytest")

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"
POLICY_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Mesmer" / "Me_Any" / "My Energy Surge.py"
SMART_NAME = "Py4GWCoreLib.Builds.Skills.SmartMesmer"
POLICY_NAME = "controller_test.my_energy_surge"


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


class _Profession(IntEnum):
    _None = 0
    Mesmer = 5


class _Allegiance(IntEnum):
    Unknown = 0
    Ally = 1
    Enemy = 3


class _Intent:
    def __init__(
        self,
        owner_email: str,
        skill_id: int,
        target_agent_id: int,
        expires_at_tick: int,
        group_id: int,
        *,
        lock_mode: int = 1,
        reentry_policy: int = 1,
        claim_strength: int = 1,
        max_holders: int = 1,
    ) -> None:
        self.OwnerEmail = owner_email
        self.KindID = 1
        self.LockMode = lock_mode
        self.ReentryPolicy = reentry_policy
        self.ClaimStrength = claim_strength
        self.MaxHolders = max_holders
        self.SkillID = skill_id
        self.TargetAgentID = target_agent_id
        self.IsolationGroupID = group_id
        self.PostedAtTick = 0
        self.ExpiresAtTick = expires_at_tick
        self.Active = True


class _AgentInfo:
    def __init__(
        self,
        x: float,
        y: float,
        *,
        health: float = 0.50,
        profession: str = "Warrior",
        caster: bool = False,
        casting: bool = False,
        allegiance: int = 3,
        alive: bool = True,
    ) -> None:
        self.x = x
        self.y = y
        self.health = health
        self.profession = profession
        self.caster = caster
        self.casting = casting
        self.allegiance = allegiance
        self.alive = alive


class _FakeAllAccounts:
    def __init__(self, runtime: "_Runtime") -> None:
        self.runtime = runtime
        self.intents: list[_Intent] = []
        self.AccountData: list[Any] = []
        self.raw_reads = 0

    def GetAllIntents(self) -> list[tuple[int, _Intent]]:
        self.raw_reads += 1
        return [(index, intent) for index, intent in enumerate(self.intents) if intent.Active]


class _FakeSharedMemory:
    def __init__(self, runtime: "_Runtime") -> None:
        self.runtime = runtime
        self.accounts = _FakeAllAccounts(runtime)
        self.cached_get_all_intents_calls = 0
        self.clear_calls: list[tuple[int, str, int, int, int]] = []

    def GetAllAccounts(self) -> _FakeAllAccounts:
        return self.accounts

    def GetAllIntents(self) -> list[tuple[int, _Intent]]:
        self.cached_get_all_intents_calls += 1
        raise AssertionError("controller used cached SharedMemory.GetAllIntents")

    def GetAccountGroupByEmail(self, owner_email: str) -> int:
        return self.runtime.group_id

    def PostIntent(
        self,
        owner_email: str,
        skill_id: int,
        target_agent_id: int,
        expires_at_tick: int,
        *,
        isolation_group_id: int,
    ) -> int:
        slot_index = len(self.accounts.intents)
        intent = _Intent(
            owner_email,
            skill_id,
            target_agent_id,
            expires_at_tick,
            isolation_group_id,
        )
        self.accounts.intents.append(intent)
        if self.runtime.post_hook is not None:
            self.runtime.post_hook()
        return slot_index

    def ClearIntentIfMatch(
        self,
        index: int,
        owner_email: str,
        skill_id: int,
        target_agent_id: int,
        group_id: int,
    ) -> bool:
        self.clear_calls.append((index, owner_email, skill_id, target_agent_id, group_id))
        if index < 0 or index >= len(self.accounts.intents):
            return False
        intent = self.accounts.intents[index]
        if (
            not intent.Active
            or intent.OwnerEmail != owner_email
            or intent.SkillID != skill_id
            or intent.TargetAgentID != target_agent_id
            or intent.IsolationGroupID != group_id
        ):
            return False
        intent.Active = False
        return True


_DEFAULT_RUNTIME_DATA = object()


class _Runtime:
    def __init__(self) -> None:
        self.now = 1_000
        self.map_id = 1
        self.uptime = 1_000
        self.player_id = 1
        self.group_id = 7
        self.owner_email = "local@example.test"
        self.rank = 8
        self.local_attributes: Any = _DEFAULT_RUNTIME_DATA
        self.progression_data: Any = _DEFAULT_RUNTIME_DATA
        self.can_cast = True
        self.can_cast_sequence: list[bool] = []
        self.cast_result = True
        self.agents: dict[int, _AgentInfo] = {
            self.player_id: _AgentInfo(
                0.0,
                0.0,
                allegiance=int(_Allegiance.Ally),
            )
        }
        self.enemy_ids: list[int] = []
        self.enemy_array_calls = 0
        self.cast_calls: list[tuple[int, int]] = []
        self.can_cast_calls = 0
        self.logs: list[str] = []
        self.post_hook: Any = None
        self.shared = _FakeSharedMemory(self)

    def add_enemy(self, agent_id: int, x: float, y: float, **kwargs: Any) -> None:
        self.agents[agent_id] = _AgentInfo(x, y, **kwargs)
        if agent_id not in self.enemy_ids:
            self.enemy_ids.append(agent_id)

    def add_foreign_reservation(
        self,
        target_agent_id: int,
        *,
        owner_email: str = "foreign@example.test",
        rank: int = 10,
        lock_mode: int = 1,
        reentry_policy: int = 1,
        claim_strength: int = 1,
        max_holders: int = 1,
        include_owner_data: bool = True,
        foreign_attributes: Any = _DEFAULT_RUNTIME_DATA,
        last_updated: int | None = None,
    ) -> None:
        self.shared.accounts.intents.append(
            _Intent(
                owner_email,
                39,
                target_agent_id,
                self.now + 5_000,
                self.group_id,
                lock_mode=lock_mode,
                reentry_policy=reentry_policy,
                claim_strength=claim_strength,
                max_holders=max_holders,
            )
        )
        if not include_owner_data:
            return
        attribute_values = (
            [types.SimpleNamespace(Id=2, Value=rank)]
            if foreign_attributes is _DEFAULT_RUNTIME_DATA
            else foreign_attributes
        )
        attributes = types.SimpleNamespace(Attributes=attribute_values)
        skills = types.SimpleNamespace(Skills=[types.SimpleNamespace(Id=39)])
        agent_data = types.SimpleNamespace(
            AgentID=100 + len(self.shared.accounts.AccountData),
            Map=types.SimpleNamespace(MapID=self.map_id),
            Skillbar=skills,
            Attributes=attributes,
        )
        self.shared.accounts.AccountData.append(
            types.SimpleNamespace(
                AccountEmail=owner_email,
                IsSlotActive=True,
                IsAccount=True,
                IsolationGroupID=self.group_id,
                LastUpdated=self.now if last_updated is None else last_updated,
                AgentData=agent_data,
            )
        )


_ACTIVE_RUNTIME: _Runtime | None = None


def _runtime() -> _Runtime:
    assert _ACTIVE_RUNTIME is not None
    return _ACTIVE_RUNTIME


class _RecordingBuildMgr:
    def __init__(
        self,
        name: str = "Generic Build",
        required_primary: _Profession | None = None,
        required_secondary: _Profession | None = None,
        template_code: str = "",
        required_skills: list[int] | None = None,
        optional_skills: list[int] | None = None,
        **_: Any,
    ) -> None:
        self.build_name = name
        self.required_primary = required_primary
        self.required_secondary = required_secondary
        self.template_code = template_code
        self.required_skills = list(required_skills or [])
        self.optional_skills = list(optional_skills or [])
        self.fallback: Any = None
        self.fallback_name = ""
        self.blocked_skills: list[int] = []
        self.local_handler: Any = None
        self.current_skills = [39]

    def _get_current_skills(self) -> list[int]:
        return list(self.current_skills)

    def ScoreMatch(
        self,
        current_primary: _Profession | None = None,
        current_secondary: _Profession | None = None,
        current_skills: list[int] | None = None,
    ) -> int:
        if self.required_primary is not None and self.required_primary != current_primary:
            return -1
        if self.required_secondary not in (None, _Profession(0)) and self.required_secondary != current_secondary:
            return -1
        skills = set(current_skills or [])
        if any(skill_id not in skills for skill_id in self.required_skills):
            return -1
        return len(self.required_skills) + sum(skill_id in skills for skill_id in self.optional_skills)

    def SetFallback(self, name: str, handler: Any) -> None:
        self.fallback_name = name
        self.fallback = handler

    def SetBlockedSkills(self, skill_ids: list[int]) -> None:
        self.blocked_skills = list(skill_ids)

    def SetSkillCastingFn(self, handler: Any) -> None:
        self.local_handler = handler

    def CanCastSkillID(self, _skill_id: int) -> bool:
        runtime = _runtime()
        runtime.can_cast_calls += 1
        if runtime.can_cast_sequence:
            return runtime.can_cast_sequence.pop(0)
        return runtime.can_cast

    def CastSkillID(
        self,
        *,
        skill_id: int,
        target_agent_id: int,
        aftercast_delay: int,
        log: bool = False,
    ):
        if False:
            yield
        runtime = _runtime()
        runtime.cast_calls.append((target_agent_id, aftercast_delay))
        return runtime.cast_result

    def ProcessSkillCasting(self):
        if False:
            yield
        result = _drain(self.local_handler()) if self.local_handler is not None else False
        if result:
            return True
        if self.fallback is not None:
            apply_blocked = getattr(self.fallback, "ApplyBlockedSkillIDs", None)
            if callable(apply_blocked):
                apply_blocked(self.blocked_skills)
            return (yield from self.fallback.ProcessSkillCasting())
        return False


class _RecordingHeroAI:
    def __init__(self, **_: Any) -> None:
        self.calls = 0
        self.blocked_skills: list[int] = []

    def ApplyBlockedSkillIDs(self, skill_ids: list[int] | None = None) -> None:
        self.blocked_skills = list(skill_ids or [])

    def ProcessSkillCasting(self):
        if False:
            yield
        self.calls += 1
        return True


class _AgentAPI:
    @staticmethod
    def IsValid(agent_id: int) -> bool:
        return agent_id in _runtime().agents

    @staticmethod
    def IsDead(agent_id: int) -> bool:
        return not _runtime().agents[agent_id].alive

    @staticmethod
    def IsKnockedDown(_agent_id: int) -> bool:
        return False

    @staticmethod
    def GetAllegiance(agent_id: int) -> tuple[int, str]:
        info = _runtime().agents[agent_id]
        return info.allegiance, "Enemy" if info.allegiance == 3 else "Ally"

    @staticmethod
    def GetXY(agent_id: int) -> tuple[float, float]:
        info = _runtime().agents[agent_id]
        return info.x, info.y

    @staticmethod
    def GetHealth(agent_id: int) -> float:
        return _runtime().agents[agent_id].health

    @staticmethod
    def GetProfessionNames(agent_id: int) -> tuple[str, str]:
        return _runtime().agents[agent_id].profession, ""

    @staticmethod
    def IsCaster(agent_id: int) -> bool:
        return _runtime().agents[agent_id].caster

    @staticmethod
    def IsCasting(agent_id: int) -> bool:
        return _runtime().agents[agent_id].casting

    @staticmethod
    def GetAttributes(_agent_id: int) -> Any:
        if _runtime().local_attributes is not _DEFAULT_RUNTIME_DATA:
            return _runtime().local_attributes
        return [
            types.SimpleNamespace(
                attribute_id=2,
                level=_runtime().rank,
                level_base=max(0, _runtime().rank - 1),
            )
        ]


class _AgentArrayAPI:
    @staticmethod
    def GetEnemyArray() -> list[int]:
        runtime = _runtime()
        runtime.enemy_array_calls += 1
        return list(runtime.enemy_ids)


class _PlayerAPI:
    @staticmethod
    def GetAgentID() -> int:
        return _runtime().player_id

    @staticmethod
    def GetXY() -> tuple[float, float]:
        info = _runtime().agents[_runtime().player_id]
        return info.x, info.y

    @staticmethod
    def GetAccountEmail() -> str:
        return _runtime().owner_email


class _MapAPI:
    @staticmethod
    def IsMapReady() -> bool:
        return True

    @staticmethod
    def IsExplorable() -> bool:
        return True

    @staticmethod
    def GetMapID() -> int:
        return _runtime().map_id

    @staticmethod
    def GetInstanceUptime() -> int:
        return _runtime().uptime


class _SkillDataAPI:
    @staticmethod
    def GetAoERange(_skill_id: int) -> float:
        return 4.0

    @staticmethod
    def GetActivation(_skill_id: int) -> float:
        return 0.25

    @staticmethod
    def GetAftercast(_skill_id: int) -> float:
        return 0.75


class _SkillAPI:
    Data = _SkillDataAPI()


class _SkillModule:
    @staticmethod
    def GetID(_name: str) -> int:
        return 39

    @staticmethod
    def GetProgressionData(_skill_id: int) -> Any:
        if _runtime().progression_data is not _DEFAULT_RUNTIME_DATA:
            return _runtime().progression_data
        return [
            (
                "Domination Magic",
                "Energyloss",
                {0: 1.0, 8: 6.0, 10: 7.0, 12: 8.0},
            )
        ]


def _drain(generator: Any) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as finished:
            return finished.value


_install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
_install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
_install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
_install_package("Py4GWCoreLib.Builds.Any", ROOT / "Py4GWCoreLib" / "Builds" / "Any")
_install_package("Py4GWCoreLib.GlobalCache", ROOT / "Py4GWCoreLib" / "GlobalCache")
_install_package(
    "Py4GWCoreLib.GlobalCache.shared_memory_src",
    ROOT / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src",
)
_install_package("Py4GWCoreLib.enums_src", ROOT / "Py4GWCoreLib" / "enums_src")

root_package: Any = sys.modules["Py4GWCoreLib"]
root_package.Profession = _Profession
root_package.Range = types.SimpleNamespace(Spellcast=types.SimpleNamespace(value=20.0))
root_package.Agent = _AgentAPI
root_package.AgentArray = _AgentArrayAPI
root_package.Player = _PlayerAPI
root_package.Map = _MapAPI
root_package.Routines = types.SimpleNamespace(
    Checks=types.SimpleNamespace(Map=types.SimpleNamespace(MapValid=lambda: True))
)
root_package.Skill = _SkillAPI
root_package.GLOBAL_CACHE = types.SimpleNamespace(Skill=_SkillAPI())
root_package.ConsoleLog = lambda _sender, message, *_args, **_kwargs: _runtime().logs.append(str(message))

skill_module: Any = types.ModuleType("Py4GWCoreLib.Skill")
skill_module.Skill = _SkillModule
sys.modules["Py4GWCoreLib.Skill"] = skill_module

build_mgr_module: Any = types.ModuleType("Py4GWCoreLib.BuildMgr")
build_mgr_module.BuildMgr = _RecordingBuildMgr
sys.modules["Py4GWCoreLib.BuildMgr"] = build_mgr_module

hero_ai_module: Any = types.ModuleType("Py4GWCoreLib.Builds.Any.HeroAI")
hero_ai_module.HeroAI = _RecordingHeroAI
sys.modules["Py4GWCoreLib.Builds.Any.HeroAI"] = hero_ai_module

game_data_module: Any = types.ModuleType("Py4GWCoreLib.enums_src.GameData_enums")
game_data_module.Allegiance = _Allegiance
sys.modules["Py4GWCoreLib.enums_src.GameData_enums"] = game_data_module

whiteboard_module: Any = types.ModuleType("Py4GWCoreLib.enums_src.Whiteboard_enums")
whiteboard_module.WhiteboardLockKind = types.SimpleNamespace(SKILL_TARGET=1)
whiteboard_module.WhiteboardLockMode = types.SimpleNamespace(EXCLUSIVE=1)
whiteboard_module.WhiteboardReentryPolicy = types.SimpleNamespace(OWNER_REENTRANT=1)
whiteboard_module.WhiteboardClaimStrength = types.SimpleNamespace(HARD=1)
sys.modules["Py4GWCoreLib.enums_src.Whiteboard_enums"] = whiteboard_module

globals_module: Any = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.Globals")
globals_module.SHMEM_INTENT_DEFAULT_PING_BUDGET_MS = 150
globals_module.SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS = 5_000
sys.modules["Py4GWCoreLib.GlobalCache.shared_memory_src.Globals"] = globals_module

intent_sync_module: Any = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync")
intent_sync_module.tick_is_expired = lambda now, expires: (
    ((int(expires) - int(now)) & 0xFFFFFFFF) == 0 or ((int(expires) - int(now)) & 0xFFFFFFFF) >= 0x80000000
)
_tick_helpers = _load_module(
    "_energy_surge_tick_helpers", ROOT / "Py4GWCoreLib/GlobalCache/shared_memory_src/IntentSync.py"
)
intent_sync_module.publication_is_live = _tick_helpers.publication_is_live
sys.modules["Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync"] = intent_sync_module

clock_module: Any = types.ModuleType("PySystem")
clock_module.get_tick_count64 = lambda: _runtime().now
clock_module.Console = types.SimpleNamespace(MessageType=types.SimpleNamespace(Info=0))
sys.modules["PySystem"] = clock_module

smart_mesmer = _load_module(SMART_NAME, SKILLS_DIR / "SmartMesmer.py")
policy = _load_module(POLICY_NAME, POLICY_PATH)


@pytest.fixture()
def runtime() -> _Runtime:
    global _ACTIVE_RUNTIME
    _ACTIVE_RUNTIME = _Runtime()
    return _ACTIVE_RUNTIME


def _controller(runtime: _Runtime) -> Any:
    root_package.GLOBAL_CACHE.ShMem = runtime.shared
    controller = policy.My_Energy_Surge()
    return controller


def _add_dense_pair(runtime: _Runtime, *, first_id: int = 10) -> None:
    runtime.add_enemy(first_id, 5.0, 0.0)
    runtime.add_enemy(first_id + 1, 7.0, 0.0)


def test_buildmgr_ownership_match_only_and_fallback_mask(runtime: _Runtime) -> None:
    match_only = policy.My_Energy_Surge(match_only=True)
    assert (
        match_only.ScoreMatch(
            current_primary=_Profession.Mesmer,
            current_secondary=_Profession._None,
            current_skills=[39],
        )
        >= policy.MATCH_SCORE_BONUS
    )
    assert (
        match_only.ScoreMatch(
            current_primary=_Profession._None,
            current_secondary=_Profession._None,
            current_skills=[39],
        )
        == -1
    )
    assert match_only.optional_skills == []
    assert not hasattr(match_only, "fallback") or match_only.fallback is None

    controller = _controller(runtime)
    assert controller.fallback_name == "HeroAI"
    assert controller.blocked_skills == [39]
    assert controller.optional_skills == []
    assert controller.local_handler is not None


def test_large_enemy_list_uses_one_snapshot_and_direct_selected_dispatch(
    runtime: _Runtime,
) -> None:
    _add_dense_pair(runtime)
    for agent_id in range(1000, 1600):
        runtime.add_enemy(agent_id, 100_000.0 + agent_id, 0.0)
    runtime.add_enemy(999, 5.0, 0.0, allegiance=int(_Allegiance.Ally))
    runtime.add_enemy(998, 5.0, 0.0, alive=False)

    controller = _controller(runtime)
    result = _drain(controller._run_local_skill_logic())

    assert result is True
    assert runtime.enemy_array_calls == 2
    assert runtime.cast_calls == [(10, 1_100)]
    assert runtime.shared.cached_get_all_intents_calls == 0
    assert runtime.shared.accounts.raw_reads >= 4


def test_decline_runs_heroai_fallback_and_blocks_only_energy_surge(
    runtime: _Runtime,
) -> None:
    _add_dense_pair(runtime)
    runtime.can_cast = False
    controller = _controller(runtime)

    result = _drain(controller.ProcessSkillCasting())

    assert result is True
    assert controller.fallback.calls == 1
    assert controller.fallback.blocked_skills == [39]
    assert runtime.enemy_array_calls == 0
    assert runtime.cast_calls == []


def test_rank_zero_uses_exact_progression_and_dynamic_lease(runtime: _Runtime) -> None:
    runtime.rank = 0
    for agent_id in range(10, 20):
        runtime.add_enemy(agent_id, 5.0, 0.0)
    controller = _controller(runtime)

    params = controller._resolve_runtime_parameters()
    assert params is not None and params.domination_rank == 0
    result = _drain(controller._run_local_skill_logic())

    assert result is True
    assert runtime.cast_calls == [(10, 1_100)]
    local_intents = [
        intent
        for intent in runtime.shared.accounts.intents
        if intent.OwnerEmail == runtime.owner_email and intent.Active
    ]
    assert len(local_intents) == 1
    assert local_intents[0].ExpiresAtTick == runtime.now + 2_250


@pytest.mark.parametrize(
    "attributes",
    (
        None,
        [],
        [types.SimpleNamespace(Id=1, Value=8)],
        [types.SimpleNamespace(Id=2, Value="malformed")],
    ),
)
def test_unresolved_local_domination_rank_blocks_reservation_and_cast(
    runtime: _Runtime,
    attributes: Any,
) -> None:
    runtime.local_attributes = attributes
    _add_dense_pair(runtime)
    controller = _controller(runtime)

    assert controller._resolve_runtime_parameters() is None
    result = _drain(controller.ProcessSkillCasting())

    assert result is True
    assert controller.fallback.calls == 1
    assert runtime.cast_calls == []
    assert not [intent for intent in runtime.shared.accounts.intents if intent.OwnerEmail == runtime.owner_email]


def test_untrusted_progression_field_blocks_local_reservation_and_cast(runtime: _Runtime) -> None:
    runtime.progression_data = [("Domination Magic", "TotalDamage", {0: 99.0, 8: 99.0})]
    _add_dense_pair(runtime)
    controller = _controller(runtime)

    assert controller._resolve_runtime_parameters() is None
    result = _drain(controller.ProcessSkillCasting())

    assert result is True
    assert controller.fallback.calls == 1
    assert runtime.cast_calls == []
    assert not [intent for intent in runtime.shared.accounts.intents if intent.OwnerEmail == runtime.owner_email]


def test_focus_keeps_group_best_candidate_while_challenger_stabilizes(
    runtime: _Runtime,
) -> None:
    for agent_id, x in ((10, 2.0), (11, 3.0), (12, 4.0), (20, 12.0), (21, 13.0)):
        runtime.add_enemy(agent_id, x, 0.0)
    controller = _controller(runtime)
    lifecycle_id = controller._refresh_lifecycle()
    params = controller._resolve_runtime_parameters()
    assert params is not None
    controller._focus_aoe_radius = params.aoe_radius

    first_data = controller._build_snapshot(params, lifecycle_id, runtime.now)
    assert first_data is not None
    first_snapshot, first_enemies, first_distances = first_data
    first_decision = policy.evaluate_energy_surge(
        first_snapshot,
        first_enemies,
        aoe_radius=params.aoe_radius,
        cast_range=params.cast_range,
        group_link_radius=params.aoe_radius,
        local_resolved_drain=params.local_drain,
        pairwise_distances=first_distances,
    )
    assert controller._focus_candidate(first_decision, first_snapshot, first_distances).target_agent_id == 10

    runtime.add_enemy(22, 14.0, 0.0)
    runtime.add_enemy(23, 13.5, 1.0)
    runtime.now += 100
    runtime.uptime += 100
    second_data = controller._build_snapshot(params, lifecycle_id, runtime.now)
    assert second_data is not None
    second_snapshot, second_enemies, second_distances = second_data
    second_decision = policy.evaluate_energy_surge(
        second_snapshot,
        second_enemies,
        aoe_radius=params.aoe_radius,
        cast_range=params.cast_range,
        group_link_radius=params.aoe_radius,
        local_resolved_drain=params.local_drain,
        pairwise_distances=second_distances,
    )
    assert second_decision.selected_target_agent_id == 20
    assert controller._focus_candidate(second_decision, second_snapshot, second_distances).target_agent_id == 10

    runtime.now += 301
    runtime.uptime += 301
    third_data = controller._build_snapshot(params, lifecycle_id, runtime.now)
    assert third_data is not None
    third_snapshot, third_enemies, third_distances = third_data
    third_decision = policy.evaluate_energy_surge(
        third_snapshot,
        third_enemies,
        aoe_radius=params.aoe_radius,
        cast_range=params.cast_range,
        group_link_radius=params.aoe_radius,
        local_resolved_drain=params.local_drain,
        pairwise_distances=third_distances,
    )
    assert controller._focus_candidate(third_decision, third_snapshot, third_distances).target_agent_id == 20


def test_nonviable_retained_group_is_cleared_without_gap_grace(runtime: _Runtime) -> None:
    for agent_id, x in ((10, 2.0), (11, 3.0), (12, 4.0), (20, 12.0), (21, 13.0)):
        runtime.add_enemy(agent_id, x, 0.0)
    controller = _controller(runtime)
    lifecycle_id = controller._refresh_lifecycle()
    params = controller._resolve_runtime_parameters()
    assert params is not None
    controller._focus_aoe_radius = params.aoe_radius

    initial = controller._build_snapshot(params, lifecycle_id, runtime.now)
    assert initial is not None
    snapshot, enemies, distances = initial
    decision = policy.evaluate_energy_surge(
        snapshot,
        enemies,
        aoe_radius=params.aoe_radius,
        cast_range=params.cast_range,
        group_link_radius=params.aoe_radius,
        local_resolved_drain=params.local_drain,
        pairwise_distances=distances,
    )
    assert controller._focus_candidate(decision, snapshot, distances).target_agent_id == 10

    for agent_id in (10, 11, 12):
        runtime.agents[agent_id].health = 0.05
    runtime.now += 100
    runtime.uptime += 100
    updated = controller._build_snapshot(params, lifecycle_id, runtime.now)
    assert updated is not None
    snapshot, enemies, distances = updated
    decision = policy.evaluate_energy_surge(
        snapshot,
        enemies,
        aoe_radius=params.aoe_radius,
        cast_range=params.cast_range,
        group_link_radius=params.aoe_radius,
        local_resolved_drain=params.local_drain,
        pairwise_distances=distances,
    )
    selected = controller._focus_candidate(decision, snapshot, distances)
    assert selected is not None
    assert selected.target_agent_id == 20


def test_foreign_projection_is_explicit_and_missing_owner_uses_table_max(
    runtime: _Runtime,
) -> None:
    _add_dense_pair(runtime)
    runtime.add_foreign_reservation(10, rank=10)
    controller = _controller(runtime)
    params = controller._resolve_runtime_parameters()
    assert params is not None
    rows = controller._read_raw_intents()
    assert rows is not None
    foreign_rows, projections = controller._foreign_projections(
        rows,
        runtime.owner_email,
        runtime.group_id,
        runtime.now,
        params,
        runtime.map_id,
    )
    assert len(foreign_rows) == 1
    assert projections[0].projected_drain == 7.0

    runtime.shared.accounts.AccountData.clear()
    _, missing_owner_projections = controller._foreign_projections(
        rows,
        runtime.owner_email,
        runtime.group_id,
        runtime.now,
        params,
        runtime.map_id,
    )
    assert missing_owner_projections[0].projected_drain == params.maximum_drain
    assert missing_owner_projections[0].projected_drain != 14.0


def test_foreign_rank_zero_uses_rank_zero_progression_without_local_substitution(
    runtime: _Runtime,
) -> None:
    _add_dense_pair(runtime)
    runtime.add_foreign_reservation(10, rank=0)
    controller = _controller(runtime)
    params = controller._resolve_runtime_parameters()
    assert params is not None
    rows = controller._read_raw_intents()
    assert rows is not None

    foreign_rows, projections = controller._foreign_projections(
        rows,
        runtime.owner_email,
        runtime.group_id,
        runtime.now,
        params,
        runtime.map_id,
    )

    assert len(foreign_rows) == 1
    assert projections[0].projected_drain == 1.0
    assert projections[0].projected_drain != params.local_drain
    assert runtime.shared.accounts.intents[0].Active is True


@pytest.mark.parametrize(
    "foreign_attributes",
    (
        None,
        [],
        [types.SimpleNamespace(Id=1, Value=10)],
        [types.SimpleNamespace(Id=2, Value="malformed")],
        [types.SimpleNamespace(Id=2, Value=-1)],
        [types.SimpleNamespace(Id=2, Value=1.5)],
    ),
)
def test_foreign_unresolved_domination_rank_uses_dynamic_table_max(
    runtime: _Runtime,
    foreign_attributes: Any,
) -> None:
    _add_dense_pair(runtime)
    runtime.add_foreign_reservation(10, foreign_attributes=foreign_attributes)
    controller = _controller(runtime)
    params = controller._resolve_runtime_parameters()
    assert params is not None
    rows = controller._read_raw_intents()
    assert rows is not None

    foreign_rows, projections = controller._foreign_projections(
        rows,
        runtime.owner_email,
        runtime.group_id,
        runtime.now,
        params,
        runtime.map_id,
    )

    assert len(foreign_rows) == 1
    assert projections[0].projected_drain == params.maximum_drain
    assert projections[0].projected_drain != params.local_drain
    assert projections[0].projected_drain != 14.0
    assert runtime.shared.accounts.intents[0].Active is True


def test_stale_foreign_owner_metadata_keeps_reservation_and_uses_table_max(
    runtime: _Runtime,
) -> None:
    _add_dense_pair(runtime)
    runtime.add_foreign_reservation(10, rank=0, last_updated=runtime.now - 6_000)
    controller = _controller(runtime)
    params = controller._resolve_runtime_parameters()
    assert params is not None
    rows = controller._read_raw_intents()
    assert rows is not None

    foreign_rows, projections = controller._foreign_projections(
        rows,
        runtime.owner_email,
        runtime.group_id,
        runtime.now,
        params,
        runtime.map_id,
    )

    assert len(foreign_rows) == 1
    assert projections[0].projected_drain == params.maximum_drain
    assert runtime.shared.accounts.intents[0].Active is True


def test_two_foreign_reservations_and_unexpected_semantics_decline(
    runtime: _Runtime,
) -> None:
    _add_dense_pair(runtime)
    runtime.add_foreign_reservation(10)
    runtime.add_foreign_reservation(11)
    runtime.add_foreign_reservation(
        10,
        owner_email="foreign2@example.test",
        lock_mode=2,
        reentry_policy=2,
        claim_strength=2,
        max_holders=4,
    )
    runtime.add_foreign_reservation(
        11,
        owner_email="foreign2@example.test",
        lock_mode=2,
        reentry_policy=2,
        claim_strength=2,
        max_holders=4,
    )
    controller = _controller(runtime)

    result = _drain(controller._run_local_skill_logic())

    assert result is False
    assert runtime.cast_calls == []
    assert any("unexpected_foreign_contract" in log for log in runtime.logs)
    params = controller._resolve_runtime_parameters()
    rows = controller._read_raw_intents()
    assert params is not None and rows is not None
    foreign_rows, projections = controller._foreign_projections(
        rows,
        runtime.owner_email,
        runtime.group_id,
        runtime.now,
        params,
        runtime.map_id,
    )
    assert any(
        not controller._is_exact_contract(row) and projection.projected_drain == params.maximum_drain
        for row, projection in zip(foreign_rows, projections)
    )
    assert not [
        intent
        for intent in runtime.shared.accounts.intents
        if intent.OwnerEmail == runtime.owner_email and intent.Active
    ]


def test_post_race_releases_only_returned_local_slot(runtime: _Runtime) -> None:
    _add_dense_pair(runtime)

    def add_racing_reservation() -> None:
        if len(runtime.shared.accounts.intents) == 1:
            runtime.add_foreign_reservation(10, owner_email="racer@example.test")
            runtime.add_foreign_reservation(10, owner_email="racer2@example.test")

    runtime.post_hook = add_racing_reservation
    controller = _controller(runtime)

    result = _drain(controller._run_local_skill_logic())

    assert result is False
    assert runtime.cast_calls == []
    assert len(runtime.shared.clear_calls) == 1
    assert runtime.shared.clear_calls[0][0] == 0
    assert runtime.shared.clear_calls[0][1] == runtime.owner_email
    assert not runtime.shared.accounts.intents[0].Active


def test_final_revalidation_releases_when_target_changes(runtime: _Runtime) -> None:
    _add_dense_pair(runtime)
    original_enemy_array = _AgentArrayAPI.GetEnemyArray

    def changing_enemy_array() -> list[int]:
        result = original_enemy_array()
        if runtime.enemy_array_calls == 2:
            runtime.agents[10].health = 0.05
        return result

    _AgentArrayAPI.GetEnemyArray = staticmethod(changing_enemy_array)
    try:
        controller = _controller(runtime)
        result = _drain(controller._run_local_skill_logic())
    finally:
        _AgentArrayAPI.GetEnemyArray = staticmethod(original_enemy_array)

    assert result is False
    assert runtime.cast_calls == []
    assert len(runtime.shared.clear_calls) == 1
    assert runtime.shared.clear_calls[0][3] == 10


def test_final_revalidation_releases_on_cast_gate_and_lifecycle_change(
    runtime: _Runtime,
) -> None:
    _add_dense_pair(runtime)
    runtime.can_cast_sequence = [True, False]
    controller = _controller(runtime)
    result = _drain(controller._run_local_skill_logic())
    assert result is False
    assert runtime.cast_calls == []
    assert len(runtime.shared.clear_calls) == 1

    runtime.shared.clear_calls.clear()
    runtime.shared.accounts.intents.clear()
    runtime.map_id = 1
    runtime.uptime = 1_000
    runtime.can_cast_sequence = []
    runtime.can_cast = True
    _add_dense_pair(runtime)
    controller = _controller(runtime)

    def change_lifecycle() -> None:
        runtime.map_id = 2

    runtime.post_hook = change_lifecycle
    result = _drain(controller._run_local_skill_logic())
    assert result is False
    assert runtime.cast_calls == []
    assert len(runtime.shared.clear_calls) == 1


def test_final_revalidation_releases_if_player_starts_casting(runtime: _Runtime) -> None:
    _add_dense_pair(runtime)

    def start_casting() -> None:
        runtime.agents[runtime.player_id].casting = True

    runtime.post_hook = start_casting
    controller = _controller(runtime)
    result = _drain(controller._run_local_skill_logic())

    assert result is False
    assert runtime.cast_calls == []
    assert len(runtime.shared.clear_calls) == 1
    assert runtime.shared.clear_calls[0][1:] == (
        runtime.owner_email,
        39,
        10,
        runtime.group_id,
    )


def test_lifecycle_generation_changes_on_uptime_reset(runtime: _Runtime) -> None:
    controller = _controller(runtime)
    first = controller._refresh_lifecycle()
    runtime.uptime = 0
    second = controller._refresh_lifecycle()
    assert first == (1, 1, 0)
    assert second == (1, 1, 1)
    assert first != second


def test_diagnostics_are_signature_throttled_and_do_not_log_owner_identity(
    runtime: _Runtime,
) -> None:
    controller = _controller(runtime)
    controller._emit_diagnostic("runtime_gate", ("not_ready",))
    runtime.now += 100
    controller._emit_diagnostic("runtime_gate", ("not_ready",))
    runtime.now += 1_000
    controller._emit_diagnostic("runtime_gate", ("not_ready",))

    assert len(runtime.logs) == 2
    assert runtime.owner_email not in " ".join(runtime.logs)


def test_controller_source_has_no_target_hijack_or_energy_whiteboard_registration() -> None:
    source = POLICY_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "AcquireTarget",
        "ChangeTarget",
        "CastSkillIDAndRestoreTarget",
        "GetPartyTarget",
        "CallTarget",
        "CountLocks",
    ):
        assert forbidden not in source
    assert "register(" not in source


@pytest.mark.parametrize(
    "last,now,live",
    [(0, 4999, True), (0, 5000, False), (0xFFFFFFF0, 5, True), (100, 99, False), (0, 0x80000000, False)],
)
def test_foreign_owner_freshness_at_rollover(runtime: _Runtime, last: int, now: int, live: bool) -> None:
    runtime.add_foreign_reservation(10, rank=10, last_updated=last)
    controller = _controller(runtime)
    # Use the actual owner identity installed by the runtime fixture.
    email = runtime.shared.accounts.AccountData[0].AccountEmail
    snapshots = controller._copy_foreign_owner_snapshots({email}, now, runtime.map_id)
    assert snapshots[email].active is live
