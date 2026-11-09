"""Live service observations and per-widget service-resolution state."""

import math
import re
import unicodedata
from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import Protocol
from typing import cast

ServiceCandidateSnapshot = tuple[tuple[float, float] | None, str, tuple[int, ...], tuple[int, ...]]
SupportedContext = tuple[bool, str, dict[str, tuple[float, float] | None]]


@dataclass(frozen=True)
class LiveServiceRoleScan:
    """One bounded view of currently materialized outpost service candidates."""

    player_xy: tuple[float, float] | None
    player_xy_source: str
    candidate_ids: tuple[int, ...]
    candidate_fingerprint: tuple[int, ...]
    resolved_coords: dict[str, tuple[float, float]]
    pending_agent_ids: frozenset[int]


class SelectorLike(Protocol):
    @property
    def label(self) -> str: ...

    @property
    def encoded_identity(self) -> tuple[int, ...]: ...

    @property
    def model_id(self) -> int: ...

    @property
    def expected_xy(self) -> tuple[float, float]: ...

    @property
    def coordinate_tolerance(self) -> float: ...


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


def normalize_vendor_encoded_identity(raw_identity: object) -> tuple[int, ...] | None:
    """Return exact encoded bytes without invoking any string decoder."""

    if not isinstance(raw_identity, (bytes, bytearray, list, tuple)):
        return None
    try:
        values = tuple(int(value) for value in raw_identity)
    except (TypeError, ValueError):
        return None
    if any(value < 0 or value > 255 for value in values):
        return None
    return values


