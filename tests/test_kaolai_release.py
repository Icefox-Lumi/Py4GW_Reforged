"""Offline release-admission tests; no claim about native ash identity or healing."""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar

import pytest

ROOT = Path(__file__).resolve().parents[1]
_Function = TypeVar("_Function", bound=Callable[..., Any])


def _frame_cache(**_: Any) -> Callable[[_Function], _Function]:
    def decorate(function: _Function) -> _Function:
        return function

    return decorate


def _login_agent_id(login: int) -> int:
    return login


def _skill_id(name: str) -> int:
    return 1219 if name == "Protective_Was_Kaolai" else 1


def _is_equipped(skill_id: int) -> bool:
    return skill_id == 1219


class _Range(Enum):
    Spirit = 2500.0
    Earshot = 1012.0


@dataclass
class _Timer:
    now: int = 0
    deadline: int | None = None
    delay: int = 0

    def IsStopped(self) -> bool:
        return self.deadline is None

    def IsExpired(self) -> bool:
        return self.deadline is not None and self.now >= self.deadline

    def Stop(self) -> None:
        self.deadline = None

    def SetThrottleTime(self, delay: int) -> None:
        self.delay = delay

    def Reset(self) -> None:
        self.deadline = self.now + self.delay


@dataclass
class _World:
    allies: list[int] = field(default_factory=lambda: [1, 2, 3, 4])
    players: list[Any] = field(
        default_factory=lambda: [SimpleNamespace(login_number=i, is_connected=True) for i in range(1, 5)]
    )
    heroes: list[Any] = field(default_factory=list[Any])
    henchmen: list[Any] = field(default_factory=list[Any])
    valid: set[int] = field(default_factory=lambda: {1, 2, 3, 4})
    health: dict[int, float] = field(default_factory=lambda: dict.fromkeys(range(1, 5), 0.5))
    dead: set[int] = field(default_factory=set[int])
    positions: dict[int, tuple[float, float]] = field(default_factory=dict[int, tuple[float, float]])
    origin: tuple[float, float] = (0.0, 0.0)
    accounts: list[Any] = field(default_factory=list[Any])
    remote_now: int = 10000
    party_loaded: bool = True
    holding: bool = True
    button_present: bool = True
    button_usable: bool = True
    can_cast: bool = True
    clicks: int = 0
    frame_requests: list[tuple[int, list[int]]] = field(default_factory=list[tuple[int, list[int]]])
    timer: _Timer = field(default_factory=_Timer)
    helper: Any = None
    generic: Any = None

    def is_holding(self, agent_id: int) -> bool:
        return self.holding

    def is_valid(self, agent_id: int) -> bool:
        return agent_id in self.valid

    def is_dead(self, agent_id: int) -> bool:
        return agent_id in self.dead

    def get_health(self, agent_id: int) -> float:
        return self.health.get(agent_id, 0.0)

    def position(self, agent_id: int) -> tuple[float, float]:
        return self.positions.get(agent_id, self.origin)

    def click(self) -> None:
        self.clicks += 1
        # Deliberately leave holding/health unchanged: submission proves neither.

    def frames(self, anchor: int, path: list[int]) -> list[Any]:
        self.frame_requests.append((anchor, path))
        if not self.button_present:
            return []
        return [SimpleNamespace(is_usable=self.button_usable, click=self.click)]


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


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    state = _World()
    ranges = _Range
    player = SimpleNamespace(GetAgentID=lambda: 1, GetXY=lambda: state.origin)
    party = SimpleNamespace(
        IsPartyLoaded=lambda: state.party_loaded,
        GetPlayers=lambda: state.players,
        GetHeroes=lambda: state.heroes,
        GetHenchmen=lambda: state.henchmen,
        GetPartyID=lambda: 7,
        Players=SimpleNamespace(GetAgentIDByLoginNumber=_login_agent_id),
    )
    agent = SimpleNamespace(
        IsHoldingItem=state.is_holding,
        IsValid=state.is_valid,
        IsDead=state.is_dead,
        GetHealth=state.get_health,
        GetLoginNumber=_login_agent_id,
        GetXY=state.position,
        DEAD_HEALTH_EPSILON=0.0001,
    )
    core = _module(
        monkeypatch,
        "Py4GWCoreLib",
        Range=ranges,
        Player=player,
        Party=party,
        Agent=agent,
        AgentArray=SimpleNamespace(GetAllyArray=lambda: state.allies),
        Profession=SimpleNamespace(Necromancer=4, Ritualist=8),
        Routines=SimpleNamespace(),
    )
    core.__path__ = []
    _module(monkeypatch, "PySystem")
    _module(monkeypatch, "Py4GWCoreLib.Player", Player=player)
    _module(monkeypatch, "Py4GWCoreLib.Agent", Agent=agent)
    _module(monkeypatch, "Py4GWCoreLib.Party", Party=party)
    _module(monkeypatch, "Py4GWCoreLib.FrameTree", FrameTree=SimpleNamespace(frames_at_path=state.frames))
    _module(monkeypatch, "Py4GWCoreLib.enums_src").__path__ = []
    _module(monkeypatch, "Py4GWCoreLib.enums_src.GameData_enums", Range=ranges, Allegiance=object)
    _module(monkeypatch, "PyAgent")
    _module(monkeypatch, "Py4GWCoreLib.Py4GWcorelib", Utils=SimpleNamespace(Distance=math.dist))
    _module(monkeypatch, "Py4GWCoreLib.Context", GWContext=SimpleNamespace())
    _module(monkeypatch, "Py4GWCoreLib.native_src.context.AgentContext", AgentStruct=object)
    arrays = _load(monkeypatch, "Py4GWCoreLib.AgentArray", "Py4GWCoreLib/AgentArray.py")
    monkeypatch.setattr(arrays.AgentArray, "GetAllyArray", staticmethod(lambda: state.allies))
    core.__dict__["AgentArray"] = arrays.AgentArray
    _module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src").__path__ = []
    _module(
        monkeypatch,
        "Py4GWCoreLib.py4gwcorelib_src.FrameCache",
        frame_cache=_frame_cache,
    )
    _module(monkeypatch, "Py4GWCoreLib.routines_src").__path__ = []
    map_module = _module(
        monkeypatch,
        "Py4GWCoreLib.Map",
        Map=SimpleNamespace(
            IsMapReady=lambda: True,
            GetMapID=lambda: 10,
            GetRegion=lambda: (1,),
            GetDistrict=lambda: 1,
            GetLanguage=lambda: (0,),
        ),
    )
    core.__dict__["Map"] = map_module.__dict__["Map"]

    def publications(*, sort_results: bool = True) -> list[Any]:
        return state.accounts

    _module(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache",
        GLOBAL_CACHE=SimpleNamespace(ShMem=SimpleNamespace(GetAllAccountData=publications)),
    )
    clock = _load(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync",
        "Py4GWCoreLib/GlobalCache/shared_memory_src/IntentSync.py",
    )
    monkeypatch.setattr(clock, "get_uncached_tick_count64", lambda: state.remote_now)
    checks = _load(monkeypatch, "Py4GWCoreLib.routines_src.Checks", "Py4GWCoreLib/routines_src/Checks.py")
    core.Routines.Checks = checks.Checks
    checks.Checks.Skills.CanCast = staticmethod(lambda: state.can_cast)
    build_module = _load(monkeypatch, "Py4GWCoreLib.BuildMgr", "Py4GWCoreLib/BuildMgr.py")
    core.__dict__["BuildMgr"] = build_module.BuildMgr
    build_type: type[Any] = build_module.BuildMgr
    build = object.__new__(build_type)
    build._local_cast_timer = state.timer
    subject = _load(monkeypatch, "_kaolai_release_subject", "Py4GWCoreLib/Builds/Skills/ritualist/NoAttribute.py")
    state.generic = subject.NoAttribute(build)
    smart = _load(monkeypatch, "_smart_kaolai_subject", "Py4GWCoreLib/Builds/Skills/SmartKaolai.py")
    state.helper = smart.SmartKaolai(build, SimpleNamespace())
    return state


