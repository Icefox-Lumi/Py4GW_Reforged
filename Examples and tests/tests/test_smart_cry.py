"""Offline D1B tests for pure Smart Cry policy and interrupt assessment."""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "Py4GWCoreLib" / "Builds" / "Skills"
SMART_MESMER_NAME = "Py4GWCoreLib.Builds.Skills.SmartMesmer"
SMART_CRY_NAME = "d1b_test.smart_cry"
INTERRUPT_NAME = "Py4GWCoreLib.HeroAI.interrupt"


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
def _isolated_smart_modules() -> Any:
    def is_owned(name: str) -> bool:
        return name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name.startswith("d1b_test.")

    original = {name: module for name, module in sys.modules.items() if is_owned(name)}
    try:
        for name in tuple(sys.modules):
            if is_owned(name):
                sys.modules.pop(name, None)
        _install_package("Py4GWCoreLib", ROOT / "Py4GWCoreLib")
        _install_package("Py4GWCoreLib.Builds", ROOT / "Py4GWCoreLib" / "Builds")
        _install_package("Py4GWCoreLib.Builds.Skills", SKILLS_DIR)
        _install_package("d1b_test", ROOT / "Examples and tests" / "tests")
        _install_package("d1b_test.smart", ROOT / "Examples and tests" / "tests")
        yield
    finally:
        for name in tuple(sys.modules):
            if is_owned(name):
                sys.modules.pop(name, None)
        sys.modules.update(original)


with _isolated_smart_modules():
    smart_mesmer = _load_module(SMART_MESMER_NAME, SKILLS_DIR / "SmartMesmer.py")
    smart_cry = _load_module(SMART_CRY_NAME, SKILLS_DIR / "SmartCry.py")

CombatSnapshot = smart_mesmer.CombatSnapshot
EnemyObservation = smart_mesmer.EnemyObservation
CryCandidateReason = smart_cry.CryCandidateReason
CryCastObservation = smart_cry.CryCastObservation
CryClassificationProvenance = smart_cry.CryClassificationProvenance
CryDecisionReason = smart_cry.CryDecisionReason
CryEnemyObservation = smart_cry.CryEnemyObservation
CryInterruptEvidence = smart_cry.CryInterruptEvidence
CryOnsetConfidence = smart_cry.CryOnsetConfidence
CryPolicyParameters = smart_cry.CryPolicyParameters
CrySkillCategory = smart_cry.CrySkillCategory
CrySkillClassification = smart_cry.CrySkillClassification
DEFAULT_POLICY = smart_cry.DEFAULT_POLICY
evaluate_smart_cry = smart_cry.evaluate_smart_cry


def _evidence(
    agent_id: int,
    skill_id: int,
    *,
    feasible: bool = True,
    trusted: bool = True,
    active: bool = True,
    sequence: int = 1,
    reason: str = "feasible",
) -> Any:
    return CryInterruptEvidence(
        target_agent_id=agent_id,
        enemy_skill_id=skill_id,
        mechanically_feasible=feasible,
        timing_trusted=trusted,
        cast_active=active,
        reason=reason,
        observation_identity=(agent_id, skill_id, sequence),
        observation_age_ms=100,
        onset_confidence=(CryOnsetConfidence.TRUSTED if trusted else CryOnsetConfidence.UNCERTAIN),
    )


def _cast(
    agent_id: int,
    skill_id: int,
    *,
    category: Any = CrySkillCategory.UNKNOWN,
    provenance: Any = CryClassificationProvenance.UNCLASSIFIED,
    metadata_populated: bool = False,
    feasible: bool = True,
    trusted: bool = True,
    active: bool = True,
    value_override: int | None = None,
) -> Any:
    return CryCastObservation(
        enemy_skill_id=skill_id,
        interrupt=_evidence(
            agent_id,
            skill_id,
            feasible=feasible,
            trusted=trusted,
            active=active,
            reason="feasible" if feasible else "not_feasible",
        ),
        classification=CrySkillClassification(
            category=category,
            provenance=provenance,
            metadata_populated=metadata_populated,
        ),
        value_override=value_override,
    )


