"""Offline D1A tests for dynamic My Mesmer ownership and fallback composition."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Any
from typing import Iterator
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"
COMPOSITION_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Mesmer" / "Me_Any" / "My Energy Surge.py"
SMART_ENERGY_PATH = SKILLS_DIR / "SmartEnergySurge.py"
SMART_MESMER_PATH = SKILLS_DIR / "SmartMesmer.py"
HERO_AI_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Any" / "HeroAI.py"
SPIRITUAL_PAIN_SKILL_ID = 1336


class _Profession(IntEnum):
    _None = 0
    Mesmer = 5


def _install_package(name: str, path: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeBuildMgr:
    def __init__(
        self,
        name: str = "Generic Build",
        required_primary: _Profession | None = None,
        required_secondary: _Profession | None = None,
        required_skills: list[int] | None = None,
        optional_skills: list[int] | None = None,
        **_: Any,
    ) -> None:
        self.build_name = name
        self.required_primary = required_primary
        self.required_secondary = required_secondary
        self.required_skills = list(required_skills or [])
        self.optional_skills = list(optional_skills or [])
        self.blocked_skills: list[int] = []
        self.fallback_name: str | None = None
        self.fallback: Any = None
        self._tick_success = False
        self._cached_data: Any = None

    def set_cached_data(self, cached_data: Any) -> None:
        self._cached_data = cached_data

    def ScoreMatch(
        self,
        current_primary: _Profession | None = None,
        current_secondary: _Profession | None = None,
        current_skills: list[int] | None = None,
    ) -> int:
        del current_skills
        if self.required_primary not in (None, _Profession(0), current_primary):
            return -1
        if self.required_secondary not in (None, _Profession(0), current_secondary):
            return -1
        return len(self.required_skills)

    def SetFallback(self, fallback_name: str | None = None, fallback_handler: Any = None) -> None:
        self.fallback_name = fallback_name
        self.fallback = fallback_handler

    def SetBlockedSkills(self, skill_ids: list[int] | None = None) -> None:
        self.blocked_skills = list(skill_ids or [])

    def SetSkillCastingFn(self, handler: Any) -> None:
        self._local_skill_casting_handler = handler

    def ResetTickState(self) -> None:
        self._tick_success = False

    def SetTickSuccess(self) -> None:
        self._tick_success = True

    def DidTickSucceed(self) -> bool:
        return self._tick_success

    def CanProcess(self) -> bool:
        return True

    def ResolveFallback(self) -> Any:
        if self.fallback is not None:
            self.fallback.ApplyBlockedSkillIDs(self.blocked_skills)
        return self.fallback


class _FakeHeroAI:
    def __init__(self, **_: Any) -> None:
        self.calls = 0
        self.blocked_skills: list[int] = []

    def ApplyBlockedSkillIDs(self, skill_ids: list[int] | None = None) -> None:
        self.blocked_skills = list(skill_ids or [])

    def ProcessSkillCasting(self):
        if False:
            yield
        self.calls += 1
        return True


class _FakeHandler:
    def __init__(self, runtime: "_Runtime", skill_id: int) -> None:
        self.runtime = runtime
        self.skill_id = skill_id
        self.skill_slot: int | None = None
        self.active_dispatch = False
        self.lifecycle_updates = 0
        self.attempts = 0
        self.dispose_reasons: list[str] = []
        self.cancel_reasons: list[str] = []

    def set_skill_slot(self, slot_index: int | None) -> None:
        self.skill_slot = slot_index

    def update_lifecycle(self, _context: Any = None) -> None:
        self.lifecycle_updates += 1

    def has_active_dispatch(self) -> bool:
        return self.active_dispatch

    def build_interrupt_proposal(self) -> object | None:
        return object()

    def try_cast_selected(self, _proposal: object) -> bool:
        self.attempts += 1
        if self.runtime.raise_handler:
            raise RuntimeError("test handler failure")
        if self.skill_id == 1336 and (
            not self.runtime.spiritual_toggle_enabled or not self.runtime.spiritual_combat_enabled
        ):
            return False
        return self.runtime.handler_results.get(self.skill_id, self.runtime.handler_cast_result)

    def try_cast(self):
        if False:
            yield
        self.attempts += 1
        if self.runtime.raise_handler:
            raise RuntimeError("test handler failure")
        if self.skill_id == 1336 and (
            not self.runtime.spiritual_toggle_enabled or not self.runtime.spiritual_combat_enabled
        ):
            return False
        return self.runtime.handler_results.get(self.skill_id, self.runtime.handler_cast_result)

    def cancel_pending(self, reason: str) -> None:
        self.cancel_reasons.append(reason)

    def dispose(self, reason: str = "disposed") -> None:
        self.dispose_reasons.append(reason)
        self.cancel_pending(reason)


class _Runtime:
    def __init__(self) -> None:
        self.bar = [0] * 8
        self.handler_cast_result = False
        self.handler_results: dict[int, bool] = {}
        self.raise_handler = False
        self.raise_factory_for: set[int] = set()
        self.handlers: list[_FakeHandler] = []
        self.coordinator_attempts = 0
        self.coordinator_handler_ids: tuple[int, ...] = ()
        self.coordinator_selected_skill_id: int | None = None
        self.spiritual_toggle_enabled = True
        self.spiritual_combat_enabled = True

    def factory(self, *, skill_id: int) -> _FakeHandler:
        if skill_id in self.raise_factory_for:
            raise RuntimeError(f"constructor failure for {skill_id}")
        handler = _FakeHandler(self, skill_id)
        self.handlers.append(handler)
        return handler


class _RealPathTimer:
    def __init__(self, _interval_ms: int) -> None:
        self.stopped = False

    def Stop(self) -> None:
        self.stopped = True


class _RealPathCachedData:
    def __init__(self) -> None:
        self.data = types.SimpleNamespace(in_aggro=True)
        self.update_count = 0
        self.combat_update_count = 0

    def Update(self) -> None:
        self.update_count += 1

    def UpdateCombat(self) -> None:
        self.combat_update_count += 1


class _RealPathHandler:
    def __init__(self, runtime: "_RealPathRuntime", skill_id: int) -> None:
        self.runtime = runtime
        self.skill_id = skill_id
        self.skill_slot: int | None = None
        self.lifecycle_updates = 0
        self.attempts = 0
        self.dispose_reasons: list[str] = []
        self.disposed = False

    def set_skill_slot(self, slot_index: int | None) -> None:
        self.skill_slot = slot_index

    def update_lifecycle(self, _context: Any = None) -> None:
        self.lifecycle_updates += 1

    def try_cast(self):
        if False:
            yield
        if self.disposed:
            return False
        self.attempts += 1
        return True

    def dispose(self, reason: str = "disposed") -> None:
        if self.disposed:
            return
        self.dispose_reasons.append(reason)
        self.disposed = True


class _RealPathRuntime:
    def __init__(self) -> None:
        self.bar = [39, 101, 102, 103, 0, 0, 0, 0]
        self.map_valid = True
        self.explorable = True
        self.in_cinematic = False
        self.player_alive = True
        self.player_knocked_down = False
        self.handlers: list[_RealPathHandler] = []

    def factory(self, *, skill_id: int) -> _RealPathHandler:
        handler = _RealPathHandler(self, skill_id)
        self.handlers.append(handler)
        return handler


class _RealPathSkillBar:
    runtime: _RealPathRuntime

    @classmethod
    def GetSkillIDBySlot(cls, slot_index: int) -> int:
        return cls.runtime.bar[slot_index - 1]


class _RealPathRegistry:
    def __init__(self, build: Any) -> None:
        self.build = build
        self.build_init_kwargs: dict[str, Any] = {}
        self.calls = 0

    def _iter_matchable_builds(self) -> list[Any]:
        self.calls += 1
        return [self.build]


class _SkillBar:
    runtime: _Runtime

    @classmethod
    def GetSkillIDBySlot(cls, slot_index: int) -> int:
        return cls.runtime.bar[slot_index - 1]


@contextmanager
def _loaded_runtime() -> Iterator[tuple[Any, _Runtime, Any]]:
    owned_prefixes = (
        "Py4GWCoreLib",
        "PySystem",
        "d1a_test.",
    )
    original = {
        name: module
        for name, module in sys.modules.items()
        if name == "PySystem" or name.startswith("Py4GWCoreLib") or name.startswith("d1a_test.")
    }
    runtime = _Runtime()
    try:
        for name in tuple(sys.modules):
            if any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in owned_prefixes):
                sys.modules.pop(name, None)

        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
        _install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
        _install_package("Py4GWCoreLib.Builds.Mesmer", ROOT / "Py4GWCoreLib" / "Builds" / "Mesmer")
        _install_package(
            "Py4GWCoreLib.Builds.Mesmer.Me_Any",
            COMPOSITION_PATH.parent,
        )
        _install_package("Py4GWCoreLib.Builds.Any", ROOT / "Py4GWCoreLib" / "Builds" / "Any")

        root_package: Any = sys.modules["Py4GWCoreLib"]
        root_package.Profession = _Profession
        root_package.ConsoleLog = lambda *_args, **_kwargs: None

        build_mgr_module = types.ModuleType("Py4GWCoreLib.BuildMgr")
        setattr(build_mgr_module, "BuildMgr", _FakeBuildMgr)
        sys.modules["Py4GWCoreLib.BuildMgr"] = build_mgr_module

        hero_ai_module = types.ModuleType("Py4GWCoreLib.Builds.Any.HeroAI")
        setattr(hero_ai_module, "HeroAI", _FakeHeroAI)
        sys.modules["Py4GWCoreLib.Builds.Any.HeroAI"] = hero_ai_module

        skill_module = types.ModuleType("Py4GWCoreLib.Skill")

        def _get_skill_id(name: str) -> int:
            return 55 if name == "Cry_of_Frustration" else 39

        setattr(skill_module, "Skill", types.SimpleNamespace(GetID=_get_skill_id))
        sys.modules["Py4GWCoreLib.Skill"] = skill_module

        skillbar_module = types.ModuleType("Py4GWCoreLib.Skillbar")
        _SkillBar.runtime = runtime
        setattr(skillbar_module, "SkillBar", _SkillBar)
        sys.modules["Py4GWCoreLib.Skillbar"] = skillbar_module

        sys.modules["PySystem"] = cast(
            Any,
            types.SimpleNamespace(
                get_tick_count64=lambda: 0,
                Console=types.SimpleNamespace(MessageType=types.SimpleNamespace(Info=0)),
            ),
        )

        _load_module("Py4GWCoreLib.Builds.Skills.SmartMesmer", SMART_MESMER_PATH)
        smart_energy = _load_module("Py4GWCoreLib.Builds.Skills.SmartEnergySurge", SMART_ENERGY_PATH)
        composition = _load_module("d1a_test.composition", COMPOSITION_PATH)
        composition.get_supported_handler_factories = lambda: {39: runtime.factory}
        composition.SmartCryController = runtime.factory

        class _FakeCoordinator:
            def try_cast(self, handlers: Any):
                if False:
                    yield
                supplied = tuple(handlers)
                runtime.coordinator_attempts += 1
                runtime.coordinator_handler_ids = tuple(handler.skill_id for handler in supplied)
                selected_skill_id = runtime.coordinator_selected_skill_id
                if selected_skill_id is None:
                    return False
                selected_handler = next(
                    (handler for handler in supplied if handler.skill_id == selected_skill_id),
                    None,
                )
                if selected_handler is None:
                    return False
                return bool(selected_handler.try_cast_selected(selected_handler.build_interrupt_proposal()))

        composition.SmartCryComplicateCoordinator = _FakeCoordinator
        yield composition, runtime, smart_energy
    finally:
        for name in tuple(sys.modules):
            if name == "PySystem" or name.startswith("Py4GWCoreLib") or name.startswith("d1a_test."):
                sys.modules.pop(name, None)
        sys.modules.update(original)


@contextmanager
def _loaded_real_heroai_runtime() -> (
    Iterator[tuple[Any, Any, _RealPathRuntime, _RealPathCachedData, _RealPathRegistry, list[Any]]]
):
    owned_prefixes = (
        "Py4GWCoreLib",
        "PySystem",
        "d1a_real.",
    )
    original = {
        name: module
        for name, module in sys.modules.items()
        if name == "PySystem" or name.startswith("Py4GWCoreLib") or name.startswith("d1a_real.")
    }
    runtime = _RealPathRuntime()
    try:
        for name in tuple(sys.modules):
            if any(name == prefix.rstrip(".") or name.startswith(prefix) for prefix in owned_prefixes):
                sys.modules.pop(name, None)

        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
        _install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
        _install_package("Py4GWCoreLib.Builds.Mesmer", ROOT / "Py4GWCoreLib" / "Builds" / "Mesmer")
        _install_package(
            "Py4GWCoreLib.Builds.Mesmer.Me_Any",
            COMPOSITION_PATH.parent,
        )
        _install_package("Py4GWCoreLib.Builds.Any", ROOT / "Py4GWCoreLib" / "Builds" / "Any")

        root_package: Any = sys.modules["Py4GWCoreLib"]
        root_package.Profession = _Profession
        root_package.ThrottledTimer = _RealPathTimer
        root_package.ConsoleLog = lambda *_args, **_kwargs: None
        root_package.Agent = types.SimpleNamespace(
            GetProfessions=lambda _agent_id: (_Profession.Mesmer, _Profession._None),
            IsAlive=lambda _agent_id: runtime.player_alive,
            IsDead=lambda _agent_id: not runtime.player_alive,
            IsKnockedDown=lambda _agent_id: runtime.player_knocked_down,
        )
        root_package.Map = types.SimpleNamespace(
            IsExplorable=lambda: runtime.explorable,
            IsInCinematic=lambda: runtime.in_cinematic,
            GetMapID=lambda: 1,
            GetRegion=lambda: (1, 0),
            GetDistrict=lambda: 1,
            GetLanguage=lambda: (0, 0),
        )
        root_package.Player = types.SimpleNamespace(GetAgentID=lambda: 1)

        def _wait(_milliseconds: int):
            if False:
                yield

        root_package.Routines = types.SimpleNamespace(
            Checks=types.SimpleNamespace(
                Map=types.SimpleNamespace(
                    MapValid=lambda: runtime.map_valid,
                    IsExplorable=lambda: runtime.explorable,
                ),
                Player=types.SimpleNamespace(CanAct=lambda: True),
            ),
            Yield=types.SimpleNamespace(wait=_wait),
        )

        sys.modules["PySystem"] = cast(
            Any,
            types.SimpleNamespace(
                get_tick_count64=lambda: 0,
                Console=types.SimpleNamespace(MessageType=types.SimpleNamespace(Info=0)),
            ),
        )

        build_mgr_module = _load_module("Py4GWCoreLib.BuildMgr", ROOT / "Py4GWCoreLib" / "BuildMgr.py")
        root_package.BuildMgr = build_mgr_module.BuildMgr

        hero_ai_module = _load_module("Py4GWCoreLib.Builds.Any.HeroAI", HERO_AI_PATH)
        _load_module("Py4GWCoreLib.Builds.Skills.SmartMesmer", SMART_MESMER_PATH)
        _load_module("Py4GWCoreLib.Builds.Skills.SmartEnergySurge", SMART_ENERGY_PATH)

        skill_module = types.ModuleType("Py4GWCoreLib.Skill")

        def _get_skill_id(name: str) -> int:
            return 55 if name == "Cry_of_Frustration" else 39

        setattr(skill_module, "Skill", types.SimpleNamespace(GetID=_get_skill_id))
        sys.modules["Py4GWCoreLib.Skill"] = skill_module

        skillbar_module = types.ModuleType("Py4GWCoreLib.Skillbar")
        _RealPathSkillBar.runtime = runtime
        setattr(skillbar_module, "SkillBar", _RealPathSkillBar)
        sys.modules["Py4GWCoreLib.Skillbar"] = skillbar_module

        composition = _load_module("d1a_real.composition", COMPOSITION_PATH)
        composition.get_supported_handler_factories = lambda: {39: runtime.factory}
        composition.SmartCryController = runtime.factory
        composition_build = composition.MyMesmer()
        composition_build._whiteboard_owner_self_clear = lambda: None
        composition_build.SetTickSuccess = lambda: setattr(
            composition_build,
            "tick_state",
            types.SimpleNamespace(name="SUCCESS"),
        )
        composition_build.SetTickFailure = lambda: setattr(
            composition_build,
            "tick_state",
            types.SimpleNamespace(name="FAILURE"),
        )

        cached_data = _RealPathCachedData()
        hero_ai = hero_ai_module.HeroAI(cached_data=cached_data)
        registry = _RealPathRegistry(composition_build)
        hero_ai._build_registry = registry
        hero_ai.SetTickSuccess = lambda: setattr(hero_ai, "tick_state", types.SimpleNamespace(name="SUCCESS"))
        hero_ai.SetTickFailure = lambda: setattr(hero_ai, "tick_state", types.SimpleNamespace(name="FAILURE"))
        activation_calls: list[Any] = []
        original_activate = composition_build.OnContractActivated

        def _record_activation(activation_data: Any = None) -> None:
            activation_calls.append(activation_data)
            original_activate(activation_data)

        composition_build.OnContractActivated = _record_activation
        yield hero_ai, composition_build, runtime, cached_data, registry, activation_calls
    finally:
        for name in tuple(sys.modules):
            if name == "PySystem" or name.startswith("Py4GWCoreLib") or name.startswith("d1a_real."):
                sys.modules.pop(name, None)
        sys.modules.update(original)


def _drain(generator: Any) -> Any:
    while True:
        try:
            next(generator)
        except StopIteration as finished:
            return finished.value


def _composition(runtime: _Runtime, composition: Any) -> Any:
    return composition.MyMesmer()


def _use_fake_priority_handlers(composition: Any, runtime: _Runtime) -> None:
    composition.SmartUnnaturalSignet = runtime.factory
    composition.SmartComplicateController = runtime.factory
    composition.SmartSpiritualPain = runtime.factory


def test_registry_contains_only_energy_surge() -> None:
    with _loaded_runtime() as (_composition_module, _runtime_value, smart_energy):
        factories = smart_energy.get_supported_handler_factories()
        assert tuple(factories) == (39,)
        assert factories[39] is smart_energy.SmartEnergySurgeHandler


def test_spiritual_pain_is_smart_owned_and_masked() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        composition_module.SmartSpiritualPain = runtime.factory
        runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 101, 102, 0, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (SPIRITUAL_PAIN_SKILL_ID,)
        assert composition.blocked_skills == [SPIRITUAL_PAIN_SKILL_ID]
        assert composition.fallback.blocked_skills == [SPIRITUAL_PAIN_SKILL_ID]
        assert composition.fallback.calls == 1


def test_spiritual_pain_constructor_failure_remains_owned_and_masked() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        composition_module.SmartSpiritualPain = runtime.factory
        runtime.raise_factory_for.add(SPIRITUAL_PAIN_SKILL_ID)
        runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 101, 102, 0, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (SPIRITUAL_PAIN_SKILL_ID,)
        assert composition.active_handlers == {}
        assert composition.blocked_skills == [SPIRITUAL_PAIN_SKILL_ID]
        assert composition.fallback.blocked_skills == [SPIRITUAL_PAIN_SKILL_ID]


def test_spiritual_pain_toggle_or_combat_off_remains_owned_and_masked() -> None:
    for disabled_attribute in ("spiritual_toggle_enabled", "spiritual_combat_enabled"):
        with _loaded_runtime() as (composition_module, runtime, _smart_energy):
            composition_module.SmartSpiritualPain = runtime.factory
            setattr(runtime, disabled_attribute, False)
            runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 101, 102, 0, 0, 0, 0, 0]
            composition = _composition(runtime, composition_module)

            _drain(composition.ProcessSkillCasting())

            assert composition.active_smart_ids == (SPIRITUAL_PAIN_SKILL_ID,)
            assert composition.blocked_skills == [SPIRITUAL_PAIN_SKILL_ID]
            assert composition.fallback.blocked_skills == [SPIRITUAL_PAIN_SKILL_ID]
            assert composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID].attempts == 1


def test_spiritual_pain_slot_movement_and_removal_refresh_ownership() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        composition_module.SmartSpiritualPain = runtime.factory
        runtime.bar[:] = [101, SPIRITUAL_PAIN_SKILL_ID, 102, 103, 104, 105, 106, 107]
        composition = _composition(runtime, composition_module)
        _drain(composition.ProcessSkillCasting())
        handler = composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID]

        assert composition.skill_slots[SPIRITUAL_PAIN_SKILL_ID] == 2
        assert handler.skill_slot == 2

        runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 101, 102, 103, 104, 105, 106, 107]
        _drain(composition.ProcessSkillCasting())
        assert composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID] is handler
        assert handler.skill_slot == 1

        runtime.bar[0] = 108
        _drain(composition.ProcessSkillCasting())
        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []
        assert handler.dispose_reasons == ["skill_removed"]


def test_unsupported_and_pvp_spiritual_pain_ids_remain_heroai_owned() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        composition_module.SmartSpiritualPain = runtime.factory
        runtime.bar[:] = [3189, 101, 102, 0, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []
        assert composition.fallback.blocked_skills == []
        assert composition.fallback.calls == 1


def test_energy_surge_precedes_spiritual_pain_when_spiritual_is_earlier_on_bar() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 39, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({SPIRITUAL_PAIN_SKILL_ID: True, 39: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID].attempts == 0


def test_energy_surge_decline_allows_spiritual_pain_afterward() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 39, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({SPIRITUAL_PAIN_SKILL_ID: True, 39: False})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID].attempts == 1


def test_valid_cry_interrupt_prevents_spiritual_pain_that_pass() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 55, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({SPIRITUAL_PAIN_SKILL_ID: True, 55: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[55].attempts == 1
        assert composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID].attempts == 0
        assert runtime.coordinator_attempts == 0


def test_residual_bar_order_runs_unnatural_before_spiritual_pain() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, SPIRITUAL_PAIN_SKILL_ID, 55, 39, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, SPIRITUAL_PAIN_SKILL_ID: True, 55: False, 39: False})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[934].attempts == 1
        assert composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID].attempts == 0


def test_residual_bar_order_runs_spiritual_pain_before_unnatural() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [SPIRITUAL_PAIN_SKILL_ID, 934, 55, 39, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, SPIRITUAL_PAIN_SKILL_ID: True, 55: False, 39: False})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[SPIRITUAL_PAIN_SKILL_ID].attempts == 1
        assert composition.active_handlers[934].attempts == 0


def test_energy_surge_only_masks_only_the_supported_skill() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [101, 39, 102, 103, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_smart_ids == (39,)
        assert composition.blocked_skills == [39]
        assert composition.fallback.blocked_skills == [39]
        assert runtime.handlers[0].attempts == 1


def test_unnatural_signet_is_smart_owned_and_masked() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 934
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (934,)
        assert composition.blocked_skills == [934]
        assert composition.fallback.blocked_skills == [934]
        assert composition.fallback.calls == 1
        assert composition.skill_slots[934] == 1


def test_unnatural_signet_constructor_failure_remains_owned_and_masked() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 934
        runtime.raise_factory_for.add(934)
        composition_module.SmartUnnaturalSignet = runtime.factory
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (934,)
        assert composition.active_handlers == {}
        assert composition.blocked_skills == [934]
        assert composition.fallback.blocked_skills == [934]
        assert composition.fallback.calls == 1


def test_unnatural_signet_slot_movement_refreshes_and_removal_disposes() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 934
        composition = _composition(runtime, composition_module)
        _drain(composition.ProcessSkillCasting())
        handler = composition.active_handlers[934]

        runtime.bar[:] = [101, 934, 102, 103, 0, 0, 0, 0]
        _drain(composition.ProcessSkillCasting())
        assert composition.active_handlers[934] is handler
        assert composition.skill_slots[934] == 2
        assert handler.skill_slot == 2

        runtime.bar[1] = 0
        _drain(composition.ProcessSkillCasting())
        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []


def test_unnatural_signet_coexists_with_existing_smart_handlers() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [934, 0, 39, 55, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (934, 39, 55)
        assert composition.blocked_skills == [934, 39, 55]
        assert composition.fallback.blocked_skills == [934, 39, 55]


def test_energy_surge_precedes_unnatural_when_unnatural_is_first_on_bar() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 39, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 39: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[934].attempts == 0


def test_energy_surge_precedes_unnatural_when_energy_surge_is_first_on_bar() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [39, 934, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 39: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[934].attempts == 0


def test_energy_surge_decline_allows_unnatural_to_run() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 39, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 39: False})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[934].attempts == 1


def test_lone_cry_precedes_unnatural_regardless_of_bar_order() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 55, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 55: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[55].attempts == 1
        assert composition.active_handlers[934].attempts == 0


def test_lone_cry_decline_continues_through_energy_surge_to_unnatural() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 55, 39, 0, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 55: False, 39: False})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[55].attempts == 1
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[934].attempts == 1


def test_lone_complicate_precedes_unnatural_regardless_of_bar_order() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 932, 0, 0, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 932: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[932].attempts == 1
        assert composition.active_handlers[934].attempts == 0


def test_lone_complicate_decline_continues_through_energy_surge_to_unnatural() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 932, 39, 0, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 932: False, 39: False})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[932].attempts == 1
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[934].attempts == 1


def test_paired_interrupt_coordinator_precedes_energy_surge_and_unnatural() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 39, 932, 55, 0, 0, 0, 0]
        runtime.coordinator_selected_skill_id = 55
        runtime.handler_results.update({934: True, 39: True, 55: True, 932: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert runtime.coordinator_attempts == 1
        assert runtime.coordinator_handler_ids == (932, 55)
        assert composition.active_handlers[55].attempts == 1
        assert composition.active_handlers[932].attempts == 0
        assert composition.active_handlers[39].attempts == 0
        assert composition.active_handlers[934].attempts == 0


def test_paired_interrupt_decline_allows_energy_surge_before_unnatural() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 39, 932, 55, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 39: True, 55: True, 932: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert runtime.coordinator_attempts == 1
        assert composition.active_handlers[55].attempts == 0
        assert composition.active_handlers[932].attempts == 0
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[934].attempts == 0


def test_paired_interrupt_and_energy_surge_decline_allow_unnatural_once() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        runtime.bar[:] = [934, 39, 932, 55, 0, 0, 0, 0]
        runtime.handler_results.update({934: True, 39: False, 55: True, 932: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert runtime.coordinator_attempts == 1
        assert composition.active_handlers[55].attempts == 0
        assert composition.active_handlers[932].attempts == 0
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[934].attempts == 1


def test_remaining_smart_handlers_keep_stable_bar_order_after_priority_tiers() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        _use_fake_priority_handlers(composition_module, runtime)
        composition_module.get_supported_handler_factories = lambda: {
            39: runtime.factory,
            700: runtime.factory,
            701: runtime.factory,
        }
        runtime.bar[:] = [701, 934, 39, 700, 0, 0, 0, 0]
        runtime.handler_results.update({701: False, 934: False, 39: False, 700: True})
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_handlers[39].attempts == 1
        assert composition.active_handlers[701].attempts == 1
        assert composition.active_handlers[934].attempts == 1
        assert composition.active_handlers[700].attempts == 1


def test_cry_only_is_smart_owned_and_masked() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [55, 101, 102, 0, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        assert composition.ScoreMatch(_Profession.Mesmer, _Profession._None, [55]) > 0
        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_smart_ids == (55,)
        assert composition.blocked_skills == [55]
        assert composition.fallback.blocked_skills == [55]
        assert composition.fallback.calls == 1


def test_passive_cry_does_not_report_tick_success_and_fallback_continues() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [55, 101, 102, 0, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.DidTickSucceed() is False
        assert composition.active_handlers[55].has_active_dispatch() is False
        assert composition.fallback.calls == 1


def test_passive_cry_does_not_preempt_energy_surge_handler() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [55, 0, 39, 101, 0, 0, 0, 0]
        runtime.handler_results[39] = True
        runtime.handler_results[55] = False
        composition = _composition(runtime, composition_module)

        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.DidTickSucceed() is True
        assert composition.active_handlers[55].attempts == 1
        assert composition.active_handlers[39].attempts == 1


def test_complicate_is_smart_owned_and_fail_closed_when_runtime_resolution_is_unavailable() -> None:
    with _loaded_runtime() as (composition_module, runtime, smart_energy):
        runtime.bar[:] = [932, 101, 102, 0, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        assert 932 not in smart_energy.get_supported_handler_factories()
        assert _drain(composition.ProcessSkillCasting()) is True
        assert composition.active_smart_ids == (932,)
        assert composition.blocked_skills == [932]
        assert composition.fallback.blocked_skills == [932]
        assert composition.fallback.calls == 1


def test_complicate_toggle_off_remains_smart_owned_and_blocked() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [932, 101, 102, 0, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)
        root: Any = sys.modules["Py4GWCoreLib"]
        setattr(root, "GLOBAL_CACHE", types.SimpleNamespace())
        setattr(root, "Player", types.SimpleNamespace(GetAccountEmail=lambda: "toggle-test"))

        _drain(composition.ProcessSkillCasting())
        handler = composition.active_handlers[932]
        handler.set_cached_data(
            types.SimpleNamespace(
                account_options=types.SimpleNamespace(Skills=[True, True, False, True, True, True, True, True])
            )
        )

        _drain(composition.ProcessSkillCasting())

        assert handler._skill_toggle_enabled(3) is False
        assert composition.active_smart_ids == (932,)
        assert composition.blocked_skills == [932]
        assert composition.fallback.blocked_skills == [932]


def test_complicate_constructor_failure_does_not_claim_runtime_ownership() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [932, 101, 102, 0, 0, 0, 0, 0]
        runtime.raise_factory_for.add(932)
        composition_module.SmartComplicateController = runtime.factory
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (932,)
        assert composition.blocked_skills == [932]
        assert composition.fallback.blocked_skills == [932]
        assert composition.fallback.calls == 1


def test_energy_surge_and_cry_mask_both_smart_skills() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [55, 0, 39, 101, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (55, 39)
        assert composition.blocked_skills == [55, 39]
        assert composition.fallback.blocked_skills == [55, 39]


def test_neither_gives_the_full_bar_to_one_heroai_fallback() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [56, 101, 102, 103, 0, 0, 0, 0]
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []
        assert composition.fallback.blocked_skills == []
        assert composition.fallback.calls == 1


def test_arbitrary_slot_resolution_and_unsupported_replacement() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [101, 102, 103, 104, 105, 106, 39, 107]
        composition = _composition(runtime, composition_module)
        _drain(composition.ProcessSkillCasting())
        handler = composition.active_handlers[39]

        assert composition.skill_slots[39] == 7
        assert handler.skill_slot == 7
        assert composition.blocked_skills == [39]

        runtime.bar[6] = 108
        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []
        assert handler.dispose_reasons == ["skill_removed"]
        assert composition.fallback.blocked_skills == []


def test_slot_reorder_preserves_the_logical_handler_and_updates_slot() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[:] = [39, 101, 102, 103, 104, 105, 106, 107]
        composition = _composition(runtime, composition_module)
        _drain(composition.ProcessSkillCasting())
        handler = composition.active_handlers[39]
        first_generation = composition.composition_generation

        runtime.bar[:] = [101, 102, 103, 39, 104, 105, 106, 107]
        _drain(composition.ProcessSkillCasting())

        assert composition.active_handlers[39] is handler
        assert handler.dispose_reasons == []
        assert handler.skill_slot == 4
        assert composition.composition_generation == first_generation + 1


def test_remove_and_readd_create_clean_handler_state() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 39
        composition = _composition(runtime, composition_module)
        _drain(composition.ProcessSkillCasting())
        old_handler = composition.active_handlers[39]

        runtime.bar[0] = 0
        _drain(composition.ProcessSkillCasting())
        assert old_handler.dispose_reasons == ["skill_removed"]
        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []

        runtime.bar[0] = 39
        _drain(composition.ProcessSkillCasting())
        new_handler = composition.active_handlers[39]
        assert new_handler is not old_handler
        assert new_handler.dispose_reasons == []
        assert composition.blocked_skills == [39]


def test_disabled_handler_remains_smart_owned_and_does_not_transfer_to_heroai() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 39
        runtime.handler_cast_result = False
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (39,)
        assert composition.blocked_skills == [39]
        assert composition.fallback.blocked_skills == [39]
        assert composition.fallback.calls == 1
        assert composition.active_handlers[39].attempts == 1


def test_handler_error_keeps_ownership_masked_for_that_cycle() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 39
        runtime.raise_handler = True
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        handler = composition.active_handlers[39]
        assert handler.cancel_reasons == ["handler_exception"]
        assert composition.blocked_skills == [39]
        assert composition.fallback.blocked_skills == [39]


def test_energy_surge_constructor_failure_keeps_ownership_masked_and_recovers() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 39
        runtime.raise_factory_for.add(39)
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (39,)
        assert composition.active_handlers == {}
        assert composition.blocked_skills == [39]
        assert composition.fallback.blocked_skills == [39]
        assert composition.fallback.calls == 1
        assert runtime.handlers == []

        runtime.raise_factory_for.clear()
        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (39,)
        assert composition.blocked_skills == [39]
        assert tuple(composition.active_handlers) == (39,)
        assert runtime.handlers[0].attempts == 1


def test_cry_constructor_failure_keeps_ownership_masked_and_recovers() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 55
        runtime.raise_factory_for.add(55)
        composition = _composition(runtime, composition_module)

        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (55,)
        assert composition.active_handlers == {}
        assert composition.blocked_skills == [55]
        assert composition.fallback.blocked_skills == [55]
        assert composition.fallback.calls == 1
        assert runtime.handlers == []

        runtime.raise_factory_for.clear()
        _drain(composition.ProcessSkillCasting())

        assert composition.active_smart_ids == (55,)
        assert composition.blocked_skills == [55]
        assert tuple(composition.active_handlers) == (55,)
        assert runtime.handlers[0].attempts == 1


def test_lifecycle_updates_before_cannot_act_gate() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 39
        composition = _composition(runtime, composition_module)
        composition.CanProcess = lambda: False

        assert _drain(composition.ProcessSkillCasting()) is False

        handler = composition.active_handlers[39]
        assert handler.lifecycle_updates == 1
        assert composition.blocked_skills == [39]
        assert composition.fallback.calls == 0


def test_contract_disposal_clears_mask_and_activation_allows_cached_reuse() -> None:
    with _loaded_runtime() as (composition_module, runtime, _smart_energy):
        runtime.bar[0] = 39
        composition = _composition(runtime, composition_module)
        _drain(composition.ProcessSkillCasting())
        old_handler = composition.active_handlers[39]

        composition.Dispose("contract_replaced")
        assert old_handler.dispose_reasons == ["contract_replaced"]
        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []

        composition.OnContractActivated()
        _drain(composition.ProcessSkillCasting())
        assert composition.active_handlers[39] is not old_handler
        assert composition.blocked_skills == [39]


def test_real_heroai_lifecycle_clears_and_reactivates_cached_composition() -> None:
    with _loaded_real_heroai_runtime() as (hero_ai, composition, runtime, _cached_data, registry, activations):
        _drain(hero_ai.ProcessCombat())

        old_handler = runtime.handlers[0]
        assert hero_ai.GetBuildContract() is composition
        assert composition.active_smart_ids == (39,)
        assert composition.blocked_skills == [39]
        assert len(activations) == 1
        assert registry.calls == 1

        runtime.map_valid = False
        _drain(hero_ai.ProcessCombat())

        assert hero_ai.GetBuildContract() is None
        assert old_handler.dispose_reasons == ["contract_cleared"]
        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []
        assert _drain(old_handler.try_cast()) is False

        _drain(hero_ai.ProcessCombat())
        assert old_handler.dispose_reasons == ["contract_cleared"]

        runtime.map_valid = True
        _drain(hero_ai.ProcessCombat())

        new_handler = runtime.handlers[1]
        assert hero_ai.GetBuildContract() is composition
        assert new_handler is not old_handler
        assert new_handler.disposed is False
        assert composition.active_smart_ids == (39,)
        assert composition.blocked_skills == [39]
        assert len(activations) == 2
        assert registry.calls == 2

        _drain(hero_ai.ProcessCombat())

        assert runtime.handlers == [old_handler, new_handler]
        assert new_handler.dispose_reasons == []
        assert len(activations) == 2
        assert registry.calls == 2

        runtime.explorable = False
        _drain(hero_ai.ProcessCombat())

        assert hero_ai.GetBuildContract() is None
        assert new_handler.dispose_reasons == ["contract_cleared"]
        assert composition.active_smart_ids == ()
        assert composition.blocked_skills == []


def _assert_real_heroai_transient_gate_preserves_contract(
    gate_name: str,
    transient_value: bool,
) -> None:
    with _loaded_real_heroai_runtime() as (hero_ai, composition, runtime, _cached_data, registry, activations):
        _drain(hero_ai.ProcessCombat())

        contract = hero_ai.GetBuildContract()
        handler = runtime.handlers[0]
        attempts_before_gate = handler.attempts
        assert contract is composition
        assert composition.active_handlers[39] is handler
        assert composition.blocked_skills == [39]
        assert len(activations) == 1
        assert registry.calls == 1

        setattr(runtime, gate_name, transient_value)
        _drain(hero_ai.ProcessCombat())

        assert hero_ai.GetBuildContract() is contract
        assert composition.active_handlers[39] is handler
        assert composition.active_smart_ids == (39,)
        assert composition.blocked_skills == [39]
        assert handler.disposed is False
        assert handler.dispose_reasons == []
        assert len(activations) == 1
        assert registry.calls == 1
        assert runtime.handlers == [handler]

        setattr(runtime, gate_name, not transient_value)
        _drain(hero_ai.ProcessCombat())

        assert hero_ai.GetBuildContract() is contract
        assert composition.active_handlers[39] is handler
        assert composition.blocked_skills == [39]
        assert handler.disposed is False
        assert handler.dispose_reasons == []
        assert handler.attempts == attempts_before_gate + 1
        assert len(activations) == 1
        assert registry.calls == 1
        assert runtime.handlers == [handler]


def test_real_heroai_lifecycle_preserves_contract_through_knockdown() -> None:
    _assert_real_heroai_transient_gate_preserves_contract("player_knocked_down", True)


def test_real_heroai_lifecycle_preserves_contract_through_cinematic() -> None:
    _assert_real_heroai_transient_gate_preserves_contract("in_cinematic", True)


def test_real_heroai_lifecycle_preserves_contract_through_player_death() -> None:
    _assert_real_heroai_transient_gate_preserves_contract("player_alive", False)
