"""Offline fixture for the silent, least-commitment settings migration (filter-structure contract).

The persisted surface does NOT move: the selection still lives under the INI key
``general/profile``, in the same documents, at the same scopes. Only the VALUE changed --
from a filter-set NAME to its id. This fixture drives the REAL feature stores against
in-memory fakes of Settings/JsonFactory/ConsoleLog and proves:

- a legacy NAME is adopted into the set's id once, written back to the SAME key, silently
  (the value being an id is its own migration state; there is no marker);
- after adoption the selection survives a rename, because ids are stable;
- a value matching no set falls back to none in memory and the document is NOT
  rewritten, so a transiently unreadable filter pool cannot destroy a valid selection;
- a user clearing the selection overwrites the same key, so nothing resurrects it;
- the factory document's legacy ``profiles`` key remains a plain read fallback.

Run:  python "Examples and tests/tests/test_settings_migration.py"
Exit code 1 on any failure.
"""

import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
SS_DIR = ROOT / "Py4GWCoreLib" / "py4gwcorelib_src" / "system_settings"

_LOOT_INI = "Widgets/System/LootFilters.ini"
_RECOLOR_INI = "Widgets/System/RecolorBeacons.ini"
_FACTORY_DOC = "Widgets/System/LootFilterFactory.json"

MELEE_JSON = [{"id": "set_1", "name": "Melee", "filter_ids": []}]
RENAMED_JSON = [{"id": "set_1", "name": "Melee Reborn", "filter_ids": []}]

# -- a fake Py4GWCoreLib package chain, so the real stores load offline ----------


def _fake_package(name: str) -> types.ModuleType:
    package = types.ModuleType(name)
    package.__path__ = []
    sys.modules[name] = package
    return package


for _name in (
    "Py4GWCoreLib",
    "Py4GWCoreLib.py4gwcorelib_src",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters",
    "Py4GWCoreLib.py4gwcorelib_src.system_settings.recolor_beacons",
):
    _fake_package(_name)


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec is not None and spec.loader is not None, "could not build a module spec for %s" % path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.model",
      SS_DIR / "loot_filter_factory" / "model.py")
factory_store = _load("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filter_factory.store",
                      SS_DIR / "loot_filter_factory" / "store.py")
_load("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters.nicholas",
      SS_DIR / "loot_filters" / "nicholas.py")
_load("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters.model",
      SS_DIR / "loot_filters" / "model.py")
loot_store = _load("Py4GWCoreLib.py4gwcorelib_src.system_settings.loot_filters.store",
                   SS_DIR / "loot_filters" / "store.py")
_load("Py4GWCoreLib.py4gwcorelib_src.system_settings.recolor_beacons.model",
      SS_DIR / "recolor_beacons" / "model.py")
recolor_store = _load("Py4GWCoreLib.py4gwcorelib_src.system_settings.recolor_beacons.store",
                      SS_DIR / "recolor_beacons" / "store.py")

# -- in-memory Settings / JsonFactory / ConsoleLog -------------------------------


class FakeSettings:
    """Enough of the Settings surface for the stores; one dict per (path, scope)."""

    _DOCS: dict = {}

    def __init__(self, path: str, scope: str):
        self._data = FakeSettings._DOCS.setdefault((str(path), str(scope)), {})

    @staticmethod
    def _k(section: str, key: str) -> str:
        return "%s|%s" % (section, key)

    def get_str(self, section: str, key: str, default: str = "") -> str:
        value = self._data.get(self._k(section, key))
        return str(value) if value is not None else str(default)

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        value = self._data.get(self._k(section, key))
        if value is None:
            return bool(default)
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        value = self._data.get(self._k(section, key))
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def set(self, section: str, key: str, value) -> None:
        self._data[self._k(section, key)] = value

    @staticmethod
    def doc(path: str, scope: str) -> dict:
        return FakeSettings._DOCS.setdefault((str(path), str(scope)), {})

    @staticmethod
    def reset() -> None:
        FakeSettings._DOCS.clear()


class FakeJsonFactory:
    _DOCS: dict = {}

    def __init__(self, path: str, scope: str):
        self._data = FakeJsonFactory._DOCS.setdefault((str(path), str(scope)), {})

    def get_json(self, key: str, default=None):
        return self._data.get(key, default)

    def set_json(self, key: str, value) -> None:
        self._data[key] = value

    @staticmethod
    def doc(path: str, scope: str) -> dict:
        return FakeJsonFactory._DOCS.setdefault((str(path), str(scope)), {})

    @staticmethod
    def reset() -> None:
        FakeJsonFactory._DOCS.clear()


_CONSOLE: list = []


def _console_log(tag: str, message: str) -> None:
    _CONSOLE.append((tag, message))


_console_module = types.ModuleType("Py4GWCoreLib.Py4GWcorelib")
setattr(_console_module, "ConsoleLog", _console_log)
sys.modules["Py4GWCoreLib.Py4GWcorelib"] = _console_module
_settings_module = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.Settings")
setattr(_settings_module, "Settings", FakeSettings)
sys.modules["Py4GWCoreLib.py4gwcorelib_src.Settings"] = _settings_module
_json_module = types.ModuleType("Py4GWCoreLib.py4gwcorelib_src.JsonFactory")
setattr(_json_module, "JsonFactory", FakeJsonFactory)
sys.modules["Py4GWCoreLib.py4gwcorelib_src.JsonFactory"] = _json_module

