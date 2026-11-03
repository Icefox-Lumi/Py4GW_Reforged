"""Pinned widget functions against Package 1 accounts, with inert host boundaries.

Git blobs are read into memory only. No widget module initialization, native
binding, shared-memory mapping, persistence, or local MR regression is invoked.
These checks establish selected consumer behavior, not concurrent atomicity.
"""

# pyright: strict

from __future__ import annotations

import ast
import builtins
import dis
import hashlib
import math
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from enum import IntEnum
from pathlib import Path
from types import CodeType
from types import ModuleType
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest
from test_account_publication import ROOT
from test_account_publication import account_world as account_world
from test_active_account_clock import consumers as _consumers_fixture
from test_message_permission_identity import world as _world_fixture

consumers = _consumers_fixture
world = _world_fixture
# Keep pytest's scalar comparator and its default tolerances at this typed boundary.
approx_scalar = cast(Callable[[float], object], getattr(pytest, "approx"))


@dataclass(frozen=True)
class Source:
    path: str
    blob: str
    repository: Path = ROOT


MR = Source("Widgets/Guild Wars/Items & Loot/MerchantRules.py", "b551b8a09cb1408e1320007e6128ab7696edcbf3")
HTM = Source("Py4GWCoreLib/modular/hero_team_manager.py", "8f58e42b6e42f0e8d919e7e6808122e00e846b86")
PF = Source("Py4GWCoreLib/HeroAI/party_formations.py", "a7af4d84728451173aa2e4952f598a8d6702f9e8")
PYCONS = Source("Widgets/Automation/Helpers/Pycons.py", "8580b005dfe021d727096326f45f6e625517151a")
SMART = Source("Py4GWCoreLib/Builds/Skills/SmartCryController.py", "7da8f89c32fb429e9227b0ad253687f8f8d6f494")
ACTIONS = Source(
    "Widgets/Automation/Multiboxing/HeroAI Actions.py",
    "7cdf5a63391983d3174ef42b9a27c5014e849cdc",
    ROOT.with_name("Py4GW_Reforged-main TESTS"),
)
COMMANDS = Source("Py4GWCoreLib/HeroAI/commands.py", "9b95abdf10c1a3552627b65f8d9085a2fd8c3360")
COMMAND_API = Source("Py4GWCoreLib/HeroAI/command_api.py", "f17f7bbb34fc4d081b5af3803c8d6459a6ab7c1a")
GAME_DATA = Source("Py4GWCoreLib/enums_src/GameData_enums.py", "3af5487f543ed2fe6d14067a6eafd81f5c1fc23a")


def _read_source(source: Source) -> str:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "-C",
            str(source.repository.resolve()),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "diff.external=",
            "cat-file",
            "blob",
            source.blob,
        ],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, (
        f"Required source unavailable: {source.repository} {source.path}@{source.blob}: "
        f"{result.stderr.decode('utf-8', errors='replace')}"
    )
    content = result.stdout
    observed = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
    assert observed == source.blob, f"Source mismatch for {source.path}: expected {source.blob}, observed {observed}"
    return content.decode("utf-8-sig")


