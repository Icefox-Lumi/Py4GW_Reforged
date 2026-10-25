"""Committed My BiP parity and historical stock Spirit Light submission paths."""

from __future__ import annotations

import importlib
import subprocess
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

controller: Any = importlib.import_module("test_my_blood_is_power")
transfer: Any = importlib.import_module("test_smart_spirit_transfer")
world = controller.world
runtime = controller.runtime
bip_runtime = controller.bip_runtime
target_bip_runtime = controller.target_bip_runtime
spirit_runtime = controller.spirit_runtime
capture_runtime = controller.capture_runtime
capture_actions = controller.capture_actions
spirit_models = transfer.spirit_models
ROOT = Path(__file__).resolve().parents[1]
LIGHT = 915


@pytest.fixture(scope="module")
def before_sources() -> dict[str, str]:
    head = "f1406579f4fd19c0b6de21280b8c8cea25845bd3"
    revisions = {
        "manager": f"{head}:Py4GWCoreLib/BuildMgr.py",
        "owner": f"{head}:Py4GWCoreLib/Builds/Necromancer/N_Rt/My Blood is Power.py",
        "historical_manager": "423fda782b5240e25633a83115712d919fa636bd^:Py4GWCoreLib/BuildMgr.py",
    }
    return {
        name: subprocess.check_output(
            ["git", "--no-optional-locks", "show", revision], cwd=ROOT, text=True, encoding="utf-8"
        )
        for name, revision in revisions.items()
    }


@pytest.fixture
def prior_types(runtime: Any, before_sources: dict[str, str]) -> SimpleNamespace:
    manager: dict[str, Any] = {"__name__": "_pre_light_manager"}
    exec(compile(before_sources["manager"], "pre_light_BuildMgr.py", "exec"), manager)
    # Use the committed manager as well as the committed controller: the gate
    # being removed is part of the baseline's observable behavior.
    source = before_sources["owner"]
    import_line = "from Py4GWCoreLib import BuildMgr\n"
    assert source.count(import_line) == 1
    owner: dict[str, Any] = {"__name__": "_pre_light_owner", "BuildMgr": manager["BuildMgr"]}
    exec(compile(source.replace(import_line, ""), "pre_light_owner.py", "exec"), owner)
    historical: dict[str, Any] = {"__name__": "_historical_light_manager"}
    exec(compile(before_sources["historical_manager"], "historical_light_BuildMgr.py", "exec"), historical)
    return SimpleNamespace(Owner=owner["MyBloodIsPower"], Historical=historical["BuildMgr"])


@pytest.fixture
def light_runtime(target_bip_runtime: Any, prior_types: SimpleNamespace) -> Any:
    r = target_bip_runtime
    r.Before = prior_types.Owner
    r.world.health.update({1: 0.8, 2: 0.2, 3: 0.8, 4: 0.8})
    r.world.place(10, 500)
    return r