# -- helpers ---------------------------------------------------------------------

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


def reset_all() -> None:
    FakeSettings.reset()
    FakeJsonFactory.reset()
    _CONSOLE.clear()


def seed_factory(sets_json) -> None:
    FakeJsonFactory.doc(_FACTORY_DOC, "global")["filter_sets"] = sets_json


# -- 1. a legacy NAME adopts the id, in the SAME key, once and silently ----------

reset_all()
seed_factory([dict(entry) for entry in MELEE_JSON])
loot_ini = FakeSettings.doc(_LOOT_INI, "global")
loot_ini["general|profile"] = "Melee"
config = loot_store.load()
check("adopts the legacy name into the id", "set_1", config.filter_set_id)
check("writes the id back to the SAME key", "set_1", loot_ini.get("general|profile"))
check("logs the adoption exactly once",
      [("Loot Filters", "selected filter set 'Melee' migrated to its id 'set_1'")], _CONSOLE)
reloaded = loot_store.load()
check("second load keeps the id", "set_1", reloaded.filter_set_id)
check("second load is silent",
      [("Loot Filters", "selected filter set 'Melee' migrated to its id 'set_1'")], _CONSOLE)

# -- 2. after adoption, a RENAME in the factory leaves the selection intact -------

seed_factory([dict(entry) for entry in RENAMED_JSON])   # same id, new name
reloaded = loot_store.load()
check("a renamed set still resolves through its id", "set_1", reloaded.filter_set_id)
check("the rename adds no new console message",
      [("Loot Filters", "selected filter set 'Melee' migrated to its id 'set_1'")], _CONSOLE)

# -- 3. a value matching nothing falls back in memory, the disk is untouched ------

reset_all()
seed_factory([])                                        # the set is gone
loot_ini = FakeSettings.doc(_LOOT_INI, "global")
loot_ini["general|profile"] = "Melee"
config = loot_store.load()
check("fallback resolves to none in memory", "", config.filter_set_id)
check("the stored value is not rewritten away", "Melee", loot_ini.get("general|profile"))
check("fallback is logged",
      [("Loot Filters", "selected filter set 'Melee' no longer exists - falling back to none")],
      _CONSOLE)

# -- 4. a dangling id falls back the same way ------------------------------------

reset_all()
seed_factory([])
loot_ini = FakeSettings.doc(_LOOT_INI, "global")
loot_ini["general|profile"] = "set_1"
config = loot_store.load()
check("dangling id resolves to none", "", config.filter_set_id)
check("the stored id stays on disk", "set_1", loot_ini.get("general|profile"))
check("the dangling id is reported",
      [("Loot Filters", "selected filter set 'set_1' no longer exists - falling back to none")],
      _CONSOLE)

# -- 5. clearing the selection overwrites the same key: nothing resurrects --------

reset_all()
seed_factory([dict(entry) for entry in MELEE_JSON])
loot_ini = FakeSettings.doc(_LOOT_INI, "global")
loot_ini["general|profile"] = "Melee"
config = loot_store.load()                              # adopts set_1 in the same key
config.filter_set_id = ""                               # the user deliberately clears it
loot_store.save(config)
check("save writes the cleared selection over the same key", "", loot_ini.get("general|profile"))
reloaded = loot_store.load()
check("the cleared selection is not resurrected", "", reloaded.filter_set_id)

# -- 6. the legacy account -> global copy keeps working, value resolved once ------

reset_all()
seed_factory([dict(entry) for entry in MELEE_JSON])
account_ini = FakeSettings.doc(_LOOT_INI, "account")
account_ini["general|profile"] = "Melee"
config = loot_store.load()
global_ini = FakeSettings.doc(_LOOT_INI, "global")
check("the legacy account policy is copied", True, global_ini.get("migration|from_account"))
check("the copied name resolves to the id under the same key", "set_1",
      global_ini.get("general|profile"))
check("the loaded selection is the id", "set_1", config.filter_set_id)
account_ini["general|profile"] = "Other"                # the account changes afterwards...
reloaded = loot_store.load()
check("a later account change is not re-imported over the configured policy", "set_1",
      reloaded.filter_set_id)

# -- 7. the factory document's legacy key stays a plain read fallback -------------

reset_all()
factory_doc = FakeJsonFactory.doc(_FACTORY_DOC, "global")
factory_doc["profiles"] = [dict(entry) for entry in MELEE_JSON]
sets = factory_store.load_filter_sets()
check("reads the legacy profiles key", "set_1", sets[0].id)
check("adds no filter_sets key on read", None, factory_doc.get("filter_sets"))
check("keeps the legacy key untouched", MELEE_JSON, factory_doc.get("profiles"))

# -- 8. Recolor & Beacons follows the same single-key scheme ----------------------

reset_all()
seed_factory([dict(entry) for entry in MELEE_JSON])
rb_ini = FakeSettings.doc(_RECOLOR_INI, "account")
rb_ini["general|profile"] = "Melee"
mark = recolor_store.load()
check("recolor adopts the legacy name into the id", "set_1", mark.filter_set_id)
check("recolor writes the id back to the SAME key", "set_1", rb_ini.get("general|profile"))
check("recolor logs the adoption once",
      [("Recolor & Beacons", "selected filter set 'Melee' migrated to its id 'set_1'")], _CONSOLE)

print("=" * 68)
print("%d case(s) failed" % failures)
sys.exit(1 if failures else 0)
