"""Exercise the real detached reader and wire declarations without injected imports."""

# pyright: strict

from __future__ import annotations
import __future__

import ast
import ctypes
import importlib.util
import sys
import types
from enum import IntEnum
from importlib import import_module
from pathlib import Path
from typing import Any
from typing import cast

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


@pytest.fixture
def subject(monkeypatch: Any) -> Any:
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
    reader = load_module(f"{package_name}.AccountPublication", WIRE / "AccountPublication.py", monkeypatch)
    return types.SimpleNamespace(**namespace, reader=reader, clock=clock)


def cohort(subject: Any, tick: int = 0) -> Any:
    table = subject.AllAccounts()
    for index in range(3):
        row = table.AccountData[index]
        row.AccountEmail = "owner"
        row.IsSlotActive = True
        row.SlotNumber = index
        row.LastUpdated = tick
        row.Key.HWND = 100
        row.Key.EntityType = index
        row.Key.LocalIndex = 7 if index == 1 else 0
        row.IsAccount = index == 0
        row.IsHero = index == 1
        row.IsPet = index == 2
        row.AgentData.AgentID = 1000 + index
        row.AgentData.LoginNumber = 1 if index == 0 else 0
        row.AgentData.OwnerAgentID = 1000 if index else 0
        row.AgentData.HeroID = 7 if index == 1 else 0
        row.AgentData.Map.MapID = 10
        row.AgentPartyData.PartyID = 5
        table.Keys[index] = row.Key
    return table


def envelope_v3(subject: Any, tick: int = 100, instance: int = 0) -> Any:
    reader = subject.reader
    envelope = reader._EnvelopeWireV3()
    h = envelope.header
    h.magic = 0x3356425747345950
    h.version = 3
    h.header_size = ctypes.sizeof(reader._HeaderWireV3)
    h.envelope_size = ctypes.sizeof(envelope)
    h.live_size = subject.AllAccounts.Inbox.offset
    h.account_size = ctypes.sizeof(subject.AccountStruct)
    h.owner_size = ctypes.sizeof(reader._OwnerWireV3)
    h.witness_size = ctypes.sizeof(reader._BuildWitnessWireV3)
    h.owner_capacity = subject.SHMEM_MAX_PLAYERS
    h.witness_capacity = subject.SHMEM_MAX_BUILD_WITNESSES
    h.recovery_epoch = 1
    table = cohort(subject, tick)
    if instance == 0:
        table.AccountData[1].IsSlotActive = False
        table.AccountData[2].IsSlotActive = False
    table.AccountData[0].AgentData.UUID[0] = 123
    ctypes.memmove(
        ctypes.addressof(envelope) + reader._EnvelopeWireV3.keys.offset, ctypes.addressof(table), h.live_size
    )
    h.live_count = sum(bool(row.IsSlotActive) for row in envelope.accounts)
    h.owner_count = 1
    meta = envelope.owners[0]
    meta.active = 1
    meta.instance_type = instance
    meta.instance_epoch = 1 if instance == 0 else 3
    meta.published_tick = tick & 0xFFFFFFFF
    meta.witness_count = 1
    meta.incarnation[0] = 77
    meta.character_uuid[0] = 123
    witness = meta.witnesses[0]
    witness.kind = 1
    witness.hero_id = 7
    witness.primary = 5
    witness.secondary = 8
    witness.skills[:] = [65, 57, 979, 934, 67, 1336, 25, 791]
    witness.revision = 1
    witness.outpost_epoch = 1
    witness.observed_at_tick64 = tick
    return envelope


def decode_v3(subject: Any, envelope: Any, now: int = 101) -> Any:
    return subject.reader.read_native_account_snapshot_v3(lambda: ("success", now, bytes(envelope)))