@pytest.mark.parametrize(
    "case",
    [
        "genuine",
        "boundary",
        "outside",
        "absent",
        "pet",
        "unspawned",
        "dead",
        "invalid",
        "low_self_genuine",
        "low_self_pet",
        "high_self_pet",
        "self",
        "lowest_ally",
        "recipient_boundary",
        "recipient_outside",
        "emergency_below",
        "emergency_equal",
        "ordinary_below",
        "ordinary_equal",
        "metadata_threshold",
        "metadata_default",
        "energy",
        "recharge",
        "toggle",
        "pending",
        "missing",
        "moved",
    ],
)
def test_committed_admission_target_and_submission_parity(light_runtime: Any, case: str) -> None:
    r = light_runtime
    threshold: float | None = None
    r.world.place(10, {"boundary": 1012, "outside": 1012.01}.get(case, 500))
    if case == "absent":
        r.world.spirits.clear()
    elif case in ("pet", "low_self_pet", "high_self_pet"):
        r.world.spirits.clear()
        r.world.pets.append(10)
        r.world.spawned.clear()
    elif case == "unspawned":
        r.world.spawned.clear()
    elif case == "dead":
        r.world.dead.add(10)
    elif case == "invalid":
        r.world.valid.remove(10)
    elif case == "lowest_ally":
        r.world.health[3] = 0.1
    elif case.startswith("recipient_"):
        r.world.place(2, 1248 if case.endswith("boundary") else 1248.01)
    elif case.startswith("emergency_"):
        threshold = 0.30
        r.world.health[2] = 0.2999 if case.endswith("below") else 0.30
    elif case.startswith("ordinary_"):
        r.world.health[2] = 0.5999 if case.endswith("below") else 0.60
    elif case == "energy":
        r.world.energy = 0.1
    elif case == "recharge":
        r.world.recharge = 1
    elif case == "toggle":
        r.cache.account_options.Skills[3] = False
    elif case == "missing":
        r.state.bar[3] = 0
    elif case == "moved":
        r.state.bar[3], r.state.bar[7] = r.state.bar[7], r.state.bar[3]
    if case in ("self", "low_self_genuine", "low_self_pet"):
        r.world.health[1] = 0.1
    elif case == "high_self_pet":
        r.world.health[1] = 1.0

    results: list[Any] = []
    for kind in (r.Before, r.Custom):
        build = kind(cached_data=r.cache)
        if case == "pending":
            build._mark_local_cast_pending(250)
        if case in ("metadata_threshold", "metadata_default"):
            build.GetCustomSkill(LIGHT).Conditions.LessLife = 0.15 if case == "metadata_threshold" else 0.0
        component = build.skillbook.Ritualist.RestorationMagic if kind is r.Before else build._smart_spirit_light
        attempt = component.Spirit_Light if kind is r.Before else component.try_cast
        events: list[tuple[str, int]] = []

        def submission(event: str, target: int) -> None:
            events.append((event, target))

        component.bip_diagnostic = SimpleNamespace(submission=submission)
        r.world.submissions.clear()
        r.trace.clear()
        r.target = 20
        accepted = controller.finish(attempt(health_threshold=threshold))
        duplicate = controller.finish(attempt(health_threshold=threshold))
        actions = [event for event in r.trace if event[0] in ("submit", "restore")]
        results.append((accepted, duplicate, list(r.world.submissions), actions, events, r.target))
        assert build.GetCustomSkill(LIGHT).Conditions.RequiresSpiritInEarshot
    assert results[0] == results[1], (case, results)
    allowed = case in {
        "genuine",
        "boundary",
        "low_self_genuine",
        "self",
        "lowest_ally",
        "recipient_boundary",
        "emergency_below",
        "ordinary_below",
        "metadata_default",
        "moved",
    }
    target = 1 if case in ("self", "low_self_genuine") else 3 if case == "lowest_ally" else 2
    slot = 8 if case == "moved" else 4
    assert results[1][0] is allowed and results[1][1] is False, (case, results)
    assert results[1][2] == ([(slot, target, 250)] if allowed else []), (case, results)
    assert results[1][4] == ([("heal", target)] if allowed else []), (case, results)
    assert results[1][5] == 20, (case, results)


