"""Deterministic offline behavior tests for the pure SmartMesmer helper."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "Py4GWCoreLib" / "Builds" / "Skills" / "SmartMesmer.py"
MODULE_NAME = "_checkpoint_a_smart_mesmer"
MODULE_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None, "could not load SmartMesmer.py"
smart_mesmer: Any = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_NAME] = smart_mesmer
MODULE_SPEC.loader.exec_module(smart_mesmer)


CombatGroup = smart_mesmer.CombatGroup
CombatSnapshot = smart_mesmer.CombatSnapshot
EnemyObservation = smart_mesmer.EnemyObservation
FocusCandidate = smart_mesmer.FocusCandidate
FocusState = smart_mesmer.FocusState
FocusTransitionParameters = smart_mesmer.FocusTransitionParameters


def _snapshot(*observations: tuple[int, float, float], at: float, lifecycle: str = "life") -> Any:
    return CombatSnapshot(
        enemies=tuple(EnemyObservation(agent_id, x, y) for agent_id, x, y in observations),
        observed_at=at,
        lifecycle_id=lifecycle,
    )


def _group(*agent_ids: int) -> Any:
    return CombatGroup(tuple(EnemyObservation(agent_id, float(index), 0.0) for index, agent_id in enumerate(agent_ids)))


def _candidate(group: Any, value: float, viable: bool = True) -> Any:
    return FocusCandidate(group=group, value=value, viable=viable)


def _parameters(
    *,
    overlap: float = 0.5,
    gap: float = 0.0,
    stability: float = 0.0,
    switch_ratio: float = 1.0,
) -> Any:
    return FocusTransitionParameters(
        minimum_overlap_ratio=overlap,
        gap_grace_seconds=gap,
        challenger_stability_seconds=stability,
        switch_value_ratio=switch_ratio,
    )


def test_connected_components_use_one_cached_pairwise_matrix_and_radius_boundaries() -> None:
    snapshot = _snapshot(
        (30, 6.0, 0.0),
        (10, 0.0, 0.0),
        (40, 20.0, 0.0),
        (20, 3.0, 0.0),
        at=0.0,
    )
    distances = smart_mesmer.pairwise_squared_distances(snapshot)

    assert distances.agent_ids == (10, 20, 30, 40), "distance IDs must be canonical and sorted"
    assert distances.squared_distance(10, 20) == 9.0, "distance result must be squared and reusable"
    assert distances.squared_distance(20, 10) == 9.0, "distance matrix must be symmetric"

    moved_snapshot = _snapshot(
        (30, 7.0, 0.0),
        (10, 0.0, 0.0),
        (40, 20.0, 0.0),
        (20, 3.0, 0.0),
        at=0.1,
    )
    try:
        smart_mesmer.build_combat_groups(moved_snapshot, 3.0, distances=distances)
    except ValueError as error:
        assert "snapshot" in str(error)
    else:
        raise AssertionError("a distance matrix must not be reused for moved observations")

    connected = smart_mesmer.build_combat_groups(snapshot, 3.0, distances=distances)
    assert tuple(group.canonical_id for group in connected) == (
        (10, 20, 30),
        (40,),
    ), "exact-radius links must connect transitively while distant agents stay separate"

    disconnected = smart_mesmer.build_combat_groups(snapshot, 2.999)
    assert tuple(group.canonical_id for group in disconnected) == (
        (10,),
        (20,),
        (30,),
        (40,),
    ), "a radius below the boundary must disconnect the components"


def test_group_ordering_and_identity_are_deterministic() -> None:
    first = _snapshot(
        (9, 9.0, 0.0),
        (3, 1.0, 0.0),
        (7, 100.0, 0.0),
        (2, 0.0, 0.0),
        at=0.0,
    )
    reversed_input = _snapshot(
        (2, 0.0, 0.0),
        (7, 100.0, 0.0),
        (3, 1.0, 0.0),
        (9, 9.0, 0.0),
        at=0.0,
    )

    first_groups = smart_mesmer.build_combat_groups(first, 2.0)
    reversed_groups = smart_mesmer.build_combat_groups(reversed_input, 2.0)

    expected = ((2, 3), (7,), (9,))
    assert tuple(group.canonical_id for group in first_groups) == expected, "group IDs must include all members"
    assert (
        tuple(group.canonical_id for group in reversed_groups) == expected
    ), "group ordering cannot depend on observation iteration order"


def test_equal_initial_values_use_canonical_identity_as_the_tie_breaker() -> None:
    state = smart_mesmer.transition_focus(
        FocusState(),
        _snapshot((20, 0.0, 0.0), (10, 20.0, 0.0), at=0.0),
        (_candidate(_group(20), 5.0), _candidate(_group(10), 5.0)),
        _parameters(),
    )

    assert state.focused_group is not None
    assert state.focused_group.canonical_id == (10,), "equal values must choose the canonical lowest identity"


def test_focus_retains_a_group_through_membership_change_by_overlap() -> None:
    initial_group = smart_mesmer.build_combat_groups(
        _snapshot((10, 0.0, 0.0), (20, 1.0, 0.0), at=0.0),
        2.0,
    )[0]
    changed_group = smart_mesmer.build_combat_groups(
        _snapshot((20, 1.0, 0.0), (30, 2.0, 0.0), at=1.0),
        2.0,
    )[0]
    parameters = _parameters(overlap=0.5, switch_ratio=2.0)

    state = smart_mesmer.transition_focus(
        FocusState(),
        _snapshot((10, 0.0, 0.0), (20, 1.0, 0.0), at=0.0),
        (_candidate(initial_group, 10.0),),
        parameters,
    )
    retained = smart_mesmer.transition_focus(
        state,
        _snapshot((20, 1.0, 0.0), (30, 2.0, 0.0), at=1.0),
        (_candidate(changed_group, 10.0),),
        parameters,
    )

    assert retained.focused_group is not None
    assert retained.focused_group.canonical_id == (
        20,
        30,
    ), "the retained focus must follow shared membership instead of the old lowest AgentID"
    assert retained.gap_started_at is None


def test_transient_gap_uses_the_caller_supplied_boundary_and_resets_after_it() -> None:
    group = _group(1, 2)
    parameters = _parameters(gap=0.5)
    state = smart_mesmer.transition_focus(
        FocusState(),
        _snapshot((1, 0.0, 0.0), (2, 1.0, 0.0), at=0.0),
        (_candidate(group, 10.0),),
        parameters,
    )

    during_gap = smart_mesmer.transition_focus(
        state,
        _snapshot(at=0.0),
        (),
        parameters,
    )
    at_boundary = smart_mesmer.transition_focus(
        during_gap,
        _snapshot(at=0.5),
        (),
        parameters,
    )
    after_gap = smart_mesmer.transition_focus(
        at_boundary,
        _snapshot(at=0.51),
        (),
        parameters,
    )

    assert during_gap.focused_group == group, "a missing group must survive inside the grace interval"
    assert at_boundary.focused_group == group, "the caller-supplied grace boundary is inclusive"
    assert after_gap.focused_group is None, "a focus must reset after the grace interval expires"


def test_lifecycle_change_resets_old_focus_and_pending_state() -> None:
    old_group = _group(1)
    new_group = _group(99)
    parameters = _parameters(stability=0.8)
    state = smart_mesmer.transition_focus(
        FocusState(),
        _snapshot((1, 0.0, 0.0), at=0.0, lifecycle="old-life"),
        (_candidate(old_group, 10.0),),
        parameters,
    )
    pending = smart_mesmer.transition_focus(
        state,
        _snapshot((1, 0.0, 0.0), (99, 10.0, 0.0), at=0.1, lifecycle="old-life"),
        (_candidate(old_group, 10.0), _candidate(new_group, 20.0)),
        parameters,
    )
    reset = smart_mesmer.transition_focus(
        pending,
        _snapshot((99, 10.0, 0.0), at=0.2, lifecycle="new-life"),
        (_candidate(new_group, 1.0),),
        parameters,
    )

    assert pending.challenger_group == new_group, "the setup must create pending old-lifecycle state"
    assert reset.focused_group == new_group, "a lifecycle change must choose from the new lifecycle"
    assert reset.challenger_group is None and reset.gap_started_at is None


def test_disconnected_challenger_waits_for_stability_then_switches() -> None:
    focused_group = _group(1, 2)
    challenger_group = _group(10, 11)
    parameters = _parameters(stability=0.5, switch_ratio=1.1)
    state = smart_mesmer.transition_focus(
        FocusState(),
        _snapshot(at=0.0),
        (_candidate(focused_group, 10.0),),
        parameters,
    )

    first_seen = smart_mesmer.transition_focus(
        state,
        _snapshot(at=1.0),
        (_candidate(focused_group, 10.0), _candidate(challenger_group, 12.0)),
        parameters,
    )
    before_stable = smart_mesmer.transition_focus(
        first_seen,
        _snapshot(at=1.49),
        (_candidate(focused_group, 10.0), _candidate(challenger_group, 12.0)),
        parameters,
    )
    switched = smart_mesmer.transition_focus(
        before_stable,
        _snapshot(at=1.5),
        (_candidate(focused_group, 10.0), _candidate(challenger_group, 12.0)),
        parameters,
    )

    assert first_seen.focused_group == focused_group
    assert first_seen.challenger_group == challenger_group
    assert before_stable.focused_group == focused_group, "a disconnected challenger must not switch early"
    assert switched.focused_group == challenger_group, "the challenger switches after caller-supplied stability"


def test_switch_ratio_is_caller_supplied_and_changes_behavior() -> None:
    focused_group = _group(1)
    challenger_group = _group(2)
    snapshot = _snapshot(at=1.0)

    low_ratio_state = smart_mesmer.transition_focus(
        smart_mesmer.transition_focus(
            FocusState(),
            _snapshot(at=0.0),
            (_candidate(focused_group, 10.0),),
            _parameters(switch_ratio=1.1),
        ),
        snapshot,
        (_candidate(focused_group, 10.0), _candidate(challenger_group, 12.0)),
        _parameters(switch_ratio=1.1),
    )
    high_ratio_state = smart_mesmer.transition_focus(
        smart_mesmer.transition_focus(
            FocusState(),
            _snapshot(at=0.0),
            (_candidate(focused_group, 10.0),),
            _parameters(switch_ratio=1.3),
        ),
        snapshot,
        (_candidate(focused_group, 10.0), _candidate(challenger_group, 12.0)),
        _parameters(switch_ratio=1.3),
    )

    assert low_ratio_state.focused_group == challenger_group, "a lower caller ratio permits the switch"
    assert high_ratio_state.focused_group == focused_group, "a higher caller ratio rejects the same challenger"


def test_nonviable_candidates_do_not_compete_for_initial_focus() -> None:
    viable_group = _group(1)
    nonviable_group = _group(2)
    state = smart_mesmer.transition_focus(
        FocusState(),
        _snapshot(at=0.0),
        (_candidate(nonviable_group, 100.0, viable=False), _candidate(viable_group, 1.0)),
        _parameters(),
    )

    assert state.focused_group == viable_group, "viability is caller-supplied and must be honored before scoring"


def test_focus_parameters_are_explicit_caller_inputs() -> None:
    parameters = FocusTransitionParameters(
        minimum_overlap_ratio=0.37,
        gap_grace_seconds=0.11,
        challenger_stability_seconds=0.29,
        switch_value_ratio=1.07,
    )

    assert parameters.minimum_overlap_ratio == 0.37
    assert parameters.gap_grace_seconds == 0.11
    assert parameters.challenger_stability_seconds == 0.29
    assert parameters.switch_value_ratio == 1.07
