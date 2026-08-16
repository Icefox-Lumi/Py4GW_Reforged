"""The Factory's store -- filters and filter sets, global.

**Definitions are shared, selections are local.** Filters and filter sets are definitions, so they live
at **global** scope and a filter written once is available to every account. Which filter set a feature
runs is a selection and belongs to that feature's per-account settings.

``JsonFactory`` is correct here: these are user-generated, nested, variable-length collections. (The
*catalogs* are the opposite -- shipped reference data, package source, never in the JSON store.)

Ids are short sequential numbers. Not uuids: the pool is a single global store where sequential ids
cannot collide, and the system is a multi-account setup driven by one person, so two clients minting
an id in the same instant is not a real scenario. A readable id also keeps the stored JSON
hand-inspectable.
"""

from .model import Filter
from .model import FilterSet

_DOC = "Widgets/System/LootFilterFactory.json"

#: The document keys. "profiles" is the pre-contract legacy key; reads fall
#: back to it, writes always use "filter_sets".
_FILTERS_KEY = "filters"
_FILTER_SETS_KEY = "filter_sets"
_LEGACY_FILTER_SETS_KEY = "profiles"


def _doc():
    """The global document. Imported lazily so this module stays import-safe offline."""
    try:
        from Py4GWCoreLib.py4gwcorelib_src.JsonFactory import JsonFactory

        return JsonFactory(_DOC, "global")
    except Exception:
        return None


# ---------------------------------------------------------------- filters


#: The pre-contract per-filter outcome fields, still present in the document
#: until Recolor & Beacons' one-time import is verified live. `Filter` itself
#: no longer carries them; these helpers are the migration bridge.
_LEGACY_MARK_KEYS = ("mark_recolor", "mark_color", "mark_blank", "mark_beacon", "mark_preset")


def load_filters() -> list[Filter]:
    doc = _doc()
    if doc is None:
        return []
    raw = doc.get_json(_FILTERS_KEY, [])
    if not isinstance(raw, list):
        return []
    out: list[Filter] = []
    for entry in raw:
        if isinstance(entry, dict):
            try:
                out.append(Filter.from_dict(entry))
            except Exception:
                continue
    return out


def legacy_mark_entries() -> dict[str, dict]:
    """Raw ``filter_id -> {mark_* fields}`` for entries that mark something.

    Reads the RAW document -- ``Filter`` no longer carries outcomes, so parsed
    filters cannot see these. This feeds Recolor & Beacons' one-time, silent
    import into its own account store; removed with the preserve-on-save shim
    once that import is verified live.
    """
    doc = _doc()
    if doc is None:
        return {}
    raw = doc.get_json(_FILTERS_KEY, [])
    if not isinstance(raw, list):
        return {}
    out: dict[str, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        filter_id = str(entry.get("id", ""))
        if not filter_id:
            continue
        marks = {key: entry[key] for key in _LEGACY_MARK_KEYS if key in entry}
        if not any(marks.get(key) for key in ("mark_recolor", "mark_blank", "mark_beacon")):
            continue                    # nothing to import: not an outcome
        out[filter_id] = marks
    return out


def save_filters(filters) -> None:
    doc = _doc()
    if doc is None:
        return
    # Migration shim: merge the legacy outcome fields back by id, so a factory
    # save never strips data an account has not imported yet. Gone with
    # `legacy_mark_entries` after the live gate.
    legacy = legacy_mark_entries()
    doc.set_json(_FILTERS_KEY, [dict(f.to_dict(), **legacy.get(f.id, {})) for f in filters])


def next_filter_id(filters) -> str:
    """The next short sequential id, unique within the single global pool."""
    taken = {f.id for f in filters}
    index = 1
    while "filter_%d" % index in taken:
        index += 1
    return "filter_%d" % index


def filter_by_id(filters, filter_id: str) -> Filter | None:
    for f in filters:
        if f.id == filter_id:
            return f
    return None


# ---------------------------------------------------------------- filter sets


def load_filter_sets() -> list[FilterSet]:
    doc = _doc()
    if doc is None:
        return []
    raw = doc.get_json(_FILTER_SETS_KEY, None)
    if not isinstance(raw, list):
        raw = doc.get_json(_LEGACY_FILTER_SETS_KEY, [])
    if not isinstance(raw, list):
        return []
    out: list[FilterSet] = []
    for entry in raw:
        if isinstance(entry, dict):
            try:
                out.append(FilterSet.from_dict(entry))
            except Exception:
                continue
    return out


def save_filter_sets(filter_sets) -> None:
    doc = _doc()
    if doc is not None:
        doc.set_json(_FILTER_SETS_KEY, [fs.to_dict() for fs in filter_sets])


def next_filter_set_id(filter_sets) -> str:
    """The next short sequential id, unique within the single global pool."""
    taken = {fs.id for fs in filter_sets}
    index = 1
    while "set_%d" % index in taken:
        index += 1
    return "set_%d" % index


def filter_set_by_name(filter_sets, name: str) -> FilterSet | None:
    for fs in filter_sets:
        if fs.name == name:
            return fs
    return None


def filter_set_by_id(filter_sets, filter_set_id: str) -> FilterSet | None:
    for fs in filter_sets:
        if fs.id == filter_set_id:
            return fs
    return None


def resolve_filter_set_selection(stored: str, filter_sets) -> tuple[str, str]:
    """Map one feature's stored selection to a live filter set id.

    Returns ``(resolved_id, message)``. A stored **id** wins untouched; a legacy
    **name** migrates to the matching set's id (rename-safe, ids are stable);
    anything that matches no set resolves to ``""`` (none) with a message for
    the console. Pure -- callers decide what to persist and log.
    """
    if not stored:
        return "", ""
    if filter_set_by_id(filter_sets, stored) is not None:
        return stored, ""
    by_name = filter_set_by_name(filter_sets, stored)
    if by_name is not None:
        return by_name.id, ("selected filter set '%s' migrated to its id '%s'" % (stored, by_name.id))
    return "", ("selected filter set '%s' no longer exists - falling back to none" % stored)


def filters_in_set(filters, filter_set: FilterSet | None) -> list[Filter]:
    """The filters a filter set names, in the set's order. Unknown ids are skipped."""
    if filter_set is None:
        return []
    index = {f.id: f for f in filters}
    return [index[i] for i in filter_set.filter_ids if i in index]
