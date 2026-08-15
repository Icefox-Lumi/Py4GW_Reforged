"""Recolor & Beacons persistence -- flat, per account, and only the PERSISTED instance is written.

Everything here is a handful of flat values, so ``Settings`` is the whole story: there is no
structured collection to keep. The filters and filter sets belong to the Loot Filter Factory's
global store, and beacon presets to the Beacons module's -- neither is duplicated here.

**The outcome IS here.** ``Widgets/System/RecolorOutcomes.json`` (account scope) maps
``filter_id -> {recolor, color, blank, beacon, preset}``: what one filter marks for THIS
account. A filter is criteria only and carries no outcome.

**The live instance is never written.** There is no code path from it to a writer.
"""

from .model import MarkConfig
from .model import MarkOutcome

_INI = "Widgets/System/RecolorBeacons.ini"
_OUTCOMES_DOC = "Widgets/System/RecolorOutcomes.json"


def _settings():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.Settings import Settings

        return Settings(_INI, "account")
    except Exception:
        return None


def _log(message: str) -> None:
    try:
        from Py4GWCoreLib.Py4GWcorelib import ConsoleLog

        ConsoleLog("Recolor & Beacons", message)
    except Exception:
        pass


def load() -> MarkConfig:
    """The persisted configuration. Live is seeded from a copy of this."""
    config = MarkConfig()
    settings = _settings()
    if settings is None:
        return config
    config.enabled = settings.get_bool("general", "enabled", False)
    # The persisted key has always been ``general/profile`` and it stays: only the VALUE
    # moved from a filter-set NAME to its id. Names are still read and adopted by load().
    config.filter_set_id = settings.get_str("general", "profile", "")
    config.blank_unassigned = settings.get_bool("general", "blank_unassigned", False)
    config.max_beacons = settings.get_int("beacons", "max_beacons", 8)
    config.beacon_distance = float(settings.get_int("beacons", "beacon_distance", 2500))
    config.cheap_distant = settings.get_bool("beacons", "cheap_distant", True)
    config.cheap_distance = float(settings.get_int("beacons", "cheap_distance", 1200))
    _resolve_filter_set(config, settings)
    return config


def _resolve_filter_set(config: MarkConfig, settings) -> None:
    """Adopt a legacy filter-set NAME into its id, in place, once and silently.

    Same scheme as the loot store's twin: the key does not move, the value
    becomes the set's id (written back once, idempotent), and a value matching
    no set falls back to none in memory without rewriting the document.
    """
    if not config.filter_set_id:
        return
    from ..loot_filter_factory import store as factory_store

    stored = config.filter_set_id
    selection, message = factory_store.resolve_filter_set_selection(
        stored, factory_store.load_filter_sets())
    config.filter_set_id = selection
    if message:
        _log(message)
    if selection and selection != stored:
        settings.set("general", "profile", selection)


def save(config: MarkConfig) -> None:
    """Persist. Only ever called with the PERSISTED instance -- never with live."""
    settings = _settings()
    if settings is None:
        return
    settings.set("general", "enabled", bool(config.enabled))
    settings.set("general", "profile", str(config.filter_set_id))
    settings.set("general", "blank_unassigned", bool(config.blank_unassigned))
    settings.set("beacons", "max_beacons", int(config.max_beacons))
    settings.set("beacons", "beacon_distance", int(config.beacon_distance))
    settings.set("beacons", "cheap_distant", bool(config.cheap_distant))
    settings.set("beacons", "cheap_distance", int(config.cheap_distance))


# ---------------------------------------------------------------- outcomes (filter_id -> outcome)


def _outcomes_doc():
    try:
        from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

        return JsonFactory(_OUTCOMES_DOC, "account")
    except Exception:
        return None


def load_outcomes() -> dict[str, MarkOutcome]:
    """Every stored outcome for this account, plus the silent one-time legacy import.

    The pre-contract outcomes lived on the global filters (``mark_*`` fields). The
    first load copies them into this account's store, keyed by filter id -- idempotent
    by state: ids already present here are NEVER overwritten, so nothing a user
    configured, or deliberately cleared, can be resurrected. The legacy fields stay
    readable in the factory document until the live gate passes.
    """
    doc = _outcomes_doc()
    if doc is None:
        return {}
    raw = doc.get_json("outcomes", {}) or {}
    if not isinstance(raw, dict):
        return {}
    outcomes: dict[str, MarkOutcome] = {}
    for filter_id, entry in raw.items():
        if isinstance(entry, dict):
            outcomes[str(filter_id)] = MarkOutcome.from_dict(entry)
    _import_legacy_outcomes(doc, outcomes)
    return outcomes


def _import_legacy_outcomes(doc, outcomes: dict[str, MarkOutcome]) -> None:
    from ..loot_filter_factory import store as factory_store

    legacy = factory_store.legacy_mark_entries()
    if not legacy:
        return
    imported = 0
    for filter_id, marks in legacy.items():
        if filter_id in outcomes:
            continue                    # this account already decided: never overwrite
        # The legacy keys are mark_recolor/mark_color/...; drop the prefix for MarkOutcome.
        stripped = {key[len("mark_"):]: value for key, value in marks.items()}
        outcomes[filter_id] = MarkOutcome.from_dict(stripped)
        imported += 1
    if imported:
        doc.set_json("outcomes", {k: v.to_dict() for k, v in outcomes.items()})
        _log("imported %d legacy outcome(s) from the factory into this account's store" % imported)


def save_outcomes(outcomes: dict[str, MarkOutcome]) -> None:
    """Persist the whole outcome map. Only ever called through the settings UI."""
    doc = _outcomes_doc()
    if doc is not None:
        doc.set_json("outcomes", {k: v.to_dict() for k, v in outcomes.items()})
