from __future__ import annotations

from collections.abc import Callable
from typing import Any
from typing import TYPE_CHECKING
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
from Py4GWCoreLib.Builds.Skills.SmartKaolai import SmartKaolai
from Py4GWCoreLib.Skill import Skill

if TYPE_CHECKING:
    from Py4GWCoreLib.Builds.Skills.BipDiagnostic import BipDiagnostic, Snapshot

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
        self._bip_diagnostic: BipDiagnostic | None = None
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
        self._smart_kaolai = SmartKaolai(self, self.skillbook.Ritualist.RestorationMagic)
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
            self._diagnostic_stop()
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
        self._diagnostic_stop()
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
        self._diagnostic_stop("ABORTED_CONTRACT_DISPOSED")
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
            self._diagnostic_stop()
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

    def _diagnostic_stop(self, reason: str = "ABORTED_SESSION_CHANGED") -> None:
        diagnostic = self._bip_diagnostic
        if diagnostic is None:
            return
        diagnostic.stop(reason)
        self._bip_diagnostic = None
        self.skillbook.Necromancer.BloodMagic.bip_diagnostic = None
        self.skillbook.Ritualist.RestorationMagic.bip_diagnostic = None
        self._smart_kaolai.bip_diagnostic = None

    def _diagnostic_begin(self) -> None:
        # Registry candidates never acquire a capture. Activation alone does not
        # start it either: only the selected owner's next aggro decision can.
        if not self._active:
            return
        diagnostic = self._bip_diagnostic
        try:
            if diagnostic is None or diagnostic.done:
                from Py4GWCoreLib.Builds.Skills.BipDiagnostic import pending_capture

                diagnostic = pending_capture("My Blood is Power")
            if diagnostic is None:
                return
            # Track every new pass, including entries rejected by the sample throttle.
            diagnostic.enter_decision()
            if not diagnostic.poll_due():
                return
            identity = None
            if Routines.Checks.Map.MapValid() and Map.IsExplorable():
                identity = (
                    Player.GetAgentID(),
                    Player.GetName(),
                    Map.GetMapID(),
                    Map.GetRegion()[0],
                    Map.GetDistrict(),
                    Map.GetLanguage()[0],
                    *self._get_current_skills(),
                )
            diagnostic.begin(identity, self.IsInAggro() if identity is not None else False, self._diagnostic_snapshot)
            if diagnostic.started is not None and not diagnostic.done:
                self._bip_diagnostic = diagnostic
                self.skillbook.Necromancer.BloodMagic.bip_diagnostic = diagnostic
                self.skillbook.Ritualist.RestorationMagic.bip_diagnostic = diagnostic
                self._smart_kaolai.bip_diagnostic = diagnostic
        except Exception:
            if diagnostic is not None:
                diagnostic.stop("ABORTED_OBSERVATION_ERROR")

    def _diagnostic_snapshot(self) -> Snapshot:
        from Py4GWCoreLib.Builds.Skills.BipDiagnostic import observe_build

        snapshot = observe_build(
            self,
            self.skillbook,
            cast_timer=self._local_cast_timer,
            weapon_allowed=self._meets_custom_skill_weapon_requirement,
            shared_allowed=self._meets_custom_skill_shared_conditions,
            uses_coordination=self._is_whiteboard_skill,
            target_allowed=self._validate_target_for_skill_cast,
        )
        snapshot.kaolai = self._smart_kaolai.observe(pending="pending" in snapshot.gates, busy="busy" in snapshot.gates)
        return snapshot

    def _diagnostic_finish(self, winner: str, *, preempted: bool = False) -> None:
        if self._bip_diagnostic is not None:
            self._bip_diagnostic.finish(winner, preempted=preempted)

    def _run_local_skill_logic(self) -> BuildCoroutine:
        self._diagnostic_begin()
        if not Routines.Checks.Skills.CanCast():
            self._diagnostic_finish("cannot_cast")
            return False

        restoration = self.skillbook.Ritualist.RestorationMagic
        soul_reaping = self.skillbook.Necromancer.SoulReaping
        if (yield from restoration.Spirit_Transfer(health_threshold=0.30)):
            self._diagnostic_finish("Spirit_Transfer", preempted=True)
            return True
        if (yield from restoration.Spirit_Light(health_threshold=0.30)):
            self._diagnostic_finish("Spirit_Light", preempted=True)
            return True
        if (yield from restoration.Mend_Body_and_Soul(health_threshold=0.40)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=True)
            return True
        if (yield from self._smart_kaolai.Drop_Held_Bundle(health_threshold=0.75)):
            self._diagnostic_finish("Drop_Held_Bundle", preempted=True)
            return True
        if (yield from soul_reaping.Signet_of_Lost_Souls(max_self_energy_pct=0.30)):
            self._diagnostic_finish("Signet_of_Lost_Souls", preempted=True)
            return True
        if (yield from restoration.Recuperation(min_party_damaged_count=6)):
            self._diagnostic_finish("Recuperation", preempted=True)
            return True
        if (yield from restoration.Recuperation(min_degen_count=6)):
            self._diagnostic_finish("Recuperation", preempted=True)
            return True
        if (yield from self.skillbook.Necromancer.BloodMagic.Blood_is_Power()):
            self._diagnostic_finish("Blood_is_Power", preempted=False)
            return True
        if (yield from restoration.Spirit_Transfer()):
            self._diagnostic_finish("Spirit_Transfer", preempted=False)
            return True
        if (yield from restoration.Mend_Body_and_Soul(cleanse_blind_martial=True)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True
        if (yield from restoration.Mend_Body_and_Soul(cleanse_cripple_melee=True)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True
        if (yield from restoration.Recuperation(min_party_damaged_count=6)):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True
        if (yield from restoration.Recuperation(min_degen_count=4)):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True
        if (yield from soul_reaping.Signet_of_Lost_Souls(max_self_energy_pct=0.60)):
            self._diagnostic_finish("Signet_of_Lost_Souls", preempted=False)
            return True
        if (yield from restoration.Life()):
            self._diagnostic_finish("Life", preempted=False)
            return True
        if (yield from restoration.Mend_Body_and_Soul(health_threshold=0.75)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True
        if (yield from self._smart_kaolai.Protective_Was_Kaolai()):
            self._diagnostic_finish("Protective_Was_Kaolai", preempted=False)
            return True
        if not self.IsInAggro():
            self._diagnostic_finish("idle")
            return False
        if (yield from soul_reaping.Signet_of_Lost_Souls()):
            self._diagnostic_finish("Signet_of_Lost_Souls", preempted=False)
            return True
        if (yield from restoration.Recuperation(min_party_damaged_count=6)):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True
        if (yield from restoration.Recuperation(min_degen_count=2)):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True
        if (yield from restoration.Mend_Body_and_Soul(health_threshold=0.85)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True
        if (yield from restoration.Spirit_Light()):
            self._diagnostic_finish("Spirit_Light", preempted=False)
            return True
        self._diagnostic_finish("none")
        return False
