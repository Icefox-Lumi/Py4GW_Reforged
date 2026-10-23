"""My Blood is Power's Kaolai policy; the build retains action ownership.

Holding an item does not identify Kaolai ashes. Positive ash identity remains
a prerequisite for any future emergency rule or wider release census.
"""

from __future__ import annotations

from collections import Counter
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

    def Drop_Held_Bundle(
        self,
        *,
        min_party_damaged_count: int = 4,
        health_threshold: float = 0.75,
        within_range: float = Range.Spirit.value,
    ) -> BuildCoroutine:
        """Submit a bundle release for enough injured nearby party members.

        Retain the existing ally population and Spirit-range limit until a
        reliable positive ash identity is established. Membership filtering
        only narrows that population; this is not the full party-area census.
        True means the click call returned, not that release or healing completed.
        """
        from Py4GWCoreLib import AgentArray, Party
        from Py4GWCoreLib.FrameTree import FrameTree

        self._observe_event("drop_checked")
        # Use the pending-only gate; public cast checks also require energy/recharge.
        if self.build._is_local_cast_pending() or not Party.IsPartyLoaded():  # pyright: ignore[reportPrivateUsage]
            self._observe_event("pending_or_party_gate")
            return False

        player_id: int = Player.GetAgentID()

        if not Agent.IsHoldingItem(player_id):
            self._observe_event("no_generic_held_item")
            return False

        party_ids: set[int] = {
            Party.Players.GetAgentIDByLoginNumber(member.login_number)
            for member in Party.GetPlayers() or []
            if member.is_connected
        }
        party_ids.update(member.agent_id for member in Party.GetHeroes() or [])
        party_ids.update(member.agent_id for member in Party.GetHenchmen() or [])

        # Intersect, rather than add roster members missing from the old census:
        # broadening release eligibility is unsafe while bundle identity is unknown.
        ally_ids: set[int] = set(AgentArray.GetAllyArray()) & party_ids
        player_pos = Player.GetXY()

        damaged_count = 0
        for aid in ally_ids:
            if aid <= 0 or not Agent.IsValid(aid):
                continue
            if not dist(player_pos, Agent.GetXY(aid)) <= within_range:
                continue
            # Preserve same-party remote-player health/liveness evidence.
            if not Routines.Checks.Agents.IsAlive(aid):
                continue
            health = Routines.Checks.Agents.GetHealth(aid)
            if 0.0 < health < health_threshold:
                damaged_count += 1
                if damaged_count >= min_party_damaged_count:
                    break
        if damaged_count < min_party_damaged_count:
            self._observe_event("below_threshold")
            return False

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
