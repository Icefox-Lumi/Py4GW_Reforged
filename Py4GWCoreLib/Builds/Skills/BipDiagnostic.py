"""Temporary, opt-in BiP decision-pass capture. Remove after Stage 3 evidence collection."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from math import isfinite
from time import perf_counter
from typing import TYPE_CHECKING
from typing import Any
from typing import Protocol
from typing import cast

if TYPE_CHECKING:
    from Py4GWCoreLib import ThrottledTimer
    from Py4GWCoreLib.BuildMgr import BuildMgr
    from Py4GWCoreLib.Builds.Skills import SkillsTemplate
    from Py4GWCoreLib.Builds.Skills.SmartKaolai import KaolaiCapture
    from Py4GWCoreLib.Builds.Skills.SmartKaolai import KaolaiObservation
    from Py4GWCoreLib.GlobalCache.shared_memory_src.AccountStruct import AccountStruct
    from Py4GWCoreLib.GlobalCache.shared_memory_src.ConditionObservations import Observation

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


# Also terminate an in-place module reload before replacing the process-local arm.
_previous_stop = globals().get("stop_capture")
if callable(_previous_stop):
    _previous_stop("ABORTED_RELOADED")

# Process-local only. Widget activation never arms; an explicit button click does.
ARM_BIP_CAPTURE = False
_armed = ARM_BIP_CAPTURE
_arm_consumed = False
_capture: BipDiagnostic | None = None


def arm_capture(*, mbas: bool = False) -> bool:
    """Request one fresh capture; repeated clicks while waiting/running are harmless."""
    global _armed, _arm_consumed, _capture
    if _armed or (_capture is not None and not _capture.done):
        return False
    _capture = BipDiagnostic(mbas=mbas)
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
    kaolai: KaolaiObservation | None = None


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
    from Py4GWCoreLib import GLOBAL_CACHE
    from Py4GWCoreLib import Agent
    from Py4GWCoreLib import AgentArray
    from Py4GWCoreLib import Map
    from Py4GWCoreLib import Player
    from Py4GWCoreLib import Range
    from Py4GWCoreLib import Routines
    from Py4GWCoreLib import Skill
    from Py4GWCoreLib import SkillBar
    from Py4GWCoreLib import Utils
    from Py4GWCoreLib.GlobalCache.WhiteboardLocks import BLOOD_ENERGY_BUFF_LOCK_KEY
    from Py4GWCoreLib.GlobalCache.WhiteboardLocks import is_buff_target_lock_blocked

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
    from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64
    from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

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


def _account_evidence(account: Any, accounts: list[AccountStruct]) -> dict[str, Any]:
    """Read only the numeric/boolean fields we may print; never serialize an account."""
    from Py4GWCoreLib.GlobalCache.shared_memory_src.Globals import SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS
    from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64
    from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_age
    from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import publication_is_live

    values: dict[str, Any] = {}
    for path in (
        "LastUpdated",
        "IsAccount",
        "IsSlotActive",
        "IsHero",
        "IsPet",
        "IsNPC",
        "IsIsolated",
        "AgentData.AgentID",
        "AgentData.LoginNumber",
        "AgentData.OwnerAgentID",
        "AgentPartyData.PartyID",
        "AgentData.Map.MapID",
        "AgentData.Map.Region",
        "AgentData.Map.District",
        "AgentData.Map.Language",
        "AgentData.Energy.Current",
    ):
        value: Any = account
        try:
            for part in path.split("."):
                value = getattr(value, part)
            values[path.split(".")[-1]] = value if isinstance(value, (int, float)) and isfinite(value) else None
        except (AttributeError, TypeError, ValueError):
            values[path.split(".")[-1]] = None
    try:
        email = account.AccountEmail
        values["account_present"] = bool(email)
        values["account_candidates"] = sum(other.AccountEmail == email for other in accounts) if email else 0
    except (AttributeError, TypeError, ValueError):
        values.setdefault("account_present", None)
        values["account_candidates"] = None
    stamp = values["LastUpdated"]
    try:
        now = get_uncached_tick_count64() if isinstance(stamp, int) else None
    except OSError:
        now = None
    values["age_ms"] = publication_age(now, stamp) if now is not None else None
    values["fresh"] = publication_is_live(now, stamp, SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS) if now is not None else None
    return values


def inspect_account_evidence() -> None:
    """One explicit, bounded read. No capture state, publication or PartyCache writes."""
    import json
    import sys

    from Py4GWCoreLib import GLOBAL_CACHE
    from Py4GWCoreLib import Agent
    from Py4GWCoreLib import Console
    from Py4GWCoreLib import Map
    from Py4GWCoreLib import Player
    from Py4GWCoreLib import Skill
    from Py4GWCoreLib.GlobalCache.shared_memory_src.Globals import SHMEM_MAX_PLAYERS
    from Py4GWCoreLib.GlobalCache.shared_memory_src.Globals import SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS

    def emit(kind: str, values: dict[str, Any]) -> None:
        Console.Log(
            "SmartBiP3B",
            "BIP3B EVIDENCE " + kind + " " + json.dumps(values, sort_keys=True, allow_nan=False),
            Console.MessageType.Info,
        )

    try:
        accounts = GLOBAL_CACHE.ShMem.GetAllAccountData(sort_results=False)
        party = cast("_PartyIdentity", GLOBAL_CACHE.Party).GetPartyID()
        location = (Map.GetMapID(), Map.GetRegion()[0], Map.GetDistrict(), Map.GetLanguage()[0])
        ready = Map.IsMapReady()
        self_id = Player.GetAgentID()
        get_agent = cast("_PartyLogins", GLOBAL_CACHE.Party.Players).GetAgentIDByLoginNumber
        roster = sorted(
            (get_agent(member.login_number), member.login_number, bool(member.is_connected))
            for member in cast("list[_PartyPlayer]", GLOBAL_CACHE.Party.GetPlayers())
        )
        remote = [row for row in roster if row[0] and row[0] != self_id]
        buffs = (Skill.GetID("Blood_is_Power"), Skill.GetID("Blood_Ritual"))
        active = [_account_evidence(account, accounts) for account in accounts]
        raw: list[dict[str, Any]] | None = None
        try:
            slots = GLOBAL_CACHE.ShMem.GetAllAccounts()
            raw = [_account_evidence(slots.GetAccountData(i), accounts) for i in range(SHMEM_MAX_PLAYERS)]
        except Exception:
            pass  # A filtered-out slot is useful evidence, but not required for the active read.

        rows: list[dict[str, Any]] = []
        for agent_id, login, connected in remote[:16]:
            failure: list[str] = []
            valid, _, _, profession = (
                publication_values(accounts, agent_id, login, party, location, buffs, failure=failure)
                if connected
                else (False, None, None, None)
            )
            candidates = [v for v in active if v["AgentID"] == agent_id]
            exact = [
                v for v in candidates if tuple(v[k] for k in ("MapID", "Region", "District", "Language")) == location
            ]
            by_login = [v for v in active if login > 0 and v["LoginNumber"] == login]
            raw_agent = [v for v in raw or [] if v["AgentID"] == agent_id]
            raw_login = [v for v in raw or [] if login > 0 and v["LoginNumber"] == login]
            # Never choose arbitrarily among duplicate candidates at a stronger association.
            source, chosen = "none", []
            for label, choices in (
                ("active_exact", exact),
                ("active_agent", candidates),
                ("active_login", by_login),
                ("raw_agent", raw_agent),
                ("raw_login", raw_login),
            ):
                if choices:
                    source, chosen = label, choices
                    break
            rows.append(
                dict(
                    agent=agent_id,
                    login=login,
                    connected=connected,
                    valid=valid,
                    verified_mesmer=valid and profession == 5,
                    first="disconnected" if not connected else failure[0] if failure else "pass",
                    active_agent=len(candidates),
                    active_exact=len(exact),
                    active_login=len(by_login),
                    raw_agent=len(raw_agent) if raw is not None else None,
                    raw_login=len(raw_login) if raw is not None else None,
                    source=source,
                    unique=len(chosen) == 1,
                    published=chosen[0] if len(chosen) == 1 else None,
                )
            )
        emit(
            "summary",
            dict(
                active_total=len(accounts),
                remote_total=len(remote),
                inspected=len(rows),
                raw_available=raw is not None,
                fresh_boundary_ms=f"age < {SHMEM_SUBSCRIBE_TIMEOUT_MILLISECONDS}",
                reads="non-atomic; null=unavailable; active reader may be frame-cached",
                members=[{k: row[k] for k in ("agent", "first", "active_agent", "active_exact")} for row in rows],
            ),
        )
        if not rows:
            return
        selected = next((row for row in rows if row["verified_mesmer"]), rows[0])
        rejected = [row for row in rows if not row["valid"]]
        if rejected:
            selected = rejected[0]
            for row in rejected:
                try:
                    # A rejected publication cannot establish profession; use the roster agent's local read.
                    if Agent.GetProfessions(row["agent"])[0] == 5:
                        selected = row
                        break
                except Exception:
                    pass  # Unavailable profession keeps the stable rejected-recipient fallback.
        expected: dict[str, Any] = dict(zip(("MapID", "Region", "District", "Language"), location))
        expected.update(
            AgentID=selected["agent"],
            LoginNumber=selected["login"],
            OwnerAgentID=0,
            PartyID=party,
            IsAccount=True,
            IsSlotActive=True,
            IsHero=False,
            IsPet=False,
            IsNPC=False,
        )
        emit("selected", {k: v for k, v in selected.items() if k != "published"})
        emit(
            "identity",
            dict(
                expected=expected,
                published=selected["published"],
                selection=(
                    "rejected first (locally observed Mesmer preferred); "
                    "all valid: verified Mesmer preferred; agent/login order"
                ),
            ),
        )
        published = selected["published"]
        failed: list[str] = []
        unavailable: list[str] = ["publication"] if published is None else []
        region_exception: bool | None = None
        association: bool | None = None
        if published is not None:
            checks = {
                key: None if published[key] is None else published[key] == value for key, value in expected.items()
            }
            checks.update(
                IsIsolated=None if published["IsIsolated"] is None else True,
                account_present=published["account_present"],
                account_unique=(
                    None if published["account_candidates"] is None else published["account_candidates"] == 1
                ),
                freshness=published["fresh"],
                connected=selected["connected"],
                expected_login=selected["login"] > 0,
            )
            failed = [key for key, value in checks.items() if value is False]
            unavailable = [key for key, value in checks.items() if value is None]
            keys = ("MapID", "District", "Language", "AgentID", "PartyID", "Region")
            if all(published[key] is not None for key in keys):
                same_map = all(published[key] == expected[key] for key in ("MapID", "District", "Language"))
                # SameMapOrPartyAsAccount's rule, evaluated on these printed fields.
                region_exception = bool(
                    ready
                    and same_map
                    and published["AgentID"] in {row[0] for row in roster}
                    and published["PartyID"] == party
                )
                association = bool(ready and same_map and (region_exception or published["Region"] == location[1]))
        emit(
            "gates",
            dict(
                first=selected["first"],
                failed_fields=failed,
                unavailable_fields=unavailable,
                diagnostic_accepted=selected["valid"],
                detail=(
                    "candidate_count uses exact agent+map/Region/district/language; "
                    "details are separate nearby reads"
                ),
            ),
        )

        # Do not construct CacheData: its initialization/update owns settings and cache writes.
        cache_module = sys.modules.get("Py4GWCoreLib.HeroAI.cache_data")
        cache: Any = getattr(getattr(cache_module, "CacheData", None), "_instance", None)
        cache_values: dict[str, Any] | None = None
        cache_party: int | None = None
        energy_rule: bool | None = None
        if cache is not None:
            cache_party = int(cache.party.party_id)
            account = cache.party.get_by_player_id(selected["agent"])
            if account is not None:
                cache_values = _account_evidence(account, accounts)
                energy = cache_values["Current"]
                if all(cache_values[key] is not None for key in ("IsSlotActive", "PartyID", "Current")):
                    energy_rule = bool(
                        cache_values["IsSlotActive"] and cache_values["PartyID"] == cache_party and 0 <= energy <= 1
                    )
            else:
                energy_rule = False
        emit(
            "production",
            dict(
                map_ready=ready,
                association_rule_accepts=association,
                current_party_region_exception=region_exception,
                cache_available=cache is not None,
                cache_party=cache_party,
                cache_entry=cache_values,
                energy_lookup_rule_accepts=energy_rule,
                comparison=(
                    "source rules evaluated on printed fields; no cache refresh; "
                    "not a target/cast decision or frame-cached lookup result"
                ),
            ),
        )
    except Exception:
        # Never log exception text: bindings may include account identifiers in errors.
        emit("unavailable", dict(reason="read_failed; partial preceding evidence may exist"))


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


@dataclass
class MendAttempt:
    """One capture-local evidence token; target is an anonymized label, not an agent ID."""

    number: int
    target: int
    healthy: bool
    admissions: int = 0
    rejected: bool = False
    closed: bool = False


class BipDiagnostic:
    """One client/build-owned capture; all callbacks fail closed for diagnostics only."""

    def __init__(
        self,
        clock: Callable[[], float] = perf_counter,
        emit: Callable[[str], None] | None = None,
        *,
        mbas: bool = False,
    ) -> None:
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
        self.kaolai: KaolaiCapture | None = None
        self._mbas = mbas
        self._mend_attempt: MendAttempt | None = None
        self._mend_targets: dict[int, int] = {}
        self._mend_next: dict[tuple[int, str], float] = {}
        self._mend_counts: Counter[str] = Counter()
        self._mend_records = 0

    def _mend_write(self, message: str, *, final: bool = False) -> None:
        # Independent budget: never consume or alter the historical BIP3B records.
        try:
            if self._mend_records < 48 or final:
                self._mend_records += 1
                self.emit("MBASV2 " + message)
            else:
                self._mend_counts["omitted"] += 1
        except Exception:
            self._mend_counts["output_error"] += 1

    @staticmethod
    def _mend_age(observation: Observation | None) -> str:
        if observation is None:
            return "unavailable"
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import get_uncached_tick_count64

        return str(get_uncached_tick_count64() - observation.sampled_at)

    def mend_candidate(
        self,
        target: int,
        health: float,
        mode: str,
        observation: Observation | None,
        ranked_conditions: tuple[str, ...],
        spirits: int,
        severity: int,
        useful: int,
        capacity: int,
    ) -> MendAttempt | None:
        """Copy a real selected remote publication; never evaluate eligibility here."""
        try:
            now = self.clock()
            if (
                not self._mbas
                or not self._active(now)
                or observation is None
                or mode not in {"urgent", "opportunistic"}
            ):
                return None
            if self._mend_counts["candidates"] >= 8 or now < self._mend_next.get((target, mode), -1.0):
                self._mend_counts["suppressed"] += 1
                return None
            self._mend_cancel()
            self._mend_next[target, mode] = now + 2.0
            self._mend_counts["candidates"] += 1
            label = self._mend_targets.setdefault(target, len(self._mend_targets) + 1)
            attempt = MendAttempt(self._mend_counts["candidates"], label, health >= 0.85)
            self._mend_attempt = attempt
            self._mend_write(
                f"CANDIDATE attempt={attempt.number} target=remote{label} remote_human=1 "
                f"hp_pct={health * 100:.3f} healthy_attribution={int(attempt.healthy)} mode={mode} "
                f"conditions={','.join(sorted(observation.conditions))} ranked={','.join(sorted(ranked_conditions))} "
                f"source=authorized_owner_publication age_ms={self._mend_age(observation)} binding=VALID "
                f"spirits={spirits} severity={severity} useful={useful} capacity={capacity} "
                "selection_gates=PASS emergency_preemption=0 "
                f"reserve={'PASS' if mode == 'opportunistic' else 'NOT_REQUIRED'}"
            )
            return attempt
        except Exception:
            self._mend_counts["observation_error"] += 1
            return None

    def mend_admission(
        self,
        attempt: MendAttempt | None,
        accepted: bool,
        reason: str,
        *,
        health: float | None = None,
        spirits: int | None = None,
        observation: Observation | None = None,
        binding: str = "NOT_CHECKED",
    ) -> None:
        try:
            if attempt is None or attempt.closed or not self._active(self.clock()):
                return
            attempt.admissions += 1
            attempt.rejected |= not accepted
            self._mend_write(
                f"ADMISSION attempt={attempt.number} target=remote{attempt.target} call={attempt.admissions} "
                f"accepted={int(accepted)} reason={reason} scope=MBAS_CALLBACK "
                f"hp_pct={health * 100 if health is not None else 'unavailable'} spirits={spirits} "
                f"age_ms={self._mend_age(observation)} binding={binding}"
            )
        except Exception:
            self._mend_counts["observation_error"] += 1

    def mend_return(self, attempt: MendAttempt | None, accepted: bool) -> None:
        try:
            if attempt is None or attempt.closed or not self._active(self.clock()):
                return
            attempt.closed = True
            positive = accepted and attempt.healthy and attempt.admissions > 0 and not attempt.rejected
            self._mend_counts["queued"] += int(accepted)
            self._mend_counts["healthy_queued"] += int(positive)
            self._mend_write(
                f"SUBMISSION attempt={attempt.number} target=remote{attempt.target} accepted={int(accepted)} "
                f"healthy_condition_only={int(positive)} reason={'RETURN_TRUE' if accepted else 'BUILDMGR_DECLINED'} "
                "native_execution=UNVERIFIED"
            )
        except Exception:
            self._mend_counts["observation_error"] += 1

    def _mend_cancel(self) -> None:
        attempt = self._mend_attempt
        if attempt is not None and not attempt.closed:
            attempt.closed = True
            self._mend_counts["cancelled"] += 1
            self._mend_write(
                f"CANCELLED attempt={attempt.number} target=remote{attempt.target} "
                "return=UNOBSERVED queued=UNKNOWN queued_work_not_retracted=1"
            )

    def mend_cancel(self, attempt: MendAttempt | None) -> None:
        if attempt is not None and attempt is self._mend_attempt:
            self._mend_cancel()

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
        self._mend_cancel()
        if self._decision_unfinished or self.pending is not None:
            if self.kaolai is not None and self.pending is not None and self.pending.kaolai is not None:
                self.kaolai.counts["inconclusive_cancelled_pass"] += 1
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
            if self.pending.kaolai is not None:
                if self.kaolai is None:
                    from Py4GWCoreLib.Builds.Skills.SmartKaolai import KaolaiCapture

                    self.kaolai = KaolaiCapture()
                self.kaolai.observe(self.pending.kaolai, now)
        except Exception:
            self.stop("ABORTED_OBSERVATION_ERROR")

    def start(self, now: float) -> None:
        if self.started is not None or self.done:
            return
        self.started = now
        self.next_sample = now
        self._write("BIP3B START duration_s=60 max_hz=4 scope=player_party decision_passes_only=1")
        if self._mbas:
            self._mend_write("START duration_s=60 max_attempts=8 max_records=49 repeat_interval_s=2")

    def advance(self, now: float) -> bool:
        if self.done or self.started is None:
            return False
        if self.kaolai is not None:
            self.kaolai.advance(now)
        elapsed = now - self.started
        if elapsed >= 60:
            self._aggregate(60.0)
            self.stop("COMPLETE" if self.totals["demand40"] else "INCONCLUSIVE_NO_RELEVANT_DEMAND")
            return False
        if elapsed >= self.next_report:
            self._aggregate(elapsed)
            self.next_report = (int(elapsed // 10) + 1) * 10.0
        return True

    def kaolai_event(self, event: str) -> None:
        """Account for a real owner action; never read the world or submit work."""
        try:
            now = self.clock()
            if self._active(now) and self.kaolai is not None:
                self.kaolai.event(event, now)
        except Exception:
            self.stop("ABORTED_ACCOUNTING_ERROR")

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
            if self.kaolai is not None and winner == "Drop_Held_Bundle":
                self.kaolai.event("drop_selected", now)
            # These are the rotation's only no-action outcomes; all skill winners are accepted requests.
            action_accepted = winner not in {"none", "idle", "cannot_cast"}
            sample, self.pending = self.pending, None
            if sample is None:
                if action_accepted:
                    self._break_continuity()
                return
            if self.kaolai is not None and sample.kaolai is not None:
                # This associates a completed pass with its entry census, even
                # when the action yielded. It is not a census at submission time.
                self.kaolai.finish(sample.kaolai, winner, preempted)
            # Suspended coroutines are missing evidence, never seconds of inferred blockage.
            if now - self.pending_at > 0.25:
                self.totals["stale_pass"] += 1
                if self.kaolai is not None and sample.kaolai is not None:
                    self.kaolai.counts["delayed_pass_outcome"] += 1
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
            + (self.kaolai.summary() if self.kaolai is not None else "")
        )

    def stop(self, reason: str = "ABORTED_CONTRACT_DISPOSED") -> None:
        global _armed
        if self.done:
            return
        self.done = True
        self.result = reason
        self._mend_cancel()
        if self._mbas and self.started is not None:
            result = (
                "HEALTHY_CONDITION_ONLY_QUEUED"
                if self._mend_counts["healthy_queued"]
                else "EXERCISED_NO_HEALTHY_QUEUE_PROOF" if self._mend_counts["candidates"] else "NOT_EXERCISED"
            )
            if self._mend_counts["output_error"] or self._mend_counts["observation_error"]:
                result = "INCONCLUSIVE_DIAGNOSTIC_ERROR"
            self._mend_write(
                f"DONE result={result} completion={reason} "
                + " ".join(
                    f"{key}={self._mend_counts[key]}"
                    for key in (
                        "candidates",
                        "queued",
                        "healthy_queued",
                        "cancelled",
                        "suppressed",
                        "omitted",
                        "output_error",
                        "observation_error",
                    )
                )
                + " native_execution=UNVERIFIED condition_removal=UNVERIFIED",
                final=True,
            )
        if _capture is self:
            _armed = False
        self._decision_unfinished = False
        self.pending = None
        self.health_target = 0
        self._break_continuity()
        self.submitted_targets.clear()
        if self.kaolai is not None:
            self.kaolai.end("inconclusive_capture_ended")
        if self.started is not None:
            try:
                self._write(
                    f"BIP3B DONE result={reason} observed_effect_is_not_caster_attribution=1"
                    + (self.kaolai.summary() if self.kaolai is not None else "")
                )
            except Exception:
                pass
