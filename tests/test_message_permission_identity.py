"""Offline send/receive authorization regressions using real shared-account methods."""

from __future__ import annotations

import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_account_publication import ROOT
from test_account_publication import WIRE
from test_account_publication import account_world as _account_world_fixture
from test_account_publication import load_module

account_world = _account_world_fixture


@pytest.fixture
def world(account_world: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Add real message enums and send inputs to the shared reader fixture."""
    env = account_world
    # Keep the original receiver fixture's one-millisecond lead over the frame clock.
    env.table.AccountData[1].LastUpdated = env.clock.uncached + 1
    enums = load_module("_message_enums", WIRE.parents[1] / "enums_src/Multiboxing_enums.py", monkeypatch)
    namespace = env.table.SendMessage.__func__.__globals__
    monkeypatch.setitem(namespace, "SharedCommandType", enums.SharedCommandType)
    tree = ast.parse((WIRE / "AllAccounts.py").read_text(encoding="utf-8"))
    timeout = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_MESSAGE_RUNNING_STALE_MS" for target in node.targets)
    )
    monkeypatch.setitem(namespace, "_MESSAGE_RUNNING_STALE_MS", ast.literal_eval(timeout))

    def send(
        target: Any = env.table, recipient: str = env.receiver, command: Any = enums.SharedCommandType.Pycons
    ) -> int:
        return int(target.SendMessage(env.sender, recipient, command, (1.0, 2.0), ("secret payload",)))

    env.commands = enums.SharedCommandType
    env.send = send
    return env


def _live_pair(world: Any, sender_group: int = 1, receiver_group: int = 1) -> None:
    world.clock.frame = 10000
    world.clock.uncached = 10016
    for index, group in enumerate((sender_group, receiver_group)):
        row = world.table.AccountData[index]
        row.LastUpdated = 10016
        row.IsolationGroupID = group
        row.AgentPartyData.PartyID = 10 + index
        world.table.Keys[index].HWND = 100 + index


@pytest.mark.parametrize("same_party", [False, True])
@pytest.mark.parametrize("sender_group,receiver_group", [(0, 0), (0, 1), (1, 1), (1, 2)])
@pytest.mark.parametrize("isolated", [False, True])
def test_condition_accessor_preserves_communication_policy(
    world: Any,
    same_party: bool,
    sender_group: int,
    receiver_group: int,
    isolated: bool,
) -> None:
    _live_pair(world, sender_group, receiver_group)
    world.table.AccountData[0].IsIsolated = isolated
    if same_party:
        world.table.AccountData[1].AgentPartyData.PartyID = 10
    expected = same_party or (sender_group == receiver_group and (sender_group > 0 or not isolated))
    before = bytes(world.table)
    assert world.table.GetAuthorizedAccountSlot(world.sender, world.receiver) == (1 if expected else -1)
    assert bytes(world.table) == before
    world.table.AccountData[2] = world.table.AccountData[1]
    assert world.table.GetAuthorizedAccountSlot(world.sender, world.receiver) == -1


def _queue(world: Any) -> None:
    message = world.table.Inbox[0]
    message.SenderEmail = world.sender
    message.ReceiverEmail = world.receiver
    message.Command = world.commands.Pycons
    message.Active = True
    message.Running = False
    message.Timestamp = 10000


def _review_state(world: Any) -> None:
    _live_pair(world, 1, 2)
    table = world.table
    table.AccountData[0].LastUpdated = 10000
    table.AccountData[2] = table.AccountData[1]
    table.AccountData[2].LastUpdated = 4999
    table.AccountData[2].IsolationGroupID = 1
    table.AccountData[3] = table.AccountData[0]
    table.AccountData[3].LastUpdated = 4999
    table.AccountData[3].IsolationGroupID = 2
    world.clock.hwnd = 100


def test_review_complete_cross_group_sequence(world: Any) -> None:
    _review_state(world)
    assert world.table.GetSlotByEmail(world.receiver) == 1
    sent = world.send()
    if sent == -1:
        # Exercise receive independently even after the fixed sender refuses it.
        _queue(world)
    world.clock.hwnd = 101
    world.clock.frame = 10016
    initial_receive = world.table.GetNextMessage(world.receiver)[0]
    world.table.AccountData[0].LastUpdated = 10032
    world.clock.uncached = 10032
    later_receive = world.table.GetNextMessage(world.receiver)[0]
    assert (sent, initial_receive, later_receive) == (-1, -1, -1), (
        "frame 10000->10016; current/publication 10016->10032; live groups 1/2; expired groups 2/1",
        (sent, initial_receive, later_receive),
    )


def test_review_send_rejects_historical_receiver_group(world: Any) -> None:
    _review_state(world)
    before = bytes(world.table)
    assert world.send() == -1
    assert bytes(world.table) == before, "unauthorized send wrote the inbox"


def test_review_receive_rejects_historical_sender_group(world: Any) -> None:
    _review_state(world)
    _queue(world)
    world.clock.hwnd = 101
    world.clock.frame = 10016
    world.clock.uncached = 10032
    world.table.AccountData[0].LastUpdated = 10032
    before = bytes(world.table)
    assert world.table.GetNextMessage(world.receiver) == (-1, None)
    assert world.table.PreviewNextMessage(world.receiver) == (-1, None)
    assert world.table.GetAllMessages() == []
    assert bytes(world.table) == before, "read authorization must not mutate the message"


@pytest.mark.parametrize(
    "sender_group,receiver_group,isolated,same_party,allowed",
    [
        (1, 1, False, False, True),
        (0, 0, False, False, True),
        (0, 0, True, False, False),
        (1, 2, False, False, False),
        (0, 1, False, False, False),
        (1, 2, True, True, True),
    ],
)
def test_live_permission_policy_both_directions(
    world: Any, sender_group: int, receiver_group: int, isolated: bool, same_party: bool, allowed: bool
) -> None:
    _live_pair(world, sender_group, receiver_group)
    world.table.AccountData[1].IsIsolated = isolated
    if same_party:
        world.table.AccountData[1].AgentPartyData.PartyID = 10
    before = bytes(world.table)
    assert world.send() == (0 if allowed else -1)
    if not allowed:
        assert bytes(world.table) == before
        _queue(world)
    world.clock.frame = 10001  # Receive may run against another cached frame.
    queued = bytes(world.table)
    assert world.table.GetNextMessage(world.receiver)[0] == (0 if allowed else -1)
    assert world.table.PreviewNextMessage(world.receiver)[0] == (0 if allowed else -1)
    assert len(world.table.GetAllMessages()) == int(allowed)
    assert bytes(world.table) == queued
    start = ctypes.addressof(world.table.Inbox) - ctypes.addressof(world.table)
    end = start + ctypes.sizeof(world.table.Inbox)
    assert (queued[:start], queued[end:]) == (before[:start], before[end:])


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
@pytest.mark.parametrize("expired_first", [False, True])
def test_expired_duplicate_never_supplies_permissions(world: Any, role: int, expired_first: bool) -> None:
    _live_pair(world)
    table = world.table
    table.AccountData[2] = table.AccountData[role]
    expired = role if expired_first else 2
    table.AccountData[expired].LastUpdated = 4999
    table.AccountData[expired].IsolationGroupID = 2
    assert world.send() == 0
    assert table.GetNextMessage(world.receiver)[0] == 0


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
@pytest.mark.parametrize("conflict", ["group", "party", "isolation", "identical"])
def test_multiple_live_identities_fail_closed(world: Any, role: int, conflict: str) -> None:
    _live_pair(world)
    table = world.table
    table.AccountData[2] = table.AccountData[role]
    if conflict == "group":
        table.AccountData[2].IsolationGroupID = 2
    elif conflict == "party":
        table.AccountData[2].AgentPartyData.PartyID = 777
    elif conflict == "isolation":
        table.AccountData[2].IsIsolated = True
    before = bytes(table)
    assert world.send() == -1, "multiple current physical identities must not be ranked for authorization"
    assert bytes(table) == before
    _queue(world)
    assert table.GetNextMessage(world.receiver) == (-1, None)


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
@pytest.mark.parametrize("case", ["missing", "inactive", "not_account", "expired", "future", "half_range"])
def test_unresolved_identity_cannot_send_or_receive(world: Any, role: int, case: str) -> None:
    _live_pair(world)
    row = world.table.AccountData[role]
    if case == "missing":
        row.AccountEmail = "unrelated@example.invalid"
    elif case == "inactive":
        row.IsSlotActive = False
    elif case == "not_account":
        row.IsAccount = False
    elif case == "expired":
        row.LastUpdated = 5016
    elif case == "future":
        row.LastUpdated = 10017
    else:
        row.LastUpdated = (10016 - 0x80000000) & 0xFFFFFFFF
    before = bytes(world.table)
    assert world.send() == -1
    assert bytes(world.table) == before
    _queue(world)
    assert world.table.GetNextMessage(world.receiver) == (-1, None)


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
@pytest.mark.parametrize(
    "current,age,allowed",
    [
        (10016, 0, True),
        (10016, 4999, True),
        (10016, 5000, False),
        (0x100000005, 21, True),
        (0x100000005, 4999, True),
        (0x100000005, 5000, False),
        (0x100000005, -1, False),
        (0x100000005, 0x80000000, False),
    ],
)
def test_permission_freshness_boundaries(world: Any, role: int, current: int, age: int, allowed: bool) -> None:
    _live_pair(world)
    world.clock.uncached = current
    world.clock.frame = current - 16
    for row in world.table.AccountData[:2]:
        row.LastUpdated = current & 0xFFFFFFFF
    world.table.AccountData[role].LastUpdated = (current - age) & 0xFFFFFFFF
    assert world.send() == (0 if allowed else -1)
    if not allowed:
        _queue(world)
    assert world.table.GetNextMessage(world.receiver)[0] == (0 if allowed else -1)


@pytest.mark.parametrize("lag", [1, 15, 16])
def test_independent_frame_advancement_and_deduplication(world: Any, lag: int) -> None:
    _live_pair(world)
    world.clock.uncached = 10000 + lag
    for row in world.table.AccountData[:2]:
        row.LastUpdated = 10000 + lag
    assert world.send() == 0
    queued = bytes(world.table)
    assert world.send() == 0
    assert bytes(world.table) == queued
    world.clock.frame = 10000 + lag
    world.clock.uncached += lag
    world.table.AccountData[0].LastUpdated = world.clock.uncached
    assert world.table.GetNextMessage(world.receiver)[0] == 0
    world.table.Inbox[0].Running = True
    assert world.table.GetNextMessage(world.receiver) == (-1, None)
    assert world.table.PreviewNextMessage(world.receiver)[0] == 0
    assert world.table.PreviewNextMessage(world.receiver, include_running=False) == (-1, None)
    assert world.send() == 0
    assert world.logs == []


@pytest.mark.parametrize("case", ["fresh", "inactive", "expired", "future", "conflicting_duplicate"])
def test_local_hwnd_lookup_is_not_permission(world: Any, case: str) -> None:
    _live_pair(world)
    world.clock.hwnd = 101
    row = world.table.AccountData[1]
    if case == "inactive":
        row.IsSlotActive = False
    elif case == "expired":
        row.LastUpdated = 4999
    elif case == "future":
        row.LastUpdated = 10017
    elif case == "conflicting_duplicate":
        world.table.AccountData[2] = row
        world.table.AccountData[2].IsolationGroupID = 2
    assert world.table.GetSlotByEmail(world.receiver) == 1, "preserve existing HWND lookup shortcut"
    assert world.send() == (0 if case == "fresh" else -1)
    if case != "fresh":
        _queue(world)
    assert world.table.GetNextMessage(world.receiver)[0] == (0 if case == "fresh" else -1)


def test_permission_cannot_switch_receiver_after_admission(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _live_pair(world)
    table = world.table
    table.AccountData[2] = table.AccountData[1]
    table.AccountData[2].IsSlotActive = False
    original = table.GetSlotByEmail

    def changed(email: str) -> int:
        index = int(original(email))
        table.AccountData[1].IsSlotActive = False
        table.AccountData[2].IsSlotActive = True
        return index

    monkeypatch.setattr(table, "GetSlotByEmail", changed)
    assert world.send() == -1, "permission must remain tied to the admitted receiver row"
    assert not any(message.Active for message in table.Inbox)


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
def test_expired_local_identity_cannot_borrow_remote_duplicate(world: Any, role: int) -> None:
    _live_pair(world)
    table = world.table
    world.clock.hwnd = 100 + role
    table.AccountData[2] = table.AccountData[role]
    table.Keys[2].HWND = 300
    table.AccountData[role].LastUpdated = 4999
    table.AccountData[role].IsolationGroupID = 2
    assert world.send() == -1
    _queue(world)
    assert table.GetNextMessage(world.receiver) == (-1, None)


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
@pytest.mark.parametrize("operation", ["send", "receive"])
@pytest.mark.parametrize("field", ["email", "active", "account", "stamp", "party", "group", "isolated"])
def test_observed_identity_mutation_fails_closed(
    world: Any, monkeypatch: pytest.MonkeyPatch, role: int, operation: str, field: str
) -> None:
    _live_pair(world)
    table = world.table
    original = table._get_message_account_snapshot
    target_email = (world.sender, world.receiver)[role]

    def changed(email: str, expected_index: int | None = None) -> Any:
        snapshot = original(email, expected_index)
        if email == target_email and snapshot is not None:
            row = table.AccountData[role]
            if field == "email":
                row.AccountEmail = "replacement@example.invalid"
            elif field == "active":
                row.IsSlotActive = False
            elif field == "account":
                row.IsAccount = False
            elif field == "stamp":
                row.LastUpdated += 1
            elif field == "party":
                row.AgentPartyData.PartyID += 1
            elif field == "group":
                row.IsolationGroupID = 2
            else:
                row.IsIsolated = True
        return snapshot

    monkeypatch.setattr(table, "_get_message_account_snapshot", changed)
    if operation == "send":
        assert world.send() == -1
        assert not any(message.Active for message in table.Inbox)
    else:
        _queue(world)
        assert table.GetNextMessage(world.receiver) == (-1, None)


def test_permission_expiring_during_resolution_fails_closed(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _live_pair(world)
    table = world.table
    table.AccountData[0].LastUpdated = 5017  # Initially age 4999.
    original = table._get_message_account_snapshot

    def clock_advances(email: str, expected_index: int | None = None) -> Any:
        snapshot = original(email, expected_index)
        if email == world.receiver:
            world.clock.uncached = 10017
        return snapshot

    monkeypatch.setattr(table, "_get_message_account_snapshot", clock_advances)
    before = bytes(table)
    assert world.send() == -1
    assert bytes(table) == before


def test_unavailable_permission_clock_fails_closed_on_receive(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _live_pair(world)
    _queue(world)
    namespace = world.table._can_communicate.__func__.__globals__

    def unavailable() -> int:
        raise OSError("fixture clock unavailable")

    monkeypatch.setitem(namespace, "get_uncached_tick_count64", unavailable)
    assert world.table.GetNextMessage(world.receiver) == (-1, None)
    assert world.table.PreviewNextMessage(world.receiver) == (-1, None)
    assert world.table.GetAllMessages() == []


def test_self_messages_require_current_identity(world: Any) -> None:
    _live_pair(world)
    world.table.AccountData[0].IsSlotActive = False
    assert world.table.SendMessage(world.sender, world.sender, world.commands.Pycons) == -1
    _queue(world)
    world.table.Inbox[0].ReceiverEmail = world.sender
    assert world.table.GetNextMessage(world.sender) == (-1, None)


def test_full_inbox_still_returns_failure(world: Any) -> None:
    _live_pair(world)
    for message in world.table.Inbox:
        message.Active = True
    before = bytes(world.table)
    assert world.send() == -1
    assert bytes(world.table) == before


def test_explicit_system_control_exception_preserved(world: Any) -> None:
    _live_pair(world, 1, 2)
    assert world.send(command=world.commands.AccountSettingsSync) == 0
    assert world.table.GetNextMessage(world.receiver)[0] == 0
    assert world.table.PreviewNextMessage(world.receiver)[0] == 0


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
def test_expired_duplicate_cannot_supply_same_party_exception(world: Any, role: int) -> None:
    _live_pair(world, 1, 2)
    table = world.table
    table.AccountData[2] = table.AccountData[role]
    table.AccountData[2].LastUpdated = 4999
    table.AccountData[2].AgentPartyData.PartyID = table.AccountData[1 - role].AgentPartyData.PartyID
    assert world.send() == -1
    _queue(world)
    assert table.GetNextMessage(world.receiver) == (-1, None)


def test_ungrouped_isolated_sender_is_denied(world: Any) -> None:
    _live_pair(world, 0, 0)
    world.table.AccountData[0].IsIsolated = True
    assert world.send() == -1
    _queue(world)
    assert world.table.GetNextMessage(world.receiver) == (-1, None)


def test_messaging_never_uses_visibility_identity_ranking(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _live_pair(world)

    def wrong_owner(_email: str) -> int:
        pytest.fail("message permissions called the unrelated frame-based visibility resolver")

    monkeypatch.setattr(world.table, "_find_account_slot_by_email", wrong_owner)
    assert world.send() == 0
    assert world.table.GetNextMessage(world.receiver)[0] == 0
    assert world.table.PreviewNextMessage(world.receiver)[0] == 0
    assert len(world.table.GetAllMessages()) == 1


@pytest.mark.parametrize("role", [0, 1], ids=["sender", "receiver"])
@pytest.mark.parametrize("defect", ["missing", "loading", "not_account", "expired", "future", "duplicate", "group"])
def test_pending_message_survives_denial_and_recovers(world: Any, role: int, defect: str) -> None:
    _live_pair(world)
    table = world.table
    assert world.send() == 0
    row = table.AccountData[role]
    original = world.wire.AccountStruct.from_buffer_copy(bytes(row))
    if defect == "missing":
        row.AccountEmail = ""
    elif defect == "loading":
        row.IsSlotActive = False
    elif defect == "not_account":
        row.IsAccount = False
    elif defect == "expired":
        row.LastUpdated = 5016
    elif defect == "future":
        row.LastUpdated = 10017
    elif defect == "duplicate":
        table.AccountData[2] = row
    else:
        row.IsolationGroupID = 2
    denied = bytes(table)
    assert world.send() == -1, (role, defect)
    assert table.GetNextMessage(world.receiver) == table.PreviewNextMessage(world.receiver) == (-1, None)
    assert table.GetAllMessages() == []
    assert bytes(table) == denied, "temporary denial must neither delete nor rewrite the pending message"
    table.AccountData[role] = original
    table.AccountData[2].IsSlotActive = False
    recovered = bytes(table)
    assert table.GetNextMessage(world.receiver)[0] == table.PreviewNextMessage(world.receiver)[0] == 0
    assert len(table.GetAllMessages()) == 1
    assert world.send() == 0, "recovery must reuse the original pending request"
    assert bytes(table) == recovered


@pytest.mark.parametrize("self_message", [False, True])
def test_current_same_group_isolated_accounts_remain_authorized(world: Any, self_message: bool) -> None:
    _live_pair(world)
    for row in world.table.AccountData[:2]:
        row.IsIsolated = True
    recipient = world.sender if self_message else world.receiver
    assert world.send(recipient=recipient) == 0
    assert world.table.GetNextMessage(recipient)[0] == 0
    assert world.table.PreviewNextMessage(recipient)[0] == 0
    assert len(world.table.GetAllMessages()) == 1


@pytest.mark.parametrize("command_name", ["AccountSettingsSync", "AccountSettingsSyncResult"])
@pytest.mark.parametrize("sender_available", [False, True])
def test_both_settings_exceptions_preserve_dispatch_and_listing_contract(
    world: Any, command_name: str, sender_available: bool
) -> None:
    _live_pair(world, 1, 2)
    world.table.AccountData[0].IsSlotActive = sender_available
    world.table.AccountData[1].IsIsolated = True
    assert world.send(command=getattr(world.commands, command_name)) == 0
    before = bytes(world.table)
    assert world.table.GetNextMessage(world.receiver)[0] == 0
    assert world.table.PreviewNextMessage(world.receiver)[0] == 0
    # The existing listing filter has no settings exception; dispatch uses GetNextMessage.
    assert world.table.GetAllMessages() == []
    assert bytes(world.table) == before


@pytest.mark.parametrize("command_name", ["AccountSettingsSync", "AccountSettingsSyncResult"])
def test_settings_exception_does_not_bypass_receiver_lookup(world: Any, command_name: str) -> None:
    _live_pair(world, 1, 2)
    world.table.AccountData[1].IsSlotActive = False
    before = bytes(world.table)
    assert world.send(command=getattr(world.commands, command_name)) == -1
    assert bytes(world.table) == before


def _production_function(path: Path, name: str, namespace: dict[str, Any]) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.Module([ast.ImportFrom("__future__", [ast.alias("annotations")], 0), function], [])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("command_name", ["Pycons", "MerchantRules", "PickUpLoot", "TravelToMap"])
def test_real_messaging_dispatch_waits_for_permission_recovery(world: Any, command_name: str) -> None:
    _live_pair(world)
    assert world.send(command=getattr(world.commands, command_name)) == 0
    world.table.AccountData[1].IsolationGroupID = 2
    queued: list[tuple[int, int]] = []
    received: list[int] = []

    def record_received(message: Any) -> None:
        received.append(int(message.Command))

    def dispatch(index: int, message: Any) -> tuple[int, int]:
        return index, int(message.Command)

    namespace: dict[str, Any] = dict(
        Player=SimpleNamespace(GetAccountEmail=lambda: world.receiver),
        GLOBAL_CACHE=SimpleNamespace(ShMem=world.table, Coroutines=queued),
        SharedCommandType=world.commands,
        _record_received_message=record_received,
    )
    namespace[command_name] = dispatch
    process = _production_function(ROOT / "Widgets/System/Messaging.py", "ProcessMessages", namespace)
    denied = bytes(world.table)
    process()
    assert queued == received == []
    assert bytes(world.table) == denied
    world.table.AccountData[1].IsolationGroupID = 1
    process()
    assert queued == [(0, int(getattr(world.commands, command_name)))]
    assert received == [int(getattr(world.commands, command_name))]


@pytest.mark.parametrize("caller", ["pycons", "merchant", "bot"])
@pytest.mark.parametrize("allowed", [False, True])
def test_stock_senders_use_real_message_admission(world: Any, caller: str, allowed: bool) -> None:
    _live_pair(world, 1, 1 if allowed else 2)
    logs: list[str] = []

    def debug(message: str, *_args: Any) -> None:
        logs.append(message)

    namespace: dict[str, Any] = dict(
        Player=SimpleNamespace(GetAccountEmail=lambda: world.sender, GetTargetID=lambda: 123),
        # The selected recipient may have changed group since its caller enumerated it.
        GLOBAL_CACHE=SimpleNamespace(
            ShMem=SimpleNamespace(
                SendMessage=world.table.SendMessage,
                GetAllAccountData=lambda: list(world.table.AccountData[:2]),
            )
        ),
        SharedCommandType=world.commands,
        Console=SimpleNamespace(MessageType=SimpleNamespace(Warning=1)),
        _debug=debug,
        _party_mode=1,
    )
    if caller == "pycons":
        send = _production_function(ROOT / "Widgets/Automation/Helpers/Pycons.py", "_send_conset_remote_use", namespace)
        assert send("key", "item", 123, 456, world.receiver) is allowed
        command, params = world.commands.UseItem, (123.0, 1.0, 456.0, 0.0)
    elif caller == "merchant":
        send = _production_function(
            ROOT / "Widgets/Guild Wars/Items & Loot/MerchantRules.py", "_send_multibox_command", namespace
        )
        assert send(SimpleNamespace(_debug_log=logs.append), world.receiver, 17, "request", "ready") is allowed
        command, params = world.commands.MerchantRules, (17.0, 0.0, 0.0, 0.0)
    else:
        send = _production_function(
            ROOT / "Widgets/Automation/Bots/Vanquish/Factions/The Jade Sea/Mount Qinkai.py",
            "_dispatch_dialog_to_alts_only",
            namespace,
        )
        assert send(456) == [(world.receiver, 0 if allowed else -1)]
        command, params = world.commands.SendDialogToTarget, (123.0, 456.0, 0.0, 0.0)
    assert sum(bool(message.Active) for message in world.table.Inbox) == int(allowed)
    if allowed:
        message = world.table.Inbox[0]
        assert message.Command == command and tuple(message.Params) == params
        assert (message.SenderEmail, message.ReceiverEmail) == (world.sender, world.receiver)
        if caller == "merchant":
            assert world.table._c_wchar_array_to_str(message.ExtraData[0]) == "request"


@pytest.mark.parametrize("consumer", ["headless", "resurrection"])
def test_real_heroai_listing_consumers_preserve_denied_messages(world: Any, consumer: str) -> None:
    _live_pair(world)
    command = world.commands.SetHeadlessLooting if consumer == "headless" else world.commands.SetResurrectionScroll
    assert world.table.SendMessage(world.sender, world.receiver, command, (1.0, 0.0, 1.0, 0.0)) == 0
    world.table.AccountData[1].IsolationGroupID = 2
    changes: list[bool] = []

    def console_log(*_args: Any) -> None:
        pass

    namespace: dict[str, Any] = dict(
        Player=SimpleNamespace(GetAccountEmail=lambda: world.receiver),
        GLOBAL_CACHE=SimpleNamespace(ShMem=world.table),
        SharedCommandType=world.commands,
        _MSG_FIELD_ENABLED=1,
        _MSG_FIELD_SKIP=2,
        _settings=SimpleNamespace(set_account_resurrection_scroll_enabled=changes.append),
        _broadcast_local_state=lambda: None,
        is_enabled=lambda: True,
        ConsoleLog=console_log,
        Console=SimpleNamespace(MessageType=SimpleNamespace(Info=0)),
    )
    owner = SimpleNamespace(_headless_looting_enabled=False)
    if consumer == "headless":
        handle = _production_function(
            ROOT / "Py4GWCoreLib/HeroAI/headless_tree.py", "_consume_headless_looting_control_messages", namespace
        )
        args = (owner,)
    else:
        handle = _production_function(
            ROOT / "Py4GWCoreLib/HeroAI/resurrection_scroll.py", "_consume_toggle_messages", namespace
        )
        args = ()
    denied = bytes(world.table)
    handle(*args)
    assert not owner._headless_looting_enabled and changes == []
    assert bytes(world.table) == denied
    world.table.AccountData[1].IsolationGroupID = 1
    handle(*args)
    assert not world.table.Inbox[0].Active
    assert owner._headless_looting_enabled if consumer == "headless" else changes == [True]