@pytest.mark.parametrize("stage", ["selection", "wrapper_admission"])
@pytest.mark.parametrize("loss", ["dead", "invalid", "outside", "absent"])
@pytest.mark.parametrize("pet", [False, True])
@pytest.mark.parametrize("recipient", [1, 2], ids=["self", "other"])
def test_spirit_loss_rejects_both_committed_and_smart_paths(
    light_runtime: Any, monkeypatch: pytest.MonkeyPatch, stage: str, loss: str, pet: bool, recipient: int
) -> None:
    r = light_runtime
    r.world.health.update({1: 0.4 if recipient == 1 else 0.8, 2: 0.8 if recipient == 1 else 0.2})
    if pet:
        r.world.pets.append(11)
        r.world.valid.add(11)
        r.world.health[11] = 1.0
        r.world.place(11, 100)
    for kind in (r.Before, r.Custom):
        r.world.spirits = [10]
        r.world.dead.discard(10)
        r.world.valid.add(10)
        r.world.place(10, 500)
        build = kind(cached_data=r.cache)
        reached: list[str] = []

        def lose_spirit() -> None:
            reached.append(stage)
            if loss == "dead":
                r.world.dead.add(10)
            elif loss == "invalid":
                r.world.valid.remove(10)
            elif loss == "outside":
                r.world.place(10, 1012.01)
            else:
                r.world.spirits.clear()

        with monkeypatch.context() as patch:
            if stage == "selection":
                original = build.ResolvePreferredAllyTarget

                def select(*args: Any, **kwargs: Any) -> int:
                    target: int = original(*args, **kwargs)
                    assert target == recipient
                    lose_spirit()
                    return target

                patch.setattr(build, "ResolvePreferredAllyTarget", select)
            else:

                def target_id() -> int:
                    lose_spirit()
                    return 20

                patch.setattr(r.core.Player, "GetTargetID", target_id)
            attempt = (
                build.skillbook.Ritualist.RestorationMagic.Spirit_Light
                if kind is r.Before
                else build._smart_spirit_light.try_cast
            )
            assert controller.finish(attempt()) is False, (stage, loss, pet, kind)
        assert reached == [stage] and not r.world.submissions, (stage, loss, pet, kind)
        assert build._local_cast_timer.IsStopped()


@pytest.mark.parametrize("kind", ["genuine", "pet", "unspawned", "absent", "dead", "invalid"])
@pytest.mark.parametrize("self_hp", [0.1, 0.30, 0.3001, 0.8])
def test_stock_helper_matches_historical_admission_and_sacrifice_policy(
    runtime: Any, prior_types: SimpleNamespace, kind: str, self_hp: float
) -> None:
    r = runtime
    r.world.health.update({1: self_hp, 2: 0.2})
    if kind == "pet":
        r.world.spirits.clear()
        r.world.pets.append(10)
        r.world.spawned.clear()
    elif kind == "unspawned":
        r.world.spawned.clear()
    elif kind == "absent":
        r.world.spirits.clear()
    elif kind == "dead":
        r.world.dead.add(10)
    elif kind == "invalid":
        r.world.valid.remove(10)
    results: list[Any] = []
    for build in (prior_types.Historical(), r.Generic()):
        build.set_cached_data(r.cache)
        helper = type(r.world.helper)(build)
        admission = (build.CanCastSkillID(LIGHT), build.CanCastSkillSlot(4))
        r.world.submissions.clear()
        accepted = controller.finish(helper.Spirit_Light())
        results.append((admission, accepted, list(r.world.submissions)))
    assert results[0] == results[1], (kind, self_hp, results)
    admitted = kind in ("genuine", "pet", "unspawned")
    accepted = kind == "genuine" or (kind in ("pet", "unspawned") and self_hp > 0.30)
    target = 1 if kind == "genuine" and self_hp < 0.2 else 2
    assert results[1] == ((admitted, admitted), accepted, [(4, target, 250)] if accepted else []), results
    assert r.world.health[1] == self_hp, "Offline submission does not prove sacrifice or healing."


@pytest.mark.parametrize("consumer", ["Generic", "Xinrae", "SoS"])
@pytest.mark.parametrize("only_self", [False, True])
def test_stock_consumers_can_use_pet_supported_other_ally_fallback(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, consumer: str, only_self: bool
) -> None:
    r = runtime
    if consumer == "SoS":
        module = controller.admission._load(
            monkeypatch, "_light_stock_sos", "Py4GWCoreLib/Builds/Ritualist/Rt_Any/SoS Healer.py"
        )
        kind = module.SoS_Healer
    else:
        kind = getattr(r, consumer)
    r.world.spirits.clear()
    r.world.pets.append(10)
    r.world.spawned.clear()
    r.world.health[1] = 0.4
    if only_self:
        r.world.allies = [1]
    build = kind()
    build.set_cached_data(r.cache)
    assert controller.finish(build.skills.Ritualist.RestorationMagic.Spirit_Light()) is (not only_self)
    assert r.world.submissions == ([] if only_self else [(4, 2, 250)])


