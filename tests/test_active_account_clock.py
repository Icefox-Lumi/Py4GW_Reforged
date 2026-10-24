"""Real central readers, facade frame cache and HeroAI consumers without injection."""

from __future__ import annotations

import ast
import ctypes
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from test_account_publication import ROOT, account_world as _world_fixture, load_module

world = _world_fixture


def _pair(world: Any) -> Any:
    table = world.table
    for index, row in enumerate(table.AccountData[:2]):
        row.LastUpdated = world.clock.uncached & 0xFFFFFFFF
        row.AgentData.AgentID = 101 + index
        row.AgentData.Map.MapID = 1
        row.AgentPartyData.PartyID = 7
        row.AgentPartyData.PartyPosition = index
        row.AgentData.Energy.Current = 0.25
        row.AgentData.Buffs.Buffs[0].SkillId = 42
    return table


def _ids(rows: Any) -> list[int]:
    return [int(row.AgentData.AgentID) for row in rows]


@pytest.mark.parametrize("lag", [1, 15, 16])
def test_frame_lag_central_readers(world: Any, lag: int) -> None:
    world.clock.uncached = world.clock.frame + lag
    table = _pair(world)
    before = bytes(table)
    assert table._is_slot_active(1), f"frame={world.clock.frame}, publication=current={world.clock.uncached}"
    assert table.GetVisibleSlotByEmail(world.receiver) == 1
    assert table.GetAccountDataFromEmail(world.receiver).AgentData.AgentID == 102
    assert table.GetAccountDataFromPartyNumber(1).AgentData.AgentID == 102
    assert _ids(table.GetAllActivePlayers()) == [101, 102]
    assert _ids(table.GetAllActivePlayers(include_isolated=True)) == [101, 102]
    assert _ids(table.GetAllActiveSlotsData()) == [101, 102]
    assert table.GetNumActivePlayers() == table.GetNumActiveSlots() == 2
    assert len(table.GetAllAccountHeroAIOptions()) == 2
    assert _ids([row for row, _ in table.GetAllActiveAccountHeroAIPairs()]) == [101, 102]
    assert table.GetHeroAIOptionsFromEmail(world.receiver) is not None
    assert table.GetHeroAIOptionsByPartyNumber(1) is not None
    assert table.GetMapsFromPlayers() == [(1, 0, 0, 0)]
    assert table.GetPartiesFromMaps(1, 0, 0, 0) == [7]
    assert _ids(table.GetPlayersFromParty(7, 1, 0, 0, 0)) == [101, 102]
    assert table.AccountHasEffect(world.receiver, 42)
    assert bytes(table) == before, "visibility readers must not publish or reclaim"


@pytest.mark.parametrize(
    "now,published,live",
    [
        (10016, 10016, True),
        (10016, 5017, True),
        (10016, 5016, False),
        (10016, 5015, False),
        (10016, 10017, False),
        (0x100000005, 0xFFFFFFF0, True),
        (0x100000005, (5 - 4999) & 0xFFFFFFFF, True),
        (0x100000005, (5 - 5000) & 0xFFFFFFFF, False),
        (0x100000005, 6, False),
        (0x100000005, 0x80000005, False),
        (0x80000000, 0, False),
    ],
)
def test_freshness_boundaries(world: Any, now: int, published: int, live: bool) -> None:
    world.clock.uncached = now
    world.clock.frame = now - 16
    table = _pair(world)
    table.AccountData[1].LastUpdated = published
    before = bytes(table)
    assert table._is_slot_active(1) is live, (now, published, live)
    assert (table.GetVisibleSlotByEmail(world.receiver) == 1) is live
    assert (table.GetAccountDataFromEmail(world.receiver) is not None) is live
    assert (102 in _ids(table.GetAllActivePlayers())) is live
    assert (102 in _ids(table.GetAllActiveSlotsData())) is live
    assert bytes(table) == before


