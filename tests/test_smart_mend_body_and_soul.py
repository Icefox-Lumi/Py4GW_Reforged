"""Real Smart MBaS decisions and BuildMgr submissions with bounded native doubles."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from collections.abc import Callable
from collections.abc import Generator
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
from test_condition_observations import account_world as _condition_account_fixture
from test_condition_observations import condition_world as _condition_world_fixture

account_world = _condition_account_fixture
condition_world = _condition_world_fixture

controller: Any = importlib.import_module("test_my_blood_is_power")
world = controller.world
runtime = controller.runtime
capture_runtime = controller.capture_runtime
ROOT = Path(__file__).resolve().parents[1]
MEND = 1234


@pytest.fixture
def mend_runtime(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    r = runtime

    def native_skill(name: str) -> SimpleNamespace:
        return SimpleNamespace(id=SimpleNamespace(id=r.world.skill_id(name)))

    controller.admission._module(monkeypatch, "PySkill", Skill=native_skill)
    models = controller.admission._load(monkeypatch, "_mend_models", "Py4GWCoreLib/enums_src/Model_enums.py")
    r.core.SpiritModelID = models.SpiritModelID
    r.world.valid.update({3, 4})
    r.world.health.update(dict.fromkeys((1, 2, 3, 4), 1.0))
    r.world.allies = [1, 2, 3, 4]
    r.conditions = {aid: [] for aid in r.world.allies}
    r.flags = {aid: set() for aid in r.world.allies}
    r.professions = {1: 4, 2: 5, 3: 1, 4: 8}
    r.weapons = {1: "Staff", 2: "Spear", 3: "Sword", 4: "Staff"}
    r.iw = set()
    r.effect_reads = []
    r.accounts = []
    r.remote_players = set()
    r.account_reads = []
    r.heroes = []
    r.hero_bars = {}
    r.types = {}
    r.excluded = set()
    r.events = []
    r.clock = 10000
    r.cost = 5.0

    def effects(aid: int) -> list[Any]:
        r.effect_reads.append(aid)
        return list(r.conditions[aid])

    def accounts(*, sort_results: bool = True) -> list[Any]:
        r.account_reads.append(sort_results)
        return r.accounts

    def condition(aid: int, *names: str) -> None:
        r.conditions[aid] = [
            SimpleNamespace(skill_id=r.world.skill_id(name), duration=20, time_remaining=10) for name in names
        ]

    r.condition = condition

    def conditioned(aid: int) -> bool:
        return bool(r.conditions[aid] or r.flags[aid])

    def bleeding(aid: int) -> bool:
        return "Bleeding" in r.flags[aid]

    def crippled(aid: int) -> bool:
        return "Crippled" in r.flags[aid]

    def wounded(aid: int) -> bool:
        return "Deep_Wound" in r.flags[aid]

    def pet(aid: int) -> bool:
        return aid in r.world.pets

    def professions(aid: int) -> tuple[int, int]:
        return r.professions[aid], 8 if aid == 1 else 0

    def iw(aid: int) -> bool:
        return aid in r.iw

    def weapon(aid: int) -> tuple[int, str]:
        return 1, r.weapons[aid]

    def cost(_skill: int, _aid: int) -> float:
        return r.cost

    def skill_type(skill: int) -> tuple[int, str]:
        return r.types.get(skill, 5), "offline"

    def hero_bar(index: int) -> list[Any]:
        return r.hero_bars[index]

    def identity(value: int) -> int:
        return value

    def login_number(aid: int) -> int:
        return aid if aid == 1 or aid in r.remote_players else 0

    def excluded(aid: int, _skill: int) -> bool:
        return aid in r.excluded

    def record(event: str, aid: int) -> None:
        r.events.append((event, aid))

    r.core.Agent.IsConditioned = conditioned
    r.core.Agent.IsBleeding = bleeding
    r.core.Agent.IsCrippled = crippled
    r.core.Agent.IsDeepWounded = wounded
    r.core.Agent.IsPet = pet
    r.core.Agent.GetLoginNumber = login_number
    r.core.Agent.GetProfessions = professions
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "HasIllusionaryWeaponry", iw)
    monkeypatch.setattr(r.core.Routines.Checks.Agents, "_get_shared_weapon_name", weapon)
    monkeypatch.setattr(r.core.Routines.Checks.Skills, "GetEnergyCostWithEffects", cost)
    r.core.Skill.GetType = skill_type
    r.core.SkillBar.GetHeroSkillbar = hero_bar
    r.core.Party = SimpleNamespace(
        IsPartyLoaded=lambda: False,
        GetPartyID=lambda: 7,
        GetPlayers=lambda: [SimpleNamespace(login_number=aid, is_connected=True) for aid in (1, *r.remote_players)],
        Players=SimpleNamespace(GetAgentIDByLoginNumber=identity),
        GetHeroes=lambda: r.heroes,
        GetHeroIndex=identity,
    )
    r.core.GLOBAL_CACHE.ShMem.GetAllAccountData = accounts
    clock: Any = sys.modules["Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync"]
    monkeypatch.setattr(clock, "get_uncached_tick_count64", lambda: r.clock)
    utils: Any = sys.modules["Py4GWCoreLib.HeroAI.utils"]
    monkeypatch.setattr(utils, "CheckForEffect", excluded)
    controller.admission._module(monkeypatch, "Py4GWCoreLib.Effect", Effects=SimpleNamespace(GetEffects=effects))
    # Exercise the production cache, including its per-frame reset registration.
    callbacks: list[Any] = []

    def register(*args: Any, **kwargs: Any) -> None:
        callbacks.append(args)

    controller.admission._module(
        monkeypatch,
        "PyCallback",
        PyCallback=SimpleNamespace(Register=register, RemoveByName=controller.noop),
        Phase=SimpleNamespace(PreUpdate=0),
    )
    cache = controller.admission._load(
        monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.FrameCache", "Py4GWCoreLib/py4gwcorelib_src/FrameCache.py"
    )
    r.frame = cache.FRAME_CACHE
    assert len(callbacks) == 1
    subject = controller.admission._load(
        monkeypatch,
        "Py4GWCoreLib.Builds.Skills.SmartMendBodyAndSoul",
        "Py4GWCoreLib/Builds/Skills/SmartMendBodyAndSoul.py",
    )
    r.build = r.Custom(cached_data=r.cache)
    r.mend = subject.SmartMendBodyAndSoul(r.build)
    r.build._smart_mend = r.mend
    r.mend.bip_diagnostic = SimpleNamespace(submission=record)
    return r


def publication(r: Any, aid: int, *conditions: str) -> Any:
    r.remote_players.add(aid)
    return SimpleNamespace(
        IsAccount=True,
        IsSlotActive=True,
        LastUpdated=r.clock - 1,
        AgentPartyData=SimpleNamespace(PartyID=7),
        AgentData=SimpleNamespace(
            AgentID=aid,
            LoginNumber=aid,
            Map=SimpleNamespace(MapID=r.state.map, Region=1, District=1, Language=0),
            Health=SimpleNamespace(Current=r.world.health[aid]),
            Is_Dead=False,
            Is_DeadByTypeMap=False,
            Is_Conditioned=bool(conditions),
            Buffs=SimpleNamespace(
                Buffs=[
                    SimpleNamespace(SkillId=r.world.skill_id(name), Type=2, Duration=20, Remaining=10)
                    for name in conditions
                ]
            ),
            Skillbar=SimpleNamespace(Skills=[]),
        ),
    )


@pytest.fixture
def staged_remote(mend_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Execute both production publisher methods; double only native inputs/timers."""
    r = mend_runtime
    account = publication(r, 2, "Dazed", "Poison")
    account.LastUpdated = r.clock - 600
    account.AccountName = "remote"
    account.InAggro, account.InAggroTick64 = False, 0
    account.InventoryBags = SimpleNamespace(reset=controller.noop)
    r.accounts.append(account)
    r.condition(2, "Poison")
    r.world.health[3] = 0.50
    data = account.AgentData
    stages: dict[int, int] = {}
    fast_timers: dict[int, Any] = {}
    updates: list[str] = []

    def timer(timers: Any, *_args: Any) -> Any:
        return SimpleNamespace(IsExpired=lambda: timers is fast_timers, Reset=controller.noop)

    def buff_update(_aid: int) -> None:
        updates.append("buffs")
        data.Buffs.Buffs = [
            SimpleNamespace(SkillId=effect.skill_id, Type=2, Duration=effect.duration, Remaining=effect.time_remaining)
            for effect in r.conditions[2]
        ]

    def health_update(aid: int) -> None:
        data.Health.Current = r.world.health[aid]

    data.Health.from_context = health_update
    data.Energy = SimpleNamespace(from_context=controller.noop)
    data.Map.from_context = lambda: updates.append("map")
    data.Skillbar.from_context = lambda: updates.append("skillbar")
    data.Buffs.from_context = buff_update
    namespace: dict[str, Any] = {
        "__package__": "Py4GWCoreLib.GlobalCache.shared_memory_src",
        "_get_agent_timer": timer,
        "_get_slot_timer": timer,
        "_agent_fast_stage": stages,
        "_agent_fast_timers": fast_timers,
        "SHMEM_MAX_PLAYERS": 64,
        "PySystem": SimpleNamespace(get_tick_count64=lambda: r.clock - 1),
    }

    def vector(*values: float) -> tuple[float, ...]:
        return values

    namespace.update(Vec2f=vector, Vec3f=vector)
    for speed in ("fast", "medium", "slow"):
        namespace.setdefault(f"_agent_{speed}_timers", {})
        namespace[f"SHMEM_AGENT_{speed.upper()}_UPDATE_THROTTLE_MS"] = 0
    for speed in ("meta", "progress", "static", "inventory"):
        namespace[f"_player_{speed}_timers"] = {}
        namespace[f"SHMEM_PLAYER_{speed.upper()}_UPDATE_THROTTLE_MS"] = 0

    def load_method(filename: str) -> Any:
        path = ROOT / "Py4GWCoreLib/GlobalCache/shared_memory_src" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        method = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "from_context"
        )
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
        return namespace["from_context"]

    data.from_context = partial(load_method("AgentDataStruct.py"), data)
    publish = partial(load_method("AccountStruct.py"), account)

    def position(_aid: int) -> tuple[float, float, float]:
        return 0.0, 0.0, 0.0

    def velocity(_aid: int) -> tuple[float, float]:
        return 0.0, 0.0

    def resume(stage: int) -> None:
        stages[2] = stage
        updates.clear()
        with monkeypatch.context() as patch:
            for name, value in (("Party", r.core.Party), ("Map", r.core.Map)):
                controller.admission._module(patch, f"Py4GWCoreLib.{name}", **{name: value})
            controller.admission._module(patch, "Py4GWCoreLib.enums_src.Item_enums", Bags=SimpleNamespace())
            patch.setattr(r.state, "agent", 2)
            patch.setattr(r.core.Party, "IsPartyLoaded", lambda: True)
            patch.setattr(r.core.Player, "IsPlayerLoaded", lambda: True, raising=False)
            patch.setattr(r.core.Map, "IsMapLoading", lambda: False, raising=False)
            patch.setattr(r.core.Map, "IsMapReady", lambda: True, raising=False)
            for name in ("GetZPlane", "GetRotationAngle", "GetAgentEffects", "GetTypeMap"):
                patch.setattr(r.core.Agent, name, controller.false, raising=False)
            patch.setattr(r.core.Agent, "GetXYZ", position, raising=False)
            patch.setattr(r.core.Agent, "GetVelocityXY", velocity, raising=False)
            publish("remote@example.invalid", 2)
        assert account.LastUpdated == r.clock - 1
        assert updates == [{0: "map", 1: "skillbar", 2: "buffs"}[stage]]

    r.remote_account, r.resume_publication = account, resume
    return r


