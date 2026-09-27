"""Interrupt feasibility helper for HeroAI.

Owns the per-frame cast sampler, the interrupt classifier (driven by
``SkillNature.Interrupt`` tags in ``Py4GWCoreLib/HeroAI/custom_skill_src/``), the
``is_interrupt_feasible`` decision helper, and post-fire outcome logging.

Consumed by two evaluators:
* ``Py4GWCoreLib/HeroAI/combat.py`` ``AreCastConditionsMet`` — data-driven (unmatched bar).
* ``Py4GWCoreLib/BuildMgr.py`` ``CastSkillID`` — matched-build choke point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

import Py4GW  # noqa: F401 - importing the embedded runtime module initializes its bridge.
import PyPing
import PySystem

from Py4GWCoreLib import GLOBAL_CACHE
from Py4GWCoreLib import Agent
from Py4GWCoreLib import AgentArray
from Py4GWCoreLib import Effects
from Py4GWCoreLib import Player
from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib import Utils

from .types import SkillNature

# Logs every decision to the console while True. Flip off when validated.
INTERRUPT_DEBUG: bool = False

# Safety multiplier on measured ping.
_PING_SAFETY = 1.2

# Reaction margin on top of cast + ping buffer.
_DEFAULT_REACTION_MARGIN_MS = 50

# Sampler entry age-out. Exceeds the longest in-game activation time.
_OBSERVATION_MAX_AGE_MS = 10_000

# Grace past nominal activation before declaring FAIL — covers aftercast.
_OUTCOME_FAIL_GRACE_MS = 500

# ---------------------------------------------------------------------------
# Non-Fast-Casting cast-time modifiers.
#
# Applied on top of apply_fast_casting() as a multiplier. FC itself is exempt
# from the -25%/+150% caps — these tables only cover the non-FC side
# (consumables, self-buffs, spirit auras, slowing hexes), and the raw product
# of active modifiers gets clamped to [_NON_FC_MIN_MULT, _NON_FC_MAX_MULT].
# ---------------------------------------------------------------------------

# Consumables — stack MULTIPLICATIVELY with each other per user guidance.
# (skill_id_name, multiplier)
_CONSUMABLE_CAST_MODS: list[tuple[str, float]] = [
    ("Blue_Rock_Candy_Rush", 0.80),  # 20% faster
    ("Green_Rock_Candy_Rush", 0.85),  # 15% faster
    ("Red_Rock_Candy_Rush", 0.75),  # 25% faster
    ("Essence_of_Celerity_item_effect", 0.80),  # 20% faster
    ("Pie_Induced_Ecstasy", 0.85),  # Slice of Pumpkin Pie buff — 15% faster
]

# Self-enchantments that only affect SPELLS (not signets, not attack skills).
# Gated on GLOBAL_CACHE.Skill.Flags.IsSpell(our_skill_id).
_SPELL_ONLY_SPEEDUPS: list[tuple[str, float]] = [
    ("Mindbender", 0.80),  # 20% faster, PvE-only
]

# Slowing hexes that affect ALL skill types. Take MAX (they don't stack).
_SLOWING_HEXES_ALL: list[tuple[str, float]] = [
    ("Migraine", 2.0),
    ("Snaring_Web", 2.0),
]

# Slowing hexes that only affect SPELLS. Take MAX across spell+all hexes.
_SLOWING_HEXES_SPELLS: list[tuple[str, float]] = [
    ("Frustration", 2.0),
    ("Confusing_Images", 2.0),
    ("Arcane_Conundrum", 2.0),
    ("Enchanters_Conundrum", 2.0),
    ("Stolen_Speed", 2.0),
    ("Shared_Burden", 1.5),
    ("Sum_of_All_Fears", 1.33),
]

# Caps on the non-FC multiplier: -25% floor, +150% ceiling of original.
_NON_FC_MIN_MULT: float = 0.75
_NON_FC_MAX_MULT: float = 2.5

# --- Attack-skill interrupt parameters (ranger bow + warrior/sin melee) ---
# Attack skills use the attack-speed mechanic, not activation-time. The
# spell-side modifier tables don't apply — only AttackSpeedModifier and
# projectile flight time.

# Projectile flight ms per gw of distance. Py4GW doesn't expose bow subtype
# (Recurve/Longbow/Shortbow/Hornbow/Flatbow), so every bow is treated as
# Recurve — the most common subtype on hero bars.
_BOW_FLIGHT_MS_PER_GW: float = 0.42

# Touch range for melee swings. Bow attacks use Range.Spellcast (1248gw).
_MELEE_TOUCH_RANGE_GW: int = 144

# Lazy cache — populated on first use so we don't hit the game API at import.
_SKILL_ID_CACHE: dict[str, int] = {}

_LOG_PREFIX = "HeroAI.interrupt"


class ObservationOnsetConfidence(str, Enum):
    """Local confidence in when a sampled cast began.

    The sampler cannot manufacture a globally unique cast-instance ID.  A
    first observation is therefore deliberately marked uncertain unless a
    caller supplies a locally confirmed onset.  The identity is useful for
    local policy reasoning only; it is not a native cast identifier.
    """

    UNKNOWN = "unknown"
    FIRST_SEEN = "first_seen_uncertain"
    CONFIRMED = "confirmed_local_onset"


@dataclass(frozen=True, slots=True)
class CastObservation:
    """Immutable local identity and timing state for one sampled cast."""

    agent_id: int
    skill_id: int
    first_seen_ms: int
    last_seen_ms: int
    sequence: int
    onset_confidence: ObservationOnsetConfidence

    @property
    def observation_identity(self) -> tuple[int, int, int]:
        """Return a local, process-scoped identity for this observation."""

        return self.agent_id, self.skill_id, self.sequence


class InterruptAssessmentReason(str, Enum):
    """Bounded reasons returned by the structured interrupt assessment."""

    FEASIBLE = "feasible"
    INVALID_TARGET = "invalid_target"
    TARGET_STATE_UNKNOWN = "target_state_unknown"
    CAST_STOPPED = "cast_stopped"
    CAST_CHANGED = "cast_changed"
    UNKNOWN_ENEMY_SKILL = "unknown_enemy_skill"
    INVALID_GEOMETRY = "invalid_geometry"
    MISSING_GEOMETRY = "missing_geometry"
    OUT_OF_RANGE = "out_of_range"
    INVALID_TIMING = "invalid_timing"
    INSTANT_TARGET_SKILL = "instant_target_skill"
    UNKNOWN_OBSERVATION_AGE = "unknown_observation_age"
    UNCERTAIN_ONSET = "uncertain_onset"
    STALE_OBSERVATION = "stale_observation"
    CAST_FINISHED = "cast_finished"
    INSUFFICIENT_TIME = "insufficient_time"


@dataclass(frozen=True, slots=True)
class InterruptAssessment:
    """Structured mechanical interrupt result shared by legacy and strict callers."""

    feasible: bool
    reason: InterruptAssessmentReason
    strict: bool
    target_agent_id: int
    our_skill_id: int
    enemy_skill_id: int = 0
    observation_identity: tuple[int, int, int] | None = None
    observation_age_ms: int | None = None
    onset_confidence: ObservationOnsetConfidence = ObservationOnsetConfidence.UNKNOWN
    enemy_activation_ms: int | None = None
    enemy_remaining_ms: int | None = None
    our_activation_ms: int | None = None
    ping_ms: float | None = None
    ping_allowance_ms: int | None = None
    reaction_margin_ms: int | None = None
    interrupt_budget_ms: int | None = None
    distance_gw: float | None = None
    max_range_gw: int | None = None
    range_label: str | None = None
    geometry_available: bool = False
    geometry_missing: bool = False
    timing_invalid: bool = False
    observation_age_available: bool = False
    observation_stale: bool = False
    observation_untrusted: bool = False


def _now_ms() -> int:
    return int(PySystem.get_tick_count64())


def _log(message: str, level: str = "Debug") -> None:
    # Master switch: all interrupt-module output is gated on INTERRUPT_DEBUG.
    if not INTERRUPT_DEBUG:
        return
    msg_type = {
        "Debug": PySystem.Console.MessageType.Debug,
        "Info": PySystem.Console.MessageType.Info,
        "Warning": PySystem.Console.MessageType.Warning,
    }.get(level, PySystem.Console.MessageType.Debug)
    try:
        PySystem.Console.Log(_LOG_PREFIX, message, msg_type)
    except Exception:
        # Console may not be available during very early import; swallow.
        pass


# --- Classifier ---
# Reuses Py4GWCoreLib/HeroAI/custom_skill_src/ Nature tags as source of truth.

_INTERRUPT_SKILL_IDS: set[int] | None = None


def _ensure_registry() -> set[int]:
    """Build the classified-interrupt set once, lazily.

    Deferred to first call so ``HeroAI.combat`` has finished importing.
    """
    global _INTERRUPT_SKILL_IDS
    if _INTERRUPT_SKILL_IDS is not None:
        return _INTERRUPT_SKILL_IDS

    try:
        from .combat import custom_skill_data_handler  # lazy to avoid cycles
    except Exception as exc:
        _log(f"registry bootstrap failed: {exc}", "Warning")
        _INTERRUPT_SKILL_IDS = set()
        return _INTERRUPT_SKILL_IDS

    # skill_data is a pre-sized list; the index IS the skill_id.
    ids: set[int] = set()
    try:
        for skill_id, cs in enumerate(custom_skill_data_handler.skill_data):
            if cs.Nature == SkillNature.Interrupt.value:
                ids.add(skill_id)
    except Exception as exc:
        _log(f"registry scan failed: {exc}", "Warning")

    _INTERRUPT_SKILL_IDS = ids
    _log(f"registry populated: {len(ids)} interrupt skills classified", "Info")
    return _INTERRUPT_SKILL_IDS


def is_classified_as_interrupt(skill_id: int) -> bool:
    """True if ``skill_id`` is tagged ``SkillNature.Interrupt``."""
    if not skill_id:
        return False
    return skill_id in _ensure_registry()


# --- CastObserver: per-frame sampler ---


class CastObserver:
    """Tracks every observed enemy cast within compass radius every frame.

    Key: ``(agent_id, casting_skill_id)`` → value: first_seen_ms.
    ``elapsed_ms`` returns ``now - first_seen`` or ``None`` when unknown.

    The public observation record adds a process-local sequence and onset
    confidence without pretending to identify a native cast instance.  A
    first-seen cast remains uncertain because it may already have been in
    progress before this sampler noticed it.  The same-enemy/same-skill
    stop/restart case cannot be distinguished perfectly when both transitions
    happen between samples; D1B intentionally leaves that limitation local.
    """

    def __init__(self) -> None:
        self._observations: dict[tuple[int, int], int] = {}
        self._observation_records: dict[tuple[int, int], CastObservation] = {}
        self._last_observed_skill: dict[int, int] = {}
        self._next_sequence = 0
        self._pending_outcomes: list[tuple[int, int, int, int, int]] = []
        # (target_id, enemy_skill_id, our_skill_id, fired_at_ms, enemy_total_ms)

    # --- Public queries -----------------------------------------------------

    def observe(
        self,
        agent_id: int,
        skill_id: int,
        observed_at_ms: int,
        *,
        onset_confidence: ObservationOnsetConfidence = ObservationOnsetConfidence.FIRST_SEEN,
        onset_ms: int | None = None,
    ) -> CastObservation:
        """Record one local sample, optionally with a confirmed local onset."""

        if agent_id <= 0 or skill_id <= 0:
            raise ValueError("agent_id and skill_id must be positive")
        if observed_at_ms < 0:
            raise ValueError("observed_at_ms must be non-negative")
        if onset_ms is not None and (onset_ms < 0 or onset_ms > observed_at_ms):
            raise ValueError("onset_ms must be between zero and observed_at_ms")

        try:
            confidence = ObservationOnsetConfidence(onset_confidence)
        except ValueError as error:
            raise ValueError("invalid onset confidence") from error

        key = (agent_id, skill_id)
        previous = self._observation_records.get(key)
        if previous is None and key in self._observations:
            previous = CastObservation(
                agent_id=agent_id,
                skill_id=skill_id,
                first_seen_ms=self._observations[key],
                last_seen_ms=self._observations[key],
                sequence=0,
                onset_confidence=ObservationOnsetConfidence.FIRST_SEEN,
            )

        if previous is None:
            self._next_sequence += 1
            first_seen_ms = observed_at_ms if onset_ms is None else onset_ms
            sequence = self._next_sequence
            effective_confidence = confidence
        else:
            first_seen_ms = previous.first_seen_ms if onset_ms is None else onset_ms
            sequence = previous.sequence
            effective_confidence = previous.onset_confidence
            if onset_ms is not None or confidence is ObservationOnsetConfidence.CONFIRMED:
                effective_confidence = ObservationOnsetConfidence.CONFIRMED

        record = CastObservation(
            agent_id=agent_id,
            skill_id=skill_id,
            first_seen_ms=first_seen_ms,
            last_seen_ms=observed_at_ms,
            sequence=sequence,
            onset_confidence=effective_confidence,
        )
        self._observations[key] = first_seen_ms
        self._observation_records[key] = record
        self._last_observed_skill[agent_id] = skill_id
        return record

    def record_observed_onset(
        self,
        agent_id: int,
        skill_id: int,
        onset_ms: int,
        *,
        observed_at_ms: int | None = None,
    ) -> CastObservation:
        """Record a locally confirmed onset for strict/offline assessment use."""

        now_ms = _now_ms() if observed_at_ms is None else observed_at_ms
        return self.observe(
            agent_id,
            skill_id,
            now_ms,
            onset_confidence=ObservationOnsetConfidence.CONFIRMED,
            onset_ms=onset_ms,
        )

    def get_observation(self, agent_id: int, skill_id: int) -> CastObservation | None:
        """Return the current local observation, if the exact cast key is tracked."""

        record = self._observation_records.get((agent_id, skill_id))
        if record is not None:
            return record
        first_seen_ms = self._observations.get((agent_id, skill_id))
        if first_seen_ms is None:
            return None
        return CastObservation(
            agent_id=agent_id,
            skill_id=skill_id,
            first_seen_ms=first_seen_ms,
            last_seen_ms=first_seen_ms,
            sequence=0,
            onset_confidence=ObservationOnsetConfidence.FIRST_SEEN,
        )

    def get_agent_observations(self, agent_id: int) -> tuple[CastObservation, ...]:
        """Return current observations for one agent in deterministic order."""

        return tuple(
            sorted(
                (record for record in self._observation_records.values() if record.agent_id == agent_id),
                key=lambda record: (record.skill_id, record.sequence),
            )
        )

    def last_observed_skill(self, agent_id: int) -> int | None:
        """Return the last locally observed skill for an agent slot, if any."""

        return self._last_observed_skill.get(agent_id)

    def elapsed_ms(self, agent_id: int, skill_id: int) -> int | None:
        ts = self._observations.get((agent_id, skill_id))
        if ts is None:
            return None
        return _now_ms() - ts

    # --- Per-frame tick -----------------------------------------------------

    def tick(self) -> None:
        try:
            self._sweep_observations()
            self._sweep_pending_outcomes()
        except Exception as exc:
            _log(f"tick error: {exc}", "Warning")

    def _sweep_observations(self) -> None:
        now = _now_ms()

        try:
            player_pos = Player.GetXY()
            enemies = AgentArray.Filter.ByDistance(
                AgentArray.GetEnemyArray(),
                player_pos,
                Range.SafeCompass.value,
            )
        except Exception:
            enemies = []

        live_keys: set[tuple[int, int]] = set()

        for agent_id in enemies:
            if not Agent.IsValid(agent_id):
                # Slot recycled since AgentArray was captured — drop any
                # prior observation under this id and skip the deref.
                self._drop_agent(agent_id)
                continue
            try:
                if not Agent.IsCasting(agent_id):
                    self._drop_agent(agent_id)
                    continue
                sid = Agent.GetCastingSkillID(agent_id)
            except Exception:
                continue

            if not sid:
                self._drop_agent(agent_id)
                continue

            key = (agent_id, sid)
            if key not in self._observations:
                self._drop_agent(agent_id)
            self.observe(agent_id, sid, now)
            live_keys.add(key)

        stale_cutoff = now - _OBSERVATION_MAX_AGE_MS
        to_remove = [key for key, ts in self._observations.items() if key not in live_keys and ts < stale_cutoff]
        for key in to_remove:
            self._observations.pop(key, None)
            self._observation_records.pop(key, None)

    def _drop_agent(self, agent_id: int) -> None:
        keys = [k for k in self._observations if k[0] == agent_id]
        for k in keys:
            self._observations.pop(k, None)
            self._observation_records.pop(k, None)

    # --- Outcome logging ----------------------------------------------------

    def queue_outcome(
        self,
        target_id: int,
        enemy_skill_id: int,
        our_skill_id: int,
        enemy_total_ms: int,
    ) -> None:
        if not target_id or not enemy_skill_id or not our_skill_id:
            return
        self._pending_outcomes.append((target_id, enemy_skill_id, our_skill_id, _now_ms(), enemy_total_ms))

    def _sweep_pending_outcomes(self) -> None:
        if not self._pending_outcomes:
            return

        now = _now_ms()
        keep: list[tuple[int, int, int, int, int]] = []

        for record in self._pending_outcomes:
            target, enemy_skill, our_skill, fired_at, enemy_total = record

            # SUCCESS: target no longer casting that skill in the sampler.
            if self.elapsed_ms(target, enemy_skill) is None:
                self._log_outcome("SUCCESS", target, enemy_skill, our_skill, now - fired_at)
                continue

            # Target slot was recycled since we queued the outcome — the enemy is gone (died / despawned)
            if not Agent.IsValid(target):
                self._log_outcome("SUCCESS", target, enemy_skill, our_skill, now - fired_at)
                continue

            # SUCCESS: target is still casting, but a different skill now.
            try:
                current_sid = Agent.GetCastingSkillID(target) if Agent.IsCasting(target) else 0
            except Exception:
                current_sid = 0
            if current_sid and current_sid != enemy_skill:
                self._log_outcome("SUCCESS", target, enemy_skill, our_skill, now - fired_at)
                continue

            # FAIL: the enemy cast has had time to complete past its activation.
            if now - fired_at > enemy_total + _OUTCOME_FAIL_GRACE_MS:
                self._log_outcome("FAIL", target, enemy_skill, our_skill, now - fired_at)
                continue

            keep.append(record)

        self._pending_outcomes = keep

    def _log_outcome(
        self,
        verdict: str,
        target_id: int,
        enemy_skill_id: int,
        our_skill_id: int,
        elapsed_ms: int,
    ) -> None:
        our_name = _safe_skill_name(our_skill_id)
        target_name = _safe_agent_name(target_id)
        enemy_skill_name = _safe_skill_name(enemy_skill_id)
        _log(
            f"[outcome] {verdict} our={our_name}({our_skill_id}) "
            f"target={target_name}({target_id}) enemy_skill="
            f"{enemy_skill_name}({enemy_skill_id}) elapsed={elapsed_ms}ms",
            "Info",
        )


cast_observer = CastObserver()


# --- Shared helpers ---


_PING_HANDLER = PyPing.PingHandler()


def _get_player_fast_casting_level() -> int:
    """Read the player's Fast Casting attribute level, 0 if absent."""
    try:
        player_id = Player.GetAgentID()
        for attribute in Agent.GetAttributes(player_id):
            if attribute.GetName() == "Fast Casting":
                return int(attribute.level)
    except Exception:
        pass
    return 0


