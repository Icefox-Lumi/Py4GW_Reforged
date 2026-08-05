from __future__ import annotations

from typing import TYPE_CHECKING

from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Skill import Skill

if TYPE_CHECKING:
    from Py4GWCoreLib.BuildMgr import BuildMgr

__all__ = ["SpearMastery"]


class SpearMastery:
    def __init__(self, build: BuildMgr) -> None:
        self.build: BuildMgr = build

    def _resolve_spear_target(self, skill_id: int) -> int:
        if not self.build.CanCastSkillID(skill_id):
            return 0
        target_acquired, _ = self.build._resolve_target("EnemyInjured")
        if not target_acquired:
            return 0
        return self.build.current_target_id

    #region M
    def Mighty_Throw(self) -> BuildCoroutine:
        mighty_throw_id: int = Skill.GetID("Mighty_Throw")
        target_agent_id = self._resolve_spear_target(mighty_throw_id)
        if not target_agent_id:
            return False

        return (yield from self.build.CastSkillIDAndRestoreTarget(
            skill_id=mighty_throw_id,
            target_agent_id=target_agent_id,
            log=False,
            aftercast_delay=250,
        ))
    #endregion

