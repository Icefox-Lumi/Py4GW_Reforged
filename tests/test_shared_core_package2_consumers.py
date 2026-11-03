"""Selected pinned MR and ordinary Botting consumers of Package 2 lifetimes."""

# pyright: strict

from __future__ import annotations

import ast
import sys
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from test_shared_core_package1_consumers import Source
from test_shared_core_package2_dispatch import account_world as account_world
from test_shared_core_package2_dispatch import assert_terminal
from test_shared_core_package2_dispatch import drain
from test_shared_core_package2_dispatch import env as dispatch_env_fixture
from test_shared_core_package2_dispatch import make_fsm
from test_shared_core_package2_dispatch import make_message
from test_shared_core_package2_dispatch import queue_receipt
from test_shared_core_package2_dispatch import read_source
from test_shared_core_package2_dispatch import real_widget
from test_shared_core_package2_dispatch import selected
from test_shared_core_package2_dispatch import wait_once
from test_shared_core_package2_dispatch import world as world

BOTTING = Source("Py4GWCoreLib/Botting.py", "781b9b4213a2eb64e7e23ace94f9794bb2628e74")
STATES = Source("Py4GWCoreLib/botting_src/subclases_src/STATES_src.py", "10bda9072ad01abf1937f6489a664320e7c9a872")
EVENTS = Source("Py4GWCoreLib/botting_src/event.py", "38ae050a6c26c04752dd5cffeba047c4f66d078a")
UI = Source("Py4GWCoreLib/botting_src/subclases_src/UI_src.py", "52e6f2d5f9bcb14436edcc821efaf9db2652fa58")
env = dispatch_env_fixture


@pytest.mark.parametrize("change", ["widget", "profile", "account", "lifecycle"])
@pytest.mark.parametrize("started", [False, True])
def test_c1_pinned_owner_and_generation_cancel_stale_work(
    env: Any, monkeypatch: pytest.MonkeyPatch, change: str, started: bool
) -> None:
    receipt = queue_receipt(env)
    old_widget = env.widget
    if started:
        env.scheduler()
    if change == "widget":
        env.widget = real_widget(env, monkeypatch)
    elif change == "profile":
        old_widget.merchant_rules_profile_generation += 1
    elif change == "account":
        old_widget.account_key = "different@example.invalid"
    else:
        env.map_id = 2
    drain(env)
    receipt.close()
    assert "scan" not in env.events
    assert old_widget.merchant_rules_remote_dispatch_count == 0
    assert old_widget.merchant_rules_owned_work_count == 0
    assert not env.world.table.Inbox[0].Active
    if change == "widget":
        assert env.widget.merchant_rules_remote_dispatch_count == 0
        assert env.widget.merchant_rules_owned_work_count == 0


def test_c1_readiness_wait_and_reload_capture_are_real_widget_paths(env: Any) -> None:
    env.party_ready = False
    receipt = queue_receipt(env)
    env.scheduler()
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    assert env.widget.merchant_rules_owned_work_count == 0
    assert env.world.table.Inbox[0].Running
    env.party_ready = True
    env.scheduler()
    assert env.widget.merchant_rules_owned_work_count == 1
    receipt.close()
    env.cache.Coroutines.clear()
    reload_receipt = queue_receipt(env, opcode=1, request="reload")
    captured = env.widget._pending_multibox_profile_reload_payload
    assert captured == {"version": 1, "label": "captured"}
    env.payload["label"] = "later"
    assert captured["label"] == "captured"
    assert env.widget.pending_multibox_profile_reload == ("reload", env.world.sender, env.world.receiver)
    reload_receipt.close()
    assert env.widget.pending_multibox_profile_reload is None
    assert not env.widget._merchant_rules_staged_multibox_reload_requests
    assert env.reloads == []


