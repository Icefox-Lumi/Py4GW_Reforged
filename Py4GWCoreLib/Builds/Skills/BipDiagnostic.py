"""Temporary, opt-in BiP decision-pass capture. Remove after Stage 3 evidence collection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from Py4GWCoreLib import ThrottledTimer
    from Py4GWCoreLib.BuildMgr import BuildMgr
    from Py4GWCoreLib.Builds.Skills import SkillsTemplate
    from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountStruct import AccountStruct

    # Narrow read interfaces for the existing unannotated Python facades.
    class _PartyIdentity(Protocol):
        def GetPartyID(self) -> int: ...

    class _SkillChecks(Protocol):
        def HasEnoughEnergy(self, agent_id: int, skill_id: int) -> bool: ...
        def IsSkillIDReady(self, skill_id: int) -> bool: ...
        def HasEnoughAdrenalineBySlot(self, slot: int) -> bool: ...

    class _PartyPlayer(Protocol):
        login_number: int
        is_connected: bool

    class _PartyLogins(Protocol):
        def GetAgentIDByLoginNumber(self, login_number: int) -> int: ...

    class _Distance(Protocol):
        def Distance(self, first: tuple[float, float], second: tuple[float, float]) -> float: ...

    class _SkillIDs(Protocol):
        def GetSkillIDBySlot(self, slot: int) -> int: ...


# Process-local only. Widget activation never arms; an explicit button click does.
ARM_BIP_CAPTURE = False
_armed = ARM_BIP_CAPTURE
_arm_consumed = False
_capture: BipDiagnostic | None = None


def arm_capture() -> bool:
    """Request one fresh capture; repeated clicks while waiting/running are harmless."""
    global _armed, _arm_consumed, _capture
    if _armed or (_capture is not None and not _capture.done):
        return False
    _capture = BipDiagnostic()
    _arm_consumed = False
    _armed = True
    return True


def stop_capture(reason: str = "ABORTED_MANUAL_STOP") -> None:
    global _armed
    _armed = False
    if _capture is not None:
        _capture.stop(reason)


def pending_capture(owner_name: str = "My Blood is Power") -> BipDiagnostic | None:
    """Offer this custom-only arm; the selected owner claims it on an aggro decision."""
    global _capture
    if owner_name != "My Blood is Power" or not _armed or _arm_consumed:
        return None
    if _capture is None:
        _capture = BipDiagnostic()
    return _capture


def update_capture() -> None:
    """Finish the existing capture clock even while the BiP coroutine is suspended."""
    capture = _capture
    if capture is not None and capture.started is not None and not capture.done:
        try:
            capture.advance(capture.clock())
        except Exception:
            capture.stop("ABORTED_ACCOUNTING_ERROR")


def capture_status() -> str:
    if _capture is None:
        return "Disarmed"
    if _capture.done:
        if _capture.started is None:
            return "Disarmed"
        if _capture.result == "COMPLETE":
            return "Finished - complete (disarmed)"
        if _capture.result == "INCONCLUSIVE_NO_RELEVANT_DEMAND":
            return "Finished - no verified demand (disarmed)"
        if _capture.result in {"ABORTED_MANUAL_STOP", "ABORTED_WIDGET_DISABLED"}:
            return "Finished - stopped (disarmed)"
        return "Finished - aborted (disarmed)"
    return "Armed - waiting for My Blood is Power combat" if _capture.started is None else "Capturing"


@dataclass(frozen=True)
class Recipient:
    agent_id: int
    connected_account: bool
    energy: float | None
    alive: bool
    in_range: bool
    covered: bool | None
    locked: bool
    primary_profession: int | None = None


@dataclass
class Snapshot:
    counts: Counter[str] = field(default_factory=Counter[str])
    demand: frozenset[int] = frozenset()
    eligible: frozenset[int] = frozenset()
    covered: frozenset[int] = frozenset()
    late_rejected: frozenset[int] = frozenset()
    hp: float = 0.0
    maximum: float = 0.0
    required: float = 0.0
    safe: bool | None = None
    gates: tuple[str, ...] = ()
    restoration: int | None = None
    blood: int | None = None
    hr: str = "unknown"


def observe_build(
    owner: BuildMgr,
    skillbook: SkillsTemplate,
    *,
    cast_timer: ThrottledTimer,
    weapon_allowed: Callable[[int], bool],
    shared_allowed: Callable[[int], bool],
    uses_coordination: Callable[[int], bool],
    target_allowed: Callable[[int, int], bool],
) -> Snapshot:
    """Read the owner using its explicitly lent, non-mutating admission checks."""
    from Py4GWCoreLib import Agent, AgentArray, GLOBAL_CACHE, Map, Player, Range, Routines, Skill, SkillBar, Utils
    from Py4GWCoreLib.GlobalCache.WhiteboardLocks import BLOOD_ENERGY_BUFF_LOCK_KEY, is_buff_target_lock_blocked

    player_id = Player.GetAgentID()
    bip = Skill.GetID("Blood_is_Power")
    ritual = Skill.GetID("Blood_Ritual")
    allies = set(AgentArray.GetAllyArray())
    rows: list[Recipient] = []
    # One bounded active-publication read per sample; never trust retained party entries.
    accounts = GLOBAL_CACHE.ShMem.GetAllAccountData(sort_results=False)
    party_id = cast("_PartyIdentity", GLOBAL_CACHE.Party).GetPartyID()
    map_identity = (Map.GetMapID(), Map.GetRegion()[0], Map.GetDistrict(), Map.GetLanguage()[0])
    # The older Python facades lack annotations; these signatures are source-verified.
    get_agent_id = cast("_PartyLogins", GLOBAL_CACHE.Party.Players).GetAgentIDByLoginNumber
    distance = cast("_Distance", Utils).Distance
    for member in cast("list[_PartyPlayer]", GLOBAL_CACHE.Party.GetPlayers()):
        agent_id = get_agent_id(member.login_number)
        if not agent_id or agent_id == player_id:
            continue
        published, energy, covered, profession = (
            publication_values(accounts, agent_id, member.login_number, party_id, map_identity, (bip, ritual))
            if member.is_connected
            else (False, None, None, None)
        )
        rows.append(
            Recipient(
                agent_id,
                bool(member.is_connected and published),
                energy,
                agent_id in allies and Agent.IsAlive(agent_id),
                agent_id in allies and distance(Player.GetXY(), Agent.GetXY(agent_id)) <= Range.Spellcast.value,
                covered,
                is_buff_target_lock_blocked(agent_id, BLOOD_ENERGY_BUFF_LOCK_KEY),
                profession,
            )
        )
    result = recipient_counts(rows)
    fraction = float(Agent.GetHealth(player_id))
    result.maximum = float(Agent.GetMaxHealth(player_id))
    result.hp = fraction * result.maximum
    conditions = owner.GetCustomSkill(bip).Conditions
    sacrifice = float(conditions.SacrificePercent)
    floor_fraction = float(conditions.MinHealthAfterSacrificePercent)
    floor_absolute = float(conditions.MinHealthAfterSacrificeAbsolute)
    result.required = max(
        float(conditions.SacrificeHealth) * result.maximum,
        (sacrifice + floor_fraction) * result.maximum,
        sacrifice * result.maximum + floor_absolute,
    )
    if result.maximum > 0 and isfinite(fraction):
        after = result.hp - result.maximum * sacrifice
        result.safe = (
            fraction > conditions.SacrificeHealth and after > floor_absolute and after / result.maximum > floor_fraction
        )
    slot = owner.GetEquippedSkillSlot(bip)
    gates: list[str] = []
    skill_checks = cast("_SkillChecks", Routines.Checks.Skills)
    slot_id = cast("_SkillIDs", SkillBar).GetSkillIDBySlot
    checks: dict[str, bool] = {
        "busy": bool(Routines.Checks.Skills.CanCast()),
        "pending": cast_timer.IsStopped() or cast_timer.IsExpired(),
        "energy": skill_checks.HasEnoughEnergy(player_id, bip),
        "ready": skill_checks.IsSkillIDReady(bip),
        "slot": 1 <= slot <= 8 and slot_id(slot) == bip,
        "toggle": owner.IsSharedSkillToggleEnabled(slot),
        "throttle": skillbook.Necromancer.BloodMagic.bip_throttle.IsStopped()
        or skillbook.Necromancer.BloodMagic.bip_throttle.IsExpired(),
        "weapon": weapon_allowed(bip),
        "shared": shared_allowed(bip),
        "adrenaline": skill_checks.HasEnoughAdrenalineBySlot(slot),
        "spirit": not owner.SpiritBuffExists(bip),
    }
    gates.extend(key for key, passed in checks.items() if not passed)
    # No second selector, CanCastSkillID (which stops timers), reservation or cast call.
    # If BiP ever opts into another coordination policy, attribution becomes unknown.
    if uses_coordination(bip):
        gates.append("coordination_unknown")
    result.late_rejected = frozenset(target for target in result.eligible if not target_allowed(bip, target))
    result.gates = tuple(gates)
    try:
        result.restoration, result.blood = effective_ranks(Agent.GetAttributes(player_id))
    except Exception:
        pass
    try:
        result.hr = str(bool(GLOBAL_CACHE.Effects.HasEffect(player_id, Skill.GetID("Heroic_Refrain"))))
    except Exception:
        pass
    return result


def publication_values(
    accounts: list[AccountStruct],
    agent_id: int,
    login: int,
    party: int,
    map_identity: tuple[int, int, int, int],
    energy_buffs: tuple[int, int],
    *,
    failure: list[str] | None = None,
) -> tuple[bool, float | None, bool | None, int | None]:
    """Read one unambiguous current player publication, never a retained PartyCache entry."""
    from Py4GWCoreLib.GlobalCache.shared_memory_src.Globals import SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS
    from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64, publication_is_live

    unknown = (False, None, None, None)
    gate = "candidate_fields"

    def rejected(reason: str) -> tuple[bool, float | None, bool | None, int | None]:
        if failure is not None:
            failure.append(reason)
        return unknown

    try:
        matches = [
            account
            for account in accounts
            if account.AgentData.AgentID == agent_id
            and (
                account.AgentData.Map.MapID,
                account.AgentData.Map.Region,
                account.AgentData.Map.District,
                account.AgentData.Map.Language,
            )
            == map_identity
        ]
        if len(matches) != 1:
            return rejected("candidate_count")
        account = matches[0]

        def stamp() -> tuple[object, ...]:
            data = account.AgentData
            location = data.Map
            return (
                account.LastUpdated,
                account.AccountEmail,
                account.IsAccount,
                account.IsSlotActive,
                account.IsHero,
                account.IsPet,
                account.IsNPC,
                data.AgentID,
                data.LoginNumber,
                data.OwnerAgentID,
                account.AgentPartyData.PartyID,
                location.MapID,
                location.Region,
                location.District,
                location.Language,
                account.IsIsolated,
            )

        gate = "identity_stamp"
        before = stamp()
        if not account.AccountEmail:
            return rejected("account_present")
        gate = "account_unique"
        if sum(other.AccountEmail == account.AccountEmail for other in accounts) != 1:
            return rejected(gate)
        if login <= 0:
            return rejected("expected_login")
        gate = "freshness"
        last_updated = account.LastUpdated
        # Live views may advance after enumeration; sample boot time after the stamp.
        try:
            now_tick = get_uncached_tick_count64()
        except OSError:
            return rejected("freshness_unavailable")
        if not publication_is_live(now_tick, last_updated, SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS):
            return rejected(gate)
        # GetAllAccountData already applies group-aware visibility. The raw isolation flag
        # remains required and stamped for change detection, but is not an identity veto.
        if before[2:-1] != (True, True, False, False, False, agent_id, login, 0, party, *map_identity):
            return rejected("identity")
        energy: float | None = None
        covered: bool | None = None
        profession: int | None = None
        try:
            energy = float(account.AgentData.Energy.Current)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            covered = any(buff.SkillId in energy_buffs for buff in account.AgentData.Buffs.Buffs)
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            primary = account.AgentData.Profession[0]
            profession = primary if 1 <= primary <= 10 else None
        except (AttributeError, IndexError, TypeError, ValueError):
            pass
        # Detect observed slot reuse/update while reading. This is not an atomic snapshot.
        gate = "identity_recheck"
        return (True, energy, covered, profession) if before == stamp() else rejected("publication_changed")
    except (AttributeError, TypeError, ValueError):
        return rejected(gate + "_unavailable")


def recipient_counts(rows: list[Recipient]) -> Snapshot:
    result = Snapshot()
    demand: set[int] = set()
    eligible: set[int] = set()
    covered: set[int] = set()
    for row in rows:
        valid = row.connected_account and row.energy is not None and isfinite(row.energy) and 0 <= row.energy <= 1
        result.counts["players"] += 1
        result.counts["valid_accounts"] += int(row.connected_account and valid)
        result.counts["energy_unknown"] += int(not valid)
        result.counts["dead"] += int(not row.alive)
        result.counts["range"] += int(not row.in_range)
        result.counts["effect_unknown"] += int(row.covered is None)
        result.counts["covered"] += int(row.covered is True)
        result.counts["locked"] += int(row.locked)
        if row.covered is True:
            covered.add(row.agent_id)
        if valid and row.energy is not None and row.energy <= 0.4:
            result.counts["low40"] += 1
            result.counts["dead40"] += int(not row.alive)
            result.counts["range40"] += int(not row.in_range)
            result.counts["effect_unknown40"] += int(row.covered is None)
        if not (valid and row.alive and row.in_range):
            continue
        assert row.energy is not None
        if row.energy <= 0.4:
            result.counts["covered40"] += int(row.covered is True)
            if row.covered is False:
                demand.add(row.agent_id)
                profession = (
                    "mesmer" if row.primary_profession == 5 else "other" if row.primary_profession else "unknown"
                )
                result.counts[f"demand40_{profession}"] += 1
                result.counts["locked40"] += int(row.locked)
                if not row.locked:
                    eligible.add(row.agent_id)
                    result.counts[f"eligible40_{profession}"] += 1
        elif row.energy <= 0.5 and row.covered is False and not row.locked:
            result.counts["band50"] += 1
    result.demand = frozenset(demand)
    result.eligible = frozenset(eligible)
    result.covered = frozenset(covered)
    result.counts["demand40"] = len(demand)
    result.counts["eligible40"] = len(eligible)
    return result


def effective_ranks(attributes: list[Any]) -> tuple[int | None, int | None]:
    ranks: dict[int, int] = {}
    for attribute in attributes:
        attribute_id = getattr(attribute, "attribute_id", None)
        level = getattr(attribute, "level", None)
        if attribute_id in (4, 33) and isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 30:
            ranks[int(attribute_id)] = level
    return ranks.get(33), ranks.get(4)


class BipDiagnostic:
    """One client/build-owned capture; all callbacks fail closed for diagnostics only."""

    def __init__(self, clock: Callable[[], float] = perf_counter, emit: Callable[[str], None] | None = None) -> None:
        self.clock = clock
        self.emit = emit or self._console
        self.started: float | None = None
        self.done = False
        self.result: str | None = None
        self.identity: tuple[object, ...] | None = None
        self.next_sample = 0.0
        self.next_report = 10.0
        self.pending: Snapshot | None = None
        self._decision_unfinished: bool = False
        self.pending_at = 0.0
        self.health_target = 0
        self.totals: Counter[str] = Counter()
        self.winners: Counter[str] = Counter()
        self.preemptions: Counter[str] = Counter()
        self.gates: Counter[str] = Counter()
        self.demand_gates: Counter[str] = Counter()
        self.attributes: Counter[str] = Counter()
        self.samples = 0
        self.sampled_seconds = 0.0
        self.demand_seconds = 0.0
        self.health_only_seconds = 0.0
        self.hp_block_seconds = 0.0
        self.block_streak = 0.0
        self.max_block_streak = 0.0
        self.previous: Snapshot | None = None
        self.previous_at = 0.0
        self.previous_health_only = False
        self.last: Snapshot | None = None
        self.submitted_targets: dict[int, float] = {}
        self.records = 0

    @staticmethod
    def _console(message: str) -> None:
        from Py4GWCoreLib import Console

        Console.Log("SmartBiP3B", message, Console.MessageType.Info)

    def _write(self, message: str) -> None:
        if self.records < 8:
            self.records += 1
            self.emit(message)

    def _active(self, now: float) -> bool:
        return not self.done and self.started is not None and now - self.started < 60.0

    def discard_pending(self) -> None:
        """At a new decision entry, abandon evidence whose pass never finished."""
        if self._decision_unfinished or self.pending is not None:
            self._decision_unfinished = False
            self.pending = None
            self.health_target = 0
            self._break_continuity()

    def enter_decision(self) -> None:
        """Track a new rotation entry independently of its sampling admission."""
        self.discard_pending()
        self._decision_unfinished = self.started is not None and not self.done

    def poll_due(self) -> bool:
        if self.done or not _armed:
            return False
        now = self.clock()
        if self.started is not None and not self.advance(now):
            return False
        if now < self.next_sample:
            return False
        self.next_sample = now + 0.25
        return True

    def begin(self, identity: tuple[object, ...] | None, in_aggro: bool, observe: Callable[[], Snapshot]) -> None:
        global _arm_consumed
        if self.done or not _armed:
            return
        try:
            now = self.clock()
            if identity is None:
                if self.started is not None:
                    self.stop("ABORTED_INVALID_SESSION")
                return
            if self.identity is not None and self.identity != identity:
                self.stop("ABORTED_IDENTITY_CHANGED")
                return
            if self.started is None:
                if _arm_consumed or not in_aggro:
                    return
                _arm_consumed = True
                self.identity = identity
                self.start(now)
            if not self.advance(now):
                return
            self.next_sample = now + 0.25
            # A sample belongs to the current entry; do not abandon that entry.
            if self.pending is not None:
                self.discard_pending()
            self._decision_unfinished = True
            self.pending = observe()
            self.pending_at = now
            self.health_target = 0
        except Exception:
            self.stop("ABORTED_OBSERVATION_ERROR")

    def start(self, now: float) -> None:
        if self.started is not None or self.done:
            return
        self.started = now
        self.next_sample = now
        self._write("BIP3B START duration_s=60 max_hz=4 scope=player_party decision_passes_only=1")

    def advance(self, now: float) -> bool:
        if self.done or self.started is None:
            return False
        elapsed = now - self.started
        if elapsed >= 60:
            self._aggregate(60.0)
            self.stop("COMPLETE" if self.totals["demand40"] else "INCONCLUSIVE_NO_RELEVANT_DEMAND")
            return False
        if elapsed >= self.next_report:
            self._aggregate(elapsed)
            self.next_report = (int(elapsed // 10) + 1) * 10.0
        return True

    def health_rejected(self, target: int) -> None:
        # Called only after the real selector, lock and throttle checks passed.
        if self.pending is not None:
            self.health_target = target

    def submission(self, category: str, target: int, self_id: int | None = None) -> None:
        try:
            now = self.clock()
            if not self._active(now):
                return
            if category == "bip":
                self.totals["bip_q"] += 1
                if len(self.submitted_targets) < 12 or target in self.submitted_targets:
                    self.submitted_targets[target] = now
            else:
                if self_id is None and self.identity is not None:
                    observed_id = self.identity[0]
                    self_id = observed_id if isinstance(observed_id, int) else None
                if self_id is None:
                    self.totals["heal_target_unknown_q"] += 1
                    return
                scope = "self" if target == self_id else "other"
                self.totals[f"heal_{scope}_q"] += 1
                if self.pending is not None and self.pending.demand and now - self.pending_at <= 0.25:
                    self.totals[f"heal_{scope}_sampled_demand_q"] += 1
        except Exception:
            self.stop("ABORTED_ACCOUNTING_ERROR")

    def finish(self, winner: str, *, preempted: bool = False) -> None:
        self._decision_unfinished = False
        try:
            now = self.clock()
            if not self._active(now):
                self.pending = None
                self.advance(now)
                return
            self.winners[winner] += 1
            # These are the rotation's only no-action outcomes; all skill winners are accepted requests.
            action_accepted = winner not in {"none", "idle", "cannot_cast"}
            sample, self.pending = self.pending, None
            if sample is None:
                if action_accepted:
                    self._break_continuity()
                return
            # Suspended coroutines are missing evidence, never seconds of inferred blockage.
            if now - self.pending_at > 0.25:
                self.totals["stale_pass"] += 1
                self._break_continuity()
                return
            if sample.demand and preempted:
                self.preemptions[winner] += 1
            if sample.demand and winner == "Signet_of_Lost_Souls":
                self.totals["sols_sampled_demand_q"] += 1
            self.record(
                sample,
                self.pending_at,
                preempted,
                self.health_target,
                action_accepted=action_accepted,
            )
        except Exception:
            self.stop("ABORTED_ACCOUNTING_ERROR")

    def _break_continuity(self) -> None:
        self.previous = None
        self.previous_health_only = False
        self.block_streak = 0.0

    def record(
        self, sample: Snapshot, now: float, preempted: bool, health_target: int, *, action_accepted: bool = False
    ) -> None:
        weight = 0.0
        demand_weight = 0.0
        previous = self.previous
        if previous is not None and 0 <= now - self.previous_at <= 0.5:
            weight = min(0.25, now - self.previous_at)
            if previous.demand & sample.demand:
                demand_weight = weight
                self.demand_seconds += weight
                if previous.safe is False and sample.safe is True:
                    field = (
                        "recovered"
                        if sample.maximum == previous.maximum and sample.hp > previous.hp
                        else "floor_changed"
                    )
                    self.totals[field] += 1
            if sample.maximum == previous.maximum and sample.hp > previous.hp and previous.demand & sample.demand:
                self.totals["hp_rise"] += 1
        if previous is not None and previous.demand & sample.demand and sample.safe is False:
            self.hp_block_seconds += weight
            self.block_streak = self.block_streak + weight if weight else 0.0
            self.max_block_streak = max(self.max_block_streak, self.block_streak)
        else:
            self.block_streak = 0.0
        health_only = (
            sample.safe is False
            and not sample.gates
            and not preempted
            and not action_accepted
            and health_target in sample.eligible
            and health_target not in sample.late_rejected
        )
        self.samples += 1
        self.sampled_seconds += weight
        self.health_only_seconds += demand_weight if health_only and self.previous_health_only else 0.0
        self.totals.update(sample.counts)
        self.totals["hp_block"] += int(bool(sample.demand) and sample.safe is False)
        if sample.demand and sample.safe is False and sample.maximum > 0:
            fraction = sample.hp / sample.maximum
            self.totals["hp_75_85"] += int(0.75 <= fraction < 0.85)
            self.totals["hp_85_floor"] += int(fraction >= 0.85)
        self.totals["health_only"] += int(health_only)
        self.totals["health_reject"] += int(health_target > 0)
        self.totals["health_reject_other_gate"] += int(
            health_target > 0 and bool(sample.gates or health_target in sample.late_rejected)
        )
        self.totals["health_reject_unverified_target"] += int(
            health_target > 0 and health_target not in sample.eligible
        )
        self.totals["after_health_action"] += int(health_target > 0 and action_accepted and not preempted)
        self.totals["preempt"] += int(bool(sample.demand) and preempted)
        self.gates.update(sample.gates)
        if sample.demand:
            self.demand_gates.update(sample.gates)
            self.demand_gates["late_effect"] += int(bool(sample.late_rejected))
        self.attributes.update((f"resto_{sample.restoration}", f"blood_{sample.blood}", f"hr_{sample.hr}"))
        for target, submitted_at in tuple(self.submitted_targets.items()):
            if now > submitted_at and target in sample.covered:
                self.totals["coverage_after_q"] += 1
                del self.submitted_targets[target]
            elif now - submitted_at >= 10:
                self.totals["coverage_unseen_10s"] += 1
                del self.submitted_targets[target]
        self.previous, self.previous_at, self.last = sample, now, sample
        self.previous_health_only = health_only

    def _aggregate(self, elapsed: float) -> None:
        def pairs(values: Counter[str]) -> str:
            return ",".join(f"{key}:{value}" for key, value in sorted(values.items()) if value) or "none"

        last = self.last
        state = (
            "unknown"
            if last is None
            else (
                f"{last.hp:.1f}/{last.maximum:.1f};need_gt:{last.required:.1f};safe:{last.safe};"
                f"resto:{last.restoration};blood:{last.blood};hr:{last.hr}"
            )
        )
        self._write(
            f"BIP3B AGG t={elapsed:.1f} cumulative=1 n={self.samples} sampled_s={self.sampled_seconds:.2f} "
            f"unobserved_s={max(0, elapsed-self.sampled_seconds):.2f} demand_s={self.demand_seconds:.2f} "
            f"health_only_s={self.health_only_seconds:.2f} counts=[{pairs(self.totals)}] "
            f"hp_block_s={self.hp_block_seconds:.2f} max_hp_block_streak_s={self.max_block_streak:.2f} "
            f"gates=[{pairs(self.gates)}] demand_gates=[{pairs(self.demand_gates)}] "
            f"winners=[{pairs(self.winners)}] preemptions=[{pairs(self.preemptions)}] "
            f"attrs=[{pairs(self.attributes)}] last=[{state}]"
        )

    def stop(self, reason: str = "ABORTED_CONTRACT_DISPOSED") -> None:
        global _armed
        if self.done:
            return
        self.done = True
        self.result = reason
        if _capture is self:
            _armed = False
        self._decision_unfinished = False
        self.pending = None
        self.health_target = 0
        self._break_continuity()
        self.submitted_targets.clear()
        if self.started is not None:
            try:
                self._write(f"BIP3B DONE result={reason} observed_effect_is_not_caster_attribution=1")
            except Exception:
                pass
