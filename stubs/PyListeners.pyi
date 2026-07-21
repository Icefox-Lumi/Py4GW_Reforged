# PyListeners stub - Reforged Native surface.
# Exact counterpart of src/listeners/listeners_bindings.cpp.
#
# Runtime toggles for the native game-event listeners. A listener is a named unit
# over a set of StoC packet callbacks whose only job is to be switched on or off:
# enable installs the callbacks, disable removes them (both idempotent), so a
# disabled listener has zero callback overhead. Registered names currently include
# "merchant" and "agent_events" (see include/listeners/listeners.h).
#
# Every toggle is addressed by name and returns False when the name is unknown.

from typing import List

def list() -> List[str]:
    """List the names of all toggleable listeners."""
    ...

def enable(name: str) -> bool:
    """Enable a listener by name. False if the name is unknown."""
    ...

def disable(name: str) -> bool:
    """Disable a listener by name. False if the name is unknown."""
    ...

def toggle(name: str) -> bool:
    """Toggle a listener by name. False if the name is unknown."""
    ...

def set_enabled(name: str, enabled: bool) -> bool:
    """Set a listener's enabled state. False if the name is unknown."""
    ...

def is_enabled(name: str) -> bool:
    """Check whether a listener is enabled. False if the name is unknown."""
    ...
