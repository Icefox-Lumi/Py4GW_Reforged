"""Offline controller contracts using the existing spirit-admission native stubs."""

from __future__ import annotations

import ast
import importlib
import sys
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest

pytest_plugins = ["test_restoration_spirit_admission"]
ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = "Py4GWCoreLib/Builds/Necromancer/N_Rt/"
IDS = [119, 962, 1234, 915, 1219, 1251, 981, 1365]
NAMES = [
    "Blood_is_Power",
    "Spirit_Transfer",
    "Mend_Body_and_Soul",
    "Spirit_Light",
    "Protective_Was_Kaolai",
    "Life",
    "Recuperation",
    "Signet_of_Lost_Souls",
]
admission: Any = importlib.import_module("test_restoration_spirit_admission")


def finish(coroutine: Generator[Any, None, Any]) -> Any:
    return admission._finish(coroutine)


def false(*_args: Any, **_kwargs: Any) -> bool:
    return False


def noop(*_args: Any, **_kwargs: Any) -> None:
    pass


def empty_group(_owner: Any) -> SimpleNamespace:
    return SimpleNamespace()


def empty_list() -> list[Any]:
    return []


def unlocked(allies: list[int], _key: int) -> list[int]:
    return allies


class Timer:
    now = 0

    def __init__(self, delay: int) -> None:
        self.delay = delay
        self.deadline: int | None = None

    def Stop(self) -> None:
        self.deadline = None

    def Reset(self) -> None:
        self.deadline = self.now + self.delay

    def SetThrottleTime(self, delay: int) -> None:
        self.delay = delay

    def IsStopped(self) -> bool:
        return self.deadline is None

    def IsExpired(self) -> bool:
        return self.deadline is not None and self.now >= self.deadline