def _finish(coroutine: Generator[Any, None, Any]) -> Any:
    while True:
        try:
            next(coroutine)
        except StopIteration as result:
            return result.value


def _release(world: _World) -> bool:
    return bool(_finish(world.helper.Drop_Held_Bundle(health_threshold=0.75)))


@pytest.mark.parametrize(
    "case,injured,critical,dead,outside,missing,routine",
    [
        ("four", 4, 0, 0, 0, 0, True),
        ("two_critical", 2, 2, 0, 0, 0, False),
        ("three_critical", 3, 3, 0, 0, 0, False),
        ("dead_fourth", 3, 0, 1, 0, 0, False),
        ("outside_fourth", 3, 0, 0, 1, 0, False),
        ("boundary_range", 4, 0, 0, 0, 0, True),
        ("boundary_health", 3, 0, 0, 0, 0, False),
        ("missing_ally", 3, 0, 0, 0, 1, False),
        ("duplicates", 4, 0, 0, 0, 0, True),
        ("pending", 4, 0, 0, 0, 0, False),
        ("busy", 4, 0, 0, 0, 0, False),
        ("no_button", 4, 0, 0, 0, 0, False),
    ],
)
def test_observation_census_matches_existing_admission(
    world: _World, case: str, injured: int, critical: int, dead: int, outside: int, missing: int, routine: bool
) -> None:
    if case in {"two_critical", "three_critical"}:
        count = 2 if case == "two_critical" else 3
        world.health = {aid: 0.1 if aid <= count else 1.0 for aid in range(1, 5)}
    elif case == "dead_fourth":
        world.dead.add(4)
    elif case == "outside_fourth":
        world.positions[4] = (2500.001, 0)
    elif case == "boundary_range":
        world.positions[4] = (2500, 0)
    elif case == "boundary_health":
        world.health[4] = 0.75
    elif case == "missing_ally":
        world.allies.remove(4)
    elif case == "duplicates":
        world.allies.extend([1, 1, 2])
        world.players.append(world.players[0])
    elif case == "pending":
        world.timer.deadline = 250
    elif case == "no_button":
        world.button_present = False
    before_timer = vars(world.timer).copy()
    observed = world.helper.observe(pending=case == "pending", busy=case == "busy")
    assert (
        observed.injured,
        observed.critical,
        observed.dead,
        observed.outside,
        observed.missing,
        observed.routine,
    ) == (injured, critical, dead, outside, missing, routine), (case, observed)
    assert vars(world.timer) == before_timer and world.clicks == 0, (case, world)
    # Busy is an outer rotation gate; the release helper has only a pending gate.
    assert _release(world) == (routine or case == "busy"), (case, observed, world)