def _enemy(
    agent_id: int,
    x: float,
    *,
    distance: float | None = None,
    cast: Any = None,
    alive: bool = True,
    hostile: bool = True,
    allowed: bool = True,
) -> Any:
    return CryEnemyObservation(
        observation=EnemyObservation(agent_id, x, 0.0),
        distance_from_player=abs(x) if distance is None else distance,
        is_alive=alive,
        is_hostile=hostile,
        target_allowed=allowed,
        current_cast=cast,
    )


def _snapshot(enemies: tuple[Any, ...]) -> Any:
    return CombatSnapshot(
        enemies=tuple(enemy.observation for enemy in enemies),
        observed_at=0.0,
        lifecycle_id="smart-cry-test",
    )


def _evaluate(
    enemies: tuple[Any, ...],
    *,
    cry_radius: float = 4.0,
    cast_range: float = 20.0,
    handled: tuple[Any, ...] = (),
    policy: Any = DEFAULT_POLICY,
) -> Any:
    return evaluate_smart_cry(
        _snapshot(enemies),
        enemies,
        cry_radius=cry_radius,
        cast_range=cast_range,
        handled_cast_keys=handled,
        policy=policy,
    )


def test_one_generic_feasible_cast_is_below_default_threshold() -> None:
    decision = _evaluate((_enemy(10, 0.0, cast=_cast(10, 100)),))

    assert decision.selected is None
    assert decision.candidates[0].total_interrupt_value == 1
    assert decision.candidates[0].reason is CryCandidateReason.BELOW_MINIMUM_VALUE


def test_two_generic_feasible_casts_inside_one_cry_footprint_admit() -> None:
    decision = _evaluate(
        (
            _enemy(10, 0.0, cast=_cast(10, 100)),
            _enemy(11, 2.0, cast=_cast(11, 101)),
        ),
    )

    assert decision.selected_primary_agent_id == 10
    assert decision.selected is not None
    assert decision.selected.total_interrupt_value == 2
    assert decision.selected.feasible_covered_cast_count == 2


def test_explicit_healing_and_resurrection_values_admit() -> None:
    heal = _evaluate(
        (
            _enemy(
                10,
                0.0,
                cast=_cast(
                    10,
                    100,
                    category=CrySkillCategory.HEALING,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                ),
            ),
        )
    )
    resurrection = _evaluate(
        (
            _enemy(
                10,
                0.0,
                cast=_cast(
                    10,
                    100,
                    category=CrySkillCategory.RESURRECTION,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                ),
            ),
        )
    )

    assert heal.selected is not None and heal.selected.total_interrupt_value == 2
    assert resurrection.selected is not None and resurrection.selected.total_interrupt_value == 4


def test_default_metadata_is_not_explicit_classification_evidence() -> None:
    decision = _evaluate(
        (
            _enemy(
                10,
                0.0,
                cast=_cast(
                    10,
                    100,
                    category=CrySkillCategory.HEALING,
                    provenance=CryClassificationProvenance.DEFAULT_METADATA,
                    metadata_populated=True,
                ),
            ),
        )
    )

    assert decision.selected is None
    assert decision.candidates[0].total_interrupt_value == 1


def test_unknown_timing_finished_and_changed_casts_contribute_nothing() -> None:
    unknown = _evaluate((_enemy(10, 0.0, cast=_cast(10, 100, trusted=False)),))
    finished = _evaluate((_enemy(10, 0.0, cast=_cast(10, 100, active=False)),))
    changed = CryCastObservation(
        enemy_skill_id=100,
        interrupt=_evidence(99, 100),
    )
    changed_decision = _evaluate((_enemy(10, 0.0, cast=changed),))

    assert unknown.selected is None and unknown.candidates[0].total_interrupt_value == 0
    assert finished.selected is None and finished.candidates[0].total_interrupt_value == 0
    assert changed_decision.selected is None and changed_decision.candidates[0].total_interrupt_value == 0
    assert unknown.candidates[0].reason is CryCandidateReason.UNKNOWN_TIMING
    assert finished.candidates[0].reason is CryCandidateReason.CAST_NOT_ACTIVE
    assert changed_decision.candidates[0].reason is CryCandidateReason.CAST_ASSESSMENT_MISMATCH


