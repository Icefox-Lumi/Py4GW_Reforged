from __future__ import annotations

from typing import TYPE_CHECKING

from Py4GWCoreLib import Profession
from Py4GWCoreLib import Routines
from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI_Build
from Py4GWCoreLib import BuildMgr
from Py4GWCoreLib.Skill import Skill
from Py4GWCoreLib.Builds.Skills import SkillsTemplate

if TYPE_CHECKING:
    from Py4GWCoreLib.Builds.Skills.BipDiagnostic import BipDiagnostic, Snapshot



Blood_is_Power_ID = Skill.GetID("Blood_is_Power")
Signet_of_Lost_Souls_ID = Skill.GetID("Signet_of_Lost_Souls")
Mend_Body_and_Soul_ID = Skill.GetID("Mend_Body_and_Soul")
Spirit_Light_ID = Skill.GetID("Spirit_Light")
Protective_Was_Kaolai_ID = Skill.GetID("Protective_Was_Kaolai")
Vital_Weapon_ID = Skill.GetID("Vital_Weapon")
Wielders_Boon_ID = Skill.GetID("Wielders_Boon")
Mending_Grip_ID = Skill.GetID("Mending_Grip")
Spirit_Transfer_ID = Skill.GetID("Spirit_Transfer")
Life_ID = Skill.GetID("Life")
You_Are_All_Weaklings_ID = Skill.GetID("You_Are_All_Weaklings")
Enfeebling_Blood_ID = Skill.GetID("Enfeebling_Blood")
Recovery_ID = Skill.GetID("Recovery")
Breath_of_the_Great_Dwarf_ID = Skill.GetID("Breath_of_the_Great_Dwarf")
Recuperation_ID = Skill.GetID("Recuperation")
Blood_Bond_ID = Skill.GetID("Blood_Bond")
Ebon_Vanguard_Assassin_Support_ID = Skill.GetID("Ebon_Vanguard_Assassin_Support")


