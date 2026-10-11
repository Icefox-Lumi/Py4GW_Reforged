"""Temporary, passive Stage 3 evidence probe for the Widget Browser.

Enable before the ready-outpost baseline. The probe reads published evidence and the
temporary passive Upkeeper forwarding recorder; it never drives or repairs game state.
Widget enablement also arms the local-witness console diagnostic until the widget
is disabled, including after this probe finishes its evidence collection.
"""

# pyright: strict

from __future__ import annotations

from collections import Counter
from importlib import import_module
from time import monotonic
from time import monotonic_ns
from typing import Callable
from typing import NamedTuple
from typing import Protocol
from typing import cast

import PySystem

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Map
from Py4GWCoreLib.GlobalCache.CleansingContext import CleansingContext
from Py4GWCoreLib.GlobalCache.CleansingContext import CleansingContextSnapshot
from Py4GWCoreLib.GlobalCache.CleansingContext import CleansingRole
from Py4GWCoreLib.GlobalCache.CleansingContext import CleansingSkillIDs
from Py4GWCoreLib.GlobalCache.CleansingContext import CompositionStatus
from Py4GWCoreLib.GlobalCache.CleansingContext import EvidenceSource
from Py4GWCoreLib.GlobalCache.CleansingContext import MemberKind
from Py4GWCoreLib.GlobalCache.CleansingContext import MemberRecord
from Py4GWCoreLib.GlobalCache.CleansingContext import RoleEvidence
from Py4GWCoreLib.GlobalCache.CleansingContext import recognize_role
from Py4GWCoreLib.GlobalCache.CleansingContext import Stage3OwnerEvidence
from Py4GWCoreLib.GlobalCache.CleansingContext import Stage3FinalVerificationDiagnostic
from Py4GWCoreLib.GlobalCache.CleansingContext import TransitionPhase
from Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics import STAGE3_EVIDENCE_PROBE_DIAGNOSTICS
from Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics import ProbeForwardingEvent
from Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics import ProbeRefreshEvent
from Py4GWCoreLib.GlobalCache.Stage3EvidenceProbeDiagnostics import ProbeSnapshotEvidence

_cleansing_context_module = import_module(CleansingContext.__module__)

MODULE_NAME = "Stage 3 Evidence Probe"
_PREFIX = "STAGE3_EVIDENCE_V1"
_MAX_RUNTIME_SECONDS = 180.0
_MAX_PREFLIGHT_SECONDS = 10.0
_FINALIZATION_RETRY_SECONDS = 1.0
_MAX_OUTPUT_LINES = 24
_MAX_OUTPUT_CHARACTERS = 1024
_RESERVED_EVIDENCE_LINES = 7
_MAX_OUTPOST_DELTA_CHARACTERS = 256  # Complete console record, including newline.
_MAX_OUTPOST_CAUSE_CHARACTERS = 256
# Counter text is exact: decimal through 999, otherwise 0z followed by base-36 digits.
# Python counters have no upper bound. Values outside this display range fail closed;
# they are never rounded, clipped, hashed, or used in place of the original integers.
_MAX_DISPLAY_COUNTER = (1 << 64) - 1
_MAX_REASON_CHARACTERS = len("remote_player_role_contradicts_outpost_baseline")


class _CounterDisplayOverflow(ValueError):
    """The exact counter cannot be represented by the bounded output contract."""


def _counter_text(value: int) -> str:
    if not 0 <= value <= _MAX_DISPLAY_COUNTER:
        raise _CounterDisplayOverflow
    if value <= 999:
        return str(value)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, digit = divmod(value, 36)
        encoded = digits[digit] + encoded
    return "0z" + encoded


def _record(event: str, details: str = "") -> str:
    return f"{_PREFIX} event={event} {details}".rstrip()


def _loading_details(
    seq: str, refresh: str, before_rev: str, after_rev: str, before_epoch: str, after_epoch: str
) -> str:
    return f"seq={seq} fwd=1 map=1 refresh={refresh} rev={before_rev}>{after_rev} epoch={before_epoch}>{after_epoch} latch=1"


def _sample_details(
    number: int, refresh: str, epoch: str, player: str = "", hero: str = "", continuity: str = ""
) -> str:
    details = f"{number}/3 refresh={refresh} e={epoch}"
    if number < 3:
        details += f" roles={player}/{hero} c={continuity}"
    return details


def _final_details(result: str, reason: str, attempt: str, loading: int, samples: int) -> str:
    return f"result={result} reason={reason} attempt={attempt} loading={loading} samples={samples}/3"


def _failure_output_details(reason: str, error: str) -> str:
    return f"result=FAILURE reason={reason} output={error}"


# Derive reservations from the same serializers used below, including each newline.
# Seven evidence records and one verdict are separate, non-borrowing budgets. Optional
# diagnostics may disappear; evidence and the terminal record cannot spend their space.
_WIDEST_COUNTER = _counter_text(_MAX_DISPLAY_COUNTER)
_DESTINATION_EVIDENCE_CHARACTERS = sum(
    len(_record(event, details)) + 1
    for event, details in (
        ("outpost", "created roster=8/8"),
        ("loading", _loading_details(*((_WIDEST_COUNTER,) * 6))),
        ("destination_sample", _sample_details(1, _WIDEST_COUNTER, _WIDEST_COUNTER, "BiP", "UNK", "1/1/1")),
        ("destination_sample", _sample_details(2, _WIDEST_COUNTER, _WIDEST_COUNTER, "BiP", "UNK", "1/1/1")),
        ("destination_sample", _sample_details(3, _WIDEST_COUNTER, _WIDEST_COUNTER)),
    )
)
# Before Loading, a rejection uses the unused Loading/sample reservation instead.
# These paths are mutually exclusive; neither may borrow the verdict reservation.
_REQUIRED_EVIDENCE_CHARACTERS = _MAX_OUTPOST_CAUSE_CHARACTERS + max(
    _DESTINATION_EVIDENCE_CHARACTERS,
    len(_record("outpost", "created roster=8/8")) + 1 + _MAX_OUTPOST_DELTA_CHARACTERS,
)
_FINAL_OUTPUT_RESERVE = max(
    len(_record("final", details)) + 1
    for details in (
        _final_details("INCONCLUSIVE", "x" * _MAX_REASON_CHARACTERS, _WIDEST_COUNTER, 1, 3),
        _failure_output_details("x" * _MAX_REASON_CHARACTERS, "counter_display_overflow"),
    )
)
assert _REQUIRED_EVIDENCE_CHARACTERS + _FINAL_OUTPUT_RESERVE <= _MAX_OUTPUT_CHARACTERS
# Readiness shares the existing character reservation: outpost rejection and
# destination evidence are mutually exclusive. It has its own reserved line.
assert (
    max(
        _DESTINATION_EVIDENCE_CHARACTERS,
        len(_record("outpost", "created roster=8/8"))
        + 1
        + _MAX_OUTPOST_DELTA_CHARACTERS
        + _MAX_OUTPOST_CAUSE_CHARACTERS,
    )
    + len(_record("no_go", "reason=" + "x" * _MAX_REASON_CHARACTERS))
    + 1
    <= _REQUIRED_EVIDENCE_CHARACTERS
)
assert _RESERVED_EVIDENCE_LINES + 1 <= _MAX_OUTPUT_LINES
_MAX_OUTPOST_DETAIL_REPORTS = 5
_OUTPOST_DETAIL_INTERVAL_SECONDS = 1.0
_OUTPOST_WAIT_PHASE = 1
_OUTPOST_WAIT_SNAPSHOT = 2
_OUTPOST_WAIT_MEMBERS = 3
_OUTPOST_REPORT_BASELINE = 4
_OUTPOST_REPORT_CREATED = 5
_POLL_SECONDS = 0.25
_SAMPLE_INTERVAL_SECONDS = 1.0
_SAMPLE_INTERVAL_NS = 1_000_000_000
_REQUIRED_DESTINATION_SAMPLES = 3
_FORWARDING_FRESHNESS_NS = 750_000_000
_PREFORWARD_REFRESH_FRESHNESS_NS = 1_000_000_000
_OUTPOST_WITNESS_KIND = 1

_EXPECTED_LOCAL_PLAYER = Counter({CleansingRole.HEROIC_REFRAIN: 1})
_EXPECTED_LOCAL_HEROES_BY_REMOTE_PLAYER = {
    CleansingRole.ENERGY_SURGE: Counter(
        {
            CleansingRole.BIP: 1,
            CleansingRole.SOUL_TWISTING: 1,
            CleansingRole.INEPTITUDE: 1,
            CleansingRole.ENERGY_SURGE: 2,
        }
    ),
    CleansingRole.BIP: Counter(
        {
            CleansingRole.SOUL_TWISTING: 1,
            CleansingRole.INEPTITUDE: 1,
            CleansingRole.ENERGY_SURGE: 3,
        }
    ),
}
_EXPECTED_REMOTE_HEROES = Counter({CleansingRole.ENERGY_SURGE: 1})


class _PublisherView(Protocol):
    recovery_epoch: int
    incarnation: bytes
    character_uuid: tuple[int, ...]
    account_email: str
    hwnd: int


class _RemotePlayerBaselineView(Protocol):
    publisher: _PublisherView
    party_id: int
    destination_map_id: int | None
    destination_lifecycle_epoch: int | None
    destination_instance_epoch: int | None


class _NativeMapView(Protocol):
    MapID: int


class _NativeAgentView(Protocol):
    LoginNumber: int
    AgentID: int
    Map: _NativeMapView


class _NativeKeyView(Protocol):
    HWND: int


class _NativePartyView(Protocol):
    PartyID: int


class _NativeOwnerView(Protocol):
    AccountEmail: str
    Key: _NativeKeyView
    AgentData: _NativeAgentView
    AgentPartyData: _NativePartyView


class _NativeEvidenceView(Protocol):
    def GetAccountData(self) -> _NativeOwnerView: ...


class _NativeWitnessView(Protocol):
    kind: object
    hero_id: int
    primary: int
    skills: tuple[int, ...]


class _NativeCohortView(Protocol):
    owner: _NativeEvidenceView
    incarnation: bytes
    character_uuid: tuple[int, ...]
    instance_type: int
    witnesses: tuple[_NativeWitnessView, ...]


class _NativeSnapshotView(Protocol):
    recovery_epoch: int
    cohorts: tuple[_NativeCohortView, ...]


class _PublisherIdentity(NamedTuple):
    recovery_epoch: int
    incarnation: bytes
    character_uuid: tuple[int, ...]
    account_email: str
    hwnd: int


class _SnapshotEvidence(NamedTuple):
    snapshot: CleansingContextSnapshot
    signature: tuple[object, ...]
    production_evidence: ProbeSnapshotEvidence | None
    local_player_roles: Counter[CleansingRole]
    local_hero_roles: Counter[CleansingRole]
    remote_player_roles: Counter[CleansingRole]
    remote_hero_roles: Counter[CleansingRole]
    local_baseline_count: int
    local_roster_keys: tuple[tuple[MemberKind, int, int], ...]
    party_id: int | None
    remote_player: MemberRecord | None
    remote_hero: MemberRecord | None
    remote_player_baseline: _RemotePlayerBaselineView | None
    composition_unknown: int
    complete_eight: bool
    local_roles_match: bool
    remote_player_baseline_retained: bool
    stage4_fence: bool


class _OutpostBaseline(NamedTuple):
    attempt_id: int
    revision: int
    lifecycle_epoch: int
    map_id: int
    signature: tuple[object, ...]
    roster_signature: tuple[object, ...]
    local_character_identity: tuple[str, str] | None
    local_roster_keys: tuple[tuple[MemberKind, int, int], ...]
    party_id: int
    remote_player_role: CleansingRole
    remote_hero_key: tuple[MemberKind, int, int]
    publisher: _PublisherIdentity
    publisher_generation: int
    witness_status: str
    original_witness_role: CleansingRole | None
    original_witness_build_complete: bool


class _OutpostWitnessEvidence(NamedTuple):
    status: str
    role: CleansingRole | None
    build_complete: bool
    reason_code: str = "none"


class _DiagnosticUnavailable(RuntimeError):
    """Signals that required temporary recorder evidence could not be read."""


class _TerminalOutcome(NamedTuple):
    result: str
    reason: str
    details: str


_started_at: float | None = None
_last_poll_at = 0.0
_lines = 0
_characters = 0
_optional_characters = 0
_required_characters = 0
_optional_lines = 0
_required_lines = 0
_finished = False
_outpost_report_stage = 0
_outpost_detail_signature: str | None = None
_outpost_detail_report_count = 0
_outpost_detail_last_emit: float | None = None
_outpost_detail_last_ready = False
_outpost_baseline_reported = False
_outpost_detail_budget_exhausted = False
_outpost_unready_since: float | None = None
_outpost_baseline: _OutpostBaseline | None = None
_attempt_id: int | None = None
_last_forwarding_sequence = 0
_last_refresh_sequence = 0
_candidate_loading_event: ProbeForwardingEvent | None = None
_loading_event: ProbeForwardingEvent | None = None
_destination_signature: tuple[object, ...] | None = None
_destination_last_revision: int | None = None
_destination_last_sample_at: int | None = None
_destination_last_refresh_sequence: int | None = None
_destination_samples = 0
_pending_destination_sample_details: list[str] = []
_sample_output_error: str | None = None
_pending_outpost_details: list[tuple[str, ...]] = []
_pending_outpost_delta: str | None = None
_pending_outpost_cause: str | None = None
_deferred_outpost_refresh: int | None = None
_terminal_details: str | None = None
_terminal_outcome: _TerminalOutcome | None = None
_next_finalization_retry_at = 0.0
_owner_source: Stage3OwnerEvidence | None = None
_last_owner_sequence = 0
_owner_watermark = 0
_admission_event: Stage3OwnerEvidence | None = None
_accepted_destination_events: tuple[Stage3OwnerEvidence, ...] = ()
_latest_destination_owner: Stage3OwnerEvidence | None = None
_fixed_production_deadline: float | None = None
_last_completion_time: float | None = None
_final_verify_diagnostic_emitted = False
_readiness_reported = False
_readiness_characters = 0


