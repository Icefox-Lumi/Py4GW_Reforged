"""Detached Native v2 evidence. Coordination remains exclusively in v1."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .AccountStruct import AccountStruct
from .AllAccounts import AllAccounts
from .Globals import SHMEM_MAX_EMAIL_LEN
from .Globals import SHMEM_MAX_PLAYERS
from .IntentSync import publication_is_live
from .KeyStruct import KeyStruct


class AccountPublicationStatus(Enum):
    SUCCESS = "success"
    BUSY = "busy"
    UNAVAILABLE = "unavailable"
    RECOVERY = "recovery"
    SYNC_FAILURE = "sync_failure"


@dataclass(frozen=True, slots=True)
class NativeAccountEvidence:
    slot_index: int
    data: bytes

    def GetAccountData(self) -> AccountStruct:
        """Decode a new Python-owned copy; mutations cannot affect the transport."""
        return AccountStruct.from_buffer_copy(self.data)


@dataclass(frozen=True, slots=True)
class NativeAccountSnapshot:
    captured_at_tick64: int
    accounts: tuple[NativeAccountEvidence, ...]


@dataclass(frozen=True, slots=True)
class AccountPublicationResult:
    status: AccountPublicationStatus
    snapshot: NativeAccountSnapshot | None = None
    reason: str = ""


NativeSnapshotRead = Callable[[], tuple[str, int, bytes, int, int, int, int]]


def _key(key: KeyStruct) -> tuple[int, int, int]:
    return int(key.HWND), int(key.EntityType), int(key.LocalIndex)


def _map(account: AccountStruct) -> tuple[int, int, int, int]:
    value = account.AgentData.Map
    return int(value.MapID), int(value.Region), int(value.District), int(value.Language)


def read_native_account_snapshot(reader: NativeSnapshotRead | None) -> AccountPublicationResult:
    """Acquire once, validate the detached cohort, and never reuse prior evidence."""
    if reader is None:
        return AccountPublicationResult(AccountPublicationStatus.UNAVAILABLE, reason="Native v2 binding unavailable")
    try:
        status_text, now, payload, prefix_size, total_size, native_span, timestamp_offset = reader()
        status = AccountPublicationStatus(status_text)
        if status is not AccountPublicationStatus.SUCCESS:
            return AccountPublicationResult(status, reason=status_text)
        prefix = int(getattr(AllAccounts, "Inbox").offset)
        span = int(getattr(AccountStruct, "IsIsolated").offset)
        last_offset = int(getattr(AccountStruct, "LastUpdated").offset)
        account_offset = int(getattr(AllAccounts, "AccountData").offset)
        key_offset = int(getattr(AllAccounts, "Keys").offset)
        account_size = ctypes.sizeof(AccountStruct)
        if (
            type(payload) is not bytes
            or now < 0
            or ctypes.sizeof(ctypes.c_wchar) != 2
            or prefix_size != prefix
            or total_size != ctypes.sizeof(AllAccounts)
            or native_span != span
            or timestamp_offset != last_offset
            or len(payload) != prefix
            or prefix != account_offset + account_size * SHMEM_MAX_PLAYERS
            or key_offset != 0
            or account_offset != key_offset + ctypes.sizeof(KeyStruct) * SHMEM_MAX_PLAYERS
            or span != int(getattr(AccountStruct, "IsNPC").offset) + ctypes.sizeof(ctypes.c_bool)
            or last_offset != int(getattr(AccountStruct, "InAggroTick64").offset) + ctypes.sizeof(ctypes.c_uint64)
            or account_size != last_offset + ctypes.sizeof(ctypes.c_uint32)
        ):
            raise ValueError("Native/Python account publication layout mismatch")

        records: list[tuple[int, AccountStruct, bool]] = []
        for index in range(SHMEM_MAX_PLAYERS):
            account = AccountStruct.from_buffer_copy(payload, account_offset + index * account_size)
            if not account.IsSlotActive:
                continue
            key = KeyStruct.from_buffer_copy(payload, key_offset + index * ctypes.sizeof(KeyStruct))
            kind = int(account.Key.EntityType)
            typed = (
                sum((bool(account.IsAccount), bool(account.IsHero), bool(account.IsPet), bool(account.IsNPC))) == 1
                and not account.IsNPC
                and kind == (0 if account.IsAccount else 1 if account.IsHero else 2)
            )
            valid = (
                typed
                and _key(key) == _key(account.Key)
                and bool(key.HWND)
                and 0 < len(account.AccountEmail) < SHMEM_MAX_EMAIL_LEN
                and int(account.SlotNumber) == index
                and publication_is_live(now, int(account.LastUpdated))
                and int(account.AgentData.AgentID) > 0
                and int(account.AgentData.Map.MapID) > 0
                and int(account.AgentPartyData.PartyID) > 0
            )
            records.append((index, account, valid))

        owners: dict[tuple[str, int], list[tuple[int, AccountStruct, bool]]] = {}
        key_counts: dict[tuple[int, int, int], int] = {}
        for record in records:
            account = record[1]
            key = _key(account.Key)
            key_counts[key] = key_counts.get(key, 0) + 1
            if account.IsAccount:
                owners.setdefault((account.AccountEmail, int(account.Key.HWND)), []).append(record)
        email_counts: dict[str, int] = {}
        for email, _hwnd in owners:
            email_counts[email] = email_counts.get(email, 0) + 1
        usable: list[NativeAccountEvidence] = []
        for identity, candidates in owners.items():
            if len(candidates) != 1 or email_counts[identity[0]] != 1:
                continue
            owner_record = candidates[0]
            owner = owner_record[1]
            if (
                not owner_record[2]
                or key_counts[_key(owner.Key)] != 1
                or int(owner.Key.LocalIndex) != 0
                or int(owner.AgentData.OwnerAgentID) != 0
                or int(owner.AgentData.HeroID) != 0
                or int(owner.AgentData.LoginNumber) <= 0
            ):
                continue
            cohort = [owner_record]
            keys = {_key(owner.Key)}
            agents = {int(owner.AgentData.AgentID)}
            complete = True
            for record in records:
                child = record[1]
                if child.IsAccount or child.AccountEmail != identity[0]:
                    continue
                if int(child.Key.HWND) != identity[1]:
                    if int(child.AgentData.OwnerAgentID) == int(owner.AgentData.AgentID):
                        complete = False
                        break
                    continue
                key = _key(child.Key)
                agent = int(child.AgentData.AgentID)
                if (
                    not record[2]
                    or key_counts[key] != 1
                    or key in keys
                    or agent in agents
                    or int(child.LastUpdated) != int(owner.LastUpdated)
                    or int(child.AgentData.OwnerAgentID) != int(owner.AgentData.AgentID)
                    or _map(child) != _map(owner)
                    or int(child.AgentPartyData.PartyID) != int(owner.AgentPartyData.PartyID)
                    or (child.IsHero and (int(child.AgentData.HeroID) <= 0 or key[2] != int(child.AgentData.HeroID)))
                    or (child.IsPet and (key[2] != 0 or int(child.AgentData.HeroID) != 0))
                ):
                    complete = False
                    break
                keys.add(key)
                agents.add(agent)
                cohort.append(record)
            if complete:
                for index, account, _valid in cohort:
                    # Reserved coordination bytes in v2 are not a second system.
                    ctypes.memset(ctypes.addressof(account) + span, 0, last_offset - span)
                    usable.append(NativeAccountEvidence(index, bytes(account)))
        snapshot = NativeAccountSnapshot(now, tuple(sorted(usable, key=lambda record: record.slot_index)))
        return AccountPublicationResult(AccountPublicationStatus.SUCCESS, snapshot)
    except Exception as exc:
        return AccountPublicationResult(AccountPublicationStatus.SYNC_FAILURE, reason=str(exc))
