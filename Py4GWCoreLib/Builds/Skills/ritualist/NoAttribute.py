from __future__ import annotations

from math import dist
from typing import TYPE_CHECKING

from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib import Range, Routines
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.Player import Player

if TYPE_CHECKING:
    from Py4GWCoreLib.BuildMgr import BuildMgr

__all__ = ["NoAttribute"]


class NoAttribute:
    def __init__(self, build: BuildMgr) -> None:
        self.build: BuildMgr = build

    # region D
    def Drop_Held_Bundle(
        self,
        *,
        min_party_damaged_count: int = 4,
        health_threshold: float = 0.65,
        within_range: float = Range.Spirit.value,
    ) -> BuildCoroutine:
        """Submit a bundle release for enough injured nearby party members.

        The Kaolai callers retain the existing ally population and Spirit-range
        limit until a reliable positive ash identity is established. Membership
        filtering only narrows that population; this is not the full party-area
        census and the generic holding check does not identify Kaolai's ashes.
        True means a click was submitted, not that release or healing completed.
        """
        from Py4GWCoreLib import AgentArray, Party
        from Py4GWCoreLib.FrameTree import FrameTree

        # Use the pending-only gate; public cast checks also require energy/recharge.
        if self.build._is_local_cast_pending() or not Party.IsPartyLoaded():  # pyright: ignore[reportPrivateUsage]
            return False

        player_id: int = Player.GetAgentID()

        if not Agent.IsHoldingItem(player_id):
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
            return False

        # Frame 5040781 is the in-game "Drop Bundle Button" (see
        # the FrameTree alias table). Clicking it directly is more
        # reliable than ControlAction_DropItem - the keybind silently no-ops if
        # the player hasn't bound a drop-item key in GW's controls.
        drop_buttons = FrameTree.frames_at_path(5040781, [0, 0])
        if not drop_buttons or not drop_buttons[0].is_usable:
            return False

        drop_buttons[0].click()
        # FrameClick isn't a CastSkillID-style cast, so BuildMgr's per-tick
        # aftercast timer isn't stamped automatically. Mark it manually so the
        # next tick doesn't fire another action while the engine is still
        # processing the drop. Stamp BEFORE yielding so the outer loop sees
        # the timer set on its very next pass.
        self.build._mark_local_cast_pending(250)
        yield  # Keep this a generator under BuildCoroutine; gives the engine
        # one tick to register the drop before the rotation continues.
        return True

    # endregion