def _emit(event: str, details: str = "", *, final: bool = False, reserved: bool = False) -> bool:
    global _lines, _characters, _optional_characters, _required_characters, _optional_lines, _required_lines
    global _readiness_characters
    if _finished:
        return False
    line = _record(event, details)
    if "\n" in line or "\r" in line:
        return False
    line_characters = len(line) + 1
    next_characters = _characters + line_characters
    terminal_prepared = _terminal_details is not None
    if reserved and terminal_prepared:
        return False
    terminal_characters = (
        len(_record("final", _terminal_details)) + 1 if _terminal_details is not None else _FINAL_OUTPUT_RESERVE
    )
    line_limit = (
        _MAX_OUTPUT_LINES
        if final
        else (
            _MAX_OUTPUT_LINES - 1 if reserved or terminal_prepared else _MAX_OUTPUT_LINES - _RESERVED_EVIDENCE_LINES - 1
        )
    )
    if _lines >= line_limit or next_characters > (
        _MAX_OUTPUT_CHARACTERS if final else _MAX_OUTPUT_CHARACTERS - terminal_characters
    ):
        return False
    if (
        not final
        and not reserved
        and terminal_prepared
        and next_characters + terminal_characters
        > (_MAX_OUTPUT_CHARACTERS - _MAX_OUTPOST_CAUSE_CHARACTERS + _readiness_characters)
    ):
        return False
    if final:
        next_optional_characters = _optional_characters
        next_required_characters = _required_characters
    elif reserved:
        if (
            _required_lines >= _RESERVED_EVIDENCE_LINES
            or _required_characters + line_characters > _REQUIRED_EVIDENCE_CHARACTERS
        ):
            return False
        next_optional_characters = _optional_characters
        next_required_characters = _required_characters + line_characters
    else:
        optional_limit = _MAX_OUTPUT_CHARACTERS - _FINAL_OUTPUT_RESERVE - _REQUIRED_EVIDENCE_CHARACTERS
        if not terminal_prepared and (
            _optional_lines >= _MAX_OUTPUT_LINES - _RESERVED_EVIDENCE_LINES - 1
            or _optional_characters + line_characters > optional_limit
        ):
            return False
        next_optional_characters = _optional_characters + line_characters
        next_required_characters = _required_characters
    PySystem.Console.Log(MODULE_NAME, line, PySystem.Console.MessageType.Info)
    _lines += 1
    _characters = next_characters
    _optional_characters = next_optional_characters
    _required_characters = next_required_characters
    if reserved and event in ("ready_to_zone", "no_go"):
        # Spend readiness from the existing source-failure reservation, keeping
        # the established optional-detail capacity and the total hard cap.
        _readiness_characters += line_characters
    if not final:
        if reserved:
            _required_lines += 1
        else:
            _optional_lines += 1
    return True


def _finish(result: str, reason: str) -> None:
    global _terminal_outcome
    if _finished:
        return
    if _terminal_outcome is not None:
        _retry_finalization()
        return
    if not _readiness_reported and result != "FULL_SUCCESS":
        try:
            _report_zone_readiness(None, reason)
        except Exception:
            # A failed NO-GO delivery cannot keep a disabled attempt alive.
            pass
    if result == "FULL_SUCCESS":
        diagnostic = Stage3FinalVerificationDiagnostic()
        pre_samples = _destination_samples
        third = _accepted_destination_events[-1] if len(_accepted_destination_events) == 3 else None
        latest = _latest_destination_owner
        if _commit_full_success(reason, diagnostic):
            if _attempt_id is not None:
                try:
                    STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.end(_attempt_id)
                except Exception:
                    pass
            _retry_finalization()
            return
        _emit_final_verification_failure(diagnostic, pre_samples, third, latest)
        _reset_destination_samples()
        result, reason = "INCONCLUSIVE", "final_verification_failed"
    if _destination_signature is not None:
        # The recorder may expire before it captures an invalidation. GetSnapshot
        # returns the already-published object; this performs no game-memory read.
        try:
            context = getattr(GLOBAL_CACHE, "CleansingContext", None)
            if isinstance(context, CleansingContext):
                snapshot = context.GetSnapshot()
                if (
                    not snapshot.ready
                    or (snapshot.map_id, snapshot.lifecycle_epoch) != _destination_signature[:2]
                    or (_destination_last_revision is not None and snapshot.revision < _destination_last_revision)
                ):
                    _reset_destination_samples()
        except Exception:
            # No new invalidation is proven; retain observations and fail incomplete.
            if result != "FAILURE":
                result, reason = "INCONCLUSIVE", "probe_read_failed"
    output_error = _sample_output_error
    try:
        attempt_text = _counter_text(_attempt_id) if _attempt_id is not None else "none"
    except _CounterDisplayOverflow:
        attempt_text = "unprinted"
        output_error = output_error or "counter_display_overflow"
    if not reason.isascii() or not reason.isidentifier() or len(reason) > _MAX_REASON_CHARACTERS:
        reason = "verdict_detail_unrepresentable"
        if result != "FAILURE":
            result = "INCONCLUSIVE"
    if output_error is not None and result != "FAILURE":
        result, reason = "INCONCLUSIVE", output_error
    details = _final_details(result, reason, attempt_text, int(_loading_event is not None), _destination_samples)
    if output_error is not None and result == "FAILURE":
        # Preserve the contradiction and explicitly report lost output within the same reserve.
        details = _failure_output_details(reason, output_error)
    # Commit the outcome and retain the remaining evidence before releasing the
    # recorder. From this point, updates may only resume output, never recollect.
    _terminal_outcome = _TerminalOutcome(result, reason, details)
    if _attempt_id is None:
        # A blocked preflight needs its current explanation, not transient history.
        del _pending_outpost_details[1:]
    if _attempt_id is not None:
        try:
            STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.end(_attempt_id)
        except Exception:
            # Cleanup cannot change a committed verdict. The recorder lease also
            # expires independently; retries perform no further recorder polling.
            pass
    _retry_finalization()


def _emit_final_verification_failure(
    diagnostic: Stage3FinalVerificationDiagnostic,
    pre_samples: int,
    third: Stage3OwnerEvidence | None,
    latest: Stage3OwnerEvidence | None,
) -> None:
    global _final_verify_diagnostic_emitted
    if _final_verify_diagnostic_emitted:
        return
    _final_verify_diagnostic_emitted = True
    try:

        def counter(event: Stage3OwnerEvidence | None) -> str:
            try:
                return _counter_text(event.boundary.completed_refresh) if event is not None else "unavailable"
            except Exception:
                return "unavailable"

        def flag(value: bool | None) -> str:
            return "unavailable" if value is None else str(int(value))

        line = (
            "STAGE3_FINAL_VERIFY_DIAG_V1 "
            f"boundary={diagnostic.boundary or diagnostic.stage} gate={diagnostic.gate or 'unreported'} "
            f"pre_samples={min(max(pre_samples, 0), 3)} third={counter(third)} latest={counter(latest)} "
            f"inputs_current={flag(diagnostic.inputs_current)} "
            f"watermark_current={flag(diagnostic.watermark_current)} "
            f"session_current={flag(diagnostic.session_current)}"
        )
        PySystem.Console.Log(MODULE_NAME, line, PySystem.Console.MessageType.Info)
    except Exception:
        # Delivery is best effort and cannot alter a refusal or replay on retry.
        pass


def _commit_full_success(reason: str, diagnostic: Stage3FinalVerificationDiagnostic | None = None) -> bool:
    global _terminal_outcome
    diagnostic = diagnostic if diagnostic is not None else Stage3FinalVerificationDiagnostic()
    baseline = _outpost_baseline
    loading = _loading_event
    source = _owner_source
    admission = _admission_event
    samples = _accepted_destination_events
    latest = _latest_destination_owner
    context = getattr(GLOBAL_CACHE, "CleansingContext", None)
    if reason != "three_stable_destination_samples" or not isinstance(context, CleansingContext):
        return diagnostic.reject("probe", "reason_or_context")
    if _started_at is None or monotonic() >= _started_at + _MAX_RUNTIME_SECONDS:
        return diagnostic.reject("probe", "attempt_deadline")
    if baseline is None or source is None or loading is None or loading.owner is None or admission is None:
        return diagnostic.reject("probe", "original_proof_or_loading_missing")
    if (
        admission.boundary.deadline != _fixed_production_deadline
        or admission.boundary.deadline is None
        or admission.boundary.completed_at is None
        or admission.boundary.completed_at >= admission.boundary.deadline
    ):
        return diagnostic.reject("probe", "admission_deadline")
    if _attempt_id != baseline.attempt_id or not _valid_initial_forwarding_event(loading, baseline):
        return diagnostic.reject("probe", "attempt_or_loading_association")
    if (
        _destination_samples != 3
        or len(samples) != 3
        or len({event.boundary.completed_refresh for event in samples}) != 3
        or latest is None
    ):
        return diagnostic.reject("probe", "three_distinct_samples_required")
    if _sample_output_error is not None or _terminal_outcome is not None:
        return diagnostic.reject("probe", "output_or_terminal_state")
    watermark = _owner_watermark
    if _last_owner_sequence != watermark or latest.sequence > watermark:
        return diagnostic.reject("evidence", "undrained_owner_events")
    for first, second in zip(samples, samples[1:]):
        if (
            first.sequence >= second.sequence
            or first.boundary.completed_refresh >= second.boundary.completed_refresh
            or first.boundary.completed_at is None
            or second.boundary.completed_at is None
            or second.boundary.completed_at - first.boundary.completed_at < 1.0
        ):
            return diagnostic.reject("probe", "sample_order_or_spacing")
    if latest.sequence < samples[-1].sequence:
        return diagnostic.reject("probe", "closing_anchor_order")
    try:
        diagnostic.stage = "probe"
        for event in (*samples, latest):
            boundary = event.boundary
            if (
                event.kind != "completion"
                or boundary.transition_id != source.boundary.transition_id
                or boundary.source_generation != source.boundary.source_generation
                or boundary.destination != admission.boundary.destination
                or boundary.lifecycle_generation != admission.boundary.lifecycle_generation
                or boundary.loading is not loading.owner.boundary.loading
                or boundary.deadline != _fixed_production_deadline
                or boundary.phase is not TransitionPhase.DESTINATION_VERIFIED
                or boundary.retired_members
            ):
                return diagnostic.reject("probe", "completion_association")
            production = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.evidence_for(context, event)
            if production is None or event.verification is None:
                return diagnostic.reject("probe", "completion_inputs_missing")
            if (
                _classify_destination(_snapshot_evidence(event.snapshot, context, production), baseline)[0]
                != "FULL_SUCCESS"
            ):
                return diagnostic.reject("probe", "destination_classification")
        details = _final_details("FULL_SUCCESS", reason, _counter_text(baseline.attempt_id), 1, 3)

        def commit() -> bool:
            global _terminal_outcome
            diagnostic.stage = "commit"
            if (
                _terminal_outcome is not None
                or _finished
                or _outpost_baseline is not baseline
                or _loading_event is not loading
                or _owner_source is not source
                or _admission_event is not admission
                or _accepted_destination_events is not samples
                or _destination_samples != 3
                or _latest_destination_owner is not latest
                or _owner_watermark != watermark
                or _last_owner_sequence != watermark
                or _attempt_id != baseline.attempt_id
                or _sample_output_error is not None
                or vars(GLOBAL_CACHE).get("CleansingContext") is not context
                or _started_at is None
                or monotonic() >= _started_at + _MAX_RUNTIME_SECONDS
            ):
                return diagnostic.reject("commit", "probe_binding_changed")
            _terminal_outcome = _TerminalOutcome("FULL_SUCCESS", reason, details)
            return True

        return STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.verify_and_commit(
            baseline.attempt_id,
            context,
            latest,
            watermark,
            commit,
            history=(source, loading.owner, admission),
            samples=samples,
            diagnostic=diagnostic,
        )
    except Exception:
        return diagnostic.reject(diagnostic.stage, "exception")