@pytest.mark.parametrize("case", ["death", "unloaded", "invalid", "oversized_roster"])
def test_observation_refuses_incomplete_context(world: _World, case: str) -> None:
    if case == "death":
        world.dead.add(1)
    elif case == "unloaded":
        world.party_loaded = False
    elif case == "invalid":
        world.valid.remove(1)
    else:
        world.players *= 17
    observed = world.helper.observe(pending=False, busy=False)
    assert not observed.complete and not observed.routine, (case, observed)
    if case != "oversized_roster":
        assert observed.held is None, (case, observed)
    assert not world.frame_requests and not world.clicks


def _kaolai_capture(world: _World) -> Any:
    capture = sys.modules["_smart_kaolai_subject"].KaolaiCapture()
    capture.observe(world.helper.observe(pending=False, busy=False), 0.0)
    capture.event("click_call_returned", 0.0)
    return capture


@pytest.mark.parametrize("held", [True, False])
def test_held_state_and_hp_rise_are_separate_unattributed_observations(world: _World, held: bool) -> None:
    capture = _kaolai_capture(world)
    world.holding = held
    capture.observe(world.helper.observe(pending=False, busy=False), 0.25)
    # Healing may become visible after a held-state change.
    world.health[2] = 0.9
    capture.observe(world.helper.observe(pending=False, busy=False), 0.5)
    capture.advance(2.0)
    assert capture.watch is None
    assert capture.counts["generic_held_cleared"] == int(not held)
    assert capture.counts["no_change_observed"] == int(held)
    assert capture.counts["hp_fraction_rises_unattributed"] == 1
    summary = capture.summary()
    assert "identity:unknown" in summary and "heal_receipt:unavailable" in summary
    assert "click_receipt:unavailable" in summary and "confirmed" not in summary
    assert world.clicks == 0, "Observation must never produce actions."


@pytest.mark.parametrize("ending", ["gap", "late_clear", "death", "unloaded", "stop"])
def test_release_watch_inconclusive_endings(world: _World, ending: str) -> None:
    capture = _kaolai_capture(world)
    if ending == "stop":
        capture.end("inconclusive_capture_ended")
    elif ending in {"gap", "late_clear"}:
        capture.advance(2.0)
        if ending == "late_clear":
            world.holding = False
            capture.observe(world.helper.observe(pending=False, busy=False), 2.1)
    else:
        world.holding = False
        if ending == "death":
            world.dead.add(1)
        else:
            world.party_loaded = False
        capture.observe(world.helper.observe(pending=False, busy=False), 0.5)
    assert capture.watch is None and not capture.counts["generic_held_cleared"], (ending, capture.counts)
    assert sum(value for key, value in capture.counts.items() if key.startswith("inconclusive_")) == 1


def test_release_watch_bounds_and_repeated_calls_do_not_extend_deadline(world: _World) -> None:
    capture = _kaolai_capture(world)
    for index in range(1, 100):
        capture.event("click_call_returned", index / 100)
    assert capture.watch.started == 0 and capture.counts["windows"] == 1
    capture.advance(2.0)
    for now in range(2, 20, 2):
        capture.event("click_call_returned", float(now))
        capture.advance(now + 2.0)
    assert capture.watch is None and capture.counts["windows"] == 4
    assert capture.counts["overlapping_calls"] == 99
    assert capture.counts["window_budget_exhausted"] == 6


@pytest.mark.parametrize("bundle", ["unknown", "other_ashes", "quest_bundle"])
def test_generic_detector_never_promotes_bundle_identity(world: _World, bundle: str) -> None:
    # The supported detector exposes the same boolean for all these inputs.
    world.holding = True
    capture = _kaolai_capture(world)
    assert capture.last.held is True and "identity:unknown" in capture.summary(), bundle
    assert _release(world) is True, "Diagnostics must not silently change the existing generic-bundle policy."


def test_four_players_include_caster_once_and_preserve_button_route(world: _World) -> None:
    world.allies.extend([1, 1, 2])
    world.players.append(world.players[0])
    assert _release(world) is True, world
    assert (world.clicks, world.frame_requests, world.timer.delay) == (1, [(5040781, [0, 0])], 250)
    assert world.holding and world.health[1] == 0.5, "Submission must not claim release/healing."


def test_three_distinct_members_do_not_become_four_through_duplicates(world: _World) -> None:
    world.allies = [1, 1, 2, 2, 3, 3]
    assert _release(world) is False, world
    assert world.clicks == 0


