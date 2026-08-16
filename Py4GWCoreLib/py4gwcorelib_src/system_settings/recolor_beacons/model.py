"""The marking feature's configuration -- the same class twice: persisted and live.

Everything a script can touch is doubled. The persisted copy is the user's, written only by the user
through System Settings; the live copy is what runs, and a script writes only that. There is no path
from live to a writer, so **a script never persists**. A restart is a reset by construction.

**The outcome is here.** ``MarkOutcome`` is what one filter marks for ONE account
(``filter_id -> outcome`` in this feature's own store). The filter itself carries
criteria only. What also lives here is the feature's settings: the master switch,
the active filter set, and the beacon budget.

**The budget is the user's, not ours.** The class imposes no hidden cap; it gives the controls --
maximum live beacons, a distance limit, and a cheap stand-in for distant ones -- and the user decides
the trade-off.
"""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import fields as dataclass_fields


@dataclass
class MarkOutcome:
    """What one filter marks, for ONE account. A filter carries no outcome of its own.

    ``recolor`` and ``beacon`` are independent -- a filter may do either, both, or neither.
    An outcome with everything off marks nothing and is simply a stored "cleared" state.
    """

    #: Recolour the item's label.
    recolor: bool = False
    #: The label colour, RGBA 0..1.
    color: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    #: **BLANK** -- a named feature, not a trick. A fully transparent colour removes the item
    #: from the on-screen labels entirely. Visual only: blanking never changes what is wanted.
    blank: bool = False
    #: Put a beacon over it.
    beacon: bool = False
    #: Which beacon preset, by name. Empty = the base beacon.
    preset: str = ""

    def marks(self) -> bool:
        """Whether this outcome does anything at all."""
        return bool(self.recolor or self.blank or self.beacon)

    def to_dict(self) -> dict:
        return {"recolor": self.recolor, "color": list(self.color), "blank": self.blank,
                "beacon": self.beacon, "preset": self.preset}

    @staticmethod
    def from_dict(raw: dict) -> "MarkOutcome":
        stored_color = raw.get("color") or (1.0, 1.0, 1.0, 1.0)
        try:
            channels = tuple(float(c) for c in stored_color)[:4]
        except (TypeError, ValueError):
            channels = (1.0, 1.0, 1.0, 1.0)
        if len(channels) != 4:
            channels = (1.0, 1.0, 1.0, 1.0)
        return MarkOutcome(
            recolor=bool(raw.get("recolor", False)),
            color=(channels[0], channels[1], channels[2], channels[3]),
            blank=bool(raw.get("blank", False)),
            beacon=bool(raw.get("beacon", False)),
            preset=str(raw.get("preset", "")),
        )


@dataclass
class MarkConfig:
    """Per account. Two instances exist: what the user saved, and what is running."""

    #: The feature's own master switch. Symmetric with Loot Filters -- each feature is standalone,
    #: so neither can be switched off from the other's section.
    enabled: bool = False
    #: The active marking filter set, by its stable id. One at a time, and independent of the
    #: loot feature's choice. A legacy selection stored as a NAME migrates to the id once, at load.
    filter_set_id: str = ""

    # -- recolour --
    #: Blank loot that is assigned to somebody else. A stated use of BLANK: it is not ours to take,
    #: so it does not need to be on screen. Visual only -- it changes nothing about what is wanted.
    blank_unassigned: bool = False

    # -- the beacon budget, all the user's to set --
    #: How many beacons may be alive at once. Nearest first when there are more.
    max_beacons: int = 8
    #: Beacons only within this range.
    beacon_distance: float = 2500.0
    #: Beyond ``cheap_distance``, draw a stripped-down stand-in instead of the full effect.
    cheap_distant: bool = True
    cheap_distance: float = 1200.0

    def copy(self) -> "MarkConfig":
        return MarkConfig(**{f.name: getattr(self, f.name) for f in dataclass_fields(self)})

    def differs_from(self, other: "MarkConfig") -> bool:
        return any(getattr(self, f.name) != getattr(other, f.name) for f in dataclass_fields(self))

    def diff(self, other: "MarkConfig") -> list[str]:
        """What a script changed, in words -- this feeds the live-state label and its detail view."""
        labels = {
            "enabled": "Marking", "filter_set_id": "Filter set", "blank_unassigned": "Blank unassigned loot",
            "max_beacons": "Max beacons", "beacon_distance": "Beacon distance",
            "cheap_distant": "Cheap distant beacons", "cheap_distance": "Cheap beacon distance",
        }
        out: list[str] = []
        for spec in dataclass_fields(self):
            mine, theirs = getattr(self, spec.name), getattr(other, spec.name)
            if mine != theirs:
                out.append("%s: %s -> %s" % (labels.get(spec.name, spec.name),
                                             theirs if theirs != "" else "(none)",
                                             mine if mine != "" else "(none)"))
        return out