def _retry_finalization() -> None:
    global _finished, _terminal_details, _next_finalization_retry_at, _outpost_detail_report_count
    global _pending_outpost_delta, _pending_outpost_cause
    outcome = _terminal_outcome
    if _finished or outcome is None:
        return
    now = monotonic()
    if now < _next_finalization_retry_at:
        return
    _next_finalization_retry_at = now + _FINALIZATION_RETRY_SECONDS
    while _pending_destination_sample_details:
        try:
            emitted = _emit("destination_sample", _pending_destination_sample_details[0], reserved=True)
        except Exception:
            return
        if not emitted:
            return
        # A successful logger return is the delivery acknowledgement. Failed
        # records retain their place; successful records are never replayed.
        del _pending_destination_sample_details[0]
    if _pending_outpost_delta is not None:
        try:
            if not _emit("outpost_delta", _pending_outpost_delta, reserved=True):
                return
        except Exception:
            return
        _pending_outpost_delta = None
    if _pending_outpost_cause is not None:
        try:
            if not _emit("outpost_cause", _pending_outpost_cause, reserved=True):
                return
        except Exception:
            return
        _pending_outpost_cause = None
    _terminal_details = outcome.details
    # A blocked preflight's latest diagnostic is required before its verdict.
    # Established validation retains optional, best-effort diagnostic output.
    while _pending_outpost_details:
        alternatives = _pending_outpost_details[0]
        emitted = False
        try:
            for diagnostic_details in alternatives:
                if _emit("outpost_detail", diagnostic_details):
                    _outpost_detail_report_count += 1
                    emitted = True
                    break
        except Exception:
            if _attempt_id is None:
                return
        if not emitted and _attempt_id is None:
            return
        del _pending_outpost_details[0]
    try:
        emitted = _emit("final", outcome.details, final=True)
    except Exception:
        return
    if emitted:
        _finished = True


def _runtime_limit_reason() -> str:
    if _attempt_id is None:
        return "outpost_baseline_not_established"
    if _deferred_outpost_refresh is not None:
        return "outpost_refresh_unresolved"
    return "loading_not_observed" if _loading_event is None else "stable_destination_samples_incomplete"


def _phase() -> str:
    if Map.IsMapLoading():
        return "loading"
    if not Map.IsMapReady():
        return "unknown"
    if Map.IsOutpost():
        return "outpost"
    if Map.IsExplorable():
        return "explorable"
    return "unknown"


def _remote_records(snapshot: CleansingContextSnapshot) -> tuple[MemberRecord | None, MemberRecord | None]:
    remote_players = tuple(
        member for member in snapshot.members if member.evidence_source is EvidenceSource.REMOTE_PLAYER
    )
    remote_heroes = tuple(member for member in snapshot.members if member.evidence_source is EvidenceSource.REMOTE_HERO)
    player = remote_players[0] if len(remote_players) == 1 else None
    hero = remote_heroes[0] if len(remote_heroes) == 1 else None
    if player is not None and hero is not None and hero.identity.owner_id != player.identity.owner_id:
        hero = None
    return player, hero


def _local_baseline_keys(
    context: CleansingContext,
    production_evidence: ProbeSnapshotEvidence | None = None,
) -> set[tuple[MemberKind, int, int]]:
    if production_evidence is not None:
        return {key for key, _value in production_evidence.local_baselines}
    raw_baselines = getattr(context, "_baselines", None)
    if not isinstance(raw_baselines, dict):
        return set()
    typed_baselines = cast(dict[tuple[MemberKind, int, int], object], raw_baselines)
    return set(typed_baselines)


def _remote_player_baselines(
    context: CleansingContext,
    production_evidence: ProbeSnapshotEvidence | None = None,
) -> dict[tuple[MemberKind, int, int], _RemotePlayerBaselineView]:
    if production_evidence is not None:
        return cast(
            dict[tuple[MemberKind, int, int], _RemotePlayerBaselineView],
            dict(production_evidence.remote_player_baselines),
        )
    raw_baselines = getattr(context, "_remote_player_baselines", None)
    if not isinstance(raw_baselines, dict):
        return {}
    return cast(dict[tuple[MemberKind, int, int], _RemotePlayerBaselineView], raw_baselines)


def _publisher_identity(publisher: _PublisherView) -> _PublisherIdentity:
    return _PublisherIdentity(
        recovery_epoch=publisher.recovery_epoch,
        incarnation=publisher.incarnation,
        character_uuid=publisher.character_uuid,
        account_email=publisher.account_email.strip().casefold(),
        hwnd=publisher.hwnd,
    )


def _capture_evidence(context: CleansingContext) -> _SnapshotEvidence:
    try:
        production = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.capture_observation(context, _attempt_id)
    except Exception as error:
        raise _DiagnosticUnavailable from error
    if production is None:
        raise _DiagnosticUnavailable
    return _snapshot_evidence(production.snapshot, context, production)


def _snapshot_evidence(
    snapshot: CleansingContextSnapshot,
    context: CleansingContext,
    production_evidence: ProbeSnapshotEvidence | None = None,
) -> _SnapshotEvidence:
    local_player_roles: Counter[CleansingRole] = Counter()
    local_hero_roles: Counter[CleansingRole] = Counter()
    remote_player_roles: Counter[CleansingRole] = Counter()
    remote_hero_roles: Counter[CleansingRole] = Counter()
    local_baseline_count = 0
    if production_evidence is None:
        try:
            production_evidence = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.capture_snapshot(context, snapshot)
        except Exception as error:
            raise _DiagnosticUnavailable from error
    local_baseline_keys = _local_baseline_keys(context, production_evidence)
    remote_baselines = _remote_player_baselines(context, production_evidence)
    remote_player, remote_hero = _remote_records(snapshot)

    for member in snapshot.members:
        if member.evidence_source is EvidenceSource.LOCAL_PLAYER:
            local_player_roles[member.role] += 1
            local_baseline_count += member.identity.stable_key in local_baseline_keys
        elif member.evidence_source is EvidenceSource.LOCAL_HERO:
            local_hero_roles[member.role] += 1
            local_baseline_count += member.identity.stable_key in local_baseline_keys
        elif member.evidence_source is EvidenceSource.REMOTE_PLAYER:
            remote_player_roles[member.role] += 1
        elif member.evidence_source is EvidenceSource.REMOTE_HERO:
            remote_hero_roles[member.role] += 1

    remote_player_baseline = (
        remote_baselines.get(remote_player.identity.stable_key) if remote_player is not None else None
    )
    remote_player_baseline_retained = remote_player_baseline is not None
    party_id = remote_player_baseline.party_id if remote_player_baseline is not None else None
    role_counts = dict(snapshot.composition.role_counts)
    composition_unknown = role_counts.get(CleansingRole.UNKNOWN, 0)
    complete_eight = (
        snapshot.ready
        and len(snapshot.members) == 8
        and snapshot.composition.member_count == 8
        and snapshot.composition.declared_party_size == 8
    )
    local_roles_match = local_player_roles == _EXPECTED_LOCAL_PLAYER and any(
        local_hero_roles == expected_heroes for expected_heroes in _EXPECTED_LOCAL_HEROES_BY_REMOTE_PLAYER.values()
    )
    stage4_fence = (
        snapshot.composition.status is CompositionStatus.FALLBACK
        and composition_unknown == 2
        and snapshot.composition.member_count == 8
        and snapshot.composition.declared_party_size == 8
    )

    signature_members: list[tuple[object, ...]] = []
    for member in snapshot.members:
        baseline = (
            remote_baselines.get(member.identity.stable_key)
            if member.evidence_source is EvidenceSource.REMOTE_PLAYER
            else None
        )
        publisher = _publisher_identity(baseline.publisher) if baseline is not None else None
        destination_epoch = baseline.destination_instance_epoch if baseline is not None else None
        signature_members.append(
            (
                member.evidence_source.value,
                member.identity.kind.value,
                member.identity.owner_id,
                member.identity.member_id,
                member.role.value,
                member.candidate_role.value,
                member.reason,
                member.primary_profession,
                member.anchor_skill_ids,
                member.remote_provenance_generation,
                publisher,
                destination_epoch,
            )
        )
    signature_members.sort(key=lambda item: tuple(str(value) for value in item[:4]))
    signature = (
        snapshot.map_id,
        snapshot.lifecycle_epoch,
        snapshot.ready,
        snapshot.composition.status.value,
        snapshot.composition.member_count,
        snapshot.composition.declared_party_size,
        tuple((role.value, count) for role, count in snapshot.composition.role_counts),
        tuple(signature_members),
        production_evidence.roster_signature if production_evidence is not None else None,
    )
    local_roster_keys = tuple(
        sorted(
            (
                member.identity.stable_key
                for member in snapshot.members
                if member.evidence_source in (EvidenceSource.LOCAL_PLAYER, EvidenceSource.LOCAL_HERO)
            ),
            key=lambda key: (key[0].value, key[1], key[2]),
        )
    )
    return _SnapshotEvidence(
        snapshot=snapshot,
        signature=signature,
        production_evidence=production_evidence,
        local_player_roles=local_player_roles,
        local_hero_roles=local_hero_roles,
        remote_player_roles=remote_player_roles,
        remote_hero_roles=remote_hero_roles,
        local_baseline_count=local_baseline_count,
        local_roster_keys=local_roster_keys,
        party_id=party_id,
        remote_player=remote_player,
        remote_hero=remote_hero,
        remote_player_baseline=remote_player_baseline,
        composition_unknown=composition_unknown,
        complete_eight=complete_eight,
        local_roles_match=local_roles_match,
        remote_player_baseline_retained=remote_player_baseline_retained,
        stage4_fence=stage4_fence,
    )


_DELTA_PUBLISHER_FIELDS = ("recovery_epoch", "incarnation", "character_uuid", "account_email", "hwnd")
_DELTA_MEMBER_FIELDS = (
    "source",
    "kind",
    "owner_id",
    "member_id",
    "agent_id",
    "role",
    "candidate_role",
    "reason",
    "profession",
    "anchors",
    "generation",
)
_DELTA_LOCAL_BASELINE_FIELDS = ("kind", "owner_id", "member_id", "role", "profession", "anchors")
_DELTA_REMOTE_BASELINE_FIELDS = (
    "kind",
    "owner_id",
    "member_id",
    "publisher.recovery_epoch",
    "publisher.incarnation",
    "publisher.character_uuid",
    "publisher.account_email",
    "publisher.hwnd",
    "role",
    "professions",
    "anchors",
    "local_character_identity",
    "local_character_uuid",
    "party_id",
    "outpost_map_id",
    "lifecycle_epoch",
    "destination_map_id",
    "destination_lifecycle_epoch",
    "destination_instance_epoch",
)
_DELTA_SNAPSHOT_FIELDS = (
    "map_id",
    "lifecycle_epoch",
    "ready",
    "character_identity",
    "composition.status",
    "composition.member_count",
    "composition.declared_party_size",
    "composition.role_counts",
)


def _delta_fields(before: object, after: object, names: tuple[str, ...], prefix: str, differences: list[str]) -> None:
    if before == after:
        return
    if not isinstance(before, tuple) or not isinstance(after, tuple):
        differences.append(prefix + "shape")
        return
    old = cast(tuple[object, ...], before)
    new = cast(tuple[object, ...], after)
    if len(old) != len(names) or len(new) != len(names):
        differences.append(prefix + "shape")
        return
    for name, old_value, new_value in zip(names, old, new):
        if old_value != new_value:
            if name == "publisher":
                _delta_fields(old_value, new_value, _DELTA_PUBLISHER_FIELDS, prefix + "publisher.", differences)
            else:
                differences.append(prefix + name)


def _delta_rows(before: object, after: object, names: tuple[str, ...], scope: str, differences: list[str]) -> None:
    if before == after:
        return
    if not isinstance(before, tuple) or not isinstance(after, tuple):
        differences.append(scope + ".shape")
        return
    old = cast(tuple[object, ...], before)
    new = cast(tuple[object, ...], after)
    if len(old) != len(new):
        differences.append(scope + ".count")
    if max(len(old), len(new)) > 8:
        differences.append(scope + ".shape")
    old, new = old[:8], new[:8]
    identity_columns = tuple(names.index(name) for name in ("kind", "owner_id", "member_id"))

    def identity(row: object) -> tuple[object, ...] | None:
        if not isinstance(row, tuple):
            return None
        values = cast(tuple[object, ...], row)
        return tuple(values[column] for column in identity_columns) if len(values) == len(names) else None

    matched: dict[int, int] = {}
    used: set[int] = set()
    for index, row in enumerate(old):
        key = identity(row)
        for candidate, new_row in enumerate(new):
            if key is not None and candidate not in used and key == identity(new_row):
                matched[index] = candidate
                used.add(candidate)
                break
    # Pair substitutions only after preserving all unchanged identities. A sorted
    # replacement must not make every intervening hero look like a role change.
    missing = [index for index in range(len(old)) if index not in matched]
    added = [index for index in range(len(new)) if index not in used]
    for index, candidate in zip(missing, added):
        matched[index] = candidate
        used.add(candidate)
    pairs = [(row, new[matched[index]] if index in matched else None) for index, row in enumerate(old)]
    pairs.extend((None, row) for index, row in enumerate(new) if index not in used)
    if len(old) == len(new) == len(matched) and all(left == right for left, right in pairs):
        differences.append(scope + ".order")
    ordinals: Counter[str] = Counter()
    for old_row, new_row in pairs:
        row = old_row if old_row is not None else new_row
        category = "M"
        if isinstance(row, tuple) and row:
            discriminator = cast(tuple[object, ...], row)[0]
            if scope == "members":
                for source, code in (
                    (EvidenceSource.LOCAL_PLAYER, "LP"),
                    (EvidenceSource.LOCAL_HERO, "LH"),
                    (EvidenceSource.REMOTE_PLAYER, "RP"),
                    (EvidenceSource.REMOTE_HERO, "RH"),
                ):
                    if discriminator == source.value:
                        category = code
            elif scope == "local_baselines":
                category = "LBP" if discriminator == MemberKind.PLAYER.value else "LBH"
            else:
                category = "RB"
        ordinals[category] += 1
        # Ordinals refer to sorted signature rows, never runtime identity values.
        prefix = f"{category}{ordinals[category]}."
        if old_row is None or new_row is None:
            differences.append(prefix + "presence")
        else:
            _delta_fields(old_row, new_row, names, prefix, differences)