def test_current_roster_includes_ordinary_and_mercenary_heroes_and_henchmen(world: _World) -> None:
    world.players = world.players[:1]
    world.heroes = [SimpleNamespace(agent_id=2, hero_id=3), SimpleNamespace(agent_id=3, hero_id=28)]
    world.henchmen = [SimpleNamespace(agent_id=4)]
    assert _release(world) is True, world


@pytest.mark.parametrize("excluded", ["nonparty", "disconnected", "dead", "invalid", "unavailable"])
def test_unqualified_fourth_recipient_cannot_trigger_release(world: _World, excluded: str) -> None:
    if excluded == "nonparty":
        world.players.pop()
    elif excluded == "disconnected":
        world.players[-1].is_connected = False
    elif excluded == "dead":
        world.dead.add(4)
    elif excluded == "invalid":
        world.valid.remove(4)
    else:
        world.health.pop(4)
    assert _release(world) is False, (excluded, world)
    assert world.clicks == 0


@pytest.mark.parametrize("health", [0.75, 1.0, 0.0, -0.1, float("nan"), float("inf")])
def test_invalid_or_not_strictly_injured_health_is_excluded(world: _World, health: float) -> None:
    world.health[4] = health
    assert _release(world) is False, (health, world)


def test_health_just_below_threshold_qualifies(world: _World) -> None:
    world.health[4] = 0.749999
    assert _release(world) is True, world


@pytest.mark.parametrize("injured", [1, 2])
def test_no_new_single_or_two_critical_recipient_policy(world: _World, injured: int) -> None:
    world.health = {agent: 0.01 if agent <= injured else 1.0 for agent in range(1, 5)}
    assert _release(world) is False, (injured, world)
    assert world.clicks == 0


@pytest.mark.parametrize("distance, expected", [(2500.0, True), (2500.1, False), (3000.0, False), (5021.0, False)])
def test_range_remains_conservative_until_ash_identity_is_proven(
    world: _World, distance: float, expected: bool
) -> None:
    world.origin = (10000.0, -2000.0)
    world.positions[4] = (10000.0 + distance, -2000.0)
    assert _release(world) is expected, (distance, expected, world)


def test_caster_missing_from_old_population_is_not_added_while_identity_is_unknown(world: _World) -> None:
    world.allies = [2, 3, 4]
    assert _release(world) is False, world


@pytest.mark.parametrize("unavailable", ["party", "holding", "button", "button_usable"])
def test_unavailable_admission_evidence_prevents_click(world: _World, unavailable: str) -> None:
    if unavailable == "party":
        world.party_loaded = False
    elif unavailable == "holding":
        world.holding = False
    elif unavailable == "button":
        world.button_present = False
    else:
        world.button_usable = False
    assert _release(world) is False, (unavailable, world)
    assert world.clicks == 0 and world.timer.IsStopped()


def test_pending_blocks_second_attempt_then_allows_retry_after_expiry(world: _World) -> None:
    assert _release(world) is True
    world.timer.now = 249
    assert _release(world) is False
    assert world.clicks == 1
    world.timer.now = 250
    assert _release(world) is True
    assert world.clicks == 2 and world.holding, "A retry is allowed; a previous click did not prove release."


def test_preexisting_cast_pending_blocks_release(world: _World) -> None:
    world.helper.build._mark_local_cast_pending(250)
    assert _release(world) is False
    assert world.frame_requests == []


@pytest.mark.parametrize(
    "shared_health, shared_dead, expected", [(0.5, False, True), (1.0, False, False), (0.5, True, False)]
)
def test_real_health_helpers_use_same_party_remote_evidence(
    world: _World, shared_health: float, shared_dead: bool, expected: bool
) -> None:
    world.health[4] = 1.0 if shared_health < 0.75 else 0.5
    world.accounts = [
        SimpleNamespace(
            IsSlotActive=True,
            AgentPartyData=SimpleNamespace(PartyID=7),
            AgentData=SimpleNamespace(
                AgentID=4,
                Map=SimpleNamespace(MapID=10, Region=1, District=1, Language=0),
                Health=SimpleNamespace(Current=shared_health),
                Is_Dead=shared_dead,
                Is_DeadByTypeMap=False,
            ),
        )
    ]
    assert _release(world) is expected, (shared_health, shared_dead, world)


def test_release_needs_no_casting_energy_recharge_or_unproven_effect_api(world: _World) -> None:
    # None of these APIs exists in the fixture. Any new lookup fails this test.
    # Generic holding is intentionally not represented as proven Kaolai identity.
    assert _release(world) is True


