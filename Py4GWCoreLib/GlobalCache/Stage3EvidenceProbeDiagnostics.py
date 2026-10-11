"""TEMPORARY passive diagnostics for the Stage 3 evidence probe.

Remove this module and its GlobalCache call sites after live validation.
"""

# pyright: strict

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic_ns
from typing import Protocol
from typing import cast
from typing import Callable

from .CleansingContext import CleansingContext
from .CleansingContext import CleansingContextSnapshot
from .CleansingContext import CleansingRole
from .CleansingContext import MemberKind
from .CleansingContext import Stage3DecisionBinding
from .CleansingContext import Stage3RefreshDecision
from .CleansingContext import Stage3OwnerEvidence
from .CleansingContext import Stage3FinalVerificationDiagnostic

_ATTEMPT_LEASE_NS = 180_000_000_000
_EVENT_CAPACITY = 128


class _BaselineView(Protocol):
    role: CleansingRole
    profession: int
    relevant_anchors: tuple[int, ...]


class _RefreshView(Protocol):
    session: object
    sequence: int


class _PublisherView(Protocol):
    recovery_epoch: int
    incarnation: bytes
    character_uuid: tuple[int, ...]
    account_email: str
    hwnd: int


class _RemoteBaselineView(Protocol):
    publisher: _PublisherView
    role: CleansingRole
    professions: tuple[int, int]
    relevant_anchors: tuple[int, ...]
    local_character_identity: tuple[str, str]
    local_character_uuid: tuple[int, ...]
    party_id: int
    outpost_map_id: int
    lifecycle_epoch: int
    destination_map_id: int | None
    destination_lifecycle_epoch: int | None
    destination_instance_epoch: int | None


@dataclass(frozen=True, slots=True)
class ProbeSnapshotEvidence:
    """Immutable production snapshot and private baseline values captured together."""

    snapshot: CleansingContextSnapshot
    local_baselines: tuple[tuple[tuple[MemberKind, int, int], object], ...]
    remote_player_baselines: tuple[tuple[tuple[MemberKind, int, int], object], ...]
    roster_signature: tuple[object, ...]
    decision: Stage3RefreshDecision | None = None
    decision_status: str = "UNAVAILABLE"
    unfinished_refresh_sequence: int | None = None
    owner: Stage3OwnerEvidence | None = None


@dataclass(frozen=True, slots=True)
class ProbeForwardingEvent:
    sequence: int
    attempt_id: int
    observed_at_ns: int
    forwarded_loading: bool
    before_revision: int
    before_lifecycle_epoch: int
    before_map_id: int | None
    before_ready: bool
    after_revision: int
    after_lifecycle_epoch: int
    after_map_id: int | None
    after_ready: bool
    transition_latched: bool | None
    before_roster_signature: tuple[object, ...] | None
    pre_forward_refresh_sequence: int | None
    pre_forward_refresh_observed_at_ns: int | None
    pre_forward_refresh_after_attempt: bool
    pre_forward_refresh_matches_attempt: bool
    pre_forward_refresh_matches_snapshot: bool
    owner: Stage3OwnerEvidence | None = None


@dataclass(frozen=True, slots=True)
class ProbeRefreshEvent:
    sequence: int
    attempt_id: int
    observed_at_ns: int
    evidence: ProbeSnapshotEvidence | None
    owner: Stage3OwnerEvidence | None = None


@dataclass(frozen=True, slots=True)
class ProbeEventBatch:
    active: bool
    overflowed: bool
    events: tuple[ProbeForwardingEvent, ...]


@dataclass(frozen=True, slots=True)
class ProbeRefreshBatch:
    active: bool
    overflowed: bool
    events: tuple[ProbeRefreshEvent, ...]


@dataclass(frozen=True, slots=True)
class ProbeOrderedBatch:
    active: bool
    overflowed: bool
    events: tuple[Stage3OwnerEvidence, ...]
    watermark: int
    replaced: bool = False


@dataclass(slots=True)
class _ProbeAttempt:
    attempt_id: int
    context: CleansingContext
    starting_revision: int
    starting_lifecycle_epoch: int
    starting_map_id: int
    starting_sequence: int
    starting_refresh_sequence: int
    starting_roster_signature: tuple[object, ...]
    lease_expires_at_ns: int
    source: Stage3OwnerEvidence
    deadline_ns: int
    starting_owner_sequence: int