def _outpost_delta_details(
    baseline: _OutpostBaseline, current: _SnapshotEvidence, max_characters: int = _MAX_OUTPOST_DELTA_CHARACTERS
) -> str:
    """Describe equality failures using only authored field names, never values."""
    differences: list[str] = []
    old, new = baseline.signature, current.signature
    if len(old) != 9 or len(new) != 9:
        differences.append("signature.shape")
    else:
        _delta_fields(old[:7], new[:7], _DELTA_SNAPSHOT_FIELDS[:3] + _DELTA_SNAPSHOT_FIELDS[4:], "", differences)
        outer_member_fields = tuple(name for name in _DELTA_MEMBER_FIELDS if name != "agent_id") + (
            "publisher",
            "destination_instance_epoch",
        )
        _delta_rows(old[7], new[7], outer_member_fields, "members", differences)
        old_roster, new_roster = old[8], new[8]
        if isinstance(old_roster, tuple) and isinstance(new_roster, tuple):
            old_roster = cast(tuple[object, ...], old_roster)
            new_roster = cast(tuple[object, ...], new_roster)
            if len(old_roster) == len(new_roster) == 11:
                _delta_fields(old_roster[:8], new_roster[:8], _DELTA_SNAPSHOT_FIELDS, "", differences)
                _delta_rows(old_roster[8], new_roster[8], _DELTA_MEMBER_FIELDS, "members", differences)
                _delta_rows(old_roster[9], new_roster[9], _DELTA_LOCAL_BASELINE_FIELDS, "local_baselines", differences)
                _delta_rows(
                    old_roster[10], new_roster[10], _DELTA_REMOTE_BASELINE_FIELDS, "remote_baselines", differences
                )
            elif old_roster != new_roster:
                differences.append("roster.shape")
        elif old_roster != new_roster:
            differences.append("roster.shape")
    fields = tuple(dict.fromkeys(differences))
    if current.signature != baseline.signature and not fields:
        fields = ("signature.shape",)
    reason_changed = any(field.endswith(".reason") for field in fields)
    continuity_changed = any(not field.endswith(".reason") for field in fields)
    continuity_changed = continuity_changed or (
        not current.snapshot.ready
        or current.snapshot.lifecycle_epoch != baseline.lifecycle_epoch
        or current.snapshot.map_id != baseline.map_id
    )
    classification = (
        "mixed" if reason_changed and continuity_changed else "reason_only" if reason_changed else "continuity"
    )
    header = (
        f"ready={int(not current.snapshot.ready)} "
        f"lifecycle={int(current.snapshot.lifecycle_epoch != baseline.lifecycle_epoch)} "
        f"map={int(current.snapshot.map_id != baseline.map_id)} "
        f"signature={int(current.signature != baseline.signature)} class={classification} fields="
    )
    # A return to Outpost after destination observations can share this branch.
    # Preserve those mandatory samples as well, using compact predicate codes.
    if len(_record("outpost_delta", header + (fields[0] if fields else "none") + " trunc=1")) + 1 > max_characters:
        code = "M" if reason_changed and continuity_changed else "R" if reason_changed else "C"
        header = (
            f"r={int(not current.snapshot.ready)} "
            f"l={int(current.snapshot.lifecycle_epoch != baseline.lifecycle_epoch)} "
            f"m={int(current.snapshot.map_id != baseline.map_id)} "
            f"s={int(current.signature != baseline.signature)} c={code} fields="
        )
    selected: list[str] = []
    for field in fields:
        candidate = header + ",".join((*selected, field)) + " trunc=1"
        if len(_record("outpost_delta", candidate)) + 1 > max_characters:
            break
        selected.append(field)
    return header + (",".join(selected) or "none") + f" trunc={int(len(selected) < len(fields))}"


_CAUSE_GATES = {
    "NONE": "NONE",
    "UNKNOWN": "U",
    "REFRESH_READ": "READ",
    "CONTROLLED_IDENTITY": "CP",
    "RUNTIME": "RT",
    "PUBLICATION": "PUB",
    "CAPTURE_TIME": "TIME",
    "RECOVERY": "REC",
    "OWNER_CLAIM": "CLAIM",
    "PUBLISHER": "PROV",
    "INSTANCE_EPOCH": "EPOCH",
    "OWNER_UUID": "UUID",
    "OWNER_TYPE": "TYPE",
    "OWNER_KEY": "KEY",
    "OWNER_SLOT": "SLOT",
    "OWNER_AGENT": "AGENT",
    "OWNER_LOGIN": "LOGIN",
    "OWNER_PARENT": "PARENT",
    "OWNER_HERO": "HERO",
    "OWNER_PROFESSION": "PROF",
    "OWNER_TICK": "TICK",
    "LEASE": "LEASE",
    "PUBLISHER_CONFLICT": "CONFLICT",
    "OWNER_PROOF": "OWNER",
    "OWNER_ENDPOINT": "ENDPOINT",
    "OWNER_ROLE": "ROLE",
    "HERO_PROOF": "HPROOF",
    "WITNESS_QUALIFICATION": "WQUAL",
    "WITNESS_REVISION": "WREV",
    "WITNESS_TIME": "WTIME",
    "WITNESS_EPOCH": "WEPOCH",
    "HERO_PROFESSION": "HPROF",
    "WITNESS_BUILD": "WBUILD",
    "CHILD_BAR": "BAR",
    "HERO_ROLE": "HROLE",
    "LOCAL_BAR": "LBAR",
    "CLOSING_READ": "READ",
    "FINAL_RUNTIME": "FINAL",
    "HERO_IDENTITY": "HID",
    "HERO_OWNER": "HOWNER",
    "HERO_ENDPOINT": "HEND",
    "CHILD_CLAIM": "CCLAIM",
    "CHILD_SEMANTICS": "CHILD",
    "WITNESS_MISSING": "WMISS",
    "WITNESS_DUPLICATE": "WDUP",
    "WITNESS_KIND": "WKIND",
    "WITNESS_PROFESSION": "HPROF",
    "WITNESS_BAR": "WBUILD",
    "ENDPOINT_CONTRADICTION": "ENDPOINT",
    "CHILD_CONTRADICTION": "CHILD",
    "ORIGINAL_UNSUPPORTED": "BUILD",
    "LOCAL_CONTINUITY": "LBAR",
    "OWNER_LIVING": "ENDPOINT",
    "RUNTIME_REJECTED": "RT",
    "READ_FAILED_CLOSING": "READ",
    "ENVIRONMENT_GATE": "ENV",
    "OUT_OF_SCOPE": "SCOPE",
    "PARTY_NOT_LOADED": "PARTY",
    "LOCAL_IDENTITY": "ID",
    "INCARNATION": "INC",
    "OWNER_EMAIL": "EMAIL",
    "OWNER_HWND": "WINDOW",
}
_CAUSE_CLOSING = {
    "NOT_EVALUATED": "N",
    "OK": "OK",
    "CLOSING_INCOHERENT": "I",
    "UNAVAILABLE": "U",
    "PUBLICATION_REJECTED": "P",
    "READ_FAILED_CLOSING": "R",
    "CONTROLLED_IDENTITY": "CP",
    "RUNTIME_REJECTED": "RT",
    "LOCAL_CONTINUITY": "LB",
}
_CAUSE_SCOPES = {
    "NONE": "NONE",
    "UNKNOWN": "U",
    "SHARED": "S",
    "LOCAL_OWNER": "LO",
    "REMOTE_OWNER": "RO",
    "LOCAL_HERO": "LH",
    **{f"{kind}{index}": f"{kind}{index}" for kind in ("LH", "RH") for index in range(1, 8)},
}
_CAUSE_OWNER_CODES = frozenset(
    "RECOVERY_EPOCH HWND UUID INCARNATION EPOCH COHORT_UUID OWNER_UUID OWNER_HWND OWNER_EMAIL "
    "OWNER_TYPE OWNER_KEY OWNER_SLOT OWNER_LOGIN OWNER_AGENT OWNER_PARENT OWNER_HERO OWNER_TICK LEASE "
    "OWNER_LIVING OWNER_LIVING_LOGIN OWNER_PROFESSION OWNER_ROSTER PUBLISHER_CONFLICT".split()
)


def _reject_outpost_change(baseline: _OutpostBaseline, current: _SnapshotEvidence) -> None:
    global _pending_outpost_delta, _pending_outpost_cause
    remaining_evidence = (
        _REQUIRED_EVIDENCE_CHARACTERS
        - _required_characters
        - _MAX_OUTPOST_CAUSE_CHARACTERS
        - sum(len(_record("destination_sample", details)) + 1 for details in _pending_destination_sample_details)
    )
    _pending_outpost_delta = _outpost_delta_details(
        baseline, current, min(_MAX_OUTPOST_DELTA_CHARACTERS, remaining_evidence)
    )
    _pending_outpost_cause = _outpost_cause_details(current)
    _finish("INCONCLUSIVE", "outpost_changed_before_loading")


def _outpost_cause_details(evidence: _SnapshotEvidence) -> str:
    """Serialize only authored codes from this immutable observation, never latest state."""
    try:
        production = evidence.production_evidence
        if production is None or production.decision_status != "EXACT" or production.decision is None:
            return (
                "a=AMBIGUOUS"
                if production is not None and production.decision_status == "AMBIGUOUS"
                else "a=UNAVAILABLE"
            )
        decision = production.decision
        if type(decision.sequence) is not int or type(decision.revision) is not int:
            return "a=UNAVAILABLE"
        if (
            production.snapshot is not evidence.snapshot
            or decision.revision != evidence.snapshot.revision
            or decision.sequence <= 0
        ):
            return "a=AMBIGUOUS"
        if any(
            type(values) is not tuple
            for values in (decision.paths, decision.baselines, decision.remote, decision.failure)
        ):
            return "a=UNAVAILABLE"
        if (
            len(decision.paths) != 5
            or len(decision.baselines) != 4
            or len(decision.remote) != 2
            or len(decision.failure) != 3
        ):
            return "a=UNAVAILABLE"
        counts = (*decision.paths, *decision.baselines, *decision.remote)
        if any(type(value) is not int or not 0 <= value <= 7 for value in counts):
            return "a=UNAVAILABLE"
        if any(value not in (0, 1) for value in decision.remote):
            return "a=UNAVAILABLE"
        gate, scope, pass_number = decision.failure
        if any(
            type(code) is not str or len(code) > 24
            for code in (gate, scope, decision.opening, decision.closing, decision.final)
        ):
            return "a=UNAVAILABLE"
        if type(pass_number) is not int or not 0 <= pass_number <= 3:
            return "a=UNAVAILABLE"
        opening = {
            "NOT_EVALUATED": "N",
            "ACCEPTED": "A",
            "PARTIAL": "X",
            "QUALIFICATION": "Q",
            "COHORT_MISSING": "C",
            "COHORT_AMBIGUOUS": "D",
            "PUBLICATION_REJECTED": "P",
            "EVALUATION_FAILED": "R",
        }.get(decision.opening)
        if opening is None:
            opening = "O" if decision.opening in _CAUSE_OWNER_CODES else "U"
        details = (
            f"a=EXACT s={_counter_text(decision.sequence)} r={_counter_text(decision.revision)} "
            f"p={'/'.join(str(value) for value in decision.paths)} o={opening} "
            f"c={_CAUSE_CLOSING.get(decision.closing, 'U')} "
            f"g={_CAUSE_GATES.get(gate, 'U')}/{_CAUSE_SCOPES.get(scope, 'U')}/{pass_number} "
            f"f={_CAUSE_CLOSING.get(decision.final, 'U')} "
            f"b={'/'.join(str(value) for value in decision.baselines)} "
            f"x={'/'.join(str(value) for value in decision.remote)}"
        )
        return (
            details if len(_record("outpost_cause", details)) + 1 <= _MAX_OUTPOST_CAUSE_CHARACTERS else "a=UNAVAILABLE"
        )
    except Exception:
        return "a=UNAVAILABLE"


