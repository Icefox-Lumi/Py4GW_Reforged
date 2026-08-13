# FrenkeyLib Stage 0 Cutover Ledger

Status: historical rejected migration ledger; superseded by
`frenkeylib-migration-failure-and-rollback-record.md`
Scope: live-source inventory for the FrenkeyLib and Mark modifier-consumer
migration. Deprecated inventory control is an explicit exclusion.
Authority: current Python source, `Item.Mods`, the layered migration plan, and
the current decoder parity report. Legacy source is behavioural reference only.

Related current plan: `frenkeylib-complete-cutover-plan.md`.
The layered plan remains the detailed historical execution journal.

## Recorded migration boundary

The retained FrenkeyLib surface is a consumer of an already supplied item ID.
It may present or compose public Reforged item answers. It must not scan bags,
construct snapshots for control flow, select inventory actions, or execute
identify, salvage, or storage work.

The native System Settings inventory owner now supplies explicit execution
requests without inheriting a Frenkey inventory handler. Its current contract
is deliberately narrow: an identify request accepts item IDs and polls each
native result; salvage and storage operate only on an explicitly hovered item;
materials-salvage confirmation requires a separate explicit request. The
controller uses native `PyInventory` actions and does not create a second raw
modifier, catalogue, snapshot, or action queue owner.

This is an execution owner, not a new inventory rule engine. Reforged remains
the source of item facts and rule verdicts, while the System Settings controller
only receives item IDs. Automatic selection, range interpretation, and legacy
MerchantRules policy remain outside this first cutover.

## Source-reachability inventory