@pytest.mark.parametrize("cancel_at", ["unstarted", "started", "after_action"])
def test_c2_nested_leases_and_deferred_callbacks(env: Any, cancel_at: str) -> None:
    called: list[str] = []

    def execute(**_kwargs: Any) -> Generator[int, None, None]:
        env.actions.AddActionWithDelay("ACTION", 100, lambda: called.append("native-command"))
        yield 250

    env.widget._execute_now = execute
    receipt = queue_receipt(env, opcode=3)
    assert env.widget.merchant_rules_remote_dispatch_count == 1
    assert env.widget.merchant_rules_owned_work_count == 0
    if cancel_at != "unstarted":
        env.scheduler()
        assert env.widget.merchant_rules_remote_dispatch_count == 1
        assert env.widget.merchant_rules_owned_work_count == 1
    if cancel_at == "after_action":
        env.scheduler()
        assert env.widget.merchant_rules_owned_action_count == 1
        assert len(env.actions.pending) == 1
        assert not called, "submission executed a supposedly deferred callback"
        env.widget.merchant_rules_profile_generation += 1
    receipt.close()
    receipt.close()
    assert env.widget.merchant_rules_remote_dispatch_count == 0
    assert env.widget.merchant_rules_owned_work_count == 0
    env.actions.drain()
    assert env.widget.merchant_rules_owned_action_count == 0
    assert not called


def test_c2_deferred_valid_callback_runs_once_after_receipt_completes(env: Any) -> None:
    called: list[str] = []

    def execute(**_kwargs: Any) -> Generator[int, None, None]:
        env.actions.AddAction("ACTION", lambda: called.append("command"))
        yield 1

    env.widget._execute_now = execute
    queue_receipt(env, opcode=3)
    drain(env)
    assert not called
    assert env.widget.merchant_rules_owned_work_count == env.widget.merchant_rules_remote_dispatch_count == 0
    assert env.widget.merchant_rules_owned_action_count == 1
    callback, args, kwargs = env.actions.pending[0]
    env.actions.drain()
    assert called == ["command"]
    assert env.widget.merchant_rules_owned_action_count == 0
    # Widget callback release is idempotent; transport must not replace that ownership.
    callback.release()
    assert env.widget.merchant_rules_owned_action_count == 0
    assert args == () and kwargs == {}


@pytest.mark.parametrize("failure", [False, True])
def test_c3_real_handler_completion_and_failure_restore_temporary_options(env: Any, failure: bool) -> None:
    options = env.world.table.GetHeroAIOptionsFromEmail(env.world.receiver)
    options.Following = True
    options.Combat = True
    env.widget.destroy_include_protected_items = False
    row = make_message(env)
    row.ExtraData[2].value = "1"
    row.ExtraData[3].value = "1"
    if failure:

        def scan_failure() -> None:
            raise ValueError("inert inventory scan failed")

        env.widget._scan_preview = scan_failure
    env.messaging._queue_merchant_rules_message(0, row)
    env.scheduler()
    assert env.widget.destroy_include_protected_items
    assert not options.Following
    drain(env)
    assert not env.widget.destroy_include_protected_items
    assert not env.widget.destroy_instant_enabled
    assert options.Following and options.Combat
    assert env.results[-1][1]["opcode"] == (199 if failure else 101)
    assert env.widget.merchant_rules_owned_work_count == env.widget.merchant_rules_remote_dispatch_count == 0
    assert not row.Active