def _outpost_witness_evidence(
    evidence: _SnapshotEvidence,
    context: CleansingContext,
) -> _OutpostWitnessEvidence:
    player = evidence.remote_player
    hero = evidence.remote_hero
    baseline = evidence.remote_player_baseline
    if player is None or hero is None:
        return _OutpostWitnessEvidence("not_run", None, False, "inputs_missing")
    if baseline is None or evidence.snapshot.map_id is None:
        return _OutpostWitnessEvidence("not_run", None, False, "baseline_missing")

    reader_called = False
    try:
        shared_memory = getattr(GLOBAL_CACHE, "ShMem", None)
        reader = getattr(shared_memory, "GetNativeAccountSnapshotV3", None)
        if not callable(reader):
            return _OutpostWitnessEvidence("not_run", None, False, "reader_missing")
        read_snapshot = cast(Callable[[], object], reader)
        reader_called = True
        result = read_snapshot()
        status = getattr(getattr(result, "status", None), "value", None)
        raw_native_snapshot = getattr(result, "snapshot", None)
        if status != "success" or raw_native_snapshot is None:
            return _OutpostWitnessEvidence("unavailable", None, False, "snapshot_unavailable")
        native_snapshot = cast(_NativeSnapshotView, raw_native_snapshot)
        matching_cohorts: list[_NativeCohortView] = []
        for cohort in native_snapshot.cohorts:
            owner = cohort.owner.GetAccountData()
            if (
                cohort.instance_type == 0
                and owner.AgentData.LoginNumber == player.identity.owner_id
                and owner.AgentData.AgentID == player.identity.agent_id
                and owner.AgentData.Map.MapID == evidence.snapshot.map_id
                and owner.AgentPartyData.PartyID == baseline.party_id
                and _PublisherIdentity(
                    recovery_epoch=native_snapshot.recovery_epoch,
                    incarnation=bytes(cohort.incarnation),
                    character_uuid=tuple(int(value) for value in cohort.character_uuid),
                    account_email=owner.AccountEmail.strip().casefold(),
                    hwnd=int(owner.Key.HWND),
                )
                == _publisher_identity(baseline.publisher)
            ):
                matching_cohorts.append(cohort)
        if len(matching_cohorts) != 1:
            status = "ambiguous" if len(matching_cohorts) > 1 else "unavailable"
            reason_code = "cohort_ambiguous" if status == "ambiguous" else "cohort_missing"
            return _OutpostWitnessEvidence(status, None, False, reason_code)
        witnesses: list[_NativeWitnessView] = []
        for witness in matching_cohorts[0].witnesses:
            witness_kind = getattr(witness.kind, "value", witness.kind)
            if isinstance(witness_kind, int) and witness_kind == _OUTPOST_WITNESS_KIND:
                if witness.hero_id == hero.identity.member_id:
                    witnesses.append(witness)
        if len(witnesses) == 1:
            witness = witnesses[0]
            build_complete = (
                witness.primary > 0 and len(witness.skills) == 8 and all(skill_id > 0 for skill_id in witness.skills)
            )
            raw_skill_ids = getattr(context, "_role_skill_ids", None)
            if not build_complete or raw_skill_ids is None:
                reason_code = "none" if build_complete else "build_incomplete"
                return _OutpostWitnessEvidence("available", None, build_complete, reason_code)
            recognition = recognize_role(
                RoleEvidence(
                    identity=hero.identity,
                    source=EvidenceSource.REMOTE_HERO,
                    primary_profession=witness.primary,
                    skill_ids=witness.skills,
                    ownership_proven=True,
                ),
                cast(CleansingSkillIDs, raw_skill_ids),
            )
            role = recognition.candidate_role
            return _OutpostWitnessEvidence(
                "available",
                role if role is not CleansingRole.UNKNOWN else None,
                build_complete,
                "none" if role is not CleansingRole.UNKNOWN else "role_unrecognized",
            )
        status = "ambiguous" if len(witnesses) > 1 else "unavailable"
        reason_code = "witness_ambiguous" if status == "ambiguous" else "witness_missing"
        return _OutpostWitnessEvidence(status, None, False, reason_code)
    except Exception:
        if reader_called:
            return _OutpostWitnessEvidence("unavailable", None, False, "reader_error")
        return _OutpostWitnessEvidence("not_run", None, False, "reader_missing")


def _snapshot_wait_reason(snapshot: CleansingContextSnapshot) -> str:
    reason = snapshot.reason.casefold()
    if reason == "context has not been refreshed":
        return "refresh_pending"
    if reason.startswith("environment upkeeper skipped cache refresh"):
        return "refresh_gated"
    if reason == "local player or party context is not loaded":
        return "context_unavailable"
    if reason == "map is loading or not ready":
        return "map_not_ready"
    if reason == "pvp context is out of scope":
        return "pvp_out_of_scope"
    if reason.startswith("runtime evidence read failed"):
        return "evidence_read_failed"
    return "snapshot_not_ready"


def _outpost_baseline_wait_reasons(evidence: _SnapshotEvidence) -> tuple[str, ...]:
    player = evidence.remote_player
    hero = evidence.remote_hero
    baseline = evidence.remote_player_baseline
    reasons: list[str] = []
    if not evidence.complete_eight:
        reasons.append("the complete eight-member roster is not proven")
    if not evidence.local_roles_match:
        reasons.append("the required local player and hero roles are not proven")
    if evidence.local_baseline_count != 6:
        reasons.append("six local outpost role baselines are not retained")

    if len(evidence.remote_player_roles) != 1 or player is None:
        reasons.append("exactly one remote player is not proven")
    elif player.role not in _EXPECTED_LOCAL_HEROES_BY_REMOTE_PLAYER:
        reasons.append("the remote player is not proven as BiP or Energy Surge")
    elif evidence.remote_player_roles != Counter({player.role: 1}) or not _local_role_distribution_matches(
        evidence, player.role
    ):
        reasons.append("the local heroes and remote player do not match a supported Composition A distribution")

    remote_heroes = tuple(
        member for member in evidence.snapshot.members if member.evidence_source is EvidenceSource.REMOTE_HERO
    )
    if (
        player is not None
        and len(remote_heroes) == 1
        and remote_heroes[0].identity.owner_id != player.identity.owner_id
    ):
        reasons.append("the remote hero owner does not match the remote player")
    elif len(evidence.remote_hero_roles) != 1 or hero is None:
        reasons.append("exactly one remote hero is not proven")
    elif player is not None and hero.identity.owner_id != player.identity.owner_id:
        reasons.append("the remote hero owner does not match the remote player")

    if baseline is None:
        reasons.append("the remote publisher baseline is not retained")
    if evidence.party_id is None or evidence.party_id <= 0:
        reasons.append("the remote party identity is unavailable")
    if evidence.snapshot.map_id is None:
        reasons.append("the outpost map identity is unavailable")
    if evidence.production_evidence is None:
        reasons.append("the production snapshot evidence is unavailable")
    if player is not None and player.remote_provenance_generation is None:
        reasons.append("the remote publisher generation is not proven")
    if not evidence.stage4_fence:
        reasons.append("the composition safety fence is not satisfied")
    return tuple(reasons)


def _outpost_is_baseline(evidence: _SnapshotEvidence) -> bool:
    return not _outpost_baseline_wait_reasons(evidence)


def _local_role_distribution_matches(evidence: _SnapshotEvidence, remote_player_role: CleansingRole) -> bool:
    expected_heroes = _EXPECTED_LOCAL_HEROES_BY_REMOTE_PLAYER.get(remote_player_role)
    return (
        expected_heroes is not None
        and evidence.local_player_roles == _EXPECTED_LOCAL_PLAYER
        and evidence.local_hero_roles == expected_heroes
    )


def _new_outpost_baseline(
    evidence: _SnapshotEvidence,
    context: CleansingContext,
    witness_status: _OutpostWitnessEvidence,
) -> _OutpostBaseline | None:
    player = evidence.remote_player
    hero = evidence.remote_hero
    baseline = evidence.remote_player_baseline
    if (
        player is None
        or hero is None
        or baseline is None
        or evidence.snapshot.map_id is None
        or player.remote_provenance_generation is None
        or evidence.production_evidence is None
    ):
        return None
    try:
        attempt_id = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.begin(
            context,
            evidence.production_evidence,
            int(_started_at * 1_000_000_000) if _started_at is not None else None,
        )
    except Exception as error:
        raise _DiagnosticUnavailable from error
    if attempt_id is None:
        return None
    return _OutpostBaseline(
        attempt_id=attempt_id,
        revision=evidence.snapshot.revision,
        lifecycle_epoch=evidence.snapshot.lifecycle_epoch,
        map_id=evidence.snapshot.map_id,
        signature=evidence.signature,
        roster_signature=evidence.production_evidence.roster_signature,
        local_character_identity=evidence.snapshot.character_identity,
        local_roster_keys=evidence.local_roster_keys,
        party_id=evidence.party_id if evidence.party_id is not None else 0,
        remote_hero_key=hero.identity.stable_key,
        remote_player_role=player.role,
        publisher=_publisher_identity(baseline.publisher),
        publisher_generation=player.remote_provenance_generation,
        witness_status=witness_status.status,
        original_witness_role=witness_status.role,
        original_witness_build_complete=witness_status.build_complete,
    )


def _report_zone_readiness(context: CleansingContext | None, refusal: str = "attempt_not_armed") -> bool:
    global _readiness_reported
    if _readiness_reported:
        return True
    baseline, source = _outpost_baseline, _owner_source
    reason = refusal
    if context is not None and baseline is not None and source is not None:
        if (
            _terminal_outcome is not None
            or _finished
            or vars(GLOBAL_CACHE).get("CleansingContext") is not context
            or _attempt_id != baseline.attempt_id
        ):
            reason = "attempt_binding_changed"
        else:
            reason = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.readiness_reason(baseline.attempt_id, context, source)
            if reason == "ready":
                if baseline.witness_status != "available":
                    reason = "original_witness_unavailable"
                elif not baseline.original_witness_build_complete:
                    reason = "original_witness_build_incomplete"
                elif baseline.original_witness_role is not CleansingRole.ENERGY_SURGE:
                    reason = "original_witness_not_energy_surge"
    # Delivery is attempted once. A logger failure cannot turn a delayed detail
    # or a later production Refresh into a new readiness authorization.
    _readiness_reported = True
    if reason == "ready" and baseline is not None:
        return _emit("ready_to_zone", "attempt=" + _counter_text(baseline.attempt_id), reserved=True)
    if not reason.isascii() or not reason.isidentifier() or len(reason) > _MAX_REASON_CHARACTERS:
        reason = "attempt_not_ready"
    return _emit("no_go", "reason=" + reason, reserved=True)


def _valid_initial_forwarding_event(event: ProbeForwardingEvent, baseline: _OutpostBaseline) -> bool:
    owner, source = event.owner, _owner_source
    if owner is None or source is None:
        return False
    boundary = owner.boundary
    observation = boundary.observation
    loading = boundary.loading
    return (
        event.attempt_id == baseline.attempt_id
        and event.forwarded_loading
        and observation is not None
        and loading is not None
        and observation.loading is loading
        and loading.loading
        and all(loading.contexts)
        and loading.raw_instance_type == 2
        and boundary.transition_id == source.boundary.transition_id
        and boundary.source_generation == source.boundary.source_generation
        and boundary.phase is not TransitionPhase.RETIRED
        and not boundary.retired_members
        and boundary.deadline is not None
        and loading.observed_at < boundary.deadline
        and source.sequence < owner.sequence
        and source.observed_at <= loading.observed_at <= owner.observed_at
        and source.snapshot.lifecycle_epoch == baseline.lifecycle_epoch
        and source.snapshot.map_id == baseline.map_id
    )


def _valid_repeated_forwarding_event(event: ProbeForwardingEvent, initial: ProbeForwardingEvent) -> bool:
    owner, first = event.owner, initial.owner
    return (
        owner is not None
        and first is not None
        and event.attempt_id == initial.attempt_id
        and owner.sequence > first.sequence
        and owner.boundary.transition_id == first.boundary.transition_id
        and owner.boundary.source_generation == first.boundary.source_generation
        and owner.boundary.phase is not TransitionPhase.RETIRED
        and not owner.boundary.retired_members
        and owner.boundary.loading is first.boundary.loading
    )


def _accept_loading_evidence(now_ns: int) -> bool:
    global _loading_event
    baseline, candidate = _outpost_baseline, _candidate_loading_event
    if baseline is None or candidate is None or now_ns < candidate.observed_at_ns:
        return False
    if _started_at is None or now_ns >= int((_started_at + _MAX_RUNTIME_SECONDS) * 1_000_000_000):
        return False
    if not _valid_initial_forwarding_event(candidate, baseline):
        return False
    _loading_event = candidate
    return True


def _loading_line(event: ProbeForwardingEvent) -> str:
    if event.pre_forward_refresh_sequence is None:
        raise _CounterDisplayOverflow
    return _loading_details(
        *(
            _counter_text(value)
            for value in (
                event.sequence,
                event.pre_forward_refresh_sequence,
                event.before_revision,
                event.after_revision,
                event.before_lifecycle_epoch,
                event.after_lifecycle_epoch,
            )
        )
    )


