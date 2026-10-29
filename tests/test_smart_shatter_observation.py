"""Offline capture limits, Draw routing, real-input provenance, and privacy."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from collections.abc import Iterable
from dataclasses import fields
from dataclasses import is_dataclass
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
import test_smart_shatter_hex as shatter_tests

ROOT = Path(__file__).resolve().parents[1]
SHATTER = shatter_tests.SHATTER
OBS = SHATTER.ShatterObservation
WIDGET = ROOT / "Widgets/Coding/Debug/Py4GW/Smart Shatter Observation.py"


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[int], object]:
    return shatter_tests.arm_observation_fixture(monkeypatch)


def _drain(observation: Any = OBS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _ in range(40):
        lines = observation.drain_console_draw()
        assert len(lines) <= 2, "console must emit no more than two lines per Draw"
        for line in lines:
            assert line.isascii() and len(line.encode("ascii")) <= 1536
            assert line.startswith("SmartShatterObs ")
            rows.append(json.loads(line.removeprefix("SmartShatterObs ")))
        if observation._capture.output_done:
            break
    assert observation._capture.output_done, "bounded output must terminate with END"
    assert len(rows) <= 72 and rows[-1]["kind"] == "END"
    return rows


def _sample(clock: list[int], *, elapsed: int = 500, observation: Any = OBS) -> None:
    clock[0] += elapsed
    request = observation.draw_request()
    assert request is not None
    epoch, _mode, context = request
    assert observation.accept_draw_sample(epoch, replace(context, uptime_ms=context.uptime_ms + elapsed), clock[0], 11)


def _effect(skill_id: int = 883, remaining: object = 7000) -> Any:
    return SimpleNamespace(skill_id=skill_id, remaining_ms=remaining, time_remaining=remaining)


def _arm_owner(monkeypatch: pytest.MonkeyPatch) -> tuple[list[int], object]:
    monkeypatch.setattr(OBS, "_capture", None)
    clock = [10_000]
    context = OBS.ContextSample(42, 1, 1, 0, 1000, 77, 7, (11, 22), 77)
    epoch = OBS.arm_capture("owner", "SH1", 1, context, ((11, 23), (22, 77)), lambda: clock[0], 10_000, 10_000, 13)
    assert epoch is not None
    return clock, epoch


def test_inactive_imports_do_not_touch_runtime_and_use_one_canonical_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OBS, "_capture", None)
    widget, calls, _console, _gui = _widget(monkeypatch)
    assert widget.Observation is OBS
    assert SHATTER.ShatterObservation is OBS
    widget.on_enable()
    widget.on_disable()
    assert OBS.scheduler_entry() is None and calls == [] and OBS._capture is None
    assert not hasattr(widget, "update"), "no Update probe or Update-to-Draw forwarding"


def test_real_classification_preserves_order_results_and_does_not_load_config(
    monkeypatch: pytest.MonkeyPatch,
    capture: tuple[Any, list[int], object],
) -> None:
    observation, _clock, epoch = capture
    calls: list[int] = []
    effect_reads: list[int] = []
    priority = types.ModuleType("Py4GWCoreLib.GlobalCache.HexRemovalPriority")

    def classify(skill_id: int, target: int) -> int:
        assert target == 77
        calls.append(skill_id)
        return 3 if skill_id == 883 else 1

    def forbidden(*_args: object) -> None:
        raise AssertionError("diagnostic attempted configuration loading")

    def read_effects(_target: int) -> tuple[tuple[int, int], ...]:
        effect_reads.append(_target)
        return ((883, 7000), (5, 4000))

    priority.__dict__.update(
        MIN_HEX_REMAINING_MS_TO_REMOVE=2500,
        classify_hex_for_removal=classify,
        get_hex_removal_effect_observations=read_effects,
        _resolved_profile_identity=("private@example.test", "Private Character"),
        _priority_cache_generation=8,
        _role_cache={77: (SimpleNamespace(value=2), 9)},
        _build_hex_removal_priority=forbidden,
        _get_active_profile_identity=forbidden,
    )
    monkeypatch.setitem(sys.modules, priority.__name__, priority)
    handler = object.__new__(SHATTER.SmartShatterHex)
    expected = handler._hex_identity_evidence(77)
    baseline_order = calls[:]
    calls.clear()
    handler._live_capture_hex_details = True
    ticket = observation.begin_evaluation(epoch)
    actual = handler._hex_identity_evidence(77, ticket)
    assert actual == expected and calls == baseline_order == [5, 883]
    assert effect_reads == [77, 77], "coexisting diagnostics must share each production effect read"
    assert handler._live_hex_details == {77: ((5, 883), 0)}
    decision = shatter_tests.observation_decision(shatter_tests.observation_ally(77))
    observation.snapshot_event(ticket, "decision", decision)
    row = observation._capture.decisions[0]
    assert row["vm_priority"] == 3 and row["profile"] == "profile1" and row["cache"] == 8
    assert row["role"] == 2 and row["profession"] == 9
    observation.stop_capture()
    text = json.dumps(_drain())
    for private in ("private@example.test", "Private Character", "owner_email", "agent_id", "login_number"):
        assert private not in text


@pytest.mark.parametrize(
    "effects,expected",
    [(((883, 2500),), "not_evaluated"), ((), "not_evaluated"), (((883, 9000),), "classification_exception")],
)
def test_not_classified_and_original_classification_exception_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
    capture: tuple[Any, list[int], object],
    effects: Any,
    expected: str,
) -> None:
    observation, _clock, epoch = capture
    calls: list[int] = []

    def classify(skill_id: int, _target: int) -> int:
        calls.append(skill_id)
        raise RuntimeError("original classifier failure")

    def read_effects(_target: int) -> Any:
        return effects

    priority = types.ModuleType("Py4GWCoreLib.GlobalCache.HexRemovalPriority")
    priority.__dict__.update(
        MIN_HEX_REMAINING_MS_TO_REMOVE=2500,
        classify_hex_for_removal=classify,
        get_hex_removal_effect_observations=read_effects,
    )
    monkeypatch.setitem(sys.modules, priority.__name__, priority)
    handler = object.__new__(SHATTER.SmartShatterHex)
    baseline = handler._hex_identity_evidence(77)
    order = calls[:]
    calls.clear()
    ticket = observation.begin_evaluation(epoch)
    assert handler._hex_identity_evidence(77, ticket) == baseline
    assert calls == order
    assert observation._capture.decisions[0]["vm_priority"] == expected


def test_available_input_completeness_is_not_reader_completeness(capture: tuple[Any, list[int], object]) -> None:
    observation, _clock, epoch = capture
    ticket = observation.begin_evaluation(epoch)
    observation.snapshot_event(ticket, "effects", 77, ())
    observation.snapshot_event(
        ticket, "decision", shatter_tests.observation_decision(shatter_tests.observation_ally(77))
    )
    assert observation._capture.decisions[0]["vm"][0] == "absent_in_input"
    observation.stop_capture()
    rows = _drain()
    assert rows[0]["reader_completeness"] == "unknown"
    assert rows[0]["instance_identity"] == "not_proven"


def test_first_claim_outcome_is_retained_when_first_target_is_not_watched(
    capture: tuple[Any, list[int], object],
) -> None:
    observation, _clock, epoch = capture
    ticket = observation.begin_evaluation(epoch)
    decision = shatter_tests.observation_decision(
        shatter_tests.observation_ally(23, health_fraction=0.2), shatter_tests.observation_ally(77)
    )
    observation.snapshot_event(ticket, "decision", decision)
    observation.snapshot_event(ticket, "claim", 23, False)
    observation.snapshot_event(ticket, "claim", 77, True)
    row = observation._capture.decisions[0]
    assert row["first"][0] == "P1" and row["first_claim"] == "claim_unavailable"
    assert row["chosen"] == "P2" and row["hr_claim"] == "acquired"
    assert row["claims_observed"] == 2 and row["claims_unavailable"] == 1


def test_passive_effect_and_candidate_traversal_never_reads_beyond_caps(capture: tuple[Any, list[int], object]) -> None:
    observation, _clock, epoch = capture
    inspected: list[int] = []

    class Effects:
        def __len__(self) -> int:
            return 100

        def __getitem__(self, index: int) -> Any:
            assert index < 64
            inspected.append(index)
            return _effect(5)

    class Candidates:
        def __len__(self) -> int:
            return 100

        def __getitem__(self, index: int) -> Any:
            assert index < 32
            return shatter_tests.observation_decision(shatter_tests.observation_ally(index + 100)).selected

    ticket = observation.begin_evaluation(epoch)
    observation.snapshot_event(ticket, "effects", 77, Effects())
    decision = SimpleNamespace(reason=SimpleNamespace(value="selected"), selected=None, candidates=Candidates())
    observation.snapshot_event(ticket, "decision", decision)
    row = observation._capture.decisions[0]
    assert inspected == list(range(64)) and row["vm"][0] == "unknown"
    assert row["hr"] == "unknown_truncated" and row["candidates_complete"] is False
    observation.stop_capture()
    assert _drain()[-1]["outcome"] == "INCOMPLETE"


@pytest.mark.parametrize("gap,active", [(749, True), (750, True), (751, False)])
def test_passive_hook_enforces_context_gap_without_draw(
    capture: tuple[Any, list[int], object], gap: int, active: bool
) -> None:
    observation, clock, epoch = capture
    clock[0] += gap
    observation.scheduler(epoch, "process_gate")
    assert observation._capture.active is active
    if not active:
        assert observation._capture.reason == "context_gap" and observation._capture.uncertain_after == 10_000


def test_absolute_deadline_is_enforced_by_late_callback(capture: tuple[Any, list[int], object]) -> None:
    observation, clock, epoch = capture
    index = observation.acquired(epoch, 1, 4, 77, 3400)
    for _ in range(59):
        _sample(clock)
    clock[0] = 39_999
    observation.attempt_event(epoch, index, "binding_enter")
    assert observation._capture.active
    before = list(observation._capture.attempts[index]["st"])
    clock[0] = 40_000
    observation.attempt_event(epoch, index, "binding_return", True)
    assert not observation._capture.active and observation._capture.reason == "completed"
    assert observation._capture.attempts[index]["st"] == before


@pytest.mark.parametrize("tail_ms", [500, 1])
def test_normal_completion_marks_only_the_unvalidated_context_tail(
    capture: tuple[Any, list[int], object], tail_ms: int
) -> None:
    observation, clock, epoch = capture
    index = observation.acquired(epoch, 1, 4, 77, 3400)
    observation.scheduler(epoch, "process_gate")
    for _ in range(57):
        _sample(clock)
    for elapsed in ((500, 500) if tail_ms == 500 else (749, 750)):
        _sample(clock, elapsed=elapsed)
    last_context = 40_000 - tail_ms
    assert observation._capture.last_sample == last_context
    clock[0] = 39_999
    observation.scheduler(epoch, "offered")
    observation.attempt_event(epoch, index, "binding_enter")
    stages = list(observation._capture.attempts[index]["st"])
    queries = observation._capture.queries
    clock[0] = 40_000
    observation.attempt_event(epoch, index, "binding_return", True)
    assert observation._capture.reason == "completed" and not observation._capture.active
    assert observation._capture.uncertain_after == last_context
    assert observation._capture.queries == queries, "expiration must not read game context"
    assert observation._capture.attempts[index]["st"] == stages
    rows = _drain()
    assert rows[-1]["outcome"] == "OBSERVED" and rows[-1]["reason"] == "completed"
    assert rows[-1]["last_context"] == rows[-1]["uncertain_after"] == last_context
    assert any(row["kind"] == "SCH" and row["t"] == 10_000 for row in rows), "validated evidence is preserved"
    assert any(row["kind"] == "SCH" and row["last"] == 39_999 for row in rows)


@pytest.mark.parametrize("final_read", ["unaccepted", "failed"])
def test_final_context_read_crossing_deadline_does_not_validate_the_tail(
    capture: tuple[Any, list[int], object], final_read: str
) -> None:
    observation, clock, epoch = capture
    for _ in range(49):
        _sample(clock, elapsed=600)
    assert clock[0] == 39_400
    clock[0] = 39_900
    request = observation.draw_request()
    assert request is not None
    queries = observation._capture.queries
    clock[0] = 40_000
    if final_read == "unaccepted":
        assert not observation.accept_draw_sample(epoch, replace(request[2], uptime_ms=31_000), clock[0], 11)
    else:
        observation.sample_failed(epoch, "sample_failure", 11)
    assert observation._capture.queries == queries + 11
    end = _drain()[-1]
    assert end["reason"] == "completed" and end["last_context"] == end["uncertain_after"] == 39_400
    assert end["outcome"] == ("OBSERVED" if final_read == "unaccepted" else "INCOMPLETE")


@pytest.mark.parametrize(
    "sealed_reason", ["manual_stop", "diagnostic_failure", "context_gap", "completed", "sample_failure"]
)
def test_late_work_preserves_existing_seal_and_context_boundary(
    capture: tuple[Any, list[int], object], sealed_reason: str
) -> None:
    observation, clock, epoch = capture
    index = observation.acquired(epoch, 1, 4, 77, 3400)
    for _ in range(59):
        _sample(clock)
    if sealed_reason == "diagnostic_failure":
        observation._failed()
    elif sealed_reason in ("context_gap", "completed"):
        clock[0] = 40_251 if sealed_reason == "context_gap" else 40_000
        observation.scheduler(epoch, "idle")
    else:
        observation.stop_capture(sealed_reason)
    capture_state = observation._capture
    assert capture_state.reason == sealed_reason and not capture_state.active
    assert capture_state.uncertain_after == 39_500
    before = (capture_state.reason, capture_state.last_now, capture_state.uncertain_after, capture_state.hooks)
    stages = list(capture_state.attempts[index]["st"])
    clock[0] = 41_000
    observation.scheduler(epoch, "offered")
    observation.attempt_event(epoch, index, "binding_return", True)
    assert observation.begin_evaluation(epoch) is None and observation.draw_request() is None
    observation.stop_capture("widget_disabled")
    assert (capture_state.reason, capture_state.last_now, capture_state.uncertain_after, capture_state.hooks) == before
    assert capture_state.attempts[index]["st"] == stages


def test_old_tokens_and_owner_samples_cannot_cross_stop_and_rearm(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, old_epoch = _arm_owner(monkeypatch)
    OBS.owner_sample(old_epoch, [_effect()])
    OBS.stop_capture()
    previous = OBS._capture
    _drain()
    epoch = OBS.arm_capture(
        "owner", "SH2", 1, previous.context, ((11, 23), (22, 77)), lambda: clock[0], clock[0], clock[0], 13
    )
    assert epoch is not None and epoch is not old_epoch
    OBS.owner_sample(old_epoch, [_effect()])
    OBS.scheduler(old_epoch, "offered")
    assert OBS._capture.owner_rows == [] and OBS._capture.scheduler == {}


def test_profile_change_stops_without_reading_configuration(
    monkeypatch: pytest.MonkeyPatch, capture: tuple[Any, list[int], object]
) -> None:
    observation, clock, epoch = capture
    module = types.ModuleType("Py4GWCoreLib.GlobalCache.HexRemovalPriority")
    module.__dict__.update(_resolved_profile_identity=("a", "b"), _priority_cache_generation=1, _role_cache={})
    monkeypatch.setitem(sys.modules, module.__name__, module)
    first = observation.begin_evaluation(epoch)
    observation.snapshot_event(first, "classification", 77, 3)
    _sample(clock)
    module.__dict__["_resolved_profile_identity"] = ("a", "c")
    observation.snapshot_event(first, "classification", 77, 1)
    assert observation._capture.reason == "profile_changed"
    assert observation._capture.uncertain_after == clock[0]


@pytest.mark.parametrize(
    "change", ["map_id", "region", "district", "language", "party_id", "player_id", "watched_id", "roster", "uptime_ms"]
)
def test_context_change_seals_observation_only(capture: tuple[Any, list[int], object], change: str) -> None:
    observation, clock, epoch = capture
    old = observation._capture.context
    clock[0] += 500
    assert observation.draw_request() is not None
    value = (11, 33) if change == "roster" else 1 if change == "uptime_ms" else getattr(old, change) + 1
    changed = replace(old, **{change: value})
    assert not observation.accept_draw_sample(epoch, changed, clock[0], 11)
    assert observation._capture.reason == "context_changed"


def test_attempt_and_hook_limits_reserve_end(capture: tuple[Any, list[int], object]) -> None:
    observation, _clock, epoch = capture
    for index in range(8):
        assert observation.acquired(epoch, index, 1, 77, 3400) == index
    assert observation.acquired(epoch, 9, 1, 77, 3400) == -1
    rows = _drain()
    assert len([row for row in rows if row["kind"] == "ATT"]) == 8
    assert rows[-1]["reason"] == "attempt_limit" and rows[-1]["outcome"] == "INCOMPLETE"


def test_hook_exhaustion_and_clock_fault_never_escape(
    monkeypatch: pytest.MonkeyPatch, capture: tuple[Any, list[int], object]
) -> None:
    observation, _clock, epoch = capture
    observation._capture.hooks = observation.MAX_HOOKS - 1
    observation.scheduler(epoch, "process_gate")
    observation.scheduler(epoch, "process_gate")
    assert observation._capture.hooks == observation.MAX_HOOKS and observation._capture.reason == "hook_limit"
    _drain()
    observation._capture = None
    _observation, _clock, epoch = shatter_tests.arm_observation_fixture(monkeypatch)
    assert observation._capture is not None

    def broken_clock() -> int:
        raise OSError("private OS error")

    observation._capture.clock = broken_clock
    assert observation.scheduler_entry() is None
    assert observation._capture.reason == "diagnostic_failure"


def _owned_size(value: object, seen: set[int] | None = None) -> int:
    if seen is None:
        seen = set()
    if id(value) in seen or isinstance(value, (types.FunctionType, types.ModuleType, type)):
        return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        total += sum(
            _owned_size(key, seen) + _owned_size(item, seen) for key, item in cast(dict[object, object], value).items()
        )
    elif isinstance(value, (tuple, list, set, frozenset)):
        total += sum(_owned_size(item, seen) for item in cast(Iterable[object], value))
    elif is_dataclass(value) and not isinstance(value, type):
        total += sum(_owned_size(getattr(value, item.name), seen) for item in fields(value))
    return total


def test_worst_case_retained_state_output_and_sampling_bounds(
    monkeypatch: pytest.MonkeyPatch, capture: tuple[Any, list[int], object]
) -> None:
    observation, clock, epoch = capture
    profile = types.ModuleType("Py4GWCoreLib.GlobalCache.HexRemovalPriority")
    profile.__dict__.update(
        _resolved_profile_identity=("a" * 320, "b" * 320),
        _priority_cache_generation=(1 << 63) - 1,
        _HEX_REMOVAL_PRIORITY_BUILT=True,
        _role_cache={77: (SimpleNamespace(value=2), 9)},
    )
    monkeypatch.setitem(sys.modules, profile.__name__, profile)
    for index in range(32):
        observation._target(observation._capture, index + 1000)
    # Fill all record classes, all reason counters, all target labels and stages.
    for bucket in range(30):
        if bucket:
            _sample(clock)
            _sample(clock)
        observation.scheduler_entry()
        for reason in observation._SCHEDULER_REASONS:
            observation.scheduler(epoch, reason, 123456789, True)
        for reason in (
            "active_or_disposed",
            "composition",
            "runtime",
            "slot_or_readiness",
            "parameters",
            "snapshot",
            "lifecycle",
            "no_candidates",
        ):
            observation.gate(epoch, reason)
        ticket = observation.begin_evaluation(epoch)
        observation.snapshot_event(ticket, "effects", 77, [_effect(883, 1.23456789012345e99)] * 64)
        observation.snapshot_event(ticket, "classification", 77, 3)
        decision = shatter_tests.observation_decision(
            shatter_tests.observation_ally(77), shatter_tests.observation_ally(100 + bucket)
        )
        observation.snapshot_event(ticket, "decision", decision)
        observation.snapshot_event(ticket, "claim", 77, False)
        assert observation.begin_evaluation(epoch) is None
        if bucket < 8:
            index = observation.acquired(epoch, (1 << 63) - 1, (1 << 63) - 1, 100 + bucket, 2147483647)
            for at_execution in (False, True):
                extra = observation.begin_revalidation(epoch, index, at_execution)
                observation.snapshot_event(extra, "effects", 77, [_effect(883, 1.23456789012345e99)] * 64)
                observation.snapshot_event(extra, "classification", 77, 3)
                observation.snapshot_event(extra, "decision", decision)
            for stage in (
                "pre",
                "queue",
                "exec",
                "renew",
                "binding_enter",
                "binding_return",
                "binding_exception",
                "abort",
                "cancel",
            ):
                observation.attempt_event(
                    epoch,
                    index,
                    stage,
                    "accepted" if stage in ("pre", "exec", "abort", "cancel") else 1.23456789012345e99,
                )
    _sample(clock)
    assert observation._capture.samples == 60 and observation._capture.queries <= 672
    assert observation.draw_request() is None, "no extra query or catch-up at the same timestamp"
    assert len(observation._capture.decisions) == 30 and len(observation._capture.revalidation_tickets) == 16
    assert observation._capture.snapshot_reads == 46
    state_bytes = _owned_size(observation._capture)
    # Double the measured 32-bit object/container cost for a conservative margin,
    # and reserve 64 KiB for transient Draw record views and two formatted lines.
    assert state_bytes * 2 + 65536 < 512 * 1024, f"worst-case retained state {state_bytes} bytes"
    clock[0] = 40_000
    observation.scheduler(epoch, "idle")
    rows = _drain()
    assert len(rows) == 70
    assert all("omitted" not in row for row in rows), "attempt summaries must fit without dropping decisive fields"
    assert rows[-1]["record_count"] == 70 and rows[-1]["skipped_detail"] == 30


def test_owner_repeat_suppression_and_not_exercised(monkeypatch: pytest.MonkeyPatch) -> None:
    clock, epoch = _arm_owner(monkeypatch)
    for index in range(60):
        if index:
            _sample(clock)
        OBS.owner_sample(epoch, [_effect(5)])
    clock[0] = 40_000
    OBS.draw_request()
    rows = _drain()
    owner = [row for row in rows if row["kind"] == "OWNER"]
    assert len(owner) == 1 and owner[0]["samples"] == 60
    assert rows[-1]["outcome"] == "NOT_EXERCISED" and rows[-1]["suppressed"] == 59


def test_oversized_line_and_formatter_failure_are_honest(
    monkeypatch: pytest.MonkeyPatch, capture: tuple[Any, list[int], object]
) -> None:
    observation, _clock, epoch = capture
    observation.scheduler(epoch, "idle")
    observation._capture.scheduler[0]["test_only_oversize"] = "x" * 2000
    observation.stop_capture()
    rows = _drain()
    assert rows[1]["omitted"] == "line_limit" and rows[-1]["outcome"] == "INCOMPLETE"


def test_total_formatter_failure_still_reserves_terminal_output(
    monkeypatch: pytest.MonkeyPatch, capture: tuple[Any, list[int], object]
) -> None:
    observation, _clock, epoch = capture
    observation.scheduler(epoch, "idle")
    observation.stop_capture()

    def broken_format(*_args: object) -> str:
        raise ValueError("format failure containing private context")

    monkeypatch.setattr(observation, "_format", broken_format)
    rows = _drain()
    assert rows[-1] == {"kind": "END", "outcome": "INCOMPLETE", "reason": "format_failure"}


def test_stage_limit_and_provisional_snapshot_work_are_bounded(capture: tuple[Any, list[int], object]) -> None:
    observation, _clock, epoch = capture
    index = observation.acquired(epoch, 1, 1, 77, 3400)
    for _ in range(10):
        observation.attempt_event(epoch, index, "renew", True)
    assert len(observation._capture.attempts[index]["st"]) == 10
    assert observation._capture.reason == "stage_limit"
    _drain()


def test_repeated_unfinished_evaluations_cannot_exceed_snapshot_read_budget(
    capture: tuple[Any, list[int], object],
) -> None:
    observation, _clock, epoch = capture
    for _ in range(47):
        ticket = observation.begin_evaluation(epoch)
        observation.snapshot_event(ticket, "effects", 77, [_effect()])
    assert observation._capture.snapshot_reads == 46 and observation._capture.reason == "snapshot_limit"
    assert _drain()[-1]["outcome"] == "INCOMPLETE"


def test_recorder_reload_preserves_sealed_output_and_rejects_old_epoch(
    monkeypatch: pytest.MonkeyPatch,
    capture: tuple[Any, list[int], object],
) -> None:
    observation, clock, old_epoch = capture
    observation.scheduler(old_epoch, "process_gate")
    spec = observation.__spec__
    monkeypatch.setitem(sys.modules, spec.name, observation)
    spec.loader.exec_module(observation)
    assert not observation._capture.active and observation._capture.reason == "reloaded"
    previous = observation._capture
    _drain()
    new_epoch = observation.arm_capture(
        "mesmer", "SH2", 2, previous.context, ((11, 23), (22, 77)), lambda: clock[0], clock[0], clock[0], 13
    )
    observation.scheduler(old_epoch, "offered")
    assert new_epoch is not None and new_epoch is not old_epoch and observation._capture.scheduler == {}


def _widget(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[str], list[str], dict[str, Any]]:
    calls: list[str] = []
    console: list[str] = []
    gui: dict[str, Any] = {"visible": True, "arm": False, "stop": False, "players": 2, "clock": 10_000}
    core = types.ModuleType("Py4GWCoreLib")
    core.__path__ = []
    builds = types.ModuleType("Py4GWCoreLib.Builds")
    builds.__path__ = []
    skills = types.ModuleType("Py4GWCoreLib.Builds.Skills")
    skills.__path__ = []
    skills.__dict__["SmartShatterObservation"] = OBS
    for module in (core, builds, skills):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Builds.Skills.SmartShatterObservation", OBS)
    spec = importlib.util.spec_from_file_location("_shatter_observation_widget_test", WIDGET)
    assert spec is not None and spec.loader is not None
    widget = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, widget)

    def query(name: str, result: Any) -> Any:
        def read(*args: object) -> Any:
            assert widget._in_draw, f"native getter {name} escaped Draw"
            calls.append(name)
            return result(*args) if callable(result) else result

        return read

    core.__dict__["Map"] = SimpleNamespace(
        **{
            name: query(name, value)
            for name, value in {
                "IsMapReady": True,
                "IsExplorable": True,
                "GetMapID": 42,
                "GetRegion": (1, ""),
                "GetDistrict": 1,
                "GetLanguage": (0, ""),
                "GetInstanceUptime": lambda: gui["clock"] - 9000,
            }.items()
        }
    )
    core.__dict__["Player"] = SimpleNamespace(GetAgentID=query("GetAgentID", 77))

    def lookup(login: int) -> int:
        if login == gui.get("lookup_failure"):
            raise RuntimeError("unavailable watched target")
        return gui.get("agents", {}).get(login, 77 if login == 2 else login + 100)

    def owner_effects(_agent: int) -> list[Any]:
        return [_effect()]

    def log(_name: str, line: str, _level: int) -> None:
        console.append(line)

    core.__dict__["Party"] = SimpleNamespace(
        GetPartyID=query("GetPartyID", 7),
        GetPlayers=query(
            "GetPlayers",
            lambda: [SimpleNamespace(login_number=i) for i in gui.get("roster", range(1, gui["players"] + 1))],
        ),
        Players=SimpleNamespace(GetAgentIDByLoginNumber=query("GetAgentIDByLoginNumber", lookup)),
    )
    core.__dict__["Effects"] = SimpleNamespace(GetEffects=query("GetEffects", owner_effects))
    core.__dict__["Console"] = SimpleNamespace(Log=log, MessageType=SimpleNamespace(Info=0))

    def button(name: str) -> bool:
        key = "arm" if name == "Arm one capture" else "stop"
        pressed = bool(gui[key])
        gui[key] = False
        return pressed

    def noop(*_args: object) -> None:
        pass

    def begin(_name: str) -> bool:
        return bool(gui["visible"])

    def combo(_name: str, value: int, _choices: tuple[str, ...]) -> int:
        return value

    def input_text(_name: str, value: str) -> str:
        return value

    def input_int(_name: str, value: int) -> int:
        return value

    core.__dict__["PyImGui"] = SimpleNamespace(
        begin=begin,
        end=noop,
        text=noop,
        begin_disabled=noop,
        end_disabled=noop,
        combo=combo,
        input_text=input_text,
        input_int=input_int,
        button=button,
    )
    clock_module = types.ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync")
    clock_module.__dict__["get_uncached_tick_count64"] = lambda: gui["clock"]
    monkeypatch.setitem(sys.modules, clock_module.__name__, clock_module)
    spec.loader.exec_module(widget)
    return widget, calls, console, gui


@pytest.mark.parametrize("mode", [0, 1])
def test_widget_exact_query_budget_collapsed_draw_disable_and_reenable(
    monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    monkeypatch.setattr(OBS, "_capture", None)
    widget, calls, console, gui = _widget(monkeypatch)
    widget._mode = mode
    widget._watched_label = 12 if mode else 2
    gui["players"] = 12
    gui["roster"] = tuple(range(12, 0, -1))
    widget.on_enable()
    widget.draw()
    assert calls == [] and console == [] and OBS._capture is None
    gui["arm"] = True
    widget.draw()
    assert calls.count("GetAgentIDByLoginNumber") == 12, "Arm must resolve each roster member only once"
    assert len(calls) == (23 if mode == 0 else 22) and OBS._capture.actor == "P2"
    assert OBS._capture.watched == ("P2" if mode == 0 else "P12")
    assert OBS._capture.context.watched_id == (77 if mode == 0 else 112)
    assert OBS._capture.context.roster == tuple(range(1, 13))
    assert OBS._capture.actors == {77 if login == 2 else login + 100: f"P{login}" for login in range(1, 13)}
    gui["visible"] = False
    for _ in range(59):
        before = len(calls)
        resolutions = calls.count("GetAgentIDByLoginNumber")
        gui["clock"] += 500
        widget.draw()
        assert len(calls) - before == 11
        assert calls.count("GetAgentIDByLoginNumber") - resolutions == mode
    assert len(calls) == (672 if mode == 0 else 671)
    assert OBS._capture.queries == len(calls) <= OBS.MAX_QUERIES
    assert calls.count("GetEffects") == (60 if mode == 0 else 0)
    before = len(calls)
    widget.on_disable()
    widget.on_enable()
    for _ in range(40):
        previous = len(console)
        widget.draw()
        assert len(console) - previous <= 2
    assert len(calls) == before and not OBS._capture.active
    assert json.loads(console[-1].removeprefix("SmartShatterObs "))["kind"] == "END"
    with pytest.raises(RuntimeError, match="Draw"):
        widget._sample_context_draw("owner", 1, initial=True)
    assert len(calls) == before


@pytest.mark.parametrize("invalid", ["out_of_roster", "unavailable", "lookup_failure", "duplicate_agent"])
def test_widget_arm_rejects_invalid_watched_identity_without_extra_resolution(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    monkeypatch.setattr(OBS, "_capture", None)
    widget, calls, _console, gui = _widget(monkeypatch)
    widget._mode = 1
    widget._watched_label = 12
    gui["players"] = 2 if invalid == "out_of_roster" else 12
    if invalid == "lookup_failure":
        gui["lookup_failure"] = 12
    elif invalid in ("unavailable", "duplicate_agent"):
        gui["agents"] = {12: 0 if invalid == "unavailable" else 77}
    gui["arm"] = True
    widget.draw()
    assert calls.count("GetAgentIDByLoginNumber") == gui["players"]
    assert len(calls) == 10 + gui["players"]
    assert OBS._capture is None and not gui["arm"], "invalid identity must not arm or retry"


@pytest.mark.parametrize("change", ["moved", "unavailable", "lookup_failure"])
def test_widget_subsequent_draw_still_resolves_and_validates_watched_identity(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    monkeypatch.setattr(OBS, "_capture", None)
    widget, calls, console, gui = _widget(monkeypatch)
    widget._mode = 1
    widget._watched_label = 12
    gui["players"] = 12
    gui["arm"] = True
    widget.draw()
    assert OBS._capture.context.watched_id == 112
    before = len(calls)
    resolutions = calls.count("GetAgentIDByLoginNumber")
    if change == "lookup_failure":
        gui["lookup_failure"] = 12
    else:
        gui["agents"] = {12: 999 if change == "moved" else 0}
    gui["clock"] += 500
    widget.draw()
    assert len(calls) - before == 11 and calls.count("GetAgentIDByLoginNumber") - resolutions == 1
    assert OBS._capture.queries == len(calls) and not OBS._capture.active
    assert OBS._capture.context.watched_id == 112 and OBS._capture.uncertain_after == 10_000
    end = json.loads(console[-1].removeprefix("SmartShatterObs "))
    assert end["kind"] == "END" and end["outcome"] == "INCOMPLETE"


def test_widget_roster_overflow_short_circuits_and_reload_never_arms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OBS, "_capture", None)
    widget, calls, _console, gui = _widget(monkeypatch)
    gui["players"] = 13
    gui["arm"] = True
    widget.draw()
    assert len(calls) == 10 and OBS._capture is None
    gui["players"] = 2
    gui["arm"] = True
    widget.draw()
    old_epoch = OBS._capture.epoch
    before = len(calls)
    spec = widget.__spec__
    spec.loader.exec_module(widget)
    assert OBS._capture.epoch is old_epoch and not OBS._capture.active and OBS._capture.reason == "reloaded"
    assert len(calls) == before


@pytest.mark.parametrize("malformed_result", [False, True])
def test_failed_draw_reads_are_accounted_without_exception_text(
    monkeypatch: pytest.MonkeyPatch, malformed_result: bool
) -> None:
    monkeypatch.setattr(OBS, "_capture", None)
    widget, calls, console, gui = _widget(monkeypatch)
    gui["arm"] = True
    widget.draw()
    core = sys.modules["Py4GWCoreLib"]

    def region() -> Any:
        assert widget._in_draw
        calls.append("GetRegion")
        if malformed_result:
            return None
        raise RuntimeError("private account/context exception text")

    core.__dict__["Map"].GetRegion = region
    gui["clock"] += 500
    widget.draw()
    for _ in range(40):
        widget.draw()
    assert len(calls) == 17
    end = json.loads(console[-1].removeprefix("SmartShatterObs "))
    assert end["outcome"] == "INCOMPLETE"
    assert end["queries"] == (24 if malformed_result else 17)
    assert end["query_count_upper_bound"] is malformed_result
    assert all("private account" not in line for line in console)


def test_no_new_native_getters_in_passive_owner_and_no_update_forwarder() -> None:
    tree = ast.parse(WIDGET.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "update" not in functions
    for name in ("on_enable", "on_disable"):
        calls = [node for node in ast.walk(functions[name]) if isinstance(node, ast.Call)]
        assert all(isinstance(call.func, ast.Attribute) and call.func.attr == "stop_capture" for call in calls)
    recorder_tree = ast.parse(Path(OBS.__file__).read_text(encoding="utf-8"))
    assert not any(
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("Py4GWCoreLib")
        for node in ast.walk(recorder_tree)
    )
