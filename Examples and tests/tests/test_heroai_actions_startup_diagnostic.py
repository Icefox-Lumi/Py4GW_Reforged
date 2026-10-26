"""Offline, fail-closed runtime fixtures for the temporary startup diagnostic."""

# pyright: strict

from __future__ import annotations

import copy
import ast
import ctypes
import enum
import importlib.abc
import importlib.machinery
import importlib.util
import subprocess
import sys
import types
import unittest
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from typing import Iterator
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT.parent / "Py4GW_Reforged-main TESTS"
WIDGET = ROOT / "Widgets/Coding/Debug/Py4GW/HeroAI Actions Startup Diagnostic.py"
EMAIL = "private-owner@example.invalid"
ALT = "private-alt@example.invalid"
NAME = "Private Character Name"


class Account:
    def __init__(self, slot: int, email: str, **changes: Any) -> None:
        self.AccountEmail = email
        self.SlotNumber = slot
        self.IsAccount = True
        self.IsSlotActive = True
        self.IsIsolated = True
        self.IsolationGroupID = 10
        self.LastUpdated = 9900
        self.AgentPartyData = types.SimpleNamespace(PartyID=100 + slot)
        self.AgentData = types.SimpleNamespace(
            Map=types.SimpleNamespace(MapID=1, Region=0, District=1, Language=0),
            AgentID=20 + slot,
            LoginNumber=30 + slot,
            CharacterName=NAME,
        )
        self.visible = True
        self.selected = True
        self.hidden = False
        self.authorized = True
        self.copy_error = False
        for name, value in changes.items():
            setattr(self, name, value)

    @classmethod
    def from_buffer_copy(cls, row: Account) -> Account:
        if row.copy_error:
            raise RuntimeError(f"{EMAIL} {NAME} password=never-print-this")
        return copy.deepcopy(row)


class Runtime:
    def __init__(self, rows: list[Account]) -> None:
        self.shm = object()  # Already attached; capture must never call _attach.
        self.AccountData = list(rows) + [
            Account(i, "", IsAccount=False, IsSlotActive=False, visible=False, selected=False)
            for i in range(len(rows), 64)
        ]
        self.calls: Counter[str] = Counter()
        self.logs: list[str] = []
        self.forbidden: list[str] = []
        self.button = False
        self.auth_error = False
        self.selection_error = False
        self.registry_error = False
        self.log_error = False
        self.log_failure_at: int | None = None
        self.log_interrupt = False

    def __getattr__(self, name: str) -> Any:
        self.forbidden.append(name)
        raise AssertionError(f"Unexpected runtime operation: {name}")

    def GetAllAccounts(self) -> Runtime:
        self.calls["registry"] += 1
        if self.registry_error:
            raise RuntimeError(f"{EMAIL} {NAME}")
        return self

    def GetAllAccountData(self) -> list[Account]:
        self.calls["visible"] += 1
        return [a for a in self.AccountData if a.visible]

    def _is_slot_isolated(self, slot: int) -> bool:
        self.calls["hidden"] += 1
        return self.AccountData[slot].hidden

    def _can_communicate(self, sender: str, receiver: str) -> bool:
        self.calls["authorize"] += 1
        if self.auth_error:
            raise RuntimeError(f"{sender} {receiver} {NAME}")
        return any(a.AccountEmail == receiver and a.authorized for a in self.AccountData)

    def select(self) -> list[Account]:
        self.calls["selected"] += 1
        if self.selection_error:
            raise RuntimeError(f"{EMAIL} {NAME}")
        return [a for a in self.AccountData if a.selected]

    def log(self, sender: str, message: str, level: int) -> None:
        del sender, level
        self.calls["log"] += 1
        if self.calls["log"] == self.log_failure_at and self.log_interrupt:
            raise KeyboardInterrupt("Console interrupted")
        if self.log_error or self.calls["log"] == self.log_failure_at:
            raise RuntimeError("Console unavailable")
        self.logs.append(message)

    def press(self, label: str) -> bool:
        assert label == "Capture Snapshot"
        pressed, self.button = self.button, False
        return pressed


class ImportTripwire(importlib.abc.MetaPathFinder):
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        del path, target
        if fullname.startswith("Py4GWCoreLib") or fullname == "PyCallback":
            self.attempts.append(fullname)
            raise AssertionError("Diagnostic attempted a cold runtime import")
        return None


def source_members(path: str, module_name: str, owner: str | None, names: tuple[str, ...], **scope: Any) -> Any:
    """Execute selected TESTS bodies verbatim, retaining their real decorators/imports.

    Module startup is deliberately excluded here, not in the diagnostic. Native
    pointers/bindings are fixtures; this is not a live-client safety proof.
    """
    source = REFERENCE / "Py4GWCoreLib" / path
    tree = ast.parse(source.read_text(encoding="utf-8"))
    body = (
        tree.body
        if owner is None
        else next(n.body for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == owner)
    )
    methods = [n for n in body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in methods} == set(names), (path, owner, names)
    nodes: list[ast.stmt] = list(methods)
    if owner:
        nodes = [ast.ClassDef(name=owner, bases=[], keywords=[], body=nodes, decorator_list=[])]
    module = sys.modules.get(module_name)
    if module is None:
        module = types.ModuleType(module_name)
        sys.modules[module_name] = module
    module.__dict__.update(scope, __package__=module_name.rpartition(".")[0])
    compiled = ast.fix_missing_locations(
        ast.Module(
            body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes],
            type_ignores=[],
        )
    )
    exec(compile(compiled, str(source), "exec"), module.__dict__)
    return module.__dict__[owner] if owner else module