| Current root or dependency | Evidence | Stage 0 disposition |
|---|---|---|
| `Widgets/Guild Wars/Items & Loot/TeamInventoryViewer.py` | Source cutover removed Mark parser imports, `ModDatabase`, `parse_modifiers`, raw modifier reads, and the unused raw-modifier hash cache. | Retained read-only consumer. It uses `Item.Mods.Inspect(item_id).upgrades` for conservative base-name cleanup and public slot reads for detailed row labels. |
| `Widgets/Guild Wars/Items & Loot/MerchantRules.py` | Its Mark parser import, `MOD_DB` catalog load, private raw armor parser, and legacy `runes.json` picker/model-catalog loads have been removed. It consumes `Item.Mods.Inspect`, `GetKnownUpgradeFacts`, and `NormalizeUpgradeIdentifier` for modifier and upgrade facts. Account JsonFactory documents own profiles; account `Settings("Widgets/Guild Wars/Items & Loot/MerchantRules/MerchantRules.ini")` owns main-window geometry, and account `Settings("Widgets/Guild Wars/Items & Loot/MerchantRules/MerchantRulesFloating.ini")` owns floating-icon geometry. The floating icon owns only session visibility. | Retained inventory widget is a Reforged consumer; its future execution-policy replacement remains separate from this item-mod cutover. |
| `Widgets/Guild Wars/PartyQuestLog.py` | Direct FrenkeyLib widget root. | Retained non-inventory feature slice. Its log and configuration UI are direct PyImGui consumers; account Settings own personal state after a non-overwriting one-time import from the former global/widget-config documents. |
| `Widgets/Guild Wars/MultiBoxing.py` | Direct FrenkeyLib widget root. | Retained non-inventory feature slice. Its shared policy, account ordering, and stable-ID layout records remain global; its Configure window geometry is account Settings with a one-time non-overwriting import from the old global keys. Layout display names never form document paths. |
| `Widgets/Automation/Bots/Runners/Sulfurous Runner.py` | Direct FrenkeyLib widget root. | Retained non-inventory feature slice. Its configuration and tooltip are direct PyImGui; account Settings own personal state after a non-overwriting one-time import from the former global/widget-config documents. Map-overlay/path rendering stays with the existing overlay owner. |
| `Widgets/Automation/Bots/Miscellaneous/Polymock.py` | Direct FrenkeyLib widget root. | Retained non-inventory feature slice. Widget UI is direct PyImGui with account `Settings("Widgets/Automation/Bots/Miscellaneous/Polymock.ini")` for main-window geometry after one non-overwriting import from the former global value; WidgetManager remains the open owner. The active texture helper is used only for piece-image rendering. No direct modifier-read evidence in this pass. |
| `Widgets/Guild Wars/Items & Loot/LootEx.py` | Explicit WidgetManager entry added on 2026-08-11 after source and history confirmed that `LootEx/gui.py` was never a runnable script. | Source-cutover-complete jailed presentation surface. Account `Settings` owns geometry and page state; account `JsonFactory` owns only Factory-profile selection and conversion audit. Reforged Loot Filter Factory owns all rule/profile records and matching. LootEx provides selection, read-only display, explicit item-ID preview, catalogue status, and conversion UI while avoiding the legacy GUI, raw catalogue loaders, and inventory, merchant, salvage, or storage handlers. Its explicit converter is conservative: a legacy predicate with a missing Reforged fact creates no active rule and records its rejection rather than broadening the match. Live account-bind, seeded-catalogue readback, and window restore acceptance remain required. |
| `Sources/frenkeyLib/Core/` | No retained root imports the package after Polymock's direct PyImGui label cutover. | Historical facade and legacy executor support evidence. It is not an active migrated dependency; the boundary verifier rejects any attempt to reattach it from a retained consumer. |
| `Sources/frenkeyLib/Core/encoded_names.py` | Imported only by `ItemHandling/Items/item_collecting.py`. | Excluded with the snapshot collector. Its current missing `PyGameThread` static import is not a retained Polymock/Core failure and must not pull inventory collection back into this migration. |
| `Sources/frenkeyLib/Py4GWLibrary/library.py` | No current importer outside its own module; its configuration is read and written through `Settings.find`. | Dormant shared UI helper. No persistence migration is needed unless a supported current launchpad adopts it. |
| `Sources/frenkeyLib/Drafts/` | Historical widget-manager and library scripts create their own old INI directories; no current importer was found. | Not a retained feature. Document as historical code; do not migrate its persistence or UI surface. |
| `Py4GWCoreLib/py4gwcorelib_src/AutoInventoryHandler.py` | Imports `ItemSnapshot` at line 137 and `BTNodes` at lines 338 and 361. | Explicitly excluded and later deprecated. No migration work may repair this coupling or use it as a compatibility path. |
| `Widgets/Guild Wars/Items & Loot/InventoryPlus.py` | Manual identify and salvage submit explicit requests to System Settings. | It no longer imports, constructs, configures, or schedules `AutoInventoryHandler`; automatic-mode controls and blacklist persistence were removed. Its separately dynamic `Xunlaimanager.py` storage-sort bridge remains an Inventory+/System Settings retirement concern, not a Frenkey migration dependency. |
| `Sources/frenkeyLib/LootEx/inventory_handling.py` | Defines `LootExAutoInventoryHandler`, `InventoryHandler`, and replaces the core handler instance. | Explicitly excluded. It is evidence of the old competing inventory owner, not a base to port. |
| `Sources/frenkeyLib/LootEx/messaging.py` | The standard `Widgets/System/Messaging.py` dispatcher reserves `SharedCommandType.LootEx` as an explicit no-op; source importers of the legacy receiver are inside the historical LootEx graph. | Explicitly excluded. The retained LootEx widget neither sends nor receives this command, so no legacy messaging protocol is part of its migration. The shared enum/comment marks it as reserved legacy protocol rather than a current private receiver. |
| `Sources/frenkeyLib/ItemHandling/{BTNodes,Handlers,Items/item_snapshot.py}` | Snapshot and behavior-tree paths drive inventory decisions and actions. | Explicitly excluded. Do not migrate, test for parity, or retain as a dependency of a migrated consumer. |

The direct Frenkey widget roots are source-reachability evidence, not proof
that every transitive module is live in a particular injected-client session.
Existing runtime diagnostics are consulted only for a reported feature concern;
they are not a migration prerequisite.

## 2026-08-11 retained-surface certification

The four retained feature packages have complete Python-file parity with their
legacy counterparts: MultiBoxing (7 files), PartyQuestLog (4), Polymock (4),
and SulfurousRunner (6). Current source contains no legacy UI facade,
raw-persistence operation, raw modifier reader, parser/catalog owner, or
deprecated inventory-handler import in those packages or their four widget
roots.