def capture_snapshot_evidence(
    context: CleansingContext,
    snapshot: CleansingContextSnapshot,
    binding: Stage3DecisionBinding | None = None,
    session: object | None = None,
    refresh: _RefreshView | None = None,
    owner: Stage3OwnerEvidence | None = None,
) -> ProbeSnapshotEvidence | None:
    """Copy only the already-published snapshot and its internal continuity baselines."""
    raw_local_baselines = dict(owner.local) if owner is not None else getattr(context, "_baselines", None)
    raw_remote_baselines = (
        dict(owner.remote) if owner is not None else getattr(context, "_remote_player_baselines", None)
    )
    if not isinstance(raw_local_baselines, dict) or not isinstance(raw_remote_baselines, dict):
        return None

    local_baselines = cast(dict[tuple[MemberKind, int, int], object], raw_local_baselines)
    remote_baselines = cast(dict[tuple[MemberKind, int, int], object], raw_remote_baselines)
    local_items = tuple(
        sorted(
            local_baselines.items(),
            key=lambda item: (item[0][0].value, item[0][1], item[0][2]),
        )
    )
    remote_items = tuple(
        sorted(
            remote_baselines.items(),
            key=lambda item: (item[0][0].value, item[0][1], item[0][2]),
        )
    )

    member_rows: list[tuple[object, ...]] = []
    for member in snapshot.members:
        identity = member.identity
        member_rows.append(
            (
                member.evidence_source.value,
                identity.kind.value,
                identity.owner_id,
                identity.member_id,
                identity.agent_id,
                member.role.value,
                member.candidate_role.value,
                member.reason,
                member.primary_profession,
                member.anchor_skill_ids,
                member.remote_provenance_generation,
            )
        )
    member_rows.sort(key=lambda row: tuple(str(value) for value in row[:4]))

    local_baseline_rows: list[tuple[object, ...]] = []
    for key, raw_baseline in local_items:
        baseline = cast(_BaselineView, raw_baseline)
        local_baseline_rows.append(
            (
                key[0].value,
                key[1],
                key[2],
                baseline.role.value,
                baseline.profession,
                baseline.relevant_anchors,
            )
        )

    remote_baseline_rows: list[tuple[object, ...]] = []
    for key, raw_baseline in remote_items:
        baseline = cast(_RemoteBaselineView, raw_baseline)
        publisher = baseline.publisher
        remote_baseline_rows.append(
            (
                key[0].value,
                key[1],
                key[2],
                publisher.recovery_epoch,
                publisher.incarnation,
                publisher.character_uuid,
                publisher.account_email.strip().casefold(),
                publisher.hwnd,
                baseline.role.value,
                baseline.professions,
                baseline.relevant_anchors,
                baseline.local_character_identity,
                baseline.local_character_uuid,
                baseline.party_id,
                baseline.outpost_map_id,
                baseline.lifecycle_epoch,
                baseline.destination_map_id,
                baseline.destination_lifecycle_epoch,
                baseline.destination_instance_epoch,
            )
        )

    role_counts = tuple((role.value, count) for role, count in snapshot.composition.role_counts)
    signature: tuple[object, ...] = (
        snapshot.map_id,
        snapshot.lifecycle_epoch,
        snapshot.ready,
        snapshot.character_identity,
        snapshot.composition.status.value,
        snapshot.composition.member_count,
        snapshot.composition.declared_party_size,
        role_counts,
        tuple(member_rows),
        tuple(local_baseline_rows),
        tuple(remote_baseline_rows),
    )
    # No revision search or nearest-time matching. The owner verifies that this
    # binding survived the capture with the same published object and baselines.
    unfinished_sequence: int | None = None
    try:
        if owner is not None:
            decision = owner.decision.decision if owner.decision is not None else None
            status = "EXACT" if decision is not None else "UNAVAILABLE"
        elif session is None:
            decision, status = None, "UNAVAILABLE"
        elif not context.OwnsStage3DecisionSession(session) or (
            binding is not None and binding.decision.session is not session
        ):
            decision, status = None, "AMBIGUOUS"
        else:
            decision, status = context.ResolveStage3Decision(binding, snapshot, local_items, remote_items)
            if not context.OwnsStage3DecisionSession(session):
                decision, status = None, "AMBIGUOUS"
            elif (
                status == "AMBIGUOUS"
                and binding is None
                and refresh is not None
                and refresh.session is session
                and refresh.sequence == getattr(context, "_stage3_decision_sequence", None)
                and snapshot is context.GetSnapshot()
                and context.GetStage3DecisionBinding() is None
                and refresh is getattr(context, "_stage3_decision_active", None)
                and context.OwnsStage3DecisionSession(session)
            ):
                # The same owner-issued Refresh token spans this copy. Ambiguity
                # from a stale binding/session or post-commit mutation cannot qualify.
                unfinished_sequence = refresh.sequence
    except Exception:
        decision, status = None, "UNAVAILABLE"
    return ProbeSnapshotEvidence(
        snapshot=snapshot,
        local_baselines=local_items,
        remote_player_baselines=remote_items,
        roster_signature=signature,
        decision=decision,
        decision_status=status,
        unfinished_refresh_sequence=unfinished_sequence,
        owner=owner,
    )


