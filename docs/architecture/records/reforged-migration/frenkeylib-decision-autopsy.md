# FrenkeyLib Migration Decision Autopsy

Status: current analysis of a rejected migration
Scope: decisions made in the uncommitted FrenkeyLib/Reforged migration
Authority: current worktree, base `01cfb912`, legacy FrenkeyLib source, user
direction during the migration, and the failure/rollback records

Related records:

- [failure and rollback record](frenkeylib-migration-failure-and-rollback-record.md)
- [rollback file manifest](frenkeylib-rollback-file-manifest.md)

## Purpose

This records the decisions that changed FrenkeyLib into a different product.
For each decision it gives the adopted premise, why it seemed plausible, the
contradictory evidence, source consequence, verification failure, and a rule
that prevents repetition.

The root error was: **ownership of decoded Reforged facts was mistaken for
ownership of FrenkeyLib's profiles, rules, workflows, and UI.**

## Domain map that should have controlled the migration

| Domain | Correct owner | Allowed role | Forbidden substitution |
|---|---|---|---|
| Item fact | Reforged `Item.Mods` / item APIs | Return a supplied item's decoded facts. | A Frenkey action or profile decision. |
| Broad loot/action filter | Frenkey profile/filter model | Choose feature action by category, rarity, model, material, stack, value, and profile state. | An item-mod or universal Factory rule. |
| Mod, weapon, rune predicate | Frenkey rule model using Reforged facts | Apply specialized feature rule semantics. | The whole profile or an external Factory reference. |
| Profile | FrenkeyLib | Compose filters, rules, kits, storage/crafting state, and user choices. | A collection of external Factory IDs. |
| Persistence | `Settings` / `JsonFactory` | Store the same scalar/schema safely. | Change data meaning or feature ownership. |
| UI | FrenkeyLib workflow rendered in Reforged PyImGui | Preserve configuration and profile operations. | A smaller Factory editor/preview. |
| Later execution | System Settings | Execute explicitly supplied IDs. | Candidate selection, profile semantics, or auto handling. |

## Evidence that was available

Legacy `C:\Users\Apo\Py4GW_python_files\Sources\frenkeyLib\LootEx\profile.py`
has one composed `Profile` containing `filters`, `skin_rules`, per-item-type
`weapon_rules`, rune and weapon-mod choices, blacklist/rare-weapon state,
kits, loot range, deposit/storage settings, crafting, Nick, and other workflow
state. `LootEx/filter.py` maps broad conditions to actions such as loot, hold,
stash, sell, and salvage. A LootEx filter was therefore an action-policy
feature, not merely an item-mod predicate.

The user also narrowed the work repeatedly:

1. do not plan or revive auto inventory handling;
2. use Reforged `Item.Mods` capabilities and do not bypass its decoding;
3. the Item Mods Playground is decoder evidence, not a mandate to base work on
   Loot Filter Factory;
4. jailed JSON is a persistence requirement;
5. FrenkeyLib is not the future inventory handler, but must remain a usable
   feature base.

Those boundaries were interpreted as general architectural permissions. They
were limits, not permissions.

## D-01: Use the severance audit as a product design

**Decision.** The real findings about missing APIs, custom-build imports,
singleton handler hijacking, and broken automatic execution were treated as a
reason to shrink LootEx into a small retained presentation surface.

**Why it looked reasonable.** The automatic handler was explicitly deprecated,
and reusing its current imports would be unsafe.

**Why it was wrong.** “This executor cannot be ported unchanged” does not mean
“the feature's profiles, passive configuration, rules, or UI are retired.” The
scope exclusion was automatic inventory handling, not the whole product.

**Consequence.** A new `Widgets/Guild Wars/Items & Loot/LootEx.py` was created
as a Factory-profile selector/preview/catalogue window instead of recovering
the legacy visible workflow.

**Why tests passed.** Lifecycle tests verified the new window, not the legacy
screen set, profile operations, or intended user tasks.

**Replacement rule.** Every legacy capability must be classified as retain,
retire, replace later, or blocked. An excluded executor cannot automatically
retire its profile or UI capability.

## D-02: Convert “consume Reforged facts” into “Factory owns Frenkey verdicts”

**Decision.** Merchant's own protection and salvage predicates were declared
forbidden local matchers. Loot Filter Factory became the required verdict
owner; Merchant could retain only action intent after a Factory match.

**Why it looked reasonable.** Duplicate raw modifier parsing and private
catalogues were genuine risks. Reforged should be the source of decoded item
facts.

**Why it was wrong.** There are separate questions:

1. What decoded fact does an item have? Reforged owns this.
2. What does this Frenkey profile do with that fact? Frenkey owns this.

Calling `Item.Mods` from a Frenkey rule is not recreating a decoder. The
migration conflated a fact-provider boundary with product decision ownership.

