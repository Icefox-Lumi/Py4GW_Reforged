from __future__ import annotations

import ast
import copy
import ctypes
import importlib.util
import os
import random
import re
import sys
import time
import traceback
import types
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Literal
from typing import Optional
from typing import cast as type_cast


import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXPECTED_SUPPORTED_SKILLS: tuple[tuple[str, str, int], ...] = (
    ("energy_surge", "Energy_Surge", 39),
    ("panic", "Panic", 52),
    ("ineptitude", "Ineptitude", 47),
    ("heroic_refrain", "Heroic_Refrain", 3431),
    ("blood_is_power", "Blood_is_Power", 119),
    ("soul_twisting", "Soul_Twisting", 1240),
    ("shelter", "Shelter", 982),
    ("union", "Union", 911),
    ("healing_burst", "Healing_Burst", 1118),
    ("together_as_one", "Together_as_one", 3427),
)
_NATIVE_SKILL_IDS = {native_name: skill_id for _, native_name, skill_id in _EXPECTED_SUPPORTED_SKILLS}
_PREVIOUS_DISPLAY_SKILL_NAMES: tuple[tuple[str, str], ...] = (
    ("energy_surge", "Energy Surge"),
    ("panic", "Panic"),
    ("ineptitude", "Ineptitude"),
    ("heroic_refrain", "Heroic Refrain"),
    ("blood_is_power", "Blood is Power"),
    ("soul_twisting", "Soul Twisting"),
    ("shelter", "Shelter"),
    ("union", "Union"),
    ("healing_burst", "Healing Burst"),
    ("together_as_one", "Together as One"),
)
_SUPPORTED_ROLES = (
    "ENERGY_SURGE",
    "PANIC",
    "INEPTITUDE",
    "HEROIC_REFRAIN",
    "BIP",
    "SOUL_TWISTING",
    "HEALING_BURST",
    "TAO",
)


def _native_skill_id_by_name(name: str) -> int:
    return _NATIVE_SKILL_IDS.get(name, 0)


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _install_package(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    module = _install_module(monkeypatch, name)
    module.__path__ = []
    return module


def _load_source(monkeypatch: pytest.MonkeyPatch, name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load production source at {path}")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def _load_production_map_loading_api(monkeypatch: pytest.MonkeyPatch, gw_context: Any) -> type[Any]:
    source_path = _REPO_ROOT / "Py4GWCoreLib" / "Map.py"
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    production_map = next(node for node in source_tree.body if isinstance(node, ast.ClassDef) and node.name == "Map")
    method_names = {
        "IsMapDataLoaded",
        "GetInstanceType",
        "IsMapLoading",
        "IsMapLoadingObserved",
        "GetLoadingObservation",
    }
    methods = [node for node in production_map.body if isinstance(node, ast.FunctionDef) and node.name in method_names]
    if {method.name for method in methods} != method_names:
        raise AssertionError("production Map loading methods changed; update this regression harness")
    # Keep the production bodies intact while removing frame caching between simulated frames.
    for method in methods:
        method.decorator_list = [
            decorator
            for decorator in method.decorator_list
            if isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
        ]

    map_class = ast.ClassDef(
        name="Map",
        bases=[],
        keywords=[],
        body=[],
        decorator_list=[],
    )
    map_class.body.extend(methods)
    module = types.ModuleType("test_production_map_loading_api")
    map_enums = _load_source(
        monkeypatch,
        "Py4GWCoreLib.enums_src.Map_enums",
        _REPO_ROOT / "Py4GWCoreLib" / "enums_src" / "Map_enums.py",
    )
    module.__dict__.update(
        GWContext=gw_context, InstanceType=map_enums.InstanceType, dataclass=dataclass, monotonic=time.monotonic
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    observation_class = next(
        node for node in source_tree.body if isinstance(node, ast.ClassDef) and node.name == "LoadingObservation"
    )
    executable = ast.fix_missing_locations(ast.Module(body=[observation_class, map_class], type_ignores=[]))
    exec(compile(executable, str(source_path), "exec"), module.__dict__)
    return module.Map


def _load_global_cache_owner(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    corelib = sys.modules["Py4GWCoreLib"]
    corelib.__dict__["ThrottledTimer"] = type("ThrottledTimer", (), {})
    action_queue_module = _install_module(monkeypatch, "Py4GWCoreLib.Py4GWcorelib")
    action_queue_module.__dict__["ActionQueueManager"] = type("ActionQueueManager", (), {})

    dependencies = {
        "CameraCache": ("CameraCache",),
        "EffectCache": ("EffectsCache",),
        "InventoryCache": ("InventoryCache",),
        "ItemCache": ("ItemArray", "ItemCache", "RawItemCache"),
        "MerchantCache": ("TradingCache",),
        "PartyCache": ("PartyCache",),
        "QuestCache": ("QuestCache",),
        "SharedMemory": ("Py4GWSharedMemoryManager",),
        "SkillbarCache": ("SkillbarCache",),
        "SkillCache": ("SkillCache",),
    }
    for module_name, class_names in dependencies.items():
        dependency_module = _install_module(monkeypatch, f"Py4GWCoreLib.GlobalCache.{module_name}")
        for class_name in class_names:
            dependency_module.__dict__[class_name] = type(class_name, (), {})

    _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "Stage3EvidenceProbeDiagnostics.py",
    )

    module = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.GlobalCache",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "GlobalCache.py",
    )
    return module.GlobalCache


def _load_stage3_evidence_probe(monkeypatch: pytest.MonkeyPatch, global_cache: Any) -> types.ModuleType:
    corelib = sys.modules["Py4GWCoreLib"]
    corelib.__dict__["GLOBAL_CACHE"] = global_cache
    return _load_source(
        monkeypatch,
        "test_stage3_evidence_probe",
        _REPO_ROOT / "Widgets" / "Coding" / "Debug" / "Py4GW" / "Stage 3 Evidence Probe.py",
    )


def _load_widget_class_for_stage3_tests(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    previous_system = sys.modules.get("PySystem")
    current_console = getattr(previous_system, "Console", None)
    console_logs = getattr(previous_system, "stage3_console_logs", [])
    py_system = _install_module(monkeypatch, "PySystem")

    def _log_console(sender: str, message: str, message_type: Any) -> None:
        console_logs.append((sender, message, message_type))
        print(message)

    py_system.Console = types.SimpleNamespace(
        get_projects_path=lambda: str(_REPO_ROOT),
        get_gw_window_handle=getattr(current_console, "get_gw_window_handle", lambda: 0),
        Log=_log_console,
        MessageType=types.SimpleNamespace(Error=1, Info=2, Warning=3),
    )
    py_system.stage3_console_logs = console_logs
    for module_name in ("PyPing", "PyGameThread", "PyDXOverlay", "PyAgentEvents"):
        _install_module(monkeypatch, module_name)

    py_callback = _install_module(monkeypatch, "PyCallback")

    class _CallbackApi:
        Phase = types.SimpleNamespace(Update=1)
        Context = types.SimpleNamespace(Update=1, Draw=2, Main=3)
        _next_id = 0
        callbacks: dict[int, Callable[[], Any]] = {}

        @classmethod
        def Register(
            cls,
            _name: str,
            _phase: Any,
            callback: Callable[[], Any],
            **_kwargs: Any,
        ) -> int:
            cls._next_id += 1
            cls.callbacks[cls._next_id] = callback
            return cls._next_id

        @staticmethod
        def PauseById(_callback_id: int) -> None:
            return None

        @staticmethod
        def ResumeById(_callback_id: int) -> None:
            return None

    py_callback.PyCallback = _CallbackApi
    py_callback.Phase = _CallbackApi.Phase
    py_callback.Context = _CallbackApi.Context
    profiling = types.SimpleNamespace(enabled=False, register=lambda _name: None)
    source_path = _REPO_ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "WidgetManager.py"
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    widget_node = next(node for node in source_tree.body if isinstance(node, ast.ClassDef) and node.name == "Widget")
    namespace = {
        "__name__": "test_widget_manager_widget_class",
        "dataclass": dataclass,
        "field": field,
        "Callable": Callable,
        "Iterable": Iterable,
        "Literal": Literal,
        "Optional": Optional,
        "ModuleType": types.ModuleType,
        "importlib": importlib,
        "os": os,
        "sys": sys,
        "traceback": traceback,
        "PySystem": py_system,
        "PyCallback": py_callback,
        "base_path": str(_REPO_ROOT),
        "_bump_widgets_revision": lambda: None,
        "_get_profiling": lambda: profiling,
    }
    executable = ast.fix_missing_locations(ast.Module(body=[widget_node], type_ignores=[]))
    exec(compile(executable, str(source_path), "exec", dont_inherit=True), namespace)
    return namespace["Widget"]


def _instantiate_stage3_browser_widget(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, str]:
    widget_path = Path("Widgets/Coding/Debug/Py4GW/Stage 3 Evidence Probe.py")
    assert (_REPO_ROOT / widget_path.parent / ".widget").is_file()
    widget_type = _load_widget_class_for_stage3_tests(monkeypatch)
    widget = widget_type(
        folder_script_name="Coding/Debug/Py4GW/Stage 3 Evidence Probe.py",
        plain_name="Stage 3 Evidence Probe",
        widget_path="Coding/Debug/Py4GW",
        script_path=str(_REPO_ROOT / widget_path),
    )
    if widget.module is None:
        raise AssertionError("WidgetManager did not load the Stage 3 probe module")
    return widget, widget.module.__name__


def _run_stage3_browser_update(widget: Any) -> None:
    callback_id = int(widget.update_callback_id)
    callbacks = sys.modules["PyCallback"].PyCallback.callbacks
    callback = callbacks.get(callback_id)
    if callback is None:
        raise AssertionError("WidgetManager did not register the probe update callback")
    callback()


def _load_environment_upkeeper(
    monkeypatch: pytest.MonkeyPatch, runtime: _Runtime, global_cache: Any
) -> tuple[types.ModuleType, type[Any]]:
    corelib = sys.modules["Py4GWCoreLib"]

    class _ActionQueueManager:
        def ResetAllQueues(self) -> None:
            pass

        def ResetNonTransitionQueues(self) -> None:
            pass

        def ProcessQueue(self, _queue_name: str) -> None:
            pass

    class _Overlay:
        def __init__(self) -> None:
            pass

        def UpkeepTextures(self) -> None:
            pass

    class _ThrottledTimer:
        def __init__(self, _interval_ms: int) -> None:
            pass

        def IsExpired(self) -> bool:
            return False

        def Reset(self) -> None:
            pass

    class _LootFilters:
        map_change_calls = 0

        def __init__(self) -> None:
            pass

        def on_map_change(self) -> None:
            type(self).map_change_calls += 1

    corelib.__dict__.update(
        GLOBAL_CACHE=global_cache,
        ActionQueueManager=_ActionQueueManager,
        Overlay=_Overlay,
        ThrottledTimer=_ThrottledTimer,
        Routines=types.SimpleNamespace(
            Checks=types.SimpleNamespace(
                Map=types.SimpleNamespace(
                    MapValid=lambda: (
                        runtime.ready
                        and not runtime.cinematic
                        and runtime.party_loaded
                        and corelib.Map.IsMapDataLoaded()
                        and not corelib.Map.IsMapLoading()
                    ),
                )
            )
        ),
    )

    _install_module(monkeypatch, "PyImGui")
    hotkey_module = _install_module(monkeypatch, "Py4GWCoreLib.HotkeyManager")
    hotkey_module.__dict__["HOTKEY_MANAGER"] = types.SimpleNamespace(update=lambda: None)
    _install_package(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src")
    _install_package(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.system_settings")
    loot_module = _install_module(monkeypatch, "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters")
    loot_module.__dict__["LootFilters"] = _LootFilters

    module = _load_source(
        monkeypatch,
        "test_environment_upkeeper",
        _REPO_ROOT / "Widgets" / "System" / "Environment Upkeeper.py",
    )
    return module, _LootFilters


class _Runtime:
    publication_mutator: Callable[[], None] | None
    publication_now: int
    publication_result: Any
    witness_skillbars: dict[tuple[int, int], tuple[int, ...]] | None
    local_uuid: tuple[int, int, int, int]

    def __init__(self) -> None:
        self.ready = True
        self.frame_now: int | None = None
        self.uncached_now: int | None = None
        self.instance_type_override: int | None = None
        self.missing_map_contexts: set[str] = set()
        self.cinematic = False
        self.pvp = False
        self.outpost = True
        self.explorable = False
        self.map_id = 1
        self.party_loaded = True
        self.party_size_override: int | None = None
        self.login_number = 11
        self.agent_id = 1001
        self.party_id = 5
        self.region_id = 0
        self.district_id = 0
        self.language_id = 0
        self.local_uuid = (111, 0, 0, 0)
        self.local_hwnd = 50
        self.account_email = "mesmer@example.test"
        self.character_name = "Mesmer A"
        self.player_names: dict[int, str] = {}
        self.players: list[Any] = []
        self.heroes: list[Any] = []
        self.henchmen: list[Any] = []
        self.professions: dict[int, int] = {}
        self.secondaries: dict[int, int] = {}
        self.bars: dict[int, tuple[int, ...]] = {}
        self.skill_types: dict[int, int] = {}
        self.skill_type_errors: set[int] = set()
        self.attack_skill_id = 999
        self.local_agent_by_login = {self.login_number: self.agent_id}
        self.agent_type_by_id: dict[int, bool] = {}
        self.unavailable_agents: set[int] = set()
        self.original_hero_builds: dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, int]]] = {}
        self.living_login_override: dict[int, int] = {}
        self.hero_agent_by_position_override: dict[int, int] = {}
        self.hero_agent_positions: list[int] = []
        self.hero_skillbar_positions: list[int] = []
        self.skillbar_agent_id: int | None = None
        self.profession: Any = None
        self.skill_type: Any = None
        self.players = [types.SimpleNamespace(login_number=self.login_number, is_connected=True)]
        self.professions[self.agent_id] = 0
        self.bars[self.agent_id] = tuple(900 + index for index in range(8))

    @property
    def party_size(self) -> int:
        if self.party_size_override is not None:
            return self.party_size_override
        return len(self.players) + len(self.heroes) + len(self.henchmen)

    @property
    def instance_type(self) -> int:
        if self.instance_type_override is not None:
            return self.instance_type_override
        return 0 if self.outpost else 1

    def agent_id_at_party_position(self, party_position: int) -> int:
        if party_position == 0:
            return self.agent_id
        hero_roster_index = party_position - 1
        if 0 <= hero_roster_index < len(self.heroes):
            return int(self.heroes[hero_roster_index].agent_id)
        return 0

    def skill_ids_at_party_position(self, party_position: int) -> tuple[int, ...]:
        agent_id = self.agent_id_at_party_position(party_position)
        return self.bars.get(agent_id, ())

    def set_identity(self, login_number: int, account_email: str, character_name: str) -> None:
        old_login = self.login_number
        self.login_number = login_number
        self.account_email = account_email
        self.character_name = character_name
        self.players = [
            types.SimpleNamespace(
                login_number=login_number if int(player.login_number) == old_login else int(player.login_number),
                is_connected=bool(getattr(player, "is_connected", True)),
            )
            for player in self.players
        ]
        self.local_agent_by_login.pop(old_login, None)
        self.local_agent_by_login[login_number] = self.agent_id


@pytest.fixture
def cleansing_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[_Runtime, types.ModuleType]:
    runtime = _Runtime()
    corelib = _install_package(monkeypatch, "Py4GWCoreLib")
    _install_package(monkeypatch, "Py4GWCoreLib.enums_src")
    _load_source(
        monkeypatch,
        "Py4GWCoreLib.enums_src.GameData_enums",
        _REPO_ROOT / "Py4GWCoreLib" / "enums_src" / "GameData_enums.py",
    )
    _install_package(monkeypatch, "Py4GWCoreLib.GlobalCache")

    map_api = types.SimpleNamespace(
        IsMapReady=lambda: runtime.ready,
        IsInCinematic=lambda: runtime.cinematic,
        IsPVP=lambda: runtime.pvp,
        IsOutpost=lambda: runtime.outpost,
        IsExplorable=lambda: runtime.explorable,
        GetMapID=lambda: runtime.map_id,
        GetRegion=lambda: (runtime.region_id, "Test"),
        GetDistrict=lambda: runtime.district_id,
        GetLanguage=lambda: (runtime.language_id, "Test"),
    )
    player_api = types.SimpleNamespace(
        IsPlayerLoaded=lambda: runtime.ready,
        GetAgentID=lambda: runtime.agent_id,
        GetLoginNumber=lambda: runtime.login_number,
        GetAccountEmail=lambda: runtime.account_email,
        GetName=lambda: runtime.character_name,
        GetPlayerUUID=lambda: runtime.local_uuid,
        _sanitize_account_email_or_fallback=lambda email: str(email or runtime.account_email),
    )

    def get_agent_by_id(agent_id: int) -> Any:
        if agent_id in runtime.unavailable_agents:
            return None
        known = (
            agent_id == runtime.agent_id
            or agent_id in runtime.local_agent_by_login.values()
            or any(int(hero.agent_id) == agent_id for hero in runtime.heroes)
            or agent_id in runtime.professions
        )
        if not known:
            return None
        login_number = runtime.living_login_override.get(
            agent_id,
            next(
                (login for login, current_agent in runtime.local_agent_by_login.items() if current_agent == agent_id), 0
            ),
        )
        living = types.SimpleNamespace(
            login_number=login_number,
            primary=runtime.professions.get(agent_id, 0),
            secondary=runtime.secondaries.get(agent_id, 0),
        )
        return types.SimpleNamespace(
            agent_id=agent_id,
            is_living_type=runtime.agent_type_by_id.get(agent_id, True),
            GetAsAgentLiving=lambda: living,
        )

    def get_professions(agent_id: int, *, _stage3_observation: dict[str, Any] | None = None) -> tuple[int, int]:
        if agent_id in runtime.unavailable_agents:
            if _stage3_observation is not None:
                _stage3_observation.update(agent_found=False, primary=None, professions=None, gate="AGENT")
            return 0, 0
        primary = runtime.professions.get(agent_id, 0)
        if _stage3_observation is not None:
            _stage3_observation.update(primary=primary, professions=True, gate="ZERO" if primary == 0 else "OK")
        return primary, runtime.secondaries.get(agent_id, 0)

    agent_api = types.SimpleNamespace(
        GetProfessions=get_professions,
        GetAgentByID=get_agent_by_id,
        GetNameByID=lambda agent_id: (
            runtime.character_name
            if agent_id == runtime.agent_id
            else next(
                (
                    runtime.player_names.get(login, "")
                    for login, mapped in runtime.local_agent_by_login.items()
                    if mapped == agent_id
                ),
                "",
            )
        ),
    )

    def get_hero_agent_id_by_party_position(party_position: int) -> int:
        runtime.hero_agent_positions.append(party_position)
        if party_position in runtime.hero_agent_by_position_override:
            return runtime.hero_agent_by_position_override[party_position]
        return runtime.agent_id_at_party_position(party_position)

    party_api = types.SimpleNamespace(
        IsPartyLoaded=lambda: runtime.party_loaded,
        GetPlayers=lambda: tuple(runtime.players),
        GetHeroes=lambda: tuple(runtime.heroes),
        GetHenchmen=lambda: tuple(runtime.henchmen),
        GetPartySize=lambda: runtime.party_size,
        GetPartyID=lambda: runtime.party_id,
        Players=types.SimpleNamespace(
            GetAgentIDByLoginNumber=lambda login: runtime.local_agent_by_login.get(login, 0),
            GetPlayerNameByLoginNumber=lambda login: runtime.player_names.get(login, ""),
        ),
        Heroes=types.SimpleNamespace(
            GetHeroAgentIDByPartyPosition=get_hero_agent_id_by_party_position,
        ),
    )

    def get_skill_type(skill_id: int) -> tuple[int, str]:
        if skill_id in runtime.skill_type_errors:
            raise RuntimeError("skill type read failed")
        return runtime.skill_types.get(skill_id, 0), ""

    skill_api = types.SimpleNamespace(
        GetID=_native_skill_id_by_name,
        GetType=get_skill_type,
    )

    class _FakePyParty:
        def GetContext(self) -> None:
            return None

        @property
        def party_id(self) -> int:
            return runtime.party_id

        @property
        def party_size(self) -> int:
            return runtime.party_size

        @property
        def is_party_loaded(self) -> bool:
            return runtime.party_loaded

        @property
        def players(self) -> tuple[Any, ...]:
            return tuple(runtime.players)

        @property
        def heroes(self) -> tuple[Any, ...]:
            return tuple(runtime.heroes)

        @property
        def henchmen(self) -> tuple[Any, ...]:
            return tuple(runtime.henchmen)

        def GetAgentIDByLoginNumber(self, login_number: int) -> int:
            return int(runtime.local_agent_by_login.get(login_number, 0))

        def GetPlayerNameByLoginNumber(self, login_number: int) -> str:
            return runtime.player_names.get(login_number, "")

    py_party = _install_module(monkeypatch, "PyParty")
    py_party.__dict__["PyParty"] = _FakePyParty
    py_party.__dict__["get_is_party_loaded"] = lambda: runtime.party_loaded
    py_system = _install_module(monkeypatch, "PySystem")
    stage3_console_logs: list[tuple[str, str, Any]] = []

    def _log_console(sender: str, message: str, message_type: Any) -> None:
        stage3_console_logs.append((sender, message, message_type))
        print(message)

    py_system.__dict__["Console"] = types.SimpleNamespace(
        get_gw_window_handle=lambda: runtime.local_hwnd,
        Log=_log_console,
        MessageType=types.SimpleNamespace(Error=1, Info=2, Warning=3),
    )
    py_system.__dict__["stage3_console_logs"] = stage3_console_logs

    _install_package(monkeypatch, "Py4GWCoreLib.GlobalCache.shared_memory_src")
    publication_module = _install_module(monkeypatch, "Py4GWCoreLib.GlobalCache.shared_memory_src.AccountPublication")
    publication_module.__dict__["BuildWitnessKind"] = Enum("BuildWitnessKind", {"OUTPOST_BUILD_WITNESS": 1})
    intent_sync = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "shared_memory_src" / "IntentSync.py",
    )

    def make_context(factory: Callable[[], Any], context_name: str | None = None) -> Any:
        def get_context() -> Any:
            if context_name in runtime.missing_map_contexts:
                return None
            return factory()

        return types.SimpleNamespace(
            GetContext=get_context,
            IsValid=lambda: get_context() is not None,
        )

    context_module = _install_module(monkeypatch, "Py4GWCoreLib.Context")
    gw_context = types.SimpleNamespace(
        Map=make_context(lambda: types.SimpleNamespace(), "map"),
        Char=make_context(
            lambda: types.SimpleNamespace(
                current_map_id=runtime.map_id,
                district_number=runtime.district_id,
                language=runtime.language_id,
                player_name_str=runtime.character_name,
                player_email_str=runtime.account_email,
                player_uuid=runtime.local_uuid,
                observe_map_id=runtime.map_id,
            ),
            "char",
        ),
        World=make_context(
            lambda: types.SimpleNamespace(player_controlled_character=types.SimpleNamespace(agent_id=runtime.agent_id)),
            "world",
        ),
        InstanceInfo=make_context(
            lambda: types.SimpleNamespace(
                instance_type=runtime.instance_type,
                current_map_info=types.SimpleNamespace(is_pvp=runtime.pvp),
            ),
            "instance_info",
        ),
        ServerRegion=make_context(lambda: types.SimpleNamespace(region_id=runtime.region_id)),
        Cinematic=make_context(lambda: types.SimpleNamespace(h0004=int(runtime.cinematic))),
    )
    context_module.__dict__["GWContext"] = gw_context
    production_map_api = _load_production_map_loading_api(monkeypatch, gw_context)
    map_api.IsMapDataLoaded = production_map_api.IsMapDataLoaded
    map_api.GetInstanceType = production_map_api.GetInstanceType
    map_api.IsMapLoading = production_map_api.IsMapLoading
    map_api.IsMapLoadingObserved = production_map_api.IsMapLoadingObserved
    map_api.GetLoadingObservation = production_map_api.GetLoadingObservation

    class _FakeSharedMemory:
        def GetNativeAccountSnapshotV3(self) -> Any:
            if runtime.publication_mutator is not None:
                runtime.publication_mutator()
            return runtime.publication_result

        def GetBaseTimestamp(self) -> int:
            return runtime.publication_now if runtime.frame_now is None else runtime.frame_now

    runtime.publication_mutator = None
    runtime.publication_now = 101
    monkeypatch.setattr(
        intent_sync,
        "get_uncached_tick_count64",
        lambda: runtime.publication_now if runtime.uncached_now is None else runtime.uncached_now,
    )
    runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value="unavailable"), snapshot=None)
    corelib.__dict__.update(
        Agent=agent_api,
        GLOBAL_CACHE=types.SimpleNamespace(Party=party_api, Skill=skill_api, ShMem=_FakeSharedMemory()),
        Map=map_api,
        Player=player_api,
    )

    class _FakeSkillbar:
        def __init__(self) -> None:
            self.agent_id = 0
            self.skills: list[Any] = []

        @staticmethod
        def _slots(skill_ids: tuple[int, ...]) -> list[Any]:
            return [types.SimpleNamespace(id=types.SimpleNamespace(id=skill_id)) for skill_id in skill_ids]

        def GetContext(self) -> None:
            self.agent_id = runtime.agent_id if runtime.skillbar_agent_id is None else runtime.skillbar_agent_id
            self.skills = self._slots(runtime.bars.get(runtime.agent_id, ()))

        def GetHeroSkillbar(self, hero_position: int) -> list[Any]:
            runtime.hero_skillbar_positions.append(hero_position)
            return self._slots(runtime.skill_ids_at_party_position(hero_position))

    skillbar_module = _install_module(monkeypatch, "PySkillbar")
    skillbar_module.__dict__["Skillbar"] = _FakeSkillbar

    module = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.CleansingContext",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "CleansingContext.py",
    )
    runtime.profession = module.Profession
    runtime.skill_type = sys.modules["Py4GWCoreLib.enums_src.GameData_enums"].SkillType
    runtime.professions[runtime.agent_id] = int(module.Profession.Mesmer)
    return runtime, module


def _skill_ids(_runtime: _Runtime, module: types.ModuleType) -> Any:
    return module.resolve_supported_skill_ids(_native_skill_id_by_name)


def _add_remote_player(
    runtime: _Runtime,
    module: types.ModuleType,
    *,
    login_number: int = 22,
    agent_id: int = 2001,
    role: Any = None,
    connected: bool = True,
    name: str = "Remote Player",
) -> Any:
    player = types.SimpleNamespace(login_number=login_number, is_connected=connected)
    runtime.players.append(player)
    runtime.local_agent_by_login[login_number] = agent_id
    runtime.player_names[login_number] = name
    runtime.professions[agent_id] = _profession_for(module, role) if role is not None else int(module.Profession.Mesmer)
    if role is None:
        runtime.bars[agent_id] = tuple(7000 + index for index in range(8))
    else:
        runtime.bars[agent_id] = _role_bar(runtime, module, role, utility_seed=7000 + login_number * 10)
        if role is module.CleansingRole.TAO:
            runtime.skill_types[runtime.attack_skill_id] = int(runtime.skill_type.Attack)
    return player


def _account_evidence(
    *,
    slot: int,
    email: str,
    name: str,
    hwnd: int,
    entity_type: int,
    local_index: int,
    is_account: bool,
    is_hero: bool,
    agent_id: int,
    owner_agent_id: int,
    hero_id: int,
    login_number: int,
    character_uuid: tuple[int, int, int, int],
    professions: tuple[int, int],
    map_signature: tuple[int, int, int, int],
    party_id: int,
    skill_ids: tuple[int, ...],
    published_tick: int,
) -> Any:
    account = types.SimpleNamespace(
        SlotNumber=slot,
        AccountEmail=email,
        Key=types.SimpleNamespace(HWND=hwnd, EntityType=entity_type, LocalIndex=local_index),
        IsSlotActive=True,
        IsAccount=is_account,
        IsHero=is_hero,
        IsPet=False,
        IsNPC=False,
        LastUpdated=published_tick,
        AgentData=types.SimpleNamespace(
            CharacterName=name,
            AgentID=agent_id,
            OwnerAgentID=owner_agent_id,
            HeroID=hero_id,
            LoginNumber=login_number,
            UUID=character_uuid,
            Profession=professions,
            Map=types.SimpleNamespace(
                MapID=map_signature[0],
                Region=map_signature[1],
                District=map_signature[2],
                Language=map_signature[3],
            ),
            Skillbar=types.SimpleNamespace(Skills=tuple(types.SimpleNamespace(Id=skill_id) for skill_id in skill_ids)),
        ),
        AgentPartyData=types.SimpleNamespace(PartyID=party_id),
    )
    return types.SimpleNamespace(slot_index=slot, GetAccountData=lambda: account)


def _remote_publication(
    runtime: _Runtime,
    module: types.ModuleType,
    *,
    age_ms: int = 1,
    owner_skillbars: dict[int, tuple[int, ...]] | None = None,
    witness_skillbars: dict[tuple[int, int], tuple[int, ...]] | None = None,
    witness_professions: dict[tuple[int, int], tuple[int, int]] | None = None,
    include_local: bool = False,
    omit_outpost_children: bool = False,
) -> Any:
    current_tick = int(runtime.publication_now)
    published_tick = (current_tick - age_ms) & 0xFFFFFFFF
    map_signature = (runtime.map_id, runtime.region_id, runtime.district_id, runtime.language_id)
    owner_skillbars = owner_skillbars or {}
    witness_skillbars = witness_skillbars or {}
    witness_professions = witness_professions or {}
    cohorts = []
    for owner_index, player in enumerate(
        [member for member in runtime.players if int(member.login_number) != runtime.login_number]
        + (
            [member for member in runtime.players if int(member.login_number) == runtime.login_number]
            if include_local
            else []
        )
    ):
        login_number = int(player.login_number)
        agent_id = int(runtime.local_agent_by_login.get(login_number, 0))
        profession = int(runtime.professions.get(agent_id, 0))
        owner_professions = (profession, 0)
        owner_skills = owner_skillbars.get(login_number, runtime.bars.get(agent_id, tuple(7000 + i for i in range(8))))
        email = f"remote{login_number}@example.test"
        hwnd = 1000 + login_number
        uuid = (login_number * 100, login_number, 0, 0)
        incarnation = bytes((login_number % 255 + 1,)) + bytes(15)
        if login_number == runtime.login_number:
            email, hwnd, uuid = runtime.account_email, runtime.local_hwnd, runtime.local_uuid
        owner = _account_evidence(
            slot=10 + owner_index,
            email=email,
            name=runtime.player_names.get(login_number, ""),
            hwnd=hwnd,
            entity_type=0,
            local_index=0,
            is_account=True,
            is_hero=False,
            agent_id=agent_id,
            owner_agent_id=0,
            hero_id=0,
            login_number=login_number,
            character_uuid=uuid,
            professions=owner_professions,
            map_signature=map_signature,
            party_id=runtime.party_id,
            skill_ids=owner_skills,
            published_tick=published_tick,
        )
        children = []
        witnesses = []
        for child_index, hero in enumerate(
            hero for hero in runtime.heroes if int(hero.owner_player_id) == login_number
        ):
            hero_id = int(hero.hero_id)
            hero_agent_id = int(hero.agent_id)
            hero_profession = int(runtime.professions.get(hero_agent_id, 0))
            hero_professions = (hero_profession, 0)
            hero_skills = runtime.bars.get(hero_agent_id, tuple(7100 + i for i in range(8)))
            children.append(
                _account_evidence(
                    slot=30 + owner_index * 10 + child_index,
                    email=email,
                    name=f"Hero {hero_id}",
                    hwnd=hwnd,
                    entity_type=1,
                    local_index=hero_id,
                    is_account=False,
                    is_hero=True,
                    agent_id=hero_agent_id,
                    owner_agent_id=agent_id,
                    hero_id=hero_id,
                    login_number=0,
                    character_uuid=(0, 0, 0, 0),
                    professions=hero_professions,
                    map_signature=map_signature,
                    party_id=runtime.party_id,
                    skill_ids=hero_skills,
                    published_tick=published_tick,
                )
            )
            key = (login_number, hero_id)
            if runtime.outpost:
                runtime.original_hero_builds[key] = (
                    witness_skillbars.get(key, hero_skills),
                    witness_professions.get(key, hero_professions),
                )
            if key not in runtime.original_hero_builds:
                continue
            original_skills, original_professions = runtime.original_hero_builds[key]
            witness_skills = witness_skillbars.get(key, original_skills)
            witness_profession = witness_professions.get(key, original_professions)
            witnesses.append(
                types.SimpleNamespace(
                    kind=types.SimpleNamespace(value=1),
                    hero_id=hero_id,
                    primary=witness_profession[0],
                    secondary=witness_profession[1],
                    skills=witness_skills,
                    observed_at_tick64=1,
                    revision=1,
                    outpost_epoch=1,
                )
            )
        cohorts.append(
            types.SimpleNamespace(
                owner=owner,
                children=() if runtime.outpost and omit_outpost_children else tuple(children),
                incarnation=incarnation,
                character_uuid=uuid,
                instance_type=0 if runtime.outpost else 1,
                instance_epoch=1 if runtime.outpost else 3,
                published_tick=published_tick,
                witnesses=tuple(witnesses),
            )
        )
    return types.SimpleNamespace(
        status=types.SimpleNamespace(value="success"),
        snapshot=types.SimpleNamespace(
            captured_at_tick64=current_tick,
            recovery_epoch=1,
            cohorts=tuple(cohorts),
        ),
    )


def _preserve_publication_publisher_identity_for_probe(publication: Any, publisher: Any) -> None:
    cohort = publication.snapshot.cohorts[0]
    cohort.incarnation = publisher.incarnation
    cohort.character_uuid = publisher.character_uuid
    owner = cohort.owner.GetAccountData()
    owner.AccountEmail = publisher.account_email
    owner.Key.HWND = publisher.hwnd
    owner.AgentData.UUID = publisher.character_uuid
    for child in cohort.children:
        account = child.GetAccountData()
        account.AccountEmail = publisher.account_email
        account.Key.HWND = publisher.hwnd


def _profession_for(module: types.ModuleType, role: Any) -> int:
    profession_by_role = {
        module.CleansingRole.ENERGY_SURGE: module.Profession.Mesmer,
        module.CleansingRole.PANIC: module.Profession.Mesmer,
        module.CleansingRole.INEPTITUDE: module.Profession.Mesmer,
        module.CleansingRole.HEROIC_REFRAIN: module.Profession.Paragon,
        module.CleansingRole.BIP: module.Profession.Necromancer,
        module.CleansingRole.SOUL_TWISTING: module.Profession.Ritualist,
        module.CleansingRole.HEALING_BURST: module.Profession.Monk,
        module.CleansingRole.TAO: module.Profession.Ranger,
    }
    return int(profession_by_role[role])


def _role_bar(runtime: _Runtime, module: types.ModuleType, role: Any, utility_seed: int = 2000) -> tuple[int, ...]:
    skill_ids = _skill_ids(runtime, module)
    anchor_by_role = {
        module.CleansingRole.ENERGY_SURGE: (skill_ids.energy_surge,),
        module.CleansingRole.PANIC: (skill_ids.panic,),
        module.CleansingRole.INEPTITUDE: (skill_ids.ineptitude,),
        module.CleansingRole.HEROIC_REFRAIN: (skill_ids.heroic_refrain,),
        module.CleansingRole.BIP: (skill_ids.blood_is_power,),
        module.CleansingRole.SOUL_TWISTING: (skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union),
        module.CleansingRole.HEALING_BURST: (skill_ids.healing_burst,),
        module.CleansingRole.TAO: (skill_ids.together_as_one, runtime.attack_skill_id),
    }
    bar = list(anchor_by_role[role])
    while len(bar) < 8:
        bar.append(utility_seed + len(bar))
    return tuple(bar)


def _set_player_role(runtime: _Runtime, module: types.ModuleType, role: Any) -> None:
    runtime.professions[runtime.agent_id] = _profession_for(module, role)
    runtime.bars[runtime.agent_id] = _role_bar(runtime, module, role)
    if role is module.CleansingRole.TAO:
        runtime.skill_types[runtime.attack_skill_id] = int(runtime.skill_type.Attack)


def _add_hero(
    runtime: _Runtime,
    module: types.ModuleType,
    role: Any,
    *,
    hero_id: int,
    agent_id: int,
    owner_id: int | None = None,
) -> Any:
    hero = types.SimpleNamespace(
        agent_id=agent_id,
        owner_player_id=runtime.login_number if owner_id is None else owner_id,
        hero_id=hero_id,
    )
    runtime.heroes.append(hero)
    runtime.professions[agent_id] = _profession_for(module, role)
    runtime.bars[agent_id] = _role_bar(runtime, module, role, utility_seed=3000 + hero_id * 10)
    if role is module.CleansingRole.TAO:
        runtime.skill_types[runtime.attack_skill_id] = int(runtime.skill_type.Attack)
    return hero


def _configure_team(runtime: _Runtime, module: types.ModuleType, roles: list[Any]) -> None:
    runtime.heroes.clear()
    runtime.players = [types.SimpleNamespace(login_number=runtime.login_number, is_connected=True)]
    _set_player_role(runtime, module, roles[0])
    for index, role in enumerate(roles[1:], start=1):
        _add_hero(runtime, module, role, hero_id=100 + index, agent_id=2000 + index)
    runtime.party_size_override = None


def _member_records(module: types.ModuleType, roles: list[Any]) -> tuple[Any, ...]:
    records = []
    for index, role in enumerate(roles):
        identity = module.MemberIdentity(module.MemberKind.PLAYER, index + 1, index + 1, index + 100)
        records.append(
            module.MemberRecord(
                identity=identity,
                role=role,
                candidate_role=role,
                evidence_source=module.EvidenceSource.LOCAL_PLAYER,
                reason="test evidence",
            )
        )
    return tuple(records)


def _supported_role(module: types.ModuleType, name: str) -> Any:
    return getattr(module.CleansingRole, name)


@pytest.mark.parametrize("role_name", _SUPPORTED_ROLES)
def test_role_recognition_accepts_each_supported_family(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], role_name: str
) -> None:
    runtime, module = cleansing_runtime
    role = _supported_role(module, role_name)
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.PLAYER, 1, 1, 1001),
        source=module.EvidenceSource.LOCAL_PLAYER,
        primary_profession=_profession_for(module, role),
        skill_ids=_role_bar(runtime, module, role),
        ownership_proven=True,
        weapon_attack_equipped=True if role is module.CleansingRole.TAO else None,
    )

    result = module.recognize_role(evidence, _skill_ids(runtime, module))

    assert (
        result.candidate_role is role
    ), f"role={role_name}; expected={role}; observed={result}; reason={result.reason}"


@pytest.mark.parametrize(
    ("missing_anchor", "expected_name"),
    (("Shelter", "Shelter"), ("Union", "Union")),
)
def test_soul_twisting_requires_both_protection_anchors(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], missing_anchor: str, expected_name: str
) -> None:
    runtime, module = cleansing_runtime
    skill_ids = _skill_ids(runtime, module)
    anchors = [skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union]
    anchors.remove(getattr(skill_ids, missing_anchor.casefold()))
    bar = tuple(anchors + [2200 + index for index in range(8 - len(anchors))])
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 11, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(module.Profession.Ritualist),
        skill_ids=bar,
        ownership_proven=True,
    )

    result = module.recognize_role(evidence, skill_ids)

    assert result.candidate_role is module.CleansingRole.UNKNOWN, f"missing={expected_name}; observed={result}"
    assert expected_name in result.reason, f"missing={expected_name}; reason={result.reason}"


@pytest.mark.parametrize("attack_evidence", (False, None))
def test_tao_requires_positive_weapon_attack_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], attack_evidence: bool | None
) -> None:
    runtime, module = cleansing_runtime
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 11, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(module.Profession.Ranger),
        skill_ids=_role_bar(runtime, module, module.CleansingRole.TAO),
        ownership_proven=True,
        weapon_attack_equipped=attack_evidence,
    )

    result = module.recognize_role(evidence, _skill_ids(runtime, module))

    assert (
        result.candidate_role is module.CleansingRole.UNKNOWN
    ), f"attack_evidence={attack_evidence}; expected UNKNOWN; observed={result}"


def test_role_recognition_rejects_wrong_profession_unsupported_anchor_and_incomplete_bar(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    skill_ids = _skill_ids(runtime, module)
    identity = module.MemberIdentity(module.MemberKind.PLAYER, 11, 11, 1001)

    wrong_profession = module.RoleEvidence(
        identity,
        module.EvidenceSource.LOCAL_PLAYER,
        int(module.Profession.Ranger),
        (skill_ids.energy_surge, *range(3000, 3007)),
        True,
        True,
    )
    unsupported_elite = module.RoleEvidence(
        identity,
        module.EvidenceSource.LOCAL_PLAYER,
        int(module.Profession.Mesmer),
        tuple(range(4000, 4008)),
        True,
    )
    incomplete = module.RoleEvidence(
        identity,
        module.EvidenceSource.LOCAL_PLAYER,
        int(module.Profession.Mesmer),
        (skill_ids.energy_surge, *range(5000, 5006)),
        True,
    )

    results = tuple(
        module.recognize_role(evidence, skill_ids) for evidence in (wrong_profession, unsupported_elite, incomplete)
    )

    assert all(
        result.candidate_role is module.CleansingRole.UNKNOWN for result in results
    ), f"expected wrong profession, unsupported anchor, and incomplete bar to be UNKNOWN; observed={results}"
    assert "profession" in results[0].reason
    assert "anchor" in results[1].reason
    assert "incomplete" in results[2].reason


@pytest.mark.parametrize("profession_name", ("Warrior", "Elementalist"))
def test_unrelated_primary_professions_do_not_match_supported_roles(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], profession_name: str
) -> None:
    runtime, module = cleansing_runtime
    skill_ids = _skill_ids(runtime, module)
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 11, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(getattr(module.Profession, profession_name)),
        skill_ids=(skill_ids.energy_surge, *range(6000, 6007)),
        ownership_proven=True,
    )

    result = module.recognize_role(evidence, skill_ids)

    assert (
        result.candidate_role is module.CleansingRole.UNKNOWN
    ), f"profession={profession_name}; supported elite must not identify this role; observed={result}"


def test_role_recognition_rejects_ambiguous_ownership(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    evidence = module.RoleEvidence(
        identity=module.MemberIdentity(module.MemberKind.HERO, 99, 101, 2001),
        source=module.EvidenceSource.LOCAL_HERO,
        primary_profession=int(module.Profession.Mesmer),
        skill_ids=_role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE),
        ownership_proven=False,
    )

    result = module.recognize_role(evidence, _skill_ids(runtime, module))

    assert (
        result.candidate_role is module.CleansingRole.UNKNOWN
    ), f"ambiguous ownership must fail closed; observed={result}"
    assert "ownership" in result.reason


def test_supported_skill_names_resolve_with_exact_native_names(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _runtime, module = cleansing_runtime
    expected_names = tuple((field, native_name) for field, native_name, _ in _EXPECTED_SUPPORTED_SKILLS)
    result = module.resolve_supported_skill_ids(_native_skill_id_by_name)
    resolved_ids = tuple(getattr(result, field) for field, _, _ in _EXPECTED_SUPPORTED_SKILLS)
    expected_ids = tuple(skill_id for _, _, skill_id in _EXPECTED_SUPPORTED_SKILLS)

    assert (
        module.SUPPORTED_SKILL_NAMES == expected_names
    ), f"supported names={module.SUPPORTED_SKILL_NAMES}; expected native names={expected_names}"
    assert resolved_ids == expected_ids, f"resolved IDs={resolved_ids}; expected Native IDs={expected_ids}"
    assert all(skill_id > 0 for skill_id in resolved_ids), f"resolved IDs must be positive: {resolved_ids}"
    assert len(set(resolved_ids)) == len(_EXPECTED_SUPPORTED_SKILLS), f"resolved IDs must be unique: {resolved_ids}"


@pytest.mark.parametrize("unknown_name", ("Energy Surge", "energy_surge", "energy_Surge", "Not_A_Skill"))
def test_native_skill_lookup_returns_zero_for_unknown_exact_names(unknown_name: str) -> None:
    assert _native_skill_id_by_name(unknown_name) == 0, f"unknown native lookup should return zero: {unknown_name}"


def test_previous_display_name_configuration_fails_with_strict_native_lookup(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, module = cleansing_runtime
    monkeypatch.setattr(module, "SUPPORTED_SKILL_NAMES", _PREVIOUS_DISPLAY_SKILL_NAMES)

    with pytest.raises(ValueError, match="did not resolve"):
        module.resolve_supported_skill_ids(_native_skill_id_by_name)


def test_supported_skill_resolution_fails_closed_for_zero_ids(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _runtime, module = cleansing_runtime

    with pytest.raises(ValueError, match="did not resolve"):
        module.resolve_supported_skill_ids(lambda _name: 0)


def test_supported_skill_resolution_fails_closed_for_duplicate_ids(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _runtime, module = cleansing_runtime

    with pytest.raises(ValueError, match="duplicate IDs"):
        module.resolve_supported_skill_ids(lambda _name: 39)


@pytest.mark.parametrize(
    "roles",
    (
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
        ),
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "PANIC",
        ),
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "HEALING_BURST",
        ),
        ("HEROIC_REFRAIN", "BIP", "SOUL_TWISTING", "INEPTITUDE", "ENERGY_SURGE", "ENERGY_SURGE", "ENERGY_SURGE", "TAO"),
    ),
)
def test_composition_matcher_accepts_only_the_four_supported_histograms_in_any_order(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], roles: tuple[str, ...]
) -> None:
    _, module = cleansing_runtime
    role_list = [_supported_role(module, role) for role in roles]
    random.Random(41).shuffle(role_list)

    result = module.match_supported_composition(_member_records(module, role_list), declared_party_size=8)

    assert (
        result.status is module.CompositionStatus.ACTIVE
    ), f"roles={roles}; shuffled={role_list}; counts={result.role_counts}; reason={result.reason}"
    assert result.is_proven
    assert result.member_count == 8


@pytest.mark.parametrize(
    "roles",
    (
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
        ),
        (
            "HEROIC_REFRAIN",
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
        ),
        (
            "HEROIC_REFRAIN",
            "BIP",
            "SOUL_TWISTING",
            "INEPTITUDE",
            "ENERGY_SURGE",
            "ENERGY_SURGE",
            "PANIC",
            "HEALING_BURST",
        ),
        ("HEROIC_REFRAIN", "BIP", "SOUL_TWISTING", "INEPTITUDE", "ENERGY_SURGE", "ENERGY_SURGE", "PANIC", "TAO"),
    ),
)
def test_composition_matcher_rejects_missing_core_and_duplicate_or_multiple_substitutions(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], roles: tuple[str, ...]
) -> None:
    _, module = cleansing_runtime
    members = _member_records(module, [_supported_role(module, role) for role in roles])

    result = module.match_supported_composition(members)

    assert result.status is module.CompositionStatus.FALLBACK, f"unsupported roles={roles}; observed={result}"
    assert not result.is_proven


def test_composition_matcher_rejects_unknown_candidate_even_when_candidate_is_energy_surge(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    members = list(_member_records(module, roles))
    member = members[-1]
    members[-1] = module.MemberRecord(
        identity=member.identity,
        role=module.CleansingRole.UNKNOWN,
        candidate_role=module.CleansingRole.ENERGY_SURGE,
        evidence_source=member.evidence_source,
        reason="candidate anchor lacks original-bar provenance",
    )

    result = module.match_supported_composition(members)

    assert result.status is module.CompositionStatus.FALLBACK, f"candidate role is not proven; observed={result}"
    assert "UNKNOWN" in result.reason


@pytest.mark.parametrize("member_count", (7, 9))
def test_composition_matcher_rejects_wrong_party_size(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], member_count: int
) -> None:
    _, module = cleansing_runtime
    roles = [module.CleansingRole.ENERGY_SURGE] * member_count
    members = _member_records(module, roles)

    result = module.match_supported_composition(members, declared_party_size=member_count)

    assert result.status is module.CompositionStatus.FALLBACK, f"party_size={member_count}; observed={result}"
    assert "exactly 8" in result.reason


def test_composition_matcher_rejects_declared_party_size_mismatch_and_duplicate_identity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _, module = cleansing_runtime
    roles = [module.CleansingRole.ENERGY_SURGE] * 8
    members = list(_member_records(module, roles))
    mismatch = module.match_supported_composition(members, declared_party_size=9)
    members[-1] = module.MemberRecord(
        identity=members[0].identity,
        role=members[-1].role,
        candidate_role=members[-1].candidate_role,
        evidence_source=members[-1].evidence_source,
        reason=members[-1].reason,
    )
    duplicate = module.match_supported_composition(members)

    assert (
        mismatch.status is module.CompositionStatus.FALLBACK and "incomplete" in mismatch.reason
    ), f"declared size mismatch should fail; observed={mismatch}"
    assert (
        duplicate.status is module.CompositionStatus.FALLBACK and "duplicate" in duplicate.reason
    ), f"duplicate identity should fail; observed={duplicate}"


def test_random_team_with_one_valid_es_candidate_does_not_prove_mesmerway(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _, module = cleansing_runtime
    roles = [module.CleansingRole.UNKNOWN] * 8
    roles[3] = module.CleansingRole.ENERGY_SURGE
    members = list(_member_records(module, roles))
    candidate = members[3]
    members[3] = module.MemberRecord(
        identity=candidate.identity,
        role=candidate.role,
        candidate_role=candidate.role,
        evidence_source=candidate.evidence_source,
        reason="equipped E-Surge candidate",
    )

    result = module.match_supported_composition(members)

    assert result.status is module.CompositionStatus.FALLBACK, f"one E-Surge is not a supported team; observed={result}"
    assert dict(result.role_counts)[module.CleansingRole.ENERGY_SURGE] == 1


def test_context_proves_a_supported_outpost_team_and_revalidates_it_in_explorable(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()

    outpost = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    explorable = context.Refresh()

    assert outpost.supported_composition_proven, f"outpost roles should be proven; observed={outpost.composition}"
    assert (
        explorable.supported_composition_proven
    ), f"fresh explorable bars matching the ready-outpost baseline should prove roles; observed={explorable.composition}"
    assert explorable.revision > outpost.revision
    assert explorable.lifecycle_epoch > outpost.lifecycle_epoch


@pytest.mark.parametrize("attack_equipped", (True, False))
def test_context_uses_skill_type_attack_for_tao_guard(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], attack_equipped: bool
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.TAO,
    ]
    _configure_team(runtime, module, roles)
    tao_hero = runtime.heroes[-1]
    if not attack_equipped:
        bar = runtime.bars[tao_hero.agent_id]
        runtime.bars[tao_hero.agent_id] = (bar[0], *bar[2:], 9900)
    snapshot = module.CleansingContext().Refresh()
    tao_member = next(member for member in snapshot.members if member.identity.agent_id == tao_hero.agent_id)

    if attack_equipped:
        assert tao_member.role is module.CleansingRole.TAO, f"Attack skill type should prove TaO; observed={tao_member}"
        assert snapshot.supported_composition_proven, f"TaO substitution should match; observed={snapshot.composition}"
    else:
        assert (
            tao_member.role is module.CleansingRole.UNKNOWN
        ), f"TaO without Attack must be UNKNOWN; observed={tao_member}"
        assert not snapshot.supported_composition_proven


def test_local_skillbar_agent_mismatch_is_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.skillbar_agent_id = runtime.agent_id + 1

    snapshot = module.CleansingContext().Refresh()

    assert (
        snapshot.members[0].role is module.CleansingRole.UNKNOWN
    ), f"local bar owner mismatch must not classify the player's role; observed={snapshot.members[0]}"
    assert "ownership" in snapshot.members[0].reason


def test_copied_supported_elite_without_matching_outpost_baseline_remains_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    context = module.CleansingContext()
    outpost = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    _set_player_role(runtime, module, module.CleansingRole.PANIC)

    explorable = context.Refresh()
    member = explorable.members[0]

    assert outpost.members[0].role is module.CleansingRole.ENERGY_SURGE
    assert (
        member.role is module.CleansingRole.UNKNOWN
    ), f"copied Panic must not replace baseline E-Surge; observed={member}"
    assert member.candidate_role is module.CleansingRole.PANIC
    assert not explorable.supported_composition_proven


def test_utility_skill_changes_preserve_a_proven_core_role(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    context.Refresh()
    for agent_id, bar in tuple(runtime.bars.items()):
        runtime.bars[agent_id] = (*bar[:3], 8000 + agent_id, *bar[4:])
    outpost = context.Refresh()

    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    for agent_id, bar in tuple(runtime.bars.items()):
        runtime.bars[agent_id] = (*bar[:4], 9000 + agent_id, *bar[5:])
    explorable = context.Refresh()

    assert (
        outpost.supported_composition_proven
    ), f"utility changes in outpost preserve roles; observed={outpost.composition}"
    assert (
        explorable.supported_composition_proven
    ), f"unrelated utility changes in explorable preserve baseline anchors; observed={explorable.composition}"


def test_supported_to_unsupported_bar_clears_the_outpost_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    context = module.CleansingContext()
    context.Refresh()
    original_bar = runtime.bars[runtime.agent_id]
    runtime.bars[runtime.agent_id] = tuple(7000 + index for index in range(8))
    unsupported = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.bars[runtime.agent_id] = original_bar
    returned = context.Refresh()

    assert unsupported.members[0].role is module.CleansingRole.UNKNOWN
    assert (
        returned.members[0].role is module.CleansingRole.UNKNOWN
    ), f"restored anchor cannot reuse a baseline invalidated by an unsupported bar; observed={returned.members[0]}"


def test_unsupported_to_supported_bar_establishes_a_new_outpost_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    runtime.bars[runtime.agent_id] = tuple(7000 + index for index in range(8))
    context = module.CleansingContext()
    unsupported = context.Refresh()
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    supported = context.Refresh()

    assert not unsupported.supported_composition_proven
    assert (
        supported.supported_composition_proven
    ), f"new valid outpost baseline should be proven; observed={supported.composition}"


def test_nonlocal_hero_and_hero_index_mismatch_are_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    _add_hero(
        runtime,
        module,
        module.CleansingRole.ENERGY_SURGE,
        hero_id=101,
        agent_id=2001,
        owner_id=99,
    )
    context = module.CleansingContext()
    nonlocal_snapshot = context.Refresh()
    local_hero = runtime.heroes[0]
    local_hero.owner_player_id = runtime.login_number
    local_hero.agent_id = 2002
    runtime.professions[2002] = int(module.Profession.Mesmer)
    runtime.bars[2002] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.hero_agent_by_position_override[1] = 2001
    mismatch = context.Refresh()

    assert nonlocal_snapshot.members[1].role is module.CleansingRole.UNKNOWN
    assert nonlocal_snapshot.members[1].evidence_source is module.EvidenceSource.REMOTE_HERO
    assert "unavailable" in nonlocal_snapshot.members[1].reason
    assert mismatch.members[1].role is module.CleansingRole.UNKNOWN
    assert "index" in mismatch.members[1].reason


def test_live_party_positions_keep_zero_on_player_and_align_owned_hero_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.TAO,
    ]
    _configure_team(runtime, module, roles)
    first_hero, second_hero = runtime.heroes[:2]

    party = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.Party
    assert party.Heroes.GetHeroAgentIDByPartyPosition(0) == runtime.agent_id
    assert party.Heroes.GetHeroAgentIDByPartyPosition(1) == first_hero.agent_id
    assert party.Heroes.GetHeroAgentIDByPartyPosition(2) == second_hero.agent_id
    assert runtime.hero_agent_positions == [0, 1, 2]

    native_skillbar = sys.modules["PySkillbar"].Skillbar()
    native_skillbar.GetContext()
    bars_by_position = tuple(
        tuple(slot.id.id for slot in native_skillbar.GetHeroSkillbar(position)) for position in (0, 1, 2)
    )
    assert bars_by_position == (
        runtime.bars[runtime.agent_id],
        runtime.bars[first_hero.agent_id],
        runtime.bars[second_hero.agent_id],
    )
    assert runtime.hero_skillbar_positions == [0, 1, 2]
    assert bars_by_position[0] != bars_by_position[1]
    assert bars_by_position[1] != bars_by_position[2]

    runtime.hero_agent_positions.clear()
    runtime.hero_skillbar_positions.clear()
    snapshot = module.CleansingContext().Refresh()
    queried_positions = list(range(1, len(runtime.heroes) + 1))

    assert runtime.hero_agent_positions == queried_positions * 3  # Opening plus bounded final double collection.
    assert runtime.hero_skillbar_positions == queried_positions * 3
    player = next(member for member in snapshot.members if member.identity.kind is module.MemberKind.PLAYER)
    hero_records = {
        member.identity.agent_id: member
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.HERO
    }
    assert player.role is module.CleansingRole.HEROIC_REFRAIN
    assert hero_records[first_hero.agent_id].role is module.CleansingRole.BIP
    assert hero_records[second_hero.agent_id].role is module.CleansingRole.SOUL_TWISTING
    assert (
        snapshot.supported_composition_proven
    ), f"correctly positioned heroes should complete the supported team: {snapshot.composition}"


@pytest.mark.parametrize("reuse_agent_id", (False, True))
def test_hero_replacement_or_agent_identity_reuse_does_not_reuse_old_role(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], reuse_agent_id: bool
) -> None:
    runtime, module = cleansing_runtime
    team = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, team)
    context = module.CleansingContext()
    context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    context.Refresh()

    old_hero = runtime.heroes[0]
    replacement_agent_id = old_hero.agent_id if reuse_agent_id else old_hero.agent_id + 500
    replacement_hero = types.SimpleNamespace(
        agent_id=replacement_agent_id,
        owner_player_id=runtime.login_number,
        hero_id=old_hero.hero_id + 500,
    )
    runtime.heroes[0] = replacement_hero
    runtime.professions[replacement_agent_id] = int(module.Profession.Mesmer)
    runtime.bars[replacement_agent_id] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    replaced = context.Refresh()

    record = next(member for member in replaced.members if member.identity.kind is module.MemberKind.HERO)
    assert (
        record.role is module.CleansingRole.UNKNOWN
    ), f"replacement identity must not inherit an old role; reuse_agent_id={reuse_agent_id}; observed={record}"
    assert record.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert not replaced.supported_composition_proven


def test_map_loading_clears_published_roles_and_same_map_reset_drops_baselines(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    outpost = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    active = context.Refresh()
    runtime.ready = False
    runtime.instance_type_override = 2
    loading = context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    reset = context.Refresh()

    assert outpost.supported_composition_proven and active.supported_composition_proven
    assert not loading.ready and loading.members == (), f"loading must publish no previous roles; observed={loading}"
    assert loading.lifecycle_epoch > active.lifecycle_epoch
    assert not reset.supported_composition_proven
    assert all(
        member.role is module.CleansingRole.UNKNOWN for member in reset.members
    ), f"same-map lifecycle reset must discard prior baseline roles; observed={reset.members}"


@pytest.mark.parametrize("unsafe_state", ("loading", "party_unavailable", "cinematic"))
@pytest.mark.parametrize("supported_recovery", (True, False))
def test_environment_upkeeper_gate_invalidates_snapshot_without_running_normal_cache_updates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    unsafe_state: str,
    supported_recovery: bool,
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    corelib = sys.modules["Py4GWCoreLib"]
    runtime_cache = corelib.GLOBAL_CACHE
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = runtime_cache.Party
    global_cache.Skill = runtime_cache.Skill
    global_cache.Coroutines = []

    refresh_calls = 0

    def update_normal_caches() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        context.Refresh()

    global_cache._update_cache = update_normal_caches
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)

    upkeeper.main()
    active = context.GetSnapshot()
    assert active.supported_composition_proven, f"precondition requires ACTIVE composition; observed={active}"
    assert refresh_calls == 1

    if unsafe_state == "loading":
        runtime.ready = False
        runtime.instance_type_override = 2
    elif unsafe_state == "party_unavailable":
        runtime.party_loaded = False
    else:
        runtime.cinematic = True

    upkeeper.main()
    invalid = context.GetSnapshot()
    assert not invalid.ready and invalid.members == (), f"unsafe state must hide prior members; observed={invalid}"
    assert invalid.composition.status is module.CompositionStatus.FALLBACK
    assert invalid.revision > active.revision
    assert invalid.lifecycle_epoch == active.lifecycle_epoch + 1
    assert refresh_calls == 1, "normal cache refresh must stay gated while MapValid is false"

    upkeeper.main()
    repeated_invalid = context.GetSnapshot()
    assert repeated_invalid.revision == invalid.revision, "repeated unsafe frames must not churn revisions"
    assert repeated_invalid.lifecycle_epoch == invalid.lifecycle_epoch, "one unsafe period advances one epoch"
    assert refresh_calls == 1

    changed_core_hero = runtime.heroes[0]
    if not supported_recovery:
        runtime.bars[changed_core_hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.party_loaded = True
    runtime.cinematic = False
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    upkeeper.main()
    recovered = context.GetSnapshot()

    assert refresh_calls == 2, "normal cache refresh resumes only after MapValid becomes true"
    if supported_recovery:
        assert recovered.supported_composition_proven, f"fresh matching evidence should restore ACTIVE; {recovered}"
    else:
        assert not recovered.supported_composition_proven
        assert recovered.composition.status is module.CompositionStatus.FALLBACK
        changed_record = next(
            member for member in recovered.members if member.identity.agent_id == changed_core_hero.agent_id
        )
        assert changed_record.role is module.CleansingRole.UNKNOWN


def test_environment_upkeeper_gate_arms_remote_outpost_transition_without_context_refresh(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()
    runtime_cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = runtime_cache.Party
    global_cache.Skill = runtime_cache.Skill
    global_cache.ShMem = runtime_cache.ShMem
    global_cache.Coroutines = []
    refresh_calls = 0

    def update_normal_caches() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        context.Refresh()

    global_cache._update_cache = update_normal_caches
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)

    upkeeper.main()
    outpost = context.GetSnapshot()
    assert _remote_player_record(outpost, module).role is module.CleansingRole.PANIC

    runtime.ready = False
    runtime.instance_type_override = 2
    upkeeper.main()
    upkeeper.main()
    production_map = sys.modules["Py4GWCoreLib"].Map
    assert production_map.IsMapDataLoaded()
    assert production_map.IsMapLoading()
    assert production_map.GetInstanceType() == 2
    gated = context.GetSnapshot()
    assert not gated.ready and gated.members == ()
    assert context._pending_outpost_transition
    assert context._pending_remote_outpost_transition
    assert context._remote_player_baselines
    assert refresh_calls == 1, "loading gate must skip the normal party and agent context refresh"

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    upkeeper.main()
    explorable = context.GetSnapshot()
    local = next(
        member
        for member in explorable.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
    )

    assert _remote_player_record(explorable, module).role is module.CleansingRole.PANIC
    assert explorable.ready
    assert local.role is module.CleansingRole.ENERGY_SURGE
    assert refresh_calls == 2

    upkeeper.main()
    unchanged = context.GetSnapshot()
    assert _remote_player_record(unchanged, module).role is module.CleansingRole.PANIC
    assert unchanged.ready
    assert refresh_calls == 3


@pytest.mark.parametrize("loading_was_observed", (False, True))
def test_environment_gate_rejects_cinematic_only_transition_authority(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    loading_was_observed: bool,
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()
    runtime_cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = runtime_cache.Party
    global_cache.Skill = runtime_cache.Skill
    global_cache.ShMem = runtime_cache.ShMem
    global_cache.Coroutines = []
    refresh_calls = 0

    def update_normal_caches() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        context.Refresh()

    global_cache._update_cache = update_normal_caches
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)

    upkeeper.main()
    assert _remote_player_record(context.GetSnapshot(), module).role is module.CleansingRole.PANIC
    if loading_was_observed:
        runtime.ready = False
        runtime.instance_type_override = 2
        upkeeper.main()
        assert context._pending_outpost_transition

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.cinematic = True
    upkeeper.main()
    upkeeper.main()

    assert not context._pending_remote_outpost_transition
    assert context._remote_player_baselines == {}
    assert refresh_calls == 1, "invalid gate callbacks must not refresh party or agent evidence"

    runtime.cinematic = False
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    upkeeper.main()
    destination = context.GetSnapshot()
    remote = _remote_player_record(destination, module)

    assert remote.role is module.CleansingRole.UNKNOWN
    assert remote.candidate_role is module.CleansingRole.PANIC
    assert destination.ready
    assert refresh_calls == 2


@pytest.mark.parametrize("invalid_state", ("missing_world_context", "unknown_instance_type"))
def test_map_loading_fallback_is_not_remote_transition_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    invalid_state: str,
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()
    corelib = sys.modules["Py4GWCoreLib"]
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = corelib.GLOBAL_CACHE.Party
    global_cache.Skill = corelib.GLOBAL_CACHE.Skill
    global_cache.ShMem = corelib.GLOBAL_CACHE.ShMem
    global_cache.Coroutines = []
    refresh_calls = 0

    def update_normal_caches() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        context.Refresh()

    global_cache._update_cache = update_normal_caches
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)
    upkeeper.main()
    assert _remote_player_record(context.GetSnapshot(), module).role is module.CleansingRole.PANIC
    assert context._remote_player_baselines

    map_api = corelib.Map
    map_enums = sys.modules["Py4GWCoreLib.enums_src.Map_enums"]
    if invalid_state == "missing_world_context":
        runtime.missing_map_contexts.add("world")
        assert map_api.GetInstanceType() == map_enums.InstanceType.Outpost.value
        assert not map_api.IsMapDataLoaded()
    else:
        runtime.instance_type_override = 999
        assert map_api.GetInstanceType() == map_enums.InstanceType.Loading.value
        assert map_api.IsMapDataLoaded()

    assert map_api.IsMapLoading(), f"production fallback should report loading for {invalid_state}"
    upkeeper.main()
    upkeeper.main()

    gated = context.GetSnapshot()
    assert not gated.ready
    assert context._pending_outpost_transition == (invalid_state == "missing_world_context")
    assert not context._pending_remote_outpost_transition
    assert bool(context._remote_player_baselines) == (invalid_state == "missing_world_context")
    assert refresh_calls == 1, "invalid callbacks must not read party or agent evidence"

    runtime.missing_map_contexts.clear()
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.ready = True
    runtime.publication_result = _remote_publication(runtime, module)
    upkeeper.main()
    destination = context.GetSnapshot()
    remote = _remote_player_record(destination, module)
    local = next(
        member
        for member in destination.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
    )

    assert destination.ready
    assert remote.role is module.CleansingRole.UNKNOWN
    assert remote.candidate_role is module.CleansingRole.PANIC
    assert local.role is module.CleansingRole.ENERGY_SURGE
    assert refresh_calls == 2


def test_incomplete_outpost_cannot_establish_remote_transition_authority(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    runtime.party_size_override = 3
    context = module.CleansingContext()

    incomplete = context.Refresh()
    assert not incomplete.ready
    assert _remote_player_record(incomplete, module).role is module.CleansingRole.PANIC

    runtime.party_size_override = None
    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    assert not context._pending_outpost_transition
    assert not context._pending_remote_outpost_transition
    assert context._remote_player_baselines == {}

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    destination = context.Refresh()

    assert _remote_player_record(destination, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(destination, module).candidate_role is module.CleansingRole.PANIC
    local = next(
        member
        for member in destination.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
    )
    assert local.role is module.CleansingRole.ENERGY_SURGE
    assert destination.ready


@pytest.mark.parametrize("missing_context", ("world", "map", "char", "instance_info"))
def test_direct_refresh_missing_required_context_cannot_carry_remote_baselines(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    missing_context: str,
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()

    outpost = context.Refresh()
    assert outpost.ready
    assert _remote_player_record(outpost, module).role is module.CleansingRole.PANIC
    assert context._baselines and context._remote_player_baselines

    corelib = sys.modules["Py4GWCoreLib"]
    map_api = corelib.Map
    runtime.missing_map_contexts.add(missing_context)
    assert not map_api.IsMapDataLoaded()
    assert map_api.IsMapLoading()
    assert not map_api.IsMapLoadingObserved()

    invalid = context.Refresh()
    repeated_invalid = context.Refresh()
    assert not invalid.ready and invalid.members == ()
    assert not repeated_invalid.ready and repeated_invalid.members == ()
    assert context._pending_outpost_transition
    assert not context._pending_remote_outpost_transition
    assert context._baselines, "invalid map data must preserve the local Stage 2 baseline"
    assert context._remote_player_baselines, "temporary absence retains private candidates without authorizing Loading"

    runtime.missing_map_contexts.clear()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    destination = context.Refresh()
    remote = _remote_player_record(destination, module)
    local = next(
        member
        for member in destination.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
    )
    assert destination.ready
    assert local.role is module.CleansingRole.ENERGY_SURGE
    assert remote.role is module.CleansingRole.UNKNOWN
    assert remote.candidate_role is module.CleansingRole.PANIC

    unchanged = context.Refresh()
    assert unchanged.ready
    assert _remote_player_record(unchanged, module).role is module.CleansingRole.UNKNOWN
    assert (
        next(
            member
            for member in unchanged.members
            if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
        ).role
        is module.CleansingRole.ENERGY_SURGE
    )


@pytest.mark.parametrize(
    ("invalid_state", "raw_instance_type"),
    (("outpost", 0), ("unknown_instance_type", 999)),
)
def test_direct_refresh_outpost_or_unknown_type_cannot_authorize_remote_carry(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    invalid_state: str,
    raw_instance_type: int,
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()

    outpost = context.Refresh()
    assert outpost.ready
    assert _remote_player_record(outpost, module).role is module.CleansingRole.PANIC

    map_api = sys.modules["Py4GWCoreLib"].Map
    map_enums = sys.modules["Py4GWCoreLib.enums_src.Map_enums"]
    runtime.ready = False
    runtime.instance_type_override = raw_instance_type
    assert map_api.IsMapDataLoaded()
    assert not map_api.IsMapLoadingObserved()
    if invalid_state == "outpost":
        assert map_api.GetInstanceType() == map_enums.InstanceType.Outpost.value
        assert not map_api.IsMapLoading()
    else:
        assert map_api.GetInstanceType() == map_enums.InstanceType.Loading.value
        assert map_api.IsMapLoading()

    invalid = context.Refresh()
    repeated_invalid = context.Refresh()
    assert not invalid.ready and not repeated_invalid.ready
    assert context._pending_outpost_transition == (invalid_state == "outpost")
    assert not context._pending_remote_outpost_transition
    assert bool(context._remote_player_baselines) == (invalid_state == "outpost")

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    destination = context.Refresh()
    assert destination.ready
    assert _remote_player_record(destination, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(destination, module).candidate_role is module.CleansingRole.PANIC


def test_direct_refresh_explicit_loading_preserves_remote_carry_and_destination_roles(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()

    outpost = context.Refresh()
    assert outpost.ready
    assert _remote_player_record(outpost, module).role is module.CleansingRole.PANIC

    map_api = sys.modules["Py4GWCoreLib"].Map
    map_enums = sys.modules["Py4GWCoreLib.enums_src.Map_enums"]
    runtime.ready = False
    runtime.instance_type_override = map_enums.InstanceType.Loading.value
    assert map_api.IsMapDataLoaded()
    assert map_api.IsMapLoading()
    assert map_api.IsMapLoadingObserved()
    context.Refresh()
    context.Refresh()
    assert context._pending_outpost_transition
    assert context._pending_remote_outpost_transition
    assert context._remote_player_baselines

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    destination = context.Refresh()
    remote = _remote_player_record(destination, module)
    local = next(
        member
        for member in destination.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
    )
    assert destination.ready
    assert local.role is module.CleansingRole.ENERGY_SURGE
    assert remote.role is module.CleansingRole.PANIC

    unchanged = context.Refresh()
    assert unchanged.ready
    assert _remote_player_record(unchanged, module).role is module.CleansingRole.PANIC
    assert (
        next(
            member
            for member in unchanged.members
            if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
        ).role
        is module.CleansingRole.ENERGY_SURGE
    )


def test_direct_refresh_cinematic_invalidation_clears_remote_transition_authority(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()

    outpost = context.Refresh()
    assert outpost.ready
    assert _remote_player_record(outpost, module).role is module.CleansingRole.PANIC

    runtime.ready = False
    runtime.instance_type_override = sys.modules["Py4GWCoreLib.enums_src.Map_enums"].InstanceType.Loading.value
    context.Refresh()
    assert context._pending_remote_outpost_transition

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.cinematic = True
    invalid = context.Refresh()
    assert not invalid.ready
    assert not context._pending_remote_outpost_transition
    assert context._remote_player_baselines == {}

    runtime.cinematic = False
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    destination = context.Refresh()
    assert destination.ready
    assert _remote_player_record(destination, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(destination, module).candidate_role is module.CleansingRole.PANIC


@pytest.mark.parametrize("replacement", ("character", "hero_agent", "party_hero"))
def test_environment_upkeeper_rechecks_identity_after_suppressed_lifecycle_updates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    corelib = sys.modules["Py4GWCoreLib"]
    runtime_cache = corelib.GLOBAL_CACHE
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = runtime_cache.Party
    global_cache.Skill = runtime_cache.Skill
    global_cache.Coroutines = []

    refresh_calls = 0

    def update_normal_caches() -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        context.Refresh()

    global_cache._update_cache = update_normal_caches
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)

    upkeeper.main()
    assert context.GetSnapshot().supported_composition_proven
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    upkeeper.main()
    active = context.GetSnapshot()
    assert active.supported_composition_proven, f"precondition requires active explorable context; {active}"

    runtime.ready = False
    runtime.instance_type_override = 2
    upkeeper.main()
    invalid = context.GetSnapshot()
    assert not invalid.ready and not invalid.supported_composition_proven
    assert refresh_calls == 2

    if replacement == "character":
        runtime.set_identity(12, "mesmer@example.test", "Mesmer B")
    elif replacement == "hero_agent":
        hero = runtime.heroes[0]
        hero.agent_id += 500
        runtime.professions[hero.agent_id] = int(module.Profession.Paragon)
        runtime.bars[hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    else:
        old_hero = runtime.heroes[0]
        replacement_agent_id = old_hero.agent_id + 500
        replacement_hero = types.SimpleNamespace(
            agent_id=replacement_agent_id,
            owner_player_id=runtime.login_number,
            hero_id=old_hero.hero_id + 500,
        )
        runtime.heroes[0] = replacement_hero
        runtime.professions[replacement_agent_id] = int(module.Profession.Paragon)
        runtime.bars[replacement_agent_id] = _role_bar(runtime, module, module.CleansingRole.HEROIC_REFRAIN)

    runtime.ready = True
    runtime.instance_type_override = None
    upkeeper.main()
    refreshed = context.GetSnapshot()

    assert refresh_calls == 3
    assert (
        not refreshed.supported_composition_proven
    ), f"{replacement} replacement during an invalid period must not inherit prior ACTIVE proof; {refreshed}"
    assert refreshed.composition.status is module.CompositionStatus.FALLBACK


def test_local_character_switch_invalidates_all_old_build_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
    ]
    _configure_team(runtime, module, roles)
    context = module.CleansingContext()
    baseline = context.Refresh()
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.set_identity(12, "mesmer@example.test", "Mesmer B")
    for hero in runtime.heroes:
        hero.owner_player_id = runtime.login_number
    switched = context.Refresh()

    assert baseline.supported_composition_proven
    assert switched.character_identity == ("mesmer@example.test", "Mesmer B")
    assert not switched.supported_composition_proven
    assert all(
        member.role is module.CleansingRole.UNKNOWN for member in switched.members
    ), f"old character baselines must not cross a character switch; observed={switched.members}"


def test_runtime_read_failure_clears_snapshot_and_baselines(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    context = module.CleansingContext()
    supported = context.Refresh()
    corelib = sys.modules["Py4GWCoreLib"]
    original_party = corelib.GLOBAL_CACHE.Party
    failing_party = types.SimpleNamespace(
        IsPartyLoaded=lambda: True,
        GetPlayers=lambda: (_ for _ in ()).throw(RuntimeError("party read failed")),
        GetHeroes=original_party.GetHeroes,
        GetHenchmen=original_party.GetHenchmen,
        GetPartySize=original_party.GetPartySize,
        Players=original_party.Players,
        Heroes=original_party.Heroes,
    )
    monkeypatch.setattr(corelib.GLOBAL_CACHE, "Party", failing_party)

    failed = context.Refresh()

    assert supported.members[0].role is module.CleansingRole.ENERGY_SURGE
    assert failed.members == () and not failed.ready, f"failed reads must publish no stale roles; observed={failed}"
    assert "read failed" in failed.reason


def test_unchanged_refresh_keeps_revision_and_member_lookup_is_from_snapshot(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    context = module.CleansingContext()
    first = context.Refresh()
    second = context.Refresh()

    assert (
        second.revision == first.revision
    ), f"unchanged evidence should not publish a new revision: {first} -> {second}"
    assert second.get_member(first.members[0].identity) == first.members[0]
    assert context.GetMember(first.members[0].identity) == first.members[0]


def _remote_player_record(snapshot: Any, module: types.ModuleType, login_number: int = 22) -> Any:
    return next(
        member
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == login_number
    )


def _preserve_remote_publisher_identity(destination: Any, source: Any) -> None:
    destination_owner = destination.owner.GetAccountData()
    source_owner = source.owner.GetAccountData()
    destination_owner.AccountEmail = source_owner.AccountEmail
    destination_owner.Key.HWND = source_owner.Key.HWND
    destination_owner.AgentData.UUID = source_owner.AgentData.UUID
    destination.character_uuid = source.character_uuid
    destination.incarnation = source.incarnation


def _preserve_remote_publishers_by_agent(destination: Any, originals_by_agent: dict[int, Any]) -> None:
    for cohort in destination.cohorts:
        agent_id = int(cohort.owner.GetAccountData().AgentData.AgentID)
        _preserve_remote_publisher_identity(cohort, originals_by_agent[agent_id])


def _remote_hero_record(snapshot: Any, module: types.ModuleType, owner: int = 22, hero_id: int = 7) -> Any:
    return next(
        member
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.HERO
        and member.identity.owner_id == owner
        and member.identity.member_id == hero_id
    )


def _setup_remote_hero(
    runtime: _Runtime,
    module: types.ModuleType,
    *,
    owner_login: int = 22,
    owner_agent: int = 2001,
    hero_id: int = 7,
    hero_agent: int = 3001,
    owner_role: Any = None,
    hero_role: Any = None,
) -> Any:
    _add_remote_player(
        runtime,
        module,
        login_number=owner_login,
        agent_id=owner_agent,
        role=owner_role,
        name=f"Remote {owner_login}",
    )
    if hero_role is None:
        hero_role = module.CleansingRole.ENERGY_SURGE
    _add_hero(
        runtime,
        module,
        hero_role,
        hero_id=hero_id,
        agent_id=hero_agent,
        owner_id=owner_login,
    )
    runtime.publication_result = _remote_publication(runtime, module)
    return runtime.publication_result.snapshot.cohorts[0]


def test_connected_remote_player_role_is_visible_but_composition_projects_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()
    remote = _remote_player_record(snapshot, module)

    assert remote.role is module.CleansingRole.PANIC, f"proven remote role should be visible: {remote}"
    assert remote.evidence_source is module.EvidenceSource.REMOTE_PLAYER
    assert remote.remote_provenance_generation == 1
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.UNKNOWN] == 1
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.PANIC] == 0


def test_remote_owner_with_unknown_role_still_proves_remote_hero(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _setup_remote_hero(runtime, module, owner_role=None, hero_role=module.CleansingRole.ENERGY_SURGE)

    snapshot = module.CleansingContext().Refresh()
    owner = _remote_player_record(snapshot, module)
    hero = _remote_hero_record(snapshot, module)

    assert owner.role is module.CleansingRole.UNKNOWN
    assert owner.remote_provenance_generation == 1
    assert hero.role is module.CleansingRole.ENERGY_SURGE, f"owner role is irrelevant to hero ownership: {hero}"
    assert hero.evidence_source is module.EvidenceSource.REMOTE_HERO
    assert hero.remote_provenance_generation == owner.remote_provenance_generation


@pytest.mark.parametrize(
    "defect",
    (
        "disconnected",
        "duplicate_login",
        "zero_endpoint",
        "mismatched_endpoint",
        "agent_login_mismatch",
        "local_window",
        "local_account",
        "profession_mismatch",
        "trustworthy_name_mismatch",
        "not_living_type",
    ),
)
def test_remote_player_identity_defects_fail_closed_without_breaking_local_stage2(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], defect: str
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    remote = _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    owner = runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData()

    if defect == "disconnected":
        remote.is_connected = False
    elif defect == "duplicate_login":
        runtime.players.append(types.SimpleNamespace(login_number=22, is_connected=True))
        runtime.local_agent_by_login[23] = 2002
        runtime.professions[2002] = int(module.Profession.Mesmer)
    elif defect == "zero_endpoint":
        runtime.local_agent_by_login[22] = 0
    elif defect == "mismatched_endpoint":
        owner.AgentData.AgentID = 2999
    elif defect == "agent_login_mismatch":
        runtime.living_login_override[2001] = 23
    elif defect == "local_window":
        owner.Key.HWND = runtime.local_hwnd
    elif defect == "local_account":
        owner.AccountEmail = runtime.account_email
    elif defect == "profession_mismatch":
        owner.AgentData.Profession = (int(module.Profession.Monk), 0)
    elif defect == "trustworthy_name_mismatch":
        owner.AgentData.CharacterName = "Someone Else"
    elif defect == "not_living_type":
        runtime.agent_type_by_id[2001] = False

    snapshot = module.CleansingContext().Refresh()
    remote_record = _remote_player_record(snapshot, module)
    local_record = next(member for member in snapshot.members if member.identity.owner_id == runtime.login_number)

    assert remote_record.role is module.CleansingRole.UNKNOWN, f"{defect} must fail closed: {remote_record}"
    assert remote_record.evidence_source is module.EvidenceSource.REMOTE_PLAYER
    assert local_record.role is module.CleansingRole.ENERGY_SURGE
    assert snapshot.ready, "remote identity failures must not redefine CleansingContext.ready"


def test_competing_contextual_owner_claims_count_before_window_name_or_profession_filtering(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    owner = runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData()
    competing = _account_evidence(
        slot=99,
        email="another@example.test",
        name="Wrong Name",
        hwnd=runtime.local_hwnd,
        entity_type=0,
        local_index=0,
        is_account=True,
        is_hero=False,
        agent_id=2001,
        owner_agent_id=0,
        hero_id=0,
        login_number=22,
        character_uuid=(9900, 1, 0, 0),
        professions=(int(module.Profession.Monk), 0),
        map_signature=(runtime.map_id, runtime.region_id, runtime.district_id, runtime.language_id),
        party_id=runtime.party_id,
        skill_ids=tuple(8000 + index for index in range(8)),
        published_tick=owner.LastUpdated,
    )
    base_cohort = runtime.publication_result.snapshot.cohorts[0]
    rival = types.SimpleNamespace(
        owner=competing,
        children=(),
        incarnation=b"rival-owner-claim!",
        character_uuid=(9900, 1, 0, 0),
        instance_type=base_cohort.instance_type,
        instance_epoch=base_cohort.instance_epoch,
        published_tick=base_cohort.published_tick,
        witnesses=(),
    )
    runtime.publication_result.snapshot.cohorts += (rival,)

    snapshot = module.CleansingContext().Refresh()
    remote_record = _remote_player_record(snapshot, module)

    assert remote_record.role is module.CleansingRole.UNKNOWN
    assert "ambiguous" in remote_record.reason


def test_remote_player_explorable_requires_outpost_loading_transition_and_matching_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    outpost = context.Refresh()

    runtime.ready = False
    runtime.instance_type_override = 2
    loading = context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.publication_result = _remote_publication(runtime, module)
    explorable = context.Refresh()

    assert _remote_player_record(outpost, module).role is module.CleansingRole.PANIC
    assert not loading.ready and loading.members == ()
    assert _remote_player_record(explorable, module).role is module.CleansingRole.PANIC
    assert explorable.lifecycle_epoch > outpost.lifecycle_epoch


def test_remote_player_destination_baseline_survives_unchanged_refreshes_and_rejects_contradiction(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    first_destination = context.Refresh()
    repeated_destination = context.Refresh()

    assert _remote_player_record(first_destination, module).role is module.CleansingRole.PANIC
    assert _remote_player_record(repeated_destination, module).role is module.CleansingRole.PANIC
    assert len(context._remote_player_baselines) == 1

    runtime.bars[2001] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.publication_result = _remote_publication(runtime, module)
    contradictory = context.Refresh()

    assert _remote_player_record(contradictory, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(contradictory, module).candidate_role is module.CleansingRole.ENERGY_SURGE
    assert context._remote_player_baselines == {}


def test_remote_player_disconnect_during_transition_prevents_reconnect_from_reusing_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    remote = _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    remote.is_connected = False
    runtime.publication_result = _remote_publication(runtime, module)
    disconnected = context.Refresh()
    remote.is_connected = True
    runtime.publication_result = _remote_publication(runtime, module)
    reconnected = context.Refresh()

    assert _remote_player_record(disconnected, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(reconnected, module).candidate_role is module.CleansingRole.PANIC
    assert _remote_player_record(reconnected, module).role is module.CleansingRole.UNKNOWN
    assert context._remote_player_baselines == {}


def test_remote_player_baseline_does_not_cross_an_unobserved_transition(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC

    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.publication_result = _remote_publication(runtime, module)
    direct = context.Refresh()

    assert _remote_player_record(direct, module).role is module.CleansingRole.UNKNOWN
    assert context._remote_player_baselines == {}


def test_remote_player_baseline_is_bound_to_the_local_character_uuid(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.local_uuid = (777, 1, 0, 0)
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.publication_result = _remote_publication(runtime, module)
    changed_local_character = context.Refresh()

    assert _remote_player_record(changed_local_character, module).role is module.CleansingRole.UNKNOWN


def test_remote_player_baseline_rebinds_login_only_with_exact_publisher_continuity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    remote_player = _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    original_cohort = runtime.publication_result.snapshot.cohorts[0]
    original_owner = original_cohort.owner.GetAccountData()
    original_publisher = (
        original_owner.AccountEmail,
        original_owner.Key.HWND,
        original_owner.AgentData.UUID,
        original_cohort.incarnation,
    )
    context = module.CleansingContext()
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    remote_player.login_number = 24
    runtime.local_agent_by_login.pop(22)
    runtime.local_agent_by_login[24] = 2001
    runtime.player_names[24] = runtime.player_names.pop(22)
    runtime.publication_result = _remote_publication(runtime, module)
    rebound_cohort = runtime.publication_result.snapshot.cohorts[0]
    rebound_owner = rebound_cohort.owner.GetAccountData()
    rebound_owner.AccountEmail = original_publisher[0]
    rebound_owner.Key.HWND = original_publisher[1]
    rebound_owner.AgentData.UUID = original_publisher[2]
    rebound_cohort.character_uuid = original_publisher[2]
    rebound_cohort.incarnation = original_publisher[3]

    rebound = context.Refresh()
    repeated = context.Refresh()
    current_key = (module.MemberKind.PLAYER, 24, 24)

    assert _remote_player_record(rebound, module, login_number=24).role is module.CleansingRole.PANIC
    assert _remote_player_record(repeated, module, login_number=24).role is module.CleansingRole.PANIC
    assert current_key in context._remote_player_baselines
    assert (module.MemberKind.PLAYER, 22, 22) not in context._remote_player_baselines

    assert len(context._remote_player_baselines) == 1


@pytest.mark.parametrize("defect", ("publisher", "local_character", "ambiguous"))
def test_remote_player_login_reassociation_rejects_broken_or_ambiguous_continuity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], defect: str
) -> None:
    runtime, module = cleansing_runtime
    remote_player = _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    original_cohort = runtime.publication_result.snapshot.cohorts[0]
    original_owner = original_cohort.owner.GetAccountData()
    context = module.CleansingContext()
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC
    if defect == "ambiguous":
        context._remote_player_baselines[(module.MemberKind.PLAYER, 23, 23)] = next(
            iter(context._remote_player_baselines.values())
        )

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    remote_player.login_number = 24
    runtime.local_agent_by_login.pop(22)
    runtime.local_agent_by_login[24] = 2001
    runtime.player_names[24] = runtime.player_names.pop(22)
    runtime.publication_result = _remote_publication(runtime, module)
    rebound_cohort = runtime.publication_result.snapshot.cohorts[0]
    rebound_owner = rebound_cohort.owner.GetAccountData()
    rebound_owner.AccountEmail = original_owner.AccountEmail
    rebound_owner.Key.HWND = original_owner.Key.HWND
    rebound_owner.AgentData.UUID = original_owner.AgentData.UUID
    rebound_cohort.character_uuid = original_cohort.character_uuid
    rebound_cohort.incarnation = original_cohort.incarnation
    if defect == "publisher":
        rebound_cohort.incarnation = b"changed-incarnation"
    elif defect == "local_character":
        runtime.local_uuid = (777, 1, 0, 0)

    rejected = context.Refresh()
    remote = _remote_player_record(rejected, module, login_number=24)

    assert remote.candidate_role is module.CleansingRole.PANIC
    assert remote.role is module.CleansingRole.UNKNOWN
    assert rejected.ready
    assert _remote_player_record(rejected, module, login_number=24).identity.agent_id == 2001
    assert all(key[1] != 22 for key in context._remote_player_baselines)
    assert len(context._remote_player_baselines) == 0
    if defect == "ambiguous":
        assert "multiple" in remote.reason


@pytest.mark.parametrize("reverse_roster", (False, True))
def test_remote_players_can_swap_destination_logins_without_overwriting_baselines(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], reverse_roster: bool
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, login_number=22, agent_id=2001, role=module.CleansingRole.PANIC)
    _add_remote_player(runtime, module, login_number=23, agent_id=2002, role=module.CleansingRole.INEPTITUDE)
    runtime.publication_result = _remote_publication(runtime, module)
    originals_by_agent = {
        int(cohort.owner.GetAccountData().AgentData.AgentID): cohort
        for cohort in runtime.publication_result.snapshot.cohorts
    }
    context = module.CleansingContext()
    assert _remote_player_record(context.Refresh(), module, login_number=22).role is module.CleansingRole.PANIC
    assert _remote_player_record(context.GetSnapshot(), module, login_number=23).role is module.CleansingRole.INEPTITUDE

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    agent_22 = runtime.local_agent_by_login[22]
    agent_23 = runtime.local_agent_by_login[23]
    runtime.local_agent_by_login[22] = agent_23
    runtime.local_agent_by_login[23] = agent_22
    name_22 = runtime.player_names[22]
    runtime.player_names[22] = runtime.player_names[23]
    runtime.player_names[23] = name_22
    if reverse_roster:
        runtime.players = [runtime.players[0], runtime.players[2], runtime.players[1]]
    runtime.publication_result = _remote_publication(runtime, module)
    _preserve_remote_publishers_by_agent(runtime.publication_result.snapshot, originals_by_agent)

    destination = context.Refresh()
    by_agent = {
        member.identity.agent_id: member
        for member in destination.members
        if member.evidence_source is module.EvidenceSource.REMOTE_PLAYER
    }

    assert by_agent[2001].identity.owner_id == 23
    assert by_agent[2001].role is module.CleansingRole.PANIC
    assert by_agent[2002].identity.owner_id == 22
    assert by_agent[2002].role is module.CleansingRole.INEPTITUDE
    assert destination.ready
    assert len(context._remote_player_baselines) == 2
    assert set(context._remote_player_baselines) == {
        (module.MemberKind.PLAYER, 22, 22),
        (module.MemberKind.PLAYER, 23, 23),
    }


def test_rejected_reassociation_does_not_corrupt_another_owners_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    owner_a = _add_remote_player(runtime, module, login_number=22, agent_id=2001, role=module.CleansingRole.PANIC)
    _add_remote_player(runtime, module, login_number=23, agent_id=2002, role=module.CleansingRole.INEPTITUDE)
    runtime.publication_result = _remote_publication(runtime, module)
    original_cohorts = {
        int(cohort.owner.GetAccountData().AgentData.AgentID): cohort
        for cohort in runtime.publication_result.snapshot.cohorts
    }
    context = module.CleansingContext()
    context.Refresh()

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    owner_a.login_number = 24
    runtime.local_agent_by_login.pop(22)
    runtime.local_agent_by_login[24] = 2001
    runtime.player_names[24] = runtime.player_names.pop(22)
    runtime.publication_result = _remote_publication(runtime, module)
    _preserve_remote_publishers_by_agent(runtime.publication_result.snapshot, original_cohorts)
    owner_a_bar = runtime.bars[2001]
    runtime.bars[2001] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.publication_result = _remote_publication(runtime, module)
    _preserve_remote_publishers_by_agent(runtime.publication_result.snapshot, original_cohorts)
    runtime.bars[2001] = owner_a_bar

    destination = context.Refresh()
    owner_a_record = _remote_player_record(destination, module, login_number=24)
    owner_b_record = _remote_player_record(destination, module, login_number=23)

    assert owner_a_record.role is module.CleansingRole.UNKNOWN
    assert owner_a_record.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert owner_b_record.role is module.CleansingRole.INEPTITUDE
    assert destination.ready
    assert (module.MemberKind.PLAYER, 23, 23) in context._remote_player_baselines
    assert (module.MemberKind.PLAYER, 22, 22) not in context._remote_player_baselines


@pytest.mark.parametrize("reverse_roster", (False, True))
def test_reassociation_retired_foreign_baseline_does_not_reserve_destination(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], reverse_roster: bool
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    owner_a = _add_remote_player(runtime, module, login_number=22, agent_id=2001, role=module.CleansingRole.PANIC)
    owner_b = _add_remote_player(runtime, module, login_number=24, agent_id=2002, role=module.CleansingRole.INEPTITUDE)
    runtime.publication_result = _remote_publication(runtime, module)
    originals_by_agent = {
        int(cohort.owner.GetAccountData().AgentData.AgentID): cohort
        for cohort in runtime.publication_result.snapshot.cohorts
    }
    context = module.CleansingContext()
    context.Refresh()

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    owner_a.login_number = 24
    owner_b.login_number = 23
    runtime.local_agent_by_login.pop(22)
    runtime.local_agent_by_login.pop(24)
    runtime.local_agent_by_login[24] = 2001
    runtime.local_agent_by_login[23] = 2002
    name_a = runtime.player_names.pop(22)
    name_b = runtime.player_names.pop(24)
    runtime.player_names[24] = name_a
    runtime.player_names[23] = name_b
    if reverse_roster:
        runtime.players = [runtime.players[0], runtime.players[2], runtime.players[1]]
    runtime.publication_result = _remote_publication(runtime, module)
    _preserve_remote_publishers_by_agent(runtime.publication_result.snapshot, originals_by_agent)
    changed_owner_b = next(
        cohort
        for cohort in runtime.publication_result.snapshot.cohorts
        if cohort.owner.GetAccountData().AgentData.AgentID == 2002
    )
    changed_owner_b.incarnation = bytes((99,)) + bytes(15)

    destination = context.Refresh()
    owner_a_record = _remote_player_record(destination, module, login_number=24)
    owner_b_record = _remote_player_record(destination, module, login_number=23)

    assert owner_a_record.role is module.CleansingRole.PANIC
    assert owner_a_record.candidate_role is module.CleansingRole.PANIC
    assert owner_b_record.role is module.CleansingRole.UNKNOWN
    assert destination.ready
    assert (module.MemberKind.PLAYER, 22, 22) not in context._remote_player_baselines
    assert context._remote_player_baselines[(module.MemberKind.PLAYER, 24, 24)].publisher == (
        module._publisher_token(
            module._copy_published_cohorts(types.SimpleNamespace(cohorts=(originals_by_agent[2001],)))[0], 1
        )
    )
    assert (module.MemberKind.PLAYER, 22, 22) not in context.GetTransitionBoundary().retired_members
    assert (module.MemberKind.PLAYER, 24, 24) in context.GetTransitionBoundary().retired_members


def test_remote_destination_epoch_change_invalidates_only_affected_player_proof(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, login_number=22, agent_id=2001, role=module.CleansingRole.PANIC)
    _add_remote_player(runtime, module, login_number=23, agent_id=2002, role=module.CleansingRole.INEPTITUDE)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()
    context.Refresh()

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    admitted = context.Refresh()
    assert _remote_player_record(admitted, module, login_number=22).role is module.CleansingRole.PANIC
    assert _remote_player_record(admitted, module, login_number=23).role is module.CleansingRole.INEPTITUDE

    affected_cohort = next(
        cohort
        for cohort in runtime.publication_result.snapshot.cohorts
        if cohort.owner.GetAccountData().AgentData.LoginNumber == 22
    )
    admitted_epoch = affected_cohort.instance_epoch
    affected_cohort.instance_epoch += 1
    changed_epoch = context.Refresh()
    owner_a = _remote_player_record(changed_epoch, module, login_number=22)
    owner_b = _remote_player_record(changed_epoch, module, login_number=23)

    assert owner_a.role is module.CleansingRole.UNKNOWN
    assert owner_a.candidate_role is module.CleansingRole.PANIC
    assert owner_b.role is module.CleansingRole.INEPTITUDE
    assert changed_epoch.ready
    assert (module.MemberKind.PLAYER, 22, 22) not in context._remote_player_baselines

    affected_cohort.instance_epoch = admitted_epoch
    reverted_epoch = context.Refresh()
    assert _remote_player_record(reverted_epoch, module, login_number=22).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(reverted_epoch, module, login_number=22).candidate_role is module.CleansingRole.PANIC
    assert _remote_player_record(reverted_epoch, module, login_number=23).role is module.CleansingRole.INEPTITUDE


def test_remote_player_first_seen_in_explorable_stays_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()

    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(snapshot, module).candidate_role is module.CleansingRole.PANIC


def test_contradictory_explorable_remote_candidate_clears_private_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC
    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.bars[2001] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.publication_result = _remote_publication(runtime, module)

    mismatch = context.Refresh()
    remote = _remote_player_record(mismatch, module)

    assert remote.role is module.CleansingRole.UNKNOWN
    assert remote.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert context._remote_player_baselines == {}


@pytest.mark.parametrize("continuity_change", ("incarnation", "character_uuid", "recovery_epoch"))
def test_remote_publisher_continuity_change_invalidates_player_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], continuity_change: str
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    first = context.Refresh()
    old_generation = _remote_player_record(first, module).remote_provenance_generation
    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.publication_result = _remote_publication(runtime, module)
    cohort = runtime.publication_result.snapshot.cohorts[0]
    owner = cohort.owner.GetAccountData()
    if continuity_change == "incarnation":
        cohort.incarnation = b"new-incarnation!!"
    elif continuity_change == "character_uuid":
        owner.AgentData.UUID = (7777, 1, 0, 0)
        cohort.character_uuid = (7777, 1, 0, 0)
    else:
        runtime.publication_result.snapshot.recovery_epoch = 2

    changed = context.Refresh()
    remote = _remote_player_record(changed, module)

    assert remote.role is module.CleansingRole.UNKNOWN
    assert remote.candidate_role is module.CleansingRole.PANIC
    assert remote.remote_provenance_generation == old_generation + 1


@pytest.mark.parametrize("age_ms,expected", ((4999, True), (5000, False)))
def test_remote_publication_freshness_boundary(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], age_ms: int, expected: bool
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, age_ms=age_ms)

    snapshot = module.CleansingContext().Refresh()

    assert (_remote_player_record(snapshot, module).role is module.CleansingRole.PANIC) is expected


@pytest.mark.parametrize("status", ("busy", "unavailable", "recovery", "sync_failure"))
def test_remote_publication_status_failure_isolated_from_local_stage2(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], status: str
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value=status), snapshot=None)

    snapshot = module.CleansingContext().Refresh()

    assert snapshot.members[0].role is module.CleansingRole.ENERGY_SURGE
    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN
    assert snapshot.ready


def test_remote_publication_exception_and_success_empty_do_not_break_local_recognition(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    context = module.CleansingContext()
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC

    runtime.publication_mutator = lambda: (_ for _ in ()).throw(RuntimeError("publication failed"))
    failed = context.Refresh()
    runtime.publication_mutator = None
    runtime.publication_result = types.SimpleNamespace(
        status=types.SimpleNamespace(value="success"),
        snapshot=types.SimpleNamespace(captured_at_tick64=runtime.publication_now, recovery_epoch=1, cohorts=()),
    )
    empty = context.Refresh()

    assert _remote_player_record(failed, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(empty, module).role is module.CleansingRole.UNKNOWN
    assert failed.members[0].role is module.CleansingRole.ENERGY_SURGE
    assert empty.members[0].role is module.CleansingRole.ENERGY_SURGE


@pytest.mark.parametrize("mutated", ("map", "party", "endpoint"))
def test_opening_closing_runtime_disagreement_suppresses_remote_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], mutated: str
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)

    def mutate() -> None:
        if mutated == "map":
            runtime.map_id += 1
        elif mutated == "party":
            runtime.party_id += 1
        else:
            runtime.local_agent_by_login[22] = 2999

    runtime.publication_mutator = mutate
    snapshot = module.CleansingContext().Refresh()

    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(snapshot, module).reason == "runtime evidence changed during closing"
    assert not snapshot.ready


def test_remote_hero_current_bar_must_agree_with_owner_witness(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    cohort = _setup_remote_hero(runtime, module)
    runtime.witness_skillbars = {(22, 7): _role_bar(runtime, module, module.CleansingRole.PANIC, utility_seed=9000)}
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars=runtime.witness_skillbars)

    snapshot = module.CleansingContext().Refresh()
    hero = _remote_hero_record(snapshot, module)

    assert hero.role is module.CleansingRole.UNKNOWN
    assert hero.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert "does not agree" in hero.reason
    assert cohort.witnesses[0].hero_id == 7


def test_remote_hero_copied_elite_without_supported_original_witness_stays_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module)
    runtime.publication_result = _remote_publication(
        runtime,
        module,
        witness_skillbars={(22, 7): tuple(9000 + index for index in range(8))},
    )

    snapshot = module.CleansingContext().Refresh()
    hero = _remote_hero_record(snapshot, module)

    assert hero.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert hero.role is module.CleansingRole.UNKNOWN
    assert "original witness role is UNKNOWN" in hero.reason


def test_same_hero_id_under_different_remote_owners_is_valid(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module, owner_login=22, owner_agent=2001, hero_id=7, hero_agent=3001)
    _add_remote_player(runtime, module, login_number=23, agent_id=2002, name="Remote 23")
    _add_hero(
        runtime,
        module,
        module.CleansingRole.ENERGY_SURGE,
        hero_id=7,
        agent_id=3002,
        owner_id=23,
    )
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()
    heroes = [member for member in snapshot.members if member.identity.kind is module.MemberKind.HERO]

    assert len(heroes) == 2
    assert {member.identity.owner_id for member in heroes} == {22, 23}
    assert all(member.role is module.CleansingRole.ENERGY_SURGE for member in heroes)


def test_remote_hero_witness_is_matched_by_owner_hero_id_not_old_agent_endpoint(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_hero_record(context.Refresh(), module).role is module.CleansingRole.ENERGY_SURGE

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    hero = runtime.heroes[0]
    hero.agent_id = 4001
    runtime.professions[4001] = int(module.Profession.Mesmer)
    runtime.bars[4001] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    runtime.publication_result = _remote_publication(runtime, module)

    destination = context.Refresh()

    assert _remote_hero_record(destination, module).role is module.CleansingRole.ENERGY_SURGE
    assert _remote_hero_record(destination, module).identity.agent_id == 4001


def test_remote_hero_reownership_requires_a_witness_from_the_new_owner(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_hero_record(context.Refresh(), module).role is module.CleansingRole.ENERGY_SURGE

    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    _add_remote_player(runtime, module, login_number=23, agent_id=2002, name="Remote 23")
    runtime.heroes[0].owner_player_id = 23
    runtime.publication_result = _remote_publication(runtime, module)
    new_owner_cohort = next(
        cohort
        for cohort in runtime.publication_result.snapshot.cohorts
        if cohort.owner.GetAccountData().AgentData.LoginNumber == 23
    )
    new_owner_cohort.witnesses = ()

    reowned = context.Refresh()

    reowned_hero = _remote_hero_record(reowned, module, owner=23)
    assert reowned_hero.role is module.CleansingRole.UNKNOWN
    assert "witness" in reowned_hero.reason


def test_remote_hero_with_unproven_roster_owner_stays_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module)
    runtime.heroes[0].owner_player_id = 23
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()

    unproven_owner_hero = _remote_hero_record(snapshot, module, owner=23)
    assert unproven_owner_hero.role is module.CleansingRole.UNKNOWN
    assert "owner identity is not proven" in unproven_owner_hero.reason


def test_multiple_supported_elites_remain_ambiguous_for_remote_hero(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module)
    hero = runtime.heroes[0]
    bar = list(runtime.bars[hero.agent_id])
    bar[1] = _skill_ids(runtime, module).panic
    runtime.bars[hero.agent_id] = tuple(bar)
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()
    remote_hero = _remote_hero_record(snapshot, module)

    assert remote_hero.role is module.CleansingRole.UNKNOWN
    assert remote_hero.candidate_role is module.CleansingRole.UNKNOWN
    assert "multiple supported" in remote_hero.reason or "does not agree" in remote_hero.reason


@pytest.mark.parametrize("change", ("agent_assignment", "duplicate_agent"))
def test_remote_player_agentid_assignments_must_be_unique_and_not_local(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], change: str
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    if change == "agent_assignment":
        runtime.local_agent_by_login[22] = runtime.agent_id
    else:
        _add_remote_player(runtime, module, login_number=23, agent_id=2001, name="Remote 23")
        runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()

    assert all(
        member.role is module.CleansingRole.UNKNOWN
        for member in snapshot.members
        if member.evidence_source is module.EvidenceSource.REMOTE_PLAYER
    )


@pytest.mark.parametrize("endpoint_kind", ("player", "hero"))
def test_henchman_agentid_conflicts_make_remote_player_or_hero_unknown_without_affecting_local_stage2(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], endpoint_kind: str
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    if endpoint_kind == "player":
        _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
        runtime.henchmen.append(types.SimpleNamespace(agent_id=2001))
    else:
        _setup_remote_hero(
            runtime,
            module,
            owner_role=module.CleansingRole.PANIC,
            hero_role=module.CleansingRole.ENERGY_SURGE,
        )
        runtime.henchmen.append(types.SimpleNamespace(agent_id=3001))
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()
    local = next(
        member
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id == runtime.login_number
    )
    if endpoint_kind == "player":
        collided = _remote_player_record(snapshot, module)
        expected_source = module.EvidenceSource.REMOTE_PLAYER
    else:
        collided = _remote_hero_record(snapshot, module)
        expected_source = module.EvidenceSource.REMOTE_HERO

    assert collided.role is module.CleansingRole.UNKNOWN
    assert collided.evidence_source is expected_source
    assert "conflicting" in collided.reason
    assert local.role is module.CleansingRole.ENERGY_SURGE
    assert snapshot.ready


def test_escaped_or_lossy_remote_names_are_not_authoritative(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC, name=r"\x52emote")
    runtime.publication_result = _remote_publication(runtime, module)
    owner = runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData()
    owner.AgentData.CharacterName = r"\x4Fther"

    snapshot = module.CleansingContext().Refresh()

    assert _remote_player_record(snapshot, module).role is module.CleansingRole.PANIC


def test_remote_publication_loss_after_success_does_not_reuse_last_role(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    first = context.Refresh()
    runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value="busy"), snapshot=None)

    lost = context.Refresh()

    assert _remote_player_record(first, module).role is module.CleansingRole.PANIC
    assert _remote_player_record(lost, module).role is module.CleansingRole.UNKNOWN
    assert lost.members[0].role is module.CleansingRole.ENERGY_SURGE


def test_remote_player_baseline_is_cleared_by_full_invalidation_and_character_switch(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    context = module.CleansingContext()
    runtime.publication_result = _remote_publication(runtime, module)
    context.Refresh()
    assert context._remote_player_baselines

    context.Invalidate()
    assert context._remote_player_baselines == {}

    runtime.publication_result = _remote_publication(runtime, module)
    context.Refresh()
    runtime.ready = False
    runtime.instance_type_override = 2
    context.Refresh()
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.set_identity(12, runtime.account_email, "Mesmer B")
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = context.Refresh()

    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN


def test_remote_publication_failure_does_not_erase_local_hero_stage2_proof(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
    local_hero = _add_hero(
        runtime,
        module,
        module.CleansingRole.BIP,
        hero_id=8,
        agent_id=2002,
    )
    runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value="unavailable"), snapshot=None)

    snapshot = module.CleansingContext().Refresh()
    local_hero_record = next(
        member
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.HERO and member.identity.owner_id == runtime.login_number
    )

    assert local_hero_record.identity.member_id == local_hero.hero_id
    assert local_hero_record.role is module.CleansingRole.BIP
    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN


def test_decoded_v3_cohort_output_drives_remote_owner_and_hero_recognition(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    publication_tests_spec = importlib.util.spec_from_file_location(
        "test_account_publication_for_cleansing", _REPO_ROOT / "tests" / "test_account_publication.py"
    )
    assert publication_tests_spec and publication_tests_spec.loader
    publication_tests = importlib.util.module_from_spec(publication_tests_spec)
    publication_tests_spec.loader.exec_module(publication_tests)
    publication_subject = publication_tests.build_publication_subject(monkeypatch)

    runtime.agent_id = 9000
    runtime.local_agent_by_login = {runtime.login_number: runtime.agent_id, 1: 1000}
    runtime.professions[runtime.agent_id] = int(module.Profession.Mesmer)
    runtime.map_id = 10
    runtime.outpost = False
    runtime.explorable = True
    _add_remote_player(runtime, module, login_number=1, agent_id=1000, role=None, name="Decoded Remote")
    _add_hero(
        runtime,
        module,
        module.CleansingRole.ENERGY_SURGE,
        hero_id=7,
        agent_id=1001,
        owner_id=1,
    )
    runtime.secondaries[1001] = 8
    runtime.bars[1001] = _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
    envelope = publication_tests.envelope_v3(publication_subject, tick=100, instance=1)
    owner = envelope.accounts[0]
    child = envelope.accounts[1]
    owner.AgentData.CharacterName = "Decoded Remote"
    owner.AgentData.Profession[0] = int(module.Profession.Mesmer)
    owner.AgentData.Profession[1] = 0
    child.AgentData.Profession[0] = int(module.Profession.Mesmer)
    child.AgentData.Profession[1] = 8
    for index, skill_id in enumerate(runtime.bars[1001]):
        child.AgentData.Skillbar.Skills[index].Id = skill_id
    witness_bar = runtime.bars[1001]
    envelope.owners[0].witnesses[0].skills[:] = witness_bar
    envelope.owners[0].witnesses[0].primary = int(module.Profession.Mesmer)
    envelope.owners[0].witnesses[0].secondary = 8
    decoded = publication_subject.reader.read_native_account_snapshot_v3(lambda: ("success", 101, bytes(envelope)))
    runtime.publication_result = decoded

    snapshot = module.CleansingContext().Refresh()
    owner_record = _remote_player_record(snapshot, module, login_number=1)
    hero_record = _remote_hero_record(snapshot, module, owner=1, hero_id=7)

    assert owner_record.role is module.CleansingRole.UNKNOWN
    assert owner_record.remote_provenance_generation == 1
    assert hero_record.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert (
        hero_record.role is module.CleansingRole.UNKNOWN
    ), "a Native witness alone cannot create a Python outpost origin in an explorable"
    assert hero_record.evidence_source is module.EvidenceSource.REMOTE_HERO


@pytest.mark.parametrize(
    "defect",
    ("wrong_owner_agent", "wrong_hero_id", "wrong_local_index", "wrong_agent", "missing", "duplicate_child"),
)
def test_remote_hero_child_claims_fail_closed(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], defect: str
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module)
    cohort = runtime.publication_result.snapshot.cohorts[0]
    child = cohort.children[0].GetAccountData()
    if defect == "wrong_owner_agent":
        child.AgentData.OwnerAgentID = 2999
    elif defect == "wrong_hero_id":
        child.AgentData.HeroID = 8
    elif defect == "wrong_local_index":
        child.Key.LocalIndex = 8
    elif defect == "wrong_agent":
        child.AgentData.AgentID = 3999
    elif defect == "missing":
        cohort.children = ()
    elif defect == "duplicate_child":
        cohort.children = (*cohort.children, cohort.children[0])

    snapshot = module.CleansingContext().Refresh()
    hero = _remote_hero_record(snapshot, module)

    expected = module.CleansingRole.ENERGY_SURGE if defect == "missing" else module.CleansingRole.UNKNOWN
    assert hero.role is expected
    assert hero.evidence_source is module.EvidenceSource.REMOTE_HERO


def test_remote_hero_with_matching_owner_witness_is_recognized_and_fenced_from_composition(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module, owner_role=None, hero_role=module.CleansingRole.ENERGY_SURGE)

    snapshot = module.CleansingContext().Refresh()
    hero = _remote_hero_record(snapshot, module)

    assert hero.role is module.CleansingRole.ENERGY_SURGE
    assert hero.candidate_role is module.CleansingRole.ENERGY_SURGE
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.UNKNOWN] == 3
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK


def test_witness_without_current_party_hero_does_not_add_a_hero_member(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _add_remote_player(runtime, module, role=None)
    runtime.publication_result = _remote_publication(runtime, module)

    snapshot = module.CleansingContext().Refresh()

    assert not any(member.identity.kind is module.MemberKind.HERO for member in snapshot.members)


@pytest.mark.parametrize("role_name", ("SOUL_TWISTING", "TAO"))
def test_remote_hero_role_anchors_keep_stage2_safety_checks(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], role_name: str
) -> None:
    runtime, module = cleansing_runtime
    role = getattr(module.CleansingRole, role_name)
    _setup_remote_hero(runtime, module, hero_role=role)
    hero = runtime.heroes[0]
    if role is module.CleansingRole.SOUL_TWISTING:
        runtime.bars[hero.agent_id] = (_skill_ids(runtime, module).soul_twisting, *tuple(9000 + i for i in range(7)))
    else:
        bar = list(runtime.bars[hero.agent_id])
        bar[1] = 9999
        runtime.bars[hero.agent_id] = tuple(bar)
        runtime.skill_type_errors.add(9999)
        runtime.skill_type_errors.update(bar[2:])

    runtime.publication_result = _remote_publication(runtime, module)
    snapshot = module.CleansingContext().Refresh()
    remote_hero = _remote_hero_record(snapshot, module)

    assert remote_hero.role is module.CleansingRole.UNKNOWN
    if role is module.CleansingRole.SOUL_TWISTING:
        assert "Shelter" in remote_hero.reason or "Union" in remote_hero.reason
    else:
        assert "unavailable" in remote_hero.reason


@pytest.mark.parametrize("remote_role", ("PANIC", "HEALING_BURST", "TAO"))
def test_stage3_composition_fence_rejects_each_remote_substitution_family(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], remote_role: str
) -> None:
    _, module = cleansing_runtime
    roles = [
        module.CleansingRole.HEROIC_REFRAIN,
        module.CleansingRole.BIP,
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        getattr(module.CleansingRole, remote_role),
    ]
    members = list(_member_records(module, roles))
    remote = members[-1]
    members[-1] = module.MemberRecord(
        identity=remote.identity,
        role=remote.role,
        candidate_role=remote.candidate_role,
        evidence_source=module.EvidenceSource.REMOTE_PLAYER,
        reason="recognized remote role",
    )

    composition = module.match_supported_composition(members, declared_party_size=8)

    assert composition.status is module.CompositionStatus.FALLBACK
    assert len(members) == composition.member_count == 8
    assert dict(composition.role_counts)[module.CleansingRole.UNKNOWN] == 1


class _ProbeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def read(self) -> float:
        return self.value

    def read_ns(self) -> int:
        return int(self.value * 1_000_000_000)

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _prepare_stage3_probe_harness(
    monkeypatch: pytest.MonkeyPatch,
    runtime: _Runtime,
    module: types.ModuleType,
    *,
    omit_outpost_hero_child: bool = False,
    load_probe: bool = True,
    role_distribution: Literal["remote_es", "remote_bip"] = "remote_es",
    remote_player_role: Any | None = None,
) -> tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime]:
    if role_distribution == "remote_bip":
        local_roles = [
            module.CleansingRole.HEROIC_REFRAIN,
            module.CleansingRole.SOUL_TWISTING,
            module.CleansingRole.INEPTITUDE,
            module.CleansingRole.ENERGY_SURGE,
            module.CleansingRole.ENERGY_SURGE,
            module.CleansingRole.ENERGY_SURGE,
        ]
        expected_remote_player_role = module.CleansingRole.BIP
    else:
        local_roles = [
            module.CleansingRole.HEROIC_REFRAIN,
            module.CleansingRole.BIP,
            module.CleansingRole.SOUL_TWISTING,
            module.CleansingRole.INEPTITUDE,
            module.CleansingRole.ENERGY_SURGE,
            module.CleansingRole.ENERGY_SURGE,
        ]
        expected_remote_player_role = module.CleansingRole.ENERGY_SURGE

    _configure_team(
        runtime,
        module,
        local_roles,
    )
    _setup_remote_hero(
        runtime,
        module,
        owner_agent=4001,
        owner_role=expected_remote_player_role if remote_player_role is None else remote_player_role,
        hero_agent=5001,
        hero_role=module.CleansingRole.ENERGY_SURGE,
    )
    if omit_outpost_hero_child:
        runtime.publication_result.snapshot.cohorts[0].children = ()

    context = module.CleansingContext()
    corelib = sys.modules["Py4GWCoreLib"]
    runtime_cache = corelib.GLOBAL_CACHE
    global_cache_type = _load_global_cache_owner(monkeypatch)
    global_cache = object.__new__(global_cache_type)
    global_cache.CleansingContext = context
    global_cache.Party = runtime_cache.Party
    global_cache.Skill = runtime_cache.Skill
    global_cache.ShMem = runtime_cache.ShMem
    global_cache.Coroutines = []

    class _AlwaysExpiredTimer:
        def IsExpired(self) -> bool:
            return True

        def Reset(self) -> None:
            return None

    global_cache._TrottleTimers = types.SimpleNamespace(
        _75ms=_AlwaysExpiredTimer(),
        _500ms=_AlwaysExpiredTimer(),
        _150ms=_AlwaysExpiredTimer(),
    )
    global_cache.Party._update_cache = lambda: None
    global_cache._RawItemCache = types.SimpleNamespace(update=lambda: None)
    global_cache.Item = types.SimpleNamespace(_update_cache=lambda: None)
    global_cache.Camera = types.SimpleNamespace(_update_cache=lambda: None)
    global_cache.SkillBar = types.SimpleNamespace(_update_cache=lambda: None)
    sys.modules["Py4GWCoreLib"].__dict__["GLOBAL_CACHE"] = global_cache
    upkeeper, _loot_filters = _load_environment_upkeeper(monkeypatch, runtime, global_cache)
    probe = _load_stage3_evidence_probe(monkeypatch, global_cache) if load_probe else None
    clock = _ProbeClock()
    monkeypatch.setattr(module, "_transition_clock", clock.read)
    monkeypatch.setitem(corelib.Map.GetLoadingObservation.__globals__, "monotonic", clock.read)
    diagnostics = sys.modules["Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics"]
    monkeypatch.setattr(diagnostics, "monotonic_ns", clock.read_ns)
    if probe is not None:
        monkeypatch.setattr(probe, "monotonic", clock.read)
        monkeypatch.setattr(probe, "monotonic_ns", clock.read_ns)
    return context, global_cache, upkeeper, probe, clock, diagnostics, runtime


def _stage3_retained_party_cache(monkeypatch: pytest.MonkeyPatch, cache: Any, *, loaded: bool = False) -> Any:
    """Keep readiness stale until the production PartyCache calls GetContext."""
    py_party = sys.modules["PyParty"]
    native_party_type = py_party.PyParty
    hero_agent = cache.Party.Heroes.GetHeroAgentIDByPartyPosition

    class _RetainedParty(native_party_type):
        def __init__(self) -> None:
            self.loaded = loaded
            self.updates = 0

        @property
        def is_party_loaded(self) -> bool:
            return self.loaded

        def GetContext(self) -> None:
            assert py_party.get_is_party_loaded() is True, "party update before Native readiness"
            self.updates += 1
            self.loaded = True

        def GetHeroAgentID(self, position: int) -> int:
            return int(hero_agent(position))

    monkeypatch.setattr(py_party, "PyParty", _RetainedParty)
    corelib = sys.modules["Py4GWCoreLib"]
    monkeypatch.setattr(corelib, "Party", types.SimpleNamespace(), raising=False)
    party_module = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.PartyCache",
        _REPO_ROOT / "Py4GWCoreLib" / "GlobalCache" / "PartyCache.py",
    )
    cache.Party = party_module.PartyCache(None)
    return cache.Party._party_instance


def test_stage3_party_bootstrap_recovers_through_upkeeper_without_priming(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    context, cache, upkeeper, _probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module, load_probe=False
    )
    retained = _stage3_retained_party_cache(monkeypatch, cache)
    assert runtime.party_size == 8 and runtime.party_loaded
    assert not cache.Party.IsPartyLoaded() and retained.updates == 0
    assert context.CaptureEnvironment().readable, "Native-ready outpost must bootstrap stale PartyCache"

    upkeeper.main()

    snapshot = context.GetSnapshot()
    assert retained.updates == 1 and cache.Party.IsPartyLoaded()
    assert context.GetTransitionBoundary().completed_refresh == 1
    assert snapshot.ready and len(snapshot.members) == 8, snapshot.reason
    assert context._remote_player_baselines and context._baselines
    assert all(member.role is not module.CleansingRole.UNKNOWN for member in snapshot.members)


@pytest.mark.parametrize("readiness", (False, None, "failure", "missing", 1))
@pytest.mark.parametrize("established", (False, True))
def test_stage3_party_bootstrap_rejects_unready_or_unavailable_native_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    readiness: Any,
    established: bool,
) -> None:
    runtime, module = cleansing_runtime
    context, cache, upkeeper, _probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module, load_probe=False
    )
    retained = _stage3_retained_party_cache(monkeypatch, cache, loaded=True)
    if established:
        upkeeper.main()
        assert context.GetSnapshot().ready
    updates = retained.updates
    completed = context.GetTransitionBoundary().completed_refresh
    py_party = sys.modules["PyParty"]

    def observe_readiness() -> Any:
        if readiness == "failure":
            raise RuntimeError("Native party readiness unavailable")
        return readiness

    if readiness == "missing":
        monkeypatch.delattr(py_party, "get_is_party_loaded")
    else:
        monkeypatch.setattr(py_party, "get_is_party_loaded", observe_readiness)

    def forbidden() -> Any:
        pytest.fail(f"unsafe recognition read with Native readiness={readiness!r}")

    monkeypatch.setattr(context, "_refresh_from_runtime", forbidden)
    monkeypatch.setattr(sys.modules["Py4GWCoreLib"].Agent, "GetAgentByID", forbidden)
    for _ in range(3):
        upkeeper.main()
    snapshot = context.GetSnapshot()
    assert not snapshot.ready and snapshot.members == (), (readiness, snapshot)
    assert retained.updates == updates
    assert context.GetTransitionBoundary().completed_refresh == completed


def test_stage3_party_bootstrap_observation_preserves_refresh_throttling(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    context, cache, upkeeper, _probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module, load_probe=False
    )
    retained = _stage3_retained_party_cache(monkeypatch, cache)
    expired = [False]
    timer = types.SimpleNamespace(IsExpired=lambda: expired[0], Reset=lambda: None)
    cache._TrottleTimers = types.SimpleNamespace(_75ms=timer, _150ms=timer, _500ms=timer)
    for _ in range(5):
        upkeeper.main()
    assert context.GetTransitionBoundary().observation.readable
    assert retained.updates == context.GetTransitionBoundary().completed_refresh == 0
    expired[0] = True
    upkeeper.main()
    assert retained.updates == context.GetTransitionBoundary().completed_refresh == 1
    assert context.GetSnapshot().ready
    expired[0] = False
    for _ in range(5):
        upkeeper.main()
    assert retained.updates == context.GetTransitionBoundary().completed_refresh == 1


@pytest.mark.parametrize(
    "defect", ("map", "char", "world", "instance_info", "cinematic", "map_ready", "player", "identity", "uuid", "type")
)
def test_stage3_party_bootstrap_keeps_environment_prerequisites(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    runtime, module = cleansing_runtime
    context, cache, upkeeper, _probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module, load_probe=False
    )
    retained = _stage3_retained_party_cache(monkeypatch, cache)
    if defect in ("map", "char", "world", "instance_info"):
        runtime.missing_map_contexts.add(defect)
    elif defect == "cinematic":
        runtime.cinematic = True
    elif defect == "map_ready":
        runtime.ready = False
    elif defect == "player":
        monkeypatch.setattr(sys.modules["Py4GWCoreLib"].Player, "IsPlayerLoaded", lambda: False)
    elif defect == "identity":
        runtime.account_email = ""
    elif defect == "uuid":
        runtime.local_uuid = (0, 0, 0, 0)
    else:
        runtime.instance_type_override = 99

    def forbidden() -> bool:
        pytest.fail(f"Native party readiness queried before environment prerequisite={defect}")

    monkeypatch.setattr(sys.modules["PyParty"], "get_is_party_loaded", forbidden)
    upkeeper.main()
    assert not context.GetSnapshot().ready and context.GetSnapshot().members == ()
    assert retained.updates == context.GetTransitionBoundary().completed_refresh == 0


@pytest.mark.parametrize("finish", ("recover", "expire"))
def test_stage3_party_bootstrap_preserves_strict_loading_and_fixed_transition_deadline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, finish: str
) -> None:
    runtime, module = cleansing_runtime
    context, cache, upkeeper, _probe, clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module, load_probe=False
    )
    retained = _stage3_retained_party_cache(monkeypatch, cache)
    upkeeper.main()
    assert context.GetSnapshot().ready
    original_remote = dict(context._remote_player_baselines)
    original_local = dict(context._baselines)
    runtime.party_loaded = False
    upkeeper.main()
    boundary = context.GetTransitionBoundary()
    assert boundary.phase is module.TransitionPhase.WAITING_FOR_LOADING
    assert boundary.deadline == clock.read() + 60.0 and boundary.loading is None
    deadline = boundary.deadline
    runtime.instance_type_override = 2
    runtime.missing_map_contexts.add("world")
    upkeeper.main()
    assert context.GetTransitionBoundary().loading is None, "missing context cannot prove Loading"
    runtime.missing_map_contexts.clear()
    clock.advance(1.0)

    def forbidden() -> bool:
        pytest.fail("Native party readiness queried during Loading")

    with monkeypatch.context() as loading_patch:
        loading_patch.setattr(sys.modules["PyParty"], "get_is_party_loaded", forbidden)
        upkeeper.main()
    boundary = context.GetTransitionBoundary()
    assert boundary.phase is module.TransitionPhase.LOADING_CONFIRMED
    assert boundary.loading is not None and boundary.loading.loading
    assert all(boundary.loading.contexts) and boundary.loading.raw_instance_type == 2
    loading = boundary.loading
    runtime.instance_type_override = None
    runtime.map_id, runtime.outpost, runtime.explorable = 2, False, True
    clock.advance(1.0)
    upkeeper.main()
    assert retained.updates == 1 and context.GetTransitionBoundary().completed_refresh == 1
    assert not context.GetSnapshot().ready and context.GetSnapshot().members == ()
    assert context._remote_player_baselines == original_remote and context._baselines == original_local
    assert context.GetTransitionBoundary().deadline == deadline
    assert context.GetTransitionBoundary().loading is loading
    if finish == "expire":
        clock.value = deadline
        upkeeper.main()
        assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED
        assert not context._remote_player_baselines and not context._baselines
    else:
        runtime.party_loaded = True
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
        upkeeper.main()
        assert retained.updates == 2 and context.GetTransitionBoundary().completed_refresh == 2
        assert context.GetSnapshot().ready
        assert context.GetTransitionBoundary().phase is module.TransitionPhase.DESTINATION_VERIFIED
        assert context.GetTransitionBoundary().deadline == deadline


def _probe_enter_outpost(harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime]) -> None:
    _context, _cache, upkeeper, probe, _clock, _diagnostics, _runtime = harness
    upkeeper.main()
    probe.update()


def _probe_enter_loading(
    harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime], *, repeated_callbacks: int = 1
) -> None:
    _context, _cache, upkeeper, probe, clock, _diagnostics, runtime = harness
    clock.advance(0.26)
    upkeeper.main()
    probe.update()
    runtime.ready = False
    runtime.instance_type_override = 2
    for _ in range(repeated_callbacks):
        upkeeper.main()
    clock.advance(0.26)
    probe.update()


def _probe_enter_destination(
    harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime],
    *,
    omit_remote_hero_child: bool = False,
    witness_skillbars: dict[tuple[int, int], tuple[int, ...]] | None = None,
    publisher_identity: Any | None = None,
    poll_probe: bool = True,
    include_local: bool = False,
) -> None:
    _context, _cache, upkeeper, probe, clock, _diagnostics, runtime = harness
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    publication = _remote_publication(
        runtime,
        sys.modules["Py4GWCoreLib.GlobalCache.CleansingContext"],
        witness_skillbars=witness_skillbars,
        include_local=include_local,
    )
    if publisher_identity is not None:
        _preserve_publication_publisher_identity_for_probe(publication, publisher_identity)
    runtime.publication_result = publication
    if omit_remote_hero_child:
        runtime.publication_result.snapshot.cohorts[0].children = ()
    upkeeper.main()
    clock.advance(0.26)
    if poll_probe:
        probe.update()


def _probe_sample_destination(harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime]) -> None:
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    clock.advance(1.01)
    upkeeper.main()
    probe.update()


def _probe_poll_destination(harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime]) -> None:
    _context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    clock.advance(1.01)
    probe.update()


def test_stage3_probe_direct_console_exec_needs_no_registered_module_and_stays_passive(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _context_module = cleansing_runtime
    context, _cache, _upkeeper, _probe, _clock, diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, _context_module
    )
    source_path = _REPO_ROOT / "Widgets" / "Coding" / "Debug" / "Py4GW" / "Stage 3 Evidence Probe.py"
    console_namespace: dict[str, Any] = {
        "__name__": "unregistered_stage3_console_probe",
        "__file__": "<string>",
    }

    exec(compile(source_path.read_text(encoding="utf-8"), "<string>", "exec"), console_namespace)

    assert "unregistered_stage3_console_probe" not in sys.modules
    assert console_namespace["_attempt_id"] is None
    assert console_namespace["_outpost_baseline"] is None
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
    assert capsys.readouterr().out == ""


def test_stage3_probe_widget_enable_emits_bounded_activation_to_normal_console(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, context_module = cleansing_runtime
    context, _cache, _upkeeper, _probe, _clock, diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, context_module, load_probe=False
    )
    widget, module_name = _instantiate_stage3_browser_widget(monkeypatch)
    probe = widget.module
    assert probe is not None
    console_logs = sys.modules["PySystem"].stage3_console_logs
    try:
        widget.enable()

        assert widget.enabled
        assert context_module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
        assert probe._cleansing_context_module is context_module
        assert context.Refresh.__func__.__globals__ is context_module.__dict__
        assert probe._attempt_id is None
        assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
        assert len(console_logs) == 1
        sender, message, message_type = console_logs[0]
        assert sender == probe.MODULE_NAME
        assert message == "STAGE3_EVIDENCE_V1 event=activation state=enabled source=widget_browser"
        assert message_type == sys.modules["PySystem"].Console.MessageType.Info
        assert probe._lines == 1
        assert probe._characters == len(message) + 1
        assert len(message) <= probe._MAX_OUTPUT_CHARACTERS
        assert "@example.test" not in message and "Mesmer A" not in message
        assert capsys.readouterr().out.splitlines() == [message]
    finally:
        if widget.enabled:
            widget.disable()
        sys.modules.pop(module_name, None)


def test_stage3_probe_widget_update_establishes_initial_outpost_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, context_module = cleansing_runtime
    context, _cache, upkeeper, _probe, clock, diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, context_module, load_probe=False
    )
    widget, module_name = _instantiate_stage3_browser_widget(monkeypatch)
    probe = widget.module
    assert probe is not None
    monkeypatch.setattr(probe, "monotonic", clock.read)
    monkeypatch.setattr(probe, "monotonic_ns", clock.read_ns)
    console_logs = sys.modules["PySystem"].stage3_console_logs
    try:
        widget.enable()
        clock.advance(0.26)
        upkeeper.main()
        _run_stage3_browser_update(widget)

        assert probe._attempt_id is not None
        assert probe._outpost_baseline is not None
        assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) == probe._attempt_id
        assert any("event=activation state=enabled" in message for _, message, _ in console_logs)
        assert any("event=outpost created roster=8/8" in message for _, message, _ in console_logs)
        baseline_lines = tuple(message for _, message, _ in console_logs if "event=outpost created" in message)
        assert len(baseline_lines) == 1
        # Optional details wait until finalization releases unused evidence capacity.
        widget.disable()
        detail_lines = tuple(message for _, message, _ in console_logs if "event=outpost_detail " in message)
        assert len(baseline_lines) == 1
        assert len(detail_lines) == probe._outpost_detail_report_count == 1
        assert "L=LP:HR/1,H1:BiP/1,H2:ST/1,H3:IN/1,H4:ES/1,H5:ES/1" in detail_lines[0]
        assert "witness=proven/ES" in detail_lines[0]
    finally:
        if widget.enabled:
            widget.disable()
        sys.modules.pop(module_name, None)


def test_stage3_probe_reports_initial_refresh_wait_and_remote_role_blocker(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, context_module = cleansing_runtime
    context, _cache, upkeeper, _probe, clock, diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, context_module, load_probe=False
    )
    widget, module_name = _instantiate_stage3_browser_widget(monkeypatch)
    probe = widget.module
    assert probe is not None
    monkeypatch.setattr(probe, "monotonic", clock.read)
    monkeypatch.setattr(probe, "monotonic_ns", clock.read_ns)
    console_logs = sys.modules["PySystem"].stage3_console_logs
    try:
        widget.enable()
        clock.advance(0.26)
        _run_stage3_browser_update(widget)
        clock.advance(1.01)
        _run_stage3_browser_update(widget)

        assert probe._attempt_id is None
        assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
        assert sum("event=outpost_wait" in message for _, message, _ in console_logs) == 0

        remote_agent = runtime.local_agent_by_login[22]
        runtime.bars[remote_agent] = tuple(9000 + index for index in range(8))
        runtime.publication_result = _remote_publication(runtime, context_module)
        upkeeper.main()
        clock.advance(0.26)
        _run_stage3_browser_update(widget)

        assert len(context.GetSnapshot().members) == 8
        assert probe._attempt_id is None
        assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
        widget.disable()
        # The current role blocker takes priority over the transient refresh wait.
        assert not any("wait=refresh_pending" in message for _, message, _ in console_logs)
        assert any("wait=remote_role" in message for _, message, _ in console_logs)
    finally:
        if widget.enabled:
            widget.disable()
        sys.modules.pop(module_name, None)


def test_stage3_probe_widget_discovery_load_does_not_start_collection(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _context_module = cleansing_runtime
    context, _cache, _upkeeper, _probe, _clock, diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, _context_module
    )
    widget, module_name = _instantiate_stage3_browser_widget(monkeypatch)
    try:
        assert widget.widget_path == "Coding/Debug/Py4GW"
        assert widget.name == "Stage 3 Evidence Probe"
        assert not widget.enabled
        assert widget.module is not None
        assert not _context_module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
        assert sys.modules.get(module_name) is widget.module
        assert widget.module._attempt_id is None
        assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
        assert capsys.readouterr().out == ""
    finally:
        if widget.enabled:
            widget.disable()
        sys.modules.pop(module_name, None)


def test_stage3_probe_widget_enable_disable_and_reenable_use_fresh_attempts(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, context_module = cleansing_runtime
    context, _cache, upkeeper, _probe, clock, diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, context_module, load_probe=False
    )
    widget, module_name = _instantiate_stage3_browser_widget(monkeypatch)
    probe = widget.module
    assert probe is not None
    monkeypatch.setattr(probe, "monotonic", clock.read)
    monkeypatch.setattr(probe, "monotonic_ns", clock.read_ns)
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    try:
        widget.enable()
        assert widget.enabled
        assert probe._attempt_id is None
        clock.advance(0.26)
        upkeeper.main()
        _run_stage3_browser_update(widget)
        first_attempt_id = probe._attempt_id
        assert first_attempt_id is not None
        assert recorder.active_attempt_id(context) == first_attempt_id

        clock.advance(0.26)
        upkeeper.main()
        _run_stage3_browser_update(widget)
        runtime.ready = False
        runtime.instance_type_override = 2
        upkeeper.main()
        upkeeper.main()
        clock.advance(0.26)
        _run_stage3_browser_update(widget)
        assert probe._loading_event is not None

        runtime.ready = True
        runtime.instance_type_override = None
        runtime.map_id = 2
        runtime.outpost = False
        runtime.explorable = True
        runtime.publication_result = _remote_publication(runtime, context_module)
        upkeeper.main()
        clock.advance(0.26)
        _run_stage3_browser_update(widget)
        assert probe._destination_samples == 1

        widget.disable()
        assert not widget.enabled
        assert not context_module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
        assert probe._finished
        assert recorder.active_attempt_id(context) is None
        upkeeper.main()
        assert recorder.active_attempt_id(context) is None

        runtime.map_id = 1
        runtime.outpost = True
        runtime.explorable = False
        runtime.publication_result = _remote_publication(runtime, context_module)
        upkeeper.main()
        widget.enable()
        assert widget.enabled
        assert not probe._finished
        assert probe._started_at == clock.value
        assert probe._outpost_baseline is None
        assert probe._candidate_loading_event is None
        assert probe._loading_event is None
        assert probe._destination_samples == 0
        assert probe._outpost_report_stage == 0

        _run_stage3_browser_update(widget)
        clock.advance(0.26)
        upkeeper.main()
        _run_stage3_browser_update(widget)
        second_attempt_id = probe._attempt_id
        assert second_attempt_id is not None and second_attempt_id != first_attempt_id
        assert recorder.active_attempt_id(context) == second_attempt_id
        assert recorder.read_events(second_attempt_id, 0).events == ()
        refresh_events = recorder.read_refresh_events(second_attempt_id, 0).events
        assert len(refresh_events) == 1
        assert refresh_events[0].attempt_id == second_attempt_id
        assert refresh_events[0].evidence is not None
        assert refresh_events[0].evidence.snapshot.ready
        assert refresh_events[0].evidence.snapshot.map_id == 1

        widget.disable()
        output = capsys.readouterr().out
        assert "result=INCONCLUSIVE reason=widget_disabled" in output
        assert "@example.test" not in output
        assert "Mesmer A" not in output and "Remote 22" not in output
    finally:
        if widget.enabled:
            widget.disable()
        sys.modules.pop(module_name, None)


def test_stage3_probe_startup_cleanup_errors_do_not_leak_private_details(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, _context_module = cleansing_runtime
    context, _cache, upkeeper, _probe, clock, diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, _context_module, load_probe=False
    )
    widget, module_name = _instantiate_stage3_browser_widget(monkeypatch)
    probe = widget.module
    assert probe is not None
    monkeypatch.setattr(probe, "monotonic", clock.read)
    monkeypatch.setattr(probe, "monotonic_ns", clock.read_ns)
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    original_end = recorder.end
    private_marker = "private-account@example.invalid"

    def fail_end(_attempt_id: int) -> None:
        raise RuntimeError(private_marker)

    attempt_id: int | None = None
    try:
        widget.enable()
        clock.advance(0.26)
        upkeeper.main()
        _run_stage3_browser_update(widget)
        attempt_id = probe._attempt_id
        assert attempt_id is not None
        monkeypatch.setattr(recorder, "end", fail_end)

        widget.disable()
        assert probe._finished
        widget.enable()
        assert not probe._finished
        assert probe._attempt_id is None

        output = capsys.readouterr().out
        assert "result=INCONCLUSIVE reason=widget_disabled" in output
        assert private_marker not in output
    finally:
        monkeypatch.setattr(recorder, "end", original_end)
        if attempt_id is not None:
            original_end(attempt_id)
        if widget.enabled:
            widget.disable()
        sys.modules.pop(module_name, None)


def _queue_stage3_destination_refresh(
    harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime],
    *,
    delay_seconds: float = 1.01,
) -> None:
    _context, _cache, upkeeper, _probe, clock, _diagnostics, _runtime = harness
    clock.advance(delay_seconds)
    upkeeper.main()


def _extend_stage3_probe_test_lease(
    harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostics = harness[5]
    # Historical callers needed a longer rolling lease. The absolute deadline
    # already covers these scenarios and must remain the production 180 seconds.
    assert diagnostics._ATTEMPT_LEASE_NS == 180_000_000_000


def _fresh_stage3_outpost_context(harness: Any, module: Any) -> Any:
    runtime = harness[-1]
    fields = ("map_id", "outpost", "explorable", "ready", "instance_type_override", "publication_result")
    saved = tuple(getattr(runtime, name) for name in fields)
    try:
        runtime.map_id, runtime.outpost, runtime.explorable = 1, True, False
        runtime.ready, runtime.instance_type_override = True, None
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
        context = module.CleansingContext()
        assert context.Refresh().ready
        return context
    finally:
        for name, value in zip(fields, saved):
            setattr(runtime, name, value)


def test_stage3_probe_uses_production_role_counts_and_accepts_omitted_hero_child(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, omit_outpost_hero_child=True)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness

    _probe_enter_outpost(harness)
    snapshot = context.GetSnapshot()
    remote_hero = _remote_hero_record(snapshot, module)

    assert snapshot.ready and len(snapshot.members) == snapshot.composition.member_count == 8
    assert snapshot.composition.declared_party_size == 8
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.UNKNOWN] == 2
    assert remote_hero.role is module.CleansingRole.ENERGY_SURGE
    assert "qualified owner outpost witness" in remote_hero.reason
    assert context._remote_player_baselines
    assert probe._attempt_id is not None, "outpost acceptance must not require hero role recognition"
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) == probe._attempt_id
    probe.on_disable()
    output = capsys.readouterr().out
    assert "created roster=8/8" in output
    assert "P=ES pub=1 base=1" in output
    assert "H=ES" in output
    assert "witness=proven/ES" in output
    assert "stage4=FALLBACK u=2" in output
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None


def test_stage3_probe_records_actual_upkeeper_forwarding_and_requires_three_stable_samples(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness

    _probe_enter_outpost(harness)
    _probe_enter_loading(harness, repeated_callbacks=2)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_events(attempt_id, 0)
    assert batch.active and not batch.overflowed and len(batch.events) == 2
    first, second = batch.events
    assert first.forwarded_loading and first.transition_latched is True
    assert first.before_ready and first.before_map_id == 1
    assert first.pre_forward_refresh_matches_attempt
    assert first.pre_forward_refresh_matches_snapshot
    assert first.after_revision > first.before_revision
    assert first.after_lifecycle_epoch == first.before_lifecycle_epoch + 1
    assert second.forwarded_loading and second.transition_latched is True
    assert second.before_lifecycle_epoch == second.after_lifecycle_epoch == first.after_lifecycle_epoch

    _probe_enter_destination(harness)
    assert probe._destination_samples == 1
    _probe_sample_destination(harness)
    assert probe._destination_samples == 2 and not probe._finished
    refresh_batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, 0)
    destination_refreshes = tuple(
        event for event in refresh_batch.events if event.evidence is not None and event.evidence.snapshot.map_id == 2
    )
    assert len(destination_refreshes) == 2
    assert len({event.sequence for event in destination_refreshes}) == 2
    assert len({event.evidence.snapshot.revision for event in destination_refreshes if event.evidence}) == 1
    _probe_sample_destination(harness)

    output = capsys.readouterr().out
    assert probe._finished
    assert "event=loading seq=" in output and "map=1" in output
    assert "latch=1" in output
    assert "witness=proven" in output
    assert "event=destination_sample 2/3" in output
    destination_lines = tuple(line for line in output.splitlines() if "event=destination_sample" in line)
    refresh_sequences = tuple(line.split("refresh=", 1)[1].split(" ", 1)[0] for line in destination_lines)
    assert len(destination_lines) == len(set(refresh_sequences)) == 3, output
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output, output
    assert "witness=proven/ES" in output
    assert "roles=ES/ES" in output
    assert "c=1/1/1" in output
    assert "@example.test" not in output
    assert "Mesmer A" not in output and "Remote 22" not in output
    assert "1001" not in output and "2001" not in output and "3001" not in output
    probe_lines = tuple(line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 "))
    assert len(probe_lines) <= probe._MAX_OUTPUT_LINES
    assert sum(len(line) + 1 for line in probe_lines) <= probe._MAX_OUTPUT_CHARACTERS


def _assert_stage3_output_budget(probe: Any, output: str) -> tuple[str, ...]:
    records = tuple(line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 "))
    assert len(records) == probe._lines <= 24, output
    assert sum(len(line) + 1 for line in records) == probe._characters <= probe._MAX_OUTPUT_CHARACTERS, output
    finals = tuple(line for line in records if "event=final " in line)
    assert len(finals) == 1 and records[-1] == finals[0], output
    return records


def _seed_stage3_probe_counters(harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime], seed: int) -> None:
    context, _cache, _upkeeper, _probe, _clock, diagnostics, _runtime = harness
    context._revision = seed
    context._lifecycle_epoch = seed
    context._completed_refresh = max(0, seed - 1)
    context._stage3_evidence_sequence = seed
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    recorder._next_sequence = seed
    recorder._next_refresh_sequence = seed


def _queue_stage3_remote_player_contradiction(
    harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime], module: types.ModuleType
) -> None:
    # Inject the contradiction at the Native/runtime boundary, so the owner
    # records it. Editing a passive recorder copy cannot create authority.
    runtime = harness[6]
    owner = next(player for player in runtime.players if player.login_number != runtime.login_number)
    agent_id = runtime.local_agent_by_login[owner.login_number]
    old_bar, old_publication = runtime.bars[agent_id], runtime.publication_result
    runtime.bars[agent_id] = _role_bar(runtime, module, module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module)
    _queue_stage3_destination_refresh(harness, delay_seconds=0.26)
    runtime.bars[agent_id], runtime.publication_result = old_bar, old_publication


@pytest.mark.parametrize("seed", (999_999_999, (1 << 64) - 100))
def test_stage3_probe_large_counters_keep_all_required_records(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    seed: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    probe.on_enable()
    _seed_stage3_probe_counters(harness, seed)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    output = capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    samples = tuple(line for line in records if "event=destination_sample " in line)
    assert len(samples) == 3, output
    refresh_texts = tuple(line.split("refresh=", 1)[1].split()[0] for line in samples)
    sequences = tuple(int(value[2:], 36) if value.startswith("0z") else int(value) for value in refresh_texts)
    assert sequences == (seed + 2, seed + 3, seed + 4), output
    assert probe._destination_last_refresh_sequence == sequences[-1]
    loading = probe._loading_event
    assert loading is not None and loading.before_revision == seed + 1
    assert loading.before_lifecycle_epoch == seed
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in records[-1], output


@pytest.mark.parametrize("sample_count", (1, 2))
def test_stage3_probe_timeout_prints_each_valid_partial_sample(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_count: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe, clock = harness[3:5]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    sequences = [probe._destination_last_refresh_sequence]
    if sample_count == 2:
        _probe_sample_destination(harness)
        sequences.append(probe._destination_last_refresh_sequence)
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    output = capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    samples = tuple(line for line in records if "event=destination_sample " in line)
    assert len(samples) == sample_count, output
    assert [int(line.split("refresh=", 1)[1].split()[0]) for line in samples] == sequences, output
    assert "result=INCONCLUSIVE reason=stable_destination_samples_incomplete" in records[-1], output
    assert f"samples={sample_count}/3" in records[-1], output
    assert "FULL_SUCCESS" not in output, output


@pytest.mark.parametrize("seed", (0, 999_999_999, (1 << 64) - 100))
@pytest.mark.parametrize("sample_count", (1, 3))
def test_stage3_probe_long_failure_verdict_survives_buffered_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    seed: int,
    sample_count: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    probe.on_enable()
    _seed_stage3_probe_counters(harness, seed)
    harness[5].STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._next_attempt_id = max(9999, seed)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    if sample_count == 3:
        _queue_stage3_destination_refresh(harness)
        _queue_stage3_destination_refresh(harness)
    _queue_stage3_remote_player_contradiction(harness, module)
    probe.update()
    output = capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert "result=FAILURE reason=remote_player_role_contradicts_outpost_baseline" in records[-1], output
    assert len([line for line in records if "event=destination_sample " in line]) == sample_count, output
    assert "FULL_SUCCESS" not in output, output


def test_stage3_probe_evaluates_a_complete_buffered_batch_before_success(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, _clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    assert probe._destination_samples == 1
    attempt_id = probe._attempt_id
    assert attempt_id is not None

    cursor = probe._last_refresh_sequence
    _queue_stage3_destination_refresh(harness)
    _queue_stage3_destination_refresh(harness)
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    outpost_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills
    runtime.bars[remote_hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): outpost_witness})
    _queue_stage3_destination_refresh(harness, delay_seconds=0.16)

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    sequences = tuple(event.sequence for event in batch.events)
    assert batch.active and not batch.overflowed and len(batch.events) == 3
    assert sequences == tuple(sorted(set(sequences)))
    records = tuple(
        _remote_hero_record(event.evidence.snapshot, module) for event in batch.events if event.evidence is not None
    )
    assert len(records) == 3
    assert [record.role for record in records] == [
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.UNKNOWN,
    ]
    assert records[-1].candidate_role is module.CleansingRole.PANIC
    latest_event = batch.events[-1]
    assert latest_event.evidence is not None
    latest_evidence = probe._snapshot_evidence(
        latest_event.evidence.snapshot,
        context,
        latest_event.evidence,
    )
    assert probe._classify_destination(latest_evidence, probe._outpost_baseline) == (
        "FAILURE",
        "supported_hero_roles_contradict",
    )

    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=FAILURE reason=supported_hero_roles_contradict" in output
    assert "result=FULL_SUCCESS" not in output
    assert "event=destination_sample 3/3 refresh=" in output


def test_stage3_probe_still_accepts_exactly_three_good_production_refreshes_in_one_poll(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness, poll_probe=False)
    assert probe._destination_samples == 0
    attempt_id = probe._attempt_id
    assert attempt_id is not None

    cursor = probe._last_refresh_sequence
    _queue_stage3_destination_refresh(harness)
    _queue_stage3_destination_refresh(harness)
    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    sequences = tuple(event.sequence for event in batch.events)
    assert batch.active and not batch.overflowed and len(batch.events) == 3
    assert sequences == tuple(sorted(set(sequences)))

    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output
    assert "result=FAILURE" not in output


def test_stage3_probe_later_safe_unknown_cancels_an_earlier_success_candidate(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    cursor = probe._last_refresh_sequence

    _queue_stage3_destination_refresh(harness)
    _queue_stage3_destination_refresh(harness)
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    supported_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills
    runtime.bars[remote_hero.agent_id] = tuple(9000 + index for index in range(8))
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): supported_witness})
    _queue_stage3_destination_refresh(harness, delay_seconds=0.16)

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    assert batch.active and not batch.overflowed and len(batch.events) == 3
    assert batch.events[-1].evidence is not None
    final_evidence = probe._snapshot_evidence(
        batch.events[-1].evidence.snapshot,
        context,
        batch.events[-1].evidence,
    )
    assert _remote_hero_record(final_evidence.snapshot, module).role is module.CleansingRole.UNKNOWN
    assert probe._classify_destination(final_evidence, probe._outpost_baseline) == (
        "SAFE_UNKNOWN",
        "current_hero_role_unproven",
    )

    probe.update()

    output = capsys.readouterr().out
    assert probe._finished, output
    assert probe._terminal_outcome.reason == "production_transition_retired"
    assert probe._destination_samples == 0
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_later_continuity_break_invalidates_buffered_stability(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    cursor = probe._last_refresh_sequence

    _queue_stage3_destination_refresh(harness)
    _queue_stage3_destination_refresh(harness)
    runtime.party_id += 1
    runtime.publication_result = _remote_publication(runtime, module)
    _queue_stage3_destination_refresh(harness, delay_seconds=0.16)

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    sequences = tuple(event.sequence for event in batch.events)
    assert batch.active and not batch.overflowed and len(batch.events) == 3
    assert sequences == tuple(sorted(set(sequences)))

    probe.update()

    output = capsys.readouterr().out
    assert probe._finished, output
    assert probe._terminal_outcome.reason == "production_transition_retired"
    assert probe._destination_samples == 0
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_later_matching_build_cannot_revive_retired_hero(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    cursor = probe._last_refresh_sequence
    # This case checks state reset across a long buffer, not the separate console-budget behavior.
    monkeypatch.setattr(probe, "_MAX_OUTPUT_CHARACTERS", probe._MAX_OUTPUT_CHARACTERS + 432)
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    supported_bar = runtime.bars[remote_hero.agent_id]
    supported_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills

    _queue_stage3_destination_refresh(harness)
    runtime.bars[remote_hero.agent_id] = tuple(9000 + index for index in range(8))
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): supported_witness})
    _queue_stage3_destination_refresh(harness)
    runtime.bars[remote_hero.agent_id] = supported_bar
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): supported_witness})
    for _ in range(3):
        _queue_stage3_destination_refresh(harness)

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    assert batch.active and not batch.overflowed and len(batch.events) == 5
    roles = tuple(
        _remote_hero_record(event.evidence.snapshot, module).role
        for event in batch.events
        if event.evidence is not None
    )
    assert roles == (
        module.CleansingRole.ENERGY_SURGE,
        module.CleansingRole.UNKNOWN,
        module.CleansingRole.UNKNOWN,
        module.CleansingRole.UNKNOWN,
        module.CleansingRole.UNKNOWN,
    )

    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert probe._destination_samples == 0
    assert probe._terminal_outcome.reason == "production_transition_retired"
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_terminal_role_failure_is_not_erased_by_later_good_refreshes(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    cursor = probe._last_refresh_sequence
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    supported_bar = runtime.bars[remote_hero.agent_id]
    supported_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills

    _queue_stage3_destination_refresh(harness)
    runtime.bars[remote_hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): supported_witness})
    _queue_stage3_destination_refresh(harness, delay_seconds=0.16)
    runtime.bars[remote_hero.agent_id] = supported_bar
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): supported_witness})
    for _ in range(3):
        _queue_stage3_destination_refresh(harness)

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    assert batch.active and not batch.overflowed and len(batch.events) == 5

    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=FAILURE reason=supported_hero_roles_contradict" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_polls_of_cached_snapshot_do_not_count_as_refreshes(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    before = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, 0)
    assert probe._destination_samples == 1

    for _ in range(3):
        _probe_poll_destination(harness)

    after = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, 0)
    assert tuple(event.sequence for event in after.events) == tuple(event.sequence for event in before.events)
    assert probe._destination_samples == 1
    assert not probe._finished

    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    output = capsys.readouterr().out
    assert "result=INCONCLUSIVE reason=stable_destination_samples_incomplete" in output
    assert "samples=1/3" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_one_refresh_followed_by_polls_stays_incomplete(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    assert probe._destination_samples == 2

    for _ in range(3):
        _probe_poll_destination(harness)

    assert probe._destination_samples == 2
    assert not probe._finished
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    output = capsys.readouterr().out
    assert "result=INCONCLUSIVE reason=stable_destination_samples_incomplete" in output
    assert "samples=2/3" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_environment_gate_does_not_record_a_completed_refresh(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, global_cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    before = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, 0)
    assert probe._destination_samples == 1

    runtime.missing_map_contexts.add("world")
    global_cache._update_cache_for_environment(False, map_loading_observed=False)
    after = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, 0)
    assert tuple(event.sequence for event in after.events) == tuple(event.sequence for event in before.events)
    assert probe._destination_samples == 1
    clock.advance(0.26)
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert probe._destination_samples == 0
    assert probe._loading_event is not None
    assert probe._terminal_outcome.reason == "production_transition_retired"
    assert "result=FULL_SUCCESS" not in output


@pytest.mark.parametrize(
    "method_name", ("read_ordered_events", "evidence_for", "forwarding_for", "capture_observation", "end")
)
def test_stage3_probe_sanitizes_recorder_exceptions(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    method_name: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS

    def fail_with_private_detail(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("sensitive-publisher-detail")

    monkeypatch.setattr(recorder, method_name, fail_with_private_detail)
    if method_name == "end":
        probe._finish("INCONCLUSIVE", "widget_disabled")
    else:
        if method_name in ("evidence_for", "forwarding_for"):
            _probe_enter_loading(harness)
        clock.advance(0.26)
        probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    expected_reason = "widget_disabled" if method_name == "end" else "diagnostic_unavailable"
    assert f"result=INCONCLUSIVE reason={expected_reason}" in output
    assert "FULL_SUCCESS" not in output
    assert "sensitive-publisher-detail" not in output


def test_stage3_probe_recorder_failure_does_not_interrupt_production_refresh(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, global_cache, _upkeeper, _probe, _clock, diagnostics, _runtime = harness
    before = context.GetSnapshot().revision

    def fail_refresh_record(*_args: Any) -> None:
        raise RuntimeError("diagnostic failure")

    monkeypatch.setattr(
        diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS,
        "record_refresh",
        fail_refresh_record,
    )

    global_cache._update_cache()

    assert context.GetSnapshot().revision > before


def test_stage3_probe_does_not_accept_historical_gate_state_without_new_attempt_event(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, global_cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _upkeeper.main()
    assert context.GetSnapshot().ready

    global_cache._update_cache_for_environment(False, map_loading_observed=True)
    runtime.ready = False
    runtime.instance_type_override = 2
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert probe._attempt_id is None
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in output
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._active is None


def test_stage3_probe_fails_closed_if_context_disappears_after_real_loading(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, global_cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    assert probe._loading_event is not None

    global_cache.CleansingContext = None
    clock.advance(0.26)
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "loading=1" in output
    assert "result=INCONCLUSIVE reason=context_unavailable" in output


def test_stage3_probe_rejects_destination_from_a_different_lifecycle(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    assert probe._loading_event is not None

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    upkeeper.main()
    completed = context._stage3_evidence[-1]
    context._stage3_evidence[-1] = replace(
        completed, boundary=replace(completed.boundary, source_generation=completed.boundary.source_generation + 1)
    )
    clock.advance(0.26)
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=INCONCLUSIVE reason=production_transition_retired" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_restart_clears_old_attempt_events_and_keeps_sequence_monotonic(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    old_attempt = probe._attempt_id
    assert old_attempt is not None
    old_event = recorder.read_events(old_attempt, 0).events[0]

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 1
    runtime.outpost = True
    runtime.explorable = False
    runtime.publication_result = _remote_publication(runtime, module)
    upkeeper.main()
    restarted_probe = _load_stage3_evidence_probe(monkeypatch, _cache)
    monkeypatch.setattr(restarted_probe, "monotonic", clock.read)
    restarted_probe.update()
    new_attempt = restarted_probe._attempt_id

    assert new_attempt is not None and new_attempt > old_attempt
    assert not recorder.read_events(old_attempt, 0).active
    assert recorder.read_events(new_attempt, 0).events == ()

    runtime.ready = False
    runtime.instance_type_override = 2
    upkeeper.main()
    new_events = recorder.read_events(new_attempt, old_event.sequence).events
    assert len(new_events) == 1
    assert new_events[0].attempt_id == new_attempt
    assert new_events[0].sequence > old_event.sequence


def test_stage3_probe_temporary_false_forwarding_preserves_loading(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, global_cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    global_cache._update_cache_for_environment(False, map_loading_observed=False)
    clock.advance(0.26)
    probe.update()
    interrupted_output = capsys.readouterr().out
    assert not probe._finished
    assert probe._loading_event is not None
    assert probe._destination_samples == 0
    assert "event=final" not in interrupted_output


def test_stage3_probe_consumes_delayed_owner_loading_before_fixed_deadline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    upkeeper.main()
    runtime.ready = False
    runtime.instance_type_override = 2
    upkeeper.main()
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    event = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_events(attempt_id, 0).events[0]
    monkeypatch.setattr(
        probe,
        "monotonic_ns",
        lambda: event.observed_at_ns + probe._FORWARDING_FRESHNESS_NS + 1,
    )
    clock.advance(0.26)
    probe.update()
    assert probe._loading_event is not None
    assert probe._loading_event.owner is event.owner

    runtime.ready = True
    runtime.instance_type_override = None
    runtime.map_id = 2
    runtime.outpost = False
    runtime.explorable = True
    runtime.publication_result = _remote_publication(runtime, module)
    upkeeper.main()
    clock.advance(0.26)
    probe.update()
    stale_output = capsys.readouterr().out
    assert not probe._finished
    assert probe._destination_samples == 1
    assert "loading_not_observed" not in stale_output
    assert "result=FULL_SUCCESS" not in stale_output


def test_stage3_probe_rejects_party_change_at_pre_forward_boundary(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    runtime.party_id += 1
    runtime.publication_result = _remote_publication(runtime, module)
    clock.advance(0.26)
    upkeeper.main()
    runtime.ready = False
    runtime.instance_type_override = 2
    upkeeper.main()
    attempt_id = probe._attempt_id
    assert attempt_id is not None and probe._outpost_baseline is not None
    forwarding = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_events(attempt_id, 0).events
    assert forwarding
    assert forwarding[0].forwarded_loading
    assert forwarding[0].owner.boundary.transition_id != probe._owner_source.boundary.transition_id
    clock.advance(0.26)
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=INCONCLUSIVE reason=outpost_changed_before_loading" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_rejects_same_role_local_hero_replacement_before_forwarding(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    previous = next(
        hero for hero in runtime.heroes if hero.owner_player_id == runtime.login_number and hero.hero_id == 101
    )
    runtime.heroes.remove(previous)
    _add_hero(
        runtime,
        module,
        module.CleansingRole.BIP,
        hero_id=112,
        agent_id=2112,
        owner_id=runtime.login_number,
    )
    clock.advance(0.26)
    upkeeper.main()
    runtime.ready = False
    runtime.instance_type_override = 2
    upkeeper.main()
    attempt_id = probe._attempt_id
    assert attempt_id is not None and probe._outpost_baseline is not None
    forwarding = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_events(attempt_id, 0).events
    assert forwarding
    assert forwarding[0].forwarded_loading
    assert forwarding[0].owner.local != probe._owner_source.local
    clock.advance(0.26)
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=INCONCLUSIVE reason=outpost_changed_before_loading" in output
    assert "result=FULL_SUCCESS" not in output


@pytest.mark.parametrize("replacement", ("remote_owner", "remote_hero", "party", "local_hero"))
def test_stage3_probe_resets_stability_on_party_roster_or_publisher_replacement(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    replacement: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    assert probe._destination_samples == 1

    if replacement == "remote_owner":
        publication = _remote_publication(runtime, module)
        publication.snapshot.cohorts[0].incarnation = bytes((99,)) + bytes(15)
        runtime.publication_result = publication
    elif replacement == "remote_hero":
        remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
        remote_hero.hero_id = 8
        runtime.publication_result = _remote_publication(runtime, module)
    elif replacement == "party":
        runtime.party_id += 1
        runtime.publication_result = _remote_publication(runtime, module)
    else:
        previous = next(
            hero for hero in runtime.heroes if hero.owner_player_id == runtime.login_number and hero.hero_id == 101
        )
        runtime.heroes.remove(previous)
        _add_hero(
            runtime,
            module,
            module.CleansingRole.BIP,
            hero_id=112,
            agent_id=2112,
            owner_id=runtime.login_number,
        )
        runtime.publication_result = _remote_publication(runtime, module)
    upkeeper.main()
    if replacement == "local_hero":
        current = probe._snapshot_evidence(context.GetSnapshot(), context)
        assert probe._outpost_baseline is not None
        assert current.local_roster_keys != probe._outpost_baseline.local_roster_keys
    clock.advance(0.26)
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished and probe._destination_samples == 0
    assert probe._terminal_outcome.reason == "production_transition_retired"
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_allows_destination_agent_id_changes_with_publisher_continuity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)

    old_owner_agent = runtime.local_agent_by_login[22]
    new_owner_agent = 2022
    runtime.local_agent_by_login[22] = new_owner_agent
    runtime.professions[new_owner_agent] = runtime.professions[old_owner_agent]
    runtime.bars[new_owner_agent] = runtime.bars[old_owner_agent]
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    old_hero_agent = remote_hero.agent_id
    new_hero_agent = 4007
    remote_hero.agent_id = new_hero_agent
    runtime.professions[new_hero_agent] = runtime.professions[old_hero_agent]
    runtime.bars[new_hero_agent] = runtime.bars[old_hero_agent]

    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    output = capsys.readouterr().out

    assert probe._finished
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output
    assert "c=1/1/1" in output


def test_stage3_probe_allows_remote_login_reassociation_with_same_publisher(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    publisher = next(iter(context._remote_player_baselines.values())).publisher
    _probe_enter_loading(harness)

    remote_player = next(player for player in runtime.players if player.login_number == 22)
    remote_player.login_number = 23
    remote_agent_id = runtime.local_agent_by_login.pop(22)
    runtime.local_agent_by_login[23] = remote_agent_id
    runtime.player_names[23] = "Remote Reassociated"
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    remote_hero.owner_player_id = 23
    runtime.original_hero_builds[(23, 7)] = runtime.original_hero_builds.pop((22, 7))

    _probe_enter_destination(harness, publisher_identity=publisher)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    refreshes = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, 0)
    assert any(event.evidence is not None and event.evidence.snapshot.map_id == 2 for event in refreshes.events), [
        (event.sequence, event.evidence.snapshot.map_id if event.evidence is not None else None)
        for event in refreshes.events
    ]
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    output = capsys.readouterr().out

    assert probe._finished, output
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output
    assert "c=1/1/1" in output


@pytest.mark.parametrize("destination_samples", (1, 2))
def test_stage3_probe_runtime_cap_never_promotes_incomplete_stability(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    destination_samples: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    for _ in range(destination_samples - 1):
        _probe_sample_destination(harness)
    assert probe._destination_samples == destination_samples
    assert not probe._finished

    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=INCONCLUSIVE reason=stable_destination_samples_incomplete" in output
    assert f"samples={destination_samples}/3" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_output_cap_never_bypasses_stable_sampling(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    assert probe._destination_samples == 1
    probe._lines = probe._MAX_OUTPUT_LINES - 1
    _probe_sample_destination(harness)
    assert probe._destination_samples == 2
    assert not probe._finished
    assert probe._terminal_outcome is None
    _probe_sample_destination(harness)

    output = capsys.readouterr().out
    # This deliberately corrupts accounting by consuming reserved evidence lines.
    # Refused required output must remain pending; it cannot be called delivered.
    assert not probe._finished
    assert probe._terminal_outcome.result == "FULL_SUCCESS"
    assert len(probe._pending_destination_sample_details) == 3
    assert "event=final " not in output
    assert "result=FULL_SUCCESS" not in output
    assert probe._lines <= probe._MAX_OUTPUT_LINES
    assert probe._characters <= probe._MAX_OUTPUT_CHARACTERS


@pytest.mark.parametrize("cap", ("output", "runtime"))
def test_stage3_probe_caps_still_validate_later_buffered_contradictions(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cap: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    cursor = probe._last_refresh_sequence

    _queue_stage3_destination_refresh(harness)
    _queue_stage3_destination_refresh(harness)
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    outpost_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills
    runtime.bars[remote_hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): outpost_witness})
    _queue_stage3_destination_refresh(harness, delay_seconds=0.16)

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    assert batch.active and not batch.overflowed and len(batch.events) == 3
    if cap == "output":
        probe._lines = probe._MAX_OUTPUT_LINES - 1
    else:
        probe._started_at = clock.read() - probe._MAX_RUNTIME_SECONDS

    probe.update()

    output = capsys.readouterr().out
    if cap == "output":
        assert not probe._finished
        assert probe._terminal_outcome.result == "FAILURE"
        assert probe._terminal_outcome.reason == "supported_hero_roles_contradict"
        assert len(probe._pending_destination_sample_details) == 3
        assert "event=final " not in output
    else:
        assert probe._finished
        assert "result=FAILURE reason=supported_hero_roles_contradict" in output
    assert "result=FULL_SUCCESS" not in output
    assert probe._lines <= probe._MAX_OUTPUT_LINES
    assert probe._characters <= probe._MAX_OUTPUT_CHARACTERS


def test_stage3_probe_fails_closed_on_overflowed_forwarding_event_batch(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness, repeated_callbacks=2)
    attempt_id = probe._attempt_id
    assert attempt_id is not None

    for _ in range(_context._stage3_evidence.maxlen + 2):
        clock.advance(0.001)
        upkeeper.main()

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_events(attempt_id, probe._last_forwarding_sequence)
    sequences = tuple(event.sequence for event in batch.events)
    assert batch.active and batch.overflowed
    assert len(batch.events) == diagnostics._EVENT_CAPACITY
    assert sequences == tuple(sorted(set(sequences)))

    clock.advance(0.26)
    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=INCONCLUSIVE reason=production_evidence_buffer_overflow" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_fails_closed_on_overflowed_production_refresh_batch(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    attempt_id = probe._attempt_id
    assert attempt_id is not None
    cursor = probe._last_refresh_sequence

    for _ in range(diagnostics._EVENT_CAPACITY + 1):
        _queue_stage3_destination_refresh(harness)

    batch = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_refresh_events(attempt_id, cursor)
    sequences = tuple(event.sequence for event in batch.events)
    assert batch.active and batch.overflowed
    assert len(batch.events) == diagnostics._EVENT_CAPACITY
    assert sequences == tuple(sorted(set(sequences)))
    assert batch.events[0].sequence > cursor + 1
    assert all(event.evidence is not None for event in batch.events)

    probe.update()

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=INCONCLUSIVE reason=production_evidence_buffer_overflow" in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_fails_on_proven_destination_witness_contradiction(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    assert probe._destination_samples == 1

    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    outpost_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills
    runtime.bars[remote_hero.agent_id] = _role_bar(runtime, module, module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): outpost_witness})
    upkeeper.main()
    clock.advance(0.26)
    probe.update()

    assert probe._destination_samples == 0
    assert _remote_hero_record(context.GetSnapshot(), module).role is module.CleansingRole.UNKNOWN
    assert probe._finished
    output = capsys.readouterr().out
    assert "result=FAILURE reason=supported_hero_roles_contradict" in output


def test_stage3_probe_does_not_call_unproven_publisher_continuity_safe_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, runtime = harness
    original_witness = _role_bar(runtime, module, module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): original_witness})
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    runtime.bars[runtime.local_agent_by_login[22]] = tuple(8000 + index for index in range(8))
    _probe_enter_destination(harness, witness_skillbars={(22, 7): original_witness})

    assert _remote_player_record(context.GetSnapshot(), module).role is module.CleansingRole.UNKNOWN
    assert probe._destination_samples == 0
    assert probe._finished and probe._attempt_id is None
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    output = capsys.readouterr().out
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in output
    assert "result=SAFE_UNKNOWN" not in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_refuses_to_arm_an_unsupported_original_witness(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, _diagnostics, runtime = harness
    unsupported_witness = tuple(9000 + index for index in range(8))
    runtime.publication_result = _remote_publication(runtime, module, witness_skillbars={(22, 7): unsupported_witness})
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness, witness_skillbars={(22, 7): unsupported_witness})
    _probe_sample_destination(harness)
    assert probe._destination_samples == 0
    assert probe._finished and probe._attempt_id is None
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)

    output = capsys.readouterr().out
    assert probe._finished
    assert "witness=proven/UNKNOWN" in output
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in output
    assert "result=FAILURE" not in output
    assert "result=FULL_SUCCESS" not in output


@pytest.mark.parametrize("witness_state", ("missing", "incomplete"))
def test_stage3_probe_treats_missing_or_incomplete_original_build_as_inconclusive(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    witness_state: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, runtime = harness
    publication = _remote_publication(runtime, module)
    if witness_state == "missing":
        publication.snapshot.cohorts[0].witnesses = ()
    else:
        witness = publication.snapshot.cohorts[0].witnesses[0]
        witness.skills = tuple(witness.skills[:7])
    runtime.publication_result = publication
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)

    assert probe._destination_samples == 0
    assert probe._finished and probe._attempt_id is None
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    output = capsys.readouterr().out
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in output
    assert "result=FAILURE" not in output
    assert "result=FULL_SUCCESS" not in output


def test_stage3_probe_changed_current_hero_build_does_not_count_as_safe_sample(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, _diagnostics, runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    original_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    runtime.bars[remote_hero.agent_id] = tuple(9000 + index for index in range(8))
    _probe_enter_destination(harness, witness_skillbars={(22, 7): original_witness})
    assert _remote_hero_record(context.GetSnapshot(), module).role is module.CleansingRole.UNKNOWN
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)

    output = capsys.readouterr().out
    assert probe._finished
    assert "result=INCONCLUSIVE reason=production_transition_retired" in output
    assert "result=FULL_SUCCESS" not in output
    assert "samples=0/3" in output


def test_stage3_probe_phase_noise_does_not_exhaust_output_budget(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness

    # Keep noise inside preflight so the subsequent baseline remains eligible.
    for _ in range(16):
        runtime.ready = False
        runtime.instance_type_override = 0
        probe.update()
        clock.advance(0.26)
        runtime.ready = True
        runtime.instance_type_override = None
        probe.update()
        clock.advance(0.26)
    upkeeper.main()
    probe.update()

    output = capsys.readouterr().out
    assert not probe._finished, output
    assert probe._attempt_id is not None
    assert probe._lines == 3
    assert output.count("event=ready_to_zone ") == 1
    assert output.count("event=outpost_wait reason=map_not_ready") == 1
    assert output.count("wait=refresh_pending") == 0
    assert output.count("event=outpost created") == 1
    assert output.count("event=outpost_detail ") == 0
    assert probe._outpost_detail_budget_exhausted
    assert "result=INCONCLUSIVE reason=output_cap" not in output
    probe_lines = tuple(line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 "))
    assert len(probe_lines) == 3
    assert sum(len(line) + 1 for line in probe_lines) <= probe._MAX_OUTPUT_CHARACTERS
    probe.on_disable()
    output += capsys.readouterr().out
    assert output.count("wait=refresh_pending") == 1
    _assert_stage3_output_budget(probe, output)


def test_stage3_probe_source_has_no_state_changing_or_file_output_calls() -> None:
    source_path = _REPO_ROOT / "Widgets" / "Coding" / "Debug" / "Py4GW" / "Stage 3 Evidence Probe.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    called_attributes = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    called_names = {
        node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden_calls = {
        "Refresh",
        "Invalidate",
        "InvalidateForEnvironmentGate",
        "InvalidatePublishedSnapshot",
        "CastSkill",
        "UseSkill",
        "SetTarget",
        "AddHero",
        "KickPlayer",
        "PublishFormationFollowPoints",
        "GetAllAccounts",
        "open",
    }

    assert not (called_attributes | called_names).intersection(forbidden_calls)


def _stage3_refresh_diagnostic_messages() -> list[str]:
    console_logs = sys.modules["PySystem"].stage3_console_logs
    return [
        message for _sender, message, _message_type in console_logs if message.startswith("STAGE3_REFRESH_DIAG_V1 ")
    ]


def test_stage3_probe_accepts_client_a_hr_with_client_b_bip_and_remote_es_hero(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness

    _probe_enter_outpost(harness)
    snapshot = context.GetSnapshot()
    local_player = next(
        member for member in snapshot.members if member.evidence_source is module.EvidenceSource.LOCAL_PLAYER
    )
    local_heroes = tuple(
        member for member in snapshot.members if member.evidence_source is module.EvidenceSource.LOCAL_HERO
    )
    remote_player = _remote_player_record(snapshot, module)
    remote_hero = _remote_hero_record(snapshot, module)

    assert snapshot.ready and len(snapshot.members) == snapshot.composition.member_count == 8
    assert local_player.role is module.CleansingRole.HEROIC_REFRAIN
    assert len(local_heroes) == 5
    assert sum(member.role is module.CleansingRole.SOUL_TWISTING for member in local_heroes) == 1
    assert sum(member.role is module.CleansingRole.INEPTITUDE for member in local_heroes) == 1
    assert sum(member.role is module.CleansingRole.ENERGY_SURGE for member in local_heroes) == 3
    assert remote_player.role is module.CleansingRole.BIP
    assert remote_player.evidence_source is module.EvidenceSource.REMOTE_PLAYER
    assert remote_hero.role is module.CleansingRole.ENERGY_SURGE
    assert remote_hero.evidence_source is module.EvidenceSource.REMOTE_HERO
    assert remote_hero.identity.owner_id == remote_player.identity.owner_id
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.UNKNOWN] == 2
    assert probe._attempt_id is not None
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) == probe._attempt_id
    output = capsys.readouterr().out
    assert "created roster=8/8" in output

    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    destination = context.GetSnapshot()
    assert probe._finished
    assert destination.composition.status is module.CompositionStatus.FALLBACK
    assert dict(destination.composition.role_counts)[module.CleansingRole.UNKNOWN] == 2
    assert _remote_player_record(destination, module).role is module.CleansingRole.BIP
    assert _remote_hero_record(destination, module).role is module.CleansingRole.ENERGY_SURGE
    output += capsys.readouterr().out
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output
    assert "P=BiP pub=1 base=1" in output
    assert "H=ES" in output
    assert "witness=proven/ES" in output
    assert "stage4=FALLBACK u=2" in output
    _assert_stage3_output_budget(probe, output)


@pytest.mark.parametrize(
    ("role_distribution", "remote_role", "expected_reason"),
    (
        ("remote_es", "BIP", "wait=distribution"),
        ("remote_bip", "ENERGY_SURGE", "wait=distribution"),
        ("remote_es", "PANIC", "wait=remote_role"),
    ),
)
def test_stage3_probe_rejects_unsupported_local_remote_role_pairings(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    role_distribution: Literal["remote_es", "remote_bip"],
    remote_role: str,
    expected_reason: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(
        monkeypatch,
        runtime,
        module,
        role_distribution=role_distribution,
        remote_player_role=getattr(module.CleansingRole, remote_role),
    )
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness

    _probe_enter_outpost(harness)

    assert context.GetSnapshot().ready and len(context.GetSnapshot().members) == 8
    assert probe._attempt_id is None
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
    probe.on_disable()
    probe_messages = [
        message
        for _sender, message, _message_type in sys.modules["PySystem"].stage3_console_logs
        if message.startswith("STAGE3_EVIDENCE_V1 ")
    ]
    assert expected_reason in " ".join(probe_messages)


def test_cleansing_context_refresh_diagnostic_reports_success_snapshot(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    _configure_team(
        runtime,
        module,
        [
            module.CleansingRole.HEROIC_REFRAIN,
            module.CleansingRole.BIP,
            module.CleansingRole.SOUL_TWISTING,
            module.CleansingRole.INEPTITUDE,
            module.CleansingRole.ENERGY_SURGE,
            module.CleansingRole.ENERGY_SURGE,
            module.CleansingRole.ENERGY_SURGE,
            module.CleansingRole.ENERGY_SURGE,
        ],
    )
    context = module.CleansingContext()
    console_logs = sys.modules["PySystem"].stage3_console_logs
    console_logs.clear()
    clock = [100.0]
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])

    snapshot = context.Refresh()

    messages = _stage3_refresh_diagnostic_messages()
    assert snapshot.ready
    assert len(messages) == 1
    assert "attempt=1 window=1 success=1 failure=0 outcome=success" in messages[0]
    assert f"ready=1 revision={snapshot.revision} members={len(snapshot.members)}" in messages[0]


def test_cleansing_context_refresh_diagnostic_captures_exception_type_and_application_site(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, module = cleansing_runtime
    context = module.CleansingContext()
    console_logs = sys.modules["PySystem"].stage3_console_logs
    console_logs.clear()
    clock = [200.0]
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])

    def fail_refresh() -> Any:
        raise ValueError("private-account@example.invalid")

    monkeypatch.setattr(context, "_refresh_from_runtime", fail_refresh)
    snapshot = context.Refresh()

    messages = _stage3_refresh_diagnostic_messages()
    assert not snapshot.ready
    assert snapshot.reason == "runtime evidence read failed (ValueError)"
    assert len(messages) == 1
    assert "outcome=failure" in messages[0] and "error=ValueError" in messages[0]
    assert re.search(r"site=Refresh:\d+", messages[0])
    assert "private-account@example.invalid" not in messages[0]
    assert "C:\\Users\\" not in messages[0] and ".py" not in messages[0]


def test_cleansing_context_refresh_diagnostic_distinguishes_recovery_and_no_new_attempts(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    _configure_team(
        runtime,
        module,
        [
            module.CleansingRole.HEROIC_REFRAIN,
            module.CleansingRole.BIP,
            module.CleansingRole.SOUL_TWISTING,
            module.CleansingRole.INEPTITUDE,
            module.CleansingRole.ENERGY_SURGE,
            module.CleansingRole.ENERGY_SURGE,
        ],
    )
    context = module.CleansingContext()
    console_logs = sys.modules["PySystem"].stage3_console_logs
    console_logs.clear()
    clock = [300.0]
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    original_refresh = context._refresh_from_runtime

    def fail_refresh() -> Any:
        raise RuntimeError("private runtime detail")

    monkeypatch.setattr(context, "_refresh_from_runtime", fail_refresh)
    failed_snapshot = context.Refresh()
    failure_line = _stage3_refresh_diagnostic_messages()[-1]
    assert not failed_snapshot.ready and "outcome=failure" in failure_line

    monkeypatch.setattr(context, "_refresh_from_runtime", original_refresh)
    clock[0] += 1.1
    recovered_snapshot = context.Refresh()
    recovery_line = _stage3_refresh_diagnostic_messages()[-1]
    assert recovered_snapshot.ready
    assert "attempt=2 window=1 success=1 failure=0 outcome=success ready=1" in recovery_line

    clock[0] += 0.1
    monkeypatch.setattr(context, "_refresh_from_runtime", fail_refresh)
    context.Refresh()
    clock[0] += 0.1
    monkeypatch.setattr(context, "_refresh_from_runtime", original_refresh)
    context.Refresh()
    clock[0] += 1.0
    context.ReportRefreshDiagnostic()
    recovered_line = _stage3_refresh_diagnostic_messages()[-1]
    assert "attempt=4 window=2 success=1 failure=1 outcome=success ready=1" in recovered_line
    assert "recovered=1 failure_error=RuntimeError" in recovered_line
    assert re.search(r"failure_site=Refresh:\d+", recovered_line)

    console_logs.clear()
    clock[0] += 1.1
    context.ReportRefreshDiagnostic()
    idle_line = _stage3_refresh_diagnostic_messages()[-1]
    assert "attempt=4 window=0 success=0 failure=0 outcome=none ready=1" in idle_line
    assert "error=" not in idle_line


def test_cleansing_context_refresh_diagnostic_is_rate_limited_and_hard_capped(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, module = cleansing_runtime
    context = module.CleansingContext()
    console_logs = sys.modules["PySystem"].stage3_console_logs
    console_logs.clear()
    clock = [400.0]
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(context, "_refresh_from_runtime", context.GetSnapshot)

    for _ in range(8):
        context.Refresh()
        context.ReportRefreshDiagnostic()
        clock[0] += 0.1

    assert len(_stage3_refresh_diagnostic_messages()) == 1

    for _ in range(20):
        clock[0] += 1.01
        context.Refresh()

    messages = _stage3_refresh_diagnostic_messages()
    assert len(messages) == 12
    assert context._refresh_diagnostic_lines == 12
    assert context._refresh_diagnostic_attempts == 28


def test_cleansing_context_refresh_diagnostic_failures_do_not_change_refresh_results(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, module = cleansing_runtime
    context = module.CleansingContext()
    console = sys.modules["PySystem"].Console
    monkeypatch.setattr(console, "Log", lambda *_args: (_ for _ in ()).throw(RuntimeError("log failure")))
    expected_snapshot = context.GetSnapshot()
    monkeypatch.setattr(context, "_refresh_from_runtime", lambda: expected_snapshot)

    actual_snapshot = context.Refresh()
    context.ReportRefreshDiagnostic()

    assert actual_snapshot is expected_snapshot
    assert context.GetSnapshot() is expected_snapshot


def _replace_stage3_snapshot_members(
    context: Any,
    module: types.ModuleType,
    members: tuple[Any, ...],
) -> None:
    snapshot = context.GetSnapshot()
    composition = module.match_supported_composition(
        members,
        declared_party_size=snapshot.composition.declared_party_size,
    )
    context._snapshot = replace(snapshot, members=members, composition=composition)


def test_stage3_probe_reports_five_missing_local_baselines_and_skips_native_reader(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    context, cache, upkeeper, probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module
    )
    upkeeper.main()
    local_members = tuple(
        member
        for member in context.GetSnapshot().members
        if member.evidence_source in (module.EvidenceSource.LOCAL_PLAYER, module.EvidenceSource.LOCAL_HERO)
    )
    assert len(local_members) == 6 and len(context._baselines) == 6
    reader = cache.ShMem.GetNativeAccountSnapshotV3
    reader_calls = 0

    def counted_reader() -> Any:
        nonlocal reader_calls
        reader_calls += 1
        return reader()

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", counted_reader)
    for member in local_members[1:]:
        context._baselines.pop(member.identity.stable_key, None)

    probe.update()

    probe.on_disable()
    output = capsys.readouterr().out
    detail = next(line for line in output.splitlines() if "event=outpost_detail " in line)
    assert detail.count("/0") == 5
    assert "/base_missing" in detail or "why=base_missing" in detail
    assert "LP:HR/1," in detail
    assert "witness=not_run" in detail
    assert reader_calls == 0
    assert probe._attempt_id is None


def test_stage3_probe_reports_distinct_safe_local_unknown_reasons(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    context, _cache, upkeeper, probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module
    )
    upkeeper.main()
    snapshot = context.GetSnapshot()
    local_heroes = tuple(
        member for member in snapshot.members if member.evidence_source is module.EvidenceSource.LOCAL_HERO
    )
    assert len(local_heroes) == 5
    changed_reasons = {
        local_heroes[0].identity.stable_key: "skillbar evidence is incomplete",
        local_heroes[1].identity.stable_key: "multiple supported elite anchors make the role ambiguous",
    }
    members = tuple(
        (
            replace(
                member,
                role=module.CleansingRole.UNKNOWN,
                candidate_role=module.CleansingRole.UNKNOWN,
                reason=changed_reasons[member.identity.stable_key],
            )
            if member.identity.stable_key in changed_reasons
            else member
        )
        for member in snapshot.members
    )
    for key in changed_reasons:
        context._baselines.pop(key, None)
    _replace_stage3_snapshot_members(context, module, members)

    probe.update()

    probe.on_disable()
    detail = next(line for line in capsys.readouterr().out.splitlines() if "event=outpost_detail " in line)
    assert "H1:UNKNOWN/0/bar_incomplete" in detail
    assert "H2:UNKNOWN/0/anchor_ambiguous" in detail
    assert "skillbar evidence is incomplete" not in detail
    assert "multiple supported elite anchors" not in detail
    assert probe._attempt_id is None


def test_stage3_probe_reports_remote_hero_witness_mismatch_as_safe_reason(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    witness_bar = _role_bar(runtime, module, module.CleansingRole.PANIC, utility_seed=9000)
    runtime.witness_skillbars = {(22, 7): witness_bar}
    runtime.publication_result = _remote_publication(
        runtime,
        module,
        witness_skillbars=runtime.witness_skillbars,
    )

    _probe_enter_outpost(harness)

    hero = _remote_hero_record(context.GetSnapshot(), module)
    probe.on_disable()
    output = capsys.readouterr().out
    detail = next(line for line in output.splitlines() if "event=outpost_detail " in line)
    assert hero.role is module.CleansingRole.UNKNOWN
    assert "does not agree" in hero.reason
    assert "H=UNKNOWN r=witness_mismatch" in detail
    assert "does not agree" not in detail


def test_stage3_probe_reports_reader_failure_as_unavailable_not_not_run(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    context, cache, upkeeper, probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module
    )
    upkeeper.main()
    monkeypatch.setattr(
        cache.ShMem,
        "GetNativeAccountSnapshotV3",
        lambda: types.SimpleNamespace(status=types.SimpleNamespace(value="busy"), snapshot=None),
    )

    probe.update()

    probe.on_disable()
    output = capsys.readouterr().out
    detail = next(line for line in output.splitlines() if "event=outpost_detail " in line)
    assert "witness=unavailable/snapshot" in detail
    assert probe._outpost_baseline is not None
    assert probe._outpost_baseline.witness_status == "unavailable"
    assert probe._attempt_id is not None
    assert context.GetSnapshot().ready


def test_stage3_probe_emits_changed_outpost_state_but_suppresses_unchanged_state(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module
    )
    monkeypatch.setattr(probe, "_MAX_OUTPUT_CHARACTERS", probe._MAX_OUTPUT_CHARACTERS + 432)
    upkeeper.main()
    local_members = tuple(
        member
        for member in context.GetSnapshot().members
        if member.evidence_source in (module.EvidenceSource.LOCAL_PLAYER, module.EvidenceSource.LOCAL_HERO)
    )
    saved_baselines = context._baselines.copy()
    for member in local_members[1:]:
        context._baselines.pop(member.identity.stable_key, None)

    probe.update()
    first_output = capsys.readouterr().out
    clock.advance(0.26)
    probe.update()
    unchanged_output = capsys.readouterr().out
    assert first_output.count("event=outpost_detail ") == 1
    assert "event=outpost_detail " not in unchanged_output

    context._baselines[local_members[1].identity.stable_key] = saved_baselines[local_members[1].identity.stable_key]
    clock.advance(1.01)
    probe.update()
    probe.on_disable()
    changed_output = capsys.readouterr().out
    changed_lines = tuple(line for line in changed_output.splitlines() if "event=outpost_detail " in line)
    assert len(changed_lines) == 1
    assert "/0/base_missing" in first_output
    assert "H1:BiP/1," in changed_lines[0]
    assert probe._outpost_detail_report_count == 2
    assert probe._attempt_id is None


def test_stage3_probe_never_emits_untrusted_reason_or_identity_text(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    context, _cache, upkeeper, probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module
    )
    upkeeper.main()
    snapshot = context.GetSnapshot()
    hero = _remote_hero_record(snapshot, module)
    private_reason = "untrusted reason private-account@example.invalid HWND=777 UUID=deadbeef AgentID=3001"
    members = tuple(
        (
            replace(
                member,
                role=module.CleansingRole.UNKNOWN,
                candidate_role=module.CleansingRole.UNKNOWN,
                reason=private_reason,
            )
            if member is hero
            else member
        )
        for member in snapshot.members
    )
    _replace_stage3_snapshot_members(context, module, members)

    probe.update()

    probe.on_disable()
    output = capsys.readouterr().out
    detail = next(line for line in output.splitlines() if "event=outpost_detail " in line)
    assert "H=UNKNOWN r=unproven" in detail
    assert "private-account@example.invalid" not in output
    assert "HWND=777" not in output and "deadbeef" not in output and "AgentID=3001" not in output
    assert "3001" not in detail
    assert "Mesmer A" not in output and "Remote 22" not in output


def test_stage3_probe_five_missing_baselines_cannot_starve_validation_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    probe.on_enable()
    upkeeper.main()
    local_members = tuple(
        member
        for member in context.GetSnapshot().members
        if member.evidence_source in (module.EvidenceSource.LOCAL_PLAYER, module.EvidenceSource.LOCAL_HERO)
    )
    saved_baselines = context._baselines.copy()
    assert len(local_members) == len(saved_baselines) == 6
    for member in local_members[1:]:
        context._baselines.pop(member.identity.stable_key, None)

    probe.update()
    assert probe._attempt_id is None

    context._baselines.update(saved_baselines)
    clock.advance(1.01)
    probe.update()
    assert probe._attempt_id is not None
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)

    output = capsys.readouterr().out
    probe_lines = tuple(line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 "))
    outpost_details = tuple(line for line in probe_lines if "event=outpost_detail " in line)
    sample_lines = tuple(line for line in probe_lines if "event=destination_sample " in line)
    refresh_sequences = tuple(line.split("refresh=", 1)[1].split(" ", 1)[0] for line in sample_lines)
    assert "event=outpost created roster=8/8" in output
    assert any("why=base_missing" in line for line in outpost_details), output
    assert "event=loading seq=" in output
    assert len(sample_lines) == len(set(refresh_sequences)) == 3
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output, output
    assert "result=INCONCLUSIVE reason=output_cap" not in output
    required_lines = tuple(
        line
        for line in probe_lines
        if "event=outpost created" in line
        or "event=ready_to_zone " in line
        or "event=loading " in line
        or "event=destination_sample " in line
    )
    assert len(required_lines) == 6
    assert probe._required_characters == sum(len(line) + 1 for line in required_lines)
    assert probe._required_characters <= probe._REQUIRED_EVIDENCE_CHARACTERS
    assert len(probe_lines) <= probe._MAX_OUTPUT_LINES
    assert sum(len(line) + 1 for line in probe_lines) <= probe._MAX_OUTPUT_CHARACTERS


def test_stage3_probe_five_then_four_missing_baselines_cannot_starve_validation_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    probe.on_enable()
    upkeeper.main()
    local_members = tuple(
        member
        for member in context.GetSnapshot().members
        if member.evidence_source in (module.EvidenceSource.LOCAL_PLAYER, module.EvidenceSource.LOCAL_HERO)
    )
    saved_baselines = context._baselines.copy()
    assert len(local_members) == len(saved_baselines) == 6
    for member in local_members[1:]:
        context._baselines.pop(member.identity.stable_key, None)
    probe.update()

    restored_member = local_members[1]
    context._baselines[restored_member.identity.stable_key] = saved_baselines[restored_member.identity.stable_key]
    clock.advance(1.01)
    probe.update()

    context._baselines.update(saved_baselines)
    clock.advance(1.01)
    probe.update()
    assert probe._attempt_id is not None
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)

    output = capsys.readouterr().out
    probe_lines = tuple(line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 "))
    outpost_details = tuple(line for line in probe_lines if "event=outpost_detail " in line)
    sample_lines = tuple(line for line in probe_lines if "event=destination_sample " in line)
    refresh_sequences = tuple(line.split("refresh=", 1)[1].split(" ", 1)[0] for line in sample_lines)
    assert "event=outpost created roster=8/8" in output
    assert len(outpost_details) == probe._outpost_detail_report_count == 1, output
    assert "why=base_missing" in outpost_details[0]
    assert probe._outpost_detail_budget_exhausted
    assert "event=loading seq=" in output
    assert len(sample_lines) == len(set(refresh_sequences)) == 3
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output, output
    assert "result=INCONCLUSIVE reason=output_cap" not in output
    required_lines = tuple(
        line
        for line in probe_lines
        if "event=outpost created" in line
        or "event=ready_to_zone " in line
        or "event=loading " in line
        or "event=destination_sample " in line
    )
    assert len(required_lines) == 6
    assert probe._required_characters == sum(len(line) + 1 for line in required_lines)
    assert probe._required_characters <= probe._REQUIRED_EVIDENCE_CHARACTERS
    assert len(probe_lines) <= probe._MAX_OUTPUT_LINES
    assert sum(len(line) + 1 for line in probe_lines) <= probe._MAX_OUTPUT_CHARACTERS


def test_stage3_probe_reserves_evidence_lines_and_final_character_capacity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    _context, cache, _upkeeper, probe, _clock, _diagnostics, _runtime = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module
    )
    probe.on_enable()
    actual_character_cap = probe._MAX_OUTPUT_CHARACTERS
    monkeypatch.setattr(probe, "_MAX_OUTPUT_CHARACTERS", actual_character_cap * 4)
    ordinary_limit = probe._MAX_OUTPUT_LINES - probe._RESERVED_EVIDENCE_LINES - 1
    while probe._lines < ordinary_limit:
        assert probe._emit("detail", "x")
    assert probe._lines == ordinary_limit
    assert not probe._emit("detail", "x")

    for event in (
        "outpost",
        "ready_to_zone",
        "loading",
        "destination_sample",
        "destination_sample",
        "destination_sample",
        "outpost_cause",
    ):
        assert probe._emit(event, "x", reserved=True)
    assert probe._lines == probe._MAX_OUTPUT_LINES - 1
    probe._finish("INCONCLUSIVE", "line_budget_test")
    assert probe._lines == probe._MAX_OUTPUT_LINES
    line_output = capsys.readouterr().out
    assert "event=loading x" in line_output
    assert "event=destination_sample x" in line_output
    assert "event=final result=INCONCLUSIVE reason=line_budget_test" in line_output

    probe = _load_stage3_evidence_probe(monkeypatch, cache)
    optional_limit = probe._MAX_OUTPUT_CHARACTERS - probe._FINAL_OUTPUT_RESERVE - probe._REQUIRED_EVIDENCE_CHARACTERS
    optional_prefix_length = len(f"{probe._PREFIX} event=padding ")
    optional_payload_length = optional_limit - probe._optional_characters - optional_prefix_length - 1
    assert probe._emit("padding", "x" * optional_payload_length)
    assert probe._optional_characters == optional_limit
    assert not probe._emit("padding", "y")
    required_prefix_length = len(f"{probe._PREFIX} event=padding ")
    required_payload_length = (
        probe._REQUIRED_EVIDENCE_CHARACTERS - probe._required_characters - required_prefix_length - 1
    )
    assert probe._emit("padding", "z" * required_payload_length, reserved=True)
    assert probe._required_characters == probe._REQUIRED_EVIDENCE_CHARACTERS
    assert probe._characters == probe._MAX_OUTPUT_CHARACTERS - probe._FINAL_OUTPUT_RESERVE
    assert not probe._emit("padding", "w", reserved=True)
    probe._finish("INCONCLUSIVE", "character_budget_test")
    character_output = capsys.readouterr().out
    probe_lines = tuple(line for line in character_output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 "))
    assert probe_lines[-1].startswith("STAGE3_EVIDENCE_V1 event=final result=INCONCLUSIVE reason=character_budget_test")
    assert probe._characters <= probe._MAX_OUTPUT_CHARACTERS


def test_stage3_probe_valid_composition_a_summary_preserves_success_gates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness

    probe.on_enable()
    probe.update()
    clock.advance(0.26)
    upkeeper.main()
    probe.update()
    outpost_output = capsys.readouterr().out
    outpost_lines = tuple(line for line in outpost_output.splitlines() if "event=outpost " in line)
    assert len(outpost_lines) == 1
    assert "event=outpost created roster=8/8" in outpost_lines[0]

    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)

    output = outpost_output + capsys.readouterr().out
    detail = next(line for line in output.splitlines() if "event=outpost_detail " in line)
    assert "L=LP:HR/1,H1:ST/1,H2:IN/1,H3:ES/1,H4:ES/1,H5:ES/1" in detail
    assert "P=BiP pub=1 base=1" in detail
    assert "H=ES" in detail
    assert "stage4=FALLBACK u=2 fence=1" in detail
    assert "witness=proven/ES" in detail
    assert probe._finished
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in output
    assert "result=FAILURE" not in output and "result=INCONCLUSIVE reason=output_cap" not in output
    probe_lines = tuple(line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 "))
    assert sum(len(line) + 1 for line in probe_lines) <= probe._MAX_OUTPUT_CHARACTERS


def test_stage3_probe_attempt_10000_failure_at_reserved_character_boundary(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    harness[5].STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._next_attempt_id = 9999
    _probe_enter_outpost(harness)
    assert probe._attempt_id == 10000
    for reserved, capacity, used in (
        (
            False,
            probe._MAX_OUTPUT_CHARACTERS - probe._REQUIRED_EVIDENCE_CHARACTERS - probe._FINAL_OUTPUT_RESERVE,
            probe._optional_characters,
        ),
        (True, probe._REQUIRED_EVIDENCE_CHARACTERS, probe._required_characters),
    ):
        payload = capacity - used - len(probe._record("padding", "")) - 2
        assert payload >= 0
        assert probe._emit("padding", "x" * payload, reserved=reserved)
    assert probe._characters == probe._MAX_OUTPUT_CHARACTERS - probe._FINAL_OUTPUT_RESERVE
    probe._finish("FAILURE", "remote_player_role_contradicts_outpost_baseline")
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert "result=FAILURE reason=remote_player_role_contradicts_outpost_baseline" in records[-1]
    assert "attempt=0z7ps" in records[-1]
    assert probe._finished


def test_stage3_probe_exact_character_boundary_keeps_widest_verdict(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    harness[5].STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._next_attempt_id = (1 << 64) - 2
    _probe_enter_outpost(harness)
    optional_capacity = probe._MAX_OUTPUT_CHARACTERS - probe._REQUIRED_EVIDENCE_CHARACTERS - probe._FINAL_OUTPUT_RESERVE
    for reserved, remaining in (
        (False, optional_capacity - probe._optional_characters),
        (True, probe._REQUIRED_EVIDENCE_CHARACTERS - probe._required_characters),
    ):
        assert probe._emit("padding", "x" * (remaining - len(probe._record("padding")) - 2), reserved=reserved)
    # This is a serializer boundary test; use the longest supported reason and result widths.
    probe._finish("INCONCLUSIVE", "remote_player_role_contradicts_outpost_baseline")
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert probe._characters == probe._MAX_OUTPUT_CHARACTERS
    assert "reason=remote_player_role_contradicts_outpost_baseline" in records[-1]
    assert not probe._emit("extra", "x")


@pytest.mark.parametrize("sample_count", (1, 2))
def test_stage3_probe_lifecycle_reset_never_flushes_old_partial_samples(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_count: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    if sample_count == 2:
        _probe_sample_destination(harness)
    _queue_stage3_destination_refresh(harness)
    context = harness[0]
    event = context._stage3_evidence[-1]
    context._stage3_evidence[-1] = replace(
        event,
        snapshot=replace(event.snapshot, lifecycle_epoch=event.snapshot.lifecycle_epoch + 1),
    )
    probe.update()
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert not any("event=destination_sample " in record for record in records)
    assert "result=INCONCLUSIVE reason=production_completion_order_invalid" in records[-1]
    assert "samples=0/3" in records[-1]


@pytest.mark.parametrize("sample_count", (1, 2))
def test_stage3_probe_safe_but_incomplete_streak_prints_observed_samples(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_count: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    original_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills
    remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
    runtime.bars[remote_hero.agent_id] = tuple(9000 + i for i in range(8))
    _probe_enter_destination(harness, witness_skillbars={(22, 7): original_witness})
    if sample_count == 2:
        _probe_sample_destination(harness)
    evidence = probe._snapshot_evidence(context.GetSnapshot(), context)
    assert probe._classify_destination(evidence, probe._outpost_baseline)[0] == "SAFE_UNKNOWN"
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert not any("event=destination_sample " in record for record in records)
    assert "result=INCONCLUSIVE reason=production_transition_retired" in records[-1]
    assert "samples=0/3" in records[-1]
    assert "FULL_SUCCESS" not in records[-1] and "result=SAFE_UNKNOWN" not in records[-1]


def test_stage3_probe_counter_serialization_is_exact_and_bounded(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    probe = _prepare_stage3_probe_harness(monkeypatch, runtime, module)[3]
    values = [0, 1, 998, 999, 1000, 999_999_999, 1_000_000_000, (1 << 64) - 1]
    rng = random.Random(3)
    values += [rng.randrange(1 << 64) for _ in range(100)]
    texts = [probe._counter_text(value) for value in values]
    assert len(set(texts)) == len(set(values))
    for value, encoded in zip(values, texts):
        decoded = int(encoded[2:], 36) if encoded.startswith("0z") else int(encoded)
        assert decoded == value and len(encoded) <= len(probe._WIDEST_COUNTER), (value, encoded)
    for value in (-1, 1 << 64, 1 << 10000):
        with pytest.raises(probe._CounterDisplayOverflow):
            probe._counter_text(value)


@pytest.mark.parametrize("location", ("loading", "sample", "attempt", "failure"))
def test_stage3_probe_unrepresentable_counter_fails_explicitly_without_losing_failure(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    location: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    if location == "loading":
        _seed_stage3_probe_counters(harness, 1 << 64)
    if location == "attempt":
        diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._next_attempt_id = 1 << 64
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    if location != "loading":
        _probe_enter_destination(harness)
        _queue_stage3_destination_refresh(harness)
        if location in ("sample", "failure"):
            event = context._stage3_evidence[-1]
            context._stage3_evidence[-1] = replace(event, boundary=replace(event.boundary, completed_refresh=1 << 64))
            context._completed_refresh = 1 << 64
        if location == "failure":
            _queue_stage3_remote_player_contradiction(harness, module)
        probe.update()
        if not probe._finished:
            probe.on_disable()
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    if location == "failure":
        assert "result=FAILURE reason=remote_player_role_contradicts_outpost_baseline" in records[-1]
        assert "output=counter_display_overflow" in records[-1]
    else:
        assert "result=INCONCLUSIVE reason=counter_display_overflow" in records[-1]
    assert "FULL_SUCCESS" not in records[-1]


def test_stage3_probe_cleanup_failure_cannot_replace_a_contradiction(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _queue_stage3_remote_player_contradiction(harness, module)

    def fail_end(_attempt_id: int) -> None:
        raise RuntimeError("private@example.invalid")

    monkeypatch.setattr(diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS, "end", fail_end)
    probe.update()
    output = capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert "result=FAILURE reason=remote_player_role_contradicts_outpost_baseline" in records[-1]
    assert "private@example.invalid" not in output


def test_stage3_probe_reenable_discards_old_buffered_samples_and_budget(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    assert probe._destination_samples == 1
    assert probe._pending_destination_sample_details
    old_output = capsys.readouterr().out
    probe.on_enable()
    restart_output = capsys.readouterr().out
    old_tail, activation = restart_output.split("STAGE3_EVIDENCE_V1 event=activation", 1)
    old_output += old_tail
    old_records: list[str] = [line for line in old_output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 ")]
    assert len(old_records) <= 24 and sum(len(line) + 1 for line in old_records) <= probe._MAX_OUTPUT_CHARACTERS
    assert len([record for record in old_records if "event=final " in record]) == 1
    assert "result=INCONCLUSIVE reason=observer_restarted" in old_records[-1]
    assert "samples=1/3" in old_records[-1]
    assert probe._destination_samples == probe._required_lines == probe._required_characters == 0
    assert probe._pending_destination_sample_details == []
    assert probe._pending_outpost_details == []
    assert probe._terminal_details is None
    probe.on_disable()
    output = "STAGE3_EVIDENCE_V1 event=activation" + activation + capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert not any("event=destination_sample " in record for record in records)
    assert "samples=0/3" in records[-1]


def test_stage3_probe_timeout_discards_samples_invalidated_after_recorder_expiry(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    assert probe._destination_samples == 1
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    runtime.ready = False
    runtime.instance_type_override = 0
    upkeeper.main()
    assert not context.GetSnapshot().ready
    probe.update()
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert not any("event=destination_sample " in record for record in records)
    assert "result=INCONCLUSIVE" in records[-1]
    assert "samples=0/3" in records[-1]


def test_stage3_probe_saturated_optional_budget_cannot_starve_widest_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    capacity = probe._MAX_OUTPUT_CHARACTERS - probe._REQUIRED_EVIDENCE_CHARACTERS - probe._FINAL_OUTPUT_RESERVE
    assert probe._emit("padding", "x" * (capacity - len(probe._record("padding")) - 2))
    assert not probe._emit("detail", "optional output refused")
    _seed_stage3_probe_counters(harness, (1 << 64) - 100)
    harness[5].STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._next_attempt_id = (1 << 64) - 100
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert probe._optional_characters == capacity
    assert len([record for record in records if "event=destination_sample " in record]) == 3
    assert "result=FULL_SUCCESS" in records[-1]


def test_stage3_probe_exact_line_boundary_keeps_prepared_verdict(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    probe = _prepare_stage3_probe_harness(monkeypatch, runtime, module)[3]
    # Model the sealed evidence phase directly so the line guard is exercised
    # independently of the longer production diagnostic records, at the real caps.
    probe._terminal_details = probe._final_details("INCONCLUSIVE", "widget_disabled", "none", 0, 0)
    for _ in range(23):
        assert probe._emit("d")
    assert not probe._emit("d")
    probe._finish("INCONCLUSIVE", "widget_disabled")
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert len(records) == 24
    assert "result=INCONCLUSIVE reason=widget_disabled" in records[-1]


def test_stage3_probe_supported_verdicts_and_samples_fit_derived_reservations(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    probe = _prepare_stage3_probe_harness(monkeypatch, runtime, module)[3]
    source_path = _REPO_ROOT / "Widgets/Coding/Debug/Py4GW/Stage 3 Evidence Probe.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    reasons = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_finish":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                reasons.add(node.args[1].value)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
            fields = node.value.elts
            if len(fields) == 2 and all(isinstance(field, ast.Constant) for field in fields):
                if isinstance(fields[1], ast.Constant) and isinstance(fields[1].value, str):
                    reasons.add(fields[1].value)
    reasons.update(
        ("outpost_baseline_not_established", "loading_not_observed", "stable_destination_samples_incomplete")
    )
    for reason in reasons:
        assert len(reason) <= probe._MAX_REASON_CHARACTERS, reason
        for result in ("FAILURE", "INCONCLUSIVE", "FULL_SUCCESS", "SAFE_UNKNOWN"):
            details = probe._final_details(result, reason, probe._WIDEST_COUNTER, 1, 3)
            assert len(probe._record("final", details)) + 1 <= probe._FINAL_OUTPUT_RESERVE, details
    assert probe._REQUIRED_EVIDENCE_CHARACTERS == 793
    assert probe._FINAL_OUTPUT_RESERVE == 152


@pytest.mark.parametrize("runtime_expired", (False, True))
def test_stage3_probe_replaced_attempt_cannot_flush_previous_partial_samples(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    runtime_expired: bool,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    assert probe._destination_samples == 1
    if runtime_expired:
        clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    else:
        clock.advance(0.26)
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    replacement_context = _fresh_stage3_outpost_context(harness, module)
    evidence = recorder.capture_snapshot(replacement_context, replacement_context.GetSnapshot())
    assert evidence is not None
    new_attempt_id = recorder.begin(replacement_context, evidence)
    assert new_attempt_id is not None and new_attempt_id != probe._attempt_id
    probe.update()
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert not any("event=destination_sample " in record for record in records)
    assert "result=INCONCLUSIVE reason=validation_attempt_expired_or_replaced" in records[-1]
    assert "samples=0/3" in records[-1]
    assert recorder.active_attempt_id(replacement_context) == new_attempt_id


def _interrupt_stage3_finalization_output(
    monkeypatch: pytest.MonkeyPatch, probe: Any, target: str, failures: int | None = 1
) -> dict[str, int]:
    state = {"remaining": failures if failures is not None else -1, "attempts": 0}

    def should_fail() -> bool:
        state["attempts"] += 1
        if state["remaining"] == 0:
            return False
        if state["remaining"] > 0:
            state["remaining"] -= 1
        return True

    if target == "final_refused":
        original_emit = probe._emit

        def refuse_final(event: str, details: str = "", *, final: bool = False, reserved: bool = False) -> bool:
            if final and should_fail():
                return False
            return original_emit(event, details, final=final, reserved=reserved)

        monkeypatch.setattr(probe, "_emit", refuse_final)
    else:
        console = getattr(sys.modules["PySystem"], "Console")
        original_log = console.Log
        if target == "all_exception":
            record = probe._PREFIX
        elif target == "optional_exception":
            record = "event=outpost_detail "
        elif target == "final_exception":
            record = "event=final "
        else:
            record = f"event=destination_sample {target[-1]}/3 "

        def interrupt_log(sender: str, message: str, message_type: object) -> None:
            if sender == probe.MODULE_NAME and record in message and should_fail():
                raise RuntimeError("private-output-failure@example.invalid")
            original_log(sender, message, message_type)

        monkeypatch.setattr(console, "Log", interrupt_log)
    return state


@pytest.mark.parametrize("target", ("sample_1", "sample_2", "final_exception", "final_refused"))
def test_stage3_probe_retries_confirmed_terminal_output_failures_without_losing_verdict(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe, clock = harness[3:5]
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _queue_stage3_destination_refresh(harness)
    _queue_stage3_destination_refresh(harness)
    _queue_stage3_remote_player_contradiction(harness, module)
    interruption = _interrupt_stage3_finalization_output(monkeypatch, probe, target)
    probe.update()
    pending = getattr(probe, "_terminal_outcome", None)
    first_output = capsys.readouterr().out
    assert not probe._finished
    assert "event=final " not in first_output
    first_samples = tuple(line for line in first_output.splitlines() if "event=destination_sample " in line)
    expected_printed = 0 if target == "sample_1" else 1 if target == "sample_2" else 3
    assert len(first_samples) == expected_printed, first_output
    first_lines, first_characters = probe._lines, probe._characters
    clock.advance(1.01)
    probe.update()
    output = first_output + capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert "result=FAILURE reason=remote_player_role_contradicts_outpost_baseline" in records[-1], output
    assert pending is not None
    assert (pending.result, pending.reason) == ("FAILURE", "remote_player_role_contradicts_outpost_baseline")
    assert probe._terminal_outcome is pending
    assert probe._lines >= first_lines and probe._characters >= first_characters
    assert len(records) == len(set(records)), output
    assert len([record for record in records if "event=destination_sample " in record]) == 3, output
    assert interruption["attempts"] == 2
    assert "private-output-failure@example.invalid" not in output
    assert "validation_attempt_expired_or_replaced" not in output
    assert probe._finished


def _assert_stage3_pending_finalization(probe: Any, output: str, result: str, reason: str) -> None:
    records = [line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 ")]
    assert len(records) == probe._lines <= 24, output
    assert sum(len(line) + 1 for line in records) == probe._characters <= probe._MAX_OUTPUT_CHARACTERS, output
    assert not any("event=final " in record for record in records), output
    assert not probe._finished
    assert (probe._terminal_outcome.result, probe._terminal_outcome.reason) == (result, reason)
    samples = [record for record in records if "event=destination_sample " in record]
    assert len(samples) == len(set(samples)), output
    observed = len(samples) + len(probe._pending_destination_sample_details)
    if result == "FAILURE":
        # Delivery can retain historical sample records after their acceptance
        # was retired. The terminal verdict must show zero supporting samples.
        assert probe._destination_samples == 0 and observed <= 3
        assert "samples=0/3" in probe._terminal_outcome.details
    else:
        assert observed == probe._destination_samples


@pytest.mark.parametrize("target", ("sample_2", "final_exception", "final_refused"))
def test_stage3_probe_repeated_terminal_output_failures_preserve_acknowledged_progress(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe, clock = harness[3:5]
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _queue_stage3_destination_refresh(harness)
    _queue_stage3_destination_refresh(harness)
    _queue_stage3_remote_player_contradiction(harness, module)
    interruption = _interrupt_stage3_finalization_output(monkeypatch, probe, target, failures=3)
    probe.update()
    output = capsys.readouterr().out
    pending = probe._terminal_outcome
    accounting = (probe._lines, probe._characters, probe._required_lines, probe._required_characters)
    for _ in range(3):
        _assert_stage3_pending_finalization(probe, output, "FAILURE", "remote_player_role_contradicts_outpost_baseline")
        assert probe._terminal_outcome is pending
        assert (probe._lines, probe._characters, probe._required_lines, probe._required_characters) == accounting
        # Competing finish requests cannot replace an already determined result.
        probe._finish("INCONCLUSIVE", "validation_attempt_expired_or_replaced")
        clock.advance(1.01)
        probe.update()
        output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert len(records) == len(set(records)), output
    assert len([record for record in records if "event=destination_sample " in record]) == 3
    assert "result=FAILURE reason=remote_player_role_contradicts_outpost_baseline" in records[-1]
    assert interruption["attempts"] == 4
    assert probe._terminal_outcome is pending


@pytest.mark.parametrize("target", ("final_exception", "final_refused"))
@pytest.mark.parametrize("result", ("FULL_SUCCESS", "INCONCLUSIVE"))
def test_stage3_probe_completed_destination_output_recovers_after_collection_timeout(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
    result: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    probe, clock = harness[3:5]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    original_witness = runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills
    if result == "INCONCLUSIVE":
        remote_hero = next(hero for hero in runtime.heroes if hero.owner_player_id == 22)
        runtime.bars[remote_hero.agent_id] = tuple(9000 + i for i in range(8))
        _interrupt_stage3_finalization_output(monkeypatch, probe, target)
    _probe_enter_destination(harness, witness_skillbars={(22, 7): original_witness})
    if result == "FULL_SUCCESS":
        _probe_sample_destination(harness)
        _interrupt_stage3_finalization_output(monkeypatch, probe, target)
        _probe_sample_destination(harness)
    output = capsys.readouterr().out
    reason = "three_stable_destination_samples" if result == "FULL_SUCCESS" else "production_transition_retired"
    _assert_stage3_pending_finalization(probe, output, result, reason)
    pending = probe._terminal_outcome
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS + 1.0
    probe.update()
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert f"result={result} reason={reason}" in records[-1]
    assert len(records) == len(set(records))
    assert probe._terminal_outcome is pending


@pytest.mark.parametrize("sample_count", (1, 2))
@pytest.mark.parametrize("target", ("sample_1", "final_exception", "final_refused"))
def test_stage3_probe_partial_timeout_output_resumes_without_fabricating_samples(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    sample_count: int,
    target: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe, clock = harness[3:5]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    if sample_count == 2:
        _probe_sample_destination(harness)
    original_samples = tuple(probe._pending_destination_sample_details)
    _interrupt_stage3_finalization_output(monkeypatch, probe, target)
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    output = capsys.readouterr().out
    _assert_stage3_pending_finalization(probe, output, "INCONCLUSIVE", "stable_destination_samples_incomplete")
    pending = probe._terminal_outcome
    clock.advance(1.01)
    probe.update()
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    samples = tuple(
        record.split("event=destination_sample ", 1)[1] for record in records if "event=destination_sample " in record
    )
    assert samples == original_samples and len(samples) == sample_count
    assert "result=INCONCLUSIVE reason=stable_destination_samples_incomplete" in records[-1]
    assert f"samples={sample_count}/3" in records[-1]
    assert probe._terminal_outcome is pending


@pytest.mark.parametrize("target", ("sample_1", "final_refused"))
def test_stage3_probe_pending_verdict_ignores_ended_replaced_recorder_and_later_invalidation(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _queue_stage3_remote_player_contradiction(harness, module)
    _interrupt_stage3_finalization_output(monkeypatch, probe, target)
    probe.update()
    output = capsys.readouterr().out
    _assert_stage3_pending_finalization(probe, output, "FAILURE", "remote_player_role_contradicts_outpost_baseline")
    pending = probe._terminal_outcome
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    assert recorder.active_attempt_id(context) is None
    replacement_context = _fresh_stage3_outpost_context(harness, module)
    evidence = recorder.capture_snapshot(replacement_context, replacement_context.GetSnapshot())
    assert evidence is not None
    new_attempt_id = recorder.begin(replacement_context, evidence)
    assert new_attempt_id is not None and new_attempt_id != probe._attempt_id
    context.InvalidatePublishedSnapshot()

    def forbid_collection(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("pending finalization must not read or reclassify collection evidence")

    for method in ("heartbeat", "read_events", "read_refresh_events", "active_attempt_id", "end"):
        monkeypatch.setattr(recorder, method, forbid_collection)
    monkeypatch.setattr(context, "GetSnapshot", forbid_collection)
    monkeypatch.setattr(probe, "_phase", forbid_collection)
    monkeypatch.setattr(probe, "_classify_destination", forbid_collection)
    clock.advance(1.01)
    probe.update()
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert "result=FAILURE reason=remote_player_role_contradicts_outpost_baseline" in records[-1]
    assert probe._terminal_outcome is pending
    assert recorder._active.attempt_id == new_attempt_id


@pytest.mark.parametrize("target", ("all_exception", "final_refused"))
def test_stage3_probe_permanent_output_failure_retains_truth_and_throttles_retries(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe, clock = harness[3:5]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _queue_stage3_remote_player_contradiction(harness, module)
    interruption = _interrupt_stage3_finalization_output(monkeypatch, probe, target, failures=None)
    probe.update()
    output = capsys.readouterr().out
    pending = probe._terminal_outcome
    accounting = (probe._lines, probe._characters, probe._required_lines, probe._required_characters)
    remaining = tuple(probe._pending_destination_sample_details)
    for cycle in range(5):
        clock.value = probe._next_finalization_retry_at - 0.001
        for _ in range(100):
            probe.update()
        probe.on_disable()
        probe.on_enable()
        assert interruption["attempts"] == cycle + 1
        clock.value = probe._next_finalization_retry_at
        probe.update()
        assert interruption["attempts"] == cycle + 2
        output += capsys.readouterr().out
        _assert_stage3_pending_finalization(probe, output, "FAILURE", "remote_player_role_contradicts_outpost_baseline")
        assert probe._terminal_outcome is pending
        assert tuple(probe._pending_destination_sample_details) == remaining
        assert (probe._lines, probe._characters, probe._required_lines, probe._required_characters) == accounting
    assert "private-output-failure@example.invalid" not in output
    assert "event=activation " not in output


def test_stage3_probe_optional_output_exception_cannot_block_required_output(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe = harness[3]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    interruption = _interrupt_stage3_finalization_output(monkeypatch, probe, "optional_exception")
    _probe_sample_destination(harness)
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert probe._finished and interruption["attempts"] == 1
    assert len([record for record in records if "event=destination_sample " in record]) == 3
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in records[-1]


def test_stage3_probe_new_attempt_resets_finalization_state_only_after_delivery(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    interruption = _interrupt_stage3_finalization_output(monkeypatch, probe, "final_exception")
    _probe_sample_destination(harness)
    output = capsys.readouterr().out
    pending, first_attempt = probe._terminal_outcome, probe._attempt_id
    # Re-enable while pending resumes the old output instead of erasing it.
    clock.advance(1.01)
    probe.on_enable()
    output += capsys.readouterr().out
    _assert_stage3_output_budget(probe, output)
    assert probe._finished and probe._terminal_outcome is pending
    assert "event=activation " not in output
    assert interruption["attempts"] == 2
    probe.on_enable()
    assert probe._terminal_outcome is None and probe._terminal_details is None
    assert probe._next_finalization_retry_at == 0.0
    assert probe._required_lines == probe._required_characters == probe._destination_samples == 0
    runtime.ready, runtime.outpost, runtime.explorable, runtime.map_id = True, True, False, 1
    runtime.publication_result = _remote_publication(runtime, module)
    _probe_enter_outpost(harness)
    assert probe._attempt_id is not None and probe._attempt_id != first_attempt
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in records[-1]
    assert len([record for record in records if "event=destination_sample " in record]) == 3


@pytest.mark.parametrize("target", ("final_exception", "final_refused"))
@pytest.mark.parametrize("boundary", ("characters", "lines"))
def test_stage3_probe_finalization_retry_preserves_real_cap_boundaries(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
    boundary: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe, clock = harness[3:5]
    if boundary == "characters":
        harness[5].STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._next_attempt_id = (1 << 64) - 2
        _probe_enter_outpost(harness)
        optional = probe._MAX_OUTPUT_CHARACTERS - probe._REQUIRED_EVIDENCE_CHARACTERS - probe._FINAL_OUTPUT_RESERVE
        for reserved, remaining in (
            (False, optional - probe._optional_characters),
            (True, probe._REQUIRED_EVIDENCE_CHARACTERS - probe._required_characters),
        ):
            assert probe._emit("padding", "x" * (remaining - len(probe._record("padding")) - 2), reserved=reserved)
        reason = "remote_player_role_contradicts_outpost_baseline"
    else:
        # Exercise the sealed-output line guard independently of record length.
        probe._terminal_details = probe._final_details("INCONCLUSIVE", "widget_disabled", "none", 0, 0)
        for _ in range(23):
            assert probe._emit("d")
        reason = "widget_disabled"
    _interrupt_stage3_finalization_output(monkeypatch, probe, target)
    accounting = (probe._lines, probe._characters)
    probe._finish("INCONCLUSIVE", reason)
    assert (probe._lines, probe._characters) == accounting
    assert not probe._finished
    output = capsys.readouterr().out
    pending = probe._terminal_outcome
    clock.advance(1.01)
    probe.update()
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert f"result=INCONCLUSIVE reason={reason}" in records[-1]
    assert probe._terminal_outcome is pending
    assert probe._characters == probe._MAX_OUTPUT_CHARACTERS if boundary == "characters" else probe._lines == 24


@pytest.mark.parametrize(
    "blocker",
    (
        "missing_baselines",
        "unknown_roles",
        "snapshot",
        "phase",
        "sixth_state",
        "remote_player",
        "snapshot_at_deadline",
        "phase_at_deadline",
        "members",
        "late_callback",
    ),
)
def test_stage3_probe_blocked_preflight_reports_latest_evidence_at_ten_seconds(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    blocker: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    probe.on_enable()
    upkeeper.main()
    original = context.GetSnapshot()
    local_members = tuple(
        member
        for member in original.members
        if member.evidence_source in (module.EvidenceSource.LOCAL_PLAYER, module.EvidenceSource.LOCAL_HERO)
    )
    saved_baselines = context._baselines.copy()

    def forbid_runtime_reads(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("blocked preflight must use published evidence without refreshing or reading Native witnesses")

    monkeypatch.setattr(context, "Refresh", forbid_runtime_reads)
    monkeypatch.setattr(cache, "_update_cache", forbid_runtime_reads)
    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", forbid_runtime_reads)
    if blocker == "sixth_state":
        for missing in (5, 4, 3, 2, 1):
            context._baselines = saved_baselines.copy()
            for member in local_members[1 : missing + 1]:
                context._baselines.pop(member.identity.stable_key)
            probe.update()
            clock.advance(1.01)
        assert len(probe._pending_outpost_details) == 5
    if blocker in ("missing_baselines", "unknown_roles", "sixth_state"):
        for member in local_members[1:]:
            context._baselines.pop(member.identity.stable_key, None)
    if blocker in ("unknown_roles", "sixth_state"):
        reasons = (
            "skillbar evidence is incomplete",
            "multiple supported elite anchors make the role ambiguous",
            "no matching ready-outpost baseline",
            "skillbar ownership is ambiguous",
            "no supported role anchor private-character@example.invalid",
        )
        changed = {member.identity.stable_key: reason for member, reason in zip(local_members[1:], reasons)}
        members = tuple(
            (
                replace(
                    member,
                    role=module.CleansingRole.UNKNOWN,
                    candidate_role=module.CleansingRole.UNKNOWN,
                    reason=changed[member.identity.stable_key],
                )
                if member.identity.stable_key in changed
                else (
                    replace(
                        member,
                        role=module.CleansingRole.UNKNOWN,
                        candidate_role=module.CleansingRole.UNKNOWN,
                        reason="remote hero witness is unavailable private-character@example.invalid",
                    )
                    if member.evidence_source is module.EvidenceSource.REMOTE_HERO
                    else member
                )
            )
            for member in original.members
        )
        _replace_stage3_snapshot_members(context, module, members)
    elif blocker == "snapshot":
        context.InvalidatePublishedSnapshot("runtime lifecycle is unsafe; private-character@example.invalid")
    elif blocker == "phase":
        monkeypatch.setattr(probe, "_phase", lambda: "unknown")
    elif blocker == "remote_player":
        _replace_stage3_snapshot_members(
            context,
            module,
            tuple(
                (
                    replace(
                        member,
                        role=module.CleansingRole.UNKNOWN,
                        candidate_role=module.CleansingRole.UNKNOWN,
                        reason="no supported role anchor private-character@example.invalid",
                    )
                    if member.evidence_source is module.EvidenceSource.REMOTE_PLAYER
                    else member
                )
                for member in original.members
            ),
        )
    elif blocker.endswith("_at_deadline"):
        context._baselines.clear()
    elif blocker == "members":
        _replace_stage3_snapshot_members(context, module, ())
    elif blocker == "late_callback":
        context._baselines.clear()
    probe.update()
    assert probe._started_at is not None
    clock.value = probe._started_at + 9.99
    probe.update()
    output = capsys.readouterr().out
    assert "event=final " not in output
    assert probe._attempt_id is None and not probe._finished
    clock.value = probe._started_at + 10.0
    if blocker == "snapshot_at_deadline":
        context.InvalidatePublishedSnapshot()
    elif blocker == "phase_at_deadline":
        monkeypatch.setattr(probe, "_phase", lambda: "unknown")
    elif blocker == "late_callback":
        clock.value = probe._started_at + 200.0
        context.InvalidatePublishedSnapshot()
    probe.update()
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert len(records) == 4, output
    assert sum("event=no_go " in record for record in records) == 1
    detail = records[-2]
    assert "event=outpost_detail " in detail
    if blocker in ("missing_baselines", "unknown_roles", "sixth_state"):
        assert "LP:HR/1," in detail and detail.count("/0") == 5, output
        assert "P=BiP pub=1 base=1" in detail
        assert "witness=not_run" in detail and "stage4=FALLBACK" in detail
        if blocker == "missing_baselines":
            assert "base_missing" in detail and "fence=1" in detail
        else:
            for reason in ("bar_incomplete", "anchor_ambiguous", "base_missing", "ownership", "no_anchor"):
                assert reason in detail, output
            assert "H=UNKNOWN r=witness" in detail and "u=7 fence=0" in detail
    elif blocker == "remote_player":
        assert "P=UNKNOWN pub=1 base=1 r=no_anchor" in detail and "wait=remote_role" in detail
        assert "H=ES" in detail and "witness=not_run" in detail
    else:
        reason = (
            "map_not_ready"
            if blocker.startswith("phase")
            else "members" if blocker == "members" else "snapshot_not_ready"
        )
        assert f"wait={reason}" in detail
        assert "LP:" not in detail and "H1:" not in detail
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in records[-1]
    assert "attempt=none loading=0 samples=0/3" in records[-1]
    assert "private-character" not in output
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
    outcome = probe._terminal_outcome
    context._baselines.update(saved_baselines)
    clock.advance(100.0)
    probe.update()
    assert capsys.readouterr().out == "" and probe._terminal_outcome is outcome
    probe.on_enable()
    assert probe._terminal_outcome is None and not probe._finished and probe._started_at == clock.read()


def test_stage3_probe_recovered_preflight_keeps_normal_validation_duration_and_full_success(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    probe.on_enable()
    _extend_stage3_probe_test_lease(harness, monkeypatch)
    upkeeper.main()
    saved = context._baselines.copy()
    context._baselines.clear()
    probe.update()
    clock.advance(9.0)
    context._baselines.update(saved)
    probe.update()
    assert probe._attempt_id is not None
    for _ in range(161):
        clock.advance(1.0)
        probe.update()
    assert not probe._finished and probe._terminal_outcome is None
    assert probe._REQUIRED_EVIDENCE_CHARACTERS == 793 and probe._FINAL_OUTPUT_RESERVE == 152
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in records[-1]
    assert len([record for record in records if "event=destination_sample " in record]) == 3
    assert len([record for record in records if "event=loading " in record]) == 1


def test_stage3_probe_preflight_deadline_requires_update_execution(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    probe, clock = harness[3:5]
    probe.on_enable()
    activated = clock.read()
    clock.advance(1000.0)
    output = capsys.readouterr().out
    assert output.splitlines() == ["STAGE3_EVIDENCE_V1 event=activation state=enabled source=widget_browser"]
    assert probe._started_at == activated and probe._terminal_outcome is None and not probe._finished
    probe.update()
    assert probe._started_at == activated and probe._terminal_outcome.result == "INCONCLUSIVE"
    assert probe._terminal_outcome.reason == "outpost_baseline_not_established"
    assert "event=final result=INCONCLUSIVE" in capsys.readouterr().out


@pytest.mark.parametrize("observed_at", (9.99, 10.0, 10.01, 30.0, 179.99, 180.0, 200.0))
def test_stage3_probe_baseline_eligibility_respects_preflight_and_overall_deadlines(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    observed_at: float,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    probe.on_enable()
    upkeeper.main()
    saved = context._baselines.copy()
    context._baselines.clear()
    probe.update()
    context._baselines.update(saved)
    clock.advance(observed_at)
    probe.update()
    output = capsys.readouterr().out
    if observed_at >= probe._MAX_RUNTIME_SECONDS:
        records = _assert_stage3_output_budget(probe, output)
        assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in records[-1], output
        assert "event=outpost created" not in output
        assert probe._outpost_baseline is None and probe._attempt_id is None
        assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
        assert "LP:HR/1,H1:ST/1,H2:IN/1,H3:ES/1,H4:ES/1,H5:ES/1" in records[-2]
        return
    assert "event=outpost created roster=8/8" in output, output
    assert "event=final " not in output, output
    assert probe._attempt_id is not None and probe._terminal_outcome is None
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) == probe._attempt_id
    assert probe._started_at == 100.0
    if observed_at >= probe._MAX_RUNTIME_SECONDS - probe._POLL_SECONDS:
        # Eligibility just before expiry does not restart the overall runtime cap.
        clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
        probe.update()
        expected = "result=INCONCLUSIVE reason=loading_not_observed"
    else:
        _probe_enter_loading(harness)
        _probe_enter_destination(harness)
        _probe_sample_destination(harness)
        _probe_sample_destination(harness)
        expected = "result=FULL_SUCCESS reason=three_stable_destination_samples"
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert expected in records[-1], output
    assert "outpost_baseline_not_established" not in output


@pytest.mark.parametrize("target", ("optional_exception", "detail_refused", "final_exception", "final_refused"))
def test_stage3_probe_blocked_preflight_finalization_retries_required_latest_diagnostic(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    target: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    probe.on_enable()
    upkeeper.main()
    context._baselines.clear()
    probe.update()
    if target == "detail_refused":
        original_emit = probe._emit
        retry_at = probe._started_at + 11.0

        def refuse_detail(event: str, details: str = "", *, final: bool = False, reserved: bool = False) -> bool:
            if event == "outpost_detail" and clock.read() < retry_at:
                return False
            return original_emit(event, details, final=final, reserved=reserved)

        monkeypatch.setattr(probe, "_emit", refuse_detail)
    else:
        _interrupt_stage3_finalization_output(monkeypatch, probe, target)
    clock.value = probe._started_at + 10.0
    probe.update()
    output = capsys.readouterr().out
    _assert_stage3_pending_finalization(probe, output, "INCONCLUSIVE", "outpost_baseline_not_established")
    pending = probe._terminal_outcome
    assert (pending.result, pending.reason) == ("INCONCLUSIVE", "outpost_baseline_not_established")
    if target == "optional_exception":
        assert len(probe._pending_outpost_details) == 1
        assert probe._lines == 2
        assert probe._characters == 72 + len(probe._record("no_go", "reason=outpost_baseline_not_established")) + 1

    def forbid_recollection(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("a pending preflight verdict must only resume its retained output")

    monkeypatch.setattr(probe, "_phase", forbid_recollection)
    monkeypatch.setattr(context, "GetSnapshot", forbid_recollection)
    clock.advance(1.01)
    probe.update()
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert len(records) == 4 and len(records) == len(set(records)), output
    assert "event=outpost_detail " in records[-2] and "LP:HR/0/base_missing" in records[-2]
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in records[-1]
    assert probe._terminal_outcome is pending


@pytest.mark.parametrize("restoration", ("direct", "production_refresh"))
def test_stage3_probe_near_deadline_throttled_recovery_keeps_full_validation_eligibility(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    restoration: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    probe.on_enable()
    upkeeper.main()
    saved = context._baselines.copy()
    assert len(saved) == 6
    local_player = next(
        member
        for member in context.GetSnapshot().members
        if member.evidence_source is module.EvidenceSource.LOCAL_PLAYER
    )
    context._baselines = {local_player.identity.stable_key: saved[local_player.identity.stable_key]}
    probe.update()
    started_at = probe._started_at
    clock.value = started_at + 9.90
    probe.update()
    assert probe._attempt_id is None and probe._last_poll_at == clock.read()
    refresh_attempts = context._refresh_diagnostic_attempts
    clock.value = started_at + 9.99
    if restoration == "direct":
        context._baselines.update(saved)
    else:
        upkeeper.main()
        assert context._refresh_diagnostic_attempts == refresh_attempts + 1
    assert len(context._baselines) == 6
    assert probe._outpost_is_baseline(probe._snapshot_evidence(context.GetSnapshot(), context))
    probe.update()
    assert probe._last_poll_at == started_at + 9.90
    assert probe._attempt_id is None and probe._terminal_outcome is None
    output = capsys.readouterr().out
    records = [line for line in output.splitlines() if line.startswith("STAGE3_EVIDENCE_V1 ")]
    assert len(records) == 1 and "event=activation " in records[0], output
    clock.value = started_at + 10.00
    probe.update()
    output += capsys.readouterr().out
    assert "event=outpost created roster=8/8" in output, output
    assert "event=final " not in output, output
    assert probe._attempt_id is not None and probe._terminal_outcome is None
    assert probe._started_at == started_at and probe._MAX_RUNTIME_SECONDS == 180.0
    for _ in range(160):
        clock.advance(1.0)
        probe.update()
    assert clock.read() == started_at + 170.0 and not probe._finished
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    output += capsys.readouterr().out
    records = _assert_stage3_output_budget(probe, output)
    assert "result=FULL_SUCCESS reason=three_stable_destination_samples" in records[-1], output
    samples = [record for record in records if "event=destination_sample " in record]
    assert len(samples) == len(set(samples)) == 3, output
    refreshes = [record.split("refresh=", 1)[1].split(" ", 1)[0] for record in samples]
    assert len(set(refreshes)) == 3
    assert len([record for record in records if "event=loading " in record]) == 1
    assert probe._required_lines == 6


@pytest.mark.parametrize("observed_at", (180.0, 200.0))
@pytest.mark.parametrize("emission", ("success", "optional_exception", "final_refused"))
def test_stage3_probe_overall_expiry_cannot_open_new_baseline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    observed_at: float,
    emission: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    probe.on_enable()
    upkeeper.main()
    context._baselines.clear()
    probe.update()
    started_at = probe._started_at
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    next_attempt_id = recorder._next_attempt_id
    clock.value = started_at + observed_at - 0.01
    refresh_attempts = context._refresh_diagnostic_attempts
    upkeeper.main()
    assert context._refresh_diagnostic_attempts == refresh_attempts + 1
    assert len(context._baselines) == 6
    assert probe._outpost_is_baseline(probe._snapshot_evidence(context.GetSnapshot(), context))

    def forbid_new_attempt(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("an expired attempt must not read Native witnesses, reopen collection, or reclassify on retry")

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", forbid_new_attempt)
    if emission != "success":
        _interrupt_stage3_finalization_output(monkeypatch, probe, emission)
    clock.value = started_at + observed_at
    probe.update()
    output = capsys.readouterr().out
    assert "event=outpost created" not in output, output
    assert probe._outpost_baseline is None and probe._attempt_id is None
    assert recorder.active_attempt_id(context) is None
    assert recorder._next_attempt_id == next_attempt_id
    assert probe._started_at == started_at
    pending = probe._terminal_outcome
    assert (pending.result, pending.reason) == ("INCONCLUSIVE", "outpost_baseline_not_established")
    monkeypatch.setattr(recorder, "begin", forbid_new_attempt)
    monkeypatch.setattr(probe, "_phase", forbid_new_attempt)
    monkeypatch.setattr(context, "GetSnapshot", forbid_new_attempt)
    if emission != "success":
        _assert_stage3_pending_finalization(probe, output, "INCONCLUSIVE", "outpost_baseline_not_established")
        clock.advance(1.01)
        probe.update()
        output += capsys.readouterr().out
        assert probe._terminal_outcome is pending
    records = _assert_stage3_output_budget(probe, output)
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in records[-1], output
    assert "LP:HR/1,H1:ST/1,H2:IN/1,H3:ES/1,H4:ES/1,H5:ES/1" in records[-2]
    assert "P=BiP pub=1 base=1 H=ES" in records[-2] and "witness=not_run" in records[-2]
    assert "base_missing" not in output
    clock.advance(1.0)
    probe.update()
    assert capsys.readouterr().out == "" and probe._terminal_outcome is pending
    assert recorder._next_attempt_id == next_attempt_id


@pytest.mark.parametrize("destination", (False, True), ids=("outpost", "destination"))
@pytest.mark.parametrize("closing_publication", (2, 3), ids=("first_closing", "second_closing"))
@pytest.mark.parametrize(
    "mutation",
    (
        "agent",
        "account",
        "hero_id",
        "loading",
        "bar",
        "login",
        "character",
        "uuid",
        "hwnd",
        "party",
        "map",
        "position",
        "player_bar",
        "not_ready",
        "profession",
    ),
)
def test_stage3_final_publication_read_review_race(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    destination: bool,
    mutation: str,
    closing_publication: int,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if destination:
        assert all(member.role is not module.CleansingRole.UNKNOWN for member in context.Refresh().members)
        _witness_enter_destination(runtime, module, context)
    publication_reads = 0

    def mutate() -> None:
        nonlocal publication_reads
        publication_reads += 1
        if publication_reads != closing_publication:
            return
        if mutation == "agent":
            runtime.agent_id = 2001
        elif mutation == "account":
            runtime.account_email = "replacement@example.test"
        elif mutation == "hero_id":
            runtime.heroes[0].hero_id = 99
        elif mutation == "loading":
            runtime.ready = False
            runtime.instance_type_override = 2
        elif mutation == "bar":
            runtime.bars[4000] = tuple(range(9000, 9008))
        elif mutation == "login":
            runtime.players[0].login_number = 33
            runtime.local_agent_by_login[33] = runtime.local_agent_by_login.pop(11)
        elif mutation == "character":
            runtime.character_name = "Replacement"
        elif mutation == "uuid":
            runtime.local_uuid = (999, 0, 0, 0)
        elif mutation == "hwnd":
            runtime.local_hwnd += 1
        elif mutation == "party":
            runtime.party_id += 1
        elif mutation == "map":
            runtime.map_id += 1
        elif mutation == "position":
            runtime.hero_agent_by_position_override[1] = 4001
        elif mutation == "player_bar":
            runtime.bars[1001] = tuple(range(9100, 9108))
        elif mutation == "not_ready":
            runtime.missing_map_contexts.add("map")
        elif mutation == "profession":
            runtime.professions[1001] = int(module.Profession.Mesmer)

    runtime.publication_mutator = mutate
    snapshot = context.Refresh()
    expected_reads = 3 if mutation == "player_bar" else closing_publication
    assert publication_reads == expected_reads, (destination, mutation, publication_reads)
    assert not snapshot.ready, (destination, mutation, snapshot)
    assert len(snapshot.members) == 8 and all(
        member.role is module.CleansingRole.UNKNOWN for member in snapshot.members
    ), snapshot
    assert not context._baselines, context._baselines
    assert not context._remote_player_baselines
    assert not context._remote_hero_origins
    expected = (
        "controlled player changed during closing"
        if mutation in {"agent", "account", "login"}
        else "runtime evidence changed during closing"
    )
    assert snapshot.reason == expected, snapshot


def test_stage3_final_publication_read_review_living_identity_race(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    runtime.unavailable_agents.clear()
    publication_reads = 0

    def mutate() -> None:
        nonlocal publication_reads
        publication_reads += 1
        if publication_reads == 2:
            runtime.agent_id = 2001

    runtime.publication_mutator = mutate
    snapshot = context.Refresh()
    assert publication_reads == 2
    assert not snapshot.ready and snapshot.reason == "controlled player changed during closing", snapshot
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members), snapshot
    assert not context._baselines
    assert not context._remote_player_baselines
    assert not context._remote_hero_origins


@pytest.mark.parametrize("mutation", ("agent", "account", "bar", "loading"))
def test_stage3_final_boundary_living_locals_without_publication_authority(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    _add_hero(runtime, module, module.CleansingRole.ENERGY_SURGE, hero_id=7, agent_id=4000)
    context = module.CleansingContext()
    publication_reads = 0

    def mutate() -> None:
        nonlocal publication_reads
        publication_reads += 1
        if mutation == "agent":
            runtime.agent_id = 2001
        elif mutation == "account":
            runtime.account_email = "replacement@example.test"
        elif mutation == "bar":
            runtime.bars[4000] = tuple(range(9000, 9008))
        else:
            runtime.instance_type_override = 2

    runtime.publication_mutator = mutate
    snapshot = context.Refresh()
    assert publication_reads == 1 and not snapshot.ready, snapshot
    assert len(snapshot.members) == 2 and all(
        member.role is module.CleansingRole.UNKNOWN for member in snapshot.members
    )
    assert not context._baselines
    assert snapshot.reason == (
        "controlled player changed during closing"
        if mutation in {"agent", "account"}
        else "runtime evidence changed during closing"
    )


@pytest.mark.parametrize("mutation", ("agent", "hero_id"))
def test_stage3_final_boundary_rejects_mixed_runtime_collection(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    char_api = sys.modules["Py4GWCoreLib.Context"].GWContext.Char
    original_char = char_api.GetContext
    reads = 0
    armed = False
    changed = False

    class MixedChar:
        def __init__(self, snapshot: Any) -> None:
            self.snapshot = snapshot

        def __getattr__(self, name: str) -> Any:
            nonlocal changed
            value = getattr(self.snapshot, name)
            if armed and not changed and name == "player_name_str":
                # The actual closing helper has already copied controlled identity
                # and roster when it asks for this field.
                changed = True
                if mutation == "agent":
                    runtime.agent_id = 2001
                else:
                    runtime.heroes[0].hero_id = 99
            return value

    monkeypatch.setattr(char_api, "GetContext", lambda: MixedChar(original_char()))

    def arm() -> None:
        nonlocal armed, reads
        reads += 1
        armed = reads == 3

    runtime.publication_mutator = arm
    snapshot = context.Refresh()
    assert reads == 3 and changed
    assert not snapshot.ready and all(
        member.role is module.CleansingRole.UNKNOWN for member in snapshot.members
    ), snapshot
    assert not context._baselines
    assert snapshot.reason == (
        "controlled player changed during closing" if mutation == "agent" else "runtime evidence changed during closing"
    )


@pytest.mark.parametrize("mutation", ("bar", "remote_endpoint"))
def test_stage3_final_boundary_rejects_evidence_changed_after_its_first_copy(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if mutation == "remote_endpoint":
        context.Refresh()
        _witness_enter_destination(runtime, module, context)
    skillbar = sys.modules["PySkillbar"].Skillbar
    original_read = skillbar.GetHeroSkillbar
    reads = 0
    changed = False

    def arm() -> None:
        nonlocal reads
        reads += 1

    def read_bar(self: Any, position: int) -> Any:
        nonlocal changed
        slots = original_read(self, position)
        if reads == 3 and position == 5 and not changed:
            changed = True
            if mutation == "bar":
                runtime.bars[4000] = tuple(range(9000, 9008))
            else:
                runtime.unavailable_agents.add(3001)
        return slots

    runtime.publication_mutator = arm
    monkeypatch.setattr(skillbar, "GetHeroSkillbar", read_bar)
    snapshot = context.Refresh()
    assert reads == 3 and changed
    assert not snapshot.ready and snapshot.reason == "runtime evidence changed during closing", snapshot
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members)
    if mutation == "remote_endpoint":
        assert len(context._baselines) == 6
        assert all(
            baseline.witness_origin is None or baseline.witness_origin.destination_epoch is None
            for baseline in context._baselines.values()
        )
    else:
        assert not context._baselines


@pytest.mark.parametrize("witness_backed", (False, True))
def test_stage3_final_boundary_stable_collections_are_bounded_and_recognized(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    witness_backed: bool,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if not witness_backed:
        runtime.unavailable_agents.clear()
    publication_reads = 0
    runtime_reads = 0
    original_close = module._read_closing_state

    def count_publication() -> None:
        nonlocal publication_reads
        publication_reads += 1

    def count_runtime() -> Any:
        nonlocal runtime_reads
        runtime_reads += 1
        return original_close()

    runtime.publication_mutator = count_publication
    monkeypatch.setattr(module, "_read_closing_state", count_runtime)
    snapshot = context.Refresh()
    assert (publication_reads, runtime_reads) == ((3, 4) if witness_backed else (2, 3))
    assert snapshot.ready and len(snapshot.members) == 8
    assert all(member.role is not module.CleansingRole.UNKNOWN for member in snapshot.members), snapshot
    assert len(context._baselines) == 6
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.UNKNOWN] == 2


def _copy_closing_publication(result: Any) -> Any:
    detached = copy.deepcopy(result)
    for old, new in zip(result.snapshot.cohorts, detached.snapshot.cohorts):
        for original, copied in zip((old.owner, *old.children), (new.owner, *new.children)):
            account = copy.deepcopy(original.GetAccountData())
            copied.GetAccountData = lambda account=account: account
    return detached


@pytest.mark.parametrize("destination", (False, True), ids=("outpost", "destination"))
@pytest.mark.parametrize("mutation", ("witnesses", "recovery", "incarnation"))
def test_stage3_closing_review_publication_replacement(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    destination: bool,
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if destination:
        assert all(member.role is not module.CleansingRole.UNKNOWN for member in context.Refresh().members)
        _witness_enter_destination(runtime, module, context)
    original_close = module._read_closing_state
    closing_calls = 0

    def closing() -> Any:
        nonlocal closing_calls
        closing_calls += 1
        if closing_calls == 1:
            replacement = _copy_closing_publication(runtime.publication_result)
            if mutation == "recovery":
                replacement.snapshot.recovery_epoch += 1
            for index, cohort in enumerate(replacement.snapshot.cohorts):
                if mutation == "witnesses":
                    cohort.witnesses = ()
                elif mutation == "incarnation":
                    cohort.incarnation = bytes((90 + index,)) + bytes(15)
            runtime.publication_result = replacement
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    dependent = [
        member for member in snapshot.members if member.evidence_source is not module.EvidenceSource.LOCAL_PLAYER
    ]
    assert dependent and all(member.role is module.CleansingRole.UNKNOWN for member in dependent), (
        destination,
        mutation,
        closing_calls,
        snapshot,
    )
    assert len(context._baselines) == 1, (destination, mutation, context._baselines)
    assert not context._remote_hero_origins
    assert bool(context._remote_player_baselines) is (destination and mutation == "witnesses")
    assert closing_calls == 3  # Initial closing rejection plus the final runtime double collection.


def test_stage3_closing_review_controlled_player_substitution(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    original_close = module._read_closing_state
    closing_calls = 0

    def closing() -> Any:
        nonlocal closing_calls
        closing_calls += 1
        runtime.agent_id = 2001
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members), (closing_calls, snapshot)
    assert not context._baselines, context._baselines
    assert not context._remote_hero_origins
    assert not context._remote_player_baselines
    assert closing_calls == 3


@pytest.mark.parametrize("destination", (False, True), ids=("outpost", "destination"))
@pytest.mark.parametrize("closing_pass", (1, 2))
@pytest.mark.parametrize("mutation", ("agent", "login", "account"))
def test_stage3_closing_controlled_identity_at_each_boundary(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    destination: bool,
    closing_pass: int,
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if destination:
        context.Refresh()
        _witness_enter_destination(runtime, module, context)
    original_close = module._read_closing_state
    calls = 0

    def closing() -> Any:
        nonlocal calls
        calls += 1
        if calls == closing_pass:
            if mutation == "agent":
                runtime.agent_id = 2001
            elif mutation == "login":
                runtime.players[0].login_number = 33
                runtime.local_agent_by_login[33] = runtime.local_agent_by_login.pop(11)
            else:
                runtime.account_email = "replacement@example.test"
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    assert calls == closing_pass + 2, (destination, closing_pass, mutation, calls)
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members), snapshot
    assert not context._baselines
    assert not context._remote_player_baselines
    assert not context._remote_hero_origins


@pytest.mark.parametrize("owner_index", (0, 1), ids=("remote", "local"))
@pytest.mark.parametrize(
    "destination,defect",
    [
        (destination, defect)
        for destination in (False, True)
        for defect in (
            "missing_owner",
            "duplicate_owner",
            "wrong_owner",
            "stale",
            "instance_epoch",
            "duplicate_witness",
            "original_skills",
            "original_profession",
            "revision",
            "observation",
            "child_owner",
            "child_build",
            "child_missing",
            "busy",
        )
        if destination or defect != "child_missing"
    ],
)
def test_stage3_closing_current_publication_fails_closed(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    destination: bool,
    owner_index: int,
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if destination:
        context.Refresh()
        _witness_enter_destination(runtime, module, context)
    elif defect in {"child_owner", "child_build"}:
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    replacement = _copy_closing_publication(runtime.publication_result)
    cohort = replacement.snapshot.cohorts[owner_index]
    witness = cohort.witnesses[0]
    if defect == "missing_owner":
        replacement.snapshot.cohorts = tuple(c for i, c in enumerate(replacement.snapshot.cohorts) if i != owner_index)
    elif defect == "duplicate_owner":
        replacement.snapshot.cohorts = (*replacement.snapshot.cohorts, copy.deepcopy(cohort))
    elif defect == "wrong_owner":
        cohort.owner.GetAccountData().AgentData.LoginNumber = 99
    elif defect == "stale":
        cohort.published_tick = (runtime.publication_now - 10000) & 0xFFFFFFFF
        cohort.owner.GetAccountData().LastUpdated = cohort.published_tick
    elif defect == "instance_epoch":
        cohort.instance_epoch += 1
    elif defect == "duplicate_witness":
        cohort.witnesses = (*cohort.witnesses, copy.deepcopy(witness))
    elif defect == "original_skills":
        witness.skills = (*witness.skills[:-1], witness.skills[-1] + 100)
    elif defect == "original_profession":
        witness.secondary = 8
    elif defect == "revision":
        witness.revision += 1
    elif defect == "observation":
        witness.observed_at_tick64 += 1
    elif defect == "child_owner":
        cohort.children[0].GetAccountData().AgentData.OwnerAgentID = 9999
    elif defect == "child_build":
        cohort.children[0].GetAccountData().AgentData.Skillbar.Skills[0].Id = _skill_ids(runtime, module).panic
    elif defect == "child_missing":
        cohort.children = ()
    elif defect == "busy":
        replacement = types.SimpleNamespace(status=types.SimpleNamespace(value="busy"), snapshot=None)
    original_close = module._read_closing_state

    def closing() -> Any:
        runtime.publication_result = replacement
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members[1:]), (
        destination,
        owner_index,
        defect,
        snapshot,
    )
    if destination:
        owner_contradiction = defect in {"duplicate_owner", "wrong_owner", "instance_epoch"}
        hero_contradiction = defect in {
            "duplicate_witness",
            "original_skills",
            "original_profession",
            "revision",
            "observation",
            "child_owner",
            "child_build",
        }
        expected_local = (1 if owner_contradiction else 5 if hero_contradiction else 6) if owner_index == 1 else 6
        assert len(context._baselines) == expected_local, context._baselines
        assert bool(context._remote_player_baselines) is not (owner_index == 0 and owner_contradiction)
        assert bool(context._remote_hero_origins) is not (
            owner_index == 0 and (owner_contradiction or hero_contradiction)
        )
        assert all(baseline.destination_map_id is None for baseline in context._remote_player_baselines.values())
        assert all(origin.destination_epoch is None for origin in context._remote_hero_origins.values())
        assert all(
            baseline.witness_origin is None or baseline.witness_origin.destination_epoch is None
            for baseline in context._baselines.values()
        )
    else:
        assert len(context._baselines) == 1, context._baselines
        assert not context._remote_hero_origins
        assert not context._remote_player_baselines


@pytest.mark.parametrize("destination", (False, True), ids=("outpost", "destination"))
def test_stage3_closing_publication_replacement_between_passes(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    destination: bool,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if destination:
        context.Refresh()
        _witness_enter_destination(runtime, module, context)
    original_close = module._read_closing_state
    calls = 0

    def closing() -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            runtime.publication_result = _copy_closing_publication(runtime.publication_result)
            runtime.publication_result.snapshot.recovery_epoch += 1
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    assert calls == 4
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members[1:]), snapshot
    assert len(context._baselines) == 1


@pytest.mark.parametrize("destination", (False, True), ids=("outpost", "destination"))
@pytest.mark.parametrize("outpost_child_change", ("appears", "disappears"))
def test_stage3_closing_permits_fresh_phase_specific_publication_updates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    destination: bool,
    outpost_child_change: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if destination:
        context.Refresh()
        _witness_enter_destination(runtime, module, context)
    elif outpost_child_change == "disappears":
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    frozen = tuple(tuple(cohort.witnesses) for cohort in runtime.publication_result.snapshot.cohorts)
    original_close = module._read_closing_state
    calls = 0

    def closing() -> Any:
        nonlocal calls
        calls += 1
        runtime.publication_now += 10
        if destination:
            # Current utility skills may evolve; the frozen original must not.
            runtime.bars[3001] = (*runtime.bars[3001][:-1], 8000 + calls)
            runtime.bars[2001] = (*runtime.bars[2001][:-1], 8100 + calls)
        runtime.publication_result = _remote_publication(
            runtime,
            module,
            include_local=True,
            omit_outpost_children=not destination and outpost_child_change == "disappears",
        )
        assert frozen == tuple(tuple(cohort.witnesses) for cohort in runtime.publication_result.snapshot.cohorts)
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    assert calls == 4
    assert len(snapshot.members) == 8 and all(
        member.role is not module.CleansingRole.UNKNOWN for member in snapshot.members
    ), snapshot
    assert len(context._baselines) == 6
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.UNKNOWN] == 2


@pytest.mark.parametrize("publisher_replaced", (False, True))
def test_stage3_closing_destination_agent_reassociation_requires_same_publisher(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    publisher_replaced: bool,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    assert len(context.Refresh().members) == 8
    _witness_enter_destination(runtime, module, context)
    old_agent = runtime.agent_id
    runtime.agent_id = 5001
    runtime.local_agent_by_login[runtime.login_number] = runtime.agent_id
    runtime.professions[runtime.agent_id] = runtime.professions[old_agent]
    runtime.bars[runtime.agent_id] = runtime.bars[old_agent]
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    if publisher_replaced:
        runtime.publication_result.snapshot.cohorts[1].incarnation = bytes((90,)) + bytes(15)
    snapshot = context.Refresh()
    local = [member for member in snapshot.members if member.evidence_source is module.EvidenceSource.LOCAL_HERO]
    assert all((member.role is module.CleansingRole.UNKNOWN) == publisher_replaced for member in local), snapshot
    assert len(context._baselines) == (1 if publisher_replaced else 6)


def test_stage3_closing_normal_living_recognition_without_publication_authority(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    _add_hero(runtime, module, module.CleansingRole.ENERGY_SURGE, hero_id=7, agent_id=4000)
    context = module.CleansingContext()
    cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    calls = 0

    def unavailable() -> Any:
        nonlocal calls
        calls += 1
        return types.SimpleNamespace(status=types.SimpleNamespace(value="busy"), snapshot=None)

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", unavailable)
    snapshot = context.Refresh()
    assert calls == 1  # No publication authority, so no closing publication read is needed.
    assert all(member.role is not module.CleansingRole.UNKNOWN for member in snapshot.members), snapshot
    assert len(context._baselines) == 2


def test_stage3_closing_publication_failure_preserves_independent_living_local_roles(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    runtime.unavailable_agents.clear()
    original_close = module._read_closing_state

    def closing() -> Any:
        runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value="busy"), snapshot=None)
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    local = [
        member
        for member in snapshot.members
        if member.evidence_source
        in (
            module.EvidenceSource.LOCAL_PLAYER,
            module.EvidenceSource.LOCAL_HERO,
        )
    ]
    assert len(local) == 6 and all(member.role is not module.CleansingRole.UNKNOWN for member in local), snapshot
    assert len(context._baselines) == 6
    assert all(baseline.witness_origin is None for baseline in context._baselines.values())
    assert _remote_hero_record(snapshot, module).role is module.CleansingRole.UNKNOWN


def _outpost_witness_party(runtime: _Runtime, module: types.ModuleType, *, local_count: int = 5) -> Any:
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    roles = (
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        *(module.CleansingRole.ENERGY_SURGE,) * 3,
    )
    for index, role in enumerate(roles[:local_count]):
        _add_hero(runtime, module, role, hero_id=28 + index if local_count == 5 else 7, agent_id=4000 + index)
    _setup_remote_hero(runtime, module, owner_role=module.CleansingRole.BIP)
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    return module.CleansingContext()


@pytest.mark.parametrize("local_count", (1, 5))
def test_outpost_witness_local_and_remote_without_living_or_children(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    local_count: int,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module, local_count=local_count)
    snapshot = context.Refresh()
    local = [member for member in snapshot.members if member.evidence_source is module.EvidenceSource.LOCAL_HERO]
    assert len(local) == local_count and all(
        member.role is not module.CleansingRole.UNKNOWN for member in local
    ), snapshot
    assert len(context._baselines) == local_count + 1, context._baselines
    assert all(context._baselines[member.identity.stable_key].witness_origin is not None for member in local)
    assert _remote_hero_record(snapshot, module).role is module.CleansingRole.ENERGY_SURGE
    assert len(snapshot.members) == runtime.party_size
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    assert dict(snapshot.composition.role_counts)[module.CleansingRole.UNKNOWN] == 2


@pytest.mark.parametrize("owner_index", (0, 1), ids=("remote", "local"))
@pytest.mark.parametrize(
    "defect",
    (
        "missing",
        "duplicate",
        "wrong_kind",
        "wrong_primary",
        "wrong_secondary",
        "wrong_epoch",
        "zero_revision",
        "future",
        "empty_bar",
        "unsupported_bar",
        "stale",
        "wrong_owner",
        "publisher_conflict",
    ),
)
def test_outpost_witness_authority_failures_close_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    owner_index: int,
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    cohort = runtime.publication_result.snapshot.cohorts[owner_index]
    witness = cohort.witnesses[0]
    if defect == "missing":
        cohort.witnesses = cohort.witnesses[1:]
    elif defect == "duplicate":
        cohort.witnesses = (*cohort.witnesses, witness)
    elif defect == "wrong_kind":
        witness.kind = types.SimpleNamespace(value=9)
    elif defect == "wrong_primary":
        witness.primary = 0
    elif defect == "wrong_secondary":
        witness.secondary = 11
    elif defect == "wrong_epoch":
        witness.outpost_epoch = 2
    elif defect == "zero_revision":
        witness.revision = 0
    elif defect == "future":
        witness.observed_at_tick64 = runtime.publication_now + 1
    elif defect == "empty_bar":
        witness.skills = (0,) * 8
    elif defect == "unsupported_bar":
        witness.skills = tuple(range(9000, 9008))
    elif defect == "stale":
        cohort.published_tick = (runtime.publication_now - 10000) & 0xFFFFFFFF
        cohort.owner.GetAccountData().LastUpdated = cohort.published_tick
    elif defect == "wrong_owner":
        cohort.owner.GetAccountData().AgentData.LoginNumber = 99
    elif defect == "publisher_conflict":
        runtime.publication_result.snapshot.cohorts = (*runtime.publication_result.snapshot.cohorts, cohort)
    snapshot = context.Refresh()
    target = next(
        member for member in snapshot.members if member.identity.agent_id == (3001 if owner_index == 0 else 4000)
    )
    assert target.role is module.CleansingRole.UNKNOWN, (owner_index, defect, target)
    assert target.identity.stable_key not in context._baselines, (defect, context._baselines)


@pytest.mark.parametrize(
    "mutation", ("bar", "roster", "character", "uuid", "hwnd", "instance", "map", "world", "living", "lease")
)
def test_outpost_witness_actual_closing_rejects_changes(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    original_close = module._read_closing_state

    def closing() -> Any:
        if mutation == "bar":
            runtime.bars[4000] = tuple(range(9000, 9008))
        elif mutation == "roster":
            runtime.heroes[0].hero_id = 99
        elif mutation == "character":
            runtime.character_name = "Replacement"
        elif mutation == "uuid":
            runtime.local_uuid = (999, 0, 0, 0)
        elif mutation == "hwnd":
            runtime.local_hwnd += 1
        elif mutation == "instance":
            runtime.outpost = False
        elif mutation == "map":
            runtime.map_id += 1
        elif mutation == "world":
            runtime.missing_map_contexts.add("world")
        elif mutation == "living":
            runtime.unavailable_agents.discard(4000)
            runtime.professions[4000] = int(module.Profession.Mesmer)
        elif mutation == "lease":
            runtime.publication_now += 10000
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    local = [member for member in snapshot.members if member.evidence_source is module.EvidenceSource.LOCAL_HERO]
    assert all(member.role is module.CleansingRole.UNKNOWN for member in local), (mutation, snapshot)
    expected_baselines = 1 if mutation in {"living", "lease"} else 0
    assert len(context._baselines) == expected_baselines, (mutation, context._baselines)
    assert snapshot.ready == (mutation in {"living", "lease"}), (mutation, snapshot)


def _witness_enter_destination(
    runtime: _Runtime, module: types.ModuleType, context: Any, *, observed: bool = True
) -> None:
    if observed:
        runtime.ready = False
        runtime.instance_type_override = 2
        assert not context.Refresh().ready
    runtime.ready = True
    runtime.instance_type_override = None
    runtime.outpost = False
    runtime.explorable = True
    runtime.map_id = 2
    runtime.unavailable_agents.clear()
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)


@pytest.mark.parametrize(
    "defect",
    (
        "valid",
        "endpoint",
        "child",
        "stale_child",
        "profession",
        "copied_elite",
        "unobserved",
        "publisher",
        "witness_revision",
        "roster",
    ),
)
@pytest.mark.parametrize("owner_index", (0, 1), ids=("remote", "local"))
def test_outpost_witness_destination_requires_current_and_original_proof(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    owner_index: int,
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    assert all(member.role is not module.CleansingRole.UNKNOWN for member in context.Refresh().members)
    frozen = tuple(
        witness.skills for cohort in runtime.publication_result.snapshot.cohorts for witness in cohort.witnesses
    )
    _witness_enter_destination(runtime, module, context, observed=defect != "unobserved")
    cohort = runtime.publication_result.snapshot.cohorts[owner_index]
    agent_id = 3001 if owner_index == 0 else 4000
    child = cohort.children[0].GetAccountData()
    if defect == "endpoint":
        runtime.unavailable_agents.add(agent_id)
    elif defect == "child":
        cohort.children = cohort.children[1:]
    elif defect == "stale_child":
        child.LastUpdated = (runtime.publication_now - 10000) & 0xFFFFFFFF
    elif defect == "profession":
        runtime.professions[agent_id] = int(module.Profession.Monk)
    elif defect == "copied_elite":
        runtime.bars[agent_id] = _role_bar(runtime, module, module.CleansingRole.PANIC)
        for slot, skill in zip(child.AgentData.Skillbar.Skills, runtime.bars[agent_id]):
            slot.Id = skill
    elif defect == "publisher":
        cohort.incarnation = bytes([99]) + bytes(15)
    elif defect == "witness_revision":
        cohort.witnesses[0].revision += 1
    elif defect == "roster":
        runtime.heroes[0 if owner_index else -1].hero_id = 99
    assert frozen == tuple(
        witness.skills for c in runtime.publication_result.snapshot.cohorts for witness in c.witnesses
    )
    snapshot = context.Refresh()
    target = next(member for member in snapshot.members if member.identity.agent_id == agent_id)
    if defect == "valid":
        assert target.role is not module.CleansingRole.UNKNOWN, (owner_index, target)
        assert context.Refresh().members == snapshot.members
    else:
        assert target.role is module.CleansingRole.UNKNOWN, (owner_index, defect, target)
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK


@pytest.mark.parametrize("local_owner", (False, True))
@pytest.mark.parametrize("closing_mutation", ("unchanged", "retired", "recovery", "incarnation"))
def test_outpost_witness_decoded_v3_without_hero_endpoint(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    local_owner: bool,
    closing_mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    spec = importlib.util.spec_from_file_location(
        "publication_outpost_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    assert spec and spec.loader
    publication_tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publication_tests)
    subject = publication_tests.build_publication_subject(monkeypatch)
    envelope = publication_tests.envelope_v3(subject, instance=0)
    runtime.map_id = 10
    if local_owner:
        runtime.agent_id = 1000
        runtime.local_agent_by_login = {runtime.login_number: 1000}
        runtime.account_email = "owner"
        runtime.local_hwnd = 100
        runtime.local_uuid = (123, 0, 0, 0)
        _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    else:
        runtime.agent_id = 9000
        runtime.local_agent_by_login = {runtime.login_number: 9000}
        runtime.professions[9000] = int(module.Profession.Mesmer)
        _add_remote_player(
            runtime, module, login_number=1, agent_id=1000, role=module.CleansingRole.BIP, name="Decoded"
        )
    owner = envelope.accounts[0]
    owner.AgentData.LoginNumber = runtime.login_number if local_owner else 1
    owner.AgentData.CharacterName = runtime.character_name if local_owner else "Decoded"
    owner.AgentData.Profession[0] = runtime.professions[1000]
    _add_hero(
        runtime,
        module,
        module.CleansingRole.ENERGY_SURGE,
        hero_id=7,
        agent_id=1001,
        owner_id=runtime.login_number if local_owner else 1,
    )
    runtime.secondaries[1001] = 8
    runtime.unavailable_agents.add(1001)
    envelope.owners[0].witnesses[0].skills[:] = runtime.bars[1001]
    runtime.publication_result = publication_tests.decode_v3(subject, envelope)
    assert runtime.publication_result.status.value == "success"
    assert runtime.publication_result.snapshot.cohorts[0].children == ()
    original_close = module._read_closing_state
    closing_calls = 0

    def closing() -> Any:
        nonlocal closing_calls
        closing_calls += 1
        replacement: Any = type_cast(Any, type(envelope)).from_buffer_copy(bytes(envelope))
        if closing_mutation == "retired":
            replacement.owners[0].witness_count = 0
        elif closing_mutation == "recovery":
            replacement.header.recovery_epoch += 1
        elif closing_mutation == "incarnation":
            replacement.owners[0].incarnation[0] += 1
        runtime.publication_result = publication_tests.decode_v3(subject, replacement)
        assert runtime.publication_result.status.value == "success"
        return original_close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    context = module.CleansingContext()
    snapshot = context.Refresh()
    hero = next(member for member in snapshot.members if member.identity.kind is module.MemberKind.HERO)
    if closing_mutation == "unchanged":
        assert hero.role is module.CleansingRole.ENERGY_SURGE, (local_owner, hero)
        assert closing_calls == (4 if local_owner else 3)
    else:
        assert hero.role is module.CleansingRole.UNKNOWN, (local_owner, closing_mutation, hero)
        assert not any(key[0] is module.MemberKind.HERO for key in context._baselines)
        assert closing_calls == 3


def test_outpost_witness_probe_requires_three_distinct_destination_refreshes(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    _probe_enter_outpost(harness)
    assert len(context._baselines) == 6 and probe._attempt_id is not None
    _probe_enter_loading(harness)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    assert probe._destination_samples == 1 and not probe._finished
    _probe_poll_destination(harness)
    assert probe._destination_samples == 1 and not probe._finished
    _probe_sample_destination(harness)
    assert probe._destination_samples == 2 and not probe._finished
    _probe_sample_destination(harness)
    assert probe._destination_samples == 3 and probe._finished
    assert context.GetSnapshot().composition.status is module.CompositionStatus.FALLBACK


@pytest.mark.parametrize(
    "defect",
    ("position", "duplicate_hero", "duplicate_endpoint", "wrong_owner", "bar_mismatch", "local_publisher_uuid"),
)
def test_outpost_witness_local_roster_and_bar_guards(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    if defect == "position":
        runtime.hero_agent_by_position_override[1] = 999
    elif defect == "duplicate_hero":
        runtime.heroes[1].hero_id = runtime.heroes[0].hero_id
    elif defect == "duplicate_endpoint":
        runtime.heroes[1].agent_id = 4000
    elif defect == "wrong_owner":
        runtime.heroes[0].owner_player_id = 99
    elif defect == "bar_mismatch":
        runtime.bars[4000] = tuple(range(9000, 9008))
    elif defect == "local_publisher_uuid":
        runtime.publication_result.snapshot.cohorts[1].character_uuid = (999, 0, 0, 0)
    target = next(member for member in context.Refresh().members if member.identity.agent_id == 4000)
    assert target.role is module.CleansingRole.UNKNOWN, (defect, target)
    assert target.identity.stable_key not in context._baselines


@pytest.mark.parametrize("defect", ("profession", "secondary", "owner_login", "bar"))
def test_outpost_witness_remote_available_facts_cannot_contradict(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    runtime.unavailable_agents.remove(3001)
    if defect == "profession":
        runtime.professions[3001] = int(module.Profession.Monk)
    elif defect == "secondary":
        runtime.secondaries[3001] = 8
    elif defect == "owner_login":
        runtime.living_login_override[3001] = 22
    else:
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
        runtime.publication_result.snapshot.cohorts[0].witnesses[0].skills = tuple(range(9000, 9008))
    target = _remote_hero_record(context.Refresh(), module)
    assert target.role is module.CleansingRole.UNKNOWN, (defect, target)


@pytest.mark.parametrize("phase", ("opening", "closing"))
def test_outpost_witness_present_endpoint_identity_mismatch_fails_closed(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    agent_api = sys.modules["Py4GWCoreLib"].Agent
    original = agent_api.GetAgentByID

    def corrupt(agent_id: int) -> Any:
        if agent_id == 3001:
            return types.SimpleNamespace(agent_id=9999, is_living_type=False)
        return original(agent_id)

    if phase == "opening":
        monkeypatch.setattr(agent_api, "GetAgentByID", corrupt)
    else:
        close = module._read_closing_state

        def corrupt_at_close() -> Any:
            monkeypatch.setattr(agent_api, "GetAgentByID", corrupt)
            return close()

        monkeypatch.setattr(module, "_read_closing_state", corrupt_at_close)
    assert _remote_hero_record(context.Refresh(), module).role is module.CleansingRole.UNKNOWN


def test_outpost_witness_closing_bar_callback_cannot_change_roster(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    skillbar = sys.modules["PySkillbar"].Skillbar
    original = skillbar.GetHeroSkillbar
    calls = 0

    def read_bar(self: Any, position: int) -> Any:
        nonlocal calls
        calls += 1
        result = original(self, position)
        if calls == 6:
            runtime.heroes[0].hero_id = 99
        return result

    monkeypatch.setattr(skillbar, "GetHeroSkillbar", read_bar)
    snapshot = context.Refresh()
    assert all(
        member.role is module.CleansingRole.UNKNOWN
        for member in snapshot.members
        if member.evidence_source is module.EvidenceSource.LOCAL_HERO
    ), snapshot
    assert len(context._baselines) == 0


def test_outpost_witness_local_only_party_closes_before_committing(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module, local_count=1)
    runtime.players = runtime.players[:1]
    runtime.heroes = runtime.heroes[:1]
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    close = module._read_closing_state
    calls = 0

    def closing() -> Any:
        nonlocal calls
        calls += 1
        return close()

    monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = context.Refresh()
    assert snapshot.members[-1].role is not module.CleansingRole.UNKNOWN, snapshot
    assert calls >= 1 and len(context._baselines) == 2


def test_outpost_witness_fixture_preserves_published_original_not_destination(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    runtime, module = cleansing_runtime
    _setup_remote_hero(runtime, module)
    unsupported = tuple(range(9000, 9008))
    _remote_publication(runtime, module, witness_skillbars={(22, 7): unsupported})
    runtime.outpost = False
    runtime.explorable = True
    publication = _remote_publication(runtime, module)
    cohort = publication.snapshot.cohorts[0]
    assert cohort.witnesses[0].skills == unsupported
    assert tuple(skill.Id for skill in cohort.children[0].GetAccountData().AgentData.Skillbar.Skills) != unsupported
    runtime.original_hero_builds.clear()
    assert _remote_publication(runtime, module).snapshot.cohorts[0].witnesses == ()


def _endpoint_runtime(
    runtime: _Runtime, module: types.ModuleType, monkeypatch: pytest.MonkeyPatch, *, real_admission: bool = False
) -> Any:
    """Use the owning adapter methods, with explicit faults at the game-memory boundary."""
    _set_player_role(runtime, module, module.CleansingRole.HEROIC_REFRAIN)
    roles = (
        module.CleansingRole.SOUL_TWISTING,
        module.CleansingRole.INEPTITUDE,
        *(module.CleansingRole.ENERGY_SURGE,) * 3,
    )
    for slot, role in enumerate(roles):
        _add_hero(runtime, module, role, hero_id=28 + slot, agent_id=4000 + slot)
    _setup_remote_hero(runtime, module, owner_role=module.CleansingRole.BIP, hero_id=23)
    faults: dict[int, str] = {}
    calls: dict[str, int] = {}
    trace: list[str] = []

    def count(label: str, agent_id: int | None = None) -> None:
        calls[label] = calls.get(label, 0) + 1
        trace.append(label if agent_id is None else f"{label}:{agent_id}")

    def extract(path: str, owner: str, names: set[str]) -> list[ast.FunctionDef]:
        tree = ast.parse((_REPO_ROOT / path).read_text(encoding="utf-8-sig"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
        return [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]

    native_tree = ast.parse(
        (_REPO_ROOT / "Py4GWCoreLib/native_src/context/AgentContext.py").read_text(encoding="utf-8-sig")
    )
    scope = next(
        node for node in native_tree.body if isinstance(node, ast.FunctionDef) and node.name == "Stage3ObservationScope"
    )
    namespace: dict[str, Any] = {"__name__": "endpoint_adapter_fixture", "contextmanager": contextmanager}
    methods = extract("Py4GWCoreLib/Agent.py", "Agent", {"GetLivingAgentByID", "GetProfessions"})
    adapter_class = ast.ClassDef(name="Agent", bases=[], keywords=[], body=[*methods], decorator_list=[])
    tree = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            scope,
            adapter_class,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(tree), "endpoint_adapter_fixture", "exec"), namespace)
    adapter = namespace["Agent"]
    adapter._living_cache = {}

    def pointer(agent: Any) -> Any:
        return agent

    def pointer_type(target: Any) -> Any:
        return target

    def cast_pointer(agent: Any, _target: Any) -> Any:
        if faults.get(agent.agent_id) == "conversion_read":
            raise ValueError("PRIVATE conversion failure")
        return types.SimpleNamespace(contents=None if faults.get(agent.agent_id) == "conversion" else agent.living)

    native_namespace: dict[str, Any] = {
        "type_cast": type_cast,
        "Optional": Optional,
        "Stage3ObservationScope": namespace["Stage3ObservationScope"],
        "ctypes": types.SimpleNamespace(
            pointer=pointer,
            POINTER=pointer_type,
            cast=cast_pointer,
        ),
        "AgentLivingStruct": object,
    }
    conversion = extract("Py4GWCoreLib/native_src/context/AgentContext.py", "AgentStruct", {"GetAsAgentLiving"})
    conversion_tree = ast.Module(body=[tree.body[0], *conversion], type_ignores=[])
    exec(compile(ast.fix_missing_locations(conversion_tree), "endpoint_conversion_fixture", "exec"), native_namespace)

    class Living:
        def __init__(self, agent_id: int) -> None:
            self.agent_id = agent_id

        @property
        def login_number(self) -> int:
            count("login", self.agent_id)
            if faults.get(self.agent_id) == "login_read":
                raise ValueError("PRIVATE login failure")
            return next(
                (login for login, agent_id in runtime.local_agent_by_login.items() if agent_id == self.agent_id), 0
            )

        @property
        def primary(self) -> int:
            count("primary", self.agent_id)
            if faults.get(self.agent_id) == "read":
                raise ValueError("PRIVATE account and memory details must never be logged")
            return 0 if faults.get(self.agent_id) == "zero" else runtime.professions[self.agent_id]

        @property
        def secondary(self) -> int:
            count("secondary", self.agent_id)
            if faults.get(self.agent_id) == "secondary_read":
                raise ValueError("PRIVATE secondary failure")
            return runtime.secondaries.get(self.agent_id, 0)

    class CurrentAgent:
        def __init__(self, agent_id: int) -> None:
            self.agent_id = agent_id
            self.living = Living(agent_id)

        @property
        def is_living_type(self) -> bool:
            count("type", self.agent_id)
            if faults.get(self.agent_id) == "type_read":
                raise ValueError("PRIVATE type failure")
            return faults.get(self.agent_id) != "nonliving"

        def GetAsAgentLiving(self, **kwargs: Any) -> Any:
            count("conversion", self.agent_id)
            return native_namespace["GetAsAgentLiving"](self, **kwargs)

    def lookup(agent_id: int) -> Any:
        count("agent", agent_id)
        if faults.get(agent_id) == "lookup_read":
            raise ValueError("PRIVATE lookup failure")
        return None if faults.get(agent_id) == "absent" else CurrentAgent(agent_id)

    adapter.GetAgentByID = staticmethod(lookup)
    core = sys.modules["Py4GWCoreLib"]
    core.Agent.GetProfessions = adapter.GetProfessions
    core.Agent.GetAgentByID = lookup
    for api, names in (
        (
            core.GLOBAL_CACHE.Party,
            ("IsPartyLoaded", "GetPlayers", "GetHeroes", "GetHenchmen", "GetPartySize", "GetPartyID"),
        ),
        (core.GLOBAL_CACHE.Party.Players, ("GetAgentIDByLoginNumber", "GetPlayerNameByLoginNumber")),
        (core.GLOBAL_CACHE.Party.Heroes, ("GetHeroAgentIDByPartyPosition",)),
        (core.GLOBAL_CACHE.ShMem, ("GetNativeAccountSnapshotV3", "GetBaseTimestamp")),
        (core.GLOBAL_CACHE.Skill, ("GetID", "GetType")),
        (core.Agent, ("GetNameByID",)),
        (
            core.Map,
            (
                "IsMapReady",
                "IsInCinematic",
                "IsPVP",
                "IsOutpost",
                "IsExplorable",
                "GetMapID",
                "GetRegion",
                "GetDistrict",
                "GetLanguage",
                "IsMapDataLoaded",
                "GetInstanceType",
                "IsMapLoading",
            ),
        ),
        (
            core.Player,
            ("IsPlayerLoaded", "GetAgentID", "GetLoginNumber", "GetAccountEmail", "GetName", "GetPlayerUUID"),
        ),
        (sys.modules["PySkillbar"].Skillbar, ("GetContext", "GetHeroSkillbar")),
    ):
        for name in names:
            original = getattr(api, name)

            def tracked(*args: Any, _original: Any = original, _name: str = name, **kwargs: Any) -> Any:
                count(_name)
                return _original(*args, **kwargs)

            monkeypatch.setattr(api, name, tracked)
    clock = [10.0]
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    if not real_admission:
        # Branch/serialization checks admit immediately; admission tests use the production delay.
        monkeypatch.setattr(module, "_ENDPOINT_STABLE_SECONDS", 0.0, raising=False)
    return types.SimpleNamespace(adapter=adapter, faults=faults, calls=calls, clock=clock, trace=trace)


def _endpoint_lines() -> list[str]:
    return [
        message
        for _, message, _ in sys.modules["PySystem"].stage3_console_logs
        if message.startswith("STAGE3_ENDPOINT_DIAG_V1 ")
    ]


@pytest.mark.parametrize(
    ("fault", "flags", "primary", "gate", "role_known"),
    (
        ("absent", "0UU", "U", "AGENT", False),
        ("nonliving", "100", "U", "TYPE", False),
        ("conversion", "110", "U", "CONVERT", False),
        ("zero", "111", "0", "ZERO", False),
        ("valid", "111", "8", "OK", True),
        ("read", "111", "U", "READ", False),
    ),
)
def test_endpoint_diagnostic_local_actual_adapter_branches(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    flags: str,
    primary: str,
    gate: str,
    role_known: bool,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    harness.faults[4000] = fault
    context = module.CleansingContext()
    snapshot = context.Refresh()
    hero = next(member for member in snapshot.members if member.identity.agent_id == 4000)
    line = _endpoint_lines()[0]
    assert (hero.role is not module.CleansingRole.UNKNOWN) == role_known, (fault, hero)
    assert (hero.identity.stable_key in context._baselines) == role_known, (fault, context._baselines)
    reason = "ok" if role_known else "read" if fault == "read" else "profession"
    bar = "U" if fault == "read" else "1"
    assert f"H1={flags}/{primary}/{bar}/{reason}/{gate}" in line, (fault, line)
    assert len(line) + 1 <= 320 and "PRIVATE" not in line


@pytest.mark.parametrize(
    ("fault", "flags", "gate"),
    (("absent", "0UU", "AGENT"), ("nonliving", "10U", "TYPE"), ("conversion", "110", "CONVERT")),
)
def test_endpoint_diagnostic_remote_early_gates_do_not_infer_native_absence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    flags: str,
    gate: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    harness.faults[3001] = fault
    snapshot = module.CleansingContext().Refresh()
    hero = _remote_hero_record(snapshot, module, hero_id=23)
    assert hero.role is module.CleansingRole.ENERGY_SURGE, (fault, hero)
    assert f"R={flags}/U/{gate} N=c1,w1" in _endpoint_lines()[0]
    assert runtime.publication_result.snapshot.cohorts[
        0
    ].witnesses, "Native facts existed despite the early Python return"


@pytest.mark.parametrize("omit_child", (False, True))
def test_endpoint_diagnostic_native_counts_only_after_existing_evaluation(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    omit_child: bool,
) -> None:
    runtime, module = cleansing_runtime
    _endpoint_runtime(runtime, module, monkeypatch)
    if omit_child:
        runtime.publication_result.snapshot.cohorts[0].children = ()
    module.CleansingContext().Refresh()
    line = _endpoint_lines()[0]
    assert "R=111/1/OK" in line
    assert ("N=c0,w1" if omit_child else "N=c1,w1") in line


@pytest.mark.parametrize(
    ("fault", "flags"),
    (
        ("lookup_read", "UUU"),
        ("type_read", "1UU"),
        ("conversion_read", "11U"),
        ("login_read", "111"),
        ("read", "111"),
        ("secondary_read", "111"),
    ),
)
def test_endpoint_diagnostic_remote_read_errors_remain_unknown_and_preserve_refresh(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    flags: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    harness.faults[3001] = fault
    context = module.CleansingContext()
    snapshot = context.Refresh()
    assert snapshot.ready and len(context._baselines) == 6
    assert f"R={flags}/U/READ N=cNOT_EVALUATED,wNOT_EVALUATED" in _endpoint_lines()[0]
    assert "PRIVATE" not in _endpoint_lines()[0]


def test_endpoint_diagnostic_nonpositive_endpoint_does_not_read_agent(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
) -> None:
    _runtime, module = cleansing_runtime
    observation: dict[str, Any] = {}

    def forbidden(_agent_id: int) -> Any:
        pytest.fail("nonpositive endpoints must not perform a lookup")

    assert module._read_living_identity(types.SimpleNamespace(GetAgentByID=forbidden), 0, observation) is None
    assert observation == {
        "agent_found": None,
        "living_type": None,
        "conversion": None,
        "primary": None,
        "professions": None,
        "cached": None,
        "gate": "ID",
    }


def test_endpoint_diagnostic_changes_are_throttled_and_skipped_fields_are_unknown(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    context = module.CleansingContext()
    context.Refresh()
    harness.faults[4000] = "absent"
    harness.adapter._living_cache.clear()
    harness.clock[0] += 0.1
    context.Refresh()
    assert len(_endpoint_lines()) == 1
    harness.clock[0] += 1.0
    context.Refresh()
    assert len(_endpoint_lines()) == 2
    assert "H1=0UU/U/1/other/AGENT" in _endpoint_lines()[-1]


def test_endpoint_diagnostic_five_mercenary_slots_and_recognition_read_count_parity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    harness.faults.update({4000: "absent", 4001: "nonliving", 4002: "conversion", 4003: "zero", 3001: "absent"})
    context = module.CleansingContext()
    observed = context.Refresh()
    baselines = dict(context._baselines)
    observed_calls = dict(harness.calls)
    positions = (list(runtime.hero_agent_positions), list(runtime.hero_skillbar_positions))
    line = _endpoint_lines()[0]
    assert "H1=0UU/U/1/profession/AGENT" in line
    assert "H2=100/U/1/profession/TYPE" in line
    assert "H3=110/U/1/profession/CONVERT" in line
    assert "H4=111/0/1/profession/ZERO" in line
    assert "H5=111/5/1/ok/OK" in line
    harness.adapter._living_cache.clear()
    harness.calls.clear()
    runtime.hero_agent_positions.clear()
    runtime.hero_skillbar_positions.clear()
    monkeypatch.setattr(module, "_endpoint_diagnostic_records", 3)
    ordinary_context = module.CleansingContext()
    ordinary = ordinary_context.Refresh()
    assert observed == ordinary, (observed, ordinary)
    assert baselines == ordinary_context._baselines
    assert observed_calls == harness.calls, (observed_calls, harness.calls)
    assert positions == (runtime.hero_agent_positions, runtime.hero_skillbar_positions)
    assert harness.calls["GetNativeAccountSnapshotV3"] == 3  # Opening and both production closing passes.


def test_endpoint_diagnostic_waits_for_full_roster_then_caps_changes_across_contexts(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    complete = list(runtime.heroes)
    runtime.heroes = complete[:-1]
    module.CleansingContext().Refresh()
    assert not _endpoint_lines() and module._endpoint_diagnostic_records == 0
    runtime.heroes = complete
    context = module.CleansingContext()
    for fault in ("absent", "absent", "nonliving", "conversion", "zero", "valid"):
        harness.faults[4000] = fault
        harness.adapter._living_cache.clear()
        harness.clock[0] += 1.1
        context.Refresh()
    assert len(_endpoint_lines()) == module._endpoint_diagnostic_records == 3
    context.Invalidate()
    module.CleansingContext().Refresh()
    assert len(_endpoint_lines()) == 3, "the limit belongs to the client, not a context or map"


def test_endpoint_diagnostic_console_failures_are_isolated_and_not_retried_each_frame(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    attempted: list[str] = []

    def fail_console(_sender: str, message: str, _kind: object) -> None:
        if message.startswith("STAGE3_ENDPOINT_DIAG_V1 "):
            attempted.append(message)
        raise RuntimeError("PRIVATE")

    monkeypatch.setattr(sys.modules["PySystem"].Console, "Log", fail_console)
    context = module.CleansingContext()
    for _ in range(10):
        harness.adapter._living_cache.clear()
        harness.clock[0] += 2
        snapshot = context.Refresh()
        assert snapshot.ready and len(context._baselines) == 6
    assert len(attempted) == module._endpoint_diagnostic_records == 1


def test_endpoint_diagnostic_unknown_cache_fields_privacy_and_worst_case_bound(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    harness.adapter.GetProfessions(4000)
    observation: dict[str, Any] = {}
    assert harness.adapter.GetProfessions(4000, _stage3_observation=observation) == (8, 0)
    assert module._endpoint_flags(observation) == "UUU", "cache hits do not perform an agent/type/conversion read"
    snapshot = module.CleansingContext().Refresh()
    assert "H1=UUU/8/1/ok/CACHE" in _endpoint_lines()[0]
    monkeypatch.setattr(module, "_endpoint_diagnostic_last_emit", None)
    dirty = {
        "agent_found": "SECRET",
        "living_type": 99999,
        "conversion": False,
        "primary": 99999,
        "bar": "SECRET",
        "gate": "SECRET",
    }
    member = replace(snapshot.members[0], role=module.CleansingRole.UNKNOWN, reason="SECRET email/account/raw endpoint")
    module._emit_endpoint_diagnostic([(dirty, member)] * 5, {"gate": "SECRET", "children": 999999})
    line = _endpoint_lines()[-1]
    assert len(line) + 1 <= 320 and "SECRET" not in line and "99999" not in line
    assert "N=c9,wNOT_EVALUATED" in line
    for secret in (runtime.account_email, runtime.character_name, "4000", "3001", "HWND", "UUID"):
        assert secret not in line, (secret, line)


def test_endpoint_diagnostic_reproduction_hostile_cached_observer(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)

    class RaisingUpdate(dict[str, Any]):
        def update(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("observer rejected update")

    assert harness.adapter.GetProfessions(4000) == (8, 0)
    before = dict(harness.calls)
    assert harness.adapter.GetProfessions(4000, _stage3_observation=RaisingUpdate()) == (8, 0)
    assert harness.calls == {**before, "primary": before["primary"] + 1, "secondary": before["secondary"] + 1}


def test_endpoint_diagnostic_reproduction_reused_observer(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    observation: dict[str, Any] = {"stale": "another invocation"}
    assert harness.adapter.GetProfessions(4000, _stage3_observation=observation) == (8, 0)
    assert module._endpoint_flags(observation) == "111"
    harness.adapter.GetProfessions(4001)
    assert harness.adapter.GetProfessions(4001, _stage3_observation=observation) == (5, 0)
    assert module._endpoint_flags(observation) == "UUU", observation
    assert observation["cached"] is True and "stale" not in observation
    harness.faults[4999] = "absent"
    assert harness.adapter.GetProfessions(4999, _stage3_observation=observation) == (0, 0)
    assert observation == {
        "agent_found": False,
        "living_type": None,
        "conversion": None,
        "primary": None,
        "professions": False,
        "cached": None,
        "gate": "AGENT",
    }


def test_endpoint_diagnostic_reproduction_zero_startup_endpoints(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    for hero in runtime.heroes[:3]:
        hero.agent_id = 0
    context = module.CleansingContext()
    for _ in range(3):
        context.Refresh()
        harness.clock[0] += 1.1
    assert not _endpoint_lines(), _endpoint_lines()
    assert module._endpoint_diagnostic_records == 0
    for slot, hero in enumerate(runtime.heroes[:3]):
        hero.agent_id = 4000 + slot
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert not _endpoint_lines()
    harness.clock[0] += 2.0
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert len(_endpoint_lines()) == 1
    assert "H1=111/8/1/ok/OK H2=111/5/1/ok/OK H3=111/5/1/ok/OK" in _endpoint_lines()[0]


def test_endpoint_diagnostic_reproduction_owner_gate_reserves_endpoint_capacity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    cohorts = runtime.publication_result.snapshot.cohorts
    runtime.publication_result.snapshot.cohorts = ()
    context = module.CleansingContext()
    for fault in ("absent", "nonliving", "conversion"):
        harness.faults[4000] = fault
        harness.adapter._living_cache.clear()
        context.Refresh()
        harness.clock[0] += 2.1
        harness.adapter._living_cache.clear()
        context.Refresh()
        harness.clock[0] += 1.1
    assert module._endpoint_diagnostic_records <= 1, _endpoint_lines()
    assert "R=UUU/U/OWNER" in _endpoint_lines()[0]
    runtime.publication_result.snapshot.cohorts = cohorts
    harness.faults[3001] = "absent"
    harness.adapter._living_cache.clear()
    context.Refresh()
    harness.clock[0] += 2.1
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert "R=0UU/U/AGENT" in _endpoint_lines()[-1], _endpoint_lines()
    assert "H1=110/U/1/profession/CONVERT" in _endpoint_lines()[-1]


@pytest.mark.parametrize("mutation", ("clear", "update", "setitem"))
def test_endpoint_diagnostic_hostile_native_observer_preserves_results_and_exception(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)

    class Hostile(dict[str, Any]):
        def clear(self) -> None:
            if mutation == "clear":
                raise RuntimeError("observer clear")
            super().clear()

        def update(self, *args: Any, **kwargs: Any) -> None:
            if mutation == "update":
                raise RuntimeError("observer update")
            super().update(*args, **kwargs)

        def __setitem__(self, key: str, value: Any) -> None:
            raise RuntimeError("observer assignment")

    agent = harness.adapter.GetAgentByID(4000)
    assert agent.GetAsAgentLiving(_stage3_observation=Hostile()) is agent.living
    expected = agent.GetAsAgentLiving()
    assert expected is agent.living
    harness.faults[4000] = "nonliving"
    assert agent.GetAsAgentLiving(_stage3_observation=Hostile()) is None
    harness.faults[4000] = "type_read"
    with pytest.raises(ValueError, match="PRIVATE type failure"):
        agent.GetAsAgentLiving(_stage3_observation=Hostile())
    harness.faults[4000] = "conversion_read"
    with pytest.raises(ValueError, match="PRIVATE conversion failure"):
        agent.GetAsAgentLiving(_stage3_observation=Hostile())

    original_error = ValueError("original production exception")

    def fail_lookup(_agent_id: int) -> Any:
        raise original_error

    monkeypatch.setattr(harness.adapter, "GetAgentByID", fail_lookup)
    with pytest.raises(ValueError) as observed:
        harness.adapter.GetProfessions(4999, _stage3_observation=Hostile())
    assert observed.value is original_error
    assert 4999 not in harness.adapter._living_cache


def test_endpoint_diagnostic_reuse_conversion_and_exception_schema(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    observation: dict[str, Any] = {}
    for fault, flags, gate in (("valid", "111", "OK"), ("nonliving", "100", "TYPE"), ("conversion", "110", "CONVERT")):
        harness.faults[4000] = fault
        harness.adapter._living_cache.clear()
        harness.adapter.GetProfessions(4000, _stage3_observation=observation)
        assert module._endpoint_flags(observation) == flags, (fault, observation)
        assert observation["gate"] == gate and observation["cached"] is None
        assert set(observation) == {
            "agent_found",
            "living_type",
            "conversion",
            "primary",
            "professions",
            "cached",
            "gate",
        }
    harness.faults[4000] = "secondary_read"
    with pytest.raises(ValueError):
        harness.adapter.GetProfessions(4000, _stage3_observation=observation)
    assert observation == {
        "agent_found": True,
        "living_type": True,
        "conversion": True,
        "primary": 8,
        "professions": None,
        "cached": None,
        "gate": "READ",
    }
    # Standalone conversion reports only its own type/conversion reads.
    agent = harness.adapter.GetAgentByID(4000)
    harness.faults[4000] = "valid"
    assert agent.GetAsAgentLiving(_stage3_observation=observation) is agent.living
    assert module._endpoint_flags(observation) == "U11"
    assert observation["primary"] is observation["cached"] is observation["professions"] is None
    harness.faults[4000] = "nonliving"
    assert agent.GetAsAgentLiving(_stage3_observation=observation) is None
    assert module._endpoint_flags(observation) == "U0U"
    harness.faults[4000] = "conversion"
    assert agent.GetAsAgentLiving(_stage3_observation=observation) is None
    assert module._endpoint_flags(observation) == "U10"


@pytest.mark.parametrize("local_fault", ("absent", "zero"))
def test_endpoint_diagnostic_persistent_blocked_state_emits_without_transition(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, local_fault: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    harness.faults.update({agent_id: local_fault for agent_id in range(4000, 4005)})
    harness.faults[3001] = "absent"
    context = module.CleansingContext()
    for tick in (10.0, 10.15, 11.95):
        harness.clock[0] = tick
        harness.adapter._living_cache.clear()
        context.Refresh()
        assert not _endpoint_lines()
    harness.clock[0] = 12.0
    harness.adapter._living_cache.clear()
    snapshot = context.Refresh()
    assert len(_endpoint_lines()) == 1
    expected = "0UU/U/1/profession/AGENT" if local_fault == "absent" else "111/0/1/profession/ZERO"
    assert all(f"H{slot}={expected}" in _endpoint_lines()[0] for slot in range(1, 6))
    assert "R=0UU/U/AGENT N=c1,w1" in _endpoint_lines()[0]
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    for _ in range(5):
        harness.clock[0] += 3
        harness.adapter._living_cache.clear()
        context.Refresh()
    assert len(_endpoint_lines()) == 1


def test_endpoint_diagnostic_deadline_reports_latest_zero_or_changing_roster(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    runtime.heroes[0].agent_id = 0
    context = module.CleansingContext()
    for tick, fault in ((10.0, "absent"), (13.0, "nonliving"), (16.0, "zero"), (19.9, "conversion")):
        harness.clock[0] = tick
        harness.faults[4001] = fault
        harness.adapter._living_cache.clear()
        context.Refresh()
        assert not _endpoint_lines()
    harness.clock[0] = 20.0
    harness.faults[4001] = "absent"
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert len(_endpoint_lines()) == 1
    assert "H1=UUU/U/U/identity/ROSTER H2=0UU/U/1/profession/AGENT" in _endpoint_lines()[0]


def test_endpoint_diagnostic_transitions_replace_pending_and_zoning_clears_only_pending(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    context = module.CleansingContext()
    for tick, fault in ((10.0, "absent"), (10.75, "nonliving"), (11.5, "conversion"), (13.49, "conversion")):
        harness.clock[0] = tick
        harness.faults[4000] = fault
        harness.adapter._living_cache.clear()
        context.Refresh()
        assert not _endpoint_lines()
    harness.clock[0] = 13.5
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert len(_endpoint_lines()) == 1 and "H1=110/U/1/profession/CONVERT" in _endpoint_lines()[0]
    harness.faults[4000] = "absent"
    harness.clock[0] += 1
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert module._endpoint_diagnostic_pending is not None
    runtime.ready = False
    context.Refresh()
    assert module._endpoint_diagnostic_pending is None and module._endpoint_diagnostic_records == 1
    runtime.ready = True
    harness.clock[0] += 20
    context = module.CleansingContext()
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert len(_endpoint_lines()) == 1, "a new ready interval must stabilize"
    harness.clock[0] += 2
    harness.adapter._living_cache.clear()
    context.Refresh()
    assert len(_endpoint_lines()) == 2 and "H1=0UU/U/1/profession/AGENT" in _endpoint_lines()[-1]


@pytest.mark.parametrize(
    "fault",
    (
        "valid",
        "local_absent",
        "local_nonliving",
        "local_conversion",
        "local_zero",
        "local_read",
        "local_lookup_read",
        "local_type_read",
        "local_conversion_read",
        "local_secondary_read",
        "remote_absent",
        "remote_nonliving",
        "remote_conversion",
        "remote_zero",
        "remote_read",
        "remote_lookup_read",
        "remote_type_read",
        "remote_conversion_read",
        "remote_login_read",
        "remote_secondary_read",
        "child_missing",
        "witness_missing",
    ),
)
def test_endpoint_diagnostic_22_production_parity_cases(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    if fault.startswith("local_"):
        harness.faults[4000] = fault.removeprefix("local_")
    elif fault.startswith("remote_"):
        harness.faults[3001] = fault.removeprefix("remote_")
    elif fault == "child_missing":
        runtime.publication_result.snapshot.cohorts[0].children = ()
    elif fault == "witness_missing":
        runtime.publication_result.snapshot.cohorts[0].witnesses = ()
    context = module.CleansingContext()
    observed = context.Refresh()
    baselines = (dict(context._baselines), dict(context._remote_player_baselines))
    observed_calls, observed_trace = dict(harness.calls), list(harness.trace)
    positions = (list(runtime.hero_agent_positions), list(runtime.hero_skillbar_positions))
    assert len(_endpoint_lines()) == 1, (fault, _endpoint_lines())
    if fault == "witness_missing":
        assert "N=c1,w0" in _endpoint_lines()[0]
        assert _remote_hero_record(observed, module, hero_id=23).role is module.CleansingRole.UNKNOWN
    harness.adapter._living_cache.clear()
    harness.calls.clear()
    harness.trace.clear()
    runtime.hero_agent_positions.clear()
    runtime.hero_skillbar_positions.clear()
    monkeypatch.setattr(module, "_endpoint_diagnostic_records", 3)
    ordinary_context = module.CleansingContext()
    ordinary = ordinary_context.Refresh()
    assert observed == ordinary, (fault, observed, ordinary)
    assert baselines == (ordinary_context._baselines, ordinary_context._remote_player_baselines), fault
    assert observed_calls == harness.calls, (fault, observed_calls, harness.calls)
    assert observed_trace == harness.trace, (fault, observed_trace, harness.trace)
    assert positions == (runtime.hero_agent_positions, runtime.hero_skillbar_positions), fault
    failed_before_closing = fault in {
        "remote_read",
        "remote_lookup_read",
        "remote_type_read",
        "remote_conversion_read",
        "remote_login_read",
        "remote_secondary_read",
    }
    expected_reads = 1 if failed_before_closing else 3 if fault == "local_absent" else 2
    assert harness.calls["GetNativeAccountSnapshotV3"] == expected_reads
    assert observed.composition.status is module.CompositionStatus.FALLBACK


@pytest.mark.parametrize("console_failure", (False, True))
def test_endpoint_diagnostic_real_admission_lifetime_caps_and_probe_toggles(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, console_failure: bool
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    core = sys.modules["Py4GWCoreLib"]
    _load_global_cache_owner(monkeypatch)
    context = module.CleansingContext()
    core.GLOBAL_CACHE.CleansingContext = context
    probe = _load_stage3_evidence_probe(monkeypatch, core.GLOBAL_CACHE)
    attempted: list[str] = []
    console = sys.modules["PySystem"].Console
    original = console.Log

    def log(sender: str, line: str, kind: Any) -> None:
        if line.startswith("STAGE3_ENDPOINT_DIAG_V1 "):
            attempted.append(line)
            if console_failure:
                raise RuntimeError("PRIVATE console failure")
        original(sender, line, kind)

    monkeypatch.setattr(console, "Log", log)
    for index, fault in enumerate(("absent", "nonliving", "conversion", "zero")):
        probe.on_enable()
        assert module._endpoint_diagnostic_records == min(index, 3)
        harness.faults[4000] = fault
        for elapsed in (0.0, 2.0):
            harness.clock[0] = 30.0 + index * 4.0 + elapsed
            harness.adapter._living_cache.clear()
            snapshot = context.Refresh()
            assert snapshot.ready and len(context._baselines) == 5
        assert module._endpoint_diagnostic_records == len(attempted) == min(index + 1, 3)
        probe.on_disable()
        runtime.ready = False
        context.Refresh()
        runtime.ready = True
        context = module.CleansingContext()
        core.GLOBAL_CACHE.CleansingContext = context
    assert len(attempted) == len(set(attempted)) == 3
    local_rows: list[str] = []
    for line in attempted:
        match = re.search(r"H1=(\S+)", line)
        assert match is not None, line
        local_rows.append(match.group(1))
    assert local_rows == [
        "0UU/U/1/profession/AGENT",
        "100/U/1/profession/TYPE",
        "110/U/1/profession/CONVERT",
    ]
    assert all(len(line) + 1 <= 320 for line in attempted)
    assert len(_endpoint_lines()) == (0 if console_failure else 3)
    for line in attempted:
        for secret in (runtime.account_email, runtime.character_name, "4000", "3001", "PRIVATE", "UUID", "HWND"):
            assert secret not in line


def test_endpoint_diagnostic_interval_and_session_duplicate_suppression(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    context = module.CleansingContext()
    for tick, fault, expected in (
        (10.0, "absent", 1),
        (10.999, "nonliving", 1),
        (11.0, "nonliving", 2),
        (13.0, "absent", 2),
        (15.0, "conversion", 3),
        (17.0, "zero", 3),
    ):
        harness.clock[0] = tick
        harness.faults[4000] = fault
        harness.adapter._living_cache.clear()
        context.Refresh()
        assert len(_endpoint_lines()) == expected, (tick, _endpoint_lines())
    assert len(set(_endpoint_lines())) == 3


def test_endpoint_diagnostic_remote_identity_reader_safe_fresh_publication(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch)
    observation: dict[str, Any] = {"children": 9, "witnesses": 9, "cached": True}
    assert module._read_living_identity(harness.adapter, 4000, observation) == (0, 8, 0)
    assert module._endpoint_flags(observation) == "111"
    harness.faults[4000] = "absent"
    assert module._read_living_identity(harness.adapter, 4000, observation) is None
    assert observation == {
        "agent_found": False,
        "living_type": None,
        "conversion": None,
        "primary": None,
        "professions": None,
        "cached": None,
        "gate": "AGENT",
    }

    class Hostile(dict[str, Any]):
        def clear(self) -> None:
            raise RuntimeError("publication rejected")

    assert module._read_living_identity(harness.adapter, 4000, Hostile()) is None
    harness.faults[4000] = "read"
    with pytest.raises(ValueError, match="PRIVATE account"):
        module._read_living_identity(harness.adapter, 4000, Hostile())


@pytest.mark.parametrize(("gate", "wait"), (("OWNER", 2.0), ("ROSTER", 10.0)))
def test_endpoint_diagnostic_permanent_early_remote_gate_has_bounded_truthful_record(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, gate: str, wait: float
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    if gate == "OWNER":
        runtime.publication_result.snapshot.cohorts = ()
    else:
        runtime.heroes[-1].agent_id = 0
    context = module.CleansingContext()
    for elapsed in (0.0, wait - 0.01, wait, wait + 20.0):
        harness.clock[0] = 10.0 + elapsed
        harness.adapter._living_cache.clear()
        context.Refresh()
        assert len(_endpoint_lines()) == int(elapsed >= wait), (elapsed, _endpoint_lines())
    line = _endpoint_lines()[0]
    assert f"R=UUU/U/{gate} N=cNOT_EVALUATED,wNOT_EVALUATED" in line
    assert "H1=111/8/1/ok/OK" in line and "H5=111/5/1/ok/OK" in line


def _local_witness_diagnostic_fixture(
    runtime: _Runtime, module: types.ModuleType, monkeypatch: pytest.MonkeyPatch
) -> Any:
    context = _outpost_witness_party(runtime, module)
    clock = [10.0]
    observations: list[Any] = []
    emit = module._emit_local_witness_diagnostic

    def observe(observation: Any, **kwargs: Any) -> None:
        observations.append(observation)
        emit(observation, **kwargs)

    monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", True)
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "_emit_local_witness_diagnostic", observe)
    return types.SimpleNamespace(context=context, clock=clock, observations=observations)


def _local_witness_lines() -> list[str]:
    return [
        line
        for _, line, _ in sys.modules["PySystem"].stage3_console_logs
        if line.startswith("STAGE3_LOCAL_WITNESS_DIAG_V1 ")
    ]


def test_local_witness_diagnostic_observes_changed_second_agent_lookup(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    lookup = sys.modules["Py4GWCoreLib"].Agent.GetAgentByID
    reads = 0
    observations: list[Any] = []

    def changing(agent: int) -> Any:
        nonlocal reads
        if agent == 4000:
            reads += 1
            harness.faults[agent] = "absent" if reads == 1 else "valid"
        return lookup(agent)

    def observe(observation: Any, **_kwargs: Any) -> None:
        observations.append(observation)

    monkeypatch.setattr(sys.modules["Py4GWCoreLib"].Agent, "GetAgentByID", changing)
    monkeypatch.setattr(harness.adapter, "GetAgentByID", changing)
    monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", True)
    monkeypatch.setattr(module, "_emit_local_witness_diagnostic", observe)
    snapshot = module.CleansingContext().Refresh()
    row = observations[-1].heroes[1]
    assert row["entry"] == "AGENT_PRESENT" and "opening" not in row, row
    assert reads == 2 and snapshot.members[2].role is module.CleansingRole.UNKNOWN


@pytest.mark.parametrize(
    "entry",
    (
        "ENTER",
        "AGENT_PRESENT",
        "PROF_PRESENT",
        "IDENTITY_FAIL",
        "POSITION_FAIL",
        "READ_FAIL",
    ),
)
def test_local_witness_diagnostic_actual_entry_gates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    core = sys.modules["Py4GWCoreLib"]
    if entry == "AGENT_PRESENT":
        lookup = core.Agent.GetAgentByID

        def present(agent: int) -> Any:
            return object() if agent == 4000 else lookup(agent)

        monkeypatch.setattr(core.Agent, "GetAgentByID", present)
    elif entry == "PROF_PRESENT":
        runtime.unavailable_agents.remove(4000)
    elif entry == "IDENTITY_FAIL":
        runtime.heroes[0].hero_id = 0
    elif entry == "POSITION_FAIL":
        runtime.hero_agent_by_position_override[1] = 999
    elif entry == "READ_FAIL":
        professions = core.Agent.GetProfessions

        def fail(agent: int, **kwargs: Any) -> Any:
            if agent == 4000:
                raise RuntimeError("PRIVATE read failure")
            return professions(agent, **kwargs)

        monkeypatch.setattr(core.Agent, "GetProfessions", fail)
    snapshot = harness.context.Refresh()
    row = harness.observations[-1].heroes[1]
    assert row["entry"] == entry, (entry, row, snapshot)
    if entry == "ENTER":
        assert row["opening"] == row["committed"] == 1, row
        assert row["gate"] == "ACCEPTED"
    else:
        assert "opening" not in row and "matches" not in row, row


@pytest.mark.parametrize("status", ("unavailable", "busy", "recovery", "sync_failure", "raise"))
def test_local_witness_diagnostic_opening_native_failures(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)

    def read() -> Any:
        if status == "raise":
            raise RuntimeError("PRIVATE native failure")
        return types.SimpleNamespace(status=types.SimpleNamespace(value=status), snapshot=None)

    monkeypatch.setattr(
        sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem,
        "GetNativeAccountSnapshotV3",
        read,
    )
    snapshot = harness.context.Refresh()
    observation = harness.observations[-1]
    assert observation.values["native"] == ("READ_FAILED" if status == "raise" else status.upper())
    assert "owner" not in observation.values and "matches" not in observation.heroes[1], observation
    assert observation.heroes[1]["opening"] == observation.heroes[1]["committed"] == 0
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK


@pytest.mark.parametrize(
    ("defect", "gate"),
    (
        ("missing_owner", "COHORT_MISSING"),
        ("wrong_context", "COHORT_MISSING"),
        ("duplicate_owner", "COHORT_AMBIGUOUS"),
        ("stale", "LEASE"),
        ("uuid", "COHORT_UUID"),
        ("login", "OWNER_LOGIN"),
        ("hwnd", "OWNER_HWND"),
        ("profession", "OWNER_PROFESSION"),
        ("conflict", "PUBLISHER_CONFLICT"),
    ),
)
def test_local_witness_diagnostic_first_local_owner_failure(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
    gate: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    publication = runtime.publication_result.snapshot
    cohort = publication.cohorts[1]
    owner = cohort.owner.GetAccountData()
    if defect == "missing_owner":
        publication.cohorts = publication.cohorts[:1]
    elif defect == "wrong_context":
        owner.AgentPartyData.PartyID += 1
    elif defect == "duplicate_owner":
        publication.cohorts = (*publication.cohorts, cohort)
    elif defect == "stale":
        cohort.published_tick = (runtime.publication_now - 10000) & 0xFFFFFFFF
        owner.LastUpdated = cohort.published_tick
    elif defect == "uuid":
        cohort.character_uuid = (999, 0, 0, 0)
    elif defect == "login":
        owner.AgentData.LoginNumber = 99
    elif defect == "hwnd":
        owner.Key.HWND += 1
    elif defect == "profession":
        owner.AgentData.Profession = (0, 0)
    elif defect == "conflict":
        publication.cohorts[0].character_uuid = runtime.local_uuid
    snapshot = harness.context.Refresh()
    observation = harness.observations[-1]
    assert observation.values["owner"] == gate, (defect, observation, snapshot)
    assert all(row["opening"] == row["committed"] == 0 for row in observation.heroes.values())
    assert all("qualified" not in row for row in observation.heroes.values())


@pytest.mark.parametrize(
    ("defect", "gate"),
    (
        ("missing", "WITNESS_MISSING"),
        ("wrong_id", "WITNESS_MISSING"),
        ("duplicate", "WITNESS_DUPLICATE"),
        ("kind", "WITNESS_KIND"),
        ("primary", "WITNESS_PROFESSION"),
        ("secondary", "WITNESS_PROFESSION"),
        ("bar", "WITNESS_BAR"),
        ("revision", "WITNESS_REVISION"),
        ("epoch", "WITNESS_EPOCH"),
        ("future", "WITNESS_TIME"),
        ("unsupported", "ORIGINAL_UNSUPPORTED"),
        ("current_bar", "BAR_MISMATCH"),
        ("endpoint", "ENDPOINT_CONTRADICTION"),
        ("child", "CHILD_CONTRADICTION"),
        ("child_semantics", "CHILD_SEMANTICS"),
        ("child_duplicate", "CHILD_CLAIM"),
    ),
)
def test_local_witness_diagnostic_first_hero_rejection(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
    gate: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    cohort = runtime.publication_result.snapshot.cohorts[1]
    witness = cohort.witnesses[0]
    if defect == "missing":
        cohort.witnesses = cohort.witnesses[1:]
    elif defect == "wrong_id":
        witness.hero_id = 99
    elif defect == "duplicate":
        cohort.witnesses = (*cohort.witnesses, witness)
    elif defect == "kind":
        witness.kind = types.SimpleNamespace(value=9)
    elif defect == "primary":
        witness.primary = 0
    elif defect == "secondary":
        witness.secondary = 11
    elif defect == "bar":
        witness.skills = (0,) * 8
    elif defect == "revision":
        witness.revision = 0
    elif defect == "epoch":
        witness.outpost_epoch = 2
    elif defect == "future":
        witness.observed_at_tick64 = runtime.publication_now + 1
    elif defect == "unsupported":
        witness.skills = tuple(range(9000, 9008))
    elif defect == "current_bar":
        runtime.bars[4000] = tuple(range(9000, 9008))
    elif defect == "endpoint":
        lookup = sys.modules["Py4GWCoreLib"].Agent.GetAgentByID
        reads = 0

        def contradictory(agent: int) -> Any:
            nonlocal reads
            if agent == 4000:
                reads += 1
                if reads > 1:
                    return types.SimpleNamespace(
                        agent_id=4000,
                        is_living_type=True,
                        GetAsAgentLiving=lambda: types.SimpleNamespace(login_number=0, primary=1, secondary=0),
                    )
            return lookup(agent)

        monkeypatch.setattr(sys.modules["Py4GWCoreLib"].Agent, "GetAgentByID", contradictory)
    else:
        # Reuse the already-frozen original witness; publish a separate child.
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
        child = runtime.publication_result.snapshot.cohorts[1].children[0].GetAccountData()
        if defect == "child":
            child.AgentData.Profession = (1, 0)
        elif defect == "child_semantics":
            child.AgentData.OwnerAgentID = 999
        elif defect == "child_duplicate":
            own = runtime.publication_result.snapshot.cohorts[1]
            own.children = (*own.children, own.children[0])
    snapshot = harness.context.Refresh()
    row = harness.observations[-1].heroes[1]
    assert row["gate"] == gate, (defect, row, snapshot)
    assert row["opening"] == row["committed"] == 0, row
    if defect in ("primary", "secondary"):
        assert row["profession"] == 0
    if defect == "bar":
        assert row["profession"] == 1 and row["qualified"] == 0, row
    if defect == "current_bar":
        assert row["qualified"] == row["role"] == 1 and row["bar"] == 0, row


def test_local_witness_diagnostic_interleaved_positions_and_five_mercenaries(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    remote = runtime.heroes.pop()
    runtime.heroes.insert(2, remote)
    snapshot = harness.context.Refresh()
    observation = harness.observations[-1]
    assert set(observation.heroes) == {1, 2, 4, 5, 6}, observation
    assert all(row["gate"] == "ACCEPTED" and row["committed"] == 1 for row in observation.heroes.values())
    assert _remote_hero_record(snapshot, module).role is module.CleansingRole.ENERGY_SURGE
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK
    assert runtime.hero_skillbar_positions[:5] == [1, 2, 4, 5, 6]


@pytest.mark.parametrize("boundary", ("publication", "runtime", "controlled", "bar"))
def test_local_witness_diagnostic_opening_acceptance_and_closing_rejection(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    if boundary == "publication":
        reader = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem.GetNativeAccountSnapshotV3
        reads = 0

        def read() -> Any:
            nonlocal reads
            reads += 1
            if reads == 2:
                runtime.publication_result.snapshot.cohorts[1].witnesses = ()
            return reader()

        monkeypatch.setattr(
            sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem,
            "GetNativeAccountSnapshotV3",
            read,
        )
    else:
        close = module._read_closing_state
        reads = 0

        def closing() -> Any:
            nonlocal reads
            reads += 1
            if reads == 3:
                if boundary == "bar":
                    runtime.bars[4000] = tuple(range(9000, 9008))
                elif boundary == "controlled":
                    runtime.agent_id += 1
                else:
                    runtime.party_id += 1
            return close()

        monkeypatch.setattr(module, "_read_closing_state", closing)
    snapshot = harness.context.Refresh()
    observation = harness.observations[-1]
    assert observation.heroes[1]["opening"] == 1 and observation.heroes[1]["committed"] == 0, observation
    if boundary == "publication":
        assert observation.values["closing"] == "UNAVAILABLE", observation
    else:
        assert observation.values["final"] == (
            "CONTROLLED_IDENTITY" if boundary == "controlled" else "RUNTIME_REJECTED"
        )
        if boundary == "bar":
            assert observation.values["final_gate"] == "LOCAL_CONTINUITY", observation
    assert all(
        member.role is module.CleansingRole.UNKNOWN
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.HERO
    )


@pytest.mark.parametrize("wire_case", ("present", "absent", "decoder_omitted"))
def test_local_witness_diagnostic_actual_decoder_boundary_reports_raw_not_observed(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    wire_case: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "local_witness_wire_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    assert spec and spec.loader
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    subject = fixtures.build_publication_subject(monkeypatch)
    envelope = fixtures.envelope_v3(subject, tick=runtime.publication_now)
    sources = runtime.publication_result.snapshot.cohorts
    for row in envelope.accounts:
        row.IsSlotActive = False
    for meta in envelope.owners:
        meta.active = meta.witness_count = 0
    for index, source in enumerate(sources):
        original = source.owner.GetAccountData()
        row = envelope.accounts[index]
        row.IsSlotActive = row.IsAccount = True
        row.IsHero = row.IsPet = row.IsNPC = False
        row.AgentData.OwnerAgentID = row.AgentData.HeroID = 0
        row.Key.HWND = original.Key.HWND
        row.Key.EntityType = row.Key.LocalIndex = 0
        envelope.keys[index] = row.Key
        row.AccountEmail = original.AccountEmail
        row.SlotNumber = index
        row.LastUpdated = source.published_tick
        row.AgentPartyData.PartyID = original.AgentPartyData.PartyID
        for name in ("AgentID", "LoginNumber", "CharacterName"):
            setattr(row.AgentData, name, getattr(original.AgentData, name))
        row.AgentData.Profession[:] = original.AgentData.Profession
        row.AgentData.UUID[:] = original.AgentData.UUID
        for name in ("MapID", "Region", "District", "Language"):
            setattr(row.AgentData.Map, name, getattr(original.AgentData.Map, name))
        for slot, skill in zip(row.AgentData.Skillbar.Skills, original.AgentData.Skillbar.Skills):
            slot.Id = skill.Id
        meta = envelope.owners[index]
        meta.active = 1
        meta.instance_type = 0
        meta.instance_epoch = source.instance_epoch
        meta.incarnation[:] = source.incarnation
        meta.character_uuid[:] = source.character_uuid
        meta.published_tick = source.published_tick
        meta.witness_count = len(source.witnesses)
        for wire, witness in zip(meta.witnesses, source.witnesses):
            wire.kind = 1
            wire.hero_id = witness.hero_id
            wire.primary = witness.primary
            wire.secondary = witness.secondary
            wire.skills[:] = witness.skills
            wire.revision = witness.revision
            wire.outpost_epoch = witness.outpost_epoch
            wire.observed_at_tick64 = witness.observed_at_tick64
    if wire_case == "absent":
        envelope.accounts[1].IsSlotActive = False
        envelope.owners[1].active = envelope.owners[1].witness_count = 0
    elif wire_case == "decoder_omitted":
        envelope.keys[1].HWND += 1
        envelope.owners[1].witness_count = 0
    envelope.header.live_count = sum(bool(row.IsSlotActive) for row in envelope.accounts)
    envelope.header.owner_count = sum(bool(meta.active) for meta in envelope.owners)
    runtime.publication_result = fixtures.decode_v3(subject, envelope, now=runtime.publication_now)
    assert runtime.publication_result.status.value == "success", (
        wire_case,
        runtime.publication_result,
    )
    assert len(runtime.publication_result.snapshot.cohorts) == (2 if wire_case == "present" else 1)
    harness.context.Refresh()
    harness.clock[0] += 2.1
    snapshot = harness.context.Refresh()
    observation = harness.observations[-1]
    assert "raw=NOT_OBSERVED" in _local_witness_lines()[-1], _local_witness_lines()
    assert _remote_hero_record(snapshot, module).role is module.CleansingRole.ENERGY_SURGE
    if wire_case == "present":
        assert all(row["qualified"] == row["committed"] == 1 for row in observation.heroes.values())
    else:
        assert observation.values["owner"] == "COHORT_MISSING", (wire_case, observation)
        assert all(row["committed"] == 0 for row in observation.heroes.values())
        assert "DECODER_OMITTED" not in _local_witness_lines()[-1]


def test_local_witness_diagnostic_startup_latest_deadline_dedup_and_lifetime_budget(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    full_roster = list(runtime.heroes)
    runtime.heroes = runtime.heroes[:4]
    for tick in (10.0, 13.0, 25.0):
        harness.clock[0] = tick
        harness.context.Refresh()
        assert not _local_witness_lines() and module._local_witness_records == 0
    runtime.heroes = full_roster
    # The real opening reader returns no local cohort. Recognition need not
    # succeed for a complete, stable blocked roster to be admitted.
    runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    for tick in (26.0, 27.9, 28.0, 35.0):
        harness.clock[0] = tick
        harness.context.Refresh()
        assert len(_local_witness_lines()) == int(tick >= 28.0)
    assert "owner=COHORT_MISSING" in _local_witness_lines()[0]
    # A changing full roster/result cannot postpone reporting indefinitely.
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    for index, tick in enumerate((36.0, 39.0, 42.0, 45.9, 46.0)):
        runtime.bars[4000] = tuple(range(9100 + index * 8, 9108 + index * 8))
        runtime.heroes[0].hero_id = 99 if index % 2 else 28
        harness.clock[0] = tick
        harness.context.Refresh()
        assert len(_local_witness_lines()) == (2 if tick == 46.0 else 1), _local_witness_lines()
    assert "H1=ENTER/BAR_MISMATCH/" in _local_witness_lines()[-1]
    monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", False)
    harness.context.Refresh()
    monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", True)
    runtime.hero_agent_by_position_override[1] = 999
    harness.context.Invalidate()
    harness.context = module.CleansingContext()
    for tick in (50.0, 52.1, 55.0):
        harness.clock[0] = tick
        harness.context.Refresh()
    assert len(_local_witness_lines()) == module._local_witness_records == 3
    assert "H1=POSITION_FAIL/POSITION_FAIL/" in _local_witness_lines()[-1]
    runtime.hero_agent_by_position_override.clear()
    for tick in (60.0, 70.0, 80.0):
        harness.clock[0] = tick
        module.CleansingContext().Refresh()
    assert len(_local_witness_lines()) == 3


def test_local_witness_diagnostic_privacy_allowlist_saturation_and_seven_slot_limit(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, module = cleansing_runtime
    clock = [0.0]
    monkeypatch.setattr(module, "_monotonic", lambda: clock[0])
    observation = module._LocalWitnessObservation()
    module._local_witness_note(
        observation,
        native="PRIVATE email HWND UUID address",
        cohorts=100000,
        contextual=-1,
        claims=100000,
    )
    for slot in range(1, 100):
        module._local_witness_note(observation, slot, entry="ENTER", gate="PRIVATE reason", matches=100000)
    for tick in (0.0, 2.0):
        clock[0] = tick
        module._emit_local_witness_diagnostic(
            observation,
            context_key=("PRIVATE",),
            roster_key=(123456789,),
            complete=True,
        )
    line = _local_witness_lines()[-1]
    assert len(line) <= module._LOCAL_WITNESS_LINE_LIMIT
    assert "PRIVATE" not in line and "123456789" not in line
    assert "cohort=9/0/9" in line and "native=UNKNOWN" in line
    assert "H7=" in line and "H8=" not in line
    assert "qUpUrUbUoUcU" in line, line


def test_local_witness_diagnostic_console_failure_retains_latest_and_bounds_attempts(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    console = sys.modules["PySystem"].Console
    log = console.Log
    attempts: list[str] = []

    def fail(sender: str, line: str, kind: Any) -> None:
        if line.startswith("STAGE3_LOCAL_WITNESS_DIAG_V1 "):
            attempts.append(line)
            if len(attempts) != 2:
                raise RuntimeError("PRIVATE console failure")
        log(sender, line, kind)

    monkeypatch.setattr(console, "Log", fail)
    for tick in (10.0, 12.0, 12.1, 13.0):
        harness.clock[0] = tick
        snapshot = harness.context.Refresh()
        assert snapshot.ready and len(harness.context._baselines) == 6
    assert len(attempts) == 2 and len(_local_witness_lines()) == 1
    runtime.bars[4000] = tuple(range(9100, 9108))
    for tick in (14.0, 16.0, 20.0, 30.0):
        harness.clock[0] = tick
        harness.context.Refresh()
    assert len(attempts) == module._local_witness_records == 3


@pytest.mark.parametrize("failure", ("factory", "record", "clock"))
def test_local_witness_diagnostic_observer_failures_do_not_change_production(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module)
    ordinary = context.Refresh()
    baselines = dict(context._baselines)
    monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", True)

    class Hostile(dict[str, Any]):
        def __setitem__(self, _key: str, _value: Any) -> None:
            raise RuntimeError("PRIVATE observer failure")

    def fail() -> Any:
        raise RuntimeError("PRIVATE observer failure")

    if failure == "factory":
        monkeypatch.setattr(module, "_LocalWitnessObservation", fail)
    elif failure == "record":
        observation = module._LocalWitnessObservation(values=Hostile(), heroes=Hostile())
        monkeypatch.setattr(module, "_LocalWitnessObservation", lambda: observation)
    else:
        monkeypatch.setattr(module, "_monotonic", fail)
        # Keep the existing, independently owned refresh logger out of this fault.
        monkeypatch.setattr(context, "_emit_refresh_diagnostic", lambda: None)
    observed = context.Refresh()
    assert ordinary == observed and baselines == context._baselines, (
        failure,
        ordinary,
        observed,
    )


@pytest.mark.parametrize(
    "fault",
    (
        "valid",
        "absent",
        "nonliving",
        "conversion",
        "zero",
        "read",
        "lookup_read",
        "type_read",
        "conversion_read",
        "secondary_read",
        "missing_owner",
        "witness_missing",
        "bar_mismatch",
        "destination",
    ),
)
def test_local_witness_diagnostic_exact_production_read_order_and_result_parity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    harness.faults.update({agent: "absent" for agent in range(4000, 4005)})
    harness.faults[3001] = "absent"
    if fault in (
        "valid",
        "nonliving",
        "conversion",
        "zero",
        "read",
        "lookup_read",
        "type_read",
        "conversion_read",
        "secondary_read",
    ):
        harness.faults[4000] = fault
    elif fault == "missing_owner":
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    elif fault == "witness_missing":
        own = runtime.publication_result.snapshot.cohorts[1]
        own.witnesses = own.witnesses[1:]
    elif fault == "bar_mismatch":
        runtime.bars[4000] = tuple(range(9100, 9108))
    initial = copy.deepcopy(runtime.__dict__)
    initial_faults = dict(harness.faults)
    outcomes: list[Any] = []
    for enabled in (False, True):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        harness.faults.clear()
        harness.faults.update(initial_faults)
        monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", enabled)
        harness.clock[0] = 10.0
        harness.adapter._living_cache.clear()
        harness.calls.clear()
        harness.trace.clear()
        context = module.CleansingContext()
        snapshot = context.Refresh()
        harness.clock[0] += 2.1
        snapshot = context.Refresh()
        if fault == "destination":
            harness.faults.clear()
            _witness_enter_destination(runtime, module, context)
            for _ in range(3):
                snapshot = context.Refresh()
        outcomes.append(
            (
                snapshot,
                dict(context._baselines),
                dict(context._remote_player_baselines),
                dict(context._remote_hero_origins),
                dict(harness.calls),
                tuple(harness.trace),
                tuple(runtime.hero_agent_positions),
                tuple(runtime.hero_skillbar_positions),
            )
        )
    assert outcomes[0] == outcomes[1], (fault, outcomes)
    assert outcomes[1][0].composition.status is module.CompositionStatus.FALLBACK


def test_local_witness_review_transient_owner_lookup_is_not_publication_rejection(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    core = sys.modules["Py4GWCoreLib"]
    lookup = core.Agent.GetAgentByID
    close = harness.context._recheck_remote_evidence
    in_closing = False
    failures = 0
    publication = copy.deepcopy(runtime.publication_result)

    def transient(agent_id: int) -> Any:
        nonlocal failures
        if in_closing and agent_id == runtime.agent_id and failures == 0:
            failures += 1
            return None
        return lookup(agent_id)

    def closing(**kwargs: Any) -> Any:
        nonlocal in_closing
        in_closing = True
        try:
            return close(**kwargs)
        finally:
            in_closing = False

    monkeypatch.setattr(core.Agent, "GetAgentByID", transient)
    monkeypatch.setattr(harness.context, "_recheck_remote_evidence", closing)
    snapshot = harness.context.Refresh()
    observation = harness.observations[-1]
    assert failures == 1 and runtime.publication_result == publication
    assert observation.values["native"] == observation.values["owner"] == "OK", observation
    assert observation.values["final"] == observation.values["final_gate"] == "OK", observation
    assert all(row["opening"] == 1 and row["committed"] == 0 for row in observation.heroes.values())
    assert all(
        member.role is module.CleansingRole.UNKNOWN
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.HERO
    )
    assert not any(key[0] is module.MemberKind.HERO for key in harness.context._baselines)
    assert observation.values["closing"] == "UNAVAILABLE", observation


def test_local_witness_review_reentrant_identical_refresh_preserves_changed_record_budget(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    console = sys.modules["PySystem"].Console
    log = console.Log
    attempts: list[str] = []
    nested: list[Any] = []

    def reenter(sender: str, line: str, kind: Any) -> None:
        log(sender, line, kind)
        if line.startswith("STAGE3_LOCAL_WITNESS_DIAG_V1 "):
            attempts.append(line)
            if len(attempts) <= 3:
                harness.clock[0] += 1.1
                nested.append(harness.context.Refresh())

    monkeypatch.setattr(console, "Log", reenter)
    harness.context.Refresh()
    harness.clock[0] = 12.1
    outer = harness.context.Refresh()
    assert len(attempts) == len(nested) == module._local_witness_records == 1, attempts
    assert outer.ready and nested[0].ready
    assert f"revision={outer.revision}" in attempts[0], (outer, attempts)
    runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    harness.context.Refresh()
    harness.clock[0] += 2.1
    changed = harness.context.Refresh()
    assert len(attempts) == module._local_witness_records == 2, attempts
    assert "owner=COHORT_MISSING" in attempts[-1] and f"revision={changed.revision}" in attempts[-1]


@pytest.mark.parametrize(
    ("result_name", "expected"),
    (
        ("COHERENT", "OK"),
        ("INCOHERENT", "CLOSING_INCOHERENT"),
        ("CONTROLLED_IDENTITY_CHANGED", "CONTROLLED_IDENTITY"),
        ("RUNTIME_CHANGED", "RUNTIME_REJECTED"),
    ),
)
def test_local_witness_review_closing_contract(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], result_name: str, expected: str
) -> None:
    _runtime, module = cleansing_runtime
    assert module._local_witness_closing_code(getattr(module._ClosingVerification, result_name)) == expected


@pytest.mark.parametrize("boundary", ("success", "native_status", "native_absent", "generic"))
def test_local_witness_review_observed_closing_and_commitment(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    reader = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem.GetNativeAccountSnapshotV3
    reads = 0

    def read() -> Any:
        nonlocal reads
        reads += 1
        result = reader()
        if reads == 2:
            if boundary == "native_status":
                return types.SimpleNamespace(status="busy", snapshot=None)
            if boundary == "native_absent":
                return types.SimpleNamespace(status="success", snapshot=None)
        return result

    def generic(**_kwargs: Any) -> Any:
        return module._ClosingVerification.INCOHERENT

    monkeypatch.setattr(sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem, "GetNativeAccountSnapshotV3", read)
    if boundary == "generic":
        monkeypatch.setattr(harness.context, "_recheck_remote_evidence", generic)
    snapshot = harness.context.Refresh()
    observation = harness.observations[-1]
    expected = (
        "OK" if boundary == "success" else "CLOSING_INCOHERENT" if boundary == "generic" else "PUBLICATION_REJECTED"
    )
    assert observation.values["closing"] == expected, (boundary, observation)
    assert observation.values["native"] == observation.values["owner"] == "OK"
    assert all(row["opening"] == 1 for row in observation.heroes.values())
    assert all(row["committed"] == int(boundary == "success") for row in observation.heroes.values())
    local_records = [member for member in snapshot.members if member.identity.agent_id in range(4000, 4005)]
    assert len(local_records) == 5
    assert all((record.role is not module.CleansingRole.UNKNOWN) == (boundary == "success") for record in local_records)
    assert all(
        (record.identity.stable_key in harness.context._baselines) == (boundary == "success")
        for record in local_records
    )
    # A specific observed failure must survive the caller's generic enum mapping.
    module._local_witness_note(observation, closing="OK")
    assert observation.values["closing"] == expected


@pytest.mark.parametrize("raise_first", (False, True))
def test_local_witness_review_reentrant_changed_evidence_revision_and_bounded_delivery(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, raise_first: bool
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    console = sys.modules["PySystem"].Console
    log = console.Log
    cohorts = runtime.publication_result.snapshot.cohorts
    attempts: list[str] = []
    nested: list[Any] = []
    depth = 0
    maximum_depth = 0

    def reenter(sender: str, line: str, kind: Any) -> None:
        nonlocal depth, maximum_depth
        log(sender, line, kind)
        if not line.startswith("STAGE3_LOCAL_WITNESS_DIAG_V1 "):
            return
        depth += 1
        maximum_depth = max(maximum_depth, depth)
        try:
            attempts.append(line)
            runtime.publication_result.snapshot.cohorts = cohorts[:1] if len(attempts) == 1 else cohorts
            if len(attempts) == 2:
                runtime.bars[4000] = tuple(range(9100, 9108))
            harness.clock[0] += 1.1
            nested.append(harness.context.Refresh())
            if raise_first and len(attempts) == 1:
                raise RuntimeError("PRIVATE emitted then failed")
        finally:
            depth -= 1

    monkeypatch.setattr(console, "Log", reenter)
    harness.context.Refresh()
    harness.clock[0] = 12.1
    for attempt in range(1, 4):
        outer = harness.context.Refresh()
        assert len(attempts) == module._local_witness_records == attempt, attempts
        assert f"revision={outer.revision}" in attempts[-1], (outer, attempts)
        assert not module._local_witness_delivering
        if attempt < 3:
            pending = module._local_witness_pending
            assert pending is not None and pending.revision == nested[-1].revision, (pending, nested)
            assert pending.revision > outer.revision, (pending, outer)
            assert ("owner=COHORT_MISSING" if attempt == 1 else "BAR_MISMATCH") in pending.line
        harness.clock[0] += 2.1
    assert maximum_depth == 1 and len(nested) == 3
    assert "owner=COHORT_MISSING" in attempts[1] and "BAR_MISMATCH" in attempts[2]
    for _ in range(5):
        harness.clock[0] += 20.0
        harness.context.Refresh()
    assert len(attempts) == module._local_witness_records == 3


def test_local_witness_review_failed_reentrant_retry_spacing_and_reservation_release(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    console = sys.modules["PySystem"].Console
    log = console.Log
    attempts: list[tuple[float, str]] = []

    def fail_once(sender: str, line: str, kind: Any) -> None:
        if line.startswith("STAGE3_LOCAL_WITNESS_DIAG_V1 "):
            attempts.append((harness.clock[0], line))
            if len(attempts) == 1:
                harness.clock[0] += 0.4
                harness.context.Refresh()
                raise RuntimeError("PRIVATE console failure")
        log(sender, line, kind)

    monkeypatch.setattr(console, "Log", fail_once)
    for tick in (10.0, 12.0, 12.5, 12.99):
        harness.clock[0] = tick
        snapshot = harness.context.Refresh()
        assert snapshot.ready and len(harness.context._baselines) == 6
    assert len(attempts) == module._local_witness_records == 1 and not module._local_witness_seen
    harness.clock[0] = 13.0
    harness.context.Refresh()
    assert [tick for tick, _line in attempts] == [12.0, 13.0]
    assert len(_local_witness_lines()) == 1 and len(module._local_witness_seen) == 1
    for tick in (14.1, 30.0):
        harness.clock[0] = tick
        harness.context.Refresh()
    assert len(attempts) == module._local_witness_records == 2


@pytest.mark.parametrize(
    "boundary",
    (
        "owner_transient",
        "publication_closing",
        "runtime_closing",
        "console_exception",
        "reentrant_identical",
        "reentrant_changed",
        "reentrant_changed_exception",
    ),
)
def test_local_witness_review_closing_and_console_exact_production_parity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    harness.faults.update({agent: "absent" for agent in (*range(4000, 4005), 3001)})
    initial = copy.deepcopy(runtime.__dict__)
    initial_faults = dict(harness.faults)
    shmem = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem
    native_reader = shmem.GetNativeAccountSnapshotV3
    closing_reader = module._read_closing_state
    console = sys.modules["PySystem"].Console
    logger = console.Log
    outcomes: list[Any] = []
    for enabled in (False, True):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        harness.faults.clear()
        harness.faults.update(initial_faults)
        harness.adapter._living_cache.clear()
        harness.calls.clear()
        harness.trace.clear()
        harness.clock[0] = 10.0
        monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", enabled)
        context = module.CleansingContext()
        close = context._recheck_remote_evidence
        native_reads = 0
        closing_reads = 0
        owner_failed = False
        console_attempts = 0
        nested: list[Any] = []

        def read_native() -> Any:
            nonlocal native_reads
            native_reads += 1
            result = native_reader()
            if boundary == "publication_closing" and native_reads == 2:
                return types.SimpleNamespace(status="busy", snapshot=None)
            return result

        def read_closing() -> Any:
            nonlocal closing_reads
            closing_reads += 1
            harness.trace.append("closing_state")
            state = closing_reader()
            if boundary == "runtime_closing" and closing_reads == 1:
                return replace(state, party_id=state.party_id + 1)
            return state

        def verify(**kwargs: Any) -> Any:
            nonlocal owner_failed
            fail_owner = boundary == "owner_transient" and not owner_failed
            if fail_owner:
                owner_failed = True
                harness.faults[runtime.agent_id] = "absent"
            try:
                return close(**kwargs)
            finally:
                if fail_owner:
                    harness.faults.pop(runtime.agent_id)

        def nested_refresh() -> None:
            if "changed" in boundary:
                runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
            harness.clock[0] += 1.1
            nested.append(context.Refresh())

        def log(sender: str, line: str, kind: Any) -> None:
            nonlocal console_attempts
            if line.startswith("STAGE3_LOCAL_WITNESS_DIAG_V1 "):
                console_attempts += 1
                if boundary.startswith("reentrant"):
                    nested_refresh()
                if boundary in ("console_exception", "reentrant_changed_exception"):
                    raise RuntimeError("PRIVATE console failure")
            logger(sender, line, kind)

        monkeypatch.setattr(shmem, "GetNativeAccountSnapshotV3", read_native)
        monkeypatch.setattr(module, "_read_closing_state", read_closing)
        monkeypatch.setattr(context, "_recheck_remote_evidence", verify)
        monkeypatch.setattr(console, "Log", log)
        snapshots = [context.Refresh()]
        harness.clock[0] = 12.1
        snapshots.append(context.Refresh())
        # OFF performs the same explicit callback work after publication. ON
        # performs it from the actual console callback, after that same publish.
        if not enabled and boundary.startswith("reentrant"):
            nested_refresh()
        if enabled and (boundary.startswith("reentrant") or boundary == "console_exception"):
            assert console_attempts == module._local_witness_records == 1, (boundary, console_attempts)
        outcomes.append(
            (
                tuple(snapshots),
                tuple(nested),
                context.GetSnapshot(),
                dict(context._baselines),
                dict(context._remote_player_baselines),
                dict(context._remote_hero_origins),
                dict(harness.calls),
                tuple(harness.trace),
                tuple(runtime.hero_agent_positions),
                tuple(runtime.hero_skillbar_positions),
                native_reads,
                closing_reads,
            )
        )
        assert all(
            snapshot.composition.status is module.CompositionStatus.FALLBACK for snapshot in (*snapshots, *nested)
        )
    assert outcomes[0] == outcomes[1], (boundary, outcomes)


def _stage3_local_witness_widget(runtime: _Runtime, module: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> Any:
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    harness.faults.update({int(hero.agent_id): "absent" for hero in runtime.heroes})
    core = sys.modules["Py4GWCoreLib"]
    original_cache = core.GLOBAL_CACHE
    owner = _load_global_cache_owner(monkeypatch)
    cache = object.__new__(owner)
    cache.__dict__.update(original_cache.__dict__)
    cache.CleansingContext = module.CleansingContext()
    monkeypatch.setattr(core, "GLOBAL_CACHE", cache)
    widget, name = _instantiate_stage3_browser_widget(monkeypatch)
    monkeypatch.setitem(sys.modules, name, widget.module)

    def now() -> float:
        return harness.clock[0]

    def now_ns() -> int:
        return int(now() * 1_000_000_000)

    monkeypatch.setattr(widget.module, "monotonic", now)
    monkeypatch.setattr(module, "_transition_clock", now)
    monkeypatch.setitem(core.Map.GetLoadingObservation.__globals__, "monotonic", now)
    monkeypatch.setattr(widget.module, "monotonic_ns", now_ns)
    monkeypatch.setattr(sys.modules["Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics"], "monotonic_ns", now_ns)
    return types.SimpleNamespace(widget=widget, probe=widget.module, cache=cache, runtime=harness)


def test_stage3_widget_local_witness_discovery_enable_disable_and_repeated_updates(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    widget, probe = fixture.widget, fixture.probe
    assert not widget.enabled and not module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    assert probe._cleansing_context_module is sys.modules[module.CleansingContext.__module__] is module
    assert fixture.cache.CleansingContext.Refresh.__func__.__globals__ is module.__dict__
    enable = widget.on_enable
    activations = 0

    def enabled() -> None:
        nonlocal activations
        activations += 1
        enable()

    def forbid_import(_name: str) -> Any:
        pytest.fail("widget lifecycle must reuse its canonical module binding")

    monkeypatch.setattr(widget, "on_enable", enabled)
    monkeypatch.setattr(probe, "import_module", forbid_import)
    before = dict(fixture.runtime.calls), tuple(fixture.runtime.trace)
    widget.enable()
    callback_id = widget.update_callback_id
    assert module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC and activations == 1
    assert before == (dict(fixture.runtime.calls), tuple(fixture.runtime.trace))
    for _ in range(8):
        widget.enable()
        _run_stage3_browser_update(widget)
    assert activations == 1 and widget.update_callback_id == callback_id
    assert module._local_witness_records == 0
    pauses: list[int] = []
    monkeypatch.setattr(sys.modules["PyCallback"].PyCallback, "PauseById", pauses.append)
    widget.disable()
    assert not widget.enabled and not module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    assert callback_id in pauses
    fixture.cache._refresh_cleansing_context()
    fixture.runtime.clock[0] += 20.0
    fixture.cache._refresh_cleansing_context()
    assert module._local_witness_records == 0 and not _local_witness_lines()


def test_stage3_widget_local_witness_incomplete_startup_then_full_party(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    full_roster = list(runtime.heroes)
    runtime.heroes = runtime.heroes[:4]
    fixture.widget.enable()
    try:
        for tick in (10.0, 13.0, 25.0):
            fixture.runtime.clock[0] = tick
            fixture.cache._refresh_cleansing_context()
            _run_stage3_browser_update(fixture.widget)
            assert module._local_witness_records == 0 and not _local_witness_lines()
        assert fixture.probe._finished and module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
        runtime.heroes = full_roster
        for tick in (26.0, 28.1):
            fixture.runtime.clock[0] = tick
            fixture.cache._refresh_cleansing_context()
            _run_stage3_browser_update(fixture.widget)
        assert module._local_witness_records == len(_local_witness_lines()) == 1
        assert "close=OK final=OK/OK" in _local_witness_lines()[0]
        assert "w1q1p1r1b1o1c1" in _local_witness_lines()[0]
    finally:
        fixture.widget.disable()
    assert not module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC


@pytest.mark.parametrize("churn", (False, True))
def test_stage3_widget_local_witness_survives_inconclusive_until_stable_or_deadline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, churn: bool
) -> None:
    runtime, module = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    fixture.widget.enable()
    _run_stage3_browser_update(fixture.widget)
    if churn:
        runtime.bars[4000] = tuple(range(9100, 9108))
        for index, tick in enumerate((10.1, 13.1, 16.1, 19.9)):
            runtime.heroes[0].hero_id = 28 if index % 2 else 99
            fixture.runtime.clock[0] = tick
            fixture.cache._refresh_cleansing_context()
            _run_stage3_browser_update(fixture.widget)
    else:
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
        fixture.runtime.clock[0] = 19.0
        fixture.cache._refresh_cleansing_context()
        _run_stage3_browser_update(fixture.widget)
    assert not _local_witness_lines() and module._local_witness_pending is not None
    fixture.runtime.clock[0] = 20.0
    _run_stage3_browser_update(fixture.widget)
    assert fixture.probe._finished and fixture.widget.enabled and module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    logs = sys.modules["PySystem"].stage3_console_logs
    probe_lines = [line for _, line, _ in logs if line.startswith("STAGE3_EVIDENCE_V1 ")]
    assert "result=INCONCLUSIVE reason=outpost_baseline_not_established" in probe_lines[-1]
    frozen_probe = fixture.probe._terminal_outcome, fixture.probe._lines, fixture.probe._characters
    fixture.runtime.clock[0] = 20.2 if churn else 21.1
    if churn:
        runtime.heroes[0].hero_id = 99
    fixture.cache._refresh_cleansing_context()
    snapshot = fixture.cache.CleansingContext.GetSnapshot()
    _run_stage3_browser_update(fixture.widget)
    lines = _local_witness_lines()
    assert len(lines) == module._local_witness_records == 1, lines
    assert ("WITNESS_MISSING" if churn else "owner=COHORT_MISSING") in lines[0], lines
    assert f"revision={snapshot.revision}" in lines[0]
    assert frozen_probe == (fixture.probe._terminal_outcome, fixture.probe._lines, fixture.probe._characters)
    assert len(lines[0]) <= 640 and "H6=" not in lines[0]
    for private in (runtime.account_email, runtime.character_name, "4000", "PRIVATE", "HWND", "UUID"):
        assert private not in lines[0]
    fixture.widget.disable()
    assert not module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC


def test_stage3_widget_local_witness_lifetime_budget_survives_toggles_zone_and_context_replacement(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    full_publication = runtime.publication_result
    fixture.widget.enable()
    for index in range(3):
        if index == 1:
            runtime.publication_result = copy.deepcopy(full_publication)
            runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
        elif index == 2:
            runtime.publication_result = full_publication
            runtime.bars[4000] = tuple(range(9100, 9108))
        for tick in (10.0 + index * 10, 12.1 + index * 10):
            fixture.runtime.clock[0] = tick
            fixture.cache._refresh_cleansing_context()
            _run_stage3_browser_update(fixture.widget)
        assert module._local_witness_records == len(_local_witness_lines()) == index + 1
        seen = set(module._local_witness_seen)
        fixture.widget.disable()
        fixture.cache.CleansingContext.InvalidateForEnvironmentGate(map_loading_observed=True)
        fixture.cache.CleansingContext = module.CleansingContext()
        fixture.widget.enable()
        assert fixture.probe._cleansing_context_module is module
        assert module._local_witness_records == index + 1 and module._local_witness_seen == seen
    runtime.hero_agent_by_position_override[1] = 999
    for tick in (40.0, 50.0, 70.0):
        fixture.runtime.clock[0] = tick
        fixture.cache._refresh_cleansing_context()
        _run_stage3_browser_update(fixture.widget)
    assert len(_local_witness_lines()) == module._local_witness_records == 3
    fixture.widget.disable()


def test_stage3_widget_local_witness_is_bound_to_its_client_module_instance(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, client_a = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, client_a, monkeypatch)
    # Separate module instances model the independent interpreter registries.
    # Replacing this registry entry cannot retarget A's already-bound module.
    client_b = _load_source(
        monkeypatch,
        "Py4GWCoreLib.GlobalCache.CleansingContext",
        _REPO_ROOT / "Py4GWCoreLib/GlobalCache/CleansingContext.py",
    )
    widget_b, name_b = _instantiate_stage3_browser_widget(monkeypatch)
    monkeypatch.setitem(sys.modules, name_b, widget_b.module)
    assert widget_b.module._cleansing_context_module is client_b
    assert fixture.probe._cleansing_context_module is client_a
    assert not client_a.STAGE3_LOCAL_WITNESS_DIAGNOSTIC and not client_b.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    fixture.widget.enable()
    assert client_a.STAGE3_LOCAL_WITNESS_DIAGNOSTIC and not client_b.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    widget_b.enable()
    fixture.widget.disable()
    assert not client_a.STAGE3_LOCAL_WITNESS_DIAGNOSTIC and client_b.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    widget_b.disable()
    assert not client_b.STAGE3_LOCAL_WITNESS_DIAGNOSTIC


@pytest.mark.parametrize("failure", ("activation", "final", "local_witness"))
def test_stage3_widget_local_witness_console_errors_and_disable_cleanup(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    runtime, module = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    console = sys.modules["PySystem"].Console
    logger = console.Log
    failed: list[str] = []
    prefix = "STAGE3_LOCAL_WITNESS_DIAG_V1 " if failure == "local_witness" else f"STAGE3_EVIDENCE_V1 event={failure} "

    def log(sender: str, line: str, kind: Any) -> None:
        if line.startswith(prefix):
            failed.append(line)
            raise RuntimeError("controlled console error")
        logger(sender, line, kind)

    monkeypatch.setattr(console, "Log", log)
    fixture.widget.enable()
    assert fixture.widget.enabled and module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    for tick in (10.0, 12.1, 13.2, 14.3, 20.0):
        fixture.runtime.clock[0] = tick
        fixture.cache._refresh_cleansing_context()
        snapshot = fixture.cache.CleansingContext.GetSnapshot()
        assert snapshot.ready and snapshot.composition.status is module.CompositionStatus.FALLBACK
        assert _remote_hero_record(snapshot, module, hero_id=23).role is module.CleansingRole.ENERGY_SURGE
        _run_stage3_browser_update(fixture.widget)
    fixture.widget.disable()
    assert failed and not module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC and not fixture.widget.enabled
    if failure == "final":
        assert not fixture.probe._finished and fixture.probe._terminal_outcome is not None
        assert "outpost_baseline_not_established" in fixture.probe._terminal_details
    elif failure == "local_witness":
        assert len(failed) == module._local_witness_records == 3
    assert all(len(line) <= 640 for line in _local_witness_lines())


@pytest.mark.parametrize("scenario", ("qualified", "missing_cohort", "bar_mismatch", "destination", "console_error"))
def test_stage3_widget_local_witness_exact_read_and_production_parity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    runtime, module = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    if scenario == "missing_cohort":
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    elif scenario == "bar_mismatch":
        runtime.bars[4000] = tuple(range(9100, 9108))
    initial = copy.deepcopy(runtime.__dict__)
    initial_faults = dict(fixture.runtime.faults)
    console = sys.modules["PySystem"].Console
    logger = console.Log

    def log(sender: str, line: str, kind: Any) -> None:
        if scenario == "console_error" and line.startswith("STAGE3_LOCAL_WITNESS_DIAG_V1 "):
            raise RuntimeError("controlled console error")
        logger(sender, line, kind)

    monkeypatch.setattr(console, "Log", log)
    outcomes: list[Any] = []
    for enabled in (False, True):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        fixture.runtime.faults.clear()
        fixture.runtime.faults.update(initial_faults)
        fixture.runtime.adapter._living_cache.clear()
        fixture.runtime.calls.clear()
        fixture.runtime.trace.clear()
        fixture.runtime.clock[0] = 10.0
        fixture.cache.CleansingContext = module.CleansingContext()
        fixture.widget.enable()
        # Both runs use the real enabled probe. OFF models its prior behavior;
        # this isolates diagnostic enablement from the probe's existing reads.
        if not enabled:
            monkeypatch.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", False)
        snapshots: list[Any] = []
        for tick in (10.0, 12.1):
            fixture.runtime.clock[0] = tick
            fixture.cache._refresh_cleansing_context()
            snapshots.append(fixture.cache.CleansingContext.GetSnapshot())
            _run_stage3_browser_update(fixture.widget)
        if scenario == "destination":
            fixture.runtime.faults.clear()
            _witness_enter_destination(runtime, module, fixture.cache.CleansingContext)
            for _ in range(3):
                fixture.runtime.clock[0] += 1.1
                fixture.cache._refresh_cleansing_context()
                snapshots.append(fixture.cache.CleansingContext.GetSnapshot())
                _run_stage3_browser_update(fixture.widget)
        context = fixture.cache.CleansingContext
        outcomes.append(
            (
                tuple(snapshots),
                dict(context._baselines),
                dict(context._remote_player_baselines),
                dict(context._remote_hero_origins),
                dict(fixture.runtime.calls),
                tuple(fixture.runtime.trace),
                tuple(runtime.hero_agent_positions),
                tuple(runtime.hero_skillbar_positions),
            )
        )
        assert all(snapshot.composition.status is module.CompositionStatus.FALLBACK for snapshot in snapshots)
        fixture.widget.disable()
        assert not module.STAGE3_LOCAL_WITNESS_DIAGNOSTIC
    assert outcomes[0] == outcomes[1], (scenario, outcomes)


def _load_char_context_layout(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Load the real Win32 declarations without registering runtime callbacks."""
    assert (
        ctypes.sizeof(ctypes.c_void_p) == 4 and ctypes.sizeof(ctypes.c_wchar) == 2
    ), "CharContext regressions require the supported Windows 32-bit interpreter"
    package = "_stage3_char_layout"
    for name in (package, f"{package}.internals", f"{package}.context"):
        _install_package(monkeypatch, name)
    for name in ("helpers", "gw_array"):
        _load_source(
            monkeypatch,
            f"{package}.internals.{name}",
            _REPO_ROOT / "Py4GWCoreLib/native_src/internals" / f"{name}.py",
        )
    callback = _install_module(monkeypatch, "PyCallback")

    def register_callback(*_args: Any, **_kwargs: Any) -> None:
        pass

    callback.__dict__.update(
        PyCallback=types.SimpleNamespace(Register=register_callback),
        Phase=types.SimpleNamespace(PreUpdate=0),
        Context=types.SimpleNamespace(Draw=0),
    )
    return _load_source(
        monkeypatch,
        f"{package}.context.CharContext",
        _REPO_ROOT / "Py4GWCoreLib/native_src/context/CharContext.py",
    )


def _synthetic_char_context(layout: types.ModuleType, email: str, prefix: str = "ABCD") -> Any:
    """Own a synthetic buffer; write the email at Native's independent offset."""
    assert len(prefix) == 4 and len(email.encode("utf-16-le")) < 0x80, (prefix, email)
    memory = ctypes.create_string_buffer(0x458)
    ctypes.memmove(ctypes.addressof(memory) + 0x3D0, prefix.encode("utf-16-le"), 8)
    encoded = (email + "\0").encode("utf-16-le")
    ctypes.memmove(ctypes.addressof(memory) + 0x3D8, encoded, len(encoded))
    return types.SimpleNamespace(memory=memory, view=layout.CharContextStruct.from_buffer(memory))


def _install_real_account_identity(runtime: _Runtime, monkeypatch: pytest.MonkeyPatch, email: str) -> Any:
    layout = _load_char_context_layout(monkeypatch)
    synthetic = _synthetic_char_context(layout, email)
    core = sys.modules["Py4GWCoreLib"]
    gw_context = sys.modules["Py4GWCoreLib.Context"].GWContext

    def current_char() -> Any:
        view = synthetic.view
        view.current_map_id = runtime.map_id
        view.observe_map_id = runtime.map_id
        view.district_number = runtime.district_id
        view.language = runtime.language_id
        view.player_uuid_ptr[:] = runtime.local_uuid
        view.player_name_enc = runtime.character_name
        return view

    monkeypatch.setattr(gw_context.Char, "GetContext", current_char)
    source = _REPO_ROOT / "Py4GWCoreLib/Player.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    player = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Player")
    methods = {"GetAccountEmail", "_sanitize_account_email_or_fallback", "_hwnd_account_fallback"}
    body: list[ast.stmt] = [
        node
        for node in player.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in methods
            or isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "_ACCOUNT_EMAIL_MAX_LEN" for target in node.targets)
        )
    ]
    assert {node.name for node in body if isinstance(node, ast.FunctionDef)} == methods
    # Preserve the production getter and sanitizer bodies; simulated frames bypass only the frame cache.
    for node in body:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = [ast.Name(id="staticmethod", ctx=ast.Load())]
    namespace: dict[str, Any] = {
        "__name__": "Py4GWCoreLib.Player",
        "__package__": "Py4GWCoreLib",
        "GWContext": gw_context,
        "PySystem": sys.modules["PySystem"],
    }
    definition = ast.ClassDef(name="Player", bases=[], keywords=[], body=body, decorator_list=[])
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[definition], type_ignores=[])), str(source), "exec"),
        namespace,
    )
    real_player = namespace["Player"]
    real_player.IsPlayerLoaded = staticmethod(lambda: runtime.ready)
    map_module = _install_module(monkeypatch, "Py4GWCoreLib.Map")
    map_module.__dict__["Map"] = core.Map
    monkeypatch.setattr(core.Player, "GetAccountEmail", real_player.GetAccountEmail)
    monkeypatch.setattr(
        core.Player, "_sanitize_account_email_or_fallback", real_player._sanitize_account_email_or_fallback
    )
    synthetic.player = real_player
    return synthetic


def test_char_context_native_win32_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    layout = _load_char_context_layout(monkeypatch)
    expected = {
        "h0000_array": 0x0000,
        "h0010": 0x0010,
        "h0014_array": 0x0014,
        "h0024": 0x0024,
        "h0034_array": 0x0034,
        "h0044_array": 0x0044,
        "h0054": 0x0054,
        "player_uuid_ptr": 0x0064,
        "player_name_enc": 0x0074,
        "h009C": 0x009C,
        "h00EC_array": 0x00EC,
        "h00FC": 0x00FC,
        "world_flags": 0x0190,
        "token1": 0x0194,
        "map_id": 0x0198,
        "is_explorable": 0x019C,
        "host": 0x01A0,
        "token2": 0x01B8,
        "h01BC": 0x01BC,
        "h0228": 0x0228,
        "district_number": 0x022C,
        "language": 0x0230,
        "observe_map_id": 0x0234,
        "current_map_id": 0x0238,
        "observe_map_type": 0x023C,
        "current_map_type": 0x0240,
        "h0244": 0x0244,
        "observer_matches_array": 0x0258,
        "h0268": 0x0268,
        "player_flags": 0x02AC,
        "player_number": 0x02B0,
        "h02B4": 0x02B4,
        "progress_bar_ptr": 0x0360,
        "h0360": 0x0364,
        "player_email_ptr": 0x03D8,
    }
    actual = {name: getattr(layout.CharContextStruct, name).offset for name, _ in layout.CharContextStruct._fields_}
    assert actual == expected, ("Native CharContext field offsets", expected, actual)
    assert layout.CharContextStruct._pack_ == 1
    assert ctypes.alignment(layout.CharContextStruct) == 1
    assert ctypes.sizeof(layout.CharContextStruct) == 0x458
    assert ctypes.sizeof(layout.ProgressBar) == 0x2C
    types_by_name = dict(layout.CharContextStruct._fields_)
    assert types_by_name["h02B4"]._length_ == 43
    assert types_by_name["h0360"]._length_ == 29
    assert types_by_name["player_email_ptr"] is ctypes.c_wchar * 64
    assert types_by_name["progress_bar_ptr"] is ctypes.POINTER(layout.ProgressBar)


@pytest.mark.parametrize("prefix", ("ABCD", "\x01\x02\x03\x04", "\0\0\0\0"), ids=("text", "controls", "zeros"))
def test_char_context_reads_native_email_past_misleading_prefix(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    layout = _load_char_context_layout(monkeypatch)
    synthetic = _synthetic_char_context(layout, "current@example.test", prefix)
    view = synthetic.view
    assert view.player_email_encoded_str == view.player_email_str == "current@example.test", (
        prefix,
        view.player_email_str,
    )
    legacy = ctypes.wstring_at(ctypes.addressof(synthetic.memory) + 0x3D0, 64).split("\0", 1)[0]
    assert layout.encoded_wstr_to_str(legacy) != view.player_email_str, (prefix, legacy)
    progress = layout.ProgressBar()
    progress.pips, progress.progress = 3, 0.5
    ctypes.c_uint32.from_buffer(synthetic.memory, 0x360).value = ctypes.addressof(progress)
    assert view.progress_bar.pips == 3 and view.progress_bar.progress == 0.5
    # The preserved padding name now denotes Native's h0364 array, including its final words.
    ctypes.c_uint32.from_buffer(synthetic.memory, 0x364).value = 0x12345678
    assert view.h0360[0] == 0x12345678


@pytest.mark.parametrize(
    ("local_email", "publisher_email", "accepted"),
    (
        ("current@example.test", "current@example.test", True),
        (" CURRENT@EXAMPLE.TEST ", "current@example.test", True),
        ("current@example.test", "different@example.test", False),
        ("", "current@example.test", False),
        ("bad\x01identity", "current@example.test", False),
        ("nonascii\u00e9@example.test", "nonascii?@example.test", False),
    ),
    ids=("match", "existing-normalization", "mismatch", "missing", "malformed", "encoding-separate"),
)
def test_char_context_stage3_independent_owner_identity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    local_email: str,
    publisher_email: str,
    accepted: bool,
) -> None:
    runtime, module = cleansing_runtime
    runtime.account_email = publisher_email
    harness = _local_witness_diagnostic_fixture(runtime, module, monkeypatch)
    synthetic = _install_real_account_identity(runtime, monkeypatch, local_email)
    snapshot = harness.context.Refresh()
    if not local_email:
        assert not snapshot.ready and snapshot.members == ()
        assert not harness.observations
        assert not harness.context._baselines and not harness.context._remote_player_baselines
        assert harness.context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED
        return
    observation = harness.observations[-1]
    local = [member for member in snapshot.members if member.evidence_source is module.EvidenceSource.LOCAL_HERO]
    assert len(local) == 5, (local_email, publisher_email, snapshot)
    assert all((member.role is not module.CleansingRole.UNKNOWN) == accepted for member in local), snapshot
    assert observation.values["owner"] == ("OK" if accepted else "OWNER_EMAIL"), observation
    assert all(row["opening"] == row["committed"] == int(accepted) for row in observation.heroes.values()), observation
    assert observation.values["final_gate"] == ("OK" if local_email else "CONTROLLED_IDENTITY"), observation
    if not accepted:
        assert all("qualified" not in row for row in observation.heroes.values()), observation
    assert len(harness.context._baselines) == (6 if accepted else int(bool(local_email))), harness.context._baselines
    if local_email:
        assert _remote_player_record(snapshot, module).role is module.CleansingRole.BIP, snapshot
        assert _remote_hero_record(snapshot, module).role is module.CleansingRole.ENERGY_SURGE, snapshot
        assert synthetic.player.GetAccountEmail().strip().casefold() == module._read_closing_state().local_account_email
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK


@pytest.mark.parametrize("unavailable", ("char", "not_ready", "cinematic"))
def test_char_context_stage3_unavailable_identity_fails_closed(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, unavailable: str
) -> None:
    runtime, module = cleansing_runtime
    runtime.account_email = "current@example.test"
    context = _outpost_witness_party(runtime, module)
    _install_real_account_identity(runtime, monkeypatch, "current@example.test")
    if unavailable == "char":
        monkeypatch.setattr(sys.modules["Py4GWCoreLib.Context"].GWContext.Char, "GetContext", lambda: None)
    elif unavailable == "not_ready":
        runtime.ready = False
    else:
        runtime.cinematic = True
    assert sys.modules["Py4GWCoreLib"].Player.GetAccountEmail() == ""
    snapshot = context.Refresh()
    assert not context._baselines, (unavailable, snapshot, context._baselines)
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members), (unavailable, snapshot)
    assert snapshot.composition.status is module.CompositionStatus.FALLBACK


def test_char_context_stage3_real_identity_survives_loading_destination(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    runtime.account_email = "current@example.test"
    context = _outpost_witness_party(runtime, module)
    _install_real_account_identity(runtime, monkeypatch, "current@example.test")
    outpost = context.Refresh()
    assert len(context._baselines) == 6 and len(outpost.members) == 8, outpost
    _witness_enter_destination(runtime, module, context)
    destination = context.Refresh()
    assert len(destination.members) == 8 and all(
        member.role is not module.CleansingRole.UNKNOWN for member in destination.members
    ), destination
    assert len(context._baselines) == 6
    assert _remote_player_record(destination, module).role is module.CleansingRole.BIP
    assert _remote_hero_record(destination, module).role is module.CleansingRole.ENERGY_SURGE
    assert destination.composition.status is module.CompositionStatus.FALLBACK


def _assert_outpost_delta(probe: Any, output: str, *expected: str) -> str:
    records = _assert_stage3_output_budget(probe, output)
    deltas = [line for line in records if "event=outpost_delta " in line]
    assert len(deltas) == 1, records
    delta = deltas[0]
    assert len(delta) + 1 <= probe._MAX_OUTPOST_DELTA_CHARACTERS, delta
    assert all(field in delta for field in expected), (expected, delta)
    assert "reason=outpost_changed_before_loading" in records[-1], records
    assert probe._finished and probe._pending_outpost_delta is None
    return delta


def test_stage3_probe_outpost_delta_reason_only_real_recognition_transition(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    probe.on_enable()
    _probe_enter_outpost(harness)
    before = context.GetSnapshot()
    initial_output = capsys.readouterr().out
    assert "created roster=8/8" in initial_output and "event=outpost_detail " not in initial_output
    assert probe._pending_outpost_details
    runtime.unavailable_agents.remove(next(int(hero.agent_id) for hero in runtime.heroes))
    clock.advance(0.26)
    upkeeper.main()
    after = context.GetSnapshot()
    changed = {
        name
        for old, new in zip(before.members, after.members)
        for name in old.__dataclass_fields__
        if getattr(old, name) != getattr(new, name)
    }
    assert changed == {"reason"} and all(member.role is not module.CleansingRole.UNKNOWN for member in after.members)

    def forbidden_read(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("outpost delta must use captured values, without runtime or Native reads")

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", forbidden_read)
    monkeypatch.setattr(cache.ShMem, "GetBaseTimestamp", forbidden_read)
    core = sys.modules["Py4GWCoreLib"]
    for api, names in (
        (core.Agent, ("GetAgentByID", "GetProfessions")),
        (core.Player, ("GetAgentID", "GetLoginNumber", "GetAccountEmail", "GetName", "GetPlayerUUID")),
        (core.Map, ("GetMapID", "GetRegion", "GetDistrict", "GetLanguage")),
    ):
        for name in names:
            monkeypatch.setattr(api, name, forbidden_read)
    monkeypatch.setattr(context, "Refresh", forbidden_read)
    snapshot_reads: list[None] = []
    original_snapshot = context.GetSnapshot

    def snapshot() -> Any:
        snapshot_reads.append(None)
        return original_snapshot()

    monkeypatch.setattr(context, "GetSnapshot", snapshot)
    probe.update()
    output = initial_output + capsys.readouterr().out
    delta = _assert_outpost_delta(
        probe, output, "ready=0 lifecycle=0 map=0 signature=1", "class=reason_only fields=LH1.reason trunc=0"
    )
    assert snapshot_reads == []
    details = [line for line in output.splitlines() if "event=outpost_detail " in line]
    assert details and all("source=baseline" in line for line in details), details
    assert output.index(delta) < output.index(details[0]) < output.index("event=final "), output


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        ("reason", "LH1.reason"),
        ("role", "LH1.role"),
        ("hero_identity", "LH1.member_id"),
        ("endpoint", "LH1.agent_id"),
        ("owner", "LH1.owner_id"),
        ("publisher", "publisher.incarnation"),
        ("publisher_uuid", "publisher.character_uuid"),
        ("publisher_email", "publisher.account_email"),
        ("publisher_hwnd", "publisher.hwnd"),
        ("recovery", "publisher.recovery_epoch"),
        ("ready", "ready=1 lifecycle=0 map=0"),
        ("lifecycle", "ready=0 lifecycle=1 map=0"),
        ("map", "ready=0 lifecycle=0 map=1"),
        ("character", "character_identity"),
        ("composition", "composition.status"),
        ("local_baseline", "LBH1.anchors"),
        ("remote_baseline", "RB1.party_id"),
        ("baseline_loss", "local_baselines.count"),
    ),
)
def test_stage3_probe_outpost_delta_named_fields_and_private_values(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
    expected: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    snapshot = context.GetSnapshot()
    members = list(snapshot.members)
    position = next(i for i, member in enumerate(members) if member.evidence_source is module.EvidenceSource.LOCAL_HERO)
    member = members[position]
    private_number = 987654321
    private_text = "PRIVATE_DELTA_SENTINEL@example.test"
    if mutation in ("reason", "role", "hero_identity", "endpoint", "owner"):
        if mutation == "reason":
            members[position] = replace(member, reason=private_text)
        elif mutation == "role":
            members[position] = replace(member, role=module.CleansingRole.UNKNOWN)
        else:
            field = {"hero_identity": "member_id", "endpoint": "agent_id", "owner": "owner_id"}[mutation]
            members[position] = replace(member, identity=replace(member.identity, **{field: private_number}))
        context._snapshot = replace(snapshot, members=tuple(members))
    elif mutation in (
        "publisher",
        "publisher_uuid",
        "publisher_email",
        "publisher_hwnd",
        "recovery",
        "remote_baseline",
    ):
        key, baseline = next(iter(context._remote_player_baselines.items()))
        if mutation == "remote_baseline":
            baseline = replace(baseline, party_id=private_number)
        else:
            publisher_changes = {
                "publisher": {"incarnation": b"PRIVATE_PUBLISHER"},
                "publisher_uuid": {"character_uuid": (private_number, 0, 0, 0)},
                "publisher_email": {"account_email": private_text},
                "publisher_hwnd": {"hwnd": private_number},
                "recovery": {"recovery_epoch": private_number},
            }
            publisher = replace(baseline.publisher, **publisher_changes[mutation])
            baseline = replace(baseline, publisher=publisher)
        context._remote_player_baselines[key] = baseline
    elif mutation == "local_baseline":
        context._baselines[member.identity.stable_key] = replace(
            context._baselines[member.identity.stable_key], relevant_anchors=(private_number,)
        )
    elif mutation == "baseline_loss":
        context._baselines.pop(member.identity.stable_key)
    elif mutation == "composition":
        context._snapshot = replace(
            snapshot, composition=replace(snapshot.composition, status=module.CompositionStatus.ACTIVE)
        )
    else:
        changes = {
            "ready": {"ready": False},
            "lifecycle": {"lifecycle_epoch": snapshot.lifecycle_epoch + 1},
            "map": {"map_id": private_number},
            "character": {"character_identity": (private_text, private_text)},
        }
        context._snapshot = replace(snapshot, **changes[mutation])
    clock.advance(0.26)
    probe.update()
    output = capsys.readouterr().out
    delta = _assert_outpost_delta(probe, output, expected)
    assert ("class=reason_only" in delta) == (mutation == "reason"), (mutation, delta)
    for private in (
        str(private_number),
        private_text,
        "PRIVATE_PUBLISHER",
        runtime.account_email,
        runtime.character_name,
    ):
        assert private not in output, (mutation, private, output)
    assert probe._loading_event is None and probe._destination_samples == 0


def test_stage3_probe_outpost_delta_many_changes_are_deterministic_and_bounded(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    snapshot = context.GetSnapshot()
    context._snapshot = replace(
        snapshot,
        ready=False,
        lifecycle_epoch=snapshot.lifecycle_epoch + 1,
        map_id=987654321,
        character_identity=("PRIVATE_ACCOUNT", "PRIVATE_CHARACTER"),
        members=tuple(
            replace(
                member,
                identity=replace(member.identity, owner_id=987654321, member_id=987654321, agent_id=987654321),
                role=module.CleansingRole.UNKNOWN,
                candidate_role=module.CleansingRole.UNKNOWN,
                reason="PRIVATE_REASON",
                primary_profession=987654321,
                anchor_skill_ids=(987654321,),
                remote_provenance_generation=987654321,
            )
            for member in snapshot.members
        ),
    )
    current = probe._snapshot_evidence(context.GetSnapshot(), context)
    details = probe._outpost_delta_details(probe._outpost_baseline, current)
    assert details == probe._outpost_delta_details(probe._outpost_baseline, current)
    clock.advance(0.26)
    probe.update()
    delta = _assert_outpost_delta(probe, capsys.readouterr().out, "class=mixed", "trunc=1")
    assert delta == probe._record("outpost_delta", details)
    assert "PRIVATE" not in delta and "987654321" not in delta


@pytest.mark.parametrize("pressure", ("characters", "lines"))
def test_stage3_probe_outpost_delta_and_verdict_have_mandatory_capacity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pressure: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    if pressure == "lines":
        monkeypatch.setattr(probe, "_MAX_OUTPUT_LINES", 8)
        while probe._optional_lines < probe._MAX_OUTPUT_LINES - probe._RESERVED_EVIDENCE_LINES - 1:
            assert probe._emit("padding", "x")
    else:
        capacity = probe._MAX_OUTPUT_CHARACTERS - probe._REQUIRED_EVIDENCE_CHARACTERS - probe._FINAL_OUTPUT_RESERVE
        assert probe._emit("padding", "x" * (capacity - len(probe._record("padding")) - 2))
    assert not probe._emit("padding", "optional diagnostic must be refused")
    _probe_enter_outpost(harness)
    snapshot = context.GetSnapshot()
    context._snapshot = replace(snapshot, ready=False, map_id=987654321, lifecycle_epoch=snapshot.lifecycle_epoch + 1)
    clock.advance(0.26)
    probe.update()
    delta = _assert_outpost_delta(probe, capsys.readouterr().out, "ready=1 lifecycle=1 map=1 signature=1")
    assert "trunc=0" in delta
    assert probe._required_lines == 4 and probe._required_characters <= probe._REQUIRED_EVIDENCE_CHARACTERS


@pytest.mark.parametrize("interrupted_event", ("outpost_delta", "final"))
@pytest.mark.parametrize("delivery", ("exception", "refused"))
def test_stage3_probe_outpost_delta_retries_output_without_duplicate_acknowledged_evidence(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    interrupted_event: str,
    delivery: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    context._snapshot = replace(context.GetSnapshot(), ready=False)
    original_emit = probe._emit
    interrupted = False

    def emit(event: str, details: str = "", **kwargs: Any) -> bool:
        nonlocal interrupted
        if event == interrupted_event and not interrupted:
            interrupted = True
            if delivery == "refused":
                return False
            raise RuntimeError("PRIVATE console exception")
        return bool(original_emit(event, details, **kwargs))

    monkeypatch.setattr(probe, "_emit", emit)
    clock.advance(0.26)
    probe.update()
    assert interrupted and not probe._finished and probe._terminal_outcome is not None
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) is None
    assert (probe._pending_outpost_delta is not None) == (interrupted_event == "outpost_delta")
    clock.advance(1.01)
    probe.update()
    output = capsys.readouterr().out
    _assert_outpost_delta(probe, output, "ready=1")
    assert output.count("event=final ") == 1 and "PRIVATE" not in output


def test_stage3_probe_owner_return_to_outpost_invalidates_samples_at_widest_counters(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _seed_stage3_probe_counters(harness, (1 << 64) - 100)
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    assert probe._destination_samples == len(probe._pending_destination_sample_details) == 2
    # A live phase alone is not authority; the owner observes the return and
    # retires the admitted destination before the verdict can be committed.
    runtime.outpost, runtime.explorable = True, False
    _context.ObserveCurrentEnvironment()
    clock.advance(0.26)
    probe.update()
    output = capsys.readouterr().out
    _assert_stage3_output_budget(probe, output)
    assert not any("event=destination_sample " in line for line in output.splitlines()), output
    assert "reason=production_transition_retired" in output
    assert "loading=1 samples=0/3" in output, output
    assert probe._required_lines == 3
    assert probe._required_characters <= probe._REQUIRED_EVIDENCE_CHARACTERS


def test_stage3_probe_outpost_delta_widget_rearm_and_stable_refresh_publication(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(
        monkeypatch, runtime, module, load_probe=False, role_distribution="remote_bip"
    )
    context, _cache, upkeeper, _probe, clock, diagnostics, _runtime = harness
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    upkeeper.main()
    widget, name = _instantiate_stage3_browser_widget(monkeypatch)
    probe = widget.module
    assert probe is not None
    monkeypatch.setattr(probe, "monotonic", clock.read)
    monkeypatch.setattr(probe, "monotonic_ns", clock.read_ns)
    try:
        widget.enable()
        _run_stage3_browser_update(widget)
        first_attempt, first_baseline = probe._attempt_id, probe._outpost_baseline
        snapshot = context.GetSnapshot()
        members = list(snapshot.members)
        members[0] = replace(members[0], reason="PRIVATE_CHANGED_REASON")
        context._snapshot = replace(snapshot, members=tuple(members))
        clock.advance(0.26)
        _run_stage3_browser_update(widget)
        _assert_outpost_delta(probe, capsys.readouterr().out, "class=reason_only")
        widget.disable()
        upkeeper.main()
        widget.enable()
        assert probe._outpost_baseline is None and probe._pending_outpost_delta is None
        _run_stage3_browser_update(widget)
        assert probe._attempt_id == first_attempt + 1 and probe._outpost_baseline is not first_baseline
        for _ in range(24):
            clock.advance(0.26)
            runtime.publication_now += 260
            runtime.publication_result = _remote_publication(
                runtime, module, include_local=True, omit_outpost_children=True
            )
            upkeeper.main()
            context._snapshot = replace(context.GetSnapshot(), revision=context.GetSnapshot().revision + 1)
            context._revision = context.GetSnapshot().revision
            _run_stage3_browser_update(widget)
            assert not probe._finished and probe._pending_outpost_delta is None
        assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.active_attempt_id(context) == probe._attempt_id
        assert "event=outpost_delta " not in capsys.readouterr().out
    finally:
        widget.disable()
        sys.modules.pop(name, None)


def _cause_widget(runtime: _Runtime, module: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> Any:
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    fixture.cache._refresh_cleansing_context()
    fixture.widget.enable()
    _run_stage3_browser_update(fixture.widget)
    assert fixture.probe._outpost_baseline is not None
    return fixture


def _cause_record(probe: Any, output: str) -> str:
    records = _assert_stage3_output_budget(probe, output)
    causes = [line for line in records if "event=outpost_cause " in line]
    assert len(causes) == 1, records
    assert len(causes[0]) + 1 <= probe._MAX_OUTPOST_CAUSE_CHARACTERS
    assert records.index(causes[0]) == next(i for i, line in enumerate(records) if "event=outpost_delta " in line) + 1
    assert "event=final " in records[-1], records
    return causes[0]


@pytest.mark.parametrize(
    "mechanism", ("closing_first", "closing_second", "missing_owner", "nonliving", "conversion", "zero", "living")
)
def test_stage3_outpost_cause_real_widget_mechanisms_and_recovery(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mechanism: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    before = context.GetSnapshot()
    reader = fixture.cache.ShMem.GetNativeAccountSnapshotV3
    reads = 0

    def publication() -> Any:
        nonlocal reads
        reads += 1
        result = reader()
        if reads == (2 if mechanism == "closing_first" else 3):
            result = _copy_closing_publication(result)
            result.snapshot.cohorts[1].witnesses[0].revision += 1
        return result

    if mechanism.startswith("closing"):
        monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    elif mechanism == "missing_owner":
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    else:
        fixture.runtime.faults.update(
            {agent: "valid" if mechanism == "living" else mechanism for agent in range(4000, 4005)}
        )
    fixture.runtime.clock[0] += 0.26
    fixture.cache._refresh_cleansing_context()
    after = context.GetSnapshot()
    evidence = probe._capture_evidence(context)
    decision = evidence.production_evidence.decision
    assert evidence.production_evidence.decision_status == "EXACT" and decision is not None
    _run_stage3_browser_update(fixture.widget)
    output = capsys.readouterr().out
    cause = _cause_record(probe, output)
    assert "a=EXACT s=1" in cause and f"r={after.revision}" in cause, cause
    assert after.ready and (after.map_id, after.lifecycle_epoch) == (before.map_id, before.lifecycle_epoch)
    local = [member for member in after.members if member.evidence_source is module.EvidenceSource.LOCAL_HERO]
    remote = [
        member
        for member in after.members
        if member.evidence_source in (module.EvidenceSource.REMOTE_PLAYER, module.EvidenceSource.REMOTE_HERO)
    ]
    if mechanism == "living":
        assert "class=reason_only" in output and "p=5/0/0/0/0 o=N" in cause
        assert decision.baselines == (5, 5, 5, 0)
        assert all(member.role is not module.CleansingRole.UNKNOWN for member in local)
    else:
        assert (
            "class=mixed fields=composition.role_counts,LH1.role,LH1.candidate_role,LH1.reason,LH1.profession,LH1.anchors"
            in output
        )
        expected_profession = None if mechanism.startswith("closing") or mechanism == "missing_owner" else 0
        assert all(
            (member.role, member.candidate_role, member.primary_profession, member.anchor_skill_ids)
            == (module.CleansingRole.UNKNOWN, module.CleansingRole.UNKNOWN, expected_profession, ())
            for member in local
        )
        retained = 4 if mechanism.startswith("closing") else (5 if mechanism in ("missing_owner", "zero") else 0)
        assert decision.baselines == (5, 0, retained, 5 - retained)
        assert len(context._baselines) == retained + 1
        assert dict(after.composition.role_counts)[module.CleansingRole.UNKNOWN] == 7
        if mechanism.startswith("closing"):
            assert f"p=0/5/0/0/0 o=A c=I g=WREV/LH1/{1 if mechanism == 'closing_first' else 2} f=OK" in cause
            assert "x=0/0" in cause and all(member.role is module.CleansingRole.UNKNOWN for member in remote)
            assert context._remote_player_baselines and context._remote_hero_origins
            assert len(context._transition.retired) == 1
        elif mechanism == "missing_owner":
            assert "p=0/5/0/0/0 o=C c=OK" in cause and "x=1/1" in cause
        else:
            assert "p=0/0/5/0/0 o=N c=OK" in cause and "x=1/1" in cause
    assert after.composition.status is module.CompositionStatus.FALLBACK
    # Recovery uses the real production path; the finished observer has retired its state.
    assert context.GetStage3DecisionBinding() is None
    monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", reader)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    fixture.runtime.faults.update({agent: "absent" for agent in range(4000, 4005)})
    fixture.runtime.adapter._living_cache.clear()
    fixture.cache._refresh_cleansing_context()
    recovered = context.GetSnapshot()
    assert recovered.ready
    retired = context._transition.retired
    if mechanism == "living":
        # The direct living read replaced the historical witness origin. Fresh
        # outpost roles may be recognized, but that retired source cannot arm.
        assert len(retired) == 5 and context.BindStage3Outpost(recovered) is None
        assert all(member.role is not module.CleansingRole.UNKNOWN for member in recovered.members)
    mismatched = tuple(
        (member.identity.stable_key, member.role)
        for member in recovered.members
        if mechanism != "living"
        and (member.role is module.CleansingRole.UNKNOWN) != (member.identity.stable_key in retired)
    )
    assert not mismatched, (mechanism, mismatched)
    assert len(context._baselines) == (5 if mechanism.startswith("closing") else (1 if mechanism == "living" else 6))
    assert recovered.composition.status is module.CompositionStatus.FALLBACK
    fixture.widget.disable()


def test_stage3_outpost_cause_heartbeat_and_between_refresh_witness_replacement(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    initial = context.GetSnapshot()
    previous_sequence = 0
    for index in range(12):
        runtime.publication_now += 260
        runtime.publication_result = _remote_publication(
            runtime, module, include_local=True, omit_outpost_children=True
        )
        if index % 2:
            for cohort in runtime.publication_result.snapshot.cohorts:
                for witness in cohort.witnesses:
                    witness.revision = index + 10
                    witness.observed_at_tick64 = runtime.publication_now - 10
        fixture.runtime.clock[0] += 0.26
        fixture.cache._refresh_cleansing_context()
        evidence = probe._capture_evidence(context)
        decision = evidence.production_evidence.decision
        assert decision is not None and decision.sequence > previous_sequence
        previous_sequence = decision.sequence
        assert context.GetSnapshot() is initial  # Equal evidence really reuses the published object/revision.
        assert decision.closing == decision.final == "OK" and decision.failure == ("NONE", "NONE", 0)
        assert decision.baselines == (5, 5, 5, 0)
        _run_stage3_browser_update(fixture.widget)
        assert not probe._finished and probe._pending_outpost_cause is None
    fixture.widget.disable()


def test_stage3_outpost_cause_duplicate_revision_uses_exact_refresh_not_old_cause(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    reader = fixture.cache.ShMem.GetNativeAccountSnapshotV3
    reads, mode = 0, "revision"

    def publication() -> Any:
        nonlocal reads
        reads += 1
        result = reader()
        if reads == 2:
            result = _copy_closing_publication(result)
            cohort = result.snapshot.cohorts[1]
            if mode == "revision":
                cohort.witnesses[0].revision += 1
            else:
                cohort.instance_epoch += 1
        return result

    monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    fixture.cache._refresh_cleansing_context()
    first = probe._capture_evidence(context)
    first_decision = first.production_evidence.decision
    assert first_decision.failure == ("WITNESS_REVISION", "LH1", 1)
    reads, mode = 0, "epoch"
    fixture.cache._refresh_cleansing_context()
    second = probe._capture_evidence(context)
    second_decision = second.production_evidence.decision
    assert first.snapshot is not second.snapshot and first_decision.revision < second_decision.revision
    assert second_decision.sequence == first_decision.sequence + 1
    assert second_decision.failure == ("INSTANCE_EPOCH", "LOCAL_OWNER", 1)
    assert "g=WREV/LH1/1" in probe._outpost_cause_details(first)  # Historical evidence stays immutable.
    fixture.runtime.clock[0] += 0.26
    _run_stage3_browser_update(fixture.widget)
    cause = _cause_record(probe, capsys.readouterr().out)
    # Process the earlier terminal contradiction before later evidence. Its
    # immutable companion must not be replaced by a newer diagnostic cause.
    assert "a=EXACT s=1" in cause and "g=WREV/LH1/1" in cause and "EPOCH" not in cause
    fixture.widget.disable()


@pytest.mark.parametrize(
    "association", ("missing", "stale_sequence", "stale_session", "baseline_mutated", "invalidated", "in_progress")
)
def test_stage3_outpost_cause_unavailable_association_is_honest(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    association: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    fixture.cache._refresh_cleansing_context()
    binding = context.GetStage3DecisionBinding()
    assert binding is not None
    if association == "missing":
        context._stage3_decision_result = None
    elif association == "stale_sequence":
        context._stage3_decision_sequence += 1
    elif association == "stale_session":
        context._stage3_decision_session = object()
    elif association == "baseline_mutated":
        context._baselines.pop(next(key for key in context._baselines if key[0] is module.MemberKind.HERO))
    elif association == "invalidated":
        context.InvalidatePublishedSnapshot()
    else:
        context._stage3_decision_active = module._Stage3DecisionCapture(object(), 999)
    evidence = probe._capture_evidence(context)
    assert evidence.production_evidence.decision is None
    status = "UNAVAILABLE" if association in ("missing", "invalidated", "stale_session") else "AMBIGUOUS"
    assert evidence.production_evidence.decision_status == status
    assert probe._outpost_cause_details(evidence) == f"a={status}"
    fixture.widget.disable()


def test_stage3_outpost_cause_first_closing_failure_survives_final_runtime_failure(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context = fixture.cache.CleansingContext
    reader = fixture.cache.ShMem.GetNativeAccountSnapshotV3
    closing = module._read_closing_state
    reads, boundaries = 0, 0

    def publication() -> Any:
        nonlocal reads
        reads += 1
        value = reader()
        if reads == 2:
            value = _copy_closing_publication(value)
            value.snapshot.cohorts[1].witnesses[0].revision += 1
        return value

    def runtime_boundary() -> Any:
        nonlocal boundaries
        boundaries += 1
        if boundaries == 2:
            runtime.character_name = "PRIVATE_CHANGED_CHARACTER"
        return closing()

    monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    monkeypatch.setattr(module, "_read_closing_state", runtime_boundary)
    fixture.cache._refresh_cleansing_context()
    decision = context.GetStage3DecisionBinding().decision
    assert decision.failure == ("WITNESS_REVISION", "LH1", 1)
    assert decision.closing == "CLOSING_INCOHERENT" and decision.final == "RUNTIME_REJECTED"
    assert not context.GetSnapshot().ready
    fixture.widget.disable()


@pytest.mark.parametrize(
    "fault",
    (
        "absent",
        "valid",
        "nonliving",
        "conversion",
        "zero",
        "read",
        "missing_owner",
        "witness_missing",
        "closing_revision",
    ),
)
def test_stage3_outpost_cause_capture_preserves_exact_production_results_and_read_order(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    harness.faults.update({agent: "absent" for agent in range(4000, 4005)})
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    if fault == "missing_owner":
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    elif fault == "witness_missing":
        runtime.publication_result.snapshot.cohorts[1].witnesses = ()
    elif fault != "closing_revision":
        harness.faults[4000] = fault
    initial = copy.deepcopy(runtime.__dict__)
    outcomes = []
    reader = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem.GetNativeAccountSnapshotV3
    reads = 0

    def publication() -> Any:
        nonlocal reads
        reads += 1
        value = reader()
        if fault == "closing_revision" and reads == 2:
            value = _copy_closing_publication(value)
            value.snapshot.cohorts[1].witnesses[0].revision += 1
        return value

    monkeypatch.setattr(sys.modules["Py4GWCoreLib"].GLOBAL_CACHE.ShMem, "GetNativeAccountSnapshotV3", publication)
    for enabled in (False, True):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        harness.adapter._living_cache.clear()
        harness.calls.clear()
        harness.trace.clear()
        reads = 0
        context = module.CleansingContext()
        if enabled:
            context.SetStage3DecisionSession(object())
        snapshot = context.Refresh()
        outcomes.append(
            (
                snapshot,
                dict(context._baselines),
                dict(context._remote_player_baselines),
                dict(context._remote_hero_origins),
                dict(harness.calls),
                tuple(harness.trace),
                reads,
                tuple(runtime.hero_skillbar_positions),
                tuple(runtime.hero_agent_positions),
            )
        )
    assert outcomes[0] == outcomes[1], (fault, outcomes)


@pytest.mark.parametrize("event", ("outpost_delta", "outpost_cause", "final"))
@pytest.mark.parametrize("delivery", ("exception", "refused"))
def test_stage3_outpost_cause_mandatory_delivery_is_frozen_and_retried(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    event: str,
    delivery: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    fixture.runtime.clock[0] += 0.26
    fixture.cache._refresh_cleansing_context()
    original_emit = probe._emit
    interrupted = False

    def emit(name: str, details: str = "", **kwargs: Any) -> bool:
        nonlocal interrupted
        if name == event and not interrupted:
            interrupted = True
            if delivery == "exception":
                raise RuntimeError("PRIVATE delivery failure")
            return False
        return bool(original_emit(name, details, **kwargs))

    monkeypatch.setattr(probe, "_emit", emit)
    _run_stage3_browser_update(fixture.widget)
    assert interrupted and not probe._finished and context.GetStage3DecisionBinding() is None
    # A later recovery must not replace the already-associated pending record.
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    recorder = probe.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    replacement = type(recorder)()
    fixture.cache._refresh_cleansing_context()
    replacement_id = replacement.begin(context, recorder.capture_snapshot(context, context.GetSnapshot()))
    assert replacement_id is not None
    fixture.cache._refresh_cleansing_context()
    replacement_binding = context.GetStage3DecisionBinding()
    fixture.runtime.clock[0] += 0.5
    _run_stage3_browser_update(fixture.widget)
    assert not probe._finished
    fixture.runtime.clock[0] += 0.6
    _run_stage3_browser_update(fixture.widget)
    output = capsys.readouterr().out
    cause = _cause_record(probe, output)
    assert "o=C" in cause and "PRIVATE" not in output
    assert output.count("event=outpost_delta ") == output.count("event=final ") == 1
    fixture.widget.disable()
    assert context.GetStage3DecisionBinding() is replacement_binding
    assert replacement.capture_observation(context).decision_status == "EXACT"
    replacement.end(replacement_id)


@pytest.mark.parametrize(
    "defect",
    (
        "gate",
        "scope",
        "opening",
        "closing",
        "final",
        "counts",
        "shape",
        "counter",
        "pass",
        "remote",
        "counter_bool",
        "counter_float",
        "large_shape",
        "failure_shape",
    ),
)
def test_stage3_outpost_cause_privacy_allowlist_and_malformed_capture(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    fixture.cache._refresh_cleansing_context()
    evidence = probe._capture_evidence(context)
    decision = evidence.production_evidence.decision
    private = "PRIVATE_email@example.invalid\nUUID_HWND_AgentID_HeroID"
    changes = {
        "gate": {"failure": (private, "NONE", 1)},
        "scope": {"failure": ("NONE", private, 1)},
        "opening": {"opening": private},
        "closing": {"closing": private},
        "final": {"final": private},
        "counts": {"paths": (private,) * 5},
        "shape": {"baselines": (1,)},
        "counter": {"sequence": 1 << 1000},
        "pass": {"failure": ("NONE", "NONE", private)},
        "remote": {"remote": (7, 7)},
        "counter_bool": {"sequence": True},
        "counter_float": {"sequence": 1.5},
        "large_shape": {"paths": (7,) * 10000},
        "failure_shape": {"failure": ("NONE",)},
    }[defect]
    bad = replace(decision, **changes)
    current = evidence._replace(production_evidence=replace(evidence.production_evidence, decision=bad))
    details = probe._outpost_cause_details(current)
    assert "PRIVATE" not in details and "\n" not in details and "example.invalid" not in details
    assert len(probe._record("outpost_cause", details)) + 1 <= probe._MAX_OUTPOST_CAUSE_CHARACTERS
    fixture.widget.disable()


def test_stage3_outpost_cause_disable_reenable_retires_session_and_reentrant_refresh_is_ambiguous(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    fixture.cache._refresh_cleansing_context()
    old = context.GetStage3DecisionBinding()
    fixture.widget.disable()

    assert context.GetStage3DecisionBinding() is None and context._stage3_decision_session is None
    fixture.widget.enable()
    _run_stage3_browser_update(fixture.widget)
    fixture.cache._refresh_cleansing_context()
    new = context.GetStage3DecisionBinding()
    assert old.decision.session is not new.decision.session and new.decision.sequence > old.decision.sequence
    assert context.ResolveStage3Decision(old, context.GetSnapshot(), new.local, new.remote) == (None, "AMBIGUOUS")
    original = context._record_refresh_diagnostic
    nested = False

    def record(snapshot: Any, outcome: str, error: Any = None) -> None:
        nonlocal nested
        if not nested:
            nested = True
            context.Refresh()
        original(snapshot, outcome, error)

    monkeypatch.setattr(context, "_record_refresh_diagnostic", record)
    fixture.cache._refresh_cleansing_context()
    evidence = probe._capture_evidence(context)
    assert (
        evidence.production_evidence.decision_status == "UNAVAILABLE" and evidence.production_evidence.decision is None
    )
    assert context._stage3_evidence[-1].verification is None
    fixture.widget.disable()


@pytest.mark.parametrize(
    "mutation,gate,scope,closing_code",
    (
        ("revision", "WITNESS_REVISION", "LH1", "CLOSING_INCOHERENT"),
        ("time", "WITNESS_TIME", "LH1", "CLOSING_INCOHERENT"),
        ("build", "WITNESS_BUILD", "LH1", "CLOSING_INCOHERENT"),
        ("missing_witness", "WITNESS_MISSING", "LH1", "UNAVAILABLE"),
        ("incarnation", "INCARNATION", "LOCAL_OWNER", "CLOSING_INCOHERENT"),
        ("recovery", "RECOVERY", "REMOTE_OWNER", "CLOSING_INCOHERENT"),
        ("epoch", "INSTANCE_EPOCH", "LOCAL_OWNER", "CLOSING_INCOHERENT"),
        ("email", "OWNER_EMAIL", "LOCAL_OWNER", "CLOSING_INCOHERENT"),
        ("lease", "LEASE", "LOCAL_OWNER", "UNAVAILABLE"),
        ("capture_time", "CAPTURE_TIME", "SHARED", "CLOSING_INCOHERENT"),
        ("hero_endpoint", "ENDPOINT_CONTRADICTION", "LH1", "UNAVAILABLE"),
        ("busy", "PUBLICATION", "SHARED", "PUBLICATION_REJECTED"),
        ("read", "CLOSING_READ", "UNKNOWN", "READ_FAILED_CLOSING"),
    ),
)
def test_stage3_outpost_cause_actual_closing_first_gate_categories(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    gate: str,
    scope: str,
    closing_code: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context = fixture.cache.CleansingContext
    reader = fixture.cache.ShMem.GetNativeAccountSnapshotV3
    reads = 0

    def publication() -> Any:
        nonlocal reads
        reads += 1
        result = reader()
        if reads != 2:
            return result
        if mutation == "read":
            raise ValueError("PRIVATE Native failure")
        if mutation == "busy":
            return types.SimpleNamespace(status="busy", snapshot=None)
        value = _copy_closing_publication(result)
        cohort = value.snapshot.cohorts[1]
        witness = cohort.witnesses[0]
        if mutation == "revision":
            witness.revision += 1
        elif mutation == "time":
            witness.observed_at_tick64 += 1
        elif mutation == "build":
            witness.skills = (*witness.skills[:-1], witness.skills[-1] + 10)
        elif mutation == "missing_witness":
            cohort.witnesses = cohort.witnesses[1:]
        elif mutation == "incarnation":
            cohort.incarnation = bytes((99,)) + bytes(15)
        elif mutation == "recovery":
            value.snapshot.recovery_epoch += 1
        elif mutation == "epoch":
            cohort.instance_epoch += 1
        elif mutation == "email":
            cohort.owner.GetAccountData().AccountEmail = "PRIVATE_other@example.invalid"
        elif mutation == "lease":
            cohort.published_tick = (runtime.publication_now - 10000) & 0xFFFFFFFF
            cohort.owner.GetAccountData().LastUpdated = cohort.published_tick
        elif mutation == "capture_time":
            value.snapshot.captured_at_tick64 = runtime.publication_now + 100
        elif mutation == "hero_endpoint":
            fixture.runtime.faults[4000] = "valid"
            runtime.professions[4000] = int(module.Profession.Mesmer)
        return value

    monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    fixture.cache._refresh_cleansing_context()
    decision = context.GetStage3DecisionBinding().decision
    assert decision.failure == (gate, scope, 1), (mutation, decision)
    assert decision.closing == closing_code and decision.final == "OK", (mutation, decision)
    fixture.widget.disable()


@pytest.mark.parametrize("pressure", ("characters", "lines"))
def test_stage3_outpost_cause_exact_companion_survives_optional_pressure(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    pressure: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    probe = fixture.probe
    if pressure == "lines":
        monkeypatch.setattr(probe, "_MAX_OUTPUT_LINES", 8)
    assert not probe._emit("padding", "optional details must not borrow mandatory cause capacity")
    runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    fixture.runtime.clock[0] += 0.26
    fixture.cache._refresh_cleansing_context()
    _run_stage3_browser_update(fixture.widget)
    output = capsys.readouterr().out
    cause = _cause_record(probe, output)
    assert "a=EXACT" in cause and "o=C" in cause and probe._finished
    fixture.widget.disable()


@pytest.mark.parametrize("error_type", (MemoryError, ValueError))
@pytest.mark.parametrize("failure_site", ("GetStage3DecisionBinding", "ResolveStage3Decision"))
def test_stage3_outpost_cause_association_failure_does_not_change_probe_rejection(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_site: str,
    error_type: type[Exception],
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    fixture.runtime.clock[0] += 0.26
    fixture.cache._refresh_cleansing_context()

    def fail(*_args: Any) -> Any:
        raise error_type("PRIVATE observer failure")

    monkeypatch.setattr(fixture.cache.CleansingContext, failure_site, fail)
    _run_stage3_browser_update(fixture.widget)
    cause = _cause_record(fixture.probe, capsys.readouterr().out)
    assert "a=EXACT" in cause
    assert fixture.probe._terminal_outcome.reason == "outpost_changed_before_loading"
    fixture.widget.disable()


def test_stage3_outpost_cause_widest_record_and_expired_session(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    fixture.cache._refresh_cleansing_context()
    evidence = probe._capture_evidence(context)
    maximum = probe._MAX_DISPLAY_COUNTER
    snapshot = replace(evidence.snapshot, revision=maximum)
    decision = replace(
        evidence.production_evidence.decision,
        sequence=maximum,
        revision=maximum,
        paths=(7,) * 5,
        baselines=(7,) * 4,
        remote=(1, 1),
        opening="PUBLISHER_CONFLICT",
        closing="CLOSING_INCOHERENT",
        failure=("WITNESS_QUALIFICATION", "RH7", 2),
        final="CONTROLLED_IDENTITY",
    )
    production = replace(evidence.production_evidence, snapshot=snapshot, decision=decision)
    widest = evidence._replace(snapshot=snapshot, production_evidence=production)
    details = probe._outpost_cause_details(widest)
    assert details.startswith("a=EXACT") and details.count(probe._counter_text(maximum)) == 2
    assert len(probe._record("outpost_cause", details)) + 1 <= probe._MAX_OUTPOST_CAUSE_CHARACTERS
    mismatched = widest._replace(snapshot=replace(snapshot))
    assert probe._outpost_cause_details(mismatched) == "a=AMBIGUOUS"
    fixture.runtime.clock[0] += 2.1
    recorder = sys.modules["Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics"].STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    assert recorder.active_attempt_id(context) == probe._attempt_id
    fixture.runtime.clock[0] = probe._started_at + probe._MAX_RUNTIME_SECONDS
    assert recorder.active_attempt_id(context) is None and context.GetStage3DecisionBinding() is None
    current = probe._capture_evidence(context)
    assert probe._outpost_cause_details(current) == "a=UNAVAILABLE"
    fixture.widget.disable()


@pytest.mark.parametrize("blocker", ("selection", "allocation", "ownership"))
def test_stage3_review_original_blockers(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    blocker: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    diagnostics = probe.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    if blocker == "selection":
        fixture.cache._refresh_cleansing_context()
        selected = context.GetSnapshot()
        fixture.cache._refresh_cleansing_context()
        assert selected is context.GetSnapshot()
        evidence = diagnostics.capture_snapshot(context, selected)
        assert evidence.decision_status != "EXACT", "A bare snapshot cannot prove which Refresh selected it"
    elif blocker == "allocation":

        def fail(*args: Any, **kwargs: Any) -> Any:
            raise MemoryError("diagnostic allocation")

        monkeypatch.setattr(module, "_LocalWitnessObservation", fail)
        fixture.cache._refresh_cleansing_context()
        snapshot = context.GetSnapshot()
        assert sum(member.role is not module.CleansingRole.UNKNOWN for member in snapshot.members) == 8
        assert len(context._baselines) == 6 and len(context._remote_player_baselines) == 1
    else:
        replacement = type(diagnostics)()
        evidence = diagnostics.capture_snapshot(context, context.GetSnapshot())
        replacement.begin(context, evidence)
        fixture.cache._refresh_cleansing_context()
        assert diagnostics.capture_snapshot(context, context.GetSnapshot()).decision_status != "EXACT"
        binding = context.GetStage3DecisionBinding()
        diagnostics.end(probe._attempt_id)
        assert context.GetStage3DecisionBinding() is binding, "Old cleanup retired the replacement session"
    fixture.widget.disable()


@pytest.mark.parametrize(
    "interleave", ("selection", "resolution", "after_capture", "attempt_before_token", "attempt_during_token")
)
def test_stage3_review_same_snapshot_different_refresh_widget_interleaving(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    interleave: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    reader = fixture.cache.ShMem.GetNativeAccountSnapshotV3
    reads, epoch = 0, False

    def publication() -> Any:
        nonlocal reads
        reads += 1
        result = reader()
        if reads == 2:
            result = _copy_closing_publication(result)
            if epoch:
                result.snapshot.cohorts[1].instance_epoch += 1
            else:
                result.snapshot.cohorts[1].witnesses[0].revision += 1
        return result

    monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    fixture.cache._refresh_cleansing_context()
    selected = context.GetSnapshot()
    first = probe._capture_evidence(context)
    assert first.production_evidence.decision.failure == ("WITNESS_REVISION", "LH1", 1)
    recorder = probe.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    old_id = probe._attempt_id

    def intervene() -> None:
        nonlocal reads, epoch
        reads, epoch = 0, True
        fixture.cache._refresh_cleansing_context()
        assert context.GetSnapshot() is not selected
        binding = context.GetStage3DecisionBinding()
        if interleave.startswith("attempt_"):
            assert binding is None
        else:
            assert binding.decision.failure == ("INSTANCE_EPOCH", "LOCAL_OWNER", 1)

    if interleave == "selection":
        get_snapshot = context.GetSnapshot

        def select_then_refresh() -> Any:
            snapshot = get_snapshot()
            monkeypatch.setattr(context, "GetSnapshot", get_snapshot)
            intervene()
            return snapshot

        monkeypatch.setattr(context, "GetSnapshot", select_then_refresh)
    elif interleave == "resolution":
        resolve = context.ResolveStage3Decision

        def refresh_then_resolve(*args: Any) -> Any:
            monkeypatch.setattr(context, "ResolveStage3Decision", resolve)
            intervene()
            return resolve(*args)

        monkeypatch.setattr(context, "ResolveStage3Decision", refresh_then_resolve)
    elif interleave.startswith("attempt_"):
        target = recorder if interleave == "attempt_before_token" else context
        method = "active_attempt_id" if interleave == "attempt_before_token" else "GetStage3DecisionBinding"
        original = getattr(target, method)

        def replace_attempt(*args: Any) -> Any:
            monkeypatch.setattr(target, method, original)
            recorder.begin(context, recorder.capture_snapshot(context, selected))
            intervene()
            return old_id if interleave == "attempt_before_token" else context.GetStage3DecisionBinding()

        monkeypatch.setattr(target, method, replace_attempt)
    else:
        intervene()
        assert "a=EXACT s=1" in probe._outpost_cause_details(first)
        assert "g=WREV/LH1/1" in probe._outpost_cause_details(first)
    if interleave != "after_capture":
        # Exercise the legacy selection path directly. Ordered consumption uses
        # already-frozen owner values and must never borrow its later token.
        captured = recorder.capture_observation(context, old_id)
        assert captured.decision_status != "EXACT"
    fixture.runtime.clock[0] += 0.26
    _run_stage3_browser_update(fixture.widget)
    output = capsys.readouterr().out
    if interleave.startswith("attempt_"):
        assert "event=outpost_cause" not in output
        assert probe._terminal_outcome.reason == "validation_attempt_expired_or_replaced"
        assert recorder._active is None
    else:
        cause = _cause_record(probe, output)
        assert "a=EXACT s=1" in cause and "g=WREV/LH1/1" in cause and "EPOCH" not in cause
        assert probe._terminal_outcome.reason == "outpost_changed_before_loading"
    fixture.widget.disable()
    if interleave.startswith("attempt_"):
        assert context.GetStage3DecisionBinding() is None
        assert recorder.active_attempt_id(context) is None


@pytest.mark.parametrize("error_type", (MemoryError, ValueError))
@pytest.mark.parametrize("genuine_failure", (False, True))
@pytest.mark.parametrize(
    "site",
    (
        "capture",
        "opening_allocation",
        "closing_allocation",
        "opening_classification",
        "closing_classification",
        "recording",
        "decision_publication",
        "binding_publication",
        "publication_call",
    ),
)
def test_stage3_review_diagnostic_fault_recognition_and_read_order_parity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
    genuine_failure: bool,
    site: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    harness.faults.update({agent: "absent" for agent in range(4000, 4005)})
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    initial = copy.deepcopy(runtime.__dict__)
    cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    reader = cache.ShMem.GetNativeAccountSnapshotV3
    reads = 0
    injected = 0

    def fail(*args: Any, **kwargs: Any) -> Any:
        nonlocal injected
        injected += 1
        raise error_type("PRIVATE diagnostic fault")

    class FaultMap(dict[str, Any]):
        def get(self, *args: Any, **kwargs: Any) -> Any:
            return fail()

        def __setitem__(self, key: str, value: Any) -> None:
            if site == "recording":
                fail()
            super().__setitem__(key, value)

    def publication() -> Any:
        nonlocal reads
        reads += 1
        result = reader()
        if genuine_failure and reads == 2:
            result = _copy_closing_publication(result)
            result.snapshot.cohorts[1].witnesses[0].revision += 1
        return result

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    outcomes: list[tuple[Any, ...]] = []
    for enabled in (False, True):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        harness.adapter._living_cache.clear()
        harness.calls.clear()
        harness.trace.clear()
        reads = 0
        context = module.CleansingContext()
        with monkeypatch.context() as faults:
            if enabled:
                context.SetStage3DecisionSession(object())
                if site == "capture":
                    faults.setattr(module, "_Stage3DecisionCapture", fail)
                elif site in ("opening_allocation", "closing_allocation", "opening_classification", "recording"):
                    observation = module._LocalWitnessObservation

                    def allocate(*args: Any, **kwargs: Any) -> Any:
                        if site == "opening_allocation" and "decision" not in kwargs:
                            return fail()
                        if site == "closing_allocation" and "decision" in kwargs:
                            return fail()
                        result = observation(*args, **kwargs)
                        if site in ("opening_classification", "recording"):
                            result.values = FaultMap()
                        return result

                    faults.setattr(module, "_LocalWitnessObservation", allocate)
                elif site == "closing_classification":
                    faults.setattr(module, "_stage3_hero_scope", fail)
                elif site == "decision_publication":
                    faults.setattr(module, "Stage3RefreshDecision", fail)
                elif site == "binding_publication":
                    faults.setattr(module, "Stage3DecisionBinding", fail)
                else:
                    faults.setattr(context, "_stage3_complete_decision", fail)
            snapshot = context.Refresh()
            outcomes.append(
                (
                    snapshot,
                    dict(context._baselines),
                    dict(context._remote_player_baselines),
                    dict(context._remote_hero_origins),
                    dict(harness.calls),
                    tuple(harness.trace),
                    reads,
                    tuple(runtime.hero_skillbar_positions),
                    tuple(runtime.hero_agent_positions),
                )
            )
            if enabled:
                assert context.GetStage3DecisionBinding() is None, site
        # The next genuine Refresh recovers after a transient diagnostic or production fault.
        context.Refresh()
        recovered = context.GetSnapshot()
        assert recovered.ready and sum(m.role is not module.CleansingRole.UNKNOWN for m in recovered.members) == 8
        assert len(context._baselines) == 6 and len(context._remote_player_baselines) == 1
    assert injected > 0, site
    assert outcomes[0] == outcomes[1], (site, error_type, genuine_failure, outcomes)
    expected = 1 if genuine_failure else 8
    assert sum(m.role is not module.CleansingRole.UNKNOWN for m in outcomes[1][0].members) == expected


@pytest.mark.parametrize("retirement", ("capture", "end", "lease", "heartbeat", "events", "refresh_events", "reenable"))
def test_stage3_review_replacement_session_has_exclusive_ownership(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    retirement: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    old = probe.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    old_id = probe._attempt_id
    replacement = type(old)()
    replacement_id = replacement.begin(context, old.capture_snapshot(context, context.GetSnapshot()))
    fixture.cache._refresh_cleansing_context()
    selected = replacement.capture_observation(context)
    assert selected.decision_status == "EXACT"
    binding = context.GetStage3DecisionBinding()
    if retirement in ("end", "reenable"):
        old.end(old_id)
    elif retirement == "lease":
        fixture.runtime.clock[0] += 2.1
        # Renew only the replacement, leaving the old recorder expired.
        replacement._active.lease_expires_at_ns += 3_000_000_000
        assert old.active_attempt_id(context) is None
    elif retirement == "heartbeat":
        assert not old.heartbeat(old_id, context)
    elif retirement == "events":
        assert not old.read_events(old_id, 0).active
    elif retirement == "refresh_events":
        assert not old.read_refresh_events(old_id, 0).active
    else:
        assert old.capture_observation(context).decision_status != "EXACT"
    assert old.capture_observation(context).decision_status != "EXACT"
    assert context.GetStage3DecisionBinding() is binding
    assert replacement.capture_observation(context).decision_status == "EXACT"
    if retirement == "reenable":
        newer_id = old.begin(context, selected)
        assert newer_id is not None
        fixture.cache._refresh_cleansing_context()
        newer = context.GetStage3DecisionBinding()
        replacement.end(replacement_id)
        assert context.GetStage3DecisionBinding() is newer
        assert old.capture_observation(context).decision_status == "EXACT"
    else:
        replacement.end(replacement_id)
        assert context.GetStage3DecisionBinding() is None
    fixture.widget.disable()


@pytest.mark.parametrize("error_type", (MemoryError, ValueError))
@pytest.mark.parametrize("site", ("session_lock", "begin", "retire"))
def test_stage3_review_session_api_faults_preserve_recognition_and_ownership(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
    site: str,
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    old = probe.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    fixture.cache._refresh_cleansing_context()
    replacement = type(old)()

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise error_type("PRIVATE session failure")

    if site == "session_lock":
        with monkeypatch.context() as fault:
            fault.setattr(module, "RLock", fail)
            isolated = module.CleansingContext()
        snapshot = isolated.Refresh()
        assert snapshot == context.GetSnapshot()
        assert len(isolated._baselines) == 6 and len(isolated._remote_player_baselines) == 1
        assert replacement.begin(isolated, old.capture_snapshot(isolated, snapshot)) is None
    elif site == "begin":
        binding = context.GetStage3DecisionBinding()
        monkeypatch.setattr(context, "SetStage3DecisionSession", fail)
        assert replacement.begin(context, old.capture_observation(context)) is None
        assert context.GetStage3DecisionBinding() is binding
        assert old.capture_observation(context).decision_status == "EXACT"
    else:
        replacement_id = replacement.begin(context, old.capture_observation(context))
        fixture.cache._refresh_cleansing_context()
        binding = context.GetStage3DecisionBinding()
        with monkeypatch.context() as fault:
            fault.setattr(context, "RetireStage3DecisionSession", fail)
            old.end(probe._attempt_id)
        assert context.GetStage3DecisionBinding() is binding
        assert replacement.capture_observation(context).decision_status == "EXACT"
        replacement.end(replacement_id)
    assert context.GetSnapshot().ready
    assert all(member.role is not module.CleansingRole.UNKNOWN for member in context.GetSnapshot().members)
    fixture.widget.disable()


@pytest.mark.parametrize("error_type", (MemoryError, ValueError))
def test_stage3_review_failed_attempt_allocation_retires_only_its_session(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    recorder = probe.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    evidence = recorder.capture_snapshot(context, context.GetSnapshot())
    diagnostics_module = sys.modules["Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics"]

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise error_type("PRIVATE attempt allocation failure")

    with monkeypatch.context() as fault:
        fault.setattr(diagnostics_module, "_ProbeAttempt", fail)
        assert recorder.begin(context, evidence) is None
    assert recorder.active_attempt_id(context) is None
    assert context._stage3_decision_session is None and context.GetStage3DecisionBinding() is None
    fixture.cache._refresh_cleansing_context()
    assert context.GetSnapshot().ready and all(
        member.role is not module.CleansingRole.UNKNOWN for member in context.GetSnapshot().members
    )
    new_id = recorder.begin(context, evidence)
    fixture.cache._refresh_cleansing_context()
    assert new_id != probe._attempt_id and recorder.capture_observation(context, new_id).decision_status == "EXACT"
    assert recorder.capture_observation(context, probe._attempt_id).decision_status != "EXACT"
    fixture.widget.disable()
    assert recorder.capture_observation(context, new_id).decision_status == "EXACT"
    recorder.end(new_id)
def test_stage3_unsupported_direct_hero_counter_write_preserves_refresh(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    harness.faults.update({agent: "absent" for agent in range(4001, 4005)})
    supported_bar = runtime.bars[4000]
    runtime.bars[4000] = tuple(range(9000, 9008))
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    initial = copy.deepcopy(runtime.__dict__)
    cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    reader = cache.ShMem.GetNativeAccountSnapshotV3
    reads = 0
    injected = 0
    capture_type = module._Stage3DecisionCapture

    class FaultCounters(list[int]):
        def __setitem__(self, index: Any, value: Any) -> None:
            nonlocal injected
            if index == 4:
                injected += 1
                raise MemoryError("PRIVATE unsupported-build diagnostic counter fault")
            super().__setitem__(index, value)

    def allocate(*args: Any, **kwargs: Any) -> Any:
        capture = capture_type(*args, **kwargs)
        capture.paths = FaultCounters(capture.paths)
        return capture

    def publication() -> Any:
        nonlocal reads
        reads += 1
        return reader()

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    outcomes: list[tuple[Any, ...]] = []
    for mode in ("disabled", "enabled", "fault"):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        harness.adapter._living_cache.clear()
        harness.calls.clear()
        harness.trace.clear()
        reads = 0
        context = module.CleansingContext()
        with monkeypatch.context() as fault:
            if mode != "disabled":
                context.SetStage3DecisionSession(object())
            if mode == "fault":
                fault.setattr(module, "_Stage3DecisionCapture", allocate)
            snapshot = context.Refresh()
        observed = (
            snapshot.ready,
            len(snapshot.members),
            sum(m.role is not module.CleansingRole.UNKNOWN for m in snapshot.members),
            len(context._baselines),
            len(context._remote_player_baselines),
        )
        assert observed == (True, 8, 7, 5, 1), (mode, observed, tuple(m.identity for m in snapshot.members))
        assert len({m.identity for m in snapshot.members}) == 8
        unsupported = next(m for m in snapshot.members if m.identity.agent_id == 4000)
        assert unsupported.role is module.CleansingRole.UNKNOWN
        assert unsupported.identity.stable_key not in context._baselines
        assert snapshot.composition.status is module.CompositionStatus.FALLBACK
        outcomes.append(
            (
                snapshot,
                dict(context._baselines),
                dict(context._remote_player_baselines),
                dict(context._remote_hero_origins),
                dict(harness.calls),
                tuple(harness.trace),
                reads,
                tuple(runtime.hero_skillbar_positions),
                tuple(runtime.hero_agent_positions),
            )
        )
        binding = context.GetStage3DecisionBinding()
        if mode == "enabled":
            assert binding is not None and binding.decision.paths == (1, 4, 0, 0, 1)
        elif mode == "fault":
            assert injected == 1 and binding is None
            assert context.ResolveStage3Decision(
                binding, snapshot, tuple(context._baselines.items()), tuple(context._remote_player_baselines.items())
            ) == (None, "UNAVAILABLE")
        runtime.bars[4000] = supported_bar
        recovered = context.Refresh()
        assert recovered.ready and len(recovered.members) == 8
        assert all(m.role is not module.CleansingRole.UNKNOWN for m in recovered.members)
        assert len(context._baselines) == 6 and len(context._remote_player_baselines) == 1
        if mode != "disabled":
            assert context.GetStage3DecisionBinding() is not None
    assert outcomes[0] == outcomes[1] == outcomes[2], outcomes


@pytest.mark.parametrize("error_type", (MemoryError, ValueError))
@pytest.mark.parametrize(
    "mutation",
    (
        "direct",
        "witness",
        "blocked",
        "identity",
        "read",
        "previous",
        "opening",
        "closing_pass",
        "closing",
        "failure",
        "final",
    ),
)
def test_stage3_capture_mutation_faults_preserve_production(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    harness.faults.update({agent: "absent" for agent in range(4000, 4005)})
    if mutation == "direct":
        harness.faults[4000] = "valid"
    elif mutation == "blocked":
        harness.faults[4000] = "nonliving"
    elif mutation == "identity":
        runtime.heroes[0].hero_id = 0
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    initial = copy.deepcopy(runtime.__dict__)
    cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    reader = cache.ShMem.GetNativeAccountSnapshotV3
    native_skillbar = sys.modules["PySkillbar"].Skillbar
    read_bar = native_skillbar.GetHeroSkillbar
    capture_type = module._Stage3DecisionCapture
    path_index = {"direct": 0, "witness": 1, "blocked": 2, "identity": 3, "read": 3}.get(mutation)
    reads = 0
    injected = 0

    class FaultCounters(list[int]):
        def __setitem__(self, index: Any, value: Any) -> None:
            nonlocal injected
            if index == path_index:
                injected += 1
                raise error_type("PRIVATE diagnostic path counter")
            super().__setitem__(index, value)

    class FaultCapture(capture_type):
        def __setattr__(self, name: str, value: Any) -> None:
            nonlocal injected
            if name == mutation and getattr(self, "armed", False):
                injected += 1
                raise error_type("PRIVATE diagnostic field mutation")
            object.__setattr__(self, name, value)

    def allocate(*args: Any, **kwargs: Any) -> Any:
        capture = FaultCapture(*args, **kwargs)
        capture.paths = FaultCounters(capture.paths)
        capture.armed = True
        return capture

    def publication() -> Any:
        nonlocal reads
        reads += 1
        result = reader()
        if mutation == "failure" and reads == 2:
            result = _copy_closing_publication(result)
            result.snapshot.cohorts[1].witnesses[0].revision += 1
        return result

    def skillbar(self: Any, position: int) -> Any:
        harness.trace.append(f"hero_bar:{position}")
        if mutation == "read" and position == 1:
            raise ValueError("genuine game-memory skillbar read failure")
        return read_bar(self, position)

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    monkeypatch.setattr(native_skillbar, "GetHeroSkillbar", skillbar)
    outcomes: list[tuple[Any, ...]] = []
    for enabled in (False, True):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        harness.adapter._living_cache.clear()
        harness.calls.clear()
        harness.trace.clear()
        reads = 0
        context = module.CleansingContext()
        with monkeypatch.context() as fault:
            if enabled:
                context.SetStage3DecisionSession(object())
                fault.setattr(module, "_Stage3DecisionCapture", allocate)
            snapshot = context.Refresh()
        assert len(snapshot.members) == len({m.identity for m in snapshot.members}) == 8, (mutation, snapshot)
        assert snapshot.composition.status is module.CompositionStatus.FALLBACK
        outcomes.append(
            (
                snapshot,
                dict(context._baselines),
                dict(context._remote_player_baselines),
                dict(context._remote_hero_origins),
                dict(harness.calls),
                tuple(harness.trace),
                reads,
                tuple(runtime.hero_skillbar_positions),
                tuple(runtime.hero_agent_positions),
            )
        )
        if enabled:
            assert injected > 0, mutation
            assert context.GetStage3DecisionBinding() is None
            assert context.ResolveStage3Decision(
                None, snapshot, tuple(context._baselines.items()), tuple(context._remote_player_baselines.items())
            ) == (None, "UNAVAILABLE")
        if mutation == "read":
            failed = next(m for m in snapshot.members if m.identity.agent_id == 4000)
            assert failed.role is module.CleansingRole.UNKNOWN and "evidence read failed (ValueError)" in failed.reason
        if mutation == "failure":
            assert sum(m.role is not module.CleansingRole.UNKNOWN for m in snapshot.members) == 1
            assert len(context._baselines) == 1 and not context._remote_player_baselines
        recovered = context.Refresh()
        if enabled:
            assert context.GetStage3DecisionBinding() is not None
        assert len(recovered.members) == 8
    assert outcomes[0] == outcomes[1], (mutation, error_type, outcomes)


@pytest.fixture
def stage3_closing_clocks(cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch) -> Any:
    runtime, module = cleansing_runtime
    harness = _endpoint_runtime(runtime, module, monkeypatch, real_admission=True)
    harness.faults.update({int(hero.agent_id): "absent" for hero in runtime.heroes})
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    clock = types.SimpleNamespace(
        active=False,
        frame=90,
        opening=101,
        closing=(117, 133),
        fresh=(118, 134),
        mutation="none",
        mutation_pass=1,
        unavailable=False,
        reads=0,
        trace=[],
    )

    def capture() -> Any:
        value = _copy_closing_publication(runtime.publication_result)
        if not clock.active:
            return value
        clock.reads += 1
        closing_pass = clock.reads - 1
        value.snapshot.captured_at_tick64 = clock.opening if not closing_pass else clock.closing[closing_pass - 1]
        if closing_pass == clock.mutation_pass:
            cohort = value.snapshot.cohorts[1]
            witness = cohort.witnesses[0]
            if clock.mutation == "heartbeat":
                for current in value.snapshot.cohorts:
                    current.published_tick = value.snapshot.captured_at_tick64 & 0xFFFFFFFF
                    current.owner.GetAccountData().LastUpdated = current.published_tick
            elif clock.mutation == "recovery_zero":
                value.snapshot.recovery_epoch = 0
            elif clock.mutation == "recovery":
                value.snapshot.recovery_epoch += 1
            elif clock.mutation == "incarnation":
                cohort.incarnation = bytes((99,)) + bytes(15)
            elif clock.mutation == "email":
                cohort.owner.GetAccountData().AccountEmail = "PRIVATE_changed@example.invalid"
            elif clock.mutation == "hero_id":
                witness.hero_id += 100
            elif clock.mutation == "revision":
                witness.revision += 1
            elif clock.mutation == "witness_time":
                witness.observed_at_tick64 += 1
            elif clock.mutation == "build":
                witness.skills = (*witness.skills[:-1], witness.skills[-1] + 10)
            elif clock.mutation == "lease":
                cohort.published_tick = (value.snapshot.captured_at_tick64 - 5000) & 0xFFFFFFFF
                cohort.owner.GetAccountData().LastUpdated = cohort.published_tick
        clock.trace.append(("capture", value.snapshot.captured_at_tick64))
        return value

    def fresh_clock() -> Any:
        if not clock.active:
            return runtime.publication_now
        value = clock.fresh[clock.reads - 2]
        clock.trace.append(("clock", value))
        if clock.unavailable and clock.reads - 1 == clock.mutation_pass:
            raise OSError("PRIVATE clock unavailable")
        return value

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", capture)
    monkeypatch.setattr(
        cache.ShMem, "GetBaseTimestamp", lambda: clock.frame if clock.active else runtime.publication_now
    )
    sync = sys.modules["Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync"]
    monkeypatch.setattr(sync, "get_uncached_tick_count64", fresh_clock)
    return types.SimpleNamespace(runtime=runtime, module=module, harness=harness, cache=cache, clock=clock)


@pytest.mark.parametrize("closing_pass", (1, 2))
@pytest.mark.parametrize(
    "case,gate,scope",
    (
        ("advance", "NONE", "NONE"),
        ("equal", "NONE", "NONE"),
        ("heartbeat", "NONE", "NONE"),
        ("wrap", "NONE", "NONE"),
        ("backward", "CAPTURE_TIME", "SHARED"),
        ("future", "CAPTURE_TIME", "SHARED"),
        ("fresh_before_frame", "CAPTURE_TIME", "SHARED"),
        ("recovery_zero", "RECOVERY", "SHARED"),
        ("recovery", "RECOVERY", "REMOTE_OWNER"),
        ("incarnation", "INCARNATION", "LOCAL_OWNER"),
        ("email", "OWNER_EMAIL", "LOCAL_OWNER"),
        ("hero_id", "WITNESS_MISSING", "LH1"),
        ("revision", "WITNESS_REVISION", "LH1"),
        ("witness_time", "WITNESS_TIME", "LH1"),
        ("build", "WITNESS_BUILD", "LH1"),
        ("lease", "LEASE", "LOCAL_OWNER"),
        ("expired_during_close", "LEASE", "REMOTE_OWNER"),
        ("unavailable", "CLOSING_READ", "UNKNOWN"),
        ("negative", "CLOSING_READ", "UNKNOWN"),
        ("overflow", "CLOSING_READ", "UNKNOWN"),
        ("none", "CLOSING_READ", "UNKNOWN"),
        ("bool", "CLOSING_READ", "UNKNOWN"),
        ("float", "CLOSING_READ", "UNKNOWN"),
        ("string", "CLOSING_READ", "UNKNOWN"),
    ),
)
def test_stage3_closing_clock_contract_and_diagnostic_parity(
    stage3_closing_clocks: Any,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    gate: str,
    scope: str,
    closing_pass: int,
) -> None:
    fixture = stage3_closing_clocks
    runtime, module, clock, harness = fixture.runtime, fixture.module, fixture.clock, fixture.harness
    clock.mutation, clock.mutation_pass = case, closing_pass
    index = closing_pass - 1
    if case == "equal":
        clock.closing, clock.fresh = (101, 101), (101, 101)
    elif case == "wrap":
        runtime.publication_now = (1 << 32) - 1
        runtime.publication_result = _remote_publication(
            runtime, module, include_local=True, omit_outpost_children=True
        )
        clock.frame, clock.opening = (1 << 32) - 10, (1 << 32) - 1
        clock.closing, clock.fresh = ((1 << 32) + 15, (1 << 32) + 31), ((1 << 32) + 16, (1 << 32) + 32)
    elif case == "backward":
        clock.closing = tuple(100 if i == index else value for i, value in enumerate(clock.closing))
    elif case in ("future", "fresh_before_frame"):
        clock.fresh = tuple(clock.closing[i] - 1 if i == index else value for i, value in enumerate(clock.fresh))
        if case == "fresh_before_frame":
            clock.frame = 1000
    elif case == "expired_during_close":
        clock.fresh = tuple(5100 if i == index else value for i, value in enumerate(clock.fresh))
    elif case == "unavailable":
        clock.unavailable = True
        # Fail only the requested pass, including when the first closing succeeds.
        clock.fresh = (118, 134)
    elif case in ("negative", "overflow", "none", "bool", "float", "string"):
        invalid = {"negative": -1, "overflow": 1 << 64, "none": None, "bool": True, "float": 118.5, "string": "118"}
        clock.fresh = tuple(invalid[case] if i == index else value for i, value in enumerate(clock.fresh))
    initial = copy.deepcopy(runtime.__dict__)
    outcomes: list[Any] = []
    for diagnostics in ("disabled", "enabled", "fault"):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        clock.active = False
        harness.adapter._living_cache.clear()
        context = module.CleansingContext()
        baseline = context.Refresh()
        assert len(context._baselines) == 6 and all(
            m.role is not module.CleansingRole.UNKNOWN for m in baseline.members
        )
        harness.calls.clear()
        harness.trace.clear()
        runtime.hero_agent_positions.clear()
        runtime.hero_skillbar_positions.clear()
        clock.active, clock.reads = True, 0
        clock.trace.clear()
        with monkeypatch.context() as diagnostic:
            diagnostic.setattr(module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", diagnostics != "disabled")
            if diagnostics != "disabled":
                context.SetStage3DecisionSession(object())
            if diagnostics == "fault":

                def fail(*args: Any, **kwargs: Any) -> Any:
                    raise MemoryError("PRIVATE diagnostic failure")

                diagnostic.setattr(context, "_stage3_complete_decision", fail)
            snapshot = context.Refresh()
            rejected = gate != "NONE"
            expected_pass = closing_pass if rejected else 0
            if diagnostics == "enabled":
                binding = context.GetStage3DecisionBinding()
                assert binding is not None, (case, closing_pass)
                decision, association = context.ResolveStage3Decision(binding, snapshot, binding.local, binding.remote)
                assert association == "EXACT" and decision is not None
                assert decision.failure == (gate, scope, expected_pass), (case, closing_pass, decision, clock.trace)
                assert decision.opening == "ACCEPTED" and decision.final == "OK", (case, decision)
                retained = 4 if case in {"revision", "witness_time", "build"} else 0
                assert decision.baselines == ((5, 0, retained, 5 - retained) if rejected else (5, 5, 5, 0)), (
                    case,
                    decision,
                )
                assert decision.remote == ((0, 0) if rejected else (1, 1)), (case, decision)
            elif diagnostics == "fault":
                assert context.GetStage3DecisionBinding() is None
            expected_trace = [("capture", clock.opening)]
            for i in range(closing_pass if rejected else 2):
                expected_trace.extend((("capture", clock.closing[i]), ("clock", clock.fresh[i])))
            assert clock.trace == expected_trace, (case, closing_pass, clock.trace, expected_trace)
            assert snapshot.ready and snapshot.composition.status is module.CompositionStatus.FALLBACK
            assert sum(m.role is not module.CleansingRole.UNKNOWN for m in snapshot.members) == (1 if rejected else 8)
            isolated_hero = case in {"revision", "witness_time", "build"}
            isolated_owner = case in {"incarnation", "email"}
            assert len(context._baselines) == ((5 if isolated_hero else 1) if rejected else 6)
            assert bool(context._remote_player_baselines) is (not rejected or isolated_hero or isolated_owner)
            outcomes.append(
                (
                    snapshot,
                    dict(context._baselines),
                    dict(context._remote_player_baselines),
                    dict(context._remote_hero_origins),
                    dict(harness.calls),
                    tuple(harness.trace),
                    tuple(clock.trace),
                    tuple(runtime.hero_agent_positions),
                    tuple(runtime.hero_skillbar_positions),
                )
            )
        clock.active = False
        recovered = context.Refresh()
        if isolated_hero or isolated_owner:
            retired_keys = context._transition.retired
            assert len(retired_keys) == (1 if isolated_hero else 5)
            assert all(
                (m.role is module.CleansingRole.UNKNOWN) == (m.identity.stable_key in retired_keys)
                for m in recovered.members
            ), (case, recovered)
            assert len(context._baselines) == (5 if isolated_hero else 1) and len(context._remote_player_baselines) == 1
        else:
            assert all(m.role is not module.CleansingRole.UNKNOWN for m in recovered.members), (case, recovered)
            assert len(context._baselines) == 6 and len(context._remote_player_baselines) == 1
    assert outcomes[0] == outcomes[1] == outcomes[2], (case, closing_pass, outcomes)


@pytest.mark.parametrize("heartbeat", (False, True))
def test_stage3_closing_clock_probe_stays_armed(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch, heartbeat: bool
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    initial = context.GetSnapshot()
    attempt_id = probe._attempt_id
    baseline = probe._outpost_baseline
    original_cohorts = module._copy_published_cohorts(runtime.publication_result.snapshot)
    runtime.frame_now = 90
    reads, start = 0, 101
    trace: list[tuple[str, int]] = []

    def publication() -> Any:
        nonlocal reads
        reads += 1
        value = _copy_closing_publication(runtime.publication_result)
        value.snapshot.captured_at_tick64 = start + (reads - 1) * 16
        if heartbeat:
            for cohort in value.snapshot.cohorts:
                cohort.published_tick = value.snapshot.captured_at_tick64 & 0xFFFFFFFF
                cohort.owner.GetAccountData().LastUpdated = cohort.published_tick
            runtime.publication_result = value
        else:
            assert module._copy_published_cohorts(value.snapshot) == original_cohorts
        trace.append(("capture", value.snapshot.captured_at_tick64))
        return value

    def fresh_clock() -> int:
        value = start + (reads - 1) * 16 + 1
        trace.append(("clock", value))
        return value

    monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    monkeypatch.setattr(
        sys.modules["Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync"], "get_uncached_tick_count64", fresh_clock
    )
    try:
        for cycle in range(3):
            start, reads = 101 + 48 * cycle, 0
            trace.clear()
            fixture.runtime.clock[0] += 0.26
            fixture.cache._refresh_cleansing_context()
            evidence = probe._capture_evidence(context)
            assert evidence.production_evidence.decision_status == "EXACT"
            decision = evidence.production_evidence.decision
            assert decision.failure == ("NONE", "NONE", 0) and decision.baselines == (5, 5, 5, 0)
            assert decision.remote == (1, 1)
            assert "g=NONE/NONE/0" in probe._outpost_cause_details(evidence)
            assert trace == [
                ("capture", start),
                ("capture", start + 16),
                ("clock", start + 17),
                ("capture", start + 32),
                ("clock", start + 33),
            ]
            _run_stage3_browser_update(fixture.widget)
            assert not probe._finished and probe._attempt_id == attempt_id
            assert probe._outpost_baseline is baseline
            assert context.GetSnapshot() == initial and len(context._baselines) == 6
            assert context.GetSnapshot().composition.status is module.CompositionStatus.FALLBACK
            if heartbeat:
                current = module._copy_published_cohorts(runtime.publication_result.snapshot)
                assert tuple(c.witnesses for c in current) == tuple(c.witnesses for c in original_cohorts)
    finally:
        fixture.widget.disable()


def _baseline_deferral_harness(
    monkeypatch: pytest.MonkeyPatch, runtime: _Runtime, module: types.ModuleType
) -> tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime]:
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    _probe_enter_outpost(harness)
    assert harness[3]._outpost_baseline is not None and len(harness[0]._baselines) == 6
    return harness


def _ignore_stage3_refresh(*_args: Any) -> None:
    pass


def _observe_unfinished_baseline_refresh(
    harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime],
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[], None] | None = None,
) -> Any:
    context, cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    original = cache.ShMem.GetNativeAccountSnapshotV3
    published = context.GetSnapshot()
    observations: list[Any] = []

    def publication() -> Any:
        if not observations:
            # Preliminary reads change staged candidates. The completed proof
            # stays private and intact until the owner commits this Refresh.
            assert context.GetSnapshot() is published and len(context._baselines) == 6
            assert context._stage3_mutations > 0
            if mutate is not None:
                mutate()
            evidence = probe._capture_evidence(context)
            observations.append(evidence)
            clock.advance(0.26)
            probe.update()
        return original()

    with monkeypatch.context() as patch:
        patch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", publication)
        upkeeper.main()
    assert len(observations) == 1
    return observations[0]


@pytest.mark.parametrize("loading", ("later", "queued"))
def test_stage3_baseline_deferral_restores_original_attempt_and_verifies_destination(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    loading: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    baseline, started = probe._outpost_baseline, probe._started_at
    evidence = _observe_unfinished_baseline_refresh(harness, monkeypatch)
    production = evidence.production_evidence
    assert production.decision_status == "AMBIGUOUS" and production.unfinished_refresh_sequence is not None
    assert probe._deferred_outpost_refresh is None and not probe._finished
    assert probe._loading_event is None and probe._destination_samples == 0
    assert evidence.production_evidence.roster_signature == baseline.roster_signature
    assert len(context._baselines) == 6 and context.GetSnapshot() is evidence.snapshot
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    completed = recorder._refresh_events[-1].evidence
    assert completed.decision_status == "EXACT"
    assert completed.decision.sequence == production.unfinished_refresh_sequence
    assert completed.roster_signature == baseline.roster_signature
    if loading == "queued":
        runtime.ready, runtime.instance_type_override = False, 2
        upkeeper.main()
        clock.advance(0.26)
        probe.update()
        assert probe._loading_event is not None
    else:
        clock.advance(0.26)
        probe.update()
        assert probe._deferred_outpost_refresh is None and not probe._finished
        _probe_enter_loading(harness)
    assert probe._outpost_baseline is baseline and probe._started_at == started
    assert probe._attempt_id == baseline.attempt_id and probe._deferred_outpost_refresh is None
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    assert probe._destination_samples == 1 and not probe._finished
    _probe_poll_destination(harness)
    assert probe._destination_samples == 1 and not probe._finished
    _probe_sample_destination(harness)
    assert probe._destination_samples == 2 and not probe._finished
    _probe_sample_destination(harness)
    assert probe._destination_samples == 3 and probe._finished
    assert context.GetSnapshot().composition.status is module.CompositionStatus.FALLBACK
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert not any("event=outpost_delta " in line or "event=outpost_cause " in line for line in records)
    assert "result=FULL_SUCCESS" in records[-1]


@pytest.mark.parametrize("recovery", (False, True))
def test_stage3_baseline_deferral_rejects_completed_loss_even_if_later_restored(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    recovery: bool,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness

    def missing_owner() -> None:
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]

    _observe_unfinished_baseline_refresh(harness, monkeypatch, missing_owner)
    assert probe._deferred_outpost_refresh is None and not probe._finished
    assert len(context._baselines) == 6
    if recovery:
        runtime.publication_result = _remote_publication(
            runtime, module, include_local=True, omit_outpost_children=True
        )
        upkeeper.main()
        assert len(context._baselines) == 6
    clock.advance(0.26)
    probe.update()
    assert probe._finished and probe._loading_event is None and probe._destination_samples == 0
    cause = _cause_record(probe, capsys.readouterr().out)
    assert "a=EXACT" in cause and probe._terminal_outcome.reason == "outpost_changed_before_loading"


@pytest.mark.parametrize(
    "mutation", ("role", "build", "identity", "endpoint", "character", "publisher", "map", "lifecycle", "ready")
)
def test_stage3_owner_rejects_completed_substantive_changes_after_reentrant_read(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness

    def change() -> None:
        snapshot = context.GetSnapshot()
        members = list(snapshot.members)
        position = next(
            i for i, member in enumerate(members) if member.evidence_source is module.EvidenceSource.LOCAL_HERO
        )
        member = members[position]
        if mutation == "role":
            members[position] = replace(member, role=module.CleansingRole.UNKNOWN)
        elif mutation == "build":
            members[position] = replace(member, anchor_skill_ids=(987654321,))
        elif mutation in ("identity", "endpoint"):
            members[position] = replace(
                member,
                identity=replace(member.identity, **{"member_id" if mutation == "identity" else "agent_id": 987654321}),
            )
        elif mutation == "publisher":
            key, baseline = next(iter(context._remote_player_baselines.items()))
            context._remote_player_baselines[key] = replace(
                baseline, publisher=replace(baseline.publisher, account_email="PRIVATE_DEFERRAL@example.invalid")
            )
        else:
            changes = {
                "character": {"character_identity": ("PRIVATE_DEFERRAL", "PRIVATE_DEFERRAL")},
                "map": {"map_id": 987654321},
                "lifecycle": {"lifecycle_epoch": snapshot.lifecycle_epoch + 1},
                "ready": {"ready": False},
            }
            context._snapshot = replace(snapshot, **changes[mutation])
            return
        context._snapshot = replace(snapshot, members=tuple(members))

    observation = _observe_unfinished_baseline_refresh(harness, monkeypatch, change)
    assert observation.production_evidence.decision_status == "AMBIGUOUS"
    assert not probe._finished and probe._destination_samples == 0
    # An unfinished read is not authority. Retain the changed values on the
    # completed owner record to exercise the same negative after publication.
    completed = context._stage3_evidence[-1]
    context._stage3_evidence[-1] = replace(
        completed,
        snapshot=observation.snapshot,
        boundary=replace(
            completed.boundary,
            snapshot_revision=observation.snapshot.revision,
            lifecycle_generation=observation.snapshot.lifecycle_epoch,
        ),
        local=observation.production_evidence.local_baselines,
        remote=observation.production_evidence.remote_player_baselines,
        verification=None,
        decision=None,
    )
    _clock.advance(0.26)
    probe.update()
    assert probe._finished and probe._deferred_outpost_refresh is None
    output = capsys.readouterr().out
    assert "result=FULL_SUCCESS" not in output
    assert probe._destination_samples == 0 and probe._loading_event is None
    assert _cause_record(probe, output).endswith("a=UNAVAILABLE")
    assert "PRIVATE_DEFERRAL" not in output and "987654321" not in output


@pytest.mark.parametrize("association", ("post_commit", "stale_sequence", "stale_session", "unrelated_active"))
def test_stage3_baseline_deferral_requires_current_unfinished_refresh_authority(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    association: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    upkeeper.main()
    context._baselines = {key: value for key, value in context._baselines.items() if key[0] is module.MemberKind.PLAYER}
    if association == "stale_sequence":
        context._stage3_decision_sequence += 1
    elif association == "stale_session":
        context.SetStage3DecisionSession(object())
    elif association == "unrelated_active":
        context._stage3_decision_result = None
        context._stage3_decision_active = module._Stage3DecisionCapture(object(), context._stage3_decision_sequence)
    observation = probe._capture_evidence(context)
    assert observation.production_evidence.unfinished_refresh_sequence is None
    clock.advance(0.26)
    probe.update()
    assert probe._finished and probe._deferred_outpost_refresh is None and probe._loading_event is None


@pytest.mark.parametrize("phase", ("outpost", "loading", "explorable"))
def test_stage3_baseline_deferral_requires_recorded_completion_and_keeps_deadline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    phase: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    started, baseline = probe._started_at, probe._outpost_baseline
    with monkeypatch.context() as patch:
        patch.setattr(recorder, "record_refresh", _ignore_stage3_refresh)
        _observe_unfinished_baseline_refresh(harness, monkeypatch)
    assert len(context._baselines) == 6 and probe._deferred_outpost_refresh is None
    if phase != "outpost":
        runtime.ready, runtime.instance_type_override = False, 2
        upkeeper.main()
        if phase == "explorable":
            runtime.unavailable_agents.clear()
            with monkeypatch.context() as patch:
                patch.setattr(recorder, "record_refresh", _ignore_stage3_refresh)
                _probe_enter_destination(harness, include_local=True)
    clock.advance(0.26)
    probe.update()
    assert not probe._finished
    assert (probe._loading_event is not None) == (phase != "outpost")
    assert probe._destination_samples == (1 if phase == "explorable" else 0)
    assert context.ReadStage3OwnerEvidence(probe._owner_source.sequence).events
    assert probe._outpost_baseline is baseline and probe._started_at == started
    # The compatibility lease field cannot extend the absolute activation deadline.
    recorder._active.lease_expires_at_ns = clock.read_ns() + 1_000_000_000_000
    clock.advance(probe._MAX_RUNTIME_SECONDS - (clock.read() - started))
    probe.update()
    assert probe._finished and probe._terminal_outcome.result == "INCONCLUSIVE"
    output = capsys.readouterr().out
    assert "result=FULL_SUCCESS" not in output
    _assert_stage3_output_budget(probe, output)


@pytest.mark.parametrize("replacement", ("disable", "recorder", "reentrant"))
def test_stage3_baseline_deferral_retires_stale_sessions_and_reentrant_completion(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    with monkeypatch.context() as patch:
        if replacement == "reentrant":
            patch.setattr(recorder, "record_refresh", _ignore_stage3_refresh)
        _observe_unfinished_baseline_refresh(harness, monkeypatch)
    old_attempt, old_session = probe._attempt_id, context._stage3_decision_session
    if replacement == "disable":
        probe.on_disable()
        probe.on_enable()
        assert probe._deferred_outpost_refresh is None
        probe.update()
        assert probe._attempt_id != old_attempt and context._stage3_decision_session is not old_session
        assert not recorder.read_refresh_events(old_attempt, 0).active
    elif replacement == "recorder":
        recorder.begin(context, recorder.capture_snapshot(context, context.GetSnapshot()))
        clock.advance(0.26)
        probe.update()
        assert probe._finished and probe._terminal_outcome.reason == "validation_attempt_expired_or_replaced"
        assert context._stage3_decision_session is not old_session
    else:
        # No first completion was recorded. Reproduce the owner's established
        # reentrant-completion ambiguity through its actual path.
        original = context._record_refresh_diagnostic
        nested = False

        def record(snapshot: Any, outcome: str, error: Any = None) -> None:
            nonlocal nested
            if not nested:
                nested = True
                context.Refresh()
            original(snapshot, outcome, error)

        with monkeypatch.context() as patch:
            patch.setattr(context, "_record_refresh_diagnostic", record)
            upkeeper.main()
        assert recorder._refresh_events[-1].evidence.decision_status == "UNAVAILABLE"
        assert recorder._refresh_events[-1].owner.verification is None
        clock.advance(0.26)
        probe.update()
        assert probe._deferred_outpost_refresh is None and not probe._finished
        assert probe._destination_samples == 0
        upkeeper.main()
        clock.advance(0.26)
        probe.update()
        assert probe._deferred_outpost_refresh is None and not probe._finished


def test_stage3_baseline_deferral_reentrant_observation_cannot_borrow_a_refresh_token(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    fixture = _cause_widget(runtime, module, monkeypatch)
    context, probe = fixture.cache.CleansingContext, fixture.probe
    original_reader = fixture.cache.ShMem.GetNativeAccountSnapshotV3
    original_resolve = context.ResolveStage3Decision
    observations: list[Any] = []

    def publication() -> Any:
        if not observations:

            def resolve(*args: Any) -> Any:
                monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", original_reader)
                context.Refresh()
                return original_resolve(*args)

            with monkeypatch.context() as patch:
                patch.setattr(context, "ResolveStage3Decision", resolve)
                observations.append(probe._capture_evidence(context))
        return original_reader()

    monkeypatch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
    fixture.cache._refresh_cleansing_context()
    assert observations[0].production_evidence.unfinished_refresh_sequence is None
    assert probe._destination_samples == 0 and probe._loading_event is None
    assert observations[0].production_evidence.decision_status != "EXACT"
    fixture.widget.disable()


def test_stage3_baseline_deferral_completed_baseline_only_loss_control_rejects(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    original = context._stage3_complete_decision

    def complete(capture: Any, snapshot: Any) -> None:
        # Injected negative control: normal commit removes the associated roles
        # too. Freeze a completed baseline-only loss to test the probe boundary.
        context._baselines = {
            key: value for key, value in context._baselines.items() if key[0] is module.MemberKind.PLAYER
        }
        original(capture, snapshot)

    monkeypatch.setattr(context, "_stage3_complete_decision", complete)
    evidence = _observe_unfinished_baseline_refresh(harness, monkeypatch)
    assert context.GetSnapshot() is evidence.snapshot and len(context._baselines) == 1
    clock.advance(0.26)
    probe.update()
    output = capsys.readouterr().out
    assert (
        "fields=local_baselines.count,LBH1.presence,LBH2.presence,LBH3.presence,LBH4.presence,LBH5.presence trunc=0"
        in output
    )
    assert "a=EXACT" in _cause_record(probe, output)
    assert probe._finished and probe._loading_event is None


def test_stage3_owner_ambiguous_completion_does_not_replace_authentic_loading(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    _observe_unfinished_baseline_refresh(harness, monkeypatch)
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    original = context._record_refresh_diagnostic
    nested = False

    def record(snapshot: Any, outcome: str, error: Any = None) -> None:
        nonlocal nested
        if not nested:
            nested = True
            context.Refresh()
        original(snapshot, outcome, error)

    with monkeypatch.context() as patch:
        patch.setattr(context, "_record_refresh_diagnostic", record)
        upkeeper.main()
    assert recorder._refresh_events[-1].evidence.decision_status == "UNAVAILABLE"
    assert recorder._refresh_events[-1].owner.verification is None
    runtime.ready, runtime.instance_type_override = False, 2
    upkeeper.main()
    clock.advance(0.26)
    probe.update()
    assert probe._deferred_outpost_refresh is None and not probe._finished
    assert probe._loading_event is not None and probe._destination_samples == 0
    assert probe._loading_event.owner.boundary.loading.loading


def test_stage3_baseline_deferral_keeps_rejecting_new_substantive_changes_while_waiting(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    with monkeypatch.context() as patch:
        patch.setattr(recorder, "record_refresh", _ignore_stage3_refresh)
        _observe_unfinished_baseline_refresh(harness, monkeypatch)
    context._snapshot = replace(context.GetSnapshot(), character_identity=("PRIVATE_CHANGED", "PRIVATE_CHANGED"))
    clock.advance(0.26)
    probe.update()
    assert probe._finished and probe._terminal_outcome.reason == "outpost_changed_before_loading"


def test_stage3_baseline_deferral_diagnostic_disabled_enabled_recognition_and_read_order_parity(
    cleansing_runtime: tuple[_Runtime, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    fixture = _stage3_local_witness_widget(runtime, module, monkeypatch)
    initial = copy.deepcopy(runtime.__dict__)
    faults = dict(fixture.runtime.faults)
    outcomes: list[Any] = []
    for enabled in (False, True):
        runtime.__dict__.clear()
        runtime.__dict__.update(copy.deepcopy(initial))
        fixture.runtime.faults.clear()
        fixture.runtime.faults.update(faults)
        fixture.runtime.adapter._living_cache.clear()
        fixture.runtime.clock[0] = 10.0
        fixture.cache.CleansingContext = module.CleansingContext()
        context = fixture.cache.CleansingContext
        fixture.cache._refresh_cleansing_context()
        if enabled:
            fixture.widget.enable()
            _run_stage3_browser_update(fixture.widget)
        fixture.runtime.calls.clear()
        fixture.runtime.trace.clear()
        reader = fixture.cache.ShMem.GetNativeAccountSnapshotV3
        reads = 0

        def publication() -> Any:
            nonlocal reads
            reads += 1
            if reads == 1 and enabled:
                # Isolate the new passive observation from the widget's existing
                # Map phase polls, which intentionally perform extra reads.
                evidence = fixture.probe._capture_evidence(context)
                assert evidence.production_evidence.decision_status == "AMBIGUOUS"
                assert context._stage3_mutations > 0
                assert evidence.production_evidence.roster_signature == fixture.probe._outpost_baseline.roster_signature
            return reader()

        with monkeypatch.context() as patch:
            patch.setattr(fixture.cache.ShMem, "GetNativeAccountSnapshotV3", publication)
            fixture.cache._refresh_cleansing_context()
        outcomes.append(
            (
                context.GetSnapshot(),
                dict(context._baselines),
                dict(context._remote_player_baselines),
                dict(context._remote_hero_origins),
                dict(fixture.runtime.calls),
                tuple(fixture.runtime.trace),
                reads,
            )
        )
        if enabled:
            fixture.runtime.clock[0] += 0.26
            _run_stage3_browser_update(fixture.widget)
            assert not fixture.probe._finished and fixture.probe._deferred_outpost_refresh is None
        fixture.widget.disable()
    assert outcomes[0] == outcomes[1]


def _record_loading_between_probe_polls(
    harness: tuple[Any, Any, Any, Any, _ProbeClock, Any, _Runtime],
    *,
    before_loading: Callable[[], None] | None = None,
    delay: float = 0.05,
) -> Any:
    _context, _cache, upkeeper, probe, clock, diagnostics, runtime = harness
    upkeeper.main()
    if before_loading is not None:
        before_loading()
    clock.advance(delay)
    runtime.ready, runtime.instance_type_override = False, 2
    upkeeper.main()
    event = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_events(probe._attempt_id, 0).events[0]
    if delay < probe._POLL_SECONDS:
        probe.update()  # The real poll throttle skips this short Loading state.
        assert probe._loading_event is None and probe._candidate_loading_event is None
    return event


@pytest.mark.parametrize("observation", ("missed", "direct", "deferred_missed"))
def test_stage3_recorded_loading_authorizes_destination_without_a_second_live_observation(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    observation: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    baseline, started = probe._outpost_baseline, probe._started_at
    if observation == "deferred_missed":
        _observe_unfinished_baseline_refresh(harness, monkeypatch)
        assert probe._deferred_outpost_refresh is None
    event = _record_loading_between_probe_polls(harness)
    assert event.forwarded_loading and event.transition_latched is True
    assert probe._valid_initial_forwarding_event(event, baseline)
    assert len(context._baselines) == 6
    if observation == "direct":
        clock.advance(0.26)
        probe.update()
        assert probe._phase() == "loading" and probe._loading_event is event
    # The first destination Refresh must occur strictly after recorded Loading.
    clock.advance(0.001)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    assert probe._phase() == "explorable" and probe._loading_event is event
    assert 0 <= clock.read_ns() - event.observed_at_ns <= probe._FORWARDING_FRESHNESS_NS
    assert probe._outpost_baseline is baseline and probe._started_at == started
    assert probe._deferred_outpost_refresh is None and len(context._baselines) == 6
    assert all(member.role is not module.CleansingRole.UNKNOWN for member in context.GetSnapshot().members)
    assert context.GetSnapshot().composition.status is module.CompositionStatus.FALLBACK
    assert dict(context.GetSnapshot().composition.role_counts)[module.CleansingRole.UNKNOWN] == 2
    assert probe._capture_evidence(context).stage4_fence
    assert probe._destination_samples == 1 and not probe._finished
    _probe_poll_destination(harness)
    assert probe._destination_samples == 1 and not probe._finished
    _probe_sample_destination(harness)
    assert probe._destination_samples == 2 and not probe._finished
    _probe_sample_destination(harness)
    assert probe._destination_samples == 3 and probe._finished
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert sum("event=loading " in line for line in records) == 1
    assert "result=FULL_SUCCESS" in records[-1] and "loading=1 samples=3/3" in records[-1]


@pytest.mark.parametrize("authority", ("generic", "unknown_raw", "world", "map", "char", "instance_info"))
def test_stage3_recorded_loading_rejects_missing_or_unobserved_raw_loading_authority(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    authority: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    _context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    upkeeper.main()
    runtime.ready = False
    if authority == "generic":
        runtime.instance_type_override = 0
    elif authority == "unknown_raw":
        runtime.instance_type_override = 999
    else:
        runtime.instance_type_override = 2
        runtime.missing_map_contexts.add(authority)
    upkeeper.main()
    event = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_events(probe._attempt_id, 0).events[0]
    assert not event.forwarded_loading and event.transition_latched is False
    runtime.missing_map_contexts.clear()
    clock.advance(0.001)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    assert probe._finished and probe._terminal_outcome.reason == "outpost_changed_before_loading"
    assert probe._loading_event is None
    assert probe._destination_samples == 0


@pytest.mark.parametrize("defect", ("stale", "future", "pre_forward_stale", "attempt", "latch", "lifecycle", "map"))
def test_stage3_recorded_loading_uses_fixed_deadline_and_owner_association(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    event = _record_loading_between_probe_polls(harness, delay=1.01 if defect == "pre_forward_stale" else 0.05)
    if defect == "stale":
        clock.advance(0.8)
    elif defect == "attempt":
        context.SetStage3DecisionSession(object())
    elif defect != "pre_forward_stale":
        # Corrupt the owning record, rather than a legacy presentation copy.
        owner = event.owner
        assert owner is not None
        if defect == "future":
            corrupted = replace(owner, observed_at=clock.read() + 10.0)
        else:
            changes = {
                "latch": {"loading": None},
                "lifecycle": {"source_generation": owner.boundary.source_generation + 1},
                "map": {"transition_id": owner.boundary.transition_id + 1},
            }
            corrupted = replace(owner, boundary=replace(owner.boundary, **changes[defect]))
        position = next(i for i, item in enumerate(context._stage3_evidence) if item is owner)
        context._stage3_evidence[position] = corrupted
    clock.advance(0.001)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    if defect in ("stale", "pre_forward_stale"):
        assert not probe._finished and probe._loading_event is not None
        assert probe._destination_samples == 1
        return
    assert probe._finished and probe._loading_event is None and probe._destination_samples == 0
    expected = {
        "future": "production_evidence_order_invalid",
        "attempt": "validation_attempt_expired_or_replaced",
        "latch": "loading_authority_unproven",
        "lifecycle": "outpost_changed_before_loading",
        "map": "outpost_changed_before_loading",
    }[defect]
    assert probe._terminal_outcome.reason == expected


@pytest.mark.parametrize("replacement", ("session", "replay"))
def test_stage3_recorded_loading_cannot_reuse_a_retired_session_or_previous_attempt_event(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    event = _record_loading_between_probe_polls(harness)
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    if replacement == "session":
        # A separate recorder can allocate the same numeric attempt ID; the
        # existing context session ownership must still reject the old recorder.
        replacement_recorder = type(recorder)()
        runtime.ready, runtime.instance_type_override = True, None
        upkeeper.main()
        new_id = replacement_recorder.begin(context, recorder.capture_snapshot(context, context.GetSnapshot()))
        assert new_id == event.attempt_id
    else:
        probe.on_disable()
        runtime.ready, runtime.instance_type_override = True, None
        upkeeper.main()
        probe.on_enable()
        probe.update()
        assert probe._attempt_id != event.attempt_id
        recorder._events.append(event)  # Inject the old, otherwise genuine event.
        assert recorder.read_events(probe._attempt_id, 0).events == ()
    clock.advance(0.001)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    assert probe._finished and probe._loading_event is None and probe._destination_samples == 0
    expected = (
        "validation_attempt_expired_or_replaced" if replacement == "session" else "outpost_changed_before_loading"
    )
    assert probe._terminal_outcome.reason == expected


@pytest.mark.parametrize("change", ("roster", "owner", "publisher", "baseline", "publication"))
def test_stage3_recorded_loading_rejects_changed_original_outpost_proof(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness

    def change_before_loading() -> None:
        if change == "baseline":
            # Post-commit mutation control: six baselines were originally
            # accepted, but only five are present at the actual forwarding edge.
            context._baselines.pop(next(key for key in context._baselines if key[0] is module.MemberKind.HERO))
            return
        if change == "roster":
            runtime.party_id += 1
            runtime.publication_result = _remote_publication(
                runtime, module, include_local=True, omit_outpost_children=True
            )
        elif change == "owner":
            runtime.heroes[0].owner_player_id = 99
        elif change == "publisher":
            runtime.publication_result.snapshot.cohorts[0].incarnation = bytes((99,)) + bytes(15)
        else:
            runtime.publication_result = types.SimpleNamespace(status="busy", snapshot=None)
        upkeeper.main()

    event = _record_loading_between_probe_polls(harness, before_loading=change_before_loading)
    assert event.forwarded_loading
    clock.advance(0.001)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    expected = "production_transition_retired" if change == "baseline" else "outpost_changed_before_loading"
    assert probe._finished and probe._terminal_outcome.reason == expected
    assert (probe._loading_event is not None) == (change == "baseline")
    assert probe._destination_samples == 0


@pytest.mark.parametrize("samples", (1, 2))
def test_stage3_recorded_loading_cannot_finish_with_fewer_than_three_destination_refreshes(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    samples: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    event = _record_loading_between_probe_polls(harness)
    clock.advance(0.001)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    if samples == 2:
        _probe_sample_destination(harness)
    assert probe._loading_event is event and probe._destination_samples == samples and not probe._finished
    for _ in range(2):
        _probe_poll_destination(harness)
        assert probe._destination_samples == samples and not probe._finished
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    recorder._active.lease_expires_at_ns = clock.read_ns() + 1_000_000_000_000
    clock.value = probe._started_at + probe._MAX_RUNTIME_SECONDS
    probe.update()
    assert probe._finished and probe._terminal_outcome.reason == "stable_destination_samples_incomplete"
    records = _assert_stage3_output_budget(probe, capsys.readouterr().out)
    assert "result=INCONCLUSIVE" in records[-1] and f"samples={samples}/3" in records[-1]


def test_stage3_recorded_loading_live_poll_alone_cannot_authorize_or_extend_the_deadline(
    cleansing_runtime: tuple[_Runtime, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime, module = cleansing_runtime
    harness = _baseline_deferral_harness(monkeypatch, runtime, module)
    _context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    started, baseline = probe._started_at, probe._outpost_baseline
    runtime.ready, runtime.instance_type_override = False, 2
    # The live state is explicitly Loading, but Upkeeper never forwards it.
    clock.advance(0.26)
    probe.update()
    assert probe._phase() == "loading" and not probe._finished
    assert probe._loading_event is None and probe._destination_samples == 0
    assert probe._started_at == started and probe._outpost_baseline is baseline
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    recorder._active.lease_expires_at_ns = clock.read_ns() + 1_000_000_000_000
    clock.value = started + probe._MAX_RUNTIME_SECONDS
    probe.update()
    assert probe._finished and probe._terminal_outcome.reason == "loading_not_observed"
    assert probe._loading_event is None and probe._destination_samples == 0
    _assert_stage3_output_budget(probe, capsys.readouterr().out)


def _bounded_stage3_setup(
    runtime: Any,
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    witnesses: bool = False,
) -> tuple[Any, list[float]]:
    clock = [100.0]
    map_api = sys.modules["Py4GWCoreLib"].Map
    monkeypatch.setitem(map_api.GetLoadingObservation.__globals__, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module, "_transition_clock", lambda: clock[0])
    if witnesses:
        context = _outpost_witness_party(runtime, module, local_count=1)
    else:
        _set_player_role(runtime, module, module.CleansingRole.ENERGY_SURGE)
        _add_remote_player(runtime, module, role=module.CleansingRole.PANIC)
        runtime.publication_result = _remote_publication(runtime, module)
        context = module.CleansingContext()
    assert context.Refresh().ready
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.OUTPOST_READY
    return context, clock


def _bounded_stage3_loading(runtime: Any, context: Any) -> None:
    runtime.ready, runtime.instance_type_override = False, 2
    assert not context.Refresh().ready
    runtime.ready, runtime.instance_type_override = True, None
    runtime.map_id, runtime.outpost, runtime.explorable = 2, False, True
    runtime.unavailable_agents.clear()


@pytest.mark.parametrize("gap", ("source", "empty", "busy", "unavailable", "endpoint", "build", "party"))
@pytest.mark.parametrize("witnesses", (False, True))
def test_bounded_stage3_late_destination_admission(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    gap: str,
    witnesses: bool,
) -> None:
    runtime, module = cleansing_runtime
    context, clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=witnesses)
    source = runtime.publication_result
    source_remote = dict(context._remote_player_baselines)
    source_origins = dict(context._remote_hero_origins)
    _bounded_stage3_loading(runtime, context)
    loading = context.GetTransitionBoundary().loading
    deadline = context.GetTransitionBoundary().deadline
    destination = _remote_publication(runtime, module, include_local=witnesses)
    runtime.publication_result = destination
    if gap == "source":
        runtime.publication_result = source
    elif gap == "empty":
        runtime.publication_result = copy.deepcopy(destination)
        runtime.publication_result.snapshot.cohorts = ()
    elif gap in ("busy", "unavailable"):
        runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value=gap), snapshot=None)
    elif gap == "endpoint":
        runtime.unavailable_agents.add(2001)
    elif gap == "build":
        runtime.publication_result = copy.deepcopy(destination)
        runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData().AgentData.Skillbar.Skills = tuple(
            types.SimpleNamespace(Id=0) for _ in range(8)
        )
    else:
        runtime.party_loaded = False
    pending = context.Refresh()
    assert context._remote_player_baselines == source_remote, (gap, pending, context._remote_player_baselines)
    assert set(context._remote_hero_origins) == set(source_origins)
    assert all(
        (origin.publisher, origin.witness) == (source_origins[key].publisher, source_origins[key].witness)
        for key, origin in context._remote_hero_origins.items()
    )
    assert context.GetTransitionBoundary().loading is loading
    assert context.GetTransitionBoundary().deadline == deadline
    if pending.members:
        assert _remote_player_record(pending, module).role is module.CleansingRole.UNKNOWN
    else:
        assert not pending.ready
    runtime.party_loaded = True
    runtime.unavailable_agents.clear()
    runtime.publication_result = _remote_publication(runtime, module, include_local=witnesses)
    clock[0] += 59.0
    admitted = context.Refresh()
    assert _remote_player_record(admitted, module).role is (
        module.CleansingRole.BIP if witnesses else module.CleansingRole.PANIC
    ), (gap, admitted)
    if witnesses:
        assert _remote_hero_record(admitted, module).role is module.CleansingRole.ENERGY_SURGE
        assert all(member.role is not module.CleansingRole.UNKNOWN for member in admitted.members)
        assert admitted.composition.status is module.CompositionStatus.FALLBACK
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.DESTINATION_VERIFIED


@pytest.mark.parametrize("recover", (False, True))
def test_bounded_stage3_original_deadline_and_outpost_recovery(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    recover: bool,
) -> None:
    runtime, module = cleansing_runtime
    context, clock = _bounded_stage3_setup(runtime, module, monkeypatch)
    runtime.missing_map_contexts.add("world")
    assert not context.Refresh().ready
    first = context.GetTransitionBoundary()
    assert first.phase is module.TransitionPhase.WAITING_FOR_LOADING
    assert first.deadline == 160.0 and first.loading is None
    assert context._remote_player_baselines
    runtime.missing_map_contexts.clear()
    if recover:
        for moment in (110.0, 130.0, 159.0):
            clock[0] = moment
            assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC
            assert context.GetTransitionBoundary().phase is module.TransitionPhase.OUTPOST_READY
            runtime.party_loaded = False
            assert not context.Refresh().ready
            assert context.GetTransitionBoundary().deadline == first.deadline
            runtime.party_loaded = True
    clock[0] = 160.0
    runtime.ready, runtime.instance_type_override = False, 2
    context.Refresh()
    assert not context._remote_player_baselines
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED
    runtime.ready, runtime.instance_type_override = True, None
    runtime.outpost, runtime.explorable, runtime.map_id = False, True, 2
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.UNKNOWN


@pytest.mark.parametrize("missing", ("map", "char", "world", "instance_info"))
def test_bounded_stage3_strict_loading_and_no_destination_without_it(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch)
    runtime.missing_map_contexts.add(missing)
    runtime.instance_type_override = 2
    context.Refresh()
    assert context.GetTransitionBoundary().loading is None
    assert context._remote_player_baselines
    runtime.missing_map_contexts.clear()
    runtime.instance_type_override = None
    runtime.outpost, runtime.explorable, runtime.map_id = False, True, 2
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.UNKNOWN
    assert not context._remote_player_baselines


@pytest.mark.parametrize("status", ("recovery", "sync_failure", "malformed", "exception"))
def test_bounded_stage3_native_failures_retire_without_resurrection(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _bounded_stage3_loading(runtime, context)
    destination = _remote_publication(runtime, module, include_local=True)
    if status == "exception":

        def fail() -> None:
            raise RuntimeError("unclassified publication failure")

        runtime.publication_mutator = fail
    elif status == "malformed":
        runtime.publication_result = types.SimpleNamespace(
            status=types.SimpleNamespace(value="success"), snapshot=object()
        )
    else:
        runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value=status), snapshot=None)
    context.Refresh()
    assert not context._remote_player_baselines and not context._remote_hero_origins

    assert not any(baseline.witness_origin is not None for baseline in context._baselines.values())
    runtime.publication_mutator = None
    runtime.publication_result = destination
    result = context.Refresh()
    assert _remote_player_record(result, module).role is module.CleansingRole.UNKNOWN
    assert _remote_hero_record(result, module).role is module.CleansingRole.UNKNOWN


def test_bounded_stage3_upkeeper_matches_direct_and_observes_before_throttle(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    direct, clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    owned = module.CleansingContext()
    owned.Refresh()
    runtime_cache = sys.modules["Py4GWCoreLib"].GLOBAL_CACHE
    cache = object.__new__(_load_global_cache_owner(monkeypatch))
    cache.CleansingContext, cache.Party = owned, runtime_cache.Party
    cache.ShMem, cache.Skill, cache.Coroutines = runtime_cache.ShMem, runtime_cache.Skill, []
    monkeypatch.setattr(cache.Party, "_update_cache", lambda: None, raising=False)
    expired = [False]
    timer = types.SimpleNamespace(IsExpired=lambda: expired[0], Reset=lambda: None)
    cache._TrottleTimers = types.SimpleNamespace(_75ms=timer, _150ms=timer, _500ms=timer)
    cache._RawItemCache = types.SimpleNamespace(update=lambda: None)
    cache.Item = cache.Camera = cache.SkillBar = types.SimpleNamespace(_update_cache=lambda: None)
    upkeeper, _loot = _load_environment_upkeeper(monkeypatch, runtime, cache)
    calls = [0]
    refresh = owned._refresh_from_runtime

    def count_refresh() -> Any:
        calls[0] += 1
        return refresh()

    monkeypatch.setattr(owned, "_refresh_from_runtime", count_refresh)
    for _ in range(5):
        upkeeper.main()
    assert calls[0] == 0
    assert owned.GetTransitionBoundary().sequence == 6
    runtime.missing_map_contexts.add("world")
    direct.Refresh()
    upkeeper.main()
    first_deadline = owned.GetTransitionBoundary().deadline
    assert direct.GetTransitionBoundary().phase == owned.GetTransitionBoundary().phase
    assert direct.GetSnapshot().lifecycle_epoch == owned.GetSnapshot().lifecycle_epoch
    assert owned._remote_player_baselines and owned.GetSnapshot().members == ()
    runtime.missing_map_contexts.clear()
    clock[0] += 1.0
    runtime.ready, runtime.instance_type_override = False, 2
    direct.Refresh()
    upkeeper.main()
    production_loading = owned.GetTransitionBoundary().loading
    assert production_loading is not None and production_loading.loading
    assert calls[0] == 0
    runtime.ready, runtime.instance_type_override = True, None
    runtime.map_id, runtime.outpost, runtime.explorable = 2, False, True
    runtime.unavailable_agents.clear()
    runtime.party_loaded = False
    direct.Refresh()
    upkeeper.main()
    assert direct.GetTransitionBoundary().phase == owned.GetTransitionBoundary().phase
    runtime.party_loaded = True
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    for _ in range(5):
        upkeeper.main()
    assert calls[0] == 0 and owned.GetTransitionBoundary().deadline == first_deadline
    assert owned.GetTransitionBoundary().loading is production_loading
    expired[0] = True
    upkeeper.main()
    direct.Refresh()
    assert calls[0] == 1

    assert (
        direct.GetTransitionBoundary().phase
        == owned.GetTransitionBoundary().phase
        == module.TransitionPhase.DESTINATION_VERIFIED
    )
    assert tuple(member.role for member in direct.GetSnapshot().members) == tuple(
        member.role for member in owned.GetSnapshot().members
    )
    assert direct.GetSnapshot().lifecycle_epoch == owned.GetSnapshot().lifecycle_epoch
    assert direct.GetSnapshot().composition == owned.GetSnapshot().composition
    boundary = owned.GetTransitionBoundary()
    expired[0] = False
    upkeeper.main()
    assert owned.GetTransitionBoundary().sequence == boundary.sequence + 1
    assert owned.GetTransitionBoundary().completed_refresh == boundary.completed_refresh
    assert calls[0] == 1


@pytest.mark.parametrize(
    "defect", ("account", "uuid", "incarnation", "window", "recovery", "party", "build", "disconnect", "duplicate")
)
def test_bounded_stage3_positive_contradictions_cannot_resurrect(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    cohort = runtime.publication_result.snapshot.cohorts[0]
    owner = cohort.owner.GetAccountData()
    if defect == "account":
        owner.AccountEmail = "different@example.test"
    elif defect == "uuid":
        cohort.character_uuid = owner.AgentData.UUID = (999, 0, 0, 0)
    elif defect == "incarnation":
        cohort.incarnation = bytes([99]) * 16
    elif defect == "window":
        owner.Key.HWND += 1
    elif defect == "recovery":
        runtime.publication_result.snapshot.recovery_epoch += 1
    elif defect == "party":
        runtime.party_id += 1
    elif defect == "build":
        owner.AgentData.Skillbar.Skills = tuple(
            types.SimpleNamespace(Id=skill) for skill in _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
        )
    elif defect == "disconnect":
        runtime.players[1].is_connected = False
    else:
        runtime.publication_result.snapshot.cohorts = (*runtime.publication_result.snapshot.cohorts, cohort)
    rejected = context.Refresh()
    assert _remote_player_record(rejected, module).role is module.CleansingRole.UNKNOWN
    assert _remote_hero_record(rejected, module).role is module.CleansingRole.UNKNOWN
    assert not context._remote_player_baselines and not context._remote_hero_origins
    runtime.players[1].is_connected = True
    runtime.party_id = 5
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    returned = context.Refresh()
    assert _remote_player_record(returned, module).role is module.CleansingRole.UNKNOWN
    assert _remote_hero_record(returned, module).role is module.CleansingRole.UNKNOWN


@pytest.mark.parametrize("status", ("busy", "unavailable", "empty"))
@pytest.mark.parametrize("closing_pass", (2, 3))
def test_bounded_stage3_closing_unavailability_discards_admissions_only(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    closing_pass: int,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _bounded_stage3_loading(runtime, context)
    destination = _remote_publication(runtime, module, include_local=True)
    runtime.publication_result = destination
    count = [0]
    empty = _remote_publication(runtime, module, include_local=True)
    empty.snapshot.cohorts = ()

    def select_publication() -> None:
        count[0] += 1
        runtime.publication_result = (
            destination
            if count[0] != closing_pass
            else (
                empty
                if status == "empty"
                else types.SimpleNamespace(status=types.SimpleNamespace(value=status), snapshot=None)
            )
        )

    runtime.publication_mutator = select_publication
    snapshot = context.Refresh()
    assert count[0] >= closing_pass
    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN
    assert _remote_hero_record(snapshot, module).role is module.CleansingRole.UNKNOWN
    assert context._remote_player_baselines and all(
        baseline.destination_map_id is None for baseline in context._remote_player_baselines.values()
    )
    assert context._remote_hero_origins and all(
        origin.destination_epoch is None for origin in context._remote_hero_origins.values()
    )
    runtime.publication_mutator = None
    runtime.publication_result = destination
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.BIP


@pytest.mark.parametrize("defect", ("account", "uuid"))
def test_bounded_stage3_available_local_contradiction_overrides_missing_context(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch)
    runtime.missing_map_contexts.add("world")
    if defect == "account":
        runtime.account_email = "different@example.test"
    else:
        runtime.local_uuid = (999, 0, 0, 0)
    assert not context.Refresh().ready
    assert not context._remote_player_baselines
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED


@pytest.mark.parametrize("retirement", ("invalidate", "second_loading", "second_destination", "stale_source"))
def test_bounded_stage3_unsupported_reuse_is_retired(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    retirement: str,
) -> None:
    runtime, module = cleansing_runtime
    context, clock = _bounded_stage3_setup(runtime, module, monkeypatch)
    if retirement == "stale_source":
        clock[0] += 5.001
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module)
    if retirement != "stale_source":
        assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC
    if retirement == "invalidate":
        context.Invalidate()
    elif retirement == "second_loading":
        runtime.ready, runtime.instance_type_override = False, 2
        context.Refresh()
        runtime.ready, runtime.instance_type_override = True, None
    elif retirement == "second_destination":
        runtime.map_id += 1
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.UNKNOWN
    assert not context._remote_player_baselines


@pytest.mark.parametrize("removal", ("owner", "hero"))
def test_bounded_stage3_complete_roster_removal_retires_candidates(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    removal: str,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _bounded_stage3_loading(runtime, context)
    players, heroes = list(runtime.players), list(runtime.heroes)
    if removal == "owner":
        runtime.players = runtime.players[:1]
        runtime.heroes = [hero for hero in runtime.heroes if hero.owner_player_id == runtime.login_number]
    else:
        runtime.heroes = [hero for hero in runtime.heroes if hero.owner_player_id == runtime.login_number]
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    context.Refresh()
    assert not context._remote_hero_origins
    if removal == "owner":
        assert not context._remote_player_baselines
    runtime.players, runtime.heroes = players, heroes
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    returned = context.Refresh()
    assert _remote_hero_record(returned, module).role is module.CleansingRole.UNKNOWN
    if removal == "owner":
        assert _remote_player_record(returned, module).role is module.CleansingRole.UNKNOWN


@pytest.mark.parametrize("change", ("region", "district", "language"))
def test_bounded_stage3_destination_signature_change_retires(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch)
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.PANIC
    setattr(runtime, f"{change}_id", getattr(runtime, f"{change}_id") + 1)
    runtime.publication_result = _remote_publication(runtime, module)
    assert _remote_player_record(context.Refresh(), module).role is module.CleansingRole.UNKNOWN
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED


def test_bounded_stage3_deadline_crossed_during_closing_rejects_admission(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    context, clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    reads = [0]

    def expire_at_closing() -> None:
        reads[0] += 1
        if reads[0] == 3:
            clock[0] = 160.0

    runtime.publication_mutator = expire_at_closing
    snapshot = context.Refresh()
    assert reads[0] == 3
    assert all(member.role is module.CleansingRole.UNKNOWN for member in snapshot.members[1:])
    assert not context._remote_player_baselines and not context._remote_hero_origins
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED


@pytest.mark.parametrize("gap", ("busy", "empty", "endpoint"))
def test_bounded_stage3_publication_loss_after_admission_does_not_rearm(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    gap: str,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    assert _remote_hero_record(context.Refresh(), module).role is module.CleansingRole.ENERGY_SURGE
    if gap == "busy":
        runtime.publication_result = types.SimpleNamespace(status=types.SimpleNamespace(value="busy"), snapshot=None)
    elif gap == "empty":
        runtime.publication_result.snapshot.cohorts = ()
    else:
        runtime.unavailable_agents.add(2001)
    rejected = context.Refresh()
    assert _remote_player_record(rejected, module).role is module.CleansingRole.UNKNOWN
    assert _remote_hero_record(rejected, module).role is module.CleansingRole.UNKNOWN
    assert not context._remote_player_baselines and not context._remote_hero_origins
    runtime.unavailable_agents.clear()
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    returned = context.Refresh()
    assert _remote_player_record(returned, module).role is module.CleansingRole.UNKNOWN
    assert _remote_hero_record(returned, module).role is module.CleansingRole.UNKNOWN


def test_bounded_stage3_unreadable_environment_avoids_runtime_reads_and_freezes_boundary(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch)
    runtime.missing_map_contexts.add("world")
    core = sys.modules["Py4GWCoreLib"]
    calls: list[str] = []

    def forbidden() -> bool:
        calls.append("unsafe")
        raise AssertionError("unreadable environment accessed player or party runtime")

    monkeypatch.setattr(core.Player, "IsPlayerLoaded", forbidden)
    monkeypatch.setattr(core.GLOBAL_CACHE.Party, "IsPartyLoaded", forbidden)
    observation = context.CaptureEnvironment()
    assert not observation.readable
    boundary = context.ObserveEnvironment(observation)
    assert not context.Refresh(boundary).ready
    assert calls == []
    with pytest.raises(AttributeError):
        observation.loading.raw_instance_type = 2
    with pytest.raises(AttributeError):
        boundary.deadline = 999.0
    current = context.GetTransitionBoundary()
    assert current.completed_refresh == boundary.completed_refresh + 1
    assert current.sequence == boundary.sequence
    assert context.Refresh(boundary).reason == "stale environment observation supplied to Refresh"
    assert not context._remote_player_baselines


def _stage3_owner_probe_candidate(runtime: _Runtime, module: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    _probe_sample_destination(harness)
    _context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    assert probe._destination_samples == 2 and not probe._finished
    clock.advance(1.01)
    upkeeper.main()
    return harness


def test_stage3_owner_probe_existing_completed_outpost_arms_without_refresh(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, _clock, diagnostics, _runtime = harness
    upkeeper.main()
    before = context.GetTransitionBoundary()
    probe.on_enable()
    probe.update()
    assert probe._attempt_id is not None
    assert context.GetTransitionBoundary() is before
    assert probe._owner_source.boundary is before
    assert probe._owner_source.verification is not None
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.source_proof(probe._attempt_id, context) is probe._owner_source


@pytest.mark.parametrize(
    "fault,reason",
    (
        ("active", "owner_refresh_in_progress"),
        ("snapshot", "completed_outpost_snapshot_replaced"),
        ("verification", "completed_outpost_verification_missing"),
        ("synchronization", "owner_synchronization_unavailable"),
    ),
)
def test_stage3_owner_probe_arming_reports_exact_owner_refusal(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    reason: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, _probe, _clock, diagnostics, _runtime = harness
    upkeeper.main()
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    evidence = recorder.capture_snapshot(context, context.GetSnapshot())
    assert evidence is not None
    if fault == "active":
        context._stage3_mutations = 1
    elif fault == "snapshot":
        context._snapshot = replace(context.GetSnapshot())
    elif fault == "verification":
        event = context._stage3_evidence[-1]
        context._stage3_evidence[-1] = replace(event, verification=None)
    else:
        context._stage3_evidence_lock = None
    assert recorder.begin(context, evidence) is None
    assert recorder.last_begin_reason == reason
    assert recorder._active is None and context._stage3_decision_session is None


def test_stage3_owner_probe_failed_session_publication_retires_partial_binding(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, _probe, _clock, diagnostics, _runtime = harness
    upkeeper.main()
    snapshot = context.GetSnapshot()
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    evidence = recorder.capture_snapshot(context, snapshot)
    original = context.SetStage3DecisionSession

    def publish_then_fail(session: object) -> None:
        original(session)
        raise MemoryError("PRIVATE session publication fault")

    monkeypatch.setattr(context, "SetStage3DecisionSession", publish_then_fail)
    assert recorder.begin(context, evidence) is None
    assert recorder.last_begin_reason == "owner_binding_exception"
    assert recorder._active is None and context._stage3_decision_session is None
    assert context.GetSnapshot() is snapshot and snapshot.ready


@pytest.mark.parametrize("site", ("Stage3OwnerEvidence", "_Stage3ClosingInputs"))
@pytest.mark.parametrize("error_type", (MemoryError, ValueError))
def test_stage3_owner_probe_capture_fault_preserves_recognition_and_forbids_arming(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    site: str,
    error_type: type[Exception],
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, _probe, _clock, diagnostics, _runtime = harness
    upkeeper.main()
    expected = context.GetSnapshot()
    baselines = (dict(context._baselines), dict(context._remote_player_baselines), dict(context._remote_hero_origins))
    cursor = context._stage3_evidence_sequence

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise error_type("PRIVATE diagnostic allocation fault")

    with monkeypatch.context() as patch:
        patch.setattr(module, site, fail)
        observed = context.Refresh()
    assert observed is expected and observed.ready
    assert (context._baselines, context._remote_player_baselines, context._remote_hero_origins) == baselines
    assert context.ReadStage3OwnerEvidence(cursor).gap
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    assert recorder.begin(context, recorder.capture_snapshot(context, observed)) is None
    assert recorder.last_begin_reason == "owner_evidence_capture_failed"
    assert context.Refresh() is expected
    assert context.BindStage3Outpost(expected) is None


def test_stage3_owner_probe_oversized_record_is_not_retained(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, _probe, _clock, _diagnostics, _runtime = harness
    upkeeper.main()
    snapshot = context.GetSnapshot()
    before = tuple(context._stage3_evidence)
    context._snapshot = replace(snapshot, members=snapshot.members * 1000)
    context._update_transition_boundary()
    assert tuple(context._stage3_evidence) == before
    assert context._stage3_evidence_failed
    assert context.ReadStage3OwnerEvidence(before[-1].sequence).gap


@pytest.mark.parametrize("entry", ("direct", "upkeeper"))
@pytest.mark.parametrize("delay", (0.8, 3.0, 59.0))
def test_stage3_owner_probe_delayed_loading_uses_production_authority(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
    delay: float,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    clock.advance(0.3)
    runtime.ready, runtime.instance_type_override = False, 2
    if entry == "direct":
        context.Refresh()
    else:
        upkeeper.main()
    clock.advance(delay)
    probe.update()
    assert not probe._finished and probe._loading_event is not None, (entry, delay, probe._terminal_outcome)
    assert probe._loading_event.owner.boundary.loading.loading
    assert probe._loading_event.owner.boundary.transition_id == probe._owner_source.boundary.transition_id


@pytest.mark.parametrize("order", ("unavailable_loading", "loading_unavailable"))
def test_stage3_owner_probe_temporary_unreadiness_preserves_loading(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    order: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    for state in order.split("_"):
        clock.advance(0.3)
        runtime.ready = False
        runtime.instance_type_override = 2 if state == "loading" else None
        runtime.missing_map_contexts = set() if state == "loading" else {"world"}
        context.Refresh()
    clock.advance(0.3)
    probe.update()
    assert not probe._finished and probe._loading_event is not None, (order, probe._terminal_outcome)
    assert probe._destination_samples == 0


@pytest.mark.parametrize("count", (0, 1, 2))
def test_stage3_owner_probe_direct_finish_cannot_serialize_incomplete_success(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    count: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    probe = harness[3]
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    if count:
        _probe_enter_destination(harness)
    if count == 2:
        _probe_sample_destination(harness)
    assert probe._destination_samples == count
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    output = capsys.readouterr().out
    assert "result=FULL_SUCCESS" not in output, (count, output)
    assert probe._terminal_outcome.result == "INCONCLUSIVE"
    probe._retry_finalization()
    assert "result=FULL_SUCCESS" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "mutation",
    (
        "account",
        "character",
        "uuid",
        "party",
        "recovery",
        "incarnation",
        "hwnd",
        "owner",
        "hero",
        "witness",
        "build",
        "freshness",
        "context",
        "exception",
        "refresh",
        "invalidation",
        "published_invalidation",
        "session",
        "attempt",
    ),
)
def test_stage3_owner_probe_fresh_final_verification_rejects_changed_proof(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    mutation: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    snapshot = context.GetSnapshot()
    boundary = context.GetTransitionBoundary()
    cohorts = runtime.publication_result.snapshot.cohorts
    cohort = cohorts[0]
    if mutation == "account":
        runtime.account_email = "changed@example.invalid"
    elif mutation == "character":
        runtime.character_name = "Different Character"
    elif mutation == "uuid":
        runtime.local_uuid = (999, 0, 0, 0)
    elif mutation == "party":
        runtime.party_id += 1
    elif mutation == "recovery":
        runtime.publication_result.snapshot.recovery_epoch += 1
    elif mutation == "incarnation":
        cohort.incarnation = bytes((99,)) + bytes(15)
    elif mutation == "hwnd":
        cohort.owner.GetAccountData().Key.HWND += 1
    elif mutation == "owner":
        cohort.owner.GetAccountData().AgentData.LoginNumber += 1
    elif mutation == "hero":
        cohort.children[0].GetAccountData().AgentData.HeroID += 1
    elif mutation == "witness":
        cohort.witnesses[0].revision += 1
    elif mutation == "build":
        hero = runtime.heroes[0]
        runtime.bars[hero.agent_id] = (77777,) * 8
    elif mutation == "freshness":
        runtime.uncached_now = int(runtime.publication_now) + 10_000
    elif mutation == "context":
        cache.CleansingContext = None
    else:
        read = cache.ShMem.GetNativeAccountSnapshotV3
        invoked = False

        def reenter() -> Any:
            nonlocal invoked
            if not invoked:
                invoked = True
                if mutation == "exception":
                    raise RuntimeError("PRIVATE final read failed")
                if mutation == "refresh":
                    context.Refresh()
                elif mutation == "invalidation":
                    context.Invalidate("offline final invalidation")
                elif mutation == "published_invalidation":
                    context.InvalidatePublishedSnapshot("offline final unavailability")
                elif mutation == "session":
                    context.SetStage3DecisionSession(object())
                elif mutation == "attempt":
                    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
                    recorder.end(probe._attempt_id)
            return read()

        monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", reenter)
    clock.advance(0.3)
    probe.update()
    output = capsys.readouterr().out
    assert "result=FULL_SUCCESS" not in output, (mutation, output)
    assert probe._terminal_outcome is not None and probe._terminal_outcome.result == "INCONCLUSIVE", (mutation, output)
    assert "PRIVATE" not in output
    if mutation not in ("refresh", "invalidation", "published_invalidation"):
        assert context.GetSnapshot() is snapshot and context.GetTransitionBoundary() is boundary, mutation


def test_stage3_owner_probe_final_verification_is_read_only_and_exactly_three_samples(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    before = (
        context.GetSnapshot(),
        context.GetTransitionBoundary(),
        dict(context._baselines),
        dict(context._remote_player_baselines),
        dict(context._remote_hero_origins),
        context._stage3_generation,
    )
    clock.advance(0.3)
    probe.update()
    output = capsys.readouterr().out
    assert "event=final result=FULL_SUCCESS reason=three_stable_destination_samples" in output, output
    assert "loading=1 samples=3/3" in output
    after = (
        context.GetSnapshot(),
        context.GetTransitionBoundary(),
        dict(context._baselines),
        dict(context._remote_player_baselines),
        dict(context._remote_hero_origins),
        context._stage3_generation,
    )
    assert before == after
    assert len(probe._accepted_destination_events) == 3
    assert len({event.snapshot.revision for event in probe._accepted_destination_events}) == 1
    assert len({event.boundary.completed_refresh for event in probe._accepted_destination_events}) == 3
    assert all(
        not context.OwnsStage3DecisionSession(event.decision.decision.session)
        for event in probe._accepted_destination_events
    )


@pytest.mark.parametrize("before_loading", (False, True))
def test_stage3_owner_probe_retirement_cannot_be_revived_in_one_batch(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    before_loading: bool,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    clock.advance(0.3)
    if before_loading:
        context.Invalidate("offline contradiction before Loading")
    runtime.ready, runtime.instance_type_override = False, 2
    context.Refresh()
    if not before_loading:
        context.Invalidate("offline contradiction after Loading")
    probe.update()
    output = capsys.readouterr().out
    assert probe._finished and probe._terminal_outcome.result == "INCONCLUSIVE"
    assert "result=FULL_SUCCESS" not in output


@pytest.mark.parametrize("fault", ("gap", "overflow", "replay", "future"))
def test_stage3_owner_probe_rejects_broken_owner_event_integrity(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    fault: str,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    cursor = probe._last_owner_sequence
    clock.advance(0.3)
    runtime.ready, runtime.instance_type_override = False, 2
    context.Refresh()
    records = context._stage3_evidence
    if fault == "gap":
        context._stage3_evidence = type(records)(
            (event for event in records if event.sequence != cursor + 1), maxlen=256
        )
    elif fault == "overflow":
        for _ in range(260):
            context.ObserveCurrentEnvironment()
    elif fault == "future":
        context._stage3_evidence = type(records)(
            (replace(event, observed_at=clock.read() + 1.0) if event.sequence > cursor else event for event in records),
            maxlen=256,
        )
    elif fault == "replay":
        read = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_ordered_events

        def replay(attempt: int, after: int) -> Any:
            batch = read(attempt, after)
            return replace(batch, events=(*batch.events, batch.events[0]))

        monkeypatch.setattr(diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS, "read_ordered_events", replay)
    probe.update()
    output = capsys.readouterr().out
    assert probe._finished and probe._terminal_outcome.result == "INCONCLUSIVE", (fault, output)
    assert "result=FULL_SUCCESS" not in output


def test_stage3_owner_probe_third_sample_then_invalidation_in_same_batch(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    context.InvalidatePublishedSnapshot("offline later evidence")
    clock.advance(0.3)
    probe.update()
    assert not probe._finished and probe._destination_samples == 0
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    output = capsys.readouterr().out
    assert "result=FULL_SUCCESS" not in output
    assert probe._terminal_outcome.result == "INCONCLUSIVE"


@pytest.mark.parametrize("delay", (60.0, 120.0))
def test_stage3_owner_probe_timely_admission_remains_historical_proof(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    delay: float,
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    _context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    clock.advance(delay)
    probe.update()
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result == "FULL_SUCCESS", output
    assert probe._admission_event.boundary.completed_at < probe._fixed_production_deadline < clock.read()


@pytest.mark.parametrize("elapsed", (59.999, 60.0, 60.001))
def test_stage3_owner_probe_production_deadline_is_fixed_and_exclusive(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    elapsed: float,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    runtime.ready, runtime.instance_type_override = False, 2
    context.Refresh()
    deadline = context.GetTransitionBoundary().deadline
    clock.advance(elapsed)
    probe.update()
    assert probe._finished == (elapsed >= 60.0), (elapsed, probe._terminal_outcome)
    if probe._finished:
        assert probe._terminal_outcome.result == "INCONCLUSIVE"
    assert context.GetTransitionBoundary().deadline == deadline
    assert "result=FULL_SUCCESS" not in capsys.readouterr().out


def test_stage3_owner_probe_loading_output_error_survives_intervening_unreadiness(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    clock.advance(0.3)
    runtime.ready, runtime.instance_type_override = False, 2
    context.Refresh()
    runtime.instance_type_override = None
    runtime.missing_map_contexts.add("world")
    clock.advance(0.1)
    context.Refresh()
    runtime.missing_map_contexts.clear()
    runtime.ready, runtime.outpost, runtime.explorable, runtime.map_id = True, False, True, 2
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    for _ in range(3):
        clock.advance(1.01)
        context.Refresh()

    def fail_loading_line(_event: Any) -> str:
        raise probe._CounterDisplayOverflow()

    monkeypatch.setattr(probe, "_loading_line", fail_loading_line)
    probe.update()
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result == "INCONCLUSIVE"
    assert probe._terminal_outcome.reason == "counter_display_overflow"
    assert "result=FULL_SUCCESS" not in output
    assert probe._sample_output_error == "counter_display_overflow"


@pytest.mark.parametrize("spacing,expected", ((0.999, 1), (1.0, 2), (1.001, 2)))
def test_stage3_owner_probe_sample_spacing_uses_completion_time_not_consumption_time(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    spacing: float,
    expected: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_outpost(harness)
    _probe_enter_loading(harness)
    _probe_enter_destination(harness)
    first = probe._accepted_destination_events[0]
    clock.value = first.boundary.completed_at + spacing
    context.Refresh()
    second = context._stage3_evidence[-1]
    assert second.boundary.completed_refresh > first.boundary.completed_refresh
    assert second.snapshot.revision == first.snapshot.revision
    clock.advance(5.0)
    probe.update()
    assert not probe._finished and probe._destination_samples == expected
    assert len(probe._accepted_destination_events) == expected


def test_stage3_owner_probe_final_native_reads_run_outside_commit_locks(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    read = cache.ShMem.GetNativeAccountSnapshotV3
    calls = 0
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS

    def inspect_locks() -> Any:
        nonlocal calls
        calls += 1
        assert not context._stage3_evidence_lock._is_owned()
        assert recorder._lock.acquire(blocking=False)
        recorder._lock.release()
        return read()

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", inspect_locks)
    clock.advance(0.3)
    probe.update()
    assert calls == 2 and probe._terminal_outcome.result == "FULL_SUCCESS"


@pytest.mark.parametrize("closing_read", (1, 4))
@pytest.mark.parametrize("raise_after", (False, True))
@pytest.mark.parametrize("passive_unavailable", (False, True))
def test_stage3_review_refresh_invalidation_discards_all_staged_results(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    closing_read: int,
    raise_after: bool,
    passive_unavailable: bool,
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    assert context._remote_hero_origins and any(b.witness_origin for b in context._baselines.values())
    if passive_unavailable:
        context._stage3_evidence_lock = None
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    completed = context._completed_refresh
    read = module._read_closing_state
    calls = 0
    invalidated = None

    def invalidate_after_read() -> Any:
        nonlocal calls, invalidated
        assert not context._recognition_commit_lock._is_owned()
        state = read()
        calls += 1
        if invalidated is None:
            assert not context.GetSnapshot().ready
            assert all(b.destination_map_id is None for b in context._remote_player_baselines.values())
            assert all(origin.destination_epoch is None for origin in context._remote_hero_origins.values())
        if calls == closing_read:
            invalidated = context.Invalidate("review regression explicit invalidation")
            assert not invalidated.ready and not context._baselines
            assert not context._remote_player_baselines and not context._remote_hero_origins
            if raise_after:
                raise RuntimeError("interrupted read")
        return state

    with monkeypatch.context() as patch:
        patch.setattr(module, "_read_closing_state", invalidate_after_read)
        result = context.Refresh()
    assert calls >= closing_read and result is invalidated is context.GetSnapshot()
    assert context._completed_refresh == completed
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED
    assert context.GetTransitionBoundary().destination is None
    assert context._stage3_closing_inputs is None and context._staged_evidence is None
    assert not context._baselines and not context._remote_player_baselines and not context._remote_hero_origins
    # A later destination continuation has fresh data, but cannot reacquire the
    # retired witness origins without a new qualified outpost lifecycle.
    continuation = context.Refresh()
    assert not context._remote_player_baselines and not context._remote_hero_origins
    assert all(
        m.role is module.CleansingRole.UNKNOWN
        for m in continuation.members
        if m.evidence_source in (module.EvidenceSource.REMOTE_PLAYER, module.EvidenceSource.REMOTE_HERO)
    )


def test_stage3_review_uninterrupted_refresh_commits_verified_completion(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    completed = context._completed_refresh
    snapshot = context.Refresh()
    assert snapshot.ready and all(m.role is not module.CleansingRole.UNKNOWN for m in snapshot.members)
    event = context.ReadStage3OwnerEvidence(0).events[-1]
    assert event.kind == "completion" and event.snapshot is snapshot and event.verification is not None
    assert event.boundary.completed_refresh == completed + 1
    assert event.boundary.phase is module.TransitionPhase.DESTINATION_VERIFIED


@pytest.mark.parametrize("change", ("incarnation", "owner", "witness", "lease", "clock", "invalidation", "session"))
def test_stage3_review_final_change_after_native_capture_cannot_freeze_success(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, change: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    native = cache.ShMem.GetNativeAccountSnapshotV3
    closing = module._read_closing_state
    captured = False
    changed = False

    def read_native() -> Any:
        nonlocal captured
        result = native()
        captured = True
        return result

    def change_during_runtime() -> Any:
        nonlocal changed
        state = closing()
        if captured and not changed:
            changed = True
            cohort = runtime.publication_result.snapshot.cohorts[0]
            if change == "incarnation":
                cohort.incarnation = bytes((99,)) + bytes(15)
            elif change == "owner":
                cohort.owner.GetAccountData().AgentData.LoginNumber += 1
            elif change == "witness":
                cohort.witnesses[0].revision += 1
            elif change in ("lease", "clock"):
                clock.advance(6.0)
                runtime.uncached_now = int(runtime.publication_now) + 6000
                if change == "clock":
                    runtime.publication_result.snapshot.captured_at_tick64 = runtime.uncached_now
            elif change == "invalidation":
                context.Invalidate("review final verification invalidation")
            else:
                context.SetStage3DecisionSession(object())
        return state

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", read_native)
    monkeypatch.setattr(module, "_read_closing_state", change_during_runtime)
    clock.advance(0.3)
    probe.update()
    output = capsys.readouterr().out
    assert captured and changed, change
    assert "result=FULL_SUCCESS" not in output, (change, output)
    assert probe._terminal_outcome is not None and probe._terminal_outcome.result != "FULL_SUCCESS"


@pytest.mark.parametrize("change", ("missing", "login", "agent", "both"))
@pytest.mark.parametrize("endpoint_missing", (False, True))
def test_stage3_review_local_owner_login_retirement_is_irreversible_and_scoped(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, change: str, endpoint_missing: bool
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    local_key = next(key for key, b in context._baselines.items() if b.witness_origin is not None)
    original = context._baselines[local_key]
    remote = dict(context._remote_player_baselines)
    _bounded_stage3_loading(runtime, context)
    missing = change == "missing"
    hero = next(h for h in runtime.heroes if h.owner_player_id == runtime.login_number)
    agent_id = hero.agent_id
    if endpoint_missing:
        hero.agent_id = 0
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    local = runtime.publication_result.snapshot.cohorts[1]
    if missing:
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[:1]
    if change in ("login", "both"):
        local.owner.GetAccountData().AgentData.LoginNumber = 111
    if change in ("agent", "both"):
        local.owner.GetAccountData().AgentData.AgentID = 1101
        for child in local.children:
            child.GetAccountData().AgentData.OwnerAgentID = 1101
    result = context.Refresh()
    assert next(m for m in result.members if m.identity.stable_key == local_key).role is module.CleansingRole.UNKNOWN
    assert (context._baselines.get(local_key) == original) is missing
    assert (local_key in context.GetTransitionBoundary().retired_members) is (not missing)
    assert set(context._remote_player_baselines) == set(remote)
    hero.agent_id = agent_id
    runtime.publication_now += 10
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    restored_owner = runtime.publication_result.snapshot.cohorts[1].owner.GetAccountData()
    assert restored_owner.AgentData.LoginNumber == runtime.login_number == 11
    assert restored_owner.AgentData.AgentID == runtime.agent_id == 1001
    restored = context.Refresh()
    assert (
        next(m for m in restored.members if m.identity.stable_key == local_key).role is not module.CleansingRole.UNKNOWN
    ) is missing
    assert (local_key in context.GetTransitionBoundary().retired_members) is (not missing)
    assert _remote_player_record(restored, module).role is module.CleansingRole.BIP


@pytest.mark.parametrize("gap", ("endpoint", "mapping", "removal", "identity", "expired"))
def test_stage3_review_local_hero_endpoint_waits_only_without_contradiction(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, gap: str
) -> None:
    runtime, module = cleansing_runtime
    context, clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    hero = next(h for h in runtime.heroes if h.owner_player_id == runtime.login_number)
    key = (module.MemberKind.HERO, runtime.login_number, hero.hero_id)
    original = context._baselines[key]
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    agent_id, hero_id = hero.agent_id, hero.hero_id
    if gap in ("endpoint", "expired"):
        hero.agent_id = 0
    elif gap == "mapping":
        runtime.hero_agent_by_position_override[1] = 0
    elif gap == "identity":
        hero.hero_id += 100
    else:
        runtime.heroes.remove(hero)
    pending = context.Refresh()
    retained = gap in ("endpoint", "mapping", "expired")
    assert (context._baselines.get(key) == original) is retained, (gap, pending, context._baselines)
    if gap != "removal":
        assert all(
            m.role is module.CleansingRole.UNKNOWN
            for m in pending.members
            if m.identity.kind is module.MemberKind.HERO and m.identity.owner_id == runtime.login_number
        )
    if gap == "removal":
        runtime.heroes.append(hero)
    hero.agent_id, hero.hero_id = agent_id, hero_id
    runtime.hero_agent_by_position_override.clear()
    if gap == "expired":
        clock[0] += 60.0
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    restored = context.Refresh()
    member = next(m for m in restored.members if m.identity.stable_key == key)
    assert (member.role is not module.CleansingRole.UNKNOWN) is (gap in ("endpoint", "mapping")), (gap, restored)


@pytest.mark.parametrize("build", ("contradictory", "matching", "incomplete", "stale", "unassociated"))
@pytest.mark.parametrize("endpoint", ("absent", "zero", "profession", "present"))
def test_stage3_review_remote_build_contradiction_survives_missing_endpoint(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, build: str, endpoint: str
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    key = next(iter(context._remote_player_baselines))
    local = dict(context._baselines)
    origins = set(context._remote_hero_origins)
    assert origins
    _bounded_stage3_loading(runtime, context)
    deadline = context.GetTransitionBoundary().deadline
    bars = None if build == "matching" else {22: _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)}
    if build == "incomplete":
        bars = {22: (0,) * 8}
    runtime.publication_result = _remote_publication(
        runtime, module, include_local=True, owner_skillbars=bars, age_ms=6000 if build == "stale" else 1
    )
    if build == "unassociated":
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[1:]
    elif build == "contradictory":
        runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData().AgentData.Profession = (
            int(module.Profession.Mesmer),
            0,
        )
    publication_tests = _load_source(
        monkeypatch, "remote_availability_publication_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    subject = publication_tests.build_publication_subject(monkeypatch)
    runtime.publication_result = _stage3_decode_retirement_publication(
        subject, publication_tests, runtime.publication_result, expected_cohorts=0 if build == "stale" else None
    )
    profession = runtime.professions[2001]
    if endpoint == "absent":
        runtime.unavailable_agents.add(2001)
    elif endpoint == "zero":
        runtime.local_agent_by_login[22] = 0
    elif endpoint == "profession":
        runtime.professions[2001] = 0
    pending = context.Refresh()
    assert (_remote_player_record(pending, module).role is module.CleansingRole.BIP) is (
        endpoint == "present" and build == "matching"
    )
    assert (key in context._remote_player_baselines) is (build != "contradictory")
    assert (key in context.GetTransitionBoundary().retired_members) is (build == "contradictory")
    if build == "contradictory":
        if endpoint != "present":
            assert (
                _remote_player_record(pending, module).reason
                == "remote published build contradicts its qualified baseline"
            )
        assert origins <= set(context.GetTransitionBoundary().retired_members)
        assert not context._remote_hero_origins
    assert set(context._baselines) == set(local)
    if build != "contradictory" and endpoint != "present":
        assert context.GetTransitionBoundary().deadline == deadline
        assert origins <= set(context._remote_hero_origins)
    runtime.unavailable_agents.clear()
    runtime.local_agent_by_login[22] = 2001
    runtime.professions[2001] = profession
    runtime.publication_now += 10
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    runtime.publication_result = _stage3_decode_retirement_publication(
        subject, publication_tests, runtime.publication_result
    )
    restored = context.Refresh()
    assert (_remote_player_record(restored, module).role is module.CleansingRole.BIP) is (build != "contradictory")
    assert (key in context.GetTransitionBoundary().retired_members) is (build == "contradictory")


def _stage3_decode_retirement_publication(
    subject: Any,
    publication_tests: Any,
    publication: Any,
    *,
    expected_cohorts: int | None = None,
    expected_status: str = "success",
) -> Any:
    """Round-trip the deterministic party through the owning Native v3 decoder."""
    snapshot = publication.snapshot
    envelope = publication_tests.envelope_v3(subject)
    for rows in (envelope.accounts, envelope.keys, envelope.owners):
        ctypes.memset(ctypes.addressof(rows), 0, ctypes.sizeof(rows))
    envelope.header.recovery_epoch = snapshot.recovery_epoch
    envelope.header.owner_count = len(snapshot.cohorts)
    live_count = 0
    for cohort in snapshot.cohorts:
        for record in (cohort.owner, *cohort.children):
            source = record.GetAccountData()
            row = envelope.accounts[record.slot_index]
            for name in (
                "SlotNumber",
                "AccountEmail",
                "IsSlotActive",
                "IsAccount",
                "IsHero",
                "IsPet",
                "IsNPC",
                "LastUpdated",
            ):
                setattr(row, name, getattr(source, name))
            for name in ("HWND", "EntityType", "LocalIndex"):
                setattr(row.Key, name, getattr(source.Key, name))
            for name in ("CharacterName", "AgentID", "OwnerAgentID", "HeroID", "LoginNumber"):
                setattr(row.AgentData, name, getattr(source.AgentData, name))
            row.AgentData.UUID[:] = source.AgentData.UUID
            row.AgentData.Profession[:] = source.AgentData.Profession
            for name in ("MapID", "Region", "District", "Language"):
                setattr(row.AgentData.Map, name, getattr(source.AgentData.Map, name))
            for skill, source_skill in zip(row.AgentData.Skillbar.Skills, source.AgentData.Skillbar.Skills):
                skill.Id = source_skill.Id
            row.AgentPartyData.PartyID = source.AgentPartyData.PartyID
            envelope.keys[record.slot_index] = row.Key
            live_count += 1
        meta = envelope.owners[cohort.owner.slot_index]
        meta.active = 1
        meta.instance_type = cohort.instance_type
        meta.instance_epoch = cohort.instance_epoch
        meta.published_tick = cohort.published_tick
        meta.incarnation[:] = cohort.incarnation
        meta.character_uuid[:] = cohort.character_uuid
        meta.witness_count = len(cohort.witnesses)
        for witness, source_witness in zip(meta.witnesses, cohort.witnesses):
            witness.kind = source_witness.kind.value
            for name in ("hero_id", "primary", "secondary", "observed_at_tick64", "revision", "outpost_epoch"):
                setattr(witness, name, getattr(source_witness, name))
            witness.skills[:] = source_witness.skills
    envelope.header.live_count = live_count
    result = publication_tests.decode_v3(subject, envelope, now=snapshot.captured_at_tick64)
    assert result.status.value == expected_status, result.reason
    if expected_status != "success":
        assert result.snapshot is None
        return result
    assert len(result.snapshot.cohorts) == (len(snapshot.cohorts) if expected_cohorts is None else expected_cohorts)
    return result


@pytest.mark.parametrize("contradiction", ("local_both", "remote_zero", "remote_profession", "unchanged"))
def test_stage3_retirement_bypasses_decoded_eight_member_probe(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, contradiction: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    publication_tests = _load_source(
        monkeypatch, "retirement_publication_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    subject = publication_tests.build_publication_subject(monkeypatch)
    reader = cache.ShMem.GetNativeAccountSnapshotV3

    def decoded_publication() -> Any:
        return _stage3_decode_retirement_publication(subject, publication_tests, reader())

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", decoded_publication)
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    _probe_enter_outpost(harness)
    assert len(context.GetSnapshot().members) == 8 and probe._outpost_baseline is not None
    local = {key: b for key, b in context._baselines.items() if b.witness_origin is not None}
    remote = dict(context._remote_player_baselines)
    origins = dict(context._remote_hero_origins)
    assert len(local) == 5 and len(remote) == len(origins) == 1
    _probe_enter_loading(harness)
    assert context.GetTransitionBoundary().loading.loading
    runtime.ready, runtime.instance_type_override = True, None
    runtime.map_id, runtime.outpost, runtime.explorable = 2, False, True
    runtime.unavailable_agents.clear()
    runtime.publication_now += 10
    runtime.publication_result = _remote_publication(
        runtime,
        module,
        include_local=True,
        owner_skillbars=(
            {22: _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)}
            if contradiction in ("remote_zero", "remote_profession")
            else None
        ),
    )
    if contradiction == "local_both":
        cohort = runtime.publication_result.snapshot.cohorts[1]
        publisher = next(iter(local.values())).witness_origin.publisher
        owner = cohort.owner.GetAccountData()
        assert (cohort.incarnation, cohort.character_uuid, owner.AccountEmail, owner.Key.HWND) == (
            publisher.incarnation,
            publisher.character_uuid,
            publisher.account_email,
            publisher.hwnd,
        )
        owner.AgentData.LoginNumber, owner.AgentData.AgentID = 111, 1101
        for child in cohort.children:
            child.GetAccountData().AgentData.OwnerAgentID = 1101
        assert runtime.login_number == 11 and runtime.local_agent_by_login[11] == 1001
    elif contradiction == "remote_zero":
        runtime.local_agent_by_login[22] = 0
    elif contradiction == "remote_profession":
        cohort = runtime.publication_result.snapshot.cohorts[0]
        owner = cohort.owner.GetAccountData()
        owner.AgentData.Profession = (int(module.Profession.Mesmer), 0)
        publisher = next(iter(remote.values())).publisher
        assert (cohort.incarnation, cohort.character_uuid, owner.AccountEmail, owner.Key.HWND) == (
            publisher.incarnation,
            publisher.character_uuid,
            publisher.account_email,
            publisher.hwnd,
        )
        assert runtime.local_agent_by_login[22] == owner.AgentData.AgentID == 4001
        runtime.professions[4001] = 0
        assert module._read_living_identity(sys.modules["Py4GWCoreLib"].Agent, 4001) == (22, 0, 0)
    upkeeper.main()
    contradicted = context.GetSnapshot()
    retired = set(context.GetTransitionBoundary().retired_members)
    retained_local = set(context._baselines)
    retained_remote = set(context._remote_player_baselines)
    retained_origins = set(context._remote_hero_origins)
    if contradiction != "unchanged":
        evidence = context.ReadStage3OwnerEvidence(0)
        assert not context.VerifyStage3Destination(
            evidence.events[-1], evidence.watermark, context._stage3_decision_session, lambda: True
        )
    recorder_events = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._refresh_events
    assert recorder_events[-1].owner.snapshot is contradicted
    clock.advance(0.3)
    probe.update()
    # Rebuild every row independently after restoring current ownership/mapping.
    runtime.local_agent_by_login[22] = 4001
    runtime.professions[4001] = int(module.Profession.Necromancer)
    runtime.publication_now += 10
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    owner = runtime.publication_result.snapshot.cohorts[1].owner.GetAccountData()
    assert (owner.AgentData.LoginNumber, owner.AgentData.AgentID) == (11, 1001)
    assert runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData().AgentData.AgentID == 4001
    for _ in range(4):
        _probe_sample_destination(harness)
    restored = context.GetSnapshot()
    if not probe._finished:
        clock.advance(181.0)
        probe.update()
    output = capsys.readouterr().out
    assert probe._finished and probe._terminal_outcome is not None, output
    if contradiction == "unchanged":
        assert probe._terminal_outcome.result == "FULL_SUCCESS", output
        assert not retired
        samples = probe._accepted_destination_events
        assert len(samples) == len({event.boundary.completed_refresh for event in samples}) == 3
        assert "stage4=FALLBACK u=2 fence=1" in output
    else:
        assert probe._terminal_outcome.result == "INCONCLUSIVE", output
        assert probe._terminal_outcome.reason == "production_transition_retired", output
        assert "result=FULL_SUCCESS" not in output, output
        if contradiction == "remote_profession":
            assert _remote_player_record(contradicted, module).reason == (
                "remote published build contradicts its qualified baseline"
            )
        affected = set(local) if contradiction == "local_both" else set(remote) | set(origins)
        assert affected <= retired
        assert all(
            m.role is module.CleansingRole.UNKNOWN for m in contradicted.members if m.identity.stable_key in affected
        )
        assert all(
            m.role is module.CleansingRole.UNKNOWN for m in restored.members if m.identity.stable_key in affected
        )
        if contradiction == "local_both":
            assert not set(local) & retained_local
            assert retained_remote == set(remote) and retained_origins == set(origins)
        else:
            assert not retained_remote and not retained_origins
            assert set(local) <= retained_local
        assert affected <= set(context.GetTransitionBoundary().retired_members)
        evidence = context.ReadStage3OwnerEvidence(0)
        assert not context.VerifyStage3Destination(
            evidence.events[-1], evidence.watermark, context._stage3_decision_session, lambda: True
        )


@pytest.mark.parametrize("publication", ("unchanged", "reassociated", "stale", "ambiguous", "wrong_context"))
def test_stage3_retirement_local_attribution_controls(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, publication: str
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    local = {key: b for key, b in context._baselines.items() if b.witness_origin is not None}
    _bounded_stage3_loading(runtime, context)
    if publication == "reassociated":
        runtime.agent_id = 1101
        runtime.local_agent_by_login[11] = 1101
        runtime.professions[1101] = runtime.professions[1001]
        runtime.bars[1101] = runtime.bars[1001]
    runtime.publication_result = _remote_publication(
        runtime, module, include_local=True, age_ms=6000 if publication == "stale" else 1
    )
    cohort = runtime.publication_result.snapshot.cohorts[1]
    if publication in ("stale", "ambiguous", "wrong_context"):
        owner = cohort.owner.GetAccountData()
        owner.AgentData.LoginNumber, owner.AgentData.AgentID = 111, 1101
        for child in cohort.children:
            child.GetAccountData().AgentData.OwnerAgentID = 1101
        if publication == "ambiguous":
            competitor = _remote_publication(runtime, module, include_local=True).snapshot.cohorts[1]
            competitor.incarnation = bytes((99,)) + bytes(15)
            runtime.publication_result.snapshot.cohorts += (competitor,)
        elif publication == "wrong_context":
            owner.AgentData.Map.MapID += 1
    snapshot = context.Refresh()
    matching = publication in ("unchanged", "reassociated")
    assert all(
        (member.role is not module.CleansingRole.UNKNOWN) is matching
        for member in snapshot.members
        if member.identity.stable_key in local
    )
    if publication == "ambiguous":
        # Competing claims are not ordinary absence; existing safety may retire.
        assert all(
            member.role is module.CleansingRole.UNKNOWN
            for member in snapshot.members
            if member.identity.stable_key in local
        )
        return
    assert not set(local) & set(context.GetTransitionBoundary().retired_members)
    if not matching:
        assert all(context._baselines.get(key) == baseline for key, baseline in local.items())
        runtime.publication_now += 10
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
        restored = context.Refresh()
        assert all(
            member.role is not module.CleansingRole.UNKNOWN
            for member in restored.members
            if member.identity.stable_key in local
        )


def _stage3_reassociate_remote_owner(runtime: Any, login: int = 222) -> None:
    player = next(player for player in runtime.players if player.login_number == 22)
    player.login_number = login
    runtime.local_agent_by_login[login] = runtime.local_agent_by_login.pop(22)
    runtime.player_names[login] = runtime.player_names.pop(22)
    for hero in runtime.heroes:
        if hero.owner_player_id == 22:
            hero.owner_player_id = login
            runtime.original_hero_builds[(login, hero.hero_id)] = runtime.original_hero_builds.pop((22, hero.hero_id))


def _stage3_historical_publication(runtime: Any, module: Any, publisher: Any, **kwargs: Any) -> Any:
    publication = _remote_publication(runtime, module, include_local=True, **kwargs)
    _preserve_publication_publisher_identity_for_probe(publication, publisher)
    return publication


@pytest.mark.parametrize(
    "scenario",
    ("r1_mapping", "r1_both", "r2_living", "reassociated", "unchanged", "mapping", "endpoint", "publication"),
)
def test_stage3_historical_ownership_decoded_eight_member_probe(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, scenario: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    publication_tests = _load_source(
        monkeypatch, "historical_ownership_publication_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    subject = publication_tests.build_publication_subject(monkeypatch)
    reader = cache.ShMem.GetNativeAccountSnapshotV3

    def decoded_publication() -> Any:
        result = _stage3_decode_retirement_publication(subject, publication_tests, reader())
        # Check the actual detached decoder output, including the adversarial IDs.
        for original, decoded in zip(runtime.publication_result.snapshot.cohorts, result.snapshot.cohorts):
            original_owner, decoded_owner = original.owner.GetAccountData(), decoded.owner.GetAccountData()
            assert decoded_owner.AgentData.LoginNumber == original_owner.AgentData.LoginNumber
            assert decoded_owner.AgentData.AgentID == original_owner.AgentData.AgentID
            assert tuple(decoded_owner.AgentData.Profession) == tuple(original_owner.AgentData.Profession)
            assert tuple(skill.Id for skill in decoded_owner.AgentData.Skillbar.Skills) == tuple(
                skill.Id for skill in original_owner.AgentData.Skillbar.Skills
            )
            assert (
                decoded.incarnation,
                decoded.character_uuid,
                decoded_owner.AccountEmail,
                decoded_owner.Key.HWND,
            ) == (original.incarnation, original.character_uuid, original_owner.AccountEmail, original_owner.Key.HWND)
        return result

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", decoded_publication)
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    _probe_enter_outpost(harness)
    local = {key: b for key, b in context._baselines.items() if b.witness_origin is not None}
    remote, origins = dict(context._remote_player_baselines), dict(context._remote_hero_origins)
    publisher = next(iter(remote.values())).publisher
    assert len(local) == 5 and len(remote) == len(origins) == 1 and len(context.GetSnapshot().members) == 8
    assert next(iter(remote))[1] == 22 and probe._outpost_baseline is not None
    _probe_enter_loading(harness)
    deadline = context.GetTransitionBoundary().deadline
    assert context.GetTransitionBoundary().loading.loading
    runtime.ready, runtime.instance_type_override = True, None
    runtime.map_id, runtime.outpost, runtime.explorable = 2, False, True
    runtime.unavailable_agents.clear()
    reassociated = scenario in ("r2_living", "reassociated")
    if reassociated:
        _stage3_reassociate_remote_owner(runtime)
    login = 222 if reassociated else 22
    invalid = scenario.startswith(("r1", "r2"))
    runtime.publication_now += 10
    runtime.publication_result = _stage3_historical_publication(
        runtime,
        module,
        publisher,
        owner_skillbars={login: _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)} if invalid else None,
    )
    cohort = runtime.publication_result.snapshot.cohorts[0]
    owner = cohort.owner.GetAccountData()
    assert (
        module._publisher_token(module._copy_published_cohorts(runtime.publication_result.snapshot)[0], 1) == publisher
    )
    assert owner.AgentData.AgentID == runtime.local_agent_by_login[login] == 4001
    if invalid:
        owner.AgentData.Profession = (int(module.Profession.Mesmer), 0)
        assert owner.AgentData.Profession[0] == 5
    if scenario == "r1_mapping":
        runtime.local_agent_by_login[22] = 0
        owner.AgentData.LoginNumber = 222
    elif scenario == "r1_both":
        runtime.unavailable_agents.add(4001)
        owner.AgentData.LoginNumber, owner.AgentData.AgentID = 222, 4444
        for child in cohort.children:
            child.GetAccountData().AgentData.OwnerAgentID = 4444
    elif scenario == "r2_living":
        runtime.living_login_override[4001] = 333
        runtime.professions[4001] = 0
        assert module._read_living_identity(sys.modules["Py4GWCoreLib"].Agent, 4001) == (333, 0, 0)
    elif scenario == "mapping":
        runtime.local_agent_by_login[22] = 0
    elif scenario == "endpoint":
        runtime.unavailable_agents.add(4001)
    elif scenario == "publication":
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[1:]
    upkeeper.main()
    pending = context.GetSnapshot()
    retired = context.GetTransitionBoundary().retired_members
    affected = set(remote) | set(origins)
    retained_remote, retained_origins = dict(context._remote_player_baselines), dict(context._remote_hero_origins)
    if scenario in ("mapping", "endpoint", "publication"):
        assert context._remote_player_baselines == remote and context._remote_hero_origins == origins
        assert context.GetTransitionBoundary().deadline == deadline
        assert _remote_player_record(pending, module).role is module.CleansingRole.UNKNOWN
    assert set(local) <= set(context._baselines)
    assert not set(local) & retired
    assert diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._refresh_events[-1].owner.snapshot is pending
    clock.advance(0.3)
    probe.update()
    # Restore by constructing every publication row afresh, with the qualified token.
    runtime.local_agent_by_login[login] = 4001
    runtime.unavailable_agents.clear()
    runtime.living_login_override.clear()
    runtime.professions[4001] = int(module.Profession.Necromancer)
    runtime.publication_now += 10
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    restored_owner = runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData()
    assert restored_owner is not owner
    assert (restored_owner.AgentData.LoginNumber, restored_owner.AgentData.AgentID) == (login, 4001)
    assert restored_owner.AgentData.Profession[0] == int(module.Profession.Necromancer)
    assert restored_owner.AgentData.Skillbar.Skills[0].Id == _skill_ids(runtime, module).blood_is_power
    for _ in range(4):
        _probe_sample_destination(harness)
    restored = context.GetSnapshot()
    if not probe._finished:
        clock.advance(181.0)
        probe.update()
    output = capsys.readouterr().out
    assert probe._finished and probe._terminal_outcome is not None, (scenario, output)
    if invalid:
        assert probe._terminal_outcome.result == "INCONCLUSIVE", (scenario, output)
        assert probe._terminal_outcome.reason == "production_transition_retired", (scenario, output)
        assert "result=FULL_SUCCESS" not in output
        assert affected <= retired, (scenario, retired, pending)
        assert not retained_remote and not retained_origins
        assert _remote_player_record(pending, module, login_number=login).role is module.CleansingRole.UNKNOWN
        assert _remote_player_record(pending, module, login_number=login).reason == (
            "remote player is not the expected living-agent login"
            if scenario == "r2_living"
            else "qualified remote publisher owner claims contradict the current roster"
        )
        assert (module.MemberKind.PLAYER, 222, 222) not in retired
        assert not context._remote_player_baselines and not context._remote_hero_origins
        assert affected <= context.GetTransitionBoundary().retired_members
        assert _remote_player_record(restored, module, login_number=login).role is module.CleansingRole.UNKNOWN
        evidence = context.ReadStage3OwnerEvidence(0)
        assert not context.VerifyStage3Destination(
            evidence.events[-1], evidence.watermark, context._stage3_decision_session, lambda: True
        )
    else:
        assert probe._terminal_outcome.result == "FULL_SUCCESS", (scenario, output)
        assert probe._terminal_outcome.reason == "three_stable_destination_samples"
        assert "loading=1 samples=3/3" in output and "stage4=FALLBACK u=2 fence=1" in output
        samples = probe._accepted_destination_events
        assert len(samples) == len({event.boundary.completed_refresh for event in samples}) == 3
        assert all(b.boundary.completed_at - a.boundary.completed_at >= 1.0 for a, b in zip(samples, samples[1:]))
        assert not context.GetTransitionBoundary().retired_members
        assert _remote_player_record(restored, module, login_number=login).role is module.CleansingRole.BIP


@pytest.mark.parametrize("admitted", (False, True), ids=("before_reassociation", "after_reassociation"))
@pytest.mark.parametrize(
    "conflict",
    (
        "invalid_login",
        "disconnected",
        "duplicate_login",
        "endpoint_collision",
        "local_endpoint",
        "living_login",
        "owner_login",
        "owner_agent",
        "profession",
        "name",
        "build",
        "destination_epoch",
        "competing_claim",
    ),
)
def test_stage3_historical_ownership_adjacent_retirement_callers(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, admitted: bool, conflict: str
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    _add_remote_player(runtime, module, login_number=33, agent_id=6001, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    context.Refresh()
    source_key = (module.MemberKind.PLAYER, 22, 22)
    unrelated_key = (module.MemberKind.PLAYER, 33, 33)
    publisher = context._remote_player_baselines[source_key].publisher
    origins = {key for key, origin in context._remote_hero_origins.items() if origin.publisher == publisher}
    assert origins and unrelated_key in context._remote_player_baselines
    _bounded_stage3_loading(runtime, context)
    _stage3_reassociate_remote_owner(runtime)
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    if admitted:
        assert _remote_player_record(context.Refresh(), module, login_number=222).role is module.CleansingRole.BIP
        assert source_key not in context._remote_player_baselines
        assert (module.MemberKind.PLAYER, 222, 222) in context._remote_player_baselines
    player = next(player for player in runtime.players if player.login_number == 222)
    cohort = runtime.publication_result.snapshot.cohorts[0]
    owner = cohort.owner.GetAccountData()
    if conflict == "invalid_login":
        player.login_number = 0
        runtime.local_agent_by_login.pop(222)
    elif conflict == "disconnected":
        player.is_connected = False
    elif conflict == "duplicate_login":
        runtime.players.append(types.SimpleNamespace(login_number=222, is_connected=True))
    elif conflict == "endpoint_collision":
        runtime.heroes[0].agent_id = 2001
    elif conflict == "local_endpoint":
        runtime.local_agent_by_login[222] = runtime.agent_id
        runtime.living_login_override[runtime.agent_id] = runtime.login_number
    elif conflict == "living_login":
        runtime.living_login_override[2001] = 333
        runtime.professions[2001] = 0
    elif conflict == "owner_login":
        owner.AgentData.LoginNumber = 444
    elif conflict == "owner_agent":
        owner.AgentData.AgentID = 4444
        for child in cohort.children:
            child.GetAccountData().AgentData.OwnerAgentID = 4444
    elif conflict == "profession":
        runtime.professions[2001] = int(module.Profession.Mesmer)
    elif conflict == "name":
        owner.AgentData.CharacterName = "Conflicting current name"
    elif conflict == "build":
        owner.AgentData.Skillbar.Skills = tuple(
            types.SimpleNamespace(Id=skill) for skill in _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)
        )
    elif conflict == "destination_epoch":
        if not admitted:
            # An initial destination epoch has no admitted epoch to contradict.
            # Use a context mismatch for the pre-admission caller instead.
            cohort.instance_type = 0
        else:
            cohort.instance_epoch += 1
    else:
        competitor = _remote_publication(runtime, module, include_local=True).snapshot.cohorts[0]
        runtime.publication_result.snapshot.cohorts += (competitor,)
    snapshot = context.Refresh()
    retired = context.GetTransitionBoundary().retired_members
    if conflict == "destination_epoch" and not admitted:
        assert source_key not in retired
        assert source_key in context._remote_player_baselines
        return
    assert source_key in retired and origins <= retired, (admitted, conflict, retired, snapshot)
    assert (module.MemberKind.PLAYER, 222, 222) not in retired, (admitted, conflict, retired)
    assert all(b.publisher != publisher for b in context._remote_player_baselines.values())
    assert all(origin.publisher != publisher for origin in context._remote_hero_origins.values())
    if conflict == "local_endpoint":
        assert not snapshot.ready and snapshot.reason == "controlled player changed during closing"
        assert not context._remote_player_baselines and not context._remote_hero_origins
        return
    assert unrelated_key in context._remote_player_baselines, (admitted, conflict, snapshot)
    assert unrelated_key not in retired
    assert _remote_player_record(snapshot, module, login_number=33).role is module.CleansingRole.PANIC


@pytest.mark.parametrize("gap", ("mapping", "endpoint", "publication"))
@pytest.mark.parametrize("reassociated", (False, True))
def test_stage3_historical_ownership_unavailability_preserves_source_and_fixed_deadline(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, gap: str, reassociated: bool
) -> None:
    runtime, module = cleansing_runtime
    context, clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    source_remote, source_origins = dict(context._remote_player_baselines), dict(context._remote_hero_origins)
    publisher = next(iter(source_remote.values())).publisher
    _bounded_stage3_loading(runtime, context)
    deadline = context.GetTransitionBoundary().deadline
    if reassociated:
        _stage3_reassociate_remote_owner(runtime)
    login = 222 if reassociated else 22
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    if gap == "mapping":
        runtime.local_agent_by_login[login] = 0
    elif gap == "endpoint":
        runtime.unavailable_agents.add(2001)
    else:
        runtime.publication_result.snapshot.cohorts = runtime.publication_result.snapshot.cohorts[1:]
    for _ in range(3):
        clock[0] += 1.01
        snapshot = context.Refresh()
        assert _remote_player_record(snapshot, module, login_number=login).role is module.CleansingRole.UNKNOWN
        assert context._remote_player_baselines == source_remote and context._remote_hero_origins == source_origins
        assert context.GetTransitionBoundary().deadline == deadline
        assert not context.GetTransitionBoundary().retired_members
    runtime.local_agent_by_login[login] = 2001
    runtime.unavailable_agents.clear()
    runtime.publication_now += 10
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    restored = context.Refresh()
    assert _remote_player_record(restored, module, login_number=login).role is module.CleansingRole.BIP
    assert not context.GetTransitionBoundary().retired_members


@pytest.mark.parametrize("scenario", ("r1", "r2"))
def test_stage3_historical_ownership_invalidation_discards_staged_retirement(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    publisher = next(iter(context._remote_player_baselines.values())).publisher
    source_keys = set(context._remote_player_baselines) | set(context._remote_hero_origins)
    _bounded_stage3_loading(runtime, context)
    if scenario == "r2":
        _stage3_reassociate_remote_owner(runtime)
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    if scenario == "r1":
        runtime.local_agent_by_login[22] = 0
        runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData().AgentData.LoginNumber = 222
    else:
        runtime.living_login_override[2001] = 333
        runtime.professions[2001] = 0
    evaluate = module.CleansingContext._evaluate_remote_players
    completed = context._completed_refresh
    invalidated = None

    def invalidate_after_evaluation(work: Any, **kwargs: Any) -> Any:
        nonlocal invalidated
        result = evaluate(work, **kwargs)
        assert work is not context and source_keys <= work._transition.retired
        assert not work._candidate_remote and not work._candidate_origins
        assert source_keys <= set(context._remote_player_baselines) | set(context._remote_hero_origins)
        invalidated = context.Invalidate("historical ownership retirement interrupted before commit")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(module.CleansingContext, "_evaluate_remote_players", invalidate_after_evaluation)
        snapshot = context.Refresh()
    assert snapshot is invalidated is context.GetSnapshot()
    assert not snapshot.ready and context._completed_refresh == completed
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED
    assert not context._remote_player_baselines and not context._remote_hero_origins
    assert context._stage3_closing_inputs is None and context._staged_evidence is None
    runtime.living_login_override.clear()
    runtime.local_agent_by_login[222 if scenario == "r2" else 22] = 2001
    runtime.professions[2001] = int(module.Profession.Necromancer)
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    restored = context.Refresh()
    assert (
        _remote_player_record(restored, module, login_number=222 if scenario == "r2" else 22).role
        is module.CleansingRole.UNKNOWN
    )
    assert not context._remote_player_baselines and not context._remote_hero_origins


@pytest.mark.parametrize(
    "change",
    (
        "unrelated",
        "incarnation",
        "recovery",
        "uuid",
        "account",
        "window",
        "duplicate",
        "competing",
        "stale",
        "malformed",
        "wrong_map",
        "wrong_party",
    ),
)
def test_stage3_historical_ownership_attribution_requires_exact_unambiguous_live_context(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    remote, origins = dict(context._remote_player_baselines), dict(context._remote_hero_origins)
    publisher = next(iter(remote.values())).publisher
    _bounded_stage3_loading(runtime, context)
    deadline = context.GetTransitionBoundary().deadline
    publication = _stage3_historical_publication(
        runtime,
        module,
        publisher,
        age_ms=6000 if change == "stale" else 1,
        owner_skillbars={22: _role_bar(runtime, module, module.CleansingRole.ENERGY_SURGE)},
    )
    cohort = publication.snapshot.cohorts[0]
    owner = cohort.owner.GetAccountData()
    owner.AgentData.LoginNumber, owner.AgentData.AgentID = 222, 4444
    owner.AgentData.Profession = (int(module.Profession.Mesmer), 0)
    for child in cohort.children:
        child.GetAccountData().AgentData.OwnerAgentID = 4444
    runtime.local_agent_by_login[22] = 0
    if change in ("incarnation", "unrelated"):
        cohort.incarnation = bytes((99,)) + bytes(15)
    if change == "recovery":
        publication.snapshot.recovery_epoch += 1
    if change in ("uuid", "unrelated"):
        cohort.character_uuid = (999, 8, 7, 6)
        owner.AgentData.UUID = cohort.character_uuid
    if change in ("account", "unrelated"):
        owner.AccountEmail = "unrelated@example.test"
        for child in cohort.children:
            child.GetAccountData().AccountEmail = owner.AccountEmail
    if change in ("window", "unrelated"):
        owner.Key.HWND = 9999
        for child in cohort.children:
            child.GetAccountData().Key.HWND = owner.Key.HWND
    if change == "malformed":
        cohort.character_uuid = (999, 0, 0, 0)
    elif change == "wrong_map":
        owner.AgentData.Map.MapID += 1
        for child in cohort.children:
            child.GetAccountData().AgentData.Map.MapID = owner.AgentData.Map.MapID
    elif change == "wrong_party":
        owner.AgentPartyData.PartyID += 1
        for child in cohort.children:
            child.GetAccountData().AgentPartyData.PartyID = owner.AgentPartyData.PartyID
    elif change in ("duplicate", "competing"):
        competitor = _stage3_historical_publication(runtime, module, publisher).snapshot.cohorts[0]
        competitor.owner.slot_index = 20
        competitor_owner = competitor.owner.GetAccountData()
        competitor_owner.SlotNumber = 20
        competitor_owner.AgentData.LoginNumber, competitor_owner.AgentData.AgentID = 222, 4444
        competitor_owner.Key.HWND += 100
        competitor_owner.AccountEmail = "competitor@example.test"
        competitor.children = ()
        competitor.witnesses = ()
        if change == "competing":
            competitor.incarnation = bytes((99,)) + bytes(15)
        publication.snapshot.cohorts += (competitor,)
    publication_tests = _load_source(
        monkeypatch, "historical_attribution_publication_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    subject = publication_tests.build_publication_subject(monkeypatch)
    invalid = change in ("malformed", "duplicate")
    runtime.publication_result = _stage3_decode_retirement_publication(
        subject,
        publication_tests,
        publication,
        expected_cohorts=0 if change == "stale" else None,
        expected_status="sync_failure" if invalid else "success",
    )
    if not invalid and change not in ("stale",):
        decoded = runtime.publication_result.snapshot.cohorts[0]
        decoded_owner = decoded.owner.GetAccountData()
        assert (decoded_owner.AgentData.LoginNumber, decoded_owner.AgentData.AgentID) == (222, 4444)
        assert tuple(decoded_owner.AgentData.Profession) == (int(module.Profession.Mesmer), 0)
    snapshot = context.Refresh()
    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN
    retained = change in ("unrelated", "stale", "wrong_map", "wrong_party")
    # Token changes and competing provenance retain the established fail-closed
    # retirement. Stale/context-unrelated data cannot manufacture a contradiction.
    assert bool(context._remote_player_baselines) is retained, (change, context.GetTransitionBoundary(), snapshot)
    assert bool(context._remote_hero_origins) is retained, (change, context.GetTransitionBoundary(), snapshot)
    if retained:
        assert context._remote_player_baselines == remote and context._remote_hero_origins == origins
        assert not context.GetTransitionBoundary().retired_members
        assert context.GetTransitionBoundary().deadline == deadline
    runtime.local_agent_by_login[22] = 2001
    runtime.publication_now += 10
    rebuilt = _stage3_historical_publication(runtime, module, publisher)
    assert rebuilt.snapshot.cohorts[0].owner.GetAccountData() is not owner
    runtime.publication_result = _stage3_decode_retirement_publication(subject, publication_tests, rebuilt)
    restored = context.Refresh()
    assert (_remote_player_record(restored, module).role is module.CleansingRole.BIP) is retained, (change, restored)


@pytest.mark.parametrize("admitted", (False, True))
@pytest.mark.parametrize("reverse", (False, True))
def test_stage3_historical_ownership_numeric_key_reuse_preserves_other_publisher(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, admitted: bool, reverse: bool
) -> None:
    runtime, module = cleansing_runtime
    context, _clock = _bounded_stage3_setup(runtime, module, monkeypatch, witnesses=True)
    other = _add_remote_player(runtime, module, login_number=222, agent_id=6001, role=module.CleansingRole.PANIC)
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    originals = {
        int(c.owner.GetAccountData().AgentData.AgentID): c for c in runtime.publication_result.snapshot.cohorts
    }
    context.Refresh()
    source_key = (module.MemberKind.PLAYER, 22, 22)
    other_source = (module.MemberKind.PLAYER, 222, 222)
    publisher = context._remote_player_baselines[source_key].publisher
    other_publisher = context._remote_player_baselines[other_source].publisher
    _bounded_stage3_loading(runtime, context)
    other.login_number = 333
    runtime.local_agent_by_login[333] = runtime.local_agent_by_login.pop(222)
    runtime.player_names[333] = runtime.player_names.pop(222)
    _stage3_reassociate_remote_owner(runtime)
    if reverse:
        runtime.players.reverse()
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    _preserve_remote_publishers_by_agent(runtime.publication_result.snapshot, originals)
    if admitted:
        snapshot = context.Refresh()
        assert _remote_player_record(snapshot, module, login_number=222).role is module.CleansingRole.BIP
        assert _remote_player_record(snapshot, module, login_number=333).role is module.CleansingRole.PANIC
    runtime.living_login_override[2001] = 444
    snapshot = context.Refresh()
    retired = context.GetTransitionBoundary().retired_members
    assert source_key in retired and other_source not in retired, (admitted, reverse, retired)
    assert all(b.publisher != publisher for b in context._remote_player_baselines.values())
    assert all(origin.publisher != publisher for origin in context._remote_hero_origins.values())
    assert context._remote_player_baselines[(module.MemberKind.PLAYER, 333, 333)].publisher == other_publisher
    assert _remote_player_record(snapshot, module, login_number=333).role is module.CleansingRole.PANIC
    runtime.living_login_override.clear()
    runtime.publication_now += 10
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    _preserve_remote_publishers_by_agent(runtime.publication_result.snapshot, originals)
    restored = context.Refresh()
    assert _remote_player_record(restored, module, login_number=222).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(restored, module, login_number=333).role is module.CleansingRole.PANIC
    assert other_source not in context.GetTransitionBoundary().retired_members


@pytest.mark.parametrize("gap", ("endpoint", "profession", "build"))
def test_stage3_historical_ownership_unavailable_owner_with_only_hero_origin(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, gap: str
) -> None:
    runtime, module = cleansing_runtime
    context = _outpost_witness_party(runtime, module, local_count=1)
    clock = [100.0]
    monkeypatch.setitem(
        sys.modules["Py4GWCoreLib"].Map.GetLoadingObservation.__globals__, "monotonic", lambda: clock[0]
    )
    monkeypatch.setattr(module, "_transition_clock", lambda: clock[0])
    runtime.bars[2001] = tuple(range(8000, 8008))
    runtime.publication_result = _remote_publication(runtime, module, include_local=True)
    context.Refresh()
    assert not context._remote_player_baselines and context._remote_hero_origins
    origins = dict(context._remote_hero_origins)
    publisher = next(iter(origins.values())).publisher
    _bounded_stage3_loading(runtime, context)
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    if gap == "endpoint":
        runtime.unavailable_agents.add(2001)
    elif gap == "profession":
        runtime.professions[2001] = 0
    else:
        runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData().AgentData.Skillbar.Skills = tuple(
            types.SimpleNamespace(Id=0) for _ in range(8)
        )
    snapshot = context.Refresh()
    assert _remote_player_record(snapshot, module).role is module.CleansingRole.UNKNOWN
    assert not context.GetTransitionBoundary().retired_members
    if gap == "build":
        # A fresh independently verified hero does not require a recognized owner bar.
        assert _remote_hero_record(snapshot, module).role is module.CleansingRole.ENERGY_SURGE
        assert all(
            origin.publisher == origins[key].publisher
            and origin.witness == origins[key].witness
            and origin.destination_epoch == 3
            for key, origin in context._remote_hero_origins.items()
        )
    else:
        assert context._remote_hero_origins == origins
    runtime.unavailable_agents.clear()
    runtime.professions[2001] = int(module.Profession.Necromancer)
    runtime.publication_result = _stage3_historical_publication(runtime, module, publisher)
    restored = context.Refresh()
    assert _remote_hero_record(restored, module).role is module.CleansingRole.ENERGY_SURGE


def _stage3_reciprocal_publication(runtime: Any, module: Any, publishers: dict[int, Any]) -> Any:
    publication = _remote_publication(runtime, module, include_local=True, omit_outpost_children=runtime.outpost)
    for cohort in publication.snapshot.cohorts:
        agent = int(cohort.owner.GetAccountData().AgentData.AgentID)
        publisher = publishers.get(agent)
        if publisher is not None:
            _preserve_publication_publisher_identity_for_probe(
                types.SimpleNamespace(snapshot=types.SimpleNamespace(cohorts=(cohort,))), publisher
            )
    return publication


def _stage3_reciprocal_setup(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, *, reverse: bool
) -> tuple[Any, ...]:
    runtime, module = cleansing_runtime
    clock = [100.0]
    monkeypatch.setattr(module, "_transition_clock", lambda: clock[0])
    monkeypatch.setitem(
        sys.modules["Py4GWCoreLib"].Map.GetLoadingObservation.__globals__, "monotonic", lambda: clock[0]
    )
    context = _outpost_witness_party(runtime, module, local_count=1)
    _setup_remote_hero(
        runtime,
        module,
        owner_login=222,
        owner_agent=6001,
        hero_id=8,
        hero_agent=7001,
        owner_role=module.CleansingRole.PANIC,
        hero_role=module.CleansingRole.ENERGY_SURGE,
    )
    _setup_remote_hero(
        runtime,
        module,
        owner_login=33,
        owner_agent=8001,
        hero_id=9,
        hero_agent=9001,
        owner_role=module.CleansingRole.INEPTITUDE,
        hero_role=module.CleansingRole.ENERGY_SURGE,
    )
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    publication_tests = _load_source(
        monkeypatch, "reciprocal_publication_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    subject = publication_tests.build_publication_subject(monkeypatch)
    source = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    publishers = {
        cohort.owner.agent_id: module._publisher_token(cohort, 1)
        for cohort in module._copy_published_cohorts(source.snapshot)
    }
    runtime.publication_result = _stage3_decode_retirement_publication(subject, publication_tests, source)
    snapshot = context.Refresh()
    assert snapshot.ready and len(snapshot.members) == 8
    assert len(context._remote_player_baselines) == len(context._remote_hero_origins) == 3
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.OUTPOST_READY
    source_baselines, source_origins = dict(context._remote_player_baselines), dict(context._remote_hero_origins)
    _bounded_stage3_loading(runtime, context)
    assert context.GetTransitionBoundary().loading.loading
    q = next(player for player in runtime.players if player.login_number == 222)
    q.login_number = 333
    runtime.local_agent_by_login[333] = runtime.local_agent_by_login.pop(222)
    runtime.player_names[333] = runtime.player_names.pop(222)
    for hero in runtime.heroes:
        if hero.owner_player_id == 222:
            hero.owner_player_id = 333
            runtime.original_hero_builds[(333, hero.hero_id)] = runtime.original_hero_builds.pop((222, hero.hero_id))
    _stage3_reassociate_remote_owner(runtime)
    if reverse:
        runtime.players.reverse()
    runtime.publication_now += 10
    destination = _stage3_reciprocal_publication(runtime, module, publishers)
    runtime.publication_result = _stage3_decode_retirement_publication(subject, publication_tests, destination)
    decoded = module._copy_published_cohorts(runtime.publication_result.snapshot)
    assert {cohort.owner.login_number for cohort in decoded} == {11, 222, 333, 33}
    assert all(module._publisher_token(cohort, 1) == publishers[cohort.owner.agent_id] for cohort in decoded)
    return context, clock, subject, publication_tests, publishers, source_baselines, source_origins


@pytest.mark.parametrize("admitted", (False, True), ids=("pre_admission", "post_admission"))
@pytest.mark.parametrize("reverse", (False, True), ids=("p_before_q", "q_before_p"))
def test_stage3_reciprocal_collision_retires_only_contradictory_q(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, admitted: bool, reverse: bool
) -> None:
    runtime, module = cleansing_runtime
    context, clock, subject, publication_tests, publishers, source, origins = _stage3_reciprocal_setup(
        cleansing_runtime, monkeypatch, reverse=reverse
    )
    p_key, q_key, r_key = ((module.MemberKind.PLAYER, login, login) for login in (22, 222, 33))
    p_origins = {key for key, origin in origins.items() if origin.publisher == publishers[2001]}
    q_origins = {key for key, origin in origins.items() if origin.publisher == publishers[6001]}
    r_origins = {key for key, origin in origins.items() if origin.publisher == publishers[8001]}
    assert source[p_key].publisher == publishers[2001] and source[q_key].publisher == publishers[6001]
    if admitted:
        before = context.Refresh()
        assert _remote_player_record(before, module, login_number=222).role is module.CleansingRole.BIP
        assert _remote_player_record(before, module, login_number=333).role is module.CleansingRole.PANIC
        assert not context.GetTransitionBoundary().retired_members
    runtime.living_login_override[6001] = 444
    completed = context._completed_refresh
    clock[0] += 1.01
    snapshot = context.Refresh()
    retired = context.GetTransitionBoundary().retired_members
    assert q_key in retired and q_origins <= retired, (admitted, reverse, retired)
    assert p_key not in retired and not p_origins & retired, (admitted, reverse, retired, snapshot)
    assert r_key not in retired and not r_origins & retired
    assert _remote_player_record(snapshot, module, login_number=222).role is module.CleansingRole.BIP
    assert _remote_hero_record(snapshot, module, owner=222, hero_id=7).role is module.CleansingRole.ENERGY_SURGE
    assert _remote_player_record(snapshot, module, login_number=333).role is module.CleansingRole.UNKNOWN
    assert _remote_hero_record(snapshot, module, owner=333, hero_id=8).role is module.CleansingRole.UNKNOWN
    assert _remote_player_record(snapshot, module, login_number=33).role is module.CleansingRole.INEPTITUDE
    assert context._remote_player_baselines[q_key].publisher == publishers[2001]
    assert all(b.publisher != publishers[6001] for b in context._remote_player_baselines.values())
    assert all(origin.publisher != publishers[6001] for origin in context._remote_hero_origins.values())
    assert context._completed_refresh == completed + 1
    evidence = context.ReadStage3OwnerEvidence(0)
    event = evidence.events[-1]
    assert event.kind == "completion" and event.snapshot is snapshot
    assert event.boundary.completed_refresh == completed + 1 and event.boundary.retired_members == retired
    assert not context.VerifyStage3Destination(
        event, evidence.watermark, context._stage3_decision_session, lambda: True
    )
    runtime.living_login_override.clear()
    old_owner = runtime.publication_result.snapshot.cohorts[0].owner.GetAccountData()
    for _ in range(3):
        runtime.publication_now += 10
        rebuilt = _stage3_reciprocal_publication(runtime, module, publishers)
        assert all(cohort.owner.GetAccountData() is not old_owner for cohort in rebuilt.snapshot.cohorts)
        runtime.publication_result = _stage3_decode_retirement_publication(subject, publication_tests, rebuilt)
        clock[0] += 1.01
        restored = context.Refresh()
        assert _remote_player_record(restored, module, login_number=222).role is module.CleansingRole.BIP
        assert _remote_hero_record(restored, module, owner=222, hero_id=7).role is module.CleansingRole.ENERGY_SURGE
        assert _remote_player_record(restored, module, login_number=333).role is module.CleansingRole.UNKNOWN
        assert _remote_hero_record(restored, module, owner=333, hero_id=8).role is module.CleansingRole.UNKNOWN
        assert {q_key, *q_origins} <= context.GetTransitionBoundary().retired_members
        assert not {p_key, r_key, *p_origins, *r_origins} & context.GetTransitionBoundary().retired_members


@pytest.mark.parametrize("reverse", (False, True))
def test_stage3_reciprocal_collision_publishers_can_exchange_source_keys_at_admission(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    runtime, module = cleansing_runtime
    context, clock, subject, publication_tests, publishers, _source, _origins = _stage3_reciprocal_setup(
        cleansing_runtime, monkeypatch, reverse=reverse
    )
    # P will own 222 and Q will own 22 at their first destination admission.
    # Both source numbers are reusable with independently proved current owners.
    next(player for player in runtime.players if player.login_number == 333).login_number = 22
    runtime.local_agent_by_login[22] = runtime.local_agent_by_login.pop(333)
    runtime.player_names[22] = runtime.player_names.pop(333)
    for hero in runtime.heroes:
        if hero.owner_player_id == 333:
            hero.owner_player_id = 22
            runtime.original_hero_builds[(22, hero.hero_id)] = runtime.original_hero_builds.pop((333, hero.hero_id))
    runtime.publication_now += 10
    runtime.publication_result = _stage3_decode_retirement_publication(
        subject, publication_tests, _stage3_reciprocal_publication(runtime, module, publishers)
    )
    clock[0] += 1.01
    reused = context.Refresh()
    assert _remote_player_record(reused, module, login_number=222).role is module.CleansingRole.BIP
    assert _remote_player_record(reused, module, login_number=22).role is module.CleansingRole.PANIC
    assert _remote_hero_record(reused, module, owner=222, hero_id=7).role is module.CleansingRole.ENERGY_SURGE
    assert _remote_hero_record(reused, module, owner=22, hero_id=8).role is module.CleansingRole.ENERGY_SURGE
    assert context._remote_player_baselines[(module.MemberKind.PLAYER, 222, 222)].publisher == publishers[2001]
    assert context._remote_player_baselines[(module.MemberKind.PLAYER, 22, 22)].publisher == publishers[6001]
    assert not context.GetTransitionBoundary().retired_members


@pytest.mark.parametrize("reverse", (False, True))
@pytest.mark.parametrize("gap", ("publication", "endpoint", "profession", "ambiguous_context"))
def test_stage3_reciprocal_collision_unresolved_owner_waits_without_retiring_p(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, reverse: bool, gap: str
) -> None:
    runtime, module = cleansing_runtime
    context, clock, subject, publication_tests, publishers, source, origins = _stage3_reciprocal_setup(
        cleansing_runtime, monkeypatch, reverse=reverse
    )
    p_key, q_key = ((module.MemberKind.PLAYER, login, login) for login in (22, 222))
    deadline = context.GetTransitionBoundary().deadline
    if gap in ("publication", "ambiguous_context"):
        raw = _stage3_reciprocal_publication(runtime, module, publishers)
        cohort = next(c for c in raw.snapshot.cohorts if c.owner.GetAccountData().AgentData.AgentID == 6001)
        if gap == "publication":
            raw.snapshot.cohorts = tuple(c for c in raw.snapshot.cohorts if c is not cohort)
        else:
            # Valid publication for another party cannot resolve Q's current ownership here.
            cohort.owner.GetAccountData().AgentPartyData.PartyID += 1
            for child in cohort.children:
                child.GetAccountData().AgentPartyData.PartyID += 1
        runtime.publication_result = _stage3_decode_retirement_publication(subject, publication_tests, raw)
    elif gap == "endpoint":
        runtime.unavailable_agents.add(6001)
    else:
        runtime.professions[6001] = 0
    for _ in range(2):
        clock[0] += 1.01
        snapshot = context.Refresh()
        assert _remote_player_record(snapshot, module, login_number=222).role is module.CleansingRole.UNKNOWN
        assert _remote_player_record(snapshot, module, login_number=333).role is module.CleansingRole.UNKNOWN
        assert context._remote_player_baselines[p_key] == source[p_key]
        assert context._remote_player_baselines[q_key] == source[q_key]
        assert not context.GetTransitionBoundary().retired_members, (reverse, gap, snapshot)
        assert all(
            context._remote_hero_origins.get(key) == origin for key, origin in origins.items() if key[1] in (22, 222)
        )
        assert context.GetTransitionBoundary().deadline == deadline
    runtime.unavailable_agents.clear()
    runtime.professions[6001] = int(module.Profession.Mesmer)
    runtime.publication_now += 10
    runtime.publication_result = _stage3_decode_retirement_publication(
        subject, publication_tests, _stage3_reciprocal_publication(runtime, module, publishers)
    )
    restored = context.Refresh()
    assert _remote_player_record(restored, module, login_number=222).role is module.CleansingRole.BIP
    assert _remote_player_record(restored, module, login_number=333).role is module.CleansingRole.PANIC
    assert not context.GetTransitionBoundary().retired_members


@pytest.mark.parametrize("reverse", (False, True))
@pytest.mark.parametrize("collision", ("publisher_login", "publisher_agent", "roster_login", "roster_agent"))
def test_stage3_reciprocal_collision_real_current_claims_remain_disqualifying(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, reverse: bool, collision: str
) -> None:
    runtime, module = cleansing_runtime
    context, _clock, subject, publication_tests, publishers, _source, origins = _stage3_reciprocal_setup(
        cleansing_runtime, monkeypatch, reverse=reverse
    )
    raw = _stage3_reciprocal_publication(runtime, module, publishers)
    q = next(c for c in raw.snapshot.cohorts if c.owner.GetAccountData().AgentData.AgentID == 6001)
    if collision == "publisher_login":
        q.owner.GetAccountData().AgentData.LoginNumber = 222
    elif collision == "publisher_agent":
        q.owner.GetAccountData().AgentData.AgentID = 2001
        for child in q.children:
            child.GetAccountData().AgentData.OwnerAgentID = 2001
    elif collision == "roster_login":
        next(player for player in runtime.players if player.login_number == 333).login_number = 222
    else:
        runtime.local_agent_by_login[333] = 2001
    runtime.publication_result = _stage3_decode_retirement_publication(subject, publication_tests, raw)
    snapshot = context.Refresh()
    assert all(
        member.role is module.CleansingRole.UNKNOWN
        for member in snapshot.members
        if member.identity.kind is module.MemberKind.PLAYER and member.identity.owner_id in (222, 333)
    ), (reverse, collision, snapshot)
    retired = context.GetTransitionBoundary().retired_members
    assert {(module.MemberKind.PLAYER, 22, 22), (module.MemberKind.PLAYER, 222, 222)} <= retired
    assert {key for key in origins if key[1] in (22, 222)} <= retired
    assert _remote_player_record(snapshot, module, login_number=33).role is module.CleansingRole.INEPTITUDE
    assert (module.MemberKind.PLAYER, 33, 33) not in retired
    assert all(
        b.publisher not in (publishers[2001], publishers[6001]) for b in context._remote_player_baselines.values()
    )


@pytest.mark.parametrize("reverse", (False, True))
def test_stage3_reciprocal_collision_retired_q_never_reserves_p_number_again(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    runtime, module = cleansing_runtime
    context, _clock, subject, publication_tests, publishers, _source, _origins = _stage3_reciprocal_setup(
        cleansing_runtime, monkeypatch, reverse=reverse
    )
    runtime.local_agent_by_login[222] = 0
    runtime.living_login_override[6001] = 444
    pending = context.Refresh()
    p_key, q_key = ((module.MemberKind.PLAYER, login, login) for login in (22, 222))
    assert p_key in context._remote_player_baselines and q_key in context.GetTransitionBoundary().retired_members
    assert _remote_player_record(pending, module, login_number=222).role is module.CleansingRole.UNKNOWN
    runtime.local_agent_by_login[222] = 2001
    # Q remains absent: its retirement is sufficient to release historical
    # occupancy, never sufficient to give Q fresh recognition or resurrect it.
    raw = _stage3_reciprocal_publication(runtime, module, publishers)
    raw.snapshot.cohorts = tuple(c for c in raw.snapshot.cohorts if c.owner.GetAccountData().AgentData.AgentID != 6001)
    runtime.publication_result = _stage3_decode_retirement_publication(subject, publication_tests, raw)
    restored = context.Refresh()
    assert _remote_player_record(restored, module, login_number=222).role is module.CleansingRole.BIP
    assert p_key not in context.GetTransitionBoundary().retired_members
    assert q_key in context.GetTransitionBoundary().retired_members
    assert context._remote_player_baselines[q_key].publisher == publishers[2001]


@pytest.mark.parametrize("reverse", (False, True))
def test_stage3_reciprocal_collision_invalidation_discards_staged_reassociation(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    runtime, module = cleansing_runtime
    context, _clock, subject, publication_tests, publishers, source, origins = _stage3_reciprocal_setup(
        cleansing_runtime, monkeypatch, reverse=reverse
    )
    runtime.living_login_override[6001] = 444
    completed = context._completed_refresh
    evaluate = module.CleansingContext._evaluate_remote_players
    invalidated = None

    def invalidate_after_evaluation(work: Any, **kwargs: Any) -> Any:
        nonlocal invalidated
        result = evaluate(work, **kwargs)
        assert work is not context
        assert work._candidate_remote[(module.MemberKind.PLAYER, 222, 222)].publisher == publishers[2001]
        assert all(b.publisher != publishers[6001] for b in work._candidate_remote.values())
        assert context._remote_player_baselines == source and context._remote_hero_origins == origins
        invalidated = context.Invalidate("reciprocal retirement/reassociation interrupted before commit")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(module.CleansingContext, "_evaluate_remote_players", invalidate_after_evaluation)
        snapshot = context.Refresh()
    assert snapshot is invalidated is context.GetSnapshot() and not snapshot.ready
    assert context._completed_refresh == completed
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.RETIRED
    assert not context._remote_player_baselines and not context._remote_hero_origins
    assert context._stage3_closing_inputs is None and context._staged_evidence is None
    runtime.living_login_override.clear()
    runtime.publication_result = _stage3_decode_retirement_publication(
        subject, publication_tests, _stage3_reciprocal_publication(runtime, module, publishers)
    )
    restored = context.Refresh()
    assert all(
        member.role is module.CleansingRole.UNKNOWN
        for member in restored.members
        if member.evidence_source in (module.EvidenceSource.REMOTE_PLAYER, module.EvidenceSource.REMOTE_HERO)
    )
    assert not context._remote_player_baselines and not context._remote_hero_origins


def _stage3_proof_lifetime_count_three(harness: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    context, _cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    # Stop only terminal dispatch so real owner completions can be counted before
    # later activity. Final verification and commitment remain production code.
    finish = probe._finish

    def defer_success(result: str, reason: str) -> None:
        if result != "FULL_SUCCESS":
            finish(result, reason)

    with monkeypatch.context() as patch:
        patch.setattr(probe, "_finish", defer_success)
        clock.advance(0.3)
        probe.update()
    assert probe._destination_samples == len(probe._accepted_destination_events) == 3
    assert probe._latest_destination_owner is probe._accepted_destination_events[-1]
    assert probe._terminal_outcome is None
    assert context.GetSnapshot().ready


@pytest.mark.parametrize("activity", ("none", "fourth", "many_refreshes", "benign", "many_observations", "mixed"))
@pytest.mark.parametrize("count_before_activity", (False, True))
def test_stage3_proof_lifetime_harmless_preverification_activity(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    activity: str,
    count_before_activity: bool,
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    if count_before_activity:
        _stage3_proof_lifetime_count_three(harness, monkeypatch)
    deadline = context.GetTransitionBoundary().deadline
    third = context._stage3_evidence[-1]
    for _ in range(4 if activity.startswith("many") else 1):
        clock.advance(0.1)
        if activity in ("fourth", "many_refreshes", "mixed"):
            upkeeper.main()
        if activity in ("benign", "many_observations", "mixed"):
            context.ObserveCurrentEnvironment()
    if activity in ("benign", "many_observations", "mixed"):
        assert context._stage3_closing_inputs is None
    clock.advance(0.3)
    probe.update()
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result == "FULL_SUCCESS", (activity, count_before_activity, output)
    samples = probe._accepted_destination_events
    assert len(samples) == 3 and samples[-1] is third
    assert len({event.boundary.completed_refresh for event in samples}) == 3
    assert len({event.snapshot.revision for event in (*samples, probe._latest_destination_owner)}) == 1
    assert context.GetTransitionBoundary().deadline == deadline
    assert probe._admission_event.boundary.completed_at < deadline
    assert "STAGE3_FINAL_VERIFY_DIAG_V1" not in output
    assert "samples=3/3" in output
    if activity in ("fourth", "many_refreshes", "mixed"):
        assert probe._latest_destination_owner.boundary.completed_refresh > third.boundary.completed_refresh


@pytest.mark.parametrize("activity", ("fourth", "benign"))
def test_stage3_proof_lifetime_original_five_witnesses_and_eight_member_fence(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, activity: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    runtime.unavailable_agents = {hero.agent_id for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    _probe_enter_outpost(harness)
    assert sum(b.witness_origin is not None for b in context._baselines.values()) == 5
    assert probe._outpost_baseline.witness_status == "available"
    _probe_enter_loading(harness)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    _probe_sample_destination(harness)
    clock.advance(1.01)
    upkeeper.main()
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    if activity == "fourth":
        upkeeper.main()
    else:
        context.ObserveCurrentEnvironment()
    clock.advance(0.3)
    probe.update()
    assert probe._terminal_outcome.result == "FULL_SUCCESS", capsys.readouterr().out
    assert len(context.GetSnapshot().members) == 8
    assert context.GetSnapshot().composition.status is module.CompositionStatus.FALLBACK


@pytest.mark.parametrize(
    "activity",
    (
        "contradiction",
        "incomplete",
        "unreadable",
        "ambiguous_identity",
        "ambiguous_then_valid",
        "incomplete_then_valid",
        "invalidate",
        "published_invalidation",
        "retired_then_matching",
        "second_loading",
        "other_destination",
        "session",
        "attempt",
        "overflow",
        "gap",
        "replaced_completion",
        "wrong_destination",
        "source_replaced",
        "history_replaced",
        "missing_inputs",
        "duplicate",
        "spacing",
        "lifecycle",
    ),
)
def test_stage3_proof_lifetime_later_invalid_authority_fails_closed(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, activity: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    samples = probe._accepted_destination_events
    latest = probe._latest_destination_owner
    process_events = True
    if activity == "contradiction":
        _queue_stage3_remote_player_contradiction(harness, module)
    elif activity in ("incomplete", "incomplete_then_valid"):
        original_bar = runtime.bars[runtime.heroes[0].agent_id]
        runtime.bars[runtime.heroes[0].agent_id] = (0,) * 8
        context.Refresh()
        if activity == "incomplete_then_valid":
            runtime.bars[runtime.heroes[0].agent_id] = original_bar
            context.Refresh()
    elif activity == "unreadable":
        runtime.missing_map_contexts.add("world")
        context.ObserveCurrentEnvironment()
    elif activity in ("ambiguous_identity", "ambiguous_then_valid"):
        observation = replace(context.CaptureEnvironment(), character_uuid=None)
        context.ObserveEnvironment(observation)
        if activity == "ambiguous_then_valid":
            context.Refresh()
    elif activity in ("invalidate", "retired_then_matching"):
        context.Invalidate("proof lifetime regression")
        if activity == "retired_then_matching":
            context.Refresh()
    elif activity == "published_invalidation":
        context.InvalidatePublishedSnapshot("proof lifetime unavailable")
    elif activity == "second_loading":
        runtime.ready, runtime.instance_type_override = False, 2
        context.ObserveCurrentEnvironment()
    elif activity == "other_destination":
        runtime.map_id += 1
        context.Refresh()
    elif activity == "session":
        context.SetStage3DecisionSession(object())
    elif activity == "attempt":
        diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.end(probe._attempt_id)
    elif activity == "overflow":
        for _ in range(260):
            context.ObserveCurrentEnvironment()
    elif activity == "gap":
        context.ObserveCurrentEnvironment()
        context._stage3_evidence.pop()
    else:
        process_events = False
        if activity == "replaced_completion":
            context._stage3_evidence[-1] = replace(latest)
        elif activity == "wrong_destination":
            probe._latest_destination_owner = replace(
                latest, boundary=replace(latest.boundary, destination=(99, 0, 0, 0))
            )
        elif activity == "source_replaced":
            probe._owner_source = replace(probe._owner_source)
        elif activity == "history_replaced":
            probe._accepted_destination_events = (replace(samples[0]), *samples[1:])
        elif activity == "missing_inputs":
            probe._accepted_destination_events = (replace(samples[0], verification=None), *samples[1:])
        elif activity == "duplicate":
            probe._accepted_destination_events = (samples[0], samples[0], samples[2])
        elif activity == "spacing":
            changed = replace(
                samples[1], boundary=replace(samples[1].boundary, completed_at=samples[0].boundary.completed_at)
            )
            probe._accepted_destination_events = (samples[0], changed, samples[2])
        elif activity == "lifecycle":
            context._boundary = replace(
                context._boundary, lifecycle_generation=context._boundary.lifecycle_generation + 1
            )
    if process_events:
        probe._process_owner_batch(context, False)
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result != "FULL_SUCCESS", (activity, output)
    assert "result=FULL_SUCCESS" not in output, (activity, output)
    assert probe._destination_samples == 0, activity


@pytest.mark.parametrize("anchor_activity", ("fourth", "benign"))
@pytest.mark.parametrize(
    "mutation",
    (
        "observation",
        "refresh",
        "invalidate",
        "session",
        "attempt",
        "context",
        "publisher",
        "uuid",
        "witness",
        "expiry",
        "exception",
    ),
)
def test_stage3_proof_lifetime_fresh_reads_reject_concurrent_mutation(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, anchor_activity: str, mutation: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    if anchor_activity == "fourth":
        context.Refresh()
    else:
        context.ObserveCurrentEnvironment()
    native = cache.ShMem.GetNativeAccountSnapshotV3
    calls = 0

    def reenter() -> Any:
        nonlocal calls
        result = native()
        calls += 1
        assert not context._recognition_commit_lock._is_owned()
        if calls == 1:
            if mutation == "observation":
                context.ObserveCurrentEnvironment()
            elif mutation == "refresh":
                context.Refresh()
            elif mutation == "invalidate":
                context.Invalidate("proof lifetime concurrent invalidation")
            elif mutation == "session":
                context.SetStage3DecisionSession(object())
            elif mutation == "attempt":
                recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
                recorder._active = replace(recorder._active)
            elif mutation == "context":
                cache.CleansingContext = module.CleansingContext()
            elif mutation == "publisher":
                runtime.publication_result.snapshot.cohorts[0].incarnation = bytes((99,)) + bytes(15)
            elif mutation == "uuid":
                runtime.local_uuid = (999, 0, 0, 0)
            elif mutation == "witness":
                runtime.publication_result.snapshot.cohorts[0].witnesses[0].revision += 1
            elif mutation == "expiry":
                runtime.uncached_now = int(runtime.publication_now) + 6000
            else:
                raise RuntimeError("PRIVATE proof lifetime read exception")
        return result

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", reenter)
    clock.advance(0.3)
    probe.update()
    output = capsys.readouterr().out
    assert calls >= 1, (anchor_activity, mutation, output)
    assert probe._terminal_outcome.result == "INCONCLUSIVE", (anchor_activity, mutation, output)
    assert probe._terminal_outcome.reason == "final_verification_failed"
    assert "result=FULL_SUCCESS" not in output and "PRIVATE" not in output
    assert output.count("STAGE3_FINAL_VERIFY_DIAG_V1") == 1


@pytest.mark.parametrize("logger_raises", (False, True))
@pytest.mark.parametrize(
    "fault,boundary,gate,native_reads",
    (
        ("probe", "probe", "three_distinct_samples_required", 0),
        ("recorder", "recorder", "attempt_expired_or_replaced", 0),
        ("binding", "owner", "current_binding", 0),
        ("retention", "evidence", "proof_not_retained", 0),
        ("runtime", "runtime", "runtime_changed", 1),
        ("native", "native", "INCARNATION", 1),
        ("concurrent", "commit", "owner_generation_changed", 2),
        ("recorder_concurrent", "recorder", "commit_session_or_attempt", 2),
        ("expiry", "native", "FINAL_LEASE", 2),
        ("native_exception", "native", "exception", 1),
        ("runtime_exception", "runtime", "exception", 0),
        ("reset_during_verify", "commit", "probe_binding_changed", 2),
    ),
)
def test_stage3_proof_lifetime_first_failure_diagnostic_is_bounded_and_passive(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    logger_raises: bool,
    fault: str,
    boundary: str,
    gate: str,
    native_reads: int,
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    third = probe._accepted_destination_events[-1]
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    if fault == "probe":
        probe._destination_samples = 2
    elif fault == "recorder":
        recorder.end(probe._attempt_id)
    elif fault == "binding":
        context._stage3_decision_result = None
    elif fault == "retention":
        old = probe._accepted_destination_events[0]
        context._stage3_evidence = type(context._stage3_evidence)(
            (replace(event) if event is old else event for event in context._stage3_evidence), maxlen=256
        )
    elif fault == "runtime":
        runtime.bars[runtime.heroes[0].agent_id] = (77777,) * 8
    elif fault == "native":
        runtime.publication_result.snapshot.cohorts[0].incarnation = bytes((99,)) + bytes(15)
    read_native = cache.ShMem.GetNativeAccountSnapshotV3
    read_runtime = module._read_closing_state
    calls = 0
    expired = False

    def native() -> Any:
        nonlocal calls
        calls += 1
        if fault == "native_exception":
            raise RuntimeError("PRIVATE Native exception")
        result = read_native()
        if calls == 1:
            if fault == "concurrent":
                context.ObserveCurrentEnvironment()
            elif fault == "recorder_concurrent":
                recorder._active = replace(recorder._active)
            elif fault == "reset_during_verify":
                probe._reset_destination_samples()
        return result

    def runtime_closing() -> Any:
        nonlocal expired
        if fault == "runtime_exception":
            raise RuntimeError("PRIVATE runtime exception")
        result = read_runtime()
        if fault == "expiry" and calls and not expired:
            expired = True
            runtime.uncached_now = int(runtime.publication_now) + 6000
        return result

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", native)
    monkeypatch.setattr(module, "_read_closing_state", runtime_closing)
    console = sys.modules["PySystem"].Console
    log = console.Log
    records: list[str] = []

    def log_failure(sender: str, message: str, level: Any) -> None:
        if message.startswith("STAGE3_FINAL_VERIFY_DIAG_V1 "):
            assert calls == native_reads, (fault, calls, message)
            assert probe._terminal_outcome is None, message
            assert probe._destination_samples == (0 if fault == "reset_during_verify" else 2 if fault == "probe" else 3)
            records.append(message)
            if logger_raises:
                raise RuntimeError("PRIVATE logger exception")
        log(sender, message, level)

    monkeypatch.setattr(console, "Log", log_failure)
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    assert probe._terminal_outcome.result == "INCONCLUSIVE"
    assert probe._terminal_outcome.reason == "final_verification_failed"
    assert probe._destination_samples == 0 and len(records) == 1, (fault, records)
    record = records[0]
    assert f"boundary={boundary} gate={gate} " in record, (fault, record)
    assert f"pre_samples={2 if fault == 'probe' else 3} " in record
    assert f"third={probe._counter_text(third.boundary.completed_refresh)} " in record
    assert len(record) <= 320 and "\n" not in record and "PRIVATE" not in record
    assert calls == native_reads
    clock.advance(1.01)
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    probe._retry_finalization()
    assert len(records) == 1 and calls == native_reads
    output = capsys.readouterr().out
    assert "result=FULL_SUCCESS" not in output and "PRIVATE" not in output
    if not logger_raises:
        assert output.index(record) < output.index("event=final ")


def test_stage3_proof_lifetime_frozen_success_retry_never_reverifies(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, cache, _upkeeper, probe, clock, _diagnostics, _runtime = harness
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    context.Refresh()
    context.ObserveCurrentEnvironment()
    _interrupt_stage3_finalization_output(monkeypatch, probe, "final_refused")
    probe._process_owner_batch(context, False)
    outcome, samples = probe._terminal_outcome, probe._accepted_destination_events
    assert outcome.result == "FULL_SUCCESS" and not probe._finished
    context.Invalidate("ordinary gameplay after terminal freeze")
    runtime.local_uuid = (999, 0, 0, 0)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("frozen success retried verification or collection")

    monkeypatch.setattr(context, "VerifyStage3Destination", forbidden)
    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", forbidden)
    monkeypatch.setattr(context, "Refresh", forbidden)
    clock.advance(181.0)
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    probe.update()
    assert probe._finished and probe._terminal_outcome is outcome
    assert probe._accepted_destination_events is samples and probe._destination_samples == 3
    output = capsys.readouterr().out
    assert output.count("event=final result=FULL_SUCCESS") == 1
    assert "STAGE3_FINAL_VERIFY_DIAG_V1" not in output


def _stage3_retention_harness(cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    publication_tests = _load_source(
        monkeypatch, "retention_publication_fixture", _REPO_ROOT / "tests/test_account_publication.py"
    )
    subject = publication_tests.build_publication_subject(monkeypatch)
    reader = cache.ShMem.GetNativeAccountSnapshotV3

    def decoded() -> Any:
        return _stage3_decode_retirement_publication(subject, publication_tests, reader())

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", decoded)
    runtime.unavailable_agents = {int(hero.agent_id) for hero in runtime.heroes}
    runtime.publication_result = _remote_publication(runtime, module, include_local=True, omit_outpost_children=True)
    _probe_enter_outpost(harness)
    assert len(context.GetSnapshot().members) == 8 and len(context._baselines) == 6
    assert len(context._remote_player_baselines) == 1
    assert sum(b.witness_origin is not None for b in context._baselines.values()) == 5
    assert probe._outpost_baseline.witness_status == "available"
    return harness


def _stage3_retention_observations(harness: Any, count: int) -> None:
    context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    for index in range(count):
        context.ObserveCurrentEnvironment()
        probe._process_owner_batch(context, False)
        assert probe._terminal_outcome is None, (index, probe._terminal_outcome)


@pytest.mark.parametrize("count", (0, 257, 280))
def test_stage3_retention_original_source_survives_drained_history_eviction(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, count: int
) -> None:
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, _cache, _upkeeper, probe, _clock, _diagnostics, runtime = harness
    source = probe._owner_source
    _stage3_retention_observations(harness, count)
    if count:
        assert not any(event is source for event in context._stage3_evidence)
    _probe_enter_loading(harness)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    _probe_sample_destination(harness)
    _probe_sample_destination(harness)
    output = capsys.readouterr().out
    failure = next((line for line in output.splitlines() if line.startswith("STAGE3_FINAL_VERIFY_DIAG_V1")), "none")
    assert probe._terminal_outcome.result == "FULL_SUCCESS", (count, failure, probe._terminal_outcome)
    assert len(probe._accepted_destination_events) == 3
    assert context.GetSnapshot().composition.status.value == "FALLBACK"
    assert "stage4=FALLBACK u=2 fence=1" in output
    assert "STAGE3_FINAL_VERIFY_DIAG_V1" not in output


@pytest.mark.parametrize("pressure_after_sample", (1, 2, 3))
@pytest.mark.parametrize("extra_completions", (False, True))
def test_stage3_retention_counted_proofs_and_latest_survive_eviction(
    cleansing_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
    pressure_after_sample: int,
    extra_completions: bool,
) -> None:
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, _cache, upkeeper, probe, clock, _diagnostics, runtime = harness
    _probe_enter_loading(harness)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    finish = probe._finish

    def defer_success(result: str, reason: str) -> None:
        if result != "FULL_SUCCESS":
            finish(result, reason)

    with monkeypatch.context() as patch:
        patch.setattr(probe, "_finish", defer_success)
        for _ in range(pressure_after_sample - 1):
            _probe_sample_destination(harness)
        original = probe._accepted_destination_events
        for _ in range(280):
            if extra_completions:
                upkeeper.main()
            else:
                context.ObserveCurrentEnvironment()
            probe._process_owner_batch(context, False)
            retention = context._stage3_proof_retention
            assert retention is not None and len(retention.anchors) <= 7
            assert probe._terminal_outcome is None
        assert not any(event is original[0] for event in context._stage3_evidence)
        while probe._destination_samples < 3:
            _probe_sample_destination(harness)
    before = context.GetTransitionBoundary()
    clock.advance(0.3)
    probe.update()
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result == "FULL_SUCCESS", (pressure_after_sample, extra_completions, output)
    assert context.GetTransitionBoundary() is before, "final verification manufactured a completion"
    assert all(first is second for first, second in zip(original, probe._accepted_destination_events))
    assert context._stage3_proof_retention is None


@pytest.mark.parametrize("fault", ("overflow", "gap", "replay_cursor", "replaced_source", "too_many_anchors"))
def test_stage3_retention_cannot_acknowledge_missing_or_forged_authority(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, fault: str
) -> None:
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    source, cursor = probe._owner_source, probe._last_owner_sequence
    session = recorder._decision_session
    context.ObserveCurrentEnvironment()
    if fault == "overflow":
        for _ in range(280):
            context.ObserveCurrentEnvironment()
    elif fault == "gap":
        context._stage3_evidence.pop()
    elif fault == "replay_cursor":
        cursor -= 1
    elif fault == "replaced_source":
        source = replace(source)
    history = (source,) * (8 if fault == "too_many_anchors" else 1)
    assert not context.RetainStage3Proofs(
        session, probe._attempt_id, cursor, context._stage3_evidence_sequence, history, (), None, lambda: True
    ), fault
    probe.on_disable()
    assert context._stage3_proof_retention is None and recorder._active is None
    assert "result=FULL_SUCCESS" not in capsys.readouterr().out


@pytest.mark.parametrize("fault", ("ambiguous", "incomplete", "retirement", "invalidation", "publisher", "witness"))
def test_stage3_retention_disqualification_survives_eviction_and_matching_recovery(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, fault: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    _probe_enter_loading(harness)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    _probe_sample_destination(harness)
    clock.advance(1.01)
    upkeeper.main()
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    samples = probe._accepted_destination_events
    if fault == "ambiguous":
        context.ObserveEnvironment(replace(context.CaptureEnvironment(), character_uuid=None))
    elif fault == "incomplete":
        agent = runtime.heroes[0].agent_id
        bar = runtime.bars[agent]
        runtime.bars[agent] = (0,) * 8
        context.Refresh()
        runtime.bars[agent] = bar
    elif fault == "retirement":
        context.ObserveEnvironment(replace(context.CaptureEnvironment(), cinematic=True))
    elif fault == "invalidation":
        context.Invalidate("retained original proof invalidated")
    elif fault == "publisher":
        runtime.publication_result.snapshot.cohorts[0].incarnation = bytes((99,)) + bytes(15)
        context.Refresh()
    elif fault == "witness":
        runtime.publication_result.snapshot.cohorts[0].witnesses[0].revision += 1
        context.Refresh()
    disqualification = context._stage3_evidence[-1]
    # Leave an ambiguous observation to the owner streak reduction: the probe's
    # ordinary observation path does not classify its missing UUID as terminal.
    if fault == "ambiguous":
        finish = probe._finish

        def defer_success(result: str, reason: str) -> None:
            if result != "FULL_SUCCESS":
                finish(result, reason)

        with monkeypatch.context() as patch:
            patch.setattr(probe, "_finish", defer_success)
            probe._process_owner_batch(context, False)
            assert not context._stage3_proof_retention.streak_valid
            context.Refresh()
            _stage3_retention_observations(harness, 280)
            assert not context._stage3_proof_retention.streak_valid
    else:
        probe._process_owner_batch(context, False)
        runtime.publication_result = _remote_publication(runtime, module, include_local=True)
        context.Refresh()
        for _ in range(280):
            context.ObserveCurrentEnvironment()
    assert not any(event is disqualification for event in context._stage3_evidence)
    probe._accepted_destination_events = samples
    probe._destination_samples = 3
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result != "FULL_SUCCESS", (fault, output)
    assert "result=FULL_SUCCESS" not in output


@pytest.mark.parametrize("replacement", ("context", "session", "attempt", "expiry", "disable"))
def test_stage3_retention_cleanup_revokes_discarded_proof(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    _runtime, module = cleansing_runtime
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    source, attempt, session = probe._owner_source, probe._attempt_id, recorder._decision_session
    if replacement == "context":
        cache.CleansingContext = module.CleansingContext()
        probe._process_owner_batch(cache.CleansingContext, False)
    elif replacement == "session":
        context.SetStage3DecisionSession(object())
        recorder.active_attempt_id(context)
    elif replacement == "attempt":
        evidence = recorder.capture_snapshot(context, context.GetSnapshot())
        assert recorder.begin(context, evidence) != attempt
    elif replacement == "expiry":
        clock.value = probe._started_at + 180.0
        context.ReadStage3OwnerEvidence(probe._last_owner_sequence)
        recorder.active_attempt_id(context)
    else:
        probe.on_disable()
    assert context._stage3_proof_retention is None or context._stage3_proof_retention.session is not session
    assert not context.RetainStage3Proofs(
        session, attempt, source.sequence, context._stage3_evidence_sequence, (source,), (), None, lambda: True
    ), replacement
    recorder.end(recorder._active.attempt_id if recorder._active is not None else attempt)
    assert context._stage3_proof_retention is None


def test_stage3_retention_repeated_activation_disable_has_fixed_memory_bound(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, _cache, upkeeper, probe, clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    for _ in range(20):
        assert len(context._stage3_proof_retention.anchors) == 1
        probe.on_disable()
        assert context._stage3_proof_retention is None and recorder._active is None
        assert not recorder._events and not recorder._refresh_events
        clock.advance(0.3)
        probe.on_enable()
        upkeeper.main()
        probe.update()
        assert len(context._stage3_evidence) <= 256
    probe.on_disable()


@pytest.mark.parametrize(
    "fault", ("none", "unavailable", "incomplete", "unknown", "arm", "context", "session", "source")
)
def test_stage3_ready_to_zone_uses_only_saved_attempt_authority(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, fault: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    upkeeper.main()
    if fault in ("unavailable", "incomplete", "unknown"):
        witness = probe._OutpostWitnessEvidence(
            "unavailable" if fault == "unavailable" else "available",
            module.CleansingRole.UNKNOWN if fault == "unknown" else module.CleansingRole.ENERGY_SURGE,
            fault != "incomplete",
        )

        def saved_witness(*_args: Any) -> Any:
            return witness

        monkeypatch.setattr(probe, "_outpost_witness_evidence", saved_witness)
    elif fault == "arm":

        def refuse_arm(*_args: Any) -> None:
            return None

        monkeypatch.setattr(context, "ArmStage3Outpost", refuse_arm)
    elif fault in ("context", "session", "source"):
        report = probe._report_outpost

        def replace_during_report(*args: Any) -> bool:
            result = report(*args)
            if fault == "context":
                cache.CleansingContext = module.CleansingContext()
            elif fault == "session":
                context.SetStage3DecisionSession(object())
            else:
                context._stage3_evidence[-1] = replace(context._stage3_evidence[-1])
            return result

        monkeypatch.setattr(probe, "_report_outpost", replace_during_report)
    native = cache.ShMem.GetNativeAccountSnapshotV3
    calls = 0

    def read() -> Any:
        nonlocal calls
        calls += 1
        return native()

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", read)
    boundary = context.GetTransitionBoundary()
    start = clock.read()
    probe.update()
    output = capsys.readouterr().out
    if fault == "none":
        assert output.count("event=ready_to_zone ") == 1, output
        assert "event=outpost created roster=8/8" in output
        assert clock.read() == start, "readiness waited for an unrelated local witness diagnostic"
        assert context.GetTransitionBoundary() is boundary and probe._destination_samples == 0
        assert calls == 1, "readiness queried Native beyond the existing original witness read"
        for _ in range(3):
            clock.advance(0.3)
            probe.update()
        assert "event=ready_to_zone " not in capsys.readouterr().out
    else:
        assert "event=ready_to_zone " not in output, (fault, output)
        if fault == "arm":
            clock.advance(10.0)
            probe.update()
            output += capsys.readouterr().out
        assert output.count("event=no_go ") == 1, (fault, output)
        if fault in ("unavailable", "incomplete", "unknown"):
            assert probe._outpost_baseline is not None, "created baseline meaning changed"
            upkeeper.main()
            clock.advance(2.1)
            probe.update()
            assert "event=ready_to_zone " not in capsys.readouterr().out
    probe.on_disable()


@pytest.mark.parametrize("fault", ("witness", "publisher", "freshness", "unavailable", "runtime", "reentrant"))
def test_stage3_retention_evicted_anchors_still_require_fresh_verification(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, fault: str
) -> None:
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, cache, upkeeper, probe, clock, _diagnostics, runtime = harness
    _stage3_retention_observations(harness, 280)
    assert not any(event is probe._owner_source for event in context._stage3_evidence)
    _probe_enter_loading(harness)
    runtime.unavailable_agents.clear()
    _probe_enter_destination(harness, include_local=True)
    _probe_sample_destination(harness)
    clock.advance(1.01)
    upkeeper.main()
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    if fault == "witness":
        runtime.publication_result.snapshot.cohorts[0].witnesses[0].revision += 1
    elif fault == "publisher":
        runtime.publication_result.snapshot.cohorts[0].incarnation = bytes((99,)) + bytes(15)
    elif fault == "freshness":
        runtime.uncached_now = int(runtime.publication_now) + 6000
    elif fault == "runtime":
        runtime.bars[runtime.heroes[0].agent_id] = (77777,) * 8
    native = cache.ShMem.GetNativeAccountSnapshotV3
    calls = 0

    def read() -> Any:
        nonlocal calls
        calls += 1
        assert not context._recognition_commit_lock._is_owned()
        if fault == "unavailable":
            return types.SimpleNamespace(status=types.SimpleNamespace(value="busy"), snapshot=None)
        result = native()
        if fault == "reentrant" and calls == 1:
            context.ObserveCurrentEnvironment()
        return result

    monkeypatch.setattr(cache.ShMem, "GetNativeAccountSnapshotV3", read)
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    output = capsys.readouterr().out
    assert calls >= 1 and probe._terminal_outcome.result == "INCONCLUSIVE", (fault, output)
    assert probe._terminal_outcome.reason == "final_verification_failed"
    assert output.count("STAGE3_FINAL_VERIFY_DIAG_V1") == 1
    assert "result=FULL_SUCCESS" not in output
    assert context._stage3_proof_retention is None


@pytest.mark.parametrize(
    "fault", ("source", "transition", "destination", "lifecycle", "sample_session", "latest_session")
)
def test_stage3_retention_exact_association_cannot_be_replaced(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, fault: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    if fault == "source":
        probe._owner_source = replace(probe._owner_source)
    elif fault in ("transition", "destination", "lifecycle"):
        changes = {
            "transition": {"transition_id": context._boundary.transition_id + 1},
            "destination": {"destination": (999, 0, 0, 0)},
            "lifecycle": {"lifecycle_generation": context._boundary.lifecycle_generation + 1},
        }
        context._boundary = replace(context._boundary, **changes[fault])
    else:
        event = probe._accepted_destination_events[0] if fault == "sample_session" else probe._latest_destination_owner
        decision = replace(event.decision, decision=replace(event.decision.decision, session=object()))
        changed = replace(event, decision=decision)
        if fault == "sample_session":
            probe._accepted_destination_events = (changed, *probe._accepted_destination_events[1:])
        else:
            probe._latest_destination_owner = changed
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result != "FULL_SUCCESS", (fault, output)
    assert "result=FULL_SUCCESS" not in output


def test_stage3_retention_missing_completion_decision_cannot_be_hidden_by_later_success(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    runtime, module = cleansing_runtime
    harness = _stage3_owner_probe_candidate(runtime, module, monkeypatch)
    context, _cache, _upkeeper, probe, _clock, _diagnostics, _runtime = harness
    _stage3_proof_lifetime_count_three(harness, monkeypatch)
    finish = probe._finish

    def defer_success(result: str, reason: str) -> None:
        if result != "FULL_SUCCESS":
            finish(result, reason)

    def fail_decision(*_args: Any) -> None:
        raise RuntimeError("offline decision capture failure")

    with monkeypatch.context() as patch:
        patch.setattr(context, "_stage3_complete_decision", fail_decision)
        context.Refresh()
    with monkeypatch.context() as patch:
        patch.setattr(probe, "_finish", defer_success)
        probe._process_owner_batch(context, False)
        context.Refresh()
        _stage3_retention_observations(harness, 280)
        assert not context._stage3_proof_retention.streak_valid
    probe._finish("FULL_SUCCESS", "three_stable_destination_samples")
    output = capsys.readouterr().out
    assert probe._terminal_outcome.result == "INCONCLUSIVE", output
    assert "gate=incompatible_observation" in output


@pytest.mark.parametrize("fault", ("missing_uuid", "unread_gap"))
def test_stage3_retention_arming_accounts_for_the_source_to_activation_tail(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any, fault: str
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    upkeeper.main()
    if fault == "missing_uuid":
        context.ObserveEnvironment(replace(context.CaptureEnvironment(), character_uuid=None))
    else:
        context.ObserveCurrentEnvironment()
        context._stage3_evidence.pop()
    probe.update()
    assert probe._attempt_id is None and context._stage3_proof_retention is None
    clock.advance(10.0)
    probe.update()
    output = capsys.readouterr().out
    assert "event=ready_to_zone " not in output and "event=no_go " in output


def test_stage3_ready_to_zone_no_go_logger_failure_cannot_prevent_disable_cleanup(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, _cache, _upkeeper, probe, _clock, diagnostics, _runtime = harness
    assert context._stage3_proof_retention is not None
    probe._readiness_reported = False  # Inject a pending readiness delivery.
    console = sys.modules["PySystem"].Console
    log = console.Log

    def fail_no_go(sender: str, message: str, level: Any) -> None:
        if "event=no_go " in message:
            raise RuntimeError("offline readiness logger failure")
        log(sender, message, level)

    monkeypatch.setattr(console, "Log", fail_no_go)
    probe.on_disable()
    assert probe._terminal_outcome.result == "INCONCLUSIVE" and probe._finished
    assert context._stage3_proof_retention is None and diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS._active is None


@pytest.mark.parametrize("revocation", ("already_started", "gap", "invalidation", "expiry"))
def test_stage3_retention_cannot_renew_or_resurrect_in_the_same_session(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, revocation: str
) -> None:
    harness = _stage3_retention_harness(cleansing_runtime, monkeypatch)
    context, _cache, _upkeeper, probe, clock, diagnostics, _runtime = harness
    recorder = diagnostics.STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
    session, attempt, source = recorder._decision_session, probe._attempt_id, probe._owner_source
    if revocation == "gap":
        context.ObserveCurrentEnvironment()
        context._stage3_evidence.pop()
        assert not context.RetainStage3Proofs(
            session,
            attempt,
            probe._last_owner_sequence,
            context._stage3_evidence_sequence,
            (source,),
            (),
            None,
            lambda: True,
        )
    elif revocation == "invalidation":
        context.Invalidate("retention revocation")
    elif revocation == "expiry":
        clock.advance(180.0)
        context.ReadStage3OwnerEvidence(probe._last_owner_sequence)
    with pytest.raises(RuntimeError, match="owner retention binding invalid"):
        context.BeginStage3ProofRetention(
            session, attempt, source, context._stage3_evidence_sequence, clock.read() + 180.0
        )
    probe.on_disable()


def test_stage3_ready_to_zone_refuses_already_expired_outpost_authority(
    cleansing_runtime: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    runtime, module = cleansing_runtime
    harness = _prepare_stage3_probe_harness(monkeypatch, runtime, module, role_distribution="remote_bip")
    context, _cache, upkeeper, probe, clock, _diagnostics, _runtime = harness
    upkeeper.main()
    clock.advance(5.01)
    probe.update()
    output = capsys.readouterr().out
    assert "event=no_go reason=outpost_verification_expired" in output
    assert "event=ready_to_zone " not in output
    assert context.GetTransitionBoundary().phase is module.TransitionPhase.OUTPOST_READY
    probe.on_disable()
