"""Exercise retained V1 wire declarations and freshness without injected imports."""

# pyright: strict

from __future__ import annotations

import ast
import ctypes
import importlib.util
import sys
import types
from enum import IntEnum
from importlib import import_module
from pathlib import Path
from typing import Any, cast

pytest: Any = import_module("pytest")

ROOT = Path(__file__).resolve().parents[1]
WIRE = ROOT / "Py4GWCoreLib/GlobalCache/shared_memory_src"


def load_module(name: str, path: Path, monkeypatch: Any) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def build_wire_subject(monkeypatch: Any) -> Any:
    # Evaluate the owning _fields_ declarations, including real enum-derived
    # capacities. Only injected runtime methods/imports are excluded.
    namespace: dict[str, Any] = dict(vars(ctypes), IntEnum=IntEnum)
    enum_tree = ast.parse((ROOT / "Py4GWCoreLib/enums_src/GameData_enums.py").read_text(encoding="utf-8"))
    attribute = next(node for node in enum_tree.body if isinstance(node, ast.ClassDef) and node.name == "Attribute")
    exec(compile(ast.Module([attribute], []), "Attribute", "exec"), namespace)
    globals_tree = ast.parse((WIRE / "Globals.py").read_text(encoding="utf-8"))
    for node in globals_tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            exec(compile(ast.Module([node], []), "Globals", "exec"), namespace)
    pending: list[ast.ClassDef] = []
    paths = [*WIRE.glob("*.py"), ROOT / "Py4GWCoreLib/native_src/internals/types.py"]
    for path in paths:
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "Structure" for base in node.bases
            ):
                fields: list[ast.stmt] = [
                    item
                    for item in node.body
                    if isinstance(item, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id in ("_pack_", "_fields_") for target in item.targets
                    )
                ]
                pending.append(ast.ClassDef(node.name, node.bases, [], fields, []))
    while pending:
        progress = False
        for node in pending[:]:
            try:
                exec(compile(ast.fix_missing_locations(ast.Module([node], [])), "wire", "exec"), namespace)
            except NameError:
                continue
            pending.remove(node)
            progress = True
        assert progress, f"unresolved wire declarations: {[node.name for node in pending]}"
    package_name = "_publication_wire"
    package = types.ModuleType(package_name)
    package.__path__ = [str(WIRE)]
    monkeypatch.setitem(sys.modules, package_name, package)
    for name in ("AccountStruct", "AllAccounts", "KeyStruct", "Globals"):
        module = types.ModuleType(f"{package_name}.{name}")
        module.__dict__.update({key: value for key, value in namespace.items() if not key.startswith("__")})
        monkeypatch.setitem(sys.modules, module.__name__, module)
    clock = load_module(f"{package_name}.IntentSync", WIRE / "IntentSync.py", monkeypatch)
    return types.SimpleNamespace(**namespace, clock=clock)


