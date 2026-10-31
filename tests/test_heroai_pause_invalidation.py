"""Native-free production lifecycle paths; ACTION drains independently of widget ticks."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from typing import Any

import pytest
from test_heroai_movement_dispatch import load_widget_module
from test_restoration_spirit_admission import install_test_module
from test_restoration_spirit_admission import load_test_module
from test_smart_heroic_refrain import SY
from test_smart_heroic_refrain import admission_world as admission_world
from test_smart_heroic_refrain import load_headless_tree
from test_smart_heroic_refrain import world as _heroic_world_fixture

ROOT = Path(__file__).resolve().parents[1]
heroic_world = _heroic_world_fixture


def _ignore(*args: Any) -> None:
    pass


@dataclass
class _Runtime:
    world: Any
    manager: Any
    widget: Any
    widget_source: Any
    bot: Any
    events: list[str]
    lifecycle: list[str]
    make_widget: Callable[[ModuleType], Any]


@pytest.fixture
def runtime(heroic_world: Any, monkeypatch: pytest.MonkeyPatch) -> _Runtime:
    world = heroic_world
    events: list[str] = []
    lifecycle: list[str] = []
    module = install_test_module
    load = load_test_module

    def record(event: str) -> Callable[..., None]:
        def callback(*args: Any) -> None:
            events.append(event)

        return callback

    console = SimpleNamespace(
        get_projects_path=lambda: str(ROOT),
        Log=record("log"),
        MessageType=SimpleNamespace(Info=1, Error=2, Warning=3),
    )
    monkeypatch.setattr(sys.modules["PySystem"], "Console", console, raising=False)
    for name in ("PyPing", "PyGameThread", "PyDXOverlay", "PyAgentEvents", "PyImGui"):
        module(monkeypatch, name)
    module(
        monkeypatch,
        "PyCallback",
        PyCallback=SimpleNamespace(
            PauseById=record("scheduler.pause"),
            ResumeById=record("scheduler.resume"),
        ),
    )
    imports: dict[str, dict[str, Any]] = {
        "Py4GWCoreLib.HotkeyManager": {"HOTKEY_MANAGER": object(), "HotKey": object},
        "Py4GWCoreLib.ImGui_src.Style": {"Style": object},
        "Py4GWCoreLib.ImGui_src.types": {"Alignment": object, "StyleTheme": object},
        "Py4GWCoreLib.py4gwcorelib_src.Settings": {"Settings": object},
        "Py4GWCoreLib.ImGui": {"ImGui": object},
        "Py4GWCoreLib.enums_src.IO_enums": {"Key": object, "ModifierKey": object},
        "Py4GWCoreLib.enums_src.Multiboxing_enums": {"SharedCommandType": object},
        "Py4GWCoreLib.ImGui_src.IconsFontAwesome5": {"IconsFontAwesome5": object},
        "Py4GWCoreLib.py4gwcorelib_src.Color": {"Color": object},
    }
    for name, attributes in imports.items():
        module(monkeypatch, name, **attributes)
    manager: Any = load(
        monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.WidgetManager", "Py4GWCoreLib/py4gwcorelib_src/WidgetManager.py"
    )
    widget_source: Any = load_widget_module()
    widget_source.heroai_build = world.driver
    widget_source.HeroAI_FloatingWindows = SimpleNamespace(
        settings=SimpleNamespace(reset=_ignore), SETTINGS_THROTTLE=SimpleNamespace(SetThrottleTime=_ignore)
    )
    monkeypatch.setitem(
        sys.modules, "py4gw_widget_Automation_Multiboxing_HeroAI_py", ModuleType("pause_test_placeholder")
    )

    def make_widget(source: ModuleType) -> Any:
        # Only module execution/registration are stubbed. Widget construction,
        # callback extraction, pause/resume, enable/disable and reload are real.
        def execute(target: ModuleType) -> None:
            target.__dict__.update(source.__dict__)

        def spec_from_file_location(*args: Any) -> SimpleNamespace:
            return SimpleNamespace(loader=SimpleNamespace(exec_module=execute))

        def module_from_spec(spec: Any) -> ModuleType:
            return ModuleType("pause_test_widget")

        manager.importlib = SimpleNamespace(
            util=SimpleNamespace(
                spec_from_file_location=spec_from_file_location,
                module_from_spec=module_from_spec,
            )
        )
        widget = manager.Widget(
            folder_script_name="Automation/Multiboxing/HeroAI.py",
            script_path=str(ROOT / "Widgets/Automation/Multiboxing/HeroAI.py"),
        )
        widget.RegisterCallbacks = lambda: events.append("register")
        widget.main_callback_id = 1
        widget.enable()
        return widget

    widget = make_widget(widget_source)
    world.driver._build_registry._iter_matchable_builds = lambda: [world.owner]
    assert world.driver.EnsureBuildContract() is world.owner
    headless = load_headless_tree(world, monkeypatch)
    headless.tree = SimpleNamespace(reset=lambda: events.append("tree.reset"))
    behavior: Any = sys.modules["Py4GWCoreLib.py4gwcorelib_src.BehaviorTree"].__dict__["BehaviorTree"]
    module(
        monkeypatch,
        "Py4GWCoreLib.py4gwcorelib_src.BehaviorTree",
        BehaviorTree=type("_BehaviorTree", (), {"Node": object, "NodeState": behavior.NodeState}),
    )
    module(monkeypatch, "Py4GWCoreLib.botting_tree_src", __path__=[])
    module(monkeypatch, "Py4GWCoreLib.GlobalCache.shared_memory_src.Globals", SHMEM_MAX_NUMBER_OF_SKILLS=8)
    module(monkeypatch, "Py4GWCoreLib.GlobalCache.shared_memory_src.HeroAIOptionStruct", HeroAIOptionStruct=object)
    module(
        monkeypatch,
        "Py4GWCoreLib.botting_tree_src.enums",
        HeroAIStatus=SimpleNamespace(DISABLED=SimpleNamespace(value="disabled")),
        PlannerStatus=object,
    )
    load(monkeypatch, "Py4GWCoreLib.botting_tree_src.heroai", "Py4GWCoreLib/botting_tree_src/heroai.py")
    dependencies = {
        "account_config": ["BottingTreeAccountConfig", "BottingTreeAccountMode"],
        "auto_inventory": ["BottingTreeAutoInventoryMixin"],
        "blackboard": ["BottingTreeBlackboardMixin"],
        "config": ["_BottingTreeConfig"],
        "debugging": ["BottingTreeDebuggingMixin"],
        "isolation": ["BottingTreeIsolationMixin"],
        "messaging": ["BottingTreeMessagingMixin"],
        "planner": ["BottingTreePlannerMixin"],
        "services": ["BottingTreeServicesMixin"],
        "ticks": ["BottingTreeTicksMixin"],
        "ui": ["BottingTreeUIMovePathMixin", "_BottingTreeUI"],
        "upkeep": ["BottingTreeUpkeepMixin"],
        "widget_control": ["BottingTreeWidgetControlMixin"],
    }
    for name, classes in dependencies.items():
        module(monkeypatch, f"Py4GWCoreLib.botting_tree_src.{name}", **{cls: type(cls, (), {}) for cls in classes})
    module(monkeypatch, "Py4GWCoreLib.routines_src.behaviourtrees_src", constants=SimpleNamespace())
    bot_module = load(monkeypatch, "Py4GWCoreLib.BottingTree", "Py4GWCoreLib/BottingTree.py")
    bot = object.__new__(bot_module.BottingTree)
    bot.headless_heroai = headless
    bot.started, bot.paused, bot.headless_heroai_enabled = True, False, True
    bot.blackboard = {"retained": object()}
    bot._last_heroai_state = "active"
    bot.ApplyAccountIsolation = lambda: events.append("isolation")
    bot._restore_heroai_widget_after_headless = lambda: events.append("handoff")
    bot._disable_heroai_widget_for_headless = lambda: events.append("widget.disable")

    def sync_widget(enabled: bool) -> None:
        events.append(f"sync:{enabled}")

    bot._sync_multibox_heroai_widget = sync_widget
    activate, dispose = world.owner.OnContractActivated, world.owner.Dispose

    def activated(data: Any = None) -> None:
        lifecycle.append("activate")
        activate(data)

    def disposed(reason: str = "contract_disposed") -> None:
        lifecycle.append(f"dispose:{reason}")
        dispose(reason)

    world.owner.OnContractActivated, world.owner.Dispose = activated, disposed
    events.clear()
    return _Runtime(world, manager, widget, widget_source, bot, events, lifecycle, make_widget)


def _queue_valid(runtime: _Runtime) -> Any:
    w = runtime.world
    w.pressure()
    assert w.policy.TryCast(), "Precondition: a valid request must enter the real guarded queue"
    request = w.policy._request
    assert request is not None and request.submitted_ms is None
    assert w.driver._tick_coroutine is None, "Reproduction must not depend on a scheduler generator"
    return request


def _dispatch_pending(runtime: _Runtime, request: Any) -> None:
    w = runtime.world
    w.dispatch(delay=50)
    assert w.now - request.queued_ms < w.policy.QUEUE_MS, "Cancellation must not be explained by timeout"


@pytest.mark.parametrize("resume", [False, True], ids=["paused", "rapid_resume"])
def test_widget_pause_revokes_pending_request(runtime: _Runtime, resume: bool) -> None:
    request = _queue_valid(runtime)
    runtime.widget.pause()
    if resume:
        runtime.widget.resume()
        assert not runtime.widget.is_paused
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == [], f"Widget pause must revoke pending request; native calls={runtime.world.calls}"
    assert runtime.lifecycle == [], "Scheduler pause must not dispose or reactivate the cached controller"


@pytest.mark.parametrize("resume", [False, True], ids=["paused", "rapid_resume"])
def test_headless_pause_revokes_before_handoff(runtime: _Runtime, resume: bool) -> None:
    request = _queue_valid(runtime)
    seen: list[int] = []
    runtime.bot._restore_heroai_widget_after_headless = lambda: seen.append(runtime.world.owner.GetPolicyGeneration())
    runtime.bot.Pause()
    if resume:
        runtime.bot.Pause(False)
        assert not runtime.bot.paused
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == [], f"Headless pause must revoke pending request; native calls={runtime.world.calls}"
    assert seen and seen[0] > request.generation, "Revoke the old executor before restoring ordinary HeroAI"
    assert runtime.lifecycle == []


@pytest.mark.parametrize("resume", [False, True], ids=["disabled", "rapid_enable"])
def test_retained_headless_disable_revokes_pending_request(runtime: _Runtime, resume: bool) -> None:
    request = _queue_valid(runtime)
    headless = runtime.bot.headless_heroai
    retained = (headless.tree, headless._follow_state, headless.cached_data, dict(runtime.bot.blackboard))
    runtime.bot.SetHeadlessHeroAIEnabled(False, reset_runtime=False)
    if resume:
        runtime.bot.SetHeadlessHeroAIEnabled(True, reset_runtime=False)
        assert runtime.bot.headless_heroai_enabled
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == [], f"Retained headless disable dispatched: {runtime.world.calls}"
    assert runtime.world.driver.GetBuildContract() is runtime.world.owner
    assert retained == (headless.tree, headless._follow_state, headless.cached_data, runtime.bot.blackboard)
    assert runtime.lifecycle == [] and "tree.reset" not in runtime.events


@pytest.mark.parametrize("suppress", ["optional", "all"])
def test_manager_suppression_preserves_surrounding_actions(runtime: _Runtime, suppress: str) -> None:
    request = _queue_valid(runtime)
    actions: list[str] = []
    runtime.world.queue.insert(0, lambda: actions.append("before"))
    runtime.world.queue.append(lambda: actions.append("after"))
    handler = runtime.manager.WidgetHandler()
    generic = runtime.make_widget(ModuleType("generic_widget"))
    handler.widgets = {"HeroAI": runtime.widget, "Generic": generic}
    if suppress == "optional":
        handler.pause_optional_widgets()
        assert handler.optional_widgets_paused
    else:
        handler.PauseAllWidgets()
        assert handler.paused
    assert runtime.widget.is_paused and generic.is_paused
    for _ in range(3):
        _dispatch_pending(runtime, request)
    assert actions == ["before", "after"] and runtime.world.calls == []
    assert not runtime.world.queue and runtime.lifecycle == []


def test_widget_repeated_pause_disable_and_enable_counts(runtime: _Runtime) -> None:
    request = _queue_valid(runtime)
    runtime.widget.pause()
    generation = runtime.world.owner.GetPolicyGeneration()
    runtime.widget.pause()
    assert runtime.world.owner.GetPolicyGeneration() == generation, "Notify only the transition to paused"
    assert runtime.events == ["scheduler.pause", "scheduler.pause"]
    runtime.widget.disable()
    assert runtime.world.owner.GetPolicyGeneration() > generation
    generation = runtime.world.owner.GetPolicyGeneration()
    runtime.widget.disable()
    assert runtime.world.owner.GetPolicyGeneration() == generation
    assert runtime.lifecycle == []
    runtime.widget.enable()
    assert runtime.lifecycle == ["dispose:contract_cleared"], "Retain the existing enable cleanup, exactly once"
    assert runtime.world.driver.EnsureBuildContract() is runtime.world.owner
    assert runtime.lifecycle == ["dispose:contract_cleared", "activate"]
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == []


def test_generic_pause_notification_is_optional_and_transition_only(runtime: _Runtime) -> None:
    generic = runtime.make_widget(ModuleType("generic_widget"))
    runtime.events.clear()
    generic.pause()
    generic.pause()
    generic.resume()
    assert generic.on_pause is None and not generic.is_paused
    assert runtime.events == ["scheduler.pause", "scheduler.pause", "scheduler.resume"]
    notifications: list[str] = []
    generic.on_pause = lambda: notifications.append("pause")
    generic.pause()
    generic.pause()
    generic.resume()
    generic.pause()
    assert notifications == ["pause", "pause"]
    # Construction starts paused; it has no active execution permission to revoke.
    initial = runtime.manager.Widget(
        folder_script_name="Automation/Multiboxing/HeroAI.py", script_path=runtime.widget.script_path
    )
    initial.on_pause = lambda: notifications.append("unexpected")
    initial.pause()
    assert notifications == ["pause", "pause"]


def test_reload_revokes_before_replacement_and_reloads_pause_callback(runtime: _Runtime) -> None:
    request = _queue_valid(runtime)
    handler = runtime.manager.WidgetHandler()
    handler.widgets = {"HeroAI": runtime.widget}
    seen: list[int] = []

    def scan_stub() -> None:
        assert not runtime.widget.enabled and handler.widgets == {}
        seen.append(runtime.world.owner.GetPolicyGeneration())
        handler.widgets["HeroAI"] = runtime.make_widget(runtime.widget_source)

    # Keep the production unload/reload ordering without filesystem discovery.
    handler._scan_widget_folders = scan_stub
    handler.reload_widgets()
    replacement = handler.widgets["HeroAI"]
    assert seen[0] > request.generation
    assert replacement is not runtime.widget and replacement.on_pause is runtime.widget_source.on_pause
    assert runtime.lifecycle == ["dispose:contract_cleared"]
    assert runtime.world.driver.EnsureBuildContract() is runtime.world.owner
    assert runtime.lifecycle == ["dispose:contract_cleared", "activate"]
    replacement.pause()
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == []
    assert runtime.make_widget(ModuleType("without_callback")).on_pause is None


@pytest.mark.parametrize("entry", ["widget", "headless_pause", "headless_disable"])
def test_fresh_cached_work_survives_old_callback_and_finalizer(runtime: _Runtime, entry: str) -> None:
    old = _queue_valid(runtime)
    _suspend(runtime, entry)
    _resume(runtime, entry)
    w = runtime.world
    assert w.driver.EnsureBuildContract() is w.owner
    w.policy.Advance()
    w.now += 150
    w.health[3] = 0.5
    assert w.policy.TryCast(), "Resumed cached owner must accept fresh pressure work"
    fresh = w.policy._request
    assert fresh is not old and fresh.generation > old.generation
    _dispatch_pending(runtime, old)
    assert w.policy._request is fresh and w.calls == []
    w.policy._finish(old, "late_cleanup", failed=True)
    assert w.policy._request is fresh and w.policy._retry["sy"].failures == 0
    w.dispatch()
    assert w.calls == [(SY, 0)] and runtime.lifecycle == []


def _suspend(runtime: _Runtime, entry: str) -> None:
    if entry == "widget":
        runtime.widget.pause()
    elif entry == "headless_pause":
        runtime.bot.Pause()
    else:
        runtime.bot.SetHeadlessHeroAIEnabled(False, reset_runtime=False)


def _resume(runtime: _Runtime, entry: str) -> None:
    if entry == "widget":
        runtime.widget.resume()
    elif entry == "headless_pause":
        runtime.bot.Pause(False)
    else:
        runtime.bot.SetHeadlessHeroAIEnabled(True, reset_runtime=False)


@pytest.mark.parametrize("entry", ["widget", "headless_pause", "headless_disable"])
def test_submitted_native_work_keeps_bounded_guard_without_resubmission(runtime: _Runtime, entry: str) -> None:
    request = _queue_valid(runtime)
    w = runtime.world
    callback = w.queue[0]
    _dispatch_pending(runtime, request)
    assert w.calls == [(SY, 0)] and request.submitted_ms is not None
    guard, sequence = w.policy._dispatch_guard_until, w.owner.GetLocalActionSequence()
    _suspend(runtime, entry)
    _resume(runtime, entry)
    callback()
    assert not w.policy.TryCast(), "Suspension must not forgive the native submission guard"
    assert w.policy._dispatch_guard_until == guard and w.owner.GetLocalActionSequence() == sequence
    assert w.policy._retry["sy"].failures == 0
    assert w.calls == [(SY, 0)] and not w.queue and runtime.lifecycle == []
    w.now = guard
    assert not w.policy.Advance(), "The retained guard must still expire normally"


@pytest.mark.parametrize("entry", ["headless_pause", "headless_disable"])
def test_repeated_headless_suppression_keeps_lifecycle_counts(runtime: _Runtime, entry: str) -> None:
    request = _queue_valid(runtime)
    _suspend(runtime, entry)
    _suspend(runtime, entry)
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == [] and runtime.lifecycle == []
    assert runtime.events.count("handoff") == (1 if entry == "headless_pause" else 0)
    assert "tree.reset" not in runtime.events


def test_headless_disable_with_reset_retains_existing_reset_and_disposal_counts(runtime: _Runtime) -> None:
    request = _queue_valid(runtime)
    old_follow = runtime.bot.headless_heroai._follow_state
    retained = runtime.bot.blackboard["retained"]
    runtime.bot.SetHeadlessHeroAIEnabled(False, reset_runtime=True)
    assert runtime.events == ["isolation", "sync:False", "tree.reset"]
    assert runtime.lifecycle == ["dispose:contract_cleared"]
    assert runtime.world.driver.GetBuildContract() is None
    assert runtime.bot.headless_heroai._follow_state is not old_follow
    assert runtime.bot.blackboard["retained"] is retained
    assert runtime.bot.blackboard["HEROAI_STATUS"] == "disabled"
    runtime.bot.SetHeadlessHeroAIEnabled(False, reset_runtime=True)
    assert runtime.events.count("tree.reset") == 2, "Retain one existing reset per explicit call"
    assert runtime.lifecycle == ["dispose:contract_cleared"]
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == []


@pytest.mark.parametrize("failure", ["scheduler", "handoff", "isolation", "sync", "reset"])
def test_revocation_precedes_failing_cleanup(runtime: _Runtime, failure: str) -> None:
    request = _queue_valid(runtime)
    seen: list[int] = []

    def fail(*args: Any) -> None:
        seen.append(runtime.world.owner.GetPolicyGeneration())
        raise RuntimeError(failure)

    def disable_with_reset() -> None:
        runtime.bot.SetHeadlessHeroAIEnabled(False, reset_runtime=True)

    if failure == "scheduler":
        runtime.widget.PauseCallbacks = fail
        action = runtime.widget.pause
    elif failure == "handoff":
        runtime.bot._restore_heroai_widget_after_headless = fail
        action = runtime.bot.Pause
    else:
        if failure == "isolation":
            runtime.bot.ApplyAccountIsolation = fail
        elif failure == "sync":
            runtime.bot._sync_multibox_heroai_widget = fail
        else:
            runtime.bot.headless_heroai.tree.reset = fail
        action = disable_with_reset
    with pytest.raises(RuntimeError, match=failure):
        action()
    assert seen and seen[0] > request.generation, "Revoke before invoking potentially failing external cleanup"
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == [] and runtime.lifecycle == []


def test_optional_hook_failure_is_logged_and_scheduler_still_pauses(runtime: _Runtime) -> None:
    request = _queue_valid(runtime)

    def hook() -> None:
        runtime.widget_source.on_pause()
        assert runtime.widget.is_paused, "Set state before notification to prevent recursive transitions"
        raise RuntimeError("hook failure")

    runtime.widget.on_pause = hook
    runtime.widget.pause()
    assert runtime.events == ["log", "log", "scheduler.pause"]
    _dispatch_pending(runtime, request)
    assert runtime.world.calls == [] and runtime.lifecycle == []
