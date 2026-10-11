from __future__ import annotations

import re
from collections import Counter
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from enum import Enum
from threading import RLock
from threading import RLock as _CommitLock
from time import monotonic as _monotonic
from time import monotonic as _transition_clock
from typing import Any
from typing import Callable
from typing import Iterable
from typing import cast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Py4GWCoreLib.Map import LoadingObservation

from Py4GWCoreLib.enums_src.GameData_enums import Profession

_REFRESH_DIAGNOSTIC_MAX_LINES = 12
_REFRESH_DIAGNOSTIC_MAX_COUNTER = 2_147_483_647
_REFRESH_DIAGNOSTIC_MAX_LINE_CHARACTERS = 320
_REFRESH_DIAGNOSTIC_INTERVAL_SECONDS = 1.0

# TEMPORARY endpoint capture. Process/module lifetime cap; never reset on zoning or probe enable.
_endpoint_diagnostic_records = 0
_endpoint_diagnostic_seen: set[str] = set()
_endpoint_diagnostic_last_emit: float | None = None
_EndpointRead = dict[str, bool | int | str | None]
# Production refresh is normally about 150 ms: stabilize across several refreshes,
# but bound waiting for a full roster whose endpoints never finish initializing.
_ENDPOINT_STABLE_SECONDS = 2.0
_ENDPOINT_DEADLINE_SECONDS = 10.0
_endpoint_diagnostic_early_spent = False


@dataclass(slots=True)
class _EndpointCandidate:
    line: str
    stable_since: float
    started: float
    context_key: tuple[object, ...]
    roster_key: tuple[int, ...]


_endpoint_diagnostic_pending: _EndpointCandidate | None = None

# TEMPORARY, opt-in from the normal Python console via this module's switch.
# Switching off/on and zoning do not replenish the module-lifetime budget.
# Console: import importlib; diag = importlib.import_module(
#     "Py4GWCoreLib.GlobalCache.CleansingContext")
# Then: diag.STAGE3_LOCAL_WITNESS_DIAGNOSTIC = True (False disables).
# Per-hero w/q/p/r/b/o/c = matches/qualification/professions/role/bar/open/commit;
# H1-H7 are local hero ordinals, sorted by existing global party position.
# U means not evaluated. Raw transport bytes are not exposed at this read site.
STAGE3_LOCAL_WITNESS_DIAGNOSTIC = False
_LOCAL_WITNESS_LINE_LIMIT = 640
_local_witness_records = 0
_local_witness_seen: set[str] = set()
_local_witness_pending: _LocalWitnessCandidate | None = None
_local_witness_last_attempt: float | None = None
_local_witness_delivering = False


@dataclass(slots=True)
class _LocalWitnessCandidate(_EndpointCandidate):
    revision: int | None


@dataclass(slots=True)
class _LocalWitnessObservation:
    values: dict[str, str | int] = field(default_factory=lambda: dict[str, str | int]())
    heroes: dict[int, dict[str, str | int]] = field(default_factory=lambda: dict[int, dict[str, str | int]]())
    decision: _Stage3DecisionCapture | None = None
    decision_scopes: dict[int, str] = field(default_factory=lambda: dict[int, str]())


def _new_local_witness_observation(*, decision_capture: bool = False) -> _LocalWitnessObservation | None:
    try:
        return _LocalWitnessObservation() if STAGE3_LOCAL_WITNESS_DIAGNOSTIC or decision_capture else None
    except Exception:
        return None


def _local_witness_note(observation: _LocalWitnessObservation | None, slot: int = 0, **values: str | int) -> None:
    try:
        if observation is None:
            return
        if slot and not 1 <= slot <= 7:
            return
        target = observation.heroes.setdefault(slot, {}) if slot else observation.values
        for key, value in values.items():
            if key in ("gate", "final_gate") and value not in ("OK", "NOT_EVALUATED", "ACCEPTED", "COMMITTED"):
                _stage3_failure(
                    observation.decision,
                    str(value),
                    observation.decision_scopes.get(slot, "SHARED"),
                    3 if key == "final_gate" else 0,
                )
            if key == "closing" and target.get(key) not in (
                None,
                "OK",
                "NOT_EVALUATED",
            ):
                continue
            # A later generic failure must never erase the actual first rejection.
            if not key.endswith("gate") or key not in target:
                target[key] = value
    except Exception:
        if observation is not None and observation.decision is not None:
            observation.decision.failed = True


def _local_witness_reject(
    observation: _LocalWitnessObservation | None,
    code: str,
    rejected: bool,
    slot: int = 0,
) -> bool:
    if rejected:
        _local_witness_note(observation, slot, **({"gate": code} if slot else {"owner": code}))
    if slot and code == "WITNESS_PROFESSION":
        _local_witness_note(observation, slot, profession=int(not rejected))
    return rejected


def _local_witness_absent(observation: _LocalWitnessObservation | None, slot: int, agent: object) -> bool:
    absent = agent is None
    _local_witness_note(observation, slot, entry="ENTER" if absent else "AGENT_PRESENT")
    if absent:
        _local_witness_note(observation, slot, opening=0, committed=0)
    return absent


def _emit_local_witness_diagnostic(
    observation: _LocalWitnessObservation | None,
    *,
    context_key: tuple[object, ...],
    roster_key: tuple[int, ...],
    complete: bool,
) -> None:
    global _local_witness_records, _local_witness_pending, _local_witness_last_attempt, _local_witness_delivering
    try:
        if observation is None or _local_witness_records >= 3:
            _local_witness_pending = None
            return
        values = observation.values
        # Only allow literals authored at observation sites; no runtime reason text.
        codes = _LOCAL_WITNESS_CODES

        def code(value: str | int | None) -> str:
            return value if isinstance(value, str) and value in codes else "UNKNOWN"

        def count(value: str | int | None) -> str:
            return str(min(max(value, 0), 9)) if type(value) is int else "U"

        native = code(values.get("native", "NOT_EVALUATED"))
        owner = code(values.get("owner", "NOT_EVALUATED"))
        line = (
            "STAGE3_LOCAL_WITNESS_DIAG_V1 outpost=1 "
            f"ready={count(values.get('ready'))} raw=NOT_OBSERVED native={native} "
            f"cohort={count(values.get('cohorts'))}/{count(values.get('contextual'))}/"
            f"{count(values.get('claims'))} owner={owner}"
            f" eval={code(values.get('evaluation', 'NOT_EVALUATED'))}"
        )
        for index, (_position, row) in enumerate(sorted(observation.heroes.items())[:7], start=1):
            entry = code(row.get("entry", "NOT_EVALUATED"))
            gate = row.get("gate", "NOT_EVALUATED")
            if gate == "NOT_EVALUATED" and entry == "ENTER":
                gate = native if native not in ("OK", "NOT_EVALUATED") else owner
                if values.get("evaluation") == "EVALUATION_FAILED":
                    gate = "EVALUATION_FAILED"
            line += (
                f" H{index}={entry}/{code(gate)}/w{count(row.get('matches'))}"
                f"q{count(row.get('qualified'))}p{count(row.get('profession'))}"
                f"r{count(row.get('role'))}b{count(row.get('bar'))}"
                f"o{count(row.get('opening'))}c{count(row.get('committed'))}"
            )
        line += (
            f" close={code(values.get('closing', 'NOT_EVALUATED'))}"
            f" final={code(values.get('final', 'NOT_EVALUATED'))}"
            f"/{code(values.get('final_gate', 'NOT_EVALUATED'))}"
        )
        if len(line) > _LOCAL_WITNESS_LINE_LIMIT:
            return
        if line in _local_witness_seen:
            if not _local_witness_delivering:
                _local_witness_pending = None
            return
        now = _monotonic()
        observed_revision = values.get("revision")
        revision = observed_revision if type(observed_revision) is int else None
        pending = _local_witness_pending
        if pending is None or pending.context_key != context_key:
            pending = _LocalWitnessCandidate(line, now, now, context_key, roster_key, revision)
        elif pending.line != line or pending.roster_key != roster_key:
            pending = _LocalWitnessCandidate(line, now, pending.started, context_key, roster_key, revision)
        else:
            pending = replace(pending, revision=revision)
        _local_witness_pending = pending
        # Require 8/8 admission. A stable 6/6 startup must not spend this budget.
        # Retain the latest complete candidate even while the result churns.
        if not complete:
            _local_witness_pending = None
            return
        # Nested Refresh may retain newer evidence, but must never log recursively.
        if _local_witness_delivering:
            return
        if now - pending.stable_since < 2.0 and now - pending.started < 10.0:
            return
        if _local_witness_last_attempt is not None and now - _local_witness_last_attempt < 1.0:
            return
        import PySystem

        suffix = (
            f" revision={min(max(pending.revision, 0), _REFRESH_DIAGNOSTIC_MAX_COUNTER)}"
            if pending.revision is not None
            else " revision=UNKNOWN"
        )
        if len(line + suffix) > _LOCAL_WITNESS_LINE_LIMIT:
            return
        # Reserve before entering the console: it can reenter Refresh or emit and
        # then raise. Failed attempts share the cap and may retry after spacing.
        _local_witness_seen.add(line)
        _local_witness_last_attempt = now
        _local_witness_records += 1
        _local_witness_delivering = True
        try:
            PySystem.Console.Log("CleansingContext", line + suffix, PySystem.Console.MessageType.Info)
        except Exception:
            _local_witness_seen.discard(line)
            raise
        finally:
            _local_witness_delivering = False
        # A nested changed observation belongs to its own completed Refresh.
        if _local_witness_pending is pending:
            _local_witness_pending = None
    except Exception:
        pass


_LOCAL_WITNESS_CODES = frozenset(
    "UNKNOWN NOT_EVALUATED NOT_OBSERVED OK ENTER AGENT_PRESENT PROF_PRESENT "
    "IDENTITY_FAIL POSITION_FAIL READ_FAIL UNAVAILABLE BUSY RECOVERY SYNC_FAILURE "
    "READ_FAILED EVALUATION_FAILED COHORT_MISSING COHORT_AMBIGUOUS RECOVERY_EPOCH "
    "HWND UUID INCARNATION EPOCH COHORT_UUID OWNER_UUID OWNER_HWND OWNER_EMAIL "
    "OWNER_TYPE OWNER_KEY OWNER_SLOT OWNER_LOGIN OWNER_AGENT OWNER_PARENT OWNER_HERO "
    "OWNER_TICK LEASE OWNER_LIVING OWNER_LIVING_LOGIN OWNER_PROFESSION OWNER_ROSTER "
    "PUBLISHER_CONFLICT HERO_IDENTITY HERO_OWNER HERO_ENDPOINT CHILD_CLAIM CHILD_SEMANTICS "
    "WITNESS_MISSING WITNESS_DUPLICATE WITNESS_KIND WITNESS_PROFESSION WITNESS_BAR "
    "WITNESS_REVISION WITNESS_EPOCH WITNESS_TIME ENDPOINT_CONTRADICTION CHILD_CONTRADICTION "
    "ORIGINAL_UNSUPPORTED BAR_MISMATCH ACCEPTED PUBLICATION_REJECTED CONTROLLED_IDENTITY "
    "RUNTIME_REJECTED LOCAL_CONTINUITY READ_FAILED_CLOSING CLOSING_INCOHERENT COMMITTED".split()
)


@contextmanager
def _endpoint_observation_scope(sink: _EndpointRead | None) -> Iterator[_EndpointRead | None]:
    observation: _EndpointRead | None = (
        dict(
            agent_found=None,
            living_type=None,
            conversion=None,
            primary=None,
            professions=None,
            cached=None,
            gate="UNKNOWN",
        )
        if sink is not None
        else None
    )
    try:
        yield observation
    finally:
        if sink is not None and observation is not None:
            try:
                sink.clear()
                sink.update(observation)
            except Exception:
                pass


class CleansingRole(Enum):
    UNKNOWN = "unknown"
    ENERGY_SURGE = "energy_surge"
    PANIC = "panic"
    INEPTITUDE = "ineptitude"
    HEROIC_REFRAIN = "heroic_refrain"
    BIP = "bip"
    SOUL_TWISTING = "soul_twisting"
    HEALING_BURST = "healing_burst"
    TAO = "tao"


class MemberKind(Enum):
    PLAYER = "player"
    HERO = "hero"
    HENCHMAN = "henchman"


class EvidenceSource(Enum):
    LOCAL_PLAYER = "local_player"
    LOCAL_HERO = "local_hero"
    REMOTE_PLAYER = "remote_player"
    REMOTE_HERO = "remote_hero"
    NONE = "none"


class CompositionStatus(Enum):
    ACTIVE = "ACTIVE"
    FALLBACK = "FALLBACK"


@dataclass(frozen=True, slots=True)
class MemberIdentity:
    kind: MemberKind
    owner_id: int
    member_id: int
    agent_id: int = 0

    @property
    def stable_key(self) -> tuple[MemberKind, int, int]:
        return self.kind, self.owner_id, self.member_id


@dataclass(frozen=True, slots=True)
class CleansingSkillIDs:
    energy_surge: int
    panic: int
    ineptitude: int
    heroic_refrain: int
    blood_is_power: int
    soul_twisting: int
    shelter: int
    union: int
    healing_burst: int
    together_as_one: int

    @property
    def role_anchor_ids(self) -> tuple[int, ...]:
        return (
            self.energy_surge,
            self.panic,
            self.ineptitude,
            self.heroic_refrain,
            self.blood_is_power,
            self.soul_twisting,
            self.healing_burst,
            self.together_as_one,
        )

    @property
    def all_anchor_ids(self) -> tuple[int, ...]:
        return (*self.role_anchor_ids, self.shelter, self.union)


SUPPORTED_SKILL_NAMES: tuple[tuple[str, str], ...] = (
    ("energy_surge", "Energy_Surge"),
    ("panic", "Panic"),
    ("ineptitude", "Ineptitude"),
    ("heroic_refrain", "Heroic_Refrain"),
    ("blood_is_power", "Blood_is_Power"),
    ("soul_twisting", "Soul_Twisting"),
    ("shelter", "Shelter"),
    ("union", "Union"),
    ("healing_burst", "Healing_Burst"),
    ("together_as_one", "Together_as_one"),
)


def resolve_supported_skill_ids(resolve_skill_id: Callable[[str], int]) -> CleansingSkillIDs:
    resolved = {field: int(resolve_skill_id(name)) for field, name in SUPPORTED_SKILL_NAMES}
    if any(skill_id <= 0 for skill_id in resolved.values()):
        raise ValueError("one or more supported skill names did not resolve")
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("supported skill names resolved to duplicate IDs")
    return CleansingSkillIDs(**resolved)


@dataclass(frozen=True, slots=True)
class RoleEvidence:
    identity: MemberIdentity
    source: EvidenceSource
    primary_profession: int | None
    skill_ids: tuple[int, ...]
    ownership_proven: bool
    weapon_attack_equipped: bool | None = None


@dataclass(frozen=True, slots=True)
class RoleRecognition:
    candidate_role: CleansingRole
    reason: str
    anchor_skill_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MemberRecord:
    identity: MemberIdentity
    role: CleansingRole
    candidate_role: CleansingRole
    evidence_source: EvidenceSource
    reason: str
    primary_profession: int | None = None
    anchor_skill_ids: tuple[int, ...] = ()
    remote_provenance_generation: int | None = None


def _profession_anchors(profession: int, skill_ids: CleansingSkillIDs) -> tuple[int, ...]:
    anchors_by_profession = {
        int(Profession.Mesmer): (skill_ids.energy_surge, skill_ids.panic, skill_ids.ineptitude),
        int(Profession.Paragon): (skill_ids.heroic_refrain,),
        int(Profession.Necromancer): (skill_ids.blood_is_power,),
        int(Profession.Ritualist): (skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union),
        int(Profession.Monk): (skill_ids.healing_burst,),
        int(Profession.Ranger): (skill_ids.together_as_one,),
    }
    return anchors_by_profession.get(profession, ())


def _recognized_role_anchors(profession: int, skill_ids: CleansingSkillIDs) -> tuple[int, ...]:
    if profession == int(Profession.Mesmer):
        return skill_ids.energy_surge, skill_ids.panic, skill_ids.ineptitude
    if profession == int(Profession.Paragon):
        return (skill_ids.heroic_refrain,)
    if profession == int(Profession.Necromancer):
        return (skill_ids.blood_is_power,)
    if profession == int(Profession.Ritualist):
        return skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union
    if profession == int(Profession.Monk):
        return (skill_ids.healing_burst,)
    if profession == int(Profession.Ranger):
        return (skill_ids.together_as_one,)
    return ()


def recognize_role(evidence: RoleEvidence, skill_ids: CleansingSkillIDs) -> RoleRecognition:
    if evidence.source not in (
        EvidenceSource.LOCAL_PLAYER,
        EvidenceSource.LOCAL_HERO,
        EvidenceSource.REMOTE_PLAYER,
        EvidenceSource.REMOTE_HERO,
    ):
        return RoleRecognition(CleansingRole.UNKNOWN, "role evidence source is unsupported", ())
    if not evidence.ownership_proven:
        return RoleRecognition(CleansingRole.UNKNOWN, "member or skillbar ownership is ambiguous", ())
    if len(evidence.skill_ids) != 8 or any(skill_id <= 0 for skill_id in evidence.skill_ids):
        return RoleRecognition(CleansingRole.UNKNOWN, "skillbar evidence is incomplete", ())
    if evidence.primary_profession is None or evidence.primary_profession <= 0:
        return RoleRecognition(CleansingRole.UNKNOWN, "primary profession is unavailable", ())

    equipped = set(evidence.skill_ids)
    present_role_anchors: tuple[int, ...] = tuple(sorted(equipped.intersection(skill_ids.role_anchor_ids)))
    if not present_role_anchors:
        return RoleRecognition(CleansingRole.UNKNOWN, "no supported role anchor is equipped", ())
    if len(present_role_anchors) > 1:
        return RoleRecognition(
            CleansingRole.UNKNOWN,
            "multiple supported elite anchors make the role ambiguous",
            present_role_anchors,
        )

    profession = int(evidence.primary_profession)
    expected_anchors = _profession_anchors(profession, skill_ids)
    anchor = next(iter(equipped.intersection(skill_ids.role_anchor_ids)))
    if anchor not in expected_anchors:
        return RoleRecognition(
            CleansingRole.UNKNOWN,
            "supported role anchor conflicts with the primary profession",
            present_role_anchors,
        )

    if profession == int(Profession.Mesmer):
        role_by_anchor = {
            skill_ids.energy_surge: CleansingRole.ENERGY_SURGE,
            skill_ids.panic: CleansingRole.PANIC,
            skill_ids.ineptitude: CleansingRole.INEPTITUDE,
        }
        return RoleRecognition(role_by_anchor[anchor], "primary Mesmer with matching equipped elite anchor", (anchor,))
    if profession == int(Profession.Paragon):
        return RoleRecognition(CleansingRole.HEROIC_REFRAIN, "primary Paragon with Heroic Refrain equipped", (anchor,))
    if profession == int(Profession.Necromancer):
        return RoleRecognition(CleansingRole.BIP, "primary Necromancer with Blood is Power equipped", (anchor,))
    if profession == int(Profession.Ritualist):
        missing = tuple(
            name
            for name, anchor_id in (("Shelter", skill_ids.shelter), ("Union", skill_ids.union))
            if anchor_id not in equipped
        )
        if missing:
            return RoleRecognition(
                CleansingRole.UNKNOWN,
                "Soul Twisting protection anchors are incomplete: missing " + " and ".join(missing),
                tuple(
                    anchor_id
                    for anchor_id in (skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union)
                    if anchor_id in equipped
                ),
            )
        return RoleRecognition(
            CleansingRole.SOUL_TWISTING,
            "primary Ritualist with Soul Twisting, Shelter, and Union equipped",
            (skill_ids.soul_twisting, skill_ids.shelter, skill_ids.union),
        )
    if profession == int(Profession.Monk):
        return RoleRecognition(CleansingRole.HEALING_BURST, "primary Monk with Healing Burst equipped", (anchor,))
    if profession == int(Profession.Ranger):
        if evidence.weapon_attack_equipped is not True:
            reason = "Together as One lacks positive weapon-attack evidence"
            if evidence.weapon_attack_equipped is None:
                reason = "weapon-attack evidence is unavailable for Together as One"
            return RoleRecognition(CleansingRole.UNKNOWN, reason, (anchor,))
        return RoleRecognition(
            CleansingRole.TAO,
            "primary Ranger with Together as One and a weapon attack equipped",
            (anchor,),
        )
    return RoleRecognition(
        CleansingRole.UNKNOWN, "primary profession is outside the supported roles", present_role_anchors
    )


@dataclass(frozen=True, slots=True)
class CompositionResult:
    status: CompositionStatus
    role_counts: tuple[tuple[CleansingRole, int], ...]
    member_count: int
    declared_party_size: int | None
    reason: str

    @property
    def is_proven(self) -> bool:
        return self.status is CompositionStatus.ACTIVE


_CORE_COUNTS = (
    (CleansingRole.HEROIC_REFRAIN, 1),
    (CleansingRole.BIP, 1),
    (CleansingRole.SOUL_TWISTING, 1),
    (CleansingRole.INEPTITUDE, 1),
)
_SUPPORTED_HISTOGRAMS = (
    (*_CORE_COUNTS, (CleansingRole.ENERGY_SURGE, 4)),
    (*_CORE_COUNTS, (CleansingRole.ENERGY_SURGE, 3), (CleansingRole.PANIC, 1)),
    (*_CORE_COUNTS, (CleansingRole.ENERGY_SURGE, 3), (CleansingRole.HEALING_BURST, 1)),
    (*_CORE_COUNTS, (CleansingRole.ENERGY_SURGE, 3), (CleansingRole.TAO, 1)),
)


def match_supported_composition(
    members: Iterable[MemberRecord],
    declared_party_size: int | None = None,
) -> CompositionResult:
    member_list = tuple(members)
    # Stage 3 recognizes remote roles for consumers, but they cannot satisfy
    # the exact composition proof until the Stage 4 boundary is implemented.
    projected_roles = tuple(
        CleansingRole.UNKNOWN
        if member.evidence_source in (EvidenceSource.REMOTE_PLAYER, EvidenceSource.REMOTE_HERO)
        else member.role
        for member in member_list
    )
    counter = Counter(projected_roles)
    counts = tuple((role, counter.get(role, 0)) for role in CleansingRole)

    def fallback(reason: str) -> CompositionResult:
        return CompositionResult(CompositionStatus.FALLBACK, counts, len(member_list), declared_party_size, reason)

    if declared_party_size is not None and declared_party_size != len(member_list):
        return fallback(
            f"party roster evidence is incomplete: declared {declared_party_size}, observed {len(member_list)} members"
        )
    if len(member_list) != 8:
        return fallback(f"supported composition requires exactly 8 party members; observed {len(member_list)}")
    unique_member_keys = {member.identity.stable_key for member in member_list}
    if len(unique_member_keys) != len(member_list):
        return fallback("party roster contains duplicate member identities")
    if counter.get(CleansingRole.UNKNOWN, 0):
        return fallback("one or more required members have UNKNOWN roles")

    role_histogram = tuple((role, counter.get(role, 0)) for role in CleansingRole if role is not CleansingRole.UNKNOWN)
    for pattern in _SUPPORTED_HISTOGRAMS:
        pattern_counts = dict(pattern)
        if all(count == pattern_counts.get(role, 0) for role, count in role_histogram):
            return CompositionResult(
                CompositionStatus.ACTIVE,
                counts,
                len(member_list),
                declared_party_size,
                "supported role histogram matched",
            )

    return fallback("recognized role counts do not match a supported composition")


@dataclass(frozen=True, slots=True)
class CleansingContextSnapshot:
    revision: int
    lifecycle_epoch: int
    map_id: int | None
    ready: bool
    character_identity: tuple[str, str] | None
    members: tuple[MemberRecord, ...]
    composition: CompositionResult
    reason: str

    @property
    def supported_composition_proven(self) -> bool:
        return self.composition.is_proven

    def get_member(self, identity: MemberIdentity) -> MemberRecord | None:
        return next((member for member in self.members if member.identity == identity), None)


@dataclass(frozen=True, slots=True)
class _Baseline:
    role: CleansingRole
    profession: int
    relevant_anchors: tuple[int, ...]
    witness_origin: _LocalWitnessOrigin | None = None


@dataclass(frozen=True, slots=True)
class _PublishedAccount:
    slot_index: int
    slot_number: int
    account_email: str
    character_name: str
    key_hwnd: int
    key_entity_type: int
    key_local_index: int
    is_slot_active: bool
    is_account: bool
    is_hero: bool
    is_pet: bool
    is_npc: bool
    last_updated: int
    agent_id: int
    owner_agent_id: int
    hero_id: int
    login_number: int
    character_uuid: tuple[int, int, int, int]
    professions: tuple[int, int]
    map_signature: tuple[int, int, int, int]
    party_id: int
    skill_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _PublishedWitness:
    kind: int
    hero_id: int
    primary: int
    secondary: int
    skill_ids: tuple[int, ...]
    observed_at_tick64: int
    revision: int
    outpost_epoch: int


@dataclass(frozen=True, slots=True)
class _PublishedCohort:
    owner: _PublishedAccount
    children: tuple[_PublishedAccount, ...]
    incarnation: bytes
    character_uuid: tuple[int, int, int, int]
    instance_type: int
    instance_epoch: int
    published_tick: int
    witnesses: tuple[_PublishedWitness, ...]


@dataclass(frozen=True, slots=True)
class _PublisherToken:
    recovery_epoch: int
    incarnation: bytes
    character_uuid: tuple[int, int, int, int]
    account_email: str
    hwnd: int


@dataclass(frozen=True, slots=True)
class _LocalWitnessOrigin:
    publisher: _PublisherToken
    witness: _PublishedWitness
    destination_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class _OutpostHeroProof:
    identity: MemberIdentity
    cohort: _PublishedCohort
    professions: tuple[int, int]
    child: _PublishedAccount | None


@dataclass(frozen=True, slots=True)
class _LocalHeroWitnessRead:
    record_index: int
    party_position: int
    hero: _PartyHeroEvidence
    skill_ids: tuple[int, ...]
    origin: _LocalWitnessOrigin | None


@dataclass(frozen=True, slots=True)
class _LocalSkillbarRead:
    party_position: int
    agent_id: int
    skill_ids: tuple[int, ...]
    primary_profession: int
    witness: _PublishedWitness | None = None


@dataclass(frozen=True, slots=True)
class _RemotePlayerBaseline:
    publisher: _PublisherToken
    role: CleansingRole
    professions: tuple[int, int]
    relevant_anchors: tuple[int, ...]
    local_character_identity: tuple[str, str]
    local_character_uuid: tuple[int, int, int, int]
    party_id: int
    outpost_map_id: int
    lifecycle_epoch: int
    destination_map_id: int | None = None
    destination_lifecycle_epoch: int | None = None
    destination_instance_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class _RemoteBaselineReassociation:
    position: int
    source_key: tuple[MemberKind, int, int]
    destination_key: tuple[MemberKind, int, int]
    baseline: _RemotePlayerBaseline
    record: MemberRecord


@dataclass(frozen=True, slots=True)
class _RemoteOwnerProof:
    login_number: int
    agent_id: int
    cohort: _PublishedCohort
    publisher: _PublisherToken
    provenance_generation: int
    professions: tuple[int, int]
    candidate: RoleRecognition


@dataclass(frozen=True, slots=True)
class _PartyPlayerEvidence:
    login_number: int
    connected: bool
    agent_id: int
    character_name: str


@dataclass(frozen=True, slots=True)
class _PartyHeroEvidence:
    owner_login_number: int
    hero_id: int
    agent_id: int


@dataclass(frozen=True, slots=True)
class _RemoteHeroProof:
    identity: MemberIdentity
    cohort: _PublishedCohort
    child: _PublishedAccount
    professions: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _ClosingState:
    safe_lifecycle: bool
    map_id: int
    map_signature: tuple[int, int, int, int]
    instance_type: int
    party_id: int
    party_size: int
    players: tuple[tuple[int, bool, int], ...]
    heroes: tuple[tuple[int, int, int], ...]
    henchmen: tuple[int, ...]
    local_agent_id: int
    local_login_number: int
    local_account_email: str
    local_character_name: str
    local_character_uuid: tuple[int, int, int, int]
    local_hwnd: int


class _ClosingVerification(Enum):
    COHERENT = "coherent"
    UNAVAILABLE = "unavailable"
    INCOHERENT = "incoherent"
    CONTROLLED_IDENTITY_CHANGED = "controlled_identity_changed"
    RUNTIME_CHANGED = "runtime_changed"