@pytest.mark.parametrize("stage", [0, 1, 2], ids=["map", "skillbar", "buffs"])
@pytest.mark.parametrize("mode", ["urgent", "opportunistic"])
def test_resumed_heartbeat_does_not_refresh_retained_conditions(staged_remote: Any, stage: int, mode: str) -> None:
    r = staged_remote
    r.resume_publication(stage)
    retained = {buff.SkillId for buff in r.remote_account.AgentData.Buffs.Buffs}
    assert retained == {r.world.skill_id(name) for name in (("Poison",) if stage == 2 else ("Dazed", "Poison"))}
    for _ in range(3):
        r.frame.reset_cache()
        accepted = controller.finish(r.mend.try_cast(mode=mode))
        assert (accepted, r.world.submissions) == (False, []), (
            stage,
            mode,
            "current=Poison; HP=100%; ally=50%; heartbeat_age=1",
            retained,
            accepted,
            r.world.submissions,
        )
    attempt(r, "routine", 3)


@pytest.mark.parametrize("stage", [0, 1], ids=["map", "skillbar"])
def test_owner_heals_injured_ally_instead_of_stale_remote_dazed(staged_remote: Any, stage: int) -> None:
    r = staged_remote
    r.resume_publication(stage)
    r.build.OnContractActivated(r.cache)
    actual: Callable[..., Generator[Any, None, bool]] = r.mend.try_cast
    controller.trace_rotation(r.build, r.build.skillbook, None)
    results: list[tuple[str, bool]] = []

    def record(*, mode: str) -> Generator[Any, None, bool]:
        accepted = yield from actual(mode=mode)
        results.append((mode, accepted))
        return accepted

    r.mend.try_cast = record
    controller.finish(r.build.ProcessSkillCasting())
    assert results == [("emergency", False), ("urgent", False), ("routine", True)]
    assert r.world.submissions == [(3, 3, 250)] and r.build.DidTickSucceed()


@pytest.mark.parametrize("mode,hp", [("emergency", 0.20), ("routine", 0.50), ("preventive", 0.80)])
def test_unknown_remote_conditions_cannot_promote_healing_ties(mend_runtime: Any, mode: str, hp: float) -> None:
    r = mend_runtime
    r.world.health.update({2: hp, 3: hp})
    r.world.allies = [1, 3, 2, 4]
    r.accounts.append(publication(r, 2, "Deep_Wound", "Dazed", "Poison"))
    attempt(r, mode, 3)


@pytest.mark.parametrize("mode,hp", [("emergency", 0.20), ("routine", 0.50), ("preventive", 0.80)])
@pytest.mark.parametrize("published", [False, True])
def test_remote_health_healing_survives_unknown_conditions(
    mend_runtime: Any, mode: str, hp: float, published: bool
) -> None:
    r = mend_runtime
    r.world.health[2] = hp
    r.remote_players.add(2)
    if published:
        r.accounts.append(publication(r, 2, "Dazed", "Poison"))
    attempt(r, mode, 2)
    assert r.effect_reads == []


