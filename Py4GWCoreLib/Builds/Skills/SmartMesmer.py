"""Pure combat geometry and focus-retention primitives for combat policies."""

from __future__ import annotations

import math
from collections.abc import Hashable
from collections.abc import Iterable
from dataclasses import dataclass

GroupIdentity = tuple[int, ...]


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class EnemyObservation:
    """Immutable geometry for one observed enemy."""

    agent_id: int
    x: float
    y: float

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, int):
            raise TypeError("agent_id must be an int")
        _require_finite("x", self.x)
        _require_finite("y", self.y)


@dataclass(frozen=True, slots=True)
class CombatSnapshot:
    """A deterministic, immutable set of enemy observations at one time."""

    enemies: tuple[EnemyObservation, ...]
    observed_at: float
    lifecycle_id: Hashable | None = None

    def __post_init__(self) -> None:
        enemies = tuple(sorted(tuple(self.enemies), key=lambda enemy: enemy.agent_id))
        agent_ids = tuple(enemy.agent_id for enemy in enemies)
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("a snapshot cannot contain duplicate agent IDs")
        _require_finite("observed_at", self.observed_at)
        object.__setattr__(self, "enemies", enemies)

    @property
    def agent_ids(self) -> tuple[int, ...]:
        return tuple(enemy.agent_id for enemy in self.enemies)

    @property
    def geometry_key(self) -> tuple[tuple[int, float, float], ...]:
        return tuple((enemy.agent_id, enemy.x, enemy.y) for enemy in self.enemies)


@dataclass(frozen=True, slots=True)
class PairwiseDistances:
    """Immutable squared-distance matrix indexed by sorted agent IDs."""

    agent_ids: tuple[int, ...]
    matrix: tuple[tuple[float, ...], ...]
    geometry_key: tuple[tuple[int, float, float], ...]

    def __post_init__(self) -> None:
        agent_ids = tuple(self.agent_ids)
        matrix = tuple(tuple(row) for row in self.matrix)
        geometry_key = tuple(tuple(entry) for entry in self.geometry_key)
        if agent_ids != tuple(sorted(agent_ids)):
            raise ValueError("agent_ids must be sorted")
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("agent_ids cannot contain duplicates")
        if len(matrix) != len(agent_ids) or any(len(row) != len(agent_ids) for row in matrix):
            raise ValueError("distance matrix must be square and match agent_ids")
        if any(len(entry) != 3 for entry in geometry_key) or tuple(entry[0] for entry in geometry_key) != agent_ids:
            raise ValueError("geometry_key must match sorted agent IDs")
        object.__setattr__(self, "agent_ids", agent_ids)
        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "geometry_key", geometry_key)

    def squared_distance(self, first_agent_id: int, second_agent_id: int) -> float:
        """Return the cached squared distance between two observed agents."""

        try:
            first_index = self.agent_ids.index(first_agent_id)
            second_index = self.agent_ids.index(second_agent_id)
        except ValueError as error:
            raise KeyError("agent ID is not present in this distance matrix") from error
        return self.matrix[first_index][second_index]


def pairwise_squared_distances(snapshot: CombatSnapshot) -> PairwiseDistances:
    """Calculate each unordered pair once and return its reusable distance matrix."""

    observations = snapshot.enemies
    matrix = [[0.0 for _ in observations] for _ in observations]
    for left_index, left in enumerate(observations):
        for right_index in range(left_index + 1, len(observations)):
            right = observations[right_index]
            delta_x = left.x - right.x
            delta_y = left.y - right.y
            distance_squared = delta_x * delta_x + delta_y * delta_y
            matrix[left_index][right_index] = distance_squared
            matrix[right_index][left_index] = distance_squared

    return PairwiseDistances(
        agent_ids=snapshot.agent_ids,
        matrix=tuple(tuple(row) for row in matrix),
        geometry_key=snapshot.geometry_key,
    )


@dataclass(frozen=True, slots=True)
class CombatGroup:
    """A deterministic connected component of enemy observations."""

    members: tuple[EnemyObservation, ...]

    def __post_init__(self) -> None:
        members = tuple(sorted(tuple(self.members), key=lambda enemy: enemy.agent_id))
        agent_ids = tuple(enemy.agent_id for enemy in members)
        if not members:
            raise ValueError("a combat group cannot be empty")
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("a combat group cannot contain duplicate agent IDs")
        object.__setattr__(self, "members", members)

    @property
    def agent_ids(self) -> tuple[int, ...]:
        return tuple(enemy.agent_id for enemy in self.members)

    @property
    def canonical_id(self) -> GroupIdentity:
        """Return the full sorted membership identity for diagnostics and ordering."""

        return self.agent_ids