def test_direct_cast_range_boundary_is_inclusive_and_outside_is_rejected() -> None:
    boundary = _evaluate((_enemy(10, 0.0, distance=10.0, cast=_cast(10, 100)),), cast_range=10.0)
    outside = _evaluate((_enemy(10, 0.0, distance=10.001, cast=_cast(10, 100)),), cast_range=10.0)

    assert boundary.candidates[0].reason is CryCandidateReason.BELOW_MINIMUM_VALUE
    assert outside.candidates[0].reason is CryCandidateReason.OUT_OF_CAST_RANGE


def test_collateral_outside_direct_range_can_contribute_inside_cry_radius() -> None:
    decision = _evaluate(
        (
            _enemy(10, 0.0, distance=10.0, cast=_cast(10, 100)),
            _enemy(11, 2.0, distance=12.0, cast=_cast(11, 101)),
        ),
        cast_range=10.0,
        cry_radius=2.0,
    )

    assert decision.selected_primary_agent_id == 10
    assert decision.selected is not None
    assert decision.selected.total_interrupt_value == 2


def test_cry_radius_boundary_is_inclusive_and_just_outside_is_not_covered() -> None:
    boundary = _evaluate(
        (_enemy(10, 0.0, cast=_cast(10, 100)), _enemy(11, 5.0, cast=_cast(11, 101))),
        cry_radius=5.0,
    )
    outside = _evaluate(
        (_enemy(10, 0.0, cast=_cast(10, 100)), _enemy(11, 5.001, cast=_cast(11, 101))),
        cry_radius=5.0,
    )

    assert boundary.candidates[0].feasible_covered_cast_count == 2
    assert outside.candidates[0].feasible_covered_cast_count == 1


def test_connected_chain_does_not_expand_one_cry_footprint() -> None:
    enemies = (
        _enemy(10, 0.0, cast=_cast(10, 100)),
        _enemy(11, 4.0, cast=_cast(11, 101)),
        _enemy(12, 8.0, cast=_cast(12, 102)),
    )
    decision = _evaluate(enemies, cry_radius=4.0)
    candidate = next(candidate for candidate in decision.candidates if candidate.primary_agent_id == 10)

    assert candidate.affected_enemy_ids == (10, 11)
    assert candidate.feasible_covered_cast_count == 2
    assert candidate.total_interrupt_value == 2


def test_policy_is_invariant_to_input_order() -> None:
    enemies = (
        _enemy(20, 10.0, cast=_cast(20, 200)),
        _enemy(10, 0.0, cast=_cast(10, 100)),
        _enemy(11, 2.0, cast=_cast(11, 101)),
    )

    first = _evaluate(enemies)
    second = _evaluate(tuple(reversed(enemies)))

    assert first == second


def test_ranking_prefers_total_value_then_count_then_primary_value_then_agent_id() -> None:
    total = _evaluate(
        (
            _enemy(
                10,
                0.0,
                cast=_cast(
                    10,
                    100,
                    category=CrySkillCategory.RESURRECTION,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                ),
            ),
            _enemy(11, 1.0, cast=_cast(11, 101)),
            _enemy(20, 12.0, cast=_cast(20, 200)),
            _enemy(21, 13.0, cast=_cast(21, 201)),
        ),
        cry_radius=2.0,
    )
    count = _evaluate(
        (
            _enemy(10, 0.0, cast=_cast(10, 100, value_override=1)),
            _enemy(11, 1.0, cast=_cast(11, 101, value_override=1)),
            _enemy(20, 10.0, cast=_cast(20, 200, value_override=2)),
        ),
        cry_radius=1.0,
    )
    primary_value = _evaluate(
        (
            _enemy(
                10,
                0.0,
                cast=_cast(
                    10,
                    100,
                    category=CrySkillCategory.HEALING,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                ),
            ),
            _enemy(11, 1.0, cast=_cast(11, 101)),
            _enemy(20, 10.0, cast=_cast(20, 200)),
            _enemy(
                21,
                11.0,
                cast=_cast(
                    21,
                    201,
                    category=CrySkillCategory.HEALING,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                ),
            ),
        ),
        cry_radius=1.0,
    )

    assert total.selected_primary_agent_id == 10
    assert count.selected_primary_agent_id == 10
    assert primary_value.selected_primary_agent_id == 10


