"""Console evidence and noninterference through the existing native-free HR world."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import re
import sys
from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Sequence
from dataclasses import asdict
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
from test_restoration_spirit_admission import world as _admission_fixture
from test_smart_heroic_refrain import FGJ
from test_smart_heroic_refrain import MYT
from test_smart_heroic_refrain import SY
from test_smart_heroic_refrain import HeroicRefrainWorld as _World
from test_smart_heroic_refrain import admission_world as admission_world
from test_smart_heroic_refrain import (
    test_native_acceptance_alone_and_late_resource_are_not_success as _timeout,
)
from test_smart_heroic_refrain import (
    test_nontrio_stock_call_order_is_unchanged as _stock_order,
)
from test_smart_heroic_refrain import (
    test_normal_reset_completion_and_rapid_reenable as _invalidation,
)
from test_smart_heroic_refrain import (
    test_partial_myt_latch_and_independent_fgj as _partial_myt,
)
from test_smart_heroic_refrain import (
    test_queued_reservation_covers_actual_phase_and_fallback as _fallback,
)
from test_smart_heroic_refrain import (
    test_repeated_protection_cycles_use_all_three_and_retain_resource_gap as _cycles,
)
from test_smart_heroic_refrain import (
    test_stock_hr_bootstrap_spread_recovery_and_ooc_upkeep as _upkeep,
)
from test_smart_heroic_refrain import world as world


def _reload_virtual_on(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    name = "Py4GWCoreLib.Builds.Skills.SmartSaveYourselves"
    path = Path(__file__).resolve().parents[1] / "Py4GWCoreLib/Builds/Skills/SmartSaveYourselves.py"
    source = path.read_text(encoding="utf-8")
    assert source.count("_DIAGNOSTIC_ARM_ONCE = False") == 1
    virtual = source.replace("_DIAGNOSTIC_ARM_ONCE = False", "_DIAGNOSTIC_ARM_ONCE = True", 1)

    class VirtualLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(
            self, fullname: str, path: Sequence[str] | None, target: ModuleType | None = None
        ) -> ModuleSpec | None:
            return importlib.util.spec_from_loader(fullname, self) if fullname == name else None

        def create_module(self, spec: ModuleSpec) -> ModuleType | None:
            return None

        def exec_module(self, module: ModuleType) -> None:
            exec(compile(virtual, str(path), "exec"), module.__dict__)

    monkeypatch.setattr(sys, "meta_path", [VirtualLoader(), *sys.meta_path])
    original = sys.modules[name]
    reloaded = importlib.reload(original)
    assert reloaded is original, "Exercise real reload and the old methods' shared module globals"
    return reloaded


def _replace_selected_owner(w: _World) -> Any:
    old = w.owner
    new = w.stock_module.Paragon_Refrain()
    new._custom_skill_data_handler = old._custom_skill_data_handler
    new.ResolveAllyTarget = old.ResolveAllyTarget
    new.RestoreEnemyTarget = old.RestoreEnemyTarget
    new.AutoAttack = old.AutoAttack
    w.driver._build_registry._cached_runtime_matchable_builds = [new]
    w.driver._contract_signature = None
    assert w.driver.EnsureBuildContract() is new
    w.owner, w.policy = new, new.heroic_refrain_policy
    return new


def _normal_owner_entry(w: _World, *, combat: bool = False) -> None:
    """Use the actual selected-contract dispatcher and normal OOC owner seam."""
    from test_restoration_spirit_admission import finish_coroutine

    assert w.driver.GetBuildContract() is w.owner
    previous = w.owner.current_fallback_handler

    def apply_blocked(skills: list[int]) -> None:
        pass

    def idle() -> Iterator[None]:
        return iter(())

    w.owner.current_fallback_handler = SimpleNamespace(
        ApplyBlockedSkillIDs=apply_blocked, ProcessOOC=idle, ProcessCombat=idle
    )
    try:
        finish_coroutine(w.driver._run_contract(w.owner._cached_data, is_in_combat=combat))
    finally:
        w.owner.current_fallback_handler = previous


def test_reload_revoked_callback_cannot_steal_selected_arm(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    output: list[str] = []

    def log(sender: str, message: str) -> None:
        output.append(message)

    world.core.ConsoleLog = log
    world.pressure()
    assert world.policy.TryCast()
    old = world.owner
    generation = old.GetPolicyGeneration()
    selected = _replace_selected_owner(world)
    assert old.GetPolicyGeneration() > generation
    module = _reload_virtual_on(monkeypatch)
    world.dispatch()
    assert old.heroic_refrain_policy.last_outcome == "context_cancelled"
    assert world.calls == []
    assert old.heroic_refrain_policy._capture is None, "Revoked callback must not acquire the new module-lifetime arm"
    assert not module.__dict__["_diagnostic_consumed"]
    _normal_owner_entry(world)
    assert selected.heroic_refrain_policy._capture.state == "ARMED"
    assert module.__dict__["_diagnostic_consumed"]
    assert sum(" ARMED " in line for line in output) == 1


@pytest.mark.parametrize("capturing", [False, True])
def test_backward_clock_terminates_with_unknown_timing(world: _World, capturing: bool) -> None:
    output = _enable(world)
    _normal_owner_entry(world)
    if capturing:
        world.pressure()
    capture = world.policy._capture
    counts = dict(capture.counts)
    world.now -= 1000
    world.policy.Advance()
    assert capture.stop_reason == "clock_discontinuity", output
    assert not capture.active
    assert capture.counts == counts
    terminal = output[-3:]
    assert any("capture_ms=unknown" in line and "last_coverage_observation_ms=unknown" in line for line in terminal)
    assert any("unobserved_ms=unknown" in line for line in terminal)
    assert all(line.startswith("t=unknown ") for line in terminal)
    assert not any(re.search(r"(?:_ms|elapsed_ms)=-\d", line) for line in terminal)
    assert sum(" SUMMARY " in line for line in output) == 1


@pytest.mark.parametrize("combat", [False, True])
def test_only_selected_normal_entry_can_acquire_unclaimed_arm(world: _World, combat: bool) -> None:
    output = _enable(world, enter=False)
    world.stock_module.Paragon_Refrain(match_only=True)
    unselected = world.stock_module.Paragon_Refrain()
    unselected.set_cached_data(world.owner._cached_data)
    unselected.heroic_refrain_policy.Advance()
    world.policy.Advance()
    assert output == []
    assert world.policy._capture is None and unselected.heroic_refrain_policy._capture is None
    _normal_owner_entry(world, combat=combat)
    assert world.policy._capture.state == "ARMED"
    assert not world.policy._pressure
    _normal_owner_entry(world, combat=combat)
    assert sum(" ARMED " in line for line in output) == 1


def test_unselected_same_name_callback_cannot_arm_without_revocation(world: _World) -> None:
    selected = world.owner
    other = world.stock_module.Paragon_Refrain()
    other.set_cached_data(selected._cached_data)
    other._custom_skill_data_handler = selected._custom_skill_data_handler
    other.ResolveAllyTarget = selected.ResolveAllyTarget
    world.policy = other.heroic_refrain_policy
    world.pressure()
    assert world.policy.TryCast()
    assert world.driver.GetBuildContract() is selected
    world.policy = selected.heroic_refrain_policy
    output = _enable(world, enter=False)
    world.dispatch()
    assert other.heroic_refrain_policy.last_outcome == "submitted", "Do not change the existing gameplay guards"
    assert other.heroic_refrain_policy._capture is None and output == []
    _normal_owner_entry(world)
    assert selected.heroic_refrain_policy._capture.state == "ARMED"


@pytest.mark.parametrize("previously_armed", [False, True])
def test_old_callback_cannot_replace_selected_capture_after_reload(
    world: _World, monkeypatch: pytest.MonkeyPatch, previously_armed: bool
) -> None:
    if previously_armed:
        _enable(world)
    world.pressure()
    assert world.policy.TryCast()
    old = world.owner
    _replace_selected_owner(world)
    module = _reload_virtual_on(monkeypatch)
    assert not module.__dict__["_diagnostic_consumed"]
    _normal_owner_entry(world)
    capture = world.policy._capture
    counts = dict(capture.counts)
    world.dispatch()
    assert old.heroic_refrain_policy.last_outcome == "context_cancelled"
    assert world.policy._capture is capture and capture.state == "ARMED"
    assert capture.counts == counts
    assert not world.calls


@pytest.mark.parametrize("drain_before_arm", [False, True])
def test_reload_silences_old_recorder_complete_stream(
    world: _World, monkeypatch: pytest.MonkeyPatch, drain_before_arm: bool
) -> None:
    output = _enable(world)
    world.pressure()
    assert world.policy.TryCast()
    old = world.policy
    retired = old._capture
    assert retired.active and retired.state == "CAPTURING"
    assert any("stage=queued" in line for line in output)
    queued_at = world.now
    _replace_selected_owner(world)
    world.health[2] = 1.0
    world.roster = [1, 2]
    module = _reload_virtual_on(monkeypatch)
    boundary = len(output)
    if drain_before_arm:
        world.dispatch(delay=0)
        assert old.last_outcome == "context_cancelled" and not world.calls
        assert not module.__dict__["_diagnostic_consumed"]
        assert len(output) == boundary, output[boundary:]
    _normal_owner_entry(world)
    current = world.policy._capture
    world.pressure()
    assert world.policy.TryCast()
    counts, labels = dict(current.counts), dict(current.labels)
    before_callback = list(output)
    if not drain_before_arm:
        world.dispatch(delay=50)
        assert world.now - queued_at == 200 < old.QUEUE_MS
        assert old.last_outcome == "context_cancelled" and not world.calls
    assert current.active and world.policy._capture is current
    assert current.counts == counts and current.labels == labels
    assert output == before_callback, output[len(before_callback) :]
    world.dispatch(delay=0)
    assert world.calls == [(SY, 0)] and world.policy.last_outcome == "submitted"
    world.raw[SY] = 0
    world.now += 150
    world.policy.Advance()
    stream = output[boundary:]
    assert not any("context_cancelled" in line or "context_reset" in line or " context " in line for line in stream), (
        "Obsolete recorder interleaved with the new lifetime:\n" + "\n".join(stream)
    )
    for token in (
        " ARMED ",
        " CAPTURING ",
        "decision_payload",
        "stage=queued",
        "stage=native_true",
        "sy_resource_consequence",
    ):
        assert any(token in line for line in stream), (token, stream)
    requests = [line for line in stream if " request " in line or " native " in line]
    assert requests and all("request=1 " in line for line in requests), requests
    assert stream[0].startswith("+0ms ARMED ")
    assert any(line.startswith("+150ms request ") and "stage=queued" in line for line in requests)
    assert current.counts["sy_queued"] == current.counts["sy_native_calls"] == 1
    assert current.counts["sy_observation_success"] == 1
    assert current.labels == {(2, 0): 1}, current.labels
    assert (3, 0) in retired.labels and (3, 0) not in current.labels
    before_finish = list(output)
    retired.finish("late_old_finish")
    assert output == before_finish, "An old final summary must also be silent"
    world.now = current.started + 120000
    world.policy.Advance()
    assert current.stop_reason == "combat_limit"
    assert sum(" SUMMARY " in line for line in output[boundary:]) == 1


@pytest.mark.parametrize("capturing", [False, True])
@pytest.mark.parametrize("operation", ["send", "event", "flush", "finish", "observation"])
def test_reload_silences_every_old_output_boundary(
    world: _World, monkeypatch: pytest.MonkeyPatch, capturing: bool, operation: str
) -> None:
    output = _enable(world)
    if capturing:
        world.pressure()
    old = world.policy
    retired = old._capture
    retired.deferred = True
    retired.event("old_buffered", marker="old_lifetime_only")
    assert retired.pending and retired.active
    _replace_selected_owner(world)
    _reload_virtual_on(monkeypatch)
    _normal_owner_entry(world)
    current = world.policy._capture
    before = list(output)
    old_lines = retired.lines
    counts, labels = dict(current.counts), dict(current.labels)
    attempted: list[str] = []
    original = world.core.ConsoleLog

    def failing_logger(sender: str, message: str) -> None:
        attempted.append(message)
        raise RuntimeError("A stale recorder must never reach this logger")

    world.core.ConsoleLog = failing_logger
    if operation == "send":
        retired.send(world.now, "old_direct", {"marker": "old_lifetime_only"})
    elif operation == "event":
        retired.deferred = False
        retired.event("old_event", marker="old_lifetime_only")
    elif operation == "flush":
        retired.deferred = False
        retired.flush()
    elif operation == "finish":
        retired.stop_requested = "old_pending_stop"
        retired.flush()
        retired.finish("old_finish")
    else:
        old.ObserveStock("AutoAttack", True)
        old._diagnostic_step(world.now + 200000)
    assert attempted == [] and output == before
    assert retired.lines == old_lines and retired.logger_failures == 0
    assert not retired.active and current.active
    assert current.counts == counts and current.labels == labels
    # A real current-lifetime logger fault still belongs only to that recorder.
    world.policy.ObserveStock("AutoAttack", True)
    assert len(attempted) == 1 and current.logger_failures == 1
    assert current.stop_reason == "logger_failure" and not current.active
    assert retired.logger_failures == 0
    world.core.ConsoleLog = original
    _replace_selected_owner(world)
    _normal_owner_entry(world)
    assert world.policy._capture is None and output == before


def test_two_reloads_never_revive_older_callbacks(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _enable(world)
    older: list[Any] = []
    for _ in range(2):
        world.pressure()
        assert world.policy.TryCast()
        older.append(world.policy)
        _replace_selected_owner(world)
        world.health[2] = 1.0
        _reload_virtual_on(monkeypatch)
        _normal_owner_entry(world)
    current = world.policy._capture
    before = list(output)
    counts, labels = dict(current.counts), dict(current.labels)
    for old in older:
        assert world.now - old._request.queued_ms < old.QUEUE_MS
        world.dispatch(delay=0)
        assert old.last_outcome == "context_cancelled"
        old._capture.flush()
        old._capture.finish("old_lifetime_finish")
        old._capture.send(world.now, "old_direct", {})
        assert not old._capture.active
        assert output == before and not world.calls
        assert current.counts == counts and current.labels == labels and current.active
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    assert world.calls == [(SY, 0)]
    world.raw[SY] = 0
    world.now += 150
    world.policy.Advance()
    world.now = current.started + 120000
    world.policy.Advance()
    assert current.stop_reason == "combat_limit"
    assert current.counts["sy_observation_success"] == 1
    assert sum(" SUMMARY " in line for line in output) == 1
    assert sum(" ARMED " in line for line in output) == 3
    _replace_selected_owner(world)
    _normal_owner_entry(world)
    assert world.policy._capture is None
    ended = list(output)
    for old in older:
        old._capture.send(world.now, "old_after_completion", {})
    assert output == ended


@pytest.mark.parametrize("unavailable", ["map", "combat", "cinematic", "party", "no_sy"])
def test_normal_entry_waits_for_existing_runtime_validity(world: _World, unavailable: str) -> None:
    _enable(world, enter=False)
    world.driver._build_registry._cached_runtime_matchable_builds = [world.owner]

    def wait(delay: int) -> Iterator[None]:
        return iter(())

    world.core.Routines.Yield = SimpleNamespace(wait=wait)
    if unavailable == "map":
        world.valid = False
    elif unavailable == "combat":
        world.owner._cached_data.account_options.Combat = False
    elif unavailable == "cinematic":
        world.cinematic = True
    elif unavailable == "party":
        world.party_loaded = False
    else:
        world.bar[1] = 0
    # Selection is supplied by the actual dispatcher; invalid map can revoke it.
    _normal_owner_entry(world)
    assert world.policy._capture is None
    world.valid = world.party_loaded = True
    world.cinematic = False
    world.owner._cached_data.account_options.Combat = True
    world.bar[1] = SY
    world.driver._contract_build = world.owner
    world.driver._contract_signature = world.driver._get_contract_signature()
    _normal_owner_entry(world)
    assert world.policy._capture.state == "ARMED"


def test_cached_reenable_reconstruction_and_fresh_reload(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _enable(world)
    original_capture = world.policy._capture
    world.driver.InvalidateContractPolicyWork()
    world.owner._cached_data.account_options.Combat = False
    _normal_owner_entry(world)
    world.owner._cached_data.account_options.Combat = True
    world.owner.OnContractActivated(world.owner._cached_data)
    _normal_owner_entry(world)
    assert world.policy._capture is original_capture
    assert sum(" ARMED " in line for line in output) == 1
    _replace_selected_owner(world)
    _normal_owner_entry(world)
    assert world.policy._capture is None, "Reconstruction cannot reset the module-lifetime latch"
    module = _reload_virtual_on(monkeypatch)
    assert not module.__dict__["_diagnostic_consumed"]
    _normal_owner_entry(world)
    assert world.policy._capture.state == "ARMED"
    assert sum(" ARMED " in line for line in output) == 2


@pytest.mark.parametrize("capturing", [False, True])
def test_clock_discontinuity_keeps_summary_budget_and_cannot_finish_twice(world: _World, capturing: bool) -> None:
    output = _enable(world)
    if capturing:
        world.pressure()
    capture = world.policy._capture
    while capture.lines < 395:
        world.policy.ObserveStock("AutoAttack", bool(capture.lines % 2))
    world.now -= 1000
    world.policy.Advance()
    assert capture.stop_reason == "clock_discontinuity"
    assert len(output) == capture.lines <= 400
    length = len(output)
    world.now += 200000
    world.policy.Advance()
    world.policy.ObserveStock("AutoAttack", True)
    capture.finish("line_limit")
    assert len(output) == length
    assert sum(" SUMMARY " in line for line in output) == 1


@pytest.mark.parametrize("callback", [False, True])
def test_clock_discontinuity_logger_failure_does_not_escape(world: _World, callback: bool) -> None:
    output = _enable(world)
    world.pressure()
    if callback:
        assert world.policy.TryCast()
    capture = world.policy._capture
    original = world.core.ConsoleLog

    def fail(sender: str, message: str) -> None:
        original(sender, message)
        if "clock_discontinuity" in message:
            raise RuntimeError("discontinuity logger stub failure")

    world.core.ConsoleLog = fail
    world.now -= 1000
    if callback:
        world.dispatch(delay=0)
        assert world.policy.last_outcome == "context_cancelled"
    else:
        world.policy.Advance()
    assert capture.clock_discontinuity and not capture.active
    assert capture.logger_failures == 1 and capture.stop_reason == "logger_failure"
    assert len(output) <= 400 and not world.calls


def _enable(w: _World, *, fail: bool = False, enter: bool = True) -> list[str]:
    module = sys.modules["Py4GWCoreLib.Builds.Skills.SmartSaveYourselves"]
    module.__dict__["_DIAGNOSTIC_ARM_ONCE"] = True
    output: list[str] = []

    def log(sender: str, message: str, *args: Any, **kwargs: Any) -> None:
        assert sender == "HR-DIAG", (sender, message)
        output.append(message)
        if fail:
            raise RuntimeError("test logger failure")

    w.core.ConsoleLog = log
    if enter:
        _normal_owner_entry(w)
        w.trace.clear()
    return output


def test_diagnostic_off_and_construction_are_inert(world: _World) -> None:
    output: list[Any] = []

    def log(*args: Any) -> None:
        output.append(args)

    world.core.ConsoleLog = log
    module = sys.modules["Py4GWCoreLib.Builds.Skills.SmartSaveYourselves"]
    assert module.__dict__["_DIAGNOSTIC_ARM_ONCE"] is False
    _cycles(world)
    assert output == [] and world.policy._capture is None


def test_diagnostic_one_owner_and_module_lifetime(world: _World) -> None:
    output = _enable(world, enter=False)
    match = world.stock_module.Paragon_Refrain(match_only=True)
    other = world.stock_module.Paragon_Refrain()
    other.set_cached_data(world.owner._cached_data)
    assert not hasattr(match, "heroic_refrain_policy")
    assert world.policy._capture is None and other.heroic_refrain_policy._capture is None
    assert output == [], "Discovery and constructors must not consume the arm"
    _normal_owner_entry(world)
    assert world.policy._capture.state == "ARMED"
    other.heroic_refrain_policy.Advance()
    assert other.heroic_refrain_policy._capture is None
    assert sum(" ARMED " in line for line in output) == 1
    world.now += 180000
    world.policy.Advance()
    third = world.stock_module.Paragon_Refrain()
    third.set_cached_data(world.owner._cached_data)
    third.heroic_refrain_policy.Advance()
    assert third.heroic_refrain_policy._capture is None


@pytest.mark.parametrize("late_entry", [False, True])
def test_diagnostic_time_bounds_and_unknown_hiatus(world: _World, late_entry: bool) -> None:
    output = _enable(world)
    world.policy.Advance()
    armed = world.now
    if late_entry:
        world.now += 100000
    world.pressure()
    capture = world.policy._capture
    assert capture.state == "CAPTURING" and capture.counts["pressure_episodes"] == 1
    deadline = min(armed + 180000, capture.started + 120000)
    world.now = deadline - 1
    world.policy.Advance()
    assert capture.active
    world.now = deadline
    world.policy.Advance()
    assert capture.state == "FINISHED"
    assert capture.stop_reason == ("arm_limit" if late_entry else "combat_limit")
    assert capture.observed_ms == capture.inferred_ms == 0
    assert capture.unobserved_ms > 0 and "observation_gap" in "\n".join(output)
    assert sum(" SUMMARY " in line for line in output) == 1


def test_diagnostic_no_pressure_is_inconclusive(world: _World) -> None:
    output = _enable(world)
    world.policy.Advance()
    world.now += 180000
    world.policy.Advance()
    assert world.policy._capture.state == "INCONCLUSIVE"
    assert any("pressure_seen=False" in line for line in output)
    assert not any(" CAPTURING " in line for line in output)


def test_diagnostic_hard_line_limit_keeps_final_summary(world: _World) -> None:
    output = _enable(world)
    world.pressure()
    capture = world.policy._capture
    for i in range(600):
        world.policy.ObserveStock("AutoAttack", bool(i % 2))
    assert capture.state == "FINISHED" and capture.stop_reason == "line_limit"
    assert len(output) == capture.lines <= 400
    assert any(" EVIDENCE_TOTALS " in line for line in output)
    assert any("truncated=True" in line for line in output)


def test_diagnostic_status_and_reasons_are_coalesced(world: _World) -> None:
    output = _enable(world)
    world.pressure(raw=0)
    world.energy = 10
    world.hr_target = 2
    world.policy.TryCast(preparation=True)
    for _ in range(100):
        world.now += 1
        world.policy.TryCast(preparation=True)
    assert sum("decision_preparation" in line for line in output) == 1
    assert sum(" status " in line for line in output) == 1
    assert any("'myt_energy': False" in line for line in output)
    world.now += 1000
    world.policy.Advance()
    assert sum(" status " in line for line in output) == 2


@pytest.mark.parametrize(
    "result,stage",
    [
        (True, "native_true"),
        (False, "native_false"),
        (RuntimeError(), "native_exception"),
    ],
)
def test_diagnostic_native_stages_and_dispatch_silence(world: _World, result: Any, stage: str) -> None:
    output = _enable(world)
    world.pressure()
    assert world.policy.TryCast()
    assert any("stage=queued" in line for line in output)
    assert not any("stage=native_" in line for line in output)
    before = list(output)
    world.native_result = result
    original = world.native

    def native(slot: int, target: int) -> bool:
        assert output == before, "No console output is allowed in the guarded dispatch before the native call"
        return original(slot, target)

    world.core.GLOBAL_CACHE.SkillBar._skillbar_instance.UseSkill = native
    world.dispatch()
    assert any("stage=" + stage in line for line in output), output
    assert world.policy._capture.counts["sy_native_calls"] == 1
    assert not world.policy._holds
    if result is True:
        assert any("native_acceptance_not_application" in line for line in output)


@pytest.mark.parametrize(
    "change,stage",
    [
        ("expire", "queue_expired"),
        ("cancel", "context_cancelled"),
        ("supersede", "preparation_superseded"),
        ("reject", "guard_rejected"),
    ],
)
def test_diagnostic_pre_native_cancellation(world: _World, change: str, stage: str) -> None:
    output = _enable(world)
    world.pressure(raw=0 if change == "supersede" else 100)
    assert world.policy.TryCast(preparation=change == "supersede")
    delay = 50
    if change == "expire":
        delay = 250
    elif change == "cancel":
        world.owner.InvalidatePolicyWork()
    elif change == "supersede":
        world.raw[SY] = 100
    else:

        def reject(*args: Any) -> bool:
            return False

        world.owner.AdmitPolicySkill = reject
    world.dispatch(delay)
    assert world.calls == []
    assert any("stage=" + stage in line for line in output), output


@pytest.mark.parametrize(
    "kind,progress,stage",
    [
        ("sy", True, "sy_resource_consequence"),
        ("myt", True, "myt_observed_progress"),
        ("myt", False, "observation_unresolved"),
        ("fgj", True, "fgj_observed_effect"),
        ("fgj", False, "observation_unresolved"),
    ],
)
def test_diagnostic_observations_are_not_native_receipts(world: _World, kind: str, progress: bool, stage: str) -> None:
    output = _enable(world)
    world.pressure(raw=100 if kind == "sy" else 0)
    if kind == "fgj":
        world.recharge[MYT] = 1
    assert world.policy.TryCast(preparation=kind != "sy")
    world.dispatch()
    if progress and kind != "fgj":
        world.raw[SY] = 0 if kind == "sy" else 40
    elif progress:
        world.add_effect(1, FGJ, 20000)
    world.now += 150 if progress else 750
    world.policy.Advance()
    assert any("stage=" + stage in line for line in output), output
    if kind == "myt" and progress:
        assert not world.policy._resource_ready(SY)
        assert "ready=False" in "\n".join(output)
        world.raw[SY] = 100
        assert world.policy._resource_ready(SY)
        assert "ready=True" in output[-1]
    if kind == "fgj":
        assert world.raw[SY] == 0, "An FGJ effect is not an adrenaline refill"


def test_diagnostic_coverage_and_refresh_demand_are_qualified(world: _World) -> None:
    output = _enable(world)
    world.heroes = [2]
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    world.raw[SY] = 0
    world.now += 150
    world.policy.Advance()
    world.add_effect(2, SY, 1000)
    world.now += 150
    world.policy.Advance()
    for _ in range(8):
        world.now += 500
        world.policy.TryCast()
    capture = world.policy._capture
    assert capture.observed_ms > 0 and capture.inferred_ms > 0 and capture.unknown_ms > 0
    assert capture.counts.get("refresh_demand_gaps", 0) > 0
    text = "\n".join(output)
    assert "'observed'" in text and "'inferred'" in text and "'unknown'" in text
    assert "overdue_scheduling_demand_not_proven_loss" in text
    before = (capture.observed_ms, capture.inferred_ms, capture.unknown_ms)
    world.now += 10000
    world.policy.Advance()
    assert before == (capture.observed_ms, capture.inferred_ms, capture.unknown_ms)


def test_diagnostic_positive_sy_effect_and_no_personal_identifiers(
    world: _World,
) -> None:
    output = _enable(world)
    world.owner._cached_data.account_email = "private-account@example.invalid"
    world.heroes = [2]
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch()
    world.add_effect(2, SY, 3000)
    world.now += 150
    world.policy.Advance()
    assert any("stage=sy_observed_effect" in line for line in output)
    assert not world.policy._holds
    assert "private-account" not in "\n".join(output)
    assert "example.invalid" not in "\n".join(output)
    assert all(line.startswith("+") for line in output)


def test_diagnostic_stock_evidence_is_only_helper_or_attack_request(
    world: _World,
) -> None:
    output = _enable(world)
    _upkeep(world)
    world.policy.ObserveStock("AutoAttack", True)
    text = "\n".join(output)
    assert "helper=HR_bootstrap_or_spread result=True" in text
    assert "helper=HR_self_ready result=False" in text
    assert "helper=Theyre_on_Fire result=True" in text
    assert "evidence=helper_admission_not_application" in text
    assert "evidence=attack_request" in text


def test_diagnostic_logger_failure_after_native_cannot_undo_acceptance(world: _World) -> None:
    output = _enable(world)
    world.pressure()
    assert world.policy.TryCast()
    log = world.core.ConsoleLog

    def fail_after_native(sender: str, message: str) -> None:
        log(sender, message)
        if "stage=native_true" in message:
            raise RuntimeError("console failed after recording native acceptance")

    world.core.ConsoleLog = fail_after_native
    world.dispatch()
    assert world.calls == [(SY, 0)] and world.policy.last_outcome == "submitted"
    assert world.owner._local_cast_timer.deadline == world.now + 250
    assert world.policy._capture.logger_failures == 1
    assert world.policy._capture.state == "FINISHED"
    emitted = len(output)
    world.raw[SY] = 0
    world.now += 150
    world.policy.Advance()
    assert world.policy.last_outcome == "sy_resource_consequence"
    assert len(output) == emitted


def test_diagnostic_delayed_dispatch_finishes_before_recording_late_events(world: _World) -> None:
    output = _enable(world)
    world.pressure()
    assert world.policy.TryCast()
    world.dispatch(130000)
    assert world.policy.last_outcome == "queue_expired" and not world.calls
    capture = world.policy._capture
    assert capture.state == "FINISHED" and capture.stop_reason == "combat_limit"
    assert any("capture_ms=120000" in line for line in output)
    assert not any("stage=queue_expired" in line for line in output), "Exclude events beyond the capture deadline"


def test_diagnostic_arming_mid_pressure_waits_for_a_real_entry(world: _World) -> None:
    world.pressure()
    output = _enable(world)
    world.policy.Advance()
    assert world.policy._capture.state == "ARMED"
    world.attacking.clear()
    world.now += 2000
    world.policy.Advance()
    assert not world.policy._pressure
    world.attacking.add(90)
    world.health[2] -= 0.1
    world.now += 150
    world.policy.Advance()
    assert world.policy._capture.state == "CAPTURING"
    assert sum(" CAPTURING " in line for line in output) == 1


def test_diagnostic_pressure_maintenance_and_invalidation_are_observed(world: _World) -> None:
    output = _enable(world)
    world.pressure()
    for _ in range(6):
        world.now += 500
        world.policy.Advance()
    assert world.policy._pressure, "Hostile activity maintains pressure without fresh health loss"
    assert world.policy._capture.counts["pressure_episodes"] == 1
    world.owner.InvalidatePolicyWork()
    assert not any("generation=1" in line for line in output), "No invented callback at the invalidation time"
    world.now += 3000
    world.policy.Advance()
    assert any("generation=1" in line for line in output)
    assert any("unknown_no_pause_timestamp" in line for line in output)


def test_diagnostic_buffer_overflow_is_isolated(world: _World) -> None:
    output = _enable(world)
    world.pressure()
    capture = world.policy._capture
    capture.deferred = True
    for i in range(100):
        world.policy.ObserveStock("AutoAttack", bool(i % 2))
    assert len(capture.pending) == 64
    world.policy._diagnostic("flush")
    assert capture.stop_reason == "event_buffer_limit" and len(output) <= 400
    assert world.policy.TryCast(), "A completed recorder cannot block the policy"


def test_diagnostic_no_negative_effect_census_claim(world: _World) -> None:
    output = _enable(world)
    world.pressure(raw=0)
    world.recharge[MYT] = 1
    world.add_effect(1, FGJ, 10000)
    world.now += 150
    world.policy.Advance()
    assert not world.policy.TryCast(preparation=True)
    text = "\n".join(output)
    assert "evidence=positive_active" in text
    assert "'fgj_no_positive_effect': False" in text
    assert "evidence=no_positive_evidence" in text
    assert not world.calls


def test_diagnostic_does_not_count_armed_time_as_combat_evidence(world: _World) -> None:
    _enable(world)
    world.pressure()
    capture = world.policy._capture
    assert capture.observed_ms == capture.inferred_ms == capture.unknown_ms == 0
    world.now += 150
    world.policy.Advance()
    assert capture.unknown_ms == 2 * 150


def test_diagnostic_queue_error_is_not_native_rejection(world: _World) -> None:
    output = _enable(world)
    world.pressure()

    def reject_queue(callback: Callable[..., Any]) -> None:
        raise RuntimeError("queue stub failure")

    world.core.GLOBAL_CACHE.SkillBar.QueueGuardedUseSkill = reject_queue
    assert not world.policy.TryCast()
    assert any("stage=queue_exception" in line for line in output)
    assert world.policy._capture.counts["sy_native_calls"] == 0
    assert not world.calls and not world.queue


@pytest.mark.parametrize("native_result,stage", [(True, "native_true"), (RuntimeError(), "native_exception")])
def test_diagnostic_native_evidence_survives_owner_bookkeeping_failure(
    world: _World, native_result: Any, stage: str
) -> None:
    output = _enable(world)
    world.pressure()
    assert world.policy.TryCast()
    world.native_result = native_result

    def fail_bookkeeping(delay: int) -> None:
        raise RuntimeError("owner bookkeeping stub failure")

    world.owner.MarkPolicySkillSubmitted = fail_bookkeeping
    world.dispatch()
    assert world.calls == [(SY, 0)]
    assert world.policy.last_outcome == "dispatch_exception"
    assert world.policy._capture.counts["sy_native_calls"] == 1
    assert world.policy._capture.counts["sy_" + stage] == 1
    assert any(" native " in line and "stage=" + stage in line for line in output)


def _snapshot(w: _World) -> dict[str, Any]:
    p, o = w.policy, w.owner
    return {
        "calls": list(w.calls),
        "ordinary": list(w.ordinary),
        "trace": list(w.trace),
        "restored": list(w.restored),
        "queued": len(w.queue),
        "tick": o.tick_state,
        "generation": o.GetPolicyGeneration(),
        "action_sequence": o.GetLocalActionSequence(),
        "timer": dict(cast(dict[str, Any], vars(o._local_cast_timer))),
        "attack_timer": dict(cast(dict[str, Any], vars(o._auto_attack_timer))),
        "outcome": p.last_outcome,
        "request": asdict(p._request) if p._request else None,
        "retry": {key: asdict(value) for key, value in p._retry.items()},
        "effects": {key: asdict(value) for key, value in p._effects.items()},
        "retired": {key: asdict(value) for key, value in p._retired_effects.items()},
        "holds": p._holds.copy(),
        "coverage_deadline": p._deadline(w.now),
        "health": {key: asdict(value) for key, value in p._health.items()},
        "policy": (
            p._generation,
            p._context,
            p._next_request,
            p._pressure,
            p._last_activity,
            p._last_now,
            p._dispatch_guard_until,
            p._myt_latched,
            p._myt_busy_seen,
            p._recipients,
        ),
    }


def _selected_combat_rounds(w: _World) -> None:
    _normal_owner_entry(w, combat=True)
    w.now += 150
    w.health[2] = 0.55
    _normal_owner_entry(w, combat=True)
    assert w.queue
    w.dispatch()
    w.raw[SY] = 0
    w.now += 250
    _normal_owner_entry(w, combat=True)
    assert w.queue
    w.dispatch()
    w.raw[SY] = 40
    w.now += 250
    _normal_owner_entry(w, combat=True)
    w.driver.InvalidateContractPolicyWork()
    if w.queue:
        w.dispatch()
    _normal_owner_entry(w, combat=False)


def _clock_jump(w: _World) -> None:
    w.pressure()
    assert w.policy.TryCast()
    w.now -= 1000
    w.dispatch(delay=0)
    assert w.policy.last_outcome == "context_cancelled"
    w.now += 1000
    _normal_owner_entry(w, combat=False)


@pytest.mark.parametrize(
    "scenario",
    [
        _cycles,
        _upkeep,
        _invalidation,
        _fallback,
        _stock_order,
        _timeout,
        _partial_myt,
        _selected_combat_rounds,
        _clock_jump,
    ],
    ids=[
        "cycles",
        "upkeep",
        "invalidation",
        "fallback",
        "stock_order",
        "timeout",
        "partial_myt",
        "selected_combat",
        "clock_jump",
    ],
)
@pytest.mark.parametrize("logger_fails", [False, True])
def test_diagnostic_off_on_behavioral_equivalence(scenario: Callable[[_World], None], logger_fails: bool) -> None:
    results: list[dict[str, Any]] = []
    outputs: list[list[str]] = []
    for enabled in (False, True):
        with pytest.MonkeyPatch.context() as mp:
            make_admission = cast(Callable[[pytest.MonkeyPatch], Any], getattr(_admission_fixture, "__wrapped__"))
            make_world = cast(Callable[[Any, pytest.MonkeyPatch], _World], getattr(world, "__wrapped__"))
            admission = make_admission(mp)
            w = make_world(admission, mp)
            output = _enable(w, fail=logger_fails, enter=False) if enabled else []
            reads: list[tuple[str, tuple[Any, ...]]] = []
            for api, name in (
                (w.core.SkillBar, "GetSkillData"),
                (w.core.GLOBAL_CACHE.Effects, "GetEffects"),
                (w.core.Agent, "GetEnergy"),
                (w.core.Agent, "GetMaxEnergy"),
            ):
                original = getattr(api, name)

                def spy(*args: Any, _original: Any = original, _name: str = name) -> Any:
                    reads.append((_name, args))
                    return _original(*args)

                mp.setattr(api, name, spy)
            _normal_owner_entry(w)
            w.trace.clear()
            scenario(w)
            result = _snapshot(w)
            result["resource_effect_energy_reads"] = reads
            results.append(result)
            outputs.append(output)
    assert results[0] == results[1], f"OFF/ON mismatch for {scenario.__name__}; logger_fails={logger_fails}"
    assert outputs[1], "The parity replay must actually exercise the armed diagnostic"
