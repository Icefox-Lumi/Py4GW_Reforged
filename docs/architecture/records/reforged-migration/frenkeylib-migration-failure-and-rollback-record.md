# FrenkeyLib Migration Failure and Rollback Record

Status: current failure record; rollback not yet executed
Scope: the uncommitted FrenkeyLib, LootEx, Merchant Rules, Mark, Factory,
settings, jailed-data, and UI migration worktree
Authority: the current worktree, repository base `01cfb912`, the legacy
`C:\Users\Apo\Py4GW_python_files\Sources\frenkeyLib` tree, and the user's
stated product intent

## Decision

The migration is rejected. It changed the contracts and product model of
FrenkeyLib instead of porting its intended behaviour to Reforged.

No later migration record may describe this worktree as a completed or
accepted cutover. Passing source checks prove only that code satisfies the
newly imposed source contracts; they do not prove those contracts preserve
FrenkeyLib's intended rules, profiles, workflows, or UI.

The next engineering action is evidence preservation and a staged rollback
design. It is not further Factory conversion, ImGui cleanup, or live-client
acceptance of the rejected design.

The detailed causal analysis is in
`frenkeylib-decision-autopsy.md`.

## What was supposed to be migrated

The intended outcome was a Reforged-compatible FrenkeyLib, not a replacement
product built around the Loot Filter Factory.

Reforged may provide infrastructure and facts:

- `Settings` and `JsonFactory` as persistence mechanisms;
- `Item.Mods` and related public APIs as decoded item facts;
- the existing Factory where a caller actually needs a Factory rule.

FrenkeyLib was still expected to retain its own product-level profile,
workflow, rule composition, and UI contracts. In particular, a loot filter is
not an item-mod filter and must not become the global verdict that rules every
Frenkey action or profile. Item-mod criteria are one specialized input to an
existing Frenkey rule system; they are not a replacement for its action rules,
skin rules, filters, per-item configuration, rune/weapon choices, or user
workflow.

The future System Settings explicit-ID execution work is a separate program.
It must not be used to justify changing FrenkeyLib's product semantics during
this rollback.

## Failure mechanism

### 1. Ownership was extended into product semantics

The migration correctly identified a need to avoid duplicated raw modifier
decoding. It then extended that fact-owner rule into an incorrect requirement:
Factory had to own every rule verdict, and consumers could retain only an
action after Factory matched.

Current evidence is explicit in
`Widgets/Guild Wars/Items & Loot/MerchantRules.py`:

- `protected_factory_rule_ids` and `target_factory_rule_ids` were added to
  Merchant profile rule records;
- `_migrate_profile_upgrade_predicates` rewrites saved Merchant data through
  the global Loot Filter Factory;
- `_draw_factory_rule_reference_editor` tells users that Factory owns the
  verdict and directs authoring to System Settings;
- unavailable or deferred Factory conversion disables a destructive rule.

This is not an adapter from Reforged facts to a Frenkey rule. It transfers the
meaning and availability of a Frenkey rule to another product's rule store.

### 2. Loot filters and item-mod rules were conflated

Legacy `LootEx/profile.py` demonstrates separate rule families in one profile:

- `filters`: broad item/action policy (`Filter.action`, item types, rarity,
  materials, stack and vendor-value conditions);
- `skin_rules`: skin/model action rules;
- `weapon_rules`: weapon-specific rules;
- `runes` and `weapon_mods`: specialized upgrade decisions;
- blacklist, rare weapon, kit, storage, crafting, Nick, and profile workflow
  state.

Legacy `LootEx/filter.py` maps its filter conditions to action decisions such
as stash, sell, salvage, hold, and loot. This proves a LootEx filter was not
merely a modifier predicate.

The rejected migration instead made the Loot Filter Factory the canonical
definition and matcher for profile rule references, including Merchant
upgrade-protection and salvage-target paths. The result makes unrelated
Frenkey profile concerns flow through a system designed for filter matching.
That is the central semantic regression.

### 3. Profile contracts were replaced rather than persisted