def test_exact_overlap_marks_lower_ranked_candidate_redundant() -> None:
    decision = _evaluate(
        (
            _enemy(10, 0.0, cast=_cast(10, 100)),
            _enemy(11, 1.0, cast=_cast(11, 101)),
        ),
        cry_radius=2.0,
    )

    lower = next(candidate for candidate in decision.candidates if candidate.primary_agent_id == 11)
    assert decision.selected_primary_agent_id == 10
    assert lower.redundant is True
    assert lower.canonical_primary_agent_id == 10
    assert lower.overlapping_primary_agent_ids == (10,)


def test_collective_higher_coverage_does_not_make_candidate_redundant() -> None:
    decision = _evaluate(
        (
            _enemy(
                40,
                0.0,
                cast=_cast(
                    40,
                    400,
                    category=CrySkillCategory.RESURRECTION,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                ),
            ),
            _enemy(10, 2.0, cast=_cast(10, 100)),
            _enemy(20, 4.0, cast=_cast(20, 200)),
            _enemy(30, 6.0, cast=_cast(30, 300)),
            _enemy(
                50,
                8.0,
                cast=_cast(
                    50,
                    500,
                    category=CrySkillCategory.RESURRECTION,
                    provenance=CryClassificationProvenance.HEROAI_METADATA,
                    metadata_populated=True,
                ),
            ),
        ),
        cry_radius=2.0,
    )

    lower = next(candidate for candidate in decision.candidates if candidate.primary_agent_id == 20)
    candidate_a = next(candidate for candidate in decision.candidates if candidate.primary_agent_id == 10)
    candidate_b = next(candidate for candidate in decision.candidates if candidate.primary_agent_id == 30)

    assert candidate_a.total_interrupt_value > lower.total_interrupt_value
    assert candidate_b.total_interrupt_value > lower.total_interrupt_value
    assert set(candidate_a.covered_cast_keys).intersection(lower.covered_cast_keys)
    assert set(candidate_b.covered_cast_keys).intersection(lower.covered_cast_keys)
    assert set(candidate_a.covered_cast_keys) | set(candidate_b.covered_cast_keys) >= set(lower.covered_cast_keys)
    assert not set(lower.covered_cast_keys).issubset(candidate_a.covered_cast_keys)
    assert not set(lower.covered_cast_keys).issubset(candidate_b.covered_cast_keys)
    assert lower.redundant is False
    assert lower.canonical_primary_agent_id is None
    assert lower in decision.canonical_candidates


def test_disjoint_valuable_cast_sets_remain_canonical_alternatives() -> None:
    decision = _evaluate(
        (
            _enemy(10, 0.0, cast=_cast(10, 100)),
            _enemy(11, 1.0, cast=_cast(11, 101)),
            _enemy(20, 20.0, cast=_cast(20, 200)),
            _enemy(21, 21.0, cast=_cast(21, 201)),
        ),
        cry_radius=2.0,
    )

    assert len(decision.canonical_candidates) == 2
    assert {candidate.primary_agent_id for candidate in decision.canonical_candidates} == {10, 20}


def test_externally_handled_cast_is_excluded_and_all_handled_declines() -> None:
    first = _cast(10, 100)
    second = _cast(11, 101)
    first_key = first.cast_key
    second_key = second.cast_key
    partial = _evaluate((_enemy(10, 0.0, cast=first), _enemy(11, 1.0, cast=second)), handled=(first_key,))
    all_handled = _evaluate(
        (_enemy(10, 0.0, cast=first), _enemy(11, 1.0, cast=second)),
        handled=(first_key, second_key),
    )

    partial_candidate = next(candidate for candidate in partial.candidates if candidate.primary_agent_id == 10)
    assert partial.selected is None
    assert partial_candidate.handled_cast_keys == (first_key,)
    assert all_handled.selected is None
    assert all_handled.reason is CryDecisionReason.ALL_USEFUL_CASTS_HANDLED