def test_c3_cleanup_exception_cannot_leave_receipt_retrying_forever(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    receipt = queue_receipt(env)
    env.scheduler()

    def unavailable_options(_email: str) -> Any:
        raise ValueError("host options disappeared during cleanup")

    monkeypatch.setattr(env.world.table, "GetHeroAIOptionsFromEmail", unavailable_options)
    try:
        receipt.close()
    except ValueError:
        pass
    receipt.close()
    assert_terminal(env, receipt)
    assert env.widget.merchant_rules_owned_work_count == env.widget.merchant_rules_remote_dispatch_count == 0
    assert not env.world.table.Inbox[0].Active
    assert not env.messaging._merchant_rules_dispatches


def test_c3_distinct_preview_overlap_retains_inherited_temporary_option_limit(env: Any) -> None:
    first = make_message(env, index=0, request="first")
    first.ExtraData[2].value = "1"
    second = make_message(env, index=1, request="second")
    second.ExtraData[2].value = "0"
    env.messaging._queue_merchant_rules_message(0, first)
    env.messaging._queue_merchant_rules_message(1, second)
    assert env.widget.merchant_rules_remote_dispatch_count == 2
    env.scheduler()
    assert env.widget.merchant_rules_owned_work_count == 2
    drain(env)
    assert env.widget.merchant_rules_remote_dispatch_count == env.widget.merchant_rules_owned_work_count == 0
    # Two legitimate requests retain the widget's snapshot/restore overlap.
    # The transport receipt does not claim ownership of these widget options.
    assert env.widget.destroy_include_protected_items is True


def _bot(env: Any, monkeypatch: pytest.MonkeyPatch, owner: Any) -> Any:
    module = selected(
        read_source(BOTTING),
        f"{BOTTING.path}@{BOTTING.blob}",
        ("BottingClass.Start", "BottingClass.Stop", "BottingClass.StartAtStep", "BottingClass.Update"),
        monkeypatch,
        {},
    )
    bot = module.BottingClass()
    bot.config = SimpleNamespace(FSM=owner, fsm_running=False, initialized=True, state_description="", bot_name="test")
    bot.helpers = SimpleNamespace()
    bot._start_coroutines = lambda: env.events.append("upkeep")
    return bot


def test_c4_real_botting_state_wrappers_preserve_ordinary_waits(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = env.FSM("bot")
    bot = _bot(env, monkeypatch, owner)
    module = selected(read_source(STATES), f"{STATES.path}@{STATES.blob}", ("_STATES",), monkeypatch, {})
    states = module._STATES(bot)
    calls: list[str] = []

    def background() -> Generator[None, None, None]:
        calls.append("background-start")
        while True:
            yield

    def custom() -> Generator[None, None, None]:
        calls.append("custom-start")
        yield
        calls.append("custom-end")

    states.AddManagedCoroutine("background", background)
    states.AddCustomState(custom, "custom")
    states.RemoveManagedCoroutine("background")
    owner.AddState("hold", execute_fn=lambda: calls.append("hold"), exit_condition=lambda: False)
    bot.Start()
    for _ in range(8):
        bot.Update()
    assert calls == ["background-start", "custom-start", "custom-end", "hold"]
    assert not owner.HasManagedCoroutine("background")
    assert owner.current_state.name == "hold"
    bot.Stop()
    assert not bot.config.fsm_running
    assert not owner.is_started()
    assert not owner.managed_coroutines
    bot.StartAtStep("hold")
    assert bot.config.fsm_running
    assert owner.is_started()
    assert owner.current_state.name == "hold"


def test_c4_real_events_deduplicate_latch_and_advance_while_paused(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules["Py4GWCoreLib"], "Routines", env.routines, raising=False)
    module = selected(
        read_source(EVENTS), f"{EVENTS.path}@{EVENTS.blob}", ("Event", "Events.start", "Events.stop"), monkeypatch, {}
    )
    owner = make_fsm(env)
    events = module.Events()
    events.parent = SimpleNamespace(FSM=owner)
    fired: list[str] = []
    for name in (
        "on_death",
        "on_party_defeated",
        "on_party_wipe",
        "on_party_member_behind",
        "on_party_member_in_danger",
        "on_party_member_dead_behind",
        "on_party_member_dead",
    ):
        event = module.Event(events.parent, name, callback=lambda key=name: fired.append(key))
        event.should_trigger = lambda: True
        event.should_reset = lambda: False
        setattr(events, name, event)
    events.start()
    original = tuple(owner.managed_coroutines)
    events.start()
    assert tuple(owner.managed_coroutines) == original
    assert len(original) == 7
    owner.pause()
    owner.update()
    assert len(fired) == 7
    owner.update()
    assert len(fired) == 7
    ordinary = wait_once(1)
    assert owner.AddManagedCoroutine("ordinary", ordinary)
    events.stop()
    assert owner.managed_coroutines == [ordinary]


def _ui_toggle(env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    tree = ast.parse(read_source(UI), filename=UI.path)
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_UI")
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "_draw_main_child")
    candidates = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Call)
        and isinstance(node.test.func, ast.Attribute)
        and node.test.func.attr == "button"
        and any(isinstance(value, ast.Constant) and value.value == "##BotToggle" for value in ast.walk(node.test))
    ]
    assert len(candidates) == 1, "pinned UI toggle selection changed"
    function = ast.parse("def ui_toggle(self):\n    pass\n").body[0]
    assert isinstance(function, ast.FunctionDef)
    function.body = [candidates[0]]

    def pressed(_label: str) -> bool:
        return True

    namespace: dict[str, Any] = dict(
        icon="",
        legend="",
        PyImGui=SimpleNamespace(button=pressed),
        GLOBAL_CACHE=env.cache,
        ConsoleLog=env.log,
        Console=env.console,
    )
    exec(compile(ast.fix_missing_locations(ast.Module([function], [])), f"{UI.path}@{UI.blob}", "exec"), namespace)
    return namespace["ui_toggle"]


