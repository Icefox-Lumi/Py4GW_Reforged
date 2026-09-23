from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any

import PySystem

from Py4GWCoreLib import Agent
from Py4GWCoreLib import AgentArray
from Py4GWCoreLib import Allegiance
from Py4GWCoreLib import BuildMgr
from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Player
from Py4GWCoreLib import Profession
from Py4GWCoreLib import Routines
from Py4GWCoreLib import SpiritModelID
from Py4GWCoreLib import Utils
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build
from Py4GWCoreLib.Builds.Skills import SkillsTemplate
from Py4GWCoreLib.BuildMgr import BuildCoroutine
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
DIAGNOSTIC_HEARTBEAT_MS = 5000

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
    context: _EncounterContext = _EncounterContext.TRAVEL_READY
    local_in_aggro: bool = False
    leader_in_aggro: bool = False
    party_in_aggro: bool = False
    in_aggro: bool = False
    effective_in_aggro: bool = False
    close_to_aggro: bool = False
    player_agent_id: int = 0
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
    deployment_ready: bool = False
    soul_twisting: _EffectObservation = _EffectObservation()
    boon_of_creation: _EffectObservation = _EffectObservation()
    spirits_gift: _EffectObservation = _EffectObservation()
    core_spirits: dict[int, tuple[_SpiritObservation, ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True, slots=True)
class _SoulTwistingAction:
    kind: _ActionKind
    skill_id: int = 0
    reason: str = ""


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
        self._diagnostic_online = False
        self._diagnostic_previous_close: bool | None = None
        self._diagnostic_previous_leader_combat = False
        self._diagnostic_previous_deployment = False
        self._diagnostic_close_since: int | None = None
        self._diagnostic_leader_combat_since: int | None = None
        self._diagnostic_deployment_since: int | None = None
        self._diagnostic_functional_presence: dict[int, bool] = {}
        self._diagnostic_functional_spawn_since: dict[int, int | None] = {}
        self._diagnostic_last_heartbeat_ms = 0

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
    ) -> dict[int, tuple[_SpiritObservation, ...]]:
        observations: dict[int, list[_SpiritObservation]] = {
            skill_id: [] for skill_id in _CORE_SKILLS
        }
        try:
            spirit_array = list(AgentArray.GetSpiritPetArray() or [])
        except Exception:
            spirit_array = []

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
                continue

        return {skill_id: tuple(values) for skill_id, values in observations.items()}

    def _build_snapshot(self) -> _SoulTwistingSnapshot:
        tick_ms = self._now_ms()
        player_agent_id = self._read_local_agent_id()
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
        core_spirits = self._scan_core_spirits(
            party_root_ids=party_root_ids,
            player_position=player_position,
            leader_valid=leader_valid,
            leader_alive=leader_alive,
            leader_position=leader_position,
        )

        return _SoulTwistingSnapshot(
            tick_ms=tick_ms,
            context=context,
            local_in_aggro=local_in_aggro,
            leader_in_aggro=leader_in_aggro,
            party_in_aggro=party_in_aggro,
            in_aggro=effective_in_aggro,
            effective_in_aggro=effective_in_aggro,
            close_to_aggro=close_to_aggro,
            player_agent_id=player_agent_id,
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

    def _select_action(self, snapshot: _SoulTwistingSnapshot) -> _SoulTwistingAction:
        if snapshot.deployment_ready:
            if not snapshot.soul_twisting.equipped:
                return _SoulTwistingAction(
                    kind=_ActionKind.BLOCKED_NO_ACTION,
                    reason="soul_twisting_unavailable",
                )
            if not self._effect_is_ready(
                snapshot.soul_twisting, SOUL_TWISTING_READY_MS
            ):
                return _SoulTwistingAction(
                    kind=_ActionKind.SOUL_TWISTING_READINESS,
                    skill_id=Soul_Twisting_ID,
                    reason="soul_twisting_must_arm_before_core_deployment",
                )

            equipped_core = self._equipped_core_skills()
            if not equipped_core:
                return _SoulTwistingAction(
                    kind=_ActionKind.BLOCKED_NO_ACTION,
                    reason="no_core_skill_equipped",
                )
            for skill_id in equipped_core:
                status = _core_status(snapshot, skill_id)
                if not status.functional_covers:
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
            if self._armor_is_castable():
                return _SoulTwistingAction(
                    kind=_ActionKind.POST_DEPLOYMENT,
                    skill_id=Armor_of_Unfeeling_ID,
                    reason="post_deployment_armor_maintenance",
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
                return False, "deployment_window_closed"
            if not snapshot.soul_twisting.equipped:
                return False, "soul_twisting_not_equipped"
            if not self._effect_is_ready(
                snapshot.soul_twisting, SOUL_TWISTING_READY_MS
            ):
                return False, "soul_twisting_not_ready"
            if not self._is_skill_equipped(action.skill_id):
                return False, "core_skill_not_equipped"
            status = _core_status(snapshot, action.skill_id)
            if status.functional_covers:
                return False, "functional_core_became_covered_before_cast"
            return True, "ready"

        if action.kind is _ActionKind.POST_DEPLOYMENT:
            if not snapshot.deployment_ready:
                return False, "deployment_window_closed"
            if not self._all_core_useful(snapshot):
                return False, "core_package_no_longer_useful"
            return True, "ready"

        return False, "no_action"

    def _execute_action(
        self,
        action: _SoulTwistingAction,
    ) -> Generator[None, None, bool]:
        if (
            action.kind is _ActionKind.POST_DEPLOYMENT
            and action.skill_id == Armor_of_Unfeeling_ID
        ):
            try:
                result = yield from self.skills.Ritualist.Communing.Armor_of_Unfeeling()
            except Exception:
                result = False
            return bool(result)

        result = yield from self.CastSkillID(
            skill_id=action.skill_id,
            target_agent_id=0,
            log=False,
            aftercast_delay=250,
        )
        return bool(result)

    def _run_policy(self, phase: str) -> BuildCoroutine:
        can_cast = self._normal_cast_state()
        if not can_cast:
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
        self._emit_snapshot_diagnostics(snapshot, phase=phase)
        action = self._select_action(snapshot)
        self._emit_action(action, phase=phase)
        if action.kind is _ActionKind.BLOCKED_NO_ACTION:
            return False

        # Core actions always reobserve the encounter, leader geometry, ST, and
        # functional coverage immediately before casting.  The same seam
        # protects the portable actions from a stale effect snapshot.
        latest_snapshot = self._build_snapshot()
        self._emit_snapshot_diagnostics(latest_snapshot, phase=phase)
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

        result = yield from self._execute_action(action)
        if not result:
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
        self._emit_snapshot_diagnostics(after_snapshot, phase=phase)
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
    def _quantized_remaining(effect: _EffectObservation) -> int:
        return int(effect.remaining_ms // 500) * 500

    @staticmethod
    def _format_position(position: Position | None) -> str:
        if position is None:
            return "na"
        return f"{position[0]:.0f},{position[1]:.0f}"

    def _format_core_summary(self, snapshot: _SoulTwistingSnapshot) -> str:
        summary: list[str] = []
        for skill_id in _CORE_SKILLS:
            observations = snapshot.core_spirits.get(skill_id, ())
            if not observations:
                summary.append(f"{_CORE_SKILL_NAMES[skill_id]}:none")
                continue
            entries = []
            for observation in observations:
                distance_player = (
                    "na"
                    if observation.distance_from_player is None
                    else f"{observation.distance_from_player:.0f}"
                )
                distance_leader = (
                    "na"
                    if observation.distance_from_leader is None
                    else f"{observation.distance_from_leader:.0f}"
                )
                if (
                    observation.root_category is _SpiritCategory.PARTY_ROOT_MATCH
                    and observation.alive
                    and observation.spawned
                ):
                    coverage = (
                        "functional-covering"
                        if observation.covers_leader
                        else "functional-out-of-coverage"
                    )
                else:
                    coverage = "ignored"
                entries.append(
                    f"a={observation.agent_id}/root={observation.owner_id}"
                    f"/category={observation.root_category.value}/coverage={coverage}"
                    f"/alive={int(observation.alive)}/spawned={int(observation.spawned)}"
                    f"/hp={observation.hp_fraction:.2f}/dplayer={distance_player}/dleader={distance_leader}"
                )
            summary.append(f"{_CORE_SKILL_NAMES[skill_id]}:[{';'.join(entries)}]")
        return " ".join(summary)

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

    def _emit_snapshot_diagnostics(
        self, snapshot: _SoulTwistingSnapshot, *, phase: str
    ) -> None:
        if not self._diagnostic_online:
            self._diagnostic_online = True
            self._emit_event(
                "package",
                signature=("online",),
                package="online",
                build="My Soul Twisting",
            )

        if snapshot.close_to_aggro and self._diagnostic_previous_close is not True:
            self._diagnostic_close_since = snapshot.tick_ms
        elif not snapshot.close_to_aggro:
            self._diagnostic_close_since = None
        if snapshot.leader_in_aggro and not self._diagnostic_previous_leader_combat:
            self._diagnostic_leader_combat_since = snapshot.tick_ms
        elif not snapshot.leader_in_aggro:
            self._diagnostic_leader_combat_since = None
        if snapshot.deployment_ready and not self._diagnostic_previous_deployment:
            self._diagnostic_deployment_since = snapshot.tick_ms
        elif not snapshot.deployment_ready:
            self._diagnostic_deployment_since = None

        self._emit_event(
            "phase",
            signature=(phase, snapshot.context.value, snapshot.player_moving),
            phase=phase,
            context=snapshot.context.value,
            player_moving=int(snapshot.player_moving),
        )
        self._emit_event(
            "encounter",
            signature=(
                snapshot.context.value,
                snapshot.local_in_aggro,
                snapshot.leader_in_aggro,
                snapshot.party_in_aggro,
                snapshot.in_aggro,
                snapshot.effective_in_aggro,
                snapshot.close_to_aggro,
                self._diagnostic_close_since,
                self._diagnostic_leader_combat_since,
            ),
            context=snapshot.context.value,
            local=int(snapshot.local_in_aggro),
            leader=int(snapshot.leader_in_aggro),
            party=int(snapshot.party_in_aggro),
            in_aggro=int(snapshot.in_aggro),
            effective=int(snapshot.effective_in_aggro),
            close=int(snapshot.close_to_aggro),
            close_since=self._diagnostic_close_since,
            leader_combat_since=self._diagnostic_leader_combat_since,
        )
        self._emit_event(
            "geometry",
            signature=(
                self._format_position(snapshot.player_position),
                self._format_position(snapshot.leader_position),
                snapshot.leader_agent_id,
                snapshot.leader_valid,
                snapshot.leader_alive,
                snapshot.normal_cast_state,
                None
                if snapshot.distance_to_leader is None
                else round(snapshot.distance_to_leader),
                snapshot.deployment_ready,
            ),
            player=self._format_position(snapshot.player_position),
            leader=self._format_position(snapshot.leader_position),
            leader_id=snapshot.leader_agent_id,
            leader_valid=int(snapshot.leader_valid),
            leader_alive=int(snapshot.leader_alive),
            leader_moving=int(snapshot.leader_moving),
            normal_cast=int(snapshot.normal_cast_state),
            distance_to_leader=(
                "na"
                if snapshot.distance_to_leader is None
                else f"{snapshot.distance_to_leader:.0f}"
            ),
            radius=SPIRIT_PROTECTION_RADIUS,
            margin=SPIRIT_COVERAGE_SAFETY_MARGIN,
            deployment=int(snapshot.deployment_ready),
            deployment_since=self._diagnostic_deployment_since,
        )
        readiness_signature = (
            snapshot.soul_twisting.equipped,
            snapshot.soul_twisting.present,
            self._quantized_remaining(snapshot.soul_twisting),
            snapshot.boon_of_creation.equipped,
            snapshot.boon_of_creation.present,
            self._quantized_remaining(snapshot.boon_of_creation),
            snapshot.spirits_gift.equipped,
            snapshot.spirits_gift.present,
            self._quantized_remaining(snapshot.spirits_gift),
            round(snapshot.player_energy_fraction, 2),
        )
        self._emit_event(
            "readiness",
            signature=readiness_signature,
            st_equipped=int(snapshot.soul_twisting.equipped),
            st_present=int(snapshot.soul_twisting.present),
            st_remaining=snapshot.soul_twisting.remaining_ms,
            st_ready=int(
                self._effect_is_ready(snapshot.soul_twisting, SOUL_TWISTING_READY_MS)
            ),
            boon_equipped=int(snapshot.boon_of_creation.equipped),
            boon_present=int(snapshot.boon_of_creation.present),
            boon_remaining=snapshot.boon_of_creation.remaining_ms,
            gift_equipped=int(snapshot.spirits_gift.equipped),
            gift_present=int(snapshot.spirits_gift.present),
            gift_remaining=snapshot.spirits_gift.remaining_ms,
            energy_fraction=f"{snapshot.player_energy_fraction:.2f}",
            energy_before=f"{snapshot.current_energy:.2f}",
            energy_max=f"{snapshot.maximum_energy:.2f}",
            st_python_cost=SOUL_TWISTING_PYTHON_COST,
            st_live_min_cost=SOUL_TWISTING_LIVE_MIN_COST,
        )

        core_signature: list[Any] = []
        for skill_id in _CORE_SKILLS:
            observations = snapshot.core_spirits.get(skill_id, ())
            status = _core_status(snapshot, skill_id)
            present = status.functional_exists
            previous_present = self._diagnostic_functional_presence.get(skill_id, False)
            if present and not previous_present:
                self._diagnostic_functional_spawn_since[skill_id] = snapshot.tick_ms
            elif not present:
                self._diagnostic_functional_spawn_since[skill_id] = None
            self._diagnostic_functional_presence[skill_id] = present
            core_signature.append(
                (
                    skill_id,
                    tuple(
                        (
                            observation.agent_id,
                            observation.owner_id,
                            observation.root_category.value,
                            observation.alive,
                            observation.spawned,
                            round(observation.hp_fraction, 2),
                            None
                            if observation.distance_from_player is None
                            else round(observation.distance_from_player),
                            None
                            if observation.distance_from_leader is None
                            else round(observation.distance_from_leader),
                            observation.covers_leader,
                        )
                        for observation in observations
                    ),
                    status.functional_exists,
                    status.functional_covers,
                    status.functional_out_of_coverage,
                )
            )
        self._emit_event(
            "core",
            signature=(
                snapshot.player_agent_id,
                snapshot.local_native_root_id,
                tuple(sorted(snapshot.party_root_ids)),
                tuple(core_signature),
            ),
            player_agent_id=snapshot.player_agent_id,
            local_native_root_id=snapshot.local_native_root_id,
            party_root_ids=tuple(sorted(snapshot.party_root_ids)),
            summary=self._format_core_summary(snapshot),
            radius=SPIRIT_PROTECTION_RADIUS,
            functional_exists=tuple(
                _CORE_SKILL_NAMES[skill_id]
                for skill_id in _CORE_SKILLS
                if _core_status(snapshot, skill_id).functional_exists
            ),
            functional_covers=tuple(
                _CORE_SKILL_NAMES[skill_id]
                for skill_id in _CORE_SKILLS
                if _core_status(snapshot, skill_id).functional_covers
            ),
            spawn_since=tuple(
                (
                    _CORE_SKILL_NAMES[skill_id],
                    self._diagnostic_functional_spawn_since.get(skill_id),
                )
                for skill_id in _CORE_SKILLS
            ),
            functional_out_of_coverage=tuple(
                _CORE_SKILL_NAMES[skill_id]
                for skill_id in _CORE_SKILLS
                if _core_status(snapshot, skill_id).functional_out_of_coverage
            ),
        )

        if (
            snapshot.tick_ms - self._diagnostic_last_heartbeat_ms
            >= DIAGNOSTIC_HEARTBEAT_MS
        ):
            self._diagnostic_last_heartbeat_ms = snapshot.tick_ms
            self._emit_event(
                "heartbeat",
                signature=(
                    snapshot.tick_ms // DIAGNOSTIC_HEARTBEAT_MS,
                    phase,
                    snapshot.context.value,
                ),
                force=True,
                phase=phase,
                context=snapshot.context.value,
                deployment=int(snapshot.deployment_ready),
                leader_distance=(
                    "na"
                    if snapshot.distance_to_leader is None
                    else f"{snapshot.distance_to_leader:.0f}"
                ),
            )

        self._diagnostic_previous_close = snapshot.close_to_aggro
        self._diagnostic_previous_leader_combat = snapshot.leader_in_aggro
        self._diagnostic_previous_deployment = snapshot.deployment_ready


__all__ = ["My_Soul_Twisting"]