`Py4GWCoreLib/py4gwcorelib_src/AutoInventoryHandler.py` remains the sole
external importer of Frenkey `ItemHandling`. It is explicitly quarantined for
the later retirement work; it is neither a retained Frenkey feature nor a
compatibility dependency of the migrated surface. No code in this migration
ports, restores, or extends it.

`python -m py_compile` and focused Pyright over all retained package modules
and the four widget roots completed with zero
diagnostics. MerchantRules remains a separate legacy inventory-policy widget;
its full-file Pyright run reported 541 diagnostics on 2026-08-11. This remains
a separately tracked legacy baseline; the Mark facade is the only one of these
two files with a clean focused Pyright result.

On 2026-08-12, the current retained surface was rechecked together:
MultiBoxing, PartyQuestLog, SulfurousRunner, Polymock, the Mark presentation
facade, TeamInventoryViewer, and the active LootEx widget/profile/catalogue/
converter modules. `python -m py_compile` completed for every listed module
and strict Pyright reported zero errors and warnings. This is source-level
evidence only; JsonFactory first-bind defaults, account conversion, and LootEx
geometry/collapse/close behaviour still require an injected Guild Wars client.

## Item-mod call ledger

| ID | Current source and evidence | Question currently answered | Required owner after cutover | Disposition and removal condition |
|---|---|---|---|---|
| M-01 | `Sources/marks_sources/mods_parser.py`: former `ModDatabase`, JSON loading, `Rune`, `WeaponMod`, and `parse_modifiers`. | Provide display-oriented named upgrade facts for a supplied item ID. | `Item.Mods.Inspect`, `GetKnownUpgradeFacts`, `NormalizeUpgradeIdentifier`, and slot reads. | Source cutover complete on 2026-08-11. The module is a thin typed `Item.Mods` facade; it accepts no raw triples and owns no catalogue, parser, formula, or match verdict. Its dormant historical JSON files are not loaded by retained source. |
| M-02 | `TeamInventoryViewer.py`. | Show prefix, suffix, and inherent names in detailed rows; remove only proven modifier-name edges from a supplied rendered name. | `Item.Mods.GetUpgradeInSlot` for detailed rows and `Item.Mods.Inspect(item_id).upgrades` for conservative cleanup. | Source cutover complete. The viewer no longer imports Mark parser/catalog code or reads raw modifiers. Decoded facts prove a removable prefix, insignia, inherent edge, suffix, or rune edge; unproven text remains unchanged. |
| M-03 | `MerchantRules.py` modifier and armor-upgrade paths. | Classify applied upgrades and support UI rule selection and salvage revalidation. | `Item.Mods.Inspect`, `GetKnownUpgradeFacts`, `NormalizeUpgradeIdentifier`, and `HasUpgrade`. | Source cutover complete: no Mark parser/catalog import, `runes.json` load, raw triple comparison, or exact-signature helper remains. The picker and saved-target normalization consume typed Reforged upgrade identities. Legacy persisted weapon variants now constrain public item type and public `Item.Mods.HasUpgrade` slot/threshold facts together; their target-type metadata no longer has a divergent protection versus salvage interpretation. Merchant retains only downstream action policy. |
| F-01 | `LootEx/utility.py:104-171,572`. | Interpret requirement, damage, damage type, shield armor, and values from raw modifier argument positions. | `Item.Properties` for generic item facts and typed `Item.Mods.GetSubtype` for modifier facts. | Source cutover complete on 2026-08-10: no runtime `GetModifierValues` use remains in this utility. `Item.Properties.GetShieldArmor` was added as the narrow owner gap for its paired shield value. |
| F-02 | `LootEx/data_collection.py`, `LootEx/cache.py`, and `LootEx/models.py:ItemModifiersInformation`. | Build a local modifier-information model from raw modifiers, item type, model ID, and inscribability. | `Item.Mods` plus public item facts; no local modifier-information authority. | 2026-08-11 reachability audit: all callers are inside LootEx's deprecated inventory handler, automatic handlers, trading/salvage flow, or its inventory UI. There is no retained non-inventory caller to repoint. Retire this graph with the deprecated inventory owner; do not migrate it as a compatibility layer. |
| F-03 | `LootEx/models.py`, `data.py`, `weaponmods.py`, `weapon_rule.py`, and `filter.py`. | Catalogued rune/weapon-mod identities, roll ranges, and local raw-triple matches. | Named upgrades, slots, max status, direction-aware thresholds, and descriptions from `Item.Mods`. | 2026-08-11 reachability audit: this catalogue/matching graph is only consumed by the same deprecated LootEx inventory graph. Retire it with that owner. Static non-mod feature data needs a separate owner audit. |
| F-04 | `ItemHandling/GlobalConfigs/Rule.py:275-278`. | Compare named upgrades and a rune target type; it reaches `Item.Mods` but first obtains an `ItemSnapshot`. | Public `Item.Mods.GetSubtype` and `GetUpgrades` for a supplied item ID. | Do not port the snapshot/control-flow path. Reuse these calls only if a future non-inventory consumer has the same question. |
| F-05 | `ItemHandling/Items/item_snapshot.py:217-226`. | Cache raw modifiers, upgrades, and subtype as part of inventory control. | None in this migration. | Excluded. The later native owner supplies the item ID and reads public facts directly. |