def production_runtime(runtime: Runtime) -> Any:
    """Install the audited capture call tree without importing production modules."""
    prefix = "Py4GWCoreLib."
    frame_module = sys.modules[prefix + "py4gwcorelib_src.FrameCache"]
    frame_path = REFERENCE / "Py4GWCoreLib/py4gwcorelib_src/FrameCache.py"
    frame_tree = ast.parse(frame_path.read_text(encoding="utf-8"))
    # Keep the real decorator/cache; only its module-startup enable call is omitted.
    frame_tree.body = [n for n in frame_tree.body if not isinstance(n, ast.Expr)]
    exec(compile(frame_tree, str(frame_path), "exec"), vars(frame_module))
    frame_cache = vars(frame_module)["frame_cache"]
    frame = vars(frame_module)["FRAME_CACHE"]

    def facade(value: object) -> Any:
        return types.SimpleNamespace(GetContext=lambda: value, IsValid=lambda: value is not None)

    char = types.SimpleNamespace(
        player_number=30, player_email_str=EMAIL, current_map_id=1, observe_map_id=1, district_number=1, language=0
    )
    # Non-matching login forces IsPlayerLoaded through Agent, AgentArray and UIManager.
    context = types.SimpleNamespace(
        Map=facade(object()),
        Char=facade(char),
        InstanceInfo=facade(types.SimpleNamespace(instance_type=1)),
        World=facade(types.SimpleNamespace(player_controlled_character=types.SimpleNamespace(agent_id=20))),
        Party=facade(
            types.SimpleNamespace(
                player_party=types.SimpleNamespace(players=[types.SimpleNamespace(login_number=99, is_connected=True)])
            )
        ),
        Cinematic=facade(types.SimpleNamespace(h0004=0)),
        ServerRegion=facade(types.SimpleNamespace(region_id=0)),
    )
    sys.modules[prefix + "Context"].__dict__["GWContext"] = context
    map_api = source_members(
        "Map.py",
        prefix + "Map",
        "Map",
        (
            "IsMapDataLoaded",
            "GetInstanceType",
            "IsOutpost",
            "IsExplorable",
            "IsMapLoading",
            "IsObservingMatch",
            "IsMapReady",
            "GetMapID",
            "GetRegion",
            "GetDistrict",
            "GetLanguage",
            "IsInCinematic",
        ),
        GWContext=context,
        frame_cache=frame_cache,
        InstanceType=enum.IntEnum("InstanceType", {"Explorable": 0, "Outpost": 1, "Loading": 2}),
        ServerRegionName={0: "region", 255: "unknown"},
        ServerLanguageName={0: "language", 255: "unknown"},
    )
    system = sys.modules["PySystem"]
    vars(system)["Console"].get_gw_window_handle = lambda: 123
    player = source_members(
        "Player.py",
        prefix + "Player",
        "Player",
        (
            "GetAccountEmail",
            "IsPlayerLoaded",
            "GetPlayerNumber",
            "_hwnd_account_fallback",
            "_sanitize_account_email_or_fallback",
        ),
        GWContext=context,
        frame_cache=frame_cache,
        PySystem=system,
    )
    player._ACCOUNT_EMAIL_MAX_LEN = 64
    source_members("Agent.py", prefix + "Agent", "Agent", ("IsValid", "GetAgentByID", "GetInstanceUptime"))
    source_members("AgentArray.py", prefix + "AgentArray", "AgentArray", ("GetAgentByID",))
    source_members(
        "UIManager.py",
        prefix + "UIManager",
        "UIManager",
        ("GetFPSLimit",),
        PyUIManager=sys.modules["PyUIManager"],
        frame_cache=frame_cache,
    )

    class NativeAgent(ctypes.Structure):
        _fields_ = [("timer", ctypes.c_uint32)]

    native_agent = NativeAgent(60)
    agent_context = source_members(
        "native_src/context/AgentContext.py",
        prefix + "native_src.context.AgentContext",
        "AgentArray",
        ("GetAgentByID",),
        cast=ctypes.cast,
        POINTER=ctypes.POINTER,
        AgentStruct=NativeAgent,
    )
    agent_context._agent_by_id = {}
    wrapper_type = source_members(
        "native_src/ShMem/structs/AgentArraySSM.py",
        prefix + "native_src.ShMem.structs.AgentArraySSM",
        "AgentArraySHMemWrapper",
        ("_build_agents_dict", "get_agent_by_id"),
        AGENT_ARRAY_MAX_SIZE=64,
    )
    wrapper = object.__new__(wrapper_type)
    wrapper._agents_dict = None
    wrapper._raw = types.SimpleNamespace(
        AgentArrayCount=1, AgentArray=[types.SimpleNamespace(agent_id=20, ptr=ctypes.addressof(native_agent))]
    )
    manager_type = source_members(
        "native_src/ShMem/SysShaMem.py",
        prefix + "native_src.ShMem.SysShaMem",
        "SystemSharedMemoryManager",
        ("get_agent_array_wrapper",),
    )
    manager = object.__new__(manager_type)
    manager.agent_array_wrapper = wrapper
    sys.modules[prefix + "native_src.ShMem.SysShaMem"].__dict__["SystemShaMemMgr"] = manager

    timing = source_members(
        "GlobalCache/shared_memory_src/IntentSync.py",
        prefix + "GlobalCache.shared_memory_src.IntentSync",
        None,
        ("get_uncached_tick_count64", "normalize_tick", "tick_elapsed", "publication_age", "publication_is_live"),
        _kernel32=types.SimpleNamespace(GetTickCount64=lambda: 10000),
        UINT32_MASK=0xFFFFFFFF,
        UINT32_HALF_RANGE=0x80000000,
    )
    registry_type = source_members(
        "GlobalCache/shared_memory_src/AllAccounts.py",
        prefix + "GlobalCache.shared_memory_src.AllAccounts",
        "AllAccounts",
        (
            "GetAccountData",
            "_is_slot_active",
            "_is_visible_account",
            "_is_visible_slot",
            "_get_slot_group",
            "_get_local_group_id",
            "_get_local_account_email",
            "_get_slot_owner_email",
            "_is_slot_owned_by_email",
            "_is_local_owned_slot",
            "_is_slot_isolated",
            "_find_account_slot_by_email",
            "_find_player_slot_by_key",
            "GetSlotByEmail",
            "_get_message_account_snapshot",
            "_can_communicate",
            "GetAuthorizedAccountSlot",
            "GetAllActivePlayers",
            "GetAllActiveSlotsData",
        ),
        SHMEM_MAX_PLAYERS=64,
        SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS=5000,
        PySystem=system,
        **{
            name: vars(timing)[name] for name in ("get_uncached_tick_count64", "publication_age", "publication_is_live")
        },
    )
    registry = object.__new__(registry_type)
    registry.AccountData = runtime.AccountData
    registry.Keys = [types.SimpleNamespace(HWND=123 if i == 0 else 456, EntityType=0) for i in range(64)]
    for row in runtime.AccountData:
        row.AgentPartyData.PartyPosition = 0

    def from_buffer(buffer: object) -> Any:
        del buffer
        return registry

    registry_type.from_buffer = staticmethod(from_buffer)
    shared_type = source_members(
        "GlobalCache/SharedMemory.py",
        prefix + "GlobalCache.SharedMemory",
        "Py4GWSharedMemoryManager",
        ("GetAllAccounts", "GetAllAccountData", "GetAllActiveSlotsData"),
        frame_cache=frame_cache,
        AllAccounts=registry_type,
    )
    shared = object.__new__(shared_type)
    shared.shm = types.SimpleNamespace(buf=object())

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        runtime.forbidden.append("initialization_or_write")
        raise AssertionError("Capture attempted initialization or mutation")

    shared._attach = forbidden
    party_type = source_members(
        "GlobalCache/PartyCache.py",
        prefix + "GlobalCache.PartyCache",
        "PartyCache",
        ("GetPartyID", "GetPlayers", "IsPartyLoaded"),
        Map=map_api,
        Player=player,
    )
    party = object.__new__(party_type)

    def agent_by_login(login: int) -> int:
        del login
        return 20

    party._party_instance = types.SimpleNamespace(
        party_id=100,
        is_party_loaded=True,
        players=[types.SimpleNamespace(login_number=30)],
        GetAgentIDByLoginNumber=agent_by_login,
    )
    players_type = source_members(
        "GlobalCache/PartyCache.py", prefix + "GlobalCache.PartyCache", "_Players", ("GetAgentIDByLoginNumber",)
    )
    party.Players = object.__new__(players_type)
    party.Players._parent = party
    cache = sys.modules[prefix + "GlobalCache"].__dict__["GLOBAL_CACHE"]
    cache.ShMem, cache.Party = shared, party
    utils = source_members(
        "HeroAI/utils.py",
        prefix + "HeroAI.utils",
        None,
        ("_account_key", "SameMapOrPartyAsAccount"),
        frame_cache=frame_cache,
        Map=map_api,
        GLOBAL_CACHE=cache,
    )
    api_type = source_members(
        "HeroAI/command_api.py",
        prefix + "HeroAI.command_api",
        "HeroAICommandAPI",
        ("_resolve_accounts",),
        Map=map_api,
        GLOBAL_CACHE=cache,
        SameMapOrPartyAsAccount=vars(utils)["SameMapOrPartyAsAccount"],
    )
    api_type._instance = object.__new__(api_type)
    handler_type = source_members(
        "py4gwcorelib_src/WidgetManager.py",
        prefix + "py4gwcorelib_src.WidgetManager",
        "WidgetHandler",
        ("_get_widget_by_plain_name", "is_widget_enabled"),
    )
    handler = object.__new__(handler_type)
    handler.widgets = {"hero": types.SimpleNamespace(plain_name="HeroAI", enabled=True)}
    sys.modules[prefix + "py4gwcorelib_src.WidgetManager"].__dict__["_widget_handler"] = handler
    # Any subsequent owner construction or write is an error, including negative controls.
    owners: tuple[Any, ...] = (
        vars(frame_module)["FrameCache"],
        manager_type,
        shared_type,
        party_type,
        api_type,
        handler_type,
    )
    for owner in owners:
        owner.__new__ = staticmethod(forbidden)
    for name in ("SendMessage", "SubmitAccount", "SetAccountIsolationByEmail", "SetAccountGroupByEmail"):
        setattr(registry, name, forbidden)
    cache.Party.InvitePlayer = cache.Party.LeaveParty = map_api.Travel = forbidden
    callback = types.ModuleType("PyCallback")
    callback.__dict__["PyCallback"] = types.SimpleNamespace(Register=forbidden)
    sys.modules["PyCallback"] = callback
    return types.SimpleNamespace(
        player=player,
        map=map_api,
        frame=frame,
        registry=registry,
        shared=shared,
        api=api_type._instance,
        party=party,
        char=char,
        native_agent=native_agent,
        agent_context=agent_context,
    )