def _destination_continuity(evidence: _SnapshotEvidence, baseline: _OutpostBaseline) -> tuple[bool, bool, bool]:
    player = evidence.remote_player
    hero = evidence.remote_hero
    current = evidence.remote_player_baseline
    if player is None or hero is None or current is None:
        return False, False, False
    publisher_continuity = (
        _publisher_identity(current.publisher) == baseline.publisher
        and player.remote_provenance_generation == baseline.publisher_generation
        and current.party_id == baseline.party_id
        and current.destination_map_id == evidence.snapshot.map_id
        and current.destination_lifecycle_epoch == evidence.snapshot.lifecycle_epoch
        and current.destination_instance_epoch is not None
        and current.destination_instance_epoch > 0
    )
    hero_continuity = (
        hero.identity.kind is MemberKind.HERO
        and hero.identity.member_id == baseline.remote_hero_key[2]
        and hero.identity.owner_id == player.identity.owner_id
        and hero.remote_provenance_generation == baseline.publisher_generation
    )
    roster_continuity = (
        evidence.local_roster_keys == baseline.local_roster_keys
        and evidence.snapshot.character_identity == baseline.local_character_identity
        and evidence.party_id == baseline.party_id
    )
    return publisher_continuity, hero_continuity, roster_continuity


def _classify_destination(evidence: _SnapshotEvidence, baseline: _OutpostBaseline) -> tuple[str, str]:
    if not evidence.complete_eight:
        return "INCONCLUSIVE", "destination_roster_incomplete"
    if (
        sum(evidence.local_player_roles.values()) != 1
        or sum(evidence.local_hero_roles.values()) != 5
        or sum(evidence.remote_player_roles.values()) != 1
        or sum(evidence.remote_hero_roles.values()) != 1
    ):
        return "INCONCLUSIVE", "destination_sources_incomplete"
    player, hero = evidence.remote_player, evidence.remote_hero
    if player is not None and player.candidate_role not in (CleansingRole.UNKNOWN, baseline.remote_player_role):
        return "FAILURE", "remote_player_role_contradicts_outpost_baseline"
    if hero is not None and hero.candidate_role not in (CleansingRole.UNKNOWN, CleansingRole.ENERGY_SURGE):
        return "FAILURE", "supported_hero_roles_contradict"
    if any(
        member.role is CleansingRole.UNKNOWN
        for member in evidence.snapshot.members
        if member.evidence_source in (EvidenceSource.LOCAL_PLAYER, EvidenceSource.LOCAL_HERO)
    ):
        return "INCONCLUSIVE", "local_stage2_baseline_unavailable"
    if not evidence.stage4_fence:
        return "FAILURE", "stage4_composition_fence"
    if not evidence.local_roles_match:
        return "FAILURE", "local_role_contract"
    if not _local_role_distribution_matches(evidence, baseline.remote_player_role):
        return "FAILURE", "composition_a_source_distribution"
    if evidence.local_baseline_count != 6:
        return "INCONCLUSIVE", "local_stage2_baseline_unavailable"

    publisher_continuity, hero_continuity, roster_continuity = _destination_continuity(evidence, baseline)
    if not roster_continuity:
        return "INCONCLUSIVE", "party_or_local_roster_continuity_unproven"
    if not publisher_continuity:
        return "INCONCLUSIVE", "publisher_continuity_unproven"
    if not hero_continuity:
        return "INCONCLUSIVE", "remote_hero_continuity_unproven"

    player = evidence.remote_player
    hero = evidence.remote_hero
    if player is None or hero is None:
        return "INCONCLUSIVE", "remote_role_evidence_unavailable"

    if player.candidate_role not in (CleansingRole.UNKNOWN, baseline.remote_player_role):
        return "FAILURE", "remote_player_role_contradicts_outpost_baseline"
    if player.role is not CleansingRole.UNKNOWN and player.role is not baseline.remote_player_role:
        return "FAILURE", "remote_player_role_contradicts_outpost_baseline"

    if player.role not in (CleansingRole.UNKNOWN, baseline.remote_player_role):
        return "FAILURE", "remote_role_contract"
    if hero.role not in (CleansingRole.UNKNOWN, CleansingRole.ENERGY_SURGE):
        return "FAILURE", "remote_role_contract"
    if baseline.witness_status != "available":
        return "INCONCLUSIVE", "original_witness_unavailable"
    if not baseline.original_witness_build_complete:
        return "INCONCLUSIVE", "original_witness_build_incomplete"

    original_role = baseline.original_witness_role
    if original_role is not None and hero.candidate_role not in (CleansingRole.UNKNOWN, original_role):
        return "FAILURE", "supported_hero_roles_contradict"
    if hero.candidate_role not in (CleansingRole.UNKNOWN, CleansingRole.ENERGY_SURGE):
        return "FAILURE", "remote_role_contract"
    if original_role is None:
        if hero.role is CleansingRole.UNKNOWN:
            return "SAFE_UNKNOWN", "original_witness_role_unproven"
        return "INCONCLUSIVE", "original_witness_role_unproven"
    if hero.role is CleansingRole.UNKNOWN:
        return "SAFE_UNKNOWN", "current_hero_role_unproven"
    if hero.role is not original_role or hero.role is not hero.candidate_role:
        return "FAILURE", "supported_hero_roles_contradict"
    if player.role is CleansingRole.UNKNOWN:
        return "SAFE_UNKNOWN", "remote_player_role_unproven"
    if (
        evidence.remote_player_roles != Counter({baseline.remote_player_role: 1})
        or evidence.remote_hero_roles != _EXPECTED_REMOTE_HEROES
        or original_role is not CleansingRole.ENERGY_SURGE
    ):
        return "FAILURE", "remote_role_contract"
    return "FULL_SUCCESS", "three_stable_destination_samples"


def _reset_destination_samples(*, preserve_output: bool = False) -> None:
    global _destination_signature, _destination_last_revision, _destination_last_sample_at
    global _destination_last_refresh_sequence, _destination_samples, _pending_destination_sample_details
    global _accepted_destination_events, _latest_destination_owner
    _accepted_destination_events = ()
    _latest_destination_owner = None
    _destination_signature = None
    _destination_last_revision = None
    _destination_last_sample_at = None
    _destination_last_refresh_sequence = None
    _destination_samples = 0
    if not preserve_output:
        _pending_destination_sample_details = []


def _collect_destination_sample(evidence: _SnapshotEvidence, event: ProbeRefreshEvent) -> bool:
    global _destination_signature, _destination_last_revision, _destination_last_sample_at, _destination_samples
    global _destination_last_refresh_sequence, _pending_destination_sample_details, _sample_output_error
    revision = evidence.snapshot.revision
    if _destination_signature is None:
        _destination_signature = evidence.signature
        _destination_last_revision = revision
        _destination_last_sample_at = event.observed_at_ns
        _destination_last_refresh_sequence = event.sequence
        _destination_samples = 1
        return True

    if evidence.signature != _destination_signature or (
        _destination_last_revision is not None and revision < _destination_last_revision
    ):
        _destination_signature = evidence.signature
        _destination_last_revision = revision
        _destination_last_sample_at = event.observed_at_ns
        _destination_last_refresh_sequence = event.sequence
        _destination_samples = 1
        _pending_destination_sample_details = []
        return True

    if _destination_samples >= _REQUIRED_DESTINATION_SAMPLES:
        return False

    if (
        _destination_last_sample_at is None
        or _destination_last_refresh_sequence is None
        or event.sequence <= _destination_last_refresh_sequence
        or event.observed_at_ns - _destination_last_sample_at < _SAMPLE_INTERVAL_NS
    ):
        return False
    _destination_last_revision = revision
    _destination_last_sample_at = event.observed_at_ns
    _destination_last_refresh_sequence = event.sequence
    _destination_samples += 1
    return True


def _report_outpost(
    snapshot: CleansingContextSnapshot,
    context: CleansingContext,
    evidence: _SnapshotEvidence | None,
    witness_status: _OutpostWitnessEvidence,
    baseline_created: bool,
    waiting_reasons: tuple[str, ...],
) -> bool:
    global _outpost_detail_signature, _outpost_detail_report_count, _outpost_detail_last_emit
    global _outpost_detail_last_ready
    global _outpost_baseline_reported, _outpost_detail_budget_exhausted

    if baseline_created and not _outpost_baseline_reported:
        if not _emit("outpost", f"created roster={len(snapshot.members)}/8", reserved=True):
            return False
        _outpost_baseline_reported = True

    production_evidence = evidence.production_evidence if evidence is not None else None
    local_baselines = _local_baseline_keys(context, production_evidence)
    remote_baselines = _remote_player_baselines(context, production_evidence)
    local_player_records = tuple(
        member for member in snapshot.members if member.evidence_source is EvidenceSource.LOCAL_PLAYER
    )
    local_hero_records = tuple(
        member for member in snapshot.members if member.evidence_source is EvidenceSource.LOCAL_HERO
    )
    rows: list[str] = []
    local_player = local_player_records[0] if len(local_player_records) == 1 else None
    rows.append(_local_detail_row("LP", local_player, local_baselines))
    for hero_slot in range(5):
        member = local_hero_records[hero_slot] if hero_slot < len(local_hero_records) else None
        rows.append(_local_detail_row(f"H{hero_slot + 1}", member, local_baselines))

    remote_players = tuple(
        member for member in snapshot.members if member.evidence_source is EvidenceSource.REMOTE_PLAYER
    )
    remote_heroes = tuple(member for member in snapshot.members if member.evidence_source is EvidenceSource.REMOTE_HERO)
    remote_player = remote_players[0] if len(remote_players) == 1 else None
    remote_hero = remote_heroes[0] if len(remote_heroes) == 1 else None
    remote_player_baseline = (
        remote_baselines.get(remote_player.identity.stable_key) if remote_player is not None else None
    )
    player_role = _role_code(remote_player.role) if remote_player is not None else "UNKNOWN"
    player_published = int(remote_player is not None and remote_player.remote_provenance_generation is not None)
    player_baseline = int(remote_player_baseline is not None)
    player_reason = (
        _safe_member_reason(remote_player, EvidenceSource.REMOTE_PLAYER) if remote_player is not None else "record"
    )
    hero_role = _role_code(remote_hero.role) if remote_hero is not None else "UNKNOWN"
    hero_reason = _safe_member_reason(remote_hero, EvidenceSource.REMOTE_HERO) if remote_hero is not None else "record"
    player_reason_text = f" r={player_reason}" if player_role == "UNKNOWN" else ""
    hero_reason_text = f" r={hero_reason}" if hero_role == "UNKNOWN" else ""

    role_counts = dict(snapshot.composition.role_counts)
    unknown_count = role_counts.get(CleansingRole.UNKNOWN, 0)
    stage4_status = _composition_status_code(snapshot.composition.status)
    exact_fence = (
        evidence.stage4_fence
        if evidence is not None
        else stage4_status == "FALLBACK"
        and unknown_count == 2
        and snapshot.composition.member_count == 8
        and snapshot.composition.declared_party_size == 8
    )
    witness_text = _witness_detail(witness_status)
    wait_codes = tuple(_outpost_wait_code(reason) for reason in waiting_reasons)
    if not snapshot.ready:
        wait_codes = (*wait_codes, _snapshot_wait_reason(snapshot))
    elif not snapshot.members:
        wait_codes = (*wait_codes, "members")
    wait_priority = (
        "local_baselines",
        "local_roles",
        "remote_role",
        "remote_player",
        "remote_hero",
        "distribution",
        "stage4_fence",
    )
    unique_wait_codes = tuple(dict.fromkeys(wait_codes))
    prioritized_wait_codes = tuple(code for code in wait_priority if code in unique_wait_codes)
    prioritized_wait_codes = (
        *prioritized_wait_codes,
        *(code for code in unique_wait_codes if code not in wait_priority),
    )
    wait_text = ",".join(prioritized_wait_codes[:3]) or "none"
    if not snapshot.ready or not snapshot.members:
        details = f"wait={_snapshot_wait_reason(snapshot) if not snapshot.ready else 'members'}"
        detail_event = "outpost"
    else:
        detail_status = "waiting roster={}/8 ".format(len(snapshot.members)) if not baseline_created else ""
        details = (
            f"{detail_status}"
            f"L={','.join(rows)} "
            f"P={player_role} pub={player_published} base={player_baseline}{player_reason_text} "
            f"H={hero_role}{hero_reason_text} "
            f"stage4={stage4_status} u={unknown_count} fence={int(exact_fence)} "
            f"witness={witness_text}"
            f"{f' wait={wait_text}' if wait_text != 'none' else ''}"
        )
        detail_event = "outpost_detail"
    if baseline_created:
        details += " source=baseline"
    signature = details
    now = monotonic()
    if signature == _outpost_detail_signature:
        return True
    if _outpost_detail_report_count >= _MAX_OUTPOST_DETAIL_REPORTS:
        return True
    if (
        _outpost_detail_last_emit is not None
        and now - _outpost_detail_last_emit < _OUTPOST_DETAIL_INTERVAL_SECONDS
        and not baseline_created
        and not (snapshot.ready and not _outpost_detail_last_ready)
        and not _pending_outpost_details
        and not (_attempt_id is None and _started_at is not None and now - _started_at >= _MAX_PREFLIGHT_SECONDS)
    ):
        return True
    emitted = _emit(detail_event, details)
    if not emitted:
        compact_details = _compact_outpost_details(
            rows,
            wait_text,
            stage4_status,
            unknown_count,
            exact_fence,
            witness_text,
            player_role,
            player_reason,
            hero_role,
            hero_reason,
        )
        if baseline_created:
            compact_details += " source=baseline"
        _outpost_detail_budget_exhausted = True
        alternatives = (details, compact_details) if snapshot.ready and snapshot.members else (details,)
        if wait_text != "none":
            alternatives += (f"wait={wait_text.split(',', 1)[0]}",)
        if alternatives in _pending_outpost_details:
            _pending_outpost_details.remove(alternatives)
        if baseline_created:
            _pending_outpost_details.append(alternatives)
        else:
            _pending_outpost_details.insert(0, alternatives)
        del _pending_outpost_details[_MAX_OUTPOST_DETAIL_REPORTS - _outpost_detail_report_count :]
        _outpost_detail_signature = signature
        _outpost_detail_last_emit = now
        _outpost_detail_last_ready = snapshot.ready
        return True
    _outpost_detail_signature = signature
    _outpost_detail_report_count += 1
    _outpost_detail_last_emit = now
    _outpost_detail_last_ready = snapshot.ready
    return True


