"""Optional owner condition census. No native account-layout or message writes."""

# pyright: strict
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from multiprocessing import shared_memory
from struct import Struct
from typing import TYPE_CHECKING
from uuid import uuid4

from .Globals import SHMEM_MAX_PLAYERS
from .IntentSync import get_uncached_tick_count64
from .IntentSync import intent_table_lock
from .IntentSync import publication_is_live

if TYPE_CHECKING:
    from .AllAccounts import AllAccounts

TABLE_NAME = "Py4GW_ConditionObservations_v1"
SAMPLE_INTERVAL_MS = 250
MAX_AGE_MS = 750
CONDITIONS = (
    "Bleeding",
    "Blind",
    "Burning",
    "Cracked_Armor",
    "Crippled",
    "Dazed",
    "Deep_Wound",
    "Disease",
    "Poison",
    "Weakness",
)
_HEADER = Struct("<8sIII")
_HEADER_BYTES = _HEADER.pack(b"GWCOND01", 1, SHMEM_MAX_PLAYERS, 112)
# commit, valid, mask, incarnation start, sequence, sample tick, nonce,
# exact owner/context SHA256, context generation. Hashes avoid truncated Unicode
# wire identities; generation rejects resumed work even after identical re-entry.
_RECORD = Struct("<BBHQQQ16s32s32sI")
_SIZE = _HEADER.size + SHMEM_MAX_PLAYERS * _RECORD.size
_Location = tuple[int, int, int, int]


@dataclass(frozen=True)
class Context:
    email: str
    character: str
    agent: int
    login: int
    hwnd: int
    location: _Location
    party: int
    instance: bytes


@dataclass(frozen=True)
class Owner:
    slot: int
    email: str
    character: str
    agent: int
    login: int
    hwnd: int
    location: _Location
    party: int
    group: int
    isolated: bool

    def digest(self) -> bytes:
        return sha256(repr(self).encode("utf-8")).digest()


@dataclass(frozen=True)
class Observation:
    owner: Owner
    instance: bytes
    incarnation: tuple[int, bytes, int]
    sequence: int
    sampled_at: int
    conditions: frozenset[str]

    @property
    def binding(self) -> tuple[Owner, bytes, tuple[int, bytes, int]]:
        return self.owner, self.instance, self.incarnation


class Publisher:
    """One widget enable lifetime; a superseded lifetime never reclaims a slot."""

    def __init__(self) -> None:
        self.started: int = get_uncached_tick_count64()
        self.nonce: bytes = uuid4().bytes
        self.sequence: int = 0
        self.generation: int = 0
        self.active: bool = True
        self.owner: Owner | None = None


def current_context() -> Context | None:
    """Read existing context surfaces only; deliberately no Player uptime/loaded helper."""
    import PySystem

    from Py4GWCoreLib import Agent
    from Py4GWCoreLib import Map
    from Py4GWCoreLib import Party
    from Py4GWCoreLib.Context import GWContext

    if not Map.IsMapReady() or Map.IsMapLoading() or not Map.IsExplorable() or Map.IsInCinematic():
        return None
    char = GWContext.Char.GetContext()
    world = GWContext.World.GetContext()
    if char is None or not char.token1 or world is None:
        return None
    controlled = world.player_controlled_character
    if controlled is None:
        return None
    # Player.GetAgentID/GetAccountEmail both transitively call IsPlayerLoaded,
    # whose fallback queries renderer-only FPS state. Read their existing owning
    # context fields here so a build's consumer adds no such callback dependency.
    agent, email = controlled.agent_id, char.player_email_str
    name = Agent.GetNameByID(agent)
    login, party = Agent.GetLoginNumber(agent), Party.GetPartyID()
    if agent <= 0 or login <= 0 or party <= 0 or not email or not name or not Agent.IsValid(agent):
        return None
    if not any(member.login_number == login and member.is_connected for member in Party.GetPlayers() or []):
        return None
    # CharContext already defines token1 as world id and host as the server
    # endpoint. Equality is an additional conservative gate, not a new offset.
    host = bytes(char.host)
    if len(host) != 24 or not any(host):
        return None
    instance = sha256(Struct("<I24s").pack(char.token1, host)).digest()
    return Context(
        email,
        name,
        agent,
        login,
        PySystem.Console.get_gw_window_handle(),
        (Map.GetMapID(), Map.GetRegion()[0], Map.GetDistrict(), Map.GetLanguage()[0]),
        party,
        instance,
    )


def account_owner(accounts: AllAccounts, slot: int) -> Owner | None:
    if not 0 <= slot < SHMEM_MAX_PLAYERS:
        return None
    account = accounts.AccountData[slot]
    data = account.AgentData
    stamp = int(account.LastUpdated)
    if not (
        account.IsSlotActive
        and account.IsAccount
        and not account.IsHero
        and account.Key.EntityType == 0
        and account.Key.LocalIndex == 0
        and publication_is_live(get_uncached_tick_count64(), stamp)
    ):
        return None
    owner = Owner(
        slot,
        account.AccountEmail,
        data.CharacterName,
        int(data.AgentID),
        int(data.LoginNumber),
        int(account.Key.HWND),
        (data.Map.MapID, data.Map.Region, data.Map.District, data.Map.Language),
        int(account.AgentPartyData.PartyID),
        int(account.IsolationGroupID),
        bool(account.IsIsolated),
    )
    if not owner.email or not owner.character or min(owner.agent, owner.login, owner.hwnd, owner.party) <= 0:
        return None
    return owner if int(account.LastUpdated) == stamp else None


