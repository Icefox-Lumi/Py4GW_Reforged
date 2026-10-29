"""Offline HR census/publication checks; isolated mappings, current EDITS sources only."""

from __future__ import annotations

import ast
import importlib.util
import sys
import threading
import types
from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any
from typing import cast
from typing import overload
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "Py4GWCoreLib/GlobalCache/shared_memory_src"


@overload
def runtime_stub(callback: Callable[[Any], Any]) -> Callable[..., Any]: ...


@overload
def runtime_stub(callback: Callable[[Any, Any], Any]) -> Callable[..., Any]: ...


@overload
def runtime_stub(callback: Callable[[Any, Any, Any], Any]) -> Callable[..., Any]: ...


@overload
def runtime_stub(callback: Callable[..., Any]) -> Callable[..., Any]: ...


def runtime_stub(callback: Callable[..., Any]) -> Callable[..., Any]:
    """Typed dynamic boundary for isolated injected-runtime fixtures."""
    return callback


def variadic_stub(callback: Callable[..., Any]) -> Callable[..., Any]:
    return callback


def load_source(name: str, path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    assert module.__file__ is not None
    assert Path(module.__file__).resolve() == path.resolve()
    return module


@pytest.fixture
def hr(monkeypatch: pytest.MonkeyPatch):
    prefix = "Py4GWCoreLib.GlobalCache.shared_memory_src"
    for name in ("Py4GWCoreLib", "Py4GWCoreLib.GlobalCache", prefix):
        package = types.ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    constants = types.ModuleType(prefix + ".Globals")
    constants.__dict__.update(SHMEM_MAX_PLAYERS=64, SHMEM_MAX_NUMBER_OF_BUFFS=240)
    monkeypatch.setitem(sys.modules, constants.__name__, constants)
    sync = load_source(prefix + ".IntentSync", SHARED / "IntentSync.py", monkeypatch)
    clock = [10_000]
    monkeypatch.setattr(sync, "get_uncached_tick_count64", runtime_stub(lambda: clock[0]))
    identity = load_source(prefix + ".ConditionObservations", SHARED / "ConditionObservations.py", monkeypatch)
    module = load_source(prefix + ".HrHexObservations", SHARED / "HrHexObservations.py", monkeypatch)
    monkeypatch.setattr(module, "TABLE_NAME", "Py4GW.HrHex.Offline." + uuid4().hex)
    owner = identity.Owner(0, "hr@example.test", "Fixture HR", 77, 22, 123, (42, 1, 1, 0), 5, 7, False)
    context = identity.Context(
        owner.email, owner.character, owner.agent, owner.login, owner.hwnd, owner.location, owner.party, b"w" * 32
    )
    table = module.HrHexTable()
    state = NS(
        module=module,
        identity=identity,
        sync=sync,
        clock=clock,
        owner=owner,
        context=context,
        table=table,
        publisher=identity.Publisher(),
        core=sys.modules["Py4GWCoreLib"],
    )
    yield state
    table.close()


def census(hr: Any, *, remaining: float | None = 6000, ids: tuple[int, ...] = (883,)) -> Any:
    return hr.module.HrHexCensus(frozenset(ids), len(ids), remaining)


def publish(hr: Any, value: Any = None) -> bool:
    return hr.table.publish(hr.publisher, hr.owner, hr.context.instance, hr.clock[0], value or census(hr))


@pytest.mark.parametrize(
    "effects,expected",
    cast(
        list[Any],
        [
            ([], (frozenset(), 0, None)),
            ([(100, 9000), (883, 6000), (883, 5000)], (frozenset({883}), 2, 5000)),
            ([(883, None), (883, 6000)], (frozenset({883}), 2, None)),
            ([(883, 0), (883, 6000)], (frozenset({883}), 1, None)),
            ([(883, -1)], (frozenset(), 0, None)),
            ([(883, float("nan"))], (frozenset({883}), 1, None)),
            ([(883, "bad")], (frozenset({883}), 1, None)),
            ([(883, True)], (frozenset({883}), 1, None)),
        ],
    ),
)
def test_census_facts_and_conservative_duplicate_durations(hr: Any, effects: Any, expected: Any) -> None:
    values = [NS(skill_id=skill_id, time_remaining=remaining) for skill_id, remaining in effects]
    assert hr.module.collect_hex_census(
        values, runtime_stub(lambda skill_id: skill_id == 883)
    ) == hr.module.HrHexCensus(*expected)


@pytest.mark.parametrize("bad", [0, -1, True, "883", 2**32])
def test_malformed_identity_invalidates_whole_census(hr: Any, bad: Any) -> None:
    assert (
        hr.module.collect_hex_census(
            [NS(skill_id=883, time_remaining=5000), NS(skill_id=bad)], runtime_stub(lambda _: True)
        )
        is None
    )


def test_processing_bound_failed_enumeration_and_classification(hr: Any) -> None:
    effects = [NS(skill_id=883, time_remaining=5000)] * 240
    assert hr.module.collect_hex_census(effects, runtime_stub(lambda _: True)).entry_count == 240
    assert hr.module.collect_hex_census(effects + [effects[0]], runtime_stub(lambda _: False)) is None
    assert hr.module.collect_hex_census(None, runtime_stub(lambda _: True)) is None
    assert hr.module.collect_hex_census(effects, runtime_stub(lambda _: None)) is None

    def incomplete():
        yield effects[0]
        raise RuntimeError("incomplete native enumeration")

    def bad_classification(_: int) -> bool:
        raise RuntimeError("classification unavailable")

    assert hr.module.collect_hex_census(incomplete(), runtime_stub(lambda _: True)) is None
    assert hr.module.collect_hex_census(effects, bad_classification) is None


@pytest.mark.parametrize("age,available", [(0, True), (749, True), (750, False), (-1, False)])
def test_freshness_and_four_readers_share_immutable_record(hr: Any, age: int, available: bool) -> None:
    assert publish(hr)
    original = hr.table.read(hr.owner, hr.context.instance)
    hr.clock[0] += age
    readers = [hr.module.HrHexTable() for _ in range(4)]
    try:
        for reader in readers:
            result = reader.read(hr.owner, hr.context.instance)
            assert (result is not None) == available, (age, result)
            if available:
                assert result == original
                assert result is not original
    finally:
        for reader in readers:
            reader.close()
    assert original.census == census(hr)


def test_invalid_empty_and_failed_read_are_distinct_without_refresh(hr: Any) -> None:
    assert hr.table.read(hr.owner, hr.context.instance) is None
    assert publish(hr, census(hr, remaining=None, ids=()))
    assert hr.table.read(hr.owner, hr.context.instance).census.hex_ids == frozenset()
    sequence = hr.publisher.sequence
    hr.table.invalidate(hr.publisher, stop=False)
    assert hr.table.read(hr.owner, hr.context.instance) is None
    assert hr.publisher.sequence == sequence
    hr.clock[0] += 250
    assert publish(hr)
    assert hr.publisher.sequence == sequence + 1


def test_sequence_generation_reload_and_exact_successor_protection(hr: Any) -> None:
    assert publish(hr)
    first = hr.table.read(hr.owner, hr.context.instance)
    assert not publish(hr), "same timestamp cannot manufacture another successful owner read"
    hr.table.invalidate(hr.publisher, stop=False)
    hr.clock[0] += 250
    assert publish(hr)
    second = hr.table.read(hr.owner, hr.context.instance)
    assert second.sequence > first.sequence and second.incarnation[2] > first.incarnation[2]
    old = hr.publisher
    hr.clock[0] += 250
    hr.publisher = hr.identity.Publisher()
    assert publish(hr)
    successor = hr.table.read(hr.owner, hr.context.instance)
    hr.table.invalidate(old)
    assert hr.table.read(hr.owner, hr.context.instance) == successor
    assert not hr.table.publish(old, hr.owner, hr.context.instance, hr.clock[0], census(hr))


@pytest.mark.parametrize(
    "field,value",
    [
        ("email", "replacement@example.test"),
        ("character", "Other"),
        ("agent", 78),
        ("login", 23),
        ("hwnd", 124),
        ("location", (43, 1, 1, 0)),
        ("party", 6),
        ("group", 8),
        ("isolated", True),
    ],
)
def test_full_owner_binding_and_slot_reuse(hr: Any, field: str, value: Any) -> None:
    assert publish(hr)
    assert hr.table.read(replace(hr.owner, **{field: value}), hr.context.instance) is None
    assert hr.table.read(hr.owner, b"x" * 32) is None


def test_real_mutex_contention_does_not_wait_or_refresh(hr: Any) -> None:
    assert publish(hr)
    before = hr.table.read(hr.owner, hr.context.instance)
    entered, release = threading.Event(), threading.Event()

    def hold() -> None:
        with hr.sync.intent_table_lock(hr.module.TABLE_NAME, timeout_ms=0) as acquired:
            assert acquired
            entered.set()
            assert release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(5)
    try:
        hr.clock[0] += 250
        assert not publish(hr)
        assert hr.table.read(hr.owner, hr.context.instance) is None
        hr.table.invalidate(hr.publisher)
    finally:
        release.set()
        thread.join(5)
    assert hr.table.read(hr.owner, hr.context.instance) == before, "failed invalidation relies on bounded expiry"
    hr.clock[0] = before.sampled_at + 750
    assert hr.table.read(hr.owner, hr.context.instance) is None


def test_schema_mismatch_and_partial_commit_are_unavailable_without_repair(hr: Any) -> None:
    assert publish(hr)
    buffer = hr.table._shm.buf
    header = bytes(buffer[: hr.module._HEADER.size])
    buffer[0] = 0
    corrupt = bytes(buffer)
    hr.clock[0] += 250
    assert not publish(hr)
    assert hr.table.read(hr.owner, hr.context.instance) is None
    assert bytes(buffer) == corrupt
    buffer[: hr.module._HEADER.size] = header
    buffer[hr.module._HEADER.size] = 0
    assert hr.table.read(hr.owner, hr.context.instance) is None


def account_row(owner: Any, tick: int) -> Any:
    return NS(
        IsAccount=True,
        IsHero=False,
        IsSlotActive=True,
        LastUpdated=tick,
        Key=NS(EntityType=0, LocalIndex=0, HWND=owner.hwnd),
        AccountEmail=owner.email,
        AgentData=NS(
            CharacterName=owner.character,
            AgentID=owner.agent,
            LoginNumber=owner.login,
            Map=NS(
                MapID=owner.location[0],
                Region=owner.location[1],
                District=owner.location[2],
                Language=owner.location[3],
            ),
        ),
        AgentPartyData=NS(PartyID=owner.party),
        IsolationGroupID=owner.group,
        IsIsolated=owner.isolated,
    )


def test_authorization_and_registry_rechecked_around_read(hr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert publish(hr)
    rows = [NS(IsAccount=False, IsSlotActive=False) for _ in range(64)]
    rows[0] = account_row(hr.owner, hr.clock[0])
    permission = [True]
    accounts = NS(AccountData=rows, GetAuthorizedAccountSlot=variadic_stub(lambda *_: 0 if permission[0] else -1))

    def read():
        return hr.module.read_authorized(
            hr.table, accounts, hr.context, hr.owner.agent, hr.owner.login, hr.owner.character
        )

    assert read() is not None
    permission[0] = False
    assert read() is None
    permission[0] = True
    original = hr.table.read

    def revoke(owner: Any, instance: bytes):
        result = original(owner, instance)
        permission[0] = False
        return result

    monkeypatch.setattr(hr.table, "read", revoke)
    assert read() is None
    monkeypatch.setattr(hr.table, "read", original)
    permission[0] = True
    rows[1] = account_row(hr.owner, hr.clock[0])
    assert read() is None, "ambiguous duplicate account slot"
    rows[1].IsAccount = False
    rows[0].AgentData.CharacterName = "replacement"
    assert read() is None


@pytest.fixture
def publisher(hr: Any, monkeypatch: pytest.MonkeyPatch):
    state = NS(
        profession=9,
        bar=[3431] + [0] * 7,
        effects=[NS(skill_id=883, time_remaining=6000)],
        reads=[],
        context=hr.context,
        uptime=1000,
        during_read=runtime_stub(lambda: None),
    )

    def read_effects(agent: int):
        state.reads.append((agent, hr.clock[0]))
        state.during_read()
        return state.effects

    hr.core.__dict__.update(
        GLOBAL_CACHE=NS(
            ShMem=NS(GetHrHexTable=runtime_stub(lambda: hr.table), GetHrHexOwner=runtime_stub(lambda _: hr.owner))
        ),
        Agent=NS(GetProfessionIDs=runtime_stub(lambda _: (state.profession, 0))),
        Effects=NS(GetEffects=read_effects),
        Map=NS(GetInstanceUptime=runtime_stub(lambda: state.uptime)),
        Player=NS(GetAgentID=runtime_stub(lambda: hr.context.agent)),
        Profession=NS(Paragon=NS(value=9)),
        Skill=NS(GetID=runtime_stub(lambda _: 3431), Flags=NS(IsHex=runtime_stub(lambda skill_id: skill_id == 883))),
        SkillBar=NS(GetSkillIDBySlot=runtime_stub(lambda slot: state.bar[slot - 1])),
    )
    gui = types.ModuleType("PyImGui")
    gui.__dict__.update(begin=runtime_stub(lambda _: False), end=runtime_stub(lambda: None))
    monkeypatch.setitem(sys.modules, "PyImGui", gui)
    monkeypatch.setattr(hr.identity, "current_context", runtime_stub(lambda: state.context))
    widget = load_source("_hr_hex_widget", ROOT / "Widgets/System/HR Hex Observations.py", monkeypatch)
    widget.on_enable()
    yield widget, state
    widget.on_disable()


@pytest.mark.parametrize(
    "profession,bar,expected",
    [(9, [3431], True), (9, [1], False), (5, [3431], False), (9, [3431, None], False), (9, [3431, -1], False)],
)
def test_owner_qualification_uses_actual_equipment_not_echo(
    hr: Any, publisher: Any, profession: int, bar: Any, expected: bool
) -> None:
    widget, state = publisher
    state.profession = profession
    state.bar = bar + [0] * (8 - len(bar))
    widget.draw()
    assert (hr.table.read(hr.owner, hr.context.instance) is not None) == expected
    assert len(state.reads) == int(expected)
    if expected:
        state.bar = [1] * 8
        hr.clock[0] += 250
        widget.draw()
        assert hr.table.read(hr.owner, hr.context.instance) is None


def test_cadence_no_catch_up_timestamp_before_read_and_collapsed_ui(hr: Any, publisher: Any) -> None:
    widget, state = publisher
    widget.configure()  # Collapsed UI does not gate draw.
    widget.draw()
    for elapsed in (1, 100, 249):
        hr.clock[0] = 10_000 + elapsed
        widget.draw()
    assert len(state.reads) == 1
    hr.clock[0] = 10_250
    state.during_read = runtime_stub(lambda: hr.clock.__setitem__(0, hr.clock[0] + 400))
    widget.draw()
    observation = hr.table.read(hr.owner, hr.context.instance)
    assert observation.sampled_at == 10_250
    assert hr.clock[0] == 10_650
    widget.draw()
    assert len(state.reads) == 2
    hr.clock[0] += 250
    state.during_read = runtime_stub(lambda: None)
    widget.draw()
    hr.clock[0] += 5000
    widget.draw()
    widget.draw()
    assert len(state.reads) == 4


@pytest.mark.parametrize("failure", ["slow", "exception", "none", "context", "equipment", "disable", "clock"])
def test_failed_sample_cannot_refresh_positive(hr: Any, publisher: Any, failure: str) -> None:
    widget, state = publisher
    widget.draw()
    first = hr.table.read(hr.owner, hr.context.instance)
    original_publisher = widget._publisher
    hr.clock[0] += 250

    def during_read() -> None:
        if failure == "slow":
            hr.clock[0] += 750
        elif failure == "exception":
            raise RuntimeError("native read failed")
        elif failure == "context":
            state.context = None
        elif failure == "equipment":
            state.bar = [1] * 8
        elif failure == "disable":
            widget.on_disable()
        elif failure == "clock":
            hr.clock[0] -= 1000

    state.during_read = during_read
    if failure == "none":
        state.effects = None
    widget.draw()
    assert hr.table.read(hr.owner, hr.context.instance) is None
    assert original_publisher.sequence == first.sequence


def test_draw_only_routing_and_additive_uncached_shared_memory_entry_points() -> None:
    widget = ast.parse((ROOT / "Widgets/System/HR Hex Observations.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in widget.body if isinstance(node, ast.FunctionDef)}
    assert "update" not in functions and "main" not in functions
    for name in ("on_enable", "on_disable", "configure"):
        calls = {ast.unparse(node.func) for node in ast.walk(functions[name]) if isinstance(node, ast.Call)}
        assert not any(call.startswith(("Agent.", "Player.", "Map.", "Skill.", "SkillBar.")) for call in calls)
        assert "_advance" not in calls and "current_context" not in calls and "_hr_equipped" not in calls
    manager = ast.parse((ROOT / "Py4GWCoreLib/GlobalCache/SharedMemory.py").read_text(encoding="utf-8"))
    methods = {node.name: node for node in ast.walk(manager) if isinstance(node, ast.FunctionDef)}
    for name in ("GetHrHexOwner", "ReadHrHexObservation", "_condition_accounts"):
        assert methods[name].decorator_list == []
    read = ast.unparse(methods["ReadHrHexObservation"])
    assert "self._condition_accounts()" in read and read.count("current_context()") == 2


def test_widget_reload_and_old_cleanup_cannot_invalidate_successor(hr: Any, publisher: Any) -> None:
    widget, _state = publisher
    widget.draw()
    old = widget._publisher
    first = hr.table.read(hr.owner, hr.context.instance)
    path = ROOT / "Widgets/System/HR Hex Observations.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), widget.__dict__)
    assert not old.active and hr.table.read(hr.owner, hr.context.instance) is None
    hr.clock[0] += 250
    widget.on_enable()
    widget.draw()
    successor = hr.table.read(hr.owner, hr.context.instance)
    assert successor is not None and successor.incarnation != first.incarnation
    hr.table.invalidate(old)
    assert hr.table.read(hr.owner, hr.context.instance) == successor


@pytest.mark.parametrize("change", ["character", "party", "map", "instance", "uptime", "clock"])
def test_draw_lifecycle_invalidates_before_sampling_deadline(hr: Any, publisher: Any, change: str) -> None:
    widget, state = publisher
    widget.draw()
    hr.clock[0] += 1
    if change == "character":
        state.context = replace(hr.context, character="Replacement")
    elif change == "party":
        state.context = replace(hr.context, party=6)
    elif change == "map":
        state.context = replace(hr.context, location=(43, 1, 1, 0))
    elif change == "instance":
        state.context = replace(hr.context, instance=b"x" * 32)
    elif change == "uptime":
        state.uptime -= 1
    else:
        hr.clock[0] -= 2
    widget.draw()
    assert len(state.reads) == 1
    assert hr.table.read(hr.owner, hr.context.instance) is None


@pytest.mark.parametrize("change", ["character", "login", "window", "party", "map", "group", "permission", "expiry"])
def test_authorized_read_rejects_owner_mutation_during_copy(
    hr: Any, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    assert publish(hr)
    row = account_row(hr.owner, hr.clock[0])
    rows = [row] + [NS(IsAccount=False, IsSlotActive=False) for _ in range(63)]
    permission = [True]
    accounts = NS(AccountData=rows, GetAuthorizedAccountSlot=variadic_stub(lambda *_: 0 if permission[0] else -1))
    original = hr.table.read

    def mutate(owner: Any, instance: bytes) -> Any:
        result = original(owner, instance)
        if change == "character":
            row.AgentData.CharacterName = "Changed"
        elif change == "login":
            row.AgentData.LoginNumber += 1
        elif change == "window":
            row.Key.HWND += 1
        elif change == "party":
            row.AgentPartyData.PartyID += 1
        elif change == "map":
            row.AgentData.Map.MapID += 1
        elif change == "group":
            row.IsolationGroupID += 1
        elif change == "permission":
            permission[0] = False
        else:
            hr.clock[0] += 750
        return result

    monkeypatch.setattr(hr.table, "read", mutate)
    assert (
        hr.module.read_authorized(hr.table, accounts, hr.context, hr.owner.agent, hr.owner.login, hr.owner.character)
        is None
    )


def test_real_communication_policy_preserves_same_party_exception(hr: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = load_source("_hr_authorization_fixture", ROOT / "tests/test_hex_removal_atomic_claim.py", monkeypatch)
    cls = harness.AllAccounts
    monkeypatch.setattr(harness.ALL_ACCOUNTS_MODULE, "get_uncached_tick_count64", runtime_stub(lambda: hr.clock[0]))
    local = replace(
        hr.owner,
        slot=1,
        agent=88,
        login=33,
        email="mesmer@example.test",
        character="Mesmer",
        group=999,
        hwnd=456,
        isolated=True,
    )
    rows = [account_row(hr.owner, hr.clock[0]), account_row(local, hr.clock[0])]
    rows += [NS(IsAccount=False, IsSlotActive=False, AccountEmail="") for _ in range(62)]
    registry = NS(AccountData=rows)
    registry.GetSlotByEmail = runtime_stub(
        lambda email: next((i for i, row in enumerate(rows) if row.AccountEmail == email), -1)
    )
    for name in ("_get_message_account_snapshot", "_can_communicate", "GetAuthorizedAccountSlot"):
        setattr(registry, name, types.MethodType(getattr(cls, name), registry))
    context = hr.identity.Context(
        local.email,
        local.character,
        local.agent,
        local.login,
        local.hwnd,
        local.location,
        local.party,
        hr.context.instance,
    )
    assert publish(hr)
    assert registry.GetAuthorizedAccountSlot(local.email, hr.owner.email) == 0
    assert hr.module.read_authorized(hr.table, registry, context, 77, 22, hr.owner.character) is not None
    rows[0].AgentPartyData.PartyID += 1
    assert registry.GetAuthorizedAccountSlot(local.email, hr.owner.email) == -1
    assert hr.module.read_authorized(hr.table, registry, context, 77, 22, hr.owner.character) is None


def test_public_read_checks_age_after_last_context_read(hr: Any) -> None:
    path = ROOT / "Py4GWCoreLib/GlobalCache/SharedMemory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    method = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "ReadHrHexObservation"
    )
    code = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace: dict[str, Any] = {"HrHexObservation": hr.module.HrHexObservation, "HR_HEX_MAX_AGE_MS": 750}
    calls: list[int] = []

    def context() -> Any:
        calls.append(hr.clock[0])
        if len(calls) == 2:
            hr.clock[0] += 750
        return hr.context

    assert publish(hr)
    snapshot = hr.table.read(hr.owner, hr.context.instance)
    namespace.update(
        current_context=context,
        get_uncached_tick_count64=runtime_stub(lambda: hr.clock[0]),
        read_hr_hex_authorized=variadic_stub(lambda *_: snapshot),
    )
    exec(compile(code, str(path), "exec"), namespace)
    manager = NS(GetHrHexTable=runtime_stub(lambda: hr.table), _condition_accounts=runtime_stub(lambda: object()))
    assert namespace["ReadHrHexObservation"](manager, 77, 22, hr.owner.character) is None
    assert len(calls) == 2


@pytest.fixture
def publisher_console(publisher: Any, hr: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    widget, state = publisher
    state.console = []
    state.console_hook = runtime_stub(lambda: None)

    def log(sender: str, message: str, _level: int) -> None:
        assert sender == "HR Hex Observations"
        state.console.append((hr.clock[0], message))
        state.console_hook()

    system = types.ModuleType("PySystem")
    system.__dict__["Console"] = NS(Log=log, MessageType=NS(Info=1))
    monkeypatch.setitem(sys.modules, "PySystem", system)
    return widget, state


@pytest.mark.parametrize("kind", ["vm", "unknown_duration", "empty"])
def test_owner_console_reports_only_committed_facts(hr: Any, publisher_console: Any, kind: str) -> None:
    widget, state = publisher_console
    state.effects = (
        [] if kind == "empty" else [NS(skill_id=883, time_remaining=None if kind == "unknown_duration" else 6000)] * 2
    )
    widget.draw()
    observation = hr.table.read(hr.owner, hr.context.instance)
    assert observation is not None and len(state.console) == 1
    fields = dict(part.split("=", 1) for part in state.console[0][1].split()[1:])
    assert fields == {
        "event": "published",
        "trigger": "first",
        "state": "valid_empty" if kind == "empty" else "valid",
        "owner_bind": sha256(hr.owner.digest() + hr.context.instance + observation.incarnation[1]).hexdigest()[:16],
        "pub_nonce": observation.incarnation[1].hex(),
        "pub_started_ms": str(observation.incarnation[0]),
        "context_gen": str(observation.incarnation[2]),
        "sample_seq": str(observation.sequence),
        "sample_tick_ms": str(observation.sampled_at),
        "vm_present": str(int(kind != "empty")),
        "observed_entries": str(observation.census.entry_count),
        "distinct_ids": str(len(observation.census.hex_ids)),
        "vm_sample_ms": "6000" if kind == "vm" else "unknown",
    }
    assert hr.owner.email not in state.console[0][1] and hr.owner.character not in state.console[0][1]
    assert len(state.console[0][1]) <= 600 and len(state.reads) == 1


@pytest.mark.parametrize(
    "remaining,empty",
    [
        (1e308, False),
        (1.2345678901234567e250, False),
        (sys.float_info.max, False),
        (sys.float_info.min, False),
        (float.fromhex("0x0.0000000000001p-1022"), False),
        (1e-200, False),
        (6000.0, False),
        (6000.123456789, False),
        (0.1, False),
        (None, False),
        (None, True),
    ],
)
def test_owner_console_numeric_fidelity_after_full_width_publication(
    hr: Any, publisher_console: Any, monkeypatch: pytest.MonkeyPatch, remaining: float | None, empty: bool
) -> None:
    widget, state = publisher_console
    hr.clock[0] = 2**64 - 1
    owner_publisher = hr.identity.Publisher()
    owner_publisher.sequence = 2**64 - 2
    owner_publisher.generation = 2**32 - 1
    widget._publisher = owner_publisher
    widget._context, widget._uptime, widget._last_tick = hr.context, state.uptime, hr.clock[0]
    # Exercise maximum accepted entry/distinct counts as well as integer widths.
    state.effects = (
        [] if empty else [NS(skill_id=skill_id, time_remaining=remaining) for skill_id in (*range(1, 240), 883)]
    )
    monkeypatch.setattr(hr.core.Skill.Flags, "IsHex", runtime_stub(lambda _: True))
    widget.draw()
    observation = hr.table.read(hr.owner, hr.context.instance)
    assert observation is not None and len(state.console) == 1, (remaining, empty, widget._status, state.console)
    message: str = state.console[0][1]
    tokens = message.split()
    assert tokens[0] == "HR_HEX_OWNER_V1" and len(tokens) == 14, message
    fields = dict(part.split("=", 1) for part in tokens[1:])
    duration = fields.pop("vm_sample_ms")
    assert fields == {
        "event": "published",
        "trigger": "first",
        "state": "valid_empty" if empty else "valid",
        "owner_bind": sha256(hr.owner.digest() + hr.context.instance + observation.incarnation[1]).hexdigest()[:16],
        "pub_nonce": observation.incarnation[1].hex(),
        "pub_started_ms": str(2**64 - 1),
        "context_gen": str(2**32 - 1),
        "sample_seq": str(2**64 - 1),
        "sample_tick_ms": str(2**64 - 1),
        "vm_present": str(int(not empty)),
        "observed_entries": str(observation.census.entry_count),
        "distinct_ids": str(len(observation.census.hex_ids)),
    }, message
    assert observation.incarnation[0] == observation.sequence == observation.sampled_at == 2**64 - 1
    assert observation.incarnation[2] == 2**32 - 1
    assert observation.census.entry_count == len(observation.census.hex_ids) == (0 if empty else 240)
    if remaining is None:
        assert duration == "unknown" and observation.census.vm_remaining_ms is None, message
    else:
        assert float(duration) == observation.census.vm_remaining_ms == remaining, (remaining, duration, message)
        assert len(duration) <= 24, duration
    assert len(message) <= 600 and len(state.reads) == 1, message
    assert hr.owner.email not in message and hr.owner.character not in message


@pytest.mark.parametrize("length", [599, 600, 601])
def test_owner_console_length_guard_preserves_complete_fields(hr: Any, publisher_console: Any, length: int) -> None:
    widget, state = publisher_console
    widget.draw()
    observation = hr.table.read(hr.owner, hr.context.instance)
    assert observation is not None and len(state.console) == 1
    original: str = state.console[0][1]
    expected = original.replace("trigger=first ", "trigger=vm_periodic ")
    # Valid wire fields fit comfortably. Inject an oversized formatter-only
    # sequence to exercise the final guard without publishing invalid wire data.
    sequence = int("9" * (length - len(expected) + 1))
    expected = expected.replace("sample_seq=1 ", f"sample_seq={sequence} ")
    assert len(expected) == length
    formatting_publisher = NS(started=observation.incarnation[0], nonce=observation.incarnation[1], sequence=sequence)
    state.console.clear()
    widget._log_publication(
        formatting_publisher,
        hr.owner,
        hr.context.instance,
        observation.incarnation[2],
        observation.sampled_at,
        observation.census,
        hr.clock[0] + 5000,
    )
    assert len(widget._console_ticks) == 2, "oversized output must still consume the attempted-output budget"
    assert hr.table.read(hr.owner, hr.context.instance) == observation
    if length > 600:
        assert state.console == [], "an oversized structured record must be skipped whole"
    else:
        assert len(state.console) == 1 and state.console[0][1] == expected
        fields = dict(part.split("=", 1) for part in state.console[0][1].split()[1:])
        original_fields = dict(part.split("=", 1) for part in original.split()[1:])
        assert fields == {**original_fields, "trigger": "vm_periodic", "sample_seq": str(sequence)}
        assert (
            int(fields["sample_seq"]) == sequence
            and float(fields["vm_sample_ms"]) == observation.census.vm_remaining_ms
        )


@pytest.mark.parametrize("failure", ["equipment", "profession", "census", "stale", "commit", "owner"])
def test_owner_console_never_reports_failed_or_ineligible_publication(
    hr: Any, publisher_console: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    widget, state = publisher_console
    if failure == "equipment":
        state.bar = [0] * 8
    elif failure == "profession":
        state.profession = 5
    elif failure == "census":
        state.effects = None
    elif failure == "stale":
        state.during_read = runtime_stub(lambda: hr.clock.__setitem__(0, hr.clock[0] + 750))
    elif failure == "owner":
        monkeypatch.setattr(hr.core.GLOBAL_CACHE.ShMem, "GetHrHexOwner", runtime_stub(lambda _: None))
    else:
        monkeypatch.setattr(hr.table, "publish", variadic_stub(lambda *_: False))
    for _ in range(5):
        widget.draw()
        hr.clock[0] += 1000
    assert state.console == [] and hr.table.read(hr.owner, hr.context.instance) is None


def test_owner_console_transitions_periodic_ack_and_valid_empty(hr: Any, publisher_console: Any) -> None:
    widget, state = publisher_console
    widget.draw()
    for _ in range(19):
        hr.clock[0] += 250
        widget.draw()
    assert len(state.console) == 1
    hr.clock[0] += 250
    widget.draw()
    assert "trigger=vm_periodic" in state.console[-1][1] and "sample_seq=21 " in state.console[-1][1]
    hr.clock[0] += 1000
    state.effects = []
    widget.draw()
    assert "trigger=vm_transition state=valid_empty" in state.console[-1][1]
    for _ in range(24):
        hr.clock[0] += 250
        widget.draw()
    assert len(state.console) == 3, "empty observations have no periodic positive-VM heartbeat"
    state.effects = [NS(skill_id=883, time_remaining=6000)]
    widget.draw()  # Not due yet.
    hr.clock[0] += 250
    widget.draw()
    assert len(state.console) == 4 and "trigger=vm_transition state=valid " in state.console[-1][1]


def test_owner_console_context_generation_matches_replacement_commit(hr: Any, publisher_console: Any) -> None:
    widget, state = publisher_console
    widget.draw()
    first = dict(part.split("=", 1) for part in state.console[-1][1].split()[1:])
    hr.clock[0] += 1000
    state.context = replace(hr.context, instance=b"x" * 32)
    widget.draw()
    observation = hr.table.read(hr.owner, state.context.instance)
    current = dict(part.split("=", 1) for part in state.console[-1][1].split()[1:])
    assert current["context_gen"] == str(observation.incarnation[2]) == "1"
    assert current["sample_seq"] == str(observation.sequence) == "2"
    assert current["owner_bind"] != first["owner_bind"] and current["pub_nonce"] == first["pub_nonce"]


def test_owner_console_total_budget_survives_oscillation_disable_and_reload(hr: Any, publisher_console: Any) -> None:
    widget, state = publisher_console
    for index in range(600):
        state.effects = [NS(skill_id=883, time_remaining=6000)] if index % 2 else []
        if index % 8 == 0:
            widget.on_disable()
            widget.on_enable()
        if index == 120:
            path = ROOT / "Widgets/System/HR Hex Observations.py"
            exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), widget.__dict__)
            widget.on_enable()
        widget.draw()
        hr.clock[0] += 250
    times = [tick for tick, _message in state.console]
    assert len(times) > 16
    assert all(sum(tick - 60_000 < other <= tick for other in times) <= 16 for tick in times)
    assert all(right - left >= 1000 for left, right in zip(times, times[1:]))
    assert len(widget._console_ticks) <= 16 and all(len(message) <= 600 for _tick, message in state.console)


@pytest.mark.parametrize("failure", [RuntimeError, MemoryError])
@pytest.mark.parametrize("where", ["format", "console"])
def test_owner_console_failure_preserves_commit_and_cadence(
    hr: Any, publisher_console: Any, monkeypatch: pytest.MonkeyPatch, failure: type[Exception], where: str
) -> None:
    widget, state = publisher_console

    def fail(*_args: Any) -> Any:
        raise failure("injected owner diagnostic failure")

    if where == "format":
        monkeypatch.setattr(widget, "sha256", fail)
    else:
        state.console_hook = fail
    widget.draw()
    observation = hr.table.read(hr.owner, hr.context.instance)
    assert observation is not None and observation.sequence == 1 and observation.incarnation[2] == 0
    assert widget._status == "Publishing owner-observed hexes" and widget._next_sample == 10_250
    hr.clock[0] += 250
    widget.draw()
    assert hr.table.read(hr.owner, hr.context.instance).sequence == 2 and len(state.reads) == 2


def test_owner_console_failure_cannot_invalidate_a_successor(hr: Any, publisher_console: Any) -> None:
    widget, state = publisher_console
    successors: list[Any] = []

    def replace_then_fail() -> None:
        hr.clock[0] += 1
        successor = hr.identity.Publisher()
        assert hr.table.publish(successor, hr.owner, hr.context.instance, hr.clock[0], census(hr))
        successors.append(successor)
        raise RuntimeError("console failed after another publisher committed")

    state.console_hook = replace_then_fail
    widget.draw()
    observed = hr.table.read(hr.owner, hr.context.instance)
    assert observed is not None and observed.incarnation[1] == successors[0].nonce
    assert widget._publisher.generation == 0 and widget._next_sample == 10_250


def test_owner_console_adds_no_probes_and_runs_outside_table_mutex(
    hr: Any, publisher_console: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget, state = publisher_console
    calls: dict[str, int] = {}

    def counted(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            calls[name] = calls.get(name, 0) + 1
            return function(*args, **kwargs)

        return call

    for name, owner, attribute in (
        ("tick", widget, "get_uncached_tick_count64"),
        ("context", widget, "current_context"),
        ("owner", hr.core.GLOBAL_CACHE.ShMem, "GetHrHexOwner"),
        ("uptime", hr.core.Map, "GetInstanceUptime"),
        ("player", hr.core.Player, "GetAgentID"),
        ("profession", hr.core.Agent, "GetProfessionIDs"),
        ("skill", hr.core.Skill, "GetID"),
        ("slot", hr.core.SkillBar, "GetSkillIDBySlot"),
        ("effects", hr.core.Effects, "GetEffects"),
        ("classification", hr.core.Skill.Flags, "IsHex"),
        ("shared_read", hr.table, "read"),
    ):
        monkeypatch.setattr(owner, attribute, counted(name, getattr(owner, attribute)))
    acquired: list[bool] = []

    def probe() -> None:
        def inspect() -> None:
            with hr.sync.intent_table_lock(hr.module.TABLE_NAME, timeout_ms=0) as owned:
                acquired.append(owned)

        thread = threading.Thread(target=inspect)
        thread.start()
        thread.join(5)
        assert not thread.is_alive()

    state.console_hook = probe
    widget.draw()
    assert acquired == [True] and len(state.console) == 1
    assert calls == {
        "tick": 3,
        "context": 2,
        "owner": 2,
        "uptime": 1,
        "player": 2,
        "profession": 2,
        "skill": 2,
        "slot": 16,
        "effects": 1,
        "classification": 1,
    }