def _compact_outpost_details(
    rows: list[str],
    wait_text: str,
    stage4_status: str,
    unknown_count: int,
    exact_fence: bool,
    witness_text: str,
    player_role: str,
    player_reason: str,
    hero_role: str,
    hero_reason: str,
) -> str:
    compact_rows = [row.replace("/base_missing", "") for row in rows]
    details = f"L={','.join(compact_rows)}"
    missing_baseline = any("/0" in row and "UNKNOWN" not in row for row in compact_rows)
    if missing_baseline:
        details += " why=base_missing"
    if stage4_status != "UNKNOWN":
        details += f" stage4={stage4_status} u={unknown_count} fence={int(exact_fence)}"
    details += f" witness={witness_text}"
    if player_role == "UNKNOWN":
        details += f" player=UNKNOWN r={player_reason}"
    if hero_role == "UNKNOWN":
        details += f" hero=UNKNOWN r={hero_reason}"
    if wait_text != "none" and not missing_baseline:
        details += f" wait={wait_text}"
    return details


def _role_code(role: CleansingRole) -> str:
    return {
        CleansingRole.UNKNOWN: "UNKNOWN",
        CleansingRole.ENERGY_SURGE: "ES",
        CleansingRole.PANIC: "Panic",
        CleansingRole.INEPTITUDE: "IN",
        CleansingRole.HEROIC_REFRAIN: "HR",
        CleansingRole.BIP: "BiP",
        CleansingRole.SOUL_TWISTING: "ST",
        CleansingRole.HEALING_BURST: "HB",
        CleansingRole.TAO: "TAO",
    }[role]


def _safe_member_reason(member: MemberRecord, source: EvidenceSource) -> str:
    reason = member.reason.casefold()
    if source is EvidenceSource.REMOTE_HERO and "role does not agree" in reason and "witness" in reason:
        return "witness_mismatch"
    if member.role is not CleansingRole.UNKNOWN:
        return "ok"
    if "local hero identity is ambiguous" in reason or "roster identity" in reason:
        return "identity"
    if "skillbar index does not match" in reason:
        return "index"
    if "skillbar ownership is ambiguous" in reason or "ownership is ambiguous" in reason:
        return "ownership"
    if "evidence read failed" in reason:
        return "read"
    if "skillbar evidence is incomplete" in reason:
        return "bar_incomplete"
    if "primary profession is unavailable" in reason or "professions do not agree" in reason:
        return "profession"
    if "multiple supported elite anchors" in reason:
        return "anchor_ambiguous"
    if "supported role anchor conflicts" in reason:
        return "profession_conflict"
    if "no supported role anchor" in reason:
        return "no_anchor"
    if "weapon-attack evidence is unavailable" in reason:
        return "weapon_read"
    if "weapon-attack" in reason or "together as one" in reason:
        return "weapon"
    if "skillbar evidence read failed" in reason:
        return "bar_read"
    if source is EvidenceSource.REMOTE_PLAYER:
        if "disconnected" in reason:
            return "disconnected"
        if "endpoint" in reason or "living-agent" in reason or "livingagent" in reason:
            return "endpoint"
        if "publication owner claim" in reason:
            return "owner_claim"
        if "publisher identity conflicts" in reason:
            return "publisher"
        if "account identity" in reason or "character name" in reason or "owner identity" in reason:
            return "owner"
        if "publication" in reason:
            return "publication"
        if "opening and closing" in reason:
            return "coherence"
        if "login identity" in reason:
            return "identity"
    elif source is EvidenceSource.REMOTE_HERO:
        if "owner identity" in reason or "owner is not proven" in reason:
            return "owner"
        if "child claim" in reason:
            return "child_claim"
        if "child does not match" in reason:
            return "child_mismatch"
        if "witness" in reason or "professions" in reason:
            return "witness"
        if "endpoint" in reason or "livingagent" in reason:
            return "endpoint"
    if "ready-outpost baseline" in reason or "no matching ready-outpost baseline" in reason:
        return "base_missing"
    return "unproven"


def _local_detail_row(
    label: str,
    member: MemberRecord | None,
    local_baselines: set[tuple[MemberKind, int, int]],
) -> str:
    if member is None:
        return f"{label}:UNKNOWN/0"
    has_baseline = member.identity.stable_key in local_baselines
    role = _role_code(member.role)
    reason = _safe_member_reason(member, member.evidence_source)
    if member.role is not CleansingRole.UNKNOWN and not has_baseline:
        reason = "base_missing"
    elif member.role is CleansingRole.UNKNOWN and has_baseline and reason == "unproven":
        reason = "baseline_role"
    if member.role is not CleansingRole.UNKNOWN and has_baseline:
        return f"{label}:{role}/1"
    return f"{label}:{role}/{int(has_baseline)}/{reason}"


def _composition_status_code(status: CompositionStatus) -> str:
    if status is CompositionStatus.FALLBACK:
        return "FALLBACK"
    if status is CompositionStatus.ACTIVE:
        return "ACTIVE"
    return "UNKNOWN"


def _sample_role_code(role: CleansingRole) -> str:
    return "UNK" if role is CleansingRole.UNKNOWN else _role_code(role)


def _witness_detail(witness: _OutpostWitnessEvidence) -> str:
    if witness.status == "not_run":
        return "not_run"
    if witness.status == "available" and witness.build_complete:
        role = _role_code(witness.role) if witness.role is not None else "UNKNOWN"
        return f"proven/{role}"
    safe_reasons = {
        "snapshot_unavailable": "snapshot",
        "cohort_missing": "cohort",
        "cohort_ambiguous": "ambiguous",
        "build_incomplete": "build",
        "role_unrecognized": "role",
        "witness_missing": "witness",
        "witness_ambiguous": "ambiguous",
        "reader_error": "reader_error",
        "inputs_missing": "inputs",
        "baseline_missing": "baseline",
        "reader_missing": "reader",
    }
    reason = safe_reasons.get(witness.reason_code, "unavailable")
    return f"unavailable/{reason}"


def _outpost_wait_code(reason: str) -> str:
    normalized = reason.casefold()
    if "complete eight-member roster" in normalized:
        return "roster"
    if "required local player and hero roles" in normalized:
        return "local_roles"
    if "six local outpost role baselines" in normalized:
        return "local_baselines"
    if "exactly one remote player" in normalized:
        return "remote_player"
    if "remote player is not proven" in normalized:
        return "remote_role"
    if "supported composition a distribution" in normalized:
        return "distribution"
    if "remote hero owner" in normalized:
        return "hero_owner"
    if "exactly one remote hero" in normalized:
        return "remote_hero"
    if "remote publisher baseline" in normalized:
        return "publisher_baseline"
    if "party identity" in normalized:
        return "party"
    if "map identity" in normalized:
        return "map"
    if "production snapshot evidence" in normalized:
        return "production"
    if "publisher generation" in normalized:
        return "generation"
    if "composition safety fence" in normalized:
        return "stage4_fence"
    if "recorder did not open" in normalized:
        return "recorder"
    if "members_missing" in normalized or "no member evidence" in normalized:
        return "members"
    return "gate"


def _report_waiting_outpost(reason: str, stage: int) -> bool:
    global _outpost_report_stage, _outpost_detail_budget_exhausted, _outpost_detail_signature
    signature = f"wait={reason}"
    if signature != _outpost_detail_signature:
        if (signature,) in _pending_outpost_details:
            _pending_outpost_details.remove((signature,))
        _pending_outpost_details.insert(0, (signature,))
        del _pending_outpost_details[_MAX_OUTPOST_DETAIL_REPORTS - _outpost_detail_report_count :]
        _outpost_detail_signature = signature
    if stage <= _outpost_report_stage:
        return True
    if _outpost_detail_budget_exhausted:
        return True
    if not _emit("outpost_wait", f"reason={reason}"):
        _outpost_detail_budget_exhausted = True
        return True
    if _pending_outpost_details and _pending_outpost_details[0] == (signature,):
        del _pending_outpost_details[0]
    _outpost_report_stage = stage
    return True


