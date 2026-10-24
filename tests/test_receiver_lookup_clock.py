"""Receiver clock regression using real lookup/send methods and ctypes wire data."""

from __future__ import annotations

import ctypes
from typing import Any

import pytest

from test_message_permission_identity import account_world as _account_world_fixture, world as _world_fixture

account_world = _account_world_fixture
world = _world_fixture


@pytest.mark.parametrize("lag", [1, 15, 16])
def test_frame_lag_accepts_current_receiver(world: Any, lag: int) -> None:
    world.clock.frame = 10000
    world.clock.uncached = 10000 + lag
    world.table.AccountData[1].LastUpdated = 10000 + lag
    before = bytes(world.table)
    assert world.table.GetSlotByEmail(world.receiver) == 1, f"frame=10000, publication=current={10000 + lag}"
    assert bytes(world.table) == before, "receiver lookup must remain read-only"
    assert world.send() == 0
    assert world.send() == 0, "matching pending message must still be reused"
    assert world.logs == [], "admitted receiver must not warn or invoke the probe"


@pytest.mark.parametrize(
    "current,published,expected",
    [
        (10001, 10002, -1),  # Genuinely future, regardless of frame lag.
        (10001, 10001, 1),
        (10001, 5002, 1),  # 4999 ms.
        (10001, 5001, -1),  # Exactly 5000 ms.
        (10001, 5000, -1),
        (10001, 1, -1),
        (0x100000005, 0xFFFFFFF0, 1),
        (0x100000005, (0x100000005 - 4999) & 0xFFFFFFFF, 1),
        (0x100000005, (0x100000005 - 5000) & 0xFFFFFFFF, -1),
        (0x100000005, 6, -1),
        (0x80000000, 0, -1),
        (0x100000005, 0x80000005, -1),
    ],
)
def test_current_clock_boundaries(world: Any, current: int, published: int, expected: int) -> None:
    world.clock.uncached = current
    world.clock.frame = current - 16
    # This suite varies receiver freshness; authorization also needs a live sender.
    world.table.AccountData[0].LastUpdated = current & 0xFFFFFFFF
    world.table.AccountData[1].LastUpdated = published
    before = bytes(world.table)
    assert world.table.GetSlotByEmail(world.receiver) == expected, (current, published, expected)
    assert bytes(world.table) == before
    result = world.send()
    assert result == (0 if expected == 1 else -1)
    if expected == -1:
        assert bytes(world.table) == before
        assert world.logs[0][1] == f"Receiver account {world.receiver} not found."
    else:
        assert world.logs == []


@pytest.mark.parametrize("case", ["inactive", "wrong_identifier", "case_mismatch", "not_account", "empty"])
def test_receiver_requirements_are_unchanged(world: Any, case: str) -> None:
    world.clock.uncached = 10001
    row = world.table.AccountData[1]
    recipient = world.receiver
    if case == "inactive":
        row.IsSlotActive = False
    elif case == "wrong_identifier":
        row.AccountEmail = "different@example.invalid"
    elif case == "case_mismatch":
        row.AccountEmail = world.receiver.upper()
    elif case == "not_account":
        row.IsAccount = False
    else:
        recipient = ""
    before = bytes(world.table)
    assert world.table.GetSlotByEmail(recipient) == -1
    assert world.send(recipient=recipient) == -1
    assert bytes(world.table) == before


def test_selection_order_and_local_hwnd_bypass_unchanged(world: Any) -> None:
    table = world.table
    world.clock.uncached = 10001
    table.AccountData[2] = table.AccountData[1]
    assert table.GetSlotByEmail(world.receiver) == 1, "first eligible row still wins"
    table.AccountData[1].IsSlotActive = False
    assert table.GetSlotByEmail(world.receiver) == 2
    table.AccountData[1].IsSlotActive = True
    table.AccountData[1].LastUpdated = 10002
    assert table.GetSlotByEmail(world.receiver) == 2, "genuinely future duplicate must be skipped"
    # The established local HWND fast path never applies freshness/activity.
    world.clock.hwnd = 123
    table.Keys[1].HWND = 123
    table.AccountData[1].IsSlotActive = False
    assert table.GetSlotByEmail(world.receiver) == 1


@pytest.mark.parametrize(
    "sender_group,receiver_group,isolated,party_id,system_control,expected",
    [
        (0, 0, False, 0, False, 0),
        (0, 0, True, 0, False, -1),
        (1, 2, False, 0, False, -1),
        (1, 0, False, 0, False, -1),
        (1, 1, False, 0, False, 0),
        (1, 2, True, 7, False, 0),  # Existing same-party exception.
        (1, 2, True, 0, True, 0),  # Existing system-control allowlist.
    ],
)
def test_admitted_receiver_still_obeys_permissions(
    world: Any,
    sender_group: int,
    receiver_group: int,
    isolated: bool,
    party_id: int,
    system_control: bool,
    expected: int,
) -> None:
    table = world.table
    world.clock.uncached = 10001
    table.AccountData[0].IsolationGroupID = sender_group
    table.AccountData[1].IsolationGroupID = receiver_group
    table.AccountData[1].IsIsolated = isolated
    for row in table.AccountData[:2]:
        row.AgentPartyData.PartyID = party_id
    before = bytes(table)
    command = world.commands.AccountSettingsSync if system_control else world.commands.Pycons
    assert world.send(command=command) == expected
    # Compare every non-inbox byte, including account isolation, keys and intents.
    inbox_start = ctypes.addressof(table.Inbox) - ctypes.addressof(table)
    inbox_end = inbox_start + ctypes.sizeof(table.Inbox)
    after = bytes(table)
    assert (after[:inbox_start], after[inbox_end:]) == (before[:inbox_start], before[inbox_end:])
    if expected == -1:
        assert after == before
        assert len(world.logs) == 1 and "Cannot communicate" in world.logs[0][1]
    else:
        message = table.Inbox[0]
        assert message.Active and not message.Running
        assert (message.SenderEmail, message.ReceiverEmail, message.Command) == (world.sender, world.receiver, command)
        assert tuple(message.Params) == (1.0, 2.0, 0.0, 0.0)
        assert message.Timestamp == world.clock.frame, "message timestamp contract must remain unchanged"
        assert world.logs == []


def test_receiver_and_central_visibility_use_current_clock(world: Any) -> None:
    world.clock.uncached = 10001
    assert world.table.GetSlotByEmail(world.receiver) == 1
    assert world.table._is_slot_active(1)
    assert world.table.GetAccountDataFromEmail(world.receiver) is not None
    assert world.table.GetVisibleSlotByEmail(world.receiver) == 1