def _definitions(
    source: Source,
    names: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    namespace: dict[str, Any] | None = None,
    constants: tuple[str, ...] = (),
) -> Any:
    """Compile exact selected definitions; omit module startup and all imports."""
    tree = ast.parse(_read_source(source), filename=f"{source.path}@{source.blob}")
    body: list[ast.stmt] = [ast.ImportFrom("__future__", [ast.alias("annotations")], 0)]
    for name in constants:
        assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        ]
        assert len(assignments) == 1, f"{source.path}@{source.blob}: expected one constant {name}"
        assignment = assignments[0]
        assert not any(isinstance(node, (ast.Call, ast.Attribute)) for node in ast.walk(assignment.value)), name
        body.append(assignment)
    methods: dict[str, list[ast.stmt]] = {}
    for name in names:
        if "." in name:
            owner_name, method_name = name.split(".", 1)
            owners = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner_name]
            assert len(owners) == 1, f"{source.path}@{source.blob}: missing owner {owner_name}"
            matches = [
                node for node in owners[0].body if isinstance(node, ast.FunctionDef) and node.name == method_name
            ]
            assert len(matches) == 1, f"{source.path}@{source.blob}: missing method {name}"
            methods.setdefault(owner_name, []).append(matches[0])
        else:
            matches = [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == name
            ]
            assert len(matches) == 1, f"{source.path}@{source.blob}: missing or ambiguous definition {name}"
            body.append(matches[0])
    for owner_name, owner_methods in methods.items():
        body.append(ast.ClassDef(owner_name, [], [], owner_methods, []))
    module = ModuleType(f"_package1_{source.blob}")
    module.__dict__.update(
        dataclass=dataclass, field=field, math=math, hashlib=hashlib, Any=Any, Callable=Callable, cast=cast
    )
    module.__dict__.update(namespace or {})
    monkeypatch.setitem(sys.modules, module.__name__, module)
    code = compile(ast.fix_missing_locations(ast.Module(body, [])), f"{source.path}@{source.blob}", "exec")
    exec(code, module.__dict__)
    missing = _global_loads(code) - module.__dict__.keys() - vars(builtins).keys()
    assert not missing, f"{source.path}@{source.blob}: incomplete selected-function closure: {sorted(missing)}"
    return module


def _global_loads(code: CodeType) -> set[str]:
    names = {
        cast(str, instruction.argval)
        for instruction in dis.get_instructions(code)
        if instruction.opname == "LOAD_GLOBAL"
    }
    for value in code.co_consts:
        if isinstance(value, CodeType):
            names.update(_global_loads(value))
    return names