def on_enable() -> None:
    """Start a clean observer session when WidgetManager enables this widget."""
    global _started_at, _last_poll_at, _lines, _characters, _optional_characters, _required_characters, _finished
    global _outpost_report_stage, _outpost_baseline, _attempt_id
    global _outpost_detail_signature, _outpost_detail_report_count, _outpost_detail_last_emit
    global _outpost_detail_last_ready
    global _outpost_baseline_reported, _outpost_detail_budget_exhausted
    global _outpost_unready_since
    global _last_forwarding_sequence, _last_refresh_sequence
    global _candidate_loading_event, _loading_event
    global _optional_lines, _required_lines
    global _pending_outpost_details, _terminal_details
    global _pending_outpost_delta, _pending_outpost_cause
    global _terminal_outcome, _next_finalization_retry_at
    global _deferred_outpost_refresh
    global _owner_source, _last_owner_sequence, _owner_watermark, _admission_event
    global _sample_output_error
    global _final_verify_diagnostic_emitted
    global _readiness_reported
    global _readiness_characters

    setattr(_cleansing_context_module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", True)

    if _terminal_outcome is not None and not _finished:
        _retry_finalization()
        return
    if not _finished and (_started_at is not None or _attempt_id is not None):
        _finish("INCONCLUSIVE", "observer_restarted")
        if not _finished:
            return
    elif _attempt_id is not None:
        try:
            STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.end(_attempt_id)
        except Exception:
            pass

    _started_at = monotonic()
    _owner_source = None
    _last_owner_sequence = 0
    _owner_watermark = 0
    _admission_event = None
    _last_poll_at = 0.0
    _lines = 0
    _characters = 0
    _optional_characters = 0
    _required_characters = 0
    _optional_lines = 0
    _required_lines = 0
    _pending_outpost_details = []
    _pending_outpost_delta = None
    _pending_outpost_cause = None
    _deferred_outpost_refresh = None
    _terminal_details = None
    _terminal_outcome = None
    _next_finalization_retry_at = 0.0
    _finished = False
    _outpost_report_stage = 0
    _outpost_detail_signature = None
    _outpost_detail_report_count = 0
    _outpost_detail_last_emit = None
    _outpost_detail_last_ready = False
    _outpost_baseline_reported = False
    _outpost_detail_budget_exhausted = False
    _outpost_unready_since = None
    _outpost_baseline = None
    _attempt_id = None
    _last_forwarding_sequence = 0
    _last_refresh_sequence = 0
    _candidate_loading_event = None
    _loading_event = None
    _sample_output_error = None
    _final_verify_diagnostic_emitted = False
    _readiness_reported = False
    _readiness_characters = 0
    _reset_destination_samples()
    _emit("activation", "state=enabled source=widget_browser")


def on_disable() -> None:
    """End the active evidence attempt when WidgetManager disables this widget."""
    setattr(_cleansing_context_module, "STAGE3_LOCAL_WITNESS_DIAGNOSTIC", False)
    _finish("INCONCLUSIVE", "widget_disabled")


def _bind_owner_cursor(context: CleansingContext) -> None:
    global _owner_source, _last_owner_sequence, _owner_watermark, _last_refresh_sequence
    global _fixed_production_deadline, _last_completion_time
    if _attempt_id is None:
        return
    source = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.source_proof(_attempt_id, context)
    cursor = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.starting_cursor(_attempt_id, context)
    if source is None or cursor is None:
        raise _DiagnosticUnavailable("coherent original-outpost proof unavailable")
    _owner_source = source
    _last_owner_sequence = cursor
    _owner_watermark = cursor
    _last_refresh_sequence = source.boundary.completed_refresh
    _last_completion_time = source.boundary.completed_at
    _fixed_production_deadline = source.boundary.deadline


def _process_owner_batch(context: CleansingContext, runtime_expired: bool) -> None:
    global _last_owner_sequence, _owner_watermark, _last_refresh_sequence
    global _candidate_loading_event, _last_forwarding_sequence, _admission_event
    global _accepted_destination_events, _latest_destination_owner
    global _fixed_production_deadline, _last_completion_time
    global _sample_output_error
    baseline, source = _outpost_baseline, _owner_source
    if baseline is None or source is None or _attempt_id is None:
        _finish("INCONCLUSIVE", "outpost_baseline_missing")
        return
    try:
        if not runtime_expired and not STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.heartbeat(_attempt_id, context):
            _reset_destination_samples()
            _finish("INCONCLUSIVE", "validation_attempt_expired_or_replaced")
            return
        after_sequence = _last_owner_sequence
        batch = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.read_ordered_events(_attempt_id, _last_owner_sequence)
        if not batch.active:
            if runtime_expired and not batch.replaced:
                _finish("INCONCLUSIVE", _runtime_limit_reason())
            else:
                _reset_destination_samples()
                _finish("INCONCLUSIVE", "validation_attempt_expired_or_replaced")
            return
        if batch.overflowed:
            _reset_destination_samples()
            _finish("INCONCLUSIVE", "production_evidence_buffer_overflow")
            return
        now_ns = monotonic_ns()
        for owner in batch.events:
            boundary = owner.boundary
            if owner.sequence != _last_owner_sequence + 1 or int(owner.observed_at * 1_000_000_000) > now_ns:
                _reset_destination_samples()
                _finish("INCONCLUSIVE", "production_evidence_order_invalid")
                return
            _last_owner_sequence = owner.sequence
            if boundary.deadline is not None:
                if _fixed_production_deadline is None:
                    _fixed_production_deadline = boundary.deadline
                elif boundary.deadline != _fixed_production_deadline:
                    _reset_destination_samples()
                    _finish("INCONCLUSIVE", "production_deadline_changed")
                    return
            if (
                boundary.transition_id != source.boundary.transition_id
                or boundary.source_generation != source.boundary.source_generation
                or boundary.phase is TransitionPhase.RETIRED
                or boundary.retired_members
            ):
                production = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.evidence_for(context, owner)
                if _loading_event is None and production is not None:
                    _reject_outpost_change(baseline, _snapshot_evidence(owner.snapshot, context, production))
                    return
                classification = (
                    _classify_destination(_snapshot_evidence(owner.snapshot, context, production), baseline)
                    if production is not None and owner.snapshot.ready
                    else ("INCONCLUSIVE", "production_transition_retired")
                )
                _reset_destination_samples(preserve_output=classification[0] == "FAILURE")
                _finish(
                    *(
                        classification
                        if classification[0] == "FAILURE"
                        else ("INCONCLUSIVE", "production_transition_retired")
                    )
                )
                return
            observation = boundary.observation
            if _loading_event is not None and owner.sequence > cast(Stage3OwnerEvidence, _loading_event.owner).sequence:
                repeated = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.forwarding_for(_attempt_id, owner)
                if repeated is None or not _valid_repeated_forwarding_event(repeated, _loading_event):
                    _reset_destination_samples()
                    _finish("INCONCLUSIVE", "loading_association_changed")
                    return
            if _loading_event is None and observation is not None and observation.loading.loading:
                candidate = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.forwarding_for(_attempt_id, owner)
                if candidate is None or not _valid_initial_forwarding_event(candidate, baseline):
                    _finish("INCONCLUSIVE", "loading_authority_unproven")
                    return
                _candidate_loading_event = candidate
                if not _accept_loading_evidence(now_ns):
                    _finish("INCONCLUSIVE", "loading_evidence_invalid")
                    return
                _last_forwarding_sequence = owner.sequence
                try:
                    loading_line = _loading_line(candidate)
                except _CounterDisplayOverflow:
                    _sample_output_error = "counter_display_overflow"
                    continue
                if not _emit("loading", loading_line, reserved=True):
                    _finish("INCONCLUSIVE", "output_cap")
                    return
            if observation is None or not observation.readable:
                _reset_destination_samples()
                continue
            if owner.kind != "completion":
                if owner.kind == "invalidation":
                    _reset_destination_samples()
                continue
            completion = boundary.completed_refresh
            if (
                completion <= _last_refresh_sequence
                or boundary.completed_at is None
                or boundary.completed_at > owner.observed_at
                or (_last_completion_time is not None and boundary.completed_at < _last_completion_time)
                or boundary.snapshot_revision != owner.snapshot.revision
                or boundary.lifecycle_generation != owner.snapshot.lifecycle_epoch
            ):
                _reset_destination_samples()
                _finish("INCONCLUSIVE", "production_completion_order_invalid")
                return
            _last_refresh_sequence = completion
            _last_completion_time = boundary.completed_at
            production = STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.evidence_for(context, owner)
            if production is None:
                _reset_destination_samples()
                continue
            current = _snapshot_evidence(owner.snapshot, context, production)
            if observation.outpost:
                if current.signature != baseline.signature:
                    _reject_outpost_change(baseline, current)
                    return
                _reset_destination_samples()
                continue
            if _loading_event is None:
                _reset_destination_samples()
                _finish("INCONCLUSIVE", "loading_not_observed")
                return
            classification = _classify_destination(current, baseline)
            if classification[0] == "FAILURE":
                _reset_destination_samples(preserve_output=True)
                _finish(*classification)
                return
            if (
                not observation.explorable
                or not owner.snapshot.ready
                or not current.complete_eight
                or owner.verification is None
                or boundary.phase is not TransitionPhase.DESTINATION_VERIFIED
            ):
                _reset_destination_samples()
                continue
            if _admission_event is None:
                if boundary.deadline is None or boundary.completed_at >= boundary.deadline:
                    _finish("INCONCLUSIVE", "production_transition_expired")
                    return
                _admission_event = owner
            result, reason = _classify_destination(current, baseline)
            if result == "FAILURE":
                _reset_destination_samples(preserve_output=True)
                _finish(result, reason)
                return
            if result != "FULL_SUCCESS":
                _reset_destination_samples()
                continue
            event = ProbeRefreshEvent(
                completion, _attempt_id, int(boundary.completed_at * 1_000_000_000), production, owner
            )
            sampled = _collect_destination_sample(current, event)
            _latest_destination_owner = owner
            if sampled:
                _accepted_destination_events = (
                    (owner,) if _destination_samples == 1 else (*_accepted_destination_events, owner)
                )
                player, hero = current.remote_player, current.remote_hero
                continuity = _destination_continuity(current, baseline)
                try:
                    details = _sample_details(
                        _destination_samples,
                        _counter_text(completion),
                        _counter_text(owner.snapshot.lifecycle_epoch),
                        _sample_role_code(player.role) if player is not None else "UNK",
                        _sample_role_code(hero.role) if hero is not None else "UNK",
                        "/".join(str(int(value)) for value in continuity),
                    )
                    _pending_destination_sample_details.append(details)
                except _CounterDisplayOverflow:
                    _sample_output_error = "counter_display_overflow"
        _owner_watermark = batch.watermark
        if _loading_event is None and not runtime_expired and not getattr(context, "_stage3_mutations", 0):
            # A mutable published object is not new authority. Detect corruption
            # of the bound proof, while leaving active Refresh staging private.
            current = _capture_evidence(context)
            if current.signature != baseline.signature:
                _reject_outpost_change(baseline, current)
                return
        if _last_owner_sequence != batch.watermark:
            _reset_destination_samples()
            _finish("INCONCLUSIVE", "production_evidence_gap")
        elif runtime_expired:
            _finish("INCONCLUSIVE", _runtime_limit_reason())
        elif not STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.retain_processed_proofs(
            _attempt_id,
            context,
            after_sequence,
            batch.watermark,
            history=(
                source,
                *((_loading_event.owner,) if _loading_event is not None and _loading_event.owner is not None else ()),
                *((_admission_event,) if _admission_event is not None else ()),
            ),
            samples=_accepted_destination_events,
            latest=_latest_destination_owner,
        ):
            _reset_destination_samples()
            _finish("INCONCLUSIVE", "proof_retention_or_integrity_failed")
        elif _sample_output_error is not None:
            _finish("INCONCLUSIVE", _sample_output_error)
        elif _destination_samples == 3:
            _finish("FULL_SUCCESS", "three_stable_destination_samples")
        elif _admission_event is None:
            boundary = context.GetTransitionBoundary()
            if boundary.deadline is not None and monotonic() >= boundary.deadline:
                _reset_destination_samples()
                _finish("INCONCLUSIVE", "production_transition_expired")
    except Exception:
        _reset_destination_samples()
        _finish("INCONCLUSIVE", "diagnostic_unavailable")


def update() -> None:
    """WidgetManager invokes this only while the optional widget is enabled."""
    global _started_at, _last_poll_at, _outpost_report_stage, _outpost_baseline
    global _attempt_id, _last_forwarding_sequence, _last_refresh_sequence, _candidate_loading_event
    global _outpost_unready_since
    global _sample_output_error
    global _deferred_outpost_refresh

    if _finished:
        return
    if _terminal_outcome is not None:
        _retry_finalization()
        return
    now = monotonic()
    if _started_at is None:
        _started_at = now
    runtime_expired = now - _started_at >= _MAX_RUNTIME_SECONDS
    preflight_expired = _attempt_id is None and now - _started_at >= _MAX_PREFLIGHT_SECONDS
    if now - _last_poll_at < _POLL_SECONDS and not runtime_expired and not preflight_expired:
        return
    _last_poll_at = now

    try:
        phase = _phase()
        raw_context = getattr(GLOBAL_CACHE, "CleansingContext", None)
        context = raw_context if isinstance(raw_context, CleansingContext) else None
    except Exception:
        _finish("INCONCLUSIVE", "probe_read_failed")
        return
    if context is None:
        _finish("INCONCLUSIVE", "context_unavailable")
        return

    try:
        context.ReportRefreshDiagnostic()
    except Exception:
        pass

    if _attempt_id is not None:
        _process_owner_batch(context, runtime_expired)
        return

    if phase == "loading":
        if _attempt_id is None:
            _finish("INCONCLUSIVE", "outpost_baseline_not_established")
        elif runtime_expired:
            _finish("INCONCLUSIVE", _runtime_limit_reason())
        return

    if _attempt_id is None:
        if phase == "explorable":
            _finish("INCONCLUSIVE", "outpost_baseline_incomplete")
            return
        if phase == "unknown":
            if not _report_waiting_outpost("map_not_ready", _OUTPOST_WAIT_PHASE):
                _finish("INCONCLUSIVE", "output_cap")
            elif preflight_expired:
                _finish("INCONCLUSIVE", "outpost_baseline_not_established")
            return
        if phase != "outpost":
            return
        try:
            snapshot = context.GetSnapshot()
            if not snapshot.ready:
                if _outpost_unready_since is None:
                    _outpost_unready_since = now
                if now - _outpost_unready_since < _OUTPOST_DETAIL_INTERVAL_SECONDS and not preflight_expired:
                    return
                if not _report_outpost(
                    snapshot,
                    context,
                    None,
                    _OutpostWitnessEvidence("not_run", None, False, "gate_not_met"),
                    False,
                    (),
                ):
                    _finish("INCONCLUSIVE", "output_cap")
                elif preflight_expired:
                    _finish("INCONCLUSIVE", "outpost_baseline_not_established")
                return
            _outpost_unready_since = None
            if not snapshot.members:
                if not _report_outpost(
                    snapshot,
                    context,
                    None,
                    _OutpostWitnessEvidence("not_run", None, False, "gate_not_met"),
                    False,
                    ("members_missing",),
                ):
                    _finish("INCONCLUSIVE", "output_cap")
                elif preflight_expired:
                    _finish("INCONCLUSIVE", "outpost_baseline_not_established")
                return
            evidence = _capture_evidence(context)
            snapshot = evidence.snapshot
            baseline_created = False
            witness_status = _OutpostWitnessEvidence("not_run", None, False, "gate_not_met")
            waiting_reasons = _outpost_baseline_wait_reasons(evidence)
            # Current eligibility may rescue a throttled preflight update, but
            # cannot open a recorder after the overall collection has expired.
            if not runtime_expired and _outpost_is_baseline(evidence):
                witness_status = _outpost_witness_evidence(evidence, context)
                _outpost_baseline = _new_outpost_baseline(evidence, context, witness_status)
                baseline_created = _outpost_baseline is not None
                if not baseline_created:
                    waiting_reasons = (
                        "the evidence recorder did not open a validation attempt: "
                        + STAGE3_EVIDENCE_PROBE_DIAGNOSTICS.last_begin_reason,
                    )
            report_stage = _OUTPOST_REPORT_CREATED if baseline_created else _OUTPOST_REPORT_BASELINE
            if not _report_outpost(
                snapshot,
                context,
                evidence,
                witness_status,
                baseline_created,
                waiting_reasons,
            ):
                _finish("INCONCLUSIVE", "output_cap")
                return
            if report_stage > _outpost_report_stage:
                _outpost_report_stage = report_stage
            if _outpost_baseline is not None:
                _attempt_id = _outpost_baseline.attempt_id
                _bind_owner_cursor(context)
                if _attempt_id <= 0:
                    _finish("INCONCLUSIVE", "validation_attempt_unavailable")
                    return
                if not _report_zone_readiness(context):
                    _finish("INCONCLUSIVE", "output_cap")
                    return
            elif preflight_expired:
                _finish("INCONCLUSIVE", "outpost_baseline_not_established")
        except _DiagnosticUnavailable:
            _finish("INCONCLUSIVE", "diagnostic_unavailable")
            return
        except Exception:
            _finish("INCONCLUSIVE", "probe_read_failed")
            return
        return