class TransitionPhase(Enum):
    RETIRED = "retired"
    OUTPOST_READY = "outpost_ready"
    WAITING_FOR_LOADING = "waiting_for_loading"
    LOADING_CONFIRMED = "loading_confirmed"
    DESTINATION_PENDING = "destination_pending"
    DESTINATION_VERIFIED = "destination_verified"


@dataclass(frozen=True, slots=True)
class EnvironmentObservation:
    loading: LoadingObservation
    readable: bool
    cinematic: bool
    map_id: int | None
    outpost: bool
    explorable: bool
    character_identity: tuple[str, str] | None
    character_uuid: tuple[int, int, int, int] | None


@dataclass(frozen=True, slots=True)
class TransitionBoundary:
    """Owner-issued ordering shared by observations and completed Refresh calls."""

    sequence: int
    completed_refresh: int
    transition_id: int
    lifecycle_generation: int
    phase: TransitionPhase
    observation: EnvironmentObservation | None
    loading: LoadingObservation | None
    deadline: float | None
    source_generation: int | None = None
    destination: tuple[int, int, int, int] | None = None
    snapshot_revision: int = 0
    retired_members: frozenset[tuple[MemberKind, int, int]] = frozenset()
    completed_at: float | None = None


@dataclass(frozen=True, slots=True)
class _Stage3ClosingInputs:
    opening: _ClosingState
    players: tuple[_PartyPlayerEvidence, ...]
    heroes: tuple[_PartyHeroEvidence, ...]
    local_reads: tuple[_LocalSkillbarRead, ...]
    witness_reads: tuple[_LocalHeroWitnessRead, ...]
    owners: tuple[_RemoteOwnerProof, ...]
    hero_proofs: tuple[_RemoteHeroProof | _OutpostHeroProof, ...]
    captured_at_tick64: int
    role_skill_ids: CleansingSkillIDs


@dataclass(frozen=True, slots=True)
class Stage3OwnerEvidence:
    """Passive, context-local ordering; only the owner can issue a completion."""

    sequence: int
    kind: str
    boundary: TransitionBoundary
    snapshot: CleansingContextSnapshot
    local: tuple[tuple[tuple[MemberKind, int, int], _Baseline], ...]
    remote: tuple[tuple[tuple[MemberKind, int, int], _RemotePlayerBaseline], ...]
    verification: _Stage3ClosingInputs | None
    decision: Stage3DecisionBinding | None
    observed_at: float


@dataclass(frozen=True, slots=True)
class Stage3OwnerBatch:
    events: tuple[Stage3OwnerEvidence, ...]
    watermark: int
    gap: bool


@dataclass(frozen=True, slots=True)
class _Stage3ProofRetention:
    session: object
    attempt_id: int
    deadline: float
    source: Stage3OwnerEvidence
    cursor: int
    anchors: tuple[Stage3OwnerEvidence, ...]
    samples: tuple[Stage3OwnerEvidence, ...] = ()
    streak_valid: bool = True


@dataclass(slots=True)
class Stage3FinalVerificationDiagnostic:
    """First refusal only; copied facts, never queries or console delivery."""

    stage: str = "probe"
    boundary: str | None = None
    gate: str | None = None
    inputs_current: bool | None = None
    watermark_current: bool | None = None
    session_current: bool | None = None

    def reject(self, boundary: str, gate: str) -> bool:
        if self.gate is None:
            self.boundary, self.gate = boundary, gate
        return False


@dataclass(frozen=True, slots=True)
class _Transition:
    identifier: int
    generation: int
    source: _ClosingState
    verified_at: float
    local: tuple[tuple[tuple[MemberKind, int, int], _Baseline], ...]
    remote: tuple[tuple[tuple[MemberKind, int, int], _RemotePlayerBaseline], ...]
    origins: tuple[tuple[tuple[MemberKind, int, int], _LocalWitnessOrigin], ...]
    publishers: tuple[_PublisherToken, ...]
    started_at: float | None = None
    deadline: float | None = None
    loading: LoadingObservation | None = None
    destination: tuple[int, int, int, int] | None = None
    admitted: frozenset[tuple[MemberKind, int, int]] = frozenset()
    retired: frozenset[tuple[MemberKind, int, int]] = frozenset()


@dataclass(frozen=True, slots=True)
class Stage3RefreshDecision:
    """Temporary coded evidence; sequence identifies a Refresh, never a revision.

    Paths count direct/witness/blocked/identity-or-read/other attempts. Baselines
    count prior/current commits/prior still present/prior removed, for local heroes.
    Retention overlaps commitment; it does not claim the old witness stayed valid.
    Failure pass 1/2 is publication closing, 3 is final runtime, 0 is earlier work.
    """

    session: object
    sequence: int
    revision: int
    paths: tuple[int, ...]
    opening: str
    closing: str
    failure: tuple[str, str, int]
    final: str
    baselines: tuple[int, int, int, int]
    remote: tuple[int, int]


@dataclass(frozen=True, slots=True)
class Stage3DecisionBinding:
    snapshot: CleansingContextSnapshot
    decision: Stage3RefreshDecision
    local: tuple[tuple[tuple[MemberKind, int, int], object], ...]
    remote: tuple[tuple[tuple[MemberKind, int, int], object], ...]


@dataclass(slots=True)
class _Stage3DecisionCapture:
    session: object
    sequence: int
    paths: list[int] = field(default_factory=lambda: [0] * 5)
    previous: tuple[tuple[MemberKind, int, int], ...] = ()
    opening: str = "NOT_EVALUATED"
    closing: str = "NOT_EVALUATED"
    failure: tuple[str, str, int] = ("NONE", "NONE", 0)
    closing_pass: int = 0
    final: str = "NOT_EVALUATED"
    failed: bool = False


def _stage3_failure(capture: _Stage3DecisionCapture | None, gate: str, scope: str, pass_number: int = 0) -> None:
    try:
        if capture is not None and capture.failure[0] == "NONE":
            capture.failure = (gate, scope, pass_number or capture.closing_pass)
    except Exception:
        if capture is not None:
            capture.failed = True


def _stage3_reject(capture: _Stage3DecisionCapture | None, gate: str, scope: str, rejected: bool) -> bool:
    try:
        if rejected:
            _stage3_failure(capture, gate, scope)
    except Exception:
        if capture is not None:
            capture.failed = True
    return rejected


def _stage3_hero_scope(
    capture: _Stage3DecisionCapture | None,
    identity: MemberIdentity,
    heroes: tuple[_PartyHeroEvidence, ...],
    local_login: int,
) -> str:
    try:
        if capture is not None:
            for ordinal, hero in enumerate(heroes[:7], start=1):
                if hero.owner_login_number == identity.owner_id and hero.hero_id == identity.member_id:
                    return f"{'LH' if identity.owner_id == local_login else 'RH'}{ordinal}"
    except Exception:
        if capture is not None:
            capture.failed = True
    return "UNKNOWN"


def _stage3_publisher_reject(
    capture: _Stage3DecisionCapture | None,
    cohort: _PublishedCohort,
    recovery_epoch: int,
    publisher: _PublisherToken,
    scope: str,
    rejected: bool,
) -> bool:
    try:
        if rejected and capture is not None:
            if recovery_epoch != publisher.recovery_epoch:
                gate = "RECOVERY"
            elif cohort.incarnation != publisher.incarnation:
                gate = "INCARNATION"
            elif cohort.character_uuid != publisher.character_uuid:
                gate = "OWNER_UUID"
            elif cohort.owner.account_email.strip().casefold() != publisher.account_email:
                gate = "OWNER_EMAIL"
            elif cohort.owner.key_hwnd != publisher.hwnd:
                gate = "OWNER_HWND"
            else:
                gate = "PUBLISHER"
            _stage3_failure(capture, gate, scope)
    except Exception:
        if capture is not None:
            capture.failed = True
    return rejected


def _local_witness_closing_code(result: _ClosingVerification) -> str:
    try:
        # INCOHERENT includes both publication and live endpoint evidence failures.
        return {
            _ClosingVerification.COHERENT: "OK",
            _ClosingVerification.UNAVAILABLE: "UNAVAILABLE",
            _ClosingVerification.INCOHERENT: "CLOSING_INCOHERENT",
            _ClosingVerification.CONTROLLED_IDENTITY_CHANGED: "CONTROLLED_IDENTITY",
            _ClosingVerification.RUNTIME_CHANGED: "RUNTIME_REJECTED",
        }[result]
    except Exception:
        return "UNKNOWN"


def _copy_published_account(evidence: object) -> _PublishedAccount:
    account = getattr(evidence, "GetAccountData")()
    agent_data = account.AgentData
    skill_ids = tuple(int(skill.Id) for skill in agent_data.Skillbar.Skills)
    return _PublishedAccount(
        slot_index=int(getattr(evidence, "slot_index")),
        slot_number=int(account.SlotNumber),
        account_email=str(account.AccountEmail),
        character_name=str(agent_data.CharacterName),
        key_hwnd=int(account.Key.HWND),
        key_entity_type=int(account.Key.EntityType),
        key_local_index=int(account.Key.LocalIndex),
        is_slot_active=bool(account.IsSlotActive),
        is_account=bool(account.IsAccount),
        is_hero=bool(account.IsHero),
        is_pet=bool(account.IsPet),
        is_npc=bool(account.IsNPC),
        last_updated=int(account.LastUpdated),
        agent_id=int(agent_data.AgentID),
        owner_agent_id=int(agent_data.OwnerAgentID),
        hero_id=int(agent_data.HeroID),
        login_number=int(agent_data.LoginNumber),
        character_uuid=_copy_uuid(agent_data.UUID),
        professions=_copy_professions(agent_data.Profession),
        map_signature=(
            int(agent_data.Map.MapID),
            int(agent_data.Map.Region),
            int(agent_data.Map.District),
            int(agent_data.Map.Language),
        ),
        party_id=int(account.AgentPartyData.PartyID),
        skill_ids=skill_ids,
    )


def _copy_published_cohorts(snapshot: object) -> tuple[_PublishedCohort, ...]:
    copied: list[_PublishedCohort] = []
    for cohort in getattr(snapshot, "cohorts"):
        witnesses = tuple(
            _PublishedWitness(
                kind=int(witness.kind.value),
                hero_id=int(witness.hero_id),
                primary=int(witness.primary),
                secondary=int(witness.secondary),
                skill_ids=tuple(int(skill_id) for skill_id in witness.skills),
                observed_at_tick64=int(witness.observed_at_tick64),
                revision=int(witness.revision),
                outpost_epoch=int(witness.outpost_epoch),
            )
            for witness in cohort.witnesses
        )
        copied.append(
            _PublishedCohort(
                owner=_copy_published_account(cohort.owner),
                children=tuple(_copy_published_account(child) for child in cohort.children),
                incarnation=bytes(cohort.incarnation),
                character_uuid=_copy_uuid(cohort.character_uuid),
                instance_type=int(cohort.instance_type),
                instance_epoch=int(cohort.instance_epoch),
                published_tick=int(cohort.published_tick),
                witnesses=witnesses,
            )
        )
    return tuple(copied)


def _copy_uuid(values: Iterable[int]) -> tuple[int, int, int, int]:
    copied = tuple(int(value) for value in values)
    if len(copied) != 4:
        raise ValueError("character UUID must contain four values")
    return copied[0], copied[1], copied[2], copied[3]


def _copy_professions(values: Iterable[int]) -> tuple[int, int]:
    copied = tuple(int(value) for value in values)
    if len(copied) != 2:
        raise ValueError("profession pair must contain two values")
    return copied[0], copied[1]


def _publisher_token(cohort: _PublishedCohort, recovery_epoch: int) -> _PublisherToken:
    owner = cohort.owner
    return _PublisherToken(
        recovery_epoch=int(recovery_epoch),
        incarnation=cohort.incarnation,
        character_uuid=cohort.character_uuid,
        account_email=owner.account_email.strip().casefold(),
        hwnd=owner.key_hwnd,
    )


def _qualified_hero_witness(
    cohort: _PublishedCohort,
    hero_id: int,
    captured_at_tick64: int,
    observation: _LocalWitnessObservation | None = None,
    slot: int = 0,
) -> _PublishedWitness | None:
    matches = tuple(witness for witness in cohort.witnesses if witness.hero_id == hero_id)
    _local_witness_note(observation, slot, matches=len(matches))
    if len(matches) != 1:
        _local_witness_note(
            observation,
            slot,
            qualified=0,
            gate="WITNESS_MISSING" if not matches else "WITNESS_DUPLICATE",
        )
        return None
    witness = matches[0]
    if (
        _local_witness_reject(observation, "WITNESS_KIND", witness.kind != 1, slot)
        or _local_witness_reject(observation, "WITNESS_PROFESSION", not 1 <= witness.primary <= 10, slot)
        or _local_witness_reject(observation, "WITNESS_PROFESSION", not 0 <= witness.secondary <= 10, slot)
        or _local_witness_reject(observation, "WITNESS_BAR", len(witness.skill_ids) != 8, slot)
        or _local_witness_reject(
            observation,
            "WITNESS_BAR",
            any(skill <= 0 for skill in witness.skill_ids),
            slot,
        )
        or _local_witness_reject(observation, "WITNESS_REVISION", witness.revision <= 0, slot)
        or _local_witness_reject(observation, "WITNESS_EPOCH", witness.outpost_epoch <= 0, slot)
        or _local_witness_reject(
            observation,
            "WITNESS_TIME",
            witness.observed_at_tick64 > captured_at_tick64,
            slot,
        )
        or _local_witness_reject(
            observation,
            "WITNESS_TIME",
            captured_at_tick64 - witness.observed_at_tick64
            < ((captured_at_tick64 - cohort.published_tick) & 0xFFFFFFFF),
            slot,
        )
        or _local_witness_reject(
            observation,
            "WITNESS_EPOCH",
            cohort.instance_type == 0 and witness.outpost_epoch != cohort.instance_epoch,
            slot,
        )
        or _local_witness_reject(
            observation,
            "WITNESS_EPOCH",
            cohort.instance_type == 1 and witness.outpost_epoch >= cohort.instance_epoch,
            slot,
        )
        or _local_witness_reject(observation, "WITNESS_EPOCH", cohort.instance_type not in (0, 1), slot)
    ):
        _local_witness_note(observation, slot, qualified=0)
        return None
    _local_witness_note(observation, slot, qualified=1, profession=1)
    return witness


def _trustworthy_name(value: str) -> str | None:
    name = value.strip()
    if not name or "\ufffd" in name or any(ord(character) < 32 or ord(character) == 127 for character in name):
        return None
    if re.search(r"\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})", name):
        return None
    return name.casefold()


def _read_living_identity(
    agent_api: object, agent_id: int, observation: _EndpointRead | None = None, *, verify_hero_identity: bool = False
) -> tuple[int, int, int] | None:
    with _endpoint_observation_scope(observation) as current:
        if current is not None:
            current["gate"] = "ID"
        if agent_id <= 0:
            return None
        if current is not None:
            current["gate"] = "READ"
        agent = getattr(agent_api, "GetAgentByID")(agent_id)
        if current is not None:
            current.update(agent_found=agent is not None, gate="AGENT")
        if agent is None:
            return None
        if verify_hero_identity and int(getattr(agent, "agent_id")) != agent_id:
            raise ValueError("hero endpoint identity contradicts the party roster")
        if current is not None:
            current["gate"] = "READ"
        is_living = bool(getattr(agent, "is_living_type", False))
        if current is not None:
            current.update(living_type=is_living, gate="TYPE")
        if not is_living:
            return None
        if current is not None:
            current["gate"] = "READ"
        living = getattr(agent, "GetAsAgentLiving")()
        if current is not None:
            current.update(conversion=living is not None, gate="CONVERT")
        if living is None:
            return None
        if current is not None:
            current["gate"] = "READ"
        login = int(getattr(living, "login_number"))
        primary = int(getattr(living, "primary"))
        if current is not None:
            current["primary"] = primary
        secondary = int(getattr(living, "secondary"))
        if current is not None:
            current.update(professions=True, gate="OK")
        return login, primary, secondary


def _endpoint_reason(record: MemberRecord) -> str:
    if record.role is not CleansingRole.UNKNOWN:
        return "ok"
    # Match only fixed production labels; never serialize runtime reason text.
    for fragment, code in (
        ("primary profession is unavailable", "profession"),
        ("identity is ambiguous", "identity"),
        ("skillbar index does not match", "index"),
        ("skillbar evidence is incomplete", "bar"),
        ("evidence read failed", "read"),
        ("multiple supported elite anchors", "anchor"),
        ("conflicts with the primary profession", "conflict"),
    ):
        if fragment in record.reason:
            return code
    return "other"


def _endpoint_flags(observation: _EndpointRead) -> str:
    return "".join(
        "1" if observation.get(key) is True else "0" if observation.get(key) is False else "U"
        for key in ("agent_found", "living_type", "conversion")
    )


def _endpoint_gate(observation: _EndpointRead) -> str:
    gate = observation.get("gate")
    for code in ("ID", "ROSTER", "OWNER", "AGENT", "TYPE", "CONVERT", "ZERO", "OK", "CACHE", "READ"):
        if gate == code:
            return code
    return "UNKNOWN"


def _emit_endpoint_diagnostic(
    local: list[tuple[_EndpointRead, MemberRecord]],
    remote: _EndpointRead,
    *,
    context_key: tuple[object, ...] = (),
    roster_key: tuple[int, ...] = (),
    endpoints_ready: bool = True,
) -> None:
    global _endpoint_diagnostic_records, _endpoint_diagnostic_last_emit
    global _endpoint_diagnostic_pending, _endpoint_diagnostic_early_spent
    try:
        if _endpoint_diagnostic_records >= 3:
            return
        rows: list[str] = []
        for slot, (observation, record) in enumerate(local, start=1):
            primary = observation.get("primary")
            profession = str(primary) if type(primary) is int and 0 <= primary <= 10 else "U"
            usable = observation.get("bar")
            bar = "1" if usable is True else "0" if usable is False else "U"
            rows.append(
                f"H{slot}={_endpoint_flags(observation)}/{profession}/{bar}/"
                f"{_endpoint_reason(record)}/{_endpoint_gate(observation)}"
            )
        professions = remote.get("professions")
        available = "1" if professions is True else "0" if professions is False else "U"
        rows.append(f"R={_endpoint_flags(remote)}/{available}/{_endpoint_gate(remote)}")
        native: list[str] = []
        for key, label in (("children", "c"), ("witnesses", "w")):
            count = remote.get(key)
            native.append(f"{label}{min(max(count, 0), 9)}" if type(count) is int else f"{label}NOT_EVALUATED")
        line = "STAGE3_ENDPOINT_DIAG_V1 " + " ".join(rows) + " N=" + ",".join(native)
        now = _monotonic()
        if len(line) + 1 > 320 or line in _endpoint_diagnostic_seen:
            _endpoint_diagnostic_pending = None
            return
        pending = _endpoint_diagnostic_pending
        if pending is None or pending.context_key != context_key:
            pending = _EndpointCandidate(line, now, now, context_key, roster_key)
            _endpoint_diagnostic_pending = pending
        elif pending.line != line or pending.roster_key != roster_key:
            # Replace transient evidence; keep the deadline so churn cannot postpone forever.
            pending.line = line
            pending.roster_key = roster_key
            pending.stable_since = now
        early = _endpoint_gate(remote) in ("UNKNOWN", "ROSTER", "OWNER", "ID")
        # At most one pre-endpoint attempt; reserve the other two for actual remote reads.
        if (
            (early and _endpoint_diagnostic_early_spent)
            or not (
                (endpoints_ready and now - pending.stable_since >= _ENDPOINT_STABLE_SECONDS)
                or now - pending.started >= _ENDPOINT_DEADLINE_SECONDS
            )
            or (_endpoint_diagnostic_last_emit is not None and now - _endpoint_diagnostic_last_emit < 1.0)
        ):
            return
        # Count attempts too: a failing console must not cause per-frame retries.
        _endpoint_diagnostic_records += 1
        if early:
            _endpoint_diagnostic_early_spent = True
        _endpoint_diagnostic_seen.add(line)
        _endpoint_diagnostic_last_emit = now
        _endpoint_diagnostic_pending = None
        import PySystem

        PySystem.Console.Log("CleansingContext", line, PySystem.Console.MessageType.Info)
    except Exception:
        pass


def _weapon_attack_evidence(
    primary_profession: int,
    bar_skill_ids: tuple[int, ...],
    skill_api: object,
    skill_type_attack: int,
    skill_ids: CleansingSkillIDs,
) -> bool | None:
    if primary_profession != int(Profession.Ranger) or skill_ids.together_as_one not in bar_skill_ids:
        return None
    type_read_failed = False
    for bar_skill_id in bar_skill_ids:
        try:
            skill_type = int(getattr(skill_api, "GetType")(bar_skill_id)[0])
        except Exception:
            type_read_failed = True
            continue
        if skill_type == skill_type_attack:
            return True
    return None if type_read_failed else False


def _recognize_bar(
    *,
    identity: MemberIdentity,
    source: EvidenceSource,
    profession: int,
    bar_skill_ids: tuple[int, ...],
    skill_api: object,
    skill_type_attack: int,
    role_skill_ids: CleansingSkillIDs,
) -> RoleRecognition:
    evidence = RoleEvidence(
        identity=identity,
        source=source,
        primary_profession=profession,
        skill_ids=bar_skill_ids,
        ownership_proven=True,
        weapon_attack_equipped=_weapon_attack_evidence(
            profession, bar_skill_ids, skill_api, skill_type_attack, role_skill_ids
        ),
    )
    return recognize_role(evidence, role_skill_ids)


def _read_closing_state() -> _ClosingState:
    import PyParty
    import PySystem

    from Py4GWCoreLib.Context import GWContext

    map_context = GWContext.Map.GetContext()
    char = GWContext.Char.GetContext()
    world = GWContext.World.GetContext()
    instance = GWContext.InstanceInfo.GetContext()
    server_region = GWContext.ServerRegion.GetContext()
    cinematic = GWContext.Cinematic.GetContext()
    if (
        map_context is None
        or char is None
        or world is None
        or instance is None
        or server_region is None
        or cinematic is None
    ):
        raise RuntimeError("closing runtime context is unavailable")

    party = PyParty.PyParty()
    party.GetContext()
    players = tuple(
        (
            int(member.login_number),
            bool(member.is_connected),
            int(party.GetAgentIDByLoginNumber(int(member.login_number))),
        )
        for member in party.players
    )
    heroes = tuple(
        (int(hero.owner_player_id), int(hero.hero_id), int(hero.agent_id)) for hero in party.heroes
    )
    henchmen = tuple(int(henchman.agent_id) for henchman in party.henchmen)
    controlled_character = world.player_controlled_character
    if controlled_character is None:
        raise RuntimeError("closing player agent is unavailable")
    local_agent_id = int(controlled_character.agent_id)
    local_logins = tuple(
        login_number
        for login_number, connected, agent_id in players
        if connected and agent_id == local_agent_id
    )
    local_login_number = local_logins[0] if len(local_logins) == 1 else 0
    local_character_name = str(char.player_name_str or "").strip()
    local_character_uuid = _copy_uuid(char.player_uuid)
    local_hwnd = int(PySystem.Console.get_gw_window_handle() or 0)
    map_id = int(char.current_map_id)
    map_signature = (
        map_id,
        int(server_region.region_id),
        int(char.district_number),
        int(char.language),
    )
    instance_type = int(instance.instance_type)
    map_info = instance.current_map_info
    safe_lifecycle = (
        map_id > 0
        and int(char.observe_map_id) == map_id
        and instance_type in (0, 1)
        and cinematic.h0004 == 0
        and bool(party.is_party_loaded)
        and map_info is not None
        and not bool(map_info.is_pvp)
        and local_agent_id > 0
        and local_login_number > 0
    )
    return _ClosingState(
        safe_lifecycle=safe_lifecycle,
        map_id=map_id,
        map_signature=map_signature,
        instance_type=instance_type,
        party_id=int(party.party_id),
        party_size=int(party.party_size),
        players=players,
        heroes=heroes,
        henchmen=henchmen,
        local_agent_id=local_agent_id,
        local_login_number=local_login_number,
        local_account_email=str(char.player_email_str or "").strip().casefold(),
        local_character_name=local_character_name,
        local_character_uuid=local_character_uuid,
        local_hwnd=local_hwnd,
    )


def _unknown_member(
    identity: MemberIdentity,
    source: EvidenceSource,
    reason: str,
    profession: int | None = None,
    candidate_role: CleansingRole = CleansingRole.UNKNOWN,
    anchor_skill_ids: tuple[int, ...] = (),
) -> MemberRecord:
    return MemberRecord(
        identity=identity,
        role=CleansingRole.UNKNOWN,
        candidate_role=candidate_role,
        evidence_source=source,
        reason=reason,
        primary_profession=profession,
        anchor_skill_ids=anchor_skill_ids,
    )


def _role_evidence_record(evidence: RoleEvidence, recognition: RoleRecognition) -> MemberRecord:
    return MemberRecord(
        identity=evidence.identity,
        role=recognition.candidate_role,
        candidate_role=recognition.candidate_role,
        evidence_source=evidence.source,
        reason=recognition.reason,
        primary_profession=evidence.primary_profession,
        anchor_skill_ids=recognition.anchor_skill_ids,
    )


def _replace_record_role(record: MemberRecord, role: CleansingRole, reason: str) -> MemberRecord:
    return MemberRecord(
        identity=record.identity,
        role=role,
        candidate_role=record.candidate_role,
        evidence_source=record.evidence_source,
        reason=reason,
        primary_profession=record.primary_profession,
        anchor_skill_ids=record.anchor_skill_ids,
        remote_provenance_generation=record.remote_provenance_generation,
    )


