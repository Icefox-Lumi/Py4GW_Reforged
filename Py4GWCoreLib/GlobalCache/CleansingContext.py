from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from typing import Iterable

from Py4GWCoreLib.enums_src.GameData_enums import Profession


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
    ("energy_surge", "Energy Surge"),
    ("panic", "Panic"),
    ("ineptitude", "Ineptitude"),
    ("heroic_refrain", "Heroic Refrain"),
    ("blood_is_power", "Blood is Power"),
    ("soul_twisting", "Soul Twisting"),
    ("shelter", "Shelter"),
    ("union", "Union"),
    ("healing_burst", "Healing Burst"),
    ("together_as_one", "Together as One"),
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
    if evidence.source not in (EvidenceSource.LOCAL_PLAYER, EvidenceSource.LOCAL_HERO):
        return RoleRecognition(CleansingRole.UNKNOWN, "role evidence is not from a supported local source", ())
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
    counter = Counter(member.role for member in member_list)
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
    )


class CleansingContext:
    """Publishes local, build-proven cleansing roles and the exact team proof."""

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
        self._role_skill_ids: CleansingSkillIDs | None = None
        self._character_identity: tuple[str, str] | None = None
        self._last_ready_map_id: int | None = None
        self._last_ready_was_outpost = False
        self._last_hero_agents: dict[tuple[int, int], int] = {}
        self._pending_outpost_transition = False

    def GetSnapshot(self) -> CleansingContextSnapshot:
        return self._snapshot

    def GetMember(self, identity: MemberIdentity) -> MemberRecord | None:
        return self._snapshot.get_member(identity)

    def Invalidate(self, reason: str = "context explicitly invalidated") -> CleansingContextSnapshot:
        self._baselines.clear()
        self._pending_outpost_transition = False
        self._last_hero_agents.clear()
        self._character_identity = None
        self._last_ready_map_id = None
        self._last_ready_was_outpost = False
        return self.InvalidatePublishedSnapshot(reason)

    def InvalidatePublishedSnapshot(
        self, reason: str = "runtime lifecycle is unsafe; awaiting fresh evidence"
    ) -> CleansingContextSnapshot:
        """Hide published proof without runtime reads or discarding transition baselines."""
        return self._publish(
            map_id=None,
            ready=False,
            character_identity=None,
            members=(),
            declared_party_size=None,
            reason=reason,
        )

    def Refresh(self) -> CleansingContextSnapshot:
        try:
            return self._refresh_from_runtime()
        except Exception as error:
            self._baselines.clear()
            self._pending_outpost_transition = False
            self._last_hero_agents.clear()
            self._character_identity = None
            if not self._snapshot.ready and not self._snapshot.reason.startswith("runtime evidence read failed"):
                self._lifecycle_epoch += 1
            return self._publish(
                map_id=None,
                ready=False,
                character_identity=None,
                members=(),
                declared_party_size=None,
                reason=f"runtime evidence read failed ({type(error).__name__})",
            )

    def _refresh_from_runtime(self) -> CleansingContextSnapshot:
        import PySkillbar

        from Py4GWCoreLib import GLOBAL_CACHE
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import Map
        from Py4GWCoreLib import Player
        from Py4GWCoreLib.enums_src.GameData_enums import SkillType

        if not Map.IsMapReady() or Map.IsMapLoading() or Map.IsInCinematic():
            self._pending_outpost_transition = self._last_ready_was_outpost
            if not self._pending_outpost_transition:
                self._baselines.clear()
            return self._publish(
                map_id=self._last_ready_map_id,
                ready=False,
                character_identity=self._character_identity,
                members=(),
                declared_party_size=None,
                reason="map is loading or not ready",
            )

        if Map.IsPVP():
            if not self._snapshot.ready and self._snapshot.reason != "PvP context is out of scope":
                self._lifecycle_epoch += 1
            self._baselines.clear()
            self._pending_outpost_transition = False
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
        if map_changed:
            self._lifecycle_epoch += 1
            if not expected_outpost_entry:
                self._baselines.clear()
        elif not self._snapshot.ready and not self._pending_outpost_transition:
            self._baselines.clear()

        if not Player.IsPlayerLoaded() or not GLOBAL_CACHE.Party.IsPartyLoaded():
            if not expected_outpost_entry:
                self._baselines.clear()
            self._pending_outpost_transition = expected_outpost_entry
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
            self._baselines.clear()
            self._pending_outpost_transition = False
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
            self._baselines.clear()
            self._lifecycle_epoch += 1
        self._character_identity = character_identity

        party = GLOBAL_CACHE.Party
        players = tuple(party.GetPlayers())
        heroes = tuple(party.GetHeroes())
        henchmen = tuple(party.GetHenchmen())
        party_size = int(party.GetPartySize())
        if party_size < 0:
            raise ValueError("party size is invalid")

        hero_agents = {
            (int(hero.owner_player_id), int(hero.hero_id)): int(hero.agent_id)
            for hero in heroes
            if int(hero.owner_player_id) > 0 and int(hero.hero_id) > 0
        }
        if self._last_ready_map_id == map_id:
            for stable_key, agent_id in hero_agents.items():
                if stable_key in self._last_hero_agents and self._last_hero_agents[stable_key] != agent_id:
                    self._baselines.pop((MemberKind.HERO, stable_key[0], stable_key[1]), None)

        skill_api = GLOBAL_CACHE.Skill
        if self._role_skill_ids is None:
            self._role_skill_ids = resolve_supported_skill_ids(skill_api.GetID)
        role_skill_ids = self._role_skill_ids
        if role_skill_ids is None:
            raise ValueError("supported skill IDs are unavailable")
        native_skillbar = PySkillbar.Skillbar()
        native_skillbar.GetContext()

        records: list[MemberRecord] = []
        local_player_seen = 0
        for player_member in players:
            login_number = int(player_member.login_number)
            identity = MemberIdentity(MemberKind.PLAYER, login_number, login_number)
            if login_number != local_login_number:
                records.append(
                    _unknown_member(
                        identity,
                        EvidenceSource.NONE,
                        "remote player role recognition is not supported in this stage",
                    )
                )
                continue

            local_player_seen += 1
            identity = MemberIdentity(MemberKind.PLAYER, local_login_number, local_login_number, local_agent_id)
            mapped_agent_id = int(party.Players.GetAgentIDByLoginNumber(local_login_number))
            if (
                local_player_seen != 1
                or mapped_agent_id != local_agent_id
                or int(native_skillbar.agent_id) != local_agent_id
            ):
                self._baselines.pop(identity.stable_key, None)
                records.append(
                    _unknown_member(
                        identity, EvidenceSource.LOCAL_PLAYER, "local player or skillbar ownership is ambiguous"
                    )
                )
                continue

            records.append(
                self._read_and_recognize_member(
                    identity=identity,
                    source=EvidenceSource.LOCAL_PLAYER,
                    agent_id=local_agent_id,
                    skill_slots=tuple(native_skillbar.skills),
                    primary_profession=int(Agent.GetProfessions(local_agent_id)[0]),
                    skill_api=skill_api,
                    skill_type_attack=int(SkillType.Attack),
                    skill_ids=role_skill_ids,
                    character_identity=character_identity,
                    is_outpost=is_outpost,
                    is_explorable=is_explorable,
                )
            )

        if local_player_seen != 1:
            self._baselines.pop((MemberKind.PLAYER, local_login_number, local_login_number), None)

        duplicate_hero_keys = {
            (int(hero.owner_player_id), int(hero.hero_id))
            for hero in heroes
            if sum(
                int(other.owner_player_id) == int(hero.owner_player_id) and int(other.hero_id) == int(hero.hero_id)
                for other in heroes
            )
            > 1
        }
        # Native party positions reserve 0 for the local player; hero rows start at 1.
        for hero_position, hero in enumerate(heroes, start=1):
            owner_id = int(hero.owner_player_id)
            hero_id = int(hero.hero_id)
            hero_agent_id = int(hero.agent_id)
            identity = MemberIdentity(MemberKind.HERO, owner_id, hero_id, hero_agent_id)
            if owner_id != local_login_number:
                records.append(_unknown_member(identity, EvidenceSource.NONE, "hero is not owned by the local player"))
                continue
            if (owner_id, hero_id) in duplicate_hero_keys or hero_id <= 0 or hero_agent_id <= 0:
                self._baselines.pop(identity.stable_key, None)
                records.append(_unknown_member(identity, EvidenceSource.LOCAL_HERO, "local hero identity is ambiguous"))
                continue
            mapped_hero_agent_id = int(party.Heroes.GetHeroAgentIDByPartyPosition(hero_position))
            if mapped_hero_agent_id != hero_agent_id:
                self._baselines.pop(identity.stable_key, None)
                records.append(
                    _unknown_member(
                        identity, EvidenceSource.LOCAL_HERO, "hero skillbar index does not match the party hero"
                    )
                )
                continue

            try:
                hero_skill_slots = tuple(native_skillbar.GetHeroSkillbar(hero_position))
                primary_profession = int(Agent.GetProfessions(hero_agent_id)[0])
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
                    )
                )
            except Exception as error:
                self._baselines.pop(identity.stable_key, None)
                records.append(
                    _unknown_member(
                        identity,
                        EvidenceSource.LOCAL_HERO,
                        f"local hero evidence read failed ({type(error).__name__})",
                    )
                )

        for henchman in henchmen:
            identity = MemberIdentity(MemberKind.HENCHMAN, 0, int(henchman.agent_id), int(henchman.agent_id))
            records.append(_unknown_member(identity, EvidenceSource.NONE, "henchman role recognition is not supported"))

        roster_complete = len(records) == party_size
        if not roster_complete:
            reason = f"party member records incomplete: party reports {party_size}, evidence has {len(records)}"
        elif not any(
            record.identity.kind is MemberKind.PLAYER and record.identity.owner_id == local_login_number
            for record in records
        ):
            reason = "local player is absent from the party member records"
        else:
            reason = "local party evidence refreshed"

        self._pending_outpost_transition = False
        self._last_ready_map_id = map_id
        self._last_ready_was_outpost = is_outpost
        self._last_hero_agents = hero_agents
        return self._publish(
            map_id=map_id,
            ready=roster_complete and local_player_seen == 1,
            character_identity=character_identity,
            members=tuple(records),
            declared_party_size=party_size,
            reason=reason,
        )

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
    ) -> MemberRecord:
        try:
            bar_skill_ids = tuple(int(slot.id.id) for slot in skill_slots)  # type: ignore[attr-defined]
        except Exception as error:
            self._baselines.pop(identity.stable_key, None)
            return _unknown_member(
                identity,
                source,
                f"skillbar evidence read failed ({type(error).__name__})",
                primary_profession,
            )

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
            if recognition.candidate_role is CleansingRole.UNKNOWN:
                self._baselines.pop(identity.stable_key, None)
                return current_record
            self._baselines[identity.stable_key] = _Baseline(
                role=recognition.candidate_role,
                profession=primary_profession,
                relevant_anchors=tuple(
                    sorted(set(bar_skill_ids).intersection(_recognized_role_anchors(primary_profession, skill_ids)))
                ),
            )
            return _replace_record_role(
                current_record, recognition.candidate_role, recognition.reason + "; ready-outpost baseline"
            )

        baseline = self._baselines.get(identity.stable_key)
        if not is_explorable or baseline is None or self._character_identity != character_key:
            if baseline is not None and (not is_explorable or self._character_identity != character_key):
                self._baselines.pop(identity.stable_key, None)
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
            self._baselines.pop(identity.stable_key, None)
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
