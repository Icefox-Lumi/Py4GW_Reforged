"""Focused offline checks for the opt-in guarded Skillbar dispatch seam."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SKILLBAR_CACHE_PATH = ROOT / "Py4GWCoreLib" / "GlobalCache" / "SkillbarCache.py"


class _FakeSkillbar:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def UseSkill(self, slot: int, target: int = 0) -> bool:
        self.calls.append((slot, target))
        return slot == 4 and target == 99

    def GetContext(self) -> None:
        return None


class _FakeQueue:
    def __init__(self) -> None:
        self.add_calls: list[tuple[str, Any, tuple[Any, ...]]] = []
        self.delayed_calls: list[tuple[str, int, Any, tuple[Any, ...]]] = []

    def AddAction(self, queue_name: str, action: Any, *args: Any) -> None:
        self.add_calls.append((queue_name, action, args))

    def AddActionWithDelay(self, queue_name: str, delay: int, action: Any, *args: Any) -> None:
        self.delayed_calls.append((queue_name, delay, action, args))


def _load_cache_module() -> tuple[Any, _FakeQueue, Any]:
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name in {"PySkillbar", "Py4GWCoreLib", "Py4GWCoreLib.Py4GWcorelib"}
    }
    queue = _FakeQueue()
    try:
        py_skillbar = types.ModuleType("PySkillbar")
        py_skillbar.Skillbar = _FakeSkillbar
        core_package = types.ModuleType("Py4GWCoreLib")
        core_module = types.ModuleType("Py4GWCoreLib.Py4GWcorelib")
        core_module.ActionQueueManager = _FakeQueue
        sys.modules.update(
            {
                "PySkillbar": py_skillbar,
                "Py4GWCoreLib": core_package,
                "Py4GWCoreLib.Py4GWcorelib": core_module,
            }
        )
        spec = importlib.util.spec_from_file_location("d1c_test.skillbar_cache", SKILLBAR_CACHE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module, queue, module.SkillbarCache(queue)
    finally:
        for name in ("PySkillbar", "Py4GWCoreLib", "Py4GWCoreLib.Py4GWcorelib"):
            sys.modules.pop(name, None)
        sys.modules.update(original_modules)


def test_ordinary_use_skill_keeps_the_existing_delayed_queue_contract() -> None:
    module, queue, cache = _load_cache_module()
    native = cache._skillbar_instance

    cache.UseSkill(2, target_agent_id=7, aftercast_delay=33)

    assert len(queue.delayed_calls) == 1
    queue_name, delay, action, args = queue.delayed_calls[0]
    assert queue_name == "ACTION"
    assert delay == 33
    assert action == native.UseSkill
    assert args == (2, 7)
    assert queue.add_calls == []


def test_guarded_dispatch_queues_one_callback_and_delivers_native_result() -> None:
    _module, queue, cache = _load_cache_module()
    native = cache._skillbar_instance
    observed: list[bool] = []

    cache.QueueGuardedUseSkill(lambda use_skill: observed.append(use_skill(4, 99)))

    assert len(queue.add_calls) == 1
    assert queue.delayed_calls == []
    queue_name, action, args = queue.add_calls[0]
    assert queue_name == "ACTION"
    assert action.__self__ is cache
    assert args[0] is not None

    action(*args)

    assert observed == [True]
    assert native.calls == [(4, 99)]
    assert len(queue.add_calls) == 1


def test_guarded_callback_exception_is_owned_by_the_callback() -> None:
    _module, queue, cache = _load_cache_module()
    errors: list[str] = []

    def guarded(_use_skill: Any) -> None:
        try:
            raise RuntimeError("controller failure")
        except RuntimeError as error:
            errors.append(str(error))

    cache.QueueGuardedUseSkill(guarded)
    _queue_name, action, args = queue.add_calls[0]
    action(*args)

    assert errors == ["controller failure"]
    assert len(queue.add_calls) == 1
