# FrenkeyLib ItemManager and DataCollector Reforged Port Plan

Status: proposed
Progress: Phase 1 executed on 2026-08-12; containment applied, imports
repointed, and the port now lives entirely under `Sources/frenkeyLib`.
Phase 2 binding shims in progress; the port-set Pyright count is down from
189 to 52. INI persistence now uses the jailed `Settings` class directly,
with no IniManager compatibility layer.
Scope: minimal-shim port of the ItemManager feature set from the
`data_collection` branch onto the Reforged base
Authority: `frenkey-derp/Py4GW@data_collection`
(`164ab958c6df89ac55f246ad0e0e7b9e976e718e`), Reforged base `01cfb912`
sources and stubs, the surviving `reforged-migration` records, and
`Py4GW_Reforged_Native` JSON seeding implementation

## Purpose and constraints

The goal is a working Reforged ItemManager, not a replacement product. The
port copies the legacy code verbatim and changes only the severed surfaces:
binding renames, changed data shapes, and the persistence owner. There is no
redesign, no profile conversion on load, no field deletion, and no UI rewrite.

Reforged owns the item-mod class and other `Py4GWCoreLib` surfaces. Until the
real migration, every ported legacy module is contained under
`Sources/frenkeyLib` so the two ownership domains never collide and the legacy
graph can be removed or re-homed later in one place.

The non-negotiable controls in
`frenkeylib-migration-failure-and-rollback-record.md` and
`frenkeylib-decision-autopsy.md` govern this plan. Reforged supplies facts
(`Item`, `Item.Mods`, `PyItem`) and storage (`Settings`, `JsonFactory`).
FrenkeyLib keeps its own profiles, rules, workflows, and UI.

## Baselines

| Boundary | Value |
|---|---|
| Source | `frenkey-derp/Py4GW` branch `data_collection` |
| Target | `Py4GW_Reforged` base `01cfb912` |
| Native | `Py4GW_Reforged_Native`; global JSON seeds from `json/Defaults/<name>` on first bind, verified in `src/json/json_factory.cpp:313-340` |
| Worktree | Reverted to `01cfb912` on 2026-08-12; migration docs and the dirty `.gitignore` retained |

The local `Py4GW_python_files` tree is parity evidence only. The branch is the
authoritative source for these paths because it contains the ItemManager,
DataCollector, and moved module layout that the local tree lacks.

## Port set

Measured on the branch checkout: 44 Python files, about 27,500 lines, after
adding the two Core helpers the DataCollector imports.

| Group | Files | Role |
|---|---|---|
| `Widgets/Guild Wars/Items & Loot/ItemManager.py` | 1 | Widget entry point; uses `main()` as the per-frame UI callback |
| `Sources/frenkeyLib/ItemManager/{btrees,config,ui}.py` | 3 | Behavior trees, INI-backed config, and the full UI |
| `Sources/frenkeyLib/DataCollector/` | 15 | Runtime dependency: `item_snapshot.data` and the UI call `ITEMS.get_item_data(...)` |
| `Sources/frenkeyLib/ItemHandling/{InventoryBT,Recipe}.py` | 2 | Only surviving ItemHandling imports; the branch deletes the rest |
| `Sources/frenkeyLib/global_configs/` | 9 | Buy, Loot, Inventory, Crafting, Sorting configs, rules, conditions, and the profile manager |
| `Sources/frenkeyLib/item_data/{ItemData,item_snapshot}.py` | 2 | Item snapshots and parsed item data |
| `Sources/frenkeyLib/item_mods_src/` | 9 | Legacy modifier/upgrade decoding and properties, quarantined from the Reforged mod class |
| `Sources/frenkeyLib/Core/{data_dict,json_serializable}.py` | 2 | DataDict JSON persistence helpers imported by DataCollector; absent from Reforged base |

The widget folder already carries a `.widget` marker on the branch, matching
Reforged discovery.

## Containment and ownership

The three legacy packages were first copied under `Py4GWCoreLib/` and then
moved to `Sources/frenkeyLib/{global_configs,item_data,item_mods_src}` on the
user's direction. Every import of those three prefixes inside the ported set
was repointed from `Py4GWCoreLib.` to `Sources.frenkeyLib.`, and the two Core
helpers were added to `Sources/frenkeyLib/Core/`. Verification after the move:
44 files scanned, 22 files repointed, zero byte-level mismatches against the
branch sources, and zero remaining `Py4GWCoreLib.global_configs|item_data|
item_mods_src` references anywhere in the repository.

This keeps the legacy mod/config/data graph inside `frenkeyLib` and leaves
`Py4GWCoreLib/Item`, `Item.Mods`, and the rest of the Reforged mod class
untouched. No base-owned file referenced the moved paths, so no base import
was harmed by the relocation.