@pytest.fixture
def runtime(world: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Real BuildMgr, HeroAI, SkillsTemplate and the four reached helper classes."""
    state = SimpleNamespace(
        bar=IDS.copy(),
        primary=4,
        secondary=8,
        name="Necromancer",
        agent=1,
        map=10,
        uptime=10000,
        agent_uptime=9000,
        valid=True,
        can_cast=True,
        aggro=True,
        attributes={},
    )
    core: Any = sys.modules["Py4GWCoreLib"]
    enums: Any = sys.modules["Py4GWCoreLib.enums_src.GameData_enums"]
    core.Profession = enums.Profession
    core.ThrottledTimer = Timer
    Timer.now = 0
    core.BuildMgr = sys.modules["Py4GWCoreLib.BuildMgr"].BuildMgr
    world.ids.update(dict(zip(NAMES, IDS)))
    world.ids["Blood_Ritual"] = 157
    core.Player.GetAgentID = lambda: state.agent
    core.Player.GetName = lambda: state.name
    core.Player.GetAccountEmail = lambda: "offline@example.invalid"
    core.Player.GetInstanceUptime = lambda: state.agent_uptime

    def professions(_agent: int) -> tuple[int, int]:
        return state.primary, state.secondary

    def max_health(_agent: int) -> int:
        return 500

    def equipped_skill(slot: int) -> int:
        return state.bar[slot - 1]

    def equipped_slot(skill: int) -> int:
        return state.bar.index(skill) + 1 if skill in state.bar else 0

    def in_aggro(_build: Any) -> bool:
        return state.aggro

    core.Agent.GetProfessions = professions
    core.Agent.IsKnockedDown = false
    core.Agent.GetMaxHealth = max_health
    core.Agent.IsHoldingItem = false
    core.Map = SimpleNamespace(
        IsExplorable=lambda: world.explorable,
        GetMapID=lambda: state.map,
        GetRegion=lambda: (1,),
        GetDistrict=lambda: 1,
        GetLanguage=lambda: (0,),
        GetInstanceUptime=lambda: state.uptime,
        IsInCinematic=lambda: False,
    )
    core.SkillBar.GetSkillIDBySlot = equipped_skill
    core.SkillBar.GetSlotBySkillID = equipped_slot
    monkeypatch.setattr(core.Routines.Checks.Map, "MapValid", staticmethod(lambda: state.valid))
    monkeypatch.setattr(core.Routines.Checks.Player, "CanAct", staticmethod(lambda: True))
    monkeypatch.setattr(core.Routines.Checks.Skills, "CanCast", staticmethod(lambda: state.can_cast))
    monkeypatch.setattr(core.BuildMgr, "IsInAggro", in_aggro)
    monkeypatch.setattr(core.BuildMgr, "IsCloseToAggro", false)
    behavior: Any = sys.modules["Py4GWCoreLib.py4gwcorelib_src.BehaviorTree"]
    behavior.BehaviorTree.NodeState = SimpleNamespace(
        SUCCESS=SimpleNamespace(name="SUCCESS"), FAILURE=SimpleNamespace(name="FAILURE")
    )

    def module(name: str, **attrs: Any) -> Any:
        return admission._module(monkeypatch, name, **attrs)

    def load(name: str, path: str) -> Any:
        return admission._load(monkeypatch, name, path)

    module("Py4GWCoreLib.Builds").__path__ = []
    module("Py4GWCoreLib.Builds.Any").__path__ = []
    module("Py4GWCoreLib.Builds.Skills").__path__ = []
    # Optional diagnostic code must be absent even when the generic controller
    # tries its lazy diagnostic import during the parity comparison.
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Builds.Skills.BipDiagnostic", None)
    locks = module(
        "Py4GWCoreLib.GlobalCache.WhiteboardLocks",
        BLOOD_ENERGY_BUFF_LOCK_KEY=1,
        is_buff_target_lock_blocked=false,
        post_buff_target_lock=noop,
        filter_unlocked_buff_targets=unlocked,
    )
    blood = load("_phase_a_blood", "Py4GWCoreLib/Builds/Skills/necromancer/BloodMagic.py")
    soul = load("_phase_a_soul", "Py4GWCoreLib/Builds/Skills/necromancer/SoulReaping.py")
    ashes = load("_phase_a_ashes", "Py4GWCoreLib/Builds/Skills/ritualist/NoAttribute.py")
    restoration = cast(Any, type(world.helper))

    def necromancer(owner: Any) -> SimpleNamespace:
        return SimpleNamespace(BloodMagic=blood.BloodMagic(owner), SoulReaping=soul.SoulReaping(owner))

    def ritualist(owner: Any) -> SimpleNamespace:
        return SimpleNamespace(RestorationMagic=restoration(owner), NoAttribute=ashes.NoAttribute(owner))

    for group in ("any", "warrior", "ranger", "Monk", "mesmer", "elementalist", "assassin", "paragon", "dervish"):
        module(f"Py4GWCoreLib.Builds.Skills.{group}", **{f"{group.capitalize()}Skills": empty_group})
    module(
        "Py4GWCoreLib.Builds.Skills.necromancer",
        NecromancerSkills=necromancer,
    )
    module(
        "Py4GWCoreLib.Builds.Skills.ritualist",
        RitualistSkills=ritualist,
    )
    template = load("Py4GWCoreLib.Builds.Skills.SkillsTemplate", "Py4GWCoreLib/Builds/Skills/SkillsTemplate.py")
    sys.modules["Py4GWCoreLib.Builds.Skills"].__dict__["SkillsTemplate"] = template.SkillsTemplate
    hero = load("Py4GWCoreLib.Builds.Any.HeroAI", "Py4GWCoreLib/Builds/Any/HeroAI.py")
    custom = load("Py4GWCoreLib.Builds.My Blood is Power", BUILD_DIR + "My Blood is Power.py")
    generic = load("Py4GWCoreLib.Builds.Blood is Power Healer", BUILD_DIR + "Blood is Power Healer.py")
    metadata = load(
        "Py4GWCoreLib.HeroAI.custom_skill_src.necromancer", "Py4GWCoreLib/HeroAI/custom_skill_src/necromancer.py"
    )
    metadata.NecromancerSkills(world.metadata)
    cast(Any, sys.modules["Py4GWCoreLib.HeroAI.custom_skill_src.ritualist"]).RitualistSkills(world.metadata)
    registry: Any = sys.modules["Py4GWCoreLib.BuildMgr"].BuildRegistry
    monkeypatch.setattr(registry, "_cached_build_types", [generic.Blood_is_Power_Healer, custom.MyBloodIsPower])

    # Use the production mask writer, not a duplicate of its replacement semantics.
    tree = ast.parse((ROOT / "Py4GWCoreLib/HeroAI/combat.py").read_text(encoding="utf-8"))
    combat_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "CombatClass")
    methods: list[ast.stmt] = [
        node
        for node in combat_class.body
        if isinstance(node, ast.FunctionDef) and node.name in ("ApplyBlockedSkillIDs", "IsSkillReady")
    ]
    namespace: dict[str, Any] = {"MAX_SKILLS": 8}
    exec(compile(ast.Module(body=methods, type_ignores=[]), "combat.py", "exec"), namespace)
    calls: list[set[int]] = []

    class Combat:
        ApplyBlockedSkillIDs = namespace["ApplyBlockedSkillIDs"]
        IsSkillReady = namespace["IsSkillReady"]

        def __init__(self) -> None:
            self.blocked_skill_ids: set[int] = set()
            self.is_skill_enabled = [True] * 8
            self.skill_order = list(range(8))
            self.skills = [SimpleNamespace(skill_id=skill, skillbar_data=SimpleNamespace(recharge=0)) for skill in IDS]

        def HandleCombat(self, _cache: Any, ooc: bool = False) -> bool:
            calls.append(set(self.blocked_skill_ids))
            return False

    cache = SimpleNamespace(
        combat_handler=Combat(),
        data=SimpleNamespace(in_aggro=True),
        Update=noop,
        UpdateCombat=noop,
        account_options=SimpleNamespace(Skills=[True] * 8),
    )
    return SimpleNamespace(
        state=state,
        world=world,
        core=core,
        cache=cache,
        calls=calls,
        locks=locks,
        Custom=custom.MyBloodIsPower,
        Generic=generic.Blood_is_Power_Healer,
        Hero=hero.HeroAI_Build,
        Registry=registry,
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_real_registry_selection_and_cached_instance(runtime: Any, reverse: bool) -> None:
    r = runtime
    r.Registry._cached_build_types = [r.Custom, r.Generic] if reverse else [r.Generic, r.Custom]
    registry = r.Registry(build_init_kwargs={"cached_data": r.cache})
    assert r.Custom(match_only=True).ScoreMatch() == 1008
    assert r.Generic(match_only=True).ScoreMatch() == 8
    winner = registry.GetBestBuild()
    assert isinstance(winner, r.Custom)
    assert registry.GetBestBuild() is winner
    r.state.bar[-1] = r.world.skill_id("Wielders_Boon")
    assert registry.GetBestBuild() is None  # Removed the generic healer's required signet.
    r.state.bar = IDS.copy()
    r.state.bar[5] = r.world.skill_id("Wielders_Boon")
    assert isinstance(registry.GetBestBuild(), r.Generic)


@pytest.mark.parametrize("bar", [IDS[:-1], IDS + [119], IDS[:-1] + [119], IDS[:-1] + [0], IDS[:-1] + [9999]])
def test_rejects_inexact_bars(runtime: Any, bar: list[int]) -> None:
    assert runtime.Custom(match_only=True).ScoreMatch(current_skills=bar) == -1, bar


@pytest.mark.parametrize("primary,secondary", [(8, 4), (4, 0), (5, 8), (0, 0)])
def test_rejects_wrong_professions(runtime: Any, primary: int, secondary: int) -> None:
    runtime.state.primary, runtime.state.secondary = primary, secondary
    assert runtime.Custom(match_only=True).ScoreMatch() == -1


def test_slot_order_and_attributes_do_not_change_match(runtime: Any) -> None:
    build = runtime.Custom(match_only=True)
    for offset in range(8):
        runtime.state.bar = IDS[offset:] + IDS[:offset]
        runtime.state.attributes = {"Blood Magic": offset, "Restoration Magic": 16 - offset}
        assert build.ScoreMatch() == 1008, runtime.state
    runtime.state.bar.reverse()
    assert build.ScoreMatch() == 1008


def trace_rotation(build: Any, book: Any, success_at: int | None) -> tuple[Any, list[Any], list[Any]]:
    calls: list[Any] = []
    yields: list[Any] = []

    def handler(name: str) -> Any:
        def call(**kwargs: Any) -> Generator[Any, None, bool]:
            calls.append((name, kwargs))
            yield len(calls)
            return len(calls) == success_at

        return call

    for group, names in (
        (
            book.Ritualist.RestorationMagic,
            ["Spirit_Transfer", "Spirit_Light", "Mend_Body_and_Soul", "Recuperation", "Life", "Protective_Was_Kaolai"],
        ),
        (book.Ritualist.NoAttribute, ["Drop_Held_Bundle"]),
        (book.Necromancer.BloodMagic, ["Blood_is_Power"]),
        (book.Necromancer.SoulReaping, ["Signet_of_Lost_Souls"]),
    ):
        for name in names:
            setattr(group, name, handler(name))
    coroutine = build._run_local_skill_logic()
    while True:
        try:
            yields.append(next(coroutine))
        except StopIteration as result:
            return result.value, calls, yields


@pytest.mark.parametrize("aggro", [False, True])
@pytest.mark.parametrize("success_at", [None, *range(1, 23)])
def test_every_reached_priority_and_yield_matches_generic(runtime: Any, aggro: bool, success_at: int | None) -> None:
    runtime.state.aggro = aggro
    generic = runtime.Generic()
    custom = runtime.Custom()
    expected = trace_rotation(generic, generic.skills, success_at)
    observed = trace_rotation(custom, custom.skillbook, success_at)
    assert observed == expected, (aggro, success_at, expected, observed)
    assert len(observed[1]) <= (22 if aggro else 17)
    assert custom.skillbook.Necromancer.BloodMagic.bip_diagnostic is None
    assert custom.skillbook.Ritualist.RestorationMagic.bip_diagnostic is None
    assert not hasattr(custom, "_bip_diagnostic")


def test_cannot_cast_stops_both_rotations(runtime: Any) -> None:
    runtime.state.can_cast = False
    generic, custom = runtime.Generic(), runtime.Custom()
    assert (
        trace_rotation(generic, generic.skills, None)
        == trace_rotation(custom, custom.skillbook, None)
        == (False, [], [])
    )


def decline() -> Generator[None, None, bool]:
    if False:
        yield
    return False


def test_real_fallback_masks_every_owned_skill_after_decline(runtime: Any) -> None:
    r = runtime
    outer = r.Hero(cached_data=r.cache)
    custom = outer.EnsureBuildContract()
    assert isinstance(custom, r.Custom)
    custom.SetSkillCastingFn(decline)
    finish(outer.ProcessCombat())
    assert r.calls == [set(IDS)]
    assert all(not r.cache.combat_handler.IsSkillReady(slot) for slot in range(8))
    assert custom.GetSupportedSkills() == IDS
    assert custom.GetBlockedSkills() == IDS
    assert custom.skillbook.owner is custom
    assert custom.skillbook.Necromancer.BloodMagic.build is custom
    assert custom.current_fallback_handler._standalone_fallback
    assert all(not isinstance(value, r.Generic) for value in cast(dict[str, Any], vars(custom)).values())


def test_real_custom_generic_custom_and_pure_heroai_transitions(runtime: Any) -> None:
    r = runtime
    outer = r.Hero(cached_data=r.cache)
    custom = outer.EnsureBuildContract()
    custom.SetSkillCastingFn(decline)
    finish(outer.ProcessCombat())
    custom.current_target_id = 55
    custom.skillbook.Necromancer.BloodMagic.bip_throttle.Reset()
    r.state.bar[5] = r.world.skill_id("Wielders_Boon")
    generic = outer.EnsureBuildContract()
    assert isinstance(generic, r.Generic)
    assert not r.cache.combat_handler.blocked_skill_ids
    generic.current_fallback_handler.set_cached_data(r.cache)
    generic.SetSkillCastingFn(decline)
    finish(outer.ProcessCombat())
    assert r.calls[-1] == set(generic.GetBlockedSkills())
    diagnostic_stops: list[bool] = []
    generic._bip_diagnostic = SimpleNamespace(stop=lambda: diagnostic_stops.append(True))
    r.state.bar = IDS.copy()
    assert outer.EnsureBuildContract() is custom
    assert diagnostic_stops == [True]
    assert custom.skillbook.Necromancer.BloodMagic.bip_diagnostic is None
    assert custom.current_target_id == 0
    assert custom.skillbook.Necromancer.BloodMagic.bip_throttle.IsStopped()
    finish(outer.ProcessCombat())
    assert r.calls[-1] == set(IDS)
    r.state.bar = [9999] * 8
    finish(outer.ProcessCombat())
    assert outer.GetBuildContract() is outer
    assert r.calls[-1] == set(), "Pure HeroAI must not inherit the custom mask."


@pytest.mark.parametrize("replacement", [IDS, [777]])
def test_dispose_does_not_clear_successor_mask(runtime: Any, replacement: list[int]) -> None:
    custom = runtime.Custom(cached_data=runtime.cache)
    custom.OnContractActivated()
    runtime.cache.combat_handler.ApplyBlockedSkillIDs(replacement)
    custom.Dispose()
    custom.Dispose()
    assert runtime.cache.combat_handler.blocked_skill_ids == set(replacement)


@pytest.mark.parametrize(
    "change", ["name", "agent", "map", "uptime", "agent_uptime", "slots", "invalid", "bar", "dispose"]
)
def test_pending_work_cannot_resume_in_an_old_context(runtime: Any, change: str) -> None:
    r = runtime
    custom = r.Custom(cached_data=r.cache)
    custom.OnContractActivated()
    submitted: list[str] = []
    restored: list[str] = []
    closed: list[bool] = []

    def pending() -> Generator[None, None, bool]:
        submitted.append("already queued")
        try:
            yield
            restored.append("old enemy")
            return True
        finally:
            closed.append(True)

    custom.SetSkillCastingFn(pending)
    coroutine = custom.ProcessCombat()
    next(coroutine)
    custom.current_target_id = 55
    custom._resolved_self_agent_id = 99
    custom.skillbook.Necromancer.BloodMagic.bip_throttle.Reset()
    if change == "name":
        r.state.name = "Other character"
    elif change == "agent":
        r.state.agent = 2
    elif change == "map":
        r.state.map += 1
    elif change in ("uptime", "agent_uptime"):
        setattr(r.state, change, 1)
    elif change == "slots":
        r.state.bar.reverse()
    elif change == "invalid":
        r.state.valid = False
    elif change == "bar":
        r.state.bar[0] = 9999
    else:
        custom.Dispose()
        custom.OnContractActivated()
    finish(coroutine)
    assert submitted == ["already queued"], "Disposal must not pretend to cancel ordinary queued actions."
    assert not restored and closed == [True], change
    if change == "slots":
        assert not custom.skillbook.Necromancer.BloodMagic.bip_throttle.IsStopped()
    else:
        assert custom.current_target_id == custom._resolved_self_agent_id == 0
        assert custom.skillbook.Necromancer.BloodMagic.bip_throttle.IsStopped()


def test_same_context_coroutine_restores_normally(runtime: Any) -> None:
    custom = runtime.Custom(cached_data=runtime.cache)
    custom.OnContractActivated()
    restored: list[bool] = []

    def pending() -> Generator[None, None, bool]:
        yield
        restored.append(True)
        return True

    custom.SetSkillCastingFn(pending)
    finish(custom.ProcessCombat())
    assert restored == [True]
    assert custom.DidTickSucceed()


def test_cache_replacement_releases_only_the_old_receiver(runtime: Any) -> None:
    custom = runtime.Custom(cached_data=runtime.cache)
    custom.OnContractActivated()
    old = runtime.cache.combat_handler
    new = type(old)()
    custom.set_cached_data(SimpleNamespace(combat_handler=new))
    assert not old.blocked_skill_ids
    custom.OnContractActivated()
    assert new.blocked_skill_ids == set(IDS)
    custom.Dispose()
    assert not new.blocked_skill_ids


def test_registry_discovers_the_new_file_with_its_nr_t_neighbors(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    package = sys.modules["Py4GWCoreLib.Builds"]
    monkeypatch.setattr(package, "__path__", [str(ROOT / BUILD_DIR)])
    admission._load(monkeypatch, "Py4GWCoreLib.Builds.Xinraes Weapon Healer", BUILD_DIR + "Xinraes Weapon Healer.py")
    discovered = runtime.Registry._scan_build_types()
    assert runtime.Custom in discovered and runtime.Generic in discovered
    candidates = [build_type(match_only=True) for build_type in discovered]
    scores = {build.build_name: build.ScoreMatch() for build in candidates}
    assert scores["My Blood is Power"] == 1008
    assert scores["Blood is Power Healer"] == 8
    assert all(score < 1008 for name, score in scores.items() if name != "My Blood is Power"), scores


def mechanics_build(runtime: Any, custom: bool, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    build = runtime.Custom() if custom else runtime.Generic()
    build.set_cached_data(runtime.cache)
    build._custom_skill_data_handler = SimpleNamespace(get_skill=runtime.world.metadata.__getitem__)
    monkeypatch.setattr(build, "SpiritBuffExists", false)
    book = build.skillbook if custom else build.skills
    return build, book


@pytest.mark.parametrize(
    "skill,threshold", [(962, 0.30), (962, 0.50), (915, 0.30), (915, 0.60), (1234, 0.40), (1234, 0.75), (1234, 0.85)]
)
@pytest.mark.parametrize("delta", [-0.0001, 0, 0.0001])
def test_real_healing_thresholds_targets_and_submissions_match_generic(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, skill: int, threshold: float, delta: float
) -> None:
    r = runtime
    r.world.health.update({1: 1.0, 2: threshold + delta})
    # Outside earshot avoids the optional condition-preferring MBaS tier here.
    r.world.place(10, 500 if skill == 915 else 1100)
    results: list[Any] = []
    for custom in (False, True):
        _, book = mechanics_build(r, custom, monkeypatch)
        helper = getattr(book.Ritualist.RestorationMagic, NAMES[IDS.index(skill)])
        r.world.submissions.clear()
        result = finish(helper(health_threshold=threshold))
        results.append((result, list(r.world.submissions)))
    expected: tuple[bool, list[tuple[int, int, int]]] = (
        (True, [(IDS.index(skill) + 1, 2, 250)]) if delta < 0 else (False, [])
    )
    assert results == [expected, expected], (skill, threshold, delta, results)


@pytest.mark.parametrize("skill,range_limit", [(962, 1248.0), (915, 1012.0)])
@pytest.mark.parametrize("outside,pet", [(False, False), (True, False), (False, True)])
def test_new_owner_uses_actual_spirit_admission(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, skill: int, range_limit: float, outside: bool, pet: bool
) -> None:
    r = runtime
    _, book = mechanics_build(r, True, monkeypatch)
    r.world.place(10, range_limit + (0.01 if outside else -0.01))
    if pet:
        r.world.spirits.clear()
        r.world.pets.append(10)
        r.world.spawned.clear()
    helper = getattr(book.Ritualist.RestorationMagic, NAMES[IDS.index(skill)])
    assert finish(helper(health_threshold=0.30)) is (not outside and not pet)
    assert bool(r.world.submissions) is (not outside and not pet)


@pytest.fixture
def bip_runtime(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    r = runtime
    r.world.health.update({1: 1.0, 2: 0.8, 3: 0.8, 4: 0.8})
    r.world.valid.update({3, 4})
    r.world.allies = [1, 4, 3, 2]
    r.world.place(3, 400)
    r.world.place(4, 400)
    r.energy = {1: 0.1, 2: 0.4, 3: 0.4, 4: 0.4}
    r.effects = set()
    r.locked = set()
    r.posts = []

    def energy(agent: int) -> float:
        return r.energy[agent]

    def valid(value: float) -> bool:
        return 0 <= value <= 1

    def effect(agent: int, skill: int, **_kwargs: Any) -> bool:
        return (agent, skill) in r.effects

    def filtered(allies: list[int], _key: int) -> list[int]:
        return [agent for agent in allies if agent not in r.locked]

    def blocked(agent: int, _key: int) -> bool:
        return agent in r.locked

    def post(agent: int, **kwargs: Any) -> None:
        r.posts.append((agent, kwargs))

    utils: Any = sys.modules["Py4GWCoreLib.HeroAI.utils"]
    utils.GetEnergyValues = energy
    utils.IsValidEnergyValue = valid
    utils.CheckForEffect = effect
    r.locks.filter_unlocked_buff_targets = filtered
    # BloodMagic imports these functions by value; patch its module as well.
    blood: Any = sys.modules["_phase_a_blood"]
    blood.is_buff_target_lock_blocked = blocked
    blood.post_buff_target_lock = post
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "HasEffect", staticmethod(effect))
    return r


@pytest.mark.parametrize(
    "health,max_hp,allowed",
    [
        (0.88, 500, False),
        (0.8801, 500, True),
        (0.955, 280, False),
        (0.9551, 280, True),
        (0.99, 250, False),
        (1.0, 250, False),
        (1.0, 500, True),
        (1.0, 0, False),
    ],
)
def test_bip_strict_sacrifice_floors_with_no_diagnostic(
    bip_runtime: Any, monkeypatch: pytest.MonkeyPatch, health: float, max_hp: int, allowed: bool
) -> None:
    r = bip_runtime
    r.world.health[1] = health

    def maximum(_agent: int) -> int:
        return max_hp

    r.core.Agent.GetMaxHealth = maximum
    results: list[Any] = []
    for custom in (False, True):
        _, book = mechanics_build(r, custom, monkeypatch)
        r.world.submissions.clear()
        accepted = finish(book.Necromancer.BloodMagic.Blood_is_Power())
        results.append((accepted, list(r.world.submissions)))
    expected = (allowed, [(1, 2, 250)] if allowed else [])
    assert results == [expected, expected], (health, max_hp, results)


def test_bip_inclusive_energy_ranking_effects_locks_and_throttle(
    bip_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = bip_runtime
    build, book = mechanics_build(r, True, monkeypatch)
    helper = book.Necromancer.BloodMagic
    # Exactly 40% is eligible; self has less energy but is never a recipient.
    assert finish(helper.Blood_is_Power()) is True
    assert r.world.submissions == [(1, 2, 250)]
    assert r.posts[0][0] == 2
    build._local_cast_timer.Stop()
    Timer.now = 1499
    assert finish(helper.Blood_is_Power()) is False
    Timer.now = 1500
    r.energy[2] = 0.40001
    assert finish(helper.Blood_is_Power()) is True
    assert r.world.submissions[-1] == (1, 3, 250), "Equal energy/distance resolves by agent ID."
    build._local_cast_timer.Stop()
    Timer.now = 3000
    r.effects.add((3, 119))
    assert finish(helper.Blood_is_Power()) is True
    assert r.world.submissions[-1] == (1, 4, 250)
    build._local_cast_timer.Stop()
    Timer.now = 4500
    r.effects.add((4, 157))
    assert finish(helper.Blood_is_Power()) is False
    r.effects.clear()
    r.locked.update({3, 4})
    assert finish(helper.Blood_is_Power()) is False
    assert len(r.world.submissions) == 3


@pytest.mark.parametrize(
    "energy,enemy_hp,expected",
    [(0.2999, 0.49, True), (0.30, 0.49, False), (0.5999, 0.49, True), (0.60, 0.49, False), (0.1, 0.50, False)],
)
def test_signet_strict_resource_and_enemy_thresholds(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, energy: float, enemy_hp: float, expected: bool
) -> None:
    r = runtime
    r.world.energy = energy
    r.world.health.update({20: enemy_hp, 21: 0.1})
    r.world.valid.update({20, 21})
    r.world.hostile.update({20, 21})
    r.world.place(20, 100)
    r.world.place(21, 2000)
    monkeypatch.setattr(r.core.AgentArray, "GetEnemyArray", staticmethod(lambda: [21, 20]))
    for custom in (False, True):
        _, book = mechanics_build(r, custom, monkeypatch)
        r.world.submissions.clear()
        threshold = 0.60 if energy > 0.3 else 0.30
        assert finish(book.Necromancer.SoulReaping.Signet_of_Lost_Souls(max_self_energy_pct=threshold)) is expected
        assert r.world.submissions == ([(8, 20, 250)] if expected else [])


def test_transient_invalid_frame_recovers_under_the_same_outer_signature(runtime: Any) -> None:
    r = runtime
    outer = r.Hero(cached_data=r.cache)
    custom = outer.EnsureBuildContract()

    def pending() -> Generator[None, None, bool]:
        yield
        return True

    custom.SetSkillCastingFn(pending)
    finish(outer.Tick(True))
    r.state.valid = False
    finish(outer.Tick(True))
    assert not r.cache.combat_handler.blocked_skill_ids
    r.state.valid = True
    assert outer.EnsureBuildContract() is custom
    custom.SetSkillCastingFn(decline)
    finish(outer.Tick(True))
    assert r.calls == [set(IDS)], "The cached custom owner must resume after the invalid frame."


@pytest.mark.parametrize(
    "scenario,expected",
    [("transfer", 962), ("light", 915), ("mend", 1234), ("bip_ooc", 119), ("kaolai", 1219), ("none", 0)],
)
def test_real_rotation_submissions_match_generic(
    bip_runtime: Any, monkeypatch: pytest.MonkeyPatch, scenario: str, expected: int
) -> None:
    r = bip_runtime
    r.world.health.update({1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0})
    r.energy.update({1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0})
    r.world.place(10, 500)
    r.state.aggro = False
    if scenario in ("transfer", "light", "mend"):
        r.world.health[2] = 0.2
    elif scenario == "bip_ooc":
        r.energy[2] = 0.40
    r.core.Party = SimpleNamespace(IsPartyLoaded=lambda: False)
    admission._module(monkeypatch, "Py4GWCoreLib.FrameTree", FrameTree=SimpleNamespace())
    monkeypatch.setattr(r.core.AgentArray, "GetEnemyArray", staticmethod(lambda: []))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsMartial", staticmethod(false))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsMelee", staticmethod(false))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsConditioned", staticmethod(false))
    r.core.Agent.IsCrippled = false

    def ready(skill: int) -> bool:
        return skill == expected

    monkeypatch.setattr(r.core.Routines.Checks.Skills, "IsSkillIDReady", staticmethod(ready))
    outcomes: list[Any] = []
    for custom in (False, True):
        build, _ = mechanics_build(r, custom, monkeypatch)
        r.world.submissions.clear()
        result = finish(build._run_local_skill_logic())
        outcomes.append((result, list(r.world.submissions)))
    target = 1 if scenario == "kaolai" else 2
    wanted: tuple[bool, list[tuple[int, int, int]]] = (
        (True, [(IDS.index(expected) + 1, target, 250)]) if expected else (False, [])
    )
    assert outcomes == [wanted, wanted], (scenario, outcomes)


@pytest.mark.parametrize("fourth_hp,expected", [(0.7499, True), (0.75, False)])
def test_real_kaolai_release_and_pending_protection(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, fourth_hp: float, expected: bool
) -> None:
    r = runtime
    r.world.allies = [1, 2, 3, 4, 10]
    r.world.valid.update({3, 4})
    r.world.health.update({1: 0.6, 2: 0.6, 3: 0.6, 4: fourth_hp})
    clicks: list[bool] = []

    def holding(_agent: int) -> bool:
        return True

    def login_agent(login: int) -> int:
        return login

    def frames(hash_id: int, offsets: list[int]) -> list[Any]:
        assert (hash_id, offsets) == (5040781, [0, 0])
        return [SimpleNamespace(is_usable=True, click=lambda: clicks.append(True))]

    r.core.Agent.IsHoldingItem = holding
    r.core.Party = SimpleNamespace(
        IsPartyLoaded=lambda: True,
        GetPlayers=lambda: [SimpleNamespace(login_number=agent, is_connected=True) for agent in (1, 2, 3, 4)],
        GetHeroes=empty_list,
        GetHenchmen=empty_list,
        Players=SimpleNamespace(GetAgentIDByLoginNumber=login_agent),
    )
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsAlive", staticmethod(r.world.is_alive))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "GetHealth", staticmethod(r.world.get_health))
    admission._module(monkeypatch, "Py4GWCoreLib.FrameTree", FrameTree=SimpleNamespace(frames_at_path=frames))
    for custom in (False, True):
        build, book = mechanics_build(r, custom, monkeypatch)
        clicks.clear()
        helper = book.Ritualist.NoAttribute
        assert finish(helper.Drop_Held_Bundle(health_threshold=0.75)) is expected
        assert clicks == ([True] if expected else [])
        if expected:
            assert build._local_cast_timer.delay == 250
            assert finish(helper.Drop_Held_Bundle(health_threshold=0.75)) is False
            assert clicks == [True]


@pytest.fixture
def spirit_runtime(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    r = runtime

    def native_skill(name: str) -> SimpleNamespace:
        return SimpleNamespace(id=SimpleNamespace(id=r.world.skill_id(name)))

    admission._module(monkeypatch, "PySkill", Skill=native_skill)
    models = admission._load(monkeypatch, "_phase_a_models", "Py4GWCoreLib/enums_src/Model_enums.py")
    r.core.SpiritModelID = models.SpiritModelID
    cast(Any, sys.modules["Py4GWCoreLib.enums"]).SPIRIT_BUFF_MAP = models.SPIRIT_BUFF_MAP
    r.spirit_model = int(models.SpiritModelID.RECUPERATION)

    def model(_agent: int) -> int:
        return r.spirit_model

    def duration(_skill: int) -> float:
        return 0.0

    def wait(_duration: int) -> Generator[None, None, None]:
        yield

    r.core.Agent.GetPlayerNumber = model
    r.core.GLOBAL_CACHE.Skill.Data = SimpleNamespace(GetActivation=duration, GetAftercast=duration)
    r.core.Routines.Yield = SimpleNamespace(wait=wait)
    return r


@pytest.mark.parametrize("health,present", [(0.1999, False), (0.20, True), (0.2001, True)])
def test_recuperation_replacement_uses_existing_metadata(spirit_runtime: Any, health: float, present: bool) -> None:
    r = spirit_runtime
    r.world.place(10, 500)
    r.world.health[10] = health
    custom = r.Custom(cached_data=r.cache)
    custom._custom_skill_data_handler = SimpleNamespace(get_skill=r.world.metadata.__getitem__)
    assert custom.SpiritBuffExists(981) is present
    r.spirit_model = int(r.core.SpiritModelID.LIFE)
    assert custom.SpiritBuffExists(1251) is True, "Life retains its existing no-refresh rule."


@pytest.mark.parametrize("approaching", [False, True])
def test_life_preparation_and_real_spirit_wait_interruption(
    spirit_runtime: Any, monkeypatch: pytest.MonkeyPatch, approaching: bool
) -> None:
    r = spirit_runtime
    r.state.aggro = False
    r.world.spirits.clear()

    def approach(_build: Any) -> bool:
        return approaching

    monkeypatch.setattr(r.core.BuildMgr, "IsCloseToAggro", approach)
    custom = r.Custom(cached_data=r.cache)
    custom._custom_skill_data_handler = SimpleNamespace(get_skill=r.world.metadata.__getitem__)
    custom.OnContractActivated()
    custom.SetSkillCastingFn(custom.skillbook.Ritualist.RestorationMagic.Life)
    if not approaching:
        assert finish(custom.skillbook.Ritualist.RestorationMagic.Life()) is False
        assert not r.world.submissions
        return
    coroutine = custom.ProcessOOC()
    next(coroutine)
    assert r.world.submissions == [(6, 0, 250)]
    assert custom._is_local_cast_pending()
    r.state.name = "Another character"
    finish(coroutine)
    assert r.world.submissions == [(6, 0, 250)]
    assert not custom._is_local_cast_pending()
    assert not custom.DidTickSucceed(), "The old spirit wait must not report success after invalidation."


def test_outer_clear_closes_pending_work_and_reactivates_the_cached_owner(runtime: Any) -> None:
    r = runtime
    outer = r.Hero(cached_data=r.cache)
    custom = outer.EnsureBuildContract()
    events: list[str] = []

    def pending() -> Generator[None, None, bool]:
        try:
            yield
            events.append("restored")
            return True
        finally:
            events.append("closed")

    custom.SetSkillCastingFn(pending)
    finish(outer.Tick(True))
    outer.ClearBuildContract()
    assert events == ["closed"]
    assert not r.cache.combat_handler.blocked_skill_ids
    assert outer.EnsureBuildContract() is custom
    assert r.cache.combat_handler.blocked_skill_ids == set(IDS)
