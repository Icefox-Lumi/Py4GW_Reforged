"""Bounded HR-owner census; observed entries are not removable instances or cover depth."""

# pyright: strict
from __future__ import annotations

import math
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from multiprocessing import shared_memory
from struct import Struct
from typing import TYPE_CHECKING
from typing import Protocol

from .ConditionObservations import Context
from .ConditionObservations import Owner
from .ConditionObservations import Publisher
from .ConditionObservations import account_owner
from .ConditionObservations import local_owner
from .Globals import SHMEM_MAX_NUMBER_OF_BUFFS
from .Globals import SHMEM_MAX_PLAYERS
from .IntentSync import get_uncached_tick_count64
from .IntentSync import intent_table_lock
from .IntentSync import publication_is_live

if TYPE_CHECKING:
    from .AllAccounts import AllAccounts

TABLE_NAME = "Py4GW_HrHexObservations_v1"
SAMPLE_INTERVAL_MS = 250
MAX_AGE_MS = 750
MAX_EFFECT_ENTRIES = SHMEM_MAX_NUMBER_OF_BUFFS  # 240 total input entries, including non-hex effects.
VM_SKILL_ID = 883
_HEADER = Struct("<8sIIII")
# commit, valid, HR-qualified, reserved, entry/distinct counts, birth/sequence/sample,
# nonce, owner/instance digests, generation, VM milliseconds (-1 = unknown), 240 IDs.
_RECORD = Struct(f"<BBBBHHQQQ16s32s32sId{MAX_EFFECT_ENTRIES}I")
_HEADER_BYTES = _HEADER.pack(b"GWHRHEX1", 1, SHMEM_MAX_PLAYERS, _RECORD.size, MAX_EFFECT_ENTRIES)
_SIZE = _HEADER.size + SHMEM_MAX_PLAYERS * _RECORD.size


class EffectEntry(Protocol):
    @property
    def skill_id(self) -> int: ...

    @property
    def time_remaining(self) -> object: ...


@dataclass(frozen=True)
class HrHexCensus:
    hex_ids: frozenset[int]
    entry_count: int
    vm_remaining_ms: float | None


@dataclass(frozen=True)
class HrHexObservation:
    owner: Owner
    instance: bytes
    incarnation: tuple[int, bytes, int]
    sequence: int
    sampled_at: int
    hr_qualified: bool
    census: HrHexCensus

    @property
    def binding(self) -> tuple[Owner, bytes, tuple[int, bytes, int]]:
        return self.owner, self.instance, self.incarnation


def collect_hex_census(effects: Iterable[EffectEntry] | None, is_hex: Callable[[int], bool]) -> HrHexCensus | None:
    """Process at most 240 entries plus one overflow probe; fail the whole census on error.

    Duplicate active VM durations use their minimum. Any unknown or expired VM
    duplicate makes the remaining duration unknown, even alongside a positive one.
    Neither ordering nor effect-instance identity is inferred from the array.
    """
    if effects is None:
        return None
    ids: set[int] = set()
    count = 0
    vm_durations: list[float] = []
    vm_unknown = False
    try:
        for index, effect in enumerate(effects):
            if index >= MAX_EFFECT_ENTRIES:
                return None
            skill_id = effect.skill_id
            if type(skill_id) is not int or not 0 < skill_id <= 0xFFFFFFFF:
                return None
            classified = is_hex(skill_id)
            if type(classified) is not bool:
                return None
            if not classified:
                continue
            raw_remaining = effect.time_remaining
            remaining = (
                float(raw_remaining)
                if isinstance(raw_remaining, (int, float)) and not isinstance(raw_remaining, bool)
                else None
            )
            if remaining is not None and not math.isfinite(remaining):
                remaining = None
            if skill_id == VM_SKILL_ID:
                if remaining is None or remaining <= 0:
                    vm_unknown = True
                else:
                    vm_durations.append(remaining)
            if remaining is not None and remaining <= 0:
                continue
            ids.add(skill_id)
            count += 1
    except Exception:
        return None
    return HrHexCensus(frozenset(ids), count, min(vm_durations) if vm_durations and not vm_unknown else None)