@pytest.mark.parametrize("mode", ["urgent", "opportunistic"])
@pytest.mark.parametrize("published", [False, True])
def test_remote_native_snapshot_is_not_assumed_current(mend_runtime: Any, mode: str, published: bool) -> None:
    r = mend_runtime
    r.remote_players.add(2)
    # Even a matching local snapshot cannot corroborate a remote identity without
    # a verified freshness contract; native duration is not an observation age.
    r.condition(2, "Dazed", "Poison")
    r.flags[2].update({"Deep_Wound", "Bleeding", "Crippled"})
    if published:
        r.accounts.append(publication(r, 2, "Dazed", "Poison"))
    attempt(r, mode, None)
    assert r.mend._read_conditions(2) is None
    assert r.effect_reads == []


@pytest.mark.parametrize("stage", ["wrapper", "dispatch"])
@pytest.mark.parametrize("mode", ["urgent", "opportunistic"])
@pytest.mark.parametrize("published", [False, True])
def test_both_admissions_reject_evidence_that_becomes_untrusted(
    mend_runtime: Any, monkeypatch: pytest.MonkeyPatch, stage: str, mode: str, published: bool
) -> None:
    r = mend_runtime
    r.condition(2, "Dazed", "Poison")
    r.world.health[3] = 0.50
    decisions: list[bool] = []
    admit: Callable[..., bool] = r.build.CanCastSkillID
    submit: Callable[..., Generator[Any, None, bool]] = r.build.CastSkillIDAndRestoreTarget

    def record_admission(skill: int, **kwargs: Any) -> bool:
        accepted = admit(skill, **kwargs)
        if callable(kwargs.get("extra_condition")):
            decisions.append(accepted)
        return accepted

    def lose_trust() -> None:
        r.remote_players.add(2)
        r.condition(2, "Poison")
        if published:
            r.accounts[:] = [publication(r, 2, "Dazed", "Poison")]

    def before_wrapper(skill: int, target: int, **kwargs: Any) -> Generator[Any, None, bool]:
        assert target == 2
        lose_trust()
        return (yield from submit(skill, target, **kwargs))

    def before_dispatch() -> int:
        lose_trust()
        return 20

    monkeypatch.setattr(r.build, "CanCastSkillID", record_admission)
    if stage == "wrapper":
        monkeypatch.setattr(r.build, "CastSkillIDAndRestoreTarget", before_wrapper)
    else:
        monkeypatch.setattr(r.core.Player, "GetTargetID", before_dispatch)
    attempt(r, mode, None)
    assert decisions == ([False] if stage == "wrapper" else [True, False]), (stage, mode, published, decisions)


def test_full_health_local_mesmer_keeps_one_spirit_dazed_cleanse(mend_runtime: Any) -> None:
    r = mend_runtime
    r.professions[1] = 5
    r.condition(1, "Dazed")
    assert r.mend._spirit_count() == 1
    attempt(r, "urgent", 1)


def attempt(r: Any, mode: str, target: int | None) -> None:
    observed = controller.finish(r.mend.try_cast(mode=mode))
    expected = [] if target is None else [(r.state.bar.index(MEND) + 1, target, 250)]
    assert observed is (target is not None), (mode, target, observed, r.world.submissions)
    assert r.world.submissions == expected, (mode, target, r.world.submissions)
    assert r.events == ([] if target is None else [("heal", target)])
    if target is not None:
        # Even before native flags/recharge update, the owner's pending barrier applies.
        assert controller.finish(r.mend.try_cast(mode=mode)) is False
        assert r.world.submissions == expected