@pytest.mark.parametrize("build_name", ["Blood is Power Healer", "Xinraes Weapon Healer"])
@pytest.mark.parametrize("preemption", [None, "Spirit_Transfer", "Spirit_Light", "Mend_Body_and_Soul", "cannot_cast"])
def test_real_callers_preserve_emergency_precedence_and_release_contract(
    world: _World, monkeypatch: pytest.MonkeyPatch, build_name: str, preemption: str | None
) -> None:
    _module(monkeypatch, "Py4GWCoreLib.Builds").__path__ = []
    _module(monkeypatch, "Py4GWCoreLib.Builds.Any").__path__ = []
    _module(monkeypatch, "Py4GWCoreLib.Builds.Any.HeroAI", HeroAI_Build=object)
    _module(monkeypatch, "Py4GWCoreLib.Builds.Skills", SkillsTemplate=object)
    _module(monkeypatch, "Py4GWCoreLib.Skill", Skill=SimpleNamespace(GetID=_skill_id))
    module = _load(monkeypatch, "_kaolai_caller", f"Py4GWCoreLib/Builds/Necromancer/N_Rt/{build_name}.py")
    caller_type: type[Any] = (
        module.Blood_is_Power_Healer if build_name.startswith("Blood") else module.Xinraes_Weapon_Healer
    )
    caller = object.__new__(caller_type)
    events: list[tuple[str, dict[str, Any]]] = []

    def attempt(name: str, **kwargs: Any) -> Generator[None, None, bool]:
        events.append((name, kwargs))
        if name == "drop":
            release: Generator[None, None, bool] = world.generic.Drop_Held_Bundle(**kwargs)
            return (yield from release)
        return name == preemption

    caller.IsSkillEquipped = _is_equipped
    caller.skills = SimpleNamespace(
        Ritualist=SimpleNamespace(
            RestorationMagic=SimpleNamespace(
                Spirit_Transfer=partial(attempt, "Spirit_Transfer"),
                Spirit_Light=partial(attempt, "Spirit_Light"),
                Mend_Body_and_Soul=partial(attempt, "Mend_Body_and_Soul"),
            ),
            NoAttribute=SimpleNamespace(Drop_Held_Bundle=partial(attempt, "drop")),
        )
    )
    world.can_cast = preemption != "cannot_cast"
    result = _finish(caller._run_local_skill_logic())
    expected_order = ["Spirit_Transfer", "Spirit_Light", "Mend_Body_and_Soul", "drop"]
    if preemption == "cannot_cast":
        assert result is False and events == [] and world.clicks == 0
    elif preemption is not None:
        assert result is True and world.clicks == 0
        assert [name for name, _ in events] == expected_order[: expected_order.index(preemption) + 1]
    else:
        assert result is True and world.clicks == 1
        assert events == [
            ("Spirit_Transfer", {"health_threshold": 0.30}),
            ("Spirit_Light", {"health_threshold": 0.30}),
            ("Mend_Body_and_Soul", {"health_threshold": 0.40}),
            ("drop", {"health_threshold": 0.75}),
        ], (build_name, events)


@pytest.mark.parametrize("agent_id", [0, -1, 999])
def test_smart_rejects_nonpositive_and_invalid_roster_ids(world: _World, agent_id: int) -> None:
    world.allies[-1] = agent_id
    world.players[-1].login_number = agent_id
    world.health[agent_id] = 0.5
    assert _release(world) is False, (agent_id, world)


@pytest.mark.parametrize(
    "change", ["duplicates", "nonparty", "disconnected", "invalid", "zero", "negative", "party", "pending"]
)
def test_stock_intentionally_loses_later_admission_safeguards(world: _World, change: str) -> None:
    if change == "duplicates":
        world.allies = [1, 1, 2, 3]
    elif change == "nonparty":
        world.players.pop()
    elif change == "disconnected":
        world.players[-1].is_connected = False
    elif change == "invalid":
        world.valid.remove(4)
    elif change in ("zero", "negative"):
        agent_id = 0 if change == "zero" else -1
        world.allies[-1] = agent_id
        world.players[-1].login_number = agent_id
        world.health[agent_id] = 0.5
    elif change == "party":
        world.party_loaded = False
    else:
        world.generic.build._mark_local_cast_pending(250)
    assert _release(world) is False, (change, world)
    assert _finish(world.generic.Drop_Held_Bundle(health_threshold=0.75)) is True, (change, world)
    assert world.clicks == 1 and world.timer.delay == 250


@pytest.mark.parametrize("boundary, expected", [(0.749999, True), (0.75, False), (0.0, False), (-0.1, False)])
def test_stock_retains_shared_liveness_and_strict_upper_health_boundary(
    world: _World, boundary: float, expected: bool
) -> None:
    world.health[4] = boundary
    assert _finish(world.generic.Drop_Held_Bundle(health_threshold=0.75)) is expected, world


@pytest.mark.parametrize("unavailable", ["holding", "button", "button_usable", "dead", "distance"])
def test_stock_retains_original_release_requirements(world: _World, unavailable: str) -> None:
    if unavailable == "holding":
        world.holding = False
    elif unavailable == "button":
        world.button_present = False
    elif unavailable == "button_usable":
        world.button_usable = False
    elif unavailable == "dead":
        world.dead.add(4)
    else:
        world.positions[4] = (2500.1, 0.0)
    assert _finish(world.generic.Drop_Held_Bundle(health_threshold=0.75)) is False, (unavailable, world)
    assert world.clicks == 0 and world.timer.IsStopped()