**Consequence.** `MerchantRules.py` gained `protected_factory_rule_ids`,
`target_factory_rule_ids`, `_factory_protection_hit_reason`, Factory-only
protection/salvage paths, and `_draw_factory_rule_reference_editor`, which
explicitly sends authoring to System Settings.

**Why tests passed.** Merchant guards were written to reject every local legacy
verdict. They proved the faulty premise had been consistently enforced.

**Replacement rule.** Replace raw fact reads with public Reforged facts. Do
not replace a feature's own decision graph unless a separate product decision
explicitly transfers that graph.

## D-03: Select Loot Filter Factory as a universal profile platform

**Decision.** Factory was used as Merchant's canonical schema, editor,
persistence target, and matcher for upgrade protections and salvage targets;
LootEx then became a Factory profile consumer.

**Why it looked reasonable.** Factory already had declarative criteria,
persistence, an editor, and matching. It appeared reusable.

**Why it was wrong.** Reuse is not ownership. A loot filter has its own
semantics. Frenkey profiles combine broad actions, specialized mod rules, and
non-filter workflow state. Factory cannot become the global rule platform just
because it can represent a subset of item criteria.

**Consequence.** New `merchant_profile_migration.py` and
`merchant_upgrade_migration.py` create Factory rules from Merchant fields.
Factory's model/matcher/config UI were expanded with upgrades, effects,
inscribability, and directional criteria to absorb this work.

**Why tests passed.** They prove deterministic and bind-safe conversion, never
whether Factory was the right domain model.

**Replacement rule.** Before consuming any platform as a schema/editor, prove
domain fit: semantics, authoring, scope, lifecycle, failure behavior, and UI
must match the feature's existing contract. Otherwise consume only facts or
services.

## D-04: Make conversion redefine profiles and disable rules

**Decision.** The converter removed legacy predicate fields, created Factory
drafts/IDs, wrote `merchant_factory_upgrade_migration` audit state, and set
`enabled=False` when a mapping was rejected or Factory was unavailable.

**Why it looked reasonable.** Sell/salvage must fail safely; widening an
unsupported rule would be dangerous.

**Why it was wrong.** Execution safety was applied as data-migration policy.
The profile itself became dependent on an external global Factory and lost its
original active representation. A destructive action can be guarded without
rewriting what the user's configuration means.

**Consequence.** `_replace_rule_predicates` and
`_replace_identifier_predicates` remove source fields; deferred Factory bind
still changes in-memory enabled state around drafts/references.

**Why tests passed.** Tests asserted only that uncertain data cannot authorize
an action. They did not require lossless profile preservation, continued
authorability, or user-approved conversion.

**Replacement rule.** Separate lossless import, compatibility reporting, and
operation-time safety. No field deletion or semantic rewrite on load without a
user-approved reversible migration and profile-parity samples.

## D-05: Promote an input clarification into a cross-product rule grammar

**Decision.** The no-lambda and directional-threshold discussion was expanded
into Factory `EffectRequirement`/`UpgradeRequirement` schema, retired grammar
rejection, matcher changes, and Item.Mods input restrictions.

**Why it looked reasonable.** Opaque lambdas and arbitrary exact/range forms
should not be invented in persisted inputs.

**Why it was wrong.** This described the appropriate public input surface; it
did not authorize Factory to become the target grammar for all Frenkey
profiles. Abstract range work was done before proving a concrete missing
Reforged capability or a required legacy field.

**Consequence.** Factory schema/matcher and Merchant conversion were expanded
together, making a narrow API constraint a profile-model rewrite.

**Why tests passed.** Directional grammar tests prove the new grammar rejects
forms. They do not prove that it belongs to Frenkey profiles.

**Replacement rule.** State the exact legacy field, required Reforged fact,
and desired output first. Add only the smallest missing public capability;
never infer an editor, schema, or conversion program from an input guideline.

## D-06: Turn jailed JSON into a semantic migration

**Decision.** Profile selection, catalogues, audits, and state were moved into
new `JsonFactory` documents and `json/Defaults` records while their model was
also changed to Factory-linked data.

**Why it looked reasonable.** Source-tree file I/O is brittle, and JSON must be
jailed.

**Why it was wrong.** A jail controls storage location and safe access, not
profile meaning, scope, or composition. Location migration and semantic
conversion were fused, making recovery much harder.

**Consequence.** New LootEx stores, Factory selection documents, catalogue
seeds, Merchant account/global wrappers, and conversion audits were created
with the semantic rewrite.

**Why tests passed.** Persistence tests verified bind, malformed input,
seeding, and locking—not behavioral equivalence of the stored profile.

**Replacement rule.** Start with `legacy schema -> same schema in jail`.
Semantic conversion needs a separate decision, reversible export, and profile
samples proving unchanged behavior.

## D-07: Replace UI while investigating entrypoints and stack safety

