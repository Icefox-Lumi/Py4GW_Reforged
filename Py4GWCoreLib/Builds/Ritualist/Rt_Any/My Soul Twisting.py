from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

import PyAgentEvents
import PySystem

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import AgentArray
from Py4GWCoreLib import Allegiance
from Py4GWCoreLib import BuildMgr
from Py4GWCoreLib import Map
from Py4GWCoreLib import Player
from Py4GWCoreLib import Profession
from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib import SpiritModelID
from Py4GWCoreLib import Utils
from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build
from Py4GWCoreLib.Builds.Skills import SkillsTemplate
from Py4GWCoreLib.Skill import Skill

Soul_Twisting_ID = Skill.GetID("Soul_Twisting")
Boon_of_Creation_ID = Skill.GetID("Boon_of_Creation")
Shelter_ID = Skill.GetID("Shelter")
Union_ID = Skill.GetID("Union")
Displacement_ID = Skill.GetID("Displacement")
Summon_Spirits_kurzick_ID = Skill.GetID("Summon_Spirits_kurzick")
Summon_Spirits_luxon_ID = Skill.GetID("Summon_Spirits_luxon")
Armor_of_Unfeeling_ID = Skill.GetID("Armor_of_Unfeeling")
Spirits_Gift_ID = Skill.GetID("Spirits_Gift")
Breath_of_the_Great_Dwarf_ID = Skill.GetID("Breath_of_the_Great_Dwarf")
Ebon_Vanguard_Assassin_Support_ID = Skill.GetID("Ebon_Vanguard_Assassin_Support")
Ebon_Battle_Standard_of_Wisdom_ID = Skill.GetID("Ebon_Battle_Standard_of_Wisdom")
I_Am_Unstoppable_ID = Skill.GetID("I_Am_Unstoppable")
Air_of_Superiority_ID = Skill.GetID("Air_of_Superiority")
Remove_Hex_ID = Skill.GetID("Remove_Hex")
Edge_of_Extinction_ID = Skill.GetID("Edge_of_Extinction")

REQUIRED_SKILLS = [Soul_Twisting_ID, Shelter_ID, Union_ID]
OPTIONAL_SKILLS = [
    Boon_of_Creation_ID,
    Displacement_ID,
    Summon_Spirits_kurzick_ID,
    Summon_Spirits_luxon_ID,
    Armor_of_Unfeeling_ID,
    Spirits_Gift_ID,
    Breath_of_the_Great_Dwarf_ID,
    Ebon_Vanguard_Assassin_Support_ID,
    Ebon_Battle_Standard_of_Wisdom_ID,
    I_Am_Unstoppable_ID,
    Air_of_Superiority_ID,
    Remove_Hex_ID,
    Edge_of_Extinction_ID,
]
SUPPORTED_SKILLS = REQUIRED_SKILLS + OPTIONAL_SKILLS
_REQUIRED_SKILL_SET = frozenset(REQUIRED_SKILLS)
_SUPPORTED_SKILL_SET = frozenset(SUPPORTED_SKILLS)
_MATCH_SCORE_BONUS = 1000

# Ordinary protective Binding Rituals use an approximately 2512-unit passive
# radius.  Range.Spirit is the rounded 2500-unit library value, but it is not
# used as the placement gate here.  Keep the live-tunable semantic explicit.
SPIRIT_PROTECTION_RADIUS = 2512.0
SPIRIT_COVERAGE_SAFETY_MARGIN = 0.0

SOUL_TWISTING_READY_MS = 5000
BOON_REFRESH_MS = 4000
SPIRITS_GIFT_REFRESH_MS = 500
PORTABLE_MIN_ENERGY_FRACTION = 0.50
SOUL_TWISTING_PYTHON_COST = 10
SOUL_TWISTING_LIVE_MIN_COST = 5
# A moving party can briefly leave an otherwise healthy core spirit behind.
# Keep this debounce local and easy to tune from live-test observations.
CORE_REBUILD_MOVEMENT_DEBOUNCE_MS = 900
ARMOR_DEPLOYMENT_LOOKBACK_MS = 3000
ARMOR_REQUEST_TO_ACTIVATION_MS = 500
ARMOR_ACTIVATION_TO_FINISH_MS = 1500
ARMOR_REQUEST_TO_FINISH_MS = 1750
ARMOR_FINISH_TO_CANDIDATE_MS = 2000
ARMOR_CANDIDATE_SETTLE_MS = 1000
ARMOR_DEPLOYMENT_PROBE_MAX_MS = (
    ARMOR_REQUEST_TO_FINISH_MS
    + ARMOR_FINISH_TO_CANDIDATE_MS
    + ARMOR_CANDIDATE_SETTLE_MS
)
ARMOR_DEPLOYMENT_EPOCH_MS = 15000
ARMOR_ASSOCIATION_RADIUS = 128.0
_DEPLOYMENT_EVENT_TYPE_NAMES = (
    "SKILL_ACTIVATE_PACKET",
    "SKILL_ACTIVATED",
    "SKILL_STOPPED",
    "SKILL_FINISHED",
    "INTERRUPTED",
)
_DEPLOYMENT_ACTIVATION_TYPES = frozenset(
    {"SKILL_ACTIVATE_PACKET", "SKILL_ACTIVATED"}
)
_DEPLOYMENT_TERMINAL_TYPES = frozenset(
    {"SKILL_STOPPED", "SKILL_FINISHED", "INTERRUPTED"}
)
_DEPLOYMENT_MAX_RECORDED_EVENTS = 16

_CORE_SKILLS = (Shelter_ID, Union_ID, Displacement_ID)
_CORE_SKILL_NAMES = {
    Shelter_ID: "Shelter",
    Union_ID: "Union",
    Displacement_ID: "Displacement",
}
_CORE_MODEL_BY_SKILL = {
    Shelter_ID: int(SpiritModelID.SHELTER),
    Union_ID: int(SpiritModelID.UNION),
    Displacement_ID: int(SpiritModelID.DISPLACEMENT),
}
_CORE_SKILL_BY_MODEL = {
    model_id: skill_id for skill_id, model_id in _CORE_MODEL_BY_SKILL.items()
}


class _EncounterContext(str, Enum):
    TRAVEL_READY = "TRAVEL_READY"
    PREPARATION = "PREPARATION"
    ACTIVE_COMBAT = "ACTIVE_COMBAT"


class _SpiritCategory(str, Enum):
    PARTY_ROOT_MATCH = "party-root-match"
    HOSTILE = "hostile"
    UNKNOWN = "unknown"


class _ActionKind(str, Enum):
    PORTABLE_READINESS = "portable-readiness"
    SOUL_TWISTING_READINESS = "soul-twisting-readiness"
    CORE_DEPLOYMENT = "core-deployment"
    POST_DEPLOYMENT = "post-deployment"
    BLOCKED_NO_ACTION = "blocked/no-action"


Position = tuple[float, float]


@dataclass(frozen=True, slots=True)
class _EffectObservation:
    equipped: bool = False
    present: bool = False
    remaining_ms: int = 0

    @property
    def ready(self) -> bool:
        return self.equipped and self.present and self.remaining_ms > 0


@dataclass(frozen=True, slots=True)
class _SpiritObservation:
    skill_id: int
    model_id: int
    agent_id: int
    owner_id: int
    root_category: _SpiritCategory
    allegiance: int
    alive: bool
    spawned: bool
    hp_fraction: float
    position: Position | None
    distance_from_player: float | None
    distance_from_leader: float | None
    covers_leader: bool


@dataclass(frozen=True, slots=True)
class _CoreStatus:
    observations: tuple[_SpiritObservation, ...] = ()
    functional_exists: bool = False
    functional_covers: bool = False
    functional_out_of_coverage: bool = False


