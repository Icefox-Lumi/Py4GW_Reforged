"""Stock restoration and owner-bound Spirit Transfer, through production casting."""

from __future__ import annotations

import importlib
import subprocess
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

controller: Any = importlib.import_module("test_my_blood_is_power")
world = controller.world
runtime = controller.runtime
bip_runtime = controller.bip_runtime
target_bip_runtime = controller.target_bip_runtime
ROOT = Path(__file__).resolve().parents[1]
TRANSFER = 962


@pytest.fixture(autouse=True)
def spirit_models(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def native_skill(name: str) -> SimpleNamespace:
        return SimpleNamespace(id=SimpleNamespace(id=runtime.world.skill_id(name)))

    controller.admission._module(monkeypatch, "PySkill", Skill=native_skill)
    models = controller.admission._load(monkeypatch, "_transfer_models", "Py4GWCoreLib/enums_src/Model_enums.py")
    runtime.core.SpiritModelID = models.SpiritModelID


@pytest.fixture(scope="module")
def before_sources() -> dict[str, str]:
    revision = "6306a9a34e6734bed7a2f10f50a128e0885f39d0"
    paths = {
        "manager": "Py4GWCoreLib/BuildMgr.py",
        "owner": "Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py",
    }
    return {
        key: subprocess.check_output(
            ["git", "--no-optional-locks", "show", f"{revision}:{path}"], cwd=ROOT, text=True, encoding="utf-8"
        )
        for key, path in paths.items()
    }


@pytest.fixture
def transfer_runtime(target_bip_runtime: Any, before_sources: dict[str, str]) -> Any:
    r = target_bip_runtime
    manager: dict[str, Any] = {"__name__": "_pre_spirit_manager"}
    exec(compile(before_sources["manager"], "pre_spirit_BuildMgr.py", "exec"), manager)
    # Bind the pinned controller to its pinned manager, retaining both real
    # production admission paths while native inputs/dispatch stay offline.
    source = before_sources["owner"]
    import_line = "from Py4GWCoreLib import BuildMgr\n"
    assert source.count(import_line) == 1
    owner: dict[str, Any] = {"__name__": "_pre_spirit_owner", "BuildMgr": manager["BuildMgr"]}
    exec(compile(source.replace(import_line, ""), "pre_spirit_owner.py", "exec"), owner)
    r.Before = owner["MyBloodIsPower"]
    r.energy[1] = 1.0
    r.world.health.update({1: 0.8, 2: 0.2, 3: 0.8, 4: 0.8})
    return r


@pytest.mark.parametrize(
    "scenario",
    [
        "earshot",
        "casting_range",
        "boundary",
        "outside",
        "absent",
        "pet",
        "invalid",
        "dead",
        "energy",
        "recharge",
        "toggle",
        "pending",
        "missing",
        "moved",
        "self",
        "recipient_outside",
        "emergency_below",
        "emergency_equal",
        "ordinary_below",
        "ordinary_equal",
        "metadata_threshold",
    ],
)
def test_pinned_behavior_parity_through_real_submission(transfer_runtime: Any, scenario: str) -> None:
    r = transfer_runtime
    r.world.place(10, {"earshot": 500, "boundary": 1248, "outside": 1248.01}.get(scenario, 1100))
    threshold: float | None = None
    if scenario == "absent":
        r.world.spirits.clear()
    elif scenario == "pet":
        r.world.spawned.clear()
    elif scenario == "invalid":
        r.world.valid.remove(10)
    elif scenario == "dead":
        r.world.dead.add(10)
    elif scenario == "energy":
        r.world.energy = 0.1
    elif scenario == "recharge":
        r.world.recharge = 1
    elif scenario == "toggle":
        r.cache.account_options.Skills[1] = False
    elif scenario == "missing":
        r.state.bar[1] = 0
    elif scenario == "moved":
        r.state.bar[1], r.state.bar[7] = r.state.bar[7], r.state.bar[1]
    elif scenario == "self":
        r.world.health[1] = 0.1
    elif scenario == "recipient_outside":
        r.world.place(2, 1248.01)
    elif scenario.startswith("emergency"):
        threshold = 0.30
        r.world.health[2] = 0.2999 if scenario.endswith("below") else 0.30
    elif scenario.startswith("ordinary"):
        r.world.health[2] = 0.4999 if scenario.endswith("below") else 0.50

    observed: list[Any] = []
    for kind in (r.Before, r.Custom):
        build = kind(cached_data=r.cache)
        if scenario == "pending":
            build._mark_local_cast_pending(250)
        if scenario == "metadata_threshold":
            build.GetCustomSkill(TRANSFER).Conditions.LessLife = 0.15
        events: list[tuple[str, int]] = []

        def submission(event: str, target: int) -> None:
            events.append((event, target))

        diagnostic = SimpleNamespace(submission=submission)
        if kind is r.Before:
            component = build.skillbook.Ritualist.RestorationMagic
            attempt = component.Spirit_Transfer
        else:
            component = build._smart_spirit_transfer
            attempt = component.try_cast
        component.bip_diagnostic = diagnostic
        r.world.submissions.clear()
        r.trace.clear()
        r.target = 20
        result = controller.finish(attempt(health_threshold=threshold))
        duplicate = controller.finish(attempt(health_threshold=threshold))
        observed.append((result, duplicate, list(r.world.submissions), list(r.trace), events, r.target))
    assert observed[0] == observed[1], (scenario, observed)
    allowed = scenario in {"earshot", "casting_range", "boundary", "moved", "self", "emergency_below", "ordinary_below"}
    result, duplicate, submissions, _, events, target = observed[1]
    expected_target = 1 if scenario == "self" else 2
    expected_slot = 8 if scenario == "moved" else 2
    assert result is allowed and duplicate is False, (scenario, observed)
    assert submissions == ([(expected_slot, expected_target, 250)] if allowed else []), (scenario, observed)
    assert events == ([("heal", expected_target)] if allowed else []), (scenario, observed)
    assert target == 20, (scenario, observed)


@pytest.mark.parametrize("stage", ["selection", "first_admission"])
def test_donor_loss_revalidated_before_dispatch(runtime: Any, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    r = runtime
    build = r.Custom(cached_data=r.cache)
    r.world.place(10, 1100)
    if stage == "selection":
        original = build.ResolvePreferredAllyTarget

        def select(*args: Any, **kwargs: Any) -> int:
            target: int = original(*args, **kwargs)
            r.world.dead.add(10)
            return target

        monkeypatch.setattr(build, "ResolvePreferredAllyTarget", select)
    else:
        # GetTargetID is between the wrapper's admission and CastSkillID's
        # admission. Only the native observation boundary changes here.
        def target_id() -> int:
            r.world.dead.add(10)
            return 0

        r.core.Player.GetTargetID = target_id
    assert controller.finish(build._smart_spirit_transfer.try_cast()) is False
    assert not r.world.submissions and build._local_cast_timer.IsStopped()


def test_real_metadata_registry_isolation(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    r = runtime
    load = controller.admission._load
    for profession in ("warrior", "ranger", "monk", "mesmer", "elementalist", "assassin", "paragon", "dervish", "pve"):
        load(
            monkeypatch,
            "Py4GWCoreLib.HeroAI.custom_skill_src." + profession,
            "Py4GWCoreLib/HeroAI/custom_skill_src/" + profession + ".py",
        )
    load(monkeypatch, "Py4GWCoreLib.HeroAI.custom_skill", "Py4GWCoreLib/HeroAI/custom_skill.py")
    before = r.Generic()
    original = before.GetCustomSkill(TRANSFER)
    smart = r.Custom()
    after = r.Generic()
    assert original.Conditions.RequiresSpiritInEarshot
    assert after.GetCustomSkill(TRANSFER).Conditions.RequiresSpiritInEarshot
    assert not smart.GetCustomSkill(TRANSFER).Conditions.RequiresSpiritInEarshot
    assert smart.GetCustomSkill(TRANSFER) is not original
    assert smart.GetCustomSkill(TRANSFER).Conditions is not original.Conditions
    expected = dict(cast("dict[str, Any]", vars(original.Conditions)))
    expected["RequiresSpiritInEarshot"] = False
    assert vars(smart.GetCustomSkill(TRANSFER).Conditions) == expected
    assert smart.GetCustomSkill(915).Conditions.RequiresSpiritInEarshot
    assert r.Custom(match_only=True)._custom_skill_data_handler is None


@pytest.mark.parametrize("consumer", ["Generic", "Xinrae", "SoS"])
def test_stock_consumers_keep_historical_earshot_limit(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, consumer: str
) -> None:
    r = runtime
    if consumer == "SoS":
        module = controller.admission._load(
            monkeypatch, "_stock_sos", "Py4GWCoreLib/Builds/Ritualist/Rt_Any/SoS Healer.py"
        )
        kind = module.SoS_Healer
    else:
        kind = getattr(r, consumer)
    build = kind()
    build.set_cached_data(r.cache)
    r.world.place(10, 1100)
    assert not build.CanCastSkillID(TRANSFER)
    assert not controller.finish(build.skills.Ritualist.RestorationMagic.Spirit_Transfer())
    assert not r.world.submissions
    r.world.place(10, 500)
    assert controller.finish(build.skills.Ritualist.RestorationMagic.Spirit_Transfer())
    assert r.world.submissions == [(2, 2, 250)]


@pytest.mark.parametrize(
    "guard", ["aggro", "self_energy", "overcast", "enemies", "allies", "spirits", "minions", "weapon", "adrenaline"]
)
def test_other_shared_execution_guards_remain(runtime: Any, guard: str) -> None:
    r = runtime
    build = r.Custom(cached_data=r.cache)
    conditions = build.GetCustomSkill(TRANSFER).Conditions
    r.world.place(10, 1100)

    def zero(_agent: int) -> int:
        return 0

    def weapon(_agent: int) -> tuple[int, str]:
        return 1, "Axe"

    def empty(*_args: Any, **_kwargs: Any) -> list[int]:
        return []

    if guard == "aggro":
        conditions.CloseToAggro = True
        r.state.aggro = False
    elif guard == "self_energy":
        conditions.LessSelfEnergyPercentage = 0.5
    elif guard == "overcast":
        conditions.Overcast = 1
        r.core.Agent.GetOvercast = zero
    elif guard in ("enemies", "allies", "spirits", "minions"):
        field, query = {
            "enemies": ("EnemyCount", "GetFilteredEnemyArray"),
            "allies": ("AlliesInRange", "GetFilteredAllyArray"),
            "spirits": ("SpiritsInRange", "GetFilteredSpiritArray"),
            "minions": ("MinionsInRange", "GetFilteredMinionArray"),
        }[guard]
        setattr(conditions, field, 1)
        setattr(r.core.Routines.Agents, query, empty)
    elif guard == "weapon":
        conditions.RequireWeapon = "Staff"
        r.core.Agent.GetWeaponType = weapon
    else:
        r.world.adrenaline = False
    assert not controller.finish(build._smart_spirit_transfer.try_cast()), guard
    assert not r.world.submissions and build._local_cast_timer.IsStopped(), guard


@pytest.mark.parametrize("change", ["same", "map", "character", "slots", "removed", "cache", "dispose", "invalid"])
def test_suspended_smart_transfer_uses_owner_lifecycle(target_bip_runtime: Any, change: str) -> None:
    r = target_bip_runtime
    r.world.health[2] = 0.2
    r.world.place(10, 1100)
    restored: list[int] = []

    def restore(target: int) -> Generator[None, None, None]:
        yield
        restored.append(target)

    r.core.Routines.Yield.Agents.ChangeTarget = restore
    build = r.Custom(cached_data=r.cache)
    build.OnContractActivated()
    component = build._smart_spirit_transfer
    build.SetSkillCastingFn(component.try_cast)
    coroutine = build.ProcessSkillCasting()
    next(coroutine)
    assert r.world.submissions == [(2, 2, 250)]
    assert build.ResolveFallback() is None
    if change == "map":
        r.state.map += 1
    elif change == "character":
        r.state.name = "Other character"
    elif change == "slots":
        r.state.bar.reverse()
    elif change == "removed":
        r.state.bar[1] = 0
    elif change == "cache":
        build.set_cached_data(SimpleNamespace(combat_handler=type(r.cache.combat_handler)()))
    elif change == "dispose":
        build.Dispose()
    elif change == "invalid":
        r.state.valid = False
    controller.finish(coroutine)
    assert restored == ([20] if change == "same" else []), change
    assert r.world.submissions == [(2, 2, 250)], change
    assert build._smart_spirit_transfer is component


def test_stock_pet_gate_and_genuine_helper_requirement_are_independent(runtime: Any) -> None:
    r = runtime
    build = r.Generic()
    build.set_cached_data(r.cache)
    r.world.place(10, 1100)
    r.world.pets.append(11)
    r.world.valid.add(11)
    r.world.health[11] = 1.0
    r.world.place(11, 100)
    assert build.CanCastSkillID(TRANSFER) and build.CanCastSkillSlot(2)
    assert controller.finish(build.skills.Ritualist.RestorationMagic.Spirit_Transfer())
    assert r.world.submissions == [(2, 2, 250)]


@pytest.mark.parametrize("by_slot", [False, True])
def test_generic_direct_submission_restores_historical_pet_acceptance(runtime: Any, by_slot: bool) -> None:
    r = runtime
    build = r.Generic()
    build.set_cached_data(r.cache)
    r.world.spawned.clear()
    attempt = (
        build.CastSkillSlot(2, target_agent_id=2, aftercast_delay=250, log=False)
        if by_slot
        else build.CastSkillIDAndRestoreTarget(TRANSFER, 2)
    )
    assert controller.finish(attempt)
    assert r.world.submissions == [(2, 2, 250)]