def _safe_skill_name(skill_id: int) -> str:
    try:
        return str(GLOBAL_CACHE.Skill.GetName(skill_id) or "").strip() or "?"
    except Exception:
        return "?"


def _safe_agent_name(agent_id: int) -> str:
    if not agent_id or not Agent.IsValid(agent_id):
        return "?"
    try:
        return str(Agent.GetNameByID(agent_id) or "").strip() or "?"
    except Exception:
        return "?"


def _resolve_skill_id(name: str) -> int:
    """Cached skill_id lookup by name. Returns 0 when unknown.

    Logs a one-shot warning on unresolved names so typos in modifier
    tables surface without console spam.
    """
    if name in _SKILL_ID_CACHE:
        return _SKILL_ID_CACHE[name]
    sid = 0
    try:
        sid = int(GLOBAL_CACHE.Skill.GetID(name) or 0)
    except Exception:
        sid = 0
    _SKILL_ID_CACHE[name] = sid
    if sid == 0:
        _log(f"unresolved modifier skill_id: '{name}'", "Warning")
    return sid


def _compute_modifier_multiplier(
    our_skill_id: int,
) -> tuple[float, float, list[str]]:
    """Stacked non-FC cast-time multiplier.

    Returns ``(raw, capped, applied)`` — caller multiplies the
    FC-reduced activation by ``capped``. FC is exempt from the cap;
    only the non-FC product is clamped to ``[_NON_FC_MIN_MULT,
    _NON_FC_MAX_MULT]``. ``applied`` is a list of display strings
    for logging.
    """
    try:
        player_id = Player.GetAgentID()
    except Exception:
        return 1.0, 1.0, []

    try:
        is_our_spell = bool(GLOBAL_CACHE.Skill.Flags.IsSpell(our_skill_id))
    except Exception:
        is_our_spell = False

    applied: list[str] = []
    raw = 1.0

    # Consumables — stack multiplicatively.
    for name, mult in _CONSUMABLE_CAST_MODS:
        sid = _resolve_skill_id(name)
        if not sid:
            continue
        try:
            present = Effects.HasEffect(player_id, sid)
        except Exception:
            present = False
        if present:
            raw *= mult
            applied.append(f"{name} (x{mult:.2f})")

    # Self-enchantments that only affect spells.
    if is_our_spell:
        for name, mult in _SPELL_ONLY_SPEEDUPS:
            sid = _resolve_skill_id(name)
            if not sid:
                continue
            try:
                present = Effects.HasEffect(player_id, sid)
            except Exception:
                present = False
            if present:
                raw *= mult
                applied.append(f"{name} (x{mult:.2f})")

    # Slowing hexes — take MAX across all-skill + spell-only (hexes don't stack).
    hex_candidates: list[tuple[str, float]] = list(_SLOWING_HEXES_ALL)
    if is_our_spell:
        hex_candidates.extend(_SLOWING_HEXES_SPELLS)

    strongest_hex_mult = 1.0
    strongest_hex_name = ""
    for name, mult in hex_candidates:
        sid = _resolve_skill_id(name)
        if not sid:
            continue
        try:
            present = Effects.HasEffect(player_id, sid)
        except Exception:
            present = False
        if present and mult > strongest_hex_mult:
            strongest_hex_mult = mult
            strongest_hex_name = name
    if strongest_hex_mult > 1.0:
        raw *= strongest_hex_mult
        applied.append(f"{strongest_hex_name} (x{strongest_hex_mult:.2f})")

    capped = max(_NON_FC_MIN_MULT, min(_NON_FC_MAX_MULT, raw))
    return raw, capped, applied


