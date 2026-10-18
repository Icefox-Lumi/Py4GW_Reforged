from __future__ import annotations

from collections.abc import Callable
from typing import Any
from typing import Protocol
from typing import cast

from Py4GWCoreLib import BuildMgr
from Py4GWCoreLib import Map
from Py4GWCoreLib import Player
from Py4GWCoreLib import Profession
from Py4GWCoreLib import Routines
from Py4GWCoreLib.BuildMgr import BuildCoroutine
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build
from Py4GWCoreLib.Builds.Skills import SkillsTemplate
from Py4GWCoreLib.Skill import Skill

_SKILL_IDS: tuple[int, ...] = (
    Skill.GetID("Blood_is_Power"),
    Skill.GetID("Spirit_Transfer"),
    Skill.GetID("Mend_Body_and_Soul"),
    Skill.GetID("Spirit_Light"),
    Skill.GetID("Protective_Was_Kaolai"),
    Skill.GetID("Life"),
    Skill.GetID("Recuperation"),
    Skill.GetID("Signet_of_Lost_Souls"),
)


class _MaskedCombat(Protocol):
    blocked_skill_ids: set[int]

    def ApplyBlockedSkillIDs(self, blocked_skill_ids: list[int] | None = None) -> None: ...


class MyBloodIsPower(BuildMgr):
    """Exact N/Rt bar, with the generic healer's eight-skill decision order."""

    def __init__(self, cached_data: Any = None, match_only: bool = False) -> None:
        super().__init__(
            name="My Blood is Power",
            required_primary=Profession.Necromancer,
            required_secondary=Profession.Ritualist,
            template_code="OAhjQgGaIP3Bhn0cyNMHnVvqK",
            required_skills=list(_SKILL_IDS),
        )
        self._active = False
        self._generation = 0
        self._identity: tuple[str, str, int, int, int, int, int] | None = None
        self._bar: tuple[int, ...] = ()
        self._uptime: tuple[int, int] = (0, 0)
        self._mask_handler: _MaskedCombat | None = None
        self._applied_mask: set[int] | None = None
        self._cached_data = cached_data
        if match_only:
            return

        self._fallback = HeroAI_Build(cached_data=cached_data, standalone_fallback=True)
        self.SetFallback("HeroAI", self._fallback)
        self.skillbook = SkillsTemplate(self)
        self.SetSkillCastingFn(self._run_local_skill_logic)

    def ScoreMatch(
        self,
        current_primary: Profession | None = None,
        current_secondary: Profession | None = None,
        current_skills: list[int] | None = None,
    ) -> int:
        skills = self._get_current_skills() if current_skills is None else current_skills
        if len(skills) != 8 or 0 in skills or len(set(skills)) != 8 or set(skills) != set(_SKILL_IDS):
            return -1
        # BuildMgr's profession parameters are currently unannotated.
        base_match: Callable[[Profession | None, Profession | None, list[int]], int] = cast(Any, super()).ScoreMatch
        score = base_match(current_primary, current_secondary, skills)
        return 1000 + score if score >= 0 else -1

    def set_cached_data(self, cached_data: Any) -> None:
        if cached_data is not self._cached_data:
            self._release_fallback_mask()
            self._identity = None
            self._generation += 1
        super().set_cached_data(cached_data)
        if hasattr(self, "_fallback"):
            self._fallback.set_cached_data(cached_data)

    def OnContractActivated(self, cached_data: Any = None) -> None:
        super().OnContractActivated(cached_data)
        self._active = True
        if self._sync_context():
            self._apply_fallback_skill_mask(self._fallback)

    def _apply_fallback_skill_mask(self, fallback_handler: BuildMgr | None) -> None:
        super()._apply_fallback_skill_mask(fallback_handler)
        if fallback_handler is self._fallback:
            handler = cast(_MaskedCombat | None, getattr(self._fallback._cached_data, "combat_handler", None))
            if handler is not None:
                self._mask_handler = handler
                self._applied_mask = handler.blocked_skill_ids

    def _release_fallback_mask(self) -> None:
        handler = self._mask_handler
        # Combat replaces this set on every mask application. Identity protects
        # a successor's mask even when it happens to contain the same skill IDs.
        if handler is not None and handler.blocked_skill_ids is self._applied_mask:
            handler.ApplyBlockedSkillIDs([])
        self._mask_handler = None
        self._applied_mask = None

    def _reset_runtime_state(self) -> None:
        self._generation += 1
        self.ResetTarget()
        self.priority_target = 0
        self._resolved_self_agent_id = 0
        self._was_in_aggro = False
        self.ResetPartyHealthMonitor()
        self._local_cast_timer.Stop()
        self._auto_attack_timer.Stop()
        self._auto_attack_time = 0
        self.ResetTickState()
        # Ordinary queued requests and their shared coordination leases retain
        # their existing lifetime; disposal is not native queue cancellation.
        self._wb_prev_cast_pending = False
        self._wb_posted_this_cast = False
        self._wb_posted_claim = None
        if hasattr(self, "skillbook"):
            self.skillbook.Necromancer.BloodMagic.bip_throttle.Stop()
            self._fallback.ClearBuildContract()

    def Dispose(self, reason: str = "contract_disposed") -> None:
        self._active = False
        self._release_fallback_mask()
        self._reset_runtime_state()
        self._identity = None
        self._bar = ()
        self._uptime = (0, 0)
        super().Dispose(reason)

    def _sync_context(self) -> bool:
        if not self._active:
            return False
        if not Routines.Checks.Map.MapValid() or not Map.IsExplorable() or self.ScoreMatch() < 0:
            # The outer contract may keep the same signature after a transient
            # invalid frame. Remain selected so its next valid tick can recover.
            self._release_fallback_mask()
            self._reset_runtime_state()
            self._identity = None
            self._bar = ()
            self._uptime = (0, 0)
            return False

        identity = (
            Player.GetAccountEmail(),
            Player.GetName(),
            Player.GetAgentID(),
            Map.GetMapID(),
            Map.GetRegion()[0],
            Map.GetDistrict(),
            Map.GetLanguage()[0],
        )
        uptime = (Map.GetInstanceUptime(), Player.GetInstanceUptime())
        bar = tuple(self._get_current_skills())
        if identity != self._identity or any(now < before for now, before in zip(uptime, self._uptime)):
            self._reset_runtime_state()
            self._identity = identity
        elif bar != self._bar:
            # Reordered slots invalidate suspended work, but do not reset a
            # same-character cast window or the shared helper's BiP throttle.
            self._generation += 1
        self._uptime = uptime
        self._bar = bar
        return True

    def ProcessSkillCasting(self) -> BuildCoroutine:
        if not self._sync_context():
            return
        self._apply_fallback_skill_mask(self._fallback)
        generation = self._generation
        coroutine = super().ProcessSkillCasting()
        try:
            while self._sync_context() and generation == self._generation:
                try:
                    value = next(coroutine)
                except StopIteration:
                    return
                yield value
        finally:
            # Prevent an old spirit wait / target restore from resuming in a
            # different context. Calls already submitted to the queue remain.
            coroutine.close()

    def _run_local_skill_logic(self) -> BuildCoroutine:
        if not Routines.Checks.Skills.CanCast():
            return False

        restoration = self.skillbook.Ritualist.RestorationMagic
        soul_reaping = self.skillbook.Necromancer.SoulReaping
        if (yield from restoration.Spirit_Transfer(health_threshold=0.30)):
            return True
        if (yield from restoration.Spirit_Light(health_threshold=0.30)):
            return True
        if (yield from restoration.Mend_Body_and_Soul(health_threshold=0.40)):
            return True
        if (yield from self.skillbook.Ritualist.NoAttribute.Drop_Held_Bundle(health_threshold=0.75)):
            return True
        if (yield from soul_reaping.Signet_of_Lost_Souls(max_self_energy_pct=0.30)):
            return True
        if (yield from restoration.Recuperation(min_party_damaged_count=6)):
            return True
        if (yield from restoration.Recuperation(min_degen_count=6)):
            return True
        if (yield from self.skillbook.Necromancer.BloodMagic.Blood_is_Power()):
            return True
        if (yield from restoration.Spirit_Transfer()):
            return True
        if (yield from restoration.Mend_Body_and_Soul(cleanse_blind_martial=True)):
            return True
        if (yield from restoration.Mend_Body_and_Soul(cleanse_cripple_melee=True)):
            return True
        if (yield from restoration.Recuperation(min_party_damaged_count=6)):
            return True
        if (yield from restoration.Recuperation(min_degen_count=4)):
            return True
        if (yield from soul_reaping.Signet_of_Lost_Souls(max_self_energy_pct=0.60)):
            return True
        if (yield from restoration.Life()):
            return True
        if (yield from restoration.Mend_Body_and_Soul(health_threshold=0.75)):
            return True
        if (yield from restoration.Protective_Was_Kaolai()):
            return True
        if not self.IsInAggro():
            return False
        if (yield from soul_reaping.Signet_of_Lost_Souls()):
            return True
        if (yield from restoration.Recuperation(min_party_damaged_count=6)):
            return True
        if (yield from restoration.Recuperation(min_degen_count=2)):
            return True
        if (yield from restoration.Mend_Body_and_Soul(health_threshold=0.85)):
            return True
        if (yield from restoration.Spirit_Light()):
            return True
        return False
