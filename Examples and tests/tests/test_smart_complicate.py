"""Offline D2A tests for pure Smart Complicate policy and proposal data."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from dataclasses import dataclass
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Any
from typing import Iterator

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"
SMART_MESMER_PATH = SKILLS_DIR / "SmartMesmer.py"
SMART_CRY_PATH = SKILLS_DIR / "SmartCry.py"
SMART_COMPLICATE_PATH = SKILLS_DIR / "SmartComplicate.py"
SKILL_DESCRIPTIONS_PATH = ROOT / "Py4GWCoreLib" / "skill_descriptions.json"


def _install_package(name: str, path: Path) -> None:
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"could not load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _raises(exception_type: type[BaseException], *, match: str | None = None) -> Iterator[None]:
    try:
        yield
    except exception_type as error:
        if match is not None and match not in str(error):
            raise AssertionError(f"expected {match!r} in {str(error)!r}") from error
    else:
        raise AssertionError(f"expected {exception_type.__name__}")


@contextmanager
def _isolated_smart_modules() -> Iterator[tuple[Any, Any]]:
    original = {
        name: module
        for name, module in sys.modules.items()
        if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d2a_test.")
    }
    try:
        for name in tuple(sys.modules):
            if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d2a_test."):
                sys.modules.pop(name, None)
        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
        _install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
        _install_package("d2a_test", ROOT / "Examples and tests" / "tests")
        _load_module("Py4GWCoreLib.Builds.Skills.SmartMesmer", SMART_MESMER_PATH)
        smart_cry = _load_module("Py4GWCoreLib.Builds.Skills.SmartCry", SMART_CRY_PATH)
        smart_complicate = _load_module("d2a_test.smart_complicate", SMART_COMPLICATE_PATH)
        yield smart_cry, smart_complicate
    finally:
        for name in tuple(sys.modules):
            if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d2a_test."):
                sys.modules.pop(name, None)
        sys.modules.update(original)


with _isolated_smart_modules() as (smart_cry, smart_complicate):
    CryCastKey = smart_cry.CryCastKey
    CandidateObservation = smart_complicate.ComplicateCandidateObservation
    CandidateReason = smart_complicate.ComplicateCandidateReason
    DecisionReason = smart_complicate.ComplicateDecisionReason
    CastValue = smart_complicate.ComplicateCastValue
    InterruptEvidence = smart_complicate.ComplicateInterruptEvidence
    ObservedCast = smart_complicate.ComplicateObservedCast
    evaluate_smart_complicate = smart_complicate.evaluate_smart_complicate
    d2a_imported_runtime_interrupt = "Py4GWCoreLib.HeroAI.interrupt" in sys.modules


class _AssessmentReason(str, Enum):
    FEASIBLE = "feasible"
    INSUFFICIENT_TIME = "insufficient_time"


class _OnsetConfidence(str, Enum):
    UNKNOWN = "unknown"
    FIRST_SEEN = "first_seen_uncertain"
    CONFIRMED = "confirmed_local_onset"


@dataclass(frozen=True, slots=True)
class _Assessment:
    feasible: bool
    reason: _AssessmentReason
    strict: bool
    target_agent_id: int
    our_skill_id: int
    enemy_skill_id: int
    observation_identity: tuple[int, int, int] | None
    observation_age_ms: int | None
    onset_confidence: _OnsetConfidence
    enemy_remaining_ms: int | None
    interrupt_budget_ms: int | None
    observation_stale: bool = False
    observation_untrusted: bool = False
    timing_invalid: bool = False
    geometry_available: bool = True


def _assessment(
    agent_id: int,
    skill_id: int,
    *,
    assessed_with_skill_id: int = 932,
    feasible: bool = True,
    strict: bool = True,
    trusted: bool = True,
    sequence: int = 1,
    reason: _AssessmentReason | None = None,
) -> _Assessment:
    return _Assessment(
        feasible=feasible,
        reason=reason or (_AssessmentReason.FEASIBLE if feasible else _AssessmentReason.INSUFFICIENT_TIME),
        strict=strict,
        target_agent_id=agent_id,
        our_skill_id=assessed_with_skill_id,
        enemy_skill_id=skill_id,
        observation_identity=(agent_id, skill_id, sequence),
        observation_age_ms=100,
        onset_confidence=_OnsetConfidence.CONFIRMED if trusted else _OnsetConfidence.FIRST_SEEN,
        enemy_remaining_ms=800 if feasible else 200,
        interrupt_budget_ms=400,
    )


def _evidence(
    agent_id: int,
    skill_id: int,
    *,
    assessed_with_skill_id: int = 932,
    feasible: bool = True,
    strict: bool = True,
    trusted: bool = True,
    sequence: int = 1,
) -> Any:
    return InterruptEvidence.from_assessment(
        _assessment(
            agent_id,
            skill_id,
            assessed_with_skill_id=assessed_with_skill_id,
            feasible=feasible,
            strict=strict,
            trusted=trusted,
            sequence=sequence,
        )
    )


def _resolved_value(agent_id: int, skill_id: int, value: int, source: str) -> Any:
    evaluation = smart_cry.CryCandidateEvaluation(
        primary_agent_id=agent_id,
        primary_enemy_skill_id=skill_id,
        eligible=False,
        reason=smart_cry.CryCandidateReason.BELOW_MINIMUM_VALUE,
        affected_enemy_ids=(),
        feasible_covered_cast_keys=(),
        covered_cast_keys=(),
        handled_cast_keys=(),
        covered_cast_values=(),
        total_interrupt_value=value,
        primary_cast_value=value,
        feasible_covered_cast_count=1,
        primary_value_source=source,
    )
    return CastValue.from_smart_cry_evaluation(
        evaluation,
        expected_agent_id=agent_id,
        expected_enemy_skill_id=skill_id,
    )


def _duration(rank: int | None) -> Any:
    metadata = json.loads(SKILL_DESCRIPTIONS_PATH.read_text(encoding="utf-8"))["932"]["progression"]
    progression_data = tuple(
        (
            progression["attribute"],
            progression["field"],
            {int(key): float(value) for key, value in progression["values"].items()},
        )
        for progression in metadata
    )
    return smart_complicate.ComplicateDisableDurationEvidence.from_skill_progression(932, rank, progression_data)


def _candidate(
    agent_id: int,
    skill_id: int | None = 100,
    *,
    value: int | None = 1,
    value_source: str = "generic",
    feasible: bool = True,
    strict: bool = True,
    trusted: bool = True,
    assessed_with_skill_id: int = 932,
    sequence: int = 1,
    area_casts: tuple[Any, ...] = (),
    duration_rank: int | None = None,
) -> Any:
    evidence = None
    resolved_value = None
    if skill_id is not None:
        evidence = _evidence(
            agent_id,
            skill_id,
            assessed_with_skill_id=assessed_with_skill_id,
            feasible=feasible,
            strict=strict,
            trusted=trusted,
            sequence=sequence,
        )
    if value is not None:
        resolved_value = _resolved_value(agent_id, skill_id or 100, value, value_source)
    return CandidateObservation(
        primary_agent_id=agent_id,
        primary_enemy_skill_id=skill_id,
        mechanical_assessment=evidence,
        primary_value=resolved_value,
        affected_area_casts=area_casts,
        disable_duration=_duration(duration_rank),
    )


def test_complicate_id_and_effect_semantics_match_checked_in_metadata() -> None:
    metadata = json.loads(SKILL_DESCRIPTIONS_PATH.read_text(encoding="utf-8"))
    complicate = metadata[str(smart_complicate.COMPLICATE_SKILL_ID)]
    progression = complicate["progression"][0]

    assert smart_complicate.COMPLICATE_SKILL_ID == 932
    assert complicate["name"] == "Complicate"
    assert "that skill is interrupted and disabled" in complicate["desc_full"]
    assert "all foes in the area" in complicate["desc_full"]
    assert progression["attribute"] == "Domination Magic"
    assert progression["field"] == "Duration"
    assert progression["values"]["15"] == "12"
    assert _duration(0).duration_seconds == 5
    assert _duration(15).duration_seconds == 12
    assert _duration(21).duration_seconds == 15


def test_d2a_module_does_not_import_runtime_interrupt_owner() -> None:
    assert d2a_imported_runtime_interrupt is False


def test_disable_duration_is_ranked_source_evidence_and_rejects_bad_values() -> None:
    resolved = _duration(15)
    assert resolved is not None
    assert resolved.skill_id == 932
    assert resolved.attribute == "Domination Magic"
    assert resolved.field == "Duration"
    assert resolved.attribute_rank == 15
    assert resolved.duration_seconds == 12
    assert "skill_descriptions.json:932" in resolved.source
    assert _duration(None) is None
    with _raises(FrozenInstanceError):
        resolved.attribute_rank = 0
    with _raises(TypeError):
        smart_complicate.ComplicateDisableDurationEvidence()

    factory = smart_complicate.ComplicateDisableDurationEvidence.from_skill_progression
    for invalid in (0, -1, float("nan"), float("inf"), 16, 12.5):
        with _raises(ValueError):
            factory(932, 0, [("Domination Magic", "Duration", {0: invalid})])
    with _raises(ValueError):
        factory(932, 22, [("Domination Magic", "Duration", {22: 15})])
    assert factory(932, 15, [("Domination Magic", "Duration", {0: 5})]) is None
    with _raises(ValueError):
        factory(57, 0, [("Domination Magic", "Duration", {0: 5})])


def test_mechanically_infeasible_primary_is_rejected() -> None:
    decision = evaluate_smart_complicate((_candidate(10, feasible=False),))

    assert decision.selected is None
    assert decision.reason is DecisionReason.NO_ELIGIBLE_CANDIDATE
    assert decision.candidates[0].eligible is False
    assert decision.candidates[0].reason is CandidateReason.MECHANICALLY_INFEASIBLE


def test_handled_primary_cannot_be_rescued_by_same_skill_area_observations() -> None:
    primary = _candidate(
        10,
        value=0,
        value_source="override:zero_test",
        area_casts=(ObservedCast(11, 100), ObservedCast(12, 100)),
    )
    handled_key = CryCastKey(10, 100)
    decision = evaluate_smart_complicate((primary,), handled_cast_keys=(handled_key,))

    candidate = decision.candidates[0]
    assert decision.selected is None
    assert candidate.eligible is False
    assert candidate.reason is CandidateReason.PRIMARY_CAST_HANDLED
    assert candidate.primary_cast_value == 0
    assert candidate.observed_same_skill_area_agent_ids == (11, 12)


def test_unavailable_primary_cannot_be_rescued_by_secondary_casts() -> None:
    unavailable = CandidateObservation(
        primary_agent_id=10,
        primary_enemy_skill_id=None,
        mechanical_assessment=None,
        primary_value=None,
        affected_area_casts=(ObservedCast(11, 100), ObservedCast(12, 100)),
    )
    decision = evaluate_smart_complicate((unavailable,))

    assert decision.selected is None
    assert decision.candidates[0].eligible is False
    assert decision.candidates[0].reason is CandidateReason.PRIMARY_SKILL_UNAVAILABLE
    assert decision.candidates[0].primary_cast_key is None
    assert decision.candidates[0].observed_same_skill_area_agent_ids == ()


def test_resolved_zero_value_is_distinct_from_unavailable_and_can_be_proposed() -> None:
    zero_value = _candidate(
        10,
        value=0,
        value_source="override:zero_test",
        area_casts=(ObservedCast(11, 100),),
        duration_rank=9,
    )
    unavailable_value = _candidate(12, value=None)
    decision = evaluate_smart_complicate((unavailable_value, zero_value))

    assert decision.selected is not None
    assert decision.selected.primary_agent_id == 10
    assert decision.selected.primary_cast_value == 0
    assert decision.selected.primary_value_source == "override:zero_test"
    assert decision.selected.disable_duration_seconds == 9
    assert decision.selected.disable_duration is not None
    assert decision.selected.disable_duration.attribute_rank == 9
    assert decision.candidates[1].reason is CandidateReason.PRIMARY_VALUE_UNAVAILABLE
    assert decision.candidates[1].primary_cast_value is None


def test_candidates_rank_deterministically_by_value_then_exact_skill_coverage() -> None:
    candidates = (
        _candidate(20, value=2, area_casts=(ObservedCast(21, 100),)),
        _candidate(10, value=2, area_casts=(ObservedCast(11, 100), ObservedCast(12, 100))),
        _candidate(30, value=3),
    )
    first = evaluate_smart_complicate(candidates)
    second = evaluate_smart_complicate(tuple(reversed(candidates)))

    assert first.selected is not None
    assert second.selected is not None
    assert first.selected.primary_agent_id == 30
    assert second.selected.primary_agent_id == 30
    assert tuple(item.primary_agent_id for item in first.ranked_candidates) == (30, 10, 20)
    assert tuple(item.primary_agent_id for item in second.ranked_candidates) == (30, 10, 20)


def test_area_observations_require_the_exact_current_skill_id() -> None:
    decision = evaluate_smart_complicate(
        (
            _candidate(
                10,
                skill_id=100,
                area_casts=(ObservedCast(11, 100), ObservedCast(12, 101), ObservedCast(13, 100)),
            ),
        )
    )

    assert decision.selected is not None
    assert decision.selected.interrupted_skill_id == 100
    assert decision.selected.observed_same_skill_area_agent_ids == (11, 13)
    observation_fields = tuple(smart_complicate.ComplicateObservedCast.__dataclass_fields__)
    assert observation_fields == ("agent_id", "current_skill_id")
    observation_contract = CandidateObservation.__doc__ or ""
    assert "adapter precondition" in observation_contract
    assert "does not infer hostility or geometry" in observation_contract


def test_same_skill_new_observation_is_not_suppressed_by_old_identity() -> None:
    primary = _candidate(10, skill_id=100, sequence=2)
    previous_identity = CryCastKey(10, 100, (10, 100, 1))
    current_decision = evaluate_smart_complicate((primary,), handled_cast_keys=(previous_identity,))
    assert current_decision.selected is not None
    assert current_decision.selected.primary_cast_key == CryCastKey(10, 100, (10, 100, 2))

    broad_key_decision = evaluate_smart_complicate((primary,), handled_cast_keys=(CryCastKey(10, 100),))
    assert broad_key_decision.selected is None
    assert broad_key_decision.candidates[0].reason is CandidateReason.PRIMARY_CAST_HANDLED


def test_interrupt_projection_retains_shared_enums_and_rejects_contradictions() -> None:
    assessment = _assessment(10, 100)
    evidence = InterruptEvidence.from_assessment(assessment)
    assert evidence.assessment is assessment
    assert evidence.reason is assessment.reason
    assert evidence.onset_confidence is assessment.onset_confidence
    assert evidence.mechanically_feasible is True
    assert evidence.strict is True

    infeasible_assessment = _assessment(11, 100, feasible=False)
    infeasible = InterruptEvidence.from_assessment(infeasible_assessment)
    assert infeasible.reason is _AssessmentReason.INSUFFICIENT_TIME
    assert infeasible.mechanically_feasible is False

    with _raises(ValueError, match="contradicts"):
        InterruptEvidence.from_assessment(replace(assessment, reason=_AssessmentReason.INSUFFICIENT_TIME))
    with _raises(ValueError, match="remaining-time"):
        InterruptEvidence.from_assessment(replace(assessment, enemy_remaining_ms=100))
    with _raises(ValueError, match="observation or geometry"):
        InterruptEvidence.from_assessment(replace(assessment, onset_confidence=_OnsetConfidence.UNKNOWN))

    with _raises(FrozenInstanceError):
        evidence.assessment = infeasible_assessment


def test_smart_cry_value_projection_enforces_its_domain_and_provenance() -> None:
    assert _resolved_value(10, 100, 0, "override:zero_test").value == 0
    with _raises(TypeError):
        CastValue()
    for invalid_value, source in ((99, "generic"), (1, "made_up"), (1, "unavailable")):
        with _raises(ValueError):
            _resolved_value(10, 100, invalid_value, source)

    evaluation = smart_cry.CryCandidateEvaluation(
        primary_agent_id=11,
        primary_enemy_skill_id=100,
        eligible=False,
        reason=smart_cry.CryCandidateReason.BELOW_MINIMUM_VALUE,
        affected_enemy_ids=(),
        feasible_covered_cast_keys=(),
        covered_cast_keys=(),
        handled_cast_keys=(),
        covered_cast_values=(),
        total_interrupt_value=1,
        primary_cast_value=1,
        feasible_covered_cast_count=1,
        primary_value_source="generic",
    )
    with _raises(ValueError, match="match the expected primary"):
        CastValue.from_smart_cry_evaluation(
            evaluation,
            expected_agent_id=10,
            expected_enemy_skill_id=100,
        )


def test_proposal_and_nested_observations_are_immutable() -> None:
    decision = evaluate_smart_complicate((_candidate(10, area_casts=(ObservedCast(12, 100), ObservedCast(11, 100))),))
    proposal = decision.selected
    assert proposal is not None
    assert proposal.observed_same_skill_area_agent_ids == (11, 12)
    assert proposal.primary_cast_key == CryCastKey(10, 100, (10, 100, 1))

    try:
        setattr(proposal, "primary_agent_id", 99)
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("Smart Complicate proposal accepted mutation of primary_agent_id")
    assert proposal.disable_duration is None
    with _raises(FrozenInstanceError):
        proposal.mechanical_assessment.assessment.strict = False


def test_candidate_rejects_missing_mismatched_or_wrong_skill_assessment() -> None:
    missing = CandidateObservation(
        primary_agent_id=10,
        primary_enemy_skill_id=100,
        mechanical_assessment=None,
        primary_value=_resolved_value(10, 100, 1, "generic"),
    )
    mismatch = CandidateObservation(
        primary_agent_id=12,
        primary_enemy_skill_id=100,
        mechanical_assessment=_evidence(11, 100),
        primary_value=_resolved_value(12, 100, 1, "generic"),
    )
    wrong_skill = _candidate(13, assessed_with_skill_id=57)

    decision = evaluate_smart_complicate((missing, mismatch, wrong_skill))

    assert decision.selected is None
    assert {candidate.reason for candidate in decision.candidates} == {
        CandidateReason.MECHANICAL_ASSESSMENT_UNAVAILABLE,
        CandidateReason.ASSESSMENT_MISMATCH,
        CandidateReason.ASSESSMENT_SKILL_MISMATCH,
    }