class Blood_is_Power_Healer(BuildMgr):
    _bip_diagnostic: BipDiagnostic | None = None

    def __init__(self, match_only: bool = False):
        super().__init__(
            name="Blood is Power Healer",
            required_primary=Profession.Necromancer,
            required_secondary=Profession.Ritualist,
            template_code="OAhjQkGZIP3hqq0EAAAAAAAAAA",
            required_skills=[
                Blood_is_Power_ID,
                Signet_of_Lost_Souls_ID,
                Mend_Body_and_Soul_ID,
            ],
            optional_skills=[
                Spirit_Light_ID,
                Protective_Was_Kaolai_ID,
                Vital_Weapon_ID,
                Wielders_Boon_ID,
                Mending_Grip_ID,
                Spirit_Transfer_ID,
                Life_ID,
                You_Are_All_Weaklings_ID,
                Enfeebling_Blood_ID,
                Recovery_ID,
                Breath_of_the_Great_Dwarf_ID,
                Recuperation_ID,
                Blood_Bond_ID,
                Ebon_Vanguard_Assassin_Support_ID,
            ],
        )
        if match_only:
            return

        self.SetFallback("HeroAI", HeroAI_Build(standalone_fallback=True))
        self.SetSkillCastingFn(self._run_local_skill_logic)
        self.skills: SkillsTemplate = SkillsTemplate(self)

    def Dispose(self, reason: str = "contract_disposed") -> None:
        if self._bip_diagnostic is not None:
            self._bip_diagnostic.stop()
        super().Dispose(reason)

    def _diagnostic_finish(self, winner: str, *, preempted: bool = False) -> None:
        if self._bip_diagnostic is not None:
            self._bip_diagnostic.finish(winner, preempted=preempted)

    def _diagnostic_begin(self) -> None:
        diagnostic = self._bip_diagnostic
        try:
            if diagnostic is None or diagnostic.done:
                from Py4GWCoreLib.Builds.Skills.BipDiagnostic import pending_capture

                diagnostic = pending_capture("Blood is Power Healer")
            if diagnostic is None:
                return
            # A new rotation entry owns no evidence from an interrupted predecessor.
            diagnostic.discard_pending()
            if not diagnostic.poll_due():
                return
            from Py4GWCoreLib import Map, Player

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
                self.skills.Necromancer.BloodMagic.bip_diagnostic = diagnostic
                self.skills.Ritualist.RestorationMagic.bip_diagnostic = diagnostic
        except Exception:
            if diagnostic is not None:
                diagnostic.stop("ABORTED_OBSERVATION_ERROR")

    def _diagnostic_snapshot(self) -> Snapshot:
        from Py4GWCoreLib.Builds.Skills.BipDiagnostic import observe_build

        return observe_build(
            self,
            self.skills,
            cast_timer=self._local_cast_timer,
            weapon_allowed=self._meets_custom_skill_weapon_requirement,
            shared_allowed=self._meets_custom_skill_shared_conditions,
            uses_coordination=self._is_whiteboard_skill,
            target_allowed=self._validate_target_for_skill_cast,
        )

    def _run_local_skill_logic(self):
        self._diagnostic_begin()
        if not Routines.Checks.Skills.CanCast():
            self._diagnostic_finish("cannot_cast", preempted=False)
            return False

        # emergency: Spirit Transfer when a spirit is in range and any ally is at or below 30% HP.
        if (yield from self.skills.Ritualist.RestorationMagic.Spirit_Transfer(health_threshold=0.30)):
            self._diagnostic_finish("Spirit_Transfer", preempted=True)
            return True

        # emergency: spirit-gated burst heal when any ally is at or below 30% HP.
        if (yield from self.skills.Ritualist.RestorationMagic.Spirit_Light(health_threshold=0.30)):
            self._diagnostic_finish("Spirit_Light", preempted=True)
            return True

        # emergency: any ally at or below 40% HP preempts everything.
        if (yield from self.skills.Ritualist.RestorationMagic.Mend_Body_and_Soul(health_threshold=0.40)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=True)
            return True

        # Kaolai release: four nearby party members below 75% HP.
        # Equipped plus holding does not identify the bundle; the shared helper
        # retains the conservative range until positive ash identity is established.
        if self.IsSkillEquipped(Protective_Was_Kaolai_ID) and (yield from self.skills.Ritualist.NoAttribute.Drop_Held_Bundle(health_threshold=0.75)):
            self._diagnostic_finish("Drop_Held_Bundle", preempted=True)
            return True

        # Signet of Lost Souls: emergency energy refill when caster < 30%.
        if (yield from self.skills.Necromancer.SoulReaping.Signet_of_Lost_Souls(max_self_energy_pct=0.30)):
            self._diagnostic_finish("Signet_of_Lost_Souls", preempted=True)
            return True

        # Recuperation 6+ allies below 75% HP OR 6+ allies degenning.
        if self.IsSkillEquipped(Recuperation_ID) and (yield from self.skills.Ritualist.RestorationMagic.Recuperation(
            min_party_damaged_count=6,
        )):
            self._diagnostic_finish("Recuperation", preempted=True)
            return True
        if self.IsSkillEquipped(Recuperation_ID) and (yield from self.skills.Ritualist.RestorationMagic.Recuperation(
            min_degen_count=6,
        )):
            self._diagnostic_finish("Recuperation", preempted=True)
            return True

        if (yield from self.skills.Necromancer.BloodMagic.Blood_is_Power()):
            self._diagnostic_finish("Blood_is_Power", preempted=False)
            return True

        if self.IsSkillEquipped(Wielders_Boon_ID) and (yield from self.skills.Ritualist.RestorationMagic.Wielders_Boon()):
            self._diagnostic_finish("Wielders_Boon", preempted=False)
            return True

        if self.IsSkillEquipped(Mending_Grip_ID) and (yield from self.skills.Ritualist.RestorationMagic.Mending_Grip()):
            self._diagnostic_finish("Mending_Grip", preempted=False)
            return True

        if self.IsSkillEquipped(Spirit_Transfer_ID) and (yield from self.skills.Ritualist.RestorationMagic.Spirit_Transfer()):
            self._diagnostic_finish("Spirit_Transfer", preempted=False)
            return True

        # spirit-gated cleanse: blind on a martial (melee/ranger/paragon).
        if (yield from self.skills.Ritualist.RestorationMagic.Mend_Body_and_Soul(cleanse_blind_martial=True)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True

        # spirit-gated cleanse: cripple on a melee ally.
        if (yield from self.skills.Ritualist.RestorationMagic.Mend_Body_and_Soul(cleanse_cripple_melee=True)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True

        # Recuperation: 6+ allies below 75% HP OR 4+ allies degenning.
        if self.IsSkillEquipped(Recuperation_ID) and (yield from self.skills.Ritualist.RestorationMagic.Recuperation(
            min_party_damaged_count=6,
        )):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True
        if self.IsSkillEquipped(Recuperation_ID) and (yield from self.skills.Ritualist.RestorationMagic.Recuperation(
            min_degen_count=4,
        )):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True

        if self.IsSkillEquipped(Ebon_Vanguard_Assassin_Support_ID) and (yield from self.skills.Any.PvE.Ebon_Vanguard_Assassin_Support(min_self_energy_pct=0.40)):
            self._diagnostic_finish("Ebon_Vanguard_Assassin_Support", preempted=False)
            return True

        # Signet of Lost Souls : energy refill when caster < 60%.
        if (yield from self.skills.Necromancer.SoulReaping.Signet_of_Lost_Souls(max_self_energy_pct=0.60)):
            self._diagnostic_finish("Signet_of_Lost_Souls", preempted=False)
            return True

        if self.IsSkillEquipped(Blood_Bond_ID) and (yield from self.skills.Necromancer.BloodMagic.Blood_Bond()):
            self._diagnostic_finish("Blood_Bond", preempted=False)
            return True

        # Life: spirit prep. Self-gated on aggro/close-to-aggro and on
        # SpiritBuffExists, so safe to fire before the MBaS @75% tier and
        # before the IsInAggro build gate.
        if self.IsSkillEquipped(Life_ID) and (yield from self.skills.Ritualist.RestorationMagic.Life()):
            self._diagnostic_finish("Life", preempted=False)
            return True

        # damaged: any ally at or below 75% HP, before combat skills.
        if (yield from self.skills.Ritualist.RestorationMagic.Mend_Body_and_Soul(health_threshold=0.75)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True

        # Protective Was Kaolai: arm the next party-heal-on-drop. Cast on
        # cooldown when not already holding a bundle - keeps ashes ready so
        # Drop_Held_Bundle has something to release on the next damage spike.
        if self.IsSkillEquipped(Protective_Was_Kaolai_ID) and (yield from self.skills.Ritualist.RestorationMagic.Protective_Was_Kaolai()):
            self._diagnostic_finish("Protective_Was_Kaolai", preempted=False)
            return True

        if not self.IsInAggro():
            self._diagnostic_finish("idle", preempted=False)
            return False

        if self.IsSkillEquipped(Vital_Weapon_ID) and (yield from self.skills.Ritualist.Communing.Vital_Weapon()):
            self._diagnostic_finish("Vital_Weapon", preempted=False)
            return True

        if self.IsSkillEquipped(Recovery_ID) and (yield from self.skills.Ritualist.RestorationMagic.Recovery()):
            self._diagnostic_finish("Recovery", preempted=False)
            return True

        # Signet of Lost Souls: opportunistic refill, no caster energy gate.
        if (yield from self.skills.Necromancer.SoulReaping.Signet_of_Lost_Souls()):
            self._diagnostic_finish("Signet_of_Lost_Souls", preempted=False)
            return True

        # Recuperation: 6+ allies below 75% HP OR 2+ allies degenning.
        if self.IsSkillEquipped(Recuperation_ID) and (yield from self.skills.Ritualist.RestorationMagic.Recuperation(
            min_party_damaged_count=6,
        )):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True
        if self.IsSkillEquipped(Recuperation_ID) and (yield from self.skills.Ritualist.RestorationMagic.Recuperation(
            min_degen_count=2,
        )):
            self._diagnostic_finish("Recuperation", preempted=False)
            return True

        # preventive: any ally at or below 85% HP, after Recuperation.
        if (yield from self.skills.Ritualist.RestorationMagic.Mend_Body_and_Soul(health_threshold=0.85)):
            self._diagnostic_finish("Mend_Body_and_Soul", preempted=False)
            return True

        if self.IsSkillEquipped(Breath_of_the_Great_Dwarf_ID) and (yield from self.skills.Any.NoAttribute.Breath_of_the_Great_Dwarf()):
            self._diagnostic_finish("Breath_of_the_Great_Dwarf", preempted=False)
            return True

        if self.IsSkillEquipped(You_Are_All_Weaklings_ID) and (yield from self.skills.Any.NoAttribute.You_Are_All_Weaklings()):
            self._diagnostic_finish("You_Are_All_Weaklings", preempted=False)
            return True

        if self.IsSkillEquipped(Enfeebling_Blood_ID) and (yield from self.skills.Necromancer.Curses.Enfeebling_Blood()):
            self._diagnostic_finish("Enfeebling_Blood", preempted=False)
            return True

        if (yield from self.skills.Ritualist.RestorationMagic.Spirit_Light()):
            self._diagnostic_finish("Spirit_Light", preempted=False)
            return True

        self._diagnostic_finish("none")
        return False