@pytest.mark.parametrize("instance", [0, 1])
def test_v3_valid_detached_cohort(subject: Any, instance: int) -> None:
    envelope = envelope_v3(subject, instance=instance)
    calls = 0

    def read() -> tuple[str, int, bytes]:
        nonlocal calls
        calls += 1
        return "success", 101, bytes(envelope)

    result = subject.reader.read_native_account_snapshot_v3(read)
    assert result.status is subject.reader.AccountPublicationStatus.SUCCESS, result.reason
    snapshot = result.snapshot
    assert snapshot and calls == 1
    assert len(snapshot.accounts) == (1 if instance == 0 else 3)
    owner = snapshot.cohorts[0]
    assert len(owner.witnesses) == 1
    witness = owner.witnesses[0]
    assert witness.hero_id == 7 and witness.skills[0] == 65
    assert witness.observed_at_tick64 == 100 and witness.revision == 1
    assert owner.character_uuid == (123, 0, 0, 0)
    envelope.owners[0].witnesses[0].skills[0] = 39
    envelope.accounts[0].AgentData.AgentID = 99
    assert witness.skills[0] == 65 and owner.owner.GetAccountData().AgentData.AgentID == 1000
    detached = owner.owner.GetAccountData()
    detached.AgentData.AgentID = 77
    assert owner.owner.GetAccountData().AgentData.AgentID == 1000
    assert "owner" not in repr(snapshot)  # account identity/payload omitted from normal diagnostics


@pytest.mark.parametrize(
    "field,value",
    [
        ("magic", 0),
        ("version", 4),
        ("header_size", 1),
        ("envelope_size", 1),
        ("live_size", 1),
        ("account_size", 1),
        ("owner_size", 1),
        ("witness_size", 1),
        ("owner_capacity", 65),
        ("witness_capacity", 8),
        ("live_count", 65),
        ("live_count", 0),
        ("owner_count", 65),
        ("owner_count", 0),
        ("recovery_epoch", 0),
    ],
)
def test_v3_reject_layout(subject: Any, field: str, value: int) -> None:
    envelope = envelope_v3(subject)
    setattr(envelope.header, field, value)
    result = decode_v3(subject, envelope)
    assert result.snapshot is None and result.status is subject.reader.AccountPublicationStatus.SYNC_FAILURE, field


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", 2),
        ("hero_id", 0),
        ("primary", 0),
        ("primary", 11),
        ("secondary", 11),
        ("revision", 0),
        ("outpost_epoch", 0),
        ("outpost_epoch", 2),
        ("observed_at_tick64", 102),
    ],
)
def test_v3_reject_witness(subject: Any, field: str, value: int) -> None:
    envelope = envelope_v3(subject)
    setattr(envelope.owners[0].witnesses[0], field, value)
    assert decode_v3(subject, envelope).snapshot is None, field


@pytest.mark.parametrize(
    "case",
    [
        "skills",
        "duplicate",
        "count",
        "incarnation",
        "uuid",
        "owner",
        "stamp",
        "epoch",
        "phase",
        "unassociated",
        "destination",
    ],
)
def test_v3_reject_association(subject: Any, case: str) -> None:
    envelope = envelope_v3(subject, instance=1 if case == "destination" else 0)
    meta = envelope.owners[0]
    if case == "skills":
        meta.witnesses[0].skills[7] = 0
    elif case == "duplicate":
        meta.witness_count = 2
        meta.witnesses[1] = meta.witnesses[0]
    elif case == "count":
        meta.witness_count = 8
    elif case == "incarnation":
        meta.incarnation[0] = 0
    elif case == "uuid":
        meta.character_uuid[0] = 124
    elif case == "owner":
        envelope.accounts[0].IsAccount = False
    elif case == "stamp":
        meta.published_tick = 99
    elif case == "epoch":
        meta.instance_epoch = 0
    elif case == "phase":
        meta.instance_type = 2
    elif case == "unassociated":
        meta.active = 0
        envelope.header.owner_count = 0
    elif case == "destination":
        meta.witnesses[0].hero_id = 8
    assert decode_v3(subject, envelope).snapshot is None, case


