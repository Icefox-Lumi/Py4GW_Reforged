"""Offline stock admission coverage; no DLL observation or completed-healing claim."""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar

import pytest

TRANSFER = 962
LIGHT = 915
OTHER = 3000
ROOT = Path(__file__).resolve().parents[1]
_Function = TypeVar("_Function", bound=Callable[..., Any])


def _frame_cache(**_: Any) -> Callable[[_Function], _Function]:
    def decorate(function: _Function) -> _Function:
        return function

    return decorate


def _module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load(monkeypatch: pytest.MonkeyPatch, name: str, path: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _finish(coroutine: Generator[Any, None, Any]) -> Any:
    while True:
        try:
            next(coroutine)
        except StopIteration as result:
            return result.value


finish_coroutine = _finish
load_test_module = _load
install_test_module = _module


@dataclass
class _Timer:
    deadline: int | None = None
    delay: int = 0

    def IsStopped(self) -> bool:
        return self.deadline is None

    def IsExpired(self) -> bool:
        return False

    def Stop(self) -> None:
        self.deadline = None

    def SetThrottleTime(self, delay: int) -> None:
        self.delay = delay

    def Reset(self) -> None:
        self.deadline = self.delay


def _false(*args: Any, **kwargs: Any) -> bool:
    return False


def _first(values: list[int]) -> int:
    return values[0] if values else 0


def _empty(*args: Any, **kwargs: Any) -> list[int]:
    return []


@dataclass
class _SpiritWorld:
    origin: tuple[float, float] = (2300.0, -1700.0)
    positions: dict[int, tuple[float, float]] = field(default_factory=dict[int, tuple[float, float]])
    health: dict[int, float] = field(default_factory=lambda: {1: 0.8, 2: 0.2, 10: 1.0})
    valid: set[int] = field(default_factory=lambda: {1, 2, 10})
    dead: set[int] = field(default_factory=set[int])
    spawned: set[int] = field(default_factory=lambda: {10})
    spirits: list[int] = field(default_factory=lambda: [10])
    pets: list[int] = field(default_factory=list[int])
    allies: list[int] = field(default_factory=lambda: [1, 2])
    hostile: set[int] = field(default_factory=set[int])
    energy: float = 1.0
    recharge: int = 0
    slot: int = 2
    equipped_skill_id: int = TRANSFER
    explorable: bool = True
    adrenaline: bool = True
    skills_enabled: list[bool] = field(default_factory=lambda: [True] * 8)
    timer: _Timer = field(default_factory=_Timer)
    submissions: list[tuple[int, int, int]] = field(default_factory=list[tuple[int, int, int]])
    ids: dict[str, int] = field(default_factory=lambda: {"Spirit_Transfer": TRANSFER, "Spirit_Light": LIGHT})
    metadata: dict[int, Any] = field(default_factory=dict[int, Any])
    build: Any = None
    helper: Any = None
    routines: Any = None
    ranges: Any = None

    def skill_id(self, name: str) -> int:
        return self.ids.setdefault(name, 2000 + len(self.ids))

    def position(self, agent_id: int) -> tuple[float, float]:
        return self.positions.get(agent_id, self.origin)

    def place(self, agent_id: int, distance: float) -> None:
        self.positions[agent_id] = (self.origin[0] + distance, self.origin[1])

    def is_alive(self, agent_id: int) -> bool:
        return agent_id in self.valid and agent_id not in self.dead and self.get_health(agent_id) > 0.0001

    def is_dead(self, agent_id: int) -> bool:
        return not self.is_alive(agent_id)

    def get_health(self, agent_id: int) -> float:
        return self.health.get(agent_id, 0.0)

    def get_energy(self, agent_id: int) -> float:
        return self.energy

    def max_energy(self, agent_id: int) -> int:
        return 30

    def get_slot(self, skill_id: int) -> int:
        return self.slot if skill_id == self.equipped_skill_id else 0

    def equipped_skill(self, slot: int) -> int:
        return self.equipped_skill_id

    def skill_data(self, slot: int) -> SimpleNamespace:
        return SimpleNamespace(recharge=self.recharge)

    def skill_type(self, skill_id: int) -> tuple[int, str]:
        return 5, "Spell"

    def allegiance(self, agent_id: int) -> tuple[int, str]:
        if agent_id in self.hostile:
            return 3, "Enemy"
        if agent_id in self.spirits or agent_id in self.pets:
            return 4, "SpiritPet"
        return 1, "Ally"

    def spirit_pet_array(self) -> list[int]:
        return self.spirits + self.pets

    def energy_cost(self, skill_id: int, agent_id: int) -> int:
        return 10 if skill_id == TRANSFER else 5

    def has_adrenaline(self, slot: int) -> bool:
        return self.adrenaline

    def submit(self, slot: int, target_agent_id: int = 0, aftercast_delay: int = 0) -> None:
        self.submissions.append((slot, target_agent_id, aftercast_delay))

    def all_allies(self, distance: float, ordered: bool = True) -> list[int]:
        return list(self.allies)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _SpiritWorld:
    state = _SpiritWorld()
    state.place(10, 500.0)
    state.place(2, 300.0)
    core = _module(monkeypatch, "Py4GWCoreLib", Profession=SimpleNamespace())
    core.__path__ = []
    _module(monkeypatch, "PySystem")
    _module(monkeypatch, "PyAgent")
    _module(monkeypatch, "PyUIManager", FramePosition=object)
    _module(monkeypatch, "Py4GWCoreLib.enums_src").__path__ = []
    enums = _load(monkeypatch, "Py4GWCoreLib.enums_src.GameData_enums", "Py4GWCoreLib/enums_src/GameData_enums.py")
    state.ranges = enums.Range
    core.__dict__["Range"] = enums.Range
    _module(monkeypatch, "Py4GWCoreLib.enums", SPIRIT_BUFF_MAP={})
    player = SimpleNamespace(GetAgentID=lambda: 1, GetXY=lambda: state.origin, GetTargetID=lambda: 0)
    agent = SimpleNamespace(
        GetXY=state.position,
        IsAlive=state.is_alive,
        IsDead=state.is_dead,
        IsValid=state.valid.__contains__,
        IsSpawned=state.spawned.__contains__,
        GetHealth=state.get_health,
        GetEnergy=state.get_energy,
        GetMaxEnergy=state.max_energy,
        GetAllegiance=state.allegiance,
    )
    utils = SimpleNamespace(Distance=math.dist, GetFirstFromArray=_first)
    skill = SimpleNamespace(GetID=state.skill_id, GetType=state.skill_type)
    skillbar = SimpleNamespace(
        GetSlotBySkillID=state.get_slot,
        GetSkillIDBySlot=state.equipped_skill,
        GetSkillData=state.skill_data,
        UseSkill=state.submit,
    )
    cache = SimpleNamespace(Skill=skill, SkillBar=skillbar)
    routines = SimpleNamespace(Targeting=SimpleNamespace(GetAllAlliesArray=state.all_allies))
    core.__dict__.update(
        Agent=agent,
        Player=player,
        Utils=utils,
        Skill=skill,
        SkillBar=skillbar,
        GLOBAL_CACHE=cache,
        Routines=routines,
        ConsoleLog=_false,
        Console=SimpleNamespace(),
    )
    for name, value in (("Agent", agent), ("Player", player), ("Skill", skill), ("Skillbar", skillbar)):
        _module(monkeypatch, f"Py4GWCoreLib.{name}", **{("SkillBar" if name == "Skillbar" else name): value})
    _module(monkeypatch, "Py4GWCoreLib.GlobalCache", GLOBAL_CACHE=cache).__path__ = []
    _module(monkeypatch, "Py4GWCoreLib.GlobalCache.SharedMemory", SHMEM_MAX_EMAIL_LEN=64)
    _module(monkeypatch, "Py4GWCoreLib.Py4GWcorelib", Utils=utils)
    _module(monkeypatch, "Py4GWCoreLib.Context", GWContext=SimpleNamespace())
    _module(monkeypatch, "Py4GWCoreLib.native_src.context.AgentContext", AgentStruct=object)
    array_module = _load(monkeypatch, "Py4GWCoreLib.AgentArray", "Py4GWCoreLib/AgentArray.py")
    core.__dict__["AgentArray"] = array_module.AgentArray
    monkeypatch.setattr(array_module.AgentArray, "GetSpiritPetArray", staticmethod(state.spirit_pet_array))
    monkeypatch.setattr(array_module.AgentArray, "GetAllyArray", staticmethod(lambda: list(state.allies)))
    _module(monkeypatch, "Py4GWCoreLib.HeroAI").__path__ = []
    _module(
        monkeypatch,
        "Py4GWCoreLib.HeroAI.constants",
        Range=enums.Range,
        MAX_NUM_PLAYERS=8,
        NUMBER_OF_SKILLS=8,
        MAX_NUMBER_OF_BUFFS=30,
        BLOOD_IS_POWER=119,
        BLOOD_RITUAL=157,
    )
    _load(monkeypatch, "Py4GWCoreLib.HeroAI.types", "Py4GWCoreLib/HeroAI/types.py")
    _module(monkeypatch, "Py4GWCoreLib.HeroAI.custom_skill_src").__path__ = []
    metadata_types = _load(
        monkeypatch,
        "Py4GWCoreLib.HeroAI.custom_skill_src.skill_types",
        "Py4GWCoreLib/HeroAI/custom_skill_src/skill_types.py",
    )
    _module(
        monkeypatch, "Py4GWCoreLib.HeroAI.custom_skill", CustomSkill=metadata_types.CustomSkill, CustomSkillClass=object
    )
    metadata = _load(
        monkeypatch,
        "Py4GWCoreLib.HeroAI.custom_skill_src.ritualist",
        "Py4GWCoreLib/HeroAI/custom_skill_src/ritualist.py",
    )
    metadata.RitualistSkills(state.metadata)
    state.metadata[OTHER] = metadata_types.CustomSkill()
    state.metadata[OTHER].Conditions.RequiresSpiritInEarshot = True
    _module(monkeypatch, "Py4GWCoreLib.routines_src").__path__ = []
    agents = _load(monkeypatch, "Py4GWCoreLib.routines_src.Agents", "Py4GWCoreLib/routines_src/Agents.py")
    routines.Agents = agents.Agents
    _module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src").__path__ = []
    _module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.FrameCache", frame_cache=_frame_cache)
    checks = _load(monkeypatch, "Py4GWCoreLib.routines_src.Checks", "Py4GWCoreLib/routines_src/Checks.py")
    routines.Checks = checks.Checks
    monkeypatch.setattr(checks.Checks.Map, "IsExplorable", staticmethod(lambda: state.explorable))
    monkeypatch.setattr(checks.Checks.Skills, "GetEnergyCostWithEffects", staticmethod(state.energy_cost))
    monkeypatch.setattr(checks.Checks.Skills, "HasEnoughAdrenalineBySlot", staticmethod(state.has_adrenaline))
    _module(monkeypatch, "Py4GWCoreLib.HeroAI.utils", CheckForEffect=_false)
    _module(
        monkeypatch,
        "Py4GWCoreLib.EnemyBlacklist",
        EnemyBlacklist=lambda: SimpleNamespace(is_empty=lambda: True, is_blacklisted=_false),
    )
    _load(monkeypatch, "Py4GWCoreLib.HeroAI.targeting", "Py4GWCoreLib/HeroAI/targeting.py")
    _module(
        monkeypatch,
        "Py4GWCoreLib.py4gwcorelib_src.BehaviorTree",
        BehaviorTree=SimpleNamespace(NodeState=SimpleNamespace(SUCCESS="success")),
    )
    build_module = _load(monkeypatch, "Py4GWCoreLib.BuildMgr", "Py4GWCoreLib/BuildMgr.py")
    build = object.__new__(build_module.BuildMgr)
    build._custom_skill_data_handler = SimpleNamespace(get_skill=state.metadata.__getitem__)
    build._local_cast_timer = state.timer
    build._cached_data = SimpleNamespace(account_options=SimpleNamespace(Skills=state.skills_enabled))
    build.is_combat_automator_compatible = True
    monkeypatch.setattr(build, "SpiritBuffExists", _false)
    helper = _load(
        monkeypatch, "_restoration_admission_subject", "Py4GWCoreLib/Builds/Skills/ritualist/RestorationMagic.py"
    )
    state.build = build
    state.helper = helper.RestorationMagic(build)
    state.routines = routines
    return state


@pytest.fixture
def light_world(world: _SpiritWorld) -> _SpiritWorld:
    world.equipped_skill_id = LIGHT
    world.place(10, 500.0)
    return world


@pytest.fixture
def pet_world(light_world: _SpiritWorld) -> _SpiritWorld:
    # A separate living pet in the SpiritPet array, with the non-spawned pet classification.
    light_world.spirits.clear()
    light_world.pets.append(20)
    light_world.valid.add(20)
    light_world.health[20] = 1.0
    light_world.place(20, 100.0)
    assert light_world.allegiance(20) == (4, "SpiritPet") and 20 not in light_world.spawned
    assert light_world.is_alive(20)
    return light_world


@pytest.mark.parametrize(
    "distance, expected", [(500.0, True), (1012.0, True), (1012.01, False), (1100.0, False), (1248.0, False)]
)
def test_spirit_range_through_helper_and_shared_admission(world: _SpiritWorld, distance: float, expected: bool) -> None:
    world.place(10, distance)
    assert world.build.CanCastSkillID(TRANSFER) is expected, world
    assert world.build.CanCastSkillSlot(2) is expected, world
    assert bool(_finish(world.helper.Spirit_Transfer())) is expected, world
    assert world.submissions == ([(2, 2, 250)] if expected else []), world


@pytest.mark.parametrize("kind", ["absent", "dead", "unspawned", "invalid"])
def test_invalid_donor_never_admits(world: _SpiritWorld, kind: str) -> None:
    world.place(10, 500.0)
    if kind == "absent":
        world.spirits.clear()
    elif kind == "dead":
        world.dead.add(10)
    elif kind == "unspawned":
        world.spawned.clear()
    else:
        world.valid.remove(10)
    # Historical shared admission accepts living unspawned SpiritPet entries;
    # the stock helper still requires a genuine donor before targeting.
    assert world.build.CanCastSkillID(TRANSFER) is (kind == "unspawned"), (kind, world)
    assert _finish(world.helper.Spirit_Transfer()) is False, (kind, world)
    assert world.submissions == [], world


@pytest.mark.parametrize("skill_id", [TRANSFER, LIGHT], ids=["transfer", "light"])
@pytest.mark.parametrize("hostile", [False, True], ids=["allied", "enemy"])
def test_supplied_spirit_allegiances_are_eligible(world: _SpiritWorld, skill_id: int, hostile: bool) -> None:
    world.equipped_skill_id = skill_id
    world.place(10, 500.0)
    if hostile:
        world.hostile.add(10)
    helper = world.helper.Spirit_Transfer if skill_id == TRANSFER else world.helper.Spirit_Light
    assert _finish(helper()) is True, world
    assert world.submissions == [(2, 2, 250)], world


def test_low_health_nearest_spirit_preserves_availability_policy(world: _SpiritWorld) -> None:
    world.health[10] = 0.001
    world.spirits.append(11)
    world.valid.add(11)
    world.spawned.add(11)
    world.health[11] = 1.0
    world.place(11, 1200.0)
    assert world.routines.Agents.GetNearestSpirit(world.ranges.Spellcast.value) == 10, world
    assert _finish(world.helper.Spirit_Transfer()) is True, world
    assert world.health[10] == 0.001 and world.health[2] == 0.2, "Submission must not simulate completed healing"


def test_invalid_nearer_entries_do_not_hide_a_qualifying_spirit(world: _SpiritWorld) -> None:
    world.spirits.extend([11, 12, 13])
    world.valid.update([11, 12])
    world.spawned.update([12, 13])
    world.dead.add(12)
    for agent_id in (11, 12, 13):
        world.health[agent_id] = 1.0
        world.place(agent_id, 100.0)
    assert world.routines.Agents.GetNearestSpirit(world.ranges.Spellcast.value) == 10, world
    assert _finish(world.helper.Spirit_Transfer()) is True, world


@pytest.mark.parametrize("skill_id", [TRANSFER, LIGHT], ids=["transfer", "light"])
@pytest.mark.parametrize("guard", ["energy", "recharge", "toggle", "pending", "unequipped", "map", "adrenaline"])
def test_existing_cast_guards_still_block(world: _SpiritWorld, skill_id: int, guard: str) -> None:
    world.equipped_skill_id = skill_id
    world.place(10, 500.0)
    if guard == "energy":
        world.energy = 0.1
    elif guard == "recharge":
        world.recharge = 1
    elif guard == "toggle":
        world.skills_enabled[1] = False
    elif guard == "pending":
        world.timer.deadline = 250
    elif guard == "unequipped":
        world.slot = 0
    elif guard == "map":
        world.explorable = False
    else:
        world.adrenaline = False
    helper = world.helper.Spirit_Transfer if skill_id == TRANSFER else world.helper.Spirit_Light
    assert world.build.CanCastSkillID(skill_id) is False, (guard, world)
    assert _finish(helper()) is False, (guard, world)
    assert world.submissions == [], world


@pytest.mark.parametrize("skill_id", [TRANSFER, LIGHT], ids=["transfer", "light"])
def test_extra_condition_and_following_shared_conditions_remain(world: _SpiritWorld, skill_id: int) -> None:
    world.equipped_skill_id = skill_id
    world.place(10, 500.0)
    assert world.build.CanCastSkillID(skill_id, extra_condition=False) is False, world
    conditions = world.metadata[skill_id].Conditions
    conditions.EnemyCount = 1
    world.routines.Agents.GetFilteredEnemyArray = _empty
    assert world.build.CanCastSkillID(skill_id) is False, world


@pytest.mark.parametrize("distance, expected", [(1248.0, True), (1248.01, False)])
def test_recipient_range_is_independent_of_donor_range(world: _SpiritWorld, distance: float, expected: bool) -> None:
    world.place(2, -distance)
    assert bool(_finish(world.helper.Spirit_Transfer())) is expected, world
    assert world.submissions == ([(2, 2, 250)] if expected else []), world


@pytest.mark.parametrize(
    "threshold, health, expected", [(None, 0.49, True), (None, 0.50, False), (0.30, 0.29, True), (0.30, 0.30, False)]
)
def test_recipient_health_thresholds_remain(
    world: _SpiritWorld, threshold: float | None, health: float, expected: bool
) -> None:
    world.health[2] = health
    assert bool(_finish(world.helper.Spirit_Transfer(health_threshold=threshold))) is expected, world


@pytest.mark.parametrize("skill_id", [TRANSFER, LIGHT], ids=["transfer", "light"])
def test_submission_marks_pending_and_prevents_duplicate(world: _SpiritWorld, skill_id: int) -> None:
    world.equipped_skill_id = skill_id
    world.place(10, 500.0)
    helper = world.helper.Spirit_Transfer if skill_id == TRANSFER else world.helper.Spirit_Light
    assert _finish(helper()) is True, world
    assert world.timer.deadline == 250, world
    assert _finish(helper()) is False, world
    assert world.submissions == [(2, 2, 250)], world


def test_donor_is_rechecked_after_target_selection(world: _SpiritWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    resolve = world.build.ResolvePreferredAllyTarget

    def resolve_then_lose_spirit(*args: Any, **kwargs: Any) -> int:
        target: int = resolve(*args, **kwargs)
        world.dead.add(10)
        return target

    monkeypatch.setattr(world.build, "ResolvePreferredAllyTarget", resolve_then_lose_spirit)
    assert _finish(world.helper.Spirit_Transfer()) is False, world
    assert world.submissions == [], world


@pytest.mark.parametrize("skill_id", [LIGHT, OTHER], ids=["spirit_light", "other_flagged_skill"])
@pytest.mark.parametrize("distance, expected", [(1012.0, True), (1100.0, False)])
def test_other_skills_keep_earshot_admission(
    world: _SpiritWorld, skill_id: int, distance: float, expected: bool
) -> None:
    world.place(10, distance)
    assert world.build._meets_custom_skill_shared_conditions(skill_id) is expected, world
    assert world.metadata[TRANSFER].Conditions.RequiresSpiritInEarshot is True
    assert world.metadata[LIGHT].Conditions.RequiresSpiritInEarshot is True


@pytest.mark.parametrize("distance, expected", [(500.0, True), (1012.0, True), (1012.01, False), (1100.0, False)])
def test_spirit_light_earshot_through_helper_and_admission(
    light_world: _SpiritWorld, distance: float, expected: bool
) -> None:
    light_world.place(10, distance)
    assert light_world.build.CanCastSkillID(LIGHT) is expected, light_world
    assert light_world.build.CanCastSkillSlot(2) is expected, light_world
    assert bool(_finish(light_world.helper.Spirit_Light())) is expected, light_world
    assert light_world.submissions == ([(2, 2, 250)] if expected else []), light_world


@pytest.mark.parametrize("kind", ["absent", "dead", "unspawned", "invalid"])
def test_stock_spirit_light_restores_unspawned_admission(light_world: _SpiritWorld, kind: str) -> None:
    if kind == "absent":
        light_world.spirits.clear()
    elif kind == "dead":
        light_world.dead.add(10)
    elif kind == "unspawned":
        light_world.spawned.clear()
    else:
        light_world.valid.remove(10)
    expected = kind == "unspawned"
    assert light_world.build.CanCastSkillID(LIGHT) is expected, (kind, light_world)
    assert _finish(light_world.helper.Spirit_Light()) is expected, (kind, light_world)
    assert light_world.submissions == ([(2, 2, 250)] if expected else []), light_world


@pytest.mark.parametrize("skill_id", [TRANSFER, LIGHT], ids=["transfer", "light"])
def test_pet_only_stock_admission_and_helper_behavior(pet_world: _SpiritWorld, skill_id: int) -> None:
    pet_world.equipped_skill_id = skill_id
    helper = pet_world.helper.Spirit_Transfer if skill_id == TRANSFER else pet_world.helper.Spirit_Light
    assert pet_world.routines.Agents.GetNearestSpirit(pet_world.ranges.Earshot.value) == 0, pet_world
    assert pet_world.health[1] > pet_world.metadata[LIGHT].Conditions.SacrificeHealth, pet_world
    assert pet_world.build.CanCastSkillID(skill_id) is True, pet_world
    assert pet_world.build.CanCastSkillSlot(2) is True, pet_world
    assert _finish(helper()) is (skill_id == LIGHT), pet_world
    assert pet_world.submissions == ([(2, 2, 250)] if skill_id == LIGHT else []), pet_world


def test_pet_does_not_hide_qualifying_spirit(pet_world: _SpiritWorld) -> None:
    pet_world.spirits.append(10)
    assert pet_world.routines.Agents.GetNearestSpirit(pet_world.ranges.Earshot.value) == 10, pet_world
    assert _finish(pet_world.helper.Spirit_Light()) is True, pet_world
    assert pet_world.submissions == [(2, 2, 250)], pet_world


def test_unrelated_spirit_gate_keeps_pet_behavior_without_extra_scan(
    pet_world: _SpiritWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_scan(*args: Any, **kwargs: Any) -> int:
        raise AssertionError("Unrelated spirit-gated skills must retain their existing observation path")

    monkeypatch.setattr(pet_world.routines.Agents, "GetNearestSpirit", unexpected_scan)
    assert pet_world.build._meets_custom_skill_shared_conditions(OTHER) is True, pet_world


def test_spirit_light_keeps_spirit_supported_self_healing(light_world: _SpiritWorld) -> None:
    light_world.health[1] = 0.1
    assert _finish(light_world.helper.Spirit_Light(health_threshold=0.30)) is True, light_world
    assert light_world.submissions == [(2, 1, 250)], light_world
    assert light_world.health[1] == 0.1, "Submission must not simulate completed healing"


@pytest.mark.parametrize(
    "threshold, health, expected",
    [
        (None, 0.59, True),
        (None, 0.60, False),
        (0.30, 0.29, True),
        (0.30, 0.30, False),
        (0.60, 0.59, True),
        (0.60, 0.60, False),
    ],
)
def test_spirit_light_recipient_thresholds_remain(
    light_world: _SpiritWorld, threshold: float | None, health: float, expected: bool
) -> None:
    light_world.health[2] = health
    assert bool(_finish(light_world.helper.Spirit_Light(health_threshold=threshold))) is expected, light_world
    assert light_world.submissions == ([(2, 2, 250)] if expected else []), light_world
