# SYSTEM_SETTINGS_HANDOVER

Status: active handover (2026-08-13)
Scope: reworking `Py4GWCoreLib/py4gwcorelib_src/system_settings/` to comply
with the filter-domain scheme and the vocabulary it settles.
Contract: `docs/loot/redesign/filter-structure.md` — read it first; this
handover is the execution map, the contract is the authority.

## The scheme, in one breath

```
evaluation  = one declarative test over an item and its mods
filter      = a named set of evaluations, one ALL/ANY mode
filter set  = a named group of filters for one feature ("melee loot")
```

Nothing above filter set. There is **no profile layer** — scrapped by owner
decision; do not reintroduce one.

- Filters and filter sets are **global** definitions (`Widgets/System/
  LootFilterFactory.json`). Every account shares them.
- Each **feature keeps its own store, its own scopes, and its own
  selection** of a filter set. Loot selects its set, Recolor selects its set
  — separately, using the existing `Settings`/`JsonFactory` save schemes.
- A filter carries **evaluations only, no outcome**. What a match *means*
  (wanted / salvage mode / mark color / beacon) lives with the consuming
  feature, in the feature's store.
- The word **"rule" is retired** from the filter domain (it meant filter
  natively, condition→action in legacy).

## Why (the reasoning, settled)

1. **Multi-account reuse without a sharing object.** Configure a filter set
   once (global); point any number of accounts at it (per-feature,
   per-account selection). Each account configures itself once; nothing has
   to be bundled or propagated.
2. **Local/global must survive.** The account/global jail model is a hard
   project rule. A profile layer holding "everything" would have collapsed
   every setting into one shared document and made local settings obsolete —
   rejected for exactly that reason.
3. **Filter purity.** One filter must serve loot, salvage, and recolor with
   different outcomes. Outcomes on the filter (the `mark_*` legacy) make that
   impossible and leak one feature's meaning into a shared object.
4. **The profile editor would have been a selector, not an editor.** Its only
   job would have been picking a set per feature — per-feature dropdowns
   already do that where the feature already lives. A third editor and a
   third store bought nothing.
5. **One vocabulary.** "Rule" is ambiguous by construction (native vs legacy
   meaning); "profile" had three meanings in this repo (feature group,
   filter set, settings bundle). The contract removes both words from the
   shared vocabulary.

## Current compliance inventory (verified 2026-08-13)

| Feature | Status |
|---|---|
| `loot_filter_factory` | **Compliant.** `Filter`/`FilterSet` renamed, `set_N` ids minted, store reads legacy `profiles` key and writes `filter_sets`, UI says "Filter Sets". Filters are criteria only: the `mark_*` outcome fields are gone from the model (T2 done; legacy fields preserved on disk via a store shim until the live gate). |
| `loot_filters` | **Compliant.** Stores `filter_set_id`; a legacy name migrates to the id once at load; a deleted set falls back to none with a console log (T3 done). Reads no outcome, ever. |
| `recolor_beacons` | **Compliant.** Selections by id (T3); outcomes live in its own account store (`RecolorOutcomes.json`, `filter_id → outcome`) with a silent one-time import of the legacy `mark_*` values (T2 done). |
| `agent_recolor` | Own `Rule` class (agent recolor rules — a different domain object, criteria + color). **Settled 2026-08-13: renamed** `Rule` → `AgentRule`, API `*_rule` → `*_agent_rule` (T6). |
| `title_on_map_load` | `TITLE_MAP_RULES` static mapping. **Settled 2026-08-13: renamed** `TitleMapRule`/`TITLE_MAP_RULES` → `TitleMapEntry`/`TITLE_MAP_ENTRIES` (T6). |
| `beacons`, `inventory`, `camera_smoothing`, `skillbar_plus`, `name_obfuscation`, `map_utilities`, `window_renamer`, `agent_recolor` stores | Unaffected — their settings stay per-feature. Note: `beacons/effect.py` "ground profile" and `window_renamer` "account profile" are unrelated meanings; leave them. |

## Ordered rework tasks

### T1 — stale pointers (done inline)

`loot_filter_factory/__init__.py` docstring pointed at the removed profile
plan; corrected to `docs/loot/redesign/filter-structure.md`.

### T2 — move Recolor's outcome into its own store (done 2026-08-13)

The last non-compliant piece of the filter domain.

1. `recolor_beacons/store.py` extended: account-scoped
   `JsonFactory("Widgets/System/RecolorOutcomes.json")`, mapping
   `filter_id → {recolor, color, blank, beacon, preset}` (`MarkOutcome` in
   `recolor_beacons/model.py`). DONE.
2. `recolor_beacons/controller.py`: `resolve()` reads outcomes from the
   account store; `marking_filters()` is "filters with a stored outcome that
   marks". DONE.
3. Factory `model.py`: the `mark_*` fields, `marks()` and the
   `TODO(compliance)` note are deleted -- a filter no longer knows what it
   marks. The factory store keeps a migration bridge: `legacy_mark_entries()`
   reads the raw legacy fields, and `save_filters` merges them back by id
   (preserve-on-save shim) so no account loses data before the live gate.
   DONE.
4. UI: the factory filter editor had no outcome controls to remove; Recolor's
   "Outcomes" tab now edits this account's store instead of rewriting
   filters. DONE.