@pytest.mark.parametrize("age,count", [(4999, 1), (5000, 0), (0x80000000, 0), (0xFFFFFFFF, 0)])
def test_v3_modular_lease(subject: Any, age: int, count: int) -> None:
    tick = 0xFFFFFFF0
    envelope = envelope_v3(subject, tick=tick)
    result = decode_v3(subject, envelope, now=tick + age)
    assert result.snapshot and len(result.snapshot.cohorts) == count


@pytest.mark.parametrize("status", ["busy", "unavailable", "recovery", "sync_failure"])
def test_v3_failure_has_no_evidence(subject: Any, status: str) -> None:
    result = subject.reader.read_native_account_snapshot_v3(lambda: (status, 0, b""))
    assert result.snapshot is None and result.status.value == status


def test_v3_missing_binding_and_invalid_payload(subject: Any) -> None:
    reader = subject.reader
    assert reader.read_native_account_snapshot_v3(None).status is reader.AccountPublicationStatus.UNAVAILABLE
    for payload in (b"", bytes(envelope_v3(subject))[:-1], bytearray(bytes(envelope_v3(subject)))):
        result = reader.read_native_account_snapshot_v3(lambda: ("success", 101, payload))
        assert result.snapshot is None
    success = decode_v3(subject, envelope_v3(subject))
    assert success.snapshot
    assert reader.read_native_account_snapshot_v3(lambda: ("busy", 101, b"")).snapshot is None


def transport(subject: Any, table: Any, now: int = 1, status: str = "success") -> tuple[Any, ...]:
    return (
        status,
        now,
        bytes(table)[: subject.AllAccounts.Inbox.offset],
        subject.AllAccounts.Inbox.offset,
        ctypes.sizeof(subject.AllAccounts),
        subject.AccountStruct.IsIsolated.offset,
        subject.AccountStruct.LastUpdated.offset,
    )


def read(subject: Any, table: Any, now: int = 1) -> Any:
    return subject.reader.read_native_account_snapshot(lambda: transport(subject, table, now))


def test_native_layout_and_names(subject: Any) -> None:
    # These values are also asserted and printed by the production Native tests.
    assert ctypes.sizeof(subject.AllAccounts) == 940096
    assert ctypes.sizeof(subject.AccountStruct) == 13639
    assert subject.AllAccounts.Inbox.offset == 873920
    assert subject.AccountStruct.IsIsolated.offset == 13621
    assert subject.AccountStruct.LastUpdated.offset == 13635
    assert subject.SHMEM_SHARED_MEMORY_FILE_NAME == "Py4GW_Shared_Mem"
    assert subject.SHMEM_NATIVE_EVIDENCE_NAME == "Py4GW_Shared_Mem.v2"
    assert subject.SHMEM_NATIVE_PUBLICATION_MUTEX == r"Local\Py4GW.AccountPublication.v2"


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
    result = read(subject, cohort(subject, last), now)
    assert result.status is subject.reader.AccountPublicationStatus.SUCCESS
    assert len(result.snapshot.accounts) == (3 if live else 0)


def test_detached_evidence_and_reserved_coordination(subject: Any) -> None:
    table = cohort(subject)
    table.AccountData[0].IsolationGroupID = 123
    result = read(subject, table)
    assert len(result.snapshot.accounts) == 3
    owned = result.snapshot.accounts[0].GetAccountData()
    assert owned.IsolationGroupID == 0
    assert table.AccountData[0].IsolationGroupID == 123
    original = result.snapshot.accounts[0].data
    table.AccountData[0].AgentData.AgentID = 999
    owned.AgentData.AgentID = 888
    assert result.snapshot.accounts[0].data == original
    assert result.snapshot.accounts[0].GetAccountData().AgentData.AgentID == 1000


@pytest.mark.parametrize("status", ["busy", "unavailable", "recovery", "sync_failure"])
def test_failures_never_reuse_success(subject: Any, status: str) -> None:
    table = cohort(subject)
    replies = iter([transport(subject, table), transport(subject, table, status=status)])
    reader = lambda: next(replies)
    assert subject.reader.read_native_account_snapshot(reader).snapshot is not None
    failed = subject.reader.read_native_account_snapshot(reader)
    assert failed.status.value == status
    assert failed.snapshot is None
    assert subject.reader.read_native_account_snapshot(None).snapshot is None