def test_stock_stamps_before_yield_but_does_not_itself_suppress_retries(world: _World) -> None:
    world.positions[4] = (2500.0, 0.0)
    pending = world.generic.Drop_Held_Bundle(health_threshold=0.75)
    assert next(pending) is None
    assert world.clicks == 1 and world.timer.deadline == 250
    assert _finish(pending) is True
    assert _finish(world.generic.Drop_Held_Bundle(health_threshold=0.75)) is True
    assert world.clicks == 2 and world.holding


def _emergency(world: _World, *, after_targeted_heals: bool = False) -> bool:
    return bool(_finish(world.helper.Drop_Emergency_Bundle(after_targeted_heals=after_targeted_heals)))


def _injuries(world: _World, health: tuple[float, ...]) -> None:
    world.health = dict.fromkeys(range(1, 5), 1.0)
    world.health.update(dict(zip((2, 3, 4), health)))


@pytest.mark.parametrize(
    "health,expected",
    [
        ((0.28, 0.34, 0.37), True),
        ((0.30, 0.34), True),
        ((0.35, 0.35), True),
        ((0.3501, 0.35), False),
        ((0.39, 0.39), False),
        ((0.399, 0.399, 0.399), True),
        ((0.40, 0.40, 0.40), False),
        ((0.50, 0.55, 0.60), False),
        ((0.09,), False),
        ((0.09, 0.35), False),
        ((0.20, 0.35), True),
        ((0.1999, 0.35), False),
        ((0, 0.3), False),
        ((-0.1, 0.3), False),
        ((math.nan, 0.3), False),
        ((math.inf, 0.3), False),
    ],
)
def test_emergency_injury_burden_and_rescue_boundaries(
    world: _World, health: tuple[float, ...], expected: bool
) -> None:
    _injuries(world, health)
    assert _emergency(world) is expected, (health, world.clicks)
    assert world.clicks == int(expected)
    assert world.timer.deadline == (250 if expected else None)
    assert world.holding and (world.health[2] == health[0] or math.isnan(health[0]))


def test_failed_targeted_rescue_allows_critical_group_but_never_a_single_recipient(world: _World) -> None:
    _injuries(world, (0.09, 0.30))
    assert not _emergency(world) and not world.clicks
    assert _emergency(world, after_targeted_heals=True)
    world.timer.Stop()
    _injuries(world, (0.09,))
    assert not _emergency(world, after_targeted_heals=True) and world.clicks == 1


@pytest.mark.parametrize("kind", ["dead", "invalid", "zero", "disconnected", "outside", "npc", "duplicate"])
def test_emergency_counts_only_distinct_eligible_living_party(world: _World, kind: str) -> None:
    _injuries(world, (0.28, 0.30))
    if kind == "dead":
        world.dead.add(3)
    elif kind == "invalid":
        world.valid.remove(3)
    elif kind == "zero":
        world.players[2].login_number = 0
        world.allies.append(0)
        world.valid.add(0)
        world.health[0] = 0.2
    elif kind == "disconnected":
        world.players[2].is_connected = False
    elif kind == "outside":
        world.positions[3] = (2500.01, 0)
    elif kind == "npc":
        world.players = [member for member in world.players if member.login_number != 3]
    else:
        world.health[3] = 1.0
        world.players += [world.players[1]] * 3
        world.allies += [2] * 3
    assert not _emergency(world), (kind, world)
    assert world.clicks == 0


def test_emergency_keeps_inclusive_range_and_roster_hero_henchman_support(world: _World) -> None:
    _injuries(world, (0.28, 0.34))
    world.players = world.players[:1]
    world.heroes = [SimpleNamespace(agent_id=2)]
    world.henchmen = [SimpleNamespace(agent_id=3)]
    world.positions[3] = (2500, 0)
    assert _emergency(world)
    assert world.frame_requests == [(5040781, [0, 0])]


@pytest.mark.parametrize("rank,maximum", [(None, 0), (0, 280), (8, 500), (12, 1000), (16, 500), ((12, 16), 500)])
def test_emergency_heuristic_does_not_invent_healing_from_rank_or_maximum(
    world: _World, monkeypatch: pytest.MonkeyPatch, rank: Any, maximum: int
) -> None:
    _injuries(world, (0.28, 0.34))
    agent = sys.modules["Py4GWCoreLib.Agent"].__dict__["Agent"]

    def forbidden(*_args: Any) -> Any:
        pytest.fail(f"Severity heuristic must not infer healing: rank={rank}, max_health={maximum}")

    for name in ("GetAttributes", "GetMaxHealth", "GetWeaponExtraData"):
        monkeypatch.setattr(agent, name, forbidden, raising=False)
    _module(monkeypatch, "PyEffects", PyEffects=forbidden)
    _module(monkeypatch, "PyItem", Item=forbidden)
    _module(monkeypatch, "PyGameThread", enqueue=forbidden)
    assert _emergency(world)
    assert world.clicks == 1


