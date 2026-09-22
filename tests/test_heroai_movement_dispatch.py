"""Focused regression tests for widget HeroAI movement/combat arbitration."""

from __future__ import annotations

import importlib.util
import sys
import types
from enum import Enum, auto
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

_MISSING = object()


class _NodeState(Enum):
    RUNNING = auto()
    SUCCESS = auto()
    FAILURE = auto()


class _Node:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.last_state: _NodeState | None = None
        self.blackboard: dict[str, Any] = {}

    def _tick_impl(self) -> _NodeState:
        return _NodeState.FAILURE

    def tick(self) -> _NodeState:
        result = self._tick_impl()
        self.last_state = result
        return result

    def reset(self) -> None:
        self.last_state = None


def _reset_children(children: list[_Node]) -> None:
    for child in children:
        child.reset()


class _ActionNode(_Node):
    def __init__(
        self, action_fn, aftercast_ms: int = 0, *args: Any, **kwargs: Any
    ) -> None:
        super().__init__()
        self.action_fn = action_fn
        self._action_done = False
        self._action_result: _NodeState | None = None

    def _tick_impl(self) -> _NodeState:
        if not self._action_done:
            result = self.action_fn()
            if result == _NodeState.RUNNING:
                return result
            self._action_done = True
            self._action_result = result
            return _NodeState.RUNNING

        result = self._action_result or _NodeState.FAILURE
        self._action_done = False
        self._action_result = None
        return result

    def reset(self) -> None:
        super().reset()
        self._action_done = False
        self._action_result = None