def _valid_census(census: HrHexCensus) -> bool:
    return (
        type(census.entry_count) is int
        and len(census.hex_ids) <= census.entry_count <= MAX_EFFECT_ENTRIES
        and (bool(census.hex_ids) == bool(census.entry_count))
        and all(type(skill_id) is int and 0 < skill_id <= 0xFFFFFFFF for skill_id in census.hex_ids)
        and (
            census.vm_remaining_ms is None
            or (
                VM_SKILL_ID in census.hex_ids
                and not isinstance(census.vm_remaining_ms, bool)
                and math.isfinite(census.vm_remaining_ms)
                and census.vm_remaining_ms > 0
            )
        )
    )


class HrHexTable:
    """v1: 24-byte header + 64 x 1084-byte records = 69400 bytes; close only.

    Each record has room for 240 distinct IDs, bounded by the 240-entry census
    budget. These are engineering limits, not a claim about the game's maximum.
    """

    def __init__(self) -> None:
        self._shm: shared_memory.SharedMemory | None = None

    def close(self) -> None:
        if self._shm is not None:
            self._shm.close()
            self._shm = None

    def _attach(self, create: bool) -> bool:
        if self._shm is None:
            try:
                self._shm = shared_memory.SharedMemory(name=TABLE_NAME)
            except FileNotFoundError:
                if not create:
                    return False
                self._shm = shared_memory.SharedMemory(name=TABLE_NAME, create=True, size=_SIZE)
                buffer = self._shm.buf
                if buffer is None:
                    return False
                buffer[:] = bytes(_SIZE)
                buffer[: _HEADER.size] = _HEADER_BYTES
        buffer = self._shm.buf
        return buffer is not None and self._shm.size >= _SIZE and bytes(buffer[: _HEADER.size]) == _HEADER_BYTES

    def publish(
        self, publisher: Publisher, owner: Owner, instance: bytes, sampled_at: int, census: HrHexCensus
    ) -> bool:
        """Only a successful, freshly read, HR-qualified census can advance sequence/time."""
        if (
            not publisher.active
            or not 0 <= owner.slot < SHMEM_MAX_PLAYERS
            or len(instance) != 32
            or not _valid_census(census)
            or not 0 <= get_uncached_tick_count64() - sampled_at < MAX_AGE_MS
        ):
            self.invalidate(publisher, stop=False)
            return False
        generation = publisher.generation
        sequence = publisher.sequence + 1
        identity = owner.digest()
        ids = tuple(sorted(census.hex_ids))
        body = _RECORD.pack(
            0,
            1,
            1,
            0,
            census.entry_count,
            len(ids),
            publisher.started,
            sequence,
            sampled_at,
            publisher.nonce,
            identity,
            instance,
            generation,
            -1.0 if census.vm_remaining_ms is None else census.vm_remaining_ms,
            *(ids + (0,) * (MAX_EFFECT_ENTRIES - len(ids))),
        )
        try:
            with intent_table_lock(TABLE_NAME, timeout_ms=0) as acquired:
                if not acquired or not publisher.active or publisher.generation != generation:
                    return False
                if not self._attach(True) or self._shm is None or self._shm.buf is None:
                    return False
                buffer = self._shm.buf
                offset = _HEADER.size + owner.slot * _RECORD.size
                current = _RECORD.unpack_from(buffer, offset)
                birth, previous_seq, nonce = int(current[6]), int(current[7]), bytes(current[9])
                same = (birth, nonce) == (publisher.started, publisher.nonce)
                if (not same and birth >= publisher.started) or (same and previous_seq >= sequence):
                    publisher.active = False
                    return False
                if same and sampled_at <= int(current[8]):
                    return False
                if not 0 <= get_uncached_tick_count64() - sampled_at < MAX_AGE_MS:
                    return False
                # A partial write after an abandoned mutex is never a readable record.
                buffer[offset] = 0
                buffer[offset : offset + _RECORD.size] = body
                publisher.owner = owner
                if not publisher.active or publisher.generation != generation:
                    return False
                publisher.sequence = sequence
                buffer[offset] = 1
                if not publisher.active or publisher.generation != generation:
                    buffer[offset + 1] = 0
                    return False
                return True
        except (OSError, ValueError, BufferError, OverflowError):
            return False

    def invalidate(self, publisher: Publisher, *, stop: bool = True) -> None:
        generation = publisher.generation
        if stop:
            publisher.active = False
        else:
            publisher.generation += 1
        owner = publisher.owner
        if owner is None:
            return
        try:
            with intent_table_lock(TABLE_NAME, timeout_ms=0) as acquired:
                if not acquired or not self._attach(False) or self._shm is None or self._shm.buf is None:
                    return
                buffer = self._shm.buf
                offset = _HEADER.size + owner.slot * _RECORD.size
                record = _RECORD.unpack_from(buffer, offset)
                if (int(record[6]), bytes(record[9])) != (publisher.started, publisher.nonce):
                    publisher.active = False
                elif int(record[12]) <= generation:
                    buffer[offset + 1] = 0
        except (OSError, ValueError, BufferError):
            return

    def read(self, owner: Owner, instance: bytes) -> HrHexObservation | None:
        if not 0 <= owner.slot < SHMEM_MAX_PLAYERS:
            return None
        identity = owner.digest()
        try:
            with intent_table_lock(TABLE_NAME, timeout_ms=0) as acquired:
                if not acquired or not self._attach(False) or self._shm is None or self._shm.buf is None:
                    return None
                record = _RECORD.unpack_from(self._shm.buf, _HEADER.size + owner.slot * _RECORD.size)
            committed, valid, qualified, reserved, entries, distinct, birth, seq, stamp = record[:9]
            nonce, stored_identity, world, generation, vm_duration = record[9:14]
            ids = tuple(record[14:])
            if not (
                committed == valid == qualified == 1
                and reserved == 0
                and birth > 0
                and seq > 0
                and 0 <= distinct <= MAX_EFFECT_ENTRIES
                and stored_identity == identity
                and world == instance
                and 0 <= get_uncached_tick_count64() - stamp < MAX_AGE_MS
                and all(value == 0 for value in ids[distinct:])
                and len(set(ids[:distinct])) == distinct
            ):
                return None
            census = HrHexCensus(frozenset(ids[:distinct]), entries, None if vm_duration == -1.0 else vm_duration)
            if not _valid_census(census):
                return None
            return HrHexObservation(owner, instance, (birth, nonce, generation), seq, stamp, True, census)
        except (OSError, ValueError, BufferError):
            return None