def _is_attack_skill(skill_id: int) -> bool:
    """True if classified as Attack — bypasses FC and the spell modifier
    table; uses the attack-speed mechanic instead."""
    if not skill_id:
        return False
    try:
        return bool(GLOBAL_CACHE.Skill.Flags.IsAttack(skill_id))
    except Exception:
        return False


def _max_interrupt_range_gw(our_skill_id: int) -> tuple[int, str]:
    """Return (max_range_gw, label) for the range gate.

    - Spell / signet:    spellcast (1248gw)
    - Attack + bow:      spellcast (1248gw)
    - Attack + melee:    touch (144gw)

    Melee swings can't connect past 144gw regardless of timing budget.
    """
    if not _is_attack_skill(our_skill_id):
        return int(Range.Spellcast.value), "spellcast"

    try:
        player_id = Player.GetAgentID()
        weapon_type, _ = Agent.GetWeaponType(player_id)
    except Exception:
        weapon_type = 0

    if weapon_type == 1:  # Weapon.Bow
        return int(Range.Spellcast.value), "spellcast"
    return _MELEE_TOUCH_RANGE_GW, "melee touch"


def _calc_attack_skill_activation_ms(
    our_skill_id: int,
    distance_gw: int,
    player_id: int,
) -> tuple[int, int, int, float, list[str]]:
    """Compute time-to-impact for an attack-skill interrupt.

    Returns ``(total_ms, release_ms, flight_ms, ias_modifier, breakdown)``.

    Half-interval rule: attack skills release/connect at *half* the stated
    activation time (the remaining half is the return-to-neutral tail —
    irrelevant for interrupt feasibility). So ``release_ms = stated/2``.

    Ranged adds ``flight_ms`` for projectile travel; ``total_ms = release +
    flight``. IAS scales the interval (Frenzy = 0.66, etc).
    """
    # Stated activation; fall back to weapon interval when the skill has
    # no explicit time (uses first half of the next attack interval).
    try:
        stated_s = GLOBAL_CACHE.Skill.Data.GetActivation(our_skill_id) or 0.0
    except Exception:
        stated_s = 0.0
    if stated_s <= 0:
        try:
            stated_s = float(Agent.GetWeaponAttackSpeed(player_id) or 0.0)
        except Exception:
            stated_s = 0.0

    stated_ms = int(stated_s * 1000)
    half_interval_ms = stated_ms // 2

    # IAS modifier scales the interval. Defaults to 1.0 if the API misbehaves.
    try:
        ias_modifier = float(Agent.GetAttackSpeedModifier(player_id) or 1.0)
    except Exception:
        ias_modifier = 1.0
    if ias_modifier <= 0:
        ias_modifier = 1.0

    release_ms = int(half_interval_ms * ias_modifier)

    # Flight time only for bows. Bow subtype isn't exposed by Py4GW —
    # every bow is treated as Recurve (0.42 ms/gw).
    flight_ms = 0
    try:
        weapon_type, _ = Agent.GetWeaponType(player_id)
    except Exception:
        weapon_type = 0
    if weapon_type == 1:  # Weapon.Bow
        flight_ms = int(distance_gw * _BOW_FLIGHT_MS_PER_GW)

    total_ms = release_ms + flight_ms

    breakdown = [
        f"half_interval={half_interval_ms}ms",
        f"IAS=x{ias_modifier:.2f}",
        f"release={release_ms}ms",
    ]
    if flight_ms > 0:
        breakdown.append(f"flight={flight_ms}ms (bow recurve assumed)")
        breakdown.append(f"impact={total_ms}ms")

    return total_ms, release_ms, flight_ms, ias_modifier, breakdown


