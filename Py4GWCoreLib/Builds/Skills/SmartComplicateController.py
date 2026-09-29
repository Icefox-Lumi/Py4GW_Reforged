"""Runtime Smart Complicate owner and the narrow Cry/Complicate coordinator.

Smart Complicate owns only its runtime adapter and skill-specific proposal
construction.  Guarded queueing, late D0 claiming, native-boundary checks, and
receipt cleanup are inherited from the proven Smart Cry controller.
"""

from __future__ import annotations

import math
from collections.abc import Generator
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import replace
from typing import Any
from typing import cast

from Py4GWCoreLib.Builds.Skills.SmartComplicate import COMPLICATE_SKILL_ID
from Py4GWCoreLib.Builds.Skills.SmartComplicate import ComplicateCandidateObservation
from Py4GWCoreLib.Builds.Skills.SmartComplicate import ComplicateCastValue
from Py4GWCoreLib.Builds.Skills.SmartComplicate import ComplicateDisableDurationEvidence
from Py4GWCoreLib.Builds.Skills.SmartComplicate import ComplicateInterruptEvidence
from Py4GWCoreLib.Builds.Skills.SmartComplicate import ComplicateObservedCast
from Py4GWCoreLib.Builds.Skills.SmartComplicate import evaluate_smart_complicate
from Py4GWCoreLib.Builds.Skills.SmartCry import DEFAULT_POLICY
from Py4GWCoreLib.Builds.Skills.SmartCry import CryPolicyParameters
from Py4GWCoreLib.Builds.Skills.SmartCryController import QUEUE_DEADLINE_MS
from Py4GWCoreLib.Builds.Skills.SmartCryController import SmartCryController
from Py4GWCoreLib.Builds.Skills.SmartInterruptChooser import SmartComplicateInterruptProposal
from Py4GWCoreLib.Builds.Skills.SmartInterruptChooser import SmartInterruptProposal
from Py4GWCoreLib.Builds.Skills.SmartInterruptChooser import choose_smart_interrupt

COMPLICATE_SKILL_NAME = "Complicate"


@dataclass(frozen=True, slots=True)
class _ComplicateRuntimeDecision:
    selected: SmartComplicateInterruptProposal | None
    reason: Any
    candidates: tuple[Any, ...]


def get_complicate_skill_id() -> int:
    """Resolve Complicate through the canonical skill owner and require D2A ID 932."""

    from Py4GWCoreLib.Skill import Skill

    resolved_id = int(Skill.GetID(COMPLICATE_SKILL_NAME) or 0)
    if resolved_id != COMPLICATE_SKILL_ID:
        raise ValueError(f"canonical Complicate skill ID mismatch: expected {COMPLICATE_SKILL_ID}, got {resolved_id}")
    return resolved_id