class _ConditionNode(_Node):
    def __init__(self, condition_fn, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.condition_fn = condition_fn

    def _tick_impl(self) -> _NodeState:
        result = self.condition_fn()
        if isinstance(result, _NodeState):
            return result
        return _NodeState.SUCCESS if bool(result) else _NodeState.FAILURE


class _SequenceNode(_Node):
    def __init__(self, children=None, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.children: list[_Node] = list(children or [])
        self._current_child_index = 0

    def _tick_impl(self) -> _NodeState:
        while self._current_child_index < len(self.children):
            result = self.children[self._current_child_index].tick()
            if result == _NodeState.RUNNING:
                return result
            if result == _NodeState.FAILURE:
                self._current_child_index = 0
                _reset_children(self.children)
                return result
            self._current_child_index += 1
        self._current_child_index = 0
        _reset_children(self.children)
        return _NodeState.SUCCESS

    def reset(self) -> None:
        super().reset()
        self._current_child_index = 0
        _reset_children(self.children)


class _SelectorNode(_SequenceNode):
    def _tick_impl(self) -> _NodeState:
        while self._current_child_index < len(self.children):
            result = self.children[self._current_child_index].tick()
            if result == _NodeState.RUNNING:
                return result
            if result == _NodeState.SUCCESS:
                self._current_child_index = 0
                _reset_children(self.children)
                return result
            self._current_child_index += 1
        self._current_child_index = 0
        _reset_children(self.children)
        return _NodeState.FAILURE


class _BehaviorTree:
    NodeState = _NodeState
    Node = _Node
    ActionNode = _ActionNode
    ConditionNode = _ConditionNode
    SequenceNode = _SequenceNode
    SelectorNode = _SelectorNode


def _install_module(
    name: str,
    *,
    package: bool = False,
    **attributes: Any,
) -> types.ModuleType:
    module = types.ModuleType(name)
    if package:
        module.__path__ = []
    module.__dict__.update(attributes)
    sys.modules[name] = module
    return module


def _load_widget_module() -> types.ModuleType:
    class _Timer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def IsExpired(self) -> bool:
            return True

        def Reset(self) -> None:
            pass

        def SetThrottleTime(self, *_args: Any) -> None:
            pass

    agent = SimpleNamespace(
        IsAlive=lambda *_args: True,
        IsKnockedDown=lambda *_args: False,
        IsCasting=lambda *_args: False,
        IsMoving=lambda *_args: False,
    )
    player = SimpleNamespace(
        GetAgentID=lambda: 1,
        GetAccountEmail=lambda: "test@example.com",
        GetXY=lambda: (0.0, 0.0),
    )
    game_map = SimpleNamespace(
        Pathing=SimpleNamespace(Quad=object),
        IsExplorable=lambda: True,
    )
    stub_names = {
        "Py4GW",
        "PyImGui",
        "PySystem",
        "Py4GWCoreLib",
        "Py4GWCoreLib.Builds",
        "Py4GWCoreLib.Builds.Any",
        "Py4GWCoreLib.Builds.Any.HeroAI",
        "Py4GWCoreLib.Map",
        "Py4GWCoreLib.Player",
        "Py4GWCoreLib.routines_src",
        "Py4GWCoreLib.routines_src.BehaviourTrees",
        "Py4GWCoreLib.HeroAI",
        "Py4GWCoreLib.HeroAI.cache_data",
        "Py4GWCoreLib.HeroAI.follow",
        "Py4GWCoreLib.HeroAI.follow.follower_runtime",
        "Py4GWCoreLib.HeroAI.dispatch_diagnostics",
        "Py4GWCoreLib.HeroAI.enemy_party",
        "Py4GWCoreLib.HeroAI.resurrection_scroll",
        "Py4GWCoreLib.HeroAI.team_viewer_broadcast",
        "Py4GWCoreLib.HeroAI.windows",
        "Py4GWCoreLib.HeroAI.ui_base",
        "Py4GWCoreLib.HeroAI.ui",
    }
    original_modules = {name: sys.modules.get(name, _MISSING) for name in stub_names}
    _install_module(
        "Py4GWCoreLib",
        package=True,
        GLOBAL_CACHE=SimpleNamespace(),
        Agent=agent,
        Map=game_map,
        Player=player,
        Range=SimpleNamespace(
            SafeCompass=SimpleNamespace(value=500),
            Adjacent=SimpleNamespace(value=100),
            Spellcast=SimpleNamespace(value=120),
        ),
        Routines=SimpleNamespace(),
        ThrottledTimer=_Timer,
        SharedCommandType=SimpleNamespace(PickUpLoot=1),
    )

    class _HeroAI_Build:
        def __init__(self, _cached_data: Any) -> None:
            pass

    class _CacheData:
        pass

    _install_module("Py4GW")
    _install_module(
        "PyImGui",
        get_io=lambda: SimpleNamespace(
            want_capture_keyboard=False,
            want_capture_mouse=False,
        ),
        is_key_down=lambda _key: False,
        is_mouse_down=lambda _button: False,
    )
    _install_module(
        "PySystem",
        get_tick_count64=lambda: 0,
        Console=SimpleNamespace(
            get_projects_path=lambda: ".",
            Log=lambda *_args, **_kwargs: None,
            MessageType=SimpleNamespace(Info=1, Error=2),
        ),
    )
    _install_module("Py4GWCoreLib.Builds", package=True)
    _install_module("Py4GWCoreLib.Builds.Any", package=True)
    _install_module(
        "Py4GWCoreLib.Builds.Any.HeroAI",
        HeroAI_Build=_HeroAI_Build,
    )
    _install_module("Py4GWCoreLib.Map", Map=game_map)
    _install_module("Py4GWCoreLib.Player", Player=player)
    _install_module("Py4GWCoreLib.routines_src", package=True)
    _install_module(
        "Py4GWCoreLib.routines_src.BehaviourTrees",
        BehaviorTree=_BehaviorTree,
    )
    _install_module("Py4GWCoreLib.HeroAI", package=True)
    _install_module("Py4GWCoreLib.HeroAI.cache_data", CacheData=_CacheData)
    _install_module("Py4GWCoreLib.HeroAI.follow", package=True)
    _install_module(
        "Py4GWCoreLib.HeroAI.follow.follower_runtime",
        FollowExecutionState=lambda: SimpleNamespace(
            stuck=SimpleNamespace(mode="idle"),
        ),
        execute_follower_follow=lambda *_args: _NodeState.FAILURE,
        get_follow_destination_distance=lambda *_args: 0.0,
        is_follow_recovery_active=lambda *_args: False,
    )
    _install_module(
        "Py4GWCoreLib.HeroAI.dispatch_diagnostics",
        cached_state_fields=lambda *_args: {},
        increment_counter=lambda *_args: None,
        log_compact_state=lambda *_args, **_kwargs: None,
        node_state=lambda value: str(getattr(value, "name", value)).lower(),
        set_active_owner=lambda *_args: None,
    )
    _install_module("Py4GWCoreLib.HeroAI.enemy_party")
    _install_module("Py4GWCoreLib.HeroAI.resurrection_scroll")
    _install_module("Py4GWCoreLib.HeroAI.team_viewer_broadcast")
    _install_module(
        "Py4GWCoreLib.HeroAI.windows",
        HeroAI_FloatingWindows=SimpleNamespace(),
        HeroAI_Windows=SimpleNamespace(),
    )
    _install_module(
        "Py4GWCoreLib.HeroAI.ui_base",
        HeroAI_BaseUI=SimpleNamespace(),
    )
    _install_module(
        "Py4GWCoreLib.HeroAI.ui",
        draw_configure_window=lambda *_args: None,
        draw_skip_cutscene_overlay=lambda *_args: None,
    )

    path = (
        Path(__file__).resolve().parents[1]
        / "Widgets"
        / "Automation"
        / "Multiboxing"
        / "HeroAI.py"
    )
    module_name = "_heroai_widget_movement_test_subject"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    subject = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = subject
    try:
        spec.loader.exec_module(subject)
    finally:
        for name, original in original_modules.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = cast(types.ModuleType, original)
    return subject


SUBJECT: Any = _load_widget_module()


def _configure_subject(
    *,
    in_aggro: bool,
    moving: bool,
    casting: bool = False,
) -> None:
    SUBJECT.cached_data = SimpleNamespace(
        data=SimpleNamespace(
            in_aggro=in_aggro,
            is_leader=False,
            local_in_aggro=False,
        ),
        account_options=SimpleNamespace(
            Combat=True,
            Following=True,
            Looting=False,
        ),
        combat_handler=SimpleNamespace(
            InCastingRoutine=lambda: False,
        ),
        auto_attack_timer=SimpleNamespace(Reset=lambda: None),
    )
    SUBJECT.Agent.IsAlive = lambda *_args: True
    SUBJECT.Agent.IsKnockedDown = lambda *_args: False
    SUBJECT.Agent.IsCasting = lambda *_args: casting
    SUBJECT.Agent.IsMoving = lambda *_args: moving
    SUBJECT.Player.GetAgentID = lambda: 1
    SUBJECT.get_follow_destination_distance = lambda *_args: 0.0
    SUBJECT.is_follow_recovery_active = lambda *_args: False
    SUBJECT.follow_execution_state.stuck.mode = "idle"
    SUBJECT.LootingNode = lambda *_args: _NodeState.FAILURE
    SUBJECT.HandleOutOfCombat = lambda *_args: False
    SUBJECT.user_interrupt = lambda: _NodeState.FAILURE
    SUBJECT.Follow = lambda *_args: _NodeState.FAILURE
    SUBJECT.HeroAI_BT.reset()


def _run_widget_ticks(ticks: int) -> int:
    combat_calls = 0

    def handle_combat(_cached_data: Any) -> bool:
        nonlocal combat_calls
        combat_calls += 1
        return True

    SUBJECT.HandleCombat = handle_combat
    for _ in range(ticks):
        SUBJECT.HeroAI_BT.tick()
    return combat_calls


def test_ooc_movement_interrupt_still_owns_the_selector():
    _configure_subject(in_aggro=False, moving=True)

    combat_calls = _run_widget_ticks(24)

    assert combat_calls == 0
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["movement_result"] == "success"
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["movement_reason"] == "agent_moving"


def test_combat_movement_yields_to_build_dispatch():
    _configure_subject(in_aggro=True, moving=True)

    combat_calls = _run_widget_ticks(24)

    assert combat_calls > 0
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["movement_result"] == "failure"
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["movement_reason"] == (
        "agent_moving_combat_yield"
    )
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["movement_moving"] is True


def test_sustained_combat_movement_cannot_starve_dispatch():
    _configure_subject(in_aggro=True, moving=True)

    combat_calls = _run_widget_ticks(80)

    assert combat_calls >= 8
    assert combat_calls <= 80


def test_casting_guard_still_blocks_dispatch_until_casting_ends():
    _configure_subject(in_aggro=True, moving=True, casting=True)

    blocked_calls = _run_widget_ticks(20)

    assert blocked_calls == 0
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["casting_blocked"] is True

    SUBJECT.Agent.IsCasting = lambda *_args: False
    resumed_calls = _run_widget_ticks(24)

    assert resumed_calls > 0


def test_movement_end_falls_through_to_combat():
    _configure_subject(in_aggro=True, moving=False)

    result = SUBJECT.movement_interrupt()

    assert result.name == "FAILURE"
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["movement_reason"] == "not_moving"
    assert _run_widget_ticks(24) > 0


def test_smart_unstuck_movement_interrupt_behavior_is_preserved():
    _configure_subject(in_aggro=True, moving=True)
    SUBJECT.follow_execution_state.stuck.mode = "detouring"

    result = SUBJECT.movement_interrupt()

    assert result.name == "FAILURE"
    assert SUBJECT._OUTER_DIAGNOSTIC_RUNTIME["movement_reason"] == (
        "smart_unstuck_active"
    )
