"""Formation-only protocol. No ordinary inbox, options, groups, or intents are written.

Runtime and persistence access live in PartyFormationRuntime. This module owns
the bounded protocol and its versioned mapping, independently of widget imports.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from multiprocessing import shared_memory
from struct import Struct
from typing import Callable, Iterator, Protocol, cast
from uuid import uuid4

from .IntentSync import intent_table_lock

TABLE_NAME = "Py4GW_PartyFormation_v3"
MAX_ACCOUNTS = 64
RECORD_BYTES = 16384
PUBLICATION_MS = 750
POLL_MS = 200
TRANSACTION_MS = 10000
GRANT_MS = 3000
TERMINAL = frozenset({"denied", "expired", "failed", "confirmed"})
_HEADER = Struct("<8sIII")
_HEADER_BYTES = _HEADER.pack(b"GWFORM03", 3, MAX_ACCOUNTS, RECORD_BYTES)
_LENGTH = Struct("<I")
_SIZE = _HEADER.size + MAX_ACCOUNTS * RECORD_BYTES
CancellationBinding = tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class Identity:
    slot: int
    email: str
    character: str
    agent: int
    login: int
    hwnd: int
    location: tuple[int, int, int, int]

    @property
    def key(self) -> str:
        return sha256(json.dumps(asdict(self), sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Snapshot:
    identity: Identity
    instance: str
    uptime: int
    roster: tuple[int, ...]
    heroes: int
    henchmen: int
    others: int
    capacity: int
    seen: tuple[str, ...]
    incoming: tuple[tuple[int, ...], ...] = ()
    profession: int = 0

    @property
    def invite_priority(self) -> tuple[int, str]:
        # Preserve the existing HeroAI melee/Mesmer/Paragon/Necro/Rit ordering.
        priority = 0 if self.profession in (1, 2, 7, 10) else {5: 1, 9: 2, 4: 3, 8: 4}.get(self.profession, 5)
        return priority, self.identity.character

    @property
    def leader(self) -> bool:
        return bool(self.roster and self.roster[0] == self.identity.login)

    @property
    def size(self) -> int:
        return len(self.roster) + self.heroes + self.henchmen + self.others

    @property
    def solo(self) -> bool:
        return self.roster == (self.identity.login,) and self.size == 1


@dataclass(frozen=True)
class Consent:
    enabled: bool = False
    leaders: tuple[str, ...] = ()
    revision: int = 0

    def allows(self, leader: str) -> bool:
        return self.enabled and leader in self.leaders


@dataclass
class Transaction:
    request: str
    leader_session: str
    receiver_session: str
    receiver_key: str
    created: int
    expires: int
    stage: str = "requested"
    reason: str = "awaiting receiver authorization"
    challenge: str = ""
    grant_expires: int = 0
    consent_revision: int = -1
    leader_roster: tuple[int, ...] = ()
    leader_size: int = 0
    leader_key: str = ""
    leader_queued: bool = False
    receiver_queued: bool = False
    leader_dispatched: bool = False
    receiver_dispatched: bool = False
    # Written successfully BEFORE a native call can be attempted. Never reset by expiry.
    leader_prepared: bool = False
    # Receiver writes intent before clearing its marker, then acknowledges the
    # successful clear. Both receipts bind the original transaction and the
    # receiver publication session; they authorize no native action.
    cancellation_intent: CancellationBinding | None = None
    cancellation_ack: CancellationBinding | None = None


@dataclass
class Record:
    session: str
    started: int
    sampled: int
    state: Snapshot
    consent: Consent
    transaction: Transaction | None = None
    # One receiver can grant exactly one leader/request at a time.
    grant: tuple[str, str, str, int] | None = None
    # Blocking evidence only, never execution authority; survives session rotation.
    ownership: str = ""


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid nonnegative integer")
    return value


def validate_location(value: object) -> tuple[int, int, int, int]:
    fields = _list(value, 4)
    if len(fields) != 4:
        raise ValueError("invalid location")
    map_id, region, district, language = fields
    # Region_enums.ServerRegion and Language; Unknown is not an eligible location.
    if type(region) is not int or region not in (-2, 0, 1, 2, 3, 4):
        raise ValueError("invalid formation region")
    if type(language) is not int or language not in (0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 17):
        raise ValueError("invalid formation language")
    map_number, district_number = _integer(map_id), _integer(district)
    if not 0 < map_number <= 0xFFFFFFFF or not 0 < district_number <= 0xFFFFFFFF:
        raise ValueError("invalid formation map or district")
    return map_number, region, district_number, language


def _text(value: object, limit: int = 512) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("invalid text")
    return value


def _list(value: object, limit: int = MAX_ACCOUNTS) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("invalid sequence")
    items = cast(list[object], value)
    if len(items) > limit:
        raise ValueError("sequence overflow")
    return items


def _ints(value: object) -> tuple[int, ...]:
    return tuple(_integer(item) for item in _list(value))


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("invalid object")
    fields = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in fields):
        raise ValueError("invalid object key")
    return cast(dict[str, object], fields)


def decode_record(payload: bytes) -> Record:
    """Decode bounded untrusted mapping data without executable deserialization."""
    data = _object(json.loads(payload))
    state = _object(data["state"])
    identity = _object(state["identity"])
    for values, schema in ((data, Record), (state, Snapshot), (identity, Identity)):
        if set(values) != set(schema.__dataclass_fields__):
            raise ValueError("incompatible formation record schema")
    location = validate_location(identity["location"])
    owner = Identity(
        _integer(identity["slot"]),
        _text(identity["email"]),
        _text(identity["character"]),
        _integer(identity["agent"]),
        _integer(identity["login"]),
        _integer(identity["hwnd"]),
        (location[0], location[1], location[2], location[3]),
    )
    seen = _list(state["seen"])
    incoming = _list(state["incoming"])
    snapshot = Snapshot(
        owner,
        _text(state["instance"]),
        _integer(state["uptime"]),
        _ints(state["roster"]),
        _integer(state["heroes"]),
        _integer(state["henchmen"]),
        _integer(state["others"]),
        _integer(state["capacity"]),
        tuple(_text(item) for item in seen),
        tuple(_ints(item) for item in incoming),
        _integer(state["profession"]),
    )
    policy = _object(data["consent"])
    if set(policy) != set(Consent.__dataclass_fields__):
        raise ValueError("incompatible consent schema")
    leaders = _list(policy["leaders"], 32)
    if type(policy["enabled"]) is not bool:
        raise ValueError("invalid consent")
    consent = Consent(policy["enabled"], tuple(_text(item) for item in leaders), _integer(policy["revision"]))
    tx_data = data["transaction"]
    tx = None
    if tx_data is not None:
        values = _object(tx_data)
        # Only this schema's exact fields are accepted; booleans cannot masquerade as ticks.
        if set(values) != set(Transaction.__dataclass_fields__):
            raise ValueError("incompatible transaction")
        tx = Transaction(
            _text(values["request"]),
            _text(values["leader_session"]),
            _text(values["receiver_session"]),
            _text(values["receiver_key"]),
            _integer(values["created"]),
            _integer(values["expires"]),
        )
        for key in ("stage", "reason", "challenge", "leader_key"):
            setattr(tx, key, _text(values[key]))
        if tx.stage not in TERMINAL | {"requested", "waiting"}:
            raise ValueError("invalid transaction state")
        for key in ("grant_expires", "leader_size"):
            setattr(tx, key, _integer(values[key]))
        revision = values["consent_revision"]
        if type(revision) is not int or revision < -1:
            raise ValueError("invalid consent revision")
        tx.consent_revision = revision
        tx.leader_roster = _ints(values["leader_roster"])
        for key in ("leader_queued", "receiver_queued", "leader_dispatched", "receiver_dispatched", "leader_prepared"):
            if type(values[key]) is not bool:
                raise ValueError("invalid dispatch state")
            setattr(tx, key, values[key])
        for key in ("cancellation_intent", "cancellation_ack"):
            receipt = values[key]
            if receipt is not None:
                parts = tuple(_text(item) for item in _list(receipt, 6))
                if len(parts) != 6:
                    raise ValueError("invalid cancellation receipt")
                setattr(tx, key, parts)
    grant_data = data["grant"]
    grant = None
    if grant_data is not None:
        grant_values = _list(grant_data, 4)
        if len(grant_values) != 4:
            raise ValueError("invalid grant")
        grant = (_text(grant_values[0]), _text(grant_values[1]), _text(grant_values[2]), _integer(grant_values[3]))
    return Record(
        _text(data["session"]),
        _integer(data["started"]),
        _integer(data["sampled"]),
        snapshot,
        consent,
        tx,
        grant,
        _text(data["ownership"], 64),
    )


class FormationTable:
    """All accesses use one nonblocking mutex; partial/corrupt records fail closed."""

    def __init__(self) -> None:
        self._shm: shared_memory.SharedMemory | None = None

    @contextmanager
    def edit(self) -> Iterator[dict[int, Record]]:
        with intent_table_lock(TABLE_NAME, timeout_ms=0) as acquired:
            if not acquired:
                raise RuntimeError("formation service busy")
            if self._shm is None:
                try:
                    self._shm = shared_memory.SharedMemory(name=TABLE_NAME)
                except FileNotFoundError:
                    self._shm = shared_memory.SharedMemory(name=TABLE_NAME, create=True, size=_SIZE)
                    buffer = self._shm.buf
                    if buffer is None:
                        raise RuntimeError("formation mapping unavailable")
                    buffer[:] = bytes(_SIZE)
                    buffer[: _HEADER.size] = _HEADER_BYTES
            buffer = self._shm.buf
            if buffer is None or self._shm.size != _SIZE or bytes(buffer[: _HEADER.size]) != _HEADER_BYTES:
                raise RuntimeError("incompatible formation mapping")
            records: dict[int, Record] = {}
            for slot in range(MAX_ACCOUNTS):
                offset = _HEADER.size + slot * RECORD_BYTES
                size = _LENGTH.unpack_from(buffer, offset)[0]
                if size > RECORD_BYTES - _LENGTH.size:
                    raise ValueError("corrupt formation record")
                if size:
                    records[slot] = decode_record(bytes(buffer[offset + 4 : offset + 4 + size]))
                    if records[slot].state.identity.slot != slot:
                        raise ValueError("formation slot mismatch")
            before = {slot: json.dumps(asdict(row), sort_keys=True).encode() for slot, row in records.items()}
            yield records
            encoded = {slot: json.dumps(asdict(row), sort_keys=True).encode() for slot, row in records.items()}
            if any(not 0 <= slot < MAX_ACCOUNTS or len(value) > RECORD_BYTES - 4 for slot, value in encoded.items()):
                raise ValueError("formation record overflow")
            # Validate every publication before writing ANY row. A malformed local
            # snapshot must not poison unrelated records on the next table read.
            for slot, value in encoded.items():
                if decode_record(value).state.identity.slot != slot:
                    raise ValueError("formation slot mismatch")
            for slot in before.keys() | encoded.keys():
                if before.get(slot) == encoded.get(slot):
                    continue
                offset = _HEADER.size + slot * RECORD_BYTES
                value = encoded.get(slot, b"")
                _LENGTH.pack_into(buffer, offset, 0)
                buffer[offset + 4 : offset + 4 + len(value)] = value
                _LENGTH.pack_into(buffer, offset, len(value))


class Runtime(Protocol):
    def now(self) -> int: ...
    def snapshot(self) -> Snapshot | None: ...
    def identities(self) -> tuple[Identity, ...]: ...
    def consent(self) -> Consent: ...
    def pending_attempt(self) -> str: ...
    def set_pending_attempt(self, expected: str, request: str) -> None: ...
    def queue(self, dispatch: Callable[[Callable[[int], bool]], None]) -> None: ...


@dataclass(frozen=True)
class Outcome:
    character: str
    state: str
    reason: str


class FormationService:
    def __init__(self, runtime: Runtime, table: FormationTable | None = None) -> None:
        self.runtime = runtime
        self.table = table or FormationTable()
        self._publisher = uuid4().hex
        self.session = self._publisher + "." + uuid4().hex
        self.started = runtime.now()
        self._last_tick = -PUBLICATION_MS
        self._last_state: Snapshot | None = None
        self._owner: object | None = None
        self._pending: list[tuple[str, str, str]] = []
        self._outcomes: list[Outcome] = []
        self._current_request = ""
        self._executions: dict[tuple[str, str, bool], int] = {}
        self.status = "waiting for Messaging"

    def outcomes(self) -> tuple[Outcome, ...]:
        return tuple(self._outcomes)

    def invalidate_consent(self) -> None:
        """Revoke this endpoint's outstanding grants immediately on a local UI edit."""
        previous = self.session
        self._rotate()
        self._last_state = None
        self.status = "denied: local formation permission changed"
        # If invalidation cannot acquire the mapping, the UI must report failure
        # instead of claiming that a permission change was saved and revoked.
        with self.table.edit() as records:
            for row in records.values():
                if row.session == previous:
                    row.grant = None
                    if row.transaction is not None:
                        self._deny(row.transaction, "local formation permission changed")

    def _rotate(self) -> None:
        self.session = self._publisher + "." + uuid4().hex
        self._pending.clear()
        self._current_request = ""

    def _publish(self, records: dict[int, Record], state: Snapshot, now: int) -> Record:
        validate_location(list(state.identity.location))
        ownership = self.runtime.pending_attempt()
        old = records.get(state.identity.slot)
        if old is not None and old.session != self.session:
            if old.session.split(".")[0] != self._publisher and (old.started, old.session) > (
                self.started,
                self.session,
            ):
                raise RuntimeError("formation publisher superseded")
            # A never-prepared leader has no local safety marker, but its receiver
            # may already own one. Retain that transaction across session rotation
            # until receiver acknowledgement; old callbacks keep old bindings.
            if old.state.identity.email != state.identity.email and self._can_replace_transaction(
                old.transaction, records, now
            ):
                old = None
            else:
                old.grant = None
                if old.transaction is not None and old.transaction.stage not in TERMINAL:
                    self._deny(old.transaction, "leader session changed", "failed")
        current = Record(
            self.session,
            self.started,
            now,
            state,
            self.runtime.consent(),
            old.transaction if old else None,
            old.grant if old else None,
            ownership,
        )
        records[state.identity.slot] = current
        return current

    def _live(self, records: dict[int, Record], now: int) -> dict[str, Record]:
        identities = self.runtime.identities()
        # The runtime rejects all duplicate registry identities, not just duplicate publications.
        keys = {identity.key for identity in identities}
        rows = [
            row
            for row in records.values()
            if 0 <= now - row.sampled < PUBLICATION_MS and row.started <= row.sampled and row.state.identity.key in keys
        ]
        emails = [row.state.identity.email for row in rows]
        return {row.session: row for row in rows if emails.count(row.state.identity.email) == 1}

    @staticmethod
    def _same_instance(leader: Record, receiver: Record) -> bool:
        a, b = leader.state, receiver.state
        return (
            a.identity.location == b.identity.location
            and bool(a.instance)
            and a.instance == b.instance
            and a.identity.key in b.seen
            and b.identity.key in a.seen
        )

    @staticmethod
    def _deny(tx: Transaction, reason: str, state: str = "denied") -> None:
        tx.stage, tx.reason = state, reason

    def _validate(self, leader: Record, receiver: Record, tx: Transaction, now: int) -> str:
        if not tx.created <= now < tx.expires or tx.expires - tx.created > TRANSACTION_MS:
            return "expired"
        if (
            leader.session != tx.leader_session
            or receiver.session != tx.receiver_session
            or receiver.state.identity.key != tx.receiver_key
        ):
            return "endpoint changed"
        if not self._same_instance(leader, receiver):
            return "instance or live player identity changed"
        if not receiver.consent.allows(leader.state.identity.email):
            return "receiver permission denied"
        if not receiver.state.solo:
            return "receiver is not solo"
        if not leader.state.leader or leader.state.capacity <= leader.state.size:
            return "leader unavailable or party full"
        if tx.challenge:
            if now >= tx.grant_expires or tx.consent_revision != receiver.consent.revision:
                return "grant expired or permission changed"
            if receiver.grant != (leader.session, tx.request, tx.challenge, tx.grant_expires):
                return "receiver grant changed"
            if leader.state.roster != tx.leader_roster or leader.state.size != tx.leader_size:
                return "leader party changed"
            if leader.state.identity.key != tx.leader_key:
                return "leader identity changed"
            if receiver.ownership != tx.request:
                return "receiver ownership changed"
        if leader.ownership and leader.ownership != tx.request:
            return "leader has an unresolved formation attempt"
        return ""

    def _resolve_ownership(self, me: Record, records: dict[int, Record], now: int) -> None:
        """Release a blocker only on positive membership or proven pre-dispatch cancellation."""
        if not me.ownership:
            return
        candidates = [row for row in records.values() if row.transaction and row.transaction.request == me.ownership]
        if len(candidates) != 1:
            self.status = "failed: unresolved formation attempt; recovery evidence unavailable"
            return
        leader = candidates[0]
        tx = leader.transaction
        assert tx is not None
        live = self._live(records, now)
        receiver = next((row for row in live.values() if row.state.identity.key == tx.receiver_key), None)
        confirmed = (
            leader.session in live
            and receiver is not None
            and leader.state.identity.key == tx.leader_key
            and self._same_instance(leader, receiver)
            and leader.state.leader
            and receiver.state.roster == leader.state.roster
            and receiver.state.identity.login in leader.state.roster
        )
        # A prepared call may have had a side effect even if every later flag,
        # callback, process or publication was lost. Expiry is not cancellation.
        if confirmed:
            if confirmed and me is leader and receiver is not None and receiver.ownership == tx.request:
                # Keep the resolution metadata until the receiver has cleared its
                # own durable blocker; a new batch entry must not overwrite it.
                tx.stage, tx.reason = "confirmed", "membership confirmed; waiting for receiver recovery acknowledgement"
                return
            self.runtime.set_pending_attempt(me.ownership, "")
            me.ownership = ""
            me.grant = None
            if confirmed:
                tx.stage, tx.reason = "confirmed", "party membership and intended leader observed on both endpoints"
                self.status = "confirmed: " + tx.reason
                self._executions = {
                    key: end for key, end in self._executions.items() if key[:2] != (tx.leader_session, tx.request)
                }
        else:
            self.status = "waiting: unresolved formation attempt retains ownership"

    def _may_have_dispatched(self, tx: Transaction) -> bool:
        return (
            tx.leader_prepared
            or tx.leader_dispatched
            or tx.receiver_dispatched
            or any(key[:2] == (tx.leader_session, tx.request) for key in self._executions)
        )

    @staticmethod
    def _cancellation_binding(tx: Transaction, receiver_session: str) -> CancellationBinding:
        return (tx.leader_session, tx.request, tx.challenge, tx.receiver_session, tx.receiver_key, receiver_session)

    def _never_prepared_cancellation(self, tx: Transaction) -> bool:
        return tx.stage in TERMINAL and tx.stage != "confirmed" and not self._may_have_dispatched(tx)

    def _cancellation_acknowledged(self, tx: Transaction, records: dict[int, Record], now: int) -> bool:
        if not self._never_prepared_cancellation(tx) or tx.cancellation_intent is None:
            return False
        if tx.cancellation_intent[:5] != self._cancellation_binding(tx, "")[:5]:
            return False
        return any(
            row.state.identity.key == tx.receiver_key
            and row.ownership != tx.request
            and tx.cancellation_ack == self._cancellation_binding(tx, row.session)
            for row in self._live(records, now).values()
        )

    def _can_replace_transaction(self, tx: Transaction | None, records: dict[int, Record], now: int) -> bool:
        if tx is None or tx.stage == "confirmed":
            return True
        return self._cancellation_acknowledged(tx, records, now)

    def _receive_cancellations(self, me: Record, records: dict[int, Record], now: int) -> bool:
        """One retained transaction per leader is also the bounded cleanup record.

        First persist intent. On a later table read, clear the matching marker
        through Settings, then publish acknowledgement. A failed acknowledgement
        flush or reload can retry from the retained intent even after the marker
        was successfully cleared. Never invent completion from elapsed time.
        """
        waiting = False
        for leader in records.values():
            tx = leader.transaction
            if tx is None or tx.receiver_key != me.state.identity.key or not self._never_prepared_cancellation(tx):
                continue
            if self._cancellation_acknowledged(tx, records, now):
                continue
            waiting = True
            binding = self._cancellation_binding(tx, me.session)
            if tx.cancellation_intent is None:
                tx.cancellation_intent = binding
                continue  # Must flush intent before touching the persistent marker.
            if tx.cancellation_intent[:5] != binding[:5]:
                continue
            marker = self.runtime.pending_attempt()
            if marker == tx.request:
                self.runtime.set_pending_attempt(marker, "")
            elif marker:
                continue  # This receiver currently owns a different attempt.
            if self.runtime.pending_attempt():
                continue
            me.ownership = ""
            me.grant = None
            tx.cancellation_ack = binding
        if waiting:
            self.status = "waiting: cancellation cleanup acknowledgement"
        elif self.status == "waiting: cancellation cleanup acknowledgement":
            self.status = "waiting: ready for formation requests"
        return waiting

    def request(self) -> str:
        """Only an explicit local command invokes this method; startup never does."""
        now = self.runtime.now()
        if now - self._last_tick >= PUBLICATION_MS:
            self.status = "failed: Messaging formation service unavailable"
            return self.status
        try:
            with self.table.edit() as records:
                live = self._live(records, now)
                me = live.get(self.session)
                if me is None or not me.state.leader:
                    raise RuntimeError("local leader unavailable")
                if me.ownership or self.runtime.pending_attempt():
                    self.status = "failed: unresolved formation attempt blocks a new request"
                    return self.status
                if not self._can_replace_transaction(me.transaction, records, now):
                    self.status = (
                        "waiting: previous formation attempt requires resolution or cancellation acknowledgement"
                    )
                    return self.status
                if self._pending or (me.transaction and me.transaction.stage not in TERMINAL):
                    return "waiting: formation already in progress"
                self._outcomes.clear()
                self._pending = [
                    (row.session, row.state.identity.key, row.state.identity.character)
                    for row in sorted(live.values(), key=lambda record: record.state.invite_priority)
                    if row.session != self.session and self._same_instance(me, row)
                ]
                self.status = "requested" if self._pending else "denied: no same-instance formation endpoints"
        except Exception as exc:
            self.status = f"failed: {exc}"
        return self.status

    def tick(self, owner: object) -> None:
        now = self.runtime.now()
        if now - self._last_tick < POLL_MS and owner is self._owner:
            return
        state = self.runtime.snapshot()
        if state is None:
            if self._last_state is not None:
                self._rotate()
            self._last_state = None
            self.status = "waiting: local context unavailable"
            return
        prior = self._last_state
        if (
            owner is not self._owner
            or now - self._last_tick >= PUBLICATION_MS
            or prior is None
            or prior.identity != state.identity
            or prior.instance != state.instance
            or state.uptime < prior.uptime
        ):
            self._rotate()
        self._owner, self._last_state, self._last_tick = owner, state, now
        with self.table.edit() as records:
            me = self._publish(records, state, now)
            live = self._live(records, now)
            self._resolve_ownership(me, records, now)
            cancellation_work = self._receive_cancellations(me, records, now)
            if me.transaction is not None and self._cancellation_acknowledged(me.transaction, records, now):
                if me.ownership == me.transaction.request:
                    self.runtime.set_pending_attempt(me.ownership, "")
                    me.ownership = ""
            # Each endpoint participates in at most one transaction in either role.
            if me.grant is not None:
                leader = live.get(me.grant[0])
                if (
                    now >= me.grant[3]
                    or leader is None
                    or leader.transaction is None
                    or leader.transaction.request != me.grant[1]
                    or leader.transaction.stage in TERMINAL
                ):
                    me.grant = None
            tx = me.transaction
            if tx and tx.stage not in TERMINAL:
                receiver = live.get(tx.receiver_session)
                if not tx.created <= now < tx.expires:
                    self._deny(tx, "transaction expired", "expired")
                elif receiver is None:
                    self._deny(tx, "receiver session unavailable", "failed")
                elif (
                    tx.receiver_dispatched
                    and self._same_instance(me, receiver)
                    and me.state.leader
                    and receiver.state.roster == me.state.roster
                    and receiver.state.identity.login in me.state.roster
                ):
                    tx.stage, tx.reason = "confirmed", "party membership and intended leader observed on both endpoints"
                elif tx.receiver_dispatched:
                    # Party publications arrive on different client frames. Once
                    # both invitations were consumed, only observe the result;
                    # never dispatch again or require the receiver to remain solo.
                    if now >= tx.expires:
                        self._deny(tx, "membership confirmation timed out", "expired")
                    elif not self._same_instance(me, receiver) or not me.state.leader:
                        self._deny(tx, "membership context or intended leadership changed", "failed")
                else:
                    problem = self._validate(me, receiver, tx, now)
                    if problem:
                        self._deny(tx, problem, "expired" if "expired" in problem else "denied")
                    elif tx.challenge and not tx.leader_queued:
                        tx.leader_queued = True
                        self._queue(tx, receiver=False)
                self.status = f"{tx.stage}: {tx.reason}"
            if tx and tx.stage in TERMINAL and self._current_request == tx.request:
                target = records.get(
                    next((slot for slot, row in records.items() if row.session == tx.receiver_session), -1)
                )
                character = target.state.identity.character if target else "alternate"
                self._outcomes.append(Outcome(character, tx.stage, tx.reason))
                self._current_request = ""
                self.status = f"{tx.stage}: {tx.reason}"
                # A fresh click is not evidence that the old invitation vanished.
                if self._may_have_dispatched(tx) and tx.stage != "confirmed":
                    self._pending.clear()
            if (
                self._pending
                and not me.ownership
                and me.grant is None
                and not cancellation_work
                and self._can_replace_transaction(tx, records, now)
            ):
                session, key, _ = self._pending.pop(0)
                tx = Transaction(uuid4().hex, self.session, session, key, now, now + TRANSACTION_MS)
                me.transaction = tx
                self._current_request = tx.request
                self.status = "requested: waiting for receiver authorization"
            if me.transaction and me.transaction.stage not in TERMINAL:
                return
            for leader in sorted(live.values(), key=lambda row: row.session):
                tx = leader.transaction
                if tx is None or tx.receiver_session != self.session or tx.stage in TERMINAL:
                    continue
                if tx.receiver_dispatched:
                    continue
                if (
                    cancellation_work
                    or not self._can_replace_transaction(me.transaction, records, now)
                    or (me.ownership and me.ownership != tx.request)
                    or (me.grant is not None and me.grant[:2] != (leader.session, tx.request))
                ):
                    self._deny(tx, "receiver busy")
                    continue
                problem = self._validate(leader, me, tx, now)
                if problem:
                    self._deny(tx, problem, "expired" if "expired" in problem else "denied")
                    continue
                if not tx.challenge:
                    self.runtime.set_pending_attempt("", tx.request)
                    me.ownership = tx.request
                    tx.challenge = uuid4().hex
                    tx.grant_expires = min(tx.expires, now + GRANT_MS)
                    tx.consent_revision = me.consent.revision
                    tx.leader_roster, tx.leader_size = leader.state.roster, leader.state.size
                    tx.leader_key = leader.state.identity.key
                    me.grant = (leader.session, tx.request, tx.challenge, tx.grant_expires)
                    tx.stage, tx.reason = "waiting", "receiver authorized; waiting for leader invitation"
                if tx.leader_dispatched and not tx.receiver_queued and tx.leader_roster in state.incoming:
                    tx.receiver_queued = True
                    self._queue(tx, receiver=True)

    def _queue(self, tx: Transaction, *, receiver: bool) -> None:
        binding = (tx.leader_session, tx.request, tx.challenge, self.session)

        def execute_phase(invite: Callable[[int], bool], *, prepare: bool) -> bool:
            now = self.runtime.now()
            if binding[3] != self.session or not 0 <= now - self._last_tick < PUBLICATION_MS:
                return False
            state = self.runtime.snapshot()
            if state is None:
                return False
            prior = self._last_state
            if (
                prior is None
                or prior.identity != state.identity
                or prior.instance != state.instance
                or state.uptime < prior.uptime
            ):
                self._rotate()
                return False
            # No queue hop after this callback: PartyCache supplies the native call.
            with self.table.edit() as records:
                self._publish(records, state, now)
                live = self._live(records, now)
                leader = live.get(binding[0])
                if leader is None or leader.transaction is None:
                    return False
                current = leader.transaction
                other = live.get(current.receiver_session)
                if (
                    other is None
                    or current.stage in TERMINAL
                    or current.request != binding[1]
                    or current.challenge != binding[2]
                ):
                    return False
                problem = self._validate(leader, other, current, now)
                if problem:
                    self._deny(current, problem, "expired" if "expired" in problem else "denied")
                    return False
                if prepare:
                    if current.leader_prepared:
                        return False
                    # Persist our blocker and the protocol's write-ahead flag
                    # before permitting ANY native side effect. The receiver has
                    # already persisted its own blocker before issuing the grant.
                    self.runtime.set_pending_attempt("", current.request)
                    leader.ownership = current.request
                    current.leader_prepared = True
                    return True
                if not current.leader_prepared:
                    return False
                # Consume locally before the native side effect as well as in the
                # mapping. A failed mapping flush must not allow the same callback
                # to repeat a native invitation in this publisher lifetime.
                execution = (current.leader_session, current.request, receiver)
                if execution in self._executions:
                    return False
                if len(self._executions) >= MAX_ACCOUNTS:
                    self._deny(current, "formation execution capacity reached", "failed")
                    return False
                if receiver:
                    if (
                        current.receiver_dispatched
                        or not current.leader_dispatched
                        or current.leader_roster not in state.incoming
                    ):
                        return False
                    current.receiver_dispatched = True
                    login = leader.state.identity.login
                else:
                    if current.leader_dispatched:
                        return False
                    current.leader_dispatched = True
                    login = other.state.identity.login
                self._executions[execution] = current.expires
                current.stage, current.reason = "waiting", "invitation dispatched; awaiting membership"
                try:
                    if not invite(login):
                        self._deny(current, "native invitation rejected", "failed")
                except Exception:
                    self._deny(current, "native invitation failed", "failed")
                return True

        def dispatch(invite: Callable[[int], bool]) -> None:
            try:
                if not receiver and not execute_phase(invite, prepare=True):
                    return
                # No additional queue hop. Recheck all terminal conditions after
                # the write-ahead flush and immediately before the native call.
                execute_phase(invite, prepare=False)
            except Exception:
                self._pending.clear()
                self.status = "failed: formation persistence/dispatch uncertain; batch stopped"
                # Do not erase either durable ownership or local execution evidence.
                raise

        self.runtime.queue(dispatch)
