"""Offline Stage 3B accounting and real rotation/helper traces; no injected runtime."""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections.abc import Callable, Generator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "Py4GWCoreLib/Builds/Necromancer/N_Rt/Blood is Power Healer.py"
CUSTOM = ROOT / "Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py"
DIAGNOSTIC = ROOT / "Py4GWCoreLib/Builds/Skills/BipDiagnostic.py"
WIDGET = ROOT / "Widgets/Coding/Debug/Py4GW/Smart BiP Diagnostic.py"


def _return(value: Any) -> Callable[..., Any]:
    def read(*_args: Any, **_kwargs: Any) -> Any:
        return value

    return read


def _field(owner: Any, name: str) -> Callable[..., Any]:
    def read(*_args: Any, **_kwargs: Any) -> Any:
        return getattr(owner, name)

    return read


def _login_id(login: int) -> int:
    return login


def _skill_id(name: str) -> int:
    return {"Blood_is_Power": 119, "Blood_Ritual": 157, "Heroic_Refrain": 99}[name]


@pytest.fixture
def diagnostic(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, list[str], Any]:
    spec = importlib.util.spec_from_file_location("_bip_diagnostic_test", DIAGNOSTIC)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    setattr(module, "_armed", True)
    clock = SimpleNamespace(now=0.0)
    output: list[str] = []
    capture = module.BipDiagnostic(clock=lambda: clock.now, emit=output.append)
    return module, capture, output, clock


def _sample(module: Any, *, safe: bool = False, gates: tuple[str, ...] = ()) -> Any:
    sample = module.recipient_counts([module.Recipient(2, True, 0.2, True, True, False, False)])
    sample.hp, sample.maximum, sample.required = (450 if safe else 430), 500, 440
    sample.safe, sample.gates = safe, gates
    return sample


def _pass(capture: Any, sample: Any, *, preempted: bool = False) -> None:
    if capture.poll_due():
        capture.begin((1, "character", 10), True, lambda: sample)
        capture.health_rejected(2)
    capture.finish("heal" if preempted else "none", preempted=preempted)


def test_capture_60_seconds_four_hz_eight_records_and_one_shot(diagnostic: Any) -> None:
    module, capture, output, clock = diagnostic
    sample = _sample(module)
    for milliseconds in range(0, 61001, 10):
        clock.now = milliseconds / 1000
        _pass(capture, sample)
    assert capture.samples == 240, (capture.samples, output)
    assert capture.done and len(output) == 8, output
    assert output[0].startswith("BIP3B START ")
    assert all(line.startswith("BIP3B AGG ") for line in output[1:7])
    assert "result=COMPLETE" in output[-1]
    assert capture.health_only_seconds == 59.75
    second = module.BipDiagnostic(clock=lambda: clock.now, emit=output.append)
    second.begin((1, "character", 10), True, lambda: sample)
    assert second.started is None and len(output) == 8


def test_outpost_idle_disabled_and_no_demand_do_not_manufacture_diagnosis(diagnostic: Any) -> None:
    module, capture, output, clock = diagnostic
    capture.begin(None, True, module.Snapshot)
    clock.now = 100
    capture.begin((1,), False, module.Snapshot)
    assert not output and capture.started is None
    module._armed = False
    assert not capture.poll_due()
    capture.begin((1,), True, module.Snapshot)
    assert capture.started is None
    module._armed = True
    capture.begin((1,), True, module.Snapshot)
    capture.finish("none")
    clock.now = 160
    assert not capture.poll_due()
    assert "INCONCLUSIVE_NO_RELEVANT_DEMAND" in output[-1], output


@pytest.mark.parametrize(
    "gates,preempted,target,expected",
    [
        ((), False, 2, 1),
        (("energy",), False, 2, 0),
        (("pending", "toggle"), False, 2, 0),
        ((), True, 2, 0),
        ((), False, 0, 0),
        (("late_effect",), False, 2, 0),
    ],
)
def test_health_only_requires_actual_health_rejection_and_every_other_gate(
    diagnostic: Any, gates: tuple[str, ...], preempted: bool, target: int, expected: int
) -> None:
    module, capture, _, _ = diagnostic
    capture.record(_sample(module, gates=gates), 0, preempted, target)
    assert capture.totals["health_only"] == expected, (gates, preempted, target, capture.totals)
    assert capture.totals["hp_block"] == 1
    assert capture.totals["preempt"] == int(preempted)


def test_recipient_funnel_keeps_overlapping_exclusions_and_unknowns(diagnostic: Any) -> None:
    module, _, _, _ = diagnostic
    row = module.Recipient
    result = module.recipient_counts(
        [
            row(1, True, 0.4, True, True, False, False),
            row(2, True, 0.5, True, True, False, False),
            row(3, True, 0.2, True, True, True, True),
            row(4, False, None, False, False, None, True),
            row(5, True, float("nan"), True, True, False, False),
            row(6, True, -1, True, True, False, False),
            row(7, True, 0.1, True, True, False, True),
            row(8, True, 1.1, True, True, False, False),
        ]
    )
    assert result.demand == frozenset({1, 7}) and result.eligible == frozenset({1})
    assert dict(result.counts) == {
        "players": 8,
        "valid_accounts": 4,
        "energy_unknown": 4,
        "dead": 1,
        "range": 1,
        "effect_unknown": 1,
        "covered": 1,
        "locked": 3,
        "covered40": 1,
        "locked40": 1,
        "band50": 1,
        "demand40": 2,
        "eligible40": 1,
        "low40": 3,
        "dead40": 0,
        "range40": 0,
        "effect_unknown40": 0,
        "demand40_unknown": 2,
        "eligible40_unknown": 1,
    }, result.counts


def test_recovery_requires_same_demand_and_nearby_samples(diagnostic: Any) -> None:
    module, capture, _, _ = diagnostic
    capture.record(_sample(module), 0, False, 2)
    capture.record(_sample(module, safe=True), 0.25, False, 0)
    assert capture.totals["recovered"] == 1 and capture.totals["hp_rise"] == 1
    capture.record(_sample(module), 1, False, 2)
    capture.record(_sample(module, safe=True), 10, False, 0)
    assert capture.totals["recovered"] == 1 and capture.sampled_seconds == 0.25
    assert capture.health_only_seconds == 0


def test_health_only_duration_is_subset_of_continuing_demand_and_late_gate_is_target_specific(diagnostic: Any) -> None:
    module, capture, _, _ = diagnostic
    capture.record(module.Snapshot(), 0, False, 0)
    sample = _sample(module)
    sample.late_rejected = frozenset({3})
    capture.record(sample, 0.25, False, 2)
    assert capture.totals["health_only"] == 1
    assert capture.health_only_seconds == capture.demand_seconds == 0
    sample.late_rejected = frozenset({2})
    capture.record(sample, 0.5, False, 2)
    assert capture.totals["health_only"] == 1 and capture.demand_gates["late_effect"] == 2


def test_maximum_hp_change_is_not_claimed_as_hp_recovery(diagnostic: Any) -> None:
    module, capture, _, _ = diagnostic
    capture.record(_sample(module), 0, False, 2)
    sample = _sample(module, safe=True)
    sample.maximum = 450
    capture.record(sample, 0.25, False, 0)
    assert capture.totals["recovered"] == 0 and capture.totals["floor_changed"] == 1
    assert capture.totals["hp_rise"] == 0


def test_effect_after_submission_is_separate_from_cast_and_no_health_damage_inference(diagnostic: Any) -> None:
    module, capture, _, clock = diagnostic
    capture.start(0)
    capture.submission("bip", 2, 1)
    capture.submission("heal", 1, 1)
    capture.submission("heal", 2, 1)
    assert capture.totals["bip_q"] == 1 and capture.totals["coverage_after_q"] == 0
    sample = _sample(module)
    sample.covered = frozenset({2})
    capture.record(sample, 0.25, False, 0)
    assert capture.totals["coverage_after_q"] == 1
    assert capture.totals["heal_self_q"] == capture.totals["heal_other_q"] == 1
    clock.now = 60
    capture.submission("bip", 2, 1)
    assert capture.totals["bip_q"] == 1


@pytest.mark.parametrize(
    "attributes,expected",
    [
        (
            [
                SimpleNamespace(attribute_id=33, level=16, level_base=12),
                SimpleNamespace(attribute_id=4, level=12, level_base=8),
            ],
            (16, 12),
        ),
        ([SimpleNamespace(attribute_id=33, level=12), SimpleNamespace(attribute_id=4, level=8)], (12, 8)),
        ([SimpleNamespace(attribute_id=33, level_base=12)], (None, None)),
        ([SimpleNamespace(attribute_id=33, level=0)], (0, None)),
        ([], (None, None)),
    ],
)
def test_effective_attributes_never_add_hr_or_substitute_base(
    diagnostic: Any, attributes: list[Any], expected: Any
) -> None:
    module, _, _, _ = diagnostic
    assert module.effective_ranks(attributes) == expected, attributes


