# FrenkeyLib Rollback File Manifest

Status: current preservation manifest; no rollback action authorized
Scope: files changed or created in the rejected migration worktree as observed
on 2026-08-12
Authority: `git status --short --untracked-files=all` in `Py4GW_Reforged`,
the observed status/stat of `Py4GW_Reforged_Native`, and the current source

Read [the failure and rollback record](frenkeylib-migration-failure-and-rollback-record.md)
first. This is an evidence index, not a list of files safe to reset.

## Preservation baseline

| Repository | Observed base | Worktree condition |
|---|---|---|
| `Py4GW_Reforged` | `01cfb912` | Large mixed dirty worktree: 41 tracked modifications and untracked source, data, documents, and tests. |
| `Py4GW_Reforged_Native` | `a45b4c7` | Separate dirty worktree: settings/JSON changes plus UI, trade, and rebuilt-DLL changes. |

Neither tree may be reset as a unit. A recovery snapshot must include
untracked files and the Native DLL before any classification or rollback edit.

## Python/Reforged manifest

### Semantic Factory, profile, and LootEx replacement paths

| Path | State | Recovery classification |
|---|---|---|
| `Widgets/Guild Wars/Items & Loot/MerchantRules.py` | modified | Primary semantic and UI rollback target. |
| `Widgets/Guild Wars/Items & Loot/LootEx.py` | untracked | New replacement surface; do not treat as legacy parity. |
| `Py4GWCoreLib/py4gwcorelib_src/system_settings/loot_filter_factory/__init__.py` | modified | Factory coupling review. |
| `Py4GWCoreLib/py4gwcorelib_src/system_settings/loot_filter_factory/{config_ui,matcher,model,store}.py` | modified | Factory coupling review. |
| `Py4GWCoreLib/py4gwcorelib_src/system_settings/loot_filter_factory/{merchant_profile_migration,merchant_upgrade_migration}.py` | untracked | Direct Merchant coupling rollback target. |
| `Py4GWCoreLib/py4gwcorelib_src/system_settings/merchant_rules_catalogue.py` | untracked | New Merchant catalogue adapter; review with profile/UI recovery. |
| `Sources/frenkeyLib/LootEx/{catalogue_store,migration,profile_store}.py` | untracked | New migration adapter layer; preserve, then remove/replace only with the recovered schema. |
| `Sources/frenkeyLib/LootEx/{gui,instance_manager,inventory_handling,profile,settings}.py` | modified | Compare against base and legacy before porting or restoring. |
| `json/Defaults/Widgets/Guild Wars/Items & Loot/LootEx/catalogue/{items,materials,nick_cycle,scraped_items}.json` | untracked | New Factory/jail-era seed data; preserve as evidence, do not seed more data. |
| `json/Defaults/Widgets/Guild Wars/Items & Loot/MerchantRules/catalogue/{curated,drop_data}.json` | untracked | Same. |
| `json/Defaults/Widgets/LootManager/{modelid_drop_data,Nick_cycles}.json` | untracked | Same; classify separately from Frenkey profile recovery. |

### Item facts, parser, and automation boundary changes

| Path | State | Recovery classification |
|---|---|---|
| `Py4GWCoreLib/Item.py` | modified | Review public fact additions individually; do not retain a consumer-contract rewrite by association. |
| `Py4GWCoreLib/mods_core.py` | modified | Decoder/fact review against concrete mod capability evidence. |
| `Sources/marks_sources/mods_parser.py` | modified | Restore or adapt only after Mark's actual caller/UI contract is recovered. |
| `Py4GWCoreLib/botting_src/helpers_src/Items.py` | modified | Separate explicit-ID/System Settings boundary review. |
| `Py4GWCoreLib/py4gwcorelib_src/system_settings/inventory/{config_ui,controller}.py` | modified | Separate future System Settings execution work; not proof of a Frenkey rollback target. |
| `Widgets/Guild Wars/Items & Loot/InventoryPlus.py` | modified | Separate Inventory+/System Settings work; inspect dependencies before rollback. |
| `Widgets/System/Messaging.py` | modified | Check whether only historical LootEx messaging was removed/reserved. |

### Retained-feature and UI infrastructure changes requiring independent review

