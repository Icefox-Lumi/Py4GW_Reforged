"""My Blood is Power's recipient policy; the owner and BloodMagic execute it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Skill import Skill

if TYPE_CHECKING:
    from Py4GWCoreLib.BuildMgr import BuildMgr
    from Py4GWCoreLib.Builds.Skills.necromancer.BloodMagic import BloodMagic


class SmartBloodIsPower:
    """Propose the stock recipient without retaining targets or lifecycle state."""

    def __init__(self, build: BuildMgr, blood_magic: BloodMagic) -> None:
        self.build: BuildMgr = build
        self._blood_magic: BloodMagic = blood_magic

    def try_cast(self) -> BuildCoroutine:
        """Delegate one proposal; BloodMagic may reject it if eligibility changed."""
        skill_id = Skill.GetID("Blood_is_Power")
        if not self.build.IsSkillEquipped(skill_id):
            return False

        target_agent_id = self.build.ResolveAllyTarget(skill_id)
        if not target_agent_id:
            return False

        return (yield from self._blood_magic.Blood_is_Power(target_agent_id=target_agent_id))