class CleansingContext:
    """Publishes party roles with local and remote provenance plus exact team proof."""

    def __init__(self) -> None:
        self._revision = 0
        self._lifecycle_epoch = 0
        self._snapshot = CleansingContextSnapshot(
            revision=0,
            lifecycle_epoch=0,
            map_id=None,
            ready=False,
            character_identity=None,
            members=(),
            composition=match_supported_composition(()),
            reason="context has not been refreshed",
        )
        self._baselines: dict[tuple[MemberKind, int, int], _Baseline] = {}
        self._remote_player_baselines: dict[tuple[MemberKind, int, int], _RemotePlayerBaseline] = {}
        self._remote_hero_origins: dict[tuple[MemberKind, int, int], _LocalWitnessOrigin] = {}
        # After observing an outpost, a destination cannot reacquire a retired origin.
        self._remote_hero_outpost_seen = False
        self._remote_publisher_generations: dict[int, tuple[_PublisherToken, int]] = {}
        self._role_skill_ids: CleansingSkillIDs | None = None
        self._character_identity: tuple[str, str] | None = None
        self._last_ready_map_id: int | None = None
        self._last_ready_was_outpost = False
        self._last_hero_agents: dict[tuple[int, int], int] = {}
        self._pending_outpost_transition = False
        self._pending_remote_outpost_transition = False
        self._transition: _Transition | None = None
        self._transition_phase = TransitionPhase.RETIRED
        self._transition_counter = 0
        self._observation_sequence = 0
        self._completed_refresh = 0
        self._completed_at: float | None = None
        self._environment: EnvironmentObservation | None = None
        self._boundary = TransitionBoundary(0, 0, 0, 0, TransitionPhase.RETIRED, None, None, None)
        self._staged_evidence: (
            tuple[
                dict[tuple[MemberKind, int, int], _Baseline],
                dict[tuple[MemberKind, int, int], _RemotePlayerBaseline],
                dict[tuple[MemberKind, int, int], _LocalWitnessOrigin],
            ]
            | None
        ) = None
        self._closing_preserve_candidates = False
        self._refresh_diagnostic_attempts = 0
        self._refresh_diagnostic_window_attempts = 0
        self._refresh_diagnostic_window_successes = 0
        self._refresh_diagnostic_window_failures = 0
        self._refresh_diagnostic_lines = 0
        self._refresh_diagnostic_last_emit: float | None = None
        self._refresh_diagnostic_last_outcome = "none"
        self._refresh_diagnostic_error_type: str | None = None
        self._refresh_diagnostic_failure_site: str | None = None
        self._refresh_diagnostic_snapshot = self._snapshot
        self._stage3_decision_session: object | None = None
        try:
            self._stage3_session_lock: RLock | None = RLock()
        except Exception:
            self._stage3_session_lock = None
        self._stage3_decision_sequence = 0
        self._stage3_decision_active: _Stage3DecisionCapture | None = None
        self._stage3_decision_result: Stage3DecisionBinding | None = None
        self._stage3_decision_status = "UNAVAILABLE"

        # This lock protects passive capture/commit, never runtime reads. A writer
        # announces itself before doing work so final verification cannot commit
        # against a partially completed or reentrant recognition operation.
        try:
            self._stage3_evidence_lock: RLock | None = RLock()
        except Exception:
            self._stage3_evidence_lock = None
        # Production commits remain serialized when passive diagnostics cannot
        # allocate their synchronization surface. Normally this is the same lock.
        self._recognition_commit_lock = self._stage3_evidence_lock or _CommitLock()
        self._stage3_mutations = 0
        self._stage3_generation = 0
        self._stage3_evidence_sequence = 0
        self._stage3_evidence_failed = False
        self._stage3_evidence: deque[Stage3OwnerEvidence] = deque(maxlen=256)
        self._stage3_closing_inputs: _Stage3ClosingInputs | None = None
        self._stage3_proof_retention: _Stage3ProofRetention | None = None
        self._stage3_retention_started = False

    @contextmanager
    def _stage3_mutation(self, *, commit_only: bool = False) -> Iterator[None]:
        with self._recognition_commit_lock:
            self._stage3_mutations += 1
            self._stage3_generation += 1
            self._stage3_closing_inputs = None
            if commit_only:
                try:
                    yield
                finally:
                    self._stage3_mutations -= 1
                return
        try:
            yield
        finally:
            with self._recognition_commit_lock:
                self._stage3_mutations -= 1

    def ReadStage3OwnerEvidence(self, after_sequence: int) -> Stage3OwnerBatch:
        if self._stage3_evidence_lock is None:
            return Stage3OwnerBatch((), 0, True)
        with self._stage3_evidence_lock:
            self._expire_stage3_retention()
            events = tuple(event for event in self._stage3_evidence if event.sequence > after_sequence)
            oldest = self._stage3_evidence[0].sequence if self._stage3_evidence else after_sequence + 1
            return Stage3OwnerBatch(
                events, self._stage3_evidence_sequence, self._stage3_evidence_failed or oldest > after_sequence + 1
            )

    def _expire_stage3_retention(self) -> None:
        retention = self._stage3_proof_retention
        if retention is not None and _transition_clock() >= retention.deadline:
            self._stage3_proof_retention = None

    def BeginStage3ProofRetention(
        self, session: object, attempt_id: int, source: Stage3OwnerEvidence, cursor: int, deadline: float
    ) -> None:
        if self._stage3_evidence_lock is None:
            raise RuntimeError("owner retention unavailable")
        with self._stage3_evidence_lock:
            proof, _reason = self.InspectStage3Outpost(source.snapshot)
            now = _transition_clock()
            if (
                not self.OwnsStage3DecisionSession(session)
                or self._stage3_retention_started
                or proof is not source
                or cursor != self._stage3_evidence_sequence
                or not now < deadline <= now + 180.0
            ):
                raise RuntimeError("owner retention binding invalid")
            inputs = source.verification
            tail = tuple(event for event in self._stage3_evidence if event.sequence > source.sequence)
            if (
                inputs is None
                or len(tail) != cursor - source.sequence
                or any(
                    event.sequence != source.sequence + index
                    or event.kind != "observation"
                    or event.snapshot is not source.snapshot
                    or event.boundary.phase is not TransitionPhase.OUTPOST_READY
                    or event.boundary.transition_id != source.boundary.transition_id
                    or event.boundary.source_generation != source.boundary.source_generation
                    or event.boundary.retired_members
                    or event.observed_at > now
                    or event.boundary.observation is None
                    or not event.boundary.observation.readable
                    or event.boundary.observation.cinematic
                    or not event.boundary.observation.outpost
                    or event.boundary.observation.explorable
                    or not all(event.boundary.observation.loading.contexts)
                    or event.boundary.observation.loading.raw_instance_type != 0
                    or event.boundary.observation.map_id != inputs.opening.map_id
                    or event.boundary.observation.character_identity
                    != (inputs.opening.local_account_email, inputs.opening.local_character_name)
                    or event.boundary.observation.character_uuid != inputs.opening.local_character_uuid
                    for index, event in enumerate(tail, 1)
                )
            ):
                raise RuntimeError("owner source observation integrity invalid")
            self._stage3_proof_retention = _Stage3ProofRetention(
                session, attempt_id, deadline, source, cursor, (source,)
            )
            self._stage3_retention_started = True

    def _stage3_proof_is_retained(self, proof: Stage3OwnerEvidence, retention: _Stage3ProofRetention | None) -> bool:
        # A present sequence must still name the exact issued object. A protected
        # anchor may outlive eviction, but never a replacement of that sequence.
        present = next((event for event in self._stage3_evidence if event.sequence == proof.sequence), None)
        if present is not None:
            return present is proof
        return retention is not None and any(event is proof for event in retention.anchors)

    @staticmethod
    def _stage3_destination_event_matches(event: Stage3OwnerEvidence, closing: Stage3OwnerEvidence) -> bool:
        inputs, boundary = closing.verification, closing.boundary
        observation = event.boundary.observation
        return (
            inputs is not None
            and event.kind in ("completion", "observation")
            and (event.kind != "observation" or event.snapshot is closing.snapshot)
            and event.snapshot.ready
            and event.snapshot.lifecycle_epoch == closing.snapshot.lifecycle_epoch
            and event.snapshot.map_id == closing.snapshot.map_id
            and (event.kind != "completion" or event.verification is not None)
            and (
                event.kind != "completion"
                or (
                    event.decision is not None
                    and closing.decision is not None
                    and event.decision.decision.session is closing.decision.decision.session
                )
            )
            and event.boundary.transition_id == boundary.transition_id
            and event.boundary.source_generation == boundary.source_generation
            and event.boundary.lifecycle_generation == boundary.lifecycle_generation
            and event.boundary.destination == boundary.destination
            and event.boundary.loading is boundary.loading
            and event.boundary.deadline == boundary.deadline
            and event.boundary.phase is TransitionPhase.DESTINATION_VERIFIED
            and not event.boundary.retired_members
            and observation is not None
            and observation.readable
            and not observation.cinematic
            and observation.explorable
            and not observation.outpost
            and all(observation.loading.contexts)
            and observation.loading.raw_instance_type == 1
            and observation.map_id == inputs.opening.map_id
            and observation.character_identity
            == (inputs.opening.local_account_email, inputs.opening.local_character_name)
            and observation.character_uuid == inputs.opening.local_character_uuid
        )

    def RetainStage3Proofs(
        self,
        session: object,
        attempt_id: int,
        after_sequence: int,
        watermark: int,
        history: tuple[Stage3OwnerEvidence, ...],
        samples: tuple[Stage3OwnerEvidence, ...],
        latest: Stage3OwnerEvidence | None,
        acknowledge: Callable[[], bool],
    ) -> bool:
        """Authenticate a processed contiguous batch before protecting at most seven anchors.

        Lock order is owner -> recorder. No runtime reads, recognition, or event
        retention are added. The streak reduction preserves the final verifier's
        ordered checks even when already-accounted-for events leave the ring.
        """
        if self._stage3_evidence_lock is None:
            return False
        with self._stage3_evidence_lock:
            self._expire_stage3_retention()
            retention = self._stage3_proof_retention
            if (
                retention is None
                or retention.session is not session
                or retention.attempt_id != attempt_id
                or not self.OwnsStage3DecisionSession(session)
                or self._stage3_evidence_failed
                or after_sequence != retention.cursor
                or not after_sequence <= watermark <= self._stage3_evidence_sequence
                or len(history) > 3
                or len(samples) > 3
            ):
                return False
            events = tuple(event for event in self._stage3_evidence if after_sequence < event.sequence <= watermark)
            if len(events) != watermark - after_sequence or any(
                event.sequence != after_sequence + index for index, event in enumerate(events, 1)
            ):
                # This attempt can never acknowledge its way past a lost event.
                self._stage3_proof_retention = None
                return False
            anchors: list[Stage3OwnerEvidence] = [retention.source]
            for proof in (*history, *samples, *((latest,) if latest is not None else ())):
                if (
                    proof.sequence > watermark
                    or not self._stage3_proof_is_retained(proof, retention)
                    or proof.boundary.transition_id != retention.source.boundary.transition_id
                    or proof.boundary.source_generation != retention.source.boundary.source_generation
                ):
                    return False
                if not any(anchor is proof for anchor in anchors):
                    anchors.append(proof)
            if len(anchors) > 7:
                return False
            same_streak = bool(samples and retention.samples and samples[0] is retention.samples[0])
            if samples and not same_streak and samples[0].sequence <= retention.cursor:
                return False
            streak_valid = retention.streak_valid if same_streak else True
            if samples:
                if latest is None or latest.sequence < samples[-1].sequence:
                    return False
                streak_valid = streak_valid and all(
                    self._stage3_destination_event_matches(event, latest)
                    for event in (*samples, *(event for event in events if event.sequence >= samples[0].sequence))
                )
            if not acknowledge():
                return False
            self._stage3_proof_retention = replace(
                retention, cursor=watermark, anchors=tuple(anchors), samples=samples, streak_valid=streak_valid
            )
            return True

    def InspectStage3Readiness(self, session: object, attempt_id: int, source: Stage3OwnerEvidence) -> str:
        if self._stage3_evidence_lock is None:
            return "owner_synchronization_unavailable"
        with self._stage3_evidence_lock:
            self._expire_stage3_retention()
            retention = self._stage3_proof_retention
            if (
                retention is None
                or retention.session is not session
                or retention.attempt_id != attempt_id
                or retention.source is not source
                or not self.OwnsStage3DecisionSession(session)
            ):
                return "attempt_binding_changed"
            proof, reason = self.InspectStage3Outpost(source.snapshot)
            if proof is not source:
                return reason if proof is None else "completed_outpost_proof_changed"
            if retention.cursor != self._stage3_evidence_sequence:
                return "unprocessed_owner_events"
            transition, now = self._transition, _transition_clock()
            if transition is None:
                return "outpost_association_unavailable"
            if transition.deadline is not None and now >= transition.deadline:
                return "production_transition_expired"
            if transition.started_at is None and not 0.0 <= now - transition.verified_at <= 5.0:
                return "outpost_verification_expired"
            return "ready"

    def BindStage3Outpost(self, snapshot: CleansingContextSnapshot) -> Stage3OwnerEvidence | None:
        proof, _reason = self.InspectStage3Outpost(snapshot)
        return proof

    def InspectStage3Outpost(self, snapshot: CleansingContextSnapshot) -> tuple[Stage3OwnerEvidence | None, str]:
        """Explain refusal using the same synchronized checks used by arming."""
        if self._stage3_evidence_lock is None:
            return None, "owner_synchronization_unavailable"
        with self._stage3_evidence_lock:
            if self._stage3_evidence_failed:
                return None, "owner_evidence_capture_failed"
            event = next((item for item in reversed(self._stage3_evidence) if item.kind == "completion"), None)
            if self._stage3_mutations:
                return None, "owner_refresh_in_progress"
            if event is None:
                return None, "completed_outpost_proof_missing"
            if event.snapshot is not snapshot or snapshot is not self._snapshot:
                return None, "completed_outpost_snapshot_replaced"
            if not snapshot.ready:
                return None, "completed_outpost_not_ready"
            if event.verification is None:
                return None, "completed_outpost_verification_missing"
            if event.boundary.retired_members or self._boundary.retired_members:
                return None, "original_outpost_proof_retired"
            if (
                event.boundary.phase is not TransitionPhase.OUTPOST_READY
                or self._boundary.phase is not TransitionPhase.OUTPOST_READY
            ):
                return None, "owner_not_in_verified_outpost"
            if (
                event.boundary.transition_id != self._boundary.transition_id
                or event.boundary.source_generation != self._boundary.source_generation
            ):
                return None, "original_outpost_association_changed"
            return event, "verified_outpost"

    def ArmStage3Outpost(
        self,
        snapshot: CleansingContextSnapshot,
        arm: Callable[[Stage3OwnerEvidence, int], int | None],
        refuse: Callable[[str], None] | None = None,
    ) -> int | None:
        if self._stage3_evidence_lock is None:
            if refuse is not None:
                refuse("owner_synchronization_unavailable")
            return None
        with self._stage3_evidence_lock:
            proof, reason = self.InspectStage3Outpost(snapshot)
            if proof is None and refuse is not None:
                refuse(reason)
            return arm(proof, self._stage3_evidence_sequence) if proof is not None else None

    def VerifyStage3Destination(
        self,
        third: Stage3OwnerEvidence,
        watermark: int,
        session: object,
        commit: Callable[[], bool],
        *,
        history: tuple[Stage3OwnerEvidence, ...] = (),
        samples: tuple[Stage3OwnerEvidence, ...] = (),
        diagnostic: Stage3FinalVerificationDiagnostic | None = None,
    ) -> bool:
        """Recheck the latest retained completion against an unchanged current owner.

        Lock order is owner evidence -> recorder. Runtime and Native reads occur
        outside both locks. The callback may only freeze a diagnostic verdict.
        ``third`` retains its public parameter name for compatibility; it is the
        closing anchor, which may follow the three historical counted samples.
        """
        diagnostic = diagnostic if diagnostic is not None else Stage3FinalVerificationDiagnostic()
        diagnostic.stage = "owner"
        if self._stage3_evidence_lock is None:
            return diagnostic.reject("owner", "synchronization_unavailable")
        with self._stage3_evidence_lock:
            self._expire_stage3_retention()
            retention = self._stage3_proof_retention
            inputs = third.verification
            boundary = self._boundary
            generation = self._stage3_generation
            retained = tuple(self._stage3_evidence)
            candidates = (*retained, *(retention.anchors if retention is not None else ()))
            latest = max(
                (event for event in candidates if event.kind == "completion"),
                key=lambda event: event.sequence,
                default=None,
            )
            diagnostic.inputs_current = inputs is not None and inputs is self._stage3_closing_inputs
            diagnostic.watermark_current = watermark == self._stage3_evidence_sequence
            diagnostic.session_current = self.OwnsStage3DecisionSession(session)
            if self._stage3_mutations:
                return diagnostic.reject("owner", "mutation_in_progress")
            if self._stage3_evidence_failed or not diagnostic.watermark_current:
                return diagnostic.reject("evidence", "capture_or_watermark")
            if not self._stage3_proof_is_retained(third, retention) or any(
                not self._stage3_proof_is_retained(proof, retention) for proof in (*history, *samples)
            ):
                return diagnostic.reject("evidence", "proof_not_retained")
            if (
                retention is None
                or retention.session is not session
                or retention.cursor != watermark
                or len(samples) != 3
                or len(retention.samples) != 3
                or any(first is not second for first, second in zip(samples, retention.samples))
            ):
                return diagnostic.reject("evidence", "retention_binding_or_cursor")
            if not retention.streak_valid:
                return diagnostic.reject("evidence", "incompatible_observation")
            if inputs is None:
                return diagnostic.reject("owner", "verification_inputs_missing")
            if latest is not third or third.kind != "completion":
                return diagnostic.reject("owner", "latest_completion_replaced")
            if (
                third.snapshot is not self._snapshot
                or not third.snapshot.ready
                or third.decision is None
                or third.decision is not self._stage3_decision_result
                or third.decision.decision.session is not session
                or self._stage3_decision_active is not None
                or third.boundary.completed_refresh != boundary.completed_refresh
                or third.boundary.transition_id != boundary.transition_id
                or third.boundary.source_generation != boundary.source_generation
                or third.boundary.lifecycle_generation != boundary.lifecycle_generation
                or third.boundary.destination != boundary.destination
                or third.boundary.loading is not boundary.loading
                or third.boundary.deadline != boundary.deadline
                or third.boundary.phase is not TransitionPhase.DESTINATION_VERIFIED
                or boundary.phase is not TransitionPhase.DESTINATION_VERIFIED
                or third.boundary.retired_members
                or boundary.retired_members
                or inputs.opening.instance_type != 1
                or inputs.opening.map_signature != boundary.destination
                or dict(third.local) != self._baselines
                or dict(third.remote) != self._remote_player_baselines
            ):
                return diagnostic.reject("owner", "current_binding")
            if not diagnostic.session_current:
                return diagnostic.reject("recorder", "owner_session_replaced")
            # Working inputs are disposable. Check the whole counted streak so
            # a later valid completion cannot hide an intervening ambiguity.
            first_sequence = samples[0].sequence if samples else third.sequence
            ordered = tuple(event for event in retained if event.sequence >= first_sequence)
            # The owner-authenticated cursor covers evicted processed events;
            # unread gaps cannot advance it. Recheck all still-present events.
            for event in ordered:
                observation = event.boundary.observation
                if (
                    event.kind not in ("completion", "observation")
                    or (event.sequence > third.sequence and event.kind != "observation")
                    or (event.sequence >= third.sequence and event.snapshot is not third.snapshot)
                    or not event.snapshot.ready
                    or event.snapshot.lifecycle_epoch != third.snapshot.lifecycle_epoch
                    or event.snapshot.map_id != third.snapshot.map_id
                    or (event.kind == "completion" and event.verification is None)
                    or event.boundary.transition_id != boundary.transition_id
                    or event.boundary.source_generation != boundary.source_generation
                    or event.boundary.lifecycle_generation != boundary.lifecycle_generation
                    or event.boundary.destination != boundary.destination
                    or event.boundary.loading is not boundary.loading
                    or event.boundary.deadline != boundary.deadline
                    or event.boundary.phase is not TransitionPhase.DESTINATION_VERIFIED
                    or event.boundary.retired_members
                    or observation is None
                    or not observation.readable
                    or observation.cinematic
                    or not observation.explorable
                    or observation.outpost
                    or not all(observation.loading.contexts)
                    or observation.loading.raw_instance_type != 1
                    or observation.map_id != inputs.opening.map_id
                    or observation.character_identity
                    != (inputs.opening.local_account_email, inputs.opening.local_character_name)
                    or observation.character_uuid != inputs.opening.local_character_uuid
                ):
                    return diagnostic.reject("evidence", "incompatible_observation")
            if (
                generation != self._stage3_generation
                or boundary is not self._boundary
                or watermark != self._stage3_evidence_sequence
            ):
                return diagnostic.reject("commit", "capture_changed")
        try:
            diagnostic.stage = "runtime"
            from Py4GWCoreLib import Agent, GLOBAL_CACHE
            from Py4GWCoreLib.enums_src.GameData_enums import SkillType
            import PySkillbar

            opening = inputs.opening
            get_hero = cast(Callable[[int], int], getattr(GLOBAL_CACHE.Party.Heroes, "GetHeroAgentIDByPartyPosition"))
            decision = _Stage3DecisionCapture(session, 0)

            def close_runtime() -> _ClosingVerification:
                diagnostic.stage = "runtime"
                result = self._recheck_final_runtime(
                    opening=opening,
                    local_reads=inputs.local_reads,
                    native_skillbar=PySkillbar.Skillbar(),
                    get_hero_agent_id=get_hero,
                    agent_api=Agent,
                    owner_proofs=inputs.owners,
                    hero_proofs=inputs.hero_proofs,
                )
                if result is not _ClosingVerification.COHERENT:
                    diagnostic.reject("runtime", result.value)
                diagnostic.stage = "native"
                return result

            result = self._recheck_remote_evidence(
                opening_players=inputs.players,
                opening_heroes=inputs.heroes,
                opening_henchmen=opening.henchmen,
                opening_party_size=opening.party_size,
                opening_party_id=opening.party_id,
                opening_map_id=opening.map_id,
                opening_map_signature=opening.map_signature,
                opening_instance_type=opening.instance_type,
                opening_character_identity=(opening.local_account_email, opening.local_character_name),
                opening_character_uuid=opening.local_character_uuid,
                opening_hwnd=opening.local_hwnd,
                opening_local_agent_id=opening.local_agent_id,
                opening_local_login_number=opening.local_login_number,
                owner_proofs=inputs.owners,
                hero_proofs=inputs.hero_proofs,
                local_witness_reads=inputs.witness_reads,
                opening_captured_at_tick64=inputs.captured_at_tick64,
                skill_api=GLOBAL_CACHE.Skill,
                skill_type_attack=int(SkillType.Attack),
                role_skill_ids=inputs.role_skill_ids,
                current_tick=0,
                read_only=True,
                final_runtime=close_runtime,
                decision=decision,
                final_diagnostic=diagnostic,
            )
            if result is not _ClosingVerification.COHERENT:
                stage = (
                    "runtime"
                    if result
                    in (_ClosingVerification.RUNTIME_CHANGED, _ClosingVerification.CONTROLLED_IDENTITY_CHANGED)
                    else "native"
                )
                return diagnostic.reject(stage, decision.failure[0] if decision.failure[0] != "NONE" else result.value)
        except Exception:
            return diagnostic.reject(diagnostic.stage, "exception")
        diagnostic.stage = "commit"
        with self._stage3_evidence_lock:
            diagnostic.watermark_current = watermark == self._stage3_evidence_sequence
            diagnostic.session_current = self.OwnsStage3DecisionSession(session)
            if self._stage3_mutations or generation != self._stage3_generation:
                return diagnostic.reject("commit", "owner_generation_changed")
            if watermark != self._stage3_evidence_sequence or self._stage3_evidence_failed:
                return diagnostic.reject("commit", "owner_watermark_changed")
            if self._stage3_proof_retention is not retention or _transition_clock() >= retention.deadline:
                self._expire_stage3_retention()
                return diagnostic.reject("commit", "retention_changed_or_expired")
            if boundary is not self._boundary or third.snapshot is not self._snapshot:
                return diagnostic.reject("commit", "owner_binding_changed")
            if third.decision is not self._stage3_decision_result or not self.OwnsStage3DecisionSession(session):
                return diagnostic.reject("commit", "owner_session_changed")
            return commit()

    def SetStage3DecisionSession(self, session: object | None) -> None:
        """TEMPORARY recorder-owned opt-in; no runtime reads or recognition effects."""
        if self._stage3_session_lock is None or self._stage3_evidence_lock is None:
            raise RuntimeError("decision session unavailable")
        with self._stage3_evidence_lock, self._stage3_session_lock:
            self._stage3_proof_retention = None
            self._stage3_retention_started = False
            self._stage3_decision_session = session
            self._stage3_decision_active = None
            self._stage3_decision_result = None
            self._stage3_decision_status = "UNAVAILABLE"

    def GetStage3DecisionBinding(self) -> Stage3DecisionBinding | None:
        return self._stage3_decision_result

    def OwnsStage3DecisionSession(self, session: object) -> bool:
        if self._stage3_session_lock is None:
            return False
        with self._stage3_session_lock:
            return self._stage3_decision_session is session

    def RetireStage3DecisionSession(self, session: object) -> None:
        if self._stage3_session_lock is None or self._stage3_evidence_lock is None:
            return
        with self._stage3_evidence_lock, self._stage3_session_lock:
            if self._stage3_decision_session is session:
                self._stage3_proof_retention = None
                self._stage3_decision_session = None
                self._stage3_decision_active = None
                self._stage3_decision_result = None
                self._stage3_decision_status = "UNAVAILABLE"

    def ResolveStage3Decision(
        self,
        binding: Stage3DecisionBinding | None,
        snapshot: CleansingContextSnapshot,
        local: tuple[tuple[tuple[MemberKind, int, int], object], ...],
        remote: tuple[tuple[tuple[MemberKind, int, int], object], ...],
    ) -> tuple[Stage3RefreshDecision | None, str]:
        if len(local) > 8 or len(remote) > 8:
            return None, "UNAVAILABLE"
        if binding is not None:
            if (
                binding is self._stage3_decision_result
                and self._stage3_decision_active is None
                and binding.snapshot is snapshot is self._snapshot
                and binding.decision.session is self._stage3_decision_session
                and binding.decision.sequence == self._stage3_decision_sequence
                and dict(binding.local) == dict(local)
                and dict(binding.remote) == dict(remote)
                # Recheck after comparisons, which may invoke reentrant callbacks.
                and binding is self._stage3_decision_result
                and binding.decision.sequence == self._stage3_decision_sequence
                and binding.decision.session is self._stage3_decision_session
            ):
                return binding.decision, "EXACT"
            return None, "AMBIGUOUS"
        return None, (
            "AMBIGUOUS"
            if self._stage3_decision_active is not None or self._stage3_decision_status == "AMBIGUOUS"
            else "UNAVAILABLE"
        )

    def _stage3_complete_decision(self, capture: _Stage3DecisionCapture | None, snapshot: CleansingContextSnapshot) -> None:
        try:
            if capture is None or capture.session is not self._stage3_decision_session:
                return
            if capture.failed:
                self._stage3_decision_result = None
                self._stage3_decision_active = None
                self._stage3_decision_status = "UNAVAILABLE"
                return
            if capture.sequence != self._stage3_decision_sequence or self._stage3_decision_active is not capture:
                self._stage3_decision_result = None
                self._stage3_decision_status = "AMBIGUOUS"
                return
            if len(snapshot.members) > 8 or len(self._baselines) > 8 or len(self._remote_player_baselines) > 8:
                self._stage3_decision_result = None
                self._stage3_decision_status = "UNAVAILABLE"
                return
            local = tuple(member for member in snapshot.members if member.evidence_source is EvidenceSource.LOCAL_HERO)
            committed = sum(
                member.role is not CleansingRole.UNKNOWN and member.identity.stable_key in self._baselines
                for member in local
            )
            retained = sum(key in self._baselines for key in capture.previous)
            decision = Stage3RefreshDecision(
                capture.session,
                capture.sequence,
                snapshot.revision,
                tuple(capture.paths),
                capture.opening,
                capture.closing,
                capture.failure,
                capture.final,
                (len(capture.previous), committed, retained, len(capture.previous) - retained),
                (
                    int(
                        any(
                            member.evidence_source is EvidenceSource.REMOTE_PLAYER
                            and member.role is not CleansingRole.UNKNOWN
                            for member in snapshot.members
                        )
                    ),
                    int(
                        any(
                            member.evidence_source is EvidenceSource.REMOTE_HERO
                            and member.role is not CleansingRole.UNKNOWN
                            for member in snapshot.members
                        )
                    ),
                ),
            )
            self._stage3_decision_result = Stage3DecisionBinding(
                snapshot, decision, tuple(self._baselines.items()), tuple(self._remote_player_baselines.items())
            )
            self._stage3_decision_status = "EXACT"
            self._stage3_decision_active = None
        except Exception:
            self._stage3_decision_result = None
            self._stage3_decision_active = None
            self._stage3_decision_status = "UNAVAILABLE"

    def GetSnapshot(self) -> CleansingContextSnapshot:
        return self._snapshot

    def GetMember(self, identity: MemberIdentity) -> MemberRecord | None:
        return self._snapshot.get_member(identity)

    def CaptureEnvironment(self) -> EnvironmentObservation:
        import PyParty

        from Py4GWCoreLib import Map, Player
        from Py4GWCoreLib.Context import GWContext

        loading = Map.GetLoadingObservation()
        map_ready = all(loading.contexts) and loading.raw_instance_type in (0, 1) and bool(Map.IsMapReady())
        cinematic = bool(Map.IsInCinematic()) if map_ready else False
        identity = None
        uuid = None
        # Identity contradictions remain observable even if a different context is absent.
        if loading.contexts[1]:
            char = GWContext.Char.GetContext()
            if char is not None:
                identity = (
                    str(char.player_email_str or "").strip().casefold(),
                    str(char.player_name_str or "").strip(),
                )
                uuid = _copy_uuid(char.player_uuid)
        return EnvironmentObservation(
            loading,
            map_ready
            and not cinematic
            and identity is not None
            and all(identity)
            and uuid is not None
            and any(uuid)
            and bool(Player.IsPlayerLoaded())
            # Retained PartyCache readiness cannot gate the update that refreshes it.
            and PyParty.get_is_party_loaded() is True,
            cinematic,
            int(Map.GetMapID()) if map_ready else None,
            map_ready and loading.raw_instance_type == 0,
            map_ready and loading.raw_instance_type == 1,
            identity,
            uuid,
        )

    def GetTransitionBoundary(self) -> TransitionBoundary:
        return self._boundary

    def ObserveCurrentEnvironment(self) -> TransitionBoundary:
        try:
            return self.ObserveEnvironment(self.CaptureEnvironment())
        except Exception:
            return self.RejectEnvironmentObservation()

    def RejectEnvironmentObservation(self) -> TransitionBoundary:
        with self._stage3_mutation(commit_only=True):
            self._observation_sequence += 1
            self._environment = None
            self.Invalidate("environment observation is malformed or failed")
            return self._update_transition_boundary()

    @property
    def _candidate_local(self) -> dict[tuple[MemberKind, int, int], _Baseline]:
        return self._staged_evidence[0] if self._staged_evidence is not None else self._baselines

    @property
    def _candidate_remote(self) -> dict[tuple[MemberKind, int, int], _RemotePlayerBaseline]:
        return self._staged_evidence[1] if self._staged_evidence is not None else self._remote_player_baselines

    @property
    def _candidate_origins(self) -> dict[tuple[MemberKind, int, int], _LocalWitnessOrigin]:
        return self._staged_evidence[2] if self._staged_evidence is not None else self._remote_hero_origins

    def _commit_evidence(self) -> None:
        if self._staged_evidence is not None:
            self._baselines, self._remote_player_baselines, self._remote_hero_origins = self._staged_evidence
            self._staged_evidence = None

    def _discard_provisional_admissions(self) -> None:
        # Roll back only staged admissions that still have a live source candidate.
        # A removed/contradictory publisher has no staged association to roll back.
        for key, baseline in self._remote_player_baselines.items():
            if baseline.destination_map_id is not None:
                continue
            provisional = tuple(
                candidate_key
                for candidate_key, candidate in self._candidate_remote.items()
                if candidate.publisher == baseline.publisher and candidate.destination_map_id is not None
            )
            if provisional:
                for candidate_key in provisional:
                    self._candidate_remote.pop(candidate_key, None)
                self._candidate_remote[key] = baseline

    def _update_transition_boundary(self, kind: str = "observation") -> TransitionBoundary:
        transition = self._transition
        self._boundary = TransitionBoundary(
            self._observation_sequence,
            self._completed_refresh,
            transition.identifier if transition is not None else self._transition_counter,
            self._lifecycle_epoch,
            self._transition_phase,
            self._environment,
            transition.loading if transition is not None else None,
            transition.deadline if transition is not None else None,
            transition.generation if transition is not None else None,
            transition.destination if transition is not None else None,
            self._snapshot.revision,
            transition.retired if transition is not None else frozenset(),
            self._completed_at,
        )
        if self._stage3_evidence_lock is None:
            return self._boundary
        with self._stage3_evidence_lock:
            self._expire_stage3_retention()
            retention = self._stage3_proof_retention
            if retention is not None and (
                self._boundary.phase is TransitionPhase.RETIRED
                or self._boundary.retired_members
                or self._boundary.transition_id != retention.source.boundary.transition_id
                or self._boundary.source_generation != retention.source.boundary.source_generation
            ):
                self._stage3_proof_retention = None
            self._stage3_evidence_sequence += 1
            try:
                if (
                    self._stage3_evidence_failed
                    or max(len(self._snapshot.members), len(self._baselines), len(self._remote_player_baselines)) > 8
                ):
                    self._stage3_evidence_failed = True
                    return self._boundary
                self._stage3_evidence.append(
                    Stage3OwnerEvidence(
                        self._stage3_evidence_sequence,
                        kind,
                        self._boundary,
                        self._snapshot,
                        tuple(self._baselines.items()),
                        tuple(self._remote_player_baselines.items()),
                        self._stage3_closing_inputs if kind == "completion" else None,
                        self._stage3_decision_result if kind == "completion" else None,
                        _transition_clock(),
                    )
                )
            except Exception:
                # Passive evidence must not turn a diagnostic allocation fault
                # into a recognition failure. Its missing order is permanent.
                self._stage3_evidence_failed = True
        return self._boundary

    def _retire_transition(self, *, preserve_stage2: bool = False) -> None:
        self._transition_phase = TransitionPhase.RETIRED
        self._transition = None
        independent = (
            {key: value for key, value in self._candidate_local.items() if value.witness_origin is None}
            if preserve_stage2
            else {}
        )
        self._baselines.clear()
        self._remote_player_baselines.clear()
        self._remote_hero_origins.clear()
        self._candidate_local.clear()
        self._candidate_remote.clear()
        self._candidate_origins.clear()
        self._candidate_local.update(independent)
        self._pending_outpost_transition = False
        self._pending_remote_outpost_transition = False

    def _waiting_for_admission(self) -> bool:
        return self._transition_phase in (
            TransitionPhase.WAITING_FOR_LOADING,
            TransitionPhase.LOADING_CONFIRMED,
            TransitionPhase.DESTINATION_PENDING,
        )

    def _begin_waiting(self) -> None:
        transition = self._transition
        if transition is None or self._transition_phase is not TransitionPhase.OUTPOST_READY:
            return
        now = self._environment.loading.observed_at if self._environment is not None else 0.0
        if transition.started_at is None:
            if not 0.0 <= now - transition.verified_at <= 5.0:
                self._retire_transition()
                return
            self._transition = replace(transition, started_at=now, deadline=now + 60.0)
        self._transition_phase = TransitionPhase.WAITING_FOR_LOADING
        self._pending_outpost_transition = True

    def _retain_remote_candidate(self, key: tuple[MemberKind, int, int]) -> bool:
        baseline = self._candidate_remote.get(key)
        return self._waiting_for_admission() and baseline is not None and baseline.destination_map_id is None

    def _retain_local_candidate(self, key: tuple[MemberKind, int, int]) -> bool:
        baseline = self._candidate_local.get(key)
        return (
            self._waiting_for_admission()
            and baseline is not None
            and (baseline.witness_origin is None or baseline.witness_origin.destination_epoch is None)
        )

    def _retire_publisher(self, publisher: _PublisherToken) -> None:
        transition = self._transition
        if transition is not None:
            keys = {key for key, baseline in transition.remote if baseline.publisher == publisher}
            keys.update(key for key, origin in transition.origins if origin.publisher == publisher)
            keys.update(
                key
                for key, baseline in transition.local
                if baseline.witness_origin is not None and baseline.witness_origin.publisher == publisher
            )
            self._transition = replace(transition, retired=transition.retired | keys)
        for key, baseline in tuple(self._candidate_remote.items()):
            if baseline.publisher == publisher:
                self._candidate_remote.pop(key, None)
        for key, origin in tuple(self._candidate_origins.items()):
            if origin.publisher == publisher:
                self._candidate_origins.pop(key, None)
        for key, baseline in tuple(self._candidate_local.items()):
            if baseline.witness_origin is not None and baseline.witness_origin.publisher == publisher:
                self._candidate_local.pop(key, None)

    def _retire_hero_candidate(self, identity: MemberIdentity, publisher: _PublisherToken | None = None) -> None:
        transition = self._transition
        if transition is not None:
            keys = {key for key, _ in transition.local if key == identity.stable_key}
            keys.update(
                key
                for key, origin in transition.origins
                if key == identity.stable_key
                or (origin.publisher == publisher and origin.witness.hero_id == identity.member_id)
            )
            self._transition = replace(transition, retired=transition.retired | keys)
        self._candidate_local.pop(identity.stable_key, None)
        for key, origin in tuple(self._candidate_origins.items()):
            if key == identity.stable_key or (
                publisher is not None and origin.publisher == publisher and origin.witness.hero_id == identity.member_id
            ):
                self._candidate_origins.pop(key, None)

    def _check_historical_publishers(self, cohorts: tuple[_PublishedCohort, ...], recovery_epoch: int) -> None:
        transition = self._transition
        if transition is None:
            return
        if any(token.recovery_epoch != recovery_epoch for token in transition.publishers):
            self._retire_transition(preserve_stage2=True)
            return
        for token in transition.publishers:
            matches = tuple(
                cohort
                for cohort in cohorts
                if cohort.owner.account_email.strip().casefold() == token.account_email
                or cohort.owner.key_hwnd == token.hwnd
                or cohort.character_uuid == token.character_uuid
                or cohort.incarnation == token.incarnation
            )
            if len(matches) > 1 or any(_publisher_token(cohort, recovery_epoch) != token for cohort in matches):
                self._retire_publisher(token)

    def _complete_transition(
        self,
        opening: _ClosingState,
        cohorts: tuple[_PublishedCohort, ...],
        recovery_epoch: int,
        snapshot_ready: bool,
        publication_valid: bool,
        members: tuple[MemberRecord, ...],
    ) -> None:
        transition = self._transition
        if (
            transition is not None
            and transition.deadline is not None
            and self._waiting_for_admission()
            and _transition_clock() >= transition.deadline
        ):
            self._retire_transition(preserve_stage2=True)
            return
        if not snapshot_ready:
            return
        if opening.instance_type == 0:
            if transition is not None and transition.started_at is not None:
                publishers = {_publisher_token(cohort, recovery_epoch) for cohort in cohorts}
                if opening != transition.source:
                    self._retire_transition(preserve_stage2=True)
                    return
                retired = set(transition.retired)
                retired.update(key for key, baseline in transition.local if self._candidate_local.get(key) != baseline)
                retired.update(
                    key for key, baseline in transition.remote if self._candidate_remote.get(key) != baseline
                )
                retired.update(key for key, origin in transition.origins if self._candidate_origins.get(key) != origin)
                for key in retired:
                    self._candidate_local.pop(key, None)
                    self._candidate_remote.pop(key, None)
                    self._candidate_origins.pop(key, None)
                self._transition = transition = replace(transition, retired=frozenset(retired))
                keys = {key for key, _ in (*transition.local, *transition.remote, *transition.origins)} - retired
                fresh_keys = {
                    member.identity.stable_key for member in members if member.role is not CleansingRole.UNKNOWN
                }
                active_publishers = {baseline.publisher for key, baseline in transition.remote if key not in retired}
                active_publishers.update(origin.publisher for key, origin in transition.origins if key not in retired)
                active_publishers.update(
                    baseline.witness_origin.publisher
                    for key, baseline in transition.local
                    if key not in retired and baseline.witness_origin is not None
                )
                if (
                    not keys <= fresh_keys
                    or not active_publishers.issubset(publishers)
                    or (not publication_valid and active_publishers)
                ):
                    return
                # Recovery keeps the first deadline, even across repeated readiness losses.
                self._transition_phase = TransitionPhase.OUTPOST_READY
            elif self._candidate_local or self._candidate_remote or self._candidate_origins:
                if transition is None:
                    self._transition_counter += 1
                self._transition = _Transition(
                    self._transition_counter,
                    self._lifecycle_epoch,
                    opening,
                    _transition_clock(),
                    tuple(self._candidate_local.items()),
                    tuple(self._candidate_remote.items()),
                    tuple(self._candidate_origins.items()),
                    tuple(
                        dict.fromkeys(
                            [baseline.publisher for baseline in self._candidate_remote.values()]
                            + [origin.publisher for origin in self._candidate_origins.values()]
                            + [
                                baseline.witness_origin.publisher
                                for baseline in self._candidate_local.values()
                                if baseline.witness_origin is not None
                            ]
                        )
                    ),
                )
                self._transition_phase = TransitionPhase.OUTPOST_READY
        elif transition is not None and self._waiting_for_admission():
            admitted = set(transition.admitted)
            retired = set(transition.retired)
            for key, baseline in transition.local:
                current = self._candidate_local.get(key)
                if current is None:
                    retired.add(key)
                elif current.witness_origin is None or current.witness_origin.destination_epoch is not None:
                    admitted.add(key)
            for key, baseline in transition.remote:
                matching = tuple(
                    value for value in self._candidate_remote.values() if value.publisher == baseline.publisher
                )
                if not matching:
                    retired.add(key)
                elif any(value.destination_map_id is not None for value in matching):
                    admitted.add(key)
            for key, origin in transition.origins:
                matching_origins = tuple(
                    value
                    for value in self._candidate_origins.values()
                    if value.publisher == origin.publisher and value.witness.hero_id == origin.witness.hero_id
                )
                if not matching_origins:
                    retired.add(key)
                elif any(value.destination_epoch is not None for value in matching_origins):
                    admitted.add(key)
            self._transition = replace(
                transition,
                destination=opening.map_signature,
                admitted=frozenset(admitted),
                retired=frozenset(retired),
            )
            keys = {key for key, _ in (*transition.local, *transition.remote, *transition.origins)}
            self._transition_phase = (
                TransitionPhase.DESTINATION_VERIFIED
                if keys <= admitted | retired
                else TransitionPhase.DESTINATION_PENDING
            )
        self._pending_outpost_transition = self._waiting_for_admission()
        self._pending_remote_outpost_transition = (
            self._waiting_for_admission() and self._transition is not None and self._transition.loading is not None
        )

    def ObserveEnvironment(self, observation: EnvironmentObservation) -> TransitionBoundary:
        with self._stage3_mutation(commit_only=True):
            self._observation_sequence += 1
            self._environment = observation
            transition = self._transition
            now = observation.loading.observed_at
            if transition is not None:
                identity_changed = (
                    observation.character_identity is not None
                    and all(observation.character_identity)
                    and observation.character_identity
                    != (transition.source.local_account_email, transition.source.local_character_name)
                ) or (
                    observation.character_uuid is not None
                    and any(observation.character_uuid)
                    and observation.character_uuid != transition.source.local_character_uuid
                )
                if (
                    identity_changed
                    or observation.cinematic
                    or (
                        transition.deadline is not None
                        and now >= transition.deadline
                        and self._transition_phase is not TransitionPhase.DESTINATION_VERIFIED
                    )
                ):
                    self._retire_transition(preserve_stage2=observation.cinematic and not identity_changed)
                elif observation.loading.raw_instance_type not in (None, 0, 1, 2):
                    self._retire_transition(preserve_stage2=True)
                elif observation.loading.loading or not observation.readable:
                    if self._transition_phase is TransitionPhase.DESTINATION_VERIFIED or (
                        transition.destination is not None and observation.loading.loading
                    ):
                        self._retire_transition()
                    elif transition.started_at is None:
                        if now - transition.verified_at > 5.0 or now < transition.verified_at:
                            self._retire_transition()
                        else:
                            self._transition = replace(transition, started_at=now, deadline=now + 60.0)
                    if self._transition is not None:
                        if observation.loading.loading:
                            self._transition = replace(
                                self._transition, loading=self._transition.loading or observation.loading
                            )
                            self._transition_phase = TransitionPhase.LOADING_CONFIRMED
                        elif self._transition.loading is None:
                            self._transition_phase = TransitionPhase.WAITING_FOR_LOADING
                elif observation.explorable:
                    if transition.loading is None or (
                        transition.destination is not None and transition.destination[0] != observation.map_id
                    ):
                        self._retire_transition(preserve_stage2=transition.loading is None)
                    elif self._transition_phase is not TransitionPhase.DESTINATION_VERIFIED:
                        self._transition_phase = TransitionPhase.DESTINATION_PENDING
                elif observation.outpost:
                    if transition.loading is not None or observation.map_id != transition.source.map_id:
                        self._retire_transition()
                else:
                    self._retire_transition()
            self._pending_outpost_transition = self._waiting_for_admission()
            self._pending_remote_outpost_transition = (
                self._waiting_for_admission() and self._transition is not None and self._transition.loading is not None
            )
            if not observation.readable:
                self.InvalidatePublishedSnapshot("environment evidence is unavailable; awaiting fresh verification")
            return self._update_transition_boundary()

    def Invalidate(self, reason: str = "context explicitly invalidated") -> CleansingContextSnapshot:
        with self._stage3_mutation(commit_only=True):
            self._retire_transition()
            self._baselines.clear()
            self._remote_player_baselines.clear()
            self._remote_hero_origins.clear()
            self._remote_publisher_generations.clear()
            self._pending_outpost_transition = False
            self._pending_remote_outpost_transition = False
            self._last_hero_agents.clear()
            self._character_identity = None
            self._last_ready_map_id = None
            self._last_ready_was_outpost = False
            snapshot = self.InvalidatePublishedSnapshot(reason)
            self._update_transition_boundary()
            return snapshot

    def InvalidatePublishedSnapshot(
        self, reason: str = "runtime lifecycle is unsafe; awaiting fresh evidence"
    ) -> CleansingContextSnapshot:
        """Hide published proof without runtime reads or discarding transition baselines."""
        with self._stage3_mutation(commit_only=True):
            snapshot = self._publish(
                map_id=None,
                ready=False,
                character_identity=None,
                members=(),
                declared_party_size=None,
                reason=reason,
            )
            if self._stage3_mutations == 1:
                self._update_transition_boundary("invalidation")
            return snapshot

    def InvalidateForEnvironmentGate(
        self,
        *,
        map_loading_observed: bool = False,
        reason: str = "Environment Upkeeper skipped cache refresh because MapValid is false",
    ) -> CleansingContextSnapshot:
        """Record safe loading evidence while keeping runtime reads at the call boundary."""
        # Compatibility only: a caller's boolean cannot manufacture Loading authority.
        self.ObserveCurrentEnvironment()
        return self.InvalidatePublishedSnapshot(reason)

    def Refresh(self, boundary: TransitionBoundary | None = None) -> CleansingContextSnapshot:
        with self._stage3_mutation():
            if self._staged_evidence is not None:
                return self.Invalidate("reentrant recognition Refresh is unsafe")
            if boundary is None:
                boundary = self.ObserveCurrentEnvironment()
            elif boundary is not self._boundary:
                return self.Invalidate("stale environment observation supplied to Refresh")
            capture: _Stage3DecisionCapture | None = None
            if self._stage3_decision_session is not None:
                try:
                    self._stage3_decision_sequence += 1
                    capture = _Stage3DecisionCapture(self._stage3_decision_session, self._stage3_decision_sequence)
                    if len(self._baselines) <= 8:
                        capture.previous = tuple(key for key in self._baselines if key[0] is MemberKind.HERO)
                    self._stage3_decision_active = capture
                    self._stage3_decision_result = None
                except Exception:
                    capture = None
                    self._stage3_decision_active = None
                    self._stage3_decision_result = None
                    self._stage3_decision_status = "UNAVAILABLE"
            self._refresh_diagnostic_attempts = min(
                self._refresh_diagnostic_attempts + 1,
                _REFRESH_DIAGNOSTIC_MAX_COUNTER,
            )
            recognition_generation = self._stage3_generation
            staged = self._staged_evidence
            try:
                with self._recognition_commit_lock:
                    if self._staged_evidence is not None:
                        return self.Invalidate("concurrent recognition Refresh is unsafe")
                    recognition_generation = self._stage3_generation
                    staged = (
                        dict(self._baselines),
                        dict(self._remote_player_baselines),
                        dict(self._remote_hero_origins),
                    )
                    self._staged_evidence = staged
                snapshot = self._refresh_from_runtime()
                with self._recognition_commit_lock:
                    if recognition_generation == self._stage3_generation:
                        self._commit_evidence()
            except Exception as error:
                with self._recognition_commit_lock:
                    if recognition_generation != self._stage3_generation:
                        if self._staged_evidence is staged:
                            self._staged_evidence = None
                        return self._snapshot
                    self._retire_transition()
                    self._staged_evidence = None
                    self._baselines.clear()
                    self._remote_player_baselines.clear()
                    self._remote_hero_origins.clear()
                    self._remote_publisher_generations.clear()
                    self._pending_outpost_transition = False
                    self._pending_remote_outpost_transition = False
                    self._last_hero_agents.clear()
                    self._character_identity = None
                    if not self._snapshot.ready and not self._snapshot.reason.startswith(
                        "runtime evidence read failed"
                    ):
                        self._lifecycle_epoch += 1
                    snapshot = self._publish(
                        map_id=None,
                        ready=False,
                        character_identity=None,
                        members=(),
                        declared_party_size=None,
                        reason=f"runtime evidence read failed ({type(error).__name__})",
                    )
                self._record_refresh_diagnostic(snapshot, "failure", error)
                with self._recognition_commit_lock:
                    if recognition_generation != self._stage3_generation:
                        return self._snapshot
                    _stage3_failure(capture, "REFRESH_READ", "SHARED")
                    try:
                        self._stage3_complete_decision(capture, snapshot)
                    except Exception:
                        self._stage3_decision_result = None
                        self._stage3_decision_active = None
                        self._stage3_decision_status = "UNAVAILABLE"
                    self._completed_refresh += 1
                    self._completed_at = _transition_clock()
                    self._update_transition_boundary("completion")
                return snapshot

            if recognition_generation != self._stage3_generation:
                return self._snapshot if not self._snapshot.ready else snapshot
            self._record_refresh_diagnostic(snapshot, "success")
            with self._recognition_commit_lock:
                if recognition_generation != self._stage3_generation or snapshot is not self._snapshot:
                    if not self._snapshot.ready:
                        return self._snapshot
                    self._stage3_closing_inputs = None
                    if capture is not None:
                        capture.failed = True
                try:
                    self._stage3_complete_decision(capture, snapshot)
                except Exception:
                    self._stage3_decision_result = None
                    self._stage3_decision_active = None
                    self._stage3_decision_status = "UNAVAILABLE"
                self._completed_refresh += 1
                self._completed_at = _transition_clock()
                self._update_transition_boundary("completion")
            return snapshot

    def ReportRefreshDiagnostic(self) -> None:
        """Emit bounded temporary refresh evidence without requesting runtime reads."""
        try:
            self._emit_refresh_diagnostic()
        except Exception:
            pass

    def _record_refresh_diagnostic(
        self,
        snapshot: CleansingContextSnapshot,
        outcome: str,
        error: Exception | None = None,
    ) -> None:
        try:
            self._refresh_diagnostic_window_attempts = min(
                self._refresh_diagnostic_window_attempts + 1,
                _REFRESH_DIAGNOSTIC_MAX_COUNTER,
            )
            if outcome == "success":
                self._refresh_diagnostic_window_successes = min(
                    self._refresh_diagnostic_window_successes + 1,
                    _REFRESH_DIAGNOSTIC_MAX_COUNTER,
                )
            else:
                self._refresh_diagnostic_window_failures = min(
                    self._refresh_diagnostic_window_failures + 1,
                    _REFRESH_DIAGNOSTIC_MAX_COUNTER,
                )
                self._refresh_diagnostic_error_type, self._refresh_diagnostic_failure_site = (
                    self._refresh_failure_details(error)
                )
            self._refresh_diagnostic_last_outcome = outcome
            self._refresh_diagnostic_snapshot = snapshot
            self._emit_refresh_diagnostic()
        except Exception:
            pass

    def _emit_refresh_diagnostic(self) -> None:
        if self._refresh_diagnostic_lines >= _REFRESH_DIAGNOSTIC_MAX_LINES:
            return

        now = _monotonic()
        last_emit = self._refresh_diagnostic_last_emit
        if last_emit is not None and now - last_emit < _REFRESH_DIAGNOSTIC_INTERVAL_SECONDS:
            return

        snapshot = self._refresh_diagnostic_snapshot
        window_attempts = self._refresh_diagnostic_window_attempts
        outcome = self._refresh_diagnostic_last_outcome if window_attempts else "none"
        revision = min(max(int(snapshot.revision), 0), _REFRESH_DIAGNOSTIC_MAX_COUNTER)
        member_count = min(len(snapshot.members), _REFRESH_DIAGNOSTIC_MAX_COUNTER)
        line = (
            "STAGE3_REFRESH_DIAG_V1 "
            f"attempt={self._refresh_diagnostic_attempts} "
            f"window={window_attempts} "
            f"success={self._refresh_diagnostic_window_successes} "
            f"failure={self._refresh_diagnostic_window_failures} "
            f"outcome={outcome} ready={int(snapshot.ready)} "
            f"revision={revision} members={member_count}"
        )
        if outcome == "failure":
            error_type = self._refresh_diagnostic_error_type or "Exception"
            failure_site = self._refresh_diagnostic_failure_site or "unknown:0"
            line += f" error={error_type} site={failure_site}"
        elif outcome == "success" and self._refresh_diagnostic_window_failures:
            error_type = self._refresh_diagnostic_error_type or "Exception"
            failure_site = self._refresh_diagnostic_failure_site or "unknown:0"
            line += f" recovered=1 failure_error={error_type} failure_site={failure_site}"
        line = line[:_REFRESH_DIAGNOSTIC_MAX_LINE_CHARACTERS]

        self._refresh_diagnostic_lines += 1
        self._refresh_diagnostic_last_emit = now
        try:
            import PySystem

            PySystem.Console.Log("CleansingContext", line, PySystem.Console.MessageType.Info)
        except Exception:
            return

        self._refresh_diagnostic_window_attempts = 0
        self._refresh_diagnostic_window_successes = 0
        self._refresh_diagnostic_window_failures = 0
        self._refresh_diagnostic_error_type = None
        self._refresh_diagnostic_failure_site = None

    @staticmethod
    def _refresh_failure_details(error: Exception | None) -> tuple[str, str]:
        try:
            error_type = type(error).__name__ if error is not None else "Exception"
            if not error_type.isidentifier():
                error_type = "Exception"
            error_type = error_type[:48]

            traceback = error.__traceback__ if error is not None else None
            deepest_frame: tuple[str, int] | None = None
            deepest_application_frame: tuple[str, int] | None = None
            while traceback is not None:
                frame = traceback.tb_frame
                function = frame.f_code.co_name
                site = (function if function.isidentifier() else "unknown", traceback.tb_lineno)
                deepest_frame = site
                module_name = frame.f_globals.get("__name__")
                if isinstance(module_name, str) and module_name.startswith("Py4GWCoreLib"):
                    deepest_application_frame = site
                traceback = traceback.tb_next

            function, line = deepest_application_frame or deepest_frame or ("unknown", 0)
            return error_type, f"{function[:64]}:{max(0, int(line))}"
        except Exception:
            return "Exception", "unknown:0"

    def _refresh_from_runtime(self) -> CleansingContextSnapshot:
        # Evaluate on private working state. This is the existing owner's staged
        # transaction, never a published context or another lifecycle authority.
        # Immutable proofs are shared; every mutable recognition map is copied.
        with self._recognition_commit_lock:
            generation, boundary = self._stage3_generation, self._boundary
            work = copy(self)
            work._baselines = dict(self._baselines)
            work._remote_player_baselines = dict(self._remote_player_baselines)
            work._remote_hero_origins = dict(self._remote_hero_origins)
            work._remote_publisher_generations = dict(self._remote_publisher_generations)
            work._last_hero_agents = dict(self._last_hero_agents)
            work._staged_evidence = (
                dict(self._candidate_local),
                dict(self._candidate_remote),
                dict(self._candidate_origins),
            )
        diagnostic_delivery: list[Callable[[], None]] = []
        work._evaluate_refresh_runtime(diagnostic_delivery)
        work._commit_evidence()
        with self._recognition_commit_lock:
            if generation != self._stage3_generation or boundary is not self._boundary:
                self._staged_evidence = None
                return self._snapshot
            self._baselines = work._baselines
            self._remote_player_baselines = work._remote_player_baselines
            self._remote_hero_origins = work._remote_hero_origins
            self._remote_publisher_generations = work._remote_publisher_generations
            self._remote_hero_outpost_seen = work._remote_hero_outpost_seen
            self._role_skill_ids = work._role_skill_ids
            self._character_identity = work._character_identity
            self._last_ready_map_id = work._last_ready_map_id
            self._last_ready_was_outpost = work._last_ready_was_outpost
            self._last_hero_agents = work._last_hero_agents
            self._pending_outpost_transition = work._pending_outpost_transition
            self._pending_remote_outpost_transition = work._pending_remote_outpost_transition
            self._transition = work._transition
            self._transition_phase = work._transition_phase
            self._transition_counter = work._transition_counter
            self._closing_preserve_candidates = work._closing_preserve_candidates
            self._lifecycle_epoch = work._lifecycle_epoch
            self._revision = work._revision
            self._stage3_closing_inputs = work._stage3_closing_inputs
            self._stage3_evidence_failed |= work._stage3_evidence_failed
            self._staged_evidence = None
            self._snapshot = work._snapshot
        for deliver in diagnostic_delivery:
            deliver()
        return work._snapshot

    def _evaluate_refresh_runtime(self, diagnostic_delivery: list[Callable[[], None]]) -> CleansingContextSnapshot:
        global _endpoint_diagnostic_pending
        decision = self._stage3_decision_active
        import PySkillbar

        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import Player
        from Py4GWCoreLib.enums_src.GameData_enums import SkillType

        environment = self._environment
        if environment is None or not environment.readable:
            _stage3_failure(decision, "ENVIRONMENT_GATE", "SHARED")
            return self._publish(
                map_id=self._last_ready_map_id,
                ready=False,
                character_identity=self._character_identity,
                members=(),
                declared_party_size=None,
                reason="map is loading or not ready",
            )

        if Map.IsPVP():
            self._retire_transition()
            _stage3_failure(decision, "OUT_OF_SCOPE", "SHARED")
            if not self._snapshot.ready and self._snapshot.reason != "PvP context is out of scope":
                self._lifecycle_epoch += 1
            self._candidate_local.clear()
            self._candidate_remote.clear()
            self._candidate_origins.clear()
            self._pending_outpost_transition = False
            self._pending_remote_outpost_transition = False
            self._last_ready_map_id = int(Map.GetMapID())
            self._last_ready_was_outpost = False
            self._last_hero_agents.clear()
            self._character_identity = None
            return self._publish(
                map_id=int(Map.GetMapID()),
                ready=False,
                character_identity=None,
                members=(),
                declared_party_size=None,
                reason="PvP context is out of scope",
            )

        map_id = int(Map.GetMapID())
        is_outpost = bool(Map.IsOutpost())
        is_explorable = bool(Map.IsExplorable())
        map_changed = self._last_ready_map_id is not None and map_id != self._last_ready_map_id
        expected_outpost_entry = self._last_ready_was_outpost and is_explorable
        remote_transition_expected = self._pending_remote_outpost_transition and is_explorable
        transition_source_map_id = self._transition.source.map_id if self._transition is not None else None
        if map_changed:
            self._lifecycle_epoch += 1
            if not expected_outpost_entry:
                self._candidate_local.clear()
            if not remote_transition_expected:
                self._candidate_remote.clear()
                self._candidate_origins.clear()
        elif not self._snapshot.ready and not self._pending_outpost_transition and self._transition is None:
            self._candidate_local.clear()
            self._candidate_remote.clear()
            self._candidate_origins.clear()

        if not Player.IsPlayerLoaded() or not GLOBAL_CACHE.Party.IsPartyLoaded():
            _stage3_failure(decision, "PARTY_NOT_LOADED", "SHARED")
            if not expected_outpost_entry:
                self._candidate_local.clear()
            if not remote_transition_expected:
                self._candidate_remote.clear()
                self._candidate_origins.clear()
            self._pending_outpost_transition = expected_outpost_entry
            self._pending_remote_outpost_transition = remote_transition_expected
            self._last_ready_map_id = map_id
            if not expected_outpost_entry:
                self._last_ready_was_outpost = is_outpost
            return self._publish(
                map_id=map_id,
                ready=False,
                character_identity=self._character_identity,
                members=(),
                declared_party_size=None,
                reason="local player or party context is not loaded",
            )

        local_agent_id = int(Player.GetAgentID())
        local_login_number = int(Player.GetLoginNumber())
        account_email = str(Player.GetAccountEmail()).strip().casefold()
        character_name = str(Player.GetName()).strip()
        character_identity = (account_email, character_name)
        if local_agent_id <= 0 or local_login_number <= 0 or not all(character_identity):
            _stage3_failure(decision, "LOCAL_IDENTITY", "LOCAL_OWNER")
            self._candidate_local.clear()
            self._candidate_remote.clear()
            self._candidate_origins.clear()
            self._remote_publisher_generations.clear()
            self._pending_outpost_transition = False
            self._pending_remote_outpost_transition = False
            self._character_identity = None
            self._last_ready_map_id = map_id
            self._last_ready_was_outpost = is_outpost
            self._last_hero_agents.clear()
            return self._publish(
                map_id=map_id,
                ready=False,
                character_identity=None,
                members=(),
                declared_party_size=None,
                reason="local character identity is incomplete",
            )

        if self._character_identity is not None and self._character_identity != character_identity:
            self._candidate_local.clear()
            self._candidate_remote.clear()
            self._candidate_origins.clear()
            self._remote_publisher_generations.clear()
            self._pending_remote_outpost_transition = False
            self._lifecycle_epoch += 1
        self._character_identity = character_identity

        party = GLOBAL_CACHE.Party
        get_players: Callable[[], Iterable[Any]] = getattr(party, "GetPlayers")
        get_heroes: Callable[[], Iterable[Any]] = getattr(party, "GetHeroes")
        get_henchmen: Callable[[], Iterable[Any]] = getattr(party, "GetHenchmen")
        get_party_agent_id_by_login: Callable[[int], int] = getattr(
            party.Players, "GetAgentIDByLoginNumber"
        )
        get_party_hero_agent_id_by_position: Callable[[int], int] = getattr(
            party.Heroes, "GetHeroAgentIDByPartyPosition"
        )
        players = tuple(get_players())
        heroes = tuple(get_heroes())
        henchmen = tuple(get_henchmen())
        party_size = int(party.GetPartySize())
        if party_size < 0:
            raise ValueError("party size is invalid")

        try:
            party_id = int(party.GetPartyID())
        except Exception:
            party_id = 0
        try:
            map_signature = (
                map_id,
                int(Map.GetRegion()[0]),
                int(Map.GetDistrict()),
                int(Map.GetLanguage()[0]),
            )
        except Exception:
            map_signature = (map_id, -1, -1, -1)
        if (
            self._transition is not None
            and self._transition.destination is not None
            and (self._transition.destination != map_signature)
        ):
            self._retire_transition()
            remote_transition_expected = False
        get_player_name_by_login: Callable[[int], str] = getattr(
            party.Players, "GetPlayerNameByLoginNumber"
        )
        copied_players: list[_PartyPlayerEvidence] = []
        for player in players:
            login_number = int(player.login_number)
            try:
                connected = bool(player.is_connected)
            except Exception:
                connected = False
            try:
                agent_id = int(get_party_agent_id_by_login(login_number))
            except Exception:
                agent_id = 0
            character_name = ""
            if login_number != local_login_number:
                try:
                    character_name = str(get_player_name_by_login(login_number) or "")
                except Exception:
                    pass
            copied_players.append(_PartyPlayerEvidence(login_number, connected, agent_id, character_name))
        player_evidence = tuple(copied_players)
        hero_evidence = tuple(
            _PartyHeroEvidence(int(hero.owner_player_id), int(hero.hero_id), int(hero.agent_id)) for hero in heroes
        )
        henchman_agent_ids = tuple(int(henchman.agent_id) for henchman in henchmen)
        if self._transition is not None and len(players) + len(heroes) + len(henchmen) == party_size:
            current_hero_ids = {hero.hero_id for hero in hero_evidence}
            current_hero_keys = {(hero.owner_login_number, hero.hero_id) for hero in hero_evidence}
            for key, _baseline in self._transition.local:
                if key[0] is MemberKind.HERO and (key[1], key[2]) not in current_hero_keys:
                    self._retire_hero_candidate(MemberIdentity(*key))
            for key, origin in self._transition.origins:
                if key[2] not in current_hero_ids:
                    self._retire_hero_candidate(MemberIdentity(*key), origin.publisher)
            if not any(player.login_number != local_login_number for player in player_evidence):
                for _key, baseline in self._transition.remote:
                    self._retire_publisher(baseline.publisher)
        endpoint_capture = (
            _endpoint_diagnostic_records < 3
            and is_outpost
            and party_size == 8
            and len(players) == 2
            and len(hero_evidence) == 6
            and not henchman_agent_ids
            and sum(hero.owner_login_number == local_login_number for hero in hero_evidence) == 5
        )
        if not endpoint_capture:
            _endpoint_diagnostic_pending = None
        local_endpoint_reads: list[tuple[_EndpointRead, int]] = []
        remote_endpoint_read: _EndpointRead | None = {} if endpoint_capture else None
        try:
            local_character_uuid = _copy_uuid(Player.GetPlayerUUID())
        except Exception:
            local_character_uuid = (0, 0, 0, 0)
        local_hwnd = 0
        try:
            import PySystem

            local_hwnd = int(PySystem.Console.get_gw_window_handle() or 0)
        except Exception:
            pass

        if self._transition is not None and (
            party_id > 0
            and party_id != self._transition.source.party_id
            or any(local_character_uuid)
            and local_character_uuid != self._transition.source.local_character_uuid
        ):
            self._retire_transition()
            remote_transition_expected = False

        hero_agents = {
            (int(hero.owner_player_id), int(hero.hero_id)): int(hero.agent_id)
            for hero in heroes
            if int(hero.owner_player_id) > 0 and int(hero.hero_id) > 0
        }
        if self._last_ready_map_id == map_id:
            for stable_key, agent_id in hero_agents.items():
                if (
                    stable_key in self._last_hero_agents
                    and self._last_hero_agents[stable_key] != agent_id
                    and (not self._waiting_for_admission() or agent_id > 0 and self._last_hero_agents[stable_key] > 0)
                ):
                    self._candidate_local.pop((MemberKind.HERO, stable_key[0], stable_key[1]), None)

        skill_api = GLOBAL_CACHE.Skill
        if self._role_skill_ids is None:
            self._role_skill_ids = resolve_supported_skill_ids(skill_api.GetID)
        role_skill_ids = self._role_skill_ids
        native_skillbar = PySkillbar.Skillbar()
        native_skillbar.GetContext()

        records: list[MemberRecord] = []
        local_skillbar_reads: list[_LocalSkillbarRead] = []
        local_player_seen = 0
        remote_player_positions: list[tuple[int, _PartyPlayerEvidence]] = []
        for player_position, copied_player in enumerate(player_evidence):
            login_number = copied_player.login_number
            identity = MemberIdentity(MemberKind.PLAYER, login_number, login_number)
            if login_number != local_login_number:
                remote_player_positions.append((player_position, copied_player))
                records.append(
                    _unknown_member(
                        identity,
                        EvidenceSource.REMOTE_PLAYER,
                        "remote player identity or role proof is unavailable",
                    )
                )
                continue

            local_player_seen += 1
            identity = MemberIdentity(MemberKind.PLAYER, local_login_number, local_login_number, local_agent_id)
            mapped_agent_id = int(get_party_agent_id_by_login(local_login_number))
            if (
                local_player_seen != 1
                or mapped_agent_id != local_agent_id
                or int(native_skillbar.agent_id) != local_agent_id
            ):
                self._candidate_local.pop(identity.stable_key, None)
                records.append(
                    _unknown_member(
                        identity, EvidenceSource.LOCAL_PLAYER, "local player or skillbar ownership is ambiguous"
                    )
                )
                continue

            player_skill_slots = tuple(native_skillbar.skills)
            player_primary = int(Agent.GetProfessions(local_agent_id)[0])
            records.append(
                self._read_and_recognize_member(
                    identity=identity,
                    source=EvidenceSource.LOCAL_PLAYER,
                    agent_id=local_agent_id,
                    skill_slots=player_skill_slots,
                    primary_profession=player_primary,
                    skill_api=skill_api,
                    skill_type_attack=int(SkillType.Attack),
                    skill_ids=role_skill_ids,
                    character_identity=character_identity,
                    is_outpost=is_outpost,
                    is_explorable=is_explorable,
                )
            )
            if records[-1].role is not CleansingRole.UNKNOWN:
                local_skillbar_reads.append(
                    _LocalSkillbarRead(
                        0, local_agent_id, tuple(int(slot.id.id) for slot in player_skill_slots), player_primary
                    )
                )

        if local_player_seen != 1:
            self._candidate_local.pop((MemberKind.PLAYER, local_login_number, local_login_number), None)

        duplicate_hero_keys = {
            (hero.owner_login_number, hero.hero_id)
            for hero in hero_evidence
            if sum(
                other.owner_login_number == hero.owner_login_number and other.hero_id == hero.hero_id
                for other in hero_evidence
            )
            > 1
        }
        # Native party positions reserve 0 for the local player; hero rows start at 1.
        remote_hero_positions: list[tuple[int, _PartyHeroEvidence]] = []
        local_witness_reads: list[_LocalHeroWitnessRead] = []
        local_observation: _LocalWitnessObservation | None = None
        try:
            local_observation = _new_local_witness_observation(decision_capture=decision is not None) if is_outpost else None
            if local_observation is not None:
                local_observation.decision = decision
            if is_outpost and decision is not None and local_observation is None:
                decision.failed = True
        except Exception:
            if decision is not None:
                decision.failed = True
        for hero_position, (hero, copied_hero) in enumerate(zip(heroes, hero_evidence), start=1):
            owner_id = copied_hero.owner_login_number
            hero_id = copied_hero.hero_id
            hero_agent_id = copied_hero.agent_id
            identity = MemberIdentity(MemberKind.HERO, owner_id, hero_id, hero_agent_id)
            if owner_id != local_login_number:
                remote_hero_positions.append((hero_position - 1, copied_hero))
                records.append(
                    _unknown_member(
                        identity, EvidenceSource.REMOTE_HERO, "remote hero owner or role proof is unavailable"
                    )
                )
                continue
            _local_witness_note(local_observation, hero_position, entry="NOT_EVALUATED")
            endpoint_read: _EndpointRead | None = {"gate": "ROSTER"} if endpoint_capture else None
            if endpoint_read is not None:
                local_endpoint_reads.append((endpoint_read, len(records)))
            if (owner_id, hero_id) in duplicate_hero_keys or hero_id <= 0:
                try:
                    if decision is not None:
                        decision.paths[3] += 1
                except Exception:
                    if decision is not None:
                        decision.failed = True
                _local_witness_note(
                    local_observation,
                    hero_position,
                    entry="IDENTITY_FAIL",
                    gate="IDENTITY_FAIL",
                )
                self._candidate_local.pop(identity.stable_key, None)
                records.append(_unknown_member(identity, EvidenceSource.LOCAL_HERO, "local hero identity is ambiguous"))
                continue
            if hero_agent_id <= 0:
                if not self._retain_local_candidate(identity.stable_key):
                    self._candidate_local.pop(identity.stable_key, None)
                records.append(
                    _unknown_member(
                        identity, EvidenceSource.LOCAL_HERO, "local hero identity is ambiguous; endpoint is unavailable"
                    )
                )
                continue
            mapped_hero_agent_id = int(get_party_hero_agent_id_by_position(hero_position))
            if mapped_hero_agent_id != hero_agent_id:
                try:
                    if decision is not None:
                        decision.paths[3] += 1
                except Exception:
                    if decision is not None:
                        decision.failed = True
                _local_witness_note(
                    local_observation,
                    hero_position,
                    entry="POSITION_FAIL",
                    gate="POSITION_FAIL",
                )
                if mapped_hero_agent_id > 0 or not self._retain_local_candidate(identity.stable_key):
                    self._candidate_local.pop(identity.stable_key, None)
                records.append(
                    _unknown_member(
                        identity, EvidenceSource.LOCAL_HERO, "hero skillbar index does not match the party hero"
                    )
                )
                continue

            try:
                if endpoint_read is not None:
                    endpoint_read["gate"] = "READ"
                hero_skill_slots = tuple(native_skillbar.GetHeroSkillbar(hero_position))
                primary_profession = int(
                    Agent.GetProfessions(hero_agent_id)[0]
                    if endpoint_read is None
                    else Agent.GetProfessions(hero_agent_id, _stage3_observation=endpoint_read)[0]
                )
                previous_baseline = self._candidate_local.get(identity.stable_key)
                origin = previous_baseline.witness_origin if previous_baseline is not None else None
                if primary_profession > 0:
                    _local_witness_note(local_observation, hero_position, entry="PROF_PRESENT")
                witness_endpoint = Agent.GetAgentByID(hero_agent_id) if is_outpost and primary_profession <= 0 else None
                needs_witness = (
                    is_outpost
                    and primary_profession <= 0
                    and _local_witness_absent(
                        local_observation,
                        hero_position,
                        witness_endpoint,
                    )
                ) or (is_explorable and origin is not None)
                if (
                    witness_endpoint is not None
                    and origin is not None
                    and (not witness_endpoint.is_living_type or witness_endpoint.GetAsAgentLiving() is None)
                ):
                    self._candidate_local.pop(identity.stable_key, None)
                try:
                    if decision is not None:
                        decision.paths[1 if needs_witness else 0 if primary_profession > 0 else 2 if is_outpost else 4] += 1
                except Exception:
                    if decision is not None:
                        decision.failed = True
                if needs_witness:
                    local_witness_reads.append(
                        _LocalHeroWitnessRead(
                            len(records),
                            hero_position,
                            copied_hero,
                            tuple(int(slot.id.id) for slot in hero_skill_slots),
                            origin,
                        )
                    )
                records.append(
                    self._read_and_recognize_member(
                        identity=identity,
                        source=EvidenceSource.LOCAL_HERO,
                        agent_id=hero_agent_id,
                        skill_slots=hero_skill_slots,
                        primary_profession=primary_profession,
                        skill_api=skill_api,
                        skill_type_attack=int(SkillType.Attack),
                        skill_ids=role_skill_ids,
                        character_identity=character_identity,
                        is_outpost=is_outpost,
                        is_explorable=is_explorable,
                        endpoint_observation=endpoint_read,
                        witness_read_pending=needs_witness,
                    )
                )
                if records[-1].role is not CleansingRole.UNKNOWN and not needs_witness:
                    local_skillbar_reads.append(
                        _LocalSkillbarRead(
                            hero_position,
                            hero_agent_id,
                            tuple(int(slot.id.id) for slot in hero_skill_slots),
                            primary_profession,
                        )
                    )
                elif not needs_witness and primary_profession > 0 and decision is not None:
                    try:
                        decision.paths[4] += 1
                    except Exception:
                        decision.failed = True
            except Exception as error:
                try:
                    if decision is not None:
                        decision.paths[3] += 1
                except Exception:
                    if decision is not None:
                        decision.failed = True
                _local_witness_note(
                    local_observation,
                    hero_position,
                    entry="READ_FAIL",
                    gate="READ_FAIL",
                )
                if endpoint_read is not None:
                    endpoint_read["gate"] = "READ"
                self._candidate_local.pop(identity.stable_key, None)
                records.append(
                    _unknown_member(
                        identity,
                        EvidenceSource.LOCAL_HERO,
                        f"local hero evidence read failed ({type(error).__name__})",
                    )
                )

        for henchman_agent_id in henchman_agent_ids:
            identity = MemberIdentity(MemberKind.HENCHMAN, 0, henchman_agent_id, henchman_agent_id)
            records.append(_unknown_member(identity, EvidenceSource.NONE, "henchman role recognition is not supported"))

        remote_player_records: dict[int, MemberRecord] = {}
        remote_hero_records: dict[int, MemberRecord] = {}
        owner_proofs: dict[int, _RemoteOwnerProof] = {}
        hero_proofs: tuple[_RemoteHeroProof | _OutpostHeroProof, ...] = ()
        publication: object | None = None
        captured_at_tick64 = -1
        publication_temporary = False
        self._closing_preserve_candidates = False
        recovery_epoch = 0
        publication_reason = "remote publication is unavailable"
        try:
            result = GLOBAL_CACHE.ShMem.GetNativeAccountSnapshotV3()
            if getattr(result.status, "value", result.status) == "success" and result.snapshot is not None:
                _local_witness_note(local_observation, native="OK")
                publication = result.snapshot
                publication_reason = ""
            else:
                status = str(getattr(result.status, "value", result.status))
                publication_temporary = status in ("busy", "unavailable")
                if publication_temporary and self._transition is not None and self._transition.publishers:
                    self._begin_waiting()
                _local_witness_note(local_observation, native=status.upper())
                publication_reason = f"remote publication is unavailable ({status})"
        except Exception as error:
            _local_witness_note(local_observation, native="READ_FAILED")
            publication_reason = f"remote publication read failed ({type(error).__name__})"
        try:
            if decision is not None and local_witness_reads and publication is None:
                decision.opening = "PUBLICATION_REJECTED"
        except Exception:
            if decision is not None:
                decision.failed = True
        copied_cohorts: tuple[_PublishedCohort, ...] = ()
        pending_local_baselines: dict[tuple[MemberKind, int, int], _Baseline] = {}
        local_witness_records: dict[int, MemberRecord] = {}
        pending_remote_origins: dict[tuple[MemberKind, int, int], _LocalWitnessOrigin] = {}
        runtime_verification = _ClosingVerification.COHERENT
        if is_outpost and remote_hero_positions:
            self._remote_hero_outpost_seen = True
        if publication is not None:
            try:
                copied_cohorts = _copy_published_cohorts(publication)
                _local_witness_note(local_observation, cohorts=len(copied_cohorts))
                recovery_epoch = int(publication.recovery_epoch)
                captured_at_tick64 = int(publication.captured_at_tick64)
                if not 0 < recovery_epoch <= 0xFFFFFFFFFFFFFFFF or not 0 <= captured_at_tick64 <= 0xFFFFFFFFFFFFFFFF:
                    raise ValueError("invalid Native publication metadata")
                self._check_historical_publishers(copied_cohorts, recovery_epoch)
                remote_player_records, owner_proofs = self._evaluate_remote_players(
                    players=player_evidence,
                    heroes=hero_evidence,
                    henchmen=henchman_agent_ids,
                    remote_positions=tuple(remote_player_positions),
                    cohorts=copied_cohorts,
                    recovery_epoch=recovery_epoch,
                    captured_at_tick64=captured_at_tick64,
                    map_signature=map_signature,
                    instance_type=0 if is_outpost else 1 if is_explorable else -1,
                    party_id=party_id,
                    local_login_number=local_login_number,
                    local_agent_id=local_agent_id,
                    local_character_identity=character_identity,
                    local_character_uuid=local_character_uuid,
                    local_account_email=account_email,
                    local_hwnd=local_hwnd,
                    transition_expected=remote_transition_expected,
                    transition_source_map_id=transition_source_map_id,
                    is_outpost=is_outpost,
                    is_explorable=is_explorable,
                    agent_api=Agent,
                    skill_api=skill_api,
                    skill_type_attack=int(SkillType.Attack),
                    role_skill_ids=role_skill_ids,
                    roster_complete=len(player_evidence) + len(hero_evidence) + len(henchman_agent_ids) == party_size,
                )
                if (
                    self._transition is not None
                    and len(player_evidence) + len(hero_evidence) + len(henchman_agent_ids) == party_size
                ):
                    hero_keys = {(hero.owner_login_number, hero.hero_id) for hero in hero_evidence}
                    for key, origin in self._transition.origins:
                        owner = next(
                            (proof for proof in owner_proofs.values() if proof.publisher == origin.publisher), None
                        )
                        if owner is not None and (owner.login_number, origin.witness.hero_id) not in hero_keys:
                            self._retire_hero_candidate(MemberIdentity(*key), origin.publisher)
                remote_hero_records, hero_proofs = self._evaluate_remote_heroes(
                    heroes=hero_evidence,
                    remote_positions=tuple(remote_hero_positions),
                    duplicate_hero_keys=duplicate_hero_keys,
                    players=player_evidence,
                    henchmen=henchman_agent_ids,
                    cohorts=copied_cohorts,
                    owner_proofs=owner_proofs,
                    captured_at_tick64=captured_at_tick64,
                    map_signature=map_signature,
                    party_id=party_id,
                    local_agent_id=local_agent_id,
                    agent_api=Agent,
                    skill_api=skill_api,
                    skill_type_attack=int(SkillType.Attack),
                    role_skill_ids=role_skill_ids,
                    endpoint_observation=remote_endpoint_read,
                )
                for position, hero in remote_hero_positions:
                    record = remote_hero_records[position]
                    if self._transition is not None and record.identity.stable_key in self._transition.retired:
                        remote_hero_records[position] = _replace_record_role(
                            record, CleansingRole.UNKNOWN, "source hero origin was retired"
                        )
                        continue
                    proof = next((proof for proof in hero_proofs if proof.identity == record.identity), None)
                    if proof is None:
                        continue
                    witness = _qualified_hero_witness(proof.cohort, hero.hero_id, captured_at_tick64)
                    owner = owner_proofs[hero.owner_login_number]
                    if is_outpost and witness is not None:
                        pending_remote_origins[record.identity.stable_key] = _LocalWitnessOrigin(
                            owner.publisher, witness
                        )
                    elif not is_outpost:
                        origin = self._candidate_origins.get(record.identity.stable_key)
                        if origin is None and remote_transition_expected:
                            owner_baseline = self._candidate_remote.get(
                                (MemberKind.PLAYER, hero.owner_login_number, hero.owner_login_number)
                            )
                            reassociated = tuple(
                                previous
                                for previous in self._candidate_origins.values()
                                if previous.publisher == owner.publisher and previous.witness.hero_id == hero.hero_id
                            )
                            if (
                                owner_baseline is not None
                                and owner_baseline.publisher == owner.publisher
                                and len(reassociated) == 1
                            ):
                                origin = reassociated[0]
                        if (
                            origin is None
                            or origin.publisher != owner.publisher
                            or origin.witness != witness
                            or (origin.destination_epoch is None and not remote_transition_expected)
                            or (
                                origin.destination_epoch is not None
                                and origin.destination_epoch != proof.cohort.instance_epoch
                            )
                        ):
                            remote_hero_records[position] = _replace_record_role(
                                record,
                                CleansingRole.UNKNOWN,
                                "remote hero outpost publisher or loading continuity is unavailable",
                            )
                        else:
                            pending_remote_origins[record.identity.stable_key] = replace(
                                origin, destination_epoch=proof.cohort.instance_epoch
                            )

                if local_witness_reads or any(
                    baseline.witness_origin is not None for baseline in self._candidate_local.values()
                ):
                    (
                        local_witness_records,
                        local_proofs,
                        local_owner,
                        pending_local_baselines,
                    ) = self._evaluate_local_witness_heroes(
                        reads=tuple(local_witness_reads),
                        records=tuple(records),
                        players=player_evidence,
                        heroes=hero_evidence,
                        henchmen=henchman_agent_ids,
                        duplicate_hero_keys=duplicate_hero_keys,
                        cohorts=copied_cohorts,
                        recovery_epoch=recovery_epoch,
                        captured_at_tick64=captured_at_tick64,
                        map_signature=map_signature,
                        party_id=party_id,
                        local_login_number=local_login_number,
                        local_agent_id=local_agent_id,
                        local_character_uuid=local_character_uuid,
                        local_account_email=account_email,
                        local_hwnd=local_hwnd,
                        transition_expected=remote_transition_expected,
                        is_outpost=is_outpost,
                        agent_api=Agent,
                        skill_api=skill_api,
                        skill_type_attack=int(SkillType.Attack),
                        role_skill_ids=role_skill_ids,
                        observation=local_observation,
                    )
                    _local_witness_note(local_observation, evaluation="OK")
                    try:
                        if decision is not None and local_observation is not None and local_witness_reads:
                            owner_code = local_observation.values.get("owner", "UNKNOWN")
                            accepted = len(pending_local_baselines)
                            decision.opening = (
                                str(owner_code)
                                if owner_code != "OK"
                                else "ACCEPTED" if accepted == len(local_witness_reads) else "PARTIAL" if accepted else "QUALIFICATION"
                            )
                    except Exception:
                        if decision is not None:
                            decision.failed = True
                    hero_proofs = (*hero_proofs, *local_proofs)
                    if local_owner is not None:
                        owner_proofs[local_login_number] = local_owner

                if remote_player_positions or remote_hero_positions or local_witness_reads:
                    verification = _ClosingVerification.INCOHERENT
                    try:
                        closing_tick = int(GLOBAL_CACHE.ShMem.GetBaseTimestamp())

                        def close_evidence() -> _ClosingVerification:
                            try:
                                if decision is not None:
                                    decision.closing_pass += 1
                            except Exception:
                                if decision is not None:
                                    decision.failed = True
                            return self._recheck_remote_evidence(
                                opening_players=player_evidence,
                                opening_heroes=hero_evidence,
                                opening_henchmen=henchman_agent_ids,
                                opening_party_size=party_size,
                                opening_party_id=party_id,
                                opening_map_id=map_id,
                                opening_map_signature=map_signature,
                                opening_instance_type=0 if is_outpost else 1 if is_explorable else -1,
                                opening_character_identity=character_identity,
                                opening_character_uuid=local_character_uuid,
                                opening_hwnd=local_hwnd,
                                opening_local_agent_id=local_agent_id,
                                opening_local_login_number=local_login_number,
                                owner_proofs=tuple(owner_proofs.values()),
                                hero_proofs=hero_proofs,
                                local_witness_reads=tuple(local_witness_reads),
                                opening_captured_at_tick64=captured_at_tick64,
                                skill_api=skill_api,
                                skill_type_attack=int(SkillType.Attack),
                                role_skill_ids=role_skill_ids,
                                current_tick=closing_tick,
                                observation=local_observation,
                                decision=decision,
                            )

                        verification = close_evidence()
                        if verification is not _ClosingVerification.COHERENT:
                            _stage3_failure(decision, "UNKNOWN", "SHARED")
                        try:
                            if decision is not None and decision.closing != "PUBLICATION_REJECTED":
                                decision.closing = _local_witness_closing_code(verification)
                        except Exception:
                            if decision is not None:
                                decision.failed = True
                        _local_witness_note(
                            local_observation,
                            closing=_local_witness_closing_code(verification),
                        )
                        coherent = verification is _ClosingVerification.COHERENT
                        for read in local_witness_reads:
                            current_bar = tuple(
                                int(slot.id.id) for slot in native_skillbar.GetHeroSkillbar(read.party_position)
                            )
                            if (
                                int(get_party_hero_agent_id_by_position(read.party_position)) != read.hero.agent_id
                                or current_bar != read.skill_ids
                            ):
                                _stage3_failure(decision, "LOCAL_BAR", "LOCAL_HERO")
                                try:
                                    if decision is not None:
                                        decision.closing = "LOCAL_CONTINUITY"
                                except Exception:
                                    if decision is not None:
                                        decision.failed = True
                                _local_witness_note(local_observation, closing="LOCAL_CONTINUITY")
                                coherent = False
                                runtime_verification = _ClosingVerification.RUNTIME_CHANGED
                        if local_witness_reads and coherent:
                            verification = close_evidence()
                            if verification is not _ClosingVerification.COHERENT:
                                _stage3_failure(decision, "UNKNOWN", "SHARED")
                            try:
                                if decision is not None and decision.closing != "PUBLICATION_REJECTED":
                                    decision.closing = _local_witness_closing_code(verification)
                            except Exception:
                                if decision is not None:
                                    decision.failed = True
                            _local_witness_note(
                                local_observation,
                                closing=_local_witness_closing_code(verification),
                            )
                            coherent = verification is _ClosingVerification.COHERENT
                        if verification is _ClosingVerification.CONTROLLED_IDENTITY_CHANGED:
                            runtime_verification = verification
                        elif verification is _ClosingVerification.RUNTIME_CHANGED:
                            runtime_verification = verification
                    except Exception:
                        try:
                            if decision is not None:
                                decision.closing = "READ_FAILED_CLOSING"
                        except Exception:
                            if decision is not None:
                                decision.failed = True
                        _stage3_failure(decision, "CLOSING_READ", "UNKNOWN")
                        _local_witness_note(local_observation, closing="READ_FAILED_CLOSING")
                        coherent = False
                    if not coherent:
                        publication = None
                        publication_reason = "opening and closing remote evidence disagree"
                        if self._closing_preserve_candidates:
                            self._begin_waiting()
                        publication_temporary = self._waiting_for_admission() and (
                            verification is _ClosingVerification.UNAVAILABLE or self._closing_preserve_candidates
                        )
                        if publication_temporary:
                            self._discard_provisional_admissions()
                        else:
                            self._candidate_remote.clear()
                            self._candidate_origins.clear()
            except Exception as error:
                try:
                    if decision is not None:
                        decision.opening = "EVALUATION_FAILED"
                except Exception:
                    if decision is not None:
                        decision.failed = True
                _local_witness_note(local_observation, evaluation="EVALUATION_FAILED")
                publication = None
                publication_reason = f"remote evidence evaluation failed ({type(error).__name__})"
                self._candidate_remote.clear()
                self._candidate_origins.clear()

        opening_runtime = _ClosingState(
            safe_lifecycle=True,
            map_id=map_id,
            map_signature=map_signature,
            instance_type=0 if is_outpost else 1 if is_explorable else -1,
            party_id=party_id,
            party_size=party_size,
            players=tuple((player.login_number, player.connected, player.agent_id) for player in player_evidence),
            heroes=tuple((hero.owner_login_number, hero.hero_id, hero.agent_id) for hero in hero_evidence),
            henchmen=henchman_agent_ids,
            local_agent_id=local_agent_id,
            local_login_number=local_login_number,
            local_account_email=character_identity[0],
            local_character_name=character_identity[1],
            local_character_uuid=local_character_uuid,
            local_hwnd=local_hwnd,
        )
        for read in local_witness_reads:
            baseline = pending_local_baselines.get(records[read.record_index].identity.stable_key)
            if publication is not None and baseline is not None and baseline.witness_origin is not None:
                local_skillbar_reads.append(
                    _LocalSkillbarRead(
                        read.party_position,
                        read.hero.agent_id,
                        read.skill_ids,
                        baseline.profession,
                        baseline.witness_origin.witness,
                    )
                )
        try:
            if local_observation is not None:
                local_observation.decision = decision
        except Exception:
            if decision is not None:
                decision.failed = True
        final_runtime = self._recheck_final_runtime(
            opening=opening_runtime,
            local_reads=tuple(local_skillbar_reads),
            native_skillbar=native_skillbar,
            get_hero_agent_id=get_party_hero_agent_id_by_position,
            agent_api=Agent,
            owner_proofs=(tuple(owner_proofs.values()) if publication is not None else ()),
            hero_proofs=hero_proofs if publication is not None else (),
            observation=local_observation,
        )
        _local_witness_note(local_observation, final=_local_witness_closing_code(final_runtime))
        try:
            if decision is not None:
                decision.final = _local_witness_closing_code(final_runtime)
                if final_runtime is not _ClosingVerification.COHERENT:
                    _stage3_failure(decision, "FINAL_RUNTIME", "SHARED", 3)
        except Exception:
            if decision is not None:
                decision.failed = True
        if (
            final_runtime is _ClosingVerification.CONTROLLED_IDENTITY_CHANGED
            or runtime_verification is _ClosingVerification.COHERENT
        ):
            runtime_verification = final_runtime
        if runtime_verification is not _ClosingVerification.COHERENT:
            publication = None
            publication_reason = (
                "controlled player changed during closing"
                if runtime_verification is _ClosingVerification.CONTROLLED_IDENTITY_CHANGED
                else "runtime evidence changed during closing"
            )
            publication_temporary = (
                runtime_verification is _ClosingVerification.UNAVAILABLE and self._waiting_for_admission()
            )
            if publication_temporary:
                self._discard_provisional_admissions()
            else:
                self._candidate_local.clear()
            records = [
                _unknown_member(record.identity, record.evidence_source, publication_reason) for record in records
            ]

        if publication is None:
            pending_remote_origins.clear()
            pending_local_baselines.clear()
            local_witness_records.clear()
            if not publication_temporary or not self._waiting_for_admission():
                self._candidate_remote.clear()
                self._candidate_origins.clear()
                for key, baseline in tuple(self._candidate_local.items()):
                    if baseline.witness_origin is not None:
                        self._candidate_local.pop(key, None)
            else:
                for key in tuple(self._candidate_remote):
                    if not self._retain_remote_candidate(key):
                        self._candidate_remote.pop(key, None)
                for key, origin in tuple(self._candidate_origins.items()):
                    if origin.destination_epoch is not None:
                        self._candidate_origins.pop(key, None)
            remote_player_records.clear()
            remote_hero_records.clear()
            owner_proofs.clear()
            hero_proofs = ()
            for position, player in remote_player_positions:
                remote_player_records[position] = _unknown_member(
                    MemberIdentity(MemberKind.PLAYER, player.login_number, player.login_number, player.agent_id),
                    EvidenceSource.REMOTE_PLAYER,
                    publication_reason,
                )
            for position, hero in remote_hero_positions:
                remote_hero_records[position] = _unknown_member(
                    MemberIdentity(MemberKind.HERO, hero.owner_login_number, hero.hero_id, hero.agent_id),
                    EvidenceSource.REMOTE_HERO,
                    publication_reason,
                )

        for position, record in remote_player_records.items():
            records[position] = record
        hero_offset = len(players)
        for position, record in remote_hero_records.items():
            records[hero_offset + position] = record
        if self._remote_hero_outpost_seen:
            for key, origin in tuple(self._candidate_origins.items()):
                if not self._waiting_for_admission() or origin.destination_epoch is not None:
                    self._candidate_origins.pop(key, None)
            self._candidate_origins.update(pending_remote_origins)

        for read in local_witness_reads:
            identity = records[read.record_index].identity
            baseline = pending_local_baselines.get(identity.stable_key)
            if baseline is None:
                _local_witness_note(local_observation, read.party_position, committed=0)
                if not self._retain_local_candidate(identity.stable_key):
                    self._candidate_local.pop(identity.stable_key, None)
                records[read.record_index] = _unknown_member(
                    identity,
                    EvidenceSource.LOCAL_HERO,
                    records[read.record_index].reason
                    + "; "
                    + (publication_reason or "local qualified outpost witness or continuity proof is unavailable"),
                )
            else:
                _local_witness_note(local_observation, read.party_position, committed=1)
                self._candidate_local[identity.stable_key] = baseline
                records[read.record_index] = local_witness_records[read.record_index]

        roster_complete = len(records) == party_size
        if runtime_verification is not _ClosingVerification.COHERENT:
            reason = publication_reason
        elif not roster_complete:
            reason = f"party member records incomplete: party reports {party_size}, evidence has {len(records)}"
        elif not any(
            record.identity.kind is MemberKind.PLAYER and record.identity.owner_id == local_login_number
            for record in records
        ):
            reason = "local player is absent from the party member records"
        else:
            reason = "local party evidence refreshed"

        snapshot_ready = (
            roster_complete and local_player_seen == 1 and runtime_verification is _ClosingVerification.COHERENT
        )
        if not snapshot_ready:
            if not self._waiting_for_admission() or runtime_verification not in (
                _ClosingVerification.COHERENT,
                _ClosingVerification.UNAVAILABLE,
            ):
                self._candidate_remote.clear()
                self._candidate_origins.clear()
        recovering_outpost = self._transition is not None and self._transition.started_at is not None and is_outpost
        completing_admission = self._waiting_for_admission()
        self._complete_transition(
            opening_runtime, copied_cohorts, recovery_epoch, snapshot_ready, publication is not None, tuple(records)
        )
        if (recovering_outpost or completing_admission) and self._transition_phase is TransitionPhase.RETIRED:
            records = [
                (
                    record
                    if record.role is CleansingRole.UNKNOWN
                    or record.evidence_source is EvidenceSource.LOCAL_PLAYER
                    or (
                        record.identity.stable_key in self._candidate_local
                        and self._candidate_local[record.identity.stable_key].witness_origin is None
                    )
                    else _unknown_member(record.identity, record.evidence_source, "original outpost recovery rejected")
                )
                for record in records
            ]
        self._last_ready_map_id = map_id
        self._last_ready_was_outpost = is_outpost and runtime_verification is _ClosingVerification.COHERENT
        self._last_hero_agents = hero_agents
        if (
            endpoint_capture
            and snapshot_ready
            and remote_endpoint_read is not None
            and len(local_endpoint_reads) == 5
            and any(
                record.evidence_source is EvidenceSource.LOCAL_PLAYER and record.role is CleansingRole.HEROIC_REFRAIN
                for record in records
            )
        ):
            diagnostic_delivery.append(
                lambda: _emit_endpoint_diagnostic(
                    [(observation, records[index]) for observation, index in local_endpoint_reads],
                    remote_endpoint_read,
                    context_key=(map_id, party_id, self._lifecycle_epoch, character_identity),
                    roster_key=tuple(
                        value for player in player_evidence for value in (player.login_number, player.agent_id)
                    )
                    + tuple(
                        value
                        for hero in hero_evidence
                        for value in (hero.owner_login_number, hero.hero_id, hero.agent_id)
                    ),
                    endpoints_ready=all(player.login_number > 0 and player.agent_id > 0 for player in player_evidence)
                    and all(
                        hero.owner_login_number > 0 and hero.hero_id > 0 and hero.agent_id > 0 for hero in hero_evidence
                    )
                    and not duplicate_hero_keys
                    and len({player.agent_id for player in player_evidence} | {hero.agent_id for hero in hero_evidence})
                    == 8,
                )
            )
        else:
            _endpoint_diagnostic_pending = None
        self._commit_evidence()
        published = self._publish(
            map_id=map_id,
            ready=snapshot_ready,
            character_identity=character_identity,
            members=tuple(records),
            declared_party_size=party_size,
            reason=reason,
        )
        if (
            snapshot_ready
            and publication is not None
            and captured_at_tick64 >= 0
            and runtime_verification is _ClosingVerification.COHERENT
            and all(record.role is not CleansingRole.UNKNOWN for record in records)
            and len(records) <= 8
        ):
            try:
                self._stage3_closing_inputs = _Stage3ClosingInputs(
                    opening_runtime,
                    player_evidence,
                    hero_evidence,
                    tuple(local_skillbar_reads),
                    tuple(local_witness_reads),
                    tuple(owner_proofs.values()),
                    hero_proofs,
                    captured_at_tick64,
                    role_skill_ids,
                )
            except Exception:
                self._stage3_evidence_failed = True
        _local_witness_note(local_observation, ready=int(snapshot_ready), revision=published.revision)
        diagnostic_delivery.append(
            lambda: _emit_local_witness_diagnostic(
                local_observation if STAGE3_LOCAL_WITNESS_DIAGNOSTIC else None,
                context_key=(
                    map_id,
                    party_id,
                    self._lifecycle_epoch,
                    character_identity,
                    local_character_uuid,
                    local_hwnd,
                ),
                roster_key=tuple(
                    value for player in player_evidence for value in (player.login_number, player.agent_id)
                )
                + tuple(
                    value for hero in hero_evidence for value in (hero.owner_login_number, hero.hero_id, hero.agent_id)
                ),
                complete=is_outpost and roster_complete and party_size == 8 and len(records) == 8,
            )
        )
        return published

    def _evaluate_remote_players(
        self,
        *,
        players: tuple[_PartyPlayerEvidence, ...],
        heroes: tuple[_PartyHeroEvidence, ...],
        henchmen: tuple[int, ...],
        remote_positions: tuple[tuple[int, _PartyPlayerEvidence], ...],
        cohorts: tuple[_PublishedCohort, ...],
        recovery_epoch: int,
        captured_at_tick64: int,
        map_signature: tuple[int, int, int, int],
        instance_type: int,
        party_id: int,
        local_login_number: int,
        local_agent_id: int,
        local_character_identity: tuple[str, str],
        local_character_uuid: tuple[int, int, int, int],
        local_account_email: str,
        local_hwnd: int,
        transition_expected: bool,
        transition_source_map_id: int | None,
        is_outpost: bool,
        is_explorable: bool,
        agent_api: object,
        skill_api: object,
        skill_type_attack: int,
        role_skill_ids: CleansingSkillIDs,
        roster_complete: bool = True,
    ) -> tuple[dict[int, MemberRecord], dict[int, _RemoteOwnerProof]]:
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

        contextual = tuple(
            cohort
            for cohort in cohorts
            if cohort.instance_type == instance_type
            and cohort.owner.map_signature == map_signature
            and cohort.owner.party_id == party_id
        )
        login_counts = Counter(player.login_number for player in players)
        baseline_snapshot = dict(self._candidate_remote)
        deferred_baseline_removals: set[tuple[MemberKind, int, int]] = set()
        pending_reassociations: list[_RemoteBaselineReassociation] = []

        def remove_publisher_history(publisher: _PublisherToken) -> None:
            # Transition keys remain source keys even after candidate reassociation.
            # The saved evaluation snapshot must obey the same retirement.
            self._retire_publisher(publisher)
            deferred_baseline_removals.update(
                key for key, baseline in baseline_snapshot.items() if baseline.publisher == publisher
            )

        def remove_baseline(key: tuple[MemberKind, int, int], *, unavailable: bool = False) -> None:
            if unavailable:
                self._begin_waiting()
            if unavailable and (
                self._retain_remote_candidate(key)
                or self._waiting_for_admission()
                and any(
                    origin_key[1] == key[1] and origin.destination_epoch is None
                    for origin_key, origin in self._candidate_origins.items()
                )
            ):
                return
            baseline = baseline_snapshot.get(key)
            publishers = (
                {baseline.publisher}
                if baseline is not None
                else {
                    origin.publisher
                    for origin_key, origin in self._candidate_origins.items()
                    if origin_key[1] == key[1]
                }
            )
            for publisher in publishers:
                remove_publisher_history(publisher)
            if is_explorable:
                deferred_baseline_removals.add(key)
            else:
                self._candidate_remote.pop(key, None)

        qualified_publishers = {baseline.publisher for baseline in baseline_snapshot.values()}
        qualified_publishers.update(origin.publisher for origin in self._candidate_origins.values())
        owner_contradictions: set[_PublisherToken] = set()
        current_account_email = local_account_email.strip().casefold()

        def owner_context_valid(cohort: _PublishedCohort) -> bool:
            owner = cohort.owner
            account_email = owner.account_email.strip().casefold()
            return (
                local_hwnd > 0
                and owner.key_hwnd > 0
                and owner.key_hwnd != local_hwnd
                and bool(account_email)
                and account_email != current_account_email
                and owner.is_slot_active
                and owner.is_account
                and not owner.is_hero
                and not owner.is_pet
                and not owner.is_npc
                and owner.key_entity_type == 0
                and owner.key_local_index == 0
                and owner.slot_index == owner.slot_number
                and any(cohort.character_uuid)
                and cohort.character_uuid != local_character_uuid
                and cohort.character_uuid == owner.character_uuid
                and any(cohort.incarnation)
                and cohort.instance_epoch > 0
                and cohort.published_tick == owner.last_updated
                and owner.owner_agent_id == 0
                and owner.hero_id == 0
                and owner.map_signature == map_signature
                and owner.party_id == party_id
            )

        # Attribute history without consulting the owner's potentially contradictory
        # instance-local IDs. Only a unique, fresh, contextual exact publisher can
        # supply positive current-owner evidence; absence is still bounded waiting.
        for publisher in qualified_publishers:
            attributed = tuple(cohort for cohort in contextual if _publisher_token(cohort, recovery_epoch) == publisher)
            if len(attributed) != 1:
                continue
            cohort = attributed[0]
            if (
                not owner_context_valid(cohort)
                or len(cohort.incarnation) != 16
                or not publication_is_live(captured_at_tick64, cohort.published_tick)
                or any(other is not cohort and self._publisher_identity_conflicts(cohort, other) for other in cohorts)
            ):
                continue
            owner = cohort.owner
            current_owners = tuple(player for player in players if player.login_number == owner.login_number)
            if (
                roster_complete
                and owner.login_number > 0
                and (
                    not current_owners
                    or owner.login_number == local_login_number
                    or owner.agent_id == local_agent_id
                    or any(
                        player.agent_id > 0 and owner.agent_id > 0 and player.agent_id != owner.agent_id
                        for player in current_owners
                    )
                )
            ):
                owner_contradictions.add(publisher)
                remove_publisher_history(publisher)

        def owner_claims_for(player: _PartyPlayerEvidence) -> tuple[_PublishedCohort, ...]:
            return tuple(
                cohort
                for cohort in contextual
                if (player.login_number > 0 and cohort.owner.login_number == player.login_number)
                or (player.agent_id > 0 and cohort.owner.agent_id == player.agent_id)
            )

        def remove_owner_history(
            player: _PartyPlayerEvidence, claims: tuple[_PublishedCohort, ...], *, unavailable: bool = False
        ) -> None:
            publishers = {_publisher_token(cohort, recovery_epoch) for cohort in claims} & qualified_publishers
            if publishers:
                for publisher in publishers:
                    keys = tuple(key for key, baseline in baseline_snapshot.items() if baseline.publisher == publisher)
                    if unavailable:
                        self._begin_waiting()
                        for key in keys:
                            remove_baseline(key, unavailable=True)
                        if not keys:
                            for origin_key, origin in tuple(self._candidate_origins.items()):
                                if origin.publisher == publisher:
                                    remove_baseline((MemberKind.PLAYER, origin_key[1], origin_key[1]), unavailable=True)
                    else:
                        remove_publisher_history(publisher)
                return
            key = (MemberKind.PLAYER, player.login_number, player.login_number)
            baseline = baseline_snapshot.get(key)
            # A reused source login may now belong to another publisher. Never
            # retire that numeric key on behalf of an unrelated current claim.
            if not claims and not (
                baseline is not None
                and any(
                    _publisher_token(cohort, recovery_epoch) == baseline.publisher
                    for current in players
                    if current is not player
                    for cohort in owner_claims_for(current)
                )
            ):
                remove_baseline(key, unavailable=unavailable)

        endpoint_logins: dict[int, set[int]] = {}
        endpoint_assignments = Counter(
            agent_id
            for agent_id in (
                *(player.agent_id for player in players),
                *(hero.agent_id for hero in heroes),
                *henchmen,
            )
            if agent_id > 0
        )
        for player in players:
            if player.agent_id > 0:
                endpoint_logins.setdefault(player.agent_id, set()).add(player.login_number)

        records: dict[int, MemberRecord] = {}
        proofs: dict[int, _RemoteOwnerProof] = {}
        for position, player in remote_positions:
            identity = MemberIdentity(
                MemberKind.PLAYER, player.login_number, player.login_number, player.agent_id
            )
            baseline_key = identity.stable_key
            owner_claims = owner_claims_for(player)
            if player.login_number <= 0 or login_counts[player.login_number] != 1:
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote party login identity is missing or duplicated"
                )
                continue
            if not player.connected:
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote party player is disconnected"
                )
                continue
            if player.agent_id > 0 and (
                endpoint_logins.get(player.agent_id) != {player.login_number}
                or endpoint_assignments[player.agent_id] != 1
            ):
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote player endpoint is missing or conflicting"
                )
                continue
            if player.agent_id == local_agent_id or player.login_number == local_login_number:
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote player resolves to the local endpoint"
                )
                continue

            living = _read_living_identity(agent_api, player.agent_id) if player.agent_id > 0 else None
            if living is not None and living[0] != player.login_number:
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote player is not the expected living-agent login"
                )
                continue

            if len(owner_claims) != 1:
                remove_owner_history(player, owner_claims, unavailable=not owner_claims)
                baseline = baseline_snapshot.get(baseline_key)
                records[position] = _unknown_member(
                    identity,
                    EvidenceSource.REMOTE_PLAYER,
                    (
                        "qualified remote publisher owner claims contradict the current roster"
                        if baseline is not None and baseline.publisher in owner_contradictions
                        else "remote player publication owner claim is missing or ambiguous"
                    ),
                )
                continue
            cohort = owner_claims[0]
            owner = cohort.owner
            publisher = _publisher_token(cohort, recovery_epoch)
            conflicting_publisher = any(
                other is not cohort and self._publisher_identity_conflicts(cohort, other)
                for other in contextual
            )
            if conflicting_publisher:
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote publisher identity conflicts with another cohort"
                )
                continue

            if (
                not owner_context_valid(cohort)
                or owner.login_number != player.login_number
                or owner.agent_id <= 0
                or (player.agent_id > 0 and owner.agent_id != player.agent_id)
            ):
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote owner account identity does not match context"
                )
                continue

            if not publication_is_live(captured_at_tick64, owner.last_updated):
                remove_owner_history(player, owner_claims, unavailable=True)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote publication lease is unavailable"
                )
                continue

            current_name = _trustworthy_name(player.character_name)
            published_name = _trustworthy_name(owner.character_name)
            if current_name is not None and published_name is not None and current_name != published_name:
                remove_owner_history(player, owner_claims)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote character name does not corroborate its owner row"
                )
                continue

            # Independent owner evidence must constrain history before any
            # unavailable mapping, living endpoint, or profession can retain it.
            complete_build = len(owner.skill_ids) == 8 and all(skill > 0 for skill in owner.skill_ids)
            if (living is None or living[1] <= 0) and complete_build and owner.professions[0] > 0 and roster_complete:
                baselines = tuple(
                    (key, baseline) for key, baseline in baseline_snapshot.items() if baseline.publisher == publisher
                )
                if baselines:
                    role = _recognize_bar(
                        identity=identity,
                        source=EvidenceSource.REMOTE_PLAYER,
                        profession=owner.professions[0],
                        bar_skill_ids=owner.skill_ids,
                        skill_api=skill_api,
                        skill_type_attack=skill_type_attack,
                        role_skill_ids=role_skill_ids,
                    )
                    anchors = tuple(
                        sorted(
                            set(owner.skill_ids).intersection(
                                _recognized_role_anchors(owner.professions[0], role_skill_ids)
                            )
                        )
                    )
                    contradictions = tuple(
                        key
                        for key, baseline in baselines
                        if role.candidate_role is not baseline.role
                        or owner.professions != baseline.professions
                        or anchors != baseline.relevant_anchors
                    )
                    for key in contradictions:
                        remove_baseline(key)
                    if contradictions:
                        records[position] = _unknown_member(
                            identity,
                            EvidenceSource.REMOTE_PLAYER,
                            "remote published build contradicts its qualified baseline",
                        )
                        continue

            if living is None:
                remove_owner_history(player, owner_claims, unavailable=True)
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_PLAYER, "remote living endpoint is unavailable"
                )
                continue

            current_professions = (living[1], living[2])
            if current_professions[0] <= 0 or owner.professions != current_professions:
                remove_owner_history(player, owner_claims, unavailable=current_professions[0] <= 0)
                records[position] = _unknown_member(
                    identity,
                    EvidenceSource.REMOTE_PLAYER,
                    "remote owner professions do not agree with its current living agent",
                )
                continue

            candidate = _recognize_bar(
                identity=identity,
                source=EvidenceSource.REMOTE_PLAYER,
                profession=current_professions[0],
                bar_skill_ids=owner.skill_ids,
                skill_api=skill_api,
                skill_type_attack=skill_type_attack,
                role_skill_ids=role_skill_ids,
            )
            previous_generation = self._remote_publisher_generations.get(player.login_number)
            if previous_generation is None:
                provenance_generation = 1
            elif previous_generation[0] == publisher:
                provenance_generation = previous_generation[1]
            else:
                provenance_generation = previous_generation[1] + 1
            self._remote_publisher_generations[player.login_number] = (publisher, provenance_generation)
            proof = _RemoteOwnerProof(
                player.login_number,
                player.agent_id,
                cohort,
                publisher,
                provenance_generation,
                current_professions,
                candidate,
            )
            proofs[player.login_number] = proof
            record = MemberRecord(
                identity=identity,
                role=candidate.candidate_role,
                candidate_role=candidate.candidate_role,
                evidence_source=EvidenceSource.REMOTE_PLAYER,
                reason=candidate.reason,
                primary_profession=current_professions[0],
                anchor_skill_ids=candidate.anchor_skill_ids,
                remote_provenance_generation=provenance_generation,
            )

            if len(owner.skill_ids) != 8 or any(skill <= 0 for skill in owner.skill_ids):
                remove_owner_history(player, owner_claims, unavailable=True)
                records[position] = _replace_record_role(
                    record, CleansingRole.UNKNOWN, "remote build read is incomplete"
                )
                continue

            if is_outpost:
                if self._transition is not None and baseline_key in self._transition.retired:
                    records[position] = _replace_record_role(
                        record, CleansingRole.UNKNOWN, "source transition member was retired"
                    )
                    continue
                if candidate.candidate_role is CleansingRole.UNKNOWN:
                    remove_owner_history(player, owner_claims)
                    records[position] = record
                    continue
                current_anchors = tuple(
                    sorted(set(owner.skill_ids).intersection(_recognized_role_anchors(current_professions[0], role_skill_ids)))
                )
                self._candidate_remote[baseline_key] = _RemotePlayerBaseline(
                    publisher,
                    candidate.candidate_role,
                    current_professions,
                    current_anchors,
                    local_character_identity,
                    local_character_uuid,
                    party_id,
                    map_signature[0],
                    (
                        self._transition.generation
                        if self._transition is not None and self._transition.started_at is not None
                        else self._lifecycle_epoch
                    ),
                )
                records[position] = _replace_record_role(
                    record, candidate.candidate_role, candidate.reason + "; ready-outpost remote baseline"
                )
                continue

            if not is_explorable:
                remove_owner_history(player, owner_claims)
                records[position] = _replace_record_role(
                    record, CleansingRole.UNKNOWN, "no continuous ready-outpost remote baseline proves this role"
                )
                continue

            publisher_baselines = tuple(
                (candidate_key, candidate_baseline)
                for candidate_key, candidate_baseline in baseline_snapshot.items()
                if candidate_key[0] is MemberKind.PLAYER
                and candidate_baseline.publisher == publisher
                and candidate_key not in deferred_baseline_removals
            )
            changed_destination_epochs = tuple(
                (candidate_key, candidate_baseline)
                for candidate_key, candidate_baseline in publisher_baselines
                if candidate_baseline.destination_map_id == map_signature[0]
                and candidate_baseline.destination_lifecycle_epoch == self._lifecycle_epoch
                and candidate_baseline.destination_instance_epoch != cohort.instance_epoch
            )
            for candidate_key, _candidate_baseline in changed_destination_epochs:
                remove_baseline(candidate_key)
            if changed_destination_epochs:
                for candidate_key, _candidate_baseline in publisher_baselines:
                    remove_baseline(candidate_key)
                records[position] = _replace_record_role(
                    record,
                    CleansingRole.UNKNOWN,
                    "remote publisher instance epoch changed after destination admission",
                )
                continue

            baseline_candidates: list[_RemoteBaselineReassociation] = []
            for candidate_key, candidate_baseline in publisher_baselines:
                initial_destination_admission = (
                    candidate_baseline.destination_map_id is None
                    and candidate_baseline.destination_lifecycle_epoch is None
                    and candidate_baseline.destination_instance_epoch is None
                    and transition_expected
                    and candidate_baseline.outpost_map_id == transition_source_map_id
                    and self._transition is not None
                    and candidate_baseline.lifecycle_epoch == self._transition.generation
                )
                continued_destination_validation = (
                    candidate_baseline.destination_map_id == map_signature[0]
                    and candidate_baseline.destination_lifecycle_epoch == self._lifecycle_epoch
                    and candidate_baseline.destination_instance_epoch == cohort.instance_epoch
                )
                if initial_destination_admission or continued_destination_validation:
                    baseline_candidates.append(
                        _RemoteBaselineReassociation(
                            position,
                            candidate_key,
                            baseline_key,
                            candidate_baseline,
                            record,
                        )
                    )

            if len(baseline_candidates) > 1:
                for association in baseline_candidates:
                    remove_baseline(association.source_key)
                records[position] = _replace_record_role(
                    record, CleansingRole.UNKNOWN, "multiple remote baselines match publisher continuity"
                )
                continue

            if len(baseline_candidates) != 1:
                for candidate_key, _candidate_baseline in publisher_baselines:
                    remove_baseline(candidate_key)
                records[position] = _replace_record_role(
                    record,
                    CleansingRole.UNKNOWN,
                    "no continuous ready-outpost remote baseline proves this role",
                )
                continue

            association = baseline_candidates[0]
            source_key = association.source_key
            baseline = baseline_snapshot[source_key]
            if (
                baseline.local_character_identity != local_character_identity
                or baseline.local_character_uuid != local_character_uuid
                or baseline.party_id != party_id
            ):
                remove_baseline(source_key)
                records[position] = _replace_record_role(
                    record, CleansingRole.UNKNOWN, "remote baseline does not match the current local character or party"
                )
                continue

            current_anchors = tuple(
                sorted(set(owner.skill_ids).intersection(_recognized_role_anchors(current_professions[0], role_skill_ids)))
            )
            if (
                candidate.candidate_role is CleansingRole.UNKNOWN
                or candidate.candidate_role is not baseline.role
                or current_professions != baseline.professions
                or current_anchors != baseline.relevant_anchors
            ):
                remove_baseline(source_key)
                records[position] = _replace_record_role(
                    record, CleansingRole.UNKNOWN, "current remote role contradicts its ready-outpost baseline"
                )
                continue

            accepted_baseline = _RemotePlayerBaseline(
                publisher=baseline.publisher,
                role=baseline.role,
                professions=baseline.professions,
                relevant_anchors=baseline.relevant_anchors,
                local_character_identity=baseline.local_character_identity,
                local_character_uuid=baseline.local_character_uuid,
                party_id=baseline.party_id,
                outpost_map_id=baseline.outpost_map_id,
                lifecycle_epoch=baseline.lifecycle_epoch,
                destination_map_id=map_signature[0],
                destination_lifecycle_epoch=self._lifecycle_epoch,
                destination_instance_epoch=cohort.instance_epoch,
            )
            pending_reassociations.append(
                _RemoteBaselineReassociation(
                    position,
                    source_key,
                    baseline_key,
                    accepted_baseline,
                    _replace_record_role(
                        record,
                        baseline.role,
                        candidate.reason + "; current remote bar matches ready-outpost anchors",
                    ),
                )
            )

        current_remote_logins = {player.login_number for _, player in remote_positions}
        if is_explorable:
            destination_counts = Counter(plan.destination_key for plan in pending_reassociations)
            source_counts = Counter(plan.source_key for plan in pending_reassociations)
            rejected_positions = {
                plan.position
                for plan in pending_reassociations
                if destination_counts[plan.destination_key] > 1
                or source_counts[plan.source_key] > 1
                or plan.source_key in deferred_baseline_removals
            }
            active_reassociations = [
                plan for plan in pending_reassociations if plan.position not in rejected_positions
            ]

            # These dictionaries reserve historical proof, not current logins.
            # Resolve staged retirement before classifying any destination, then
            # follow publisher movement rather than a possibly reused numeric key.
            for plan in pending_reassociations:
                if plan.position in rejected_positions:
                    remove_publisher_history(plan.baseline.publisher)
            historical_occupants: dict[tuple[MemberKind, int, int], set[_PublisherToken]] = {}
            transition = self._transition
            retired_publishers = {
                baseline.publisher for key, baseline in baseline_snapshot.items() if key in deferred_baseline_removals
            }
            if transition is not None:
                retired_publishers.update(
                    baseline.publisher for key, baseline in transition.remote if key in transition.retired
                )
            for key, baseline in (
                *baseline_snapshot.items(),
                *(transition.remote if transition is not None else ()),
            ):
                if baseline.publisher in retired_publishers:
                    continue
                historical_occupants.setdefault(key, set()).add(baseline.publisher)
            blocked_positions: set[int] = set()

            while True:
                moving_publishers = {plan.baseline.publisher for plan in active_reassociations}
                conflicts = tuple(
                    plan
                    for plan in active_reassociations
                    if historical_occupants.get(plan.destination_key, set())
                    - moving_publishers
                    - {plan.baseline.publisher}
                )
                if not conflicts:
                    break
                # Unresolved historical ownership blocks admission, but supplies
                # no positive contradiction against an independently valid owner.
                blocked_positions.update(plan.position for plan in conflicts)
                active_reassociations = [
                    plan for plan in active_reassociations if plan.position not in blocked_positions
                ]

            current_publishers = {proof.publisher for proof in proofs.values()}
            baseline_removals = set(deferred_baseline_removals)
            baseline_removals.update(
                key
                for key, baseline in baseline_snapshot.items()
                if key[0] is not MemberKind.PLAYER
                or (roster_complete and key[1] not in current_remote_logins and not self._retain_remote_candidate(key))
                or (baseline.publisher not in current_publishers and not self._retain_remote_candidate(key))
            )
            baseline_removals.update(
                plan.source_key
                for plan in pending_reassociations
                if plan.position in rejected_positions
            )
            moving_sources = {plan.source_key for plan in active_reassociations}
            for key in baseline_removals - moving_sources:
                baseline = baseline_snapshot.get(key)
                if baseline is not None:
                    remove_publisher_history(baseline.publisher)
            baseline_removals.update(deferred_baseline_removals)

            updated_baselines = dict(baseline_snapshot)
            for key in baseline_removals:
                updated_baselines.pop(key, None)
            for plan in active_reassociations:
                updated_baselines.pop(plan.source_key, None)
            for plan in active_reassociations:
                updated_baselines[plan.destination_key] = plan.baseline
                records[plan.position] = plan.record
            for plan in pending_reassociations:
                if plan.position in rejected_positions or plan.position in blocked_positions:
                    records[plan.position] = _replace_record_role(
                        plan.record,
                        CleansingRole.UNKNOWN,
                        "destination baseline reassociation conflicts with another publisher or identity",
                    )

            self._candidate_remote.clear()
            self._candidate_remote.update(updated_baselines)
            retired_publishers = {baseline.publisher for baseline in baseline_snapshot.values()} - {
                baseline.publisher for baseline in updated_baselines.values()
            }
            for key, origin in tuple(self._candidate_origins.items()):
                if origin.publisher in retired_publishers:
                    self._candidate_origins.pop(key, None)
        else:
            for baseline_key in tuple(self._candidate_remote):
                if baseline_key[0] is not MemberKind.PLAYER or (
                    roster_complete and baseline_key[1] not in current_remote_logins
                ):
                    self._candidate_remote.pop(baseline_key, None)
        return records, proofs

    @staticmethod
    def _publisher_identity_conflicts(left: _PublishedCohort, right: _PublishedCohort) -> bool:
        left_owner = left.owner
        right_owner = right.owner
        same_email = bool(left_owner.account_email and right_owner.account_email) and (
            left_owner.account_email.strip().casefold() == right_owner.account_email.strip().casefold()
        )
        same_window = left_owner.key_hwnd > 0 and left_owner.key_hwnd == right_owner.key_hwnd
        same_uuid = any(left.character_uuid) and left.character_uuid == right.character_uuid
        same_incarnation = any(left.incarnation) and left.incarnation == right.incarnation
        return same_email or same_window or same_uuid or same_incarnation

    def _retire_local_owner_identity_contradiction(
        self, cohort: _PublishedCohort, recovery_epoch: int, login_number: int, agent_id: int, captured_at_tick64: int
    ) -> bool:
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

        owner = cohort.owner
        mismatch = (owner.login_number > 0 and owner.login_number != login_number) or (
            owner.agent_id > 0 and owner.agent_id != agent_id
        )
        if (
            mismatch
            and owner.last_updated == cohort.published_tick
            and publication_is_live(captured_at_tick64, cohort.published_tick)
        ):
            self._retire_publisher(_publisher_token(cohort, recovery_epoch))
        return mismatch

    def _evaluate_local_witness_heroes(
        self,
        *,
        reads: tuple[_LocalHeroWitnessRead, ...],
        records: tuple[MemberRecord, ...],
        players: tuple[_PartyPlayerEvidence, ...],
        heroes: tuple[_PartyHeroEvidence, ...],
        henchmen: tuple[int, ...],
        duplicate_hero_keys: set[tuple[int, int]],
        cohorts: tuple[_PublishedCohort, ...],
        recovery_epoch: int,
        captured_at_tick64: int,
        map_signature: tuple[int, int, int, int],
        party_id: int,
        local_login_number: int,
        local_agent_id: int,
        local_character_uuid: tuple[int, int, int, int],
        local_account_email: str,
        local_hwnd: int,
        transition_expected: bool,
        is_outpost: bool,
        agent_api: object,
        skill_api: object,
        skill_type_attack: int,
        role_skill_ids: CleansingSkillIDs,
        observation: _LocalWitnessObservation | None = None,
    ) -> tuple[
        dict[int, MemberRecord],
        tuple[_RemoteHeroProof | _OutpostHeroProof, ...],
        _RemoteOwnerProof | None,
        dict[tuple[MemberKind, int, int], _Baseline],
    ]:
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

        contextual = tuple(
            cohort
            for cohort in cohorts
            if cohort.instance_type == (0 if is_outpost else 1)
            and cohort.owner.map_signature == map_signature
            and cohort.owner.party_id == party_id
        )
        qualified_publishers = {
            baseline.witness_origin.publisher
            for baseline in self._candidate_local.values()
            if baseline.witness_origin is not None
        }
        claims = tuple(
            cohort
            for cohort in contextual
            if cohort.owner.login_number == local_login_number
            or cohort.owner.agent_id == local_agent_id
            or _publisher_token(cohort, recovery_epoch) in qualified_publishers
        )
        _local_witness_note(
            observation,
            cohorts=len(cohorts),
            contextual=len(contextual),
            claims=len(claims),
        )
        if len(claims) != 1:
            if not claims:
                self._begin_waiting()
            _local_witness_note(
                observation,
                owner="COHORT_MISSING" if not claims else "COHORT_AMBIGUOUS",
            )
            return {}, (), None, {}
        cohort = claims[0]
        owner = cohort.owner
        living = _read_living_identity(agent_api, local_agent_id)
        if (
            _local_witness_reject(observation, "RECOVERY_EPOCH", recovery_epoch <= 0)
            or _local_witness_reject(observation, "HWND", local_hwnd <= 0)
            or _local_witness_reject(observation, "UUID", not any(local_character_uuid))
            or _local_witness_reject(observation, "INCARNATION", len(cohort.incarnation) != 16)
            or _local_witness_reject(observation, "INCARNATION", not any(cohort.incarnation))
            or _local_witness_reject(observation, "EPOCH", cohort.instance_epoch <= 0)
            or _local_witness_reject(
                observation,
                "COHORT_UUID",
                cohort.character_uuid != local_character_uuid,
            )
            or _local_witness_reject(observation, "OWNER_UUID", owner.character_uuid != local_character_uuid)
            or _local_witness_reject(observation, "OWNER_HWND", owner.key_hwnd != local_hwnd)
            or _local_witness_reject(
                observation,
                "OWNER_EMAIL",
                owner.account_email.strip().casefold() != local_account_email,
            )
            or _local_witness_reject(observation, "OWNER_TYPE", not owner.is_slot_active)
            or _local_witness_reject(observation, "OWNER_TYPE", not owner.is_account)
            or _local_witness_reject(observation, "OWNER_TYPE", owner.is_hero)
            or _local_witness_reject(observation, "OWNER_TYPE", owner.is_pet)
            or _local_witness_reject(observation, "OWNER_TYPE", owner.is_npc)
            or _local_witness_reject(observation, "OWNER_KEY", owner.key_entity_type != 0)
            or _local_witness_reject(observation, "OWNER_KEY", owner.key_local_index != 0)
            or _local_witness_reject(observation, "OWNER_SLOT", owner.slot_index != owner.slot_number)
            or _local_witness_reject(observation, "OWNER_PARENT", owner.owner_agent_id != 0)
            or _local_witness_reject(observation, "OWNER_HERO", owner.hero_id != 0)
            or _local_witness_reject(
                observation,
                "PUBLISHER_CONFLICT",
                any(other is not cohort and self._publisher_identity_conflicts(cohort, other) for other in contextual),
            )
            or _local_witness_reject(
                observation,
                "OWNER_ROSTER",
                sum(
                    player.login_number == local_login_number and player.connected and player.agent_id == local_agent_id
                    for player in players
                )
                != 1,
            )
            or _local_witness_reject(
                observation,
                "OWNER_LOGIN",
                self._retire_local_owner_identity_contradiction(
                    cohort, recovery_epoch, local_login_number, local_agent_id, captured_at_tick64
                ),
            )
            or _local_witness_reject(observation, "OWNER_LOGIN", owner.login_number != local_login_number)
            or _local_witness_reject(observation, "OWNER_AGENT", owner.agent_id != local_agent_id)
            or _local_witness_reject(observation, "OWNER_TICK", owner.last_updated != cohort.published_tick)
            or _local_witness_reject(
                observation,
                "LEASE",
                not publication_is_live(captured_at_tick64, cohort.published_tick),
            )
            or _local_witness_reject(observation, "OWNER_LIVING", living is None)
            or _local_witness_reject(
                observation,
                "OWNER_LIVING_LOGIN",
                cast(tuple[int, int, int], living)[0] != local_login_number,
            )
            or _local_witness_reject(
                observation,
                "OWNER_PROFESSION",
                (
                    cast(tuple[int, int, int], living)[1],
                    cast(tuple[int, int, int], living)[2],
                )
                != owner.professions,
            )
        ):
            return {}, (), None, {}
        _local_witness_note(observation, owner="OK")
        publisher = _publisher_token(cohort, recovery_epoch)
        local_owner = _RemoteOwnerProof(
            local_login_number,
            local_agent_id,
            cohort,
            publisher,
            0,
            owner.professions,
            RoleRecognition(CleansingRole.UNKNOWN, "local publisher identity", ()),
        )
        # Reuse owner-scoped hero checks; the resulting records retain local authority below.
        published_records, proofs = self._evaluate_remote_heroes(
            heroes=heroes,
            remote_positions=tuple((read.party_position - 1, read.hero) for read in reads),
            duplicate_hero_keys=duplicate_hero_keys,
            players=players,
            henchmen=henchmen,
            cohorts=cohorts,
            owner_proofs={local_login_number: local_owner},
            captured_at_tick64=captured_at_tick64,
            map_signature=map_signature,
            party_id=party_id,
            local_agent_id=local_agent_id,
            agent_api=agent_api,
            skill_api=skill_api,
            skill_type_attack=skill_type_attack,
            role_skill_ids=role_skill_ids,
            observation=observation,
        )
        selected: dict[int, MemberRecord] = {}
        baselines: dict[tuple[MemberKind, int, int], _Baseline] = {}
        for read in reads:
            record = published_records[read.party_position - 1]
            if self._transition is not None and record.identity.stable_key in self._transition.retired:
                continue
            witness = _qualified_hero_witness(
                cohort,
                read.hero.hero_id,
                captured_at_tick64,
                observation,
                read.party_position,
            )
            if witness is None or record.role is CleansingRole.UNKNOWN:
                continue
            if is_outpost:
                if read.skill_ids != witness.skill_ids:
                    _local_witness_note(observation, read.party_position, bar=0, gate="BAR_MISMATCH")
                    continue
                _local_witness_note(observation, read.party_position, bar=1)
                origin = _LocalWitnessOrigin(publisher, witness)
                baseline = _Baseline(
                    record.role,
                    witness.primary,
                    tuple(
                        sorted(
                            set(read.skill_ids).intersection(_recognized_role_anchors(witness.primary, role_skill_ids))
                        )
                    ),
                    origin,
                )
            else:
                baseline = self._candidate_local.get(record.identity.stable_key)
                origin = read.origin
                child = next((proof.child for proof in proofs if proof.identity == record.identity), None)
                if (
                    baseline is None
                    or origin is None
                    or origin.publisher != publisher
                    or origin.witness != witness
                    or (origin.destination_epoch is None and not transition_expected)
                    or (origin.destination_epoch is not None and origin.destination_epoch != cohort.instance_epoch)
                    or child is None
                    or child.skill_ids != read.skill_ids
                    or records[read.record_index].role is not record.role
                ):
                    if origin is not None and (
                        origin.publisher != publisher
                        or origin.witness != witness
                        or origin.destination_epoch is not None
                        and origin.destination_epoch != cohort.instance_epoch
                        or child is not None
                        and len(child.skill_ids) == 8
                        and all(child.skill_ids)
                        and child.skill_ids != read.skill_ids
                    ):
                        self._candidate_local.pop(record.identity.stable_key, None)
                    continue
                baseline = replace(baseline, witness_origin=replace(origin, destination_epoch=cohort.instance_epoch))
            selected[read.record_index] = replace(
                record,
                evidence_source=EvidenceSource.LOCAL_HERO,
                remote_provenance_generation=None,
            )
            baselines[record.identity.stable_key] = baseline
            _local_witness_note(observation, read.party_position, opening=1, gate="ACCEPTED")
        return selected, proofs, local_owner, baselines

    def _evaluate_remote_heroes(
        self,
        *,
        heroes: tuple[_PartyHeroEvidence, ...],
        remote_positions: tuple[tuple[int, _PartyHeroEvidence], ...],
        duplicate_hero_keys: set[tuple[int, int]],
        players: tuple[_PartyPlayerEvidence, ...],
        henchmen: tuple[int, ...],
        cohorts: tuple[_PublishedCohort, ...],
        owner_proofs: dict[int, _RemoteOwnerProof],
        captured_at_tick64: int,
        map_signature: tuple[int, int, int, int],
        party_id: int,
        local_agent_id: int,
        agent_api: object,
        skill_api: object,
        skill_type_attack: int,
        role_skill_ids: CleansingSkillIDs,
        endpoint_observation: _EndpointRead | None = None,
        observation: _LocalWitnessObservation | None = None,
        read_only: bool = False,
    ) -> tuple[dict[int, MemberRecord], tuple[_RemoteHeroProof | _OutpostHeroProof, ...]]:
        from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountPublication import BuildWitnessKind
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

        contextual = tuple(
            cohort
            for cohort in cohorts
            if cohort.owner.map_signature == map_signature and cohort.owner.party_id == party_id
        )
        assigned_agents = Counter(
            agent_id
            for agent_id in (
                *(player.agent_id for player in players),
                *(hero.agent_id for hero in heroes),
                *henchmen,
            )
            if agent_id > 0
        )
        records: dict[int, MemberRecord] = {}
        proofs: list[_RemoteHeroProof | _OutpostHeroProof] = []

        for position, hero in remote_positions:
            if endpoint_observation is not None:
                endpoint_observation["gate"] = "ROSTER"
            identity = MemberIdentity(
                MemberKind.HERO, hero.owner_login_number, hero.hero_id, hero.agent_id
            )
            if (
                hero.owner_login_number <= 0
                or hero.hero_id <= 0
                or hero.agent_id <= 0
                or (hero.owner_login_number, hero.hero_id) in duplicate_hero_keys
                or hero.agent_id == local_agent_id
                or assigned_agents[hero.agent_id] != 1
            ):
                if hero.agent_id > 0:
                    if not read_only:
                        self._retire_hero_candidate(identity)
                _local_witness_note(observation, position + 1, gate="HERO_IDENTITY")
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_HERO, "remote hero roster identity or endpoint is conflicting"
                )
                continue
            owner_proof = owner_proofs.get(hero.owner_login_number)
            if owner_proof is None:
                _local_witness_note(observation, position + 1, gate="HERO_OWNER")
                if endpoint_observation is not None:
                    endpoint_observation["gate"] = "OWNER"
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_HERO, "remote hero owner identity is not proven"
                )
                continue

            living = _read_living_identity(agent_api, hero.agent_id, endpoint_observation, verify_hero_identity=True)
            is_outpost = owner_proof.cohort.instance_type == 0
            if living is None and not is_outpost:
                _local_witness_note(observation, position + 1, gate="HERO_ENDPOINT")
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_HERO, "remote hero endpoint is not a current LivingAgent"
                )
                continue

            claims: list[tuple[_PublishedCohort, _PublishedAccount]] = []
            for cohort in contextual:
                if cohort.instance_type != owner_proof.cohort.instance_type:
                    continue
                for child in cohort.children:
                    shares_owner_identity = (
                        cohort.owner.key_hwnd == owner_proof.cohort.owner.key_hwnd
                        or child.owner_agent_id == owner_proof.agent_id
                    )
                    shares_hero_identity = child.hero_id == hero.hero_id or child.key_local_index == hero.hero_id
                    if child.agent_id == hero.agent_id or (shares_owner_identity and shares_hero_identity):
                        claims.append((cohort, child))
            if endpoint_observation is not None:
                endpoint_observation["children"] = min(len(claims), 9)
            if (len(claims) != 1 or claims[0][0] is not owner_proof.cohort) and not (is_outpost and not claims):
                if claims:
                    if not read_only:
                        self._retire_hero_candidate(identity, owner_proof.publisher)
                _local_witness_note(observation, position + 1, gate="CHILD_CLAIM")
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_HERO, "remote hero publication child claim is missing or ambiguous"
                )
                continue
            cohort = owner_proof.cohort
            child = claims[0][1] if claims else None
            owner = cohort.owner
            child_semantics_valid = child is None or (
                child.is_slot_active
                and child.is_hero
                and not child.is_account
                and not child.is_pet
                and not child.is_npc
                and child.key_hwnd == owner.key_hwnd
                and child.key_entity_type == 1
                and child.key_local_index == hero.hero_id
                and child.slot_index == child.slot_number
                and child.agent_id == hero.agent_id
                and child.owner_agent_id == owner_proof.agent_id
                and child.hero_id == hero.hero_id
                and child.login_number == 0
                and child.account_email.strip().casefold() == owner.account_email.strip().casefold()
                and child.map_signature == map_signature
                and child.party_id == party_id
                and owner.agent_id == owner_proof.agent_id
                and owner.login_number == hero.owner_login_number
                and cohort.instance_type == owner_proof.cohort.instance_type
                and cohort.instance_epoch == owner_proof.cohort.instance_epoch
                and cohort.published_tick == owner_proof.cohort.published_tick
                and child.last_updated == owner.last_updated
                and publication_is_live(captured_at_tick64, child.last_updated)
            )
            if not child_semantics_valid:
                if not read_only:
                    self._retire_hero_candidate(identity, owner_proof.publisher)
                _local_witness_note(observation, position + 1, gate="CHILD_SEMANTICS")
                records[position] = _unknown_member(
                    identity, EvidenceSource.REMOTE_HERO, "remote hero child does not match its owner cohort"
                )
                continue

            witness_matches = tuple(
                witness
                for witness in cohort.witnesses
                if witness.kind == int(BuildWitnessKind.OUTPOST_BUILD_WITNESS.value)
                and witness.hero_id == hero.hero_id
            )
            if endpoint_observation is not None:
                endpoint_observation["witnesses"] = min(len(witness_matches), 9)
            witness = _qualified_hero_witness(cohort, hero.hero_id, captured_at_tick64, observation, position + 1)
            if witness is None:
                if not read_only:
                    self._retire_hero_candidate(identity, owner_proof.publisher)
            if is_outpost:
                if (
                    witness is None
                    or _local_witness_reject(
                        observation,
                        "ENDPOINT_CONTRADICTION",
                        (
                            living is not None
                            and (living[0] != 0 or (living[1], living[2]) != (witness.primary, witness.secondary))
                        ),
                        position + 1,
                    )
                    or _local_witness_reject(
                        observation,
                        "CHILD_CONTRADICTION",
                        (
                            child is not None
                            and (
                                child.professions != (witness.primary, witness.secondary)
                                or child.skill_ids != witness.skill_ids
                            )
                        ),
                        position + 1,
                    )
                ):
                    rejected = _unknown_member(
                        identity,
                        EvidenceSource.REMOTE_HERO,
                        "outpost witness or available hero evidence is inconsistent",
                    )
                    if (
                        witness is not None
                        and child is not None
                        and child.professions == (witness.primary, witness.secondary)
                    ):
                        current_role = _recognize_bar(
                            identity=identity,
                            source=EvidenceSource.REMOTE_HERO,
                            profession=child.professions[0],
                            bar_skill_ids=child.skill_ids,
                            skill_api=skill_api,
                            skill_type_attack=skill_type_attack,
                            role_skill_ids=role_skill_ids,
                        )
                        rejected = replace(
                            rejected,
                            candidate_role=current_role.candidate_role,
                            reason="current remote hero role does not agree with its same-cohort outpost witness",
                            primary_profession=child.professions[0],
                            anchor_skill_ids=current_role.anchor_skill_ids,
                        )
                        original_role = _recognize_bar(
                            identity=identity,
                            source=EvidenceSource.REMOTE_HERO,
                            profession=witness.primary,
                            bar_skill_ids=witness.skill_ids,
                            skill_api=skill_api,
                            skill_type_attack=skill_type_attack,
                            role_skill_ids=role_skill_ids,
                        )
                        _local_witness_note(
                            observation,
                            position + 1,
                            role=int(original_role.candidate_role is not CleansingRole.UNKNOWN),
                        )
                        if original_role.candidate_role is CleansingRole.UNKNOWN:
                            rejected = replace(
                                rejected,
                                reason=rejected.reason + "; original witness role is UNKNOWN: " + original_role.reason,
                            )
                    records[position] = rejected
                    continue
                original_role = _recognize_bar(
                    identity=identity,
                    source=EvidenceSource.REMOTE_HERO,
                    profession=witness.primary,
                    bar_skill_ids=witness.skill_ids,
                    skill_api=skill_api,
                    skill_type_attack=skill_type_attack,
                    role_skill_ids=role_skill_ids,
                )
                _local_witness_note(
                    observation,
                    position + 1,
                    role=int(original_role.candidate_role is not CleansingRole.UNKNOWN),
                )
                if original_role.candidate_role is CleansingRole.UNKNOWN:
                    _local_witness_note(observation, position + 1, gate="ORIGINAL_UNSUPPORTED")
                proofs.append(_OutpostHeroProof(identity, cohort, (witness.primary, witness.secondary), child))
                records[position] = MemberRecord(
                    identity=identity,
                    role=original_role.candidate_role,
                    candidate_role=original_role.candidate_role,
                    evidence_source=EvidenceSource.REMOTE_HERO,
                    reason="qualified owner outpost witness; " + original_role.reason,
                    primary_profession=witness.primary,
                    anchor_skill_ids=original_role.anchor_skill_ids,
                    remote_provenance_generation=owner_proof.provenance_generation,
                )
                continue
            if living is None or child is None:
                continue  # Destination proofs always require both current surfaces.
            current_professions = (living[1], living[2])
            if (
                witness is None
                or living[0] != 0
                or current_professions[0] <= 0
                or child.professions != current_professions
                or (
                    witness_matches
                    and (witness_matches[0].primary, witness_matches[0].secondary) != current_professions
                )
            ):
                if not read_only:
                    self._retire_hero_candidate(identity, owner_proof.publisher)
                records[position] = _unknown_member(
                    identity,
                    EvidenceSource.REMOTE_HERO,
                    "remote hero professions or owner outpost witness are unavailable or inconsistent",
                    current_professions[0],
                )
                continue

            assert witness is not None
            proof = _RemoteHeroProof(identity, cohort, child, current_professions)
            proofs.append(proof)
            current_role = _recognize_bar(
                identity=identity,
                source=EvidenceSource.REMOTE_HERO,
                profession=current_professions[0],
                bar_skill_ids=child.skill_ids,
                skill_api=skill_api,
                skill_type_attack=skill_type_attack,
                role_skill_ids=role_skill_ids,
            )
            original_role = _recognize_bar(
                identity=identity,
                source=EvidenceSource.REMOTE_HERO,
                profession=witness.primary,
                bar_skill_ids=witness.skill_ids,
                skill_api=skill_api,
                skill_type_attack=skill_type_attack,
                role_skill_ids=role_skill_ids,
            )
            current_anchors = tuple(
                sorted(
                    set(child.skill_ids).intersection(
                        _recognized_role_anchors(current_professions[0], role_skill_ids)
                    )
                )
            )
            if (
                current_role.candidate_role is not CleansingRole.UNKNOWN
                and current_role.candidate_role is original_role.candidate_role
            ):
                records[position] = MemberRecord(
                    identity=identity,
                    role=current_role.candidate_role,
                    candidate_role=current_role.candidate_role,
                    evidence_source=EvidenceSource.REMOTE_HERO,
                    reason="current remote hero role agrees with its same-cohort outpost witness; "
                    + current_role.reason,
                    primary_profession=current_professions[0],
                    anchor_skill_ids=current_role.anchor_skill_ids,
                    remote_provenance_generation=owner_proof.provenance_generation,
                )
            else:
                if len(child.skill_ids) == 8 and all(skill > 0 for skill in child.skill_ids):
                    if not read_only:
                        self._retire_hero_candidate(identity, owner_proof.publisher)
                mismatch = "current remote hero role does not agree with its same-cohort outpost witness"
                if current_role.candidate_role is CleansingRole.UNKNOWN:
                    mismatch += "; " + current_role.reason
                elif original_role.candidate_role is CleansingRole.UNKNOWN:
                    mismatch += "; original witness role is UNKNOWN: " + original_role.reason
                records[position] = MemberRecord(
                    identity=identity,
                    role=CleansingRole.UNKNOWN,
                    candidate_role=current_role.candidate_role,
                    evidence_source=EvidenceSource.REMOTE_HERO,
                    reason=mismatch,
                    primary_profession=current_professions[0],
                    anchor_skill_ids=current_anchors,
                    remote_provenance_generation=owner_proof.provenance_generation,
                )
        return records, tuple(proofs)

    @staticmethod
    def _recheck_final_runtime(
        *,
        opening: _ClosingState,
        local_reads: tuple[_LocalSkillbarRead, ...],
        native_skillbar: object,
        get_hero_agent_id: Callable[[int], int],
        agent_api: object,
        owner_proofs: tuple[_RemoteOwnerProof, ...],
        hero_proofs: tuple[_RemoteHeroProof | _OutpostHeroProof, ...],
        observation: _LocalWitnessObservation | None = None,
    ) -> _ClosingVerification:
        coherent = True
        unavailable = False
        observed: list[_ClosingState] = []
        # Bounded double collection catches mixed reads. This is not an atomic
        # transaction with the game or Native publisher, and never retries.
        for _ in range(2):
            try:
                if local_reads:
                    getattr(native_skillbar, "GetContext")()
                    coherent = int(getattr(native_skillbar, "agent_id")) == opening.local_agent_id and coherent
                    if not coherent:
                        _local_witness_note(observation, final_gate="LOCAL_CONTINUITY")
                for read in local_reads:
                    slots = (
                        getattr(native_skillbar, "skills")
                        if read.party_position == 0
                        else getattr(native_skillbar, "GetHeroSkillbar")(read.party_position)
                    )
                    current_bar = tuple(int(slot.id.id) for slot in slots)
                    mapped = int(get_hero_agent_id(read.party_position)) if read.party_position > 0 else read.agent_id
                    incomplete = len(current_bar) != 8 or not all(current_bar) or mapped <= 0
                    unavailable = unavailable or incomplete
                    if not incomplete and (current_bar != read.skill_ids or mapped != read.agent_id):
                        _local_witness_note(observation, final_gate="LOCAL_CONTINUITY")
                        coherent = False
                    living = _read_living_identity(
                        agent_api, read.agent_id, verify_hero_identity=read.party_position > 0
                    )
                    if living is None:
                        if read.witness is None or opening.instance_type != 0:
                            _local_witness_note(observation, final_gate="HERO_ENDPOINT")
                            unavailable = True
                    elif (
                        living[0] != (opening.local_login_number if read.party_position == 0 else 0)
                        or living[1] != read.primary_profession
                        or (read.witness is not None and living[2] != read.witness.secondary)
                    ):
                        _local_witness_note(observation, final_gate="ENDPOINT_CONTRADICTION")
                        coherent = False
                for owner in owner_proofs:
                    living = _read_living_identity(agent_api, owner.agent_id)
                    if living is None:
                        unavailable = True
                    elif living[0] != owner.login_number or (living[1], living[2]) != owner.professions:
                        _local_witness_note(observation, final_gate="OWNER_LIVING")
                        coherent = False
                for hero in hero_proofs:
                    living = _read_living_identity(agent_api, hero.identity.agent_id, verify_hero_identity=True)
                    if living is None:
                        if not isinstance(hero, _OutpostHeroProof) or opening.instance_type != 0:
                            _local_witness_note(observation, final_gate="HERO_ENDPOINT")
                            unavailable = True
                    elif living[0] != 0 or (living[1], living[2]) != hero.professions:
                        _local_witness_note(observation, final_gate="ENDPOINT_CONTRADICTION")
                        coherent = False
            except Exception:
                _local_witness_note(observation, final_gate="READ_FAILED_CLOSING")
                coherent = False
            # Read runtime after all fallible evidence access, including the final
            # publication read and local skillbar/mapping/endpoint reads above.
            try:
                observed.append(_read_closing_state())
            except Exception:
                _local_witness_note(observation, final_gate="READ_FAILED_CLOSING")
                coherent = False
        if any(
            state.local_agent_id != opening.local_agent_id
            or state.local_login_number != opening.local_login_number
            or state.local_account_email != opening.local_account_email
            for state in observed
        ):
            _local_witness_note(observation, final_gate="CONTROLLED_IDENTITY")
            return _ClosingVerification.CONTROLLED_IDENTITY_CHANGED
        if not coherent or len(observed) != 2 or any(state != opening for state in observed):
            _local_witness_note(observation, final_gate="RUNTIME_REJECTED")
            return _ClosingVerification.RUNTIME_CHANGED
        if unavailable:
            return _ClosingVerification.UNAVAILABLE
        _local_witness_note(observation, final_gate="OK")
        return _ClosingVerification.COHERENT

    def _recheck_remote_evidence(
        self,
        *,
        opening_players: tuple[_PartyPlayerEvidence, ...],
        opening_heroes: tuple[_PartyHeroEvidence, ...],
        opening_henchmen: tuple[int, ...],
        opening_party_size: int,
        opening_party_id: int,
        opening_map_id: int,
        opening_map_signature: tuple[int, int, int, int],
        opening_instance_type: int,
        opening_character_identity: tuple[str, str],
        opening_character_uuid: tuple[int, int, int, int],
        opening_hwnd: int,
        opening_local_agent_id: int,
        opening_local_login_number: int,
        owner_proofs: tuple[_RemoteOwnerProof, ...],
        hero_proofs: tuple[_RemoteHeroProof | _OutpostHeroProof, ...],
        local_witness_reads: tuple[_LocalHeroWitnessRead, ...],
        opening_captured_at_tick64: int,
        skill_api: object,
        skill_type_attack: int,
        role_skill_ids: CleansingSkillIDs,
        current_tick: int,
        observation: _LocalWitnessObservation | None = None,
        decision: _Stage3DecisionCapture | None = None,
        read_only: bool = False,
        final_runtime: Callable[[], _ClosingVerification] | None = None,
        final_diagnostic: Stage3FinalVerificationDiagnostic | None = None,
    ) -> _ClosingVerification:
        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

        closing = _read_closing_state()
        # These are identities within this Refresh, not AgentIDs retained across zoning.
        if (
            closing.local_agent_id != opening_local_agent_id
            or closing.local_login_number != opening_local_login_number
            or closing.local_account_email != opening_character_identity[0]
        ):
            _stage3_failure(decision, "CONTROLLED_IDENTITY", "LOCAL_OWNER")
            return _ClosingVerification.CONTROLLED_IDENTITY_CHANGED
        expected_players = tuple((player.login_number, player.connected, player.agent_id) for player in opening_players)
        expected_heroes = tuple((hero.owner_login_number, hero.hero_id, hero.agent_id) for hero in opening_heroes)
        if (
            not closing.safe_lifecycle
            or closing.map_id != opening_map_id
            or closing.map_signature != opening_map_signature
            or closing.instance_type != opening_instance_type
            or closing.party_id != opening_party_id
            or closing.party_size != opening_party_size
            or closing.players != expected_players
            or closing.heroes != expected_heroes
            or closing.henchmen != opening_henchmen
            or closing.local_character_name != opening_character_identity[1]
            or closing.local_character_uuid != opening_character_uuid
            or closing.local_hwnd != opening_hwnd
        ):
            _stage3_failure(decision, "RUNTIME", "SHARED")
            return _ClosingVerification.RUNTIME_CHANGED

        if not owner_proofs and not hero_proofs:
            if final_runtime is not None:
                return _ClosingVerification.INCOHERENT
            return _ClosingVerification.COHERENT
        if final_diagnostic is not None:
            final_diagnostic.stage = "native"
        result = GLOBAL_CACHE.ShMem.GetNativeAccountSnapshotV3()
        if getattr(result.status, "value", result.status) != "success" or result.snapshot is None:
            try:
                if decision is not None:
                    decision.closing = "PUBLICATION_REJECTED"
            except Exception:
                if decision is not None:
                    decision.failed = True
            _stage3_failure(decision, "PUBLICATION", "SHARED")
            _local_witness_note(observation, closing="PUBLICATION_REJECTED")
            if getattr(result.status, "value", result.status) in ("busy", "unavailable"):
                return _ClosingVerification.UNAVAILABLE
            return _ClosingVerification.INCOHERENT
        snapshot = result.snapshot
        cohorts = _copy_published_cohorts(snapshot)
        recovery_epoch = int(snapshot.recovery_epoch)
        if not read_only:
            self._check_historical_publishers(cohorts, recovery_epoch)
        captured_at_tick64 = int(snapshot.captured_at_tick64)
        # Native capture uses the uncached boot clock, which can advance beyond this frame's timestamp.
        current_tick = get_uncached_tick_count64()
        if type(current_tick) is not int or not 0 <= current_tick <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("Invalid uncached closing timestamp")
        if (
            _stage3_reject(decision, "RECOVERY", "SHARED", recovery_epoch <= 0)
            or captured_at_tick64 < opening_captured_at_tick64
            or captured_at_tick64 > current_tick
        ):
            _stage3_failure(decision, "CAPTURE_TIME", "SHARED")
            return _ClosingVerification.INCOHERENT
        contextual = tuple(
            cohort
            for cohort in cohorts
            if cohort.instance_type == opening_instance_type
            and cohort.owner.map_signature == opening_map_signature
            and cohort.owner.party_id == opening_party_id
        )

        current_owners: dict[int, _RemoteOwnerProof] = {}
        for proof in owner_proofs:
            scope = "LOCAL_OWNER" if proof.login_number == opening_local_login_number else "REMOTE_OWNER"
            claims = tuple(
                cohort
                for cohort in contextual
                if cohort.owner.login_number == proof.login_number or cohort.owner.agent_id == proof.agent_id
            )
            if len(claims) != 1:
                _stage3_failure(decision, "OWNER_CLAIM", scope)
                if not claims:
                    return _ClosingVerification.UNAVAILABLE
                if not read_only:
                    self._retire_publisher(proof.publisher)
                if not read_only:
                    self._closing_preserve_candidates = True
                return _ClosingVerification.INCOHERENT
            cohort = claims[0]
            owner = cohort.owner
            if (
                _stage3_publisher_reject(
                    decision,
                    cohort,
                    recovery_epoch,
                    proof.publisher,
                    scope,
                    _publisher_token(cohort, recovery_epoch) != proof.publisher,
                )
                or _stage3_reject(decision, "INSTANCE_EPOCH", scope, cohort.instance_epoch != proof.cohort.instance_epoch)
                or _stage3_reject(decision, "OWNER_UUID", scope, cohort.character_uuid != owner.character_uuid)
                or _stage3_reject(decision, "OWNER_TYPE", scope, not owner.is_slot_active)
                or _stage3_reject(decision, "OWNER_TYPE", scope, not owner.is_account)
                or _stage3_reject(decision, "OWNER_TYPE", scope, owner.is_hero)
                or _stage3_reject(decision, "OWNER_TYPE", scope, owner.is_pet)
                or _stage3_reject(decision, "OWNER_TYPE", scope, owner.is_npc)
                or _stage3_reject(decision, "OWNER_KEY", scope, owner.key_entity_type != 0)
                or _stage3_reject(decision, "OWNER_KEY", scope, owner.key_local_index != 0)
                or _stage3_reject(decision, "OWNER_SLOT", scope, owner.slot_index != owner.slot_number)
                or _stage3_reject(decision, "OWNER_AGENT", scope, owner.agent_id != proof.agent_id)
                or _stage3_reject(decision, "OWNER_LOGIN", scope, owner.login_number != proof.login_number)
                or _stage3_reject(decision, "OWNER_PARENT", scope, owner.owner_agent_id != 0)
                or _stage3_reject(decision, "OWNER_HERO", scope, owner.hero_id != 0)
                or _stage3_reject(decision, "OWNER_PROFESSION", scope, owner.professions != proof.professions)
                or _stage3_reject(decision, "OWNER_TICK", scope, cohort.published_tick != owner.last_updated)
                or _stage3_reject(
                    decision,
                    "PUBLISHER_CONFLICT",
                    scope,
                    any(other is not cohort and self._publisher_identity_conflicts(cohort, other) for other in contextual),
                )
            ):
                _stage3_failure(decision, "OWNER_PROOF", scope)
                if not read_only:
                    self._retire_publisher(proof.publisher)
                if not read_only:
                    self._closing_preserve_candidates = True
                return _ClosingVerification.INCOHERENT
            if not publication_is_live(current_tick, cohort.published_tick):
                _stage3_failure(decision, "LEASE", scope)
                return _ClosingVerification.UNAVAILABLE
            current = _read_living_identity(Agent, proof.agent_id)
            if current is None or current[0] != proof.login_number or (current[1], current[2]) != proof.professions:
                _stage3_failure(decision, "OWNER_ENDPOINT", scope)
                if current is None:
                    return _ClosingVerification.UNAVAILABLE
                if not read_only:
                    self._retire_publisher(proof.publisher)
                if not read_only:
                    self._closing_preserve_candidates = True
                return _ClosingVerification.INCOHERENT
            current_role = _recognize_bar(
                identity=MemberIdentity(MemberKind.PLAYER, proof.login_number, proof.login_number, proof.agent_id),
                source=EvidenceSource.REMOTE_PLAYER,
                profession=owner.professions[0],
                bar_skill_ids=owner.skill_ids,
                skill_api=skill_api,
                skill_type_attack=skill_type_attack,
                role_skill_ids=role_skill_ids,
            )
            # Local owner bars are not publication authority; remote player bars are.
            if proof.login_number != opening_local_login_number and (
                current_role.candidate_role is not proof.candidate.candidate_role
                or current_role.anchor_skill_ids != proof.candidate.anchor_skill_ids
            ):
                _stage3_failure(decision, "OWNER_ROLE", scope)
                if len(owner.skill_ids) != 8 or not all(owner.skill_ids):
                    return _ClosingVerification.UNAVAILABLE
                if not read_only:
                    self._retire_publisher(proof.publisher)
                if not read_only:
                    self._closing_preserve_candidates = True
                return _ClosingVerification.INCOHERENT
            current_owners[proof.login_number] = replace(proof, cohort=cohort)

        positions = tuple(
            (index, hero)
            for index, hero in enumerate(opening_heroes)
            if any(
                proof.identity.owner_id == hero.owner_login_number and proof.identity.member_id == hero.hero_id
                for proof in hero_proofs
            )
        )
        closing_observation: _LocalWitnessObservation | None = None
        try:
            if decision is not None:
                closing_observation = _LocalWitnessObservation(decision=decision)
                closing_observation.decision_scopes = {
                    position + 1: f"{'LH' if hero.owner_login_number == opening_local_login_number else 'RH'}{position + 1}"
                    for position, hero in positions[:7]
                }
        except Exception:
            if decision is not None:
                decision.failed = True
        records, current_proofs = self._evaluate_remote_heroes(
            heroes=opening_heroes,
            remote_positions=positions,
            duplicate_hero_keys={
                key
                for key, count in Counter((hero.owner_login_number, hero.hero_id) for hero in opening_heroes).items()
                if count > 1
            },
            players=opening_players,
            henchmen=opening_henchmen,
            cohorts=cohorts,
            owner_proofs=current_owners,
            captured_at_tick64=current_tick,
            map_signature=opening_map_signature,
            party_id=opening_party_id,
            local_agent_id=opening_local_agent_id,
            agent_api=Agent,
            skill_api=skill_api,
            skill_type_attack=skill_type_attack,
            role_skill_ids=role_skill_ids,
            observation=closing_observation,
            read_only=read_only,
        )
        for proof in hero_proofs:
            scope = "UNKNOWN"
            try:
                scope = _stage3_hero_scope(decision, proof.identity, opening_heroes, opening_local_login_number)
            except Exception:
                if decision is not None:
                    decision.failed = True
            current_proof = next((current for current in current_proofs if current.identity == proof.identity), None)
            if current_proof is None:
                _stage3_failure(decision, "HERO_PROOF", scope)
                return _ClosingVerification.UNAVAILABLE
            if type(current_proof) is not type(proof):
                owner = current_owners.get(proof.identity.owner_id)
                if not read_only:
                    self._retire_hero_candidate(proof.identity, owner.publisher if owner is not None else None)
                if not read_only:
                    self._closing_preserve_candidates = True
                _stage3_failure(decision, "HERO_PROOF", scope)
                return _ClosingVerification.INCOHERENT
            opening_witness = _qualified_hero_witness(proof.cohort, proof.identity.member_id, opening_captured_at_tick64)
            current_witness = _qualified_hero_witness(current_proof.cohort, proof.identity.member_id, current_tick)
            # Native carries this frozen original through Loading; it never refreshes
            # its revision, observation time or outpost epoch from destination skills.
            if opening_witness is None or current_witness != opening_witness:
                gate = "WITNESS_QUALIFICATION"
                try:
                    if decision is not None and opening_witness is not None and current_witness is not None:
                        for name, code in (
                            ("revision", "WITNESS_REVISION"),
                            ("observed_at_tick64", "WITNESS_TIME"),
                            ("outpost_epoch", "WITNESS_EPOCH"),
                            ("primary", "HERO_PROFESSION"),
                            ("secondary", "HERO_PROFESSION"),
                            ("skill_ids", "WITNESS_BUILD"),
                        ):
                            if getattr(opening_witness, name) != getattr(current_witness, name):
                                gate = code
                                break
                except Exception:
                    if decision is not None:
                        decision.failed = True
                _stage3_failure(decision, gate, scope)
                owner = current_owners.get(proof.identity.owner_id)
                if not read_only:
                    self._retire_hero_candidate(proof.identity, owner.publisher if owner is not None else None)
                if not read_only:
                    self._closing_preserve_candidates = True
                return _ClosingVerification.INCOHERENT
            original_role = _recognize_bar(
                identity=proof.identity,
                source=EvidenceSource.REMOTE_HERO,
                profession=opening_witness.primary,
                bar_skill_ids=opening_witness.skill_ids,
                skill_api=skill_api,
                skill_type_attack=skill_type_attack,
                role_skill_ids=role_skill_ids,
            )
            expected_role = original_role.candidate_role
            if isinstance(proof, _RemoteHeroProof):
                opening_role = _recognize_bar(
                    identity=proof.identity,
                    source=EvidenceSource.REMOTE_HERO,
                    profession=proof.professions[0],
                    bar_skill_ids=proof.child.skill_ids,
                    skill_api=skill_api,
                    skill_type_attack=skill_type_attack,
                    role_skill_ids=role_skill_ids,
                )
                if opening_role.candidate_role is not expected_role:
                    expected_role = CleansingRole.UNKNOWN
                local_read = next(
                    (read for read in local_witness_reads if read.hero.agent_id == proof.identity.agent_id), None
                )
                if (
                    local_read is not None
                    and current_proof.child is not None
                    and current_proof.child.skill_ids != local_read.skill_ids
                ):
                    _stage3_failure(decision, "CHILD_BAR", scope)
                    owner = current_owners.get(proof.identity.owner_id)
                    if not read_only:
                        self._retire_hero_candidate(proof.identity, owner.publisher if owner is not None else None)
                    if not read_only:
                        self._closing_preserve_candidates = True
                    return _ClosingVerification.INCOHERENT
            record = next(record for record in records.values() if record.identity == proof.identity)
            if record.role is not expected_role:
                _stage3_failure(decision, "HERO_ROLE", scope)
                owner = current_owners.get(proof.identity.owner_id)
                if not read_only:
                    self._retire_hero_candidate(proof.identity, owner.publisher if owner is not None else None)
                if not read_only:
                    self._closing_preserve_candidates = True
                return _ClosingVerification.INCOHERENT
        if final_runtime is not None:
            if not read_only or final_runtime() is not _ClosingVerification.COHERENT:
                return _ClosingVerification.INCOHERENT
            # Close Native authority after *all* fallible runtime/skill reads.
            # Equality binds the already canonically checked immutable rows;
            # an intervening renewal is conservatively rejected, never merged.
            result = GLOBAL_CACHE.ShMem.GetNativeAccountSnapshotV3()
            if getattr(result.status, "value", result.status) != "success" or result.snapshot is None:
                _stage3_failure(decision, "FINAL_PUBLICATION", "SHARED")
                return _ClosingVerification.UNAVAILABLE
            final = result.snapshot
            final_cohorts = _copy_published_cohorts(final)
            accepted_at = get_uncached_tick_count64()
            if (
                type(accepted_at) is not int
                or not 0 <= accepted_at <= 0xFFFFFFFFFFFFFFFF
                or int(final.recovery_epoch) != recovery_epoch
                or final_cohorts != cohorts
                or not captured_at_tick64 <= int(final.captured_at_tick64) <= accepted_at
            ):
                _stage3_failure(decision, "FINAL_NATIVE_BINDING", "SHARED")
                return _ClosingVerification.INCOHERENT
            if any(
                not publication_is_live(accepted_at, owner.cohort.published_tick) for owner in current_owners.values()
            ):
                _stage3_failure(decision, "FINAL_LEASE", "SHARED")
                return _ClosingVerification.INCOHERENT
            if any(
                _qualified_hero_witness(proof.cohort, proof.identity.member_id, accepted_at)
                != _qualified_hero_witness(proof.cohort, proof.identity.member_id, current_tick)
                for proof in hero_proofs
            ):
                _stage3_failure(decision, "FINAL_WITNESS", "SHARED")
                return _ClosingVerification.INCOHERENT
        return _ClosingVerification.COHERENT

    def _read_and_recognize_member(
        self,
        *,
        identity: MemberIdentity,
        source: EvidenceSource,
        agent_id: int,
        skill_slots: tuple[object, ...],
        primary_profession: int,
        skill_api: object,
        skill_type_attack: int,
        skill_ids: CleansingSkillIDs,
        character_identity: tuple[str, str],
        is_outpost: bool,
        is_explorable: bool,
        endpoint_observation: _EndpointRead | None = None,
        witness_read_pending: bool = False,
    ) -> MemberRecord:
        try:
            bar_skill_ids = tuple(int(slot.id.id) for slot in skill_slots)  # type: ignore[attr-defined]
        except Exception as error:
            if endpoint_observation is not None:
                endpoint_observation["bar"] = False
            self._candidate_local.pop(identity.stable_key, None)
            return _unknown_member(
                identity,
                source,
                f"skillbar evidence read failed ({type(error).__name__})",
                primary_profession,
            )

        if endpoint_observation is not None:
            endpoint_observation["bar"] = len(bar_skill_ids) == 8 and all(skill_id > 0 for skill_id in bar_skill_ids)
        previous = self._candidate_local.get(identity.stable_key)
        if (
            is_outpost
            and witness_read_pending
            and previous is not None
            and previous.witness_origin is not None
            and primary_profession <= 0
        ):
            return _unknown_member(identity, source, "fresh qualified outpost witness is required", primary_profession)
        if identity.stable_key in self._candidate_local and (
            len(bar_skill_ids) != 8 or not all(bar_skill_ids) or primary_profession <= 0
        ):
            self._begin_waiting()
        if self._retain_local_candidate(identity.stable_key) and (
            len(bar_skill_ids) != 8 or not all(bar_skill_ids) or primary_profession <= 0
        ):
            return _unknown_member(identity, source, "current build read is incomplete", primary_profession)
        weapon_attack_equipped: bool | None = None
        if primary_profession == int(Profession.Ranger) and skill_ids.together_as_one in bar_skill_ids:
            type_read_failed = False
            for bar_skill_id in bar_skill_ids:
                try:
                    skill_type = int(skill_api.GetType(bar_skill_id)[0])  # type: ignore[attr-defined]
                except Exception:
                    type_read_failed = True
                    continue
                if skill_type == skill_type_attack:
                    weapon_attack_equipped = True
                    break
            else:
                weapon_attack_equipped = None if type_read_failed else False

        evidence = RoleEvidence(
            identity=identity,
            source=source,
            primary_profession=primary_profession,
            skill_ids=bar_skill_ids,
            ownership_proven=agent_id > 0,
            weapon_attack_equipped=weapon_attack_equipped,
        )
        recognition = recognize_role(evidence, skill_ids)
        current_record = _role_evidence_record(evidence, recognition)
        character_key = (character_identity[0], character_identity[1])
        if is_outpost:
            if self._transition is not None and identity.stable_key in self._transition.retired:
                return _replace_record_role(
                    current_record, CleansingRole.UNKNOWN, "source transition member was retired"
                )
            if recognition.candidate_role is CleansingRole.UNKNOWN:
                self._candidate_local.pop(identity.stable_key, None)
                return current_record
            self._candidate_local[identity.stable_key] = _Baseline(
                role=recognition.candidate_role,
                profession=primary_profession,
                relevant_anchors=tuple(
                    sorted(set(bar_skill_ids).intersection(_recognized_role_anchors(primary_profession, skill_ids)))
                ),
            )
            return _replace_record_role(
                current_record, recognition.candidate_role, recognition.reason + "; ready-outpost baseline"
            )

        baseline = self._candidate_local.get(identity.stable_key)
        if not is_explorable or baseline is None or self._character_identity != character_key:
            if baseline is not None and (not is_explorable or self._character_identity != character_key):
                self._candidate_local.pop(identity.stable_key, None)
            reason = "no matching ready-outpost baseline proves the current role"
            if recognition.candidate_role is CleansingRole.UNKNOWN:
                reason += "; " + recognition.reason
            return _replace_record_role(
                current_record,
                CleansingRole.UNKNOWN,
                reason,
            )

        current_anchors = tuple(
            sorted(set(bar_skill_ids).intersection(_recognized_role_anchors(primary_profession, skill_ids)))
        )
        if (
            recognition.candidate_role is not baseline.role
            or primary_profession != baseline.profession
            or current_anchors != baseline.relevant_anchors
        ):
            self._candidate_local.pop(identity.stable_key, None)
            mismatch_reason = recognition.reason
            if recognition.candidate_role is baseline.role:
                mismatch_reason = "current role anchors differ from the ready-outpost baseline"
            return _replace_record_role(current_record, CleansingRole.UNKNOWN, mismatch_reason)

        return _replace_record_role(
            current_record,
            baseline.role,
            recognition.reason + "; current bar matches ready-outpost anchors",
        )

    def _publish(
        self,
        *,
        map_id: int | None,
        ready: bool,
        character_identity: tuple[str, str] | None,
        members: tuple[MemberRecord, ...],
        declared_party_size: int | None,
        reason: str,
    ) -> CleansingContextSnapshot:
        global _endpoint_diagnostic_pending, _local_witness_pending
        self._stage3_decision_result = None
        self._stage3_decision_status = "UNAVAILABLE"
        if not members:
            _local_witness_pending = None
        if not ready:
            _endpoint_diagnostic_pending = None
        if self._snapshot.ready and not ready:
            self._lifecycle_epoch += 1
        composition = match_supported_composition(members, declared_party_size)
        candidate = CleansingContextSnapshot(
            revision=self._revision,
            lifecycle_epoch=self._lifecycle_epoch,
            map_id=map_id,
            ready=ready,
            character_identity=character_identity,
            members=members,
            composition=composition,
            reason=reason,
        )
        if candidate == self._snapshot:
            return self._snapshot
        self._revision += 1
        self._snapshot = CleansingContextSnapshot(
            revision=self._revision,
            lifecycle_epoch=self._lifecycle_epoch,
            map_id=map_id,
            ready=ready,
            character_identity=character_identity,
            members=members,
            composition=composition,
            reason=reason,
        )
        return self._snapshot