def test_policy_parameters_are_tunable_data() -> None:
    custom = CryPolicyParameters(
        resurrection_value=6,
        healing_value=5,
        generic_value=3,
        unknown_value=0,
        minimum_candidate_value=3,
    )
    decision = _evaluate((_enemy(10, 0.0, cast=_cast(10, 100)),), policy=custom)

    assert decision.selected is not None
    assert decision.selected.total_interrupt_value == 3
    assert DEFAULT_POLICY.generic_value == 1
    assert DEFAULT_POLICY.minimum_candidate_value == 2


def test_primary_target_rules_are_represented_in_pure_input() -> None:
    dead = _evaluate((_enemy(10, 0.0, alive=False, cast=_cast(10, 100)),))
    friendly = _evaluate((_enemy(10, 0.0, hostile=False, cast=_cast(10, 100)),))
    disallowed = _evaluate((_enemy(10, 0.0, allowed=False, cast=_cast(10, 100)),))

    assert dead.candidates[0].reason is CryCandidateReason.DEAD_PRIMARY
    assert friendly.candidates[0].reason is CryCandidateReason.NON_HOSTILE_PRIMARY
    assert disallowed.candidates[0].reason is CryCandidateReason.TARGET_NOT_ALLOWED


def test_smart_cry_module_has_no_runtime_action_or_api_reads() -> None:
    source = (SKILLS_DIR / "SmartCry.py").read_text(encoding="utf-8")
    for forbidden in (
        "from Py4GWCoreLib.BuildMgr",
        "BuildMgr(",
        "GLOBAL_CACHE",
        "Agent.",
        "Map.",
        "Party.",
        "Player.",
        "Skillbar",
        "TryPostInterruptLock",
        "CastSkillID",
        "ChangeTarget",
        "PySystem",
    ):
        assert forbidden not in source


class _InterruptRuntime:
    def __init__(self) -> None:
        self.now = 1_100
        self.casting = True
        self.enemy_skill_id = 7
        self.player_position: tuple[float, float] | None = (0.0, 0.0)
        self.enemy_position: tuple[float, float] | None = (100.0, 0.0)
        self.activations = {5: 0.1, 7: 1.0, 8: 1.0}


