"""Real fixed mapping, account authorization and widget code; no injected client."""

from __future__ import annotations

import ast
import importlib
import os
import sys
from collections.abc import Callable
from collections.abc import Iterator
from dataclasses import replace
from threading import Event
from threading import Thread
from types import ModuleType
from types import SimpleNamespace
from typing import Any
from typing import cast
from uuid import uuid4

import pytest
from test_account_publication import ROOT
from test_account_publication import WIRE
from test_account_publication import account_world as _account_world_fixture
from test_account_publication import load_module

account_world = _account_world_fixture


@pytest.fixture
def condition_world(account_world: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    r = account_world
    r.module = load_module("_publication_wire.ConditionObservations", WIRE / "ConditionObservations.py", monkeypatch)
    monkeypatch.setattr(r.module, "TABLE_NAME", f"Py4GW_ConditionTest_{uuid4().hex}")
    monkeypatch.setattr(r.module, "get_uncached_tick_count64", lambda: r.clock.uncached)
    for index in (0, 1):
        row = r.table.AccountData[index]
        row.Key.HWND = 100 + index
        r.table.Keys[index] = row.Key
        row.SlotNumber = index
        row.AgentData.CharacterName = f"Character {index}"
        row.AgentData.AgentID = row.AgentData.LoginNumber = index + 1
        row.AgentPartyData.PartyID = 7
        row.AgentData.Map.MapID = 1
        row.AgentData.Map.Region = 1
        row.AgentData.Map.District = 1
    r.clock.hwnd = 100
    r.local = r.module.Context(r.sender, "Character 0", 1, 1, 100, (1, 1, 1, 0), 7, b"i" * 32)
    r.owner = r.module.account_owner(r.table, 1)
    r.mapping = r.module.ConditionTable()
    r.publisher = r.module.Publisher()
    r.manager = manager_subject(r)
    yield r
    r.mapping.close()


def manager_subject(r: Any) -> Any:
    """Execute the actual narrow manager integration over the real registry view."""
    source = ROOT / "Py4GWCoreLib/GlobalCache/SharedMemory.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    names = {"GetConditionTable", "_condition_accounts", "GetConditionOwner", "ReadConditionObservation"}
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace: dict[str, Any] = {**vars(r.module), "AllAccounts": type(r.table), "current_context": lambda: r.local}
    exec(
        compile(
            ast.fix_missing_locations(
                ast.Module(
                    [
                        ast.ImportFrom("__future__", [ast.alias("annotations")], 0),
                        cls,
                    ],
                    [],
                )
            ),
            str(source),
            "exec",
        ),
        namespace,
    )
    manager = namespace[cls.name]()
    manager.shm = SimpleNamespace(buf=memoryview(r.table))
    manager._attach = lambda: True
    manager._condition_table = r.mapping
    return manager


def publish(r: Any, *conditions: str) -> bool:
    return bool(r.mapping.publish(r.publisher, r.owner, r.local.instance, r.clock.uncached, frozenset(conditions)))


def read(r: Any) -> Any:
    return r.manager.ReadConditionObservation(2, 2, "Character 1")


def test_complete_empty_unknown_and_removal(condition_world: Any) -> None:
    r = condition_world
    assert read(r) is None  # Reader never creates the optional mapping.
    assert publish(r, "Blind", "Cracked_Armor")
    first = read(r)
    assert first.conditions == frozenset({"Blind", "Cracked_Armor"})
    assert publish(r, "Cracked_Armor")
    assert read(r).conditions == frozenset({"Cracked_Armor"})
    assert publish(r)
    assert read(r).conditions == frozenset()
    assert r.mapping.publish(r.publisher, r.owner, r.local.instance, r.clock.uncached, None)
    assert read(r) is None
    assert first.conditions == frozenset({"Blind", "Cracked_Armor"}), "reads must be immutable copies"


@pytest.mark.parametrize("age,allowed", [(-1, False), (0, True), (749, True), (750, False), (751, False)])
def test_full_width_sample_age(condition_world: Any, age: int, allowed: bool) -> None:
    r = condition_world
    r.clock.uncached += 1 << 32
    for row in r.table.AccountData[:2]:
        row.LastUpdated = r.clock.uncached & 0xFFFFFFFF
    assert publish(r, "Blind")
    r.clock.uncached += age
    assert (read(r) is not None) is allowed, (age, allowed)


@pytest.mark.parametrize("field", ["email", "character", "agent", "login", "hwnd", "map", "party", "group", "isolated"])
def test_owner_identity_changes_are_unknown(condition_world: Any, field: str) -> None:
    r = condition_world
    assert publish(r, "Blind")
    row = r.table.AccountData[1]
    changes = {
        "email": (row, "AccountEmail", "replacement@example.invalid"),
        "character": (row.AgentData, "CharacterName", "Replacement"),
        "agent": (row.AgentData, "AgentID", 55),
        "login": (row.AgentData, "LoginNumber", 55),
        "hwnd": (row.Key, "HWND", 500),
        "map": (row.AgentData.Map, "District", 2),
        "party": (row.AgentPartyData, "PartyID", 8),
        "group": (row, "IsolationGroupID", 8),
        "isolated": (row, "IsIsolated", True),
    }
    obj, name, value = changes[field]
    setattr(obj, name, value)
    assert read(r) is None, field


def test_duplicate_slots_instance_change_and_expired_registry(condition_world: Any) -> None:
    r = condition_world
    assert publish(r, "Blind")
    r.table.AccountData[2] = r.table.AccountData[1]
    assert read(r) is None
    r.table.AccountData[2].IsSlotActive = False
    r.local = replace(r.local, instance=b"j" * 32)
    assert read(r) is None
    r.local = replace(r.local, instance=b"i" * 32)
    r.table.AccountData[1].LastUpdated = 1
    assert read(r) is None


def test_restart_old_writer_cleanup_and_out_of_order(condition_world: Any) -> None:
    r = condition_world
    assert publish(r, "Blind")
    first = read(r)
    old = r.publisher
    r.clock.uncached += 1
    r.publisher = r.module.Publisher()
    assert publish(r)
    assert read(r).incarnation != first.incarnation
    assert not r.mapping.publish(old, r.owner, r.local.instance, r.clock.uncached, frozenset({"Blind"}))
    r.mapping.invalidate(old)
    assert read(r).conditions == frozenset()


def test_late_sample_cannot_resurrect_removed_condition(condition_world: Any) -> None:
    r = condition_world
    assert publish(r, "Blind")
    earlier = r.clock.uncached
    r.clock.uncached += 250
    assert publish(r)
    assert not r.mapping.publish(r.publisher, r.owner, r.local.instance, earlier, frozenset({"Blind"}))
    assert read(r).conditions == frozenset()
    r.publisher.sequence = 0
    assert not publish(r, "Blind")
    assert read(r).conditions == frozenset()


def test_schema_partial_record_and_independent_slots(condition_world: Any) -> None:
    r = condition_world
    assert publish(r, "Blind")
    other = r.module.account_owner(r.table, 0)
    writer = r.module.Publisher()
    assert r.mapping.publish(writer, other, r.local.instance, r.clock.uncached, frozenset({"Poison"}))
    assert r.mapping.read(other, r.local.instance).conditions == frozenset({"Poison"})
    offset = r.module._HEADER.size + r.module._RECORD.size
    r.mapping._shm.buf[offset] = 0  # Interrupted writer before commit.
    assert read(r) is None
    assert r.mapping.read(other, r.local.instance) is not None
    r.mapping._shm.buf[0] = 0
    assert read(r) is None and not publish(r, "Blind")


def test_real_zero_wait_mutex_and_close_only_lifetime(condition_world: Any) -> None:
    r = condition_world
    assert publish(r, "Blind")
    attached = r.module.ConditionTable()
    assert attached.read(r.owner, r.local.instance) is not None
    held, release = Event(), Event()

    def hold() -> None:
        with r.module.intent_table_lock(r.module.TABLE_NAME, timeout_ms=0) as acquired:
            assert acquired
            held.set()
            assert release.wait(5)

    thread = Thread(target=hold)
    thread.start()
    try:
        assert held.wait(5)
        assert read(r) is None and not publish(r, "Poison")
    finally:
        release.set()
        thread.join(5)
    r.mapping.close()
    assert attached.read(r.owner, r.local.instance).conditions == frozenset({"Blind"})
    attached.close()


def test_missing_registry_and_mapping_failure_are_unknown(
    condition_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = condition_world
    r.manager._attach = lambda: False
    assert read(r) is None
    r.manager._attach = lambda: True

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("mapping unavailable")

    monkeypatch.setattr(r.module.shared_memory, "SharedMemory", fail)
    assert read(r) is None and not publish(r, "Blind")


@pytest.fixture
def publisher_widget(condition_world: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    r = condition_world
    r.local = replace(r.local, email=r.receiver, character="Character 1", agent=2, login=2, hwnd=101)
    r.clock.hwnd = 101
    r.ready, r.uptime, r.effects, r.reads, r.after_read = True, 1000, [], [], None
    r.outpost, r.visible, r.clicked, r.pause = False, False, False, None
    r.players = [SimpleNamespace(login_number=login, is_connected=True) for login in (1, 2)]
    core: Any = ModuleType("Py4GWCoreLib")
    core.__path__ = []
    core.GLOBAL_CACHE = SimpleNamespace(ShMem=r.manager)
    core.Map = SimpleNamespace(GetInstanceUptime=lambda: r.uptime, IsOutpost=lambda: r.outpost)
    core.Player = SimpleNamespace(GetAgentID=lambda: 2)

    def identity(agent: int) -> int:
        return agent

    def character(agent: int) -> str:
        return f"Character {agent - 1}"

    core.Agent = SimpleNamespace(GetLoginNumber=identity, GetNameByID=character)
    core.Party = SimpleNamespace(
        GetPlayers=lambda: r.players, Players=SimpleNamespace(GetAgentIDByLoginNumber=identity)
    )
    ids = {name: index + 1 for index, name in enumerate(r.module.CONDITIONS)}
    core.Skill = SimpleNamespace(GetID=ids.__getitem__)

    def effects(agent: int) -> Any:
        assert agent == 2
        r.reads.append((r.clock.uncached, agent))
        if r.after_read is not None:
            r.after_read()
        if isinstance(r.effects, Exception):
            raise r.effects
        return r.effects

    core.Effects = SimpleNamespace(GetEffects=effects)
    imgui: Any = ModuleType("PyImGui")

    def begin(_name: str) -> bool:
        return bool(r.visible)

    def checkbox(_label: str, value: bool) -> bool:
        assert _label == "Pause publishing (this session)"
        return value if r.pause is None else bool(r.pause)

    def button(label: str) -> bool:
        assert label == "Check publication status"
        clicked, r.clicked = r.clicked, False
        return bool(clicked)

    def text(_value: str) -> None:
        pass

    imgui.begin = begin
    imgui.end = lambda: None
    imgui.checkbox, imgui.button, imgui.text = checkbox, button, text
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", core)
    monkeypatch.setitem(sys.modules, "PyImGui", imgui)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations", r.module)
    clock: Any = ModuleType("Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync")
    clock.get_uncached_tick_count64 = lambda: r.clock.uncached
    monkeypatch.setitem(sys.modules, clock.__name__, clock)
    monkeypatch.setattr(r.module, "current_context", lambda: r.local if r.ready else None)
    r.widget = load_module("_condition_widget", ROOT / "Widgets/System/Condition Observations.py", monkeypatch)
    r.widget.on_enable()
    r.core, r.imgui = core, imgui
    r.ids = ids
    return r


def click_status(r: Any) -> str:
    before = len(r.logs)
    r.visible = r.clicked = True
    r.widget.configure()
    assert len(r.logs) == before, "configure must defer native status reads to Draw"
    r.widget.draw()
    assert len(r.logs) == before + 1
    sender, message, level = r.logs[-1]
    assert sender == "ConditionObservations" and level == 0
    assert message.startswith("ConditionObservations STATUS ")
    return str(message)


def publish_peer(r: Any, *conditions: str) -> None:
    owner = r.module.account_owner(r.table, 0)
    assert r.mapping.publish(r.publisher, owner, r.local.instance, r.clock.uncached, frozenset(conditions))


@pytest.mark.parametrize("opted_in", [False, True])
def test_manual_status_explains_outpost_without_publishing(publisher_widget: Any, opted_in: bool) -> None:
    r = publisher_widget
    r.outpost, r.ready = True, False
    r.widget._publishing = opted_in
    message = click_status(r)
    assert ("LOCAL_WAITING_FOR_EXPLORABLE" if opted_in else "LOCAL_DISABLED") in message
    assert "location=OUTPOST; publication=NOT_EXPECTED; remote=NOT_CHECKED" in message
    assert r.reads == [] and r.mapping._shm is None


def test_manual_status_verifies_current_local_publisher(publisher_widget: Any) -> None:
    r = publisher_widget
    r.widget.draw()
    r.clock.uncached += 100
    before = bytes(r.mapping._shm.buf)
    sequence = r.widget._publisher.sequence
    message = click_status(r)
    assert "LOCAL_PUBLISHING(FRESH_VALID_EMPTY(age_ms=100,count=0,instance=MATCH))" in message
    assert r.widget._publisher.sequence == sequence and bytes(r.mapping._shm.buf) == before
    assert r.reads == [(10000, 2)]
    r.mapping.invalidate(r.widget._publisher)
    assert "LOCAL_SUPERSEDED" in click_status(r)


@pytest.mark.parametrize("conditions", [(), ("Blind", "Cracked_Armor")])
def test_manual_status_reads_peer_with_local_publication_off(
    publisher_widget: Any, conditions: tuple[str, ...]
) -> None:
    r = publisher_widget
    r.widget._publishing = False
    publish_peer(r, *conditions)
    before, registry = bytes(r.mapping._shm.buf), bytes(r.table)
    r.clock.uncached += 123
    accepted = r.manager.ReadConditionObservation(1, 1, "Character 0")
    assert accepted is not None and accepted.conditions == frozenset(conditions)
    message = click_status(r)
    expected = "REMOTE_FRESH_WITH_CONDITIONS" if conditions else "REMOTE_FRESH_VALID_EMPTY"
    assert "LOCAL_DISABLED" in message and f"party[1]={expected}" in message
    assert f"age_ms=123,count={len(conditions)},instance=MATCH" in message
    assert r.reads == [] and r.widget._publisher is None
    assert bytes(r.mapping._shm.buf) == before and bytes(r.table) == registry
    assert r.sender not in message and r.receiver not in message and "Character" not in message


@pytest.mark.parametrize("fault", ["missing", "expired", "instance", "unauthorized", "identity", "invalid", "attach"])
def test_manual_rejections_match_consumer_without_guessing(publisher_widget: Any, fault: str) -> None:
    r = publisher_widget
    r.widget._publishing = False
    if fault != "missing":
        publish_peer(r, "Blind")
    if fault == "expired":
        r.clock.uncached += 750
    elif fault == "instance":
        r.local = replace(r.local, instance=b"j" * 32)
    elif fault == "unauthorized":
        r.table.AccountData[0].AgentPartyData.PartyID = 8
        r.table.AccountData[0].IsolationGroupID = 2
        r.table.AccountData[1].IsolationGroupID = 1
        assert r.table.GetAuthorizedAccountSlot(r.receiver, r.sender) == -1
    elif fault == "identity":
        r.table.AccountData[0].AgentData.CharacterName = "Changed"
    elif fault == "invalid":
        r.mapping.invalidate(r.publisher)
    elif fault == "attach":
        r.manager._attach = lambda: False
    before = bytes(r.mapping._shm.buf) if r.mapping._shm is not None else None
    assert r.manager.ReadConditionObservation(1, 1, "Character 0") is None
    message = click_status(r)
    assert "party[1]=REMOTE_REJECTED_OR_UNAVAILABLE(instance=UNVERIFIED)" in message, (fault, message)
    assert "instance=MATCH" not in message and r.reads == []
    after = bytes(r.mapping._shm.buf) if r.mapping._shm is not None else None
    assert after == before, fault


def test_status_output_is_manual_bounded_and_does_not_change_cadence(publisher_widget: Any) -> None:
    r = publisher_widget
    r.visible = True
    for delta in (0, 100, 150):
        r.clock.uncached += delta
        r.widget.configure()
        r.widget.draw()
    assert r.logs == [] and r.reads == [(10000, 2), (10250, 2)]
    r.players = [SimpleNamespace(login_number=login, is_connected=True) for login in range(1, 101)]
    message = click_status(r)
    assert "party_scan=FIRST_12_ONLY" in message
    assert message.count("party[") == 11 and len(message) < 2048 and "\n" not in message
    for _ in range(5):
        r.widget.draw()
        r.widget.configure()
    assert len(r.logs) == 1 and r.reads == [(10000, 2), (10250, 2)]


def test_disabled_widget_cancels_pending_status(publisher_widget: Any) -> None:
    r = publisher_widget
    r.visible = r.clicked = True
    r.widget.configure()
    assert r.widget._status_requested
    r.widget.on_disable()
    r.widget.draw()
    assert not r.widget._status_requested and r.logs == [] and r.reads == []


def test_local_status_does_not_claim_another_publisher(publisher_widget: Any) -> None:
    r = publisher_widget
    r.widget.draw()
    r.clock.uncached += 1
    r.publisher = r.module.Publisher()
    assert publish(r, "Blind")  # Different nonce from the widget's publisher.
    assert "LOCAL_PUBLICATION_UNVERIFIED" in click_status(r)


def test_status_failure_does_not_log_private_exception_text(
    publisher_widget: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = publisher_widget
    r.widget._publishing = False

    def fail(_agent: int, _login: int, _character: str) -> Any:
        raise RuntimeError(f"private {r.sender} {r.local.hwnd} {r.local.instance!r}")

    monkeypatch.setattr(r.manager, "ReadConditionObservation", fail)
    message = click_status(r)
    assert "REMOTE_REJECTED_OR_UNAVAILABLE" in message
    assert r.sender not in message and str(r.local.hwnd) not in message and "private" not in message


def test_widget_single_enumeration_cadence_and_unknown(publisher_widget: Any) -> None:
    r = publisher_widget
    r.effects = [SimpleNamespace(skill_id=r.ids["Blind"]), SimpleNamespace(skill_id=r.ids["Cracked_Armor"])]
    for delta in (0, 100, 149, 1):
        r.clock.uncached += delta
        r.widget.configure()  # Collapsed UI never owns advancement.
        r.widget.draw()
    assert r.reads == [(10000, 2), (10250, 2)]
    assert r.mapping.read(r.owner, r.local.instance).conditions == frozenset({"Blind", "Cracked_Armor"})
    r.clock.uncached += 250
    r.effects = RuntimeError("native list unavailable")
    r.widget.draw()
    assert r.mapping.read(r.owner, r.local.instance) is None
    r.clock.uncached += 250
    r.effects = []
    r.widget.draw()
    assert r.mapping.read(r.owner, r.local.instance).conditions == frozenset()


def test_optional_widget_and_reentrant_draw(publisher_widget: Any) -> None:
    r = publisher_widget
    r.widget.on_disable()
    r.widget.draw()
    assert r.reads == [] and r.widget._publisher is None
    r.widget.on_enable()

    def reenter() -> None:
        r.clock.uncached += 300
        r.widget.draw()

    r.after_read = reenter
    r.widget.draw()
    assert len(r.reads) == 1
    assert r.mapping.read(r.owner, r.local.instance).conditions == frozenset()


@pytest.mark.parametrize("effects", [None, [SimpleNamespace()], [SimpleNamespace(skill_id=0)]])
def test_unusable_owner_list_is_not_empty(publisher_widget: Any, effects: Any) -> None:
    r = publisher_widget
    r.widget.draw()
    r.effects = effects
    r.clock.uncached += 250
    r.widget.draw()
    assert r.mapping.read(r.owner, r.local.instance) is None


@pytest.mark.parametrize("unavailable", ["outpost", "loading", "not_ready", "cinematic", "character_selection"])
def test_consumer_context_never_calls_loaded_or_uptime_facades(
    condition_world: Any,
    monkeypatch: pytest.MonkeyPatch,
    unavailable: str,
) -> None:
    r = condition_world

    class ForbiddenPlayer:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"Consumer reached Player.{name} from Update")

    core: Any = ModuleType("Py4GWCoreLib")
    core.__path__ = []
    core.Player = ForbiddenPlayer()

    def name(_agent: int) -> str:
        return "Character 0"

    def login(_agent: int) -> int:
        return 1

    def valid(_agent: int) -> bool:
        return True

    core.Agent = SimpleNamespace(GetNameByID=name, GetLoginNumber=login, IsValid=valid)
    core.Party = SimpleNamespace(
        GetPartyID=lambda: 7,
        GetPlayers=lambda: [SimpleNamespace(login_number=1, is_connected=True)],
    )
    core.Map = SimpleNamespace(
        IsMapReady=lambda: True,
        IsMapLoading=lambda: False,
        IsExplorable=lambda: True,
        IsInCinematic=lambda: False,
        GetMapID=lambda: 1,
        GetRegion=lambda: (1, ""),
        GetDistrict=lambda: 1,
        GetLanguage=lambda: (0, ""),
    )
    char = SimpleNamespace(token1=42, host=b"h" * 24, player_email_str=r.sender)
    context: Any = ModuleType("Py4GWCoreLib.Context")
    context.GWContext = SimpleNamespace(
        Char=SimpleNamespace(GetContext=lambda: char),
        World=SimpleNamespace(
            GetContext=lambda: SimpleNamespace(player_controlled_character=SimpleNamespace(agent_id=1))
        ),
    )
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", core)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Context", context)
    observed = r.module.current_context()
    assert observed is not None and observed.agent == 1 and observed.email == r.sender
    char.token1 += 1
    assert r.module.current_context().instance != observed.instance
    if unavailable == "character_selection":
        context.GWContext.Char.GetContext = lambda: None
    else:
        map_gate = {
            "outpost": "IsExplorable",
            "loading": "IsMapLoading",
            "not_ready": "IsMapReady",
            "cinematic": "IsInCinematic",
        }[unavailable]
        setattr(core.Map, map_gate, lambda: unavailable in {"loading", "cinematic"})
    assert r.module.current_context() is None
    context.GWContext.Char.GetContext = lambda: char
    core.Map.IsMapReady = core.Map.IsExplorable = lambda: True
    core.Map.IsMapLoading = core.Map.IsInCinematic = lambda: False
    char.host = bytes(24)
    assert r.module.current_context() is None


@pytest.mark.parametrize("loss", ["disable", "map", "during_read", "uptime"])
def test_widget_lifecycle_and_inflight_disable(publisher_widget: Any, loss: str) -> None:
    r = publisher_widget
    r.widget.draw()
    assert r.mapping.read(r.owner, r.local.instance) is not None
    if loss == "disable":
        r.widget.on_disable()
    elif loss == "map":
        r.ready = False
    elif loss == "uptime":
        r.uptime = 1
    else:
        r.after_read = r.widget.on_disable
        r.clock.uncached += 250
    r.widget.draw()
    assert r.mapping.read(r.owner, r.local.instance) is None
    assert len(r.reads) == (2 if loss == "during_read" else 1)


def test_callback_and_transitive_uptime_boundary(publisher_widget: Any) -> None:
    r = publisher_widget
    assert not hasattr(r.widget, "update") and not hasattr(r.widget, "main")
    widget_tree = ast.parse((ROOT / "Widgets/System/Condition Observations.py").read_text())
    calls = [n.func for n in ast.walk(widget_tree) if isinstance(n, ast.Call)]
    assert not any(isinstance(n, ast.Attribute) and n.attr in ("IsPlayerLoaded", "GetFPSLimit") for n in calls)
    tree = ast.parse((ROOT / "Py4GWCoreLib/Map.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Map")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "GetInstanceUptime")
    fn.decorator_list = []
    namespace: dict[str, Any] = {
        "GWContext": SimpleNamespace(AccAgent=SimpleNamespace(GetContext=lambda: SimpleNamespace(instance_timer=42)))
    }
    exec(compile(ast.Module([fn], []), "map_uptime", "exec"), namespace)
    assert namespace["GetInstanceUptime"]() == 42


@pytest.mark.parametrize("saved_enabled", [False, True])
def test_actual_widget_manager_starts_system_publisher_only_in_draw(
    publisher_widget: Any,
    monkeypatch: pytest.MonkeyPatch,
    saved_enabled: bool,
) -> None:
    r = publisher_widget
    callbacks: list[tuple[str, Callable[[], Any]]] = []

    def register(_name: str, _phase: str, fn: Callable[[], Any], *, priority: int, context: str) -> int:
        assert priority == 99
        callbacks.append((context, fn))
        return len(callbacks)

    def noop(_name: str) -> None:
        pass

    source = ROOT / "Py4GWCoreLib/py4gwcorelib_src/WidgetManager.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    namespace: dict[str, Any] = {
        "Callable": Callable,
        "os": os,
        "sys": sys,
        "importlib": importlib,
        "base_path": str(ROOT),
        "_bump_widgets_revision": lambda: None,
        "PyCallback": SimpleNamespace(
            PyCallback=SimpleNamespace(Register=register),
            Phase=SimpleNamespace(Update="Update"),
            Context=SimpleNamespace(Update="Update", Draw="Draw", Main="Main"),
        ),
        "_get_profiling": lambda: SimpleNamespace(enabled=False, register=noop),
    }
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Widget")
    cls.decorator_list = []
    cls.body = [
        n
        for n in cls.body
        if isinstance(n, ast.FunctionDef)
        and n.name
        in {
            "enabled",
            "load_module",
            "RegisterCallbacks",
            "enable",
            "disable",
        }
    ]
    apply = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_apply_ini_configuration")
    exec(compile(ast.Module([cls, apply], []), str(source), "exec"), namespace)
    for name in (
        "PyPing",
        "PyGameThread",
        "PyDXOverlay",
        "PyAgentEvents",
        "py4gw_widget_System_Condition Observations_py",
    ):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    widget = namespace["Widget"]()
    widget.module = None
    widget._Widget__enabled = False
    widget.widget_path = "System"
    widget.folder_script_name = "System/Condition Observations.py"
    widget.script_path = str(ROOT / "Widgets/System/Condition Observations.py")
    widget.update_callback_id = widget.draw_callback_id = widget.main_callback_id = 0
    widget.ResumeCallbacks = widget.PauseCallbacks = lambda: None
    persisted: list[tuple[str, str, bool]] = []

    def get_bool(_section: str, _key: str, _default: bool) -> bool:
        return saved_enabled

    def set_value(section: str, key: str, value: bool) -> None:
        persisted.append((section, key, value))

    settings = SimpleNamespace(get_bool=get_bool, set=set_value)
    manager = SimpleNamespace(
        widgets={widget.folder_script_name: widget},
        _manager_cfg=lambda: settings,
        _log_success=noop,
        _log_error=pytest.fail,
    )
    assert (ROOT / "Widgets/System/.widget").is_file()
    namespace["_apply_ini_configuration"](manager)
    assert widget.enabled and widget.category == "System" and widget.optional
    assert persisted == ([] if saved_enabled else [("Widget:System/Condition Observations.py", "enabled", True)])
    r.widget = cast(Any, widget.module)
    assert r.widget._publishing and r.widget._enabled
    assert not r.reads and not r.logs  # Module loading/enabling does no native sampling.
    assert [context for context, _ in callbacks] == ["Draw"]
    for context, callback in callbacks:
        if context == "Update":
            callback()
    assert r.reads == [] and r.logs == []
    callbacks[0][1]()
    assert r.reads == [(10000, 2)] and r.logs == []  # No configuration/UI interaction.
    namespace["_apply_ini_configuration"](manager)
    assert len(callbacks) == 1
    r.visible = r.clicked = True
    r.widget.configure()
    callbacks[0][1]()
    assert r.reads == [(10000, 2)] and len(r.logs) == 1
    widget.disable()
    assert r.mapping.read(r.owner, r.local.instance) is None


@pytest.mark.parametrize("ending", ["reload", "restart", "disable_enable"])
def test_automatic_publisher_restart_and_stale_writer(
    publisher_widget: Any, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    r = publisher_widget
    r.widget.draw()
    old = r.widget._publisher
    r.clock.uncached += 250
    if ending == "reload":
        exec(
            compile(
                (ROOT / "Widgets/System/Condition Observations.py").read_text(encoding="utf-8"),
                r.widget.__file__,
                "exec",
            ),
            cast(dict[str, Any], vars(r.widget)),
        )
    else:
        r.widget.on_disable()
        if ending == "restart":
            r.widget = load_module(
                "_restarted_condition_widget", ROOT / "Widgets/System/Condition Observations.py", monkeypatch
            )
    assert not old.active and r.mapping.read(r.owner, r.local.instance) is None
    r.widget.on_enable()
    r.widget.draw()
    current = r.mapping.read(r.owner, r.local.instance)
    assert current is not None and current.incarnation[1] != old.nonce
    assert not r.mapping.publish(old, r.owner, r.local.instance, r.clock.uncached, frozenset({"Blind"}))
    r.mapping.invalidate(old)
    assert r.mapping.read(r.owner, r.local.instance) == current


@pytest.mark.parametrize("paused_inflight", [False, True])
def test_session_pause_invalidation_and_fresh_default(
    publisher_widget: Any,
    monkeypatch: pytest.MonkeyPatch,
    paused_inflight: bool,
) -> None:
    r = publisher_widget
    r.widget.draw()
    r.visible, r.pause = True, True
    if paused_inflight:
        r.after_read = r.widget.configure
        r.clock.uncached += 250
        r.widget.draw()
        r.after_read = None
    else:
        r.widget.configure()
    assert not r.widget._publishing and r.mapping.read(r.owner, r.local.instance) is None
    reads = list(r.reads)
    for _ in range(10):
        r.clock.uncached += 250
        r.widget.draw()
    assert r.reads == reads and not r.logs
    assert "LOCAL_DISABLED" in click_status(r)
    r.widget.on_disable()
    r.widget.on_enable()
    r.widget.draw()
    assert r.reads == reads  # A troubleshooting pause lasts for this module session.
    r.pause = False
    r.widget.configure()
    r.widget.draw()
    assert len(r.reads) == len(reads) + 1
    r.pause = True
    r.widget.configure()
    r.widget.on_disable()
    r.clock.uncached += 250
    r.widget = load_module("_fresh_condition_widget", ROOT / "Widgets/System/Condition Observations.py", monkeypatch)
    r.widget.on_enable()
    r.widget.draw()  # No configuration callback; stale UI input cannot persist a pause.
    assert r.widget._publishing and r.mapping.read(r.owner, r.local.instance) is not None


@pytest.mark.parametrize("change", ["character", "instance", "logout"])
def test_automatic_publisher_invalidates_context_and_resumes(publisher_widget: Any, change: str) -> None:
    r = publisher_widget
    r.widget.draw()
    old_owner, old_instance = r.owner, r.local.instance
    first = r.mapping.read(old_owner, old_instance)
    if change == "character":
        r.local = replace(r.local, character="Replacement")
        r.table.AccountData[1].AgentData.CharacterName = "Replacement"
    elif change == "instance":
        r.local = replace(r.local, instance=b"j" * 32)
    else:
        r.ready = False
    r.widget.draw()  # Context invalidation is not delayed by the sampling throttle.
    assert r.mapping.read(old_owner, old_instance) is None and len(r.reads) == 1
    r.clock.uncached += 250
    r.ready = True
    r.widget.draw()
    current_owner = r.module.account_owner(r.table, 1)
    current = r.mapping.read(current_owner, r.local.instance)
    assert current is not None and current.incarnation != first.incarnation
    assert len(r.reads) == 2 and not r.logs


def test_independent_clients_publish_own_slots_without_ui(
    publisher_widget: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = publisher_widget
    other = SimpleNamespace(**vars(r))
    other.local = replace(r.local, email=r.sender, character="Character 0", agent=1, login=1, hwnd=100)
    other.mapping = r.module.ConditionTable()
    other.manager = manager_subject(other)
    other_reads: list[int] = []

    def effects(agent: int) -> list[Any]:
        assert agent == 1
        other_reads.append(agent)
        return [SimpleNamespace(skill_id=r.ids["Blind"])]

    core: Any = ModuleType("Py4GWCoreLib")
    core.__dict__.update(vars(r.core))
    core.GLOBAL_CACHE = SimpleNamespace(ShMem=other.manager)
    core.Player = SimpleNamespace(GetAgentID=lambda: 1)
    core.Effects = SimpleNamespace(GetEffects=effects)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib", core)
    monkeypatch.setattr(r.module, "current_context", lambda: other.local)
    other.widget = load_module(
        "_other_client_condition_widget", ROOT / "Widgets/System/Condition Observations.py", monkeypatch
    )
    try:
        other.widget.on_enable()
        r.widget.draw()
        other.widget.draw()
        assert r.reads == [(10000, 2)] and other_reads == [1]
        assert r.widget._publisher is not other.widget._publisher
        assert r.widget._sample_lock is not other.widget._sample_lock
        local = r.manager.ReadConditionObservation(2, 2, "Character 1")
        peer = r.manager.ReadConditionObservation(1, 1, "Character 0")
        assert local.conditions == frozenset() and peer.conditions == frozenset({"Blind"})
        assert other.manager.ReadConditionObservation(2, 2, "Character 1") == local
        other.widget.on_disable()
        assert r.manager.ReadConditionObservation(1, 1, "Character 0") is None
        assert r.manager.ReadConditionObservation(2, 2, "Character 1") == local
        assert r.logs == []
    finally:
        other.mapping.close()


@pytest.mark.parametrize("outpost", [False, True])
def test_automatic_publisher_waits_for_valid_explorable(publisher_widget: Any, outpost: bool) -> None:
    r = publisher_widget
    r.ready, r.outpost = False, outpost
    for _ in range(10):
        r.widget.draw()
    assert not r.reads and r.mapping._shm is None and r.widget._publisher is None
    r.ready, r.outpost = True, False
    r.widget.draw()
    assert r.reads == [(10000, 2)] and r.mapping.read(r.owner, r.local.instance) is not None
    assert not r.logs and not r.visible
