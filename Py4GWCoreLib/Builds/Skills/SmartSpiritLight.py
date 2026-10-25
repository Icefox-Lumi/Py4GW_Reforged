"""My Blood is Power's spirit-supported Spirit Light policy."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from Py4GWCoreLib import Range
from Py4GWCoreLib import Routines
from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Skill import Skill

if TYPE_CHECKING:
    from Py4GWCoreLib.BuildMgr import BuildMgr
    from Py4GWCoreLib.Builds.Skills.BipDiagnostic import BipDiagnostic


class SmartSpiritLight:
    """Owner-invoked admission and targeting, with no sacrifice fallback."""

    def __init__(self, build: BuildMgr) -> None:
        self.build: BuildMgr = build
        self.bip_diagnostic: BipDiagnostic | None = None

    @staticmethod
    def _has_spirit_in_earshot() -> bool:
        return bool(cast(int, Routines.Agents.GetNearestSpirit(Range.Earshot.value)))

    def try_cast(self, *, health_threshold: float | None = None) -> BuildCoroutine:
        skill_id = Skill.GetID("Spirit_Light")
        custom_skill = self.build.GetCustomSkill(skill_id)
        threshold = (
            health_threshold if health_threshold is not None else float(custom_skill.Conditions.LessLife or 0.60)
        )
        threshold = max(0.0, min(1.0, threshold))
        if not self.build.IsSkillEquipped(skill_id) or not self._has_spirit_in_earshot():
            return False

        target_agent_id = self.build.ResolvePreferredAllyTarget(
            skill_id,
            custom_skill,
            validator=lambda agent_id: Agent.IsAlive(agent_id) and Agent.GetHealth(agent_id) < threshold,
        )
        if not target_agent_id:
            return False

        # Keep RequiresSpiritInEarshot intact; this callback additionally rejects
        # pets and rechecks genuine-spirit availability at both owner admissions.
        accepted = yield from self.build.CastSkillIDAndRestoreTarget(
            skill_id,
            target_agent_id,
            extra_condition=self._has_spirit_in_earshot,
        )
        if accepted and self.bip_diagnostic is not None:
            self.bip_diagnostic.submission("heal", target_agent_id)
        return accepted