def local_owner(accounts: AllAccounts, context: Context) -> Owner | None:
    slot = accounts.GetAuthorizedAccountSlot(context.email, context.email)
    owner = account_owner(accounts, slot)
    if owner is None or (
        owner.email,
        owner.character,
        owner.agent,
        owner.login,
        owner.hwnd,
        owner.location,
        owner.party,
    ) != (
        context.email,
        context.character,
        context.agent,
        context.login,
        context.hwnd,
        context.location,
        context.party,
    ):
        return None
    return owner


class ConditionTable:
    """Fixed Windows mapping, lazy attachment, zero-wait dedicated mutex, close only."""

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
        self,
        publisher: Publisher,
        owner: Owner,
        instance: bytes,
        sampled_at: int,
        conditions: frozenset[str] | None,
    ) -> bool:
        if not publisher.active or not 0 <= owner.slot < SHMEM_MAX_PLAYERS or len(instance) != 32:
            return False
        now = get_uncached_tick_count64()
        if not 0 <= now - sampled_at < MAX_AGE_MS:
            conditions = None
        if conditions is not None and not conditions.issubset(CONDITIONS):
            conditions = None
        publisher.sequence += 1
        sequence = publisher.sequence
        mask = sum(1 << index for index, name in enumerate(CONDITIONS) if conditions is not None and name in conditions)
        try:
            with intent_table_lock(TABLE_NAME, timeout_ms=0) as acquired:
                if not acquired or not publisher.active or not self._attach(True) or self._shm is None:
                    return False
                buffer = self._shm.buf
                if buffer is None:
                    return False
                offset = _HEADER.size + owner.slot * _RECORD.size
                current = _RECORD.unpack_from(buffer, offset)
                birth, previous_seq, nonce = int(current[3]), int(current[4]), bytes(current[6])
                same = (birth, nonce) == (publisher.started, publisher.nonce)
                if (not same and birth >= publisher.started) or (same and previous_seq >= sequence):
                    publisher.active = False
                    return False
                if same and sampled_at < int(current[5]):
                    return False
                # Even an abandoned mutex cannot expose a partially written body.
                buffer[offset] = 0
                _RECORD.pack_into(
                    buffer,
                    offset,
                    0,
                    int(conditions is not None),
                    mask,
                    publisher.started,
                    sequence,
                    sampled_at,
                    publisher.nonce,
                    owner.digest(),
                    instance,
                    publisher.generation,
                )
                publisher.owner = owner
                if not publisher.active:
                    return False
                buffer[offset] = 1
                if not publisher.active:
                    buffer[offset + 1] = 0
                    return False
                return True
        except (OSError, ValueError, BufferError, OverflowError):
            return False

    def invalidate(self, publisher: Publisher, *, stop: bool = True) -> None:
        """Cancel first, then best-effort CAS invalidation; contention expires naturally."""
        if stop:
            publisher.active = False
        else:
            publisher.generation += 1
        owner = publisher.owner
        if owner is None:
            return
        try:
            with intent_table_lock(TABLE_NAME, timeout_ms=0) as acquired:
                if not acquired or not self._attach(False) or self._shm is None:
                    return
                buffer = self._shm.buf
                if buffer is None:
                    return
                offset = _HEADER.size + owner.slot * _RECORD.size
                current = _RECORD.unpack_from(buffer, offset)
                if (int(current[3]), bytes(current[6])) == (publisher.started, publisher.nonce):
                    buffer[offset + 1] = 0
                else:
                    publisher.active = False
        except (OSError, ValueError, BufferError):
            return

    def read(self, owner: Owner, instance: bytes) -> Observation | None:
        if not 0 <= owner.slot < SHMEM_MAX_PLAYERS:
            return None
        try:
            with intent_table_lock(TABLE_NAME, timeout_ms=0) as acquired:
                if not acquired or not self._attach(False) or self._shm is None:
                    return None
                buffer = self._shm.buf
                if buffer is None:
                    return None
                record = _RECORD.unpack_from(buffer, _HEADER.size + owner.slot * _RECORD.size)
            committed, valid, mask, birth, seq, stamp, nonce, identity, world, generation = record
            if not (
                committed == valid == 1
                and birth > 0
                and seq > 0
                and mask < (1 << len(CONDITIONS))
                and identity == owner.digest()
                and world == instance
                and 0 <= get_uncached_tick_count64() - stamp < MAX_AGE_MS
            ):
                return None
            return Observation(
                owner,
                instance,
                (birth, nonce, generation),
                seq,
                stamp,
                frozenset(name for index, name in enumerate(CONDITIONS) if mask & (1 << index)),
            )
        except (OSError, ValueError, BufferError):
            return None


def read_authorized(
    table: ConditionTable,
    accounts: AllAccounts,
    context: Context,
    agent: int,
    login: int,
    character: str,
) -> Observation | None:
    local = local_owner(accounts, context)
    if local is None:
        return None
    # AccountData remains the sole registry. Match once, then pin authorization
    # and both copied owners across the synchronized condition read.
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