@contextmanager
def loaded(rows: list[Account]) -> Iterator[tuple[Any, Runtime]]:
    runtime = Runtime(rows)
    modules: dict[str, types.ModuleType] = {}

    def module(name: str, **members: Any) -> types.ModuleType:
        result = types.ModuleType(name)
        result.__dict__.update(members)
        modules[name] = result
        return result

    for name in (
        "Py4GWCoreLib",
        "Py4GWCoreLib.GlobalCache",
        "Py4GWCoreLib.GlobalCache.shared_memory_src",
        "Py4GWCoreLib.HeroAI",
        "Py4GWCoreLib.py4gwcorelib_src",
        "Py4GWCoreLib.native_src",
        "Py4GWCoreLib.native_src.context",
        "Py4GWCoreLib.native_src.ShMem",
    ):
        module(name).__path__ = []

    def end() -> None:
        runtime.calls["end"] += 1

    def begin(name: str, *, flags: int) -> bool:
        del name, flags
        return True

    def text(value: str) -> None:
        del value

    def enabled(name: str) -> bool:
        del name
        return True

    gui = module(
        "PyImGui",
        begin=begin,
        end=end,
        button=runtime.press,
        text=text,
        text_wrapped=text,
        WindowFlags=types.SimpleNamespace(AlwaysAutoResize=1, NoSavedSettings=2),
    )
    module("PySystem", Console=types.SimpleNamespace(Log=runtime.log), MessageType=types.SimpleNamespace(Info=0))
    module("PyUIManager", UIManager=types.SimpleNamespace(get_frame_limit=lambda: 60))
    setattr(
        modules["Py4GWCoreLib.GlobalCache"],
        "GLOBAL_CACHE",
        types.SimpleNamespace(
            ShMem=runtime, Party=types.SimpleNamespace(IsPartyLoaded=lambda: True, GetPartyID=lambda: 100)
        ),
    )
    module("Py4GWCoreLib.GlobalCache.shared_memory_src.AccountStruct", AccountStruct=Account)
    module(
        "Py4GWCoreLib.GlobalCache.shared_memory_src.Globals",
        SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS=5000,
        SHMEM_MAX_PLAYERS=64,
    )

    class API:
        _instance: API | None = None

        def __new__(cls) -> API:
            raise AssertionError("Diagnostic must not construct HeroAI")

        def _resolve_accounts(self) -> list[Account]:
            return runtime.select()

    setattr(API, "_instance", object.__new__(API))
    module("Py4GWCoreLib.HeroAI.command_api", HeroAICommandAPI=API)
    module(
        "Py4GWCoreLib.Map",
        Map=types.SimpleNamespace(
            GetMapID=lambda: 1,
            GetRegion=lambda: (0, ""),
            GetDistrict=lambda: 1,
            GetLanguage=lambda: (0, ""),
            IsMapReady=lambda: True,
            IsMapLoading=lambda: False,
            IsOutpost=lambda: True,
        ),
    )
    module(
        "Py4GWCoreLib.Player", Player=types.SimpleNamespace(GetAccountEmail=lambda: EMAIL, IsPlayerLoaded=lambda: True)
    )
    for name, member in (
        ("Context", "GWContext"),
        ("py4gwcorelib_src.FrameCache", "FRAME_CACHE"),
        ("Agent", "Agent"),
        ("AgentArray", "AgentArray"),
        ("UIManager", "UIManager"),
        ("native_src.context.AgentContext", "AgentArray"),
        ("native_src.ShMem.SysShaMem", "SystemShaMemMgr"),
    ):
        module(f"Py4GWCoreLib.{name}", **{member: object()})
    module(
        "Py4GWCoreLib.py4gwcorelib_src.WidgetManager",
        _widget_handler=types.SimpleNamespace(is_widget_enabled=enabled),
    )
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("startup_diagnostic_under_test", WIDGET)
        assert spec is not None and spec.loader is not None
        widget = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(widget)
        with patch.object(widget, "_clock", return_value=10000):
            yield widget, runtime
    del gui