@pytest.mark.parametrize("case", ["inactive", "missing", "wrong_case", "non_account", "zeroed", "bad_timestamp"])
def test_missing_and_invalid_account_publications(world: Any, case: str) -> None:
    table = _pair(world)
    email = world.receiver
    if case == "inactive":
        table.AccountData[1].IsSlotActive = False
    elif case == "missing":
        email = "missing@example.invalid"
    elif case == "wrong_case":
        email = world.receiver.upper()
    elif case == "non_account":
        table.AccountData[1].IsAccount = False
    elif case == "zeroed":
        table.AccountData[1] = world.wire.AccountStruct()
    else:
        table.AccountData[1].LastUpdated = 0xFFFFFFFF
    before = bytes(table)
    assert table.GetVisibleSlotByEmail(email) == -1, case
    assert table.GetAccountDataFromEmail(email) is None, case
    assert table.GetAccountDataFromEmail("") is None
    assert not table._is_slot_active(63), "unpublished slot"
    with pytest.raises(IndexError):
        table._is_slot_active(64)
    with pytest.raises(TypeError):
        table.AccountData[63].LastUpdated = "malformed"
    assert bytes(table) == before


@pytest.mark.parametrize(
    "local_group,remote_group,isolated,visible",
    [
        (0, 0, False, True),
        (0, 0, True, False),
        (4, 4, True, True),
        (4, 5, False, False),
        (0, 4, False, False),
        (4, 0, False, False),
    ],
)
def test_isolation_and_owned_entities(
    world: Any, monkeypatch: pytest.MonkeyPatch, local_group: int, remote_group: int, isolated: bool, visible: bool
) -> None:
    world.clock.uncached += 16
    table = _pair(world)
    player_module = ModuleType("Py4GWCoreLib.Player")
    player_module.__dict__.update(Player=SimpleNamespace(GetAccountEmail=lambda: world.sender))
    monkeypatch.setitem(sys.modules, player_module.__name__, player_module)
    monkeypatch.setitem(
        table._get_local_group_id.__globals__, "__package__", "Py4GWCoreLib.GlobalCache.shared_memory_src"
    )
    table.AccountData[0].IsolationGroupID = local_group
    table.AccountData[0].IsIsolated = True
    table.AccountData[1].IsolationGroupID = remote_group
    table.AccountData[1].IsIsolated = isolated
    for index, flag in [(2, "IsHero"), (3, "IsPet")]:
        table.AccountData[index] = table.AccountData[1]
        table.AccountData[index].IsAccount = False
        setattr(table.AccountData[index], flag, True)
        table.AccountData[index].AgentData.AgentID = 101 + index
        table.AccountData[index].AgentData.OwnerAgentID = 102
    before = bytes(table)
    assert _ids(table.GetAllActivePlayers()) == ([101, 102] if visible else [101])
    assert _ids(table.GetAllActiveSlotsData()) == ([101, 102, 103, 104] if visible else [101])
    assert _ids(table.GetHeroesFromPlayers(102)) == ([103] if visible else [])
    assert _ids(table.GetPetsFromPlayers(102)) == ([104] if visible else [])
    assert _ids(table.GetAllActivePlayers(include_isolated=True)) == [101, 102]
    assert bytes(table) == before


def test_duplicate_selection_and_raw_enumeration_contract(world: Any) -> None:
    world.clock.uncached += 16
    table = _pair(world)
    table.AccountData[2] = table.AccountData[1]
    table.AccountData[2].AgentData.AgentID = 103
    table.AccountData[1].LastUpdated -= 1
    assert table.GetVisibleSlotByEmail(world.receiver) == 2, "newest live duplicate wins across frame lag"
    assert _ids(table.GetAllActivePlayers()) == [101, 102, 103], "enumeration does not deduplicate"
    table.AccountData[1].LastUpdated += 1
    assert table.GetVisibleSlotByEmail(world.receiver) == 2, "equal timestamps prefer higher slot"
    world.clock.hwnd = 123
    table.Keys[1].HWND = 123
    assert table.GetVisibleSlotByEmail(world.receiver) == 1, "live local HWND takes priority"
    table.AccountData[1].LastUpdated -= 5000
    assert table.GetVisibleSlotByEmail(world.receiver) == 2, "expired local row cannot hide a live duplicate"
    table.AccountData[2].LastUpdated = world.clock.uncached + 1
    assert table.GetVisibleSlotByEmail(world.receiver) == -1
    assert table._find_account_slot_by_email(world.receiver) == 1, "raw fallback remains newest comparable row"