@dataclass(frozen=True, slots=True)
class _SoulTwistingSnapshot:
    tick_ms: int = 0
    map_id: int = 0
    instance_uptime_ms: int = 0
    context: _EncounterContext = _EncounterContext.TRAVEL_READY
    local_in_aggro: bool = False
    leader_in_aggro: bool = False
    party_in_aggro: bool = False
    in_aggro: bool = False
    effective_in_aggro: bool = False
    close_to_aggro: bool = False
    player_agent_id: int = 0
    player_alive: bool = True
    local_native_root_id: int = 0
    party_root_ids: frozenset[int] = frozenset()
    player_position: Position | None = None
    player_moving: bool = False
    player_energy_fraction: float = 0.0
    current_energy: float = 0.0
    maximum_energy: float = 0.0
    leader_agent_id: int = 0
    leader_valid: bool = False
    leader_alive: bool = False
    leader_position: Position | None = None
    leader_moving: bool = False
    distance_to_leader: float | None = None
    normal_cast_state: bool = True
    map_explorable: bool = True
    map_loading: bool = False
    deployment_ready: bool = False
    soul_twisting: _EffectObservation = _EffectObservation()
    boon_of_creation: _EffectObservation = _EffectObservation()
    spirits_gift: _EffectObservation = _EffectObservation()
    core_spirits_readable: bool = True
    core_spirits: dict[int, tuple[_SpiritObservation, ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class _SoulTwistingAction:
    kind: _ActionKind
    skill_id: int = 0
    reason: str = ""
    target_agent_id: int = 0


@dataclass(slots=True)
class _DeploymentEventRecord:
    event_type: str
    timestamp_ms: int
    caster_agent_id: int
    skill_id: int
    target_agent_id: int
    float_value: float
    controlled: bool
    association: str


@dataclass(slots=True)
class _DeploymentCandidate:
    agent_id: int
    first_seen_at_ms: int
    first_spawned_at_ms: int | None
    first_alive: bool
    first_position: Position | None
    first_distance_from_origin: float | None
    last_seen_at_ms: int
    last_spawned: bool
    last_alive: bool
    spawned_evidence_checked: bool = False
    qualified_at_ms: int | None = None
    qualification_fingerprint: tuple[int, int, str] | None = None


@dataclass(slots=True)
class _ArmorDeploymentProbe:
    skill_id: int
    model_id: int
    requested_at_ms: int
    map_id: int
    instance_uptime_ms: int
    player_agent_id: int
    cast_origin: Position
    pre_agent_ids: frozenset[int]
    baseline_event_keys: frozenset[tuple[int, int, int, int, int, float]] = (
        frozenset()
    )
    seen_event_keys: set[tuple[int, int, int, int, int, float]] = field(
        default_factory=set
    )
    event_records: list[_DeploymentEventRecord] = field(default_factory=list)
    foreign_event_casters: set[int] = field(default_factory=set)
    activate_packet_at_ms: int | None = None
    activation_at_ms: int | None = None
    terminal_at_ms: int | None = None
    terminal_event_type: str | None = None
    finish_at_ms: int | None = None
    wrapper_result: bool | None = None
    candidates: dict[int, _DeploymentCandidate] = field(default_factory=dict)
    qualifying_candidate_id: int | None = None
    qualifying_at_ms: int | None = None
    settle_until_ms: int | None = None
    invalid_reason: str | None = None
    token_issued: bool = False
    current_observations: tuple[_SpiritObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class _ArmorDeploymentToken:
    skill_id: int
    model_id: int
    witness_agent_id: int
    map_id: int
    instance_uptime_ms: int
    player_agent_id: int
    request_at_ms: int
    finish_at_ms: int
    witness_fingerprint: tuple[int, int, str]


@dataclass(slots=True)
class _ArmorDeploymentEpoch:
    epoch_id: int
    map_id: int
    instance_uptime_ms: int
    player_agent_id: int
    started_at_ms: int
    expires_at_ms: int
    tokens: dict[int, _ArmorDeploymentToken] = field(default_factory=dict)


def _classify_context(
    *,
    local_in_aggro: bool,
    leader_in_aggro: bool,
    party_in_aggro: bool,
    effective_in_aggro: bool,
    close_to_aggro: bool,
) -> _EncounterContext:
    if local_in_aggro or leader_in_aggro or party_in_aggro or effective_in_aggro:
        return _EncounterContext.ACTIVE_COMBAT
    if close_to_aggro:
        return _EncounterContext.PREPARATION
    return _EncounterContext.TRAVEL_READY


def _classify_spirit(
    *,
    owner_id: int,
    allegiance: int,
    party_root_ids: set[int] | frozenset[int],
) -> _SpiritCategory:
    if int(allegiance) == int(Allegiance.Enemy):
        return _SpiritCategory.HOSTILE
    if int(owner_id) != 0 and int(owner_id) in party_root_ids:
        return _SpiritCategory.PARTY_ROOT_MATCH
    return _SpiritCategory.UNKNOWN


def _leader_is_covered(
    *,
    distance_to_leader: float | None,
    leader_valid: bool,
    leader_alive: bool,
) -> bool:
    if not leader_valid or not leader_alive or distance_to_leader is None:
        return False
    return (
        distance_to_leader <= SPIRIT_PROTECTION_RADIUS - SPIRIT_COVERAGE_SAFETY_MARGIN
    )


def _core_status(snapshot: _SoulTwistingSnapshot, skill_id: int) -> _CoreStatus:
    observations = snapshot.core_spirits.get(skill_id, ())
    functional = tuple(
        observation
        for observation in observations
        if observation.root_category is _SpiritCategory.PARTY_ROOT_MATCH
        and observation.alive
        and observation.spawned
    )
    return _CoreStatus(
        observations=observations,
        functional_exists=bool(functional),
        functional_covers=any(observation.covers_leader for observation in functional),
        functional_out_of_coverage=any(
            not observation.covers_leader for observation in functional
        ),
    )


class My_Soul_Twisting(BuildMgr):
    """Small, snapshot-driven Ritualist controller for the custom ST bar."""

    def __init__(self, match_only: bool = False):
        super().__init__(
            name="My Soul Twisting",
            required_primary=Profession.Ritualist,
            template_code="OAOj4MgMJPYTr3jDAAAAAAAAAA",
            required_skills=list(REQUIRED_SKILLS),
            optional_skills=list(OPTIONAL_SKILLS),
        )
        if match_only:
            return

        self.SetFallback("HeroAI", HeroAI_Build(standalone_fallback=True))
        self.SetBlockedSkills(list(SUPPORTED_SKILLS))
        self.SetOOCFn(self._run_ooc)
        self.SetCombatFn(self._run_combat)
        self.skills: SkillsTemplate = SkillsTemplate(self)

        self._diagnostic_last_signatures: dict[str, tuple[Any, ...]] = {}
        self._armor_deployment_probes: dict[int, _ArmorDeploymentProbe] = {}
        self._armor_deployment_active_cast: _ArmorDeploymentProbe | None = None
        self._armor_deployment_last_terminal_cast: _ArmorDeploymentProbe | None = None
        self._armor_deployment_epoch: _ArmorDeploymentEpoch | None = None
        self._armor_deployment_epoch_counter = 0
        self._armor_deployment_lifecycle: tuple[int, int] | None = None
        self._armor_deployment_player_agent_id = 0
        self._core_rebuild_debounce_skill_id: int | None = None
        self._core_rebuild_debounce_started_ms: int | None = None
        self._core_rebuild_debounce_expired = False
        self._core_rebuild_debounce_presence: tuple[tuple[int, int], ...] | None = None
        self._core_rebuild_debounce_scope: tuple[
            int, int, tuple[int, ...], int
        ] | None = None
        self._core_rebuild_debounce_instance_uptime_ms: int | None = None

    def ScoreMatch(
        self,
        current_primary=None,
        current_secondary=None,
        current_skills: list[int] | None = None,
    ) -> int:
        if current_skills is None:
            current_skills = self._get_current_skills()

        equipped_skills = [int(skill_id) for skill_id in current_skills if skill_id]
        equipped_skill_set = set(equipped_skills)
        if len(equipped_skills) != 8 or len(equipped_skill_set) != 8:
            return -1
        if not _SUPPORTED_SKILL_SET.issuperset(equipped_skill_set):
            return -1
        if not _REQUIRED_SKILL_SET.issubset(equipped_skill_set):
            return -1

        base_score = super().ScoreMatch(
            current_primary=current_primary,
            current_secondary=current_secondary,
            current_skills=equipped_skills,
        )
        if base_score < 0:
            return -1
        return _MATCH_SCORE_BONUS + base_score

    @staticmethod
    def _now_ms() -> int:
        try:
            return int(PySystem.get_tick_count64())
        except Exception:
            try:
                return int(Utils.GetBaseTimestamp())
            except Exception:
                return 0

    @staticmethod
    def _safe_position(agent_id: int) -> Position | None:
        try:
            position = Agent.GetXY(agent_id)
            if position is None or len(position) < 2:
                return None
            return float(position[0]), float(position[1])
        except Exception:
            return None

    @staticmethod
    def _safe_distance(first: Position | None, second: Position | None) -> float | None:
        if first is None or second is None:
            return None
        try:
            return float(Utils.Distance(first, second))
        except Exception:
            return None

    @staticmethod
    def _read_local_agent_id() -> int:
        try:
            return int(Player.GetAgentID() or 0)
        except Exception:
            return 0

    def _read_encounter(self) -> tuple[bool, bool, bool, bool, bool]:
        data = getattr(getattr(self, "_cached_data", None), "data", None)
        local_value = getattr(data, "local_in_aggro", None)
        leader_value = getattr(data, "leader_in_aggro", None)
        party_value = getattr(data, "party_in_aggro", None)
        effective_value = getattr(data, "in_aggro", None)

        if local_value is None:
            try:
                local_value = Routines.Checks.Agents.InAggro(self.GetActiveScanRange())
            except Exception:
                local_value = False
        if effective_value is None:
            try:
                effective_value = self.IsInAggro()
            except Exception:
                effective_value = bool(local_value or leader_value or party_value)

        try:
            close_to_aggro = bool(self.IsCloseToAggro())
        except Exception:
            close_to_aggro = False

        return (
            bool(local_value),
            bool(leader_value),
            bool(party_value),
            bool(effective_value),
            close_to_aggro,
        )

    def _read_effect(self, skill_id: int) -> _EffectObservation:
        try:
            equipped = bool(self.IsSkillEquipped(skill_id))
        except Exception:
            equipped = False
        if not equipped:
            return _EffectObservation()

        player_agent_id = self._read_local_agent_id()
        try:
            present = bool(Routines.Checks.Agents.HasEffect(player_agent_id, skill_id))
        except Exception:
            present = False
        if not present:
            return _EffectObservation(equipped=True)

        try:
            remaining_ms = max(
                0,
                int(
                    GLOBAL_CACHE.Effects.GetEffectTimeRemaining(
                        player_agent_id, skill_id
                    )
                    or 0
                ),
            )
        except Exception:
            remaining_ms = 0
        return _EffectObservation(
            equipped=True, present=True, remaining_ms=remaining_ms
        )

    def _read_energy(self, player_agent_id: int) -> tuple[float, float, float]:
        try:
            fraction = min(1.0, max(0.0, float(Agent.GetEnergy(player_agent_id))))
        except Exception:
            fraction = 0.0
        try:
            maximum = max(0.0, float(Agent.GetMaxEnergy(player_agent_id)))
        except Exception:
            maximum = 0.0
        return fraction, fraction * maximum, maximum

    @staticmethod
    def _normal_cast_state() -> bool:
        try:
            return bool(Routines.Checks.Skills.CanCast())
        except Exception:
            return False

    @staticmethod
    def _read_instance_lifecycle() -> tuple[int, int]:
        try:
            map_id = int(Map.GetMapID() or 0)
        except Exception:
            map_id = 0
        try:
            instance_uptime_ms = max(0, int(Map.GetInstanceUptime() or 0))
        except Exception:
            instance_uptime_ms = 0
        return map_id, instance_uptime_ms

    @staticmethod
    def _read_agent_owner_id(agent_id: int) -> int:
        try:
            return int(Agent.GetOwnerID(agent_id) or 0)
        except Exception:
            return 0

    def _read_party_member_agent_ids(self, local_agent_id: int) -> set[int]:
        member_agent_ids: set[int] = set()
        if local_agent_id > 0:
            member_agent_ids.add(local_agent_id)

        try:
            party = GLOBAL_CACHE.Party
        except Exception:
            return member_agent_ids

        try:
            players = list(party.GetPlayers() or [])
            party_players = party.Players
            for player in players:
                login_number = int(getattr(player, "login_number", 0) or 0)
                if login_number <= 0:
                    continue
                agent_id = int(party_players.GetAgentIDByLoginNumber(login_number) or 0)
                if agent_id > 0:
                    member_agent_ids.add(agent_id)
        except Exception:
            pass

        for getter_name in ("GetHeroes", "GetHenchmen"):
            try:
                members = list(getattr(party, getter_name)() or [])
            except Exception:
                continue
            for member in members:
                try:
                    agent_id = int(getattr(member, "agent_id", 0) or 0)
                except Exception:
                    agent_id = 0
                if agent_id > 0:
                    member_agent_ids.add(agent_id)

        return member_agent_ids

    def _read_party_root_ids(
        self, local_agent_id: int, local_native_root_id: int
    ) -> frozenset[int]:
        root_ids: set[int] = set()
        if local_native_root_id > 0:
            root_ids.add(local_native_root_id)
        for member_agent_id in self._read_party_member_agent_ids(local_agent_id):
            member_root_id = self._read_agent_owner_id(member_agent_id)
            if member_root_id > 0:
                root_ids.add(member_root_id)
        return frozenset(root_ids)

    def _scan_core_spirits(
        self,
        *,
        party_root_ids: frozenset[int],
        player_position: Position | None,
        leader_valid: bool,
        leader_alive: bool,
        leader_position: Position | None,
    ) -> tuple[dict[int, tuple[_SpiritObservation, ...]], bool]:
        observations: dict[int, list[_SpiritObservation]] = {
            skill_id: [] for skill_id in _CORE_SKILLS
        }
        scan_readable = True
        try:
            spirit_array = list(AgentArray.GetSpiritPetArray() or [])
        except Exception:
            spirit_array = []
            scan_readable = False

        for spirit_id_value in spirit_array:
            try:
                spirit_id = int(spirit_id_value)
                model_id = int(Agent.GetPlayerNumber(spirit_id))
                skill_id = _CORE_SKILL_BY_MODEL.get(model_id)
                if skill_id is None:
                    continue

                owner_id = int(Agent.GetOwnerID(spirit_id) or 0)
                allegiance_value = Agent.GetAllegiance(spirit_id)
                if isinstance(allegiance_value, tuple):
                    allegiance = int(allegiance_value[0])
                else:
                    allegiance = int(allegiance_value)
                root_category = _classify_spirit(
                    owner_id=owner_id,
                    allegiance=allegiance,
                    party_root_ids=party_root_ids,
                )
                alive = bool(Agent.IsAlive(spirit_id))
                spawned = bool(Agent.IsSpawned(spirit_id))
                hp_fraction = min(1.0, max(0.0, float(Agent.GetHealth(spirit_id))))
                position = self._safe_position(spirit_id)
                distance_from_player = self._safe_distance(player_position, position)
                distance_from_leader = self._safe_distance(leader_position, position)
                covers_leader = (
                    root_category is _SpiritCategory.PARTY_ROOT_MATCH
                    and alive
                    and spawned
                    and _leader_is_covered(
                        distance_to_leader=distance_from_leader,
                        leader_valid=leader_valid,
                        leader_alive=leader_alive,
                    )
                )
                observations[skill_id].append(
                    _SpiritObservation(
                        skill_id=skill_id,
                        model_id=model_id,
                        agent_id=spirit_id,
                        owner_id=owner_id,
                        root_category=root_category,
                        allegiance=allegiance,
                        alive=alive,
                        spawned=spawned,
                        hp_fraction=hp_fraction,
                        position=position,
                        distance_from_player=distance_from_player,
                        distance_from_leader=distance_from_leader,
                        covers_leader=covers_leader,
                    )
                )
            except Exception:
                scan_readable = False
                continue

        return (
            {skill_id: tuple(values) for skill_id, values in observations.items()},
            scan_readable,
        )

    def _build_snapshot(self) -> _SoulTwistingSnapshot:
        tick_ms = self._now_ms()
        map_id, instance_uptime_ms = self._read_instance_lifecycle()
        player_agent_id = self._read_local_agent_id()
        try:
            player_alive = bool(
                player_agent_id > 0 and Agent.IsAlive(player_agent_id)
            )
        except Exception:
            player_alive = False
        local_native_root_id = self._read_agent_owner_id(player_agent_id)
        party_root_ids = self._read_party_root_ids(
            player_agent_id, local_native_root_id
        )
        try:
            player_position = self._safe_position(player_agent_id)
            if player_position is None:
                raw_player_position = Player.GetXY()
                if raw_player_position is not None and len(raw_player_position) >= 2:
                    player_position = (
                        float(raw_player_position[0]),
                        float(raw_player_position[1]),
                    )
        except Exception:
            player_position = None
        try:
            player_moving = bool(Agent.IsMoving(player_agent_id))
        except Exception:
            player_moving = False

        try:
            leader_agent_id = int(GLOBAL_CACHE.Party.GetPartyLeaderID() or 0)
        except Exception:
            leader_agent_id = 0
        try:
            leader_valid = bool(leader_agent_id and Agent.IsValid(leader_agent_id))
        except Exception:
            leader_valid = False
        try:
            leader_alive = bool(leader_valid and Agent.IsAlive(leader_agent_id))
        except Exception:
            leader_alive = False
        leader_position = self._safe_position(leader_agent_id) if leader_valid else None
        if leader_position is None and leader_agent_id == player_agent_id:
            leader_position = player_position
        try:
            leader_moving = bool(leader_valid and Agent.IsMoving(leader_agent_id))
        except Exception:
            leader_moving = False
        distance_to_leader = self._safe_distance(player_position, leader_position)

        (
            local_in_aggro,
            leader_in_aggro,
            party_in_aggro,
            effective_in_aggro,
            close_to_aggro,
        ) = self._read_encounter()
        context = _classify_context(
            local_in_aggro=local_in_aggro,
            leader_in_aggro=leader_in_aggro,
            party_in_aggro=party_in_aggro,
            effective_in_aggro=effective_in_aggro,
            close_to_aggro=close_to_aggro,
        )
        player_energy_fraction, current_energy, maximum_energy = self._read_energy(
            player_agent_id
        )
        normal_cast_state = self._normal_cast_state()
        try:
            map_explorable = bool(Map.IsExplorable())
        except Exception:
            map_explorable = map_id > 0
        try:
            map_loading = bool(Map.IsMapLoading())
        except Exception:
            map_loading = False
        core_spirits, core_spirits_readable = self._scan_core_spirits(
            party_root_ids=party_root_ids,
            player_position=player_position,
            leader_valid=leader_valid,
            leader_alive=leader_alive,
            leader_position=leader_position,
        )

        return _SoulTwistingSnapshot(
            tick_ms=tick_ms,
            map_id=map_id,
            instance_uptime_ms=instance_uptime_ms,
            context=context,
            local_in_aggro=local_in_aggro,
            leader_in_aggro=leader_in_aggro,
            party_in_aggro=party_in_aggro,
            in_aggro=effective_in_aggro,
            effective_in_aggro=effective_in_aggro,
            close_to_aggro=close_to_aggro,
            player_agent_id=player_agent_id,
            player_alive=player_alive,
            local_native_root_id=local_native_root_id,
            party_root_ids=party_root_ids,
            player_position=player_position,
            player_moving=player_moving,
            player_energy_fraction=player_energy_fraction,
            current_energy=current_energy,
            maximum_energy=maximum_energy,
            leader_agent_id=leader_agent_id,
            leader_valid=leader_valid,
            leader_alive=leader_alive,
            leader_position=leader_position,
            leader_moving=leader_moving,
            distance_to_leader=distance_to_leader,
            normal_cast_state=normal_cast_state,
            map_explorable=map_explorable,
            map_loading=map_loading,
            deployment_ready=(
                context is not _EncounterContext.TRAVEL_READY
                and normal_cast_state
                and _leader_is_covered(
                    distance_to_leader=distance_to_leader,
                    leader_valid=leader_valid,
                    leader_alive=leader_alive,
                )
            ),
            soul_twisting=self._read_effect(Soul_Twisting_ID),
            boon_of_creation=self._read_effect(Boon_of_Creation_ID),
            spirits_gift=self._read_effect(Spirits_Gift_ID),
            core_spirits_readable=core_spirits_readable,
            core_spirits=core_spirits,
        )

    def _is_skill_equipped(self, skill_id: int) -> bool:
        try:
            return bool(self.IsSkillEquipped(skill_id))
        except Exception:
            return False

    @staticmethod
    def _effect_is_ready(effect: _EffectObservation, refresh_ms: int) -> bool:
        return effect.equipped and effect.present and effect.remaining_ms > refresh_ms

    @staticmethod
    def _energy_is_healthy(snapshot: _SoulTwistingSnapshot) -> bool:
        return snapshot.player_energy_fraction >= PORTABLE_MIN_ENERGY_FRACTION

    def _equipped_core_skills(self) -> tuple[int, ...]:
        return tuple(
            skill_id for skill_id in _CORE_SKILLS if self._is_skill_equipped(skill_id)
        )

    def _all_core_useful(self, snapshot: _SoulTwistingSnapshot) -> bool:
        equipped_core = self._equipped_core_skills()
        return bool(equipped_core) and all(
            _core_status(snapshot, skill_id).functional_covers
            for skill_id in equipped_core
        )

    def _select_portable_action(
        self,
        snapshot: _SoulTwistingSnapshot,
        *,
        allow_active: bool = False,
    ) -> _SoulTwistingAction | None:
        if snapshot.context is _EncounterContext.ACTIVE_COMBAT and not allow_active:
            return None
        if (
            snapshot.soul_twisting.equipped
            and not self._effect_is_ready(
                snapshot.soul_twisting, SOUL_TWISTING_READY_MS
            )
            and self._energy_is_healthy(snapshot)
        ):
            return _SoulTwistingAction(
                kind=_ActionKind.SOUL_TWISTING_READINESS,
                skill_id=Soul_Twisting_ID,
                reason="soul_twisting_missing_or_within_deployment_refresh",
            )
        if (
            snapshot.boon_of_creation.equipped
            and not self._effect_is_ready(snapshot.boon_of_creation, BOON_REFRESH_MS)
            and self._energy_is_healthy(snapshot)
        ):
            return _SoulTwistingAction(
                kind=_ActionKind.PORTABLE_READINESS,
                skill_id=Boon_of_Creation_ID,
                reason="boon_missing_or_within_refresh",
            )
        if (
            snapshot.spirits_gift.equipped
            and not self._effect_is_ready(
                snapshot.spirits_gift, SPIRITS_GIFT_REFRESH_MS
            )
            and self._energy_is_healthy(snapshot)
        ):
            return _SoulTwistingAction(
                kind=_ActionKind.PORTABLE_READINESS,
                skill_id=Spirits_Gift_ID,
                reason="spirits_gift_missing_or_within_refresh",
            )
        return None

    def _armor_is_castable(self) -> bool:
        if not self._is_skill_equipped(Armor_of_Unfeeling_ID):
            return False
        try:
            return bool(self.CanCastSkillID(Armor_of_Unfeeling_ID))
        except Exception:
            return True

    def _armor_qualifying_core_types(
        self, snapshot: _SoulTwistingSnapshot
    ) -> tuple[int, ...]:
        if not snapshot.core_spirits_readable:
            return ()
        epoch = self._armor_deployment_epoch
        if epoch is None:
            return ()
        qualifying: list[int] = []
        for skill_id, token in epoch.tokens.items():
            if self._armor_token_witness(token, snapshot) is not None:
                qualifying.append(skill_id)
        return tuple(sorted(qualifying, key=_CORE_SKILLS.index))

    def _armor_eligibility(
        self, snapshot: _SoulTwistingSnapshot
    ) -> tuple[bool, tuple[int, ...], str]:
        if not self._armor_is_castable():
            return False, (), "armor_not_castable"
        if not snapshot.deployment_ready:
            return False, (), "deployment_window_closed"
        if not snapshot.core_spirits_readable:
            return False, (), "core_scan_unreadable"
        if snapshot.player_agent_id <= 0 or snapshot.player_position is None:
            return False, (), "player_identity_or_position_unreadable"
        if self._armor_deployment_probes:
            return False, (), "deployment_probe_pending"
        epoch = self._armor_deployment_epoch
        if epoch is None:
            return False, (), "no_active_deployment_epoch"
        if snapshot.tick_ms >= epoch.expires_at_ms:
            self._reset_armor_deployment_state(reason="deployment_epoch_expired")
            return False, (), "deployment_epoch_expired"
        if (
            snapshot.map_id != epoch.map_id
            or snapshot.instance_uptime_ms < epoch.instance_uptime_ms
            or snapshot.player_agent_id != epoch.player_agent_id
        ):
            self._reset_armor_deployment_state(reason="lifecycle_or_player_changed")
            return False, (), "lifecycle_or_player_changed"
        if not self._all_core_useful(snapshot):
            return False, (), "core_package_no_longer_useful"

        qualifying_types = self._armor_qualifying_core_types(snapshot)
        if len(qualifying_types) < 2:
            return False, qualifying_types, "fewer_than_two_valid_deployment_tokens"
        for skill_id in qualifying_types:
            token = epoch.tokens[skill_id]
            observation = self._armor_token_witness(token, snapshot)
            if observation is None:
                self._invalidate_armor_token(
                    skill_id, reason="witness_invalid_before_dispatch"
                )
                return False, (), "deployment_witness_invalid"
            if (
                observation.distance_from_player is None
                or observation.distance_from_player > Range.Earshot.value
            ):
                return False, qualifying_types, "deployment_witness_out_of_earshot"
        return True, qualifying_types, "ready"

    def _clear_core_rebuild_debounce(
        self, *, reason: str, tick_ms: int | None = None
    ) -> None:
        skill_id = self._core_rebuild_debounce_skill_id
        started_ms = self._core_rebuild_debounce_started_ms
        presence = self._core_rebuild_debounce_presence
        if skill_id is None:
            self._core_rebuild_debounce_started_ms = None
            self._core_rebuild_debounce_expired = False
            self._core_rebuild_debounce_presence = None
            self._core_rebuild_debounce_scope = None
            self._core_rebuild_debounce_instance_uptime_ms = None
            return

        current_tick_ms = self._now_ms() if tick_ms is None else tick_ms
        elapsed_ms = (
            None
            if started_ms is None
            else max(0, int(current_tick_ms) - int(started_ms))
        )
        self._emit_event(
            "core-rebuild-debounce",
            signature=("reset", skill_id, started_ms, reason),
            state="reset",
            skill=_CORE_SKILL_NAMES.get(skill_id, str(skill_id)),
            reason=reason,
            started_at=started_ms,
            elapsed_ms=elapsed_ms,
            spirit_ids=()
            if presence is None
            else tuple(agent_id for agent_id, _owner_id in presence),
        )
        self._core_rebuild_debounce_skill_id = None
        self._core_rebuild_debounce_started_ms = None
        self._core_rebuild_debounce_expired = False
        self._core_rebuild_debounce_presence = None
        self._core_rebuild_debounce_scope = None
        self._core_rebuild_debounce_instance_uptime_ms = None

    def _start_core_rebuild_debounce(
        self,
        snapshot: _SoulTwistingSnapshot,
        skill_id: int,
        presence: tuple[tuple[int, int], ...],
    ) -> None:
        scope = (
            snapshot.player_agent_id,
            snapshot.leader_agent_id,
            tuple(sorted(snapshot.party_root_ids)),
            snapshot.map_id,
        )
        self._core_rebuild_debounce_skill_id = skill_id
        self._core_rebuild_debounce_started_ms = snapshot.tick_ms
        self._core_rebuild_debounce_expired = False
        self._core_rebuild_debounce_presence = presence
        self._core_rebuild_debounce_scope = scope
        self._core_rebuild_debounce_instance_uptime_ms = snapshot.instance_uptime_ms
        self._emit_event(
            "core-rebuild-debounce",
            signature=("start", skill_id, snapshot.tick_ms),
            state="started",
            skill=_CORE_SKILL_NAMES.get(skill_id, str(skill_id)),
            started_at=snapshot.tick_ms,
            grace_ms=CORE_REBUILD_MOVEMENT_DEBOUNCE_MS,
            player_moving=int(snapshot.player_moving),
            leader_moving=int(snapshot.leader_moving),
            spirit_ids=tuple(agent_id for agent_id, _owner_id in presence),
        )

    @staticmethod
    def _core_rebuild_presence(
        status: _CoreStatus,
    ) -> tuple[tuple[int, int], ...]:
        return tuple(
            sorted(
                (
                    observation.agent_id,
                    observation.owner_id,
                )
                for observation in status.observations
                if (
                    observation.root_category is _SpiritCategory.PARTY_ROOT_MATCH
                    and observation.alive
                    and observation.spawned
                    and not observation.covers_leader
                )
            )
        )

    def _should_defer_core_rebuild(
        self,
        snapshot: _SoulTwistingSnapshot,
        skill_id: int,
        status: _CoreStatus,
    ) -> bool:
        current_skill_id = self._core_rebuild_debounce_skill_id
        if snapshot.map_id <= 0 or snapshot.instance_uptime_ms <= 0:
            self._clear_core_rebuild_debounce(
                reason="lifecycle_changed", tick_ms=snapshot.tick_ms
            )
            return False

        if current_skill_id is not None and current_skill_id != skill_id:
            self._clear_core_rebuild_debounce(
                reason="need_changed", tick_ms=snapshot.tick_ms
            )

        if not status.functional_exists:
            if current_skill_id == skill_id:
                self._clear_core_rebuild_debounce(
                    reason="nonfunctional", tick_ms=snapshot.tick_ms
                )
            return False
        if not status.functional_out_of_coverage:
            if current_skill_id == skill_id:
                self._clear_core_rebuild_debounce(
                    reason="coverage_recovered", tick_ms=snapshot.tick_ms
                )
            return False

        scope = (
            snapshot.player_agent_id,
            snapshot.leader_agent_id,
            tuple(sorted(snapshot.party_root_ids)),
            snapshot.map_id,
        )
        if (
            current_skill_id == skill_id
            and self._core_rebuild_debounce_scope != scope
        ):
            self._clear_core_rebuild_debounce(
                reason="runtime_invalidated", tick_ms=snapshot.tick_ms
            )
            current_skill_id = None

        started_instance_uptime_ms = self._core_rebuild_debounce_instance_uptime_ms
        if (
            current_skill_id == skill_id
            and started_instance_uptime_ms is not None
            and snapshot.instance_uptime_ms < started_instance_uptime_ms
        ):
            self._clear_core_rebuild_debounce(
                reason="lifecycle_changed", tick_ms=snapshot.tick_ms
            )
            current_skill_id = None

        presence = self._core_rebuild_presence(status)
        if (
            current_skill_id == skill_id
            and self._core_rebuild_debounce_presence != presence
        ):
            self._clear_core_rebuild_debounce(
                reason="package_changed", tick_ms=snapshot.tick_ms
            )
            current_skill_id = None

        moving = snapshot.player_moving or snapshot.leader_moving
        if not moving:
            if current_skill_id == skill_id:
                self._clear_core_rebuild_debounce(
                    reason="movement_stabilized", tick_ms=snapshot.tick_ms
                )
            return False

        if self._core_rebuild_debounce_skill_id != skill_id:
            self._start_core_rebuild_debounce(snapshot, skill_id, presence)
        else:
            started_ms = self._core_rebuild_debounce_started_ms
            if started_ms is None or snapshot.tick_ms < started_ms:
                self._clear_core_rebuild_debounce(
                    reason="runtime_invalidated", tick_ms=snapshot.tick_ms
                )
                self._start_core_rebuild_debounce(snapshot, skill_id, presence)

        if self._core_rebuild_debounce_expired:
            return False

        started_ms = self._core_rebuild_debounce_started_ms
        if started_ms is None:
            return False
        elapsed_ms = snapshot.tick_ms - started_ms
        if elapsed_ms >= CORE_REBUILD_MOVEMENT_DEBOUNCE_MS:
            self._core_rebuild_debounce_expired = True
            self._emit_event(
                "core-rebuild-debounce",
                signature=("expired", skill_id, started_ms),
                state="ended",
                skill=_CORE_SKILL_NAMES.get(skill_id, str(skill_id)),
                reason="grace_expired",
                started_at=started_ms,
                elapsed_ms=elapsed_ms,
                grace_ms=CORE_REBUILD_MOVEMENT_DEBOUNCE_MS,
            )
            return False
        return True

    def _select_action(self, snapshot: _SoulTwistingSnapshot) -> _SoulTwistingAction:
        if snapshot.map_id <= 0 or snapshot.instance_uptime_ms <= 0:
            self._clear_core_rebuild_debounce(
                reason="lifecycle_changed", tick_ms=snapshot.tick_ms
            )
        if not snapshot.deployment_ready:
            self._clear_core_rebuild_debounce(
                reason="runtime_invalidated", tick_ms=snapshot.tick_ms
            )
        if snapshot.deployment_ready:
            if not snapshot.soul_twisting.equipped:
                self._clear_core_rebuild_debounce(
                    reason="runtime_invalidated", tick_ms=snapshot.tick_ms
                )
                return _SoulTwistingAction(
                    kind=_ActionKind.BLOCKED_NO_ACTION,
                    reason="soul_twisting_unavailable",
                )
            if not self._effect_is_ready(
                snapshot.soul_twisting, SOUL_TWISTING_READY_MS
            ):
                self._clear_core_rebuild_debounce(
                    reason="runtime_invalidated", tick_ms=snapshot.tick_ms
                )
                return _SoulTwistingAction(
                    kind=_ActionKind.SOUL_TWISTING_READINESS,
                    skill_id=Soul_Twisting_ID,
                    reason="soul_twisting_must_arm_before_core_deployment",
                )

            equipped_core = self._equipped_core_skills()
            if not equipped_core:
                self._clear_core_rebuild_debounce(
                    reason="runtime_invalidated", tick_ms=snapshot.tick_ms
                )
                return _SoulTwistingAction(
                    kind=_ActionKind.BLOCKED_NO_ACTION,
                    reason="no_core_skill_equipped",
                )
            if (
                self._core_rebuild_debounce_skill_id is not None
                and self._core_rebuild_debounce_skill_id not in equipped_core
            ):
                self._clear_core_rebuild_debounce(
                    reason="need_changed", tick_ms=snapshot.tick_ms
                )
            for skill_id in equipped_core:
                status = _core_status(snapshot, skill_id)
                if status.functional_covers:
                    if self._core_rebuild_debounce_skill_id == skill_id:
                        self._clear_core_rebuild_debounce(
                            reason="coverage_recovered", tick_ms=snapshot.tick_ms
                        )
                    continue
                if self._should_defer_core_rebuild(snapshot, skill_id, status):
                    # The deferred need remains the priority; do not fall through
                    # to a later core type while movement is still settling.
                    return _SoulTwistingAction(
                        kind=_ActionKind.BLOCKED_NO_ACTION,
                        skill_id=skill_id,
                        reason=(
                            "movement_debounce_"
                            f"{_CORE_SKILL_NAMES[skill_id]}"
                        ),
                    )
                reason = (
                    f"rebuild_out_of_coverage_{_CORE_SKILL_NAMES[skill_id]}"
                    if status.functional_exists
                    else f"missing_functional_coverage_{_CORE_SKILL_NAMES[skill_id]}"
                )
                return _SoulTwistingAction(
                    kind=_ActionKind.CORE_DEPLOYMENT,
                    skill_id=skill_id,
                    reason=reason,
                )
            if self._core_rebuild_debounce_skill_id is not None:
                self._clear_core_rebuild_debounce(
                    reason="coverage_recovered", tick_ms=snapshot.tick_ms
                )
            armor_eligible, armor_token_types, armor_reason = (
                self._armor_eligibility(snapshot)
            )
            if armor_eligible:
                self._emit_event(
                    "armor-selected",
                    signature=(snapshot.tick_ms, armor_token_types),
                    target_agent_id=0,
                    token_types=tuple(
                        _CORE_SKILL_NAMES[skill_id] for skill_id in armor_token_types
                    ),
                    reason=armor_reason,
                )
                return _SoulTwistingAction(
                    kind=_ActionKind.POST_DEPLOYMENT,
                    skill_id=Armor_of_Unfeeling_ID,
                    reason="armor_epoch_ready",
                    target_agent_id=0,
                )
            portable_action = self._select_portable_action(snapshot, allow_active=True)
            if portable_action is not None:
                return portable_action
            return _SoulTwistingAction(
                kind=_ActionKind.BLOCKED_NO_ACTION,
                reason="core_package_online_no_action",
            )

        portable_action = self._select_portable_action(snapshot)
        if portable_action is not None:
            return portable_action
        if snapshot.context is _EncounterContext.ACTIVE_COMBAT:
            return _SoulTwistingAction(
                kind=_ActionKind.BLOCKED_NO_ACTION,
                reason="active_combat_waiting_for_leader_coverage",
            )
        return _SoulTwistingAction(
            kind=_ActionKind.BLOCKED_NO_ACTION,
            reason="travel_or_preparation_no_readiness_action",
        )

    def _revalidate_action(
        self,
        action: _SoulTwistingAction,
        snapshot: _SoulTwistingSnapshot,
    ) -> tuple[bool, str]:
        if not snapshot.normal_cast_state:
            self._clear_core_rebuild_debounce(
                reason="runtime_invalidated", tick_ms=snapshot.tick_ms
            )
            return False, "normal_cast_state_closed"
        if action.kind is _ActionKind.SOUL_TWISTING_READINESS:
            if not snapshot.soul_twisting.equipped:
                return False, "soul_twisting_not_equipped_after_snapshot"
            if self._effect_is_ready(snapshot.soul_twisting, SOUL_TWISTING_READY_MS):
                return False, "soul_twisting_became_ready"
            if not snapshot.deployment_ready and not self._energy_is_healthy(snapshot):
                return False, "portable_energy_not_healthy"
            return True, "ready"

        if action.kind is _ActionKind.PORTABLE_READINESS:
            if (
                snapshot.context is _EncounterContext.ACTIVE_COMBAT
                and not snapshot.deployment_ready
            ):
                return False, "optional_readiness_preempted_by_active_combat"
            if not self._energy_is_healthy(snapshot):
                return False, "portable_energy_not_healthy"
            if action.skill_id == Boon_of_Creation_ID:
                if self._effect_is_ready(snapshot.boon_of_creation, BOON_REFRESH_MS):
                    return False, "boon_became_ready"
            elif action.skill_id == Spirits_Gift_ID:
                if self._effect_is_ready(
                    snapshot.spirits_gift, SPIRITS_GIFT_REFRESH_MS
                ):
                    return False, "spirits_gift_became_ready"
            else:
                return False, "unsupported_portable_action"
            return True, "ready"

        if action.kind is _ActionKind.CORE_DEPLOYMENT:
            if not snapshot.deployment_ready:
                self._clear_core_rebuild_debounce(
                    reason="runtime_invalidated", tick_ms=snapshot.tick_ms
                )
                return False, "deployment_window_closed"
            if not snapshot.soul_twisting.equipped:
                self._clear_core_rebuild_debounce(
                    reason="runtime_invalidated", tick_ms=snapshot.tick_ms
                )
                return False, "soul_twisting_not_equipped"
            if not self._effect_is_ready(
                snapshot.soul_twisting, SOUL_TWISTING_READY_MS
            ):
                self._clear_core_rebuild_debounce(
                    reason="runtime_invalidated", tick_ms=snapshot.tick_ms
                )
                return False, "soul_twisting_not_ready"
            if not self._is_skill_equipped(action.skill_id):
                self._clear_core_rebuild_debounce(
                    reason="need_changed", tick_ms=snapshot.tick_ms
                )
                return False, "core_skill_not_equipped"
            status = _core_status(snapshot, action.skill_id)
            if status.functional_covers:
                self._clear_core_rebuild_debounce(
                    reason="coverage_recovered", tick_ms=snapshot.tick_ms
                )
                return False, "functional_core_became_covered_before_cast"
            if not status.functional_exists:
                self._clear_core_rebuild_debounce(
                    reason="nonfunctional", tick_ms=snapshot.tick_ms
                )
            return True, "ready"

        if action.kind is _ActionKind.POST_DEPLOYMENT:
            if not snapshot.deployment_ready:
                return False, "deployment_window_closed"
            if not self._all_core_useful(snapshot):
                return False, "core_package_no_longer_useful"
            armor_eligible, _token_types, armor_reason = self._armor_eligibility(
                snapshot
            )
            if not armor_eligible:
                return False, armor_reason
            if action.target_agent_id != 0:
                return False, "armor_target_must_be_zero"
            return True, "ready"

        return False, "no_action"

    def _execute_action(
        self,
        action: _SoulTwistingAction,
    ) -> Generator[None, None, bool]:
        result = yield from self.CastSkillID(
            skill_id=action.skill_id,
            target_agent_id=action.target_agent_id,
            log=False,
            aftercast_delay=250,
        )
        return bool(result)

    @staticmethod
    def _armor_core_ids(
        snapshot: _SoulTwistingSnapshot, skill_id: int
    ) -> frozenset[int]:
        return frozenset(
            int(observation.agent_id)
            for observation in snapshot.core_spirits.get(skill_id, ())
        )

    @staticmethod
    def _deployment_event_key(event: Any) -> tuple[int, int, int, int, int, float]:
        return (
            int(getattr(event, "timestamp", 0)),
            int(getattr(event, "event_type", 0)),
            int(getattr(event, "agent_id", 0)),
            int(getattr(event, "value", 0)),
            int(getattr(event, "target_id", 0)),
            float(getattr(event, "float_value", 0.0)),
        )

    @staticmethod
    def _deployment_event_type_values() -> dict[str, int]:
        event_type_module = getattr(PyAgentEvents, "PyEventType", None)
        if event_type_module is None:
            return {}
        return {
            name: int(getattr(event_type_module, name))
            for name in _DEPLOYMENT_EVENT_TYPE_NAMES
            if getattr(event_type_module, name, None) is not None
        }

    @staticmethod
    def _deployment_event_type_name(event_type: int) -> str:
        for name, value in My_Soul_Twisting._deployment_event_type_values().items():
            if value == event_type:
                return name
        return f"TYPE_{event_type}"

    @staticmethod
    def _peek_deployment_events() -> list[Any] | None:
        try:
            return list(PyAgentEvents.peek_events() or [])
        except Exception:
            return None

    @staticmethod
    def _armor_witness_fingerprint(
        observation: _SpiritObservation,
    ) -> tuple[int, int, str]:
        return (
            int(observation.model_id),
            int(observation.owner_id),
            observation.root_category.value,
        )

    def _armor_token_witness(
        self,
        token: _ArmorDeploymentToken,
        snapshot: _SoulTwistingSnapshot,
    ) -> _SpiritObservation | None:
        if not snapshot.core_spirits_readable:
            return None
        observation = next(
            (
                candidate
                for candidate in snapshot.core_spirits.get(token.skill_id, ())
                if candidate.agent_id == token.witness_agent_id
            ),
            None,
        )
        if observation is None:
            return None
        if (
            observation.skill_id != token.skill_id
            or observation.model_id != token.model_id
            or observation.root_category is not _SpiritCategory.PARTY_ROOT_MATCH
            or not observation.alive
            or not observation.spawned
            or observation.position is None
            or self._armor_witness_fingerprint(observation)
            != token.witness_fingerprint
        ):
            return None
        return observation

    def _invalidate_armor_token(self, skill_id: int, *, reason: str) -> None:
        epoch = self._armor_deployment_epoch
        if epoch is None:
            return
        token = epoch.tokens.pop(skill_id, None)
        if token is None:
            return
        self._emit_event(
            "armor-deployment-token-invalidated",
            signature=(epoch.epoch_id, skill_id, token.witness_agent_id, reason),
            epoch_id=epoch.epoch_id,
            skill=_CORE_SKILL_NAMES[skill_id],
            witness_agent_id=token.witness_agent_id,
            reason=reason,
        )
        if not epoch.tokens:
            self._armor_deployment_epoch = None
            self._emit_event(
                "armor-deployment-epoch-closed",
                signature=(epoch.epoch_id, reason),
                epoch_id=epoch.epoch_id,
                reason=reason,
            )

    def _invalidate_armor_deployment_probe(
        self,
        probe: _ArmorDeploymentProbe,
        *,
        reason: str,
    ) -> None:
        if probe.invalid_reason is None:
            probe.invalid_reason = reason
            self._emit_event(
                "armor-deployment-probe-invalidated",
                signature=(probe.requested_at_ms, probe.skill_id, reason),
                skill=_CORE_SKILL_NAMES[probe.skill_id],
                request_at=probe.requested_at_ms,
                reason=reason,
            )
        if self._armor_deployment_probes.get(probe.skill_id) is probe:
            del self._armor_deployment_probes[probe.skill_id]
        if self._armor_deployment_active_cast is probe:
            self._armor_deployment_active_cast = None
        if self._armor_deployment_last_terminal_cast is probe:
            self._armor_deployment_last_terminal_cast = None

    def _reset_armor_deployment_state(self, *, reason: str) -> None:
        had_state = bool(
            self._armor_deployment_probes or self._armor_deployment_epoch is not None
        )
        for probe in tuple(self._armor_deployment_probes.values()):
            if probe.invalid_reason is None:
                probe.invalid_reason = reason
        self._armor_deployment_probes.clear()
        self._armor_deployment_active_cast = None
        self._armor_deployment_last_terminal_cast = None
        self._armor_deployment_epoch = None
        if had_state:
            self._emit_event(
                "armor-deployment-state-reset",
                signature=(reason,),
                reason=reason,
            )

    def _observe_armor_deployment_lifecycle(
        self, snapshot: _SoulTwistingSnapshot
    ) -> bool:
        lifecycle = (int(snapshot.map_id), int(snapshot.instance_uptime_ms))
        previous_lifecycle = self._armor_deployment_lifecycle
        previous_player_id = self._armor_deployment_player_agent_id
        if previous_lifecycle is not None and (
            lifecycle[0] != previous_lifecycle[0]
            or lifecycle[1] < previous_lifecycle[1]
        ):
            self._reset_armor_deployment_state(reason="map_or_instance_changed")
        if previous_player_id and snapshot.player_agent_id != previous_player_id:
            self._reset_armor_deployment_state(reason="player_agent_id_changed")
        self._armor_deployment_lifecycle = lifecycle
        self._armor_deployment_player_agent_id = snapshot.player_agent_id

        if (
            snapshot.map_id <= 0
            or snapshot.instance_uptime_ms <= 0
            or snapshot.player_agent_id <= 0
            or not snapshot.map_explorable
            or snapshot.map_loading
            or not snapshot.player_alive
        ):
            self._reset_armor_deployment_state(reason="runtime_not_ready")
            return False
        if not snapshot.core_spirits_readable:
            self._reset_armor_deployment_state(reason="core_scan_unreadable")
            return False
        return True

    def _record_deployment_event(
        self,
        probe: _ArmorDeploymentProbe,
        key: tuple[int, int, int, int, int, float],
        *,
        controlled: bool,
        association: str,
        allow_baseline: bool = False,
    ) -> bool:
        if (
            (not allow_baseline and key in probe.baseline_event_keys)
            or key in probe.seen_event_keys
        ):
            return False
        probe.seen_event_keys.add(key)
        event_type = self._deployment_event_type_name(key[1])
        record = _DeploymentEventRecord(
            event_type=event_type,
            timestamp_ms=key[0],
            caster_agent_id=key[2],
            skill_id=key[3],
            target_agent_id=key[4],
            float_value=key[5],
            controlled=controlled,
            association=association,
        )
        if len(probe.event_records) < _DEPLOYMENT_MAX_RECORDED_EVENTS:
            probe.event_records.append(record)
            self._emit_event(
                "armor-deployment-event",
                signature=(probe.requested_at_ms, key, controlled),
                skill=_CORE_SKILL_NAMES[probe.skill_id],
                event_type=event_type,
                event_timestamp=key[0],
                event_delay_ms=key[0] - probe.requested_at_ms,
                caster_agent_id=key[2],
                skill_id=key[3],
                target_agent_id=key[4],
                float_value=f"{key[5]:.3f}",
                controlled=int(controlled),
                association=association,
            )
        return True

    def _foreign_activation_in_lookback(
        self,
        events: list[Any],
        *,
        skill_id: int,
        player_agent_id: int,
        requested_at_ms: int,
    ) -> int | None:
        type_values = self._deployment_event_type_values()
        activation_values = {
            type_values[name]
            for name in _DEPLOYMENT_ACTIVATION_TYPES
            if name in type_values
        }
        for event in events:
            key = self._deployment_event_key(event)
            if (
                key[1] in activation_values
                and key[3] == skill_id
                and key[2] != player_agent_id
                and requested_at_ms - ARMOR_DEPLOYMENT_LOOKBACK_MS
                <= key[0]
                <= requested_at_ms
            ):
                return key[2]
        return None

    def _record_armor_deployment_request(
        self, skill_id: int, snapshot: _SoulTwistingSnapshot
    ) -> _ArmorDeploymentProbe | None:
        if skill_id not in _CORE_SKILLS:
            return None
        if self._armor_deployment_lifecycle is None:
            self._armor_deployment_lifecycle = (
                int(snapshot.map_id),
                int(snapshot.instance_uptime_ms),
            )
            self._armor_deployment_player_agent_id = snapshot.player_agent_id
        self._invalidate_armor_token(
            skill_id, reason="replacement_deployment_requested"
        )
        previous_probe = self._armor_deployment_probes.get(skill_id)
        if previous_probe is not None:
            self._invalidate_armor_deployment_probe(
                previous_probe, reason="replacement_deployment_requested"
            )
        if (
            not snapshot.core_spirits_readable
            or snapshot.player_position is None
            or snapshot.map_id <= 0
            or snapshot.instance_uptime_ms <= 0
            or snapshot.player_agent_id <= 0
            or not snapshot.map_explorable
            or snapshot.map_loading
            or not snapshot.player_alive
        ):
            self._emit_event(
                "armor-deployment-probe-rejected",
                signature=(skill_id, snapshot.tick_ms, "request_snapshot_unreadable"),
                skill=_CORE_SKILL_NAMES[skill_id],
                request_at=snapshot.tick_ms,
                reason="request_snapshot_unreadable",
            )
            return None

        events = self._peek_deployment_events()
        if events is None:
            self._emit_event(
                "armor-deployment-probe-rejected",
                signature=(skill_id, snapshot.tick_ms, "event_buffer_read_failed"),
                skill=_CORE_SKILL_NAMES[skill_id],
                request_at=snapshot.tick_ms,
                reason="event_buffer_read_failed",
            )
            return None
        foreign_caster = self._foreign_activation_in_lookback(
            events,
            skill_id=skill_id,
            player_agent_id=snapshot.player_agent_id,
            requested_at_ms=snapshot.tick_ms,
        )
        if foreign_caster is not None:
            self._emit_event(
                "armor-deployment-probe-rejected",
                signature=(skill_id, snapshot.tick_ms, foreign_caster),
                skill=_CORE_SKILL_NAMES[skill_id],
                request_at=snapshot.tick_ms,
                reason="foreign_activation_in_lookback",
                foreign_caster_agent_id=foreign_caster,
            )
            return None

        relevant_values = set(self._deployment_event_type_values().values())
        baseline_event_keys: set[tuple[int, int, int, int, int, float]] = set()
        for event in events:
            key = self._deployment_event_key(event)
            if key[1] in relevant_values:
                baseline_event_keys.add(key)
        probe = _ArmorDeploymentProbe(
            skill_id=skill_id,
            model_id=_CORE_MODEL_BY_SKILL[skill_id],
            requested_at_ms=snapshot.tick_ms,
            map_id=snapshot.map_id,
            instance_uptime_ms=snapshot.instance_uptime_ms,
            player_agent_id=snapshot.player_agent_id,
            cast_origin=snapshot.player_position,
            pre_agent_ids=self._armor_core_ids(snapshot, skill_id),
            baseline_event_keys=frozenset(baseline_event_keys),
        )
        self._armor_deployment_probes[skill_id] = probe
        self._emit_event(
            "armor-deployment-request",
            signature=(
                skill_id,
                snapshot.tick_ms,
                tuple(sorted(probe.pre_agent_ids)),
            ),
            skill=_CORE_SKILL_NAMES[skill_id],
            expected_model=probe.model_id,
            request_at=probe.requested_at_ms,
            map_id=probe.map_id,
            instance_uptime_ms=probe.instance_uptime_ms,
            player_agent_id=probe.player_agent_id,
            cast_origin=self._format_position(probe.cast_origin),
            pre_existing_same_model_ids=tuple(sorted(probe.pre_agent_ids)),
        )
        return probe

    def _record_armor_deployment_result(
        self,
        skill_id: int,
        result: bool,
        snapshot: _SoulTwistingSnapshot,
    ) -> None:
        probe = self._armor_deployment_probes.get(skill_id)
        if probe is None:
            return
        probe.wrapper_result = bool(result)
        self._emit_event(
            "armor-deployment-wrapper-result",
            signature=(probe.requested_at_ms, skill_id, bool(result)),
            skill=_CORE_SKILL_NAMES[skill_id],
            request_at=probe.requested_at_ms,
            wrapper_result=int(bool(result)),
            observed_at=snapshot.tick_ms,
            evidence_effect="telemetry_only",
        )

    def _process_deployment_events(
        self,
        snapshot: _SoulTwistingSnapshot,
        events: list[Any],
    ) -> None:
        type_values = self._deployment_event_type_values()
        if not type_values:
            for probe in tuple(self._armor_deployment_probes.values()):
                self._invalidate_armor_deployment_probe(
                    probe, reason="event_types_unavailable"
                )
            return
        relevant_values = set(type_values.values())
        ordered_events = sorted(
            (
                (index, event, self._deployment_event_key(event))
                for index, event in enumerate(events)
                if self._deployment_event_key(event)[1] in relevant_values
                and self._deployment_event_key(event)[0] <= snapshot.tick_ms
            ),
            key=lambda item: (item[2][0], item[0]),
        )
        snapshot_terminal_counts: dict[
            tuple[int, int, int, int, int, float], int
        ] = {}
        for _index, _event, key in ordered_events:
            if (
                self._deployment_event_type_name(key[1])
                in _DEPLOYMENT_TERMINAL_TYPES
            ):
                snapshot_terminal_counts[key] = (
                    snapshot_terminal_counts.get(key, 0) + 1
                )
        for _index, _event, key in ordered_events:
            event_type = self._deployment_event_type_name(key[1])
            if event_type in _DEPLOYMENT_ACTIVATION_TYPES:
                raw_skill_id = key[3]
                if raw_skill_id == 0:
                    continue
                last_terminal_cast = self._armor_deployment_last_terminal_cast
                if (
                    last_terminal_cast is not None
                    and last_terminal_cast.terminal_at_ms is not None
                    and key[2] == last_terminal_cast.player_agent_id
                    and key[0] > last_terminal_cast.terminal_at_ms
                ):
                    self._armor_deployment_last_terminal_cast = None
                for probe in tuple(self._armor_deployment_probes.values()):
                    if probe.invalid_reason is not None:
                        continue
                    if (
                        key[2] != probe.player_agent_id
                        and raw_skill_id == probe.skill_id
                        and key[0]
                        >= probe.requested_at_ms - ARMOR_DEPLOYMENT_LOOKBACK_MS
                    ):
                        if self._record_deployment_event(
                            probe,
                            key,
                            controlled=False,
                            association="foreign-caster-lookback",
                            allow_baseline=True,
                        ):
                            probe.foreign_event_casters.add(key[2])
                        self._invalidate_armor_deployment_probe(
                            probe, reason="foreign_expected_skill_activation"
                        )
                        continue
                    if (
                        key in probe.baseline_event_keys
                        or key in probe.seen_event_keys
                    ):
                        continue
                    if key[0] < probe.requested_at_ms:
                        continue
                    if raw_skill_id == probe.skill_id:
                        controlled = key[2] == probe.player_agent_id
                        if not controlled:
                            if self._record_deployment_event(
                                probe,
                                key,
                                controlled=False,
                                association="foreign-caster",
                            ):
                                probe.foreign_event_casters.add(key[2])
                            self._invalidate_armor_deployment_probe(
                                probe,
                                reason="foreign_expected_skill_activation",
                            )
                            continue
                        if probe.terminal_at_ms is not None:
                            self._record_deployment_event(
                                probe,
                                key,
                                controlled=True,
                                association="after-terminal",
                            )
                            self._invalidate_armor_deployment_probe(
                                probe,
                                reason="activation_after_terminal",
                            )
                            continue
                        if (
                            self._armor_deployment_active_cast is not None
                            and self._armor_deployment_active_cast is not probe
                            and self._armor_deployment_active_cast.invalid_reason is None
                        ):
                            self._invalidate_armor_deployment_probe(
                                self._armor_deployment_active_cast,
                                reason="intervening_controlled_skill_activation",
                            )
                        if event_type == "SKILL_ACTIVATE_PACKET":
                            self._record_deployment_event(
                                probe,
                                key,
                                controlled=True,
                                association="expected-skill",
                            )
                            if probe.activate_packet_at_ms is not None:
                                self._invalidate_armor_deployment_probe(
                                    probe, reason="duplicate_activation_packet"
                                )
                                continue
                            probe.activate_packet_at_ms = key[0]
                            self._armor_deployment_active_cast = probe
                        else:
                            if probe.activate_packet_at_ms is None:
                                self._record_deployment_event(
                                    probe,
                                    key,
                                    controlled=True,
                                    association="activation-before-packet",
                                )
                                self._invalidate_armor_deployment_probe(
                                    probe, reason="activation_before_packet"
                                )
                                continue
                            self._record_deployment_event(
                                probe,
                                key,
                                controlled=True,
                                association="expected-skill",
                            )
                            if probe.activation_at_ms is not None:
                                self._invalidate_armor_deployment_probe(
                                    probe, reason="duplicate_activation"
                                )
                                continue
                            probe.activation_at_ms = key[0]
                            self._armor_deployment_active_cast = probe
                    elif (
                        key[2] == probe.player_agent_id
                        and probe.terminal_at_ms is None
                    ):
                        self._record_deployment_event(
                            probe,
                            key,
                            controlled=True,
                            association="intervening-skill",
                        )
                        self._invalidate_armor_deployment_probe(
                            probe, reason="intervening_controlled_skill_activation"
                        )
                continue

            if event_type not in _DEPLOYMENT_TERMINAL_TYPES:
                continue
            for probe in tuple(self._armor_deployment_probes.values()):
                if probe.invalid_reason is not None or key[0] < probe.requested_at_ms:
                    continue
                if (
                    key in probe.baseline_event_keys
                    or key in probe.seen_event_keys
                ):
                    continue
                controlled = key[2] == probe.player_agent_id
                raw_skill_matches = key[3] in (0, probe.skill_id)
                active_for_probe = self._armor_deployment_active_cast is probe
                raw_zero_owner: _ArmorDeploymentProbe | None = None
                if key[3] == 0 and controlled:
                    active_cast = self._armor_deployment_active_cast
                    if (
                        active_cast is not None
                        and active_cast.invalid_reason is None
                        and active_cast.activate_packet_at_ms is not None
                        and active_cast.activate_packet_at_ms <= key[0]
                        and active_cast.player_agent_id == key[2]
                    ):
                        raw_zero_owner = active_cast
                    else:
                        last_terminal_cast = self._armor_deployment_last_terminal_cast
                        if (
                            last_terminal_cast is not None
                            and last_terminal_cast.terminal_at_ms is not None
                            and last_terminal_cast.invalid_reason is None
                            and self._armor_deployment_probes.get(
                                last_terminal_cast.skill_id
                            )
                            is last_terminal_cast
                            and last_terminal_cast.player_agent_id == key[2]
                            and last_terminal_cast.player_agent_id
                            == snapshot.player_agent_id
                            and last_terminal_cast.map_id == snapshot.map_id
                            and last_terminal_cast.instance_uptime_ms
                            <= snapshot.instance_uptime_ms
                            and self._armor_deployment_lifecycle is not None
                            and self._armor_deployment_lifecycle[0]
                            == snapshot.map_id
                            and self._armor_deployment_lifecycle[1]
                            <= snapshot.instance_uptime_ms
                            and self._armor_deployment_player_agent_id
                            == snapshot.player_agent_id
                            and last_terminal_cast.requested_at_ms
                            <= key[0]
                            and snapshot.tick_ms
                            - last_terminal_cast.requested_at_ms
                            <= ARMOR_DEPLOYMENT_PROBE_MAX_MS
                        ):
                            raw_zero_owner = last_terminal_cast
                        elif last_terminal_cast is not None:
                            self._armor_deployment_last_terminal_cast = None
                    if raw_zero_owner is None:
                        continue
                    if raw_zero_owner is not probe:
                        self._record_deployment_event(
                            probe,
                            key,
                            controlled=True,
                            association="other-controlled-cast",
                        )
                        continue
                if (
                    snapshot_terminal_counts.get(key, 0) > 1
                    and key not in probe.baseline_event_keys
                    and key[2] == probe.player_agent_id
                    and (
                        (key[3] == 0 and raw_zero_owner is probe)
                        or key[3] == probe.skill_id
                        or active_for_probe
                    )
                ):
                    self._record_deployment_event(
                        probe,
                        key,
                        controlled=True,
                        association="duplicate-terminal-in-snapshot",
                    )
                    self._invalidate_armor_deployment_probe(
                        probe, reason="duplicate_terminal_in_snapshot"
                    )
                    continue
                if (
                    not controlled
                    and key[3] == probe.skill_id
                ):
                    if self._record_deployment_event(
                        probe,
                        key,
                        controlled=False,
                        association="foreign-caster",
                    ):
                        probe.foreign_event_casters.add(key[2])
                    continue
                if not controlled:
                    continue
                if event_type == "SKILL_FINISHED" and key[3] != 0:
                    if key[3] == probe.skill_id or active_for_probe:
                        self._record_deployment_event(
                            probe,
                            key,
                            controlled=True,
                            association="nonzero-finish",
                        )
                        self._invalidate_armor_deployment_probe(
                            probe, reason="finish_value_nonzero"
                        )
                    continue
                if (
                    key[3] == 0
                    and probe.activation_at_ms is None
                ):
                    continue
                if probe.terminal_at_ms is not None and raw_skill_matches:
                    self._record_deployment_event(
                        probe,
                        key,
                        controlled=True,
                        association="after-terminal",
                    )
                    self._invalidate_armor_deployment_probe(
                        probe, reason="conflicting_or_duplicate_terminal"
                    )
                    continue
                if (
                    not raw_skill_matches
                    or (
                        key[3] == 0
                        and (
                            not active_for_probe
                            or probe.activation_at_ms is None
                        )
                    )
                    or (key[3] == probe.skill_id and not active_for_probe)
                ):
                    if active_for_probe or key[3] == probe.skill_id:
                        self._record_deployment_event(
                            probe,
                            key,
                            controlled=True,
                            association="uncertain-skill",
                        )
                        self._invalidate_armor_deployment_probe(
                            probe, reason="terminal_association_uncertain"
                        )
                    continue
                self._record_deployment_event(
                    probe,
                    key,
                    controlled=True,
                    association=(
                        "active-controlled-cast"
                        if key[3] == 0
                        else "expected-skill"
                    ),
                )
                if probe.terminal_at_ms is not None:
                    self._invalidate_armor_deployment_probe(
                        probe, reason="conflicting_or_duplicate_terminal"
                    )
                    continue
                probe.terminal_at_ms = key[0]
                probe.terminal_event_type = event_type
                self._armor_deployment_last_terminal_cast = probe
                if event_type == "SKILL_FINISHED":
                    probe.finish_at_ms = key[0]
                    if self._armor_deployment_active_cast is probe:
                        self._armor_deployment_active_cast = None
                else:
                    self._invalidate_armor_deployment_probe(
                        probe, reason=event_type.lower()
                    )

    def _update_deployment_candidates(
        self,
        probe: _ArmorDeploymentProbe,
        snapshot: _SoulTwistingSnapshot,
    ) -> None:
        observations = snapshot.core_spirits.get(probe.skill_id, ())
        current_ids: set[int] = set()
        for observation in observations:
            if (
                observation.model_id != probe.model_id
                or observation.agent_id in probe.pre_agent_ids
            ):
                continue
            agent_id = int(observation.agent_id)
            current_ids.add(agent_id)
            current_distance = self._safe_distance(
                probe.cast_origin, observation.position
            )
            candidate = probe.candidates.get(agent_id)
            if candidate is None:
                candidate = _DeploymentCandidate(
                    agent_id=agent_id,
                    first_seen_at_ms=snapshot.tick_ms,
                    first_spawned_at_ms=(
                        snapshot.tick_ms if observation.spawned else None
                    ),
                    first_alive=observation.alive,
                    first_position=observation.position,
                    first_distance_from_origin=current_distance,
                    last_seen_at_ms=snapshot.tick_ms,
                    last_spawned=observation.spawned,
                    last_alive=observation.alive,
                )
                probe.candidates[agent_id] = candidate
                self._emit_event(
                    "armor-deployment-candidate",
                    signature=(probe.requested_at_ms, probe.skill_id, agent_id),
                    skill=_CORE_SKILL_NAMES[probe.skill_id],
                    candidate_agent_id=agent_id,
                    first_visible_at=snapshot.tick_ms,
                    first_visible_delay_ms=(
                        snapshot.tick_ms - probe.requested_at_ms
                    ),
                    alive=int(observation.alive),
                    spawned=int(observation.spawned),
                    position=self._format_position(observation.position),
                    distance_from_origin=(
                        "na"
                        if candidate.first_distance_from_origin is None
                        else f"{candidate.first_distance_from_origin:.0f}"
                    ),
                )
            else:
                if observation.spawned and not candidate.last_spawned:
                    candidate.first_spawned_at_ms = (
                        candidate.first_spawned_at_ms or snapshot.tick_ms
                    )
                    self._emit_event(
                        "armor-deployment-candidate-state",
                        signature=(
                            probe.requested_at_ms,
                            agent_id,
                            "spawned",
                        ),
                        skill=_CORE_SKILL_NAMES[probe.skill_id],
                        candidate_agent_id=agent_id,
                        state="spawned",
                        spawned_at=snapshot.tick_ms,
                        spawned_delay_ms=(
                            snapshot.tick_ms - probe.requested_at_ms
                        ),
                    )
                candidate.last_seen_at_ms = snapshot.tick_ms
                candidate.last_spawned = observation.spawned
                candidate.last_alive = observation.alive
            if observation.alive and observation.spawned:
                if observation.position is None or current_distance is None:
                    self._invalidate_armor_deployment_probe(
                        probe, reason="candidate_position_unreadable"
                    )
                    return
                if not candidate.spawned_evidence_checked:
                    if current_distance > ARMOR_ASSOCIATION_RADIUS:
                        self._invalidate_armor_deployment_probe(
                            probe, reason="candidate_out_of_association_radius"
                        )
                        return
                    candidate.spawned_evidence_checked = True
            if (
                probe.finish_at_ms is not None
                and probe.qualifying_at_ms is None
                and candidate.qualified_at_ms is None
                and snapshot.tick_ms - probe.finish_at_ms
                > ARMOR_FINISH_TO_CANDIDATE_MS
            ):
                self._invalidate_armor_deployment_probe(
                    probe, reason="candidate_missing_or_late"
                )
                return
            currently_qualifying = (
                observation.root_category is _SpiritCategory.PARTY_ROOT_MATCH
                and observation.alive
                and observation.spawned
                and observation.position is not None
                and current_distance is not None
                and current_distance <= ARMOR_ASSOCIATION_RADIUS
            )
            if candidate.qualified_at_ms is not None and not currently_qualifying:
                self._invalidate_armor_deployment_probe(
                    probe, reason="candidate_qualification_lost"
                )
                return
            if candidate.qualified_at_ms is not None and (
                candidate.qualification_fingerprint is None
                or self._armor_witness_fingerprint(observation)
                != candidate.qualification_fingerprint
            ):
                self._invalidate_armor_deployment_probe(
                    probe, reason="candidate_identity_changed"
                )
                return
            if (
                probe.finish_at_ms is not None
                and probe.qualifying_at_ms is None
                and candidate.qualified_at_ms is None
                and snapshot.tick_ms >= probe.finish_at_ms
                and currently_qualifying
            ):
                candidate.qualified_at_ms = snapshot.tick_ms
                candidate.qualification_fingerprint = (
                    self._armor_witness_fingerprint(observation)
                )
                probe.qualifying_candidate_id = agent_id
                probe.qualifying_at_ms = snapshot.tick_ms
                probe.settle_until_ms = (
                    snapshot.tick_ms + ARMOR_CANDIDATE_SETTLE_MS
                )
                self._emit_event(
                    "armor-deployment-candidate-state",
                    signature=(
                        probe.requested_at_ms,
                        agent_id,
                        "qualified",
                    ),
                    skill=_CORE_SKILL_NAMES[probe.skill_id],
                    candidate_agent_id=agent_id,
                    state="qualified",
                    qualifying_at=snapshot.tick_ms,
                    settle_until=probe.settle_until_ms,
                    distance_from_origin=f"{self._safe_distance(probe.cast_origin, observation.position):.0f}",
                )

        disappeared = set(probe.candidates) - current_ids
        if disappeared:
            self._invalidate_armor_deployment_probe(
                probe, reason="candidate_disappeared"
            )
            return
        if len(probe.candidates) > 1:
            self._invalidate_armor_deployment_probe(
                probe, reason="multiple_new_same_model_candidates"
            )

    def _check_deployment_probe_timing(
        self,
        probe: _ArmorDeploymentProbe,
        now_ms: int,
    ) -> None:
        if probe.invalid_reason is not None:
            return
        request_delay = now_ms - probe.requested_at_ms
        if request_delay < 0:
            return
        # Candidate discovery has its own finish-based deadline. Once a
        # candidate qualifies, let its explicit ambiguity-settling phase finish
        # even when the next observer runs after the coarse request window.
        if (
            probe.qualifying_at_ms is None
            and request_delay > ARMOR_DEPLOYMENT_PROBE_MAX_MS
        ):
            self._invalidate_armor_deployment_probe(
                probe, reason="deployment_probe_window_expired"
            )
            return
        if (
            probe.activate_packet_at_ms is not None
            and probe.activate_packet_at_ms - probe.requested_at_ms
            > ARMOR_REQUEST_TO_ACTIVATION_MS
        ):
            self._invalidate_armor_deployment_probe(
                probe, reason="activation_packet_out_of_bounds"
            )
            return
        if (
            probe.activation_at_ms is None
            or probe.activate_packet_at_ms is None
        ):
            if request_delay > ARMOR_REQUEST_TO_ACTIVATION_MS:
                self._invalidate_armor_deployment_probe(
                    probe, reason="activation_sequence_missing_or_late"
                )
            return
        activation_delay = probe.activation_at_ms - probe.requested_at_ms
        if (
            activation_delay < 0
            or activation_delay > ARMOR_REQUEST_TO_ACTIVATION_MS
        ):
            self._invalidate_armor_deployment_probe(
                probe, reason="activation_out_of_bounds"
            )
            return
        if probe.finish_at_ms is None:
            if (
                now_ms - probe.activation_at_ms > ARMOR_ACTIVATION_TO_FINISH_MS
                or request_delay > ARMOR_REQUEST_TO_FINISH_MS
            ):
                self._invalidate_armor_deployment_probe(
                    probe, reason="finish_missing_or_late"
                )
            return
        finish_delay = probe.finish_at_ms - probe.activation_at_ms
        request_finish_delay = probe.finish_at_ms - probe.requested_at_ms
        if (
            finish_delay < 0
            or finish_delay > ARMOR_ACTIVATION_TO_FINISH_MS
            or request_finish_delay < 0
            or request_finish_delay > ARMOR_REQUEST_TO_FINISH_MS
        ):
            self._invalidate_armor_deployment_probe(
                probe, reason="finish_out_of_bounds"
            )
            return
        if probe.qualifying_at_ms is None:
            if (
                now_ms - probe.finish_at_ms
                > ARMOR_FINISH_TO_CANDIDATE_MS
            ):
                self._invalidate_armor_deployment_probe(
                    probe, reason="candidate_missing_or_late"
                )
            return
        if probe.settle_until_ms is not None and now_ms >= probe.settle_until_ms:
            self._issue_armor_deployment_token(probe, now_ms)

    def _issue_armor_deployment_token(
        self,
        probe: _ArmorDeploymentProbe,
        now_ms: int,
    ) -> None:
        if (
            probe.invalid_reason is not None
            or probe.token_issued
            or probe.qualifying_candidate_id is None
            or probe.qualifying_at_ms is None
            or probe.finish_at_ms is None
            or probe.settle_until_ms is None
            or now_ms < probe.settle_until_ms
        ):
            return
        candidate = probe.candidates.get(probe.qualifying_candidate_id)
        if candidate is None:
            self._invalidate_armor_deployment_probe(
                probe, reason="qualifying_candidate_missing"
            )
            return
        observation = next(
            (
                item
                for item in probe.current_observations
                if item.agent_id == candidate.agent_id
            ),
            None,
        )
        if observation is None:
            self._invalidate_armor_deployment_probe(
                probe, reason="qualifying_candidate_not_current"
            )
            return
        qualification_fingerprint = candidate.qualification_fingerprint
        if (
            qualification_fingerprint is None
            or self._armor_witness_fingerprint(observation)
            != qualification_fingerprint
        ):
            self._invalidate_armor_deployment_probe(
                probe, reason="candidate_identity_changed"
            )
            return
        current_distance = self._safe_distance(
            probe.cast_origin, observation.position
        )
        if not (
            observation.model_id == probe.model_id
            and observation.root_category is _SpiritCategory.PARTY_ROOT_MATCH
            and observation.alive
            and observation.spawned
            and observation.position is not None
            and current_distance is not None
            and current_distance <= ARMOR_ASSOCIATION_RADIUS
        ):
            self._invalidate_armor_deployment_probe(
                probe, reason="qualifying_candidate_not_current"
            )
            return
        probe_epoch_expires_at_ms = (
            probe.finish_at_ms + ARMOR_DEPLOYMENT_EPOCH_MS
        )
        if now_ms >= probe_epoch_expires_at_ms:
            self._invalidate_armor_deployment_probe(
                probe, reason="deployment_epoch_expired_before_token"
            )
            return
        epoch = self._armor_deployment_epoch
        if epoch is not None and now_ms >= epoch.expires_at_ms:
            if probe.finish_at_ms < epoch.expires_at_ms:
                self._invalidate_armor_deployment_probe(
                    probe, reason="deployment_epoch_expired_before_token"
                )
                return
            epoch = None
        if (
            epoch is None
            or epoch.map_id != probe.map_id
            or epoch.instance_uptime_ms > probe.instance_uptime_ms
            or epoch.player_agent_id != probe.player_agent_id
        ):
            self._armor_deployment_epoch_counter += 1
            epoch = _ArmorDeploymentEpoch(
                epoch_id=self._armor_deployment_epoch_counter,
                map_id=probe.map_id,
                instance_uptime_ms=probe.instance_uptime_ms,
                player_agent_id=probe.player_agent_id,
                started_at_ms=probe.finish_at_ms,
                expires_at_ms=probe_epoch_expires_at_ms,
            )
            self._armor_deployment_epoch = epoch
            self._emit_event(
                "armor-deployment-epoch-started",
                signature=(epoch.epoch_id, epoch.started_at_ms),
                epoch_id=epoch.epoch_id,
                started_at=epoch.started_at_ms,
                expires_at=epoch.expires_at_ms,
            )
        token = _ArmorDeploymentToken(
            skill_id=probe.skill_id,
            model_id=probe.model_id,
            witness_agent_id=candidate.agent_id,
            map_id=probe.map_id,
            instance_uptime_ms=probe.instance_uptime_ms,
            player_agent_id=probe.player_agent_id,
            request_at_ms=probe.requested_at_ms,
            finish_at_ms=probe.finish_at_ms,
            witness_fingerprint=qualification_fingerprint,
        )
        epoch.tokens[probe.skill_id] = token
        probe.token_issued = True
        self._emit_event(
            "armor-deployment-summary",
            signature=(probe.requested_at_ms, probe.skill_id, candidate.agent_id),
            skill=_CORE_SKILL_NAMES[probe.skill_id],
            expected_model=probe.model_id,
            player_agent_id=probe.player_agent_id,
            request_at=probe.requested_at_ms,
            activation_at=probe.activation_at_ms,
            activation_delay_ms=(
                "na"
                if probe.activation_at_ms is None
                else probe.activation_at_ms - probe.requested_at_ms
            ),
            finish_at=probe.finish_at_ms,
            finish_delay_ms=probe.finish_at_ms - probe.requested_at_ms,
            stopped_or_interrupted="no",
            candidate_ids=tuple(sorted(probe.candidates)),
            witness_agent_id=candidate.agent_id,
            first_visible_delay_ms=(
                candidate.first_seen_at_ms - probe.requested_at_ms
            ),
            spawned_delay_ms=(
                "na"
                if candidate.first_spawned_at_ms is None
                else candidate.first_spawned_at_ms - probe.requested_at_ms
            ),
            distance_from_origin=(
                "na"
                if candidate.first_distance_from_origin is None
                else f"{candidate.first_distance_from_origin:.0f}"
            ),
            ambiguity="no",
            wrapper_result=(
                "na" if probe.wrapper_result is None else int(probe.wrapper_result)
            ),
            epoch_id=epoch.epoch_id,
            epoch_expires_at=epoch.expires_at_ms,
            evidence="deployment_token_not_ownership",
        )
        if self._armor_deployment_probes.get(probe.skill_id) is probe:
            del self._armor_deployment_probes[probe.skill_id]
        if self._armor_deployment_active_cast is probe:
            self._armor_deployment_active_cast = None
        if self._armor_deployment_last_terminal_cast is probe:
            self._armor_deployment_last_terminal_cast = None

    def _observe_armor_deployment(
        self, snapshot: _SoulTwistingSnapshot
    ) -> None:
        if not self._observe_armor_deployment_lifecycle(snapshot):
            return
        if not self._armor_deployment_probes:
            for skill_id, token in tuple(
                (skill_id, token)
                for skill_id, token in (
                    ()
                    if self._armor_deployment_epoch is None
                    else self._armor_deployment_epoch.tokens.items()
                )
            ):
                if self._armor_token_witness(token, snapshot) is None:
                    self._invalidate_armor_token(
                        skill_id, reason="witness_invalidated"
                    )
            return
        events = self._peek_deployment_events()
        if events is None:
            self._reset_armor_deployment_state(reason="event_buffer_read_failed")
            return
        self._process_deployment_events(snapshot, events)
        for probe in tuple(self._armor_deployment_probes.values()):
            if probe.invalid_reason is not None:
                continue
            probe.current_observations = snapshot.core_spirits.get(
                probe.skill_id, ()
            )
            self._update_deployment_candidates(probe, snapshot)
            self._check_deployment_probe_timing(probe, snapshot.tick_ms)
        if self._armor_deployment_epoch is not None:
            for skill_id, token in tuple(
                self._armor_deployment_epoch.tokens.items()
            ):
                if self._armor_token_witness(token, snapshot) is None:
                    self._invalidate_armor_token(
                        skill_id, reason="witness_invalidated"
                    )

    def _consume_armor_deployment_epoch(
        self, snapshot: _SoulTwistingSnapshot
    ) -> bool:
        eligible, _token_types, _reason = self._armor_eligibility(snapshot)
        if not eligible:
            return False
        epoch = self._armor_deployment_epoch
        if epoch is None:
            return False
        self._emit_event(
            "armor-deployment-epoch-consumed",
            signature=(epoch.epoch_id, snapshot.tick_ms),
            epoch_id=epoch.epoch_id,
            consumed_at=snapshot.tick_ms,
            token_types=tuple(
                _CORE_SKILL_NAMES[skill_id] for skill_id in sorted(epoch.tokens)
            ),
        )
        self._armor_deployment_epoch = None
        return True

    def _run_policy(self, phase: str) -> BuildCoroutine:
        can_cast = self._normal_cast_state()
        if not can_cast:
            self._clear_core_rebuild_debounce(reason="runtime_invalidated")
            self._emit_event(
                "blocked",
                signature=(phase, "normal-cast-state"),
                phase=phase,
                reason="normal_cast_state",
                st_python_cost=SOUL_TWISTING_PYTHON_COST,
                st_live_min_cost=SOUL_TWISTING_LIVE_MIN_COST,
            )
            yield from Routines.Yield.wait(100)
            return False

        snapshot = self._build_snapshot()
        self._observe_armor_deployment(snapshot)
        action = self._select_action(snapshot)
        self._emit_action(action, phase=phase)
        if action.kind is _ActionKind.BLOCKED_NO_ACTION:
            return False

        # Reobserve all runtime gates immediately before the cast.  The
        # deployment evidence observer is passive and only reads the event
        # buffer, so readiness and Phase 1/2A policy stay on their normal path.
        latest_snapshot = self._build_snapshot()
        self._observe_armor_deployment(latest_snapshot)
        valid, rejection_reason = self._revalidate_action(action, latest_snapshot)
        if not valid:
            self._emit_event(
                "rejection",
                signature=(phase, action.kind.value, action.skill_id, rejection_reason),
                phase=phase,
                action=action.kind.value,
                skill=action.skill_id,
                reason=rejection_reason,
            )
            return False

        if action.kind is _ActionKind.CORE_DEPLOYMENT:
            self._emit_event(
                "core-request",
                signature=(phase, action.skill_id, latest_snapshot.tick_ms),
                phase=phase,
                skill=_CORE_SKILL_NAMES.get(action.skill_id, str(action.skill_id)),
                request_at=latest_snapshot.tick_ms,
                reason=action.reason,
            )
            self._record_armor_deployment_request(
                action.skill_id, latest_snapshot
            )

        if action.kind is _ActionKind.POST_DEPLOYMENT:
            if not self._consume_armor_deployment_epoch(latest_snapshot):
                self._emit_event(
                    "rejection",
                    signature=(phase, action.kind.value, "epoch-consume-failed"),
                    phase=phase,
                    action=action.kind.value,
                    skill=action.skill_id,
                    reason="deployment_epoch_changed_before_dispatch",
                )
                return False
            self._emit_event(
                "armor-dispatched",
                signature=(phase, latest_snapshot.tick_ms),
                phase=phase,
                target_agent_id=0,
                evidence="deployment_epoch_consumed",
            )

        result = yield from self._execute_action(action)
        if not result:
            if action.kind is _ActionKind.CORE_DEPLOYMENT:
                failed_snapshot = self._build_snapshot()
                self._record_armor_deployment_result(
                    action.skill_id,
                    False,
                    failed_snapshot,
                )
                self._observe_armor_deployment(failed_snapshot)
            cast_gate_reason = "shared_or_mechanical_cast_gate"
            if action.reason.startswith("rebuild_out_of_coverage_"):
                cast_gate_reason = (
                    "out_of_coverage_rebuild_blocked_by_shared_or_mechanical_cast_gate"
                )
            self._emit_event(
                "rejection",
                signature=(
                    phase,
                    action.kind.value,
                    action.skill_id,
                    cast_gate_reason,
                ),
                phase=phase,
                action=action.kind.value,
                skill=action.skill_id,
                reason=cast_gate_reason,
                st_python_cost=SOUL_TWISTING_PYTHON_COST,
                st_live_min_cost=SOUL_TWISTING_LIVE_MIN_COST,
            )
            return False

        after_snapshot = self._build_snapshot()
        if action.kind is _ActionKind.CORE_DEPLOYMENT:
            self._record_armor_deployment_result(
                action.skill_id,
                True,
                after_snapshot,
            )
        if action.kind is _ActionKind.CORE_DEPLOYMENT:
            self._clear_core_rebuild_debounce(
                reason="rebuild_completed", tick_ms=after_snapshot.tick_ms
            )
        self._observe_armor_deployment(after_snapshot)
        self._emit_event(
            "result",
            signature=(
                phase,
                action.kind.value,
                action.skill_id,
                after_snapshot.tick_ms,
            ),
            phase=phase,
            action=action.kind.value,
            skill=action.skill_id,
            result="success",
            energy_after=round(after_snapshot.current_energy, 2),
            st_python_cost=SOUL_TWISTING_PYTHON_COST,
            st_live_min_cost=SOUL_TWISTING_LIVE_MIN_COST,
        )
        if action.kind is _ActionKind.CORE_DEPLOYMENT:
            status = _core_status(after_snapshot, action.skill_id)
            self._emit_event(
                "core-spawn",
                signature=(action.skill_id, after_snapshot.tick_ms),
                skill=_CORE_SKILL_NAMES.get(action.skill_id, str(action.skill_id)),
                spawn_at=after_snapshot.tick_ms,
                functional_alive_spawned=status.functional_exists,
                functional_covers_leader=status.functional_covers,
                functional_out_of_coverage=status.functional_out_of_coverage,
            )
        return True

    def _run_ooc(self) -> BuildCoroutine:
        return (yield from self._run_policy("ooc"))

    def _run_combat(self) -> BuildCoroutine:
        return (yield from self._run_policy("combat"))

    @staticmethod
    def _format_position(position: Position | None) -> str:
        if position is None:
            return "na"
        return f"{position[0]:.0f},{position[1]:.0f}"

    def _emit_event(
        self,
        event: str,
        *,
        signature: tuple[Any, ...],
        force: bool = False,
        **fields: Any,
    ) -> None:
        last_signatures = getattr(self, "_diagnostic_last_signatures", None)
        if last_signatures is None:
            last_signatures = {}
            self._diagnostic_last_signatures = last_signatures
        if not force and last_signatures.get(event) == signature:
            return
        last_signatures[event] = signature
        tick_ms = self._now_ms()
        values = [f"t={tick_ms}", f"event={event}"]
        values.extend(f"{key}={value}" for key, value in fields.items())
        try:
            PySystem.Console.Log(
                "MySoulTwisting",
                "[MyST-DIAG] " + " ".join(values),
                PySystem.Console.MessageType.Info,
            )
        except Exception:
            return

    def _emit_action(self, action: _SoulTwistingAction, *, phase: str) -> None:
        self._emit_event(
            "action",
            signature=(phase, action.kind.value, action.skill_id, action.reason),
            phase=phase,
            action=action.kind.value,
            skill=action.skill_id,
            reason=action.reason,
        )


__all__ = ["My_Soul_Twisting"]