## Public contract checked during this pass

The current public `Item.Mods` source exposes the required consumer primitives:

| Consumer need | Public surface |
|---|---|
| Named applied upgrades and physical slots | `GetUpgrades`, `GetUpgradeInSlot`, `HasUpgradeInSlot`, `GetSlot` |
| Named upgrade max status | `IsMaxed` |
| Modifier existence, subtype, or direction-aware threshold | `HasMod`, `HasAllMods`, `HasAnyMods`, `GetValues`, `GetSubtype` |
| Reforged-owned readable explanation | `GetDescriptions` |
| Shield armor at and below requirement | `Item.Properties.GetShieldArmor` |

`GetModifiers` and `GetModifierValues` also exist, but this ledger classifies
them as diagnostic/compatibility reads. They are not permitted in a retained
consumer to decode a modifier or make a rule verdict.

`Item.Mods.HasMod` rejects callable predicates. FrenkeyLib and Mark use only
declarative subtype and numeric values, with the existing direction-aware
"that value or better" semantics.

## Retained-boundary static certification

On 2026-08-10, focused production searches over the retained roots
(`TeamInventoryViewer`, `PartyQuestLog`, `MultiBoxing`, `SulfurousRunner`, and
`Polymock`) found no call or import of `GetModifiers`, `GetModifierValues`,
`ModDatabase`, `parse_modifiers`, `AutoInventoryHandler`, `ItemSnapshot`, or
`BTNodes`. The same roots contain no `open(...)`, `json.load`, `json.dump`,
`configparser`, directory-creation, or existence-probe persistence path.

No production consumer imports a Mark raw parser. A broad text search found no
retained parser/catalog import outside `Sources/marks_sources/mods_parser.py`;
that module is now an `Item.Mods`-only presentation facade rather than an
active authority.

On 2026-08-11, the remaining MerchantRules raw-modifier residue was removed:
raw triples, raw-word identifier constants, raw base-stat extraction, and
weapon-mod target parsing no longer exist in the widget. Its live item path
uses typed `Item.Mods.Inspect` effect facts and named upgrade facts only.

On 2026-08-12, the legacy persisted weapon-variant compatibility records were
audited. They carry a Reforged upgrade identity, a public item-type constraint,
and a physical slot. Merchant now applies the item type before asking
`Item.Mods.GetMatchingUpgrades` for the upgrade/slot/threshold verdict and the
typed fact required by its existing presentation/action context. This removes
the private tuple matcher, but it does not complete the rule-owner cutover:
the persisted `WeaponMod*Rule` predicate schema remains a required Factory
migration package. It must become a Factory rule/profile reference before
Merchant can be certified as a pure Reforged rules consumer.

Later on 2026-08-12, the next owner cutover landed: Merchant profile loading,
ordinary profile saves, backup restore writes, and cross-account profile writes
route old sell-protection and salvage-target upgrade records through the Factory
migration owner. Weapon variants and armor rune/insignia identities become
stable global Factory-rule IDs; an unsupported record disables its affected
destructive rule and records its source fingerprint/reason. A global Factory
bind delay leaves the stored profile untouched for retry while its in-memory
action rule stays disabled. Factory references, once present, are the live
sell/salvage verdict; `Item.Mods` provides typed slot context only after that
verdict. The legacy editor controls are read-only conversion evidence, not a
second authoring or matching path.