@pytest.mark.parametrize("published,expired", [(10016, False), (10017, False), (5001, False), (5000, True)])
def test_reclamation_remains_conservative(world: Any, published: int, expired: bool) -> None:
    world.clock.uncached = 10016
    table = _pair(world)
    for row in table.AccountData:
        row.IsSlotActive = True
        row.LastUpdated = 10016
    table.AccountData[1].LastUpdated = published
    before = bytes(table)
    assert table._is_slot_expired(1) is expired
    assert table.GetExpiredSlots() == ([1] if expired else [])
    assert table.GetEmptySlot() == (1 if expired else -1)
    assert bytes(table) == before


@pytest.mark.parametrize(
    "method,args",
    [
        ("GetAllActivePlayers", ()),
        ("GetAllActiveSlotsData", ()),
        ("GetNumActiveSlots", ()),
        ("GetAllAccountHeroAIOptions", ()),
        ("GetAllActiveAccountHeroAIPairs", ()),
        ("GetHeroesFromPlayers", (102,)),
        ("GetPetsFromPlayers", (102,)),
        ("GetAccountDataFromPartyNumber", (99,)),
        ("GetHeroAIOptionsByPartyNumber", (99,)),
        ("GetMapsFromPlayers", ()),
        ("GetPartiesFromMaps", (1, 0, 0, 0)),
        ("GetPlayersFromParty", (7, 1, 0, 0, 0)),
    ],
)
def test_stable_enumeration_reads_clock_once(
    world: Any, monkeypatch: pytest.MonkeyPatch, method: str, args: tuple[int, ...]
) -> None:
    table = _pair(world)
    for index in range(2, 64):
        table.AccountData[index] = table.AccountData[1]
        table.AccountData[index].AccountEmail = f"account{index}@example.invalid"
    reads: list[int] = []

    def clock() -> int:
        reads.append(world.clock.uncached)
        return world.clock.uncached

    monkeypatch.setitem(table._is_slot_active.__globals__, "get_uncached_tick_count64", clock)
    getattr(table, method)(*args)
    assert reads == [10000], (method, reads)


@pytest.mark.parametrize("published,live", [(10016, True), (10017, False), (0x80002710, False)])
def test_publication_after_scan_sample_is_checked_with_new_time(
    world: Any, monkeypatch: pytest.MonkeyPatch, published: int, live: bool
) -> None:
    table = _pair(world)
    reads: list[int] = []
    owner = cast(Any, type(table))
    get_data = owner.GetAccountData

    def clock() -> int:
        reads.append(world.clock.uncached)
        return world.clock.uncached

    def publish_during_scan(self: Any, index: int) -> Any:
        if index == 1:
            assert reads == [10000], "initial scan sample must already exist"
            world.clock.uncached = 10016
            self.AccountData[index].LastUpdated = published
        return get_data(self, index)

    monkeypatch.setitem(table._is_slot_active.__globals__, "get_uncached_tick_count64", clock)
    monkeypatch.setattr(owner, "GetAccountData", publish_during_scan)
    assert (102 in _ids(table.GetAllActiveSlotsData())) is live, (published, live)
    assert reads == [10000, 10016], "only the newer/ambiguous row needs another sample"


