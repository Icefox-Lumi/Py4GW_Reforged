# FrenkeyLib Boundary Compliance Plan

Status: in progress
Progress: Phase 1 items 1-4 executed with the profile/config JsonFactory
migration; item 5 (DataCollector + data_dict) executed on 2026-08-13. Phase 2
item 1 (ImGuiIniReader removal) is done. Outstanding: `json/Defaults` seeds,
the one-time data import, and live-client verification.
Authority: `Py4GWCoreLib/py4gwcorelib_src/Settings.py`,
`Py4GWCoreLib/py4gwcorelib_src/JsonFactory.py`, the current ported sources under
`Sources/frenkeyLib`, and the surviving `reforged-migration` records

## Objective

Move every active FrenkeyLib persistence and window-state flow onto the
Reforged owners with no compatibility shims:

- INI key/value state through `Settings` (`settings/<account>/...` or
  `settings/Global/...`).
- structured state through `JsonFactory` (`json/<account>/...` or
  `json/Global/...`).
- window geometry and per-window state through native ImGui persistence
  (`imgui.ini`), not custom INI/JSON sections.

The ported code must call those two owners directly. No `IniHandler`,
`IniManager`, `configparser`, `open(...).write`, or filesystem-layout helpers
may remain for runtime state. This is a call-site migration, not an adapter
layer.

## Boundary 1: persistence jails

`Settings` owns flat INI documents addressed by `(section, key)`, self-throttled
and self-persisting; scope is `account` or `global`, and there is no root scope.

`JsonFactory` owns structured JSON documents addressed by slash paths, likewise
scoped `account` or `global`, with no root scope. New documents seed from the
repository `json/Defaults` tree and bind under the runtime `json/` jail.

Neither owner is opened, saved, or closed manually; `save()`/`reload()` are
escape hatches only.

## Boundary 2: ImGui window persistence

`ImGui.Begin`, `ImGui.BeginWithClose`, and `ImGui.End` accept `ini_key` for
signature compatibility only; Reforged ignores it and persists window
geometry (position, size, collapsed) through native ImGui (`imgui.ini`), keyed
by the unique window name.

Feature code may persist only functional toggles (open/visible) through
`Settings`, as `FloatingIcon` already does. Transient geometry is still
legitimate: `ImGuiCond.Always` on modal popups, centered popup placement, and
per-frame drag-preview repositioning are not persistence and stay.

Compliance means no frenkeyLib module parses or writes `imgui.ini`, and no
module persists position/size/collapsed into its own INI or JSON document.

## Current-state audit

### Already compliant

| Owner | Evidence |
|---|---|
| `ItemManager/config.py` | `Settings(main_ini_key/floating_ini_key, "account")` |
| `ItemManager/ui.py` | AutoTick toggle through `Settings(...).get_bool/set` |
| `DataCollector/config.py`, `DataCollector/data_collector.py` | `Settings(..., "global")` |
| `SulfurousRunner/settings.py` | migrated to the jailed `Settings` |
| `ItemHandling/Rules/profile.py` | `JsonFactory("ItemHandling/Profiles/<name>.json")` |
| `DataCollector/models.py:382` | `json.loads` on a stored string, not file I/O |
| `DataCollector/collectors/*` | `JsonFactory("Widgets/Data Collector/<name>.json", "account")` |
| `Core/data_dict.py` | pure serialization; no filesystem access remains |

### Resolved since the audit

| Owner | Resolution |
|---|---|
| `global_configs/GlobalConfigProfileManager.py` | `JsonFactory("Item & Inventory/Configs/<key>_shared.json", "global")` and `..._profiles.json` (account); path helpers and `os`/`shutil` removed |
| `global_configs/BuyConfig.py`, `CraftingConfig.py`, `RuleConfig.py`, `SortingConfig.py` | `reload_from_document`/`save_to_document(document, profile_key)` |
| `ItemManager/ui.py` `ConfigInfo.Save`/load | calls the document surface; the `json.dumps` cache signature stays (pure serialization) |
| `ItemHandling/Items/ItemData.py` | account `JsonFactory("ItemHandling/ItemData.json")`; the read-only repository `items.json` fallback remains (content read) |
| `Core/data_dict.py` | stripped to pure serialization (`{version, data}` payload, `remove_none_values`); file locks, mtime refresh, atomic writes, and quarantine machinery removed |
| `DataCollector/collectors/*` | `JsonFactory("Widgets/Data Collector/<name>.json", "account")`; the dormant collectors keep this wiring but were trimmed from `data_collector.py`'s runtime registry |
| `Core/utility.py` `ImGuiIniReader` | removed; the dormant `LootEx` package is its only remaining importer |

Capability deltas: the legacy mtime-based cross-client reload loop is gone (its
ShMem broadcast was already hardwired off); `JsonFactory.reload()` is the
escape hatch. The legacy global file tree `Settings/Global/Widgets/Data
Collector/` is no longer read or written and is covered by the one-time import
below.

Stale `[Window config]` sections already present in runtime INIs are legacy
artifacts with no current writer; no new code may produce them.

### Excluded from scope

- `Sources/frenkeyLib/LootEx/*` — the LootEx widget was deleted and the package
  is dormant; recommend deleting the package in the same batch rather than
  migrating it.
