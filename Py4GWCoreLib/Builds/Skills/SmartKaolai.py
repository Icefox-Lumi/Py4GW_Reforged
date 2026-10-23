"""My Blood is Power's Kaolai policy; the build retains action ownership.

Option A deliberately accepts generic holding, including the wrong-bundle risk.
Emergency admission measures injury severity, not predicted or completed healing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from math import dist
from typing import TYPE_CHECKING

from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Player import Player

if TYPE_CHECKING:
    from Py4GWCoreLib.BuildMgr import BuildMgr
    from Py4GWCoreLib.Builds.Skills.BipDiagnostic import BipDiagnostic
    from Py4GWCoreLib.Builds.Skills.ritualist.RestorationMagic import RestorationMagic


@dataclass
class KaolaiObservation:
    """Decision-entry evidence, not an atomic census or positive ash identity."""

    held: bool | None = None
    loaded: bool = False
    alive: bool = False
    complete: bool = False
    injured: int = 0
    critical: int = 0
    dead: int = 0
    outside: int = 0
    missing: int = 0
    self_hp: float = 0.0
    pending: bool = False
    busy: bool = False
    button: bool = False
    health: tuple[tuple[int, float], ...] = ()

    @property
    def routine(self) -> bool:
        return (
            self.complete
            and self.alive
            and self.held is True
            and self.injured >= 4
            and self.button
            and not self.pending
            and not self.busy
        )


@dataclass
class _ReleaseWatch:
    started: float
    health: dict[int, float]
    samples: int = 0
    rises: set[int] = field(default_factory=set[int])
    cleared: bool = False


class KaolaiCapture:
    """Temporary accounting driven exclusively by the existing BiP capture."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.last: KaolaiObservation | None = None
        self.last_at = 0.0
        self.watch: _ReleaseWatch | None = None

    def observe(self, sample: KaolaiObservation, now: float) -> None:
        self.advance(now)
        self.last, self.last_at = sample, now
        self.counts["samples"] += 1
        self.counts["incomplete_entry"] += int(not sample.complete)
        self.counts["generic_held_entry"] += int(sample.held is True)
        self.counts["four_entry"] += int(sample.complete and sample.injured >= 4)
        self.counts["below_four_entry"] += int(sample.complete and sample.injured < 4)
        self.counts["dead_nearby_entry"] += int(sample.dead > 0)
        self.counts["outside_entry"] += int(sample.outside > 0)
        self.counts["routine_entry"] += int(sample.routine)
        self.counts["critical2or3_below4"] += int(
            sample.complete and sample.held is True and sample.injured < 4 and 2 <= sample.critical <= 3
        )
        self.counts["pending_entry"] += int(sample.pending)
        self.counts["busy_entry"] += int(sample.busy)
        self.counts["self_critical_entry"] += int(sample.alive and 0 < sample.self_hp < 0.30)
        watch = self.watch
        if watch is None:
            return
        if not sample.loaded or not sample.alive or not sample.complete:
            self.end("inconclusive_context")
            return
        watch.samples += 1
        for agent_id, hp in sample.health:
            if agent_id in watch.health and hp > watch.health[agent_id]:
                watch.rises.add(agent_id)
        if sample.held is False and not watch.cleared:
            watch.cleared = True
            self.counts["generic_held_cleared"] += 1

    def event(self, event: str, now: float) -> None:
        self.advance(now)
        self.counts[event] += 1
        if event != "click_call_returned":
            return
        if self.watch is not None:
            self.counts["overlapping_calls"] += 1
            return
        if self.counts["windows"] >= 4:
            self.counts["window_budget_exhausted"] += 1
            return
        self.counts["windows"] += 1
        fresh = self.last is not None and 0 <= now - self.last_at <= 0.25
        health = dict(self.last.health) if self.last is not None and fresh else {}
        self.watch = _ReleaseWatch(now, health)

    def finish(self, sample: KaolaiObservation, winner: str, preempted: bool) -> None:
        if preempted and winner in {"Spirit_Transfer", "Spirit_Light", "Mend_Body_and_Soul"}:
            self.counts[f"early_{winner}"] += 1
            if sample.routine:
                self.counts[f"routine_entry_preempted_{winner}"] += 1
            if sample.complete and sample.held is True and sample.injured < 4 and 2 <= sample.critical <= 3:
                self.counts["critical2or3_preempted"] += 1

    def advance(self, now: float) -> None:
        if self.watch is not None and now - self.watch.started >= 2.0:
            outcome = "window_with_held_clear" if self.watch.cleared else "no_change_observed"
            self.end(outcome if self.watch.samples else "inconclusive_observation_gap")

    def end(self, outcome: str) -> None:
        if self.watch is not None:
            self.counts[outcome] += 1
            self.counts["hp_fraction_rises_unattributed"] += len(self.watch.rises)
            self.watch = None

    def summary(self) -> str:
        sample = self.last
        last = "none"
        if sample is not None:
            last = (
                f"held:{sample.held},loaded:{int(sample.loaded)},alive:{int(sample.alive)},"
                f"complete:{int(sample.complete)},injured:{sample.injured},"
                f"critical:{sample.critical},dead:{sample.dead},outside:{sample.outside},missing:{sample.missing},"
                f"four:{int(sample.injured >= 4)},button:{int(sample.button)},"
                f"pending:{int(sample.pending)},busy:{int(sample.busy)},self_hp:{sample.self_hp:.3f}"
            )
        counts = ",".join(f"{key}:{value}" for key, value in sorted(self.counts.items()) if value) or "none"
        return (
            f" kaolai=[identity:unknown,click_receipt:unavailable,heal_receipt:unavailable;"
            f"last_entry:{last};counts:{counts};watch_open:{int(self.watch is not None)}]"
        )