## Stage 0 completion and remaining evidence

Completed in this source pass:

1. Recorded direct widget roots, Mark consumers, and the core-to-Frenkey
   `AutoInventoryHandler` coupling.
2. Classified raw modifier consumers versus excluded inventory-control paths.
3. Mapped retained item-mod questions to existing public `Item.Mods` calls.

No further Stage 1 input is required unless a consumer or the parity report
identifies a concrete missing public capability. Record that capability as an
`Item.Mods` owner gap; do not add a FrenkeyLib or Mark workaround.

## Retained persistence reachability audit

The current source audit records these retained feature roots and persistence
owners. Personal behaviour and window state are account-scoped unless the
feature has an explicit multibox/shared-machine reason to be global:

| Retained feature | Reachable root | Persistence owner | Disposition |
|---|---|---|---|
| Party Quest Log | `Widgets/Guild Wars/PartyQuestLog.py` (`main`, `configure`) | Account `Settings("Widgets/Guild Wars/PartyQuestLog.ini")` | Migrated. The previous global and `Widgets/Config` values transfer once only into missing account keys; no feature file I/O remains. Its quest-log and configuration-window geometry use separate scalar sections with `NoSavedSettings`; WidgetManager owns configuration visibility. |
| MultiBoxing | `Widgets/Guild Wars/MultiBoxing.py` | Global `Settings` for deliberately shared policy/account ordering; account `Settings` view for Configure window geometry; one global `JsonFactory("MultiBoxing/Layouts.json")` repository for layouts | Migrated. Stable layout IDs and display names share one document; the initial load imports old jailed name-path records only from the prior index, rejects path-shaped names, and peer clients reload the same owner before merging. The personal window rectangle imports once from missing global legacy keys without overwriting account values. |
| Sulfurous Runner | `Widgets/Automation/Bots/Runners/Sulfurous Runner.py` | Account `Settings("Widgets/Automation/Bots/Runners/Sulfurous Runner.ini")` | Migrated. The previous global and `Widgets/Config` values transfer once only when absent; malformed persisted colours fall back to safe defaults instead of failing widget startup. |
| Polymock | `Widgets/Automation/Bots/Miscellaneous/Polymock.py` | Account `Settings("Widgets/Automation/Bots/Miscellaneous/Polymock.ini")` | Migrated. Prior global window geometry transfers once without replacing an existing account value; WidgetManager owns visibility. |
| Team Inventory Viewer | `Widgets/Guild Wars/Items & Loot/TeamInventoryViewer.py` | Global `JsonFactory` documents for deliberately shared account/inventory records; account `Settings("Widgets/Guild Wars/Items & Loot/TeamInventoryViewer.ini")` for main-window geometry | Migrated persistence split. The shared cache remains structured JsonFactory data; personal position, size, and collapse state transfer once from global Settings and no longer use Dear ImGui's INI persistence. |
| LootEx | `Widgets/Guild Wars/Items & Loot/LootEx.py` | Account `Settings` for geometry/page state; account `JsonFactory` for Factory-profile selection and conversion audit; named global JsonFactory catalogues | Retained presentation consumer. Factory profiles/rules and verdicts remain Factory-owned; static catalogues are jail-seeded and never read from source files at runtime. |
| Merchant Rules | `Widgets/Guild Wars/Items & Loot/MerchantRules.py` (`main`) | Account `Settings` for main-window and floating-icon geometry; account/global JsonFactory profile documents as defined by the existing profile owner | Retained consumer. The floating icon owns visibility only; account profiles are local, while explicitly shared profiles remain global and require the global merge/reload acceptance gate. |

The remaining direct `open`, `json.load`, `json.dump`, and catalog paths are
under `LootEx`, `ItemHandling`, or `Drafts`. `LootEx` and `ItemHandling` are
the deprecated inventory graph; `Drafts` is not a reachable feature root. They
must not be copied into a retained feature while their retirement is pending.

## Stage 1 decoder evidence

### Offline result