**Decision.** A historical LootEx GUI's lack of a direct callback was treated
as grounds for a new reduced UI. At the same time, broad ImGui
scope/persistence work changed Merchant and several retained widgets.

**Why it looked reasonable.** The old GUI had syntax/import faults, and ImGui
stacks genuinely require cleanup.

**Why it was wrong.** A broken direct script or missing callback does not state
the intended visible UX. The correct order was launcher/call-graph discovery,
screen inventory, workflow mapping, then a screen-by-screen port. Mixing UI
cleanup, persistence movement, and semantic redesign obscured every contract
change.

**Consequence.** LootEx became a reduced preview/page surface; Merchant changed
by roughly 2,618 added and 3,851 deleted lines, including Factory-reference
controls and removed legacy authoring paths.

**Why tests passed.** ImGui tests prove balanced begin/end and stored geometry,
not that users can perform the same tasks.

**Replacement rule.** Before a replacement window, document launcher,
screens, navigation, controls, saved state, profile operations, and errors.
Port one workflow at a time; do not combine UI refactor and model migration.

## D-08: Let the auto-handler exclusion erase too much feature scope

**Decision.** No auto inventory handler was correctly retained, but LootEx's
role was reduced until its profile/action behavior was redirected to Factory.

**Why it looked reasonable.** The old graph had handler hijacking, removed
APIs, custom builds, and automatic inventory operations.

**Why it was wrong.** The user excluded automatic execution, not passive
configuration, profile editing, rule construction, user-directed inspection,
or a complete feature UI.

**Consequence.** The active scope became selection/preview/catalogue display
instead of recovering passive feature behavior.

**Replacement rule.** Deprecating an executor requires a capability matrix;
each retained passive/UI capability gets an explicit port plan.

## D-09: Broaden changes before establishing a behavioral baseline

**Decision.** The migration was allowed to expand through Factory, Item.Mods,
Mark, Merchant, LootEx, persistence owners, shared ImGui helpers, and several
other widgets before a stable behavioral baseline existed. The current Native
worktree also contains JSON/settings/UI/trade changes; its manifest correctly
treats those as a separate classification problem rather than assuming every
native file belongs to this migration.

**Why it looked reasonable.** Each slice looked like a local compatibility or
cleanup fix.

**Why it was wrong.** Without a stable product baseline, every additional
cleanup increased recovery scope. Technical consistency was optimized before
product consistency.

**Consequence.** The Python worktree as observed has roughly 8,072 insertions
and 7,592 deletions in 41 tracked files plus untracked code/data/tools; it is
interleaved with user work and cannot be reset wholesale. Native has separate
dirty settings/JSON, UI, trade, and DLL changes that must be classified before
any recovery action.

**Replacement rule.** One slice may change one of fact adapter, persistence
location, profile schema, UI structure, or executor boundary. Combining two
needs an explicit compatibility matrix; three or more need separately
reviewable patches and approval.

## D-10: Report static conformance as migration progress

**Decision.** Passing syntax, type, persistence, conversion, boundary, and UI
scope tests was described as source cutover, with runtime acceptance left as a
final gate.

**Why it looked reasonable.** The checks were real and useful technical tests.

**Why it was wrong.** They were written after the product model had changed.
They could prove only consistent implementation of the wrong model. The
missing proof was legacy profile/UI parity.

**Consequence.** Existing plans and test names describe Factory-led cutover as
migration success; they are now historical evidence, not authority.

**Replacement rule.** Every migration claim needs two proofs: product parity
against agreed behavior and technical correctness of the Reforged port.
Neither substitutes for the other.

## Causal chain

```text
broken legacy executor/imports
  -> severance treated as product retirement
  -> Reforged facts treated as Factory verdict ownership
  -> Factory used as schema/editor/matcher
  -> profiles converted or disabled
  -> UI rebuilt around Factory references
  -> tests prohibit original workflow
  -> green source checks for a different product
```

The replacement sequence is the reverse:

```text
recover profile and UI workflows
  -> distinguish action filters, specialized rules, facts, and actions
  -> adapt only concrete raw fact reads through Reforged APIs
  -> move unchanged schemas into jail
  -> port screens one workflow at a time
  -> keep executor deprecation separate
  -> test product parity before technical completion claims
```

## Non-negotiable controls for the replacement migration

1. No new owner by inference: representable does not mean owned.
2. No conversion on load: loading is observational until a reversible migration
   is explicitly approved.
3. No profile-field deletion during adaptation.
4. No UI replacement without a workflow parity inventory.
5. No boundary test may prohibit feature rules merely because they consume
   public Reforged facts.
6. No mixed-purpose patch: executor retirement, persistence relocation, model
   conversion, UI repair, and capability work remain separate.
7. No success claim before an existing user can configure and use the intended
   feature flow.