def test_unavailable_clock_does_not_fall_back_to_frame(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    table = _pair(world)

    def unavailable() -> int:
        raise OSError("uncached clock unavailable")

    monkeypatch.setitem(table._is_slot_active.__globals__, "get_uncached_tick_count64", unavailable)
    with pytest.raises(OSError, match="uncached clock unavailable"):
        table.GetAllActiveSlotsData()
    with pytest.raises(OSError, match="uncached clock unavailable"):
        table._is_slot_active(1)


def _load_definitions(path: Path, names: set[str], namespace: dict[str, Any]) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = [
        node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names
    ]
    assert {node.name for node in definitions} == names
    module = ast.Module([ast.ImportFrom("__future__", [ast.alias("annotations")], 0), *definitions], [])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace


@pytest.fixture
def consumers(world: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Execute owning definitions/decorators; replace only injected host imports."""
    callbacks: list[Callable[[], None]] = []

    def register(name: str, phase: int, callback: Callable[[], None], priority: int) -> None:
        callbacks.append(callback)

    def no_pet(agent_id: int) -> int:
        return 0

    def no_effect(agent_id: int, skill_id: int) -> bool:
        return False

    def player_allegiance(agent_id: int) -> tuple[int, str]:
        return (1, "Player")

    callback_module = ModuleType("PyCallback")
    callback_module.__dict__.update(
        PyCallback=SimpleNamespace(Register=register),
        Phase=SimpleNamespace(PreUpdate=1),
    )
    monkeypatch.setitem(sys.modules, "PyCallback", callback_module)
    frame = load_module("_active_frame_cache", ROOT / "Py4GWCoreLib/py4gwcorelib_src/FrameCache.py", monkeypatch)
    facade_path = ROOT / "Py4GWCoreLib/GlobalCache/SharedMemory.py"
    tree = ast.parse(facade_path.read_text(encoding="utf-8"))
    owner = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Py4GWSharedMemoryManager"
    )
    selected = {
        "GetAllAccounts",
        "GetAllActiveSlotsData",
        "GetAllAccountData",
        "GetSlotByEmail",
        "GetAccountDataFromEmail",
        "GetHeroAIOptionsFromEmail",
        "AccountHasEffect",
    }
    owner.body = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in selected]
    namespace: dict[str, Any] = dict(AllAccounts=cast(Any, type(world.table)), frame_cache=frame.frame_cache)
    module = ast.Module([ast.ImportFrom("__future__", [ast.alias("annotations")], 0), owner], [])
    exec(compile(ast.fix_missing_locations(module), str(facade_path), "exec"), namespace)
    facade = namespace["Py4GWSharedMemoryManager"]()
    facade.shm = SimpleNamespace(buf=memoryview(world.table))
    global_cache = SimpleNamespace(
        ShMem=facade,
        Party=SimpleNamespace(
            GetPartyID=lambda: 7,
            GetPlayers=lambda: list[Any](),
            GetHeroes=lambda: list[Any](),
            Pets=SimpleNamespace(GetPetID=no_pet),
        ),
        Effects=SimpleNamespace(HasEffect=no_effect),
    )
    map_api = SimpleNamespace(
        IsMapReady=lambda: True,
        GetMapID=lambda: 1,
        GetRegion=lambda: (0, ""),
        GetDistrict=lambda: 0,
        GetLanguage=lambda: (0, ""),
    )
    utils = ModuleType("_active_heroai.utils")
    utils.__dict__.update(
        GLOBAL_CACHE=global_cache,
        Map=map_api,
        ctypes=ctypes,
        HeroAIOptionStruct=world.wire.HeroAIOptionStruct,
        frame_cache=frame.frame_cache,
        Player=SimpleNamespace(GetAgentID=lambda: 101),
        Agent=SimpleNamespace(GetAllegiance=player_allegiance),
        Allegiance=SimpleNamespace(SpiritPet=SimpleNamespace(value=99)),
    )
    _load_definitions(
        ROOT / "Py4GWCoreLib/HeroAI/utils.py",
        {
            "_account_key",
            "_agent_key",
            "_agent_skill_key",
            "SameMapOrPartyAsAccount",
            "detached_hero_ai_options",
            "IsValidEnergyValue",
            "GetEnergyValues",
            "CheckForEffect",
        },
        utils.__dict__,
    )
    monkeypatch.setitem(sys.modules, utils.__name__, utils)
    party_api = ModuleType("Py4GWCoreLib.Party")
    party_api.__dict__.update(Party=SimpleNamespace(IsPartyLoaded=lambda: True))
    monkeypatch.setitem(sys.modules, party_api.__name__, party_api)
    party_namespace = _load_definitions(
        ROOT / "Py4GWCoreLib/HeroAI/party_cache.py",
        {"PartyCache"},
        dict(
            __package__="_active_heroai",
            GLOBAL_CACHE=global_cache,
            HeroAIOptionStruct=world.wire.HeroAIOptionStruct,
        ),
    )
    return SimpleNamespace(facade=facade, party=party_namespace["PartyCache"](), utils=utils, next_frame=callbacks[0])


@pytest.mark.parametrize("lag", [1, 15, 16])
def test_frame_lag_heroai_party_energy_and_effects(world: Any, consumers: Any, lag: int) -> None:
    world.clock.uncached += lag
    _pair(world)
    consumers.party.reset()
    consumers.party.update()
    assert sorted(consumers.party.accounts) == [101, 102], f"fresh teammate lost at {lag} ms frame lag"
    cached = SimpleNamespace(party=consumers.party)
    assert consumers.utils.GetEnergyValues(102, cached) == 0.25
    assert consumers.utils.CheckForEffect(102, 42, cached)
    assert consumers.party.options[102] is not consumers.party.options[101]
    assert world.logs == []


def test_facade_and_party_cache_lifecycle(world: Any, consumers: Any) -> None:
    world.clock.uncached += 16
    table = _pair(world)
    first = consumers.facade.GetAllActiveSlotsData()
    assert _ids(first) == [101, 102]
    assert _ids(consumers.facade.GetAllAccountData()) == [101, 102]
    assert consumers.facade.GetSlotByEmail(world.receiver) == 1
    assert consumers.facade.GetAccountDataFromEmail(world.receiver).AgentData.AgentID == 102
    assert consumers.facade.AccountHasEffect(world.receiver, 42)
    consumers.party.update()
    saved_options = consumers.party.last_valid_options[world.receiver]
    table.HeroAIOptions[1].Following = not saved_options.Following
    assert saved_options.Following != table.HeroAIOptions[1].Following, "options remain detached"
    world.clock.uncached += 5000
    assert consumers.facade.GetAllActiveSlotsData() is first, "membership remains frame cached"
    consumers.next_frame()
    consumers.party.reset()
    consumers.party.update()
    assert consumers.party.accounts == {}
    assert consumers.party.last_valid_options[world.receiver] is saved_options
    _pair(world)
    consumers.next_frame()
    consumers.party.reset()
    consumers.party.update()
    assert sorted(consumers.party.accounts) == [101, 102], "new frame must sample a new uncached time"


@pytest.fixture
def grouped_world(world: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A live local group-4 row, its expired duplicate, and an ungrouped peer."""
    table = _pair(world)
    player_module = ModuleType("Py4GWCoreLib.Player")
    player_module.__dict__.update(Player=SimpleNamespace(GetAccountEmail=lambda: world.sender))
    monkeypatch.setitem(sys.modules, player_module.__name__, player_module)
    monkeypatch.setitem(
        table._get_local_group_id.__globals__, "__package__", "Py4GWCoreLib.GlobalCache.shared_memory_src"
    )
    table.AccountData[0].IsolationGroupID = 4
    table.AccountData[2] = table.AccountData[0]
    table.AccountData[2].AgentData.AgentID = 103
    table.AccountData[2].LastUpdated -= 5000
    return world


@pytest.mark.parametrize("method", ["GetAllActivePlayers", "GetAllActiveSlotsData"])
@pytest.mark.parametrize("failed_read", [2, 3])
def test_nested_group_clock_error_hides_remote(
    grouped_world: Any, monkeypatch: pytest.MonkeyPatch, method: str, failed_read: int
) -> None:
    world = grouped_world
    reads: list[str] = []

    def clock() -> int:
        failed = len(reads) + 1 == failed_read
        reads.append("failed" if failed else "ok")
        if failed:
            raise OSError("nested duplicate-resolution clock failed")
        return world.clock.uncached

    monkeypatch.setitem(world.table._get_local_group_id.__globals__, "get_uncached_tick_count64", clock)
    before = bytes(world.table)
    observed = _ids(getattr(world.table, method)())
    assert reads == [*(["ok"] * (failed_read - 1)), "failed"], (method, reads)
    assert observed == [101], f"{method}: local group=4, remote group=0, reads={reads}, observed={observed}"
    assert bytes(world.table) == before, "fault handling must not change publication bytes"


@pytest.mark.parametrize("local_group,remote_group,visible", [(4, 0, False), (0, 0, True), (4, 4, True), (4, 5, False)])
def test_duplicate_group_resolution_success(
    grouped_world: Any, local_group: int, remote_group: int, visible: bool
) -> None:
    world = grouped_world
    world.table.AccountData[0].IsolationGroupID = local_group
    world.table.AccountData[2].IsolationGroupID = local_group
    world.table.AccountData[1].IsolationGroupID = remote_group
    before = bytes(world.table)
    assert world.table._get_local_group_id() == local_group
    assert _ids(world.table.GetAllActivePlayers()) == ([101, 102] if visible else [101])
    assert _ids(world.table.GetAllActiveSlotsData()) == ([101, 102] if visible else [101])
    assert bytes(world.table) == before


@pytest.mark.parametrize("failure", ["no_email", "no_local_row", "player", "import", "resolver", "bad_group"])
def test_unavailable_local_identity_never_means_group_zero(
    grouped_world: Any, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    world = grouped_world
    player = sys.modules["Py4GWCoreLib.Player"].__dict__["Player"]

    def unavailable_email() -> str:
        raise RuntimeError("Player identity unavailable")

    def unavailable_row(email: str) -> int:
        raise ValueError("identity resolution unavailable")

    if failure == "no_email":
        monkeypatch.setattr(player, "GetAccountEmail", lambda: "")
    elif failure == "no_local_row":
        monkeypatch.setattr(player, "GetAccountEmail", lambda: "missing@example.invalid")
    elif failure == "player":
        monkeypatch.setattr(player, "GetAccountEmail", unavailable_email)
    elif failure == "import":
        monkeypatch.setitem(sys.modules, "Py4GWCoreLib.Player", None)
    elif failure == "resolver":
        monkeypatch.setattr(world.table, "_find_account_slot_by_email", unavailable_row)
    else:
        # A malformed group value cannot occur in the typed wire; fault-inject
        # the failed conversion while retaining the real resolution method.
        original = world.table._get_local_group_id.__globals__

        def invalid_int(value: Any) -> int:
            raise TypeError("group value unavailable")

        monkeypatch.setitem(original, "int", invalid_int)
    before = bytes(world.table)
    assert world.table._get_local_group_id() is None, failure
    assert world.table._is_slot_isolated(1), failure
    assert not world.table._is_visible_account(1), failure
    assert 102 not in _ids(world.table.GetAllActiveSlotsData()), failure
    assert bytes(world.table) == before


def test_unknown_local_group_hides_remote_heroes_and_pets(grouped_world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    world = grouped_world
    for index, flag, owner_index in [(3, "IsHero", 1), (4, "IsPet", 1), (5, "IsHero", 0)]:
        world.table.AccountData[index] = world.table.AccountData[owner_index]
        row = world.table.AccountData[index]
        row.IsAccount = False
        setattr(row, flag, True)
        row.AgentData.AgentID = 101 + index
        row.AgentData.OwnerAgentID = 101 + owner_index
    reads: list[bool] = []

    def clock() -> int:
        failed = bool(reads)
        reads.append(failed)
        if failed:
            raise OSError("nested local-group clock failed")
        return world.clock.uncached

    monkeypatch.setitem(world.table._get_local_group_id.__globals__, "get_uncached_tick_count64", clock)
    before = bytes(world.table)
    assert _ids(world.table.GetAllActiveSlotsData()) == [101, 106]
    assert reads == [False, True, True, True]
    assert bytes(world.table) == before


def test_nested_group_error_does_not_abort_party_cache_update(
    grouped_world: Any, consumers: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = grouped_world
    world.table.AccountData[1].IsolationGroupID = 4
    reads: list[bool] = []

    def clock() -> int:
        failed = len(reads) == 1
        reads.append(failed)
        if failed:
            raise OSError("nested local-group clock failed")
        return world.clock.uncached

    monkeypatch.setitem(world.table._get_local_group_id.__globals__, "get_uncached_tick_count64", clock)
    # Facade views have a separate instance over the same publication bytes.
    before = bytes(world.table)
    consumers.party.reset()
    consumers.party.update()
    assert sorted(consumers.party.accounts) == [101]
    assert reads[:2] == [False, True]
    consumers.next_frame()
    consumers.party.reset()
    consumers.party.update()
    assert sorted(consumers.party.accounts) == [101, 102], "successful identity resolution recovers next frame"
    assert bytes(world.table) == before
    assert world.logs == []