@pytest.mark.parametrize("field", [2, 3, 4, 5, 6])
def test_layout_failure_is_closed(subject: Any, field: int) -> None:
    reply = list(transport(subject, cohort(subject)))
    reply[field] = b"" if field == 2 else reply[field] + 1
    failed = subject.reader.read_native_account_snapshot(lambda: tuple(reply))
    assert failed.status.value == "sync_failure"
    assert failed.snapshot is None


@pytest.mark.parametrize(
    "defect",
    ["external_key", "tick", "owner", "map", "party", "type", "agent", "hero_key", "pet_key", "hwnd", "inactive_owner"],
)
def test_malformed_child_rejects_whole_cohort(subject: Any, defect: str) -> None:
    table = cohort(subject)
    child = table.AccountData[1]
    if defect == "external_key":
        table.Keys[1].HWND = 200
    elif defect == "tick":
        child.LastUpdated = 1
    elif defect == "owner":
        child.AgentData.OwnerAgentID = 3000
    elif defect == "map":
        child.AgentData.Map.MapID = 20
    elif defect == "party":
        child.AgentPartyData.PartyID = 6
    elif defect == "type":
        child.IsPet = True
    elif defect == "agent":
        child.AgentData.AgentID = 1000
    elif defect == "hero_key":
        child.AgentData.HeroID = 8
    elif defect == "pet_key":
        table.AccountData[2].Key.LocalIndex = 42
    elif defect == "hwnd":
        child.Key.HWND = table.Keys[1].HWND = 200
    elif defect == "inactive_owner":
        table.AccountData[0].IsSlotActive = False
    result = read(subject, table)
    assert result.status.value == "success"
    assert result.snapshot.accounts == (), defect


@pytest.mark.parametrize("duplicate", ["owner", "hwnd", "hero"])
def test_duplicate_identities_rejected(subject: Any, duplicate: str) -> None:
    table = cohort(subject)
    table.AccountData[3] = table.AccountData[1 if duplicate == "hero" else 0]
    table.AccountData[3].SlotNumber = 3
    if duplicate == "hwnd":
        table.AccountData[3].Key.HWND = 200
    table.Keys[3] = table.AccountData[3].Key
    assert read(subject, table).snapshot.accounts == ()


def test_loading_owner_cannot_be_used(subject: Any) -> None:
    table = cohort(subject)
    table.AccountData[0].AgentData.AgentID = 0
    assert read(subject, table).snapshot.accounts == ()