The legacy profile is a composed Frenkey configuration. The current worktree
adds a new active `Widgets/Guild Wars/Items & Loot/LootEx.py` presentation
surface plus Factory-profile selection, conversion audits, and separate
account/global Factory-linked documents. Merchant's existing profiles also
gain Factory reference IDs and conversion metadata.

Those changes turn a profile into a collection of references to external
Factory records rather than preserving it as the user's Frenkey configuration.
The UI was then changed to author or select those references. Consequently the
new UI can be structurally correct according to its tests while no longer
expressing the profile model users had.

### 4. UI migration followed the new model instead of the existing workflow

Merchant Rules changed by approximately 2,618 added and 3,851 deleted lines
in the current worktree. The active editor now contains Factory-reference
controls and conversion notices where legacy upgrade controls and profile
editing workflows previously existed. The new LootEx widget is a reduced
presentation/preview surface rather than a recovered rendering of the legacy
feature workflow.

This was compounded by treating old UI modules as historical solely because
they lacked a direct script callback, instead of first recovering the real
launcher and preserving the user-visible feature contract. Resolving an entry
point is necessary; replacing the UI while doing so was not.

### 5. Verification enforced the wrong acceptance criteria

The new verifier set explicitly guards invariants such as:

- no local Merchant verdict after Factory conversion;
- no legacy predicate authoring in Merchant;
- Factory-only profile conversion;
- no active historical LootEx execution;
- a small Factory-profile/preview LootEx surface.

These tests pass because the current source follows the new architecture.
They cannot establish legacy behaviour parity or user workflow parity. A
green verifier that prohibits the desired old workflow is evidence of the
wrong specification being encoded, not evidence that the migration succeeded.

## Worktree evidence at the point of rejection

The current repository `HEAD` is `01cfb912` (`Fix global loot settings
migration regression`). The migration work is uncommitted and interleaved with
other user changes. At the time this record was created, tracked changes show
about 8,072 insertions and 7,592 deletions across 41 files, plus untracked
Factory, LootEx, JSON-default, tooling, and migration-plan files.

Important artifacts are:

| Artifact group | Current state | Rollback disposition |
|---|---|---|
| `Widgets/Guild Wars/Items & Loot/LootEx.py` and `Sources/frenkeyLib/LootEx/{catalogue_store,migration,profile_store}.py` | New Factory-facing presentation/conversion surface. | Remove or replace only after the recovered Frenkey launcher and profile/UI contract are specified. |
| `Widgets/Guild Wars/Items & Loot/MerchantRules.py` | Large semantic/UI rewrite; Factory IDs, conversion metadata, fail-closed Factory paths, and Factory-reference editors were added. | Primary rollback target. Recover existing Merchant profile and rule semantics before any persistence adaptation. |
| `Py4GWCoreLib/py4gwcorelib_src/system_settings/loot_filter_factory/{model,matcher,store,config_ui}.py` and `merchant_*_migration.py` | Factory was expanded and coupled to Merchant conversion. | Remove Merchant coupling first; review each generic Factory improvement independently. Do not let it remain a shadow owner of Frenkey rules. |
| `Sources/marks_sources/mods_parser.py`, `Py4GWCoreLib/Item.py`, `mods_core.py` | Raw parser/callers were changed toward `Item.Mods`. | Quarantine for a capability-by-capability review. `Item.Mods` fact decoding may remain useful; a replacement parser/UI contract must not be assumed. |
| `Sources/frenkeyLib/LootEx/{gui,profile,settings,instance_manager,inventory_handling}.py` | Partially edited while simultaneously labelled historical/excluded. | Restore from the base and legacy comparison before deciding their Reforged port. Do not revive handler hijacking as an accidental side effect. |
| `json/Defaults`, jailed catalogues, and Factory/Merchant profile documents | New persistence shape created to serve the rejected Factory model. | Preserve as evidence; do not seed or convert more user data. Re-evaluate per real feature schema. |
| `MultiBoxing`, Party Quest Log, Sulfurous Runner, Polymock, Team Inventory, `ui_scope`, and `FloatingIcon` changes | Persistence/UI changes occurred in the same worktree but are not all evidence of the Factory semantic mistake. | Review separately against their own legacy behaviour. They are neither accepted automatically nor automatically reset. |
| System Settings explicit-ID controller and Inventory+ changes | Related future execution/deprecation work, explicitly separate from the Frenkey product model. | Keep out of the immediate Frenkey rollback unless a dependency review proves contamination. |