@pytest.fixture
def account_world(monkeypatch: Any) -> Any:
    """Use the real wire layout and readers with controlled host clocks."""
    wire = build_wire_subject(monkeypatch)
    clock = types.SimpleNamespace(frame=10000, uncached=10000, hwnd=0)
    logs: list[tuple[str, str, int]] = []

    def log(module: str, message: str, level: int) -> None:
        logs.append((module, message, level))

    system = types.ModuleType("PySystem")
    system.__dict__.update(
        get_tick_count64=lambda: clock.frame,
        Console=types.SimpleNamespace(
            Log=log,
            get_gw_window_handle=lambda: clock.hwnd,
            MessageType=types.SimpleNamespace(Info=0, Warning=1, Error=2),
        ),
    )
    monkeypatch.setitem(sys.modules, "PySystem", system)
    sender, receiver = "sender@example.invalid", "receiver@example.invalid"
    player = types.ModuleType("Py4GWCoreLib.Player")
    player.__dict__.update(Player=types.SimpleNamespace(GetAccountEmail=lambda: sender))
    monkeypatch.setitem(sys.modules, player.__name__, player)
    whiteboard = load_module("_active_whiteboard", WIRE.parents[1] / "enums_src/Whiteboard_enums.py", monkeypatch)

    tree = ast.parse((WIRE / "AllAccounts.py").read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AllAccounts")
    # Retain the owning methods over the real ctypes fields, without importing
    # the injected facade or repeating its field declarations.
    owner.bases = [ast.Name("WireAccounts", ast.Load())]
    owner.body = [node for node in owner.body if not isinstance(node, (ast.Assign, ast.AnnAssign))]
    namespace: dict[str, Any] = dict(
        cast(dict[str, Any], vars(wire)),
        __name__="_active_account_fixture",
        __package__="Py4GWCoreLib.GlobalCache.shared_memory_src",
        __spec__=None,
        WireAccounts=wire.AllAccounts,
        PySystem=system,
        ConsoleLog=log,
        publication_age=wire.clock.publication_age,
        publication_is_live=wire.clock.publication_is_live,
        get_uncached_tick_count64=lambda: clock.uncached,
    )
    whiteboard_symbols = cast(dict[str, Any], vars(whiteboard))
    namespace.update({name: value for name, value in whiteboard_symbols.items() if not name.startswith("__")})
    module = ast.Module([ast.ImportFrom("__future__", [ast.alias("annotations")], 0), owner], [])
    exec(compile(ast.fix_missing_locations(module), str(WIRE / "AllAccounts.py"), "exec"), namespace)
    table = namespace["AllAccounts"]()
    for index, email in enumerate((sender, receiver)):
        row = table.AccountData[index]
        row.AccountEmail = email
        row.IsAccount = True
        row.IsSlotActive = True
        row.LastUpdated = clock.uncached

    return types.SimpleNamespace(table=table, wire=wire, clock=clock, logs=logs, sender=sender, receiver=receiver)


@pytest.fixture
def subject(monkeypatch: Any) -> Any:
    return build_wire_subject(monkeypatch)


def accounts(subject: Any) -> Any:
    table = subject.AllAccounts()
    row = table.AccountData[0]
    row.AccountEmail = "owner"
    row.IsSlotActive = True
    row.IsAccount = True
    row.Key.HWND = 100
    table.Keys[0] = row.Key
    return table


def test_v1_layout_and_name(subject: Any) -> None:
    assert ctypes.sizeof(subject.AllAccounts) == 940096
    assert ctypes.sizeof(subject.AccountStruct) == 13639
    assert subject.AllAccounts.Inbox.offset == 873920
    assert subject.AccountStruct.IsIsolated.offset == 13621
    assert subject.AccountStruct.LastUpdated.offset == 13635
    assert subject.SHMEM_SHARED_MEMORY_FILE_NAME == "Py4GW_Shared_Mem"


@pytest.mark.parametrize(
    "last,now,live",
    [
        (0, 4999, True),
        (0, 5000, False),
        (0xFFFFFFF0, 0xFFFFFFF0 + 4999, True),
        (0xFFFFFFF0, 0xFFFFFFF0 + 5000, False),
        (100, 99, False),
        (0, 0x80000000, False),
    ],
)
def test_lease_boundaries(subject: Any, last: int, now: int, live: bool) -> None:
    assert subject.clock.publication_is_live(now, last) is live


def test_legacy_lease_and_duplicate_order_use_modular_clock(subject: Any) -> None:
    tree = ast.parse((WIRE / "AllAccounts.py").read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AllAccounts")
    methods: list[ast.stmt] = [
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in ("GetAccountData", "_is_slot_active", "_is_slot_expired", "GetExpiredSlots", "_find_account_slot_by_email")
    ]
    clock = types.SimpleNamespace(
        get_tick_count64=lambda: 5, Console=types.SimpleNamespace(get_gw_window_handle=lambda: 0)
    )
    namespace: dict[str, Any] = dict(
        WireAccounts=subject.AllAccounts,
        PySystem=clock,
        get_uncached_tick_count64=lambda: clock.get_tick_count64(),
        publication_age=subject.clock.publication_age,
        publication_is_live=subject.clock.publication_is_live,
        SHMEM_MAX_PLAYERS=subject.SHMEM_MAX_PLAYERS,
        SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS=5000,
    )
    isolated = ast.ClassDef("LegacyAccounts", [ast.Name("WireAccounts", ast.Load())], [], methods, [])
    exec(compile(ast.fix_missing_locations(ast.Module([isolated], [])), "legacy_leases", "exec"), namespace)
    table = namespace["LegacyAccounts"].from_buffer_copy(bytes(accounts(subject)))
    table.AccountData[3] = table.AccountData[0]
    table.AccountData[0].LastUpdated = 0xFFFFFFF0
    table.AccountData[3].LastUpdated = 0
    assert table._find_account_slot_by_email("owner") == 3
    assert table._is_slot_active(0)
    table.AccountData[3].LastUpdated = 6
    assert not table._is_slot_active(3)
    assert not table._is_slot_expired(3)  # future is not permission to evict
    assert table._find_account_slot_by_email("owner") == 0
    table.AccountData[0].LastUpdated = 0
    clock.get_tick_count64 = lambda: 4999
    assert table._is_slot_active(0) and not table._is_slot_expired(0)
    clock.get_tick_count64 = lambda: 5000
    assert not table._is_slot_active(0) and table._is_slot_expired(0)
    assert 0 in table.GetExpiredSlots()
