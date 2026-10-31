"""Stateless live service observations; scheduling and retained state belong to the widget."""

import math
import re
import unicodedata
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import cast

ServiceCandidateSnapshot = tuple[tuple[float, float] | None, str, tuple[int, ...], tuple[int, ...]]


@dataclass(frozen=True)
class LiveServiceRoleScan:
    """One bounded view of currently materialized outpost service candidates."""

    player_xy: tuple[float, float] | None
    player_xy_source: str
    candidate_ids: tuple[int, ...]
    candidate_fingerprint: tuple[int, ...]
    resolved_coords: dict[str, tuple[float, float]]
    pending_agent_ids: frozenset[int]


def normalize_service_role_text(value: object) -> str:
    """Normalize a localized service-role label for exact comparisons."""

    text = str(value or "").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold()
    return re.sub(r"\s+", " ", text).strip(" []\t\r\n")


def extract_agent_role_suffix(value: object) -> str:
    """Return only a final complete ``[role]`` suffix, or a role-only name."""

    text = str(value or "").strip()
    if not text:
        return ""
    suffix_match = re.search(r"\[([^\[\]]+)\]\s*$", text)
    if suffix_match is not None:
        return str(suffix_match.group(1) or "").strip()
    if "[" in text or "]" in text:
        return ""
    return text


def canonical_service_role(value: object, *, role_aliases: Mapping[str, tuple[str, ...]]) -> str:
    """Map a localized role suffix or role-only name to its service key."""

    normalized = normalize_service_role_text(extract_agent_role_suffix(value))
    if not normalized:
        return ""
    for service_key, aliases in role_aliases.items():
        if any(normalized == normalize_service_role_text(alias) for alias in aliases):
            return service_key
    return ""


def agent_name_matches_service_role(
    agent_name: object, expected_role: object, *, role_aliases: Mapping[str, tuple[str, ...]]
) -> bool:
    """Match a live NPC only by an exact localized service role."""

    safe_expected_role = str(expected_role or "").strip()
    canonical_expected = (
        safe_expected_role
        if safe_expected_role in role_aliases
        else canonical_service_role(safe_expected_role, role_aliases=role_aliases)
    )
    if not canonical_expected:
        return False
    canonical_live = canonical_service_role(agent_name, role_aliases=role_aliases)
    return bool(canonical_live and canonical_live == canonical_expected)


def coerce_agent_xy(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(cast(Any, value)) < 2:
        return None
    try:
        x = float(cast(Any, value)[0])
        y = float(cast(Any, value)[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    return x, y


def get_agent_search_origin(
    agent_api: object, *, player_api: object, coerce_int: Callable[[object, int], int]
) -> tuple[tuple[float, float] | None, str]:
    """Prefer the live player agent and use the legacy position only when that API is absent."""

    get_player_agent_id = getattr(player_api, "GetAgentID", None)
    get_agent_xy = getattr(agent_api, "GetXY", None)
    if callable(get_player_agent_id) and callable(get_agent_xy):
        try:
            player_agent_id = max(0, coerce_int(get_player_agent_id(), 0))
            if player_agent_id <= 0:
                return None, "player agent unavailable"
            fresh_xy = coerce_agent_xy(get_agent_xy(player_agent_id))
            if fresh_xy is None:
                return None, "player agent coordinates unavailable"
            return fresh_xy, "player agent"
        except Exception:
            # If the live-agent path exists but fails, an older Player.GetXY value may belong
            # to the previous map instance. Fail closed instead of searching from stale data.
            return None, "player agent coordinates unavailable"

    try:
        fallback_xy = coerce_agent_xy(getattr(player_api, "GetXY")())
    except Exception:
        fallback_xy = None
    if fallback_xy is None:
        return None, "player coordinates unavailable"
    return fallback_xy, "Player.GetXY fallback"


def get_live_service_candidate_snapshot(
    *,
    player_api: object,
    coerce_int: Callable[[object, int], int],
    search_distance: float,
) -> tuple[tuple[float, float] | None, str, tuple[int, ...], tuple[int, ...]]:
    """Read the current in-range NPC population without requesting names."""

    try:
        from Py4GWCoreLib import Agent
        from Py4GWCoreLib import AgentArray

        player_xy, player_xy_source = get_agent_search_origin(Agent, player_api=player_api, coerce_int=coerce_int)
        if player_xy is None:
            return None, player_xy_source, (), ()

        in_range_ids = cast(Any, AgentArray).Filter.ByDistance(
            AgentArray.GetNPCMinipetArray(),
            player_xy,
            search_distance,
        )
        candidate_ids = tuple(
            max(0, coerce_int(agent_id, 0))
            for agent_id in cast(Any, AgentArray).Sort.ByDistance(in_range_ids, player_xy)
            if max(0, coerce_int(agent_id, 0)) > 0
        )
        return (
            player_xy,
            player_xy_source,
            candidate_ids,
            tuple(sorted(set(candidate_ids))),
        )
    except Exception as exc:
        return None, f"service candidate APIs unavailable ({type(exc).__name__})", (), ()


def scan_live_service_roles(
    snapshot: ServiceCandidateSnapshot,
    *,
    role_aliases: Mapping[str, tuple[str, ...]],
) -> LiveServiceRoleScan:
    """Decode each current candidate once and resolve nearest exact service roles."""

    player_xy, player_xy_source, candidate_ids, fingerprint = snapshot
    resolved_coords: dict[str, tuple[float, float]] = {}
    pending_agent_ids: set[int] = set()

    if player_xy is not None:
        try:
            from Py4GWCoreLib import Agent

            for agent_id in candidate_ids:
                try:
                    live_name = str(Agent.GetNameByID(agent_id) or "").strip()
                except Exception:
                    live_name = ""
                pending = not bool(live_name)
                if pending:
                    pending_agent_ids.add(agent_id)
                service_role = canonical_service_role(live_name, role_aliases=role_aliases) if live_name else ""
                if service_role:
                    try:
                        agent_xy = coerce_agent_xy(Agent.GetXY(agent_id))
                    except Exception:
                        agent_xy = None
                    if service_role not in resolved_coords and agent_xy is not None:
                        resolved_coords[service_role] = agent_xy
        except Exception:
            pending_agent_ids.update(candidate_ids)

    scan = LiveServiceRoleScan(
        player_xy=player_xy,
        player_xy_source=player_xy_source,
        candidate_ids=candidate_ids,
        candidate_fingerprint=fingerprint,
        resolved_coords=resolved_coords,
        pending_agent_ids=frozenset(pending_agent_ids),
    )
    return scan