The two existing owner validators are injected-client widgets, not fixture-based
tests:

- `Widgets/Coding/Debug/Py4GW/Item Mods Playground.py` latches a hovered item,
  compares game tooltip text against `Item.Mods.GetDescriptions`, displays
  upgrades and slots, and exercises ALL/ANY and threshold helpers.
- `Widgets/Coding/Debug/Py4GW/Mod Parity Scan.py` scans inventory, equipment,
  and storage, then writes game-versus-Reforged results to
  `docs/items/modifiers/generated/mod-parity-scan.txt`.

On 2026-08-10, the user directed the migration to treat the current decoder as
authoritative and add only what is missing. The Playground and parity scan are
diagnostic tools, not migration gates or a request for separate smoke tests.
They are consulted only when their output identifies a concrete owner gap.

`npx.cmd --no-install pyright Py4GWCoreLib\\Item.py` was run on 2026-08-10. It
reported two existing `reportAttributeAccessIssue` diagnostics at lines 241 and
261, where `GetItemIdFromModelID` and `GetItemByAgentID` access `item.item_id`
on a value typed as `dict[str, Any]`. Both are outside `Item.Mods`; no
`Item.Mods` diagnostic was reported. That historical baseline is superseded:
on 2026-08-12, `pyright.cmd Py4GWCoreLib\\Item.py` completed with zero
diagnostics after the current Item owner changes.

### Current parity result

The current `mod-parity-scan.txt` was generated on 2026-08-10 at 13:47 and
scanned 271 items. It contains zero `?UNKNOWN` and zero `(UNHANDLED)` raw
decoder statuses. Its structural rows are intentionally non-display carrier
words. The report is a readable GAME-versus-OURS dump rather than an automated
mismatch verdict; sampled weapon and shield facts agree with GAME text despite
display-order differences. It identifies no concrete decoder gap.

### Source-proven owner addition

The historical 2026-07-17 parity export marked generic profession-rune carrier
IDs `0x00AF`, `0x00BB`, `0x00C0`, and `0x013D` as unknown in `GetRawDump`.
Current source inspection showed that `GetUpgrades` already resolves the named
rune and its suffix slot from the accompanying `AttributeRune` word. The
missing information was only the carrier's diagnostic name.

`Py4GWCoreLib/mods_core.py` now derives the names of all 30 generic
profession-rune carriers from the existing `ItemUpgrade.UpgradeRune` and
`ItemUpgradeId` owner data. It changes `GetRawDump` only; it does not alter
the established named-rune/slot result that consumers receive through
`GetUpgrades`.

Focused synthetic verification constructed a Superior Mesmer rune carrier plus
its Fast Casting attribute word and proved both results: `GetUpgrades` still
returns `MesmerRuneOfSuperiorFastCasting` in the suffix slot, while `GetRawDump`
now reports `SuperiorMesmerRune` rather than an unknown carrier. The same table
contains 30 generic profession-rune carrier IDs. `py_compile` and focused
Pyright on `mods_core.py` passed with zero diagnostics.

## Static checks used

- Searched Python sources for direct FrenkeyLib roots, Mark parser imports,
  raw modifier reads, parser/catalog symbols, and `AutoInventoryHandler`
  coupling.
- Inspected the current public `Item.Mods` methods in `Py4GWCoreLib/Item.py`.
- Ran focused Pyright as recorded above. The historical two-diagnostic
  baseline is superseded by the 2026-08-12 zero-diagnostic `Item.py` run.

The Stage 1 owner addition changes only raw diagnostics.

## Stage 2 Team Inventory Viewer source cutover

On 2026-08-10, `TeamInventoryViewer.py` was repointed to the public
`Item.Mods.GetUpgradeInSlot` surface for the prefix, suffix, and inherent
labels it composes into a display name. It no longer reads modifier triples,
loads `mods_data`, imports `mods_parser`, or persists a raw-modifier hash.
The hash store had no reader, so it was removed rather than replaced with a
second representation of the same item state.

The Item.Mods inherent-slot query is intentionally retained even though the
current source slot table has no listed inherent mapping. The viewer is a
consumer, not a classifier: if the owning platform reports that slot, the
existing display position receives it; otherwise it presents no inherent
parenthetical. No raw fallback is allowed.

