"""Package 2 receipts and FSM lifetimes over real source, with inert host boundaries.

No injected package is initialized. Pinned consumer blobs and candidate definitions
are compiled verbatim; the wire layout and account methods come from Package 1.
"""

# pyright: strict

from __future__ import annotations

import ast
import builtins
import ctypes
import dis
import hashlib
import os
import subprocess
import sys
import time
import traceback
import weakref
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
from types import CodeType
from types import ModuleType
from types import SimpleNamespace
from typing import Any
from typing import Protocol
from typing import cast

import pytest
from test_account_publication import ROOT
from test_account_publication import account_world as account_world
from test_message_permission_identity import world as message_world_fixture
from test_shared_core_package1_consumers import MR
from test_shared_core_package1_consumers import Source

ITEM_VALUES = Source("Sources/icefox/MerchantRules/item_values.py", "e0364a74c072e769ce43a688402721a08eee30cc")
UPKEEPER = Source("Widgets/System/Environment Upkeeper.py", "2112807958413acdf225e935dc3edcf04a8d3f30")
FSM_PATH = ROOT / "Py4GWCoreLib/py4gwcorelib_src/FSM.py"
MESSAGING_PATH = ROOT / "Widgets/System/Messaging.py"
world = message_world_fixture


@lru_cache(maxsize=12)
def read_source(source: Source) -> str:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "-C",
            str(source.repository.resolve()),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "diff.external=",
            "cat-file",
            "blob",
            source.blob,
        ],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, f"Required pinned source unavailable: {source}: {result.stderr!r}"
    content = result.stdout
    actual = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
    assert actual == source.blob, f"Pinned source mismatch: {source}: observed {actual}"
    return content.decode("utf-8-sig")


def _global_loads(code: CodeType) -> set[str]:
    names = {
        cast(str, instruction.argval)
        for instruction in dis.get_instructions(code)
        if instruction.opname == "LOAD_GLOBAL"
    }
    for value in code.co_consts:
        if isinstance(value, CodeType):
            names.update(_global_loads(value))
    return names


@lru_cache(maxsize=12)
def _source_tree(text: str, label: str) -> ast.Module:
    return ast.parse(text, filename=label)