- `Sources/frenkeyLib/Drafts/*` — not runtime code.
- Reforged-owned `Py4GWCoreLib` modules.
- Shipped catalog content read from repository source (`Sources/frenkeyLib/.../
  data/*.json`) is read-only content, not runtime state; reads may remain, but
  any local override of that content becomes a JsonFactory document.

## Phase 1: full Settings/JsonFactory compliance, no shims

1. Profile storage redesign in `GlobalConfigProfileManager`:
   - keep active-profile selection and character bindings in the existing
     `Settings` INI (`Item & Inventory/ItemManager.ini`);
   - the `SHARED` profile becomes a `global` JsonFactory document;
   - character profiles become `account` JsonFactory documents;
   - remove `os.makedirs`, `get_active_config_folder`,
     `get_active_config_file_path`, and every direct path the manager hands to
     config classes.

2. Config classes accept a document name instead of a file path:
   - `BuyConfig`, `LootConfig`, `InventoryConfig`, `CraftingConfig`,
     `SortingConfig`, `RuleConfig` load/save through
     `JsonFactory(name, scope).get_json/set_json`.

3. `ItemManager/ui.py` `ConfigInfo.Save`/`reload_from_file` call the new
   JsonFactory surface; `json.dumps` for cache signatures is pure string
   serialization and stays.

4. `ItemHandling/Items/ItemData.py` moves `item_json_path` to an account-scoped
   JsonFactory document.

5. `Core/data_dict.py` stays a serialization helper. Consumers pass either a
   JsonFactory-backed payload or a read-only content path; no runtime override
   may write through `open()`.

6. One-time data import: copy the current
   `Settings/Global/Item & Inventory/Configs/*` JSON into the new JsonFactory
   documents, then stop touching that filesystem tree. The import is a
   migration step, not a runtime shim.

### Phase 1 execution record (2026-08-13)

Items 1-4 landed with the profile/config migration; item 5 landed in the
DataCollector pass. Decisions taken during item 5:

- Collected data lives in account-scoped documents named
  `Widgets/Data Collector/<file>.json`, one per legacy collector file,
  preserving the legacy `{version, data}` payload shape.
- The ten collectors not wired into `DataCollectorRuntime` stay importable but
  were trimmed from the runtime registry and import list.
- `Core/data_dict.py` keeps only serialization; document reads/writes happen
  in `BaseCollector.load`/`try_save` through `JsonFactory` directly.
- `BaseCollector` drops the mtime-based `refresh_from_disk_if_changed` loop;
  `JsonFactory` dedups unchanged `set_json` calls, so there is no save loop.

Item 6 (one-time import, now including the legacy
`Settings/Global/Widgets/Data Collector/` tree) and the `json/Defaults` seed
names remain open, along with the live-client gate.

## Phase 2: ImGui window-persistence compliance

1. Remove `ImGuiIniReader` from `Core/utility.py`; nothing active imports it
   once the dormant LootEx package is deleted.
2. Confirm no remaining `imgui.ini` access in `Sources/frenkeyLib`.
3. Keep `FloatingIcon` and AutoTick functional toggles in `Settings`.
4. Leave transient popup/drag geometry as is; the ItemManager main window
   already delegates its geometry to native ImGui.
5. Optionally drop the now-dead `ini_key` arguments at call sites; this is
   cosmetic and must stay separate from any behavior change.

## Verification gates

- Grep: no `open(..., "w")`, `json.dump`, `json.load`, `os.makedirs`, or
  `configparser` remains in `Sources/frenkeyLib` outside read-only catalog
  loaders.
- Grep: no `imgui.ini`, `ImGuiIniReader`, or `[Window config]` writes remain
  in `Sources/frenkeyLib`.
- Pyright reports zero errors on every changed file.
- Live client: profiles load, save, switch, and rename; new documents appear
  under `json/...`; INI state appears under `settings/...`; no file is written
  outside the two jails.
- Live client: window positions, sizes, and collapse state survive a reload
  through `imgui.ini`; open-state toggles survive through `Settings`.
- `SHARED` edits survive across accounts; character edits stay per account.

Offline verification run 2026-08-13: `compileall` over the changed files,
strict Pyright over `Core/data_dict.py` and `DataCollector/` (0 errors), a
headless round-trip test of the `{version, data}` payload and
`remove_none_values`, and the grep gates. The remaining grep hits are the
documented exclusions: dormant `LootEx`/`Drafts`/`ConfigExamples`, asset-path
joins, and the read-only `ItemHandling/Items/ItemData.py` catalog fallback.
Live-client verification of document bind/load/save remains outstanding.

## Risks and open questions

- ~~JsonFactory documents are self-throttled; remove any manual save loop the
  current classes rely on.~~ Resolved: collectors only serialize when marked
  dirty, and `set_json` dedups unchanged payloads.
- Global documents take a cross-process lock; only `SHARED` should be global.
- Account documents stage until the account anchor resolves; profile reads at
  boot must tolerate an unbound document.
- The exact `json/Defaults` seed names for each config type are decided during
  implementation and recorded here before merging.
- Profile rename semantics under JsonFactory (single document per profile
  versus one document with a profile map) are resolved in step 1.
- ImGui persists window state keyed by window name; renaming a window loses
  its geometry, so window-name stability is part of the UI contract.

## Relationship to prior records

This plan supersedes none of the rejected records. It extends
`frenkeylib-itemmanager-port-plan.md`: that plan shimmed the port into a
loadable state, while this plan removes the remaining persistence shims and
moves the port fully inside the Reforged jails.