def _module(monkeypatch: pytest.MonkeyPatch, name: str, **values: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(values)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _account(runtime: Any, index: int, email: str, *, group: int = 0, party: int = 7, map_id: int = 1) -> Any:
    row = runtime.world.table.AccountData[index]
    row.AccountEmail = email
    row.IsAccount = True
    row.IsSlotActive = True
    row.LastUpdated = runtime.world.clock.uncached
    row.IsolationGroupID = group
    row.AgentData.AgentID = 101 + index
    row.AgentData.LoginNumber = 101 + index
    row.AgentData.CharacterName = f"Character {index}"
    row.AgentData.Map.MapID = map_id
    row.AgentData.Map.Region = 0
    row.AgentData.Map.District = 0
    row.AgentData.Map.Language = 0
    row.AgentPartyData.PartyID = party
    row.AgentPartyData.PartyPosition = index
    return row


@pytest.fixture
def runtime(world: Any, consumers: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(
        world=world,
        facade=consumers.facade,
        next_frame=consumers.next_frame,
        local_email=world.sender,
        map_ready=True,
        explorable=True,
        party_loaded=True,
        leader_id=101,
        log=[],
        flags=[],
        unflags=[],
        chat=[],
        queued=[],
    )
    _account(state, 0, world.sender)
    _account(state, 1, world.receiver)

    def is_party_member(agent_id: int) -> bool:
        return agent_id in (101, 102)

    def agent_id_by_login(login_number: int) -> int:
        return login_number

    def hero_name(hero_id: int) -> str:
        return f"Hero {hero_id}"

    def hero_agent_by_position(position: int) -> int:
        return 201 if position == 1 else 0

    def flag_hero(agent_id: int, x: float, y: float) -> None:
        state.flags.append((agent_id, x, y))

    def is_valid_agent(agent_id: int) -> bool:
        return agent_id in (101, 102, 201)

    def is_dead(_agent_id: int) -> bool:
        return False

    def agent_xyz(_agent_id: int) -> tuple[float, float, float]:
        return (1000.0, 2000.0, 0.0)

    def agent_rotation(_agent_id: int) -> float:
        return math.pi / 2.0

    def queue_action(queue: str, action: Callable[[], None]) -> None:
        state.queued.append((queue, action))

    def real_name(name: str) -> str:
        return name

    player = SimpleNamespace(
        GetAccountEmail=lambda: state.local_email,
        GetAgentID=lambda: 101,
        GetLoginNumber=lambda: 101,
        SendChatCommand=state.chat.append,
    )
    map_api = SimpleNamespace(
        IsMapReady=lambda: state.map_ready,
        IsMapLoading=lambda: False,
        IsInCinematic=lambda: False,
        IsExplorable=lambda: state.explorable,
        IsGuildHall=lambda: False,
        GetMapID=lambda: 1,
        GetRegion=lambda: (0, ""),
        GetDistrict=lambda: 0,
        GetLanguage=lambda: (0, ""),
    )
    party = SimpleNamespace(
        IsPartyLoaded=lambda: state.party_loaded,
        GetPartyID=lambda: 7,
        GetPartyLeaderID=lambda: state.leader_id,
        GetPlayers=lambda: [SimpleNamespace(login_number=101), SimpleNamespace(login_number=102)],
        IsPartyMember=is_party_member,
        Players=SimpleNamespace(GetAgentIDByLoginNumber=agent_id_by_login),
        GetHeroes=lambda: [SimpleNamespace(agent_id=201, hero_id=28)],
        Heroes=SimpleNamespace(
            GetHeroNameById=hero_name,
            GetHeroAgentIDByPartyPosition=hero_agent_by_position,
            FlagHero=flag_hero,
            UnflagHero=state.unflags.append,
        ),
    )
    agent = SimpleNamespace(
        IsValid=is_valid_agent,
        IsDead=is_dead,
        GetXYZ=agent_xyz,
        GetRotationAngle=agent_rotation,
    )
    cache = SimpleNamespace(
        ShMem=state.facade,
        Party=party,
        _ActionQueueManager=SimpleNamespace(AddAction=queue_action),
    )
    state.player, state.map, state.cache = player, map_api, cache
    _module(monkeypatch, "Py4GWCoreLib", __path__=[], GLOBAL_CACHE=cache, Player=player)
    _module(monkeypatch, "Py4GWCoreLib.HeroAI", __path__=[])
    _module(monkeypatch, "Py4GWCoreLib.GlobalCache", GLOBAL_CACHE=cache)
    for name, value in (("Player", player), ("Map", map_api), ("Party", party), ("Agent", agent)):
        _module(monkeypatch, f"Py4GWCoreLib.{name}", **{name: value})
    # This is the actual selected utils predicate loaded by the shared fixture.
    consumers.utils.__dict__.update(GLOBAL_CACHE=cache, Map=map_api, Player=player)
    monkeypatch.setitem(sys.modules, "Py4GWCoreLib.HeroAI.utils", consumers.utils)
    state.same_map = consumers.utils.SameMapOrPartyAsAccount
    _module(
        monkeypatch,
        "Py4GWCoreLib.py4gwcorelib_src.system_settings.name_obfuscation.resolve",
        require_real_name=real_name,
    )
    return state


@pytest.fixture
def merchant(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    module = _definitions(
        MR,
        (
            "_normalize_multibox_account_email",
            "MerchantRulesWidget._get_account_display_name",
            "MerchantRulesWidget._get_account_party_position",
            "MerchantRulesWidget._get_multibox_accounts",
            "MerchantRulesWidget._get_multibox_active_email_map",
            "MerchantRulesWidget._get_selected_multibox_emails",
            "MerchantRulesWidget._send_multibox_command",
        ),
        monkeypatch,
        dict(GLOBAL_CACHE=runtime.cache, Player=runtime.player, SharedCommandType=runtime.world.commands),
    )
    widget = module.MerchantRulesWidget()
    widget._debug_log = runtime.log.append
    widget.multibox_selected_accounts = {runtime.world.receiver: True}
    return widget


def test_merchant_discovery_selection_and_live_send(runtime: Any, merchant: Any) -> None:
    _account(runtime, 2, "stale@example.invalid").LastUpdated = 1
    _account(runtime, 3, "isolated@example.invalid", group=8)
    assert [row.AccountEmail for row in merchant._get_multibox_accounts()] == [runtime.world.receiver]
    assert merchant._get_selected_multibox_emails() == [runtime.world.receiver]
    assert merchant._send_multibox_command(runtime.world.receiver, 17, "request", "ready") is True
    inbox = runtime.world.table.Inbox[0]
    assert inbox.Active and inbox.ReceiverEmail == runtime.world.receiver
    assert inbox.Command == int(runtime.world.commands.MerchantRules)


@pytest.mark.parametrize("defect", ["expired", "duplicate", "group"])
def test_merchant_cached_selection_never_grants_send_permission(runtime: Any, merchant: Any, defect: str) -> None:
    assert merchant._get_selected_multibox_emails() == [runtime.world.receiver]
    if defect == "expired":
        runtime.world.table.AccountData[1].LastUpdated = 1
    elif defect == "duplicate":
        _account(runtime, 2, runtime.world.receiver)
    else:
        runtime.world.table.AccountData[1].IsolationGroupID = 8
        runtime.world.table.AccountData[1].AgentPartyData.PartyID = 9
    assert merchant._send_multibox_command(runtime.world.receiver, 17, "request", "ready") is False
    assert not any(row.Active for row in runtime.world.table.Inbox)


@pytest.fixture
def htm(monkeypatch: pytest.MonkeyPatch) -> Any:
    enum_tree = ast.parse(_read_source(GAME_DATA))
    enum_definitions: list[ast.stmt] = [
        node
        for node in enum_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ProfessionShort"
        or isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ProfessionShort_Names" for target in node.targets)
    ]
    assert len(enum_definitions) == 2, "HTM profession dependency is incomplete"
    enum_module = _module(monkeypatch, "Py4GWCoreLib.enums_src.GameData_enums", IntEnum=IntEnum)
    exec(compile(ast.Module(enum_definitions, []), GAME_DATA.path, "exec"), enum_module.__dict__)
    return _definitions(
        HTM,
        (
            "AltAccountStatus",
            "alt_account_identity_key",
            "_account_email",
            "_account_character_name",
            "_account_login_number",
            "_account_agent_id",
            "_account_profession_label",
            "_profession_short_label",
            "_account_party_id",
            "_account_party_position",
            "_account_is_isolated",
            "_shared_memory_account_records",
            "active_alt_account_choices",
        ),
        monkeypatch,
    )


def test_htm_real_discovery_keeps_isolated_and_raw_diagnostic_rows(runtime: Any, htm: Any) -> None:
    _account(runtime, 2, "isolated@example.invalid", group=9).IsIsolated = True
    _account(runtime, 3, "stale@example.invalid").LastUpdated = 1
    runtime.world.table.AccountData[1].AgentData.Profession[0] = 1
    runtime.world.table.AccountData[1].AgentData.Profession[1] = 2
    active, raw = htm._shared_memory_account_records(runtime.facade)
    assert [row.AccountEmail for row in active] == [
        runtime.world.sender,
        runtime.world.receiver,
        "isolated@example.invalid",
    ]
    assert [row.AccountEmail for row in raw] == [
        runtime.world.sender,
        runtime.world.receiver,
        "isolated@example.invalid",
        "stale@example.invalid",
    ]
    choices = htm.active_alt_account_choices(player_api=runtime.player, shared_memory=runtime.facade)
    assert [(row.account_email, row.status) for row in choices] == [
        (runtime.world.receiver, "active"),
        ("isolated@example.invalid", "isolated"),
    ]
    assert choices[0].profession_label == "W/R"
    assert runtime.facade.GetAllAccounts().AccountData[3].LastUpdated == 1


@pytest.fixture
def formations(monkeypatch: pytest.MonkeyPatch) -> Any:
    return _definitions(
        PF,
        (
            "FormationAssignment",
            "FormationApplyResult",
            "_safe_str",
            "_safe_float",
            "_safe_int",
            "_safe_bool",
            "_safe_assignment_kind",
            "normalize_target_mode",
            "rotate_offset",
            "_hero_slot_label",
            "_player_slot_label",
            "_resolve_hero_assignment_with_position",
            "_resolve_hero_slot_assignment_with_position",
            "_resolve_hero_assignment_with_position_for_mode",
            "_resolve_hero_assignment_for_mode",
            "_resolve_account_assignment",
            "_resolve_account_slot_assignment",
            "_resolve_account_assignment_for_mode",
            "_account_label",
            "apply_formation",
            "clear_formation",
        ),
        monkeypatch,
        constants=(
            "ASSIGNMENT_UNASSIGNED",
            "ASSIGNMENT_HERO",
            "ASSIGNMENT_ACCOUNT",
            "TARGET_MODE_IDENTITY",
            "TARGET_MODE_PARTY_SLOT",
            "TARGET_MODES",
            "LEADER_PARTY_POSITION",
        ),
    )


@pytest.mark.parametrize("target_mode", ["identity", "party_slot"])
def test_formations_real_apply_clear_preserve_option_references(
    runtime: Any, formations: Any, target_mode: str
) -> None:
    account = formations.FormationAssignment(
        kind="account", account_email=runtime.world.receiver, account_party_position=1, offset_y=100.0
    )
    hero = formations.FormationAssignment(kind="hero", hero_id=28, hero_party_position=1, offset_x=100.0)
    formation = SimpleNamespace(target_mode=target_mode, assignments=[account, hero])
    options = runtime.world.table.HeroAIOptions[1]
    options.Following = True
    assert formations.apply_formation(formation).applied == 2
    assert options.IsFlagged and options.FlagPosX == approx_scalar(900.0)
    assert runtime.flags == [(201, 1000.0, 2100.0)]
    options.Following = False
    runtime.next_frame()
    assert formations.apply_formation(formation).skipped == 1
    assert formations.clear_formation(formation).applied == 2
    assert not options.IsFlagged and options.FlagPos.x == options.FlagPosX == 0.0
    assert runtime.unflags == [1]


@pytest.mark.parametrize(
    "target_mode,account_index,hero_agent,hero_position", [("identity", 2, 202, 2), ("party_slot", 1, 201, 1)]
)
def test_formations_party_slot_uses_current_occupants_with_mismatched_saved_identities(
    runtime: Any,
    formations: Any,
    monkeypatch: pytest.MonkeyPatch,
    target_mode: str,
    account_index: int,
    hero_agent: int,
    hero_position: int,
) -> None:
    def is_valid_agent(agent_id: int) -> bool:
        return agent_id in (101, 102, 103, 201, 202)

    _account(runtime, 2, "former@example.invalid").AgentData.Health.Current = 1.0
    monkeypatch.setattr(
        runtime.cache.Party,
        "GetHeroes",
        lambda: [SimpleNamespace(agent_id=201, hero_id=28), SimpleNamespace(agent_id=202, hero_id=29)],
    )
    monkeypatch.setattr(sys.modules["Py4GWCoreLib.Agent"].__dict__["Agent"], "IsValid", is_valid_agent)
    account = formations.FormationAssignment(
        kind="account", account_email="former@example.invalid", account_party_position=1, offset_y=100.0
    )
    hero = formations.FormationAssignment(kind="hero", hero_id=29, hero_party_position=1, offset_x=100.0)
    formation = SimpleNamespace(target_mode=target_mode, assignments=[account, hero])
    for index in (1, 2):
        options = runtime.world.table.HeroAIOptions[index]
        options.Following = True
        options.IsFlagged = True
        options.FlagPosX = 123.0
    options = runtime.world.table.HeroAIOptions[account_index]
    untouched = runtime.world.table.HeroAIOptions[3 - account_index]
    before_untouched = bytes(untouched)
    result = formations.apply_formation(formation)
    assert (result.applied, result.skipped) == (2, 0), result.messages
    assert options.FlagPosX == approx_scalar(900.0)
    assert bytes(untouched) == before_untouched
    assert runtime.flags == [(hero_agent, 1000.0, 2100.0)]
    options.Following = False
    runtime.next_frame()
    result = formations.clear_formation(formation)
    assert (result.applied, result.skipped) == (2, 0), result.messages
    assert not options.IsFlagged and options.FlagPosX == options.FlagPos.x == 0.0
    assert bytes(untouched) == before_untouched
    assert runtime.unflags == [hero_position]


@pytest.mark.parametrize("defect", ["expired", "group", "map", "party", "not_leader"])
def test_formations_real_resolution_rejects_ineligible_accounts(runtime: Any, formations: Any, defect: str) -> None:
    assignment = formations.FormationAssignment(kind="account", account_email=runtime.world.receiver)
    formation = SimpleNamespace(target_mode="identity", assignments=[assignment])
    runtime.world.table.HeroAIOptions[1].Following = True
    row = runtime.world.table.AccountData[1]
    if defect == "expired":
        row.LastUpdated = 1
    elif defect == "group":
        row.IsolationGroupID = 9
    elif defect == "map":
        row.AgentData.Map.MapID = 2
    elif defect == "party":
        row.AgentPartyData.PartyID = 8
    else:
        runtime.leader_id = 102
    result = formations.apply_formation(formation)
    assert (result.applied, result.skipped) == (0, 1), (defect, result.messages)
    assert not runtime.world.table.HeroAIOptions[1].IsFlagged


@pytest.fixture
def pycons(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    def load_team_flags(email: str) -> tuple[bool, bool]:
        return False, email != "optout@example.invalid"

    return _definitions(
        PYCONS,
        (
            "_acc_email",
            "_acc_name",
            "_acc_party_id",
            "_acc_party_position",
            "_normalize_sync_account_email",
            "_pycons_sync_account_display_name",
            "_get_pycons_sync_accounts",
            "_get_team_broadcast_recipients",
            "_mbdp_control_scope",
        ),
        monkeypatch,
        dict(
            GLOBAL_CACHE=runtime.cache,
            Player=runtime.player,
            _load_team_flags_for_email=load_team_flags,
        ),
    )


def test_pycons_real_discovery_broadcast_and_control_scope(runtime: Any, pycons: Any) -> None:
    _account(runtime, 2, "optout@example.invalid")
    _account(runtime, 3, "elsewhere@example.invalid", map_id=2)
    _account(runtime, 4, "stale@example.invalid").LastUpdated = 1
    assert [row.AccountEmail for row in pycons._get_pycons_sync_accounts()] == [
        runtime.world.receiver,
        "optout@example.invalid",
        "elsewhere@example.invalid",
    ]
    recipients, detail = pycons._get_team_broadcast_recipients()
    assert recipients == [runtime.world.receiver], detail
    scope = pycons._mbdp_control_scope()
    members = "|".join(sorted((runtime.world.sender, runtime.world.receiver, "optout@example.invalid")))
    assert scope == dict(
        party_id=7,
        map_id=1,
        map_region=0,
        map_district=0,
        map_language=0,
        scope_signature=hashlib.sha256(f"7|1|0|0|0|{members}".encode()).hexdigest()[:16],
    )
    runtime.world.table.AccountData[0].IsAccount = False
    runtime.next_frame()
    assert pycons._get_team_broadcast_recipients()[0] == []
    assert pycons._mbdp_control_scope() is None


@pytest.mark.parametrize(
    "case",
    ["positive", "historical", "missing", "zero_group", "unknown_email", "lookup_exception", "inconsistent_fallback"],
)
def test_smart_real_owner_context_keeps_historical_lookup_contract(
    runtime: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    module = _definitions(
        SMART,
        (
            "_OwnerContextResult",
            "SmartCryController._shared_owner_account_row",
            "SmartCryController._local_owner_context_result",
            "SmartCryController._local_owner_context",
        ),
        monkeypatch,
    )
    row = runtime.world.table.AccountData[0]
    row.IsolationGroupID = 5
    clock_calls: list[str] = []
    if case == "historical":
        row.LastUpdated = 1
    elif case == "missing":
        row.IsAccount = False
    elif case == "zero_group":
        row.IsolationGroupID = 0
    elif case == "unknown_email":
        runtime.local_email = ""
    elif case == "lookup_exception":
        _account(runtime, 2, runtime.world.sender, group=5)

        def unavailable_clock() -> int:
            clock_calls.append("duplicate owner lookup")
            raise OSError("controlled clock failure during actual owner lookup")

        monkeypatch.setitem(
            runtime.world.table._find_account_slot_by_email.__globals__, "get_uncached_tick_count64", unavailable_clock
        )
    elif case == "inconsistent_fallback":
        row.IsolationGroupID = 0
        assert runtime.facade.GetAccountGroupByEmail(runtime.world.sender) == 0
        # Retain the actual facade's cached zero while its raw row changes.
        row.IsolationGroupID = 5
    result = module.SmartCryController._local_owner_context_result()
    expected_context = (runtime.world.sender, 5) if case in ("positive", "historical") else None
    assert result.context == expected_context, (case, result)
    assert module.SmartCryController._local_owner_context() == expected_context
    if case == "missing":
        assert result.reason == "account_context_missing"
    elif case == "zero_group":
        assert result.reason == "isolation_group_missing"
    elif case == "unknown_email":
        assert result.reason == "owner_missing"
    elif case in ("lookup_exception", "inconsistent_fallback"):
        assert result.reason == "owner_context_lookup_failed"
        if case == "lookup_exception":
            assert clock_calls == ["duplicate owner lookup", "duplicate owner lookup"]


@pytest.fixture
def actions(runtime: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    def console_log(*args: object) -> None:
        runtime.log.append(args)

    namespace = dict(
        GLOBAL_CACHE=runtime.cache,
        Player=runtime.player,
        Map=runtime.map,
        SharedCommandType=runtime.world.commands,
        ConsoleLog=console_log,
        SameMapOrPartyAsAccount=runtime.same_map,
    )
    commands = _definitions(
        COMMANDS,
        ("Command", "HeroAICommands.__invite_all_command", "HeroAICommands.__travel_alts_to_leader_map_command"),
        monkeypatch,
        namespace,
    )
    owner = commands.HeroAICommands()
    form = commands.Command("Form Party", "", owner._HeroAICommands__invite_all_command)
    travel = commands.Command(
        "Travel Alt Accounts to Leader's Map", "", owner._HeroAICommands__travel_alts_to_leader_map_command
    )
    owner.Commands = {"Form Party": form, "Travel Alt Accounts to Leader's Map": travel}
    widget = _definitions(ACTIONS, ("_command",), monkeypatch, dict(_COMMANDS=owner))
    api = _definitions(
        COMMAND_API, ("HeroAICommandAPI._resolve_accounts", "HeroAICommandAPI._run"), monkeypatch, namespace
    )
    return SimpleNamespace(api=api.HeroAICommandAPI(), widget=widget, form=form, travel=travel)


def test_current_actions_use_candidate_visibility_and_existing_commands(runtime: Any, actions: Any) -> None:
    _account(runtime, 2, "offmap@example.invalid", map_id=2)
    _account(runtime, 3, "isolated@example.invalid", group=9)
    assert [row.AccountEmail for row in actions.api._resolve_accounts()] == [
        runtime.world.sender,
        runtime.world.receiver,
    ]
    assert actions.widget._command("Form Party") is actions.form
    assert actions.widget._command("Travel Alt Accounts to Leader's Map") is actions.travel
    # The current command deliberately travels a supplied off-map account.
    actions.form([runtime.world.table.AccountData[2]])
    first = runtime.world.table.Inbox[0]
    assert (first.ReceiverEmail, first.Command) == ("offmap@example.invalid", int(runtime.world.commands.TravelToMap))
    first.Active = False
    # Travel deliberately re-enumerates accounts rather than honoring an empty list.
    actions.travel([])
    assert first.Active and first.ReceiverEmail == "offmap@example.invalid"
    runtime.explorable = False
    runtime.next_frame()
    assert [row.AccountEmail for row in actions.api._resolve_accounts()] == [
        runtime.world.sender,
        runtime.world.receiver,
    ]


def test_current_actions_api_logs_command_failure(runtime: Any, actions: Any) -> None:
    def fail(_accounts: Any) -> None:
        raise RuntimeError("controlled command failure")

    actions.form.command_function = fail
    actions.api._run(actions.form)
    assert any("controlled command failure" in str(item) for item in runtime.log)


def test_unknown_local_identity_changes_visibility_but_preserves_htm_discovery(
    runtime: Any, merchant: Any, pycons: Any, actions: Any, htm: Any
) -> None:
    runtime.local_email = ""
    assert merchant._get_multibox_accounts() == []
    assert pycons._get_pycons_sync_accounts() == []
    assert actions.api._resolve_accounts() == []
    assert runtime.facade.GetAllAccountData() == []
    active, raw = htm._shared_memory_account_records(runtime.facade)
    expected = [runtime.world.sender, runtime.world.receiver]
    assert [row.AccountEmail for row in active] == expected
    assert [row.AccountEmail for row in raw] == expected
    choices = htm.active_alt_account_choices(player_api=runtime.player, shared_memory=runtime.facade)
    assert [row.account_email for row in choices] == expected
    assert all(row.is_active and row.status == "active" for row in choices)
