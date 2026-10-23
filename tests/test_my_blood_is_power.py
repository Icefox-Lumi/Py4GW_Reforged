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

    def login_number(agent: int) -> int:
        return agent

    def publications(*, sort_results: bool = True) -> list[Any]:
        return []

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
    core.Agent.GetLoginNumber = login_number
    core.GLOBAL_CACHE.ShMem = SimpleNamespace(GetAllAccountData=publications)
    publication_clock = admission._load(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync",
        "Py4GWCoreLib/GlobalCache/shared_memory_src/IntentSync.py",
    )
    monkeypatch.setattr(publication_clock, "get_uncached_tick_count64", lambda: 10000)
    core.Party = SimpleNamespace(IsPartyLoaded=false)
    admission._module(monkeypatch, "Py4GWCoreLib.FrameTree", FrameTree=SimpleNamespace(frames_at_path=empty_list))
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
    load("Py4GWCoreLib.Builds.Skills.SmartKaolai", "Py4GWCoreLib/Builds/Skills/SmartKaolai.py")
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
        (getattr(build, "_smart_kaolai", book.Ritualist.NoAttribute), ["Drop_Held_Bundle"]),
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
    assert custom._bip_diagnostic is None


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
        helper = build._smart_kaolai if custom else book.Ritualist.NoAttribute
        assert finish(helper.Drop_Held_Bundle(health_threshold=0.75)) is expected
        assert clicks == ([True] if expected else [])
        if expected:
            assert build._local_cast_timer.delay == 250
            assert finish(helper.Drop_Held_Bundle(health_threshold=0.75)) is (not custom)
            assert clicks == ([True] if custom else [True, True])


