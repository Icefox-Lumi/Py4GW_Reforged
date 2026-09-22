from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from enum import IntEnum
from typing import Any
from typing import Callable

import PySystem

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import BuildMgr
from Py4GWCoreLib import Map
from Py4GWCoreLib import Player
from Py4GWCoreLib import Profession
from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib import SkillBar
from Py4GWCoreLib import Utils
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build
from Py4GWCoreLib.Builds.Skills import HexRemovalPriority
from Py4GWCoreLib.Builds.Skills import SkillsTemplate
from Py4GWCoreLib.enums_src.GameData_enums import Attribute
from Py4GWCoreLib.enums_src.Whiteboard_enums import WhiteboardLockKind
from Py4GWCoreLib.GlobalCache.shared_memory_src import Globals as _SharedMemoryGlobals
from Py4GWCoreLib.GlobalCache.WhiteboardLocks import claim_resurrection_target
from Py4GWCoreLib.Skill import Skill

HEALING_BURST_ID = Skill.GetID("Healing_Burst")
DWAYNAS_KISS_ID = Skill.GetID("Dwaynas_Kiss")
GREAT_DWARF_ARMOR_ID = Skill.GetID("Great_Dwarf_Armor")
SIGNET_OF_REJUVENATION_ID = Skill.GetID("Signet_of_Rejuvenation")
PATIENT_SPIRIT_ID = Skill.GetID("Patient_Spirit")
DRAW_CONDITIONS_ID = Skill.GetID("Draw_Conditions")
AEGIS_ID = Skill.GetID("Aegis")
RESTORE_LIFE_ID = Skill.GetID("Restore_Life")
SEED_OF_LIFE_ID = Skill.GetID("Seed_of_Life")
CURE_HEX_ID = Skill.GetID("Cure_Hex")
EBON_BATTLE_STANDARD_OF_WISDOM_ID = Skill.GetID("Ebon_Battle_Standard_of_Wisdom")
OOC_EMERGENCY_HEALTH_THRESHOLD = 0.50
COMBAT_CRITICAL_HEALTH_THRESHOLD = 0.35
COMBAT_PRESSURE_DROP_THRESHOLD = 0.08
AEGIS_PRESSURE_DROP_THRESHOLD = 0.10
DIVINE_FAVOR_HEAL_PER_RANK = 3.2
SEED_TRIGGER_HEAL_PER_RANK = 2.0
SHARED_EFFECT_FRESHNESS_MS = 150
# AgentDataStruct stages fast fields and medium animation fields independently;
# LastUpdated only marks the enclosing account update, not these field writes.
_SHARED_AGENT_STAGE_COUNT = 4
_SHARED_EFFECT_FIELD_MAX_AGE_MS = (
    _SharedMemoryGlobals.SHMEM_AGENT_FAST_UPDATE_THROTTLE_MS * _SHARED_AGENT_STAGE_COUNT
)
_SHARED_ACTIVITY_FIELD_MAX_AGE_MS = (
    _SharedMemoryGlobals.SHMEM_AGENT_MEDIUM_UPDATE_THROTTLE_MS
    * _SHARED_AGENT_STAGE_COUNT
)

# TEMPORARY live emergency-healing diagnostics. Remove this block after the
# reaction investigation is complete. The trace is deliberately build-local;
# it must not become another owner of healing or scheduling decisions.
_TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED = True
_DIAGNOSTIC_MODULE_NAME = "HealingBurstSupportDiag"
_DIAGNOSTIC_HEALTH_THRESHOLD = 0.80
_DIAGNOSTIC_CALLBACK_GAP_MS = 500
_DIAGNOSTIC_HEARTBEAT_MS = 1000
_DIAGNOSTIC_OOC_PROBE_INTERVAL_MS = 500
_SURVIVAL_PRESSURE_WEIGHT = 0.50
_PATIENT_HEALTH_CEILING = 0.85
_PATIENT_SAFE_HEALTH_FLOOR = 0.45
_PATIENT_SAFE_DROP_LIMIT = COMBAT_PRESSURE_DROP_THRESHOLD
_PATIENT_MIN_MISSING_FRACTION = 0.12
_PATIENT_DELAYED_HEAL_FRACTION = 0.50
_SEED_MIN_DROP = 0.10
_SEED_HEALTH_CEILING = 0.70
_SEED_LARGE_DROP = 0.18
_HEALTH_TREND_MAX_GAP_MS = 1000
_HEALTH_TREND_EPSILON = 0.01


def _diagnostic_log(message: str) -> None:
    if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
        return
    try:
        PySystem.Console.Log(
            _DIAGNOSTIC_MODULE_NAME,
            f"[HBS-DIAG] {message}",
            PySystem.Console.MessageType.Info,
        )
    except Exception:
        try:
            print(f"[HBS-DIAG] {message}")
        except Exception:
            pass


def _diagnostic_ooc_log(message: str) -> None:
    if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
        return
    try:
        PySystem.Console.Log(
            _DIAGNOSTIC_MODULE_NAME,
            f"[HBS-OOC-DIAG] {message}",
            PySystem.Console.MessageType.Info,
        )
    except Exception:
        try:
            print(f"[HBS-OOC-DIAG] {message}")
        except Exception:
            pass


REQUIRED_SKILLS = [
    HEALING_BURST_ID,
    DWAYNAS_KISS_ID,
]

OPTIONAL_SKILLS = [
    GREAT_DWARF_ARMOR_ID,
    SIGNET_OF_REJUVENATION_ID,
    PATIENT_SPIRIT_ID,
    DRAW_CONDITIONS_ID,
    AEGIS_ID,
    RESTORE_LIFE_ID,
    SEED_OF_LIFE_ID,
    CURE_HEX_ID,
    EBON_BATTLE_STANDARD_OF_WISDOM_ID,
]

SUPPORTED_SKILLS = REQUIRED_SKILLS + OPTIONAL_SKILLS
_REQUIRED_SKILL_SET = frozenset(REQUIRED_SKILLS)
_SUPPORTED_SKILL_SET = frozenset(SUPPORTED_SKILLS)
_MATCH_SCORE_BONUS = 1000
_DIAGNOSTIC_RELEVANT_SKILLS = (
    HEALING_BURST_ID,
    DWAYNAS_KISS_ID,
    SIGNET_OF_REJUVENATION_ID,
    PATIENT_SPIRIT_ID,
    SEED_OF_LIFE_ID,
)


class _CombatUrgency(IntEnum):
    MAINTENANCE = 0
    CURRENT_INJURY = 1
    URGENT_REACTIVE = 2
    CRITICAL_IMMEDIATE = 3


@dataclass(slots=True)
class _SkillSnapshot:
    skill_id: int
    equipped: bool
    castable: bool
    energy_cost: float = 0.0
    activation_seconds: float = 0.0
    aftercast_seconds: float = 0.0
    recharge_seconds: float = 0.0
    scale_0: float = 0.0
    scale_15: float = 0.0
    bonus_scale_0: float = 0.0
    bonus_scale_15: float = 0.0


@dataclass(slots=True)
class _PartyMemberSnapshot:
    agent_id: int
    party_order: int
    is_self: bool
    valid: bool
    alive: bool
    health: float
    maximum_health: float
    missing_hp: float
    position: tuple[float, float] | None
    distance_from_player: float
    recent_health_drop: float
    health_is_falling: bool
    is_critical: bool
    is_pressure_target: bool
    is_aegis_spike_target: bool
    is_injured: bool
    is_martial: bool
    is_melee: bool
    is_attacking: bool
    is_casting: bool
    health_is_recovering: bool = False


@dataclass(slots=True)
class _EffectSummary:
    supported_count: int
    minimum_count: int
    confidence: str
    source: str
    snapshot_age_ms: int | None = None


@dataclass(slots=True)
class _SharedAgentSnapshot:
    last_updated: int
    effect_ids: frozenset[int]
    exact_effects_available: bool
    is_enchanted: bool
    is_hexed: bool
    is_attacking: bool
    is_casting: bool


@dataclass(slots=True)
class _DiagnosticMemberObservation:
    agent_id: int
    present: bool
    valid: bool
    alive: bool
    is_remote: bool
    health: float | None
    native_health: float | None
    shared_health: float | None
    shared_found: bool
    shared_age_ms: int | None
    maximum_health: float | None
    missing_hp: float | None
    position_available: bool
    distance_from_player: float | None
    recent_health_drop: float
    is_critical: bool | None
    is_pressure: bool | None
    is_injured: bool | None


@dataclass(slots=True)
class _DiagnosticEpisode:
    started_tick: int
    last_logged_tick: int
    is_remote: bool
    last_signature: tuple[Any, ...] | None = None
    last_candidate_tick: int = 0
    last_candidate_signature: tuple[Any, ...] | None = None


@dataclass(slots=True)
class _CombatContext:
    tick_ms: int
    player_id: int
    player_position: tuple[float, float] | None
    party_members: tuple[_PartyMemberSnapshot, ...]
    party_by_id: dict[int, _PartyMemberSnapshot]
    critical_ids: tuple[int, ...]
    pressure_ids: tuple[int, ...]
    aegis_actionable_ids: tuple[int, ...]
    injured_ids: tuple[int, ...]
    critical_missing_hp: float
    pressure_missing_hp: float
    injured_missing_hp: float
    healing_prayers_rank: int
    divine_favor_rank: int
    protection_prayers_rank: int
    current_energy: float
    maximum_energy: float
    skill_states: dict[int, _SkillSnapshot]
    specialized_spike_candidates: tuple[int, ...]
    nearby_enemy_count: int
    nearby_martial_enemy_count: int
    nearby_attacking_martial_enemy_count: int
    distance_cache: dict[tuple[int, int], float] = field(default_factory=dict)
    effect_summary_cache: dict[int, _EffectSummary] = field(default_factory=dict)
    effect_presence_cache: dict[tuple[int, int], bool] = field(default_factory=dict)
    shared_last_updated: dict[int, int] = field(default_factory=dict)
    shared_effect_snapshots: dict[int, _SharedAgentSnapshot] = field(
        default_factory=dict
    )
    party_player_ids: frozenset[int] = frozenset()
    diagnostic_rejections: dict[int, dict[int, list[str]]] = field(default_factory=dict)
    diagnostic_aux_rejections: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _CombatActionCandidate:
    skill_id: int
    target_agent_id: int
    urgency: _CombatUrgency
    primary_value: float
    secondary_value: float
    time_to_primary_effect: float
    energy_spend_fraction: float
    evaluator_order: int
    target_order: int
    preempts_high_cure: bool
    revalidate: Callable[[], bool]
    execute: Callable[[], Any]
    diagnostic_reason: str
    rescue_revalidate: Callable[[], bool] | None = None
    target_health: float = 1.0
    target_recent_health_drop: float = 0.0