@pytest.mark.parametrize("pump_first", [False, True])
def test_c4_ui_clear_and_real_copied_scheduler_never_start_stale_receipt(
    env: Any, monkeypatch: pytest.MonkeyPatch, pump_first: bool
) -> None:
    owner = make_fsm(env)
    bot = _bot(env, monkeypatch, owner)
    bot.config.fsm_running = True
    toggle = _ui_toggle(env, monkeypatch)
    ui = SimpleNamespace(_config=bot.config, parent=bot)

    def clear_from_first_snapshot_entry() -> Generator[None, None, None]:
        toggle(ui)
        yield

    env.cache.Coroutines.append(clear_from_first_snapshot_entry())
    receipt = queue_receipt(env)
    if pump_first:
        env.messaging.main()
    # Upkeeper's inherited remove-after-clear may raise ValueError. It must never
    # delegate the stale second snapshot entry, regardless of that scheduler quirk.
    try:
        env.scheduler()
    except ValueError:
        pass
    env.messaging.main()
    assert not owner.is_started()
    assert not bot.config.fsm_running
    assert bot.config.state_description == "Idle"
    assert not env.cache.Coroutines
    assert "scan" not in env.events
    assert env.widget.merchant_rules_remote_dispatch_count == 0
    assert not env.world.table.Inbox[0].Active
    assert_terminal(env, receipt)


