# Filter Structure Contract

Status: active contract (2026-08-13)
Scope: the native filter system built on `Item.Mods` — the Loot Filter Factory,
Loot Filters, Recolor & Beacons, and the future salvage/identify features.
This is **not** a FrenkeyLib migration record: FrenkeyLib's own mod handling
is a separate legacy domain that migrates *onto* `Item.Mods` eventually (see
the reforged-migration records).
Authority: current sources `system_settings/loot_filter_factory/{model,store,matcher,config_ui}.py`,
`system_settings/loot_filters/{store,controller}.py`,
`system_settings/recolor_beacons/{store,controller}.py`,
`Py4GWCoreLib/{Item.py,mods_core.py,mods_types.py}` (`Item.Mods` surface), and
`Py4GWCoreLib/py4gwcorelib_src/JsonFactory.py` (scopes)

## Profile concept scrapped (2026-08-13)

Earlier drafts designed a **profile** object grouping features (loot +
salvage + recolor + beacons) with a profile editor. That concept is scrapped
by owner decision:

- There is **no profile layer, no profile store, no profile editor.**
- Filters and filter sets are **global** definitions; each account selects
  which filter set a feature runs, **per feature, in that feature's own
  store** — exactly the save scheme the system already has.
- Each account configures itself once; nothing bundles features together.
- "Melee" is simply the name of filter sets an account points its features
  at. Reuse is per set, per feature, never through a shared profile object.

Do not reintroduce a profile layer: the feature-owned, per-scope stores are
the settled mechanism.

## Ontology (settled)

```
filter set  = a named group of filters for one feature ("melee loot")
filter      = a named set of evaluations, one ALL/ANY mode
evaluation  = one declarative test (type, rarity, name, value, requirement,
              damage, dye, salvages-into, upgrade-in-slot, ...)
```

- A **filter** is pure evaluations and carries **no outcome** — the same
  filter can serve loot, salvage, and recolor with different outcomes. The
  outcome lives with the feature that consumes the filter, in the feature's
  own store.
- The word **"rule" is retired** from the shared vocabulary: natively it meant
  filter, in legacy it meant condition→action. Ambiguous by default, so it
  goes. Settled follow-up (2026-08-13): the unrelated domain objects were
  renamed with their domain prefix instead of keeping the bare word --
  `agent_recolor.Rule` → `AgentRule` (with its `*_rule` API → `*_agent_rule`)
  and `title_on_map_load.TITLE_MAP_RULES` → `TITLE_MAP_ENTRIES`. Persisted
  data is untouched: only identifiers changed.

## Mapping to the current code

| Layer | Current code | Change |
|---|---|---|
| evaluation | factory filter criteria (item_types, rarities, max_requirement, ...) | name only; vocabulary grows beyond the drop-visible subset |
| filter | factory `Filter` (renamed from `Rule`) | done; outcome moved to Recolor's own account store |
| filter set | factory `FilterSet` (renamed from `Profile`), stable `set_N` ids | done; feature selections migrate name→id |

The two live consumers (Loot Filters, Recolor & Beacons) keep their own
per-feature stores and selections. Selections now store filter-set **ids**
(legacy names migrate once at load) with rename/delete integrity -- a deleted
set falls back to none with a console log.

## Scope axis

Filters and filter sets are **global** definitions — shared across accounts,
exactly as today. Feature selections and toggles stay per-account (or global
where the feature's design says so, e.g. the machine-wide loot policy). The
account/global jail model is untouched; nothing here makes local settings
obsolete.

## Extension beyond looting (filter capability, verified)

- Today's filter carries three mod criteria (requirement, damage, damage
  type) — a deliberate subset of the ~60 effect identifiers in
  `mods_core._EFFECT`, closed to what is visible on an unidentified drop.
- The architecture extends cleanly: one generic effect criterion
  (`(mod, subtype?, threshold?)` evaluated through `Item.Mods.HasMod`) and one
  upgrade criterion family (`(name, slot?)` + `maxed`, evaluated through
  `GetUpgrades`/`IsMaxed`) cover the whole `Item.Mods` class.
- Features on identified items (salvage, identify, mod hunting) reuse the same
  filter model with a different evaluation context; the outcome difference is
  exactly what each feature's own store owns.

## Compliance status

Executed (2026-08-13):

- Renamed across the factory and both consumers: `Rule` → `Filter`,
  `Profile` → `FilterSet`, `load_rules`/`save_rules` → `load_filters`/
  `save_filters`, `load_profiles`/`save_profiles` → `load_filter_sets`/
  `save_filter_sets`, `profile_by_name` → `filter_set_by_name`,
  `rules_in_profile` → `filters_in_set`, `matching_rules` →
  `matching_filters`; UI tabs and labels follow ("Filter Sets").
- Filter sets now carry stable ids (`set_N`) minted by `next_filter_set_id`;
  the store reads the legacy `profiles` document key and writes `filter_sets`.
- Feature selections by id, with the least persistence churn possible: both
  features keep the SAME INI key (`general/profile`) and only the VALUE moved
  from a filter-set NAME to its id. A stored name is adopted into its id once
  at load (written back to the same key, idempotent, silent -- the value being
  an id is its own migration state, no markers); rename propagates because ids
  are stable; a value matching no set falls back to none **in memory** (the
  document is not rewritten, so a transiently unreadable filter pool cannot
  destroy a valid selection) with a console log. The shared pure resolver is
  `resolve_filter_set_selection` in the factory store; offline fixtures
  `Examples and tests/tests/test_filter_set_selection.py` and
  `Examples and tests/tests/test_settings_migration.py`.
- `min_damage` defect fixed: the criterion now compares the damage range's top
  end through `Item.Mods.GetValues` instead of passing lambdas to `HasMod`;
  offline fixture `Examples and tests/tests/test_loot_filter_matcher.py`.

- `mark_*` relocation: a filter is now criteria only. Recolor & Beacons owns
  the outcome in its own account store
  (`Widgets/System/RecolorOutcomes.json`, `filter_id → outcome`); the factory
  editor has no outcome controls. The pre-contract `mark_*` fields were
  imported once per account, silently and idempotently (ids already present
  are never overwritten, so a cleared outcome cannot resurrect); the factory
  document keeps the legacy fields readable via a preserve-on-save shim until
  the live gate removes the bridge. Offline fixture
  `Examples and tests/tests/test_recolor_outcomes.py`.

- `agent_recolor` and `title_on_map_load` naming follow-ups settled: `Rule` →
  `AgentRule` (API `*_rule` → `*_agent_rule`), `TitleMapRule`/`TITLE_MAP_RULES`
  → `TitleMapEntry`/`TITLE_MAP_ENTRIES` -- identifiers only, no persisted data
  touched.

Remaining: nothing. Deferred model growth (the effect/upgrade criteria of the
"Extension beyond looting" section) starts when a salvage/identify feature
needs it, not before.

## Verification gates

- Strict Pyright over the factory and both consumers (clean as of the
  compliance pass).
- Offline fixtures: selection name→id adoption, rename/delete integrity, the
  outcome round-trip with its one-time import, and the matcher damage-range
  regression are covered by
  `Examples and tests/tests/test_filter_set_selection.py`,
  `Examples and tests/tests/test_settings_migration.py`,
  `Examples and tests/tests/test_recolor_outcomes.py` and
  `Examples and tests/tests/test_loot_filter_matcher.py` (all run offline,
  no client).
- Live client: filter sets selectable per feature; selections survive reload;
  documents stay in the jails.