def _load_interrupt() -> tuple[Any, _InterruptRuntime]:
    runtime = _InterruptRuntime()
    owned_names = {
        name
        for name in sys.modules
        if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name in {"Py4GW", "PyPing", "PySystem"}
    }
    original_modules = {name: sys.modules[name] for name in owned_names}
    root = types.ModuleType("Py4GWCoreLib")
    heroai = types.ModuleType("Py4GWCoreLib.HeroAI")
    heroai.__path__ = [str(ROOT / "Py4GWCoreLib" / "HeroAI")]
    types_mod = types.ModuleType("Py4GWCoreLib.HeroAI.types")
    types_mod.SkillNature = IntEnum("SkillNature", {"Interrupt": 10})

    class _SkillData:
        def GetActivation(self, skill_id: int) -> float:
            return runtime.activations.get(skill_id, 0.0)

    class _SkillFlags:
        def IsAttack(self, _skill_id: int) -> bool:
            return False

        def IsSpell(self, _skill_id: int) -> bool:
            return True

    class _Skill:
        Data = _SkillData()
        Flags = _SkillFlags()

        def GetName(self, skill_id: int) -> str:
            return f"Skill_{skill_id}"

        def GetID(self, _name: str) -> int:
            return 0

    class _GlobalCache:
        Skill = _Skill()

    class _Agent:
        def IsValid(self, _agent_id: int) -> bool:
            return True

        def IsCasting(self, _agent_id: int) -> bool:
            return runtime.casting

        def GetCastingSkillID(self, _agent_id: int) -> int:
            return runtime.enemy_skill_id

        def GetXY(self, _agent_id: int) -> tuple[float, float] | None:
            return runtime.enemy_position

        def GetAttributes(self, _agent_id: int) -> list[Any]:
            return []

        def GetWeaponType(self, _agent_id: int) -> tuple[int, int]:
            return (0, 0)

        def GetWeaponAttackSpeed(self, _agent_id: int) -> float:
            return 1.0

        def GetAttackSpeedModifier(self, _agent_id: int) -> float:
            return 1.0

        def GetNameByID(self, _agent_id: int) -> str:
            return "Enemy"

    class _Player:
        def GetXY(self) -> tuple[float, float] | None:
            return runtime.player_position

        def GetAgentID(self) -> int:
            return 1

    class _Checks:
        class Skills:
            @staticmethod
            def apply_fast_casting(skill_id: int, _fast_casting_level: int) -> tuple[float, float]:
                return runtime.activations.get(skill_id, 0.0), 0.0

    class _Routines:
        Checks = _Checks()

    class _Effects:
        def HasEffect(self, _agent_id: int, _skill_id: int) -> bool:
            return False

    class _Utils:
        def Distance(self, first: tuple[float, float], second: tuple[float, float]) -> float:
            return math.hypot(first[0] - second[0], first[1] - second[1])

    root.GLOBAL_CACHE = _GlobalCache()
    root.Agent = _Agent()
    root.AgentArray = types.SimpleNamespace()
    root.Effects = _Effects()
    root.Player = _Player()
    root.Range = types.SimpleNamespace(
        Spellcast=types.SimpleNamespace(value=1_248),
        SafeCompass=types.SimpleNamespace(value=5_000),
    )
    root.Routines = _Routines()
    root.Utils = _Utils()

    py_system = types.ModuleType("PySystem")
    py_system.get_tick_count64 = lambda: runtime.now
    py_system.Console = types.SimpleNamespace(
        MessageType=types.SimpleNamespace(Debug=0, Info=1, Warning=2),
        Log=lambda *_args, **_kwargs: None,
    )
    py_ping = types.ModuleType("PyPing")
    py_ping.PingHandler = lambda: types.SimpleNamespace(GetCurrentPing=lambda: 10)
    sys.modules.update(
        {
            "Py4GWCoreLib": root,
            "Py4GWCoreLib.HeroAI": heroai,
            "Py4GWCoreLib.HeroAI.types": types_mod,
            "Py4GW": types.ModuleType("Py4GW"),
            "PyPing": py_ping,
            "PySystem": py_system,
        }
    )
    module = _load_module(INTERRUPT_NAME, ROOT / "Py4GWCoreLib" / "HeroAI" / "interrupt.py")
    module.cast_observer = module.CastObserver()
    for name in tuple(sys.modules):
        if name == "Py4GWCoreLib" or name.startswith("Py4GWCoreLib.") or name in {"Py4GW", "PyPing", "PySystem"}:
            sys.modules.pop(name, None)
    sys.modules.update(original_modules)
    return module, runtime


interrupt, interrupt_runtime = _load_interrupt()


def _trusted_interrupt_observation(onset_ms: int = 1_000) -> Any:
    interrupt.cast_observer = interrupt.CastObserver()
    return interrupt.cast_observer.record_observed_onset(
        10,
        7,
        onset_ms,
        observed_at_ms=interrupt_runtime.now,
    )


def test_structured_interrupt_reports_trusted_onset_and_shared_budget() -> None:
    observation = _trusted_interrupt_observation()
    result = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)

    assert result.feasible is True
    assert result.reason is interrupt.InterruptAssessmentReason.FEASIBLE
    assert result.observation_identity == observation.observation_identity
    assert result.observation_age_ms == 100
    assert result.enemy_remaining_ms == 900
    assert result.our_activation_ms == 100
    assert result.ping_allowance_ms == 12
    assert result.interrupt_budget_ms == 162
    assert result.distance_gw == 100.0