class SmartComplicateController(SmartCryController):
    """Guarded runtime controller for one Smart Complicate attempt."""

    def __init__(
        self,
        match_only: bool = False,
        *,
        skill_id: int | None = None,
        queue_deadline_ms: int = QUEUE_DEADLINE_MS,
    ) -> None:
        super().__init__(
            match_only=match_only,
            skill_id=COMPLICATE_SKILL_ID if skill_id is None else int(skill_id),
            queue_deadline_ms=queue_deadline_ms,
        )
        if match_only:
            return
        self.build_name = "Smart Complicate"
        self._runtime_skill_id_valid = self._validate_runtime_skill_id()
        if not self._runtime_skill_id_valid:
            self._emit_diagnostic("declined", ("complicate_skill_id_mismatch",))

    def _validate_runtime_skill_id(self) -> bool:
        if self.skill_id != COMPLICATE_SKILL_ID:
            return False
        try:
            return get_complicate_skill_id() == self.skill_id
        except Exception:
            return False

    def _runtime_gate(self) -> bool:
        return self._runtime_skill_id_valid and self._validate_runtime_skill_id() and super()._runtime_gate()

    def _selection_policy(self) -> CryPolicyParameters:
        """Expose all resolved Cry values so D2A can admit zero-value casts."""

        return replace(DEFAULT_POLICY, minimum_candidate_value=0)

    def _selection_dispatch_allowed(self, captured: Any, now_ms: int) -> bool:
        del captured, now_ms
        if not self._runtime_skill_id_valid or not self._validate_runtime_skill_id():
            return False
        if not self._runtime_gate():
            return False
        slot = self._resolve_current_slot()
        return slot is not None and self._skill_readiness(slot)

    def _build_selection(self, now_ms: int, handled_cast_keys: set[Any]) -> Any:
        if not self._runtime_skill_id_valid or not self._validate_runtime_skill_id():
            return self._record_selection_failure("complicate_skill_id_mismatch")

        base_selection = super()._build_selection(now_ms, handled_cast_keys)
        if base_selection is None:
            return None

        duration = self._resolve_disable_duration()
        candidates: list[ComplicateCandidateObservation] = []
        for cry_candidate in base_selection.decision.candidates:
            primary_agent_id = int(cry_candidate.primary_agent_id)
            primary_skill_id = int(cry_candidate.primary_enemy_skill_id or 0)
            skill_id = primary_skill_id if primary_skill_id > 0 else None
            assessment = None
            if skill_id is not None and self._activation_evidence.matches(primary_agent_id, skill_id, now_ms):
                assessment = self._strict_assessment(primary_agent_id, now_ms)

            mechanical_evidence = None
            if assessment is not None:
                try:
                    mechanical_evidence = ComplicateInterruptEvidence.from_assessment(assessment)
                except (TypeError, ValueError):
                    mechanical_evidence = None

            primary_value = None
            if skill_id is not None and str(getattr(cry_candidate, "primary_value_source", "unavailable")) != (
                "unavailable"
            ):
                try:
                    primary_value = ComplicateCastValue.from_smart_cry_evaluation(
                        cry_candidate,
                        expected_agent_id=primary_agent_id,
                        expected_enemy_skill_id=skill_id,
                    )
                except (TypeError, ValueError):
                    primary_value = None

            area_casts = ()
            if skill_id is not None:
                area_casts = self._observed_same_skill_area_casts(
                    base_selection.snapshot,
                    primary_agent_id,
                    skill_id,
                )
            candidates.append(
                ComplicateCandidateObservation(
                    primary_agent_id=primary_agent_id,
                    primary_enemy_skill_id=skill_id,
                    mechanical_assessment=mechanical_evidence,
                    primary_value=primary_value,
                    affected_area_casts=area_casts,
                    disable_duration=duration,
                )
            )

        decision = evaluate_smart_complicate(
            candidates,
            handled_cast_keys=handled_cast_keys,
        )
        selected = None
        primary_assessment = None
        if decision.selected is not None:
            selected = SmartComplicateInterruptProposal(decision.selected)
            primary_assessment = decision.selected.mechanical_assessment.assessment
        runtime_decision = _ComplicateRuntimeDecision(
            selected=selected,
            reason=decision.reason,
            candidates=decision.candidates,
        )
        return type(base_selection)(
            decision=cast(Any, runtime_decision),
            snapshot=base_selection.snapshot,
            primary_assessment=primary_assessment,
            runtime_rejection_counts=base_selection.runtime_rejection_counts,
        )

    def _final_native_boundary_validate(self, request: Any, receipt: Any) -> int | None:
        if not self._runtime_skill_id_valid or not self._validate_runtime_skill_id():
            return None
        return super()._final_native_boundary_validate(request, receipt)

    def _selection_diagnostic_signature(self, selection: Any) -> tuple[Any, ...]:
        if selection is None:
            return (
                "no_eligible_candidate",
                f"selection={self._selection_failure_reason or 'selection_unavailable'}",
            )
        decision = selection.decision
        reason_counts: dict[str, int] = {}
        for candidate in decision.candidates:
            reason = str(getattr(getattr(candidate, "reason", None), "value", "unknown"))
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        reason_summary = ",".join(f"{reason}={count}" for reason, count in sorted(reason_counts.items())) or "none"
        decision_reason = str(getattr(getattr(decision, "reason", None), "value", "unknown"))
        runtime_summary = (
            ",".join(f"{reason}={count}" for reason, count in selection.runtime_rejection_counts) or "none"
        )
        return (
            "no_eligible_candidate",
            f"decision={decision_reason}",
            f"reasons={reason_summary}",
            f"runtime={runtime_summary}",
        )

    def _adapt_selection_proposal(self, selection: Any) -> SmartComplicateInterruptProposal | None:
        selected = selection.decision.selected
        return selected if isinstance(selected, SmartComplicateInterruptProposal) else None

    @staticmethod
    def _selected_candidate_is_valid(selected: Any, request: Any, receipt: Any) -> bool:
        try:
            return (
                selected.primary_agent_id == request.primary_agent_id
                and selected.primary_enemy_skill_id == int(receipt.enemy_skill_id)
                and selected.total_interrupt_value >= 0
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _resolve_disable_duration(self) -> ComplicateDisableDurationEvidence | None:
        try:
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import Player
            from Py4GWCoreLib.enums_src.GameData_enums import Attribute
            from Py4GWCoreLib.Skill import Skill

            player_id = int(Player.GetAgentID() or 0)
            rank = None
            if player_id > 0:
                for attribute in Agent.GetAttributes(player_id) or ():
                    if int(getattr(attribute, "attribute_id", -1)) == int(Attribute.DominationMagic.value):
                        effective_level = getattr(attribute, "level", None)
                        if effective_level is None:
                            effective_level = getattr(attribute, "Value", None)
                        if effective_level is None:
                            return None
                        rank = int(effective_level)
                        break
            progression_data = Skill.GetProgressionData(self.skill_id)
            return ComplicateDisableDurationEvidence.from_skill_progression(
                self.skill_id,
                rank,
                progression_data,
            )
        except Exception:
            return None

    def _observed_same_skill_area_casts(
        self,
        snapshot: Any,
        primary_agent_id: int,
        primary_skill_id: int,
    ) -> tuple[ComplicateObservedCast, ...]:
        try:
            from Py4GWCoreLib import GLOBAL_CACHE
            from Py4GWCoreLib import Agent

            radius = float(GLOBAL_CACHE.Skill.Data.GetAoERange(self.skill_id))
        except Exception:
            return ()
        if not math.isfinite(radius) or radius < 0.0:
            return ()
        radius_squared = radius * radius
        primary = next(
            (enemy for enemy in snapshot.enemies if enemy.agent_id == primary_agent_id),
            None,
        )
        if primary is None:
            return ()

        observed: list[ComplicateObservedCast] = []
        for enemy in snapshot.enemies:
            if enemy.agent_id == primary_agent_id:
                continue
            dx = float(enemy.x) - float(primary.x)
            dy = float(enemy.y) - float(primary.y)
            if dx * dx + dy * dy > radius_squared:
                continue
            try:
                if not bool(Agent.IsValid(enemy.agent_id)):
                    continue
                if bool(Agent.IsDead(enemy.agent_id)) or not self._is_enemy(enemy.agent_id):
                    continue
                if not bool(Agent.IsCasting(enemy.agent_id)):
                    continue
                current_skill_id = int(Agent.GetCastingSkillID(enemy.agent_id) or 0)
                if current_skill_id != primary_skill_id:
                    continue
                observed.append(ComplicateObservedCast(enemy.agent_id, current_skill_id))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
        return tuple(observed)


class SmartCryComplicateCoordinator:
    """Coordinate only the two committed local smart-interrupt families."""

    def try_cast(self, handlers: Iterable[Any]) -> Generator[None, None, bool]:
        if False:
            yield
        supplied = tuple(handlers)
        if any(self._has_active_dispatch(handler) for handler in supplied):
            return True

        entries: list[tuple[Any, SmartInterruptProposal]] = []
        for handler in supplied:
            build_proposal = getattr(handler, "build_interrupt_proposal", None)
            if not callable(build_proposal):
                continue
            try:
                proposal = cast(SmartInterruptProposal | None, build_proposal())
            except Exception as error:
                self._emit(handler, "declined", ("proposal_exception", type(error).__name__))
                continue
            if proposal is not None:
                entries.append((handler, proposal))

        if not entries:
            return False
        try:
            selected = choose_smart_interrupt(proposal for _handler, proposal in entries)
        except (TypeError, ValueError) as error:
            for handler, _proposal in entries:
                self._emit(handler, "declined", ("chooser_rejected", type(error).__name__))
            return False
        if selected is None:
            return False
        selected_handler = next(
            (handler for handler, proposal in entries if proposal is selected),
            None,
        )
        if selected_handler is None:
            return False
        self._emit(
            selected_handler,
            "chooser_selected",
            (
                selected.family.value,
                selected.primary_agent_id,
                selected.primary_enemy_skill_id,
            ),
        )
        for handler, proposal in entries:
            if handler is selected_handler:
                continue
            discard = getattr(handler, "discard_interrupt_proposal", None)
            if callable(discard):
                try:
                    discard(proposal)
                except Exception:
                    self._emit(handler, "declined", ("proposal_discard_exception",))
        dispatch = getattr(selected_handler, "try_cast_selected", None)
        if not callable(dispatch):
            self._emit(selected_handler, "declined", ("selected_dispatch_unavailable",))
            return False
        result = dispatch(selected)
        if hasattr(result, "__next__"):
            result = yield from cast(Generator[None, None, Any], result)
        return bool(result)

    @staticmethod
    def _has_active_dispatch(handler: Any) -> bool:
        checker = getattr(handler, "has_active_dispatch", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return True

    @staticmethod
    def _emit(handler: Any, family: str, signature: tuple[Any, ...]) -> None:
        emit = getattr(handler, "_emit_diagnostic", None)
        if callable(emit):
            try:
                emit(family, signature)
            except Exception:
                return


__all__ = [
    "COMPLICATE_SKILL_ID",
    "COMPLICATE_SKILL_NAME",
    "SmartComplicateController",
    "SmartCryComplicateCoordinator",
    "get_complicate_skill_id",
]