`python -m py_compile` and focused strict Pyright on the widget completed with
zero diagnostics.

On 2026-08-12, its final copied modifier display catalogue was removed as
well. Base-name cleanup now accepts the supplied item ID and uses only
`Item.Mods.Inspect(item_id).upgrades`: exact decoded prefix/insignia/inherent
facts may remove a leading name edge, while suffix/rune facts may remove a
trailing edge. If inspection is unavailable or the rendered name does not
match a decoded fact, the name is preserved unchanged. This deliberately
replaces guessing with a harmless conservative result. The focused Team
Inventory verifier covers prefix/suffix, possessive insignia, rune suffix, and
unavailable-decoder behavior and rejects reintroduction of the local catalogue.

## Stage 3 LootEx utility source cutover

On 2026-08-10, `LootEx/utility.py` was repointed from runtime raw modifier
arguments to `Item.Properties.GetRequirement`, `Item.Properties.GetDamage`,
`Item.Mods.GetSubtype`, and `Item.Properties.GetShieldArmor`. The first three
were existing public calls. `GetShieldArmor` is the sole source-proven owner
addition: it returns the shield's above- and below-requirement values as the
former helper contract requires, without exposing raw modifier arguments to
FrenkeyLib.

`python -m py_compile` passed for the edited core and utility modules. Focused
Pyright reported five existing errors outside the edits: two `dict[str, Any]`
attribute reads in `Item.py` (lines 241 and 261), and three analogous item/slot
reads in `LootEx/utility.py` (lines 746-747). The converted methods introduced
no diagnostics. Live feature evidence remains deferred to the retained
non-inventory LootEx slice.

## Remaining raw-owner disposition

The final 2026-08-10 source reachability pass found no retained direct Frenkey
widget root importing `LootEx`. The remaining `ItemModifiersInformation`,
rune/weapon-mod catalog matching, and `get_target_item_type_from_mod` callers
flow through LootEx collection, filtering, storage/salvage, or Merchant Rules
inventory planning. They remain explicitly excluded legacy inventory owners.

Removing or deprecating those modules is a later System Settings rule-policy
cutover decision. This migration does not give them a new raw-parser wrapper,
does not keep them as a compatibility dependency of a retained consumer, and
does not delete them prematurely.

## Native inventory cutover prerequisites

The 2026-08-10 retirement scan established these required replacement points:

1. `InventoryPlus` must stop invoking `AutoInventoryHandler` for its manual
   identify and salvage commands before that handler is deprecated.
2. LootEx must stop assigning its `LootExAutoInventoryHandler` into the core
   singleton before its inventory module can be detached.
3. The System Settings inventory controller now provides explicit native
   identify, salvage, and storage requests. A later rule-policy integration
   must consume public Reforged verdicts and submit only item IDs; it must not
   restore a Python compatibility inventory handler.
4. Only after those roots are cut over may the `ItemHandling` snapshot,
   behavior-tree, handler, and raw-model graph be removed or deprecated.

## System Settings execution cutover

On 2026-08-11, `system_settings/inventory` gained the first native execution
contract. `InventorySettingsController.request_identify(item_ids)`,
`request_salvage_batch(item_ids, salvage_kit_id=None)`, and
`request_store(item_id)` accept explicit current inventory IDs and route only
through native `PyInventory` calls. Identify advances after polling the public
identified state. Salvage advances only after an item is consumed or its stack
quantity decreases; a materials-salvage confirmation requires a separate
explicit request. The System Settings UI accepts a temporary comma/space
separated item-ID list and does not enumerate unidentified candidates. The
controller therefore executes supplied IDs but does not make a rule decision,
write operation settings, or run on inventory change.

The manual identify and salvage helpers in `InventoryPlus.py` now submit their
selected explicit item IDs (and an optional selected salvage kit) to System
Settings; the widget no longer calls `AutoInventoryHandler().IdentifyItems` or
`AutoInventoryHandler().SalvageItems`. The old direct salvage coroutine,
including automatic dialog handling and retired transaction helpers, was
removed rather than retained as a fallback. InventoryPlus also no longer
imports, instantiates, configures, or schedules the deprecated automatic
handler; future policy work belongs under Reforged ownership.