def _publication(agent: int, health: float, *, stamp: int = 9999) -> Any:
    return SimpleNamespace(
        IsSlotActive=True,
        IsAccount=True,
        LastUpdated=stamp,
        AgentPartyData=SimpleNamespace(PartyID=7),
        AgentData=SimpleNamespace(
            AgentID=agent,
            LoginNumber=agent,
            Map=SimpleNamespace(MapID=10, Region=1, District=1, Language=0),
            Health=SimpleNamespace(Current=health),
            Is_Dead=False,
            Is_DeadByTypeMap=False,
        ),
    )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("fresh", True),
        ("249ms", True),
        ("250ms", False),
        ("stale", False),
        ("future", False),
        ("wrap", True),
        ("duplicate", False),
        ("login", False),
        ("map", False),
        ("party", False),
        ("inactive", False),
        ("nonplayer", False),
        ("dead", False),
        ("type_dead", False),
        ("nan", False),
        ("missing", False),
    ],
)
def test_emergency_remote_publication_freshness_and_identity(world: _World, case: str, expected: bool) -> None:
    _injuries(world, (1.0, 0.30))
    row = _publication(2, 0.28)
    world.accounts = [row]
    if case in {"249ms", "250ms", "stale", "future", "wrap"}:
        row.LastUpdated = {"249ms": 9751, "250ms": 9750, "stale": 6000, "future": 10001, "wrap": 0xFFFFFFF0}[case]
        if case == "wrap":
            world.remote_now = 0x100000010
    elif case == "duplicate":
        world.accounts.append(_publication(2, 0.29))
    elif case == "login":
        row.AgentData.LoginNumber = 22
    elif case == "map":
        row.AgentData.Map.MapID = 11
    elif case == "party":
        row.AgentPartyData.PartyID = 8
    elif case == "inactive":
        row.IsSlotActive = False
    elif case == "nonplayer":
        row.IsAccount = False
    elif case == "dead":
        row.AgentData.Is_Dead = True
    elif case == "type_dead":
        row.AgentData.Is_DeadByTypeMap = True
    elif case == "nan":
        row.AgentData.Health.Current = math.nan
    elif case == "missing":
        del row.LastUpdated
    assert _emergency(world) is expected, (case, world.accounts)
    assert world.clicks == int(expected)


def test_emergency_rejects_publication_changed_while_copying(world: _World) -> None:
    _injuries(world, (1.0, 0.30))
    row = _publication(2, 0.28)

    class ChangingHealth:
        @property
        def Current(self) -> float:
            row.LastUpdated += 1
            return 0.28

    row.AgentData.Health = ChangingHealth()
    world.accounts = [row]
    assert not _emergency(world) and not world.clicks


def test_uncertain_emergency_evidence_does_not_gate_four_person_routine(world: _World) -> None:
    world.accounts = [_publication(2, 0.28, stamp=6000)]
    world.health[3] = 0.30
    assert not _emergency(world)
    assert _release(world)
    assert world.clicks == 1