def test_first_seen_cast_has_uncertain_onset_and_strict_path_fails_closed() -> None:
    interrupt.cast_observer = interrupt.CastObserver()
    interrupt.cast_observer.observe(10, 7, 1_000)
    result = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)

    assert result.feasible is False
    assert result.reason is interrupt.InterruptAssessmentReason.UNCERTAIN_ONSET
    assert result.observation_untrusted is True


def test_unknown_elapsed_does_not_become_zero_in_strict_mode_but_legacy_bool_remains_callable() -> None:
    interrupt.cast_observer = interrupt.CastObserver()
    strict = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    legacy = interrupt.is_interrupt_feasible(10, 5, 0, 10)

    assert strict.reason is interrupt.InterruptAssessmentReason.UNKNOWN_OBSERVATION_AGE
    assert strict.observation_age_available is False
    assert legacy is True


def test_missing_and_invalid_geometry_fail_closed() -> None:
    _trusted_interrupt_observation()
    interrupt_runtime.player_position = None
    missing = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    interrupt_runtime.player_position = (0.0, 0.0)
    interrupt_runtime.enemy_position = (float("nan"), 0.0)
    invalid = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    interrupt_runtime.enemy_position = (100.0, 0.0)

    assert missing.reason is interrupt.InterruptAssessmentReason.MISSING_GEOMETRY
    assert missing.geometry_missing is True
    assert missing.distance_gw is None
    assert invalid.reason is interrupt.InterruptAssessmentReason.INVALID_GEOMETRY
    assert invalid.geometry_missing is False


def test_invalid_timing_stale_stopped_changed_and_finished_casts_are_rejected() -> None:
    _trusted_interrupt_observation()
    invalid = interrupt.assess_interrupt(10, 5, 0, float("nan"), strict=True)

    interrupt_runtime.now = 11_001
    stale = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    interrupt_runtime.now = 1_100
    interrupt_runtime.casting = False
    stopped = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    interrupt_runtime.casting = True
    interrupt_runtime.enemy_skill_id = 8
    changed = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    interrupt_runtime.enemy_skill_id = 7
    _trusted_interrupt_observation(onset_ms=100)
    interrupt_runtime.now = 1_100
    finished = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    interrupt_runtime.now = 1_100

    assert invalid.reason is interrupt.InterruptAssessmentReason.INVALID_TIMING
    assert stale.reason is interrupt.InterruptAssessmentReason.STALE_OBSERVATION
    assert stopped.reason is interrupt.InterruptAssessmentReason.CAST_STOPPED
    assert changed.reason is interrupt.InterruptAssessmentReason.CAST_CHANGED
    assert finished.reason is interrupt.InterruptAssessmentReason.CAST_FINISHED


def test_insufficient_time_and_clear_feasibility_have_explicit_reasons() -> None:
    _trusted_interrupt_observation(onset_ms=200)
    insufficient = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)
    _trusted_interrupt_observation(onset_ms=1_000)
    feasible = interrupt.assess_interrupt(10, 5, 0, 10, strict=True)

    assert insufficient.reason is interrupt.InterruptAssessmentReason.INSUFFICIENT_TIME
    assert insufficient.feasible is False
    assert feasible.reason is interrupt.InterruptAssessmentReason.FEASIBLE
    assert feasible.feasible is True


def test_sampler_sequence_progression_is_local_and_same_skill_restart_remains_limited() -> None:
    observer = interrupt.CastObserver()
    first = observer.observe(10, 7, 100)
    observer._drop_agent(10)
    second = observer.observe(10, 7, 200)

    assert first.observation_identity != second.observation_identity
    assert first.agent_id == second.agent_id == 10
    assert first.skill_id == second.skill_id == 7


def test_boolean_and_structured_paths_share_the_same_mechanical_result() -> None:
    _trusted_interrupt_observation()
    structured = interrupt.assess_interrupt(10, 5, 0, 10, strict=False)
    legacy = interrupt.is_interrupt_feasible(10, 5, 0, 10)

    assert structured.feasible is legacy
    assert structured.interrupt_budget_ms == 162
    assert structured.enemy_remaining_ms == 900
