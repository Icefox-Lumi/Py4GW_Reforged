"""Native-free integration tests; raw resource fixtures are not strike/gain oracles."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from math import isclose
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
from test_restoration_spirit_admission import finish_coroutine as _finish
from test_restoration_spirit_admission import install_test_module as _module
from test_restoration_spirit_admission import load_test_module as _load
from test_restoration_spirit_admission import world as _admission_fixture

admission_world = _admission_fixture

HR, TOF, MYT, FGJ, SY, SY2, BIP, TNTF = 3431, 1598, 1779, 343, 1954, 2097, 119, 2354


class _State(Enum):
    SUCCESS = 1
    FAILURE = 2
    RUNNING = 3


def _ignore(*args: Any, **kwargs: Any) -> None:
    pass


def _false(*args: Any, **kwargs: Any) -> bool:
    return False


def _true(*args: Any, **kwargs: Any) -> bool:
    return True


def _zero(*args: Any, **kwargs: Any) -> int:
    return 0


@dataclass
class _World:
    now: int = 10000
    monitor_offset: int = 0
    bar: list[int] = field(default_factory=lambda: [HR, SY, MYT, FGJ, TOF, TNTF, 0, 0])
    raw: dict[int, int] = field(default_factory=lambda: {SY: 100, SY2: 100})
    recharge: dict[int, int] = field(default_factory=dict[int, int])
    costs: dict[int, int] = field(default_factory=lambda: {HR: 15, TOF: 10, MYT: 10, FGJ: 5})
    health: dict[int, float] = field(default_factory=lambda: {1: 1.0, 2: 1.0, 3: 1.0, 90: 1.0})
    maximum: dict[int, int] = field(default_factory=lambda: {1: 500, 2: 500, 3: 500})
    effects: dict[int, list[Any]] = field(default_factory=dict[int, list[Any]])
    roster: list[int] = field(default_factory=lambda: [1, 2, 3])
    heroes: list[int] = field(default_factory=list[int])
    dead: set[int] = field(default_factory=set[int])
    positions: dict[int, tuple[float, float]] = field(default_factory=dict[int, tuple[float, float]])
    attacking: set[int] = field(default_factory=lambda: {1, 90})
    casting: dict[int, int] = field(default_factory=dict[int, int])
    knocked: bool = False
    valid: bool = True
    cinematic: bool = False
    party_loaded: bool = True
    map_id: int = 1
    party_id: int = 1
    energy: float = 30.0
    leadership: int = 20
    hr_target: int = 0
    native_result: bool | Exception = True
    calls: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])
    ordinary: list[tuple[int, int]] = field(default_factory=list[tuple[int, int]])
    queue: list[Callable[[], Any]] = field(default_factory=list[Callable[[], Any]])
    trace: list[str] = field(default_factory=list[str])
    restored: list[int] = field(default_factory=list[int])
    casts: set[str] = field(default_factory=set[str])
    core: Any = None
    owner: Any = None
    policy: Any = None
    driver: Any = None
    stock_module: Any = None
    real_leadership: Any = None

    def slot(self, skill_id: int) -> int:
        return self.bar.index(skill_id) + 1 if skill_id in self.bar and skill_id else 0

    def skill(self, slot: int) -> Any:
        skill_id = self.bar[slot - 1] if 1 <= slot <= 8 else 0
        return SimpleNamespace(
            id=SimpleNamespace(id=skill_id),
            adrenaline_a=self.raw.get(skill_id, 0),
            recharge=self.recharge.get(skill_id, 0),
        )

    def native(self, slot: int, target: int) -> bool:
        self.calls.append((self.bar[slot - 1], target))
        if isinstance(self.native_result, Exception):
            raise self.native_result
        return self.native_result

    def add_effect(
        self,
        agent_id: int,
        skill_id: int,
        remaining: int,
        identity: int = 1,
        *,
        timestamp: int | None = None,
        append: bool = False,
    ) -> None:
        values = self.effects.setdefault(agent_id, [])
        if not append:
            values[:] = [effect for effect in values if effect.skill_id != skill_id]
        values.append(
            SimpleNamespace(
                skill_id=skill_id,
                time_remaining=remaining,
                effect_id=identity,
                timestamp=identity if timestamp is None else timestamp,
            )
        )

    def pressure(self, *, raw: int = 100) -> None:
        self.raw[SY] = raw
        self.policy.Advance()
        self.now += 150
        self.health[2] = 0.55
        self.policy.Advance()
        assert self.policy._pressure, "Fixture must enter pressure through the actual health monitor"

    def dispatch(self, delay: int = 50) -> None:
        self.now += delay
        self.queue.pop(0)()


# Reused by the separate console diagnostic tests; the fixture remains the owner.
HeroicRefrainWorld = _World


class _Book:
    def __init__(self, world: _World, owner: Any, path: str = "") -> None:
        self.world, self.owner, self.path = world, owner, path

    def __getattr__(self, name: str) -> Any:
        path = f"{self.path}.{name}" if self.path else name
        if name == "IsHeroicRefrainSelfReady":
            return self.world.real_leadership(self.owner).IsHeroicRefrainSelfReady
        return _Book(self.world, self.owner, path)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        name = self.path.split(".")[-1]
        self.world.trace.append(name)
        if name in {"Heroic_Refrain", "Theyre_on_Fire", "Aggressive_Refrain", "Make_Your_Time"}:
            coroutine = cast(
                Generator[Any, None, Any], getattr(self.world.real_leadership(self.owner), name)(*args, **kwargs)
            )
            return (yield from coroutine)
        if name in self.world.casts:
            self.owner.SetTickSuccess()
            return True
        if False:
            yield
        return False


@pytest.fixture
def world(admission_world: Any, monkeypatch: pytest.MonkeyPatch) -> _World:
    w = _World()
    core: Any = sys.modules["Py4GWCoreLib"]
    w.core = core
    base = sys.modules["Py4GWCoreLib.BuildMgr"].BuildMgr
    enums = sys.modules["Py4GWCoreLib.enums_src.GameData_enums"]
    core.BuildMgr = base
    core.Profession = enums.Profession
    core.SpiritModelID = SimpleNamespace()
    ids = {
        "Heroic_Refrain": HR,
        "Theyre_on_Fire": TOF,
        "Make_Your_Time": MYT,
        "For_Great_Justice": FGJ,
        "Save_Yourselves_kurzick": SY,
        "Save_Yourselves_luxon": SY2,
        "Blood_is_Power": BIP,
        "Theres_Nothing_to_Fear": TNTF,
    }

    def get_id(name: str) -> int:
        return ids.setdefault(name, 5000 + len(ids))

    def get_type(skill_id: int) -> tuple[Any, str]:
        return sys.modules["Py4GWCoreLib.HeroAI.types"].SkillType.Shout.value, "Shout"

    def get_adrenaline(skill_id: int) -> int:
        return 100 if skill_id in (SY, SY2) else 0

    core.Skill.GetID = get_id
    core.Skill.GetType = get_type
    core.Skill.GetName = str
    core.Skill.Data = SimpleNamespace(GetAdrenaline=get_adrenaline)
    core.Player.GetAgentID = lambda: 1
    core.Player.GetTargetID = lambda: 90
    core.Player.GetXY = lambda: (0.0, 0.0)
    agent_api: dict[str, Callable[[int], Any]] = {
        "GetXY": lambda agent_id: w.positions.get(agent_id, (100.0, 0.0)),
        "IsAlive": lambda agent_id: agent_id in w.health and agent_id not in w.dead,
        "IsDead": lambda agent_id: not core.Agent.IsAlive(agent_id),
        "GetHealth": lambda agent_id: w.health.get(agent_id, 0.0),
        "GetMaxHealth": lambda agent_id: w.maximum.get(agent_id, 0),
        "GetEnergy": lambda agent_id: w.energy / 30.0,
        "GetMaxEnergy": lambda agent_id: 30,
        "IsAttacking": lambda agent_id: agent_id in w.attacking,
        "IsCasting": lambda agent_id: bool(w.casting.get(agent_id)),
        "GetCastingSkillID": lambda agent_id: w.casting.get(agent_id, 0),
        "IsKnockedDown": lambda agent_id: w.knocked,
        "IsHoldingItem": lambda agent_id: False,
        "GetProfessions": lambda agent_id: (9, 1),
        "GetWeaponType": lambda agent_id: (1, "Spear"),
        "GetAttributes": lambda agent_id: [SimpleNamespace(GetName=lambda: "Leadership", level=w.leadership)],
    }
    core.Agent.__dict__.update(agent_api)
    core.Agent.DEAD_HEALTH_EPSILON = 0.0001
    core.AgentArray.GetAllyArray = lambda: list(w.roster)
    core.AgentArray.GetSpiritPetArray = lambda: list[int]()
    core.AgentArray.GetEnemyArray = lambda: [90]
    core.Utils.GetBaseTimestamp = lambda: (w.now + w.monitor_offset) % 86400000
    core.Map = SimpleNamespace(
        IsMapReady=lambda: w.valid,
        IsExplorable=lambda: w.valid,
        IsInCinematic=lambda: w.cinematic,
        GetMapID=lambda: w.map_id,
        GetRegion=lambda: (1, ""),
        GetDistrict=lambda: 1,
        GetLanguage=lambda: (0, ""),
    )
    _module(monkeypatch, "Py4GWCoreLib.Map", Map=core.Map)

    def get_agent(number: int) -> int:
        return number

    core.GLOBAL_CACHE.Party = SimpleNamespace(
        GetPartyID=lambda: w.party_id,
        IsPartyLoaded=lambda: w.party_loaded,
        GetPlayers=lambda: [SimpleNamespace(login_number=agent_id) for agent_id in w.roster],
        GetHeroes=lambda: [SimpleNamespace(agent_id=agent_id) for agent_id in w.heroes],
        GetHenchmen=lambda: list[Any](),
        Players=SimpleNamespace(GetAgentIDByLoginNumber=get_agent),
    )

    def get_effects(agent_id: int) -> list[Any]:
        return list(w.effects.get(agent_id, []))

    core.GLOBAL_CACHE.Effects = SimpleNamespace(GetEffects=get_effects)

    def all_allies(*args: Any, **kwargs: Any) -> list[int]:
        return list(w.roster)

    def all_enemies(*args: Any, **kwargs: Any) -> list[int]:
        return [90]

    core.Routines.Targeting.GetAllAlliesArray = all_allies
    core.Routines.Agents.GetFilteredEnemyArray = all_enemies
    checks = _load(monkeypatch, "Py4GWCoreLib.routines_src.Checks", "Py4GWCoreLib/routines_src/Checks.py").Checks
    core.Routines.Checks = checks
    checks.Map.MapValid = staticmethod(lambda: w.valid)
    checks.Map.IsExplorable = staticmethod(lambda: w.valid)
    checks.Agents._get_same_party_shared_agent_data = staticmethod(_ignore)

    def has_effect(agent_id: int, skill_id: int, **kwargs: Any) -> bool:
        return any(e.skill_id == skill_id and e.time_remaining > 0 for e in w.effects.get(agent_id, []))

    def adjusted_cost(skill_id: int, agent_id: int) -> int:
        return w.costs.get(skill_id, 0)

    checks.Agents.HasEffect = staticmethod(has_effect)
    checks.Skills.GetEnergyCostWithEffects = staticmethod(adjusted_cost)

    class Timer:
        def __init__(self, delay: int) -> None:
            self.delay = delay
            self.deadline: int | None = None

        def SetThrottleTime(self, delay: int) -> None:
            self.delay = delay

        def Reset(self) -> None:
            self.deadline = w.now + self.delay

        def Stop(self) -> None:
            self.deadline = None

        def IsStopped(self) -> bool:
            return self.deadline is None

        def IsExpired(self) -> bool:
            return self.deadline is not None and w.now >= self.deadline

    core.ThrottledTimer = Timer
    sys.modules["PySystem"].__dict__["get_tick_count64"] = lambda: w.now
    sys.modules["Py4GWCoreLib.py4gwcorelib_src.BehaviorTree"].BehaviorTree.NodeState = _State
    _module(monkeypatch, "PySkillbar", Skillbar=lambda: SimpleNamespace(GetSkill=w.skill, UseSkill=w.native))
    sys.modules["Py4GWCoreLib.Py4GWcorelib"].__dict__["ActionQueueManager"] = object
    cache_type = _load(monkeypatch, "_hr_skillbar_cache", "Py4GWCoreLib/GlobalCache/SkillbarCache.py").SkillbarCache

    class Queue:
        def AddAction(self, queue_name: str, callback: Callable[..., Any], *args: Any) -> None:
            w.queue.append(lambda: callback(*args))

        def AddActionWithDelay(self, queue_name: str, delay: int, native: Any, slot: int, target: int) -> None:
            w.ordinary.append((w.bar[slot - 1], target))

    cache = cache_type(Queue())
    cache.GetCasting = lambda: 0
    core.GLOBAL_CACHE.SkillBar = cache
    core.SkillBar.GetSlotBySkillID = w.slot

    def get_skill_id(slot: int) -> int:
        return int(w.skill(slot).id.id)

    core.SkillBar.GetSkillIDBySlot = get_skill_id
    core.SkillBar.GetSkillData = w.skill
    core.SkillBar.GetSkillbar = lambda: [skill_id for skill_id in w.bar if skill_id]
    core.SkillBar.GetCasting = lambda: 0
    for package in ("Py4GWCoreLib.Builds", "Py4GWCoreLib.Builds.Any", "Py4GWCoreLib.Builds.Skills"):
        _module(monkeypatch, package).__path__ = []
    helper = _load(
        monkeypatch,
        "Py4GWCoreLib.Builds.Skills.SmartSaveYourselves",
        "Py4GWCoreLib/Builds/Skills/SmartSaveYourselves.py",
    )
    heroai = _load(monkeypatch, "Py4GWCoreLib.Builds.Any.HeroAI", "Py4GWCoreLib/Builds/Any/HeroAI.py")
    w.real_leadership = _load(
        monkeypatch, "_hr_leadership", "Py4GWCoreLib/Builds/Skills/paragon/Leadership.py"
    ).Leadership

    def book_factory(owner: Any) -> _Book:
        return _Book(w, owner)

    def is_party_member(agent_id: int) -> bool:
        return agent_id in w.roster

    sys.modules["Py4GWCoreLib.Builds.Skills"].__dict__["SkillsTemplate"] = book_factory
    sys.modules["Py4GWCoreLib.HeroAI.utils"].__dict__["IsPartyMember"] = is_party_member
    stock = _load(monkeypatch, "_hr_stock", "Py4GWCoreLib/Builds/Paragon/P_W/My Heroic Refrain.py")
    w.stock_module = stock
    owner = stock.Paragon_Refrain()
    w.owner = owner
    custom_type = sys.modules["Py4GWCoreLib.HeroAI.custom_skill_src.skill_types"].CustomSkill
    metadata: dict[int, Any] = {}

    def get_custom(skill_id: int) -> Any:
        return metadata.setdefault(skill_id, custom_type())

    owner._custom_skill_data_handler = SimpleNamespace(get_skill=get_custom)
    owner.set_cached_data(
        SimpleNamespace(
            data=SimpleNamespace(in_aggro=True), account_options=SimpleNamespace(Combat=True, Skills=[True] * 8)
        )
    )

    def resolve_hr(*args: Any, **kwargs: Any) -> int:
        return w.hr_target

    def restore_enemy(target: int) -> Generator[None, None, None]:
        yield w.restored.append(target)

    owner.ResolveAllyTarget = resolve_hr
    owner.RestoreEnemyTarget = restore_enemy
    owner.AutoAttack = lambda: iter(())
    w.policy = owner.heroic_refrain_policy
    w.add_effect(1, HR, 20000)
    w.add_effect(1, TOF, 10000)
    w.driver = heroai.HeroAI_Build(owner._cached_data)
    w.driver._contract_build = owner
    w.driver._contract_signature = w.driver._get_contract_signature()
    assert isinstance(w.policy, helper.SmartSaveYourselves)
    return w


def test_match_only_has_no_operational_policy(world: _World) -> None:
    match = world.stock_module.Paragon_Refrain(match_only=True)
    assert not hasattr(match, "heroic_refrain_policy")


@pytest.fixture
def discovered_registry(world: _World, monkeypatch: pytest.MonkeyPatch) -> Any:
    controller_dir = Path(__file__).resolve().parents[1] / "Py4GWCoreLib/Builds/Paragon/P_W"
    package_name = "Py4GWCoreLib.Builds.Paragon.P_W"
    _module(monkeypatch, "Py4GWCoreLib.Builds.Paragon", __path__=[str(controller_dir.parent)])
    package = _module(monkeypatch, package_name, __path__=[str(controller_dir)])
    # Import the real controllers through their discovered module paths, and arrange
    # teardown even though importlib itself inserts the module into sys.modules.
    for name in ("Defensive Refrain", "My Heroic Refrain"):
        module_name = f"{package_name}.{name}"
        monkeypatch.setitem(sys.modules, module_name, None)
        monkeypatch.delitem(sys.modules, module_name)

    def scoped_import(name: str) -> ModuleType:
        if name == "Py4GWCoreLib.Builds":
            return package
        return importlib.import_module(name)

    build_module: Any = sys.modules["Py4GWCoreLib.BuildMgr"]
    monkeypatch.setattr(build_module, "importlib", SimpleNamespace(import_module=scoped_import))
    registry_type = build_module.BuildRegistry
    registry_type.ClearCache()
    registry = registry_type()
    discovered: list[type[Any]] = registry.GetBuildTypes()
    assert len(discovered) == 2, "The actual scanner must discover stock and custom exactly once each"
    assert {controller.__module__ for controller in discovered} == {
        f"{package_name}.Defensive Refrain",
        f"{package_name}.My Heroic Refrain",
    }
    for controller in discovered:
        assert controller.__name__ == "Paragon_Refrain"
        assert Path(str(sys.modules[controller.__module__].__file__)).resolve() == (
            controller_dir / f"{controller.__module__.rsplit('.', 1)[1]}.py"
        )
    return registry


def test_original_controller_matches_current_head_blob() -> None:
    root = Path(__file__).resolve().parents[1]
    relative = "Py4GWCoreLib/Builds/Paragon/P_W/Defensive Refrain.py"
    blob = subprocess.check_output(
        ["git", "cat-file", "blob", f"HEAD:{relative}"], cwd=root, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    )
    assert (root / relative).read_bytes() == blob, "Stock controller must remain byte-identical to current HEAD"


def test_stock_custom_discovery_identity_and_dormant_caches(world: _World, discovered_registry: Any) -> None:
    registry = discovered_registry
    matches: list[Any] = registry._iter_matchable_builds(match_only=True)
    runtime: list[Any] = registry._iter_matchable_builds()
    assert {build.build_name for build in matches} == {"Defensive Refrain", "My Heroic Refrain"}
    assert len({f"{type(build).__module__}.{type(build).__name__}" for build in matches}) == 2
    for match in matches:
        assert match.required_skills == [HR]
        assert match.required_primary == world.core.Profession(9)
        assert match.required_secondary == world.core.Profession(0)
        assert not hasattr(match, "heroic_refrain_policy")
        assert not match.is_fallback_candidate
        owner = registry._instantiate_build(type(match))
        assert owner is registry._instantiate_build(type(match))
        assert owner is not match and owner.build_name == match.build_name
        assert owner.GetPolicyGeneration() == 0, "Discovery/instantiation must not activate a controller"
        assert owner.tick_state is None
    assert len(registry._runtime_build_instances) == len(registry._match_only_build_instances) == 2
    assert runtime[0] is not runtime[1]
    assert sum(hasattr(build, "heroic_refrain_policy") for build in runtime) == 1
    assert not world.queue and not world.ordinary and not world.calls


@pytest.mark.parametrize("reverse", [False, True], ids=["discovered-order", "reversed-order"])
def test_coexisting_selection_and_flexible_bars(
    world: _World, discovered_registry: Any, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    registry_type: Any = discovered_registry.__class__
    discovered: list[type[Any]] = discovered_registry.GetBuildTypes()
    # Reorder only the actual scanner result; both production selectors run unchanged.
    monkeypatch.setattr(registry_type, "_cached_build_types", discovered[::-1] if reverse else discovered)
    registry = registry_type()
    matches: dict[str, Any] = {build.build_name: build for build in registry._iter_matchable_builds(match_only=True)}
    custom, stock = matches["My Heroic Refrain"], matches["Defensive Refrain"]
    world.driver.ClearBuildContract()
    world.driver._build_registry = registry
    original_bar = list(world.bar)
    bars = [[HR], [HR, 12345, SY2, 0, 0, 0, 0, 0], [HR, MYT, 12345, TOF, 0, 0, 0, 0]]
    bars.extend(original_bar[offset:] + original_bar[:offset] for offset in range(8))
    owner: Any = None
    for secondary in (1, 2, 0):

        def professions(agent_id: int) -> tuple[int, int]:
            return 9, secondary

        monkeypatch.setattr(world.core.Agent, "GetProfessions", professions)
        for bar in bars:
            args = dict(
                current_primary=world.core.Profession(9),
                current_secondary=world.core.Profession(secondary),
                current_skills=bar,
            )
            assert custom.ScoreMatch(**args) == 1000 + stock.ScoreMatch(**args), (secondary, bar)
            operational = registry.ResolveBuild(**args)
            if owner is None:
                owner = operational
            assert operational is owner and type(operational) is type(custom), (reverse, secondary, bar)
            world.bar = bar + [0] * (8 - len(bar))
            assert world.driver.EnsureBuildContract() is operational, (reverse, secondary, bar)
            assert operational.heroic_refrain_policy._owner is operational
            assert operational.current_fallback_name == "HeroAI"
            assert operational.GetSupportedSkills() == world.owner.GetSupportedSkills()
            assert {HR, MYT, FGJ, SY, SY2} <= set(operational.GetBlockedSkills())

    for primary, bar in ((9, [MYT, FGJ, SY]), (1, [HR])):
        args = dict(
            current_primary=world.core.Profession(primary),
            current_secondary=world.core.Profession(1),
            current_skills=bar,
        )
        assert custom.ScoreMatch(**args) == stock.ScoreMatch(**args) == -1
        assert registry.ResolveBuild(**args) is None
    # Existing eligibility filtering makes stock selectable; there is no manual
    # build-activation switch in the supported-build browser.
    custom.is_combat_automator_compatible = False
    stock_owner = registry.ResolveBuild(
        current_primary=world.core.Profession(9), current_secondary=world.core.Profession(1), current_skills=[HR]
    )
    assert type(stock_owner) is type(stock)
    assert stock_owner is not owner
    assert not world.queue and not world.ordinary and not world.calls


@pytest.mark.parametrize("reverse", [False, True], ids=["discovered-order", "reversed-order"])
def test_real_selection_reuses_one_owner_without_reviving_requests(
    world: _World, discovered_registry: Any, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    registry_type: Any = discovered_registry.__class__
    discovered: list[type[Any]] = discovered_registry.GetBuildTypes()
    monkeypatch.setattr(registry_type, "_cached_build_types", discovered[::-1] if reverse else discovered)
    registry = registry_type()
    fixture_owner = world.owner
    cached = fixture_owner._cached_data
    blocked: list[int] = []

    def fallback_combat(*args: Any, **kwargs: Any) -> bool:
        world.trace.append("fallback")
        return False

    cached.combat_handler = SimpleNamespace(ApplyBlockedSkillIDs=blocked.extend, HandleCombat=fallback_combat)
    cached.Update = _ignore
    cached.UpdateCombat = _ignore
    world.driver.ClearBuildContract()
    world.driver._build_registry = registry
    custom = world.driver.EnsureBuildContract(cached)
    assert custom.build_name == "My Heroic Refrain"
    stock = next(build for build in registry._iter_matchable_builds() if build.build_name == "Defensive Refrain")
    for owner in (custom, stock):
        owner._custom_skill_data_handler = fixture_owner._custom_skill_data_handler
        owner.ResolveAllyTarget = fixture_owner.ResolveAllyTarget
        owner.RestoreEnemyTarget = fixture_owner.RestoreEnemyTarget
        owner.AutoAttack = fixture_owner.AutoAttack
        owner.current_fallback_handler.set_cached_data(cached)
    world.owner = custom
    world.policy = custom.heroic_refrain_policy
    world.pressure()
    _finish(world.driver._run_contract(cached, is_in_combat=True))
    assert len(world.queue) == 1 and not world.ordinary
    assert stock.GetPolicyGeneration() == 0 and stock.tick_state is None
    old = world.queue.pop()
    generation = custom.GetPolicyGeneration()

    # Change eligibility through the existing contract, then change a real bar
    # slot to trigger reselection. No selector or ScoreMatch result is mocked.
    custom.is_combat_automator_compatible = False
    world.bar = world.bar[1:] + world.bar[:1]
    assert world.driver.EnsureBuildContract(cached) is stock
    assert custom.GetPolicyGeneration() > generation
    old()
    assert not world.calls and not world.queue
    world.casts.add("Save_Yourselves_kurzick")
    _finish(world.driver._run_contract(cached, is_in_combat=True))
    assert world.trace.count("Save_Yourselves_kurzick") == 1
    assert not world.queue, "Only stock execution should run while stock owns the contract"

    custom.is_combat_automator_compatible = True
    world.bar = world.bar[1:] + world.bar[:1]
    assert world.driver.EnsureBuildContract(cached) is custom
    assert custom is registry._instantiate_build(type(custom)), "Reuse the actual cached instance"
    old()
    assert not world.calls and not world.queue
    world.health[2] = 1.0
    world.now += 150
    world.pressure()
    world.trace.clear()
    _finish(world.driver._run_contract(cached, is_in_combat=True))
    _finish(world.driver._run_contract(cached, is_in_combat=True))
    assert len(world.queue) == 1 and not world.ordinary, "Repeated ticks must not admit duplicate or fallback work"
    assert "Save_Yourselves_kurzick" not in world.trace, "Dormant stock must not execute alongside custom"
    assert "fallback" not in world.trace
    assert not world.policy.TryCast(preparation=True)
    assert custom.ResolveFallback() is custom.current_fallback_handler
    assert {MYT, FGJ, SY, SY2} <= set(blocked)
    world.dispatch()
    assert world.calls == [(SY, 0)]
    old()
    assert world.calls == [(SY, 0)], "Old generation callback must stay inert after new dispatch"


@pytest.mark.parametrize("skill_id,slot", [(SY, 2), (SY, 8), (SY2, 3)])
def test_dynamic_sy_identity_and_one_admission(world: _World, skill_id: int, slot: int) -> None:
    world.bar = [HR, MYT, FGJ, TOF, 0, 0, 0, 0]
    world.bar[slot - 1] = skill_id
    world.pressure()
    assert world.policy.TryCast()
    assert world.owner.DidTickSucceed()
    assert not world.policy.TryCast(preparation=True)
    world.dispatch()
    assert world.calls == [(skill_id, 0)]
    assert world.owner._is_local_cast_pending()


def test_disabled_preferred_sy_does_not_hide_other_identity(world: _World) -> None:
    world.bar[6] = SY2
    world.owner._cached_data.account_options.Skills[world.slot(SY) - 1] = False
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    assert world.calls == [(SY2, 0)]


def test_disabled_sy_owns_supports_but_absent_sy_preserves_stock(world: _World) -> None:
    world.pressure(raw=0)
    world.owner._cached_data.account_options.Skills[1] = False
    _finish(world.owner._run_combat())
    assert not world.queue and not world.ordinary
    assert "Make_Your_Time" not in world.trace and "For_Great_Justice" not in world.trace
    world.bar[1] = 0
    world.trace.clear()
    _finish(world.owner._run_combat())
    assert (MYT, 1) in world.ordinary
    assert "Make_Your_Time" in world.trace
    assert {MYT, FGJ, SY, SY2} <= set(world.owner.GetBlockedSkills())


def test_unknown_remote_hold_uses_dispatch_time_and_does_not_extend(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    dispatched = world.now
    world.now += 150
    world.raw[SY] = 0
    world.policy.Advance()
    assert world.policy.last_outcome == "sy_resource_consequence"
    assert world.policy._deadline(world.now) == dispatched + 3500
    world.now = dispatched + 751
    world.policy.Advance()
    assert world.policy._deadline(world.now) == dispatched + 3500
    world.raw[SY] = 100
    assert not world.policy.TryCast()
    world.now = dispatched + 3500
    assert world.policy.TryCast()


def test_native_acceptance_alone_and_late_resource_are_not_success(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    world.now += 751
    world.raw[SY] = 0
    world.policy.Advance()
    assert not world.policy._holds
    assert world.policy.last_outcome == "observation_unresolved"
    assert world.policy._retry["sy"].failures == 1


def test_intervening_stock_action_prevents_resource_attribution(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    world.dispatch()
    world.owner._mark_local_cast_pending(250)
    world.now += 150
    world.raw[SY] = 0
    world.policy.Advance()
    assert not world.policy._holds


@pytest.mark.parametrize(
    "result,outcome", [(False, "native_false"), (RuntimeError("native stub failure"), "native_exception")]
)
def test_native_outcomes_backoff_and_no_cleanup_of_new_timer(world: _World, result: Any, outcome: str) -> None:
    world.pressure()
    world.native_result = result
    assert world.policy.TryCast()
    world.dispatch()
    assert world.policy.last_outcome == outcome
    assert world.policy._retry["sy"].not_before == world.now + 1000
    world.now += 1000
    assert world.policy.TryCast()
    world.dispatch()
    assert world.policy._retry["sy"].not_before == world.now + 5000


def test_expiry_releases_reservation_and_old_callback_cannot_clear_new(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    old = world.queue.pop(0)
    world.now += 250
    assert not world.policy.Advance()
    assert world.policy.last_outcome == "queue_expired"
    world.now += 1000
    assert world.policy.TryCast()
    newer = world.policy._request
    old()
    assert world.policy._request is newer and not world.calls
    world.dispatch()
    assert world.calls == [(SY, 0)]


@pytest.mark.parametrize("change", ["toggle", "bar", "map", "party", "energy", "casting", "custom", "weapon", "shout"])
def test_final_dispatch_revalidates_guards(world: _World, change: str) -> None:
    world.pressure(raw=0)
    assert world.policy.TryCast(preparation=True)
    if change == "toggle":
        world.owner._cached_data.account_options.Skills[world.slot(MYT) - 1] = False
    elif change == "bar":
        world.bar[world.slot(MYT) - 1] = 0
    elif change == "map":
        world.map_id += 1
    elif change == "party":
        world.party_id += 1
    elif change == "energy":
        world.energy = 1
    elif change == "casting":
        world.casting[1] = 42
    elif change == "custom":
        world.owner.GetCustomSkill(MYT).Conditions.LessSelfEnergyPercentage = 0.5
    elif change == "weapon":
        world.owner.GetCustomSkill(MYT).Conditions.RequireWeapon = "Sword"
    else:
        world.add_effect(1, world.core.Skill.GetID("Vocal_Minority"), 10000)
    world.dispatch()
    assert not world.calls, f"Final {change} change must reject the native call"
    assert world.policy._retry["myt"].failures == 0


def test_superseded_myt_is_benign_and_fgj_needs_its_effect(world: _World) -> None:
    world.pressure(raw=0)
    assert world.policy.TryCast(preparation=True)
    world.raw[SY] = 100
    world.dispatch()
    assert world.policy.last_outcome == "preparation_superseded"
    assert world.policy._retry["myt"].failures == 0
    assert not world.calls
    world.raw[SY] = 0
    world.recharge[MYT] = 1
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    world.now += 150
    world.raw[SY] = 20
    world.policy.Advance()
    assert world.policy.last_outcome == "submitted"
    world.add_effect(1, FGJ, 20000, 2)
    world.now += 150
    world.policy.Advance()
    assert world.policy.last_outcome == "fgj_observed_effect"


def test_partial_myt_latch_and_independent_fgj(world: _World) -> None:
    world.pressure(raw=0)
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    world.now += 150
    world.raw[SY] = 20
    world.policy.Advance()
    assert world.policy.last_outcome == "myt_observed_progress"
    world.now += 100
    world.attacking.discard(1)
    assert not world.policy.TryCast(preparation=True)
    world.attacking.add(1)
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    assert [skill_id for skill_id, _ in world.calls] == [MYT, FGJ]


def test_myt_no_progress_has_bounded_retry_and_pressure_flicker_preserves_streak(world: _World) -> None:
    world.pressure(raw=0)
    world.bar[world.slot(FGJ) - 1] = 0
    world.policy.Advance()
    world.now += 150
    world.health[3] = 0.5
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    world.now += 750
    world.policy.Advance()
    retry = world.policy._retry["myt"]
    assert retry.failures == 1
    world.owner._cached_data.data.in_aggro = False
    world.policy.Advance()
    world.owner._cached_data.data.in_aggro = True
    world.policy.Advance()
    assert retry.failures == 1 and not world.policy._myt_latched


@pytest.mark.parametrize("energy,imminent,expected", [(19.9, True, False), (20, True, True), (10, False, True)])
def test_dynamic_energy_obligation(world: _World, energy: float, imminent: bool, expected: bool) -> None:
    world.pressure(raw=0)
    world.energy = energy
    # Refresh the same native effect id, rather than add an overlapping instance.
    world.add_effect(1, TOF, 1500 if imminent else 10000, timestamp=2)
    world.policy.Advance()
    assert world.policy._energy_available(MYT, world.now) is expected


def test_unavailable_hr_spread_still_reserves_and_no_casting_probe(world: _World) -> None:
    world.pressure(raw=0)
    world.hr_target = 2
    world.recharge[HR] = 1
    world.energy = 24
    assert not world.policy._energy_available(MYT, world.now)
    assert not world.ordinary and not world.queue
    world.hr_target = 0
    assert world.policy._energy_available(MYT, world.now)
    world.costs[MYT] = 40
    assert not world.policy._energy_available(MYT, world.now)
    world.costs[MYT] = 5
    assert world.policy._energy_available(MYT, world.now)


def test_pressure_baseline_old_low_health_and_caster_only(world: _World) -> None:
    world.health[2] = 0.3
    world.policy.Advance()
    world.now += 150
    world.health[1] = 0.1
    world.policy.Advance()
    assert not world.policy._pressure
    world.now += 150
    world.health[2] = 0.28
    world.policy.Advance()
    assert world.policy._pressure


def test_spread_requires_recent_losses_and_processes_each_sample_once(world: _World) -> None:
    world.policy.Advance()
    world.now += 150
    world.health[2] = 0.94
    world.policy.Advance()
    assert not world.policy._pressure
    world.now += 150
    world.health[3] = 0.94
    world.policy.Advance()
    assert world.policy._pressure
    world.attacking.clear()
    world.now += 2000
    world.policy.Advance()
    assert not world.policy._pressure
    world.attacking.add(90)
    world.policy.Advance()
    assert not world.policy._pressure


def test_bip_excludes_only_its_recipient_and_does_not_cancel_active_episode(world: _World) -> None:
    world.policy.Advance()
    world.casting[2] = BIP
    world.now += 150
    world.health[2] = 0.5
    world.policy.Advance()
    assert not world.policy._pressure
    world.now += 150
    world.health[3] = 0.5
    world.policy.Advance()
    assert world.policy._pressure
    world.casting[3] = BIP
    world.now += 150
    world.policy.Advance()
    assert world.policy._pressure


def test_max_health_change_exclusion_and_successful_mitigation(world: _World) -> None:
    world.policy.Advance()
    world.now += 150
    world.maximum[2] = 400
    world.health[2] = 0.5
    world.policy.Advance()
    assert not world.policy._pressure
    world.now += 150
    world.health[3] = 0.5
    world.policy.Advance()
    world.now += 10000
    world.policy.Advance()
    assert world.policy._pressure, "Continuing hostile activity intentionally maintains the episode"


def test_newcomer_and_resurrection_do_not_inherit_hold(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    world.dispatch()
    world.now += 150
    world.raw[SY] = 0
    world.policy.Advance()
    assert world.policy._deadline(world.now) > world.now
    world.roster.append(4)
    world.health[4] = 1.0
    world.policy.Advance()
    assert world.policy._deadline(world.now) == world.now
    world.roster.remove(4)
    world.dead.add(2)
    world.policy.Advance()
    world.dead.remove(2)
    world.policy.Advance()
    assert (2, 1) in world.policy._recipients
    assert world.policy._deadline(world.now) == world.now


def test_positive_local_duplicates_age_without_consumer_refresh(world: _World) -> None:
    world.heroes = [2, 3]
    for recipient in world.heroes:
        world.add_effect(recipient, SY2, 4000)
    world.pressure()
    deadline = world.policy._deadline(world.now)
    assert not world.policy.TryCast()
    world.now += 1000
    world.policy.Advance()
    assert world.policy._deadline(world.now) == deadline
    world.effects[2] = []
    world.policy.Advance()
    assert world.policy._deadline(world.now) == deadline
    world.add_effect(3, SY2, 0)
    world.policy.Advance()
    assert world.policy._deadline(world.now) <= world.now


def test_normal_reset_completion_and_rapid_reenable(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    generation = world.owner.GetPolicyGeneration()
    world.driver.ResetTickExecution()
    assert world.owner.GetPolicyGeneration() == generation
    world.dispatch()
    assert world.calls == [(SY, 0)]
    world.now += 751
    world.policy.Advance()
    world.now += 1000
    assert world.policy.TryCast()
    world.driver.InvalidateContractPolicyWork()
    world.owner.OnContractActivated(world.owner._cached_data)
    world.dispatch()
    assert world.calls == [(SY, 0)]
    assert world.owner.GetPolicyGeneration() > generation


def test_cleanup_failure_invalidates_before_close_and_preserves_exception(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    before = world.owner.GetPolicyGeneration()
    seen: list[int] = []
    world.driver._tick_coroutine = SimpleNamespace(close=lambda: seen.append(world.owner.GetPolicyGeneration()))

    def fail(reason: str) -> None:
        raise RuntimeError(reason)

    world.owner.Dispose = fail
    with pytest.raises(RuntimeError, match="contract_cleared"):
        world.driver.ClearBuildContract()
    assert seen and seen[0] > before
    world.dispatch()
    assert not world.calls


def test_stock_hr_bootstrap_spread_recovery_and_ooc_upkeep(world: _World) -> None:
    world.owner._cached_data.data.in_aggro = False
    world.leadership = 16
    assert _finish(world.owner._run_ooc())
    assert world.ordinary[-1] == (HR, 1)
    assert world.restored == [90]
    world.now += 250
    world.recharge[HR] = 1
    assert _finish(world.owner._run_ooc())
    assert len(world.ordinary) == 1, "Waiting for the actual bootstrap postcondition must not cast ToF"
    world.leadership = 20
    world.recharge[HR] = 0
    world.hr_target = 2
    assert _finish(world.owner._run_ooc())
    assert world.ordinary[-1] == (HR, 2)
    world.now += 250
    world.hr_target = 0
    world.effects[1] = [e for e in world.effects[1] if e.skill_id != TOF]
    assert _finish(world.owner._run_ooc())
    assert world.ordinary[-1] == (TOF, 1)
    world.now += 250
    world.effects[1] = []
    assert _finish(world.owner._run_ooc())
    assert world.ordinary[-1] == (HR, 1)


def test_tntf_precedes_uncertain_preparation_and_observation_does_not_block(world: _World) -> None:
    world.pressure(raw=0)
    world.casts.add("Theres_Nothing_to_Fear")
    _finish(world.owner._run_combat_phase())
    assert not world.queue
    world.casts.clear()
    _finish(world.owner._run_combat_phase())
    assert len(world.queue) == 1
    world.dispatch()
    world.now += 250
    world.casts.add("Theres_Nothing_to_Fear")
    world.trace.clear()
    _finish(world.owner._run_combat_phase())
    assert "Theres_Nothing_to_Fear" in world.trace
    assert world.policy._request is not None, "Resource observation is still pending without owning the rotation"


def test_queued_reservation_covers_actual_phase_and_fallback(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    fallback = SimpleNamespace(
        ApplyBlockedSkillIDs=_ignore, ProcessCombat=lambda: (world.trace.append("fallback") for _ in range(1))
    )
    world.owner.current_fallback_handler = fallback
    _finish(world.owner.ProcessCombat())
    assert world.owner.DidTickSucceed()
    assert "fallback" not in world.trace and not world.ordinary
    world.now += 250
    world.owner._cached_data.data.in_aggro = False
    _finish(world.owner.ProcessCombat())
    assert "fallback" in world.trace


def test_monitor_clock_domain_and_midnight_baseline(world: _World) -> None:
    world.monitor_offset = 12345678
    world.pressure()
    assert world.policy._pressure
    world.owner._cached_data.data.in_aggro = False
    world.policy.Advance()
    world.owner._cached_data.data.in_aggro = True
    world.owner.ResetPartyHealthMonitor()
    world.policy._health.clear()
    world.monitor_offset = 86400000 - world.now - 100
    world.policy.Advance()
    world.now += 150
    world.health[2] = 0.4
    world.policy.Advance()
    assert not world.policy._pressure, "Midnight is a new baseline, not a new loss"
    world.now += 150
    world.health[2] = 0.35
    world.policy.Advance()
    assert world.policy._pressure


def test_pressure_end_cancels_only_unsubmitted_work(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    world.owner._cached_data.data.in_aggro = False
    world.dispatch()
    assert world.policy.last_outcome == "demand_cancelled"
    assert not world.calls and world.policy._retry["sy"].failures == 0
    world.owner._cached_data.data.in_aggro = True
    world.now += 150
    world.health[3] = 0.5
    assert world.policy.TryCast()
    world.dispatch()
    world.owner._cached_data.data.in_aggro = False
    world.now += 150
    world.raw[SY] = 0
    world.policy.Advance()
    assert world.policy._holds and world.policy.last_outcome == "sy_resource_consequence"
    assert not world.policy.TryCast(preparation=True)


def test_precall_raw_snapshot_and_fresh_readiness_override_retained_cache(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    world.raw[SY] = 120
    world.dispatch()
    assert world.policy._request.pre_adrenaline == 120
    world.now += 100
    world.raw[SY] = 100
    world.policy.Advance()
    assert world.policy.last_outcome == "sy_resource_consequence"
    world.now += 3500
    world.raw[SY] = 0

    # Retained GLOBAL_CACHE metadata says ready; fresh SkillBar does not.
    def retained_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(adrenaline_a=100, recharge=0)

    world.core.GLOBAL_CACHE.SkillBar.GetSkillData = retained_data
    assert not world.policy.TryCast()


def test_positive_sy_effect_can_settle_without_claiming_remote_coverage(world: _World) -> None:
    world.heroes = [2]
    world.pressure()
    world.policy.TryCast()
    world.dispatch()
    world.add_effect(2, SY, 4000, 77)
    world.now += 100
    world.policy.Advance()
    assert world.policy.last_outcome == "sy_observed_effect"
    assert not world.policy._holds
    assert world.policy._deadline(world.now) == world.now, "Remote recipient 3 remains unknown"


def test_queue_exception_is_distinct_and_cannot_leave_reservation(world: _World) -> None:
    world.pressure()

    def fail(callback: Any) -> None:
        raise RuntimeError("queue unavailable")

    world.core.GLOBAL_CACHE.SkillBar.QueueGuardedUseSkill = fail
    assert not world.policy.TryCast()
    assert world.policy.last_outcome == "queue_exception"
    assert not world.policy.Advance()


def test_existing_other_timer_is_never_cleared_by_old_callback(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    old = world.queue.pop()
    world.owner.InvalidatePolicyWork()
    world.owner._mark_local_cast_pending(2000)
    deadline = world.owner._local_cast_timer.deadline
    old()
    assert not world.calls
    assert world.owner._local_cast_timer.deadline == deadline


def test_actual_tick_completion_keeps_accepted_callback(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    before = world.owner.GetPolicyGeneration()
    world.driver._tick_coroutine = iter(())
    world.driver._tick_phase = True
    world.driver._tick_contract_signature = world.driver._get_contract_signature()
    next(world.driver.Tick(True))
    assert world.driver._tick_coroutine is None
    assert world.owner.GetPolicyGeneration() == before
    world.dispatch()
    assert world.calls == [(SY, 0)]


def test_cached_owner_reactivation_and_unrelated_lifecycle_counts(world: _World) -> None:
    world.pressure()
    world.policy.TryCast()
    calls: list[str] = []
    activate = world.owner.OnContractActivated

    def on_activate(data: Any) -> None:
        calls.append("activate")
        activate(data)

    def on_dispose(reason: str) -> None:
        calls.append("dispose")

    world.owner.OnContractActivated = on_activate
    world.owner.Dispose = on_dispose
    world.driver._build_registry._iter_matchable_builds = lambda: [world.owner]
    world.bar[7] = 12345
    assert world.driver.EnsureBuildContract() is world.owner
    assert calls == ["activate"], "Cached same-owner reselection must not add a disposal call"
    world.dispatch()
    assert not world.calls
    base = world.owner.__class__.__bases__[0]
    other = base(name="unrelated")
    other.Dispose = calls.append
    world.driver._contract_build = other
    world.driver.ClearBuildContract()
    assert calls == ["activate", "contract_cleared"]


def _headless(world: _World, monkeypatch: pytest.MonkeyPatch) -> Any:
    _module(monkeypatch, "Py4GWCoreLib.Routines", Routines=world.core.Routines)
    _module(monkeypatch, "Py4GWCoreLib.HeroAI.cache_data", CacheData=object)
    _module(monkeypatch, "Py4GWCoreLib.HeroAI.follow").__path__ = []
    _module(
        monkeypatch,
        "Py4GWCoreLib.HeroAI.follow.follower_runtime",
        FollowExecutionState=object,
        execute_follower_follow=_ignore,
        get_follow_destination_distance=_zero,
        is_follow_recovery_active=_false,
    )
    _module(monkeypatch, "Py4GWCoreLib.HeroAI.resurrection_scroll")
    _module(monkeypatch, "Py4GWCoreLib.HeroAI.settings", Settings=object)
    _module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.system_settings").__path__ = []
    _module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters", LootFilters=object)
    _module(monkeypatch, "Py4GWCoreLib.routines_src.BehaviourTrees", BehaviorTree=SimpleNamespace(NodeState=_State))
    sys.modules["Py4GWCoreLib.HeroAI.utils"].__dict__["DrawSharedMemoryFlags"] = lambda: None
    world.core.ActionQueueManager = object
    world.core.SharedCommandType = SimpleNamespace()
    module = _load(monkeypatch, "Py4GWCoreLib.HeroAI.headless_tree", "Py4GWCoreLib/HeroAI/headless_tree.py")
    tree = object.__new__(module.HeroAIHeadlessTree)
    tree.heroai_build = world.driver
    tree.cached_data = world.owner._cached_data
    tree._headless_combat_enabled = True
    tree._follow_state = object()
    return tree


load_headless_tree = _headless


def test_headless_no_generator_disable_and_rapid_reenable(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = _headless(world, monkeypatch)
    world.pressure()
    world.policy.TryCast()
    assert world.driver._tick_coroutine is None
    tree.SetCombatEnabled(False)
    tree.SetCombatEnabled(True)
    world.dispatch()
    assert not world.calls


def test_widget_disable_and_observed_option_suppression(world: _World) -> None:
    from test_heroai_movement_dispatch import load_widget_module

    widget: Any = load_widget_module()
    widget.heroai_build = world.driver
    world.pressure()
    world.policy.TryCast()
    widget.on_disable()
    world.dispatch()
    assert not world.calls
    world.now += 150
    world.health[3] = 0.5
    assert world.policy.TryCast()
    world.owner._cached_data.account_options.Combat = False
    assert not widget.HandleCombat(world.owner._cached_data)
    world.owner._cached_data.account_options.Combat = True
    world.dispatch()
    assert not world.calls


def test_headless_observed_suppression_invalidates_before_reset(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = _headless(world, monkeypatch)
    world.pressure()
    world.policy.TryCast()
    tree.cached_data.account_options.Combat = False
    before = world.owner.GetPolicyGeneration()
    seen: list[int] = []
    world.driver._tick_coroutine = SimpleNamespace(close=lambda: seen.append(world.owner.GetPolicyGeneration()))
    assert not tree._handle_combat()
    assert seen[0] > before
    tree.cached_data.account_options.Combat = True
    world.dispatch()
    assert not world.calls


def test_repeated_protection_cycles_use_all_three_and_retain_resource_gap(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    first = world.now
    world.raw[SY] = 0
    world.now += 150
    world.policy.Advance()
    world.now = first + 250
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    assert world.calls[-1][0] == FGJ
    world.add_effect(1, FGJ, 20000, 2)
    world.recharge[FGJ] = 1
    world.now += 150
    world.policy.Advance()
    world.now = first + 2000
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    world.raw[SY] = 40  # Explicit partial observation, not a prediction of MYT's gain/cap.
    world.recharge[MYT] = 1
    world.now += 150
    world.policy.Advance()
    world.now = first + 3300
    world.raw[SY] = 100
    assert not world.policy.TryCast()
    world.now = first + 3500
    assert world.policy.TryCast()
    world.dispatch()
    second = world.now
    world.raw[SY] = 0
    world.now += 150
    world.policy.Advance()
    world.now = second + 4000
    assert not world.policy.TryCast()
    assert not world.policy.TryCast(preparation=True)
    assert world.policy._deadline(world.now) < world.now, "Unready resources leave a modeled coverage gap"
    world.raw[SY] = 100
    assert world.policy.TryCast()
    world.dispatch()
    world.raw[SY] = 0
    world.now += 150
    world.policy.Advance()
    world.now = first + 22000
    world.effects[1] = [e for e in world.effects[1] if e.skill_id != FGJ]
    world.recharge[FGJ] = 0
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    assert [skill_id for skill_id, _ in world.calls] == [SY, FGJ, MYT, SY, SY, FGJ]


def test_nontrio_stock_call_order_is_unchanged(world: _World) -> None:
    world.owner.IsSkillEquipped = _true
    world.owner.AutoAttack = lambda: (world.trace.append("AutoAttack") for _ in range(1))
    _finish(world.owner._run_combat())
    assert world.trace == [
        "Angelic_Protection",
        "Theres_Nothing_to_Fear",
        "Aria_of_Zeal",
        "Aria_of_Restoration",
        "Stand_Your_Ground",
        "Never_Surrender",
        "Protectors_Defense",
        "To_the_Limit",
        "Go_for_the_Eyes",
        "Find_Their_Weakness",
        "Lyric_of_Zeal",
        "Ebon_Vanguard_Assassin_Support",
        "Ebon_Battle_Standard_of_Honor",
        "Ebon_Battle_Standard_of_Wisdom",
        "Great_Dwarf_Weapon",
        "Breath_of_the_Great_Dwarf",
        "You_Move_Like_a_Dwarf",
        "Finish_Him",
        "Mending_Refrain",
        "Bladeturn_Refrain",
        "Energizing_Finale",
        "Burning_Refrain",
        "Blazing_Finale",
        "Hasty_Refrain",
        "Vicious_Attack",
        "Mighty_Throw",
        "Spear_of_Redemption",
        "AutoAttack",
    ]


def test_ready_sy_precedes_tntf_and_post_submission_guard_is_local(world: _World) -> None:
    world.pressure()
    world.casts.add("Theres_Nothing_to_Fear")
    _finish(world.owner._run_combat_phase())
    assert len(world.queue) == 1 and "Theres_Nothing_to_Fear" not in world.trace
    world.dispatch()
    assert not world.owner.CanCastSkillID(TNTF)
    world.now += 250
    assert world.owner.CanCastSkillID(TNTF)


def test_support_recharge_is_revalidated_from_fresh_snapshot(world: _World) -> None:
    world.pressure(raw=0)
    assert world.policy.TryCast(preparation=True)
    original = world.core.GLOBAL_CACHE.SkillBar.GetSkillData

    def retained_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(adrenaline_a=0, recharge=0)

    world.core.GLOBAL_CACHE.SkillBar.GetSkillData = retained_data
    world.recharge[MYT] = 1
    world.dispatch()
    assert not world.calls
    world.core.GLOBAL_CACHE.SkillBar.GetSkillData = original


def test_missing_optional_supports_and_candidate_gate(world: _World) -> None:
    world.bar[world.slot(MYT) - 1] = 0
    world.pressure(raw=0)
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    assert world.calls == [(FGJ, 0)]
    world.now += 751
    world.policy.Advance()
    world.bar[world.slot(FGJ) - 1] = MYT
    world.roster = [1, 2]
    world.policy.Advance()
    world.now += 150
    world.health[2] = 0.4
    assert not world.policy.TryCast(preparation=True), "Retain the stock MYT candidate count gate"


def test_replayed_callback_cannot_submit_again_after_dispatch_guard(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    callback = world.queue[0]
    world.dispatch()
    world.now += 250
    callback()
    assert world.calls == [(SY, 0)], "A still-observing request must not submit twice"
    assert world.policy.last_outcome == "submitted"


def test_queue_expiry_during_final_validation_does_not_submit(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    admit = world.owner.AdmitPolicySkill

    def slow_admission(skill_id: int, target: int) -> bool:
        accepted = bool(admit(skill_id, target))
        world.now += 250
        return accepted

    world.owner.AdmitPolicySkill = slow_admission
    world.dispatch()
    assert not world.calls
    assert world.policy.last_outcome == "queue_expired"
    assert not world.owner._is_local_cast_pending()


@pytest.mark.parametrize("combat", [True, False])
@pytest.mark.parametrize("early_evidence", [True, False])
def test_dispatch_guard_covers_fallback_even_after_early_evidence(
    world: _World, combat: bool, early_evidence: bool
) -> None:
    world.pressure()
    for skill_id in (MYT, FGJ):
        world.owner._cached_data.account_options.Skills[world.slot(skill_id) - 1] = False
    assert world.policy.TryCast()
    world.dispatch()
    dispatched = world.now

    def fallback_phase() -> Generator[None, None, None]:
        yield world.trace.append("fallback")

    world.owner.current_fallback_handler = SimpleNamespace(
        ApplyBlockedSkillIDs=_ignore, ProcessCombat=fallback_phase, ProcessOOC=fallback_phase
    )
    world.owner._cached_data.data.in_aggro = combat
    phase = world.owner.ProcessCombat if combat else world.owner.ProcessOOC
    world.now += 150
    if early_evidence:
        world.raw[SY] = 0
    _finish(phase())
    assert "fallback" not in world.trace
    assert world.owner.DidTickSucceed()
    world.now = dispatched + 250
    _finish(phase())
    assert "fallback" in world.trace, "Observation must release the rotation at the guard deadline"


def test_fallback_handoff_prevents_later_resource_attribution(world: _World) -> None:
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()

    def fallback_phase() -> Generator[None, None, None]:
        world.raw[SY] = 0
        yield world.trace.append("fallback")

    world.owner.current_fallback_handler = SimpleNamespace(ApplyBlockedSkillIDs=_ignore, ProcessCombat=fallback_phase)
    world.now += 250
    _finish(world.owner.ProcessCombat())
    assert "fallback" in world.trace
    world.now += 150
    world.policy.Advance()
    assert not world.policy._holds, "Fallback spending is not evidence of this owner's SY expenditure"
    assert world.policy.last_outcome == "submitted"


def test_small_loss_endangered_entry_uses_actual_decaying_monitor(world: _World) -> None:
    world.policy.Advance()
    entries: list[int] = []
    drops: list[float] = []
    for sample in range(1, 61):
        world.now += 150
        world.health[2] = 1.0 - sample * 0.009
        world.policy.Advance()
        drops.append(world.owner.GetPartyHealthDelta(2))
        if world.policy._pressure:
            entries.append(sample)
    assert isclose(world.health[2], 0.46, abs_tol=1e-12)
    assert max(drops) < 0.10, "The real decaying monitor never reaches the spike threshold in this sequence"
    assert entries and entries[0] == 45, f"Expected endangered entry at 59.5% health; entries={entries}, drops={drops}"
    assert world.policy.TryCast(), "Continuing qualifying pressure must reach actual SY admission"


def test_small_loss_spread_entry_uses_actual_decaying_monitor(world: _World) -> None:
    world.policy.Advance()
    entries: list[int] = []
    for sample in range(1, 31):
        world.now += 150
        for recipient in (2, 3):
            world.health[recipient] = 1.0 - sample * 0.009
        world.policy.Advance()
        if world.policy._pressure:
            entries.append(sample)
    assert all(isclose(world.health[recipient], 0.73, abs_tol=1e-12) for recipient in (2, 3))
    assert all(0.05 < world.owner.GetPartyHealthDelta(recipient) < 0.10 for recipient in (2, 3))
    assert entries and entries[0] == 12, f"Expected fresh spread entry at sample 12; entries={entries}"


@pytest.mark.parametrize("observation", ["first_low", "same_sample", "unchanged", "healing"])
def test_small_loss_requires_a_fresh_event(world: _World, observation: str) -> None:
    if observation == "first_low":
        world.health[2] = 0.46
        world.policy.Advance()
    else:
        world.attacking.discard(90)
        world.policy.Advance()
        world.now += 150
        world.health[2] = 0.55
        world.policy.Advance()
        assert world.owner.GetPartyHealthDelta(2) > 0.10
        assert not world.policy._pressure
        world.attacking.add(90)
        if observation != "same_sample":
            world.now += 150
        if observation == "healing":
            world.health[2] += 0.009
        world.policy.Advance()
    assert not world.policy._pressure, f"{observation} must not manufacture a new loss"
    assert not world.policy.TryCast()


def test_small_loss_keeps_trigger_thresholds_and_ignores_only_numerical_noise(world: _World) -> None:
    world.policy.Advance()
    world.now += 150
    world.health[2] = 0.991
    world.policy.Advance()
    assert not world.policy._pressure, "One small loss at high health is below every trigger threshold"
    world.attacking.discard(90)
    world.now += 150
    world.health[2] = 0.59
    world.policy.Advance()
    world.attacking.add(90)
    world.now += 150
    world.health[2] -= 1e-10
    world.policy.Advance()
    assert not world.policy._pressure, "Floating-point noise must not turn old loss into an event"
    world.now += 150
    world.health[2] -= 1e-6
    world.policy.Advance()
    assert world.policy._pressure, "Fresh loss must not require a gameplay-sized minimum step"


@pytest.mark.parametrize("skill_id", [SY, SY2])
@pytest.mark.parametrize("long_first", [True, False])
def test_effect_instances_overlap_and_reordered_stale_entries(world: _World, skill_id: int, long_first: bool) -> None:
    world.heroes = [2, 3]
    world.pressure()
    observed = world.now
    durations = (4000, 200) if long_first else (200, 4000)
    for identity, remaining in enumerate(durations, 1):
        world.add_effect(2, skill_id, remaining, identity, append=True)
    world.add_effect(3, skill_id, 6000, 3)
    world.policy.Advance()
    assert world.policy._deadline(world.now) == observed + 3500
    assert not world.policy.TryCast(), "A short overlapping instance must not erase the long instance"
    world.now += 250
    world.policy.Advance()
    assert world.policy._deadline(world.now) == observed + 3500
    world.now = observed + 5000
    world.effects[2].reverse()
    world.policy.Advance()
    assert world.policy._deadline(world.now) <= world.now, "Reordering expired snapshots must not restart their ages"
    assert world.policy.TryCast()


@pytest.mark.parametrize("skill_id", [SY, SY2])
def test_effect_instances_stale_reappearance_after_pruning_and_new_incarnation(world: _World, skill_id: int) -> None:
    world.roster = [1, 2]
    world.heroes = [2]
    world.pressure()
    world.add_effect(2, skill_id, 4000, 7, timestamp=100)
    world.policy.Advance()
    world.effects[2] = []
    world.now += 5000
    world.policy.Advance()
    assert world.policy._deadline(world.now) <= world.now
    world.add_effect(2, skill_id, 4000, 7, timestamp=100)
    world.policy.Advance()
    assert world.policy._deadline(world.now) <= world.now, "Disappearance and pruning must not revive this identity"
    world.add_effect(2, skill_id, 4000, 7, timestamp=101)
    world.policy.Advance()
    assert world.policy._deadline(world.now) == world.now + 3500
    assert not world.policy.TryCast(), "A genuinely new incarnation can supply new positive evidence"


def test_effect_instances_aggregate_per_recipient_then_across_party(world: _World) -> None:
    world.heroes = [2, 3]
    world.pressure()
    observed = world.now
    world.add_effect(2, SY, 6000, 1)
    world.add_effect(2, SY2, 1000, 2, append=True)
    world.add_effect(3, SY2, 200, 3)
    world.add_effect(3, SY, 4000, 4, append=True)
    world.policy.Advance()
    assert (
        world.policy._deadline(world.now) == observed + 3500
    ), "Use max expiry within each recipient, then min across recipients"
    world.now = observed + 3499
    assert not world.policy.TryCast()
    world.now += 1
    assert world.policy.TryCast(), "The 500-ms refresh margin applies exactly once"


def test_effect_instances_pruning_is_bounded_without_relearning_retired_snapshots(world: _World) -> None:
    world.roster = [1, 2]
    world.heroes = [2]
    world.pressure()
    for identity in range(1, 101):
        world.add_effect(2, SY, 1, identity)
        world.policy.Advance()
        world.now += 2
    world.effects[2] = []
    world.policy.Advance()
    assert len(world.policy._effects) <= 65, "Expired observations must not grow an unbounded history"
    world.add_effect(2, SY, 4000, 1)
    world.policy.Advance()
    assert world.policy._deadline(world.now) <= world.now
    world.add_effect(2, SY, 4000, 101)
    world.policy.Advance()
    assert world.policy._deadline(world.now) == world.now + 3500


@pytest.mark.parametrize("obligation", [HR, TOF])
def test_upkeep_toggle_disabled_obligation_allows_ten_energy_myt(world: _World, obligation: int) -> None:
    world.pressure(raw=0)
    world.energy = 10
    world.owner._cached_data.account_options.Skills[world.slot(obligation) - 1] = False
    if obligation == HR:
        world.hr_target = 2
    else:
        world.effects[1] = [effect for effect in world.effects[1] if effect.skill_id != TOF]
        world.now += 10000
    world.policy.Advance()
    assert world.owner.CanCastSkillID(MYT)
    assert world.policy._energy_available(MYT, world.now)
    assert not world.queue and not world.calls and not world.ordinary, "Reserve inspection must perform no action"
    _finish(world.owner._run_combat_phase())
    assert len(world.queue) == 1
    world.dispatch()
    assert world.calls == [(MYT, 1)]


@pytest.mark.parametrize("obligation", [HR, TOF])
def test_upkeep_toggle_recharging_obligation_keeps_adjusted_reserve(world: _World, obligation: int) -> None:
    if obligation == TOF:
        world.add_effect(1, TOF, 1500)
    world.pressure(raw=0)
    if obligation == HR:
        world.hr_target = 2
    world.recharge[obligation] = 1
    world.costs[obligation] = 12
    world.energy = 21.99
    assert not world.owner.CanCastSkillID(obligation)
    assert not world.policy._energy_available(MYT, world.now)
    world.energy = 22
    assert world.policy._energy_available(MYT, world.now)
    world.energy = 10
    slot = world.slot(obligation)
    world.owner._cached_data.account_options.Skills[slot - 1] = False
    assert world.policy._energy_available(MYT, world.now)
    world.owner._cached_data.account_options.Skills[slot - 1] = True
    assert not world.policy._energy_available(MYT, world.now)
    world.bar[slot - 1] = 0
    assert world.policy._energy_available(MYT, world.now)
    assert not world.queue and not world.calls and not world.ordinary


@pytest.mark.parametrize("obligation", [HR, TOF])
@pytest.mark.parametrize("enabled_at_dispatch", [True, False])
def test_upkeep_toggle_is_rechecked_at_dispatch(world: _World, obligation: int, enabled_at_dispatch: bool) -> None:
    if obligation == TOF:
        world.add_effect(1, TOF, 1500)
    world.pressure(raw=0)
    if obligation == HR:
        world.hr_target = 2
    slot = world.slot(obligation)
    world.recharge[obligation] = 1
    world.owner._cached_data.account_options.Skills[slot - 1] = not enabled_at_dispatch
    world.energy = 10 if enabled_at_dispatch else 25
    assert world.policy.TryCast(preparation=True)
    world.owner._cached_data.account_options.Skills[slot - 1] = enabled_at_dispatch
    world.energy = 10
    world.dispatch()
    assert world.calls == ([] if enabled_at_dispatch else [(MYT, 1)])
    assert world.policy._retry["myt"].failures == 0


def test_upkeep_toggle_disabled_hr_does_not_bypass_stock_bootstrap(world: _World) -> None:
    world.pressure(raw=0)
    world.leadership = 16
    world.owner._cached_data.account_options.Skills[world.slot(HR) - 1] = False
    _finish(world.owner._run_combat_phase())
    assert not world.queue and not world.calls and not world.ordinary


@pytest.mark.parametrize("second_skill", [SY, SY2])
def test_effect_instances_two_unchanged_four_second_entries_expire(world: _World, second_skill: int) -> None:
    world.roster = [1, 2]
    world.heroes = [2]
    world.pressure()
    observed = world.now
    world.add_effect(2, SY, 4000, 1)
    world.add_effect(2, second_skill, 4000, 2, append=True)
    world.policy.Advance()
    assert world.policy._deadline(world.now) == 13650 == observed + 3500
    world.now += 5000
    world.effects[2].reverse()
    world.policy.Advance()
    assert world.policy._deadline(world.now) <= world.now
    assert world.policy.TryCast(), "The reviewer's unchanged duplicate snapshots must not defer SY to 18650"


def test_effect_instances_active_budget_keeps_latest_expiry_and_rejects_evicted_replay(world: _World) -> None:
    world.roster = [1, 2]
    world.heroes = [2]
    world.pressure()
    observed = world.now
    for identity in range(1, 71):
        world.add_effect(2, SY, 4000 + identity, identity, append=True)
    world.policy.Advance()
    assert len(world.policy._effects) <= 65, "Bound active SY instances plus the self ToF observation"
    assert world.policy._deadline(world.now) == observed + 4070 - 500
    world.effects[2].reverse()
    world.now += 20
    world.policy.Advance()
    assert len(world.policy._effects) <= 65
    assert world.policy._deadline(world.now) == observed + 4070 - 500
    world.effects[2] = []
    world.now += 5000
    world.policy.Advance()
    world.add_effect(2, SY, 4000, 1)
    world.policy.Advance()
    assert world.policy._deadline(world.now) <= world.now, "Even a budget-evicted identity cannot be relearned"


def test_effect_instances_refresh_replaces_only_that_effect_id(world: _World) -> None:
    world.roster = [1, 2]
    world.heroes = [2]
    world.pressure()
    world.add_effect(2, SY, 6000, 7, timestamp=100)
    world.add_effect(2, SY, 2000, 8, timestamp=100, append=True)
    world.policy.Advance()
    world.now += 1000
    world.add_effect(2, SY, 4000, 7, timestamp=101)
    world.policy.Advance()
    assert (
        world.policy._deadline(world.now) == world.now + 3500
    ), "A new incarnation replaces the old incarnation of id 7"
    deadline = world.policy._deadline(world.now)
    world.add_effect(2, SY, 9000, 7, timestamp=100)
    world.policy.Advance()
    assert world.policy._deadline(world.now) == deadline, "An older incarnation must not replace the refreshed one"


def test_effect_instances_expired_positive_evidence_remains_distinct_from_own_hold(world: _World) -> None:
    world.roster = [1, 2]
    world.heroes = [2]
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    dispatched = world.now
    world.now += 150
    world.raw[SY] = 0
    world.add_effect(2, SY, 0, 9)
    world.policy.Advance()
    assert world.policy._holds[(2, 0)] == (dispatched + 3500, dispatched)
    assert (
        world.policy._deadline(world.now) <= world.now
    ), "Pruned expiry evidence must still qualify the applicable inferred hold"
    world.now += 150
    world.add_effect(2, SY2, 2000, 10)
    world.policy.Advance()
    assert world.policy._deadline(world.now) == world.now + 1500


@pytest.mark.parametrize("exclusion", ["bip", "maximum"])
def test_small_loss_exclusions_remain_per_recipient(world: _World, exclusion: str) -> None:
    world.health[2] = world.health[3] = 0.55
    world.policy.Advance()
    if exclusion == "bip":
        world.casting[2] = BIP
    else:
        world.maximum[2] = 400
    world.now += 150
    world.health[2] -= 0.009
    world.policy.Advance()
    assert not world.policy._pressure
    world.now += 150
    world.health[3] -= 0.009
    world.policy.Advance()
    assert world.policy._pressure, "One excluded recipient must not erase another recipient's small fresh loss"


def test_effect_instances_fgj_replay_cannot_settle_a_later_request(world: _World) -> None:
    world.pressure(raw=0)
    world.recharge[MYT] = 1
    world.add_effect(1, FGJ, 5000, 10, append=True)
    world.add_effect(1, FGJ, 200, 11, append=True)
    world.policy.Advance()
    assert not world.policy.TryCast(preparation=True), "Any still-active FGJ instance must suppress reapplication"
    world.now += 5000
    assert world.policy.TryCast(preparation=True)
    world.dispatch()
    world.now += 150
    world.policy.Advance()
    assert world.policy.last_outcome == "submitted", "Retired FGJ snapshots cannot confirm the new request"
    world.add_effect(1, FGJ, 20000, 12)
    world.now += 150
    world.policy.Advance()
    assert world.policy.last_outcome == "fgj_observed_effect"
