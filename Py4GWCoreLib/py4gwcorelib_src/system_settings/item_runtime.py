"""Shared lifecycle barrier for System Settings item access.

Inventory handles and native item queues are volatile during an instance
transition. This module deliberately reads only the established map boundary
until that boundary has remained valid long enough for item handlers to run.
"""

import time
from collections.abc import Callable


MapContext = tuple[int, bool, bool]
ArrivalDelay = float | Callable[[MapContext], float]


class StableMapGate:
    """Admit item work only after the normal map boundary has settled."""

    def __init__(self) -> None:
        self._observed_context: MapContext | None = None
        self._observed_at = 0.0

    def reset(self) -> None:
        self._observed_context = None
        self._observed_at = 0.0

    def context(self, arrival_delay_seconds: ArrivalDelay = 0.0) -> MapContext | None:
        """Return a valid settled map context, or ``None`` without touching inventory.

        The caller owns the optional arrival delay.  The runtime always enforces
        the established ``Map`` and ``Checks.Map`` predicates first; it never
        hard-codes a guess about how long an instance needs to settle.
        """
        try:
            from Py4GWCoreLib.Map import Map
            from Py4GWCoreLib.routines_src.Checks import Checks

            if (
                not Map.IsMapReady()
                or Map.IsMapLoading()
                or not Checks.Map.MapValid()
            ):
                self.reset()
                return None
            map_id = int(Map.GetMapID() or 0)
            if map_id <= 0:
                self.reset()
                return None
            current = map_id, bool(Map.IsExplorable()), bool(Map.IsOutpost())
        except Exception:
            self.reset()
            return None

        now = time.monotonic()
        try:
            delay_value = arrival_delay_seconds(current) if callable(arrival_delay_seconds) else arrival_delay_seconds
            delay = max(0.0, float(delay_value))
        except (TypeError, ValueError):
            delay = 0.0
        if current != self._observed_context:
            self._observed_context = current
            self._observed_at = now
        if now - self._observed_at < delay:
            return None
        return current