@pytest.mark.parametrize("phase", ["pending", "running"])
@pytest.mark.parametrize("survivor", ["successor_row", "independent_owner"])
def test_c4_ui_stop_reconcile_then_stale_snapshot_preserves_owners(
    env: Any, monkeypatch: pytest.MonkeyPatch, phase: str, survivor: str
) -> None:
    owner = make_fsm(env)
    independent = make_fsm(env)
    bot = _bot(env, monkeypatch, owner)
    bot.config.fsm_running = True
    toggle = _ui_toggle(env, monkeypatch)
    ui = SimpleNamespace(_config=bot.config, parent=bot)
    old = queue_receipt(env, request="before-ui-stop")
    assert owner.AddManagedCoroutine("old", old)
    expired_binding = owner._managed_dispatch_bindings[id(old)]
    expired_run = owner._dispatch_run_token
    if phase == "running":
        env.scheduler()
        assert env.world.table.Inbox[0].Running
        assert env.widget.merchant_rules_owned_work_count == 1
    else:
        assert not env.world.table.Inbox[0].Running
        assert env.widget.merchant_rules_owned_work_count == 0

    if survivor == "independent_owner":
        independent_receipt = old
        assert independent.AddManagedCoroutine("independent", old)
    else:
        independent_receipt = queue_receipt(env, index=1, request="independent")
        assert independent.AdoptGlobalCoroutine(independent_receipt)
        independent.update()
        assert env.world.table.Inbox[1].Running
    independent_binding = independent._managed_dispatch_bindings[id(independent_receipt)]
    independent_run = independent._dispatch_run_token
    assert env.cache.Coroutines == [old]
    assert "scan" not in env.events

    order: list[str] = []
    fresh_receipts: list[Any] = []
    successor_rows: list[bytes] = []
    captured_snapshots: list[tuple[Any, ...]] = []
    callbacks: list[str] = []

    def execute_fresh(**_kwargs: Any) -> Generator[int, None, None]:
        env.actions.AddAction("ACTION", lambda: callbacks.append("fresh-action"))
        yield 1

    env.widget._execute_now = execute_fresh

    def snapshot() -> tuple[Any, ...]:
        state = owner.current_state
        return (
            tuple(bytes(env.world.table.Inbox[index]) for index in range(3)),
            owner._dispatch_run_token,
            state,
            state._activation_token,
            state.executed,
            state.transition_timer.resets,
            state.transition_timer.stops,
            dict(owner._managed_dispatch_bindings),
            dict(owner._named_managed),
            tuple(owner.managed_coroutines),
            independent._dispatch_run_token,
            dict(independent._managed_dispatch_bindings),
            tuple(independent.managed_coroutines),
            dict(env.messaging._merchant_rules_dispatches),
            tuple(env.cache.Coroutines),
            env.widget,
            env.widget.merchant_rules_remote_dispatch_count,
            env.widget.merchant_rules_owned_work_count,
            env.widget.merchant_rules_owned_action_count,
            tuple(env.events),
            tuple(env.results),
            tuple(env.actions.pending),
        )

    def stop_restart_and_reconcile() -> Generator[None, None, None]:
        toggle(ui)
        order.append("ui-stop-and-global-clear")
        assert not owner.is_started()
        assert not bot.config.fsm_running
        assert not env.cache.Coroutines
        assert not owner.managed_coroutines, "real UI Stop clears FSM membership; the stale reference is in Upkeeper"
        assert not owner._dispatch_binding_is_current(*expired_binding)
        assert independent._dispatch_binding_is_current(*independent_binding)

        bot.StartAtStep("hold")
        order.append("restart")
        assert owner._dispatch_run_token is not expired_run
        assert owner.is_started() and bot.config.fsm_running
        fresh = env.messaging.MerchantRules(2, make_message(env, index=2, opcode=3, request="fresh-run"))
        assert owner.AddManagedCoroutine("fresh", fresh)
        fresh_receipts.append(fresh)
        if survivor == "successor_row":
            successor_rows.append(bytes(make_message(env, request="successor-row")))

        order.append("reconcile-enter")
        env.messaging.main()
        order.append("reconcile-return")
        assert owner.HasManagedCoroutine("fresh")
        assert independent._dispatch_run_token is independent_run
        assert independent._dispatch_binding_is_current(*independent_binding)
        assert not callbacks and not env.actions.pending
        if survivor == "successor_row":
            assert old.terminal
            assert bytes(env.world.table.Inbox[0]) == successor_rows[0]
            successor = env.cache.Coroutines[0]
            assert successor is not old
            assert successor in env.messaging._merchant_rules_dispatches.values()
            assert env.widget.merchant_rules_remote_dispatch_count == 3
            assert env.widget.merchant_rules_owned_work_count == 1
        else:
            assert not old.terminal
            assert old not in env.cache.Coroutines
            assert env.widget.merchant_rules_remote_dispatch_count == 2
            assert env.widget.merchant_rules_owned_work_count == (1 if phase == "running" else 0)
        captured_snapshots.append(snapshot())
        yield

    def snapshot_tail() -> Generator[None, None, None]:
        order.append("snapshot-tail")
        yield

    original_next = env.messaging._MerchantRulesDispatchReceipt.__next__

    def observed_next(receipt: Any) -> Any:
        if receipt is not old:
            return original_next(receipt)
        # Observe the real candidate call; its ownership decisions and return are unchanged.
        order.append("stale-global-enter")
        assert order == [
            "ui-stop-and-global-clear",
            "restart",
            "reconcile-enter",
            "reconcile-return",
            "stale-global-enter",
        ]
        assert snapshot() == captured_snapshots[0]
        result = original_next(receipt)
        assert result is None
        assert (
            snapshot() == captured_snapshots[0]
        ), "stale global caller changed successor work or another owner's leases"
        order.append("stale-global-return")
        return result

    monkeypatch.setattr(env.messaging._MerchantRulesDispatchReceipt, "__next__", observed_next)
    first = stop_restart_and_reconcile()
    tail = snapshot_tail()
    env.cache.Coroutines.insert(0, first)
    env.cache.Coroutines.append(tail)
    assert env.cache.Coroutines == [first, old, tail], "the real Upkeeper must capture the old receipt before UI clear"
    env.scheduler()
    assert order == [
        "ui-stop-and-global-clear",
        "restart",
        "reconcile-enter",
        "reconcile-return",
        "stale-global-enter",
        "stale-global-return",
        "snapshot-tail",
    ]
    assert "scan" not in env.events
    assert not callbacks
    assert snapshot() == captured_snapshots[0]

    # The invalid global caller above must not borrow this still-valid FSM attachment.
    independent.update()
    independent.update()
    assert independent_receipt.terminal
    assert env.events.count("scan") == 1
    assert fresh_receipts[0] in owner.managed_coroutines
    owner.update()
    owner.update()
    assert env.world.table.Inbox[2].Running
    assert len(env.actions.pending) == 1 and not callbacks
    owner.update()
    assert fresh_receipts[0].terminal
    assert env.widget.merchant_rules_owned_action_count == 1
    env.actions.drain()
    assert callbacks == ["fresh-action"]
    assert env.widget.merchant_rules_owned_action_count == 0
    if survivor == "successor_row":
        assert bytes(env.world.table.Inbox[0]) == successor_rows[0]
        drain(env)
        assert env.events.count("scan") == 2
    assert env.widget.merchant_rules_remote_dispatch_count == 0
    assert env.widget.merchant_rules_owned_work_count == 0