## Dependency verdict

Verified against base `01cfb912` on 2026-08-12:

- Every `Py4GWCoreLib` import resolves except `IniManager`,
  `py4gwcorelib_src.IniHandler`, and the port payload itself.
- All seven consumed enum modules (`GameData`, `Item`, `Model`, `IO`,
  `Texture`, `Region`, `Multiboxing`) have zero members missing in Reforged.
- `Merchant.Trading`, `Routines.Checks.Map.MapValid`, `UIManager`, and
  `Item.item_instance` exist at base. Reforged renamed the legacy
  `Item.Customization` fact owner: `Item.Mods.GetModifiers` and
  `Item.Properties.IsStackable` are the current names.

## INI persistence decision

Per the user's direction, INI access uses `Settings(name, scope)` directly;
no `IniManager`/`IniHandler` compatibility shim was created. The ItemManager,
DataCollector, and profile-manager documents bind through `Settings` with
their legacy names and sections, and defaults are seeded only when a key is
absent. One capability delta is recorded: profile rename previously
propagated the active-profile assignment across every account's INI file on
disk. `Settings` exposes no account enumeration, so the port updates the
current account only and the cross-account propagation is deferred to the
later migration.
- The Reforged `ImGui` wrapper keeps the `ini_key` parameter on `Begin`/`End`
  for compatibility; `FloatingIcon` consumes it through
  `Settings(ini_key, "account")`.

## Verified gap ledger

This is the complete expected change surface. Anything not listed here should
not be changed.

| # | Legacy surface | Reforged surface | Change |
|---|---|---|---|
| 1 | `Py4GW.Console.{Log,MessageType,get_projects_path}` | `PySystem.Console.*` | Repoint call sites; the same message types and path helper exist |
| 2 | Module-level `PyItem.GetNameEnc(id)`, `GetSingleItemName(id)`, `GetCompleteNameEnc(id)` | Instance methods on `PyItem.PyItem(id)` | Wrap the three `_load_name_bytes` callers in `item_snapshot.py` |
| 3 | `PyInventory.Bag(...).FindItemById(id)` | Removed | Iterate `Bag.GetItems()` dicts and compare `item_id` |
| 4 | `Bag.GetItems()` returns `PyItem` objects | Returns `{item_id, slot, model_id, quantity}` dicts | Build `PyItem.PyItem(entry["item_id"])` before snapshot construction; read `slot` and `item_id` as dict keys |
| 5 | `PyImGui.set_item_allow_overlap`, `push_style_var2` | `set_next_item_allow_overlap`, `push_style_var_vec2` | Two renames; flag enums otherwise match the Reforged stub |
| 6 | `IniManager` / `IniHandler` | `Settings(name, scope)` | `ensure_key`/`load_once` disappear; `read_key`/`write_key` become `get_*`/`set_*` with identical sections and keys |
| 7 | Raw `json`/`os`/`shutil` profile and catalogue I/O (62 sites) | Temporary bounded compatibility shim now; `JsonFactory` with the identical schema later | Preserve the legacy access surface unchanged; defer the storage-owner swap to a separately planned migration |
| 8 | Same-account profile duplicate/rename/delete via file operations | Deferred with item 7 | Later migration expresses these with `JsonFactory` primitives; audit `delete("")` semantics at that point |

## Persistence scope and gitignore reconciliation

| Data | Scope | Git treatment |
|---|---|---|
| Window geometry, page and toggle state | account `Settings` (`ItemManager.ini` names) | ignored |
| Per-character active profile selection | account `JsonFactory` | ignored |
| Static catalogues: item data, Nick cycle, recipes, upgrades, materials | global `JsonFactory`, seeded from `json/Defaults` | Defaults tracked |
| `SHARED` profile | global `JsonFactory` | Defaults tracked as the shipped template |
| Per-account collected discoveries | account `JsonFactory` | ignored |

This table is the eventual target. For this port the user directed a temporary
JSON compatibility shim instead: the ported code keeps accessing its JSON the
way it does today (`DataDict` local/default paths and the profile file
operations), quarantined inside `frenkeyLib`, and the `JsonFactory` migration
happens later. The shim is explicitly temporary and bounded; it does not
introduce a new permanent persistence owner. The known tradeoff is that legacy
file paths can sit outside the `/json` jail until the follow-up migration
re-jails them.

Base `.gitignore` ignores `json/**` with exceptions only for `json/modular/**`
and `json/Global/EnemyTracker/*.json`. The dirty worktree `.gitignore` adds the
LootEx/MerchantRules Defaults exceptions; its disposition is a separate user
decision, preserved rather than overwritten.

The port adds the ItemManager Defaults exception using the established
drilldown pattern:

```gitignore
# ItemManager shipped JSON seeds; global documents seed from these on first bind
!json/Defaults/Widgets/Guild Wars/Items & Loot/ItemManager/
!json/Defaults/Widgets/Guild Wars/Items & Loot/ItemManager/**
```

Generated `json/Global/.../ItemManager` documents remain ignored: the native
side seeds them from the tracked Defaults templates. Account documents stay
ignored as per-user state.

## Phases and exit gates

### Phase 0: baseline and hygiene

Branch `codex/frenkeylib-itemmanager-port` from the clean base. Resolve the
`.gitignore` reconciliation decision and record it. Freeze a map of
DataCollector `get_local_path`/`get_default_path` inputs to their intended
jailed document names.

Branch created on 2026-08-12. Gate: `git status` shows only the planned
documentation, gitignore, and port changes. The `.gitignore` disposition
remains open and is deferred with the JSON migration.

### Phase 1: verbatim copy

Copy the port set unchanged, add the two missing Core helpers, move the three
legacy packages under `Sources/frenkeyLib`, repoint the three import prefixes,
and verify byte-for-byte against the branch sources. Done on 2026-08-12:
44 files, 22 repointed, zero mismatches, zero stale prefixes.

Gate: copied files contain no edits beyond the mechanical prefix repoint.

### Phase 2: binding shims

Apply gap ledger items 1-5 in dependency order: `item_data`, then
`global_configs`, `ItemManager`, `DataCollector`. Run the `PyImGui` surface
sweep for signature drift.

Gate: strict Pyright over the ported set reports no new baseline errors and
`py_compile` passes.

### Phase 3: temporary JSON compatibility shim

Keep the legacy JSON access surface working through a bounded shim confined to
`frenkeyLib`: `DataDict` keeps its local/default path inputs, and the profile
manager keeps its existing file operations. This defers the `JsonFactory`
owner swap and the gitignore exceptions to a separate migration, per the
user's direction.

Gate: legacy catalogue and profile reads/writes behave as they did on the
branch; the shim is quarantined, documented as temporary, and does not leak
legacy ownership into `Py4GWCoreLib`.

### Later: JsonFactory migration

Apply gap ledger items 7 and 8 with the same-schema rule: move documents into
`json/` through `JsonFactory`, add the ItemManager `json/Defaults` seeds and
gitignore exceptions, and audit same-account profile duplicate/rename/delete.
This is a separate program and is not started during the port.

### Phase 4: offline verification

Run the strict project Pyright configuration, `compileall`, and a headless
import smoke harness following the `tools/verify_*.py` pattern with stubbed
embedded modules. Add attributable fixtures for snapshot construction and
modifier parsing.

Gate: every check passes with readable input/state/expected/observed output.

### Phase 5: live-client acceptance

Boot the widget in an injected client: discovery, `main()` render, console
logging, profile load/save, and catalogue read. Correlate crash and injection
logs on any failure.

Gate: the user can configure and use the intended ItemManager flow.

## Acceptance criteria

The port is complete only when all of the following hold:

- Legacy profile JSON loads unchanged from the jailed documents.
- The ItemManager UI boots and exposes the same screens and operations.
- `Item`, `Item.Mods`, and `PyItem` are consumed only as fact providers; no
  rule or profile ownership moves to another product.
- JSON access runs through the bounded compatibility shim; the later
  `JsonFactory` migration is tracked as a separate program.
- Pyright, the smoke harness, and the fixtures pass.
- A live injected-client session exercises the workflow end to end.

## Open items

- Exact `json/Defaults` document names for the DataCollector catalogue inputs
  (resolved in the later JsonFactory migration).
- `JsonFactory` same-account profile duplicate/rename/delete semantics and the
  `delete("")` root behavior (audited in the later migration).
- Live-client verification, which cannot be performed offline.
- Disposition of the currently dirty `.gitignore` (deferred with the JSON
  migration).
- Cross-account profile-assignment propagation on rename, until `Settings`
  exposes account enumeration or the later migration decides otherwise.

## Relationship to the rejected records

This plan supersedes none of the rejected records. The failure and rollback
record and the decision autopsy remain binding lessons; the complete-cutover,
layered, and stage-0 documents remain historical evidence of the rejected
direction. This document is forward-only.

## LootEx port (2026-08-13)

The LootEx widget was the actual objective of this session. It is a separate
feature from ItemManager: its widget `Widgets/Guild Wars/Items & Loot/LootEx.py`
plus the `Sources/frenkeyLib/LootEx` package (30 modules), the
`Sources/frenkeyLib/SulfurousRunner` package (6 modules), and the shared
`Sources/frenkeyLib/Core` modules (`gui`, `utility`, `iterable`, `ex_style`,
`texture_map`, `encoded_names`, `data_dict`, `json_serializable`,
`ui_manager_extensions`).