class StartupDiagnosticTests(unittest.TestCase):
    def assert_private(self, runtime: Runtime) -> str:
        output = "\n".join(runtime.logs)
        for private in (EMAIL, ALT, NAME, "never-print-this"):
            self.assertNotIn(private, output)
        self.assertEqual(runtime.forbidden, [])
        return output

    def assert_partial_dependency(self, name: str, member: str, mode: str) -> None:
        with loaded([Account(0, EMAIL), Account(1, ALT)]) as (widget, runtime):
            source = production_runtime(runtime)
            module_name = "Py4GWCoreLib." + name
            module = sys.modules[module_name]
            lazy_reads: list[str] = []

            def lazy(attribute: str) -> Any:
                lazy_reads.append(attribute)
                raise AssertionError("Lazy production access")

            if mode == "absent":
                sys.modules.pop(module_name)
            else:
                if mode == "missing_symbol":
                    vars(module).pop(member)
                elif mode == "initializing":
                    spec = importlib.machinery.ModuleSpec(module_name, loader=None)
                    vars(spec)["_initializing"] = True
                    module.__spec__ = spec
                vars(module)["__getattr__"] = lazy
            before = copy.deepcopy([vars(a) for a in runtime.AccountData])
            tripwire = ImportTripwire()
            with patch.object(sys, "meta_path", [tripwire, *sys.meta_path]):
                widget._capture_snapshot()
                output = self.assert_private(runtime)
                self.assertEqual(tripwire.attempts, [], (name, mode, output))
                self.assertEqual(lazy_reads, [], (name, mode, output))
                self.assertIn("email_available=False email_error=dependencies_unavailable", output)
                self.assertIn("player_loaded=None error=dependencies_unavailable", output)
                self.assertIn("party_loaded=None error=dependencies_unavailable", output)
                self.assertIn("HA_STARTUP ACCOUNT slot=1", output)
                self.assertIn("state=visibility_unknown", output)
                self.assertIn("authorized=None/local_identity_unavailable", output)
                self.assertIn("self_missing=None", output)
                self.assertEqual(widget._baseline_number, 0)
                self.assertEqual(before, [vars(a) for a in runtime.AccountData])
                self.assertLessEqual(len(runtime.logs), 96)
                self.assertTrue(runtime.logs[-1].startswith("HA_STARTUP END"))
                # Deliberately bypass the diagnostic guard. GetAccountEmail can
                # swallow the error and manufacture an HWND fallback: inspect traps.
                try:
                    source.player.GetAccountEmail()
                except AssertionError:
                    pass
                self.assertTrue(tripwire.attempts or lazy_reads, (name, mode, "negative control did not fire"))

    def test_real_getters_map_absent(self) -> None:
        self.assert_partial_dependency("Map", "Map", "absent")

    def test_real_getters_map_partial(self) -> None:
        self.assert_partial_dependency("Map", "Map", "missing_symbol")

    def test_real_getters_agent_absent(self) -> None:
        self.assert_partial_dependency("Agent", "Agent", "absent")

    def test_real_getters_agent_partial(self) -> None:
        self.assert_partial_dependency("Agent", "Agent", "missing_symbol")

    def test_real_getters_reject_initializing_modules_even_with_symbols(self) -> None:
        for name in ("Map", "Agent"):
            with self.subTest(module=name):
                self.assert_partial_dependency(name, name, "initializing")

    def test_real_getters_reject_lazy_modules_even_with_symbols(self) -> None:
        for name in ("Map", "Agent"):
            with self.subTest(module=name):
                self.assert_partial_dependency(name, name, "lazy_with_symbol")

    def test_initializing_spec_alone_blocks_real_getters(self) -> None:
        for name in ("Map", "Agent"):
            with self.subTest(module=name), loaded([Account(0, EMAIL)]) as (widget, runtime):
                source = production_runtime(runtime)
                module = sys.modules["Py4GWCoreLib." + name]
                spec = importlib.machinery.ModuleSpec(module.__name__, loader=None)
                vars(spec)["_initializing"] = True
                module.__spec__ = spec
                widget._capture_snapshot()
                output = self.assert_private(runtime)
                self.assertIn("email_available=False email_error=dependencies_unavailable", output)
                self.assertEqual(widget._baseline_number, 0)
                self.assertEqual(source.agent_context._agent_by_id, {})
                # All symbols exist; only the completion flag prevents entry.
                self.assertEqual(source.player.GetAccountEmail(), EMAIL)
                self.assertIn(20, source.agent_context._agent_by_id)

    def test_missing_services_preserve_only_available_evidence(self) -> None:
        for name, member in (
            ("Player", "Player"),
            ("Context", "GWContext"),
            ("py4gwcorelib_src.FrameCache", "FRAME_CACHE"),
        ):
            for partial in (False, True):
                with self.subTest(module=name, partial=partial), loaded([Account(0, EMAIL)]) as (widget, runtime):
                    production_runtime(runtime)
                    module_name = "Py4GWCoreLib." + name
                    if partial:
                        vars(sys.modules[module_name]).pop(member)
                    else:
                        sys.modules.pop(module_name)
                    tripwire = ImportTripwire()
                    with patch.object(sys, "meta_path", [tripwire, *sys.meta_path]):
                        widget._capture_snapshot()
                    output = self.assert_private(runtime)
                    self.assertEqual(tripwire.attempts, [])
                    if name == "py4gwcorelib_src.FrameCache":
                        # The registry getter itself needs this cache. Do not
                        # bypass its decorator or build an alternative registry.
                        self.assertIn("reason=registry_cache_unavailable", output)
                    else:
                        self.assertIn("HA_STARTUP ACCOUNT slot=0", output)
                        self.assertIn("self=None state=visibility_unknown", output)
                        self.assertIn("self_missing=None", output)
                    self.assertEqual(widget._baseline_number, 0)

    def test_partial_native_console_blocks_fallback_identity_and_authorization(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            production_runtime(runtime)
            system = sys.modules["PySystem"]
            console = types.ModuleType("PySystem.Console")
            console.__dict__["Log"] = runtime.log
            reads: list[str] = []

            def lazy(name: str) -> Any:
                reads.append(name)
                raise AssertionError("Lazy native console access")

            console.__dict__["__getattr__"] = lazy
            system.__dict__["Console"] = console
            widget._secret = b"s" * 32
            lines: list[str] = []
            self.assertIsNone(widget._collect(lines))
            self.assertEqual(reads, [])
            self.assertIn("self_missing=None", "\n".join(lines))
            self.assertIn("email_available=False email_error=dependencies_unavailable", "\n".join(lines))

    def test_real_idle_frames_do_not_populate_caches(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            source = production_runtime(runtime)
            tripwire = ImportTripwire()
            with patch.object(sys, "meta_path", [tripwire, *sys.meta_path]):
                for _ in range(100):
                    widget.main()
            self.assertEqual(source.frame._values, {})
            self.assertEqual(source.agent_context._agent_by_id, {})
            self.assertEqual(tripwire.attempts, [])
            self.assertEqual(runtime.calls, {"end": 100})
            self.assertEqual(self.assert_private(runtime), "")

    def test_real_fps_binding_partial_module_cannot_lazy_initialize(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            source = production_runtime(runtime)
            binding = sys.modules["PyUIManager"]
            vars(binding).pop("UIManager")
            reads: list[str] = []

            def lazy(name: str) -> Any:
                reads.append(name)
                raise AssertionError("Lazy FPS binding access")

            vars(binding)["__getattr__"] = lazy
            widget._capture_snapshot()
            self.assertEqual(reads, [])
            self.assertIn("self_missing=None", self.assert_private(runtime))
            self.assertEqual(widget._baseline_number, 0)
            source.player.GetAccountEmail()  # Production catches this and falls back.
            self.assertEqual(reads, ["UIManager"])

    def test_real_fps_binding_absent_preserves_raw_evidence(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            production_runtime(runtime)
            sys.modules.pop("PyUIManager")
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("HA_STARTUP ACCOUNT slot=0", output)
            self.assertIn("self=None state=visibility_unknown", output)
            self.assertEqual(widget._baseline_number, 0)

    def test_real_readiness_fallback_guards_entire_import_chain(self) -> None:
        for name, member in (
            ("AgentArray", "AgentArray"),
            ("UIManager", "UIManager"),
            ("native_src.context.AgentContext", "AgentArray"),
            ("native_src.ShMem.SysShaMem", "SystemShaMemMgr"),
        ):
            for mode in ("absent", "missing_symbol", "initializing", "lazy_with_symbol"):
                with self.subTest(module=name, mode=mode):
                    self.assert_partial_dependency(name, member, mode)

    def test_real_initialized_capture_preserves_registry_and_uses_production_policy(self) -> None:
        rows = [Account(0, EMAIL), Account(1, ALT), Account(2, "hidden", IsolationGroupID=22)]
        with loaded(rows) as (widget, runtime):
            source = production_runtime(runtime)
            before = copy.deepcopy([vars(a) for a in runtime.AccountData])
            tripwire = ImportTripwire()
            with patch.object(sys, "meta_path", [tripwire, *sys.meta_path]):
                widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertEqual(tripwire.attempts, [])
            self.assertEqual(before, [vars(a) for a in runtime.AccountData])
            self.assertIn("state=selected", output)
            self.assertIn("state=hidden_isolation", output)
            self.assertIn("selected_error=none", output)
            self.assertIn("self_missing=False", output)
            self.assertEqual(widget._baseline_number, 1)
            self.assertLessEqual(len(runtime.logs), 96)
            # Existing APIs populate Python caches: do not claim zero process-state effects.
            self.assertTrue(source.frame._values)
            self.assertIn(20, source.agent_context._agent_by_id)

    def test_real_explorable_selection_and_cross_region_party_exception(self) -> None:
        rows = [Account(0, EMAIL), Account(1, ALT)]
        rows[1].AgentData.AgentID = 20
        rows[1].AgentData.Map.Region = 1
        rows[1].AgentPartyData.PartyID = 100
        with loaded(rows) as (widget, runtime):
            source = production_runtime(runtime)
            context = sys.modules["Py4GWCoreLib.Context"].__dict__["GWContext"]
            context.InstanceInfo.GetContext().instance_type = 0
            widget._capture_snapshot()
            self.assertIn(f"id={widget._token(ALT)} self=False state=selected", self.assert_private(runtime))
            self.assertEqual(source.frame._callback_registered, False)

    def test_real_party_discovery_unsafe_negative_controls(self) -> None:
        for missing in ("Map", "Agent"):
            for target in ("party", "selection", "visibility", "isolation"):
                with self.subTest(missing=missing, target=target), loaded([Account(0, EMAIL)]) as (widget, runtime):
                    source = production_runtime(runtime)
                    sys.modules.pop("Py4GWCoreLib." + missing)
                    tripwire = ImportTripwire()
                    with patch.object(sys, "meta_path", [tripwire, *sys.meta_path]):
                        widget._capture_snapshot()
                        self.assertEqual(tripwire.attempts, [])
                        self.assert_private(runtime)
                        unsafe = {
                            "party": source.party.GetPlayers,
                            "selection": source.api._resolve_accounts,
                            "visibility": source.shared.GetAllAccountData,
                            "isolation": lambda: source.registry._is_slot_isolated(0),
                        }[target]
                        try:
                            unsafe()
                        except AssertionError:
                            pass
                        self.assertTrue(tripwire.attempts, (missing, target))

    def test_real_unattached_registry_does_not_retry_attach(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            source = production_runtime(runtime)
            source.shared.shm = None
            widget._capture_snapshot()
            self.assertIn("reason=registry_not_attached_or_loaded", self.assert_private(runtime))
            self.assertEqual(widget._baseline_number, 0)
            with self.assertRaises(AssertionError):
                source.shared.GetAllAccounts()
            self.assertEqual(runtime.forbidden, ["initialization_or_write"])

    def test_real_missing_party_service_preserves_raw_registry(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            production_runtime(runtime)
            cache = sys.modules["Py4GWCoreLib.GlobalCache"].__dict__["GLOBAL_CACHE"]
            del cache.Party
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("party_loaded=None error=AttributeError", output)
            self.assertIn("state=selection_unavailable", output)
            self.assertIn("HA_STARTUP ACCOUNT slot=0", output)

    def test_real_empty_identity_does_not_classify_visibility_or_missing(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            source = production_runtime(runtime)
            source.char.observe_map_id = 2
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("email_available=False", output)
            self.assertIn("state=visibility_unknown", output)
            self.assertIn("self_missing=None", output)
            self.assertEqual(widget._baseline_number, 0)

    def test_dependencies_disappearing_before_confirmation_do_not_advance_baseline(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            source = production_runtime(runtime)
            widget._capture_snapshot()
            baseline = set(widget._previous_tokens)
            original = source.registry._can_communicate

            def authorize(sender: str, receiver: str) -> bool:
                sys.modules.pop("Py4GWCoreLib.Agent", None)
                return bool(original(sender, receiver))

            runtime.logs.clear()
            with patch.object(source.registry, "_can_communicate", side_effect=authorize):
                widget._capture_snapshot()
            self.assertIn("identity_stable=False", self.assert_private(runtime))
            self.assertEqual(widget._previous_tokens, baseline)
            self.assertEqual(widget._baseline_number, 1)

    def test_partial_console_module_never_invokes_lazy_loader(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            system = sys.modules["PySystem"]
            vars(system).pop("Console")
            lazy_reads: list[str] = []

            def lazy(name: str) -> Any:
                lazy_reads.append(name)
                raise AssertionError("Lazy console initialization")

            vars(system)["__getattr__"] = lazy
            widget._capture_snapshot()
            self.assertEqual(lazy_reads, [])
            self.assertEqual(widget._baseline_number, 0)
            self.assertEqual(runtime.logs, [])
            self.assertIn("Console output failed", widget._status)

    def test_production_owner_construction_callback_and_write_traps_have_negative_controls(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            source = production_runtime(runtime)
            widget._capture_snapshot()
            self.assert_private(runtime)
            operations = (
                lambda: type(source.api)(),
                lambda: sys.modules["PyCallback"].__dict__["PyCallback"].Register("forbidden"),
                lambda: source.registry.SendMessage(EMAIL, ALT),
                lambda: source.party.InvitePlayer(1),
                lambda: source.registry.SetAccountIsolationByEmail(EMAIL, False),
                lambda: source.map.Travel(1),
            )
            for operation in operations:
                with self.assertRaises(AssertionError):
                    operation()
            self.assertEqual(len(runtime.forbidden), len(operations))

    def test_import_and_idle_frames_do_not_sample_or_log(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            for _ in range(100):
                widget.main()
            self.assertEqual(runtime.logs, [])
            self.assertEqual(runtime.calls, {"end": 100})
            self.assertIsNone(widget._secret)

    def test_button_captures_once_without_mutating_registry(self) -> None:
        rows = [Account(0, EMAIL), Account(1, ALT)]
        before = copy.deepcopy([vars(a) for a in rows])
        with loaded(rows) as (widget, runtime):
            runtime.button = True
            widget.main()
            for _ in range(20):
                widget.main()
            output = self.assert_private(runtime)
            self.assertIn("BEGIN snapshot=1", output)
            self.assertIn("END snapshot=1", output)
            self.assertEqual(runtime.calls["registry"], 1)
            self.assertEqual(runtime.calls["selected"], 1)
            self.assertEqual(before, [vars(a) for a in rows])

    def test_hidden_then_selected_and_session_tokens_stay_stable(self) -> None:
        alt = Account(1, ALT, IsolationGroupID=22, visible=False, selected=False, hidden=True, authorized=False)
        with loaded([Account(0, EMAIL), alt]) as (widget, runtime):
            widget._capture_snapshot()
            token = widget._token(ALT)
            self.assertIn("state=hidden_isolation", self.assert_private(runtime))
            alt.IsolationGroupID = 10
            alt.visible = alt.selected = alt.authorized = True
            alt.hidden = False
            runtime.logs.clear()
            widget._capture_snapshot()
            self.assertIn(f"id={token} self=False state=selected", self.assert_private(runtime))

    def test_stale_inactive_unready_and_location_excluded(self) -> None:
        rows = [
            Account(0, EMAIL),
            Account(1, ALT, LastUpdated=5000),
            Account(2, "inactive", IsSlotActive=False),
            Account(3, "unready"),
            Account(4, "other-map", selected=False),
        ]
        rows[3].AgentData.LoginNumber = 0
        rows[4].AgentData.Map.District = 2
        with loaded(rows) as (widget, runtime):
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            for state in ("stale", "inactive", "identity_unready", "excluded_location"):
                self.assertIn(f"state={state}", output)

    def test_duplicate_live_rows_and_authorization_rejection_are_explicit(self) -> None:
        with loaded([Account(0, EMAIL), Account(1, ALT), Account(2, ALT), Account(3, "denied", authorized=False)]) as (
            widget,
            runtime,
        ):
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertEqual(output.count("state=duplicate_live_identity"), 2)
            self.assertIn("state=selected_authorization_denied", output)
            self.assertIn("authorized=False/none", output)

    def test_selection_and_authorizer_errors_remain_unknown_and_private(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            runtime.selection_error = runtime.auth_error = True
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("state=selection_unavailable", output)
            self.assertIn("selected_error=RuntimeError", output)
            self.assertIn("authorized=None/RuntimeError", output)

    def test_disappeared_rows_and_missing_local_identity(self) -> None:
        with loaded([Account(0, EMAIL), Account(1, ALT)]) as (widget, runtime):
            widget._capture_snapshot()
            token = widget._token(ALT)
            runtime.AccountData[:] = [
                Account(i, "", IsAccount=False, IsSlotActive=False, visible=False, selected=False) for i in range(64)
            ]
            runtime.logs.clear()
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("self_missing=True", output)
            self.assertIn("MISSING_SINCE_PREVIOUS ids=", output)
            self.assertIn(token, output)

    def test_partial_copy_does_not_falsely_report_missing_previous_accounts(self) -> None:
        rows = [Account(0, EMAIL), Account(1, ALT)]
        with loaded(rows) as (widget, runtime):
            widget._capture_snapshot()
            rows[1].copy_error = True
            runtime.logs.clear()
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("state=read_error error=RuntimeError", output)
            self.assertIn("scan_complete=False", output)
            self.assertNotIn("MISSING_SINCE_PREVIOUS", output)

    def test_output_and_raw_scan_are_bounded(self) -> None:
        rows = [Account(i, EMAIL if i == 0 else str(i)) for i in range(100)]
        with loaded(rows) as (widget, runtime):
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertEqual(output.count("HA_STARTUP ACCOUNT "), 64)
            self.assertLessEqual(len(runtime.logs), widget._MAX_LINES)
            self.assertTrue(all(len(line) <= len("HA_STARTUP ") + widget._MAX_LINE_LENGTH for line in runtime.logs))
            self.assertTrue(runtime.logs[-1].startswith("HA_STARTUP END"))

    def test_capture_and_console_failures_never_retry_in_background(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            runtime.registry_error = True
            widget._capture_snapshot()
            self.assertIn("ERROR stage=capture type=RuntimeError", self.assert_private(runtime))
            runtime.log_error = True
            widget._capture_snapshot()
            attempts = runtime.calls["log"]
            for _ in range(10):
                widget.main()
            self.assertEqual(runtime.calls["log"], attempts)

    def test_wrap_future_clock_failure_and_secret_separation(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            self.assertEqual(widget._age(8, 0xFFFFFFFB), 13)
            self.assertIsNone(widget._age(8, 9))
            with patch.object(widget, "_clock", side_effect=OSError("private clock error")):
                widget._capture_snapshot()
            self.assertIn("state=freshness_unknown", self.assert_private(runtime))
            widget._secret = b"a" * 32
            first = widget._token(EMAIL)
            widget._secret = b"b" * 32
            self.assertNotEqual(first, widget._token(EMAIL))

    def test_partial_startup_keeps_registry_evidence_and_does_not_create_manager(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            sys.modules.pop("Py4GWCoreLib.py4gwcorelib_src.WidgetManager")
            player = sys.modules["Py4GWCoreLib.Player"].__dict__["Player"]
            map_api = sys.modules["Py4GWCoreLib.Map"].__dict__["Map"]
            with patch.object(player, "GetAccountEmail", side_effect=RuntimeError(NAME)):
                with patch.object(map_api, "GetMapID", side_effect=RuntimeError(EMAIL)):
                    widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("email_available=False email_error=RuntimeError", output)
            self.assertIn("map=None map_error=RuntimeError", output)
            self.assertIn("manager_not_loaded", output)
            self.assertIn("HA_STARTUP ACCOUNT slot=0", output)
            self.assertIn("authorized=None/local_identity_unavailable", output)
            self.assertNotIn("Py4GWCoreLib.py4gwcorelib_src.WidgetManager", sys.modules)

    def test_ui_exception_balances_window_without_logging_or_scanning(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            with patch.object(sys.modules["PyImGui"], "text", side_effect=RuntimeError(NAME)):
                widget.main()
            self.assertEqual(runtime.calls, {"end": 1})
            self.assertEqual(runtime.logs, [])

    def test_cold_capture_in_fresh_process_cannot_import_production_or_register_callbacks(self) -> None:
        code = r'''
import importlib.abc, importlib.util, sys, types
attempts, callbacks, output = [], [], []
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("Py4GWCoreLib") or fullname == "PyCallback":
            attempts.append(fullname)
            raise AssertionError("cold import")
def register(*args, **kwargs):
    callbacks.append(args)
    raise AssertionError("callback registration")
sys.modules["PyImGui"] = types.ModuleType("PyImGui")
system = types.ModuleType("PySystem")
system.Console = types.SimpleNamespace(Log=lambda sender, message, level: output.append(message))
system.MessageType = types.SimpleNamespace(Info=0)
sys.modules["PySystem"] = system
callback = types.ModuleType("PyCallback")
callback.PyCallback = types.SimpleNamespace(Register=register)
sys.modules["PyCallback"] = callback
sys.meta_path.insert(0, Guard())
spec = importlib.util.spec_from_file_location("cold_diagnostic", sys.argv[1])
widget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(widget)
widget._capture_snapshot()
assert attempts == [] and callbacks == [], (attempts, callbacks)
assert not any(name.startswith("Py4GWCoreLib") for name in sys.modules)
assert any("registry=unavailable selection=unavailable" in line for line in output)
assert output[-1].startswith("HA_STARTUP END")
assert widget._baseline_number == 0
try:
    __import__("Py4GWCoreLib.HeroAI.command_api")
except AssertionError:
    pass
assert attempts == ["Py4GWCoreLib"], attempts
print("PASS cold capture: no production imports/callbacks; negative-control import trapped")
'''
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(WIDGET)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS cold capture", result.stdout)

    def test_real_interrupt_source_registers_at_import_and_recording_binding_detects_it(self) -> None:
        source = REFERENCE / "Py4GWCoreLib/HeroAI/interrupt.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_register_tick_callback")
        self.assertTrue(
            any(
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Name)
                and n.value.func.id == helper.name
                for n in tree.body
            )
        )
        registered: list[str] = []

        def register(name: str, *args: object, **kwargs: object) -> None:
            del args, kwargs
            registered.append(name)

        def log(*args: object) -> None:
            del args

        binding = types.ModuleType("PyCallback")
        binding.__dict__.update(
            PyCallback=types.SimpleNamespace(Register=register),
            Phase=types.SimpleNamespace(Data=0),
            Context=types.SimpleNamespace(Draw=0),
        )
        scope: dict[str, Any] = {
            "_CALLBACK_NAME": "HeroAI.Interrupt.Tick",
            "cast_observer": types.SimpleNamespace(tick=log),
            "_log": log,
        }
        with patch.dict(sys.modules, {"PyCallback": binding}):
            exec(compile(ast.Module(body=[helper], type_ignores=[]), str(source), "exec"), scope)
            scope[helper.name]()
        self.assertEqual(registered, ["HeroAI.Interrupt.Tick"])

    def test_missing_heroai_keeps_visibility_evidence_without_imports(self) -> None:
        alt = Account(1, ALT, visible=False, selected=False, hidden=True, authorized=False)
        with loaded([Account(0, EMAIL), alt]) as (widget, runtime):
            sys.modules.pop("Py4GWCoreLib.HeroAI.command_api")
            sys.modules.pop("Py4GWCoreLib.HeroAI")
            tripwire = ImportTripwire()
            with patch.object(sys, "meta_path", [tripwire, *sys.meta_path]):
                widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertEqual(tripwire.attempts, [])
            self.assertNotIn("Py4GWCoreLib.HeroAI", sys.modules)
            self.assertEqual(runtime.calls["selected"], 0)
            self.assertIn("selected_error=service_or_instance_not_loaded", output)
            self.assertIn("state=hidden_isolation", output)
            self.assertIn("state=selection_unavailable", output)

    def test_loaded_api_without_instance_is_not_constructed(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            api_type = sys.modules["Py4GWCoreLib.HeroAI.command_api"].__dict__["HeroAICommandAPI"]
            api_type._instance = None
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertEqual(runtime.calls["selected"], 0)
            self.assertIn("state=selection_unavailable", output)
            self.assertNotIn("ERROR stage=capture", output)

    def test_real_loaded_resolver_and_location_predicate_without_cold_import(self) -> None:
        api_path = REFERENCE / "Py4GWCoreLib/HeroAI/command_api.py"
        utils_path = REFERENCE / "Py4GWCoreLib/HeroAI/utils.py"
        api_tree = ast.parse(api_path.read_text(encoding="utf-8"))
        utils_tree = ast.parse(utils_path.read_text(encoding="utf-8"))
        resolver = next(
            n for n in ast.walk(api_tree) if isinstance(n, ast.FunctionDef) and n.name == "_resolve_accounts"
        )
        predicate = next(
            n for n in utils_tree.body if isinstance(n, ast.FunctionDef) and n.name == "SameMapOrPartyAsAccount"
        )
        predicate.decorator_list = []
        api_class = ast.ClassDef(
            name="HeroAICommandAPI",
            bases=[],
            keywords=[],
            body=[resolver],
            decorator_list=[],
        )
        module_tree = ast.fix_missing_locations(
            ast.Module(
                body=[
                    ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                    predicate,
                    api_class,
                ],
                type_ignores=[],
            )
        )
        rows = [Account(0, EMAIL), Account(1, ALT, selected=True)]
        rows[1].AgentData.Map.District = 2
        with loaded(rows) as (widget, runtime):
            cache = sys.modules["Py4GWCoreLib.GlobalCache"].__dict__["GLOBAL_CACHE"]

            def get_players() -> list[object]:
                return []

            cache.Party.GetPlayers = get_players
            map_service = sys.modules["Py4GWCoreLib.Map"].__dict__["Map"]
            map_service.IsExplorable = lambda: False
            scope: dict[str, Any] = {"GLOBAL_CACHE": cache, "Map": map_service}
            exec(compile(module_tree, str(api_path), "exec"), scope)
            real_api = scope["HeroAICommandAPI"]
            real_api._instance = object.__new__(real_api)
            sys.modules["Py4GWCoreLib.HeroAI.command_api"].__dict__["HeroAICommandAPI"] = real_api
            tripwire = ImportTripwire()
            with patch.object(sys, "meta_path", [tripwire, *sys.meta_path]):
                widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("state=excluded_location", output)
            self.assertIn("selected_error=none", output)
            self.assertEqual(tripwire.attempts, [])

    def test_partially_loaded_module_does_not_invoke_lazy_getattr(self) -> None:
        with loaded([Account(0, EMAIL)]) as (widget, runtime):
            api_module = sys.modules["Py4GWCoreLib.HeroAI.command_api"]
            api_module.__dict__.pop("HeroAICommandAPI")
            lazy_reads: list[str] = []

            def lazy(name: str) -> object:
                lazy_reads.append(name)
                raise AssertionError("lazy initialization forbidden")

            api_module.__dict__["__getattr__"] = lazy
            widget._capture_snapshot()
            self.assertIn("state=selection_unavailable", self.assert_private(runtime))
            self.assertEqual(lazy_reads, [])

    def test_local_copy_failure_is_unknown_not_missing(self) -> None:
        with loaded([Account(0, EMAIL, copy_error=True), Account(1, ALT)]) as (widget, runtime):
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("self_slots=[] scan_complete=False", output)
            self.assertIn("self_missing=None", output)
            self.assertNotIn("self_missing=True", output)
            self.assertEqual(widget._baseline_number, 0)

    def test_confirmation_copy_failure_does_not_confirm_absence(self) -> None:
        with loaded([Account(0, EMAIL), Account(1, ALT)]) as (widget, runtime):
            original = Account.from_buffer_copy
            reads = 0

            def copy_row(row: Account) -> Account:
                nonlocal reads
                reads += 1
                if reads == 65:
                    raise RuntimeError(EMAIL)
                return original(row)

            with patch.object(Account, "from_buffer_copy", side_effect=copy_row):
                widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("confirm_errors=[0]", output)
            self.assertIn("self_missing=None", output)

    def test_local_account_published_mid_capture_is_not_reported_missing(self) -> None:
        with loaded([Account(1, ALT)]) as (widget, runtime):
            # Match the real fixed-size slot array; slot 0 has no account initially.
            runtime.AccountData[0] = Account(0, "", IsAccount=False, visible=False, selected=False)
            runtime.AccountData[1] = Account(1, ALT)
            original = getattr(runtime, "_can_communicate")

            def authorize(sender: str, receiver: str) -> bool:
                runtime.AccountData[0] = Account(0, EMAIL)
                return original(sender, receiver)

            with patch.object(runtime, "_can_communicate", side_effect=authorize):
                widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertIn("changed_slots=[0]", output)
            self.assertIn("self_missing=None", output)
            self.assertNotIn("self_missing=True", output)
            self.assertEqual(widget._baseline_number, 0)

    def test_incomplete_layout_and_invalid_identity_cannot_prove_missing(self) -> None:
        for kind in ("short_layout", "invalid_identity"):
            with self.subTest(kind=kind), loaded([Account(0, EMAIL)]) as (widget, runtime):
                if kind == "short_layout":
                    runtime.AccountData.clear()
                else:
                    runtime.AccountData[0].AccountEmail = ""
                widget._capture_snapshot()
                output = self.assert_private(runtime)
                self.assertIn("self_missing=None", output)
                self.assertEqual(widget._baseline_number, 0)

    def test_publication_change_does_not_advance_last_successful_baseline(self) -> None:
        with loaded([Account(0, EMAIL), Account(1, ALT)]) as (widget, runtime):
            widget._capture_snapshot()
            baseline = set(widget._previous_tokens)
            original = getattr(runtime, "_can_communicate")

            def authorize(sender: str, receiver: str) -> bool:
                runtime.AccountData[1].LastUpdated += 1
                return original(sender, receiver)

            runtime.logs.clear()
            with patch.object(runtime, "_can_communicate", side_effect=authorize):
                widget._capture_snapshot()
            self.assertIn("changed_slots=[1]", self.assert_private(runtime))
            self.assertEqual(widget._previous_tokens, baseline)
            self.assertEqual(widget._baseline_number, 1)

    def test_console_failures_at_first_middle_and_end_preserve_disappearance_baseline(self) -> None:
        for position in ("first", "middle", "end", "interrupt"):
            with self.subTest(position=position), loaded([Account(0, EMAIL), Account(1, ALT)]) as (widget, runtime):
                widget._capture_snapshot()
                entries = len(runtime.logs)
                baseline = set(widget._previous_tokens)
                alt_token = widget._token(ALT)
                runtime.AccountData[1] = Account(1, "", IsAccount=False, visible=False, selected=False)
                offset = entries if position == "end" else 3 if position in ("middle", "interrupt") else 1
                runtime.log_failure_at = runtime.calls["log"] + offset
                runtime.log_interrupt = position == "interrupt"
                runtime.logs.clear()
                widget._capture_snapshot()
                self.assertEqual(widget._previous_tokens, baseline)
                self.assertEqual(widget._baseline_number, 1)
                self.assertFalse(any("END snapshot=2" in line for line in runtime.logs))
                self.assertLessEqual(len(runtime.logs), 96)
                attempts = runtime.calls["log"]
                widget.main()
                self.assertEqual(runtime.calls["log"], attempts)
                runtime.log_failure_at = None
                runtime.log_interrupt = False
                runtime.logs.clear()
                widget._capture_snapshot()
                output = self.assert_private(runtime)
                self.assertIn("BEGIN snapshot=3 baseline_snapshot=1", output)
                self.assertIn(f"MISSING_SINCE_PREVIOUS ids={alt_token}", output)
                self.assertEqual(widget._baseline_number, 3)
                self.assertNotIn(alt_token, widget._previous_tokens)

    def test_collect_failure_and_truncated_output_do_not_commit_baseline(self) -> None:
        with loaded([Account(0, EMAIL), Account(1, ALT)]) as (widget, runtime):
            widget._capture_snapshot()
            baseline = set(widget._previous_tokens)
            runtime.registry_error = True
            widget._capture_snapshot()
            self.assertEqual(widget._baseline_number, 1)
            runtime.registry_error = False
            runtime.logs.clear()
            with patch.object(widget, "_MAX_LINES", 4):
                widget._capture_snapshot()
            self.assertEqual(widget._previous_tokens, baseline)
            self.assertEqual(widget._baseline_number, 1)
            self.assertEqual(len(runtime.logs), 4)
            self.assertIn("TRUNCATED", self.assert_private(runtime))

    def test_logger_raises_after_accepting_end_still_does_not_commit(self) -> None:
        with loaded([Account(0, EMAIL), Account(1, ALT)]) as (widget, runtime):
            widget._capture_snapshot()
            baseline = set(widget._previous_tokens)
            runtime.AccountData[1] = Account(1, "", IsAccount=False, visible=False, selected=False)
            original = runtime.log

            def log(sender: str, message: str, level: int) -> None:
                original(sender, message, level)
                if "END snapshot=2" in message:
                    raise RuntimeError("Logger failed after accepting entry")

            console = sys.modules["PySystem"].__dict__["Console"]
            with patch.object(console, "Log", side_effect=log):
                widget._capture_snapshot()
            self.assertEqual(widget._baseline_number, 1)
            self.assertEqual(widget._previous_tokens, baseline)

    def test_all_copy_errors_remain_bounded_and_never_confirm_missing(self) -> None:
        with loaded([Account(i, str(i), copy_error=True) for i in range(64)]) as (widget, runtime):
            widget._capture_snapshot()
            output = self.assert_private(runtime)
            self.assertLessEqual(len(runtime.logs), 96)
            self.assertIn("self_missing=None", output)
            self.assertEqual(output.count("state=read_error"), 64)
            self.assertEqual(widget._baseline_number, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