def build_combat_groups(
    snapshot: CombatSnapshot,
    link_radius: float,
    *,
    distances: PairwiseDistances | None = None,
) -> tuple[CombatGroup, ...]:
    """Build sorted connected components using the caller-supplied link radius."""

    _require_finite("link_radius", link_radius)
    if link_radius < 0.0:
        raise ValueError("link_radius must be non-negative")

    if distances is None:
        distances = pairwise_squared_distances(snapshot)
    elif distances.agent_ids != snapshot.agent_ids or distances.geometry_key != snapshot.geometry_key:
        raise ValueError("distances must have been calculated for this snapshot")

    radius_squared = link_radius * link_radius
    remaining = set(range(len(snapshot.enemies)))
    groups: list[CombatGroup] = []

    for start_index in range(len(snapshot.enemies)):
        if start_index not in remaining:
            continue

        remaining.remove(start_index)
        frontier = [start_index]
        component_indices: list[int] = []
        frontier_index = 0
        while frontier_index < len(frontier):
            current_index = frontier[frontier_index]
            frontier_index += 1
            component_indices.append(current_index)
            for candidate_index in range(len(snapshot.enemies)):
                if candidate_index not in remaining:
                    continue
                if distances.matrix[current_index][candidate_index] <= radius_squared:
                    remaining.remove(candidate_index)
                    frontier.append(candidate_index)

        groups.append(CombatGroup(tuple(snapshot.enemies[index] for index in component_indices)))

    return tuple(sorted(groups, key=lambda group: group.canonical_id))


def group_overlap_ratio(first: CombatGroup, second: CombatGroup) -> float:
    """Return shared membership divided by the smaller group's membership."""

    shared_members = len(set(first.agent_ids).intersection(second.agent_ids))
    return shared_members / min(len(first.members), len(second.members))


@dataclass(frozen=True, slots=True)
class FocusCandidate:
    """A caller-scored group candidate with explicit viability."""

    group: CombatGroup
    value: float
    viable: bool = True

    def __post_init__(self) -> None:
        _require_finite("candidate value", self.value)
        if self.value < 0.0:
            raise ValueError("candidate value must be non-negative")


@dataclass(frozen=True, slots=True)
class FocusTransitionParameters:
    """Caller-owned thresholds for the generic focus state transition."""

    minimum_overlap_ratio: float
    gap_grace_seconds: float
    challenger_stability_seconds: float
    switch_value_ratio: float

    def __post_init__(self) -> None:
        _require_finite("minimum_overlap_ratio", self.minimum_overlap_ratio)
        _require_finite("gap_grace_seconds", self.gap_grace_seconds)
        _require_finite("challenger_stability_seconds", self.challenger_stability_seconds)
        _require_finite("switch_value_ratio", self.switch_value_ratio)
        if not 0.0 < self.minimum_overlap_ratio <= 1.0:
            raise ValueError("minimum_overlap_ratio must be in the interval (0, 1]")
        if self.gap_grace_seconds < 0.0:
            raise ValueError("gap_grace_seconds must be non-negative")
        if self.challenger_stability_seconds < 0.0:
            raise ValueError("challenger_stability_seconds must be non-negative")
        if self.switch_value_ratio <= 0.0:
            raise ValueError("switch_value_ratio must be positive")


@dataclass(frozen=True, slots=True)
class FocusState:
    """Immutable focus state returned by :func:`transition_focus`."""

    lifecycle_id: Hashable | None = None
    focused_group: CombatGroup | None = None
    focused_value: float | None = None
    gap_started_at: float | None = None
    challenger_group: CombatGroup | None = None
    challenger_value: float | None = None
    challenger_since: float | None = None

    def __post_init__(self) -> None:
        if self.focused_group is None and self.focused_value is not None:
            raise ValueError("focused_value requires focused_group")
        if self.focused_group is not None and self.focused_value is None:
            raise ValueError("focused_group requires focused_value")
        if self.focused_value is not None:
            _require_finite("focused value", self.focused_value)
        if self.gap_started_at is not None:
            _require_finite("gap_started_at", self.gap_started_at)

        if self.challenger_group is None:
            if self.challenger_value is not None or self.challenger_since is not None:
                raise ValueError("challenger fields require challenger_group")
        elif self.challenger_value is None or self.challenger_since is None:
            raise ValueError("challenger_group requires value and start time")
        else:
            _require_finite("challenger value", self.challenger_value)
            _require_finite("challenger_since", self.challenger_since)


def _candidate_sort_key(candidate: FocusCandidate) -> tuple[float, GroupIdentity]:
    return (-candidate.value, candidate.group.canonical_id)