def selected(
    text: str,
    label: str,
    names: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    namespace: dict[str, Any],
    *,
    package: str = "",
) -> Any:
    """Select complete owning definitions without imports or module startup."""
    tree = _source_tree(text, label)
    body: list[ast.stmt] = [ast.ImportFrom("__future__", [ast.alias("annotations")], 0)]
    methods: dict[str, list[ast.stmt]] = {}
    for name in names:
        if "." in name:
            owner, member = name.split(".", 1)
            owners = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner]
            assert len(owners) == 1, f"{label}: missing owner {owner}"
            matches = [node for node in owners[0].body if isinstance(node, ast.FunctionDef) and node.name == member]
            assert len(matches) == 1, f"{label}: missing method {name}"
            methods.setdefault(owner, []).append(matches[0])
            continue
        matches: list[ast.stmt] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
                matches.append(node)
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name for target in node.targets
            ):
                matches.append(node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
                matches.append(node)
        assert len(matches) == 1, f"{label}: expected one definition of {name}, found {len(matches)}"
        body.append(matches[0])
    for owner, members in methods.items():
        body.append(ast.ClassDef(owner, [], [], members, []))
    module = ModuleType(f"_package2_selected_{len(sys.modules)}")
    module.__package__ = package
    module.__dict__.update(
        Any=Any,
        Callable=Callable,
        Generator=Generator,
        Iterator=Iterator,
        Protocol=Protocol,
        ReferenceType=weakref.ReferenceType,
        cast=cast,
        dataclass=dataclass,
        field=field,
        ctypes=ctypes,
        deepcopy=deepcopy,
        traceback=traceback,
        weakref=weakref,
        ref=weakref.ref,
        time=time,
    )
    module.__dict__.update(namespace)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    code = compile(ast.fix_missing_locations(ast.Module(body, [])), label, "exec")
    exec(code, module.__dict__)
    missing = _global_loads(code) - module.__dict__.keys() - vars(builtins).keys()
    assert not missing, f"{label}: incomplete source closure: {sorted(missing)}"
    return module


class Timer:
    """An observable inert clock; callbacks remain owned by production FSM code."""

    def __init__(self, *_args: Any) -> None:
        self.resets = 0
        self.stops = 0
        self.elapsed = True

    def Reset(self) -> None:
        self.resets += 1

    def Start(self) -> None:
        self.resets += 1

    def Stop(self) -> None:
        self.stops += 1

    def HasElapsed(self, _milliseconds: int) -> bool:
        return self.elapsed

    def IsExpired(self) -> bool:
        return False


class ActionBoundary:
    """Store callbacks without running them during submission."""

    def __init__(self) -> None:
        self.pending: list[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []

    def AddAction(self, _queue: str, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.pending.append((callback, args, kwargs))

    def AddActionWithDelay(
        self, queue: str, _delay: int, callback: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> None:
        self.pending.append((callback, args, kwargs))

    def drain(self) -> None:
        pending = self.pending[:]
        self.pending.clear()
        for callback, args, kwargs in pending:
            callback(*args, **kwargs)


def wait_once(milliseconds: int) -> Generator[int, None, None]:
    yield milliseconds


def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("An unselected runtime boundary was invoked")


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


def real_widget(env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    source = read_source(MR)
    safe = selected(read_source(ITEM_VALUES), ITEM_VALUES.path, ("safe_int",), monkeypatch, {})
    methods = (
        "_get_account_key",
        "_merchant_rules_is_generation_current",
        "_refresh_merchant_rules_lifecycle_state",
        "_merchant_rules_map_party_ready",
        "_merchant_rules_lifecycle_block_reason",
        "_merchant_rules_lifecycle_is_current",
        "_merchant_rules_owned_work_lifecycle_state",
        "_yield_merchant_rules_lifecycle_wait",
        "_wait_for_merchant_rules_lifecycle",
        "_merchant_rules_operation_generation",
        "_merchant_rules_operation_lifecycle_generation",
        "_capture_merchant_rules_work_lifecycle_baseline",
        "_capture_merchant_rules_remote_dispatch_lifecycle",
        "_release_merchant_rules_owned_work",
        "_release_merchant_rules_owned_action",
        "_track_merchant_rules_owned_action",
        "_begin_merchant_rules_action_capture",
        "_end_merchant_rules_action_capture",
        "_close_merchant_rules_generator",
        "_advance_merchant_rules_owned_generator",
        "_track_merchant_rules_owned_work",
        "_release_merchant_rules_remote_dispatch",
        "_get_staged_multibox_reload_request_key",
        "_read_validated_multibox_profile_payload",
        "_capture_multibox_profile_reload_payload",
        "_clear_pending_multibox_profile_reload",
        "_stage_multibox_profile_reload",
        "_release_staged_multibox_profile_reload",
        "track_merchant_rules_remote_dispatch",
        "_extract_multibox_message_extra_data",
        "_get_multibox_message_opcode",
        "_is_multibox_result_opcode",
        "_multibox_message_requires_merchant_lock",
        "_wait_for_remote_execute_start",
        "_snapshot_multibox_hero_ai_options",
        "_disable_multibox_hero_ai_options",
        "_enable_multibox_hero_ai_options",
        "_restore_multibox_hero_ai_options",
        "handle_shared_multibox_message",
        "_handle_shared_multibox_message",
    )
    constants = (
        "MERCHANT_RULES_OWNED_ACTION_QUEUES",
        "MERCHANT_RULES_LIFECYCLE_WAIT_TIMEOUT_MS",
        "MERCHANT_RULES_LIFECYCLE_WAIT_STEP_MS",
        "MERCHANT_RULES_MAP_READY_UPTIME_MS",
        "MERCHANT_RULES_PLAYER_READY_UPTIME_MS",
        "MULTIBOX_REMOTE_IDLE_WAIT_TIMEOUT_MS",
        "MULTIBOX_REMOTE_STATUS_UPDATE_INTERVAL_MS",
        "MERCHANT_RULES_OPCODE_RELOAD_PROFILE",
        "MERCHANT_RULES_OPCODE_PREVIEW",
        "MERCHANT_RULES_OPCODE_EXECUTE",
        "MERCHANT_RULES_OPCODE_STATUS_RESULT",
        "MERCHANT_RULES_OPCODE_PREVIEW_RESULT",
        "MERCHANT_RULES_OPCODE_EXECUTE_RESULT",
        "MERCHANT_RULES_OPCODE_ERROR_RESULT",
        "PROFILE_VERSION",
    )
    module = selected(
        source,
        f"{MR.path}@{MR.blob}",
        constants
        + (
            "RequestScopedMerchantStockTarget",
            "MerchantRulesExecutionContext",
            "_parse_request_scoped_merchant_stock",
            "_MerchantRulesOwnedGenerator",
            "_MerchantRulesOwnedQueueCallback",
        )
        + tuple(f"MerchantRulesWidget.{name}" for name in methods),
        monkeypatch,
        dict(
            _safe_int=safe.safe_int,
            Map=env.map,
            Player=env.player,
            Routines=env.routines,
            GLOBAL_CACHE=env.cache,
            ActionQueueManager=lambda: env.actions,
            Console=env.console,
            ConsoleLog=env.log,
            MODULE_NAME="Merchant Rules",
            PlanResult=SimpleNamespace,
        ),
    )
    widget = module.MerchantRulesWidget()
    widget.initialized = True
    widget.account_key = env.world.receiver
    widget.merchant_rules_profile_generation = 1
    widget.merchant_rules_lifecycle_generation = 1
    widget._merchant_rules_active_generation = None
    widget._merchant_rules_active_lifecycle_generation = None
    widget._merchant_rules_planned_lifecycle_generation = None
    widget._merchant_rules_planned_travel_active = False
    widget._merchant_rules_lifecycle_map_ready_snapshot = True
    widget._merchant_rules_lifecycle_map_snapshot = 1
    widget._merchant_rules_lifecycle_uptime_snapshot_ms = 100000
    widget.map_ready_snapshot = True
    widget.map_snapshot = 1
    widget.map_instance_uptime_snapshot_ms = 100000
    widget._character_profile_resolution_started = False
    widget.merchant_rules_remote_dispatch_count = 0
    widget.merchant_rules_owned_work_count = 0
    widget.merchant_rules_owned_action_count = 0
    widget.merchant_session_open = False
    widget.execution_running = False
    widget.manual_vendor_running = False
    widget.destroy_include_protected_items = False
    widget.destroy_instant_enabled = False
    widget.last_error = ""
    widget.status_message = ""
    widget.pending_multibox_profile_reload = None
    widget._pending_multibox_profile_reload_payload = None
    widget._merchant_rules_staged_multibox_reload_requests = set()
    # These are the inventory, profile and UI boundaries outside this package.
    for name in (
        "_debug_log",
        "_ensure_initialized",
        "_clear_inventory_shortcut_material_storage_count_cache",
        "_clear_inventory_shortcut_xunlai_display_cache",
        "_clear_preview_projection_state",
        "_clear_preview_inventory_diff",
        "_mark_character_profile_unresolved",
        "_clear_inventory_monitor_signatures",
        "_invalidate_supported_context_cache",
        "_reset_service_resolution_lifecycle",
    ):
        setattr(widget, name, _noop)
    widget._character_profile_gate_block_reason = lambda: ""
    widget._get_remote_execute_wait_reason = lambda: ""
    widget._scan_preview = lambda: env.events.append("scan")
    widget.build_remote_preview_result = lambda: {"opcode": 101, "success": True}
    widget.build_remote_execute_result = lambda: {"opcode": 102, "success": True}

    def unmet_targets(_context: Any) -> list[Any]:
        return []

    def execute_inventory(**_kwargs: Any) -> Generator[int, None, None]:
        return wait_once(200)

    def record_result(*args: Any, **kwargs: Any) -> None:
        env.results.append((args, kwargs))

    def record_reload(**kwargs: Any) -> None:
        env.reloads.append(kwargs)

    def get_json(*_args: Any) -> Any:
        return env.payload

    widget._get_unmet_request_stock_targets = unmet_targets
    widget._execute_now = execute_inventory
    widget._send_multibox_result_message = record_result
    widget._send_multibox_status_message = record_result
    widget._send_multibox_status_from_message = record_result
    widget._request_multibox_profile_reload = record_reload
    widget._normalize_profile_payload = deepcopy
    widget._live_config_doc = lambda: SimpleNamespace(reload=lambda: True, get_json=get_json)
    widget._module = module
    return widget


@pytest.fixture
def env(world: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    world.clock.frame = 10000
    world.clock.uncached = 10016
    for index in (0, 1):
        world.table.AccountData[index].LastUpdated = 10016
        world.table.AccountData[index].IsolationGroupID = 1
        world.table.AccountData[index].AgentPartyData.PartyID = 10 + index
        world.table.Keys[index].HWND = 100 + index
    state = SimpleNamespace(
        world=world,
        events=[],
        results=[],
        reloads=[],
        logs=[],
        payload={"version": 1, "label": "captured"},
        ready=True,
        party_ready=True,
        map_id=1,
        uptime=100000,
        actions=ActionBoundary(),
    )

    def record_log(*args: Any, **kwargs: Any) -> None:
        state.logs.append((args, kwargs))

    def record_received(_message: Any) -> None:
        state.events.append("received")

    state.log = record_log
    state.console = SimpleNamespace(MessageType=SimpleNamespace(Info=0, Warning=1, Error=2, Success=3, Debug=4))
    # Messaging consumes the facade getter; all wire operations remain the real
    # AllAccounts methods exercised by Package 1.
    world.table.GetAllAccounts = lambda: world.table
    state.cache = SimpleNamespace(ShMem=world.table, Coroutines=[], _update_cache=lambda: None)
    state.player = SimpleNamespace(
        GetAccountEmail=lambda: world.receiver,
        GetName=lambda: "Receiver",
        IsPlayerLoaded=lambda: state.ready,
        GetAgentID=lambda: 123,
        GetInstanceUptime=lambda: state.uptime,
    )
    state.map = SimpleNamespace(
        IsMapReady=lambda: state.ready,
        GetMapID=lambda: state.map_id,
        GetInstanceUptime=lambda: state.uptime,
        IsOutpost=lambda: True,
        IsGuildHall=lambda: False,
        IsMapLoading=lambda: False,
        IsInCinematic=lambda: False,
    )
    state.routines = SimpleNamespace(
        Yield=SimpleNamespace(wait=wait_once),
        Checks=SimpleNamespace(Map=SimpleNamespace(MapValid=lambda: state.party_ready)),
    )
    monkeypatch.setattr(sys.modules["Py4GWCoreLib"], "GLOBAL_CACHE", state.cache, raising=False)
    global_module = ModuleType("Py4GWCoreLib.GlobalCache")
    global_module.__dict__["GLOBAL_CACHE"] = state.cache
    monkeypatch.setitem(sys.modules, global_module.__name__, global_module)
    loot_module = ModuleType("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters")
    loot_module.__dict__["LootFilters"] = lambda: SimpleNamespace(on_map_change=lambda: None)
    monkeypatch.setitem(sys.modules, loot_module.__name__, loot_module)
    state.FSM = selected(
        FSM_PATH.read_text(encoding="utf-8-sig"),
        str(FSM_PATH),
        ("_DispatchReceipt", "_FSMDispatchOwner", "_StateIdentity", "_SelfManagedIdentity", "FSM"),
        monkeypatch,
        dict(Timer=Timer, ThrottledTimer=Timer, Console=state.console, ConsoleLog=state.log, PySystem=world.system),
        package="Py4GWCoreLib.py4gwcorelib_src",
    ).FSM
    state.widget = real_widget(state, monkeypatch)
    state.original_widget = state.widget
    source = MESSAGING_PATH.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    names = tuple(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and (
            node.name.startswith("_merchant_rules_")
            or node.name.startswith("_MerchantRules")
            or node.name
            in (
                "MerchantRules",
                "_queue_merchant_rules_message",
                "_reconcile_merchant_rules_dispatches",
                "ProcessMessages",
                "main",
                "on_disable",
            )
        )
    )
    assert "_MerchantRulesDispatchReceipt" in names, "Package 2 candidate receipt missing"
    namespace: dict[str, Any] = dict(
        GLOBAL_CACHE=state.cache,
        SharedMessageStruct=world.wire.SharedMessageStruct,
        SharedCommandType=world.commands,
        Player=state.player,
        Console=state.console,
        ConsoleLog=state.log,
        PySystem=world.system,
        MODULE_NAME="Messaging",
        _merchant_busy=False,
        _merchant_rules_dispatches={},
        _get_merchant_rules_widget=lambda: state.widget,
        _record_received_message=record_received,
        HealStaleHeroAISnapshot=_noop,
        _process_pending_widget_enables=lambda: None,
    )
    process = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "ProcessMessages")
    for node in ast.walk(process):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in names:
            if node.func.id not in namespace and node.func.id not in vars(builtins):
                namespace[node.func.id] = _forbidden
    state.messaging = selected(source, str(MESSAGING_PATH), names, monkeypatch, namespace)
    configuration = SimpleNamespace(
        action_queue_manager=SimpleNamespace(ResetNonTransitionQueues=_noop, ProcessQueue=_noop),
        overlay=SimpleNamespace(UpkeepTextures=lambda: None),
    )
    for name in ("action", "transition", "loot", "merchant", "salvage", "identify", "fast"):
        setattr(configuration, f"throttle_{name}_queue", Timer())
    state.scheduler = selected(
        read_source(UPKEEPER),
        f"{UPKEEPER.path}@{UPKEEPER.blob}",
        ("main",),
        monkeypatch,
        dict(
            GLOBAL_CACHE=state.cache,
            HOTKEY_MANAGER=SimpleNamespace(update=lambda: None),
            Routines=state.routines,
            Map=state.map,
            widget_config=configuration,
        ),
    ).main
    return state


def make_message(env: Any, *, index: int = 0, opcode: int = 2, request: str = "request") -> Any:
    row = env.world.table.Inbox[index]
    ctypes.memset(ctypes.addressof(row), 0, ctypes.sizeof(row))
    row.SenderEmail = env.world.sender
    row.ReceiverEmail = env.world.receiver
    row.Command = env.world.commands.MerchantRules
    row.Params[0] = opcode
    row.ExtraData[0].value = request
    row.Active = True
    row.Running = False
    row.Timestamp = 10000 + index
    return row


def queue_receipt(env: Any, **kwargs: Any) -> Any:
    row = make_message(env, **kwargs)
    env.messaging._queue_merchant_rules_message(kwargs.get("index", 0), row)
    assert len(env.cache.Coroutines) > 0, "accepted receipt was not enqueued"
    return env.cache.Coroutines[-1]


def make_fsm(env: Any, *, final: bool = False) -> Any:
    owner = env.FSM("package2")
    owner.AddState("hold", exit_condition=lambda: final)
    owner.start()
    return owner


def drain(env: Any, ticks: int = 10) -> None:
    for _ in range(ticks):
        if not env.cache.Coroutines:
            return
        env.scheduler()
    raise AssertionError(f"scheduler retained {env.cache.Coroutines!r}; events={env.events!r}")


def assert_terminal(env: Any, receipt: Any) -> None:
    assert receipt.terminal
    before = (bytes(env.world.table), tuple(env.events), env.widget.merchant_rules_remote_dispatch_count)
    if receipt in env.cache.Coroutines:
        with pytest.raises(StopIteration):
            next(receipt)
    else:
        # The actual Upkeeper removes without checking membership. A stale
        # copied-list caller must yield harmlessly after transfer or clear.
        assert next(receipt) is None
    assert before == (bytes(env.world.table), tuple(env.events), env.widget.merchant_rules_remote_dispatch_count)


def test_d1_duplicate_pending_and_waiting_have_one_reservation(env: Any) -> None:
    env.party_ready = False
    row = make_message(env)
    pending = bytes(row)
    for _ in range(3):
        env.messaging.ProcessMessages()
    assert len(env.cache.Coroutines) == 1
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    assert bytes(row) == pending
    receipt = env.cache.Coroutines[0]
    env.scheduler()
    assert row.Running
    assert env.widget.merchant_rules_owned_work_count == 0
    env.messaging._queue_merchant_rules_message(0, row)
    assert env.cache.Coroutines == [receipt]
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    env.party_ready = True
    drain(env)
    assert not row.Active
    assert env.widget.merchant_rules_remote_dispatch_count == 0


def test_d1_reservation_precedes_reentrant_tracker_and_copies_pending_bytes(env: Any) -> None:
    row = make_message(env)
    original = env.widget.track_merchant_rules_remote_dispatch
    calls: list[Any] = []

    def tracking(message: Any, generator: Any) -> Any:
        calls.append(message)
        env.messaging._queue_merchant_rules_message(0, row)
        return original(message, generator)

    env.widget.track_merchant_rules_remote_dispatch = tracking
    pending = bytes(row)
    env.messaging._queue_merchant_rules_message(0, row)
    assert len(calls) == len(env.cache.Coroutines) == 1
    assert calls[0] is not row
    env.world.clock.frame += 1
    env.scheduler()
    assert bytes(calls[0]) == pending
    assert row.Timestamp != calls[0].Timestamp
    assert row.Running and not calls[0].Running


def test_d1_real_tracker_constructor_failure_releases_attempt(env: Any) -> None:
    row = make_message(env)
    pending = bytes(row)
    constructor = env.widget._module._MerchantRulesOwnedGenerator

    def fail_constructor(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("owned iterator allocation failed")

    env.widget._module._MerchantRulesOwnedGenerator = fail_constructor
    try:
        env.messaging._queue_merchant_rules_message(0, row)
    except ValueError:
        pass
    assert bytes(row) == pending
    assert env.widget.merchant_rules_remote_dispatch_count == 0
    assert not env.messaging._merchant_rules_dispatches
    env.widget._module._MerchantRulesOwnedGenerator = constructor
    env.messaging._queue_merchant_rules_message(0, row)
    drain(env)
    assert not row.Active


@pytest.mark.parametrize("failure", ["tracker", "append", "append_after"])
def test_d1_failed_construction_or_enqueue_preserves_pending_retry(env: Any, failure: str) -> None:
    row = make_message(env)
    pending = bytes(row)
    original = env.widget.track_merchant_rules_remote_dispatch
    if failure == "tracker":

        def fail_tracker(*_args: Any) -> Any:
            raise ValueError("tracker")

        env.widget.track_merchant_rules_remote_dispatch = fail_tracker
    else:

        class RejectAppend(list[Any]):
            def append(self, _value: Any) -> None:
                if failure == "append_after":
                    super().append(_value)
                raise ValueError("append")

        env.cache.Coroutines = RejectAppend()
    try:
        env.messaging._queue_merchant_rules_message(0, row)
    except ValueError:
        pass
    assert bytes(row) == pending
    assert env.widget.merchant_rules_remote_dispatch_count == 0
    assert not env.messaging._merchant_rules_dispatches
    env.widget.track_merchant_rules_remote_dispatch = original
    env.cache.Coroutines = []
    env.messaging._queue_merchant_rules_message(0, row)
    drain(env)
    assert not row.Active


@pytest.mark.parametrize("phase", ["unstarted", "waiting", "running", "complete"])
def test_d2_receipt_close_is_terminal_and_idempotent(env: Any, phase: str) -> None:
    env.party_ready = phase != "waiting"
    receipt = queue_receipt(env)
    if phase in ("waiting", "running", "complete"):
        env.scheduler()
    if phase == "complete":
        drain(env)
    receipt.close()
    receipt.close()
    assert_terminal(env, receipt)
    assert env.widget.merchant_rules_remote_dispatch_count == 0
    assert env.widget.merchant_rules_owned_work_count == 0
    assert not env.world.table.Inbox[0].Active


@pytest.mark.parametrize("phase", ["unstarted", "waiting", "running"])
@pytest.mark.parametrize("cancel", ["clear", "disable"])
def test_d3_empty_inbox_reconcile_and_disable_release_once(env: Any, phase: str, cancel: str) -> None:
    env.party_ready = phase != "waiting"
    receipt = queue_receipt(env)
    if phase != "unstarted":
        env.scheduler()
    if cancel == "clear":
        env.cache.Coroutines.clear()
        env.messaging.main()
    else:
        env.messaging.on_disable()
    env.messaging.main()
    receipt.close()
    assert env.widget.merchant_rules_remote_dispatch_count == 0
    assert env.widget.merchant_rules_owned_work_count == 0
    assert not env.world.table.Inbox[0].Active
    assert not env.messaging._merchant_rules_dispatches


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("field_name", ["params", "timestamp", "status", "receiver"])
def test_d4_exact_wire_fingerprint_preserves_observed_successor(env: Any, running: bool, field_name: str) -> None:
    receipt = queue_receipt(env)
    row = env.world.table.Inbox[0]
    if running:
        env.scheduler()
    if field_name == "params":
        row.Params[1] = -0.0
    elif field_name == "timestamp":
        row.Timestamp += 1
    elif field_name == "status":
        row.Active = not row.Active
    else:
        row.ReceiverEmail = "replacement@example.invalid"
    successor = bytes(row)
    receipt.close()
    assert bytes(row) == successor, f"retirement overwrote {field_name} successor; running={running}"
    assert env.widget.merchant_rules_remote_dispatch_count == 0


def test_d4_nan_bytes_and_registry_successor(env: Any) -> None:
    row = make_message(env)
    # Preserve an exact NaN payload, not floating-point equality or canonicalization.
    ctypes.c_uint32.from_address(ctypes.addressof(row.Params) + ctypes.sizeof(ctypes.c_float)).value = 0x7FC00042
    env.messaging._queue_merchant_rules_message(0, row)
    old = env.cache.Coroutines[-1]
    env.messaging._queue_merchant_rules_message(0, row)
    assert len(env.cache.Coroutines) == 1
    make_message(env, request="successor")
    env.messaging._queue_merchant_rules_message(0, row)
    successor = env.cache.Coroutines[-1]
    assert successor is not old
    before = bytes(row)
    old.close()
    assert bytes(row) == before
    assert successor in env.messaging._merchant_rules_dispatches.values()
    successor.close()


def test_d4_identical_wire_aba_remains_indistinguishable(env: Any) -> None:
    receipt = queue_receipt(env)
    row = env.world.table.Inbox[0]
    pending = bytes(row)
    row.ExtraData[0].value = "unobserved-successor"
    ctypes.memmove(ctypes.addressof(row), pending, len(pending))
    receipt.close()
    # Without a wire generation field, equality after an unobserved ABA is
    # indistinguishable from the original row. This is a residual, not CAS.
    assert not row.Active


def test_d4_nan_payload_survives_exact_pending_to_running_fingerprint(env: Any) -> None:
    row = make_message(env)
    bits = ctypes.c_uint32.from_address(ctypes.addressof(row.Params) + ctypes.sizeof(ctypes.c_float))
    bits.value = 0x7FC00042
    env.messaging._queue_merchant_rules_message(0, row)
    receipt = env.cache.Coroutines[-1]
    env.scheduler()
    assert row.Running and not receipt.terminal
    assert bits.value == 0x7FC00042
    drain(env)
    assert receipt.terminal and not row.Active


@pytest.mark.parametrize("terminal", ["terminate", "natural"])
@pytest.mark.parametrize("pump_first", [False, True])
def test_d5_terminal_epoch_cannot_revive_retained_receipt(env: Any, terminal: str, pump_first: bool) -> None:
    owner = make_fsm(env)

    def transfer_and_restart() -> Generator[None, None, None]:
        assert owner.AdoptGlobalCoroutine(old)
        if terminal == "terminate":
            owner.terminate()
        else:
            owner.current_state.exit_condition = lambda: True
            owner.update()
            assert owner.finished
        assert old in owner.managed_coroutines, "exercise retained-list revocation before the pump"
        owner.ResetAndStartAtStep("hold")
        owner.current_state.exit_condition = lambda: False
        yield

    env.cache.Coroutines.append(transfer_and_restart())
    old = queue_receipt(env)
    if pump_first:
        env.messaging.main()
    env.scheduler()
    owner.update()
    if not pump_first:
        env.messaging.main()
    assert "scan" not in env.events
    new = queue_receipt(env, index=1, request="new-run")
    assert owner.AdoptGlobalCoroutine(new)
    owner.update()
    assert env.world.table.Inbox[1].Running
    owner.update()
    assert not env.world.table.Inbox[1].Active


@pytest.mark.parametrize("phase", ["execute", "can_exit", "exit", "transition", "enter"])
@pytest.mark.parametrize("raises", [False, True])
def test_d6_callback_restart_preserves_successor_state(env: Any, phase: str, raises: bool) -> None:
    owner = env.FSM("callbacks")
    owner.AddState("old")
    owner.AddState("next")
    owner.AddState("successor", exit_condition=lambda: False)
    owner.start()
    successor = owner.states[2]
    observed: list[tuple[int, int, bool]] = []

    def restart(*_args: Any) -> bool:
        owner.ResetAndStartAtStep("successor")
        owner.pause()
        observed.append((successor.transition_timer.resets, successor.transition_timer.stops, successor.executed))
        if raises:
            raise ValueError("callback restarted then raised")
        return True

    if phase == "execute":
        owner.states[0].execute_fn = restart
    elif phase == "can_exit":
        owner.states[0].exit_condition = restart
    elif phase == "exit":
        owner.states[0].on_exit = restart
    elif phase == "transition":
        owner.set_transition_callback(restart)
    else:
        owner.states[1].on_enter = restart
    try:
        owner.update()
    except ValueError:
        assert raises
    assert owner.current_state is successor
    assert owner.paused
    assert observed == [(successor.transition_timer.resets, successor.transition_timer.stops, successor.executed)]
    assert not successor.executed


def test_d6_same_state_reactivation_and_event_reentry(env: Any) -> None:
    owner = make_fsm(env)
    state = owner.current_state
    state.execute_fn = lambda: owner.ResetAndStartAtStep("hold")
    before = state.transition_timer.resets
    owner.update()
    assert owner.current_state is state
    assert not state.executed
    assert state.transition_timer.resets == before
    owner.AddState("event-target")
    owner.AddState("new", exit_condition=lambda: False)
    state.add_event_transition("go", "event-target")
    state.on_exit = lambda: owner.ResetAndStartAtStep("new")
    owner.trigger_event("go")
    assert owner.current_state.name == "new"
    assert not owner.current_state.executed


def test_d7_reset_loop_child_interrupt_and_timeout_reentry(env: Any) -> None:
    owner = env.FSM("reset-loop")
    owner.AddState("first")
    owner.AddState("untouched")
    owner.AddState("new", exit_condition=lambda: False)
    owner.start()
    first_reset = owner.states[0].reset

    def reentrant_reset() -> None:
        first_reset()
        owner.ResetAndStartAtStep("new")

    owner.states[0].reset = reentrant_reset
    before = owner.states[1].transition_timer.stops
    owner.reset()
    assert owner.current_state.name == "new"
    assert owner.states[1].transition_timer.stops == before

    parent = env.FSM("parent")
    child = make_fsm(env)
    parent.AddSubroutine("child", condition_fn=lambda: True, sub_fsm=child)
    parent.AddState("new", exit_condition=lambda: False)
    parent.start()
    child.reset = lambda: parent.ResetAndStartAtStep("new")
    parent.update()
    assert parent.current_state.name == "new"
    assert not parent.states[0].sub_fsm_active

    interrupt = env.FSM("interrupt")
    interrupt.AddState("old", on_exit=lambda: interrupt.ResetAndStartAtStep("new"))
    interrupt.AddState("new", exit_condition=lambda: False)
    interrupt.start()
    fired: list[str] = []
    interrupt.interrupt(lambda: fired.append("stale"))
    interrupt.update()
    assert not fired
    assert interrupt.current_state.name == "new"

    timeout = env.FSM("timeout")
    timeout.AddWaitState("wait", condition_fn=lambda: False, on_timeout=lambda: timeout.ResetAndStartAtStep("new"))
    timeout.AddState("new", exit_condition=lambda: False)
    timeout.start()
    timeout.update()
    assert timeout.current_state.name == "new"
    assert not timeout.current_state.executed


def test_d7_recursive_update_run_until_and_completion_restart(env: Any) -> None:
    owner = env.FSM("recursive")
    calls: list[str] = []

    def execute() -> None:
        calls.append("execute")
        owner.update()
        owner.run_until(lambda: False)

    owner.AddState("only", execute_fn=execute)
    owner.set_completion_callback(lambda: (calls.append("complete"), owner.ResetAndStartAtStep("only")))
    owner.start()
    owner.update()
    assert calls == ["execute", "complete"]
    assert owner.current_state.name == "only"
    assert not owner.finished
    assert not owner.current_state.executed


@pytest.mark.parametrize("superseded", [False, True])
def test_d8_reset_start_trailing_resume_only_current_operation(env: Any, superseded: bool) -> None:
    owner = env.FSM("resume")

    def entered() -> None:
        if superseded:
            owner.ResetAndStartAtStep("new")
        owner.pause()

    owner.AddState("target", on_enter=entered)
    owner.AddState("new", exit_condition=lambda: False)
    owner.ResetAndStartAtStep("target")
    assert owner.paused is superseded
    assert owner.current_state.name == ("new" if superseded else "target")


@pytest.mark.parametrize("mode", ["self", "named"])
@pytest.mark.parametrize("result", ["fresh", "successor", "none", "raises"])
def test_d9_factory_reentry_never_overwrites_successor(env: Any, mode: str, result: str) -> None:
    owner = env.FSM("factory")
    successor = env.messaging.MerchantRules(1, make_message(env, index=1, request="B"))
    old = env.messaging.MerchantRules(0, make_message(env, index=0, request="A"))
    installed: list[tuple[int, bool]] = []

    def factory() -> Any:
        if mode == "self":
            owner.ResetAndStartAtStep("work")
            state = owner.current_state
            state.coroutine_fn = lambda: successor
            state.execute()
            installed.append((state.transition_timer.resets, state.executed))
        else:
            owner.RemoveManagedCoroutine("work")
            assert owner.AddManagedCoroutine("work", lambda: successor)
        if result == "raises":
            raise ValueError("old factory failed after successor installation")
        return {"fresh": old, "successor": successor, "none": None}[result]

    if mode == "self":
        owner.AddSelfManagedYieldStep("work", factory)
        owner.start()
        owner.update()
        state = owner.current_state
        assert state.coroutine_instance is successor
        assert installed == [(state.transition_timer.resets, state.executed)]
        assert not state.can_exit()
    else:
        owner.AddState("hold", exit_condition=lambda: False)
        owner.start()
        assert not owner.AddManagedCoroutine("work", factory)
        assert owner._named_managed["work"] is successor
        assert owner.HasManagedCoroutine("work")
    assert successor in owner.managed_coroutines
    assert old not in owner.managed_coroutines
    owner.update()
    assert env.world.table.Inbox[1].Running
    old.close()


@pytest.mark.parametrize("disposition", ["fresh", "independent", "expired"])
def test_d10_factory_cleanup_is_ownership_selective(env: Any, disposition: str) -> None:
    owner = make_fsm(env)
    row = make_message(env)
    before = bytes(row)
    receipt = env.messaging.MerchantRules(0, row)
    other = make_fsm(env)
    if disposition in ("independent", "expired"):
        assert other.AddManagedCoroutine("owned", receipt)
        if disposition == "expired":
            other.terminate()

    def rejected_factory() -> Any:
        owner.terminate()
        return receipt

    assert not owner.AddManagedCoroutine("rejected", rejected_factory)
    if disposition == "fresh":
        assert bytes(row) == before
        assert env.widget.merchant_rules_remote_dispatch_count == 0
    elif disposition == "independent":
        assert other.HasManagedCoroutine("owned")
        other.update()
        assert row.Running
    else:
        assert not row.Active
        assert_terminal(env, receipt)


@pytest.mark.parametrize("return_successor", [False, True])
def test_d10_remove_invalidates_unfinished_name_without_mapping(env: Any, return_successor: bool) -> None:
    owner = make_fsm(env)
    old = env.messaging.MerchantRules(0, make_message(env))
    successor = env.messaging.MerchantRules(1, make_message(env, index=1, request="successor"))
    independent = wait_once(1)
    assert owner.AddManagedCoroutine("independent", independent)

    def factory() -> Any:
        assert "work" not in owner._named_managed
        owner.RemoveManagedCoroutine("work")
        assert owner.AddManagedCoroutine("work", successor)
        return successor if return_successor else old

    assert not owner.AddManagedCoroutine("work", factory)
    assert owner._named_managed["work"] is successor
    assert owner._named_managed["independent"] is independent
    assert successor in owner.managed_coroutines
    assert old not in owner.managed_coroutines
    owner.update()
    assert env.world.table.Inbox[1].Running
    old.close()


def test_d10_rejected_cleanup_reentry_preserves_new_name_mapping(env: Any) -> None:
    owner = make_fsm(env)
    successor = env.messaging.MerchantRules(1, make_message(env, index=1, request="B"))
    release = env.widget._release_merchant_rules_remote_dispatch
    releases: list[str] = []

    def reentrant_release() -> None:
        release()
        releases.append("A")
        assert owner.AddManagedCoroutine("work", successor)
        raise ValueError("cleanup failed after installing successor")

    env.widget._release_merchant_rules_remote_dispatch = reentrant_release
    old = env.messaging.MerchantRules(0, make_message(env, request="A"))
    pending = bytes(env.world.table.Inbox[0])

    def stale_factory() -> Any:
        owner.RemoveManagedCoroutine("work")
        return old

    assert not owner.AddManagedCoroutine("work", stale_factory)
    assert releases == ["A"]
    assert owner._named_managed["work"] is successor
    assert successor in owner.managed_coroutines
    assert bytes(env.world.table.Inbox[0]) == pending
    owner.update()
    assert env.world.table.Inbox[1].Running


@pytest.mark.parametrize("independent", [False, True])
@pytest.mark.parametrize("insert_before_failure", [False, True])
def test_d10_self_managed_append_failure_cleans_only_fresh_attempt(
    env: Any, independent: bool, insert_before_failure: bool
) -> None:
    if independent:
        receipt = queue_receipt(env)
    else:
        receipt = env.messaging.MerchantRules(0, make_message(env))
    pending = bytes(env.world.table.Inbox[0])

    class RejectAppend(list[Any]):
        def append(self, value: Any) -> None:
            if insert_before_failure:
                super().append(value)
            raise ValueError("managed append failed")

    owner = env.FSM("self-append-failure")
    owner.AddSelfManagedYieldStep("work", lambda: receipt)
    owner.start()
    owner.managed_coroutines = RejectAppend()
    owner.current_state.execute()
    assert owner.current_state.coroutine_instance is None
    assert not owner.managed_coroutines
    assert bytes(env.world.table.Inbox[0]) == pending
    if independent:
        assert receipt in env.cache.Coroutines
        assert not receipt.terminal
        assert env.widget.merchant_rules_remote_dispatch_count == 1
        drain(env)
    else:
        assert receipt.terminal
        assert env.widget.merchant_rules_remote_dispatch_count == 0


@pytest.mark.parametrize("copy_mode", [False, True])
def test_d11_transfer_and_multiple_owner_revocation(env: Any, copy_mode: bool) -> None:
    receipt = queue_receipt(env)
    first = make_fsm(env)
    second = make_fsm(env)
    assert first.AdoptGlobalCoroutine(receipt, remove_from_global=not copy_mode)
    assert (receipt in env.cache.Coroutines) is copy_mode
    assert second.AddManagedCoroutine("shared", receipt)
    first.terminate()
    first.ResetAndStartAtStep("hold")
    first.update()
    assert not env.world.table.Inbox[0].Running, "revoked first owner advanced another owner's receipt"
    second.update()
    assert env.world.table.Inbox[0].Running
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    second.terminate()
    if copy_mode:
        env.scheduler()
        assert not env.world.table.Inbox[0].Active
    else:
        env.messaging.main()
        assert not env.world.table.Inbox[0].Active
    assert env.widget.merchant_rules_remote_dispatch_count == 0


def test_d11_transfer_failure_preserves_global_owner(env: Any) -> None:
    receipt = queue_receipt(env)
    owner = make_fsm(env)

    class RejectAppend(list[Any]):
        def append(self, _value: Any) -> None:
            raise ValueError("attachment list refused")

    owner.managed_coroutines = RejectAppend()
    try:
        assert not owner.AdoptGlobalCoroutine(receipt)
    except ValueError:
        pass
    assert receipt in env.cache.Coroutines
    assert not owner.managed_coroutines
    drain(env)
    assert not env.world.table.Inbox[0].Active


@pytest.mark.parametrize("independent_owner", [False, True])
def test_d11_reattach_expired_receipt_cannot_resurrect_without_live_owner(env: Any, independent_owner: bool) -> None:
    receipt = queue_receipt(env)
    owner = make_fsm(env)
    assert owner.AdoptGlobalCoroutine(receipt, remove_from_global=not independent_owner)
    owner.terminate()
    owner.ResetAndStartAtStep("hold")
    attached = owner.AddManagedCoroutine("new-run", receipt)
    assert attached is independent_owner
    if independent_owner:
        owner.update()
        assert env.world.table.Inbox[0].Running
    else:
        assert not env.world.table.Inbox[0].Active
        owner.update()
        assert "scan" not in env.events


@pytest.mark.parametrize("terminal", ["terminate", "natural"])
def test_d11_stale_named_mapping_does_not_block_fresh_run(env: Any, terminal: str) -> None:
    owner = make_fsm(env)
    old = env.messaging.MerchantRules(0, make_message(env))
    assert owner.AddManagedCoroutine("same-name", old)
    if terminal == "natural":
        owner.current_state.exit_condition = lambda: True
        owner.update()
    else:
        owner.terminate()
    assert old in owner.managed_coroutines
    owner.ResetAndStartAtStep("hold")
    owner.current_state.exit_condition = lambda: False
    fresh = env.messaging.MerchantRules(1, make_message(env, index=1, request="fresh"))
    assert owner.AddManagedCoroutine("same-name", fresh)
    assert owner._named_managed["same-name"] is fresh
    owner.update()
    assert env.world.table.Inbox[1].Running
    assert "scan" not in env.events


def test_d11_revoke_during_advance_preserves_independent_owner(env: Any) -> None:
    receipt = queue_receipt(env)
    first = make_fsm(env)
    second = make_fsm(env)
    assert first.AdoptGlobalCoroutine(receipt)
    assert second.AddManagedCoroutine("shared", receipt)
    original = env.widget._scan_preview

    def scan() -> None:
        first.terminate()
        original()

    env.widget._scan_preview = scan
    first.update()
    first.update()
    assert first.finished
    second.update()
    assert not env.world.table.Inbox[0].Active
    assert env.events.count("scan") == 1


@pytest.mark.parametrize("other_owner", ["fsm", "global"])
def test_d11_running_mark_revocation_cannot_borrow_other_owner_authority(
    env: Any, monkeypatch: pytest.MonkeyPatch, other_owner: str
) -> None:
    receipt = queue_receipt(env)
    first = make_fsm(env)
    second = make_fsm(env)
    assert first.AdoptGlobalCoroutine(receipt, remove_from_global=other_owner != "global")
    if other_owner == "fsm":
        assert second.AddManagedCoroutine("independent", receipt)
    mark = env.world.table.MarkMessageAsRunning

    def revoke_after_mark(receiver: str, index: int) -> None:
        mark(receiver, index)
        first.terminate()

    monkeypatch.setattr(env.world.table, "MarkMessageAsRunning", revoke_after_mark)
    first.update()
    assert env.world.table.Inbox[0].Running
    assert env.widget.merchant_rules_owned_work_count == 0
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    assert "scan" not in env.events
    if other_owner == "fsm":
        second.update()
    else:
        env.scheduler()
    assert env.widget.merchant_rules_owned_work_count == 1


def test_d12_receipt_protocol_and_yield_routine_exclusion(env: Any) -> None:
    receipt = queue_receipt(env)
    owner = make_fsm(env)
    assert owner._as_generator(receipt) is receipt
    with pytest.raises((TypeError, ValueError)):
        receipt.send("unsupported")
    assert owner.AddManagedCoroutine("receipt", receipt)
    assert receipt.send(None) == 100
    receipt.close()
    fresh = env.messaging.MerchantRules(1, make_message(env, index=1))
    pending = bytes(env.world.table.Inbox[1])
    excluded = env.FSM.YieldRoutineState(0, "excluded", lambda: fresh)
    excluded.execute()
    assert fresh not in env.cache.Coroutines
    assert excluded.coroutine_instance is None
    assert bytes(env.world.table.Inbox[1]) == pending
    assert env.widget.merchant_rules_remote_dispatch_count == 0


def test_d12_ordinary_generators_preserve_wait_dedup_pause_and_order(env: Any) -> None:
    owner = env.FSM("ordinary")
    events: list[str] = []

    def background() -> Generator[None, None, None]:
        events.append("background-1")
        yield
        events.append("background-2")

    def foreground() -> Generator[None, None, None]:
        events.append("foreground-1")
        yield
        events.append("foreground-2")

    owner.AddSelfManagedYieldStep("foreground", foreground)
    owner.AddState("hold", execute_fn=lambda: events.append("hold"), exit_condition=lambda: False)
    owner.start()
    routine = background()
    assert owner.AddManagedCoroutine("background", routine)
    assert not owner.AddManagedCoroutine("background", lambda: _forbidden())
    owner.pause()
    owner.update()
    assert events == ["background-1"]
    owner.resume()
    owner.update()
    assert events == ["background-1", "background-2"]
    assert owner.current_state.name == "foreground"
    owner.update()
    assert events[-1] == "foreground-1"
    owner.update()
    assert events[-1] == "foreground-2"
    assert owner.current_state.name == "hold"
    owner.update()
    assert events[-1] == "hold"
    ordinary = foreground()
    state = env.FSM.YieldRoutineState(99, "global", lambda: ordinary)
    state.execute()
    assert ordinary in env.cache.Coroutines
    assert not state.can_exit()
    drain(env)
    assert state.can_exit()
    assert owner.RemoveManagedCoroutine("background") is False


def test_d12_ordinary_bound_state_executes_directly_without_current_activation(env: Any) -> None:
    owner = env.FSM("direct-state")
    called: list[str] = []
    owner.AddState("direct", execute_fn=lambda: called.append("direct"))
    owner.AddState("current", exit_condition=lambda: False)
    state = owner.states[0]
    state.execute()
    assert called == ["direct"]
    assert state.executed and state.transition_timer.resets == 1
    owner.start()
    owner.jump_to_state_by_name("current")
    state.reset()
    state.execute()
    assert called == ["direct", "direct"]
    assert state.executed and state.transition_timer.resets == 2
    assert owner.current_state.name == "current"


def test_d12_exit_callback_can_select_next_state(env: Any) -> None:
    owner = env.FSM("dynamic-next")
    owner.AddState("old")
    owner.AddState("default")
    owner.AddState("selected", exit_condition=lambda: False)
    owner.states[0].on_exit = lambda: owner.states[0].set_next_state(owner.states[2])
    owner.start()
    owner.update()
    assert owner.current_state is owner.states[2]
    assert not owner.finished


@pytest.mark.parametrize("operation", ["start", "stop", "reset"])
def test_d7_ordinary_generator_finalization_cannot_clobber_reentrant_run(env: Any, operation: str) -> None:
    owner = env.FSM("finalizer")
    owner.AddState("old", exit_condition=lambda: False)
    owner.AddState("new", exit_condition=lambda: False)
    owner.start()
    events: list[str] = []

    def anonymous() -> Generator[None, None, None]:
        try:
            yield
        finally:
            events.append("finalized")
            owner.ResetAndStartAtStep("new")
            owner.pause()

    routine = anonymous()
    next(routine)
    owner.managed_coroutines.append(routine)
    del routine
    getattr(owner, operation)()
    assert events == ["finalized"], "the real generator's finalizer must execute during cleanup"
    assert owner.current_state.name == "new"
    assert not owner.finished
    assert owner.paused


@pytest.mark.parametrize("entry", ["restart", "condition"])
def test_d7_composite_restart_preserves_receipt_installed_after_nested_state_reset(env: Any, entry: str) -> None:
    child = make_fsm(env)
    parent = env.FSM("composite-restart")
    parent.AddSubroutine("child", condition_fn=lambda: True, sub_fsm=child)
    parent.start()
    installed: list[Any] = []
    events: list[str] = []

    def child_work() -> Generator[None, None, None]:
        try:
            yield
        finally:
            events.append("child-finalized")
            parent.current_state.reset()
            receipt = env.messaging.MerchantRules(0, make_message(env))
            assert parent.AddManagedCoroutine("new-receipt", receipt)
            installed.append(receipt)
            parent.pause()

    routine = child_work()
    next(routine)
    child.managed_coroutines.append(routine)
    del routine
    if entry == "restart":
        parent.restart()
    else:
        outer = env.FSM("outer-condition")
        outer.AddSubroutine("parent", condition_fn=lambda: True, sub_fsm=parent)
        outer.start()
        outer.update()
        assert not outer.current_state.sub_fsm_active
    assert events == ["child-finalized"]
    assert len(installed) == 1
    assert parent.HasManagedCoroutine("new-receipt"), "aborted reset must not permit the outer restart's start"
    assert installed[0] in parent.managed_coroutines
    assert parent.paused
    parent.update()
    assert env.world.table.Inbox[0].Running
    assert env.widget.merchant_rules_owned_work_count == 1


def _post_reconcile_successor_identity(env: Any, owner: Any, receipt: Any, index: int) -> tuple[Any, ...]:
    state = owner.current_state
    return (
        owner._dispatch_run_token,
        state,
        state.coroutine_instance,
        state._coroutine_binding,
        owner._managed_dispatch_bindings.get(id(receipt)),
        state.executed,
        state.transition_timer.resets,
        state.transition_timer.stops,
        owner.paused,
        bytes(env.world.table.Inbox[index]),
    )


@pytest.mark.parametrize("terminal", ["terminate", "natural"])
@pytest.mark.parametrize("visitor", ["global", "fsm"])
def test_d5_reconciliation_after_restart_precedes_retained_scheduler_visit(
    env: Any, monkeypatch: pytest.MonkeyPatch, terminal: str, visitor: str
) -> None:
    order: list[str] = ["scheduled"]
    fresh_receipts: list[Any] = []
    owner = env.FSM("post-reconcile-owner")
    owner.AddState("old", exit_condition=lambda: terminal == "natural")
    owner.AddSelfManagedYieldStep("successor", lambda: fresh_receipts[0])
    owner.states[0].set_next_state(None)
    owner.start()
    original_list = owner.managed_coroutines
    independent_owner = make_fsm(env)
    independent = env.messaging.MerchantRules(2, make_message(env, index=2, request="independent"))
    assert independent_owner.AddManagedCoroutine("independent", independent)
    independent_binding = independent_owner._managed_dispatch_bindings[id(independent)]
    independent_row = bytes(env.world.table.Inbox[2])
    unrelated_widget = real_widget(env, monkeypatch)
    unrelated_work = unrelated_widget._track_merchant_rules_owned_work(wait_once(7))
    assert unrelated_widget.merchant_rules_owned_work_count == 1
    checkpoints: list[tuple[Any, ...]] = []
    observe_stale = [False]

    def after_stale_entry() -> Generator[None, None, None]:
        order.append("stale-visit-checkpoint")
        fresh = fresh_receipts[0]
        assert old in owner.managed_coroutines
        assert owner.managed_coroutines is original_list
        assert _post_reconcile_successor_identity(env, owner, fresh, 0) == checkpoints[0]
        assert independent_owner._managed_dispatch_bindings[id(independent)] is independent_binding
        assert bytes(env.world.table.Inbox[2]) == independent_row
        assert env.widget.merchant_rules_remote_dispatch_count == 2
        assert env.widget.merchant_rules_owned_work_count == 0
        assert unrelated_widget.merchant_rules_owned_work_count == 1
        assert not env.actions.pending
        assert not env.results
        assert "scan" not in env.events
        yield

    def revoke_restart_and_reconcile() -> None:
        assert owner.AdoptGlobalCoroutine(old)
        if terminal == "terminate":
            owner.terminate()
        else:
            owner.update()
            assert owner.finished
        order.append("revoked")
        assert old in original_list
        assert id(old) not in owner._managed_dispatch_bindings
        owner.ResetAndStartAtStep("successor")
        assert old in owner.managed_coroutines
        assert owner.managed_coroutines is original_list
        order.append("restarted-with-retained-entry")
        if visitor == "fsm":
            owner.managed_coroutines.append(after_stale_entry())
        fresh = env.messaging.MerchantRules(0, make_message(env, request="fresh-successor"))
        fresh_receipts.append(fresh)
        owner.current_state.execute()
        owner.pause()
        assert owner.current_state.coroutine_instance is fresh
        assert owner._dispatch_binding_is_current(*owner.current_state._coroutine_binding)
        checkpoints.append(_post_reconcile_successor_identity(env, owner, fresh, 0))
        assert env.widget.merchant_rules_remote_dispatch_count == 3
        assert env.widget.merchant_rules_owned_work_count == (1 if terminal == "natural" else 0)
        assert old in owner.managed_coroutines
        order.append("reconcile-enter")
        env.messaging.main()
        order.append("reconcile-exit")
        assert old.terminal
        assert old in owner.managed_coroutines
        assert _post_reconcile_successor_identity(env, owner, fresh, 0) == checkpoints[0]
        assert not fresh.terminal and not independent.terminal
        assert fresh in env.messaging._merchant_rules_dispatches.values()
        assert independent in env.messaging._merchant_rules_dispatches.values()
        assert env.widget.merchant_rules_remote_dispatch_count == 2
        assert env.widget.merchant_rules_owned_work_count == 0
        old.close()
        old.close()
        assert env.widget.merchant_rules_remote_dispatch_count == 2
        assert unrelated_widget.merchant_rules_owned_work_count == 1
        observe_stale[0] = True

    def global_controller() -> Generator[None, None, None]:
        revoke_restart_and_reconcile()
        yield

    if visitor == "global":
        env.cache.Coroutines.append(global_controller())
    old = queue_receipt(env, request="expired")
    receipt_type = env.messaging._MerchantRulesDispatchReceipt
    assert type(old) is receipt_type
    original_next: Callable[[Any], Any] = receipt_type.__next__
    original_getattribute: Callable[[Any, str], Any] = receipt_type.__getattribute__

    def observed_next(receipt: Any) -> Any:
        if receipt is old and observe_stale[0]:
            order.append("stale-global-entry")
        return original_next(receipt)

    def observed_attribute(receipt: Any, name: str) -> Any:
        value = original_getattribute(receipt, name)
        if receipt is old and observe_stale[0] and name == "_fsm_dispatch_receipt":
            order.append("stale-fsm-entry")
        return value

    # These observers delegate unchanged production operations. In particular,
    # an FSM with no old binding must inspect and skip that retained entry.
    monkeypatch.setattr(receipt_type, "__next__", observed_next)
    monkeypatch.setattr(receipt_type, "__getattribute__", observed_attribute)
    if visitor == "global":
        env.cache.Coroutines.append(after_stale_entry())
        env.scheduler()
    else:
        revoke_restart_and_reconcile()
        owner.update()
    observe_stale[0] = False
    assert order == [
        "scheduled",
        "revoked",
        "restarted-with-retained-entry",
        "reconcile-enter",
        "reconcile-exit",
        f"stale-{visitor}-entry",
        "stale-visit-checkpoint",
    ]
    fresh = fresh_receipts[0]
    assert owner.current_state.coroutine_instance is fresh
    assert owner._dispatch_binding_is_current(*owner.current_state._coroutine_binding)
    assert old in owner.managed_coroutines
    order.append("fresh-valid-owner")
    if visitor == "global":
        owner.update()
    assert env.world.table.Inbox[0].Running
    owner.update()
    assert not env.world.table.Inbox[0].Active
    order.append("independent-valid-owner")
    independent_owner.update()
    assert env.world.table.Inbox[2].Running
    independent_owner.update()
    assert not env.world.table.Inbox[2].Active
    assert {result[1]["request_id"] for result in env.results} == {"fresh-successor", "independent"}
    assert env.widget.merchant_rules_remote_dispatch_count == env.widget.merchant_rules_owned_work_count == 0
    order.append("unrelated-widget-valid-owner")
    assert next(unrelated_work) == 7
    unrelated_work.close()
    assert unrelated_widget.merchant_rules_owned_work_count == 0
    assert order[-3:] == ["fresh-valid-owner", "independent-valid-owner", "unrelated-widget-valid-owner"]


@pytest.mark.parametrize("terminal", ["terminate", "natural"])
def test_d11_post_restart_reconciliation_preserves_independent_owner(
    env: Any, monkeypatch: pytest.MonkeyPatch, terminal: str
) -> None:
    order: list[str] = ["scheduled"]
    first = make_fsm(env, final=terminal == "natural")
    second = make_fsm(env)
    old = queue_receipt(env, request="shared-old")
    assert first.AdoptGlobalCoroutine(old)
    assert second.AddManagedCoroutine("shared", old)
    expired_binding = first._managed_dispatch_bindings[id(old)]
    independent_binding = second._managed_dispatch_bindings[id(old)]
    original_list = first.managed_coroutines
    if terminal == "terminate":
        first.terminate()
    else:
        first.update()
        assert first.finished
    order.append("revoked")
    first.ResetAndStartAtStep("hold")
    first.current_state.exit_condition = lambda: False
    first.pause()
    assert old in first.managed_coroutines and first.managed_coroutines is original_list
    order.append("restarted-with-retained-entry")
    old_row = bytes(env.world.table.Inbox[0])
    original_inner_count = 1 if terminal == "natural" else 0
    assert env.widget.merchant_rules_owned_work_count == original_inner_count
    successor = (
        first._dispatch_run_token,
        first.current_state,
        first.current_state.executed,
        first.current_state.transition_timer.resets,
        first.current_state.transition_timer.stops,
        first.paused,
    )
    order.append("reconcile-enter")
    env.messaging.main()
    order.append("reconcile-exit")
    assert old in first.managed_coroutines
    assert not old.terminal
    assert second._managed_dispatch_bindings[id(old)] is independent_binding
    assert bytes(env.world.table.Inbox[0]) == old_row
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    assert env.widget.merchant_rules_owned_work_count == original_inner_count
    order.append("expired-attachment-call")
    assert old._advance_fsm(first, expired_binding[1], expired_binding[2]) is False
    assert not old.terminal
    assert bytes(env.world.table.Inbox[0]) == old_row
    assert env.widget.merchant_rules_owned_work_count == original_inner_count
    receipt_type = env.messaging._MerchantRulesDispatchReceipt
    assert type(old) is receipt_type
    original_getattribute: Callable[[Any, str], Any] = receipt_type.__getattribute__
    observe_stale = [True]

    def observed_attribute(receipt: Any, name: str) -> Any:
        value = original_getattribute(receipt, name)
        if receipt is old and observe_stale[0] and name == "_fsm_dispatch_receipt":
            order.append("stale-fsm-entry")
        return value

    monkeypatch.setattr(receipt_type, "__getattribute__", observed_attribute)
    first.update()
    observe_stale[0] = False
    order.append("stale-visit-complete")
    assert successor == (
        first._dispatch_run_token,
        first.current_state,
        first.current_state.executed,
        first.current_state.transition_timer.resets,
        first.current_state.transition_timer.stops,
        first.paused,
    )
    assert old in first.managed_coroutines
    assert second._managed_dispatch_bindings[id(old)] is independent_binding
    assert bytes(env.world.table.Inbox[0]) == old_row
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    assert env.widget.merchant_rules_owned_work_count == original_inner_count
    assert not env.results and not env.actions.pending
    assert "scan" not in env.events
    assert order == [
        "scheduled",
        "revoked",
        "restarted-with-retained-entry",
        "reconcile-enter",
        "reconcile-exit",
        "expired-attachment-call",
        "stale-fsm-entry",
        "stale-visit-complete",
    ]
    order.append("independent-valid-owner")
    second.update()
    if terminal == "terminate":
        assert env.world.table.Inbox[0].Running
        second.update()
    assert old.terminal
    assert not env.world.table.Inbox[0].Active
    assert [result[1]["request_id"] for result in env.results] == ["shared-old"]
    assert env.widget.merchant_rules_remote_dispatch_count == env.widget.merchant_rules_owned_work_count == 0
    fresh = env.messaging.MerchantRules(1, make_message(env, index=1, request="fresh-after-stale"))
    assert first.AddManagedCoroutine("fresh", fresh)
    order.append("fresh-valid-owner")
    first.update()
    assert env.world.table.Inbox[1].Running
    first.update()
    assert not env.world.table.Inbox[1].Active
    assert [result[1]["request_id"] for result in env.results] == ["shared-old", "fresh-after-stale"]
    assert env.widget.merchant_rules_remote_dispatch_count == env.widget.merchant_rules_owned_work_count == 0
    assert order[-2:] == ["independent-valid-owner", "fresh-valid-owner"]