class ServiceResolutionSession:
    """Per-widget service evidence, context caching and cooperative discovery."""

    def __init__(
        self,
        *,
        default_selectors: Mapping[str, str],
        supported_selectors: Mapping[int, Mapping[str, str]],
        rune_selectors: Mapping[int, str],
        scroll_selectors: Mapping[int, str],
        service_model_ids: Mapping[int, Mapping[str, int]],
        map_service_selectors: Mapping[int, Mapping[str, tuple[SelectorLike, ...]]],
        role_aliases: Mapping[str, tuple[str, ...]],
        merchant_labels: Mapping[str, str],
        merchant_type: str,
        materials_type: str,
        rune_type: str,
        scroll_type: str,
        rare_materials_type: str,
        consumable_type: str,
        embark_map_id: int,
        search_max_dist: float,
        name_retry_seconds: float,
        name_retry_poll_seconds: float,
        event_poll_seconds: float,
        meaningful_move_dist: float,
        xunlai_agent_name: str,
        xunlai_chest_name: str,
        xunlai_agent_model_ids: tuple[int, ...],
        xunlai_chest_model_id: int,
        module_name: str,
        get_map_id: Callable[[], int],
        get_map_name: Callable[[int], str],
        is_map_ready: Callable[[], bool],
        is_outpost: Callable[[], bool],
        is_guild_hall: Callable[[], bool],
        monotonic: Callable[[], float],
        candidate_snapshot: Callable[[], ServiceCandidateSnapshot],
        player_origin: Callable[[object], tuple[tuple[float, float] | None, str]],
        coerce_int: Callable[[], Callable[[object, int], int]],
        selector_authoritative: Callable[[str, str], bool],
        resolve_agent_step: Callable[[dict[str, object], str, int, str, float, bool], tuple[float, float] | None],
        storage_is_open: Callable[[], bool],
        scroll_policy: Callable[[], bool],
        debug_log: Callable[[Callable[[], str]], None],
        log_failure: Callable[[str, Callable[[], str]], None],
        format_coords: Callable[[], Callable[[tuple[float, float] | None], str]],
    ) -> None:
        self._default_selectors = default_selectors
        self._supported_selectors = supported_selectors
        self._rune_selectors = rune_selectors
        self._scroll_selectors = scroll_selectors
        self._service_model_ids = service_model_ids
        self._map_service_selectors = map_service_selectors
        self._role_aliases = role_aliases
        self._merchant_labels = merchant_labels
        self._merchant_type = merchant_type
        self._materials_type = materials_type
        self._rune_type = rune_type
        self._scroll_type = scroll_type
        self._rare_materials_type = rare_materials_type
        self._consumable_type = consumable_type
        self._embark_map_id = embark_map_id
        self._search_max_dist = search_max_dist
        self._name_retry_seconds = name_retry_seconds
        self._name_retry_poll_seconds = name_retry_poll_seconds
        self._event_poll_seconds = event_poll_seconds
        self._meaningful_move_dist = meaningful_move_dist
        self._xunlai_agent_name = xunlai_agent_name
        self._xunlai_chest_name = xunlai_chest_name
        self._xunlai_agent_model_ids = xunlai_agent_model_ids
        self._xunlai_chest_model_id = xunlai_chest_model_id
        self._module_name = module_name
        self._get_map_id = get_map_id
        self._get_map_name = get_map_name
        self._is_map_ready = is_map_ready
        self._is_outpost = is_outpost
        self._is_guild_hall = is_guild_hall
        self._monotonic = monotonic
        self._candidate_snapshot = candidate_snapshot
        self._player_origin = player_origin
        self._coerce_int = coerce_int
        self._selector_authoritative = selector_authoritative
        self._resolve_agent_step = resolve_agent_step
        self._storage_is_open = storage_is_open
        self._scroll_policy = scroll_policy
        self._debug_log = debug_log
        self._log_failure = log_failure
        self._format_coords = format_coords
        self.cached_context_map_id: int = -1
        self.cached_supported_context: SupportedContext | None = None
        self.observed_coords: dict[str, tuple[float, float]] = {}
        self.candidate_fingerprint: tuple[int, ...] | None = None
        self.retry_fingerprint: tuple[int, ...] | None = None
        self.player_anchor: tuple[float, float] | None = None
        self.pending_agent_ids: set[int] = set()
        self.name_retry_deadline_at: float = 0.0
        self.next_poll_at: float = 0.0
        self.lifecycle_active: bool = False

    def invalidate_context(self) -> None:
        self.cached_context_map_id = -1
        self.cached_supported_context = None

    def reset_observations(self) -> None:
        """Clear observations that are valid only for the current map instance."""

        self.observed_coords = {}
        self.candidate_fingerprint = None
        self.retry_fingerprint = None
        self.player_anchor = None
        self.pending_agent_ids = set()
        self.name_retry_deadline_at = 0.0
        self.next_poll_at = 0.0
        self.lifecycle_active = False

    def resolve_rune_trader_coords(
        self,
        map_id: int,
        *,
        log_failures: bool = True,
        role_scan: LiveServiceRoleScan | None = None,
        resolve_role_fallback: bool = True,
    ) -> tuple[float, float] | None:
        selector_name = str(self._rune_selectors.get(int(map_id), "") or "").strip()
        return self.resolve_service_coords(
            map_id=map_id,
            service_type=self._rune_type,
            selector_name=selector_name,
            fallback_role=self._rune_type,
            log_failures=log_failures,
            role_scan=role_scan,
            resolve_role_fallback=resolve_role_fallback,
        )

    def get_scroll_trader_lookup(self) -> tuple[str, str]:
        if self._is_guild_hall():
            return "scroll_trader", self._scroll_type
        return "rare_scroll_trader", "rare_scroll_trader"

    def get_scroll_trader_service_label(self) -> str:
        return "Scroll Trader" if self._is_guild_hall() else "Rare Scroll Trader"

    def resolve_scroll_trader_coords(
        self,
        map_id: int,
        selector_data: Mapping[str, str] | None = None,
        *,
        log_failures: bool = True,
        role_scan: LiveServiceRoleScan | None = None,
        resolve_role_fallback: bool = True,
    ) -> tuple[float, float] | None:
        selector_key, fallback_role = self.get_scroll_trader_lookup()
        selector_name = str(self._scroll_selectors.get(int(map_id), "") or "").strip()
        if not selector_name and selector_data:
            selector_name = str(selector_data.get(selector_key, "") or "").strip()
        return self.resolve_service_coords(
            map_id=map_id,
            service_type=self._scroll_type,
            selector_name=selector_name,
            fallback_role=fallback_role,
            log_failures=log_failures,
            role_scan=role_scan,
            resolve_role_fallback=resolve_role_fallback,
        )

    def resolve_map_specific_service_coords(
        self,
        *,
        map_id: int,
        service_type: str,
        selectors: tuple[SelectorLike, ...],
        log_failures: bool,
    ) -> tuple[float, float] | None:
        safe_map_id = max(0, self._coerce_int()(map_id, 0))
        service_label = self._merchant_labels.get(service_type, service_type)
        current_map_id = max(0, self._coerce_int()(self._get_map_id(), 0))
        if safe_map_id <= 0 or current_map_id != safe_map_id:
            if log_failures:
                self._log_failure(
                    self._module_name,
                    lambda: f"Map-specific {service_label} selector rejected: current map {current_map_id} "
                    f"does not match required map {safe_map_id}.",
                )
            return None

        try:
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import AgentArray
        except Exception as exc:
            if log_failures:
                self._log_failure(
                    self._module_name,
                    lambda exc=exc: f"Map-specific {service_label} selector APIs are unavailable: {exc}",
                )
            return None

        player_xy, player_xy_source = self._player_origin(Agent)
        if player_xy is None:
            if log_failures:
                self._log_failure(
                    self._module_name,
                    lambda: f"Map-specific {service_label} selector rejected: {player_xy_source}.",
                )
            return None

        try:
            npc_agent_ids = tuple(
                dict.fromkeys(
                    safe_agent_id
                    for agent_id in AgentArray.GetNPCMinipetArray()
                    if (safe_agent_id := max(0, self._coerce_int()(agent_id, 0))) > 0
                )
            )
        except Exception as exc:
            if log_failures:
                self._log_failure(
                    self._module_name,
                    lambda exc=exc: f"Map-specific {service_label} selector could not read the NPC array: {exc}",
                )
            return None

        encoded_identity_by_agent: dict[int, tuple[int, ...] | None] = {}
        model_id_by_agent: dict[int, int] = {}
        xy_by_agent: dict[int, tuple[float, float] | None] = {}

        def get_encoded_identity(agent_id: int) -> tuple[int, ...] | None:
            if agent_id not in encoded_identity_by_agent:
                try:
                    raw_identity = Agent.GetEncNameByID(agent_id)
                except Exception:
                    raw_identity = None
                encoded_identity_by_agent[agent_id] = normalize_vendor_encoded_identity(raw_identity)
            return encoded_identity_by_agent[agent_id]

        def get_model_id(agent_id: int) -> int:
            if agent_id not in model_id_by_agent:
                try:
                    model_id_by_agent[agent_id] = max(0, self._coerce_int()(Agent.GetModelID(agent_id), 0))
                except Exception:
                    model_id_by_agent[agent_id] = 0
            return model_id_by_agent[agent_id]

        def get_agent_xy(agent_id: int) -> tuple[float, float] | None:
            if agent_id not in xy_by_agent:
                try:
                    xy_by_agent[agent_id] = coerce_agent_xy(Agent.GetXY(agent_id))
                except Exception:
                    xy_by_agent[agent_id] = None
            return xy_by_agent[agent_id]

        candidates: list[tuple[float, str, tuple[float, float]]] = []
        failure_details: list[str] = []
        collision_details: list[str] = []
        for selector in selectors:
            expected_identity = normalize_vendor_encoded_identity(selector.encoded_identity)
            expected_xy = coerce_agent_xy(selector.expected_xy)
            expected_model_id = max(0, self._coerce_int()(selector.model_id, 0))
            try:
                coordinate_tolerance = float(selector.coordinate_tolerance)
            except (TypeError, ValueError):
                coordinate_tolerance = 0.0
            if (
                not expected_identity
                or expected_xy is None
                or expected_model_id <= 0
                or not math.isfinite(coordinate_tolerance)
                or coordinate_tolerance <= 0.0
            ):
                failure_details.append(f"{selector.label}: invalid selector definition")
                continue

            encoded_matches = [
                agent_id for agent_id in npc_agent_ids if get_encoded_identity(agent_id) == expected_identity
            ]
            if not encoded_matches:
                failure_details.append(f"{selector.label}: encoded identity mismatch")
                continue

            model_matches = [agent_id for agent_id in encoded_matches if get_model_id(agent_id) == expected_model_id]
            if not model_matches:
                failure_details.append(f"{selector.label}: model mismatch")
                continue

            complete_matches: list[tuple[int, tuple[float, float]]] = []
            for agent_id in model_matches:
                agent_xy = get_agent_xy(agent_id)
                if agent_xy is None or math.dist(agent_xy, expected_xy) > coordinate_tolerance:
                    continue
                complete_matches.append((agent_id, agent_xy))
            if not complete_matches:
                failure_details.append(f"{selector.label}: coordinate mismatch")
                continue
            if len(complete_matches) > 1:
                collision_detail = (
                    f"{selector.label}: unexpected multiple-match collision " f"({len(complete_matches)} NPCs)"
                )
                failure_details.append(collision_detail)
                collision_details.append(collision_detail)
                continue

            _agent_id, agent_xy = complete_matches[0]
            distance_from_player = math.dist(player_xy, agent_xy)
            if distance_from_player > self._search_max_dist:
                failure_details.append(f"{selector.label}: outside the service search range")
                continue
            candidates.append((distance_from_player, str(selector.label), agent_xy))

        if candidates:
            if collision_details:
                self._debug_log(
                    lambda: f"Map-specific {service_label} selector collision detail: "
                    f"{'; '.join(collision_details)}"
                )
            candidates.sort(key=lambda candidate: (candidate[0], candidate[1].casefold(), candidate[2]))
            return candidates[0][2]

        if log_failures:
            detail_text = "; ".join(failure_details) if failure_details else "no selector definitions"
            self._log_failure(
                self._module_name,
                lambda: f"Map-specific {service_label} selectors did not resolve on map {safe_map_id}: "
                f"{detail_text}.",
            )
        return None

    def record_scan(self, scan: LiveServiceRoleScan) -> None:
        """Retain safe role observations and maintain one bounded name-retry window."""

        self.lifecycle_active = True
        if scan.player_xy is None:
            return

        now = self._monotonic()
        fingerprint_changed = scan.candidate_fingerprint != self.candidate_fingerprint
        self.candidate_fingerprint = scan.candidate_fingerprint
        self.player_anchor = scan.player_xy
        self.observed_coords.update(scan.resolved_coords)
        self.pending_agent_ids = set(scan.pending_agent_ids)

        if scan.pending_agent_ids:
            if fingerprint_changed or scan.candidate_fingerprint != self.retry_fingerprint:
                self.retry_fingerprint = scan.candidate_fingerprint
                self.name_retry_deadline_at = now + self._name_retry_seconds
            elif self.name_retry_deadline_at > 0.0 and now >= self.name_retry_deadline_at:
                self.name_retry_deadline_at = 0.0
        else:
            self.retry_fingerprint = scan.candidate_fingerprint
            self.name_retry_deadline_at = 0.0

        retry_active = bool(self.pending_agent_ids and self.name_retry_deadline_at > now)
        self.next_poll_at = now + (self._name_retry_poll_seconds if retry_active else self._event_poll_seconds)

    def scan_live_roles(
        self,
        *,
        record_lifecycle: bool = True,
    ) -> LiveServiceRoleScan:
        snapshot = self._candidate_snapshot()
        scan = scan_live_service_roles(snapshot, role_aliases=self._role_aliases)
        if record_lifecycle:
            self.record_scan(scan)
        return scan

    def refresh_context_if_changed(
        self,
        *,
        force_context_refresh: bool,
    ) -> SupportedContext | None:
        previous_observations = dict(self.observed_coords)
        previous_pending_agent_ids = set(self.pending_agent_ids)
        role_scan = self.scan_live_roles()
        lifecycle_state_changed = bool(
            previous_observations != self.observed_coords or previous_pending_agent_ids != self.pending_agent_ids
        )
        if not force_context_refresh and not lifecycle_state_changed:
            return

        old_context = (
            self.cached_supported_context
            if self.cached_context_map_id == max(0, self._coerce_int()(self._get_map_id(), 0))
            else None
        )
        self.invalidate_context()
        refreshed_context = self.resolve_context(
            passive=True,
            log_context=False,
            role_scan_override=role_scan,
        )
        context_changed = bool(
            old_context is None or old_context[0] != refreshed_context[0] or old_context[2] != refreshed_context[2]
        )
        return refreshed_context if context_changed else None

    def poll_context_change(self) -> SupportedContext | None:
        if not self.lifecycle_active:
            return
        if not self._is_map_ready() or (not self._is_outpost() and not self._is_guild_hall()):
            return

        now = self._monotonic()
        if now < self.next_poll_at:
            return

        player_xy, _player_xy_source, _candidate_ids, fingerprint = self._candidate_snapshot()
        if player_xy is None:
            self.next_poll_at = now + self._event_poll_seconds
            return

        retry_active = bool(self.pending_agent_ids and self.name_retry_deadline_at > now)
        if self.name_retry_deadline_at > 0.0 and now >= self.name_retry_deadline_at:
            self.name_retry_deadline_at = 0.0
            retry_active = False

        candidate_changed = fingerprint != self.candidate_fingerprint
        moved_meaningfully = bool(
            self.player_anchor is not None
            and math.hypot(
                player_xy[0] - self.player_anchor[0],
                player_xy[1] - self.player_anchor[1],
            )
            >= self._meaningful_move_dist
        )
        if retry_active or candidate_changed or moved_meaningfully:
            return self.refresh_context_if_changed(
                force_context_refresh=bool(candidate_changed or moved_meaningfully),
            )

        self.next_poll_at = now + self._event_poll_seconds

    def resolve_service_role_coords(
        self,
        *,
        service_role: str,
        log_failures: bool,
        role_scan: LiveServiceRoleScan | None = None,
    ) -> tuple[float, float] | None:
        safe_service_role = str(service_role or "").strip()
        aliases = self._role_aliases.get(safe_service_role)
        if not aliases:
            if log_failures and safe_service_role:
                self._log_failure(
                    self._module_name,
                    lambda: f"Service-role fallback rejected unknown role {safe_service_role!r}.",
                )
            return None

        live_scan = role_scan if role_scan is not None else self.scan_live_roles()
        if live_scan.player_xy is None:
            if log_failures:
                self._log_failure(
                    self._module_name,
                    lambda: f"Could not resolve {aliases[0]} by localized role: {live_scan.player_xy_source}.",
                )
            return None

        resolved = live_scan.resolved_coords.get(safe_service_role)
        if resolved is None:
            resolved = self.observed_coords.get(safe_service_role)
        if resolved is not None:
            return resolved

        if log_failures:
            self._log_failure(
                self._module_name,
                lambda: f"Could not resolve {aliases[0]} by exact localized service role "
                f"within {self._search_max_dist:.0f}.",
            )
        return None

    def resolve_service_coords(
        self,
        *,
        map_id: int = 0,
        service_type: str = "",
        selector_name: str = "",
        model_id: int = 0,
        fallback_role: str = "",
        log_failures: bool = True,
        role_scan: LiveServiceRoleScan | None = None,
        resolve_role_fallback: bool = True,
    ) -> tuple[float, float] | None:
        safe_map_id = max(0, self._coerce_int()(map_id, 0))
        safe_service_type = str(service_type or "").strip()
        map_specific_selectors = self._map_service_selectors.get(safe_map_id, {}).get(
            safe_service_type,
            (),
        )
        if map_specific_selectors:
            return self.resolve_map_specific_service_coords(
                map_id=safe_map_id,
                service_type=safe_service_type,
                selectors=map_specific_selectors,
                log_failures=log_failures,
            )

        safe_selector_name = str(selector_name or "").strip()
        safe_model_id = max(0, self._coerce_int()(model_id, 0))
        safe_fallback_role = str(fallback_role or "").strip()
        has_role_fallback = safe_fallback_role in self._role_aliases
        has_authoritative_selector = bool(
            safe_selector_name and self._selector_authoritative("npc", safe_selector_name)
        )
        if has_authoritative_selector:
            selector_coords = self._resolve_agent_step(
                {"npc": safe_selector_name},
                self._module_name,
                0,
                "npc",
                self._search_max_dist,
                bool(log_failures and safe_model_id <= 0 and not has_role_fallback),
            )
            if selector_coords is not None:
                return selector_coords
            if safe_model_id <= 0 and not has_role_fallback:
                return None
        if safe_model_id > 0:
            model_coords = self._resolve_agent_step(
                {"model_id": safe_model_id},
                self._module_name,
                0,
                "npc",
                self._search_max_dist,
                bool(log_failures and not has_authoritative_selector and not has_role_fallback),
            )
            if model_coords is not None:
                return model_coords
            if has_authoritative_selector and log_failures and not has_role_fallback:
                service_label = self._merchant_labels.get(safe_service_type, safe_service_type or "service")
                self._log_failure(
                    self._module_name,
                    lambda: f"Could not resolve {service_label} using encoded selector {safe_selector_name!r} "
                    f"or map-scoped model ID {safe_model_id}.",
                )
            if not has_role_fallback:
                return None
        if has_role_fallback and resolve_role_fallback:
            return self.resolve_service_role_coords(
                service_role=safe_fallback_role,
                log_failures=log_failures,
                role_scan=role_scan,
            )
        if not safe_selector_name:
            return None
        if log_failures:
            self._log_failure(
                self._module_name,
                lambda: (
                    f"Service selector {safe_selector_name!r} "
                    "has no encoded name or model ID; resolution was skipped."
                ),
            )
        return None

    def get_diagnostics(self) -> str:
        """Read positional counts without requesting or decoding any NPC names."""

        try:
            from Py4GWCoreLib import Agent
            from Py4GWCoreLib import AgentArray

            player_xy, source = self._player_origin(Agent)
            npc_ids = list(AgentArray.GetNPCMinipetArray() or [])
            if player_xy is None:
                return f"player=unavailable source={source} total_npcs={len(npc_ids)} in_range_npcs=unavailable"
            in_range_ids = AgentArray.Filter.ByDistance(
                npc_ids,
                player_xy,
                self._search_max_dist,
            )
            return (
                f"player=({player_xy[0]:.1f}, {player_xy[1]:.1f}) source={source} "
                f"total_npcs={len(npc_ids)} in_range_npcs={len(in_range_ids)}"
            )
        except Exception as exc:
            return f"player/NPC diagnostics unavailable: {type(exc).__name__}"

    def resolve_storage_access_coords(self) -> tuple[float, float] | None:
        if not self._is_map_ready():
            return None
        if not self._is_outpost() and not self._is_guild_hall():
            return None

        lookup_steps: list[tuple[dict[str, object], str]] = [
            ({"target": self._xunlai_agent_name, "exact_name": True}, "npc"),
            ({"target": self._xunlai_chest_name, "exact_name": True}, "gadget"),
        ]
        lookup_steps.extend(({"model_id": model_id}, "npc") for model_id in self._xunlai_agent_model_ids)
        lookup_steps.append(({"model_id": self._xunlai_chest_model_id}, "gadget"))

        for step, agent_kind in lookup_steps:
            coords = self._resolve_agent_step(
                step,
                self._module_name,
                0,
                agent_kind,
                self._search_max_dist,
                False,
            )
            if coords is not None:
                return coords
        return None

    def has_local_storage_access(self) -> bool:
        if self._storage_is_open():
            return True
        return self.resolve_storage_access_coords() is not None

    def resolve_context(
        self,
        *,
        passive: bool = False,
        log_context: bool = True,
        role_scan_override: LiveServiceRoleScan | None = None,
    ) -> SupportedContext:
        current_map_id = int(self._get_map_id() or 0)
        if self.cached_supported_context is not None and self.cached_context_map_id == current_map_id:
            return self.cached_supported_context

        coords: dict[str, tuple[float, float] | None] = {
            self._merchant_type: None,
            self._materials_type: None,
            self._rune_type: None,
            self._scroll_type: None,
            self._rare_materials_type: None,
            self._consumable_type: (3592.99, 78.78) if current_map_id == self._embark_map_id else None,
        }

        if not self._is_map_ready():
            self.cached_context_map_id = current_map_id
            self.cached_supported_context = (False, "Map is not ready.", coords)
            return self.cached_supported_context
        if not self._is_outpost() and not self._is_guild_hall():
            self.cached_context_map_id = current_map_id
            self.cached_supported_context = (False, "Current map is not an outpost or Guild Hall.", coords)
            return self.cached_supported_context

        map_id = current_map_id
        selector_data = self._supported_selectors.get(map_id) or {}
        model_overrides = self._service_model_ids.get(map_id, {})

        selector_keys = {
            self._merchant_type: "merchant",
            self._materials_type: "materials",
            self._rare_materials_type: "rare_materials",
        }

        for merchant_type, selector_key in selector_keys.items():
            map_selector_name = str(selector_data.get(selector_key) or "").strip()
            selector_name = map_selector_name or self._default_selectors.get(selector_key)
            model_id = 0 if map_selector_name else max(0, self._coerce_int()(model_overrides.get(merchant_type, 0), 0))
            coords[merchant_type] = self.resolve_service_coords(
                map_id=map_id,
                service_type=merchant_type,
                selector_name=str(selector_name or ""),
                model_id=model_id,
                fallback_role=merchant_type,
                log_failures=not passive,
                resolve_role_fallback=False,
            )

        coords[self._rune_type] = self.resolve_rune_trader_coords(
            map_id,
            log_failures=not passive,
            resolve_role_fallback=False,
        )
        coords[self._scroll_type] = self.resolve_scroll_trader_coords(
            map_id,
            selector_data,
            log_failures=bool(not passive and self._scroll_policy()),
            resolve_role_fallback=False,
        )

        fallback_roles = {
            self._merchant_type: self._merchant_type,
            self._materials_type: self._materials_type,
            self._rare_materials_type: self._rare_materials_type,
            self._rune_type: self._rune_type,
            self._scroll_type: self.get_scroll_trader_lookup()[1],
        }
        generic_fallback_roles = {
            service_type: fallback_role
            for service_type, fallback_role in fallback_roles.items()
            if coords[service_type] is None and not self._map_service_selectors.get(map_id, {}).get(service_type)
        }
        if generic_fallback_roles:
            role_scan = role_scan_override if role_scan_override is not None else self.scan_live_roles()
            for service_type, fallback_role in generic_fallback_roles.items():
                coords[service_type] = self.resolve_service_role_coords(
                    service_role=fallback_role,
                    log_failures=bool(not passive and (service_type != self._scroll_type or self._scroll_policy())),
                    role_scan=role_scan,
                )

        resolved_services = [
            self._merchant_labels.get(service_type, service_type)
            for service_type, service_coords in coords.items()
            if service_coords is not None
        ]
        unresolved_services = [
            self._merchant_labels.get(service_type, service_type)
            for service_type, service_coords in coords.items()
            if service_coords is None
        ]
        resolved_count = len(resolved_services)
        location_label = "Guild Hall" if self._is_guild_hall() else "Outpost"
        has_merchant_rules_map_selectors = bool(self._map_service_selectors.get(map_id))
        selector_mode_label = (
            "verified trader locations"
            if has_merchant_rules_map_selectors
            else (
                "location-specific trader information"
                if map_id in self._supported_selectors
                else "default trader information"
            )
        )
        base_message = (
            f"{location_label} ready: {self._get_map_name(map_id)} ({map_id}). " f"Using {selector_mode_label}."
        )
        supported_map = resolved_count > 0
        resolved_text = ", ".join(resolved_services) if resolved_services else "none"
        unresolved_text = ", ".join(unresolved_services) if unresolved_services else "none"
        reason = f"{base_message} Resolved services: {resolved_text}. Unresolved services: {unresolved_text}."

        resolved_context = (supported_map, reason, coords)
        self.cached_context_map_id = current_map_id
        self.cached_supported_context = resolved_context
        selector_mode = (
            "merchant_rules_specific"
            if has_merchant_rules_map_selectors
            else "specific" if map_id in self._supported_selectors else "generic"
        )
        if log_context:
            self._debug_log(
                lambda: f"Context resolved: map={self._get_map_name(map_id)} ({map_id}) selector_mode={selector_mode} "
                f"supported={supported_map} {self.get_diagnostics()} "
                f"resolved_services={resolved_text} unresolved_services={unresolved_text} "
                f"merchant={self._format_coords()(coords[self._merchant_type])} "
                f"materials={self._format_coords()(coords[self._materials_type])} "
                f"rune={self._format_coords()(coords[self._rune_type])} "
                f"scroll={self._format_coords()(coords[self._scroll_type])} "
                f"rare={self._format_coords()(coords[self._rare_materials_type])} "
                f"consumable={self._format_coords()(coords[self._consumable_type])}"
            )
            if not supported_map or resolved_count < len(coords):
                self._debug_log(lambda: f"Context detail: {reason}")
        return self.cached_supported_context