class My_Healing_Burst(BuildMgr):
    """Monk healing/protection controller for a full supported skillbar."""

    def __init__(self, match_only: bool = False):
        super().__init__(
            name="My Healing Burst",
            required_primary=Profession.Monk,
            # BuildMgr treats Profession(0) as the wildcard secondary.
            required_secondary=Profession(0),
            template_code="OwAS0YITeRNgbE5gsi4iTf6EA",
            required_skills=list(REQUIRED_SKILLS),
            optional_skills=list(OPTIONAL_SKILLS),
        )

        # BuildRegistry uses match_only construction for scoring. Keep all
        # runtime helpers and fallback setup below this guard.
        if match_only:
            return

        self.SetFallback("HeroAI", HeroAI_Build(standalone_fallback=True))
        self.SetOOCFn(self._process_ooc)
        self.SetCombatFn(self._process_combat)
        self._health_trend_history: dict[int, tuple[tuple[int, float], ...]] = {}
        self._diagnostic_last_callback_tick: int | None = None
        self._diagnostic_last_callback_run: str | None = None
        self._diagnostic_last_ooc_probe_tick: int | None = None
        self._diagnostic_last_aux_candidate_tick = 0
        self._diagnostic_last_aux_candidate_signature: tuple[Any, ...] | None = None
        self._diagnostic_last_decision_tick = 0
        self._diagnostic_last_decision_signature: tuple[Any, ...] | None = None
        self._diagnostic_last_high_cure_tick = 0
        self._diagnostic_last_high_cure_signature: tuple[Any, ...] | None = None
        self._diagnostic_last_patient_blocker_tick = 0
        self._diagnostic_last_patient_blocker_signature: tuple[Any, ...] | None = None
        self._diagnostic_revalidation_state: dict[
            tuple[int, int, str], tuple[bool, int]
        ] = {}
        self._diagnostic_episodes: dict[int, _DiagnosticEpisode] = {}
        self._diagnostic_ooc_last_state: dict[
            str, tuple[tuple[Any, ...], int]
        ] = {}
        self._diagnostic_ooc_actual_party_ids: tuple[int, ...] = ()
        self._diagnostic_ooc_probe_observations: tuple[
            _DiagnosticMemberObservation, ...
        ] = ()
        self._diagnostic_ooc_active_ids: tuple[int, ...] = ()
        self._diagnostic_ooc_trace_active = False
        self.skillbook: SkillsTemplate = SkillsTemplate(self)
        self._combat_evaluators: tuple[
            Callable[..., list[_CombatActionCandidate]], ...
        ] = (
            self._evaluate_healing_burst,
            self._evaluate_dwaynas_kiss,
            self._evaluate_signet_of_rejuvenation,
            self._evaluate_patient_spirit,
            self._evaluate_seed_of_life,
            self._evaluate_aegis,
        )

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

        # This controller owns the normal full-bar form only. BuildMgr filters
        # empty slots in _get_current_skills(), so eight entries means all eight
        # skillbar slots are populated.
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

        # The explicit bonus makes a valid supported bar win over the older
        # generic Healing Burst matcher without relying on registry order.
        return _MATCH_SCORE_BONUS + base_score

    def _is_castable(self, skill_id: int) -> bool:
        return self.IsSkillEquipped(skill_id) and self.CanCastSkillID(skill_id)

    @staticmethod
    def _diagnostic_ooc_value(value: Any) -> str:
        if value is None:
            return "na"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            if math.isnan(value):
                return "nan"
            if math.isinf(value):
                return "inf" if value > 0 else "-inf"
            return f"{value:.3f}"
        if isinstance(value, (tuple, list)):
            return "|".join(
                My_Healing_Burst._diagnostic_ooc_value(item)
                for item in value
            ) or "none"
        text = str(value)
        return "".join(
            character
            if character.isalnum() or character in "_-.:,;|=/[]?"
            else "_"
            for character in text
        ) or "na"

    @classmethod
    def _diagnostic_ooc_signature_value(cls, value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 2) if math.isfinite(value) else cls._diagnostic_ooc_value(value)
        if isinstance(value, (tuple, list)):
            return tuple(cls._diagnostic_ooc_signature_value(item) for item in value)
        if isinstance(value, dict):
            return tuple(
                (key, cls._diagnostic_ooc_signature_value(item))
                for key, item in sorted(value.items())
            )
        return value

    def _diagnostic_log_ooc_state(
        self,
        key: str,
        kind: str,
        fields: dict[str, Any],
        *,
        signature_fields: dict[str, Any] | None = None,
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            tick_ms = self._diagnostic_tick()
            signature_source = signature_fields or fields
            signature = tuple(
                (
                    field_name,
                    self._diagnostic_ooc_signature_value(field_value),
                )
                for field_name, field_value in sorted(signature_source.items())
            )
            previous = self._diagnostic_ooc_last_state.get(key)
            heartbeat_due = (
                previous is not None
                and tick_ms - previous[1] >= _DIAGNOSTIC_HEARTBEAT_MS
            )
            if previous is not None and previous[0] == signature and not heartbeat_due:
                return
            rendered_fields = " ".join(
                f"{self._diagnostic_safe_label(field_name)}="
                f"{self._diagnostic_ooc_value(field_value)}"
                for field_name, field_value in sorted(fields.items())
            )
            _diagnostic_ooc_log(
                f"kind={self._diagnostic_safe_label(kind)} "
                f"tick={tick_ms} key={self._diagnostic_safe_label(key)} "
                f"{rendered_fields}"
            )
            self._diagnostic_ooc_last_state[key] = (signature, tick_ms)
        except Exception:
            return

    def _diagnostic_ooc_state_would_emit(
        self,
        key: str,
        signature_fields: dict[str, Any],
    ) -> bool:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return False
        try:
            tick_ms = self._diagnostic_tick()
            signature = tuple(
                (
                    field_name,
                    self._diagnostic_ooc_signature_value(field_value),
                )
                for field_name, field_value in sorted(signature_fields.items())
            )
            previous = self._diagnostic_ooc_last_state.get(key)
            return bool(
                previous is None
                or previous[0] != signature
                or tick_ms - previous[1] >= _DIAGNOSTIC_HEARTBEAT_MS
            )
        except Exception:
            return False

    def _diagnostic_ooc_emergency_members(
        self,
    ) -> tuple[list[int], list[dict[str, Any]], bool]:
        actual_party_ids = list(self._diagnostic_ooc_actual_party_ids)
        active_ids = set(self._diagnostic_ooc_active_ids)
        members: list[dict[str, Any]] = []
        observations_by_id = {
            observation.agent_id: observation
            for observation in self._diagnostic_ooc_probe_observations
        }
        for agent_id in actual_party_ids:
            observation = observations_by_id.get(agent_id)
            valid = observation.valid if observation is not None else None
            alive = observation.alive if observation is not None else None
            health = observation.native_health if observation is not None else None
            distance = (
                observation.distance_from_player if observation is not None else None
            )
            threshold_ok = agent_id in active_ids
            emergency_member = threshold_ok
            party_member = True
            members.append(
                {
                    "agent_id": agent_id,
                    "actual_party": True,
                    "valid": valid,
                    "alive": alive,
                    "party_member": party_member,
                    "health": health,
                    "distance": distance,
                    "threshold": threshold_ok,
                    "emergency": emergency_member,
                }
            )
        return actual_party_ids, members, bool(active_ids)

    def _diagnostic_ooc_member_summary(
        self,
        members: list[dict[str, Any]],
    ) -> str:
        return ";".join(
            ":".join(
                (
                    str(member.get("agent_id", 0)),
                    f"h={self._diagnostic_ooc_value(member.get('health'))}",
                    f"valid={self._diagnostic_ooc_value(member.get('valid'))}",
                    f"alive={self._diagnostic_ooc_value(member.get('alive'))}",
                    f"party={self._diagnostic_ooc_value(member.get('party_member'))}",
                    f"dist={self._diagnostic_ooc_value(member.get('distance'))}",
                    f"threshold={self._diagnostic_ooc_value(member.get('threshold'))}",
                    f"emergency={self._diagnostic_ooc_value(member.get('emergency'))}",
                )
            )
            for member in members
        ) or "none"

    def _diagnostic_ooc_emergency_active(self) -> bool:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return False
        actual_party_ids, members, emergency_active = (
            self._diagnostic_ooc_emergency_members()
        )
        if not emergency_active:
            return False
        low_ids = [
            member["agent_id"]
            for member in members
            if member.get("emergency")
        ]
        signature_fields = {
            "stage": "emergency_active",
            "threshold": OOC_EMERGENCY_HEALTH_THRESHOLD,
            "actual_n": len(actual_party_ids),
            "low_ids": low_ids,
            "member_signature": tuple(
                (
                    member.get("agent_id"),
                    member.get("health"),
                    member.get("valid"),
                    member.get("alive"),
                    member.get("distance"),
                    member.get("threshold"),
                    member.get("emergency"),
                )
                for member in members
            ),
        }
        if not self._diagnostic_ooc_state_would_emit(
            "emergency_interval",
            signature_fields,
        ):
            return True
        fields = {
            key: signature_fields[key]
            for key in ("stage", "threshold", "actual_n", "low_ids")
        }
        fields["members"] = self._diagnostic_ooc_member_summary(members)
        self._diagnostic_log_ooc_state(
            "emergency_interval",
            "interval",
            fields,
            signature_fields=signature_fields,
        )
        return True

    def _diagnostic_ooc_should_trace_skill(self, skill_id: int) -> bool:
        if (
            not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED
            or not self._diagnostic_ooc_trace_active
        ):
            return False
        if skill_id == SIGNET_OF_REJUVENATION_ID:
            try:
                return bool(self.IsSkillEquipped(skill_id))
            except Exception:
                return False
        return True

    def _diagnostic_ooc_skill_state(self, skill_id: int) -> dict[str, Any]:
        snapshot = self._get_skill_snapshot(skill_id)
        try:
            slot = int(SkillBar.GetSlotBySkillID(skill_id) or 0)
        except Exception:
            slot = 0

        def optional_bool(getter: Callable[[], Any]) -> bool | None:
            try:
                return bool(getter())
            except Exception:
                return None

        map_explorable = optional_bool(Routines.Checks.Map.IsExplorable)
        cast_pending = optional_bool(self._is_local_cast_pending)
        energy_ok = optional_bool(
            lambda: Routines.Checks.Skills.HasEnoughEnergy(
                Player.GetAgentID(),
                skill_id,
            )
        )
        ready = optional_bool(
            lambda: Routines.Checks.Skills.IsSkillIDReady(skill_id)
        )
        shared_toggle = (
            optional_bool(lambda: self.IsSharedSkillToggleEnabled(slot))
            if 1 <= slot <= 8
            else None
        )
        weapon_ok = optional_bool(
            lambda: self._meets_custom_skill_weapon_requirement(skill_id)
        )
        shared_conditions_ok = optional_bool(
            lambda: self._meets_custom_skill_shared_conditions(skill_id)
        )
        adrenaline_ok = (
            optional_bool(
                lambda: Routines.Checks.Skills.HasEnoughAdrenalineBySlot(slot)
            )
            if 1 <= slot <= 8
            else None
        )
        try:
            effect_present = bool(self.SpiritBuffExists(skill_id))
        except Exception:
            effect_present = None
        try:
            skill_type, _ = GLOBAL_CACHE.Skill.GetType(skill_id)
        except Exception:
            skill_type = None
        try:
            from Py4GWCoreLib.HeroAI.types import SkillType

            is_shout = skill_type == SkillType.Shout.value
        except Exception:
            is_shout = False
        if is_shout:
            try:
                player_id = Player.GetAgentID()
                vocal_minority_id = GLOBAL_CACHE.Skill.GetID("Vocal_Minority")
                well_of_silence_id = GLOBAL_CACHE.Skill.GetID("Well_of_Silence")
                silence_blocked = bool(
                    Routines.Checks.Agents.HasEffect(
                        player_id,
                        vocal_minority_id,
                    )
                    or Routines.Checks.Agents.HasEffect(
                        player_id,
                        well_of_silence_id,
                    )
                )
                silence_ok: bool | None = not silence_blocked
            except Exception:
                silence_blocked = None
                silence_ok = None
        else:
            silence_blocked = None
            silence_ok = None
        try:
            agent_casting = bool(Agent.IsCasting(Player.GetAgentID()))
        except Exception:
            agent_casting = None
        cached_data = getattr(self, "_cached_data", None)
        combat_handler = getattr(cached_data, "combat_handler", None)
        if combat_handler is None:
            casting_routine = None
        else:
            try:
                casting_routine = bool(combat_handler.InCastingRoutine())
            except Exception:
                casting_routine = None
        try:
            energy_fraction = float(Agent.GetEnergy(Player.GetAgentID()))
        except Exception:
            energy_fraction = None
        return {
            "skill": self._diagnostic_skill_label(skill_id),
            "skill_id": skill_id,
            "equipped": snapshot.equipped,
            "slot": slot,
            "castable": snapshot.castable,
            "cast_pending": cast_pending,
            "map_explorable": map_explorable,
            "energy": energy_fraction,
            "energy_cost": snapshot.energy_cost,
            "energy_ok": energy_ok,
            "ready": ready,
            "recharge_s": snapshot.recharge_seconds,
            "silence_blocked": silence_blocked,
            "silence_ok": silence_ok,
            "shared_toggle": shared_toggle,
            "weapon_ok": weapon_ok,
            "shared_conditions_ok": shared_conditions_ok,
            "adrenaline_ok": adrenaline_ok,
            "effect_present": effect_present,
            "agent_casting": agent_casting,
            "casting_routine": casting_routine,
        }

    def _diagnostic_ooc_trace_skill(
        self,
        skill_id: int,
        *,
        stage: str,
        variant: str = "none",
        force: bool = False,
    ) -> dict[str, Any] | None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return None
        if not force and not self._diagnostic_ooc_should_trace_skill(skill_id):
            return None
        try:
            fields = self._diagnostic_ooc_skill_state(skill_id)
            fields.update({"stage": stage, "variant": variant})
            self._diagnostic_log_ooc_state(
                f"skill:{skill_id}:{variant}:{stage}",
                "skill_state",
                fields,
            )
            return fields
        except Exception:
            return None

    def _diagnostic_ooc_trace_target(
        self,
        skill_id: int,
        target_agent_id: int,
        *,
        custom_skill: Any,
        other_ally: bool = False,
        variant: str = "none",
    ) -> None:
        try:
            self._diagnostic_ooc_trace_target_impl(
                skill_id,
                target_agent_id,
                custom_skill=custom_skill,
                other_ally=other_ally,
                variant=variant,
            )
        except Exception:
            return

    def _diagnostic_ooc_trace_target_impl(
        self,
        skill_id: int,
        target_agent_id: int,
        *,
        custom_skill: Any,
        other_ally: bool = False,
        variant: str = "none",
    ) -> None:
        actual_party_ids, _, _ = self._diagnostic_ooc_emergency_members()
        try:
            ally_ids = list(
                Routines.Targeting.GetAllAlliesArray(Range.Spellcast.value) or []
            )
        except Exception:
            ally_ids = []
        try:
            player_position = self._coerce_position(Player.GetXY())
        except Exception:
            player_position = None
        try:
            target_predicate = self._build_custom_skill_target_predicate(
                custom_skill=custom_skill
            )
        except Exception:
            target_predicate = None
        candidate_ids = list(dict.fromkeys(actual_party_ids))
        if target_agent_id and target_agent_id not in candidate_ids:
            candidate_ids.append(target_agent_id)
        rows: list[str] = []
        eligible_count = 0
        target_health: float | None = None
        target_actual_party = False
        for agent_id in candidate_ids:
            actual_party = agent_id in actual_party_ids
            in_pool = agent_id in ally_ids
            try:
                pool_alive = bool(Routines.Checks.Agents.IsAlive(agent_id))
            except Exception:
                pool_alive = None
            try:
                valid = bool(Agent.IsValid(agent_id))
            except Exception:
                valid = None
            try:
                alive = bool(Agent.IsAlive(agent_id))
            except Exception:
                alive = None
            try:
                party_member = bool(Routines.Party.IsPartyMember(agent_id))
            except Exception:
                party_member = None
            try:
                health = float(Agent.GetHealth(agent_id))
            except Exception:
                health = None
            threshold_ok = (
                health is not None
                and math.isfinite(health)
                and health <= OOC_EMERGENCY_HEALTH_THRESHOLD
            )
            try:
                other_ally_ok = not other_ally or agent_id != Player.GetAgentID()
            except Exception:
                other_ally_ok = None
            if custom_skill is None:
                custom_ok = False
            elif target_predicate is None:
                custom_ok = True
            else:
                try:
                    custom_ok = bool(target_predicate(agent_id))
                except Exception:
                    custom_ok = None
            try:
                position = self._coerce_position(Agent.GetXY(agent_id))
            except Exception:
                position = None
            if player_position is None or position is None:
                distance = None
            else:
                try:
                    distance = float(Utils.Distance(player_position, position))
                except Exception:
                    distance = None
            range_ok = (
                distance is not None and distance <= Range.Spellcast.value
            )
            eligible = bool(
                in_pool
                and pool_alive
                and custom_ok
                and valid
                and alive
                and party_member
                and threshold_ok
                and other_ally_ok
            )
            if eligible:
                eligible_count += 1
            if agent_id == target_agent_id:
                target_health = health
                target_actual_party = actual_party
            rows.append(
                ":".join(
                    (
                        str(agent_id),
                        f"actual={self._diagnostic_ooc_value(actual_party)}",
                        f"pool={self._diagnostic_ooc_value(in_pool)}",
                        f"pool_alive={self._diagnostic_ooc_value(pool_alive)}",
                        f"valid={self._diagnostic_ooc_value(valid)}",
                        f"alive={self._diagnostic_ooc_value(alive)}",
                        f"party={self._diagnostic_ooc_value(party_member)}",
                        f"health={self._diagnostic_ooc_value(health)}",
                        f"threshold={self._diagnostic_ooc_value(threshold_ok)}",
                        f"dist={self._diagnostic_ooc_value(distance)}",
                        f"range={self._diagnostic_ooc_value(range_ok)}",
                        f"custom={self._diagnostic_ooc_value(custom_ok)}",
                        f"other={self._diagnostic_ooc_value(other_ally_ok)}",
                        f"eligible={self._diagnostic_ooc_value(eligible)}",
                    )
                )
            )
        self._diagnostic_log_ooc_state(
            f"target:{skill_id}:{variant}",
            "target",
            {
                "stage": "resolved",
                "skill": self._diagnostic_skill_label(skill_id),
                "skill_id": skill_id,
                "variant": variant,
                "target": target_agent_id,
                "target_health": target_health,
                "target_actual_party": target_actual_party,
                "other_ally": other_ally,
                "ally_pool_n": len(ally_ids),
                "eligible_n": eligible_count,
                "members": ";".join(rows) or "none",
            },
        )

    def _diagnostic_ooc_trace_action_result(
        self,
        skill_id: int,
        target_agent_id: int,
        result: Any,
        *,
        variant: str = "none",
    ) -> None:
        accepted = bool(result)
        try:
            post_state = self._diagnostic_ooc_skill_state(skill_id)
        except Exception:
            post_state = {}
        self._diagnostic_log_ooc_state(
            f"action:{skill_id}:{variant}",
            "action_request",
            {
                "stage": "returned",
                "skill": self._diagnostic_skill_label(skill_id),
                "skill_id": skill_id,
                "variant": variant,
                "target": target_agent_id,
                "request_result": accepted,
                "request_accepted": accepted,
                "native_cast_proven": False,
                "healed_proven": False,
                "post_castable": post_state.get("castable"),
                "post_cast_pending": post_state.get("cast_pending"),
                "post_ready": post_state.get("ready"),
                "post_energy_ok": post_state.get("energy_ok"),
                "post_shared_toggle": post_state.get("shared_toggle"),
                "post_weapon_ok": post_state.get("weapon_ok"),
                "post_shared_conditions_ok": post_state.get(
                    "shared_conditions_ok"
                ),
            },
        )

    def _diagnostic_record_rejection(
        self,
        context: _CombatContext,
        agent_id: int,
        skill_id: int,
        reason: str,
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED or not reason:
            return
        try:
            if agent_id not in self._diagnostic_episodes:
                return
            skill_rejections = context.diagnostic_rejections.setdefault(agent_id, {})
            reasons = skill_rejections.setdefault(skill_id, [])
            if reason not in reasons:
                reasons.append(reason)
        except Exception:
            return

    def _diagnostic_log_patient_party_blockers(
        self,
        context: _CombatContext,
        target_agent_id: int,
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            blockers: list[tuple[_PartyMemberSnapshot, str]] = []
            for member in context.party_members:
                if member.agent_id == target_agent_id:
                    continue
                reason = self._patient_party_blocker_reason(member)
                if reason:
                    blockers.append((member, reason))
            if not blockers:
                return

            signature = tuple(
                (
                    member.agent_id,
                    self._diagnostic_quantize(member.health),
                    self._diagnostic_quantize(member.recent_health_drop),
                    member.is_critical,
                    member.is_pressure_target,
                    reason,
                )
                for member, reason in blockers
            )
            tick_ms = context.tick_ms
            previous_signature = getattr(
                self,
                "_diagnostic_last_patient_blocker_signature",
                None,
            )
            previous_tick = int(
                getattr(self, "_diagnostic_last_patient_blocker_tick", 0)
            )
            if (
                previous_signature == (target_agent_id, signature)
                and tick_ms - previous_tick < _DIAGNOSTIC_HEARTBEAT_MS
            ):
                return

            blocker_text = ";".join(
                (
                    f"{member.agent_id}:"
                    f"h={self._diagnostic_format_float(member.health)}:"
                    f"drop={self._diagnostic_format_float(member.recent_health_drop)}:"
                    f"critical={self._diagnostic_flag(member.is_critical)}:"
                    f"pressure={self._diagnostic_flag(member.is_pressure_target)}:"
                    f"reason={reason}"
                )
                for member, reason in blockers
            )
            _diagnostic_log(
                "kind=patient_blocker "
                f"tick={tick_ms} run=combat target={target_agent_id} "
                f"blockers={blocker_text}"
            )
            self._diagnostic_last_patient_blocker_signature = (
                target_agent_id,
                signature,
            )
            self._diagnostic_last_patient_blocker_tick = tick_ms
        except Exception:
            return

    def _diagnostic_record_aux_rejection(
        self,
        context: _CombatContext,
        reason: str,
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED or not reason:
            return
        try:
            if not self._diagnostic_episodes:
                return
            if reason not in context.diagnostic_aux_rejections:
                context.diagnostic_aux_rejections.append(reason)
        except Exception:
            return

    def _diagnostic_skill_state_reasons(
        self,
        context: _CombatContext,
        skill_id: int,
    ) -> tuple[str, ...]:
        """Describe known CanCastSkillID gates without changing the cast path."""
        try:
            skill_state = context.skill_states.get(skill_id)
            if skill_state is None:
                return ("unsupported",)
            if not skill_state.equipped:
                return ("not_equipped",)

            reasons: list[str] = []
            if self._is_local_cast_pending():
                reasons.append("cast_pending")
            try:
                if not Routines.Checks.Map.IsExplorable():
                    reasons.append("map_unavailable")
            except Exception:
                pass
            try:
                if not Routines.Checks.Skills.HasEnoughEnergy(
                    Player.GetAgentID(),
                    skill_id,
                ):
                    reasons.append("insufficient_energy")
            except Exception:
                if context.current_energy + 1e-6 < skill_state.energy_cost:
                    reasons.append("insufficient_energy")
            try:
                if not Routines.Checks.Skills.IsSkillIDReady(skill_id):
                    reasons.append("recharge")
            except Exception:
                pass

            try:
                slot = int(SkillBar.GetSlotBySkillID(skill_id))
            except Exception:
                slot = 0
            if not 1 <= slot <= 8:
                reasons.append("not_slotted")
            else:
                try:
                    if not self.IsSharedSkillToggleEnabled(slot):
                        reasons.append("toggle_off")
                except Exception:
                    pass
                try:
                    if not self._meets_custom_skill_weapon_requirement(skill_id):
                        reasons.append("weapon_requirement")
                except Exception:
                    pass
                try:
                    if not self._meets_custom_skill_shared_conditions(skill_id):
                        reasons.append("shared_condition")
                except Exception:
                    pass
                try:
                    if not Routines.Checks.Skills.HasEnoughAdrenalineBySlot(slot):
                        reasons.append("insufficient_adrenaline")
                except Exception:
                    pass
            try:
                if self.SpiritBuffExists(skill_id):
                    reasons.append("skill_effect_present")
            except Exception:
                pass

            if not skill_state.castable and not reasons:
                reasons.append("not_castable")
            return tuple(dict.fromkeys(reasons))
        except Exception:
            return ("castability_unknown",)

    def _diagnostic_record_skill_state_rejection(
        self,
        context: _CombatContext,
        skill_id: int,
        target_ids: tuple[int, ...],
    ) -> bool:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return False
        try:
            if not target_ids:
                return False
            skill_state = context.skill_states.get(skill_id)
            if skill_state is not None and skill_state.castable:
                return False
            reasons = self._diagnostic_skill_state_reasons(context, skill_id)
            for agent_id in target_ids:
                for reason in reasons:
                    self._diagnostic_record_rejection(
                        context,
                        agent_id,
                        skill_id,
                        reason,
                    )
            return True
        except Exception:
            return False

    def _diagnostic_target_ids(self, context: _CombatContext) -> tuple[int, ...]:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return ()
        try:
            return tuple(sorted(self._diagnostic_episodes))
        except Exception:
            return ()

    def _diagnostic_effect_rejection(
        self,
        context: _CombatContext,
        agent_id: int,
        skill_id: int,
    ) -> str:
        if agent_id == context.player_id or agent_id not in context.party_player_ids:
            return (
                "effect_present"
                if self._has_effect_cached(context, agent_id, skill_id)
                else ""
            )
        snapshot = context.shared_effect_snapshots.get(agent_id)
        if snapshot is None or not snapshot.exact_effects_available:
            return "effect_state_unknown"
        if not self._is_shared_effect_snapshot_fresh(context.tick_ms, snapshot):
            return "effect_state_stale"
        return "effect_present" if skill_id in snapshot.effect_ids else ""

    @staticmethod
    def _patient_party_blocker_reason(
        member: _PartyMemberSnapshot,
    ) -> str:
        if not member.valid or not member.alive:
            return ""
        if member.is_critical:
            return "critical"
        if (
            member.health <= _PATIENT_SAFE_HEALTH_FLOOR
            and member.health_is_falling
        ):
            return "low_and_falling"
        return ""

    @classmethod
    def _patient_party_emergency_ids(
        cls,
        context: _CombatContext,
    ) -> frozenset[int]:
        return frozenset(
            member.agent_id
            for member in context.party_members
            if cls._patient_party_blocker_reason(member)
        )

    @classmethod
    def _patient_safety_rejection(
        cls,
        context: _CombatContext,
        target: _PartyMemberSnapshot,
        delayed_heal_hp: float = 0.0,
    ) -> str:
        if target.is_critical:
            return "critical_target"
        if target.health > _PATIENT_HEALTH_CEILING:
            return "health_threshold"
        maximum_health = max(0.0, float(target.maximum_health))
        missing_hp = max(0.0, float(target.missing_hp))
        if maximum_health <= 0.0:
            return "trivial_missing_health"
        minimum_missing_hp = maximum_health * _PATIENT_MIN_MISSING_FRACTION
        if math.isfinite(delayed_heal_hp) and delayed_heal_hp > 0.0:
            minimum_missing_hp = max(
                minimum_missing_hp,
                delayed_heal_hp * _PATIENT_DELAYED_HEAL_FRACTION,
            )
        if missing_hp < minimum_missing_hp:
            return "trivial_missing_health"
        if target.health <= _PATIENT_SAFE_HEALTH_FLOOR:
            return "delay_unsafe"
        if target.recent_health_drop >= _PATIENT_SAFE_DROP_LIMIT:
            return "rapid_drop"
        if any(
            member.agent_id != target.agent_id
            and cls._patient_party_blocker_reason(member)
            for member in context.party_members
        ):
            return "party_emergency"
        return ""

    @staticmethod
    def _seed_spike_rejection(
        context: _CombatContext,
        target: _PartyMemberSnapshot,
        *,
        nearby_enemy_count: int | None = None,
    ) -> str:
        if target.is_self:
            return "self_not_legal"
        if target.is_critical:
            return "critical_direct_rescue"
        if any(agent_id != target.agent_id for agent_id in context.critical_ids):
            return "party_emergency"
        if target.health > _SEED_HEALTH_CEILING:
            return "health_threshold"
        if target.recent_health_drop < _SEED_MIN_DROP:
            return "insufficient_pressure"
        if target.health_is_recovering:
            return "spike_recovered"
        active_nearby_enemy_count = (
            context.nearby_enemy_count
            if nearby_enemy_count is None
            else nearby_enemy_count
        )
        if not target.health_is_falling and not (
            target.recent_health_drop >= _SEED_LARGE_DROP
            and (active_nearby_enemy_count > 0 or len(context.pressure_ids) > 1)
        ):
            return "spike_not_continuing"
        return ""

    @staticmethod
    def _diagnostic_flag(value: bool | None) -> str:
        if value is None:
            return "?"
        return "1" if value else "0"

    @staticmethod
    def _diagnostic_format_float(value: float | None, digits: int = 3) -> str:
        if value is None:
            return "na"
        try:
            numeric_value = float(value)
        except Exception:
            return "na"
        if math.isnan(numeric_value):
            return "nan"
        if math.isinf(numeric_value):
            return "inf" if numeric_value > 0 else "-inf"
        return f"{numeric_value:.{digits}f}"

    @staticmethod
    def _diagnostic_quantize(value: float | None) -> float | str | None:
        if value is None:
            return None
        try:
            numeric_value = float(value)
        except Exception:
            return None
        if math.isnan(numeric_value):
            return "nan"
        if math.isinf(numeric_value):
            return "inf" if numeric_value > 0 else "-inf"
        return round(numeric_value, 2)

    @staticmethod
    def _diagnostic_distance_bucket(value: float | None) -> int | str | None:
        if value is None:
            return None
        try:
            numeric_value = float(value)
        except Exception:
            return None
        if not math.isfinite(numeric_value):
            return "inf"
        return int(numeric_value // 50.0)

    @staticmethod
    def _diagnostic_age_bucket(value: int | None) -> str:
        if value is None:
            return "na"
        if value <= 150:
            return "fresh"
        if value <= 500:
            return "recent"
        if value <= 1000:
            return "old"
        return "stale"

    @staticmethod
    def _diagnostic_safe_label(value: Any) -> str:
        try:
            text = str(value)
        except Exception:
            return "unknown"
        cleaned = "".join(
            character if character.isalnum() or character in "_-.:" else "_"
            for character in text
        )
        return cleaned or "unknown"

    @staticmethod
    def _diagnostic_tick() -> int:
        try:
            return int(PySystem.get_tick_count64())
        except Exception:
            return 0

    def _diagnostic_runtime_state(
        self,
    ) -> tuple[bool | None, bool | None, bool | None, int]:
        try:
            in_aggro: bool | None = bool(self.IsInAggro())
        except Exception:
            in_aggro = None
        try:
            player_id = int(Player.GetAgentID() or 0)
        except Exception:
            player_id = 0
        try:
            local_casting: bool | None = (
                bool(Agent.IsCasting(player_id)) if player_id else None
            )
        except Exception:
            local_casting = None
        try:
            local_cast_timer = getattr(self, "_local_cast_timer", None)
            cast_pending = (
                None
                if local_cast_timer is None
                else bool(
                    not local_cast_timer.IsStopped()
                    and not local_cast_timer.IsExpired()
                )
            )
        except Exception:
            cast_pending = None
        try:
            build_target = int(getattr(self, "current_target_id", 0) or 0)
        except Exception:
            build_target = 0
        return in_aggro, local_casting, cast_pending, build_target

    @staticmethod
    def _diagnostic_shared_health(account: Any) -> float | None:
        if account is None:
            return None
        try:
            return float(getattr(getattr(account, "AgentData"), "Health").Current)
        except Exception:
            return None

    @staticmethod
    def _diagnostic_shared_age(tick_ms: int, account: Any) -> int | None:
        if account is None:
            return None
        try:
            last_updated = int(getattr(account, "LastUpdated", 0) or 0)
        except Exception:
            return None
        if last_updated <= 0:
            return None
        return max(0, int(tick_ms) - last_updated)

    def _diagnostic_observation_from_values(
        self,
        agent_id: int,
        *,
        present: bool,
        valid: bool,
        alive: bool,
        is_remote: bool,
        health: float | None,
        native_health: float | None,
        shared_account: Any,
        tick_ms: int,
        maximum_health: float | None,
        missing_hp: float | None,
        position_available: bool,
        distance_from_player: float | None,
        recent_health_drop: float,
    ) -> _DiagnosticMemberObservation:
        if health is None or not math.isfinite(health):
            is_critical: bool | None = None
            is_injured: bool | None = None
        else:
            is_critical = health <= COMBAT_CRITICAL_HEALTH_THRESHOLD
            is_injured = health < 1.0
        try:
            normalized_drop = max(0.0, min(1.0, float(recent_health_drop)))
        except Exception:
            normalized_drop = 0.0
        return _DiagnosticMemberObservation(
            agent_id=agent_id,
            present=present,
            valid=valid,
            alive=alive,
            is_remote=is_remote,
            health=health,
            native_health=native_health,
            shared_health=self._diagnostic_shared_health(shared_account),
            shared_found=shared_account is not None,
            shared_age_ms=self._diagnostic_shared_age(tick_ms, shared_account),
            maximum_health=maximum_health,
            missing_hp=missing_hp,
            position_available=position_available,
            distance_from_player=distance_from_player,
            recent_health_drop=normalized_drop,
            is_critical=is_critical,
            is_pressure=(normalized_drop >= COMBAT_PRESSURE_DROP_THRESHOLD),
            is_injured=is_injured,
        )

    def _diagnostic_recent_drop(
        self,
        agent_id: int,
        health_monitor: dict[int, dict[str, float]] | None = None,
    ) -> float:
        try:
            if health_monitor is not None and agent_id in health_monitor:
                return float(health_monitor[agent_id].get("drop", 0.0) or 0.0)
        except Exception:
            pass
        try:
            return float(self.GetPartyHealthDelta(agent_id))
        except Exception:
            return 0.0

    def _diagnostic_collect_member(
        self,
        agent_id: int,
        *,
        player_id: int,
        player_position: tuple[float, float] | None,
        party_player_ids: frozenset[int] | set[int],
        shared_accounts: dict[int, Any],
        tick_ms: int,
    ) -> _DiagnosticMemberObservation:
        try:
            is_valid = bool(Agent.IsValid(agent_id))
            is_alive = is_valid and bool(Routines.Checks.Agents.IsAlive(agent_id))
        except Exception:
            is_valid = False
            is_alive = False

        try:
            raw_health = float(Routines.Checks.Agents.GetHealth(agent_id))
            health = raw_health
        except Exception:
            health = None
        try:
            native_health = float(Agent.GetHealth(agent_id))
        except Exception:
            native_health = None
        try:
            native_maximum_health = float(Agent.GetMaxHealth(agent_id) or 0.0)
        except Exception:
            native_maximum_health = None
        if native_maximum_health is None or not math.isfinite(native_maximum_health):
            context_maximum_health = 0.0
        else:
            context_maximum_health = max(0.0, native_maximum_health)

        try:
            position = self._coerce_position(Agent.GetXY(agent_id))
        except Exception:
            position = None
        if player_position is None or position is None:
            distance_from_player = float("inf")
        else:
            try:
                distance_from_player = float(Utils.Distance(player_position, position))
            except Exception:
                distance_from_player = float("inf")

        if (
            health is not None
            and math.isfinite(health)
            and context_maximum_health > 0.0
        ):
            missing_hp = context_maximum_health * max(0.0, 1.0 - health)
        elif context_maximum_health == 0.0 and native_maximum_health is not None:
            missing_hp = 0.0
        else:
            missing_hp = None

        return self._diagnostic_observation_from_values(
            agent_id,
            present=True,
            valid=is_valid,
            alive=is_alive,
            is_remote=agent_id in party_player_ids and agent_id != player_id,
            health=health,
            native_health=native_health,
            shared_account=shared_accounts.get(agent_id),
            tick_ms=tick_ms,
            maximum_health=native_maximum_health,
            missing_hp=missing_hp,
            position_available=position is not None,
            distance_from_player=distance_from_player,
            recent_health_drop=self._diagnostic_recent_drop(agent_id),
        )

    def _diagnostic_note_callback(self, run: str) -> int:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return 0
        tick_ms = self._diagnostic_tick()
        try:
            previous_tick = self._diagnostic_last_callback_tick
            previous_run = self._diagnostic_last_callback_run or "unknown"
            if (
                self._diagnostic_episodes
                and previous_tick is not None
                and tick_ms > previous_tick
                and tick_ms - previous_tick >= _DIAGNOSTIC_CALLBACK_GAP_MS
            ):
                active_ids = ",".join(
                    str(agent_id) for agent_id in sorted(self._diagnostic_episodes)
                )
                _diagnostic_log(
                    "kind=callback_gap "
                    f"tick={tick_ms} prev_tick={previous_tick} "
                    f"gap_ms={tick_ms - previous_tick} last_run={previous_run} "
                    f"run={run} danger={active_ids or 'none'}"
                )
            self._diagnostic_last_callback_tick = tick_ms
            self._diagnostic_last_callback_run = run
        except Exception:
            try:
                self._diagnostic_last_callback_tick = tick_ms
                self._diagnostic_last_callback_run = run
            except Exception:
                pass
        return tick_ms

    def _diagnostic_probe_ooc(self, tick_ms: int) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            previous_probe_tick = self._diagnostic_last_ooc_probe_tick
            if (
                previous_probe_tick is not None
                and tick_ms > previous_probe_tick
                and tick_ms - previous_probe_tick < _DIAGNOSTIC_OOC_PROBE_INTERVAL_MS
            ):
                return
            self._diagnostic_last_ooc_probe_tick = tick_ms

            actual_party_ids = self._get_actual_party_ids()
            party_player_ids = frozenset(self._get_current_party_player_ids())
            shared_accounts = self._get_same_party_shared_accounts(
                set(actual_party_ids)
            )
            try:
                player_id = int(Player.GetAgentID() or 0)
            except Exception:
                player_id = 0
            try:
                player_position = self._coerce_position(Player.GetXY())
            except Exception:
                player_position = None
            observations = [
                self._diagnostic_collect_member(
                    agent_id,
                    player_id=player_id,
                    player_position=player_position,
                    party_player_ids=party_player_ids,
                    shared_accounts=shared_accounts,
                    tick_ms=tick_ms,
                )
                for agent_id in actual_party_ids
            ]
            self._diagnostic_ooc_actual_party_ids = tuple(actual_party_ids)
            self._diagnostic_ooc_probe_observations = tuple(observations)
            self._diagnostic_ooc_active_ids = tuple(
                observation.agent_id
                for observation in observations
                if (
                    observation.present
                    and observation.valid
                    and observation.alive
                    and observation.native_health is not None
                    and math.isfinite(observation.native_health)
                    and observation.native_health <= OOC_EMERGENCY_HEALTH_THRESHOLD
                )
            )
            self._diagnostic_trace_observations(
                run="ooc",
                tick_ms=tick_ms,
                actual_party_ids=actual_party_ids,
                observations=observations,
                player_position=player_position,
            )
        except Exception:
            return

    @staticmethod
    def _diagnostic_health_is_low(value: float | None) -> bool:
        return (
            value is not None
            and math.isfinite(value)
            and value <= _DIAGNOSTIC_HEALTH_THRESHOLD
        )

    def _diagnostic_member_signature(
        self,
        *,
        run: str,
        state: str,
        observation: _DiagnosticMemberObservation,
        in_aggro: bool | None,
        local_casting: bool | None,
        cast_pending: bool | None,
        build_target: int,
    ) -> tuple[Any, ...]:
        return (
            run,
            state,
            self._diagnostic_flag(in_aggro),
            self._diagnostic_flag(local_casting),
            self._diagnostic_flag(cast_pending),
            build_target,
            observation.present,
            observation.valid,
            observation.alive,
            observation.is_remote,
            self._diagnostic_quantize(observation.health),
            self._diagnostic_quantize(observation.native_health),
            self._diagnostic_quantize(observation.shared_health),
            observation.shared_found,
            self._diagnostic_age_bucket(observation.shared_age_ms),
            self._diagnostic_quantize(observation.maximum_health),
            self._diagnostic_quantize(observation.missing_hp),
            observation.position_available,
            self._diagnostic_distance_bucket(observation.distance_from_player),
            self._diagnostic_quantize(observation.recent_health_drop),
            observation.is_critical,
            observation.is_pressure,
            observation.is_injured,
        )

    def _diagnostic_log_member_observation(
        self,
        *,
        run: str,
        state: str,
        tick_ms: int,
        actual_count: int,
        episode: _DiagnosticEpisode,
        observation: _DiagnosticMemberObservation,
        player_position: tuple[float, float] | None,
        in_aggro: bool | None,
        local_casting: bool | None,
        cast_pending: bool | None,
        build_target: int,
    ) -> None:
        shared_age = (
            "na"
            if observation.shared_age_ms is None
            else str(observation.shared_age_ms)
        )
        episode_age = max(0, tick_ms - episode.started_tick)
        _diagnostic_log(
            "kind=episode "
            f"tick={tick_ms} run={run} state={state} "
            f"episode_tick={episode.started_tick} episode_age_ms={episode_age} "
            f"actual_n={actual_count} agent={observation.agent_id} "
            f"remote={self._diagnostic_flag(observation.is_remote)} "
            f"present={self._diagnostic_flag(observation.present)} "
            f"valid={self._diagnostic_flag(observation.valid)} "
            f"alive={self._diagnostic_flag(observation.alive)} "
            f"check_h={self._diagnostic_format_float(observation.health)} "
            f"native_h={self._diagnostic_format_float(observation.native_health)} "
            f"shared_h={self._diagnostic_format_float(observation.shared_health)} "
            f"shared_found={self._diagnostic_flag(observation.shared_found)} "
            f"shared_age_ms={shared_age} "
            f"max_hp={self._diagnostic_format_float(observation.maximum_health, 1)} "
            f"missing_hp={self._diagnostic_format_float(observation.missing_hp, 1)} "
            f"monk_pos={self._diagnostic_flag(player_position is not None)} "
            f"pos={self._diagnostic_flag(observation.position_available)} "
            f"dist={self._diagnostic_format_float(observation.distance_from_player, 1)} "
            f"drop={self._diagnostic_format_float(observation.recent_health_drop)} "
            f"inj={self._diagnostic_flag(observation.is_injured)} "
            f"pressure={self._diagnostic_flag(observation.is_pressure)} "
            f"critical={self._diagnostic_flag(observation.is_critical)} "
            f"aggro={self._diagnostic_flag(in_aggro)} "
            f"monk_cast={self._diagnostic_flag(local_casting)} "
            f"cast_pending={self._diagnostic_flag(cast_pending)} "
            f"build_target={build_target}"
        )

    def _diagnostic_trace_observations(
        self,
        *,
        run: str,
        tick_ms: int,
        actual_party_ids: list[int],
        observations: list[_DiagnosticMemberObservation],
        player_position: tuple[float, float] | None,
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            observations_by_id = {
                observation.agent_id: observation for observation in observations
            }
            in_aggro, local_casting, cast_pending, build_target = (
                self._diagnostic_runtime_state()
            )
            actual_count = len(actual_party_ids)
            for observation in observations:
                if run == "ooc":
                    danger_detected = bool(
                        observation.valid
                        and observation.alive
                        and observation.native_health is not None
                        and math.isfinite(observation.native_health)
                        and observation.native_health
                        <= OOC_EMERGENCY_HEALTH_THRESHOLD
                    )
                else:
                    health_values = (
                        observation.health,
                        observation.native_health,
                        observation.shared_health,
                    )
                    danger_detected = (
                        any(
                            self._diagnostic_health_is_low(value)
                            for value in health_values
                        )
                        or observation.recent_health_drop
                        >= COMBAT_PRESSURE_DROP_THRESHOLD
                    )
                episode = self._diagnostic_episodes.get(observation.agent_id)
                if episode is None:
                    if (
                        not observation.present
                        or not observation.alive
                        or not danger_detected
                    ):
                        continue
                    episode = _DiagnosticEpisode(
                        started_tick=tick_ms,
                        last_logged_tick=0,
                        is_remote=observation.is_remote,
                    )
                    self._diagnostic_episodes[observation.agent_id] = episode
                    state = "start"
                elif not observation.present:
                    state = "missing"
                elif not observation.valid:
                    state = "invalid"
                elif not observation.alive:
                    state = "dead"
                elif not danger_detected:
                    state = "recover"
                elif observation.health is None:
                    state = "health_unavailable"
                else:
                    state = "danger"

                if state in {"recover", "dead"}:
                    self._diagnostic_log_member_observation(
                        run=run,
                        state=state,
                        tick_ms=tick_ms,
                        actual_count=actual_count,
                        episode=episode,
                        observation=observation,
                        player_position=player_position,
                        in_aggro=in_aggro,
                        local_casting=local_casting,
                        cast_pending=cast_pending,
                        build_target=build_target,
                    )
                    self._diagnostic_episodes.pop(observation.agent_id, None)
                    continue

                signature = self._diagnostic_member_signature(
                    run=run,
                    state=state,
                    observation=observation,
                    in_aggro=in_aggro,
                    local_casting=local_casting,
                    cast_pending=cast_pending,
                    build_target=build_target,
                )
                heartbeat_due = (
                    episode.last_logged_tick == 0
                    or tick_ms - episode.last_logged_tick >= _DIAGNOSTIC_HEARTBEAT_MS
                )
                if (
                    episode.last_signature != signature
                    or heartbeat_due
                    or state == "start"
                ):
                    self._diagnostic_log_member_observation(
                        run=run,
                        state=state,
                        tick_ms=tick_ms,
                        actual_count=actual_count,
                        episode=episode,
                        observation=observation,
                        player_position=player_position,
                        in_aggro=in_aggro,
                        local_casting=local_casting,
                        cast_pending=cast_pending,
                        build_target=build_target,
                    )
                    episode.last_signature = signature
                    episode.last_logged_tick = tick_ms

            for agent_id, episode in list(self._diagnostic_episodes.items()):
                if agent_id in observations_by_id:
                    continue
                missing_observation = _DiagnosticMemberObservation(
                    agent_id=agent_id,
                    present=False,
                    valid=False,
                    alive=False,
                    is_remote=episode.is_remote,
                    health=None,
                    native_health=None,
                    shared_health=None,
                    shared_found=False,
                    shared_age_ms=None,
                    maximum_health=None,
                    missing_hp=None,
                    position_available=False,
                    distance_from_player=None,
                    recent_health_drop=0.0,
                    is_critical=None,
                    is_pressure=None,
                    is_injured=None,
                )
                signature = self._diagnostic_member_signature(
                    run=run,
                    state="missing",
                    observation=missing_observation,
                    in_aggro=in_aggro,
                    local_casting=local_casting,
                    cast_pending=cast_pending,
                    build_target=build_target,
                )
                heartbeat_due = (
                    episode.last_logged_tick == 0
                    or tick_ms - episode.last_logged_tick >= _DIAGNOSTIC_HEARTBEAT_MS
                )
                if episode.last_signature != signature or heartbeat_due:
                    self._diagnostic_log_member_observation(
                        run=run,
                        state="missing",
                        tick_ms=tick_ms,
                        actual_count=actual_count,
                        episode=episode,
                        observation=missing_observation,
                        player_position=player_position,
                        in_aggro=in_aggro,
                        local_casting=local_casting,
                        cast_pending=cast_pending,
                        build_target=build_target,
                    )
                    episode.last_signature = signature
                    episode.last_logged_tick = tick_ms

            if not self._diagnostic_episodes:
                self._diagnostic_last_aux_candidate_tick = 0
                self._diagnostic_last_aux_candidate_signature = None
                self._diagnostic_last_decision_tick = 0
                self._diagnostic_last_decision_signature = None
                self._diagnostic_last_high_cure_tick = 0
                self._diagnostic_last_high_cure_signature = None
                self._diagnostic_revalidation_state.clear()
        except Exception:
            return

    def _diagnostic_skill_label(self, skill_id: int) -> str:
        try:
            skill_name = GLOBAL_CACHE.Skill.GetName(skill_id)
        except Exception:
            skill_name = ""
        return self._diagnostic_safe_label(skill_name or skill_id)

    def _diagnostic_candidate_label(self, candidate: _CombatActionCandidate) -> str:
        urgency_name = self._diagnostic_safe_label(
            getattr(candidate.urgency, "name", candidate.urgency)
        )
        return (
            f"{self._diagnostic_skill_label(candidate.skill_id)}"
            f"/{candidate.skill_id}@{candidate.target_agent_id}"
            f":u={urgency_name}:{int(candidate.urgency)}"
            f":life={self._diagnostic_flag(candidate.preempts_high_cure)}"
        )

    @staticmethod
    def _diagnostic_candidate_signature(
        candidate: _CombatActionCandidate,
    ) -> tuple[Any, ...]:
        return (
            candidate.skill_id,
            candidate.target_agent_id,
            int(candidate.urgency),
            round(float(candidate.primary_value), 2),
            round(float(candidate.secondary_value), 2),
            round(float(candidate.time_to_primary_effect), 2),
            round(float(candidate.energy_spend_fraction), 2),
            candidate.preempts_high_cure,
        )

    def _diagnostic_candidate_is_relevant(
        self,
        candidate: _CombatActionCandidate,
    ) -> bool:
        return bool(self._diagnostic_episodes) and (
            candidate.target_agent_id in self._diagnostic_episodes
            or candidate.skill_id == AEGIS_ID
        )

    def _diagnostic_rejection_label(
        self,
        context: _CombatContext,
        agent_id: int,
    ) -> str:
        skill_rejections = context.diagnostic_rejections.get(agent_id, {})
        labels: list[str] = []
        for skill_id in _DIAGNOSTIC_RELEVANT_SKILLS:
            reasons = skill_rejections.get(skill_id)
            if not reasons:
                continue
            labels.append(
                f"{self._diagnostic_skill_label(skill_id)}[{','.join(reasons)}]"
            )
        return ";".join(labels)

    @staticmethod
    def _diagnostic_rejection_signature(
        context: _CombatContext,
        agent_id: int,
    ) -> tuple[Any, ...]:
        skill_rejections = context.diagnostic_rejections.get(agent_id, {})
        return tuple(
            (skill_id, tuple(skill_rejections.get(skill_id, ())))
            for skill_id in _DIAGNOSTIC_RELEVANT_SKILLS
        )

    def _diagnostic_trace_candidates(
        self,
        context: _CombatContext,
        candidates: list[_CombatActionCandidate],
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            if not self._diagnostic_episodes:
                return
            tick_ms = context.tick_ms
            for agent_id, episode in list(self._diagnostic_episodes.items()):
                if agent_id not in context.party_by_id:
                    for skill_id in _DIAGNOSTIC_RELEVANT_SKILLS:
                        self._diagnostic_record_rejection(
                            context,
                            agent_id,
                            skill_id,
                            "invalid_or_dead",
                        )
                target_candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.target_agent_id == agent_id
                ]
                candidate_signature = tuple(
                    self._diagnostic_candidate_signature(candidate)
                    for candidate in target_candidates
                )
                rejection_signature = self._diagnostic_rejection_signature(
                    context,
                    agent_id,
                )
                signature = (candidate_signature, rejection_signature)
                heartbeat_due = (
                    episode.last_candidate_tick == 0
                    or tick_ms - episode.last_candidate_tick >= _DIAGNOSTIC_HEARTBEAT_MS
                )
                if episode.last_candidate_signature != signature or heartbeat_due:
                    labels = ";".join(
                        self._diagnostic_candidate_label(candidate)
                        for candidate in target_candidates
                    )
                    _diagnostic_log(
                        "kind=candidates "
                        f"tick={tick_ms} run=combat agent={agent_id} "
                        f"skills={labels or 'none'} "
                        f"rejected={self._diagnostic_rejection_label(context, agent_id) or 'none'}"
                    )
                    episode.last_candidate_signature = signature
                    episode.last_candidate_tick = tick_ms

            auxiliary_candidates = [
                candidate for candidate in candidates if candidate.skill_id == AEGIS_ID
            ]
            auxiliary_signature = tuple(
                self._diagnostic_candidate_signature(candidate)
                for candidate in auxiliary_candidates
            )
            auxiliary_rejections = tuple(context.diagnostic_aux_rejections)
            auxiliary_state_signature = (auxiliary_signature, auxiliary_rejections)
            auxiliary_heartbeat_due = (
                self._diagnostic_last_aux_candidate_tick == 0
                or tick_ms - self._diagnostic_last_aux_candidate_tick
                >= _DIAGNOSTIC_HEARTBEAT_MS
            )
            if (
                auxiliary_state_signature != ((), ())
                or self._diagnostic_last_aux_candidate_signature is not None
            ) and (
                self._diagnostic_last_aux_candidate_signature
                != auxiliary_state_signature
                or auxiliary_heartbeat_due
            ):
                labels = ";".join(
                    self._diagnostic_candidate_label(candidate)
                    for candidate in auxiliary_candidates
                )
                _diagnostic_log(
                    "kind=aux_candidates "
                    f"tick={tick_ms} run=combat skills={labels or 'none'} "
                    f"rejected={','.join(auxiliary_rejections) or 'none'}"
                )
                self._diagnostic_last_aux_candidate_signature = (
                    auxiliary_state_signature
                )
                self._diagnostic_last_aux_candidate_tick = tick_ms
        except Exception:
            return

    def _diagnostic_log_revalidation(
        self,
        candidate: _CombatActionCandidate,
        *,
        stage: str,
        result: bool,
        tick_ms: int | None = None,
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            if not self._diagnostic_candidate_is_relevant(candidate):
                return
            current_tick = self._diagnostic_tick() if tick_ms is None else tick_ms
            state_key = (candidate.skill_id, candidate.target_agent_id, stage)
            previous_state = self._diagnostic_revalidation_state.get(state_key)
            result_value = bool(result)
            heartbeat_due = (
                previous_state is None
                or current_tick - previous_state[1] >= _DIAGNOSTIC_HEARTBEAT_MS
            )
            if (
                previous_state is not None
                and previous_state[0] == result_value
                and not heartbeat_due
            ):
                return
            _diagnostic_log(
                "kind=revalidate "
                f"tick={current_tick} run=combat stage={stage} "
                f"skill={self._diagnostic_skill_label(candidate.skill_id)} "
                f"skill_id={candidate.skill_id} target={candidate.target_agent_id} "
                f"urgency={self._diagnostic_safe_label(getattr(candidate.urgency, 'name', candidate.urgency))} "
                f"lifesaving={self._diagnostic_flag(candidate.preempts_high_cure)} "
                f"result={self._diagnostic_flag(result_value)}"
            )
            self._diagnostic_revalidation_state[state_key] = (
                result_value,
                current_tick,
            )
        except Exception:
            return

    def _diagnostic_log_decision(
        self,
        context: _CombatContext,
        *,
        branch: str,
        selected: _CombatActionCandidate | None,
        skipped: str = "none",
        rescue_pool: int = 0,
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            if not self._diagnostic_episodes:
                return
            _, local_casting, cast_pending, _ = self._diagnostic_runtime_state()
            selected_label = (
                self._diagnostic_candidate_label(selected)
                if selected is not None
                else "none"
            )
            selected_target = selected.target_agent_id if selected is not None else 0
            danger_ids = ",".join(
                str(agent_id) for agent_id in sorted(self._diagnostic_episodes)
            )
            signature = (
                branch,
                danger_ids,
                rescue_pool,
                selected_label,
                selected_target,
                self._diagnostic_flag(local_casting),
                self._diagnostic_flag(cast_pending),
                self._diagnostic_safe_label(skipped),
            )
            if (
                self._diagnostic_last_decision_signature == signature
                and context.tick_ms - self._diagnostic_last_decision_tick
                < _DIAGNOSTIC_HEARTBEAT_MS
            ):
                return
            _diagnostic_log(
                "kind=decision "
                f"tick={context.tick_ms} run=combat branch={branch} "
                f"danger={danger_ids or 'none'} rescue_pool={rescue_pool} "
                f"selected={selected_label} selected_target={selected_target} "
                f"monk_cast={self._diagnostic_flag(local_casting)} "
                f"cast_pending={self._diagnostic_flag(cast_pending)} "
                f"skipped={self._diagnostic_safe_label(skipped)}"
            )
            self._diagnostic_last_decision_signature = signature
            self._diagnostic_last_decision_tick = context.tick_ms
        except Exception:
            return

    def _diagnostic_log_high_cure(
        self,
        context: _CombatContext,
        *,
        attempted: bool,
        result: bool | None,
        skipped: str = "none",
    ) -> None:
        if not _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED:
            return
        try:
            if not self._diagnostic_episodes:
                return
            result_text = "na" if result is None else self._diagnostic_flag(result)
            danger_ids = ",".join(
                str(agent_id) for agent_id in sorted(self._diagnostic_episodes)
            )
            signature = (
                danger_ids,
                attempted,
                result_text,
                self._diagnostic_safe_label(skipped),
            )
            if (
                self._diagnostic_last_high_cure_signature == signature
                and context.tick_ms - self._diagnostic_last_high_cure_tick
                < _DIAGNOSTIC_HEARTBEAT_MS
            ):
                return
            _diagnostic_log(
                "kind=high_cure "
                f"tick={context.tick_ms} run=combat "
                f"attempt={self._diagnostic_flag(attempted)} result={result_text} "
                f"skipped={self._diagnostic_safe_label(skipped)}"
            )
            self._diagnostic_last_high_cure_signature = signature
            self._diagnostic_last_high_cure_tick = context.tick_ms
        except Exception:
            return

    def _health_threshold(self, skill_id: int, default: float) -> float:
        custom_skill = self.GetCustomSkill(skill_id)
        if custom_skill is None:
            return default

        threshold = float(custom_skill.Conditions.LessLife or default)
        return max(0.0, min(1.0, threshold))

    def _resolve_injured_target(
        self,
        skill_id: int,
        *,
        other_ally: bool = False,
        prefer_active_target: bool = False,
        health_threshold_override: float | None = None,
        require_valid: bool = False,
        require_party_member: bool = False,
    ) -> int:
        if not self._is_castable(skill_id):
            return 0

        custom_skill = self.GetCustomSkill(skill_id)
        if custom_skill is None:
            return 0

        health_threshold = (
            self._health_threshold(skill_id, 0.80)
            if health_threshold_override is None
            else health_threshold_override
        )
        player_id = Player.GetAgentID()

        def is_valid_target(agent_id: int) -> bool:
            if (
                (require_valid and not Agent.IsValid(agent_id))
                or not Agent.IsAlive(agent_id)
                or (require_party_member and not Routines.Party.IsPartyMember(agent_id))
                or Agent.GetHealth(agent_id) > health_threshold
            ):
                return False
            return not other_ally or agent_id != player_id

        def rank_target(agent_id: int) -> tuple[float, int, float]:
            active_priority = 1
            if prefer_active_target and (
                Routines.Checks.Agents.IsAttacking(agent_id)
                or Agent.IsCasting(agent_id)
            ):
                active_priority = 0
            return (
                Agent.GetHealth(agent_id),
                active_priority,
                -self.GetPartyHealthDelta(agent_id),
            )

        return self.ResolveRankedPartyAllyTarget(
            skill_id,
            custom_skill,
            validator=is_valid_target,
            rank_key=rank_target,
        )

    def _is_valid_ooc_emergency_target(
        self,
        agent_id: int,
        *,
        other_ally: bool = False,
    ) -> bool:
        return (
            Agent.IsValid(agent_id)
            and Agent.IsAlive(agent_id)
            and Routines.Party.IsPartyMember(agent_id)
            and Agent.GetHealth(agent_id) <= OOC_EMERGENCY_HEALTH_THRESHOLD
            and (not other_ally or agent_id != Player.GetAgentID())
        )

    def _resolve_ooc_emergency_direct_target(
        self,
        skill_id: int,
        *,
        other_ally: bool = False,
        prefer_active_target: bool = False,
    ) -> int:
        return self._resolve_injured_target(
            skill_id,
            other_ally=other_ally,
            prefer_active_target=prefer_active_target,
            health_threshold_override=OOC_EMERGENCY_HEALTH_THRESHOLD,
            require_valid=True,
            require_party_member=True,
        )

    def _resolve_ooc_emergency_dwaynas_kiss_target(self) -> int:
        diagnostic_state = self._diagnostic_ooc_trace_skill(
            DWAYNAS_KISS_ID,
            stage="before_target",
        )
        if not self._is_castable(DWAYNAS_KISS_ID):
            if diagnostic_state is not None:
                self._diagnostic_log_ooc_state(
                    f"decision:{DWAYNAS_KISS_ID}:not_castable",
                    "decision",
                    {
                        "stage": "target_rejected",
                        "skill": self._diagnostic_skill_label(DWAYNAS_KISS_ID),
                        "skill_id": DWAYNAS_KISS_ID,
                        "decision": "rejected",
                        "reason": "skill_not_castable",
                        "target": 0,
                    },
                )
            return 0

        custom_skill = self.GetCustomSkill(DWAYNAS_KISS_ID)
        if custom_skill is None:
            if diagnostic_state is not None:
                self._diagnostic_log_ooc_state(
                    f"decision:{DWAYNAS_KISS_ID}:custom_missing",
                    "decision",
                    {
                        "stage": "target_rejected",
                        "skill": self._diagnostic_skill_label(DWAYNAS_KISS_ID),
                        "skill_id": DWAYNAS_KISS_ID,
                        "decision": "rejected",
                        "reason": "custom_skill_missing",
                        "target": 0,
                    },
                )
            return 0

        variants = (
            (
                "enchantment",
                lambda skill: setattr(skill.Conditions, "HasEnchantment", True),
            ),
            (
                "hex",
                lambda skill: setattr(skill.Conditions, "HasHex", True),
            ),
            ("base", None),
        )
        for variant_name, variant in variants:
            variant_skill = custom_skill if variant is None else deepcopy(custom_skill)
            if variant is not None:
                variant(variant_skill)

            target_agent_id = self.ResolveRankedPartyAllyTarget(
                DWAYNAS_KISS_ID,
                variant_skill,
                validator=lambda agent_id: self._is_valid_ooc_emergency_target(
                    agent_id,
                    other_ally=True,
                ),
                rank_key=lambda agent_id: (
                    Agent.GetHealth(agent_id),
                    -self.GetPartyHealthDelta(agent_id),
                ),
            )
            if diagnostic_state is not None:
                self._diagnostic_ooc_trace_target(
                    DWAYNAS_KISS_ID,
                    target_agent_id,
                    custom_skill=variant_skill,
                    other_ally=True,
                    variant=variant_name,
                )
                self._diagnostic_log_ooc_state(
                    f"decision:{DWAYNAS_KISS_ID}:{variant_name}",
                    "decision",
                    {
                        "stage": "candidate",
                        "skill": self._diagnostic_skill_label(DWAYNAS_KISS_ID),
                        "skill_id": DWAYNAS_KISS_ID,
                        "variant": variant_name,
                        "decision": (
                            "candidate_selected" if target_agent_id else "rejected"
                        ),
                        "reason": "target_found" if target_agent_id else "no_target",
                        "target": target_agent_id,
                    },
                )
            if target_agent_id:
                return target_agent_id

        return 0

    def _try_ooc_emergency_direct_heal(
        self,
        skill_id: int,
        *,
        other_ally: bool = False,
        prefer_active_target: bool = False,
    ):
        diagnostic_state = self._diagnostic_ooc_trace_skill(
            skill_id,
            stage="before_target",
        )
        target_agent_id = self._resolve_ooc_emergency_direct_target(
            skill_id,
            other_ally=other_ally,
            prefer_active_target=prefer_active_target,
        )
        if diagnostic_state is None and target_agent_id:
            diagnostic_state = self._diagnostic_ooc_trace_skill(
                skill_id,
                stage="action_attempt",
                variant="direct",
                force=True,
            )
        if diagnostic_state is not None:
            custom_skill = self.GetCustomSkill(skill_id)
            self._diagnostic_ooc_trace_target(
                skill_id,
                target_agent_id,
                custom_skill=custom_skill,
                other_ally=other_ally,
                variant="direct",
            )
            self._diagnostic_log_ooc_state(
                f"decision:{skill_id}:direct",
                "decision",
                {
                    "stage": "candidate",
                    "skill": self._diagnostic_skill_label(skill_id),
                    "skill_id": skill_id,
                    "decision": (
                        "candidate_selected" if target_agent_id else "rejected"
                    ),
                    "reason": (
                        "target_found"
                        if target_agent_id
                        else (
                            "skill_not_castable"
                            if not diagnostic_state.get("castable")
                            else "no_target"
                        )
                    ),
                    "target": target_agent_id,
                    "castable": diagnostic_state.get("castable"),
                },
            )
        if not target_agent_id:
            return False

        result = yield from self.CastSkillIDAndRestoreTarget(
            skill_id,
            target_agent_id,
        )
        if diagnostic_state is not None:
            self._diagnostic_ooc_trace_action_result(
                skill_id,
                target_agent_id,
                result,
                variant="direct",
            )
        return result

    def _try_ooc_emergency_dwaynas_kiss(self):
        diagnostic_active = self._diagnostic_ooc_emergency_active()
        target_agent_id = self._resolve_ooc_emergency_dwaynas_kiss_target()
        if not target_agent_id:
            return False

        if not diagnostic_active:
            diagnostic_state = self._diagnostic_ooc_trace_skill(
                DWAYNAS_KISS_ID,
                stage="action_attempt",
                variant="kiss",
                force=True,
            )
            if diagnostic_state is not None:
                self._diagnostic_ooc_trace_target(
                    DWAYNAS_KISS_ID,
                    target_agent_id,
                    custom_skill=self.GetCustomSkill(DWAYNAS_KISS_ID),
                    other_ally=True,
                    variant="action_attempt",
                )
                diagnostic_active = True

        result = yield from self.CastSkillIDAndRestoreTarget(
            DWAYNAS_KISS_ID,
            target_agent_id,
        )
        if diagnostic_active:
            self._diagnostic_ooc_trace_action_result(
                DWAYNAS_KISS_ID,
                target_agent_id,
                result,
                variant="kiss",
            )
        return result

    def _try_cure_hex(self, min_priority: int):
        if not self._is_castable(CURE_HEX_ID):
            return False
        return (
            yield from self.skillbook.Monk.HealingPrayers.Cure_Hex(
                min_priority=min_priority,
            )
        )

    def _has_earshot_enemies(self, enemy_count: int | None = None) -> bool:
        if enemy_count is not None:
            return enemy_count >= 2
        player_x, player_y = Player.GetXY()
        enemy_array = Routines.Agents.GetFilteredEnemyArray(
            player_x,
            player_y,
            Range.Earshot.value,
        )
        return len(enemy_array or []) >= 2

    def _get_current_nearby_enemy_count(self) -> int:
        try:
            player_x, player_y = Player.GetXY()
            enemy_array = Routines.Agents.GetFilteredEnemyArray(
                player_x,
                player_y,
                Range.Earshot.value,
            )
        except Exception:
            return 0
        return len(enemy_array or [])

    def _try_ebon_battle_standard_of_wisdom(self, enemy_count: int | None = None):
        if not self._is_castable(EBON_BATTLE_STANDARD_OF_WISDOM_ID):
            return False
        if not self._has_earshot_enemies(enemy_count):
            return False
        return (
            yield from self.skillbook.Any.NoAttribute.Ebon_Battle_Standard_of_Wisdom()
        )

    def _get_actual_party_ids(self) -> list[int]:
        party_ids: list[int] = []
        seen_ids: set[int] = set()

        def append_agent(agent_id: Any) -> None:
            try:
                normalized_id = int(agent_id or 0)
            except Exception:
                return
            if normalized_id > 0 and normalized_id not in seen_ids:
                seen_ids.add(normalized_id)
                party_ids.append(normalized_id)

        try:
            players = GLOBAL_CACHE.Party.GetPlayers() or []
        except Exception:
            players = []
        for player in players:
            try:
                append_agent(
                    GLOBAL_CACHE.Party.Players.GetAgentIDByLoginNumber(
                        player.login_number
                    )
                )
            except Exception:
                continue

        try:
            heroes = GLOBAL_CACHE.Party.GetHeroes() or []
        except Exception:
            heroes = []
        for hero in heroes:
            append_agent(getattr(hero, "agent_id", 0))

        try:
            henchmen = GLOBAL_CACHE.Party.GetHenchmen() or []
        except Exception:
            henchmen = []
        for henchman in henchmen:
            append_agent(getattr(henchman, "agent_id", 0))

        player_id = int(Player.GetAgentID() or 0)
        if player_id and player_id not in seen_ids:
            party_ids.insert(0, player_id)

        return party_ids

    def _get_current_party_player_ids(self) -> set[int]:
        player_ids: set[int] = set()
        try:
            players = GLOBAL_CACHE.Party.GetPlayers() or []
        except Exception:
            return player_ids

        for player in players:
            try:
                agent_id = int(
                    GLOBAL_CACHE.Party.Players.GetAgentIDByLoginNumber(
                        player.login_number
                    )
                    or 0
                )
            except Exception:
                continue
            if agent_id > 0:
                player_ids.add(agent_id)
        return player_ids

    def _get_same_party_shared_accounts(
        self,
        party_member_ids: set[int] | None = None,
    ) -> dict[int, Any]:
        if party_member_ids is None:
            party_member_ids = set(self._get_actual_party_ids())
        if not party_member_ids:
            return {}

        try:
            map_signature = (
                int(Map.GetMapID() or 0),
                int(Map.GetRegion()[0] or 0),
                int(Map.GetDistrict() or 0),
                int(Map.GetLanguage()[0] or 0),
            )
            party_id = int(GLOBAL_CACHE.Party.GetPartyID() or 0)
        except Exception:
            return {}
        if map_signature[0] <= 0 or party_id <= 0:
            return {}

        try:
            account_data = GLOBAL_CACHE.ShMem.GetAllActiveSlotsData() or []
        except Exception:
            try:
                account_data = GLOBAL_CACHE.ShMem.GetAllAccountData() or []
            except Exception:
                return {}

        shared_accounts: dict[int, Any] = {}
        for account in account_data:
            try:
                if not bool(getattr(account, "IsSlotActive", False)):
                    continue
                if not bool(getattr(account, "IsAccount", False)):
                    continue
                agent_data = getattr(account, "AgentData", None)
                agent_id = int(getattr(agent_data, "AgentID", 0) or 0)
                if agent_id <= 0 or agent_id not in party_member_ids:
                    continue
                account_party_id = int(
                    getattr(getattr(account, "AgentPartyData", None), "PartyID", 0) or 0
                )
                if account_party_id != party_id:
                    continue
                account_map = getattr(agent_data, "Map", None)
                account_map_signature = (
                    int(getattr(account_map, "MapID", 0) or 0),
                    int(getattr(account_map, "Region", 0) or 0),
                    int(getattr(account_map, "District", 0) or 0),
                    int(getattr(account_map, "Language", 0) or 0),
                )
                if account_map_signature != map_signature:
                    continue
                if int(getattr(account, "LastUpdated", 0) or 0) <= 0:
                    continue
                shared_accounts[agent_id] = account
            except Exception:
                continue
        return shared_accounts

    def _get_shared_last_updated(
        self,
        party_member_ids: set[int] | None = None,
    ) -> dict[int, int]:
        return {
            agent_id: int(getattr(account, "LastUpdated", 0) or 0)
            for agent_id, account in self._get_same_party_shared_accounts(
                party_member_ids
            ).items()
        }

    def _build_shared_effect_snapshots(
        self,
        shared_accounts: dict[int, Any],
    ) -> dict[int, _SharedAgentSnapshot]:
        snapshots: dict[int, _SharedAgentSnapshot] = {}
        for agent_id, account in shared_accounts.items():
            try:
                agent_data = getattr(account, "AgentData", None)
                last_updated = int(getattr(account, "LastUpdated", 0) or 0)
                if agent_id <= 0 or last_updated <= 0 or agent_data is None:
                    continue
            except Exception:
                continue

            exact_effects_available = True
            try:
                buffs = getattr(getattr(agent_data, "Buffs", None), "Buffs", None)
                if buffs is None:
                    raise ValueError("shared buff list is unavailable")
                effect_ids = frozenset(
                    effect_id
                    for effect in buffs
                    if (effect_id := self._get_effect_skill_id(effect)) > 0
                )
            except Exception:
                effect_ids = frozenset()
                exact_effects_available = False

            try:
                is_enchanted = bool(getattr(agent_data, "Is_Enchanted"))
            except Exception:
                is_enchanted = False
            try:
                is_hexed = bool(getattr(agent_data, "Is_Hexed"))
            except Exception:
                is_hexed = False
            try:
                is_attacking = int(getattr(agent_data, "AnimationCode", 0)) == 2
            except Exception:
                is_attacking = False
            try:
                is_casting = bool(getattr(agent_data, "Is_Casting"))
            except Exception:
                is_casting = False

            snapshots[agent_id] = _SharedAgentSnapshot(
                last_updated=last_updated,
                effect_ids=effect_ids,
                exact_effects_available=exact_effects_available,
                is_enchanted=is_enchanted,
                is_hexed=is_hexed,
                is_attacking=is_attacking,
                is_casting=is_casting,
            )
        return snapshots

    def _get_effective_attribute_rank(
        self,
        attribute_id: int,
        attribute_ranks: dict[int, int] | None = None,
    ) -> int:
        if attribute_ranks is None:
            attribute_ranks = self._get_attribute_ranks()
        return max(0, int(attribute_ranks.get(int(attribute_id), 0)))

    def _get_attribute_ranks(self) -> dict[int, int]:
        ranks: dict[int, int] = {}
        try:
            attributes = Agent.GetAttributes(Player.GetAgentID()) or []
        except Exception:
            return ranks

        for attribute in attributes:
            try:
                attribute_key = int(getattr(attribute, "attribute_id", 0))
                effective_level = int(
                    getattr(
                        attribute,
                        "level",
                        getattr(attribute, "level_base", 0),
                    )
                )
            except Exception:
                continue
            ranks[attribute_key] = max(ranks.get(attribute_key, 0), effective_level)
        return ranks

    def _scaled_runtime_value(
        self,
        skill_id: int,
        rank: int,
        *,
        bonus: bool = False,
        skill_snapshot: _SkillSnapshot | None = None,
    ) -> float:
        try:
            if skill_snapshot is None:
                scale = (
                    GLOBAL_CACHE.Skill.Attribute.GetBonusScale(skill_id)
                    if bonus
                    else GLOBAL_CACHE.Skill.Attribute.GetScale(skill_id)
                )
                scale_0, scale_15 = scale
            elif bonus:
                scale_0 = skill_snapshot.bonus_scale_0
                scale_15 = skill_snapshot.bonus_scale_15
            else:
                scale_0 = skill_snapshot.scale_0
                scale_15 = skill_snapshot.scale_15
            rank_value = max(0.0, float(rank))
            return float(
                math.floor(
                    float(scale_0)
                    + (float(scale_15) - float(scale_0)) * rank_value / 15.0
                    + 0.5
                )
            )
        except Exception:
            return 0.0

    def _divine_favor_heal(self, rank: int) -> float:
        return float(math.floor(DIVINE_FAVOR_HEAL_PER_RANK * max(0, rank) + 0.5))

    def _get_skill_snapshot(self, skill_id: int) -> _SkillSnapshot:
        try:
            equipped = bool(self.IsSkillEquipped(skill_id))
        except Exception:
            equipped = False
        try:
            castable = equipped and bool(self.CanCastSkillID(skill_id))
        except Exception:
            castable = False

        def get_float(getter: Callable[[int], Any]) -> float:
            try:
                return max(0.0, float(getter(skill_id) or 0.0))
            except Exception:
                return 0.0

        try:
            energy_cost = max(
                0.0,
                float(
                    Routines.Checks.Skills.GetEnergyCostWithEffects(
                        skill_id,
                        Player.GetAgentID(),
                    )
                    or 0.0
                ),
            )
        except Exception:
            energy_cost = 0.0

        try:
            scale_0, scale_15 = GLOBAL_CACHE.Skill.Attribute.GetScale(skill_id)
        except Exception:
            scale_0, scale_15 = 0.0, 0.0
        try:
            bonus_scale_0, bonus_scale_15 = GLOBAL_CACHE.Skill.Attribute.GetBonusScale(
                skill_id
            )
        except Exception:
            bonus_scale_0, bonus_scale_15 = 0.0, 0.0

        return _SkillSnapshot(
            skill_id=skill_id,
            equipped=equipped,
            castable=castable,
            energy_cost=energy_cost,
            activation_seconds=get_float(GLOBAL_CACHE.Skill.Data.GetActivation),
            aftercast_seconds=get_float(GLOBAL_CACHE.Skill.Data.GetAftercast),
            recharge_seconds=get_float(GLOBAL_CACHE.Skill.Data.GetRecharge),
            scale_0=float(scale_0 or 0.0),
            scale_15=float(scale_15 or 0.0),
            bonus_scale_0=float(bonus_scale_0 or 0.0),
            bonus_scale_15=float(bonus_scale_15 or 0.0),
        )

    @staticmethod
    def _coerce_position(raw_position: Any) -> tuple[float, float] | None:
        try:
            x, y = raw_position
            position = (float(x), float(y))
        except Exception:
            return None
        if not math.isfinite(position[0]) or not math.isfinite(position[1]):
            return None
        return position

    @staticmethod
    def _shared_snapshot_age_ms(
        tick_ms: int,
        snapshot: _SharedAgentSnapshot,
    ) -> int:
        return max(0, tick_ms - int(snapshot.last_updated))

    @classmethod
    def _is_shared_effect_snapshot_fresh(
        cls,
        tick_ms: int,
        snapshot: _SharedAgentSnapshot,
    ) -> bool:
        return (
            cls._shared_snapshot_age_ms(tick_ms, snapshot)
            + _SHARED_EFFECT_FIELD_MAX_AGE_MS
            <= SHARED_EFFECT_FRESHNESS_MS
        )

    @classmethod
    def _is_shared_effect_flags_fresh(
        cls,
        tick_ms: int,
        snapshot: _SharedAgentSnapshot,
    ) -> bool:
        return (
            cls._shared_snapshot_age_ms(tick_ms, snapshot) <= SHARED_EFFECT_FRESHNESS_MS
        )

    @classmethod
    def _is_shared_activity_snapshot_fresh(
        cls,
        tick_ms: int,
        snapshot: _SharedAgentSnapshot,
    ) -> bool:
        return (
            cls._shared_snapshot_age_ms(tick_ms, snapshot)
            + _SHARED_ACTIVITY_FIELD_MAX_AGE_MS
            <= SHARED_EFFECT_FRESHNESS_MS
        )

    def _recent_health_trend_samples(
        self,
        agent_id: int,
        tick_ms: int,
    ) -> tuple[tuple[int, float], ...]:
        previous_samples = self._health_trend_history.get(agent_id, ())
        recent_samples = tuple(
            sample
            for sample in previous_samples
            if 0 <= tick_ms - sample[0] <= _HEALTH_TREND_MAX_GAP_MS
        )
        if recent_samples and recent_samples[-1][0] == tick_ms:
            recent_samples = recent_samples[:-1]
        return recent_samples

    @staticmethod
    def _health_trend_is_falling(
        samples: tuple[tuple[int, float], ...],
    ) -> bool:
        if len(samples) < 3:
            return False

        (
            (first_tick, first_health),
            (second_tick, second_health),
            (
                third_tick,
                third_health,
            ),
        ) = samples
        return (
            first_tick < second_tick < third_tick
            and first_health - second_health > _HEALTH_TREND_EPSILON
            and second_health - third_health > _HEALTH_TREND_EPSILON
        )

    def _health_trend_is_recovering(
        self,
        agent_id: int,
        tick_ms: int,
        health: float,
    ) -> bool:
        recent_samples = self._recent_health_trend_samples(agent_id, tick_ms)
        return bool(
            recent_samples and health > recent_samples[-1][1] + _HEALTH_TREND_EPSILON
        )

    @staticmethod
    def _health_trend_samples_with_observation(
        recent_samples: tuple[tuple[int, float], ...],
        tick_ms: int,
        health: float,
    ) -> tuple[tuple[int, float], ...]:
        if (
            recent_samples
            and abs(health - recent_samples[-1][1]) <= _HEALTH_TREND_EPSILON
        ):
            return recent_samples
        return (*recent_samples, (tick_ms, health))[-3:]

    def _record_health_trend_sample(
        self,
        agent_id: int,
        tick_ms: int,
        health: float,
    ) -> bool:
        recent_samples = self._recent_health_trend_samples(agent_id, tick_ms)
        samples = self._health_trend_samples_with_observation(
            recent_samples,
            tick_ms,
            health,
        )
        self._health_trend_history[agent_id] = samples
        return self._health_trend_is_falling(samples)

    def _read_health_trend_state(
        self,
        agent_id: int,
        tick_ms: int,
        health: float,
    ) -> bool:
        recent_samples = self._recent_health_trend_samples(agent_id, tick_ms)
        samples = self._health_trend_samples_with_observation(
            recent_samples,
            tick_ms,
            health,
        )
        return self._health_trend_is_falling(samples)

    def _build_combat_context(self) -> _CombatContext:
        try:
            tick_ms = int(PySystem.get_tick_count64())
        except Exception:
            tick_ms = 0

        player_id = int(Player.GetAgentID() or 0)
        try:
            player_position = self._coerce_position(Player.GetXY())
        except Exception:
            player_position = None

        try:
            health_monitor = (
                self.UpdatePartyHealthMonitor(
                    sample_interval_ms=150,
                    window_ms=1000,
                )
                or {}
            )
        except Exception:
            health_monitor = {}

        actual_party_ids = self._get_actual_party_ids()
        party_player_ids = frozenset(self._get_current_party_player_ids())
        shared_accounts = self._get_same_party_shared_accounts(set(actual_party_ids))
        shared_effect_snapshots = self._build_shared_effect_snapshots(shared_accounts)
        shared_last_updated = {
            agent_id: snapshot.last_updated
            for agent_id, snapshot in shared_effect_snapshots.items()
        }
        active_party_ids = set(actual_party_ids)
        for agent_id in list(self._health_trend_history):
            if agent_id not in active_party_ids:
                del self._health_trend_history[agent_id]
        party_members: list[_PartyMemberSnapshot] = []
        diagnostic_observations: list[_DiagnosticMemberObservation] = []
        for party_order, agent_id in enumerate(actual_party_ids):
            is_remote_player = agent_id in party_player_ids and agent_id != player_id
            shared_account = shared_accounts.get(agent_id)
            try:
                is_valid = bool(Agent.IsValid(agent_id))
                is_alive = is_valid and bool(Routines.Checks.Agents.IsAlive(agent_id))
            except Exception:
                is_valid = False
                is_alive = False
            if not is_valid or not is_alive:
                self._health_trend_history.pop(agent_id, None)
                diagnostic_observations.append(
                    self._diagnostic_observation_from_values(
                        agent_id,
                        present=True,
                        valid=is_valid,
                        alive=is_alive,
                        is_remote=is_remote_player,
                        health=None,
                        native_health=None,
                        shared_account=shared_account,
                        tick_ms=tick_ms,
                        maximum_health=None,
                        missing_hp=None,
                        position_available=False,
                        distance_from_player=None,
                        recent_health_drop=self._diagnostic_recent_drop(
                            agent_id,
                            health_monitor,
                        ),
                    )
                )
                continue

            try:
                raw_health = float(Routines.Checks.Agents.GetHealth(agent_id))
            except Exception:
                self._health_trend_history.pop(agent_id, None)
                diagnostic_observations.append(
                    self._diagnostic_observation_from_values(
                        agent_id,
                        present=True,
                        valid=is_valid,
                        alive=is_alive,
                        is_remote=is_remote_player,
                        health=None,
                        native_health=None,
                        shared_account=shared_account,
                        tick_ms=tick_ms,
                        maximum_health=None,
                        missing_hp=None,
                        position_available=False,
                        distance_from_player=None,
                        recent_health_drop=self._diagnostic_recent_drop(
                            agent_id,
                            health_monitor,
                        ),
                    )
                )
                continue
            if not math.isfinite(raw_health):
                self._health_trend_history.pop(agent_id, None)
                diagnostic_observations.append(
                    self._diagnostic_observation_from_values(
                        agent_id,
                        present=True,
                        valid=is_valid,
                        alive=is_alive,
                        is_remote=is_remote_player,
                        health=raw_health,
                        native_health=None,
                        shared_account=shared_account,
                        tick_ms=tick_ms,
                        maximum_health=None,
                        missing_hp=None,
                        position_available=False,
                        distance_from_player=None,
                        recent_health_drop=self._diagnostic_recent_drop(
                            agent_id,
                            health_monitor,
                        ),
                    )
                )
                continue
            health = max(0.0, min(1.0, raw_health))
            try:
                native_maximum_health = float(Agent.GetMaxHealth(agent_id) or 0.0)
            except Exception:
                native_maximum_health = None
                maximum_health = 0.0
            else:
                maximum_health = native_maximum_health
            if (
                maximum_health is None
                or not math.isfinite(maximum_health)
                or maximum_health <= 0.0
            ):
                maximum_health = 0.0
            try:
                native_health = float(Agent.GetHealth(agent_id))
            except Exception:
                native_health = None
            try:
                position = self._coerce_position(Agent.GetXY(agent_id))
                if player_position is None or position is None:
                    distance_from_player = float("inf")
                else:
                    distance_from_player = float(
                        Utils.Distance(player_position, position)
                    )
            except Exception:
                position = None
                distance_from_player = float("inf")

            monitor_state = health_monitor.get(agent_id, {})
            try:
                recent_health_drop = max(
                    0.0,
                    min(
                        1.0,
                        float(
                            monitor_state.get(
                                "drop",
                                self.GetPartyHealthDelta(agent_id),
                            )
                            or 0.0
                        ),
                    ),
                )
            except Exception:
                recent_health_drop = 0.0

            health_is_recovering = self._health_trend_is_recovering(
                agent_id,
                tick_ms,
                health,
            )
            health_is_falling = self._record_health_trend_sample(
                agent_id,
                tick_ms,
                health,
            )

            diagnostic_observations.append(
                self._diagnostic_observation_from_values(
                    agent_id,
                    present=True,
                    valid=is_valid,
                    alive=is_alive,
                    is_remote=is_remote_player,
                    health=raw_health,
                    native_health=native_health,
                    shared_account=shared_account,
                    tick_ms=tick_ms,
                    maximum_health=native_maximum_health,
                    missing_hp=(
                        maximum_health * max(0.0, 1.0 - health)
                        if maximum_health > 0.0
                        else 0.0
                    ),
                    position_available=position is not None,
                    distance_from_player=distance_from_player,
                    recent_health_drop=recent_health_drop,
                )
            )

            try:
                is_martial = bool(Routines.Checks.Agents.IsMartial(agent_id))
            except Exception:
                is_martial = False
            try:
                is_melee = bool(Routines.Checks.Agents.IsMelee(agent_id))
            except Exception:
                is_melee = False
            shared_snapshot = shared_effect_snapshots.get(agent_id)
            if is_remote_player:
                if (
                    shared_snapshot is not None
                    and self._is_shared_activity_snapshot_fresh(
                        tick_ms, shared_snapshot
                    )
                ):
                    is_attacking = shared_snapshot.is_attacking
                    is_casting = shared_snapshot.is_casting
                else:
                    is_attacking = False
                    is_casting = False
            else:
                try:
                    is_attacking = bool(Routines.Checks.Agents.IsAttacking(agent_id))
                except Exception:
                    is_attacking = False
                try:
                    is_casting = bool(Agent.IsCasting(agent_id))
                except Exception:
                    is_casting = False

            party_members.append(
                _PartyMemberSnapshot(
                    agent_id=agent_id,
                    party_order=party_order,
                    is_self=agent_id == player_id,
                    valid=is_valid,
                    alive=is_alive,
                    health=health,
                    maximum_health=maximum_health,
                    missing_hp=(
                        maximum_health * max(0.0, 1.0 - health)
                        if maximum_health > 0.0
                        else 0.0
                    ),
                    position=position,
                    distance_from_player=distance_from_player,
                    recent_health_drop=recent_health_drop,
                    health_is_falling=health_is_falling,
                    is_critical=health <= COMBAT_CRITICAL_HEALTH_THRESHOLD,
                    is_pressure_target=recent_health_drop
                    >= COMBAT_PRESSURE_DROP_THRESHOLD,
                    is_aegis_spike_target=recent_health_drop
                    >= AEGIS_PRESSURE_DROP_THRESHOLD,
                    is_injured=health < 1.0,
                    is_martial=is_martial,
                    is_melee=is_melee,
                    is_attacking=is_attacking,
                    is_casting=is_casting,
                    health_is_recovering=health_is_recovering,
                )
            )

        self._diagnostic_trace_observations(
            run="combat",
            tick_ms=tick_ms,
            actual_party_ids=actual_party_ids,
            observations=diagnostic_observations,
            player_position=player_position,
        )

        party_members_tuple = tuple(party_members)
        party_by_id = {member.agent_id: member for member in party_members_tuple}
        critical_ids = tuple(
            member.agent_id for member in party_members_tuple if member.is_critical
        )
        pressure_ids = tuple(
            member.agent_id
            for member in party_members_tuple
            if member.is_pressure_target
        )
        aegis_actionable_ids = tuple(
            member.agent_id
            for member in party_members_tuple
            if member.is_aegis_spike_target
        )
        injured_ids = tuple(
            member.agent_id for member in party_members_tuple if member.is_injured
        )

        specialized_spikes: list[tuple[float, float, int]] = []
        for raw_agent_id, state in health_monitor.items():
            try:
                agent_id = int(raw_agent_id)
                drop = float(state.get("drop", 0.0) or 0.0)
            except Exception:
                continue
            if drop < AEGIS_PRESSURE_DROP_THRESHOLD:
                continue
            try:
                if not Routines.Checks.Agents.IsAlive(agent_id):
                    continue
                health = float(Routines.Checks.Agents.GetHealth(agent_id))
            except Exception:
                continue
            specialized_spikes.append((drop, health, agent_id))
        specialized_spikes.sort(key=lambda item: (-item[0], item[1], item[2]))

        attribute_ranks = self._get_attribute_ranks()
        skill_states = {
            skill_id: self._get_skill_snapshot(skill_id)
            for skill_id in (
                HEALING_BURST_ID,
                DWAYNAS_KISS_ID,
                SIGNET_OF_REJUVENATION_ID,
                PATIENT_SPIRIT_ID,
                SEED_OF_LIFE_ID,
                AEGIS_ID,
            )
        }

        try:
            maximum_energy = float(Agent.GetMaxEnergy(player_id) or 0.0)
            current_energy = float(Agent.GetEnergy(player_id) or 0.0) * maximum_energy
        except Exception:
            current_energy = 0.0
            maximum_energy = 0.0

        if player_position is None:
            enemy_array = []
        else:
            try:
                enemy_array = list(
                    Routines.Agents.GetFilteredEnemyArray(
                        player_position[0],
                        player_position[1],
                        Range.Earshot.value,
                    )
                    or []
                )
            except Exception:
                enemy_array = []
        nearby_martial_enemy_count = 0
        nearby_attacking_martial_enemy_count = 0
        for enemy_id in enemy_array:
            try:
                is_martial_enemy = bool(Agent.IsMartial(enemy_id))
            except Exception:
                is_martial_enemy = False
            if not is_martial_enemy:
                continue
            nearby_martial_enemy_count += 1
            try:
                if Agent.IsAttacking(enemy_id):
                    nearby_attacking_martial_enemy_count += 1
            except Exception:
                continue

        return _CombatContext(
            tick_ms=tick_ms,
            player_id=player_id,
            player_position=player_position,
            party_members=party_members_tuple,
            party_by_id=party_by_id,
            critical_ids=critical_ids,
            pressure_ids=pressure_ids,
            aegis_actionable_ids=aegis_actionable_ids,
            injured_ids=injured_ids,
            critical_missing_hp=sum(
                party_by_id[agent_id].missing_hp for agent_id in critical_ids
            ),
            pressure_missing_hp=sum(
                party_by_id[agent_id].missing_hp for agent_id in pressure_ids
            ),
            injured_missing_hp=sum(
                party_by_id[agent_id].missing_hp for agent_id in injured_ids
            ),
            healing_prayers_rank=self._get_effective_attribute_rank(
                Attribute.HealingPrayers,
                attribute_ranks,
            ),
            divine_favor_rank=self._get_effective_attribute_rank(
                Attribute.DivineFavor,
                attribute_ranks,
            ),
            protection_prayers_rank=self._get_effective_attribute_rank(
                Attribute.ProtectionPrayers,
                attribute_ranks,
            ),
            current_energy=current_energy,
            maximum_energy=maximum_energy,
            skill_states=skill_states,
            specialized_spike_candidates=tuple(item[2] for item in specialized_spikes),
            nearby_enemy_count=len(enemy_array),
            nearby_martial_enemy_count=nearby_martial_enemy_count,
            nearby_attacking_martial_enemy_count=nearby_attacking_martial_enemy_count,
            shared_last_updated=shared_last_updated,
            shared_effect_snapshots=shared_effect_snapshots,
            party_player_ids=party_player_ids,
        )

    def _context_distance(
        self,
        context: _CombatContext,
        source_agent_id: int,
        target_agent_id: int,
    ) -> float:
        cache_key = (source_agent_id, target_agent_id)
        if cache_key in context.distance_cache:
            return context.distance_cache[cache_key]

        if source_agent_id == context.player_id:
            source_position = context.player_position
        else:
            source_member = context.party_by_id.get(source_agent_id)
            if source_member is not None:
                source_position = source_member.position
            else:
                try:
                    source_position = self._coerce_position(
                        Agent.GetXY(source_agent_id)
                    )
                except Exception:
                    source_position = None

        target_member = context.party_by_id.get(target_agent_id)
        if target_member is not None:
            target_position = target_member.position
        else:
            try:
                target_position = self._coerce_position(Agent.GetXY(target_agent_id))
            except Exception:
                target_position = None

        if source_position is None or target_position is None:
            distance = float("inf")
        else:
            try:
                distance = float(Utils.Distance(source_position, target_position))
            except Exception:
                distance = float("inf")
        context.distance_cache[cache_key] = distance
        return distance

    def _has_effect_cached(
        self,
        context: _CombatContext,
        agent_id: int,
        skill_id: int,
    ) -> bool:
        cache_key = (agent_id, skill_id)
        if cache_key in context.effect_presence_cache:
            return context.effect_presence_cache[cache_key]
        try:
            has_effect = bool(Routines.Checks.Effects.HasEffect(agent_id, skill_id))
        except Exception:
            has_effect = False
        context.effect_presence_cache[cache_key] = has_effect
        return has_effect

    def _has_verified_effect_absence(
        self,
        context: _CombatContext,
        agent_id: int,
        skill_id: int,
    ) -> bool:
        if agent_id == context.player_id or agent_id not in context.party_player_ids:
            return True
        snapshot = context.shared_effect_snapshots.get(agent_id)
        return bool(
            snapshot is not None
            and snapshot.exact_effects_available
            and self._is_shared_effect_snapshot_fresh(context.tick_ms, snapshot)
            and skill_id not in snapshot.effect_ids
        )

    def _has_effect_fresh(
        self,
        agent_id: int,
        skill_id: int,
        *,
        shared_accounts: dict[int, Any] | None = None,
        party_player_ids: set[int] | frozenset[int] | None = None,
        context: _CombatContext | None = None,
    ) -> bool:
        if not agent_id or not skill_id:
            return False

        local_player_id = (
            context.player_id if context is not None else Player.GetAgentID()
        )
        if agent_id == local_player_id:
            try:
                return bool(GLOBAL_CACHE.Effects.HasEffect(agent_id, skill_id))
            except Exception:
                pass

        if party_player_ids is None:
            party_player_ids = (
                context.party_player_ids
                if context is not None
                else self._get_current_party_player_ids()
            )

        is_remote_player = agent_id in party_player_ids
        if shared_accounts is not None and agent_id in shared_accounts:
            is_remote_player = True
        if context is not None and agent_id in context.shared_effect_snapshots:
            is_remote_player = True

        if is_remote_player:
            try:
                if shared_accounts is None:
                    shared_accounts = self._get_same_party_shared_accounts(
                        set(party_player_ids)
                    )
                snapshots = self._build_shared_effect_snapshots(shared_accounts)
                try:
                    tick_ms = int(PySystem.get_tick_count64())
                except Exception:
                    tick_ms = 0
                snapshot = snapshots.get(agent_id)

                if (
                    snapshot is None
                    or tick_ms <= 0
                    or not snapshot.exact_effects_available
                    or int(snapshot.last_updated) <= 0
                    or not self._is_shared_effect_snapshot_fresh(tick_ms, snapshot)
                ):
                    # Unknown shared state must not be treated as an uncovered
                    # target at the final execution boundary.
                    return True
                return skill_id in snapshot.effect_ids
            except Exception:
                # An exclusion check that cannot prove a fresh exact snapshot
                # must fail closed: the effect may still be present.
                return True

        try:
            return bool(GLOBAL_CACHE.Effects.HasEffect(agent_id, skill_id))
        except Exception:
            try:
                return bool(Routines.Checks.Effects.HasEffect(agent_id, skill_id))
            except Exception:
                return True

    @staticmethod
    def _get_effect_skill_id(effect: Any) -> int:
        raw_skill_id = getattr(effect, "skill_id", None)
        if raw_skill_id is None:
            raw_skill_id = getattr(effect, "SkillId", 0)
        try:
            return int(raw_skill_id or 0)
        except Exception:
            return 0

    def _get_effect_summary(
        self,
        context: _CombatContext,
        agent_id: int,
    ) -> _EffectSummary:
        if agent_id in context.effect_summary_cache:
            return context.effect_summary_cache[agent_id]

        snapshot_age_ms: int | None = None
        source = "native"
        skill_ids: frozenset[int] | set[int] = set()
        boolean_lower_bound = 0
        shared_snapshot = context.shared_effect_snapshots.get(agent_id)
        is_remote_player = agent_id != context.player_id and (
            agent_id in context.party_player_ids or shared_snapshot is not None
        )

        if is_remote_player:
            if shared_snapshot is None:
                shared_timestamp = context.shared_last_updated.get(agent_id)
                if shared_timestamp is not None:
                    snapshot_age_ms = max(0, context.tick_ms - int(shared_timestamp))
                summary = _EffectSummary(
                    supported_count=0,
                    minimum_count=0,
                    confidence="unknown",
                    source="unverified_shared",
                    snapshot_age_ms=snapshot_age_ms,
                )
                context.effect_summary_cache[agent_id] = summary
                return summary

            snapshot_age_ms = self._shared_snapshot_age_ms(
                context.tick_ms,
                shared_snapshot,
            )
            effect_snapshot_fresh = self._is_shared_effect_snapshot_fresh(
                context.tick_ms,
                shared_snapshot,
            )
            effect_flags_fresh = self._is_shared_effect_flags_fresh(
                context.tick_ms,
                shared_snapshot,
            )
            if effect_snapshot_fresh and shared_snapshot.exact_effects_available:
                skill_ids = shared_snapshot.effect_ids
                source = "fresh_shared"
            elif effect_flags_fresh:
                source = "fresh_shared_flags"
            else:
                source = "stale_shared"
            if effect_flags_fresh:
                boolean_lower_bound = int(shared_snapshot.is_enchanted) + int(
                    shared_snapshot.is_hexed
                )
        else:
            try:
                effects = list(GLOBAL_CACHE.Effects.GetBuffs(agent_id) or [])
            except Exception:
                effects = []
            try:
                effects.extend(GLOBAL_CACHE.Effects.GetEffects(agent_id) or [])
            except Exception:
                pass
            skill_ids = {
                skill_id
                for effect in effects
                if (skill_id := self._get_effect_skill_id(effect)) > 0
            }
            try:
                boolean_lower_bound = int(
                    bool(Routines.Checks.Agents.IsEnchanted(agent_id))
                ) + int(bool(Routines.Checks.Agents.IsHexed(agent_id)))
            except Exception:
                boolean_lower_bound = 0

        supported_ids: set[int] = set()
        for skill_id in skill_ids:
            try:
                if GLOBAL_CACHE.Skill.Flags.IsEnchantment(
                    skill_id
                ) or GLOBAL_CACHE.Skill.Flags.IsHex(skill_id):
                    supported_ids.add(skill_id)
            except Exception:
                continue

        enumerated_count = len(supported_ids)
        supported_count = max(enumerated_count, boolean_lower_bound)
        if supported_count > enumerated_count:
            confidence = "boolean_lower_bound"
        elif source in {"fresh_shared", "fresh_shared_flags"}:
            confidence = "fresh_shared"
        elif source == "stale_shared":
            confidence = "boolean_lower_bound" if supported_count else "unknown"
        else:
            confidence = "native_enumerated"

        summary = _EffectSummary(
            supported_count=supported_count,
            minimum_count=supported_count,
            confidence=confidence,
            source=source,
            snapshot_age_ms=snapshot_age_ms,
        )
        context.effect_summary_cache[agent_id] = summary
        return summary

    def _has_reliable_activity(
        self,
        context: _CombatContext,
        member: _PartyMemberSnapshot,
    ) -> bool:
        if member.agent_id not in context.party_player_ids:
            return member.is_attacking or member.is_casting
        if member.agent_id == context.player_id:
            return member.is_attacking or member.is_casting
        shared_snapshot = context.shared_effect_snapshots.get(member.agent_id)
        return bool(
            shared_snapshot is not None
            and self._is_shared_activity_snapshot_fresh(
                context.tick_ms,
                shared_snapshot,
            )
            and (shared_snapshot.is_attacking or shared_snapshot.is_casting)
        )

    def _relief(
        self,
        context: _CombatContext,
        member_ids: tuple[int, ...] | list[int],
        effect_by_target: dict[int, float],
    ) -> float:
        total_missing = 0.0
        total_relief = 0.0
        for agent_id in member_ids:
            member = context.party_by_id.get(agent_id)
            if member is None:
                continue
            missing_hp = max(0.0, member.missing_hp)
            total_missing += missing_hp
            total_relief += min(
                missing_hp,
                max(0.0, float(effect_by_target.get(agent_id, 0.0))),
            )
        if total_missing <= 0.0:
            return 0.0
        return max(0.0, min(1.0, total_relief / total_missing))

    @staticmethod
    def _predicted_heal_hp(healing_points: float) -> float:
        """Return a predicted healing packet in HP, never a health fraction."""
        try:
            healing_hp = float(healing_points)
        except Exception:
            return 0.0
        if not math.isfinite(healing_hp):
            return 0.0
        return max(0.0, healing_hp)

    def _has_useful_relief(
        self,
        context: _CombatContext,
        member_ids: tuple[int, ...] | list[int],
        effect_by_target: dict[int, float],
    ) -> bool:
        return self._relief(context, member_ids, effect_by_target) > 0.0

    def _get_combat_urgency(
        self,
        context: _CombatContext,
        immediate_effects: dict[int, float],
        conservative_effects: dict[int, float],
    ) -> _CombatUrgency:
        if self._has_useful_relief(context, context.critical_ids, immediate_effects):
            return _CombatUrgency.CRITICAL_IMMEDIATE
        if self._has_useful_relief(context, context.pressure_ids, conservative_effects):
            return _CombatUrgency.URGENT_REACTIVE
        if self._has_useful_relief(context, context.injured_ids, conservative_effects):
            return _CombatUrgency.CURRENT_INJURY
        return _CombatUrgency.MAINTENANCE

    def _get_candidate_values(
        self,
        context: _CombatContext,
        urgency: _CombatUrgency,
        immediate_effects: dict[int, float],
        conservative_effects: dict[int, float],
    ) -> tuple[float, float]:
        if urgency == _CombatUrgency.CRITICAL_IMMEDIATE:
            return (
                self._relief(context, context.critical_ids, immediate_effects),
                self._relief(context, context.injured_ids, immediate_effects),
            )
        if urgency == _CombatUrgency.URGENT_REACTIVE:
            return (
                self._relief(context, context.pressure_ids, conservative_effects),
                self._relief(context, context.injured_ids, immediate_effects),
            )
        if urgency == _CombatUrgency.CURRENT_INJURY:
            return (
                self._relief(context, context.injured_ids, conservative_effects),
                self._relief(context, context.injured_ids, immediate_effects),
            )
        return 0.0, 0.0

    def _is_lifesaving_candidate(
        self,
        context: _CombatContext,
        immediate_effects: dict[int, float],
        direct_primary_targets: set[int],
    ) -> bool:
        for agent_id in context.critical_ids:
            member = context.party_by_id.get(agent_id)
            if member is None or member.maximum_health <= 0.0:
                continue
            immediate_heal_hp = max(
                0.0,
                float(immediate_effects.get(agent_id, 0.0)),
            )
            useful_heal_hp = min(immediate_heal_hp, max(0.0, member.missing_hp))
            if useful_heal_hp <= 0.0:
                continue
            if agent_id in direct_primary_targets:
                return True
            projected_health_fraction = (
                member.health + useful_heal_hp / member.maximum_health
            )
            if projected_health_fraction > COMBAT_CRITICAL_HEALTH_THRESHOLD:
                return True
        return False

    def _revalidate_lifesaving_candidate(
        self,
        context: _CombatContext,
        immediate_effects: dict[int, float],
        direct_primary_targets: frozenset[int],
        incidental_target_validator: Callable[[int], bool] | None = None,
    ) -> bool:
        for agent_id, raw_heal_hp in immediate_effects.items():
            if (
                agent_id not in direct_primary_targets
                and incidental_target_validator is not None
                and not incidental_target_validator(agent_id)
            ):
                continue
            member = context.party_by_id.get(agent_id)
            if member is None or member.maximum_health <= 0.0:
                continue
            try:
                if (
                    not Agent.IsValid(agent_id)
                    or not Routines.Party.IsPartyMember(agent_id)
                    or not Routines.Checks.Agents.IsAlive(agent_id)
                ):
                    continue
                current_health = float(Routines.Checks.Agents.GetHealth(agent_id))
                maximum_health = float(Agent.GetMaxHealth(agent_id) or 0.0)
            except Exception:
                continue
            if (
                not math.isfinite(current_health)
                or not math.isfinite(maximum_health)
                or maximum_health <= 0.0
            ):
                continue
            current_health = max(0.0, min(1.0, current_health))
            useful_heal_hp = min(
                max(0.0, float(raw_heal_hp)),
                maximum_health * max(0.0, 1.0 - current_health),
            )
            if (
                useful_heal_hp <= 0.0
                or current_health > COMBAT_CRITICAL_HEALTH_THRESHOLD
            ):
                continue
            if agent_id in direct_primary_targets:
                return True
            projected_health_fraction = current_health + useful_heal_hp / maximum_health
            if projected_health_fraction > COMBAT_CRITICAL_HEALTH_THRESHOLD:
                return True
        return False

    def _is_currently_within_earshot(
        self,
        source_agent_id: int,
        target_agent_id: int,
    ) -> bool:
        try:
            source_position = self._coerce_position(Agent.GetXY(source_agent_id))
            target_position = self._coerce_position(Agent.GetXY(target_agent_id))
        except Exception:
            return False
        if source_position is None or target_position is None:
            return False
        try:
            return (
                float(Utils.Distance(source_position, target_position))
                <= Range.Earshot.value
            )
        except Exception:
            return False

    def _get_energy_spend_fraction(
        self,
        context: _CombatContext,
        skill_id: int,
    ) -> float:
        if context.current_energy <= 0.0:
            return 1.0
        skill_state = context.skill_states.get(skill_id)
        if skill_state is None:
            return 1.0
        return max(
            0.0,
            min(1.0, skill_state.energy_cost / context.current_energy),
        )

    def _revalidate_party_target(
        self,
        context: _CombatContext,
        skill_id: int,
        target_agent_id: int,
        health_threshold: float,
        *,
        other_ally: bool = False,
        strict_less: bool = False,
        minimum_health_drop: float = 0.0,
        absent_effect_id: int = 0,
    ) -> bool:
        if not target_agent_id or not self._is_castable(skill_id):
            return False
        if not Agent.IsValid(target_agent_id):
            return False
        if not Routines.Party.IsPartyMember(target_agent_id):
            return False
        if not Routines.Checks.Agents.IsAlive(target_agent_id):
            return False
        if other_ally and target_agent_id == context.player_id:
            return False
        current_health = float(Routines.Checks.Agents.GetHealth(target_agent_id))
        if strict_less:
            if current_health >= health_threshold:
                return False
        elif current_health > health_threshold:
            return False
        if minimum_health_drop > 0.0:
            member = context.party_by_id.get(target_agent_id)
            if member is None or member.recent_health_drop < minimum_health_drop:
                return False
        if absent_effect_id and self._has_effect_fresh(
            target_agent_id,
            absent_effect_id,
            context=context,
        ):
            return False
        try:
            distance = Utils.Distance(Player.GetXY(), Agent.GetXY(target_agent_id))
        except Exception:
            return False
        return distance <= Range.Spellcast.value

    def _fresh_policy_context(
        self,
        context: _CombatContext,
    ) -> tuple[_CombatContext, frozenset[int]] | None:
        try:
            tick_ms = int(PySystem.get_tick_count64())
            health_monitor = (
                self.UpdatePartyHealthMonitor(
                    sample_interval_ms=150,
                    window_ms=1000,
                    force=True,
                )
                or {}
            )
        except Exception:
            return None

        actual_party_ids = self._get_actual_party_ids()
        if not actual_party_ids:
            return None

        fresh_states: dict[int, tuple[float, float, float, bool, bool]] = {}
        for agent_id in actual_party_ids:
            try:
                if not Agent.IsValid(agent_id):
                    continue
                if not Routines.Checks.Agents.IsAlive(agent_id):
                    continue
                health = float(Routines.Checks.Agents.GetHealth(agent_id))
                maximum_health = float(Agent.GetMaxHealth(agent_id) or 0.0)
            except Exception:
                return None
            if (
                not math.isfinite(health)
                or not math.isfinite(maximum_health)
                or maximum_health <= 0.0
            ):
                return None

            monitor_state = health_monitor.get(agent_id)
            if monitor_state is None:
                return None
            try:
                raw_drop = monitor_state.get("drop")
                if raw_drop is None:
                    return None
                recent_health_drop = float(raw_drop)
            except Exception:
                return None
            if not math.isfinite(recent_health_drop):
                return None

            normalized_health = max(0.0, min(1.0, health))
            normalized_drop = max(0.0, min(1.0, recent_health_drop))
            health_is_recovering = self._health_trend_is_recovering(
                agent_id,
                tick_ms,
                normalized_health,
            )
            health_is_falling = self._read_health_trend_state(
                agent_id,
                tick_ms,
                normalized_health,
            )
            fresh_states[agent_id] = (
                normalized_health,
                maximum_health,
                normalized_drop,
                health_is_falling,
                health_is_recovering,
            )

        for member in context.party_members:
            if member.valid and member.alive and member.agent_id not in fresh_states:
                return None
        if not fresh_states:
            return None

        fresh_members: list[_PartyMemberSnapshot] = []
        for member in context.party_members:
            state = fresh_states.get(member.agent_id)
            if state is None:
                fresh_members.append(member)
                continue
            (
                health,
                maximum_health,
                recent_health_drop,
                health_is_falling,
                health_is_recovering,
            ) = state
            fresh_members.append(
                replace(
                    member,
                    health=health,
                    maximum_health=maximum_health,
                    missing_hp=maximum_health * max(0.0, 1.0 - health),
                    recent_health_drop=recent_health_drop,
                    health_is_falling=health_is_falling,
                    is_critical=health <= COMBAT_CRITICAL_HEALTH_THRESHOLD,
                    is_pressure_target=(
                        recent_health_drop >= COMBAT_PRESSURE_DROP_THRESHOLD
                    ),
                    is_aegis_spike_target=(
                        recent_health_drop >= AEGIS_PRESSURE_DROP_THRESHOLD
                    ),
                    is_injured=health < 1.0,
                    health_is_recovering=health_is_recovering,
                )
            )

        fresh_members_tuple = tuple(fresh_members)
        fresh_party_by_id = {member.agent_id: member for member in fresh_members_tuple}
        critical_ids = tuple(
            agent_id
            for agent_id, state in fresh_states.items()
            if state[0] <= COMBAT_CRITICAL_HEALTH_THRESHOLD
        )
        pressure_ids = tuple(
            agent_id
            for agent_id, state in fresh_states.items()
            if state[2] >= COMBAT_PRESSURE_DROP_THRESHOLD
        )
        aegis_actionable_ids = tuple(
            agent_id
            for agent_id, state in fresh_states.items()
            if state[2] >= AEGIS_PRESSURE_DROP_THRESHOLD
        )
        injured_ids = tuple(
            agent_id for agent_id, state in fresh_states.items() if state[0] < 1.0
        )
        current_party_player_ids = frozenset(self._get_current_party_player_ids())
        if not current_party_player_ids:
            current_party_player_ids = context.party_player_ids

        fresh_context = replace(
            context,
            tick_ms=tick_ms,
            party_members=fresh_members_tuple,
            party_by_id=fresh_party_by_id,
            critical_ids=critical_ids,
            pressure_ids=pressure_ids,
            aegis_actionable_ids=aegis_actionable_ids,
            injured_ids=injured_ids,
            critical_missing_hp=sum(
                state[1] * max(0.0, 1.0 - state[0])
                for state in fresh_states.values()
                if state[0] <= COMBAT_CRITICAL_HEALTH_THRESHOLD
            ),
            pressure_missing_hp=sum(
                state[1] * max(0.0, 1.0 - state[0])
                for state in fresh_states.values()
                if state[2] >= COMBAT_PRESSURE_DROP_THRESHOLD
            ),
            injured_missing_hp=sum(
                state[1] * max(0.0, 1.0 - state[0])
                for state in fresh_states.values()
                if state[0] < 1.0
            ),
            distance_cache={},
            effect_summary_cache={},
            effect_presence_cache={},
            party_player_ids=current_party_player_ids,
        )
        return fresh_context, self._patient_party_emergency_ids(fresh_context)

    def _revalidate_patient_candidate(
        self,
        context: _CombatContext,
        target_agent_id: int,
        delayed_heal_hp: float = 0.0,
    ) -> bool:
        fresh_policy = self._fresh_policy_context(context)
        if fresh_policy is None:
            self._diagnostic_record_rejection(
                context,
                target_agent_id,
                PATIENT_SPIRIT_ID,
                "fresh_policy_unavailable",
            )
            return False
        fresh_context, emergency_ids = fresh_policy
        target = fresh_context.party_by_id.get(target_agent_id)
        if target is None:
            self._diagnostic_record_rejection(
                context,
                target_agent_id,
                PATIENT_SPIRIT_ID,
                "target_missing",
            )
            return False
        if any(agent_id != target_agent_id for agent_id in emergency_ids):
            self._diagnostic_log_patient_party_blockers(
                fresh_context,
                target_agent_id,
            )
            self._diagnostic_record_rejection(
                context,
                target_agent_id,
                PATIENT_SPIRIT_ID,
                "party_emergency",
            )
            return False
        safety_rejection = self._patient_safety_rejection(
            fresh_context,
            target,
            delayed_heal_hp,
        )
        if safety_rejection:
            if safety_rejection == "party_emergency":
                self._diagnostic_log_patient_party_blockers(
                    fresh_context,
                    target_agent_id,
                )
            self._diagnostic_record_rejection(
                context,
                target_agent_id,
                PATIENT_SPIRIT_ID,
                safety_rejection,
            )
            return False
        return self._revalidate_party_target(
            fresh_context,
            PATIENT_SPIRIT_ID,
            target_agent_id,
            _PATIENT_HEALTH_CEILING,
            absent_effect_id=PATIENT_SPIRIT_ID,
        )

    def _revalidate_seed_candidate(
        self,
        context: _CombatContext,
        target_agent_id: int,
    ) -> bool:
        fresh_policy = self._fresh_policy_context(context)
        if fresh_policy is None:
            self._diagnostic_record_rejection(
                context,
                target_agent_id,
                SEED_OF_LIFE_ID,
                "fresh_policy_unavailable",
            )
            return False
        fresh_context, _ = fresh_policy
        target = fresh_context.party_by_id.get(target_agent_id)
        if target is None:
            self._diagnostic_record_rejection(
                context,
                target_agent_id,
                SEED_OF_LIFE_ID,
                "target_missing",
            )
            return False
        nearby_enemy_count: int | None = None
        if (
            not target.is_self
            and not target.is_critical
            and not target.health_is_falling
            and target.recent_health_drop >= _SEED_LARGE_DROP
            and len(fresh_context.pressure_ids) <= 1
            and not any(
                agent_id != target_agent_id for agent_id in fresh_context.critical_ids
            )
        ):
            nearby_enemy_count = self._get_current_nearby_enemy_count()
        spike_rejection = self._seed_spike_rejection(
            fresh_context,
            target,
            nearby_enemy_count=nearby_enemy_count,
        )
        if spike_rejection:
            self._diagnostic_record_rejection(
                context,
                target_agent_id,
                SEED_OF_LIFE_ID,
                spike_rejection,
            )
            return False
        return self._revalidate_party_target(
            fresh_context,
            SEED_OF_LIFE_ID,
            target_agent_id,
            _SEED_HEALTH_CEILING,
            other_ally=True,
            minimum_health_drop=_SEED_MIN_DROP,
            absent_effect_id=SEED_OF_LIFE_ID,
        )

    def _revalidate_aegis_candidate(self, context: _CombatContext) -> bool:
        if not self._is_castable(AEGIS_ID):
            return False
        if not context.aegis_actionable_ids:
            return False
        shared_accounts = self._get_same_party_shared_accounts()
        party_player_ids = self._get_current_party_player_ids()
        if self._has_effect_fresh(
            context.player_id,
            AEGIS_ID,
            shared_accounts=shared_accounts,
            party_player_ids=party_player_ids,
            context=context,
        ):
            return False

        if context.nearby_attacking_martial_enemy_count > 0:
            candidate_ids = context.pressure_ids
            minimum_health_drop = COMBAT_PRESSURE_DROP_THRESHOLD
        elif context.nearby_martial_enemy_count > 0:
            candidate_ids = context.injured_ids
            minimum_health_drop = 0.0
        else:
            return False

        for agent_id in candidate_ids:
            member = context.party_by_id.get(agent_id)
            if member is None or not member.alive:
                continue
            if member.recent_health_drop < minimum_health_drop:
                continue
            if (
                self._context_distance(context, context.player_id, agent_id)
                > Range.Earshot.value
            ):
                continue
            if not self._has_effect_fresh(
                agent_id,
                AEGIS_ID,
                shared_accounts=shared_accounts,
                party_player_ids=party_player_ids,
                context=context,
            ):
                return True
        return False

    @staticmethod
    def _select_candidate(
        candidates: list[_CombatActionCandidate],
    ) -> _CombatActionCandidate | None:
        if not candidates:
            return None

        def survival_key(
            candidate: _CombatActionCandidate,
        ) -> tuple[int, float, float, int]:
            current_health = max(0.0, min(1.0, float(candidate.target_health)))
            recent_drop = max(
                0.0,
                min(1.0, float(candidate.target_recent_health_drop)),
            )
            survival_risk = max(
                0.0,
                min(
                    1.0,
                    (1.0 - current_health) + recent_drop * _SURVIVAL_PRESSURE_WEIGHT,
                ),
            )
            critical = int(
                candidate.urgency == _CombatUrgency.CRITICAL_IMMEDIATE
                or current_health <= COMBAT_CRITICAL_HEALTH_THRESHOLD
            )
            urgent_tiebreak = int(candidate.urgency == _CombatUrgency.URGENT_REACTIVE)
            return critical, survival_risk, recent_drop, urgent_tiebreak

        return max(
            candidates,
            key=lambda candidate: (
                *survival_key(candidate),
                candidate.primary_value,
                candidate.secondary_value,
                -candidate.time_to_primary_effect,
                -candidate.energy_spend_fraction,
                -candidate.evaluator_order,
                -candidate.target_order,
                -candidate.target_agent_id,
            ),
        )

    @classmethod
    def _select_evaluator_candidates(
        cls,
        candidates: list[_CombatActionCandidate],
    ) -> list[_CombatActionCandidate]:
        ordinary_candidate = cls._select_candidate(candidates)
        if ordinary_candidate is None:
            return []
        rescue_candidate = cls._select_candidate(
            [candidate for candidate in candidates if candidate.preempts_high_cure]
        )
        if rescue_candidate is None or rescue_candidate is ordinary_candidate:
            return [ordinary_candidate]
        return [ordinary_candidate, rescue_candidate]

    def _execute_combat_candidate(
        self,
        candidate: _CombatActionCandidate,
        *,
        branch: str = "unknown",
    ):
        try:
            final_revalidation = candidate.revalidate()
        except Exception as exc:
            if self._diagnostic_candidate_is_relevant(candidate):
                _diagnostic_log(
                    "kind=revalidate "
                    f"tick={self._diagnostic_tick()} run=combat stage=final "
                    f"branch={branch} skill={self._diagnostic_skill_label(candidate.skill_id)} "
                    f"skill_id={candidate.skill_id} target={candidate.target_agent_id} "
                    f"result=exception:{self._diagnostic_safe_label(type(exc).__name__)}"
                )
            raise

        self._diagnostic_log_revalidation(
            candidate,
            stage="final",
            result=final_revalidation,
        )
        if not final_revalidation:
            return False

        if self._diagnostic_candidate_is_relevant(candidate):
            _diagnostic_log(
                "kind=execution "
                f"tick={self._diagnostic_tick()} run=combat stage=begin "
                f"branch={branch} skill={self._diagnostic_skill_label(candidate.skill_id)} "
                f"skill_id={candidate.skill_id} target={candidate.target_agent_id}"
            )
        try:
            result = yield from candidate.execute()
        except Exception as exc:
            if self._diagnostic_candidate_is_relevant(candidate):
                _diagnostic_log(
                    "kind=execution "
                    f"tick={self._diagnostic_tick()} run=combat stage=result "
                    f"branch={branch} skill={self._diagnostic_skill_label(candidate.skill_id)} "
                    f"skill_id={candidate.skill_id} target={candidate.target_agent_id} "
                    f"result=exception:{self._diagnostic_safe_label(type(exc).__name__)}"
                )
            raise
        if self._diagnostic_candidate_is_relevant(candidate):
            _diagnostic_log(
                "kind=execution "
                f"tick={self._diagnostic_tick()} run=combat stage=result "
                f"branch={branch} skill={self._diagnostic_skill_label(candidate.skill_id)} "
                f"skill_id={candidate.skill_id} target={candidate.target_agent_id} "
                f"result={self._diagnostic_flag(bool(result))}"
            )
        return result

    def _evaluate_healing_burst(
        self,
        context: _CombatContext,
        evaluator_order: int,
    ) -> list[_CombatActionCandidate]:
        target_ids = self._diagnostic_target_ids(context)
        skill_state = context.skill_states.get(HEALING_BURST_ID)
        if self._diagnostic_record_skill_state_rejection(
            context,
            HEALING_BURST_ID,
            target_ids,
        ):
            return []
        if skill_state is None or not skill_state.castable:
            return []

        health_threshold = self._health_threshold(HEALING_BURST_ID, 0.80)
        base_heal = self._scaled_runtime_value(
            HEALING_BURST_ID,
            context.healing_prayers_rank,
            skill_snapshot=skill_state,
        )
        divine_favor_heal = self._divine_favor_heal(context.divine_favor_rank)
        eligible_targets: list[_PartyMemberSnapshot] = []
        for member in context.party_members:
            if member.health > health_threshold:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    HEALING_BURST_ID,
                    "health_threshold",
                )
                continue
            if (
                self._context_distance(context, context.player_id, member.agent_id)
                > Range.Spellcast.value
            ):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    HEALING_BURST_ID,
                    "out_of_range",
                )
                continue
            eligible_targets.append(member)
        if not eligible_targets:
            return []

        candidates: list[_CombatActionCandidate] = []
        for anchor in eligible_targets:
            immediate_effects: dict[int, float] = {
                anchor.agent_id: self._predicted_heal_hp(
                    base_heal + divine_favor_heal,
                )
            }
            for member in context.party_members:
                if member.agent_id == anchor.agent_id:
                    continue
                if (
                    self._context_distance(context, anchor.agent_id, member.agent_id)
                    <= Range.Earshot.value
                ):
                    immediate_effects[member.agent_id] = self._predicted_heal_hp(
                        divine_favor_heal
                    )

            conservative_effects = dict(immediate_effects)
            urgency = self._get_combat_urgency(
                context,
                immediate_effects,
                conservative_effects,
            )
            if urgency == _CombatUrgency.MAINTENANCE:
                self._diagnostic_record_rejection(
                    context,
                    anchor.agent_id,
                    HEALING_BURST_ID,
                    "no_useful_healing",
                )
                continue
            primary_value, secondary_value = self._get_candidate_values(
                context,
                urgency,
                immediate_effects,
                conservative_effects,
            )
            candidates.append(
                _CombatActionCandidate(
                    skill_id=HEALING_BURST_ID,
                    target_agent_id=anchor.agent_id,
                    urgency=urgency,
                    primary_value=primary_value,
                    secondary_value=secondary_value,
                    time_to_primary_effect=skill_state.activation_seconds,
                    energy_spend_fraction=self._get_energy_spend_fraction(
                        context,
                        HEALING_BURST_ID,
                    ),
                    evaluator_order=evaluator_order,
                    target_order=anchor.party_order,
                    preempts_high_cure=self._is_lifesaving_candidate(
                        context,
                        immediate_effects,
                        {anchor.agent_id},
                    ),
                    revalidate=lambda target_agent_id=anchor.agent_id, threshold=health_threshold: (
                        self._revalidate_party_target(
                            context,
                            HEALING_BURST_ID,
                            target_agent_id,
                            threshold,
                        )
                    ),
                    rescue_revalidate=lambda effects=dict(immediate_effects), direct_targets=frozenset({anchor.agent_id}), anchor_agent_id=anchor.agent_id: (
                        self._revalidate_lifesaving_candidate(
                            context,
                            effects,
                            direct_targets,
                            incidental_target_validator=lambda target_agent_id, source_agent_id=anchor_agent_id: (
                                self._is_currently_within_earshot(
                                    source_agent_id,
                                    target_agent_id,
                                )
                            ),
                        )
                    ),
                    execute=lambda target_agent_id=anchor.agent_id: (
                        self.CastSkillIDAndRestoreTarget(
                            HEALING_BURST_ID,
                            target_agent_id,
                        )
                    ),
                    diagnostic_reason="Healing Burst direct heal with party-wide Divine Favor value",
                    target_health=anchor.health,
                    target_recent_health_drop=anchor.recent_health_drop,
                )
            )

        return self._select_evaluator_candidates(candidates)

    def _evaluate_dwaynas_kiss(
        self,
        context: _CombatContext,
        evaluator_order: int,
    ) -> list[_CombatActionCandidate]:
        target_ids = self._diagnostic_target_ids(context)
        skill_state = context.skill_states.get(DWAYNAS_KISS_ID)
        if self._diagnostic_record_skill_state_rejection(
            context,
            DWAYNAS_KISS_ID,
            target_ids,
        ):
            return []
        if skill_state is None or not skill_state.castable:
            return []

        health_threshold = self._health_threshold(DWAYNAS_KISS_ID, 0.80)
        eligible_targets: list[_PartyMemberSnapshot] = []
        for member in context.party_members:
            if member.is_self:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    DWAYNAS_KISS_ID,
                    "self_not_legal",
                )
                continue
            if member.health > health_threshold:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    DWAYNAS_KISS_ID,
                    "health_threshold",
                )
                continue
            if (
                self._context_distance(context, context.player_id, member.agent_id)
                > Range.Spellcast.value
            ):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    DWAYNAS_KISS_ID,
                    "out_of_range",
                )
                continue
            eligible_targets.append(member)
        if not eligible_targets:
            return []

        base_heal = self._scaled_runtime_value(
            DWAYNAS_KISS_ID,
            context.healing_prayers_rank,
            skill_snapshot=skill_state,
        )
        bonus_per_effect = self._scaled_runtime_value(
            DWAYNAS_KISS_ID,
            context.healing_prayers_rank,
            bonus=True,
            skill_snapshot=skill_state,
        )
        divine_favor_heal = self._divine_favor_heal(context.divine_favor_rank)
        candidates: list[_CombatActionCandidate] = []
        for target in eligible_targets:
            effect_summary = self._get_effect_summary(context, target.agent_id)
            heal_amount = (
                base_heal
                + bonus_per_effect * effect_summary.supported_count
                + divine_favor_heal
            )
            immediate_effects = {target.agent_id: self._predicted_heal_hp(heal_amount)}
            urgency = self._get_combat_urgency(
                context,
                immediate_effects,
                immediate_effects,
            )
            if urgency == _CombatUrgency.MAINTENANCE:
                self._diagnostic_record_rejection(
                    context,
                    target.agent_id,
                    DWAYNAS_KISS_ID,
                    "no_useful_healing",
                )
                continue
            primary_value, secondary_value = self._get_candidate_values(
                context,
                urgency,
                immediate_effects,
                immediate_effects,
            )
            candidates.append(
                _CombatActionCandidate(
                    skill_id=DWAYNAS_KISS_ID,
                    target_agent_id=target.agent_id,
                    urgency=urgency,
                    primary_value=primary_value,
                    secondary_value=secondary_value,
                    time_to_primary_effect=skill_state.activation_seconds,
                    energy_spend_fraction=self._get_energy_spend_fraction(
                        context,
                        DWAYNAS_KISS_ID,
                    ),
                    evaluator_order=evaluator_order,
                    target_order=target.party_order,
                    preempts_high_cure=self._is_lifesaving_candidate(
                        context,
                        immediate_effects,
                        {target.agent_id},
                    ),
                    revalidate=lambda target_agent_id=target.agent_id, threshold=health_threshold: (
                        self._revalidate_party_target(
                            context,
                            DWAYNAS_KISS_ID,
                            target_agent_id,
                            threshold,
                            other_ally=True,
                        )
                    ),
                    rescue_revalidate=lambda effects=dict(immediate_effects), direct_targets=frozenset({target.agent_id}): (
                        self._revalidate_lifesaving_candidate(
                            context,
                            effects,
                            direct_targets,
                        )
                    ),
                    execute=lambda target_agent_id=target.agent_id: (
                        self.CastSkillIDAndRestoreTarget(
                            DWAYNAS_KISS_ID,
                            target_agent_id,
                        )
                    ),
                    diagnostic_reason=(
                        "Dwayna's Kiss with "
                        f"{effect_summary.supported_count} justified enchantment/hex effects "
                        f"({effect_summary.confidence})"
                    ),
                    target_health=target.health,
                    target_recent_health_drop=target.recent_health_drop,
                )
            )

        return self._select_evaluator_candidates(candidates)

    def _evaluate_signet_of_rejuvenation(
        self,
        context: _CombatContext,
        evaluator_order: int,
    ) -> list[_CombatActionCandidate]:
        target_ids = self._diagnostic_target_ids(context)
        skill_state = context.skill_states.get(SIGNET_OF_REJUVENATION_ID)
        if self._diagnostic_record_skill_state_rejection(
            context,
            SIGNET_OF_REJUVENATION_ID,
            target_ids,
        ):
            return []
        if skill_state is None or not skill_state.castable:
            return []

        health_threshold = self._health_threshold(SIGNET_OF_REJUVENATION_ID, 0.80)
        eligible_targets: list[_PartyMemberSnapshot] = []
        for member in context.party_members:
            if member.health > health_threshold:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SIGNET_OF_REJUVENATION_ID,
                    "health_threshold",
                )
                continue
            if (
                self._context_distance(context, context.player_id, member.agent_id)
                > Range.Spellcast.value
            ):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SIGNET_OF_REJUVENATION_ID,
                    "out_of_range",
                )
                continue
            eligible_targets.append(member)
        if not eligible_targets:
            return []

        candidates: list[_CombatActionCandidate] = []
        for target in eligible_targets:
            heal_amount = self._scaled_runtime_value(
                SIGNET_OF_REJUVENATION_ID,
                context.healing_prayers_rank,
                skill_snapshot=skill_state,
            )
            if self._has_reliable_activity(context, target):
                heal_amount += self._scaled_runtime_value(
                    SIGNET_OF_REJUVENATION_ID,
                    context.healing_prayers_rank,
                    bonus=True,
                    skill_snapshot=skill_state,
                )
            immediate_effects = {target.agent_id: self._predicted_heal_hp(heal_amount)}
            urgency = self._get_combat_urgency(
                context,
                immediate_effects,
                immediate_effects,
            )
            if urgency == _CombatUrgency.MAINTENANCE:
                self._diagnostic_record_rejection(
                    context,
                    target.agent_id,
                    SIGNET_OF_REJUVENATION_ID,
                    "no_useful_healing",
                )
                continue
            primary_value, secondary_value = self._get_candidate_values(
                context,
                urgency,
                immediate_effects,
                immediate_effects,
            )
            candidates.append(
                _CombatActionCandidate(
                    skill_id=SIGNET_OF_REJUVENATION_ID,
                    target_agent_id=target.agent_id,
                    urgency=urgency,
                    primary_value=primary_value,
                    secondary_value=secondary_value,
                    time_to_primary_effect=skill_state.activation_seconds,
                    energy_spend_fraction=self._get_energy_spend_fraction(
                        context,
                        SIGNET_OF_REJUVENATION_ID,
                    ),
                    evaluator_order=evaluator_order,
                    target_order=target.party_order,
                    preempts_high_cure=self._is_lifesaving_candidate(
                        context,
                        immediate_effects,
                        {target.agent_id},
                    ),
                    revalidate=lambda target_agent_id=target.agent_id, threshold=health_threshold: (
                        self._revalidate_party_target(
                            context,
                            SIGNET_OF_REJUVENATION_ID,
                            target_agent_id,
                            threshold,
                        )
                    ),
                    rescue_revalidate=lambda effects=dict(immediate_effects), direct_targets=frozenset({target.agent_id}): (
                        self._revalidate_lifesaving_candidate(
                            context,
                            effects,
                            direct_targets,
                        )
                    ),
                    execute=lambda target_agent_id=target.agent_id: (
                        self.CastSkillIDAndRestoreTarget(
                            SIGNET_OF_REJUVENATION_ID,
                            target_agent_id,
                        )
                    ),
                    diagnostic_reason="Signet of Rejuvenation with observed active/casting bonus only",
                    target_health=target.health,
                    target_recent_health_drop=target.recent_health_drop,
                )
            )

        return self._select_evaluator_candidates(candidates)

    def _evaluate_patient_spirit(
        self,
        context: _CombatContext,
        evaluator_order: int,
    ) -> list[_CombatActionCandidate]:
        target_ids = self._diagnostic_target_ids(context)
        skill_state = context.skill_states.get(PATIENT_SPIRIT_ID)
        if self._diagnostic_record_skill_state_rejection(
            context,
            PATIENT_SPIRIT_ID,
            target_ids,
        ):
            return []
        if skill_state is None or not skill_state.castable:
            return []

        health_threshold = _PATIENT_HEALTH_CEILING
        immediate_heal = self._predicted_heal_hp(
            self._divine_favor_heal(context.divine_favor_rank)
        )
        delayed_heal = self._predicted_heal_hp(
            self._scaled_runtime_value(
                PATIENT_SPIRIT_ID,
                context.healing_prayers_rank,
                skill_snapshot=skill_state,
            )
        )
        eligible_targets: list[_PartyMemberSnapshot] = []
        for member in context.party_members:
            if member.health > health_threshold:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    PATIENT_SPIRIT_ID,
                    "health_threshold",
                )
                continue
            if (
                self._context_distance(context, context.player_id, member.agent_id)
                > Range.Spellcast.value
            ):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    PATIENT_SPIRIT_ID,
                    "out_of_range",
                )
                continue
            effect_rejection = self._diagnostic_effect_rejection(
                context,
                member.agent_id,
                PATIENT_SPIRIT_ID,
            )
            if effect_rejection:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    PATIENT_SPIRIT_ID,
                    effect_rejection,
                )
                continue
            if not self._has_verified_effect_absence(
                context,
                member.agent_id,
                PATIENT_SPIRIT_ID,
            ):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    PATIENT_SPIRIT_ID,
                    "effect_state_unknown",
                )
                continue
            if self._has_effect_cached(context, member.agent_id, PATIENT_SPIRIT_ID):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    PATIENT_SPIRIT_ID,
                    "effect_present",
                )
                continue
            safety_rejection = self._patient_safety_rejection(
                context,
                member,
                delayed_heal,
            )
            if safety_rejection:
                if safety_rejection == "party_emergency":
                    self._diagnostic_log_patient_party_blockers(
                        context,
                        member.agent_id,
                    )
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    PATIENT_SPIRIT_ID,
                    safety_rejection,
                )
                continue
            eligible_targets.append(member)
        if not eligible_targets:
            return []

        candidates: list[_CombatActionCandidate] = []
        for target in eligible_targets:
            immediate_effects = {target.agent_id: immediate_heal}
            conservative_effects = {target.agent_id: immediate_heal + delayed_heal}
            urgency = self._get_combat_urgency(
                context,
                immediate_effects,
                conservative_effects,
            )
            if urgency == _CombatUrgency.MAINTENANCE:
                self._diagnostic_record_rejection(
                    context,
                    target.agent_id,
                    PATIENT_SPIRIT_ID,
                    "no_useful_healing",
                )
                continue
            primary_value, secondary_value = self._get_candidate_values(
                context,
                urgency,
                immediate_effects,
                conservative_effects,
            )
            delayed_time = 2.0 if urgency != _CombatUrgency.CRITICAL_IMMEDIATE else 0.0
            candidates.append(
                _CombatActionCandidate(
                    skill_id=PATIENT_SPIRIT_ID,
                    target_agent_id=target.agent_id,
                    urgency=urgency,
                    primary_value=primary_value,
                    secondary_value=secondary_value,
                    time_to_primary_effect=skill_state.activation_seconds
                    + delayed_time,
                    energy_spend_fraction=self._get_energy_spend_fraction(
                        context,
                        PATIENT_SPIRIT_ID,
                    ),
                    evaluator_order=evaluator_order,
                    target_order=target.party_order,
                    preempts_high_cure=self._is_lifesaving_candidate(
                        context,
                        immediate_effects,
                        set(),
                    ),
                    revalidate=lambda target_agent_id=target.agent_id, delayed_heal_hp=delayed_heal: (
                        self._revalidate_patient_candidate(
                            context,
                            target_agent_id,
                            delayed_heal_hp,
                        )
                    ),
                    rescue_revalidate=lambda effects=dict(immediate_effects): (
                        self._revalidate_lifesaving_candidate(
                            context,
                            effects,
                            frozenset(),
                        )
                    ),
                    execute=lambda target_agent_id=target.agent_id: (
                        self.CastSkillIDAndRestoreTarget(
                            PATIENT_SPIRIT_ID,
                            target_agent_id,
                        )
                    ),
                    diagnostic_reason="Patient Spirit delayed value with immediate Divine Favor only for rescue semantics",
                    target_health=target.health,
                    target_recent_health_drop=target.recent_health_drop,
                )
            )

        return self._select_evaluator_candidates(candidates)

    def _evaluate_seed_of_life(
        self,
        context: _CombatContext,
        evaluator_order: int,
    ) -> list[_CombatActionCandidate]:
        target_ids = self._diagnostic_target_ids(context)
        skill_state = context.skill_states.get(SEED_OF_LIFE_ID)
        if self._diagnostic_record_skill_state_rejection(
            context,
            SEED_OF_LIFE_ID,
            target_ids,
        ):
            return []
        if skill_state is None or not skill_state.castable:
            return []

        health_threshold = min(
            self._health_threshold(SEED_OF_LIFE_ID, 0.80),
            _SEED_HEALTH_CEILING,
        )
        eligible_targets: list[_PartyMemberSnapshot] = []
        for member in context.party_members:
            spike_rejection = self._seed_spike_rejection(context, member)
            if spike_rejection:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SEED_OF_LIFE_ID,
                    spike_rejection,
                )
                continue
            if member.health > health_threshold:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SEED_OF_LIFE_ID,
                    "health_threshold",
                )
                continue
            if (
                self._context_distance(context, context.player_id, member.agent_id)
                > Range.Spellcast.value
            ):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SEED_OF_LIFE_ID,
                    "out_of_range",
                )
                continue
            effect_rejection = self._diagnostic_effect_rejection(
                context,
                member.agent_id,
                SEED_OF_LIFE_ID,
            )
            if effect_rejection:
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SEED_OF_LIFE_ID,
                    effect_rejection,
                )
                continue
            if not self._has_verified_effect_absence(
                context,
                member.agent_id,
                SEED_OF_LIFE_ID,
            ):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SEED_OF_LIFE_ID,
                    "effect_state_unknown",
                )
                continue
            if self._has_effect_cached(context, member.agent_id, SEED_OF_LIFE_ID):
                self._diagnostic_record_rejection(
                    context,
                    member.agent_id,
                    SEED_OF_LIFE_ID,
                    "effect_present",
                )
                continue
            eligible_targets.append(member)
        if not eligible_targets:
            return []

        def seed_target_tier(member: _PartyMemberSnapshot) -> int:
            if member.is_melee and member.is_martial:
                return 0
            if member.is_martial:
                return 1
            return 2

        eligible_targets.sort(
            key=lambda member: (
                -member.recent_health_drop,
                -int(member.health_is_falling),
                member.health,
                seed_target_tier(member),
                member.party_order,
            )
        )
        target = eligible_targets[0]
        immediate_heal = self._predicted_heal_hp(
            self._divine_favor_heal(context.divine_favor_rank)
        )
        conservative_trigger = {
            member.agent_id: self._predicted_heal_hp(
                SEED_TRIGGER_HEAL_PER_RANK * max(0, context.divine_favor_rank)
            )
            for member in context.party_members
        }
        immediate_effects = {target.agent_id: immediate_heal}
        conservative_effects = dict(conservative_trigger)
        conservative_effects[target.agent_id] = (
            conservative_effects.get(target.agent_id, 0.0) + immediate_heal
        )
        urgency = self._get_combat_urgency(
            context,
            immediate_effects,
            conservative_effects,
        )
        if urgency == _CombatUrgency.MAINTENANCE:
            self._diagnostic_record_rejection(
                context,
                target.agent_id,
                SEED_OF_LIFE_ID,
                "no_useful_healing",
            )
            return []
        primary_value, secondary_value = self._get_candidate_values(
            context,
            urgency,
            immediate_effects,
            conservative_effects,
        )
        return [
            _CombatActionCandidate(
                skill_id=SEED_OF_LIFE_ID,
                target_agent_id=target.agent_id,
                urgency=urgency,
                primary_value=primary_value,
                secondary_value=secondary_value,
                time_to_primary_effect=skill_state.activation_seconds,
                energy_spend_fraction=self._get_energy_spend_fraction(
                    context,
                    SEED_OF_LIFE_ID,
                ),
                evaluator_order=evaluator_order,
                target_order=target.party_order,
                preempts_high_cure=self._is_lifesaving_candidate(
                    context,
                    immediate_effects,
                    set(),
                ),
                revalidate=lambda target_agent_id=target.agent_id: (
                    self._revalidate_seed_candidate(
                        context,
                        target_agent_id,
                    )
                ),
                rescue_revalidate=lambda effects=dict(immediate_effects): (
                    self._revalidate_lifesaving_candidate(
                        context,
                        effects,
                        frozenset(),
                    )
                ),
                execute=lambda target_agent_id=target.agent_id: (
                    self.CastSkillIDAndRestoreTarget(
                        SEED_OF_LIFE_ID,
                        target_agent_id,
                    )
                ),
                diagnostic_reason="Seed of Life filtered pressure target with one conservative Divine Favor trigger",
                target_health=target.health,
                target_recent_health_drop=target.recent_health_drop,
            )
        ]

    def _evaluate_aegis(
        self,
        context: _CombatContext,
        evaluator_order: int,
    ) -> list[_CombatActionCandidate]:
        skill_state = context.skill_states.get(AEGIS_ID)
        if (
            _TEMPORARY_EMERGENCY_DIAGNOSTICS_ENABLED
            and self._diagnostic_episodes
            and (skill_state is None or not skill_state.castable)
        ):
            for reason in self._diagnostic_skill_state_reasons(context, AEGIS_ID):
                self._diagnostic_record_aux_rejection(context, reason)
            return []
        if skill_state is None or not skill_state.castable:
            return []
        if not context.aegis_actionable_ids:
            self._diagnostic_record_aux_rejection(context, "insufficient_pressure")
            return []
        if self._has_effect_cached(context, context.player_id, AEGIS_ID):
            self._diagnostic_record_aux_rejection(context, "effect_present")
            return []

        pressure_targets: list[int] = []
        for agent_id in context.pressure_ids:
            if agent_id not in context.party_by_id:
                self._diagnostic_record_aux_rejection(context, "invalid_target")
                continue
            if (
                self._context_distance(context, context.player_id, agent_id)
                > Range.Earshot.value
            ):
                self._diagnostic_record_aux_rejection(context, "out_of_range")
                continue
            if self._has_effect_cached(context, agent_id, AEGIS_ID):
                self._diagnostic_record_aux_rejection(context, "effect_present")
                continue
            pressure_targets.append(agent_id)
        if not pressure_targets:
            self._diagnostic_record_aux_rejection(context, "no_pressure_target")
            return []

        pressure_coverage = len(pressure_targets) / max(1, len(context.pressure_ids))
        active_weapon_pressure = context.nearby_attacking_martial_enemy_count / max(
            1,
            context.nearby_enemy_count,
        )
        if active_weapon_pressure > 0.0:
            urgency = _CombatUrgency.URGENT_REACTIVE
            primary_value = 0.50 * pressure_coverage * active_weapon_pressure
        elif context.nearby_martial_enemy_count > 0:
            injured_targets = [
                agent_id
                for agent_id in context.injured_ids
                if self._context_distance(context, context.player_id, agent_id)
                <= Range.Earshot.value
                and not self._has_effect_cached(context, agent_id, AEGIS_ID)
            ]
            injured_coverage = len(injured_targets) / max(1, len(context.injured_ids))
            potential_weapon_pressure = context.nearby_martial_enemy_count / max(
                1,
                context.nearby_enemy_count,
            )
            urgency = _CombatUrgency.CURRENT_INJURY
            primary_value = 0.50 * injured_coverage * potential_weapon_pressure
        else:
            self._diagnostic_record_aux_rejection(context, "skill_specific_rule")
            return []

        if primary_value <= 0.0:
            self._diagnostic_record_aux_rejection(context, "no_useful_healing")
            return []
        aegis_target = context.party_by_id.get(context.player_id)
        return [
            _CombatActionCandidate(
                skill_id=AEGIS_ID,
                target_agent_id=context.player_id,
                urgency=urgency,
                primary_value=primary_value,
                secondary_value=0.0,
                time_to_primary_effect=skill_state.activation_seconds,
                energy_spend_fraction=self._get_energy_spend_fraction(
                    context,
                    AEGIS_ID,
                ),
                evaluator_order=evaluator_order,
                target_order=-1,
                preempts_high_cure=False,
                revalidate=lambda: self._revalidate_aegis_candidate(context),
                execute=lambda: self._try_aegis(list(context.aegis_actionable_ids)),
                diagnostic_reason="Aegis actionability value without Divine Favor or HIGH Cure preemption",
                target_health=aegis_target.health if aegis_target is not None else 1.0,
                target_recent_health_drop=(
                    aegis_target.recent_health_drop if aegis_target is not None else 0.0
                ),
            )
        ]

    def _evaluate_combat_candidates(
        self,
        context: _CombatContext,
    ) -> list[_CombatActionCandidate]:
        candidates: list[_CombatActionCandidate] = []
        for evaluator_order, evaluator in enumerate(self._combat_evaluators):
            candidates.extend(evaluator(context, evaluator_order))
        return candidates

    def _restore_life_cast_window_ms(self) -> int:
        activation_ms = 0
        aftercast_ms = 0
        try:
            activation_ms = int(
                max(
                    0.0,
                    float(
                        GLOBAL_CACHE.Skill.Data.GetActivation(RESTORE_LIFE_ID) or 0.0
                    ),
                )
                * 1000
            )
        except Exception:
            pass
        try:
            aftercast_ms = int(
                max(
                    0.0,
                    float(GLOBAL_CACHE.Skill.Data.GetAftercast(RESTORE_LIFE_ID) or 0.0),
                )
                * 1000
            )
        except Exception:
            pass
        return max(250, activation_ms + aftercast_ms + 100)

    def _resolve_restore_life_target(self) -> int:
        # Resolve without claiming so the exact candidate can be revalidated
        # and reserved immediately before the cast.
        return Routines.Agents.GetResurrectionTarget(
            Range.Spellcast.value,
            reserve=False,
        )

    def _claim_restore_life_target(
        self, target_agent_id: int, aftercast_delay: int
    ) -> bool:
        try:
            return (
                claim_resurrection_target(
                    [target_agent_id],
                    skill_id=RESTORE_LIFE_ID,
                    aftercast_delay=aftercast_delay,
                )
                == target_agent_id
            )
        except Exception:
            return False

    def _clear_restore_life_reservation(self, target_agent_id: int) -> None:
        # Custom builds keep failed-cast cleanup local so shared CoreLib stays unchanged.
        if target_agent_id <= 0:
            return
        try:
            email = Player.GetAccountEmail() or ""
            if not email:
                return
            group_id = int(GLOBAL_CACHE.ShMem.GetAccountGroupByEmail(email))
            GLOBAL_CACHE.ShMem.GetAllAccounts().ClearLockByOwnerKindTarget(
                email,
                int(WhiteboardLockKind.RESURRECT_TARGET),
                int(target_agent_id),
                group_id,
            )
        except Exception:
            return

    def _is_valid_restore_life_target(self, target_agent_id: int) -> bool:
        if not Agent.IsValid(target_agent_id) or not Agent.IsDead(target_agent_id):
            return False
        try:
            return (
                Utils.Distance(Player.GetXY(), Agent.GetXY(target_agent_id))
                <= Range.Spellcast.value
            )
        except Exception:
            return False

    def _try_restore_life(self):
        if not self._is_castable(RESTORE_LIFE_ID):
            return False

        cast_window_ms = self._restore_life_cast_window_ms()
        target_agent_id = self._resolve_restore_life_target()
        if (
            not target_agent_id
            or not self._is_valid_restore_life_target(target_agent_id)
            or not self._is_castable(RESTORE_LIFE_ID)
        ):
            return False

        if not self._claim_restore_life_target(target_agent_id, cast_window_ms):
            return False

        # Recheck after the late claim too: another controller or the game can
        # change the corpse before the cast helper commits the action.
        reservation_pending = True
        try:
            if not self._is_valid_restore_life_target(
                target_agent_id
            ) or not self._is_castable(RESTORE_LIFE_ID):
                return False

            cast_succeeded = yield from self.CastSkillIDAndRestoreTarget(
                RESTORE_LIFE_ID,
                target_agent_id,
                aftercast_delay=cast_window_ms,
            )
            if cast_succeeded:
                reservation_pending = False
            return cast_succeeded
        finally:
            if reservation_pending:
                self._clear_restore_life_reservation(target_agent_id)

    def _is_aegis_actionable(self, spike_candidates: list[int]) -> bool:
        if not spike_candidates or not self._is_castable(AEGIS_ID):
            return False
        return not self._has_effect_fresh(Player.GetAgentID(), AEGIS_ID)

    def _try_aegis(self, spike_candidates: list[int]):
        if not self._is_aegis_actionable(spike_candidates):
            return False

        # Aegis is party-wide; self-targeting keeps the party coverage centered
        # on the Monk instead of selecting an arbitrary injured ally.
        return (
            yield from self.CastSkillIDAndRestoreTarget(
                AEGIS_ID,
                Player.GetAgentID(),
            )
        )

    def _resolve_great_dwarf_armor_target(self, spike_candidates: list[int]) -> int:
        custom_skill = self.GetCustomSkill(GREAT_DWARF_ARMOR_ID)
        if custom_skill is None:
            return 0

        spike_ids = set(spike_candidates)

        def is_unbuffed(agent_id: int) -> bool:
            return not Routines.Checks.Effects.HasEffect(agent_id, GREAT_DWARF_ARMOR_ID)

        if spike_ids:
            target_agent_id = self.ResolveRankedPartyAllyTarget(
                GREAT_DWARF_ARMOR_ID,
                custom_skill,
                validator=lambda agent_id: (
                    is_unbuffed(agent_id)
                    and Agent.IsMelee(agent_id)
                    and agent_id in spike_ids
                ),
                rank_key=lambda agent_id: (
                    -self.GetPartyHealthDelta(agent_id),
                    Agent.GetHealth(agent_id),
                ),
            )
            if target_agent_id:
                return target_agent_id

        target_agent_id = self.ResolveRankedPartyAllyTarget(
            GREAT_DWARF_ARMOR_ID,
            custom_skill,
            validator=lambda agent_id: (
                is_unbuffed(agent_id) and Agent.IsMelee(agent_id)
            ),
            rank_key=lambda agent_id: (
                Agent.GetHealth(agent_id),
                -self.GetPartyHealthDelta(agent_id),
            ),
        )
        if target_agent_id:
            return target_agent_id

        if spike_ids:
            target_agent_id = self.ResolveRankedPartyAllyTarget(
                GREAT_DWARF_ARMOR_ID,
                custom_skill,
                validator=lambda agent_id: (
                    is_unbuffed(agent_id) and agent_id in spike_ids
                ),
                rank_key=lambda agent_id: (
                    -self.GetPartyHealthDelta(agent_id),
                    Agent.GetHealth(agent_id),
                ),
            )
            if target_agent_id:
                return target_agent_id

        return self.ResolveRankedPartyAllyTarget(
            GREAT_DWARF_ARMOR_ID,
            custom_skill,
            validator=is_unbuffed,
            rank_key=lambda agent_id: (
                Agent.GetHealth(agent_id),
                -self.GetPartyHealthDelta(agent_id),
            ),
        )

    def _try_great_dwarf_armor(self, spike_candidates: list[int]):
        if not self._is_castable(GREAT_DWARF_ARMOR_ID):
            return False

        target_agent_id = self._resolve_great_dwarf_armor_target(spike_candidates)
        if not target_agent_id:
            return False

        return (
            yield from self.CastSkillIDAndRestoreTarget(
                GREAT_DWARF_ARMOR_ID,
                target_agent_id,
            )
        )

    def _try_preengagement_great_dwarf_armor(self):
        if not self.IsSkillEquipped(GREAT_DWARF_ARMOR_ID):
            return False
        if not self.IsCloseToAggro():
            return False

        leader_agent_id = int(GLOBAL_CACHE.Party.GetPartyLeaderID() or 0)
        if (
            not leader_agent_id
            or not Agent.IsValid(leader_agent_id)
            or not Agent.IsAlive(leader_agent_id)
        ):
            return False

        if Routines.Checks.Effects.HasEffect(
            leader_agent_id,
            GREAT_DWARF_ARMOR_ID,
        ):
            return False

        try:
            if (
                Utils.Distance(Player.GetXY(), Agent.GetXY(leader_agent_id))
                > Range.Spellcast.value
            ):
                return False
        except Exception:
            return False

        if not self._is_castable(GREAT_DWARF_ARMOR_ID):
            return False

        return (
            yield from self.CastSkillIDAndRestoreTarget(
                GREAT_DWARF_ARMOR_ID,
                leader_agent_id,
            )
        )

    def _try_draw_conditions(self):
        if not self.IsInAggro() or not self.IsSkillEquipped(DRAW_CONDITIONS_ID):
            return False
        return (yield from self.skillbook.Monk.ProtectionPrayers.Draw_Conditions())

    def _process_ooc(self):
        diagnostic_tick = self._diagnostic_note_callback("ooc")
        self._diagnostic_probe_ooc(diagnostic_tick)
        diagnostic_emergency_active = self._diagnostic_ooc_emergency_active()
        self._diagnostic_ooc_trace_active = diagnostic_emergency_active
        if diagnostic_emergency_active:
            self._diagnostic_log_ooc_state(
                "ooc_dispatch",
                "dispatch",
                {
                    "stage": "entered",
                    "order": "great_dwarf>healing_burst>dwaynas_kiss>signet>cure_hex>restore_life",
                },
            )

        if (yield from self._try_preengagement_great_dwarf_armor()):
            if diagnostic_emergency_active:
                self._diagnostic_log_ooc_state(
                    "ooc_dispatch",
                    "dispatch",
                    {
                        "stage": "returned",
                        "decision": "great_dwarf_armor_preempted",
                    },
                )
            return True

        if (yield from self._try_ooc_emergency_direct_heal(HEALING_BURST_ID)):
            if diagnostic_emergency_active:
                self._diagnostic_log_ooc_state(
                    "ooc_dispatch",
                    "dispatch",
                    {
                        "stage": "returned",
                        "decision": "healing_burst_request_accepted",
                    },
                )
            return True

        if (yield from self._try_ooc_emergency_dwaynas_kiss()):
            if diagnostic_emergency_active:
                self._diagnostic_log_ooc_state(
                    "ooc_dispatch",
                    "dispatch",
                    {
                        "stage": "returned",
                        "decision": "dwaynas_kiss_request_accepted",
                    },
                )
            return True

        if (
            yield from self._try_ooc_emergency_direct_heal(
                SIGNET_OF_REJUVENATION_ID,
                prefer_active_target=True,
            )
        ):
            if diagnostic_emergency_active:
                self._diagnostic_log_ooc_state(
                    "ooc_dispatch",
                    "dispatch",
                    {
                        "stage": "returned",
                        "decision": "signet_request_accepted",
                    },
                )
            return True

        if (yield from self._try_cure_hex(HexRemovalPriority.HIGH)):
            if diagnostic_emergency_active:
                self._diagnostic_log_ooc_state(
                    "ooc_dispatch",
                    "dispatch",
                    {
                        "stage": "returned",
                        "decision": "cure_hex_request_accepted",
                    },
                )
            return True

        if (yield from self._try_restore_life()):
            if diagnostic_emergency_active:
                self._diagnostic_log_ooc_state(
                    "ooc_dispatch",
                    "dispatch",
                    {
                        "stage": "returned",
                        "decision": "restore_life_request_accepted",
                    },
                )
            return True

        if diagnostic_emergency_active:
            self._diagnostic_log_ooc_state(
                "ooc_dispatch",
                "dispatch",
                {
                    "stage": "returned",
                    "decision": "no_action_accepted",
                },
            )

        return False

    def _process_specialized_combat(self, context: _CombatContext):
        actions: tuple[Callable[[], Any], ...] = (
            self._try_restore_life,
            self._try_draw_conditions,
            lambda: self._try_great_dwarf_armor(
                list(context.specialized_spike_candidates)
            ),
            lambda: self._try_cure_hex(HexRemovalPriority.LOW),
            lambda: self._try_ebon_battle_standard_of_wisdom(
                context.nearby_enemy_count
            ),
        )
        for action in actions:
            if (yield from action()):
                return True
        return False

    def _process_combat(self):
        self._diagnostic_note_callback("combat")
        context = self._build_combat_context()
        candidates = self._evaluate_combat_candidates(context)
        self._diagnostic_trace_candidates(context, candidates)

        high_cure_preemptors: list[_CombatActionCandidate] = []
        for candidate in candidates:
            if not candidate.preempts_high_cure:
                continue
            if candidate.rescue_revalidate is None:
                rescue_revalidation = True
            else:
                rescue_revalidation = candidate.rescue_revalidate()
            self._diagnostic_log_revalidation(
                candidate,
                stage="rescue",
                result=bool(rescue_revalidation),
                tick_ms=context.tick_ms,
            )
            if not rescue_revalidation:
                continue
            candidate_revalidation = candidate.revalidate()
            self._diagnostic_log_revalidation(
                candidate,
                stage="high_cure_gate",
                result=bool(candidate_revalidation),
                tick_ms=context.tick_ms,
            )
            if candidate_revalidation:
                high_cure_preemptors.append(candidate)

        selected_rescue = self._select_candidate(high_cure_preemptors)
        self._diagnostic_log_decision(
            context,
            branch="rescue",
            selected=selected_rescue,
            rescue_pool=len(high_cure_preemptors),
        )
        if high_cure_preemptors:
            if selected_rescue is not None:
                self._diagnostic_log_high_cure(
                    context,
                    attempted=False,
                    result=None,
                    skipped="rescue_selected",
                )
                return (
                    yield from self._execute_combat_candidate(
                        selected_rescue,
                        branch="rescue",
                    )
                )

        high_cure_result = yield from self._try_cure_hex(HexRemovalPriority.HIGH)
        self._diagnostic_log_high_cure(
            context,
            attempted=True,
            result=bool(high_cure_result),
        )
        if high_cure_result:
            self._diagnostic_log_decision(
                context,
                branch="ordinary",
                selected=None,
                skipped="high_cure_succeeded",
            )
            return True

        selected_ordinary = self._select_candidate(candidates)
        self._diagnostic_log_decision(
            context,
            branch="ordinary",
            selected=selected_ordinary,
        )
        if selected_ordinary is not None:
            return (
                yield from self._execute_combat_candidate(
                    selected_ordinary,
                    branch="ordinary",
                )
            )

        return (yield from self._process_specialized_combat(context))


__all__ = ["My_Healing_Burst"]