| Paths | State | Recovery classification |
|---|---|---|
| `Py4GWCoreLib/ImGui_src/ImGuisrc.py`, `Py4GWCoreLib/modular/ui_scope.py` | modified | Shared UI infrastructure; keep/revert only after its own caller and runtime review. |
| `Widgets/Guild Wars/Items & Loot/TeamInventoryViewer.py` | modified | Independent widget migration review. |
| `Widgets/Guild Wars/MultiBoxing.py`, `Sources/frenkeyLib/MultiBoxing/{gui,settings}.py`, `Py4GWCoreLib/enums_src/Multiboxing_enums.py` | modified | Independent multibox persistence/UI review. |
| `Widgets/Guild Wars/PartyQuestLog.py`, `Sources/frenkeyLib/PartyQuestLog/{settings,ui}.py` | modified | Independent UI/state review. |
| `Widgets/Automation/Bots/Miscellaneous/Polymock.py`, `Sources/frenkeyLib/Polymock/gui.py` | modified | Independent UI/state review. |
| `Widgets/Automation/Bots/Runners/Sulfurous Runner.py`, `Sources/frenkeyLib/SulfurousRunner/{settings,ui}.py` | modified | Independent UI/state review. |
| `.gitignore` | modified | Unrelated until proven otherwise. |

### Documentation and verification produced by the rejected approach

| Paths | State | Recovery classification |
|---|---|---|
| `docs/architecture/records/reforged-migration/{frenkeylib-complete-cutover-plan,frenkeylib-layered-migration-plan,frenkeylib-stage-0-cutover-ledger}.md` | modified/untracked | Preserve as chronology; their forward directions are superseded. |
| `docs/architecture/records/reforged-migration/{frenkeylib-migration-failure-and-rollback-record,frenkeylib-rollback-file-manifest}.md` | untracked | Preserve; these are the current recovery records. |
| `docs/items/modifiers/item-mods-api.md`, `docs/ui/imgui/floating-icon-class.md` | modified | Review as independent API documentation; do not let rejected architecture claims remain current. |
| `tools/seed_{lootex_catalogue_defaults,merchant_rules_catalogue_defaults}.py` | untracked | Do not run while recovery is frozen. |
| `tools/verify_{catalogue_defaults,frenkey_account_settings_bind,frenkey_migration_boundary,frenkey_settings_scope_migration,item_mods_directional_input,loot_filter_factory_directional_grammar,loot_filter_factory_item_type_matching,loot_filter_factory_migration_store,lootex_catalogue_store,lootex_migration_converter,lootex_profile_store,lootex_widget_lifecycle,marks_mods_facade,merchant_legacy_predicate_guard,merchant_preview_child_scope,merchant_profile_factory_migration,merchant_rules_catalogue,merchant_upgrade_migration,merchant_window_lifecycle,multibox_layout_repository,multibox_region_scope,multibox_window_settings_bind,multiboxing_widget_lifecycle,native_json_factory_seeding,native_settings_global_merge,party_quest_log_ui_scopes,polymock_window_lifecycle,reforged_persistence_facades,sulfurous_runner_widget_lifecycle,system_settings_explicit_item_operations,team_inventory_window_lifecycle,ui_scope_contract}.py` | untracked | Preserve as evidence of the rejected acceptance model. Disable/remove only during a separately reviewed rollback, never as a cleanup shortcut. |

## Native sibling manifest

`Py4GW_Reforged_Native` is outside this repository's worktree. It must receive
its own snapshot before its files are touched.

| Paths | State | Recovery classification |
|---|---|---|
| `include/json/json_factory.h`, `src/json/json_factory.cpp` | modified | Persistence owner changes; separate semantic and concurrency review. |
| `include/settings/settings.h`, `src/settings/{settings,settings_methods}.cpp` | modified | Persistence owner changes; separate semantic and concurrency review. |
| `include/GW/ui/ui.h`, `src/GW/ui/{ui,ui_bindings,ui_methods}.cpp` | modified | UI/runtime changes; do not assume they are Frenkey-only. |
| `include/GW/trade/trade.h`, `src/GW/trade/{trade,trade_bindings,trade_methods}.cpp` | modified | Trade changes; presume unrelated until dependency review proves otherwise. |
| `Py4GW.dll` | modified binary | Preserve the exact binary and rebuild provenance before changing native source. |

## Recovery handling rules

1. A file marked “primary rollback target” still needs a path-by-path recovery
   patch. It is not permission for a broad Git restore.
2. A file marked “independent review” must have its pre-migration behavior and
   callers examined before keeping or reverting it.
3. A file marked “preserve as evidence” must not be deleted before a snapshot
   is captured and a successor record explains its disposition.
4. The untracked files in this manifest are particularly vulnerable: normal
   `git diff` output does not save them.