@pytest.mark.parametrize("gate", ["pending", "not_held", "party", "healthy", "routine_mild"])
def test_emergency_skips_extra_publication_scan_without_candidate(
    world: _World, monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    _injuries(world, (0.28, 0.34))
    if gate == "pending":
        world.helper.build._mark_local_cast_pending(250)
    elif gate == "not_held":
        world.holding = False
    elif gate == "party":
        world.party_loaded = False
    elif gate == "healthy":
        world.health = dict.fromkeys(range(1, 5), 1.0)
    else:
        world.health.update(dict(zip((1, 2, 3, 4), (0.60, 0.65, 0.70, 0.74))))

    def forbidden(_recipients: Any) -> Any:
        pytest.fail(f"No emergency candidate should read publications: {gate}")

    monkeypatch.setattr(world.helper, "_emergency_health", forbidden)
    assert not _emergency(world) and not world.clicks


def test_emergency_stamps_before_yield_and_closing_does_not_revoke_submission(world: _World) -> None:
    _injuries(world, (0.28, 0.34))
    work = world.helper.Drop_Emergency_Bundle()
    assert next(work) is None
    assert world.clicks == 1 and world.timer.deadline == 250
    work.close()
    assert not _emergency(world) and world.clicks == 1
    world.timer.now = 249
    assert not _emergency(world)
    world.timer.now = 250
    assert _emergency(world) and world.clicks == 2


@pytest.mark.parametrize(
    "health,early,after_rescue",
    [
        ((0.28, 0.34, 0.37, 0.95), True, True),
        ((0.28, 0.34, 0.37, 0.74), True, True),
        ((0.35, 0.35, 0.74, 0.74), True, True),
        ((0.3501, 0.35, 0.74, 0.74), False, False),
        ((0.39, 0.39, 0.39, 0.39), True, True),
        ((0.60, 0.65, 0.70, 0.74), False, False),
        ((0.19, 0.30, 0.74, 0.74), False, True),
        ((0.10, 0.74, 0.74, 0.74), False, False),
        ((0.40, 0.40, 0.40, 0.40), False, False),
        ((0.20, 0.35, 0.74, 0.74), True, True),
    ],
)
def test_four_person_emergency_priority_boundaries(
    world: _World, health: tuple[float, ...], early: bool, after_rescue: bool
) -> None:
    world.health.update(dict(zip((1, 2, 3, 4), health)))
    assert _emergency(world) is early, (health, "before rescue")
    assert world.clicks == int(early)
    world.timer.Stop()
    assert _emergency(world, after_targeted_heals=True) is after_rescue, (health, "after rescue")
    assert world.clicks == int(early) + int(after_rescue)


@pytest.mark.parametrize("additional_health", [0.95, 0.75, 0.74, 0.40, 0.39, 0.20])
def test_additional_injured_members_cannot_remove_emergency_priority(world: _World, additional_health: float) -> None:
    world.health.update({1: 0.28, 2: 0.34, 3: 0.37, 4: additional_health})
    assert _emergency(world), (4, additional_health)
    for aid in range(5, 9):
        world.timer.Stop()
        world.players.append(SimpleNamespace(login_number=aid, is_connected=True))
        world.allies.append(aid)
        world.valid.add(aid)
        world.health[aid] = additional_health
        assert _emergency(world), (aid, additional_health, world.health)
    assert world.clicks == 5


@pytest.mark.parametrize("gate", ["not_held", "pending", "stale", "conflict"])
def test_four_person_emergency_keeps_holding_pending_and_health_evidence_guards(world: _World, gate: str) -> None:
    world.health.update({1: 0.74, 2: 0.28, 3: 0.30, 4: 0.74})
    if gate == "not_held":
        world.holding = False
    elif gate == "pending":
        world.helper.build._mark_local_cast_pending(250)
    elif gate == "stale":
        world.accounts = [_publication(2, 0.28, stamp=9750)]
    else:
        world.accounts = [_publication(2, 0.28), _publication(2, 0.29)]
    assert not _emergency(world) and not world.clicks, gate
    if gate in {"stale", "conflict"}:
        assert _release(world) and world.clicks == 1, "Emergency-only evidence must not restrict routine release."


@pytest.mark.parametrize(
    "health,expected",
    [
        ((1.0, 0.25, 0.30, 1.0), True),
        ((1.0, 0.37, 0.38, 1.0), False),
        ((0.39, 0.39, 0.39, 0.39), True),
        ((0.60, 0.65, 0.70, 0.74), False),
        ((1.0, 0.19, 0.30, 1.0), False),
    ],
)
def test_emergency_examples_without_diagnostic_hooks(world: _World, health: tuple[float, ...], expected: bool) -> None:
    world.health.update(dict(zip((1, 2, 3, 4), health)))
    assert world.helper.bip_diagnostic is None
    assert _emergency(world) is expected, health
    assert world.clicks == int(expected)
    assert world.timer.deadline == (250 if expected else None)


@pytest.mark.parametrize("gate", ["pending", "party_unloaded", "no_held", "player_invalid_or_dead", "button_missing"])
def test_emergency_action_guards_without_capture(world: _World, gate: str) -> None:
    _injuries(world, (0.25, 0.30))
    if gate == "pending":
        world.timer.deadline = 250
    elif gate == "party_unloaded":
        world.party_loaded = False
    elif gate == "no_held":
        world.holding = False
    elif gate == "player_invalid_or_dead":
        world.dead.add(1)
    else:
        world.button_present = False
    assert not _emergency(world), gate
    assert not world.clicks


@pytest.mark.parametrize(
    "case,expected",
    [
        ("fresh", True),
        ("stale", False),
        ("future", False),
        ("login", False),
        ("conflict", False),
        ("missing", False),
        ("native", True),
        ("changing", False),
    ],
)
def test_emergency_publication_outcomes_without_capture(
    world: _World,
    case: str,
    expected: bool,
) -> None:
    _injuries(world, (1.0, 0.30))
    row = _publication(2, 0.25)
    world.accounts = [row]
    if case == "stale":
        row.LastUpdated = 9750
    elif case == "future":
        row.LastUpdated = 10001
    elif case == "login":
        row.AgentData.LoginNumber = 22
    elif case == "conflict":
        world.accounts.append(_publication(2, 0.25))
    elif case == "missing":
        del row.LastUpdated
    elif case == "native":
        world.accounts = []
        world.health[2] = 0.25
    elif case == "changing":

        class ChangedHealth:
            @property
            def Current(self) -> float:
                row.LastUpdated += 1
                return 0.25

        row.AgentData.Health = ChangedHealth()
    assert _emergency(world) is expected, case
    assert world.clicks == int(expected), case


@pytest.mark.parametrize("excluded", ["duplicates", "invalid", "dead", "outside"])
def test_emergency_repeated_decisions_require_unique_living_recipients(
    world: _World,
    excluded: str,
) -> None:
    _injuries(world, (0.25, 0.30))
    world.allies.extend([2, 2, 3, 3])
    world.players.extend([world.players[1], world.players[2]])
    if excluded == "invalid":
        world.valid.remove(3)
    elif excluded == "dead":
        world.dead.add(3)
    elif excluded == "outside":
        world.positions[3] = (2500.01, 0)
    for index in range(3):
        world.timer.Stop()
        assert _emergency(world) is (excluded == "duplicates"), excluded
        assert world.clicks == (index + 1 if excluded == "duplicates" else 0), (index, excluded)