5. One-time data import: `load_outcomes()` copies the legacy `mark_*` values
   into this account's store on first load, keyed by filter id -- silent,
   idempotent, and ids already present are NEVER overwritten (a cleared
   outcome cannot resurrect). Legacy fields stay readable on disk until the
   live gate. DONE.
6. Acceptance: a filter in two filter sets carries one outcome per Recolor
   configuration; Loot Filters never reads any outcome; Pyright clean;
   offline fixture `test_recolor_outcomes.py` passes. Live gate pending.

### T3 — selections by id, per feature (done 2026-08-13)

Both features now store the selected filter-set **id** -- with the least
persistence churn possible. The INI key does not move: `general/profile` still
holds the selection in the same documents and scopes; only the VALUE changed
from a filter-set NAME to its id.

1. `loot_filters/store.py` + `model.py`: the value under the existing key is
   resolved at load -- an id wins, a legacy name is adopted into its id once
   and written back to the SAME key (idempotent, silent: the value being an
   id is its own migration state, no markers), and a value matching nothing
   falls back to none **in memory** (never rewritten, so a transiently
   unreadable filter pool cannot destroy a valid selection) with a console
   log. DONE.
2. `recolor_beacons/store.py` + `model.py`: same, account scope. DONE.
3. UI labels: "Profile" → "Filter set" in both sections. DONE.
4. Integrity: on filter-set rename nothing breaks (ids stable); on delete,
   the factory's change notification already refreshes consumers — selections
   referencing the deleted id fall back to none with a console log. The
   shared pure resolver is `resolve_filter_set_selection` in the factory
   store; offline fixtures `test_filter_set_selection.py` and
   `test_settings_migration.py`. DONE.
5. Acceptance: rename a set, both features keep running it; delete it, both
   fall back; Pyright clean; documents stay in the jails. Offline-verified;
   live gate pending.

### T4 — `min_damage` defect (pre-existing) (done 2026-08-13)

The criterion passed lambdas to `Item.Mods.HasMod`, which rejects callables
(`TypeError` → criterion always failed). Fixed: compare the range's top end
via `Item.Mods.GetValues(item_id, ModifierIdentifier.Damage)` against
`min_damage`; offline matcher fixture `test_loot_filter_matcher.py` (verdict
+ breakdown, and the stub's `HasMod` raises on callables so a regression to
the lambda path fails loudly). DONE; live gate pending.

### T5 — filter model growth (when salvage/identify features start)

Spec'd in the contract's "Extension beyond looting": one generic effect
criterion `(mod, subtype?, threshold?)` through `Item.Mods.HasMod`, plus an
upgrade criterion family `(name, slot?)` / `maxed` through `GetUpgrades`/
`IsMaxed`. Additive only — the model and matcher are built for it. Do NOT
start before the feature that needs it exists.

### T6 — naming follow-ups (settled 2026-08-13: renamed, identifiers only)

- `agent_recolor.Rule`: criteria + outcome over agents, a different domain
  than item filters. Renamed `Rule` → `AgentRule`, and the rule API follows
  (`load_rules` → `load_agent_rules`, `rules()` → `agent_rules()`,
  `new_rule` → `new_agent_rule`, `update_rule` → `update_agent_rule`,
  `remove_rule`/`duplicate_rule`/`move_rule`/`clear_rules` →
  `*_agent_rule`, `rules_for_scope` → `agent_rules_for_scope`). Persisted
  data untouched (the `rules`/`list` INI key and the JSON shape stay).
- `title_on_map_load`: `TitleMapRule` → `TitleMapEntry`,
  `TITLE_MAP_RULES` → `TITLE_MAP_ENTRIES`.

## Data migration summary (all one-time, all idempotent)

| From | To | When |
|---|---|---|
| factory doc key `profiles` | `filter_sets` | done (read fallback kept) |
| filter-set selection by name | selection by id | done (2026-08-13; value-level, same key, silent) |
| `Filter.mark_*` | `Widgets/System/RecolorOutcomes.json` | done (2026-08-13; per-account, silent, idempotent; legacy fields kept readable until live gate) |
| (deferred elsewhere) ported ItemManager configs | native features | extraction phase |

Never delete legacy data during a migration step — keep the old keys/fields
readable until the live gate passes.

## Verification gates

- Strict Pyright over every touched package; `compileall` — both must pass.
- Offline fixtures: `test_filter_set_selection.py` (name→id import idempotent,
  rename/delete integrity with fallback message), `test_settings_migration.py`
  (the real stores against in-memory Settings/JsonFactory: adoption in the
  same key, rename survival, in-memory fallback, no resurrection),
  `test_recolor_outcomes.py` (outcome round-trip, silent idempotent import,
  never-overwrite, preserve-on-save) and `test_loot_filter_matcher.py`
  (matcher damage-range verdict + breakdown) — all run offline and pass.
- Live client: two features select different sets; outcomes edit in Recolor's
  section; the legacy import happens once per account; selections and
  outcomes survive reload; every document under `settings/` or `json/` only.

## Boundary discipline (read before starting)

This is the **native `Item.Mods` / system-settings side**. FrenkeyLib's own
mod handling (`item_mods_src`, ported `global_configs`) is a separate legacy
domain that migrates onto `Item.Mods` eventually — tracked in
`docs/architecture/records/reforged-migration/`. Do not fold frenkeyLib
rework into these tasks, and do not move this work back into the migration
records.