@pytest.mark.parametrize("identity,reason", [(None, "INVALID_SESSION"), ((2,), "IDENTITY_CHANGED")])
def test_session_change_terminates_and_cannot_resume(diagnostic: Any, identity: Any, reason: str) -> None:
    module, capture, output, _ = diagnostic
    capture.begin((1,), True, module.Snapshot)
    capture.begin(identity, True, module.Snapshot)
    capture.begin((1,), True, module.Snapshot)
    assert capture.done and len(output) == 2 and reason in output[-1], output


def test_disposal_and_observation_failure_are_terminal(diagnostic: Any) -> None:
    module, capture, output, _ = diagnostic

    def broken() -> Any:
        raise RuntimeError("unavailable runtime observation")

    capture.begin((1,), True, broken)
    capture.stop()
    assert capture.done and len(output) == 2 and "OBSERVATION_ERROR" in output[-1]
    pending = module.BipDiagnostic(emit=output.append)
    pending.stop()
    pending.start(0)
    assert pending.done and pending.started is None and len(output) == 2


def test_suspended_pass_does_not_turn_into_observed_duration(diagnostic: Any) -> None:
    module, capture, _, clock = diagnostic
    capture.begin((1,), True, lambda: _sample(module))
    clock.now = 3
    capture.finish("Recuperation", preempted=True)
    assert capture.samples == 0 and capture.totals["stale_pass"] == 1
    assert capture.winners["Recuperation"] == 1 and capture.sampled_seconds == 0


def _rotation_source() -> tuple[ast.FunctionDef, dict[str, int]]:
    tree = ast.parse(OWNER.read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_local_skill_logic")
    ids = {
        n.targets[0].id: index
        for index, n in enumerate(tree.body)
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
    }
    return function, ids


def _finish(coroutine: Generator[None, None, Any]) -> tuple[list[None], Any]:
    yielded: list[None] = []
    while True:
        try:
            yielded.append(next(coroutine))
        except StopIteration as stop:
            return yielded, stop.value


@pytest.mark.parametrize("winner", range(33))
@pytest.mark.parametrize("enabled", [False, True])
def test_real_rotation_has_identical_actions_and_yields_with_diagnostic(
    diagnostic: Any, winner: int, enabled: bool
) -> None:
    module, capture, _, _ = diagnostic
    function, ids = _rotation_source()
    events: list[tuple[str, dict[str, Any]]] = []

    class Helpers:
        def __getattr__(self, name: str) -> Any:
            def attempt(**kwargs: Any) -> Generator[None, None, bool]:
                events.append((name, kwargs))
                yield None
                return len(events) == winner

            return attempt

    helper = Helpers()

    def finish_pass(name: str, **kwargs: Any) -> None:
        if enabled:
            capture.finish(name, **kwargs)

    skills = SimpleNamespace(
        Ritualist=SimpleNamespace(RestorationMagic=helper, NoAttribute=helper, Communing=helper),
        Necromancer=SimpleNamespace(BloodMagic=helper, SoulReaping=helper, Curses=helper),
        Any=SimpleNamespace(PvE=helper, NoAttribute=helper),
    )
    caller = SimpleNamespace(
        skills=skills,
        IsSkillEquipped=_return(True),
        IsInAggro=lambda: True,
        _diagnostic_begin=lambda: capture.begin((1,), True, lambda: _sample(module)) if enabled else None,
        _diagnostic_finish=finish_pass,
    )
    namespace: dict[str, Any] = dict(ids)
    namespace["Routines"] = SimpleNamespace(Checks=SimpleNamespace(Skills=SimpleNamespace(CanCast=lambda: True)))
    code = compile(ast.Module(body=[function], type_ignores=[]), str(OWNER), "exec")
    exec(code, namespace)
    observed = _finish(namespace[function.name](caller))
    trace = list(events)
    events.clear()
    caller._diagnostic_begin = lambda: None
    caller._diagnostic_finish = _return(None)
    baseline = _finish(namespace[function.name](caller))
    assert observed == baseline and trace == events, (winner, enabled, observed, baseline, trace, events)
    assert len(events) == (winner if 0 < winner <= 31 else 31), (winner, events)


def test_observer_does_not_call_action_producing_helpers() -> None:
    tree = ast.parse(DIAGNOSTIC.read_text(encoding="utf-8"))
    observer = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "observe_build")
    calls = {n.func.attr for n in ast.walk(observer) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    forbidden = {
        "CanCastSkillID",
        "_is_local_cast_pending",
        "ResolveAllyTarget",
        "CastSkillID",
        "UseSkill",
        "Reset",
        "Stop",
    }
    assert not calls & forbidden, calls & forbidden


@pytest.fixture
def runtime_reads(diagnostic: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any]:
    module, _, _, _ = diagnostic
    world = SimpleNamespace(
        energy=0.2,
        hp=0.86,
        maximum=500,
        effect=False,
        locked=False,
        connected=True,
        pending=False,
        enough=True,
        ready=True,
        toggle=True,
        attributes=[],
        hr=False,
    )
    account = SimpleNamespace(
        IsAccount=True,
        IsSlotActive=True,
        AccountEmail="second@example.test",
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
            Energy=SimpleNamespace(Current=0.2),
            Buffs=SimpleNamespace(Buffs=[]),
            Profession=(5, 0),
        ),
    )
    world.account = account
    world.accounts = [account]
    world.tick = 10000
    world.frame_tick = None

    class Energy:
        @property
        def Current(self) -> Any:
            return world.energy

    class Buffs:
        @property
        def Buffs(self) -> list[Any]:
            return [SimpleNamespace(SkillId=119)] if world.effect else []

    account.AgentData.Energy = Energy()
    account.AgentData.Buffs = Buffs()
    # Execute the source-defined comparison, including its uint32 wrap convention.
    sync = ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync")
    sync_path = ROOT / "Py4GWCoreLib/GlobalCache/shared_memory_src/IntentSync.py"
    sync_tree = ast.parse(sync_path.read_text())
    names = {"normalize_tick", "tick_elapsed", "publication_age", "publication_is_live"}
    nodes: list[ast.stmt] = [
        node for node in sync_tree.body if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    sync.__dict__.update(UINT32_MASK=0xFFFFFFFF, UINT32_HALF_RANGE=0x80000000)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(sync_path), "exec"), sync.__dict__)
    sync.__dict__["get_uncached_tick_count64"] = _field(world, "tick")
    monkeypatch.setitem(sys.modules, sync.__name__, sync)
    constants = ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.Globals")
    globals_path = ROOT / "Py4GWCoreLib/GlobalCache/shared_memory_src/Globals.py"
    timeout = next(
        node
        for node in ast.parse(globals_path.read_text()).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS"
            for target in node.targets
        )
    )
    exec(compile(ast.Module(body=[timeout], type_ignores=[]), str(globals_path), "exec"), constants.__dict__)
    monkeypatch.setitem(sys.modules, constants.__name__, constants)
    cached = SimpleNamespace(party=SimpleNamespace(party_id=7, get_by_player_id=_return(account)))
    player = SimpleNamespace(GetAgentID=lambda: 1, GetXY=lambda: (0.0, 0.0))
    agent = SimpleNamespace(
        GetHealth=_field(world, 'hp'),
        GetMaxHealth=_field(world, 'maximum'),
        GetXY=_return((100.0, 0.0)),
        IsAlive=_return(True),
        GetAttributes=_field(world, 'attributes'),
    )
    skills = SimpleNamespace(
        CanCast=lambda: True,
        HasEnoughEnergy=_field(world, 'enough'),
        IsSkillIDReady=_field(world, 'ready'),
        HasEnoughAdrenalineBySlot=_return(True),
    )
    routines = SimpleNamespace(Checks=SimpleNamespace(Skills=skills))
    skill = SimpleNamespace(GetID=_skill_id)
    core = ModuleType("Py4GWCoreLib")
    for name, value in {
        "Agent": agent,
        "Map": SimpleNamespace(
            GetMapID=_return(10), GetRegion=_return((1, "")), GetDistrict=_return(1), GetLanguage=_return((0, ""))
        ),
        "Player": player,
        "Routines": routines,
        "Skill": skill,
        "SkillBar": SimpleNamespace(GetSkillIDBySlot=_return(119)),
        "AgentArray": SimpleNamespace(GetAllyArray=lambda: [1, 2]),
        "Range": SimpleNamespace(Spellcast=SimpleNamespace(value=1248)),
        "Utils": SimpleNamespace(Distance=_return(100.0)),
        "GLOBAL_CACHE": SimpleNamespace(
            Party=SimpleNamespace(
                GetPartyID=_return(7),
                GetPlayers=lambda: [SimpleNamespace(login_number=2, is_connected=world.connected)],
                Players=SimpleNamespace(GetAgentIDByLoginNumber=_login_id),
            ),
            Effects=SimpleNamespace(HasEffect=_field(world, 'hr')),
            ShMem=SimpleNamespace(
                GetAllAccountData=_field(world, 'accounts'),
                GetBaseTimestamp=lambda: world.tick if world.frame_tick is None else world.frame_tick,
            ),
        ),
    }.items():
        setattr(core, name, value)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", core)
    heroai = ModuleType("Py4GWCoreLib.HeroAI")
    setattr(
        heroai,
        "utils",
        SimpleNamespace(GetEnergyValues=_field(world, 'energy'), CheckForEffect=_field(world, 'effect')),
    )
    monkeypatch.setitem(sys.modules, heroai.__name__, heroai)
    locks = ModuleType("Py4GWCoreLib.GlobalCache.WhiteboardLocks")
    setattr(locks, "BLOOD_ENERGY_BUFF_LOCK_KEY", 1)
    setattr(locks, "is_buff_target_lock_blocked", _field(world, 'locked'))
    monkeypatch.setitem(sys.modules, locks.__name__, locks)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Builds.Skills.BipDiagnostic", module)
    timer = SimpleNamespace(IsStopped=lambda: not world.pending, IsExpired=lambda: False)
    conditions = SimpleNamespace(
        SacrificePercent=0.33,
        MinHealthAfterSacrificePercent=0.55,
        MinHealthAfterSacrificeAbsolute=175,
        SacrificeHealth=0.3,
    )

    def validate_target(*_args: Any) -> bool:
        return not world.effect

    owner = SimpleNamespace(
        _cached_data=cached,
        _local_cast_timer=timer,
        skills=SimpleNamespace(Necromancer=SimpleNamespace(BloodMagic=SimpleNamespace(bip_throttle=timer))),
        GetCustomSkill=_return(SimpleNamespace(Conditions=conditions)),
        GetEquippedSkillSlot=_return(1),
        IsSharedSkillToggleEnabled=_field(world, 'toggle'),
        _meets_custom_skill_weapon_requirement=_return(True),
        _meets_custom_skill_shared_conditions=_return(True),
        SpiritBuffExists=_return(False),
        _is_whiteboard_skill=_return(False),
        _validate_target_for_skill_cast=validate_target,
    )
    tree = ast.parse(OWNER.read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_diagnostic_snapshot")
    namespace = {"Snapshot": module.Snapshot, "cast": cast}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(OWNER), "exec"), namespace)
    return world, owner, namespace[function.name]