class Stage3EvidenceProbeDiagnostics:
    """Bounded attempt-scoped records of real production refreshes and forwarding."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active: _ProbeAttempt | None = None
        self._events: deque[ProbeForwardingEvent] = deque(maxlen=_EVENT_CAPACITY)
        self._refresh_events: deque[ProbeRefreshEvent] = deque(maxlen=_EVENT_CAPACITY)
        self._next_attempt_id = 0
        self._next_sequence = 0
        self._next_refresh_sequence = 0
        self._decision_context: CleansingContext | None = None
        self._decision_session: object | None = None
        self._owner_cursor = 0
        self._owner_gap = False
        self._ordered_gap = False
        self.last_begin_reason = "not_attempted"
        self._forward_dropped_through = 0
        self._refresh_dropped_through = 0

    def capture_observation(
        self, context: CleansingContext, attempt_id: int | None = None
    ) -> ProbeSnapshotEvidence | None:
        """Select the Refresh token before its snapshot; never look up a later token."""
        active_id = self.active_attempt_id(context)
        with self._lock:
            attempt = self._active
            session = (
                self._decision_session
                if attempt is not None
                and attempt.context is context
                and attempt.attempt_id == active_id
                and (attempt_id is None or attempt.attempt_id == attempt_id)
                else None
            )
        try:
            binding = context.GetStage3DecisionBinding() if session is not None else None
            refresh = cast(_RefreshView | None, getattr(context, "_stage3_decision_active", None))
        except Exception:
            binding = None
            refresh = None
        snapshot = context.GetSnapshot()
        return capture_snapshot_evidence(context, snapshot, binding, session, refresh)

    def _owns_session(self, context: CleansingContext) -> bool:
        try:
            return (
                self._decision_context is context
                and self._decision_session is not None
                and context.OwnsStage3DecisionSession(self._decision_session)
            )
        except Exception:
            return False

    def capture_snapshot(
        self,
        context: CleansingContext,
        snapshot: CleansingContextSnapshot,
    ) -> ProbeSnapshotEvidence | None:
        return capture_snapshot_evidence(context, snapshot)

    def begin(
        self,
        context: CleansingContext,
        evidence: ProbeSnapshotEvidence,
        activated_at_ns: int | None = None,
    ) -> int | None:
        now = monotonic_ns()
        activated = now if activated_at_ns is None else activated_at_ns
        if activated > now or now >= activated + _ATTEMPT_LEASE_NS:
            self.last_begin_reason = "attempt_activation_time_invalid_or_expired"
            return None
        with self._lock:
            previous = self._active
        if previous is not None:
            self.end(previous.attempt_id)

        def arm(source: Stage3OwnerEvidence, cursor: int) -> int | None:
            # Owner evidence -> recorder -> decision session. No runtime reads.
            with self._lock:
                if self._active is not None:
                    self.last_begin_reason = "recorder_attempt_replaced"
                    return None
                coherent = capture_snapshot_evidence(context, source.snapshot, owner=source)
                if coherent is None or coherent.roster_signature != evidence.roster_signature:
                    self.last_begin_reason = "completed_outpost_signature_changed"
                    return None
                self._next_attempt_id += 1
                session = object()
                candidate = _ProbeAttempt(
                    attempt_id=self._next_attempt_id,
                    context=context,
                    starting_revision=source.snapshot.revision,
                    starting_lifecycle_epoch=source.snapshot.lifecycle_epoch,
                    starting_map_id=source.snapshot.map_id or 0,
                    starting_sequence=self._next_sequence,
                    starting_refresh_sequence=self._next_refresh_sequence,
                    starting_roster_signature=evidence.roster_signature,
                    lease_expires_at_ns=activated + _ATTEMPT_LEASE_NS,
                    source=source,
                    deadline_ns=activated + _ATTEMPT_LEASE_NS,
                    starting_owner_sequence=cursor,
                )
                try:
                    context.SetStage3DecisionSession(session)
                    context.BeginStage3ProofRetention(
                        session, candidate.attempt_id, source, cursor, candidate.deadline_ns / 1_000_000_000
                    )
                except Exception:
                    try:
                        context.RetireStage3DecisionSession(session)
                    except Exception:
                        pass
                    raise
                self._decision_context, self._decision_session = context, session
                self._active = candidate
                self._owner_cursor = cursor
                self._owner_gap = False
                self._ordered_gap = False
                self._events.clear()
                self._refresh_events.clear()
                self._forward_dropped_through = 0
                self._refresh_dropped_through = 0
                self.last_begin_reason = "armed"
                return self._next_attempt_id

        def refuse(reason: str) -> None:
            self.last_begin_reason = reason

        try:
            self.last_begin_reason = "owner_binding_unavailable"
            return context.ArmStage3Outpost(evidence.snapshot, arm, refuse)
        except Exception:
            self.last_begin_reason = "owner_binding_exception"
            return None

    def heartbeat(self, attempt_id: int, context: CleansingContext) -> bool:
        return self.active_attempt_id(context) == attempt_id

    def active_attempt_id(self, context: CleansingContext) -> int | None:
        with self._lock:
            attempt = self._active
            valid = (
                attempt is not None
                and attempt.context is context
                and monotonic_ns() < attempt.deadline_ns
                and self._owns_session(context)
            )
            identifier = attempt.attempt_id if attempt is not None else None
        if not valid:
            if identifier is not None and attempt is not None and attempt.context is context:
                self.end(identifier)
            return None
        return identifier

    def source_proof(self, attempt_id: int, context: CleansingContext) -> Stage3OwnerEvidence | None:
        if self.active_attempt_id(context) != attempt_id:
            return None
        with self._lock:
            attempt = self._active
            return attempt.source if attempt is not None and attempt.attempt_id == attempt_id else None

    def starting_cursor(self, attempt_id: int, context: CleansingContext) -> int | None:
        if self.active_attempt_id(context) != attempt_id:
            return None
        with self._lock:
            attempt = self._active
            return attempt.starting_owner_sequence if attempt is not None and attempt.attempt_id == attempt_id else None

    def evidence_for(self, context: CleansingContext, owner: Stage3OwnerEvidence) -> ProbeSnapshotEvidence | None:
        return capture_snapshot_evidence(context, owner.snapshot, owner=owner)

    def read_ordered_events(self, attempt_id: int, after_sequence: int) -> ProbeOrderedBatch:
        with self._lock:
            attempt = self._active
        if attempt is None or attempt.attempt_id != attempt_id:
            if attempt is not None:
                return ProbeOrderedBatch(False, False, (), after_sequence, replaced=True)
            return ProbeOrderedBatch(False, False, (), after_sequence)
        if self.active_attempt_id(attempt.context) != attempt_id:
            return ProbeOrderedBatch(False, False, (), after_sequence, replaced=monotonic_ns() < attempt.deadline_ns)
        batch = attempt.context.ReadStage3OwnerEvidence(max(after_sequence, attempt.starting_owner_sequence))
        with self._lock:
            if self._active is not attempt or not self._owns_session(attempt.context):
                return ProbeOrderedBatch(False, False, (), after_sequence, replaced=True)
            self._ordered_gap = self._ordered_gap or batch.gap
            return ProbeOrderedBatch(True, self._ordered_gap, batch.events, batch.watermark)

    def retain_processed_proofs(
        self,
        attempt_id: int,
        context: CleansingContext,
        after_sequence: int,
        watermark: int,
        *,
        history: tuple[Stage3OwnerEvidence, ...],
        samples: tuple[Stage3OwnerEvidence, ...],
        latest: Stage3OwnerEvidence | None,
    ) -> bool:
        if self.active_attempt_id(context) != attempt_id:
            return False
        with self._lock:
            attempt, session = self._active, self._decision_session
        if attempt is None or session is None:
            return False

        def acknowledge() -> bool:
            with self._lock:
                if (
                    self._active is not attempt
                    or self._decision_session is not session
                    or self._decision_context is not context
                    or self._ordered_gap
                    or monotonic_ns() >= attempt.deadline_ns
                    or not self._owns_session(context)
                ):
                    return False
                # Legacy drain hints must not rediscover a gap in events already
                # authenticated and consumed by the ordered probe path.
                self._owner_cursor = max(self._owner_cursor, watermark)
                return True

        return context.RetainStage3Proofs(
            session, attempt_id, after_sequence, watermark, history, samples, latest, acknowledge
        )

    def readiness_reason(self, attempt_id: int, context: CleansingContext, source: Stage3OwnerEvidence) -> str:
        if self.active_attempt_id(context) != attempt_id:
            return "attempt_expired_or_replaced"
        with self._lock:
            attempt, session = self._active, self._decision_session
            if attempt is None or session is None or attempt.source is not source or self._ordered_gap:
                return "attempt_binding_changed"
        return context.InspectStage3Readiness(session, attempt_id, source)

    def forwarding_for(self, attempt_id: int, owner: Stage3OwnerEvidence) -> ProbeForwardingEvent | None:
        with self._lock:
            attempt = self._active
            if attempt is None or attempt.attempt_id != attempt_id:
                return None
            cached = next(
                (event for event in self._events if event.owner is owner and event.attempt_id == attempt_id), None
            )
            if cached is not None:
                return cached
            source = attempt.source
        boundary = owner.boundary
        observation = boundary.observation
        authentic = observation is not None and observation.loading.loading
        before = (
            owner.snapshot
            if observation is not None and boundary.loading is not observation.loading
            else source.snapshot
        )
        return ProbeForwardingEvent(
            sequence=owner.sequence,
            attempt_id=attempt_id,
            observed_at_ns=int(owner.observed_at * 1_000_000_000),
            forwarded_loading=authentic,
            before_revision=before.revision,
            before_lifecycle_epoch=before.lifecycle_epoch,
            before_map_id=before.map_id,
            before_ready=before.ready,
            after_revision=owner.snapshot.revision,
            after_lifecycle_epoch=owner.snapshot.lifecycle_epoch,
            after_map_id=owner.snapshot.map_id,
            after_ready=owner.snapshot.ready,
            transition_latched=boundary.loading is not None,
            before_roster_signature=attempt.starting_roster_signature,
            pre_forward_refresh_sequence=source.boundary.completed_refresh,
            pre_forward_refresh_observed_at_ns=int(source.observed_at * 1_000_000_000),
            pre_forward_refresh_after_attempt=False,
            pre_forward_refresh_matches_attempt=True,
            pre_forward_refresh_matches_snapshot=True,
            owner=owner,
        )

    def _sync_owner(self, context: CleansingContext) -> None:
        attempt_id = self.active_attempt_id(context)
        if attempt_id is None:
            return
        batch = self.read_ordered_events(attempt_id, self._owner_cursor)
        converted: list[tuple[Stage3OwnerEvidence, ProbeSnapshotEvidence | None]] = [
            (event, self.evidence_for(context, event)) for event in batch.events
        ]
        forwards = [
            self.forwarding_for(attempt_id, event)
            for event in batch.events
            if (
                event.kind == "observation"
                and event.boundary.observation is not None
                and not event.boundary.observation.readable
            )
        ]
        with self._lock:
            if self._active is None or self._active.attempt_id != attempt_id:
                return
            self._owner_gap = self._owner_gap or batch.overflowed
            for event in forwards:
                if event is not None and event.sequence > self._owner_cursor:
                    if len(self._events) == self._events.maxlen:
                        self._forward_dropped_through = self._events[0].sequence
                    self._events.append(event)
                    self._next_sequence = event.sequence
            for owner, evidence in converted:
                if owner.kind == "completion" and owner.sequence > self._owner_cursor:
                    if len(self._refresh_events) == self._refresh_events.maxlen:
                        self._refresh_dropped_through = self._refresh_events[0].sequence
                    self._refresh_events.append(
                        ProbeRefreshEvent(
                            owner.boundary.completed_refresh,
                            attempt_id,
                            int((owner.boundary.completed_at or owner.observed_at) * 1_000_000_000),
                            evidence,
                            owner,
                        )
                    )
                    self._next_refresh_sequence = owner.boundary.completed_refresh
            self._owner_cursor = max(self._owner_cursor, batch.watermark)

    def record_refresh(self, context: CleansingContext, snapshot: CleansingContextSnapshot) -> None:
        self._sync_owner(context)

    def record_forwarding(
        self,
        attempt_id: int,
        context: CleansingContext,
        forwarded_loading: bool,
        before: CleansingContextSnapshot,
        after: CleansingContextSnapshot,
        transition_latched: bool | None,
        before_evidence: ProbeSnapshotEvidence | None,
    ) -> None:
        # Legacy cache callback is only a drain hint. Its booleans and snapshots
        # cannot issue authority, create a completion, or change event order.
        self._sync_owner(context)

    def read_events(self, attempt_id: int, after_sequence: int) -> ProbeEventBatch:
        with self._lock:
            attempt = self._active
        if attempt is None or self.active_attempt_id(attempt.context) != attempt_id:
            return ProbeEventBatch(False, False, ())
        self._sync_owner(attempt.context)
        with self._lock:
            events = tuple(
                event
                for event in self._events
                if (
                    event.sequence > max(after_sequence, attempt.starting_owner_sequence)
                    and event.attempt_id == attempt_id
                )
            )
            return ProbeEventBatch(True, self._owner_gap or self._forward_dropped_through > after_sequence, events)

    def read_refresh_events(self, attempt_id: int, after_sequence: int) -> ProbeRefreshBatch:
        with self._lock:
            attempt = self._active
        if attempt is None or self.active_attempt_id(attempt.context) != attempt_id:
            return ProbeRefreshBatch(False, False, ())
        self._sync_owner(attempt.context)
        with self._lock:
            events = tuple(
                event
                for event in self._refresh_events
                if event.sequence > after_sequence
                and event.attempt_id == attempt_id
                and event.owner is not None
                and event.owner.sequence > attempt.starting_owner_sequence
            )
            return ProbeRefreshBatch(True, self._owner_gap or self._refresh_dropped_through > after_sequence, events)

    def verify_and_commit(
        self,
        attempt_id: int,
        context: CleansingContext,
        third: Stage3OwnerEvidence,
        watermark: int,
        commit: Callable[[], bool],
        *,
        history: tuple[Stage3OwnerEvidence, ...] = (),
        samples: tuple[Stage3OwnerEvidence, ...] = (),
        diagnostic: Stage3FinalVerificationDiagnostic | None = None,
    ) -> bool:
        diagnostic = diagnostic if diagnostic is not None else Stage3FinalVerificationDiagnostic()
        diagnostic.stage = "recorder"
        if self.active_attempt_id(context) != attempt_id:
            diagnostic.session_current = False
            return diagnostic.reject("recorder", "attempt_expired_or_replaced")
        with self._lock:
            attempt = self._active
            session = self._decision_session
            if self._ordered_gap:
                return diagnostic.reject("evidence", "observation_gap")
        if attempt is None or attempt.attempt_id != attempt_id or attempt.context is not context or session is None:
            return diagnostic.reject("recorder", "attempt_binding")
        if history and history[0] is not attempt.source:
            return diagnostic.reject("recorder", "original_source_replaced")

        def freeze() -> bool:
            diagnostic.stage = "recorder"
            with self._lock:
                if (
                    self._active is not attempt
                    or monotonic_ns() >= attempt.deadline_ns
                    or self._decision_session is not session
                    or self._decision_context is not context
                    or not self._owns_session(context)
                    or self._ordered_gap
                    or third.boundary.transition_id != attempt.source.boundary.transition_id
                    or third.boundary.source_generation != attempt.source.boundary.source_generation
                ):
                    return diagnostic.reject("recorder", "commit_session_or_attempt")
                return commit()

        return context.VerifyStage3Destination(
            third,
            watermark,
            session,
            freeze,
            history=(attempt.source, *history),
            samples=samples,
            diagnostic=diagnostic,
        )

    def end(self, attempt_id: int) -> None:
        with self._lock:
            if self._active is None or self._active.attempt_id != attempt_id:
                return
            context, session = self._decision_context, self._decision_session
            self._active = None
            self._decision_context = None
            self._decision_session = None
            self._events.clear()
            self._refresh_events.clear()
        # Never acquire the owner evidence lock while holding the recorder lock.
        if context is not None and session is not None:
            context.RetireStage3DecisionSession(session)


STAGE3_EVIDENCE_PROBE_DIAGNOSTICS = Stage3EvidenceProbeDiagnostics()
