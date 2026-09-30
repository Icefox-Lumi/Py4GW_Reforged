"""Personal My Mesmer composition with dynamic smart-skill ownership."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from typing import cast

from Py4GWCoreLib.BuildMgr import BuildMgr
from Py4GWCoreLib.Builds.Skills.SmartComplicate import COMPLICATE_SKILL_ID
from Py4GWCoreLib.Builds.Skills.SmartComplicateController import SmartComplicateController
from Py4GWCoreLib.Builds.Skills.SmartComplicateController import SmartCryComplicateCoordinator
from Py4GWCoreLib.Builds.Skills.SmartCryController import SmartCryController
from Py4GWCoreLib.Builds.Skills.SmartCryController import get_cry_of_frustration_id
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import DAMAGE_PER_ENERGY
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import DECISION_INTERVAL_MS
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import DEFAULT_POLICY
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import FOCUS_CHALLENGER_STABILITY_MS
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import FOCUS_GAP_GRACE_MS
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import FOCUS_MINIMUM_OVERLAP_RATIO
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import FOCUS_SWITCH_VALUE_RATIO
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import LOW_HP_THRESHOLD
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import MATCH_SCORE_BONUS
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import MAXIMUM_FOREIGN_RESERVATIONS
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import MINIMUM_EXPECTED_PACKET_DAMAGE
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import PROFESSION_MAX_ENERGY
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import SUPPORTED_HANDLER_FACTORIES
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import UNKNOWN_MAX_ENERGY
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import CandidateReason
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import DecisionReason
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import Energy_Surge_ID
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import EnergySurgeCandidateEvaluation
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import EnergySurgeController
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import EnergySurgeDecision
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import EnergySurgeEnemyObservation
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import EnergySurgeGroupEvaluation
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import EnergySurgePolicy
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import ForeignReservationProjection
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import LegacyEnergySurgeController
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import My_Energy_Surge
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import SmartEnergySurgeHandler
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import evaluate_energy_surge
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import get_energy_surge_id
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import get_supported_handler_factories
from Py4GWCoreLib.Builds.Skills.SmartEnergySurge import infer_max_energy
from Py4GWCoreLib.Builds.Skills.SmartUnnaturalSignet import UNNATURAL_SIGNET_SKILL_ID
from Py4GWCoreLib.Builds.Skills.SmartUnnaturalSignet import SmartUnnaturalSignet


class MyMesmer(BuildMgr):
    """One personal Mesmer composition with one shared HeroAI fallback."""

    def __init__(self, match_only: bool = False):
        from Py4GWCoreLib import Profession

        super().__init__(
            name="My Mesmer",
            required_primary=Profession.Mesmer,
            required_secondary=Profession(0),
            template_code="OQBCAswEc5Jw0zuoNopTOggD",
            required_skills=[],
            optional_skills=[],
        )
        self._active_handlers: dict[int, Any] = {}
        self._skill_slots: dict[int, int] = {}
        self._equipped_bar: tuple[int, ...] | None = None
        self._smart_owned_skill_ids: tuple[int, ...] = ()
        self._composition_generation = 0
        self._disposed = False
        self._last_composition_error: str | None = None

        if match_only:
            return

        from Py4GWCoreLib.Builds.Any.HeroAI import HeroAI as HeroAIBuild

        self.SetFallback("HeroAI", HeroAIBuild(standalone_fallback=True))

    def ScoreMatch(
        self,
        current_primary=None,
        current_secondary=None,
        current_skills: list[int] | None = None,
    ) -> int:
        """Keep the personal composition eligible for every primary Mesmer bar."""

        base_score = super().ScoreMatch(
            current_primary=current_primary,
            current_secondary=current_secondary,
            current_skills=current_skills,
        )
        if base_score < 0:
            return -1
        return MATCH_SCORE_BONUS + base_score

    def ValidateSkills(self) -> Generator[None, None, bool]:
        """A composition accepts bar changes instead of validating one template."""

        yield
        return True

    @property
    def active_smart_ids(self) -> tuple[int, ...]:
        return self._smart_owned_skill_ids

    @property
    def active_handlers(self) -> dict[int, Any]:
        return dict(self._active_handlers)

    @property
    def skill_slots(self) -> dict[int, int]:
        return dict(self._skill_slots)

    @property
    def composition_generation(self) -> int:
        return self._composition_generation

    def GetActiveSmartSkillIDs(self) -> list[int]:
        return list(self._smart_owned_skill_ids)

    def GetActiveHandlers(self) -> dict[int, Any]:
        return dict(self._active_handlers)

    def GetSkillSlots(self) -> dict[int, int]:
        return dict(self._skill_slots)

    def _read_equipped_bar(self) -> tuple[int, ...] | None:
        from Py4GWCoreLib.Skillbar import SkillBar

        skills: list[int] = []
        for slot_index in range(1, 9):
            try:
                raw_skill_id = SkillBar.GetSkillIDBySlot(slot_index)
            except Exception:
                return None
            if raw_skill_id is None:
                skills.append(0)
                continue
            try:
                skill_id = int(raw_skill_id)
            except (TypeError, ValueError):
                return None
            skills.append(skill_id if skill_id > 0 else 0)
        return tuple(skills)

    def _report_composition_error(self, message: str) -> None:
        if message == self._last_composition_error:
            return
        self._last_composition_error = message
        try:
            from Py4GWCoreLib import ConsoleLog

            ConsoleLog(self.build_name, message)
        except Exception:
            return

    def _resolve_handler_factories(self) -> dict[int, type[Any]]:
        try:
            supported_factories = get_supported_handler_factories()
            factories: dict[int, type[Any]] = {
                int(skill_id): cast(type[Any], factory) for skill_id, factory in supported_factories.items()
            }
        except Exception as error:
            self._report_composition_error(f"smart registry unavailable: {type(error).__name__}")
            factories = {
                int(skill_id): cast(type[Any], factory) for skill_id, factory in SUPPORTED_HANDLER_FACTORIES.items()
            }
        try:
            cry_skill_id = get_cry_of_frustration_id()
            if cry_skill_id > 0:
                factories[int(cry_skill_id)] = SmartCryController
        except Exception as error:
            self._report_composition_error(f"smart Cry unavailable: {type(error).__name__}")
        else:
            self._last_composition_error = None
        factories[COMPLICATE_SKILL_ID] = SmartComplicateController
        factories[UNNATURAL_SIGNET_SKILL_ID] = SmartUnnaturalSignet
        return factories

    def _refresh_composition(self) -> bool:
        equipped_bar = self._read_equipped_bar()
        if equipped_bar is None:
            self._report_composition_error("equipped bar snapshot unavailable")
            return False

        factories = self._resolve_handler_factories()
        owned_id_list: list[int] = []
        seen_owned_ids: set[int] = set()
        for skill_id in equipped_bar:
            if skill_id > 0 and skill_id in factories and skill_id not in seen_owned_ids:
                owned_id_list.append(skill_id)
                seen_owned_ids.add(skill_id)
        owned_ids = tuple(owned_id_list)
        previous_ids = set(self._active_handlers)
        for removed_skill_id in previous_ids - set(owned_ids):
            self._active_handlers[removed_skill_id].dispose("skill_removed")

        next_handlers: dict[int, Any] = {}
        for skill_id in owned_ids:
            handler = self._active_handlers.get(skill_id)
            if handler is None:
                try:
                    handler = factories[skill_id](skill_id=skill_id)
                except Exception as error:
                    self._report_composition_error(f"smart handler {skill_id} creation failed: {type(error).__name__}")
                    continue
            next_handlers[skill_id] = handler

        slot_by_skill: dict[int, int] = {}
        for slot_index, skill_id in enumerate(equipped_bar, start=1):
            if skill_id > 0:
                slot_by_skill.setdefault(skill_id, slot_index)
        for skill_id, handler in next_handlers.items():
            set_skill_slot = getattr(handler, "set_skill_slot", None)
            if callable(set_skill_slot):
                set_skill_slot(slot_by_skill.get(skill_id))

        if self._equipped_bar != equipped_bar:
            self._composition_generation += 1
        self._equipped_bar = equipped_bar
        self._skill_slots = slot_by_skill
        self._active_handlers = next_handlers
        self._smart_owned_skill_ids = owned_ids
        self.SetBlockedSkills(list(owned_ids))
        return True

    def _handler_result(self, handler: Any) -> Generator[None, None, bool]:
        result = handler.try_cast()
        if hasattr(result, "__next__"):
            result = yield from result
        return bool(result)

    @staticmethod
    def _handler_has_active_dispatch(handler: Any) -> bool:
        """Keep a second smart handler from preempting an in-flight cast."""

        explicit_check = getattr(handler, "has_active_dispatch", None)
        if callable(explicit_check):
            try:
                return bool(explicit_check())
            except Exception:
                return True
        if getattr(handler, "_active_reservation", None) is not None:
            return True
        pending_check = getattr(handler, "_is_local_cast_pending", None)
        if not callable(pending_check):
            return False
        try:
            return bool(pending_check())
        except Exception:
            return True

    def ProcessSkillCasting(self) -> Generator[None, None, Any]:
        if False:
            yield
        if self._disposed:
            yield
            return False

        clear_whiteboard = getattr(self, "_whiteboard_owner_self_clear", None)
        if callable(clear_whiteboard):
            clear_whiteboard()

        # Lifecycle/bar ownership must settle before any process gate or fallback.
        self.ResetTickState()
        self._refresh_composition()

        ready_handlers: list[tuple[int, Any]] = []
        for skill_id, handler in tuple(self._active_handlers.items()):
            try:
                handler.update_lifecycle(self._composition_generation)
                ready_handlers.append((skill_id, handler))
            except Exception as error:
                handler.cancel_pending("handler_lifecycle_exception")
                self._report_composition_error(f"smart handler {skill_id} failed: {type(error).__name__}")

        can_process = getattr(self, "CanProcess", None)
        if callable(can_process):
            try:
                if not can_process():
                    yield
                    return False
            except Exception:
                yield
                return False

        smart_interrupt_skill_ids = {COMPLICATE_SKILL_ID}
        try:
            smart_interrupt_skill_ids.add(get_cry_of_frustration_id())
        except Exception:
            pass
        smart_interrupt_handlers = tuple(
            handler
            for skill_id, handler in ready_handlers
            if skill_id in smart_interrupt_skill_ids
            and callable(getattr(handler, "build_interrupt_proposal", None))
            and callable(getattr(handler, "try_cast_selected", None))
        )
        prioritized_skill_ids: set[int] = set()
        if len(smart_interrupt_handlers) > 1:
            prioritized_skill_ids.update(
                skill_id for skill_id, handler in ready_handlers if handler in smart_interrupt_handlers
            )
            other_handler_active = any(
                handler not in smart_interrupt_handlers and self._handler_has_active_dispatch(handler)
                for _skill_id, handler in ready_handlers
            )
            if not other_handler_active:
                try:
                    coordinator = SmartCryComplicateCoordinator()
                    if (yield from coordinator.try_cast(smart_interrupt_handlers)):
                        self.SetTickSuccess()
                        return True
                except Exception as error:
                    for handler in smart_interrupt_handlers:
                        try:
                            handler.cancel_pending("chooser_exception")
                        except Exception:
                            pass
                    self._report_composition_error(f"smart interrupt chooser failed: {type(error).__name__}")

        elif len(smart_interrupt_handlers) == 1:
            interrupt_skill_id, interrupt_handler = next(
                (skill_id, handler) for skill_id, handler in ready_handlers if handler in smart_interrupt_handlers
            )
            prioritized_skill_ids.add(interrupt_skill_id)
            try:
                if (yield from self._handler_result(interrupt_handler)):
                    self.SetTickSuccess()
                    return True
            except Exception as error:
                interrupt_handler.cancel_pending("handler_exception")
                self._report_composition_error(f"smart handler {interrupt_skill_id} failed: {type(error).__name__}")

        try:
            energy_surge_skill_id: int | None = get_energy_surge_id()
        except Exception:
            energy_surge_skill_id = None
        energy_surge_entry = next(
            (
                (skill_id, handler)
                for skill_id, handler in ready_handlers
                if energy_surge_skill_id is not None and skill_id == energy_surge_skill_id
            ),
            None,
        )
        if energy_surge_entry is not None:
            energy_surge_skill_id, energy_surge_handler = energy_surge_entry
            prioritized_skill_ids.add(energy_surge_skill_id)
            try:
                if (yield from self._handler_result(energy_surge_handler)):
                    self.SetTickSuccess()
                    return True
            except Exception as error:
                energy_surge_handler.cancel_pending("handler_exception")
                self._report_composition_error(f"smart handler {energy_surge_skill_id} failed: {type(error).__name__}")

        for skill_id, handler in ready_handlers:
            if skill_id in prioritized_skill_ids:
                continue
            try:
                if (yield from self._handler_result(handler)):
                    self.SetTickSuccess()
                    return True
            except Exception as error:
                handler.cancel_pending("handler_exception")
                self._report_composition_error(f"smart handler {skill_id} failed: {type(error).__name__}")

        fallback = self.ResolveFallback()
        if fallback is not None:
            return (yield from fallback.ProcessSkillCasting())

        yield
        return False

    def Dispose(self, reason: str = "composition_disposed") -> None:
        if self._disposed:
            return
        for handler in tuple(self._active_handlers.values()):
            handler.dispose(reason)
        self._active_handlers.clear()
        self._skill_slots.clear()
        self._equipped_bar = None
        self._smart_owned_skill_ids = ()
        self.SetBlockedSkills([])
        self.ResetTickState()
        self._disposed = True

    def OnContractActivated(self, cached_data: Any = None) -> None:
        self._disposed = False
        self.ResetTickState()
        if cached_data is not None:
            set_cached_data = getattr(self, "set_cached_data", None)
            if callable(set_cached_data):
                set_cached_data(cached_data)


__all__ = [
    "CandidateReason",
    "DECISION_INTERVAL_MS",
    "DAMAGE_PER_ENERGY",
    "DEFAULT_POLICY",
    "DecisionReason",
    "EnergySurgeController",
    "EnergySurgeCandidateEvaluation",
    "EnergySurgeDecision",
    "EnergySurgeEnemyObservation",
    "EnergySurgeGroupEvaluation",
    "EnergySurgePolicy",
    "Energy_Surge_ID",
    "FOCUS_CHALLENGER_STABILITY_MS",
    "FOCUS_GAP_GRACE_MS",
    "FOCUS_MINIMUM_OVERLAP_RATIO",
    "FOCUS_SWITCH_VALUE_RATIO",
    "ForeignReservationProjection",
    "LegacyEnergySurgeController",
    "LOW_HP_THRESHOLD",
    "MATCH_SCORE_BONUS",
    "MAXIMUM_FOREIGN_RESERVATIONS",
    "MINIMUM_EXPECTED_PACKET_DAMAGE",
    "My_Energy_Surge",
    "MyMesmer",
    "PROFESSION_MAX_ENERGY",
    "SUPPORTED_HANDLER_FACTORIES",
    "SmartEnergySurgeHandler",
    "SmartCryController",
    "UNKNOWN_MAX_ENERGY",
    "evaluate_energy_surge",
    "infer_max_energy",
]