## Historical record correction

The following documents are retained as evidence of what was attempted, but
their steering conclusions are superseded by this record:

- `frenkeylib-complete-cutover-plan.md`;
- `frenkeylib-layered-migration-plan.md`;
- `frenkeylib-stage-0-cutover-ledger.md`.

Their assertions that Factory should own Frenkey verdicts, that legacy authoring
should be removed, or that the reduced LootEx surface represents completion
are rejected. They must be read as a chronology of the failed approach, not as
instructions for future implementation.

## Preservation rules before rollback

1. Do not run `git reset --hard`, `git checkout -- .`, `git restore .`, or
   `git clean`. The worktree contains unrelated and uncommitted user changes.
2. Freeze migration-directed writes: no further profile conversion, Factory
   registration, JSON seeding, UI deletion, or verifier expansion based on the
   rejected ownership premise.
3. Before any edits, capture a reversible patch and an exact file manifest of
   the current worktree. The capture must include untracked files; an ordinary
   diff does not preserve them.
4. Preserve both comparison sources: repository base `01cfb912` and
   `C:\Users\Apo\Py4GW_python_files\Sources\frenkeyLib`. Neither source is
   automatically a runnable Reforged result, but together they establish the
   before-state and intended legacy behavior.
5. Do not run saved-profile converters against live user documents during
   recovery. Existing converted data needs a reversible, separately documented
   import/export decision.

## Rollback sequence to design next

This is a recovery order, not permission for an automatic reset.

1. Create a frozen recovery snapshot and classify every changed/untracked file
   as unrelated, infrastructure, semantic migration, UI migration, or data
   conversion.
2. Reconstruct the real LootEx launch and lifecycle path from legacy source
   and existing Reforged widget conventions. Define the user-visible screens
   and profile operations before writing an adapter.
3. Recover the Frenkey profile schema first. Keep broad action filters,
   item/skin rules, and specialized mod rules as distinct domains. Replace only
   their raw fact reads with Reforged APIs where a concrete API gap exists.
4. Detach Merchant's Factory IDs, migration metadata, Factory-only fail-closed
   paths, and Factory-reference editor from Merchant profiles. Restore Merchant
   rule authoring and evaluation semantics; then adapt its item facts through
   `Item.Mods` without transferring rule ownership.
5. Review `Settings`/`JsonFactory` as persistence adapters only. A jail may be
   retained if it serializes the original feature schema without changing its
   meaning; it must not dictate profile composition or window workflow.
6. Rebuild the UI from recovered workflows, not from the Factory editor. Test
   visible screens and profile operations against legacy behavior before
   applying structural ImGui cleanup.
7. Decide separately whether any native persistence hardening, Item.Mods fact
   additions, explicit-ID System Settings work, or non-LootEx widget fixes are
   retained. Each requires an independent rationale and test, not association
   with this failed migration.

## Acceptance criteria for a replacement migration

A new migration proposal is acceptable only if it proves all of the following
before a broad code rewrite:

- A written domain map distinguishes action filters, mod/upgrade predicates,
  profile composition, item facts, and execution.
- The Frenkey profile remains a Frenkey-owned schema; external systems may
  supply facts or optional services but cannot silently replace its rule model.
- Each legacy screen/workflow has a parity inventory and an identified Reforged
  entry point.
- `Settings` and `JsonFactory` changes preserve data meaning; no conversion is
  accepted merely because it makes a document fit another system's schema.
- Item-mod decoding changes are limited to concrete public capability gaps
  identified by the mod tools or a reproducible user scenario.
- Tests include profile and UI behavior parity, not only static prohibition of
  legacy APIs or success of a new owner model.

Until then, this migration remains failed and no source-verification result may
be reported as migration completion.