def test_legacy_writable_api_cannot_attach_v2(subject: Any) -> None:
    source = ROOT / "Py4GWCoreLib/GlobalCache/SharedMemory.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    owner = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Py4GWSharedMemoryManager"
    )
    methods: list[ast.stmt] = [
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in (
            "__init__",
            "_attach",
            "GetAllAccounts",
            "GetNativeAccountSnapshot",
            "GetNativeAccountSnapshotV3",
            "GetAccountData",
            "ResetPlayerData",
            "SetPlayerData",
            "SetHeroesData",
            "SetPetData",
            "GetHeroSlotByHeroData",
            "GetPetSlotByPetData",
        )
    ]
    for node in methods:
        assert isinstance(node, ast.FunctionDef)
        node.decorator_list = []
    namespace: dict[str, Any] = dict(
        cast(dict[str, Any], vars(subject)),
        sizeof=ctypes.sizeof,
        PySystem=types.SimpleNamespace(),
        read_native_account_snapshot=subject.reader.read_native_account_snapshot,
        AccountPublicationResult=subject.reader.AccountPublicationResult,
        read_native_account_snapshot_v3=subject.reader.read_native_account_snapshot_v3,
        AccountPublicationResultV3=subject.reader.AccountPublicationResultV3,
    )
    isolated = ast.ClassDef(owner.name, [], [], methods, [])
    exec(
        compile(
            ast.fix_missing_locations(ast.Module([isolated], [])),
            str(source),
            "exec",
            flags=__future__.annotations.compiler_flag,
        ),
        namespace,
    )
    manager_type = namespace[owner.name]
    for name in (
        subject.SHMEM_NATIVE_EVIDENCE_NAME,
        "Local\\" + subject.SHMEM_NATIVE_EVIDENCE_NAME,
        subject.SHMEM_NATIVE_EVIDENCE_NAME_V3,
        "Local\\" + subject.SHMEM_NATIVE_EVIDENCE_NAME_V3,
    ):
        with pytest.raises(ValueError):
            manager_type(name)
        manager = object.__new__(manager_type)
        manager.shm_name = name
        manager.shm = types.SimpleNamespace(buf=bytearray(ctypes.sizeof(subject.AllAccounts)))
        manager.max_num_players = subject.SHMEM_MAX_PLAYERS
        with pytest.raises(ValueError):
            manager._attach()
        with pytest.raises(ValueError):
            manager.GetAllAccounts()
        for writer, arguments in (
            (manager.ResetPlayerData, (0,)),
            (manager.SetPlayerData, ("owner",)),
            (manager.SetHeroesData, ()),
            (manager.SetPetData, ()),
            (manager.GetHeroSlotByHeroData, (None,)),
            (manager.GetPetSlotByPetData, (None,)),
        ):
            with pytest.raises(ValueError):
                writer(*arguments)
    manager = object.__new__(manager_type)
    assert manager.GetNativeAccountSnapshot().status.value == "unavailable"
    assert manager.GetNativeAccountSnapshot().snapshot is None
    # Older DLL capability fails closed even though its v2 binding is present.
    v2_calls = 0

    def older_dll_v2_read() -> tuple[Any, ...]:
        nonlocal v2_calls
        v2_calls += 1
        return transport(subject, cohort(subject))

    namespace["PySystem"].get_account_publication_snapshot = older_dll_v2_read
    assert manager.GetNativeAccountSnapshotV3().status.value == "unavailable"
    assert manager.GetNativeAccountSnapshotV3().snapshot is None
    assert v2_calls == 0
    v3_replies = iter((("success", 101, bytes(envelope_v3(subject))), ("busy", 101, b"")))
    namespace["PySystem"].get_account_publication_snapshot_v3 = lambda: next(v3_replies)
    assert manager.GetNativeAccountSnapshotV3().snapshot is not None
    assert manager.GetNativeAccountSnapshotV3().snapshot is None
    # No legacy access occurs on either snapshot call; this object has no shm.
    replies = iter((transport(subject, cohort(subject)), transport(subject, cohort(subject), status="busy")))
    namespace["PySystem"].get_account_publication_snapshot = lambda: next(replies)
    assert manager.GetNativeAccountSnapshot().snapshot is not None
    assert manager.GetNativeAccountSnapshot().snapshot is None


def test_nonterminated_email_is_rejected(subject: Any) -> None:
    table = cohort(subject)
    table.AccountData[0].AccountEmail = "x" * subject.SHMEM_MAX_EMAIL_LEN
    assert read(subject, table).snapshot.accounts == ()


def test_mutable_binding_payload_is_rejected(subject: Any) -> None:
    reply = list(transport(subject, cohort(subject)))
    reply[2] = bytearray(reply[2])
    failed = subject.reader.read_native_account_snapshot(lambda: tuple(reply))
    assert failed.status.value == "sync_failure" and failed.snapshot is None


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
        publication_age=subject.clock.publication_age,
        publication_is_live=subject.clock.publication_is_live,
        SHMEM_MAX_PLAYERS=subject.SHMEM_MAX_PLAYERS,
        SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS=5000,
    )
    isolated = ast.ClassDef("LegacyAccounts", [ast.Name("WireAccounts", ast.Load())], [], methods, [])
    exec(compile(ast.fix_missing_locations(ast.Module([isolated], [])), "legacy_leases", "exec"), namespace)
    table = namespace["LegacyAccounts"].from_buffer_copy(bytes(cohort(subject)))
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