@pytest.mark.parametrize("change", ["same", "map", "character", "slots", "removed", "cache", "dispose", "invalid"])
def test_smart_light_suspension_stays_under_owner_lifecycle(light_runtime: Any, change: str) -> None:
    r = light_runtime
    restored: list[int] = []

    def restore(target: int) -> Generator[None, None, None]:
        yield
        restored.append(target)

    r.core.Routines.Yield.Agents.ChangeTarget = restore
    build = r.Custom(cached_data=r.cache)
    build.OnContractActivated()
    component = build._smart_spirit_light
    build.SetSkillCastingFn(component.try_cast)
    coroutine = build.ProcessSkillCasting()
    next(coroutine)
    assert r.world.submissions == [(4, 2, 250)] and build.ResolveFallback() is None
    if change == "map":
        r.state.map += 1
    elif change == "character":
        r.state.name = "Other character"
    elif change == "slots":
        r.state.bar.reverse()
    elif change == "removed":
        r.state.bar[3] = 0
    elif change == "cache":
        build.set_cached_data(SimpleNamespace(combat_handler=type(r.cache.combat_handler)()))
    elif change == "dispose":
        build.Dispose()
    elif change == "invalid":
        r.state.valid = False
    controller.finish(coroutine)
    assert restored == ([20] if change == "same" else []), change
    assert r.world.submissions == [(4, 2, 250)] and build._smart_spirit_light is component
    assert build.GetCustomSkill(LIGHT).Conditions.RequiresSpiritInEarshot


@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("case", ["emergency", "ordinary", "pet_only", "self", "transfer_first"])
def test_complete_rotation_diagnostics_and_pending_match_committed(
    capture_actions: Any, prior_types: SimpleNamespace, case: str, armed: bool
) -> None:
    r = capture_actions
    r.ready = {LIGHT, 962} if case == "transfer_first" else {LIGHT}
    r.world.health[2] = 0.55 if case == "ordinary" else 0.2
    if case == "self":
        r.world.health[1] = 0.1
    elif case == "pet_only":
        r.world.spirits.clear()
        r.world.pets.append(10)
        r.world.spawned.clear()
    outcomes: list[Any] = []
    for kind in (prior_types.Owner, r.Custom):
        r.control.stop_capture()
        r.world.submissions.clear()
        r.posts.clear()
        r.calls.clear()
        controller.Timer.now = 0
        r.now = 0.0
        build = kind(cached_data=r.cache)
        build.OnContractActivated(r.cache)
        capture: Any = r.click("Arm one capture") if armed else None
        controller.finish(build.ProcessSkillCasting())
        controller.finish(build.ProcessSkillCasting())
        outcomes.append(
            (
                list(r.world.submissions),
                list(r.calls),
                build._is_local_cast_pending(),
                (dict(capture.totals), dict(capture.winners)) if armed else None,
            )
        )
        assert r.cache.combat_handler.blocked_skill_ids == set(controller.IDS)
        if armed and kind is r.Custom:
            assert build._smart_spirit_light.bip_diagnostic is capture
            build.Dispose()
            assert build._smart_spirit_light.bip_diagnostic is None
            assert build._smart_spirit_transfer.bip_diagnostic is None
            assert build._smart_kaolai.bip_diagnostic is None and capture.done
    assert outcomes[0] == outcomes[1], (case, armed, outcomes)
    expected = [] if case == "pet_only" else [(2 if case == "transfer_first" else 4, 1 if case == "self" else 2, 250)]
    assert outcomes[1][0] == expected, (case, armed, outcomes)
    assert bool(outcomes[1][1]) is (case == "pet_only"), (case, armed, outcomes)


def test_light_component_keeps_metadata_and_matching_untouched(runtime: Any) -> None:
    r = runtime
    candidate = r.Custom(match_only=True)
    assert candidate._custom_skill_data_handler is None and not hasattr(candidate, "_smart_spirit_light")
    generic, smart = r.Generic(), r.Custom()
    stock, custom = generic.GetCustomSkill(LIGHT), smart.GetCustomSkill(LIGHT)
    assert vars(stock.Conditions) == vars(custom.Conditions)
    assert custom.Conditions.RequiresSpiritInEarshot and custom.Conditions.SacrificeHealth == 0.30
    assert vars(smart._smart_spirit_light) == {"build": smart, "bip_diagnostic": None}


