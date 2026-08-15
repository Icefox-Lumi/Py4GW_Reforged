# Native Profile System Plan

Status: proposed (draft v5, portability criterion)
Authority: current sources `system_settings/loot_filter_factory/{model,store,matcher,config_ui}.py`,
`system_settings/loot_filters/{store,controller}.py`,
`system_settings/recolor_beacons/{store,controller}.py`,
`system_settings/agent_recolor/`, `system_settings/inventory/`, the ported
`Sources/frenkeyLib/global_configs/` feature set, and
`Sources/frenkeyLib/MultiBoxing/settings.py`

## The membership rule

A profile exists for **portability of configuration that is hard or elaborate
to reproduce**. The test for any setting:

> Would re-doing this by hand on another account annoy me?

- Yes → profile content. Filters, hand lists of model ids, recolor mappings,
  rule sets, sort groups, layouts.
- No → stays per-account. Master switches, toggles, sliders, simple
  preferences.

Neither extreme: not everything is profile-scoped, and it is not a two-feature
gimmick — every elaborate configuration joins by the same rule.

## Concept

1. **Profile** — evolves from the factory's `Profile{name, filter_ids}` into
   `{id, name, sections: {filters: [...], loot: {...}, mark: {...}, rules: {...},
   sort: {...}, ...}}`. A section exists only for features that opted in; a
   profile with only the filters section is exactly today's filter set. Global
   definitions: authored once, portable across accounts. Editing is
   edit-in-place — the profile is shared, personal divergence means another
   profile.
2. **Selection** — per account, the active profile **id**. Loot's and
   Recolor's name-string selections collapse into this one selection.
3. **Simple settings** — per-feature, per-account, exactly as today (loot
   rarity toggles stay account-local; master switches stay account-local).
4. **Live/session state** — never in profiles (script additions, loot locks,
   transient UI state).
5. **Default profile** — built-in, not deletable; new accounts start on it.

## Why the factory object, not a new system

- The factory already owns global authored definitions with id minting and a
  change-notification pattern; its `Profile` is the same concept, one section
  short of general.
- The two live consumers already select it — migrating them to id-based
  selection is the same work either way.
- No rename campaign ("filter set" vs "profile") is needed: a filter set is a
  profile whose only section is filters.

## Candidate sections (by the criterion)

| Section | Content | Today |
|---|---|---|
| `filters` | ordered filter ids (the factory's filter sets) | factory `Profile.filter_ids` |
| `loot` | hand lists (model ids, dyes, salvage targets) — the elaborate lists | per-account/global in `LootFiltersSelections.json` |
| `mark` | filter → color/blank/beacon/preset mappings | `mark_*` fields on factory rules |
| `rules` | inventory processing rule sets (future extraction) | ported `global_configs` |
| `sort` | sort groups + custom orders (future extraction) | ported `SortingConfig` |
| `agents` | agent recolor schemes (mappings) | `agent_recolor` store — candidate, pending its shape |
| `layouts` | window arrangements | MultiBoxing layouts — candidate later |
| not in scope | camera, name obfuscation, skillbar+, window renamer, title-on-map-load | simple preferences; stay per-account |

Rarity toggles and similar cheap switches deliberately stay out even where
their feature has a section — the criterion is per-setting, not per-feature.

## Storage and selection

- Profiles: global `JsonFactory` document (name recorded at implementation),
  sections written by their owning features through the core.
- Selection: account-scoped document holding the active profile id.
- The core resolves `feature → section values` for the active profile; the
  owning feature remains the only interpreter of its section (schema, live
  application, native push). The core never understands a section's content.

## Migration

1. Give factory profiles stable ids (minting exists for rules; reuse it).
2. Core selection service: account-scoped id selection; integrity — rename
   propagates, delete falls back to Default with a console log.
3. Loot Filters and Recolor & Beacons switch from name-string selections to
   id-based selection through the core; `mark_*` fields move into the `mark`
   section one time (import).
4. Per-account elaborate lists (loot hand lists) import into the active
   profile's `loot` section one time; simple toggles stay.
5. New sections join as features are extracted; the ported per-character
   profile machinery is retired then.

## Verification gates

- Strict Pyright over the core and both migrated consumers.
- Offline fixtures: id minting; section round-trips; rename propagates; delete
  falls back; absent sections leave features on their account-local settings.
- Live client: switching profiles changes filters, hand lists, and marking
  together; toggles stay account-local; selection survives reload; documents
  stay in the jails.

## Open decisions

- `agents` (agent recolor schemes) in the first wave, or join later?
- One profile per account confirmed (no per-character selection in v1)?
- Edit-in-place shared profiles confirmed (the criterion implies it — the
  whole point is one authored thing, many accounts)?

## Relationship to prior records

Extends `frenkeylib-boundary-compliance-plan.md` (jailed persistence is the
substrate). Supersedes the v2-v4 drafts in this file and the source-less
`item_profiles` attempt.