def _queue_outcome(target_id: int, enemy_skill_id: int, our_skill_id: int) -> None:
    """Convenience wrapper used by call-sites after a feasibility check wins."""
    try:
        enemy_total_s = GLOBAL_CACHE.Skill.Data.GetActivation(enemy_skill_id) or 0.0
    except Exception:
        enemy_total_s = 0.0
    cast_observer.queue_outcome(target_id, enemy_skill_id, our_skill_id, int(enemy_total_s * 1000))


# --- is_interrupt_feasible: the decision helper ---


def is_interrupt_feasible(
    target_agent_id: int,
    our_skill_id: int,
    fast_casting_level: int,
    ping_ms: int,
    *,
    reaction_margin_ms: int = _DEFAULT_REACTION_MARGIN_MS,
    debug: bool | None = None,
) -> bool:
    """Compatibility boolean wrapper over the shared legacy assessment path."""

    return assess_interrupt(
        target_agent_id=target_agent_id,
        our_skill_id=our_skill_id,
        fast_casting_level=fast_casting_level,
        ping_ms=ping_ms,
        reaction_margin_ms=reaction_margin_ms,
        strict=False,
        debug=debug,
    ).feasible


# --- Structured interrupt assessment ---------------------------------------


def _make_assessment(
    *,
    target_agent_id: int,
    our_skill_id: int,
    strict: bool,
    reason: InterruptAssessmentReason,
    feasible: bool = False,
    **values: Any,
) -> InterruptAssessment:
    return InterruptAssessment(
        feasible=feasible,
        reason=reason,
        strict=strict,
        target_agent_id=target_agent_id,
        our_skill_id=our_skill_id,
        **values,
    )