`botting_src/helpers_src/Items.py::auto_identify_items` selects its own current
candidates through the existing botting routine, submits those explicit IDs to
the System Settings controller, and yields until that controller observes
completion. It no longer disables, invokes, then restores the deprecated
handler singleton. Salvage, deposit, and combined botting
commands remain deferred because their legacy behavior carries selection and
confirmation policy that has not yet been moved to the Reforged owner.

LootEx `InventoryHandler.Start()` and `Stop()` no longer assign either
`MerchantHandler._instance` or `AutoInventoryHandler._instance`. The legacy
graph can still start and stop its own quarantined work, but it cannot replace
the Reforged singleton owners. This is an ownership cut, not an attempt to
migrate its inventory policy.

## LootEx runtime entry-point recovery

Runtime evidence on 2026-08-11 showed that selecting
`Sources/frenkeyLib/LootEx/gui.py` fails with "No main()/update()/draw()
function found." Legacy history confirms that `gui.py` has only `class UI` in
both revisions where LootEx entered the repository; no tracked LootEx-named
widget, module callback, or Frenkey launcher exists. The existing
`Py4GW_widget_manager.py` is the authoritative in-client launcher and only
discovers Python files inside marked `Widgets/` folders.

`Widgets/Guild Wars/Items & Loot/LootEx.py` is therefore the explicit entry
point. It supplies `configure()` for WidgetManager and `main()` for direct
selection. Its recovered surface is deliberately limited to jailed profile
configuration: it reads window geometry through account-scoped `Settings`,
reads Factory-profile selection through account-scoped `JsonFactory`, and
saves the selected character/profile mapping without calling
`Settings.SetProfile()`, which still starts the quarantined legacy handlers.
The Reforged Loot Filter Factory owns all profile/rule authoring and matching;
LootEx renders those records read-only and previews an explicit item ID. It
does not scan bags.

The historical `gui.py` is not a live entry point. It depends on raw source
catalogues and exposes legacy inventory controls, so importing it would merely
reconnect the ownership paths that this migration removes. It remains evidence
for later presentation work; it is not a configuration surface to preserve.

`python -m py_compile` and focused Pyright passed for the entry point. Full-file
Pyright over the historical `gui.py` reports 93 pre-existing legacy diagnostics,
mostly PyImGui call-shape errors. Live injected-client rendering of the new
entry point remains unverified.

## Mark parser next owner gap

`Widgets/Guild Wars/Items & Loot/MerchantRules.py` no longer imports
`Sources.marks_sources.mods_parser` or loads its `MOD_DB` catalog. Weapon and
loose-rune classification use `Item.Mods.Inspect`; the widget's picker catalog
uses `GetKnownUpgradeFacts`, with stable generic identities rather than
parser-defined item-type variants or variable ranges. Armor snapshots, target
selection, component reservation, and extraction revalidation now use the same
typed Reforged identities. The decoder is not the gap: Reforged already decodes
the live modifier words. The owner surface supplies stable upgrade identity,
slot, subtype, and directional threshold metadata without exporting raw triples
or parser-owned catalog identifiers. That owner surface now exists:
`Item.Mods.Inspect(item_id)` returns immutable effect and installed-upgrade
facts; `GetKnownUpgradeFacts()` supplies the stable Reforged catalog; and
`NormalizeUpgradeIdentifier()` resolves an old display-style persisted name to
its stable Reforged identity.

Merchant Rules does not route through the raw `Item.Mods.GetModifiers`
compatibility reader. The old private raw helper was deleted during this
cutover. Merchant Rules consumes the typed result and must not add another
decoder, JSON catalog, or execution owner.

On 2026-08-11, the remaining `runes.json` merchant-buy and model-enrichment
loaders were removed as well. The rule picker is now built directly from
`GetKnownUpgradeFacts`; it has one explicit "All Reforged upgrades" group
rather than catalogue-invented profession, price, rarity, or model metadata.
Live trader stock is matched through its item IDs and typed Reforged upgrade
identities. `NormalizeUpgradeIdentifier` retains saved display-style targets
without restoring the legacy catalogue.

No `Gw` or `Gw64` process was available during this scan, so the migrated
viewer and feature smoke checks remain deferred.