def configure_kaolai(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Native observations for real owner dispatch; other seven skills are recharging."""
    r = runtime
    state = SimpleNamespace(
        holding=True,
        party_loaded=True,
        button_present=True,
        button_usable=True,
        clicks=[],
        players=[SimpleNamespace(login_number=agent, is_connected=True) for agent in (1, 2, 3, 4)],
        heroes=[],
        henchmen=[],
    )
    r.world.valid.update({3, 4})
    r.world.allies = [1, 2, 3, 4]
    r.world.health.update(dict.fromkeys(r.world.allies, 0.6))
    r.world.energy = 1.0

    def holding(_agent: int) -> bool:
        return state.holding

    def login_agent(login: int) -> int:
        return login

    r.core.Agent.IsHoldingItem = holding
    r.core.Party = SimpleNamespace(
        IsPartyLoaded=lambda: state.party_loaded,
        GetPartyID=lambda: 7,
        GetPlayers=lambda: state.players,
        GetHeroes=lambda: state.heroes,
        GetHenchmen=lambda: state.henchmen,
        Players=SimpleNamespace(GetAgentIDByLoginNumber=login_agent),
    )

    def frames(anchor: int, path: list[int]) -> list[Any]:
        assert (anchor, path) == (5040781, [0, 0])
        return (
            [SimpleNamespace(is_usable=state.button_usable, click=lambda: state.clicks.append(r.state.agent))]
            if state.button_present
            else []
        )

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=r.world.recharge if r.state.bar[slot - 1] == 1219 else 1)

    r.core.SkillBar.GetSkillData = skill_data
    admission._module(monkeypatch, "Py4GWCoreLib.FrameTree", FrameTree=SimpleNamespace(frames_at_path=frames))
    monkeypatch.setattr(r.core.AgentArray, "GetEnemyArray", staticmethod(empty_list))
    for name in ("IsMartial", "IsMelee", "IsConditioned"):
        monkeypatch.setattr(r.core.Routines.Checks.Agents, name, staticmethod(false))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsAlive", staticmethod(r.world.is_alive))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "GetHealth", staticmethod(r.world.get_health))
    admission._module(monkeypatch, "Py4GWCoreLib.Effect", Effects=SimpleNamespace(HasEffect=false))
    r.core.Agent.IsPoisoned = r.core.Agent.IsBleeding = r.core.Agent.IsDegenHexed = false
    r.core.Agent.IsCrippled = false
    r.kaolai = state
    return state


@pytest.mark.parametrize("custom", [False, True], ids=["generic_preparation", "smart_preparation"])
@pytest.mark.parametrize(
    "gate",
    [
        "ready",
        "holding",
        "casting",
        "energy",
        "recharge",
        "pending",
        "disabled",
        "missing",
        "reordered",
        "reordered_disabled",
        "owner_target",
    ],
)
def test_kaolai_preparation_retains_generic_admission(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, custom: bool, gate: str
) -> None:
    r = runtime
    state = configure_kaolai(r, monkeypatch)
    state.holding = gate == "holding"
    if gate == "casting":
        r.state.can_cast = False
    elif gate == "energy":
        r.world.energy = 0.0
    elif gate == "recharge":
        r.world.recharge = 1
    elif gate == "missing":
        r.state.bar[4] = 9999
    elif gate.startswith("reordered"):
        r.state.bar.reverse()
    if gate in ("disabled", "reordered_disabled"):
        r.cache.account_options.Skills[r.state.bar.index(1219)] = False
    build, book = mechanics_build(r, custom, monkeypatch)
    if gate == "pending":
        build._mark_local_cast_pending(250)
    elif gate == "owner_target":
        monkeypatch.setattr(build, "_validate_target_for_skill_cast", false)
    helper = build._smart_kaolai if custom else book.Ritualist.RestorationMagic
    result = finish(helper.Protective_Was_Kaolai())
    expected = gate in ("ready", "reordered")
    assert result is expected, (custom, gate, r.world.submissions)
    assert r.world.submissions == ([(r.state.bar.index(1219) + 1, 1, 250)] if expected else [])
    assert not state.clicks
    if expected:
        assert build._local_cast_timer.deadline == 250


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("action", ["release", "preparation"])
def test_real_kaolai_owner_dispatch_and_diagnostic_attribution(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, armed: bool, action: str
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    state.holding = action == "release"
    selected = r.outer.EnsureBuildContract()
    capture: Any = r.click("Arm one capture") if armed else None

    def stock_drop(**_kwargs: Any) -> Any:
        pytest.fail("My Blood is Power must dispatch release through Smart Kaolai.")

    monkeypatch.setattr(selected.skillbook.Ritualist.NoAttribute, "Drop_Held_Bundle", stock_drop)
    assert finish(selected.ProcessSkillCasting()) is None
    assert state.clicks == ([1] if action == "release" else [])
    assert r.world.submissions == ([(5, 1, 250)] if action == "preparation" else [])
    assert selected.DidTickSucceed() and selected._local_cast_timer.deadline == 250
    assert r.cache.combat_handler.blocked_skill_ids == set(IDS)
    if armed:
        winner = "Drop_Held_Bundle" if action == "release" else "Protective_Was_Kaolai"
        assert capture.winners == {winner: 1}
        assert capture.preemptions == ({winner: 1} if action == "release" else {})
    else:
        assert selected._bip_diagnostic is None


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("skill", [962, 915, 1234])
@pytest.mark.parametrize("critical_self", [False, True])
def test_kaolai_routine_entry_preempted_by_repeated_real_emergency_heals(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, armed: bool, skill: int, critical_self: bool
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    target = 1 if critical_self else 2
    r.world.health[target] = 0.1
    r.world.place(10, 500 if skill == 915 else 1100)

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if r.state.bar[slot - 1] in {skill, 1219} else 1)

    r.core.SkillBar.GetSkillData = skill_data
    selected = r.outer.EnsureBuildContract()
    capture: Any = r.click("Arm one capture") if armed else None
    for now in (0.0, 1.0, 2.0):
        r.now, Timer.now = now, int(now * 1000)
        finish(selected.ProcessSkillCasting())
    assert r.world.submissions == [(IDS.index(skill) + 1, target, 250)] * 3, (skill, critical_self, r.world.submissions)
    assert not state.clicks and selected._local_cast_timer.deadline == 2250
    if armed:
        counts = capture.kaolai.counts
        assert counts[f"routine_entry_preempted_{NAMES[IDS.index(skill)]}"] == 3, counts
        assert not counts["drop_checked"], counts
        assert counts["self_critical_entry"] == (3 if critical_self else 0), counts
    else:
        assert not r.output and selected._smart_kaolai.bip_diagnostic is None


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("case", ["two_critical", "three_critical", "dead", "outside", "no_button", "pending", "busy"])
def test_kaolai_emergency_opportunity_and_existing_gates_real_dispatch(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, armed: bool, case: str
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    selected = r.outer.EnsureBuildContract()
    if case in {"two_critical", "three_critical"}:
        count = 2 if case == "two_critical" else 3
        r.world.health.update({aid: 0.1 if aid <= count else 1 for aid in range(1, 5)})
    elif case == "dead":
        r.world.dead.add(4)
    elif case == "outside":
        r.world.place(4, 2500.01)
    elif case == "no_button":
        state.button_present = False
    elif case == "pending":
        selected._mark_local_cast_pending(250)
    else:
        r.state.can_cast = False
    capture: Any = r.click("Arm one capture") if armed else None
    finish(selected.ProcessSkillCasting())
    released = case in {"two_critical", "three_critical"}
    assert state.clicks == ([1] if released else []) and not r.world.submissions, (armed, case)
    assert selected._local_cast_timer.deadline == (250 if released or case == "pending" else None)
    if armed:
        counts = capture.kaolai.counts
        key = {
            "two_critical": "critical2or3_below4",
            "three_critical": "critical2or3_below4",
            "dead": "dead_nearby_entry",
            "outside": "outside_entry",
            "no_button": "button_unavailable",
            "pending": "pending_or_party_gate",
            "busy": "busy_entry",
        }[case]
        assert counts[key] == 1 and counts["click_call_returned"] == int(released), (case, counts)
    else:
        assert not r.output


@pytest.mark.parametrize("ending", ["clear", "unchanged", "gap", "death", "map", "cancel"])
def test_kaolai_real_click_followup_and_lifecycle(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")
    pending = selected.ProcessSkillCasting()
    next(pending)
    assert state.clicks == [1] and capture.kaolai.counts["click_call_returned"] == 1
    if ending == "cancel":
        pending.close()
    else:
        finish(pending)
    # A cancelled generator cannot retract its click or pending stamp.
    assert selected._local_cast_timer.deadline == 250
    state.button_present = False
    r.now, Timer.now = 0.5, 500
    if ending == "map":
        r.state.map += 1
    elif ending == "death":
        r.world.dead.add(1)
        state.holding = False
    elif ending == "clear":
        state.holding = False
        r.world.health[2] = 0.9
        r.world.recharge = 1  # No automatic re-preparation during observation.
    if ending != "gap":
        finish(selected.ProcessSkillCasting())
    r.now = 2.0
    r.widget.update()
    counts = capture.kaolai.counts
    assert counts["generic_held_cleared"] == int(ending == "clear"), (ending, counts)
    assert counts["hp_fraction_rises_unattributed"] == int(ending == "clear"), (ending, counts)
    if ending == "cancel":
        assert counts["inconclusive_cancelled_pass"] == 1 and not counts["drop_selected"], counts
    if ending in {"death", "gap"}:
        assert counts["inconclusive_observation_gap"] == 1, (ending, counts)
    if ending == "map":
        assert capture.done and counts["inconclusive_capture_ended"] == 1
    assert state.clicks == [1] and not r.world.submissions
    assert capture.kaolai.watch is None


def test_kaolai_capture_sampling_output_and_disarmed_read_bounds(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    state.button_present = False
    selected = r.outer.EnsureBuildContract()
    observed = 0
    observe = selected._smart_kaolai.observe

    def counted(**kwargs: Any) -> Any:
        nonlocal observed
        observed += 1
        return observe(**kwargs)

    monkeypatch.setattr(selected._smart_kaolai, "observe", counted)
    for _ in range(3):
        finish(selected.ProcessSkillCasting())
    assert observed == 0 and not r.output
    capture = r.click("Arm one capture")
    for index in range(301):
        r.now, Timer.now = index / 5, index * 200
        finish(selected.ProcessSkillCasting())
        r.widget.update()
    assert capture.done and 0 < observed <= 240
    assert capture.kaolai.counts["samples"] == observed
    assert len(r.output) == capture.records == 8
    assert all(len(line) < 4000 for line in r.output), [len(line) for line in r.output]
    assert "kaolai=[" in r.output[-1] and "heal_receipt:unavailable" in r.output[-1]
    assert not state.clicks and not r.world.submissions
    finish(selected.ProcessSkillCasting())
    assert capture.kaolai.counts["samples"] == observed and len(r.output) == 8
    assert all("kaolai_emergency=[" not in line for line in r.output)


@pytest.mark.parametrize("emergency", [False, True])
def test_kaolai_observation_failure_cannot_cancel_real_drop(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, emergency: bool
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    if emergency:
        r.world.health.update({1: 1.0, 2: 0.25, 3: 0.30, 4: 1.0})
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")

    def broken_observation(**_kwargs: Any) -> Any:
        raise RuntimeError("Injected diagnostic read failure")

    monkeypatch.setattr(selected._smart_kaolai, "observe", broken_observation)
    finish(selected.ProcessSkillCasting())
    assert capture.result == "ABORTED_OBSERVATION_ERROR"
    assert state.clicks == [1] and selected.DidTickSucceed() and selected._local_cast_timer.deadline == 250
    assert not r.world.submissions


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize(
    "case,health,action",
    [
        ("qualifies", (1.0, 0.25, 0.30, 1.0), "early"),
        ("deficit", (1.0, 0.37, 0.38, 1.0), "none"),
        ("four_severe", (0.39, 0.39, 0.39, 0.39), "early"),
        ("four_mild", (0.60, 0.65, 0.70, 0.74), "routine"),
        ("late", (1.0, 0.19, 0.30, 1.0), "late"),
        ("no_held", (1.0, 0.25, 0.30, 1.0), "none"),
        ("pending", (1.0, 0.25, 0.30, 1.0), "none"),
        ("button", (1.0, 0.25, 0.30, 1.0), "none"),
        ("busy", (1.0, 0.25, 0.30, 1.0), "none"),
    ],
)
def test_emergency_real_controller_armed_disarmed_action_contract(
    capture_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    armed: bool,
    case: str,
    health: tuple[float, ...],
    action: str,
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update(dict(zip((1, 2, 3, 4), health)))
    r.world.recharge = 1
    selected = r.outer.EnsureBuildContract()
    if case == "no_held":
        state.holding = False
    elif case == "pending":
        selected._mark_local_cast_pending(250)
    elif case == "button":
        state.button_present = False
    elif case == "busy":
        r.state.can_cast = False
    capture: Any = r.click("Arm one capture") if armed else None
    yielded = list(selected.ProcessSkillCasting())
    accepted = action != "none"
    assert (state.clicks, r.world.submissions, selected._local_cast_timer.deadline, selected.DidTickSucceed()) == (
        [1] if accepted else [],
        [],
        250 if accepted or case == "pending" else None,
        accepted,
    ), (armed, case, yielded)
    assert yielded == [None], (armed, case, yielded)
    if not armed:
        assert not r.output and selected._smart_kaolai.bip_diagnostic is None
        return
    assert capture.winners["Drop_Held_Bundle"] == int(accepted)
    assert capture.kaolai.counts["click_call_returned"] == int(accepted)
    assert capture.kaolai.counts["drop_checked"] == int(case != "busy" and action != "early")
    r.click("Stop")
    assert "kaolai=[" in r.output[-1] and "kaolai_emergency=[" not in r.output[-1]


@pytest.mark.parametrize("ending", ["stop", "disable", "reload", "dispose", "cancel"])
def test_emergency_release_capture_terminal_isolation(
    capture_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update({1: 1.0, 2: 0.25, 3: 0.30, 4: 1.0})
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")
    work = selected.ProcessSkillCasting()
    next(work)
    assert capture.kaolai.counts["click_call_returned"] == 1
    assert not capture.kaolai.counts["drop_selected"]
    if ending == "stop":
        r.click("Stop")
    elif ending == "disable":
        r.widget.on_disable()
    elif ending == "reload":
        r.widget.on_disable()  # WidgetManager's normal reload lifecycle.
        source = ROOT / "Widgets/Coding/Debug/Py4GW/Smart BiP Diagnostic.py"
        exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), r.widget.__dict__)
    elif ending == "dispose":
        selected.Dispose()
    else:
        work.close()
        # The next owner entry discards the unfinished sampled pass even when
        # that entry is too soon to be sampled itself.
        finish(selected.ProcessSkillCasting())
        r.click("Stop")
    work.close()
    assert capture.done and capture.pending is None
    counts = dict(capture.kaolai.counts)
    assert not counts.get("drop_selected") and state.clicks == [1]
    output = list(r.output)
    for _ in range(3):
        selected._smart_kaolai._observe_event("drop_checked")
        capture.kaolai_event("drop_checked")
        r.widget.update()
    assert capture.kaolai.counts == counts and r.output == output


@pytest.mark.parametrize("emergency", [False, True])
def test_kaolai_click_call_can_return_without_native_submission(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, emergency: bool
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    if emergency:
        r.world.health.update({1: 1.0, 2: 0.28, 3: 0.34, 4: 0.37})
    # Execute Frame.click itself: outer checks pass, its final usability recheck
    # fails. No native button request is issued, yet the helper still accepts.
    source = ROOT / "Py4GWCoreLib/FrameTree/frame.py"
    frame = next(
        node
        for node in ast.parse(source.read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef) and node.name == "Frame"
    )
    click = next(node for node in frame.body if isinstance(node, ast.FunctionDef) and node.name == "click")
    native_calls: list[int] = []
    namespace: dict[str, Any] = {
        "PyUIManager": SimpleNamespace(UIManager=SimpleNamespace(button_click=native_calls.append))
    }
    exec(compile(ast.Module(body=[click], type_ignores=[]), str(source), "exec"), namespace)
    usability = iter((True, True, False))

    class Button:
        frame_id = 42
        click = namespace["click"]

        @property
        def is_usable(self) -> bool:
            return next(usability)

    def frames(_anchor: int, _path: list[int]) -> list[Any]:
        return [Button()]

    cast(Any, sys.modules["Py4GWCoreLib.FrameTree"]).FrameTree.frames_at_path = frames
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")
    pending = selected.ProcessSkillCasting()
    next(pending)
    r.now = 0.6
    finish(pending)
    assert not native_calls and not state.clicks and not r.world.submissions
    assert selected._local_cast_timer.deadline == 250 and selected.DidTickSucceed()
    assert capture.kaolai.counts["click_call_returned"] == capture.kaolai.counts["drop_selected"] == 1
    assert capture.kaolai.counts["delayed_pass_outcome"] == 1
    r.now = 2
    r.widget.update()
    assert capture.kaolai.counts["inconclusive_observation_gap"] == 1
    assert "click_receipt:unavailable" in capture.kaolai.summary()


@pytest.mark.parametrize("armed", [False, True])
def test_kaolai_diagnostic_does_not_add_coordination_writes(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, armed: bool
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    selected = r.outer.EnsureBuildContract()

    def unexpected_write(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("Kaolai observation/release must not post a skill intent or buff lock.")

    monkeypatch.setattr(selected, "_whiteboard_post_intent", unexpected_write)
    monkeypatch.setattr(r.locks, "post_buff_target_lock", unexpected_write)
    monkeypatch.setattr(sys.modules["_phase_a_blood"], "post_buff_target_lock", unexpected_write)
    if armed:
        r.click("Arm one capture")
    finish(selected.ProcessSkillCasting())
    state.button_present = False
    r.now, Timer.now = 0.5, 500
    finish(selected.ProcessSkillCasting())
    assert state.clicks == [1] and not r.world.submissions


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize(
    "change", ["cancel", "dispose", "map", "account", "invalid", "slots", "bar", "uptime", "cache"]
)
def test_real_kaolai_release_cancellation_and_lifecycle(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, armed: bool, change: str
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    selected = r.outer.EnsureBuildContract()
    capture: Any = r.click("Arm one capture") if armed else None
    pending = selected.ProcessSkillCasting()
    assert next(pending) is None
    assert state.clicks == [1] and selected._local_cast_timer.deadline == 250
    assert not r.world.submissions
    if change == "cancel":
        pending.close()
    else:
        if change == "dispose":
            selected.Dispose()
        elif change == "map":
            r.state.map += 1
        elif change == "account":
            r.core.Player.GetAccountEmail = lambda: "second@example.invalid"
        elif change == "invalid":
            r.state.valid = False
        elif change == "slots":
            r.state.bar.reverse()
        elif change == "bar":
            r.state.bar[0] = 9999
        elif change == "uptime":
            r.state.uptime = 0
        else:
            selected.set_cached_data(SimpleNamespace(combat_handler=type(r.cache.combat_handler)()))
        assert list(pending) == []
    assert pending.gi_frame is None
    assert state.clicks == [1] and not r.world.submissions, "Already submitted clicks are not queue cancellations."
    if armed:
        assert capture.winners == {}, (change, capture.winners)


def test_real_kaolai_owner_retries_only_after_pending_expiry(bip_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    r = bip_runtime
    state = configure_kaolai(r, monkeypatch)
    selected, _ = mechanics_build(r, True, monkeypatch)
    selected.OnContractActivated()
    pending = selected.ProcessSkillCasting()
    assert next(pending) is None
    pending.close()
    Timer.now = 249
    finish(selected.ProcessSkillCasting())
    assert state.clicks == [1]
    Timer.now = 250
    finish(selected.ProcessSkillCasting())
    assert state.clicks == [1, 1] and state.holding


def test_smart_kaolai_has_no_cross_account_pending_or_preparation_state(
    bip_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = bip_runtime
    state = configure_kaolai(r, monkeypatch)
    first, _ = mechanics_build(r, True, monkeypatch)
    first.OnContractActivated()
    finish(first.ProcessSkillCasting())
    r.state.agent, r.state.name = 2, "Second necromancer"
    r.core.Player.GetAccountEmail = lambda: "second@example.invalid"
    second, _ = mechanics_build(r, True, monkeypatch)
    second.OnContractActivated()
    assert first._smart_kaolai is not second._smart_kaolai
    assert second._local_cast_timer.IsStopped()
    finish(second.ProcessSkillCasting())
    assert state.clicks == [1, 2]
    first.Dispose()
    assert second._local_cast_timer.deadline == 250
    Timer.now = 250
    state.holding = False
    finish(second.ProcessSkillCasting())
    assert r.world.submissions == [(5, 2, 250)]


def test_match_only_does_not_construct_smart_kaolai(runtime: Any) -> None:
    candidate = runtime.Custom(match_only=True)
    assert candidate.ScoreMatch() == 1008
    assert not hasattr(candidate, "_smart_kaolai")


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


@pytest.fixture
def capture_runtime(bip_runtime: Any, spirit_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Production selection, owner, reader, control and widget; native boundaries only."""
    r = bip_runtime
    assert r is spirit_runtime
    r.control = admission._load(
        monkeypatch, "Py4GWCoreLib.Builds.Skills.BipDiagnostic", "Py4GWCoreLib/Builds/Skills/BipDiagnostic.py"
    )
    publication_clock = admission._load(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync",
        "Py4GWCoreLib/GlobalCache/shared_memory_src/IntentSync.py",
    )
    monkeypatch.setattr(publication_clock, "get_uncached_tick_count64", lambda: 10000)
    admission._module(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.shared_memory_src.Globals",
        SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS=5000,
    )

    class PublishedHealth:
        @property
        def Current(self) -> float:
            return float(r.world.get_health(2))

    r.publication = SimpleNamespace(
        IsAccount=True,
        IsSlotActive=True,
        AccountEmail="recipient@example.invalid",
        LastUpdated=9999,
        IsHero=False,
        IsPet=False,
        IsNPC=False,
        IsIsolated=False,
        AgentPartyData=SimpleNamespace(PartyID=7),
        AgentData=SimpleNamespace(
            AgentID=2,
            LoginNumber=2,
            OwnerAgentID=0,
            Map=SimpleNamespace(MapID=10, Region=1, District=1, Language=0),
            Energy=SimpleNamespace(Current=0.4),
            Health=PublishedHealth(),
            Is_Dead=False,
            Is_DeadByTypeMap=False,
            Buffs=SimpleNamespace(Buffs=[]),
            Profession=(5, 0),
        ),
    )

    def publications(*, sort_results: bool) -> list[Any]:
        assert not sort_results
        return [r.publication]

    def login_agent(login: int) -> int:
        return login

    def attributes(_agent: int) -> list[Any]:
        return [
            SimpleNamespace(attribute_id=33, level=12, base_level=8),
            SimpleNamespace(attribute_id=4, level=13, base_level=9),
        ]

    r.core.GLOBAL_CACHE.ShMem = SimpleNamespace(GetAllAccountData=publications, GetBaseTimestamp=lambda: 10000)
    r.core.GLOBAL_CACHE.Party = SimpleNamespace(
        GetPartyID=lambda: 7,
        GetPlayers=lambda: [SimpleNamespace(login_number=2, is_connected=True)],
        Players=SimpleNamespace(GetAgentIDByLoginNumber=login_agent),
    )
    r.core.GLOBAL_CACHE.Effects = SimpleNamespace(HasEffect=false)
    r.core.Agent.GetAttributes = attributes
    r.ui = SimpleNamespace(clicked="", texts=[], ends=0)

    def end() -> None:
        r.ui.ends += 1

    def visible(_name: str) -> bool:
        return True

    def clicked(name: str) -> bool:
        return name == r.ui.clicked

    def combo(_label: str, selected: int, _items: Any) -> int:
        return selected

    r.core.PyImGui = SimpleNamespace(
        begin=visible,
        end=end,
        text=r.ui.texts.append,
        button=clicked,
        same_line=noop,
        separator=noop,
        combo=combo,
    )
    r.widget = admission._load(monkeypatch, "_custom_bip_widget", "Widgets/Coding/Debug/Py4GW/Smart BiP Diagnostic.py")
    r.now = 0.0
    r.output = []

    def click(label: str) -> Any:
        r.ui.clicked = label
        r.widget.draw()
        r.ui.clicked = ""
        pending = r.control.pending_capture()
        if pending is not None:
            pending.clock = lambda: r.now
            pending.emit = r.output.append
        return pending

    r.click = click
    r.outer = r.Hero(cached_data=r.cache)
    # Real metadata, while unavailable world/weapon details use the Phase A
    # native stubs. No owner method or diagnostic observation is replaced.
    metadata_module: Any = sys.modules["Py4GWCoreLib.HeroAI.custom_skill"]
    metadata_module.CustomSkillClass = lambda: SimpleNamespace(get_skill=r.world.metadata.__getitem__)
    return r


@pytest.mark.parametrize("arm_first", [False, True])
def test_custom_capture_claim_requires_selected_execution(capture_runtime: Any, arm_first: bool) -> None:
    r = capture_runtime
    r.widget.on_enable()
    assert not r.control._armed
    capture: Any = r.click("Arm one capture") if arm_first else None
    registry = r.Registry(build_init_kwargs={"cached_data": r.cache})
    candidate = registry.GetBestBuild()
    assert isinstance(candidate, r.Custom) and not candidate._active
    candidate._diagnostic_begin()
    assert candidate._bip_diagnostic is None
    selected = r.outer.EnsureBuildContract()
    assert isinstance(selected, r.Custom) and selected._active
    assert selected is not candidate
    assert selected._bip_diagnostic is None
    if not arm_first:
        trace_rotation(selected, selected.skillbook, None)
        capture = r.click("Arm one capture")
    # Even an explicitly executed generic handler cannot steal this pending arm.
    generic = r.Generic()
    trace_rotation(generic, generic.skills, None)
    assert generic._bip_diagnostic is None and capture.started is None
    assert r.control.pending_capture("Blood is Power Healer") is None
    r.state.aggro = False
    trace_rotation(selected, selected.skillbook, None)
    r.now = 80
    r.widget.update()
    assert capture.started is None and not r.output
    r.state.aggro = True
    # Run the configured production rotation through HeroAI -> ProcessCombat.
    finish(r.outer.ProcessCombat())
    assert selected._bip_diagnostic is capture and capture.started == 80
    assert selected.skillbook.Necromancer.BloodMagic.bip_diagnostic is capture
    assert selected.skillbook.Ritualist.RestorationMagic.bip_diagnostic is capture
    assert selected.GetSupportedSkills() == selected.GetBlockedSkills() == IDS
    assert r.calls[-1] == set(IDS)
    assert capture.samples == 1 and capture.totals["demand40_mesmer"] == 1
    assert capture.last.restoration == 12 and capture.last.blood == 13 and capture.last.hr == "False"
    assert r.control.pending_capture() is None and len(r.output) == 1


@pytest.mark.parametrize("success_at", [None, *range(1, 23)])
def test_custom_capture_all_branch_labels_and_action_yields(capture_runtime: Any, success_at: int | None) -> None:
    r = capture_runtime
    selected = r.outer.EnsureBuildContract()
    assert selected._diagnostic_snapshot().demand == frozenset({2})
    disarmed = trace_rotation(selected, selected.skillbook, success_at)
    capture = r.click("Arm one capture")
    armed = trace_rotation(selected, selected.skillbook, success_at)
    assert armed == disarmed, (success_at, disarmed, armed)
    assert capture.samples == 1 and not capture.done
    winner = armed[1][-1][0] if success_at else "none"
    assert capture.winners == {winner: 1}, (success_at, capture.winners)
    assert capture.preemptions == ({winner: 1} if success_at and success_at < 8 else {})
    assert capture.totals["health_only"] == 0 and capture.health_only_seconds == 0


@pytest.mark.parametrize(
    "change",
    ["generic", "pvp", "zone", "name", "agent", "map", "uptime", "agent_uptime", "slots", "invalid", "cache", "clear"],
)
def test_custom_capture_lifecycle_aborts_and_cannot_transfer(capture_runtime: Any, change: str) -> None:
    r = capture_runtime
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")
    trace_rotation(selected, selected.skillbook, None)
    assert capture.samples == 1 and not capture.done
    if change == "generic":
        r.state.bar[5] = r.world.skill_id("Wielders_Boon")
    elif change == "pvp":
        r.state.bar[5:7] = [3012, 3013]
    elif change == "zone":
        r.world.explorable = False
    elif change == "name":
        r.state.name = "Another character"
    elif change == "agent":
        r.state.agent = 3
    elif change == "map":
        r.state.map += 1
    elif change in ("uptime", "agent_uptime"):
        setattr(r.state, change, 1)
    elif change == "slots":
        r.state.bar.reverse()
    elif change == "invalid":
        r.state.valid = False
    elif change == "cache":
        selected.set_cached_data(SimpleNamespace(combat_handler=type(r.cache.combat_handler)()))
    else:
        r.outer.ClearBuildContract()
    if change in ("generic", "pvp", "zone", "map", "slots"):
        r.outer.EnsureBuildContract()
    elif change not in ("cache", "clear"):
        finish(selected.ProcessSkillCasting())
    assert capture.done and not r.control._armed, (change, capture.result)
    assert selected._bip_diagnostic is None
    assert selected.skillbook.Necromancer.BloodMagic.bip_diagnostic is None
    assert selected.skillbook.Ritualist.RestorationMagic.bip_diagnostic is None
    assert capture.pending is None and capture.health_only_seconds == 0
    assert len(r.output) == 2 and "ABORTED" in r.output[-1]
    r.state.bar, r.world.explorable, r.state.valid = IDS.copy(), True, True
    successor = r.outer.EnsureBuildContract()
    trace_rotation(successor, successor.skillbook, None)
    assert successor._bip_diagnostic is None and len(r.output) == 2


def test_custom_pending_capture_waits_through_outpost_and_pvp_bar(capture_runtime: Any) -> None:
    r = capture_runtime
    capture = r.click("Arm one capture")
    r.world.explorable = False
    assert r.outer.EnsureBuildContract() is None
    r.world.explorable = True
    r.state.bar[5:7] = [3012, 3013]
    generic = r.outer.EnsureBuildContract()
    assert isinstance(generic, r.Generic)
    trace_rotation(generic, generic.skills, None)
    r.now = 100
    r.widget.update()
    assert capture.started is None and not r.output
    r.state.bar = IDS.copy()
    custom = r.outer.EnsureBuildContract()
    trace_rotation(custom, custom.skillbook, None)
    assert custom._bip_diagnostic is capture and capture.started == 100


@pytest.fixture
def capture_actions(capture_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reach real helpers and queue submissions through the selected custom owner."""
    r = capture_runtime
    r.world.health.update({1: 0.86, 2: 0.90, 3: 0.90, 4: 0.90})
    r.world.place(10, 500)
    r.core.Party = SimpleNamespace(IsPartyLoaded=lambda: False)
    admission._module(monkeypatch, "Py4GWCoreLib.FrameTree", FrameTree=SimpleNamespace())
    monkeypatch.setattr(r.core.AgentArray, "GetEnemyArray", staticmethod(empty_list))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsMartial", staticmethod(false))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsMelee", staticmethod(false))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsConditioned", staticmethod(false))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "IsAlive", staticmethod(r.world.is_alive))
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "GetHealth", staticmethod(r.world.get_health))
    admission._module(monkeypatch, "Py4GWCoreLib.Effect", Effects=SimpleNamespace(HasEffect=false))
    r.core.Agent.IsPoisoned = r.core.Agent.IsBleeding = r.core.Agent.IsDegenHexed = false
    r.core.Agent.IsCrippled = false
    r.ready = {119}

    def ready(skill: int) -> bool:
        return skill in r.ready

    monkeypatch.setattr(r.core.Routines.Checks.Skills, "IsSkillIDReady", staticmethod(ready))
    r.selected = r.outer.EnsureBuildContract()
    return r


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
def test_custom_real_life_queue_yields_and_abandoned_pass(capture_actions: Any, armed: bool, cancel: bool) -> None:
    r = capture_actions
    capture: Any = r.click("Arm one capture") if armed else None
    # Initial completed health-only observation; real BiP selects a recipient.
    assert list(r.outer.ProcessCombat()) == [None]
    assert not r.world.submissions
    if armed:
        assert capture.samples == capture.totals["health_only"] == 1, capture.totals
    r.now, Timer.now, r.ready = 0.25, 250, {119, 1251}
    assert list(r.outer.Tick(True)) == [None]
    assert r.world.submissions == [(6, 0, 250)]
    pending = r.outer._tick_coroutine
    assert pending is not None and r.selected._local_cast_timer.deadline == 500
    if armed:
        assert capture.pending is not None and capture.samples == 1
    r.now, Timer.now = 0.30, 300
    if cancel:
        r.outer.ResetTickExecution()
        assert pending.gi_frame is None
        assert list(r.outer.ProcessCombat()) == [None]
    else:
        assert list(pending) == [None] * 10
        r.outer.ResetTickExecution()
    assert r.world.submissions == [(6, 0, 250)]
    if armed:
        assert capture.pending is None and capture.health_only_seconds == 0
        assert capture.totals["health_only"] == 1
        assert capture.totals["after_health_action"] == (0 if cancel else 1)
    r.ready = {119}
    for now in (0.50, 0.75):
        r.now, Timer.now = now, int(now * 1000)
        finish(r.outer.ProcessCombat())
    assert r.world.submissions == [(6, 0, 250)]
    if armed:
        assert capture.totals["health_only"] == 3 and capture.health_only_seconds == 0.25


@pytest.mark.parametrize("ending", ["stop", "disable", "complete"])
def test_selected_custom_can_rearm_after_control_ends(capture_runtime: Any, ending: str) -> None:
    r = capture_runtime
    selected = r.outer.EnsureBuildContract()
    first = r.click("Arm one capture")
    trace_rotation(selected, selected.skillbook, None)
    if ending == "stop":
        r.click("Stop")
    elif ending == "disable":
        r.widget.on_disable()
    else:
        for now in (10, 20, 30, 40, 50, 60):
            r.now = now
            r.widget.update()
        assert len(r.output) == 8 and first.result == "COMPLETE"
    assert first.done and first.pending is None and not r.control._armed
    r.widget.on_enable()
    assert not r.control._armed
    second = r.click("Arm one capture")
    assert second is not first and second.samples == 0
    r.now += 1
    trace_rotation(selected, selected.skillbook, None)
    assert selected._bip_diagnostic is second and second.samples == 1
    first.stop()
    assert r.control._armed and not second.done


@pytest.mark.parametrize("skill", [962, 915, 1234])
def test_rescue_and_routine_histories_preserve_actions_and_capture_budget(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, skill: int
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.place(10, 500 if skill == 915 else 1100)
    ready = False

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if ready and r.state.bar[slot - 1] == skill else 1)

    r.core.SkillBar.GetSkillData = skill_data
    selected = r.outer.EnsureBuildContract()
    for history in ("A", "B"):
        base_time = r.now + 1
        output_before = len(r.output)
        capture = r.click("Arm one capture")
        state.clicks.clear()
        r.world.submissions.clear()
        for pass_index, health in enumerate(((0.74, 0.09, 0.30, 0.74), (0.74, 0.09, 0.74, 0.74), (1.0,) * 4)):
            r.now = base_time + pass_index
            Timer.now = int(r.now * 1000)
            r.world.health.update(dict(zip((1, 2, 3, 4), health)))
            ready = pass_index == (0 if history == "A" else 1)
            finish(selected.ProcessSkillCasting())
        assert r.world.submissions == [(IDS.index(skill) + 1, 2, 250)] and state.clicks == [1], history
        assert capture.winners[NAMES[IDS.index(skill)]] == capture.winners["Drop_Held_Bundle"] == 1
        assert capture.kaolai.counts["click_call_returned"] == 1
        for elapsed in (10, 20, 30, 40, 50, 60):
            r.now = base_time + elapsed
            r.widget.update()
        assert capture.done and len(r.output) - output_before == capture.records == 8
        assert "kaolai=[" in r.output[-1]
        assert all("kaolai_emergency=[" not in line for line in r.output)


@pytest.mark.parametrize("ending", ["complete", "stop", "reset", "cancel"])
def test_failed_rescue_drop_capture_reset_and_rearm(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.place(10, 1100)
    r.world.health.update({1: 0.74, 2: 0.09, 3: 0.30, 4: 0.74})
    ready = False

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if ready and r.state.bar[slot - 1] == 962 else 1)

    r.core.SkillBar.GetSkillData = skill_data
    selected = r.outer.EnsureBuildContract()
    first = r.click("Arm one capture")
    work = selected.ProcessSkillCasting()
    next(work)
    assert first.kaolai.counts["routine_entry"] == 1
    assert not r.world.submissions and state.clicks == [1], "Failed rescues reached the yielding routine drop."
    if ending == "complete":
        for now in (10, 20, 30, 40, 50, 60):
            r.now = now
            r.widget.update()
        assert len(r.output) == 8
    elif ending == "reset":
        first.discard_pending()
        r.click("Stop")
    elif ending == "cancel":
        work.close()
        finish(selected.ProcessSkillCasting())  # Unsampled entry resets the unfinished pass.
        r.click("Stop")
    else:
        r.click("Stop")
    work.close()
    old_counts = dict(first.kaolai.counts)
    assert first.done and first.pending is None and not old_counts.get("drop_selected", 0)
    r.now, Timer.now = 61.0, 61000
    r.world.health[3] = 0.74  # One injured recipient: targeted winner without a deferral.
    ready = True
    second = r.click("Arm one capture")
    finish(selected.ProcessSkillCasting())
    assert second is not first and second.winners["Spirit_Transfer"] == 1
    first.finish("Spirit_Transfer", preempted=True)
    assert first.kaolai.counts == old_counts
    assert r.world.submissions == [(2, 2, 250)] and state.clicks == [1]
    r.click("Stop")


def test_targeted_heal_survives_capture_accounting_exception(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.place(10, 1100)
    r.world.health.update({1: 0.74, 2: 0.09, 3: 0.30, 4: 0.74})

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if r.state.bar[slot - 1] == 962 else 1)

    r.core.SkillBar.GetSkillData = skill_data
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")
    smart: Any = sys.modules["Py4GWCoreLib.Builds.Skills.SmartKaolai"]

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Injected capture accounting failure")

    monkeypatch.setattr(smart.KaolaiCapture, "finish", broken)
    finish(selected.ProcessSkillCasting())
    assert capture.result == "ABORTED_ACCOUNTING_ERROR"
    assert r.world.submissions == [(2, 2, 250)] and not state.clicks
    assert selected.DidTickSucceed() and selected._local_cast_timer.deadline == 250


@pytest.mark.parametrize("skill", [962, 915, 1234])
@pytest.mark.parametrize(
    "health,caster_hp,group_wins",
    [
        ((0.28, 0.34, 0.37), 1.0, True),
        ((0.28, 0.34, 1.0), 1.0, True),
        ((0.09, 1.0, 1.0), 1.0, False),
        ((0.09, 0.34, 0.37), 1.0, False),
        ((0.28, 0.34, 0.37), 0.74, True),
        ((0.35, 0.35, 0.74), 0.74, True),
        ((0.39, 0.39, 0.39), 0.39, True),
        ((0.20, 0.35, 0.74), 0.74, True),
        ((0.19, 0.30, 0.74), 0.74, False),
        ((0.10, 0.74, 0.74), 0.74, False),
    ],
)
def test_real_owner_selects_group_recovery_or_critical_targeted_rescue(
    capture_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    skill: int,
    health: tuple[float, ...],
    caster_hp: float,
    group_wins: bool,
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update({1: caster_hp, **dict(zip((2, 3, 4), health))})
    r.world.place(10, 500 if skill == 915 else 1100)

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if r.state.bar[slot - 1] == skill else 1)

    r.core.SkillBar.GetSkillData = skill_data
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")
    finish(selected.ProcessSkillCasting())
    expected = [] if group_wins else [(IDS.index(skill) + 1, 2, 250)]
    assert r.world.submissions == expected, (skill, health, r.world.submissions)
    assert state.clicks == ([1] if group_wins else [])
    assert selected._local_cast_timer.deadline == 250
    winner = "Drop_Held_Bundle" if group_wins else NAMES[IDS.index(skill)]
    assert capture.winners == {winner: 1}
    assert not capture.kaolai.counts["drop_checked"], "The winner must precede the ordinary routine-drop branch."
    assert not capture.kaolai.counts["generic_held_cleared"]


@pytest.mark.parametrize("failure", ["recharge", "no_spirit", "energy"])
@pytest.mark.parametrize("fourth_hp", [1.0, 0.74])
@pytest.mark.parametrize("armed", [False, True])
def test_real_failed_critical_rescue_falls_through_to_emergency_kaolai(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, failure: str, fourth_hp: float, armed: bool
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update({1: fourth_hp, 2: 0.09, 3: 0.34, 4: 0.37})
    r.world.place(10, 3000 if failure == "no_spirit" else 1100)
    r.world.energy = 0 if failure == "energy" else 1.0

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if r.state.bar[slot - 1] == 962 and failure != "recharge" else 1)

    r.core.SkillBar.GetSkillData = skill_data
    selected = r.outer.EnsureBuildContract()
    capture: Any = r.click("Arm one capture") if armed else None
    finish(selected.ProcessSkillCasting())
    assert not r.world.submissions and state.clicks == [1], (failure, r.world.submissions)
    assert selected._local_cast_timer.deadline == 250
    if not armed:
        assert not r.output
        return
    assert capture.winners["Drop_Held_Bundle"] == capture.kaolai.counts["click_call_returned"] == 1


@pytest.mark.parametrize(
    "health",
    [(0.60, 0.65, 0.70, 0.74), (0.40, 0.40, 0.40, 0.40), (0.74, 0.3501, 0.35, 0.74)],
)
def test_four_person_nonemergency_keeps_actual_routine_order(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, health: tuple[float, ...]
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update(dict(zip((1, 2, 3, 4), health)))
    selected = r.outer.EnsureBuildContract()
    capture = r.click("Arm one capture")
    finish(selected.ProcessSkillCasting())
    assert state.clicks == [1] and not r.world.submissions, health
    assert capture.kaolai.counts["drop_checked"] == capture.kaolai.counts["click_call_returned"] == 1
    assert capture.winners == {"Drop_Held_Bundle": 1}
    assert selected._local_cast_timer.deadline == 250


@pytest.mark.parametrize("change", ["recovered", "manual_drop", "disconnected", "death", "outside"])
@pytest.mark.parametrize("armed", [False, True])
def test_emergency_fallthrough_uses_fresh_evidence_after_failed_rescue(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, change: str, armed: bool
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update({1: 1.0, 2: 0.09, 3: 0.34, 4: 1.0})
    r.world.place(10, 1100)
    reads: list[int] = []

    def rejected_skill(slot: int) -> SimpleNamespace:
        skill = r.state.bar[slot - 1]
        reads.append(skill)
        if skill == 962:
            if change == "recovered":
                r.world.health[3] = 1.0
            elif change == "manual_drop":
                state.holding = False
            elif change == "disconnected":
                state.players[2].is_connected = False
            elif change == "death":
                r.world.dead.add(3)
            else:
                r.world.place(3, 2500.01)
        return SimpleNamespace(recharge=1)

    r.core.SkillBar.GetSkillData = rejected_skill
    selected = r.outer.EnsureBuildContract()
    capture: Any = r.click("Arm one capture") if armed else None
    finish(selected.ProcessSkillCasting())
    assert 962 in reads, "The test must reach real targeted-rescue admission."
    assert not state.clicks and not r.world.submissions, (change, reads)
    assert selected._local_cast_timer.IsStopped()
    if not armed:
        assert not r.output
        return
    assert not capture.kaolai.counts["click_call_returned"]


@pytest.mark.parametrize("gate", ["not_held", "button", "insufficient", "uncertain_remote"])
def test_unavailable_emergency_kaolai_keeps_actual_spot_heal_available(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update({1: 1.0, 2: 0.28, 3: 0.34, 4: 1.0})
    r.world.place(10, 1100)
    if gate == "not_held":
        state.holding = False
    elif gate == "button":
        state.button_present = False
    elif gate == "insufficient":
        r.world.health[3] = 1.0
    else:
        r.publication.LastUpdated = 9000

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if r.state.bar[slot - 1] == 962 else 1)

    r.core.SkillBar.GetSkillData = skill_data
    selected = r.outer.EnsureBuildContract()
    finish(selected.ProcessSkillCasting())
    assert state.clicks == [] and r.world.submissions == [(2, 2, 250)], gate
    assert selected._local_cast_timer.deadline == 250


@pytest.mark.parametrize("change", ["close", "dispose", "map_invalid", "death", "casting"])
def test_emergency_owner_lifecycle_can_stop_before_any_submission(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update({1: 1.0, 2: 0.28, 3: 0.34, 4: 0.37})
    selected = r.outer.EnsureBuildContract()
    work = selected.ProcessSkillCasting()
    if change == "close":
        work.close()
    elif change == "dispose":
        selected.Dispose()
    elif change == "map_invalid":
        r.state.valid = False
    elif change == "death":
        r.world.dead.add(1)
        r.state.can_cast = False
    else:
        r.state.can_cast = False
    assert list(work) == ([None] if change in {"death", "casting"} else [])
    assert not state.clicks and not r.world.submissions, change


def test_emergency_owner_has_one_pending_submission_and_preserves_fallback_mask(
    capture_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = capture_runtime
    state = configure_kaolai(r, monkeypatch)
    r.world.health.update({1: 1.0, 2: 0.28, 3: 0.34, 4: 0.37})
    selected = r.outer.EnsureBuildContract()
    work = selected.ProcessSkillCasting()
    assert next(work) is None
    assert state.clicks == [1] and selected._local_cast_timer.deadline == 250
    work.close()
    for Timer.now in (0, 100, 249):
        finish(selected.ProcessSkillCasting())
    assert state.clicks == [1] and not r.world.submissions
    assert selected.GetSupportedSkills() == selected.GetBlockedSkills() == IDS
    assert r.cache.combat_handler.blocked_skill_ids == set(IDS)
    # Pending suppresses all competing actions only for the existing window.
    Timer.now, state.holding = 250, False
    r.world.place(10, 1100)

    def skill_data(slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=0 if r.state.bar[slot - 1] == 962 else 1)

    r.core.SkillBar.GetSkillData = skill_data
    finish(selected.ProcessSkillCasting())
    assert state.clicks == [1] and r.world.submissions == [(2, 2, 250)]


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("skill,hp", [(1234, 0.67), (962, 0.45), (915, 0.55)])
def test_custom_real_later_self_heal_excludes_health_only(
    capture_actions: Any, armed: bool, skill: int, hp: float
) -> None:
    r = capture_actions
    r.world.health[1] = hp
    r.ready.add(skill)
    capture: Any = r.click("Arm one capture") if armed else None
    # Low energy recipients remain healthy; this is an actual self-heal after BiP rejection.
    assert finish(r.selected._run_local_skill_logic()) is True
    assert r.world.submissions == [(IDS.index(skill) + 1, 1, 250)], (armed, skill, r.world.submissions)
    if armed:
        assert capture.samples == 1 and capture.totals["health_reject"] == 1
        assert capture.totals["after_health_action"] == capture.totals["heal_self_q"] == 1
        assert capture.totals["health_only"] == 0 and capture.health_only_seconds == 0


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("after", ["blocked", "hp_rise", "recovered", "floor_changed"])
def test_unsampled_cancellation_breaks_all_interval_continuity(capture_actions: Any, armed: bool, after: str) -> None:
    r = capture_actions
    r.maximum = 280 if after == "floor_changed" else 500

    def maximum(_agent: int) -> int:
        return r.maximum

    r.core.Agent.GetMaxHealth = maximum
    if after == "floor_changed":
        r.world.health[1] = 0.94
    capture: Any = r.click("Arm one capture") if armed else None
    assert list(r.outer.ProcessCombat()) == [None]
    if armed:
        assert capture.samples == capture.totals["health_only"] == 1
        assert capture.pending is None and capture.next_sample == 0.25
    r.now, Timer.now, r.ready = 0.10, 100, {119, 1251}
    assert list(r.outer.Tick(True)) == [None]
    assert r.world.submissions == [(6, 0, 250)]
    assert r.selected._local_cast_timer.deadline == 350
    if armed:
        assert capture.pending is None and capture.samples == 1, "The intervening Life pass is unsampled."
        assert capture.next_sample == 0.25
    suspended = r.outer._tick_coroutine
    r.outer.ResetTickExecution()
    assert suspended.gi_frame is None and r.outer._tick_coroutine is None
    # Closing ordinary queued work does not cancel its pending timer.
    assert r.selected._local_cast_timer.deadline == 350
    r.now, Timer.now, r.ready = 0.36, 360, {119}
    r.maximum = 500
    if after == "hp_rise":
        r.world.health[1] = 0.875
    elif after == "recovered":
        r.world.health[1] = 1.0
    safe = after in {"recovered", "floor_changed"}
    assert list(r.outer.ProcessCombat()) == ([] if safe else [None])
    expected_queue = [(6, 0, 250)] + ([(1, 2, 250)] if safe else [])
    assert r.world.submissions == expected_queue, (armed, after, r.world.submissions)
    assert r.selected._local_cast_timer.deadline == (610 if safe else None)
    if not armed:
        assert r.selected._bip_diagnostic is None
        return
    observed = {
        "samples": capture.samples,
        "health_only": capture.totals["health_only"],
        "health_only_s": capture.health_only_seconds,
        "sampled_s": capture.sampled_seconds,
        "demand_s": capture.demand_seconds,
        "hp_block_s": capture.hp_block_seconds,
        "block_streak": capture.block_streak,
        "max_block_streak": capture.max_block_streak,
        "hp_rise": capture.totals["hp_rise"],
        "recovered": capture.totals["recovered"],
        "floor_changed": capture.totals["floor_changed"],
    }
    assert observed == {
        "samples": 2,
        "health_only": 1 if safe else 2,
        "health_only_s": 0,
        "sampled_s": 0,
        "demand_s": 0,
        "hp_block_s": 0,
        "block_streak": 0,
        "max_block_streak": 0,
        "hp_rise": 0,
        "recovered": 0,
        "floor_changed": 0,
    }, (after, observed)
    assert capture.pending is None and capture.next_sample == 0.61
    if not safe:
        # The fix must allow continuity to restart between valid completed samples.
        r.now, Timer.now = 0.61, 610
        assert list(r.outer.ProcessCombat()) == [None]
        assert capture.samples == capture.totals["health_only"] == 3
        assert capture.health_only_seconds == capture.sampled_seconds == capture.demand_seconds == 0.25
        assert capture.hp_block_seconds == capture.block_streak == capture.max_block_streak == 0.25


def test_completed_unsampled_decisions_preserve_legitimate_continuity(capture_actions: Any) -> None:
    r = capture_actions
    capture = r.click("Arm one capture")
    for now in (0.00, 0.10, 0.25, 0.30, 0.50):
        r.now, Timer.now = now, int(now * 1000)
        assert list(r.outer.ProcessCombat()) == [None]
    assert capture.samples == capture.totals["health_only"] == 3
    assert capture.winners == {"none": 5}
    assert capture.health_only_seconds == capture.sampled_seconds == capture.demand_seconds == 0.50
    assert capture.hp_block_seconds == capture.block_streak == capture.max_block_streak == 0.50
    assert not r.world.submissions and r.selected._local_cast_timer.IsStopped()


@pytest.mark.parametrize("armed", [False, True])
def test_unsampled_accepted_life_resumes_without_starting_another_decision(capture_actions: Any, armed: bool) -> None:
    r = capture_actions
    capture: Any = r.click("Arm one capture") if armed else None
    assert list(r.outer.ProcessCombat()) == [None]
    first = capture.previous if armed else None
    r.now, Timer.now, r.ready = 0.10, 100, {119, 1251}
    assert list(r.outer.Tick(True)) == [None]
    suspended = r.outer._tick_coroutine
    # Resumption happens after sampling would be due, but is still the same pass.
    r.now, Timer.now = 0.30, 300
    for _ in range(10):
        assert list(r.outer.Tick(True)) == [None]
        assert r.outer._tick_coroutine is suspended
        if armed:
            assert capture.pending is None and capture.samples == 1
            assert capture.next_sample == 0.25 and capture.previous is first
    assert list(r.outer.Tick(True)) == [None]
    assert r.outer._tick_coroutine is None and suspended.gi_frame is None
    if armed:
        assert capture.winners == {"none": 1, "Life": 1}
        assert capture.previous is None, "Existing finish() must break continuity for an unsampled accepted action."
    r.now, Timer.now, r.ready = 0.36, 360, {119}
    assert list(r.outer.ProcessCombat()) == [None]
    assert r.world.submissions == [(6, 0, 250)]
    assert r.selected._local_cast_timer.IsStopped()
    if armed:
        assert capture.samples == capture.totals["health_only"] == 2
        assert capture.health_only_seconds == capture.sampled_seconds == capture.demand_seconds == 0
        assert capture.hp_block_seconds == capture.block_streak == capture.max_block_streak == 0


@pytest.mark.parametrize("sampled", [False, True])
def test_repeated_cancelled_decisions_preserve_only_finalized_history(capture_actions: Any, sampled: bool) -> None:
    r = capture_actions
    capture = r.click("Arm one capture")
    # Preserve real duration already finalized before any cancellation.
    for now in (0.00, 0.25):
        r.now, Timer.now = now, int(now * 1000)
        assert list(r.outer.ProcessCombat()) == [None]
    assert capture.samples == 2 and capture.health_only_seconds == 0.25
    finalized = capture.totals.copy()
    start = 0.50 if sampled else 0.35
    for now in (start, start + 0.26):
        r.now, Timer.now, r.ready = now, round(now * 1000), {119, 1251}
        assert list(r.outer.Tick(True)) == [None]
        suspended = r.outer._tick_coroutine
        assert capture.totals == finalized and capture.samples == 2
        r.outer.ResetTickExecution()
        assert suspended.gi_frame is None
    assert r.world.submissions == [(6, 0, 250), (6, 0, 250)]
    r.now, Timer.now, r.ready = start + 0.52, round((start + 0.52) * 1000), {119}
    assert list(r.outer.ProcessCombat()) == [None]
    assert capture.pending is None and capture.samples == capture.totals["health_only"] == 3
    assert capture.health_only_seconds == capture.sampled_seconds == capture.demand_seconds == 0.25
    assert capture.hp_block_seconds == capture.max_block_streak == 0.25 and capture.block_streak == 0


@pytest.mark.parametrize("ending", ["stop", "dispose", "complete"])
def test_unsampled_decision_cannot_leak_through_capture_end_and_rearm(capture_actions: Any, ending: str) -> None:
    r = capture_actions
    first = r.click("Arm one capture")
    assert list(r.outer.ProcessCombat()) == [None]
    r.now, Timer.now, r.ready = 0.10, 100, {119, 1251}
    assert list(r.outer.Tick(True)) == [None]
    suspended = r.outer._tick_coroutine
    assert first.pending is None and first.samples == 1
    if ending == "stop":
        r.click("Stop")
    elif ending == "dispose":
        r.outer.ClearBuildContract()
        assert suspended.gi_frame is None
    else:
        r.now = 60
        r.widget.update()
    assert first.done and first.pending is None and first.previous is None
    second = r.click("Arm one capture")
    assert second is not first and second.started is None
    if ending != "dispose":
        # Old work may finish after rearming; it must still belong to the old capture.
        assert list(suspended) == [None] * 10
        r.outer.ResetTickExecution()
        assert second.started is None and second.samples == 0
    r.now += 1
    Timer.now, r.ready = round(r.now * 1000), {119}
    assert list(r.outer.ProcessCombat()) == [None]
    assert r.selected._bip_diagnostic is second
    assert second.samples == second.totals["health_only"] == 1
    assert second.health_only_seconds == second.sampled_seconds == second.demand_seconds == 0
    assert first.samples == first.totals["health_only"] == 1
    first.stop()
    assert r.control._armed and not second.done
