"""Detached Native v2 evidence and v3 build witnesses. Coordination remains exclusively in v1."""

# pyright: strict

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Callable

from .AccountStruct import AccountStruct
from .AllAccounts import AllAccounts
from .Globals import SHMEM_MAX_BUILD_WITNESSES
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


class BuildWitnessKind(Enum):
    OUTPOST_BUILD_WITNESS = 1


class _BuildWitnessWireV3(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("kind", ctypes.c_uint32),
        ("hero_id", ctypes.c_uint32),
        ("primary", ctypes.c_uint32),
        ("secondary", ctypes.c_uint32),
        ("skills", ctypes.c_uint32 * 8),
        ("revision", ctypes.c_uint64),
        ("outpost_epoch", ctypes.c_uint64),
        ("observed_at_tick64", ctypes.c_uint64),
    ]


class _OwnerWireV3(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("active", ctypes.c_uint32),
        ("instance_type", ctypes.c_uint32),
        ("instance_epoch", ctypes.c_uint64),
        ("published_tick", ctypes.c_uint32),
        ("witness_count", ctypes.c_uint32),
        ("incarnation", ctypes.c_uint8 * 16),
        ("character_uuid", ctypes.c_uint32 * 4),
        ("witnesses", _BuildWitnessWireV3 * SHMEM_MAX_BUILD_WITNESSES),
    ]


class _HeaderWireV3(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("magic", ctypes.c_uint64),
        ("version", ctypes.c_uint32),
        ("header_size", ctypes.c_uint32),
        ("envelope_size", ctypes.c_uint32),
        ("live_size", ctypes.c_uint32),
        ("account_size", ctypes.c_uint32),
        ("owner_size", ctypes.c_uint32),
        ("witness_size", ctypes.c_uint32),
        ("owner_capacity", ctypes.c_uint32),
        ("witness_capacity", ctypes.c_uint32),
        ("live_count", ctypes.c_uint32),
        ("owner_count", ctypes.c_uint32),
        ("recovery_epoch", ctypes.c_uint64),
    ]


class _EnvelopeWireV3(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", _HeaderWireV3),
        ("keys", KeyStruct * SHMEM_MAX_PLAYERS),
        ("accounts", AccountStruct * SHMEM_MAX_PLAYERS),
        ("owners", _OwnerWireV3 * SHMEM_MAX_PLAYERS),
    ]


@dataclass(frozen=True, slots=True)
class OutpostBuildWitness:
    kind: BuildWitnessKind
    hero_id: int
    primary: int
    secondary: int
    skills: tuple[int, ...]
    revision: int
    outpost_epoch: int
    observed_at_tick64: int


@dataclass(frozen=True, slots=True)
class NativeOwnerCohortV3:
    owner: NativeAccountEvidence = field(repr=False)
    children: tuple[NativeAccountEvidence, ...] = field(repr=False)
    incarnation: bytes
    character_uuid: tuple[int, ...]
    instance_type: int
    instance_epoch: int
    published_tick: int
    witnesses: tuple[OutpostBuildWitness, ...]


@dataclass(frozen=True, slots=True)
class NativeAccountSnapshotV3:
    captured_at_tick64: int
    recovery_epoch: int
    accounts: tuple[NativeAccountEvidence, ...] = field(repr=False)
    cohorts: tuple[NativeOwnerCohortV3, ...]


@dataclass(frozen=True, slots=True)
class AccountPublicationResultV3:
    status: AccountPublicationStatus
    snapshot: NativeAccountSnapshotV3 | None = None
    reason: str = ""


NativeSnapshotReadV3 = Callable[[], tuple[str, int, bytes]]