@pytest.mark.parametrize(
    "guard", ["aggro", "self_energy", "overcast", "enemies", "allies", "spirits", "minions", "weapon", "adrenaline"]
)
def test_smart_light_preserves_other_shared_gates(runtime: Any, guard: str) -> None:
    r = runtime
    build = r.Custom(cached_data=r.cache)
    conditions = build.GetCustomSkill(LIGHT).Conditions

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
    assert controller.finish(build._smart_spirit_light.try_cast()) is False, guard
    assert not r.world.submissions and build._local_cast_timer.IsStopped(), guard


@pytest.mark.parametrize("change", ["map", "character", "cache", "invalid", "dispose"])
def test_smart_light_diagnostic_reference_is_cleared_with_owner(capture_actions: Any, change: str) -> None:
    r = capture_actions
    r.ready = {LIGHT}
    r.world.health[2] = 0.2
    build = r.selected
    capture = r.click("Arm one capture")
    controller.finish(build.ProcessSkillCasting())
    assert build._smart_spirit_light.bip_diagnostic is capture
    assert capture.winners == {"Spirit_Light": 1} and r.world.submissions == [(4, 2, 250)]
    if change == "map":
        r.state.map += 1
    elif change == "character":
        r.state.name = "Other character"
    elif change == "cache":
        build.set_cached_data(SimpleNamespace(combat_handler=type(r.cache.combat_handler)()))
    elif change == "invalid":
        r.state.valid = False
    else:
        build.Dispose()
    build._sync_context()
    assert capture.done and build._bip_diagnostic is None, change
    assert build._smart_spirit_light.bip_diagnostic is None, change
    assert build._smart_spirit_transfer.bip_diagnostic is None, change
    assert build._smart_kaolai.bip_diagnostic is None, change


@pytest.mark.parametrize("self_hp", [0.1, 0.30, 0.3001, 0.4])
def test_stock_spirit_loss_can_admit_an_already_selected_self_target(
    runtime: Any, prior_types: SimpleNamespace, self_hp: float
) -> None:
    r = runtime
    r.world.health.update({1: self_hp, 2: 0.8, 11: 1.0})
    r.world.pets.append(11)
    r.world.valid.add(11)
    r.world.place(11, 100)
    results: list[Any] = []
    for build in (prior_types.Historical(), r.Generic()):
        r.world.spirits = [10]
        r.world.submissions.clear()
        build.set_cached_data(r.cache)

        def target_id() -> int:
            r.world.spirits.clear()
            return 0

        r.core.Player.GetTargetID = target_id
        accepted = controller.finish(type(r.world.helper)(build).Spirit_Light())
        results.append((accepted, list(r.world.submissions)))
    expected = (self_hp > 0.30, [(4, 1, 250)] if self_hp > 0.30 else [])
    assert results == [expected, expected], (self_hp, results)


@pytest.mark.parametrize("change", ["missing", "moved", "moved_disabled"])
def test_final_admission_uses_current_slot_and_toggle(light_runtime: Any, change: str) -> None:
    r = light_runtime
    for kind in (r.Before, r.Custom):
        r.state.bar = controller.IDS.copy()
        r.cache.account_options.Skills = [True] * 8
        r.world.submissions.clear()
        build = kind(cached_data=r.cache)

        def target_id() -> int:
            if change == "missing":
                r.state.bar[3] = 0
            else:
                r.state.bar[3], r.state.bar[7] = r.state.bar[7], r.state.bar[3]
                r.cache.account_options.Skills[7] = change != "moved_disabled"
            return 0

        r.core.Player.GetTargetID = target_id
        attempt = (
            build.skillbook.Ritualist.RestorationMagic.Spirit_Light
            if kind is r.Before
            else build._smart_spirit_light.try_cast
        )
        assert controller.finish(attempt()) is (change == "moved"), (change, kind)
        assert r.world.submissions == ([(8, 2, 250)] if change == "moved" else []), (change, kind)
