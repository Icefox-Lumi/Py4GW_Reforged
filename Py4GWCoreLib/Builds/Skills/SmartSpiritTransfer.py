"""My Blood is Power's Spirit Transfer policy; BuildMgr owns execution."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from Py4GWCoreLib import Range, Routines
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Skill import Skill

if TYPE_CHECKING:
    from Py4GWCoreLib.BuildMgr import BuildMgr
    from Py4GWCoreLib.Builds.Skills.BipDiagnostic import BipDiagnostic


class SmartSpiritTransfer:
    """Owner-invoked admission and targeting, without retained targets or actions."""

    def __init__(self, build: BuildMgr) -> None:
        self.build: BuildMgr = build
        self.bip_diagnostic: BipDiagnostic | None = None
        # GetCustomSkill belongs to this BuildMgr instance's private registry.
        # Configure it once for this owner's lifetime; stock registries stay intact.
        # Every Smart submission supplies the replacement donor condition below.
        build.GetCustomSkill(Skill.GetID("Spirit_Transfer")).Conditions.RequiresSpiritInEarshot = False

    @staticmethod
    def _has_donor() -> bool:
        return bool(cast(int, Routines.Agents.GetNearestSpirit(Range.Spellcast.value)))

    def try_cast(self, *, health_threshold: float | None = None) -> BuildCoroutine:
        skill_id = Skill.GetID("Spirit_Transfer")
        custom_skill = self.build.GetCustomSkill(skill_id)
        threshold = (
            health_threshold if health_threshold is not None else float(custom_skill.Conditions.LessLife or 0.50)
        )
        threshold = max(0.0, min(1.0, threshold))
        if not self.build.IsSkillEquipped(skill_id) or not self._has_donor():
            return False

        target_agent_id = self.build.ResolvePreferredAllyTarget(
            skill_id,
            custom_skill,
            validator=lambda agent_id: Agent.IsAlive(agent_id) and Agent.GetHealth(agent_id) < threshold,
        )
        if not target_agent_id:
            return False

        accepted = yield from self.build.CastSkillIDAndRestoreTarget(
            skill_id,
            target_agent_id,
            extra_condition=self._has_donor,
        )
        if accepted and self.bip_diagnostic is not None:
            self.bip_diagnostic.submission("heal", target_agent_id)
        return accepted