def read_authorized(
    table: HrHexTable, accounts: AllAccounts, context: Context, agent: int, login: int, character: str
) -> HrHexObservation | None:
    local = local_owner(accounts, context)
    if local is None:
        return None
    candidates = [
        index
        for index in range(SHMEM_MAX_PLAYERS)
        if accounts.AccountData[index].IsAccount
        and accounts.AccountData[index].IsSlotActive
        and accounts.AccountData[index].AgentData.AgentID == agent
        and publication_is_live(get_uncached_tick_count64(), accounts.AccountData[index].LastUpdated)
    ]
    if len(candidates) != 1:
        return None
    owner = account_owner(accounts, candidates[0])
    if (
        owner is None
        or (owner.agent, owner.login, owner.character, owner.location, owner.party)
        != (agent, login, character, context.location, context.party)
        or accounts.GetAuthorizedAccountSlot(context.email, owner.email) != owner.slot
    ):
        return None
    observation = table.read(owner, context.instance)
    if (
        observation is None
        or account_owner(accounts, owner.slot) != owner
        or local_owner(accounts, context) != local
        or accounts.GetAuthorizedAccountSlot(context.email, owner.email) != owner.slot
        or not 0 <= get_uncached_tick_count64() - observation.sampled_at < MAX_AGE_MS
    ):
        return None
    return observation