def _eligible_candidates(candidates: Iterable[FocusCandidate]) -> tuple[FocusCandidate, ...]:
    supplied = tuple(candidates)
    candidate_ids = [candidate.group.canonical_id for candidate in supplied]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidates cannot contain duplicate group identities")
    return tuple(sorted((candidate for candidate in supplied if candidate.viable), key=_candidate_sort_key))


def _best_matching_candidate(
    reference: CombatGroup,
    candidates: tuple[FocusCandidate, ...],
    minimum_overlap_ratio: float,
) -> FocusCandidate | None:
    matches = [
        (group_overlap_ratio(reference, candidate.group), candidate)
        for candidate in candidates
        if group_overlap_ratio(reference, candidate.group) >= minimum_overlap_ratio
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], -item[1].value, item[1].group.canonical_id))
    return matches[0][1]


def _best_challenger(
    reference: CombatGroup,
    candidates: tuple[FocusCandidate, ...],
    focused_value: float,
    parameters: FocusTransitionParameters,
) -> FocusCandidate | None:
    threshold = focused_value * parameters.switch_value_ratio
    challengers = [
        candidate
        for candidate in candidates
        if group_overlap_ratio(reference, candidate.group) < parameters.minimum_overlap_ratio
        and candidate.value > threshold
    ]
    return challengers[0] if challengers else None


def _initial_focus(
    lifecycle_id: Hashable | None,
    candidates: tuple[FocusCandidate, ...],
) -> FocusState:
    if not candidates:
        return FocusState(lifecycle_id=lifecycle_id)
    candidate = candidates[0]
    return FocusState(
        lifecycle_id=lifecycle_id,
        focused_group=candidate.group,
        focused_value=candidate.value,
    )


def _track_challenger(
    state: FocusState,
    snapshot: CombatSnapshot,
    candidate: FocusCandidate,
    parameters: FocusTransitionParameters,
) -> FocusState:
    if (
        state.challenger_group is not None
        and state.challenger_since is not None
        and group_overlap_ratio(state.challenger_group, candidate.group) >= parameters.minimum_overlap_ratio
    ):
        challenger_since = state.challenger_since
    else:
        challenger_since = snapshot.observed_at

    if snapshot.observed_at - challenger_since >= parameters.challenger_stability_seconds:
        return FocusState(
            lifecycle_id=snapshot.lifecycle_id,
            focused_group=candidate.group,
            focused_value=candidate.value,
        )

    return FocusState(
        lifecycle_id=snapshot.lifecycle_id,
        focused_group=state.focused_group,
        focused_value=state.focused_value,
        challenger_group=candidate.group,
        challenger_value=candidate.value,
        challenger_since=challenger_since,
    )


def transition_focus(
    state: FocusState,
    snapshot: CombatSnapshot,
    candidates: Iterable[FocusCandidate],
    parameters: FocusTransitionParameters,
) -> FocusState:
    """Advance focus deterministically using only caller-supplied policy values."""

    eligible_candidates = _eligible_candidates(candidates)
    if state.lifecycle_id != snapshot.lifecycle_id or state.focused_group is None:
        return _initial_focus(snapshot.lifecycle_id, eligible_candidates)

    matching_candidate = _best_matching_candidate(
        state.focused_group,
        eligible_candidates,
        parameters.minimum_overlap_ratio,
    )
    if matching_candidate is not None:
        challenger = _best_challenger(
            matching_candidate.group,
            eligible_candidates,
            matching_candidate.value,
            parameters,
        )
        if challenger is None:
            return FocusState(
                lifecycle_id=snapshot.lifecycle_id,
                focused_group=matching_candidate.group,
                focused_value=matching_candidate.value,
            )
        return _track_challenger(state, snapshot, challenger, parameters)

    gap_started_at = state.gap_started_at
    if gap_started_at is None:
        gap_started_at = snapshot.observed_at
    if snapshot.observed_at - gap_started_at <= parameters.gap_grace_seconds:
        return FocusState(
            lifecycle_id=snapshot.lifecycle_id,
            focused_group=state.focused_group,
            focused_value=state.focused_value,
            gap_started_at=gap_started_at,
        )

    return _initial_focus(snapshot.lifecycle_id, eligible_candidates)


__all__ = [
    "CombatGroup",
    "CombatSnapshot",
    "EnemyObservation",
    "FocusCandidate",
    "FocusState",
    "FocusTransitionParameters",
    "GroupIdentity",
    "PairwiseDistances",
    "build_combat_groups",
    "group_overlap_ratio",
    "pairwise_squared_distances",
    "transition_focus",
]