def _position_is_valid(position: Any) -> bool:
    if position is None:
        return False
    try:
        return len(position) >= 2 and all(math.isfinite(float(position[index])) for index in (0, 1))
    except (TypeError, ValueError, IndexError):
        return False


def assess_interrupt(
    target_agent_id: int,
    our_skill_id: int,
    fast_casting_level: int,
    ping_ms: int,
    *,
    reaction_margin_ms: int = _DEFAULT_REACTION_MARGIN_MS,
    strict: bool = True,
    debug: bool | None = None,
) -> InterruptAssessment:
    """Return one shared mechanical assessment for legacy or strict callers.

    ``strict=True`` rejects unknown sampler age, unconfirmed onset, missing or
    invalid geometry, stale observations, and invalid timing data.  The
    legacy boolean wrapper deliberately calls this with ``strict=False`` so
    existing HeroAI behavior keeps its established zero-value fallbacks.
    """

    if debug is None:
        debug = INTERRUPT_DEBUG

    if not target_agent_id:
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.INVALID_TARGET,
        )
    try:
        if not Agent.IsValid(target_agent_id):
            return _make_assessment(
                target_agent_id=target_agent_id,
                our_skill_id=our_skill_id,
                strict=strict,
                reason=InterruptAssessmentReason.INVALID_TARGET,
            )
    except Exception:
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.TARGET_STATE_UNKNOWN,
        )

    try:
        is_casting = bool(Agent.IsCasting(target_agent_id))
    except Exception:
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.TARGET_STATE_UNKNOWN,
        )
    if not is_casting:
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.CAST_STOPPED,
        )

    try:
        enemy_skill_id = int(Agent.GetCastingSkillID(target_agent_id) or 0)
    except Exception:
        enemy_skill_id = 0
    if enemy_skill_id <= 0:
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.UNKNOWN_ENEMY_SKILL,
        )

    try:
        observation = cast_observer.get_observation(target_agent_id, enemy_skill_id)
    except Exception:
        observation = None

    if strict and observation is None:
        try:
            last_skill = cast_observer.last_observed_skill(target_agent_id)
        except Exception:
            last_skill = None
        if last_skill is not None and last_skill != enemy_skill_id:
            return _make_assessment(
                target_agent_id=target_agent_id,
                our_skill_id=our_skill_id,
                strict=strict,
                reason=InterruptAssessmentReason.CAST_CHANGED,
                enemy_skill_id=enemy_skill_id,
                observation_untrusted=True,
            )

    geometry_available = True
    geometry_missing = False
    distance_gw: float | None = None
    try:
        player_pos = Player.GetXY()
        target_pos = Agent.GetXY(target_agent_id)
        if player_pos is None or target_pos is None:
            geometry_available = False
            geometry_missing = True
        elif not _position_is_valid(player_pos) or not _position_is_valid(target_pos):
            geometry_available = False
        else:
            distance_gw = float(Utils.Distance(player_pos, target_pos))
            if not math.isfinite(distance_gw) or distance_gw < 0.0:
                geometry_available = False
                distance_gw = None
    except Exception:
        geometry_available = False
        geometry_missing = True

    max_range_gw, range_label = _max_interrupt_range_gw(our_skill_id)
    common_values: dict[str, Any] = {
        "enemy_skill_id": enemy_skill_id,
        "observation_identity": None if observation is None else observation.observation_identity,
        "onset_confidence": (
            ObservationOnsetConfidence.UNKNOWN if observation is None else observation.onset_confidence
        ),
        "distance_gw": distance_gw,
        "max_range_gw": max_range_gw,
        "range_label": range_label,
        "geometry_available": geometry_available,
        "geometry_missing": geometry_missing,
    }

    if not geometry_available:
        if strict:
            return _make_assessment(
                target_agent_id=target_agent_id,
                our_skill_id=our_skill_id,
                strict=strict,
                reason=(
                    InterruptAssessmentReason.MISSING_GEOMETRY
                    if geometry_missing
                    else InterruptAssessmentReason.INVALID_GEOMETRY
                ),
                **common_values,
            )
        common_values["distance_gw"] = 0.0

    distance_for_calculation = int(common_values["distance_gw"])
    if distance_for_calculation > max_range_gw:
        if debug:
            _log(
                f"[rupt] Our '{_safe_skill_name(our_skill_id)}', {_safe_agent_name(target_agent_id)} "
                f"→ SKIP: out of {range_label} range "
                f"(distance={distance_for_calculation}gw, max={max_range_gw}gw)"
            )
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.OUT_OF_RANGE,
            **common_values,
        )

    try:
        enemy_total_s = float(GLOBAL_CACHE.Skill.Data.GetActivation(enemy_skill_id) or 0.0)
    except Exception:
        enemy_total_s = float("nan")
    if not math.isfinite(enemy_total_s) or enemy_total_s < 0.0:
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.INVALID_TIMING,
            timing_invalid=True,
            **common_values,
        )
    enemy_total_ms = int(enemy_total_s * 1000.0)
    common_values["enemy_activation_ms"] = enemy_total_ms
    if enemy_total_ms <= 0:
        if debug:
            _log(
                f"[rupt] Our '{_safe_skill_name(our_skill_id)}', {_safe_agent_name(target_agent_id)} "
                f"is casting '{_safe_skill_name(enemy_skill_id)}' → "
                "SKIP: target skill is instant (nothing to interrupt)"
            )
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.INSTANT_TARGET_SKILL,
            **common_values,
        )

    observation_age_available = observation is not None
    observation_stale = False
    observation_untrusted = observation is None
    if observation is None:
        elapsed_ms = 0
        observation_age_ms: int | None = None
    else:
        try:
            elapsed_ms = _now_ms() - observation.first_seen_ms
        except Exception:
            elapsed_ms = -1
        observation_age_ms = elapsed_ms
        observation_stale = elapsed_ms > _OBSERVATION_MAX_AGE_MS
        observation_untrusted = observation.onset_confidence is not ObservationOnsetConfidence.CONFIRMED
        if elapsed_ms < 0:
            return _make_assessment(
                target_agent_id=target_agent_id,
                our_skill_id=our_skill_id,
                strict=strict,
                reason=InterruptAssessmentReason.INVALID_TIMING,
                timing_invalid=True,
                observation_age_available=observation_age_available,
                observation_stale=observation_stale,
                observation_untrusted=observation_untrusted,
                observation_age_ms=observation_age_ms,
                **common_values,
            )

    common_values.update(
        {
            "observation_age_ms": observation_age_ms,
            "observation_age_available": observation_age_available,
            "observation_stale": observation_stale,
            "observation_untrusted": observation_untrusted,
            "enemy_remaining_ms": max(0, enemy_total_ms - elapsed_ms),
        }
    )

    try:
        ping_value = float(ping_ms)
        reaction_value = float(reaction_margin_ms)
        fast_casting_value = float(fast_casting_level)
    except (TypeError, ValueError):
        ping_value = float("nan")
        reaction_value = float("nan")
        fast_casting_value = float("nan")
    if (
        not math.isfinite(ping_value)
        or ping_value < 0.0
        or not math.isfinite(reaction_value)
        or reaction_value < 0.0
        or not math.isfinite(fast_casting_value)
        or fast_casting_value < 0.0
    ):
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.INVALID_TIMING,
            timing_invalid=True,
            ping_ms=ping_value,
            reaction_margin_ms=int(reaction_value) if math.isfinite(reaction_value) else None,
            **common_values,
        )

    fast_casting_level = int(fast_casting_value)
    reaction_margin_ms = int(reaction_value)
    ping_buffer_ms = int(ping_value * _PING_SAFETY)
    raw_mult = 1.0
    capped_mult = 1.0
    applied_modifiers: list[str] = []
    attack_breakdown: list[str] = []
    attack_release_ms = 0
    attack_flight_ms = 0
    attack_ias_modifier = 1.0

    try:
        is_attack_path = _is_attack_skill(our_skill_id)
        if is_attack_path:
            try:
                player_id = Player.GetAgentID()
            except Exception:
                player_id = 0
            (
                our_activation_ms,
                attack_release_ms,
                attack_flight_ms,
                attack_ias_modifier,
                attack_breakdown,
            ) = _calc_attack_skill_activation_ms(our_skill_id, distance_for_calculation, player_id)
        else:
            try:
                our_activation_s, _ = Routines.Checks.Skills.apply_fast_casting(our_skill_id, fast_casting_level)
            except Exception:
                our_activation_s = GLOBAL_CACHE.Skill.Data.GetActivation(our_skill_id) or 0.0
            our_activation_ms_after_fc = int(float(our_activation_s) * 1000.0)
            raw_mult, capped_mult, applied_modifiers = _compute_modifier_multiplier(our_skill_id)
            our_activation_ms = int(our_activation_ms_after_fc * float(capped_mult))
    except (TypeError, ValueError, OverflowError):
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.INVALID_TIMING,
            timing_invalid=True,
            ping_ms=ping_value,
            ping_allowance_ms=ping_buffer_ms,
            reaction_margin_ms=reaction_margin_ms,
            **common_values,
        )

    try:
        timing_is_valid = (
            math.isfinite(float(our_activation_ms))
            and math.isfinite(float(raw_mult))
            and math.isfinite(float(capped_mult))
            and math.isfinite(float(attack_ias_modifier))
            and our_activation_ms > 0
            and raw_mult > 0.0
            and capped_mult > 0.0
            and attack_ias_modifier > 0.0
        )
    except (TypeError, ValueError, OverflowError):
        timing_is_valid = False
    if not timing_is_valid:
        return _make_assessment(
            target_agent_id=target_agent_id,
            our_skill_id=our_skill_id,
            strict=strict,
            reason=InterruptAssessmentReason.INVALID_TIMING,
            timing_invalid=True,
            our_activation_ms=our_activation_ms,
            ping_ms=ping_value,
            ping_allowance_ms=ping_buffer_ms,
            reaction_margin_ms=reaction_margin_ms,
            **common_values,
        )

    budget_ms = int(our_activation_ms + ping_buffer_ms + reaction_margin_ms)
    common_values.update(
        {
            "our_activation_ms": our_activation_ms,
            "ping_ms": ping_value,
            "ping_allowance_ms": ping_buffer_ms,
            "reaction_margin_ms": reaction_margin_ms,
            "interrupt_budget_ms": budget_ms,
        }
    )

    if strict:
        if observation is None:
            return _make_assessment(
                target_agent_id=target_agent_id,
                our_skill_id=our_skill_id,
                strict=strict,
                reason=InterruptAssessmentReason.UNKNOWN_OBSERVATION_AGE,
                **common_values,
            )
        if observation_stale:
            return _make_assessment(
                target_agent_id=target_agent_id,
                our_skill_id=our_skill_id,
                strict=strict,
                reason=InterruptAssessmentReason.STALE_OBSERVATION,
                **common_values,
            )
        if observation.onset_confidence is not ObservationOnsetConfidence.CONFIRMED:
            return _make_assessment(
                target_agent_id=target_agent_id,
                our_skill_id=our_skill_id,
                strict=strict,
                reason=InterruptAssessmentReason.UNCERTAIN_ONSET,
                **common_values,
            )

    remaining_ms = int(common_values["enemy_remaining_ms"])
    if remaining_ms <= 0:
        reason = InterruptAssessmentReason.CAST_FINISHED
        feasible = False
    elif remaining_ms < budget_ms:
        reason = InterruptAssessmentReason.INSUFFICIENT_TIME
        feasible = False
    else:
        reason = InterruptAssessmentReason.FEASIBLE
        feasible = True

    if debug:
        verdict = "FEASIBLE" if feasible else f"SKIP: {reason.value}"
        _log(
            f"[rupt] Our '{_safe_skill_name(our_skill_id)}', {_safe_agent_name(target_agent_id)} "
            f"is casting '{_safe_skill_name(enemy_skill_id)}' → {verdict}"
        )
        _log(f"       distance={distance_for_calculation}gw ({range_label} max {max_range_gw}gw)")
        if is_attack_path:
            _log(f"       attack: {', '.join(attack_breakdown)}")
            _log(
                f"       target_remaining={remaining_ms}ms vs our_budget={budget_ms}ms  "
                f"[cast={our_activation_ms}ms (release={attack_release_ms}+flight={attack_flight_ms}, "
                f"IAS x{attack_ias_modifier:.2f}) + ping={ping_value}ms*1.2={ping_buffer_ms}ms "
                f"+ margin={reaction_margin_ms}ms]"
            )
        elif applied_modifiers:
            mods_summary = (
                f"raw x{raw_mult:.2f}, capped x{capped_mult:.2f}"
                if abs(raw_mult - capped_mult) > 1e-4
                else f"x{capped_mult:.2f}"
            )
            _log(f"       modifiers: {', '.join(applied_modifiers)} → {mods_summary}")
        _log(
            f"       target_remaining={remaining_ms}ms vs our_budget={budget_ms}ms  "
            f"[cast={our_activation_ms}ms (FC {fast_casting_level}, mods x{capped_mult:.2f}) "
            f"+ ping={ping_value}ms*1.2={ping_buffer_ms}ms + margin={reaction_margin_ms}ms]"
        )

    return _make_assessment(
        target_agent_id=target_agent_id,
        our_skill_id=our_skill_id,
        strict=strict,
        reason=reason,
        feasible=feasible,
        **common_values,
    )


# --- Per-frame tick registration ---
# Sampler runs independent of either evaluator path.

_CALLBACK_NAME = "HeroAI.Interrupt.Tick"


def _register_tick_callback() -> None:
    try:
        import PyCallback

        PyCallback.PyCallback.Register(
            _CALLBACK_NAME,
            PyCallback.Phase.Data,
            cast_observer.tick,
            priority=7,
            context=PyCallback.Context.Draw,
        )
        _log("sampler tick registered", "Info")
    except Exception as exc:
        _log(f"sampler tick registration failed: {exc}", "Warning")


_register_tick_callback()