class SmartKaolai:
    """Owner-invoked release and preparation, with no independent action state."""

    def __init__(self, build: BuildMgr, restoration: RestorationMagic) -> None:
        self.build: BuildMgr = build
        self._restoration: RestorationMagic = restoration
        self.bip_diagnostic: BipDiagnostic | None = None

    def observe(self, *, pending: bool, busy: bool) -> KaolaiObservation:
        """Read at most 64 roster entries at the owner's existing sample cadence."""
        from Py4GWCoreLib import AgentArray, Party
        from Py4GWCoreLib.FrameTree import FrameTree

        result = KaolaiObservation(pending=pending, busy=busy)
        result.loaded = Party.IsPartyLoaded()
        player_id = Player.GetAgentID()
        if not result.loaded or not Agent.IsValid(player_id):
            return result
        result.alive = Routines.Checks.Agents.IsAlive(player_id)
        if not result.alive:
            return result
        result.held = Agent.IsHoldingItem(player_id)
        result.self_hp = Routines.Checks.Agents.GetHealth(player_id)
        players, heroes, henchmen = Party.GetPlayers() or [], Party.GetHeroes() or [], Party.GetHenchmen() or []
        if len(players) + len(heroes) + len(henchmen) > 64:
            return result
        party_ids: set[int] = {
            Party.Players.GetAgentIDByLoginNumber(member.login_number) for member in players if member.is_connected
        }
        party_ids.update(member.agent_id for member in heroes)
        party_ids.update(member.agent_id for member in henchmen)
        allies = set(AgentArray.GetAllyArray())
        result.missing = len(party_ids - allies)
        position = Player.GetXY()
        health: list[tuple[int, float]] = []
        for aid in party_ids & allies:
            if aid <= 0 or not Agent.IsValid(aid):
                result.missing += 1
                continue
            if not dist(position, Agent.GetXY(aid)) <= Range.Spirit.value:
                result.outside += 1
                continue
            if not Routines.Checks.Agents.IsAlive(aid):
                result.dead += 1
                continue
            hp = Routines.Checks.Agents.GetHealth(aid)
            health.append((aid, hp))
            result.injured += int(0 < hp < 0.75)
            result.critical += int(0 < hp < 0.30)
        result.health = tuple(health)
        result.complete = True
        buttons = FrameTree.frames_at_path(5040781, [0, 0])
        result.button = bool(buttons and buttons[0].is_usable)
        return result

    def _observe_event(self, event: str) -> None:
        if self.bip_diagnostic is not None and not self.bip_diagnostic.done:
            self.bip_diagnostic.kaolai_event(event)

    def Protective_Was_Kaolai(self) -> BuildCoroutine:
        return (yield from self._restoration.Protective_Was_Kaolai())

    def _party_health(self, within_range: float) -> Iterator[tuple[int, float]]:
        """Preserve the routine census, including its shared-aware health helpers."""
        from Py4GWCoreLib import AgentArray, Party

        party_ids = {
            Party.Players.GetAgentIDByLoginNumber(member.login_number)
            for member in Party.GetPlayers() or []
            if member.is_connected
        }
        party_ids.update(member.agent_id for member in Party.GetHeroes() or [])
        party_ids.update(member.agent_id for member in Party.GetHenchmen() or [])
        ally_ids = set(AgentArray.GetAllyArray()) & party_ids
        player_pos = Player.GetXY()
        for aid in ally_ids:
            if aid <= 0 or not Agent.IsValid(aid):
                continue
            if not dist(player_pos, Agent.GetXY(aid)) <= within_range:
                continue
            if Routines.Checks.Agents.IsAlive(aid):
                yield aid, Routines.Checks.Agents.GetHealth(aid)

    def _emergency_health(self, recipients: list[tuple[int, float]]) -> list[float]:
        """Copy fresh remote HP once; uncertain publications cannot authorize emergency healing."""
        from Py4GWCoreLib import Map, Party
        from Py4GWCoreLib.GlobalCache import GLOBAL_CACHE
        from Py4GWCoreLib.GlobalCache.shared_memory_src.IntentSync import (
            get_uncached_tick_count64,
            publication_is_live,
        )

        player_id = Player.GetAgentID()
        context = (Map.GetMapID(), Map.GetRegion()[0], Map.GetDistrict(), Map.GetLanguage()[0])
        party_id = Party.GetPartyID()
        eligible = {aid for aid, _ in recipients if aid != player_id}
        remote: dict[int, float | None] = {}
        for account in GLOBAL_CACHE.ShMem.GetAllAccountData(sort_results=False):
            data = account.AgentData
            aid = int(data.AgentID)
            map_context = (data.Map.MapID, data.Map.Region, data.Map.District, data.Map.Language)
            if aid not in eligible or map_context != context or account.AgentPartyData.PartyID != party_id:
                continue
            if aid in remote:
                remote[aid] = None  # Competing same-party publications are ambiguous.
                continue
            remote[aid] = None
            stamp, login = int(account.LastUpdated), int(data.LoginNumber)
            hp = float(data.Health.Current)
            dead = bool(data.Is_Dead or data.Is_DeadByTypeMap)
            # These are live views. Reject observed changes and use the owning
            # uint32 freshness helper with a stricter, 250 ms emergency budget.
            if (
                account.IsSlotActive
                and account.IsAccount
                and login > 0
                and login == Agent.GetLoginNumber(aid)
                and (stamp, aid, login, party_id, context)
                == (
                    int(account.LastUpdated),
                    int(data.AgentID),
                    int(data.LoginNumber),
                    int(account.AgentPartyData.PartyID),
                    (data.Map.MapID, data.Map.Region, data.Map.District, data.Map.Language),
                )
                and publication_is_live(get_uncached_tick_count64(), stamp, 250)
                and not dead
                and 0 < hp <= 1
            ):
                remote[aid] = hp

        health: list[float] = []
        for aid, _ in recipients:
            if aid in remote:
                hp = remote[aid]
            else:
                hp = None if Agent.IsDead(aid) else Agent.GetHealth(aid)
            if hp is not None and 0 < hp <= 1:
                health.append(hp)
        return health

    def Drop_Emergency_Bundle(self, *, after_targeted_heals: bool = False) -> BuildCoroutine:
        """Submit for a serious group deficit, without estimating ash healing.

        At least two members must be below 40%, with a combined deficit of at
        least 30 percentage points to 50%. A member below 20% gets the existing
        targeted-rescue attempts first. Additional injured members do not veto
        emergency priority; no effect, item or rank checks apply.
        """
        from Py4GWCoreLib import Party

        if self.build._is_local_cast_pending() or not Party.IsPartyLoaded():  # pyright: ignore[reportPrivateUsage]
            return False
        player_id = Player.GetAgentID()
        if not Agent.IsHoldingItem(player_id):
            return False
        # Unavailable emergency evidence must not interrupt routine or spot heals.
        try:
            if not Agent.IsValid(player_id) or Agent.IsDead(player_id):
                return False
            recipients = list(self._party_health(Range.Spirit.value))
            if len(recipients) > 64:
                return False
            if sum(0 < hp < 0.40 for _, hp in recipients) < 2:
                return False
            if not after_targeted_heals and any(0 < hp < 0.20 for _, hp in recipients):
                return False
            health = self._emergency_health(recipients)
            if not after_targeted_heals and any(0 < hp < 0.20 for hp in health):
                return False
            serious = [hp for hp in health if 0 < hp < 0.40]
            # This is injury burden, NOT an estimate of restored HP. No rank,
            # maximum-health or Heroic Refrain assumption enters this heuristic.
            if len(serious) < 2 or sum(0.50 - hp for hp in serious) < 0.30:
                return False
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return False
        return (yield from self._submit_drop())

    def Drop_Held_Bundle(
        self,
        *,
        min_party_damaged_count: int = 4,
        health_threshold: float = 0.75,
        within_range: float = Range.Spirit.value,
    ) -> BuildCoroutine:
        """Submit a bundle release for enough injured nearby party members.

        Retain the existing party/ally intersection and Spirit-range limit.
        Generic holding is intentional; this is not positive ash identification.
        True means the click call returned, not that release or healing completed.
        """
        from Py4GWCoreLib import Party

        self._observe_event("drop_checked")
        # Use the pending-only gate; public cast checks also require energy/recharge.
        if self.build._is_local_cast_pending() or not Party.IsPartyLoaded():  # pyright: ignore[reportPrivateUsage]
            self._observe_event("pending_or_party_gate")
            return False

        player_id: int = Player.GetAgentID()

        if not Agent.IsHoldingItem(player_id):
            self._observe_event("no_generic_held_item")
            return False

        damaged_count = 0
        for _, health in self._party_health(within_range):
            if 0.0 < health < health_threshold:
                damaged_count += 1
                if damaged_count >= min_party_damaged_count:
                    break
        if damaged_count < min_party_damaged_count:
            self._observe_event("below_threshold")
            return False

        return (yield from self._submit_drop())

    def _submit_drop(self) -> BuildCoroutine:
        """Existing Python click submission; no release/healing receipt is available."""
        from Py4GWCoreLib.FrameTree import FrameTree

        # Preserve the FrameTree route; the drop-item keybind may be unbound.
        drop_buttons = FrameTree.frames_at_path(5040781, [0, 0])
        if not drop_buttons or not drop_buttons[0].is_usable:
            self._observe_event("button_unavailable")
            return False

        drop_buttons[0].click()
        # The owner must see the pending stamp before this generator yields.
        self.build._mark_local_cast_pending(250)  # pyright: ignore[reportPrivateUsage]
        self._observe_event("click_call_returned")
        yield
        return True
