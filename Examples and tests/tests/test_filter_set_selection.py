"""Offline fixture for filter-set selection integrity (filter-structure contract, T3).

Loads the factory model/store straight from source (no injected client needed) and drives
``resolve_filter_set_selection`` plus the id lookups: a stored id wins untouched, a legacy
NAME migrates to the matching set's id once, anything matching no set falls back to none
with a console message, renames are safe because ids are stable, and deletes fall back.

Run:  python "Examples and tests/tests/test_filter_set_selection.py"
Exit code 1 on any failure.
"""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
FACTORY_DIR = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings" / "loot_filter_factory"


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, "could not build a module spec for %s" % path
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "_lff"
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_pkg = types.ModuleType("_lff")
_pkg.__path__ = []
sys.modules["_lff"] = _pkg
model = _load_module("_lff.model", FACTORY_DIR / "model.py")
store = _load_module("_lff.store", FACTORY_DIR / "store.py")

Filter = model.Filter
FilterSet = model.FilterSet

MELEE = FilterSet(id="set_1", name="Melee", filter_ids=("filter_2", "filter_1", "filter_9"))
CASTER = FilterSet(id="set_2", name="Caster", filter_ids=("filter_1",))
RENAMED = FilterSet(id="set_1", name="Melee Reborn", filter_ids=("filter_2", "filter_1", "filter_9"))
POOL = [MELEE, CASTER]

failures = 0


def check(label: str, expected, observed) -> None:
    global failures
    ok = expected == observed
    if not ok:
        failures += 1
    print("[%s] %s" % ("PASS" if ok else "FAIL", label))
    if not ok:
        print("      expected: %r" % (expected,))
        print("      observed: %r" % (observed,))


# 1. A stored id wins untouched -- idempotent, no message.
check("stored id resolves to itself", ("set_1", ""),
      store.resolve_filter_set_selection("set_1", POOL))

# 2. A legacy NAME migrates to the matching id once, with a console message.
migrated_id, message = store.resolve_filter_set_selection("Melee", POOL)
check("legacy name migrates to the id", ("set_1",
      "selected filter set 'Melee' migrated to its id 'set_1'"), (migrated_id, message))
# ...and the migrated value is then an id: feeding it back is a no-op (import idempotency).
check("migrated selection is stable on re-load", ("set_1", ""),
      store.resolve_filter_set_selection(migrated_id, POOL))

# 3. A value matching nothing (deleted set, typo'd name) falls back to none with a message.
check("deleted selection falls back to none", ("",
      "selected filter set 'gone' no longer exists - falling back to none"),
      store.resolve_filter_set_selection("gone", POOL))

# 4. No selection is a no-op.
check("empty selection stays empty", ("", ""), store.resolve_filter_set_selection("", POOL))

# 5. Rename integrity: ids are stable, so a renamed set keeps satisfying its stored id.
check("rename keeps the id valid", ("set_1", ""),
      store.resolve_filter_set_selection("set_1", [RENAMED, CASTER]))

# 6. Delete integrity: the pool without the set no longer resolves the id.
check("delete invalidates the stored id", ("",
      "selected filter set 'set_1' no longer exists - falling back to none"),
      store.resolve_filter_set_selection("set_1", [CASTER]))

# 7. The id lookup itself.
check("filter_set_by_id finds the set", MELEE, store.filter_set_by_id(POOL, "set_1"))
check("filter_set_by_id misses cleanly", None, store.filter_set_by_id(POOL, "set_99"))

# 8. filters_in_set keeps the set's order and skips unknown ids -- the flow both features
#    resolve selections through.
check("filters_in_set preserves order and skips unknown ids",
      [Filter(id="filter_2"), Filter(id="filter_1")],
      store.filters_in_set([Filter(id="filter_1"), Filter(id="filter_2")], MELEE))

print("=" * 68)
print("%d case(s) failed" % failures)
sys.exit(1 if failures else 0)