The Reforged base already tracked a drifted, rejected copy of these packages.
All of them were overwritten from the `data_collection` branch (the user's
authoritative legacy copy) and then shimmed, so the working tree now holds the
legacy sources plus the minimal severed-surface fixes below. No redesign was
done.

### Shim inventory

| Legacy surface | Reforged replacement |
|---|---|
| `from Py4GW import Console` / `Py4GW.Console.*` | `py4gwcorelib_src.Console.Console` / `PySystem.Console` |
| `Py4GW.Game.enqueue(...)` | `PyGameThread.enqueue(...)` |
| `PyTrading.OfferItem(...)` | `PyTrade.offer_item(...)` |
| `Item.Customization.IsStackable` and friends | `Item.Properties.IsStackable/IsInscribable/IsPrefixUpgradable/IsSuffixUpgradable` |
| `Item.Customization.Modifiers.GetModifiers/GetModifierValues` | `Item.Mods.GetModifiers/GetModifierValues` |
| `Item.Customization.GetDyeInfo(...)` | `Item.GetDyeColor(...)` |
| `UIManager.GetFrameIDByHash/GetChildFrameID/GetFrameCoords/FrameClick` | `FrameTree.Frame.from_hash(...)._target_id()`, `.rect`, `Frame.from_id(...).click()` |
| `PyImGui.dummy/is_rect_visible/set_cursor_pos/set_cursor_screen_pos(a, b)` | tuple form `((a, b))` |
| `PyImGui.push_style_var2(idx, a, b)` | `PyImGui.push_style_var_vec2(idx, (a, b))` |
| `IniHandler` (SulfurousRunner settings) | jailed `Settings` (`get_bool`/`get_str`/`set`) |
| `native_src.methods.DatFileMethods.read_dat_file_by_hash` | `PyDatReader.read_file_by_hash` |

`Frame.from_hash(...)._target_id()` deliberately returns `0` on a missing
frame (it never raises), preserving the legacy open/closed checks.

### Verification state

- All ported files compile under Python 3.13.
- Pyright on the port set: 151 errors down to 6; the remainder are pre-existing
  optional-attribute typing in `LootEx/gui.py` around `rule.models`, not
  Reforged surface drift.
- A stub-diff sweep over every `Py*` module attribute used by the port set
  reports zero violations.
- Live injected-client load is the outstanding gate and cannot be run offline.

First live-client result (2026-08-13 01:03): the widget now loads, discovers,
and runs `main()`; rendering stopped at `LootEx/gui.py` `draw_general_settings`
with `KeyError: DyeColor.Mixed`. Reforged's `DyeColor` adds `Mixed = 1`, which
the legacy enum did not have. The dye selection loop now skips `Mixed` the same
way it skips `NoColor`. Awaiting the next live run.

Second round (user-reported ImGui/console notes, 2026-08-13):

- Recipes/Crafting: `draw_recipe_selectable` declared 2 columns when
  `expand=False` but always called `table_setup_column` five times; Reforged's
  ImGui asserts where legacy tolerated it. The Ingredients/Gold/GoldTexture
  setups are now gated behind `if expand:`.
- Debug & Data inventory: `draw_debug_item` popped the Border style color twice
  (once inside the child, once via a flag that was never set). The flag is now
  set at the first pop, balancing the stack.
- Textures: Reforged owns `Assets/Textures`. Item icons are now resolved
  through `get_texture_for_model(model_id)` (`Assets/Textures/Item
  Models/<id>-<name>.png`) with the legacy wiki-named file under
  `Assets/Textures/Items` preferred when present; dye and missing-texture
  paths point at `Assets/Textures/Dyes` and
  `Assets/Textures/missing_texture.png`.

ItemManager consumer wiring (2026-08-13):

- Fixed the live crash where bag entries arrived as `SimpleNamespace` instead
  of dicts (`item_snapshot.py`, `items_collector.py` now accept both shapes).
- `InventoryBT` no longer uses the legacy `BT.Items.*` catalog. It dispatches
  to `BTNodes.*`, with local batch shims for salvage and trader selling.
- Added a persisted "Auto-run Item Actions" toggle to the ItemManager window;
  when on it ticks the active Inventory Processing config about every 250 ms.
- Restored the legacy synchronous bag-sort planner as
  `Sources/frenkeyLib/ItemHandling/bag_sort.py` (`GetBagSortPlan`,
  `GetPlannedBagLayout`, `BuildSortBagsNode`), which powers the sorting
  preview, the Sort Selected action, and InventoryBT auto-sort maintenance.
  `BTNodes.Bags.SortBags` remains unused by this consumer because its
  provisional default order ignores the configured sort groups.
- Known remaining drift: `BTNodes` has no `XunlaiStorage`/`Collector` catalog
  equivalents, but the ItemManager consumer does not call them.