@pytest.fixture
def v2_runtime(condition_world: Any, mend_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    from dataclasses import replace

    r, storage = mend_runtime, condition_world
    storage.local = replace(storage.local, location=(r.state.map, 1, 1, 0))
    for row in storage.table.AccountData[:2]:
        row.AgentData.Map.MapID = r.state.map
    storage.owner = storage.module.account_owner(storage.table, 1)
    r.storage = storage
    r.accounts.append(publication(r, 2))
    r.core.GLOBAL_CACHE.ShMem.ReadConditionObservation = storage.manager.ReadConditionObservation

    def character(aid: int) -> str:
        return f"Character {aid - 1}"

    r.core.Agent.GetNameByID = character
    r.professions[2] = 9  # HR Paragon remains martial, not automatically a spellcaster.

    def publish(*names: str) -> None:
        assert storage.mapping.publish(
            storage.publisher, storage.owner, storage.local.instance, storage.clock.uncached, frozenset(names)
        )

    r.publish = publish
    return r


@pytest.mark.parametrize(
    "conditions,mode,allowed",
    [
        (("Blind",), "urgent", True),
        (("Dazed",), "urgent", False),
        (("Poison", "Burning"), "opportunistic", True),
        (("Poison",), "opportunistic", False),
        ((), "urgent", False),
    ],
)
def test_v2_owner_conditions_use_existing_policy(
    v2_runtime: Any, conditions: tuple[str, ...], mode: str, allowed: bool
) -> None:
    r = v2_runtime
    r.publish(*conditions)
    attempt(r, mode, 2 if allowed else None)
    assert 2 not in r.effect_reads, "consumer must never enumerate a remote human's native effects"


@pytest.mark.parametrize("fault", ["missing", "expired", "empty", "unknown", "removed", "attach"])
def test_v2_unknown_or_removed_evidence_keeps_health_healing(v2_runtime: Any, fault: str) -> None:
    r, s = v2_runtime, v2_runtime.storage
    if fault != "missing":
        r.publish("Blind")
    if fault == "expired":
        s.clock.uncached += 750
    elif fault in ("empty", "removed"):
        r.publish(*(() if fault == "empty" else ("Poison",)))
    elif fault == "unknown":
        assert s.mapping.publish(s.publisher, s.owner, s.local.instance, s.clock.uncached, None)
    elif fault == "attach":
        s.manager._attach = lambda: False
    attempt(r, "urgent", None)
    r.world.health[2] = r.accounts[0].AgentData.Health.Current = 0.50
    r.frame.reset_cache()
    attempt(r, "routine", 2)


@pytest.mark.parametrize("gate", ["spirit", "combat", "reserve", "emergency"])
def test_v2_opportunistic_preserves_all_other_gates(v2_runtime: Any, gate: str) -> None:
    r = v2_runtime
    r.publish("Blind", "Poison")
    if gate == "spirit":
        r.world.spirits = []
    elif gate == "combat":
        r.state.aggro = False
    elif gate == "reserve":
        r.cost = 10000
    else:
        r.world.health[3] = 0.39
    attempt(r, "opportunistic", None)


@pytest.mark.parametrize("stage", ["wrapper", "dispatch"])
@pytest.mark.parametrize(
    "change", ["expired", "removed", "restart", "reentry", "character", "party", "isolation", "instance"]
)
def test_v2_both_final_admissions_recheck_current_binding(
    v2_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    change: str,
) -> None:
    from dataclasses import replace

    r, s = v2_runtime, v2_runtime.storage
    r.publish("Blind")

    def mutate() -> None:
        if change == "expired":
            s.clock.uncached += 750
        elif change == "removed":
            r.publish()
        elif change == "restart":
            s.clock.uncached += 1
            s.publisher = s.module.Publisher()
            r.publish("Blind")
        elif change == "reentry":
            s.mapping.invalidate(s.publisher, stop=False)
            r.publish("Blind")
        elif change == "character":
            s.table.AccountData[1].AgentData.CharacterName = "Other character"
        elif change == "party":
            s.table.AccountData[1].AgentPartyData.PartyID = 8
        elif change == "isolation":
            s.table.AccountData[1].IsolationGroupID = 8
        else:
            s.local = replace(s.local, instance=b"j" * 32)

    original: Callable[..., Generator[Any, None, bool]] = r.build.CastSkillIDAndRestoreTarget

    def wrapper(skill: int, target: int, **kwargs: Any) -> Generator[Any, None, bool]:
        mutate()
        return (yield from original(skill, target, **kwargs))

    def dispatch() -> int:
        mutate()
        return 20

    (
        monkeypatch.setattr(r.build, "CastSkillIDAndRestoreTarget", wrapper)
        if stage == "wrapper"
        else monkeypatch.setattr(r.core.Player, "GetTargetID", dispatch)
    )
    attempt(r, "urgent", None)


def test_v2_condition_age_does_not_borrow_or_require_health_cadence(v2_runtime: Any) -> None:
    r = v2_runtime
    r.publish("Blind")
    r.accounts[0].LastUpdated = r.clock - 251
    attempt(r, "urgent", 2)


@pytest.fixture
def evidence(v2_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    r = v2_runtime
    r.control = controller.admission._load(
        monkeypatch, "Py4GWCoreLib.Builds.Skills.BipDiagnostic", "Py4GWCoreLib/Builds/Skills/BipDiagnostic.py"
    )
    output: list[str] = []
    r.output = output
    r.now = 0.0
    assert r.control.arm_capture(mbas=True)
    r.capture = r.control.pending_capture()
    r.capture.clock = lambda: r.now
    r.capture.emit = output.append
    r.capture.begin((1, "private-character", r.state.map), True, r.control.Snapshot)
    r.mend.bip_diagnostic = r.capture
    return r


def evidence_cast(r: Any, mode: str, accepted: bool) -> list[str]:
    assert controller.finish(r.mend.try_cast(mode=mode)) is accepted, r.output
    assert r.world.submissions == ([(3, 2, 250)] if accepted else []), r.output
    assert 2 not in r.effect_reads, r.effect_reads
    return [line for line in r.output if line.startswith("MBASV2 ")]


@pytest.mark.parametrize("mode,conditions", [("urgent", ("Blind",)), ("opportunistic", ("Burning", "Poison"))])
@pytest.mark.parametrize("health", [0.84, 0.85, 1.0])
def test_evidence_real_selection_admissions_and_queue(
    evidence: Any, mode: str, conditions: tuple[str, ...], health: float
) -> None:
    r = evidence
    r.world.health[2] = r.accounts[0].AgentData.Health.Current = health
    r.publish(*conditions)
    lines = evidence_cast(r, mode, True)
    assert len(lines) == 5, lines
    candidate = lines[1]
    for field in (
        "remote_human=1",
        f"hp_pct={health * 100:.3f}",
        f"mode={mode}",
        "source=authorized_owner_publication",
        "binding=VALID",
        "spirits=1",
        "selection_gates=PASS",
    ):
        assert field in candidate, (field, candidate)
    assert "ranked=" + ",".join(sorted(conditions)) in candidate
    assert all("attempt=1 target=remote1" in line for line in lines[1:]), lines
    assert "call=1 accepted=1" in lines[2] and "call=2 accepted=1" in lines[3], lines
    assert f"healthy_condition_only={int(health >= 0.85)}" in lines[-1], lines
    assert not any(secret in "\n".join(lines) for secret in ("private-character", "Character", "@", "hwnd"))
    r.now = 60
    r.control.update_capture()
    result = "HEALTHY_CONDITION_ONLY_QUEUED" if health >= 0.85 else "EXERCISED_NO_HEALTHY_QUEUE_PROOF"
    assert any(f"MBASV2 DONE result={result}" in line for line in r.output), r.output
    assert r.capture.result == "INCONCLUSIVE_NO_RELEVANT_DEMAND" and not r.control._armed


@pytest.mark.parametrize("mode", ["emergency", "routine", "preventive"])
def test_evidence_health_heal_is_not_condition_only(evidence: Any, mode: str) -> None:
    r = evidence
    r.world.health[2] = r.accounts[0].AgentData.Health.Current = 0.2
    r.publish("Blind")
    assert evidence_cast(r, mode, True) == [r.output[1]], r.output
    assert r.capture.totals["heal_other_q"] == 1


@pytest.mark.parametrize("fault", ["empty", "expired", "dazed_paragon", "no_spirits", "combat", "emergency"])
def test_evidence_no_opportunity_is_not_exercised(evidence: Any, fault: str) -> None:
    r = evidence
    r.publish(*(() if fault == "empty" else ("Dazed",) if fault == "dazed_paragon" else ("Blind",)))
    if fault == "expired":
        r.storage.clock.uncached += 750
    elif fault == "no_spirits":
        r.world.spirits = []
    elif fault == "combat":
        r.state.aggro = r.state.close = False
    elif fault == "emergency":
        r.world.health[3] = 0.39
    evidence_cast(r, "urgent", False)
    r.now = 60
    r.control.update_capture()
    assert any("MBASV2 DONE result=NOT_EXERCISED" in line for line in r.output), r.output


@pytest.mark.parametrize("call", [1, 2])
@pytest.mark.parametrize("fault", ["expired", "instance", "owner", "restart", "removed", "energy", "context"])
def test_evidence_actual_admission_rejections(
    evidence: Any, monkeypatch: pytest.MonkeyPatch, call: int, fault: str
) -> None:
    from dataclasses import replace

    r, s = evidence, evidence.storage
    r.publish("Blind")
    original: Callable[..., Generator[Any, None, bool]] = r.build.CastSkillIDAndRestoreTarget

    def mutate() -> int:
        if fault == "expired":
            s.clock.uncached += 750
        elif fault == "instance":
            s.local = replace(s.local, instance=b"z" * 32)
        elif fault == "owner":
            s.table.AccountData[1].AgentData.CharacterName = "Changed"
        elif fault == "restart":
            s.clock.uncached += 1
            s.publisher = s.module.Publisher()
            r.publish("Blind")
        elif fault == "removed":
            r.publish()
        elif fault == "context":
            r.build._generation += 1
        else:
            r.world.energy = 0
        return 20

    def wrapper(*args: Any, **kwargs: Any) -> Generator[Any, None, bool]:
        mutate()
        return (yield from original(*args, **kwargs))

    if call == 1:
        monkeypatch.setattr(r.build, "CastSkillIDAndRestoreTarget", wrapper)
    else:
        monkeypatch.setattr(r.core.Player, "GetTargetID", mutate)
    lines = evidence_cast(r, "urgent", False)
    assert "SUBMISSION attempt=1 target=remote1 accepted=0" in lines[-1], lines
    if fault != "energy":
        assert any(f"call={call} accepted=0" in line for line in lines), lines
    assert r.capture._mend_counts["healthy_queued"] == 0


@pytest.mark.parametrize("after_queue", [False, True])
@pytest.mark.parametrize("ending", ["close", "stop", "expiry", "new_decision", "dispose", "reload", "widget_disable"])
def test_evidence_cancelled_attempt_cannot_later_succeed(
    evidence: Any,
    monkeypatch: pytest.MonkeyPatch,
    after_queue: bool,
    ending: str,
) -> None:
    r = evidence
    r.publish("Blind")
    original: Callable[..., Generator[Any, None, bool]] = r.build.CastSkillIDAndRestoreTarget

    def suspended(*args: Any, **kwargs: Any) -> Generator[Any, None, Any]:
        yield
        if not after_queue:
            return (yield from original(*args, **kwargs))

    monkeypatch.setattr(r.build, "RestoreEnemyTarget" if after_queue else "CastSkillIDAndRestoreTarget", suspended)
    coroutine = r.mend.try_cast(mode="urgent")
    next(coroutine)
    assert bool(r.world.submissions) is after_queue
    token = r.capture._mend_attempt
    if ending == "close":
        coroutine.close()
    elif ending == "expiry":
        r.now = 60
        r.control.update_capture()
    elif ending == "new_decision":
        r.capture.enter_decision()
    elif ending == "dispose":
        r.build._bip_diagnostic = r.capture
        r.build.Dispose()
    elif ending == "reload":
        exec(
            compile(Path(r.control.__file__).read_text(encoding="utf-8"), r.control.__file__, "exec"),
            cast(dict[str, Any], vars(r.control)),
        )
    elif ending == "widget_disable":
        r.core.PyImGui = SimpleNamespace()
        widget = controller.admission._load(
            monkeypatch, "_mend_capture_widget", "Widgets/Coding/Debug/Py4GW/Smart BiP Diagnostic.py"
        )
        widget.on_disable()
    else:
        r.control.stop_capture()
    if ending in {"stop", "expiry", "new_decision"}:
        # Ending diagnostics must not change casting; even a real later return
        # cannot resurrect this closed evidence token.
        assert controller.finish(coroutine) is True
    r.capture.mend_return(token, True)
    assert r.capture._mend_counts["healthy_queued"] == 0, r.output
    assert any("MBASV2 CANCELLED" in line for line in r.output), r.output
    assert not any("MBASV2 SUBMISSION" in line for line in r.output), r.output
    coroutine.close()


@pytest.mark.parametrize("failure", ["sink", "candidate", "admission", "return", "cancel"])
def test_evidence_failures_cannot_block_cast(evidence: Any, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    r = evidence
    r.publish("Blind")

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("private exception must not escape")

    monkeypatch.setattr(r.capture, "emit" if failure == "sink" else "mend_" + failure, broken)
    evidence_cast(r, "urgent", True)
    assert "private exception" not in "\n".join(r.output)


def test_evidence_partial_output_failure_is_inconclusive(evidence: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    r = evidence
    r.publish("Blind")

    def emit(message: str) -> None:
        if "CANDIDATE" in message:
            raise RuntimeError("private")
        r.output.append(message)

    monkeypatch.setattr(r.capture, "emit", emit)
    evidence_cast(r, "urgent", True)
    r.now = 60
    r.control.update_capture()
    assert any("MBASV2 DONE result=INCONCLUSIVE_DIAGNOSTIC_ERROR" in line for line in r.output), r.output


@pytest.mark.parametrize("rejected", [False, True])
def test_evidence_output_rate_and_attempt_limits(
    evidence: Any,
    monkeypatch: pytest.MonkeyPatch,
    rejected: bool,
) -> None:
    r = evidence
    r.publish("Blind")
    if rejected:
        original: Callable[..., Generator[Any, None, bool]] = r.build.CastSkillIDAndRestoreTarget

        def reject(*args: Any, **kwargs: Any) -> Generator[Any, None, bool]:
            r.build._generation += 1
            return (yield from original(*args, **kwargs))

        monkeypatch.setattr(r.build, "CastSkillIDAndRestoreTarget", reject)
    for index in range(200):
        r.now = index / 10
        r.frame.reset_cache()
        r.build._local_cast_timer.Stop()
        controller.finish(r.mend.try_cast(mode="urgent"))
    assert r.capture._mend_counts["candidates"] == 8, r.output
    assert r.capture._mend_counts["suppressed"] > 0
    candidates = [line for line in r.output if line.startswith("MBASV2 CANDIDATE")]
    assert len(candidates) == 8
    assert r.capture._mend_counts["healthy_queued"] == (0 if rejected else 8)
    # Exercise the output guard independently of today's two-callback BuildMgr.
    for _ in range(100):
        r.capture._mend_write("ADMISSION limit_probe=1")
    r.now = 60
    r.control.update_capture()
    lines = [line for line in r.output if line.startswith("MBASV2 ")]
    assert len(lines) == 49 and lines[-1].startswith("MBASV2 DONE "), lines
    assert max(map(len, lines)) < 1024
    count = len(r.output)
    r.control.update_capture()
    assert len(r.output) == count and not r.control._armed


@pytest.mark.parametrize("enabled", [False, True])
def test_evidence_decisions_and_native_reads_identical(
    evidence: Any, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    r = evidence
    r.publish("Blind")
    if not enabled:
        r.control.stop_capture()
    reads: list[str] = []
    # Count all existing native-facade calls, excluding neither health nor context.
    for owner in (r.core.Agent, r.core.Player, r.core.Map):
        for name in tuple(cast(dict[str, Any], vars(owner))):
            original = getattr(owner, name)
            if not callable(original):
                continue

            def counted(*args: Any, _read: Any = original, _name: str = name, **kwargs: Any) -> Any:
                reads.append(_name)
                return _read(*args, **kwargs)

            monkeypatch.setattr(owner, name, counted)
    evidence_cast(r, "urgent", True)
    first_reads, first_submissions = list(reads), list(r.world.submissions)
    reads.clear()
    r.world.submissions.clear()
    r.frame.reset_cache()
    r.build._local_cast_timer.Stop()
    r.mend.bip_diagnostic = None
    assert controller.finish(r.mend.try_cast(mode="urgent")) is True
    assert reads == first_reads and r.world.submissions == first_submissions, (first_reads, reads)
    if not enabled:
        assert not any("MBASV2 CANDIDATE" in line for line in r.output), r.output


@pytest.mark.parametrize("change", ["character", "map"])
def test_evidence_context_change_stops_capture(evidence: Any, change: str) -> None:
    r = evidence
    identity = (1, "changed" if change == "character" else "private-character", r.state.map + int(change == "map"))
    r.capture.begin(identity, True, r.control.Snapshot)
    r.publish("Blind")
    evidence_cast(r, "urgent", True)
    assert r.capture.done and not r.control._armed
    assert not any("MBASV2 CANDIDATE" in line for line in r.output), r.output


def test_emergency_health_wins_over_condition_preference(mend_runtime: Any) -> None:
    r = mend_runtime
    r.world.health.update({2: 0.10, 3: 0.39})
    r.condition(3, "Blind", "Burning", "Bleeding")
    attempt(r, "emergency", 2)
    assert r.effect_reads == []


@pytest.mark.parametrize("mode", ["routine", "preventive"])
def test_healing_stays_health_first(mend_runtime: Any, mode: str) -> None:
    r = mend_runtime
    r.world.health.update({2: 0.50, 3: 0.60})
    r.condition(3, "Blind", "Burning", "Bleeding")
    attempt(r, mode, 2)


@pytest.mark.parametrize("mode,threshold", [("emergency", 0.40), ("routine", 0.75), ("preventive", 0.85)])
@pytest.mark.parametrize("delta", [-0.00001, 0, 0.00001])
@pytest.mark.parametrize("spirits", [0, 1])
def test_strict_healing_boundaries(mend_runtime: Any, mode: str, threshold: float, delta: float, spirits: int) -> None:
    r = mend_runtime
    r.world.health[2] = threshold + delta
    r.world.spirits = [10] if spirits else []
    attempt(r, mode, 2 if delta < 0 else None)


@pytest.mark.parametrize(
    "condition,aid,hp,allowed",
    [
        ("Dazed", 2, 1.0, True),
        ("Blind", 3, 1.0, True),
        ("Blind", 4, 1.0, False),
        ("Crippled", 3, 1.0, True),
        ("Crippled", 2, 1.0, False),
        ("Deep_Wound", 2, 0.59999, True),
        ("Deep_Wound", 2, 0.60, False),
    ],
)
@pytest.mark.parametrize("spirits", [0, 1])
def test_urgent_conditions_and_one_spirit(
    mend_runtime: Any, condition: str, aid: int, hp: float, allowed: bool, spirits: int
) -> None:
    r = mend_runtime
    r.condition(aid, condition)
    r.world.health[aid] = hp
    r.world.spirits = [10] if spirits else []
    attempt(r, "urgent", aid if allowed and spirits else None)


@pytest.mark.parametrize("mode", ["urgent", "opportunistic", "preventive", "routine", "emergency"])
@pytest.mark.parametrize("combat,close", [(False, False), (False, True), (True, False)])
def test_combat_admission(
    mend_runtime: Any, monkeypatch: pytest.MonkeyPatch, mode: str, combat: bool, close: bool
) -> None:
    r = mend_runtime
    r.state.aggro = combat
    monkeypatch.setattr(r.build, "IsCloseToAggro", lambda: close)
    r.condition(2, "Dazed", "Burning")
    r.world.health[2] = 0.39 if mode == "emergency" else 0.70
    allowed = mode in ("routine", "emergency") or combat or (mode == "urgent" and close)
    attempt(r, mode, 2 if allowed else None)


@pytest.mark.parametrize("mode", ["urgent", "opportunistic"])
def test_condition_only_declines_during_health_emergency(mend_runtime: Any, mode: str) -> None:
    r = mend_runtime
    r.world.health[3] = 0.3999
    r.condition(2, "Dazed", "Burning", "Poison")
    attempt(r, mode, None)
    assert r.effect_reads == []


@pytest.mark.parametrize("spirits", [0, 1, 3, 5])
@pytest.mark.parametrize("conditions", [1, 2, 3])
def test_opportunistic_distinct_conditions_and_capacity(mend_runtime: Any, spirits: int, conditions: int) -> None:
    r = mend_runtime
    r.world.spirits = list(range(10, 10 + spirits))
    for aid in r.world.spirits:
        r.world.valid.add(aid)
        r.world.spawned.add(aid)
        r.world.health[aid] = 1.0
        r.world.place(aid, 500)
    r.condition(2, *("Burning", "Poison", "Bleeding")[:conditions])
    attempt(r, "opportunistic", 2 if spirits and conditions >= 2 else None)


@pytest.mark.parametrize("cost,energy", [(5, 9.99), (5, 10), (8, 15.99), (8, 16), (3, 6)])
def test_opportunistic_reserve_uses_adjusted_cost(mend_runtime: Any, cost: float, energy: float) -> None:
    r = mend_runtime
    r.cost, r.world.energy = cost, energy / 30
    r.condition(2, "Burning", "Poison")
    attempt(r, "opportunistic", 2 if energy >= cost * 2 else None)


@pytest.mark.parametrize(
    "condition,aid,useful",
    [
        ("Deep_Wound", 2, True),
        ("Burning", 2, True),
        ("Weakness", 2, True),
        ("Weakness", 3, True),
        ("Cracked_Armor", 3, True),
        ("Cracked_Armor", 2, False),
        ("Disease", 2, True),
        ("Bleeding", 2, True),
        ("Blind", 4, False),
        ("Dazed", 3, False),
        ("Crippled", 2, False),
    ],
)
def test_useful_condition_classes(mend_runtime: Any, condition: str, aid: int, useful: bool) -> None:
    r = mend_runtime
    r.condition(aid, "Poison", condition)
    attempt(r, "opportunistic", aid if useful else None)


@pytest.mark.parametrize("kind", ["duplicate", "generic", "unknown", "expired", "wrong_type", "missing"])
def test_uncertain_effects_do_not_invent_multiple_conditions(mend_runtime: Any, kind: str) -> None:
    r = mend_runtime
    r.condition(2, "Poison", "Poison")
    if kind == "generic":
        r.conditions[2] = []
        r.flags[2].add("conditioned")
    elif kind == "unknown":
        r.conditions[2][1].skill_id = 99999
    elif kind == "expired":
        r.condition(2, "Poison", "Burning")
        r.conditions[2][1].time_remaining = 0
    elif kind == "wrong_type":
        account = publication(r, 2, "Poison", "Burning")
        account.AgentData.Buffs.Buffs[1].Type = 1
        r.accounts.append(account)
    elif kind == "missing":
        r.conditions[2] = [SimpleNamespace()]
    attempt(r, "opportunistic", None)


def test_specific_flags_supply_identity_without_double_counting(mend_runtime: Any) -> None:
    r = mend_runtime
    r.condition(2, "Bleeding", "Bleeding")
    r.flags[2].update({"Bleeding", "Poisoned"})
    assert controller.finish(r.mend.try_cast(mode="opportunistic")) is False
    r.frame.reset_cache()
    r.flags[2].add("Deep_Wound")
    attempt(r, "opportunistic", 2)


@pytest.mark.parametrize(
    "kind",
    [
        "caster_spear",
        "hero_spell",
        "hero_ritual",
        "other_hero",
        "remote_spell",
        "remote_ritual",
        "partial",
        "iw",
        "pet",
    ],
)
def test_roles_use_existing_martial_rules_and_visible_spellbars(mend_runtime: Any, kind: str) -> None:
    r = mend_runtime
    aid = 2 if kind not in ("iw", "pet") else 3
    r.condition(aid, "Dazed" if aid == 2 else "Blind")
    if kind.startswith("hero") or kind == "other_hero":
        r.heroes = [SimpleNamespace(agent_id=2, hero_id=1, owner_player_id=2 if kind == "other_hero" else 1)]
        r.hero_bars[1] = [SimpleNamespace(id=SimpleNamespace(id=7000)) for _ in range(8)]
        r.types[7000] = 22 if kind.endswith("ritual") or kind == "other_hero" else 5
    elif kind.startswith("remote") or kind == "partial":
        account = publication(r, 2, "Dazed")
        account.AgentData.Skillbar.Skills = [SimpleNamespace(Id=7000)] * (7 if kind == "partial" else 8)
        r.types[7000] = 22 if kind.endswith("ritual") else 5
        r.accounts.append(account)
    elif kind == "iw":
        r.iw.add(3)
    elif kind == "pet":
        r.world.pets.append(3)
        r.weapons[3] = "Unknown"
    if kind.startswith("remote") or kind == "partial":
        copied = r.mend._read_publications(True)[2]
        assert r.mend._spellcaster(2, copied) is (kind != "remote_ritual")
    attempt(r, "urgent", None if kind in ("hero_ritual", "remote_spell", "remote_ritual", "partial", "iw") else aid)


@pytest.mark.parametrize("skill_type", [4, 5, 6, 9, 11, 24, 25, 21, 22])
@pytest.mark.parametrize("source", ["remote", "local_hero"])
def test_spell_types_include_item_and_weapon_spells_but_exclude_rituals(
    mend_runtime: Any, skill_type: int, source: str
) -> None:
    r = mend_runtime
    copied = None
    if source == "remote":
        r.accounts.append(publication(r, 2, "Dazed"))
        r.accounts[0].AgentData.Skillbar.Skills = [SimpleNamespace(Id=7000)] * 8
        copied = r.mend._read_publications(True)[2]
    else:
        r.heroes = [SimpleNamespace(agent_id=2, hero_id=1, owner_player_id=1)]
        r.hero_bars[1] = [SimpleNamespace(id=SimpleNamespace(id=7000))] * 8
        r.condition(2, "Dazed")
    r.types[7000] = skill_type
    expected_role = skill_type in {4, 5, 6, 9, 11, 24, 25}
    assert r.mend._spellcaster(2, copied) is expected_role
    attempt(r, "urgent", 2 if source == "local_hero" and expected_role else None)


@pytest.mark.parametrize("mode", ["urgent", "opportunistic", "routine"])
@pytest.mark.parametrize(
    "fault",
    ["stale", "boundary", "future", "wrong_party", "wrong_map", "wrong_login", "inactive", "dead", "nan", "duplicate"],
)
def test_remote_publication_qualification(mend_runtime: Any, mode: str, fault: str) -> None:
    r = mend_runtime
    r.world.health[2] = 0.70
    # Local condition evidence must not override an identified but unsafe remote account.
    r.condition(2, "Dazed", "Poison")
    account = publication(r, 2, "Dazed", "Poison")
    r.accounts.append(account)
    if fault in ("stale", "boundary", "future"):
        account.LastUpdated = r.clock + {"stale": -251, "boundary": -250, "future": 1}[fault]
    elif fault == "wrong_party":
        account.AgentPartyData.PartyID = 8
    elif fault == "wrong_map":
        account.AgentData.Map.MapID += 1
    elif fault == "wrong_login":
        account.AgentData.LoginNumber += 1
    elif fault == "inactive":
        account.IsSlotActive = False
    elif fault == "dead":
        account.AgentData.Is_Dead = True
    elif fault == "nan":
        account.AgentData.Health.Current = float("nan")
    else:
        r.accounts.append(account)
    attempt(r, mode, None)


def test_valid_remote_evidence_and_missing_details_do_not_block_healing(mend_runtime: Any) -> None:
    r = mend_runtime
    r.world.health[2] = 0.95
    account = publication(r, 2, "Dazed")
    account.LastUpdated = r.clock - 249
    account.AgentData.Health.Current = 0.50
    del account.AgentData.Buffs
    r.accounts.append(account)
    assert controller.finish(r.mend.try_cast(mode="urgent")) is False
    attempt(r, "routine", 2)


@pytest.mark.parametrize("fault", ["invalid", "dead", "range", "safe_target", "absent", "nan", "zero", "overfull"])
def test_ineligible_ally_cannot_hide_eligible_target(mend_runtime: Any, fault: str) -> None:
    r = mend_runtime
    r.world.health.update({2: 0.41, 3: 0.55})
    r.condition(2, "Dazed")
    r.condition(3, "Blind")
    if fault == "invalid":
        r.world.valid.remove(2)
    elif fault == "dead":
        r.world.dead.add(2)
    elif fault == "range":
        r.world.place(2, 1248.01)
    elif fault == "safe_target":
        r.excluded.add(2)
    elif fault == "absent":
        r.world.allies.remove(2)
    else:
        r.world.health[2] = {"nan": float("nan"), "zero": 0.0, "overfull": 1.01}[fault]
    attempt(r, "urgent", 3)


@pytest.mark.parametrize("distance,allowed", [(1248, True), (1248.01, False)])
def test_recipient_boundary_and_self_healing(mend_runtime: Any, distance: float, allowed: bool) -> None:
    r = mend_runtime
    r.world.place(2, distance)
    r.world.health[2] = 0.2
    attempt(r, "emergency", 2 if allowed else None)
    if not allowed:
        r.world.health[1] = 0.3
        attempt(r, "emergency", 1)


@pytest.mark.parametrize("kind", ["boundary", "outside", "dead", "invalid", "pet", "duplicate", "hostile"])
def test_established_spirit_filter_is_caster_centered(mend_runtime: Any, kind: str) -> None:
    r = mend_runtime
    r.condition(2, "Dazed", "Poison")
    r.world.place(2, -1000)
    r.world.place(10, 1012 if kind == "boundary" else 1012.01 if kind == "outside" else 1000)
    if kind == "dead":
        r.world.dead.add(10)
    elif kind == "invalid":
        r.world.valid.remove(10)
    elif kind == "pet":
        r.world.spawned.remove(10)
        r.world.pets.append(10)
    elif kind == "duplicate":
        r.world.spirits.append(10)
        assert r.mend._spirit_count() == 1
    elif kind == "hostile":
        r.world.hostile.add(10)
    attempt(r, "urgent", 2 if kind in ("boundary", "duplicate", "hostile") else None)


@pytest.mark.parametrize("mode", ["emergency", "routine", "urgent", "opportunistic"])
def test_deterministic_ties_and_severity(mend_runtime: Any, mode: str) -> None:
    r = mend_runtime
    r.world.health.update({2: 0.3 if mode == "emergency" else 0.5, 3: 0.3 if mode == "emergency" else 0.5})
    r.world.allies = [1, 3, 2, 4]
    r.condition(2, "Dazed", "Poison")
    r.condition(3, "Blind", "Burning", "Poison")
    attempt(r, mode, 3 if mode == "emergency" else 2)


def test_urgent_classes_rank_before_health(mend_runtime: Any) -> None:
    r = mend_runtime
    r.world.health.update({2: 0.59, 3: 0.41, 4: 0.45})
    r.condition(2, "Deep_Wound")
    r.condition(3, "Blind")
    r.condition(4, "Dazed")
    attempt(r, "urgent", 2)


def test_capacity_is_a_ranking_aid_and_never_a_two_spirit_gate(mend_runtime: Any) -> None:
    r = mend_runtime
    r.world.spirits.extend([11, 12])
    r.world.valid.update({11, 12})
    r.world.spawned.update({11, 12})
    r.world.health.update({11: 1.0, 12: 1.0, 2: 0.90, 3: 1.0})
    r.condition(2, "Burning", "Poison")
    r.condition(3, "Burning", "Poison", "Bleeding")
    attempt(r, "opportunistic", 3)


@pytest.mark.parametrize("guard", ["missing", "pending", "recharge", "energy", "toggle", "casting", "outpost"])
def test_early_admission_prevents_observation_scans(mend_runtime: Any, guard: str) -> None:
    r = mend_runtime
    r.condition(2, "Dazed")
    if guard == "missing":
        r.state.bar[2] = 0
    elif guard == "pending":
        r.build._mark_local_cast_pending(250)
    elif guard == "recharge":
        r.world.recharge = 1
    elif guard == "energy":
        r.world.energy = 0.01
    elif guard == "toggle":
        r.cache.account_options.Skills[2] = False
    elif guard == "casting":
        r.state.can_cast = False
    else:
        r.world.explorable = False
    attempt(r, "urgent", None)
    assert r.effect_reads == [] and r.account_reads == []


@pytest.mark.parametrize("stage", ["wrapper", "dispatch"])
@pytest.mark.parametrize(
    "change",
    [
        "dead",
        "invalid",
        "range",
        "condition",
        "spirit",
        "emergency",
        "combat",
        "energy",
        "bar",
        "map",
        "generation",
        "cache",
        "casting",
        "health",
    ],
)
def test_final_revalidation_keeps_original_target_and_never_retargets(
    mend_runtime: Any, monkeypatch: pytest.MonkeyPatch, stage: str, change: str
) -> None:
    r = mend_runtime
    mode = "routine" if change == "health" else "opportunistic"
    r.world.health.update({2: 0.50, 3: 0.60})
    r.condition(2, "Dazed", "Poison")
    r.condition(3, "Blind", "Poison")

    def mutate() -> None:
        if change == "dead":
            r.world.dead.add(2)
        elif change == "invalid":
            r.world.valid.remove(2)
        elif change == "range":
            r.world.place(2, 1248.01)
        elif change == "condition":
            r.conditions[2] = []
        elif change == "spirit":
            r.world.spirits.clear()
        elif change == "emergency":
            r.world.health[4] = 0.10
        elif change == "combat":
            r.state.aggro = False
        elif change == "energy":
            r.world.energy = 9.9 / 30
        elif change == "bar":
            r.state.bar[2], r.state.bar[7] = r.state.bar[7], r.state.bar[2]
        elif change == "map":
            r.state.map += 1
        elif change == "generation":
            r.build._generation += 1
        elif change == "cache":
            r.build._cached_data = SimpleNamespace(account_options=r.cache.account_options)
        elif change == "casting":
            r.state.can_cast = False
        else:
            r.world.health[2] = 0.75

    if stage == "wrapper":
        original: Callable[..., Generator[Any, None, bool]] = r.build.CastSkillIDAndRestoreTarget

        def intercept(skill: int, target: int, **kwargs: Any) -> Generator[Any, None, Any]:
            assert target == 2
            mutate()
            result = yield from original(skill, target, **kwargs)
            return result

        monkeypatch.setattr(r.build, "CastSkillIDAndRestoreTarget", intercept)
    else:

        def target_id() -> int:
            mutate()
            return 20

        monkeypatch.setattr(r.core.Player, "GetTargetID", target_id)
    attempt(r, mode, None)


def test_frame_cache_copies_conditions_and_expires_next_frame(mend_runtime: Any) -> None:
    r = mend_runtime
    r.condition(2, "Poison")
    assert controller.finish(r.mend.try_cast(mode="opportunistic")) is False
    r.condition(2, "Poison", "Burning")
    assert controller.finish(r.mend.try_cast(mode="opportunistic")) is False
    assert r.effect_reads == [2]
    assert len(r.account_reads) == 2  # Health-only and detailed publication snapshots.
    r.frame.reset_cache()
    attempt(r, "opportunistic", 2)
    assert r.effect_reads == [2, 2, 2, 2]  # Next observation and two independent final admissions.


def test_unknown_role_does_not_make_weakness_useful(mend_runtime: Any) -> None:
    r = mend_runtime
    r.weapons[3] = "Unknown"
    r.condition(3, "Weakness", "Poison")
    attempt(r, "opportunistic", None)


def test_remote_snapshot_is_copied_and_final_checks_bypass_cache(
    mend_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = mend_runtime
    r.world.health[2] = 0.50
    account = publication(r, 2, "Dazed", "Poison")
    r.accounts.append(account)
    context = r.mend._context()
    copied = r.mend._publications(context, True)[2]
    assert copied.conditions is None and copied.health == 0.50

    def expire() -> int:
        account.LastUpdated = r.clock - 250
        account.AgentData.Health.Current = 1.0
        account.AgentData.Buffs.Buffs.clear()
        return 20

    monkeypatch.setattr(r.core.Player, "GetTargetID", expire)
    attempt(r, "routine", None)
    assert copied.conditions is None and copied.health == 0.50


def test_publication_changed_during_copy_cannot_authorize_cleansing(mend_runtime: Any) -> None:
    r = mend_runtime
    account = publication(r, 2, "Dazed")

    class ChangingBuffs:
        @property
        def Buffs(self) -> list[Any]:
            account.LastUpdated -= 1
            return [SimpleNamespace(SkillId=r.world.skill_id("Dazed"), Type=2, Duration=20, Remaining=10)]

    account.AgentData.Buffs = ChangingBuffs()
    r.accounts.append(account)
    attempt(r, "urgent", None)


@pytest.mark.parametrize("mode", ["emergency", "urgent", "routine", "preventive", "opportunistic"])
def test_owner_reaches_real_mend_policy_at_approved_opportunity(mend_runtime: Any, mode: str) -> None:
    r = mend_runtime
    r.build.OnContractActivated(r.cache)
    actual: Callable[..., Generator[Any, None, bool]] = r.mend.try_cast
    # Existing trace doubles all skill opportunities; restore MBaS's real policy
    # and dispatch to test the owner boundary without inventing other skills' demand.
    controller.trace_rotation(r.build, r.build.skillbook, None)
    modes: list[str] = []

    def record(*, mode: str) -> Generator[Any, None, Any]:
        modes.append(mode)
        result = yield from actual(mode=mode)
        return result

    r.mend.try_cast = record
    r.world.health[2] = {"emergency": 0.20, "routine": 0.60, "preventive": 0.80}.get(mode, 1.0)
    if mode == "urgent":
        r.condition(2, "Dazed")
    elif mode == "opportunistic":
        r.condition(2, "Burning", "Poison")
    controller.finish(r.build.ProcessSkillCasting())
    assert r.build.DidTickSucceed()
    order = ["emergency", "urgent", "routine", "preventive", "opportunistic"]
    assert modes == order[: order.index(mode) + 1]
    assert r.world.submissions == [(3, 2, 250)]
    assert r.build.ResolveFallback() is None
    assert r.cache.combat_handler.blocked_skill_ids == set(controller.IDS)


@pytest.mark.parametrize("change", ["unchanged", "bar", "dispose", "map"])
def test_mend_suspended_restore_stays_with_owner(
    mend_runtime: Any, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    r = mend_runtime
    r.build.OnContractActivated(r.cache)
    r.world.health[2] = 0.2
    events: list[str] = []

    def restore(_target: int) -> Generator[None, None, None]:
        yield
        events.append("restored")

    def local() -> Generator[Any, None, Any]:
        attempt: Generator[Any, None, bool] = r.mend.try_cast(mode="emergency")
        return (yield from attempt)

    monkeypatch.setattr(r.build, "RestoreEnemyTarget", restore)
    r.build.SetSkillCastingFn(local)
    coroutine = r.build.ProcessSkillCasting()
    next(coroutine)
    assert r.world.submissions == [(3, 2, 250)]
    if change == "bar":
        r.state.bar[2], r.state.bar[7] = r.state.bar[7], r.state.bar[2]
    elif change == "dispose":
        r.build.Dispose()
    elif change == "map":
        r.state.map += 1
    controller.finish(coroutine)
    assert events == (["restored"] if change == "unchanged" else [])
    assert r.world.submissions == [(3, 2, 250)]


@pytest.mark.parametrize("reverse", [False, True])
def test_collection_order_is_independent(reverse: bool) -> None:
    cases = [
        "tests/test_smart_mend_body_and_soul.py::test_emergency_health_wins_over_condition_preference",
        "tests/test_my_blood_is_power.py::test_real_registry_selection_and_cached_instance",
        "tests/test_restoration_spirit_admission.py::test_spirit_range_through_helper_and_shared_admission",
    ]
    if reverse:
        cases.reverse()
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *cases, "--tb=short"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, f"Collection order: {cases}\n{result.stdout}\n{result.stderr}"