def read_native_account_snapshot_v3(reader: NativeSnapshotReadV3 | None) -> AccountPublicationResultV3:
    """Validate one detached v3 envelope; never read or fall back to another transport."""
    if reader is None:
        return AccountPublicationResultV3(AccountPublicationStatus.UNAVAILABLE, reason="Native v3 binding unavailable")
    try:
        status_text, now, payload = reader()
        status = AccountPublicationStatus(status_text)
        if status is not AccountPublicationStatus.SUCCESS:
            return AccountPublicationResultV3(status, reason=status_text)
        if type(payload) is not bytes or now < 0 or len(payload) != ctypes.sizeof(_EnvelopeWireV3):
            raise ValueError("Invalid Native v3 envelope size")
        envelope = _EnvelopeWireV3.from_buffer_copy(payload)
        header = envelope.header
        prefix = int(getattr(AllAccounts, "Inbox").offset)
        if (
            ctypes.sizeof(_HeaderWireV3) != 60
            or ctypes.sizeof(_OwnerWireV3) != 560
            or ctypes.sizeof(_BuildWitnessWireV3) != 72
            or ctypes.sizeof(_EnvelopeWireV3) != 909820
            or header.magic != 0x3356425747345950
            or header.version != 3
            or header.header_size != ctypes.sizeof(_HeaderWireV3)
            or header.envelope_size != ctypes.sizeof(_EnvelopeWireV3)
            or header.live_size != prefix
            or header.account_size != ctypes.sizeof(AccountStruct)
            or header.owner_size != ctypes.sizeof(_OwnerWireV3)
            or header.witness_size != ctypes.sizeof(_BuildWitnessWireV3)
            or header.owner_capacity != SHMEM_MAX_PLAYERS
            or header.witness_capacity != SHMEM_MAX_BUILD_WITNESSES
            or header.live_count > SHMEM_MAX_PLAYERS
            or header.owner_count > SHMEM_MAX_PLAYERS
            or header.recovery_epoch == 0
            or int(getattr(_EnvelopeWireV3, "owners").offset) != header.header_size + prefix
        ):
            raise ValueError("Native/Python v3 layout mismatch")
        if header.live_count != sum(bool(row.IsSlotActive) for row in envelope.accounts) or header.owner_count != sum(
            bool(meta.active) for meta in envelope.owners
        ):
            raise ValueError("Invalid Native v3 record counts")
        live_bytes = payload[header.header_size : header.header_size + prefix]
        # Reuse the v2 validator on this snapshot's bytes, never the v2 API.
        live = read_native_account_snapshot(
            lambda: (
                "success",
                now,
                live_bytes,
                prefix,
                ctypes.sizeof(AllAccounts),
                int(getattr(AccountStruct, "IsIsolated").offset),
                int(getattr(AccountStruct, "LastUpdated").offset),
            )
        )
        if live.snapshot is None:
            raise ValueError("Invalid Native v3 live records")
        valid_records = {record.slot_index: record for record in live.snapshot.accounts}
        cohorts: list[NativeOwnerCohortV3] = []
        incarnations: set[bytes] = set()
        for index, meta in enumerate(envelope.owners):
            if meta.active not in (0, 1) or meta.witness_count > SHMEM_MAX_BUILD_WITNESSES:
                raise ValueError("Invalid Native v3 owner metadata")
            if not meta.active:
                if meta.witness_count:
                    raise ValueError("Unassociated Native v3 witnesses")
                continue
            row = envelope.accounts[index]
            uuid = tuple(int(value) for value in meta.character_uuid)
            incarnation = bytes(meta.incarnation)
            if (
                not row.IsSlotActive
                or not row.IsAccount
                or row.Key.EntityType != 0
                or row.Key.LocalIndex != 0
                or meta.published_tick != row.LastUpdated
                or uuid != tuple(int(value) for value in row.AgentData.UUID)
                or not any(incarnation)
                or incarnation in incarnations
                or meta.instance_type not in (0, 1, 2)
                or not meta.instance_epoch
            ):
                raise ValueError("Invalid Native v3 owner association")
            if not publication_is_live(now, int(meta.published_tick)):
                continue
            incarnations.add(incarnation)
            owner = valid_records.get(index)
            if owner is None or not any(uuid) or meta.instance_type == 2:
                if meta.witness_count:
                    raise ValueError("Native v3 witness lacks eligible owner")
                continue
            children = tuple(
                record
                for child_index, record in valid_records.items()
                if child_index != index
                and _key(envelope.accounts[child_index].Key)[0] == row.Key.HWND
                and envelope.accounts[child_index].AccountEmail == row.AccountEmail
            )
            witnesses: list[OutpostBuildWitness] = []
            hero_ids: set[int] = set()
            for wire in meta.witnesses[: meta.witness_count]:
                skills = tuple(int(value) for value in wire.skills)
                if (
                    wire.kind != BuildWitnessKind.OUTPOST_BUILD_WITNESS.value
                    or not wire.hero_id
                    or wire.hero_id in hero_ids
                    or not 1 <= wire.primary <= 10
                    or not 0 <= wire.secondary <= 10
                    or len(skills) != 8
                    or not all(skills)
                    or not wire.revision
                    or not wire.outpost_epoch
                    or wire.outpost_epoch > meta.instance_epoch
                    or wire.observed_at_tick64 > now
                    or now - wire.observed_at_tick64 < ((now - int(meta.published_tick)) & 0xFFFFFFFF)
                    or (meta.instance_type == 0 and wire.outpost_epoch != meta.instance_epoch)
                    or (meta.instance_type == 1 and wire.outpost_epoch >= meta.instance_epoch)
                ):
                    raise ValueError("Invalid Native v3 build witness")
                if (
                    meta.instance_type == 1
                    and sum(
                        envelope.accounts[child.slot_index].IsHero
                        and envelope.accounts[child.slot_index].AgentData.HeroID == wire.hero_id
                        for child in children
                    )
                    != 1
                ):
                    raise ValueError("Native v3 destination hero association missing")
                hero_ids.add(int(wire.hero_id))
                witnesses.append(
                    OutpostBuildWitness(
                        BuildWitnessKind.OUTPOST_BUILD_WITNESS,
                        int(wire.hero_id),
                        int(wire.primary),
                        int(wire.secondary),
                        skills,
                        int(wire.revision),
                        int(wire.outpost_epoch),
                        int(wire.observed_at_tick64),
                    )
                )
            cohorts.append(
                NativeOwnerCohortV3(
                    owner,
                    children,
                    incarnation,
                    uuid,
                    int(meta.instance_type),
                    int(meta.instance_epoch),
                    int(meta.published_tick),
                    tuple(witnesses),
                )
            )
        accounts = tuple(record for cohort in cohorts for record in (cohort.owner, *cohort.children))
        return AccountPublicationResultV3(
            AccountPublicationStatus.SUCCESS,
            NativeAccountSnapshotV3(now, int(header.recovery_epoch), accounts, tuple(cohorts)),
        )
    except Exception:
        return AccountPublicationResultV3(AccountPublicationStatus.SYNC_FAILURE, reason="Invalid Native v3 snapshot")


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