@pytest.mark.parametrize("defect", ["expired", "agent_mismatch"])
def test_review_retained_publication_cannot_manufacture_demand(runtime_reads: Any, defect: str) -> None:
    world, owner, observe = runtime_reads
    if defect == "expired":
        world.account.LastUpdated = 5000
    else:
        world.account.AgentData.AgentID = 99
    sample = observe(owner)
    assert sample.counts["energy_unknown"] == 1 and not sample.demand and not sample.eligible, (defect, sample)


def _production_method(path: Path, name: str, namespace: dict[str, Any]) -> Any:
    function = next(
        n
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef) and n.name == name
    )
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.fixture(params=[OWNER, CUSTOM], ids=["generic", "custom"])
def real_pass(
    runtime_reads: Any, diagnostic: Any, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> tuple[Any, Any, Any, list[str]]:
    world, owner, observe = runtime_reads
    _, capture, _, _ = diagnostic
    core: Any = sys.modules["Py4GWCoreLib"]
    skill_ids = {
        "Blood_is_Power": 119,
        "Blood_Ritual": 157,
        "Heroic_Refrain": 99,
        "Mend_Body_and_Soul": 1234,
        "Spirit_Light": 915,
        "Spirit_Transfer": 962,
    }
    core.Skill.GetID = skill_ids.get
    core.Routines.Agents = SimpleNamespace(GetNearestSpirit=_return(5))
    core.Agent.IsAlive = _return(True)
    core.Agent.IsValid = _return(True)
    core.Agent.IsCrippled = _return(False)
    core.Routines.Checks.Agents = SimpleNamespace(
        IsMartial=_return(False), IsMelee=_return(False), HasEffect=_return(False)
    )
    accepted: list[str] = []
    world.winner = "Mend_Body_and_Soul"
    world.hp = 0.67
    world.suspend = False

    def submit(skill: int, target: int, **_kwargs: Any) -> Generator[None, None, bool]:
        name = next(name for name, value in skill_ids.items() if value == skill)
        if name != world.winner:
            return False
        accepted.append(name)
        if world.suspend:
            yield None
        return True

    def select(*_args: Any, **kwargs: Any) -> int:
        return 1 if kwargs["validator"](1) else 0

    def no_action(*_args: Any, **_kwargs: Any) -> Generator[None, None, bool]:
        if False:
            yield None
        return False

    class OtherSkills:
        def __getattr__(self, _name: str) -> Any:
            return no_action

    owner.IsSkillEquipped = _return(True)
    owner.IsInAggro = _return(True)
    owner.ResolveAllyTarget = _return(2)
    owner.ResolvePreferredAllyTarget = select
    owner.CastSkillIDAndRestoreTarget = submit
    conditions = owner.GetCustomSkill(119).Conditions
    conditions.LessLife = 0.50
    conditions.LessEnergy = 0.40

    def custom_skill(skill: int) -> Any:
        return SimpleNamespace(
            Conditions=SimpleNamespace(**{**vars(conditions), "LessLife": 0.60 if skill == 915 else 0.50})
        )

    owner.GetCustomSkill = custom_skill
    timer = SimpleNamespace(IsStopped=_return(True), IsExpired=_return(False), Reset=_return(None))
    blood = SimpleNamespace(build=owner, bip_diagnostic=capture, bip_throttle=timer)
    namespace: dict[str, Any] = {
        "BuildCoroutine": Any,
        "cast": cast,
        "Agent": core.Agent,
        "Player": core.Player,
        "Skill": core.Skill,
        "Routines": core.Routines,
        "Range": core.Range,
        "is_buff_target_lock_blocked": _return(False),
        "BLOOD_ENERGY_BUFF_LOCK_KEY": 1,
        "post_buff_target_lock": _return(None),
    }
    bip_method = _production_method(
        ROOT / "Py4GWCoreLib/Builds/Skills/necromancer/BloodMagic.py", "Blood_is_Power", namespace
    )

    def bip_attempt(*, target_agent_id: int | None = None) -> Generator[Any, None, bool]:
        return (yield from cast(Generator[Any, None, bool], bip_method(blood, target_agent_id=target_agent_id)))

    blood.Blood_is_Power = bip_attempt
    restoration = SimpleNamespace(build=owner, bip_diagnostic=capture, _has_spirit_in_earshot=_return(True))
    for name in ("Mend_Body_and_Soul", "Spirit_Light", "Spirit_Transfer"):
        from functools import partial

        method = _production_method(ROOT / "Py4GWCoreLib/Builds/Skills/ritualist/RestorationMagic.py", name, namespace)
        setattr(restoration, name, partial(method, restoration))
    for name in ("Recuperation", "Life", "Protective_Was_Kaolai", "Wielders_Boon", "Mending_Grip", "Recovery"):
        setattr(restoration, name, no_action)
    targeting = ModuleType("Py4GWCoreLib.HeroAI.targeting")
    setattr(targeting, "GetAllAlliesArray", _return([1, 2]))
    # This accounting fixture already fixes owner selection at recipient 2.
    # Real population selection and stale proposals are covered by the owner
    # integration tests; keep the controlled population consistent here.
    setattr(targeting, "GetEligibleAllyEnergyTargets", _return([2]))
    monkeypatch.setitem(sys.modules, targeting.__name__, targeting)
    other = OtherSkills()
    owner.skills = SimpleNamespace(
        Necromancer=SimpleNamespace(BloodMagic=blood, SoulReaping=other, Curses=other),
        Ritualist=SimpleNamespace(RestorationMagic=restoration, NoAttribute=other, Communing=other),
        Any=SimpleNamespace(PvE=other, NoAttribute=other),
    )
    owner.skillbook = owner.skills
    owner._smart_kaolai = other
    smart_path = ROOT / "Py4GWCoreLib/Builds/Skills/SmartBloodIsPower.py"
    smart_class = next(
        node for node in ast.parse(smart_path.read_text(encoding="utf-8")).body if isinstance(node, ast.ClassDef)
    )
    exec(compile(ast.Module(body=[smart_class], type_ignores=[]), str(smart_path), "exec"), namespace)
    owner._smart_bip = namespace["SmartBloodIsPower"](owner, blood)
    owner._active = True
    owner._diagnostic_path = request.param
    # Optional Blood Bond is absent from the exact BiP bar.
    blood.Blood_Bond = no_action
    owner._diagnostic_begin = lambda: capture.begin((1,), True, lambda: observe(owner))
    owner._diagnostic_finish = capture.finish
    _, ids = _rotation_source()
    rotation = _production_method(
        request.param, "_run_local_skill_logic", {**ids, "Routines": core.Routines, "BuildCoroutine": Any}
    )
    return world, owner, rotation, accepted


@pytest.mark.parametrize("winner,hp", [("Mend_Body_and_Soul", 0.67), ("Spirit_Transfer", 0.45), ("Spirit_Light", 0.55)])
def test_review_real_rotation_later_heal_is_not_exclusive_health_wait(
    real_pass: Any, diagnostic: Any, winner: str, hp: float
) -> None:
    world, owner, rotation, actions = real_pass
    _, capture, _, clock = diagnostic
    world.winner, world.hp = winner, hp
    for now in (0, 0.25, 0.5):
        clock.now = now
        assert _finish(rotation(owner)) == ([], True)
    assert actions == [winner] * 3, actions
    assert capture.totals["hp_block"] == 3 and capture.totals["preempt"] == 0, capture.totals
    assert capture.totals["health_only"] == 0 and capture.health_only_seconds == 0, capture.totals
    assert capture.totals["health_reject"] == capture.totals["after_health_action"] == 3, capture.totals


@pytest.fixture
def interrupted_pass(real_pass: Any, runtime_reads: Any, diagnostic: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Real decision entry, BiP/Life, cast admission, queue path and scheduler cancellation."""
    from functools import partial

    world, owner, rotation, _ = real_pass
    _, _, observe = runtime_reads
    _, capture, _, clock = diagnostic
    core: Any = sys.modules["Py4GWCoreLib"]
    life_id = 777  # Test skill lookup; only identity consistency matters here.
    old_skill_id = core.Skill.GetID

    def skill_id(name: str) -> int:
        return life_id if name == "Life" else old_skill_id(name)

    core.Skill.GetID = skill_id
    core.Player.GetName = _return("diagnostic-test")
    core.Map.IsExplorable = _return(True)
    core.Routines.Checks.Map = SimpleNamespace(MapValid=_return(True), IsExplorable=_return(True))
    core.ConsoleLog = _return(None)
    core.Console = SimpleNamespace()
    core.GLOBAL_CACHE.Skill = SimpleNamespace(GetType=_return((0, "Spell")))
    core.SkillBar.GetSlotBySkillID = _return(1)
    world.hp, world.life_ready = 0.86, False
    events: list[tuple[str, Any]] = []
    observations: list[float] = []

    class CastTimer:
        running = False
        milliseconds = 0
        deadline = 0.0

        def IsStopped(self) -> bool:
            return not self.running

        def IsExpired(self) -> bool:
            return clock.now >= self.deadline

        def SetThrottleTime(self, milliseconds: int) -> None:
            self.milliseconds = milliseconds
            events.append(("pending_delay", milliseconds))

        def Reset(self) -> None:
            self.running, self.deadline = True, clock.now + self.milliseconds / 1000
            events.append(("pending_start", clock.now))

        def Stop(self) -> None:
            self.running = False
            events.append(("pending_stop", clock.now))

    def ready(skill: int) -> bool:
        return world.life_ready if skill == life_id else True

    def queue(slot: int, **kwargs: Any) -> None:
        events.append(("queue", (slot, kwargs)))

    def wait(milliseconds: int) -> Generator[None, None, None]:
        events.append(("wait", milliseconds))
        yield None
        yield None

    def no_action(*_args: Any, **_kwargs: Any) -> Generator[None, None, bool]:
        if False:
            yield None
        return False

    def snapshot() -> Any:
        observations.append(clock.now)
        return observe(owner)

    core.Routines.Checks.Skills.IsSkillIDReady = ready
    core.GLOBAL_CACHE.SkillBar = SimpleNamespace(UseSkill=queue)
    core.Routines.Yield = SimpleNamespace(wait=wait)
    types = ModuleType("Py4GWCoreLib.HeroAI.types")
    setattr(types, "SkillType", SimpleNamespace(Shout=SimpleNamespace(value=99)))
    monkeypatch.setitem(sys.modules, types.__name__, types)
    interrupt = ModuleType("Py4GWCoreLib.HeroAI.interrupt")
    for name in (
        "is_classified_as_interrupt",
        "is_interrupt_feasible",
        "_get_player_fast_casting_level",
        "_queue_outcome",
    ):
        setattr(interrupt, name, _return(False))
    setattr(interrupt, "_PING_HANDLER", None)
    monkeypatch.setitem(sys.modules, interrupt.__name__, interrupt)

    owner._local_cast_timer = CastTimer()
    owner._bip_diagnostic = capture
    owner._get_current_skills = _return((119, life_id, 1234, 915, 962, 0, 0, 0))
    owner._diagnostic_snapshot = snapshot
    namespace = {
        "Callable": Callable,
        "BuildCoroutine": Any,
        "Routines": core.Routines,
        "Skill": core.Skill,
        "Map": core.Map,
        "Player": core.Player,
    }
    for name in ("_diagnostic_begin", "_diagnostic_finish"):
        setattr(owner, name, partial(_production_method(owner._diagnostic_path, name, namespace), owner))
    for name in (
        "_is_local_cast_pending",
        "_mark_local_cast_pending",
        "_resolve_extra_condition",
        "CanCastSkillID",
        "CastSkillID",
        "CastSpiritSkillID",
    ):
        method = _production_method(ROOT / "Py4GWCoreLib/BuildMgr.py", name, namespace)
        setattr(owner, name, partial(method, owner))
    owner._is_spirit_skill = _return(True)
    owner._get_spirit_cast_wait_ms = _return(250)
    owner._wait_for_spirit_spawn_and_step_away = no_action
    owner.SetTickSuccess = _return(None)
    restoration = owner.skills.Ritualist.RestorationMagic
    life = _production_method(ROOT / "Py4GWCoreLib/Builds/Skills/ritualist/RestorationMagic.py", "Life", namespace)
    restoration.Life = partial(life, restoration)
    reset = _production_method(ROOT / "Py4GWCoreLib/Builds/Any/HeroAI.py", "ResetTickExecution", {})
    scheduler = SimpleNamespace(_tick_coroutine=None, _tick_phase=True, _tick_contract_signature=(1,))
    scheduler.ResetTickExecution = partial(reset, scheduler)
    return world, owner, rotation, events, observations, scheduler


@pytest.mark.parametrize("replacement_at", [0.30, 0.50])
def test_ownership_cancelled_life_cannot_feed_replacement_pass(
    interrupted_pass: Any, diagnostic: Any, replacement_at: float
) -> None:
    world, owner, rotation, events, observations, scheduler = interrupted_pass
    _, capture, _, clock = diagnostic
    assert _finish(rotation(owner)) == ([], False)
    assert capture.totals["health_only"] == capture.totals["health_reject"] == capture.samples == 1
    finalized = capture.totals.copy()
    clock.now, world.life_ready = 0.25, True
    coroutine = rotation(owner)
    scheduler._tick_coroutine = coroutine
    assert next(coroutine) is None
    assert capture.pending is not None and capture.health_target == 2
    assert capture.totals == finalized and capture.samples == 1
    assert [event[0] for event in events] == ["queue", "pending_delay", "pending_start", "wait"], events
    scheduler.ResetTickExecution()
    assert coroutine.gi_frame is None and scheduler._tick_coroutine is None
    clock.now = replacement_at
    world.life_ready = replacement_at < 0.50
    assert _finish(rotation(owner)) == ([], False)
    expected_samples = 1 if replacement_at < 0.50 else 2
    assert (capture.totals["health_only"], capture.health_only_seconds, capture.totals["after_health_action"]) == (
        expected_samples,
        0,
        0,
    ), (replacement_at, capture.totals, capture.health_only_seconds)
    assert capture.samples == expected_samples and capture.pending is None
    assert observations == ([0, 0.25] if replacement_at < 0.50 else [0, 0.25, 0.50]), observations
    assert capture.next_sample == (0.50 if replacement_at < 0.50 else 0.75)
    assert capture.winners == {"none": 2}, capture.winners
    if replacement_at < 0.50:
        assert capture.totals == finalized, (finalized, capture.totals)
        assert owner._local_cast_timer.running and events[-1][0] == "wait", events
    # New completed observations may accumulate exclusive time only after the gap.
    world.life_ready = False
    for now in (0.50, 0.75) if replacement_at < 0.50 else (0.75,):
        clock.now = now
        assert _finish(rotation(owner)) == ([], False)
    assert capture.totals["health_only"] == capture.totals["health_reject"] == capture.samples == 3
    assert capture.health_only_seconds == 0.25
    assert observations == [0, 0.25, 0.50, 0.75], observations
    assert sum(event[0] == "queue" for event in events) == 1, events


def test_ownership_completed_and_throttled_entries_preserve_finalized_continuity(
    interrupted_pass: Any, diagnostic: Any
) -> None:
    _, owner, rotation, events, observations, _ = interrupted_pass
    _, capture, _, clock = diagnostic
    for now in (0, 0.10, 0.25, 0.30, 0.50):
        clock.now = now
        assert _finish(rotation(owner)) == ([], False)
    assert capture.samples == capture.totals["health_only"] == 3
    assert capture.health_only_seconds == 0.50
    assert observations == [0, 0.25, 0.50] and not events, (observations, events)


def test_ownership_resuming_life_stays_in_the_original_decision(interrupted_pass: Any, diagnostic: Any) -> None:
    world, owner, rotation, events, observations, _ = interrupted_pass
    _, capture, _, clock = diagnostic
    assert _finish(rotation(owner)) == ([], False)
    clock.now, world.life_ready = 0.25, True
    coroutine = rotation(owner)
    assert next(coroutine) is None
    pending = capture.pending
    clock.now = 0.30
    assert next(coroutine) is None
    assert capture.pending is pending and observations == [0, 0.25]
    assert _finish(coroutine) == ([], True)
    assert capture.samples == 2 and capture.totals["health_only"] == 1
    assert capture.totals["health_reject"] == 2 and capture.totals["after_health_action"] == 1
    assert capture.health_only_seconds == 0
    assert sum(event[0] == "queue" for event in events) == 1, events


@pytest.mark.parametrize("enabled", [False, True])
def test_ownership_armed_and_disarmed_cancellation_have_identical_gameplay(
    interrupted_pass: Any, diagnostic: Any, enabled: bool
) -> None:
    world, owner, rotation, events, observations, scheduler = interrupted_pass
    module, capture, _, clock = diagnostic
    if not enabled:
        module._armed = False
        owner._bip_diagnostic = None
        owner.skills.Necromancer.BloodMagic.bip_diagnostic = None
        owner.skills.Ritualist.RestorationMagic.bip_diagnostic = None
    assert _finish(rotation(owner)) == ([], False)
    clock.now, world.life_ready = 0.25, True
    scheduler._tick_coroutine = rotation(owner)
    assert next(scheduler._tick_coroutine) is None
    scheduler.ResetTickExecution()
    clock.now = 0.30
    assert _finish(rotation(owner)) == ([], False)
    clock.now, world.life_ready = 0.50, False
    assert _finish(rotation(owner)) == ([], False)
    assert events == [
        ("queue", (1, {"target_agent_id": 0, "aftercast_delay": 250})),
        ("pending_delay", 250),
        ("pending_start", 0.25),
        ("wait", 250),
        ("pending_stop", 0.50),
    ], (enabled, events)
    assert observations == ([0, 0.25, 0.50] if enabled else []), observations
    assert capture.health_only_seconds == 0, (enabled, capture.totals)


@pytest.fixture
def widget_control(interrupted_pass: Any, diagnostic: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    world, owner, rotation, events, observations, scheduler = interrupted_pass
    control, _, output, clock = diagnostic
    control._armed = False
    owner._bip_diagnostic = None
    owner.skills.Necromancer.BloodMagic.bip_diagnostic = None
    owner.skills.Ritualist.RestorationMagic.bip_diagnostic = None
    world.aggro, world.explorable = True, True
    owner.IsInAggro = _field(world, "aggro")
    owner.IsCloseToAggro = _return(False)
    core: Any = sys.modules["Py4GWCoreLib"]
    from functools import partial

    owner.skillbook = owner.skills
    owner._active = True
    namespace = {"Routines": core.Routines, "Map": core.Map, "Player": core.Player, "BuildCoroutine": Any}
    for name in ("_diagnostic_begin", "_diagnostic_finish"):
        setattr(owner, name, partial(_production_method(CUSTOM, name, namespace), owner))
    rotation = _production_method(CUSTOM, "_run_local_skill_logic", namespace)
    core.Map.IsExplorable = _field(world, "explorable")
    core.Routines.Checks.Map.IsExplorable = _field(world, "explorable")
    ui = SimpleNamespace(clicked="", visible=True, ends=0, texts=[], fail=False)

    def button(label: str) -> bool:
        if ui.fail:
            raise RuntimeError("UI test failure")
        return label == ui.clicked

    def end() -> None:
        ui.ends += 1

    imgui = ModuleType("PyImGui")
    for name, value in {
        "begin": _field(ui, "visible"),
        "end": end,
        "text": ui.texts.append,
        "button": button,
        "same_line": _return(None),
    }.items():
        setattr(imgui, name, value)
    monkeypatch.setitem(sys.modules, imgui.__name__, imgui)
    core.PyImGui = imgui
    spec = importlib.util.spec_from_file_location("_bip_widget_test", WIDGET)
    assert spec is not None and spec.loader is not None
    widget = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(widget)

    # Keep the actual WidgetManager enable/disable and persisted-restore routes.
    path = ROOT / "Py4GWCoreLib/py4gwcorelib_src/WidgetManager.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    namespace: dict[str, Any] = {"_bump_widgets_revision": _return(None)}
    for class_name, wanted in (
        ("Widget", {"enabled", "enable", "disable"}),
        ("WidgetHandler", {"_apply_ini_configuration"}),
    ):
        original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        cls = ast.ClassDef(
            name=class_name,
            bases=[],
            keywords=[],
            decorator_list=[],
            body=[node for node in original.body if isinstance(node, ast.FunctionDef) and node.name in wanted],
        )
        exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(path), "exec"), namespace)
    host = namespace["Widget"]()
    host._Widget__enabled = False
    host.module = widget
    host.load_module = _return(True)
    host.RegisterCallbacks = host.ResumeCallbacks = host.PauseCallbacks = _return(None)
    host.on_enable, host.on_disable = widget.on_enable, widget.on_disable
    manager = namespace["WidgetHandler"]()
    manager.widgets = {"Coding/Debug/Py4GW/Smart BiP Diagnostic.py": host}
    manager._manager_cfg = _return(SimpleNamespace(get_bool=_return(True)))

    def click(label: str) -> None:
        ui.clicked = label
        widget.draw()
        ui.clicked = ""
        candidate = control.pending_capture()
        if candidate is not None:
            # Replace only clock/output boundaries; the widget uses the real control API.
            candidate.clock = _field(clock, "now")
            candidate.emit = output.append

    return SimpleNamespace(
        control=control,
        widget=widget,
        host=host,
        manager=manager,
        ui=ui,
        click=click,
        world=world,
        owner=owner,
        rotation=rotation,
        events=events,
        observations=observations,
        scheduler=scheduler,
        clock=clock,
        output=output,
    )


def test_widget_restored_enabled_state_never_arms(widget_control: Any) -> None:
    ctx = widget_control
    assert ctx.control.capture_status() == "Disarmed" and ctx.control.pending_capture() is None
    ctx.manager._apply_ini_configuration()
    assert ctx.host.enabled
    ctx.host.enable()
    ctx.widget.draw()
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    ctx.host.disable()
    ctx.host.enable()
    assert ctx.owner._bip_diagnostic is None and not ctx.control._armed
    assert not ctx.output and not ctx.observations and not ctx.events


def test_widget_explicit_arm_attaches_existing_owner_once(widget_control: Any) -> None:
    ctx = widget_control
    ctx.host.enable()
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    ctx.click("Arm one capture")
    pending = ctx.control.pending_capture()
    assert pending is not None and pending.started is None and not ctx.output
    ctx.click("Arm one capture")
    assert ctx.control.pending_capture() is pending
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert ctx.owner._bip_diagnostic is pending and pending.started == 0
    assert ctx.owner.skills.Necromancer.BloodMagic.bip_diagnostic is pending
    assert ctx.owner.skills.Ritualist.RestorationMagic.bip_diagnostic is pending
    ctx.click("Arm one capture")
    assert ctx.control.pending_capture() is None and len(ctx.output) == 1
    assert ctx.control.capture_status() == "Capturing"
    assert not ctx.events


def test_widget_waits_for_later_eligible_owner_and_only_one_claims(widget_control: Any) -> None:
    from functools import partial

    ctx = widget_control
    ctx.click("Arm one capture")
    pending = ctx.control.pending_capture()
    ctx.world.aggro = False
    for now, explorable in ((0, True), (20, True), (40, False)):
        ctx.clock.now, ctx.world.explorable = now, explorable
        ctx.owner._diagnostic_begin()
    assert pending.started is None and ctx.owner._bip_diagnostic is None
    assert not ctx.output and not ctx.observations
    # A subsequently constructed handler starts with the same None diagnostic field.
    later = SimpleNamespace(**vars(ctx.owner))
    core: Any = sys.modules["Py4GWCoreLib"]
    begin = _production_method(
        CUSTOM, "_diagnostic_begin", {"Routines": core.Routines, "Map": core.Map, "Player": core.Player}
    )
    later._diagnostic_begin = partial(begin, later)
    ctx.clock.now, ctx.world.aggro, ctx.world.explorable = 60, True, True
    later._diagnostic_begin()
    assert later._bip_diagnostic is pending and pending.started == 60
    ctx.owner._diagnostic_begin()
    assert ctx.owner._bip_diagnostic is None and ctx.observations == [60]
    assert len(ctx.output) == 1


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("via_disable", [False, True])
def test_widget_stop_and_disable_cancel_without_auto_rearm(
    widget_control: Any, active: bool, via_disable: bool
) -> None:
    ctx = widget_control
    ctx.host.enable()
    ctx.click("Arm one capture")
    capture = ctx.control.pending_capture()
    if active:
        assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    if via_disable:
        ctx.host.disable()
    else:
        ctx.click("Stop")
    expected = "ABORTED_WIDGET_DISABLED" if via_disable else "ABORTED_MANUAL_STOP"
    assert capture.done and capture.result == expected and not ctx.control._armed
    assert ctx.control.pending_capture() is None
    assert len(ctx.output) == (2 if active else 0)
    if active:
        assert expected in ctx.output[-1] and "stopped" in ctx.control.capture_status()
    ctx.host.enable()
    ctx.clock.now = 100
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert ctx.control.pending_capture() is None and ctx.owner._bip_diagnostic is (capture if active else None)


def test_widget_completion_disarms_and_explicit_rearm_uses_fresh_state(widget_control: Any) -> None:
    ctx = widget_control
    ctx.host.enable()
    ctx.click("Arm one capture")
    first = ctx.control.pending_capture()
    for milliseconds in range(0, 60251, 250):
        ctx.clock.now = milliseconds / 1000
        assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert first.done and first.result == "COMPLETE" and first.samples == 240
    assert len(ctx.output) == 8 and sum(line.startswith("BIP3B AGG") for line in ctx.output) == 6
    assert not ctx.control._armed and "complete" in ctx.control.capture_status()
    ctx.host.enable()
    ctx.widget.draw()
    assert ctx.owner._bip_diagnostic is first and len(ctx.output) == 8
    ctx.click("Arm one capture")
    second = ctx.control.pending_capture()
    assert second is not first and second.samples == 0 and second.started is None
    ctx.clock.now = 61
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert ctx.owner._bip_diagnostic is second and second.samples == 1 and second.started == 61
    first.stop()
    assert ctx.control._armed and not second.done


@pytest.mark.parametrize("enabled", [False, True])
def test_widget_controls_preserve_queue_yields_and_abandoned_pass_ownership(widget_control: Any, enabled: bool) -> None:
    ctx = widget_control
    ctx.host.enable()
    if enabled:
        ctx.click("Arm one capture")
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    ctx.clock.now, ctx.world.life_ready = 0.25, True
    old = ctx.owner._bip_diagnostic
    coroutine = ctx.rotation(ctx.owner)
    ctx.scheduler._tick_coroutine = coroutine
    assert next(coroutine) is None
    ctx.click("Stop")
    fresh = None
    if enabled:
        ctx.click("Arm one capture")
        fresh = ctx.control.pending_capture()
        assert old.done and old.pending is None and fresh.started is None
    # A suspended helper returning after Stop still belongs to the old capture.
    ctx.clock.now = 0.30
    assert _finish(coroutine) == ([None], True)
    if enabled:
        assert fresh is not None and fresh.started is None and old.samples == 1
    ctx.clock.now, ctx.world.life_ready = 0.50, False
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert ctx.events == [
        ("queue", (1, {"target_agent_id": 0, "aftercast_delay": 250})),
        ("pending_delay", 250),
        ("pending_start", 0.25),
        ("wait", 250),
        ("pending_stop", 0.50),
    ], (enabled, ctx.events)
    if enabled:
        assert fresh is not None and ctx.owner._bip_diagnostic is fresh
        assert fresh.health_only_seconds == 0 and fresh.samples == 1


def test_widget_fresh_process_module_starts_disarmed_and_is_isolated(widget_control: Any) -> None:
    ctx = widget_control
    ctx.click("Arm one capture")
    spec = importlib.util.spec_from_file_location("_bip_other_process", DIAGNOSTIC)
    assert spec is not None and spec.loader is not None
    other = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their defining module while loading.
    sys.modules[spec.name] = other
    try:
        spec.loader.exec_module(other)
        assert not other.ARM_BIP_CAPTURE and not other._armed and other.pending_capture() is None
        assert other.capture_status() == "Disarmed"
        other.stop_capture()
        assert ctx.control._armed and ctx.control.pending_capture() is not None
    finally:
        del sys.modules[spec.name]


def test_widget_window_stack_balanced_when_collapsed_or_drawing_fails(widget_control: Any) -> None:
    ctx = widget_control
    ctx.ui.visible = False
    ctx.widget.draw()
    assert ctx.ui.ends == 1 and not ctx.ui.texts
    ctx.ui.visible, ctx.ui.fail = True, True
    with pytest.raises(RuntimeError, match="UI test failure"):
        ctx.widget.draw()
    assert ctx.ui.ends == 2 and not ctx.control._armed


def test_widget_existing_session_abort_disarms_and_allows_explicit_rearm(widget_control: Any) -> None:
    ctx = widget_control
    ctx.click("Arm one capture")
    first = ctx.control.pending_capture()
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    ctx.clock.now, ctx.world.explorable = 0.25, False
    ctx.owner._diagnostic_begin()
    assert first.done and first.result == "ABORTED_INVALID_SESSION"
    assert not ctx.control._armed and "aborted" in ctx.control.capture_status()
    ctx.click("Arm one capture")
    second = ctx.control.pending_capture()
    ctx.clock.now, ctx.world.explorable = 0.50, True
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert ctx.owner._bip_diagnostic is second and second is not first


def test_widget_inconclusive_completion_remains_distinct(widget_control: Any) -> None:
    ctx = widget_control
    ctx.world.energy = 0.9
    ctx.click("Arm one capture")
    capture = ctx.control.pending_capture()
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    ctx.clock.now = 60
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert capture.result == "INCONCLUSIVE_NO_RELEVANT_DEMAND" and not ctx.control._armed
    assert "no verified demand" in ctx.control.capture_status()


def test_widget_clock_finishes_without_new_decisions_and_never_samples(widget_control: Any) -> None:
    ctx = widget_control
    ctx.widget.update()
    ctx.click("Arm one capture")
    capture = ctx.control.pending_capture()
    ctx.clock.now = 100
    ctx.widget.update()
    assert capture.started is None and not ctx.output and not ctx.observations
    assert _finish(ctx.rotation(ctx.owner)) == ([], False)
    assert capture.started == 100 and capture.samples == 1
    for now in (110, 120, 130, 140, 150, 160, 170):
        ctx.clock.now = now
        ctx.widget.update()
    assert capture.done and not ctx.control._armed and capture.samples == 1
    assert ctx.observations == [100] and not ctx.events
    assert len(ctx.output) == 8 and sum(line.startswith("BIP3B AGG") for line in ctx.output) == 6
    assert ctx.control.capture_status() == "Finished - complete (disarmed)"


@pytest.mark.parametrize("scenario", ["early", "exclusive", "energy", "expired"])
def test_review_real_rotation_distinguishes_health_rejection_outcomes(
    real_pass: Any, diagnostic: Any, scenario: str
) -> None:
    world, owner, rotation, actions = real_pass
    _, capture, _, clock = diagnostic
    world.winner = "Spirit_Transfer" if scenario == "early" else "none"
    world.hp = 0.2 if scenario == "early" else 0.86
    world.enough = scenario != "energy"
    if scenario == "expired":
        world.account.LastUpdated = 5000
    for now in (0, 0.25, 0.5):
        clock.now = now
        assert _finish(rotation(owner)) == ([], scenario == "early")
    expected = 3 if scenario == "exclusive" else 0
    assert capture.totals["health_only"] == expected, (scenario, capture.totals)
    assert capture.health_only_seconds == (0.5 if expected else 0), (scenario, capture.health_only_seconds)
    assert capture.totals["health_reject"] == (0 if scenario == "early" else 3), capture.totals
    assert capture.totals["preempt"] == (3 if scenario == "early" else 0), capture.totals
    assert capture.totals["after_health_action"] == 0, capture.totals
    assert capture.totals["health_reject_other_gate"] == (3 if scenario == "energy" else 0), capture.totals
    assert capture.totals["health_reject_unverified_target"] == (3 if scenario == "expired" else 0), capture.totals
    assert actions == (["Spirit_Transfer"] * 3 if scenario == "early" else []), actions
    if scenario == "expired":
        assert capture.totals["demand40"] == capture.totals["eligible40"] == 0, capture.totals


@pytest.mark.parametrize("ending", ["stale", "invalidated"])
def test_review_real_suspended_pass_never_contributes_exclusive_time(
    real_pass: Any, diagnostic: Any, ending: str
) -> None:
    world, owner, rotation, _ = real_pass
    _, capture, _, clock = diagnostic
    world.suspend = True
    coroutine = rotation(owner)
    assert next(coroutine) is None
    assert capture.health_target == 2 and capture.samples == 0
    if ending == "invalidated":
        capture.begin(None, True, lambda: None)
    clock.now = 0.3
    assert _finish(coroutine) == ([], True)
    assert capture.samples == capture.totals["health_only"] == capture.health_only_seconds == 0
    assert capture.totals["stale_pass"] == int(ending == "stale")


@pytest.mark.parametrize("gap", ["accepted", "stale", "abandoned", "unsampled_action"])
def test_review_duration_does_not_bridge_action_or_incomplete_pass(diagnostic: Any, gap: str) -> None:
    module, capture, _, clock = diagnostic
    sample = _sample(module)
    _pass(capture, sample)
    clock.now = 0.1
    if gap != "unsampled_action":
        capture.begin((1, "character", 10), True, lambda: sample)
        capture.health_rejected(2)
    if gap in {"accepted", "unsampled_action"}:
        capture.finish("Mend_Body_and_Soul")
    elif gap == "stale":
        clock.now = 0.36
        capture.finish("none")
    clock.now = 0.4
    _pass(capture, sample)
    assert capture.health_only_seconds == 0, (gap, capture.health_only_seconds)
    clock.now = 0.65
    _pass(capture, sample)
    assert capture.health_only_seconds == 0.25, (gap, capture.health_only_seconds)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize(
    "winner,hp", [("Mend_Body_and_Soul", 0.67), ("Spirit_Transfer", 0.2), ("Spirit_Light", 0.55), ("none", 0.86)]
)
def test_review_combined_production_helpers_actions_and_yields_unchanged(
    real_pass: Any, diagnostic: Any, enabled: bool, winner: str, hp: float
) -> None:
    world, owner, rotation, actions = real_pass
    _, capture, _, _ = diagnostic
    world.winner, world.hp, world.suspend = winner, hp, True
    if not enabled:
        owner._diagnostic_begin = _return(None)
        owner._diagnostic_finish = _return(None)
        owner.skills.Necromancer.BloodMagic.bip_diagnostic = None
        owner.skills.Ritualist.RestorationMagic.bip_diagnostic = None
    accepted = winner != "none"
    assert _finish(rotation(owner)) == ([None] if accepted else [], accepted)
    assert actions == ([winner] if accepted else [])
    assert capture.samples == int(enabled)


@pytest.mark.parametrize(
    "path,value",
    [
        ("IsSlotActive", False),
        ("IsAccount", False),
        ("IsHero", True),
        ("IsPet", True),
        ("IsNPC", True),
        ("AccountEmail", ""),
        ("AgentPartyData.PartyID", 9),
        ("AgentData.AgentID", 99),
        ("AgentData.LoginNumber", 99),
        ("AgentData.OwnerAgentID", 1),
        ("AgentData.Map.MapID", 99),
        ("AgentData.Map.Region", 99),
        ("AgentData.Map.District", 99),
        ("AgentData.Map.Language", 99),
        ("LastUpdated", None),
        ("AccountEmail", None),
        ("AgentData.LoginNumber", None),
        ("AgentData.AgentID", None),
        ("AgentData.Map", None),
    ],
)
@pytest.mark.parametrize("isolated", [False, True])
def test_review_invalid_publication_identity_stays_unknown(
    runtime_reads: Any, path: str, value: Any, isolated: bool
) -> None:
    world, owner, observe = runtime_reads
    world.account.IsIsolated = isolated
    target = world.account
    parts = path.split(".")
    for part in parts[:-1]:
        target = getattr(target, part)
    if value is None:
        delattr(target, parts[-1])
    else:
        setattr(target, parts[-1], value)
    sample = observe(owner)
    assert sample.counts["energy_unknown"] == sample.counts["effect_unknown"] == 1, (path, value, sample)
    assert not sample.demand and not sample.eligible, (path, value, sample)


@pytest.mark.parametrize(
    "tick,updated,valid",
    [
        (10000, 5001, True),
        (10000, 5000, False),
        (10000, 4999, False),
        (10000, 10001, False),
        (0x100000010, 0xFFFFFFF0, True),
    ],
)
@pytest.mark.parametrize("isolated", [False, True])
def test_review_source_freshness_boundary_and_wrap(
    runtime_reads: Any, tick: int, updated: int, valid: bool, isolated: bool
) -> None:
    world, owner, observe = runtime_reads
    world.account.IsIsolated = isolated
    world.tick, world.account.LastUpdated = tick, updated
    sample = observe(owner)
    assert bool(sample.demand) is valid and bool(sample.eligible) is valid, (tick, updated, sample)
    assert sample.counts["energy_unknown"] == int(not valid), sample


@pytest.mark.parametrize(
    "energy,valid",
    [
        (0.0, True),
        (0.2, True),
        (None, False),
        (float("nan"), False),
        (float("inf"), False),
        (-0.1, False),
        (1.1, False),
    ],
)
def test_review_zero_energy_is_demand_but_unavailable_is_not(runtime_reads: Any, energy: Any, valid: bool) -> None:
    world, owner, observe = runtime_reads
    world.energy = energy
    sample = observe(owner)
    assert sample.counts["valid_accounts"] == int(valid), (energy, sample)
    assert sample.counts["energy_unknown"] == int(not valid) and bool(sample.demand) is valid, (energy, sample)


def test_review_disappeared_publication_ignores_retained_cache(runtime_reads: Any) -> None:
    world, owner, observe = runtime_reads
    world.accounts = []
    assert owner._cached_data.party.get_by_player_id(2) is world.account
    sample = observe(owner)
    assert sample.counts["energy_unknown"] == 1 and not sample.demand and not sample.eligible, sample


def test_review_active_payload_replaces_retained_values_without_cache_writes(runtime_reads: Any) -> None:
    from copy import deepcopy

    world, owner, observe = runtime_reads
    active = deepcopy(world.account)
    active.AgentData.Energy = SimpleNamespace(Current=0.9)
    active.AgentData.Buffs = SimpleNamespace(Buffs=[SimpleNamespace(SkillId=157)])
    world.account.LastUpdated = 5000
    world.accounts = [active]
    sample = observe(owner)
    assert sample.counts["valid_accounts"] == sample.counts["covered"] == 1, sample
    assert not sample.demand and not sample.eligible, sample
    assert owner._cached_data.party.get_by_player_id(2) is world.account
    assert world.account.LastUpdated == 5000 and world.account.AgentData.Energy.Current == 0.2
    world.connected = False
    sample = observe(owner)
    assert sample.counts["energy_unknown"] == 1 and not sample.demand and not sample.eligible, sample


def test_review_agent_id_reuse_on_another_map_is_not_this_recipient(runtime_reads: Any) -> None:
    from copy import deepcopy

    world, owner, observe = runtime_reads
    other_map = deepcopy(world.account)
    other_map.AccountEmail = "different-map@example.test"
    other_map.AgentData.Map.MapID = 99
    world.accounts.append(other_map)
    sample = observe(owner)
    assert sample.demand == sample.eligible == frozenset({2}), sample
    other_map.AgentData.Map.MapID = 10
    sample = observe(owner)
    assert sample.counts["energy_unknown"] == 1 and not sample.demand, sample


def test_review_publication_changing_identity_during_read_stays_unknown(runtime_reads: Any) -> None:
    world, owner, observe = runtime_reads

    class ReusedSlotEnergy:
        @property
        def Current(self) -> float:
            world.account.AccountEmail = "replacement@example.test"
            return 0.2

    world.account.AgentData.Energy = ReusedSlotEnergy()
    sample = observe(owner)
    assert sample.counts["energy_unknown"] == 1 and not sample.demand and not sample.eligible, sample


@pytest.mark.parametrize("isolated", [False, True])
def test_review_distinct_accounts_professions_and_duplicate_association(runtime_reads: Any, isolated: bool) -> None:
    from copy import deepcopy

    world, owner, observe = runtime_reads
    world.account.IsIsolated = isolated
    core: Any = sys.modules["Py4GWCoreLib"]
    second = deepcopy(world.account)
    second.AccountEmail = "third@example.test"
    second.AgentData.AgentID = second.AgentData.LoginNumber = 3
    second.AgentData.Profession = (3, 5)
    world.accounts.append(second)
    core.GLOBAL_CACHE.Party.GetPlayers = _return([SimpleNamespace(login_number=n, is_connected=True) for n in (2, 3)])
    core.AgentArray.GetAllyArray = _return([1, 2, 3])
    sample = observe(owner)
    assert sample.demand == sample.eligible == frozenset({2, 3}), sample
    assert sample.counts["demand40_mesmer"] == sample.counts["demand40_other"] == 1, sample
    assert sample.counts["eligible40_mesmer"] == sample.counts["eligible40_other"] == 1, sample
    del second.AgentData.Profession
    assert observe(owner).counts["demand40_unknown"] == 1
    second.AccountEmail = world.account.AccountEmail
    sample = observe(owner)
    assert sample.counts["energy_unknown"] == 2 and not sample.demand, sample


@pytest.mark.parametrize(
    "hp,maximum,safe", [(0.88, 500, False), (0.88001, 500, True), (1.0, 260, False), (0.95, 500, True), (1.0, 0, None)]
)
def test_runtime_snapshot_strict_health_and_read_only_pending(
    runtime_reads: Any, hp: float, maximum: int, safe: Any
) -> None:
    world, owner, observe = runtime_reads
    world.hp, world.maximum = hp, maximum
    result = observe(owner)
    assert result.safe is safe and result.eligible == frozenset({2}), result
    assert result.gates == (), result.gates
    world.pending, world.enough, world.toggle = True, False, False
    assert set(observe(owner).gates) == {"pending", "throttle", "energy", "toggle"}


def test_runtime_effect_energy_and_effective_rank_observations(runtime_reads: Any) -> None:
    world, owner, observe = runtime_reads
    world.attributes = [SimpleNamespace(attribute_id=33, level=16, level_base=12)]
    world.hr = True
    result = observe(owner)
    assert result.restoration == 16 and result.blood is None and result.hr == "True"
    world.hr = False
    world.effect = True
    result = observe(owner)
    assert result.hr == "False" and not result.demand and result.counts["covered40"] == 1
    world.energy = float("nan")
    assert observe(owner).counts["energy_unknown"] == 1
    world.connected = False
    result = observe(owner)
    assert result.counts["valid_accounts"] == 0 and result.counts["effect_unknown"] == 1


def test_runtime_unavailable_energy_effects_and_attributes_stay_unknown(runtime_reads: Any) -> None:
    world, owner, observe = runtime_reads

    def unavailable(*_args: Any) -> Any:
        raise RuntimeError("observation unavailable")

    core: Any = sys.modules["Py4GWCoreLib"]
    core.Agent.GetAttributes = unavailable
    core.GLOBAL_CACHE.Effects.HasEffect = unavailable
    world.account.AgentData.Energy = SimpleNamespace()
    world.account.AgentData.Buffs = SimpleNamespace()
    result = observe(owner)
    assert result.restoration is None and result.blood is None and result.hr == "unknown"
    assert result.counts["energy_unknown"] == result.counts["effect_unknown"] == 1
    assert not result.demand and not result.eligible


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("hp,accepted", [(0.86, False), (0.88, False), (0.91, True)])
def test_real_bip_helper_health_rejection_and_submission_have_no_extra_actions(
    diagnostic: Any, enabled: bool, hp: float, accepted: bool
) -> None:
    module, capture, _, _ = diagnostic
    capture.begin((1,), True, lambda: _sample(module))
    events: list[str] = []

    def cast_skill(*args: Any, **kwargs: Any) -> Generator[None, None, bool]:
        events.append("queue")
        if False:
            yield None
        return True

    conditions = SimpleNamespace(
        SacrificeHealth=0.3,
        SacrificePercent=0.33,
        MinHealthAfterSacrificePercent=0.55,
        MinHealthAfterSacrificeAbsolute=175,
    )
    helper = SimpleNamespace(
        bip_diagnostic=capture if enabled else None,
        bip_throttle=SimpleNamespace(IsStopped=lambda: True, Reset=lambda: events.append("throttle_reset")),
        build=SimpleNamespace(
            GetCustomSkill=_return(SimpleNamespace(Conditions=conditions)),
            IsSkillEquipped=_return(True),
            ResolveAllyTarget=_return(2),
            CastSkillIDAndRestoreTarget=cast_skill,
        ),
    )
    path = ROOT / "Py4GWCoreLib/Builds/Skills/necromancer/BloodMagic.py"
    function = next(
        n
        for n in ast.walk(ast.parse(path.read_text()))
        if isinstance(n, ast.FunctionDef) and n.name == "Blood_is_Power"
    )

    def post_lock(*_args: Any, **_kwargs: Any) -> None:
        events.append("lock_post")

    namespace: dict[str, Any] = {
        "BuildCoroutine": Any,
        "Skill": SimpleNamespace(GetID=_return(119)),
        "Agent": SimpleNamespace(GetHealth=_return(hp), GetMaxHealth=_return(500)),
        "Player": SimpleNamespace(GetAgentID=lambda: 1),
        "BLOOD_ENERGY_BUFF_LOCK_KEY": 1,
        "is_buff_target_lock_blocked": _return(False),
        "post_buff_target_lock": post_lock,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    assert _finish(namespace[function.name](helper)) == ([], accepted)
    assert events == (["lock_post", "queue", "throttle_reset"] if accepted else []), (enabled, hp, events)
    assert capture.totals["bip_q"] == int(enabled and accepted)
    assert capture.health_target == (2 if enabled and not accepted else 0)


@pytest.mark.parametrize("name", ["Mend_Body_and_Soul", "Spirit_Light", "Spirit_Transfer"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("target", [1, 2])
@pytest.mark.parametrize("accepted", [False, True])
def test_real_heals_observe_selected_target_without_reselecting_or_resubmitting(
    diagnostic: Any, monkeypatch: pytest.MonkeyPatch, name: str, enabled: bool, target: int, accepted: bool
) -> None:
    module, capture, _, _ = diagnostic
    capture.begin((1,), True, lambda: _sample(module))
    events: list[tuple[str, int]] = []

    def select(*_args: Any, **_kwargs: Any) -> int:
        events.append(("select", target))
        return target

    def submit(_skill: int, agent_id: int, **_kwargs: Any) -> Generator[None, None, bool]:
        events.append(("submit", agent_id))
        if False:
            yield None
        return accepted

    targeting = ModuleType("Py4GWCoreLib.HeroAI.targeting")
    setattr(targeting, "GetAllAlliesArray", _return([1, 2]))
    monkeypatch.setitem(sys.modules, targeting.__name__, targeting)
    helper = SimpleNamespace(
        bip_diagnostic=capture if enabled else None,
        _has_spirit_in_earshot=lambda: True,
        build=SimpleNamespace(
            IsSkillEquipped=_return(True),
            ResolvePreferredAllyTarget=select,
            GetCustomSkill=_return(SimpleNamespace(Conditions=SimpleNamespace(LessLife=0.7))),
            CastSkillIDAndRestoreTarget=submit,
        ),
    )
    path = ROOT / "Py4GWCoreLib/Builds/Skills/ritualist/RestorationMagic.py"
    function = next(
        n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.FunctionDef) and n.name == name
    )
    namespace: dict[str, Any] = {
        "BuildCoroutine": Any,
        "cast": cast,
        "Skill": SimpleNamespace(GetID=_return(1)),
        "Routines": SimpleNamespace(Agents=SimpleNamespace(GetNearestSpirit=_return(5))),
        "Range": SimpleNamespace(Spellcast=SimpleNamespace(value=1248)),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    assert _finish(namespace[name](helper)) == ([], accepted)
    assert events == [("select", target), ("submit", target)], (name, enabled, target, accepted, events)
    expected = int(enabled and accepted)
    assert capture.totals["heal_self_q"] == (expected if target == 1 else 0)
    assert capture.totals["heal_other_q"] == (expected if target == 2 else 0)
